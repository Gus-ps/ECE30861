import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from phase4_service import create_app
from credentials import subject_for
from test_phase4_service import workbook
import release_guard


def digest(token):
    return 'sha256:' + hashlib.sha256(token.encode()).hexdigest()


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.env = patch.dict('os.environ', {'ENABLE_TEST_CLOCK':'true'}); self.env.start(); self.addCleanup(self.env.stop)
        self.app = create_app(Path(self.temp.name)/'service.db',
            {digest('owner-key'):'owner', digest('review-key'):'reviewer', digest('ungranted-key'):'ungranted', 'other-key':'other'},
            workbook_validator=lambda p: True, accessibility_checker=lambda p: [], enable_scheduler=False,
            enable_test_interface=True,
            test_admin_tokens={digest('admin-key'):'admin', digest('admin2-key'):'admin2'},
            test_session_users={'admin':['owner','reviewer','ungranted','other'], 'admin2':['owner']},
            reviewer_grants={'reviewer':['owner'], 'ungranted':[]})
        self.client=TestClient(self.app); self.addCleanup(self.client.close)
        self.owner={'Authorization':'Bearer owner-key'}
        response=self.client.post('/api/v1/workbooks',headers=self.owner,files={'file':('clean.xlsx',workbook('Records'))})
        self.assertEqual(response.status_code,202,response.text)
        self.ids=response.json(); self.wb='/api/v1/workbooks/'+self.ids['workbookId']
        self.version=self.wb+'/versions/'+self.ids['versionId']

    def test_clean_workbook_permission_hint_and_reviewer_write_denials(self):
        self.assertEqual(self.client.get(self.version,headers=self.owner).headers['X-Workbook-Access'],'owner')
        for token,read in [('review-key',200),('ungranted-key',403),('other-key',403),('admin-key',403),('bad',401)]:
            headers={'Authorization':'Bearer '+token}
            for suffix in ('/schedule','/notifications'):
                r=self.client.get(self.wb+suffix,headers=headers)
                self.assertEqual(r.status_code,read,(token,suffix,r.text))
            for method,url,kwargs in [('POST','/api/v1/workbooks',{'files':{'file':('book.xlsx',workbook())}}),
                ('PUT',self.wb+'/schedule',{'json':{'enabled':True,'intervalDays':7}}),('DELETE',self.wb,{})]:
                if token=='other-key' and url=='/api/v1/workbooks': continue
                r=self.client.request(method,url,headers=headers,**kwargs)
                self.assertEqual(r.status_code,401 if token=='bad' else 403,(token,method,r.text))
        r=self.client.get(self.version,headers={'Authorization':'Bearer review-key'})
        self.assertEqual(r.headers['X-Workbook-Access'],'reviewer')
        denial=self.client.get(self.version,headers={'Authorization':'Bearer ungranted-key'})
        self.assertNotIn('X-Workbook-Access',denial.headers)
        self.assertNotIn('clean.xlsx',denial.text)

    def test_second_administrator_cannot_control_first_administrators_namespace(self):
        setup=self.client.post('/test/setup',headers={'Authorization':'Bearer admin-key'},json={'session_id':'protected'})
        self.assertEqual(setup.status_code,201,setup.text)
        report=self.client.get('/test/report',headers={'Authorization':'Bearer admin2-key'},params={'session_id':'protected'})
        self.assertEqual(report.status_code,403,report.text)
        clock=self.client.post('/api/v1/test/clock',headers={'Authorization':'Bearer admin2-key','X-Test-Session':'protected'},json={'currentTime':'2027-01-02T00:00:00Z'})
        self.assertEqual(clock.status_code,403,clock.text)
        cleanup=self.client.post('/test/setup',headers={'Authorization':'Bearer admin2-key'},
            json={'session_id':'foreign-cleanup','setup':{'cleanup_session_ids':['protected']}})
        self.assertEqual(cleanup.status_code,403,cleanup.text)

    def test_real_time_release_protection_and_drain(self):
        setup=self.client.post('/test/setup',headers={'Authorization':'Bearer admin-key'},json={'session_id':'lease'})
        self.assertEqual(setup.status_code,201,setup.text)
        with self.assertRaisesRegex(RuntimeError,'Release deferred'):
            release_guard.arm(self.app.state.store)
        with self.app.state.store.connect(write=True) as db:
            db.execute('UPDATE p5_release_leases SET expires_at=0')
        release_guard.arm(self.app.state.store)
        self.assertEqual(self.client.put(self.wb+'/schedule',headers=self.owner,json={'enabled':False}).status_code,503)
        self.assertEqual(self.client.get(self.version,headers=self.owner).status_code,200)
        self.assertEqual(self.client.post('/test/setup',headers={'Authorization':'Bearer admin-key'},json={'session_id':'drain'}).status_code,503)
        release_guard.resume(self.app.state.store)
        self.assertEqual(self.client.put(self.wb+'/schedule',headers=self.owner,json={'enabled':False}).status_code,200)

    def test_security_headers_and_hashed_token_matching(self):
        r=self.client.get(self.version,headers=self.owner)
        self.assertEqual(r.headers['Cache-Control'],'no-store')
        self.assertEqual(r.headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(r.headers['X-Frame-Options'],'DENY')
        self.assertIsNone(subject_for({digest('secret'):'owner'},'bad'))
        self.assertEqual(subject_for({digest('secret'):'owner'},'secret'),'owner')
