"""Label a stack of m7 z-slices in one solve, with sheet continuity across z. Model output.

Each slice keeps slicelab's pieces, continuity edges and radial edges. Pieces of neighboring slices are joined
where their skeletons overlap: a skeleton pixel of slice j whose nearest skeleton pixel in slice j + 1 lies
within `z_radius` px votes for that pair of pieces; a pair with at least `z_min` votes gets a continuity edge
(label difference = the start-ray shift) costing c_z times the smaller of the two shares of the pieces' pixels
that voted for it, so a merged sheet in one slice that meets two sheets in the next ties weakly to each.

    python3 scripts/ringleader/slab3d.py --z 3000 3004 3008 3012 3016 --out work/ringleader/stack3000 [--params JSON]
    python3 scripts/ringleader/score.py work/ringleader/stack3000

This is Ringleader v1 as frozen for its tests: slicelab.PARAMS, slicelab.V1 and ZPARAMS, slices 4 apart.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import rlcommon  # noqa: E402
import run_slices  # noqa: E402
import slicelab  # noqa: E402

ZPARAMS = {"z_radius": 2.5, "z_min": 3, "c_z": 10.0}


def zlinks(A, B, p):
    """Continuity edges (piece of A, piece of B, shift, cost) between two neighboring slices' geometries."""
    tree = cKDTree(np.stack([B["xs"], B["ys"]], 1).astype(float))
    d, j = tree.query(np.stack([A["xs"], A["ys"]], 1).astype(float), distance_upper_bound=p["z_radius"])
    ok = np.isfinite(d)
    ia = np.flatnonzero(ok)
    jb = j[ok]
    pa, pb = A["pid"][ia], B["pid"][jb]
    dth = A["theta_p"][ia] - B["theta_p"][jb]
    s = np.where(dth > math.pi, 1, np.where(dth < -math.pi, -1, 0))
    keep = (pa >= 0) & (pb >= 0)
    pa, pb, s = pa[keep], pb[keep], s[keep]
    nb = int(B["pid"].max()) + 1
    u2, inv = np.unique(pa.astype(np.int64) * nb + pb, return_inverse=True)
    C = np.bincount(inv * 3 + (s + 1), minlength=3 * len(u2)).reshape(-1, 3)
    cnt, us = C.sum(1), C.argmax(1) - 1          # votes per piece pair, and the majority shift
    ua, ub = u2 // nb, u2 % nb
    la = np.array([len(q) for q in A["pieces"]])
    lb = np.array([len(q) for q in B["pieces"]])
    share = np.minimum(cnt / la[ua], cnt / np.maximum(lb[ub], 1))
    m = cnt >= p["z_min"]
    return [(int(a), int(b), int(sh), float(p["c_z"] * min(1.0, w))) for a, b, sh, w in
            zip(ua[m], ub[m], us[m], share[m])]


def solve_stack(geos, p, log=print):
    """One solve over slices [(z, geo)]: in-slice continuity and radial terms plus z links. Returns labels per
    piece (stacked), components, solver info (with the exact objective) and the piece offsets per slice."""
    base = np.cumsum([0] + [len(g["pieces"]) for _, g in geos])
    cont, rad = [], []
    for (z, g), b0 in zip(geos, base):
        cont += [(a_ + b0, b_ + b0, s, c) for a_, b_, s, c in slicelab.cont_costs(g, p)]
        rad += [(r[0] + b0, r[1] + b0, *r[2:]) for r in slicelab.radial_terms(g, p)]
    nz = 0
    for k in range(len(geos) - 1):
        zl = zlinks(geos[k][1], geos[k + 1][1], p)
        nz += len(zl)
        cont += [(a_ + base[k], b_ + base[k + 1], s, c) for a_, b_, s, c in zl]
    log(f"{len(geos)} slices, {base[-1]} pieces, {len(cont) - nz} in-slice and {nz} z continuity edges, "
        f"{len(rad)} radial edges, hand {geos[0][1]['hand']}")
    lab, comp, info = slicelab.solve(int(base[-1]), cont, rad, p)
    if info["status"] == 0:
        info["objective_exact"] = slicelab.objective(np.nan_to_num(lab), cont, rad, p)
    info.update(hand=int(geos[0][1]["hand"]), z_edges=nz)
    log(json.dumps(info))
    return lab, comp, info, base


def stack_hand(geos, p, track):
    """One hand for the whole stack: forced, the geometry statistic's majority, pooled full-turn tracks
    (track(z) gives one slice's track_hand record), or "objective" (both are solved, the cheaper kept)."""
    h = p.get("hand")
    if h is None:
        return 1 if sum(g["hand"] for _, g in geos) >= 0 else -1
    if h == "track":
        th_ = [track(z) for z, _ in geos]
        out_, in_ = sum(t["outward"] for t in th_), sum(t["inward"] for t in th_)
        print(f"track hand (outward {out_}, inward {in_} over {len(th_)} slices)", flush=True)
        return 1 if out_ >= in_ else -1
    return h


def label_stack(geos, p, track=None):
    """Labels of a stack [(z, geo)] in the stack's hand: (labels, components, info, piece offsets, geometries)."""
    h = stack_hand(geos, p, track)
    tries = (1, -1) if h == "objective" else (int(h),)
    best = None
    objs = {}
    for hh in tries:
        gs = [(z, slicelab.with_hand(g, hh)) for z, g in geos]
        lab, comp, info, base = solve_stack(gs, p)
        objs[str(hh)] = info.get("objective_exact")
        if best is None or (info.get("objective_exact") or math.inf) < (best[2].get("objective_exact") or math.inf):
            best = (lab, comp, info, base, gs)
    if len(tries) > 1:
        best[2]["hand_objectives"] = objs
        print(f"hand {best[2]['hand']} kept (objectives {objs})", flush=True)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--z", type=int, nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--params", default=None, help="JSON overrides of slicelab.PARAMS and ZPARAMS (on top of "
                    "slicelab.V1)")
    ap.add_argument("--m7", default=str(run_slices.WORK / "m7"), help="folder of zNNNNN.npy slices")
    ap.add_argument("--cache", default=str(run_slices.WORK / "cache"), help="umbilicus download cache")
    ap.add_argument("--geo", default=str(run_slices.WORK / "geo"), help="geometry cache")
    ap.add_argument("--umbilicus", default=None, help="umbilicus JSON (path or URL) in the slices' frame; "
                    "default PHerc0139's, moved into the m7 frame by the catalog transform")
    ap.add_argument("--exclude-z", default=None, help="z ranges never to label, lo:hi,lo:hi or a file of them")
    a = ap.parse_args()
    zs = sorted(a.z)
    rlcommon.check_z(zs, rlcommon.parse_ranges(a.exclude_z))
    p = dict(slicelab.PARAMS, **slicelab.V1, **ZPARAMS)
    if a.params:
        p.update(json.loads(a.params))
    if p.get("bridge"):
        raise SystemExit("slab3d does not use bridge edges; run with bridge 0")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "params.json").write_text(json.dumps(p, indent=1))
    t0 = time.time()
    geos = []
    for z in zs:
        g, gk = run_slices.geo_for(z, p, a.m7, a.cache, a.geo, log=lambda m: print(f"z{z}: {m}", flush=True),
                                   umbilicus=a.umbilicus)
        geos.append((z, g))
    print(f"geometry {time.time() - t0:.0f} s", flush=True)
    lab, comp, info, base, gs = label_stack(
        geos, p, lambda z: run_slices.track_hand_for(z, p, a.m7, a.cache, a.geo, a.umbilicus))
    for (z, g), b0, b1 in zip(gs, base[:-1], base[1:]):
        lp, cp = lab[b0:b1], comp[b0:b1]
        np.savez_compressed(out / f"z{z:05d}.npz", ys=g["ys"], xs=g["xs"], label=lp[g["pid"]], comp=cp[g["pid"]],
                            pid=g["pid"], theta_p=g["theta_p"], r=g["r"], hand=g["hand"], rows=g["rows"],
                            cont=np.asarray(g["cont"], np.int64).reshape(-1, 3), naive=g["naive"],
                            path_len=g["path_len"])
    with open(out / "runs.jsonl", "a") as fh:
        fh.write(json.dumps({"z": zs, "solve": info, "pieces": int(base[-1]), "z_edges": info.get("z_edges"),
                             "seconds": round(time.time() - t0, 1)}) + "\n")


if __name__ == "__main__":
    main()
