"""Clocked security gateway for Gotham's Alfred -> worker pipeline.

This is a *preflight* component. It does not run scripts, send network requests
on behalf of a worker, or bypass Gotham's existing authentication.
Set CLOCKED_API_KEY server-side and install clocked-sdk>=0.7,<1.

IMPORTANT: Make the call before passing untrusted input to any agent or running
an agent-supplied script. A missing key, API error, or ambiguous verdict blocks.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, asdict
from typing import Any, Optional

SAFE_SCRIPT_VERDICTS = {"safe", "benign", "allow", "allowed", "clean"}
BAD_INJECTION_VERDICTS = {"injection", "malicious", "unsafe", "block", "blocked", "high", "critical"}
CLEAN_INJECTION_VERDICTS = {"clean", "safe", "benign", "allow", "allowed", "none"}


@dataclass
class GateReceipt:
    allowed: bool
    status: str
    reason: str
    sanitized_text: Optional[str]
    checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _injection_clear(result: dict[str, Any]) -> bool:
    # Trust only unambiguously clean responses, never missing/unknown fields.
    flagged = result.get("injection")
    if flagged is True:
        return False
    verdict = str(result.get("verdict", "")).lower()
    if verdict in BAD_INJECTION_VERDICTS:
        return False
    return flagged is False or verdict in CLEAN_INJECTION_VERDICTS


def _script_clear(result: dict[str, Any]) -> bool:
    return str(result.get("verdict", "")).lower() in SAFE_SCRIPT_VERDICTS


def preflight(
    text: str,
    *,
    script: Optional[str] = None,
    source: str = "tool",
    client: Any = None,
) -> GateReceipt:
    """Inspect untrusted text, redact PII, and inspect optional scripts.

    A successfully sanitized response is returned as sanitized_text. The caller
    MUST use that text instead of raw input. Never treat an 'allowed' receipt
    as permission to exceed the human mission scope; normal Gotham approvals
    and sandbox controls must still apply.

    `client` supports injecting a fake Clocked client into unit tests.
    """
    if not isinstance(text, str) or not text.strip():
        return GateReceipt(False, "block", "empty_input", None, {})
    if len(text) > 100_000 or (script is not None and len(script) > 100_000):
        return GateReceipt(False, "block", "input_too_large", None, {})
    if client is None and not os.getenv("CLOCKED_API_KEY"):
        return GateReceipt(False, "block", "clocked_not_configured", None, {})
    checks: dict[str, Any] = {}
    try:
        if client is None:
            from clocked_sdk import Clocked
            client = Clocked()
        injection = dict(client.injection(text=text, source=source, evidence=True))
        checks["guard"] = {"verdict": injection.get("verdict"),
                           "injection": injection.get("injection")}
        if not _injection_clear(injection):
            return GateReceipt(False, "block", "guard_not_cleared", None, checks)
        pii = dict(client.pii(text=text,
                              entities=["person", "email", "phone", "username"],
                              threshold=0.5, anonymize="replace"))
        sanitized = pii.get("anonymized_text")
        checks["protect"] = {"redacted": isinstance(sanitized, str) and sanitized != text}
        if not isinstance(sanitized, str):
            return GateReceipt(False, "block", "pii_missing_sanitized_text", None, checks)
        if script is not None:
            inspection = dict(client.script(script=script, threshold=0.3, evidence=True))
            checks["inspect"] = {"verdict": inspection.get("verdict")}
            if not _script_clear(inspection):
                return GateReceipt(False, "block", "script_not_cleared", sanitized, checks)
        return GateReceipt(True, "allow", "clocked_preflight_cleared", sanitized, checks)
    except Exception as error:
        # Never leak provider exception details, keys, or unredacted input.
        checks["provider_error_type"] = type(error).__name__
        return GateReceipt(False, "block", "clocked_unavailable", None, checks)
