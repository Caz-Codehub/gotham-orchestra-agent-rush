"""Falsification tests for the restricted approved-only sandbox executor.

These are control-plane tests. Actual Docker work is independently exercised
by the existing four-orchestra 25-task CI integration acceptance.
"""
import pytest

from gotham.core.audit import AuditWriter
from gotham.core.engine import Alfred
from gotham.core.sandbox_evidence_worker import (
    ALLOWED_PAIRS, SandboxWorkerBlocked, preflight, run
)
from gotham.core.store import Store
from tests.test_orchestra_durable import FakeModel

SCOPE = "Owned, offline disposable security training lab with synthetic files"
WORKLOAD = {"files": {"main.py": "print('hello')\n", "test_main.py": "def test_ok(): assert True\n"}}


def _orchestra(engine):
    mid = engine.submit("orchestra", "Analyze bounded synthetic code and produce a sandbox receipt",
                        {"orchestra": "software", "scope": SCOPE, "execute": True,
                         "workloads": {"software": WORKLOAD}},
                        "operator:test")
    task = next(t for t in engine.store.tasks_for(mid) if t["kind"] == "build_and_verify")
    return mid, task


def _engine(env):
    return Alfred(store=Store(env / "data" / "sandbox_worker.sqlite3"),
                  audit=AuditWriter(env / "audit" / "sandbox_worker.sqlite3"),
                  client=FakeModel())


def test_exact_four_registered_evidence_pairs():
    assert ALLOWED_PAIRS == {
        ("Forge", "build_and_verify"), ("Oracle", "research"),
        ("Sentinel", "audit"), ("Cipher", "lab_validation")
    }


def test_unapproved_high_risk_task_never_executes_even_if_queued(env):
    engine = _engine(env)
    mid, task = _orchestra(engine)
    engine.store.set_task_status(task["id"], "pending")
    called = []
    engine.execute_task = lambda *a, **k: called.append(a)
    run(engine=engine, once=True)
    updated = engine.store.get_task(task["id"])
    # Depends on captain review, which has not completed; still not claimed.
    assert updated["status"] == "pending" and not called


def test_worker_claims_only_approved_orchestra_evidence_and_no_legacy_task(env):
    engine = _engine(env)
    mid, evidence = _orchestra(engine)
    # Mark its captain predecessors successful using the existing deterministic
    # inference fixtures; leave the high-risk evidence awaiting approval.
    from tests.conftest import run_until_done
    run_until_done(engine, concurrency=1)
    pending = [a for a in engine.store.approvals("pending", mid)
               if a["task_id"] == evidence["id"] and a["action"] == "task_start"]
    assert len(pending) == 1
    called = []
    engine.execute_task = lambda task, worker: called.append((task["agent"], task["kind"]))
    run(engine=engine, once=True)
    assert not called

    engine.store.decide_approval(pending[0]["id"], True, "batman-ci-fixture")
    run(engine=engine, once=True)
    assert called == [("Forge", "build_and_verify")]


def test_manually_bypassed_approval_is_detected_after_dependency_complete(env):
    engine = _engine(env)
    mid, evidence = _orchestra(engine)
    from tests.conftest import run_until_done
    run_until_done(engine, concurrency=1)
    engine.store.set_task_status(evidence["id"], "pending")
    called = []
    engine.execute_task = lambda task, worker: called.append(task)
    run(engine=engine, once=True)
    assert called == []
    assert engine.store.get_task(evidence["id"])["status"] == "failed"


def test_production_worker_requires_explicit_enablement(monkeypatch):
    monkeypatch.delenv("GOTHAM_SANDBOX_WORKER_ENABLE", raising=False)
    with pytest.raises(SandboxWorkerBlocked, match="not explicitly enabled"):
        preflight()
    monkeypatch.setenv("GOTHAM_SANDBOX_WORKER_ENABLE", "YES")
    monkeypatch.setattr("os.geteuid", lambda: 0)
    with pytest.raises(SandboxWorkerBlocked, match="never run as root"):
        preflight()
