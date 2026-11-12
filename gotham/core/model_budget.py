"""Durable, fail-closed per-mission inference allowance for orchestral model calls.

Every retry counts. A long-running worker must not share one lifetime
counter between unrelated missions. Reservations persist in the SQLite
mission ledger, so process restarts cannot reset a mission's allowance.
"""
from __future__ import annotations

import os

from ..inference import InferenceError


def mission_call_limit() -> int:
    raw = os.environ.get("GOTHAM_ORCHESTRA_MISSION_CALL_LIMIT", "48")
    try:
        count = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid orchestra mission-call limit") from exc
    if not 21 <= count <= 64:
        raise ValueError("orchestra mission-call limit must be 21–64")
    return count


class MissionModelClient:
    """Thin adapter over real or fixture inference; mission quota is atomic."""

    def __init__(self, *, mission_id, delegate, store, audit, limit=None):
        self.mission_id = mission_id
        self.delegate = delegate
        self.store = store
        self.audit = audit
        self.limit = mission_call_limit() if limit is None else limit
        if not isinstance(self.limit, int) or not 21 <= self.limit <= 64:
            raise ValueError("invalid mission-call limit")

    @property
    def configured(self):
        return bool(getattr(self.delegate, "configured", False))

    @property
    def provider_name(self):
        return getattr(self.delegate, "provider_name", "unknown")

    @property
    def model(self):
        return getattr(self.delegate, "model", "")

    def json(self, system: str, user: str, *, max_tokens: int = 450):
        if not self.configured:
            raise InferenceError("No configured local model; inference refused")
        permitted, ordinal = self.store.reserve_model_call(self.mission_id, self.limit)
        if not permitted:
            raise InferenceError("Mission model-call budget exhausted; no further calls issued")
        # Audit write must succeed before inference transport. Do not log prompts.
        self.audit.record(self.mission_id, None, "Alfred", "mission_model_call_reserved",
                          {"ordinal": ordinal, "limit": self.limit,
                           "provider": str(self.provider_name)[:50]})
        return self.delegate.json(system, user, max_tokens=max_tokens)
