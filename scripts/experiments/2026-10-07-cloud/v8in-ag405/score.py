"""Score every map of job v8in-ag405 that exists, build the ensembles, write results.json.

    $W/venv/bin/python score.py [--work $HOME/scrolls-work]

Every score is on the ag405 crop with a 64 px edge left out, labels at level 2. Each map's
control is its reverse-direction map; the shuffled v8in map is scored as its own row too.
v8in maps are scored from the float .npy (the uint8 .tif rounds low scores to 0, which
kit auc would drop as "no prediction"). Rerunning is cheap and safe.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCROLLS = HERE.parents[3]
SEG = "0841-ag405"
CROP = ["1024", "1664", "2496", "3136"]
SURFACE = ["3760", "4900"]
VOXEL = "9.366"
V8IN_REV = "d89166b41a3f5fad7749b3d7c0fdd1bd3695d844"
D9V2_SHA = "50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966"


def kit(py, *args):
    out = subprocess.run([py, "-m", "kit", *args], cwd=SCROLLS, capture_output=True, text=True)
    if out.returncode not in (0, 1):
        raise SystemExit(f"kit {args[0]} failed: {out.stderr}")
    return json.loads(out.stdout)


def seconds(log):
    if not log.exists():
        return None
    text = log.read_text()
    m = re.findall(r"done in (\d+)s", text)
    return int(m[-1]) if m else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", type=Path, default=Path.home() / "scrolls-work")
    a = p.parse_args()
    py = str(a.work / "venv/bin/python")
    j = a.work / "job-v8in-ag405"
    maps, logs = j / "maps", j / "logs"
    lab = a.work / "data" / f"{SEG}_labels"
    common = ["--labels", str(lab / "inklabels.zarr"), "--mask", str(lab / "supervision.zarr"), "--level", "2",
              "--crop", *CROP, "--surface-shape", *SURFACE, "--inner", "64", "--json"]

    def score(fwd, rev):
        r = {}
        auc = kit(py, "auc", str(fwd), *(["--control", str(rev)] if rev else []), *common)
        r["auc_as_stored"] = auc["forward"]["auc"]
        r["ink_px"] = auc["forward"]["ink_px"]
        if rev:
            r["auc_reversed"] = auc["control"]["auc"]
        hp = kit(py, "hpscore", str(fwd), *(["--control", str(rev)] if rev else []), "--voxel-um", VOXEL, *common)
        r["hp_r"] = hp["forward"]["hp_r"]
        r["hp_null_max_abs"] = hp["forward"]["null_max_abs"]
        if rev:
            r["hp_r_reversed"] = hp["control"]["hp_r"]
        r["_raw"] = {"auc": auc, "hpscore": hp}
        return r

    def v8(name):
        return maps / f"{name}.npy"

    rows, raw = [], {}
    base = {"job": "v8in-ag405", "segment": SEG, "window": "crop", "inner_px": 64,
            "map_from": "bare-crop", "device": "cpu"}

    def add(reader, settings, fwd, rev, secs, notes=None, extra=None):
        if not fwd.exists() or (rev is not None and not rev.exists()):
            return None
        r = score(fwd, rev)
        raw[reader] = r.pop("_raw")
        row = dict(base, reader=reader, settings=settings, **r, seconds=secs)
        if extra:
            row.update(extra)
        if notes:
            row["notes"] = notes
        rows.append({k: v for k, v in row.items() if v is not None})
        return row

    villa = "villa PR #1865, overlap 0.5, hann, batch 1, both directions"
    add("ink_9um seed42", f"step-075000, {villa}", maps / "ink9um_s42.tif", maps / "ink9um_s42_reverse.tif",
        seconds(logs / "ink9um_s42.log"), "seconds cover both directions")
    add("d9v2", f"TAUIL v1.0 d9v2_ft-012000 (sha256 {D9V2_SHA}), {villa}", maps / "d9v2.tif",
        maps / "d9v2_reverse.tif", seconds(logs / "d9v2.log"), "seconds cover both directions")
    v8set = f"YoussefMoNader/ink-8um-v8in {V8IN_REV}, central 24 of 28 layers, batch 4, fp32"
    shuf = v8("v8in_shuf_s42")
    shuf_auc = kit(py, "auc", str(shuf), *common)["forward"]["auc"] if shuf.exists() else None
    for name, stride in (("v8in_s21", 21), ("v8in_s42", 42)):
        add("v8in", f"{v8set}, forward stride {stride}, reverse stride 42", v8(name), v8("v8in_s42_reverse"),
            seconds(logs / f"{name}.log"), "seconds: forward pass only; reverse at stride 42",
            {"auc_shuffled": shuf_auc})
    add("v8in depth-shuffled", f"{v8set}, kit layers --shuffle 20261007, forward stride 42", shuf, None,
        seconds(logs / "v8in_shuf_s42.log"), "auc_as_stored here is the shuffled map's AUC (control row)")

    # Ensembles: v8in forward s21 (reverse s42), ink_9um s42, d9v2; reverses ensembled the same way.
    ens = j / "ensembles"
    ens.mkdir(exist_ok=True)
    parts = {"v8in": (v8("v8in_s21"), v8("v8in_s42_reverse")),
             "ink9um": (maps / "ink9um_s42.tif", maps / "ink9um_s42_reverse.tif"),
             "d9v2": (maps / "d9v2.tif", maps / "d9v2_reverse.tif")}
    for combo in (("v8in", "d9v2"), ("v8in", "ink9um"), ("v8in", "ink9um", "d9v2")):
        if not all(f.exists() for c in combo for f in parts[c]):
            continue
        for method in ("mean", "rank"):
            tag = "+".join(combo) + f"_{method}"
            out_f, out_r = ens / f"{tag}.npy", ens / f"{tag}_reverse.npy"
            for out, k in ((out_f, 0), (out_r, 1)):
                if not out.exists():
                    kit(py, "ensemble", str(out), *[str(parts[c][k]) for c in combo], "--method", method, "--json")
            add(" + ".join(combo).replace("ink9um", "ink_9um seed42"),
                f"ensemble {method}, equal weights; v8in forward stride 21; reverse maps ensembled the same way",
                out_f, out_r, None)

    (HERE / "results.json").write_text(json.dumps(rows, indent=1) + "\n")
    (j / "scores_raw.json").write_text(json.dumps(raw, indent=1) + "\n")
    for r in rows:
        print(f"{r['reader']:<34} {r['settings'][:40]:<40} fwd {r.get('auc_as_stored')} rev {r.get('auc_reversed')} "
              f"shuf {r.get('auc_shuffled')} hp_r {r.get('hp_r')} hp_rev {r.get('hp_r_reversed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
