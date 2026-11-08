from pathlib import Path
import pytest
from scripts.prove_local_agents import prove

class LocalFake:
    provider_name='ollama-local'
    configured=True
    def __init__(self): self.call_count=0
    def json(self,system,user,*,max_tokens=450):
        self.call_count+=1
        if 'You are Captain Alfred. You command' in system:
            return {'assignments':{name:'Review the example goal from a distinct '+name+' perspective'
                    for name in ['Scout','Forge','Oracle','Sentinel','Cipher']}}
        if 'You are Captain Alfred. Synthesize' in system:
            return {'summary':'Five AI analyses received, none externally verified.','priorities':['Local test'],
                    'open_questions':['Real execution needed']}
        return {'finding':'One specialist report, not a real tool call','recommendations':['test'],'unknowns':['validation'],
                'confidence':'low'}


def test_first_mission_writes_local_only_proof(tmp_path):
    from gotham.specter import SpecterJournal
    fake=LocalFake()
    passed,result,path=prove(client=fake,journal=SpecterJournal(tmp_path/'audit.sqlite3'),
                             receipt_dir=tmp_path/'proofs')
    assert passed
    assert path.exists()
    assert result['model_calls']==7
    assert result['verified_outcomes'] is False


def test_first_mission_rejects_offline_and_paid_backends(tmp_path):
    from gotham.inference import NoInference
    with pytest.raises(RuntimeError,match='Local Ollama'):
        prove(client=NoInference(),receipt_dir=tmp_path)
    fake=LocalFake();fake.provider_name='vultr-serverless-inference'
    with pytest.raises(RuntimeError,match='Local Ollama'):
        prove(client=fake,receipt_dir=tmp_path)
