# آزمون بخش‌های غیر-XRO (ساخت JSON نمودار و PNG) با داده‌ی ساختگی؛ xarray لازم نیست
import types, datetime as dt, json, sys, numpy as np
sys.modules.setdefault("xarray", types.ModuleType("xarray"))
import xro_forecast as X
class V:  # شبیهِ DataArray کوچک
    def __init__(s, t, v): s.time = types.SimpleNamespace(values=np.array(t)); s.values = np.array(v)
    def dropna(s, d): return s
    def isel(s, time): return V(s.time.values[time], s.values[time])
rng = np.random.default_rng(1); t = [f"{2020 + k // 12}-{k % 12 + 1:02d}-01" for k in range(48)]; ds = {"Nino34": V(t, rng.normal(0, 1, 48))}
a = types.SimpleNamespace(hist=36, show=40)
mem = np.cumsum(rng.normal(0, .3, (100, 21)), 1) + 0.5
ser, summ, labs = X.build_ser(ds, "Nino34", mem, .5, a, dt.date(2023, 12, 1))
assert len(ser["fc"]["mem"]) == 40 and len(ser["fc"]["lead"]) == 21 and ser["fc"]["lead"][0] > 0 and len(ser["obs"]["t"]) == 36
assert ser["fc"]["lead"] == sorted(ser["fc"]["lead"]) and len(summ) <= 12 and 0 <= summ[0]["pp"] <= 100
png = X.render_png(ser, "test", .5); assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
assert len(json.dumps(ser)) < 400000
print("ok", labs[0], labs[-1], len(png), "bytes png", len(json.dumps(ser)), "bytes json")
