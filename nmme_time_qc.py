"""Decode NMME monthly target coordinates without inventing forecast dates."""
import math
import re
from datetime import datetime

def _index(y, m):
    return y * 12 + m - 1

def _month(i):
    y, m = divmod(i, 12)
    return y, m + 1

def target_month_offsets(values, units, calendar, run, num2date=None):
    """Return offsets relative to initialization month; reject ambiguous axes.

    Month-start/midmonth are representations of the same target month.
    CF absolute time axes are decoded using their declared epoch.
    Month lead coordinates without an epoch must explicitly declare months.
    """
    init = datetime.strptime(str(run), "%Y%m%d%H")
    base = _index(init.year, init.month)
    u = str(units or "").strip()
    v = [float(x) for x in values]
    if not v or len(v) > 24 or not all(math.isfinite(x) for x in v):
        raise ValueError("invalid monthly coordinate")
    m = re.fullmatch(r"months?\s+since\s+(\d{4})-(\d{1,2})-0?1(?:[ T]00:00(?::00(?:\.0+)?)?(?:Z|\s+UTC)?)?", u, re.I)
    if m:
        y, mo = map(int, m.groups())
        datetime(y, mo, 1)
        if any(abs(2*x-round(2*x))>1e-6 for x in v):
            raise ValueError("unsupported fractional month coordinate")
        off = [_index(y, mo)+math.floor(x+1e-8)-base for x in v]
    elif " since " in u.lower():
        if num2date is None:
            raise ValueError("absolute time decoder unavailable")
        dates = num2date(v, u, calendar=calendar or "standard")
        off = [_index(int(d.year), int(d.month))-base for d in dates]
    elif u.lower() in ("month", "months", "mon"):
        if any(abs(2*x-round(2*x))>1e-6 for x in v):
            raise ValueError("unsupported fractional month lead")
        off = [math.floor(x+1e-8) for x in v]
    else:
        raise ValueError("monthly target units absent or ambiguous")
    if any(x < 0 or x > 12 for x in off) or any(a>=b for a,b in zip(off,off[1:])):
        raise ValueError("target outside monthly horizon or not strictly increasing")
    return off

def valid_months(run, offsets):
    init = datetime.strptime(str(run), "%Y%m%d%H")
    out = []
    if not offsets or len(offsets)>24 or any(not isinstance(x,int) or not 0<=x<=12 for x in offsets) or any(a>=b for a,b in zip(offsets,offsets[1:])):
        raise ValueError("invalid target offsets")
    for x in offsets:
        y,m = _month(_index(init.year,init.month)+x)
        out.append(f"{y:04d}{m:02d}0100")
    return out
