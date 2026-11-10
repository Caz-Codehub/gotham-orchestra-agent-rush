"""Specter 4.0: independent, append-only, tamper-evident audit journal.

Separation of authority:
  * The journal is a separate SQLite file (default: a sibling directory of the data dir that
    no worker tool or sandbox mounts), with its own HMAC key.
  * SQL triggers abort every UPDATE and DELETE (append-only).
  * Each entry's hash = HMAC(key, prev_hash || canonical(entry)), so editing the file out of band
    (without the key) is detected by `verify()`.
  * Workers/agents only ever receive an `AuditWriter` (record-only). Reading requires `AuditReader`,
    handed out solely to the Batman-authenticated API.
Limits (documented in docs/GOTHAM_ARCHITECTURE.md): an attacker with root on the host AND the key
can rewrite history; deployment should forward the head hash off-host.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

ZERO = '0' * 64
SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|token|secret|password|passwd|authorization)(["\'\s:=]+)([^\s"\',}]{6,})'),
    re.compile(r'\b(?:sk|pk|ghp|gho|ghs|xox[bp])[-_][A-Za-z0-9_\-]{16,}\b'),
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, mission_id TEXT, task_id TEXT,
  actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_events_mission ON events(mission_id);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'audit journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'audit journal is append-only'); END;
"""


def redact(value, depth=0):
    """Remove credential-shaped strings and bound size before persisting."""
    if isinstance(value, str):
        s = value
        for p in SECRET_PATTERNS:
            s = p.sub(lambda m: (m.group(1) + m.group(2) + '[REDACTED]') if m.lastindex and m.lastindex >= 3 else '[REDACTED]', s)
        return s[:2000]
    if isinstance(value, dict) and depth < 6:
        return {str(k)[:80]: redact(v, depth + 1) for k, v in list(value.items())[:60]}
    if isinstance(value, (list, tuple)) and depth < 6:
        return [redact(v, depth + 1) for v in list(value)[:60]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, default=str)


def _load_key(path: Path) -> bytes:
    env = os.environ.get('GOTHAM_AUDIT_KEY')
    if env and len(env) >= 32:
        return env.encode()
    keyfile = path.with_suffix('.key')
    if keyfile.exists():
        return keyfile.read_bytes().strip()
    key = secrets.token_hex(32).encode()
    fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(key)
    return key


class _Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self._key = _load_key(self.path)
        with self._conn() as c:
            c.executescript(SCHEMA)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _conn(self):
        c = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA busy_timeout=30000')
        return c

    def _mac(self, prev, body) -> str:
        return hmac.new(self._key, (prev + _canon(body)).encode(), hashlib.sha256).hexdigest()


class AuditWriter(_Journal):
    """Record-only handle. No read/verify/export methods are exposed to workers."""

    def record(self, mission_id, task_id, actor, action, detail=None) -> str:
        detail = redact(detail or {})
        c = self._conn()
        try:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            prev = row['hash'] if row else ZERO
            ts = round(time.time(), 6)
            body = {'ts': ts, 'mission_id': mission_id, 'task_id': task_id, 'actor': actor,
                    'action': action, 'detail': detail}
            h = self._mac(prev, body)
            c.execute('INSERT INTO events(ts,mission_id,task_id,actor,action,detail,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?)',
                      (ts, mission_id, task_id, actor, action, _canon(detail), prev, h))
            c.execute('COMMIT')
            return h
        except Exception:
            try:
                c.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            raise
        finally:
            c.close()


class AuditReader(_Journal):
    """Batman-only handle: query, verify, and report."""

    def verify(self) -> dict:
        prev = ZERO
        n = 0
        with self._conn() as c:
            for r in c.execute('SELECT * FROM events ORDER BY seq'):
                body = {'ts': r['ts'], 'mission_id': r['mission_id'], 'task_id': r['task_id'], 'actor': r['actor'],
                        'action': r['action'], 'detail': json.loads(r['detail'])}
                if r['prev_hash'] != prev:
                    return {'valid': False, 'checked': n, 'broken_at_seq': r['seq'], 'reason': 'prev_hash mismatch (deleted/reordered entry)'}
                if not hmac.compare_digest(self._mac(prev, body), r['hash']):
                    return {'valid': False, 'checked': n, 'broken_at_seq': r['seq'], 'reason': 'entry content altered'}
                prev = r['hash']
                n += 1
        return {'valid': True, 'checked': n, 'head': prev}

    def events(self, mission_id=None, limit=500, after_seq=0):
        with self._conn() as c:
            rows = c.execute('SELECT * FROM events WHERE (?1 IS NULL OR mission_id=?1) AND seq>?2 ORDER BY seq LIMIT ?3',
                             (mission_id, after_seq, limit)).fetchall()
        return [{**dict(r), 'detail': json.loads(r['detail'])} for r in rows]

    def report(self, mission_id) -> dict:
        ev = self.events(mission_id, limit=5000)
        violations = [e for e in ev if e['action'].startswith(('policy_violation', 'prompt_injection', 'scope_violation'))]
        tools = [e for e in ev if e['action'] == 'tool_call']
        return {'mission_id': mission_id, 'event_count': len(ev), 'tool_calls': len(tools),
                'policy_violations': violations, 'integrity': self.verify(),
                'actors': sorted({e['actor'] for e in ev}), 'events': ev}
