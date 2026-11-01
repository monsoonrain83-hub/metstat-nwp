"""Build ~A km2 Iranian sub-basins by topologically aggregating MERIT-Basins v0.7/v1.0_bugfix1 unit catchments.
Data: Lin et al. 2019 (WRR, doi:10.1029/2019WR025287), CC BY-NC-SA 4.0 (non-commercial, attribution, share-alike).
Run in CI (Google Drive is reachable from GitHub Actions, not from the dev shell)."""
import argparse, json, os, struct, sys, time
import numpy as np

FOLDER = "1J8vyqCnSdquY1cRI1PPsXzMBLBXKzzoW"
IRAN_BBOX = (43.9, 24.8, 63.6, 40.0)
SUF = "_MERIT_Hydro_v07_Basins_v01_bugfix1"

def log(*a):
    print("[%5.0fs]" % (time.time() - T0), *a, flush=True)

def shp_bbox(p):
    with open(p, "rb") as f:
        h = f.read(100)
    return struct.unpack("<4d", h[36:68])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/merit/merit_iran_basins.geojson")
    ap.add_argument("--a-target", type=float, default=250.0)
    ap.add_argument("--work", default="/tmp/merit")
    ap.add_argument("--outline", default="data/static/iran_outline.json")
    ap.add_argument("--codes", default="")
    a = ap.parse_args()
    import gdown, geopandas as gpd
    from shapely.geometry import Point, Polygon
    from shapely.prepared import prep
    from shapely.ops import unary_union
    os.makedirs(a.work, exist_ok=True)
    fs = gdown.download_folder(id=FOLDER, skip_download=True, quiet=True, use_cookies=False)
    ids = {f.path: f.id for f in fs}
    codes = sorted({os.path.basename(p).split("_")[2] for p in ids if p.startswith("pfaf_level_02/cat_pfaf_") and p.endswith(".shp")})
    log("level-2 codes:", codes)
    if a.codes:
        codes = a.codes.split(",")
    used = []
    for c in codes:
        base = "pfaf_level_02/%%s_pfaf_%s%s.%%s" % (c, SUF)
        sp = os.path.join(a.work, "cat_%s.shp" % c)
        try:
            gdown.download(id=ids[base % ("cat", "shp")], output=sp, quiet=True)
            bb = shp_bbox(sp)
        except Exception as e:
            log("skip", c, repr(e)[:120]); continue
        hit = not (bb[2] < IRAN_BBOX[0] or bb[0] > IRAN_BBOX[2] or bb[3] < IRAN_BBOX[1] or bb[1] > IRAN_BBOX[3])
        log("tile", c, "bbox", [round(x, 1) for x in bb], "hit" if hit else "no", "%.0f MB" % (os.path.getsize(sp) / 1e6))
        if not hit:
            os.remove(sp); continue
        for e in ("shx", "dbf", "prj"):
            for k in ("cat", "riv"):
                try:
                    gdown.download(id=ids[base % (k, e)], output=os.path.join(a.work, "%s_%s.%s" % (k, c, e)), quiet=True)
                except Exception as ex:
                    log("missing", k, e, repr(ex)[:80])
        try:
            gdown.download(id=ids[base % ("riv", "shp")], output=os.path.join(a.work, "riv_%s.shp" % c), quiet=True)
        except Exception as ex:
            log("riv shp fail", c, repr(ex)[:100]); continue
        used.append(c)
    log("tiles used:", used)
    rings = json.load(open(a.outline))["rings"]
    iran = prep(unary_union([Polygon(r).buffer(0) for r in rings]))
    cats, rivs = [], []
    for c in used:
        g = gpd.read_file(os.path.join(a.work, "cat_%s.shp" % c), bbox=IRAN_BBOX)
        r = gpd.read_file(os.path.join(a.work, "riv_%s.shp" % c), ignore_geometry=True)
        cats.append(g); rivs.append(r)
        log("tile", c, "catchments in bbox", len(g), "reaches", len(r))
    g = gpd.pd.concat(cats, ignore_index=True)
    r = gpd.pd.concat(rivs, ignore_index=True)[["COMID", "NextDownID", "uparea", "lengthkm", "slope"]]
    g = g.merge(r, on="COMID", how="left")
    rp = g.geometry.representative_point()
    inside = np.array([iran.contains(p) for p in rp])
    g = g[inside].reset_index(drop=True)
    log("catchments inside Iran:", len(g), "area km2 %.0f" % g["unitarea"].sum())
    comid = g["COMID"].astype(np.int64).values
    pos = {c: i for i, c in enumerate(comid)}
    nd = np.array([pos.get(int(x), -1) if x and x == x else -1 for x in g["NextDownID"].fillna(0).values], dtype=np.int64)
    area = g["unitarea"].astype(float).values
    n = len(g)
    indeg = np.zeros(n, np.int32)
    for i in range(n):
        if nd[i] >= 0:
            indeg[nd[i]] += 1
    acc = area.copy()
    outlet = np.zeros(n, bool)
    stack = [i for i in range(n) if indeg[i] == 0]
    seen = 0
    while stack:
        i = stack.pop(); seen += 1
        d = nd[i]
        if d < 0 or acc[i] >= a.a_target:
            outlet[i] = True
        else:
            acc[d] += acc[i]
        if d >= 0:
            indeg[d] -= 1
            if indeg[d] == 0:
                stack.append(d)
    if seen < n:   # cycles (should not happen): make leftovers outlets
        log("WARNING unreached nodes", n - seen); outlet[indeg > 0] = True
    # label = first outlet downstream (inclusive)
    lab = np.full(n, -1, np.int64)
    def find(i):
        path = []
        while lab[i] < 0 and not outlet[i]:
            path.append(i); i = nd[i]
        r = lab[i] if lab[i] >= 0 else i
        lab[i] = r
        for p in path:
            lab[p] = r
        return r
    for i in range(n):
        find(i)
    outs = np.flatnonzero(outlet)
    gid_of = {int(o): k + 1 for k, o in enumerate(outs)}
    g["gid"] = [gid_of[int(lab[i])] for i in range(n)]
    ds_gid = {}
    for o in outs:
        d = nd[o]
        ds_gid[gid_of[int(o)]] = 0 if d < 0 else gid_of[int(lab[d])]
    dis = g[["gid", "geometry", "unitarea"]].dissolve(by="gid", aggfunc={"unitarea": "sum"}).reset_index()
    dis["down_gid"] = dis["gid"].map(ds_gid)
    log("basins:", len(dis), "median area %.0f" % dis["unitarea"].median(), "p5 %.0f p95 %.0f" % tuple(np.percentile(dis["unitarea"], [5, 95])))
    try:
        import shapely
        dis["geometry"] = shapely.coverage_simplify(dis.geometry.values, 0.0015)
        log("coverage_simplify ok")
    except Exception as e:
        log("coverage_simplify unavailable:", repr(e)[:80]); dis["geometry"] = dis.geometry.simplify(0.0008, preserve_topology=True)
    dis = dis.rename(columns={"unitarea": "area_km2"})
    dis["area_km2"] = dis["area_km2"].round(1)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    dis.to_file(a.out, driver="GeoJSON", COORDINATE_PRECISION=4)
    log("wrote", a.out, "%.1f MB" % (os.path.getsize(a.out) / 1e6))

T0 = time.time()
if __name__ == "__main__":
    main()
