"""Failure-injection tests: every case here corresponds to a row in docs/GOTHAM_FAILURE_MODES.md."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gotham.core import api as v4, config, sbx
from gotham.core import engine as E
from gotham.core import tools as T
from gotham.core.audit import AuditReader
from gotham.core.engine import Alfred
from gotham.core.store import Store
from tests.conftest import needs_docker, run_until_done
from tests.fixtures import AUTH_LOG, BUGGY_PROJECT, FIX_PATCH

ROOT = Path(__file__).parents[1]
CHEAP = {'files': {'auth.log': AUTH_LOG}, 'log': 'auth.log'}


def spawn_worker(lease='30', conc='2'):
    env = {**os.environ, 'GOTHAM_LEASE_SECONDS': lease, 'GOTHAM_WORKER_CONCURRENCY': conc}
    return subprocess.Popen([sys.executable, '-m', 'gotham.core.worker'], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for(pred, timeout=60, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def acts(mid):
    return [e['action'] for e in AuditReader(config.audit_path()).events(mid, limit=5000)]


# FM-01 concurrent finalization
def test_concurrent_advance_finalizes_exactly_once(alfred, monkeypatch):
    mid = alfred.submit('log_analysis', 'finalize race probe', CHEAP, 'test')
    orig = E.Alfred.advance
    E.Alfred.advance = lambda self, m: None          # suppress per-task advance so the finalize race is isolated
    try:
        run_until_done(alfred)
    finally:
        E.Alfred.advance = orig
    ths = [threading.Thread(target=alfred.advance, args=(mid,)) for _ in range(16)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert acts(mid).count('mission_finalized') == 1
    assert alfred.store.get_mission(mid)['status'] == 'verified'


def test_stale_finalizing_is_reset_by_recovery(alfred):
    s = alfred.store
    mid = alfred.submit('log_analysis', 'wedge probe', CHEAP, 'test')
    assert s.begin_finalize(mid) and s.get_mission(mid)['status'] == 'finalizing'
    assert s.reset_stale_finalizing(older_than_s=-1) == 1
    assert s.get_mission(mid)['status'] == 'running'
    assert not s.begin_finalize('nonexistent')


# FM-02 poisoned inputs
def test_seed_path_traversal_and_absolute_paths_are_refused(alfred, env):
    for bad in ('../../escape.txt', '/tmp/gotham_abs_escape.txt'):
        mid = alfred.submit('security_audit', 'path injection probe', {'files': {bad: 'pwned'}}, 'test')
        run_until_done(alfred)
        assert alfred.store.get_mission(mid)['status'] == 'failed'
    assert not list(env.rglob('escape.txt')) and not Path('/tmp/gotham_abs_escape.txt').exists()


def test_malicious_params_cannot_override_workdir_or_escape(alfred, env):
    mid = alfred.submit('log_analysis', 'workdir override probe', {**CHEAP, 'workdir': '../../../etc'}, 'test')
    run_until_done(alfred)
    t = alfred.store.tasks_for(mid)[0]
    assert t['params']['workdir'] == 'logs'                         # engine, not caller, decides the workspace
    assert alfred.store.get_mission(mid)['status'] == 'verified'


def test_oversized_mission_is_rejected_before_planning(alfred):
    with pytest.raises(ValueError):
        alfred.submit('security_audit', 'huge payload probe', {'files': {'a.py': 'x' * 500_000}}, 'test')


# FM-03 infrastructure failure
def test_audit_journal_unwritable_blocks_tool_execution(env):
    class Broken:
        def record(self, *a, **k):
            raise OSError('disk full')
    store = Store(config.store_path())
    ws = config.workspaces_dir() / 'x' / 'w'
    ws.mkdir(parents=True)
    ctx = T.ToolContext('x', 't', 'Forge', ws, store, Broken())
    with pytest.raises(OSError):
        T.call(ctx, 'fs_write', {'path': 'z.txt', 'content': 'hi'})
    assert not (ws / 'z.txt').exists()                              # no audit => no action


def test_docker_down_fails_closed_without_host_execution(alfred, monkeypatch):
    monkeypatch.setattr(sbx, 'docker_available', lambda: False)
    marker = Path('/tmp/gotham_host_exec_marker')
    marker.unlink(missing_ok=True)
    project = {'test_x.py': f'def test_x():\n    open("{marker}", "w").write("host-executed")\n'}
    mid = alfred.submit('engineering', 'docker outage probe', {'files': project}, 'test')
    run_until_done(alfred)
    m = alfred.store.get_mission(mid)
    assert m['status'] == 'failed' and not marker.exists()          # nothing ran on the host
    forge = [t for t in alfred.store.tasks_for(mid) if t['agent'] == 'Forge'][0]
    assert 'Docker daemon unavailable' in (forge['error'] or '') and forge['attempts'] == 2   # bounded retry then fail


def test_retry_exhaustion_fails_mission_instead_of_hanging(alfred, monkeypatch):
    def boom(ctx, p):
        raise RuntimeError('simulated tool crash')
    monkeypatch.setitem(E.PLAYBOOKS, ('Sentinel', 'log_analysis'), boom)
    mid = alfred.submit('log_analysis', 'crash loop probe', CHEAP, 'test')
    run_until_done(alfred)
    t = alfred.store.tasks_for(mid)[0]
    assert t['status'] == 'failed' and t['attempts'] == 2 and alfred.store.get_mission(mid)['status'] == 'failed'
    assert 'task_retry_scheduled' in acts(mid) and 'task_failed' in acts(mid)


def test_hung_task_stops_renewing_lease_and_is_reclaimed(alfred, monkeypatch):
    monkeypatch.setattr(config, 'LEASE_SECONDS', 1)
    monkeypatch.setattr(config, 'HEARTBEAT_GRACE_S', 0)
    release = threading.Event()
    monkeypatch.setitem(E.PLAYBOOKS, ('Sentinel', 'log_analysis'), lambda ctx, p: (release.wait(30), {'status': 'ok'})[1])
    mid = alfred.submit('log_analysis', 'hung task probe', CHEAP, 'test')
    task = alfred.store.claim_next('w1', 1)
    th = threading.Thread(target=alfred.execute_task, args=({**task, 'timeout_s': 1}, 'w1'), daemon=True)
    th.start()
    assert wait_for(lambda: 'heartbeat_stopped_deadline_exceeded' in acts(mid), timeout=15)
    time.sleep(1.5)                                                  # lease lapses because heartbeats stopped
    rec = alfred.store.recover_expired()
    assert rec and rec[0]['action'] == 'requeued'
    release.set()
    th.join(timeout=10)


# FM-04 multi-process correctness
def test_two_worker_processes_never_double_execute(env):
    a = Alfred()
    mids = [a.submit('log_analysis', f'parallel probe {i}', CHEAP, 'test') for i in range(24)]
    procs = [spawn_worker(conc='3'), spawn_worker(conc='3')]
    try:
        assert wait_for(lambda: all(a.store.get_mission(m)['status'] == 'verified' for m in mids), timeout=120)
    finally:
        for p in procs:
            p.send_signal(signal.SIGTERM)
        for p in procs:
            p.wait(timeout=30)
    tasks = [t for m in mids for t in a.store.tasks_for(m)]
    assert all(t['attempts'] == 1 for t in tasks)                     # no task claimed twice
    starts = [e for e in AuditReader(config.audit_path()).events(None, limit=10000) if e['action'] == 'task_started']
    assert len(starts) == len(tasks) == 24
    assert len({e['detail']['worker'] for e in starts}) == 2          # both processes genuinely did work


@needs_docker
def test_task_longer_than_lease_is_not_stolen_thanks_to_heartbeat(env):
    slow = {'test_slow.py': 'import time\n\n\ndef test_slow():\n    time.sleep(7)\n'}
    a = Alfred()
    mid = a.submit('engineering', 'long task probe', {'files': slow}, 'test')
    procs = [spawn_worker(lease='2', conc='2'), spawn_worker(lease='2', conc='2')]
    try:
        assert wait_for(lambda: a.store.get_mission(mid)['status'] in ('verified', 'failed'), timeout=90)
    finally:
        for p in procs:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=60)
    assert a.store.get_mission(mid)['status'] == 'verified'
    forge = [t for t in a.store.tasks_for(mid) if t['agent'] == 'Forge'][0]
    assert forge['attempts'] == 1 and 'recovery_requeued' not in acts(mid)


def test_sigterm_lets_worker_exit_cleanly(env):
    a = Alfred()
    mid = a.submit('log_analysis', 'sigterm probe', CHEAP, 'test')
    p = spawn_worker()
    assert wait_for(lambda: a.store.get_mission(mid)['status'] == 'verified', timeout=30)
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=20) == 0


@needs_docker
def test_cancelling_a_running_task_kills_its_container_and_cancels_mission(alfred):
    slow = {'test_slow.py': 'import time\n\n\ndef test_slow():\n    time.sleep(60)\n'}
    mid = alfred.submit('engineering', 'cancel running probe', {'files': slow}, 'test')
    stop = threading.Event()
    from gotham.core.worker import run_worker
    th = threading.Thread(target=run_worker, args=(alfred,), kwargs={'stop': stop, 'concurrency': 2, 'poll': 0.2})
    th.start()
    try:
        assert wait_for(lambda: bool(subprocess.run(['docker', 'ps', '-q', '--filter', 'label=gotham=1'], capture_output=True, text=True).stdout.strip()), 40)
        alfred.cancel(mid, 'test')
        assert wait_for(lambda: alfred.store.get_mission(mid)['status'] == 'cancelled', 30)
        assert subprocess.run(['docker', 'ps', '-q', '--filter', 'label=gotham=1'], capture_output=True, text=True).stdout.split() == []
    finally:
        stop.set()
        th.join(timeout=60)
    assert 'cancel_requested' in acts(mid) and 'mission_cancelled' in acts(mid)


# FM-05 API surface
def test_api_rejects_oversized_body_and_survives(env, monkeypatch):
    monkeypatch.setenv('GOTHAM_OPERATOR_TOKEN', 'o' * 32)
    v4.reset_for_tests()
    from gotham.app import app
    with TestClient(app) as c:
        big = json.dumps({'kind': 'security_audit', 'goal': 'oversized body probe', 'params': {'files': {'a.py': 'x' * 1_200_000}}})
        r = c.post('/api/v4/missions', content=big, headers={'Authorization': 'Bearer ' + 'o' * 32, 'Content-Type': 'application/json'})
        assert r.status_code == 413
        assert c.get('/api/v4/health').status_code == 200
    v4.reset_for_tests()


def test_schema_version_is_set_and_reopen_is_idempotent(env):
    s1 = Store(config.store_path())
    assert s1.schema_version() == 1
    m = s1.create_mission('k', 'goal goal', {}, 'x')
    s2 = Store(config.store_path())                                  # restart: no data loss, no re-migration errors
    assert s2.get_mission(m) is not None and s2.schema_version() == 1


# FM-06 sandbox resource exhaustion (host protection)
@needs_docker
def test_output_flood_is_bounded_and_does_not_exhaust_worker_memory(env):
    import resource
    code = 'import sys\nfor _ in range(400):\n    sys.stdout.write("x" * 1000000)\n'
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    r = sbx.run('gotham-sandbox:latest', ['python', '-c', code], timeout=60)
    grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
    assert r['output_bytes'] >= 400_000_000 and len(r['stdout']) <= sbx.MAX_OUT and r['container_destroyed']
    assert grown_mb < 150                                            # 400 MB of output did not land in worker memory


@needs_docker
def test_workspace_disk_quota_kills_runaway_writer(env, monkeypatch):
    monkeypatch.setattr(sbx, 'WORKSPACE_LIMIT_MB', 20)
    ws = env / 'ws'
    ws.mkdir()
    code = 'import time\nf = open("/work/fill.bin", "wb")\nwhile True:\n    f.write(b"0" * 1000000); f.flush(); time.sleep(0.01)\n'
    r = sbx.run('gotham-sandbox:latest', ['python', '-c', code], mount=ws, rw=True, timeout=60)
    assert r['quota_killed'] and r['container_destroyed']
    assert sbx.dir_size(ws) < 120 * 1024 * 1024                      # stopped near the limit, not at disk exhaustion


def test_image_build_retries_transient_registry_errors(monkeypatch):
    calls = []

    class R:
        def __init__(self, rc, err): self.returncode, self.stderr = rc, err

    def fake_run(cmd, **kw):
        if cmd[:3] == ['docker', 'image', 'inspect']:
            return R(1, 'No such image')
        calls.append(cmd)
        return R(1, '429 Too Many Requests') if len(calls) < 3 else R(0, '')
    monkeypatch.setattr(sbx.subprocess, 'run', fake_run)
    monkeypatch.setattr(sbx.time, 'sleep', lambda s: None)
    sbx.ensure_image('gotham-sandbox:latest')
    assert len(calls) == 3                                            # two 429s retried, third succeeded


# FM-14 mixed-uid deployment (container API uid != host worker uid) and misconfiguration diagnostics
def _as_uid(uid, code, env_extra):
    def demote():
        os.setgid(uid)
        os.setuid(uid)
    return subprocess.run([sys.executable, '-c', code], cwd=ROOT, env={**os.environ, **env_extra}, preexec_fn=demote, capture_output=True, text=True)


@pytest.mark.skipif(os.geteuid() != 0, reason='needs root to simulate a second uid')
def test_audit_dir_permissions_are_not_clobbered_and_preflight_names_the_problem(env):
    import shutil
    import tempfile
    base = Path(tempfile.mkdtemp(prefix='gotham-uid-'))              # world-traversable (pytest's tmp dir is root-only)
    try:
        base.chmod(0o755)
        shared, d2 = base / 'audit', base / 'data'
        for d in (shared, d2):
            d.mkdir()
            d.chmod(0o777)
        from gotham.core.audit import AuditWriter
        AuditWriter(shared / 'specter.sqlite3')                      # root worker touches a pre-existing shared dir
        assert (shared.stat().st_mode & 0o777) == 0o777              # ...and must NOT re-permission it (this locked the API out before)
        probe = ('from gotham.core import preflight; import json; c = preflight.run("api"); '
                 'print(json.dumps([x for x in c if x["status"] == "fail"]))')
        r = _as_uid(10001, probe, {'GOTHAM_DATA_DIR': str(d2), 'GOTHAM_STORE_DB': str(d2 / 'gotham.sqlite3'),
                                'GOTHAM_AUDIT_DB': str(shared / 'specter.sqlite3')})
        assert r.returncode == 0, r.stderr[-400:]
        failed = {c['name'] for c in json.loads(r.stdout)}
        assert failed & {'audit_key_access', 'audit_db_access'}      # root-owned 0600 files: other uid is told exactly why
        assert 'uid=10001' in r.stdout and 'GOTHAM_UID' in r.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.mark.skipif(os.geteuid() != 0, reason='needs root to simulate a second uid')
def test_worker_refuses_to_start_when_audit_dir_is_unusable(env):
    import shutil
    import tempfile
    base = Path(tempfile.mkdtemp(prefix='gotham-uid-'))
    try:
        base.chmod(0o755)
        (base / 'audit').mkdir()                                     # root-owned 0755: uid 10001 cannot write here
        (base / 'audit').chmod(0o755)
        (base / 'data').mkdir()
        (base / 'data').chmod(0o777)

        def demote():
            os.setgid(10001)
            os.setuid(10001)
        p = subprocess.run([sys.executable, '-m', 'gotham.core.worker'], cwd=ROOT, capture_output=True, text=True, timeout=60, preexec_fn=demote,
                           env={**os.environ, 'GOTHAM_DATA_DIR': str(base / 'data'), 'GOTHAM_STORE_DB': str(base / 'data' / 'g.sqlite3'),
                                'GOTHAM_AUDIT_DB': str(base / 'audit' / 'a.sqlite3')})
        assert p.returncode == 3, p.stderr[-500:]                    # fail fast with a distinct exit code
        assert 'preflight FAIL' in p.stderr and 'audit_dir_writable' in p.stderr and 'refusing to start' in p.stderr
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_preflight_endpoint_and_infra_degrade_gracefully(env, monkeypatch):
    monkeypatch.setenv('GOTHAM_BATMAN_TOKEN', 'b' * 32)
    monkeypatch.setenv('GOTHAM_OPERATOR_TOKEN', 'o' * 32)
    v4.reset_for_tests()
    from gotham.app import app
    from gotham.core.audit import AuditReader as AR
    with TestClient(app) as c:
        h = {'Authorization': 'Bearer ' + 'o' * 32}
        pf = c.get('/api/v4/preflight', headers=h).json()
        assert isinstance(pf['checks'], list) and {x['name'] for x in pf['checks']} >= {'data_dir_writable', 'audit_dir_writable', 'docker_daemon'}
        monkeypatch.setattr(AR, 'verify', lambda self: (_ for _ in ()).throw(PermissionError('denied: /audit/specter.key')))
        r = c.get('/api/v4/infra', headers=h)
        assert r.status_code == 200 and r.json()['audit']['valid'] is False and 'PermissionError' in r.json()['audit']['error']
    v4.reset_for_tests()
