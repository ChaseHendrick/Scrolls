"""Label whole m7 z-slices one at a time with slicelab and save the labels for score.py. Model output.

    python3 scripts/ringleader/run_slices.py --z 3000 7000 --out work/ringleader/run1 [--params '{"c_hi": 5}']
    python3 scripts/ringleader/run_slices.py --z 3000 --out work/ringleader/grid --configs CONFIGS.json   # {name: overrides}
    python3 scripts/ringleader/score.py work/ringleader/run1

The slices come from m7slices.py (--m7). The settings start from slicelab.PARAMS with slicelab.V1 on top (the
frozen v1 settings); --params overrides them. The axis is PHerc0139's published umbilicus through the catalog
transform, or --umbilicus (a villa umbilicus JSON already in the slices' frame). Geometry (skeleton, pieces, radial
samples) is cached per slice and geometry parameters in --geo.
"""

import argparse
import concurrent.futures
import hashlib
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import rlcommon  # noqa: E402
import slicelab  # noqa: E402

WORK = Path("work") / "ringleader"


def _axis_tag(umbilicus):
    """A short hash of a custom umbilicus file, so geometry cached for one axis is not reused for another."""
    if not umbilicus:
        return ""
    return "-" + hashlib.sha256(Path(umbilicus).read_bytes()).hexdigest()[:8] if Path(umbilicus).is_file() else \
        "-" + hashlib.sha256(str(umbilicus).encode()).hexdigest()[:8]


def geo_for(z, p, m7dir, cache, geodir, log=print, umbilicus=None):
    gk = hashlib.sha256(json.dumps({k: p[k] for k in slicelab.GEO_KEYS if k in p}, sort_keys=True).encode()
                        ).hexdigest()[:12] + _axis_tag(umbilicus)
    f = Path(geodir) / f"z{z:05d}-{gk}.pkl"
    if f.is_file():
        with open(f, "rb") as fh:
            return pickle.load(fh), gk
    axis = rlcommon.load_axis(cache, umbilicus)
    cx, cy = (float(v) for v in axis.at(z))
    m7 = np.load(Path(m7dir) / f"z{z:05d}.npy")
    geo = slicelab.geometry(m7, cx, cy, p, log)
    geo["axis"] = (cx, cy)
    sl = np.arange(0, len(geo["ys"]), 3)
    nv = np.full(len(geo["ys"]), np.nan)
    nv[sl] = slicelab.naive_counts(geo["S"], geo["ys"][sl], geo["xs"][sl], cx, cy, p["r_min"])
    geo["naive"] = nv
    del geo["S"]
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(geo, fh, protocol=4)
    tmp.rename(f)
    return geo, gk


def track_hand_for(z, p, m7dir, cache, geodir, umbilicus=None):
    """slicelab.track_hand on slice z, cached in geodir as zNNNNN-trackhand.json."""
    f = Path(geodir) / f"z{z:05d}{_axis_tag(umbilicus)}-trackhand.json"
    if f.is_file():
        return json.loads(f.read_text())
    axis = rlcommon.load_axis(cache, umbilicus)
    cx, cy = (float(v) for v in axis.at(z))
    S = slicelab.clean_slice(np.load(Path(m7dir) / f"z{z:05d}.npy"), p)
    h = slicelab.track_hand(S, cx, cy, p)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(h))
    return h


def label_one(z, p, out, m7dir, cache, geodir, umbilicus=None):
    t0 = time.time()
    log = lambda m: print(f"[{out.name}] z{z}: {m}", flush=True)  # noqa: E731
    geo, gk = geo_for(z, p, m7dir, cache, geodir, log, umbilicus)
    if p.get("hand") == "track":
        geo["track_hand"] = track_hand_for(z, p, m7dir, cache, geodir, umbilicus)
        log(f"track hand {geo['track_hand']}")
    R = slicelab.label_geometry(geo, p, log)
    geo = R["geo"]                      # the hand actually used (p["hand"])
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / f"z{z:05d}.npz", ys=geo["ys"], xs=geo["xs"], label=R["label"], comp=R["comp"],
                        pid=geo["pid"], theta_p=geo["theta_p"], r=geo["r"], hand=geo["hand"], rows=geo["rows"],
                        cont=np.asarray(geo["cont"], np.int64).reshape(-1, 3), naive=geo["naive"],
                        bridges=np.asarray(geo.get("bridges", []) if p.get("bridge") else [], np.int64).reshape(-1, 3),
                        rad=np.asarray(R["rad"], float).reshape(-1, 7), path_len=geo["path_len"])
    info = {"z": z, "geo": gk, "axis": list(geo["axis"]), "hand": geo["hand"], "solve": R["info"],
            "pieces": len(geo["pieces"]), "radial_edges": len(R["rad"]), "seconds": round(time.time() - t0, 1)}
    with open(out / "runs.jsonl", "a") as fh:
        fh.write(json.dumps(info) + "\n")
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--z", type=int, nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--params", default=None, help="JSON overrides of slicelab.PARAMS (on top of slicelab.V1)")
    ap.add_argument("--m7", default=str(WORK / "m7"), help="folder of zNNNNN.npy slices (default %(default)s)")
    ap.add_argument("--cache", default=str(WORK / "cache"), help="umbilicus download cache (default %(default)s)")
    ap.add_argument("--geo", default=str(WORK / "geo"), help="geometry cache (default %(default)s)")
    ap.add_argument("--umbilicus", default=None, help="umbilicus JSON (path or URL) in the slices' frame; "
                    "default PHerc0139's, moved into the m7 frame by the catalog transform")
    ap.add_argument("--exclude-z", default=None, help="z ranges never to label, lo:hi,lo:hi or a file of them")
    ap.add_argument("--configs", default=None, help="JSON file {name: overrides}; outputs in OUT/name/")
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    rlcommon.check_z(a.z, rlcommon.parse_ranges(a.exclude_z))
    base = dict(slicelab.PARAMS, **slicelab.V1)
    if a.params:
        base.update(json.loads(a.params))
    out = Path(a.out)
    cfgs = {"": {}} if not a.configs else json.loads(Path(a.configs).read_text())
    jobs = []
    for name, ov in cfgs.items():
        p = dict(base, **ov)
        d = out / name if name else out
        d.mkdir(parents=True, exist_ok=True)
        (d / "params.json").write_text(json.dumps(p, indent=1))
        jobs.extend((z, p, d) for z in a.z)
    # geometry first, one slice per worker, so parallel solves share the cache
    gp = [dict(base, **cfgs[n]) for n in cfgs]
    gsets = {}
    for p in gp:
        k = json.dumps({kk: p[kk] for kk in slicelab.GEO_KEYS if kk in p}, sort_keys=True)
        gsets[k] = p
    with concurrent.futures.ProcessPoolExecutor(a.jobs) as pool:
        list(pool.map(geo_for, *zip(*[(z, p, a.m7, a.cache, a.geo, print, a.umbilicus)
                                      for p in gsets.values() for z in a.z])))
        futs = [pool.submit(label_one, z, p, d, a.m7, a.cache, a.geo, a.umbilicus) for z, p, d in jobs]
        for f in concurrent.futures.as_completed(futs):
            print(json.dumps(f.result()), flush=True)


if __name__ == "__main__":
    main()
