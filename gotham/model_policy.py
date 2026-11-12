"""Fail-closed, deterministic pre-model input screening for every inference provider.

Not a substitute for a dedicated policy service, but the transport can never
send the obvious credential/injection patterns below without a decision. This
module knows only sanitized text, not audit secrets, database paths or API keys.
"""
from __future__ import annotations
import re

class ModelInputDenied(ValueError):
    pass

# Prevent obvious instruction overriding, tool-result laundering, and keys
# before data is submitted to any local or remote language model.
DENIED_INSTRUCTIONS = re.compile(
    r"(?i)(?:ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+(?:instructions|rules)|"
    r"disregard\s+.{0,50}(?:system\s+prompt|instructions|rules)|"
    r"reveal\s+.{0,60}(?:private\s+key|api\s+key|credentials|secret\s+token)|"
    r"exfiltrate\s+.{0,50}(?:credential|token|secret|key)|"
    r"you\s+are\s+now\s+the\s+system)"
)
PEM = re.compile(r"-----BEGIN\s+(?:OPENSSH|RSA|EC|DSA|[A-Z ]+)\s+PRIVATE\s+KEY-----", re.I)
CREDENTIAL = re.compile(r"(?i)\b(?:sk-proj-|ghp_|gho_|ghs_|xoxb-)[A-Za-z0-9_-]{16,}")
EMAIL = re.compile(r"(?<![A-Za-z0-9_.+-])[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PRIVATE_AUDITOR = re.compile(r"(?i)\bspecter\b")

def screen(system: str, user: str) -> tuple[str, str, dict]:
    if not isinstance(system, str) or not isinstance(user, str):
        raise ModelInputDenied("model input must be text")
    if len(system) > 5000 or len(user) > 15000 or "\x00" in user + system:
        raise ModelInputDenied("model input rejected due to size or NUL")
    if PRIVATE_AUDITOR.search(system):
        raise ModelInputDenied("private auditor identity in model system prompt")
    if PEM.search(user) or PEM.search(system) or CREDENTIAL.search(user) or CREDENTIAL.search(system):
        raise ModelInputDenied("credential-like material blocked before inference")
    if DENIED_INSTRUCTIONS.search(user):
        raise ModelInputDenied("untrusted instruction override blocked before inference")
    protected = PRIVATE_AUDITOR.sub("[PRIVATE_AUDIT_COMPONENT]", user)
    protected, emails = EMAIL.subn("[REDACTED_EMAIL]", protected)
    return system, protected, {"email_addresses_redacted": emails,
                               "private_auditor_references_redacted": len(PRIVATE_AUDITOR.findall(user)),
                               "input_screened": True}
