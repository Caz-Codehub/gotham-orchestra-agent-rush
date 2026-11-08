#!/usr/bin/env python3
"""Read-only, zero-spend environment check. No external API or billable calls."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gotham.inference import is_local_model_name


def check(cmd):
    try:
        done=subprocess.run(cmd,timeout=6,capture_output=True,text=True,check=False)
        return done.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False


def main():
    parser=argparse.ArgumentParser(description='Gotham readiness, no financial actions')
    parser.add_argument('--mode',choices=['objective','repair'],default='objective')
    args=parser.parse_args()
    provider=os.environ.get('GOTHAM_INFERENCE_PROVIDER','none').lower()
    docker=bool(shutil.which('docker'))
    daemon=docker and check(['docker','info','--format','{{.ServerVersion}}'])
    image=os.environ.get('GOTHAM_SANDBOX_IMAGE','python:3.12-alpine')
    local=False
    installed=False
    model=os.environ.get('GOTHAM_OLLAMA_MODEL','qwen2.5:1.5b')
    valid_local_name=is_local_model_name(model)
    if provider=='ollama':
        try:
            with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=1.5) as answer:
                if answer.status==200:
                    local=True
                    tags=json.load(answer).get('models',[])
                    installed=valid_local_name and any(
                        (tag.get('name')==model or tag.get('model')==model)
                        and int(tag.get('size',0) or 0) > 0 for tag in tags)
        except (OSError,urllib.error.URLError,TimeoutError): pass
    paid_opt_in=os.environ.get('GOTHAM_ALLOW_PAID_INFERENCE','')=='I_ACCEPT_POTENTIAL_CHARGES'
    facts={
      'selected_mode':args.mode,'python_supported':sys.version_info >= (3,11),
      'fastapi_installed':importlib.util.find_spec('fastapi') is not None,
      'pydantic_installed':importlib.util.find_spec('pydantic') is not None,
      'mission_token_set':bool(os.environ.get('GOTHAM_ACCESS_TOKEN')),
      'separate_batman_audit_token_set':bool(os.environ.get('GOTHAM_BATMAN_TOKEN')),
      'inference_provider':provider,'local_ollama_reachable':local,
      'selected_local_model':model if provider=='ollama' else None,
      'model_is_downloaded_not_cloud':bool(installed),
      'potentially_billable_vultr_calls_opted_in':provider=='vultr' and paid_opt_in,
      'docker_cli':docker,'docker_daemon_available':daemon,
      'sandbox_image_cached':daemon and check(['docker','image','inspect',image]),
      'no_external_cloud_inference_calls_made':True,'money_spent_by_this_check_usd':0,
      'vultr_deployment_verified':False,
    }
    needed=['python_supported','fastapi_installed','pydantic_installed','mission_token_set']
    if args.mode=='repair':needed+=['docker_daemon_available','sandbox_image_cached']
    facts['ready_for_selected_mode']=all(facts[k] for k in needed)
    if provider=='ollama':
        facts['ready_for_selected_mode']=facts['ready_for_selected_mode'] and bool(installed)
    facts['actual_ai_reasoning_available']=(provider=='ollama' and installed) or (provider=='vultr' and paid_opt_in)
    print(json.dumps(facts,indent=2))
    return 0 if facts['ready_for_selected_mode'] else 1

if __name__=='__main__':sys.exit(main())
