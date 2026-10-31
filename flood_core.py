"""MetStat flood module — numeric core (no heavy imports; numba is used when installed).

All grids are flattened (row-major) 1-D arrays.  ``ds[i]`` is the flat index of the
cell that cell *i* drains into (``ds[i]==i`` for a pit/outlet, ``-1`` for cells outside
the domain).  The flow directions themselves come from PyFlwDir (MIT) in
``flood_static.py``; everything below is our own code so it can be unit-tested
without PyFlwDir.

Physical/empirical formulas used (public-domain textbook methods):
  * SCS-CN runoff (NEH-630 ch.9/10):  S = 25400/CN - 254 [mm], Ia = 0.2 S
  * Kirpich time of concentration:    Tc[min] = 0.0195 * L[m]^0.77 * S[m/m]^-0.385
  * TWI = ln(a / tan(beta))           (Beven & Kirkby 1979)
  * HAND = z - z_nearest_drainage     (Rennó et al. 2008) — own implementation
"""
import math
import numpy as np

try:  # numba is installed together with pyflwdir in the Actions job
    from numba import njit
    HAVE_NUMBA = True
except Exception:  # pragma: no cover - local tests without numba
    HAVE_NUMBA = False

    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f


M_PER_DEG = 111320.0


@njit(cache=False)
def topo_order(ds):
    """Cells ordered upstream -> downstream (every cell after all cells draining into it)."""
    n = ds.size
    indeg = np.zeros(n, np.int32)
    for i in range(n):
        d = ds[i]
        if d >= 0 and d != i:
            indeg[d] += 1
    order = np.empty(n, np.int64)
    k = 0
    for i in range(n):
        if ds[i] >= 0 and indeg[i] == 0:
            order[k] = i
            k += 1
    h = 0
    while h < k:
        i = order[h]
        h += 1
        d = ds[i]
        if d != i:
            indeg[d] -= 1
            if indeg[d] == 0:
                order[k] = d
                k += 1
    return order[:k]


@njit(cache=False)
def accumulate(order, ds, w):
    acc = w.copy()
    for k in range(order.size):
        i = order[k]
        d = ds[i]
        if d != i:
            acc[d] += acc[i]
    return acc


@njit(cache=False)
def mark_outlets(order, ds, w, is_stream, a_target):
    """Area-based sub-basin outlets.

    Walk upstream->downstream accumulating the not-yet-assigned area; a *stream* cell
    whose unassigned area reaches ``a_target`` becomes an outlet and the counter restarts.
    Pits are always outlets.  Result: sub-basins of >= a_target (typically 1-2 x a_target),
    always outlet-on-stream, topologically nested (every sub-basin drains into exactly one).
    """
    n = ds.size
    loc = np.zeros(n, np.float64)
    isout = np.zeros(n, np.bool_)
    for k in range(order.size):
        i = order[k]
        loc[i] += w[i]
        d = ds[i]
        if d == i:
            isout[i] = True
        elif is_stream[i] and loc[i] >= a_target:
            isout[i] = True
        else:
            loc[d] += loc[i]
    return isout


@njit(cache=False)
def label_basins(order, ds, isout):
    n = ds.size
    lab = np.zeros(n, np.int32)
    nid = 0
    for k in range(order.size - 1, -1, -1):
        i = order[k]
        if isout[i]:
            nid += 1
            lab[i] = nid
        else:
            lab[i] = lab[ds[i]]
    return lab, nid


@njit(cache=False)
def dist_to_outlet(order, ds, isout, link):
    n = ds.size
    dto = np.zeros(n, np.float32)
    for k in range(order.size - 1, -1, -1):
        i = order[k]
        if isout[i]:
            dto[i] = 0.0
        else:
            dto[i] = dto[ds[i]] + link[i]
    return dto


@njit(cache=False)
def hand_ref(order, ds, is_stream, z):
    """Elevation of the nearest downstream drainage cell (for HAND = z - ref)."""
    n = ds.size
    ref = np.zeros(n, np.float32)
    for k in range(order.size - 1, -1, -1):
        i = order[k]
        if is_stream[i] or ds[i] == i:
            ref[i] = z[i]
        else:
            ref[i] = ref[ds[i]]
    return ref


# ----------------------------------------------------------------------------------
# geometry helpers
# ----------------------------------------------------------------------------------
def cell_geometry(nrows, ncols, lat_top, res):
    """Per-row cell width/height in metres and area in km2 (geographic grid)."""
    lat = lat_top - (np.arange(nrows) + 0.5) * res
    dy = np.full(nrows, res * M_PER_DEG, np.float64)
    dx = res * M_PER_DEG * np.cos(np.radians(lat))
    return lat, dx, dy, dx * dy / 1e6


def link_lengths(ds, nrows, ncols, dx_row, dy_row):
    """Metres from every cell to its downstream neighbour (0 for pits / invalid)."""
    n = ds.size
    idx = np.arange(n, dtype=np.int64)
    valid = ds >= 0
    r = idx // ncols
    c = idx % ncols
    d = np.where(valid, ds, 0)
    dr = np.abs(d // ncols - r)
    dc = np.abs(d % ncols - c)
    L = np.hypot(dc * dx_row[r], dr * dy_row[r]).astype(np.float32)
    L[~valid] = 0
    L[ds == idx] = 0
    return L


def slope_deg(z2d, dx_row, dy_row):
    """Central-difference slope in degrees (float32)."""
    gy = np.gradient(z2d.astype(np.float32), axis=0) / (2 * dy_row[:, None]).astype(np.float32)
    gx = np.gradient(z2d.astype(np.float32), axis=1) / (2 * dx_row[:, None]).astype(np.float32)
    return np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)


# ----------------------------------------------------------------------------------
# SCS-CN tables (NEH-630 chapter 9, AMC-II, Ia = 0.2S).  Columns = HSG A,B,C,D.
# Mapping from land-cover classes to NEH cover types is OUR ASSUMPTION (documented in the
# report) — it must be calibrated against observed events before the numbers are trusted.
# ----------------------------------------------------------------------------------
HSG = "ABCD"
_WOODS_FAIR = (36, 60, 73, 79)
_BRUSH_FAIR = (35, 56, 70, 77)
_DESERT_SHRUB_FAIR = (55, 72, 81, 86)
_WOODS_GRASS_FAIR = (43, 65, 76, 82)
_RANGE_FAIR = (49, 69, 79, 84)
_SMALL_GRAIN_GOOD = (63, 75, 83, 87)
_URBAN_65 = (77, 85, 90, 92)          # residential 1/8 acre, 65 % impervious
_BARE = (77, 86, 91, 94)              # fallow, bare soil
_WATER = (100, 100, 100, 100)
_SNOW = (98, 98, 98, 98)

# MODIS MCD12Q1 LC_Type1 (IGBP) -> CN
CN_IGBP = {
    1: _WOODS_FAIR, 2: _WOODS_FAIR, 3: _WOODS_FAIR, 4: _WOODS_FAIR, 5: _WOODS_FAIR,
    6: _BRUSH_FAIR, 7: _DESERT_SHRUB_FAIR, 8: _WOODS_GRASS_FAIR, 9: _WOODS_GRASS_FAIR,
    10: _RANGE_FAIR, 11: _WATER, 12: _SMALL_GRAIN_GOOD, 13: _URBAN_65,
    14: tuple(int(round((a + b) / 2)) for a, b in zip(_SMALL_GRAIN_GOOD, _RANGE_FAIR)),
    15: _SNOW, 16: _BARE, 17: _WATER,
}
# KNTU Iran land cover V1 classes (1..13) -> CN
CN_KNTU = {
    1: _URBAN_65,                 # Urban
    2: _WATER,                    # Water
    3: _WATER,                    # Wetland (ponded: treated like water; assumption)
    4: (82, 88, 92, 94),          # Kalut (yardang, eroded bare)
    5: _WATER,                    # Marshland
    6: (82, 88, 92, 94),          # Salty land (crusted)
    7: (82, 88, 92, 94),          # Clay (bare clay, crusting)
    8: _WOODS_FAIR,               # Forest
    9: (88, 90, 92, 94),          # Outcrop (rock)
    10: _BARE,                    # Uncovered plain (sparse/bare)
    11: (45, 55, 65, 72),         # Sand (very high infiltration)
    12: _SMALL_GRAIN_GOOD,        # Farm land
    13: _RANGE_FAIR,              # Range land
}


def cn_table(d, nmax):
    t = np.full((nmax + 1, 4), 85.0, np.float32)
    for k, v in d.items():
        t[k] = v
    return t


USDA_CLASSES = ["sand", "loamy sand", "sandy loam", "loam", "silt loam", "silt", "sandy clay loam",
                "clay loam", "silty clay loam", "sandy clay", "silty clay", "clay"]
# NRCS rule of thumb (floodpath / NEH-630 ch.7): A sand..sandy loam; B loam, silt loam, silt;
# C sandy clay loam; D clay loam, silty clay loam, sandy clay, silty clay, clay.
_TEX_HSG = [0, 0, 0, 1, 1, 1, 2, 3, 3, 3, 3, 3]


def usda_texture_class(sand, clay):
    """USDA texture triangle -> index into USDA_CLASSES (sand, clay in %, vectorised)."""
    sand = np.asarray(sand, np.float32)
    clay = np.asarray(clay, np.float32)
    silt = np.clip(100.0 - sand - clay, 0, 100)
    out = np.full(sand.shape, 11, np.int8)            # default clay
    done = np.zeros(sand.shape, bool)

    def put(cond, k):
        nonlocal done
        m = cond & ~done
        out[m] = k
        done |= m
    put(silt + 1.5 * clay < 15, 0)
    put((silt + 1.5 * clay >= 15) & (silt + 2 * clay < 30), 1)
    put(((clay >= 7) & (clay < 20) & (sand > 52) & (silt + 2 * clay >= 30)) |
        ((clay < 7) & (silt < 50) & (silt + 2 * clay >= 30)), 2)
    put((clay >= 7) & (clay < 27) & (silt >= 28) & (silt < 50) & (sand <= 52), 3)
    put(((silt >= 50) & (clay >= 12) & (clay < 27)) | ((silt >= 50) & (silt < 80) & (clay < 12)), 4)
    put((silt >= 80) & (clay < 12), 5)
    put((clay >= 20) & (clay < 35) & (silt < 28) & (sand > 45), 6)
    put((clay >= 27) & (clay < 40) & (sand > 20) & (sand <= 45), 7)
    put((clay >= 27) & (clay < 40) & (sand <= 20), 8)
    put((clay >= 35) & (sand > 45), 9)
    put((clay >= 40) & (silt >= 40), 10)
    put((clay >= 40) & (sand <= 45) & (silt < 40), 11)
    return out


def usda_texture_hsg(sand, clay):
    """Texture -> hydrologic soil group index 0..3 (A..D)."""
    return np.asarray(_TEX_HSG, np.int8)[usda_texture_class(sand, clay)]


def scs_runoff_mm(P, CN, ia_ratio=0.2):
    """Event runoff depth Q [mm] for rainfall P [mm] (vectorised)."""
    S = 25400.0 / np.clip(CN, 1, 100) - 254.0
    Ia = ia_ratio * S
    P = np.asarray(P, np.float64)
    return np.where(P > Ia, (P - Ia) ** 2 / (P - Ia + S), 0.0)


def kirpich_tc_min(L_m, S):
    S = np.clip(S, 1e-3, None)
    return np.clip(0.0195 * np.power(np.clip(L_m, 1.0, None), 0.77) * np.power(S, -0.385), 10.0, None)
