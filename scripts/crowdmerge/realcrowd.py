"""kit crowdmerge on a real crowd: VC3D tracer runs from different seeds on one hand-traced PHerc0139 winding.

The planted bench (kit crowdmerge bench) plants independent slips; real tracer runs from nearby seeds follow the same
surface prediction, so their slips may sit at the same contacts. This script picks the seeds by a fixed rule and
scores the merged result against the hand trace, as frozen in docs/prereg/2026-10-25-crowdmerge-real-crowd.md.
PHerc0139 is public and on no prize list; the traces are mesh geometry only.

  python scripts/crowdmerge/realcrowd.py seeds [--windings w027 w037] [--agent DIR] [--json]
  python scripts/crowdmerge/realcrowd.py score TRACES [--out FILE]     # TRACES/<winding>/<k>/{x,y,z}.tif

Needs numpy, scipy and tifffile, and `python -m kit hopbench refs` first.
"""

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kit import crowdmerge as cm  # noqa: E402
from kit import sheetrefs as sr  # noqa: E402

WINDINGS = ("w027", "w037")
SEEDS = 7
CANDIDATES = 14   # with --agent: the 7 angles first, then the 7 between them, until SEEDS pass the tracer's check
RADIUS_MM = 3.0
ON_VOX, SLIP_VOX, OFF_VOX = 2.0, 6.0, 4.0
COVER_VOX = 4.0
MIN_TRACE_CM2 = 1.0
SHIFT_VOX = 6
PREDICTION = ("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/representations/predictions/"
              "surfaces/20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr/")
CT = ("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/"
      "20250728140407-9.362um-1.2m-113keV-masked.zarr/")
BARS = {"off_vs_largest_max": 0.5, "coverage_vs_largest_min": 0.9, "flag_recall_min": 0.8,
        "flag_precision_min": 0.8, "void_slipped_share_min": 0.02, "void_traces_min": 4, "control_ratio_min": 5.0}


def _np():
    return sr._np()


def seeds(refs, man, names=WINDINGS):
    """Per winding: the centre (the middle cell of its first bench contact site) and points on a RADIUS_MM circle
    around it, each the nearest labelled vertex of the hand trace, in level-0 voxels (x, y, z): "seeds" at SEEDS
    equal angles, "candidates" at CANDIDATES equal angles with those SEEDS first."""
    np = _np()
    R = {r.name: r for r in refs}
    out = {}
    for name in names:
        A = R[name]
        st = cm.sites(refs, man, [name], np.random.default_rng(cm.SEED))
        if not st:
            raise sr.BenchError(f"{name} has no contact site")
        win = st[0][2]
        c = np.array([(win[0].start + win[0].stop) // 2, (win[1].start + win[1].stop) // 2])
        lab = np.argwhere(A.labelled())
        cells = RADIUS_MM * 1000.0 / sr.VOXEL_UM / A.step
        pts = []
        step = CANDIDATES // SEEDS
        for k in [k for k in range(CANDIDATES) if k % step == 0] + [k for k in range(CANDIDATES) if k % step]:
            t = 2 * math.pi * k / CANDIDATES
            want = c + cells * np.array([math.sin(t), math.cos(t)])
            rc = lab[int(np.argmin(((lab - want) ** 2).sum(1)))]
            pts.append([int(round(float(v))) for v in A.xyz[rc[0], rc[1]]])
        out[name] = {"neighbour": st[0][1].name, "centre_cell": c.tolist(), "radius_cells": round(cells, 2),
                     "seeds": pts[:SEEDS], "candidates": pts}
    return out


def seed_check(agent, xyz):
    """Headless VC3D's seed_check (the tracer's own gate): on the m7 prediction and on papyrus in the CT."""
    out = subprocess.run([sys.executable, "-m", "kit", "vc3d", "call", "seed_check",
                          json.dumps({"volume": PREDICTION, "seed": list(xyz), "ct": CT})],
                         cwd=agent, capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        raise sr.BenchError(f"seed_check failed: {out.stderr[-500:]}")


def checked(A, xyz, agent):
    """Move a seed along A's normal to the nearest point (whole voxels, up to SHIFT_VOX, the + side first on a tie)
    that the tracer's seed_check accepts. Returns (point, shift) or (None, None)."""
    np = _np()
    _, _, _, n = sr.match(np.array([xyz], float), A)
    n = n[0] / (np.linalg.norm(n[0]) or 1.0)
    for d in sorted(range(-SHIFT_VOX, SHIFT_VOX + 1), key=lambda d: (abs(d), -d)):
        q = [int(round(float(v))) for v in np.array(xyz, float) + d * n]
        if seed_check(agent, q).get("ok"):
            return q, d
    return None, None


def _cover(A, P, valid, workers=2):
    """Labelled vertices of A within COVER_VOX of the surface (densified to about 2 voxels)."""
    np = _np()
    up, _, _, ok, _, _ = cm._densify(P, valid, 2.0)
    if not ok.any():
        return 0
    d, _ = cm._tree(up[ok]).query(A.xyz[A.labelled()], distance_upper_bound=COVER_VOX, workers=workers)
    return int(np.isfinite(d).sum())


def _area_cm2(P, valid):
    np = _np()
    a = np.linalg.norm(np.cross(P[1:, :-1] - P[:-1, :-1], P[:-1, 1:] - P[:-1, :-1]), axis=-1)
    m = valid[1:, 1:] & valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:]
    return float(a[m].sum()) * (sr.VOXEL_UM * 1e-4) ** 2


def score_winding(A, neighbours, traces, workers=2, log=None):
    """One winding: the crowd's truth against A, the vote and mean consensus, the largest trace, the flags and the
    neighbour control. `traces` is a list of (name, xyz, valid)."""
    np = _np()
    row = {"winding": A.name, "traces": {}}
    for name, P, v in traces:
        off, m = cm._off_share(P[v], A)
        s, ins, _, _ = sr.match(P[v], A)
        ok = ins & np.isfinite(s)
        row["traces"][name] = {"vertices": int(v.sum()), "area_cm2": round(_area_cm2(P, v), 3), "off": off,
                               "matched": m, "slipped": int((ok & (np.abs(s) > SLIP_VOX)).sum()),
                               "cover": _cover(A, P, v, workers)}
    row["grown_traces"] = sum(t["area_cm2"] >= MIN_TRACE_CM2 for t in row["traces"].values())
    big = max(traces, key=lambda t: int(t[2].sum()))
    row["largest"] = big[0]
    for method in ("vote", "mean"):
        t0 = time.time()
        r = cm.merge(traces, method=method, workers=workers)
        X, V = r["xyz"], r["valid"]
        off, m = cm._off_share(X[V], A)
        arm = {"off": off, "matched": m, "cover": _cover(A, X, V, workers), "seconds": round(time.time() - t0, 1)}
        if method == "vote":
            fl = {"tp": 0, "fp": 0, "fn": 0, "fn_outside": 0, "on": 0, "on_flagged": 0, "slipped": 0}
            for name, P, v in traces:
                f = r["flags"][name][v]
                s, ins, _, _ = sr.match(P[v], A)
                ok = ins & np.isfinite(s)
                sl, on = ok & (np.abs(s) > SLIP_VOX), ok & (np.abs(s) < ON_VOX)
                fl["tp"] += int((sl & (f == 2)).sum())
                fl["fn"] += int((sl & (f != 2)).sum())
                fl["fn_outside"] += int((sl & (f == 0)).sum())
                fl["fp"] += int((on & (f == 2)).sum())
                fl["on"] += int((on & (f > 0)).sum())
                fl["on_flagged"] += int((on & (f == 2)).sum())
                fl["slipped"] += int(sl.sum())
            arm["flags"] = fl
            near = {}
            for B in neighbours:
                s, ins, _, _ = sr.match(X[V], B)
                near[B.name] = int((ins & np.isfinite(s) & (np.abs(s) <= OFF_VOX)).sum())
            arm["on_A"] = m - off
            arm["on_neighbours"] = near
            arm["summary"] = {k: r["summary"][k] for k in ("vertices", "grown_vertices", "moved_share",
                                                            "contested_share", "single_trace_share")}
        row[method] = arm
        if log:
            log(f"{A.name} {method}: off {off}/{m}, cover {arm['cover']}, {arm['seconds']} s")
    return row


def _share(a, b):
    return round(a / b, 4) if b else None


def tally(rows):
    """Pooled shares over the windings and the verdict (pure; tested)."""
    tot = lambda f: sum(f(r) for r in rows)  # noqa: E731
    big = lambda r: r["traces"][r["largest"]]  # noqa: E731
    t = {"windings": len(rows)}
    t["vote_off"] = _share(tot(lambda r: r["vote"]["off"]), tot(lambda r: r["vote"]["matched"]))
    t["mean_off"] = _share(tot(lambda r: r["mean"]["off"]), tot(lambda r: r["mean"]["matched"]))
    t["largest_off"] = _share(tot(lambda r: big(r)["off"]), tot(lambda r: big(r)["matched"]))
    t["crowd_off"] = _share(tot(lambda r: sum(x["off"] for x in r["traces"].values())),
                            tot(lambda r: sum(x["matched"] for x in r["traces"].values())))
    t["crowd_slipped_share"] = _share(tot(lambda r: sum(x["slipped"] for x in r["traces"].values())),
                                      tot(lambda r: sum(x["matched"] for x in r["traces"].values())))
    t["best_trace_off"] = {r["winding"]: min(_share(x["off"], x["matched"]) or 0 for x in r["traces"].values()
                                             if x["matched"]) for r in rows}
    t["coverage_vs_largest"] = _share(tot(lambda r: r["vote"]["cover"]), tot(lambda r: big(r)["cover"]))
    f = {k: tot(lambda r, k=k: r["vote"]["flags"][k]) for k in ("tp", "fp", "fn", "fn_outside", "on",
                                                              "on_flagged", "slipped")}
    t["flags"] = f
    t["flag_recall"] = _share(f["tp"], f["tp"] + f["fn"])
    t["flag_precision"] = _share(f["tp"], f["tp"] + f["fp"])
    t["missed_outside_share"] = _share(f["fn_outside"], f["fn"])
    t["control_ratio"] = {r["winding"]: _share(r["vote"]["on_A"], max(max(r["vote"]["on_neighbours"].values() or [0]),
                                                                      1)) for r in rows}
    void = []
    if (t["crowd_slipped_share"] or 0) < BARS["void_slipped_share_min"]:
        void.append(f"the crowd slipped on {t['crowd_slipped_share']} of its vertices, under "
                    f"{BARS['void_slipped_share_min']}: nothing to correct")
    for r in rows:
        if r["grown_traces"] < BARS["void_traces_min"]:
            void.append(f"{r['winding']}: {r['grown_traces']} traces grew to {MIN_TRACE_CM2} cm2")
        if (t["control_ratio"][r["winding"]] or 0) < BARS["control_ratio_min"]:
            void.append(f"{r['winding']}: neighbour control ratio {t['control_ratio'][r['winding']]} under "
                        f"{BARS['control_ratio_min']}")
    checks = {
        "off_vs_largest": t["vote_off"] is not None and t["largest_off"] is not None
        and t["vote_off"] <= BARS["off_vs_largest_max"] * t["largest_off"],
        "coverage_vs_largest": (t["coverage_vs_largest"] or 0) >= BARS["coverage_vs_largest_min"],
        "flag_recall": (t["flag_recall"] or 0) >= BARS["flag_recall_min"],
        "flag_precision": (t["flag_precision"] or 0) >= BARS["flag_precision_min"],
    }
    t["checks"] = checks
    t["void"] = void
    t["verdict"] = "VOID" if void else ("PASS" if all(checks.values()) else "FAIL")
    return t


def load_crowd(folder):
    out = []
    for d in sorted(p for p in Path(folder).iterdir() if (p / "x.tif").is_file()):
        xyz, valid, _ = sr.read_tifxyz(str(d))
        out.append((d.name, xyz, valid))
    return out


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("seeds", help="the preregistered seed points")
    a.add_argument("--windings", nargs="+", default=list(WINDINGS))
    a.add_argument("--refs", default=str(sr.DEFAULT_REFS))
    a.add_argument("--agent", help="Headless VC3D folder: move each seed to where its seed_check passes")
    a.add_argument("--json", action="store_true")
    a = sub.add_parser("score", help="merge and score each winding's crowd")
    a.add_argument("traces", help="folder with one subfolder per winding, one tifxyz folder per trace in each")
    a.add_argument("--refs", default=str(sr.DEFAULT_REFS))
    a.add_argument("--out", help="report JSON (default TRACES/realcrowd.json)")
    a.add_argument("--workers", type=int, default=2)
    a = p.parse_args(argv)
    man, refs = sr.load_refs(a.refs)
    if a.cmd == "seeds":
        res = seeds(refs, man, a.windings)
        if a.agent:
            R = {r.name: r for r in refs}
            for name, r in res.items():
                r["checked"], r["shift_vox"], r["from_candidate"] = [], [], []
                for i, s in enumerate(r["candidates"]):
                    q, d = checked(R[name], s, a.agent)
                    if q is not None:
                        r["checked"].append(q)
                        r["shift_vox"].append(d)
                        r["from_candidate"].append(i)
                    if len(r["checked"]) == SEEDS:
                        break
        if a.json:
            print(json.dumps(res, indent=1))
        else:
            for name, r in res.items():
                for k, s in enumerate(r.get("checked") or r["seeds"]):
                    if s is not None:
                        print(name, k, *s)
        return 0
    R = {r.name: r for r in refs}
    rows = []
    for d in sorted(Path(a.traces).iterdir()):
        if d.name not in R:
            continue
        crowd = load_crowd(d)
        if len(crowd) < 2:
            _log(f"{d.name}: {len(crowd)} traces, skipped")
            continue
        A = R[d.name]
        rows.append(score_winding(A, sr._neighbours_of(A, refs, man), crowd, a.workers, _log))
    rep = {"kind": "crowdmerge-real-crowd", "settings": cm.SETTINGS, "bars": BARS, "rows": rows,
           "tally": tally(rows), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    out = Path(a.out) if a.out else Path(a.traces) / "realcrowd.json"
    out.write_text(json.dumps(rep, indent=1) + "\n")
    t = rep["tally"]
    print(f"real crowd: {t['windings']} windings, verdict {t['verdict']}")
    print(f"  off sheet: vote {t['vote_off']}, mean {t['mean_off']}, largest trace {t['largest_off']}, "
          f"crowd {t['crowd_off']} (slipped {t['crowd_slipped_share']})")
    print(f"  coverage vs largest {t['coverage_vs_largest']}; flags recall {t['flag_recall']}, precision "
          f"{t['flag_precision']}")
    for v in t["void"]:
        print(f"  void: {v}")
    print(f"  report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
