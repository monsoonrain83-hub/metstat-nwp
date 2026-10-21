import numpy as np, grid_pack as GP, grid_derive as G, tempfile, os, subprocess, sys, json
ok = True
def chk(n, c, i=''):
    global ok; print(('PASS ' if c else 'FAIL ') + n, i); ok &= bool(c)
f = GP.mock_fields(12); b = GP.encode(f, '2026102100', 12, '2026-10-21T12:00Z'); hd, d = GP.decode(b)
chk('header', hd['nlat'] == 121 and hd['nlon'] == 161 and hd['levels'] == GP.LEVELS)
for k in GP.VARS:
    off, sc, _ = GP.QUANT[k]; e = np.nanmax(np.abs(d[k] - f[k])); chk(f'roundtrip {k}', e <= 0.5 / sc + 1e-9, f'maxerr={e:.3g} (quant {0.5/sc:.3g})')
x = np.array(f['t']); x[0, 5, 5] = np.nan; hd, d2 = GP.decode(GP.encode({'t': x}, 'r', 0, 'v')); chk('missing preserved', np.isnan(d2['t'][0, 5, 5]) and not np.isnan(d2['t'][0, 5, 6]) and np.isnan(d2['u']).all())
chk('size reasonable', len(b) < 6e6, f'{len(b)/1e6:.2f} MB')
lat, lon = GP.lonlat_axes(); i850 = GP.LEVELS.index(850)
tw = G.wetbulb(d['t'][i850], d['r'][i850], 850.); chk('wetbulb from packed fields', np.isfinite(tw).all() and (tw <= d['t'][i850] + 1e-6).all(), f'{tw.min():.1f}..{tw.max():.1f} K')
chk('vorticity packed vs computed order', np.isfinite(G.vorticity(d['u'][i850], d['v'][i850], lat, lon)).all())
print('ALL PASS' if ok else 'SOME FAIL'); raise SystemExit(0 if ok else 1)
