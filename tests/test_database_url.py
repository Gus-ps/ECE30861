import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from database import Database


class DatabaseUrlTests(unittest.TestCase):
    @patch.dict(os.environ, {'DATABASE_URL': 'postgresql://user:secret@private-host/workbooks', 'DB_HOST': ''})
    def test_hosted_url_uses_encrypted_postgres_connection(self):
        driver = MagicMock()
        with patch.dict('sys.modules', {'psycopg': driver, 'psycopg.rows': MagicMock()}):
            connect = driver.connect
            database = Database()
            self.assertTrue(database.postgres)
            with database.connect() as connection:
                connection.execute('SELECT ?', (1,))
            self.assertEqual(connect.call_args.args, (os.environ['DATABASE_URL'],))
            self.assertEqual(connect.call_args.kwargs['sslmode'], 'require')
            connect.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT %s', (1,))

    @patch.dict(os.environ, {'DATABASE_URL': 'postgresql://unused-host/workbooks', 'DB_HOST': ''})
    def test_explicit_local_database_overrides_hosted_url(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / 'test.sqlite3')
            self.assertFalse(database.postgres)
            database.initialize()
            with database.connect() as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 0)
