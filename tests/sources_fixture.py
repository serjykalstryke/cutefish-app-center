"""Headless sources/channel fixture: writes only private test records."""
import json
import os
from pathlib import Path
import sys
r=json.loads(sys.stdin.readline());root=Path(os.environ['APP_CENTER_SOURCES_FIXTURE_DIR'])
state=root/'source-state.json';enabled=json.loads(state.read_text()) if state.exists() else True
source=dict(source='deb',id='debian-main',name='Debian main',display_name='Debian main',scope='system',enabled=enabled)
item=dict(source='snap',id='example',name='Example',scope='system',channel='latest/stable',installed=True,summary='A test application',icon='application-x-executable')
if r['op']=='discover':result=dict(items=[],warnings=[])
elif r['op']=='sources':result=dict(providers=[dict(id='deb',name='Native (Debian)',installed=True,available=True),dict(id='flatpak',name='Flatpak',installed=True,available=True),dict(id='snap',name='Snap',installed=False,available=False)],repositories=[source,dict(source='flatpak',id='flathub',display_name='Flathub',display_url='https://dl.flathub.org/repo/',scope='system',enabled=True,verified=True,installed_count=2)])
elif r['op']=='plan_source':
 (root/'source-plan.json').write_text(json.dumps(r));result=dict(plan=dict(target=r['target'],action=r['action'],title='Review '+r['action']+' '+r['target']['id'],note='Private source fixture review',fingerprint='a'*64))
elif r['op']=='apply_source':
 (root/'source-apply.json').write_text(json.dumps(r));state.write_text(json.dumps(False));result=dict(message='Software source changes completed.')
elif r['op']=='list':result=dict(items=[dict(item,application_key='example',application_name='Example',variants=[item])],warnings=[],total=1)
elif r['op']=='details':
 item=dict(r['target']);selected=item.get('requested_channel','latest/stable')
 item.update(details_loaded=True,publisher='Fixture Publisher',version='2',tracking_channel='latest/stable',requested_channel=selected,channel_change=selected!='latest/stable',channel_options=[dict(channel='latest/stable',version='1'),dict(channel='latest/beta',version='2')],can_open=False,screenshots=[])
 result=dict(item=item,warnings=[])
elif r['op']=='plan':
 (root/'software-plan.json').write_text(json.dumps(r));result=dict(plan=dict(target=r['target'],action=r['action'],note='Private software fixture review',changes=[],fingerprint='b'*64))
else:raise RuntimeError('Unsupported private fixture operation')
print(json.dumps(dict(event='result',ok=True,**result)))
