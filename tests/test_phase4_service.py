import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook
from app import create_app
from database import Database
from phase4_store import Store, encode


def workbook(name='Sheet1'):
    book=Workbook(); book.active.title=name
    buffer=io.BytesIO(); book.save(buffer)
    return buffer.getvalue()


class Phase4ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'service.sqlite3'
        self.app=create_app(self.path,{'a':'owner','b':'other','r':'reviewer'},
                            enable_test_interface=True,test_admin_tokens={'admin':'administrator'},
                            test_session_users={'administrator':['owner','other','reviewer']},
                            reviewer_grants={'reviewer':['owner']})
        self.client=TestClient(self.app); self.addCleanup(self.client.close)
        self.headers={'Authorization':'Bearer a'}

    def upload(self, data=None, headers=None):
        response=self.client.post('/api/v1/workbooks',headers=headers or self.headers,
                                  files={'file':('book.xlsx',data or workbook())})
        self.assertEqual(response.status_code,202,response.text)
        ids=response.json(); base=f"/api/v1/workbooks/{ids['workbookId']}/versions/{ids['versionId']}"
        return ids,base

    def audit(self,ids,base,headers=None):
        response=self.client.get(base+'/audits/'+ids['auditId'],headers=headers or self.headers)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_new_version_reaudit_history_and_immutable_source(self):
        data=workbook(); ids,base=self.upload(data)
        first=self.audit(ids,base)
        self.assertEqual(first['rulesetVersion'],'2.0.0')
        self.assertEqual(first['status'],'REMEDIATION_AVAILABLE',first)
        source=self.client.get(base+'/source',headers=self.headers)
        self.assertEqual(source.content,data)
        for header in ('Content-Length','Content-Disposition','Cache-Control','X-Request-ID'):
            self.assertIn(header,source.headers)
        second=self.client.post('/api/v1/workbooks/'+ids['workbookId']+'/versions',headers=self.headers,
                                files={'file':('changed.xlsx',workbook('Budget'))})
        self.assertEqual(second.status_code,202,second.text)
        self.assertNotEqual(second.json()['versionId'],ids['versionId'])
        newaudit=self.client.post(base+'/audits',headers=self.headers,json={})
        self.assertEqual(newaudit.status_code,202,newaudit.text)
        self.assertEqual(self.audit(ids,base),first)
        history=self.client.get('/api/v1/workbooks/'+ids['workbookId']+'/history',headers=self.headers).json()
        self.assertEqual(len(history['versions']),2)
        self.assertEqual(len(history['audits']),3)

    def test_rename_remediation_review_report_and_idempotent_replay(self):
        ids,base=self.upload(); original=self.audit(ids,base)
        review=self.client.get(base+'/audits/'+ids['auditId']+'/review',headers=self.headers)
        self.assertEqual(review.status_code,200,review.text)
        item=next(i for i in review.json()['items'] if i['currentValue']=={'name':'Sheet1'})
        body={'auditId':ids['auditId'],'decisions':[{'findingId':item['findingId'],'action':'APPLY','value':{'name':'Financial overview'}}]}
        headers=dict(self.headers,**{'Idempotency-Key':'rename-request'})
        accepted=self.client.post(base+'/remediations',headers=headers,json=body)
        self.assertEqual(accepted.status_code,202,accepted.text)
        job=self.client.get('/api/v1/remediations/'+accepted.json()['remediationId'],headers=self.headers).json()
        self.assertEqual(job['status'],'REMEDIATED',job)
        output=self.client.get('/api/v1/outputs/'+job['outputId']+'/workbook',headers=self.headers)
        self.assertEqual(output.status_code,200,output.text)
        self.assertNotEqual(output.content,workbook())
        replay=self.client.post(base+'/remediations',headers=headers,json=body)
        self.assertEqual(replay.json(),accepted.json())
        changed={'auditId':ids['auditId'],'decisions':[{'findingId':item['findingId'],'action':'DECLINE'}]}
        self.assertEqual(self.client.post(base+'/remediations',headers=headers,json=changed).status_code,409)
        self.assertEqual(self.audit(ids,base),original)
        reporturl=f"/api/v1/workbooks/{ids['workbookId']}/versions/{job['outputVersionId']}/audits/{job['auditId']}/report"
        report=self.client.get(reporturl,headers=self.headers)
        self.assertEqual(report.status_code,200,report.text)
        self.assertEqual(report.content,self.client.get(reporturl,headers=self.headers).content)
        self.assertEqual(report.json()['approvedChanges'][0]['sourceAuditId'],ids['auditId'])
        self.assertEqual(report.json()['sha256'],hashlib.sha256(output.content).hexdigest())
        self.assertEqual(report.json()['checksPerformed'],['ALT_TEXT','WORKSHEET_NAME','TABLE_HEADER','MERGED_CELLS','LINK_TEXT','COLOR_CONTRAST'])

    def test_decline_only_output_is_an_identical_separate_version(self):
        data=workbook();ids,base=self.upload(data);a=self.audit(ids,base)
        body={'auditId':ids['auditId'],'decisions':[{'findingId':a['findings'][0]['findingId'],'action':'DECLINE'}]}
        accepted=self.client.post(base+'/remediations',headers=dict(self.headers,**{'Idempotency-Key':'decline'}),json=body)
        self.assertEqual(accepted.status_code,202,accepted.text)
        job=self.client.get('/api/v1/remediations/'+accepted.json()['remediationId'],headers=self.headers).json()
        self.assertEqual(job['status'],'REMEDIATED',job)
        self.assertNotEqual(job['outputVersionId'],ids['versionId'])
        self.assertEqual(self.client.get('/api/v1/outputs/'+job['outputId']+'/workbook',headers=self.headers).content,data)

    def test_all_four_correction_families_through_the_api(self):
        from test_remediation import build
        path=Path(self.temp.name)/'all-corrections.xlsx';build(path)
        data=path.read_bytes();ids,base=self.upload(data)
        audit=self.audit(ids,base)
        review=self.client.get(base+'/audits/'+ids['auditId']+'/review',headers=self.headers)
        self.assertEqual(review.status_code,200,review.text)
        items={i['findingId']:i for i in review.json()['items']}
        values={'ALT_TEXT':{'title':'Scores','description':"Bar chart of Ada's score."},
                'LINK_TEXT':{'text':'Annual report & summary'},'WORKSHEET_NAME':{'name':"Ada's Totals"}}
        decisions=[]
        for f in audit['findings']:
            if f['classification']=='REQUIRES_USER_INPUT':
                self.assertIn('APPLY',items[f['findingId']]['allowedActions'])
                decisions.append({'findingId':f['findingId'],'action':'APPLY',
                                  'value':values.get(f['ruleId'],items[f['findingId']]['currentValue'])})
        self.assertEqual({f['ruleId'] for f in audit['findings'] if f['classification']=='REQUIRES_USER_INPUT'},
                         {'ALT_TEXT','LINK_TEXT','TABLE_HEADER','WORKSHEET_NAME'})
        accepted=self.client.post(base+'/remediations',headers=dict(self.headers,**{'Idempotency-Key':'all-families'}),
                                  json={'auditId':ids['auditId'],'decisions':decisions})
        self.assertEqual(accepted.status_code,202,accepted.text)
        job=self.client.get('/api/v1/remediations/'+accepted.json()['remediationId'],headers=self.headers).json()
        self.assertEqual(job['status'],'REMEDIATED',job)
        output=self.client.get('/api/v1/outputs/'+job['outputId']+'/workbook',headers=self.headers)
        self.assertEqual(output.status_code,200,output.text)
        self.assertEqual(self.client.get(base+'/source',headers=self.headers).content,data)
        # Retain a candidate for an actual Excel-open check outside the container.
        evidence=Path(os.getenv('PHASE4_EVIDENCE_DIR','/tmp'))
        evidence.mkdir(parents=True,exist_ok=True)
        (evidence/'four-corrections-output.xlsx').write_bytes(output.content)

    def test_invalid_decisions_are_rejected_without_reserving_keys(self):
        ids,base=self.upload(); a=self.audit(ids,base); fid=a['findings'][0]['findingId']
        headers=dict(self.headers,**{'Idempotency-Key':'retry-after-invalid'})
        body={'auditId':ids['auditId'],'decisions':[{'findingId':fid,'action':'APPLY'}]}
        bad=self.client.post(base+'/remediations',headers=headers,json=body)
        self.assertEqual(bad.status_code,400,bad.text)
        self.assertEqual(bad.json()['code'],'MISSING_VALUE')
        body['decisions'][0]['value']={'name':'Sheet2'}
        bad=self.client.post(base+'/remediations',headers=headers,json=body)
        self.assertEqual(bad.status_code,422,bad.text)
        with self.app.state.database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM p4_keys').fetchone()[0],0)

    def test_auth_namespace_and_reviewer_access(self):
        ids,base=self.upload()
        self.assertEqual(self.client.get(base).status_code,401)
        self.assertEqual(self.client.get(base,headers={'Authorization':'Bearer b'}).status_code,403)
        self.assertEqual(self.client.get(base,headers={'Authorization':'Bearer admin'}).status_code,403)
        read={'Authorization':'Bearer r'}
        self.assertEqual(self.client.get(base,headers=read).status_code,200)
        review=self.client.get(base+'/audits/'+ids['auditId']+'/review',headers=read).json()
        self.assertTrue(all(i['allowedActions']==[] for i in review['items']))
        self.assertEqual(self.client.post(base+'/audits',headers=read,json={}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/health',headers={'X-Test-Session':'unknown'}).status_code,200)

    def test_isolated_fault_is_one_shot_and_cleanup_preserves_ordinary_uploads(self):
        ordinary,ordinarybase=self.upload()
        with patch.dict(os.environ,{'ENABLE_TEST_FAULTS':'true'}):
            response=self.client.post('/test/setup',headers={'Authorization':'Bearer admin'},
                                      json={'session_id':'fault-case','setup':{'faults':{'audit_failures':1}}})
        self.assertEqual(response.status_code,201,response.text)
        headers=dict(self.headers,**{'X-Test-Session':'fault-case'})
        ids,base=self.upload(headers=headers)
        failed=self.audit(ids,base,headers)
        self.assertEqual(failed['status'],'PROCESSING_FAILED')
        self.assertEqual(failed['error']['code'],'TEST_AUDIT_FAILURE')
        self.assertEqual(failed['error']['details'],{'stage':'audit','testOnly':True})
        self.assertEqual(self.client.get(base).status_code,401)
        self.assertEqual(self.client.get(base,headers=self.headers).status_code,404)
        report=self.client.get(base+'/audits/'+ids['auditId']+'/report',headers=headers).json()
        self.assertEqual(report['checksPerformed'],[])
        accepted=self.client.post(base+'/audits',headers=headers,json={})
        self.assertEqual(accepted.status_code,202,accepted.text)
        ids2=dict(ids,auditId=accepted.json()['auditId'])
        self.assertNotEqual(self.audit(ids2,base,headers)['status'],'PROCESSING_FAILED')
        cleanup=self.client.post('/test/setup',headers={'Authorization':'Bearer admin'},
                                 json={'session_id':'after-cleanup','setup':{'cleanup_session_ids':['unknown','fault-case']}})
        self.assertEqual(cleanup.status_code,201,cleanup.text)
        self.assertEqual(self.client.get(ordinarybase,headers=self.headers).status_code,200)

    def test_phase3_rows_are_migrated_without_relabeling_audits(self):
        path=Path(self.temp.name)/'legacy.sqlite3'; database=Database(path);database.initialize()
        data=workbook('Budget');digest=hashlib.sha256(data).hexdigest()
        with database.connect(write=True) as db:
            db.execute('INSERT INTO versions VALUES (?,?,?,?,?,?,?)',('old-wb','old-v','owner','old.xlsx',digest,'2026-10-18T00:00:00Z',data))
            db.execute('''INSERT INTO audits (audit_id,workbook_id,version_id,ruleset_version,status,started_at,completed_at,request_id)
                VALUES ('old-a','old-wb','old-v','1.0.0','AUDIT_COMPLETE','2026-10-18T00:00:00Z','2026-10-18T00:00:01Z','old-request')''')
        app=create_app(path,{'a':'owner'})
        with TestClient(app) as client:
            response=client.get('/api/v1/workbooks/old-wb/versions/old-v/audits/old-a',headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['rulesetVersion'],'1.0.0')
            self.assertEqual(client.get('/api/v1/workbooks/old-wb/versions/old-v/source',headers=self.headers).content,data)


if __name__=='__main__':
    unittest.main()
