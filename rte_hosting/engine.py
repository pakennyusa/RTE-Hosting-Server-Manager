"""Local Minecraft server manager and SQLite storage for RTE Hosting.

Security note: Minecraft jars, plugins and mods are executable third-party code.
This first release is intended for a trusted Windows machine, not isolation of
mutually untrusted tenants. See SECURITY.md before external deployment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import zipfile
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

APP_VERSION = '0.1.0'
FRAMEWORKS = ['Vanilla', 'Paper', 'Spigot', 'Purpur', 'Bukkit', 'Fabric', 'Forge', 'NeoForge', 'Quilt', 'Mohist', 'Arclight', 'Other']
DATA_ROOT = Path(os.getenv('RTE_HOSTING_DATA') or (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'RTE Hosting')).expanduser().resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_ROOT / 'hosting.sqlite3'
SERVERS_ROOT = DATA_ROOT / 'servers'
BACKUPS_ROOT = DATA_ROOT / 'backups'
SERVERS_ROOT.mkdir(exist_ok=True)
BACKUPS_ROOT.mkdir(exist_ok=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                passhash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','staff','customer')),
                created_at TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf TEXT NOT NULL, expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS servers (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, framework TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '', jar TEXT NOT NULL DEFAULT 'server.jar',
                launch_mode TEXT NOT NULL DEFAULT 'jar', java_path TEXT NOT NULL DEFAULT 'java',
                min_ram INTEGER NOT NULL DEFAULT 1024, max_ram INTEGER NOT NULL DEFAULT 2048,
                port INTEGER NOT NULL UNIQUE, eula_accepted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assignments (
                server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                can_control INTEGER NOT NULL DEFAULT 1,
                can_console INTEGER NOT NULL DEFAULT 0,
                can_files INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(server_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                actor TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL
            );
        ''')


def rows(sql, args=()):
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args).fetchall()]


def one(sql, args=()):
    with connect() as db:
        item = db.execute(sql, args).fetchone()
        return dict(item) if item else None


def execute(sql, args=()):
    with connect() as db:
        result = db.execute(sql, args)
        return result.rowcount


def log_audit(actor, event, detail=''):
    execute('INSERT INTO audit(created_at,actor,event,detail) VALUES(?,?,?,?)', (utc_now(), actor, event, str(detail)[:600]))


def hash_password(password):
    if not 12 <= len(password) <= 256:
        raise ValueError('Password must be 12–256 characters long.')
    salt = secrets.token_bytes(16)
    rounds = 600_000
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, rounds)
    return f'pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}'


def verify_password(password, encoded):
    try:
        method, rounds, salt, digest = encoded.split('$')
        if method != 'pbkdf2_sha256':
            return False
        expected = bytes.fromhex(digest)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_user(username, password, role='customer'):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,31}', username):
        raise ValueError('Username must be 3–32 letters, numbers, dots, hyphens or underscores.')
    if role not in ('admin', 'staff', 'customer'):
        raise ValueError('Invalid role.')
    uid = str(uuid.uuid4())
    execute('INSERT INTO users(id,username,passhash,role,created_at) VALUES(?,?,?,?,?)',
            (uid, username, hash_password(password), role, utc_now()))
    log_audit(username, 'user_created', f'{username} ({role})')
    return uid


def safe_user(user):
    return {k: user[k] for k in ('id','username','role','created_at','disabled') if k in user}


def create_session(user):
    token = secrets.token_urlsafe(42)
    csrf = secrets.token_urlsafe(32)
    expires = int(time.time()) + 12 * 3600
    execute('INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(?,?,?,?)',
            (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf, expires))
    return token, csrf


def get_session(token):
    if not token:
        return None
    result = one('''SELECT users.*,sessions.csrf,sessions.expires FROM sessions
        JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=?''',
        (hashlib.sha256(token.encode()).hexdigest(),))
    if not result or result['expires'] < int(time.time()) or result['disabled']:
        return None
    return result


def logout(token):
    if token:
        execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))


def server_dir(server_id):
    if not re.fullmatch(r'[a-f0-9-]{36}', str(server_id)):
        raise ValueError('Invalid server ID.')
    return SERVERS_ROOT / server_id


def safe_server_path(server_id, relative):
    base = server_dir(server_id).resolve()
    if not base.exists():
        raise FileNotFoundError('Server folder not found.')
    relative = str(relative or '').replace('\\', '/')
    if '\x00' in relative or relative.startswith('/') or re.match(r'^[A-Za-z]:', relative):
        raise ValueError('Invalid path.')
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base):
        raise PermissionError('Path must remain inside the server directory.')
    if candidate.is_symlink():
        raise PermissionError('Symbolic links are not supported.')
    return candidate


def validate_jar_name(name):
    if not re.fullmatch(r'[A-Za-z0-9_ .()+-]{1,120}\.jar', name, re.IGNORECASE):
        raise ValueError('Use a .jar file name in the server root.')
    return name


def create_server(body):
    name = str(body.get('name','')).strip()
    if not 3 <= len(name) <= 64:
        raise ValueError('Server name must be 3–64 characters.')
    framework = str(body.get('framework','Paper'))
    if framework not in FRAMEWORKS:
        raise ValueError('Unsupported framework label.')
    port = int(body.get('port', 25565))
    min_ram = int(body.get('min_ram', 1024))
    max_ram = int(body.get('max_ram', 2048))
    if not 1024 <= port <= 65535:
        raise ValueError('Port must be between 1024 and 65535.')
    if not 256 <= min_ram <= max_ram <= 131072:
        raise ValueError('RAM must be between 256 and 131072 MiB; minimum cannot exceed maximum.')
    mode = body.get('launch_mode', 'jar')
    if mode not in ('jar','script'):
        raise ValueError('Launch mode must be jar or script.')
    jar = validate_jar_name(str(body.get('jar','server.jar')))
    sid = str(uuid.uuid4())
    execute('''INSERT INTO servers(id,name,framework,version,jar,launch_mode,java_path,
          min_ram,max_ram,port,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
          (sid,name,framework,str(body.get('version',''))[:40],jar,mode,
           str(body.get('java_path','java'))[:300],min_ram,max_ram,port,utc_now()))
    folder = server_dir(sid)
    folder.mkdir(mode=0o700)
    (folder / 'eula.txt').write_text('eula=false\n', encoding='utf-8')
    (folder / 'server.properties').write_text(
        f'# RTE Hosting generated defaults\nserver-port={port}\nonline-mode=true\nmax-players=20\nmotd=An RTE Hosting Minecraft server\n', encoding='utf-8')
    return sid


def server_access(user, sid):
    server = one('SELECT * FROM servers WHERE id=?', (sid,))
    if not server:
        raise FileNotFoundError('Server not found.')
    if user['role'] in ('admin','staff'):
        return server, {'can_control':1,'can_console':1,'can_files':1}
    assn = one('SELECT * FROM assignments WHERE server_id=? AND user_id=?', (sid,user['id']))
    if not assn:
        raise PermissionError('This server is not assigned to your account.')
    return server, assn


def visible_servers(user):
    if user['role'] in ('admin','staff'):
        result = rows('SELECT * FROM servers ORDER BY created_at DESC')
    else:
        result = rows('''SELECT servers.* FROM servers JOIN assignments
         ON servers.id=assignments.server_id WHERE assignments.user_id=? ORDER BY servers.name''', (user['id'],))
    for s in result:
        s['running'] = MANAGER.is_running(s['id'])
        s['can_control'] = user['role'] != 'customer' or bool(one('SELECT can_control FROM assignments WHERE user_id=? AND server_id=?', (user['id'],s['id']))['can_control'])
    return result


def read_properties(server_id):
    path = safe_server_path(server_id, 'server.properties')
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text('utf-8', errors='replace').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v = line.split('=',1)
            result[k] = v
    return {k: result.get(k, '') for k in ('motd','max-players','online-mode','pvp','difficulty')}


def update_properties(server_id, updates, is_staff):
    allowed = {'motd','max-players','pvp','difficulty'} | ({'online-mode'} if is_staff else set())
    values = {k:str(v) for k,v in updates.items() if k in allowed}
    for k,v in values.items():
        if '\n' in v or '\r' in v or len(v) > 140:
            raise ValueError('Invalid server property value.')
        if k == 'max-players' and not 1 <= int(v) <= 1000:
            raise ValueError('Max players must be 1–1000.')
        if k in ('pvp','online-mode') and v not in ('true','false'):
            raise ValueError('Expected true or false.')
        if k == 'difficulty' and v not in ('peaceful','easy','normal','hard'):
            raise ValueError('Invalid difficulty.')
    path = safe_server_path(server_id, 'server.properties')
    lines = path.read_text('utf-8').splitlines() if path.exists() else []
    seen = set()
    for i,line in enumerate(lines):
        if '=' in line and not line.lstrip().startswith('#'):
            key = line.split('=',1)[0]
            if key in values:
                lines[i] = f'{key}={values[key]}'
                seen.add(key)
    for key in values.keys() - seen:
        lines.append(f'{key}={values[key]}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


class MinecraftManager:
    def __init__(self):
        self.procs = {}
        self.log_buffers = {}
        self.lock = threading.RLock()

    def is_running(self, sid):
        with self.lock:
            p = self.procs.get(sid)
            return bool(p and p.poll() is None)

    def tail(self, sid, n=100):
        with self.lock:
            if sid in self.log_buffers:
                return list(self.log_buffers[sid])[-n:]
        path = server_dir(sid) / 'rte-console.log'
        if path.exists():
            with path.open('r',encoding='utf-8',errors='replace') as f:
                return deque(f, maxlen=n)
        return []

    def _reader(self, sid, process):
        log_path = server_dir(sid) / 'rte-console.log'
        with log_path.open('a',encoding='utf-8',errors='replace') as log:
            for line in iter(process.stdout.readline, ''):
                with self.lock:
                    self.log_buffers.setdefault(sid,deque(maxlen=500)).append(line.rstrip('\r\n'))
                log.write(line)
                log.flush()
            process.wait()
            with self.lock:
                self.log_buffers.setdefault(sid,deque(maxlen=500)).append(f'[RTE Hosting] Process exited with code {process.returncode}.')

    def start(self, server):
        sid = server['id']
        folder = server_dir(sid)
        with self.lock:
            if self.is_running(sid):
                raise ValueError('Server is already running.')
            if not server['eula_accepted']:
                raise ValueError('Minecraft EULA has not been accepted for this server.')
            if server['launch_mode'] == 'jar':
                jar = folder / validate_jar_name(server['jar'])
                if not jar.is_file():
                    raise ValueError(f'Upload {server["jar"]} to the server file manager before starting.')
                args = [server['java_path'], f'-Xms{server["min_ram"]}M', f'-Xmx{server["max_ram"]}M', '-jar',jar.name,'nogui']
            else:
                if os.name != 'nt':
                    raise ValueError('The modded run.bat mode requires Windows.')
                script = folder / 'run.bat'
                if not script.is_file():
                    raise ValueError('Install the Forge/NeoForge server files including run.bat.')
                args = ['cmd.exe','/d','/c','run.bat']
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            try:
                proc = subprocess.Popen(args, cwd=folder, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding='utf-8', errors='replace',bufsize=1,creationflags=creationflags)
            except OSError as exc:
                raise ValueError(f'Failed to launch server: {exc}') from exc
            self.procs[sid] = proc
            self.log_buffers[sid] = deque([f'[RTE Hosting] Starting {server["name"]} ({server["framework"]}).'],maxlen=500)
            threading.Thread(target=self._reader,args=(sid,proc),daemon=True).start()
            return proc.pid

    def command(self, sid, command):
        if not command or '\n' in command or '\r' in command or len(command) > 400:
            raise ValueError('Command must be a single line (max 400 characters).')
        with self.lock:
            proc = self.procs.get(sid)
            if not proc or proc.poll() is not None or not proc.stdin:
                raise ValueError('Server is not running.')
            try:
                proc.stdin.write(command.rstrip()+'\n')
                proc.stdin.flush()
            except (OSError, ValueError, BrokenPipeError) as exc:
                raise ValueError('Server console is not available.') from exc

    def stop(self, sid):
        if not self.is_running(sid):
            raise ValueError('Server is not running.')
        self.command(sid,'stop')

    def shutdown_all(self, timeout=25):
        # Avoid leaving orphaned Java instances without a control plane.
        with self.lock:
            active = [(sid,p) for sid,p in self.procs.items() if p.poll() is None]
        for sid,p in active:
            try:
                self.command(sid,'stop')
            except ValueError:
                pass
        deadline = time.monotonic() + timeout
        for sid,p in active:
            try:
                p.wait(timeout=max(0.1,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()


MANAGER = MinecraftManager()


def list_files(server_id, relative=''):
    folder = safe_server_path(server_id, relative)
    if not folder.is_dir():
        raise ValueError('Not a directory.')
    items = []
    for p in folder.iterdir():
        if p.is_symlink():
            continue
        try:
            s = p.stat()
            items.append({'name':p.name,'directory':p.is_dir(),'size':s.st_size if p.is_file() else 0,
                          'path':str(p.relative_to(server_dir(server_id).resolve())).replace('\\','/')})
        except OSError:
            continue
    return sorted(items,key=lambda i:(not i['directory'],i['name'].casefold()))[:1500]


def make_backup(sid):
    if MANAGER.is_running(sid):
        raise ValueError('Stop the server before taking a consistent world backup.')
    folder = server_dir(sid)
    output_dir = BACKUPS_ROOT / sid
    output_dir.mkdir(parents=True,exist_ok=True)
    filename = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3) + '.zip'
    target = output_dir / filename
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED, compresslevel=3,allowZip64=True) as dest:
        for root,dirs,files in os.walk(folder,followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(root)/d).is_symlink()]
            for file in files:
                source = Path(root) / file
                if source.is_symlink() or file == 'rte-console.log':
                    continue
                dest.write(source,source.relative_to(folder))
    return {'name':filename,'size':target.stat().st_size}


def backup_list(sid):
    folder = BACKUPS_ROOT / sid
    if not folder.exists():
        return []
    return [{'name':p.name,'size':p.stat().st_size} for p in sorted(folder.glob('*.zip'),reverse=True)[:100]]
