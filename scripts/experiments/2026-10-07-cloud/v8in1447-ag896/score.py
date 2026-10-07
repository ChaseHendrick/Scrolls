"""Score every finished map of job v8in1447-ag896 and print results.json rows.

    python score.py JOB_DIR > results.json      (run from the Scrolls checkout)

AUC (kit auc) and letter-scale hp_r (kit hpscore) on the ag896 crop, 64 px edge left out,
labels at level 2, each map against its reverse-direction control."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from kit import auc as kauc, ensemble, hpscore  # noqa: E402
from controls import choose_reverse

J = Path(sys.argv[1])
W = J.parent
LAB = W / "data" / "0841-ag896_labels"
CROP = (2496, 3136, 1600, 2240)
SURFACE = (4640, 4720)
VOXEL = 9.366
V8REV = "2bf9f421862cda0ed41dcae6e8274c12e295d03a"
D9SHA = "50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966"
V8 = {"checkpoint": "YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062", "revision": V8REV,
      "layer window": "central 24 of 28 (model default)", "batch": 4}
D9 = {"checkpoint": "d9v2_ft-012000.pth (TAUIL-Abd-Elilah v1.0)", "sha256": D9SHA,
      "villa": "PR #1865", "overlap": 0.5, "blend": "hann"}


def seconds(name):
    try:
        text = (J / "logs" / f"{name}.log").read_text()
    except OSError:
        return None
    m = re.findall(r"done in (\d+)s", text)
    return int(m[-1]) if m else None


def resolve(name):
    path = J / "maps" / name
    return str(path) if path.exists() else None


reverse_name, reverse_path, reverse_stride, control_status, control_note = choose_reverse(
    resolve, "v8in1447_rev_s42.npy", "v8in1447_rev_s64.npy")


def ens(name, members, method):
    paths = [resolve(member) for member in members]
    if None in paths:
        return None
    ensemble.ensemble_files(str(J / "maps" / name), paths, method)
    return name


# (reader, map, control, settings, seconds log, notes)
ROWS = [
    ("d9v2", "d9v2.tif", "d9v2_reverse.tif", D9, "d9v2", "pipeline check; bar 0.8230"),
    ("v8in-1447", "v8in1447_fwd_s42.npy", reverse_name,
     {**V8, "stride": 42, "control stride": reverse_stride},
     "v8in1447_fwd_s42", control_note),
]
for method in ("mean", "rank"):
    forward = ens(f"ens_v8in1447_d9v2_{method}.npy", ["v8in1447_fwd_s42.npy", "d9v2.tif"], method)
    # Preserve historical reverse ensembles; matched controls get new names.
    suffix = "_s42" if reverse_stride == 42 else ""
    reverse = ens(f"ens_v8in1447_d9v2_{method}_reverse{suffix}.npy",
                  [reverse_name, "d9v2_reverse.tif"], method) if reverse_name else None
    ROWS.append(("v8in-1447 + d9v2", forward, reverse,
                 {"ensemble method": method, "members": ["v8in1447_fwd_s42", "d9v2"],
                  "control members": [reverse_name, "d9v2_reverse.tif"],
                  "v8in1447_stride": 42, "reverse_stride": reverse_stride}, None, "kit ensemble"))

out = []
for reader, m, c, settings, log, notes in ROWS:
    if m is None:
        continue
    mp = J / "maps" / m
    cp = J / "maps" / c if c else None
    if not mp.exists():
        continue
    ctrl = str(cp) if cp and cp.exists() else None
    a = kauc.score_files(str(mp), str(LAB / "inklabels.zarr"), str(LAB / "supervision.zarr"), control=ctrl,
                         level="2", crop=CROP, surface_shape=SURFACE, inner=64)
    h = hpscore.score_files(str(mp), str(LAB / "inklabels.zarr"), str(LAB / "supervision.zarr"), VOXEL, control=ctrl,
                            level="2", crop=CROP, surface_shape=SURFACE, inner=64)
    row = {"job": "v8in1447-ag896", "segment": "0841-ag896", "window": "crop", "inner_px": 64,
           "map_from": "bare-crop", "reader": reader, "map": m, "settings": settings, "device": "cpu",
           "auc_as_stored": a["forward"]["auc"], "hp_r": h["forward"]["hp_r"],
           "ink_px": a["forward"]["ink_px"]}
    if ctrl:
        row["auc_reversed"] = a["control"]["auc"]
        row["hp_r_reversed"] = h["control"]["hp_r"]
    s = seconds(log) if log else None
    if s is not None:
        row["seconds"] = s
    if reader.startswith("v8in-1447"):
        row["control_status"] = control_status if ctrl else "missing"
        row["control_note"] = control_note if ctrl else "One or more reverse control members are missing."
        if ctrl:
            row["control_map"] = c
    row["notes"] = notes
    out.append(row)
print(json.dumps(out, indent=1))
