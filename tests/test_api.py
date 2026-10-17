import hashlib
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from contextlib import closing, redirect_stdout

from fastapi.testclient import TestClient
from app import create_app, load_workbook_validator


def workbook(extra=None):
    buffer = io.BytesIO()
    parts = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>',
    }
    parts.update(extra or {})
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'test.sqlite3'
        self.tokens = {'alice-token': 'alice', 'bob-token': 'bob'}
        self.client = TestClient(create_app(self.db, self.tokens, workbook_validator=lambda path: 1))
        self.auth = {'Authorization': 'Bearer alice-token'}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def upload(self, data=None, filename='budget.xlsx'):
        return self.client.post('/api/v1/workbooks', headers=self.auth,
                                files={'file': (filename, workbook() if data is None else data)})

    def test_checker_prints_are_visible_without_changing_boolean_result(self):
        path = Path(self.tmp.name) / 'sample.xlsx'
        path.write_bytes(workbook())
        checker = load_workbook_validator()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIs(checker(str(path)), True)
        self.assertIn('is valid and ready', output.getvalue())
        path.write_bytes(workbook({'xl/workbook.xml':
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><workbookProtection lockStructure="1"/></workbook>'}))
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIs(checker(str(path)), False)
        self.assertIn('is invalid', output.getvalue())
        self.assertIn('workbook structure is protected', output.getvalue())

    def test_health_auth_and_error_shape(self):
        self.assertEqual(self.client.get('/api/v1/health').json()['status'], 'AVAILABLE')
        for headers in ({}, {'Authorization': 'Bearer wrong'}):
            response = self.client.post('/api/v1/workbooks', headers=headers, files={'file': ('a.xlsx', workbook())})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(set(response.json()), {'code', 'message', 'requestId', 'details'})
        self.assertEqual(self.client.post('/api/v1/workbooks', headers=self.auth).status_code, 400)

    def test_valid_workbook_persistence_download_and_access(self):
        data = workbook()
        response = self.upload(data)
        self.assertEqual(response.status_code, 200, response.text)
        ids = response.json()
        self.assertIs(ids['valid'], True)
        self.assertNotIn('auditId', ids)
        base = f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}"
        metadata = self.client.get(base, headers=self.auth).json()
        self.assertEqual(metadata['sha256'], hashlib.sha256(data).hexdigest())
        self.assertTrue(metadata['createdAt'].endswith('Z'))
        self.assertEqual(self.client.get(base + '/original', headers=self.auth).content, data)
        for path in (base, base + '/original'):
            self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer bob-token'}).status_code, 403)
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(base + '/audits/missing', headers=self.auth).status_code, 404)
        with TestClient(create_app(self.db, self.tokens)) as restarted:
            self.assertEqual(restarted.get(base + '/original', headers=self.auth).content, data)
        with closing(sqlite3.connect(self.db)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE versions SET original=X'00'")

    def test_rejections_leave_no_records(self):
        cases = [
            (b'bad', 'a.xls', 415), (b'bad', 'a.xlsx', 422),
            (workbook({'xl/vbaProject.bin': b'macro'}), 'a.xlsx', 422),
            (b'x' * (25 * 1024 * 1024 + 1), 'a.xlsx', 413),
        ]
        for data, filename, status in cases:
            with self.subTest(filename=filename, status=status):
                response = self.upload(data, filename)
                self.assertEqual(response.status_code, status, response.text)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audits').fetchone()[0], 0)

    def test_validator_integration_rejects_before_storage(self):
        calls = []

        def validator(filepath):
            self.assertIsInstance(filepath, str)
            path = Path(filepath)
            self.assertEqual(path.suffix, '.xlsx')
            calls.append((path.read_bytes(), path))
            return 0

        with TestClient(create_app(self.db, self.tokens, workbook_validator=validator)) as client:
            data = workbook()
            response = client.post('/api/v1/workbooks', headers=self.auth,
                                   files={'file': ('budget.xlsx', data)})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()['details'], {
                'valid': False})
            self.assertEqual(calls[0][0], data)
            self.assertFalse(calls[0][1].exists())
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 0)

    def test_path_validator_accepts_and_cleans_up_after_failure(self):
        paths = []

        def validator(filepath):
            paths.append(Path(filepath))
            return True

        with TestClient(create_app(self.db, self.tokens, workbook_validator=validator)) as client:
            response = client.post('/api/v1/workbooks', headers=self.auth,
                                   files={'file': ('budget.xlsx', workbook())})
            self.assertEqual(response.status_code, 200)
        self.assertFalse(paths[0].exists())

        def failing_validator(filepath):
            paths.append(Path(filepath))
            raise OSError('Validator unavailable')

        with TestClient(create_app(self.db, self.tokens, workbook_validator=failing_validator)) as client:
            with self.assertLogs(level='ERROR'):
                response = client.post('/api/v1/workbooks', headers=self.auth,
                                       files={'file': ('budget.xlsx', workbook())})
            self.assertEqual(response.status_code, 500)
        self.assertFalse(paths[1].exists())
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 1)

    def test_unconfigured_validator_does_not_claim_validity_or_save(self):
        with patch('app.load_workbook_validator', return_value=None):
            with TestClient(create_app(self.db, self.tokens)) as client:
                response = client.post('/api/v1/workbooks', headers=self.auth,
                                       files={'file': ('budget.xlsx', workbook())})
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(response.json()['details']['valid'])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 0)

    def test_boolean_false_and_invalid_return_types(self):
        for value, expected_status in ((False, 422), ([], 500), (['error'], 500), ('1', 500), (2, 500), (None, 500)):
            with self.subTest(value=value):
                with TestClient(create_app(self.db, self.tokens, workbook_validator=lambda path: value)) as client:
                    response = client.post('/api/v1/workbooks', headers=self.auth,
                                           files={'file': ('budget.xlsx', workbook())})
                    self.assertEqual(response.status_code, expected_status)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audits').fetchone()[0], 0)

    def test_retained_audit_endpoint_is_separate_from_validation(self):
        ids = self.upload().json()
        base = f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}"
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audits').fetchone()[0], 0)
            db.execute('INSERT INTO audits (audit_id, workbook_id, status, started_at) VALUES (?, ?, ?, ?)',
                       ('future-audit', ids['workbookId'], 'AUDIT_COMPLETE', '2026-10-16T00:00:00Z'))
            db.commit()
        path = base + '/audits/future-audit'
        response = self.client.get(path, headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'AUDIT_COMPLETE')
        self.assertEqual(response.json()['findings'], [])
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer bob-token'}).status_code, 403)

    def test_real_validator_valid_and_invalid_workbooks(self):
        invalid = [
            {'xl/worksheets/sheet1.xml': '<broken'},
            {'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><workbookProtection lockStructure="1"/></workbook>'},
            {'xl/worksheets/sheet1.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetProtection sheet="1"/></worksheet>'},
        ]
        with TestClient(create_app(self.db, self.tokens)) as client:
            for parts in invalid:
                with self.subTest(parts=parts):
                    response = client.post('/api/v1/workbooks', headers=self.auth,
                                           files={'file': ('invalid.xlsx', workbook(parts))})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIs(response.json()['details']['valid'], False)
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 0)
            data = workbook()
            response = client.post('/api/v1/workbooks', headers=self.auth,
                                   files={'file': ('valid.xlsx', data)})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIs(response.json()['valid'], True)
            ids = response.json()
            original = client.get(f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}/original", headers=self.auth)
            self.assertEqual(original.content, data)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audits').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
