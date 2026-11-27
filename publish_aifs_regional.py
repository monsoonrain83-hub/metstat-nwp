"""Explicit first publication of verified AIFS regional frames.

Only the existing AIFS model key and regional begin/put/end contract are
used. Never call sync/purge, modify shared palettes, or upload empty runs.
No update to other model namespaces. Existing AIFS different run is refused
in this first-onboarding client; later rotation needs its own release gate.
"""
import argparse,hashlib,json,os,re
from datetime import datetime,timedelta,timezone
from pathlib import Path
from PIL import Image
from publish_world_host import HttpTransport,PublishError,_require
from aifs_regional_stage import palette_contract,PARAMS

def preflight(root):
    root=Path(root).resolve()
    rp=root/'aifs-stage.json'
    _require(rp.is_file() and rp.stat().st_size<65536,'invalid stage metadata')
    r=json.loads(rp.read_text())
    _require(r.get('model')=='aifs' and r.get('region')=='me' and r.get('mock') is False and r.get('grid')==[1440,721],'wrong stage identity')
    _require(r.get('source')=='ECMWF AIFS Single original Open Data; CC BY 4.0','wrong source')
    run=r['run'];dt=datetime.strptime(run,'%Y%m%d%H').replace(tzinfo=timezone.utc)
    _require(dt.strftime('%Y%m%d%H')==run and dt.hour in (0,6,12,18),'invalid run')
    _require(dt<=datetime.now(timezone.utc)+timedelta(minutes=5) and datetime.now(timezone.utc)-dt<timedelta(hours=72),'expired stage')
    frames=r.get('frames',[])
    _require(len(frames)==6 and {(f['param'],f['lead']) for f in frames}=={(p,h) for p in PARAMS for h in (24,48)},'incomplete batch')
    # Require actual producer refs for every native field, including terrain
    # and all temperature samples used by the existing product definition.
    import world_ecmwf_official as W
    keys={('orog',0),('pacc',24),('pacc',48)}
    _require(r.get('temperature_basis') in ('mean24','instant'),'unknown temperature basis')
    keys|={('t2m',h) for h in ((6,12,18,24,30,36,42,48) if r['temperature_basis']=='mean24' else (24,48))}
    refs=r.get('refs',{})
    _require(set(refs)=={f'{k}_{h}' for k,h in keys},'missing native source references')
    for k,h in keys:
        ref=refs[f'{k}_{h}'];idx,url=W.urls('aifs-single','0p25',dt,h,k)
        _require(ref.get('source_url')==url and ref.get('index_url')==idx and ref.get('distribution')=='producer' and ref.get('producer')=='ECMWF'
                 and ref.get('grid')==[1440,721] and ref.get('origin')==[-180,-90] and ref.get('spacing')==[.25,.25] and ref.get('lead_hours')==h,'native source mismatch')
        _require(ref.get('finite_fraction')==1.0,'native field incomplete')
    total=0;prepared=[]
    for f in frames:
        p,h=f['param'],f['lead'];v=(dt+timedelta(hours=h)).strftime('%Y%m%d%H')
        name=f'me/{p}_{v}.webp'
        _require(f['file']==name and f['valid']==v and (f['palette'],f['units'])==PARAMS[p],'wrong regional file identity')
        path=root/'aifs'/run/name
        _require(path.resolve()==path and path.is_file() and path.stat().st_size<=4*1024*1024,'unsafe raster')
        b=path.read_bytes();total+=len(b)
        _require(len(b)==f['bytes'] and hashlib.sha256(b).hexdigest()==f['sha256'],'raster digest mismatch')
        with Image.open(path) as im:
            _require(im.format=='WEBP' and im.size==(1440,960),'wrong regional raster geometry');im.load()
        prepared.append((f,b))
    _require(total==r.get('bytes') and total<=16*1024*1024,'stage size mismatch')
    return r,prepared

def publish(root,t):
    r,prepared=preflight(root);run=r['run']
    before=t.manifest()
    _require(palette_contract(before)==r['temperature_basis'],'shared parameter semantics changed')
    existing=before.get('models',{}).get('aifs')
    _require(existing is None or existing.get('run')==run,'existing AIFS different run; preserve')
    caps=t.call('ping')
    _require(caps.get('ok') is True and 'putm' in caps.get('caps',[]),'uploader capability unavailable')
    lim=caps.get('lim',{});up=lim.get('up',0);post=lim.get('post',0)
    for f,b in prepared:_require((not up or len(b)<=up) and (not post or len(b)+8192<=post),'upload size limit')
    def call(a,**kw):
        _require(a in ('begin','put','end'),'invalid action')
        return json.loads(t._request('POST','/nwp_upload.php?a='+a,65536,headers={'X-Upload-Key':t.key},**kw))
    def verify(f,b):
        actual=t._request('GET',f'/data/nwp/aifs/{run}/{f["file"]}',4*1024*1024,headers={'Cache-Control':'no-cache'})
        _require(hashlib.sha256(actual).hexdigest()==f['sha256'],'public AIFS raster digest mismatch')
    # Existing registered AIFS frame must match bytes, never overwrite it.
    present={(i['p'],i['v']) for i in before.get('items',[]) if i['m']=='aifs' and i['r']=='me'}
    for f,b in prepared:
        if (f['param'],f['valid']) in present:verify(f,b)
    out=call('begin',json={'model':'aifs','run':run,'name':'ECMWF AIFS Single','label':'ECMWF AIFS Single',
                           'info':{'tclass':'daily','res':'0.25° (~28 km)','cyc':'00/06/12/18','prov':'ECMWF Open Data; Iran DEM coverage only'}})
    _require(out.get('run')==run and isinstance(out.get('have'),list),'begin acknowledgement mismatch')
    for f,b in prepared:
        if f['file'] in out['have']:
            verify(f,b);continue
        result=call('put',data={'model':'aifs','run':run,'file':f['file'],'meta':json.dumps({'s':f['lead']})},
                    files={'png':('frame.webp',b,'image/webp')})
        _require(result.get('ok') is True,'regional upload acknowledgement mismatch');verify(f,b)
    result=call('end',json={'model':'aifs','run':run})
    _require(result.get('ok') is True,'regional end failed')
    after=t.manifest()
    _require(after.get('models',{}).get('aifs',{}).get('run')==run,'AIFS run changed')
    found={(i['p'],i['v'],i['s']) for i in after.get('items',[]) if i.get('m')=='aifs' and i.get('r')=='me'}
    _require({(f['param'],f['valid'],f['lead']) for f,b in prepared}<=found,'regional manifest readback incomplete')
    return dict(model='aifs',run=run,verified=len(prepared),bytes=r['bytes'],region='me',published=True,
                products=sorted(PARAMS),pending=r['pending'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',type=Path);p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if not a.apply:
        r,items=preflight(a.stage);print(json.dumps(dict(mode='dry-run',model=r['model'],verified=len(items),bytes=r['bytes'])))
    else:
        t=HttpTransport(os.environ.get('NWP_UPLOAD_KEY',''))
        try:print(json.dumps(publish(a.stage,t)))
        finally:t.close()
