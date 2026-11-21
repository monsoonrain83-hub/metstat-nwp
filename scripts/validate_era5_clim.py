"""Validate the *generated* ERA5 climatology before GitHub Actions commits it."""
import numpy as np
from pathlib import Path

p = Path('data/static/era5_clim_1deg.npz')
if not p.is_file():
    raise SystemExit(f'Missing ERA5 climatology: {p}')
with np.load(p, allow_pickle=False) as z:
    required = {'lat', 'lon', 'z500', 'z700', 'z850', 'msl', 't2m'}
    missing = required.difference(z.files)
    if missing:
        raise SystemExit(f'Incomplete ERA5 climatology, missing: {sorted(missing)}')
    lat, lon = z['lat'], z['lon']
    assert lat.shape == (61,) and lon.shape == (111,), (lat.shape, lon.shape)
    assert np.all(np.diff(lat)>0) and np.all(np.diff(lon)>0)
    ranges = {'z500':(3500,7000),'z700':(1500,4000),'z850':(500,2500),
              'msl':(800,1150),'t2m':(170,350)}
    for key,(lo,hi) in ranges.items():
        a = z[key]
        assert a.shape == (366,61,111), (key,a.shape)
        assert np.isfinite(a).all(), f'{key}: nonfinite'
        assert float(a.min())>lo and float(a.max())<hi, (key,float(a.min()),float(a.max()))
        print(f'{key}: {a.shape}, [{float(a.min()):.2f},{float(a.max()):.2f}]')
print('ERA5 artifact validated; temperature stored in Kelvin')
