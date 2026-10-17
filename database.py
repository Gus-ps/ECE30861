"""SQLite for local development; PostgreSQL for the AWS deployment."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        return self.connection.execute(query.replace('?', '%s'), parameters)


class Database:
    def __init__(self, local_path=None):
        self.postgres = local_path is None and bool(os.getenv('DB_HOST'))
        self.path = Path(local_path or os.getenv('DATABASE_PATH', 'data/workbooks.sqlite3'))
        if not self.postgres:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            if os.getenv('DB_SECRET_ARN'):
                import boto3
                secret = json.loads(boto3.client('secretsmanager').get_secret_value(
                    SecretId=os.environ['DB_SECRET_ARN'])['SecretString'])
            else:
                secret = json.loads(os.environ['DB_SECRET_JSON'])
            with psycopg.connect(
                host=os.environ['DB_HOST'], port=int(os.getenv('DB_PORT', '5432')),
                dbname=os.getenv('DB_NAME', 'workbooks'),
                user=secret['username'], password=secret['password'],
                sslmode='verify-full', sslrootcert=os.environ['DB_SSLROOTCERT'],
                connect_timeout=10, row_factory=dict_row,
            ) as connection:
                yield PostgresConnection(connection)
        else:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute('PRAGMA foreign_keys=ON')
                with connection:
                    yield connection
            finally:
                connection.close()

    def initialize(self):
        with self.connect() as db:
            if self.postgres:
                # Serialize schema initialization across simultaneous instance starts.
                db.execute('SELECT pg_advisory_xact_lock(3086101)')
            binary_type = 'BYTEA' if self.postgres else 'BLOB'
            db.execute(f'''CREATE TABLE IF NOT EXISTS versions (
                workbook_id TEXT PRIMARY KEY, version_id TEXT UNIQUE NOT NULL,
                owner TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL, original {binary_type} NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS audits (
                audit_id TEXT PRIMARY KEY, workbook_id TEXT NOT NULL REFERENCES versions(workbook_id),
                status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
                findings TEXT NOT NULL DEFAULT '[]', limitations TEXT NOT NULL DEFAULT '[]', error TEXT)''')
            if self.postgres:
                db.execute('''CREATE OR REPLACE FUNCTION reject_source_update() RETURNS trigger
                    LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'Source versions are immutable'; END; $$''')
                db.execute('DROP TRIGGER IF EXISTS immutable_source ON versions')
                db.execute('''CREATE TRIGGER immutable_source BEFORE UPDATE ON versions
                    FOR EACH ROW EXECUTE FUNCTION reject_source_update()''')
            else:
                db.execute('''CREATE TRIGGER IF NOT EXISTS immutable_source BEFORE UPDATE ON versions
                    BEGIN SELECT RAISE(ABORT, 'Source versions are immutable'); END''')
