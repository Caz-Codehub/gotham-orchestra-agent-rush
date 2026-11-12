"""Falsification-oriented H0/H1 tests for all four Gotham orchestra execution contracts.

H0: a domain adapter accepts only inputs that its actual playbook can consume,
produces a gated evidence task and cannot bypass Batman approval.
H1: a counterexample exists (wrong kind, missing args, no approval, false verification).
Passing tests is evidence *against examined H1 cases*, not proof of correctness.
"""
import pytest

from gotham.core.orchestra_missions import mission_plan
from gotham.core.playbooks import PLAYBOOKS
from gotham.core.engine import Alfred
from gotham.core.store import Store
from gotham.core.audit import AuditWriter

SCOPE = "Owned, offline disposable cyberdefense exercise in isolated test containers"

WORKLOADS = {
    "software": {"files": {"main.py": "def add(a,b): return a+b\n",
                            "test_main.py": "from main import add\ndef test_add(): assert add(2,3)==5\n"}},
    "research": {"name": "experiment", "cells": [
        {"type": "code", "source": "assert 1 + 1 == 2"}]},
    "defense": {"files": {"safe.py": "print('test')\n"}},
    "lab": {"secure": True, "expect_vulnerable": []},
}
EXPECTED = {
    "software": ("Forge", "build_and_verify"),
    "research": ("Oracle", "research"),
    "defense": ("Sentinel", "audit"),
    "lab": ("Cipher", "lab_validation"),
}


@pytest.mark.parametrize("domain", list(WORKLOADS))
def test_h0_each_orchestra_has_registered_executable_playbook_and_approval(domain, env):
    plan = mission_plan("Validate a disposable synthetic work product",
                        {"orchestra": domain, "scope": SCOPE, "execute": True,
                         "workloads": {domain: WORKLOADS[domain]}})
    specialist_tasks = [x for x in plan if x["kind"] == "orchestra_specialist"]
    assert len(specialist_tasks) == 3
    assert all(x["agent"].startswith(domain + ":") for x in specialist_tasks)
    evidence = [x for x in plan if x["key"] == domain + ":evidence"]
    assert len(evidence) == 1
    task = evidence[0]
    assert (task["agent"], task["kind"]) == EXPECTED[domain]
    assert (task["agent"], task["kind"]) in PLAYBOOKS
    assert task["risk"] == "high"
    assert task["tools"] == (["lab_start", "lab_probe", "lab_stop"] if domain == "lab" else [])
    assert task["after"] == [domain + ":review"]
    assert plan[-1]["agent"] == "Alfred"
    assert plan[-1]["after"] == [domain + ":evidence"]
    # Persisted task must remain unapproved until Batman decides.
    engine = Alfred(store=Store(env / "data" / (domain + ".sqlite3")),
                    audit=AuditWriter(env / "audit" / (domain + ".sqlite3")))
    mid = engine.submit("orchestra", "Validate a disposable synthetic work product",
                        {"orchestra": domain, "scope": SCOPE, "execute": True,
                         "workloads": {domain: WORKLOADS[domain]}}, "operator:test")
    pending = engine.store.approvals(mission_id=mid)
    assert len(pending) == 1
    assert pending[0]["action"] == "task_start" and pending[0]["status"] == "pending"
    assert pending[0]["detail"]["tools"] == task["tools"]


@pytest.mark.parametrize("domain,bad_workload", [
    ("software", {"files": {}}),
    ("software", {"files": {"main.py": 123}}),
    ("research", {"notebook": "fake.ipynb"}),
    ("research", {"name": "fake.ipynb", "cells": []}),
    ("research", {"name": "fake.ipynb", "cells": [{"type":"code","source":"print(1)"}]}),
    ("research", {"name": "fake", "cells": [{"cell_type":"code","source":"print(1)"}]}),
    ("defense", {"files": {}}),
    ("lab", {"sample": {"name": "suspicious.exe", "content": "x"}}),
    ("lab", {"secure": "yes"}),
    ("lab", {"secure": True, "dynamic": True}),
])
def test_h1_invalid_workload_is_rejected_at_plan_time(domain, bad_workload):
    with pytest.raises(ValueError):
        mission_plan("Validate a disposable synthetic work product",
                     {"orchestra": domain, "scope": SCOPE, "execute": True,
                      "workloads": {domain: bad_workload}})


def test_h0_all_four_execution_plan_has_four_approval_gated_playbooks():
    plan = mission_plan("Validate synthetic artifacts in every scoped domain",
                        {"orchestra": "all", "scope": SCOPE, "execute": True,
                         "workloads": WORKLOADS})
    assert len(plan) == 25
    evidence = [x for x in plan if x["key"].endswith(":evidence")]
    assert len(evidence) == 4
    assert {x["agent"] for x in evidence} == {"Forge", "Oracle", "Sentinel", "Cipher"}
    assert all(x["risk"] == "high" for x in evidence)
    assert set(plan[-1]["after"]) == {d + ":evidence" for d in WORKLOADS}
