"""REQ-12 / AC-12, AC-15 storage; P5-SCHEDULE initial due. Not a WCAG rule."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from database import Database
from phase4_store import Store
import phase5_schedule as schedule


class ScheduleStoreTests(unittest.TestCase):
    def test_default_write_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory)/'db')
            database.initialize()
            store = Store(database)
            schedule.initialize(store)
            with store.connect(write=True) as db:
                store.insert(db,'workbook','wb',{},'owner',None,'wb')
                store.insert(db,'version','ver',{},'owner',None,'wb','ver')
                workbook = store.get(db,'wb')
                self.assertFalse(schedule.read(db,workbook)['enabled'])
                self.assertEqual(db.execute('SELECT count(*) n FROM p5_schedules').fetchone()['n'],0)
                with patch.object(schedule,'effective_now',return_value=datetime(2027,1,1,tzinfo=timezone.utc)):
                    result=schedule.write(db,workbook,dict(enabled=True,intervalDays=90,complianceDeadline=None))
                self.assertEqual(result['nextAuditAt'],'2027-04-01T00:00:00Z')
