"""The arms of the ink offset diagnostic: 28-layer stacks cut from one wide render along the mesh normal.

The wide render holds offsets -(13.5 + MAX_SHIFT) to +(13.5 + MAX_SHIFT) in whole voxels along n_pub (odgeom), so
index i is offset i - 13.5 - MAX_SHIFT. Arm layer j (of 28) is the render at offset j - 13.5 + s, s the arm's shift:

  Rm8, Rm4, R0, Rp4, Rp8   s constant (-8, -4, 0, +4, +8)
  SNAP                     s = the pixel's offset to villa's lasagna cos maximum nearest the mesh, smoothed
                           (Gaussian, sigma one grid point of STRIDE px), rounded to whole voxels, clipped to MAX_SHIFT
  ANTI                     s = -SNAP's (the same magnitudes, the other way)
  RAND                     s = SNAP's field turned 180 degrees in the box (same values and smoothness, wrong places)

ANTI and RAND are the controls for SNAP: a correction that helps must beat moves of the same size in the wrong
direction or at the wrong places.
"""
import numpy as np

LAYERS = 28
MAX_SHIFT = 8
STRIDE = 8               # px between lasagna offset samples
SIGMA = 1.0              # smoothing, in grid points (STRIDE px)
CONST = (-8, -4, 0, 4, 8)
ARMS = ("R0", "Rm8", "Rm4", "Rp4", "Rp8", "SNAP", "ANTI", "RAND")


def arm_name(s):
    return "R0" if s == 0 else f"R{'p' if s > 0 else 'm'}{abs(s)}"


def take(big, r, layers=LAYERS, max_shift=MAX_SHIFT):
    """layers per pixel from the wide render big at index j + max_shift + r (r an (H, W) int array, |r| <= max_shift)."""
    r = np.asarray(r, np.int64)
    if np.abs(r).max(initial=0) > max_shift:
        raise ValueError(f"shift beyond {max_shift} voxels")
    if big.shape[0] != layers + 2 * max_shift:
        raise ValueError(f"the wide render has {big.shape[0]} layers, expected {layers + 2 * max_shift}")
    idx = np.arange(layers)[:, None, None] + max_shift + r[None]
    return np.take_along_axis(big, idx, axis=0)


def shift_field(d, ok, shape, stride=STRIDE, sigma=SIGMA):
    """The per-pixel lasagna offset on an (H, W) box from samples d on the stride grid (NaN where no peak), valid
    where ok: a normalized Gaussian smoothing (sigma grid points) that ignores missing samples, then bilinear
    upsampling. Returns the float field and a summary."""
    from scipy import ndimage
    d = np.asarray(d, np.float64)
    w = (ok & np.isfinite(d)).astype(np.float64)
    num = ndimage.gaussian_filter(np.where(w > 0, d, 0.0), sigma)
    den = ndimage.gaussian_filter(w, sigma)
    ds = np.where(den > 0.2, num / np.maximum(den, 1e-9), 0.0)
    H, W = shape
    yy, xx = np.meshgrid(np.arange(H) / stride, np.arange(W) / stride, indexing="ij")
    full = ndimage.map_coordinates(ds, [yy.ravel(), xx.ravel()], order=1, mode="nearest").reshape(H, W)
    sel = ds[ok] if ok.any() else np.zeros(1)
    return full, {"coverage": float(w[ok].mean()) if ok.any() else 0.0, "median": float(np.median(sel)),
                  "pct": np.percentile(sel, [5, 25, 50, 75, 95]).round(2).tolist()}


def arm_shifts(snap_field, valid, max_shift=MAX_SHIFT):
    """Every arm's (H, W) int shift field from the float SNAP field; 0 where the render is invalid."""
    snap = np.clip(np.rint(snap_field), -max_shift, max_shift).astype(np.int64)
    snap[~valid] = 0
    arms = {arm_name(s): np.full(valid.shape, s, np.int64) for s in CONST}
    arms["SNAP"] = snap
    arms["ANTI"] = -snap
    rand = snap[::-1, ::-1].copy()
    rand[~valid] = 0
    arms["RAND"] = rand
    return {a: arms[a] for a in ARMS}


def shift_summary(r, valid):
    v = r[valid] if valid.any() else np.zeros(1)
    return {"shift_mean": float(v.mean()), "shift_abs_mean": float(np.abs(v).mean()),
            "shift_pct": np.percentile(v, [5, 25, 50, 75, 95]).tolist()}


def layer_corr(a, b, mask):
    """Per-layer Pearson r of two stacks inside mask: (min, median)."""
    cs = [float(np.corrcoef(a[j][mask].astype(np.float64), b[j][mask].astype(np.float64))[0, 1])
          for j in range(a.shape[0])]
    return {"min": round(min(cs), 4), "median": round(float(np.median(cs)), 4)}


def write_zarr(path, arr):
    """A zarr group with the stack as array "0", chunks (layers, 128, 128): the layout villa's ink inference reads."""
    import zarr
    g = zarr.open_group(str(path), mode="w")
    data = np.ascontiguousarray(arr)
    chunks = (arr.shape[0], 128, 128)
    if hasattr(g, "create_array"):
        g.create_array("0", data=data, chunks=chunks)
    else:                                       # zarr 2
        g.create_dataset("0", data=data, chunks=chunks)


def read_zarr(path):
    import zarr
    return np.asarray(zarr.open_group(str(path), mode="r")["0"][:])
