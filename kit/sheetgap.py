"""kit sheetgap: a one-sheet check for a traced surface where the sheets touch.

A trace can change sheets only where its sheet touches the next one, or by crossing the gap between them. At
every dense point of a mesh the surface prediction is read along the mesh normal. The point passes when it lies
within on_run_vox of a run of the prediction no thicker than max_thick_vox, with at least gap_vox empty voxels on
both sides of that run. Neighboring points are linked only when their runs' centers lie within link_vox of each
other along the normal, so a chain of linked points cannot step from one isolated run onto the next. Small holes
enclosed by one component join it. A square inside one component is a window this check calls one sheet, and
its side in mm is the window picker's score.

What it cannot see: two sheets pressed into one run no thicker than one sheet. The planted-hop benchmark
(`python3 -m kit hopbench`, docs/tools/hopbench.md) measures how often that lets a hop through on PHerc0139.
Model output about geometry, never a reading.

    python3 -m kit.sheetgap certify SURF [--rule RULE.json] [--rows R0 R1 --cols C0 C1] [--out FILE]

SURF is a tifxyz folder in the frame of PHerc0139's scan 20250728140407 (m7 is read from the open bucket and
cached under work/hopbench/cache). Tests: tests/test_sheetgap.py (synthetic sheets, no network).
"""

import argparse
import collections
import json
import math
import sys
from pathlib import Path

from . import sheetrefs

# Status of a dense point
OK, OFF, THICK, GAP, MISSING, INVALID = 0, 1, 2, 3, 4, 5
STATUS = {OK: "ok", OFF: "off", THICK: "thick", GAP: "gap", MISSING: "missing", INVALID: "invalid"}

GAP_RULE = {
    "version": 1,
    "prediction": sheetrefs.PRED_M7,
    "threshold": 128,          # m7 is stored as 0 or 255
    "half_vox": 21,            # profile from -21 to +21 voxels along the normal (1.5 median pitches)
    "on_run_vox": 2,           # a point is seated when a run lies within 2 voxels of it
    "gap_vox": 2,              # empty voxels needed on each side of the run
    "max_thick_vox": 8,        # placeholder; the benchmark calibrates it on clean windows
    "link_vox": 2.0,           # largest step of the run center along the normal between neighbors
    "step_vox": 2.0,           # dense sampling of the mesh
    "hole_max_vox2": 400.0,    # an enclosed hole up to this area joins the component round it
    "voxel_um": 9.362,
}


def _np():
    return sheetrefs._np()


def rule_digest(rule):
    return sheetrefs.digest(rule)[:12]


class Field:
    """A binary view of a chunked prediction (anything with .chunks and .read(key) -> array or None, such as
    sheetrefs.ChunkReader), with an LRU of decoded chunks. Chunks past the array's shape read as empty; a chunk
    the reader reports missing is counted and marks the points that sample it."""

    def __init__(self, reader, threshold, cache_chunks=48):
        np = _np()
        self.reader, self.thr, self.cap = reader, threshold, int(cache_chunks)
        self.C = np.array(reader.chunks, dtype=np.int64)
        shape = (getattr(reader, "meta", None) or {}).get("shape")
        self.nchunks = None if shape is None else -(-np.array(shape, dtype=np.int64) // self.C)
        self._lru = collections.OrderedDict()
        self.missing_chunks = set()

    def chunk(self, key):
        if key in self._lru:
            self._lru.move_to_end(key)
            return self._lru[key]
        k = _np().array(key)
        if (k < 0).any() or (self.nchunks is not None and (k >= self.nchunks).any()):
            val = False
        else:
            arr = self.reader.read(key)
            if arr is None:
                self.missing_chunks.add(key)
                val = None
            else:
                val = arr >= self.thr
        self._lru[key] = val
        if len(self._lru) > self.cap:
            self._lru.popitem(last=False)
        return val

    def sample(self, Q):
        """Values (bool) and a missing flag at integer zyx voxels Q (m, 3)."""
        np = _np()
        keys = Q // self.C
        local = Q - keys * self.C
        vals = np.zeros(len(Q), bool)
        miss = np.zeros(len(Q), bool)
        uk, inv = np.unique(keys, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        order = np.argsort(inv, kind="stable")
        bounds = np.searchsorted(inv[order], np.arange(len(uk) + 1))
        for u in range(len(uk)):
            sel = order[bounds[u]:bounds[u + 1]]
            arr = self.chunk(tuple(int(x) for x in uk[u]))
            if arr is None:
                miss[sel] = True
            elif arr is not False:
                q = local[sel]
                vals[sel] = arr[q[:, 0], q[:, 1], q[:, 2]]
        return vals, miss


def profiles(field, P, N, half, batch=20000):
    """The binary prediction at P + t N for t = -half .. half (P, N in zyx), as (n, 2 half + 1), and whether
    any sample of a point fell in a missing chunk. Points are visited in chunk order for the cache."""
    np = _np()
    n = len(P)
    offs = np.arange(-half, half + 1, dtype=np.float64)
    B = np.zeros((n, len(offs)), bool)
    miss = np.zeros(n, bool)
    if n == 0:
        return B, miss
    key = np.floor(P / field.C).astype(np.int64)
    order = np.lexsort((key[:, 2], key[:, 1], key[:, 0]))
    for s in range(0, n, batch):
        idx = order[s:s + batch]
        Q = np.rint(P[idx, None, :] + offs[None, :, None] * N[idx, None, :]).astype(np.int64)
        v, m = field.sample(Q.reshape(-1, 3))
        B[idx] = v.reshape(len(idx), len(offs))
        miss[idx] = m.reshape(len(idx), len(offs)).any(1)
    return B, miss


def runs(B, on_run):
    """For each profile (n, L), the run of True nearest the center within on_run samples: (found, start, end,
    empty samples below the start, empty samples above the end). A gap that reaches the end of the profile
    counts its length; a run touching an end has a gap of 0 there."""
    np = _np()
    n, L = B.shape
    c = L // 2
    r = np.arange(n)
    idx = np.broadcast_to(np.arange(L), (n, L))
    j = np.full(n, -1, np.int64)
    for d in range(0, int(on_run) + 1):
        for k in ((c,) if d == 0 else (c - d, c + d)):
            if 0 <= k < L:
                hit = B[:, k] & (j < 0)
                j[hit] = k
    found = j >= 0
    jj = np.where(found, j, c)
    lastF = np.maximum.accumulate(np.where(~B, idx, -1), axis=1)
    nextF = np.minimum.accumulate(np.where(~B, idx, L)[:, ::-1], axis=1)[:, ::-1]
    lastT = np.maximum.accumulate(np.where(B, idx, -1), axis=1)
    nextT = np.minimum.accumulate(np.where(B, idx, L)[:, ::-1], axis=1)[:, ::-1]
    a = lastF[r, jj] + 1
    b = nextF[r, jj] - 1
    gap_lo = np.where(a >= 1, (a - 1) - lastT[r, np.clip(a - 1, 0, L - 1)], 0)
    gap_hi = np.where(b <= L - 2, nextT[r, np.clip(b + 1, 0, L - 1)] - (b + 1), 0)
    return found, a, b, gap_lo, gap_hi


def classify(B, miss, rule):
    """(status, run center offset along the normal in voxels, run thickness) per profile."""
    np = _np()
    L = B.shape[1]
    found, a, b, glo, ghi = runs(B, rule["on_run_vox"])
    thick = (b - a + 1).astype(np.int64)
    centre = (a + b) / 2.0 - L // 2
    st = np.full(len(B), OK, np.int8)
    g = int(rule["gap_vox"])
    st[(glo < g) | (ghi < g)] = GAP
    st[(thick > int(rule["max_thick_vox"])) | (a == 0) | (b == L - 1)] = THICK
    st[~found] = OFF
    st[miss] = MISSING
    return st, np.where(found, centre, np.nan), np.where(found, thick, 0)


class Cert:
    """The check on a dense grid: status, run center and thickness per point, the grid, its normals and step."""

    def __init__(self, status, centre, thick, xyz, normals, ok, step):
        self.status, self.centre, self.thick = status, centre, thick
        self.xyz, self.normals, self.ok, self.step = xyz, normals, ok, step

    def counts(self):
        np = _np()
        return {STATUS[k]: int((self.status == k).sum()) for k in STATUS}


def densify(xyz, valid, step_vox):
    """The mesh resampled to about step_vox: (xyz, valid, normals, ok, step in voxels)."""
    _, _, _, step = sheetrefs.grid_geometry(xyz, valid)
    k = max(1, int(math.ceil(step / float(step_vox)))) if math.isfinite(step) else 1
    up, uv, _ = sheetrefs.upsample(xyz, valid, k)
    nrm, _, ok, ustep = sheetrefs.grid_geometry(up, uv)
    return up, uv, nrm, ok, ustep


def check_dense(up, nrm, ok, ustep, field, rule):
    """Run the check on an already dense grid (xyz order, as tifxyz)."""
    np = _np()
    H, W = ok.shape
    status = np.full((H, W), INVALID, np.int8)
    centre = np.full((H, W), np.nan)
    thick = np.zeros((H, W), np.int64)
    if ok.any():
        P = up[ok][:, ::-1]
        N = nrm[ok][:, ::-1]
        B, miss = profiles(field, P, N, int(rule["half_vox"]))
        st, ce, th = classify(B, miss, rule)
        status[ok], centre[ok], thick[ok] = st, ce, th
    return Cert(status, centre, thick, up, nrm, ok, ustep)


def check(xyz, valid, field, rule):
    up, _, nrm, ok, ustep = densify(xyz, valid, rule["step_vox"])
    return check_dense(up, nrm, ok, ustep, field, rule)


def _edges(mask, H, W):
    """Index pairs of 8-neighbors that are both in mask (right, down, down-right, down-left)."""
    np = _np()
    out = []
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        r0, r1 = 0, H - dr
        c0, c1 = max(0, -dc), W - max(0, dc)
        a = mask[r0:r1, c0:c1] & mask[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
        rr, cc = np.nonzero(a)
        rr, cc = rr + r0, cc + c0
        out.append((rr * W + cc, (rr + dr) * W + (cc + dc)))
    return out


def components(cert, rule, mask=None, linked=True):
    """Component label per dense point (-1 where not counted). mask defaults to status OK. With linked, a pair
    of 8-neighbors joins only when the run centers, placed in 3D, lie within link_vox along the mean normal;
    without it (the seated baseline), any two neighbors in mask join. Enclosed holes up to hole_max_vox2 whose
    rim belongs to one component join it."""
    np = _np()
    from scipy import ndimage
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    H, W = cert.ok.shape
    m = (cert.status == OK) if mask is None else (mask & cert.ok)
    I, J = [], []
    if linked:
        Nf = cert.normals.reshape(-1, 3)
        C3f = (cert.xyz + np.where(np.isfinite(cert.centre), cert.centre, np.nan)[..., None] * cert.normals).reshape(-1, 3)
    for a, b in _edges(m, H, W):
        if linked and len(a):
            nm = Nf[a] + Nf[b]
            nn = np.linalg.norm(nm, axis=1)
            u = nm / np.where(nn > 0, nn, 1)[:, None]
            with np.errstate(invalid="ignore"):
                d = np.abs(np.einsum("ij,ij->i", C3f[a] - C3f[b], u))
            keep = (nn > 1.0) & np.isfinite(d) & (d <= float(rule["link_vox"]))
            a, b = a[keep], b[keep]
        I.append(a)
        J.append(b)
    I = np.concatenate(I) if I else np.zeros(0, np.int64)
    J = np.concatenate(J) if J else np.zeros(0, np.int64)
    g = coo_matrix((np.ones(len(I), np.int8), (I, J)), shape=(H * W, H * W))
    _, lab = connected_components(g, directed=False)
    lab = np.where(m.reshape(-1), lab, -1).reshape(H, W)
    # relabel to 0..k-1 by size, largest first
    vals, cnt = np.unique(lab[lab >= 0], return_counts=True)
    remap = np.full(H * W + 1, -1, np.int64)
    remap[vals[np.argsort(-cnt, kind="stable")]] = np.arange(len(vals))
    lab = np.where(lab >= 0, remap[np.where(lab >= 0, lab, H * W)], -1)
    # enclosed holes
    hmax = float(rule["hole_max_vox2"]) / max(cert.step, 1e-9) ** 2
    hl, nh = ndimage.label(lab < 0)
    if nh:
        sizes = np.bincount(hl.reshape(-1))
        border = np.unique(np.concatenate([hl[0], hl[-1], hl[:, 0], hl[:, -1]]))
        small = np.flatnonzero(sizes <= hmax)
        small = small[(small > 0) & ~np.isin(small, border)]
        objs = ndimage.find_objects(hl)
        st8 = np.ones((3, 3), bool)
        for h in small:
            sl = objs[h - 1]
            sl = tuple(slice(max(s.start - 1, 0), s.stop + 1) for s in sl)
            hm = hl[sl] == h
            rim = ndimage.binary_dilation(hm, st8) & ~hm
            ids = np.unique(lab[sl][rim])
            if len(ids) == 1 and ids[0] >= 0:
                sub = lab[sl]
                sub[hm] = ids[0]
    return lab


def largest_square(mask):
    """(side in cells, row, col) of the largest all-True square, by bisection on a summed-area table."""
    np = _np()
    H, W = mask.shape
    S = np.zeros((H + 1, W + 1), np.int64)
    S[1:, 1:] = np.cumsum(np.cumsum(mask, 0), 1)

    def where(s):
        if s <= 0 or s > min(H, W):
            return None
        t = S[s:, s:] - S[:-s, s:] - S[s:, :-s] + S[:-s, :-s]
        hit = np.argwhere(t == s * s)
        return (int(hit[0][0]), int(hit[0][1])) if len(hit) else None

    lo, hi, at = 0, min(H, W), (None, None)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        w = where(mid)
        if w is None:
            hi = mid - 1
        else:
            lo, at = mid, w
    return lo, at[0], at[1]


def best_square(lab, top=4):
    """The largest square inside one component, among the top components by size: (side, row, col, label)."""
    np = _np()
    best = (0, None, None, -1)
    for k in range(min(top, int(lab.max()) + 1 if lab.size else 0)):
        m = lab == k
        if not m.any():
            continue
        rr, cc = np.nonzero(m)
        r0, c0 = rr.min(), cc.min()
        sub = m[r0:rr.max() + 1, c0:cc.max() + 1]
        if min(sub.shape) <= best[0]:
            continue
        s, r, c = largest_square(sub)
        if s > best[0]:
            best = (s, int(r + r0), int(c + c0), k)
    return best


def summary(cert, lab, rule):
    side, r, c, k = best_square(lab)
    mm = side * cert.step * rule["voxel_um"] / 1000.0
    ok = int(cert.ok.sum())
    return {"points": ok, "status": cert.counts(), "ok_share": sheetrefs._r((cert.status == OK).sum() / max(ok, 1)),
            "components": int(lab.max()) + 1 if lab.size else 0, "step_vox": sheetrefs._r(cert.step, 3),
            "square_cells": int(side), "square_mm": sheetrefs._r(mm, 2), "square_at": [r, c], "square_label": k}


def plant(up, ok, refB, mode="band", contact_vox=4.0, ramp_half_vox=8.0, min_part_vox2=1600.0, step=None,
          workers=2):
    """A copy of a dense window of winding A that hops onto winding B. Every point is moved to B along B's
    normal (p - s n_B) by a weight w from 0 (on A) to 1 (on B). mode band: the window minus the contact zone
    (|s| <= contact_vox) splits into parts; the largest stays on A, the second largest goes to B, and w in the
    contact zone blends by distance to the two, so the copy never crosses a gap. mode ramp: w ramps along the
    rows over 2 ramp_half_vox through the contact point nearest the window center, so away from that point
    the copy crosses the gap between the sheets. Returns (xyz, valid, w, s) or None when the window has no
    such split. Points with no match on B are dropped."""
    np = _np()
    from scipy import ndimage
    H, W = ok.shape
    P = up.reshape(-1, 3)
    s = np.full(H * W, np.nan)
    nB = np.zeros((H * W, 3))
    inside = np.zeros(H * W, bool)
    sel = np.flatnonzero(ok.reshape(-1))
    if len(sel):
        ss, ins, _, nn = sheetrefs.match(P[sel], refB, workers=workers)
        s[sel], inside[sel], nB[sel] = ss, ins & np.isfinite(ss), nn
    s, inside, nB = s.reshape(H, W), inside.reshape(H, W), nB.reshape(H, W, 3)
    valid = ok & inside
    K = valid & (np.abs(s) <= contact_vox)
    if not K.any():
        return None
    step = step or sheetrefs.grid_geometry(up, ok)[3]
    if mode == "band":
        lab, n = ndimage.label(valid & ~K)
        if n < 2:
            return None
        sizes = np.bincount(lab.reshape(-1))[1:]
        order = np.argsort(-sizes)
        if sizes[order[1]] * step * step < min_part_vox2:
            return None
        RA, RB = lab == order[0] + 1, lab == order[1] + 1
        dA = ndimage.distance_transform_edt(~RA)
        dB = ndimage.distance_transform_edt(~RB)
        w = np.zeros((H, W))
        w[RB] = 1.0
        w[K] = (dA / np.maximum(dA + dB, 1e-9))[K]
    elif mode == "ramp":
        rr, cc = np.nonzero(K)
        i = int(np.argmin((rr - H / 2.0) ** 2 + (cc - W / 2.0) ** 2))
        r0 = rr[i]
        h = max(ramp_half_vox / step, 1.0)
        w = np.clip((np.arange(H)[:, None] - r0) / (2 * h) + 0.5, 0, 1) * np.ones((1, W))
    else:
        raise ValueError(f"unknown plant mode {mode}")
    out = up - (w * np.nan_to_num(s))[..., None] * nB
    out[~valid] = np.nan
    return out, valid, w, s


def bridges(lab, w, s, valid, far_vox=6.0, min_side_cells=1):
    """Whether one component holds at least min_side_cells points clearly on A (w = 0, B more than far_vox
    away) and as many clearly on B (w = 1, A more than far_vox away)."""
    np = _np()
    far = valid & (np.abs(np.nan_to_num(s)) > far_vox)
    A = far & (w <= 0) & (lab >= 0)
    B = far & (w >= 1) & (lab >= 0)
    if not A.any() or not B.any():
        return False, 0, 0
    ca = np.bincount(lab[A], minlength=int(lab.max()) + 1)
    cb = np.bincount(lab[B], minlength=int(lab.max()) + 1)
    both = (ca >= min_side_cells) & (cb >= min_side_cells)
    return bool(both.any()), int(A.sum()), int(B.sum())


def _reader(rule, cache_dir):
    return sheetrefs.ChunkReader(rule["prediction"], cache_dir)


def run_certify(args):
    np = _np()
    rule = dict(GAP_RULE)
    if args.rule:
        rule.update(json.loads(Path(args.rule).read_text()))
    xyz, valid, _ = sheetrefs.read_tifxyz(args.surface)
    if args.rows:
        xyz, valid = xyz[args.rows[0]:args.rows[1]], valid[args.rows[0]:args.rows[1]]
    if args.cols:
        xyz, valid = xyz[:, args.cols[0]:args.cols[1]], valid[:, args.cols[0]:args.cols[1]]
    field = Field(_reader(rule, args.cache), rule["threshold"])
    cert = check(xyz, valid, field, rule)
    lab = components(cert, rule)
    rep = {"surface": str(args.surface), "rule": rule, "rule_digest": rule_digest(rule),
           "missing_chunks": len(field.missing_chunks), **summary(cert, lab, rule)}
    text = json.dumps(rep, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m kit.sheetgap", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("certify", help="one-sheet windows of a tifxyz trace on m7")
    c.add_argument("surface")
    c.add_argument("--rule")
    c.add_argument("--rows", type=int, nargs=2)
    c.add_argument("--cols", type=int, nargs=2)
    c.add_argument("--cache", default=str(sheetrefs.DEFAULT_CACHE))
    c.add_argument("--out")
    args = ap.parse_args(argv)
    return run_certify(args)


if __name__ == "__main__":
    sys.exit(main())
