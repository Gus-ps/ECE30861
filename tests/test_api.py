from contextlib import closing, redirect_stdout
import hashlib
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app, load_workbook_validator, MAX_UPLOAD
from contracts import Audit, Error, UploadResponse, WorkbookVersion


def workbook(extra=None):
    buffer = io.BytesIO()
    parts = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="core" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>',
        'docProps/core.xml': '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Budget</dc:title></cp:coreProperties>',
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
        self.application = create_app(self.db, self.tokens, accessibility_checker=lambda path: [])
        self.client = TestClient(self.application)
        self.auth = {'Authorization': 'Bearer alice-token'}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def upload(self, data=None, filename='budget.xlsx', client=None):
        return (client or self.client).post('/api/v1/workbooks', headers=self.auth,
            files={'file': (filename, workbook() if data is None else data)})

    def audit_url(self, ids):
        return f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}/audits/{ids['auditId']}"

    def counts(self):
        with closing(sqlite3.connect(self.db)) as db:
            return tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                         for table in ('versions', 'audits'))

    def test_health_auth_and_error_shape(self):
        self.assertEqual(self.client.get('/api/v1/health').json(),
                         {'status': 'AVAILABLE', 'apiVersion': '1.0', 'rulesetVersion': '1.0.0'})
        for headers in ({}, {'Authorization': 'Bearer wrong'}):
            response = self.client.post('/api/v1/workbooks', headers=headers, files={'file': ('a.xlsx', workbook())})
            self.assertEqual(response.status_code, 401)
            Error.model_validate(response.json())
            self.assertEqual(set(response.json()), {'code', 'message', 'requestId', 'details'})
        self.assertEqual(self.client.post('/api/v1/workbooks', headers=self.auth).status_code, 400)
        self.assertEqual(self.counts(), (0, 0))

    def test_upload_contract_metadata_persistence_and_immutable_source(self):
        data = workbook()
        response = self.upload(data)
        self.assertEqual(response.status_code, 202, response.text)
        ids = UploadResponse.model_validate(response.json()).model_dump()
        self.assertEqual(set(response.json()), {'workbookId', 'versionId', 'auditId', 'status'})
        self.assertEqual(ids['status'], 'PROCESSING')
        base = self.audit_url(ids).split('/audits/')[0]
        metadata_response = self.client.get(base, headers=self.auth)
        metadata = WorkbookVersion.model_validate(metadata_response.json())
        self.assertEqual(metadata.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(metadata.latestAuditId, ids['auditId'])
        self.assertIsNone(metadata.sourceVersionId)
        self.assertEqual(metadata.status, 'AUDIT_COMPLETE')
        self.assertEqual(self.client.get(base + '/original', headers=self.auth).content, data)
        with TestClient(create_app(self.db, self.tokens)) as restarted:
            self.assertEqual(restarted.get(base + '/original', headers=self.auth).content, data)
        with closing(sqlite3.connect(self.db)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE versions SET original=X'00'")
        self.assertEqual(self.counts(), (1, 1))



    def test_access_control_and_identifiers(self):
        ids = self.upload().json()
        audit = self.audit_url(ids)
        base = audit.split('/audits/')[0]
        for path in (base, base + '/original', audit):
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer bob-token'}).status_code, 403)
        self.assertEqual(self.client.post(audit.rsplit('/', 1)[0], headers=self.auth).status_code, 404)
        self.assertEqual(self.client.get(audit.rsplit('/', 1)[0] + '/missing', headers=self.auth).status_code, 404)
        self.assertEqual(self.client.get(base.replace(ids['versionId'], 'x' * 65), headers=self.auth).status_code, 400)
        other = self.upload().json()
        self.assertEqual(self.client.get(audit.rsplit('/', 1)[0] + '/' + other['auditId'], headers=self.auth).status_code, 404)

    def test_rejections_leave_no_records(self):
        cases = [(b'bad', 'a.xls', 415), (b'bad', 'a.xlsx', 422),
                 (b'x' * (25_000_000 + 1), 'a.xlsx', 413),
                 (workbook(), 'a' * 251 + '.xlsx', 400),
                 (workbook({'xl/worksheets/sheet1.xml': '<broken'}), 'a.xlsx', 422),
                 (workbook({'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><workbookProtection lockStructure="1"/></workbook>'}), 'a.xlsx', 422)]
        for data, filename, status in cases:
            with self.subTest(filename=filename, status=status):
                response = self.upload(data, filename)
                self.assertEqual(response.status_code, status, response.text)
                Error.model_validate(response.json())
                if status == 422:
                    self.assertTrue(response.json()['details']['errors'])
                self.assertEqual(response.headers['X-Request-ID'], response.json()['requestId'])
        self.assertEqual(self.counts(), (0, 0))

    def test_exact_decimal_size_boundary_is_accepted(self):
        empty_padding = workbook({'padding.bin': b''})
        data = workbook({'padding.bin': b'x' * (25_000_000 - len(empty_padding))})
        self.assertEqual(MAX_UPLOAD, 25_000_000)
        self.assertEqual(len(data), MAX_UPLOAD)
        response = self.upload(data)
        self.assertEqual(response.status_code, 202, response.text)

    def test_non_zip_upload_reaches_validity_checker(self):
        received = []

        def validator(filepath):
            received.append(Path(filepath).read_bytes())
            return False

        with TestClient(create_app(self.db, self.tokens, workbook_validator=validator)) as client:
            response = self.upload(b'not a zip archive', client=client)
        self.assertEqual(received, [b'not a zip archive'])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['details'], {'valid': False})
        self.assertEqual(self.counts(), (0, 0))



    def test_bad_checker_output_is_a_controlled_audit_failure(self):
        def invalid_checker(path):
            return [{'findingId': 'bad', 'ruleId': 'ALT_TEXT', 'category': 'NOT_A_CATEGORY'}]
        with TestClient(create_app(self.db, self.tokens, accessibility_checker=invalid_checker)) as client:
            with self.assertLogs(level='ERROR'):
                response = self.upload(client=client)
            self.assertEqual(response.status_code, 202)
            audit = Audit.model_validate(client.get(self.audit_url(response.json()), headers=self.auth).json())
            self.assertEqual(audit.status, 'PROCESSING_FAILED')
            self.assertEqual(audit.findings, [])
            self.assertEqual(audit.error.code, 'AUDIT_FAILED')
            self.assertEqual(audit.error.requestId, response.headers['X-Request-ID'])
        self.assertEqual(self.counts(), (1, 1))

    def test_audit_storage_failure_rolls_back_upload(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audits BEGIN SELECT RAISE(ABORT, 'storage failure'); END")
            db.commit()
        with self.assertLogs(level='ERROR'):
            response = self.upload()
        self.assertEqual(response.status_code, 500)
        Error.model_validate(response.json())
        self.assertEqual(self.counts(), (0, 0))

    def test_validator_contract_and_temporary_path_cleanup(self):
        for result, status in ((True, 202), (1, 202), (False, 422), (0, 422), ([], 500), ('1', 500), (None, 500)):
            paths = []
            def validator(filepath):
                path = Path(filepath)
                self.assertTrue(path.is_absolute())
                self.assertEqual(path.read_bytes(), workbook())
                paths.append(path)
                return result
            with self.subTest(result=result):
                with TestClient(create_app(self.db, self.tokens, workbook_validator=validator)) as client:
                    response = self.upload(client=client)
                    self.assertEqual(response.status_code, status, response.text)
                self.assertFalse(paths[0].exists())

    def test_checker_prints_are_visible_without_changing_boolean_result(self):
        path = Path(self.tmp.name) / 'sample.xlsx'
        path.write_bytes(workbook())
        checker = load_workbook_validator()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIs(checker(str(path)), True)
        self.assertIn('is valid and ready', output.getvalue())

    def test_unconfigured_validator_is_unavailable(self):
        with patch('app.load_workbook_validator', return_value=None):
            with TestClient(create_app(self.db, self.tokens)) as client:
                response = self.upload(client=client)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.counts(), (0, 0))

    def test_audit_endpoint_reports_unconfigured_checker(self):
        with patch('app.check_workbook', None):
            with TestClient(create_app(self.db, self.tokens)) as client:
                response = self.upload(client=client)
                self.assertEqual(response.status_code, 202)
                audit = Audit.model_validate(client.get(self.audit_url(response.json()), headers=self.auth).json())
        self.assertEqual(audit.status, 'PROCESSING_FAILED')
        self.assertEqual(audit.error.code, 'CHECKER_NOT_CONFIGURED')

    def test_haruki_runner_is_connected_by_default(self):
        with TestClient(create_app(self.db, self.tokens)) as client:
            ids = self.upload(client=client).json()
            audit = Audit.model_validate(client.get(self.audit_url(ids), headers=self.auth).json())
            self.assertEqual(audit.status, 'REVIEW_REQUIRED')
            self.assertEqual([finding.ruleId for finding in audit.findings], ['WORKSHEET_NAME'])
            no_title = workbook({'docProps/core.xml': '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>'})
            ids = self.upload(no_title, client=client).json()
            audit = Audit.model_validate(client.get(self.audit_url(ids), headers=self.auth).json())
            self.assertIsNone(audit.error)
            self.assertEqual([finding.ruleId for finding in audit.findings], ['WORKSHEET_NAME'])
            self.assertFalse(any('WORKBOOK_TITLE' in limitation for limitation in audit.limitations))

    def test_checker_hook_returns_schema_valid_sorted_findings(self):
        from app import process_audit

        def checker(filepath):
            self.assertTrue(Path(filepath).is_file())
            return [
                {'findingId': 'prototype-' + rule, 'ruleId': rule, 'category': category,
                 'worksheet': 'Sheet1', 'target': target, 'classification': 'REQUIRES_USER_INPUT',
                 'message': message, 'recommendation': 'Provide a description.'}
                for rule, category, target, message in [
                    ('WORKSHEET_NAME', 'WORKSHEET_NAME', 'Sheet1', 'Default worksheet name.'),
                    ('ALT_TEXT', 'NON_TEXT_CONTENT', 'Image1', 'Missing alternative text.'),
                ]
            ]

        application = create_app(self.db, self.tokens, accessibility_checker=checker)
        with TestClient(application) as client:
            response = self.upload(client=client)
            ids = response.json()
            first = Audit.model_validate(client.get(self.audit_url(ids), headers=self.auth).json())
            self.assertEqual(first.status, 'REVIEW_REQUIRED')
            self.assertEqual([finding.ruleId for finding in first.findings], ['ALT_TEXT', 'WORKSHEET_NAME'])
            process_audit(application.state.database, ids['auditId'], checker)
            second = Audit.model_validate(client.get(self.audit_url(ids), headers=self.auth).json())
            self.assertEqual(second.findings, first.findings)



if __name__ == '__main__':
    unittest.main()
