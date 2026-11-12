"""Deterministic, audited task playbooks. Each is a fixed sequence of REAL tool calls (no model needed);
agent-mode tasks (model-driven) use gotham.core.runtime instead. Receipts label which mode produced a result."""
from __future__ import annotations
import base64
import hashlib
import json
from collections import Counter
from pathlib import Path

from .. import tools as T
from ..tools import call


def _seed(ctx, files: dict):
    for rel, content in (files or {}).items():
        call(ctx, 'fs_write', {'path': rel, 'content': content})


def _write_json(ctx, name, obj):
    call(ctx, 'fs_write', {'path': name, 'content': json.dumps(obj, indent=2, default=str)})
    return name


def _artifact(ctx, path, name=''):
    return call(ctx, 'emit_artifact', {'path': path, 'name': name or path})


# ---------------------------------------------------------------- Scout
def scout_recon(ctx, p):
    inv = call(ctx, 'fs_list', {})['items']
    files = [i for i in inv if i['type'] == 'file']
    ext = Counter(Path(i['path']).suffix or '(none)' for i in files)
    manifests = [i['path'] for i in files if Path(i['path']).name in
                 ('requirements.txt', 'pyproject.toml', 'package.json', 'Dockerfile', 'docker-compose.yml', 'Makefile')]
    tests = [i['path'] for i in files if 'test' in Path(i['path']).name.lower()]
    loc = 0
    for i in files:
        if i['path'].endswith(('.py', '.js', '.ts', '.go', '.rs', '.java')):
            loc += call(ctx, 'fs_read', {'path': i['path']})['content'].count('\n') + 1
    res = {'files': len(files), 'languages_by_ext': dict(ext), 'manifests': manifests, 'test_files': tests, 'loc': loc}
    _write_json(ctx, 'recon.json', res)
    res['artifact'] = _artifact(ctx, 'recon.json', 'recon.json')['artifact_id']
    return {'status': 'ok', 'summary': f'{len(files)} files, {loc} LOC, {len(tests)} test files', 'evidence': res}


# ---------------------------------------------------------------- Forge
def forge_build_and_verify(ctx, p, client=None):
    ev = {}
    call(ctx, 'git_init', {})
    base = call(ctx, 'git_commit', {'message': 'baseline import'})
    ev['baseline_commit'] = base['commit']
    if p.get('install'):
        ev['install'] = {k: v for k, v in call(ctx, 'install_deps', {}).items() if k in ('ok', 'exit_code', 'elapsed_ms')}
    before = call(ctx, 'run_tests', {})
    ev['tests_before'] = {'ok': before['ok'], 'summary': before['summary'], 'exit_code': before['exit_code'],
                          'container_destroyed': before['container_destroyed'], 'output_tail': (before['stdout'] + before['stderr'])[-800:]}
    repaired_by = None
    if not before['ok']:
        if p.get('patch'):
            _seed(ctx, p['patch'])
            repaired_by = 'supplied-patch'
        elif client is not None and getattr(client, 'configured', False):
            from .. import runtime
            fix = runtime.run_agent(ctx, client, 'Software Engineer',
                                    'The test-suite fails. Inspect the code and tests, repair the source (not the tests), and re-run run_tests. '
                                    f'Mission goal: {p.get("goal", "make tests pass")}')
            ev['agent_repair'] = {'steps': fix['steps'], 'claimed': fix['final'], 'provider': fix['provider']}
            repaired_by = 'model:' + fix['provider']
        else:
            return {'status': 'failed', 'summary': 'tests fail and no repair source (patch or configured model) is available',
                    'evidence': ev, 'blocked_reason': 'no_repair_source'}
    after = call(ctx, 'run_tests', {}) if repaired_by else before
    ev['tests_after'] = {'ok': after['ok'], 'summary': after['summary'], 'exit_code': after['exit_code'],
                         'container_destroyed': after['container_destroyed']}
    ev['repaired_by'] = repaired_by
    if not after['ok']:
        return {'status': 'failed', 'summary': 'tests still failing after repair attempt', 'evidence': ev}
    call(ctx, 'git_branch', {'name': p.get('branch', 'gotham/forge-change')})
    commit = call(ctx, 'git_commit', {'message': p.get('commit_message', 'Gotham Forge: verified change')})
    ev['commit'] = commit['commit']
    diff_text = T.call(ctx, 'git_diff', {})['diff']
    import subprocess
    show = T._git(ctx, 'diff', ev['baseline_commit'], ev['commit']).stdout
    call(ctx, 'fs_write', {'path': '_change.patch', 'content': show})
    ev['patch_artifact'] = _artifact(ctx, '_change.patch', 'change.patch')['artifact_id']
    ev['diff_lines'] = len(show.splitlines())
    return {'status': 'ok', 'summary': f'tests {before["summary"]} -> {after["summary"]}; committed {commit["commit"][:10]}', 'evidence': ev}


# ---------------------------------------------------------------- Sentinel
SEV = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}


def sentinel_audit(ctx, p):
    scans, findings = [], []
    sg = call(ctx, 'semgrep_scan', {})
    scans.append({'engine': sg['engine'], 'version': sg['version'], 'rules': sg['rules'], 'findings': len(sg['findings'])})
    findings += [{**f, 'engine': 'semgrep'} for f in sg['findings']]
    sc = call(ctx, 'secrets_scan', {})
    scans.append({'engine': sc['engine'], 'findings': len(sc['findings'])})
    findings += [{**f, 'engine': 'secrets'} for f in sc['findings']]
    ca = call(ctx, 'config_audit', {})
    scans.append({'engine': ca['engine'], 'findings': len(ca['findings'])})
    findings += [{**f, 'engine': 'config'} for f in ca['findings']]
    if any(i['path'] == p.get('requirements', 'requirements.txt') for i in call(ctx, 'fs_list', {})['items']):
        try:
            da = call(ctx, 'dep_audit', {'requirements': p.get('requirements', 'requirements.txt')})
            scans.append({'engine': da['engine'], 'dependencies_checked': da['dependencies_checked'], 'findings': len(da['findings'])})
            findings += [{**f, 'engine': 'pip-audit'} for f in da['findings']]
        except T.ToolError as exc:
            scans.append({'engine': 'pip-audit', 'status': 'unavailable', 'error': str(exc)[:200]})
    findings.sort(key=lambda f: -SEV.get(f['severity'], 0))
    report = {'scans': scans, 'findings': findings,
              'counts': dict(Counter(f['severity'] for f in findings)),
              'remediation': sorted({f"{f['rule']}: {f['message']}" for f in findings})[:30]}
    _write_json(ctx, 'security_report.json', report)
    aid = _artifact(ctx, 'security_report.json', 'security_report.json')['artifact_id']
    expect = p.get('expect_rules') or []
    found_rules = {f['rule'] for f in findings}
    missing = [r for r in expect if r not in found_rules]
    status = 'ok' if not missing else 'failed'
    return {'status': status, 'summary': f'{len(findings)} findings {report["counts"]}' + (f'; MISSING expected {missing}' if missing else ''),
            'evidence': {**report, 'artifact': aid, 'expected_rules_missing': missing}}


def sentinel_logs(ctx, p):
    la = call(ctx, 'log_analyze', {'path': p['log'], 'threshold': p.get('threshold', 5)})
    ev = {'log_findings': la['findings']}
    if p.get('sigma_rule') and p.get('sigma_events'):
        ev['sigma'] = call(ctx, 'sigma_eval', {'rule': p['sigma_rule'], 'events': p['sigma_events']})
    _write_json(ctx, 'log_report.json', ev)
    ev['artifact'] = _artifact(ctx, 'log_report.json', 'log_report.json')['artifact_id']
    return {'status': 'ok', 'summary': f'{len(la["findings"])} correlated detections', 'evidence': ev}


# ---------------------------------------------------------------- Cipher
def cipher_malware(ctx, p):
    s = p['sample']
    raw = base64.b64decode(s['content_b64']) if s.get('content_b64') else s['content'].encode()
    name = Path(s['name']).name
    sample_path = f'samples/{name}'
    call(ctx, 'fs_write', {'path': sample_path, 'content': raw.decode('latin-1')}) if False else None
    ctx.path('samples').mkdir(exist_ok=True)
    ctx.path(sample_path).write_bytes(raw)  # quarantined data file; never executed on host
    ctx.record('sample_quarantined', {'name': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'approved_inert': bool(p.get('approved_inert'))})
    triage = call(ctx, 'file_triage', {'path': sample_path})
    rule_name = 'gotham_' + hashlib.sha256(raw).hexdigest()[:12]
    ev = {'triage': triage}
    gen = call(ctx, 'yara_generate', {'path': sample_path, 'rule_name': rule_name})
    negatives = []
    for i, benign in enumerate(p.get('benign', ['print("hello world")\n', 'def add(a, b):\n    return a + b\n'])):
        np_ = f'samples/benign_{i}.txt'
        ctx.path(np_).write_text(benign)
        negatives.append(np_)
    val = call(ctx, 'yara_validate', {'rule_path': gen['rule_path'], 'positive': [sample_path], 'negative': negatives})
    ev['yara'] = {'rule': gen['rule'], 'validation': val}
    if p.get('dynamic'):
        ev['behavior'] = call(ctx, 'sandbox_behavior', {'path': sample_path})
    _artifact(ctx, gen['rule_path'], gen['rule_path'])
    _write_json(ctx, 'analysis.json', ev)
    ev['artifact'] = _artifact(ctx, 'analysis.json', 'malware_analysis.json')['artifact_id']
    ok = val['valid'] and gen['compiles']
    return {'status': 'ok' if ok else 'failed', 'summary': f'{triage["classification"]}; sha256 {triage["sha256"][:12]}; yara valid={val["valid"]}',
            'evidence': ev}


# ---------------------------------------------------------------- Oracle
def oracle_research(ctx, p):
    ev = {'compute': call(ctx, 'compute_info', {})}
    nb = call(ctx, 'notebook_create', {'name': p['name'], 'cells': p['cells']})
    run = call(ctx, 'notebook_execute', {'name': p['name'], 'timeout': p.get('timeout', 300)})
    ev['notebook'] = {**nb, **run}
    if not run['ok']:
        return {'status': 'failed', 'summary': 'notebook did not execute successfully: ' + str(run.get('error'))[:300], 'evidence': ev}
    ev['executed_artifact'] = _artifact(ctx, run['executed_notebook'], run['executed_notebook'])['artifact_id']
    tr = p.get('train')
    if tr:
        first = call(ctx, 'train_model', {'epochs': tr['epochs'], 'stop_after': tr.get('interrupt_at', 0)})
        ev['training_first_run'] = first
        if first['interrupted']:
            second = call(ctx, 'train_model', {'epochs': tr['epochs'], 'resume': True})
            ev['training_resumed_run'] = second
            final = second
        else:
            final = first
        ev['training_final'] = final
        if not final['ok']:
            return {'status': 'failed', 'summary': 'training failed', 'evidence': ev}
        ev['metrics_artifact'] = _artifact(ctx, 'metrics.jsonl', 'metrics.jsonl')['artifact_id']
        _artifact(ctx, 'final.json', 'final.json')
    return {'status': 'ok', 'summary': 'notebook executed (' + str(ev['notebook'].get('executed_cells')) + ' cells)'
            + ('; training resumed from checkpoint' if tr and ev.get('training_resumed_run', {}).get('resumed') else ''), 'evidence': ev}


# ---------------------------------------------------------------- Security lab
def lab_scoped_validation(ctx, p):
    ev = {}
    secure = bool(p.get('secure'))
    st = call(ctx, 'lab_start', {'secure': secure})
    target = st['target']
    try:
        probe = call(ctx, 'lab_probe', {'target': target})
        ev['probe'] = probe
        # scope enforcement self-test: an out-of-scope target must be refused
        try:
            call(ctx, 'lab_probe', {'target': 'example.com', 'checks': ['health']})
            ev['scope_enforced'] = False
        except T.ToolDenied:
            ev['scope_enforced'] = True
    finally:
        ev['stopped'] = call(ctx, 'lab_stop', {'target': target})
    ev['secure_build'] = secure
    expected = p.get('expect_vulnerable')
    vulns = {v['check'] for v in ev['probe']['vulnerabilities']}
    if expected is not None:
        ok = (vulns == set(expected)) if expected else not vulns
    else:
        ok = True
    ok = ok and ev['scope_enforced'] and ev['stopped']['removed']
    _write_json(ctx, 'lab_report.json', ev)
    ev['artifact'] = _artifact(ctx, 'lab_report.json', 'lab_report.json')['artifact_id']
    return {'status': 'ok' if ok else 'failed', 'summary': f'{"secure" if secure else "vulnerable"} build: findings {sorted(vulns)}; scope enforced={ev["scope_enforced"]}',
            'evidence': ev}


PLAYBOOKS = {
    ('Scout', 'recon'): scout_recon,
    ('Forge', 'build_and_verify'): forge_build_and_verify,
    ('Sentinel', 'audit'): sentinel_audit,
    ('Sentinel', 'log_analysis'): sentinel_logs,
    ('Cipher', 'malware_triage'): cipher_malware,
    ('Oracle', 'research'): oracle_research,
    ('Cipher', 'lab_validation'): lab_scoped_validation,
    ('Sentinel', 'lab_validation'): lab_scoped_validation,
}
