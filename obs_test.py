from obs_decode import decode_synop as d
# FORMAT-CONFORMANCE fixtures written from the WMO FM-12 spec (not real observations)
r = d("AAXX 03061 40754 12970 31808 10142 20061 30114 40178 60014 333 10168 21025 70005 91012 91135=")
assert r["wmo"] == "40754" and r["t"] == 14.2 and r["td"] == 6.1 and r["slp"] == 1017.8 and abs(r["ff_ms"] - 8) < .01 and r["dd"] == 180, r
assert r["p"] == 1011.4 and r["rr"] == 1.0 and r["vis_km"] == 20 and r["tmax"] == 16.8 and r["tmin"] == -2.5 and r["rr24_7"] == 0.5 and r["gust_ms"] == 12, r
r = d("AAXX 03124 40706 32965 00000 11033 21044 40101="); assert r["t"] == -3.3 and r["td"] == -4.4 and r["ff_ms"] == 0, r
r = d("AAXX 03123 99999 xx"); assert r is None or r["t"] is None
print("ok")
# --- r193: رگرسیون با گزارش واقعی ثبت‌شده در recent.json (ایستگاه 17098 کارس، ۴ نوامبر ۲۰۲۶؛ ارتفاع زیاد) ---
# گروه 48558 = ژئوپتانسیل سطح ۸۵۰ hPa (4a3hhh) است، نه فشار سطح دریا؛ نسخهٔ قبلی آن را slp=855.8 ثبت می‌کرد (۴۸۲ مشاهدهٔ اشتباه در ۸۰ ساعت)
r = d("AAXX 02034 17098 42660 52703 10037 20037 38255 48558 57003 83550 333 83640 85358 90730 91105==")
assert r["wmo"] == "17098" and r["t"] == 3.7 and r["td"] == 3.7 and r["p"] == 825.5 and r["dd"] == 270 and abs(r["ff_ms"] - 1.5) < .01 and r["vis_km"] == 10, r
assert r["slp"] is None, r
# --- فشار سطح دریای 900.0–999.9 hPa (گروه 49xxx) از روی مشخصات FM-12 (نمونهٔ ساختگی) ---
r = d("AAXX 06061 40754 12970 31808 10142 20061 30114 49905 60014="); assert r["slp"] == 990.5, r
r = d("AAXX 06061 40754 12970 31808 10142 20061 30114 40005 60014="); assert r["slp"] == 1000.5, r
print("ok r193")
