"""Private provider fixture for the headless UI test. Never launches software."""
import base64
import json
import os
from pathlib import Path
import sys

request=json.loads(sys.stdin.readline())
base=dict(source='flatpak',id='org.example.App',app_id='org.example.App',name='Example',summary='A fixture application',remote='flathub',arch='x86_64',icon='application-x-executable')
if request['op']=='list':
    result=dict(items=[dict(base,scope='system',branch='stable',installed=True),dict(base,scope='user',branch='beta',installed=False)],warnings=[])
elif request['op']=='details':
    item=dict(request['target'])
    image=Path(os.environ['STORE_DETAILS_FIXTURE_DIR'])/'fixture.png'
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aBZkAAAAASUVORK5CYII='))
    item.update(details_loaded=True,description='A full description.\n\nAnother paragraph.',publisher='Example Team',version='2.0',installed_version='1.0' if item['installed'] else '',can_open=item['installed'],screenshots=[dict(path=str(image),caption='First screenshot'),dict(path=str(image),caption='Second screenshot')])
    result=dict(item=item,warnings=[])
elif request['op']=='launch':
    assert request['target']['scope']=='system' and request['target']['branch']=='stable'
    (Path(os.environ['STORE_DETAILS_FIXTURE_DIR'])/'launch.json').write_text(json.dumps(request['target']))
    result=dict(message='Launch requested.')
else:
    raise RuntimeError('The UI fixture does not perform software operations.')
print(json.dumps(dict(event='result',ok=True,**result)))
