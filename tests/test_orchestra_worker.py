"""Restricted orchestra worker cannot claim legacy sandbox/security tasks."""
from gotham.core.engine import Alfred
from gotham.core.worker import run_worker
from gotham.core.orchestra_worker import SCOPED_AGENTS, run
from gotham.core.store import Store
from gotham.core.audit import AuditWriter
from tests.test_orchestra_durable import FakeModel, SCOPE


def test_scoped_worker_roster():
    assert len(SCOPED_AGENTS) == 17
    assert "Alfred" in SCOPED_AGENTS
    assert "Forge" not in SCOPED_AGENTS
    assert "Cipher" not in SCOPED_AGENTS


def test_restricted_worker_will_not_take_security_scan_task(env):
    a = Alfred(store=Store(env / "data" / "restricted.sqlite3"),
               audit=AuditWriter(env / "audit" / "restricted.sqlite3"),
               client=FakeModel())
    m = a.submit("security_audit", "Scan a synthetic file safely",
                 {"files": {"file.py": "print(1)\n"}}, "operator:test")
    run(once=True, engine=a)
    tasks = a.store.tasks_for(m)
    assert tasks
    assert not any(t["status"] == "succeeded" for t in tasks)
    assert not any(t["status"] == "running" for t in tasks)


def test_restricted_worker_executes_only_orchestra_tasks(env):
    fake = FakeModel()
    a = Alfred(store=Store(env / "data" / "orchestra-worker.sqlite3"),
               audit=AuditWriter(env / "audit" / "orchestra-worker.sqlite3"),
               client=fake)
    m = a.submit("orchestra", "Plan a synthetic four-domain defensive workflow",
                 {"orchestra": "all", "scope": SCOPE}, "operator:test")
    run(once=True, engine=a)
    state = a.store.get_mission(m)
    assert state["status"] == "completed_unverified"
    assert state["result"]["verified"] is False
    assert fake.calls == 21
