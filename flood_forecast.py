"""Flood forecast engine v0 (rainfall -> SCS-CN runoff per sub-basin). Observed model output only; nothing synthetic.
Rain: Open-Meteo hourly precipitation from ECMWF IFS 0.25 and GFS (0.25) at the 0.25-degree cell containing each basin centroid.
Runoff: SCS-CN, AMC-II (CN2 from the static layer), Ia=0.2S. Output is NOT calibrated and NOT a flood probability."""
import json, math, time, sys, datetime as dt, os
import requests
SITE="data/static/flood_basins_site.json"; OUT="data/flood/forecast_latest.json"
MODELS={"ecmwf":"ecmwf_ifs025","gfs":"gfs_seamless"}; WIN=[1,3,6,12,24,48,72,120]; H=120; BATCH=100
B=json.load(open(SITE))["b"]
def cell(v): return round((math.floor(v/0.25)+0.5)*0.25,3)
cells={}
for i,f in enumerate(B): cells.setdefault((cell(f["y"]),cell(f["x"])),[]).append(i)
keys=sorted(cells); print("basins",len(B),"cells",len(keys),flush=True)
def fetch(model):
    R={}
    for s in range(0,len(keys),BATCH):
        part=keys[s:s+BATCH]
        for att in range(6):
            try:
                r=requests.get("https://api.open-meteo.com/v1/forecast",params={"latitude":",".join(str(k[0]) for k in part),"longitude":",".join(str(k[1]) for k in part),"hourly":"precipitation","models":model,"forecast_hours":H,"timezone":"UTC"},timeout=120)
                if r.status_code==200:
                    j=r.json(); j=j if isinstance(j,list) else [j]
                    for k,o in zip(part,j): R[k]=(o["hourly"]["time"],o["hourly"]["precipitation"])
                    break
                print("HTTP",r.status_code,r.text[:120],flush=True); time.sleep(20*(att+1))
            except Exception as e: print("err",str(e)[:100],flush=True); time.sleep(10*(att+1))
        else: print("batch failed",s,flush=True)
        time.sleep(1.5)
    return R
def scs(P,cn):
    S=25400.0/cn-254.0; Ia=0.2*S
    return 0.0 if P<=Ia else (P-Ia)**2/(P+0.8*S)
out={"generated_utc":dt.datetime.utcnow().isoformat()+"Z","windows_h":WIN,"horizon_h":H,"order":"same as basins in flood_basins_site.json (by basin_id)","ids":[f["i"] for f in B],"scale":10,
     "method":"Rain: Open-Meteo hourly precipitation (ECMWF IFS 0.25, GFS) at the 0.25-degree cell of each basin centroid; runoff: SCS-CN (AMC II, Ia=0.2S). Uncalibrated.","models":{}}
for name,mid in MODELS.items():
    R=fetch(mid); got=len(R); print(name,"cells ok",got,"/",len(keys),flush=True)
    if got<0.9*len(keys): out["models"][name]={"error":f"only {got}/{len(keys)} cells"}; continue
    times=next(iter(R.values()))[0]
    # per cell rolling max accumulation per window (mm) and start index
    cw={}
    for k,(t,p) in R.items():
        p=[0.0 if v is None else float(v) for v in p]; d={}
        for w in WIN:
            best=-1; bi=0; acc=sum(p[:w])
            best=acc
            for i in range(1,len(p)-w+1):
                acc+=p[i+w-1]-p[i-1]
                if acc>best: best=acc; bi=i
            d[w]=(best,bi)
        cw[k]=d
    M={"model_id":mid,"first_valid_utc":times[0],"last_valid_utc":times[-1],"cells":got,"P":{},"Q":{},"T":{}}
    for w in WIN:
        P=[None]*len(B); Q=[None]*len(B); T=[None]*len(B)
        for k,idx in cells.items():
            if k not in cw: continue
            p,bi=cw[k][w]
            for i in idx:
                P[i]=int(round(p*10)); Q[i]=int(round(scs(p,B[i]["cn"])*10)); T[i]=bi
        M["P"][str(w)]=P; M["Q"][str(w)]=Q; M["T"][str(w)]=T
    ck=sorted(R.keys()); cidx={k:j for j,k in enumerate(ck)}
    M["hp"]=[[int(round((0.0 if v is None else float(v))*10)) for v in R[k][1]] for k in ck]
    co=[None]*len(B)
    for k,idx in cells.items():
        if k in cidx:
            for i in idx: co[i]=cidx[k]
    M["co"]=co
    out["models"][name]=M
os.makedirs("data/flood",exist_ok=True); json.dump(out,open(OUT,"w"),separators=(",",":")); print("wrote",OUT,os.path.getsize(OUT),flush=True)
