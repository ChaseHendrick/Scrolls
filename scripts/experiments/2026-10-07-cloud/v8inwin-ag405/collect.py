"""Fold the score JSONs of score.sh into results.json rows (README "Result rows" format).

    python collect.py SCORES_DIR LOGS_DIR results.json
"""
import json
import re
import sys
from pathlib import Path

scores, logs, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
REV = "d89166b41a3f5fad7749b3d7c0fdd1bd3695d844"


def seconds(name):
    p = logs / f"{name}.log"
    if not p.exists():
        return None
    m = re.search(r"done in (\d+)s", p.read_text())
    return int(m.group(1)) if m else None


def pick(d, *keys):
    for k in keys:
        if k in d:
            return d[k]
    return None


rows = []
for tag in ["w0", "w2", "w4", "mean"]:
    a, h = scores / f"{tag}_auc.json", scores / f"{tag}_hp.json"
    if not a.exists():
        continue
    auc = json.loads(a.read_text())
    hp = json.loads(h.read_text()) if h.exists() else {}
    if tag == "mean":
        window = "mean of three 24-layer windows (layers 0-23, 2-25, 4-27)"
        secs = sum(x for x in (seconds(f"w{s}_fwd_s64") for s in (0, 2, 4)) if x) or None
    else:
        s = int(tag[1])
        window = f"layers {s}-{s + 23} of 28" + (" (v8in's default, centred)" if s == 2 else "")
        secs = seconds(f"{tag}_fwd_s64")
    rows.append({
        "job": "v8inwin-ag405", "segment": "0841-ag405", "window": "crop", "inner_px": 64,
        "map_from": "bare-crop", "reader": "v8in",
        "settings": {"checkpoint": "YoussefMoNader/ink-8um-v8in", "revision": REV,
                     "stride": 64, "layer_window": window,
                     "ensemble_method": "mean" if tag == "mean" else None, "batch_size": 4,
                     "control": "reverse of the default window (layers 2-25), stride 64"},
        "device": "cpu",
        "auc_as_stored": pick(auc, "auc", "auc_as_stored", "forward"),
        "auc_reversed": pick(auc, "control_auc", "auc_control", "auc_reversed", "reverse"),
        "hp_r": pick(hp, "hp_r", "r", "score"),
        "hp_r_reversed": pick(hp, "hp_r_control", "control_r", "hp_r_reversed", "control"),
        "ink_px": pick(auc, "ink_px", "n_ink", "ink"),
        "seconds": secs,
        "notes": None if tag == "w2" else "control is the default window's reverse map (only one reverse run in the budget)",
        "raw": {"auc": auc, "hp": hp},
    })
out.write_text(json.dumps(rows, indent=1) + "\n")
print(f"{len(rows)} rows -> {out}")
