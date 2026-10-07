"""FROZEN: the exact script behind results/*.json (2026-10-07, run_mac.sh). It predates the
support corrections in checks.py (unknown supervision, mesh holes); use checks.py for new runs.

Lane B label-free checks on PHerc0841 (2026-10-07).

For one segment, on its 9.366 um surface grid, compare the team's 2.4 um ink map (model output,
4x4 block mean) with quantities that need no labels: mesh geometry, papyrus fiber orientation from
raw CT, its own spatial autocorrelation, stroke widths, and raw CT at each depth. The human labels
are used only as a reference: the same statistic on the labels says what real text gives.

    python checks.py DATA_DIR SEGMENT MAP [--control MAP_REVERSE] [--mesh MESH_DIR] > OUT.json

SEGMENT is a key of docs/results.json "segments" (w045, 0841-w00, ...). DATA_DIR holds
<SEGMENT>_9um.zarr and <SEGMENT>_labels/. MAP is any ink map of the whole surface (a 2.4 um map
is 4x4 block-averaged first); --control is scored identically (reverse-depth map), so every
label-free statistic has a control. --mesh is a 9.366 um tifxyz folder (x.tif, y.tif, z.tif).
"""
import glob, json, os, sys
import numpy as np, tifffile, zarr
from scipy import ndimage as ndi
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import laneb_run_2026_10_07 as L  # noqa: E402  (frozen copy used for results/)
SEGS = json.load(open(os.path.join(HERE, "..", "..", "..", "docs", "results.json")))["segments"]
import argparse
ap = argparse.ArgumentParser()
ap.add_argument("data"); ap.add_argument("segment"); ap.add_argument("map")
ap.add_argument("--control"); ap.add_argument("--mesh")
A = ap.parse_args()
D, seg = A.data, A.segment
H, W = SEGS[seg]["surface_shape"]; VOX = SEGS[seg]["voxel_um"]
rng = np.random.default_rng(20261007)
out = {"segment": seg, "map": os.path.basename(A.map), "control": A.control and os.path.basename(A.control), "voxel_um": VOX, "surface_shape": [H, W]}
log = lambda *a: print(*a, file=sys.stderr, flush=True)


def resample(a, shape):
    """Proportional nearest sampling of a onto shape (as collation.py does)."""
    ri = np.clip(((np.arange(shape[0]) + 0.5) / shape[0] * a.shape[0]).astype(int), 0, a.shape[0] - 1)
    ci = np.clip(((np.arange(shape[1]) + 0.5) / shape[1] * a.shape[1]).astype(int), 0, a.shape[1] - 1)
    return a[np.ix_(ri, ci)]


def load_map(path):
    m = tifffile.imread(path)
    if m.ndim == 3:
        m = m[..., 0] if m.shape[-1] < 5 else m[0]
    f = 4 if m.shape[0] > 2.5 * H else 1
    if f > 1:
        h4, w4 = m.shape[0] // 4, m.shape[1] // 4
        m4 = np.empty((h4, w4), np.float32)
        for r0 in range(0, h4, 512):
            r1 = min(h4, r0 + 512)
            m4[r0:r1] = m[r0 * 4:r1 * 4, :w4 * 4].reshape(r1 - r0, 4, w4, 4).mean((1, 3))
        m = m4
    return resample(m.astype(np.float32), (H, W))


ink = load_map(A.map)
ctl = load_map(A.control) if A.control else None
log("ink loaded")
vol = np.asarray(zarr.open(f"{D}/{seg}_9um.zarr/0", mode="r")[:])
assert vol.shape[1:] == (H, W), vol.shape
surf = ndi.binary_erosion(vol.max(0) > 0, iterations=8) & (ink > 0)
if ctl is not None:
    surf &= ctl > 0
thick = vol[4:25].astype(np.float32).mean(0)
labels = resample(np.asarray(zarr.open(f"{D}/{seg}_labels/inklabels.zarr/2", mode="r")[:]) > 0, (H, W))
supv = resample(np.asarray(zarr.open(f"{D}/{seg}_labels/supervision.zarr/2", mode="r")[:]) > 0, (H, W)) & surf
labf = labels.astype(np.float32)
out["surface_px"] = int(surf.sum()); out["supervised_px"] = int(supv.sum()); out["label_ink_px"] = int((labels & supv).sum())
log("volume and labels loaded")

MS = int(2000 / VOX)          # null shifts of at least 2 mm in the surface plane
shifts = [(int(rng.integers(MS, H - MS)), int(rng.integers(MS, W - MS))) for _ in range(30)]
maps = {"map": ink}
if ctl is not None:
    maps["control"] = ctl


def rnull(x, y, m):
    real, null = L.block_shift_null(x, np.nan_to_num(y), m, shifts)
    null = null[np.isfinite(null)]
    return dict(r=round(real, 4), null_mean=round(float(null.mean()), 4), null_abs_max=round(float(np.abs(null).max()), 4))


# 1. geometry: does the map follow the mesh (normal direction, stretch, bending)?
if A.mesh:
    xyz = np.stack([tifffile.imread(f"{A.mesh}/{c}.tif") for c in "xyz"], -1).astype(np.float64)
    valid = (xyz > 0).all(-1)
    nrm = L.normals_from_xyz(xyz, valid)
    stretch = L.stretch_from_xyz(xyz); stretch[~valid] = np.nan
    bend = np.sum(np.abs(np.gradient(nrm, axis=0)) + np.abs(np.gradient(nrm, axis=1)), -1)
    geo = {k: resample(v, (H, W)).astype(np.float32) for k, v in
           dict(normal_z=np.abs(nrm[..., 2]), stretch=stretch, bend=bend).items()}
    gm = surf & np.all([np.isfinite(v) for v in geo.values()], 0)
    out["geometry"] = {k: dict({n: rnull(m, v, gm) for n, m in maps.items()},
                               labels_in_supervision=rnull(labf, v, gm & supv)) for k, v in geo.items()}
    out["geometry"]["ct_thick_brightness"] = dict({n: rnull(m, thick, surf) for n, m in maps.items()},
                                                  labels_in_supervision=rnull(labf, thick, supv))
    log("geometry done")

# 2. papyrus fibers (structure tensor of thick-slab CT) vs orientation of map edges
sw = 80 / VOX
fib_a, fib_c = L.orientation(thick, 1.0, sw)
fib_ok = surf & (fib_c > np.percentile(fib_c[surf], 50))
grad = lambda f: np.hypot(ndi.sobel(f, 0), ndi.sobel(f, 1))


def align(img, m, tol=np.deg2rad(15)):
    a, c = L.orientation(img, 1.0, sw); g = grad(img)
    sel = m & (g > np.percentile(g[m], 80)) & (c > 0.3)
    real = float((L.axial_diff(a[sel], fib_a[sel]) < tol).mean())
    null = []
    for dy, dx in shifts[:20]:
        fa = np.roll(fib_a, (dy, dx), (0, 1)); s2 = sel & np.roll(fib_ok, (dy, dx), (0, 1))
        null.append(float((L.axial_diff(a[s2], fa[s2]) < tol).mean()))
    return dict(share_within_15deg=round(real, 4), shifted_null_mean=round(float(np.mean(null)), 4),
                shifted_null_max=round(float(np.max(null)), 4), px=int(sel.sum()))


out["fibers"] = {"fiber_angle_hist_12bins_15deg_from_0": [round(float(x), 4) for x in L.angle_hist(fib_a[fib_ok], fib_c[fib_ok])],
                 "labels_in_supervision": align(labf, fib_ok & supv)}
for n, m in maps.items():
    out["fibers"][n + "_whole"] = align(m, fib_ok)
    out["fibers"][n + "_in_supervision"] = align(m, fib_ok & supv)
log("fibers done")

# 3. stroke widths of the map thresholded without labels (Otsu over the surface); labels as reference
q = lambda w: dict(n=int(w.size), p25=round(float(np.percentile(w, 25)), 1), median=round(float(np.median(w)), 1),
                   p75=round(float(np.percentile(w, 75)), 1)) if w.size else None
out["strokes"] = {"labels_um": q(L.stroke_widths(labels & supv) * VOX),
                  "label_ink_share_in_supervision": round(float(labels[supv].mean()), 4)}
for n, m in maps.items():
    t = L.otsu(m[surf]); mk = (m > t) & surf
    out["strokes"][n] = {"otsu": round(t, 3), "area_share_above": round(float(mk[surf].mean()), 4),
                         "whole_um": q(L.stroke_widths(mk) * VOX), "in_supervision_um": q(L.stroke_widths(mk & supv) * VOX),
                         "dice_with_labels_in_supervision": round(float(2 * (mk & labels & supv).sum() / max((mk & supv).sum() + (labels & supv).sum(), 1)), 4)}
log("strokes done")

# 4. depth: which raw CT layer does the map's letter-scale (48 um high-pass) pattern follow?
sg = 48 / VOX
hpf = lambda f: f - ndi.gaussian_filter(f, sg)
hps = {n: hpf(m) for n, m in maps.items()}; lab_hp = hpf(labf)
prof = {n: [] for n in list(maps) + ["labels"]}
for k in range(vol.shape[0]):
    f = hpf(vol[k].astype(np.float32))
    for n, h in hps.items():
        prof[n].append(round(float(np.corrcoef(h[surf], f[surf])[0, 1]), 4))
    prof["labels"].append(round(float(np.corrcoef(lab_hp[supv], f[supv])[0, 1]), 4))
out["depth"] = {n + "_hp_vs_ct_layer_hp_r": p for n, p in prof.items()}
out["depth"].update({n + "_peak_layer_by_abs": int(np.argmax(np.abs(p))) for n, p in prof.items()})
print(json.dumps(out, indent=1))
