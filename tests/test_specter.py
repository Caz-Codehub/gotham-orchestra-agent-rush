"""Separate auditor tests; no Vultr calls, credit usage or live Docker."""
import hashlib
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from gotham.specter import SpecterJournal
from gotham.orchestrator import run_mission
from gotham.app import app

SAMPLE={'goal':'Repair Python addition to pass the tests',
        'code':'def add(a,b):\n    return a - b\n',
        'tests':'assert add(2,3)==5\n'}


def fake_docker(code,tests,*,timeout=5):
    ok='return a + b' in code
    return {'passed':ok,'exit_code':0 if ok else 1,'sandbox':'docker','network':'none',
            'container_destroyed':True,'timed_out':False,
            'code_sha256':hashlib.sha256(code.encode()).hexdigest(),'output':'simulated'}


def test_specter_independent_of_alfreds_team():
    from gotham.agents import team
    assert len(team())==6
    assert 'Specter' not in [a.name for a in team()]
    with patch.dict(os.environ,{'GOTHAM_ACCESS_TOKEN':'mission-only','GOTHAM_BATMAN_TOKEN':'batman-private'}):
        with TestClient(app) as browser:
            assert 'Specter' not in str(browser.get('/api/agents').json())
            assert browser.get('/api/batman/audit').status_code==401
            assert browser.get('/api/batman/audit',headers={'X-Gotham-Token':'mission-only'}).status_code==401
            assert browser.get('/api/batman/audit',headers={'X-Batman-Token':'batman-private'}).status_code==200


def test_detects_agent_policy_and_containment_breach(tmp_path):
    monitor=SpecterJournal(tmp_path/'audit.db')
    mission='mission-123'
    monitor.record(mission,'Batman','mission_received')
    monitor.record(mission,'Forge','worker_finished',{'tool':'run_baseline','state':'completed'})
    monitor.record(mission,'Alfred','sandbox_result',{'sandbox':'docker','network':'bridge','container_destroyed':False})
    monitor.record(mission,'Alfred','mission_finished',{'approved':True,'verified_evidence':False})
    found=monitor.scan_once()
    codes={x['code'] for x in found}
    assert {'TOOL_POLICY','SANDBOX_BOUNDARY','CONTAINER_NOT_DESTROYED','UNVERIFIED_APPROVAL'}<=codes
    assert monitor.status()['active_missions']==0
    assert monitor.verify()['valid'] is True
    assert monitor.scan_once()==[]  # no duplicate alerts


def test_healthy_events_no_alerts_and_hash_chain(tmp_path):
    monitor=SpecterJournal(tmp_path/'audit.db')
    mission='healthy'
    monitor.record(mission,'Batman','mission_received')
    monitor.record(mission,'Alfred','parallel_delegation',{'worker_count':5})
    monitor.record(mission,'Forge','worker_finished',{'tool':'propose_patch','state':'completed'})
    monitor.record(mission,'Alfred','sandbox_result',{'sandbox':'docker','network':'none',
                    'container_destroyed':True,'timed_out':False})
    monitor.record(mission,'Alfred','mission_finished',{'approved':True,'verified_evidence':True})
    assert monitor.scan_once()==[]
    assert monitor.verify()['valid'] is True
    with monitor._connect() as db:
        db.execute("UPDATE events SET action='tampered' WHERE id=1")
        db.commit()
    assert monitor.verify()['valid'] is False


def test_receipts_remain_private_from_operational_agents(tmp_path):
    monitor=SpecterJournal(tmp_path/'audit.db')
    with patch('gotham.agents.run_isolated',side_effect=fake_docker),\
         patch('gotham.orchestrator.run_isolated',side_effect=fake_docker):
        result=run_mission(**SAMPLE,telemetry=monitor.record)
    assert result['approval'] is True
    assert len(result['agents'])==6
    assert 'Specter' not in str(result)
    assert monitor.status()['events_recorded']>9
    assert monitor.scan_once()==[]
    assert monitor.status()['active_missions']==0
    assert monitor.verify()['valid']
