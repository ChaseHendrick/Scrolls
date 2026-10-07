"""Score job v8in-w00's maps on the 0841-w00 crop and write results.json next to this file.

    python score.py [WORKDIR]     (default ~/scrolls-work/job-v8in-w00; runs whatever maps exist)

Every map is scored with kit auc and kit hpscore on the crop, 64 px edge left out, labels at
level 2. Ensembles of the forward maps get the reverse maps ensembled the same way as control.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", ".."))
from kit import auc, ensemble, hpscore

O = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/scrolls-work/job-v8in-w00")
W = os.path.dirname(O)
M = f"{O}/maps"
LAB = f"{W}/data/0841-w00_labels"
CROP, SHAPE, VOX = (2624, 3264, 2688, 3328), (4220, 4760), 9.366
TIMES = {}
if os.path.exists(f"{O}/times.txt"):
    for line in open(f"{O}/times.txt"):
        k, v = line.split()
        TIMES[k] = int(v)

V8 = "YoussefMoNader/ink-8um-v8in d89166b41a3f5fad7749b3d7c0fdd1bd3695d844"
D9 = "TAUIL v1.0 d9v2_ft-012000 (sha256 50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966), villa PR #1865, overlap 0.5, hann"
IK = "scrollprize/ink_9um hybrid_3d2d-seed42 step-075000, villa PR #1865, overlap 0.5, hann"

def p(name):
    for ext in (".npy", ".tif"):
        if os.path.exists(f"{M}/{name}{ext}"):
            return f"{M}/{name}{ext}"
    return None

def score(fwd, rev=None, shuf=None):
    kw = dict(crop=CROP, surface_shape=SHAPE, inner=64)
    a = auc.score_files(fwd, f"{LAB}/inklabels.zarr", f"{LAB}/supervision.zarr", rev, **kw)
    h = hpscore.score_files(fwd, f"{LAB}/inklabels.zarr", f"{LAB}/supervision.zarr", VOX, rev, **kw)
    r = {"auc_as_stored": round(a["forward"]["auc"], 4), "ink_px": a["forward"]["ink_px"],
         "hp_r": None if h["forward"]["hp_r"] is None else round(h["forward"]["hp_r"], 4),
         "hp_null_max_abs": round(h["forward"]["null_max_abs"], 4)}
    if rev:
        r["auc_reversed"] = round(a["control"]["auc"], 4)
        r["hp_r_reversed"] = None if h["control"]["hp_r"] is None else round(h["control"]["hp_r"], 4)
    if shuf:
        s = auc.score_files(shuf, f"{LAB}/inklabels.zarr", f"{LAB}/supervision.zarr", None, **kw)
        r["auc_shuffled"] = round(s["forward"]["auc"], 4)
    return r

def row(reader, settings, fwd, rev=None, shuf=None, seconds=None, notes=None):
    r = {"job": "v8in-w00", "segment": "0841-w00", "window": "crop", "inner_px": 64,
         "map_from": "bare-crop", "reader": reader, "settings": settings, "device": "cpu"}
    r.update(score(fwd, rev, shuf))
    if seconds is not None:
        r["seconds"] = seconds
    if notes:
        r["notes"] = notes
    print(f"{reader:34s} fwd {r['auc_as_stored']:.4f} rev {r.get('auc_reversed', float('nan')):.4f} "
          f"shuf {r.get('auc_shuffled', float('nan')):.4f} hp {r['hp_r']} / {r.get('hp_r_reversed')}", flush=True)
    return r

rows = []
for name, label, settings in (("ink9um_s42", "ink_9um seed 42", IK), ("d9v2", "d9v2", D9)):
    if p(name) and p(name + "_reverse"):
        rows.append(row(label, settings, p(name), p(name + "_reverse"), seconds=TIMES.get(name),
                        notes="seconds cover both directions"))
rev42, shuf42 = p("v8in_s42_reverse"), p("v8in_shuf_s42")
if p("v8in_s21"):
    rows.append(row("v8in", f"{V8}, forward stride 21, reverse stride 42, batch 4", p("v8in_s21"), rev42, shuf42,
                    seconds=TIMES.get("v8in_s21"),
                    notes="seconds: forward pass only; shuffled: depth-shuffled layers (kit layers --shuffle 20261007) forward at stride 42"))
if p("v8in_s42"):
    rows.append(row("v8in (stride 42 reference)", f"{V8}, forward stride 42, reverse stride 42, batch 4", p("v8in_s42"), rev42, shuf42,
                    seconds=TIMES.get("v8in_s42"), notes="seconds: forward pass only"))
if shuf42:
    rows.append(row("v8in depth-shuffled", f"{V8}, layers shuffled with seed 20261007, forward stride 42, batch 4", shuf42,
                    seconds=TIMES.get("v8in_shuf_s42"), notes="the shuffle control scored as a map on its own"))
v8f = p("v8in_s21")
ens = {"v8in + d9v2": ["d9v2"], "v8in + ink_9um": ["ink9um_s42"], "v8in + d9v2 + ink_9um": ["d9v2", "ink9um_s42"]}
os.makedirs(f"{O}/ens", exist_ok=True)
for label, others in ens.items():
    if not (v8f and rev42 and all(p(o) and p(o + "_reverse") for o in others)):
        continue
    for method in ("mean", "rank"):
        tag = "+".join(["v8in"] + others) + "_" + method
        f = ensemble.ensemble_files(f"{O}/ens/{tag}.npy", [v8f] + [p(o) for o in others], method)["out"]
        r = ensemble.ensemble_files(f"{O}/ens/{tag}_reverse.npy", [rev42] + [p(o + "_reverse") for o in others], method)["out"]
        rows.append(row(f"{label} ({method})", f"kit ensemble --method {method}; v8in forward stride 21, reverse stride 42; villa maps both directions",
                        f, r, notes="reverse maps ensembled the same way as the control"))
json.dump(rows, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print(f"{len(rows)} rows -> results.json; reverse v8in s42 took {TIMES.get('v8in_s42_reverse')} s")
