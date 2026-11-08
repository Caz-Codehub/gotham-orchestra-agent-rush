"""Zero-cost policy, genuine agent separation, and Batman-only oversight."""
import os
import threading
from unittest.mock import patch
from fastapi.testclient import TestClient
from gotham.inference import get_inference_client, OllamaInference, NoInference
from gotham.objectives import run_objective
from gotham.app import app

GOAL='Design a zero-budget research platform that requires independent agent verification.'


def test_zero_cost_default_cannot_call_external_inference():
    with patch.dict(os.environ,{'GOTHAM_INFERENCE_PROVIDER':'none','VULTR_INFERENCE_API_KEY':'fake',
                                'VULTR_INFERENCE_MODEL':'fake','GOTHAM_ALLOW_PAID_INFERENCE':''}):
        client=get_inference_client()
        assert isinstance(client,NoInference)
        assert client.configured is False
        out=run_objective(GOAL,client=client)
    assert out['status']=='model_unavailable'
    assert not out['approval'] and not out['external_actions_executed']
    assert len(out['worker_reports'])==5
    assert all(v['status']=='not_executed' for v in out['worker_reports'].values())
    assert out['model_calls']==0


def test_vultr_double_opt_in_guard():
    with patch.dict(os.environ,{'GOTHAM_INFERENCE_PROVIDER':'vultr','VULTR_INFERENCE_API_KEY':'fake',
             'VULTR_INFERENCE_MODEL':'model','GOTHAM_ALLOW_PAID_INFERENCE':'NO'}):
        assert not get_inference_client().configured
    with patch.dict(os.environ,{'GOTHAM_INFERENCE_PROVIDER':'vultr','VULTR_INFERENCE_API_KEY':'fake',
             'VULTR_INFERENCE_MODEL':'model','GOTHAM_ALLOW_PAID_INFERENCE':'I_ACCEPT_POTENTIAL_CHARGES'}):
        assert get_inference_client().configured


class ReasoningStub:
    configured=True
    provider_name='ollama-local'
    def __init__(self): self.prompts=[];self.lock=threading.Lock();self.call_count=0
    def json(self,system,user,*,max_tokens=400):
        with self.lock:
            self.prompts.append((system,user))
            self.call_count+=1
        if system.startswith('You are Captain Alfred. You command'):
            return {'assignments':{name:'Analyze the objective from '+name+' perspective.'
                     for name in ['Scout','Forge','Oracle','Sentinel','Cipher']}}
        if system.startswith('You are Captain Alfred. Synthesize'):
            return {'summary':'Five distinct analyses reviewed; no tool execution performed.',
                    'priorities':['Build local MVP'],'open_questions':[]}
        for name in ['Scout','Forge','Oracle','Sentinel','Cipher']:
            if system.startswith('You are '+name+', an autonomous Gotham specialist'):
                return {'finding':name+' identifies a useful area of work',
                        'recommendations':['Complete '+name+' checklist'],
                        'unknowns':['Need independent evidence'], 'confidence':'medium'}
        raise AssertionError('Unexpected prompt')


def test_five_independent_analysts_and_alfred_synthesis():
    fake=ReasoningStub()
    telemetry=[]
    out=run_objective(GOAL,client=fake,telemetry=lambda mission,actor,action,detail: telemetry.append((actor,action)))
    assert out['status']=='analysis_ready'
    assert out['plan_source']=='ollama-local'
    assert out['model_calls']==7  # plan, five separate workers, final report
    assert {name for name,r in out['worker_reports'].items() if r['status']=='analysis_completed'}=={
        'Scout','Forge','Oracle','Sentinel','Cipher'}
    assert len([a for a,b in telemetry if b=='worker_finished'])==5
    assert 'Specter' not in str(fake.prompts)
    assert not out['external_actions_executed'] and not out['approval']
    assert len(out['receipt_sha256'])==64


def test_objective_api_and_separate_batman_audit_auth(tmp_path):
    with patch.dict(os.environ,{'GOTHAM_ACCESS_TOKEN':'mission-secret','GOTHAM_BATMAN_TOKEN':'audit-secret',
                  'GOTHAM_INFERENCE_PROVIDER':'none','GOTHAM_SPECTER_DB':str(tmp_path/'specter.db'),
                  'GOTHAM_LEDGER_PATH':str(tmp_path/'ledger.db')}):
        with TestClient(app) as browser:
            r=browser.post('/api/objectives',json={'goal':GOAL})
            assert r.status_code==401
            r=browser.post('/api/objectives',json={'goal':GOAL},headers={'X-Gotham-Token':'mission-secret'})
            assert r.status_code==200 and r.json()['status']=='model_unavailable'
            assert browser.get('/api/batman/audit',headers={'X-Gotham-Token':'mission-secret'}).status_code==401
            assert browser.get('/api/batman/audit',headers={'X-Batman-Token':'audit-secret'}).status_code==200
            assert browser.get('/api/history',headers={'X-Gotham-Token':'mission-secret'}).json()['missions']


def test_specter_receives_metadata_not_private_context(tmp_path):
    from gotham.specter import SpecterJournal
    journal=SpecterJournal(tmp_path/'auditor.db')
    out=run_objective(GOAL,context='SENSITIVE_PRIVATE_CONTEXT_ONLY_FOR_AGENTS',
                       client=ReasoningStub(),telemetry=journal.record)
    journal.scan_once()
    with journal._connect() as db:
        payload=' '.join(row[0] for row in db.execute('SELECT detail FROM events'))
    assert 'SENSITIVE_PRIVATE_CONTEXT_ONLY_FOR_AGENTS' not in payload
    assert journal.status()['events_recorded']>=10
    assert journal.verify()['valid']
