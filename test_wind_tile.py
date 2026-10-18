import numpy as np, wind_tile as wt
H, W = 960, 1440; yy, xx = np.mgrid[0:H, 0:W]
u = 30 * np.sin(xx / 200.0) + 20 * np.cos(yy / 150.0); v = 25 * np.cos(xx / 170.0) - 10 * np.sin(yy / 90.0); u[:50] = np.nan
for sc in (0.5, 1.0, 2.0):
    w = wt.encode(u, v, sc); s, du, dv = wt.decode(w); assert abs(s - sc) < 1e-9 and du.shape == (120, 180)
    ru, rv = u[4::8, 4::8], v[4::8, 4::8]; m = np.isfinite(ru)
    assert np.nanmax(np.abs(du[m] - ru[m])) <= sc / 2 + 1e-9 and np.isnan(du[~m]).all(), sc
    print('OK scale', sc, len(w), 'bytes')
