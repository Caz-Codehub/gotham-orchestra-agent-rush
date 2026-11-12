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

# Never accept entire prompts, token values or raw secrets as audit metadata.
# Credential-shaped values are additionally redacted by AuditWriter.
PROHIBITED_METADATA_KEYS = frozenset({
    "system_prompt", "user_prompt", "raw_prompt", "full_prompt",
    "raw_input", "api_key", "private_key", "password",
    "authorization", "bearer_token", "access_token", "secret_token",
})


def _safe_metadata_tree(obj, depth=0) -> bool:
    if depth > 8:
        return False
    if isinstance(obj, dict):
        return len(obj) <= 80 and all(
            isinstance(k, str) and k.lower() not in PROHIBITED_METADATA_KEYS
            and len(k) <= 128 and _safe_metadata_tree(v, depth + 1)
            for k, v in obj.items()
        )
    if isinstance(obj, list):
        return len(obj) <= 100 and all(_safe_metadata_tree(v, depth + 1) for v in obj)
    return obj is None or isinstance(obj, (bool, int, float)) or (
        isinstance(obj, str) and len(obj) <= 4096
    )



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
        if not _safe_metadata_tree(detail or {}):
            raise SpecterTransportError("audit event contains disallowed raw secret or prompt fields")
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
            if not isinstance(d["detail"], dict) or not _safe_metadata_tree(d["detail"]):
                raise SpecterTransportError("audit metadata policy rejected event")
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
    """Batman-only reader; never accepts record/modify/delete requests."""

    def __init__(self, path: str | Path, *, timeout=4.0):
        self.socket_path = str(path)
        self.timeout = float(timeout)

    def _request(self, query, *, max_response=2_000_000):
        raw = (json.dumps(query, sort_keys=True) + "\n").encode("utf-8")
        if len(raw) > 4096:
            raise SpecterTransportError("invalid auditor query size")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(raw)
                buf = bytearray()
                while len(buf) <= max_response:
                    chunk = sock.recv(min(8192, max_response - len(buf) + 1))
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in chunk:
                        break
            if b"\n" not in buf or len(buf) > max_response:
                raise SpecterTransportError("invalid auditor response size")
            response = json.loads(buf.split(b"\n", 1)[0])
            if response.get("ok") is not True or not isinstance(response.get("report"), (dict, list)):
                raise SpecterTransportError("Batman auditor read denied")
            return response["report"]
        except (OSError, ValueError, TypeError) as exc:
            raise SpecterTransportError("Batman auditor read unavailable") from exc

    def verify(self):
        report = self._request({"op": "verify"}, max_response=4096)
        if not isinstance(report, dict) or not isinstance(report.get("valid"), bool):
            raise SpecterTransportError("auditor returned invalid chain verification")
        return report

    def events(self, mission_id=None, limit=500, after_seq=0):
        if mission_id is not None and not re.fullmatch(r"[0-9a-f]{32}", str(mission_id)):
            raise SpecterTransportError("invalid mission identifier")
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise SpecterTransportError("invalid event page size")
        if not isinstance(after_seq, int) or after_seq < 0:
            raise SpecterTransportError("invalid event offset")
        result = self._request({"op": "events", "mission_id": mission_id,
                                "limit": limit, "after_seq": after_seq})
        if not isinstance(result, list):
            raise SpecterTransportError("auditor returned invalid event page")
        return result

    def report(self, mission_id):
        if not isinstance(mission_id, str) or not re.fullmatch(r"[0-9a-f]{32}", mission_id):
            raise SpecterTransportError("invalid mission identifier")
        result = self._request({"op": "report", "mission_id": mission_id})
        if not isinstance(result, dict) or result.get("mission_id") != mission_id:
            raise SpecterTransportError("auditor returned invalid mission report")
        return result


class _VerifyHandler(socketserver.StreamRequestHandler):
    def handle(self):
        parent = self.server
        try:
            raw_peer = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            _, uid, _ = struct.unpack("3i", raw_peer)
            if uid not in parent.allowed_uids:
                raise SpecterTransportError("unapproved Batman peer UID")
            raw = self.rfile.readline(4097)
            if len(raw) > 4096 or not raw.endswith(b"\n"):
                raise SpecterTransportError("invalid query size")
            query = json.loads(raw)
            if not isinstance(query, dict):
                raise SpecterTransportError("invalid query object")
            op = query.get("op")
            if query == {"op": "verify"}:
                result = {"ok": True, "report": parent.reader.verify()}
            elif op == "events" and set(query) == {"op", "mission_id", "limit", "after_seq"}:
                mid = query["mission_id"]
                if mid is not None and (not isinstance(mid, str) or not re.fullmatch(r"[0-9a-f]{32}", mid)):
                    raise SpecterTransportError("invalid event scope")
                lim = query["limit"]
                seq = query["after_seq"]
                if not isinstance(lim, int) or not 1 <= lim <= 1000 or not isinstance(seq, int) or seq < 0:
                    raise SpecterTransportError("invalid pagination")
                result = {"ok": True, "report": parent.reader.events(mid, limit=lim, after_seq=seq)}
            elif op == "report" and set(query) == {"op", "mission_id"}:
                mid = query["mission_id"]
                if not isinstance(mid, str) or not re.fullmatch(r"[0-9a-f]{32}", mid):
                    raise SpecterTransportError("invalid report scope")
                # For large missions callers must page via /events instead of
                # silently receiving partial audit evidence.
                report = parent.reader.report(mid)
                result = {"ok": True, "report": report}
            else:
                raise SpecterTransportError("read-only auditor interface")
            payload = (json.dumps(result, sort_keys=True) + "\n").encode()
            if len(payload) > 2_000_000:
                raise SpecterTransportError("auditor response too large; request paginated events")
        except Exception:
            payload = b'{"error":"denied","ok":false}\n'
        try:
            self.wfile.write(payload)
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
