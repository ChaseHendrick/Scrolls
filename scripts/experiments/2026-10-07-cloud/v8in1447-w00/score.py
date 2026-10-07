"""Score every map of job v8in1447-w00 that exists: python score.py OUT_DIR

Writes results.json (rows as in the cloud README) next to this file and prints a table.
Crop 0841-w00, 64 px edge left out, labels at level 2, reverse map as the control.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", ".."))
from kit import auc, ensemble, hpscore  # noqa: E402

OUT = sys.argv[1]
W = os.environ.get("W", os.path.expanduser("~/scrolls-work"))
LAB = f"{W}/data/0841-w00_labels"
CROP, SHAPE, VOXEL, LEVEL, INNER = (2624, 3264, 2688, 3328), (4220, 4760), 9.366, 2, 64
M = f"{OUT}/maps"
V8 = "YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062@2bf9f421862cda0ed41dcae6e8274c12e295d03a"
D9 = "d9v2_ft-012000.pth (TAUIL-Abd-Elilah v1.0, sha256 50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966)"
times = json.load(open(f"{OUT}/timings.json")) if os.path.exists(f"{OUT}/timings.json") else {}


def p(name):
    for ext in (".npy", ".tif"):
        if os.path.exists(f"{M}/{name}{ext}"):
            return f"{M}/{name}{ext}"
    return None


def ens(name, parts, method):
    paths = [p(x) for x in parts]
    if None in paths:
        return None
    out = f"{M}/{name}.tif"
    ensemble.ensemble_files(out, paths, method)
    return out


rows = []


def row(reader, fwd, rev, settings, seconds=None, notes=None):
    if fwd is None:
        return
    a = auc.score_files(fwd, f"{LAB}/inklabels.zarr", f"{LAB}/supervision.zarr", rev, level=LEVEL,
                        crop=CROP, surface_shape=SHAPE, inner=INNER)
    h = hpscore.score_files(fwd, f"{LAB}/inklabels.zarr", f"{LAB}/supervision.zarr", VOXEL, rev, level=LEVEL,
                            crop=CROP, surface_shape=SHAPE, inner=INNER)
    r = {"job": "v8in1447-w00", "segment": "0841-w00", "window": "crop", "inner_px": INNER,
         "map_from": "bare-crop", "reader": reader, "settings": settings, "device": "cpu",
         "auc_as_stored": a["forward"]["auc"], "auc_reversed": a["control"]["auc"] if rev else None,
         "hp_r": h["forward"]["hp_r"], "hp_r_reversed": h["control"]["hp_r"] if rev else None,
         "hp_null_max_abs": h["forward"]["null_max_abs"], "ink_px": a["forward"]["ink_px"],
         "seconds": seconds, "notes": notes}
    rows.append({k: v for k, v in r.items() if v is not None})


row("v8in-1447", p("v8in1447_s21"), p("v8in1447_s42_reverse"),
    {"checkpoint": V8, "stride": 21, "reverse_stride": 42, "layers": "28 exported, model reads its central 24", "batch": 4},
    times.get("v8in1447_s21"), "control is the stride 42 reverse map")
row("v8in-1447", p("v8in1447_s42"), p("v8in1447_s42_reverse"),
    {"checkpoint": V8, "stride": 42, "reverse_stride": 42, "layers": "28 exported, model reads its central 24", "batch": 4},
    times.get("v8in1447_s42"), "reference stride; reverse map seconds: %s" % times.get("v8in1447_s42_reverse"))
row("d9v2", p("d9v2"), p("d9v2_reverse"),
    {"checkpoint": D9, "code": "villa PR #1865", "overlap": 0.5, "blend": "hann"},
    times.get("d9v2_both"), "seconds cover both directions; pipeline bar 0.8994")
for method in ("mean", "rank"):
    for s in ("s21", "s42"):
        f = ens(f"ens_v8in1447_{s}+d9v2_{method}", [f"v8in1447_{s}", "d9v2"], method)
        r = ens(f"ens_v8in1447_{s}+d9v2_{method}_reverse", ["v8in1447_s42_reverse", "d9v2_reverse"], method)
        row("v8in-1447 + d9v2", f, r,
            {"ensemble": method, "v8in1447_stride": int(s[1:]), "reverse": "v8in1447 s42 reverse + d9v2 reverse",
             "maps": [V8, D9]},
            notes="kit ensemble, %s" % method)

json.dump(rows, open(f"{HERE}/results.json", "w"), indent=1)
print("| reader | settings | AUC as stored | reversed | hp_r | hp_r reversed |")
print("| --- | --- | --- | --- | --- | --- |")
for r in rows:
    s = r["settings"]
    tag = s.get("ensemble", "") + (f" s{s['stride']}" if "stride" in s else "") + (f" s{s['v8in1447_stride']}" if "v8in1447_stride" in s else "")
    print(f"| {r['reader']} | {tag.strip()} | {r['auc_as_stored']} | {r.get('auc_reversed')} | {r['hp_r']} | {r.get('hp_r_reversed')} |")
