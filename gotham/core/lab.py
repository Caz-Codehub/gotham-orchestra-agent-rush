"""Authorized security laboratory: scoped validation against a deliberately vulnerable LOCAL target.

Guarantees enforced in code (not by prompt):
  * target containers exist only on `gotham-lab`, a Docker --internal network with no route out;
  * the prober runs in that network, so it cannot reach anything else;
  * lab_probe accepts ONLY the target the same task started via lab_start (scope list), anything else is a
    `scope_violation` audit event and a denial;
  * lab_start / lab_probe / lab_stop are high-risk tools: they require explicit Batman approval per task;
  * probes are a fixed catalogue of benign checks (canary file read, auth-bypass marker, reflection) - no payload
    free-form input, no exploitation of anything beyond the lab canary.
"""
from __future__ import annotations
import json
import subprocess
import time
import uuid

from . import sbx
from .tools import ToolDenied, ToolError, tool

NETWORK = 'gotham-lab'
PROBER = r'''
import json, sys, urllib.request, urllib.parse
base = sys.argv[1]
def get(path):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as r:
            return r.status, dict(r.headers), r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode('utf-8', 'replace')
    except Exception as e:
        return 0, {}, repr(e)
checks = set(sys.argv[2].split(','))
res = {}
if 'health' in checks:
    s, h, b = get('/health'); res['health'] = {'vulnerable': False, 'status': s, 'evidence': b[:40]}
if 'sqli_login' in checks:
    s, h, b = get('/login?' + urllib.parse.urlencode({'user': "admin' --", 'pw': 'x'}))
    res['sqli_login'] = {'vulnerable': 'WELCOME admin' in b, 'status': s, 'evidence': b[:60], 'cwe': 'CWE-89'}
if 'path_traversal' in checks:
    s, h, b = get('/file?name=' + urllib.parse.quote('../canary.txt'))
    res['path_traversal'] = {'vulnerable': 'GOTHAM_LAB_CANARY' in b, 'status': s, 'evidence': b[:40], 'cwe': 'CWE-22'}
if 'reflected_xss' in checks:
    marker = '<gotham-xss-marker>'
    s, h, b = get('/search?q=' + urllib.parse.quote(marker))
    res['reflected_xss'] = {'vulnerable': marker in b, 'status': s, 'evidence': b[:80], 'cwe': 'CWE-79'}
if 'security_headers' in checks:
    s, h, b = get('/')
    low = {k.lower() for k in h}
    missing = [x for x in ('x-content-type-options', 'content-security-policy') if x not in low]
    res['security_headers'] = {'vulnerable': bool(missing), 'status': s, 'evidence': 'missing: ' + ','.join(missing), 'cwe': 'CWE-693'}
print('GOTHAM_PROBE ' + json.dumps(res))
'''
ALL_CHECKS = ['health', 'sqli_login', 'path_traversal', 'reflected_xss', 'security_headers']


def _docker(*args, timeout=60):
    return subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout)


def _ensure_network():
    if _docker('network', 'inspect', NETWORK).returncode != 0:
        r = _docker('network', 'create', '--internal', '--label', 'gotham=1', NETWORK)
        if r.returncode != 0:
            raise ToolError('cannot create isolated lab network: ' + r.stderr[-200:])


@tool('lab_start', 'Start the deliberately vulnerable lab target on the isolated internal network. Adds it to this task\'s authorized scope.',
      {'secure': ('bool', False, 'start the remediated build to verify fixes')}, ('Cipher', 'Sentinel'), risk='high')
def lab_start(ctx, secure=False):
    sbx.ensure_image('gotham-lab-target:latest')
    sbx.ensure_image('gotham-sandbox:latest')
    _ensure_network()
    name = 'gotham-lab-' + uuid.uuid4().hex[:10]
    r = _docker('run', '-d', '--name', name, '--label', 'gotham=1', '--label', 'gotham-lab=1', '--network', NETWORK, '--read-only',
                '--cap-drop=ALL', '--security-opt=no-new-privileges', '--memory=128m', '--pids-limit=64', '--cpus=0.5',
                '-e', f'GOTHAM_LAB_SECURE={"1" if secure else "0"}', 'gotham-lab-target:latest')
    if r.returncode != 0:
        raise ToolError('lab target failed to start: ' + r.stderr[-200:])
    ctx.scope.setdefault('targets', []).append(name)
    ctx.record('lab_target_started', {'target': name, 'network': NETWORK, 'secure_build': secure})
    for _ in range(15):
        out = _probe(ctx, name, ['health'])
        if out.get('health', {}).get('status') == 200:
            return {'target': name, 'network': NETWORK, 'internal_only': True, 'secure_build': secure}
        time.sleep(1)
    _docker('rm', '-f', name)
    raise ToolError('lab target did not become healthy')


def _probe(ctx, target, checks):
    r = sbx.run('gotham-sandbox:latest', ['python', '-c', PROBER, f'http://{target}:8080', ','.join(checks)], network=NETWORK, timeout=40,
                memory='64m', pids=32)
    import re
    m = re.search(r'GOTHAM_PROBE (\{.*\})', r['stdout'])
    return json.loads(m.group(1)) if m else {}


@tool('lab_probe', 'Run the fixed catalogue of benign validation checks against an in-scope lab target.',
      {'target': ('str', True, 'lab target container name'), 'checks': ('list', False, f'subset of {ALL_CHECKS}')},
      ('Cipher', 'Sentinel'), risk='high')
def lab_probe(ctx, target, checks=None):
    if target not in ctx.scope.get('targets', []):
        ctx.record('scope_violation', {'tool': 'lab_probe', 'target': str(target)[:80], 'authorized': ctx.scope.get('targets', [])})
        raise ToolDenied(f'target {target!r} is outside the authorized scope')
    checks = checks or ALL_CHECKS
    bad = [c for c in checks if c not in ALL_CHECKS]
    if bad:
        raise ToolError(f'unknown checks: {bad}')
    res = _probe(ctx, target, checks)
    vulns = [{'check': k, **v} for k, v in res.items() if v.get('vulnerable')]
    return {'target': target, 'network': NETWORK, 'results': res, 'vulnerabilities': vulns, 'checks_run': checks}


@tool('lab_stop', 'Stop and remove an in-scope lab target.', {'target': ('str', True, 'lab target name')}, ('Cipher', 'Sentinel'), risk='high')
def lab_stop(ctx, target):
    if target not in ctx.scope.get('targets', []):
        ctx.record('scope_violation', {'tool': 'lab_stop', 'target': str(target)[:80]})
        raise ToolDenied('target outside authorized scope')
    r = _docker('rm', '-f', target)
    ctx.scope['targets'].remove(target)
    gone = _docker('container', 'inspect', target).returncode != 0
    ctx.record('lab_target_removed', {'target': target, 'destroyed': gone})
    return {'removed': gone}
