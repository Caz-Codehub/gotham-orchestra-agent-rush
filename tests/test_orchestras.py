import os
from pathlib import Path
from fastapi.testclient import TestClient
from gotham.app import app
from gotham.orchestras import preview, run_orchestra, OrchestraError

class FakeClient:
    configured=True
    provider_name='vultr-serverless-inference'
    call_count=0
    def json(self,system,user,*,max_tokens=400):
        self.call_count+=1
        if 'Provide a JSON object:' in system:
            return {'instructions':{}}
        if 'central Captain Alfred' in system:
            return {'summary':'Analysis complete, no tools executed.','priority_actions':['Review scope']}
        return {'finding':'A planning-only report.','next_steps':['Run tests'],
                'tests':['Verify offline'], 'limitations':['Not executed']}

def test_orchestras_visible():
    specs=preview()
    assert len(specs)==4
    assert all(len(item['roles'])==3 for item in specs)

def test_lab_requires_scope():
    import pytest
    with pytest.raises(OrchestraError):
        run_orchestra('lab','Analyze these samples',client=FakeClient())

def test_offline_orchestra_never_fake_execution():
    class Unavailable:
        configured=False
        provider_name='offline'
    r=run_orchestra('research','Design a safe notebook analysis',client=Unavailable())
    assert r['executed'] is False and r['approval'] is False

def test_mocked_orchestration_and_sanitized_telemetry():
    traces=[]
    r=run_orchestra('software','Build a robust feature plan',client=FakeClient(),
                  telemetry=lambda mission,actor,action,detail:traces.append((actor,detail)))
    assert r['status']=='analysis_ready'
    assert r['executed'] is False and r['approval'] is False
    assert len(r['worker_reports'])==3
    assert r['model_calls']==5
    assert len(r['receipt_sha256'])==64
    assert all('Build a robust' not in str(details) for _,details in traces)

def test_static_ui_and_auth_rejects_unauthorized_requests(monkeypatch,tmp_path):
    monkeypatch.setenv('GOTHAM_ACCESS_TOKEN','testing-really-long-private-token')
    monkeypatch.setenv('GOTHAM_SPECTER_DB',str(tmp_path/'specter.sqlite3'))
    with TestClient(app) as c:
        page=c.get('/orchestra')
        assert page.status_code==200
        assert 'ORCHESTRA' in page.text
        assert len(c.get('/api/orchestras').json()['orchestras'])==4
        response=c.post('/api/orchestra/dispatch',json={'orchestra':'software','goal':'Build a safe website'})
        assert response.status_code==401
