"""Fail-closed, physically unit-aware global anomaly kernel (no data downloading).

This module NEVER invents climatology, regrids regional fields into world data,
changes model forecasts or publishes products. A caller supplies one verified
forecast raster AND its date-matched, spatially compatible climatology raster.
"""
from datetime import datetime, timedelta
import numpy as np

G = 9.80665
GLOBAL_BBOX = (-180.0, -90.0, 180.0, 90.0)
FIELDS = {
    'ecmwf': frozenset(('t2m', 'z500', 'z700', 'z850', 'mslp')),
    'gfs': frozenset(('t2m', 'z500', 'z700', 'z850', 'mslp')),
    'icon': frozenset(('t2m', 'z500', 'mslp')),
    'gem': frozenset(('t2m', 'z500', 'mslp')),
    'ukmo': frozenset(('t2m', 'z500', 'mslp')),
}
OUT_UNITS = {'t2m': '°C', 'mslp': 'hPa', 'z500': 'dam', 'z700': 'dam', 'z850': 'dam'}

class AnomalyUnavailable(ValueError):
    """Refuse publication of an anomaly with missing or mismatched evidence."""

def _checked_array(data):
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim != 2 or not all(x >= 2 for x in arr.shape):
        raise AnomalyUnavailable('expected a two-dimensional physical raster')
    if np.isfinite(arr).mean() < .95:
        raise AnomalyUnavailable('insufficient finite global coverage')
    return arr

def _physical(arr, param, units):
    if param == 't2m':
        if units == 'K': out = arr - 273.15
        elif units in ('°C', 'degC'): out = arr
        else: raise AnomalyUnavailable('invalid temperature units')
        if np.nanmin(out) < -125 or np.nanmax(out) > 75:
            raise AnomalyUnavailable('temperature outside physical guard')
    elif param == 'mslp':
        if units == 'Pa': out = arr / 100
        elif units == 'hPa': out = arr
        else: raise AnomalyUnavailable('invalid MSLP units')
        if np.nanmin(out) < 800 or np.nanmax(out) > 1150:
            raise AnomalyUnavailable('MSLP outside physical guard')
    elif param in ('z500', 'z700', 'z850'):
        if units in ('m²/s²', 'm2/s2'): out = arr / G / 10
        elif units == 'm': out = arr / 10
        elif units == 'dam': out = arr
        else: raise AnomalyUnavailable('invalid geopotential-height units')
        limits = {'z500':(350,670), 'z700':(200,380), 'z850':(65,210)}[param]
        if np.nanmin(out) < limits[0] or np.nanmax(out) > limits[1]:
            raise AnomalyUnavailable('geopotential height outside level guard')
    else:
        raise AnomalyUnavailable('unsupported anomaly variable')
    return out

def _check_metadata(model, param, valid_time, climatology_meta, forecast_meta, shape):
    if model not in FIELDS or param not in FIELDS[model]:
        raise AnomalyUnavailable('parameter not authorized for this model')
    if valid_time.tzinfo is None or valid_time.utcoffset() != timedelta(0):
        raise AnomalyUnavailable('UTC forecast valid time required')
    if not isinstance(forecast_meta, dict) or not isinstance(climatology_meta, dict):
        raise AnomalyUnavailable('source and climatology metadata required')
    raw_valid = forecast_meta.get('valid_utc')
    try:
        declared_valid = datetime.fromisoformat(raw_valid.replace('Z', '+00:00'))
    except (TypeError, AttributeError, ValueError):
        raise AnomalyUnavailable('missing or invalid forecast valid_utc')
    if declared_valid.tzinfo is None or declared_valid != valid_time:
        raise AnomalyUnavailable('forecast frame time mismatch')
    for meta in (forecast_meta, climatology_meta):
        if tuple(meta.get('bbox_wgs84', ())) != GLOBAL_BBOX:
            raise AnomalyUnavailable('regional or unverified geographic extent')
        if tuple(meta.get('grid_shape', ())) != tuple(shape):
            raise AnomalyUnavailable('grid geometry does not match physical raster')
        if meta.get('grid_id') is None or not isinstance(meta.get('grid_id'),str):
            raise AnomalyUnavailable('grid identifier absent')
    if forecast_meta['grid_id'] != climatology_meta['grid_id']:
        raise AnomalyUnavailable('regridding to a shared geodetic grid required')
    if climatology_meta.get('base_period') != '1991-2020':
        raise AnomalyUnavailable('missing 1991–2020 baseline; do not fake anomalies')
    if not climatology_meta.get('source') or climatology_meta.get('verified') is not True:
        raise AnomalyUnavailable('unverified climatology source')
    if climatology_meta.get('valid_mmdd') != valid_time.strftime('%m-%d'):
        raise AnomalyUnavailable('climatology calendar date mismatch')
    expected_hour = climatology_meta.get('valid_hour_utc')
    if expected_hour is not None and expected_hour != valid_time.hour:
        raise AnomalyUnavailable('hourly climatology hour mismatch')
    if expected_hour is None and climatology_meta.get('temporal_basis') != 'daily_mean':
        raise AnomalyUnavailable('climatology temporal sampling unspecified')

def anomaly(model, param, valid_time, forecast, climatology, forecast_meta, climatology_meta):
    """Return anomaly and traceable metadata; no side effects or publication.

    A daily-mean climatology for an instantaneous field must be prominently
    labelled in the output manifest to avoid false apparent precision.
    """
    if not isinstance(valid_time, datetime):
        raise AnomalyUnavailable('valid timestamp required')
    fc, cl = _checked_array(forecast), _checked_array(climatology)
    if fc.shape != cl.shape:
        raise AnomalyUnavailable('forecast/climatology grid shape mismatch')
    _check_metadata(model, param, valid_time, climatology_meta, forecast_meta, fc.shape)
    f = _physical(fc, param, forecast_meta.get('units'))
    c = _physical(cl, param, climatology_meta.get('units'))
    delta = f - c
    if not np.isfinite(delta).all():
        delta = np.where(np.isfinite(f) & np.isfinite(c), delta, np.nan)
    return delta.astype(np.float32), {
        'logical_model':model,'parameter':param,'units':OUT_UNITS[param],
        'valid_utc':valid_time.isoformat(),
        'baseline_period':'1991-2020','baseline_source':climatology_meta['source'],
        'baseline_temporal_basis':climatology_meta.get('temporal_basis','hourly'),
        'source_grid_id':forecast_meta['grid_id'],
        'bbox_wgs84':list(GLOBAL_BBOX),
        'finite_fraction':float(np.isfinite(delta).mean()),
        'quality_passed':True, # publisher must separately verify source bytes and licensing
    }

def five_day_blocks(days):
    """Independent days 1–5, 6–10, 11–15; all 15 validated daily rasters required."""
    if set(days) != set(range(1, 16)):
        raise AnomalyUnavailable('all fifteen exact daily leads are required')
    arr = [_checked_array(days[d]) for d in range(1,16)]
    shape = arr[0].shape
    if any(a.shape != shape for a in arr):
        raise AnomalyUnavailable('daily raster shape mismatch')
    blocks = {}
    for start in (1,6,11):
        window=np.stack(arr[start-1:start+4],axis=0)
        if not np.isfinite(window).all():
            raise AnomalyUnavailable('incomplete 5-day raster window')
        blocks[f'{start}-{start+4}'] = window.mean(axis=0,dtype=np.float64).astype(np.float32)
    return blocks
