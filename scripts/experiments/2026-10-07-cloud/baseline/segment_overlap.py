"""Do PHerc0841's three labelled segments trace the same papyrus? Mesh-to-mesh distances in 3D
and label agreement where two traces run together, with an in-plane displaced-match null.

    python segment_overlap.py DATA_DIR
DATA_DIR holds mesh/<w00|ag896|ag405>/{x,y,z}.tif (the 9.366 um tifxyz meshes, `kit fetch
PHerc0841/segments/<segment>/mesh/<id>-on-20250821151531-9.366um.tifxyz`) and
0841-<name>_labels/{inklabels,supervision}.zarr.
"""
import os, sys, json, numpy as np, tifffile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..")
sys.path.insert(0, ROOT)
from kit import auc
from scipy.ndimage import zoom, binary_erosion
from scipy.spatial import cKDTree
SEGS = json.load(open(os.path.join(ROOT, "docs", "results.json")))["segments"]
D = sys.argv[1] if len(sys.argv) > 1 else "data"
UP = 4   # mesh grid is 1/20 of the surface grid; upsample to 1/5 (47 um spacing)
def load(name):
    seg = "0841-" + name; H, W = SEGS[seg]["surface_shape"]
    xyz = np.stack([tifffile.imread(f"{D}/mesh/{name}/{c}.tif") for c in "xyz"], -1).astype(np.float64)
    valid = (xyz > 0).all(-1)
    xyzu = np.stack([zoom(xyz[..., i], UP, order=1) for i in range(3)], -1)
    vu = binary_erosion(zoom(valid.astype(np.float32), UP, order=0) > 0.5, iterations=UP)
    gh, gw = vu.shape
    rows = np.clip(((np.arange(gh) + 0.5) * H / gh).astype(int), 0, H - 1)
    cols = np.clip(((np.arange(gw) + 0.5) * W / gw).astype(int), 0, W - 1)
    ink, sup = auc.labels_on_map(f"{D}/{seg}_labels/inklabels.zarr", f"{D}/{seg}_labels/supervision.zarr", "2", (H, W), None, (H, W))
    y0, y1, x0, x1 = SEGS[seg]["crop"]
    crop = np.zeros((H, W), bool); crop[y0 + 64:y1 - 64, x0 + 64:x1 - 64] = True
    return dict(xyz=xyzu, v=vu, ink=ink[np.ix_(rows, cols)], sup=sup[np.ix_(rows, cols)], crop=crop[np.ix_(rows, cols)])
S = {n: load(n) for n in ["w00", "ag896", "ag405"]}
step_um = 20 / UP * 9.366
def dice(x, y): return 2 * float((x & y).sum()) / max(1, int(x.sum() + y.sum()))
A, B = S["w00"], S["ag896"]
pb_idx = np.argwhere(B["v"]); tree = cKDTree(B["xyz"][B["v"]])
d = np.full(A["v"].shape, np.inf); jy = np.zeros(A["v"].shape, int); jx = np.zeros(A["v"].shape, int)
dd, j = tree.query(A["xyz"][A["v"]], k=1)
d[A["v"]] = dd; jy[A["v"]] = pb_idx[j, 0]; jx[A["v"]] = pb_idx[j, 1]
both = A["v"] & (d <= 12) & A["sup"] & B["sup"][jy, jx]
x, y = A["ink"][both], B["ink"][jy, jx][both]
obs = dice(x, y)
# null: displace the match on B's grid by 1 to 3 mm in-plane (21 to 64 grid steps), 200 draws
rng = np.random.default_rng(20261007); nulls = []
for _ in range(200):
    r = rng.uniform(21, 64); t = rng.uniform(0, 2 * np.pi)
    sy, sx = int(round(r * np.sin(t))), int(round(r * np.cos(t)))
    ny, nx = jy + sy, jx + sx
    ok = A["v"] & (d <= 12) & A["sup"] & (ny >= 0) & (ny < B["v"].shape[0]) & (nx >= 0) & (nx < B["v"].shape[1])
    ny, nx = np.clip(ny, 0, B["v"].shape[0] - 1), np.clip(nx, 0, B["v"].shape[1] - 1)
    ok &= B["v"][ny, nx] & B["sup"][ny, nx]
    if ok.sum() > 500: nulls.append(dice(A["ink"][ok], B["ink"][ny, nx][ok]))
nulls = np.array(nulls)
print(f"w00 vs ag896, both labelled within 12 vox: {int(both.sum())} pts ({both.sum()*(step_um*1e-4)**2:.3f} cm2), Dice {obs:.3f}; "
      f"in-plane displaced null ({len(nulls)} draws): mean {nulls.mean():.3f}, 99th pct {np.percentile(nulls,99):.3f}, max {nulls.max():.3f}")
# do the scoring crops sit on the same papyrus?
for a, b in [("w00", "ag896"), ("w00", "ag405"), ("ag896", "ag405")]:
    P, Q = S[a], S[b]
    m = P["v"] & P["crop"]
    dq, jq = cKDTree(Q["xyz"][Q["v"]]).query(P["xyz"][m], k=1)
    qi = np.argwhere(Q["v"])[jq]
    in_crop = Q["crop"][qi[:, 0], qi[:, 1]]
    print(f"crop of {a}: share within 12 vox of {b}: {(dq<=12).mean():.3f}; of those, landing inside {b}'s crop: {in_crop[dq<=12].mean() if (dq<=12).any() else 0:.3f}")
# where do w00 and ag896 diverge? distance along w00's normal (sign) summary
print("w00->ag896 gap percentiles (vox):", np.percentile(d[A["v"]], [5, 25, 50, 75, 95]).round(1))
# whole-segment distances between every pair of traces
for a, b in [("w00", "ag896"), ("ag896", "w00"), ("w00", "ag405"), ("ag896", "ag405")]:
    P, Q = S[a], S[b]
    dq, _ = cKDTree(Q["xyz"][Q["v"]]).query(P["xyz"][P["v"]], k=1)
    print(f"{a} -> {b}: {P['v'].sum() * (step_um * 1e-4) ** 2:.1f} cm2, median gap {np.median(dq):.1f} vox, "
          + ", ".join(f"within {t}: {(dq <= t).mean():.3f}" for t in (5, 12, 25, 50)))
