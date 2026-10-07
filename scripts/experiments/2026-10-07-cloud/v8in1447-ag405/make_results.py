"""Collect scores/*.json into results.json (rows in the format of the cloud README).

    python scripts/experiments/2026-10-07-cloud/v8in1447-ag405/make_results.py [SECONDS_JSON]
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
S = HERE / "scores"
V8 = "YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062@2bf9f421862cda0ed41dcae6e8274c12e295d03a"
D9 = "d9v2_ft-012000.pth (TAUIL-Abd-Elilah/pherc0826-first-letters-search v1.0, sha256 50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966)"
MAPS = {
    "d9v2": ("d9v2", {"checkpoint": D9, "villa": "PR #1865", "overlap": 0.5, "blend": "hann"}, "reverse is villa --direction both"),
    "v8in1447_s42": ("v8in-1447", {"checkpoint": V8, "stride": 42, "batch": 4}, "reverse at stride 42"),
    "v8in1447_s21": ("v8in-1447", {"checkpoint": V8, "stride": 21, "batch": 4}, "control is the stride 42 reverse map"),
    "ens_v8in1447_d9v2_mean": ("v8in-1447 + d9v2", {"maps": ["v8in1447_s21", "d9v2"], "ensemble": "mean"},
                               "reverse: v8in1447 s42 reverse + d9v2 reverse, same method"),
    "ens_v8in1447_d9v2_rank": ("v8in-1447 + d9v2", {"maps": ["v8in1447_s21", "d9v2"], "ensemble": "rank"},
                               "reverse: v8in1447 s42 reverse + d9v2 reverse, same method"),
}
secs = json.loads(pathlib.Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else {}
rows = []
for name, (reader, settings, note) in MAPS.items():
    a, h = S / f"auc_{name}.json", S / f"hp_{name}.json"
    if not (a.exists() and h.exists()):
        continue
    a, h = json.loads(a.read_text()), json.loads(h.read_text())
    row = {"job": "v8in1447-ag405", "segment": "0841-ag405", "window": "crop", "inner_px": 64,
           "map_from": "bare-crop", "map": name, "reader": reader, "settings": settings, "device": "cpu",
           "auc_as_stored": a["forward"]["auc"], "auc_reversed": a.get("control", {}).get("auc"),
           "hp_r": h["forward"]["hp_r"], "hp_r_reversed": h.get("control", {}).get("hp_r"),
           "hp_null_max_abs": h["forward"]["null_max_abs"], "ink_px": a["forward"]["ink_px"], "notes": note}
    if name in secs:
        row["seconds"] = secs[name]
    rows.append(row)
(HERE / "results.json").write_text(json.dumps(rows, indent=1) + "\n")
for r in rows:
    print(f"| {r['map']} | {r['auc_as_stored']} | {r['auc_reversed']} | {r['hp_r']} | {r['hp_r_reversed']} |")
