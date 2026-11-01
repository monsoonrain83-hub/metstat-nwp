"""Probe 2: what the public EUMETView service really offers (native-res request, WMTS/GWC, limits). Observed facts only."""
import json, os, re, time, datetime as dt, concurrent.futures as cf
import requests
import xml.etree.ElementTree as ET
OUT="data/sat"; os.makedirs(OUT,exist_ok=True)
R={"utc":dt.datetime.utcnow().isoformat()+"Z"}
W="https://view.eumetsat.int/geoserver/ows"
def get(u,**k):
    t=time.time()
    try:
        r=requests.get(u,timeout=180,**k); return r,round(time.time()-t,2),None
    except Exception as e: return None,round(time.time()-t,2),str(e)[:200]
# 1 caps details: service limits + per-layer abstract/CRS/bbox for MTG
r,t,e=get(W,params={"service":"WMS","version":"1.3.0","request":"GetCapabilities"})
root=ET.fromstring(r.content); ns="{http://www.opengis.net/wms}"
svc=root.find(ns+"Service")
R["service"]={c.tag.replace(ns,""):(c.text or "").strip()[:200] for c in svc if len(list(c))==0}
R["layers"]={}
for l in root.iter(ns+"Layer"):
    n=l.find(ns+"Name")
    if n is None or not n.text.startswith("mtg_fd:"): continue
    ab=l.find(ns+"Abstract"); bb=l.find(ns+"EX_GeographicBoundingBox")
    R["layers"][n.text]={"abstract":(ab.text or "").strip()[:400] if ab is not None else "",
        "crs":[c.text for c in l.findall(ns+"CRS")][:12],
        "bbox":[x.text for x in bb] if bb is not None else None,
        "styles":[s.find(ns+"Name").text for s in l.findall(ns+"Style")][:6]}
# 2 native-resolution request: vis06 hrfi, Iran 0.5km ~ 0.0045 deg
R["native"]={}
def gm(layer,bbox,w,h,crs="EPSG:4326",fmt="image/png",tm=None):
    p={"service":"WMS","version":"1.3.0","request":"GetMap","layers":layer,"styles":"","format":fmt,"crs":crs,"bbox":bbox,"width":w,"height":h}
    if tm: p["time"]=tm
    return get(W,params=p)
for name,(bbox,w,h) in {"2048x2048":("24,44,40,64",2048,2048),"4096x3072":("24,44,40,64",4096,3072),"4444x3555_native":("24,44,40,64",4444,3555)}.items():
    r,t,e=gm("mtg_fd:vis06_hrfi",bbox,w,h)
    R["native"][name]={"status":getattr(r,"status_code",None),"sec":t,"bytes":len(r.content) if r is not None else 0,"ctype":r.headers.get("content-type") if r is not None else None,"err":e,"head":(r.text[:300] if r is not None and not r.headers.get("content-type","").startswith("image") else "")}
    if r is not None and r.headers.get("content-type","").startswith("image") and name=="2048x2048": open(OUT+"/native_vis06_2048.png","wb").write(r.content)
# 3 WMTS / GWC
R["wmts"]={}
for u in ["https://view.eumetsat.int/geoserver/gwc/service/wmts?REQUEST=GetCapabilities","https://view.eumetsat.int/geoserver/gwc/service/tms/1.0.0","https://view.eumetsat.int/geoserver/wmts?REQUEST=GetCapabilities"]:
    r,t,e=get(u); R["wmts"][u]={"status":getattr(r,"status_code",None),"sec":t,"bytes":len(r.content) if r is not None else 0,"err":e,"head":(r.text[:200] if r is not None else "")}
# 4 parallel 512px tile throughput (z7 tiles over Iran, EPSG:3857)
import math
def merc(z,x,y):
    n=2**z; s=40075016.68557849; a=-20037508.34278925
    return [a+x*s/n, a+(n-1-y)*s/n, a+(x+1)*s/n, a+(n-y)*s/n]
tiles=[(7,x,y) for x in range(81,89) for y in range(52,58)]
def one(t):
    z,x,y=t; r,s,e=get(W,params={"service":"WMS","version":"1.3.0","request":"GetMap","layers":"mtg_fd:vis06_hrfi","styles":"","format":"image/png","crs":"EPSG:3857","bbox":",".join(map(str,merc(z,x,y))),"width":512,"height":512,"transparent":"true"})
    return {"t":t,"sec":s,"ok":bool(r is not None and r.headers.get("content-type","").startswith("image")),"bytes":len(r.content) if r is not None else 0}
for conc in (4,8):
    t0=time.time()
    with cf.ThreadPoolExecutor(conc) as ex: res=list(ex.map(one,tiles[:24]))
    R[f"tiles_conc{conc}"]={"n":len(res),"ok":sum(x["ok"] for x in res),"wall_sec":round(time.time()-t0,1),"mean_sec":round(sum(x["sec"] for x in res)/len(res),2),"mean_bytes":int(sum(x["bytes"] for x in res)/len(res))}
json.dump(R,open(OUT+"/probe2_report.json","w"),ensure_ascii=False,indent=1)
print("ok")
