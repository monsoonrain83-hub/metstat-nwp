"""Exercise the real PHP endpoint and its validators with a temporary catalog."""
import gzip
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    shutil.copy(Path(__file__).resolve().parents[1]/'host/model_catalog.php', root)
    (root/'data').mkdir()
    content = json.dumps({'items':[{'m':'gfs','v':str(i)} for i in range(10000)]}).encode()
    (root/'data/manifest.json').write_bytes(content)
    process = subprocess.Popen(['php','-S','127.0.0.1:8391','-t',temp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        url = 'http://127.0.0.1:8391/model_catalog.php'
        for _ in range(40):
            try:
                with urlopen(url) as r: assert r.read() == content
                break
            except OSError: time.sleep(.1)
        else: raise RuntimeError('PHP server failed to start')
        with urlopen(Request(url,headers={'Accept-Encoding':'br, gzip;q=0.8'})) as r:
            data=r.read(); tag=r.headers['ETag']
            assert r.headers['Content-Encoding']=='gzip'
            assert gzip.decompress(data)==content and len(data)<len(content)/3
        try:
            urlopen(Request(url,headers={'Accept-Encoding':'gzip','If-None-Match':tag}))
            raise AssertionError('Expected 304')
        except HTTPError as e: assert e.code == 304
        with urlopen(Request(url,headers={'Accept-Encoding':'gzip;q=0'})) as r:
            assert not r.headers.get('Content-Encoding') and r.read()==content
        with urlopen(Request(url,method='HEAD')) as r: assert r.read()==b''
        (root/'data/manifest.json').write_bytes(b'{"items":[]}')
        with urlopen(Request(url,headers={'Accept-Encoding':'gzip','If-None-Match':tag})) as r:
            assert r.status==200 and r.headers['ETag']!=tag
        (root/'data/manifest.json').unlink()
        try:
            urlopen(url); raise AssertionError('Expected 404')
        except HTTPError as e: assert e.code==404
    finally:
        process.terminate();process.wait(timeout=5)
print('PASS compression, quality negotiation, conditional GET, HEAD, changed data, missing data')
