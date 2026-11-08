import base64
import io
import zipfile
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from gotham.app import app
from gotham.demo_artifacts import build_demo_artifact,execute_demo

@pytest.mark.parametrize('domain', ['software','research','defense','lab'])
def test_real_artifact_formats(domain):
    r=build_demo_artifact(domain,'Create a tested sample',scope='Offline owned Docker training lab')
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(r['artifact_base64']))) as z:
        assert 'gotham_manifest.json' in z.namelist()
        assert 'experiment.ipynb' in z.namelist() if domain=='research' else True
        assert 'index.html' in z.namelist() if domain=='software' else True
        assert 'hardened.py' in z.namelist() if domain=='defense' else True
        assert 'emulator.py' in z.namelist() if domain=='lab' else True
    assert len(r['artifact_sha256'])==64


def test_demo_marks_execution_only_after_docker_evidence():
    with patch('gotham.demo_artifacts.run_isolated',return_value={
        'passed':True,'container_destroyed':False,'sandbox':'docker','network':'none'}):
        r=execute_demo('research','Build a sample notebook')
    assert not r['verified_execution']


def test_specter_page_has_no_private_content_without_audit_token(monkeypatch,tmp_path):
    monkeypatch.setenv('GOTHAM_SPECTER_DB',str(tmp_path/'audit.db'))
    monkeypatch.setenv('GOTHAM_BATMAN_TOKEN','secret')
    with TestClient(app) as c:
        assert c.get('/specter').status_code == 200
        assert c.get('/api/batman/specter/missions').status_code == 401
