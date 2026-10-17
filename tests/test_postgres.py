"""Opt-in integration test against a dedicated PostgreSQL test database."""
import os
import unittest
from uuid import uuid4

from database import Database


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'Dedicated PostgreSQL test database not configured')
class PostgresTests(unittest.TestCase):
    def test_binary_roundtrip_source_immutability_and_rollback(self):
        import psycopg
        self.assertTrue(os.getenv('DB_HOST'))
        db = Database()
        db.initialize()
        workbook_id, version_id = uuid4().hex, uuid4().hex
        original = b'\x00\xfforiginal workbook bytes'
        # The final exception rolls the entire test transaction back.
        with self.assertRaisesRegex(RuntimeError, 'rollback test'):
            with db.connect() as connection:
                connection.execute('INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?)',
                                   (workbook_id, version_id, 'test-user', 'test.xlsx', 'test-hash',
                                    '2026-01-01T00:00:00Z', original))
                row = connection.execute('SELECT * FROM versions WHERE workbook_id=?', (workbook_id,)).fetchone()
                self.assertEqual(bytes(row['original']), original)
                with self.assertRaises(psycopg.Error):
                    with connection.connection.transaction():
                        connection.execute('UPDATE versions SET filename=? WHERE workbook_id=?',
                                           ('changed.xlsx', workbook_id))
                raise RuntimeError('rollback test')
        with db.connect() as connection:
            self.assertIsNone(connection.execute('SELECT * FROM versions WHERE workbook_id=?', (workbook_id,)).fetchone())
