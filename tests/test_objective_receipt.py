import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verify_receipt import verify
from gotham.objectives import run_objective
from gotham.inference import NoInference


def test_objective_receipt_internal_integrity():
    result=run_objective('Plan a secure system that runs at zero dollar cloud cost',client=NoInference())
    assert verify(result)[0]
    result['status']='faked_success'
    assert not verify(result)[0]
