#!/usr/bin/env python3
"""MetStat flash-flood module — STATIC stage (runs in GitHub Actions, never on the web host).

DEM (Copernicus GLO-90 from AWS Open Data, GLO-30 via Earth Engine as fallback)
  -> PyFlwDir (MIT) flow directions
  -> own area-based sub-basin delineation (nested, outlet on stream)
  -> per-sub-basin terrain / drainage features
  -> land cover (MODIS MCD12Q1 500 m always; KNTU 10 m fractions + SoilGrids sand/clay via Earth Engine)
  -> SCS-CN (NEH-630) per basin
  -> SUSCEPTIBILITY index (relative, 0-100) with weight-sensitivity analysis.

Outputs (in --out):  flood_basins_iran.geojson, flood_static_meta.json, flood_static_log.txt
The susceptibility is a RELATIVE ranking of basins (not a probability, not a forecast).
"""
import argparse
import json
import math
import os
import sys
import time
import traceback

import numpy as np

import flood_core as fc

W, N, E, S = 43.4, 40.1, 63.9, 24.5          # same bbox as the MODIS landcover file
LOG = []


def log(*a):
    msg = "[%6.0fs] %s" % (time.time() - T0, " ".join(str(x) for x in a))
    print(msg, flush=True)
    LOG.append(msg)


T0 = time.time()

# --------------------------------------------------------------------------------------
# DEM
# --------------------------------------------------------------------------------------
def tile_name(lat, lon):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return "Copernicus_DSM_COG_30_%s%02d_00_%s%03d_00_DEM" % (ns, abs(lat), ew, abs(lon))


def dem_from_aws(res, nrows, ncols, s_eff, workers=8):
    import rasterio
    from rasterio.enums import Resampling
    from concurrent.futures import ThreadPoolExecutor
    dem = np.full((nrows, ncols), -9999.0, np.float32)
    px = int(round(1.0 / res))
    jobs = [(la, lo) for la in range(int(math.floor(s_eff)), int(math.ceil(N))) for lo in range(int(math.floor(W)), int(math.ceil(E)))]
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2")

    def one(job):
        la, lo = job
        nm = tile_name(la, lo)
        url = "/vsicurl/https://copernicus-dem-90m.s3.amazonaws.com/%s/%s.tif" % (nm, nm)
        try:
            with rasterio.Env(**env):
                with rasterio.open(url) as src:
                    a = src.read(1, out_shape=(px, px), resampling=Resampling.average).astype(np.float32)
                    nd = src.nodata
            if nd is not None:
                a[a == nd] = -9999.0
            return job, a, None
        except Exception as ex:  # noqa: BLE001
            return job, None, str(ex)[:120]
    ok = miss = 0
    errs = {}
    with ThreadPoolExecutor(workers) as ex:
        for (la, lo), a, er in ex.map(one, jobs):
            if a is None:
                miss += 1
                errs[er] = errs.get(er, 0) + 1
                continue
            ok += 1
            r0 = int(round((N - (la + 1)) / res))
            c0 = int(round((lo - W) / res))
            rs, cs = max(r0, 0), max(c0, 0)
            re_, ce = min(r0 + px, nrows), min(c0 + px, ncols)
            if re_ <= rs or ce <= cs:
                continue
            dem[rs:re_, cs:ce] = a[rs - r0:re_ - r0, cs - c0:ce - c0]
    log("AWS GLO-90 tiles ok=%d missing=%d of %d" % (ok, miss, len(jobs)))
    for k, v in list(errs.items())[:3]:
        log("  aws error x%d: %s" % (v, k))
    return dem, ok, len(jobs)


def dem_from_gee(res, nrows, ncols, s_eff):
    import gee_grid
    ee = gee_grid.ee_init()
    img = gee_grid.dem_image(ee)
    dem = np.full((nrows, ncols), -9999.0, np.float32)
    step = 4.0
    k = 0
    for la in np.arange(s_eff, N, step):
        for lo in np.arange(W, E, step):
            w, s = float(lo), float(la)
            e, n = min(w + step, E), min(s + step, N)
            # snap to grid
            n_r = int(round((N - n) / res))
            w_c = int(round((w - W) / res))
            bbox = (W + w_c * res, N - int(round((N - s) / res)) * res, W + int(round((e - W) / res)) * res, N - n_r * res)
            a = gee_grid.fetch_tile(ee, img, bbox, res)[0]
            r0 = n_r
            c0 = w_c
            h, ww = a.shape
            sub = dem[r0:r0 + h, c0:c0 + ww]
            a = a[:sub.shape[0], :sub.shape[1]]
            m = np.isfinite(a) & (a != 0)
            sub[m] = a[m]
            k += 1
    log("GEE GLO-30 DEM tiles fetched:", k)
    return dem


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
D8_DR = {1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1}
D8_DC = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}


def d8_to_ds(d8, valid):
    """PyFlwDir 'd8' codes (1,2,4,..,128 = E,SE,S,SW,W,NW,N,NE; 0 = pit) -> flat downstream index array."""
    R, C = d8.shape
    idx = np.arange(R * C, dtype=np.int64).reshape(R, C)
    dr = np.zeros((R, C), np.int8)
    dc = np.zeros((R, C), np.int8)
    for code in D8_DR:
        m = d8 == code
        dr[m] = D8_DR[code]
        dc[m] = D8_DC[code]
    rr = np.arange(R)[:, None] + dr
    cc = np.arange(C)[None, :] + dc
    inb = (rr >= 0) & (rr < R) & (cc >= 0) & (cc < C)
    ds = np.where(inb, rr * C + cc, idx)
    ds = np.where(valid, ds, -1)
    ds = ds.ravel()
    bad = (ds >= 0) & (~valid.ravel()[np.clip(ds, 0, R * C - 1)])
    ds[bad] = np.flatnonzero(bad)          # points into a masked cell -> treat as pit
    return ds


def inside_mask(outline_path, nrows, ncols, res):
    import rasterio.features
    from rasterio.transform import from_origin
    from shapely.geometry import Polygon
    rings = json.load(open(outline_path))["rings"]
    polys = []
    for r in rings:
        p = Polygon(r)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            polys.append((p, 1))
    return rasterio.features.rasterize(polys, out_shape=(nrows, ncols), transform=from_origin(W, N, res, res), fill=0, dtype="uint8").astype(bool)


def group_reduce(lab_sorted_starts, vals_sorted, op):
    return (np.maximum if op == "max" else np.minimum).reduceat(vals_sorted, lab_sorted_starts)


LC_EN = {1: "Evergreen needleleaf forest", 2: "Evergreen broadleaf forest", 3: "Deciduous needleleaf forest", 4: "Deciduous broadleaf forest",
         5: "Mixed forest", 6: "Closed shrubland", 7: "Open shrubland", 8: "Woody savanna", 9: "Savanna", 10: "Grassland", 11: "Permanent wetland",
         12: "Cropland", 13: "Urban", 14: "Cropland/natural mosaic", 15: "Snow/ice", 16: "Barren", 17: "Water"}
KNTU_EN = {1: "Urban", 2: "Water", 3: "Wetland", 4: "Kalut (yardang)", 5: "Marshland", 6: "Salty land", 7: "Clay", 8: "Forest", 9: "Outcrop",
           10: "Uncovered plain", 11: "Sand", 12: "Farm land", 13: "Range land"}
KNTU_FA = {1: "شهری", 2: "آب", 3: "تالاب", 4: "کلوت", 5: "مرداب", 6: "شوره‌زار", 7: "رس (کویر)", 8: "جنگل", 9: "برونزد سنگی",
           10: "دشت بدون پوشش", 11: "ماسه", 12: "کشاورزی", 13: "مرتع"}
LC_FA = {1: "جنگل سوزنی‌برگ", 2: "جنگل پهن‌برگ همیشه‌سبز", 3: "جنگل سوزنی‌برگ خزان‌کننده", 4: "جنگل پهن‌برگ خزان‌کننده", 5: "جنگل مختلط",
         6: "بوتهٔ بسته", 7: "بوتهٔ باز", 8: "ساوان جنگلی", 9: "ساوان", 10: "علفزار/مرتع", 11: "تالاب", 12: "کشاورزی", 13: "شهری",
         14: "موزاییک کشاورزی-طبیعی", 15: "برف/یخ", 16: "بدون پوشش", 17: "آب"}
SOIL_FA = ["شن", "شن لومی", "لوم شنی", "لوم", "لوم سیلتی", "سیلت", "لوم رسی شنی", "لوم رسی", "لوم رسی سیلتی", "رس شنی", "رس سیلتی", "رس"]


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/static")
    ap.add_argument("--a-target", type=float, default=250.0, help="target sub-basin area km2")
    ap.add_argument("--stream-km2", type=float, default=5.0)
    ap.add_argument("--res", type=float, default=0.0025)
    ap.add_argument("--max-depth", type=float, default=50.0)
    ap.add_argument("--gee", type=int, default=1)
    ap.add_argument("--modis", default="data/static/landcover_modis_iran_2025.npz")
    ap.add_argument("--outline", default="data/static/iran_outline.json")
    ap.add_argument("--dem-source", default="auto", choices=["auto", "aws", "gee"])
    ap.add_argument("--merit", default="", help="aggregated MERIT-Basins geojson (gid, down_gid): replaces D8 labelling")
    ap.add_argument("--limit-rows", type=int, default=0, help="debug: only first N rows of the grid")
    a = ap.parse_args()
    res = a.res
    nrows = int(round((N - S) / res))
    ncols = int(round((E - W) / res))
    if a.limit_rows:
        nrows = min(nrows, a.limit_rows)
    S_eff = N - nrows * res
    os.makedirs(a.out, exist_ok=True)
    meta = {"stage": "flood_static", "grid": {"west": W, "north": N, "res_deg": res, "nrows": nrows, "ncols": ncols},
            "params": vars(a), "notes": []}

    # ---------------- DEM
    dem = None
    if a.dem_source in ("auto", "aws"):
        try:
            dem, ok, tot = dem_from_aws(res, nrows, ncols, S_eff)
            if ok < 0.25 * tot:                      # clearly not working (land tiles are only ~55 % of the box)
                log("AWS DEM mostly missing -> fallback")
                dem = None
            else:
                meta["dem_source"] = "Copernicus GLO-90 (AWS Open Data, tiles %d/%d)" % (ok, tot)
        except Exception as ex:  # noqa: BLE001
            log("AWS DEM failed:", repr(ex)[:200])
    if dem is None and a.gee and a.dem_source in ("auto", "gee"):
        dem = dem_from_gee(res, nrows, ncols, S_eff)
        meta["dem_source"] = "Copernicus GLO-30 via Earth Engine, mean-aggregated"
    if dem is None:
        raise SystemExit("no DEM source worked")
    valid2 = dem > -9000
    log("DEM valid cells: %.1f M of %.1f M; elev min/max %.0f / %.0f" % (valid2.sum() / 1e6, dem.size / 1e6, dem[valid2].min(), dem[valid2].max()))
    n = dem.size

    # ---------------- flow directions (PyFlwDir, MIT)
    import pyflwdir
    from rasterio.transform import from_origin
    tr = from_origin(W, N, res, res)
    try:
        flw = pyflwdir.from_dem(data=dem, nodata=-9999.0, transform=tr, latlon=True, outlets="edge", max_depth=a.max_depth)
    except TypeError:
        flw = pyflwdir.from_dem(data=dem, nodata=-9999.0, transform=tr, latlon=True, outlets="edge")
        meta["notes"].append("pyflwdir.from_dem without max_depth (old version)")
    try:
        d8 = np.asarray(flw.to_array("d8"))
    except Exception:  # noqa: BLE001
        d8 = np.asarray(flw.to_array(ftype="d8"))
    meta["pyflwdir_version"] = getattr(pyflwdir, "__version__", "?")
    del flw
    ds = d8_to_ds(d8, valid2)
    del d8
    log("flow directions ready; pits:", int((ds == np.arange(n)).sum()))

    lat, dx_row, dy_row, area_row = fc.cell_geometry(nrows, ncols, N, res)
    cell_area = np.repeat(area_row, ncols).astype(np.float32)
    cell_area[~valid2.ravel()] = 0
    order = fc.topo_order(ds)
    log("topological order cells:", order.size, "of valid", int(valid2.sum()))
    acc = fc.accumulate(order, ds, cell_area)
    stream = (acc >= a.stream_km2) & valid2.ravel()
    isout = fc.mark_outlets(order, ds, cell_area, stream, a.a_target)
    lab, nb = fc.label_basins(order, ds, isout)
    log("sub-basins before sliver merge:", nb)
    # ---- merge sliver basins (thin D8 artefacts on flat ground) into the DOWNSTREAM basin by un-marking their outlet
    from scipy import ndimage as _ndi
    for _pass in range(0 if a.merit else 5):
        L2 = lab.reshape(nrows, ncols)
        sl_ = _ndi.find_objects(L2)
        cnt_ = np.bincount(lab, minlength=nb + 1)
        outl = np.full(nb + 1, -1, np.int64)
        oi = np.flatnonzero(isout)
        outl[lab[oi]] = oi
        n_un = 0
        for k, s_ in enumerate(sl_, start=1):
            if s_ is None or outl[k] < 0:
                continue
            h = s_[0].stop - s_[0].start
            w = s_[1].stop - s_[1].start
            A = float(cnt_[k])
            elong = max(h, w) / max(np.sqrt(A), 1.0)
            fill = A / max(h * w, 1)
            sliver = (elong > 6.0 and fill < 0.35) or (cnt_[k] * (res * 111.0) ** 2 < 15.0)
            o = outl[k]
            if sliver and ds[o] != o:
                isout[o] = False
                n_un += 1
        log("sliver merge pass", _pass, "merged", n_un)
        if n_un == 0:
            break
        lab, nb = fc.label_basins(order, ds, isout)
    if a.merit:
        import rasterio.features as _rf
        from shapely.geometry import shape as _sh
        _fc = json.load(open(a.merit))
        _shapes = [(_sh(_f["geometry"]), int(_f["properties"]["gid"])) for _f in _fc["features"] if _f["geometry"]]
        merit_geom = {int(_f["properties"]["gid"]): _sh(_f["geometry"]) for _f in _fc["features"] if _f["geometry"]}
        lab = _rf.rasterize(_shapes, out_shape=(nrows, ncols), transform=tr, fill=0, dtype="int32").ravel().astype(np.int32)
        nb = int(max(merit_geom))
        isout[:] = False
        _idx = np.flatnonzero(lab > 0)
        _o = np.lexsort((acc[_idx], lab[_idx]))
        _ls = lab[_idx][_o]
        isout[_idx[_o][np.r_[_ls[1:] != _ls[:-1], True]]] = True      # outlet = max-accumulation cell of each MERIT basin
        log("MERIT labelling: basins", len(merit_geom), "cells labelled", int(_idx.size))
    log("sub-basins before Iran filter:", nb)

    # ---------------- Iran filter
    inside = inside_mask(a.outline, nrows, ncols, res).ravel()
    inside_cnt = np.bincount(lab, weights=inside.astype(np.float32), minlength=nb + 1)
    tot_cnt = np.bincount(lab, minlength=nb + 1).astype(np.float64)
    keep = (tot_cnt > 0) & (inside_cnt >= 0.5 * np.maximum(tot_cnt, 1))
    keep[0] = False
    new_id = np.zeros(nb + 1, np.int32)
    kidx = np.flatnonzero(keep)
    new_id[kidx] = np.arange(1, kidx.size + 1)
    m = int(kidx.size)
    lab = new_id[lab]
    log("sub-basins kept (>=50%% inside Iran): %d" % m)
    outs = np.flatnonzero(isout & (lab > 0))
    out_lab = lab[outs]
    ds_of = ds[outs]
    ds_new = np.where(ds_of == outs, 0, lab[ds_of])        # 0 = leaves Iran / terminal sink
    ds_new = np.where(ds_new == out_lab, 0, ds_new)
    ds_id = np.zeros(m + 1, np.int32)
    ds_id[out_lab] = ds_new

    # ---------------- per-basin terrain features
    zf = dem.ravel()
    zf = np.where(valid2.ravel(), zf, 0).astype(np.float32)
    sl = fc.slope_deg(np.where(valid2, dem, 0).astype(np.float32), dx_row, dy_row).ravel()
    sl[~valid2.ravel()] = 0
    link = fc.link_lengths(ds, nrows, ncols, dx_row, dy_row)
    dto = fc.dist_to_outlet(order, ds, isout, link)
    ref = fc.hand_ref(order, ds, stream, zf)
    hand = zf - ref
    rows_idx = np.repeat(np.arange(nrows), ncols)
    a_spec = (acc.astype(np.float64) * 1e6) / dx_row[rows_idx]
    tanb = np.tan(np.radians(np.clip(sl, 0.05, 89)))
    twi = np.log(np.clip(a_spec, 1, None) / tanb).astype(np.float32)
    del a_spec, tanb
    v = lab > 0
    L = lab[v]
    ca = cell_area[v]
    area = np.bincount(L, weights=ca, minlength=m + 1)
    A = np.maximum(area, 1e-6)

    def wmean(x):
        return np.bincount(L, weights=x[v] * ca, minlength=m + 1) / A
    srt = np.argsort(L, kind="stable")
    Ls = L[srt]
    starts = np.flatnonzero(np.r_[True, Ls[1:] != Ls[:-1]])
    gid = Ls[starts]                                        # == 1..m (every kept basin has >= 1 cell)

    def gmax(x):
        o = np.zeros(m + 1, np.float64)
        o[gid] = np.maximum.reduceat(x[v][srt], starts)
        return o

    def gmin(x):
        o = np.zeros(m + 1, np.float64)
        o[gid] = np.minimum.reduceat(x[v][srt], starts)
        return o
    elev_mean, elev_max, elev_min = wmean(zf), gmax(zf), gmin(zf)
    slope_mean, slope_max = wmean(sl), gmax(sl)
    relief = elev_max - elev_min
    Lmain = gmax(dto)                                       # m, longest flow path to the outlet
    S_main = np.clip(relief / np.maximum(Lmain, 1.0), 1e-3, None)
    tc_min = fc.kirpich_tc_min(Lmain, S_main)
    stream_len_km = np.bincount(L, weights=(link[v] * stream[v]) / 1000.0, minlength=m + 1)
    dd = stream_len_km / A
    twi_mean = wmean(twi)
    hand_mean = wmean(hand)
    hand_low = np.bincount(L, weights=(hand[v] < 5.0) * ca, minlength=m + 1) / A
    form = (area * 1e6) / np.maximum(Lmain, 1.0) ** 2
    cols_v = (np.flatnonzero(v) % ncols).astype(np.float64)
    cx = np.bincount(L, weights=(cols_v + 0.5) * ca, minlength=m + 1) / A * res + W
    del cols_v
    cy = N - (np.bincount(L, weights=(rows_idx[v] + 0.5) * ca, minlength=m + 1) / A) * res
    up_area = np.zeros(m + 1)
    up_area[out_lab] = acc[outs]
    log("terrain features done")
    del dto, ref, hand, twi, sl, link
    # ---------------- land cover / soil / CN (tile loop)
    lc = np.load(a.modis)
    lc1, lres, llon0, llat0 = lc["lc1"], float(lc["res"]), float(lc["lon0"]), float(lc["lat0"])
    tabM = fc.cn_table(fc.CN_IGBP, 255)
    tabK = fc.cn_table(fc.CN_KNTU, 13)
    cnt_lc = np.zeros((m + 1, 18))
    cn_sum_m = np.zeros(m + 1)
    n_m = np.zeros(m + 1)
    kfrac = np.zeros((m + 1, 14))
    cn_sum_k = np.zeros(m + 1)
    n_k = np.zeros(m + 1)
    hsg_cnt = np.zeros((m + 1, 4))
    tex_cnt = np.zeros((m + 1, 12))
    sand_sum = np.zeros(m + 1)
    clay_sum = np.zeros(m + 1)
    n_s = np.zeros(m + 1)
    lab2 = lab.reshape(nrows, ncols)
    ins2 = inside.reshape(nrows, ncols)
    tile_px = int(round(1.0 / res))
    tiles = []
    for r0 in range(0, nrows, tile_px):
        for c0 in range(0, ncols, tile_px):
            r1, c1 = min(r0 + tile_px, nrows), min(c0 + tile_px, ncols)
            if lab2[r0:r1, c0:c1].max() > 0:
                tiles.append((r0, r1, c0, c1))
    log("land-cover/soil tiles to process:", len(tiles))
    ee = None
    soil_img = kntu_img = None
    if a.gee:
        try:
            import gee_grid
            ee = gee_grid.ee_init()
            soil_img = gee_grid.soil_image(ee)
            kntu_img = gee_grid.kntu_fraction_image(ee)
            log("Earth Engine ready")
        except Exception as ex:  # noqa: BLE001
            log("Earth Engine unavailable -> MODIS only, HSG default C:", repr(ex)[:200])
            ee = None
    gee_stat = {"soil_ok": 0, "soil_fail": 0, "kntu_ok": 0, "kntu_fail": 0}

    dead = {"gee": 0 if ee is not None else 3}
    gee_stat["soil_isric_ok"] = 0
    gee_stat["soil_isric_fail"] = 0

    def get_gee(job):
        r0, r1, c0, c1 = job
        bbox = (W + c0 * res, N - r1 * res, W + c1 * res, N - r0 * res)
        out = [None, None, None]
        for k, img in ((0, soil_img), (1, kntu_img)):
            try:
                if dead["gee"] >= 3:
                    raise RuntimeError("EE skipped after repeated permission errors")
                out[k] = gee_grid.fetch_tile_sub(ee, img, bbox, res, sub=(0.5 if k == 0 else 0.25))
                gee_stat[("soil_ok", "kntu_ok")[k]] += 1
            except Exception as ex:  # noqa: BLE001
                gee_stat[("soil_fail", "kntu_fail")[k]] += 1
                if "denied" in str(ex).lower() or "permission" in str(ex).lower():
                    dead["gee"] += 1
                out[2] = out[2] or str(ex)[:200]
        if out[0] is None:  # soil fallback: ISRIC SoilGrids straight from files.isric.org
            try:
                out[0] = gee_grid.soilgrids_tile(bbox, res)
                gee_stat["soil_isric_ok"] += 1
            except Exception as ex:  # noqa: BLE001
                gee_stat["soil_isric_fail"] += 1
                out[2] = out[2] or ("ISRIC: " + str(ex)[:200])
        return job, out

    def process(job, soil, kn):
        r0, r1, c0, c1 = job
        lb = lab2[r0:r1, c0:c1]
        mk = lb > 0
        if not mk.any():
            return
        H, Wd = lb.shape
        rr = (np.arange(r0, r1) + 0.5) * res
        cc = (np.arange(c0, c1) + 0.5) * res
        mi = np.clip(np.floor(rr / lres).astype(int), 0, lc1.shape[0] - 1)
        mj = np.clip(np.floor(cc / lres).astype(int), 0, lc1.shape[1] - 1)
        cls = lc1[np.ix_(mi, mj)].astype(np.int32)
        lbm = lb[mk]
        # HSG
        hsg = np.full((H, Wd), 2, np.int8)
        have_soil = np.zeros((H, Wd), bool)
        if soil is not None:
            sd, cl = soil[0][:H, :Wd], soil[1][:H, :Wd]
            have_soil = np.isfinite(sd) & np.isfinite(cl) & ((sd + cl) > 0)
            tex = fc.usda_texture_class(np.where(have_soil, sd, 40), np.where(have_soil, cl, 20))
            hsg = np.where(have_soil, np.asarray(fc._TEX_HSG, np.int8)[tex], 2).astype(np.int8)
            ms = mk & have_soil
            if ms.any():
                lbs = lb[ms]
                n_s[:] += np.bincount(lbs, minlength=m + 1)
                sand_sum[:] += np.bincount(lbs, weights=sd[ms], minlength=m + 1)
                clay_sum[:] += np.bincount(lbs, weights=cl[ms], minlength=m + 1)
                hsg_cnt[:] += np.bincount(lbs * 4 + hsg[ms], minlength=(m + 1) * 4).reshape(m + 1, 4)
                tex_cnt[:] += np.bincount(lbs * 12 + tex[ms], minlength=(m + 1) * 12).reshape(m + 1, 12)
        # MODIS
        cnm = tabM[np.clip(cls, 0, 255), hsg]
        cnt_lc[:] += np.bincount(lbm * 18 + np.clip(np.where(cls[mk] > 17, 16, cls[mk]), 0, 17), minlength=(m + 1) * 18).reshape(m + 1, 18)
        cn_sum_m[:] += np.bincount(lbm, weights=cnm[mk], minlength=m + 1)
        n_m[:] += np.bincount(lbm, minlength=m + 1)
        # KNTU
        if kn is not None:
            fr = kn[:, :H, :Wd]
            tot = fr.sum(0)
            okk = mk & (tot > 50)
            if okk.any():
                cnk = np.zeros((H, Wd), np.float32)
                lbk = lb[okk]
                for k in range(1, 14):
                    f = fr[k - 1] / np.maximum(tot, 1e-6)
                    cnk += f * tabK[k][hsg]
                    kfrac[:, k] += np.bincount(lbk, weights=f[okk], minlength=m + 1)
                cn_sum_k[:] += np.bincount(lbk, weights=cnk[okk], minlength=m + 1)
                n_k[:] += np.bincount(lbk, minlength=m + 1)

    if a.gee:
        from concurrent.futures import ThreadPoolExecutor
        jobs = [t for t in tiles if ins2[t[0]:t[1], t[2]:t[3]].any()]
        log("GEE tiles (touching Iran):", len(jobs))
        first_err = None
        done = 0
        with ThreadPoolExecutor(8) as exr:
            for job, (soil, kn, er) in exr.map(get_gee, jobs):
                process(job, soil, kn)
                first_err = first_err or er
                done += 1
                if done % 25 == 0:
                    log("  GEE tiles done %d/%d %s" % (done, len(jobs), gee_stat))
        done_set = set(jobs)
        for t in tiles:
            if t not in done_set:
                process(t, None, None)
        log("GEE stats:", gee_stat, "first error:", first_err)
    else:
        for t in tiles:
            process(t, None, None)
    meta["gee_stats"] = gee_stat
    log("land cover / CN done")

    # ---------------- assemble features
    sl_ok = n_s > 0
    cn_m = np.where(n_m > 0, cn_sum_m / np.maximum(n_m, 1), 85.0)
    cn_k = np.where(n_k > 0, cn_sum_k / np.maximum(n_k, 1), np.nan)
    have_k = (n_k >= 0.5 * np.maximum(n_m, 1))
    cn = np.where(have_k, cn_k, cn_m)
    meta["cn_source"] = {"kntu_basins": int(have_k[1:].sum()), "modis_only_basins": int((~have_k[1:]).sum()),
                         "soil_basins": int(sl_ok[1:].sum()), "hsg_default_C_basins": int((~sl_ok[1:]).sum())}
    Sret = 25400.0 / cn - 254.0
    dom_modis = cnt_lc[:, 1:].argmax(1) + 1
    dom_kntu = kfrac[:, 1:14].argmax(1) + 1
    dom_tex = np.where(sl_ok, tex_cnt.argmax(1), -1)
    sand_m = np.where(sl_ok, sand_sum / np.maximum(n_s, 1), np.nan)
    clay_m = np.where(sl_ok, clay_sum / np.maximum(n_s, 1), np.nan)

    # ---------------- susceptibility index
    idx = np.arange(1, m + 1)
    feats = {
        "slope_mean": slope_mean[idx], "cn": cn[idx], "tc_inv": 1.0 / tc_min[idx], "drainage_density": dd[idx],
        "relief_ratio": (relief / np.maximum(Lmain, 1.0))[idx], "hand_low_frac": hand_low[idx], "twi": twi_mean[idx], "form_factor": form[idx]}
    weights = {"slope_mean": 0.18, "cn": 0.22, "tc_inv": 0.18, "drainage_density": 0.10, "relief_ratio": 0.12,
               "hand_low_frac": 0.10, "twi": 0.05, "form_factor": 0.05}
    from scipy.stats import rankdata

    def prank(x):
        return (rankdata(np.nan_to_num(x, nan=np.nanmedian(x))) - 1) / max(len(x) - 1, 1)
    R = {k: prank(v) for k, v in feats.items()}
    keys = list(weights)
    wv = np.array([weights[k] for k in keys])
    assert abs(wv.sum() - 1) < 1e-9
    Rm = np.vstack([R[k] for k in keys])                   # (K, m)
    base = 100.0 * (wv[:, None] * Rm).sum(0)
    qs = np.percentile(base, [20, 40, 60, 80])
    level = np.digitize(base, qs) + 1                        # 1..5
    dom_factor = np.array(keys)[(wv[:, None] * Rm).argmax(0)]
    # weight sensitivity: Dirichlet perturbation around the base weights
    rng = np.random.default_rng(42)
    ns = 400
    Wdir = rng.dirichlet(wv * 40.0, size=ns)                # (ns, K)
    idx_s = 100.0 * (Wdir @ Rm)                                # (ns, m)
    lev_s = np.stack([np.digitize(r, qs) + 1 for r in idx_s])
    stability = (lev_s == level[None, :]).mean(0)
    rk_std = np.std(np.stack([prank(r) for r in idx_s[::10]]), axis=0)
    meta["susceptibility"] = {
        "formula": "index = 100 * sum_i w_i * percentile_rank_i  (ranks over all Iranian sub-basins; larger factor => larger susceptibility)",
        "weights": weights, "level_breaks_q20_40_60_80": [round(float(x), 2) for x in qs],
        "levels": {"1": "Very Low", "2": "Low", "3": "Moderate", "4": "High", "5": "Very High"},
        "colors": {"1": "#1a7a2e", "2": "#7cc242", "3": "#f2d024", "4": "#f08a1c", "5": "#d7191c"},
        "sensitivity": {"samples": ns, "dirichlet_concentration": 40, "median_level_stability": round(float(np.median(stability)), 3),
                        "share_basins_stability_ge_0.8": round(float((stability >= 0.8).mean()), 3),
                        "median_rank_std_percentile": round(float(np.median(rk_std)), 4)},
        "caution": "RELATIVE susceptibility ranking, not a probability and not a forecast. Weights are expert-chosen (AHP-like) and NOT calibrated to observed floods."}
    meta["counts"] = {"basins": m, "area_km2_total": round(float(area[1:].sum()), 0),
                      "area_km2_median": round(float(np.median(area[1:])), 1), "area_km2_p10": round(float(np.percentile(area[1:], 10)), 1),
                      "area_km2_p90": round(float(np.percentile(area[1:], 90)), 1)}
    meta["assumptions"] = {
        "cn_modis_igbp": {str(k): list(v) for k, v in fc.CN_IGBP.items()}, "cn_kntu": {str(k): list(v) for k, v in fc.CN_KNTU.items()},
        "hsg_from": "SoilGrids 2.0 sand/clay 0-30 cm -> USDA texture -> NRCS HSG rule of thumb (default C when soil missing)",
        "cn_condition": "AMC-II, Ia=0.2S; land-cover -> NEH-630 cover mapping is an ASSUMPTION to be calibrated",
        "tc": "Kirpich from longest flow path and relief/length slope; clipped >= 10 min",
        "attribution": ["Copernicus DEM GLO-90/30 (Copernicus/ESA, free licence)", "MODIS MCD12Q1 v061 (Friedl & Sulla-Menashe 2022, doi:10.5067/MODIS/MCD12Q1.061)",
                        "KNTU Iran Land Cover V1 (Ghorbanian et al. 2020, CC BY 4.0)", "ISRIC SoilGrids 2.0 (CC BY 4.0)", "PyFlwDir (Deltares, MIT)"]}

    # ---------------- polygons + output
    import rasterio.features
    from shapely.geometry import shape, mapping, MultiPolygon
    from shapely.ops import unary_union
    polys = {}
    if a.merit:
        for _g, _geom in merit_geom.items():
            if _g < new_id.size and new_id[_g] > 0:
                polys.setdefault(int(new_id[_g]), []).append(_geom)
    else:
      for geom, val in rasterio.features.shapes(lab.reshape(nrows, ncols).astype(np.int32), mask=(lab.reshape(nrows, ncols) > 0), transform=tr, connectivity=8):
        polys.setdefault(int(val), []).append(shape(geom))
    log("polygonised:", len(polys))
    feats_out = []
    prov = None
    for i in range(1, m + 1):
        g = polys.get(i)
        if not g:
            continue
        g = g[0] if len(g) == 1 else unary_union(g)
        g = g.simplify(res * 0.75, preserve_topology=True)
        gj = mapping(g)

        def rnd(c):
            return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 3), round(c[1], 3)]
        gj = {"type": gj["type"], "coordinates": rnd(gj["coordinates"])}
        lcname = KNTU_EN[int(dom_kntu[i])] if have_k[i] else LC_EN.get(int(dom_modis[i]), "?")
        lcname_fa = KNTU_FA[int(dom_kntu[i])] if have_k[i] else LC_FA.get(int(dom_modis[i]), "?")
        props = {
            "basin_id": i, "basin_name": "SB-%05d" % i, "ds_id": int(ds_id[i]), "area_km2": round(float(area[i]), 1),
            "upstream_area_km2": round(float(up_area[i]), 0), "lon": round(float(cx[i]), 3), "lat": round(float(cy[i]), 3),
            "elev_mean_m": int(round(elev_mean[i])), "elev_min_m": int(round(elev_min[i])), "elev_max_m": int(round(elev_max[i])),
            "mean_slope": round(float(slope_mean[i]), 2), "max_slope": round(float(slope_max[i]), 1),
            "relief_m": int(round(relief[i])), "main_len_km": round(float(Lmain[i] / 1000), 1), "tc_min": int(round(float(tc_min[i]))),
            "drainage_density": round(float(dd[i]), 3), "twi_mean": round(float(twi_mean[i]), 2), "hand_mean_m": round(float(hand_mean[i]), 1),
            "hand_lt5_frac": round(float(hand_low[i]), 3), "form_factor": round(float(form[i]), 3),
            "land_cover": lcname, "land_cover_fa": lcname_fa,
            "soil_type": fc.USDA_CLASSES[int(dom_tex[i])] if dom_tex[i] >= 0 else None,
            "soil_type_fa": SOIL_FA[int(dom_tex[i])] if dom_tex[i] >= 0 else None,
            "sand_pct": None if np.isnan(sand_m[i]) else round(float(sand_m[i]), 1), "clay_pct": None if np.isnan(clay_m[i]) else round(float(clay_m[i]), 1),
            "hsg_dominant": "ABCD"[int(hsg_cnt[i].argmax())] if sl_ok[i] else "C?",
            "cn2": round(float(cn[i]), 1), "cn2_modis": round(float(cn_m[i]), 1), "cn2_kntu": None if np.isnan(cn_k[i]) else round(float(cn_k[i]), 1),
            "s_mm": round(float(Sret[i]), 1),
            "susceptibility_index": round(float(base[i - 1]), 1), "susceptibility_level": int(level[i - 1]),
            "susceptibility_stability": round(float(stability[i - 1]), 2), "dominant_static_factor": str(dom_factor[i - 1]),
            }
        if have_k[i]:
            props["kntu_share"] = {KNTU_EN[k]: round(float(kfrac[i, k] / max(n_k[i], 1)), 3) for k in range(1, 14) if kfrac[i, k] / max(n_k[i], 1) >= 0.02}
        props["modis_share"] = {LC_EN[k]: round(float(cnt_lc[i, k] / max(n_m[i], 1)), 3) for k in range(1, 18) if cnt_lc[i, k] / max(n_m[i], 1) >= 0.02}
        feats_out.append({"type": "Feature", "properties": props, "geometry": gj})
    fc_json = {"type": "FeatureCollection", "name": "metstat_flood_basins_iran", "features": feats_out,
               "metadata": {"generated_utc": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "stage": "static", "version": 1,
                            "note": "Susceptibility is relative (0-100) and uncalibrated."}}
    p = os.path.join(a.out, "flood_basins_iran.geojson")
    json.dump(fc_json, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
    meta["output"] = {"geojson_bytes": os.path.getsize(p), "features": len(feats_out)}
    meta["runtime_s"] = round(time.time() - T0)
    json.dump(meta, open(os.path.join(a.out, "flood_static_meta.json"), "w"), ensure_ascii=False, indent=1)
    log("OK  basins=%d  geojson=%.1f MB" % (len(feats_out), os.path.getsize(p) / 1e6))


if __name__ == "__main__":
    out = "data/static"
    for i, x in enumerate(sys.argv):
        if x == "--out" and i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
    try:
        main()
    except BaseException:  # noqa: BLE001
        log("FAILED:\n" + traceback.format_exc())
        raise
    finally:
        try:
            os.makedirs(out, exist_ok=True)
            open(os.path.join(out, "flood_static_log.txt"), "w").write("\n".join(LOG) + "\n")
        except Exception:  # noqa: BLE001
            pass
