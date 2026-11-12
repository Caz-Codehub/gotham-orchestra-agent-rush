"""Specter write-only Unix-socket transport for future separated-UID deployment.

The worker has no audit key, SQL journal handle or read API. The dedicated
server holds AuditWriter and checks OS peer credentials before appending. This
does not by itself establish OS isolation until separately deployed under an
independent UID with appropriate socket/group and journal permissions.
"""
from __future__ import annotations

import json
import os
import re
import socket
import socketserver
import struct
import threading
from pathlib import Path

from .audit import AuditWriter, AuditReader

MAX_RECORD_BYTES = 32768
HASH = re.compile(r"^[0-9a-f]{64}$")


class SpecterTransportError(RuntimeError):
    """A missing/denied/invalid audit transport must block model or tool calls."""


class SpecterWriteClient:
    """Record-only writer; intentionally has no read, verify or key methods."""

    def __init__(self, path: str | Path, *, timeout=4.0):
        self.socket_path = str(path)
        self.timeout = float(timeout)

    def record(self, mission_id, task_id, actor, action, detail=None) -> str:
        if not isinstance(actor, str) or not isinstance(action, str):
            raise SpecterTransportError("invalid auditor event identifiers")
        if not 1 <= len(actor) <= 128 or not 1 <= len(action) <= 128:
            raise SpecterTransportError("auditor event identifiers exceed policy")
        msg = {"op": "record", "mission_id": mission_id, "task_id": task_id,
               "actor": actor, "action": action, "detail": detail or {}}
        try:
            raw = (json.dumps(msg, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
            if len(raw) > MAX_RECORD_BYTES:
                raise SpecterTransportError("audit metadata exceeds size limit")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(raw)
                received = bytearray()
                while len(received) <= 4096:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    received += chunk
                    if b"\n" in received:
                        break
            if b"\n" not in received or len(received) > 4096:
                raise SpecterTransportError("missing valid auditor acknowledgment")
            reply = json.loads(received.split(b"\n", 1)[0])
            if reply.get("ok") is not True or not HASH.fullmatch(str(reply.get("hash", ""))):
                raise SpecterTransportError("auditor refused the event")
            return reply["hash"]
        except (OSError, ValueError, UnicodeError, TypeError, json.JSONDecodeError) as exc:
            raise SpecterTransportError("audit transport unavailable") from exc


class _RecordHandler(socketserver.StreamRequestHandler):
    def handle(self):
        parent = self.server
        try:
            raw_peer = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            pid, uid, gid = struct.unpack("3i", raw_peer)
            if uid not in parent.allowed_uids:
                raise SpecterTransportError("unapproved peer UID")
            raw = self.rfile.readline(MAX_RECORD_BYTES + 1)
            if not raw.endswith(b"\n") or len(raw) > MAX_RECORD_BYTES:
                raise SpecterTransportError("invalid event size")
            d = json.loads(raw)
            if not isinstance(d, dict) or set(d) != {
                "op", "mission_id", "task_id", "actor", "action", "detail"
            } or d["op"] != "record":
                raise SpecterTransportError("record-only transport")
            if not isinstance(d["actor"], str) or not isinstance(d["action"], str):
                raise SpecterTransportError("invalid metadata")
            if not 1 <= len(d["actor"]) <= 128 or not 1 <= len(d["action"]) <= 128:
                raise SpecterTransportError("invalid event identifiers")
            if not isinstance(d["detail"], dict):
                raise SpecterTransportError("audit detail must be a JSON object")
            # Use a single journal writer and serialize the short append transaction.
            with parent.write_gate:
                digest = parent.writer.record(d["mission_id"], d["task_id"],
                                              d["actor"], d["action"], d["detail"])
            reply = {"ok": True, "hash": digest}
        except Exception:
            reply = {"ok": False, "error": "denied"}
        try:
            self.wfile.write((json.dumps(reply) + "\n").encode("utf-8"))
            self.wfile.flush()
        except OSError:
            pass


class SpecterRecordServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, socket_path: str | Path, journal_path: str | Path, *,
                 allowed_uids: set[int], mode: int = 0o660):
        if not allowed_uids or any(not isinstance(x, int) or x < 0 for x in allowed_uids):
            raise ValueError("explicit allowed peer UIDs are required")
        path = Path(socket_path)
        if not path.parent.is_dir():
            raise ValueError("pre-provisioned socket directory required")
        if path.exists():
            raise SpecterTransportError("socket path exists: refusing to replace an active auditor")
        self.allowed_uids = frozenset(allowed_uids)
        self.write_gate = threading.Lock()
        self.writer = AuditWriter(journal_path)
        super().__init__(str(path), _RecordHandler)
        try:
            os.chmod(path, mode)
        except Exception:
            self.server_close()
            raise

    def server_close(self):
        name = self.server_address
        super().server_close()
        try:
            Path(name).unlink(missing_ok=True)
        except OSError:
            pass


# Batman verification is provided on a SEPARATE socket under a SEPARATE
# process identity. Operators and model workers must not be allowed UIDs.
class SpecterReadClient:
    """Verify-only client: cannot submit, amend, remove or rewrite audit events."""

    def __init__(self, path: str | Path, *, timeout=4.0):
        self.socket_path = str(path)
        self.timeout = float(timeout)

    def verify(self):
        raw = b'{"op":"verify"}\n'
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(raw)
                buf = bytearray()
                while len(buf) <= 4096:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in buf:
                        break
            if b"\n" not in buf or len(buf) > 4096:
                raise SpecterTransportError("invalid auditor verification response")
            result = json.loads(buf.split(b"\n", 1)[0])
            if result.get("ok") is not True:
                raise SpecterTransportError("Batman verification denied")
            report = result.get("report")
            if not isinstance(report, dict) or not isinstance(report.get("valid"), bool):
                raise SpecterTransportError("auditor returned invalid verification report")
            return report
        except (OSError, ValueError, TypeError) as exc:
            raise SpecterTransportError("Batman auditor verification unavailable") from exc


class _VerifyHandler(socketserver.StreamRequestHandler):
    def handle(self):
        parent = self.server
        try:
            raw_peer = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            _, uid, _ = struct.unpack("3i", raw_peer)
            if uid not in parent.allowed_uids:
                raise SpecterTransportError("unapproved verification peer")
            raw = self.rfile.readline(4097)
            if len(raw) > 4096 or not raw.endswith(b"\n"):
                raise SpecterTransportError("invalid verification request")
            query = json.loads(raw)
            if query != {"op": "verify"}:
                raise SpecterTransportError("verify-only auditor interface")
            report = parent.reader.verify()
            result = {"ok": True, "report": report}
        except Exception:
            result = {"ok": False, "error": "denied"}
        try:
            self.wfile.write((json.dumps(result, sort_keys=True) + "\n").encode())
            self.wfile.flush()
        except OSError:
            pass


class SpecterVerifyServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Owner-only audit verification server; no event bodies or HMAC key returned."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, socket_path: str | Path, journal_path: str | Path, *,
                 allowed_uids: set[int], mode: int = 0o600):
        if not allowed_uids or any(not isinstance(x, int) or x < 0 for x in allowed_uids):
            raise ValueError("explicit Batman API peer UID allowlist required")
        path = Path(socket_path)
        journal = Path(journal_path)
        if not path.parent.is_dir():
            raise ValueError("pre-provisioned verifier socket directory required")
        if path.exists():
            raise SpecterTransportError("verifier socket already exists")
        # A missing journal must not be silently treated as a healthy empty chain.
        if not journal.is_file() or not journal.with_suffix(".key").is_file():
            raise SpecterTransportError("existing verified Specter journal and key required")
        self.allowed_uids = frozenset(allowed_uids)
        self.reader = AuditReader(journal)
        super().__init__(str(path), _VerifyHandler)
        try:
            os.chmod(path, mode)
        except Exception:
            self.server_close()
            raise

    def server_close(self):
        path = self.server_address
        super().server_close()
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
