#!/usr/bin/env python3
"""Read-only local inference proof: Batman -> Alfred -> 5 workers; Specter audits.

This sends a simple synthetic objective to a model listening on 127.0.0.1 only.
It creates local receipt files, and does not execute a browser, shell agent, or Docker.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gotham.inference import get_inference_client
from gotham.objectives import run_objective
from gotham.specter import SpecterJournal

DEFAULT_GOAL=('Design a small offline task manager for college students. '
              'Each agent should give a distinct actionable recommendation and a validation approach.')


def prove(*,client=None,goal=DEFAULT_GOAL,journal=None,receipt_dir=None):
    client=client or get_inference_client()
    if not client.configured or client.provider_name != 'ollama-local':
        raise RuntimeError('Local Ollama model not ready; no cloud calls were attempted. '
                           'Start Ollama, pull the model, set GOTHAM_INFERENCE_PROVIDER=ollama.')
    journal=journal or SpecterJournal()
    result=run_objective(goal,client=client,telemetry=journal.record)
    findings=journal.scan_once()
    valid=journal.verify()['valid']
    names={'Scout','Forge','Oracle','Sentinel','Cipher'}
    passed=(result['status']=='analysis_ready' and set(result['worker_reports'])==names
            and all(x['status']=='analysis_completed' for x in result['worker_reports'].values())
            and result['plan_source']=='ollama-local' and result['model_calls']>=7
            and valid and not result['external_actions_executed']
            and not result['verified_outcomes'])
    data=Path(receipt_dir or (Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.local/share'))) / 'GothamProject' / 'proofs'))
    data.mkdir(parents=True, exist_ok=True)
    receipt_path=data / (result['mission_id']+'.json')
    receipt_path.write_text(json.dumps({'objective_result':result,'specter_findings':findings,
                          'specter_journal_valid':valid,'local_ai_proof_passed':passed},
                          indent=2,ensure_ascii=False),encoding='utf-8')
    try: receipt_path.chmod(0o600)
    except OSError: pass
    return passed,result,receipt_path


def main():
    parser=argparse.ArgumentParser(description='Gotham local Ollama proof. No paid cloud endpoints.')
    parser.add_argument('--goal',default=DEFAULT_GOAL)
    args=parser.parse_args()
    try:
        passed,result,receipt_path=prove(goal=args.goal)
    except RuntimeError as exc:
        print(f'NOT READY: {exc}',file=sys.stderr)
        return 2
    print('\nGOTHAM: REAL LOCAL MODEL PROOF')
    print('Backend:',result['model_backend'])
    print('Alfred plan source:',result['plan_source'])
    print('Model completions:',result['model_calls'])
    print('Five worker outcomes:')
    for name, report in result['worker_reports'].items():
        print(' ',name,':',report['status'])
    print('Mission status:',result['status'])
    print('Specter receipt:',receipt_path)
    print('Result:', 'PASS: 5 reports + Alfred + Specter evidence' if passed else 'INCOMPLETE: see receipt')
    print('Important: reports are AI analysis, NOT independently verified external actions.')
    return 0 if passed else 1

if __name__=='__main__':
    sys.exit(main())
