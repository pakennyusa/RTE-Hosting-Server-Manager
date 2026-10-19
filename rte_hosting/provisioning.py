"""Version discovery, Java inventory, and official Minecraft distribution downloads.

Only official providers; never accept arbitrary binary URLs from a client.
Java itself is NOT downloaded automatically. Administrators install licensed runtimes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

AGENT = 'RTE-Hosting-Server-Manager/0.2.0 (https://github.com/pakennyusa/RTE-Hosting-Server-Manager)'
HOSTS = {'piston-meta.mojang.com','piston-data.mojang.com','launcher.mojang.com',
         'fill.papermc.io','fill-data.papermc.io','api.purpurmc.org',
         'meta.fabricmc.net','maven.fabricmc.net'}
MAX_JAR_BYTES = 320 * 1024 * 1024
VERSION = re.compile(r'^[A-Za-z0-9._-]{1,40}$')


def official_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.hostname not in HOSTS:
        raise ValueError('Only approved HTTPS Minecraft distribution endpoints are allowed.')
    return url


def request(url):
    return urllib.request.Request(official_url(url), headers={'User-Agent':AGENT, 'Accept':'application/json, application/octet-stream'})


def json_get(url):
    with urllib.request.urlopen(request(url),timeout=12) as response:
        official_url(response.geturl())
        if int(response.headers.get('Content-Length','0') or 0) > 3_000_000:
            raise ValueError('Metadata response is too large.')
        blob = response.read(3_000_001)
        if len(blob) > 3_000_000:
            raise ValueError('Metadata response is too large.')
    return json.loads(blob)


def detect_java():
    locations=[]
    def add(path):
        if not path: return
        candidate=Path(path).expanduser()
        if candidate.is_file() and candidate.name.lower() in ('java.exe','java'):
            locations.append(candidate)
    add(shutil.which('java'))
    if os.environ.get('JAVA_HOME'):
        add(Path(os.environ['JAVA_HOME'])/'bin'/'java.exe')
        add(Path(os.environ['JAVA_HOME'])/'bin'/'java')
    if os.name == 'nt':
        try:
            result=subprocess.run(['where.exe','java'],capture_output=True,text=True,timeout=4)
            for line in result.stdout.splitlines(): add(line.strip())
        except (OSError,subprocess.TimeoutExpired): pass
        for var in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
            root=os.environ.get(var)
            if root:
                for vendor in ('Java','Eclipse Adoptium','Microsoft','BellSoft','Zulu','Amazon Corretto','Temurin'):
                    vendor_path=Path(root)/vendor
                    if vendor_path.is_dir():
                        for folder in list(vendor_path.iterdir())[:25]: add(folder/'bin'/'java.exe')
    records=[]
    seen=set()
    for path in locations[:80]:
        resolved=str(path.resolve())
        if resolved.casefold() in seen:continue
        seen.add(resolved.casefold())
        try:
            proc=subprocess.run([resolved,'-version'],capture_output=True,text=True,timeout=5,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
            combined=proc.stderr+'\n'+proc.stdout
            match=re.search(r'version\s+"?([0-9][0-9._+]*)',combined,re.I) or re.search(r'openjdk\s+([0-9]+)',combined,re.I)
            if not match: continue
            value=match.group(1)
            major=int(value.split('.')[1] if value.startswith('1.') else value.split('.')[0])
            records.append({'path':resolved,'version':value,'major':major})
        except (OSError,subprocess.TimeoutExpired,ValueError):continue
    return sorted(records,key=lambda x:x['major'],reverse=True)


def recommended_java(game_version):
    """Conservative baseline; modpacks/Forge builds can require another JDK."""
    if re.match(r'^26\.', game_version or ''):return 25
    parts=re.findall(r'\d+',game_version or '')
    if not parts:return 21
    major,minor,patch=(list(map(int,parts[:3]))+[0,0,0])[:3]
    if major == 1:
        if minor>=20:return 21
        if minor>=17:return 17
        if minor==16 and patch>=5:return 16
        if minor>=12:return 11
        return 8
    return 21


def choose_java(game_version, choices=None):
    options = choices if choices is not None else detect_java()
    recommended = recommended_java(game_version)
    compatible=sorted((o for o in options if o['major']>=recommended),key=lambda o:o['major'])
    return {'recommended_major':recommended,'best':compatible[0] if compatible else None,'installed':options}


def available_versions(framework):
    if framework == 'Vanilla':
        manifest=json_get('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json')
        return [v['id'] for v in manifest['versions'] if v['type']=='release'][:65]
    if framework == 'Paper':
        payload=json_get('https://fill.papermc.io/v3/projects/paper')
        return [v for group in payload['versions'].values() for v in group][:70]
    if framework == 'Purpur':
        return json_get('https://api.purpurmc.org/v2/purpur')['versions'][-70:][::-1]
    if framework == 'Fabric':
        return [v['version'] for v in json_get('https://meta.fabricmc.net/v2/versions/game') if v.get('stable')][:65]
    raise ValueError('Automated downloads are available for Vanilla, Paper, Purpur, and Fabric. Other frameworks require their official installer.')


def resolve_download(framework, version):
    if not VERSION.fullmatch(version):raise ValueError('Select a valid Minecraft release version.')
    if framework == 'Vanilla':
        manifest=json_get('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json')
        item=next((x for x in manifest['versions'] if x['id']==version and x['type']=='release'),None)
        if not item:raise ValueError('Official release not found.')
        data=json_get(item['url'])
        server=data.get('downloads',{}).get('server')
        if not server:raise ValueError('Official server download is not available for this release.')
        return {'url':official_url(server['url']),'digest':server['sha1'],'hash_type':'sha1','build':'official'}
    if framework == 'Paper':
        builds=json_get(f'https://fill.papermc.io/v3/projects/paper/versions/{version}/builds')
        if not isinstance(builds,list):raise ValueError('PaperMC did not return a build list.')
        stable=next((b for b in builds if b.get('channel')=='STABLE' and b.get('downloads',{}).get('server:default')),None)
        if not stable:raise ValueError('No stable Paper build for this version. Choose another version.')
        entry=stable['downloads']['server:default']
        sha=entry.get('checksums',{}).get('sha256','')
        if not re.fullmatch(r'[a-fA-F0-9]{64}',sha):raise ValueError('Paper SHA-256 checksum unavailable.')
        return {'url':official_url(entry['url']),'digest':sha,'hash_type':'sha256','build':str(stable['id'])}
    if framework == 'Purpur':
        info=json_get(f'https://api.purpurmc.org/v2/purpur/{version}')
        build=info.get('builds',{}).get('latest')
        if not build:raise ValueError('No Purpur builds available.')
        return {'url':f'https://api.purpurmc.org/v2/purpur/{version}/{build}/download','digest':'','hash_type':'','build':str(build)}
    if framework == 'Fabric':
        loaders=json_get(f'https://meta.fabricmc.net/v2/versions/loader/{version}')
        loader=next((l.get('loader',{}).get('version') for l in loaders if l.get('loader',{}).get('stable')),None)
        installers=json_get('https://meta.fabricmc.net/v2/versions/installer')
        installer=next((i['version'] for i in installers if i.get('stable')),None)
        if not loader or not installer:raise ValueError('No stable Fabric loader/installer was found for this game release.')
        url=f'https://meta.fabricmc.net/v2/versions/loader/{version}/{loader}/{installer}/server/jar'
        return {'url':url,'digest':'','hash_type':'','build':loader}
    raise ValueError('Install this framework manually using the vendor installer.')


def download_framework(server, framework, version):
    from . import engine as e
    sid=server['id']
    if e.MANAGER.is_running(sid):raise ValueError('Stop the Minecraft server before installing or updating the framework.')
    if framework not in ('Vanilla','Paper','Purpur','Fabric'):
        raise ValueError('Automated installation is not available for this framework.')
    spec=resolve_download(framework,version)
    folder=e.server_dir(sid).resolve()
    if not folder.is_dir():raise FileNotFoundError('Server directory not found.')
    existing=e.validate_jar_name(server['jar'])
    target=folder/existing
    if target.is_symlink():raise PermissionError('Cannot replace a linked server JAR.')
    scratch=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.rte-download-',suffix='.part',dir=folder,delete=False) as tmp:
            scratch=Path(tmp.name)
            with urllib.request.urlopen(request(spec['url']),timeout=35) as response:
                official_url(response.geturl())
                expected_size=int(response.headers.get('Content-Length','0') or 0)
                if expected_size>MAX_JAR_BYTES:raise ValueError('Download exceeds the configured size limit.')
                dig=hashlib.new(spec['hash_type']) if spec['hash_type'] else None
                size=0
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    size+=len(chunk)
                    if size>MAX_JAR_BYTES:raise ValueError('Download exceeds the configured size limit.')
                    tmp.write(chunk)
                    if dig:dig.update(chunk)
        if size<4096:raise ValueError('Downloaded file is unexpectedly small.')
        if dig and dig.hexdigest().lower()!=spec['digest'].lower():raise ValueError('Checksum verification failed. Original server.jar was not changed.')
        with scratch.open('rb') as handle:
            if handle.read(2)!=b'PK':raise ValueError('The download is not a JAR archive.')
        # Atomic replacement, no duplicate world or staging directory left behind.
        os.replace(scratch,target)
        scratch=None
        e.execute('UPDATE servers SET framework=?,version=?,jar=?,launch_mode=? WHERE id=?',
                  (framework,version,target.name,'jar',sid))
        return {'framework':framework,'version':version,'build':spec['build'],'filename':target.name,'size':size,
                'sha256':hashlib.sha256(target.read_bytes()).hexdigest(), 'java':choose_java(version)}
    finally:
        if scratch and scratch.exists():scratch.unlink()
