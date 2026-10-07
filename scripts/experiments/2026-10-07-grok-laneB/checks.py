"""Lane B label-free checks on PHerc0841 (2026-10-07).

For one segment, on its 9.366 um surface grid, compare the team's 2.4 um ink map (model output,
4x4 block mean) with quantities that need no labels: mesh geometry, papyrus fiber orientation from
raw CT, its own spatial autocorrelation, stroke widths, and raw CT at each depth. The human labels
are used only as a reference: the same statistic on the labels says what real text gives.

    python checks.py DATA_DIR SEGMENT > SEGMENT.json      (SEGMENT: w00, ag896, ag405)
Layout as fetch_data.py writes it.
"""
import glob, json, os, sys
import numpy as np, tifffile, zarr
from scipy import ndimage as ndi
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import laneb as L  # noqa: E402
SEGS = json.load(open(os.path.join(HERE, "..", "..", "..", "docs", "results.json")))["segments"]
D, name = sys.argv[1], sys.argv[2]
seg = "0841-" + name
H, W = SEGS[seg]["surface_shape"]; VOX = SEGS[seg]["voxel_um"]
rng = np.random.default_rng(20261007)
out = {"segment": seg, "voxel_um": VOX, "surface_shape": [H, W]}
log = lambda *a: print(*a, file=sys.stderr, flush=True)


def resample(a, shape):
    """Proportional nearest sampling of a onto shape (as collation.py does)."""
    ri = np.clip(((np.arange(shape[0]) + 0.5) / shape[0] * a.shape[0]).astype(int), 0, a.shape[0] - 1)
    ci = np.clip(((np.arange(shape[1]) + 0.5) / shape[1] * a.shape[1]).astype(int), 0, a.shape[1] - 1)
    return a[np.ix_(ri, ci)]


ink0 = tifffile.imread(glob.glob(f"{D}/inkdet/{name}/*.tif")[0])
out["ink_map_shape"] = list(ink0.shape)
h4, w4 = ink0.shape[0] // 4, ink0.shape[1] // 4
ink4 = np.empty((h4, w4), np.float32)
for r0 in range(0, h4, 512):
    r1 = min(h4, r0 + 512)
    ink4[r0:r1] = ink0[r0 * 4:r1 * 4, :w4 * 4].reshape(r1 - r0, 4, w4, 4).mean((1, 3))
del ink0
ink = resample(ink4, (H, W)).astype(np.float32); del ink4
log("ink loaded")
vol = np.asarray(zarr.open(f"{D}/{seg}_9um.zarr/0", mode="r")[:])
assert vol.shape[1:] == (H, W), vol.shape
surf = ndi.binary_erosion(vol.max(0) > 0, iterations=8) & (ink > 0)
thick = vol[4:25].astype(np.float32).mean(0)
labels = resample(np.asarray(zarr.open(f"{D}/{seg}_labels/inklabels.zarr/2", mode="r")[:]) > 0, (H, W))
supv = resample(np.asarray(zarr.open(f"{D}/{seg}_labels/supervision.zarr/2", mode="r")[:]) > 0, (H, W)) & surf
labf = labels.astype(np.float32)
out["surface_px"] = int(surf.sum()); out["supervised_px"] = int(supv.sum()); out["label_ink_px"] = int((labels & supv).sum())
log("volume and labels loaded")

xyz = np.stack([tifffile.imread(f"{D}/mesh/{name}/{c}.tif") for c in "xyz"], -1).astype(np.float64)
valid = (xyz > 0).all(-1)
nrm = L.normals_from_xyz(xyz, valid)
stretch = L.stretch_from_xyz(xyz); stretch[~valid] = np.nan
nz = np.abs(nrm[..., 2])      # |cos| of the angle between surface normal and scan (z) axis
bend = np.sum(np.abs(np.gradient(nrm, axis=0)) + np.abs(np.gradient(nrm, axis=1)), -1)   # normal change per mesh step
geo = {k: resample(v, (H, W)).astype(np.float32) for k, v in dict(normal_z=nz, stretch=stretch, bend=bend).items()}
gm = surf & np.all([np.isfinite(v) for v in geo.values()], 0)

MS = int(2000 / VOX)          # null shifts of at least 2 mm in the surface plane
shifts = [(int(rng.integers(MS, H - MS)), int(rng.integers(MS, W - MS))) for _ in range(30)]


def rnull(x, y, m):
    real, null = L.block_shift_null(x, np.nan_to_num(y), m, shifts)
    null = null[np.isfinite(null)]
    return dict(r=round(real, 4), null_mean=round(float(null.mean()), 4), null_abs_max=round(float(np.abs(null).max()), 4))


out["geometry"] = {k: {"ink_map": rnull(ink, v, gm), "labels_in_supervision": rnull(labf, v, gm & supv)} for k, v in geo.items()}
out["geometry"]["ct_thick_brightness"] = {"ink_map": rnull(ink, thick, surf), "labels_in_supervision": rnull(labf, thick, supv)}
log("geometry done")

sw = 80 / VOX                 # about 80 um structure-tensor window
fib_a, fib_c = L.orientation(thick, 1.0, sw)
ink_a, ink_c = L.orientation(ink, 1.0, sw)
lab_a, lab_c = L.orientation(labf, 1.0, sw)
grad = lambda f: np.hypot(ndi.sobel(f, 0), ndi.sobel(f, 1))
g_ink, g_lab = grad(ink), grad(labf)
fib_ok = surf & (fib_c > np.percentile(fib_c[surf], 50))   # where CT shows a clear fiber direction


def align(a, c, g, m, tol=np.deg2rad(15)):
    sel = m & (g > np.percentile(g[m], 80)) & (c > 0.3)
    real = float((L.axial_diff(a[sel], fib_a[sel]) < tol).mean())
    null = []
    for dy, dx in shifts[:20]:
        fa = np.roll(fib_a, (dy, dx), (0, 1)); s2 = sel & np.roll(fib_ok, (dy, dx), (0, 1))
        null.append(float((L.axial_diff(a[s2], fa[s2]) < tol).mean()))
    return dict(share_within_15deg=round(real, 4), shifted_null_mean=round(float(np.mean(null)), 4),
                shifted_null_max=round(float(np.max(null)), 4), px=int(sel.sum()), uniform_chance=round(30 / 180, 4))


out["fibers"] = {"fiber_angle_hist_12bins_15deg_from_0": [round(float(x), 4) for x in L.angle_hist(fib_a[fib_ok], fib_c[fib_ok])],
                 "ink_map_edges_vs_fibers": align(ink_a, ink_c, g_ink, fib_ok),
                 "ink_map_edges_vs_fibers_in_supervision": align(ink_a, ink_c, g_ink, fib_ok & supv),
                 "label_edges_vs_fibers": align(lab_a, lab_c, g_lab, fib_ok & supv)}
log("fibers done")

ML = int(6000 / VOX)


def ac(img, m):
    py, px = L.autocorr_profile(img.astype(np.float64), m, ML)
    res = dict(half_width_y_um=round(L.first_crossing(py, 0.5) * VOX, 1), half_width_x_um=round(L.first_crossing(px, 0.5) * VOX, 1))
    for ax, p in (("y", py), ("x", px)):
        lag, val = L.first_peak(p, 10)
        res[f"first_peak_{ax}_um"] = None if not np.isfinite(lag) else round(lag * VOX, 1)
        res[f"first_peak_{ax}_value"] = None if not np.isfinite(val) else round(val, 4)
    return res


hp1 = lambda f: f - ndi.gaussian_filter(f, 1000 / VOX)        # drop trends above 1 mm
out["autocorr"] = {"ink_map_surface": ac(hp1(ink), surf), "ink_map_in_supervision": ac(hp1(ink), supv),
                   "labels_in_supervision": ac(labf, supv), "ct_thick_surface": ac(hp1(thick), surf)}
log("autocorr done")

t = L.otsu(ink[surf])
mask_map = (ink > t) & surf
q = lambda w: dict(n=int(w.size), p25=round(float(np.percentile(w, 25)), 1), median=round(float(np.median(w)), 1),
                   p75=round(float(np.percentile(w, 75)), 1)) if w.size else None
out["strokes"] = {"otsu_threshold_0_255": round(t, 2), "map_area_share_above": round(float(mask_map[surf].mean()), 4),
                  "label_ink_share_in_supervision": round(float(labels[supv].mean()), 4),
                  "map_whole_um": q(L.stroke_widths(mask_map) * VOX),
                  "map_in_supervision_um": q(L.stroke_widths(mask_map & supv) * VOX),
                  "labels_um": q(L.stroke_widths(labels & supv) * VOX)}
log("strokes done")

sg = 48 / VOX
ink_hp = ink - ndi.gaussian_filter(ink, sg); lab_hp = labf - ndi.gaussian_filter(labf, sg)
pm, pl = [], []
for k in range(vol.shape[0]):
    f = vol[k].astype(np.float32); f = f - ndi.gaussian_filter(f, sg)
    pm.append(round(float(np.corrcoef(ink_hp[surf], f[surf])[0, 1]), 4))
    pl.append(round(float(np.corrcoef(lab_hp[supv], f[supv])[0, 1]), 4))
out["depth"] = {"ink_map_hp_vs_ct_layer_hp_r": pm, "labels_hp_vs_ct_layer_hp_r": pl,
                "ink_map_peak_layer_by_abs": int(np.argmax(np.abs(pm))), "labels_peak_layer_by_abs": int(np.argmax(np.abs(pl)))}
print(json.dumps(out, indent=1))
