"""Real-time test-run leases and a transactional deployment drain fence."""
import json
import sys
import time

PROTECTION_SECONDS = 2700  # setup + 2400 s run + report retrieval + margin


def initialize(store):
    with store.connect(write=True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS p5_release_leases (owner TEXT PRIMARY KEY, expires_at DOUBLE PRECISION NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS p5_release_state (id INTEGER PRIMARY KEY, draining INTEGER NOT NULL)')
        db.execute('INSERT INTO p5_release_state VALUES (1,0) ON CONFLICT(id) DO NOTHING')


def draining(db, *, lock=False):
    query = 'SELECT draining FROM p5_release_state WHERE id=1'
    return bool(db.execute(query + (' FOR UPDATE' if lock else '')).fetchone()['draining'])


def protect(db, owner):
    from test_interface import TestSessionError
    if draining(db):
        raise TestSessionError(503, 'A release is draining; retry setup after it completes.')
    db.execute('''INSERT INTO p5_release_leases VALUES (?,?) ON CONFLICT(owner)
                  DO UPDATE SET expires_at=excluded.expires_at''', (owner, time.time()+PROTECTION_SECONDS))


def arm(store):
    with store.connect(write=True) as db:
        # SQLite's write lock or the PG singleton row serializes setup and drain.
        if store.database.postgres:
            db.execute('SELECT id FROM p5_release_state WHERE id=1 FOR UPDATE')
        leases = db.execute('SELECT MAX(expires_at) AS until FROM p5_release_leases').fetchone()['until']
        active = db.execute("SELECT COUNT(*) AS n FROM p4_jobs WHERE state IN ('PENDING','RUNNING')").fetchone()['n']
        if active or leases and leases > time.time():
            raise RuntimeError('Release deferred: active jobs or a protected tester run (2700-second lease).')
        db.execute('UPDATE p5_release_state SET draining=1 WHERE id=1')


def resume(store):
    with store.connect(write=True) as db:
        db.execute('UPDATE p5_release_state SET draining=0 WHERE id=1')


if __name__ == '__main__':
    from database import Database
    from phase4_store import Store
    store = Store(Database())
    initialize(store)
    if sys.argv[1:] == ['arm']:
        arm(store)
        print(json.dumps({'release': 'draining', 'protectionSeconds': PROTECTION_SECONDS}))
    elif sys.argv[1:] == ['resume']:
        resume(store)
        print(json.dumps({'release': 'ready'}))
    else:
        raise SystemExit('Use arm or resume.')
