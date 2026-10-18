"""Observable HTTP checks for the October 18 pod alignment decisions."""
from contextlib import closing
import hashlib
import io
import warnings
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app
from test_api import workbook
import test_image_alt_text as image_fixtures
from test_image_alt_text import MAIN, DOC, XDR


class PodAlignmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'test.sqlite3'
        self.client = TestClient(create_app(self.path, {'test-token': 'test-user'}))
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': 'Bearer test-token'}

    def upload(self, content, name='book.xlsx'):
        return self.client.post('/api/v1/workbooks', headers=self.headers,
                                files={'file': (name, content)})

    def audit(self, ids):
        base = f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}"
        return self.client.get(f"{base}/audits/{ids['auditId']}", headers=self.headers).json()

    def test_background_picture_returns_manual_review_through_api(self):
        data = workbook({
            'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{MAIN}" xmlns:r="{DOC}"><sheetData/><picture r:id="bg"/></worksheet>',
            'xl/worksheets/_rels/sheet1.xml.rels': f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="bg" Type="{DOC}/image" Target="../media/background.png"/></Relationships>',
            'xl/media/background.png': b'background image',
        })
        response = self.upload(data)
        self.assertEqual(response.status_code, 202, response.text)
        result = self.audit(response.json())
        self.assertEqual(result['status'], 'REVIEW_REQUIRED', result)
        self.assertIsNone(result['error'])
        backgrounds = [f for f in result['findings'] if '/picture[1]' in f['target']]
        self.assertEqual(len(backgrounds), 1)
        self.assertEqual(backgrounds[0]['classification'], 'MANUAL_REVIEW')

    def test_unsafe_zip_and_xml_rejected_before_creating_resources(self):
        cases = [workbook({'../outside.xml': '<outside/>'}),
                 workbook({'xl/worksheets/sheet1.xml':
                           '<!DOCTYPE worksheet [<!ENTITY test "hello">]><worksheet/>'})]
        buffer = io.BytesIO(workbook())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(buffer, 'a') as archive:
                archive.writestr('xl/workbook.xml', '<workbook/>')
        cases.append(buffer.getvalue())
        for data in cases:
            with self.subTest(size=len(data)):
                response = self.upload(data)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()['code'], 'INVALID_WORKBOOK')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 0)

    def test_macro_extension_and_renamed_macro_packages_rejected_atomically(self):
        cases = [
            ('book.xlsm', workbook()),
            ('book.xlsx', workbook({'xl/vbaProject.bin': b'vba'})),
            ('book.xlsx', workbook({'xl/macrosheets/sheet1.xml': '<macrosheet/>'})),
            ('book.xlsx', workbook({'[Content_Types].xml': '<Types><Override ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/></Types>'})),
        ]
        for name, data in cases:
            with self.subTest(name=name):
                response = self.upload(data, name)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(set(response.json()), {'code', 'message', 'requestId', 'details'})
                self.assertEqual(response.headers['X-Request-ID'], response.json()['requestId'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM versions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audits').fetchone()[0], 0)

    def test_chartsheet_names_are_audited_and_version_is_semantic(self):
        data = workbook({
            'xl/workbook.xml': f'<workbook xmlns="{MAIN}" xmlns:r="{DOC}"><sheets><sheet name="Sheet3" sheetId="3" r:id="chart"/></sheets></workbook>',
            'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="chart" Type="{DOC}/chartsheet" Target="chartsheets/sheet3.xml"/></Relationships>',
            'xl/chartsheets/sheet3.xml': f'<chartsheet xmlns="{MAIN}"/>',
        })
        response = self.upload(data)
        self.assertEqual(response.status_code, 202, response.text)
        result = self.audit(response.json())
        self.assertEqual(result['rulesetVersion'], '1.0.0')
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertEqual([(f['ruleId'], f['worksheet'], f['target']) for f in result['findings']],
                         [('WORKSHEET_NAME', 'Sheet3', 'xl/chartsheets/sheet3.xml#sheetId=3')])

    def test_ambiguous_object_keeps_other_findings_with_stable_fallback_locations(self):
        fixture = image_fixtures.ImageAltTextTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.write_metadata([('Sheet1', None, [{}, {}, {'decorative': 'true'}])])

        def missing_id(root):
            del list(root.iter(f'{{{XDR}}}cNvPr'))[1].attrib['id']

        fixture.rewrite_part('xl/drawings/drawing90.xml', missing_id)
        with ZipFile(fixture.path, 'a') as archive:
            archive.writestr('[Content_Types].xml', '<Types/>')
        data = fixture.path.read_bytes()
        response = self.upload(data)
        self.assertEqual(response.status_code, 202, response.text)
        ids = response.json()
        result = self.audit(ids)
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['findings']), 4)
        self.assertTrue(result['limitations'])
        self.assertTrue(any('#xml=' in f['target'] and f['classification'] == 'MANUAL_REVIEW'
                            for f in result['findings']))
        second = self.audit(self.upload(data).json())
        self.assertEqual(result['findings'], second['findings'])
        base = f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}"
        metadata = self.client.get(base, headers=self.headers).json()
        self.assertEqual(metadata['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(self.client.get(base + '/original', headers=self.headers).content, data)

    def test_image_formula_is_manual_review_and_does_not_fail_audit(self):
        response = self.upload(workbook({'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{MAIN}"><sheetData><row r="1"><c r="A1"><f>_xlfn.IMAGE("https://example.invalid/image.png")</f></c></row></sheetData></worksheet>'}))
        self.assertEqual(response.status_code, 202, response.text)
        result = self.audit(response.json())
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertTrue(any(f['ruleId'] == 'ALT_TEXT' and f['classification'] == 'MANUAL_REVIEW'
                            for f in result['findings']))
        self.assertIsNone(result['error'])

    def test_health_is_unavailable_without_processing_dependency(self):
        with patch('app.load_workbook_validator', return_value=None):
            with TestClient(create_app(self.path, {'test-token': 'test-user'})) as client:
                self.assertEqual(client.get('/api/v1/health').status_code, 503)
