"""Bounded same-run append to the existing NWP endpoint; explicit apply only.
No begin/end/purge, no parallel catalogue, no redirects or credential logs.
"""
import hashlib,json,re,time
from pathlib import Path
from urllib.parse import urlsplit

ROOT='https://wtafkik.ir/online'
MAX_FRAMES=160
MAX_BYTES=128*1024*1024
MAX_JSON=32*1024*1024
MODEL={'ecmwf','gfs','icon','ukmo','gem'}

class PublishError(RuntimeError):pass

def _require(ok,message):
    if not ok:raise PublishError(message)

def identity(record):
    model,run,file=record['model'],record['run'],record['file']
    _require(model in MODEL and re.fullmatch(r'20\d{8}',run) is not None,'invalid model/run')
    match=re.fullmatch(r'world/([a-z0-9]{1,10})_(20\d{8})\.webp',file)
    _require(match is not None,'invalid frame path')
    return model,run,match[1],match[2]

def verify_plan(plan):
    _require(plan.get('manifest')=='online/data/manifest.json' and plan.get('deploy') is False,'invalid plan')
    records=plan['records'];_require(isinstance(records,list) and 0<len(records)<=MAX_FRAMES,'invalid frame count')
    total=0;seen=set();runs={};prepared=[]
    for rec in records:
        model,run,p,v=identity(rec);file=rec['file'];g=rec['meta'];key=(model,run,p,v)
        _require(key not in seen and runs.setdefault(model,run)==run,'duplicate or mixed cycles');seen.add(key)
        _require(rec['destination']==f'online/data/nwp/{model}/{run}/{file}','unexpected destination')
        q=Path(rec['source']);_require(q.is_absolute() and q.resolve()==q and q.is_file(),'unsafe source path')
        size=q.stat().st_size;total+=size
        _require(100<=size<=16*1024*1024 and total<=MAX_BYTES,'byte limit')
        b=q.read_bytes();sha=hashlib.sha256(b).hexdigest()
        _require(len(b)==size and sha==g.get('sha256') and b[:4]==b'RIFF' and b[8:12]==b'WEBP' and int.from_bytes(b[4:8],'little')==len(b)-8,'bad raster')
        _require(g.get('logical_model')==model and g.get('variable')==p and g.get('palette') and len(json.dumps(g))<=65536,'bad metadata')
        prepared.append((rec,b))
    return prepared,runs

def readback(manifest,records):
    expected={identity(r):r['meta']['sha256'] for r,_ in records}
    models=manifest.get('models',{});found={}
    for row in manifest.get('items',[]):
        if row.get('r')!='world':continue
        model=row.get('m');run=models.get(model,{}).get('run')
        key=(model,run,row.get('p'),row.get('v'))
        if key in expected:
            _require(key not in found,'duplicate world manifest entry')
            found[key]=row.get('g',{}).get('sha256')
    _require(found==expected,'manifest readback mismatch or run advanced')

def publish(plan,transport):
    prepared,runs=verify_plan(plan)
    caps=transport.call('ping')
    _require(caps.get('ok') is True and {'worldput-v1','worldsync-v1'}<=set(caps.get('caps',[])),'host world capabilities missing')
    before=transport.manifest()
    for model,run in runs.items():_require(before.get('models',{}).get(model,{}).get('run')==run,'host cycle mismatch')
    limits=caps.get('lim',{});up=limits.get('up',0);post=limits.get('post',0)
    for r,b in prepared:
        _require(not up or len(b)<=up,'host upload limit')
        _require(not post or len(b)+len(json.dumps(r['meta']).encode())+8192<=post,'host post limit')
    accepted=[]
    for r,b in prepared:
        meta=r['meta'];out=transport.call('worldput',record=r,body=b)
        _require(out.get('ok') is True and out.get('run')==r['run'] and out.get('file')==r['file'] and out.get('sha256')==meta['sha256'],'worldput acknowledgement mismatch')
        accepted.append((r,b))
    for model,run in runs.items():
        out=transport.call('worldsync',payload={'model':model,'run':run})
        _require(out.get('ok') is True and out.get('run')==run,'worldsync acknowledgement mismatch')
    readback(transport.manifest(),accepted)
    for r,b in accepted:
        _require(transport.digest(r)==r['meta']['sha256'],'public raster readback mismatch')
    return dict(verified=len(accepted),bytes=sum(len(b) for _,b in accepted),models=sorted(runs),manifest='online/data/manifest.json')

class HttpTransport:
    def __init__(self,key,root=ROOT,local_fixture=False):
        import requests
        u=urlsplit(root)
        _require(root==ROOT or (local_fixture and u.scheme=='http' and u.hostname=='127.0.0.1' and u.path=='/online' and not u.username and not u.password and not u.query and not u.fragment),'invalid host')
        _require(isinstance(key,str) and bool(key),'missing upload key')
        self.root=root;self.key=key;self.session=requests.Session();self.session.trust_env=False
    def _request(self,method,path,limit,**kwargs):
        import requests
        try:
            with self.session.request(method,self.root+path,allow_redirects=False,stream=True,timeout=(10,45),**kwargs) as response:
                _require(response.status_code==200,'host HTTP '+str(response.status_code))
                data=bytearray()
                for chunk in response.iter_content(65536):
                    _require(len(data)+len(chunk)<=limit,'response size limit')
                    data.extend(chunk)
                return bytes(data)
        except requests.RequestException as exc:raise PublishError('transport '+type(exc).__name__) from None
    def call(self,action,payload=None,record=None,body=None):
        _require(action in ('ping','worldput','worldsync'),'unsupported action')
        kw={'headers':{'X-Upload-Key':self.key}}
        if action=='worldput':
            identity(record);kw.update(data=dict(model=record['model'],run=record['run'],file=record['file'],meta=json.dumps(record['meta'])),files={'png':('frame.webp',body,'image/webp')})
        elif payload is not None:kw['json']=payload
        time.sleep(.25)
        return json.loads(self._request('POST','/nwp_upload.php?a='+action,65536,**kw))
    def manifest(self):
        return json.loads(self._request('GET','/data/manifest.json',MAX_JSON,headers={'Cache-Control':'no-cache'}))
    def digest(self,r):
        identity(r)
        return hashlib.sha256(self._request('GET','/'+r['destination'].removeprefix('online/'),16*1024*1024,headers={'Cache-Control':'no-cache'})).hexdigest()
    def close(self):self.session.close()

if __name__=='__main__':
    import argparse,os
    from plan_world_host import plan
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog',type=Path);parser.add_argument('host_manifest',type=Path);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();p=plan(args.catalog,json.loads(args.host_manifest.read_text()))
    if not args.apply:
        records,_=verify_plan(p);print(json.dumps(dict(mode='dry-run',frames=len(records),deferred=len(p['deferred']))))
    else:
        t=HttpTransport(os.environ.get('NWP_UPLOAD_KEY',''))
        try:print(json.dumps(publish(p,t)))
        finally:t.close()
