"""Decode SYNOP (FM-12) sections 0-3 groups needed for MetStat. Pure functions, no network.
Returns None for anything absent/unparseable — never guesses."""
import re
def _sgn(s, t):  # sign digit + tenths
    if not (s in "01" and t.isdigit()): return None
    v = int(t) / 10.0
    return -v if s == "1" else v
def decode_synop(raw):
    r = {"wmo": None, "t": None, "td": None, "rh": None, "p": None, "slp": None, "dd": None, "ff_ms": None,
         "gust_ms": None, "rr": None, "rr_h": None, "tmax": None, "tmin": None, "rr24_7": None, "vis_km": None}
    s = raw.replace("=", " ").split()
    if "AAXX" not in s: return None
    i = s.index("AAXX"); g = s[i + 1:]
    if len(g) < 3 or not g[0].isdigit() or len(g[0]) != 5: return None
    iw = int(g[0][4]); r["wmo"] = g[1]
    sec3 = []
    if "333" in g:
        k = g.index("333"); sec3 = g[k + 1:]; g = g[:k]
        # Section 5 (555) and section 4 (444) have their own group meanings.
        # In particular, 1xxxx/2xxxx groups after 555 are NOT Tx/Tn.
        for boundary in ("444", "555"):
            if boundary in sec3: sec3 = sec3[:sec3.index(boundary)]
    kt = iw in (3, 4); fac = 0.514444 if kt else 1.0
    if len(g) > 3:
        ir = g[2][0]; d = g[3]
        if len(d) == 5 and d[1:3].isdigit() and d[3:].isdigit():
            if d[1:3] != "//" and d[:3] != "///": r["dd"] = int(d[1:3]) * 10
            ff = int(d[3:5]); rest = g[4:]
            if ff == 99 and rest and rest[0].startswith("00") and len(rest[0]) == 5: ff = int(rest[0][2:]); rest = rest[1:]
            r["ff_ms"] = round(ff * fac, 1)
        else: rest = g[4:]
        vv = g[2][3:5] if len(g[2]) == 5 else ""
        if vv.isdigit():
            v = int(vv); r["vis_km"] = v / 10 if v <= 50 else (v - 50 if v <= 80 else None)
        for x in rest:
            if len(x) != 5: continue
            c = x[0]
            if c == "1" and r["t"] is None: r["t"] = _sgn(x[1], x[2:])
            elif c == "2" and r["td"] is None and r["t"] is not None:
                if x[1] == "9" and x[2:].isdigit(): r["rh"] = int(x[2:])
                else: r["td"] = _sgn(x[1], x[2:])
            elif c == "3" and r["p"] is None and x[1:].isdigit():
                v = int(x[1:]) / 10; r["p"] = v + (1000 if v < 500 else 0)
            elif c == "4" and r["slp"] is None and x[1:].isdigit():
                # r193: قبلاً «x[1] != "9"» فشار 900.0–999.9 hPa (گروه 49xxx) را دور می‌ریخت. گروه ژئوپتانسیل 4a3hhh هرگز با 9 شروع نمی‌شود؛
                # برای جلوگیری از اشتباه با آن، فقط مقدار در بازهٔ فیزیکی فشار سطح دریا پذیرفته می‌شود.
                v = int(x[1:]) / 10; v = v + (1000 if v < 500 else 0)
                if 870 <= v <= 1085: r["slp"] = v
            elif c == "6" and r["rr"] is None and x[1:4].isdigit() and x[4].isdigit():
                n = int(x[1:4]); mm = 0.0 if n == 990 else (n - 990) / 10 if n > 990 else float(n)
                r["rr"] = mm; r["rr_h"] = {"1": 6, "2": 12, "3": 18, "4": 24, "5": 1, "6": 2, "7": 3, "8": 9, "9": 15}.get(x[4])
    later_section3_group = False
    for x in sec3:
        if len(x) != 5: continue
        # FM-12 section-3 Tx/Tn groups (1snTxTxTx / 2snTnTnTn) occur
        # before groups 3..9. Local groups such as "333 55093 21865"
        # are not minimum temperatures (-86.5 C in the example).
        if x[0] in "3456789": later_section3_group = True
        if x[0] == "1" and not later_section3_group and r["tmax"] is None: r["tmax"] = _sgn(x[1], x[2:])
        elif x[0] == "2" and not later_section3_group and r["tmin"] is None: r["tmin"] = _sgn(x[1], x[2:])
        elif x[0] == "7" and x[1:].isdigit() and r["rr24_7"] is None:
            n = int(x[1:]); r["rr24_7"] = 0.0 if n == 9999 else n / 10
        elif x[:3] == "910" and x[3:].isdigit(): r["gust_ms"] = round(int(x[3:]) * fac, 1)
    return r
