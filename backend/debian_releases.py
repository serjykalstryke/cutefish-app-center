"""Reviewed Debian archive selection. Only the installed helper commits writes.

All paths and archive addresses are fixed here. Caller plans supply a release
identifier and fingerprint, never destination paths, file contents or commands.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import tempfile
import urllib.parse

class ReleaseError(Exception):
    pass

RELEASES = {'system': 'Original system configuration', 'stable': 'Debian Stable',
            'testing': 'Debian Testing', 'unstable': 'Debian Unstable'}
KEYRING = '/usr/share/keyrings/debian-archive-keyring.gpg'
MANAGED = '/etc/apt/sources.list.d/cutefish-app-center-debian.sources'
STATE = '/var/lib/cutefish-app-center/debian-sources.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o644):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


class System:
    def __init__(self, root=Path('/')):
        # The root override is for disposable filesystem tests; the privileged
        # entry point always constructs System() with the literal system root.
        self.root = Path(root)
        self.expected_uid = 0 if self.root == Path('/') else os.getuid()

    def path(self, value):
        return self.root / value.lstrip('/')

    def read(self, path, limit=256*1024):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.expected_uid or
                info.st_mode & 0o022 or info.st_size > limit):
            raise ReleaseError('Source configuration must be a regular administrator-owned file: ' + str(path))
        return path.read_bytes()

    def state(self):
        path = self.path(STATE)
        if not path.exists():return None
        try:
            data = json.loads(self.read(path, 1024*1024))
            if data.get('version') != 1 or data.get('release') not in RELEASES or data.get('status') not in ('ready','applying'):
                raise ValueError()
            for entry in data['originals']:
                name = entry['path']
                if (name != '/etc/apt/sources.list' and
                        (str(Path(name).parent) != '/etc/apt/sources.list.d' or Path(name).suffix not in ('.list','.sources'))):
                    raise ValueError()
                for field in ('original','disabled'):
                    if not re.fullmatch(r'[0-9a-f]{64}', entry[field]):raise ValueError()
            return data
        except (ValueError, KeyError, TypeError) as error:
            raise ReleaseError('The saved Debian source configuration needs administrator repair.') from error

    def official_uri(self, value):
        if value.startswith('mirror+file:'):value=value.rstrip('/')
        if value in ('mirror+file:/etc/apt/mirrors/debian.list', 'mirror+file:/etc/apt/mirrors/debian-security.list'):
            mirrors = self.read(self.path(value.removeprefix('mirror+file:'))).decode().splitlines()
            return bool(mirrors) and all(not line.strip() or line.lstrip().startswith('#') or self.official_uri(line.split()[0]) for line in mirrors)
        try:
            url = urllib.parse.urlsplit(value)
            return (url.scheme in ('https','http') and url.hostname in ('deb.debian.org','security.debian.org','ftp.debian.org')
                    and not url.username and not url.password and not url.query and not url.fragment
                    and url.port in (None,80,443) and url.path.rstrip('/') in ('/debian','/debian-security'))
        except ValueError:return False

    def validate_options(self, fields):
        allowed = {'types','uris','suites','components','architectures','signed-by','enabled'}
        if set(fields) - allowed:
            raise ReleaseError('A Debian source uses custom options. Edit this configuration with the system tools before switching releases.')
        if fields.get('signed-by', KEYRING) != KEYRING:
            raise ReleaseError('Release switching requires the dedicated Debian archive signing keyring.')
        if not set(fields.get('types','deb').split()) <= {'deb','deb-src'}:
            raise ReleaseError('Unsupported Debian source type.')
        components = fields.get('components','main').split()
        if not components or not set(components) <= {'main','contrib','non-free','non-free-firmware'}:
            raise ReleaseError('Unsupported Debian archive components.')
        for arch in fields.get('architectures','').split():
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',arch):raise ReleaseError('Invalid source architecture.')

    def disable_file(self, path, raw):
        text = raw.decode('utf-8');entries=[]
        if path.suffix == '.sources':
            blocks = re.split(r'(\n[ \t]*\n)',text)
            for index in range(0,len(blocks),2):
                block=blocks[index];fields={};last=None
                for line in block.splitlines():
                    if not line.strip() or line.lstrip().startswith('#'):continue
                    if line[:1].isspace() and last:fields[last]+=' '+line.strip();continue
                    if ':' not in line:raise ReleaseError('Cannot parse Debian source file: '+str(path))
                    key,value=line.split(':',1);last=key.lower();fields[last]=value.strip()
                uris=fields.get('uris','').split()
                if not uris or fields.get('enabled','yes').lower()=='no':continue
                official=[self.official_uri(uri) for uri in uris]
                if not any(official):continue
                if not all(official):raise ReleaseError('A source stanza mixes Debian and third-party addresses.')
                self.validate_options(fields);entries.append(fields)
                if re.search(r'^Enabled:',block,re.M|re.I):
                    block=re.sub(r'^Enabled:.*$', 'Enabled: no',block,flags=re.M|re.I)
                else:block=block.rstrip('\n')+'\nEnabled: no\n'
                blocks[index]=block
            return ''.join(blocks).encode(),entries
        lines=text.splitlines(keepends=True)
        for index,line in enumerate(lines):
            if not re.match(r'^\s*deb(?:-src)?\s',line):continue
            match=re.match(r'^\s*(deb(?:-src)?)\s+(?:\[([^\]]*)\]\s+)?(\S+)\s+(\S+)\s+(.+?)(?:\s+#.*)?$',line.strip())
            if not match:raise ReleaseError('Cannot parse source list entry: '+str(path))
            kind,options,uri,suite,components=match.groups()
            if not self.official_uri(uri):continue
            fields=dict(types=kind,uris=uri,suites=suite,components=components)
            for option in shlex.split(options or ''):
                key,sep,value=option.partition('=')
                if not sep or key not in ('arch','signed-by'):raise ReleaseError('A Debian source uses unsupported custom options.')
                fields['architectures' if key=='arch' else 'signed-by']=value.replace(',',' ') if key=='arch' else value
            self.validate_options(fields);entries.append(fields)
            lines[index]='# Disabled by Cutefish App Center: '+line
        return ''.join(lines).encode(),entries

    def source_files(self):
        directory=self.path('/etc/apt/sources.list.d')
        for parent in (self.path('/etc/apt'),directory):
            info=parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=self.expected_uid or info.st_mode & 0o022:
                raise ReleaseError('APT source directories must be administrator-owned directories.')
        files=sorted(list(directory.glob('*.list'))+list(directory.glob('*.sources')))
        primary=self.path('/etc/apt/sources.list')
        if primary.exists():files.insert(0,primary)
        if len(files)>128:raise ReleaseError('Too many source files for automatic release switching.')
        return files

    def generated(self, config, release):
        def stanza(uris,suites):
            result=f'Types: {" ".join(config["types"])}\nURIs: {uris}\nSuites: {suites}\nComponents: {" ".join(config["components"])}\nSigned-By: {KEYRING}\n'
            if config['architectures']:result+='Architectures: '+' '.join(config['architectures'])+'\n'
            return result
        body='# Managed by Cutefish App Center. Restore the original configuration in Software Sources.\n'
        suites=release + (' stable-updates' if release=='stable' else '')
        if release=='stable' and config.get('backports'):suites+=' stable-backports'
        body+=stanza('https://deb.debian.org/debian',suites)
        if release!='unstable':body+='\n'+stanza('https://deb.debian.org/debian-security',release+'-security')
        return body.encode()

    def build(self, release):
        if release not in RELEASES:raise ReleaseError('Invalid Debian release.')
        if not self.path('/etc/debian_version').is_file():raise ReleaseError('Debian release switching is available only on Debian-based systems.')
        keyring=self.path(KEYRING)
        if keyring.is_symlink():
            if keyring.lstat().st_uid!=self.expected_uid:raise ReleaseError('The Debian keyring link must be administrator-owned.')
            keyring=keyring.resolve(strict=True)
            if keyring.parent!=self.path('/usr/share/keyrings').resolve():raise ReleaseError('The Debian archive keyring must remain in the system keyring directory.')
        self.read(keyring,8*1024*1024)
        state=self.state();managed=self.path(MANAGED);edits={};originals=[];entries=[]
        if state:
            if release!='system' and state['status']!='ready':raise ReleaseError('A previous source change was interrupted. Restore the original configuration first.')
            for entry in state['originals']:
                path=self.path(entry['path']);current=self.read(path)
                permitted={entry['disabled']} if state['status']=='ready' else {entry['disabled'],entry['original']}
                if stat.S_IMODE(path.stat().st_mode)!=entry['mode']:raise ReleaseError('A managed source file changed permissions: '+entry['path'])
                if digest(current) not in permitted:raise ReleaseError('A managed source file changed outside App Center: '+entry['path'])
                if release=='system':
                    backup=self.path('/var/lib/cutefish-app-center/source-backups')/entry['original']
                    # Non-root review uses the hash in the protected state file.
                    data=self.read(backup) if os.access(backup,os.R_OK) else None
                    if data is not None and digest(data)!=entry['original']:raise ReleaseError('The saved original source does not match its backup.')
                    edits[entry['path']]=(current,data,entry['mode'],entry['original'])
            current=self.read(managed) if managed.exists() else None
            if state['status']=='ready' and (current is None or digest(current)!=state['generated']):raise ReleaseError('The managed Debian source file changed outside App Center.')
            if current is not None and digest(current) not in set(state.get('allowed_generated',[state['generated']])):raise ReleaseError('The managed Debian source file needs administrator repair.')
            for path in self.source_files():
                if path==managed or any(path==self.path(e["path"]) for e in state["originals"]):continue
                _,found=self.disable_file(path,self.read(path))
                if found:raise ReleaseError('Additional Debian sources were enabled outside App Center. Reconcile them before switching releases.')
            data=None if release=='system' else self.generated(state['config'],release)
            edits[MANAGED]=(current,data,0o644,digest(data) if data is not None else '')
            config=state['config'];originals=state['originals']
        else:
            if release=='system':raise ReleaseError('The original system configuration is already in use.')
            if managed.exists():raise ReleaseError('The App Center source filename is already used by an unmanaged file.')
            for path in self.source_files():
                raw=self.read(path);disabled,found=self.disable_file(path,raw)
                if not found:continue
                relative='/'+str(path.relative_to(self.root));mode=stat.S_IMODE(path.stat().st_mode)
                originals.append(dict(path=relative,original=digest(raw),disabled=digest(disabled),mode=mode))
                edits[relative]=(raw,disabled,mode,digest(disabled));entries.extend(found)
            if not entries:raise ReleaseError('No supported active official Debian repositories were found. Custom mirrors can be managed with the system tools.')
            if len(entries)>256:raise ReleaseError('Too many Debian archive entries for an automatic switch.')
            arches={tuple(sorted(e.get('architectures','').split())) for e in entries}
            if len(arches)>1:raise ReleaseError('Debian sources use different architecture restrictions. Reconcile them before switching releases.')
            config=dict(types=sorted({t for e in entries for t in e['types'].split()}),
                        components=sorted({c for e in entries for c in e['components'].split()}),
                        architectures=list(next(iter(arches))),backports=any('backports' in e['suites'] for e in entries),
                        original_archives=[{k:e[k] for k in ('types','uris','suites','components')} for e in entries])
            data=self.generated(config,release);edits[MANAGED]=(None,data,0o644,digest(data))
        changes=[dict(path=name,before=digest(old) if old is not None else '',after=after,mode=mode) for name,(old,new,mode,after) in sorted(edits.items())]
        if state and state['status']=='ready' and release==state['release']:raise ReleaseError('These Debian sources are already selected.')
        state_path=self.path(STATE);state_bytes=self.read(state_path,1024*1024) if state_path.exists() else None
        plan=dict(release=release,title='Use '+RELEASES[release],changes=changes,
                  current=state['release'] if state else 'system',configuration=((edits[MANAGED][1] or b'').decode() if release!='system' else
                  '\n\n'.join('\n'.join(k.title()+': '+e[k] for k in ('types','uris','suites','components')) for e in config.get('original_archives',[]))),
                  state_hash=digest(state_bytes) if state_bytes else '')
        if len(json.dumps(config).encode())>512*1024:raise ReleaseError('The Debian source configuration is too large for an automatic switch.')
        identity=json.dumps(plan,sort_keys=True,separators=(',',':')).encode();plan['fingerprint']=digest(identity)
        plan['note']=('This changes Debian’s system-wide software sources. It does not install or downgrade packages. '
                      'Refresh the catalog, then review all package changes through Update All. '
                      'Stable, Testing and Unstable follow Debian’s moving release tracks, including future version transitions.\n\n'
                      'Testing and Unstable change operating-system packages and can affect desktop compatibility. '
                      'Selecting Stable or restoring sources does not downgrade packages already upgraded.\n\n'
                      'Third-party repositories are kept and may not support the selected Debian release. '
                      'The original Debian configuration is backed up and can be restored if these files remain unchanged.\n\n'
                      + ('Restore the original source files.' if release=='system' else 'Official Debian archives use the Debian archive signing keyring.'))
        return plan,edits,dict(version=1,status='ready',release=release,originals=originals,config=config,
                               generated=edits[MANAGED][3])

    def status(self):
        state=None
        try:
            state=self.state()
            # A read-only preflight establishes whether supported sources exist.
            self.build('system' if state and state['status']=='applying' else 'testing' if not state or state['release']!='testing' else 'stable')
            return dict(available=True,current=state['release'] if state else 'system',managed=bool(state),
                        recovery=bool(state and state['status']=='applying'),
                        managed_files=[e['path'] for e in state['originals']]+[MANAGED] if state else [])
        except (OSError,UnicodeError,ReleaseError) as error:
            return dict(available=False,error=str(error),managed=bool(state),
                        managed_files=[e['path'] for e in state['originals']]+[MANAGED] if state else [])

    def plan(self, release):return self.build(release)[0]

    def apply(self, approved):
        plan,edits,new_state=self.build(approved.get('release'))
        if plan['fingerprint']!=approved.get('fingerprint'):raise ReleaseError('Debian source configuration changed. Review the switch again.')
        state_path=self.path(STATE);folder=state_path.parent;folder.mkdir(mode=0o755,parents=True,exist_ok=True)
        info=folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=self.expected_uid or info.st_mode & 0o022:raise ReleaseError('Unsafe source backup directory.')
        backup_dir=folder/'source-backups';backup_dir.mkdir(mode=0o700,exist_ok=True)
        info=backup_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=self.expected_uid or info.st_mode & 0o077:raise ReleaseError('Unsafe source backup directory.')
        parent_fd=os.open(folder.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(parent_fd)
        finally:os.close(parent_fd)
        old_state=self.read(state_path,1024*1024) if state_path.exists() else None
        old_managed=edits[MANAGED][0]
        # Durable backups and journal precede all edits. An interrupted operation
        # permits an explicit restore of these originals, never an unknown file.
        for entry in new_state['originals']:
            backup=backup_dir/entry['original']
            if not backup.exists():
                original=edits[entry['path']][0]
                if digest(original)!=entry['original']:raise ReleaseError('Original source backup is unavailable.')
                atomic(backup,original,0o600)
            elif digest(self.read(backup))!=entry['original']:raise ReleaseError('Source backup integrity check failed.')
        journal=dict(new_state,status='applying',allowed_generated=[new_state['generated']]+([digest(old_managed)] if old_managed else []))
        atomic(state_path,json.dumps(journal,sort_keys=True).encode())
        completed=[]
        try:
            for name,(old,new,mode,after) in edits.items():
                path=self.path(name)
                present=self.read(path) if path.exists() else None
                if present!=old:raise ReleaseError('A source changed while applying the review: '+name)
                completed.append(name)
                if new is None:
                    if name!=MANAGED:
                        new=self.read(backup_dir/after)
                        if digest(new)!=after:raise ReleaseError('Source backup integrity check failed.')
                    else:path.unlink(missing_ok=True)
                if new is not None:atomic(path,new,mode)
            for name,(_,_,_,after) in edits.items():
                path=self.path(name)
                if (digest(self.read(path)) if path.exists() else '')!=after:raise ReleaseError('Debian did not save the reviewed source configuration.')
            if approved['release']=='system':state_path.unlink()
            else:atomic(state_path,json.dumps(new_state,sort_keys=True).encode())
        except Exception as error:
            failed=[]
            for name in reversed(completed):
                old,_,mode,_=edits[name];path=self.path(name)
                try:
                    if old is None:path.unlink(missing_ok=True)
                    else:atomic(path,old,mode)
                except OSError:failed.append(name)
            if not failed:
                if old_state is None:state_path.unlink(missing_ok=True)
                else:atomic(state_path,old_state)
            raise ReleaseError(str(error)+ (' Restore the original configuration to recover the interrupted change.' if failed else ' The previous source configuration was restored.')) from error
        return dict(message='Debian sources changed. Refresh the Debian catalog, then review package upgrades with Update All.')
