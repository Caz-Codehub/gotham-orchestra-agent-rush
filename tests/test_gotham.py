import hashlib
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from gotham.agents import team,inspect_ast,scan_risks
from gotham.orchestrator import run_mission
from gotham.sandbox import run_isolated, containment_probe, SandboxUnavailable
from gotham.app import app

SAMPLE={'goal':'Repair the add function to add two numbers','code':'def add(a,b):\n    return a - b\n','tests':'assert add(2,3)==5\n'}

def fake_sandbox(code,tests,*,timeout=5):
    good='return a + b' in code
    return {'passed':good, 'timed_out':False,'exit_code':0 if good else 1,
            'sandbox':'docker','network':'none','container_destroyed':True,'output':'mocked test',
            'code_sha256':hashlib.sha256(code.encode()).hexdigest()}

def test_hierarchy_exactly_six_agents():
    people=team()
    assert len(people)==6
    assert people[0].name=='Alfred' and people[0].rank=='Captain'
    assert len({x.name for x in people})==6
    assert len(people[1:])==5
    assert 'Supervisor' not in [x.name for x in people]

def test_ast_and_security_inspection():
    info=inspect_ast('import socket\ndef test():\n    return 2')
    assert info['valid_syntax'] and 'test' in info['functions']
    assert 'network operations' in scan_risks('import socket')['advisory_findings']
    assert not inspect_ast('def :')['valid_syntax']

def test_mission_offline_mode_requires_verification():
    with patch('gotham.agents.run_isolated',side_effect=fake_sandbox),patch('gotham.orchestrator.run_isolated',side_effect=fake_sandbox):
        result=run_mission(**SAMPLE)
    assert result['approval'] and result['status']=='verified'
    assert result['inference'].startswith('OFFLINE RULES') # Does not claim contest compliance.
    assert result['candidate_source']=='sample-rule (not AI)'
    assert len(result['agents'])==6
    assert len([e for e in result['events'] if e.get('phase')=='worker'])==5
    assert len(result['receipt_sha256'])==64

def test_no_docker_no_fake_verification():
    with (patch('gotham.agents.run_isolated',side_effect=SandboxUnavailable('Docker absent')),
          patch('gotham.orchestrator.run_isolated',side_effect=SandboxUnavailable('Docker absent'))):
        result=run_mission(**SAMPLE)
    assert not result['approval']
    assert result['status']=='not_verified'

def test_docker_cli_hardening_and_timeout_cleanup():
    import subprocess
    def simulate(cmd,**kwargs):
        if cmd[1]=='run': raise subprocess.TimeoutExpired(cmd,2)
        return subprocess.CompletedProcess(cmd,0,stdout='gotham',stderr='')
    with patch('gotham.sandbox.subprocess.run',side_effect=simulate) as proc:
        out=run_isolated('while True: pass','assert 1',timeout=2)
    assert out['timed_out'] and out['container_destroyed']
    run_cmd=proc.call_args_list[0].args[0]
    for arg in ('--network=none','--read-only','--cap-drop=ALL','--pids-limit=32','--user=65534:65534'):
        assert arg in run_cmd
    assert proc.call_args_list[1].args[0][1:3]==['rm','-f']

def test_docker_unavailable_hard_fail():
    with patch('gotham.sandbox.subprocess.run',side_effect=FileNotFoundError):
        try: run_isolated('print(1)','assert 1')
        except SandboxUnavailable: pass
        else: raise AssertionError('No Docker must fail')

def test_auth_gate_and_health():
    client=TestClient(app)
    assert client.get('/health').status_code==200
    assert client.get('/api/agents').json()['agents'][0]['name']=='Alfred'
    assert client.get('/').status_code==200
    with patch.dict(os.environ,{'GOTHAM_ACCESS_TOKEN':'test-secret'}):
        assert client.post('/api/missions',json=SAMPLE).status_code==401
        assert client.post('/api/missions',headers={'X-Gotham-Token':'wrong'},json=SAMPLE).status_code==401

def test_invalid_mission_rejected():
    try: run_mission('fix','x=1','assert 1')
    except ValueError: pass
    else: raise AssertionError('Goal length validation not enforced')
