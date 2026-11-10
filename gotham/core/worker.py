"""Standalone worker service: `python -m gotham.core.worker`. Survives API restarts; recovers expired leases."""
from __future__ import annotations
import os
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import config, sbx
from .engine import Alfred
from ..inference import get_inference_client


def run_worker(alfred: Alfred | None = None, *, concurrency: int = 4, stop: threading.Event | None = None, poll: float = 0.5,
               worker_id: str | None = None, once: bool = False) -> None:
    alfred = alfred or Alfred(client=get_inference_client())
    stop = stop or threading.Event()
    wid = worker_id or f'worker-{os.getpid()}-{uuid.uuid4().hex[:6]}'
    pool = ThreadPoolExecutor(max_workers=concurrency)
    active = set()
    last_gc = 0.0
    alfred.recover()
    while not stop.is_set():
        alfred.store.worker_seen(wid, os.getpid(), concurrency)
        active = {f for f in active if not f.done()}
        did = False
        if len(active) < concurrency:
            task = alfred.store.claim_next(wid, config.LEASE_SECONDS)
            if task:
                active.add(pool.submit(alfred.execute_task, task, wid))
                did = True
        now = time.time()
        if now - last_gc > 10:
            alfred.recover()
            if now - last_gc > 300 and last_gc:
                sbx.cleanup_stale()
            last_gc = now
        if once and not did and not active:
            break
        if not did:
            stop.wait(poll)
    pool.shutdown(wait=True)


if __name__ == '__main__':
    ev = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: ev.set())
    signal.signal(signal.SIGINT, lambda *_: ev.set())
    run_worker(stop=ev, concurrency=int(os.environ.get('GOTHAM_WORKER_CONCURRENCY', '4')))
