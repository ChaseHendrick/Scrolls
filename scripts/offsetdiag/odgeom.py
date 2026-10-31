"""Mesh geometry, renders along the mesh normal, and villa's lasagna sheet center along the same normal.

Offsets are in base scan voxels along n_pub, the normal of the published surface volume: layer j of its L layers sits
at offset j - (L - 1) / 2, so for 28 layers layer 0 is at -13.5 and layer 27 at +13.5. "Minus" moves toward layer 0.
n_pub is `normal_sign` times the cross product of the mesh's column and row derivatives (x, y, z order);
`validate` checks the sign against the published surface volume.
"""
import json
from pathlib import Path

import numpy as np

RENDER_TILE = 256        # px per render tile
PEAK_MAX_ABS = 8.0       # voxels: the cos maximum must lie this close to the mesh
PEAK_MIN_VAL = 160       # the cos maximum must reach this (uint8 cos)


def load_mesh(folder):
    """(xyz (3, h, w) float64 in x, y, z order, valid mask, grid scale) from a tifxyz folder."""
    import tifffile
    d = Path(folder)
    xyz = np.stack([tifffile.imread(d / f"{a}.tif").astype(np.float64) for a in "xyz"])
    valid = (xyz > 0).all(0)
    scale = 0.05
    meta = d / "meta.json"
    if meta.exists():
        s = json.loads(meta.read_text()).get("scale")
        if s:
            scale = float(s[0] if isinstance(s, (list, tuple)) else s)
    return xyz, valid, scale


def coarse_normals(xyz, valid):
    """Unit normals on the mesh grid: cross product of the column and row derivatives (x, y, z order); NaN where
    the mesh is invalid."""
    P = np.where(valid[None], xyz, np.nan)
    dr = np.gradient(P, axis=1)
    dc = np.gradient(P, axis=2)
    n = np.cross(dc, dr, axis=0)
    n /= np.linalg.norm(n, axis=0, keepdims=True)
    return n


def surface_grid(xyz, valid, rows, cols, scale=0.05, normal_sign=-1, step=1):
    """Positions (3, H, W), unit n_pub normals (3, H, W) and a valid mask on surface pixels rows x cols (half-open
    ranges, every `step`-th pixel): the mesh upsampled bilinearly from its grid; a pixel is valid when all four
    coarse neighbors are."""
    from scipy import ndimage
    n = coarse_normals(xyz, valid)
    ii, jj = np.meshgrid(np.arange(*rows, step) * scale, np.arange(*cols, step) * scale, indexing="ij")
    co = np.stack([ii.ravel(), jj.ravel()])
    pos = np.stack([ndimage.map_coordinates(np.nan_to_num(xyz[k]), co, order=1, mode="nearest")
                    for k in range(3)]).reshape(3, *ii.shape)
    nor = np.stack([ndimage.map_coordinates(np.nan_to_num(n[k]), co, order=1, mode="nearest")
                    for k in range(3)]).reshape(3, *ii.shape)
    nor = normal_sign * nor / (np.linalg.norm(nor, axis=0, keepdims=True) + 1e-12)
    okn = (np.isfinite(n).all(0) & valid).astype(np.float64)
    ok = ndimage.map_coordinates(okn, co, order=1, mode="constant", cval=0).reshape(ii.shape) > 0.999
    return pos, nor, ok


def render(mesh, scan, offsets, rows, cols, normal_sign=-1, shift=None, tile=RENDER_TILE, log=None):
    """(len(offsets), H, W) float32: the scan sampled trilinearly at pos + (o + shift) * n_pub for each offset o, on
    surface pixels rows x cols. mesh is load_mesh's (xyz, valid, scale); scan a Zarr2 of the base scan (z, y, x);
    shift an optional (H, W) per-pixel extra offset in voxels. Pixels without a valid mesh are 0."""
    xyz, valid, scale = mesh
    H, W = rows[1] - rows[0], cols[1] - cols[0]
    out = np.zeros((len(offsets), H, W), np.float32)
    for r in range(0, H, tile):
        for c in range(0, W, tile):
            rr = (rows[0] + r, min(rows[0] + r + tile, rows[1]))
            cc = (cols[0] + c, min(cols[0] + c + tile, cols[1]))
            pos, nor, ok = surface_grid(xyz, valid, rr, cc, scale, normal_sign)
            if not ok.any():
                continue
            h, w = ok.shape
            sh = 0.0 if shift is None else shift[r:r + h, c:c + w]
            pts = np.concatenate([(pos + (o + sh) * nor)[:, ok] for o in offsets], axis=1)
            v = scan.sample(pts[::-1]).reshape(len(offsets), -1)
            for k in range(len(offsets)):
                out[k, r:r + h, c:c + w][ok] = v[k]
        if log:
            log(f"rows {rows[0] + r}..{rows[0] + min(r + tile, H)} of {rows[1]}")
    return out


def stack_offsets(layers=28, extra=0):
    """The offsets of a layers-deep stack centered on the surface, widened by `extra` voxels on each side."""
    half = (layers - 1) / 2.0
    return np.arange(-half - extra, half + extra + 0.001, 1.0)


def match_layers(published, rendered, offsets, mask):
    """For each published layer j, the render offset whose image correlates best with it inside mask:
    a list of (j, best offset, r)."""
    best = []
    R = []
    for k in range(rendered.shape[0]):
        b = rendered[k][mask].astype(np.float64)
        R.append((b - b.mean()) / (b.std() + 1e-6))
    for j in range(published.shape[0]):
        a = published[j][mask].astype(np.float64)
        a = (a - a.mean()) / (a.std() + 1e-6)
        cs = [float((a * b).mean()) for b in R]
        k = int(np.argmax(cs))
        best.append((j, float(offsets[k]), round(cs[k], 4)))
    return best


def check_layers(best, layers=28, min_r=0.9, tol=1.0):
    """True when every published layer j matched offset j - (layers - 1) / 2 within tol voxels with r >= min_r."""
    half = (layers - 1) / 2.0
    return all(abs(o - (j - half)) <= tol and r >= min_r for j, o, r in best)


def cos_profiles(mesh, cos, rows, cols, ts, normal_sign=-1, cos_scale=2.0, stride=8, block=32):
    """cos sampled along n_pub at offsets ts on every stride-th surface pixel: (len(ts), h, w) float32 and the
    (h, w) valid mask. cos is a Zarr2 of villa's cos field at 1 / cos_scale of the base voxel size."""
    xyz, valid, scale = mesh
    pos, nor, ok = surface_grid(xyz, valid, rows, cols, scale, normal_sign, step=stride)
    h, w = ok.shape
    prof = np.zeros((len(ts), h, w), np.float32)
    for a in range(0, h, block):
        for b in range(0, w, block):
            m = ok[a:a + block, b:b + block]
            if not m.any():
                continue
            P = pos[:, a:a + block, b:b + block][:, m]
            N = nor[:, a:a + block, b:b + block][:, m]
            pts = np.concatenate([P + t * N for t in ts], axis=1)
            v = cos.sample(pts[::-1] / cos_scale).reshape(len(ts), -1)
            prof[:, a:a + block, b:b + block][:, m] = v
    return prof, ok


def nearest_peak(prof, ts, max_abs=PEAK_MAX_ABS, min_val=PEAK_MIN_VAL):
    """Offset of the cos maximum nearest to 0 along each profile ((T, ...) array): a local maximum at or above
    min_val within max_abs voxels, refined by a parabola; NaN where there is none."""
    ts = np.asarray(ts, np.float64)
    T = prof.shape[0]
    p = np.asarray(prof, np.float64).reshape(T, -1)
    loc = np.zeros_like(p, bool)
    loc[1:-1] = (p[1:-1] >= p[:-2]) & (p[1:-1] > p[2:]) & (p[1:-1] >= min_val)
    dt = ts[1] - ts[0]
    d = np.full(p.shape[1], np.nan, np.float32)
    absts = np.abs(ts)
    for i in range(p.shape[1]):
        k = np.nonzero(loc[:, i] & (absts <= max_abs))[0]
        if k.size == 0:
            continue
        k = k[np.argmin(absts[k])]
        a, b, c = p[k - 1, i], p[k, i], p[k + 1, i]
        den = a - 2 * b + c
        frac = 0.5 * (a - c) / den if den != 0 else 0.0
        d[i] = ts[k] + float(np.clip(frac, -0.5, 0.5)) * dt
    return d.reshape(prof.shape[1:])
