"""Score every map of job v8in-ag896 on the crop (64 px edge left out, labels at level 2).

    W=$HOME/scrolls-work $W/venv/bin/python scripts/experiments/2026-10-07-cloud/v8in-ag896/score.py

Maps that do not exist yet are skipped, so it can run after each finished map. Writes
results.json next to this file and prints the table.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))
from kit import auc, ensemble, hpscore  # noqa: E402
from status import build_status

W = Path(os.environ.get("W", Path.home() / "scrolls-work"))
J = W / "job-v8in-ag896"
M = J / "maps"
LAB = W / "data" / "0841-ag896_labels"
SEG, CROP, SHAPE, VOXEL, INNER = "0841-ag896", (2496, 3136, 1600, 2240), (4640, 4720), 9.366, 64
V8IN_REV = "d89166b41a3f5fad7749b3d7c0fdd1bd3695d844"
D9V2_SHA = "50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966"


def path(name):
    for ext in (".npy", ".tif"):
        p = M / f"{name}{ext}"
        if p.exists():
            return p
    return None


def seconds(name):
    try:
        for line in (J / "times.txt").read_text().splitlines():
            if line.startswith(f"{name}: "):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def score(fwd, rev=None, shuf=None):
    kw = dict(crop=CROP, surface_shape=SHAPE, inner=INNER)
    lab, mask = str(LAB / "inklabels.zarr"), str(LAB / "supervision.zarr")
    a = auc.score_files(str(fwd), lab, mask, str(rev) if rev else None, **kw)
    h = hpscore.score_files(str(fwd), lab, mask, VOXEL, str(rev) if rev else None, **kw)
    out = {"auc_as_stored": a["forward"]["auc"], "ink_px": a["forward"]["ink_px"],
           "hp_r": h["forward"]["hp_r"], "hp_null_max_abs": h["forward"]["null_max_abs"]}
    if rev:
        out["auc_reversed"] = a["control"]["auc"]
        out["hp_r_reversed"] = h["control"]["hp_r"]
    if shuf:
        out["auc_shuffled"] = auc.score_files(str(shuf), lab, mask, None, **kw)["forward"]["auc"]
        out["hp_r_shuffled"] = hpscore.score_files(str(shuf), lab, mask, VOXEL, None, **kw)["forward"]["hp_r"]
    return out


def ens(names, method, reverse):
    paths = [path(n) for n in names]
    if any(p is None for p in paths):
        return None
    out = M / "ens" / f"{'+'.join(names)}_{method}{'_rev' if reverse else ''}.npy"
    out.parent.mkdir(exist_ok=True)
    ensemble.ensemble_files(str(out), [str(p) for p in paths], method)
    return out


BASE = {"job": "v8in-ag896", "segment": SEG, "window": "crop", "inner_px": INNER, "map_from": "bare-crop",
        "device": "cpu"}
V8 = {"checkpoint": "YoussefMoNader/ink-8um-v8in", "revision": V8IN_REV, "batch_size": 4,
      "layer_window": "v8in default (central 24 of 28)"}
INK = {"checkpoint": "scrollprize/ink_9um hybrid_3d2d-seed42/step-075000.pth", "villa": "PR #1865",
       "overlap": 0.5, "blend": "hann"}
D9 = {"checkpoint": "d9v2_ft-012000.pth (TAUIL-Abd-Elilah v1.0)", "sha256": D9V2_SHA, "villa": "PR #1865",
      "overlap": 0.5, "blend": "hann"}

rows = []


def add(reader, settings, fwd, rev=None, shuf=None, secs=None, notes=None):
    if fwd is None:
        return
    r = dict(BASE, reader=reader, settings=settings)
    r.update(score(fwd, rev, shuf))
    if secs is not None:
        r["seconds"] = secs
    if notes:
        r["notes"] = notes
    rows.append(r)


rev = path("v8in_s64_reverse")
shuf = path("v8in_shuf_s64")
add("v8in", dict(V8, stride=42, reverse_stride=64, shuffled_stride=64), path("v8in_s42"), rev, shuf,
    seconds("v8in_s42"), "main row: forward stride 42; controls reverse and depth-shuffled at stride 64")
add("v8in depth-shuffled", dict(V8, stride=64, shuffle_seed=20261007), shuf, None, None,
    seconds("v8in_shuf_s64"), "shuffled layers scored as a map of their own (the control)")
add("v8in reversed", dict(V8, stride=64, reverse=True), rev, None, None, seconds("v8in_s64_reverse"),
    "the reverse map scored as forward (equals auc_reversed above)")
add("ink_9um s42", INK, path("ink9um_s42"), path("ink9um_s42_reverse"), None, seconds("ink9um_s42"),
    "seconds cover both directions")
add("d9v2", D9, path("d9v2"), path("d9v2_reverse"), None, seconds("d9v2"), "seconds cover both directions")

v8f = "v8in_s42"
for others, label in ((["d9v2"], "v8in + d9v2"), (["ink9um_s42"], "v8in + ink_9um s42"),
                      (["d9v2", "ink9um_s42"], "v8in + d9v2 + ink_9um s42")):
    for method in ("mean", "rank"):
        f = ens([v8f] + others, method, False)
        r = ens(["v8in_s64_reverse"] + [o + "_reverse" for o in others], method, True)
        add(label, {"ensemble_method": method, "members": [v8f] + others,
                    "reverse_members": ["v8in_s64_reverse"] + [o + "_reverse" for o in others]},
            f, r, None, None, "map-level ensemble (kit ensemble); reverse ensembled the same way")

# Only replace reports once scoring has succeeded; existing reports survive scorer failure.
for name, payload in (("results.json", rows), ("status.json", build_status(rows))):
    temporary = HERE / (name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(HERE / name)


def fmt(v, d=4):
    return "" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))


print("| map | settings | AUC as stored | reversed | shuffled | hp_r | hp_r reversed | hp null max |")
print("| --- | --- | --- | --- | --- | --- | --- | --- |")
for r in rows:
    s = r["settings"]
    st = s.get("ensemble_method") or (f"stride {s['stride']}" if "stride" in s else "villa")
    print(f"| {r['reader']} | {st} | {fmt(r['auc_as_stored'])} | {fmt(r.get('auc_reversed'))} | "
          f"{fmt(r.get('auc_shuffled'))} | {fmt(r['hp_r'], 3)} | {fmt(r.get('hp_r_reversed'), 3)} | "
          f"{fmt(r['hp_null_max_abs'], 3)} |")

status = build_status(rows)
print("Status: " + status["status"] + "; inference completion: " + status["inference_completion"])
if status["missing_rows"]:
    print("Missing scored rows: " + ", ".join(status["missing_rows"]))
if status["missing_control_fields"]:
    print("Missing controls: " + ", ".join(status["missing_control_fields"]))
print(status["control_comparability"])
