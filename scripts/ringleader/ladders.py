"""Ringleader's sure pieces as relative-winding ladders for villa's spiral fit. Model output, never a reading.

    python3 scripts/ringleader/ladders.py ladders --geo RUN --out DIR [--z Z ...] [--matrix M.json] [--control]
    python3 scripts/ringleader/ladders.py grow --geo RUN --conv FITRUN --ladder DIR/relative_windings.json --out DIR

villa's spiral fit takes relative windings: point collections whose points carry `wind_a`, the number of windings
each lies outward of the collection's first point (`relative_windings.json` in the fit's dataset folder, read with
`input_use_pcl_relative`). Ringleader labels every m7 skeleton piece of a z-slice with a turn number in one solve.
This file keeps only the labels Ringleader is surest of and writes them in villa's format, so the fit can learn the
winding order from them. It never looks at ink, and it adds no new label: every `wind_a` is a Ringleader label.

`ladders` (round 1, label-free). For each slice of a Ringleader run folder (the `zNNNNN.npz` files that
`run_slices.py` or `slab3d.py` write):

    bad     the pieces touching a violated edge: a continuity edge whose label difference is not its shift, or a
            radial edge (the next sheet out) whose difference is not 1 plus the start-ray shift
    sure    a piece is sure when its graph distance, over the slice's continuity and radial edges, to the nearest
            bad piece is at least D_SURE (3); a slice with no bad piece makes every piece sure
    points  up to K (8) pixels per sure piece, spread evenly along it (both ends kept), mapped to the fit's grid
            (fit = M (x, y, z, 1) / scale; on PHerc0139 M is the catalog transform from scan 20250728140407, where
            m7 lives, to 20260102150214, and scale 4 for a fit on that scan's L2 grid), rounded to 0.001
    wind_a  the piece's Ringleader label minus the slice's smallest sure label
    order   points are numbered by theta' ascending (then r): villa's strip loss walks a collection's points in id
            order and unwraps the angle between neighbors, so the walk never crosses the start ray, and a slice
            whose neighboring points are pi or more apart is refused

One collection per slice, `winding_is_absolute` false. With `--control`, the plus-one control is written beside it:
the same points with every step between neighboring winding levels made one winding larger. A fit taught by the
control should score worse than one taught by the ladder; if it does not, the ladder's gain is not from its windings.

`grow` (round 2, optional). After a fit taught by round 1, `fitlabel.py convert` reads it as one label per piece on
the same skeleton (`--conv`). G keeps round 1's points and adds the K points of each uncertified piece whose fit label
minus its Ringleader label equals the slice's offset (the most common such difference over the sure pieces' pixels):
pieces where the taught fit and Ringleader agree. Q, its control, is the plus-one control of G's levels (shifted to
start at 0 and back). `grow` checks that round 1's ladder rebuilds exactly from `--geo` before it adds anything.

This is the method of the frozen test of 4 November 2026 (PHerc0139 z 1,960 to 2,300; see
docs/tools/ringleader.md), with the same constants. Standard library and numpy (scipy for the graph distance).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
D_SURE = 3
K = 8
VERSION = "1.1.0"


class LadderError(ValueError):
    pass


# ---------------------------------------------------------------- the sure rule

def sure_distance(d):
    """(dist, bad, lp) of one slice's labeling d (a Ringleader zNNNNN.npz as a dict). lp is each piece's label; bad
    marks pieces touching a violated continuity edge (difference != shift) or radial edge (difference != 1 +
    start-ray shift); dist is the graph distance in pieces (continuity and radial adjacency) to the nearest bad
    piece, inf where none is reachable."""
    from scipy import sparse
    from scipy.sparse import csgraph
    L, th, pid = np.asarray(d["label"], float), np.asarray(d["theta_p"], float), np.asarray(d["pid"])
    cont, rows = np.asarray(d["cont"]).reshape(-1, 3), np.asarray(d["rows"])
    npc = int(pid.max()) + 1
    lp = np.full(npc, np.nan)
    lp[pid[pid >= 0]] = L[pid >= 0]
    a = rows[:, 0].astype(np.int64)
    b = rows[:, 1].astype(np.int64)
    dth = th[b] - th[a]
    s = np.where(dth < -math.pi, 1, np.where(dth > math.pi, -1, 0))
    pa, pb = pid[a], pid[b]
    ok = (pa >= 0) & (pb >= 0)            # a radial sample off every piece is left out
    pa, pb, s = pa[ok], pb[ok], s[ok]
    rv = (lp[pb] - lp[pa]) != 1 + s
    cv = (lp[cont[:, 1]] - lp[cont[:, 0]]) != cont[:, 2]
    bad = np.zeros(npc, bool)
    bad[pa[rv]] = True
    bad[pb[rv]] = True
    bad[cont[cv, 0]] = True
    bad[cont[cv, 1]] = True
    E = np.concatenate([np.stack([pa, pb], 1), cont[:, :2]]).astype(np.int64)
    G = sparse.coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(npc, npc)).tocsr()
    G = G + G.T
    src = np.flatnonzero(bad)
    dist = csgraph.dijkstra(G, unweighted=True, indices=src, min_only=True) if len(src) else np.full(npc, np.inf)
    return np.asarray(dist, float), bad, lp


def sure_mask(d, d_sure: int = D_SURE):
    """(sure, has_px, dist, bad, lp): sure pieces are at least d_sure from every bad piece, labeled and on a pixel."""
    dist, bad, lp = sure_distance(d)
    pid = np.asarray(d["pid"])
    has_px = np.zeros(len(lp), bool)
    has_px[pid[pid >= 0]] = True
    return (dist >= d_sure) & np.isfinite(lp) & has_px, has_px, dist, bad, lp


# ---------------------------------------------------------------- points

def _invert(A):
    Li = np.linalg.inv(A[:, :3])
    return np.concatenate([Li, (-Li @ A[:, 3])[:, None]], axis=1)


class Frame:
    """fit = (M[:, :3] q + M[:, 3]) / scale, for q = (x, y, z) in the slices' frame. Computed as the frozen test
    did: the fit-to-slice affine (M inverse after the scale) is built first and then inverted, so the points round to
    0.001 exactly as there."""

    def __init__(self, matrix, scale=4.0):
        self.M = np.asarray(matrix, float)
        if self.M.shape != (3, 4):
            raise LadderError(f"the matrix is {self.M.shape}, not 3 x 4")
        self.scale = float(scale)
        S = np.zeros((3, 4))
        S[[0, 1, 2], [0, 1, 2]] = self.scale
        Mi = _invert(self.M)
        to_query = np.concatenate([Mi[:, :3] @ S[:, :3], (Mi[:, :3] @ S[:, 3] + Mi[:, 3])[:, None]], axis=1)
        self.Ainv = _invert(to_query)

    def to_fit(self, q):
        q = np.asarray(q, float)
        return q @ self.Ainv[:, :3].T + self.Ainv[:, 3]


def spread_pick(n: int, k: int = K) -> np.ndarray:
    """Up to k positions spread evenly over 0 .. n - 1 (both ends included)."""
    if n <= 0:
        return np.zeros(0, np.int64)
    return np.unique(np.rint(np.linspace(0, n - 1, min(k, n))).astype(np.int64))


def piece_pixels(pid, theta, r):
    """{piece: pixel indices ordered along the piece (theta', then r)}; pieces never cross the start ray."""
    order = np.lexsort((r, theta, pid))
    p = pid[order]
    keep = p >= 0
    order, p = order[keep], p[keep]
    cuts = np.flatnonzero(np.diff(p)) + 1
    return {int(g[0]): o for g, o in zip(np.split(p, cuts), np.split(order, cuts)) if len(g)}


def slice_points(d, z: int, frame, pieces, lp, base, k: int = K):
    """The ladder points of the given pieces on slice z: p (fit xyz, rounded to 0.001), wind_a, theta', r and piece,
    numbered by theta' ascending; None when no piece has a pixel."""
    pid = np.asarray(d["pid"])
    th = np.asarray(d["theta_p"], float)
    r = np.asarray(d["r"], float) if "r" in d else np.zeros(len(pid))
    px = piece_pixels(pid, th, r)
    idx, wa, pc = [], [], []
    for q in sorted(int(x) for x in pieces):
        o = px.get(q)
        if o is None:
            continue
        sel = o[spread_pick(len(o), k)]
        idx.append(sel)
        wa.append(np.full(len(sel), float(lp[q] - base)))
        pc.append(np.full(len(sel), q))
    if not idx:
        return None
    idx, wa, pc = np.concatenate(idx), np.concatenate(wa), np.concatenate(pc)
    xs, ys = np.asarray(d["xs"], float)[idx], np.asarray(d["ys"], float)[idx]
    q3 = np.stack([xs, ys, np.full(len(idx), float(z))], 1)
    fit = np.round(np.asarray(frame.to_fit(q3), float), 3)
    order = np.lexsort((r[idx], th[idx]))
    return {"p": fit[order], "wind_a": wa[order], "theta": th[idx][order], "r": r[idx][order], "piece": pc[order]}


def max_gap(theta) -> float:
    """Largest angle between neighboring points of the walk (theta' ascending)."""
    t = np.sort(np.asarray(theta, float))
    return float(np.diff(t).max()) if len(t) > 1 else 0.0


def collection(pts, z: int, arm: str, hand: int, next_id: int, extra=None, k: int = K, d_sure: int = D_SURE):
    points = {}
    for j in range(len(pts["wind_a"])):
        points[str(next_id + j)] = {"p": [float(v) for v in pts["p"][j]], "wind_a": float(pts["wind_a"][j]),
                                    "creation_time": 0}
    md = {"winding_is_absolute": False, "generator": f"ringleader ladders {VERSION} {arm}: sure pieces (D_SURE "
          f"{d_sure}, K {k}), points by theta' ascending", "z": int(z), "ringleader_hand": int(hand)}
    md.update(extra or {})
    return {"name": f"ringleader-{arm}-z{z:05d}", "metadata": md, "points": points}


# ---------------------------------------------------------------- ladders

def load_slices(geo: Path, zs=None) -> dict:
    """{z: slice dict} of a Ringleader run folder: the given z, or every zNNNNN.npz in it."""
    geo = Path(geo)
    if zs is None:
        zs = sorted(int(f.stem[1:]) for f in geo.glob("z*.npz"))
    if not zs:
        raise LadderError(f"no zNNNNN.npz in {geo}")
    out = {}
    for z in zs:
        f = geo / f"z{int(z):05d}.npz"
        if not f.is_file():
            raise LadderError(f"missing {f}")
        with np.load(f) as d:
            out[int(z)] = {key: d[key] for key in d.files}
    return out


def build_e(slices: dict, frame, arm: str = "E", k: int = K, d_sure: int = D_SURE):
    """Round 1 over the slices: (villa point collections document, record). Refuses a slice without a sure piece or
    a walk with a step of pi or more."""
    cols, rec, nid = {}, {"arm": arm, "D_SURE": d_sure, "K": k, "slices": {}}, 1
    for n, z in enumerate(sorted(slices), start=1):
        d = slices[z]
        sure, has_px, dist, bad, lp = sure_mask(d, d_sure)
        if not sure.any():
            raise LadderError(f"z {z}: no sure piece")
        base = float(np.nanmin(lp[sure]))
        pts = slice_points(d, z, frame, np.flatnonzero(sure), lp, base, k)
        gap = max_gap(pts["theta"])
        if gap >= math.pi:
            raise LadderError(f"z {z}: neighboring ladder points {gap:.2f} rad apart (villa needs under pi)")
        cols[str(n)] = collection(pts, z, arm, int(d["hand"]), nid, {"base_label": base}, k, d_sure)
        nid += len(pts["wind_a"])
        lv = np.unique(pts["wind_a"])
        rec["slices"][str(z)] = {"pieces": int(has_px.sum()), "bad": int(bad.sum()), "sure": int(sure.sum()),
                                 "sure_pixels": int(np.isin(d["pid"], np.flatnonzero(sure)).sum()),
                                 "pixels": int((np.asarray(d["pid"]) >= 0).sum()), "points": int(len(pts["wind_a"])),
                                 "levels": int(len(lv)), "span": float(lv.max() - lv.min()), "base_label": base,
                                 "hand": int(d["hand"]), "max_theta_gap": round(gap, 4)}
    doc = {"vc_pointcollections_json_version": "1", "collections": cols}
    rec["points"] = sum(v["points"] for v in rec["slices"].values())
    rec["collections"] = len(cols)
    return doc, rec


def plus_one_levels(doc: dict, src: str = "E", dst: str = "Q") -> dict:
    """The control: on each collection's distinct winding levels (shifted to start at 0, then back), every step
    between neighboring levels gains one winding; points of one level keep one level."""
    out = json.loads(json.dumps(doc))
    for col in out["collections"].values():
        lv = sorted({float(p["wind_a"]) for p in col["points"].values()})
        new, acc = {lv[0]: lv[0]}, 0.0
        for i in range(1, len(lv)):
            step = lv[i] - lv[i - 1]
            acc += step + 1
            new[lv[i]] = acc + lv[0]
        for p in col["points"].values():
            p["wind_a"] = new[float(p["wind_a"])]
        col["name"] = col["name"].replace(f"ringleader-{src}-", f"ringleader-{dst}-")
        col["metadata"] = dict(col["metadata"], control=f"plus_one on the winding levels of {src}")
    out["kit"] = dict(out.get("kit", {}), control="plus_one")
    return out


def piece_label(lab_px, pid, npc):
    """Per piece, its label (fitlabel.py writes one label per piece; NaN where none)."""
    out = np.full(npc, np.nan)
    ok = (pid >= 0) & np.isfinite(lab_px)
    out[pid[ok]] = lab_px[ok]
    return out


def points_of(doc):
    return sorted((tuple(p["p"]), p["wind_a"]) for c in doc["collections"].values() for p in c["points"].values())


def build_g(slices: dict, conv: dict, frame, e_doc: dict, k: int = K, d_sure: int = D_SURE):
    """Round 2 from one taught fit read by fitlabel.py (conv): round 1's points plus the K points of each
    uncertified piece whose fit label equals its Ringleader label up to the slice's offset. Checks that round 1
    rebuilds e_doc exactly. (doc, record)."""
    rebuilt, _ = build_e(slices, frame, "E", k, d_sure)
    if points_of(rebuilt) != points_of(e_doc):
        raise LadderError("the round 1 ladder does not rebuild from this geometry")
    cols, rec, nid = {}, {"arm": "G", "slices": {}}, 1
    for n, z in enumerate(sorted(slices), start=1):
        if z not in conv:
            raise LadderError(f"z {z}: no fitlabel conversion")
        d, c = slices[z], conv[z]
        if not (np.array_equal(d["ys"], c["ys"]) and np.array_equal(d["xs"], c["xs"])
                and np.array_equal(d["pid"], c["pid"])):
            raise LadderError(f"z {z}: the conversion is not on this geometry's pixels")
        pid = np.asarray(d["pid"])
        sure, has_px, dist, bad, lp = sure_mask(d, d_sure)
        base = float(np.nanmin(lp[sure]))
        cl = np.asarray(c["label"], float)
        fl = piece_label(cl, pid, len(lp))
        sp = np.isin(pid, np.flatnonzero(sure)) & np.isfinite(cl)
        diff = (cl - np.asarray(d["label"], float))[sp]
        if not len(diff):
            raise LadderError(f"z {z}: the fit labels no sure pixel")
        v, cnt = np.unique(diff, return_counts=True)
        off = float(v[cnt.argmax()])
        unc = ~sure & np.isfinite(lp) & has_px
        agree = unc & np.isfinite(fl) & (fl - lp == off)
        pts = slice_points(d, z, frame, np.flatnonzero(sure | agree), lp, base, k)
        gap = max_gap(pts["theta"])
        if gap >= math.pi:
            raise LadderError(f"z {z}: neighboring ladder points {gap:.2f} rad apart (villa needs under pi)")
        cols[str(n)] = collection(pts, z, "G", int(d["hand"]), nid, {"base_label": base, "offset": off,
                                                                     "fit_hand": int(c["hand"])}, k, d_sure)
        nid += len(pts["wind_a"])
        rec["slices"][str(z)] = {"sure": int(sure.sum()), "uncertified": int(unc.sum()), "agree": int(agree.sum()),
                                 "offset": off, "offset_share": float(cnt.max() / max(cnt.sum(), 1)),
                                 "points": int(len(pts["wind_a"])), "fit_hand": int(c["hand"]),
                                 "ringleader_hand": int(d["hand"]), "max_theta_gap": round(gap, 4)}
    doc = {"vc_pointcollections_json_version": "1", "collections": cols}
    rec["points"] = sum(v["points"] for v in rec["slices"].values())
    rec["agree"] = sum(v["agree"] for v in rec["slices"].values())
    rec["uncertified"] = sum(v["uncertified"] for v in rec["slices"].values())
    return doc, rec


# ---------------------------------------------------------------- command line

def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path: Path, obj) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")) + "\n")
    return sha256_file(path)


def frame_from(a) -> Frame:
    if a.matrix:
        M = np.asarray(json.loads(Path(a.matrix).read_text())["matrix"], float)
    else:
        sys.path.insert(0, str(HERE.parent))
        import rlcommon
        P = rlcommon.P0139
        M = rlcommon.catalog_matrix(P["sample"], P["from"], P["to"], a.catalog)
    return Frame(M, a.fit_scale)


def check_excluded(zs, text):
    sys.path.insert(0, str(HERE.parent))
    import rlcommon
    rlcommon.check_z(zs, rlcommon.parse_ranges(text))


def cmd_ladders(a) -> int:
    slices = load_slices(Path(a.geo), a.z)
    check_excluded(list(slices), a.exclude_z)
    e, rec = build_e(slices, frame_from(a), "E", a.k, a.d_sure)
    out = Path(a.out)
    rec["version"] = VERSION
    rec["files"] = {"E": {"file": "relative_windings.json", "sha256": write_json(out / "relative_windings.json", e)}}
    if a.control:
        q = plus_one_levels(e, "E", "Q")
        rec["files"]["Q"] = {"file": "relative_windings_control.json",
                             "sha256": write_json(out / "relative_windings_control.json", q)}
    rec["geometry"] = {f"z{z:05d}.npz": sha256_file(Path(a.geo) / f"z{z:05d}.npz") for z in sorted(slices)}
    (out / "ladders.json").write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps({k: rec[k] for k in ("points", "collections", "files")}), flush=True)
    return 0


def cmd_grow(a) -> int:
    e_doc = json.loads(Path(a.ladder).read_text())
    zs = sorted(int(c["metadata"]["z"]) for c in e_doc["collections"].values())
    slices = load_slices(Path(a.geo), zs)
    conv = load_slices(Path(a.conv), zs)
    g, rec = build_g(slices, conv, frame_from(a), e_doc, a.k, a.d_sure)
    q = plus_one_levels(g, "G", "Q")
    out = Path(a.out)
    rec["version"] = VERSION
    rec["files"] = {"G": {"file": "relative_windings_grown.json",
                          "sha256": write_json(out / "relative_windings_grown.json", g)},
                    "Q": {"file": "relative_windings_grown_control.json",
                          "sha256": write_json(out / "relative_windings_grown_control.json", q)}}
    rec["round1_sha256"] = sha256_file(a.ladder)
    (out / "grow.json").write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps({k: rec[k] for k in ("points", "agree", "uncertified", "files")}), flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--geo", required=True, help="a Ringleader run folder (its zNNNNN.npz files)")
        p.add_argument("--out", required=True, help="output folder (created)")
        p.add_argument("--matrix", help='JSON {"matrix": 3 x 4} from the slices\' frame to the fit\'s scan voxels '
                       "(default: PHerc0139's catalog transform from 20250728140407 to 20260102150214)")
        p.add_argument("--catalog", help="catalog metadata.json (path or URL) for the default matrix")
        p.add_argument("--fit-scale", type=float, default=4.0, help="scan voxels per fit-grid voxel (default 4, L2)")
        p.add_argument("--k", type=int, default=K, help=f"points per sure piece (default {K})")
        p.add_argument("--d-sure", type=int, default=D_SURE, help=f"sure distance in pieces (default {D_SURE})")
        p.add_argument("--exclude-z", default=None, help="z ranges never to use, lo:hi,lo:hi or a file of them")

    p = sub.add_parser("ladders", help="round 1: sure pieces as villa relative windings (label-free)")
    common(p)
    p.add_argument("--z", type=int, nargs="*", default=None, help="the slices to use (default: every zNNNNN.npz)")
    p.add_argument("--control", action="store_true", help="also write the plus-one control")
    p = sub.add_parser("grow", help="round 2: add pieces where a taught fit agrees with Ringleader")
    common(p)
    p.add_argument("--conv", required=True, help="fitlabel.py convert's output folder for the taught fit")
    p.add_argument("--ladder", required=True, help="round 1's relative_windings.json")
    a = ap.parse_args(argv)
    if a.k < 1 or a.d_sure < 1:
        ap.error("--k and --d-sure must be at least 1")
    try:
        return cmd_ladders(a) if a.cmd == "ladders" else cmd_grow(a)
    except LadderError as e:
        print(f"ladders: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
