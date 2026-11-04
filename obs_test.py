from obs_decode import decode_synop as d
# FORMAT-CONFORMANCE fixtures written from the WMO FM-12 spec (not real observations)
r = d("AAXX 03061 40754 12970 31808 10142 20061 30114 40178 60014 333 10168 21025 70005 91012 91135=")
assert r["wmo"] == "40754" and r["t"] == 14.2 and r["td"] == 6.1 and r["slp"] == 1017.8 and abs(r["ff_ms"] - 8) < .01 and r["dd"] == 180, r
assert r["p"] == 1011.4 and r["rr"] == 1.0 and r["vis_km"] == 20 and r["tmax"] == 16.8 and r["tmin"] == -2.5 and r["rr24_7"] == 0.5 and r["gust_ms"] == 12, r
r = d("AAXX 03124 40706 32965 00000 11033 21044 40101="); assert r["t"] == -3.3 and r["td"] == -4.4 and r["ff_ms"] == 0, r
r = d("AAXX 03123 99999 xx"); assert r is None or r["t"] is None
print("ok")
