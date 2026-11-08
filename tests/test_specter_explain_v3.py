from fastapi.testclient import TestClient
from gotham.app import app


def test_specter_read_only_answers_and_token(monkeypatch,tmp_path):
    monkeypatch.setenv('GOTHAM_SPECTER_DB',str(tmp_path/'audit.db'))
    monkeypatch.setenv('GOTHAM_BATMAN_TOKEN','private-audit-value')
    monkeypatch.setenv('GOTHAM_ACCESS_TOKEN','different-mission-value')
    with TestClient(app) as c:
        from gotham.app import _specter
        _specter.record('a-test-mission','Alfred','mission_received',{})
        _specter.record('a-test-mission','software:captain','orchestra_captain_planned',{'source':'mock'})
        _specter.scan_once()
        path='/api/batman/specter/explain'
        data={'mission_id':'a-test-mission','question':'What did each agent do?'}
        assert c.post(path,json=data,headers={'X-Batman-Token':'different-mission-value'}).status_code==401
        r=c.post(path,json=data,headers={'X-Batman-Token':'private-audit-value'})
        assert r.status_code==200
        assert 'software:captain' in r.json()['answer']
        assert 'recorded event metadata only' in r.json()['answer']
