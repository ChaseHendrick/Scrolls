"""Ringleader v1: winding labels for every sheet in one z-slice at once.

Model output from a published binary surface prediction (such as the organizers' m7); nothing here is a reading.

Idea (phase unwrapping): the label of a sheet piece is its turn number k, with unwrapped angle
Phi = theta' + 2 pi k growing outward. Local facts become soft constraints on integer labels:

  continuity  consecutive pieces of one skeleton path carry the same label, or +1 / -1 where the path crosses
              the start ray theta' = 0 (L1 cost c_cont per unit of violation)
  radial      the next sheet out along the outward normal has a label at least one higher (cost c_hi per unit
              below 1), preferably exactly one higher (cost c_lo per unit above 1, so a sheet the prediction
              missed costs little when the rest of the slice says it is there)

All costs are convex piecewise linear in label differences with integer breakpoints, so the problem is a
minimum-cost tension problem (the dual of a minimum-cost flow) and its linear relaxation has an integral
optimum; it is solved exactly with HiGHS.

A naive baseline counts the m7 sheets crossed along the straight ray from the umbilicus to each pixel.
"""

import math
import time

import numpy as np
from scipy import ndimage, sparse
from scipy.optimize import linprog
from scipy.sparse import csgraph

PARAMS = {
    "version": 1,
    "threshold": 127,
    "block_fill": 0.9,          # 64 px tiles at least this full are chunk fill, not sheets
    "r_min": 150.0,             # pixels nearer the umbilicus are left out (theta is ill-defined there)
    "piece_len": 40,            # skeleton pixels per piece along a path
    "min_piece": 4,             # pieces shorter than this get no radial samples of their own
    "radial_every": 8,          # one radial sample per this many skeleton pixels
    "tangent_half": 5,          # path pixels each side used for the local tangent
    "max_step": 40.0,           # farthest next sheet looked for along the normal (px)
    "march_step": 0.5,
    "c_hi": 20.0,               # cost per unit a radial difference falls below 1
    "c_lo": 1.0,                # cost per unit a radial difference exceeds 1
    "c_cont": 10.0,             # cost per unit a continuity difference misses its shift
    "skel_snap": 3.0,           # a hit maps to the skeleton pixel nearest the next sheet's center within this
    "block_margin": 4,          # px removed around chunk-fill blocks (their edges are not sheets)
    "spur_len": 8,              # skeleton branches from an end to a junction shorter than this are pruned
    "spur_rounds": 2,
    "rel_len": 0.0,             # >0: radial weight x min(1, path length / rel_len) at both ends
    "pitch_k": 0,               # >0: local pitch = median step of this many nearest samples; shapes costs
    "hi_lo": 0.3, "hi_hi": 0.7,     # step/pitch ramp for the 'below 1' weight (0.05 at hi_lo, 1 at hi_hi)
    "lo_lo": 1.4, "lo_hi": 1.8,     # step/pitch ramp for the 'above 1' weight (1 at lo_lo, 0.1 at lo_hi)
    "bridge": 0,                # 1: continuity edges across junctions (best straight pair) and small end gaps
    "bridge_angle": 30.0,       # max bend (deg) between two path ends joined across a junction or a gap
    "bridge_gap": 12.0,         # max gap (px) between two path ends joined
    "bridge_back": 8,           # path pixels used for an end's direction
    "c_bridge": None,           # cost of a bridge edge (None: c_cont)
    "rays": 1,                  # 3: OR of three parallel rays 1.5 px apart (fills pin holes in the next sheet)
    "cont_len": 0,              # >0: continuity edges on skeleton paths at least this long (px) cost c_cont_long
    "c_cont_long": 10.0,
    "c_seam": None,             # cost of a continuity edge across the start ray (None: as any other)
    "lp_method": "highs",       # "highs-ipm" (interior point and crossover) is about 3 times faster here;
                                # "mcf": the same optimum through the dual minimum-cost flow (OR-tools), far faster
    "mcf_scale": 1000.0,        # mcf: slopes (costs per unit) are multiplied by this and rounded to integers
    "hand": None,               # None: geometry()'s shape statistic; +1 / -1: forced; "objective": the cheaper
                                # labeling (unreliable: it can pick the wrong hand); "track": track_hand() on m7
}

# Ringleader v1: the settings of the frozen tests (the rest of PARAMS at its defaults, and slab3d.ZPARAMS for a
# stack). run_slices.py and slab3d.py start from these; --params overrides them.
V1 = {"lp_method": "mcf", "hand": "track"}


# ---------------------------------------------------------------- slice preparation

def clean_slice(s, p=PARAMS):
    """Binary sheet mask with chunk-fill blocks removed."""
    S = s > p["threshold"]
    t = 64
    H, W = S.shape
    h, w = H // t * t, W // t * t
    fill = S[:h, :w].reshape(h // t, t, w // t, t).mean(axis=(1, 3))
    bad = np.zeros_like(S)
    bad[:h, :w] = np.repeat(np.repeat(fill >= p["block_fill"], t, 0), t, 1)
    if p.get("block_margin", 0):
        bad = ndimage.binary_dilation(bad, iterations=int(p["block_margin"]))
    return S & ~bad


def skeleton(S):
    from skimage.morphology import skeletonize
    return skeletonize(S)


def prune_spurs(K, max_len, rounds=2):
    """Remove skeleton branches that run from an end pixel to a junction in fewer than max_len pixels."""
    K = K.copy()
    for _ in range(rounds):
        ys, xs, A, idx = skel_graph(K)
        deg = np.asarray(A.sum(axis=1)).ravel()
        indptr, indices = A.indptr, A.indices
        kill = []
        for e in np.flatnonzero(deg == 1):
            walk, prev, cur = [e], -1, e
            while len(walk) <= max_len:
                nb = [v for v in indices[indptr[cur]:indptr[cur + 1]] if v != prev]
                if not nb:
                    walk = []          # an isolated short piece: keep it (it is not a spur of a sheet)
                    break
                if deg[nb[0]] >= 3 or len(nb) > 1:
                    break
                prev, cur = cur, nb[0]
                walk.append(cur)
            else:
                walk = []
            if walk and len(walk) < max_len:
                kill.extend(walk)
        if not kill:
            break
        kill = np.asarray(kill)
        K[ys[kill], xs[kill]] = False
    return K


def polar(cx, cy, H, W):
    yy, xx = np.mgrid[0:H, 0:W]
    return np.hypot(xx - cx, yy - cy), np.arctan2(yy - cy, xx - cx)


# ---------------------------------------------------------------- skeleton graph and pieces

_NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def skel_graph(K):
    """Sparse neighbor adjacency over skeleton pixels; returns (ys, xs, A, index image). A diagonal step is
    dropped when the two pixels already touch through a shared 4-neighbor, so staircase lines have degree 2
    and only real junctions have degree 3 or more."""
    ys, xs = np.nonzero(K)
    n = len(ys)
    idx = -np.ones(K.shape, np.int64)
    idx[ys, xs] = np.arange(n)
    H, W = K.shape
    Kp = np.pad(K, 1)
    rows, cols = [], []
    for dy, dx in _NB:
        y2, x2 = ys + dy, xs + dx
        ok = (y2 >= 0) & (y2 < H) & (x2 >= 0) & (x2 < W)
        j = np.full(n, -1)
        j[ok] = idx[y2[ok], x2[ok]]
        m = j >= 0
        if dy and dx:
            # redundant diagonal: a 4-neighbor of both is on the skeleton
            via = Kp[ys + dy + 1, xs + 1] | Kp[ys + 1, xs + dx + 1]
            m &= ~via
        rows.append(np.arange(n)[m])
        cols.append(j[m])
    rows, cols = np.concatenate(rows), np.concatenate(cols)
    A = sparse.csr_matrix((np.ones(len(rows), np.int8), (rows, cols)), shape=(n, n))
    return ys, xs, A, idx


def paths(A, deg):
    """Simple paths of the skeleton with junction pixels (degree >= 3) removed: list of index arrays in path
    order. Junction pixels themselves are returned as their own one-pixel paths (no continuity edges)."""
    n = A.shape[0]
    keep = deg <= 2
    sub = A[keep][:, keep]
    kidx = np.flatnonzero(keep)
    ncomp, lab = csgraph.connected_components(sub, directed=False)
    sdeg = np.asarray(sub.sum(axis=1)).ravel()
    order = np.argsort(lab, kind="stable")
    bounds = np.searchsorted(lab[order], np.arange(ncomp + 1))
    out = []
    indptr, indices = sub.indptr, sub.indices
    for c in range(ncomp):
        mem = order[bounds[c]:bounds[c + 1]]
        if len(mem) == 1:
            out.append(kidx[mem])
            continue
        ends = mem[sdeg[mem] <= 1]
        start = ends[0] if len(ends) else mem[0]
        # walk the path (degree <= 2 inside the component)
        seq = [start]
        prev, cur = -1, start
        while True:
            nb = indices[indptr[cur]:indptr[cur + 1]]
            nxt = [v for v in nb if v != prev]
            if not nxt or (len(seq) > 1 and nxt[0] == start):
                break
            # an 8-connected skeleton can have small triangles; prefer an unvisited neighbor
            v = nxt[0]
            if len(seq) >= len(mem):
                break
            prev, cur = cur, v
            seq.append(cur)
        seq = np.asarray(seq)
        if len(seq) < len(mem):     # leftovers of a messy component: add them as singletons
            rest = np.setdiff1d(mem, seq)
            for v in rest:
                out.append(kidx[[v]])
        out.append(kidx[seq])
    for v in np.flatnonzero(~keep):
        out.append(np.asarray([v]))
    return out


def make_pieces(path_list, theta_p, n, p=PARAMS):
    """Cut paths into pieces of at most piece_len pixels and at every crossing of the start ray. Returns piece id
    per skeleton pixel, the pieces' pixel lists, and continuity edges (a, b, shift)."""
    pid = -np.ones(n, np.int64)
    pieces, cont = [], []
    L = p["piece_len"]
    for q in path_list:
        th = theta_p[q]
        wraps = np.flatnonzero(np.abs(np.diff(th)) > math.pi) + 1   # cut positions where theta' wraps
        cuts = set(range(L, len(q), L)) | set(wraps.tolist())
        cuts = sorted(c for c in cuts if 0 < c < len(q))
        segs = np.split(np.arange(len(q)), cuts)
        prev = None
        for s in segs:
            k = len(pieces)
            pieces.append(q[s])
            pid[q[s]] = k
            if prev is not None:
                a_last, b_first = q[prev[-1]], q[s[0]]
                d = theta_p[b_first] - theta_p[a_last]
                shift = 1 if d < -math.pi else (-1 if d > math.pi else 0)
                cont.append((len(pieces) - 2, k, shift))
            prev = s
    return pid, pieces, cont


def bridges(ys, xs, A, deg, path_list, pid, theta_p, p=PARAMS):
    """Continuity edges between path ends that continue each other: across a junction (the straightest pair of
    ends meeting there) and across a small gap between two free ends facing each other. (a, b, shift)."""
    cos_max = -math.cos(math.radians(p["bridge_angle"]))
    k = int(p["bridge_back"])
    n = len(ys)
    junc = deg >= 3
    jsub = A[junc][:, junc]
    jidx = np.flatnonzero(junc)
    _, jl = csgraph.connected_components(jsub, directed=False)
    jcl = -np.ones(n, np.int64)
    jcl[jidx] = jl
    indptr, indices = A.indptr, A.indices
    ends = []          # (pixel, piece, ux, uy, junction cluster or -1, free end)
    for q in path_list:
        if len(q) < 3 or junc[q[0]]:
            continue
        for e, inner in ((q[0], q[min(k, len(q) - 1)]), (q[-1], q[max(len(q) - 1 - k, 0)])):
            dx, dy = float(xs[e] - xs[inner]), float(ys[e] - ys[inner])
            nrm = math.hypot(dx, dy)
            if nrm < 1e-6:
                continue
            nb = indices[indptr[e]:indptr[e + 1]]
            jc = [int(jcl[v]) for v in nb if junc[v]]
            ends.append((int(e), int(pid[e]), dx / nrm, dy / nrm, jc[0] if jc else -1, deg[e] <= 1))
    out = []

    def shift(a_px, b_px):
        d = theta_p[b_px] - theta_p[a_px]
        return 1 if d < -math.pi else (-1 if d > math.pi else 0)
    used = set()
    byj = {}
    for i, e in enumerate(ends):
        if e[4] >= 0:
            byj.setdefault(e[4], []).append(i)
    for j, mem in byj.items():
        cand = []
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                a, b = ends[mem[x]], ends[mem[y]]
                if a[1] == b[1]:
                    continue
                dot = a[2] * b[2] + a[3] * b[3]
                if dot <= cos_max:
                    cand.append((dot, mem[x], mem[y]))
        cand.sort()
        for dot, x, y in cand:
            if x in used or y in used:
                continue
            used.add(x)
            used.add(y)
            a, b = ends[x], ends[y]
            out.append((a[1], b[1], shift(a[0], b[0])))
    free = [i for i, e in enumerate(ends) if e[4] < 0 and e[5] and i not in used]
    if len(free) > 1:
        from scipy.spatial import cKDTree
        P = np.asarray([[xs[ends[i][0]], ys[ends[i][0]]] for i in free], float)
        pairs = cKDTree(P).query_pairs(p["bridge_gap"], output_type="ndarray")
        cand = []
        for x, y in pairs:
            a, b = ends[free[x]], ends[free[y]]
            if a[1] == b[1]:
                continue
            v = P[y] - P[x]
            dist = float(np.hypot(*v))
            if dist < 1e-6:
                continue
            v /= dist
            if a[2] * b[2] + a[3] * b[3] > cos_max:
                continue
            if v[0] * a[2] + v[1] * a[3] < -cos_max or -(v[0] * b[2] + v[1] * b[3]) < -cos_max:
                continue
            cand.append((dist, free[x], free[y]))
        cand.sort()
        for dist, x, y in cand:
            if x in used or y in used:
                continue
            used.add(x)
            used.add(y)
            a, b = ends[x], ends[y]
            out.append((a[1], b[1], shift(a[0], b[0])))
    return out


# ---------------------------------------------------------------- radial edges

def tangents(ys, xs, path_list, half):
    """Unit tangent per skeleton pixel from its path neighbors."""
    T = np.zeros((len(ys), 2))
    for q in path_list:
        if len(q) < 2:
            continue
        P = np.stack([xs[q], ys[q]], 1).astype(float)
        a = np.clip(np.arange(len(q)) - half, 0, len(q) - 1)
        b = np.clip(np.arange(len(q)) + half, 0, len(q) - 1)
        d = P[b] - P[a]
        nrm = np.linalg.norm(d, axis=1, keepdims=True)
        T[q] = d / np.maximum(nrm, 1e-9)
    return T


def radial_edges(S, K, ys, xs, pid, pieces, T, cx, cy, p=PARAMS):
    """From sampled skeleton pixels, march outward along the normal to the next sheet; return
    (sample pixel, hit skeleton pixel, gap px, next-run width px, step px center to center) rows."""
    H, W = S.shape
    # nearest skeleton pixel for every pixel
    dist, (iy, ix) = ndimage.distance_transform_edt(~K, return_indices=True)
    idx = -np.ones(K.shape, np.int64)
    idx[ys, xs] = np.arange(len(ys))
    samp = []
    for k, q in enumerate(pieces):
        if len(q) < p["min_piece"]:
            continue
        sel = q[::p["radial_every"]] if len(q) >= p["radial_every"] else q[len(q) // 2:len(q) // 2 + 1]
        samp.append(sel)
    samp = np.concatenate(samp) if samp else np.zeros(0, np.int64)
    good = np.linalg.norm(T[samp], axis=1) > 0.5
    samp = samp[good]
    px, py = xs[samp].astype(float), ys[samp].astype(float)
    nx, ny = T[samp, 1], -T[samp, 0]            # normal = tangent rotated
    out = (nx * (px - cx) + ny * (py - cy)) < 0
    nx[out], ny[out] = -nx[out], -ny[out]
    nsteps = int(p["max_step"] / p["march_step"])
    tt = np.arange(1, nsteps + 1) * p["march_step"]
    # profile of S along each normal
    prof = np.zeros((len(samp), nsteps), bool)
    lat = (0.0,) if p.get("rays", 1) <= 1 else (-1.5, 0.0, 1.5)
    for o in lat:
        X = np.rint(px[:, None] - ny[:, None] * o + nx[:, None] * tt[None]).astype(int)
        Y = np.rint(py[:, None] + nx[:, None] * o + ny[:, None] * tt[None]).astype(int)
        inb = (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
        pr = np.zeros(X.shape, bool)
        pr[inb] = S[Y[inb], X[inb]]
        prof |= pr
    rows = []
    for i in range(len(samp)):
        pr = prof[i]
        # leave the own sheet, then find the next run
        off = np.flatnonzero(~pr)
        if not len(off):
            continue
        a = off[0]
        on = np.flatnonzero(pr[a:])
        if not len(on):
            continue
        s0 = a + on[0]
        rest = np.flatnonzero(~pr[s0:])
        s1 = s0 + (rest[0] if len(rest) else len(pr) - s0)
        mid = 0.5 * (s0 + s1 - 1)
        cxp = int(round(px[i] + nx[i] * tt[min(int(mid), nsteps - 1)]))
        cyp = int(round(py[i] + ny[i] * tt[min(int(mid), nsteps - 1)]))
        if not (0 <= cxp < W and 0 <= cyp < H) or dist[cyp, cxp] > p["skel_snap"]:
            continue
        j = idx[iy[cyp, cxp], ix[cyp, cxp]]
        if j < 0 or pid[j] == pid[samp[i]]:
            continue
        rows.append((samp[i], j, tt[s0] - tt[a] if a < len(tt) else 0.0, (s1 - s0) * p["march_step"],
                     float(np.hypot(xs[j] - px[i], ys[j] - py[i]))))
    return np.asarray(rows, dtype=float).reshape(-1, 5)


# ---------------------------------------------------------------- the solve

def solve(npieces, cont, rad, p=PARAMS, bridges_=()):
    """Integer labels minimizing the convex costs. cont: (a, b, shift); rad: (a, b, f0, f1, f2, f3[, s])
    aggregated, the cost of label difference d = s + 0, s + 1, s + 2, s + 3 (convex, extended linearly beyond),
    where s is the start-ray shift of the samples (+1 when the step outward crosses theta' = 0 in the +theta'
    direction, -1 the other way, else 0). Returns labels (float, NaN where a piece has no edge), component per
    piece, and solver info."""
    rad = [(int(r[0]), int(r[1]), *(float(v) for v in r[2:6]), int(r[6]) if len(r) > 6 else 0) for r in rad
           if max(r[2:6]) - min(r[2:6]) > 0]
    used = np.zeros(npieces, bool)
    for c_ in cont:
        used[c_[0]] = used[c_[1]] = True
    for r in rad:
        used[r[0]] = used[r[1]] = True
    for a, b, _ in bridges_:
        used[a] = used[b] = True
    var = -np.ones(npieces, np.int64)
    var[used] = np.arange(used.sum())
    nv = int(used.sum())
    cb = p["c_bridge"] if p.get("c_bridge") is not None else p["c_cont"]
    ce = [(var[c_[0]], var[c_[1]], c_[2], c_[3] if len(c_) > 3 else p["c_cont"]) for c_ in cont
          if used[c_[0]] and used[c_[1]]]
    ce += [(var[a], var[b], s, cb) for a, b, s in bridges_]
    re = [(var[r[0]], var[r[1]], r[2:6], r[6]) for r in rad]
    ne = len(ce) + len(re)
    N = nv + ne
    rows, cols, vals, rhs = [], [], [], []
    r = 0

    def add(terms, b):
        nonlocal r
        for c, v in terms:
            rows.append(r)
            cols.append(c)
            vals.append(v)
        rhs.append(b)
        r += 1
    e = nv
    for a, b, s, w in ce:
        add([(b, w), (a, -w), (e, -1.0)], w * s)
        add([(b, -w), (a, w), (e, -1.0)], -w * s)
        e += 1
    for a, b, f, sh in re:
        f = np.asarray(f, float) - min(f)
        for k in range(3):                                # t >= f(k) + s_k (d - sh - k), s_k = f(k + 1) - f(k)
            sk = float(f[k + 1] - f[k])
            if sk == 0 and f[k] == 0:
                continue
            add([(b, sk), (a, -sk), (e, -1.0)], sk * (k + sh) - float(f[k]))
        e += 1
    A = sparse.csr_matrix((vals, (rows, cols)), shape=(r, N))
    c = np.concatenate([np.zeros(nv), np.ones(ne)])
    G = sparse.coo_matrix((np.ones(ne), ([x[0] for x in ce] + [x[0] for x in re],
                                         [x[1] for x in ce] + [x[1] for x in re])), shape=(nv, nv))
    ncomp, comp = csgraph.connected_components(G, directed=False)
    bounds = [(None, None)] * nv + [(0, None)] * ne
    seen = set()
    for v in range(nv):
        if comp[v] not in seen:
            seen.add(comp[v])
            bounds[v] = (0, 0)
    t0 = time.time()
    if p.get("lp_method") == "mcf":
        return _solve_mcf(npieces, used, nv, ce, re, comp, ncomp, p, t0)
    res = linprog(c, A_ub=A, b_ub=np.asarray(rhs), bounds=bounds, method=p.get("lp_method", "highs"))
    info = {"status": int(res.status), "message": str(res.message), "seconds": round(time.time() - t0, 1),
            "variables": N, "constraints": r, "components": int(ncomp),
            "objective": float(res.fun) if res.status == 0 else None}
    lab = np.full(npieces, np.nan)
    comp_p = -np.ones(npieces, np.int64)
    if res.status == 0:
        x = res.x[:nv]
        info["max_fractional"] = float(np.abs(x - np.rint(x)).max()) if nv else 0.0
        lab[used] = np.rint(x)
        comp_p[used] = comp
    return lab, comp_p, info


def _edge_slopes(ce, re):
    """Each edge as (a, b, slopes, breakpoints): its cost of t = label b - label a is convex piecewise linear with
    slope slopes[j] between breakpoints[j - 1] and breakpoints[j] (slopes[0] to the left of breakpoints[0])."""
    out = []
    for a, b, s, w in ce:
        out.append((a, b, (-float(w), float(w)), (int(s),)))
    for a, b, f, sh in re:
        f = np.asarray(f, float) - min(f)
        sig = (float(f[1] - f[0]), float(f[2] - f[1]), float(f[3] - f[2]))
        if sig[0] > 0 or sig[2] < 0:
            # the LP route clips such a cost at 0 (max with t >= 0) at a non-integer tension; mcf cannot
            raise ValueError(f"radial cost {list(f)} is not lowest inside d = 0..3; use an LP method")
        out.append((a, b, sig, (1 + int(sh), 2 + int(sh))))
    return out


def edge_cost(t, slopes, bps):
    """The convex cost of tension t (array) on one edge, up to a constant: sum of slope changes past breakpoints."""
    t = np.asarray(t, float)
    g = slopes[0] * t
    for j, bp in enumerate(bps):
        g = g + (slopes[j + 1] - slopes[j]) * np.maximum(0.0, t - bp)
    return g


def objective(labels, cont, rad, p=PARAMS):
    """Sum of solve()'s costs for integer labels per piece (cont and rad as passed to solve), exactly, with the
    constant of each radial edge restored (its minimum over d = 0..3 is 0)."""
    tot = 0.0
    for c_ in cont:
        w = c_[3] if len(c_) > 3 else p["c_cont"]
        tot += w * abs(labels[c_[1]] - labels[c_[0]] - c_[2])
    for r in rad:
        f = np.asarray(r[2:6], float)
        f = f - f.min()
        d = labels[r[1]] - labels[r[0]] - (r[6] if len(r) > 6 else 0)
        if d <= 3:
            k = int(min(max(math.floor(d), 0), 2))
            tot += f[k] + (f[k + 1] - f[k]) * (d - k)
        else:
            tot += f[3] + (f[3] - f[2]) * (d - 3)
    return float(tot)


def _bellman_ford(n, src, dst, w, max_iter=None):
    """Shortest distances from a virtual root joined to every node at cost 0 (so all distances are <= 0), by
    vectorised Bellman-Ford over integer arc costs. Raises when a negative cycle keeps it from converging."""
    order = np.argsort(dst, kind="stable")
    src, dst, w = src[order], dst[order], w[order]
    ud, starts = np.unique(dst, return_index=True)
    d = np.zeros(n, np.int64)
    max_iter = max_iter or n + 1
    for it in range(max_iter):
        m = np.minimum.reduceat(d[src] + w, starts)
        better = m < d[ud]
        if not better.any():
            return d, it
        d[ud[better]] = m[better]
    raise RuntimeError("Bellman-Ford did not converge: negative cycle in the residual graph")


def _solve_mcf(npieces, used, nv, ce, re, comp, ncomp, p, t0):
    """solve() through its dual: a minimum-cost circulation (OR-tools network solver) whose optimal node
    potentials are the labels. Edge (a, b) with slopes s_0 < ... < s_m and integer breakpoints b_1 < ... < b_m
    becomes arcs a -> b of capacity s_j - s_(j-1) and unit cost b_j on top of a forced flow s_0 (node supplies);
    slopes are scaled by mcf_scale and rounded to integers. The labels are the shortest distances in the optimal
    flow's residual graph from a root joined to every node at cost 0 (reduced costs then all >= 0, so they are
    optimal potentials); each component is shifted so its first variable is 0, as in the LP."""
    from ortools.graph.python import min_cost_flow
    S = float(p.get("mcf_scale", 1000.0))
    E = _edge_slopes(ce, re)
    sa, sb, cap, cost = [], [], [], []
    supply = np.zeros(nv, np.int64)
    for a, b, sig, bps in E:
        q = [int(round(S * x)) for x in sig]
        supply[b] += q[0]
        supply[a] -= q[0]
        for j, bp in enumerate(bps):
            u = q[j + 1] - q[j]
            if u > 0:
                sa.append(a)
                sb.append(b)
                cap.append(u)
                cost.append(bp)
    sa, sb = np.asarray(sa, np.int64), np.asarray(sb, np.int64)
    cap, cost = np.asarray(cap, np.int64), np.asarray(cost, np.int64)
    mcf = min_cost_flow.SimpleMinCostFlow()
    arcs = mcf.add_arcs_with_capacity_and_unit_cost(sa, sb, cap, cost)
    mcf.set_nodes_supplies(np.arange(nv), supply)
    st = mcf.solve()
    info = {"status": 0 if st == mcf.OPTIMAL else int(st), "message": f"or-tools min cost flow status {st}",
            "variables": nv, "constraints": int(len(sa)), "components": int(ncomp), "method": "mcf"}
    lab = np.full(npieces, np.nan)
    comp_p = -np.ones(npieces, np.int64)
    if st != mcf.OPTIMAL:
        info["seconds"] = round(time.time() - t0, 1)
        return lab, comp_p, info
    flow = mcf.flows(arcs)
    fw = flow < cap
    bw = flow > 0
    src = np.concatenate([sa[fw], sb[bw]])
    dst = np.concatenate([sb[fw], sa[bw]])
    w = np.concatenate([cost[fw], -cost[bw]])
    t1 = time.time()
    d, iters = _bellman_ford(nv, src, dst, w)
    first = np.full(ncomp, -1, np.int64)
    for v in range(nv - 1, -1, -1):
        first[comp[v]] = v
    x = (d - d[first[comp]]).astype(float)
    lab[used] = x
    comp_p[used] = comp
    info.update({"seconds": round(time.time() - t0, 1), "potential_seconds": round(time.time() - t1, 1),
                 "bf_iterations": int(iters), "scaled_cost": int(mcf.optimal_cost()), "max_fractional": 0.0})
    return lab, comp_p, info


def sample_weights(geo, p=PARAMS):
    """Per radial sample: (w_hi, w_lo) from path reliability and the step against the local pitch."""
    rows = geo["rows"]
    n = len(rows)
    wh, wl = np.ones(n), np.ones(n)
    if not n:
        return wh, wl
    a, b = rows[:, 0].astype(int), rows[:, 1].astype(int)
    if p.get("rel_len", 0) > 0:
        plen = geo["path_len"]
        rel = np.minimum(1.0, plen[a] / p["rel_len"]) * np.minimum(1.0, plen[b] / p["rel_len"])
        wh *= rel
        wl *= rel
    if p.get("pitch_k", 0) > 0:
        from scipy.spatial import cKDTree
        P = np.stack([geo["xs"][a], geo["ys"][a]], 1).astype(float)
        step = rows[:, 4]
        k = min(int(p["pitch_k"]), n)
        _, nb = cKDTree(P).query(P, k=k)
        pitch = np.median(step[nb], axis=1)
        rho = step / np.maximum(pitch, 1e-6)
        gh = np.clip((rho - p["hi_lo"]) / (p["hi_hi"] - p["hi_lo"]), 0.0, 1.0) * 0.95 + 0.05
        gl = 1.0 - np.clip((rho - p["lo_lo"]) / (p["lo_hi"] - p["lo_lo"]), 0.0, 1.0) * 0.9
        wh *= gh
        wl *= gl
    return wh, wl


def row_costs(geo, p=PARAMS):
    """Per radial sample, the cost of label difference d = 0, 1, 2, 3 (n x 4, convex in d)."""
    n = len(geo["rows"])
    F = np.zeros((n, 4))
    wh, wl = sample_weights(geo, p)
    F[:, 0] = p["c_hi"] * wh
    F[:, 2] = p["c_lo"] * wl
    F[:, 3] = 2 * p["c_lo"] * wl
    return F


def row_shifts(geo):
    """Per radial sample, the start-ray shift of its step outward: +1 when it crosses theta' = 0 in the +theta'
    direction (the next sheet's label is then 2 higher, not 1), -1 the other way (0 higher), else 0."""
    rows = geo["rows"]
    if not len(rows):
        return np.zeros(0, np.int64)
    th = geo["theta_p"]
    d = th[rows[:, 1].astype(int)] - th[rows[:, 0].astype(int)]
    return np.where(d < -math.pi, 1, np.where(d > math.pi, -1, 0)).astype(np.int64)


def aggregate(rows, pid, F, shift=None):
    """Radial samples to (piece a, piece b, f0, f1, f2, f3, s): the summed costs of each piece pair and shift."""
    if not len(rows):
        return []
    a = pid[rows[:, 0].astype(int)]
    b = pid[rows[:, 1].astype(int)]
    sh = np.zeros(len(a), np.int64) if shift is None else np.asarray(shift, np.int64)
    key = (a * (pid.max() + 1) + b) * 3 + (sh + 1)
    u, inv = np.unique(key, return_inverse=True)
    S = np.stack([np.bincount(inv, weights=F[:, k], minlength=len(u)) for k in range(4)], 1)
    first = np.zeros(len(u), np.int64)
    first[inv] = np.arange(len(a))
    return [(int(a[i]), int(b[i]), *(float(v) for v in S[j]), int(sh[i])) for j, i in enumerate(first)]


def radial_terms(geo, p=PARAMS):
    """The aggregated radial terms of one slice, with their start-ray shifts."""
    return aggregate(geo["rows"], geo["pid"], row_costs(geo, p), row_shifts(geo))


def track_hand(S, cx, cy, p=PARAMS):
    """The spiral's hand from the cleaned m7 slice alone (no labels, no references). On rays every
    360 / track_rays degrees from the umbilicus, take the centers of thin sheet runs; from a start run, follow
    the nearest run ray by ray in the +atan2 direction (with a velocity prediction) for one full turn. Back on
    the start ray, a spiral whose radius grows with the angle lands one run outward (+1), one that shrinks one
    run inward (-1). geometry()'s shape statistic can be fooled by an off-center outline (PHerc0139: +1, while
    these tracks and the references say -1). Returns {"hand", "outward", "inward", "tracks"}."""
    H, W = S.shape
    nr = int(p.get("track_rays", 1440))
    tt = np.arange(p["r_min"], p.get("track_r_max", 3300.0), 0.5)
    cent = []
    for k in range(nr):
        a = 2 * math.pi * k / nr
        X = np.rint(cx + math.cos(a) * tt).astype(int)
        Y = np.rint(cy + math.sin(a) * tt).astype(int)
        inb = (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
        v = np.zeros(len(tt), bool)
        v[inb] = S[Y[inb], X[inb]]
        st = np.flatnonzero(v[1:] & ~v[:-1]) + 1
        en = np.flatnonzero(~v[1:] & v[:-1]) + 1
        if len(v) and v[0]:
            st = np.r_[0, st]
        if len(v) and v[-1]:
            en = np.r_[en, len(v) - 1]
        n = min(len(st), len(en))
        st, en = st[:n], np.minimum(en[:n], len(tt) - 1)
        c = 0.5 * (tt[st] + tt[en])
        cent.append(c[(tt[en] - tt[st]) <= p.get("track_max_width", 12.0)])     # thin runs: sheets, not blobs
    steps = []
    lo, hi = p.get("track_r_lo", 300.0), p.get("track_r_hi", 2600.0)
    for s0 in range(0, nr, max(1, nr // 24)):
        c0 = cent[s0]
        for i0, r0 in enumerate(c0):
            if not (lo <= r0 <= hi):
                continue
            cur, vel, miss, ok = r0, 0.0, 0, True
            for k in range(1, nr + 1):
                c = cent[(s0 + k) % nr]
                pred = cur + vel
                if len(c):
                    j = int(np.argmin(np.abs(c - pred)))
                    if abs(c[j] - pred) < 3.0:
                        vel = 0.5 * vel + 0.5 * (c[j] - cur)
                        cur, miss = c[j], 0
                        continue
                miss += 1
                cur = pred
                if miss > 12:
                    ok = False
                    break
            if not ok:
                continue
            j = int(np.argmin(np.abs(c0 - cur)))
            if abs(c0[j] - cur) <= 4:
                steps.append(j - i0)
    steps = np.asarray(steps, int)
    out_, in_ = int((steps == 1).sum()), int((steps == -1).sum())
    return {"hand": 1 if out_ >= in_ else -1, "outward": out_, "inward": in_, "tracks": int(len(steps))}


def flip_hand(geo):
    """The same geometry with the other hand: theta' -> mod(-theta'), same start ray, so the pieces stay as cut;
    continuity shifts are recomputed from their end pixels (radial shifts follow from theta' when solving)."""
    g = dict(geo)
    th = np.mod(-geo["theta_p"], 2 * math.pi)
    th[th >= 2 * math.pi] = 0.0
    g["theta_p"] = th
    g["hand"] = -int(geo["hand"])
    pc = geo["pieces"]
    cont = []
    for a_, b_, _s in geo["cont"]:
        d = th[pc[b_][0]] - th[pc[a_][-1]]
        cont.append((a_, b_, 1 if d < -math.pi else (-1 if d > math.pi else 0)))
    g["cont"] = cont
    g["bridges"] = [(a_, b_, -s_) for a_, b_, s_ in geo.get("bridges", [])]
    return g


def with_hand(geo, hand):
    return geo if hand is None or int(hand) == int(geo["hand"]) else flip_hand(geo)


# ---------------------------------------------------------------- naive baseline

def naive_counts(S, ys, xs, cx, cy, r_min, step=0.5):
    """Number of sheet runs crossed on the straight ray from r_min to each pixel."""
    H, W = S.shape
    out = np.zeros(len(ys), np.int64)
    B = 4096
    for s in range(0, len(ys), B):
        y, x = ys[s:s + B].astype(float), xs[s:s + B].astype(float)
        dx, dy = x - cx, y - cy
        R = np.hypot(dx, dy)
        ux, uy = dx / np.maximum(R, 1e-9), dy / np.maximum(R, 1e-9)
        n = int(np.ceil((R.max() - r_min) / step)) + 1
        tt = r_min + np.arange(n) * step
        X = np.rint(cx + ux[:, None] * tt[None]).astype(int)
        Y = np.rint(cy + uy[:, None] * tt[None]).astype(int)
        ok = (tt[None] <= R[:, None] - 3) & (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
        v = np.zeros(X.shape, bool)
        v[ok] = S[Y[ok], X[ok]]
        rises = (v[:, 1:] & ~v[:, :-1]).sum(1) + v[:, 0]
        out[s:s + B] = rises
    return out


# ---------------------------------------------------------------- one slice

GEO_KEYS = ("threshold", "block_fill", "block_margin", "r_min", "piece_len", "min_piece", "radial_every",
            "tangent_half", "max_step", "march_step", "skel_snap", "spur_len", "spur_rounds", "bridge",
            "bridge_angle", "bridge_gap", "bridge_back", "rays")


def geometry(m7, cx, cy, p=PARAMS, log=print):
    """Everything that does not depend on the costs: skeleton, pieces, continuity edges, radial samples."""
    t0 = time.time()
    S = clean_slice(m7, p)
    K = skeleton(S)
    H, W = S.shape
    R, TH = polar(cx, cy, H, W)
    K &= R >= p["r_min"]
    if p.get("spur_len", 0):
        K = prune_spurs(K, int(p["spur_len"]), int(p.get("spur_rounds", 2)))
    ys, xs, A, idx = skel_graph(K)
    deg = np.asarray(A.sum(axis=1)).ravel()
    th = TH[ys, xs]
    pl = paths(A, deg)
    log(f"skeleton {len(ys)} px, {len(pl)} paths, {time.time() - t0:.0f} s")
    T = tangents(ys, xs, pl, p["tangent_half"])
    num = 0.0
    path_len = np.zeros(len(ys))
    for q in pl:
        path_len[q] = len(q)
        if len(q) < 20:
            continue
        r_, t_ = R[ys[q], xs[q]], np.unwrap(th[q])
        num += float((np.diff(r_) * np.diff(t_)).sum())
    hand = 1 if num >= 0 else -1
    thp = np.mod(hand * th, 2 * math.pi)
    pid, pieces, cont = make_pieces(pl, thp, len(ys), p)
    br = bridges(ys, xs, A, deg, pl, pid, thp, p) if p.get("bridge") else []
    rows = radial_edges(S, K, ys, xs, pid, pieces, T, cx, cy, p)
    log(f"{len(pieces)} pieces, {len(cont)} continuity edges, {len(rows)} radial samples, hand {hand}, "
        f"{time.time() - t0:.0f} s")
    log(f"{len(br)} bridges")
    return {"S": S, "ys": ys, "xs": xs, "pid": pid, "pieces": pieces, "cont": cont, "bridges": br, "rows": rows,
            "path_len": path_len, "hand": hand, "theta_p": thp, "r": R[ys, xs], "deg": deg}


def cont_costs(geo, p=PARAMS):
    """Continuity edges with their cost: (a, b, shift, cost)."""
    cont = geo["cont"]
    plen = geo["path_len"]
    out = []
    for a, b, s in cont:
        c = p["c_cont"]
        if p.get("cont_len") and plen[geo["pieces"][a][0]] >= p["cont_len"]:
            c = p["c_cont_long"]
        if s != 0 and p.get("c_seam") is not None:
            c = p["c_seam"]
        out.append((a, b, s, c))
    return out


def _label_one_hand(geo, p, log):
    rad = radial_terms(geo, p)
    cont = cont_costs(geo, p)
    lab, comp, info = solve(len(geo["pieces"]), cont, rad, p, geo.get("bridges", ()) if p.get("bridge") else ())
    if info["status"] == 0:
        info["objective_exact"] = objective(np.nan_to_num(lab), cont, rad, p)
    info["hand"] = int(geo["hand"])
    log(f"solve {info}")
    return {"rad": rad, "lab_piece": lab, "comp_piece": comp, "label": lab[geo["pid"]],
            "comp": comp[geo["pid"]], "info": info, "geo": geo}


def label_geometry(geo, p=PARAMS, log=print):
    """Labels of one slice. p["hand"]: None keeps geometry()'s hand (a shape statistic that the scroll's
    off-center outline can fool), +1 or -1 forces one, "track" uses track_hand() (geo["track_hand"]), and
    "objective" solves both and keeps the cheaper labeling (no labels are read, but the two optima can
    be close and the cheaper one can have the wrong hand).
    The returned "geo" is the geometry actually used (theta', hand and continuity shifts)."""
    h = p.get("hand")
    if h == "track":
        h = geo["track_hand"]["hand"]              # set by the caller from track_hand() on the same slice
    if h != "objective":
        return _label_one_hand(with_hand(geo, h), p, log)
    R = [_label_one_hand(with_hand(geo, s), p, log) for s in (1, -1)]
    R.sort(key=lambda x: x["info"].get("objective_exact", math.inf))
    R[0]["info"]["hand_objectives"] = {str(x["info"]["hand"]): x["info"].get("objective_exact") for x in R}
    return R[0]


def label_slice(m7, cx, cy, p=PARAMS, log=print):
    geo = geometry(m7, cx, cy, p, log)
    out = label_geometry(geo, p, log)
    out.update(out.pop("geo"))
    return out
