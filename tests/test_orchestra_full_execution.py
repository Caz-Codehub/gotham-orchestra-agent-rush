"""All-four-orchestra real sandbox acceptance; 12 model identities, four tool-backed jobs.

Only the *reasoning* is supplied by a deterministic fixture model in this CI
test. Docker, Git, pytest, notebook execution, scanners and the security lab
are real. No remote inference or production credentials are accessed.
"""
import json
import subprocess

import pytest

from gotham.core import config, sbx
from gotham.core.audit import AuditReader
from gotham.core.engine import Alfred
from tests.conftest import needs_docker, run_until_done
from tests.test_orchestra_durable import FakeModel
from tests.fixtures import BUGGY_PROJECT, FIX_PATCH, NOTEBOOK_CELLS, WEAK_EXPECTED, WEAK_PROJECT

pytestmark = [pytest.mark.integration, needs_docker]
needs_research = pytest.mark.skipif(
    not sbx.image_present(config.RESEARCH_IMAGE),
    reason="gotham-research real notebook sandbox image not built"
)
SCOPE = "Owned, offline disposable cyberdefense exercise using only self-created fixtures"


@needs_research
def test_all_four_orchestras_produce_real_evidence_only_after_test_batman_approval(env):
    alfred = Alfred(client=FakeModel())
    workload = {
        "software": {"files": BUGGY_PROJECT, "patch": FIX_PATCH},
        "research": {"name": "analysis", "cells": NOTEBOOK_CELLS},
        "defense": {"files": WEAK_PROJECT, "expect_rules": WEAK_EXPECTED},
        "lab": {"secure": True, "expect_vulnerable": []},
    }
    mid = alfred.submit(
        "orchestra", "Validate all four domain artifacts using disposable offline fixtures",
        {"orchestra": "all", "scope": SCOPE, "execute": True, "workloads": workload},
        "test-operator"
    )
    tasks = alfred.store.tasks_for(mid)
    assert len(tasks) == 25
    assert sum(t["kind"] == "orchestra_specialist" for t in tasks) == 12
    evidence = [t for t in tasks if t["kind"] in ("build_and_verify", "research", "audit", "lab_validation")]
    assert len(evidence) == 4
    assert all(t["risk"] == "high" for t in evidence)
    pending = alfred.store.approvals("pending", mid)
    assert len(pending) == 4

    # Execute all model-backed planning and captain review work, but preserve
    # the four explicit Batman gates. No actual tool-backed task runs yet.
    run_until_done(alfred, concurrency=4)
    assert all(t["status"] == "awaiting_approval" for t in alfred.store.tasks_for(mid) if t["id"] in {e["id"] for e in evidence})
    assert not any(t["status"] == "succeeded" for t in alfred.store.tasks_for(mid) if t["id"] in {e["id"] for e in evidence})
    assert not any(e["action"] == "tool_call" and e["actor"] in {"Forge", "Oracle", "Sentinel", "Cipher"}
                   for e in AuditReader(config.audit_path()).events(mid, limit=5000))

    # Explicit TEST approval only; production requests are not auto-approved.
    for approval in pending:
        alfred.store.decide_approval(approval["id"], True, "batman-ci-fixture")
        alfred.audit.record(mid, approval["task_id"], "Batman", "approval_decided",
                            {"approval_id": approval["id"], "approved": True, "test_fixture": True})

    run_until_done(alfred, concurrency=4)
    mission = alfred.store.get_mission(mid)
    assert mission["status"] == "verified", json.dumps(mission["result"], default=str)[:3500]
    report = mission["result"]
    assert report["verified"] is True and report["execution_verified"] is True
    assert len(alfred.store.tasks_for(mid)) == 25
    assert len(report["evidence_tasks"]) == 4
    assert {t["agent"] for t in report["evidence_tasks"]} == {"Forge", "Oracle", "Sentinel", "Cipher"}
    assert all(t["receipt"] for t in report["evidence_tasks"])

    real_tasks = {t["kind"]: t for t in alfred.store.tasks_for(mid) if t["kind"] in
                  ("build_and_verify", "research", "audit", "lab_validation")}
    forge = real_tasks["build_and_verify"]["result"]["evidence"]
    assert not forge["tests_before"]["ok"] and forge["tests_after"]["ok"]
    assert forge["tests_after"]["container_destroyed"] and forge["commit"]
    oracle = real_tasks["research"]["result"]["evidence"]
    assert oracle["notebook"]["ok"] and oracle["notebook"]["code_cells"] == oracle["notebook"]["executed_cells"]
    sentinel = real_tasks["audit"]["result"]["evidence"]
    assert not sentinel["expected_rules_missing"] and len(sentinel["scans"]) >= 3
    cipher = real_tasks["lab_validation"]["result"]["evidence"]
    assert cipher["scope_enforced"] is True and cipher["stopped"]["removed"] is True
    assert cipher["probe"]["vulnerabilities"] == []

    audit = AuditReader(config.audit_path())
    assert audit.verify()["valid"]
    events = audit.events(mid, limit=5000)
    assert {e["actor"] for e in events if e["action"] == "tool_call"} >= {"Forge", "Oracle", "Sentinel", "Cipher"}
    assert len([e for e in events if e["action"] == "captain_report_to_alfred"]) == 4
    assert any(e["action"] == "alfred_aggregated_captain_reports" for e in events)
    assert subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=gotham-lab=1"],
        check=True, capture_output=True, text=True
    ).stdout.strip() == ""


@needs_research
def test_unapproved_orchestra_tool_jobs_cannot_pass_final_verification(env):
    alfred = Alfred(client=FakeModel())
    mid = alfred.submit(
        "orchestra", "Review disposable research and lab fixtures",
        {"orchestra": "lab", "scope": SCOPE, "execute": True,
         "workloads": {"lab": {"secure": True, "expect_vulnerable": []}}},
        "test-operator"
    )
    run_until_done(alfred, concurrency=2)
    tasks = alfred.store.tasks_for(mid)
    assert any(t["kind"] == "lab_validation" and t["status"] == "awaiting_approval" for t in tasks)
    assert not any(t["kind"] == "orchestra_synthesis" and t["status"] == "succeeded" for t in tasks)
    assert alfred.store.get_mission(mid)["status"] != "verified"
