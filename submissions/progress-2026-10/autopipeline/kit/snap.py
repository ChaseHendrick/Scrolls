"""Snap tifxyz meshes along their normals onto the nearest predicted sheet, or onto the midline of the bright CT band.

`kit snap` moves every vertex of a tifxyz mesh (x/y/z.tif in level-0 voxels, -1 for no vertex) a short distance
along its normal, regularises the offsets so the mesh cannot hop between sheets, and writes a new tifxyz folder per
mesh with the bounding box recomputed. It never edits its input. A snapped mesh is geometry; an ink map rendered on
it later is model output, never a reading.

Two sources:

--source pred (default): technique A, a port of Erwin Nieuwlaar's `mesh/snap_meshes.py` from
https://github.com/Nieuwlaar/pherc343-first-letters at commit e8370f1f88a211166056df62ea6fcfffe4a1063e, the code of
his First Letters submission for PHerc. 343 (Sourced fact, that repository's README; the prize was awarded 2026-10-08,
Sourced fact, https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for). Per vertex: a nan-aware
central-difference normal n = cross(d/dcol, d/drow), normalised; 2K + 1 nearest-voxel samples of a
surface-prediction zarr at offsets -K..K voxels (--max-off, default 15) along n; a sample is sheet where its value
is at least --threshold (default 1, which on an integer prediction is his v > 0); the runs of sheet samples, the run
whose centre is nearest 0, his parabolic sub-voxel refinement on the [1, 2, 1]-smoothed profile (the run centre
alone when the parabola's vertex is more than half a sample away); offsets more than --jump (6) voxels from the 5x5
nan-median of their neighbourhood are rejected; rejected and missing offsets are filled by normalised convolution
with a Gaussian of max(sigma, 1) grid cells, then the field is smoothed by normalised convolution with --sigma (1)
and clipped to +-K; a vertex moves only where it has a normal and both the filled and the final fields are finite,
so a vertex with no sheet anywhere near keeps its position, and invalid vertices stay -1. The output meta.json gets
his source note and his "snap" record; his report fields go to snap_report.tsv (appended, as his) and
snap_report.json. The meshes of his submission were snapped with these defaults at level 0 (Sourced fact, his
mesh/README.md).

--source ct --mode midline: technique B, the "midline" variant of RectoRefine, pass 2 of ScrollFiesta's
`scroll_snap` (src/flatten/recto_refine.c and recto_refine.h, src/tools/scroll_snap.c) from
https://github.com/Hob3rMallow/scrollfiesta_public at commit bce8a65f97652316efb084171a17d2f1f8d3ae1a, as a numpy
simplification on the tifxyz grid. Along an outward line per vertex (the mesh normal blended 0.85 with the radial
direction from the scroll axis and flipped outward, or the normal alone when no axis is given) it finds the
dark-to-bright edge of the CT band (a 0.35 isovalue of the 1st to 99th percentile window of the CT at the vertices,
scored by gradient minus a distance bias), walks outward to the next falling crossing of the same band and
targets their midpoint; a vertex with no falling crossing, or a band thinner than 1 voxel, abstains. Then one
global scalar displacement per vertex minimises sum_i w_i (d_i - target_i)^2 + mu sum_(i,j) (d_i - d_j)^2 by 48
Jacobi sweeps over the mesh's edges, each value clipped so neighbours differ by at most 0.55 x the original edge
length; abstaining vertices are anchors pulled to their input position (weight 24). The step is damped (0.70),
capped at 0.85 voxels per outer iteration and 3 voxels in total, reverted where it would land within 0.9 voxels of
another part of the input mesh, and repeated 4 times with fresh normals. Its authors measured the recto-edge
variant as harmful on their 5x3x3 core (2026-09-02: depth seams 1.95% to 5.39%, because adjacent patches snapped
to different local edges; recto_refine.h lines 50 to 57; Community report), so that variant is not ported;
midline is their "one unambiguous target per sheet".

--check (technique C, ours): a self-check that can fail. Each mesh is displaced along its normals by a known smooth
field (--check-shift voxels along the normal for pred, default 4; for ct along RectoRefine's outward line, default
-2, toward the recto side, because the midline search starts from the rising edge within --range 3 voxels; plus
--check-vary x sin x cos with a slope of at most 0.05), the displaced mesh is snapped, and the residual distance to
the reference (the input mesh, or with --check-reference snapped the snap of the undisplaced input) is reported as
median, p90 and the fraction within --check-tol voxels, with the component along the planting direction alongside.
Two controls must not recover: the same snap against the volume read with a constant shift that makes the sheet
appear --control-shift voxels from the input on the planted side (it must not come back within --check-tol of the
reference), and against a volume with no sheet (the mesh must not move at all). Exit status 1 when the recovery
fails or a control passes. The check presumes the input mesh already sits on a sheet; otherwise use
--check-reference snapped. On a rough mesh, whose normals tilt by tens of degrees between neighbours, a planted
displacement also moves vertices sideways, which no snap along the normals undoes, so the check fails there although
each vertex may land on a sheet (Interpretation, from noisy synthetic grids outside the tests: on a 3-voxel grid
over a 5-voxel sheet the pred check passed at a median neighbour normal angle of 24 degrees and failed from 31
degrees).

--sham (ours): the control arm of a snapped render. The mesh is written with every vertex moved by minus the
displacement the snap gave it (the same distance along the same line, to the other side; a vertex the snap left in
place stays), and meta.json's snap record says "sham": true. A sham-snapped render that reads ink as well as the
snapped one says the gain is not from landing on the sheet (docs/plans/2026-10-09-autopipeline-bars.md, stage 1).

Deviations from snap_meshes.py, all deliberate:
- The prediction is read through kit.vc3d_region.Volume and kit.vc3d_prep.sample_nearest (local or https zarr, v2
  or v3, false 404s retried) instead of zarr plus a multiprocessing fork pool; --procs is gone. Points are grouped
  by their full chunk index, where his packed key (cz * 100000 + cy * 300 + cx) can give two chunks one key once
  a grid is more than 300 chunks wide in x, or once cy * 300 + cx can reach 100000 (334 or more chunks in y and
  at least two in z). Values keep the volume's dtype and are compared with --threshold as numbers; his copied
  them into a uint8 array first, so a uint16 value that is a multiple of 256 read as background there and as
  sheet here, and float values below 1 read as background in both.
- Level coordinates are his level-0 coordinate / 2**level by default; --centres uses Volume.to_level instead
  ((p + 0.5) * f - 0.5, voxel centres aligned, a quarter voxel different at level 1). Bounds are his: a sample
  outside [0, size - 0.5) on any axis reads 0.
- scipy.ndimage.gaussian_filter (mode reflect, truncate 4.0) is re-implemented in numpy: separable kernels of the
  same radius int(4 sigma + 0.5), the same reflect padding (period 2n), the same symmetric summation order and a
  float32 round after each axis, which matches scipy 1.18.1 bit for bit on the cases in tests/test_snap.py.
- The run search and the parabola are vectorised over vertices (his loop is kept in tests/test_snap.py and the
  two agree exactly).
- Meshes are given as folders (or, as his, a folder plus --windings naming the meshes in it); a mesh without
  meta.json gets one. His unused --z0/--z1 are not ported. Vertices are sampled in batches (--batch points).
- The snap record in meta.json keeps his keys and adds the tool, what was snapped to, the mode, threshold, level,
  --centres and the volume.

Deviations from RectoRefine (midline), all deliberate:
- tifxyz grid instead of an OBJ: each grid cell gives the two triangles (r, c), (r, c+1), (r+1, c) and
  (r, c+1), (r+1, c+1), (r+1, c), each kept when its three vertices are valid; normals are the area-weighted sums
  of those triangles' normals, as MeshNormals_compute does, and the Jacobi solve runs over their edges.
- The scroll axis is --axis-point and --axis-dir (x y z, level-0 voxels) or an umbilicus file (--umbilicus; the
  axis is then taken as vertical at each vertex: radial = (x - cx(z), y - cy(z), 0)). With neither, the direction
  is the mesh normal as stored (their rl = 0 branch). The sign decides from which side the band can be reached:
  the search starts at the rising edge, so a vertex more than --range past it on the far side abstains.
- The contrast window comes from the CT at the input vertices with their 256-bin rule for uint8 volumes (their
  pass 1 measures it on the same mesh); other dtypes use numpy percentiles; --window LO HI overrides it.
- CT sampling is trilinear over the corners inside the array, renormalised, as their sample_trilinear does, read
  chunk by chunk through Volume's chunk cache; a missing chunk reads 0 (theirs counts a missing cube as absent).
- The occupancy guard is a hash grid over the input vertices instead of a KD-tree, and it checks every hit
  rather than the first 16.
- No OpenMP threads; numpy throughout, float32 storage with float64 arithmetic as theirs (the edge search and
  base_disp run along the double direction, the step along its float copy, as in RectoRefine_run). On synthetic
  bands, folds and volume edges this agreed with recto_refine.c, built with a stub sampler over the same voxels,
  within 2e-5 voxels; the C values are pinned in tests/test_snap.py (MidlineRulesTest).

The two MIT licences, as the sources give them:

    MIT License

    Copyright (c) 2026 Erwin Nieuwlaar

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

    MIT License

    Copyright (c) 2026 Ben Kyles

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

    (ScrollFiesta's licence file adds that it covers ScrollFiesta's own code, not the vendored dependencies under
    deps/src/; nothing from those is used here.)

Needs numpy (imported lazily, so `python -m kit snap --help` works without it). Arrays are (row, col) grids;
points are (x, y, z) in level-0 voxels; volume arrays are (z, y, x).
"""

import json
import math
import os
import sys
import time
from pathlib import Path

PRED_SOURCE_NOTE = " + snap_meshes_local (offset along normal to nearest predicted sheet, regularised)"
MIDLINE_SOURCE_NOTE = (" + kit snap midline (port of ScrollFiesta RectoRefine midline: offset along normal to the "
                       "CT band midline)")
REPORT_COLUMNS = ("winding", "n_valid", "frac_with_sheet", "frac_snapped", "median_abs_off", "p90_abs_off",
                  "frac_rejected", "frac_already_on")
DEFAULT_BATCH = 4_000_000

# RectoRefineOpts_default (recto_refine.c lines 29 to 61) and scroll_snap's pass-2 settings.
MIDLINE_DEFAULTS = {
    "band_frac": 0.35, "range": 3.0, "sample_step": 0.25, "edge_half": 0.5, "min_edge_frac": 0.08,
    "distance_bias": 4.0, "normal_blend": 0.85, "data_weight": 12.0, "anchor_weight": 24.0, "smooth_mu": 1.0,
    "max_slope": 0.55, "damping": 0.70, "max_step": 0.85, "max_total": 3.0, "occ_thresh": 0.9, "local_r": 2.0,
    "midline_min_thick": 1.0, "midline_max_thick": 6.0, "outer_iters": 4, "inner_iters": 48, "tol": 0.02,
    "pct_lo": 1.0, "pct_hi": 99.0,
}


class SnapError(ValueError):
    pass


def _numpy():
    try:
        import numpy
    except ImportError as exc:
        raise SnapError("kit snap needs numpy (pip install numpy, or run inside villa's environment)") from exc
    return numpy


# ---------------------------------------------------------------- meshes

def load_mesh(folder):
    """(xs, ys, zs, valid) of a tifxyz folder as float32 grids; valid as his: every coordinate > -0.5 and finite."""
    np = _numpy()
    d = Path(folder)
    if not (d / "x.tif").is_file():
        raise SnapError(f"{d}: no x.tif (not a tifxyz folder)")
    grids = []
    for a in "xyz":
        try:
            import tifffile
            arr = tifffile.imread(str(d / f"{a}.tif"))
        except ImportError:
            from . import vc3d_io
            r = vc3d_io.read_tiff(d / f"{a}.tif")
            arr = np.asarray(r.floats(), dtype=np.float64).reshape(r.h, r.w)
        grids.append(np.asarray(arr).astype(np.float32))
    xs, ys, zs = grids
    if not (xs.ndim == 2 and xs.shape == ys.shape == zs.shape):
        raise SnapError(f"{d}: x, y and z tifs must be 2-D grids of one size")
    valid = (xs > -0.5) & (ys > -0.5) & (zs > -0.5) & np.isfinite(xs) & np.isfinite(ys) & np.isfinite(zs)
    return xs, ys, zs, valid


def write_mesh(src, out, xs, ys, zs, valid, record, note):
    """Write x/y/z.tif (float32, -1 where invalid) and meta.json (the source's, with a new bbox, the source note
    appended and the snap record) to out."""
    np = _numpy()
    from . import vc3d_io
    meta_path = Path(src) / "meta.json" if src is not None else None
    try:                                   # read it before writing anything, so a bad one leaves no half mesh
        meta = json.loads(meta_path.read_text()) if meta_path is not None and meta_path.is_file() else {
            "format": "tifxyz", "type": "seg"}
    except json.JSONDecodeError as exc:
        raise SnapError(f"{meta_path}: not JSON ({exc})") from exc
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, arr in (("x", xs), ("y", ys), ("z", zs)):
        a = arr.astype(np.float32)
        a[~valid] = -1.0
        vc3d_io.write_tiff(out / f"{name}.tif", vc3d_io.raster_from_numpy(a))
    if valid.any():
        v = valid
        meta["bbox"] = [[float(xs[v].min()), float(ys[v].min()), float(zs[v].min())],
                        [float(xs[v].max()), float(ys[v].max()), float(zs[v].max())]]
    meta["source"] = meta.get("source", "") + note
    meta["snap"] = record
    (out / "meta.json").write_text(json.dumps(meta, indent=4))
    return out


def normals(xs, ys, zs, valid):
    """His normals: central differences where both neighbours are valid, else one-sided, n = cross(d/dcol, d/drow)
    normalised (float32), and ok = a finite normal on a valid vertex."""
    np = _numpy()
    P = np.stack([xs, ys, zs], -1).astype(np.float64)
    P[~valid] = np.nan

    def grad(axis):
        g = np.full_like(P, np.nan)
        fwd = np.roll(P, -1, axis) - P
        bwd = P - np.roll(P, 1, axis)
        n = P.shape[axis]
        idx = [slice(None)] * 3
        idx[axis] = slice(n - 1, n)
        fwd[tuple(idx)] = np.nan
        idx[axis] = slice(0, 1)
        bwd[tuple(idx)] = np.nan
        both = np.isfinite(fwd).all(-1) & np.isfinite(bwd).all(-1)
        g[both] = 0.5 * (fwd[both] + bwd[both])
        only_f = np.isfinite(fwd).all(-1) & ~both
        g[only_f] = fwd[only_f]
        only_b = np.isfinite(bwd).all(-1) & ~both
        g[only_b] = bwd[only_b]
        return g

    tu = grad(1)
    tv = grad(0)
    n = np.cross(tu, tv)
    nn = np.linalg.norm(n, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        n = n / np.where(nn > 1e-6, nn, np.nan)
    ok = np.isfinite(n).all(-1) & valid
    return n.astype(np.float32), ok


# ---------------------------------------------------------------- filters

def gaussian_kernel1d(sigma, radius):
    """scipy.ndimage._gaussian_kernel1d for order 0."""
    np = _numpy()
    x = np.arange(-radius, radius + 1)
    phi = np.exp(-0.5 / (sigma * sigma) * x ** 2)
    return phi / phi.sum()


def _reflect_index(n, r):
    """Indices of a length-n axis padded by r on both sides in scipy's 'reflect' mode (d c b a | a b c d | d c b a,
    repeated with period 2n)."""
    np = _numpy()
    i = np.mod(np.arange(-r, n + r), 2 * n)
    return np.where(i >= n, 2 * n - 1 - i, i)


def gaussian_filter(a, sigma, truncate=4.0):
    """scipy.ndimage.gaussian_filter(a, sigma) with mode 'reflect' and truncate 4.0, in numpy: one 1-D pass per axis
    in axis order, each in float64 and rounded to the input dtype, the symmetric sum taken in scipy's order (centre
    first, then the outermost pair inwards)."""
    np = _numpy()
    a = np.asarray(a)
    out = a.copy()
    sigma = float(sigma)
    if sigma <= 1e-15:
        return out
    r = int(truncate * sigma + 0.5)
    w = gaussian_kernel1d(sigma, r)[::-1]
    for axis in range(a.ndim):
        n = out.shape[axis]
        if n == 0:
            continue
        x = np.take(out.astype(np.float64), _reflect_index(n, r), axis=axis)

        def sl(k, axis=axis, n=n):
            s = [slice(None)] * a.ndim
            s[axis] = slice(k, k + n)
            return tuple(s)

        acc = x[sl(r)] * w[r]
        for j in range(r, 0, -1):
            acc = acc + (x[sl(r - j)] + x[sl(r + j)]) * w[r - j]
        out = acc.astype(a.dtype)
    return out


def nanmedian_filter(d, size=5):
    """His nan-aware median over a size x size window, from a stack of shifted copies (nan outside the grid)."""
    np = _numpy()
    import warnings
    H, W = d.shape
    r = size // 2
    pad = np.pad(d, r, constant_values=np.nan)
    st = np.stack([pad[i:i + H, j:j + W] for i in range(size) for j in range(size)], 0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(st, axis=0)


def normconv(d, sigma):
    """His normalised convolution: Gaussian of the finite values over the Gaussian of their mask, nan where the mask
    weight is at most 1e-3."""
    np = _numpy()
    m = np.isfinite(d).astype(np.float32)
    v = np.where(np.isfinite(d), d, 0).astype(np.float32)
    num = gaussian_filter(v, sigma)
    den = gaussian_filter(m, sigma)
    out = np.full_like(d, np.nan)
    okk = den > 1e-3
    out[okk] = num[okk] / den[okk]
    return out


# ---------------------------------------------------------------- sampling

class Sampler:
    """Reads one level of a zarr volume at level-0 (x, y, z) points. `shift` adds a constant level-0 vector to every
    point (the shifted control); `empty` reads 0 everywhere inside (the no-sheet control)."""

    def __init__(self, vol, level=0, centres=False, shift=None, empty=False):
        np = _numpy()
        from . import vc3d_region
        if not 0 <= level < len(vol.levels):
            raise SnapError(f"{vol}: no level {level} (it has {len(vol.levels)})")
        self.vol, self.level, self.centres, self.empty = vol, int(level), bool(centres), bool(empty)
        self.shift = None if shift is None else np.asarray(shift, dtype=np.float32).reshape(3)
        meta = vol.levels[level]["meta"]
        if len(meta["shape"]) != 3:
            raise SnapError(f"{vol} level {level}: expected a 3-D array, shape {meta['shape']}")
        self.shape_zyx = [int(s) for s in meta["shape"]]
        self.dtype = vc3d_region._dtype(meta)
        self.ds = 2 ** self.level

    def derive(self, shift=None, empty=False):
        return Sampler(self.vol, self.level, self.centres, shift=shift, empty=empty)

    def _level(self, xyz):
        if self.shift is not None:
            xyz = xyz + self.shift.astype(xyz.dtype)
        if self.centres:
            return self.vol.to_level(self.level, xyz)
        return xyz / self.ds

    def _inside(self, lv):
        Z, Y, X = self.shape_zyx
        return ((lv[:, 2] >= 0) & (lv[:, 2] < Z - 0.5) & (lv[:, 1] >= 0) & (lv[:, 1] < Y - 0.5) &
                (lv[:, 0] >= 0) & (lv[:, 0] < X - 0.5))

    def nearest(self, xyz):
        """Nearest-voxel values (the volume's dtype) at float32 points; 0 outside [0, size - 0.5) on any axis."""
        np = _numpy()
        from . import vc3d_prep
        lv = self._level(np.asarray(xyz))
        out = np.zeros(len(lv), self.dtype)
        inb = self._inside(lv)
        if self.empty or not inb.any():
            return out
        out[inb] = vc3d_prep.sample_nearest(self.vol, self.level, lv[inb])
        return out

    def trilinear(self, xyz):
        """Trilinear values (float64) over the corners inside the array, renormalised; nan with no corner inside."""
        np = _numpy()
        pts = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
        fin = np.isfinite(pts).all(axis=1)
        if self.empty:
            return np.where(fin, 0.0, np.nan)
        lv = np.asarray(self._level(pts), dtype=np.float64)
        zyx = lv[:, ::-1].copy()
        zyx[~fin] = -1e9
        f = np.floor(zyx)
        i0 = f.astype(np.int64)
        dd = zyx - f
        shape = np.array(self.shape_zyx)
        corners, weights, rows = [], [], []
        for k in range(8):
            o = np.array([k & 1, (k >> 1) & 1, (k >> 2) & 1])
            idx = i0 + o
            inside = np.all((idx >= 0) & (idx < shape), axis=1)
            w = ((dd[:, 0] if o[0] else 1 - dd[:, 0]) * (dd[:, 1] if o[1] else 1 - dd[:, 1]) *
                 (dd[:, 2] if o[2] else 1 - dd[:, 2]))
            sel = np.nonzero(inside)[0]
            corners.append(idx[sel])
            weights.append(w[sel])
            rows.append(sel)
        rows = np.concatenate(rows)
        acc = np.zeros(len(pts))
        wsum = np.zeros(len(pts))
        if len(rows):
            vals = self.gather(np.concatenate(corners)).astype(np.float64)
            w = np.concatenate(weights)
            acc = np.bincount(rows, weights=w * vals, minlength=len(pts))
            wsum = np.bincount(rows, weights=w, minlength=len(pts))
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where(wsum >= 1e-9, acc / np.where(wsum > 0, wsum, 1), np.nan)
        out[~fin] = np.nan
        return out

    def gather(self, zyx):
        """Values at integer voxels (N, 3) z, y, x inside the level, read chunk by chunk through the Volume's chunk
        cache (as sample_nearest does, grouped by sorting a scalar chunk key); a missing chunk reads 0."""
        np = _numpy()
        import concurrent.futures
        zyx = np.asarray(zyx, dtype=np.int64).reshape(-1, 3)
        meta = self.vol.levels[self.level]["meta"]
        ch = np.array([int(c) for c in meta["chunks"]])
        grid = -(-np.array(self.shape_zyx) // ch)
        out = np.zeros(len(zyx), self.dtype)
        if not len(zyx):
            return out
        c = zyx // ch
        key = (c[:, 0] * grid[1] + c[:, 1]) * grid[2] + c[:, 2]
        order = np.argsort(key, kind="stable")
        _, starts = np.unique(key[order], return_index=True)
        ends = np.append(starts[1:], len(order))
        keys3 = c[order[starts]]
        workers = max(1, getattr(self.vol, "workers", 8))
        group = max(1, workers * 4)
        with concurrent.futures.ThreadPoolExecutor(min(workers, len(keys3))) as pool:
            for g in range(0, len(keys3), group):
                part = keys3[g:g + group]
                arrs = list(pool.map(lambda k3: self.vol._chunk(self.level, tuple(int(v) for v in k3)), part))
                for j, arr in enumerate(arrs):
                    if arr is None:
                        continue
                    k = g + j
                    sel = order[starts[k]:ends[k]]
                    local = zyx[sel] - keys3[k] * ch
                    out[sel] = arr[local[:, 0], local[:, 1], local[:, 2]]
        return out


def open_volume(location):
    from . import vc3d_audit, vc3d_region
    try:
        return vc3d_region.Volume(str(location))
    except (vc3d_region.RegionError, vc3d_audit.AuditError) as exc:
        raise SnapError(f"cannot open {location}: {exc}") from exc


# ---------------------------------------------------------------- technique A: nearest predicted sheet

def choose_offsets(prof, K):
    """His per-vertex choice, vectorised: of the runs of sheet samples along the normal (prof, vertices x 2K+1),
    the one whose centre is nearest offset 0 (the first on a tie), refined by a parabola through the [1, 2, 1]
    smoothed profile at the rounded centre and its neighbours; the run centre alone when |frac| > 0.5. Returns
    (offset float32 with nan where no sheet, has-sheet)."""
    np = _numpy()
    prof = np.asarray(prof, dtype=bool)
    nv, L = prof.shape
    d = np.full(nv, np.nan, np.float32)
    has = prof.any(1)
    if not has.any():
        return d, has
    padded = np.zeros((nv, L + 2), np.int8)
    padded[:, 1:-1] = prof
    dif = np.diff(padded, axis=1)
    rs, st = np.nonzero(dif == 1)
    _, en = np.nonzero(dif == -1)
    centres = (st + en - 1) / 2.0 - K
    order = np.lexsort((np.arange(len(rs)), np.abs(centres), rs))
    first = np.ones(len(order), bool)
    first[1:] = rs[order][1:] != rs[order][:-1]
    pick = order[first]
    rows, cj = rs[pick], centres[pick]
    p = prof[rows].astype(np.float64)
    sm = np.zeros((len(rows), L + 2))
    sm[:, 1:-1] = 2 * p
    sm[:, :-2] += p
    sm[:, 2:] += p
    sm = sm[:, 1:-1]                                  # np.convolve(p, [1, 2, 1], 'same')
    c = np.rint(cj + K).astype(np.int64)
    c = np.minimum(np.maximum(c, 1), L - 2)
    ar = np.arange(len(rows))
    y0, y1, y2 = sm[ar, c - 1], sm[ar, c], sm[ar, c + 1]
    den = (y0 - 2 * y1 + y2)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(np.abs(den) > 1e-6, 0.5 * (y0 - y2) / np.where(den != 0, den, 1), 0.0)
    d[rows] = np.where(np.abs(frac) > 0.5, cj, 0.5 * (cj + (c - K + frac)))
    return d, has


def regularise(D, K, jump=6.0, sigma=1.0):
    """His regularisation of an offset grid D (nan = no sheet): (D3, filled, rejected)."""
    np = _numpy()
    med = nanmedian_filter(D, 5)
    with np.errstate(invalid="ignore"):
        rej = np.isfinite(D) & np.isfinite(med) & (np.abs(D - med) > jump)
    D2 = D.copy()
    D2[rej] = np.nan
    filled = normconv(D2, max(sigma, 1.0))
    D3 = np.where(np.isfinite(D2), D2, filled)
    D3 = normconv(D3, sigma)
    D3 = np.clip(D3, -K, K)
    return D3, filled, rej


def snap_pred(xs, ys, zs, valid, sampler, max_off=15, threshold=1.0, jump=6.0, sigma=1.0, batch=DEFAULT_BATCH):
    """Technique A on one mesh. Returns a dict: xs, ys, zs (float32), D3, apply and his report fields."""
    np = _numpy()
    K = int(max_off)
    if K < 1:
        raise SnapError("--max-off must be at least 1")
    offs = np.arange(-K, K + 1, dtype=np.float32)
    L = len(offs)
    n, ok = normals(xs, ys, zs, valid)
    vy, vx = np.nonzero(ok)
    nv = len(vy)
    base = np.stack([xs[vy, vx], ys[vy, vx], zs[vy, vx]], -1)
    nvx = n[vy, vx]
    prof = np.zeros((nv, L), bool)
    per = max(1, int(batch) // L)
    for s in range(0, nv, per):
        e = min(nv, s + per)
        S = base[s:e, None, :] + offs[None, :, None] * nvx[s:e, None, :]
        vals = sampler.nearest(S.reshape(-1, 3))
        prof[s:e] = (vals >= threshold).reshape(e - s, L)
    d, has = choose_offsets(prof, K)
    D = np.full(xs.shape, np.nan, np.float32)
    D[vy, vx] = d
    already_on = float((np.abs(d) <= 2.0).mean()) if nv else 0.0
    D3, filled, rej = regularise(D, K, jump, sigma)
    apply = ok & np.isfinite(D3) & np.isfinite(filled)
    xo, yo, zo = xs.copy(), ys.copy(), zs.copy()
    xo[apply] += D3[apply] * n[apply][:, 0]
    yo[apply] += D3[apply] * n[apply][:, 1]
    zo[apply] += D3[apply] * n[apply][:, 2]
    nvalid = int(valid.sum())
    absd = np.abs(D3[apply])
    report = {
        "n_valid": nvalid,
        "frac_with_sheet": float(has.mean()) if nv else None,
        "frac_snapped": float(apply.sum() / max(1, nvalid)),
        "median_abs_off": float(np.nanmedian(absd)) if apply.any() else None,
        "p90_abs_off": float(np.nanpercentile(absd, 90)) if apply.any() else None,
        "frac_rejected": float(rej.sum() / max(1, has.sum())),
        "frac_already_on": already_on,
    }
    record = {"max_off": K, "jump": jump, "sigma": sigma, "frac_snapped": report["frac_snapped"],
              "median_abs_off": report["median_abs_off"]}
    return {"xs": xo, "ys": yo, "zs": zo, "valid": valid, "D3": D3, "apply": apply, "report": report,
            "record": record, "note": PRED_SOURCE_NOTE}


# ---------------------------------------------------------------- technique B: CT band midline (RectoRefine)

def _grid_faces(valid):
    """Triangles of the tifxyz grid in compact vertex numbering: (r,c),(r,c+1),(r+1,c) and (r,c+1),(r+1,c+1),
    (r+1,c), each kept when its three vertices are valid. Returns (faces (F, 3), index grid)."""
    np = _numpy()
    H, W = valid.shape
    idx = np.full((H, W), -1, np.int64)
    idx[valid] = np.arange(int(valid.sum()))
    if H < 2 or W < 2:
        return np.zeros((0, 3), np.int64), idx
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    f1 = np.stack([a, b, c], -1).reshape(-1, 3)
    f2 = np.stack([b, d, c], -1).reshape(-1, 3)
    faces = np.concatenate([f1[(f1 >= 0).all(1)], f2[(f2 >= 0).all(1)]])
    return faces, idx


def _edges(faces, nv):
    """Directed one-ring edges (src, dst), unique and sorted by (src, dst)."""
    np = _numpy()
    if not len(faces):
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    key = np.unique(e[:, 0] * nv + e[:, 1])
    return key // nv, key % nv


def _mesh_normals(verts, faces):
    """MeshNormals_compute: the sum of each incident triangle's (b - a) x (c - a), normalised; zero when degenerate."""
    np = _numpy()
    nv = len(verts)
    acc = np.zeros((nv, 3), np.float32)
    if len(faces):
        v = verts.astype(np.float64)
        cr = np.cross(v[faces[:, 1]] - v[faces[:, 0]], v[faces[:, 2]] - v[faces[:, 0]]).astype(np.float32)
        for k in range(3):
            np.add.at(acc, faces[:, k], cr)
    a64 = acc.astype(np.float64)
    ln = np.linalg.norm(a64, axis=1, keepdims=True)
    return np.where(ln > 1e-12, a64 / np.where(ln > 1e-12, ln, 1), 0.0).astype(np.float32)


def _radial(verts, axis):
    """Unit radial directions from the scroll axis and their lengths before normalising (0 without an axis)."""
    np = _numpy()
    p = verts.astype(np.float64)
    if axis is None:
        return np.zeros_like(p), np.zeros(len(p))
    if axis[0] == "umbilicus":
        pts = axis[1]
        zs = np.array([q[0] for q in pts], dtype=np.float64)
        cy = np.interp(p[:, 2], zs, np.array([q[1] for q in pts], dtype=np.float64))
        cx = np.interp(p[:, 2], zs, np.array([q[2] for q in pts], dtype=np.float64))
        radial = np.stack([p[:, 0] - cx, p[:, 1] - cy, np.zeros(len(p))], 1)
    else:
        point = np.asarray(axis[1], dtype=np.float64)
        ad = np.asarray(axis[2], dtype=np.float64)
        al = float(np.linalg.norm(ad))
        ad = np.array([1.0, 0.0, 0.0]) if al < 1e-12 else ad / al
        dvec = p - point
        radial = dvec - (dvec @ ad)[:, None] * ad
    rl = np.linalg.norm(radial, axis=1)
    radial = np.where(rl[:, None] > 1e-9, radial / np.where(rl > 1e-9, rl, 1)[:, None], radial)
    return radial, rl


def _directions(verts, nrm, axis, blend):
    """rr_direction: the outward line per vertex and whether there is one."""
    np = _numpy()
    radial, rl = _radial(verts, axis)
    blend = min(max(float(blend), 0.0), 1.0)
    n64 = nrm.astype(np.float64)
    nn = np.linalg.norm(n64, axis=1)
    out = radial.copy()
    ok = ~((rl <= 1e-9) & (nn <= 0.5))
    no_r = (rl <= 1e-9) & (nn > 0.5)
    out[no_r] = n64[no_r] / nn[no_r, None]
    mix = (rl > 1e-9) & (nn > 0.5) & (blend > 0.0)
    if mix.any():
        nu = n64[mix] / nn[mix, None]
        dot = (nu * radial[mix]).sum(1)
        nu[dot < 0.0] *= -1
        o = (1.0 - blend) * radial[mix] + blend * nu
        ln = np.linalg.norm(o, axis=1)
        good = ln > 1e-9
        o[good] /= ln[good, None]
        o[~good] = radial[mix][~good]
        out[mix] = o
    out[~ok] = 0.0
    return out, ok


def stretch_window(vals, dtype, pct_lo=1.0, pct_hi=99.0):
    """Their contrast window: for uint8 data the 256-bin percentile rule of stretch_window (surface_snap.c), else
    numpy percentiles; (0, 255) when nothing was sampled or the window is empty."""
    np = _numpy()
    v = np.asarray(vals, dtype=np.float64)
    v = v[np.isfinite(v)]
    n = len(v)
    if n == 0:
        return 0.0, 255.0
    if np.dtype(dtype) == np.uint8:
        bb = np.clip(np.floor(np.maximum(v, 0.0) + 0.5), 0, 255).astype(np.int64)
        cum = np.cumsum(np.bincount(bb, minlength=256))
        tlo, thi = int(pct_lo / 100.0 * n), int(pct_hi / 100.0 * n)
        above = np.nonzero(cum > tlo)[0]
        reach = np.nonzero(cum >= thi)[0]
        lo = int(above[0]) if len(above) else 0
        hi = int(reach[0]) if len(reach) else 255
    else:
        lo, hi = (float(x) for x in np.percentile(v, [pct_lo, pct_hi]))
    if hi <= lo:
        return 0.0, 255.0
    return float(lo), float(hi)


def _profile(sampler, P, Dd, offs, batch):
    """Trilinear CT values at P + offs * Dd: offs (M,) shared or (V, M) per vertex. Returns (V, M), nan missing."""
    np = _numpy()
    V = len(P)
    offs = np.asarray(offs, dtype=np.float64)
    M = offs.shape[-1]
    out = np.full((V, M), np.nan)
    per = max(1, int(batch) // max(1, 8 * M))
    for s in range(0, V, per):
        e = min(V, s + per)
        o = offs[None, :] if offs.ndim == 1 else offs[s:e]
        q = P[s:e, None, :] + o[:, :, None] * Dd[s:e, None, :]
        out[s:e] = sampler.trilinear(q.reshape(-1, 3)).reshape(e - s, M)
    return out


def find_targets(sampler, P, Dd, o, band, min_edge, batch=DEFAULT_BATCH):
    """rr_find_target with midline on, vectorised: (offset along Dd, gradient, found) per vertex."""
    np = _numpy()
    rng_ = o["range"] if o["range"] > 0 else 3.0
    step = o["sample_step"] if o["sample_step"] > 0 else 0.25
    half = o["edge_half"] if o["edge_half"] > 0 else 0.5
    ns = int(math.floor((2.0 * rng_) / step + 0.5)) + 1
    ns = min(max(ns, 3), 1025)
    V = len(P)
    t = -rng_ + (2.0 * rng_ * np.arange(ns)) / (ns - 1)
    allo = np.concatenate([t - half, t + half])
    uo, inv = np.unique(np.round(allo, 9), return_inverse=True)
    prof = _profile(sampler, P, Dd, uo, batch)[:, inv.reshape(-1)]
    sm, sp = prof[:, :ns], prof[:, ns:]
    with np.errstate(invalid="ignore", divide="ignore"):
        grad = sp - sm
        elig = np.isfinite(sm) & np.isfinite(sp) & (grad >= min_edge)
        crossing = (sm <= band) & (sp >= band) & (sp > sm + 1e-9)
        f = np.clip((band - sm) / np.where(crossing, sp - sm, 1.0), 0.0, 1.0)
        tc = np.where(crossing, t - half + 2.0 * half * f, t)
        score = grad - o["distance_bias"] * np.abs(tc)
        score = np.where(crossing, score, score - 0.5 * np.abs(0.5 * (sm + sp) - band))
    score = np.where(elig, score, -np.inf)
    found = elig.any(1)
    best = np.argmax(score, 1)
    ar = np.arange(V)
    best_t = tc[ar, best]
    best_grad = grad[ar, best]
    tmin = o["midline_min_thick"] if o["midline_min_thick"] > 0 else 1.0
    tmax = o["midline_max_thick"] if o["midline_max_thick"] > 0 else 6.0
    nf = int(math.floor(tmax / step + 0.5)) + 1
    fidx = np.nonzero(found)[0]
    keep = np.zeros(V, bool)
    if len(fidx) and nf > 1:
        T = best_t[fidx, None] + step * np.arange(1, nf)[None, :]
        smf = _profile(sampler, P[fidx], Dd[fidx], T - half, batch)
        spf = _profile(sampler, P[fidx], Dd[fidx], T + half, batch)
        miss = ~(np.isfinite(smf) & np.isfinite(spf))
        with np.errstate(invalid="ignore"):
            fall = ~miss & (smf >= band) & (spf <= band) & (smf > spf + 1e-9)
        event = miss | fall
        k = np.argmax(event, 1)
        a2 = np.arange(len(fidx))
        ffound = event.any(1) & fall[a2, k]
        with np.errstate(invalid="ignore", divide="ignore"):
            fr = np.clip((smf[a2, k] - band) / np.where(ffound, smf[a2, k] - spf[a2, k], 1.0), 0.0, 1.0)
        t_fall = T[a2, k] - half + 2.0 * half * fr
        good = ffound & ~(t_fall - best_t[fidx] < tmin)
        keep[fidx[good]] = True
        best_t[fidx[good]] = 0.5 * (best_t[fidx[good]] + t_fall[good])
    return best_t, best_grad, keep


class _Occupancy:
    """rr_hits_other over a hash grid of the input vertices (cells of the occupancy radius)."""

    def __init__(self, start, src, dst, occ, local):
        np = _numpy()
        self.np = np
        self.start = start.astype(np.float64)
        self.occ2, self.local2 = occ * occ, local * local
        self.cell = max(occ, 1e-6)
        k = np.floor(self.start / self.cell).astype(np.int64) if len(start) else np.zeros((0, 3), np.int64)
        self.lo = k.min(axis=0) - 2 if len(k) else np.zeros(3, np.int64)
        self.dims = (k.max(axis=0) - self.lo + 3) if len(k) else np.ones(3, np.int64)
        keys = self._key(k)
        self.order = np.argsort(keys, kind="stable")
        self.keys = keys[self.order]
        nv = len(start)
        self.ring = src * max(1, nv) + dst
        self.nv = max(1, nv)

    def _key(self, k):
        r = k - self.lo
        return (r[:, 0] * self.dims[1] + r[:, 1]) * self.dims[2] + r[:, 2]

    def hits(self, i, q):
        """For vertices i moving to q: is any input vertex within the occupancy radius of q farther than local_r
        from i's input position, or outside i's one-ring?"""
        np = self.np
        out = np.zeros(len(i), bool)
        if not len(i):
            return out
        q = q.astype(np.float64)
        kq = np.floor(q / self.cell).astype(np.int64)
        for dz in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    kk = kq + np.array([dx, dy, dz])
                    r = kk - self.lo
                    inside = np.all((r >= 0) & (r < self.dims), axis=1)
                    key = self._key(np.where(inside[:, None], kk, self.lo))
                    a = np.searchsorted(self.keys, key, "left")
                    b = np.searchsorted(self.keys, key, "right")
                    b = np.where(inside, b, a)
                    m = 0
                    while True:
                        live = a + m < b
                        if not live.any():
                            break
                        li = np.nonzero(live)[0]
                        j = self.order[a[li] + m]
                        near = ((self.start[j] - q[li]) ** 2).sum(1) <= self.occ2
                        if near.any():
                            ii, jj = i[li[near]], j[near]
                            dsq = ((self.start[jj] - self.start[ii]) ** 2).sum(1)
                            pair = ii * self.nv + jj
                            pos = np.searchsorted(self.ring, pair)
                            in_ring = (ii == jj) | ((pos < len(self.ring)) &
                                                    (self.ring[np.minimum(pos, len(self.ring) - 1)] == pair))
                            bad = (dsq > self.local2) | ~in_ring
                            out[li[near][bad]] = True
                        m += 1
        return out


def snap_midline(xs, ys, zs, valid, sampler, opts=None, axis=None, window=None, batch=DEFAULT_BATCH):
    """Technique B on one mesh: RectoRefine_run with midline on, over the grid triangulation. Returns a dict like
    snap_pred's, with ScrollFiesta's pass-2 statistics under "recto"."""
    np = _numpy()
    o = dict(MIDLINE_DEFAULTS)
    o.update(opts or {})
    faces, _ = _grid_faces(valid)
    V = int(valid.sum())
    verts = np.stack([xs[valid], ys[valid], zs[valid]], 1).astype(np.float32)
    start = verts.copy()
    src, dst = _edges(faces, V)
    deg = np.bincount(src, minlength=V) if V else np.zeros(0, np.int64)
    s64 = start.astype(np.float64)
    edge = np.sqrt(((s64[dst] - s64[src]) ** 2).sum(1)) if len(src) else np.zeros(0)
    cap = (o["max_slope"] if o["max_slope"] > 0 else 0.55) * np.maximum(edge, 1e-3)
    seg = np.nonzero(deg > 0)[0]
    seg_start = np.concatenate([[0], np.cumsum(deg)[:-1]])[seg] if V else np.zeros(0, np.int64)
    if window is None:
        lo_w, hi_w = stretch_window(sampler.trilinear(start), sampler.dtype, o["pct_lo"], o["pct_hi"])
    else:
        lo_w, hi_w = float(window[0]), float(window[1])
    contrast = hi_w - lo_w
    if contrast <= 1e-6:
        lo_w, hi_w, contrast = 0.0, 255.0, 255.0
    band = lo_w + min(max(o["band_frac"], 0.05), 0.95) * contrast
    min_edge = (o["min_edge_frac"] if o["min_edge_frac"] > 0 else 0.08) * contrast
    occ = _Occupancy(start, src, dst, o["occ_thresh"] if o["occ_thresh"] > 0 else 0.9,
                     o["local_r"] if o["local_r"] > 0 else 2.0)
    ever_supported = np.zeros(V, bool)
    ever_reverted = np.zeros(V, bool)
    slope_hit = np.zeros(V, bool)
    stats = {"iterations": 0, "n_reverted": 0, "mean_abs_step": 0.0, "mean_recto_gradient": 0.0}
    first_toff = None
    first_supported = 0
    mu = o["smooth_mu"] if o["smooth_mu"] > 0 else 1.0
    damping = o["damping"] if o["damping"] > 0 else 0.70
    max_step = o["max_step"] if o["max_step"] > 0 else 0.85
    max_total = o["max_total"] if o["max_total"] > 0 else 3.0
    for outer in range(int(o["outer_iters"]) if o["outer_iters"] > 0 else 4):
        nrm = _mesh_normals(verts, faces)
        dirs, okd = _directions(verts, nrm, axis, o["normal_blend"])
        okd &= deg > 0
        dirs[~okd] = 0.0
        dd = dirs.astype(np.float64)       # theirs: the double direction for base_disp and rr_find_target,
        dirs = dirs.astype(np.float32)     # the float copy (dirs[]) for the step
        d64 = dirs.astype(np.float64)
        base = ((verts.astype(np.float64) - s64) * dd).sum(1).astype(np.float32)
        base[~okd] = 0.0
        target = np.zeros(V, np.float32)
        weight = np.full(V, o["anchor_weight"] if o["anchor_weight"] > 0 else 24.0, np.float32)
        live = np.nonzero(okd)[0]
        toff, grad, found = find_targets(sampler, verts[live].astype(np.float64), dd[live], o, band, min_edge,
                                         batch)
        sup = live[found]
        conf = np.clip((grad[found] - min_edge) / (0.25 * contrast + 1e-9), 0.0, 1.0)
        target[sup] = (base[sup].astype(np.float64) + toff[found]).astype(np.float32)
        weight[sup] = ((o["data_weight"] if o["data_weight"] > 0 else 12.0) * (0.35 + 0.65 * conf)).astype(np.float32)
        ever_supported[sup] = True
        stats["mean_recto_gradient"] = float(grad[found].mean()) if len(sup) else 0.0
        if first_toff is None:
            first_toff = np.abs(toff[found])
            first_supported = len(sup)
        cur = base.copy()
        w64, t64 = weight.astype(np.float64), target.astype(np.float64)
        for _ in range(int(o["inner_iters"]) if o["inner_iters"] > 0 else 48):
            new = np.zeros(V, np.float32)
            if len(seg):
                dj = cur[dst].astype(np.float64)
                s = np.add.reduceat(dj, seg_start)
                lo = np.maximum.reduceat(dj - cap, seg_start)
                hi = np.minimum.reduceat(dj + cap, seg_start)
                dg = deg[seg].astype(np.float64)
                val = (w64[seg] * t64[seg] + mu * s) / (w64[seg] + mu * dg)
                inside = lo <= hi
                clipped = np.clip(val, lo, np.maximum(lo, hi))
                slope_hit[seg[inside & (np.abs(clipped - val) > 1e-7)]] = True
                slope_hit[seg[~inside]] = True
                val = np.where(inside, clipped, s / dg)
                new[seg] = val.astype(np.float32)
            cur = new
        ds = damping * (cur.astype(np.float64) - base.astype(np.float64))
        ds = np.clip(ds, -max_step, max_step)
        cand = np.nonzero(np.abs(ds) >= 1e-6)[0]
        v64 = verts.astype(np.float64)
        q = (v64[cand] + ds[cand, None] * d64[cand]).astype(np.float32)
        total = q.astype(np.float64) - s64[cand]
        tl = np.sqrt((total ** 2).sum(1))
        over = tl > max_total
        if over.any():
            sc = max_total / tl[over]
            q[over] = (s64[cand][over] + sc[:, None] * total[over]).astype(np.float32)
        fin = np.isfinite(q).all(1)
        bad = ~fin
        bad[fin] = occ.hits(cand[fin], q[fin])
        acc_i = cand[~bad]
        actual = np.sqrt(((q[~bad].astype(np.float64) - v64[acc_i]) ** 2).sum(1))
        verts[acc_i] = q[~bad]
        stats["n_reverted"] += int(bad.sum())
        ever_reverted[cand[bad]] = True
        moved = len(acc_i)
        stats["mean_abs_step"] = float(actual.sum() / moved) if moved else 0.0
        stats["iterations"] = outer + 1
        if moved == 0 or stats["mean_abs_step"] < o["tol"]:
            break
    disp = np.sqrt(((verts.astype(np.float64) - s64) ** 2).sum(1))
    moved_v = disp > 1e-5
    xo, yo, zo = xs.copy(), ys.copy(), zs.copy()
    xo[valid], yo[valid], zo[valid] = verts[:, 0], verts[:, 1], verts[:, 2]
    recto = {"recto_iterations": stats["iterations"], "recto_supported": int(ever_supported.sum()),
             "recto_moved": int(moved_v.sum()), "recto_reverted": stats["n_reverted"],
             "recto_slope_limited": int(slope_hit.sum()),
             "recto_mean_disp": float(disp[moved_v].mean()) if moved_v.any() else 0.0,
             "recto_max_disp": float(disp.max()) if V else 0.0,
             "mean_abs_step": stats["mean_abs_step"], "mean_recto_gradient": stats["mean_recto_gradient"],
             "window": [lo_w, hi_w], "band": band, "min_edge": min_edge}
    report = {
        "n_valid": V,
        "frac_with_sheet": float(first_supported / V) if V else None,
        "frac_snapped": float(moved_v.sum() / max(1, V)),
        "median_abs_off": float(np.median(disp[moved_v])) if moved_v.any() else None,
        "p90_abs_off": float(np.percentile(disp[moved_v], 90)) if moved_v.any() else None,
        "frac_rejected": float(ever_reverted.sum() / max(1, V)),
        "frac_already_on": float((first_toff <= 2.0).sum() / max(1, V)) if first_toff is not None else 0.0,
    }
    apply = np.zeros(xs.shape, bool)
    apply[valid] = moved_v
    record = {"mode": "midline", "max_total": max_total, "range": o["range"], "band_frac": o["band_frac"],
              "outer_iters": o["outer_iters"], "frac_snapped": report["frac_snapped"],
              "median_abs_off": report["median_abs_off"]}
    return {"xs": xo, "ys": yo, "zs": zo, "valid": valid, "apply": apply, "report": report, "recto": recto,
            "record": record, "note": MIDLINE_SOURCE_NOTE}


# ---------------------------------------------------------------- technique C: the self-check

CHECK_MAX_SLOPE = 0.05     # largest slope of the planted field, voxels per voxel (a tilt under 3 degrees)


def planted_field(shape, shift, vary, step_r=1.0, step_c=1.0, max_slope=CHECK_MAX_SLOPE):
    """The known smooth displacement, voxels: shift + vary * sin(2 pi u / Lr) * cos(2 pi v / Lc), with u and v the
    distances in voxels from the grid's centre along rows and columns (grid steps step_r, step_c) and each
    wavelength the mesh's extent, or longer so that the slope stays at most max_slope. A gentle field barely tilts
    the normals, so a correct snap returns each vertex to where it was rather than sliding it along the sheet."""
    np = _numpy()
    H, W = shape
    er, ec = max(1.0, H * step_r), max(1.0, W * step_c)
    floor_l = 2 * np.pi * abs(vary) / max_slope if max_slope > 0 else 0.0
    lr, lc = max(er, floor_l), max(ec, floor_l)
    u = (np.arange(H)[:, None] + 0.5) * step_r - er / 2
    v = (np.arange(W)[None, :] + 0.5) * step_c - ec / 2
    return (shift + vary * np.sin(2 * np.pi * u / lr) * np.cos(2 * np.pi * v / lc)).astype(np.float32)


def grid_steps(xs, ys, zs, valid):
    """Median vertex spacing along rows and along columns, voxels (1 when there are no neighbours)."""
    np = _numpy()
    P = np.stack([xs, ys, zs], -1).astype(np.float64)
    out = []
    for axis in (0, 1):
        a = [slice(None)] * 2
        b = [slice(None)] * 2
        a[axis], b[axis] = slice(1, None), slice(None, -1)
        both = valid[tuple(a)] & valid[tuple(b)]
        d = np.linalg.norm(P[tuple(a)] - P[tuple(b)], axis=-1)[both]
        out.append(float(np.median(d)) if len(d) and np.median(d) > 0 else 1.0)
    return out


def _distances(a, b, mask):
    np = _numpy()
    d = np.sqrt(sum((a[k][mask].astype(np.float64) - b[k][mask].astype(np.float64)) ** 2 for k in range(3)))
    return d


def _summary(d, tol):
    np = _numpy()
    if not len(d):
        return {"n": 0, "median": None, "p90": None, "frac_within_tol": 0.0, "max": None}
    return {"n": int(len(d)), "median": round(float(np.median(d)), 4), "p90": round(float(np.percentile(d, 90)), 4),
            "frac_within_tol": round(float((d <= tol).mean()), 4), "max": round(float(d.max()), 4)}


def outward_lines(xs, ys, zs, valid, axis=None, blend=MIDLINE_DEFAULTS["normal_blend"]):
    """RectoRefine's outward line at every vertex of a grid (float32 H x W x 3) and where there is one."""
    np = _numpy()
    faces, _ = _grid_faces(valid)
    verts = np.stack([xs[valid], ys[valid], zs[valid]], 1).astype(np.float32)
    dirs, okd = _directions(verts, _mesh_normals(verts, faces), axis, blend)
    out = np.zeros(xs.shape + (3,), np.float32)
    ok = np.zeros(xs.shape, bool)
    out[valid] = dirs
    ok[valid] = okd
    return out, ok


def self_check(xs, ys, zs, valid, sampler, snap, shift=4.0, vary=1.0, tol=1.0, min_frac=0.8, control_shift=3.0,
               reference="original", plant=None):
    """Displace, snap, compare; then the shifted and empty controls. `snap(xs, ys, zs, valid, sampler)` returns a
    snap result dict; `plant(xs, ys, zs, valid)` gives the planting directions and where they exist (default: his
    normals). The shifted control reads the volume so that the sheet appears control_shift voxels from the input
    on the side of the planted displacement, where a snap that ignored the data could not tell it from the
    original. Returns a JSON-ready dict with "passed"."""
    np = _numpy()
    n, ok = (plant or normals)(xs, ys, zs, valid)
    if not ok.any():
        raise SnapError("no vertex has a normal: nothing to check")
    step_r, step_c = grid_steps(xs, ys, zs, valid)
    field = planted_field(xs.shape, shift, vary, step_r, step_c)
    xd, yd, zd = xs.copy(), ys.copy(), zs.copy()
    xd[ok] += field[ok] * n[ok][:, 0]
    yd[ok] += field[ok] * n[ok][:, 1]
    zd[ok] += field[ok] * n[ok][:, 2]
    orig = (xs, ys, zs)
    disp = (xd, yd, zd)
    if reference == "snapped":
        r0 = snap(xs, ys, zs, valid, sampler)
        ref = (r0["xs"], r0["ys"], r0["zs"])
    else:
        ref = orig
    res = snap(xd, yd, zd, valid, sampler)
    got = (res["xs"], res["ys"], res["zs"])
    recovered = _summary(_distances(got, ref, ok), tol)
    planted = _summary(_distances(disp, ref, ok), tol)
    along = np.abs(sum((got[k][ok].astype(np.float64) - ref[k][ok].astype(np.float64)) * n[ok][:, k]
                       for k in range(3)))
    recovered["along_median"] = round(float(np.median(along)), 4)
    recovered["along_p90"] = round(float(np.percentile(along, 90)), 4)

    def recovers(s):
        return s["median"] is not None and s["median"] <= tol and s["frac_within_tol"] >= min_frac

    mean_n = n[ok].astype(np.float64).mean(axis=0)
    ln = float(np.linalg.norm(mean_n))
    unit = mean_n / ln if ln > 1e-6 else np.array([1.0, 0.0, 0.0])
    # reading at p + v shows the sheet at -v: put it on the planted side
    vec = (-(1.0 if shift >= 0 else -1.0) * control_shift * unit).astype(np.float32)
    rs = snap(xd, yd, zd, valid, sampler.derive(shift=vec))
    shifted = _summary(_distances((rs["xs"], rs["ys"], rs["zs"]), ref, ok), tol)
    re_ = snap(xd, yd, zd, valid, sampler.derive(empty=True))
    moved = _distances((re_["xs"], re_["ys"], re_["zs"]), disp, valid)
    empty_moved = float(moved.max()) if len(moved) else 0.0
    out = {
        "reference": reference,
        "planted": {"shift": shift, "vary": vary, "grid_step": [round(step_r, 4), round(step_c, 4)], **planted},
        "recovery": {**recovered, "tol": tol, "min_frac": min_frac, "passed": recovers(recovered)},
        "control_shifted": {"shift_xyz": [round(float(v), 4) for v in vec], "control_shift": control_shift,
                            **shifted, "recovered": recovers(shifted), "caught": not recovers(shifted)},
        "control_empty": {"max_movement": round(empty_moved, 6), "caught": empty_moved == 0.0},
    }
    out["passed"] = bool(out["recovery"]["passed"] and out["control_shifted"]["caught"]
                         and out["control_empty"]["caught"])
    why = []
    if not out["recovery"]["passed"]:
        why.append(f"the snap did not recover the planted displacement (median {recovered['median']}, "
                   f"{recovered['frac_within_tol']} within {tol} voxels)")
    if not out["control_shifted"]["caught"]:
        why.append("the shifted control also recovered the mesh, so this check cannot tell a right volume from a "
                   "shifted one here")
    if not out["control_empty"]["caught"]:
        why.append(f"the mesh moved by up to {empty_moved:.4g} voxels against a volume with no sheet")
    out["why"] = why or ["recovered, and both controls caught"]
    return out


# ---------------------------------------------------------------- command line

SHAM_NOTE = "; sham: every vertex moved by minus its snap displacement (kit snap --sham, a control)"


def sham_of(original, snapped):
    """The sham snap, a control arm: every vertex moved by minus the displacement the snap gave it (the same
    distances along the same lines, to the other side). A vertex the snap left in place stays in place."""
    return tuple(2 * o.astype(_numpy().float64) - s.astype(_numpy().float64) for o, s in zip(original, snapped))


def _fmt(v, spec):
    return format(float("nan") if v is None else v, spec)


def _tsv_line(name, rep):
    return (f"{name}\t{rep['n_valid']}\t{_fmt(rep['frac_with_sheet'], '.3f')}\t{_fmt(rep['frac_snapped'], '.3f')}\t"
            f"{_fmt(rep['median_abs_off'], '.2f')}\t{_fmt(rep['p90_abs_off'], '.2f')}\t"
            f"{_fmt(rep['frac_rejected'], '.3f')}\t{_fmt(rep['frac_already_on'], '.3f')}")


def _mesh_list(args):
    if args.windings:
        if len(args.meshes) != 1:
            raise SnapError("--windings names meshes inside one folder: give exactly one MESH folder with it")
        base = Path(args.meshes[0])
        names = [ln.strip() for ln in Path(args.windings).read_text().splitlines()
                 if ln.strip() and not ln.startswith("#")]
        out = []
        for w in names:
            if not (base / w / "x.tif").exists():
                print(f"{w}: missing under {base}", file=sys.stderr)
                continue
            out.append(base / w)
        if not out:
            raise SnapError("no meshes")
        return out
    return [Path(m) for m in args.meshes]


def _axis(args):
    if args.umbilicus:
        from . import vc3d_orient
        try:
            pts = vc3d_orient.load_umbilicus(args.umbilicus, args.umbilicus_scale)
        except (vc3d_orient.OrientError, OSError) as exc:
            raise SnapError(f"--umbilicus: {exc}") from exc
        if not pts:
            raise SnapError("--umbilicus has no points")
        return ("umbilicus", sorted(pts))
    if args.axis_point is not None or args.axis_dir is not None:
        if args.axis_point is None or args.axis_dir is None:
            raise SnapError("give --axis-point and --axis-dir together")
        return ("line", args.axis_point, args.axis_dir)
    return None


def _snapper(args):
    """(name, snap(xs, ys, zs, valid, sampler), plant) for the chosen source and mode; plant is None for his
    normals."""
    if args.source == "pred":
        if args.mode not in (None, "nearest"):
            raise SnapError("--source pred snaps to the nearest predicted sheet (--mode nearest)")

        def snap(xs, ys, zs, valid, sampler):
            return snap_pred(xs, ys, zs, valid, sampler, args.max_off, args.threshold, args.jump, args.sigma,
                             args.batch)
        return "nearest", snap, None
    if args.mode not in (None, "midline"):
        raise SnapError("--source ct supports --mode midline only (the recto-edge variant measured harmful and is "
                        "not ported)")
    axis = _axis(args)
    opts = {k: getattr(args, k) for k in ("band_frac", "range", "sample_step", "edge_half", "min_edge_frac",
                                           "distance_bias", "normal_blend", "data_weight", "anchor_weight",
                                           "smooth_mu", "max_slope", "damping", "max_step", "max_total",
                                           "occ_thresh", "local_r", "outer_iters", "inner_iters", "tol")}
    opts["midline_min_thick"], opts["midline_max_thick"] = args.min_thick, args.max_thick

    def snap(xs, ys, zs, valid, sampler):
        return snap_midline(xs, ys, zs, valid, sampler, opts, axis, args.window, args.batch)

    def plant(xs, ys, zs, valid):
        return outward_lines(xs, ys, zs, valid, axis, args.normal_blend)
    return "midline", snap, plant


def run(args):
    _numpy()
    t0 = time.time()
    location = args.volume or os.environ.get("SURF_ZARR")
    if not location:
        raise SnapError("give --volume ZARR (or set SURF_ZARR to the surface prediction zarr)")
    if not args.check and not args.out:
        raise SnapError("give --out DIR for the snapped meshes (or --check to test the snap without writing them)")
    meshes = _mesh_list(args)
    names = [m.name for m in meshes]
    if len(set(names)) != len(names):
        raise SnapError(f"two meshes share a folder name: {names}")
    mode, snap, plant = _snapper(args)
    vol = open_volume(location)
    sampler = Sampler(vol, args.level, args.centres)
    out = Path(args.out) if args.out else None
    if out is not None:
        for m in meshes:
            if (out / m.name).resolve() == m.resolve():
                raise SnapError(f"{m}: the output would overwrite the input; give another --out")
        out.mkdir(parents=True, exist_ok=True)
    rows, checks = [], []
    record_extra = {"tool": "kit snap", "snapped_to": "predicted sheet" if args.source == "pred" else "CT band midline",
                    "mode": mode, "level": args.level,
                    "centres": bool(args.centres), "volume": str(location)}
    if args.source == "pred":
        record_extra["threshold"] = args.threshold
    if args.sham and args.check:
        raise SnapError("--sham writes the control mesh; --check plants and controls its own displacements")
    for m in meshes:
        xs, ys, zs, valid = load_mesh(m)
        if args.check:
            shift = args.check_shift if args.check_shift is not None else (4.0 if args.source == "pred" else -2.0)
            res = self_check(xs, ys, zs, valid, sampler, snap, shift, args.check_vary, args.check_tol,
                             args.check_frac, args.control_shift, args.check_reference, plant)
            res["mesh"] = str(m)
            checks.append(res)
            if not args.json:
                rec, cs, ce = res["recovery"], res["control_shifted"], res["control_empty"]
                print(f"{m.name}\t{'PASS' if res['passed'] else 'FAIL'}\tplanted median {res['planted']['median']}\t"
                      f"residual median {rec['median']} p90 {rec['p90']} within {rec['tol']}: "
                      f"{rec['frac_within_tol']}\tshifted control median {cs['median']} "
                      f"({'caught' if cs['caught'] else 'NOT caught'})\tempty control moved "
                      f"{ce['max_movement']} ({'caught' if ce['caught'] else 'NOT caught'})", flush=True)
            continue
        res = snap(xs, ys, zs, valid, sampler)
        rec = dict(res["record"])
        rec.update(record_extra)
        if "recto" in res:
            rec["recto"] = res["recto"]
        got, note = (res["xs"], res["ys"], res["zs"]), res["note"]
        if args.sham:
            got = sham_of((xs, ys, zs), got)
            rec["sham"] = True
            note += SHAM_NOTE
        write_mesh(m, out / m.name, *got, valid, rec, note)
        row = {"winding": m.name, **res["report"], **({"sham": True} if args.sham else {})}
        if "recto" in res:
            row["recto"] = res["recto"]
        rows.append(row)
        if not args.json:
            print(_tsv_line(m.name, res["report"]), flush=True)
    result = {"tool": "kit snap", "source": args.source, "mode": mode, "volume": str(location), "level": args.level,
              "seconds": round(time.time() - t0, 2)}
    if args.check:
        result["checks"] = checks
        result["passed"] = all(c["passed"] for c in checks)
        if out is not None:
            (out / "snap_check.json").write_text(json.dumps(result, indent=1))
    else:
        result["meshes"] = rows
        rep = open(out / "snap_report.tsv", "a")
        try:
            if rep.tell() == 0:
                rep.write("\t".join(REPORT_COLUMNS) + "\n")
            for r in rows:
                rep.write(_tsv_line(r["winding"], r) + "\n")
        finally:
            rep.close()
        (out / "snap_report.json").write_text(json.dumps(result, indent=1))
    if args.json:
        print(json.dumps(result, indent=1))
    elif not args.check:
        print(f"done {len(rows)} meshes in {result['seconds']:.0f}s -> {out}")
    return 0 if (not args.check or result["passed"]) else 1


def build_parser(p):
    p.description = ("Snap tifxyz meshes along their normals: onto the nearest predicted sheet (--source pred, a port "
                     "of Nieuwlaar's snap_meshes.py) or onto the midline of the bright CT band (--source ct --mode "
                     "midline, a port of ScrollFiesta's RectoRefine midline). --check plants a known displacement, "
                     "snaps it back and runs two controls that must fail.")
    p.add_argument("meshes", nargs="+", metavar="MESH",
                   help="tifxyz folders (x/y/z.tif, meta.json); with --windings, one folder holding the meshes")
    p.add_argument("--volume", help="surface prediction (pred) or CT (ct) zarr: a local path or an https/s3 URL; "
                                    "default $SURF_ZARR")
    p.add_argument("--out", help="output folder: OUT/<mesh>/{x,y,z}.tif + meta.json, snap_report.tsv and .json")
    p.add_argument("--windings", help="file naming the meshes to snap inside the one MESH folder (his layout)")
    p.add_argument("--source", choices=("pred", "ct"), default="pred",
                   help="pred: nearest predicted sheet (default); ct: midline of the CT band")
    p.add_argument("--mode", choices=("nearest", "midline"), default=None,
                   help="nearest for pred, midline for ct (the defaults; the CT recto-edge variant is not ported)")
    p.add_argument("--level", type=int, default=0, help="pyramid level to sample (default 0)")
    p.add_argument("--centres", action="store_true",
                   help="map level-0 points to the level with voxel centres aligned (Volume.to_level) instead of "
                        "his point / 2**level")
    p.add_argument("--batch", type=int, default=DEFAULT_BATCH, help="sample points per batch (memory bound)")
    p.add_argument("--json", action="store_true", help="print the full JSON result")
    p.add_argument("--sham", action="store_true",
                   help="write the sham snap instead, a control: every vertex moved by minus its snap displacement")
    g = p.add_argument_group("pred (snap_meshes.py)")
    g.add_argument("--max-off", type=int, default=15, help="search +-K voxels along the normal (default 15)")
    g.add_argument("--threshold", type=float, default=1.0,
                   help="a sample is sheet when its value is at least this (default 1: his v > 0 on an integer "
                        "prediction)")
    g.add_argument("--jump", type=float, default=6.0, help="reject offsets this far from the 5x5 median (default 6)")
    g.add_argument("--sigma", type=float, default=1.0, help="smoothing Gaussian in grid cells (default 1)")
    c = p.add_argument_group("ct midline (RectoRefine)")
    c.add_argument("--umbilicus", help="scroll axis as a villa umbilicus file (z, y, x points) for the outward sense")
    c.add_argument("--umbilicus-scale", type=float, default=1.0, help="multiply the umbilicus points by this")
    c.add_argument("--axis-point", type=float, nargs=3, metavar=("X", "Y", "Z"), help="a point on the scroll axis")
    c.add_argument("--axis-dir", type=float, nargs=3, metavar=("X", "Y", "Z"), help="the scroll axis direction")
    c.add_argument("--window", type=float, nargs=2, metavar=("LO", "HI"),
                   help="CT contrast window (default: 1st to 99th percentile at the vertices)")
    d = MIDLINE_DEFAULTS
    for name, typ, hlp in (("band_frac", float, "band isovalue in the window"),
                           ("range", float, "signed search radius, voxels"),
                           ("sample_step", float, "profile spacing, voxels"),
                           ("edge_half", float, "derivative half-width, voxels"),
                           ("min_edge_frac", float, "least edge as a share of the window"),
                           ("distance_bias", float, "score penalty per voxel of distance"),
                           ("normal_blend", float, "0 radial, 1 mesh normal"),
                           ("data_weight", float, "weight of a found target"),
                           ("anchor_weight", float, "weight pulling an abstaining vertex to its input position"),
                           ("smooth_mu", float, "one-ring smoothness"),
                           ("max_slope", float, "largest added neighbour difference per unit edge length"),
                           ("damping", float, "step damping"),
                           ("max_step", float, "largest step per outer iteration, voxels"),
                           ("max_total", float, "largest total displacement, voxels"),
                           ("occ_thresh", float, "occupancy radius of the input mesh, voxels"),
                           ("local_r", float, "radius of the own neighbourhood, voxels"),
                           ("outer_iters", int, "outer iterations"),
                           ("inner_iters", int, "Jacobi sweeps per outer iteration"),
                           ("tol", float, "stop when the mean step is below this, voxels")):
        c.add_argument("--" + name.replace("_", "-"), type=typ, default=d[name], help=f"{hlp} (default {d[name]})")
    c.add_argument("--min-thick", type=float, default=d["midline_min_thick"],
                   help=f"thinnest band accepted, voxels (default {d['midline_min_thick']})")
    c.add_argument("--max-thick", type=float, default=d["midline_max_thick"],
                   help=f"farthest walk to the falling edge, voxels (default {d['midline_max_thick']})")
    k = p.add_argument_group("self-check")
    k.add_argument("--check", action="store_true",
                   help="plant a known displacement, snap it back and run the shifted and empty controls; exit 1 "
                        "when the recovery fails or a control passes (writes no meshes)")
    k.add_argument("--check-shift", type=float, default=None,
                   help="planted displacement, voxels: along the normal for pred (default 4), along the outward line "
                        "for ct (default -2, toward the recto side, where the midline search starts)")
    k.add_argument("--check-vary", type=float, default=1.0, help="amplitude of its smooth variation (default 1)")
    k.add_argument("--check-tol", type=float, default=1.0, help="recovered when within this many voxels (default 1)")
    k.add_argument("--check-frac", type=float, default=0.8,
                   help="share of vertices that must be within --check-tol, with the median (default 0.8)")
    k.add_argument("--control-shift", type=float, default=3.0,
                   help="the shifted control reads the volume so the sheet appears this many voxels from the input, on "
                        "the planted side, along the mean planting direction (default 3)")
    k.add_argument("--check-reference", choices=("original", "snapped"), default="original",
                   help="compare with the input mesh (default) or with the snap of the undisplaced input")
    return p


def cmd_snap(args):
    try:
        from . import vc3d_io
        errors = (SnapError, vc3d_io.IOFormatError, OSError)
        try:
            from . import vc3d_audit
            errors = errors + (vc3d_audit.AuditError,)
            from . import vc3d_region
            errors = errors + (vc3d_region.RegionError,)
        except ImportError:
            pass
    except ImportError:
        errors = (SnapError, OSError)
    try:
        return run(args)
    except errors as exc:
        print(f"kit snap: {exc}", file=sys.stderr)
        return 2
