"""Separate auditor verification socket: peer UID and read-only response tests."""
import json
import os
import socket
import threading

import pytest

from gotham.core.specter_transport import (
    SpecterReadClient, SpecterRecordServer, SpecterTransportError,
    SpecterVerifyServer, SpecterWriteClient,
)


@pytest.fixture
def verifier(tmp_path):
    journal = tmp_path / "private" / "specter.sqlite3"
    record_path = tmp_path / "record.sock"
    verify_path = tmp_path / "verify.sock"
    record = SpecterRecordServer(record_path, journal, allowed_uids={os.getuid()})
    rt = threading.Thread(target=record.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    rt.start()
    verify = SpecterVerifyServer(verify_path, journal, allowed_uids={os.getuid()})
    vt = threading.Thread(target=verify.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    vt.start()
    try:
        yield SpecterWriteClient(record_path), SpecterReadClient(verify_path), journal, verify_path
    finally:
        verify.shutdown()
        verify.server_close()
        record.shutdown()
        record.server_close()
        rt.join(timeout=2)
        vt.join(timeout=2)


def test_separate_reader_proves_chain_without_exposing_events_or_key(verifier):
    writer, reader, _, _ = verifier
    digest = writer.record("mission", "task", "Alfred", "pre_model_gate",
                           {"private_input": "synthetic-value"})
    assert not hasattr(reader, "record")
    report = reader.verify()
    assert report["valid"] is True
    assert report["head"] == digest
    assert report["checked"] == 1
    assert "synthetic-value" not in json.dumps(report)
    assert "_key" not in json.dumps(report)


def test_unknown_mutation_request_denied_on_reader_socket(verifier):
    _, reader, _, path = verifier
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        s.connect(str(path))
        s.sendall(b'{"op":"delete"}\n')
        response = json.loads(s.makefile().readline())
    assert response == {"error": "denied", "ok": False}


def test_verifier_rejects_unauthorized_peer_uid(tmp_path):
    journal = tmp_path / "private" / "audit.sqlite3"
    record_path = tmp_path / "record.sock"
    verify_path = tmp_path / "verify.sock"
    record = SpecterRecordServer(record_path, journal, allowed_uids={os.getuid()})
    verify = SpecterVerifyServer(verify_path, journal, allowed_uids={os.getuid() + 10000})
    thread = threading.Thread(target=verify.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        with pytest.raises(SpecterTransportError, match="denied"):
            SpecterReadClient(verify_path).verify()
    finally:
        verify.shutdown()
        verify.server_close()
        record.server_close()
        thread.join(timeout=2)


def test_missing_private_journal_is_never_reported_healthy(tmp_path):
    with pytest.raises(SpecterTransportError, match="existing verified Specter journal"):
        SpecterVerifyServer(tmp_path / "verify.sock",
                            tmp_path / "journal" / "does-not-exist.sqlite3",
                            allowed_uids={os.getuid()})


def test_batman_can_page_scoped_events_and_get_mission_report(verifier):
    writer, reader, _, _ = verifier
    mid = "a" * 32
    for i in range(5):
        writer.record(mid, f"task-{i}", "Alfred", "task_started", {"ordinal": i})
    page1 = reader.events(mid, limit=2)
    assert len(page1) == 2
    assert all(e["mission_id"] == mid for e in page1)
    page2 = reader.events(mid, limit=2, after_seq=page1[-1]["seq"])
    assert len(page2) == 2
    assert [e["seq"] for e in page1 + page2] == sorted(e["seq"] for e in page1 + page2)
    report = reader.report(mid)
    assert report["mission_id"] == mid
    assert report["integrity"]["valid"] is True
    assert report["event_count"] == 5
    assert report["actors"] == ["Alfred"]


def test_reader_rejects_missing_or_invalid_mission_scope(verifier):
    _, reader, _, _ = verifier
    with pytest.raises(SpecterTransportError, match="invalid mission"):
        reader.report("../private")
    with pytest.raises(SpecterTransportError, match="invalid mission"):
        reader.events("../private")
    with pytest.raises(SpecterTransportError, match="invalid event page"):
        reader.events("a" * 32, limit=1001)
