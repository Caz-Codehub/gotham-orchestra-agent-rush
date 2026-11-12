"""Captain Alfred: mission intake, decomposition, dispatch, recovery and verification.

Alfred plans tasks (stored durably), workers claim them with leases and execute playbooks / agent loops through
the audited tool registry. Alfred never marks a mission verified from worker claims: `verify_mission` re-checks the
structured evidence each task returned (tests really passed, notebook really executed, rule really validated...).
"""
from __future__ import annotations
import hashlib
import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import config, sbx
from . import tools as T
from . import research, sectools, lab  # noqa: F401  (register tools)
from .audit import AuditWriter
from .playbooks import PLAYBOOKS
from .runtime import NoModel
from .store import Store, TERMINAL

KINDS = ('engineering', 'security_audit', 'log_analysis', 'malware_analysis', 'research', 'lab_validation', 'full_spectrum', 'objective', 'orchestra')
MAX_FILES_BYTES = 400_000


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def verify_artifact_integrity(artifacts: list[dict], root: Path) -> list[dict]:
    """Independently rehash emitted files; never trust artifact metadata alone.

    Published files must stay within the mission's dedicated artifact directory. Existing receipts
    remain valid only while their actual content and recorded size match.
    """
    root = root.resolve()
    checks = []
    for a in artifacts:
        passed = False
        reason = "missing_or_unreadable"
        try:
            path = Path(a["path"])
            actual = path.resolve(strict=True)
            if actual != root and root not in actual.parents:
                reason = "outside_mission_workspace"
            elif not actual.is_file() or path.is_symlink():
                reason = "not_regular_file"
            else:
                h = hashlib.sha256()
                size = 0
                with actual.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        size += len(chunk)
                        h.update(chunk)
                passed = size == a["size"] and h.hexdigest() == a["sha256"]
                reason = "matched" if passed else "content_or_size_mismatch"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        checks.append({"artifact": a.get("id"), "name": a.get("name"),
                       "check": "artifact_content_sha256_and_size_match",
                       "pass": passed, "reason": reason})
    return checks


class Alfred:
    def __init__(self, store: Store | None = None, audit: AuditWriter | None = None, client=None):
        self.store = store or Store(config.store_path())
        self.audit = audit or AuditWriter(config.audit_path())
        self.client = client  # inference client (None => agent-mode tasks BLOCKED)

    # ------------------------------------------------------------ intake & planning
    def submit(self, kind: str, goal: str, params: dict | None, requested_by: str, idem_key: str | None = None) -> str:
        if kind not in KINDS:
            raise ValueError(f'unknown mission kind {kind!r}; choose from {KINDS}')
        params = params or {}
        if len(json.dumps(params, default=str)) > MAX_FILES_BYTES:
            raise ValueError('mission parameters too large')
        if not 4 <= len(goal.strip()) <= 2000:
            raise ValueError('goal must be 4-2000 characters')
        mid = self.store.create_mission(kind, goal.strip(), params, requested_by, idem_key=idem_key)
        if self.store.tasks_for(mid):  # idempotent resubmission
            return mid
        self.audit.record(mid, None, 'Batman', 'mission_authorized',
                          {'requested_by': requested_by, 'kind': kind, 'goal_sha256': hashlib.sha256(goal.encode()).hexdigest(),
                           'goal_preview': goal[:200], 'params_sha256': _digest(params)})
        try:
            plan = self._plan(kind, goal, params)
        except Exception as exc:
            self.store.set_mission(mid, status='failed', result={'error': f'planning failed: {exc}'})
            self.audit.record(mid, None, 'Alfred', 'planning_failed', {'error': str(exc)[:200]})
            return mid
        ids: dict[str, str] = {}
        for t in plan:
            tid = self.store.add_task(mid, t['agent'], t['kind'], t['title'], {**t.get('params', {}), 'workdir': t.get('workdir', 'project')},
                                      depends=[ids[d] for d in t.get('after', [])], risk=t.get('risk', 'low'), mode=t.get('mode', 'playbook'),
                                      timeout_s=t.get('timeout', 300))
            ids[t['key']] = tid
            self.store.add_message(mid, tid, 'Alfred', t['agent'], 'task_assignment', {'kind': t['kind'], 'title': t['title'], 'depends_on': t.get('after', [])})
            self.audit.record(mid, tid, 'Alfred', 'task_assigned', {'agent': t['agent'], 'kind': t['kind'], 'risk': t.get('risk', 'low'),
                                                                   'mode': t.get('mode', 'playbook'), 'depends_on': t.get('after', [])})
            if t.get('risk') == 'high':
                aid = self.store.request_approval(mid, tid, 'task_start', {'agent': t['agent'], 'tools': t.get('tools', []),
                                                                         'scope': t.get('scope', 'local isolated lab only'), 'title': t['title']})
                self.audit.record(mid, tid, 'Alfred', 'approval_requested', {'approval_id': aid, 'tools': t.get('tools', [])})
        self.store.set_mission(mid, status='running')
        return mid

    def _plan(self, kind, goal, p) -> list[dict]:
        files = p.get('files') or {}
        if kind == 'orchestra':
            from .orchestra_missions import mission_plan
            return mission_plan(goal, p)
        if kind == 'engineering':
            return self._plan_engineering(goal, p)
        if kind == 'security_audit':
            return [{'key': 'recon', 'agent': 'Scout', 'kind': 'recon', 'title': 'Inventory target', 'params': {'files': files}, 'workdir': 'target'},
                    {'key': 'audit', 'agent': 'Sentinel', 'kind': 'audit', 'title': 'Scan: Semgrep, secrets, config, dependencies',
                     'params': {'files': {}, 'expect_rules': p.get('expect_rules', [])}, 'after': ['recon'], 'workdir': 'target'}]
        if kind == 'log_analysis':
            return [{'key': 'logs', 'agent': 'Sentinel', 'kind': 'log_analysis', 'title': 'Correlate security events', 'params': p, 'workdir': 'logs'}]
        if kind == 'malware_analysis':
            t = {'key': 'mal', 'agent': 'Cipher', 'kind': 'malware_triage', 'title': 'Static triage, IOCs, YARA' + (' + sandboxed behaviour' if p.get('dynamic') else ''),
                 'params': p, 'workdir': 'malware'}
            if p.get('dynamic'):
                t.update(risk='high', tools=['sandbox_behavior'], scope='inert Python sample, network-less container')
            return [t]
        if kind == 'research':
            return [{'key': 'nb', 'agent': 'Oracle', 'kind': 'research', 'title': 'Execute notebook' + (' and resumable training' if p.get('train') else ''),
                     'params': p, 'workdir': 'research', 'timeout': 900}]
        if kind == 'lab_validation':
            tools_ = ['lab_start', 'lab_probe', 'lab_stop']
            return [{'key': 'vuln', 'agent': 'Cipher', 'kind': 'lab_validation', 'title': 'Scoped validation of the vulnerable lab target',
                     'params': {'secure': False, 'expect_vulnerable': p.get('expect_vulnerable', ['sqli_login', 'path_traversal', 'reflected_xss', 'security_headers'])},
                     'risk': 'high', 'tools': tools_, 'scope': 'gotham-lab internal network, container started by this task only', 'workdir': 'lab1'},
                    {'key': 'fixed', 'agent': 'Sentinel', 'kind': 'lab_validation', 'title': 'Verify remediation on hardened build',
                     'params': {'secure': True, 'expect_vulnerable': []}, 'after': ['vuln'], 'risk': 'high', 'tools': tools_,
                     'scope': 'gotham-lab internal network, container started by this task only', 'workdir': 'lab2'}]
        if kind == 'full_spectrum':
            s = p.get('sections', {})
            plan = self._plan_engineering(goal, s.get('engineering', {})) if s.get('engineering') else []
            if s.get('security'):
                plan.append({'key': 'sec', 'agent': 'Sentinel', 'kind': 'audit', 'title': 'Security scan of built project',
                             'params': {'files': {}, 'expect_rules': s['security'].get('expect_rules', [])},
                             'after': ['build'] if plan else [], 'workdir': 'project'})
            if s.get('malware'):
                plan.append({'key': 'mal', 'agent': 'Cipher', 'kind': 'malware_triage', 'title': 'Triage inert sample', 'params': s['malware'], 'workdir': 'malware'})
            if s.get('research'):
                plan.append({'key': 'nb', 'agent': 'Oracle', 'kind': 'research', 'title': 'Notebook analysis', 'params': s['research'], 'workdir': 'research', 'timeout': 900})
            return plan
        if kind == 'objective':
            if not getattr(self.client, 'configured', False):
                raise RuntimeError('objective missions need a configured model (BLOCKED: no inference provider)')
            return [{'key': 'agent', 'agent': p.get('agent', 'Forge'), 'kind': 'agent_objective', 'title': goal[:80],
                     'params': {'files': files, 'goal': goal}, 'mode': 'agent', 'workdir': 'project', 'timeout': 600}]
        raise ValueError(kind)

    def _plan_engineering(self, goal, p):
        files = p.get('files') or {}
        return [{'key': 'recon', 'agent': 'Scout', 'kind': 'recon', 'title': 'Inspect project', 'params': {'files': files}, 'workdir': 'recon'},
                {'key': 'build', 'agent': 'Forge', 'kind': 'build_and_verify', 'title': 'Build, test, repair, commit',
                 'params': {'files': files, 'patch': p.get('patch'), 'goal': goal, 'install': p.get('install', False),
                            'branch': p.get('branch', 'gotham/forge-change'),
                            'commit_message': p.get('commit_message', 'Gotham Forge: verified change')},
                 'after': ['recon'], 'workdir': 'project', 'timeout': 600}]

    # ------------------------------------------------------------ execution
    def execute_task(self, task: dict, worker_id: str) -> None:
        tid, mid = task['id'], task['mission_id']
        ctx = self._ctx(task)
        sbx.CURRENT_TASK.set(tid)
        self.audit.record(mid, tid, 'Alfred', 'task_started', {'agent': task['agent'], 'attempt': task['attempts'], 'worker': worker_id})
        stop = threading.Event()

        def beat():
            while not stop.wait(config.LEASE_SECONDS / 3):
                if time.monotonic() > ctx.deadline + config.HEARTBEAT_GRACE_S:
                    # Task blew through its own deadline (hung thread): stop renewing so recovery can reclaim it.
                    self.audit.record(mid, tid, 'Alfred', 'heartbeat_stopped_deadline_exceeded', {})
                    return
                self.store.heartbeat(tid, worker_id, config.LEASE_SECONDS)
        hb = threading.Thread(target=beat, daemon=True)
        hb.start()
        try:
            result = self._run(task, ctx)
            status = 'succeeded' if result.get('status') == 'ok' else 'failed'
            receipt = {'task_id': tid, 'agent': task['agent'], 'kind': task['kind'], 'mode': task['mode'],
                       'tool_calls': ctx.calls, 'result_sha256': _digest(result), 'attempt': task['attempts']}
            result['receipt'] = receipt
            if self.store.finish_task(tid, worker_id, status, result, None if status == 'succeeded' else result.get('summary')):
                self.audit.record(mid, tid, 'Alfred', 'task_finished', {'status': status, **receipt, 'summary': result.get('summary', '')[:200]})
        except T.ApprovalRequired as exc:
            self.store.requeue_task(tid, worker_id, 'awaiting approval')
            self.store.set_task_status(tid, 'awaiting_approval')
            aid = self.store.request_approval(mid, tid, f'tool:{exc.tool}', exc.detail)
            self.audit.record(mid, tid, 'Alfred', 'approval_requested', {'approval_id': aid, 'tool': exc.tool})
        except T.TaskCancelled:
            self.store.finish_task(tid, worker_id, 'cancelled', None, 'cancelled by operator')
            self.audit.record(mid, tid, 'Alfred', 'task_cancelled', {})
        except NoModel as exc:
            self.store.finish_task(tid, worker_id, 'failed', {'status': 'blocked', 'summary': str(exc), 'blocked_reason': 'no_model'}, str(exc))
            self.audit.record(mid, tid, 'Alfred', 'task_blocked', {'reason': 'no_model'})
        except T.ToolDenied as exc:
            self.store.finish_task(tid, worker_id, 'failed', {'status': 'failed', 'summary': f'policy denied: {exc}'}, str(exc))
            self.audit.record(mid, tid, 'Alfred', 'task_denied', {'error': str(exc)[:200]})
        except Exception as exc:  # tool/sandbox errors: bounded retry
            err = f'{type(exc).__name__}: {exc}'[:300]
            if task['attempts'] < task['max_attempts']:
                self.store.requeue_task(tid, worker_id, err)
                self.audit.record(mid, tid, 'Alfred', 'task_retry_scheduled', {'attempt': task['attempts'], 'error': err})
            else:
                self.store.finish_task(tid, worker_id, 'failed', {'status': 'failed', 'summary': err, 'trace': traceback.format_exc()[-1200:]}, err)
                self.audit.record(mid, tid, 'Alfred', 'task_failed', {'error': err, 'attempts': task['attempts']})
        finally:
            stop.set()
            self.advance(mid)

    def _ctx(self, task) -> T.ToolContext:
        mid = task['mission_id']
        ws = config.workspaces_dir() / mid / task['params'].get('workdir', 'project')
        ws.mkdir(parents=True, exist_ok=True)
        tid = task['id']
        return T.ToolContext(mid, tid, task['agent'], ws, self.store, self.audit, deadline=time.monotonic() + task['timeout_s'],
                             is_cancelled=lambda: bool((self.store.get_mission(mid) or {}).get('cancel_requested')),
                             max_calls=int((self.store.get_mission(mid) or {}).get('budget', {}).get('max_tool_calls', 300) or 300))

    def _seed(self, ctx, files: dict) -> None:
        """Alfred (not the agent) materialises the mission's input files into the confined task workspace."""
        if not files:
            return
        total = 0
        for rel, content in files.items():
            if not isinstance(content, str):
                raise T.ToolDenied('seed files must be text')
            p = ctx.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
            total += len(content)
        self.audit.record(ctx.mission_id, ctx.task_id, 'Alfred', 'workspace_seeded',
                          {'files': len(files), 'bytes': total, 'sha256': _digest(files)})

    def _run(self, task, ctx):
        params = dict(task['params'])
        self._seed(ctx, params.pop('files', None))
        if task['kind'] in ('orchestra_plan', 'orchestra_specialist', 'orchestra_review', 'orchestra_synthesis'):
            from .orchestra_missions import execute
            return execute(ctx, {**params, '_task_kind': task['kind']}, self.client)
        if task['mode'] == 'agent':
            from . import runtime
            out = runtime.run_agent(ctx, self.client, task['agent'], params['goal'])
            return {'status': 'ok' if out['final'].get('status') == 'ok' else 'failed', 'summary': str(out['final'].get('summary'))[:500], 'evidence': out}
        fn = PLAYBOOKS.get((task['agent'], task['kind']))
        if not fn:
            raise T.ToolDenied(f'no playbook for {task["agent"]}/{task["kind"]}')
        if task['kind'] == 'build_and_verify':
            return fn(ctx, params, self.client)
        return fn(ctx, params)

    # ------------------------------------------------------------ progress, recovery, verification
    def recover(self) -> list[dict]:
        rec = self.store.recover_expired()
        for r in rec:
            orphans = sbx.remove_task_containers(r['task_id'])
            self.audit.record(r['mission_id'], r['task_id'], 'Alfred', 'recovery_' + r['action'],
                              {'reason': 'worker lease expired', 'orphan_containers_removed': len(orphans)})
        stale = self.store.reset_stale_finalizing()
        if stale:
            self.audit.record(None, None, 'Alfred', 'recovery_finalizing_reset', {'missions': stale})
        for mid in self.store.open_missions():
            self.advance(mid)
        return rec

    def cancel(self, mid: str, by: str) -> None:
        """Cancel a mission: pending tasks cancelled now; RUNNING tasks lose their containers immediately and stop at the next tool call."""
        self.store.cancel_mission(mid)
        killed = 0
        for t in self.store.tasks_for(mid):
            if t['status'] == 'running':
                killed += len(sbx.remove_task_containers(t['id']))
        self.audit.record(mid, None, 'Batman', 'cancel_requested', {'by': by, 'containers_killed': killed})
        self.advance(mid)

    def advance(self, mid: str) -> None:
        self.store.block_dependents()
        m = self.store.get_mission(mid)
        if not m or m['status'] in ('verified', 'failed', 'cancelled', 'completed_unverified', 'finalizing'):
            return
        tasks = self.store.tasks_for(mid)
        if not tasks:
            return
        if m['cancel_requested'] and all(t['status'] in TERMINAL for t in tasks):
            if self.store.begin_finalize(mid):
                self.store.set_mission(mid, status='cancelled')
                self.audit.record(mid, None, 'Alfred', 'mission_cancelled', {})
            return
        if any(t['status'] == 'awaiting_approval' for t in tasks) and m['status'] != 'awaiting_approval':
            self.store.set_mission(mid, status='awaiting_approval')
        elif m['status'] == 'awaiting_approval' and not any(t['status'] == 'awaiting_approval' for t in tasks):
            self.store.set_mission(mid, status='running')
        if all(t['status'] in TERMINAL for t in tasks):
            self.finalize(mid)

    def finalize(self, mid: str) -> dict:
        m = self.store.get_mission(mid)
        if m['status'] in ('verified', 'failed', 'cancelled', 'completed_unverified', 'finalizing'):
            return m['result'] or {}
        if not self.store.begin_finalize(mid):      # another worker won the race
            return {}
        try:
            return self._finalize_locked(mid, m)
        except Exception:
            self.store.set_mission(mid, status='running')   # never leave a mission wedged in 'finalizing'
            raise

    def _finalize_locked(self, mid, m):
        tasks = self.store.tasks_for(mid)
        checks = verify_tasks(tasks)
        arts = self.store.artifacts_for(mid)
        checks.extend(verify_artifact_integrity(arts, config.artifacts_dir() / mid))
        all_ok = bool(checks) and all(c['pass'] for c in checks)
        report = {'mission_id': mid, 'kind': m['kind'], 'goal': m['goal'], 'verified': all_ok, 'checks': checks,
                  'tasks': [{'id': t['id'], 'agent': t['agent'], 'kind': t['kind'], 'status': t['status'], 'attempts': t['attempts'],
                             'summary': (t['result'] or {}).get('summary', t['error']), 'receipt': (t['result'] or {}).get('receipt')} for t in tasks],
                  'artifacts': [{'id': a['id'], 'name': a['name'], 'sha256': a['sha256'], 'size': a['size'], 'producer': a['producer']} for a in arts],
                  'usage': self.store.usage_totals(mid), 'agents_used': sorted({t['agent'] for t in tasks if t['status'] == 'succeeded'}),
                  'finalized_at': time.time()}
        # Model-driven orchestral analysis is never equivalent to executing and
        # verifying code, notebooks or defensive scans; preserve that distinction.
        if m['kind'] == 'orchestra':
            requested = bool((m['params'] or {}).get('execute') is True)
            expected = 4 if (m['params'] or {}).get('orchestra') == 'all' else 1
            evidence_tasks = [t for t in tasks if t['kind'] in
                              ('build_and_verify', 'audit', 'research', 'lab_validation')
                              and str((t['params'] or {}).get('workdir', '')).startswith('orchestras/')]
            real_execution_verified = bool(all_ok and requested and len(evidence_tasks) == expected
                                            and all(t['status'] == 'succeeded' for t in evidence_tasks))
            report['analysis_complete'] = bool(all_ok and not requested)
            report['verified'] = real_execution_verified
            report['execution_verified'] = real_execution_verified
            report['orchestras_completed'] = sorted({
                (t['params'] or {}).get('orchestra') for t in tasks
                if t['kind'] == 'orchestra_review' and t['status'] == 'succeeded'
            })
            report['evidence_tasks'] = [{'agent': t['agent'], 'kind': t['kind'],
                                         'receipt': (t['result'] or {}).get('receipt')}
                                        for t in evidence_tasks]
        report['report_sha256'] = _digest({k: v for k, v in report.items() if k != 'finalized_at'})
        if m['kind'] == 'orchestra':
            status = ('verified' if real_execution_verified else
                      ('completed_unverified' if all_ok else ('cancelled' if m['cancel_requested'] else 'failed')))
        else:
            status = 'verified' if all_ok else ('cancelled' if m['cancel_requested'] else 'failed')
        self.store.set_mission(mid, status=status, result=report)
        self.audit.record(mid, None, 'Alfred', 'mission_finalized', {'status': status, 'report_sha256': report['report_sha256'],
                                                                     'checks_passed': sum(c['pass'] for c in checks), 'checks_total': len(checks)})
        return report


def verify_tasks(tasks: list[dict]) -> list[dict]:
    """Independent re-check of structured evidence. Each check must come from tool output, not agent prose."""
    out = []
    for t in tasks:
        r = t['result'] or {}
        ev = r.get('evidence') or {}
        ok_status = t['status'] == 'succeeded'
        out.append({'task': t['id'], 'agent': t['agent'], 'check': 'task_succeeded_with_receipt', 'pass': ok_status and bool(r.get('receipt'))})
        if not ok_status:
            continue
        k = t['kind']
        if k in ('orchestra_plan', 'orchestra_specialist', 'orchestra_review'):
            out.append({'task': t['id'], 'agent': t['agent'], 'check': 'model_receipt_present_no_execution_claimed',
                        'pass': bool(ev.get('model_sha256') and len(ev['model_sha256']) == 64
                                     and ev.get('execution') is False)})
        elif k == 'build_and_verify':
            out.append({'task': t['id'], 'agent': t['agent'], 'check': 'tests_passed_in_container_and_committed',
                        'pass': bool(ev.get('tests_after', {}).get('ok') and ev['tests_after'].get('container_destroyed') and ev.get('commit'))})
        elif k == 'audit':
            out.append({'task': t['id'], 'agent': t['agent'], 'check': 'scanners_ran_and_expectations_met',
                        'pass': len(ev.get('scans', [])) >= 3 and not ev.get('expected_rules_missing')})
        elif k == 'malware_triage':
            ok = ev.get('yara', {}).get('validation', {}).get('valid') and ev.get('triage', {}).get('executed') is False
            if 'behavior' in ev:
                ok = ok and ev['behavior'].get('telemetry_complete') and ev['behavior'].get('container_destroyed')
            out.append({'task': t['id'], 'agent': t['agent'], 'check': 'rule_validated_and_telemetry_collected', 'pass': bool(ok)})
        elif k == 'research':
            nb = ev.get('notebook', {})
            ok = nb.get('ok') and nb.get('executed_cells') == nb.get('code_cells')
            if 'training_final' in ev:
                ok = ok and ev['training_final'].get('ok')
            out.append({'task': t['id'], 'agent': t['agent'], 'check': 'notebook_executed_all_cells', 'pass': bool(ok)})
        elif k == 'lab_validation':
            out.append({'task': t['id'], 'agent': t['agent'], 'check': 'scope_enforced_and_target_destroyed',
                        'pass': bool(ev.get('scope_enforced') and ev.get('stopped', {}).get('removed'))})
    return out
