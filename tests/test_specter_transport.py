"""Specter process-boundary transport tests (no production secrets or root needed)."""
import concurrent.futures
import json
import os
import socket
import threading

import pytest

from gotham.core.audit import AuditReader
from gotham.core.specter_transport import (
    SpecterRecordServer, SpecterTransportError, SpecterWriteClient,
)


@pytest.fixture()
def sidecar(tmp_path):
    sock = tmp_path / "audit.sock"
    journal = tmp_path / "private" / "specter.sqlite3"
    server = SpecterRecordServer(sock, journal, allowed_uids={os.getuid()})
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server, SpecterWriteClient(sock), journal
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_record_only_client_commits_and_verifies_through_independent_journal(sidecar):
    server, client, journal = sidecar
    digest = client.record("mission-one", "task-one", "Alfred", "pre_model_gate",
                           {"input_sha256": "a" * 64, "permitted": True})
    assert len(digest) == 64
    assert not hasattr(client, "verify")
    assert not hasattr(client, "events")
    assert not hasattr(client, "_key")
    report = AuditReader(journal).verify()
    assert report["valid"] and report["checked"] == 1 and report["head"] == digest


def test_no_auditor_socket_never_falls_back_to_local_journal(tmp_path):
    client = SpecterWriteClient(tmp_path / "unavailable.sock", timeout=0.1)
    with pytest.raises(SpecterTransportError, match="unavailable"):
        client.record(None, None, "Alfred", "pre_model_gate", {"input": "synthetic"})


def test_peer_uid_is_enforced_before_appending(tmp_path):
    sock = tmp_path / "audit.sock"
    journal = tmp_path / "audit" / "private.sqlite3"
    server = SpecterRecordServer(sock, journal, allowed_uids={os.getuid() + 10000})
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        with pytest.raises(SpecterTransportError, match="refused"):
            SpecterWriteClient(sock).record(None, None, "Alfred", "pre_model_gate", {})
        assert AuditReader(journal).verify()["checked"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_no_read_or_verify_methods_on_socket(sidecar):
    server, client, journal = sidecar
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(2)
        s.connect(str(server.server_address))
        s.sendall((json.dumps({"op": "verify"}) + "\n").encode())
        reply = json.loads(s.makefile().readline())
    assert reply == {"ok": False, "error": "denied"}
    assert AuditReader(journal).verify()["checked"] == 0


def test_concurrent_audit_writes_keep_one_valid_chain(sidecar):
    _, client, journal = sidecar

    def send(i):
        return client.record("mission", str(i), "Orchestra", "pre_model_gate",
                             {"ordinal": i, "reason": "fixture"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        digests = list(pool.map(send, range(24)))
    assert len(set(digests)) == 24
    assert AuditReader(journal).verify()["checked"] == 24


def test_auditor_write_failure_refuses_acknowledgment(sidecar):
    server, client, journal = sidecar

    class BrokenWriter:
        def record(self, *args, **kwargs):
            raise OSError("disk unavailable")

    server.writer = BrokenWriter()
    with pytest.raises(SpecterTransportError, match="refused"):
        client.record(None, None, "Alfred", "pre_model_gate", {"hash": "b" * 64})
    assert AuditReader(journal).verify()["checked"] == 0


@pytest.mark.parametrize("sensitive", [
    {"raw_prompt": "do not persist this content"},
    {"nested": [{"authorization": "Bearer synthetic-credential"}]},
    {"system_prompt": "You are a specialist with private instructions"},
    {"api_key": "sk-proj-synthetic-do-not-log"},
])
def test_auditor_rejects_raw_prompts_and_credentials_before_journaling(sidecar, sensitive):
    _, client, journal = sidecar
    with pytest.raises(SpecterTransportError, match="disallowed"):
        client.record("mission", "task", "Alfred", "pre_model_gate", sensitive)
    assert AuditReader(journal).verify()["checked"] == 0
