"""Run with: python -m unittest discover -s tests -v"""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from rte_hosting import engine as e
from rte_hosting.webapp import start_server


class HostingAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='rte-hosting-test-')
        e.DATA_ROOT=Path(cls.tmp.name)
        e.DB_PATH=e.DATA_ROOT/'database.sqlite3'
        e.SERVERS_ROOT=e.DATA_ROOT/'servers'
        e.BACKUPS_ROOT=e.DATA_ROOT/'backups'
        e.SERVERS_ROOT.mkdir()
        e.BACKUPS_ROOT.mkdir()
        cls.http=start_server(port=0)
        cls.port=cls.http.server_port
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=2)
        cls.tmp.cleanup()

    def request(self,method,path,data=None,cookie=None,csrf=None,raw=False):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        headers={'Host':'127.0.0.1'}
        if cookie:headers['Cookie']=cookie
        if csrf:headers['X-CSRF-Token']=csrf
        body=None
        if data is not None:
            if raw:
                body=data
            else:
                body=json.dumps(data).encode()
                headers['Content-Type']='application/json'
        connection.request(method,path,body,headers)
        response=connection.getresponse()
        result=response.read()
        hdr={key.lower():val for key,val in response.getheaders()}
        status=response.status
        connection.close()
        return status,(json.loads(result) if hdr.get('content-type','').startswith('application/json') else result),hdr

    def test_end_to_end_permissions_and_backup(self):
        s,r,_=self.request('GET','/api/bootstrap/status')
        self.assertEqual(s,200)
        self.assertTrue(r['needs_setup'])
        s,r,h=self.request('POST','/api/bootstrap',{'username':'hostadmin','password':'secure admin passphrase 123'})
        self.assertEqual(s,200)
        admin_cookie=h['set-cookie'].split(';')[0]
        admin_csrf=r['csrf']
        s,r,_=self.request('GET','/api/servers')
        self.assertEqual(s,401)
        s,r,_=self.request('POST','/api/servers',{'name':'Sandbox','framework':'Paper'},cookie=admin_cookie)
        self.assertEqual(s,403)
        s,r,_=self.request('POST','/api/servers',{'name':'Demo World','framework':'Paper','port':25571},cookie=admin_cookie,csrf=admin_csrf)
        self.assertEqual(s,201)
        sid=r['id']
        s,r,_=self.request('POST','/api/admin/users',{'username':'customer01','password':'some lengthy password 456','role':'customer'},cookie=admin_cookie,csrf=admin_csrf)
        self.assertEqual(s,201)
        uid=r['id']
        s,r,_=self.request('POST','/api/login',{'username':'customer01','password':'some lengthy password 456'})
        self.assertEqual(s,200)
        # Authenticate with cookie from a second login request.
        s,r,h=self.request('POST','/api/login',{'username':'customer01','password':'some lengthy password 456'})
        customer_cookie=h['set-cookie'].split(';')[0]
        customer_csrf=r['csrf']
        s,r,_=self.request('GET','/api/servers',cookie=customer_cookie)
        self.assertEqual(len(r['servers']),0)
        s,r,_=self.request('GET',f'/api/servers/{sid}',cookie=customer_cookie)
        self.assertEqual(s,403)
        s,r,_=self.request('POST','/api/admin/assignments',{'server_id':sid,'user_id':uid,'can_control':True,'can_files':True,'can_console':False},cookie=admin_cookie,csrf=admin_csrf)
        self.assertEqual(s,200)
        s,r,_=self.request('GET','/api/servers',cookie=customer_cookie)
        self.assertEqual(len(r['servers']),1)
        s,r,_=self.request('GET',f'/api/servers/{sid}/console',cookie=customer_cookie)
        self.assertEqual(s,403)
        s,r,_=self.request('PUT',f'/api/servers/{sid}/file?path=run.bat',b'echo hello',cookie=customer_cookie,csrf=customer_csrf,raw=True)
        self.assertEqual(s,403)
        s,r,_=self.request('PUT',f'/api/servers/{sid}/file?path=..%2F..%2Fescaping.txt',b'test',cookie=customer_cookie,csrf=customer_csrf,raw=True)
        self.assertEqual(s,400)
        s,r,_=self.request('POST',f'/api/servers/{sid}/start',{},cookie=customer_cookie,csrf=customer_csrf)
        self.assertEqual(s,400)
        s,r,_=self.request('POST',f'/api/servers/{sid}/eula',{'accepted':True},cookie=customer_cookie,csrf=customer_csrf)
        self.assertEqual(s,200)
        s,r,_=self.request('POST',f'/api/servers/{sid}/backups',{},cookie=customer_cookie,csrf=customer_csrf)
        self.assertEqual(s,201)
        s,r,_=self.request('GET',f'/api/servers/{sid}/backups',cookie=customer_cookie)
        self.assertEqual(len(r['backups']),1)
        s,r,_=self.request('GET',f'/api/servers/{sid}/files',cookie=customer_cookie)
        self.assertEqual(s,200,r)
        self.assertTrue(any(f['name']=='eula.txt' for f in r['files']))
        s,r,_=self.request('GET','/api/admin/users',cookie=customer_cookie)
        self.assertEqual(s,403)

    def test_hashing_and_paths(self):
        encoded=e.hash_password('an extraordinarily long secret')
        self.assertNotIn('extraordinarily',encoded)
        self.assertTrue(e.verify_password('an extraordinarily long secret',encoded))
        self.assertFalse(e.verify_password('not the right password',encoded))

if __name__=='__main__':
    unittest.main()
