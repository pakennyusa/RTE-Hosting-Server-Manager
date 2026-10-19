"""RTE Hosting local web portal: authenticated, role-limited HTTP API."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import engine as e

STATIC = Path(__file__).resolve().parent / 'static'
LOGIN_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()
UPLOAD_LIMIT = 64 * 1024 * 1024
JSON_LIMIT = 200_000


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def clean_relative(name):
    return urllib.parse.unquote(name or '').strip('/')


class PortalHandler(SimpleHTTPRequestHandler):
    server_version = 'RTEHosting/0.1'
    sys_version = ''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt, *args):
        # Log status and endpoint; avoid inadvertently storing credentials or file payloads.
        if os.getenv('RTE_VERBOSE') == '1':
            super().log_message(fmt,*args)

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def json(self, payload, status=200, cookie=None):
        data = json.dumps(payload,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(data)

    def current_token(self):
        parsed = SimpleCookie()
        try:
            parsed.load(self.headers.get('Cookie',''))
        except Exception:
            return None
        cookie = parsed.get('rte_session')
        return cookie.value if cookie else None

    def require_auth(self, mutate=False):
        auth = e.get_session(self.current_token())
        if not auth:
            raise APIError(401, 'Log in to continue.')
        if mutate and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''), auth['csrf']):
            raise APIError(403,'Security token missing or invalid. Refresh and try again.')
        return auth

    def require_staff(self, auth, admin_only=False):
        if auth['role'] not in (('admin',) if admin_only else ('admin','staff')):
            raise APIError(403,'Staff permissions are required.')

    def require_server(self, auth, sid, grant=None):
        try:
            server, perms = e.server_access(auth,sid)
        except FileNotFoundError as exc:
            raise APIError(404,str(exc)) from exc
        except PermissionError as exc:
            raise APIError(403,str(exc)) from exc
        if grant and not perms[grant]:
            raise APIError(403,'Your account does not have permission for this action.')
        return server,perms

    def body_json(self):
        try:
            size = int(self.headers.get('Content-Length','-1'))
        except ValueError:
            raise APIError(400,'Invalid request length.')
        if size < 0 or size > JSON_LIMIT:
            raise APIError(413,'Request body exceeds limit.')
        try:
            data = json.loads(self.rfile.read(size))
        except (ValueError,UnicodeDecodeError):
            raise APIError(400,'Invalid JSON.')
        if not isinstance(data,dict):
            raise APIError(400,'Expected an object.')
        return data

    def check_origin(self):
        origin = self.headers.get('Origin')
        if origin:
            parsed = urllib.parse.urlparse(origin)
            host = self.headers.get('Host','').lower()
            if parsed.scheme not in ('http','https') or parsed.netloc.lower() != host:
                raise APIError(403,'Cross-site request rejected.')
        # DNS rebinding protection for bootstrap and local portal endpoints.
        host = self.headers.get('Host','').split(':')[0].lower().strip('[]')
        if not host or any(c in host for c in '/\\@'):
            raise APIError(403,'Invalid host header.')
        allowed = os.getenv('RTE_ALLOWED_HOSTS','localhost,127.0.0.1,::1').lower().split(',')
        if host not in [h.strip() for h in allowed]:
            raise APIError(403,'This host is not allowed. Configure RTE_ALLOWED_HOSTS.')

    def _check_login_limit(self, key, success=False):
        now = time.monotonic()
        with LOGIN_LOCK:
            if len(LOGIN_ATTEMPTS) > 10000:
                LOGIN_ATTEMPTS.clear()
            count, since = LOGIN_ATTEMPTS.get(key,(0,now))
            if now-since > 900:
                count,since = 0,now
            if success:
                LOGIN_ATTEMPTS.pop(key,None)
            elif count >= 8:
                raise APIError(429,'Too many login attempts. Try again in 15 minutes.')
            else:
                LOGIN_ATTEMPTS[key] = (count+1,since)

    def dispatch(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        get = lambda key,default='': query.get(key,[default])[0]
        method = self.command
        if not path.startswith('/api/'):
            if method != 'GET' and method != 'HEAD':
                raise APIError(405,'Method not allowed.')
            if path in ('/','/index.html'):
                self.path = '/index.html'
            return super().do_GET() if method=='GET' else super().do_HEAD()

        self.check_origin()
        if method=='GET' and path=='/api/bootstrap/status':
            return self.json({'needs_setup':e.one('SELECT id FROM users LIMIT 1') is None,
                              'version':e.APP_VERSION,'frameworks':e.FRAMEWORKS})
        if method=='POST' and path=='/api/bootstrap':
            if self.client_address[0] not in ('127.0.0.1','::1'):
                raise APIError(403,'Initial setup is only available directly on the hosting computer.')
            if e.one('SELECT id FROM users LIMIT 1'):
                raise APIError(409,'Setup is already complete.')
            data = self.body_json()
            try:
                uid = e.create_user(data.get('username',''),data.get('password',''),'admin')
            except sqlite3.IntegrityError:
                raise APIError(409,'Setup is already complete.')
            user = e.one('SELECT * FROM users WHERE id=?',(uid,))
            token,csrf = e.create_session(user)
            return self.json({'user':e.safe_user(user),'csrf':csrf},cookie=self.cookie(token))
        if method=='POST' and path=='/api/login':
            data = self.body_json()
            username = str(data.get('username',''))[:64]
            key = (self.client_address[0],username.casefold())
            self._check_login_limit(key)
            user = e.one('SELECT * FROM users WHERE username=?',(username,))
            if not user or user['disabled'] or not e.verify_password(str(data.get('password','')),user['passhash']):
                raise APIError(401,'Invalid username or password.')
            self._check_login_limit(key,success=True)
            token,csrf = e.create_session(user)
            e.log_audit(username,'login')
            return self.json({'user':e.safe_user(user),'csrf':csrf},cookie=self.cookie(token))

        auth = self.require_auth(method not in ('GET','HEAD'))
        if method=='POST' and path=='/api/logout':
            e.logout(self.current_token())
            return self.json({'ok':True},cookie=self.cookie('',maxage=0))
        if method=='GET' and path=='/api/me':
            return self.json({'user':e.safe_user(auth),'csrf':auth['csrf'],'version':e.APP_VERSION})
        if method=='GET' and path=='/api/servers':
            return self.json({'servers':e.visible_servers(auth)})
        if method=='POST' and path=='/api/servers':
            self.require_staff(auth)
            body = self.body_json()
            sid = e.create_server(body)
            e.log_audit(auth['username'],'server_created',sid+' '+body['name'])
            return self.json({'id':sid},201)
        if method=='GET' and path=='/api/admin/users':
            self.require_staff(auth)
            return self.json({'users':[e.safe_user(u) for u in e.rows('SELECT * FROM users ORDER BY username')]})
        if method=='POST' and path=='/api/admin/users':
            self.require_staff(auth)
            body = self.body_json()
            role = body.get('role','customer')
            if role != 'customer' and auth['role'] != 'admin':
                raise APIError(403,'Only administrators can create staff accounts.')
            if role == 'admin' and auth['role'] != 'admin':
                raise APIError(403,'Only administrators can create admin accounts.')
            uid = e.create_user(str(body.get('username','')),str(body.get('password','')),role)
            e.log_audit(auth['username'],'user_created',uid)
            return self.json({'id':uid},201)
        if method=='GET' and path=='/api/admin/assignments':
            self.require_staff(auth)
            return self.json({'assignments':e.rows('SELECT * FROM assignments')})
        if method=='POST' and path=='/api/admin/assignments':
            self.require_staff(auth)
            body = self.body_json()
            sid,uid = str(body.get('server_id','')),str(body.get('user_id',''))
            if not e.one('SELECT id FROM servers WHERE id=?',(sid,)) or not e.one('SELECT id FROM users WHERE id=?',(uid,)):
                raise APIError(404,'Account or server not found.')
            flags = [int(bool(body.get(x,0))) for x in ('can_control','can_console','can_files')]
            e.execute('''INSERT INTO assignments(server_id,user_id,can_control,can_console,can_files)
             VALUES(?,?,?,?,?) ON CONFLICT(server_id,user_id) DO UPDATE SET
             can_control=excluded.can_control,can_console=excluded.can_console,can_files=excluded.can_files''',
             (sid,uid,*flags))
            e.log_audit(auth['username'],'assignment_updated',uid+' -> '+sid)
            return self.json({'ok':True})
        if method=='DELETE' and path=='/api/admin/assignments':
            self.require_staff(auth)
            sid,uid = get('server_id'),get('user_id')
            e.execute('DELETE FROM assignments WHERE server_id=? AND user_id=?',(sid,uid))
            e.log_audit(auth['username'],'assignment_removed',uid+' -> '+sid)
            return self.json({'ok':True})
        if method=='GET' and path=='/api/admin/audit':
            self.require_staff(auth)
            return self.json({'events':e.rows('SELECT * FROM audit ORDER BY id DESC LIMIT 120')})

        parts = path.split('/')
        if len(parts) >= 4 and parts[1]=='api' and parts[2]=='servers':
            sid = parts[3]
            server, perms = self.require_server(auth,sid)
            sub = '/' + '/'.join(parts[4:]) if len(parts)>4 else ''
            if method=='GET' and not sub:
                return self.json({'server':dict(server,running=e.MANAGER.is_running(sid)),
                    'permissions':perms,'properties':e.read_properties(sid)})
            if method=='GET' and sub=='/console':
                self.require_server(auth,sid,'can_console')
                return self.json({'lines':list(e.MANAGER.tail(sid,150)), 'running':e.MANAGER.is_running(sid)})
            if method=='POST' and sub in ('/start','/stop'):
                self.require_server(auth,sid,'can_control')
                result = e.MANAGER.start(server) if sub=='/start' else e.MANAGER.stop(sid)
                e.log_audit(auth['username'],sub[1:]+'_server',sid)
                return self.json({'ok':True,'pid':result if sub=='/start' else None})
            if method=='POST' and sub=='/command':
                self.require_server(auth,sid,'can_console')
                value = self.body_json().get('command','')
                e.MANAGER.command(sid,str(value))
                e.log_audit(auth['username'],'console_command',sid+' [command redacted]')
                return self.json({'ok':True})
            if method=='POST' and sub=='/eula':
                self.require_server(auth,sid,'can_control')
                if self.body_json().get('accepted') is not True:
                    raise APIError(400,'Explicit acceptance required.')
                if e.MANAGER.is_running(sid):
                    raise APIError(409,'Stop the server before changing its EULA status.')
                e.safe_server_path(sid,'eula.txt').write_text('eula=true\n',encoding='utf-8')
                e.execute('UPDATE servers SET eula_accepted=1 WHERE id=?',(sid,))
                e.log_audit(auth['username'],'eula_accepted',sid)
                return self.json({'ok':True})
            if method=='GET' and sub=='/properties':
                return self.json({'properties':e.read_properties(sid)})
            if method=='POST' and sub=='/properties':
                self.require_server(auth,sid,'can_files')
                e.update_properties(sid,self.body_json(),auth['role']!='customer')
                e.log_audit(auth['username'],'properties_updated',sid)
                return self.json({'ok':True})
            if method=='GET' and sub=='/files':
                self.require_server(auth,sid,'can_files')
                return self.json({'path':get('path'),'files':e.list_files(sid,get('path'))})
            if method=='POST' and sub=='/mkdir':
                self.require_server(auth,sid,'can_files')
                rel = str(self.body_json().get('path',''))
                self.file_policy(auth,rel)
                f = e.safe_server_path(sid,rel)
                f.mkdir(parents=False,exist_ok=False)
                e.log_audit(auth['username'],'folder_created',sid+' '+rel)
                return self.json({'ok':True},201)
            if sub in ('/file','/text'):
                self.require_server(auth,sid,'can_files')
                relative = get('path')
                target = e.safe_server_path(sid,relative)
                if method=='GET' and sub=='/text':
                    if not target.is_file() or target.stat().st_size > 1024*1024:
                        raise APIError(400,'Only existing text files up to 1 MiB can be edited.')
                    if target.suffix.lower() in ('.jar','.zip','.dat','.mca','.class','.dll','.exe'):
                        raise APIError(400,'Binary files cannot be edited as text.')
                    return self.json({'content':target.read_text('utf-8')})
                if method=='GET' and sub=='/file':
                    if not target.is_file():
                        raise APIError(404,'File not found.')
                    return self.send_file(target)
                if method=='PUT' and sub=='/file':
                    self.file_policy(auth,relative)
                    try:
                        length = int(self.headers.get('Content-Length','-1'))
                    except ValueError:
                        raise APIError(400,'Invalid upload size.')
                    if length < 0 or length > UPLOAD_LIMIT:
                        raise APIError(413,'Upload limit is 64 MiB per file.')
                    if not target.parent.exists() or not target.parent.is_dir():
                        raise APIError(400,'Parent folder must exist.')
                    if target.is_dir():
                        raise APIError(400,'Cannot overwrite a folder.')
                    temp = target.parent / ('.rte-upload-'+secrets.token_hex(12))
                    try:
                        with temp.open('xb') as out:
                            left = length
                            while left:
                                chunk = self.rfile.read(min(65536,left))
                                if not chunk:
                                    raise APIError(400,'Upload terminated early.')
                                out.write(chunk)
                                left -= len(chunk)
                        temp.replace(target)
                    finally:
                        temp.unlink(missing_ok=True)
                    e.log_audit(auth['username'],'file_uploaded',sid+' '+relative)
                    return self.json({'ok':True})
                if method=='DELETE' and sub=='/file':
                    self.file_policy(auth,relative)
                    if not target.is_file():
                        raise APIError(400,'Only files can be deleted.')
                    target.unlink()
                    e.log_audit(auth['username'],'file_deleted',sid+' '+relative)
                    return self.json({'ok':True})
            if method=='GET' and sub=='/backups':
                self.require_server(auth,sid,'can_files')
                return self.json({'backups':e.backup_list(sid)})
            if method=='POST' and sub=='/backups':
                self.require_server(auth,sid,'can_files')
                backup = e.make_backup(sid)
                e.log_audit(auth['username'],'backup_created',sid+' '+backup['name'])
                return self.json({'backup':backup},201)
            if method=='GET' and sub=='/backup-file':
                self.require_server(auth,sid,'can_files')
                name = get('name')
                if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{6}\.zip',name):
                    raise APIError(400,'Invalid backup file name.')
                file = e.BACKUPS_ROOT / sid / name
                if not file.is_file():
                    raise APIError(404,'Backup not found.')
                return self.send_file(file)
        raise APIError(404,'Unknown endpoint.')

    def file_policy(self, auth, relative):
        if not relative or relative in ('.','..'):
            raise APIError(400,'Choose a file or folder path.')
        if auth['role'] != 'customer':
            return
        path = Path(relative.replace('\\','/'))
        protected = {'server.properties','eula.txt','rte-console.log','run.bat','run.sh','start.bat','start.sh','server.jar'}
        if path.name.casefold() in protected or path.suffix.lower() in ('.bat','.cmd','.ps1','.exe','.dll','.sh','.py','.pyd'):
            raise APIError(403,'Customers cannot change server boot files or executable scripts.')
        if path.suffix.lower() == '.jar' and not any(part.lower() in ('mods','plugins') for part in path.parts[:-1]):
            raise APIError(403,'Upload mod/plugin jars inside mods/ or plugins/.')

    def send_file(self,path):
        name = path.name.replace('"','_')
        self.send_response(200)
        self.send_header('Content-Type','application/octet-stream')
        self.send_header('Content-Disposition',f'attachment; filename="{name}"')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(path.stat().st_size))
        self.end_headers()
        with path.open('rb') as f:
            while data := f.read(65536):
                self.wfile.write(data)

    def cookie(self,token,maxage=None):
        # For HTTPS reverse proxy, set RTE_SECURE_COOKIE=1.
        val = f'rte_session={token}; HttpOnly; SameSite=Strict; Path=/'
        if os.getenv('RTE_SECURE_COOKIE') == '1':
            val += '; Secure'
        if maxage is not None:
            val += f'; Max-Age={maxage}'
        return val

    def do_GET(self): self.handle_errors()
    def do_POST(self): self.handle_errors()
    def do_PUT(self): self.handle_errors()
    def do_DELETE(self): self.handle_errors()
    def do_HEAD(self): self.handle_errors()

    def handle_errors(self):
        try:
            self.dispatch()
        except APIError as exc:
            self.json({'error':str(exc)},exc.status)
        except (ValueError,PermissionError,FileNotFoundError,IsADirectoryError,FileExistsError,UnicodeError) as exc:
            self.json({'error':str(exc)},400)
        except sqlite3.IntegrityError as exc:
            self.json({'error':'A database constraint was not satisfied (possibly a duplicate username or port).'},409)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as exc:
            print('Unhandled RTE Hosting error:',repr(exc),file=sys.stderr)
            traceback.print_exc()
            try:
                self.json({'error':'An internal error occurred; see local logs.'},500)
            except OSError:
                pass


class PortalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_server(host='127.0.0.1',port=8080):
    if host not in ('127.0.0.1','localhost','::1') and os.getenv('RTE_ALLOW_LAN_HTTP') != '1':
        raise ValueError('Binding to LAN interfaces is disabled. Use a TLS reverse proxy on the same machine. See SECURITY.md.')
    e.init_db()
    app = PortalServer((host,port),PortalHandler)
    return app


def main():
    parser = argparse.ArgumentParser(description='RTE Hosting desktop and portal')
    parser.add_argument('--host',default=os.getenv('RTE_HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.getenv('RTE_PORT','8080')))
    parser.add_argument('--headless',action='store_true',help='Do not open a desktop window')
    args = parser.parse_args()
    app = start_server(args.host,args.port)
    url = f'http://127.0.0.1:{args.port}'
    print(f'RTE Hosting {e.APP_VERSION} listening at {url}')
    if args.headless:
        try:
            app.serve_forever(poll_interval=.3)
        except KeyboardInterrupt:
            pass
        finally:
            e.MANAGER.shutdown_all()
            app.server_close()
        return
    threading.Thread(target=app.serve_forever,daemon=True).start()
    try:
        import webview
        webview.create_window('RTE Hosting | Server Manager',url,width=1300,height=840,min_size=(950,650),background_color='#0B101B')
        webview.start(gui='edgechromium')
    except (ImportError,Exception) as exc:
        print('Embedded WebView unavailable, opening browser:',repr(exc))
        webbrowser.open(url)
        try:
            while True:
                time.sleep(.5)
        except KeyboardInterrupt:
            pass
    finally:
        e.MANAGER.shutdown_all()
        app.shutdown()
        app.server_close()

if __name__ == '__main__':
    main()
