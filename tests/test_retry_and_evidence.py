"""Regression tests at mocked cloud/Docker boundaries. These are NOT live cloud tests."""
from __future__ import annotations
import hashlib
import threading
from unittest.mock import patch
from gotham.orchestrator import run_mission

SAMPLE = {'goal': 'Repair add so it sums numbers correctly',
          'code': 'def add(a,b):\n    return a - b\n',
          'tests': 'assert add(2,3) == 5\n'}


def simulated_container(code, tests, *, timeout=5):
    passed = 'return a + b' in code
    return {'passed': passed, 'timed_out': False, 'exit_code': 0 if passed else 1,
            'sandbox':'docker','network':'none','container_destroyed':True,
            'output': 'GOTHAM_TESTS_PASSED' if passed else 'AssertionError',
            'code_sha256':hashlib.sha256(code.encode()).hexdigest()}


class ModelStub:
    configured = True
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def json(self, system, user, *, max_tokens=450):
        with self.lock:
            self.messages.append(system)
        if 'independent tool-using AI worker' in system:
            import ast
            # Allowed tool names are printed as Python repr in the agent prompt.
            tool_list = system.split('one tool from ', 1)[1].split('. Choose',1)[0]
            return {'tool':ast.literal_eval(tool_list)[0], 'reason':'test decision'}
        if 'You are Forge, a code-repair agent' in system:
            return {'code':'def add(a,b):\n    return a * b\n', 'explanation':'wrong first patch'}
        if 'You are Forge repairing a failed Python patch' in system:
            assert 'AssertionError' in user
            return {'code':'def add(a,b):\n    return a + b\n', 'explanation':'fixed on retry'}
        if 'You are Captain Alfred, the coordinating AI' in system:
            return {'assessment':'both runs have evidence', 'recommend_approval': True}
        raise AssertionError('Unexpected model request')


def test_one_model_retry_repairs_failed_first_attempt():
    model = ModelStub()
    with patch('gotham.agents.run_isolated',side_effect=simulated_container), \
         patch('gotham.orchestrator.run_isolated',side_effect=simulated_container):
        out = run_mission(**SAMPLE,client=model)
    assert out['status']=='verified' and out['approval']
    assert [a['passed'] for a in out['attempts']] == [False,True]
    assert len(out['attempts'])==2
    assert out['candidate_code'].strip().endswith('return a + b')
    assert out['candidate_source']=='vultr-serverless-inference (retry)'
    assert any(e.get('action')=='repair_retry' for e in out['events'])
    assert len([m for m in model.messages if 'repairing a failed' in m])==1
    assert len([m for m in model.messages if 'You are Captain Alfred, the coordinating AI' in m])==1


def test_does_not_approve_when_container_cleanup_unproven():
    def no_cleanup(*args,**kwargs):
        return {**simulated_container(*args,**kwargs),'container_destroyed':False}
    with patch('gotham.agents.run_isolated',side_effect=simulated_container), \
         patch('gotham.orchestrator.run_isolated',side_effect=no_cleanup):
        result=run_mission(**SAMPLE)
    assert result['approval'] is False
    assert result['status']=='not_verified'


def test_does_not_approve_wrong_code_digest():
    def wrong_digest(*args,**kwargs):
        return {**simulated_container(*args,**kwargs),'code_sha256':'0'*64}
    with patch('gotham.agents.run_isolated',side_effect=simulated_container), \
         patch('gotham.orchestrator.run_isolated',side_effect=wrong_digest):
        result=run_mission(**SAMPLE)
    assert result['approval'] is False


def test_model_failure_cannot_claim_vultr_inference():
    from gotham.inference import InferenceError
    class Unavailable(ModelStub):
        def json(self,*args,**kwargs):
            raise InferenceError('cloud unavailable')
    with patch('gotham.agents.run_isolated',side_effect=simulated_container), \
         patch('gotham.orchestrator.run_isolated',side_effect=simulated_container):
        result=run_mission(**SAMPLE,client=Unavailable())
    assert 'NOT CONTEST COMPLIANT' in result['inference']
    assert not result['approval']
    assert result['attempts']==[]
