from fastapi.testclient import TestClient
from gotham.app import app
from gotham.specter import SpecterJournal
from gotham.orchestras import run_orchestra
from test_orchestras import FakeClient


def test_orchestra_audit_identities_and_no_worker_specter_disclosure(tmp_path):
    journal=SpecterJournal(tmp_path/'audit.sqlite3')
    result=run_orchestra('research','Draft reproducible notebook experiments',client=FakeClient(),
       telemetry=lambda mission,actor,action,detail:journal.record(mission,actor,action,detail))
    journal.scan_once()
    report=journal.mission_report(result['mission_id'])
    names={e['actor'] for e in report['events']}
    assert {'research:captain','research:Research Librarian','research:Methods Architect',
            'research:Reproducibility Reviewer','Alfred'}.issubset(names)
    assert not any(f['code']=='UNKNOWN_ACTOR' for f in report['findings'])
    assert report['integrity']['valid']
    assert journal.recent_missions()[0]['mission_id']==result['mission_id']


def test_specter_separate_dashboard_requires_distinct_token(monkeypatch,tmp_path):
    monkeypatch.setenv('GOTHAM_SPECTER_DB',str(tmp_path/'audit.sqlite3'))
    monkeypatch.setenv('GOTHAM_BATMAN_TOKEN','batman-audit-only')
    monkeypatch.setenv('GOTHAM_ACCESS_TOKEN','mission-only')
    with TestClient(app) as client:
        assert client.get('/specter').status_code==200
        assert client.get('/api/batman/specter/missions').status_code==401
        assert client.get('/api/batman/specter/missions',headers={'X-Batman-Token':'mission-only'}).status_code==401
        res=client.get('/api/batman/specter/missions',headers={'X-Batman-Token':'batman-audit-only'})
        assert res.status_code==200
        assert 'missions' in res.json()
        assert 'integrity' in res.json()['status']
