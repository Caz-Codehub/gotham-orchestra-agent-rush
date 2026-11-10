"""Durable mission/task store (SQLite WAL). All orchestration state lives here, not in memory.

Tasks are claimed with short leases. A worker that dies leaves an expired lease, and
`recover_expired` re-queues (bounded retries) or fails the task, so state survives restarts.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions(
  id TEXT PRIMARY KEY, kind TEXT, goal TEXT, status TEXT, created REAL, updated REAL,
  requested_by TEXT, params TEXT, result TEXT, budget TEXT, cancel_requested INTEGER DEFAULT 0,
  idem_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, mission_id TEXT, agent TEXT, kind TEXT, title TEXT, params TEXT,
  status TEXT, depends TEXT, attempts INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 2,
  lease_owner TEXT, lease_expires REAL, result TEXT, error TEXT, created REAL, started REAL,
  finished REAL, timeout_s INTEGER DEFAULT 300, risk TEXT DEFAULT 'low', mode TEXT DEFAULT 'playbook',
  seq INTEGER);
CREATE INDEX IF NOT EXISTS idx_tasks_mission ON tasks(mission_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE TABLE IF NOT EXISTS artifacts(
  id TEXT PRIMARY KEY, mission_id TEXT, task_id TEXT, name TEXT, path TEXT, sha256 TEXT,
  size INTEGER, producer TEXT, created REAL);
CREATE TABLE IF NOT EXISTS approvals(
  id TEXT PRIMARY KEY, mission_id TEXT, task_id TEXT, action TEXT, detail TEXT, status TEXT,
  requested REAL, decided REAL, decided_by TEXT);
CREATE TABLE IF NOT EXISTS usage(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT, task_id TEXT, kind TEXT, amount REAL, ts REAL);
CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY, pid INTEGER, started REAL, seen REAL, concurrency INTEGER);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT, task_id TEXT, sender TEXT, recipient TEXT,
  type TEXT, body TEXT, ts REAL);
"""
TERMINAL = {'succeeded', 'failed', 'cancelled', 'blocked'}


def _j(v):
    return json.dumps(v, sort_keys=True, default=str)


def _l(s):
    return json.loads(s) if s else None


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq_lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA busy_timeout=30000')
        try:
            yield c
        finally:
            c.close()

    # ---- missions -------------------------------------------------------
    def create_mission(self, kind, goal, params, requested_by, budget=None, idem_key=None) -> str:
        with self._conn() as c:
            if idem_key:
                row = c.execute('SELECT id FROM missions WHERE idem_key=?', (idem_key,)).fetchone()
                if row:
                    return row['id']
            mid = uuid.uuid4().hex
            now = time.time()
            c.execute('INSERT INTO missions(id,kind,goal,status,created,updated,requested_by,params,budget,idem_key)'
                      ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (mid, kind, goal, 'planning', now, now, requested_by, _j(params), _j(budget or {}), idem_key))
            return mid

    def get_mission(self, mid) -> dict | None:
        with self._conn() as c:
            r = c.execute('SELECT * FROM missions WHERE id=?', (mid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ('params', 'result', 'budget'):
            d[k] = _l(d[k])
        return d

    def list_missions(self, limit=50):
        with self._conn() as c:
            rows = c.execute('SELECT id,kind,goal,status,created,updated,requested_by,cancel_requested'
                             ' FROM missions ORDER BY created DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]

    def set_mission(self, mid, **fields):
        if 'result' in fields:
            fields['result'] = _j(fields['result'])
        fields['updated'] = time.time()
        cols = ','.join(f'{k}=?' for k in fields)
        with self._conn() as c:
            c.execute(f'UPDATE missions SET {cols} WHERE id=?', (*fields.values(), mid))

    # ---- tasks ----------------------------------------------------------
    def add_task(self, mission_id, agent, kind, title, params, depends=(), risk='low', mode='playbook',
                 timeout_s=300, max_attempts=2) -> str:
        tid = uuid.uuid4().hex
        status = 'awaiting_approval' if risk == 'high' else 'pending'
        with self._conn() as c:
            seq = c.execute('SELECT COALESCE(MAX(seq),0)+1 FROM tasks WHERE mission_id=?', (mission_id,)).fetchone()[0]
            c.execute('INSERT INTO tasks(id,mission_id,agent,kind,title,params,status,depends,max_attempts,created,'
                      'timeout_s,risk,mode,seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (tid, mission_id, agent, kind, title, _j(params), status, _j(list(depends)), max_attempts,
                       time.time(), timeout_s, risk, mode, seq))
        return tid

    def _task(self, r):
        d = dict(r)
        for k in ('params', 'result', 'depends'):
            d[k] = _l(d[k])
        return d

    def get_task(self, tid):
        with self._conn() as c:
            r = c.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
        return self._task(r) if r else None

    def tasks_for(self, mission_id):
        with self._conn() as c:
            rows = c.execute('SELECT * FROM tasks WHERE mission_id=? ORDER BY seq', (mission_id,)).fetchall()
        return [self._task(r) for r in rows]

    def claim_next(self, worker_id, lease_s, agents=None) -> dict | None:
        """Atomically claim one runnable task (all dependencies succeeded, mission not cancelled)."""
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                rows = c.execute("SELECT t.* FROM tasks t JOIN missions m ON m.id=t.mission_id "
                                 "WHERE t.status='pending' AND m.cancel_requested=0 ORDER BY t.created, t.seq").fetchall()
                for r in rows:
                    t = self._task(r)
                    if agents and t['agent'] not in agents:
                        continue
                    deps = t['depends'] or []
                    if deps:
                        q = ','.join('?' * len(deps))
                        done = c.execute(f"SELECT COUNT(*) FROM tasks WHERE id IN ({q}) AND status='succeeded'",
                                         deps).fetchone()[0]
                        if done != len(deps):
                            continue
                    now = time.time()
                    c.execute("UPDATE tasks SET status='running', lease_owner=?, lease_expires=?, "
                              "attempts=attempts+1, started=COALESCE(started,?) WHERE id=?",
                              (worker_id, now + lease_s, now, t['id']))
                    c.execute('COMMIT')
                    return self.get_task(t['id'])
                c.execute('COMMIT')
                return None
            except Exception:
                c.execute('ROLLBACK')
                raise

    def heartbeat(self, tid, worker_id, lease_s) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE tasks SET lease_expires=? WHERE id=? AND lease_owner=? AND status='running'",
                            (time.time() + lease_s, tid, worker_id))
            return cur.rowcount == 1

    def finish_task(self, tid, worker_id, status, result=None, error=None) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE tasks SET status=?, result=?, error=?, finished=?, lease_owner=NULL, "
                            "lease_expires=NULL WHERE id=? AND lease_owner=? AND status='running'",
                            (status, _j(result) if result is not None else None, error, time.time(), tid, worker_id))
            return cur.rowcount == 1

    def requeue_task(self, tid, worker_id, error):
        with self._conn() as c:
            c.execute("UPDATE tasks SET status='pending', lease_owner=NULL, lease_expires=NULL, error=? "
                      "WHERE id=? AND lease_owner=? AND status='running'", (error, tid, worker_id))

    def recover_expired(self) -> list[dict]:
        """Re-queue (or fail, when attempts are exhausted) tasks whose worker lease lapsed."""
        out = []
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            rows = c.execute("SELECT * FROM tasks WHERE status='running' AND lease_expires < ?", (time.time(),)).fetchall()
            for r in rows:
                if r['attempts'] >= r['max_attempts']:
                    c.execute("UPDATE tasks SET status='failed', error='lease expired; retry budget exhausted', "
                              "finished=?, lease_owner=NULL, lease_expires=NULL WHERE id=?", (time.time(), r['id']))
                    out.append({'task_id': r['id'], 'mission_id': r['mission_id'], 'action': 'failed'})
                else:
                    c.execute("UPDATE tasks SET status='pending', error='lease expired; re-queued', lease_owner=NULL,"
                              " lease_expires=NULL WHERE id=?", (r['id'],))
                    out.append({'task_id': r['id'], 'mission_id': r['mission_id'], 'action': 'requeued'})
            c.execute('COMMIT')
        return out

    def block_dependents(self) -> int:
        """Tasks whose dependency failed/cancelled/blocked can never run: mark blocked."""
        n = 0
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            for r in c.execute("SELECT id,depends FROM tasks WHERE status IN ('pending','awaiting_approval')").fetchall():
                deps = _l(r['depends']) or []
                if not deps:
                    continue
                q = ','.join('?' * len(deps))
                bad = c.execute(f"SELECT COUNT(*) FROM tasks WHERE id IN ({q}) AND status IN ('failed','cancelled','blocked')", deps).fetchone()[0]
                if bad:
                    c.execute("UPDATE tasks SET status='blocked', error='dependency did not succeed', finished=? WHERE id=?",
                              (time.time(), r['id']))
                    n += 1
            c.execute('COMMIT')
        return n

    def cancel_mission(self, mid):
        with self._conn() as c:
            c.execute('UPDATE missions SET cancel_requested=1, updated=? WHERE id=?', (time.time(), mid))
            c.execute("UPDATE tasks SET status='cancelled', finished=? WHERE mission_id=? AND status IN "
                      "('pending','awaiting_approval')", (time.time(), mid))

    def task_status(self, tid):
        with self._conn() as c:
            r = c.execute('SELECT status FROM tasks WHERE id=?', (tid,)).fetchone()
        return r['status'] if r else None

    def set_task_status(self, tid, status):
        with self._conn() as c:
            c.execute('UPDATE tasks SET status=? WHERE id=?', (status, tid))

    def open_missions(self):
        with self._conn() as c:
            return [r['id'] for r in c.execute("SELECT id FROM missions WHERE status IN ('planning','running','awaiting_approval')")]

    # ---- artifacts / approvals / usage / messages -------------------------
    def add_artifact(self, mission_id, task_id, name, path, sha256, size, producer) -> str:
        aid = uuid.uuid4().hex
        with self._conn() as c:
            c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)',
                      (aid, mission_id, task_id, name, str(path), sha256, size, producer, time.time()))
        return aid

    def artifacts_for(self, mission_id=None):
        with self._conn() as c:
            rows = c.execute('SELECT * FROM artifacts WHERE (?1 IS NULL OR mission_id=?1) ORDER BY created DESC',
                             (mission_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_artifact(self, aid):
        with self._conn() as c:
            r = c.execute('SELECT * FROM artifacts WHERE id=?', (aid,)).fetchone()
        return dict(r) if r else None

    def request_approval(self, mission_id, task_id, action, detail) -> str:
        with self._conn() as c:
            row = c.execute("SELECT id FROM approvals WHERE task_id=? AND action=? AND status='pending'",
                            (task_id, action)).fetchone()
            if row:
                return row['id']
            aid = uuid.uuid4().hex
            c.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?)',
                      (aid, mission_id, task_id, action, _j(detail), 'pending', time.time(), None, None))
            return aid

    def decide_approval(self, aid, approve: bool, decided_by) -> dict | None:
        with self._conn() as c:
            cur = c.execute("UPDATE approvals SET status=?, decided=?, decided_by=? WHERE id=? AND status='pending'",
                            ('approved' if approve else 'denied', time.time(), decided_by, aid))
            if cur.rowcount != 1:
                return None
            r = c.execute('SELECT * FROM approvals WHERE id=?', (aid,)).fetchone()
            if approve:
                c.execute("UPDATE tasks SET status='pending' WHERE id=? AND status='awaiting_approval'", (r['task_id'],))
                if r['action'] == 'task_start':
                    # One human decision authorises exactly the tools the task declared (shown to Batman).
                    for t in (_l(r['detail']) or {}).get('tools', []):
                        c.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?)',
                                  (uuid.uuid4().hex, r['mission_id'], r['task_id'], f'tool:{t}', _j({'granted_by': aid}),
                                   'approved', time.time(), time.time(), decided_by))
            else:
                c.execute("UPDATE tasks SET status='cancelled', error='approval denied', finished=? WHERE id=? "
                          "AND status='awaiting_approval'", (time.time(), r['task_id']))
        d = dict(r)
        d['detail'] = _l(d['detail'])
        return d

    def approvals(self, status=None, mission_id=None):
        with self._conn() as c:
            rows = c.execute('SELECT * FROM approvals WHERE (?1 IS NULL OR status=?1) AND (?2 IS NULL OR mission_id=?2) '
                             'ORDER BY requested DESC', (status, mission_id)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['detail'] = _l(d['detail'])
            out.append(d)
        return out

    def has_approval(self, task_id, action) -> bool:
        with self._conn() as c:
            r = c.execute("SELECT 1 FROM approvals WHERE task_id=? AND action=? AND status='approved'",
                          (task_id, action)).fetchone()
        return bool(r)

    def add_usage(self, mission_id, task_id, kind, amount):
        with self._conn() as c:
            c.execute('INSERT INTO usage(mission_id,task_id,kind,amount,ts) VALUES(?,?,?,?,?)',
                      (mission_id, task_id, kind, amount, time.time()))

    def usage_totals(self, mission_id=None):
        with self._conn() as c:
            rows = c.execute('SELECT kind, SUM(amount) a, COUNT(*) n FROM usage WHERE (?1 IS NULL OR mission_id=?1) GROUP BY kind',
                             (mission_id,)).fetchall()
        return {r['kind']: {'total': r['a'], 'events': r['n']} for r in rows}

    def add_message(self, mission_id, task_id, sender, recipient, mtype, body):
        with self._conn() as c:
            c.execute('INSERT INTO messages(mission_id,task_id,sender,recipient,type,body,ts) VALUES(?,?,?,?,?,?,?)',
                      (mission_id, task_id, sender, recipient, mtype, _j(body), time.time()))

    def messages_for(self, mission_id, limit=200):
        with self._conn() as c:
            rows = c.execute('SELECT * FROM messages WHERE mission_id=? ORDER BY id LIMIT ?', (mission_id, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['body'] = _l(d['body'])
            out.append(d)
        return out

    # ---- workers & recovery controls ---------------------------------------
    def worker_seen(self, wid, pid, concurrency):
        now = time.time()
        with self._conn() as c:
            c.execute('INSERT INTO workers(id,pid,started,seen,concurrency) VALUES(?,?,?,?,?) '
                      'ON CONFLICT(id) DO UPDATE SET seen=excluded.seen', (wid, pid, now, now, concurrency))

    def live_workers(self, within=30):
        with self._conn() as c:
            return [dict(r) for r in c.execute('SELECT * FROM workers WHERE seen > ? ORDER BY seen DESC', (time.time() - within,))]

    def retry_task(self, tid) -> bool:
        """Operator recovery: re-run a failed task (and un-block its dependents)."""
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            r = c.execute("SELECT mission_id,status FROM tasks WHERE id=?", (tid,)).fetchone()
            if not r or r['status'] not in ('failed', 'cancelled'):
                c.execute('COMMIT')
                return False
            c.execute("UPDATE tasks SET status='pending', attempts=0, error=NULL, result=NULL, finished=NULL WHERE id=?", (tid,))
            c.execute("UPDATE tasks SET status='pending', error=NULL, finished=NULL WHERE mission_id=? AND status='blocked'", (r['mission_id'],))
            c.execute("UPDATE missions SET status='running', cancel_requested=0, result=NULL, updated=? WHERE id=?", (time.time(), r['mission_id']))
            c.execute('COMMIT')
        return True

    def counts(self):
        with self._conn() as c:
            return {'missions': {r['status']: r['n'] for r in c.execute('SELECT status, COUNT(*) n FROM missions GROUP BY status')},
                    'tasks': {r['status']: r['n'] for r in c.execute('SELECT status, COUNT(*) n FROM tasks GROUP BY status')}}

    def agent_activity(self):
        with self._conn() as c:
            rows = c.execute("SELECT agent, status, COUNT(*) n FROM tasks GROUP BY agent, status").fetchall()
            cur = c.execute("SELECT agent, title, mission_id, started FROM tasks WHERE status='running'").fetchall()
        return [dict(r) for r in rows], [dict(r) for r in cur]
