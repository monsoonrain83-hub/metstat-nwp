"""Probe 3: all EUMETView layers (MSG/IODC etc.) + keyless alternatives for the Middle East (NASA GIBS). Observed facts only."""
import json, os, time, datetime as dt
import requests, xml.etree.ElementTree as ET
OUT="data/sat"; R={"utc":dt.datetime.utcnow().isoformat()+"Z"}
def get(u,**k):
    t=time.time()
    try: r=requests.get(u,timeout=120,**k); return r,round(time.time()-t,2),None
    except Exception as e: return None,round(time.time()-t,2),str(e)[:200]
r,t,e=get("https://view.eumetsat.int/geoserver/ows",params={"service":"WMS","version":"1.3.0","request":"GetCapabilities"})
ns="{http://www.opengis.net/wms}"; root=ET.fromstring(r.content); L={}
for l in root.iter(ns+"Layer"):
    n=l.find(ns+"Name")
    if n is None: continue
    ti=l.find(ns+"Title"); ab=l.find(ns+"Abstract"); d=l.find(ns+"Dimension"); bb=l.find(ns+"EX_GeographicBoundingBox")
    L[n.text]={"title":ti.text if ti is not None else "","abs":(ab.text or "").strip()[:260] if ab is not None else "","time":(d.text.strip()[-45:] if d is not None and d.text else ""),"bbox":[x.text[:7] for x in bb] if bb is not None else None}
R["eumetview_layers"]=L
# NASA GIBS WMTS capabilities (keyless)
r,t,e=get("https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml")
R["gibs_caps"]={"status":getattr(r,"status_code",None),"sec":t,"bytes":len(r.content) if r is not None else 0,"err":e}
G={}
if r is not None and r.ok:
    root=ET.fromstring(r.content); w="{http://www.opengis.net/wmts/1.0}"; o="{http://www.opengis.net/ows/1.1}"
    for lay in root.iter("{http://www.opengis.net/wmts/1.0}Layer"):
        i=lay.find(o+"Identifier").text
        if any(k in i for k in ("TrueColor","CorrectedReflectance","Cloud","Dust","Aerosol","SurfaceReflectance","Brightness_Temperature","IR","Night","Himawari","GOES","Meteosat")):
            tms=[x.find(w+"TileMatrixSet").text for x in lay.findall(w+"TileMatrixSetLink")]
            G[i]={"title":(lay.find(o+"Title").text or "")[:80],"tms":tms}
R["gibs_layers"]=G
dt_=(dt.datetime.utcnow()-dt.timedelta(days=1)).strftime("%Y-%m-%d")
R["gibs_tile_test"]={}
for lay,tm,ext in [("VIIRS_NOAA20_CorrectedReflectance_TrueColor","GoogleMapsCompatible_Level9","jpg"),("MODIS_Terra_CorrectedReflectance_TrueColor","GoogleMapsCompatible_Level9","jpg"),("VIIRS_SNPP_CorrectedReflectance_TrueColor","GoogleMapsCompatible_Level9","jpg")]:
    z=8; x,y=161,102   # tile over Iran at z8 (lon ~52E, lat ~32N)
    u=f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{lay}/default/{dt_}/{tm}/{z}/{y}/{x}.{ext}"
    r,t,e=get(u); ok=r is not None and r.headers.get("content-type","").startswith("image")
    R["gibs_tile_test"][lay]={"url":u,"ok":ok,"status":getattr(r,"status_code",None),"sec":t,"bytes":len(r.content) if r is not None else 0,"err":e}
    if ok: open(f"{OUT}/gibs_{lay}.jpg","wb").write(r.content)
json.dump(R,open(OUT+"/probe3_report.json","w"),ensure_ascii=False,indent=1); print("ok")
