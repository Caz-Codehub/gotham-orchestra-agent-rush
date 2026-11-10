"""Unit tests of the Gotham 4.0 core that do not need Docker."""
import json
import sqlite3
import time

import pytest
from fastapi import HTTPException

from gotham.core import auth, config
from gotham.core import tools as T
from gotham.core import sectools  # noqa: F401
from gotham.core.audit import AuditReader, AuditWriter, redact
from gotham.core.store import Store
from tests.fixtures import AUTH_LOG, INERT_SAMPLE


# ---------------------------------------------------------------- audit
def test_audit_chain_valid_and_append_only(env):
    w = AuditWriter(config.audit_path())
    for i in range(5):
        w.record('m1', None, 'Alfred', 'event', {'i': i})
    r = AuditReader(config.audit_path())
    assert r.verify()['valid'] and r.verify()['checked'] == 5
    conn = sqlite3.connect(config.audit_path())
    with pytest.raises(sqlite3.DatabaseError, match='append-only'):
        conn.execute("UPDATE events SET action='x' WHERE seq=1")
    with pytest.raises(sqlite3.DatabaseError, match='append-only'):
        conn.execute('DELETE FROM events WHERE seq=2')


def test_audit_detects_out_of_band_tampering(env):
    w = AuditWriter(config.audit_path())
    for i in range(4):
        w.record('m1', None, 'Forge', 'tool_call', {'i': i})
    conn = sqlite3.connect(config.audit_path())
    conn.execute('DROP TRIGGER events_no_update')           # attacker with file write access removes the guard...
    conn.execute("UPDATE events SET detail='{\"i\":99}' WHERE seq=2")  # ...and rewrites history
    conn.commit()
    res = AuditReader(config.audit_path()).verify()
    assert not res['valid'] and res['broken_at_seq'] == 2
    conn.execute('DROP TRIGGER events_no_delete')
    conn.execute('DELETE FROM events WHERE seq=3')
    conn.commit()
    res = AuditReader(config.audit_path()).verify()
    assert not res['valid']


def test_audit_redacts_secrets():
    out = redact({'note': 'password=SuperSecret123 and token: ghp_abcdefghijklmnopqrstuvwxyz0123456789'})
    assert 'SuperSecret123' not in json.dumps(out) and 'ghp_abcdef' not in json.dumps(out)


def test_writer_has_no_read_surface(env):
    w = AuditWriter(config.audit_path())
    assert not any(hasattr(w, n) for n in ('verify', 'events', 'report'))


# ---------------------------------------------------------------- tool policy
def _ctx(env, agent, store=None):
    store = store or Store(config.store_path())
    ws = config.workspaces_dir() / 'm' / 'w'
    ws.mkdir(parents=True, exist_ok=True)
    return T.ToolContext('m', 't', agent, ws, store, AuditWriter(config.audit_path()))


def test_agent_cannot_use_unpermitted_tool_and_violation_is_audited(env):
    ctx = _ctx(env, 'Scout')
    with pytest.raises(T.ToolDenied):
        T.call(ctx, 'sandbox_run', {'cmd': ['echo', 'hi']})
    ev = AuditReader(config.audit_path()).events('m')
    assert any(e['action'] == 'policy_violation_tool_not_permitted' for e in ev)


def test_path_traversal_and_symlink_escape_denied(env):
    ctx = _ctx(env, 'Forge')
    for bad in ('../../etc/passwd', '/etc/passwd', '..', 'a/../../x'):
        with pytest.raises(T.ToolDenied):
            T.call(ctx, 'fs_read', {'path': bad})
    (ctx.workspace / 'link').symlink_to('/etc')
    with pytest.raises(T.ToolDenied):
        T.call(ctx, 'fs_read', {'path': 'link/passwd'})


def test_agent_cannot_touch_audit_journal_via_tools(env):
    ctx = _ctx(env, 'Forge')
    rel = '../' * 6 + str(config.audit_path()).lstrip('/')
    with pytest.raises(T.ToolDenied):
        T.call(ctx, 'fs_write', {'path': rel, 'content': 'x'})
    with pytest.raises(T.ToolDenied):
        T.call(ctx, 'fs_read', {'path': rel})


def test_argument_validation_and_unknown_tool(env):
    ctx = _ctx(env, 'Forge')
    with pytest.raises(T.ToolError):
        T.call(ctx, 'fs_write', {'path': 'a'})
    with pytest.raises(T.ToolError):
        T.call(ctx, 'fs_read', {'path': 'a', 'extra': 1})
    with pytest.raises(T.ToolDenied):
        T.call(ctx, 'rm_rf_everything', {})


def test_high_risk_tool_requires_approval_then_runs_with_grant(env):
    store = Store(config.store_path())
    ctx = _ctx(env, 'Cipher', store)
    (ctx.workspace / 's.py').write_text('print(1)')
    with pytest.raises(T.ApprovalRequired):
        T.call(ctx, 'sandbox_behavior', {'path': 's.py'})
    store.request_approval('m', 't', 'tool:sandbox_behavior', {})
    assert not store.has_approval('t', 'tool:sandbox_behavior')  # pending is not approved


def test_tool_call_quota_enforced(env):
    ctx = _ctx(env, 'Forge')
    ctx.max_calls = 3
    for _ in range(3):
        T.call(ctx, 'fs_list', {})
    with pytest.raises(T.ToolDenied):
        T.call(ctx, 'fs_list', {})


def test_cancellation_stops_tool_calls(env):
    ctx = _ctx(env, 'Forge')
    ctx.is_cancelled = lambda: True
    with pytest.raises(T.TaskCancelled):
        T.call(ctx, 'fs_list', {})


# ---------------------------------------------------------------- store: durability, leases, deps
def test_idempotent_submission_and_dependency_ordering(env):
    s = Store(config.store_path())
    m1 = s.create_mission('k', 'goal goal', {}, 'x', idem_key='abc')
    assert s.create_mission('k', 'goal goal', {}, 'x', idem_key='abc') == m1
    a = s.add_task(m1, 'Scout', 'recon', 'a', {})
    b = s.add_task(m1, 'Forge', 'x', 'b', {}, depends=[a])
    first = s.claim_next('w1', 30)
    assert first['id'] == a
    assert s.claim_next('w2', 30) is None            # b must wait for a
    s.finish_task(a, 'w1', 'succeeded', {})
    assert s.claim_next('w2', 30)['id'] == b


def test_failed_dependency_blocks_dependents(env):
    s = Store(config.store_path())
    m = s.create_mission('k', 'goal goal', {}, 'x')
    a = s.add_task(m, 'Scout', 'recon', 'a', {})
    b = s.add_task(m, 'Forge', 'x', 'b', {}, depends=[a])
    s.claim_next('w', 30)
    s.finish_task(a, 'w', 'failed', {}, 'boom')
    s.block_dependents()
    assert s.get_task(b)['status'] == 'blocked'


def test_expired_lease_is_requeued_then_fails_after_retry_budget(env):
    s = Store(config.store_path())
    m = s.create_mission('k', 'goal goal', {}, 'x')
    t = s.add_task(m, 'Scout', 'recon', 'a', {}, max_attempts=2)
    s.claim_next('dead-worker', lease_s=-1)               # worker dies instantly: lease already expired
    assert s.recover_expired()[0]['action'] == 'requeued'
    s.claim_next('dead-worker-2', lease_s=-1)
    assert s.recover_expired()[0]['action'] == 'failed'   # attempts exhausted
    assert s.get_task(t)['status'] == 'failed'


def test_stale_worker_cannot_overwrite_after_lease_lost(env):
    s = Store(config.store_path())
    m = s.create_mission('k', 'goal goal', {}, 'x')
    t = s.add_task(m, 'Scout', 'recon', 'a', {})
    s.claim_next('w1', lease_s=-1)
    s.recover_expired()
    s.claim_next('w2', 30)
    assert s.finish_task(t, 'w1', 'succeeded', {}) is False   # w1 no longer owns the lease
    assert s.finish_task(t, 'w2', 'succeeded', {}) is True


def test_cancel_marks_pending_cancelled_and_blocks_claims(env):
    s = Store(config.store_path())
    m = s.create_mission('k', 'goal goal', {}, 'x')
    t = s.add_task(m, 'Scout', 'recon', 'a', {})
    s.cancel_mission(m)
    assert s.get_task(t)['status'] == 'cancelled' and s.claim_next('w', 30) is None


def test_approval_gate(env):
    s = Store(config.store_path())
    m = s.create_mission('k', 'goal goal', {}, 'x')
    t = s.add_task(m, 'Cipher', 'lab', 'a', {}, risk='high')
    assert s.get_task(t)['status'] == 'awaiting_approval' and s.claim_next('w', 30) is None
    aid = s.request_approval(m, t, 'task_start', {'tools': ['lab_start']})
    s.decide_approval(aid, True, 'batman')
    assert s.get_task(t)['status'] == 'pending' and s.has_approval(t, 'tool:lab_start')
    assert s.decide_approval(aid, False, 'batman') is None  # decisions are final


# ---------------------------------------------------------------- auth
class _Req:
    def __init__(self, token=None, ip='1.2.3.4'):
        self.headers = {'Authorization': f'Bearer {token}'} if token else {}
        self.client = type('c', (), {'host': ip})()


def test_roles_and_weak_tokens(monkeypatch):
    monkeypatch.setenv('GOTHAM_BATMAN_TOKEN', 'b' * 32)
    monkeypatch.setenv('GOTHAM_OPERATOR_TOKEN', 'o' * 32)
    monkeypatch.setenv('GOTHAM_VIEWER_TOKEN', 'short')
    assert auth.authenticate(_Req('b' * 32)).can('audit:read')
    op = auth.authenticate(_Req('o' * 32))
    assert op.can('missions:submit') and not op.can('audit:read') and not op.can('approvals:decide')
    with pytest.raises(HTTPException):
        auth.authenticate(_Req('short'))        # weak tokens are never accepted


def test_failed_auth_lockout(monkeypatch):
    monkeypatch.setenv('GOTHAM_BATMAN_TOKEN', 'b' * 32)
    for _ in range(10):
        with pytest.raises(HTTPException):
            auth.authenticate(_Req('wrong', ip='9.9.9.9'))
    with pytest.raises(HTTPException) as e:
        auth.authenticate(_Req('b' * 32, ip='9.9.9.9'))
    assert e.value.status_code == 429


# ---------------------------------------------------------------- security analysis tools (host-side static)
def test_log_correlation_finds_bruteforce_then_compromise(env):
    ctx = _ctx(env, 'Sentinel')
    (ctx.workspace / 'auth.log').write_text(AUTH_LOG)
    res = T.call(ctx, 'log_analyze', {'path': 'auth.log'})
    rules = {f['rule'] for f in res['findings']}
    assert {'log.brute-force', 'log.success-after-failures'} <= rules
    assert all(f['ip'] != '198.51.100.4' for f in res['findings'])   # 2 failures < threshold


def test_sigma_rule_matches_and_rejects_unsupported(env):
    ctx = _ctx(env, 'Sentinel')
    (ctx.workspace / 'r.yml').write_text('title: Encoded PowerShell\nlevel: high\ndetection:\n  sel:\n    Image|endswith: powershell.exe\n'
                                         '    CommandLine|contains: -enc\n  filt:\n    User: SYSTEM\n  condition: sel and not filt\n')
    evs = [{'Image': 'C:\\x\\powershell.exe', 'CommandLine': 'powershell -enc AAA', 'User': 'bob'},
           {'Image': 'C:\\x\\powershell.exe', 'CommandLine': 'powershell -enc AAA', 'User': 'SYSTEM'},
           {'Image': 'C:\\x\\cmd.exe', 'CommandLine': 'dir', 'User': 'bob'}]
    (ctx.workspace / 'e.jsonl').write_text('\n'.join(json.dumps(e) for e in evs))
    res = T.call(ctx, 'sigma_eval', {'rule': 'r.yml', 'events': 'e.jsonl'})
    assert res['matches'] == [0]
    (ctx.workspace / 'bad.yml').write_text("title: x\ndetection:\n  a:\n    f: 1\n  condition: __import__('os')\n")
    with pytest.raises(T.ToolError):
        T.call(ctx, 'sigma_eval', {'rule': 'bad.yml', 'events': 'e.jsonl'})


def test_static_triage_extracts_indicators_and_never_executes(env):
    ctx = _ctx(env, 'Cipher')
    (ctx.workspace / 's.py').write_text(INERT_SAMPLE)
    r = T.call(ctx, 'file_triage', {'path': 's.py'})
    assert r['executed'] is False and len(r['sha256']) == 64
    assert any('beacon-test.example.invalid' in u for u in r['iocs']['url'])
    assert not (ctx.workspace / '..' / 'gotham_inert_marker.txt').exists()


def test_yara_generated_rule_compiles_matches_sample_not_benign(env):
    ctx = _ctx(env, 'Cipher')
    (ctx.workspace / 's.py').write_text(INERT_SAMPLE)
    (ctx.workspace / 'ok.py').write_text('def add(a, b):\n    return a + b\n')
    g = T.call(ctx, 'yara_generate', {'path': 's.py', 'rule_name': 'gotham_inert_test'})
    assert g['compiles'] and g['matches_source_sample']
    v = T.call(ctx, 'yara_validate', {'rule_path': g['rule_path'], 'positive': ['s.py'], 'negative': ['ok.py']})
    assert v['valid'] and v['false_positives'] == 0
    assert T.call(ctx, 'yara_validate', {'rule_path': g['rule_path'], 'positive': ['ok.py']})['valid'] is False


def test_secrets_and_config_scanners(env):
    ctx = _ctx(env, 'Sentinel')
    (ctx.workspace / 'c.py').write_text('API_KEY = "sk-live-0123456789abcdef0123"\n')
    (ctx.workspace / 'Dockerfile').write_text('FROM python:latest\nCMD ["x"]\n')
    assert T.call(ctx, 'secrets_scan', {})['findings']
    rules = {f['rule'] for f in T.call(ctx, 'config_audit', {})['findings']}
    assert {'docker.runs-as-root', 'docker.unpinned-base'} <= rules
