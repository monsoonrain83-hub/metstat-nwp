import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import urlopen, Request

BASE = 'https://wtafkik.ir/online/data/'


def get(name):
    with urlopen(BASE + name, timeout=90) as r:
        return json.load(r)


models = get('manifest.json')['models']
run = models['ecmwfseas']['run']
target = [int(run[:4]), int(run[4:6])]
if '--publish-input' in sys.argv:
    data = open('sfc_new/sfc_idx.json','rb').read()
    new = json.loads(data)
    if new['fc']['start'] != target or new['fc'].get('mock') or not new['fc'].get('z'):
        raise ValueError('Actual new SEAS cycle not ready')
    url = os.environ['MX_HOST'].rstrip('/')+'/nwp_upload.php?a=sfput&name=sfc_idx.json&key='+os.environ['MX_KEY']
    with urlopen(Request(url,data=data), timeout=180) as response:
        assert json.load(response)['ok']
else:
    inputs = get('sfc/sfc_idx.json')
    try:
        gallery = get('sfc/gallery_latest.json')
    except HTTPError as e:
        if e.code != 404: raise
        gallery = {}
    current = inputs.get('fc',{}).get('start') or [0,0]
    refresh = models['ecmwfseas'].get('status') == 'complete' and current < target
    build = refresh or gallery.get('issued') != inputs['issued'] or gallery.get('run') != current or os.getenv('MANUAL') == 'true'
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        print('refresh='+str(refresh).lower(), 'build='+str(build).lower(), sep='\n',file=f)
