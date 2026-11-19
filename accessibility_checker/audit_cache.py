"""Caches live only for one read-only audit, never across workbook edits or requests."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_current = ContextVar('workbook_audit_cache', default=None)


@contextmanager
def audit_cache(path):
    token = _current.set((str(Path(path).resolve()), {}))
    try:
        yield
    finally:
        _current.reset(token)


def cache_for(path):
    current = _current.get()
    return current[1] if current and current[0] == str(Path(path).resolve()) else None
