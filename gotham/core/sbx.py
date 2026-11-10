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
import threading
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from . import config

CURRENT_TASK: ContextVar[str] = ContextVar('gotham_current_task', default='')

MAX_OUT = 20000
WORKSPACE_LIMIT_MB = int(os.environ.get('GOTHAM_WORKSPACE_LIMIT_MB', '256'))
ROOT = Path(__file__).resolve().parents[2]
IMAGE_FILES = {'gotham-lab-target:latest': 'docker/lab_target.Dockerfile', 'gotham-sandbox:latest': 'docker/sandbox.Dockerfile', 'gotham-research:latest': 'docker/research.Dockerfile'}


def dir_size(path) -> int:
    total = 0
    stack = [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        try:
                            total += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
        except OSError:
            pass
    return total


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


def ca_bundle_bytes() -> bytes:
    """Optional extra CA (TLS-inspecting proxy). Any problem reading it (missing, unreadable by this uid) means 'no extra CA', never a crash."""
    ca = os.environ.get('GOTHAM_BUILD_CA_BUNDLE', '')
    if not ca:
        return b''
    try:
        return Path(ca).read_bytes()
    except OSError:
        return b''


def usable_ca_path() -> Path | None:
    ca = os.environ.get('GOTHAM_BUILD_CA_BUNDLE', '')
    try:
        return Path(ca) if ca and Path(ca).is_file() and os.access(ca, os.R_OK) else None
    except OSError:
        return None


_ENSURE_LOCK = threading.Lock()


def ensure_image(image: str) -> None:
    if image_present(image):
        return
    with _ENSURE_LOCK:                 # concurrent tasks must not build the same image twice
        if image_present(image):
            return
        _build_image(image)


def _build_image(image: str) -> None:
    df = IMAGE_FILES.get(image)
    if not df:
        raise SandboxError(f'Image {image} is not present and has no build recipe')
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory(prefix='gotham-build-') as ctx:
        ctx = Path(ctx)
        shutil.copytree(ROOT / 'docker', ctx, dirs_exist_ok=True)
        shutil.copy(ROOT / df, ctx / 'Dockerfile')
        (ctx / 'ca.crt').write_bytes(ca_bundle_bytes())
        for attempt in range(1, 4):
            r = subprocess.run(['docker', 'build', '-q', '-t', image, str(ctx)], capture_output=True, text=True, timeout=1500)
            transient = re.search(r'(?i)429|toomanyrequests|timeout|timed out|temporary failure|connection (reset|refused)|TLS|EOF|503|502', r.stderr)
            if r.returncode == 0 or not transient:
                break
            time.sleep(5 * attempt)      # registry rate-limit / network blip: back off and retry (max 3 attempts)
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
    if image in IMAGE_FILES:
        ensure_image(image)            # managed images are built on demand: callers never depend on an earlier step
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
    quota_killed = False
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tails = {'out': bytearray(), 'err': bytearray()}
    counts = {'out': 0, 'err': 0}

    def drain(stream, key):
        # Bounded memory: keep only the tail, count the rest. A container printing gigabytes cannot exhaust the worker.
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            counts[key] += len(chunk)
            buf = tails[key]
            buf += chunk
            if len(buf) > MAX_OUT * 4:
                del buf[:len(buf) - MAX_OUT * 2]

    threads = [threading.Thread(target=drain, args=(proc.stdout, 'out'), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, 'err'), daemon=True)]
    [t.start() for t in threads]
    stop_watch = threading.Event()

    def watchdog():
        # Disk quota for the bind-mounted workspace: sandboxed code must not be able to fill the host disk.
        nonlocal quota_killed
        limit = WORKSPACE_LIMIT_MB * 1024 * 1024
        while not stop_watch.wait(0.5):
            if dir_size(mount) > limit:
                quota_killed = True
                subprocess.run(['docker', 'kill', name], capture_output=True, timeout=15)
                return
    if mount is not None and rw:
        threading.Thread(target=watchdog, daemon=True).start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)
        proc.kill()
        proc.wait(timeout=10)
    finally:
        stop_watch.set()
    [t.join(timeout=5) for t in threads]
    out = tails['out'][-MAX_OUT:].decode('utf-8', 'replace')
    err = tails['err'][-MAX_OUT:].decode('utf-8', 'replace')
    code = 124 if timed_out else proc.returncode
    destroyed = _destroyed(name)
    if code == 125:
        raise SandboxError('Docker could not start container: ' + (err or out)[:300])
    return {'sandbox': 'docker', 'image': image, 'network': (network if isinstance(network, str) else 'bridge') if network else 'none', 'exit_code': code,
            'timed_out': timed_out, 'quota_killed': quota_killed, 'output_bytes': counts['out'] + counts['err'],
            'container_destroyed': destroyed, 'stdout': out[-MAX_OUT:], 'stderr': err[-MAX_OUT:],
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
