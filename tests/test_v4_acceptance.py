"""Gotham 4.0 acceptance tests. These EXECUTE real work (Docker sandboxes, Semgrep, YARA, pip-audit, git, notebooks).
No mocked tools. Agent-mode (model-driven) behaviour needs an inference provider and is reported BLOCKED elsewhere."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gotham.core import config, sbx
from gotham.core.audit import AuditReader
from gotham.core.engine import Alfred
from gotham.core.store import Store
from tests.conftest import needs_docker, run_until_done
from tests.fixtures import (AUTH_LOG, BUGGY_PROJECT, FIX_PATCH, INERT_SAMPLE, NOTEBOOK_CELLS, WEAK_EXPECTED, WEAK_PROJECT)

pytestmark = [pytest.mark.integration, needs_docker]
needs_research = pytest.mark.skipif(not sbx.image_present(config.RESEARCH_IMAGE), reason='gotham-research image not built')


def approve_all(alfred, mid):
    for a in alfred.store.approvals('pending', mid):
        alfred.store.decide_approval(a['id'], True, 'batman-test')
        alfred.audit.record(mid, a['task_id'], 'Batman', 'approval_decided', {'approval_id': a['id'], 'approved': True})


def tasks(alfred, mid):
    return {(t['agent'], t['kind']): t for t in alfred.store.tasks_for(mid)}


def test_forge_repairs_defect_tests_pass_and_commit_is_real(alfred):
    mid = alfred.submit('engineering', 'Repair add() so tests pass', {'files': BUGGY_PROJECT, 'patch': FIX_PATCH}, 'test')
    run_until_done(alfred)
    m = alfred.store.get_mission(mid)
    assert m['status'] == 'verified', m['result']
    ev = tasks(alfred, mid)[('Forge', 'build_and_verify')]['result']['evidence']
    assert ev['tests_before']['summary']['failed'] == 1 and not ev['tests_before']['ok']
    assert ev['tests_after']['ok'] and ev['tests_after']['container_destroyed']
    repo = config.workspaces_dir() / mid / 'project'
    log = subprocess.run(['git', 'log', '--oneline'], cwd=repo, capture_output=True, text=True).stdout
    assert 'Gotham Forge' in log and ev['commit'][:7] in subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True).stdout
    assert 'return a + b' in (repo / 'calc.py').read_text()
    assert any(a['name'] == 'change.patch' for a in alfred.store.artifacts_for(mid))


def test_forge_without_repair_source_fails_closed(alfred):
    mid = alfred.submit('engineering', 'Repair add() so tests pass', {'files': BUGGY_PROJECT}, 'test')
    run_until_done(alfred)
    m = alfred.store.get_mission(mid)
    assert m['status'] == 'failed'
    forge = tasks(alfred, mid)[('Forge', 'build_and_verify')]
    assert forge['result']['blocked_reason'] == 'no_repair_source'   # no pretend repair, no mock model


def test_sentinel_detects_introduced_weaknesses_with_reproducible_report(alfred):
    mid = alfred.submit('security_audit', 'Audit weak project', {'files': WEAK_PROJECT, 'expect_rules': WEAK_EXPECTED}, 'test')
    run_until_done(alfred)
    assert alfred.store.get_mission(mid)['status'] == 'verified'
    ev = tasks(alfred, mid)[('Sentinel', 'audit')]['result']['evidence']
    engines = {f['engine'] for f in ev['findings']}
    assert {'semgrep', 'secrets', 'config', 'pip-audit'} <= engines
    assert any(f['engine'] == 'pip-audit' and f.get('dep') == 'requests' for f in ev['findings'])
    art = next(a for a in alfred.store.artifacts_for(mid) if a['name'] == 'security_report.json')
    import hashlib
    assert hashlib.sha256(Path(art['path']).read_bytes()).hexdigest() == art['sha256']   # artifact provenance
    # reproducibility: rerun gives the same finding set
    mid2 = alfred.submit('security_audit', 'Audit weak project again', {'files': WEAK_PROJECT}, 'test')
    run_until_done(alfred)
    ev2 = tasks(alfred, mid2)[('Sentinel', 'audit')]['result']['evidence']
    key = lambda e: sorted((f['rule'], f['file'], f['line']) for f in e['findings'] if f['engine'] != 'pip-audit')
    assert key(ev) == key(ev2)


def test_cipher_malware_analysis_static_and_isolated_behavior_with_approval(alfred):
    mid = alfred.submit('malware_analysis', 'Analyse approved inert sample', {'sample': {'name': 'inert.py', 'content': INERT_SAMPLE},
                                                                                  'dynamic': True, 'approved_inert': True}, 'test')
    run_until_done(alfred, concurrency=2)
    t = tasks(alfred, mid)[('Cipher', 'malware_triage')]
    assert t['status'] == 'awaiting_approval'                         # gate: nothing executed before Batman approves
    assert not any(e['action'] == 'task_started' for e in AuditReader(config.audit_path()).events(mid))
    approve_all(alfred, mid)
    run_until_done(alfred, concurrency=2)
    m = alfred.store.get_mission(mid)
    assert m['status'] == 'verified', m['result']
    ev = tasks(alfred, mid)[('Cipher', 'malware_triage')]['result']['evidence']
    assert ev['triage']['executed'] is False and any('example.invalid' in u for u in ev['triage']['iocs']['url'])
    assert ev['yara']['validation']['valid']
    beh = ev['behavior']
    assert beh['network'] == 'none' and beh['container_destroyed'] and beh['telemetry_complete']
    assert beh['event_counts'].get('socket.connect') and beh['event_counts'].get('open')
    assert any('network' in s for s in beh['behavior_summary'])
    # the sample's marker file was written inside the container only
    assert not os.path.exists('/tmp/gotham_inert_marker.txt')


def test_security_lab_scoped_validation_and_remediation_check(alfred):
    mid = alfred.submit('lab_validation', 'Validate vulnerable lab target and verify hardened build', {}, 'test')
    run_until_done(alfred, concurrency=2)
    assert all(t['status'] == 'awaiting_approval' for t in alfred.store.tasks_for(mid)[:1])
    approve_all(alfred, mid)
    run_until_done(alfred, concurrency=2)
    approve_all(alfred, mid)       # second task gets its own approval
    run_until_done(alfred, concurrency=2)
    m = alfred.store.get_mission(mid)
    assert m['status'] == 'verified', json.dumps(m['result'], indent=1)[:2000]
    vuln = tasks(alfred, mid)[('Cipher', 'lab_validation')]['result']['evidence']
    assert {v['check'] for v in vuln['probe']['vulnerabilities']} == {'sqli_login', 'path_traversal', 'reflected_xss', 'security_headers'}
    assert vuln['scope_enforced'] is True
    fixed = tasks(alfred, mid)[('Sentinel', 'lab_validation')]['result']['evidence']
    assert fixed['probe']['vulnerabilities'] == []
    ev = AuditReader(config.audit_path()).events(mid)
    assert any(e['action'] == 'scope_violation' for e in ev)           # the out-of-scope probe was refused and recorded
    left = subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=gotham-lab=1'], capture_output=True, text=True).stdout.split()
    assert left == []                                                   # lab containers cleaned up


@needs_research
def test_oracle_notebook_executes_and_training_resumes_from_checkpoint(alfred):
    mid = alfred.submit('research', 'Statistical comparison and resumable training',
                        {'name': 'analysis', 'cells': NOTEBOOK_CELLS, 'train': {'epochs': 6, 'interrupt_at': 3}}, 'test')
    run_until_done(alfred)
    m = alfred.store.get_mission(mid)
    assert m['status'] == 'verified', json.dumps(m['result'], indent=1)[:2500]
    ev = tasks(alfred, mid)[('Oracle', 'research')]['result']['evidence']
    assert ev['notebook']['ok'] and ev['notebook']['executed_cells'] == ev['notebook']['code_cells'] == 2
    assert any('p_value' in o for o in ev['notebook']['outputs'])
    assert ev['training_first_run']['interrupted'] and ev['training_resumed_run']['resumed']
    assert ev['training_final']['epochs_logged'] == 6
    names = {a['name'] for a in alfred.store.artifacts_for(mid)}
    assert {'analysis.executed.ipynb', 'metrics.jsonl', 'final.json'} <= names


@needs_research
def test_failing_notebook_is_never_marked_complete(alfred):
    cells = [{'type': 'code', 'source': 'print("start")\nraise ValueError("deliberate failure")'}]
    mid = alfred.submit('research', 'Notebook with a deliberate error', {'name': 'bad', 'cells': cells}, 'test')
    run_until_done(alfred)
    assert alfred.store.get_mission(mid)['status'] == 'failed'


@needs_research
def test_alfred_delegates_real_work_to_all_five_agents(alfred):
    project = {**BUGGY_PROJECT, **WEAK_PROJECT}            # a project with a defect (Forge) and weaknesses (Sentinel)
    sections = {'engineering': {'files': project, 'patch': FIX_PATCH},
                'security': {'expect_rules': WEAK_EXPECTED},
                'malware': {'sample': {'name': 'inert.py', 'content': INERT_SAMPLE}, 'approved_inert': True},
                'research': {'name': 'analysis', 'cells': NOTEBOOK_CELLS}}
    mid = alfred.submit('full_spectrum', 'Full spectrum mission across all five specialists', {'sections': sections}, 'test')
    run_until_done(alfred, concurrency=5)
    m = alfred.store.get_mission(mid)
    report = m['result']
    assert m['status'] == 'verified', json.dumps(report['checks'], indent=1)
    assert report['agents_used'] == ['Cipher', 'Forge', 'Oracle', 'Scout', 'Sentinel']
    T = tasks(alfred, mid)
    assert all(t['status'] == 'succeeded' for t in T.values()) and len(T) == 5
    assert T[('Scout', 'recon')]['finished'] <= T[('Forge', 'build_and_verify')]['started']      # dependency order respected
    assert T[('Forge', 'build_and_verify')]['finished'] <= T[('Sentinel', 'audit')]['started']
    # Cipher and Oracle have no dependencies: they ran while Scout/Forge were still working
    assert T[('Cipher', 'malware_triage')]['started'] < T[('Forge', 'build_and_verify')]['finished']
    assert T[('Oracle', 'research')]['started'] < T[('Forge', 'build_and_verify')]['finished']
    msgs = alfred.store.messages_for(mid)
    assert {x['recipient'] for x in msgs if x['type'] == 'task_assignment'} == {'Scout', 'Forge', 'Cipher', 'Oracle', 'Sentinel'}
    # every specialist really called tools, and Specter recorded them independently of Alfred's report
    ev = AuditReader(config.audit_path()).events(mid, limit=5000)
    assert {e['actor'] for e in ev if e['action'] == 'tool_call'} == {'Scout', 'Forge', 'Cipher', 'Oracle', 'Sentinel'}
    assert all(t['result']['receipt']['tool_calls'] > 0 for t in T.values())
    assert report['report_sha256'] and len(report['artifacts']) >= 6 and AuditReader(config.audit_path()).verify()['valid']


def test_recovery_after_worker_is_killed_mid_task(env):
    slow = {'test_slow.py': 'import os, time\n\n\ndef test_slow():\n    if not os.path.exists(".started"):\n        open(".started", "w").write("1")\n        time.sleep(90)\n    assert True\n'}
    alfred = Alfred()
    mid = alfred.submit('engineering', 'Run slow test project that survives a crash', {'files': slow}, 'test')
    envv = {**os.environ, 'GOTHAM_LEASE_SECONDS': '3', 'GOTHAM_WORKER_CONCURRENCY': '2'}
    p = subprocess.Popen([sys.executable, '-m', 'gotham.core.worker'], env=envv, cwd=Path(__file__).parents[1],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            forge = tasks(alfred, mid).get(('Forge', 'build_and_verify'))
            if forge and forge['status'] == 'running' and (config.workspaces_dir() / mid / 'project' / '.started').exists():
                break
            time.sleep(0.3)
        else:
            pytest.fail('forge task never reached running state')
        p.send_signal(signal.SIGKILL)                       # hard crash: no cleanup handlers run
        p.wait()
    finally:
        if p.poll() is None:
            p.kill()
    assert tasks(alfred, mid)[('Forge', 'build_and_verify')]['status'] == 'running'   # lease still held by the corpse
    time.sleep(4)                                                                      # lease lapses
    orphan = subprocess.run(['docker', 'ps', '-q', '--filter', 'label=gotham=1'], capture_output=True, text=True).stdout.split()
    run_until_done(Alfred(), concurrency=2)             # "restarted service": recovers, retries, completes
    m = Store(config.store_path()).get_mission(mid)
    assert m['status'] == 'verified', m['result']
    forge = [t for t in Store(config.store_path()).tasks_for(mid) if t['agent'] == 'Forge'][0]
    assert forge['attempts'] == 2
    acts = [e['action'] for e in AuditReader(config.audit_path()).events(mid)]
    assert 'recovery_requeued' in acts and acts.count('task_started') >= 3
    assert subprocess.run(['docker', 'ps', '-q', '--filter', 'label=gotham=1'], capture_output=True, text=True).stdout.split() == []


def test_specter_independently_records_and_workers_cannot_alter_it(alfred):
    mid = alfred.submit('engineering', 'Repair add() so tests pass', {'files': BUGGY_PROJECT, 'patch': FIX_PATCH}, 'test')
    run_until_done(alfred)
    rep = AuditReader(config.audit_path()).report(mid)
    actions = [e['action'] for e in rep['events']]
    for needed in ('mission_authorized', 'task_assigned', 'workspace_seeded', 'task_started', 'tool_call', 'tool_result',
                   'artifact_created', 'task_finished', 'mission_finalized'):
        assert needed in actions, needed
    assert rep['integrity']['valid'] and rep['tool_calls'] > 5
    # run_tests ran inside the sandbox: the container could not see the audit journal at all
    ws = config.workspaces_dir() / mid / 'project'
    r = sbx.run('gotham-sandbox:latest', ['sh', '-c', f'ls {config.audit_path().parent} 2>&1; ls /root 2>&1 | head -1'], mount=ws)
    assert 'specter.sqlite3' not in r['stdout'] and 'No such file' in r['stdout'] and r['container_destroyed']
    # and the audit file is not inside any workspace tree
    assert str(config.audit_path()).startswith(str(config.audit_path().parent)) and config.workspaces_dir() not in config.audit_path().parents


def test_sandbox_containment_flags_and_timeout_kill(env):
    r = sbx.run('gotham-sandbox:latest', ['python', '-c', 'import socket;socket.create_connection(("1.1.1.1",80),timeout=2)'])
    assert r['exit_code'] != 0 and r['network'] == 'none'
    r = sbx.run('gotham-sandbox:latest', ['python', '-c', 'open("/etc/x","w")'])
    assert r['exit_code'] != 0                                       # read-only root filesystem
    r = sbx.run('gotham-sandbox:latest', ['python', '-c', 'while True: pass'], timeout=3)
    assert r['timed_out'] and r['container_destroyed']
    r = sbx.run('gotham-sandbox:latest', ['python', '-c', 'import os;print(os.getuid())'])
    assert r['stdout'].strip() == '65534'
