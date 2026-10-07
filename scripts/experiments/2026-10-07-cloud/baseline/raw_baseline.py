"""No-model baseline: how well raw CT brightness alone separates labelled ink from background.

For each layer of a 28-layer surface volume, and for simple depth statistics, the pixel AUC
against the segment's human labels inside the supervision mask, on the 640 px crop with a
64 px edge left out (as every reader is scored here) and on the whole segment. An AUC below
0.5 means labelled ink is darker than background at that depth.

    python raw_baseline.py SEGMENT SURFACE.zarr LABEL_DIR > out.json

SEGMENT is one of w045, 0841-w00, 0841-ag896, 0841-ag405 (crop and shape from docs/results.json).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", ".."))

import numpy as np  # noqa: E402
import zarr  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

from kit import auc  # noqa: E402

SEGS = json.load(open(os.path.join(HERE, "..", "..", "..", "..", "docs", "results.json")))["segments"]


def score(img, ink, sup, inner):
    # float maps: shift to strictly positive so no real pixel is dropped as "no prediction"
    m = img.astype(np.float64)
    m = (m - m.min()) / max(m.max() - m.min(), 1e-12) * 0.999 + 0.001
    return auc.score_array(m, ink, sup, inner=inner)["auc"]


def main():
    seg, sv, labdir = sys.argv[1:4]
    info = SEGS[seg]
    H, W = info["surface_shape"]
    y0, y1, x0, x1 = info["crop"]
    voxel = info["voxel_um"]
    vol = zarr.open(sv, mode="r")
    vol = vol["0"] if hasattr(vol, "keys") else vol
    a = np.asarray(vol[:])                      # (layers, H, W)
    assert a.shape[1:] == (H, W), (a.shape, H, W)
    surface = a.max(axis=0) > 0                 # pixels the render filled
    lab, sup = f"{labdir}/inklabels.zarr", f"{labdir}/supervision.zarr"
    ink_c, sup_c = auc.labels_on_map(lab, sup, "2", (H, W), (y0, y1, x0, x1), (y1 - y0, x1 - x0))
    ink_w, sup_w = auc.labels_on_map(lab, sup, "2", (H, W), None, (H, W))
    sup_w = sup_w & surface
    out = {"segment": seg, "layers": a.shape[0], "ink_px_crop": int((ink_c & sup_c).sum()),
           "ink_px_whole": int((ink_w & sup_w).sum()), "per_layer": [], "stats": {}}
    for k in range(a.shape[0]):
        out["per_layer"].append({"layer": k,
                                 "crop": score(a[k, y0:y1, x0:x1], ink_c, sup_c, 64),
                                 "whole": score(a[k], ink_w, sup_w, 0)})
    f = a.astype(np.float32)
    sigma = 48.0 / voxel                        # Scheirer's letter-scale blur, in pixels
    stats = {
        "mean_all": f.mean(0),
        "std_depth": f.std(0),
        "max_depth": f.max(0),
        "argmax_depth": f.argmax(0).astype(np.float32),
        "mean_central_10_17": f[10:18].mean(0),
        "central_minus_outer": f[10:18].mean(0) - np.concatenate([f[:6], f[-6:]]).mean(0),
    }
    for name, img in stats.items():
        out["stats"][name] = {"crop": score(img[y0:y1, x0:x1], ink_c, sup_c, 64), "whole": score(img, ink_w, sup_w, 0)}
    # local contrast at the best crop layer chosen without labels? No: report every layer's high-pass AUC too.
    out["highpass_per_layer"] = []
    for k in range(a.shape[0]):
        hp = f[k] - gaussian_filter(f[k], sigma)
        out["highpass_per_layer"].append({"layer": k, "crop": score(hp[y0:y1, x0:x1], ink_c, sup_c, 64),
                                          "whole": score(hp, ink_w, sup_w, 0)})
    json.dump(out, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
