"""Small helper to pull gridded Earth Engine data as numpy tiles (service-account auth).

Used by flood_static.py for: SoilGrids sand/clay, KNTU Iran land-cover fractions and
(as a fallback) the Copernicus GLO-30 DEM.  Only the aggregated 0.0025-deg grid is
downloaded (never the 10 m raster), tile by tile (each request << 32 MB).
"""
import io
import json
import os
import time
import zipfile

import numpy as np
import requests


def ee_init():
    import ee
    info = json.loads(os.environ["GEE_SERVICE_ACCOUNT_KEY"].strip(), strict=False)
    creds = ee.ServiceAccountCredentials(info["client_email"], key_data=json.dumps(info))
    ee.Initialize(creds, project=os.environ["GEE_PROJECT"].strip())
    return ee


def _read_tif(blob):
    from rasterio.io import MemoryFile
    with MemoryFile(blob) as mf:
        with mf.open() as src:
            return src.read().astype(np.float32)


def parse_download(blob):
    """Bytes of a getDownloadURL response -> array (bands, H, W)."""
    if blob[:2] == b"PK":  # zipped, one tif per band
        z = zipfile.ZipFile(io.BytesIO(blob))
        names = sorted(n for n in z.namelist() if n.lower().endswith(".tif"))
        return np.concatenate([_read_tif(z.read(n)) for n in names], axis=0)
    return _read_tif(blob)


def fetch_tile(ee, image, bbox_wsen, res, retries=5, pause=4.0):
    """Download ``image`` on the regular grid (west,south,east,north step ``res``) -> (bands,H,W)."""
    w, s, e, n = bbox_wsen
    ncol = int(round((e - w) / res))
    nrow = int(round((n - s) / res))
    err = None
    for k in range(retries):
        try:
            region = ee.Geometry.Rectangle([w, s, e, n], "EPSG:4326", False)
            url = image.getDownloadURL({
                "region": region, "crs": "EPSG:4326",
                "crs_transform": [res, 0, w, 0, -res, n], "format": "GEO_TIFF"})
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            a = parse_download(r.content)
            out = np.zeros((a.shape[0], nrow, ncol), np.float32)
            h, ww = min(nrow, a.shape[1]), min(ncol, a.shape[2])
            out[:, :h, :ww] = a[:, :h, :ww]
            return out
        except Exception as ex:  # noqa: BLE001 - retry on any transport / EE error
            err = ex
            if "denied" in str(ex).lower() or "permission" in str(ex).lower():
                break  # IAM problem: retrying cannot help
            time.sleep(pause * (k + 1))
    raise RuntimeError("EE tile failed: %s" % str(err)[:300])


# ---- images -------------------------------------------------------------------------
def soil_image(ee):
    """Top-soil (0-30 cm, depth-weighted) sand and clay in % from ISRIC SoilGrids 2.0 (CC BY 4.0)."""
    def wmean(name):
        im = ee.Image("projects/soilgrids-isric/%s_mean" % name)
        b = [im.select("%s_%s_mean" % (name, d)) for d in ("0-5cm", "5-15cm", "15-30cm")]
        v = b[0].multiply(5).add(b[1].multiply(10)).add(b[2].multiply(15)).divide(30).divide(10)
        return v.rename(name).setDefaultProjection(im.select(0).projection())
    img = ee.Image.cat([wmean("sand"), wmean("clay")])
    return img.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)


def kntu_fraction_image(ee, classes=13):
    """Class fractions (percent, 13 bands c01..c13) of the KNTU 10 m Iran land-cover map (CC BY 4.0)."""
    lc = ee.Image("KNTU/LiDARLab/IranLandCover/V1").select("classification")
    fr = ee.Image.cat([lc.eq(k).rename("c%02d" % k) for k in range(1, classes + 1)])
    fr = fr.setDefaultProjection(lc.projection()).reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)
    return fr.multiply(100)


def dem_image(ee):
    """Copernicus GLO-30 DEM mosaic (metres), mean-aggregated to the output grid."""
    col = ee.ImageCollection("COPERNICUS/DEM/GLO30").select("DEM")
    proj = col.first().projection()
    return col.mosaic().setDefaultProjection(proj).reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)


# ---- SoilGrids straight from ISRIC (no Earth Engine needed) -----------------------------
SG_BASE = "https://files.isric.org/soilgrids/latest/data/%s/%s_%s_mean.vrt"


def soilgrids_tile(bbox_wsen, res):
    """sand, clay in % (0-30 cm depth-weighted) on the regular grid -> (2,H,W) float32."""
    import rasterio
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    w, s, e, n = bbox_wsen
    ncol = int(round((e - w) / res))
    nrow = int(round((n - s) / res))
    tr = from_origin(w, n, res, res)
    out = []
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".vrt,.tif",
               GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="3", VSI_CACHE="TRUE")
    with rasterio.Env(**env):
        for name in ("sand", "clay"):
            acc = np.zeros((nrow, ncol), np.float32)
            wsum = np.zeros((nrow, ncol), np.float32)
            for depth, wt in (("0-5cm", 5), ("5-15cm", 10), ("15-30cm", 15)):
                with rasterio.open(SG_BASE % (name, name, depth)) as src:
                    with WarpedVRT(src, crs="EPSG:4326", transform=tr, width=ncol, height=nrow,
                                   resampling=Resampling.average, src_nodata=src.nodata, nodata=-32768) as v:
                        a = v.read(1).astype(np.float32)
                ok = a > -30000
                acc += np.where(ok, a, 0) * wt
                wsum += np.where(ok, wt, 0)
            out.append(np.where(wsum > 0, acc / np.maximum(wsum, 1e-6) / 10.0, 0).astype(np.float32))
    return np.stack(out)
