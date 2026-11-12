"""Restricted, opt-in worker for Batman-approved four-orchestra sandbox evidence.

Unlike the local Qwen analysis worker, this executor can call the existing
offline Docker/Git/notebook/scanner/lab playbooks. It never receives the
12 specialist roles or Alfred's inference tasks, never auto-approves jobs,
and cannot be enabled by ordinary staging release automation.
"""
from __future__ import annotations

import fcntl
import os
import shutil
import signal
import subprocess
import threading
import uuid

from . import config
from .engine import Alfred

ALLOWED_PAIRS = frozenset({
    ("Forge", "build_and_verify"),
    ("Oracle", "research"),
    ("Sentinel", "audit"),
    ("Cipher", "lab_validation"),
})


class SandboxWorkerBlocked(RuntimeError):
    pass


def preflight() -> None:
    if os.environ.get("GOTHAM_SANDBOX_WORKER_ENABLE") != "YES":
        raise SandboxWorkerBlocked("restricted sandbox executor is not explicitly enabled")
    if os.geteuid() == 0:
        raise SandboxWorkerBlocked("sandbox executor must never run as root")
    if not shutil.which("docker"):
        raise SandboxWorkerBlocked("Docker CLI is not available")
    # An independent sandbox identity with narrowly scoped Docker privileges
    # must be provisioned and approved separately from the current rootless
    # staging / inference / production services.
    test = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True, text=True, timeout=12, check=False,
    )
    if test.returncode or not test.stdout.strip():
        raise SandboxWorkerBlocked("approved sandbox Docker daemon is unavailable")


def run(*, engine=None, stop=None, once=False, poll=0.5) -> None:
    stop = stop or threading.Event()
    managed = engine is None
    if managed:
        preflight()
    engine = engine or Alfred(client=None)
    wid = "sandbox-evidence-" + uuid.uuid4().hex[:12]
    engine.audit.record(None, None, "Alfred", "restricted_sandbox_worker_started",
                        {"worker": wid, "task_pairs": len(ALLOWED_PAIRS),
                         "mission_type": "orchestra", "approved_only": True})
    while not stop.is_set():
        engine.store.worker_seen(wid, os.getpid(), 1)
        task = engine.store.claim_next(
            wid, config.LEASE_SECONDS,
            allowed_pairs=ALLOWED_PAIRS,
            mission_kinds={"orchestra"},
        )
        if task:
            mid, tid = task["mission_id"], task["id"]
            if task["risk"] != "high" or not engine.store.has_approval(tid, "task_start"):
                # The SQL lease is already acquired. Never execute an unapproved
                # task even if someone manually changed its status to pending.
                engine.audit.record(mid, tid, "Alfred", "sandbox_job_blocked",
                                    {"reason": "missing_explicit_batman_approval",
                                     "agent": task["agent"], "kind": task["kind"]})
                engine.store.finish_task(tid, wid, "failed",
                                         {"status": "blocked", "summary": "Batman approval missing"},
                                         "Batman task-start approval missing")
                engine.advance(mid)
                continue
            engine.execute_task(task, wid)
            continue
        if once:
            break
        stop.wait(poll)


def main():
    preflight()
    lock_path = config.data_dir() / "sandbox-evidence-worker.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise SystemExit("BLOCKED: another restricted sandbox executor holds the lease lock")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        run(stop=stop)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
