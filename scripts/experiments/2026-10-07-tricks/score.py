"""Score maps on the crops: python score.py NAME=map[,map...][:rank] ...  (maps relative to readers/ or tricks/)."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from kit import auc, ensemble, hpscore
S = os.environ.get("S", os.path.expanduser("~/scrolls-cpu"))
LAB = {"w045": f"{S}/data/w045_labels", "0841-w00": f"{S}/data/p0841/20260220213127-w00",
       "0841-ag896": f"{S}/data/p0841/20260220214732-auto_grown_20260220144552896",
       "0841-ag405": f"{S}/data/p0841/20260221022814-auto_grown_20260220174252405"}
CR = {"w045": (3840, 4480, 2560, 3200), "0841-w00": (2624, 3264, 2688, 3328), "0841-ag896": (2496, 3136, 1600, 2240), "0841-ag405": (1024, 1664, 2496, 3136)}
SH = {"w045": (5980, 8240), "0841-w00": (4220, 4760), "0841-ag896": (4640, 4720), "0841-ag405": (3760, 4900)}

def find(seg, m):
    for d in ("tricks", "readers"):
        p = f"{S}/{d}/{seg}_{m}.tif"
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"{seg}_{m}")

def build(seg, spec, rev):
    method = "mean"
    if spec.endswith(":rank"):
        spec, method = spec[:-5], "rank"
    parts = spec.split(",")
    paths = [find(seg, p + ("_reverse" if rev else "")) for p in parts]
    if len(paths) == 1:
        return paths[0]
    alias = ALIAS.get(spec + (":rank" if method == "rank" else ""))
    out = (f"{S}/tricks/{seg}_{alias}{'_reverse' if rev else ''}.tif" if alias else
           f"{S}/tricks/ens/{seg}_{spec.replace(',', '+')}_{method}{'_reverse' if rev else ''}.tif")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ensemble.ensemble_files(out, paths, method)
    return out

ALIAS = {}
segs = [s for s in ("0841-w00", "0841-ag896", "0841-ag405", "w045")]
rows = {}
SEGS = [a[5:].split(",") for a in sys.argv[1:] if a.startswith("SEGS=")]
if SEGS:
    segs = SEGS[0]
for arg in [a for a in sys.argv[1:] if not a.startswith("SEGS=")]:
    name, spec = arg.split("=", 1)
    if name.startswith("@"):   # @alias=spec: build and save as tricks/<seg>_<alias>.tif, usable in later specs
        name = name[1:]
        ALIAS[spec] = name
    vals = []
    for seg in segs:
        try:
            f, r = build(seg, spec, False), None
            try:
                r = build(seg, spec, True)
            except FileNotFoundError:
                r = None
        except FileNotFoundError:
            vals.append(None); continue
        res = auc.score_files(f, f"{LAB[seg]}/inklabels.zarr", f"{LAB[seg]}/supervision.zarr", r, crop=CR[seg], surface_shape=SH[seg], inner=64)
        hp = hpscore.score_files(f, f"{LAB[seg]}/inklabels.zarr", f"{LAB[seg]}/supervision.zarr", 9.362 if seg == "w045" else 9.366, r, crop=CR[seg], surface_shape=SH[seg], inner=64)
        vals.append((res["forward"]["auc"], res["control"]["auc"] if r else None, hp["forward"]["hp_r"], hp["control"]["hp_r"] if r else None, hp["forward"]["null_max_abs"]))
    rows[name] = vals
    fw = [v[0] for v in vals[:3] if v]
    mean = sum(fw) / len(fw) if len(fw) == 3 else None
    cells = " | ".join("" if v is None else f"{v[0]:.4f} ({'' if v[1] is None else f'{v[1]:.3f}'}) hp {v[2]:+.3f}/{'' if v[3] is None else f'{v[3]:+.3f}'}" for v in vals)
    print(f"| {name} | {cells} | {'' if mean is None else f'{mean:.4f}'} |", flush=True)
json.dump(rows, open(f"{S}/tricks/scores_{os.getpid()}.json", "w"))
