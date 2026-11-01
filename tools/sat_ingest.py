"""Fetch the latest EUMETView frame for chosen layers, cut XYZ tiles (EPSG:3857, 512 px) over Iran/Middle East, write WebP + meta.
Observation time comes from the WMS time dimension (not from the download time). Measures size/time; no synthetic data."""
import json, os, sys, time, math, io, re, datetime as dt, concurrent.futures as cf
import requests, xml.etree.ElementTree as ET
from PIL import Image
W="https://view.eumetsat.int/geoserver/ows"; OUT=os.environ.get("SAT_OUT","sat_tiles"); CONC=8
LAYERS=os.environ.get("SAT_LAYERS","mtg_fd:vis06_hrfi,mtg_fd:ir105_hrfi,mtg_fd:rgb_dust,msg_iodc:wv062,msg_iodc:rgb_convection").split(",")
REG={"iran":(24,40,43,64,8),"mideast":(10,45,20,75,6)}  # lat0,lat1,lon0,lon1,maxzoom
def tilex(lon,z): return int((lon+180)/360*2**z)
def tiley(lat,z):
    r=math.radians(lat); return int((1-math.log(math.tan(r)+1/math.cos(r))/math.pi)/2*2**z)
def merc(z,x,y):
    n=2**z; s=40075016.68557849; a=-20037508.34278925
    return [a+x*s/n, a+(n-1-y)*s/n, a+(x+1)*s/n, a+(n-y)*s/n]
def tiles():
    S=set()
    for _,(la0,la1,lo0,lo1,mz) in REG.items():
        for z in range(3,mz+1):
            for x in range(tilex(lo0,z),tilex(lo1,z)+1):
                for y in range(tiley(la1,z),tiley(la0,z)+1): S.add((z,x,y))
    return sorted(S)
def sget(p,tries=3):
    for i in range(tries):
        try:
            r=requests.get(W,params=p,timeout=120)
            if r.ok and r.headers.get("content-type","").startswith("image"): return r
        except Exception: pass
        time.sleep(2*(i+1))
    return None
def latest_times():
    r=requests.get(W,params={"service":"WMS","version":"1.3.0","request":"GetCapabilities"},timeout=120); r.raise_for_status()
    ns="{http://www.opengis.net/wms}"; root=ET.fromstring(r.content); T={}
    for l in root.iter(ns+"Layer"):
        n=l.find(ns+"Name"); d=l.find(ns+"Dimension")
        if n is not None and n.text in LAYERS and d is not None and d.text:
            T[n.text]=d.text.strip().split(",")[-1].split("/")[1] if "/" in d.text.strip().split(",")[-1] else d.text.strip().split(",")[-1]
    return T
def main():
    os.makedirs(OUT,exist_ok=True); T=latest_times(); allt=tiles(); report={"utc":dt.datetime.utcnow().isoformat()+"Z","n_tiles_per_layer":len(allt),"layers":{}}
    for L in LAYERS:
        if L not in T: report["layers"][L]={"error":"layer or time dimension not found"}; continue
        t0=time.time(); d=f"{OUT}/{L.replace(':','_')}"; ok=0; bad=0; size=0
        def one(t):
            z,x,y=t
            r=sget({"service":"WMS","version":"1.3.0","request":"GetMap","layers":L,"styles":"","format":"image/png","crs":"EPSG:3857","bbox":",".join(map(str,merc(z,x,y))),"width":512,"height":512,"transparent":"false","time":T[L]})
            if r is None: return (t,None)
            im=Image.open(io.BytesIO(r.content)).convert("RGB"); b=io.BytesIO(); im.save(b,"WEBP",quality=90,method=4); return (t,b.getvalue())
        with cf.ThreadPoolExecutor(CONC) as ex:
            for (z,x,y),data in ex.map(one,allt):
                if data is None: bad+=1; continue
                p=f"{d}/{z}/{x}"; os.makedirs(p,exist_ok=True); open(f"{p}/{y}.webp","wb").write(data); ok+=1; size+=len(data)
        meta={"layer":L,"observation_time_utc":T[L],"fetched_utc":dt.datetime.utcnow().isoformat()+"Z","tiles_ok":ok,"tiles_failed":bad,"bytes":size,"seconds":round(time.time()-t0,1),"source":"EUMETSAT EUMETView WMS"}
        json.dump(meta,open(f"{d}/meta.json","w")); report["layers"][L]=meta
    json.dump(report,open(f"{OUT}/ingest_report.json","w"),indent=1); print(json.dumps(report)[:1500])
if __name__=="__main__": main()
