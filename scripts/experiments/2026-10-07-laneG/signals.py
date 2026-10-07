"""Lane G: new model-free ink signals at 9 um (rule: docs/prereg/2026-10-07-grok-laneG.md).

Usage: python signals.py REPO_ROOT DATA_DIR OUT_DIR
Writes OUT_DIR/maps/<seg>_<signal>[_shuf].tif (direction fixed on w045) and OUT_DIR/features.json.
Bootstrap AUCs are then taken with `python -m kit auc --bootstrap 300` (run.sh).
"""
import json, sys
import numpy as np
from scipy import ndimage as ndi
import tifffile

sys.path.insert(0, sys.argv[1])
from kit.layers import open_volume, depth_permutation
from kit.auc import labels_on_map, score_array

DATA, OUT = sys.argv[2], sys.argv[3]
SEGS = {  # w045 first: it fixes each signal's direction
    "w045": dict(zarr="w045_9um.zarr", labels="w045_labels", crop=(3840, 4480, 2560, 3200)),
    "0841-w00": dict(zarr="0841-w00_9um.zarr", labels="0841-w00_labels", crop=(2624, 3264, 2688, 3328)),
}
PAD, INNER, SEED = 48, 64, 20261007


def norm(m):
    m = m.astype(np.float64); lo, hi = np.percentile(m, [0.5, 99.5])
    return np.clip((m - lo) / (hi - lo + 1e-12), 1e-6, 1.0)


def phase_sym(img, wavelengths=(12, 24, 48), sigma_onf=0.55):
    h, w = img.shape
    fy = np.fft.fftfreq(h)[:, None]; fx = np.fft.fftfreq(w)[None, :]
    r = np.sqrt(fx ** 2 + fy ** 2); r[0, 0] = 1.0
    F = np.fft.fft2(img - img.mean())
    R1, R2 = 1j * fx / r, 1j * fy / r
    num = np.zeros_like(img); den = np.zeros_like(img)
    for lam in wavelengths:
        G = np.exp(-(np.log(r * lam)) ** 2 / (2 * np.log(sigma_onf) ** 2)); G[0, 0] = 0
        FG = F * G
        even = np.real(np.fft.ifft2(FG))
        o1, o2 = np.real(np.fft.ifft2(FG * R1)), np.real(np.fft.ifft2(FG * R2))
        odd = np.sqrt(o1 ** 2 + o2 ** 2); amp = np.sqrt(even ** 2 + odd ** 2)
        T = 2 * np.median(amp)
        num += np.maximum(np.abs(even) - odd - T, 0); den += amp
    return num / (den + 1e-6)


def features(v):
    n = v.shape[0]; z0, z1 = n // 4, n - n // 4
    mean = v[z0:z1].mean(0)
    out = {"brightness": mean}
    d = ndi.gaussian_filter(mean, 3) - ndi.gaussian_filter(mean, 6)
    out["dog_band"] = ndi.gaussian_filter(d * d, 6)
    dz2 = v[2:] - 2 * v[1:-1] + v[:-2]
    out["noise_resid"] = np.stack([ndi.median_filter(np.abs(dz2[z - 1]), 11) for z in range(z0, z1)]).mean(0)
    disk = np.hypot(*np.mgrid[-3:4, -3:4]) <= 3
    fr = []
    for z in range(z0, z1):
        bt = ndi.black_tophat(v[z], footprint=disk)
        fr.append(ndi.uniform_filter((bt > np.percentile(bt, 90)).astype(np.float32), 31))
    out["crackle"] = np.mean(fr, 0)
    p = v - v.min(0, keepdims=True)
    zc = (np.arange(n, dtype=np.float32)[:, None, None] * p).sum(0) / (p.sum(0) + 1e-6)
    out["relief"] = np.abs(ndi.gaussian_laplace(zc, 8))
    out["phase_sym"] = phase_sym(mean)
    return {k: m[PAD:-PAD, PAD:-PAD] for k, m in out.items()}


def period(profile, lo=15, hi=200):
    x = profile - profile.mean(); ac = np.correlate(x, x, "full")[len(x) - 1:]; ac = ac / (ac[0] + 1e-12)
    hi = min(hi, len(ac) - 2)
    peaks = [k for k in range(lo, hi) if ac[k] > ac[k - 1] and ac[k] >= ac[k + 1]]
    if not peaks: return None, None
    k = max(peaks, key=lambda k: ac[k]); return int(k), float(ac[k])


import os
os.makedirs(f"{OUT}/maps", exist_ok=True)
res = {"seed": SEED, "pad": PAD, "inner": INNER, "segments": {}}
sign = {}
for name, s in SEGS.items():
    vol = open_volume(f"{DATA}/{s['zarr']}"); surf = vol.shape[1:]
    y0, y1, x0, x1 = s["crop"]
    v = np.asarray(vol[:, y0 - PAD:y1 + PAD, x0 - PAD:x1 + PAD]).astype(np.float32)
    ink, sup = labels_on_map(f"{DATA}/{s['labels']}/inklabels.zarr", f"{DATA}/{s['labels']}/supervision.zarr",
                             "2", surf, s["crop"], (y1 - y0, x1 - x0))
    real, shuf = features(v), features(v[depth_permutation(v.shape[0], SEED)])
    rng = np.random.default_rng(SEED)
    shifts = [(int(a), int(b)) for a, b in rng.integers(120, 520, size=(8, 2))]
    seg = {"surface": list(map(int, surf)), "crop": list(s["crop"]), "features": {}}
    b = norm(real["brightness"])
    for k in real:
        raw = score_array(norm(real[k]), ink, sup, inner=INNER)["auc"]
        if name == "w045": sign[k] = 1 if raw >= 0.5 else -1
        sg = sign[k]
        f = lambda m: norm(sg * m)
        a = score_array(f(real[k]), ink, sup, inner=INNER)["auc"]
        nulls = [score_array(np.roll(f(real[k]), sh, (0, 1)), ink, sup, inner=INNER)["auc"] for sh in shifts]
        from scipy.stats import spearmanr
        rho = float(spearmanr(real[k].ravel()[::7], b.ravel()[::7])[0])
        seg["features"][k] = {"direction": "higher=ink" if sg > 0 else "lower=ink", "auc": a,
                              "auc_depth_shuffled": score_array(f(shuf[k]), ink, sup, inner=INNER)["auc"],
                              "rolled_null_max": max(nulls), "rolled_null_min": min(nulls),
                              "spearman_vs_brightness": rho}
        tifffile.imwrite(f"{OUT}/maps/{name}_{k}.tif", f(real[k]).astype(np.float32))
        tifffile.imwrite(f"{OUT}/maps/{name}_{k}_shuf.tif", f(shuf[k]).astype(np.float32))
    lab = np.where(sup, ink.astype(float), np.nan)
    rows = {"labels": np.nanmean(lab, 1), "dog_band": real["dog_band"].mean(1), "dog_band_shuf": shuf["dog_band"].mean(1)}
    seg["line_period"] = {}
    for k, prof in rows.items():
        prof = np.nan_to_num(prof, nan=np.nanmean(prof))
        seg["line_period"][k] = dict(zip(("lag_px", "peak"), period(prof)))
    res["segments"][name] = seg
    print(name, json.dumps(seg["features"], indent=0)[:3000], seg["line_period"], flush=True)
json.dump(res, open(f"{OUT}/features.json", "w"), indent=1)
