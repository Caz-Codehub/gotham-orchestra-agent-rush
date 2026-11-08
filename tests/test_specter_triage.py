from gotham.specter import SpecterJournal, investigate_alert_locally

class SpecterModel:
    configured=True
    provider_name='ollama-local'
    def json(self, system, user, *, max_tokens=350):
        assert 'You are Specter' in system
        assert 'SECRET_CODE' not in user
        return {'assessment':'Suspicious unauthorized tool was reported, pending evidence.',
                'recommended_action':'Batman should inspect the event chain.'}

class PaidModel(SpecterModel):
    provider_name='vultr-serverless-inference'


def test_independent_local_only_incident_triage(tmp_path):
    journal=SpecterJournal(tmp_path/'triage.db')
    journal.record('m','Batman','mission_received')
    journal.record('m','Forge','worker_finished',{'tool':'forbidden_cmd'})
    alert=journal.scan_once()[0]
    assert alert['code']=='TOOL_POLICY'
    assert investigate_alert_locally(journal,alert,client=PaidModel()) is False
    assert investigate_alert_locally(journal,alert,client=SpecterModel()) is True
    status=journal.status()['recent_alerts'][0]
    assert 'Suspicious' in status['ai_assessment']
    assert 'Batman' in status['ai_recommendation']
    assert journal.verify()['valid']
