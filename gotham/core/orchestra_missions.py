"""Durable four-orchestra mission plan and bounded inference with hidden pre-model audit.

This module deliberately performs *analysis*, not arbitrary software execution.
Only the existing approved Gotham playbooks/tool registry can execute work. All
model claims remain unverified until real tool/sandbox evidence is attached.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..orchestras import ORCHESTRAS
from ..inference import InferenceError


class OrchestraBlocked(RuntimeError):
    pass


INJECTION_PATTERN = re.compile(
    r"(?i)(ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules)|"
    r"reveal .{0,40}(?:private key|secret|token)|"
    r"disregard .{0,40}(?:rules|instructions)|"
    r"exfiltrate|you are now the system)"
)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


def roster() -> dict:
    """Authoritative scoped identities, never five global workers masquerading as twelve."""
    rows = []
    for oid, spec in ORCHESTRAS.items():
        rows.append({
            "id": oid, "label": spec["label"], "captain": spec["captain"],
            "reports_to": "Alfred",
            "specialists": [
                {"id": f"{oid}:{role}", "name": role, "legacy_tool_role": actor,
                 "responsibility": focus, "reports_to": spec["captain"]}
                for actor, role, focus in spec["roles"]
            ],
        })
    assert len(rows) == 4 and sum(len(o["specialists"]) for o in rows) == 12
    return {"supervisor": "Alfred", "orchestras": rows,
            "captains": 4, "specialists": 12,
            "audit": "independent/private", "execution_state": "not established by roster"}


def mission_plan(goal: str, params: dict) -> list[dict]:
    """Make one or four orchestra DAGs for Alfred's leased worker scheduler."""
    ids = list(ORCHESTRAS) if params.get("orchestra") == "all" else [params.get("orchestra")]
    if any(oid not in ORCHESTRAS for oid in ids):
        raise ValueError("orchestra must be software, research, defense, lab, or all")
    scope = str(params.get("scope", ""))
    if "lab" in ids and len(scope.strip()) < 12:
        raise ValueError("Authorized Security Lab requires a named, explicitly authorized laboratory scope")
    context = str(params.get("context", ""))
    if len(context) > 3000 or len(scope) > 800:
        raise ValueError("context or scope too large")
    plan = []
    for oid in ids:
        spec = ORCHESTRAS[oid]
        captain_id = f"{oid}:captain"
        common = {"orchestra": oid, "goal": goal, "context": context, "scope": scope}
        plan.append({"key": captain_id, "agent": captain_id,
                     "kind": "orchestra_plan", "title": f"{spec['captain']} delegates",
                     "params": common, "workdir": f"orchestras/{oid}/captain", "timeout": 240})
        positions = []
        for actor, role, focus in spec["roles"]:
            key = f"{oid}:{role}"
            positions.append(key)
            plan.append({"key": key, "agent": key, "kind": "orchestra_specialist",
                         "title": f"{role}: {focus}", "params": {**common, "role": role, "focus": focus,
                         "legacy_tool_role": actor}, "after": [captain_id],
                         "workdir": f"orchestras/{oid}/{actor}-{role.replace(' ', '_')}", "timeout": 240})
        plan.append({"key": f"{oid}:review", "agent": captain_id,
                     "kind": "orchestra_review", "title": f"{spec['captain']} verifies reports to Alfred",
                     "params": common, "after": positions, "workdir": f"orchestras/{oid}/review",
                     "timeout": 240})
    # Optional real-execution lane, blocked until Batman grants explicit
    # per-task high-risk approval and a separately sandbox-authorized worker exists.
    # No static model reports are treated as execution receipts.
    exec_mode = params.get("execute", False)
    if not isinstance(exec_mode, bool):
        raise ValueError("execute must be a boolean")
    dependencies = [f"{oid}:review" for oid in ids]
    if exec_mode:
        workloads = params.get("workloads")
        if not isinstance(workloads, dict) or any(
            oid not in workloads or not isinstance(workloads[oid], dict) for oid in ids
        ):
            raise ValueError("execution requires explicit workload object for every selected orchestra")
        adapters = {
            "software": ("Forge", "build_and_verify"),
            "research": ("Oracle", "research"),
            "defense": ("Sentinel", "audit"),
            "lab": ("Cipher", "lab_validation"),
        }
        dependencies = []
        for oid in ids:
            p = workloads[oid]
            if oid == "software" and (
                not isinstance(p.get("files"), dict) or not p["files"]
                or not all(isinstance(k, str) and isinstance(v, str) for k,v in p["files"].items())
            ):
                raise ValueError("software execution requires nonempty source/test files")
            if oid == "research" and (
                not isinstance(p.get("name"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", p["name"])
                or not isinstance(p.get("cells"), list) or not p["cells"]
                or not all(isinstance(c, dict) and c.get("type") in ("code", "markdown")
                           and isinstance(c.get("source"), str) for c in p["cells"])
            ):
                raise ValueError("research execution requires a filename without extension and cells with type/code|markdown and source")
            if oid == "defense" and (
                not isinstance(p.get("files"), dict) or not p["files"]
            ):
                raise ValueError("defensive scan requires nonempty authorized source files")
            if oid == "lab":
                if p.get("dynamic") or p.get("sample"):
                    raise ValueError("lab_validation uses only an isolated lab, not malware samples or dynamic payloads")
                if not isinstance(p.get("secure"), bool):
                    raise ValueError("lab execution requires explicit secure=true/false scoped lab fixture")
            agent, task_kind = adapters[oid]
            key = f"{oid}:evidence"
            plan.append({"key": key, "agent": agent, "kind": task_kind,
                         "title": f"Approved sandbox evidence for {oid}",
                         "params": p, "after": [f"{oid}:review"],
                         "risk": "high", "scope": scope or "approved local sandbox only",
                         "workdir": f"orchestras/{oid}/evidence", "timeout": 900})
            dependencies.append(key)
    plan.append({"key": "alfred:synthesis", "agent": "Alfred",
                 "kind": "orchestra_synthesis", "title": "Alfred verifies captain reports",
                 "params": {"goal": goal, "context": context, "scope": scope,
                            "orchestra": params.get("orchestra"), "execute": exec_mode},
                 "after": dependencies,
                 "workdir": "orchestras/alfred/synthesis", "timeout": 240})
    return plan


def _safe_input(text: str, limit: int) -> str:
    if not isinstance(text, str) or len(text) > limit or "\x00" in text:
        raise OrchestraBlocked("invalid or oversized model input")
    if INJECTION_PATTERN.search(text):
        raise OrchestraBlocked("untrusted instructions blocked before model invocation")
    return text


def _invoke(ctx, client, actor: str, system: str, payload: dict, *, max_tokens=220) -> tuple[dict, str]:
    """Commit a metadata-only receipt before each inference call; exceptions fail closed."""
    if not getattr(client, "configured", False):
        raise OrchestraBlocked("No configured inference model; orchestra work was not simulated")
    # Role prompts contain no private audit identity, DB path, tokens or internal topology.
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    _safe_input(raw, 12000)
    input_sha = hashlib.sha256(raw.encode()).hexdigest()
    ctx.record("pre_model_gate", {"actor": actor, "input_sha256": input_sha,
                                  "payload_bytes": len(raw), "permitted": True})
    # If the independent audit writer cannot commit, execution never reaches the model.
    try:
        result = client.json(system, raw, max_tokens=max_tokens)
    except InferenceError:
        ctx.record("model_unavailable", {"actor": actor})
        raise
    if not isinstance(result, dict):
        raise OrchestraBlocked("model result was not a JSON object")
    result_sha = _digest(result)
    ctx.record("model_result_received", {"actor": actor, "result_sha256": result_sha,
                                          "provider": str(getattr(client, "provider_name", "unknown"))[:48]})
    return result, result_sha


def execute(ctx, params: dict, client) -> dict:
    oid = params["orchestra"]
    kind = params["_task_kind"]
    if kind == "orchestra_synthesis":
        if not getattr(client, "configured", False):
            raise OrchestraBlocked("No configured model for Alfred")
        tasks = ctx.store.tasks_for(ctx.mission_id)
        reviews = [t for t in tasks if t["kind"] == "orchestra_review"]
        expected = 4 if oid == "all" else 1
        if len(reviews) != expected or any(t["status"] != "succeeded" for t in reviews):
            raise OrchestraBlocked("Alfred cannot synthesize incomplete captain reports")
        evidence = [(t["result"] or {}).get("evidence") or {} for t in reviews]
        if any(e.get("reports_to") != "Alfred" or e.get("execution") is not False for e in evidence):
            raise OrchestraBlocked("unverified captain report")
        execution_evidence = []
        if params.get("execute"):
            expected_execution = 4 if oid == "all" else 1
            for task in tasks:
                if task["kind"] not in ("build_and_verify", "audit", "research", "lab_validation"):
                    continue
                if not str((task["params"] or {}).get("workdir", "")).startswith("orchestras/"):
                    continue
                if task["status"] != "succeeded":
                    raise OrchestraBlocked("approved execution has not succeeded")
                receipt = (task["result"] or {}).get("receipt")
                if not receipt:
                    raise OrchestraBlocked("approved execution is missing a tool receipt")
                execution_evidence.append({"tool_kind": task["kind"],
                                           "agent": task["agent"],
                                           "receipt_sha256": _digest(receipt)})
            if len(execution_evidence) != expected_execution:
                raise OrchestraBlocked("missing expected approved evidence tasks")
        out, digest = _invoke(ctx, client, "Alfred", 
            "You are central Captain Alfred. Synthesize captain analyses and only the "
            "provided tool receipts, if any. Reports without execution receipts are "
            "analysis-only. Never claim deployment or unrestricted tool execution. "
            "Return JSON with summary and limitations.",
            {"goal": params["goal"], "captains": [{"name": e["captain"],
              "orchestra": e["orchestra"], "receipt": e["model_sha256"]} for e in evidence],
             "approved_tool_receipts": execution_evidence},
            max_tokens=240)
        if not isinstance(out.get("summary"), str) or not out["summary"].strip():
            raise OrchestraBlocked("Alfred summary missing")
        ctx.record("alfred_aggregated_captain_reports", {"captains": len(reviews),
                    "summary_sha256": digest, "execution_receipts": len(execution_evidence)})
        return {"status": "ok", "summary": out["summary"][:1200],
                "evidence": {"captains": [e["captain"] for e in evidence],
                             "orchestras": [e["orchestra"] for e in evidence],
                             "model_sha256": digest, "execution": False,
                             "execution_receipts": execution_evidence}}
    spec = ORCHESTRAS[oid]
    goal = _safe_input(params["goal"], 2000)
    context = _safe_input(params.get("context", ""), 3000)
    scope = _safe_input(params.get("scope", ""), 800)
    payload = {"goal": goal, "context": context,
               "authorized_scope": scope if spec.get("needs_scope") else "not applicable"}
    if spec.get("needs_scope") and len(scope.strip()) < 12:
        raise OrchestraBlocked("security laboratory scope missing")

    if kind == "orchestra_plan":
        roles = [r for _, r, _ in spec["roles"]]
        out, digest = _invoke(ctx, client, spec["captain"],
            f"You are {spec['captain']}, a domain captain reporting to Alfred. "
            "Plan three bounded analytical tasks for your assigned specialist roles only. "
            "Do not fabricate tests, tool execution, files, or source access. "
            "Reply with a compact JSON object {\"instructions\":{}}. "
            "Avoid long explanations; missing instructions use deterministic role focuses.",
            {**payload, "roles": roles, "domain": spec["mission"]})
        proposals = out.get("instructions", {})
        if not isinstance(proposals, dict):
            raise OrchestraBlocked("captain returned invalid instructions")
        instructions = {role: str(proposals.get(role, focus))[:350]
                        for _, role, focus in spec["roles"]}
        return {"status": "ok", "summary": "Captain created bounded specialist assignments",
                "evidence": {"captain": spec["captain"], "orchestra": oid,
                             "instructions": instructions, "model_sha256": digest,
                             "execution": False}}

    if kind == "orchestra_specialist":
        role = params["role"]
        if role not in [r for _, r, _ in spec["roles"]]:
            raise OrchestraBlocked("specialist not a member of this orchestra")
        tasks = ctx.store.tasks_for(ctx.mission_id)
        preceding = next((t for t in tasks if t["kind"] == "orchestra_plan"
                          and (t["params"] or {}).get("orchestra") == oid), None)
        if not preceding or preceding["status"] != "succeeded":
            raise OrchestraBlocked("captain plan not verified in durable store")
        instructions = ((preceding["result"] or {}).get("evidence") or {}).get("instructions", {})
        assignment = str(instructions.get(role, ""))[:350]
        out, digest = _invoke(ctx, client, f"{oid}:{role}",
            f"You are {role}, specialist under {spec['captain']} reporting to Alfred. "
            f"Your responsibility is {params['focus']}. "
            "Reply ONLY with compact JSON: "
            "{\"finding\":\"one short specific observation\","
            "\"next_steps\":[],\"tests\":[],\"limitations\":[]}. "
            "The finding field is mandatory and must not be empty. "
            "Do not claim tests or external tools ran.",
            {**payload, "assignment": assignment}, max_tokens=210)
        finding = out.get("finding")
        if not isinstance(finding, str) or not finding.strip():
            # One independent second attempt; never fabricate a missing finding.
            # Retry is conditional, budgeted, and committed as an audit event.
            ctx.record("specialist_response_rejected", {"role": role, "reason": "missing finding"})
            out, digest = _invoke(ctx, client, f"{oid}:{role}",
                "You are a specialist providing a bounded ANALYSIS, not test results. "
                "You MUST return exactly this JSON shape with a nonempty finding: "
                "{\"finding\":\"short factual analysis\","
                "\"next_steps\":[],\"tests\":[],\"limitations\":[\"not executed\"]}.",
                {"goal": goal[:500], "role": role, "assignment": assignment[:200]}, max_tokens=150)
            finding = out.get("finding")
            if not isinstance(finding, str) or not finding.strip():
                raise OrchestraBlocked("specialist returned no finding after bounded retry")
        def arr(key):
            value = out.get(key, [])
            return [str(x)[:240] for x in value[:5]] if isinstance(value, list) else []
        evidence = {"orchestra": oid, "specialist": role, "captain": spec["captain"],
                    "finding": finding[:1200], "next_steps": arr("next_steps"),
                    "tests_proposed": arr("tests"), "limitations": arr("limitations"),
                    "model_sha256": digest, "execution": False}
        return {"status": "ok", "summary": f"{role} submitted an analytical report",
                "evidence": evidence}

    if kind == "orchestra_review":
        tasks = ctx.store.tasks_for(ctx.mission_id)
        reports = []
        for _, role, _ in spec["roles"]:
            matching = [t for t in tasks if t["kind"] == "orchestra_specialist"
                        and (t["params"] or {}).get("orchestra") == oid
                        and (t["params"] or {}).get("role") == role]
            if len(matching) != 1 or matching[0]["status"] != "succeeded":
                raise OrchestraBlocked("missing successful specialist task: " + role)
            r = (matching[0]["result"] or {}).get("evidence") or {}
            if not r.get("model_sha256") or r.get("execution") is not False:
                raise OrchestraBlocked("unverified or malformed specialist evidence")
            reports.append({"role": role, "finding": str(r.get("finding", ""))[:800],
                            "receipt": r["model_sha256"]})
        out, digest = _invoke(ctx, client, spec["captain"],
            f"You are {spec['captain']} reporting to Alfred. Summarize these three "
            "specialist reports without treating analysis as executed evidence. "
            "Return JSON with summary and limitations. Do not authorize deployments.",
            {"goal": goal, "reports": reports}, max_tokens=700)
        if not isinstance(out.get("summary"), str) or not out["summary"].strip():
            raise OrchestraBlocked("captain review summary missing")
        ctx.record("captain_report_to_alfred", {"captain": spec["captain"], "orchestra": oid,
                                                "specialists": len(reports), "review_sha256": digest})
        return {"status": "ok", "summary": out["summary"][:1000],
                "evidence": {"captain": spec["captain"], "orchestra": oid,
                             "specialist_receipts": reports, "model_sha256": digest,
                             "reports_to": "Alfred", "execution": False}}
    raise OrchestraBlocked("unknown orchestra task kind")
