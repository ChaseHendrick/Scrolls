"""Score every finished map of job v8in1447-ag896 and print results.json rows.

    python score.py JOB_DIR > results.json      (run from the Scrolls checkout)

AUC (kit auc) and letter-scale hp_r (kit hpscore) on the ag896 crop, 64 px edge left out,
labels at level 2, each map against its reverse-direction control."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from kit import auc as kauc, hpscore  # noqa: E402

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


# (reader, map, control, settings, seconds log, notes)
ROWS = [
    ("d9v2", "d9v2.tif", "d9v2_reverse.tif", D9, "d9v2", "pipeline check; bar 0.8230"),
    ("v8in-1447", "v8in1447_fwd_s21.npy", "v8in1447_rev_s42.npy", {**V8, "stride": 21, "control stride": 42},
     "v8in1447_fwd_s21", "main run; control is the stride 42 reverse map"),
    ("v8in-1447", "v8in1447_fwd_s42.npy", "v8in1447_rev_s42.npy", {**V8, "stride": 42, "control stride": 42},
     "v8in1447_fwd_s42", "reference at stride 42"),
    ("v8in-1447 + d9v2", "ens_v8in1447_d9v2_mean.npy", "ens_v8in1447_d9v2_mean_reverse.npy",
     {"ensemble method": "mean", "members": ["v8in1447_fwd_s21", "d9v2"], "control members": ["v8in1447_rev_s42", "d9v2_reverse"]},
     None, "kit ensemble"),
    ("v8in-1447 + d9v2", "ens_v8in1447_d9v2_rank.npy", "ens_v8in1447_d9v2_rank_reverse.npy",
     {"ensemble method": "rank", "members": ["v8in1447_fwd_s21", "d9v2"], "control members": ["v8in1447_rev_s42", "d9v2_reverse"]},
     None, "kit ensemble"),
]

out = []
for reader, m, c, settings, log, notes in ROWS:
    mp, cp = J / "maps" / m, J / "maps" / c
    if not mp.exists():
        continue
    ctrl = str(cp) if cp.exists() else None
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
    row["notes"] = notes
    out.append(row)
print(json.dumps(out, indent=1))
