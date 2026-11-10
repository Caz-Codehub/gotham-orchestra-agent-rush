import json
import time

import pytest
from fastapi.testclient import TestClient

from gotham.core import api as v4, config
from tests.conftest import run_until_done
from tests.fixtures import AUTH_LOG, WEAK_EXPECTED, WEAK_PROJECT

B, O, V = 'b' * 32, 'o' * 32, 'v' * 32


@pytest.fixture()
def client(env, monkeypatch):
    monkeypatch.setenv('GOTHAM_BATMAN_TOKEN', B)
    monkeypatch.setenv('GOTHAM_OPERATOR_TOKEN', O)
    monkeypatch.setenv('GOTHAM_VIEWER_TOKEN', V)
    monkeypatch.setenv('GOTHAM_INFERENCE_PROVIDER', 'none')
    v4.reset_for_tests()
    from gotham.app import app
    from gotham.core import auth
    auth._fail.clear()
    with TestClient(app) as c:
        yield c
    v4.reset_for_tests()


def H(tok):
    return {'Authorization': f'Bearer {tok}'}


def test_unauthenticated_and_viewer_cannot_submit(client):
    assert client.get('/api/v4/missions').status_code == 401
    body = {'kind': 'security_audit', 'goal': 'audit this project please', 'params': {}}
    assert client.post('/api/v4/missions', json=body, headers=H(V)).status_code == 403
    assert client.get('/api/v4/missions', headers=H(V)).status_code == 200


def test_audit_endpoints_are_batman_only(client):
    for tok in (O, V):
        assert client.get('/api/v4/audit/verify', headers=H(tok)).status_code == 403
        assert client.get('/api/v4/audit/events', headers=H(tok)).status_code == 403
    assert client.get('/api/v4/audit/verify', headers=H(B)).json()['valid'] is True


def test_mission_lifecycle_through_api_with_artifact_integrity_and_audit(client):
    body = {'kind': 'security_audit', 'goal': 'Audit the uploaded project', 'params': {'files': WEAK_PROJECT, 'expect_rules': WEAK_EXPECTED},
            'idempotency_key': 'k-1'}
    r = client.post('/api/v4/missions', json=body, headers=H(O)).json()
    mid = r['mission']['id']
    assert client.post('/api/v4/missions', json=body, headers=H(O)).json()['mission']['id'] == mid   # idempotent
    run_until_done(v4.alfred())
    d = client.get(f'/api/v4/missions/{mid}', headers=H(V)).json()
    assert d['mission']['status'] == 'verified' and d['mission']['result']['verified']
    art = next(a for a in d['artifacts'] if a['name'] == 'security_report.json')
    pv = client.get(f"/api/v4/artifacts/{art['id']}/preview", headers=H(V)).json()
    assert pv['sha256_verified'] and 'findings' in json.loads(pv['text'])
    dl = client.get(f"/api/v4/artifacts/{art['id']}/download", headers=H(V))
    assert dl.status_code == 200 and len(dl.content) == art['size']
    # tamper with the stored artifact: download must refuse
    from pathlib import Path
    stored = Path(v4.alfred().store.get_artifact(art['id'])['path'])
    stored.write_text('tampered')
    assert client.get(f"/api/v4/artifacts/{art['id']}/download", headers=H(V)).status_code == 409
    rep = client.get(f'/api/v4/audit/missions/{mid}', headers=H(B)).json()
    assert rep['integrity']['valid'] and 'mission_finalized' in [e['action'] for e in rep['events']]
    assert 'path' not in client.get('/api/v4/artifacts', headers=H(V)).json()['artifacts'][0]


def test_cancel_before_execution_and_unknown_kind_rejected(client):
    r = client.post('/api/v4/missions', json={'kind': 'nonsense', 'goal': 'do the impossible thing'}, headers=H(O))
    assert r.status_code == 400
    m = client.post('/api/v4/missions', json={'kind': 'security_audit', 'goal': 'audit then cancel it', 'params': {'files': WEAK_PROJECT}}, headers=H(O)).json()
    mid = m['mission']['id']
    c = client.post(f'/api/v4/missions/{mid}/cancel', headers=H(O)).json()
    assert c['mission']['status'] == 'cancelled' and all(t['status'] == 'cancelled' for t in c['tasks'])
    run_until_done(v4.alfred())    # nothing left to run
    assert client.get(f'/api/v4/missions/{mid}', headers=H(O)).json()['mission']['status'] == 'cancelled'


def test_approval_decisions_batman_only_and_gate_dynamic_analysis(client):
    m = client.post('/api/v4/missions', json={'kind': 'malware_analysis', 'goal': 'Analyse inert sample dynamically',
        'params': {'sample': {'name': 's.py', 'content': 'print("x")\n'}, 'dynamic': True}}, headers=H(O)).json()
    ap = client.get('/api/v4/approvals', headers=H(O)).json()['approvals']
    assert len(ap) == 1 and ap[0]['detail']['tools'] == ['sandbox_behavior']
    assert client.post(f"/api/v4/approvals/{ap[0]['id']}/decide", json={'approve': True}, headers=H(O)).status_code == 403
    d = client.post(f"/api/v4/approvals/{ap[0]['id']}/decide", json={'approve': False, 'note': 'not today'}, headers=H(B)).json()
    assert d['status'] == 'denied'
    assert client.post(f"/api/v4/approvals/{ap[0]['id']}/decide", json={'approve': True}, headers=H(B)).status_code == 409
    got = client.get(f"/api/v4/missions/{m['mission']['id']}", headers=H(O)).json()
    assert got['mission']['status'] in ('cancelled', 'failed') and got['tasks'][0]['status'] == 'cancelled'


def test_chat_rules_mode_is_honest(client):
    r = client.post('/api/v4/chat', json={'message': 'status'}, headers=H(O)).json()
    assert 'NOT configured' in r['reply'] and 'no model' in r['source']
    r = client.post('/api/v4/chat', json={'message': 'objective: write me a compiler'}, headers=H(O)).json()
    assert 'rules mode' in r['reply']


def test_objective_mission_is_blocked_without_model(client):
    m = client.post('/api/v4/missions', json={'kind': 'objective', 'goal': 'Autonomously build a REST service'}, headers=H(O)).json()
    assert m['mission']['status'] == 'failed' and 'BLOCKED' in json.dumps(m['mission']['result'])


def test_infra_budget_and_agents_report_real_state(client):
    infra = client.get('/api/v4/infra', headers=H(V)).json()
    assert infra['auth_roles_configured'] == {'batman': True, 'operator': True, 'viewer': True} and 'docker' in infra
    ag = client.get('/api/v4/agents', headers=H(V)).json()
    assert [a['name'] for a in ag['agents']] == ['Scout', 'Forge', 'Oracle', 'Sentinel', 'Cipher']
    assert ag['captain']['planner'].startswith('rule-based')
    assert 'usage' in client.get('/api/v4/budget', headers=H(V)).json()


def test_log_analysis_mission_and_retry_of_failed_task(client):
    m = client.post('/api/v4/missions', json={'kind': 'log_analysis', 'goal': 'Correlate auth log events',
                    'params': {'files': {'auth.log': AUTH_LOG}, 'log': 'auth.log'}}, headers=H(O)).json()
    run_until_done(v4.alfred())
    d = client.get(f"/api/v4/missions/{m['mission']['id']}", headers=H(O)).json()
    assert d['mission']['status'] == 'verified'
    ev = client.get(f"/api/v4/missions/{m['mission']['id']}/evidence", headers=H(O)).json()['tasks'][0]['result']['evidence']
    assert any(f['rule'] == 'log.success-after-failures' for f in ev['log_findings'])
    bad = client.post('/api/v4/missions', json={'kind': 'log_analysis', 'goal': 'Correlate a missing log file',
                      'params': {'files': {}, 'log': 'missing.log'}}, headers=H(O)).json()
    run_until_done(v4.alfred())
    t = client.get(f"/api/v4/missions/{bad['mission']['id']}", headers=H(O)).json()
    assert t['mission']['status'] == 'failed'
    assert client.post(f"/api/v4/tasks/{t['tasks'][0]['id']}/retry", headers=H(O)).status_code == 403   # recovery is Batman-only
    assert client.post(f"/api/v4/tasks/{t['tasks'][0]['id']}/retry", headers=H(B)).json()['mission']['status'] == 'running'
