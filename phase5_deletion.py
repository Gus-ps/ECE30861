"""Durable workbook deletion reservations and resumable cleanup."""
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, NamedTuple
from time import monotonic

from contracts import strict_json
from database import remaining_seconds
from phase4_store import now

DELETE_SECONDS = 30
logger = logging.getLogger(__name__)
VERSION_IDS = """SELECT id FROM p4_resources WHERE workbook_id=? AND kind='version'
                 UNION SELECT version_id FROM versions WHERE workbook_id=?"""
STEPS = ('p4_jobs', 'p4_keys', 'p5_upload_reservations', 'p5_schedules', 'p5_notifications',
         'p5_reminder_considered', 'audits', 'test_workbooks', 'versions', 'p4_resources')


def reservation(db, workbook_id):
    return db.execute('SELECT * FROM p5_deletions WHERE workbook_id=?', (workbook_id,)).fetchone()


def namespace_has_deletion(db, namespace):
    return db.execute('SELECT 1 FROM p5_deletions WHERE namespace=? LIMIT 1', (namespace,)).fetchone() is not None

def reserve(db, workbook_id, owner, namespace):
    created = now()
    db.execute('INSERT INTO p5_deletions (workbook_id,owner,namespace,created) VALUES (?,?,?,?)',
               (workbook_id, owner, namespace, created))
    return created


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


def commit_step(store, workbook_id, table, deadline):
    with store.connect(write=True, deadline=deadline) as db:
        store.fence(db, workbook_id)
        if reservation(db, workbook_id) is None:
            return False  # A concurrent retry or namespace cleanup finished.
        delete_step(db, workbook_id, table)
        return True


def finish(store, workbook_id, deadline):
    """Commit each step separately, with the workbook fence on every step."""
    for table in STEPS:
        if not commit_step(store, workbook_id, table, deadline):
            return
    with store.connect(write=True, deadline=deadline) as db:
        store.fence(db, workbook_id)
        remaining_seconds(deadline)
        db.execute('DELETE FROM p5_deletions WHERE workbook_id=?', (workbook_id,))


def parse_ledger_line(line):
    entry = strict_json(line)
    if not isinstance(entry, dict) or set(entry) != {'workbook_id', 'timestamp'}:
        raise ValueError('Invalid ledger fields.')
    workbook_id, timestamp = entry['workbook_id'], entry['timestamp']
    if not isinstance(workbook_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', workbook_id):
        raise ValueError('Invalid ledger identifier.')
    if (not isinstance(timestamp, str)
            or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z', timestamp)):
        raise ValueError('Invalid ledger timestamp.')
    datetime.fromisoformat(timestamp)
    return workbook_id


def sync_ledger(file, path):
    file.flush()
    os.fsync(file.fileno())
    if os.name == 'posix':
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def ledger_records(store, path, *, entry=None, deadline=None):
    """Read/repair/append under the shared database's ledger mutex."""
    line_number = 0
    try:
        with store.connect(write=True, deadline=deadline) as db:
            if store.database.postgres:
                db.execute('SELECT pg_advisory_xact_lock(3086102)')
            flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, 'O_BINARY', 0)
            with os.fdopen(os.open(path, flags, 0o600), 'r+b') as file:
                file.seek(0)
                ids = set()
                good_end = 0
                for line_number, line in enumerate(file, 1):
                    if deadline is not None:
                        remaining_seconds(deadline)
                    if not line.endswith(b'\n'):
                        logger.warning('Deletion ledger ignored incomplete tail: error_type=TruncatedTail line=%d',
                                       line_number)
                        file.truncate(good_end)
                        break
                    ids.add(parse_ledger_line(line))
                    good_end += len(line)
                if entry is not None and entry['workbook_id'] not in ids:
                    if deadline is not None:
                        remaining_seconds(deadline)
                    row = json.dumps(entry, separators=(',', ':')).encode('ascii') + b'\n'
                    file.write(row)
                sync_ledger(file, path)
                return ids
    except (OSError, ValueError, RecursionError) as exc:
        logger.error('Deletion ledger unavailable or invalid: error_type=%s line=%d',
                     type(exc).__name__, line_number)
        raise RuntimeError('Deletion ledger is unavailable or invalid.') from None


class S3Ledger(NamedTuple):
    client: Any
    bucket: str


def s3_ledger_records(ledger, *, entry=None, deadline=None):
    """Put one object per deletion, or list the prefix; D11 fixes the key and body."""
    try:
        if entry is not None:
            if deadline is not None:
                remaining_seconds(deadline)
            ledger.client.put_object(Bucket=ledger.bucket, Key=f"deletions/{entry['workbook_id']}.json",
                                     Body=json.dumps(entry, separators=(',', ':')).encode('ascii'))
            return None
        ids = set()
        pages = ledger.client.get_paginator('list_objects_v2').paginate(Bucket=ledger.bucket, Prefix='deletions/')
        for page in pages:
            for item in page.get('Contents', []):
                match = re.fullmatch(r'deletions/([A-Za-z0-9_-]{1,64})\.json', item['Key'])
                if match is None:
                    raise ValueError('Invalid ledger key.')
                ids.add(match.group(1))
        return ids
    except Exception as exc:  # botocore raises several unrelated exception families.
        logger.error('Deletion ledger unavailable or invalid: error_type=%s', type(exc).__name__)
        raise RuntimeError('Deletion ledger is unavailable or invalid.') from None


def record_intent(store, ledger, workbook_id, created, deadline):
    entry = {'workbook_id': workbook_id, 'timestamp': created}
    if isinstance(ledger, S3Ledger):
        s3_ledger_records(ledger, entry=entry, deadline=deadline)
    elif ledger is not None:
        ledger_records(store, ledger, entry=entry, deadline=deadline)


def reserve_restored(store, workbook_id):
    deadline = monotonic() + DELETE_SECONDS
    with store.connect(write=True, deadline=deadline) as db:
        store.fence(db, workbook_id)
        if reservation(db, workbook_id) is not None:
            return
        row = db.execute('SELECT owner,namespace FROM p4_resources WHERE workbook_id=? LIMIT 1',
                         (workbook_id,)).fetchone()
        if row is None:
            row = db.execute('''SELECT v.owner,t.session_id AS namespace FROM versions v
                LEFT JOIN test_workbooks t ON t.workbook_id=v.workbook_id WHERE v.workbook_id=?''',
                (workbook_id,)).fetchone()
        if row is not None:
            reserve(db, workbook_id, row['owner'], row['namespace'])
            return
        for table in STEPS[1:]:
            if db.execute(f'SELECT 1 FROM {table} WHERE workbook_id=? LIMIT 1', (workbook_id,)).fetchone():
                # Residual records without a workbook identity have no owner who could resume.
                reserve(db, workbook_id, '', None)
                break


def recover(store, ledger=None):
    acknowledged = set()
    if ledger is None:
        logger.warning('DELETION_LEDGER_PATH is unset; restores can reintroduce deleted workbooks.')
    else:
        acknowledged = (s3_ledger_records(ledger) if isinstance(ledger, S3Ledger)
                        else ledger_records(store, Path(ledger)))
        for workbook_id in sorted(acknowledged):
            reserve_restored(store, workbook_id)
    with store.connect() as db:
        pending = db.execute('SELECT workbook_id,created FROM p5_deletions ORDER BY workbook_id').fetchall()
    for row in pending:
        workbook_id = row['workbook_id']
        deadline = monotonic() + DELETE_SECONDS
        if workbook_id not in acknowledged:
            record_intent(store, ledger, workbook_id, row['created'], deadline)
        finish(store, workbook_id, deadline)
