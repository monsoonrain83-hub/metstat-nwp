"""Feasibility probe for the EUMETSAT satellite mission. Writes data/sat/probe_report.json (+ sample PNGs).
Nothing is assumed: every endpoint result is recorded as observed (status, size, time) or as an error."""
import json, os, re, time, sys, datetime as dt
import requests
OUT="data/sat"; os.makedirs(OUT,exist_ok=True)
R={"utc":dt.datetime.utcnow().isoformat()+"Z","wms":{},"eumdac":{}}
WMS="https://view.eumetsat.int/geoserver/ows"
def get(u,**k):
    t=time.time()
    try:
        r=requests.get(u,timeout=90,**k); return r,round(time.time()-t,2),None
    except Exception as e: return None,round(time.time()-t,2),str(e)
r,t,e=get(WMS,params={"service":"WMS","version":"1.3.0","request":"GetCapabilities"})
R["wms"]["caps"]={"status":getattr(r,"status_code",None),"bytes":len(r.content) if r is not None else 0,"sec":t,"err":e}
layers={}
if r is not None and r.ok:
    import xml.etree.ElementTree as ET
    ns={"w":"http://www.opengis.net/wms"}
    root=ET.fromstring(r.content)
    for l in root.iter("{http://www.opengis.net/wms}Layer"):
        n=l.find("w:Name",ns)
        if n is None: continue
        nm=n.text.strip(); ti=l.find("w:Title",ns); d=l.find("w:Dimension",ns)
        layers[nm]={"title":ti.text if ti is not None else "","time":(d.text.strip()[-120:] if d is not None and d.text else "")}
R["wms"]["n_layers"]=len(layers)
mtg={k:v for k,v in layers.items() if k.lower().startswith(("mtg","li_","fci"))}
R["wms"]["mtg_layers"]=mtg
R["wms"]["msg_layers_count"]=len([k for k in layers if k.lower().startswith(("msg","mumi","iodc"))])
# Iran bbox sample GetMap (EPSG:4326, WMS 1.3.0 axis order lat,lon)
want=[k for k in mtg if re.search(r"(vis06|ir105|rgb_truecolour|rgb_dust|rgb_airmass|natural|hrfi|ir38|wv62)",k,re.I)][:14]
R["wms"]["samples"]={}
for k in want:
    r,t,e=get(WMS,params={"service":"WMS","version":"1.3.0","request":"GetMap","layers":k,"styles":"","format":"image/png","crs":"EPSG:4326","bbox":"24,44,40,64","width":1280,"height":1024})
    ok=r is not None and r.ok and r.headers.get("content-type","").startswith("image")
    R["wms"]["samples"][k]={"ok":ok,"status":getattr(r,"status_code",None),"sec":t,"bytes":len(r.content) if r is not None else 0,"ctype":r.headers.get("content-type") if r is not None else None,"err":e}
    if ok and len(R["wms"]["samples"])<=6: open(f"{OUT}/sample_{k.replace(':','_')}.png","wb").write(r.content)
# EUMDAC (needs secrets)
ck,cs=os.environ.get("EUMETSAT_KEY"),os.environ.get("EUMETSAT_SECRET")
R["eumdac"]["secrets_present"]=bool(ck and cs)
if ck and cs:
    try:
        import eumdac
        tok=eumdac.AccessToken((ck,cs)); R["eumdac"]["token_expires"]=str(tok.expiration)
        ds=eumdac.DataStore(tok)
        cols=[]
        for c in ds.collections:
            if re.search(r"MTG|FCI|MSG|SEVIRI|LI",str(c),re.I): cols.append({"id":str(c),"title":getattr(c,"title","")})
        R["eumdac"]["collections"]=cols[:60]
        for cid in ("EO:EUM:DAT:0662","EO:EUM:DAT:0665"):
            try:
                c=ds.get_collection(cid); now=dt.datetime.utcnow()
                pr=list(c.search(dtstart=now-dt.timedelta(hours=1),dtend=now))[:3]
                R["eumdac"][cid]={"title":c.title,"recent":[str(p) for p in pr],"sizes":[getattr(p,"size",None) for p in pr]}
            except Exception as ex: R["eumdac"][cid]={"err":str(ex)[:300]}
    except Exception as ex: R["eumdac"]["err"]=str(ex)[:400]
json.dump(R,open(f"{OUT}/probe_report.json","w"),ensure_ascii=False,indent=1)
print(json.dumps({"caps":R["wms"]["caps"],"n_mtg":len(mtg),"samples_ok":sum(v["ok"] for v in R["wms"]["samples"].values())}))
