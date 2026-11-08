"""Runs real Docker sandboxes only when explicitly requested; never mocks them."""
import os
import subprocess
import pytest
from gotham.sandbox import run_isolated, containment_probe

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get('GOTHAM_RUN_DOCKER_TESTS') != '1',
    reason='Requires Docker Engine, pre-pulled image and GOTHAM_RUN_DOCKER_TESTS=1')]


def test_real_docker_pass_and_fail():
    # This must fail loudly if Docker is not working in an enabled CI job.
    subprocess.run(['docker','info'], check=True, capture_output=True, timeout=10)
    passed=run_isolated('def add(a,b): return a+b\n','assert add(2,3)==5',timeout=15)
    failed=run_isolated('def add(a,b): return a-b\n','assert add(2,3)==5',timeout=15)
    assert passed['sandbox']=='docker' and passed['network']=='none'
    assert passed['passed'] and passed['container_destroyed'] and not passed['timed_out']
    assert not failed['passed'] and failed['exit_code'] != 0


def test_real_docker_containment_timeout():
    probe=containment_probe()
    assert probe['contained'] is True
    assert probe['evidence']['timed_out'] is True
    assert probe['evidence']['container_destroyed'] is True
