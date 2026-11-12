"""Startup/readiness checks. Misconfiguration (wrong uid, read-only dir, no Docker) must fail FAST with an actionable message,
not surface later as an opaque HTTP 500 or a mission that silently never runs."""
from __future__ import annotations
import os
import shutil
import tempfile
from pathlib import Path

from . import auth, config, sbx


def _writable_dir(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix='.gotham-preflight-'):
            pass
        return True, 'writable'
    except OSError as exc:
        return False, f'{exc.strerror or exc} (process uid={os.geteuid()}, dir owner uid={_owner(path)})'


def _owner(path: Path):
    try:
        return path.stat().st_uid
    except OSError:
        return '?'


def _file_access(path: Path) -> tuple[bool, str]:
    try:
        exists = path.exists()
    except OSError as exc:     # e.g. a parent directory the process may not traverse
        return False, f'{exc.strerror or exc}: cannot reach {path} as uid={os.geteuid()}; run API and worker as the SAME uid (GOTHAM_UID) or fix directory permissions'
    if not exists:
        return True, 'not created yet'
    ok = os.access(path, os.R_OK | os.W_OK)
    return ok, 'read/write ok' if ok else f'not readable/writable by uid={os.geteuid()} (owner uid={_owner(path)}); run API and worker as the SAME uid (GOTHAM_UID) or chown the directory'


def run(role: str = 'worker') -> list[dict]:
    out = []

    def add(name, ok, detail, level='fail'):
        out.append({'name': name, 'status': 'ok' if ok else level, 'detail': detail})
    try:
        ok, d = _writable_dir(config.data_dir())
    except OSError as exc:
        ok, d = False, f'{exc.strerror or exc}'
    add('data_dir_writable', ok, d)
    audit = config.audit_path()
    ok, d = _writable_dir(audit.parent)
    add('audit_dir_writable', ok, d)
    for label, f in (('audit_db_access', audit), ('audit_key_access', audit.with_suffix('.key')), ('store_db_access', config.store_path())):
        ok, d = _file_access(f)
        add(label, ok, d)
    try:
        if config.data_dir() in audit.resolve().parents:
            add('audit_outside_data_dir', False, 'audit journal is inside the data dir that workers/workspaces can reach', 'warn')
        else:
            add('audit_outside_data_dir', True, 'separate directory')
    except OSError:
        pass
    docker = sbx.docker_available()
    add('docker_daemon', docker, 'available' if docker else 'unavailable: sandboxed tasks will fail closed', 'fail' if role == 'worker' else 'warn')
    if docker:
        for img in ('gotham-sandbox:latest', config.RESEARCH_IMAGE, 'gotham-lab-target:latest'):
            present = sbx.image_present(img)
            add(f'image {img}', present, 'present' if present else 'missing: built on first use (research image takes ~10 min)', 'warn')
    try:
        free = shutil.disk_usage(config.data_dir()).free / 1e9
        add('disk_free', free > 2, f'{free:.1f} GB free', 'warn' if free > 0.5 else 'fail')
    except OSError as exc:
        add('disk_free', False, f'cannot stat data dir: {exc}', 'warn')
    if role == 'api':
        roles = auth.configured_roles()
        add('auth_tokens', roles['batman'] and roles['operator'], f'configured roles: {roles}', 'warn')
    return out


def failed(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c['status'] == 'fail']
