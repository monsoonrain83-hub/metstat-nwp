"""V104 daily pressure-height anomaly, with explicit synoptic ERA5 reference.

Only exact run-relative +6,+12,+18,+24 hour samples from one native source
per day. Missing days do not borrow older runs or mix source resolutions.
The reference cache is a new, separately provisioned artifact: no fallback
to the legacy 1990–2019 cache or an undocumented monthly climatology.
"""
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import zipfile
import numpy as np
from scipy.ndimage import map_coordinates
from anomaly_windows import sample_times, strict_mean

LEVELS = (500, 700)
HOURS = (0, 6, 12, 18)
BOUNDS = {500: (3500, 6700), 700: (2000, 3800)}
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_EXPANDED = 160 * 1024 * 1024


def grid_identity(source):
    return tuple(getattr(source, key, None) for key in
                 ('dom', 'nx', 'ny', 'la0', 'lo0', 'dx', 'dy', 'i0', 'i1', 'j0', 'j1'))


def physical_height(value, level):
    if not isinstance(value, np.ndarray) or value.ndim != 2 or not value.size:
        return None
    a = np.asarray(np.ma.filled(np.ma.asarray(value, dtype=np.float32), np.nan))
    lo, hi = BOUNDS[level]
    good = np.isfinite(a) & (a >= lo) & (a <= hi)
    return np.where(good, a, np.nan) if good.any() else None


def collect(state, fields, valid, levels):
    """Keep at most the four most recent synoptic samples for each source/level."""
    lead = (valid - state.run).total_seconds()
    if not 0 < lead <= 15*86400 or lead % 21600:
        return
    if not hasattr(state, 'zser'):
        state.zser = {}
    cutoff = valid - timedelta(hours=18)
    for series in state.zser.values():
        for old in tuple(series):
            if old < cutoff:
                del series[old]
    for key in ('main', 'upper'):
        source = state.srcs.get(key)
        if source is None:
            continue
        for level in levels:
            value = physical_height(fields.get(key, {}).get(f'geopotential_height_{level}hPa'), level)
            if value is not None:
                state.zser.setdefault((key, level), {})[valid] = (grid_identity(source), value)


def native_day(state, end, level):
    times = sample_times(state.run, end, 1)
    if not times:
        return None
    for key in ('main', 'upper'):
        source = state.srcs.get(key)
        series = getattr(state, 'zser', {}).get((key, level), {})
        if source is None or any(t not in series for t in times):
            continue
        signature = grid_identity(source)
        if any(series[t][0] != signature for t in times):
            continue
        samples = [series[t][1] for t in times]
        if level == 700:
            # Never claim a 700 hPa height where that surface lies below terrain.
            # The native model terrain is required for this new product.
            try:
                hs = source.hsurf()
            except Exception:
                continue
            if not isinstance(hs, np.ndarray) or hs.shape != samples[0].shape:
                continue
            samples = [np.where(np.isfinite(hs) & (hs < x), x, np.nan) for x in samples]
        mean = strict_mean(samples)
        if mean is not None:
            return source, mean
    return None


def _axis(axis, lo, hi):
    a = np.asarray(axis, dtype=np.float64)
    if a.ndim != 1 or len(a) < 2 or not np.isfinite(a).all():
        raise ValueError('invalid reference coordinate')
    step = np.diff(a)
    if not (step > 0).all() or not np.allclose(step, step[0], atol=1e-6, rtol=0):
        raise ValueError('reference coordinate is not increasing and regular')
    if a[0] < lo or a[-1] > hi:
        raise ValueError('reference coordinate outside geographic bounds')
    return a


class SynopticReference:
    """Arrays are [366 calendar dates, 4 UTC hours, latitude, longitude], in metres.

    Dates use the leap-year calendar (2000-01-01..2000-12-31), including
    February 29 explicitly. Hourly 1991–2020 climatology must be prepared
    upstream; this reader checks its declared contract and bytes, not its
    scientific provenance independently.
    """
    def __init__(self, arrays, metadata):
        if (metadata.get('schema') != 1 or metadata.get('source') != 'ERA5' or
            metadata.get('base_period') != '1991-2020' or
            metadata.get('temporal_basis') != 'synoptic_6h' or
            metadata.get('calendar') != '366_month_day' or
            metadata.get('hours_utc') != list(HOURS) or
            metadata.get('units') != 'm'):
            raise ValueError('reference metadata does not match required ERA5 contract')
        self.lat = _axis(arrays['lat'], -90, 90)
        self.lon = _axis(arrays['lon'], -180, 180)
        shape = (366, 4, len(self.lat), len(self.lon))
        self.fields = {}
        for level in LEVELS:
            a = arrays[f'z{level}']
            if a.shape != shape or a.dtype.kind not in 'fc' or np.iscomplexobj(a):
                raise ValueError('reference array shape/type mismatch')
            lo, hi = BOUNDS[level]
            if not np.isfinite(a).all() or a.min() < lo or a.max() > hi:
                raise ValueError('reference contains missing or implausible heights')
            self.fields[level] = a.astype(np.float32, copy=False)

    @classmethod
    def load(cls, path, metadata_path):
        path, metadata_path = Path(path), Path(metadata_path)
        if path.stat().st_size > MAX_ARCHIVE or metadata_path.stat().st_size > 8192:
            raise ValueError('reference exceeds bounded cache size')
        with metadata_path.open('r', encoding='utf-8') as f:
            metadata = json.load(f)
        if not isinstance(metadata, dict):
            raise ValueError('invalid reference metadata')
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024*1024), b''):
                digest.update(chunk)
            if metadata.get('sha256') != digest.hexdigest():
                raise ValueError('reference checksum mismatch')
            f.seek(0)
            with zipfile.ZipFile(f) as archive:
                names = archive.namelist()
                if len(names) != 4 or set(names) != {'lat.npy','lon.npy','z500.npy','z700.npy'}:
                    raise ValueError('unexpected reference archive members')
                if sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED:
                    raise ValueError('expanded reference exceeds limit')
            f.seek(0)
            with np.load(f, allow_pickle=False) as arrays:
                return cls(arrays, metadata)

    def at(self, level, valid, region):
        if valid.utcoffset() != timedelta(0) or valid.hour not in HOURS or valid.minute or valid.second or valid.microsecond:
            return None
        lat, lon = np.asarray(region.lat), np.asarray(region.lon)
        if (lat.shape != lon.shape or lat.ndim != 2 or not lat.size or
            not np.isfinite(lat).all() or not np.isfinite(lon).all() or
            lat.min() < self.lat[0] or lat.max() > self.lat[-1] or
            lon.min() < self.lon[0] or lon.max() > self.lon[-1]):
            return None
        day = datetime(2000, valid.month, valid.day).timetuple().tm_yday - 1
        f = self.fields[level][day, HOURS.index(valid.hour)]
        coords = np.array([(lat-self.lat[0])/(self.lat[1]-self.lat[0]),
                           (lon-self.lon[0])/(self.lon[1]-self.lon[0])])
        return map_coordinates(f, coords, order=1, mode='constant', cval=np.nan, prefilter=False)


def anomaly(state, end, level, region, reference):
    if reference is None:
        return None
    day = native_day(state, end, level)
    if day is None:
        return None
    source, mean = day
    # Regrid the valid daily mean and its mask using the same source coordinates.
    z = region.interp(source, mean)
    coverage = region.interp(source, np.isfinite(mean).astype(np.float32))
    c = strict_mean(reference.at(level, t, region) for t in sample_times(state.run, end, 1))
    if c is None or z is None or coverage is None or z.shape != c.shape or coverage.shape != c.shape:
        return None
    good = np.isfinite(z) & np.isfinite(c) & (coverage >= 1-1e-6)
    if not good.any():
        return None
    return np.where(good, (z-c)/10, np.nan).astype(np.float32), np.where(good,z/10,np.nan).astype(np.float32), source.dom
