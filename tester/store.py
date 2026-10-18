"""SQLite persistence for tester sessions, frozen plans, progress and reports.

States: PREPARING -> READY -> RUNNING -> COMPLETE | ABORTED, or PREPARING -> SETUP_FAILED.
One tester process owns a store file.
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    target_url TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    plan TEXT NOT NULL,
    progress TEXT,
    report BLOB,
    failure TEXT
);
CREATE TABLE IF NOT EXISTS pending_cleanup (
    target_url TEXT NOT NULL,
    session_id TEXT NOT NULL,
    PRIMARY KEY (target_url, session_id)
);
"""
ENDED = ("COMPLETE", "ABORTED")


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    owner: str
    target_url: str
    state: str
    created_at: str
    plan: dict
    progress: dict | None
    report: bytes | None
    failure: str | None


class Store:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript(SCHEMA)

    def close(self):
        with self._lock:
            self._db.close()

    def _write(self, sql, params=()):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                rowcount = self._db.execute(sql, params).rowcount
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            return rowcount

    def _rows(self, sql, params=()):
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    @staticmethod
    def _session(row):
        session_id, owner, target_url, state, created_at, plan, progress, report, failure = row
        return SessionRow(session_id, owner, target_url, state, created_at, json.loads(plan),
                          json.loads(progress) if progress else None, report, failure)

    def create(self, session_id, owner, target_url, plan):
        self._write(
            "INSERT INTO sessions (session_id, owner, target_url, state, created_at, plan) "
            "VALUES (?, ?, ?, 'PREPARING', ?, ?)",
            (session_id, owner, target_url, datetime.now(timezone.utc).isoformat(), json.dumps(plan)))

    def get(self, session_id):
        rows = self._rows("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        return self._session(rows[0]) if rows else None

    def sessions_in(self, state):
        return [self._session(row) for row in self._rows("SELECT * FROM sessions WHERE state = ?", (state,))]

    def mark_ready(self, session_id):
        return self._write("UPDATE sessions SET state = 'READY' WHERE session_id = ? AND state = 'PREPARING'",
                           (session_id,)) == 1

    def mark_setup_failed(self, session_id, reason):
        return self._write("UPDATE sessions SET state = 'SETUP_FAILED', failure = ? "
                           "WHERE session_id = ? AND state = 'PREPARING'", (reason, session_id)) == 1

    def claim_run(self, session_id):
        ##  The one and only READY -> RUNNING transition; a second caller gets False.
        return self._write("UPDATE sessions SET state = 'RUNNING' WHERE session_id = ? AND state = 'READY'",
                           (session_id,)) == 1

    def save_progress(self, session_id, progress):
        self._write("UPDATE sessions SET progress = ? WHERE session_id = ? AND state = 'RUNNING'",
                    (json.dumps(progress), session_id))

    def finish(self, session_id, state, report, failure=None):
        ##  Stores the immutable report; only a RUNNING session without a report can finish.
        if state not in ENDED:
            raise ValueError(f"cannot finish a run as {state}")
        return self._write("UPDATE sessions SET state = ?, report = ?, failure = ? "
                           "WHERE session_id = ? AND state = 'RUNNING' AND report IS NULL",
                           (state, report, failure, session_id)) == 1

    def queue_cleanup(self, target_url, session_id):
        self._write("INSERT OR IGNORE INTO pending_cleanup (target_url, session_id) VALUES (?, ?)",
                    (target_url, session_id))

    def pending_cleanup(self, target_url):
        return [row[0] for row in self._rows(
            "SELECT session_id FROM pending_cleanup WHERE target_url = ? ORDER BY session_id", (target_url,))]

    def clear_cleanup(self, target_url, session_ids):
        for session_id in session_ids:
            self._write("DELETE FROM pending_cleanup WHERE target_url = ? AND session_id = ?",
                        (target_url, session_id))
