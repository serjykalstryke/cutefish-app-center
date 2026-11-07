"""Cross-provider application fixture. Software actions only write test records."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

spec=importlib.util.spec_from_file_location('backend',Path(__file__).parents[1]/'backend/app_center_backend.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
r=json.loads(sys.stdin.readline());root=Path(os.environ['APP_CENTER_SEARCH_FIXTURE_DIR'])
base=dict(name='Example Browser',summary='Browse the web',desktop_app=True,icon='application-x-executable',installed=False)
records=[dict(base,source='flatpak',id='org.example.Browser',scope=scope,remote='flathub',branch='stable',arch='x86_64') for scope in ('system','user')]
records += [dict(base,source='deb',id='example-browser',app_id='org.example.Browser.desktop',scope='system'),
            dict(base,source='snap',id='example-browser',scope='system',channel='stable',installed=True),
            dict(base,source='appimage',id='a'*64,name='Example_Browser',scope='catalog',catalog=True),
            dict(base,source='flatpak',id='org.example.Other',scope='system',remote='flathub',branch='stable',arch='x86_64',name='Other App')]
if r['op']=='discover':result=dict(items=[],warnings=[])
elif r['op']=='list':
    items,total=b.group_search_results(records);result=dict(items=items,warnings=[],total=total)
elif r['op']=='details':
    item=dict(r['target'])
    if item['source']=='flatpak':time.sleep(.25)
    item.update(details_loaded=True,publisher=item['source']+' Publisher',description='Source-specific details',version='2.0',can_open=item['installed'],screenshots=[])
    result=dict(item=item,warnings=[])
elif r['op']=='launch':
    assert r['target']['source']=='snap' and r['target']['id']=='example-browser'
    (root/'launch.json').write_text(json.dumps(r['target']));result=dict(message='Launch requested.')
elif r['op']=='plan':
    assert r['target']['source']=='deb' and r['target']['id']=='example-browser' and r['action']=='install'
    (root/'plan.json').write_text(json.dumps(r['target']))
    result=dict(plan=dict(target=r['target'],action='install',fingerprint='a'*64,changes=[dict(info='install',id='example-browser;2;amd64;repo',summary='Example')],note='Private fixture review'))
elif r['op']=='apply':raise RuntimeError('Fixture packages must never be installed.')
else:raise RuntimeError('Unsupported private fixture operation')
print(json.dumps(dict(event='result',ok=True,**result)))
