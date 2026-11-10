"""Gotham Project HTTP control plane. No sandbox work occurs in the web process."""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import threading
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .agents import team
from .inference import get_inference_client
from .orchestrator import run_mission
from .objectives import run_objective
from .orchestras import preview as orchestra_preview, run_orchestra
from .sandbox import containment_probe, SandboxUnavailable
from .demo_artifacts import execute_demo
from .specter import SpecterJournal, watch
from .core.api import router as v4_router

BASE=Path(__file__).resolve().parent
DB=Path(os.environ.get('GOTHAM_LEDGER_PATH','/tmp/gotham-missions.sqlite3'))
_watchdog_stop = threading.Event()
_watchdog_thread = None
_specter = None

@asynccontextmanager
async def lifespan(application):
    global _watchdog_thread, _specter
    _watchdog_stop.clear()
    _specter = SpecterJournal()
    _watchdog_thread = None
    # In production, Specter is separately supervised by its own systemd service.
    if os.environ.get('GOTHAM_SPECTER_EXTERNAL','') != '1':
        _watchdog_thread = threading.Thread(target=watch,args=(_watchdog_stop,_specter),
                                            name='specter-independent-watchdog',daemon=True)
        _watchdog_thread.start()
    try:
        yield
    finally:
        _watchdog_stop.set()
        if _watchdog_thread is not None:
            _watchdog_thread.join(timeout=4)

app=FastAPI(title='Gotham 4.0 Command Center',version='4.0.0-dev',lifespan=lifespan)
app.include_router(v4_router)
lock=Lock()

class Objective(BaseModel):
    goal:str=Field(min_length=10,max_length=1200)
    context:str=Field(default='',max_length=12000)

class Mission(BaseModel):
    goal:str=Field(min_length=4,max_length=500)
    code:str=Field(min_length=1,max_length=12000)
    tests:str=Field(min_length=1,max_length=6000)


def auth(request:Request):
    token=os.environ.get('GOTHAM_ACCESS_TOKEN','')
    if not token: raise HTTPException(503,'Mission token must be configured by operator')
    supplied=request.headers.get('X-Gotham-Token','')
    if not hmac.compare_digest(token,supplied): raise HTTPException(401,'Invalid mission token')


def batman_auth(request:Request):
    secret=os.environ.get('GOTHAM_BATMAN_TOKEN','')
    if not secret: raise HTTPException(503,'Independent Batman audit token must be configured')
    submitted=request.headers.get('X-Batman-Token','')
    if not hmac.compare_digest(secret,submitted):
        raise HTTPException(401,'Batman audit authorization required')

def ledger(result):
    DB.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, created TEXT, goal TEXT, status TEXT, receipt TEXT, elapsed_ms INTEGER)')
        conn.execute('INSERT INTO missions VALUES(?,?,?,?,?,?)',(
            result['mission_id'],datetime.now(timezone.utc).isoformat(),result['goal'][:250],
            result['status'],result['receipt_sha256'],result['elapsed_ms']))
        conn.commit()

@app.get('/',response_class=HTMLResponse)
def index():
    return (BASE/'static'/'index.html').read_text(encoding='utf-8')

@app.get('/health')
def health():
    client=get_inference_client()
    return {'status':'ok','project':'Gotham Project','sandbox_cli_present':bool(shutil.which('docker')),
            'inference_configured':client.configured,'inference_provider':client.provider_name,
            'vultr_inference_configured':client.configured and client.provider_name=='vultr-serverless-inference',
            'mission_token_configured':bool(os.environ.get('GOTHAM_ACCESS_TOKEN')),
            'audit_token_configured':bool(os.environ.get('GOTHAM_BATMAN_TOKEN')),
            'paid_inference_disabled_by_default':True,
            'architecture':'Batman (human) -> Alfred (captain) -> five workers plus four domain orchestras, independent Specter',
            'orchestra_count':len(orchestra_preview())}

@app.get('/api/agents')
def agents():
    return {'agents':[a.snapshot() for a in team()],'message':'Static team configuration; mission-specific decisions in receipts'}

@app.get('/api/sample')
def sample():
    return {'goal':'Repair the Python add function so it adds two numbers and passes the tests.',
            'code':'def add(a, b):\n    return a - b\n',
            'tests':'assert add(2, 3) == 5\nassert add(-4, 7) == 3\nassert add(0, 0) == 0\n'}

@app.post('/api/missions')
async def mission(payload:Mission,request:Request):
    auth(request)
    if not shutil.which('docker'):
        raise HTTPException(503,'Docker sandbox CLI unavailable; no untrusted code was executed')
    if not lock.acquire(blocking=False): raise HTTPException(429,'One mission at a time in competition mode')
    try:
        def sink(mission_id, actor, action, detail):
            # Fail closed if telemetry cannot be written: no mission is approved
            # without the event stream being captured for independent review.
            return _specter.record(mission_id,actor,action,detail)
        result=await asyncio.to_thread(run_mission,payload.goal,payload.code,payload.tests,telemetry=sink)
        await asyncio.to_thread(ledger,result)
        return result
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    finally:
        lock.release()

@app.post('/api/objectives')
async def objective(payload:Objective,request:Request):
    auth(request)
    if not lock.acquire(blocking=False):
        raise HTTPException(429,'Another Gotham mission is in progress')
    try:
        def sink(mission_id,actor,action,detail):
            if _specter is None:
                raise RuntimeError('Independent audit journal unavailable')
            return _specter.record(mission_id,actor,action,detail)
        answer=await asyncio.to_thread(run_objective,payload.goal,payload.context,telemetry=sink)
        await asyncio.to_thread(ledger,answer)
        return answer
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    finally:
        lock.release()

@app.get('/api/history')
def history(request:Request):
    auth(request)
    if not DB.exists(): return {'missions':[]}
    with sqlite3.connect(DB) as conn:
        rows=conn.execute('SELECT id,created,goal,status,receipt,elapsed_ms FROM missions ORDER BY created DESC LIMIT 25').fetchall()
    return {'missions':[dict(zip(('id','created','goal','status','receipt','elapsed_ms'),row)) for row in rows]}

@app.post('/api/containment-probe')
async def probe(request:Request):
    auth(request)
    if not shutil.which('docker'): raise HTTPException(503,'Docker sandbox CLI unavailable; containment probe not run')
    if not lock.acquire(blocking=False): raise HTTPException(429,'Wait for current mission to complete')
    try:
        return await asyncio.to_thread(containment_probe)
    except SandboxUnavailable as exc:
        raise HTTPException(503,str(exc)) from exc
    finally:
        lock.release()

@app.get('/api/batman/audit')
def batman_audit(request:Request):
    # Specter does not appear in /api/agents or any worker prompt.
    batman_auth(request)
    if _specter is None:
        raise HTTPException(503,'Independent audit process not started')
    return _specter.status()


@app.get('/specter', response_class=HTMLResponse)
def specter_dashboard():
    # The static shell discloses no events; private data requires the separate audit token.
    return (BASE/'static'/'specter.html').read_text(encoding='utf-8')

@app.get('/api/batman/specter/missions')
def specter_missions(request: Request):
    batman_auth(request)
    return {'missions':_specter.recent_missions(), 'status':_specter.status()}

@app.get('/api/batman/specter/mission/{mission_id}')
def specter_mission(mission_id: str, request: Request):
    batman_auth(request)
    try:
        return _specter.mission_report(mission_id)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


class OrchestraOrder(BaseModel):
    orchestra:str=Field(min_length=2,max_length=32)
    goal:str=Field(min_length=10,max_length=1000)
    context:str=Field(default='',max_length=3000)
    scope:str=Field(default='',max_length=800)

@app.get('/command',response_class=HTMLResponse)
def command_center():
    return (BASE/'static'/'command.html').read_text(encoding='utf-8')

@app.get('/orchestra',response_class=HTMLResponse)
def orchestra_dashboard():
    return (BASE/'static'/'orchestra.html').read_text(encoding='utf-8')

@app.get('/api/orchestras')
def orchestra_list():
    return {'orchestras':orchestra_preview(),
            'disclaimer':'Orchestra planning is AI analysis only. Only the Code Repair route executes contained code.'}

@app.post('/api/orchestra/dispatch')
async def orchestra_dispatch(payload:OrchestraOrder,request:Request):
    auth(request)
    if not lock.acquire(blocking=False):
        raise HTTPException(429,'Another mission is already running')
    try:
        def sink(mission_id,actor,action,detail):
            if _specter is None:
                raise RuntimeError('Independent Specter audit journal unavailable')
            return _specter.record(mission_id,actor,action,detail)
        report=await asyncio.to_thread(run_orchestra,payload.orchestra,payload.goal,
                        payload.context,payload.scope,telemetry=sink)
        await asyncio.to_thread(ledger,report)
        return report
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    finally:
        lock.release()


@app.post('/api/orchestra/demo')
async def orchestra_demo(payload:OrchestraOrder,request:Request):
    """Narrow, real Docker-tested artifact example; never unrestricted code generation."""
    auth(request)
    if not shutil.which('docker'): raise HTTPException(503,'Docker unavailable')
    if not lock.acquire(blocking=False): raise HTTPException(429,'Another mission is running')
    try:
        def sink(mission_id,actor,action,detail):
            return _specter.record(mission_id,actor,action,detail)
        report=await asyncio.to_thread(run_orchestra,payload.orchestra,payload.goal,
            payload.context,payload.scope,telemetry=sink)
        mid=report['mission_id']
        _specter.record(mid,'Alfred','demo_artifact_requested',{'state':'started'})
        artifact=await asyncio.to_thread(execute_demo,payload.orchestra,payload.goal,payload.scope)
        ev=artifact['evidence']
        _specter.record(mid,'Alfred','sandbox_result',{
            'sandbox':ev.get('sandbox'),'network':ev.get('network'),
            'passed':ev.get('passed'),'container_destroyed':ev.get('container_destroyed'),
            'timed_out':ev.get('timed_out'),'exit_code':ev.get('exit_code')})
        _specter.record(mid,'Alfred','demo_artifact_completed',{'verified_evidence':artifact['verified_execution']})
        report['demo_artifact']=artifact
        report['artifact_produced_by']='deterministic bounded demo artifact engine, NOT unrestricted model coding'
        report['executed']=artifact['verified_execution']
        report['verified_evidence']=artifact['verified_execution']
        report['status']=('demo_verified' if artifact['verified_execution'] and all(w.get('status')=='analysis_ready' for w in report.get('worker_reports',[])) else ('docker_verified_ai_incomplete' if artifact['verified_execution'] else 'demo_failed'))
        report['receipt_sha256']=hashlib.sha256(json.dumps({k:v for k,v in report.items() if k!='receipt_sha256'},sort_keys=True).encode()).hexdigest()
        await asyncio.to_thread(ledger,report)
        return report
    except (ValueError,SandboxUnavailable) as exc:
        raise HTTPException(400,str(exc)) from exc
    finally:
        lock.release()


class SpecterQuestion(BaseModel):
    mission_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=4, max_length=500)

@app.post('/api/batman/specter/explain')
def specter_explain(payload: SpecterQuestion, request: Request):
    """Read-only deterministic evidence explanation, never delegated to Alfred."""
    batman_auth(request)
    report=_specter.mission_report(payload.mission_id)
    if not report['events']:
        return {'answer':'No recorded events for this mission. Specter cannot infer unrecorded actions.', 'report':report}
    by_agent={}
    for entry in report['events']:
        by_agent.setdefault(entry['actor'],[]).append(entry['action'])
    lines=['Recorded actions by agent (not proof of unlogged actions):']
    for agent,actions in by_agent.items():
        lines.append(f'{agent}: '+', '.join(actions[:30]))
    lines.append(f'Findings: {len(report["findings"])}. Internal hash chain valid: {report["integrity"]["valid"]}.')
    for finding in report['findings'][:15]:
        lines.append(f'{finding["severity"]} / {finding["code"]}: {finding["message"]}')
    lines.append('Limitation: This report contains recorded event metadata only; it cannot independently prove everything agents did or did not do.')
    return {'answer':'\n'.join(lines),'report':report}
