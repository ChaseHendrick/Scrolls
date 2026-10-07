"""Three checks on PHerc0841 with the team's published 2.4 um ink maps (ink-detection/*.tif).

1. Trace consistency: w00 and ag896 trace one sheet about 80 um apart. Correlate the team's ink
   map of each trace at matched 3D points, by gap between the traces, against an in-plane
   displaced-match null. How much does an ink reading change when the trace moves?
2. Labelled area: how much papyrus the PHerc0841 benchmark rests on.
3. Noise floor of AUC: a block bootstrap (1 mm blocks) of the AUC on each segment, to show how
   large a difference between two readers has to be before it is more than sampling noise.

    python trace_and_noise.py DATA_DIR
DATA_DIR holds mesh/<name>/{x,y,z}.tif, inkdet/<name>/*.tif and 0841-<name>_labels/.
"""
import glob, os, sys, json
import numpy as np, tifffile, zarr
from scipy.ndimage import zoom, binary_erosion
from scipy.spatial import cKDTree
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..")
sys.path.insert(0, ROOT)
from kit import auc
SEGS = json.load(open(os.path.join(ROOT, "docs", "results.json")))["segments"]
D = sys.argv[1] if len(sys.argv) > 1 else "data"
UP = 4
rng = np.random.default_rng(20261007)

def load(name):
    seg = "0841-" + name; H, W = SEGS[seg]["surface_shape"]; vox = SEGS[seg]["voxel_um"]
    xyz = np.stack([tifffile.imread(f"{D}/mesh/{name}/{c}.tif") for c in "xyz"], -1).astype(np.float64)
    valid = (xyz > 0).all(-1)
    xyzu = np.stack([zoom(xyz[..., i], UP, order=1) for i in range(3)], -1)
    vu = binary_erosion(zoom(valid.astype(np.float32), UP, order=0) > 0.5, iterations=UP)
    gh, gw = vu.shape
    lab = zarr.open(f"{D}/{seg}_labels/inklabels.zarr", mode="r")
    sup = zarr.open(f"{D}/{seg}_labels/supervision.zarr", mode="r")
    L2 = np.asarray(lab["2"]) > 0; S2 = np.asarray(sup["2"]) > 0
    ink = tifffile.imread(glob.glob(f"{D}/inkdet/{name}/*.tif")[0])          # level-0 label grid
    h4, w4 = ink.shape[0] // 4, ink.shape[1] // 4
    ink2 = ink[:h4 * 4, :w4 * 4].reshape(h4, 4, w4, 4).mean((1, 3)).astype(np.float32)
    ink2 = np.pad(ink2, ((0, L2.shape[0] - h4), (0, L2.shape[1] - w4)))        # level-2 grid
    # mesh grid point -> level-2 label pixel (mesh grid spans the surface; labels span it at a uniform scale)
    rows = np.clip(((np.arange(gh) + 0.5) / gh * L2.shape[0]).astype(int), 0, L2.shape[0] - 1)
    cols = np.clip(((np.arange(gw) + 0.5) / gw * L2.shape[1]).astype(int), 0, L2.shape[1] - 1)
    g = np.ix_(rows, cols)
    return dict(xyz=xyzu, v=vu, ink=L2[g], sup=S2[g], det=ink2[g], L2=L2, S2=S2, ink2=ink2, vox=vox,
                lab_um=2.403 * 4)

S = {n: load(n) for n in ["w00", "ag896", "ag405"]}
step_um = 20 / UP * 9.366
out = {}

# 1. trace consistency
A, B = S["w00"], S["ag896"]
pb_idx = np.argwhere(B["v"]); tree = cKDTree(B["xyz"][B["v"]])
dd, j = tree.query(A["xyz"][A["v"]], k=1)
ay, ax = np.nonzero(A["v"]); by, bx = pb_idx[j, 0], pb_idx[j, 1]
a_det, b_det = A["det"][ay, ax], B["det"][by, bx]
on = (a_det > 0) & (b_det > 0)
rows = []
print("1. team ink map, w00 trace against ag896 trace at matched points")
for lo, hi in [(0, 3), (3, 6), (6, 9), (9, 12), (12, 18), (18, 30)]:
    m = on & (dd > lo) & (dd <= hi)
    if m.sum() < 1000: continue
    r = float(np.corrcoef(a_det[m], b_det[m])[0, 1])
    nulls = []
    for _ in range(50):
        rad = rng.uniform(21, 64); t = rng.uniform(0, 2 * np.pi)
        ny = np.clip(by[m] + int(round(rad * np.sin(t))), 0, B["v"].shape[0] - 1)
        nx = np.clip(bx[m] + int(round(rad * np.cos(t))), 0, B["v"].shape[1] - 1)
        bd = B["det"][ny, nx]; ok = bd > 0
        nulls.append(float(np.corrcoef(a_det[m][ok], bd[ok])[0, 1]))
    row = dict(gap_vox=f"{lo}-{hi}", gap_um=f"{lo*9.366:.0f}-{hi*9.366:.0f}", points=int(m.sum()),
               cm2=round(int(m.sum()) * (step_um * 1e-4) ** 2, 2), pearson=round(r, 3),
               null_mean=round(float(np.mean(nulls)), 3), null_max=round(float(np.max(nulls)), 3))
    rows.append(row); print("  ", row, flush=True)
out["trace_consistency"] = rows

# 2. labelled area
print("2. labelled area")
area = {}
for n, s in S.items():
    px = (s["lab_um"] * 1e-4) ** 2
    sup_cm2 = float(s["S2"].sum() * px); ink_cm2 = float((s["S2"] & s["L2"]).sum() * px)
    surf_cm2 = float(s["v"].sum() * (step_um * 1e-4) ** 2)
    area[n] = dict(surface_cm2=round(surf_cm2, 1), supervised_cm2=round(sup_cm2, 2), ink_cm2=round(ink_cm2, 2),
                   supervised_share=round(sup_cm2 / surf_cm2, 3))
    print("  ", n, area[n])
out["area"] = area

# 3. block bootstrap of AUC, team map against labels, level-2 grid, 1 mm blocks
print("3. AUC block bootstrap (team 2.4 um map against the labels; labels may have been drawn with its help)")
boot = {}
for n, s in S.items():
    det, L, Sm = s["ink2"], s["L2"], s["S2"] & (s["ink2"] > 0)
    blk = int(round(1000 / s["lab_um"]))                      # about 104 px of 9.6 um
    by_, bx_ = np.nonzero(Sm)
    keys = (by_ // blk) * 100000 + (bx_ // blk)
    uk, inv = np.unique(keys, return_inverse=True)
    q = np.clip(det[by_, bx_].astype(np.int64), 0, 255); lab = L[by_, bx_]
    # per-block histograms for fast resampling
    hi = np.zeros((len(uk), 256)); hb = np.zeros((len(uk), 256))
    np.add.at(hi, (inv[lab], q[lab]), 1); np.add.at(hb, (inv[~lab], q[~lab]), 1)
    def auc_h(a, b):
        below = np.concatenate(([0.0], np.cumsum(b)[:-1]))
        return float((a * below).sum() + 0.5 * (a * b).sum()) / (a.sum() * b.sum())
    full = auc_h(hi.sum(0), hb.sum(0))
    bs = []
    for _ in range(300):
        w = np.bincount(rng.integers(0, len(uk), len(uk)), minlength=len(uk)).astype(float)
        bs.append(auc_h(w @ hi, w @ hb))
    lo_, hi_ = np.percentile(bs, [2.5, 97.5])
    boot[n] = dict(auc=round(full, 4), ci95=[round(lo_, 4), round(hi_, 4)], half_width=round((hi_ - lo_) / 2, 4), blocks_1mm=len(uk))
    print("  ", n, boot[n], flush=True)
out["bootstrap"] = boot
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace_and_noise.json"), "w"), indent=1)

# confound check for 1: is there as much ink signal (map spread, labelled ink) at every gap?
print("1b. per gap: map spread on each trace and share of points with labelled ink on w00")
for lo, hi in [(0, 3), (3, 6), (6, 9), (9, 12), (12, 18), (18, 30)]:
    m = on & (dd > lo) & (dd <= hi)
    if m.sum() < 1000: continue
    sup_a = A["sup"][ay, ax][m]
    print(f"   gap {lo}-{hi}: w00 map mean {a_det[m].mean():.1f} sd {a_det[m].std():.1f}; ag896 mean {b_det[m].mean():.1f} sd {b_det[m].std():.1f}; "
          f"w00 p90-p10 {np.percentile(a_det[m],90)-np.percentile(a_det[m],10):.0f}; labelled pts {int(sup_a.sum())}, ink share {A['ink'][ay, ax][m][sup_a].mean() if sup_a.any() else float('nan'):.2f}")
