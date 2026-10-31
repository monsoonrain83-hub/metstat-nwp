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
                "crsTransform": [res, 0, w, 0, -res, n], "format": "GEO_TIFF"})
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            a = parse_download(r.content)
            out = np.zeros((a.shape[0], nrow, ncol), np.float32)
            h, ww = min(nrow, a.shape[1]), min(ncol, a.shape[2])
            out[:, :h, :ww] = a[:, :h, :ww]
            return out
        except Exception as ex:  # noqa: BLE001 - retry on any transport / EE error
            err = ex
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
