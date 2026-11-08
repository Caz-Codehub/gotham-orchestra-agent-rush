"""Bounded, deterministic four-orchestra artifact demonstration.

This is NOT unrestricted AI-written software. The AI orchestras make distinct
reasoning calls and the artifact engine safely produces fixed, reviewable task
examples; every executed check runs only inside the Docker sandbox.
"""
from __future__ import annotations
import base64
import hashlib
import html
import io
import json
import zipfile
from .sandbox import run_isolated


def _title(goal: str) -> str:
    return html.escape(goal[:70].strip(), quote=True)


def build_demo_artifact(orchestra: str, goal: str, scope: str = '') -> dict:
    """Create a small verifiable artifact for the selected orchestra."""
    title = _title(goal)
    manifest = {'orchestra':orchestra, 'goal':goal[:150],
                'generator':'deterministic reviewable demo artifact engine',
                'model_code_generation':False,
                'warning':'Example task template, not unrestricted autonomous project generation'}
    if orchestra == 'software':
        page = ('<!doctype html><html><head><meta charset="utf-8"><title>Gotham demo</title>'
                '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
                '<body><main><h1>Gotham Software Orchestra</h1><p id="objective">'
                +title+'</p><label>Task<input id="task" maxlength="100"></label>'
                '<button id="add">Add</button><ul id="tasks"></ul></main>'
                '<script>document.getElementById("add").onclick=()=>{const input=document.getElementById("task");'
                'if(!input.value.trim())return;const li=document.createElement("li");'
                'li.textContent=input.value;document.getElementById("tasks").append(li);input.value=""}</script>'
                '</body></html>')
        files={'index.html':page,'README.md':'Open index.html in a modern browser. Enter a task and click Add.\n'}
        code='from html.parser import HTMLParser\nfrom pathlib import Path\npage='+repr(page)+'\n'
        tests='assert "Gotham Software Orchestra" in page\nassert "textContent=input.value" in page\nassert "innerHTML=input.value" not in page\nprint("Web app HTML and safe DOM update checks passed")'
    elif orchestra == 'defense':
        vulnerable=('def display(value):\n    return "<p>" + value + "</p>"\n')
        secure=('from html import escape\n'
                'def display(value):\n    if not isinstance(value,str) or len(value)>200:\n'
                '        raise ValueError("Rejected invalid input")\n'
                '    return "<p>" + escape(value, quote=True) + "</p>"\n'
                'SECURITY_HEADERS = {"Content-Security-Policy": "default-src \'self\'; object-src \'none\'",\n'
                ' "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}\n')
        files={'before.py':vulnerable,'hardened.py':secure,
               'README.md':'Inspect before.py and hardened.py. Docker tests verify escaping, validation, and required headers.\n'}
        code=secure
        tests='assert display("<script>alert(1)</script>") == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"\n'
        tests+='assert display("hello") == "<p>hello</p>"\n'
        tests+='try:\n    display("x"*300)\n    assert False, "Should reject oversized input"\nexcept ValueError:\n    pass\n'
        tests+='assert "Content-Security-Policy" in SECURITY_HEADERS\nprint("Defense hardening controls verified")'
    elif orchestra == 'research':
        research_code=('import statistics\n'
                       'samples = [3, 5, 7, 9, 11]\n'
                       'mean = statistics.mean(samples)\n'
                       'median = statistics.median(samples)\n'
                       'print(f"synthetic_n={len(samples)} mean={mean} median={median}")\n')
        notebook={'cells':[{'cell_type':'markdown','metadata':{},'source':['# Reproducible Gotham research demo\n',
                     'Synthetic data only; no empirical observations or external sources were used.\n',
                     'User objective: '+goal[:200]+'\n']},
                     {'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],
                      'source':research_code.splitlines(keepends=True)}],
                 'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},
                 'nbformat':4,'nbformat_minor':5}
        files={'experiment.ipynb':json.dumps(notebook,indent=2),
               'README.md':'Open experiment.ipynb in Jupyter. The same synthetic computation is checked in Docker. Notebook cells have not been executed inside Jupyter.\n'}
        code=research_code
        tests='assert samples == [3,5,7,9,11]\nassert mean == 7 and median == 7\nprint("Synthetic research calculation verified")'
    elif orchestra == 'lab':
        if len(scope.strip())<12:
            raise ValueError('Authorized lab scope must be provided')
        code=('from pathlib import Path\n'
              'lab = Path("/tmp/gotham-harmless-lab")\nlab.mkdir(exist_ok=True)\n'
              '(lab / "synthetic_behavior_marker.txt").write_text("SIMULATED suspicious file change; no malware code")\n'
              'evidence = (lab / "synthetic_behavior_marker.txt").read_text()\n'
              'print("Harmless isolated filesystem behavior emulation completed")\n')
        files={'emulator.py':code, 'README.md':('Authorized lab scope: '+scope[:250]+'\n'
                    'Emulator writes a synthetic marker only in a disposable sandbox /tmp directory. '
                    'No persistence, networking, infection or exfiltration. Run the separate containment probe for infinite-loop timeout evidence.\n')}
        tests='assert "SIMULATED" in evidence\nassert lab.exists()\nassert "exfiltration" not in evidence.lower()\nprint("Safe lab simulation verified")'
    else:
        raise ValueError('Unknown orchestra')
    files['gotham_manifest.json']=json.dumps(manifest,indent=2)
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name, text in files.items(): z.writestr(name,text)
        binary=buffer.getvalue()
    return {'sandbox_code':code,'sandbox_tests':tests,'artifact_base64':base64.b64encode(binary).decode('ascii'),
            'artifact_filename':f'gotham-{orchestra}-demo.zip',
            'artifact_sha256':hashlib.sha256(binary).hexdigest(),
            'artifact_files':list(files), 'manifest':manifest}


def execute_demo(orchestra: str, goal: str, scope: str = '') -> dict:
    result=build_demo_artifact(orchestra, goal, scope)
    evidence=run_isolated(result.pop('sandbox_code'),result.pop('sandbox_tests'))
    return {**result,'evidence':evidence,
            'verified_execution':bool(evidence.get('passed') and evidence.get('container_destroyed'))}
