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
    return plan


def _safe_input(text: str, limit: int) -> str:
    if not isinstance(text, str) or len(text) > limit or "\x00" in text:
        raise OrchestraBlocked("invalid or oversized model input")
    if INJECTION_PATTERN.search(text):
        raise OrchestraBlocked("untrusted instructions blocked before model invocation")
    return text


def _invoke(ctx, client, actor: str, system: str, payload: dict, *, max_tokens=450) -> tuple[dict, str]:
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
    spec = ORCHESTRAS[oid]
    kind = params["_task_kind"]
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
            "Return JSON: {\"instructions\":{\"role\":\"task\"}}.",
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
            f"Your responsibility is {params['focus']}. Return JSON fields finding, "
            "next_steps (array), tests (array), limitations (array). "
            "Only report analytical findings; never claim that a tool or external test ran.",
            {**payload, "assignment": assignment}, max_tokens=650)
        finding = out.get("finding")
        if not isinstance(finding, str) or not finding.strip():
            raise OrchestraBlocked("specialist returned no finding")
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
