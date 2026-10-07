"""Lane C experiment: model-free volumetric texture as an ink signal at 9 um.

After Korotetskyi and Haindl (Zenodo 20766169, 2026), who report it on PHerc. 172 only:
first-order energy (local 3D std), Laws-style energy (L5 smoothing along depth x E5 edge
in plane), 3D gradient magnitude and block lag-1 autocorrelation, each projected to 2D by
the mean over central layers. Scored with kit's AUC against the 20260918 labels on the
640 px crops the repo already uses, inner 64 px. Controls: depth-shuffled volume (kit's
depth_permutation, seed 20261007) and 8 rolled-map nulls. The readout rule is in
docs/logs/2026-10-07-grok-laneC.md and was written before this script was run.

Usage: python texture.py REPO_ROOT DATA_DIR MAPS_DIR OUT_JSON
"""
import json, sys, time
import numpy as np
from scipy import ndimage as ndi

sys.path.insert(0, sys.argv[1])
from kit.layers import open_volume, depth_permutation
from kit.auc import labels_on_map, score_array, _load

DATA, MAPS, OUT = sys.argv[2], sys.argv[3], sys.argv[4]
SEGS = {
    "w045": dict(zarr="w045_9um.zarr", labels="w045_labels", crop=(3840, 4480, 2560, 3200),
                 map="w045_ink9um_s42.tif"),
    "0841-w00": dict(zarr="0841-w00_9um.zarr", labels="0841-w00_labels", crop=(2624, 3264, 2688, 3328),
                     map="w00_ink9um_s42.tif"),
}
PAD, INNER, SEED = 32, 64, 20261007
L5 = np.array([1, 4, 6, 4, 1], float); E5 = np.array([-1, -2, 0, 2, 1], float)


def norm(m):
    m = m.astype(np.float64); lo, hi = np.percentile(m, [0.5, 99.5])
    return np.clip((m - lo) / (hi - lo + 1e-12), 1e-6, 1.0)   # never exactly 0 (kit drops zeros)


def features(v):
    """v: (layers, H, W) float32 with PAD margin. Returns dict of 2D maps without the margin."""
    n = v.shape[0]; z0, z1 = n // 4, n - n // 4                 # central half of the layers
    out = {}
    mu = ndi.uniform_filter(v, 5); sq = ndi.uniform_filter(v * v, 5)
    out["std3d"] = np.sqrt(np.maximum(sq - mu * mu, 0))[z0:z1].mean(0)
    lz = ndi.convolve1d(v, L5 / 16, axis=0)
    ey = ndi.convolve1d(lz, E5, axis=1); ex = ndi.convolve1d(lz, E5, axis=2)
    out["laws_L5E5"] = ndi.uniform_filter(np.abs(ey) + np.abs(ex), (1, 15, 15))[z0:z1].mean(0)
    gz, gy, gx = np.gradient(ndi.gaussian_filter(v, 1.0))
    out["grad3d"] = np.sqrt(gz * gz + gy * gy + gx * gx)[z0:z1].mean(0)
    d = v - ndi.uniform_filter(v, (1, 15, 15))
    num = ndi.uniform_filter(d[:, 1:, :] * d[:, :-1, :], (1, 15, 15))
    den = ndi.uniform_filter(d * d, (1, 15, 15))[:, 1:, :] + 1e-6
    ac = np.pad(num / den, ((0, 0), (0, 1), (0, 0)), mode="edge")
    out["autocorr"] = ac[z0:z1].mean(0)
    out["brightness"] = v[z0:z1].mean(0)                        # baseline (repo finding 6)
    return {k: m[PAD:-PAD, PAD:-PAD] for k, m in out.items()}


def score(m, ink, sup):
    return score_array(norm(m), ink, sup, inner=INNER)["auc"]


res = {"seed": SEED, "pad": PAD, "inner": INNER, "segments": {}}
for name, s in SEGS.items():
    t = time.time()
    vol = open_volume(f"{DATA}/{s['zarr']}")
    surf = vol.shape[1:]
    y0, y1, x0, x1 = s["crop"]
    v = np.asarray(vol[:, y0 - PAD:y1 + PAD, x0 - PAD:x1 + PAD]).astype(np.float32)
    ink, sup = labels_on_map(f"{DATA}/{s['labels']}/inklabels.zarr", f"{DATA}/{s['labels']}/supervision.zarr",
                             "2", surf, s["crop"], (y1 - y0, x1 - x0))
    perm = depth_permutation(v.shape[0], SEED)
    real, shuf = features(v), features(v[perm])
    seg = {"layers": int(v.shape[0]), "surface": list(map(int, surf)), "crop": list(s["crop"]),
           "ink_px_inner": score_array(norm(real["std3d"]), ink, sup, inner=INNER)["ink_px"], "features": {}}
    rng = np.random.default_rng(SEED)
    shifts = [(int(a), int(b)) for a, b in rng.integers(120, 520, size=(8, 2))]
    for k in real:
        nulls = [score(np.roll(real[k], sh, (0, 1)), ink, sup) for sh in shifts]
        seg["features"][k] = {"auc": score(real[k], ink, sup), "auc_depth_shuffled": score(shuf[k], ink, sup),
                              "rolled_null_min": min(nulls), "rolled_null_max": max(nulls)}
    # ink_9um seed 42 on the same window, and rank fusion with each texture feature
    full = _load(f"{MAPS}/{s['map']}")
    ref = full[y0:y1, x0:x1].astype(np.float64)
    seg["ink9um_auc"] = score_array(ref / (ref.max() or 1), ink, sup, inner=INNER)["auc"]
    seg["features_np"] = None
    res["segments"][name] = seg
    np.savez_compressed(f"{OUT}.{name}.npz", ref=ref, ink=ink, sup=sup, **real)
    seg["seconds"] = round(time.time() - t, 1)
    print(name, json.dumps(seg["features"]), "ink9um", seg["ink9um_auc"], flush=True)

# Experiment 2: orientation chosen on w045 (seen scroll, held-out segment), applied unchanged
# to PHerc0841 w00 (unseen scroll); fuse ranks with ink_9um at weights 0.1, 0.25 and 0.5.
def rank(a):
    r = np.empty(a.size); r[np.argsort(a.ravel(), kind="stable")] = np.arange(a.size); return (r / a.size).reshape(a.shape)
z = {n: np.load(f"{OUT}.{n}.npz") for n in SEGS}
fusion = {}
for k in ["std3d", "laws_L5E5", "grad3d", "autocorr", "brightness"]:
    sign = 1 if res["segments"]["w045"]["features"][k]["auc"] >= 0.5 else -1
    fusion[k] = {"sign_from_w045": sign}
    for n in SEGS:
        d = z[n]; base = rank(d["ref"])
        for w in (0.1, 0.25, 0.5):
            f = (1 - w) * base + w * rank(sign * d[k])
            fusion[k][f"{n}_w{w}"] = score_array(norm(f), d["ink"], d["sup"], inner=INNER)["auc"]
        fusion[k][f"{n}_ink9um_rank"] = score_array(norm(base), d["ink"], d["sup"], inner=INNER)["auc"]
res["fusion"] = fusion
for s in res["segments"].values():
    s.pop("features_np", None)
json.dump(res, open(OUT, "w"), indent=1)
print(json.dumps(fusion, indent=1))
