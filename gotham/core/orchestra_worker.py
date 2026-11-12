"""Restricted non-root Gotham worker for the four orchestra analysis DAGs.

Claims ONLY the 12 scoped specialist identities, four captains, and Alfred.
No Docker socket or privileged playbook access is needed. Any non-orchestral
work remains blocked until a separately authorized sandbox worker is deployed.
"""
from __future__ import annotations
import os
import fcntl
from pathlib import Path
import signal
import threading
import time
import uuid

from . import config
from .engine import Alfred
from .orchestra_missions import roster
from .model_budget import MissionModelClient
from ..inference import get_inference_client

ALLOWED_KINDS = frozenset(('orchestra_plan', 'orchestra_specialist',
                           'orchestra_review', 'orchestra_synthesis'))
SCOPED_AGENTS = frozenset(
    ['Alfred'] + [
        name
        for orchestra in roster()['orchestras']
        for name in ([f"{orchestra['id']}:captain"]
                     + [p['id'] for p in orchestra['specialists']])
    ]
)
ALLOWED_PAIRS = frozenset(
    [('Alfred', 'orchestra_synthesis')]
    + [(f"{o['id']}:captain", kind)
       for o in roster()['orchestras']
       for kind in ('orchestra_plan', 'orchestra_review')]
    + [(p['id'], 'orchestra_specialist')
       for o in roster()['orchestras']
       for p in o['specialists']]
)


def run(stop: threading.Event | None = None, *, once=False, poll=0.5, engine=None, client_factory=None):
    stop = stop or threading.Event()
    # An injected engine keeps its supplied model for deterministic unit tests.
    # Production obtains a distinct model client for each mission, not one for
    # the entire lifetime of the worker daemon.
    managed = engine is None or client_factory is not None
    engine = engine or Alfred(client=None)
    factory = client_factory or get_inference_client
    mission_clients = {}
    wid = "orchestra-worker-" + uuid.uuid4().hex[:12]
    engine.audit.record(None, None, 'Alfred', 'orchestra_worker_started',
                        {'worker': wid, 'mode': 'analysis_only',
                         'authorized_agent_slots': len(SCOPED_AGENTS)})
    last_recover = 0.0
    while not stop.is_set():
        engine.store.worker_seen(wid, os.getpid(), 1)
        task = engine.store.claim_next(wid, config.LEASE_SECONDS,
                                     allowed_pairs=ALLOWED_PAIRS, mission_kinds={'orchestra'})
        if task:
            if task['kind'] not in ALLOWED_KINDS:
                engine.audit.record(task['mission_id'], task['id'], 'Alfred',
                                    'orchestra_worker_rejected_task',
                                    {'kind': task['kind']})
                engine.store.finish_task(task['id'], wid, 'failed', {
                    'status': 'blocked', 'summary': 'not an orchestra task'
                }, 'restricted orchestra worker denied task')
                engine.advance(task['mission_id'])
            else:
                if managed:
                    mid = task['mission_id']
                    if mid not in mission_clients:
                        # Durable Store reservations still cap resumed/evicted
                        # missions; new clients cannot reset the mission quota.
                        if len(mission_clients) >= 16:
                            mission_clients.pop(next(iter(mission_clients)))
                        mission_clients[mid] = factory()
                    engine.client = MissionModelClient(
                        mission_id=mid, delegate=mission_clients[mid],
                        store=engine.store, audit=engine.audit)
                engine.execute_task(task, wid)
                if managed:
                    mission = engine.store.get_mission(task['mission_id'])
                    if mission and mission['status'] in ('verified', 'completed_unverified', 'failed', 'cancelled', 'blocked'):
                        mission_clients.pop(task['mission_id'], None)
            continue
        if time.monotonic() - last_recover >= 30:
            engine.recover()
            last_recover = time.monotonic()
        if once:
            break
        stop.wait(poll)


def main():
    # Single-worker ownership is protected by an OS flock, not just a PID file.
    # File descriptors are held until process exit, including SIGKILL.
    lock_path = config.data_dir() / "orchestra-worker.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise SystemExit("BLOCKED: another orchestra worker owns the data store")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        run(stop)
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
