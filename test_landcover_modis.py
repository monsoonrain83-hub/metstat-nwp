"""آزمون بازنمونه‌گیری شبکهٔ سینوسی با نقشهٔ ساختگیِ شناخته‌شده (بدون شبکه/GDAL)."""
import numpy as np, landcover_modis as L

def truth(lon, lat):                      # کلاس به‌صورت تابعی از مکان (بلوک‌های ۰٫۵°)
    return ((np.floor(lon * 2) * 7 + np.floor(lat * 2) * 3) % 17).astype(np.uint8)

def fake_tile(h, v):
    r, c = np.meshgrid(np.arange(L.NPIX), np.arange(L.NPIX), indexing='ij')
    lon, lat = L.tile_px_center(h, v, r, c)
    return truth(lon, lat)

def test_roundtrip_indices():
    lon = np.array([44.0, 52.3, 60.1, 63.5]); lat = np.array([25.0, 32.0, 36.5, 39.9])
    h, v, r, c = L.sin_to_tile_px(lon, lat); lo, la = L.tile_px_center(h, v, r, c)
    assert np.all(np.abs(lo - lon) < 0.01) and np.all(np.abs(la - lat) < 0.005)   # در حد نیم‌پیکسل

def test_resample_matches_truth():
    need = set()
    w, s, e, n = L.BBOX
    LON, LAT = np.meshgrid(np.linspace(w, e, 60), np.linspace(s, n, 60))
    h, v, _, _ = L.sin_to_tile_px(LON, LAT); need = {(int(a), int(b)) for a, b in zip(h.ravel(), v.ravel())}
    print('کاشی‌های لازم برای ایران:', sorted('h%02dv%02d' % k for k in need))
    assert need <= {(h, v) for h in range(20, 26) for v in range(4, 8)}
    tiles = {k: fake_tile(*k) for k in need}
    out, lon0, lat0 = L.resample(tiles)
    assert out.shape == (3120, 4100) and lon0 == w and lat0 == n
    lon = lon0 + (np.arange(out.shape[1]) + .5) * L.RES; lat = lat0 - (np.arange(out.shape[0]) + .5) * L.RES
    LON, LAT = np.meshgrid(lon, lat); t = truth(LON, LAT)
    assert (out == 255).mean() == 0                    # همه‌جا پوشش دارد
    agree = (out == t).mean(); print('تطابق با حقیقت ساختگی: %.4f' % agree)
    assert agree > 0.99                                 # فقط مرز بلوک‌ها (نیم‌پیکسل) اختلاف دارد

if __name__ == '__main__':
    test_roundtrip_indices(); test_resample_matches_truth(); print('OK')
