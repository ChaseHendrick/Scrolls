"""The PHerc0139 hand-traced windings as references for `kit hopbench`: download, manifest, point matching.

The published windings w023 to w040 of PHerc0139 in the frame of volume 20250728140407 (9.362 um), read from the
open-data bucket, are put in normal order by the offsets where they overlap. The manifest records each winding's
chain neighbors, local pitch, near-duplicate parts (dropped or masked as no-reference) and contact zones (another
winding within 8 voxels). `match` measures a point's signed offset from a winding along its normal. Only these
18 windings are downloaded: the benchmark runs on them alone, and the later windings of the stack are left out
on purpose so they stay unused as held-out data.

  python3 -m kit hopbench refs        # download and build, about 5 minutes and 40 MB

Geometry only, from published hand traces; nothing here is a reading. Needs numpy, scipy and tifffile; numcodecs
to read the blosc chunks of a prediction.
"""

import collections
import concurrent.futures
import hashlib
import html
import json
import math
import re
import threading
import time
import urllib.parse
from pathlib import Path

SAMPLE = "PHerc0139"
VOLUME = "20250728140407"
VOXEL_UM = 9.362
VOXEL_TAG = "9.362um"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
PRED_DIR = f"{SAMPLE}/representations/predictions/surfaces"
PRED_M7 = f"{PRED_DIR}/20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr"
PRED_RECTO = f"{PRED_DIR}/20250728140407-surface-20250701154204-surface-recto-090.zarr"
PRED_SOURCES = {"m7": PRED_M7, "recto090": PRED_RECTO}
M7_LEVEL0 = {"shape": [20974, 6621, 6621], "dtype": "uint8"}   # m7's level 0 (and recto-090's)
DEFAULT_ROOT = Path("work") / "hopbench"
DEFAULT_REFS = DEFAULT_ROOT / "refs" / f"{SAMPLE}-{VOLUME}"
DEFAULT_CACHE = DEFAULT_ROOT / "cache"
MESH_FILES = ("x.tif", "y.tif", "z.tif", "meta.json")
TUNE = [f"w{n:03d}" for n in range(23, 41)]
BLOCK = 128                 # voxels: coarse occupancy blocks for picking which references can be near a point
NOREF, DROPPED = -1, -2     # reference vertex labels besides a winding id

# The reference settings: every manifest records their digest, so a change is a new benchmark.
RULE = {
    "version": 2,
    "frame": {"sample": SAMPLE, "volume": VOLUME, "voxel_um": VOXEL_UM},
    "distance": {
        "primary_vox": 4.0,            # the distance a match counts at in self-overlap shares
        "upsample": 2,                 # reference grids made 2x denser (bilinear) before point-to-plane matching
        "footprint_steps": 1.5,        # inside a footprint: lateral offset within 1.5 dense grid steps
        "neighbour_max_vox": 64.0,     # farthest normal offset a match counts at
        "blend_vertices": 4,           # offset blended over this many nearest vertices of one part
    },
    "references": {
        "coincide_vox": 2.0,           # duplicate test distance
        "duplicate_share": 0.25,       # pairs with this share of either mesh within 2 voxels are one sheet
        "strip_vox": 4.0,              # a duplicate's vertices this close to the kept mesh are dropped
        "part_spread_vox": 4.0,        # a duplicate's departing part is one sheet when its offsets cluster this tight
        "part_consistent_share": 0.6,  # ... over this share of it
        "part_min_offset_vox": 6.0,    # ... and it sits at least this far from the kept mesh
        "part_min_vertices": 200,
        "contact_vox": 8.0,            # contact zone: another winding within 8 voxels
        "gap_factor": 1.5,             # a gap: chain step, or next sheet not an adjacent winding, over 1.5 pitches
        "partial_inside_share": 0.8,   # partial: a chain neighbor projects under 80 % inside it
        "min_pair_matches": 500,
        "self_far_cells": 4,           # two vertices of one mesh this many native cells apart are different parts
        "match_k": 8,                  # nearest dense vertices looked at for another part of the same mesh
    },
    "split": {"tune": TUNE, "note": "the benchmark's windings; later windings are left out as held-out data"},
}


def rule_digest(rule=None):
    return digest(RULE if rule is None else rule)


class BenchError(ValueError):
    """A problem the caller can fix: missing references, a changed rule, an unreadable surface."""


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise BenchError("kit hopbench needs numpy and scipy: pip install numpy scipy tifffile numcodecs") from exc
    return numpy


def _kdtree():
    try:
        from scipy.spatial import cKDTree
    except ImportError as exc:
        raise BenchError("kit hopbench needs scipy (cKDTree): pip install scipy") from exc
    return cKDTree


def _r(x, n=4):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else (x if math.isinf(x) else round(x, n))


def _say(log, msg):
    if log:
        log(msg)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def grid_geometry(xyz, valid):
    """(normals (H, W, 3), area per vertex in voxels^2, ok, median edge length) of a grid: central differences
    where both neighbours are valid, else one-sided (central where it can); ok = valid with a finite normal."""
    np = _np()
    P = np.where(valid[..., None], xyz, np.nan)
    with np.errstate(invalid="ignore"):
        def grad(axis):
            n = P.shape[axis]
            fwd = np.full_like(P, np.nan)
            bwd = np.full_like(P, np.nan)
            sl = [slice(None)] * 3
            lo, hi = list(sl), list(sl)
            lo[axis], hi[axis] = slice(0, n - 1), slice(1, n)
            fwd[tuple(lo)] = P[tuple(hi)] - P[tuple(lo)]
            bwd[tuple(hi)] = P[tuple(hi)] - P[tuple(lo)]
            f_ok = np.isfinite(fwd).all(-1)
            b_ok = np.isfinite(bwd).all(-1)
            return np.where((f_ok & b_ok)[..., None], 0.5 * (fwd + bwd), np.where(f_ok[..., None], fwd, bwd))

        tu, tv = grad(1), grad(0)
        n = np.cross(tu, tv)
        nn = np.linalg.norm(n, axis=-1)
        ok = valid & np.isfinite(nn) & (nn > 1e-9)
        normals = np.where(ok[..., None], n / np.where(ok, nn, 1.0)[..., None], np.nan)
        area = np.where(ok, nn, 0.0)
        edges = [np.linalg.norm(np.diff(P, axis=a), axis=-1) for a in (0, 1)]
    el = np.concatenate([e[np.isfinite(e)] for e in edges])
    return normals, area, ok, (float(np.median(el)) if el.size else float("nan"))


def upsample(xyz, valid, k):
    """A k-times denser grid by bilinear interpolation: rows i + a/k, cols j + b/k. A new vertex is valid when
    every corner it uses is; original vertices are kept exactly. Returns (xyz, valid, src) where src is the flat
    index of the top-left native vertex each one came from."""
    np = _np()
    H, W = valid.shape
    idx = np.arange(H * W).reshape(H, W)
    if k <= 1:
        return xyz, valid, idx
    Hu, Wu = (H - 1) * k + 1, (W - 1) * k + 1
    out = np.full((Hu, Wu, 3), np.nan)
    ov = np.zeros((Hu, Wu), bool)
    src = np.zeros((Hu, Wu), np.int64)
    for a in range(k):
        for b in range(k):
            h, w = (H if a == 0 else H - 1), (W if b == 0 else W - 1)
            if h <= 0 or w <= 0:
                continue
            fa, fb = a / k, b / k
            acc = (1 - fa) * (1 - fb) * xyz[:h, :w]
            v = valid[:h, :w].copy()
            if a:
                acc = acc + fa * (1 - fb) * xyz[1:h + 1, :w]
                v &= valid[1:h + 1, :w]
            if b:
                acc = acc + (1 - fa) * fb * xyz[:h, 1:w + 1]
                v &= valid[:h, 1:w + 1]
            if a and b:
                acc = acc + fa * fb * xyz[1:h + 1, 1:w + 1]
                v &= valid[1:h + 1, 1:w + 1]
            out[a::k, b::k] = acc
            ov[a::k, b::k] = v
            src[a::k, b::k] = idx[:h, :w]
    out[~ov] = np.nan
    return out, ov, src


def block_keys(points):
    """Codes of the BLOCK^3 boxes holding (x, y, z) points."""
    np = _np()
    b = np.floor(np.asarray(points)[:, ::-1] / BLOCK).astype(np.int64)
    return (b[:, 0] << 20) | (b[:, 1] << 10) | b[:, 2]


def dilate_keys(keys):
    np = _np()
    u = np.unique(keys)
    z, y, x = u >> 20, (u >> 10) & 1023, u & 1023
    out = [((z + dz) << 20) | ((y + dy) << 10) | (x + dx)
           for dz in (-1, 0, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    return np.unique(np.concatenate(out))


class Ref:
    """One reference (or candidate) surface: its native grid, per-vertex labels and attributes, and its dense
    scoring points with a KD-tree built on first use."""

    def __init__(self, name, gid, xyz, valid, rule=None, label=None):
        np = _np()
        rule = rule or RULE
        D = rule["distance"]
        self.name, self.gid = name, gid
        self.xyz, self.valid = xyz, valid
        self.normals, self.area, self.ok, self.step = grid_geometry(xyz, valid)
        self.label = (np.where(valid, gid, DROPPED).astype(np.int32) if label is None
                      else np.asarray(label, dtype=np.int32))
        self.attrs = {}
        self.k, self.foot_steps, self.neigh = int(D["upsample"]), float(D["footprint_steps"]), float(D["neighbour_max_vox"])
        self.match_k, self.far_cells = int(rule["references"]["match_k"]), int(rule["references"]["self_far_cells"])
        self.blend = int(D["blend_vertices"])
        self._pts = self._tree = self._keys = None

    def reset(self):
        self._pts = self._tree = self._keys = None

    def usable(self):
        """Native vertices that take part in matching: a normal, and not dropped as a duplicate."""
        return self.ok & (self.label != DROPPED)

    def labelled(self):
        return self.ok & (self.label == self.gid)

    def scoring(self):
        """(points, normals, native source index, dense step) of the dense grid."""
        if self._pts is None:
            keep = self.valid & (self.label != DROPPED)
            up, uv, src = upsample(self.xyz, keep, self.k)
            un, _, uok, ustep = grid_geometry(up, uv)
            if not math.isfinite(ustep):
                ustep = self.step / max(self.k, 1) if math.isfinite(self.step) else 1.0
            self._pts = (up[uok], un[uok], src[uok], ustep)
        return self._pts

    def footprint(self):
        return self.foot_steps * self.scoring()[3]

    def tree(self):
        if self._tree is None:
            self._tree = _kdtree()(self.scoring()[0])
        return self._tree

    def keys(self):
        if self._keys is None:
            u = self.usable()
            self._keys = dilate_keys(block_keys(self.xyz[u])) if u.any() else _np().zeros(0, _np().int64)
        return self._keys


def match(P, ref, workers=2, dist=False):
    """Each point against one reference: the signed offset s along the reference normal at its nearest dense
    vertex (point to plane, blended over the nearest blend_vertices of that part of the mesh), whether it
    projects inside the footprint (lateral offset within the footprint and |s| within neighbour_max_vox), that
    vertex's native index, and its normal. With dist (off by default, 14 October 2026), also the straight-line
    distance from each point to that dense vertex (NaN where none was found), as a fifth element."""
    np = _np()
    dist_out = bool(dist)
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
    pts, nrm, src, _ = ref.scoring()
    n = len(P)
    if n == 0 or len(pts) == 0:
        out = (np.full(n, np.nan), np.zeros(n, bool), np.zeros(n, np.int64), np.zeros((n, 3)))
        return out + (np.full(n, np.nan),) if dist_out else out
    foot = ref.footprint()
    upper = math.hypot(ref.neigh, foot) + 1e-6
    k = max(1, int(ref.match_k))
    dist, j = ref.tree().query(P, k=k, distance_upper_bound=upper, workers=workers)
    if k == 1:
        dist, j = dist[:, None], j[:, None]
    found = np.isfinite(dist)
    jj = np.where(found, j, 0)
    v = P[:, None, :] - pts[jj]
    s = np.einsum("ikj,ikj->ik", v, nrm[jj])
    lat2 = np.einsum("ikj,ikj->ik", v, v) - s * s
    inside = found & (lat2 <= foot * foot) & (np.abs(s) <= ref.neigh)
    pick = np.zeros(n, np.int64)
    if k > 1:
        # Where a mesh overlaps itself (a winding traced past its seam, a fold), the nearest dense vertex can
        # belong to the other part. Among the k nearest, a vertex of another part of the mesh (more than
        # self_far_cells native cells from the nearest) that lies inside the footprint and nearer along its
        # normal is taken instead: the distance is to the nearer part, not to the nearer vertex.
        W = ref.valid.shape[1]
        r0, c0 = np.divmod(src[jj[:, :1]], W)
        rr, cc = np.divmod(src[jj], W)
        far = np.maximum(np.abs(rr - r0), np.abs(cc - c0)) > ref.far_cells
        alt = inside & far & (np.abs(s) < np.abs(s[:, :1]))
        score = np.where(alt, np.abs(s), np.inf)
        best = np.argmin(score, axis=1)
        pick = np.where(np.isfinite(score[np.arange(n), best]), best, 0)
    ar = np.arange(n)
    jp = jj[ar, pick]
    sp = s[ar, pick]
    fp = found[ar, pick]
    if k > 1 and ref.blend > 1:
        # the offset is blended over the `blend` nearest vertices of the chosen part (inverse square distance),
        # which follows the surface between vertices better than the nearest vertex's plane alone
        W = ref.valid.shape[1]
        rr, cc = np.divmod(src[jj], W)
        rp, cp = np.divmod(src[jp], W)
        same = found & (np.maximum(np.abs(rr - rp[:, None]), np.abs(cc - cp[:, None])) <= ref.far_cells)
        same &= np.cumsum(same, axis=1) <= ref.blend
        w = np.where(same, 1.0 / np.maximum(np.where(found, dist, 1.0), 1e-6) ** 2, 0.0)
        tot = w.sum(1)
        sb_ = np.where(tot > 0, (w * np.where(found, s, 0.0)).sum(1) / np.where(tot > 0, tot, 1.0), sp)
        sp = np.where(fp, sb_, sp)
    out = (np.where(fp, sp, np.nan), inside[ar, pick], src[jp], nrm[jp])
    return out + (np.where(fp, dist[ar, pick], np.nan),) if dist_out else out


def _list(prefix, opener=None):
    """(sub-prefixes, keys) one level under a bucket prefix, through kit/s3retry.py."""
    from . import s3retry
    dirs, keys, token, seen = [], [], None, set()
    while True:
        url = (f"{BUCKET}/?list-type=2&max-keys=1000&delimiter=%2F&prefix={urllib.parse.quote(prefix)}"
               + (f"&continuation-token={urllib.parse.quote(token, safe='')}" if token else ""))
        with s3retry.open_url(url, opener, 60) as resp:
            xml = resp.read().decode("utf-8", "replace")
        dirs += [html.unescape(p) for p in re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix>", xml)]
        keys += [html.unescape(k) for k in re.findall(r"<Key>([^<]+)</Key>", xml)]
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
        if not m:
            return dirs, keys
        token = html.unescape(m.group(1))
        if token in seen:
            raise BenchError("bucket listing repeated a continuation token")
        seen.add(token)


def find_meshes(opener=None, sample=SAMPLE, volume=VOLUME, voxel_tag=VOXEL_TAG):
    """The winding folders of a sample's segments and, for each, the bucket prefix of its tifxyz in the given
    volume's frame. Returns (found [{name, folder, prefix}], skipped [{folder, reason}])."""
    dirs, _ = _list(f"{sample}/segments/", opener)
    found, skipped, used = [], [], set()
    for d in sorted(dirs):
        folder = d.rstrip("/").rsplit("/", 1)[-1]
        m = re.search(r"-(w\d{3})_", folder)
        if not m:
            skipped.append({"folder": folder, "reason": "not a winding (no wNNN in its name)"})
            continue
        sub, _ = _list(d + "mesh/", opener)
        hit = [s for s in sub if s.rstrip("/").endswith(f"-on-{volume}-{voxel_tag}.tifxyz")]
        if not hit:
            skipped.append({"folder": folder, "reason": f"no tifxyz in the frame of {volume}"})
            continue
        name = m.group(1)
        if name in used:
            name = f"{name}-{folder.split('-')[0]}"
        used.add(name)
        found.append({"name": name, "folder": folder, "prefix": hit[0].rstrip("/")})
    return found, skipped


def _pair_stats(A, B, sel, m, labelled_only=False):
    np = _np()
    s, inside, src, nb = m
    nA = int(A.labelled().sum() if labelled_only else A.ok.sum())
    if labelled_only:
        keep = (A.label[sel] == A.gid) & (B.label.ravel()[src] == B.gid)
        inside = inside & keep
    si = s[inside]
    dots = np.einsum("ij,ij->i", A.normals[sel][inside], nb[inside])
    out = {"n": nA, "matched": int(inside.sum())}
    if nA:
        out.update({"inside": float(inside.sum() / nA), "cov2": float((np.abs(si) <= 2).sum() / nA),
                    "cov4": float((np.abs(si) <= 4).sum() / nA), "cov8": float((np.abs(si) <= 8).sum() / nA)})
    if si.size:
        out["median_s"] = float(np.median(si))
        out["orient"] = 1 if float(np.median(dots)) >= 0 else -1
    return out


def _all_pairs(refs, log, workers, labelled_only=False, per_vertex=None):
    """Directed pair statistics A -> B (A's vertices against B's tree) for every pair whose blocks meet. When
    per_vertex is given, per_vertex(A, B, sel, m) is called for each pair as well."""
    np = _np()
    stats = {}
    for B in refs:
        if not B.usable().any():
            continue
        dil = B.keys()
        for A in refs:
            if A is B:
                continue
            base = A.labelled() if labelled_only else A.usable()
            if not base.any():
                continue
            sel = base.copy()
            sel[base] = np.isin(block_keys(A.xyz[base]), dil)
            if not sel.any():
                continue
            m = match(A.xyz[sel], B, workers)
            stats[(A.gid, B.gid)] = _pair_stats(A, B, sel, m, labelled_only)
            if per_vertex is not None:
                per_vertex(A, B, sel, m)
        _say(log, f"sheetrefs:   pairs against {B.name} done")
    return stats


def _orient(refs, stats, min_pairs):
    """+1/-1 per reference so that normals agree across overlapping meshes (spanning tree from the largest), then
    flipped as a whole so they point away from the slice centroids (outward) on average."""
    np = _np()
    n = len(refs)
    adj = collections.defaultdict(list)
    for (a, b), st in stats.items():
        if st.get("matched", 0) >= min_pairs and "orient" in st:
            adj[a].append((st["matched"], b, st["orient"]))
            adj[b].append((st["matched"], a, st["orient"]))
    orient = [0] * n
    order = sorted(range(n), key=lambda i: -float(refs[i].area.sum()))
    for root in order:
        if orient[root]:
            continue
        orient[root] = 1
        queue = [root]
        while queue:
            cur = queue.pop(0)
            for _, nb, sg in sorted(adj[cur], reverse=True):
                if not orient[nb]:
                    orient[nb] = orient[cur] * sg
                    queue.append(nb)
    conflicts = sum(1 for (a, b), st in stats.items()
                    if st.get("matched", 0) >= min_pairs and "orient" in st and orient[a] * orient[b] != st["orient"])
    pts = np.concatenate([r.xyz[r.ok] for r in refs if r.ok.any()])
    slab = np.floor(pts[:, 2] / 256).astype(np.int64)
    u, inv = np.unique(slab, return_inverse=True)
    cx = np.bincount(inv, pts[:, 0]) / np.bincount(inv)
    cy = np.bincount(inv, pts[:, 1]) / np.bincount(inv)
    vote = 0.0
    for r, o in zip(refs, orient):
        if not r.ok.any():
            continue
        p, nr = r.xyz[r.ok], r.normals[r.ok]
        k = np.searchsorted(u, np.floor(p[:, 2] / 256).astype(np.int64))
        rad = np.stack([p[:, 0] - cx[k], p[:, 1] - cy[k]], 1)
        rad /= np.maximum(np.linalg.norm(rad, axis=1, keepdims=True), 1e-9)
        vote += o * float(np.mean(nr[:, 0] * rad[:, 0] + nr[:, 1] * rad[:, 1]))
    if vote < 0:
        orient = [-o for o in orient]
    return orient, conflicts


def _resolve_duplicates(refs, stats, orient, R, log, workers):
    """Group near-duplicate meshes, choose which one keeps the shared sheet, drop the copy's coincident vertices
    and label or mask what departs from it. Returns the group records."""
    np = _np()
    by_gid = {r.gid: r for r in refs}
    parent = {r.gid: r.gid for r in refs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (a, b), st in stats.items():
        back = stats.get((b, a), {})
        if max(st.get("cov2", 0), back.get("cov2", 0)) >= R["duplicate_share"]:
            parent[find(a)] = find(b)
    groups = collections.defaultdict(list)
    for g in parent:
        groups[find(g)].append(g)
    records = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda g: -float(by_gid[g].area.sum()))
        primary = _choose_primary([by_gid[g] for g in members], refs, stats, R, workers)
        P = primary
        rec = {"members": [by_gid[g].name for g in members], "kept": P.name,
               "pairs": {f"{by_gid[a].name}->{by_gid[b].name}": _r(stats.get((a, b), {}).get("cov2"))
                         for a in members for b in members if a != b}, "copies": []}
        for g in members:
            S = by_gid[g]
            if S is P:
                continue
            rec["copies"].append(_split_copy(P, S, orient[P.gid], R, workers))
        records.append(rec)
        _say(log, f"sheetrefs: duplicates {rec['members']}: kept {P.name}; "
                  + "; ".join(f"{c['name']} {c['outcome']}" for c in rec["copies"]))
    return records


def _choose_primary(members, refs, stats, R, workers):
    """The member that stays on one sheet where the members disagree: its offset to the nearest other winding is
    the same where it departs from the others as where it coincides with them. Ties go to the larger area."""
    np = _np()
    gids = {m.gid for m in members}
    scores = []
    for M in members:
        others = [o for o in members if o is not M]
        nbrs = sorted(((st.get("matched", 0), b) for (a, b), st in stats.items()
                       if a == M.gid and b not in gids), reverse=True)
        if not nbrs or not others:
            scores.append((math.inf, M))
            continue
        N = next(r for r in refs if r.gid == nbrs[0][1])
        sel = M.usable()
        P = M.xyz[sel]
        dep = np.ones(len(P), bool)
        for O in others:
            s, ins, _, _ = match(P, O, workers)
            dep &= ~(ins & (np.abs(s) <= R["strip_vox"]))
        s, ins, _, _ = match(P, N, workers)
        a, b = s[ins & dep], s[ins & ~dep]
        if a.size < R["part_min_vertices"] or b.size < R["part_min_vertices"]:
            scores.append((math.inf, M))
            continue
        scores.append((abs(float(np.median(a)) - float(np.median(b))), M))
    best = min(s for s, _ in scores)
    if not math.isfinite(best):
        return members[0]
    return next(M for s, M in scores if s == best)


def _split_copy(P, S, orient_p, R, workers):
    """S's vertices within strip_vox of P are dropped. What departs is kept as S's own partial sheet when its
    offsets from P cluster at one distance (a copy moved one winding, like w046), else it and the part of P under
    it become no-reference masks (an ambiguous pair, like w041/w042)."""
    np = _np()
    sel = S.usable()
    s, ins, _, _ = match(S.xyz[sel], P, workers)
    coinc = ins & (np.abs(s) <= R["strip_vox"])
    dep = ~coinc
    dep_in = dep & ins
    o = orient_p * s
    lab = S.label.copy()
    flat = np.flatnonzero(sel.ravel())
    lab.ravel()[flat[coinc]] = DROPPED
    out = {"name": S.name, "dropped_share": _r(coinc.mean()), "departing_vertices": int(dep.sum())}
    if dep.sum() < R["part_min_vertices"]:
        lab.ravel()[flat[dep]] = NOREF
        out["outcome"] = "a copy: coincident part dropped, the rest masked"
        S.label = lab
        S.reset()
        return out
    med = float(np.median(o[dep_in])) if dep_in.any() else float("nan")
    near = dep_in & (np.abs(o - med) <= R["part_spread_vox"])
    share = float(near.sum() / max(dep_in.sum(), 1))
    out.update({"departing_median_offset_vox": _r(med, 2), "departing_clustered_share": _r(share)})
    consistent = dep_in.any() and share >= R["part_consistent_share"] and abs(med) >= R["part_min_offset_vox"]
    if consistent:
        keep = near | (dep & ~ins)
        lab.ravel()[flat[dep & ~keep]] = NOREF
        out["outcome"] = "moved part kept as its own partial winding"
        out["kept_part_share"] = _r(keep.sum() / max(sel.sum(), 1))
        S.label = lab
        S.reset()
        return out
    lab.ravel()[flat[dep]] = NOREF
    S.label = lab
    S.reset()
    tmp = Ref(S.name, S.gid, S.xyz, S.valid, label=np.where(lab == NOREF, S.gid, DROPPED))
    tmp.k, tmp.foot_steps, tmp.neigh = S.k, S.foot_steps, S.neigh
    psel = P.usable()
    _, pin, _, _ = match(P.xyz[psel], tmp, workers)
    plab = P.label.copy()
    pflat = np.flatnonzero(psel.ravel())
    plab.ravel()[pflat[pin]] = NOREF
    P.label = plab
    P.reset()
    out["outcome"] = "ambiguous: the disputed parts of both are no-reference masks"
    out["masked_share_of_kept"] = _r(pin.sum() / max(psel.sum(), 1))
    return out


def _positions(refs, stats, orient, min_pairs, neigh):
    """Normal position of every labelled reference (voxels, outward positive) by least squares over the median
    offsets of overlapping pairs; None for references linked to no other."""
    np = _np()
    ids = [r.gid for r in refs if r.labelled().any()]
    eqs = []
    for (a, b), st in stats.items():
        if a in ids and b in ids and st.get("matched", 0) >= min_pairs and abs(st.get("median_s", 1e9)) <= neigh:
            eqs.append((a, b, orient[b] * st["median_s"], math.sqrt(st["matched"])))
    adj = collections.defaultdict(set)
    for a, b, _, _ in eqs:
        adj[a].add(b)
        adj[b].add(a)
    pos, comp = {}, {}
    for start in ids:
        if start in comp:
            continue
        cid = len(set(comp.values()))
        stack, members = [start], []
        comp[start] = cid
        while stack:
            x = stack.pop()
            members.append(x)
            for y in adj[x]:
                if y not in comp:
                    comp[y] = cid
                    stack.append(y)
        if len(members) == 1:
            pos[start] = None if not adj[start] else 0.0
            continue
        col = {g: i for i, g in enumerate(sorted(members))}
        rows, rhs = [], []
        for a, b, o, w in eqs:
            if a in col and b in col:
                row = np.zeros(len(col))
                row[col[a]], row[col[b]] = w, -w
                rows.append(row)
                rhs.append(w * o)
        row = np.zeros(len(col))
        row[col[min(members)]] = 1.0
        rows.append(row)
        rhs.append(0.0)
        x, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
        for g, i in col.items():
            pos[g] = float(x[i])
    return pos, comp, eqs


def self_overlap(ref, workers=2):
    """Per native vertex: the distance along the normal to another part of the same mesh (more than
    self_far_cells native cells away in the grid) that lies inside the footprint, or inf. A winding traced past
    its seam overlaps itself; the offset says whether it went on to the next turn (about one pitch) or traced its
    own sheet twice (a few voxels)."""
    np = _np()
    out = np.full(ref.valid.shape, np.inf, np.float32)
    sel = ref.usable()
    if not sel.any():
        return out
    pts, nrm, src, _ = ref.scoring()
    P = ref.xyz[sel]
    rc = np.argwhere(sel)
    W = ref.valid.shape[1]
    foot = ref.footprint()
    k = max(2, int(ref.match_k) * 2)
    dist, j = ref.tree().query(P, k=k, distance_upper_bound=math.hypot(ref.neigh, foot) + 1e-6, workers=workers)
    found = np.isfinite(dist)
    jj = np.where(found, j, 0)
    rr, cc = np.divmod(src[jj], W)
    far = found & (np.maximum(np.abs(rr - rc[:, :1]), np.abs(cc - rc[:, 1:])) > ref.far_cells)
    v = P[:, None, :] - pts[jj]
    s = np.einsum("ikj,ikj->ik", v, nrm[jj])
    lat2 = np.einsum("ikj,ikj->ik", v, v) - s * s
    hit = far & (lat2 <= foot * foot)
    out[sel] = np.where(hit, np.abs(s), np.inf).min(1)
    return out


def build_manifest(dest, meshes, sources=None, skipped=None, rule=None, log=None, workers=2):
    """The reference manifest of a set of tifxyz windings in one frame (meshes: {name: folder}). Writes
    dest/attrs/<name>.npz (per-vertex labels, contact zones, gaps) and dest/manifest.json; returns the manifest."""
    np = _np()
    rule = rule or RULE
    D, R = rule["distance"], rule["references"]
    dest = Path(dest)
    t0 = time.time()
    names = sorted(meshes)
    if len(names) < 2:
        raise BenchError("a reference stack needs at least two windings")
    refs = []
    for gid, name in enumerate(names):
        xyz, valid, _ = read_tifxyz(meshes[name])
        refs.append(Ref(name, gid, xyz, valid, rule))
    _say(log, f"sheetrefs: {len(refs)} meshes read ({time.time() - t0:.0f} s); pass 1 (whole meshes)")
    stats1 = _all_pairs(refs, log, workers)
    orient, conflicts = _orient(refs, stats1, R["min_pair_matches"])
    groups = _resolve_duplicates(refs, stats1, orient, R, log, workers)

    # pass 2: labelled parts, per-vertex neighbours
    shape = {r.gid: r.valid.shape for r in refs}
    g_pos = {r.gid: np.full(shape[r.gid], np.inf, np.float32) for r in refs}
    g_neg = {r.gid: np.full(shape[r.gid], np.inf, np.float32) for r in refs}
    l_pos = {r.gid: np.full(shape[r.gid], -9, np.int32) for r in refs}
    l_neg = {r.gid: np.full(shape[r.gid], -9, np.int32) for r in refs}
    near_other = {r.gid: np.full(shape[r.gid], np.inf, np.float32) for r in refs}

    def per_vertex(A, B, sel, m):
        s, ins, src, nb = m
        flat = np.flatnonzero(sel.ravel())
        labB = B.label.ravel()[src]
        sg = np.sign(np.einsum("ij,ij->i", A.normals[sel], nb))
        t = -s * np.where(sg == 0, 1, sg)
        own = A.label.ravel()[flat]
        for side, gg, ll in ((1, g_pos[A.gid], l_pos[A.gid]), (-1, g_neg[A.gid], l_neg[A.gid])):
            tt = side * t
            cand = ins & (tt >= 0) & (tt < gg.ravel()[flat])
            gg.ravel()[flat[cand]] = tt[cand]
            ll.ravel()[flat[cand]] = labB[cand]
        diff = ins & (labB != own)
        no = near_other[A.gid].ravel()
        cur = no[flat[diff]]
        no[flat[diff]] = np.minimum(cur, np.abs(t[diff]))

    _say(log, f"sheetrefs: pass 2 (labelled parts) ({time.time() - t0:.0f} s)")
    _all_pairs(refs, log, workers, per_vertex=per_vertex)
    # two references on one sheet: where another winding lies within coincide_vox, neither can be told from the
    # other (a winding traced past its seam onto the next one's start, or a local copy); both become no-reference
    coincident = {}
    for r in refs:
        lab = r.labelled()
        hit = lab & (((g_pos[r.gid] <= R["coincide_vox"]) & (l_pos[r.gid] >= 0)) |
                     ((g_neg[r.gid] <= R["coincide_vox"]) & (l_neg[r.gid] >= 0)))
        coincident[r.gid] = (int(hit.sum()), int(lab.sum()))
        r.label[hit] = NOREF
    for r in refs:
        r.reset()
    selfov = {r.gid: self_overlap(r, workers) for r in refs}
    _say(log, f"sheetrefs: coincident parts masked, self-overlap measured ({time.time() - t0:.0f} s)")
    stats2 = _all_pairs(refs, None, workers, labelled_only=True)
    pos, comp, eqs = _positions(refs, stats2, orient, R["min_pair_matches"], D["neighbour_max_vox"])

    # the chain: labelled references in normal order (least-squares positions), each step measured directly
    # (the median offset of the two windings where they overlap, both ways), local pitch, gaps. The least-squares
    # positions order the windings but compress the steps: offsets to windings two or more turns away are
    # medians over the parts within neighbour_max_vox and inside the footprint, so the fit pulls the positions
    # together (on PHerc0139 every adjacent step came out 0.9 to 7.0 voxels shorter than measured directly).
    ordered = sorted((g for g in pos if pos[g] is not None), key=lambda g: (comp[g], pos[g]))
    by_gid = {r.gid: r for r in refs}
    chain = []
    for a, b in zip(ordered, ordered[1:]):
        if comp[a] != comp[b]:
            continue
        direct = [orient[b] * stats2[(a, b)]["median_s"]] if (a, b) in stats2 and "median_s" in stats2[(a, b)] else []
        if (b, a) in stats2 and "median_s" in stats2[(b, a)]:
            direct.append(-orient[a] * stats2[(b, a)]["median_s"])
        d_off = -float(np.mean(direct)) if direct else None
        chain.append({"inner": by_gid[a].name, "outer": by_gid[b].name, "offset_vox": pos[b] - pos[a],
                      "direct_offset_vox": d_off, "step_vox": d_off if d_off is not None else pos[b] - pos[a],
                      "cov2": stats2.get((b, a), {}).get("cov2"), "cov4": stats2.get((b, a), {}).get("cov4"),
                      "cov4_inner_to_outer": stats2.get((a, b), {}).get("cov4"),
                      "inside_outer_in_inner": stats2.get((b, a), {}).get("inside"),
                      "inside_inner_in_outer": stats2.get((a, b), {}).get("inside"),
                      "_ids": (a, b), "_comp": comp[a]})
    steps = [c["step_vox"] for c in chain]
    for i, c in enumerate(chain):
        local = [steps[j] for j in range(max(0, i - 2), min(len(steps), i + 3))
                 if j != i and chain[j]["_comp"] == c["_comp"]]
        c["local_pitch_vox"] = float(np.median(local)) if local else None
        c["gap"] = bool(local) and c["step_vox"] > R["gap_factor"] * c["local_pitch_vox"]
    pitch = {}
    for g in ordered:
        idx = [i for i, c in enumerate(chain) if g in c["_ids"]]
        win = [chain[j] for j in range(max(0, min(idx) - 1), min(len(chain), max(idx) + 2))
               if chain[j]["_comp"] == comp[g]] if idx else []
        vals = [c["step_vox"] for c in win if not c["gap"]] or [c["step_vox"] for c in win]
        pitch[g] = float(np.median(vals)) if vals else None
    neighbours = collections.defaultdict(list)
    adjacent = collections.defaultdict(set)        # chain neighbours across a step that is not a gap
    for c in chain:
        a, b = c.pop("_ids")
        c.pop("_comp")
        neighbours[a].append(b)
        neighbours[b].append(a)
        if not c["gap"]:
            adjacent[a].add(b)
            adjacent[b].add(a)

    attrs_dir = dest / "attrs"
    attrs_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    split_of = {n: "tune" for n in rule["split"]["tune"]}
    for r in refs:
        lab = r.labelled()
        p = pitch.get(r.gid)
        gp, gn = g_pos[r.gid], g_neg[r.gid]
        if p:
            # a side is a gap where no sheet was found on it, or where the nearest sheet on it is not an adjacent
            # winding (across a step that is not a gap) and lies more than gap_factor pitches away: a winding
            # with no reference there. Where the adjacent winding is the next sheet, the space between is not a
            # gap however wide (local spacing has a long tail), so a candidate off every
            # winding there is scored.
            good = np.array(sorted(adjacent[r.gid]), dtype=np.int64)
            far = R["gap_factor"] * p
            gap_pos = lab & (~np.isfinite(gp) | ((gp > far) & ~np.isin(l_pos[r.gid], good)))
            gap_neg = lab & (~np.isfinite(gn) | ((gn > far) & ~np.isin(l_neg[r.gid], good)))
        else:
            gap_pos = gap_neg = np.zeros_like(lab)
        contact = r.usable() & (near_other[r.gid] <= R["contact_vox"])
        f = attrs_dir / f"{r.name}.npz"
        np.savez_compressed(f, label=r.label, contact=contact, g_pos=gp, g_neg=gn, lab_pos=l_pos[r.gid],
                            lab_neg=l_neg[r.gid], gap_pos=gap_pos, gap_neg=gap_neg, self_s=selfov[r.gid])
        nlab = int(lab.sum())
        partial_vs = {by_gid[n].name: _r(stats2.get((n, r.gid), {}).get("inside")) for n in neighbours[r.gid]}
        partial = bool(partial_vs) and min((v or 0.0) for v in partial_vs.values()) < R["partial_inside_share"]
        area_cm2 = float(r.area[lab].sum()) * (VOXEL_UM * 1e-4) ** 2
        mpath = Path(meshes[r.name])
        try:
            rel = str(mpath.resolve().relative_to(dest.resolve()))
        except ValueError:
            rel = str(mpath.resolve())
        rows.append({
            "name": r.name, "id": r.gid, "path": rel,
            "files": {fn: _sha256(mpath / fn) for fn in MESH_FILES if (mpath / fn).is_file()},
            "attrs_sha256": _sha256(f),
            "grid": list(r.valid.shape), "vertices": int(r.ok.sum()), "labelled_vertices": nlab,
            "labelled_share": _r(nlab / max(int(r.ok.sum()), 1)),
            "no_reference_share": _r(float((r.ok & (r.label == NOREF)).sum()) / max(int(r.ok.sum()), 1)),
            "dropped_share": _r(float((r.ok & (r.label == DROPPED)).sum()) / max(int(r.ok.sum()), 1)),
            "area_cm2": _r(area_cm2, 2), "grid_step_vox": _r(r.step, 2), "orient": orient[r.gid],
            "position_vox": _r(pos.get(r.gid), 2), "component": comp.get(r.gid),
            "rank": ordered.index(r.gid) if r.gid in ordered else None,
            "chain_neighbours": [by_gid[n].name for n in neighbours[r.gid]],
            "local_pitch_vox": _r(p, 2), "partial": partial, "neighbour_inside_share": partial_vs,
            "chain_adjacent": [by_gid[n].name for n in sorted(adjacent[r.gid])],
            "gap_share_outer": _r(float(((gap_pos if orient[r.gid] > 0 else gap_neg) & lab).sum()) / max(nlab, 1)),
            "gap_share_inner": _r(float(((gap_neg if orient[r.gid] > 0 else gap_pos) & lab).sum()) / max(nlab, 1)),
            # beside them: where no sheet was found on that side, and where the next sheet is over gap_factor
            # pitches away whatever it is (the old rule's gap, kept to show how wide the spacing runs)
            "no_sheet_share_outer": _r(float((lab & ~np.isfinite(gp if orient[r.gid] > 0 else gn)).sum())
                                       / max(nlab, 1)),
            "wide_share_outer": (_r(float((lab & ~((gp if orient[r.gid] > 0 else gn) <= R["gap_factor"] * p)).sum())
                                    / max(nlab, 1)) if p else None),
            "contact_share": _r(float((contact & lab).sum()) / max(nlab, 1)),
            "coincident_share": _r(coincident[r.gid][0] / max(coincident[r.gid][1], 1)),
            "self_overlap_share": _r(float((lab & (selfov[r.gid] <= R["contact_vox"])).sum()) / max(nlab, 1)),
            "self_overlap_within_d4_share": _r(float((lab & (selfov[r.gid] <= D["primary_vox"])).sum())
                                               / max(nlab, 1)),
            "split": split_of.get(r.name, "buffer"),
            **({"source": sources[r.name]} if sources and r.name in sources else {}),
        })
    man = {
        "kind": "kit-sheetrefs", "version": 1,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "refs_rule_digest": rule_digest(rule), "rule": rule,
        "frame": rule["frame"],
        "references": rows,
        "order": [by_gid[g].name for g in ordered],
        "chain": [{k: (_r(v, 3) if isinstance(v, float) else v) for k, v in c.items()} for c in chain],
        "duplicates": groups,
        "orientation_conflicts": conflicts,
        "components": len(set(comp.values())),
        "split": {"tune": rule["split"]["tune"]},
        "skipped_folders": skipped or [],
        "seconds": round(time.time() - t0, 1),
    }
    man["digest"] = digest({k: man[k] for k in man if k not in ("created", "seconds", "digest")})
    (dest / "manifest.json").write_text(json.dumps(man, indent=1))
    _say(log, f"sheetrefs: manifest written ({man['seconds']} s), digest {man['digest'][:12]}")
    return man


def load_manifest(refs_dir, rule=None):
    p = Path(refs_dir) / "manifest.json"
    if not p.is_file():
        raise BenchError(f"{refs_dir}: no manifest.json; build it with python -m kit hopbench refs")
    man = json.loads(p.read_text())
    want = digest({k: man[k] for k in man if k not in ("created", "seconds", "digest")})
    if man.get("digest") != want:
        raise BenchError(f"{p}: the manifest does not match its digest (edited after it was built)")
    want = rule_digest(rule or RULE)
    if man.get("refs_rule_digest") != want:
        raise BenchError(f"{p}: built under rule {str(man.get('refs_rule_digest', ''))[:12]}, not the current "
                         f"rule {want[:12]}; rebuild the references (a changed rule is a new benchmark)")
    return man


class ChunkReader:
    """Level-0 chunks of a published zarr v2 prediction, cached under cache_dir. A chunk S3 reports missing
    (NoSuchKey) reads as None, the array's fill value (zeros), and is counted."""

    def __init__(self, prefix, cache_dir=DEFAULT_CACHE, opener=None):
        self.prefix, self.opener = prefix, opener
        self.root = Path(cache_dir) / prefix.rsplit("/", 1)[-1] / "0"
        meta = self.root / ".zarray"
        if not meta.is_file():
            _download(f"{BUCKET}/{prefix}/0/.zarray", meta, opener)
        self.meta = json.loads(meta.read_text())
        self.chunks = tuple(self.meta["chunks"])
        self.sep = self.meta.get("dimension_separator", ".")
        self.fetched = self.cached = self.missing = 0
        self._lock = threading.Lock()
        self._key_locks = {}

    def read(self, idx):
        # one thread at a time per chunk: two threads fetching one chunk share its .part file, and one could read
        # the chunk while the other's download is still being written into it
        key = self.sep.join(str(int(i)) for i in idx)
        with self._lock:
            lk = self._key_locks.setdefault(key, threading.Lock())
        with lk:
            return self._read(key)

    def _read(self, key):
        np = _np()
        from . import vc3d_audit
        f = self.root / key
        miss = f.with_name(f.name + ".missing")
        if miss.is_file():
            with self._lock:
                self.missing += 1
            return None
        if f.is_file():
            with self._lock:
                self.cached += 1
        else:
            if not _download(f"{BUCKET}/{self.prefix}/0/{key}", f, self.opener, optional=True):
                miss.parent.mkdir(parents=True, exist_ok=True)
                miss.write_text("")
                with self._lock:
                    self.missing += 1
                return None
            with self._lock:
                self.fetched += 1
        data = vc3d_audit._decompress(self.meta.get("compressor"), f.read_bytes())
        return np.frombuffer(data, dtype=np.dtype(self.meta["dtype"])).reshape(self.chunks)


def _neighbours_of(A, refs, man, key="chain_neighbours"):
    """A's neighbours in the chain (key chain_neighbours), or only those across a step that is not a gap
    (key chain_adjacent)."""
    rec = next((x for x in man["references"] if x["name"] == A.name), None)
    names = rec.get(key, []) if rec else []
    return [r for r in refs if r.name in names]


class LocalZarr:
    """Level-0 chunks of a local zarr v2 array (the array folder or its multiscale root), read like ChunkReader.

    A chunk file that is not there reads as the array's fill value, as zarr defines it, and is counted in `absent`:
    it is never missing, so a candidate cannot take a sampled chunk out of the comparison by leaving it unwritten.
    The array must be in m7's frame (level-0 shape (20974, 6621, 6621)) and uint8 unless an explicit offset (the frame
    voxel where the array's voxel 0 sits) and threshold are both given; given ones are recorded in the run rule."""

    def __init__(self, path, offset=None, threshold=None, expect=None):
        np = _np()
        path = Path(path)
        if not (path / ".zarray").is_file() and (path / "0" / ".zarray").is_file():
            path = path / "0"
        if not (path / ".zarray").is_file():
            raise BenchError(f"{path}: not a zarr v2 array (no .zarray)")
        self.root = path
        self.meta = json.loads((path / ".zarray").read_text())
        if self.meta.get("order", "C") != "C":
            raise BenchError(f"{path}: only C-order chunks are read")
        self.chunks = tuple(self.meta["chunks"])
        self.sep = self.meta.get("dimension_separator", ".")
        self.dtype = np.dtype(self.meta["dtype"])
        fv = self.meta.get("fill_value")
        self.fill = 0 if fv is None else fv
        exp = expect or M7_LEVEL0
        bad = []
        if list(self.meta.get("shape", [])) != list(exp["shape"]):
            bad.append(f"level-0 shape {self.meta.get('shape')} is not m7's {exp['shape']}")
        if self.dtype != np.dtype(exp["dtype"]):
            bad.append(f"dtype {self.dtype} is not {exp['dtype']}")
        if bad and (offset is None or threshold is None):
            raise BenchError(f"{path}: " + "; ".join(bad) + ": give an explicit offset and threshold (--offset, "
                             "--threshold), which the run rule records")
        self.offset = tuple(int(v) for v in offset) if offset is not None else (0, 0, 0)
        self.threshold = threshold
        self.declared = {k: v for k, v in (("offset", list(self.offset) if offset is not None else None),
                                           ("threshold", threshold)) if v is not None}
        self.fetched = self.cached = self.missing = self.absent = 0
        self.max_value = 0
        self._lock = threading.Lock()

    def read(self, idx):
        np = _np()
        from . import vc3d_audit
        f = self.root / self.sep.join(str(int(i)) for i in idx)
        if not f.is_file():
            with self._lock:
                self.absent += 1
            return np.full(self.chunks, self.fill, self.dtype)
        data = vc3d_audit._decompress(self.meta.get("compressor"), f.read_bytes())
        arr = np.frombuffer(data, dtype=self.dtype).reshape(self.chunks)
        top = arr.max().item() if arr.size else 0
        with self._lock:
            self.cached += 1
            self.max_value = max(self.max_value, top)
        return arr


def read_tifxyz(path):
    """(xyz (H, W, 3) float64, valid (H, W), meta) of a tifxyz folder; -1, NaN and all-zero vertices are holes."""
    np = _np()
    d = Path(path)
    if not (d / "x.tif").is_file():
        raise BenchError(f"{d}: no x.tif (not a tifxyz folder)")
    try:
        import tifffile
    except ImportError as exc:
        raise BenchError("kit hopbench needs tifffile: pip install tifffile") from exc
    grids = [np.asarray(tifffile.imread(str(d / f"{a}.tif"))).astype(np.float64) for a in "xyz"]
    if not (grids[0].ndim == 2 and grids[0].shape == grids[1].shape == grids[2].shape):
        raise BenchError(f"{d}: x, y and z tifs must be 2-D grids of one size")
    xyz = np.stack(grids, -1)
    valid = (xyz > -0.5).all(-1) & np.isfinite(xyz).all(-1) & (xyz.sum(-1) > 0)
    meta = {}
    mp = d / "meta.json"
    if mp.is_file():
        try:
            meta = json.loads(mp.read_text())
        except json.JSONDecodeError:
            meta = {}
    return xyz, valid, meta


def _download(url, dest, opener=None, optional=False, tries=4, sleep=time.sleep):
    """One object to dest with S3's false 404s retried (kit/s3retry.py); a real 404 raises, or returns False
    when optional. A dropped connection or a short read is retried up to `tries` times in all, waiting 2, 4 and
    8 s, before it raises."""
    import http.client
    import urllib.error
    import urllib.request
    from . import s3retry
    for attempt in range(max(1, tries)):
        req = urllib.request.Request(url, headers={"User-Agent": "kit-hopbench"})
        try:
            with s3retry.open_url(req, opener, timeout=120) as resp:
                data = resp.read()
            break
        except urllib.error.HTTPError as exc:
            if optional and exc.code == 404 and not s3retry.false_404(404, exc.read() or b""):
                return False
            if exc.code < 500 or attempt == tries - 1:
                raise BenchError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            if attempt == tries - 1:
                raise BenchError(f"{url}: {getattr(exc, 'reason', exc)!s:.200} ({type(exc).__name__})") from exc
        sleep(2.0 * 2 ** attempt)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".part{threading.get_ident()}")
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


def build_refs(dest=DEFAULT_REFS, opener=None, log=None, workers=2, rule=None, names=None):
    """Download the windings named in the rule's split (w023 to w040) in the 20250728140407 frame into
    dest/meshes/<wNNN>/, then build the reference manifest (build_manifest). Returns the manifest."""
    rule = rule or RULE
    want = set(rule["split"]["tune"] if names is None else names)
    dest = Path(dest)
    t0 = time.time()
    found, skipped = find_meshes(opener)
    left = [m["name"] for m in found if m["name"] not in want]
    found = [m for m in found if m["name"] in want]
    missing = sorted(want - {m["name"] for m in found})
    if missing:
        raise BenchError(f"windings not found on the bucket: {', '.join(missing)}")
    _say(log, f"sheetrefs: {len(found)} winding meshes in frame {VOLUME} ({len(left)} others left out)")
    jobs = [(m, f) for m in found for f in MESH_FILES]

    def get(job):
        m, f = job
        out = dest / "meshes" / m["name"] / f
        if out.is_file() and out.stat().st_size > 0:
            return 0
        _download(f"{BUCKET}/{urllib.parse.quote(m['prefix'])}/{f}", out, opener)
        return 1

    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        fetched = sum(pool.map(get, jobs))
    _say(log, f"sheetrefs: fetched {fetched} files ({time.time() - t0:.0f} s)")
    sources = {m["name"]: {"folder": m["folder"], "prefix": m["prefix"]} for m in found}
    return build_manifest(dest, {m["name"]: dest / "meshes" / m["name"] for m in found}, sources=sources,
                          skipped=skipped, rule=rule, log=log, workers=workers)


def load_refs(refs_dir=DEFAULT_REFS, rule=None):
    """(manifest, [Ref]) with each reference's labels and attributes (contact, gaps, self-overlap)."""
    np = _np()
    rule = rule or RULE
    refs_dir = Path(refs_dir)
    man = load_manifest(refs_dir, rule)
    refs = []
    for rec in man["references"]:
        path = Path(rec["path"])
        path = path if path.is_absolute() else refs_dir / path
        xyz, valid, _ = read_tifxyz(path)
        f = refs_dir / "attrs" / f"{rec['name']}.npz"
        if _sha256(f) != rec["attrs_sha256"]:
            raise BenchError(f"{f}: changed since the manifest was built")
        with np.load(f) as a:
            attrs = {k: a[k] for k in a.files}
        r = Ref(rec["name"], rec["id"], xyz, valid, rule, label=attrs.pop("label"))
        r.attrs = attrs
        r.attrs["orient"] = rec["orient"]
        r.attrs["rank"] = rec["rank"]
        refs.append(r)
    return man, refs
