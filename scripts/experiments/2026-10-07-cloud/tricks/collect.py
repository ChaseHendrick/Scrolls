"""Fold $S/tricks/scores_<seg>.json (from score_seg.sh) into results.json and tables.md here.

    python collect.py RUN_ALL_LOG

Timings come from the run log ("<seg>_<map>.tif N s" and "<seg> <map> N s" lines).
"""
import json, os, re, sys

S = os.environ.get("S", os.path.expanduser("~/scrolls-cpu"))
HERE = os.path.dirname(os.path.abspath(__file__))
SEGS = ["0841-w00", "0841-ag896", "0841-ag405", "w045"]
P0841 = SEGS[:3]
READERS = {"s42": "ink_9um seed 42", "soup42": "ink_9um soup42_last4", "d9v2": "d9v2", "rv2": "Reader v2"}
CKPT = {"s42": "scrollprize/ink_9um hybrid_3d2d-seed42/step-075000.pth (sha256 e635558a...ea76a)",
        "soup42": "soup42_last4 (seed 42 steps 40k-75k, safetensors sha256 ab3f1bde...849c, bit-identical to Nieuwlaar)",
        "d9v2": "TAUIL v1.0 d9v2_ft-012000.pth (sha256 50d2ad0e...a9f966)",
        "rv2": "domenicor046/reader-v2 reader-v2-step040000.pth (sha256 654ec5ac...d5d3a6)"}
WINS = ["z0-20", "z3-23", "z5-25", "z8-27"]
BASE = "villa main e0bbb8b40 + PR #1865 (6723ad158), overlap 0.5, hann, batch 1, no compile"

times = {}
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    for line in open(sys.argv[1]):
        m = re.match(r"^(\S+)\.tif (\d+) s$", line.strip())
        if m:
            times[m.group(1)] = int(m.group(2))
        m = re.match(r"^(\S+) (ink9um_s42|d9v2) (\d+) s$", line.strip())
        if m:
            times[f"{m.group(1)}_{'ink9um_s42' if m.group(2) == 'ink9um_s42' else 'd9v2'}"] = int(m.group(3))

scores = {}
for seg in SEGS:
    p = f"{S}/tricks/scores_{seg}.json"
    if os.path.exists(p):
        for name, vals in json.load(open(p)).items():
            scores.setdefault(name, {})[seg] = vals[0]


def get(name, seg):
    return scores.get(name, {}).get(seg)


def describe(name):
    """reader key, settings text, map files that make it (for timing)."""
    r = name.split("_")[0].split("+")[0]
    if "+" in name:
        a, b = name.split("_")[0].split("+")
        meth = name.rsplit("_", 1)[1]
        return name, f"map ensemble ({meth}) of {a} and {b} default-window maps; reverse ensembled the same way", []
    rest = name[len(r):].lstrip("_")
    files = []
    if rest == "":
        s = "default window, both directions"; files = ["ink9um_s42" if r == "s42" else r]
    elif rest in WINS:
        a, b = rest[1:].split("-"); s = f"--layer-start {a} --layer-end {b}"; files = [name]
    elif rest == "zmean":
        s = "mean of the 4 z windows 0:20 3:23 5:25 8:27 (kit ensemble mean)"; files = [f"{r}_{w}" for w in WINS]
    elif rest == "shuf":
        s = "depth-shuffled crop (numpy rng 20261007 permutation), forward only"; files = [name]
    elif rest == "tta":
        s = "--tta-mirror, both directions"; files = [name]
    else:
        s = rest
    return READERS.get(r, r), f"{CKPT.get(r, '')}; {s}; {BASE}", files


rows = []
for name in scores:
    reader, settings, files = describe(name)
    for seg in SEGS:
        v = get(name, seg)
        if not v:
            continue
        row = {"job": "tricks", "segment": seg, "window": "crop", "inner_px": 64, "map_from": "bare-crop",
               "reader": reader, "settings": settings, "device": "cpu", "map": name}
        if name.endswith("_shuf"):
            row["auc_shuffled"] = round(v[0], 4); row["hp_r_shuffled"] = round(v[2], 4)
        else:
            row["auc_as_stored"] = round(v[0], 4); row["hp_r"] = round(v[2], 4)
            if v[1] is not None:
                row["auc_reversed"] = round(v[1], 4)
            if v[3] is not None:
                row["hp_r_reversed"] = round(v[3], 4)
            sh = get(name.split("_")[0] + "_shuf", seg) if name in READERS else None
            if sh:
                row["auc_shuffled"] = round(sh[0], 4)
        row["hp_null_max_abs"] = round(v[4], 4)
        secs = [times.get(f"{seg}_{f}") for f in files]
        if files and all(s is not None for s in secs):
            row["seconds"] = sum(secs)
        rows.append(row)
json.dump(rows, open(os.path.join(HERE, "results.json"), "w"), indent=1)


def cell(v):
    if not v:
        return ""
    rev = "" if v[1] is None else f" ({v[1]:.3f})"
    return f"{v[0]:.4f}{rev} / {v[2]:+.3f}"


def mean(name, i):
    xs = [get(name, s)[i] for s in P0841 if get(name, s)]
    return sum(xs) / 3 if len(xs) == 3 else None


out = ["Forward AUC (reversed AUC in brackets) / `hp_r` (letter-scale r). Shuffle rows are forward only. "
       "Mean: over the three PHerc0841 crops, forward AUC / `hp_r`.", "",
       "| Map | 0841 w00 | 0841 ag896 | 0841 ag405 | w045 | Mean 0841 AUC / hp_r |", "| --- | --- | --- | --- | --- | --- |"]
for name in scores:
    ma, mh = mean(name, 0), mean(name, 2)
    m = "" if ma is None else f"{ma:.4f} / {mh:+.3f}"
    out.append(f"| {name} | " + " | ".join(cell(get(name, s)) for s in SEGS) + f" | {m} |")

out += ["", "Lead (d): default window, 4-window mean, best single window chosen with the labels (by AUC, and by `hp_r`). AUC / hp_r.", "",
        "| Reader | Crop | Default | 4-window mean | Best window by AUC | Best window by hp_r | Mean - default (AUC, hp_r) | Mean - best (AUC, hp_r) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |"]
agg = {}
for r in READERS:
    for seg in SEGS:
        d, z = get(r if r != "s42" else "s42", seg), get(f"{r}_zmean", seg)
        ws = [(w, get(f"{r}_{w}", seg)) for w in WINS if get(f"{r}_{w}", seg)]
        if not (d and z and len(ws) == 4):
            continue
        ba = max(ws, key=lambda t: t[1][0]); bh = max(ws, key=lambda t: t[1][2])
        dd = (z[0] - d[0], z[2] - d[2]); db = (z[0] - ba[1][0], z[2] - bh[1][2])
        out.append(f"| {READERS[r]} | {seg} | {d[0]:.4f} / {d[2]:+.3f} | {z[0]:.4f} / {z[2]:+.3f} | "
                   f"{ba[0]} {ba[1][0]:.4f} | {bh[0]} {bh[1][2]:+.3f} | {dd[0]:+.4f}, {dd[1]:+.3f} | {db[0]:+.4f}, {db[1]:+.3f} |")
        if seg in P0841:
            agg.setdefault("all", []).append((d, z, ba[1], bh[1]))
if agg.get("all"):
    L = agg["all"]; n = len(L)
    f = lambda xs: sum(xs) / n
    out += ["", f"Over {n} reader-crop cases on PHerc0841: default {f([a[0][0] for a in L]):.4f} / {f([a[0][2] for a in L]):+.4f}; "
            f"4-window mean {f([a[1][0] for a in L]):.4f} / {f([a[1][2] for a in L]):+.4f}; "
            f"best window by AUC {f([a[2][0] for a in L]):.4f}; best window by hp_r {f([a[3][2] for a in L]):+.4f}. "
            f"hp_r: mean above default in {sum(a[1][2] > a[0][2] for a in L)} of {n}, at or above the best window in {sum(a[1][2] >= a[3][2] for a in L)} of {n}."]
open(os.path.join(HERE, "tables.md"), "w").write("\n".join(out) + "\n")
print("\n".join(out))
