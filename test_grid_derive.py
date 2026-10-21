import numpy as np, grid_derive as G
ok = True
def chk(name, cond, info=''):
    global ok; print(('PASS ' if cond else 'FAIL ') + name, info); ok &= bool(cond)
lat = np.linspace(8, -8, 65); lon = np.linspace(40, 56, 65); LA, LO = np.meshgrid(lat, lon, indexing='ij')
y = G.R_E * np.deg2rad(LA); x = G.R_E * np.deg2rad(LO) * np.cos(np.deg2rad(LA))
a = 1e-5
u = -a * y; v = np.zeros_like(u)          # ∂u/∂y = −a ⇒ ζ = +a
chk('vorticity shear', abs(np.nanmean(G.vorticity(u, v, lat, lon)[10:-10, 10:-10]) - a) < 0.08 * a, np.nanmean(G.vorticity(u, v, lat, lon)[10:-10, 10:-10]))
u2 = a * x / np.cos(np.deg2rad(LA)) * np.cos(np.deg2rad(LA)); v2 = a * y     # u=a·x, v=a·y ⇒ div = 2a
d = G.divergence(u2, v2, lat, lon)[10:-10, 10:-10]; chk('divergence', abs(np.mean(d) - 2 * a) < 0.1 * a, np.mean(d))
chk('deformation pure shear', abs(np.mean(G.shearing(u, v, lat, lon)[10:-10, 10:-10]) + a) < 0.08 * a)
chk('theta', abs(G.theta(300., 1000.) - 300) < 1e-9 and abs(G.theta(280., 850.) - 280 * (1000 / 850) ** 0.2854) < 2e-3)
chk('dewpoint rh100', abs(G.dewpoint(293.15, 100.) - 293.15) < 0.05)
chk('dewpoint 20C/50%', abs(G.dewpoint(293.15, 50.) - 282.4) < 0.4, G.dewpoint(293.15, 50.))
chk('wetbulb rh100', abs(G.wetbulb(np.array([290.]), np.array([100.]), 850.)[0] - 290) < 0.05)
tw = G.wetbulb(np.array([293.15]), np.array([50.]), np.array([1000.]))[0] - 273.15
chk('wetbulb 20C/50%/1000hPa ≈13.8', abs(tw - 13.8) < 0.5, tw)
tw850 = G.wetbulb(np.array([283.15]), np.array([60.]), np.array([850.]))[0]
chk('wetbulb between Td and T', G.dewpoint(283.15, 60.) < tw850 < 283.15, tw850)
chk('theta_e rises with moisture', G.theta_e(290., 90., 850.) > G.theta_e(290., 30., 850.))
chk('theta_e 25C/80%/1000 ≈ 335..345K', 333 < G.theta_e(298.15, 80., 1000.) < 352, G.theta_e(298.15, 80., 1000.))
# جبهه: θ با گرادیان شمال–جنوب، شکل‌گیری با همگرایی میدان کشش (v=−b·y ⇒ ∂v/∂y=−b ⇒ نزدیک‌شدن به محور)
th = 290 + 1e-5 * y; ub = np.zeros_like(y); vb = -1e-5 * y
F = G.frontogenesis(th, ub, vb, lat, lon)[10:-10, 10:-10]; chk('frontogenesis >0 (convergent)', np.mean(F) > 0, np.mean(F))
F2 = G.frontogenesis(th, ub, -vb, lat, lon)[10:-10, 10:-10]; chk('frontogenesis <0 (divergent)', np.mean(F2) < 0)
# TFP: τ=tanh(y/L): بیشینهٔ گرادیان در y=0؛ TFP در آن‌جا صفر و علامتش دو طرف مخالف
L = 2e5; tau = np.tanh(y / L) * 5; T = G.tfp(tau, lat, lon); j = np.argmin(abs(lat)); col = T[:, 32]
chk('tfp sign change at the front', col[j - 8] * col[j + 8] < 0 and abs(col[j]) < 0.2 * max(abs(col[j - 8]), abs(col[j + 8])))
q1, q2, dq = G.qvec(th, np.zeros_like(y), -1e-5 * y, 700., lat, lon); chk('qvec finite', np.isfinite(dq).all())
chk('smooth keeps constants', np.allclose(G.smooth(np.ones((20, 20)), 3), 1))
print('ALL PASS' if ok else 'SOME FAIL'); raise SystemExit(0 if ok else 1)
