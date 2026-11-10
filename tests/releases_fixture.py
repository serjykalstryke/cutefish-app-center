"""Private catalog release fixture. No package or source mutation is allowed."""
import importlib.util
import json
import os
from pathlib import Path
import sys
r=json.loads(sys.stdin.readline());root=Path(os.environ['APP_CENTER_RELEASES_FIXTURE_DIR'])
spec=importlib.util.spec_from_file_location('backend',Path(__file__).parents[1]/'backend/app_center_backend.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
releases=b.catalog_releases()
if r['op']=='discover':result=dict(items=[],warnings=[])
elif r['op']=='sources':result=dict(providers=[dict(id=id,name=name,installed=True,available=True) for id,name in [('deb','Native (Debian)'),('flatpak','Flatpak'),('snap','Snap')]],repositories=[dict(source='flatpak',id='flathub'+suffix,display_name='Flathub'+suffix,display_url=url,scope='system',enabled=True,verified=True,installed_count=1,catalog_family='flathub',catalog_release=release) for suffix,url,release in [('', 'https://dl.flathub.org/repo/','stable'),('-beta','https://dl.flathub.org/beta-repo/','beta')]],debian_release=dict(available=True,current='system',managed=False))
elif r['op']=='list':
 (root/'list.json').write_text(json.dumps(releases))
 records=[dict(source=source,id='org.example.App' if source=='flatpak' else 'example',name='Example',summary='An example application',scope='system',installed=False,icon='application-x-executable',app_id='org.example.App',remote='flathub'+('-beta' if releases.get(source)=='beta' else ''),branch=releases.get(source,'stable'),channel='latest/'+releases.get(source,'stable'),requested_channel='latest/'+releases.get(source,'stable')) for source in ('flatpak','snap')]
 items,total=b.group_search_results(records);result=dict(items=items,total=total,warnings=[])
elif r['op']=='details':
 item=dict(r['target']);item.update(details_loaded=True,publisher='Fixture Publisher',description='Selected '+item.get('branch','stable')+' release',screenshots=[])
 result=dict(item=item,warnings=[])
elif r['op']=='plan_debian_release':
 (root/'debian-plan.json').write_text(json.dumps(r));result=dict(plan=dict(release=r['release'],title='Use Debian Testing',note='This changes operating-system sources. No packages are installed by this review.',changes=[dict(path='/etc/apt/sources.list.d/debian.sources')],configuration='Suites: testing',fingerprint='a'*64))
elif r['op']=='apply_debian_release':raise RuntimeError('The native fixture must never change Debian sources.')
else:raise RuntimeError('Unsupported private fixture operation')
print(json.dumps(dict(event='result',ok=True,**result)))
