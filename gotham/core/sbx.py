"""Hardened one-shot Docker execution used by every tool that runs untrusted code.

Defaults: no network, read-only root fs, all capabilities dropped, non-root, no-new-privileges,
pids/memory/cpu limits, only the task workspace mounted. Every run is labelled for cleanup and the
result records whether the container was verifiably destroyed.
"""
from __future__ import annotations
import hashlib
import os
import re
import subprocess
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from . import config

CURRENT_TASK: ContextVar[str] = ContextVar('gotham_current_task', default='')

MAX_OUT = 20000
ROOT = Path(__file__).resolve().parents[2]
IMAGE_FILES = {'gotham-lab-target:latest': 'docker/lab_target.Dockerfile', 'gotham-sandbox:latest': 'docker/sandbox.Dockerfile', 'gotham-research:latest': 'docker/research.Dockerfile'}


class SandboxError(RuntimeError):
    pass


def docker_available() -> bool:
    try:
        return subprocess.run(['docker', 'info'], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def image_present(image: str) -> bool:
    try:
        return subprocess.run(['docker', 'image', 'inspect', image], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_image(image: str) -> None:
    if image_present(image):
        return
    df = IMAGE_FILES.get(image)
    if not df:
        raise SandboxError(f'Image {image} is not present and has no build recipe')
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory(prefix='gotham-build-') as ctx:
        ctx = Path(ctx)
        shutil.copytree(ROOT / 'docker', ctx, dirs_exist_ok=True)
        shutil.copy(ROOT / df, ctx / 'Dockerfile')
        ca = os.environ.get('GOTHAM_BUILD_CA_BUNDLE', '')
        (ctx / 'ca.crt').write_bytes(Path(ca).read_bytes() if ca and Path(ca).is_file() else b'')
        r = subprocess.run(['docker', 'build', '-q', '-t', image, str(ctx)], capture_output=True, text=True, timeout=1500)
    if r.returncode != 0:
        raise SandboxError('Image build failed: ' + r.stderr[-400:])


def _destroyed(name: str) -> bool:
    try:
        r = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True, text=True, timeout=10)
        if r.returncode != 0 and ('No such object' in r.stderr or 'No such container' in r.stderr):
            return True
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)
        return False
    except (OSError, subprocess.TimeoutExpired):
        return False


def open_workspace(path: Path) -> None:
    """The sandbox user is uid 65534: grant it access to the (already isolated) task workspace only."""
    for p in [path, *path.rglob('*')]:
        if p.is_symlink():
            continue
        try:
            p.chmod(p.stat().st_mode | 0o777 if p.is_dir() else p.stat().st_mode | 0o666)
        except OSError:
            pass


def run(image: str, cmd: list[str], *, mount: Path | None = None, rw: bool = False, network: bool | str = False,
        timeout: int = 60, memory: str = '256m', cpus: str = '1', pids: int = 128, env: dict | None = None,
        ro_mounts: list[tuple[Path, str]] | None = None, tmpfs: str = '64m') -> dict:
    if not docker_available():
        raise SandboxError('Docker daemon unavailable; refusing to execute untrusted code on the host')
    name = 'gotham-' + uuid.uuid4().hex[:16]
    args = ['docker', 'run', '--rm', '--name', name, '--label', 'gotham=1', '--label', f'gotham-task={CURRENT_TASK.get()}', '--pull=never',
            '--network', (network if isinstance(network, str) else 'bridge') if network else 'none', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', f'--pids-limit={pids}', f'--memory={memory}',
            f'--memory-swap={memory}', f'--cpus={cpus}', '--user=65534:65534',
            f'--tmpfs=/tmp:rw,nosuid,size={tmpfs}', '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1']
    for k, v in (env or {}).items():
        args += ['-e', f'{k}={v}']
    if mount is not None:
        open_workspace(mount)
        args += ['--mount', f'type=bind,src={mount},dst=/work' + ('' if rw else ',readonly'), '--workdir=/work']
    for src, dst in (ro_mounts or []):
        args += ['--mount', f'type=bind,src={src},dst={dst},readonly']
    args += [image, *cmd]
    t0 = time.monotonic()
    timed_out = False
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, errors='replace')
        out, err, code = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        out = (e.stdout.decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or ''))
        err = (e.stderr.decode(errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or ''))
        code = 124
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)
    destroyed = _destroyed(name)
    if code == 125:
        raise SandboxError('Docker could not start container: ' + (err or out)[:300])
    return {'sandbox': 'docker', 'image': image, 'network': (network if isinstance(network, str) else 'bridge') if network else 'none', 'exit_code': code,
            'timed_out': timed_out, 'container_destroyed': destroyed, 'stdout': out[-MAX_OUT:], 'stderr': err[-MAX_OUT:],
            'elapsed_ms': round((time.monotonic() - t0) * 1000), 'read_only_root': True, 'cap_drop': 'ALL',
            'cmd_sha256': hashlib.sha256(' '.join(cmd).encode()).hexdigest()}


def cleanup_stale(older_than_minutes: int = 30) -> list[str]:
    """Remove leaked gotham-labelled containers: any exited/created one, or running longer than the limit."""
    removed = []
    try:
        r = subprocess.run(['docker', 'ps', '-a', '--filter', 'label=gotham=1', '--filter', 'label!=gotham-lab=1',
                            '--format', '{{.ID}}\t{{.Status}}'], capture_output=True, text=True, timeout=15)
        for line in r.stdout.splitlines():
            cid, _, status = line.partition('\t')
            stale = status.startswith(('Exited', 'Created', 'Dead'))
            m = re.match(r'Up (\d+) (minute|hour|day)', status)
            if m and (m.group(2) != 'minute' or int(m.group(1)) >= older_than_minutes):
                stale = True
            if stale:
                subprocess.run(['docker', 'rm', '-f', cid], capture_output=True, timeout=15)
                removed.append(cid)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return removed


def remove_task_containers(task_id: str) -> list[str]:
    """Kill containers orphaned by a crashed worker for this task (used during lease recovery)."""
    removed = []
    try:
        r = subprocess.run(['docker', 'ps', '-aq', '--filter', f'label=gotham-task={task_id}'], capture_output=True, text=True, timeout=15)
        for cid in r.stdout.split():
            subprocess.run(['docker', 'rm', '-f', cid], capture_output=True, timeout=20)
            removed.append(cid)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return removed
