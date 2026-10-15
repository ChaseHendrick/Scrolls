"""Carry a published segment's ink labels onto another surface's render canvas, by 3D proximity.

`python -m kit labelxfer` (docs/autopipe.md, "Scoring our own traces"). The published PHerc0841 labels sit on the
published segments' render grids; a surface AutoPipeline traces itself has its own grid, so until this tool its
maps had no labels to be scored against. For every pixel of the traced surface's render this finds the 3D point
vc_render_tifxyz samples there, the nearest point of the published segment's mesh, and that point's pixel on
the published render, whose label kit auc gives to the published map's pixel. A pixel takes the label only when
the gap between the two surfaces is under a fixed tolerance in voxels and their normals agree within a fixed
angle, so a trace that crossed to the next winding rarely borrows that winding's labels: rarely, not never, since
the PHerc0841 pitch can be as small as 7.75 voxels (its 5th percentile), the published meshes sit more than 4
voxels off the predicted sheet centre at 26 % (w00) and 42 % (ag896) of points, and adjacent windings are parallel,
so the normal test does not separate them; a 50-generation trace that had mostly left w00's winding still had 7 to
13 % of its vertices within 4 voxels of w00 (docs/compute/modal-specs/2026-10-09-own-trace-ink.md, "Dry run").
Labels borrowed from another winding are ink and papyrus of another sheet, so they push a map's score down: toward
FAIL, not toward a false PASS. The record keeps the |offset| distribution of the labelled pixels to show how far
from the published mesh the labels were taken (`coverage`). The source pixel of
every carried label is kept, so a map of the published surface can be sampled on exactly the same pixels and
the two maps compared pixel for pixel (`score`, a paired block bootstrap from kit auc).

The render canvas (Sourced fact, villa e0bbb8b, the build kit's renders use). vc_render_tifxyz at scale 1,
group 0, no affine and no crop (how AutoPipeline's render tool calls it) makes a canvas of
W = lround(cols * r / sx) by H = lround(rows * r / sy) pixels, r = scale x scale-segmentation x 2^-level (here
1) and sx, sy the tifxyz meta.json scale (apps/src/vc_render_tifxyz.cpp 1828-1845), and asks QuadSurface::gen for
it starting at -(W - 1) / 2, -(H - 1) / 2 (computeCanvasOrigin, 280-284). gen centres the grid at cols / (2 sx),
rows / (2 sy) (core/src/QuadSurface.cpp surfaceCenterFor 290-296 and gen 1634-1660), so pixel (R, C) samples
the grid at

    col = cols / 2 + (C - (W - 1) / 2) * sx / r,   row = rows / 2 + (R - (H - 1) / 2) * sy / r

bilinearly, the position clamped to the grid (warpBilinearReplicateVec3f). The pixel is rendered only where the
vertex nearest it (lround) is valid (warpNearestConstU8) and none of the four bilinear corners is a hole, since
the render turns holes into NaN first (vc_render_tifxyz.cpp 1813-1817). Its layers go along that nearest
vertex's normal, (p[r][c+1] - p[r][c-1]) x (p[r+1][c] - p[r-1][c]) (core/src/Geometry.cpp grid_normal_int),
which is NaN on the grid's border and next to a hole; such a pixel has no layers and is treated as unrendered.
A flattened or trimmed surface is a new tifxyz with its own grid: the canvas is read from whichever tifxyz was
rendered. overlap.py's sample_grid spreads an upsampled grid evenly over an array instead; on w00's 211 x 238
grid that puts the far edge about 18 surface pixels from where the render has it, so this module does not use it.

The match. The published surface is sampled every `lattice_px` canvas pixels (4: about 4 voxels) with its
tangents along canvas rows and columns; each traced pixel finds the nearest lattice point (cKDTree, as overlap.py's
match) and is projected onto that point's tangent plane, which gives the source pixel to a fraction of a pixel
and the gap as the length of what is left. A foot farther than one lattice step from its lattice point (past the
published mesh's edge) is clamped, so the gap then includes the in-plane miss and the pixel is refused.

Checks that can fail (`check`): (a) identity, carrying a segment's labels onto its own mesh must give its
supervised pixels back, nearly all from their own pixel; (b) displaced, the same labels taken `displace_mm` away in the surface
plane, in four fixed directions (overlap.py's DISPLACE_MM is 1 to 3 mm; 2 mm here), must agree with the true
labels less. The identity check uses the canvas formula on both sides, so it cannot see the formula itself go
wrong; `canvas_check` can: in a run, the render of each trace must fill only pixels this module takes as rendered
(at least CANVAS_MIN_AGREEMENT of them), or the carrying is refused. Every carried label and every score here is
model output on published labels, not a reading.

Report surfaces. 0841-ag405 is the ink bar's report surface (kit/autopipe.py REPORT_ONLY): `carry`, `check` and
`score` refuse its labels unless report=True (`--report`), and `overlap` measures where a trace lies on such a
surface from its mesh alone, with no labels.

Needs numpy, scipy (cKDTree), tifffile, and zarr for the labels: all in villa's environment.
"""

import hashlib
import json
import math
import time
from pathlib import Path

from .auc import _levels, block_bootstrap, label_grid, score_array, BLOCK_PX
from .overlap import DISPLACE_MM
from .verify import VerifyError, _numpy, load_map

# Fixed in docs/prereg/2026-10-09-own-trace-ink.md before any map of an AutoPipeline trace existed; the
# measurements that set them are in docs/autopipe.md ("Scoring our own traces").
MAX_GAP_VOX = 4.0
MAX_NORMAL_DEG = 30.0
DISPLACE_MM_FIXED = 2.0            # the middle of overlap.py's DISPLACE_MM range
DIRECTIONS_DEG = (0, 90, 180, 270)
LATTICE_PX = 4
REACH_VOX = 30.0                   # gaps are measured out to here (beyond a winding pitch), labels carried within
                                   # max_gap_vox only
# The identity check: carrying a segment's labels onto its own mesh must give back at least
# IDENTITY_MIN_COVERAGE of its supervised rendered pixels, at least IDENTITY_MIN_NEAR of them from a source within
# one pixel of itself, and equal ink labels on at least IDENTITY_MIN_INK of them. The displaced labels' ink Dice
# with the true labels must be at least DISPLACED_MIN_DROP below the identity's. Measured on 9 Oct 2026 (Model
# output, docs/autopipe.md): w00 coverage 1.0, within one pixel 0.99993, ink 1.0; ag896 0.99998, 0.99988, 1.0; the
# few pixels farther off (largest 5 and 8 px) sit where the mesh folds within half a voxel of itself. Displaced
# by 2 mm the ink Dice fell from 1.0 to at most 0.33 (w00) and 0.40 (ag896).
IDENTITY_MIN_COVERAGE = 0.99
IDENTITY_MIN_NEAR = 0.999
IDENTITY_MIN_INK = 0.999
DISPLACED_MIN_DROP = 0.25
# The canvas check (canvas_check): of the pixels a render filled (any layer non-zero), at least this share must be
# pixels this module takes as rendered. Set 10 Oct 2026, before any map of a trace, from the dry run's 25-generation
# trace v1, whose render matched rendered_mask on 819,289 of 819,300 pixels, and the review's three synthetic
# vc_render_tifxyz renders at e0bbb8b, which matched on every pixel (Model output). A canvas one pixel off on a
# 1000 x 1000 render already puts about 0.1 % of what it filled outside the mask.
CANVAS_MIN_AGREEMENT = 0.999

STATUS = {0: "not rendered: no valid nearest vertex, a hole among the four corners, or no normal",
          1: "no rendered published pixel within the gap tolerance",
          2: "within the gap tolerance, but the normals differ by more than the angle tolerance",
          3: "carried; its source pixel is outside the supervision mask",
          4: "carried and supervised: labelled"}
NOT_RENDERED, NO_SURFACE, NORMAL_REFUSED, UNSUPERVISED, LABELLED = range(5)


def _scipy_spatial():
    try:
        from scipy import spatial
    except ImportError as exc:
        raise VerifyError("scipy is required for kit labelxfer (it is in villa's environment)") from exc
    return spatial


# ---------------------------------------------------------------- the render canvas

def read_mesh(path):
    """A tifxyz surface: points (rows, cols, 3) as x, y, z in volume voxels with NaN at holes, its valid mask
    and its meta.json scale (sx, sy)."""
    np = _numpy()
    try:
        import tifffile
    except ImportError as exc:
        raise VerifyError("tifffile is required for kit labelxfer") from exc
    path = Path(path)
    try:
        xyz = np.stack([np.asarray(tifffile.imread(str(path / f"{c}.tif")), dtype=np.float64) for c in "xyz"], -1)
    except Exception as exc:  # a missing file or an unreadable TIFF
        raise VerifyError(f"cannot read the tifxyz in {path}: {exc}") from exc
    if xyz.ndim != 3 or min(xyz.shape[:2]) < 2:
        raise VerifyError(f"{path}: x, y and z must be 2D grids of one shape, at least 2 x 2")
    try:
        scale = [float(v) for v in json.loads((path / "meta.json").read_text())["scale"][:2]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VerifyError(f"{path}: meta.json gives no grid scale ({exc})") from exc
    if len(scale) != 2 or not all(s > 0 and math.isfinite(s) for s in scale):
        raise VerifyError(f"{path}: meta.json scale {scale} is not two positive numbers")
    # VC3D marks a hole with -1 in x (vc_render_tifxyz.cpp 1813-1817); NaN and negative points are holes too
    valid = np.isfinite(xyz).all(-1) & (xyz[..., 0] != -1) & (xyz >= 0).all(-1)
    xyz[~valid] = np.nan
    if valid.sum() < 4:
        raise VerifyError(f"{path}: fewer than 4 valid points")
    return {"path": str(path), "xyz": xyz, "valid": valid, "scale": scale, "shape": list(xyz.shape[:2])}


def _lround(np, g):
    """C's lround: halves away from zero."""
    return np.where(g >= 0, np.floor(g + 0.5), -np.floor(-g + 0.5)).astype(np.int64)


def canvas_shape(mesh, render_scale=1.0):
    """(H, W) of vc_render_tifxyz's canvas for this surface."""
    rows, cols = mesh["shape"]
    sx, sy = mesh["scale"]
    w = max(1, int(math.floor(cols * render_scale / sx + 0.5)))
    h = max(1, int(math.floor(rows * render_scale / sy + 0.5)))
    return h, w


def grid_of_pixel(mesh, R, C, render_scale=1.0):
    """Fractional grid (row, col) that canvas pixel rows R and columns C sample (any broadcastable arrays)."""
    np = _numpy()
    rows, cols = mesh["shape"]
    sx, sy = mesh["scale"]
    h, w = canvas_shape(mesh, render_scale)
    gx = cols / 2.0 + (np.asarray(C, dtype=np.float64) - (w - 1) / 2.0) * sx / render_scale
    gy = rows / 2.0 + (np.asarray(R, dtype=np.float64) - (h - 1) / 2.0) * sy / render_scale
    return gy, gx


def pixel_of_grid(mesh, gy, gx, render_scale=1.0):
    """Fractional canvas (row, col) at grid position (gy, gx); the inverse of grid_of_pixel."""
    np = _numpy()
    rows, cols = mesh["shape"]
    sx, sy = mesh["scale"]
    h, w = canvas_shape(mesh, render_scale)
    C = (np.asarray(gx, dtype=np.float64) - cols / 2.0) * render_scale / sx + (w - 1) / 2.0
    R = (np.asarray(gy, dtype=np.float64) - rows / 2.0) * render_scale / sy + (h - 1) / 2.0
    return R, C


def vertex_normals(mesh):
    """VC3D's per-vertex render normal (grid_normal_int): central differences along columns crossed with those
    along rows, unit length; NaN on the border, next to a hole, or where degenerate."""
    np = _numpy()
    p = mesh["xyz"]
    n = np.full(p.shape, np.nan)
    xv = p[1:-1, 2:] - p[1:-1, :-2]
    yv = p[2:, 1:-1] - p[:-2, 1:-1]
    c = np.cross(xv, yv)
    norm = np.linalg.norm(c, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        inner = np.where(norm > 0, c / norm, np.nan)
    n[1:-1, 1:-1] = inner
    if "normals" not in mesh:
        mesh["normals"] = n
    return n


def sample_pixels(mesh, R, C, render_scale=1.0):
    """The 3D points vc_render_tifxyz samples at canvas pixels (R, C) (same-shape integer arrays), their render
    normals and whether the pixel is rendered (VC3D's linear mode, see the module notes). Returns (points
    (..., 3), normals (..., 3), rendered (...))."""
    np = _numpy()
    rows, cols = mesh["shape"]
    normals = mesh.get("normals")
    if normals is None:
        normals = vertex_normals(mesh)
    gy, gx = grid_of_pixel(mesh, R, C, render_scale)
    gy, gx = np.broadcast_arrays(gy, gx)
    ny, nx = _lround(np, gy), _lround(np, gx)
    inside = (ny >= 0) & (ny < rows) & (nx >= 0) & (nx < cols)
    nyc, nxc = np.clip(ny, 0, rows - 1), np.clip(nx, 0, cols - 1)
    fy, fx = np.clip(gy, 0, rows - 1), np.clip(gx, 0, cols - 1)
    y0, x0 = np.floor(fy).astype(np.int64), np.floor(fx).astype(np.int64)
    y1, x1 = np.minimum(y0 + 1, rows - 1), np.minimum(x0 + 1, cols - 1)
    wy, wx = (fy - y0)[..., None], (fx - x0)[..., None]
    p = mesh["xyz"]
    pts = (p[y0, x0] * (1 - wx) + p[y0, x1] * wx) * (1 - wy) + (p[y1, x0] * (1 - wx) + p[y1, x1] * wx) * wy
    nrm = normals[nyc, nxc]
    ok = inside & mesh["valid"][nyc, nxc] & np.isfinite(pts).all(-1) & np.isfinite(nrm).all(-1)
    return pts, nrm, ok


def rendered_mask(mesh, render_scale=1.0, band=512):
    """The canvas pixels vc_render_tifxyz renders (bool (H, W))."""
    np = _numpy()
    h, w = canvas_shape(mesh, render_scale)
    out = np.zeros((h, w), dtype=bool)
    C = np.arange(w)[None, :]
    for r0 in range(0, h, band):
        R = np.arange(r0, min(h, r0 + band))[:, None]
        _, _, ok = sample_pixels(mesh, R, C, render_scale)
        out[r0:r0 + len(R)] = ok
    return out


def _lattice(mesh, step, render_scale):
    """The published surface every `step` canvas pixels: points, tangents per canvas pixel along columns and
    rows (central differences on the lattice, one-sided at its edge), and their canvas positions."""
    np = _numpy()
    h, w = canvas_shape(mesh, render_scale)
    R = np.arange(0, h, step)
    C = np.arange(0, w, step)
    P, _, ok = sample_pixels(mesh, R[:, None], C[None, :], render_scale)
    P = np.where(ok[..., None], P, np.nan)

    def deriv(axis):
        fwd = np.full(P.shape, np.nan)
        bwd = np.full(P.shape, np.nan)
        sl = [slice(None)] * 3
        a, b = list(sl), list(sl)
        a[axis], b[axis] = slice(1, None), slice(None, -1)
        d = (P[tuple(a)] - P[tuple(b)]) / step
        fwd[tuple(b)] = d
        bwd[tuple(a)] = d
        both = np.isfinite(fwd).all(-1) & np.isfinite(bwd).all(-1)
        out = np.where(np.isfinite(fwd).all(-1, keepdims=True), fwd, bwd)
        out[both] = 0.5 * (fwd[both] + bwd[both])
        return out

    tc, tr = deriv(1), deriv(0)
    use = ok & np.isfinite(tc).all(-1) & np.isfinite(tr).all(-1)
    rr, cc = np.nonzero(use)
    return {"points": P[use], "tc": tc[use], "tr": tr[use], "R": R[rr], "C": C[cc], "step": step,
            "count": int(use.sum())}


# ---------------------------------------------------------------- labels

def load_labels(labels, level="2"):
    """A labelled segment's ink labels and supervision mask, whole, at a pyramid level (numpy bool arrays)."""
    np = _numpy()
    labels = Path(labels)
    ink = _levels(labels / "inklabels.zarr", level)
    sup = _levels(labels / "supervision.zarr", level)
    if ink.shape != sup.shape:
        raise VerifyError(f"{labels}: inklabels {ink.shape} and supervision {sup.shape} differ at level {level}")
    return np.asarray(ink[...]) > 0, np.asarray(sup[...]) > 0


def labels_on_canvas(ink, sup, canvas):
    """Row and column index maps from a published canvas (H, W) into its labels, as kit auc assigns them to a
    map of that shape (auc.label_grid)."""
    rows, cols = label_grid(ink.shape, canvas, None, canvas)
    return rows, cols


# ---------------------------------------------------------------- carrying

def _digest_files(path):
    h = hashlib.sha256()
    for name in ("x.tif", "y.tif", "z.tif", "meta.json"):
        f = Path(path) / name
        h.update(name.encode())
        h.update(hashlib.sha256(f.read_bytes()).digest() if f.is_file() else b"-")
    return h.hexdigest()


def report_surface(labels):
    """The report surface (kit/autopipe.py REPORT_ONLY) whose labels the folder or bucket prefix `labels` names, or
    None: a path part that is its key (0841-ag405), its short name (ag405), or holds its segment id."""
    from .autopipe import BENCHMARKS, REPORT_ONLY
    parts = [q for q in str(labels).replace("\\", "/").split("/") if q]
    for key in REPORT_ONLY:
        seg = (BENCHMARKS.get(key) or {}).get("segment")
        names = {key, key.split("-", 1)[-1]}
        if any(q in names or (seg and seg in q) for q in parts):
            return key
    return None


def guard_labels(labels, report=False):
    """VerifyError for a report surface's labels unless report is true: 0841-ag405 is the ink bar's report surface,
    scored once by one frozen recipe (docs/plans/2026-10-09-autopipeline-bars.md, section 1), so its labels stay out
    of every development measurement."""
    key = report_surface(labels) if labels is not None else None
    if key and not report:
        raise VerifyError(f"{labels} holds the labels of {key}, a report surface: they are read only by its frozen "
                          "report recipe (--report). Use overlap for its geometry")
    return key


def carry(trace, published, labels=None, out=None, max_gap_vox=MAX_GAP_VOX, max_normal_deg=MAX_NORMAL_DEG,
          voxel_um=None, lattice_px=LATTICE_PX, render_scale=1.0, level="2", surface_shape=None, band=256,
          reach_vox=REACH_VOX, log=None, report=False):
    """Carry `published`'s labels (a folder holding inklabels.zarr and supervision.zarr) onto `trace`'s render
    canvas. Returns {"record": ..., "arrays": {...}}; with `out`, writes transfer.npz (source rows and columns,
    gap, signed offset along the published normal, status per pixel), inklabels.tif and supervision.tif (uint8,
    255 where set), the same as zarr arrays when zarr is installed, and record.json. surface_shape, when given,
    must be the published canvas (the published surface volume's shape), or the labels would sit elsewhere. A
    report surface's labels are refused unless report is true (guard_labels)."""
    np = _numpy()
    guard_labels(labels, report)
    spatial = _scipy_spatial()
    if not max_gap_vox > 0 or not 0 < max_normal_deg < 90:
        raise VerifyError("max_gap_vox must be above 0 and max_normal_deg between 0 and 90")
    t0 = time.time()
    say = log or (lambda m: None)
    T, P = read_mesh(trace), read_mesh(published)
    ht, wt = canvas_shape(T, render_scale)
    hp, wp = canvas_shape(P, render_scale)
    if surface_shape is not None and [hp, wp] != list(surface_shape):
        raise VerifyError(f"{published}: its render canvas is {[hp, wp]}, not the published surface volume's "
                          f"{list(surface_shape)}: the labels' pixels would not be the mesh's")
    vertex_normals(T)
    vertex_normals(P)
    lat = _lattice(P, int(lattice_px), render_scale)
    if lat["count"] < 4:
        raise VerifyError(f"{published}: too few rendered lattice points")
    tree = spatial.cKDTree(lat["points"])
    reach = max(float(reach_vox), 3.0 * float(max_gap_vox))
    bound = reach + 2.0 * lat["step"]        # a canvas pixel is about a voxel: the lattice diagonal, with slack
    cos_min = math.cos(math.radians(max_normal_deg))
    src_r = np.full((ht, wt), -1, dtype=np.int32)
    src_c = np.full((ht, wt), -1, dtype=np.int32)
    gap = np.full((ht, wt), np.nan, dtype=np.float32)
    offset = np.full((ht, wt), np.nan, dtype=np.float32)
    status = np.zeros((ht, wt), dtype=np.uint8)
    C = np.arange(wt)[None, :]
    for r0 in range(0, ht, band):
        R = np.arange(r0, min(ht, r0 + band))[:, None]
        X, nt, ok = sample_pixels(T, R, C, render_scale)
        rr, cc = np.nonzero(ok)
        if not len(rr):
            continue
        x = X[rr, cc]
        d, k = tree.query(x, k=1, distance_upper_bound=bound, workers=-1)
        found = np.isfinite(d)
        st = np.full(len(rr), NO_SURFACE, dtype=np.uint8)
        if found.any():
            k = k[found]
            v = x[found] - lat["points"][k]
            tc, tr = lat["tc"][k], lat["tr"][k]
            a, b, c = (tc * tc).sum(1), (tc * tr).sum(1), (tr * tr).sum(1)
            pu, pv = (tc * v).sum(1), (tr * v).sum(1)
            det = a * c - b * b
            with np.errstate(invalid="ignore", divide="ignore"):
                dc = np.where(det > 0, (c * pu - b * pv) / det, 0.0)
                dr = np.where(det > 0, (a * pv - b * pu) / det, 0.0)
            lim = float(lat["step"])
            dc, dr = np.clip(dc, -lim, lim), np.clip(dr, -lim, lim)
            resid = v - dc[:, None] * tc - dr[:, None] * tr
            g = np.linalg.norm(resid, axis=1)
            sr = _lround(np, lat["R"][k] + dr)
            sc = _lround(np, lat["C"][k] + dc)
            inside = (sr >= 0) & (sr < hp) & (sc >= 0) & (sc < wp)
            srn, scn = np.clip(sr, 0, hp - 1), np.clip(sc, 0, wp - 1)
            _, n_src, ok_src = sample_pixels(P, srn, scn, render_scale)
            ok_src &= inside
            off = (resid * np.nan_to_num(n_src)).sum(1)
            cosang = np.abs((nt[rr, cc][found] * np.nan_to_num(n_src)).sum(1))
            near = ok_src & (g <= max_gap_vox)
            s_found = np.where(near, np.where(cosang >= cos_min, UNSUPERVISED, NORMAL_REFUSED), NO_SURFACE)
            st[found] = s_found
            fr, fc = rr[found], cc[found]
            measured = ok_src & (g <= reach)
            gap[r0 + fr[measured], fc[measured]] = g[measured]
            offset[r0 + fr[measured], fc[measured]] = off[measured]
            keep = s_found == UNSUPERVISED
            src_r[r0 + fr[keep], fc[keep]] = sr[keep]
            src_c[r0 + fr[keep], fc[keep]] = sc[keep]
        status[r0 + rr, cc] = st
    say(f"labelxfer: matched {ht} x {wt} pixels in {time.time() - t0:.0f} s")
    carried = status == UNSUPERVISED
    ink_t = np.zeros((ht, wt), dtype=bool)
    sup_t = np.zeros((ht, wt), dtype=bool)
    lab_info = None
    if labels is not None:
        ink, sup = load_labels(labels, level)
        lr, lc = labels_on_canvas(ink, sup, (hp, wp))
        ys, xs = np.nonzero(carried)
        li, lj = lr[src_r[ys, xs]], lc[src_c[ys, xs]]
        s_here = sup[li, lj]
        sup_t[ys[s_here], xs[s_here]] = True
        ink_t[ys[s_here], xs[s_here]] = ink[li[s_here], lj[s_here]]
        status[carried & ~sup_t] = UNSUPERVISED
        status[sup_t] = LABELLED
        pub_rendered = rendered_mask(P, render_scale)
        sup_canvas = sup[np.ix_(lr, lc)] & pub_rendered
        reached = np.zeros((hp, wp), dtype=bool)
        reached[src_r[sup_t], src_c[sup_t]] = True
        lab_info = {"labels": str(labels), "level": level, "labels_shape": list(ink.shape),
                    "published_supervised_px": int(sup_canvas.sum()),
                    "published_supervised_reached_px": int((reached & sup_canvas).sum()),
                    "share_of_published_supervision_reached": round(float((reached & sup_canvas).sum())
                                                                    / max(1, int(sup_canvas.sum())), 4)}
    rec = _record(np, T, P, status, gap, offset, ink_t, sup_t, (ht, wt), (hp, wp), voxel_um, render_scale,
                  max_gap_vox, max_normal_deg, lat, reach, lab_info)
    rec["seconds"] = round(time.time() - t0, 1)
    arrays = {"src_row": src_r, "src_col": src_c, "gap": gap, "offset": offset, "status": status,
              "ink": ink_t, "supervision": sup_t}
    if out is not None:
        write(out, arrays, rec)
    return {"record": rec, "arrays": arrays}


def _pct(np, a, qs=(5, 25, 50, 75, 95)):
    return {str(q): round(float(np.percentile(a, q)), 2) for q in qs} if len(a) else None


def _record(np, T, P, status, gap, offset, ink_t, sup_t, tshape, pshape, voxel_um, render_scale, max_gap_vox,
            max_normal_deg, lat, reach, lab_info):
    counts = {"not_rendered": int((status == NOT_RENDERED).sum()), "no_surface": int((status == NO_SURFACE).sum()),
              "normal_refused": int((status == NORMAL_REFUSED).sum()),
              "carried_unsupervised": int((status == UNSUPERVISED).sum()), "labelled": int((status == LABELLED).sum())}
    within = counts["normal_refused"] + counts["carried_unsupervised"] + counts["labelled"]
    rendered = int(status.size - counts["not_rendered"])
    g = gap[np.isfinite(gap)]
    o = offset[np.isfinite(offset) & (status >= UNSUPERVISED)]
    ol = np.abs(offset[np.isfinite(offset) & (status == LABELLED)])
    px_um = voxel_um / render_scale if voxel_um else None
    cm2 = (lambda n: round(n * (px_um * 1e-4) ** 2, 4)) if px_um else (lambda n: None)
    ink_px, sup_px = int((ink_t & sup_t).sum()), int(sup_t.sum())
    rec = {"trace": T["path"], "published": P["path"], "trace_sha256": _digest_files(T["path"]),
           "published_sha256": _digest_files(P["path"]), "trace_canvas": list(tshape),
           "published_canvas": list(pshape), "render_scale": render_scale, "voxel_um": voxel_um,
           "rule": {"max_gap_vox": max_gap_vox, "max_normal_deg": max_normal_deg, "lattice_px": lat["step"],
                    "gap_measured_to_vox": reach},
           "pixels": {"rendered": rendered, **counts},
           "labelled_px": sup_px, "ink_px": ink_px, "background_px": sup_px - ink_px,
           "labelled_cm2": cm2(sup_px), "carried_cm2": cm2(counts["carried_unsupervised"] + counts["labelled"]),
           "rendered_cm2": cm2(rendered),
           "share_refused_by_normal_test": round(counts["normal_refused"] / within, 4) if within else None,
           "gap_vox": {"pixels_measured": int(len(g)), "percentiles": _pct(np, g),
                       "share_within": {str(t): round(float((g <= t).mean()), 4) for t in (1, 2, 4, 6, 8, 12, 20)}
                       if len(g) else None},
           "offset_along_published_normal_vox": {"carried_px": int(len(o)), "percentiles": _pct(np, o)},
           "abs_offset_labelled_vox": {"labelled_px": int(len(ol)), "percentiles": _pct(np, ol),
                                       "share_within": {str(v): round(float((ol <= v).mean()), 4) for v in (1, 2, 3)}
                                       if len(ol) else None},
           "note": "area counts canvas pixels at the nominal pixel size (voxel_um / render_scale), not the 3D "
                   "area under them. Carried labels are published labels moved by geometry: model output, "
                   "not a reading."}
    if lab_info:
        rec.update(lab_info)
    return rec


def write(out, arrays, rec):
    np = _numpy()
    import tifffile
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "transfer.npz", **{k: arrays[k] for k in ("src_row", "src_col", "gap", "offset",
                                                                      "status")})
    for name, key in (("inklabels", "ink"), ("supervision", "supervision")):
        img = arrays[key].astype(np.uint8) * 255
        tifffile.imwrite(str(out / f"{name}.tif"), img, compression="zlib")
        try:
            import zarr
        except ImportError:
            continue
        z = zarr.open_array(str(out / f"{name}.zarr"), mode="w", shape=img.shape, dtype="uint8",
                            chunks=(1024, 1024))
        z[...] = img
    rec = dict(rec, files=sorted(p.name for p in out.iterdir() if p.name != "record.json"))
    rec["digest"] = hashlib.sha256(json.dumps({k: v for k, v in rec.items() if k not in ("seconds", "digest")},
                                              sort_keys=True).encode()).hexdigest()
    (out / "record.json").write_text(json.dumps(rec, indent=1))
    return rec


def load(out):
    """A carried transfer as written: (record, arrays with ink and supervision as bool)."""
    np = _numpy()
    out = Path(out)
    rec = json.loads((out / "record.json").read_text())
    with np.load(out / "transfer.npz") as z:
        arrays = {k: z[k] for k in z.files}
    import tifffile
    arrays["ink"] = tifffile.imread(str(out / "inklabels.tif")) > 0
    arrays["supervision"] = tifffile.imread(str(out / "supervision.tif")) > 0
    return rec, arrays


def coverage(rec):
    """What a carried transfer covers, as a run keeps it per trace and segment and the readout quotes it beside the
    verdict: carried and labelled cm2 against the trace's rendered cm2, the share of the published supervision
    reached, the gap distribution, the |offset| of the labelled pixels and the share refused by the normal test."""
    g = rec.get("gap_vox") or {}
    pct = g.get("percentiles") or {}
    carried, rendered = rec.get("carried_cm2"), rec.get("rendered_cm2")
    return {"labelled_cm2": rec.get("labelled_cm2"), "ink_px": rec.get("ink_px"),
            "background_px": rec.get("background_px"), "carried_cm2": carried, "rendered_cm2": rendered,
            "carried_share_of_rendered": round(carried / rendered, 4) if carried is not None and rendered else None,
            "share_of_published_supervision_reached": rec.get("share_of_published_supervision_reached"),
            "share_refused_by_normal_test": rec.get("share_refused_by_normal_test"),
            "gap_vox_median": pct.get("50"), "gap_vox_percentiles": pct or None,
            "gap_share_within_4_vox": (g.get("share_within") or {}).get("4"),
            "abs_offset_labelled_vox": rec.get("abs_offset_labelled_vox"),
            "trace_canvas": rec.get("trace_canvas"), "seconds": rec.get("seconds")}


def canvas_check(mesh, render, band=256):
    """Does the render of `mesh` (a vc_render_tifxyz zarr: layers x H x W) fill only the canvas pixels this module
    takes as rendered? The identity check runs the canvas formula on both sides and cannot see it go wrong; this
    can, against the renderer itself. Of the pixels the render filled (any layer non-zero: a pixel over CT with no
    data stays zero and is left out), the share inside rendered_mask is the agreement; it passes at
    CANVAS_MIN_AGREEMENT or more. A canvas of another shape, or an empty render, fails."""
    np = _numpy()
    from .vc3d_region import Volume
    M = mesh if isinstance(mesh, dict) else read_mesh(mesh)
    mask = rendered_mask(M)
    v = Volume(str(render))
    shape = list(v.shape(0))
    out = {"render": str(render), "canvas": list(mask.shape), "render_shape": shape,
           "min_agreement": CANVAS_MIN_AGREEMENT}
    if len(shape) != 3 or shape[1:] != list(mask.shape):
        out.update(passes=False, why=f"the render is {shape}, not layers by the canvas {list(mask.shape)}")
        return out
    layers, h, w = shape
    filled = np.zeros((h, w), dtype=bool)
    for r0 in range(0, h, band):
        r1 = min(h, r0 + band)
        filled[r0:r1] = (np.asarray(v.read(0, [[0, layers], [r0, r1], [0, w]])) != 0).any(0)
    n, inside, m = int(filled.sum()), int((filled & mask).sum()), int(mask.sum())
    out.update(render_filled_px=n, mask_px=m, filled_inside_mask_px=inside,
               agreement=round(inside / n, 6) if n else None, mask_filled_share=round(inside / m, 4) if m else None,
               missing_chunks_read=v.missing)
    out["passes"] = bool(n and inside / n >= CANVAS_MIN_AGREEMENT)
    if not n:
        out["why"] = "the render is empty"
    return out


def overlap(trace, mesh, out=None, max_gap_vox=MAX_GAP_VOX, max_normal_deg=MAX_NORMAL_DEG, voxel_um=None,
            lattice_px=LATTICE_PX, log=None):
    """Where `trace` lies on another published surface `mesh`, from the meshes alone: the pixels of the trace's
    canvas within the gap and angle tolerances of it, as carry finds them with no labels. For a report surface
    (0841-ag405), whose labels are never read, so that its maps' pixels over it can be kept out of development
    choices. With `out`, writes mask.tif (uint8, 255 on the overlap) and record.json. Returns the record."""
    np = _numpy()
    res = carry(trace, mesh, None, None, max_gap_vox, max_normal_deg, voxel_um=voxel_um, lattice_px=lattice_px,
                log=log)
    rec, a = res["record"], res["arrays"]
    within = a["status"] >= UNSUPERVISED
    rendered = rec["pixels"]["rendered"]
    summary = {"trace": rec["trace"], "mesh": rec["published"], "trace_sha256": rec["trace_sha256"],
               "mesh_sha256": rec["published_sha256"], "labels": "never read", "trace_canvas": rec["trace_canvas"],
               "rule": rec["rule"], "overlap_px": int(within.sum()), "overlap_cm2": rec["carried_cm2"],
               "rendered_cm2": rec["rendered_cm2"],
               "share_of_trace": round(int(within.sum()) / rendered, 4) if rendered else None,
               "gap_vox": rec["gap_vox"], "share_refused_by_normal_test": rec["share_refused_by_normal_test"],
               "seconds": rec["seconds"],
               "note": "geometry only: the trace's render pixels within the tolerances of this surface's mesh"}
    if out is not None:
        import tifffile
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        tifffile.imwrite(str(out / "mask.tif"), within.astype(np.uint8) * 255, compression="zlib")
        summary["mask"] = str(out / "mask.tif")
        (out / "record.json").write_text(json.dumps(summary, indent=1))
    return summary


# ---------------------------------------------------------------- displaced labels

def displacement_px(displace_mm, voxel_um, render_scale=1.0):
    """(dR, dC) canvas shifts for the four fixed directions at displace_mm."""
    px = displace_mm * 1000.0 / (voxel_um / render_scale)
    return [(int(round(px * math.sin(math.radians(a)))), int(round(px * math.cos(math.radians(a)))))
            for a in DIRECTIONS_DEG]


def displaced(arrays, ink, sup, canvas, shift):
    """Labels for the carried pixels taken `shift` (dR, dC) published-canvas pixels from their source: (ink,
    supervision) bool arrays on the trace canvas. A shifted source off the canvas or outside the supervision is
    unlabelled."""
    np = _numpy()
    hp, wp = canvas
    lr, lc = labels_on_canvas(ink, sup, canvas)
    carried = arrays["status"] >= UNSUPERVISED
    ys, xs = np.nonzero(carried)
    r = arrays["src_row"][ys, xs].astype(np.int64) + shift[0]
    c = arrays["src_col"][ys, xs].astype(np.int64) + shift[1]
    inside = (r >= 0) & (r < hp) & (c >= 0) & (c < wp)
    ys, xs, r, c = ys[inside], xs[inside], r[inside], c[inside]
    li, lj = lr[r], lc[c]
    s = sup[li, lj]
    ink_d = np.zeros(arrays["status"].shape, dtype=bool)
    sup_d = np.zeros(arrays["status"].shape, dtype=bool)
    sup_d[ys[s], xs[s]] = True
    ink_d[ys[s], xs[s]] = ink[li[s], lj[s]]
    return ink_d, sup_d


def _dice(np, a, b):
    return 2.0 * float((a & b).sum()) / max(1, int(a.sum() + b.sum()))


# ---------------------------------------------------------------- the checks

def check(mesh, labels, out=None, voxel_um=None, displace_mm=DISPLACE_MM_FIXED, level="2", surface_shape=None,
          lattice_px=LATTICE_PX, log=None, report=False):
    """(a) identity and (b) displaced, on one labelled segment. (a) carries the segment's labels onto its own mesh
    and compares them with the labels kit auc gives each of its rendered pixels; (b) takes the carried pixels'
    labels displace_mm away in four directions and compares their ink with the true ink where both are
    supervised. Passes when (a) reaches IDENTITY_MIN_COVERAGE, IDENTITY_MIN_NEAR and IDENTITY_MIN_INK, and (b)
    drops the ink Dice by at least DISPLACED_MIN_DROP in every direction."""
    np = _numpy()
    if not voxel_um:
        raise VerifyError("check needs voxel_um (for the displacement in pixels)")
    res = carry(mesh, mesh, labels, out, voxel_um=voxel_um, lattice_px=lattice_px, level=level,
                surface_shape=surface_shape, log=log, report=report)
    a = res["arrays"]
    M = read_mesh(mesh)
    canvas = canvas_shape(M)
    ink, sup = load_labels(labels, level)
    lr, lc = labels_on_canvas(ink, sup, canvas)
    pub_rendered = rendered_mask(M)
    sup_own = sup[np.ix_(lr, lc)] & pub_rendered
    ink_own = ink[np.ix_(lr, lc)] & sup_own
    rows, cols = np.indices(canvas)
    lab = a["supervision"]
    off_r = np.abs(a["src_row"][lab] - rows[lab])
    off_c = np.abs(a["src_col"][lab] - cols[lab])
    both = lab & sup_own
    ident = {"supervised_rendered_px": int(sup_own.sum()), "carried_px": int(lab.sum()),
             "coverage": round(float(both.sum()) / max(1, int(sup_own.sum())), 5),
             "own_pixel_share": round(float(((off_r == 0) & (off_c == 0)).mean()), 5) if lab.any() else None,
             "within_one_px_share": round(float(((off_r <= 1) & (off_c <= 1)).mean()), 6) if lab.any() else None,
             "max_offset_px": int(max(off_r.max(), off_c.max())) if lab.any() else None,
             "ink_agreement": round(float((a["ink"][both] == ink_own[both]).mean()), 6) if both.any() else None,
             "dice": round(_dice(np, a["ink"] & both, ink_own & both), 5)}
    ident["passes"] = bool(ident["coverage"] >= IDENTITY_MIN_COVERAGE and ident["within_one_px_share"] is not None
                           and ident["within_one_px_share"] >= IDENTITY_MIN_NEAR
                           and ident["ink_agreement"] is not None and ident["ink_agreement"] >= IDENTITY_MIN_INK)
    disp = []
    for ang, shift in zip(DIRECTIONS_DEG, displacement_px(displace_mm, voxel_um)):
        ink_d, sup_d = displaced(a, ink, sup, canvas, shift)
        m = sup_d & sup_own
        disp.append({"direction_deg": ang, "shift_px": list(shift), "pixels": int(m.sum()),
                     "dice": round(_dice(np, ink_d & m, ink_own & m), 5) if m.sum() else None})
    worst = max((d["dice"] for d in disp if d["dice"] is not None), default=None)
    out_disp = {"displace_mm": displace_mm, "directions": disp, "max_dice": worst,
                "min_drop_required": DISPLACED_MIN_DROP}
    out_disp["passes"] = bool(worst is not None and ident["dice"] - worst >= DISPLACED_MIN_DROP)
    return {"mesh": str(mesh), "labels": str(labels), "identity": ident, "displaced": out_disp,
            "passes": ident["passes"] and out_disp["passes"], "transfer": res["record"],
            "rule": {"identity_min_coverage": IDENTITY_MIN_COVERAGE, "identity_min_within_one_px": IDENTITY_MIN_NEAR,
                     "identity_min_ink": IDENTITY_MIN_INK, "displaced_min_drop": DISPLACED_MIN_DROP}}


# ---------------------------------------------------------------- scoring maps on carried labels

def _map(path, shape, what):
    np = _numpy()
    m = np.squeeze(np.load(path) if str(path).endswith(".npy") else load_map(path))
    if list(m.shape) != list(shape):
        raise VerifyError(f"{what} {path} is {list(m.shape)}, not the canvas {list(shape)}: it is not a map of "
                          "this render")
    return m


def score(xfer, maps, reference=None, displace_mm=DISPLACE_MM_FIXED, draws=2000, block_px=BLOCK_PX, seed=20261009,
          keep_zero=True, report=False):
    """AUCs of a traced surface's maps on carried labels. maps: {"f": forward, "r": reverse, "s": shuffled} paths
    on the trace canvas (r and s optional). reference: a map of the published surface (its canvas), sampled at
    each carried pixel's source, scored on the same pixels and compared with the forward map by kit auc's paired
    block bootstrap. keep_zero counts a map value of 0 as a prediction: the pixels scored are then exactly the
    carried labelled pixels, fixed by geometry before any map. Returns the record."""
    np = _numpy()
    rec, a = load(xfer) if not isinstance(xfer, tuple) else xfer
    guard_labels(rec.get("labels"), report)
    shape = rec["trace_canvas"]
    ink, sup = a["ink"], a["supervision"]
    out = {"labelled_px": int(sup.sum()), "ink_px": int((ink & sup).sum()), "keep_zero": keep_zero}
    if not sup.any() or (ink & sup).all() or not (ink & sup).any():
        out["error"] = "no carried labels of both classes"
        return out
    fwd = _map(maps["f"], shape, "forward map")
    out["forward"] = score_array(fwd, ink, sup, keep_zero)
    for k, name in (("r", "reverse"), ("s", "shuffled")):
        if maps.get(k):
            out[name] = score_array(_map(maps[k], shape, f"{name} map"), ink, sup, keep_zero)
    lab_ink, lab_sup = load_labels(rec["labels"], rec["level"]) if rec.get("labels") else (None, None)
    if lab_ink is not None and rec.get("voxel_um"):
        disp = []
        for ang, shift in zip(DIRECTIONS_DEG, displacement_px(displace_mm, rec["voxel_um"], rec["render_scale"])):
            ink_d, sup_d = displaced(a, lab_ink, lab_sup, tuple(rec["published_canvas"]), shift)
            r = score_array(fwd, ink_d, sup_d, keep_zero)
            disp.append({"direction_deg": ang, "shift_px": list(shift), **r})
        aucs = [d["auc"] for d in disp if d["auc"] is not None]
        out["displaced"] = {"displace_mm": displace_mm, "directions": disp,
                            "max_auc": max(aucs) if aucs else None,
                            "mean_auc": round(float(np.mean(aucs)), 4) if aucs else None}
    if reference:
        ref = _map(reference, rec["published_canvas"], "reference map")
        on = np.zeros(fwd.shape, dtype=ref.dtype)
        ys, xs = np.nonzero(a["status"] >= UNSUPERVISED)
        on[ys, xs] = ref[a["src_row"][ys, xs], a["src_col"][ys, xs]]
        out["reference"] = {"map": str(reference), "on_carried_pixels": score_array(on, ink, sup, keep_zero)}
        b = block_bootstrap(fwd, ink, sup, draws=draws, block_px=block_px, seed=seed, other=on, keep_zero=keep_zero)
        out["paired"] = {"draws": b["draws"], "block_px": b["block_px"], "blocks": b["blocks"], "seed": b["seed"],
                         "forward_ci95": b["ci95"], **b["compare"],
                         "note": "difference is this surface's forward map minus the published surface's map on "
                                 "the same carried pixels and labels (AUCs from 1024-bin histograms)"}
    return out


# ---------------------------------------------------------------- the preregistered readout

# docs/prereg/2026-10-09-own-trace-ink.md, fixed 2026-10-09 before any map of an AutoPipeline trace existed, and
# amended 2026-10-10, before any map, after the dry run: arm A grows three traces from each seed (trace.repeats),
# and the primary is the first of seed 0's (the w00 seed's) repeats, in launch order, that qa accepts. qa decides
# without labels or maps. Who decided a failure (autopipe.FAILURE_KINDS) decides FAIL ("ours") or VOID.
READOUT = {"seed_index": 0, "repeats": 3, "segment": "0841-w00", "model": "ink_9um-seed42",
           "reference_whole_auc": 0.7479,       # AutoPipeline's w00 run of 9 Oct 2026, the same reader and render
           "reference_tolerance": 0.005, "max_reverse": 0.55, "min_gap_shuffled": 0.05, "min_gap_displaced": 0.05,
           "noninferiority_margin": 0.03}

INTERPRETATION = ("The compared pixels are those where this trace lies within the gap and angle tolerances of the "
                  "published segment. A PASS shows only that, there, our placement, flattening and render cost under "
                  "the margin in AUC; it says nothing about whether the trace stays on the winding, nor about its "
                  "area outside those pixels. Quote the coverage numbers beside the verdict.")


def _trace_rows(scores, state):
    """Every planned trace in launch order, [{"sid", "seed_index", "repeat", "accepted", "failure"}], and the
    repeats per seed: from scores.json's traces record, else from a state.json (autopipe.trace_entries), else, for
    scores written before traces were recorded, from its surfaces by name."""
    if scores and isinstance(scores.get("traces"), dict) and scores["traces"].get("planned") is not None:
        surf, seeds = scores.get("surfaces") or {}, scores["traces"].get("seeds") or {}
        rows = [{"sid": sid, "seed_index": (surf.get(sid) or {}).get("seed_index", seeds.get(sid)),
                 "repeat": (surf.get(sid) or {}).get("repeat"), "accepted": (surf.get(sid) or {}).get("accepted"),
                 "failure": (surf.get(sid) or {}).get("failure")} for sid in scores["traces"]["planned"]]
        return rows, scores["traces"].get("repeats")
    if state is not None:
        from .autopipe import trace_entries
        rows = trace_entries(state)
    elif scores:
        rows = []
        for sid, e in (scores.get("surfaces") or {}).items():
            if not sid.startswith("t"):
                continue
            idx = e.get("seed_index", int(sid[1:3]) if sid[1:3].isdigit() else None)
            ok = e.get("accepted", None if e.get("scorable") is False else True)
            rows.append({"sid": sid, "seed_index": idx, "repeat": e.get("repeat", 0), "accepted": ok,
                         "failure": e.get("failure") or ({"stage": "unknown", "kind": "ours", "reason": e.get("why")}
                                                         if e.get("scorable") is False else None)})
    else:
        return None, None
    reps = [r["repeat"] for r in rows if r.get("repeat") is not None]
    return rows, (max(reps) + 1 if reps else None)


def primary(rows, seed_index):
    """(the primary row or None, the rows passed over before it, all of seed_index's rows): the first of the seed's
    traces, in launch order, that qa accepted."""
    cands = [r for r in rows if r.get("seed_index") == seed_index]
    passed = []
    for r in cands:
        if r.get("accepted"):
            return r, passed, cands
        passed.append(r)
    return None, passed, cands


def _kind(failure):
    return (failure or {}).get("kind") or "infrastructure"


def _stage_failure(state):
    """(stage, kind, error) of the first failed stage of a state.json, or None."""
    for name, rec in (state.get("stages") or {}).items():
        if (rec or {}).get("status") == "failed":
            return name, rec.get("kind") or "infrastructure", rec.get("error")
    return None


def _coverage_numbers(seg, entry):
    c = seg.get("coverage") or {}
    keys = ("labelled_cm2", "ink_px", "background_px", "carried_cm2", "rendered_cm2", "carried_share_of_rendered",
            "share_of_published_supervision_reached", "gap_vox_median", "gap_share_within_4_vox",
            "share_refused_by_normal_test", "abs_offset_labelled_vox")
    out = {k: c.get(k) for k in keys}
    cc = (entry or {}).get("canvas_check") or {}
    out["canvas_check"] = {"passes": cc.get("passes"), "agreement": cc.get("agreement")} if cc else None
    over = (entry or {}).get("report_overlap") or {}
    out["report_overlap_cm2"] = {k: v.get("overlap_cm2", v.get("error")) for k, v in over.items()} or None
    return out


def readout(scores=None, surface=None, segment=None, model=None, state=None):
    """PASS, FAIL or VOID for the primary trace, one segment and one reader, by READOUT (the preregistered rule),
    from an AutoPipeline scores.json with score.transfer, or from the run's state.json alone when no scores were
    written (the run stopped before score). The primary is the first of seed READOUT["seed_index"]'s traces, in
    launch order, that qa accepted (`surface` names another trace to read by the same rule, never the verdict).

    Who decided each failure is in the records (autopipe.FAILURE_KINDS): our chain ("ours": a seed the seed check
    refused, a tracer exit or time-out, a qa rejection, a render refused or exiting, under min_area_cm2) gives FAIL,
    the infrastructure (a fetch, the relay, a 404, a tool that could not run, a lost driver, a stage cut off) VOID.
    So: none of the seed's traces accepted by qa is FAIL when our chain decided every one, else VOID; the primary
    not rendered is FAIL or VOID by its kind; and these come before any map, so the published side does not enter.
    With the primary rendered: VOID when a check of the published side or of the carrying failed or a map or score
    is missing; FAIL when a control on our maps was not caught or the paired interval fell below the margin; PASS
    otherwise. Returns {"verdict", "reasons", "numbers", "interpretation"}; every reason that applies is listed,
    VOID ones first. The numbers carry the coverage that goes beside the verdict."""
    R = READOUT
    segment, model = segment or R["segment"], model or R["model"]
    void, fail = [], []
    nums = {"segment": segment, "model": model}

    def done(extra_void=(), extra_fail=()):
        void.extend(extra_void)
        fail.extend(extra_fail)
        verdict = "VOID" if void else "FAIL" if fail else "PASS"
        return {"verdict": verdict, "reasons": void + fail, "numbers": nums, "rule": R,
                "interpretation": INTERPRETATION,
                "note": "a verdict on carried published labels: model output, not a reading"}

    rows, reps = _trace_rows(scores, state)
    if surface:
        nums["surface"] = surface
        row = next((r for r in rows or [] if r["sid"] == surface), None)
        if row is None and not (scores and surface in (scores.get("surfaces") or {})):
            return done([f"{surface} is not in the {'scores' if scores else 'state'}"])
    else:
        if reps is not None and reps != R["repeats"]:
            void.append(f"not the preregistered plan: {reps} traces a seed, not {R['repeats']}")
        if not rows:
            sf = _stage_failure(state) if state is not None else None
            if sf and sf[1] == "ours":
                return done(extra_fail=[f"no trace was planned: the {sf[0]} stage failed ({sf[2]})"])
            return done([f"no trace was planned: " + (f"the {sf[0]} stage failed ({sf[2]})" if sf else
                                                     "the run did not reach the trace stage")])
        row, passed, cands = primary(rows, R["seed_index"])
        nums["candidates"] = [{"surface": r["sid"], "accepted": r.get("accepted"),
                               "failure": ({k: (r["failure"] or {}).get(k) for k in ("stage", "kind", "reason")}
                                           if r.get("failure") else None)} for r in cands]
        if row is None:
            if not cands:
                return done([f"no trace of seed {R['seed_index']} is planned"])
            infra = [r["sid"] for r in cands if _kind(r.get("failure")) != "ours"]
            if infra:
                return done([f"none of seed {R['seed_index']}'s {len(cands)} traces was accepted by qa, and "
                             f"{', '.join(infra)} stopped for a reason of the infrastructure, so the primary is not "
                             "decided"])
            return done(extra_fail=[f"none of seed {R['seed_index']}'s {len(cands)} traces was accepted by qa: "
                                    + "; ".join(f"{r['sid']}: {(r.get('failure') or {}).get('reason')}"
                                                for r in cands)[:2000]])
        surface = nums["surface"] = row["sid"]
        nums["passed_over"] = [r["sid"] for r in passed]
        if row.get("failure"):
            f = row["failure"]
            why = f"the primary {surface} was accepted by qa but stopped at {f.get('stage')}: {f.get('reason')}"
            return done([why]) if _kind(f) != "ours" else done(extra_fail=[why])
    if scores is None:
        return done([f"no scores: the run stopped after {surface} was rendered, before ink or score finished"])
    chk = (scores.get("checks") or {}).get(segment)
    if not chk or chk.get("passes") is not True:
        void.append(f"labelxfer identity and displaced checks on {segment}: "
                    f"{'missing' if not chk else chk.get('error') or 'failed'}")
    ref = (((scores.get("references") or {}).get(segment) or {}).get("models") or {}).get(model) or {}
    whole = ref.get("whole") or {}
    rf, rr = (whole.get("forward") or {}).get("auc"), (whole.get("control") or {}).get("auc")
    nums["reference_whole"] = {"forward": rf, "reverse": rr}
    if rf is None or rr is None:
        void.append(f"the published {segment} map's own score is missing")
    else:
        if abs(rf - R["reference_whole_auc"]) > R["reference_tolerance"]:
            void.append(f"pipeline check: the published {segment} map scores {rf} on its own labels, not "
                        f"{R['reference_whole_auc']} within {R['reference_tolerance']}")
        if rr > R["max_reverse"]:
            void.append(f"the published {segment} reverse map scores {rr}, above {R['max_reverse']}")
    entry = (scores.get("surfaces") or {}).get(surface)
    if entry is None:
        return done([f"{surface} is not in the scores"])
    if entry.get("scorable") is False:
        f = entry.get("failure") or {}
        why = f"{surface}: {entry.get('why')}"
        return done([why]) if f and _kind(f) != "ours" else done(extra_fail=[why])
    seg = (entry.get("segments") or {}).get(segment) or {}
    if not seg:
        return done([f"{surface} has no record for {segment}"])
    nums["coverage"] = _coverage_numbers(seg, entry)
    if seg.get("scorable") is False:
        why, f = seg.get("why") or "", seg.get("failure")
        infra = _kind(f) != "ours" if f else why.startswith("labels not carried")
        return done([f"{surface} on {segment}: {why}"]) if infra else done(extra_fail=[f"{surface} on {segment}: {why}"])
    m = (seg.get("models") or {}).get(model) or {}
    fw = (m.get("forward") or {}).get("auc")
    r = (m.get("reverse") or {}).get("auc")
    sh = (m.get("shuffled") or {}).get("auc")
    dmax = (m.get("displaced") or {}).get("max_auc")
    pair = m.get("paired") or {}
    lo = (pair.get("ci95") or [None])[0]
    nums.update(forward=fw, reverse=r, shuffled=sh, displaced_max=dmax,
                reference_on_carried=((m.get("reference") or {}).get("on_carried_pixels") or {}).get("auc"),
                difference=pair.get("difference"), difference_ci95=pair.get("ci95"))
    if m.get("error") or None in (fw, r, sh, dmax, lo):
        void.append(f"{surface} on {segment}: a map or score is missing ({m.get('error') or 'incomplete'})")
    else:
        if r > R["max_reverse"]:
            fail.append(f"reverse control not caught: {r} above {R['max_reverse']}")
        if fw - sh < R["min_gap_shuffled"]:
            fail.append(f"shuffled control not caught: forward {fw} minus shuffled {sh} under {R['min_gap_shuffled']}")
        if fw - dmax < R["min_gap_displaced"]:
            fail.append(f"displaced control not caught: forward {fw} minus the best displaced {dmax} under "
                        f"{R['min_gap_displaced']}")
        if lo < -R["noninferiority_margin"]:
            fail.append(f"not non-inferior: the 95 % interval of ours minus published starts at {lo}, below "
                        f"-{R['noninferiority_margin']}")
    return done()


# ---------------------------------------------------------------- command line

def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("canvas", help="the render canvas vc_render_tifxyz makes for a tifxyz (scale 1)")
    a.add_argument("mesh")
    a = actions.add_parser("carry", help="carry a published segment's labels onto a traced surface's canvas")
    a.add_argument("trace", help="the tifxyz that was rendered (flattened or trimmed copy when one was used)")
    a.add_argument("--from", dest="published", required=True, help="the published segment's tifxyz, same frame")
    a.add_argument("--labels", required=True, help="folder with the segment's inklabels.zarr and supervision.zarr")
    a.add_argument("--out", required=True, help="output folder (keep it under work/)")
    a.add_argument("--voxel-um", type=float, required=True)
    a.add_argument("--surface-shape", type=int, nargs=2, metavar=("H", "W"),
                   help="the published surface volume's shape: refused unless the published canvas is it")
    a.add_argument("--max-gap-vox", type=float, default=MAX_GAP_VOX)
    a.add_argument("--max-normal-deg", type=float, default=MAX_NORMAL_DEG)
    a.add_argument("--lattice-px", type=int, default=LATTICE_PX)
    a.add_argument("--level", default="2")
    a.add_argument("--report", action="store_true", help="allow a report surface's labels (0841-ag405): only for "
                                                         "its frozen report recipe")
    a = actions.add_parser("check", help="identity and displaced checks of the carrying on one labelled segment")
    a.add_argument("mesh")
    a.add_argument("--labels", required=True)
    a.add_argument("--voxel-um", type=float, required=True)
    a.add_argument("--surface-shape", type=int, nargs=2, metavar=("H", "W"))
    a.add_argument("--displace-mm", type=float, default=DISPLACE_MM_FIXED)
    a.add_argument("--out")
    a.add_argument("--report", action="store_true", help="allow a report surface's labels")
    a = actions.add_parser("overlap", help="where a trace lies on another published surface, from the meshes alone "
                                           "(no labels): for a report surface such as 0841-ag405")
    a.add_argument("trace")
    a.add_argument("--on", dest="mesh", required=True, help="the other surface's tifxyz, same frame")
    a.add_argument("--voxel-um", type=float, required=True)
    a.add_argument("--out")
    a.add_argument("--max-gap-vox", type=float, default=MAX_GAP_VOX)
    a.add_argument("--max-normal-deg", type=float, default=MAX_NORMAL_DEG)
    a = actions.add_parser("canvas-check", help="does a vc_render_tifxyz render fill only the canvas pixels the "
                                                "carrying takes as rendered")
    a.add_argument("mesh", help="the tifxyz that was rendered")
    a.add_argument("render", help="its render (zarr)")
    a = actions.add_parser("score", help="AUC of a traced surface's maps on carried labels, with controls and the "
                                         "published surface's map on the same pixels")
    a.add_argument("xfer", help="a carry output folder")
    a.add_argument("forward")
    a.add_argument("--reverse")
    a.add_argument("--shuffled")
    a.add_argument("--reference", help="the published surface's map from the same reader (its own canvas)")
    a.add_argument("--displace-mm", type=float, default=DISPLACE_MM_FIXED)
    a.add_argument("--draws", type=int, default=2000)
    a.add_argument("--block-px", type=int, default=BLOCK_PX)
    a.add_argument("--seed", type=int, default=20261009)
    a.add_argument("--report", action="store_true", help="allow a report surface's labels")
    a = actions.add_parser("readout", help="the preregistered PASS, FAIL or VOID from an AutoPipeline scores.json "
                                           "(docs/prereg/2026-10-09-own-trace-ink.md)")
    a.add_argument("scores", nargs="?", help="the run's scores.json (may be absent when --state is given)")
    a.add_argument("--state", help="the run's state.json: read alone when the scores file is absent (a run that "
                                   "stopped before score), and for the traces when scores.json has no record of them")
    a.add_argument("--surface", help="read another trace by the same rule (never the verdict)")
    a.add_argument("--segment")
    a.add_argument("--model")
    for a in actions.choices.values():
        a.add_argument("--json", action="store_true")


def cmd_labelxfer(args):
    import sys
    try:
        if args.action == "canvas":
            m = read_mesh(args.mesh)
            h, w = canvas_shape(m)
            res = {"mesh": args.mesh, "grid": m["shape"], "scale": m["scale"], "canvas": [h, w],
                   "rendered_px": int(rendered_mask(m).sum())}
        elif args.action == "carry":
            res = carry(args.trace, args.published, args.labels, args.out, args.max_gap_vox, args.max_normal_deg,
                        args.voxel_um, args.lattice_px, level=args.level, surface_shape=args.surface_shape,
                        log=lambda s: print(s, file=sys.stderr), report=args.report)["record"]
        elif args.action == "check":
            res = check(args.mesh, args.labels, args.out, args.voxel_um, args.displace_mm,
                        surface_shape=args.surface_shape, log=lambda s: print(s, file=sys.stderr),
                        report=args.report)
        elif args.action == "overlap":
            res = overlap(args.trace, args.mesh, args.out, args.max_gap_vox, args.max_normal_deg,
                          voxel_um=args.voxel_um, log=lambda s: print(s, file=sys.stderr))
        elif args.action == "canvas-check":
            res = canvas_check(args.mesh, args.render)
        elif args.action == "readout":
            def read(path, what):
                try:
                    return json.loads(Path(path).read_text())
                except (OSError, ValueError) as exc:
                    raise VerifyError(f"cannot read {what} {path}: {exc}") from exc
            if not args.scores and not args.state:
                raise VerifyError("readout needs a scores.json, a --state, or both")
            have = bool(args.scores) and Path(args.scores).is_file()
            if args.scores and not have and not args.state:
                raise VerifyError(f"cannot read the scores {args.scores}: no such file (give --state for a run "
                                  "that stopped before score)")
            scores = read(args.scores, "the scores") if have else None
            state = read(args.state, "the state") if args.state else None
            res = readout(scores, args.surface, args.segment, args.model, state=state)
        else:
            res = score(args.xfer, {"f": args.forward, "r": args.reverse, "s": args.shuffled}, args.reference,
                        args.displace_mm, args.draws, args.block_px, args.seed, report=args.report)
    except VerifyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1, default=str))
    if args.action in ("check", "canvas-check"):
        return 0 if res["passes"] else 1
    return 0
