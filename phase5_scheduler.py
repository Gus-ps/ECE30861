"""Transactional dispatch for real and simulated scheduler ticks."""
from datetime import datetime, timezone
import logging
import os
from time import monotonic

from phase4_jobs import identifier
from phase5_reminders import dispatch_due_reminders, due_thresholds
from phase5_schedule import audit_due, dispatch_due_audits, locked_schedules
from release_guard import draining

logger = logging.getLogger(__name__)


def dispatch_work(store, db, namespace, instant, request_id, *, reject_busy=False,
                  audit_limit=None, reminder_limit=None, recorded_deadlines=None):
    """Fence the union once, then evaluate reminders before accepting audits."""
    if draining(db, lock=store.database.postgres):
        return [], []
    schedules = locked_schedules(store, db, namespace,
                                 lambda row: audit_due(row, instant) or due_thresholds(row, instant))
    notifications = dispatch_due_reminders(store, db, namespace, instant, limit=reminder_limit,
                                          schedules=schedules, recorded_deadlines=recorded_deadlines)
    audits = dispatch_due_audits(store, db, namespace, instant, request_id, reject_busy=reject_busy,
                                 limit=audit_limit, schedules=schedules,
                                 recorded_deadlines=recorded_deadlines)
    return audits, notifications


def tick(store):
    """Dispatch ordinary data using real UTC and report committed work."""
    request_id = identifier('scheduler')
    deadlines = []
    try:
        with store.connect(write=True) as db:
            instant = datetime.now(timezone.utc)
            audits, notifications = dispatch_work(store, db, None, instant, request_id,
                                                  recorded_deadlines=deadlines)
    except Exception as error:
        # Database errors can include connection details or row values.
        logger.error('scheduler_tick_failed request_id=%s accepted_audits=0 recorded_notifications=0 '
                     'dispatch_lag_seconds=None error_type=%s', request_id, type(error).__name__)
        raise
    lag = (instant - min(deadlines)).total_seconds() if deadlines else None
    log = logger.info if deadlines else logger.debug
    log('scheduler_tick request_id=%s accepted_audits=%d recorded_notifications=%d dispatch_lag_seconds=%s',
        request_id, len(audits), len(notifications), lag)
    return audits, notifications


def interval_seconds():
    try:
        seconds = float(os.getenv('SCHEDULER_INTERVAL_SECONDS', '1'))
    except ValueError:
        seconds = 0
    if not 0 < seconds <= 5:
        raise ValueError('SCHEDULER_INTERVAL_SECONDS must be greater than zero and at most 5 seconds.')
    return seconds


def run_scheduler(store, stop, interval):
    while not stop.is_set():
        started = monotonic()
        try:
            tick(store)
        except Exception:
            pass  # tick logged the failed transaction.
        stop.wait(max(0, interval - (monotonic() - started)))
