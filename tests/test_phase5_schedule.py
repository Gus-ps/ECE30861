"""REQ-12 / AC-12 / AC-15: P5-SCHEDULE-* and P5-ACCESS-* configuration.

No WCAG checker or scheduling dispatcher is implemented by this module.
"""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import test_phase4_service as phase4
from test_phase4_service import workbook


class ScheduleTests(unittest.TestCase):
    setUp = phase4.Phase4ServiceTests.setUp
    upload = phase4.Phase4ServiceTests.upload

    def resource(self):
        ids, base = self.upload()
        return ids, base, '/api/v1/workbooks/'+ids['workbookId']+'/schedule'

    def assert_error(self, response, status):
        self.assertEqual(response.status_code,status,response.text)
        self.assertEqual(set(response.json()),{'code','message','requestId','details'})
        self.assertEqual(response.headers['X-Request-ID'],response.json()['requestId'])

    def test_invalid_workbook_identifiers(self):
        for identifier in ('a'*65, 'invalid!id'):
            path='/api/v1/workbooks/'+identifier+'/schedule'
            for method in ('get', 'put'):
                with self.subTest(identifier=identifier, method=method):
                    kwargs={'json': {'enabled':False}} if method == 'put' else {}
                    response=getattr(self.client,method)(path,headers=self.headers,**kwargs)
                    self.assert_error(response,400)
                    self.assertEqual(response.json()['code'],'INVALID_REQUEST')

    def test_unknown_test_session(self):
        ids,base,path=self.resource()
        headers=dict(self.headers,**{'X-Test-Session':'nonexistent'})
        for method in ('get', 'put'):
            with self.subTest(method=method):
                kwargs={'json': {'enabled':False}} if method == 'put' else {}
                response=getattr(self.client,method)(path,headers=headers,**kwargs)
                self.assert_error(response,400)
                self.assertEqual(response.json()['code'],'INVALID_TEST_SESSION')

    def test_schedule_response_wire_contract(self):
        # phase5-wire-schemas.json $defs.ScheduleResponse: all seven keys are
        # required, additionalProperties=false, reminderDays is constant, and
        # disabled schedules require a null nextAuditAt.
        ids,base,path=self.resource()
        expected=dict(workbookId=ids['workbookId'],enabled=False,
            intervalDays=None,complianceDeadline=None,versionId=ids['versionId'],
            nextAuditAt=None,reminderDays=[90,30,7])
        response=self.client.get(path,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),expected)
        for body,due in [
            ({'enabled':True,'intervalDays':30,'complianceDeadline':'2027-12-31'},
             '2027-01-31T00:00:00Z'),
            ({'enabled':False,'intervalDays':30},None),
        ]:
            with self.subTest(body=body):
                with patch('phase5_schedule.effective_now',
                           return_value=datetime(2027,1,1,tzinfo=timezone.utc)):
                    response=self.client.put(path,headers=self.headers,json=body)
                expected.update(body,nextAuditAt=due,
                                complianceDeadline=body.get('complianceDeadline'))
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json(),expected)
                response=self.client.get(path,headers=self.headers)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json(),expected)

    def test_invalid_vectors_preserve_state(self):
        ids, base, path = self.resource()
        original=self.client.put(path,headers=self.headers,json={'enabled':True,'intervalDays':30}).json()
        invalid=[
            '{"enabled":true,"intervalDays":'+v+'}' for v in ['0','91','true','"30"','1.0','1e0','null','NaN','Infinity']
        ]+['{}','{"enabled":true,"intervalDays":1,"x":1}',
           '{"enabled":false,"enabled":true}', '{"enabled":1}', '[]']
        invalid += [json.dumps(dict(enabled=False,complianceDeadline=v))
                    for v in ['2027-02-30','2027-1-1','20270101','0000-01-01']]
        invalid.append(b'{"enabled":false,"x":"\xff"}')
        for body in invalid:
            with self.subTest(body=body):
                response=self.client.put(path,headers=self.headers,content=body)
                self.assert_error(response,400)
                self.assertEqual(response.json()['code'],'INVALID_REQUEST')
                self.assertEqual(self.client.get(path,headers=self.headers).json(),original)

    def test_due_replacement_and_overflow(self):
        ids, base, path = self.resource()
        def put(body, year=2027, month=1, day=1):
            with patch('phase5_schedule.effective_now',
                       return_value=datetime(year,month,day,tzinfo=timezone.utc)):
                return self.client.put(path,headers=self.headers,json=body)
        body=dict(enabled=True,intervalDays=90)
        self.assertEqual(put(body).json()['nextAuditAt'],'2027-04-01T00:00:00Z')
        self.assertEqual(put(body,2027,2,1).json()['nextAuditAt'],'2027-04-01T00:00:00Z')
        self.assertEqual(put(dict(body,complianceDeadline='2028-01-01'),2027,2,1).json()['nextAuditAt'],'2027-04-01T00:00:00Z')
        self.assertEqual(put(dict(enabled=True,intervalDays=1)).json()['nextAuditAt'],'2027-01-02T00:00:00Z')
        disabled=put({'enabled':False}).json()
        self.assertIsNone(disabled['nextAuditAt'])
        self.assertIsNone(disabled['intervalDays'])
        self.assertEqual(put(body,2028).json()['nextAuditAt'],'2028-03-31T00:00:00Z')
        before=self.client.get(path,headers=self.headers).json()
        response=put(dict(enabled=True,intervalDays=89),9999,12,31)
        self.assert_error(response,400)
        self.assertEqual(response.json()['code'],'TIME_RANGE_EXCEEDED')
        self.assertEqual(self.client.get(path,headers=self.headers).json(),before)

    def test_default_latest_and_access(self):
        ids,base,path=self.resource()
        with self.app.state.store.connect() as db:
            before=db.execute('SELECT count(*) n FROM p5_schedules').fetchone()['n']
        response=self.client.get(path,headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),dict(workbookId=ids['workbookId'],enabled=False,
            intervalDays=None,complianceDeadline=None,versionId=ids['versionId'],
            nextAuditAt=None,reminderDays=[90,30,7]))
        with self.app.state.store.connect() as db:
            self.assertEqual(before,db.execute('SELECT count(*) n FROM p5_schedules').fetchone()['n'])
        second=self.client.post('/api/v1/workbooks/'+ids['workbookId']+'/versions',
            headers=self.headers,files={'file':('second.xlsx',workbook('Budget'))}).json()
        self.assertEqual(self.client.get(path,headers=self.headers).json()['versionId'],second['versionId'])
        self.client.post(base+'/audits',headers=self.headers,json={})
        self.assertEqual(self.client.get(path,headers=self.headers).json()['versionId'],second['versionId'])
        for token,status in [('r',200),('b',403),('admin',403),('',401)]:
            headers={'Authorization':'Bearer '+token} if token else {}
            self.assertEqual(self.client.get(path,headers=headers).status_code,status)
            self.assert_error(self.client.put(path,headers=headers,content='!'),403 if token else 401)
        self.assert_error(self.client.get('/api/v1/workbooks/missing/schedule',headers=self.headers),404)
        schema=self.client.get('/openapi.json').json()
        for operation in ('get','put'):
            route=schema['paths']['/api/v1/workbooks/{workbook_id}/schedule'][operation]
            self.assertTrue(route['security'])
            self.assertIn('200',route['responses'])

    def test_generated_output_is_latest(self):
        ids,base,path=self.resource()
        audit=self.client.get(base+'/audits/'+ids['auditId'],headers=self.headers).json()
        response=self.client.post(base+'/remediations',
            headers=dict(self.headers,**{'Idempotency-Key':'schedule-output'}),
            json=dict(auditId=ids['auditId'],decisions=[
                dict(findingId=audit['findings'][0]['findingId'],action='DECLINE')]))
        self.assertEqual(response.status_code,202,response.text)
        job=self.client.get('/api/v1/remediations/'+response.json()['remediationId'],headers=self.headers).json()
        self.assertEqual(self.client.get(path,headers=self.headers).json()['versionId'],job['outputVersionId'])

    def test_namespace_cleanup(self):
        admin={'Authorization':'Bearer admin'}
        for name in ('one','two'):
            response=self.client.post('/test/setup',headers=admin,json={'session_id':name,'setup':{}})
            self.assertEqual(response.status_code,201,response.text)
        headers=dict(self.headers,**{'X-Test-Session':'one'})
        ids,base=self.upload(headers=headers)
        path='/api/v1/workbooks/'+ids['workbookId']+'/schedule'
        self.assertEqual(self.client.put(path,headers=headers,json={'enabled':True,'intervalDays':1}).status_code,200)
        self.assert_error(self.client.get(path,headers=dict(self.headers,**{'X-Test-Session':'two'})),404)
        # Active jobs, not legacy audit status, guard cleanup.
        with self.app.state.store.connect(write=True) as db:
            db.execute("UPDATE p4_jobs SET state='RUNNING' WHERE namespace='one'")
        response=self.client.post('/test/setup',headers=admin,json={'session_id':'blocked','setup':{'cleanup_session_ids':['one']}})
        self.assertEqual(response.status_code,409)
        with self.app.state.store.connect(write=True) as db:
            db.execute("UPDATE p4_jobs SET state='DONE' WHERE namespace='one'")
        response=self.client.post('/test/setup',headers=admin,json={'session_id':'clean','setup':{'cleanup_session_ids':['one']}})
        self.assertEqual(response.status_code,201,response.text)
        with self.app.state.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) n FROM p5_schedules WHERE namespace='one'").fetchone()['n'],0)
