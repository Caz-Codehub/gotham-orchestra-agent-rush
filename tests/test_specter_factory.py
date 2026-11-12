"""Opt-in Specter IPC integration is fail-closed without changing default staging."""
import os
import threading

import pytest

from gotham.core.audit import AuditReader, audit_reader, audit_writer
from gotham.core.engine import Alfred
from gotham.core.store import Store
from gotham.core.specter_transport import (
    SpecterRecordServer, SpecterTransportError, SpecterVerifyServer,
)
from tests.conftest import run_until_done
from tests.test_orchestra_durable import FakeModel


@pytest.fixture
def isolated_journal(tmp_path, monkeypatch):
    private = tmp_path / "private" / "specter.sqlite3"
    writer_socket = tmp_path / "record.sock"
    reader_socket = tmp_path / "verify.sock"
    server = SpecterRecordServer(writer_socket, private, allowed_uids={os.getuid()})
    reader = SpecterVerifyServer(reader_socket, private, allowed_uids={os.getuid()})
    wthread = threading.Thread(target=server.serve_forever,
                               kwargs={"poll_interval": 0.01}, daemon=True)
    rthread = threading.Thread(target=reader.serve_forever,
                               kwargs={"poll_interval": 0.01}, daemon=True)
    wthread.start()
    rthread.start()
    monkeypatch.setenv("GOTHAM_SPECTER_RECORD_SOCKET", str(writer_socket))
    monkeypatch.setenv("GOTHAM_SPECTER_VERIFY_SOCKET", str(reader_socket))
    monkeypatch.setenv("GOTHAM_REQUIRE_INDEPENDENT_SPECTER", "1")
    try:
        yield private
    finally:
        reader.shutdown()
        server.shutdown()
        reader.server_close()
        server.server_close()
        wthread.join(timeout=2)
        rthread.join(timeout=2)


def test_full_bounded_orchestra_uses_socket_writer_and_batman_reader(isolated_journal, env):
    model = FakeModel()
    engine = Alfred(store=Store(env / "data" / "mission.sqlite3"), client=model)
    assert type(engine.audit).__name__ == "SpecterWriteClient"
    mid = engine.submit("orchestra", "Analyze one synthetic software fixture",
                        {"orchestra": "software"}, "operator:test")
    run_until_done(engine, concurrency=1)
    mission = engine.store.get_mission(mid)
    assert mission["status"] == "completed_unverified", mission["result"]
    report = audit_reader(isolated_journal).verify()
    assert report["valid"] is True and report["checked"] > 0
    assert len(audit_reader(isolated_journal).events(mid)) > 0
    assert model.calls == 6
    assert not hasattr(engine.audit, "verify")
    assert AuditReader(isolated_journal).verify()["head"] == report["head"]


def test_strict_mode_missing_writer_socket_does_not_fallback_to_disk(env, monkeypatch):
    monkeypatch.setenv("GOTHAM_REQUIRE_INDEPENDENT_SPECTER", "1")
    monkeypatch.delenv("GOTHAM_SPECTER_RECORD_SOCKET", raising=False)
    with pytest.raises(RuntimeError, match="no record socket"):
        audit_writer(env / "audit" / "local.sqlite3")
    assert not (env / "audit" / "local.sqlite3").exists()


def test_record_mode_without_batman_reader_is_denied(env, monkeypatch):
    monkeypatch.setenv("GOTHAM_SPECTER_RECORD_SOCKET", "/tmp/owned-audit-socket")
    monkeypatch.delenv("GOTHAM_SPECTER_VERIFY_SOCKET", raising=False)
    with pytest.raises(RuntimeError, match="reader required"):
        audit_reader(env / "audit" / "local.sqlite3")


def test_socket_failure_refuses_mission_before_model_work(env, monkeypatch):
    monkeypatch.setenv("GOTHAM_SPECTER_RECORD_SOCKET", str(env / "missing.sock"))
    monkeypatch.setenv("GOTHAM_REQUIRE_INDEPENDENT_SPECTER", "1")
    model = FakeModel()
    engine = Alfred(store=Store(env / "data" / "blocked.sqlite3"), client=model)
    with pytest.raises(SpecterTransportError, match="unavailable"):
        engine.submit("orchestra", "Analyze a disposable bounded synthetic fixture",
                      {"orchestra": "software"}, "operator:test")
    assert model.calls == 0
