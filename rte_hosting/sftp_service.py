"""Opt-in SSH/SFTP server for assigned Minecraft files.

Use SSH encryption, never plaintext FTP. Default listener is localhost only.
This is file-level separation, NOT a security boundary for mutually untrusted
Minecraft plugins or mods, which run as the host Windows service account.
"""
from __future__ import annotations
import errno
import os
import re
import socket
import stat
import threading
import time
from pathlib import Path, PurePosixPath
from . import engine as e

try:
    import paramiko
except ImportError:
    paramiko = None


class VirtualFiles:
    def __init__(self,user):
        self.user=user

    def _accessible(self):
        if self.user['role'] in ('admin','staff'):
            return e.rows('SELECT id,name FROM servers ORDER BY name')
        return e.rows('''SELECT s.id,s.name FROM servers s JOIN assignments a ON a.server_id=s.id
                         WHERE a.user_id=? AND a.can_files=1 ORDER BY s.name''',(self.user['id'],))

    def path(self,p,write=False):
        if not isinstance(p,str) or '\\' in p or '\x00' in p or ':' in p or len(p)>2048:
            raise PermissionError('Invalid SFTP path.')
        if p in ('','/','.'): return None
        components=[part for part in PurePosixPath(p).parts if part not in ('/','.')]
        if not components or '..' in components or len(components)>100:
            raise PermissionError('Path traversal is not permitted.')
        sid=components[0]
        if not re.fullmatch(r'[a-f0-9-]{36}',sid) or sid not in {s['id'] for s in self._accessible()}:
            raise PermissionError('Server not assigned for file access.')
        relative='/'.join(components[1:])
        if write and self.user['role']=='customer':
            if not relative:raise PermissionError('Cannot modify server root.')
            suffix=Path(relative).suffix.lower()
            name=Path(relative).name.casefold()
            if name in ('server.properties','eula.txt','run.bat','run.sh','server.jar','rte-console.log') or suffix in ('.exe','.bat','.cmd','.ps1','.sh','.dll','.py','.pyd'):
                raise PermissionError('Protected server file.')
            if suffix=='.jar' and not any(x.lower() in ('mods','plugins') for x in components[1:-1]):
                raise PermissionError('JAR writes are limited to mods/ and plugins/.')
        return e.safe_server_path(sid,relative)


if paramiko:
    def code(exc):
        if isinstance(exc,PermissionError):return paramiko.SFTP_PERMISSION_DENIED
        if isinstance(exc,(FileNotFoundError,NotADirectoryError)):return paramiko.SFTP_NO_SUCH_FILE
        if isinstance(exc,FileExistsError):return paramiko.SFTP_FAILURE
        return paramiko.SFTP_FAILURE

    class HostAuth(paramiko.ServerInterface):
        _attempts={}
        _lock=threading.Lock()

        def __init__(self,peer):
            self.user=None
            self.peer=peer

        def get_allowed_auths(self, username):return 'password'

        def check_channel_request(self,kind,chanid):
            return paramiko.OPEN_SUCCEEDED if kind=='session' and self.user else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_auth_password(self, username,password):
            # Deliberately do not reuse session tokens or store plaintext FTP credentials.
            key=(self.peer,username.casefold())
            with self._lock:
                attempts,t=self._attempts.get(key,(0,time.monotonic()))
                if time.monotonic()-t>900:attempts,t=0,time.monotonic()
                if attempts>=8:return paramiko.AUTH_FAILED
                self._attempts[key]=(attempts+1,t)
            user=e.one('SELECT * FROM users WHERE username=?',(username,))
            if not user or user['disabled'] or not e.verify_password(password,user['passhash']):return paramiko.AUTH_FAILED
            with self._lock:self._attempts.pop(key,None)
            self.user=user
            e.log_audit(user['username'],'sftp_login',self.peer)
            return paramiko.AUTH_SUCCESSFUL

    class SFTPHandle(paramiko.SFTPHandle):
        pass

    class AssignedSFTP(paramiko.SFTPServerInterface):
        def __init__(self,server,*args,**kwargs):
            super().__init__(server,*args,**kwargs)
            self.fs=VirtualFiles(server.user)

        def _real(self,path,write=False):
            return self.fs.path(path,write)

        def list_folder(self,path):
            try:
                root=self._real(path)
                if root is None:
                    names=[x['id'] for x in self.fs._accessible()]
                    return [self._virtual_attr(name) for name in names]
                return [paramiko.SFTPAttributes.from_stat(p.stat(),filename=p.name) for p in root.iterdir() if not p.is_symlink()]
            except (OSError,ValueError) as exc:return code(exc)

        def _virtual_attr(self,name):
            a=paramiko.SFTPAttributes()
            a.filename=name
            a.st_mode=stat.S_IFDIR|0o750
            a.st_size=0
            return a

        def stat(self,path):
            try:
                p=self._real(path)
                return self._virtual_attr('/') if p is None else paramiko.SFTPAttributes.from_stat(p.stat())
            except (OSError,ValueError) as exc:return code(exc)

        def lstat(self,path):return self.stat(path)

        def open(self,path,flags,attr):
            modifying=bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            try:
                target=self._real(path,write=modifying)
                if target is None:raise PermissionError('Cannot open virtual root.')
                if target.is_symlink():raise PermissionError('Links not allowed.')
                mode=getattr(attr,'st_mode',None)
                descriptor=os.open(target,flags,0o600 if mode is None else mode & 0o600)
                fp=os.fdopen(descriptor,'r+b' if flags & os.O_RDWR else ('wb' if flags & os.O_WRONLY else 'rb'),buffering=0)
                handle=SFTPHandle(flags)
                handle.readfile=fp if not (flags & os.O_WRONLY) else None
                handle.writefile=fp if modifying else None
                return handle
            except (OSError,ValueError) as exc:return code(exc)

        def remove(self,path):
            try:self._real(path,write=True).unlink();return paramiko.SFTP_OK
            except (OSError,ValueError) as exc:return code(exc)

        def mkdir(self,path,attr):
            try:self._real(path,write=True).mkdir();return paramiko.SFTP_OK
            except (OSError,ValueError) as exc:return code(exc)

        def rmdir(self,path):
            try:self._real(path,write=True).rmdir();return paramiko.SFTP_OK
            except (OSError,ValueError) as exc:return code(exc)

        def rename(self,oldpath,newpath):
            try:
                a=self._real(oldpath,write=True)
                b=self._real(newpath,write=True)
                # Never move files between different server roots.
                if [x for x in PurePosixPath(oldpath).parts if x!='/'][0] != [x for x in PurePosixPath(newpath).parts if x!='/'][0]:raise PermissionError('Cross-instance move is blocked.')
                a.rename(b)
                return paramiko.SFTP_OK
            except (OSError,ValueError,IndexError) as exc:return code(exc)

    def start_sftp(host='127.0.0.1',port=2222):
        if host not in ('127.0.0.1','localhost','::1') and os.getenv('RTE_ALLOW_LAN_SFTP')!='1':
            raise ValueError('Remote SFTP binding requires RTE_ALLOW_LAN_SFTP=1 and a firewall/VPN policy.')
        e.init_db()
        key_path=e.DATA_ROOT/'ssh_host_rsa_key'
        if key_path.exists():host_key=paramiko.RSAKey.from_private_key_file(str(key_path))
        else:
            host_key=paramiko.RSAKey.generate(3072)
            host_key.write_private_key_file(str(key_path))
            try:key_path.chmod(0o600)
            except OSError:pass
        listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind((host,port))
        listener.listen(12)
        def handle(client,address):
            transport=paramiko.Transport(client)
            try:
                transport.add_server_key(host_key)
                transport.set_subsystem_handler('sftp',paramiko.SFTPServer,AssignedSFTP)
                auth=HostAuth(address[0])
                transport.start_server(server=auth)
                while transport.is_active():time.sleep(.3)
            except (OSError,paramiko.SSHException):pass
            finally:transport.close()
        def serve():
            while True:
                try:client,address=listener.accept()
                except OSError:break
                threading.Thread(target=handle,args=(client,address),daemon=True).start()
        threading.Thread(target=serve,daemon=True,name='RTE SFTP listener').start()
        return listener
else:
    def start_sftp(host='127.0.0.1',port=2222):
        raise RuntimeError('Install Paramiko to enable the optional SFTP service.')
