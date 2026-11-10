"""Gotham 4.0 HTTP control plane (router mounted at /api/v4). Every action maps to real backend state."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import auth, config, sbx
from . import tools as T
from .audit import AuditReader
from .engine import KINDS, Alfred
from .store import Store
from ..inference import get_inference_client

router = APIRouter(prefix='/api/v4')
_alfred: Alfred | None = None
_reader: AuditReader | None = None

AGENT_ROLES = {
    'Scout': 'Discovery, repository inspection, technical reconnaissance of authorized resources',
    'Forge': 'Software engineering: build, test, repair, commit, deploy',
    'Oracle': 'Scientific research: notebooks, ML experiments, statistics',
    'Sentinel': 'Defensive security: scans, log analysis, detection, remediation checks',
    'Cipher': 'Security research: static/dynamic malware analysis, YARA, isolated lab',
}


def alfred() -> Alfred:
    global _alfred
    if _alfred is None:
        _alfred = Alfred(client=get_inference_client())
    return _alfred


def reader() -> AuditReader:
    global _reader
    if _reader is None:
        _reader = AuditReader(config.audit_path())
    return _reader


def reset_for_tests():
    global _alfred, _reader
    _alfred = _reader = None


class MissionIn(BaseModel):
    kind: str = Field(min_length=3, max_length=40)
    goal: str = Field(min_length=4, max_length=2000)
    params: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=80)


class Decision(BaseModel):
    approve: bool
    note: str = Field(default='', max_length=300)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _mission_view(mid: str) -> dict:
    a = alfred()
    m = a.store.get_mission(mid)
    if not m:
        raise HTTPException(404, 'mission not found')
    tasks = a.store.tasks_for(mid)
    for t in tasks:
        t['params'] = {k: (v if k != 'files' else '[files]') for k, v in (t['params'] or {}).items()}
        if t['result']:
            t['result'] = {k: v for k, v in t['result'].items() if k != 'evidence'} | {'evidence_available': True}
    return {'mission': m, 'tasks': tasks, 'approvals': a.store.approvals(mission_id=mid), 'messages': a.store.messages_for(mid),
            'artifacts': a.store.artifacts_for(mid), 'usage': a.store.usage_totals(mid)}


@router.get('/health')
def health():
    return {'status': 'ok', 'version': '4.0.0-dev', 'docker': sbx.docker_available()}


@router.get('/kinds')
def kinds(p=Depends(auth.require('missions:read'))):
    return {'kinds': list(KINDS)}


@router.post('/missions')
def submit(body: MissionIn, p=Depends(auth.require('missions:submit'))):
    try:
        mid = alfred().submit(body.kind, body.goal, body.params, f'{p.role}:{p.name}', body.idempotency_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _mission_view(mid)


@router.get('/missions')
def missions(p=Depends(auth.require('missions:read'))):
    return {'missions': alfred().store.list_missions()}


@router.get('/missions/{mid}')
def mission(mid: str, p=Depends(auth.require('missions:read'))):
    return _mission_view(mid)


@router.get('/missions/{mid}/evidence')
def evidence(mid: str, p=Depends(auth.require('missions:read'))):
    return {'tasks': [{'id': t['id'], 'agent': t['agent'], 'kind': t['kind'], 'status': t['status'],
                       'result': t['result'], 'error': t['error']} for t in alfred().store.tasks_for(mid)]}


@router.post('/missions/{mid}/cancel')
def cancel(mid: str, p=Depends(auth.require('missions:cancel'))):
    a = alfred()
    if not a.store.get_mission(mid):
        raise HTTPException(404, 'mission not found')
    a.cancel(mid, f'{p.role}:{p.name}')
    return _mission_view(mid)


@router.post('/tasks/{tid}/retry')
def retry(tid: str, p=Depends(auth.require('recovery:run'))):
    a = alfred()
    t = a.store.get_task(tid)
    if not t or not a.store.retry_task(tid):
        raise HTTPException(409, 'only failed/cancelled tasks can be retried')
    a.audit.record(t['mission_id'], tid, 'Batman', 'manual_retry', {'by': p.name})
    return _mission_view(t['mission_id'])


@router.post('/recovery/run')
def recovery(p=Depends(auth.require('recovery:run'))):
    a = alfred()
    rec = a.recover()
    removed = sbx.cleanup_stale()
    a.audit.record(None, None, 'Batman', 'manual_recovery', {'requeued_or_failed': len(rec), 'containers_removed': len(removed)})
    return {'recovered_tasks': rec, 'stale_containers_removed': len(removed)}


@router.get('/approvals')
def approvals(status: str | None = 'pending', p=Depends(auth.require('missions:read'))):
    return {'approvals': alfred().store.approvals(status)}


@router.post('/approvals/{aid}/decide')
def decide(aid: str, d: Decision, p=Depends(auth.require('approvals:decide'))):
    a = alfred()
    r = a.store.decide_approval(aid, d.approve, f'{p.role}:{p.name}')
    if not r:
        raise HTTPException(409, 'approval not found or already decided')
    a.audit.record(r['mission_id'], r['task_id'], 'Batman', 'approval_decided',
                   {'approval_id': aid, 'approved': d.approve, 'action': r['action'], 'note': d.note})
    a.advance(r['mission_id'])
    return r


@router.get('/artifacts')
def artifacts(mission_id: str | None = None, p=Depends(auth.require('artifacts:read'))):
    return {'artifacts': [{k: v for k, v in x.items() if k != 'path'} for x in alfred().store.artifacts_for(mission_id)]}


@router.get('/artifacts/{aid}/download')
def download(aid: str, p=Depends(auth.require('artifacts:read'))):
    art = alfred().store.get_artifact(aid)
    if not art:
        raise HTTPException(404, 'artifact not found')
    path = Path(art['path']).resolve()
    if config.artifacts_dir().resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, 'artifact unavailable')
    if hashlib.sha256(path.read_bytes()).hexdigest() != art['sha256']:
        raise HTTPException(409, 'artifact failed integrity verification (hash mismatch)')
    return FileResponse(path, filename=art['name'], media_type='application/octet-stream')


@router.get('/artifacts/{aid}/preview')
def preview(aid: str, p=Depends(auth.require('artifacts:read'))):
    art = alfred().store.get_artifact(aid)
    if not art:
        raise HTTPException(404, 'artifact not found')
    path = Path(art['path']).resolve()
    if config.artifacts_dir().resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, 'artifact unavailable')
    data = path.read_bytes()
    return {'name': art['name'], 'size': len(data), 'sha256_verified': hashlib.sha256(data).hexdigest() == art['sha256'],
            'text': data[:60000].decode('utf-8', 'replace')}


@router.get('/agents')
def agents(p=Depends(auth.require('missions:read'))):
    rows, running = alfred().store.agent_activity()
    out = []
    for name, role in AGENT_ROLES.items():
        by = {r['status']: r['n'] for r in rows if r['agent'] == name}
        cur = [r for r in running if r['agent'] == name]
        out.append({'name': name, 'role': role, 'state': 'working' if cur else 'idle', 'current': cur, 'task_counts': by,
                    'tools': [t['name'] for t in T.specs_for(name)]})
    cl = alfred().client
    return {'captain': {'name': 'Alfred', 'model_configured': bool(getattr(cl, 'configured', False)),
                        'provider': getattr(cl, 'provider_name', 'none'),
                        'planner': 'model-assisted' if getattr(cl, 'configured', False) else 'rule-based (no model configured)'},
            'agents': out}


@router.get('/budget')
def budget(p=Depends(auth.require('infra:read'))):
    cl = alfred().client
    return {'usage': alfred().store.usage_totals(), 'limits': {'max_tool_calls_per_task': 300, 'max_model_calls': int(os.environ.get('GOTHAM_MAX_MODEL_CALLS', '16')),
            'paid_inference_enabled': os.environ.get('GOTHAM_ALLOW_PAID_INFERENCE') == 'I_ACCEPT_POTENTIAL_CHARGES'},
            'model': {'provider': getattr(cl, 'provider_name', 'none'), 'calls_used': getattr(cl, 'call_count', 0)},
            'note': 'Vultr/credit balances are not queried from this process; see docs/GOTHAM_BLOCKERS.md'}


@router.get('/infra')
def infra(p=Depends(auth.require('infra:read'))):
    a = alfred()
    du = shutil.disk_usage(config.data_dir())
    images = {i: sbx.image_present(i) for i in ('gotham-sandbox:latest', config.RESEARCH_IMAGE, 'gotham-lab-target:latest')}
    return {'docker': sbx.docker_available(), 'images': images, 'workers': a.store.live_workers(), 'counts': a.store.counts(),
            'audit': {k: v for k, v in reader().verify().items() if k != 'reason' or True},
            'disk': {'free_gb': round(du.free / 1e9, 1), 'used_pct': round(du.used / du.total * 100, 1)},
            'auth_roles_configured': auth.configured_roles(), 'cpus': os.cpu_count(),
            'inference': {'provider': getattr(a.client, 'provider_name', 'none'), 'configured': bool(getattr(a.client, 'configured', False))},
            'time': time.time()}


# ---- independent audit (Batman only) -------------------------------------------------------
@router.get('/audit/verify')
def audit_verify(p=Depends(auth.require('audit:read'))):
    return reader().verify()


@router.get('/audit/events')
def audit_events(mission_id: str | None = None, after_seq: int = 0, limit: int = 300, p=Depends(auth.require('audit:read'))):
    return {'events': reader().events(mission_id, min(limit, 1000), after_seq)}


@router.get('/audit/missions/{mid}')
def audit_report(mid: str, p=Depends(auth.require('audit:read'))):
    return reader().report(mid)


# ---- Batman <-> Alfred chat ----------------------------------------------------------------
@router.post('/chat')
def chat(body: ChatIn, p=Depends(auth.require('missions:read'))):
    a = alfred()
    text = body.message.strip()
    cmd = text.lower().split()
    a.store.add_message('chat', None, p.role, 'Alfred', 'chat', {'text': text[:2000]})
    model = getattr(a.client, 'configured', False)
    reply, source = None, 'alfred-rules (no model configured)'
    if cmd[0] in ('help', '?'):
        reply = ('Commands: status | missions | mission <id-prefix> | explain <id-prefix> | kinds. '
                 'Submit work from the workspaces (forms) or POST /api/v4/missions; approvals are decided only through the Approvals panel.')
    elif cmd[0] == 'status':
        c = a.store.counts()
        w = a.store.live_workers()
        reply = f'Missions: {c["missions"] or "none"}. Tasks: {c["tasks"] or "none"}. Live workers: {len(w)}. Model: {"configured" if model else "NOT configured (agent-mode objectives are blocked)"}.'
    elif cmd[0] == 'missions':
        ms = a.store.list_missions(8)
        reply = '\n'.join(f'{m["id"][:8]}  {m["status"]:<18} {m["kind"]:<16} {m["goal"][:60]}' for m in ms) or 'No missions yet.'
    elif cmd[0] in ('mission', 'explain') and len(cmd) > 1:
        ms = [m for m in a.store.list_missions(200) if m['id'].startswith(cmd[1])]
        if not ms:
            reply = 'No mission with that id.'
        else:
            v = _mission_view(ms[0]['id'])
            lines = [f'Mission {ms[0]["id"][:8]} is {v["mission"]["status"]}.']
            for t in v['tasks']:
                lines.append(f'- {t["agent"]}/{t["kind"]}: {t["status"]}' + (f' - {(t["result"] or {}).get("summary") or t["error"] or ""}'[:160]))
            for ap in v['approvals']:
                if ap['status'] == 'pending':
                    lines.append(f'- PENDING APPROVAL {ap["id"][:8]}: {ap["action"]}')
            reply = '\n'.join(lines)
    elif cmd[0] == 'kinds':
        reply = 'Mission kinds: ' + ', '.join(KINDS)
    elif model:
        try:
            ctx = json.dumps({'counts': a.store.counts(), 'recent': a.store.list_missions(5)}, default=str)[:3000]
            reply = a.client.chat('You are Captain Alfred of Gotham, reporting to Batman. Answer using ONLY the supplied state. You cannot execute actions from chat; '
                                  'point to the mission forms for that. State: ' + ctx, text, max_tokens=300)
            source = getattr(a.client, 'provider_name', 'model')
        except Exception as exc:
            reply = f'Model unavailable ({type(exc).__name__}); try a command (help).'
    else:
        reply = 'I run in rules mode (no model configured). Try: help, status, missions, explain <id>.'
    a.store.add_message('chat', None, 'Alfred', p.role, 'chat', {'text': reply, 'source': source})
    return {'reply': reply, 'source': source}


@router.get('/chat/history')
def chat_history(p=Depends(auth.require('missions:read'))):
    return {'messages': alfred().store.messages_for('chat', 100)}
