"""Private delayed icon protocol fixture. No network or package operations."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time

request=json.loads(sys.stdin.readline())
root=Path(os.environ['APP_CENTER_ICONS_FIXTURE_DIR'])
root.mkdir(parents=True,exist_ok=True)
def key(query,n):return hashlib.sha256(f'{query}-{n}'.encode()).hexdigest()
if request['op']=='discover':result=dict(items=[],warnings=[])
elif request['op']=='list':
    query=request.get('query','')
    result=dict(items=[dict(source='snap',id=f'{query}-{n}',name=f'{query} App {n}',summary='Private icon fixture',scope='system',installed=False,icon='application-x-executable',icon_key=key(query,n)) for n in range(40)],warnings=[])
elif request['op']=='details':
    item=request['target'];item.update(details_loaded=True,description='Fixture description',can_open=False,screenshots=[]);result=dict(item=item,warnings=[])
elif request['op']=='icons':
    keys=request['keys']
    with (root/'requests.jsonl').open('a') as f:f.write(json.dumps(keys)+'\n')
    time.sleep(0.8)
    for token in keys:
        image=root/(token+'.png')
        image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aBZkAAAAASUVORK5CYII='))
        print(json.dumps(dict(event='icon',key=token,path=str(image))),flush=True)
    result={}
else:raise RuntimeError('Icon fixture does not support operations')
print(json.dumps(dict(event='result',ok=True,**result)),flush=True)
