"""Receipt internal hash verifier; this does not prove external authenticity."""
from unittest.mock import patch
import hashlib
from gotham.orchestrator import run_mission
from scripts.verify_receipt import verify


def fake_docker(code, tests, *, timeout=5):
    passed='return a + b' in code
    return {'passed':passed,'timed_out':False,'exit_code':0 if passed else 1,
            'sandbox':'docker','network':'none','container_destroyed':True,
            'code_sha256':hashlib.sha256(code.encode()).hexdigest(),'output':'test simulated'}


def test_receipt_internal_integrity_and_tamper_detection():
    args={'goal':'Repair the add function for integer sums',
          'code':'def add(a,b):\n    return a - b\n',
          'tests':'assert add(2,3)==5\n'}
    with patch('gotham.agents.run_isolated',side_effect=fake_docker), \
         patch('gotham.orchestrator.run_isolated',side_effect=fake_docker):
        result=run_mission(**args)
    ok,_=verify(result)
    assert ok
    result['goal']='maliciously changed goal'
    ok,_=verify(result)
    assert not ok
