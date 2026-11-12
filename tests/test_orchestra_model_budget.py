"""Regression tests for persistent orchestral inference budgets.

The original failure was a single daemon-lifetime max_calls counter:
a completed mission exhausted the provider client and the next mission
could not make its first model call. Real stage acceptance must never be
replaced by fixtures; these only prove local lifecycle and quota isolation.
"""
import concurrent.futures

import pytest

from gotham.core.audit import AuditWriter
from gotham.core.engine import Alfred
from gotham.core.model_budget import MissionModelClient
from gotham.core.orchestra_worker import run
from gotham.core.store import Store
from gotham.inference import InferenceError
from tests.test_orchestra_durable import FakeModel


class BoundedFixture(FakeModel):
    """Mimic the provider's fixed client-lifetime budget, without network."""
    def __init__(self, max_calls=48):
        super().__init__()
        self.max_calls = max_calls

    def json(self, system, user, *, max_tokens=450):
        if self.calls >= self.max_calls:
            raise InferenceError("Model-call budget exhausted. No further calls issued.")
        return super().json(system, user, max_tokens=max_tokens)


def _environment(env, suffix):
    return Alfred(store=Store(env / "data" / (suffix + ".sqlite3")),
                  audit=AuditWriter(env / "audit" / (suffix + ".sqlite3")))


def test_two_consecutive_four_orchestra_missions_get_separate_model_clients(env):
    engine = _environment(env, "consecutive")
    first = engine.submit("orchestra", "Analyze one synthetic four-domain example",
                          {"orchestra": "all", "scope": "Owned offline disposable security training laboratory"},
                          "operator:test")
    second = engine.submit("orchestra", "Analyze another synthetic four-domain example",
                           {"orchestra": "all", "scope": "Owned offline disposable security training laboratory"},
                           "operator:test")
    created = []

    def factory():
        client = BoundedFixture(max_calls=48)
        created.append(client)
        return client

    run(once=True, engine=engine, client_factory=factory)
    for mid in (first, second):
        mission = engine.store.get_mission(mid)
        assert mission["status"] == "completed_unverified", mission["result"]
        assert mission["result"]["verified"] is False
        counts = engine.store.usage_totals(mid)["orchestra_model_call_reserved"]
        assert counts["events"] == 21
        assert counts["total"] == 21
    assert len(created) == 2
    assert sorted(client.calls for client in created) == [21, 21]


def test_durable_reservations_survive_new_wrapper_and_new_model_client(env):
    engine = _environment(env, "restart")
    mid = engine.submit("orchestra", "Analyze a bounded software fixture",
                        {"orchestra": "software"}, "operator:test")
    model = BoundedFixture()
    first = MissionModelClient(mission_id=mid, delegate=model, store=engine.store,
                               audit=engine.audit, limit=21)
    for _ in range(10):
        first.json("You are a specialist under an orchestra captain", "synthetic input")
    fresh = MissionModelClient(mission_id=mid, delegate=BoundedFixture(),
                               store=engine.store, audit=engine.audit, limit=21)
    for _ in range(11):
        fresh.json("You are a specialist under an orchestra captain", "synthetic input")
    with pytest.raises(InferenceError, match="Mission model-call budget exhausted"):
        fresh.json("You are a specialist under an orchestra captain", "synthetic input")
    assert engine.store.usage_totals(mid)["orchestra_model_call_reserved"]["events"] == 21


def test_concurrent_budget_reservations_cannot_race_past_cap(env):
    engine = _environment(env, "concurrent")
    mid = engine.submit("orchestra", "Analyze a bounded software fixture",
                        {"orchestra": "software"}, "operator:test")

    def reserve(_):
        return engine.store.reserve_model_call(mid, 21)[0]

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        result = list(pool.map(reserve, range(50)))
    assert result.count(True) == 21
    assert result.count(False) == 29
    assert engine.store.usage_totals(mid)["orchestra_model_call_reserved"]["total"] == 21


def test_unavailable_audit_never_calls_model(env):
    engine = _environment(env, "audit_failure")
    mid = engine.submit("orchestra", "Analyze a bounded software fixture",
                        {"orchestra": "software"}, "operator:test")

    class BrokenAudit:
        def record(self, *args, **kwargs):
            raise OSError("audit sink unavailable")

    model = BoundedFixture()
    wrapped = MissionModelClient(mission_id=mid, delegate=model,
                                 store=engine.store, audit=BrokenAudit(), limit=21)
    with pytest.raises(OSError, match="audit sink unavailable"):
        wrapped.json("You are a specialist under an orchestra captain", "synthetic input")
    assert model.calls == 0
    # Conservative budget accounting: a failed audited attempt is not refunded.
    assert engine.store.usage_totals(mid)["orchestra_model_call_reserved"]["events"] == 1
