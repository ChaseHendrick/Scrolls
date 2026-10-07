"""Collation of two traces of one sheet (PHerc0841 w00 and ag896): does the ink map agree between
the traces more than the raw CT texture does? If raw CT agrees as well, cross-trace agreement is
not specific to ink and cannot serve as a label-free ink check.

At matched 3D points (47 um grid), by gap between the traces: Pearson r of (a) the team's 2.4 um
ink maps, (b) raw CT, mean of the central five 9.4 um layers, after a 48 um high-pass (letter
scale), (c) the same raw CT without the high-pass. Also (d) agreement of the ink maps restricted
(d) how often a spot in the top 20 % of one trace's map is also in the top 20 % of the other's
(chance 0.2), for the ink maps and for thick-slab high-passed CT; (e) raw CT averaged over a
thick slab (21 layers, about 200 um), closer to what an ink model sees.

    python collation.py DATA_DIR      (layout as trace_and_noise.py, plus 0841-<name>_9um.zarr)
"""
import glob, os, sys, json
import numpy as np, tifffile, zarr
from scipy.ndimage import zoom, binary_erosion, gaussian_filter
from scipy.spatial import cKDTree
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..")
SEGS = json.load(open(os.path.join(ROOT, "docs", "results.json")))["segments"]
D = sys.argv[1] if len(sys.argv) > 1 else "data"
UP = 4

def load(name):
    seg = "0841-" + name; H, W = SEGS[seg]["surface_shape"]; vox = SEGS[seg]["voxel_um"]
    xyz = np.stack([tifffile.imread(f"{D}/mesh/{name}/{c}.tif") for c in "xyz"], -1).astype(np.float64)
    valid = (xyz > 0).all(-1)
    xyzu = np.stack([zoom(xyz[..., i], UP, order=1) for i in range(3)], -1)
    vu = binary_erosion(zoom(valid.astype(np.float32), UP, order=0) > 0.5, iterations=UP)
    gh, gw = vu.shape
    ink = tifffile.imread(glob.glob(f"{D}/inkdet/{name}/*.tif")[0]).astype(np.float32)
    ink = gaussian_filter(ink, 4)                                   # about 10 um, then sample
    ri = np.clip(((np.arange(gh) + 0.5) / gh * ink.shape[0]).astype(int), 0, ink.shape[0] - 1)
    ci = np.clip(((np.arange(gw) + 0.5) / gw * ink.shape[1]).astype(int), 0, ink.shape[1] - 1)
    vol = np.asarray(zarr.open(f"{D}/{seg}_9um.zarr", mode="r")["0"]).astype(np.float32)
    ct = vol[12:17].mean(0)                          # thin slab, about 47 um
    thick = vol[4:25].mean(0)                        # thick slab, about 200 um, like an ink model's input
    hp = ct - gaussian_filter(ct, 48 / vox)
    hpt = thick - gaussian_filter(thick, 48 / vox)
    rs = np.clip(((np.arange(gh) + 0.5) / gh * H).astype(int), 0, H - 1)
    cs = np.clip(((np.arange(gw) + 0.5) / gw * W).astype(int), 0, W - 1)
    g = np.ix_(rs, cs)
    return dict(xyz=xyzu, v=vu, ink=ink[np.ix_(ri, ci)], ct=ct[g], hp=hp[g], thick=thick[g], hpt=hpt[g])

A, B = load("w00"), load("ag896")
idx = np.argwhere(B["v"])
dd, j = cKDTree(B["xyz"][B["v"]]).query(A["xyz"][A["v"]], k=1)
ay, ax = np.nonzero(A["v"]); by, bx = idx[j, 0], idx[j, 1]
a = {k: A[k][ay, ax] for k in ("ink", "ct", "hp", "thick", "hpt")}; b = {k: B[k][by, bx] for k in ("ink", "ct", "hp", "thick", "hpt")}
ok = (a["ink"] > 0) & (b["ink"] > 0) & (a["ct"] > 0) & (b["ct"] > 0)
top = lambda x: x > np.percentile(x[ok], 80)   # a 'candidate' spot: top 20 % of a map
r = lambda x, y: float(np.corrcoef(x, y)[0, 1])
rows = []
for lo, hi_ in [(0, 3), (3, 6), (6, 9), (9, 12), (12, 18)]:
    m = ok & (dd > lo) & (dd <= hi_)
    reap = lambda k: round(float(top(b[k])[m & top(a[k])].mean()), 3)   # P(B top 20 % | A top 20 %), chance 0.2
    row = dict(gap_um=f"{lo*9.366:.0f}-{hi_*9.366:.0f}", points=int(m.sum()),
               ink_r=round(r(a["ink"][m], b["ink"][m]), 3),
               ct_highpass_r=round(r(a["hp"][m], b["hp"][m]), 3),
               ct_raw_r=round(r(a["ct"][m], b["ct"][m]), 3),
               ct_thick_r=round(r(a["thick"][m], b["thick"][m]), 3),
               ct_thick_highpass_r=round(r(a["hpt"][m], b["hpt"][m]), 3),
               reappear_ink=reap("ink"), reappear_ct_thick_highpass=reap("hpt"))
    rows.append(row); print(row, flush=True)
json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "collation.json"), "w"), indent=1)
