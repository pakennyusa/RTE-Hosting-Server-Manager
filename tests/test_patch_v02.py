"""RTE Hosting 0.2 regression tests: zero-copy import, permissions, runtime, vendor updates."""
import hashlib
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from rte_hosting import engine as e, provisioning, sftp_service
from rte_hosting.webapp import start_server


class ImportAndProvisioningTests(unittest.TestCase):
    def setUp(self):
        self._old=[e.DATA_ROOT,e.DB_PATH,e.SERVERS_ROOT,e.BACKUPS_ROOT]
        self.temp=tempfile.TemporaryDirectory()
        base=Path(self.temp.name)
        e.DATA_ROOT=base/'config'
        e.DATA_ROOT.mkdir()
        e.DB_PATH=e.DATA_ROOT/'db.sqlite3'
        e.SERVERS_ROOT=e.DATA_ROOT/'servers'
        e.BACKUPS_ROOT=e.DATA_ROOT/'backups'
        e.SERVERS_ROOT.mkdir()
        e.BACKUPS_ROOT.mkdir()
        e.init_db()
        self.folder=base/'existing-survival'
        self.folder.mkdir()
        (self.folder/'paper-26.3.jar').write_bytes(b'PK'+b'x'*5000)
        (self.folder/'world').mkdir()
        (self.folder/'world'/'level.dat').write_bytes(b'only-existing-copy')
        (self.folder/'server.properties').write_text('server-port=27777\nonline-mode=true\n')
        (self.folder/'eula.txt').write_text('eula=true\n')

    def tearDown(self):
        e.DATA_ROOT,e.DB_PATH,e.SERVERS_ROOT,e.BACKUPS_ROOT=self._old
        self.temp.cleanup()

    def test_zero_copy_import_existing_properties_and_backup(self):
        found=e.inspect_existing_server(str(self.folder))
        self.assertEqual(found['framework'],'Paper')
        self.assertEqual(found['port'],27777)
        self.assertEqual(found['jar'],'paper-26.3.jar')
        self.assertTrue(found['eula_accepted'])
        with self.assertRaises(ValueError):
            e.import_server({'path':str(self.folder),'name':'Imported Survival'})
        sid,meta=e.import_server({'path':str(self.folder),'name':'Imported Survival','acknowledge_external_write':True})
        self.assertEqual(e.server_dir(sid),self.folder.resolve())
        self.assertEqual(e.one('SELECT eula_accepted FROM servers WHERE id=?',(sid,))['eula_accepted'],1)
        self.assertFalse((e.SERVERS_ROOT/sid).exists())
        self.assertEqual((self.folder/'world'/'level.dat').read_bytes(),b'only-existing-copy')
        self.assertTrue(any(f['name']=='paper-26.3.jar' for f in e.list_files(sid)))
        with self.assertRaises(ValueError):e.import_server({'path':str(self.folder),'acknowledge_external_write':True})
        self.assertTrue(e.make_backup(sid)['name'].endswith('.zip'))
        with self.assertRaises(PermissionError):e.safe_server_path(sid,'../../escape')
        link=self.folder/'escape-link'
        try: link.symlink_to(self.folder/'world',target_is_directory=True)
        except (OSError,NotImplementedError):pass
        else:
            with self.assertRaises(PermissionError):e.safe_server_path(sid,'escape-link/level.dat')

    def test_java_detection_choice_logic(self):
        choices=[{'path':'C:/java21/bin/java.exe','major':21,'version':'21'},
                 {'path':'C:/java25/bin/java.exe','major':25,'version':'25'}]
        self.assertEqual(provisioning.choose_java('26.3',choices)['best']['major'],25)
        self.assertEqual(provisioning.choose_java('1.21.1',choices)['best']['major'],21)
        self.assertEqual(provisioning.recommended_java('1.19.4'),17)
        self.assertEqual(provisioning.recommended_java('1.16.5'),16)
        with self.assertRaises(ValueError):provisioning.official_url('http://127.0.0.1/malware.jar')
        with self.assertRaises(ValueError):provisioning.official_url('https://untrusted.example.org/file.jar')

    def test_atomic_vendor_update_same_jar_without_duplication(self):
        sid,_=e.import_server({'path':str(self.folder),'name':'Imported World','acknowledge_external_write':True})
        content=b'PK'+b'new-jar-content'*800
        target=self.folder/'paper-26.3.jar'
        fake_url='https://api.purpurmc.org/v2/purpur/26.3/latest/download'
        class Response:
            headers={'Content-Length':str(len(content))}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return fake_url
            def read(self,n=-1):
                result=self.data[:n]
                self.data=self.data[n:]
                return result
            def __init__(self):self.data=content
        with mock.patch.object(provisioning,'resolve_download',return_value={
            'url':fake_url,'digest':hashlib.sha256(content).hexdigest(),'hash_type':'sha256','build':'test'}), \
            mock.patch.object(provisioning.urllib.request,'urlopen',return_value=Response()), \
            mock.patch.object(provisioning,'detect_java',return_value=[]):
            result=provisioning.download_framework(e.one('SELECT * FROM servers WHERE id=?',(sid,)),'Purpur','26.3')
        self.assertEqual(result['filename'],'paper-26.3.jar')
        self.assertEqual(target.read_bytes(),content)
        self.assertFalse((self.folder/'server.jar').exists())
        self.assertEqual(e.one('SELECT framework FROM servers WHERE id=?',(sid,))['framework'],'Purpur')

    def test_sftp_assigned_roots_and_write_protection(self):
        sid,_=e.import_server({'path':str(self.folder),'name':'Imported Survival','acknowledge_external_write':True})
        uid=e.create_user('sftpuser','a secure test password 123','customer')
        user=e.one('SELECT * FROM users WHERE id=?',(uid,))
        fs=sftp_service.VirtualFiles(user)
        with self.assertRaises(PermissionError):fs.path('/'+sid+'/world/level.dat')
        e.execute('INSERT INTO assignments(server_id,user_id,can_files) VALUES(?,?,1)',(sid,uid))
        self.assertEqual(fs.path('/'+sid+'/world/level.dat'),self.folder/'world'/'level.dat')
        with self.assertRaises(PermissionError):fs.path('/'+sid+'/eula.txt',write=True)
        with self.assertRaises(PermissionError):fs.path('/'+sid+'/../other-server/keys')
        with self.assertRaises(PermissionError):fs.path('/'+sid+'/evil.jar',write=True)
        self.assertEqual(fs.path('/'+sid+'/mods/test.jar',write=True),self.folder/'mods'/'test.jar')

if __name__=='__main__':unittest.main()

class SFTPNetworkTests(ImportAndProvisioningTests):
    @unittest.skipIf(sftp_service.paramiko is None,'Paramiko unavailable in local Python; Windows CI installs it')
    def test_local_sftp_login_and_assigned_file_read(self):
        import paramiko
        sid,_=e.import_server({'path':str(self.folder),'name':'SFTP Integration','acknowledge_external_write':True})
        uid=e.create_user('remoteuser','long password for remote user','customer')
        e.execute('INSERT INTO assignments(server_id,user_id,can_files) VALUES(?,?,1)',(sid,uid))
        listener=sftp_service.start_sftp('127.0.0.1',0)
        try:
            transport=paramiko.Transport(('127.0.0.1',listener.getsockname()[1]))
            transport.connect(username='remoteuser',password='long password for remote user')
            try:
                client=paramiko.SFTPClient.from_transport(transport)
                self.assertIn(sid,client.listdir('/'))
                with client.open('/'+sid+'/world/level.dat','rb') as f:
                    self.assertEqual(f.read(),b'only-existing-copy')
                with self.assertRaises((OSError,IOError)):
                    client.open('/'+sid+'/eula.txt','wb')
                client.close()
            finally:transport.close()
        finally:listener.close()
