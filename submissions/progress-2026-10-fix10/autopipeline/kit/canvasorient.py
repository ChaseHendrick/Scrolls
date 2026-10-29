"""Turn a surface's render canvas upright before ink detection, and the ink maps back.

`python -m kit canvasorient measure|apply|back|check`.

Why. A traced surface's render canvas comes in whatever in-plane orientation its grid has: the tracer's grid is
not tied to the scroll axis, vc_flatten (ABF++) runs without its alignment options (alignToInputGrid and
rotateHighZToTop are off by default, villa e0bbb8b core/include/vc/flattening/ABFFlattening.hpp 34-42), and
vc_render_tifxyz copies the grid's axes onto the canvas, turning it only by right angles on request (--rotate
0/90/180/270, apps/src/vc_render_tifxyz.cpp 257-264). Published segments are in villa's standard layout, "V
down-screen aligned with +z, text readable" (vc_render_tifxyz.cpp 1297-1304), with the grid normal pointing out of
the scroll (Sourced fact). The released ink_9um readers were trained with right-angle turns and transposes only
(villa e0bbb8b vesuvius/src/vesuvius/ink_detection/data/augmentations.py 184-218): a canvas turned by another angle
is not what they saw (Sourced fact), and on a published PHerc0841 surface a 30 degree turn cost ink_9um about 0.15
AUC (Model output, this repository's ablation of 13 October 2026). This module measures, from the mesh alone, the
in-plane turn that puts a canvas into the published layout, turns a rendered surface volume by it, and takes an ink
map made on the turned canvas back to the original canvas. Whether that wins back AUC on a trace is an open
question until a preregistered test answers it (Untested idea).

Convention (the sign is the trap). Canvas positions are (row, col), rows going down the screen. An angle t turns
+row toward +col: R(t) = [[cos t, -sin t], [sin t, cos t]] acting on (row, col) vectors.

  phi      the direction of +z on a canvas: z grows fastest along (cos phi, sin phi). phi = 0 is the published
           layout (+z down the rows); phi = 90 means +z runs along +columns.
  turn     angle psi and mirror m: turned pixel b shows the source canvas at a = c_s + M (b - c_t), with
           M = R(psi), or M = F R(psi) when m, F = diag(1, -1) mirroring the columns; c_s and c_t are the two
           canvases' centers ((H - 1) / 2, (W - 1) / 2). A direction phi on the source shows at phi - psi on the
           turned canvas (with m: -phi - psi). So psi = phi turns +z down the rows, and psi = -phi after a mirror.
  back     source pixel a reads the turned map at b = c_t + M^-1 (a - c_s), with the same sampler as the turn.
  fits     a least-squares similarity fit dst ~ s R src + t on (row, col) points, angle atan2(R[1, 0], R[0, 0])
           (fit_angle), from turned pixels to the source positions they show returns psi. A fit on complex
           numbers w = a z + b with z = col + i row (angle from +col toward +row) returns -psi for the same
           mapping: from_complex_angle converts it. Mixing the two conventions turns the mirror angle.

The mirror. A proper turn keeps the sign of the grid normal N = dP/dcol x dP/drow, so a surface whose N points
toward the scroll's center (its columns mirrored against the standard) needs its columns mirrored before the turn;
the vote is kit vc3d_orient's, against the umbilicus when one is given (else a circle fitted to the surface, an
estimate). The render's layer order follows the same vote, so the layers keep growing toward the center.

The estimator. Each valid vertex with valid neighbors on both sides gives the gradient of z along the canvas
(central differences on the grid, scaled to canvas pixels by the render canvas formula, kit labelxfer
grid_of_pixel). phi is the direction of the sum of those gradients (each gradient's direction weighted by its
length); consistency is the length of the sum over the sum of the lengths (1 when every vertex agrees);
vertical is the median gradient length in voxels of z per canvas pixel (about 1 for a sheet that contains the
axis, as papyrus sheets nearly do; about 0 for a sheet lying across it). A least-squares plane z ~ a row + b col
gives a second angle, reported beside. The turn is applied only when the canvas is applicable: at least
MIN_VERTICES vertices, consistency at least min_consistency, vertical at least min_vertical, and a normal vote
that is not ambiguous. Otherwise nothing is turned and the record says why.

Sampling. turn and back share one sampler: bilinear (order 1, the default) or nearest (order 0); positions that
land on whole pixels (right angles) are copied exactly. The turned canvas is the bounding box of the whole source
canvas, so every source pixel has a place on it and back fills the source canvas completely. Turned pixels whose
position falls within HALO_PX (1 pixel) outside the source canvas read its edge; farther out they read 0
(unrendered) and are marked invalid. back reads only turned pixels marked valid (bilinear weights renormalized over
them), so whatever a model writes into the empty corners of the turned canvas never reaches the source canvas; the
halo makes sure every source pixel has a valid turned neighbor (the nearest is within 0.71 pixel).

Checks that can fail (`check`): planted turns of synthetic sheets recovered within 0.5 degrees, a mirrored sheet
flagged, a sheet lying across the axis refused, the canvas made upright measuring 0 while a canvas turned by a
deliberately wrong angle (45 degrees off, or the sign flipped) is caught, positions and right angles exact both
ways, a smooth stack's round trip within 2 gray levels, the two fit conventions pinned; and with --mesh, each real
tifxyz measured (a published segment should read within 3 degrees of 0) and planted turns of its own grid
recovered within 1 degree.

Needs numpy for everything that computes, tifffile for TIFF maps and zarr for zarr surface volumes; the module
imports with the standard library.
"""

import hashlib
import json
import math
from pathlib import Path

VERSION = 1
ORDERS = (0, 1)                 # nearest, bilinear
MIN_VERTICES = 16
MIN_CONSISTENCY = 0.9           # defaults; AutoPipeline's ink.orient stores its own in the plan
MIN_VERTICAL = 0.5
CHECK_ANGLES = (-170.0, -63.75, 0.0, 30.0, 90.0, 179.0)
CHECK_TOL_DEG = 0.5             # synthetic sheets
MESH_TOL_DEG = 1.0              # planted turns of a real grid
PUBLISHED_TOL_DEG = 3.0         # a published segment's own angle
WRONG_MIN_DEG = 20.0            # a canvas turned by a wrong angle must read at least this far from upright
ROUND_TRIP_MAX_LEVELS = 2       # a smooth uint8 stack turned and back, bilinear both ways
HALO_PX = 1.0                   # positions this close outside a canvas read its edge (so back always finds data)
CONVENTION = ("(row, col) with rows down; R(t) turns +row toward +col; phi is the direction of +z on the canvas "
              "(0: +z down the rows, villa's published layout); turned pixel b shows source a = c_s + M (b - c_t), "
              "M = R(psi) or F R(psi) with F = diag(1, -1) when mirrored; back reads b = c_t + M^-1 (a - c_s)")


class OrientError(ValueError):
    pass


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise OrientError("numpy is required for kit canvasorient (it is in villa's environment)") from exc
    return numpy


def wrap(deg):
    """An angle in degrees, wrapped into (-180, 180]."""
    d = math.fmod(float(deg), 360.0)
    if d <= -180.0:
        d += 360.0
    elif d > 180.0:
        d -= 360.0
    return d


def from_complex_angle(deg):
    """The angle of a complex-number similarity fit (w = a z + b, z = col + i row, angle from +col toward +row) in
    this module's convention: its negative."""
    return wrap(-float(deg))


# ---------------------------------------------------------------- reading a tifxyz

def read_tifxyz(path):
    """A tifxyz surface: {"xyz": (rows, cols, 3) float64 with NaN at holes, "valid", "scale": [sx, sy]}. Holes are
    VC3D's -1, NaN and negative points, as kit labelxfer.read_mesh takes them."""
    np = _np()
    path = Path(path)
    try:
        scale = [float(v) for v in json.loads((path / "meta.json").read_text())["scale"][:2]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise OrientError(f"{path}: meta.json gives no grid scale ({exc})") from exc
    if len(scale) != 2 or not all(math.isfinite(s) and s > 0 for s in scale):
        raise OrientError(f"{path}: meta.json scale {scale} is not two positive numbers")
    chans = [np.squeeze(_read_grid_tiff(np, path / f"{c}.tif")) for c in "xyz"]
    if not (chans[0].ndim == 2 and chans[0].shape == chans[1].shape == chans[2].shape) or min(chans[0].shape) < 3:
        raise OrientError(f"{path}: x, y and z must be 2D grids of one shape, at least 3 x 3")
    xyz = np.stack(chans, -1)
    valid = np.isfinite(xyz).all(-1) & (xyz[..., 0] != -1) & (xyz >= 0).all(-1)
    xyz[~valid] = np.nan
    return {"path": str(path), "xyz": xyz, "valid": valid, "scale": scale}


def _read_grid_tiff(np, f):
    """One channel of a tifxyz as float64: tifffile when it can decode the file, else kit vc3d_io's standard-library
    reader (LZW without imagecodecs, slower)."""
    first = None
    try:
        import tifffile
        return np.asarray(tifffile.imread(str(f)), dtype=np.float64)
    except Exception as exc:  # tifffile missing, or a codec it lacks (LZW needs imagecodecs)
        first = exc
    from . import vc3d_io
    try:
        img = vc3d_io.read_tiff(f)
    except Exception as exc:  # a missing file or an unreadable TIFF
        raise OrientError(f"cannot read {f}: {exc} (tifffile: {first})") from exc
    return np.asarray(img.data, dtype=np.float64).reshape(img.h, img.w)


def canvas_shape(grid_shape, scale, render_scale=1.0):
    """(H, W) of vc_render_tifxyz's canvas for a grid (kit labelxfer.canvas_shape's formula)."""
    rows, cols = grid_shape
    sx, sy = scale
    return (max(1, int(math.floor(rows * render_scale / sy + 0.5))),
            max(1, int(math.floor(cols * render_scale / sx + 0.5))))


# ---------------------------------------------------------------- the estimator

def _circular(np, gr, gc):
    """phi (degrees), consistency and per-vector deviations of gradient vectors (gr along rows, gc along columns)."""
    sr, sc = float(gr.sum()), float(gc.sum())
    mag = np.hypot(gr, gc)
    total = float(mag.sum())
    phi = math.degrees(math.atan2(sc, sr))
    cons = math.hypot(sr, sc) / total if total > 0 else 0.0
    dev = (np.degrees(np.arctan2(gc, gr)) - phi + 180.0) % 360.0 - 180.0
    return phi, cons, dev, mag


def gradients(z, valid=None):
    """Central-difference gradients of a 2D field along rows and columns, NaN where a neighbor is missing."""
    np = _np()
    z = np.asarray(z, dtype=np.float64)
    if valid is not None:
        z = np.where(valid, z, np.nan)
    gr = np.full(z.shape, np.nan)
    gc = np.full(z.shape, np.nan)
    gr[1:-1, :] = (z[2:, :] - z[:-2, :]) / 2.0
    gc[:, 1:-1] = (z[:, 2:] - z[:, :-2]) / 2.0
    return gr, gc


def measure_field(gr, gc, use=None, min_consistency=MIN_CONSISTENCY, min_vertical=MIN_VERTICAL):
    """The estimator on canvas-pixel gradients of z (gr down the rows, gc along the columns): phi, consistency,
    vertical and the spread, with what keeps it from being applicable (no normal vote here)."""
    np = _np()
    ok = np.isfinite(gr) & np.isfinite(gc)
    if use is not None:
        ok &= use
    n = int(ok.sum())
    out = {"vertices": n, "phi_deg": None, "consistency": None, "vertical": None, "why": []}
    if n < MIN_VERTICES:
        out["why"].append(f"{n} vertices with a gradient, under {MIN_VERTICES}")
        return out
    phi, cons, dev, mag = _circular(np, gr[ok], gc[ok])
    vert = float(np.median(mag))
    p5, p95 = np.percentile(dev, [5, 95])
    out.update(phi_deg=round(wrap(phi), 4), consistency=round(cons, 4), vertical=round(vert, 4),
               spread_deg={"p5": round(float(p5), 2), "p95": round(float(p95), 2),
                           "share_within_10": round(float((np.abs(dev) <= 10).mean()), 4)})
    if vert < min_vertical:
        out["why"].append(f"vertical {vert:.3f} under {min_vertical}: z hardly changes along the sheet (a sheet "
                          "lying across the axis has no up)")
    if cons < min_consistency:
        out["why"].append(f"consistency {cons:.3f} under {min_consistency}: +z points different ways across the "
                          "canvas, so no one turn makes it upright")
    return out


def measure_grid(xyz, valid, scale, render_scale=1.0, min_consistency=MIN_CONSISTENCY, min_vertical=MIN_VERTICAL):
    """The estimator on a grid of points (rows, cols, 3) in its render canvas's units, plus a least-squares plane
    of z over canvas positions."""
    np = _np()
    sx, sy = (float(v) for v in scale)
    z = np.where(valid, np.asarray(xyz, dtype=np.float64)[..., 2], np.nan)
    gr, gc = gradients(z)
    # grid_of_pixel: one canvas pixel down is sy / r grid rows, one to the right sx / r grid columns
    gr, gc = gr * (sy / render_scale), gc * (sx / render_scale)
    out = measure_field(gr, gc, None, min_consistency, min_vertical)
    rows, cols = z.shape
    rr, cc = np.nonzero(np.isfinite(z))
    if rr.size >= 3:
        A = np.stack([rr * (render_scale / sy), cc * (render_scale / sx), np.ones(rr.size)], 1)
        (a, b, _), *_ = np.linalg.lstsq(A, z[rr, cc], rcond=None)
        out["plane_phi_deg"] = round(wrap(math.degrees(math.atan2(b, a))), 4)
        if out["phi_deg"] is not None:
            out["plane_minus_phi_deg"] = round(wrap(out["plane_phi_deg"] - out["phi_deg"]), 4)
    out.update(grid=[rows, cols], scale=[sx, sy], render_scale=float(render_scale),
               canvas=list(canvas_shape((rows, cols), (sx, sy), render_scale)))
    return out


def measure_image(img, valid=None, min_consistency=MIN_CONSISTENCY, min_vertical=MIN_VERTICAL):
    """The estimator on a canvas image of z (or of any field): the direction its values grow along."""
    gr, gc = gradients(img, valid)
    return measure_field(gr, gc, None, min_consistency, min_vertical)


def normal_vote(path, umbilicus=None, centre_xy=None):
    """kit vc3d_orient's vote on the grid normal's sign: {"vote", "confidence", "outward_share", "centre",
    "layout"} or {"error"}."""
    from . import vc3d_orient
    try:
        o = vc3d_orient.orientation(path, umbilicus=umbilicus, centre_xy=centre_xy)
    except (vc3d_orient.OrientError, OSError, ValueError) as exc:
        return {"vote": None, "confidence": "ambiguous", "error": f"{type(exc).__name__}: {exc}"[:300]}
    n = o["normal"]
    return {"vote": n.get("vote"), "confidence": n.get("confidence"), "outward_share": n.get("outward_share"),
            "centre": o.get("centre"), "layout": o.get("layout"), "rows": o.get("rows")}


def decide(rec, vote, min_consistency=MIN_CONSISTENCY, min_vertical=MIN_VERTICAL):
    """Fill in mirror, angle_deg, applicable and why from an estimator record and a normal vote."""
    rec["normal"] = vote
    why = list(rec.get("why") or [])
    mirror = None
    if vote.get("vote") is None or vote.get("confidence") == "ambiguous":
        why.append("the grid normal's sign is ambiguous (" + str(vote.get("error") or vote.get("confidence")) +
                   "), so whether the columns are mirrored is unknown")
    else:
        mirror = vote["vote"] == "inward"
    rec["mirror"] = mirror
    phi = rec.get("phi_deg")
    rec["angle_deg"] = None if phi is None or mirror is None else round(wrap(-phi if mirror else phi), 4)
    rec["why"] = why
    rec["applicable"] = not why and rec["angle_deg"] is not None
    rec["thresholds"] = {"min_vertices": MIN_VERTICES, "min_consistency": min_consistency,
                         "min_vertical": min_vertical}
    rec["convention"] = CONVENTION
    return rec


def measure(surface, render_scale=1.0, umbilicus=None, centre_xy=None, min_consistency=MIN_CONSISTENCY,
            min_vertical=MIN_VERTICAL):
    """The turn that puts a tifxyz's render canvas into the published layout, from the mesh alone (no labels, no
    map): {"phi_deg", "consistency", "vertical", "plane_phi_deg", "normal", "mirror", "angle_deg", "applicable",
    "why", ...}. umbilicus: control points (kit vc3d_orient.load_umbilicus) or a file for the normal vote."""
    m = read_tifxyz(surface)
    rec = measure_grid(m["xyz"], m["valid"], m["scale"], render_scale, min_consistency, min_vertical)
    if umbilicus is not None and not isinstance(umbilicus, list):
        from . import vc3d_orient
        umbilicus = vc3d_orient.load_umbilicus(umbilicus)
    rec = {"surface": str(surface), **rec}
    return decide(rec, normal_vote(surface, umbilicus, centre_xy), min_consistency, min_vertical)


# ---------------------------------------------------------------- the transform

def _rot(deg):
    """R(deg) on (row, col), exact at multiples of 90 degrees."""
    q = float(deg) / 90.0
    if abs(q - round(q)) < 1e-12:
        c, s = [(1, 0), (0, 1), (-1, 0), (0, -1)][int(round(q)) % 4]
        return [[float(c), float(-s)], [float(s), float(c)]]
    t = math.radians(deg)
    return [[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]]


def _mul(a, b):
    return [[a[i][0] * b[0][j] + a[i][1] * b[1][j] for j in range(2)] for i in range(2)]


def _inv(m):
    det = m[0][0] * m[1][1] - m[0][1] * m[1][0]
    return [[m[1][1] / det, -m[0][1] / det], [-m[1][0] / det, m[0][0] / det]]


def plan_turn(source_shape, angle_deg, mirror=False, order=1):
    """The transform record of a turn: the turned canvas (the bounding box of the whole source canvas), both
    centers, M (turned offset to source offset) and its inverse. Standard library."""
    if order not in ORDERS:
        raise OrientError(f"order is one of {ORDERS} (nearest, bilinear)")
    h, w = (int(v) for v in source_shape)
    if h < 1 or w < 1:
        raise OrientError(f"source canvas {source_shape} is empty")
    angle = wrap(angle_deg)
    m = _rot(angle)
    if mirror:
        m = _mul([[1.0, 0.0], [0.0, -1.0]], m)
    mi = _inv(m)
    cs = ((h - 1) / 2.0, (w - 1) / 2.0)
    ext = [0.0, 0.0]
    for a in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)):
        d = (a[0] - cs[0], a[1] - cs[1])
        for k in range(2):
            ext[k] = max(ext[k], abs(mi[k][0] * d[0] + mi[k][1] * d[1]))
    ht, wt = (int(math.ceil(2 * e - 1e-6)) + 1 for e in ext)
    ct = ((ht - 1) / 2.0, (wt - 1) / 2.0)
    return {"kind": "kit canvasorient transform", "version": VERSION, "angle_deg": round(angle, 6),
            "mirror": bool(mirror), "order": int(order), "source_shape": [h, w], "turned_shape": [ht, wt],
            "source_centre": list(cs), "turned_centre": list(ct), "matrix": m, "inverse": mi,
            "convention": CONVENTION}


def check_transform(t):
    """A transform record read from a file: its fields, and its matrix consistent with its angle and mirror."""
    for k in ("angle_deg", "mirror", "order", "source_shape", "turned_shape"):
        if k not in t:
            raise OrientError(f"the transform has no {k}")
    want = plan_turn(t["source_shape"], t["angle_deg"], t["mirror"], t["order"])
    if want["turned_shape"] != list(t["turned_shape"]):
        raise OrientError(f"the transform's turned canvas {t['turned_shape']} is not {want['turned_shape']}, what its "
                          "angle and source canvas give")
    return want


def positions(t, inverse=False):
    """Fractional (rows, cols) that each pixel of the output canvas reads: on the turned canvas, the source
    positions (turn); with inverse, on the source canvas, the turned positions (back)."""
    np = _np()
    if inverse:
        m, (h, w), c_out, c_in = t["inverse"], t["source_shape"], t["source_centre"], t["turned_centre"]
    else:
        m, (h, w), c_out, c_in = t["matrix"], t["turned_shape"], t["turned_centre"], t["source_centre"]
    ii, jj = np.mgrid[0:h, 0:w].astype(np.float64)
    di, dj = ii - c_out[0], jj - c_out[1]
    return c_in[0] + m[0][0] * di + m[0][1] * dj, c_in[1] + m[1][0] * di + m[1][1] * dj


class _Sampler:
    """One sampler for both directions: nearest or bilinear at fractional positions of a 2D plane, exact copies
    where every position is a whole pixel, `fill` outside the plane."""

    def __init__(self, rows, cols, shape, order):
        np = _np()
        self.order, self.shape = order, tuple(shape)
        h, w = self.shape
        eps, halo = 1e-6, 1e-6 + HALO_PX
        self.inside = (rows >= -halo) & (rows <= h - 1 + halo) & (cols >= -halo) & (cols <= w - 1 + halo)
        rr, cc = np.rint(rows), np.rint(cols)
        self.exact = bool(np.abs(rows - rr).max(initial=0.0) < eps and np.abs(cols - cc).max(initial=0.0) < eps)
        r = np.clip(rows, 0, h - 1)
        c = np.clip(cols, 0, w - 1)
        if self.exact or order == 0:
            self.idx = (np.clip(rr, 0, h - 1).astype(np.int64), np.clip(cc, 0, w - 1).astype(np.int64))
        else:
            r0 = np.floor(r).astype(np.int64)
            c0 = np.floor(c).astype(np.int64)
            r1, c1 = np.minimum(r0 + 1, h - 1), np.minimum(c0 + 1, w - 1)
            fr, fc = (r - r0).astype(np.float32), (c - c0).astype(np.float32)
            self.corners = [(r0, c0, (1 - fr) * (1 - fc)), (r0, c1, (1 - fr) * fc), (r1, c0, fr * (1 - fc)),
                            (r1, c1, fr * fc)]

    @property
    def how(self):
        return "exact copy" if self.exact else ("nearest" if self.order == 0 else "bilinear")

    def __call__(self, plane, fill=0, mask=None):
        """The plane sampled at the positions. mask: where the plane holds data (False elsewhere, and NaN counts as
        no data); bilinear weights then fall on data only, renormalized, and a position with none reads fill.
        Sets self.ok, the positions that read data."""
        np = _np()
        a = np.asarray(plane)
        if tuple(a.shape) != self.shape:
            raise OrientError(f"a plane of {list(a.shape)}, not the {list(self.shape)} this sampler was made for")
        if mask is not None:
            mask = np.asarray(mask, bool)
            if mask.shape != a.shape:
                raise OrientError(f"a mask of {list(mask.shape)} for a plane of {list(a.shape)}")
        if a.dtype.kind == "f":
            nan = np.isnan(a)
            if nan.any():
                mask = ~nan if mask is None else mask & ~nan
        out_kind = a.dtype if a.dtype.kind in "iuf" else np.dtype(np.float32)
        ok = self.inside.copy()
        if self.exact or self.order == 0:
            v = a[self.idx]
            if mask is not None:
                ok &= mask[self.idx]
        else:
            if mask is None:
                v = sum(wt * a[i, j].astype(np.float32) for i, j, wt in self.corners)
            else:
                num = np.zeros(self.inside.shape, np.float64)
                den = np.zeros(self.inside.shape, np.float64)
                for i, j, wt in self.corners:
                    m = mask[i, j]
                    w = np.where(m, wt, 0.0)
                    num += w * np.where(m, a[i, j], 0).astype(np.float64)
                    den += w
                ok &= den > 1e-9
                v = (num / np.where(den > 1e-9, den, 1.0)).astype(np.float32)
            if a.dtype.kind in "iu":
                info = np.iinfo(a.dtype)
                v = np.clip(np.rint(v), info.min, info.max)
            v = v.astype(out_kind)
        self.ok = ok
        return np.where(ok, v, np.asarray(fill).astype(v.dtype) if a.dtype.kind in "iub" else fill).astype(
            v.dtype, copy=False)


def turn_stack(stack, t):
    """Every layer of a (layers, H, W) array turned onto the turned canvas: (array, valid mask, sampler name)."""
    np = _np()
    a = np.asarray(stack)
    if a.ndim != 3 or list(a.shape[1:]) != list(t["source_shape"]):
        raise OrientError(f"a stack of {list(a.shape)}, not layers by the transform's source canvas "
                          f"{t['source_shape']}")
    rows, cols = positions(t)
    s = _Sampler(rows, cols, a.shape[1:], t["order"])
    fill = 0 if a.dtype.kind in "iu" else np.nan
    out = np.empty((a.shape[0], *t["turned_shape"]), dtype=a.dtype)
    for k in range(a.shape[0]):
        out[k] = s(a[k], fill if a.dtype.kind in "iuf" else 0)
    return out, s.inside, s.how


def turn_plane(plane, t, inverse=False, mask=None):
    """One 2D array turned (or, with inverse, taken back): (array, valid mask, sampler name). Outside, and where
    the bilinear neighbors hold no data (mask False, or NaN): 0 for integer arrays, NaN for floats."""
    np = _np()
    a = np.asarray(plane)
    want = t["turned_shape"] if inverse else t["source_shape"]
    if a.ndim != 2 or list(a.shape) != list(want):
        raise OrientError(f"a map of {list(a.shape)}, not the {'turned' if inverse else 'source'} canvas {want}")
    rows, cols = positions(t, inverse)
    s = _Sampler(rows, cols, a.shape, t["order"])
    out = s(a, 0 if a.dtype.kind in "iub" else np.nan, mask)
    return out, s.ok, s.how


def turned_valid(t, halo=True):
    """The turned canvas's pixels that read the source canvas (apply's valid.tif); halo=False leaves out the ones
    that read its extended edge."""
    rows, cols = positions(t)
    if halo:
        return _Sampler(rows, cols, t["source_shape"], t["order"]).inside
    h, w = t["source_shape"]
    e = 1e-6
    return (rows >= -e) & (rows <= h - 1 + e) & (cols >= -e) & (cols <= w - 1 + e)


def back_map(plane, t):
    """An ink map made on the turned canvas, taken back onto the source canvas: (array of the source canvas's
    shape and the map's dtype, valid mask). Only turned pixels that show the source canvas are read, so values the
    model gave the empty corners of the turned canvas never reach the source canvas."""
    out, valid, _ = turn_plane(plane, t, inverse=True, mask=turned_valid(t))
    return out, valid


def turn_grid(xyz, valid, t):
    """A tifxyz grid's points turned as an image: the grid a surface would have had if traced turned. A turned
    vertex is valid only where it reads the source grid itself (no halo) and every bilinear neighbor it weighs is
    valid, so holes grow by their neighbors and nothing is extrapolated. Returns (xyz, valid)."""
    np = _np()
    a = np.where(valid[..., None], np.asarray(xyz, dtype=np.float64), np.nan)
    chans = [turn_plane(a[..., k], t)[0] for k in range(3)]
    full, _, _ = turn_plane(np.asarray(valid, np.float64), t)
    ok = turned_valid(t, halo=False) & (np.nan_to_num(full) > 1.0 - 1e-6)
    out = np.where(ok[..., None], np.stack(chans, -1), np.nan)
    return out, ok


def fit_angle(src, dst):
    """Least-squares similarity dst ~ s R src + t on (row, col) points (a mirror allowed): its angle
    atan2(R[1, 0], R[0, 0]) in degrees, this module's convention, and whether it mirrors."""
    np = _np()
    src, dst = np.asarray(src, np.float64), np.asarray(dst, np.float64)
    a, b = src - src.mean(0), dst - dst.mean(0)
    u, _, vt = np.linalg.svd(b.T @ a / len(a))
    r = u @ vt
    return {"angle_deg": round(math.degrees(math.atan2(r[1, 0], r[0, 0])), 4), "mirror": bool(np.linalg.det(r) < 0)}


# ---------------------------------------------------------------- files

def _array_sha256(a):
    np = _np()
    a = np.ascontiguousarray(a)
    h = hashlib.sha256(f"{a.dtype.str}|{list(a.shape)}|".encode())
    h.update(memoryview(a).cast("B"))
    return h.hexdigest()


def read_stack(path):
    """(layers, H, W) of a surface volume: a zarr group's level "0" or a bare zarr array, or a .npy."""
    np = _np()
    p = str(path)
    if p.endswith(".npy"):
        return np.load(p)
    from . import layers
    from .verify import VerifyError
    try:
        return np.asarray(layers.open_volume(p, "0")[...])
    except VerifyError as exc:
        raise OrientError(str(exc)) from exc


def write_stack(dest, data, attrs=None):
    """An OME-Zarr group with level "0" = data (zarr format 2), as scripts/vc3d/ink.py writes and reads one."""
    import shutil
    try:
        import zarr
    except ImportError as exc:
        raise OrientError("zarr is required to write a surface volume") from exc
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    try:
        group = zarr.open_group(str(dest), mode="w", zarr_format=2)
    except TypeError:  # zarr 2
        group = zarr.open_group(str(dest), mode="w")
    chunks = (data.shape[0], min(128, data.shape[1]), min(128, data.shape[2]))
    if hasattr(group, "create_array"):
        try:
            group.create_array("0", data=data, chunks=chunks)
        except TypeError:
            group.create_array("0", shape=data.shape, dtype=data.dtype, chunks=chunks)[...] = data
    else:
        group.create_dataset("0", data=data, chunks=chunks)
    group.attrs["multiscales"] = [{"version": "0.4", "name": "kit-canvasorient",
                                   "axes": [{"name": a, "type": "space"} for a in "zyx"],
                                   "datasets": [{"path": "0"}]}]
    for k, v in (attrs or {}).items():
        group.attrs[k] = v
    return dest


def read_map(path):
    np = _np()
    if str(path).endswith(".npy"):
        return np.squeeze(np.load(path))
    from .verify import VerifyError, load_map
    try:
        return load_map(path)
    except VerifyError as exc:
        raise OrientError(str(exc)) from exc


def write_map(path, arr):
    np = _np()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".npy":
        np.save(path, arr)
        return path
    try:
        import tifffile
    except ImportError as exc:
        raise OrientError("tifffile is required to write a TIFF map (or name a .npy)") from exc
    tifffile.imwrite(str(path), np.ascontiguousarray(arr), compression="zlib")
    return path


def apply(render, angle_deg, out, mirror=False, order=1, measured=None):
    """Turn a rendered surface volume: OUT/layers.zarr (the turned stack), OUT/valid.tif (255 where a turned pixel
    reads the source canvas) and OUT/transform.json (the transform, with both arrays' sha256). Returns the
    transform record."""
    src = read_stack(render)
    return apply_array(src, angle_deg, out, mirror, order, measured, source=str(render))


def apply_array(src, angle_deg, out, mirror=False, order=1, measured=None, source=None):
    """apply on a (layers, H, W) array already in memory (source: what to record as its origin)."""
    np = _np()
    src = np.asarray(src)
    if src.ndim != 3:
        raise OrientError(f"{source or 'the stack'}: expected (layers, height, width), got {list(src.shape)}")
    t = plan_turn(src.shape[1:], angle_deg, mirror, order)
    arr, valid, how = turn_stack(src, t)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rec = dict(t, source=source, sampler=how, layers=int(src.shape[0]), source_sha256=_array_sha256(src),
               turned_sha256=_array_sha256(arr), valid_px=int(valid.sum()),
               zarr=str(out / "layers.zarr"), valid=str(out / "valid.tif"))
    if measured is not None:
        rec["measured"] = measured
    write_stack(out / "layers.zarr", arr, {"kit_canvasorient": {k: rec[k] for k in (
        "angle_deg", "mirror", "order", "source_shape", "turned_shape", "source_sha256")}})
    write_map(out / "valid.tif", valid.astype(np.uint8) * 255)
    (out / "transform.json").write_text(json.dumps(rec, indent=1) + "\n")
    return rec


def load_transform(path):
    t = json.loads(Path(path).read_text())
    return check_transform(t) | {k: v for k, v in t.items() if k not in ("matrix", "inverse")}


def back(map_path, transform, out):
    """Take a map made on the turned canvas back to the source canvas; writes OUT (TIFF or .npy) and returns a
    record."""
    t = load_transform(transform) if not isinstance(transform, dict) else check_transform(transform) | transform
    m = read_map(map_path)
    arr, valid = back_map(m, t)
    write_map(out, arr)
    return {"map": str(map_path), "out": str(out), "shape": list(arr.shape), "dtype": str(arr.dtype),
            "valid_px": int(valid.sum()), "invalid_px": int((~valid).sum()), "angle_deg": t["angle_deg"],
            "mirror": t["mirror"], "order": t["order"]}


# ---------------------------------------------------------------- the self-check

def synthetic_sheet(alpha_deg, rows=41, cols=47, step=4.0, radius=300.0, axis=(500.0, 500.0), mirror=False,
                    noise=0.3, seed=0):
    """A piece of a cylinder (radius around a vertical axis) gridded so that +z runs along canvas direction
    alpha: (xyz, valid, scale). Columns run with the turn about +z (the grid normal outward) unless mirror."""
    np = _np()
    rng = np.random.default_rng(seed)
    ii, jj = np.mgrid[0:rows, 0:cols].astype(np.float64)
    di, dj = ii - (rows - 1) / 2.0, jj - (cols - 1) / 2.0
    a = math.radians(alpha_deg)
    along = di * math.cos(a) + dj * math.sin(a)          # canvas direction alpha: +z
    across = -di * math.sin(a) + dj * math.cos(a)        # perpendicular: around the axis
    if mirror:
        across = -across
    theta = 0.3 + across * step / radius
    x = axis[0] + radius * np.cos(theta)
    y = axis[1] + radius * np.sin(theta)
    z = 2000.0 + along * step + noise * rng.standard_normal(along.shape)
    xyz = np.stack([x, y, z], -1)
    return xyz, np.ones(along.shape, bool), [1.0 / step, 1.0 / step]


def flat_sheet(rows=31, cols=31, step=4.0, noise=0.3, seed=0):
    """A sheet lying across the axis (z nearly constant): no up to find."""
    np = _np()
    rng = np.random.default_rng(seed)
    ii, jj = np.mgrid[0:rows, 0:cols].astype(np.float64)
    xyz = np.stack([800.0 + jj * step, 900.0 + ii * step, 1500.0 + noise * rng.standard_normal(ii.shape)], -1)
    return xyz, np.ones(ii.shape, bool), [1.0 / step, 1.0 / step]


def write_tifxyz(path, xyz, scale):
    """A tifxyz folder (float32 TIFFs, holes as -1) from points (rows, cols, 3)."""
    np = _np()
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    a = np.where(np.isfinite(xyz), xyz, -1.0).astype(np.float32)
    for k, c in enumerate("xyz"):
        write_map(path / f"{c}.tif", a[..., k])
    (path / "meta.json").write_text(json.dumps({"scale": list(scale), "format": "tifxyz", "type": "seg"}))
    return path


def canvas_z(xyz, valid, scale, render_scale=1.0):
    """z on the render canvas (bilinear in the grid, NaN at holes): what the canvas turns."""
    np = _np()
    rows, cols = valid.shape
    h, w = canvas_shape((rows, cols), scale, render_scale)
    sx, sy = scale
    R, C = np.mgrid[0:h, 0:w].astype(np.float64)
    gy = rows / 2.0 + (R - (h - 1) / 2.0) * sy / render_scale
    gx = cols / 2.0 + (C - (w - 1) / 2.0) * sx / render_scale
    z = np.where(valid, xyz[..., 2], np.nan)
    s = _Sampler(np.clip(gy, 0, rows - 1), np.clip(gx, 0, cols - 1), (rows, cols), 1)
    return s(z.astype(np.float64), np.nan)


def _upright_after(zimg, angle, mirror, order=1):
    """phi measured on a canvas z image after turning it by angle (and mirror)."""
    t = plan_turn(zimg.shape, angle, mirror, order)
    turned, inside, _ = turn_plane(zimg, t)
    return measure_image(turned, inside & turned_valid(t, halo=False), 0.0, 0.0)["phi_deg"]


def _angle_off(a, b):
    return abs(wrap(a - b))


def check_synthetic(tmp):
    """Planted turns of synthetic sheets: recovered, the canvas made upright, a wrong angle caught, a mirrored sheet
    flagged, a sheet across the axis refused. Returns a list of records, each with passes."""
    out = []
    axis = (500.0, 500.0)
    for alpha in CHECK_ANGLES:
        for mirror in (False, True):
            xyz, valid, scale = synthetic_sheet(alpha, mirror=mirror, axis=axis)
            p = write_tifxyz(Path(tmp) / f"sheet-{alpha:+.2f}-{int(mirror)}", xyz, scale)
            m = measure(p, centre_xy=axis)
            rec = {"planted_deg": alpha, "planted_mirror": mirror, "phi_deg": m["phi_deg"],
                   "mirror": m["mirror"], "angle_deg": m["angle_deg"], "applicable": m["applicable"]}
            ok = (m["applicable"] and m["mirror"] is mirror and m["phi_deg"] is not None
                  and _angle_off(m["phi_deg"], alpha) <= CHECK_TOL_DEG)
            if ok:
                z = canvas_z(xyz, valid, scale)
                after = _upright_after(z, m["angle_deg"], mirror)
                wrong45 = _upright_after(z, m["angle_deg"] + 45.0, mirror)
                rec.update(upright_after_deg=after, wrong_plus_45_after_deg=wrong45)
                ok = _angle_off(after, 0.0) <= CHECK_TOL_DEG and _angle_off(wrong45, 0.0) >= WRONG_MIN_DEG
                if abs(wrap(2 * m["angle_deg"])) >= WRONG_MIN_DEG:      # the sign trap shows unless 2 psi is ~0
                    flipped = _upright_after(z, -m["angle_deg"], mirror)
                    rec["sign_flipped_after_deg"] = flipped
                    ok = ok and _angle_off(flipped, 0.0) >= WRONG_MIN_DEG
            rec["passes"] = bool(ok)
            out.append(rec)
    xyz, valid, scale = flat_sheet()
    p = write_tifxyz(Path(tmp) / "across-axis", xyz, scale)
    m = measure(p, centre_xy=(0.0, 0.0))
    out.append({"planted": "a sheet lying across the axis", "vertical": m["vertical"], "applicable": m["applicable"],
                "why": m["why"], "passes": not m["applicable"]})
    return out


def check_round_trip(seed=0):
    """Positions exact both ways, right angles copied exactly, a smooth stack's bilinear round trip within
    ROUND_TRIP_MAX_LEVELS, and the two fit conventions pinned."""
    np = _np()
    rng = np.random.default_rng(seed)
    out = {}
    worst = 0.0
    for shape, angle, mirror in (((37, 52), 47.3, False), ((60, 41), -123.0, True), ((33, 33), 179.0, False)):
        t = plan_turn(shape, angle, mirror)
        rows, cols = positions(t)
        # where each turned pixel reads the source, taken through the inverse, is the turned pixel itself
        ci, cj = t["turned_centre"], t["source_centre"]
        mi = t["inverse"]
        bi = ci[0] + mi[0][0] * (rows - cj[0]) + mi[0][1] * (cols - cj[1])
        bj = ci[1] + mi[1][0] * (rows - cj[0]) + mi[1][1] * (cols - cj[1])
        ii, jj = np.mgrid[0:t["turned_shape"][0], 0:t["turned_shape"][1]]
        worst = max(worst, float(np.abs(bi - ii).max()), float(np.abs(bj - jj).max()))
    out["positions_max_error_px"] = worst
    exact = True
    for angle in (0.0, 90.0, 180.0, -90.0):
        for mirror in (False, True):
            a = rng.integers(0, 256, (3, 9, 14), dtype=np.uint8)
            t = plan_turn(a.shape[1:], angle, mirror)
            turned, inside, how = turn_stack(a, t)
            back_, valid = back_map(turned[1], t)
            exact &= how == "exact copy" and bool(inside.all()) and bool(np.array_equal(back_, a[1]))
            # psi = 90 k is np.rot90 by -k (clockwise on screen); the mirror flips the source's columns first
            want = np.rot90(np.fliplr(a[0]) if mirror else a[0], -int(round(angle / 90.0)))
            exact &= bool(np.array_equal(turned[0], want))
    out["right_angles_exact"] = exact
    yy, xx = np.mgrid[0:96, 0:120].astype(np.float64)
    smooth = (128 + 60 * np.sin(yy / 13.0) * np.cos(xx / 17.0)).astype(np.uint8)
    t = plan_turn(smooth.shape, 37.0, False)
    turned, _, _ = turn_plane(smooth, t)
    back_, valid = back_map(turned, t)
    inner = np.zeros(smooth.shape, bool)
    inner[2:-2, 2:-2] = True
    err = np.abs(back_.astype(np.int64) - smooth.astype(np.int64))[inner & valid]
    out["smooth_round_trip_max_levels"] = int(err.max())
    out["smooth_round_trip_mean_levels"] = round(float(err.mean()), 4)
    out["back_fills_the_source_canvas"] = bool(valid.all())
    # the fit conventions: turned pixels to the source positions they show
    t = plan_turn((50, 70), 63.75, False)
    rows, cols = positions(t)
    ii, jj = np.mgrid[0:t["turned_shape"][0]:5, 0:t["turned_shape"][1]:5]
    src = np.stack([ii.ravel(), jj.ravel()], 1).astype(np.float64)
    dst = np.stack([rows[::5, ::5].ravel(), cols[::5, ::5].ravel()], 1)
    fit = fit_angle(src, dst)
    z = src[:, 1] + 1j * src[:, 0]
    w = dst[:, 1] + 1j * dst[:, 0]
    a = np.linalg.lstsq(np.stack([z, np.ones_like(z)], 1), w, rcond=None)[0][0]
    out["fit_angle_deg"] = fit["angle_deg"]
    out["complex_fit_angle_deg"] = round(float(np.degrees(np.angle(a))), 4)
    out["passes"] = bool(worst < 1e-9 and exact and out["smooth_round_trip_max_levels"] <= ROUND_TRIP_MAX_LEVELS
                         and out["back_fills_the_source_canvas"] and abs(fit["angle_deg"] - 63.75) < 1e-6
                         and abs(from_complex_angle(out["complex_fit_angle_deg"]) - 63.75) < 1e-3)
    return out


def check_mesh(path, umbilicus=None, planted=(-63.75, 30.0, 90.0, 150.0)):
    """A real tifxyz: its own angle (a published segment should read within PUBLISHED_TOL_DEG of 0), and planted
    turns of its grid recovered within MESH_TOL_DEG, the upright grid measuring 0 and a 45 degree wrong angle
    caught."""
    m = read_tifxyz(path)
    own = measure(path, umbilicus=umbilicus)
    rec = {"mesh": str(path), "grid": own["grid"], "phi_deg": own["phi_deg"], "consistency": own["consistency"],
           "vertical": own["vertical"], "plane_phi_deg": own.get("plane_phi_deg"), "normal": own["normal"],
           "mirror": own["mirror"], "applicable": own["applicable"], "why": own["why"],
           "standard_within_deg": PUBLISHED_TOL_DEG,
           "standard": bool(own["phi_deg"] is not None and _angle_off(own["phi_deg"], 0.0) <= PUBLISHED_TOL_DEG
                            and own["mirror"] is False),
           "planted": []}
    ok = own["applicable"]
    sx, sy = m["scale"]
    if abs(sx - sy) > 1e-9 * max(sx, sy):
        rec["planted_skipped"] = f"grid scale {m['scale']} is not square: turning the grid as an image would stretch it"
    elif own["phi_deg"] is not None:
        for beta in planted:
            t = plan_turn(m["valid"].shape, beta, False)
            xyz, valid = turn_grid(m["xyz"], m["valid"], t)
            got = measure_grid(xyz, valid, m["scale"])
            want = wrap(own["phi_deg"] - beta)
            r = {"planted_deg": beta, "expected_deg": round(want, 4), "phi_deg": got["phi_deg"]}
            good = got["phi_deg"] is not None and _angle_off(got["phi_deg"], want) <= MESH_TOL_DEG
            if good:
                up = plan_turn(valid.shape, got["phi_deg"], False)
                u_xyz, u_valid = turn_grid(xyz, valid, up)
                after = measure_grid(u_xyz, u_valid, m["scale"])["phi_deg"]
                bad = plan_turn(valid.shape, got["phi_deg"] + 45.0, False)
                b_xyz, b_valid = turn_grid(xyz, valid, bad)
                wrong = measure_grid(b_xyz, b_valid, m["scale"])["phi_deg"]
                r.update(upright_after_deg=after, wrong_plus_45_after_deg=wrong)
                good = (after is not None and _angle_off(after, 0.0) <= MESH_TOL_DEG and wrong is not None
                        and _angle_off(wrong, 0.0) >= WRONG_MIN_DEG)
            r["passes"] = bool(good)
            ok = ok and good
            rec["planted"].append(r)
    rec["passes"] = bool(ok)
    return rec


def self_check(meshes=(), umbilicus=None, require_standard=False):
    """Every check above; with meshes, each real tifxyz too (require_standard: each must also read as the
    published layout). Returns {"synthetic", "round_trip", "meshes", "passes"}."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="canvasorient-check-") as tmp:
        syn = check_synthetic(tmp)
    rt = check_round_trip()
    ms = [check_mesh(p, umbilicus) for p in meshes]
    ok = all(r["passes"] for r in syn) and rt["passes"] and all(
        r["passes"] and (r["standard"] or not require_standard) for r in ms)
    return {"synthetic": syn, "round_trip": rt, "meshes": ms, "require_standard": bool(require_standard),
            "tolerances_deg": {"synthetic": CHECK_TOL_DEG, "mesh_planted": MESH_TOL_DEG,
                               "published": PUBLISHED_TOL_DEG, "wrong_at_least": WRONG_MIN_DEG},
            "convention": CONVENTION, "passes": bool(ok)}


# ---------------------------------------------------------------- command line

def build_parser(p):
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("measure", help="the turn that puts a tifxyz's render canvas into the published layout")
    a.add_argument("surface", help="tifxyz folder (the one that was rendered)")
    a.add_argument("--umbilicus", help="umbilicus file for the normal vote (default: a circle fitted to the surface)")
    a.add_argument("--render-scale", type=float, default=1.0)
    a.add_argument("--min-consistency", type=float, default=MIN_CONSISTENCY)
    a.add_argument("--min-vertical", type=float, default=MIN_VERTICAL)
    a = sub.add_parser("apply", help="turn a rendered surface volume (zarr) by an angle into OUT")
    a.add_argument("render", help="surface volume zarr (level 0 is read) or .npy")
    a.add_argument("angle", type=float, help="psi in degrees (measure's angle_deg)")
    a.add_argument("out", help="output folder: layers.zarr, valid.tif, transform.json")
    a.add_argument("--mirror", action="store_true", help="mirror the columns before the turn (measure's mirror)")
    a.add_argument("--order", type=int, choices=ORDERS, default=1, help="0 nearest, 1 bilinear (default)")
    a = sub.add_parser("back", help="take a map made on the turned canvas back to the original canvas")
    a.add_argument("map", help="ink map on the turned canvas (TIFF or .npy)")
    a.add_argument("transform", help="transform.json written by apply")
    a.add_argument("out", help="output map (TIFF or .npy), the original canvas's shape")
    a = sub.add_parser("check", help="self-test on planted turns; exit 1 when a check fails")
    a.add_argument("--mesh", action="append", default=[], help="a real tifxyz to measure and plant turns on")
    a.add_argument("--umbilicus")
    a.add_argument("--require-standard", action="store_true",
                   help="each --mesh must also read as the published layout (published segments)")
    a.add_argument("--out", help="write the record here as JSON")


def cmd_canvasorient(args):
    import sys
    try:
        if args.action == "measure":
            rec = measure(args.surface, args.render_scale, args.umbilicus, None, args.min_consistency,
                          args.min_vertical)
        elif args.action == "apply":
            rec = apply(args.render, args.angle, args.out, args.mirror, args.order)
            rec = {k: v for k, v in rec.items() if k not in ("matrix", "inverse")}
        elif args.action == "back":
            rec = back(args.map, args.transform, args.out)
        else:
            rec = self_check(args.mesh, args.umbilicus, args.require_standard)
            if args.out:
                Path(args.out).write_text(json.dumps(rec, indent=1) + "\n")
    except OrientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rec, indent=1))
    return 1 if args.action == "check" and not rec["passes"] else 0
