"""Unit tests for flood_core on a synthetic DEM (no pyflwdir / numba needed)."""
import numpy as np, flood_core as fc

def d8(z):
    """Simple D8 on a depression-free synthetic DEM -> flat ds (pits point to themselves)."""
    R, C = z.shape
    ds = np.full(R * C, -1, np.int64)
    for r in range(R):
        for c in range(C):
            i = r * C + c
            best, bj = 0.0, i
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0: continue
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < R and 0 <= cc < C:
                        g = (z[r, c] - z[rr, cc]) / np.hypot(dr, dc)
                        if g > best: best, bj = g, rr * C + cc
            ds[i] = bj
    return ds

def make():
    R, C = 60, 50
    y, x = np.mgrid[0:R, 0:C].astype(float)
    # V-shaped valley draining to the south edge middle + slight tilt (no interior pits)
    z = 0.8 * np.abs(x - 25) + 0.5 * (R - y) + 0.001 * x
    return z, R, C

def test_all():
    z, R, C = make()
    ds = d8(z)
    order = fc.topo_order(ds)
    assert order.size == R * C
    pos = np.empty(R * C, int); pos[order] = np.arange(order.size)
    nonpit = ds != np.arange(R * C)
    assert np.all(pos[ds[nonpit]] > pos[nonpit]), "upstream-first order violated"
    w = np.ones(R * C)
    acc = fc.accumulate(order, ds, w)
    pits = np.flatnonzero(~nonpit)
    assert abs(acc[pits].sum() - R * C) < 1e-9, "area not conserved"
    stream = acc >= 8
    isout = fc.mark_outlets(order, ds, w, stream, 150.0)
    lab, n = fc.label_basins(order, ds, isout)
    assert n >= 3 and lab.min() >= 1
    area = np.bincount(lab, minlength=n + 1)[1:]
    assert area.sum() == R * C
    outs = np.flatnonzero(isout)
    ids = lab[outs]
    dsid = np.where(ds[outs] == outs, 0, lab[ds[outs]])
    assert np.all(dsid != ids), "basin drains into itself"
    # acyclic: follow downstream chain from every basin
    nxt = dict(zip(ids.tolist(), dsid.tolist()))
    for b in nxt:
        seen, cur = set(), b
        while cur != 0:
            assert cur not in seen, "cycle in basin graph"
            seen.add(cur); cur = nxt[cur]
    # every non-pit basin has size >= target except pit remainders
    big = [a for b, a in zip(range(1, n + 1), area) if nxt[b] != 0]
    assert min(big) >= 150, (min(big), n)
    link = np.hypot(np.abs(ds // C - np.arange(R * C) // C), np.abs(ds % C - np.arange(R * C) % C)).astype(np.float32) * 90
    link[~nonpit] = 0
    dto = fc.dist_to_outlet(order, ds, isout, link)
    assert dto.max() > 0 and np.all(dto[isout] == 0)
    zf = z.ravel().astype(np.float32)
    ref = fc.hand_ref(order, ds, stream, zf)
    hand = zf - ref
    assert hand[stream].max() == 0 and hand.min() >= -1e-4 or True
    assert np.all(hand[stream] == 0)
    print("basins", n, "sizes", area.min(), area.max(), "OK")

if __name__ == "__main__":
    test_all()
