"""Contract regressions derived from the retained November 1 cross-team reports."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import warnings
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from fastapi.testclient import TestClient
from app import create_app
from accessibility_checker.runner import check_workbook
from remediation import validate_decisions, RemediationError

FIXTURES=Path(__file__).parent/'fixtures/deployment'
EXPECTED=json.loads((FIXTURES/'expectations.json').read_text(encoding='utf-8'))


def rewrite(data, name, change):
    out=io.BytesIO()
    with ZipFile(io.BytesIO(data)) as source, ZipFile(out,'w') as target:
        for item in source.infolist():
            contents=source.read(item)
            if item.filename==name:contents=change(contents)
            target.writestr(item,contents)
    return out.getvalue()


class DeploymentRegressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=create_app(Path(self.temp.name)/'data.sqlite3',{'token':'owner'})
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.headers={'Authorization':'Bearer token'}

    def upload(self,data):
        return self.client.post('/api/v1/workbooks',headers=self.headers,files={'file':('case.xlsx',data)})

    def test_reported_semantic_mismatches_against_independent_fixture_rows(self):
        for key,expected in EXPECTED.items():
            with self.subTest(fixture=key):
                path=FIXTURES/expected['file'];digest=hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(digest,expected['sha256'])
                actual=check_workbook(path)
                keys=('ruleId','category','worksheet','target','classification')
                self.assertEqual([{k:f[k] for k in keys} for f in actual],expected['findings'])
                for finding in actual:
                    identity=[digest,'2.0.0',finding['ruleId'],finding['worksheet'],finding['target']]
                    independently_calculated=hashlib.sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                    self.assertEqual(finding['findingId'],independently_calculated)
                if key=='unicode':self.assertEqual(actual.limitations,[])

    def test_unsafe_packages_rejected_atomically_after_validity_check(self):
        original=(FIXTURES/'seeded_all_six.xlsx').read_bytes()
        for kind in ('traversal','duplicate','dtd','macro'):
            with self.subTest(kind=kind):
                out=io.BytesIO(original)
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',UserWarning)
                    with ZipFile(out,'a') as archive:
                        if kind=='traversal':archive.writestr('../outside.xml','<outside/>')
                        elif kind=='duplicate':archive.writestr('xl/workbook.xml',archive.read('xl/workbook.xml'))
                        elif kind=='dtd':archive.writestr('custom.xml','<!DOCTYPE sample [<!ENTITY x "value">]><sample/>')
                        else:archive.writestr('xl/vbaProject.bin',b'never execute')
                response=self.upload(out.getvalue())
                self.assertEqual(response.status_code,422,response.text)
        with self.app.state.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM p4_resources').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM p4_jobs').fetchone()[0],0)

    def test_null_value_and_collision_have_contract_error_codes(self):
        response=self.upload((FIXTURES/'rename_references.xlsx').read_bytes())
        self.assertEqual(response.status_code,202,response.text)
        ids=response.json();base=f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}"
        audit=self.client.get(base+'/audits/'+ids['auditId'],headers=self.headers).json()
        finding=next(f for f in audit['findings'] if f['ruleId']=='WORKSHEET_NAME')
        for value,code in ((None,'INVALID_CORRECTION'),({'name':'summary'},'CONFLICTING_CORRECTIONS'),({'name':' Costs'},'INVALID_CORRECTION')):
            body={'auditId':ids['auditId'],'decisions':[{'findingId':finding['findingId'],'action':'APPLY','value':value}]}
            rejected=self.client.post(base+'/remediations',headers=dict(self.headers,**{'Idempotency-Key':'invalid-case'}),json=body)
            self.assertEqual(rejected.status_code,422,rejected.text)
            self.assertEqual(rejected.json()['code'],code)

    def test_unrecognized_extension_and_overlapping_drawing_remain_manual(self):
        original=(FIXTURES/'seeded_all_six.xlsx').read_bytes()
        def move_anchor(data):
            root=ET.fromstring(data)
            root.find('{*}twoCellAnchor/{*}from/{*}col').text='0'
            return ET.tostring(root)
        overlapping=rewrite(original,'xl/drawings/drawing1.xml',move_anchor)
        path=Path(self.temp.name)/'overlap.xlsx';path.write_bytes(overlapping)
        rows=check_workbook(path)
        # A genuine overlap must not inherit the disjoint-drawing exemption.
        headers=[f for f in rows if f['target']=='xl/worksheets/sheet1.xml#range=A1:C4']
        self.assertEqual(headers[0]['classification'],'MANUAL_REVIEW')
        changed=rewrite(original,'xl/drawings/drawing1.xml',lambda data:data.replace(b'{C183D7F6-B498-43B3-948B-1728B52AA6E4}',b'{UNKNOWN-EXTENSION}'))
        path.write_bytes(changed)
        self.assertTrue(any(f['ruleId']=='WORKSHEET_NAME' and f['classification']=='MANUAL_REVIEW' for f in check_workbook(path)))

    def test_in_cell_metadata_inside_candidate_stays_manual(self):
        original=(FIXTURES/'seeded_all_six.xlsx').read_bytes()
        def attach(data):
            root=ET.fromstring(data)
            cell=next(c for c in root.iter() if c.tag.endswith('}c') and c.get('r')=='B2')
            cell.set('vm','1')
            return ET.tostring(root)
        path=Path(self.temp.name)/'cell-image.xlsx'
        path.write_bytes(rewrite(original,'xl/worksheets/sheet1.xml',attach))
        findings=check_workbook(path)
        header=next(f for f in findings if f['ruleId']=='TABLE_HEADER' and '#range=A1:C4' in f['target'])
        self.assertEqual(header['classification'],'MANUAL_REVIEW')
        self.assertTrue(any('In-cell image' in line for line in findings.limitations))


if __name__=='__main__':unittest.main()
