"""Durable workbook deletion reservations and resumable cleanup."""
from time import monotonic

from database import remaining_seconds
from phase4_store import now

DELETE_SECONDS = 30
VERSION_IDS = """SELECT id FROM p4_resources WHERE workbook_id=? AND kind='version'
                 UNION SELECT version_id FROM versions WHERE workbook_id=?"""
STEPS = ('p4_jobs', 'p4_keys', 'p5_upload_reservations', 'p5_schedules', 'p5_notifications',
         'p5_reminder_considered', 'audits', 'test_workbooks', 'versions', 'p4_resources')


def reservation(db, workbook_id):
    return db.execute('SELECT * FROM p5_deletions WHERE workbook_id=?', (workbook_id,)).fetchone()


def reserve(db, workbook_id, owner, namespace):
    db.execute('INSERT INTO p5_deletions (workbook_id,owner,namespace,created) VALUES (?,?,?,?)',
               (workbook_id, owner, namespace, now()))


def active(db, workbook_id, wall_time):
    return db.execute(f"""SELECT 1 FROM p4_jobs WHERE state IN ('PENDING','RUNNING')
        AND version_id IN ({VERSION_IDS})
        UNION ALL SELECT 1 FROM p5_upload_reservations WHERE workbook_id=? AND expires>?""",
        (workbook_id, workbook_id, workbook_id, wall_time)).fetchone() is not None


def delete_step(db, workbook_id, table):
    if table == 'p4_jobs':
        db.execute(f'DELETE FROM p4_jobs WHERE version_id IN ({VERSION_IDS})',
                   (workbook_id, workbook_id))
    else:
        db.execute(f'DELETE FROM {table} WHERE workbook_id=?', (workbook_id,))


def finish(store, workbook_id, deadline):
    """Commit each step separately, with the workbook fence on every step."""
    for table in STEPS:
        with store.connect(write=True, deadline=deadline) as db:
            store.fence(db, workbook_id)
            if reservation(db, workbook_id) is None:
                return  # A concurrent retry finished.
            delete_step(db, workbook_id, table)
    with store.connect(write=True, deadline=deadline) as db:
        store.fence(db, workbook_id)
        remaining_seconds(deadline)
        db.execute('DELETE FROM p5_deletions WHERE workbook_id=?', (workbook_id,))


def recover(store):
    with store.connect() as db:
        pending = db.execute('SELECT workbook_id FROM p5_deletions ORDER BY workbook_id').fetchall()
    for row in pending:
        finish(store, row['workbook_id'], monotonic() + DELETE_SECONDS)
