"""Persistent effective time for isolated test sessions."""
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from contracts import Contract

INITIAL_TIME = '2027-01-01T00:00:00Z'
ClockTimestamp = Annotated[str, StringConstraints(
    pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$',
), Field(json_schema_extra={'format': 'date-time'})]


class ClockRequest(Contract):
    currentTime: ClockTimestamp

    @field_validator('currentTime')
    @classmethod
    def normalize_time(cls, value):
        return format_time(datetime.fromisoformat(value))


def format_time(instant):
    return instant.isoformat().replace('+00:00', 'Z')


def read(db, session_id):
    row = db.execute('SELECT "current_time" FROM p5_clocks WHERE session_id=?', (session_id,)).fetchone()
    return datetime.fromisoformat(row['current_time']) if row else None
