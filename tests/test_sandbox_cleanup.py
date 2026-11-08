from unittest.mock import patch
import subprocess
from gotham.sandbox import run_isolated

def test_normal_docker_requires_real_cleanup_proof():
    def fake(cmd,**kw):
        if cmd[1]=='run':return subprocess.CompletedProcess(cmd,0,'GOTHAM_TESTS_PASSED','')
        if cmd[1]=='container':return subprocess.CompletedProcess(cmd,1,'','Error: No such object: x')
        raise AssertionError(cmd)
    with patch('gotham.sandbox.subprocess.run',side_effect=fake):
        receipt=run_isolated('x=1','assert x==1')
    assert receipt['passed'] and receipt['container_destroyed'] is True

def test_cleanup_uncertain_must_not_be_verified():
    def fake(cmd,**kw):
        if cmd[1]=='run':return subprocess.CompletedProcess(cmd,0,'GOTHAM_TESTS_PASSED','')
        if cmd[1]=='container':return subprocess.CompletedProcess(cmd,2,'','Docker daemon unavailable')
        raise AssertionError(cmd)
    with patch('gotham.sandbox.subprocess.run',side_effect=fake):
        receipt=run_isolated('x=1','assert x==1')
    assert receipt['passed'] and receipt['container_destroyed'] is False

def test_docker_recover_and_flag_if_container_lingers():
    recorded=[]
    def fake(cmd,**kw):
        recorded.append(cmd)
        if cmd[1]=='run':return subprocess.CompletedProcess(cmd,0,'GOTHAM_TESTS_PASSED','')
        if cmd[1]=='container':return subprocess.CompletedProcess(cmd,0,'container ID','')
        if cmd[1]=='rm':return subprocess.CompletedProcess(cmd,0,'removed','')
        raise AssertionError(cmd)
    with patch('gotham.sandbox.subprocess.run',side_effect=fake):
        receipt=run_isolated('x=1','assert x==1')
    assert receipt['container_destroyed'] is False
    assert any(cmd[1:3]==['rm','-f'] for cmd in recorded)
