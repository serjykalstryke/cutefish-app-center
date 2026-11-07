"""Private library/update fixture. Applying writes a marker, never changes packages."""
import json
import os
from pathlib import Path
import sys
import time

request=json.loads(sys.stdin.readline());root=Path(os.environ['APP_CENTER_MANAGEMENT_FIXTURE_DIR']);root.mkdir(parents=True,exist_ok=True)
base=dict(source='deb',scope='system',version='1.0',installed_version='1.0',architecture='amd64',installed=True,icon='application-x-executable',is_application=True,summary='An installed application')
items=[dict(base,id='alpha',name='Alpha',install_key='deb-alpha'),dict(base,id='zulu',name='Zulu',install_key='deb-zulu'),dict(base,id='libc6',name='libc6',install_key='deb-libc6',is_application=False,protected=True),dict(base,source='flatpak',id='org.example.Writer',name='Writer',install_key='flatpak-user',scope='user',arch='x86_64',branch='stable',remote='flathub'),dict(base,source='flatpak',id='org.example.Writer',name='Writer',install_key='flatpak-system',scope='system',arch='x86_64',branch='stable',remote='flathub'),dict(base,source='flatpak',id='org.example.Platform',name='Example Platform',install_key='flatpak-runtime',is_application=False,ref_kind='runtime',arch='x86_64',branch='stable',remote='flathub'),dict(base,source='snap',id='core24',name='Core 24',install_key='snap-core',is_application=False),dict(base,source='appimage',id='a'*64,name='Portable',install_key='appimage-portable')]
updates=[dict(i,update_available=True,update_version='2.0',version='2.0',package_id=i['id']+';2.0;amd64;repo') for i in items if i['id']!='alpha' and i['source']!='appimage']
if request['op']=='discover':result=dict(items=[],warnings=[])
elif request['op']=='library':
 if (root/'updated').exists():items=[dict(i,version='2.0',installed_version='2.0') for i in items]
 result=dict(items=items,warnings=[],complete=True)
elif request['op']=='update_inventory':
 time.sleep(0.4)
 failed=(root/'fail-source').exists()
 result=dict(items=[] if (root/'updated').exists() else updates,warnings=['snap: Source unavailable'] if failed else [],complete=not failed)
elif request['op']=='details':
 item=request['target'];item.update(details_loaded=True,description='Installed management fixture',can_open=False,screenshots=[]);result=dict(item=item,warnings=[])
elif request['op']=='plan_all_updates':
 changes=[dict(info='update',id=i['id'],name=i['name'],version='2.0') for i in updates]
 result=dict(plan=dict(groups=[dict(source='deb',scope='system',name='Debian system',targets=['zulu','libc6'],changes=changes[:2],note='Applications and system packages'),dict(source='flatpak',scope='system',name='Flatpak system',targets=['writer','platform'],changes=changes[2:5],note='Includes shared runtimes'),dict(source='snap',scope='system',name='Snap system',targets=['core24'],changes=changes[5:],note='Includes Snap bases')],fingerprint='a'*64,note='All software and sources are updated, regardless of the current filters. AppImages remain manual.'))
elif request['op']=='apply_all_updates':
 assert request['plan']['fingerprint']=='a'*64
 (root/'apply.json').write_text(json.dumps(request['plan']))
 def update(index,state,phase='',message='',percent=None):
  print(json.dumps(dict(event='update_progress',index=index,state=state,phase=phase,message=message,percent=percent)),flush=True)
 update(0,'running','authorization','Approve the administrator prompt to continue.')
 time.sleep(0.35)
 update(0,'running','downloading','Downloading libc6…',40)
 time.sleep(0.2)
 update(0,'completed')
 update(1,'running','working','Preparing Flatpak changes…')
 time.sleep(0.2)
 if (root/'partial').exists():
  update(1,'failed',message='Authentication was cancelled.')
  update(2,'skipped')
  result=dict(message='Some updates could not be completed.',completed=['Debian system'],errors=['Authentication was cancelled.'],pending=['Snap system'],restart=True,restart_notice='A system restart is required.')
 else:
  update(1,'completed');update(2,'completed');(root/'updated').touch()
  result=dict(message='Updates completed.',errors=[],restart=True,restart_notice='A system restart is required.')
else:raise RuntimeError('The fixture does not run real software operations')
print(json.dumps(dict(event='result',ok=True,**result)),flush=True)
