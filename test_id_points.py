import numpy as np, id_points as ip
seats = ip.load_seats(); assert len(seats) >= 480
pl = [['روستا%d' % i, 30 + i * 0.01, 52 + i * 0.01, 3, 5000 + i, 'pl', 'v'] for i in range(50)]
pts = ip.build(seats, pl); assert len(pts) > len(seats) and pts[0][2] == seats[0][0]
H, W = 960, 1440; yy, xx = np.mgrid[0:H, 0:W]; f = 42 - (yy + .5) / 32; f[0:100] = np.nan
w = ip.encode(f, pts); crc, n, v = ip.decode(w); assert crc == ip.crc16(pts) and n == len(pts)
exp = np.round(ip.sample(f, pts), 1); assert np.allclose(np.nan_to_num(v), np.nan_to_num(exp), atol=0.05)
assert len(w) < 20000, len(w); print('OK id_points', len(pts), len(w), 'bytes')
