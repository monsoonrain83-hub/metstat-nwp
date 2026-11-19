import json
import hashlib
from datetime import datetime, timezone
import os
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen, Request

BASE = 'https://wtafkik.ir/online/data/'


def read(name):
    with urlopen(Request(BASE + name, headers={'Cache-Control':'no-cache'}), timeout=90) as r:
        return r.read()

def get(name):
    return json.loads(read(name))


models = get('manifest.json')['models']
run = models['ecmwfseas']['run']
target = [int(run[:4]), int(run[4:6])]
if '--publish-input' in sys.argv:
    data = open('sfc_new/sfc_idx.json','rb').read()
    new = json.loads(data)
    if new['fc']['start'] != target or new['fc'].get('mock') or not new['fc'].get('z'):
        raise ValueError('Actual new SEAS cycle not ready')
    url = os.environ['MX_HOST'].rstrip('/')+'/nwp_upload.php?'+urlencode({'a':'sfput','name':'sfc_idx.json','key':os.environ['MX_KEY']})
    with urlopen(Request(url,data=data), timeout=180) as response:
        assert json.load(response)['ok']
else:
    index_data = read('sfc/sfc_idx.json')
    inputs = json.loads(index_data)
    source_hash = hashlib.sha256(index_data + read('sfc/era5_iran.json')).hexdigest()
    try:
        gallery = get('sfc/gallery_latest.json')
    except HTTPError as e:
        if e.code != 404: raise
        gallery = {}
    current = inputs.get('fc',{}).get('start') or [0,0]
    refresh = models['ecmwfseas'].get('status') == 'complete' and current < target
    expired = any(datetime.fromisoformat(row['validUntil'].replace('Z','+00:00')) <= datetime.now(timezone.utc) for row in gallery.get('products',{}).get('en',{}).get('prcp',[]))
    build = gallery.get('source_sha256') != source_hash or expired or gallery.get('version') != 1 or refresh or gallery.get('issued') != inputs['issued'] or gallery.get('run') != current or os.getenv('MANUAL') == 'true'
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        print('refresh='+str(refresh).lower(), 'build='+str(build).lower(), sep='\n',file=f)
