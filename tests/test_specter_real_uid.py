"""Real Linux UID separation challenge on a disposable CI runner only.

Runs only when explicitly invoked as root on the ephemeral GitHub runner.
No host users are created. All numeric UIDs are confined to forked subprocesses
that drop privileges before opening any Specter endpoint.
"""
import multiprocessing as mp
import os
import tempfile
import time
from pathlib import Path

import pytest

from gotham.core.audit import AuditReader
from gotham.core.specter_transport import (
    SpecterRecordServer, SpecterVerifyServer, SpecterWriteClient, SpecterReadClient
)

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0 or not hasattr(os, "setuid"),
    reason="requires explicit sudo in a disposable Linux CI runner"
)
AUDITOR = 43101
WORKER = 43102
BATMAN = 43103
ROGUE = 43104


def _drop(uid):
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)


def _auditor(record, verify, journal, ready, stop):
    _drop(AUDITOR)
    rec = SpecterRecordServer(record, journal, allowed_uids={WORKER})
    # Rootless canary explicitly grants verifier-socket group access only to Batman.
    # The default 0600 remains secure for same-UID and unprovisioned deployments.
    ver = SpecterVerifyServer(verify, journal, allowed_uids={BATMAN}, mode=0o660)
    import threading
    rt = threading.Thread(target=rec.serve_forever, daemon=True)
    vt = threading.Thread(target=ver.serve_forever, daemon=True)
    rt.start()
    vt.start()
    ready.set()
    try:
        stop.wait(15)
    finally:
        ver.shutdown()
        rec.shutdown()
        ver.server_close()
        rec.server_close()


def _client(uid, record, verify, journal, queue):
    _drop(uid)
    result = {"uid": uid}
    try:
        if uid == WORKER:
            result["write"] = len(SpecterWriteClient(record).record(
                "a" * 32, "task", "Alfred", "pre_model_gate",
                {"input_sha256": "b" * 64}
            )) == 64
            try:
                SpecterReadClient(verify).verify()
                result["read_denied"] = False
            except Exception:
                result["read_denied"] = True
            try:
                Path(journal).read_bytes()
                result["journal_denied"] = False
            except PermissionError:
                result["journal_denied"] = True
        elif uid == BATMAN:
            result["verify"] = SpecterReadClient(verify).verify()["valid"]
            try:
                SpecterWriteClient(record).record(None, None, "Batman", "forged", {})
                result["write_denied"] = False
            except Exception:
                result["write_denied"] = True
        else:
            try:
                SpecterWriteClient(record).record(None, None, "Rogue", "forged", {})
                result["write_denied"] = False
            except Exception:
                result["write_denied"] = True
            try:
                SpecterReadClient(verify).verify()
                result["read_denied"] = False
            except Exception:
                result["read_denied"] = True
    except Exception as e:
        result["unexpected"] = type(e).__name__ + ":" + str(e)[:100]
    queue.put(result)


def test_distinct_linux_uid_auditor_worker_batman_and_rogue():
    ctx = mp.get_context("fork")
    with tempfile.TemporaryDirectory(prefix="gotham-specter-real-uid-", dir="/tmp") as directory:
        base = Path(directory)
        os.chown(base, AUDITOR, AUDITOR)
        os.chmod(base, 0o711)
        record_dir = base / "record"
        verify_dir = base / "verify"
        private_dir = base / "journal"
        for path, gid, mode in (
            (record_dir, WORKER, 0o2710),
            (verify_dir, BATMAN, 0o2710),
            (private_dir, AUDITOR, 0o700),
        ):
            path.mkdir()
            os.chown(path, AUDITOR, gid)
            os.chmod(path, mode)
        record = str(record_dir / "audit.sock")
        verify = str(verify_dir / "audit.sock")
        journal = str(private_dir / "specter.sqlite3")
        ready, stop = ctx.Event(), ctx.Event()
        server = ctx.Process(target=_auditor, args=(record, verify, journal, ready, stop))
        server.start()
        try:
            assert ready.wait(timeout=8), "auditor never reached ready state"
            assert server.is_alive(), "auditor exited before test clients"
            queue = ctx.Queue()
            worker = ctx.Process(target=_client, args=(WORKER, record, verify, journal, queue))
            worker.start()
            worker.join(timeout=6)
            assert worker.exitcode == 0
            wr = queue.get(timeout=2)
            assert wr.get("write") and wr.get("read_denied") and wr.get("journal_denied"), wr
            batman = ctx.Process(target=_client, args=(BATMAN, record, verify, journal, queue))
            batman.start()
            batman.join(timeout=6)
            assert batman.exitcode == 0
            br = queue.get(timeout=2)
            assert br.get("verify") and br.get("write_denied"), br
            rogue = ctx.Process(target=_client, args=(ROGUE, record, verify, journal, queue))
            rogue.start()
            rogue.join(timeout=6)
            assert rogue.exitcode == 0
            rr = queue.get(timeout=2)
            assert rr.get("read_denied") and rr.get("write_denied"), rr
            integrity = AuditReader(journal).verify()
            assert integrity["valid"] and integrity["checked"] == 1
        finally:
            stop.set()
            server.join(timeout=6)
            if server.is_alive():
                server.terminate()
                server.join(timeout=3)
            assert not server.is_alive(), "auditor process failed to terminate"
