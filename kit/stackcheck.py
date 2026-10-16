"""Check a stack of consecutive tifxyz segments of one scroll against its umbilicus, from geometry alone.

Give the segments inner to outer, one per winding, as local tifxyz folders (x.tif, y.tif, z.tif and meta.json) or
as folders on the open-data bucket (https:// or s3:// URLs, fetched once into --cache), with the scroll's published
umbilicus JSON. Seven checks, each on the segments' vertex positions and the umbilicus only (no CT, no surface
prediction, no ink):

  order             rays from the umbilicus every degree on planes of constant z: for each adjacent pair, the
                    share of the rays crossing both once on which the inner segment lies outside the outer one (all
                    of them, and those by more than --coincide-um, which decide the flag), and the signed spacing;
                    per vertex, a nearest other segment along the normal that is out of order (a lower winding
                    outside, or a higher one inside)
  pair spacing      on the same rays, for each adjacent pair: the rays on which the two lie within --coincide-um of
                    each other (one sheet traced twice, or sheets pressed closer than the traces can be told apart),
                    and the pair's median spacing against the median over the pairs up to two places away (itself
                    included), flagged below 0.5 or above 1.75 times it (a winding counted twice, or one missing
                    all the way)
  missing sectors   heights and angles where a segment has no vertex while both its neighbours do, within the
                    segment's own z extent: the neighbours' spacing on those rays against the rays where the segment
                    is present (overall and by height), the same for the next pair out, a control of other pairs as
                    many windings apart on the same rays, and the neighbours' vertices there
  missing runs      the same where two or more adjacent windings have no vertex while the windings either side do,
                    at heights within the z extent of at least one of them
  skipped windings  vertices whose nearest other segment along the normal is two or more windings away, outward or
                    inward, and closer than half the local pitch (so nothing lies between)
  turn overlaps     per grid line along the turn, the angle traced past a full turn, and the doubly traced end:
                    the piece farther from the umbilicus (the turn ran on onto the next winding's sheet), unless the
                    nearer piece lies on the previous winding's sheet (its median distance to that segment under half
                    the rest of the segment's, and closer in that ratio than the far piece to the next) where no
                    doubly traced end of the previous segment is marked already; where it is, and its distance
                    along the normal to the segment whose sheet it lies on
  stack ends        heights where a winding between two traced ones has no segment, from each segment's z extent

A check is flagged when what it finds reaches both --min-count (rays or vertices) and --min-share (of the rays or
vertices it looked at). A check that had nothing to look at (an adjacent pair that no ray crosses once each, a
segment with a neighbour along the normal for under half of its vertices, or whose order check keeps under half of
its vertices) is listed under summary.not_checked, and the stack is then not reported clean. The innermost and
outermost segments have a neighbour on one side only, so they get no missing-sector check and a missing run that
includes them cannot be seen; summary.not_covered says so in every report. Exit status: 0 when every check looked
and none flagged, 1 when something is flagged or not checked, 2 when the run could not be made (bad input, an
unwritable output or an unexpected error).

Units and frame. Positions are tifxyz values, in voxels of one volume. The umbilicus must be in that volume; when
the segments are in another one (for example a published 9.362 um copy against a 2.399 um umbilicus), --transform
maps them into the umbilicus's volume first, with a 3x4 (or 4x4) matrix from a JSON file, or with the catalog's
sample-level matrix as catalog:SAMPLE:FROM_VOLUME:TO_VOLUME (from --catalog, by default the bucket's
metadata.json). The volume ids in the folder names ("-on-VOLUME-N.NNNum.tifxyz"), the transform and the
umbilicus (its metadata.volume, else its file name) must agree when they are known. Every position, z and grid row
in the report is then in the umbilicus's volume, except the examples' row and column, which are on the input grid.
The voxel size is --voxel-um, else the umbilicus's metadata.voxelsize_um, else (without --transform) the segment
folder name's "-N.NNNum.tifxyz"; any two of these that are known must agree to 1 %. Angles are degrees about the
umbilicus at the same z, atan2(y - y_u, x - x_u), 0 to 360, with the umbilicus interpolated linearly between
control points and held constant beyond them. Distances are micrometres: radial along a ray from the umbilicus, or
along a vertex normal for the vertex checks. Areas are summed vertex cell areas in cm2. A gap's width is the angle
from its first ray to its last.

Masks. --flags writes an .npz with one boolean mask per segment and check, on the segment's input grid
("NAME/order", "NAME/missing_sector", "NAME/skipped_winding", "NAME/turn_overlap", "NAME/coincident",
"NAME/stack_end" and their union "NAME/any"), so flagged vertices can be dropped before a spiral fit or a relative
winding count. A missing-sector mask marks the vertices of the segments either side of a missing sector or a
missing run where the segments between have no vertex (within 1.5 grid steps of height and arc), inside their z
extent. A stack-end mask marks the segments either side at the heights where a winding between them has no
segment. A turn-overlap mask marks the doubly traced end and the next segment's vertices at the same height and
angle, or the previous segment's when the doubly traced end lies on the previous winding's sheet. A coincident
vertex has another segment within --coincide-um along its normal, so the two cannot be told apart there; order
conflicts leave those out, and leave out the turn-overlap masks. The .npz suffix is added to a --flags path that
lacks it, and the report's flags_file names the file written.

Memory. Each segment's grid, made --upsample times denser, is indexed for the normal search, and all are held at
once: at the defaults (--stride 1 --upsample 2) a full 2.399 um copy of one PHerc0139 winding takes about 2 GB, so
use --stride 2 --upsample 1 for such copies (a 96 um grid; run A of the PHerc0139 note).

Usage:

    python -m kit stackcheck SEG_INNER ... SEG_OUTER --umbilicus UMBILICUS.json [--transform SPEC]
        [--voxel-um UM] [--stride N] [--planes N | --plane-z Z0 Z1 STEP] [--json] [--out REPORT.json]
        [--flags FLAGS.npz]

    # PHerc0139 w033 to w037 on their own volume (2.399 um), every second grid row and column:
    B=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139
    python -m kit stackcheck \\
        $B/segments/20260219000000-w033_2026021913/mesh/20260219000000-on-20260102150214-2.399um.tifxyz \\
        ... one URL per segment, inner to outer ... \\
        --umbilicus $B/representations/umbilicus/20260102150214-umbilicus-20260826112529.json \\
        --stride 2 --upsample 1 --out work/stackcheck/w033-w037.json --flags work/stackcheck/w033-w037-flags.npz

    # The 9.362 um copies on volume 20250728140407, mapped into 20260102150214 with the catalog's matrix:
    python -m kit stackcheck SEG ... --umbilicus UMBILICUS.json \\
        --transform catalog:PHerc0139:20250728140407:20260102150214

A segment can be named NAME=PATH (NAME without '/', '\\' or ':'); otherwise its name is the nearest folder above the
path that is neither "mesh" nor a ".tifxyz" folder. Needs numpy, tifffile and scipy.
"""

import json
import math
import os
import re
import time
import urllib.parse
from pathlib import Path

from .verify import VerifyError

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
DEFAULTS = {
    "ray_step_deg": 1.0,        # rays from the umbilicus, one per this many degrees
    "planes": 50,               # planes of constant z, evenly over the stack's height (unless plane_z is given)
    "plane_z": None,            # (start, stop, step) in voxels, stop included
    "max_normal_um": 600.0,     # farthest neighbour looked for along a vertex normal
    "coincide_um": 20.0,        # another segment this close along the normal: the two cannot be told apart
    "skip_frac": 0.5,           # a skipped winding is closer than this share of the local pitch
    "tol_cells": 1.5,           # same height and angle: within this many grid steps of z and of arc
    "upsample": 2,              # neighbour segments are made this much denser (bilinear) for the normal search
    "min_count": 10,            # a check is flagged at this many rays or vertices ...
    "min_share": 0.01,          # ... and this share of the rays or vertices it looked at
}
PAIR_SPACING = (0.5, 1.75)      # adjacent pair's median ray spacing over the nearby pairs' median: flagged outside
MASKS = ("order", "missing_sector", "skipped_winding", "turn_overlap", "coincident", "stack_end")
FOLDER_UM = re.compile(r"-([0-9]+(?:\.[0-9]+)?)um\.tifxyz/?$")
FOLDER_VOLUME = re.compile(r"-on-([^/]+?)-[0-9]+(?:\.[0-9]+)?um\.tifxyz/?$")


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise VerifyError("kit stackcheck needs numpy, tifffile and scipy") from exc
    return numpy


def _kdtree():
    try:
        from scipy.spatial import cKDTree
    except ImportError as exc:
        raise VerifyError("kit stackcheck needs scipy (cKDTree)") from exc
    return cKDTree


def _r(x, n=1):
    if x is None:
        return None
    x = float(x)
    return None if not math.isfinite(x) else round(x, n)


def _q(a, ps=(25, 50, 75), n=1):
    np = _np()
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    return [_r(v, n) for v in np.percentile(a, ps)] if len(a) else None


# ---------------------------------------------------------------- inputs

def _is_url(s):
    return str(s).startswith(("http://", "https://", "s3://"))


def _https(url):
    url = str(url)
    if url.startswith("s3://"):
        bucket, _, key = url[5:].partition("/")
        if bucket == "vesuvius-challenge-open-data":
            return f"{BUCKET}/{key}"
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return url


def segment_name(path):
    """The nearest folder above a tifxyz path that is neither 'mesh' nor a '.tifxyz' folder."""
    s = str(path).rstrip("/")
    parts = urllib.parse.urlparse(_https(s)).path.split("/") if _is_url(s) else list(Path(s).parts)
    for p in reversed(parts):
        if p and p != "mesh" and not p.endswith(".tifxyz"):
            return p
    return parts[-1] if parts else s


def fetch_tifxyz(url, cache):
    """Local copy of a tifxyz folder on a bucket (x.tif, y.tif, z.tif, and meta.json when there), under cache."""
    from . import meshaudit
    url = _https(url).rstrip("/")
    parts = urllib.parse.urlparse(url)
    rel = [p for p in parts.path.split("/") if p]
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.hostname.strip(".") == "" \
            or any(c in parts.netloc for c in ("/", "\\")):
        raise VerifyError(f"refusing a URL without an http(s) scheme and a host name: {url}")
    if any(p in (".", "..") or "\\" in p for p in rel):
        raise VerifyError(f"refusing a URL with '.' or '..' in its path: {url}")
    # checked on the path as written, not with symlinks resolved, so a cache folder linked to another disk still works
    root = Path(os.path.abspath(cache))
    dest = Path(os.path.abspath(root.joinpath(parts.netloc, *rel)))
    if dest == root or root not in dest.parents:
        raise VerifyError(f"refusing a URL whose cache folder {dest} is outside --cache {root}")
    dest.mkdir(parents=True, exist_ok=True)
    for f in ("x.tif", "y.tif", "z.tif", "meta.json"):
        p = dest / f
        if p.is_file() and p.stat().st_size > 0:
            continue
        try:
            data = meshaudit._get(f"{url}/{f}", timeout=300)
        except Exception as exc:  # network or HTTP error
            if f == "meta.json":
                continue
            raise VerifyError(f"cannot fetch {url}/{f}: {exc}") from exc
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
    return dest


def read_tifxyz(folder):
    """(xyz (H, W, 3) float64, valid (H, W), meta) of a tifxyz folder; -1, NaN and all-zero vertices are holes."""
    np = _np()
    try:
        import tifffile
    except ImportError as exc:
        raise VerifyError("kit stackcheck needs tifffile") from exc
    from . import meshaudit
    folder = Path(folder)
    try:
        arrs = [meshaudit.imread_capped(str(folder / f"{c}.tif")) for c in "xyz"]
    except Exception as exc:  # missing file or unreadable TIFF
        raise VerifyError(f"cannot read the tifxyz folder {folder}: {exc}") from exc
    if any(a.ndim != 2 or a.shape != arrs[0].shape for a in arrs):
        raise VerifyError(f"{folder}: x.tif, y.tif and z.tif must be 2D grids of one shape")
    xyz = np.stack(arrs, -1).astype(np.float64)
    valid = np.isfinite(xyz).all(-1) & (xyz > -0.5).all(-1) & (np.abs(xyz).sum(-1) > 0)
    meta = {}
    if (folder / "meta.json").is_file():
        try:
            meta = json.loads((folder / "meta.json").read_text())
        except (OSError, ValueError):
            meta = {}
    return xyz, valid, meta


class Umbilicus:
    """Control points of a scroll's umbilicus: x and y at z, linear between points and constant beyond."""

    def __init__(self, z, x, y, voxel_um=None, source=None, volume=None):
        np = _np()
        o = np.argsort(np.asarray(z, float))
        self.z, self.x, self.y = (np.asarray(v, float)[o] for v in (z, x, y))
        if len(self.z) == 0:
            raise VerifyError("the umbilicus has no control points")
        self.voxel_um, self.source, self.volume = voxel_um, source, volume

    def at(self, z):
        np = _np()
        return np.interp(z, self.z, self.x), np.interp(z, self.z, self.y)


def parse_umbilicus(data, source=None):
    """An Umbilicus from a published umbilicus JSON object: {"control_points": [{"x", "y", "z"}, ...],
    "metadata": {"voxelsize_um": ...}} (a bare list of such points is read too)."""
    pts = (data.get("control_points") or data.get("points")) if isinstance(data, dict) else data
    if not isinstance(pts, list) or not pts or not all(isinstance(p, dict) and {"x", "y", "z"} <= set(p) for p in pts):
        raise VerifyError(f"{source or 'umbilicus'}: expected control points with x, y and z keys")
    meta = (data.get("metadata") or {}) if isinstance(data, dict) else {}
    um = meta.get("voxelsize_um")
    if um is not None:
        try:
            um = float(um)
        except (TypeError, ValueError):
            um = float("nan")
        if not (math.isfinite(um) and um > 0):
            raise VerifyError(f"{source or 'umbilicus'}: metadata.voxelsize_um must be a number above 0 "
                              f"(got {meta.get('voxelsize_um')!r})")
    try:
        cols = [[float(p[c]) for p in pts] for c in "zxy"]
    except (TypeError, ValueError) as exc:
        raise VerifyError(f"{source or 'umbilicus'}: control points must be numbers") from exc
    if not all(math.isfinite(v) for col in cols for v in col):
        raise VerifyError(f"{source or 'umbilicus'}: control points must be finite")
    return Umbilicus(cols[0], cols[1], cols[2], um, source, meta.get("volume"))


def load_umbilicus(src):
    """The umbilicus JSON at a local path or URL (parse_umbilicus)."""
    from . import meshaudit
    try:
        data = meshaudit.get_json(_https(src)) if _is_url(src) else json.loads(Path(src).read_text())
    except (OSError, ValueError) as exc:
        raise VerifyError(f"cannot read the umbilicus {src}: {exc}") from exc
    return parse_umbilicus(data, str(src))


def load_transform(spec, catalog=None):
    """A 3x4 matrix taking segment positions into the umbilicus's volume: a JSON file (a 3x4 or 4x4 list, or an
    object with "matrix"), or catalog:SAMPLE:FROM:TO for the catalog's sample-level matrix."""
    np = _np()
    if spec is None:
        return None
    if str(spec).startswith("catalog:"):
        bits = str(spec).split(":")
        if len(bits) != 4:
            raise VerifyError("--transform catalog:SAMPLE:FROM_VOLUME:TO_VOLUME")
        from . import meshaudit
        try:
            cat = meshaudit.load_catalogue(catalog)
        except (OSError, ValueError) as exc:
            raise VerifyError(f"cannot read the catalog: {exc}") from exc
        try:
            m, _ = meshaudit.sample_matrix(cat, bits[1], bits[2], bits[3])
        except KeyError:
            m = None
        if m is None:
            raise VerifyError(f"the catalog has no {bits[1]} matrix from {bits[2]} to {bits[3]}")
    else:
        try:
            data = json.loads(Path(spec).read_text())
        except (OSError, ValueError) as exc:
            raise VerifyError(f"cannot read the transform {spec}: {exc}") from exc
        m = data.get("matrix") if isinstance(data, dict) else data
    try:
        M = np.asarray(m, float)
    except (TypeError, ValueError) as exc:
        raise VerifyError("a transform is a 3x4 or 4x4 matrix") from exc
    if M.shape == (4, 4):
        if not np.allclose(M[3], [0.0, 0.0, 0.0, 1.0]):
            raise VerifyError("a 4x4 transform must have [0, 0, 0, 1] as its last row")
        M = M[:3]
    if M.shape != (3, 4) or not np.isfinite(M).all():
        raise VerifyError("a transform is a 3x4 or 4x4 matrix")
    return M


# ---------------------------------------------------------------- grid geometry

def grid_geometry(xyz, valid):
    """(unit normals (H, W, 3), cell area per vertex in voxels^2, ok, median edge length) of a grid: central
    differences where both neighbours are valid, else one-sided; ok = valid with a finite normal."""
    np = _np()
    P = np.where(valid[..., None], xyz, np.nan)
    with np.errstate(invalid="ignore"):
        def grad(axis):
            n = P.shape[axis]
            fwd = np.full_like(P, np.nan)
            bwd = np.full_like(P, np.nan)
            lo, hi = [slice(None)] * 3, [slice(None)] * 3
            lo[axis], hi[axis] = slice(0, n - 1), slice(1, n)
            fwd[tuple(lo)] = P[tuple(hi)] - P[tuple(lo)]
            bwd[tuple(hi)] = P[tuple(hi)] - P[tuple(lo)]
            f_ok, b_ok = np.isfinite(fwd).all(-1), np.isfinite(bwd).all(-1)
            return np.where((f_ok & b_ok)[..., None], 0.5 * (fwd + bwd), np.where(f_ok[..., None], fwd, bwd))

        n = np.cross(grad(1), grad(0))
        nn = np.linalg.norm(n, axis=-1)
        ok = valid & np.isfinite(nn) & (nn > 1e-9)
        normals = np.where(ok[..., None], n / np.where(ok, nn, 1.0)[..., None], np.nan)
        area = np.where(ok, nn, 0.0)
        edges = [np.linalg.norm(np.diff(P, axis=a), axis=-1) for a in (0, 1)]
    el = np.concatenate([e[np.isfinite(e)].ravel() for e in edges])
    return normals, area, ok, (float(np.median(el)) if el.size else float("nan"))


def upsample(xyz, valid, k):
    """A k times denser grid by bilinear interpolation; a new vertex is valid when every corner it uses is."""
    np = _np()
    if k <= 1:
        return xyz, valid
    H, W = valid.shape
    out = np.full(((H - 1) * k + 1, (W - 1) * k + 1, 3), np.nan)
    ov = np.zeros(out.shape[:2], bool)
    for a in range(k):
        for b in range(k):
            h, w = (H if a == 0 else H - 1), (W if b == 0 else W - 1)
            if h <= 0 or w <= 0:
                continue
            fa, fb = a / k, b / k
            acc = (1 - fa) * (1 - fb) * xyz[:h, :w]
            v = valid[:h, :w].copy()
            if a:
                acc = acc + fa * (1 - fb) * xyz[1:h + 1, :w]
                v &= valid[1:h + 1, :w]
            if b:
                acc = acc + (1 - fa) * fb * xyz[:h, 1:w + 1]
                v &= valid[:h, 1:w + 1]
            if a and b:
                acc = acc + fa * fb * xyz[1:h + 1, 1:w + 1]
                v &= valid[1:h + 1, 1:w + 1]
            out[a::k, b::k] = acc
            ov[a::k, b::k] = v
    out[~ov] = np.nan
    return out, ov


def turn_angles(xyz, valid, cx, cy):
    """Angle in degrees of each vertex about the umbilicus at its own height (cx, cy per vertex), unwrapped along
    the grid direction in which the angle turns and aligned line to line, so that two vertices of one segment one
    turn apart differ by 360; NaN where not valid. Returns (angles, along): along is 1 when the grid's columns
    run along the turn (each row is a line along the turn), 0 when its rows do."""
    np = _np()
    th = np.where(valid, np.arctan2(xyz[..., 1] - cy, xyz[..., 0] - cx), np.nan)

    def wrap(d):
        return (d + np.pi) % (2 * np.pi) - np.pi

    def turning(a, ax):
        dd = wrap(np.diff(a, axis=ax))
        return float(np.nanmedian(np.abs(dd))) if np.isfinite(dd).any() else 0.0

    along = 1 if turning(th, 1) >= turning(th, 0) else 0
    T = th if along == 1 else th.T
    dd = wrap(np.diff(T, axis=1))
    rate = float(np.nanmedian(dd)) if np.isfinite(dd).any() else 0.0     # signed turn per grid step along the turn
    out = np.full(T.shape, np.nan)
    ref = np.full(T.shape[1], np.nan)          # last unwrapped angle seen in each column
    for i in range(T.shape[0]):
        cols = np.flatnonzero(np.isfinite(T[i]))
        if len(cols) == 0:
            continue
        # unwrap each run of adjacent valid columns on its own; across a hole, take the multiple of a turn nearest
        # the turn rate times the columns skipped, so a hole wider than half a turn is not crossed the short way
        t = T[i, cols].copy()
        cut = np.concatenate([[0], np.flatnonzero(np.diff(cols) > 1) + 1, [len(cols)]])
        for r in range(len(cut) - 1):
            a, b = cut[r], cut[r + 1]
            u = np.unwrap(t[a:b])
            if r:
                expect = t[a - 1] + rate * (cols[a] - cols[a - 1])
                u = u - 2 * np.pi * np.round((u[0] - expect) / (2 * np.pi))
            t[a:b] = u
        have = np.flatnonzero(np.isfinite(ref))
        if len(have):
            prev = np.interp(cols, have, ref[have])
            t = t - 2 * np.pi * np.round(np.median(t - prev) / (2 * np.pi))
        out[i, cols] = t
        ref[cols] = t
    out = np.degrees(out)
    return (out if along == 1 else out.T), along


class Segment:
    """One segment of the stack: its (strided) grid in the report's frame, and its geometry about the umbilicus."""

    def __init__(self, name, xyz, valid, path=None, stride=1, input_shape=None, input_xyz=None):
        np = _np()
        self.name, self.path, self.stride = str(name), (str(path) if path is not None else None), int(stride)
        self.input_shape = tuple(input_shape or valid.shape)
        self.valid = np.asarray(valid, bool).copy()
        self.xyz = np.where(self.valid[..., None], np.asarray(xyz, float), np.nan)
        self.input_xyz = input_xyz

    def prepare(self, umb):
        np = _np()
        n, self.area, self.ok, self.step = grid_geometry(self.xyz, self.valid)
        if not self.ok.any():
            raise VerifyError(f"{self.name}: no vertex with a usable normal")
        cx, cy = umb.at(np.nan_to_num(self.xyz[..., 2]))
        dx, dy = self.xyz[..., 0] - cx, self.xyz[..., 1] - cy
        self.radius = np.hypot(dx, dy)
        self.theta = np.mod(np.degrees(np.arctan2(dy, dx)), 360.0)
        flip = (n[..., 0] * dx + n[..., 1] * dy) < 0          # normals point away from the umbilicus
        self.normals = np.where(flip[..., None], -n, n)
        self.turn, self.along = turn_angles(self.xyz, self.ok, cx, cy)
        z = self.xyz[self.ok][:, 2]
        self.zmin, self.zmax = float(z.min()), float(z.max())
        self.rmed = float(np.median(self.radius[self.ok]))
        self.n = int(self.ok.sum())


def split_spec(spec):
    """(name or None, path) of a NAME=PATH or PATH segment argument. The text before the first '=' is a name only
    when it holds no path separator or ':' and the whole argument is not an existing path."""
    s = str(spec)
    name, sep, rest = s.partition("=")
    if sep and name and rest and not any(c in name for c in "/\\:") and not Path(s).exists():
        return name, rest
    return None, s


def load_segments(specs, transform=None, stride=1, cache="work/stackcheck/cache", log=None):
    """Segments from NAME=PATH or PATH specs (local folders or bucket URLs), strided and mapped by the transform."""
    np = _np()
    segs = []
    for spec in specs:
        name, path = split_spec(spec)
        folder = fetch_tifxyz(path, cache) if _is_url(path) else Path(path)
        if log and _is_url(path):
            log(f"stackcheck: {path} -> {folder}")
        xyz, valid, _ = read_tifxyz(folder)
        shape = valid.shape
        xyz, valid = xyz[::stride, ::stride], valid[::stride, ::stride]
        raw = xyz.copy()
        if transform is not None:
            xyz = xyz @ transform[:, :3].T + transform[:, 3]
        segs.append(Segment(name or segment_name(path), xyz, valid, path, stride, shape,
                            raw if transform is not None else None))
    names = [s.name for s in segs]
    if len(set(names)) != len(names):
        raise VerifyError(f"segment names must differ (name them NAME=PATH): {names}")
    return segs


def folder_voxel_um(path):
    m = FOLDER_UM.search(str(path).rstrip("/"))
    return float(m.group(1)) if m else None


def folder_volume(path):
    """The volume id in a tifxyz folder name 'ID-on-VOLUME-N.NNNum.tifxyz', or None."""
    m = FOLDER_VOLUME.search(str(path).rstrip("/"))
    return m.group(1) if m else None


def umbilicus_volume(umb):
    """The volume id of an umbilicus: the start of its metadata.volume ('VOLUME-2.399um-....zarr'), else of its
    file name ('VOLUME-umbilicus-....json'), or None."""
    if umb.volume:
        return str(umb.volume).split("-")[0] or None
    m = re.search(r"([^/]+?)-umbilicus-[^/]*$", str(umb.source or ""))
    return m.group(1) if m else None


# ---------------------------------------------------------------- rays from the umbilicus

def _triangles(seg):
    """Both triangles of every grid cell with four valid corners, (N, 3, 3), with their z extent."""
    np = _np()
    v = seg.valid
    c = v[:-1, :-1] & v[1:, :-1] & v[:-1, 1:] & v[1:, 1:]
    rr, cc = np.nonzero(c)
    X = seg.xyz
    P00, P10, P01, P11 = X[rr, cc], X[rr + 1, cc], X[rr, cc + 1], X[rr + 1, cc + 1]
    T = np.concatenate([np.stack([P00, P10, P11], 1), np.stack([P00, P11, P01], 1)])
    return T, T[:, :, 2].min(1), T[:, :, 2].max(1)


def plane_cut(tri, z0):
    """Pieces (M, 2, 2) in x, y where the triangles cross the plane z = z0 (a vertex at z0 counts as above)."""
    np = _np()
    T, zmin, zmax = tri
    t = T[(zmin < z0) & (zmax >= z0)]
    if not len(t):
        return np.zeros((0, 2, 2))
    above = t[:, :, 2] >= z0
    pts, crs = [], []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        cr = above[:, i] != above[:, j]
        zi, zj = t[:, i, 2], t[:, j, 2]
        s = np.where(cr, (z0 - zi) / np.where(cr, zj - zi, 1.0), 0.0)
        pts.append(t[:, i, :2] + s[:, None] * (t[:, j, :2] - t[:, i, :2]))
        crs.append(cr)
    P, K = np.stack(pts, 1), np.stack(crs, 1)
    idx = np.argsort(~K, axis=1, kind="stable")[:, :2]
    return np.take_along_axis(P, idx[:, :, None], 1)


def ray_radii(pieces, centre, nrays, keep=4):
    """For rays from centre at angles 360 k / nrays: the number of distinct crossings of the pieces, and the
    first `keep` crossing distances from the centre, sorted (NaN beyond the count)."""
    np = _np()
    counts = np.zeros(nrays, np.int16)
    R = np.full((nrays, keep), np.nan, np.float32)
    if not len(pieces):
        return counts, R
    step = 2 * np.pi / nrays
    a = pieces[:, 0] - centre
    b = pieces[:, 1] - centre
    ta = np.arctan2(a[:, 1], a[:, 0])
    d = (np.arctan2(b[:, 1], b[:, 0]) - ta + np.pi) % (2 * np.pi) - np.pi
    lo, hi = np.minimum(ta, ta + d), np.maximum(ta, ta + d)
    klo = np.ceil(lo / step - 1e-9).astype(np.int64)
    khi = np.floor(hi / step + 1e-9).astype(np.int64)
    cnt = np.maximum(khi - klo + 1, 0)
    if cnt.sum() == 0:
        return counts, R
    idx = np.repeat(np.arange(len(pieces)), cnt)
    k = klo[idx] + (np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt))
    ux, uy = np.cos(k * step), np.sin(k * step)
    A, E = a[idx], (b - a)[idx]
    den = ux * E[:, 1] - uy * E[:, 0]
    ok = np.abs(den) > 1e-12
    s = np.where(ok, -(ux * A[:, 1] - uy * A[:, 0]) / np.where(ok, den, 1.0), -1.0)
    r = ux * (A[:, 0] + s * E[:, 0]) + uy * (A[:, 1] + s * E[:, 1])
    ok &= (s >= -1e-9) & (s <= 1 + 1e-9) & (r > 0)
    k, r = np.mod(k[ok], nrays), r[ok]
    o = np.lexsort((r, k))
    k, r = k[o], r[o]
    first = np.ones(len(k), bool)
    first[1:] = (k[1:] != k[:-1]) | (np.diff(r) > 0.01)     # a crossing on a shared edge counts once
    k, r = k[first], r[first]
    counts = np.bincount(k, minlength=nrays).astype(np.int16)
    start = np.searchsorted(k, np.arange(nrays))
    rank = np.arange(len(k)) - start[k]
    sel = rank < keep
    R[k[sel], rank[sel]] = r[sel]
    return counts, R


def cast_rays(segs, umb, planes, step_deg, log=None):
    """Crossing counts (P, S, R) and first crossing distances (P, S, R, 4), voxels, of every segment on every ray."""
    np = _np()
    nrays = int(round(360.0 / step_deg))
    cnt = np.zeros((len(planes), len(segs), nrays), np.int16)
    rad = np.full((len(planes), len(segs), nrays, 4), np.nan, np.float32)
    tris = [_triangles(s) for s in segs]
    for i, z0 in enumerate(planes):
        cx, cy = umb.at(z0)
        c = np.array([float(cx), float(cy)])
        for j, tri in enumerate(tris):
            cnt[i, j], rad[i, j] = ray_radii(plane_cut(tri, z0), c, nrays)
    if log:
        log(f"stackcheck: {len(planes)} planes x {nrays} rays cast")
    return cnt, rad, np.arange(nrays) * (360.0 / nrays)


def circ_range(deg):
    """[start, end, width] of the smallest arc holding every angle, from start toward increasing angle to end."""
    np = _np()
    a = np.sort(np.mod(np.asarray(deg, float), 360.0))
    if len(a) == 0:
        return None
    if len(a) == 1:
        return [_r(a[0]), _r(a[0]), 0.0]
    gaps = np.diff(np.concatenate([a, [a[0] + 360.0]]))
    i = int(np.argmax(gaps))
    return [_r(a[(i + 1) % len(a)]), _r(a[i]), _r(360.0 - gaps[i])]


def circ_quantiles(deg, ps=(10, 50, 90)):
    """Percentiles of angles that lie within half a turn of their circular mean, as angles 0 to 360."""
    np = _np()
    a = np.radians(np.asarray(deg, float))
    if not len(a):
        return None
    m = math.atan2(np.sin(a).mean(), np.cos(a).mean())
    rel = (a - m + np.pi) % (2 * np.pi) - np.pi
    return [_r(math.degrees(m + v) % 360.0) for v in np.percentile(rel, ps)]


def circular_runs(mask):
    """(start, end) index pairs, inclusive, of the runs of True in a circular boolean array."""
    np = _np()
    m = np.asarray(mask, bool)
    n = len(m)
    if m.all():
        return [(0, n - 1)]
    if not m.any():
        return []
    k = int(np.argmin(m))
    idx = (np.arange(n) + k) % n
    mm = m[idx]
    out, i = [], 0
    while i < n:
        if mm[i]:
            j = i
            while j + 1 < n and mm[j + 1]:
                j += 1
            out.append((int(idx[i]), int(idx[j])))
            i = j + 1
        else:
            i += 1
    return out


# ---------------------------------------------------------------- neighbours along the normal

class Dense:
    """A neighbour segment for the normal search: its grid made denser, with normals, indexed by height and by arc
    length about the umbilicus (angles mod 360 at the segment's median radius, repeated one turn either side), so
    every layer of it at a point's height and angle is found together."""

    def __init__(self, seg, k, umb):
        np = _np()
        up, uv = upsample(seg.xyz, seg.valid, k)
        n, _, ok, step = grid_geometry(up, uv)
        self.pts, self.nrm = up[ok], n[ok]
        self.step = step if math.isfinite(step) else seg.step / max(k, 1)
        self.rmed, self.umb = seg.rmed, umb
        q = self.key(self.pts)
        turn = 2 * np.pi * self.rmed
        self.tree = _kdtree()(np.concatenate([q, q + [0.0, turn], q - [0.0, turn]]))
        cx, cy = umb.at(self.pts[:, 2])
        r = np.hypot(self.pts[:, 0] - cx, self.pts[:, 1] - cy)
        self.rlo, self.rhi = float(r.min()), float(r.max())

    def key(self, X):
        np = _np()
        cx, cy = self.umb.at(X[:, 2])
        a = np.mod(np.arctan2(X[:, 1] - cy, X[:, 0] - cx), 2 * np.pi)
        return np.stack([X[:, 2], a * self.rmed], -1)


def _candidates(p, n, D, centre, k, bound):
    """For points p with unit normals n: where each normal line meets the tangent planes of D's k dense vertices
    nearest in height and arc to `centre`, as (t along n, lateral distance of that point from the vertex)."""
    np = _np()
    d, j = D.tree.query(D.key(centre), k=k, distance_upper_bound=bound)
    found = np.isfinite(d)
    jj = np.where(found, j, 0) % len(D.pts)
    b, nb = D.pts[jj], D.nrm[jj]
    c = np.einsum("ij,ikj->ik", n, nb)
    ok = found & (np.abs(c) >= 0.5)
    t = np.einsum("ikj,ikj->ik", b - p[:, None, :], nb) / np.where(ok, c, 1.0)
    lat = np.linalg.norm(p[:, None, :] + t[..., None] * n[:, None, :] - b, axis=-1)
    return np.where(ok, t, np.nan), np.where(ok, lat, np.inf)


def normal_hits(P, N, D, maxd, foot, chunk=50000):
    """Signed distances along each unit normal N from points P to the nearest crossing of segment D on each side,
    voxels: (outward, t >= 0; inward, t < 0), NaN where none within maxd. Candidates are D's vertices at the point's
    height and angle (every layer of D there), where the normal meets their tangent planes within 3 feet plus the
    distance along the normal of them (a normal up to 45 degrees off the line to them, as on a sheared or
    non-circular sheet); each side's nearest is then looked up again around its crossing, where it must lie
    within `foot` of a vertex of D."""
    np = _np()
    pos, neg = np.full(len(P), np.nan), np.full(len(P), np.nan)
    if not len(P):
        return pos, neg
    for s in range(0, len(P), chunk):
        p, n = P[s:s + chunk], N[s:s + chunk]
        t, lat = _candidates(p, n, D, p, 8, 3.0 * foot)
        for out, side in ((pos, t >= 0), (neg, t < 0)):
            sel = side & (lat <= 3.0 * foot + np.abs(t)) & (np.abs(t) <= maxd)
            has = sel.any(1)
            if not has.any():
                continue
            est = np.take_along_axis(t, np.argmin(np.where(sel, np.abs(t), np.inf), 1)[:, None], 1)[:, 0]
            ph, nh = p[has], n[has]
            t2, lat2 = _candidates(ph, nh, D, ph + est[has, None] * nh, 8, 2.0 * foot)
            sel2 = (lat2 <= foot) & (np.abs(t2) <= maxd) & ((t2 >= 0) if out is pos else (t2 < 0))
            best = np.take_along_axis(t2, np.argmin(np.where(sel2, np.abs(t2), np.inf), 1)[:, None], 1)[:, 0]
            res = np.full(len(p), np.nan)
            res[has] = np.where(sel2.any(1), best, np.nan)
            out[s:s + chunk] = res
    return pos, neg


def neighbour_table(segs, umb, upsample_k, maxd, tol_cells, log=None):
    """Per segment and vertex (NaN or -1 where none): the nearest other segment along the outward normal and its
    distance, the same inward, and the distance to each adjacent segment's nearest crossing, either side."""
    np = _np()
    dense = [Dense(s, upsample_k, umb) for s in segs]
    t0 = time.time()
    table = []
    for a, A in enumerate(segs):
        ok = A.ok
        P, N = A.xyz[ok], A.normals[ok]
        out_d, out_j = np.full(len(P), np.inf), np.full(len(P), -1)
        in_d, in_j = np.full(len(P), np.inf), np.full(len(P), -1)
        adj = {}
        r = A.radius[ok]
        for b, D in enumerate(dense):
            if b == a or D.rlo > r.max() + maxd or D.rhi < r.min() - maxd:
                continue
            tp, tn = normal_hits(P, N, D, maxd, tol_cells * D.step)
            pos = np.isfinite(tp) & (tp < out_d)
            out_d[pos], out_j[pos] = tp[pos], b
            neg = np.isfinite(tn) & (-tn < in_d)
            in_d[neg], in_j[neg] = -tn[neg], b
            if abs(b - a) == 1:
                adj[b] = np.fmin(np.abs(tp), np.abs(tn))
        grid = lambda v, fill: _to_grid(A, v, fill)  # noqa: E731
        table.append({"out_d": grid(np.where(np.isfinite(out_d), out_d, np.nan), np.nan), "out_j": grid(out_j, -1),
                      "in_d": grid(np.where(np.isfinite(in_d), in_d, np.nan), np.nan), "in_j": grid(in_j, -1),
                      "adj": {b: grid(t, np.nan) for b, t in adj.items()}})
        if log:
            log(f"stackcheck: neighbours along the normal of {A.name} ({time.time() - t0:.0f} s)")
    return table


def _to_grid(seg, values, fill):
    np = _np()
    g = np.full(seg.ok.shape, fill, dtype=np.asarray(values).dtype if np.asarray(values).dtype != bool else bool)
    g[seg.ok] = values
    return g


# ---------------------------------------------------------------- same height and angle

def _sector_tree(z, ang_deg, rmed, tol):
    """KD-tree over (height, arc length at radius rmed) in units of tol, angles mod 360, repeated one turn either
    side so a query near 0 or 360 degrees finds both."""
    np = _np()
    if not len(z):
        return None
    a = np.radians(np.mod(ang_deg, 360.0))
    q = np.stack([z / tol, a * rmed / tol], -1)
    turn = 2 * np.pi * rmed / tol
    return _kdtree()(np.concatenate([q, q + [0.0, turn], q - [0.0, turn]]))


def _within(tree, z, ang_deg, rmed, tol):
    """Per query point: whether the tree holds a point within one tolerance (Chebyshev) in height and arc."""
    np = _np()
    if tree is None or not len(z):
        return np.zeros(len(z), bool)
    a = np.radians(np.mod(ang_deg, 360.0))
    d, _ = tree.query(np.stack([z / tol, a * rmed / tol], -1), k=1, p=np.inf, distance_upper_bound=1.0 + 1e-9)
    return np.isfinite(d)


def sector_mask(mark, absent, present, tol_cells):
    """Vertices of segment `mark` at whose height and angle (mod 360, within tol_cells of mark's grid steps of z
    and of arc at mark's median radius) no segment in `absent` (one segment or a list) has a vertex while segment
    `present` has one, at heights within the z extent of at least one absent segment (lower and higher heights are
    stack ends, not missing sectors)."""
    np = _np()
    absent = list(absent) if isinstance(absent, (list, tuple)) else [absent]
    out = np.zeros(mark.ok.shape, bool)
    tol = tol_cells * mark.step
    z, th = mark.xyz[mark.ok][:, 2], mark.theta[mark.ok]

    def tree(s):
        return _sector_tree(s.xyz[s.ok][:, 2], s.theta[s.ok], mark.rmed, tol)

    inz = np.zeros(len(z), bool)
    for s in absent:
        inz |= (z >= s.zmin - tol) & (z <= s.zmax + tol)
    miss = inz & _within(tree(present), z, th, mark.rmed, tol)
    for s in absent:
        if miss.any():
            miss[miss] = ~_within(tree(s), z[miss], th[miss], mark.rmed, tol)
    out[mark.ok] = miss
    return out


# ---------------------------------------------------------------- the checks

def turn_overlap(seg):
    """Per line along the turn, the angle traced past a full turn (over half a grid step of arc), and the two pieces
    traced at the same angles, as (spans, past, outer piece mask, inner piece mask, which end of the turn the outer
    piece is). The outer piece is the one farther from the umbilicus; check_stack decides which piece is the
    doubly traced one from the neighbours."""
    np = _np()
    T = seg.turn if seg.along == 1 else seg.turn.T
    Rr = seg.radius if seg.along == 1 else seg.radius.T
    tol = math.degrees(0.5 * seg.step / max(seg.rmed, 1e-9))
    lo_m, hi_m = np.zeros(T.shape, bool), np.zeros(T.shape, bool)
    spans, past, dr = [], [], []
    for i in range(T.shape[0]):
        cols = np.flatnonzero(np.isfinite(T[i]))
        if len(cols) < 2:
            continue
        u = T[i, cols]
        e = float(u.max() - u.min())
        spans.append(e)
        x = e - 360.0
        if x <= tol:
            continue
        past.append(x)
        lo, hi = u < u.min() + x, u > u.max() - x
        lo_m[i, cols[lo]] = True
        hi_m[i, cols[hi]] = True
        ul, rl = u[lo], Rr[i, cols[lo]]
        o = np.argsort(ul)
        dr.extend((Rr[i, cols[hi]] - np.interp(u[hi] - 360.0, ul[o], rl[o])).tolist())
    end = "end" if (np.median(dr) if dr else 1.0) > 0 else "start"
    outer, inner = (hi_m, lo_m) if end == "end" else (lo_m, hi_m)
    if seg.along == 0:
        outer, inner = outer.T, inner.T
    return np.array(spans), np.array(past), outer & seg.ok, inner & seg.ok, end


def _components(mask):
    np = _np()
    if not mask.any():
        return []
    from scipy import ndimage
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), int))
    sizes = np.bincount(lab.ravel())[1:]
    return [lab == (i + 1) for i in np.argsort(-sizes, kind="stable")]


def _describe(seg, mask, vu):
    """Count, area, z and angle extent, and connected parts of a vertex mask."""
    np = _np()
    out = {"vertices": int(mask.sum()), "share": _r(mask.sum() / max(seg.n, 1), 4),
           "area_cm2": _r(seg.area[mask].sum() * (vu * 1e-4) ** 2, 3)}
    if mask.any():
        out["z"] = [_r(seg.xyz[mask][:, 2].min(), 0), _r(seg.xyz[mask][:, 2].max(), 0)]
        out["angle_deg"] = circ_range(seg.theta[mask])
        out["parts"] = len(_components(mask))
    return out


def _examples(seg, mask, extra=None, k=3):
    """Up to k vertices of the largest connected part of a mask, at the 25th, 50th and 75th percentile of z."""
    np = _np()
    parts = _components(mask)
    if not parts:
        return []
    rr, cc = np.nonzero(parts[0])
    o = np.argsort(seg.xyz[rr, cc, 2], kind="stable")
    out, seen = [], set()
    for f in (0.25, 0.5, 0.75)[:k]:
        i = o[int(round(f * (len(o) - 1)))]
        r, c = int(rr[i]), int(cc[i])
        if (r, c) in seen:
            continue
        seen.add((r, c))
        rec = {"segment": seg.name, "row": r * seg.stride, "col": c * seg.stride,
               "xyz": [_r(v, 0) for v in seg.xyz[r, c]], "angle_deg": _r(seg.theta[r, c])}
        if seg.input_xyz is not None:
            rec["xyz_input"] = [_r(v, 1) for v in seg.input_xyz[r, c]]
        if extra:
            rec.update(extra(r, c))
        out.append(rec)
    return out


def _spacing(d, vu, n=1):
    np = _np()
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    if not len(d):
        return {"rays": 0}
    return {"rays": int(len(d)), "median_um": _r(np.median(d) * vu, n),
            "um_q10_25_50_75_90": _q(d * vu, (10, 25, 50, 75, 90), n),
            "inside_share": _r((d < 0).mean(), 3)}


def _arcs_meet(a, b):
    """Do two arcs (start, end, width in degrees, from start toward increasing angle) share an angle?"""
    def inside(x, r):
        return (x - r["start_deg"]) % 360.0 <= r["width_deg"]
    return inside(a["start_deg"], b) or inside(b["start_deg"], a)


def main_sector(runs):
    """The longest series of consecutive planes whose widest gaps overlap from plane to plane: one missing sector
    followed up the stack, leaving out small gaps elsewhere near the segment's ends."""
    best, cur = [], []
    for r in runs:
        if cur and (r["plane"] != cur[-1]["plane"] + 1 or not _arcs_meet(cur[-1], r)):
            cur = []
        cur.append(r)
        if len(cur) > len(best):
            best = list(cur)
    return best


def plane_heights(segs, planes=None, plane_z=None):
    np = _np()
    if plane_z:
        z0, z1, dz = (float(v) for v in plane_z)
        if dz <= 0 or z1 < z0:
            raise VerifyError("--plane-z START STOP STEP needs STEP > 0 and STOP >= START")
        return np.arange(z0, z1 + 0.5 * dz, dz)
    lo, hi = min(s.zmin for s in segs), max(s.zmax for s in segs)
    n = int(planes or DEFAULTS["planes"])
    return lo + (np.arange(n) + 0.5) * (hi - lo) / n


def check_settings(settings=None):
    """The defaults updated with the given settings (None keeps a default), checked: VerifyError on a bad value."""
    S = dict(DEFAULTS)
    S.update({k: v for k, v in (settings or {}).items() if v is not None})
    given = settings or {}
    if given.get("planes") is not None and given.get("plane_z") is not None:
        raise VerifyError("give --planes or --plane-z, not both")

    def num(key, lo=None, hi=None, lo_open=False, integer=False):
        v = S[key]
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = float("nan")
        ok = math.isfinite(x) and (not integer or x == int(x))
        if ok and lo is not None:
            ok = x > lo if lo_open else x >= lo
        if ok and hi is not None:
            ok = x <= hi
        if not ok:
            rng = (f"above {lo}" if lo_open else f"at least {lo}") if lo is not None else ""
            rng += (" and " if rng and hi is not None else "") + (f"at most {hi}" if hi is not None else "")
            raise VerifyError(f"--{key.replace('_', '-')} must be {'a whole number ' if integer else ''}{rng} "
                              f"(got {v})")
        S[key] = int(x) if integer else x

    num("ray_step_deg", 0, 10, lo_open=True)        # at least 36 rays per plane
    if S["plane_z"] is None:
        num("planes", 1, integer=True)
    num("max_normal_um", 0, lo_open=True)
    num("coincide_um", 0)
    num("skip_frac", 0, 1, lo_open=True)
    num("tol_cells", 0, lo_open=True)
    num("upsample", 1, integer=True)
    num("min_count", 1, integer=True)                # 0 would flag a check that found nothing
    num("min_share", 0, 1)
    if S["plane_z"] is not None:
        pz = list(S["plane_z"])
        if len(pz) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in pz):
            raise VerifyError("--plane-z takes START STOP STEP")
        S["planes"] = None                            # the report then names the plane heights, not a count
    return S


def check_stack(segs, umb, voxel_um, settings=None, log=None):
    """Run the checks on segments (inner to outer). Returns (report, {name: {mask: bool grid}})."""
    np = _np()
    S = check_settings(settings)
    if len(segs) < 3:
        raise VerifyError("a stack needs at least three consecutive segments")
    vu = float(voxel_um)
    t0 = time.time()
    for s in segs:
        s.prepare(umb)
    names = [s.name for s in segs]
    n = len(segs)
    maxd, coincide = S["max_normal_um"] / vu, S["coincide_um"] / vu
    min_count, min_share = int(S["min_count"]), float(S["min_share"])
    not_checked = []          # checks that had nothing to look at: the stack is then not reported clean

    def flagged(k, total):
        return k >= min_count and total > 0 and k / total >= min_share

    masks = {s.name: {m: np.zeros(s.ok.shape, bool) for m in MASKS} for s in segs}

    # rays
    planes = plane_heights(segs, S["planes"], S["plane_z"])
    zlo, zhi = min(s.zmin for s in segs), max(s.zmax for s in segs)
    if not ((planes >= zlo) & (planes <= zhi)).any():
        raise VerifyError(f"no ray plane lies within the stack's heights, z {zlo:.0f} to {zhi:.0f}")
    cnt, rad, angles = cast_rays(segs, umb, planes, S["ray_step_deg"], log)
    step_deg = 360.0 / len(angles)
    first = rad[..., 0].astype(float)
    Z = np.broadcast_to(planes[:, None], cnt[:, 0].shape)
    A = np.broadcast_to(angles[None, :], cnt[:, 0].shape)

    # a. order on rays, and the local pitch
    pairs = []
    for k in range(n - 1):
        both = (cnt[:, k] == 1) & (cnt[:, k + 1] == 1)
        d = first[:, k + 1] - first[:, k]
        inv = both & (d < 0)
        deep = both & (d < -coincide)          # inside by more than --coincide-um: not two copies of one sheet
        close = both & (np.abs(d) <= coincide)  # within --coincide-um either way: the two cannot be told apart
        rec = {"inner": names[k], "outer": names[k + 1], "rays": int(both.sum()), "inverted_rays": int(inv.sum()),
               "inverted_share": _r(inv.sum() / max(both.sum(), 1), 4),
               "inverted_beyond_coincide_rays": int(deep.sum()),
               "inverted_beyond_coincide_share": _r(deep.sum() / max(both.sum(), 1), 4),
               "within_coincide_rays": int(close.sum()),
               "within_coincide_share": _r(close.sum() / max(both.sum(), 1), 4),
               "spacing_um_q10_25_50_75_90": _q(d[both] * vu, (10, 25, 50, 75, 90))}
        if inv.any():
            rec["inverted"] = {"z": [_r(Z[inv].min(), 0), _r(Z[inv].max(), 0)], "angle_deg": circ_range(A[inv]),
                               "rays_by_30_deg": np.histogram(A[inv], bins=12, range=(0, 360))[0].tolist(),
                               "depth_um_q25_50_75": _q(-d[inv] * vu)}
        rec["flagged"] = flagged(int(deep.sum()), int(both.sum()))
        rec["coincident_flagged"] = flagged(int(close.sum()), int(both.sum()))
        if not both.any():
            not_checked.append(f"order {names[k]}/{names[k + 1]}: no ray crosses both once")
        pairs.append(rec)
    # each pair's median spacing on its rays against the median over the pairs up to two places away (itself
    # included, so that one odd pair does not move its neighbours' reference)
    ray_med = []
    for k, p in enumerate(pairs):
        both = (cnt[:, k] == 1) & (cnt[:, k + 1] == 1)
        ray_med.append(float(np.median(first[:, k + 1][both] - first[:, k][both])) if both.any() else float("nan"))
    for k, p in enumerate(pairs):
        near_pairs = [v for v in ray_med[max(0, k - 2):k + 3] if math.isfinite(v)]
        ref = float(np.median(near_pairs)) if len(near_pairs) >= 2 else float("nan")
        ratio = ray_med[k] / ref if math.isfinite(ray_med[k]) and math.isfinite(ref) and ref > 0 else float("nan")
        p["spacing_against_nearby_pairs"] = _r(ratio, 3)
        p["spacing_flagged"] = bool(math.isfinite(ratio) and not PAIR_SPACING[0] <= ratio <= PAIR_SPACING[1])
        if p["rays"] and len(near_pairs) < 2:
            not_checked.append(f"pair spacing {p['inner']}/{p['outer']}: no other pair nearby to compare with")

    # neighbours along the normal
    table = neighbour_table(segs, umb, int(S["upsample"]), maxd, float(S["tol_cells"]), log)
    for s, tb in zip(segs, table):
        near = np.fmin(tb["out_d"], tb["in_d"])
        masks[s.name]["coincident"] = s.ok & (near <= coincide)
        found = s.ok & ((tb["out_j"] >= 0) | (tb["in_j"] >= 0))
        if found.sum() < 0.5 * s.n:
            not_checked.append(f"vertex checks {s.name}: a neighbour along the normal for only "
                               f"{100 * found.sum() / max(s.n, 1):.0f} % of its vertices")

    # d. turn overlaps (first: order conflicts leave the overlap masks out)
    overlaps, own_end = [], {}

    def med_adj(k, j, mask):
        """Median distance along the normal from segment k's vertices in mask to adjacent segment j (NaN if none)."""
        d = table[k]["adj"].get(j)
        if d is None or not mask.any():
            return float("nan")
        v = d[mask]
        v = v[np.isfinite(v)]
        return float(np.median(v)) if len(v) else float("nan")

    def ratio(a, b):
        return a / b if math.isfinite(a) and math.isfinite(b) and b > 0 else float("nan")

    for k, s in enumerate(segs):
        spans, past, outer_p, inner_p, end = turn_overlap(s)
        rest = s.ok & ~outer_p & ~inner_p
        # each piece against the rest of the segment: a piece on a neighbour's sheet lies much closer to it
        r_out = ratio(med_adj(k, k + 1, outer_p), med_adj(k, k + 1, rest)) if k + 1 < n else float("nan")
        r_in = ratio(med_adj(k, k - 1, inner_p), med_adj(k, k - 1, rest)) if k >= 1 else float("nan")
        # the far piece, as a rule (the turn ran on onto the next winding's sheet); the near piece when it lies on
        # the previous winding's sheet where no doubly traced end of the previous segment is marked already (with
        # seams in line, every near piece has the previous segment's far piece on it, which is handled there)
        covered = (masks[s.name]["turn_overlap"] & inner_p).sum() / max(inner_p.sum(), 1)
        use_inner = (math.isfinite(r_in) and r_in < 0.5 and covered < 0.5
                     and not (math.isfinite(r_out) and r_out <= r_in))
        chosen = inner_p if use_inner else outer_p
        j = k - 1 if use_inner else k + 1
        masks[s.name]["turn_overlap"] |= chosen
        own_end[s.name] = chosen
        dte = {"end_of_turn": (("start" if end == "end" else "end") if use_inner else end),
               "piece": "inner" if use_inner else "outer"}
        if chosen.any():
            dte.update({"outer_piece_to_next_against_rest": _r(r_out, 3),
                        "inner_piece_to_previous_against_rest": _r(r_in, 3),
                        "inner_piece_on_previous_segments_mask_share": _r(covered, 3)})
        rec = {"segment": s.name, "lines": int(len(spans)),
               "turn_deg_per_line_q10_50_90": _q(spans, (10, 50, 90)) if len(spans) else None,
               "turn_deg_per_line_max": _r(spans.max()) if len(spans) else None,
               "lines_past_full_turn": int(len(past)),
               "past_full_turn_deg_q10_25_50_75_90": _q(past, (10, 25, 50, 75, 90)) if len(past) else None,
               "past_full_turn_deg_max": _r(past.max()) if len(past) else None,
               "doubly_traced_end": {**dte, **_describe(s, chosen, vu)}}
        if 0 <= j < n and chosen.any():
            nx = segs[j]
            tol = float(S["tol_cells"]) * s.step
            st = _sector_tree(s.xyz[chosen][:, 2], s.theta[chosen], s.rmed, tol)
            hit = np.zeros(nx.ok.shape, bool)
            hit[nx.ok] = _within(st, nx.xyz[nx.ok][:, 2], nx.theta[nx.ok], s.rmed, tol)
            masks[nx.name]["turn_overlap"] |= hit
            dn = table[k]["adj"].get(j, np.full(s.ok.shape, np.nan))[chosen]
            fin = dn[np.isfinite(dn)]
            far = fin[fin > coincide]
            rec["neighbour"] = {"segment": nx.name, "side": "inner" if use_inner else "outer",
                                "matched_share": _r(np.isfinite(dn).mean(), 3),
                                "distance_um_q5_25_50_75_95": _q(fin * vu, (5, 25, 50, 75, 95)) if len(fin) else None,
                                "within_coincide_share": _r((fin <= coincide).mean(), 3) if len(fin) else None,
                                "beyond_coincide_share": _r((fin > coincide).mean(), 3) if len(fin) else None,
                                "beyond_coincide_median_um": _r(np.median(far) * vu) if len(far) else None,
                                "vertices_at_same_height_and_angle": int(hit.sum())}
        rec["flagged"] = flagged(int(chosen.sum()), s.n)
        overlaps.append(rec)

    # the local pitch: spacing of adjacent segments along the vertex normals (both ways, outside the turn-overlap
    # masks), the median over the two pairs either side of a segment
    pair_med = []
    for k in range(n - 1):
        a, b = segs[k], segs[k + 1]
        da = table[k]["adj"].get(k + 1, np.full(a.ok.shape, np.nan))[a.ok & ~masks[a.name]["turn_overlap"]]
        db = table[k + 1]["adj"].get(k, np.full(b.ok.shape, np.nan))[b.ok & ~masks[b.name]["turn_overlap"]]
        dd = np.concatenate([da, db])
        dd = dd[np.isfinite(dd)]
        pair_med.append(float(np.median(dd)) if len(dd) >= min_count else float("nan"))
        pairs[k]["normal_spacing_um_q25_50_75"] = _q(dd * vu) if len(dd) else None
    pair_med = np.array(pair_med)
    good = pair_med[np.isfinite(pair_med) & (pair_med > 0)]
    overall = float(np.median(good)) if len(good) else float("nan")
    pitch = []
    for k in range(n):
        w = pair_med[max(0, k - 2):min(n - 1, k + 2)]
        w = w[np.isfinite(w) & (w > 0)]
        pitch.append(float(np.median(w)) if len(w) else overall)

    # a. order, per vertex
    order_v = []
    for k, (s, tb) in enumerate(zip(segs, table)):
        keep = s.ok & ~masks[s.name]["coincident"] & ~masks[s.name]["turn_overlap"]
        if keep.sum() < 0.5 * s.n:
            not_checked.append(f"order per vertex {s.name}: only {100 * keep.sum() / max(s.n, 1):.0f} % of its "
                               f"vertices are neither coincident nor on a turn-overlap mask")
        outer_low = keep & (tb["out_j"] >= 0) & (tb["out_j"] < k)
        inner_high = keep & (tb["in_j"] > k)
        conf = outer_low | inner_high
        masks[s.name]["order"] = conf
        rec = {"segment": s.name, **_describe(s, conf, vu), "groups": []}
        for side, m, J, Dd in (("outer", outer_low, tb["out_j"], tb["out_d"]),
                               ("inner", inner_high, tb["in_j"], tb["in_d"])):
            for j in np.unique(J[m]):
                g = m & (J == j)
                rec["groups"].append({"side": side, "neighbour": names[int(j)], **_describe(s, g, vu),
                                      "distance_um_q25_50_75": _q(Dd[g] * vu)})
        rec["groups"].sort(key=lambda g: -g["vertices"])
        if conf.any():
            rec["examples"] = _examples(s, conf, lambda r, c, tb=tb, k=k: _side(tb, r, c, k, names, vu))
        rec["flagged"] = flagged(int(conf.sum()), s.n)
        order_v.append(rec)

    # b. missing sectors
    present = cnt >= 1
    once = cnt == 1
    bands = [b for b in np.array_split(np.arange(len(planes)), min(10, len(planes))) if len(b)]
    missing = []
    for k in range(1, n - 1):
        s = segs[k]
        inz = (Z >= s.zmin) & (Z <= s.zmax)
        loose = present[:, k - 1] & present[:, k + 1]
        gap_l = loose & ~present[:, k]
        gap_o = once[:, k - 1] & once[:, k + 1] & inz      # rays for spacing: each neighbour crossed once
        d = first[:, k + 1] - first[:, k - 1]
        lab = f"{names[k - 1]} to {names[k + 1]}"
        rec = {"segment": s.name, "neighbours": [names[k - 1], names[k + 1]],
               "rays_with_both_neighbours": int((loose & inz).sum()), "gap_rays": int((gap_l & inz).sum()),
               "gap_share": _r((gap_l & inz).sum() / max((loose & inz).sum(), 1), 4),
               "gap_rays_outside_own_height": int((gap_l & ~inz).sum()),
               "neighbour_spacing": {"gap": _spacing(d[gap_o & ~present[:, k]], vu),
                                     "present": _spacing(d[gap_o & present[:, k]], vu)}}
        if not (loose & inz).any():
            not_checked.append(f"missing sectors {s.name}: no ray at its heights crosses both neighbours")
        if k >= 2 and k + 2 < n:
            o2 = gap_o & once[:, k - 2] & once[:, k + 2]
            d2 = first[:, k + 2] - first[:, k - 2]
            rec["outer_pair_spacing"] = {"pair": [names[k - 2], names[k + 2]],
                                         "gap": _spacing(d2[o2 & ~present[:, k]], vu),
                                         "present": _spacing(d2[o2 & present[:, k]], vu)}
        # by height: the neighbours' spacing in the gap, and where the outer neighbour lies against the next inner
        # segment as well
        g = gap_o & ~present[:, k]
        if g.any():
            by = []
            for b in bands:
                gb = g & np.isin(np.arange(len(planes)), b)[:, None]
                if not gb.any():
                    continue
                row = {"z": [_r(planes[b[0]], 0), _r(planes[b[-1]], 0)], "rays": int(gb.sum()),
                       "median_um": {lab: _r(np.median(d[gb]) * vu)},
                       "inside_share": _r((d[gb] < 0).mean(), 3)}
                if k >= 2:
                    g2 = gb & once[:, k - 2]
                    if g2.any():
                        row["median_um"][f"{names[k - 2]} to {names[k - 1]}"] = _r(
                            np.median(first[:, k - 1][g2] - first[:, k - 2][g2]) * vu)
                        row["median_um"][f"{names[k - 2]} to {names[k + 1]}"] = _r(
                            np.median(first[:, k + 1][g2] - first[:, k - 2][g2]) * vu)
                by.append(row)
            rec["gap_by_height"] = by
            # control: pairs the same number of windings apart as the outer pair, both inner or both outer of the
            # segment, on the gap's rays against the rays at its heights where it is present
            ctrl = []
            for a in [a for a in range(n - 4) if a + 4 <= k - 1 or a >= k + 1]:
                oc = once[:, a] & once[:, a + 4] & inz & loose
                dc = first[:, a + 4] - first[:, a]
                ctrl.append({"pair": [names[a], names[a + 4]], "gap": _spacing(dc[oc & ~present[:, k]], vu),
                             "present": _spacing(dc[oc & present[:, k]], vu)})
            if ctrl:
                rec["control_pairs"] = ctrl
        runs = []
        for i, z0 in enumerate(planes):
            if not (s.zmin <= z0 <= s.zmax):
                continue
            rr = [(a, b, (b - a) % len(angles) + 1) for a, b in circular_runs(gap_l[i]) if (b - a) % len(angles) + 1 >= 3]
            if rr:
                a, b, w = max(rr, key=lambda x: x[2])
                runs.append({"plane": i, "z": _r(z0, 0), "start_deg": _r(angles[a]), "end_deg": _r(angles[b]),
                             "width_deg": _r((w - 1) * step_deg)})
        main = main_sector(runs)
        if main:
            wd = np.array([r["width_deg"] for r in main])
            rec["gap_extent"] = {"planes_with_a_gap": len(runs), "planes": len(main), "z": [main[0]["z"], main[-1]["z"]],
                                 "start_deg": circ_range([r["start_deg"] for r in main]),
                                 "end_deg": circ_range([r["end_deg"] for r in main]),
                                 "start_deg_q10_50_90": circ_quantiles([r["start_deg"] for r in main]),
                                 "end_deg_q10_50_90": circ_quantiles([r["end_deg"] for r in main]),
                                 "width_deg_min_median_max": [_r(wd.min()), _r(np.median(wd)), _r(wd.max())]}
        verts = {}
        for m, other in ((segs[k - 1], segs[k + 1]), (segs[k + 1], segs[k - 1])):
            sm = sector_mask(m, s, other, float(S["tol_cells"]))
            masks[m.name]["missing_sector"] |= sm
            v = _describe(m, sm, vu)
            if sm.any():
                v["in_turn_overlap_share"] = _r((sm & masks[m.name]["turn_overlap"]).sum() / sm.sum(), 3)
                j = names.index(m.name)
                v["examples"] = _examples(m, sm & ~masks[m.name]["turn_overlap"] if (sm & ~masks[m.name]["turn_overlap"]).any()
                                          else sm, lambda r, c, tb=table[j], j=j: _side(tb, r, c, j, names, vu))
            verts[m.name] = v
        rec["neighbour_vertices"] = verts
        rec["flagged"] = flagged(int((gap_l & inz).sum()), int((loose & inz).sum()))
        if rec["flagged"]:
            rec["per_plane"] = runs
        missing.append(rec)

    # b2. missing runs: two or more adjacent windings with no segment on a ray while the windings either side have
    # one, at heights within the z extent of at least one of them (heights beyond all of them are stack ends)
    npres = np.concatenate([np.zeros(present[:, :1].shape, int), np.cumsum(present, axis=1)], axis=1)
    missing_runs = []
    for i in range(n - 3):
        for j in range(i + 3, n):
            hole = present[:, i] & present[:, j] & (npres[:, j] - npres[:, i + 1] == 0)
            if not hole.any():
                continue
            mid = segs[i + 1:j]
            inz = np.zeros(hole.shape, bool)
            for m in mid:
                inz |= (Z >= m.zmin) & (Z <= m.zmax)
            g = hole & inz
            both = present[:, i] & present[:, j] & inz
            rec = {"between": [names[i], names[j]], "missing": [m.name for m in mid], "rays": int(g.sum()),
                   "rays_with_both": int(both.sum()), "share": _r(g.sum() / max(both.sum(), 1), 4),
                   "rays_beyond_their_heights": int((hole & ~inz).sum())}
            if g.any():
                oo = once[:, i] & once[:, j]
                dd = first[:, j] - first[:, i]
                allp = (npres[:, j] - npres[:, i + 1]) == (j - i - 1)
                rec.update({"z": [_r(Z[g].min(), 0), _r(Z[g].max(), 0)], "angle_deg": circ_range(A[g]),
                            "planes": int(g.any(1).sum()),
                            "spacing": {"hole": _spacing(dd[g & oo], vu), "all_present": _spacing(dd[both & oo & allp], vu)},
                            "per_plane": [{"z": _r(planes[p], 0), "rays": int(g[p].sum()), "angle_deg": circ_range(A[p][g[p]])}
                                          for p in np.flatnonzero(g.any(1))]})
                verts = {}
                for m, other in ((segs[i], segs[j]), (segs[j], segs[i])):
                    sm = sector_mask(m, mid, other, float(S["tol_cells"]))
                    masks[m.name]["missing_sector"] |= sm
                    verts[m.name] = _describe(m, sm, vu)
                    if sm.any():
                        jm = names.index(m.name)
                        verts[m.name]["examples"] = _examples(
                            m, sm, lambda r, c, tb=table[jm], jm=jm: _side(tb, r, c, jm, names, vu))
                rec["bounding_vertices"] = verts
            rec["flagged"] = flagged(int(g.sum()), int(both.sum()))
            missing_runs.append(rec)

    # c. skipped windings
    skips = []
    for k, (s, tb) in enumerate(zip(segs, table)):
        lim = float(S["skip_frac"]) * pitch[k]
        out_a = s.ok & (tb["out_j"] >= k + 2) & (tb["out_d"] < lim)
        in_a = s.ok & (tb["in_j"] >= 0) & (tb["in_j"] <= k - 2) & (tb["in_d"] < lim)
        ov = own_end[s.name]           # the segment's own doubly traced end carries its winding one turn out or in
        out_s, in_s = out_a & ~ov, in_a & ~ov
        sk = out_s | in_s
        masks[s.name]["skipped_winding"] = sk
        dist = np.where(out_s, tb["out_d"], tb["in_d"])
        beyond = sk & (dist > coincide)
        rec = {"segment": s.name, "local_pitch_um": _r(pitch[k] * vu), "limit_um": _r(lim * vu),
               **_describe(s, sk, vu), "distance_um_q25_50_75": _q(dist[sk] * vu),
               "beyond_coincide": {"vertices": int(beyond.sum()), "area_cm2": _r(s.area[beyond].sum() * (vu * 1e-4) ** 2, 3),
                                   "distance_um_q25_50_75": _q(dist[beyond] * vu)},
               "on_own_doubly_traced_end_left_out": int(((out_a | in_a) & ov).sum()), "groups": []}
        for side, m, J in (("outer", out_s, tb["out_j"]), ("inner", in_s, tb["in_j"])):
            for j in np.unique(J[m]):
                g = m & (J == j)
                rec["groups"].append({"side": side, "neighbour": names[int(j)], "vertices": int(g.sum()),
                                      "beyond_coincide": int((g & beyond).sum()),
                                      "beyond_coincide_area_cm2": _r(s.area[g & beyond].sum() * (vu * 1e-4) ** 2, 3),
                                      "beyond_coincide_distance_um_q25_50_75": _q(dist[g & beyond] * vu)})
        off = beyond & ~masks[s.name]["turn_overlap"]
        rec["beyond_coincide_off_turn_overlap"] = {"vertices": int(off.sum()),
                                                   "area_cm2": _r(s.area[off].sum() * (vu * 1e-4) ** 2, 3)}
        if sk.any():
            rec["in_missing_sector_share"] = _r((sk & masks[s.name]["missing_sector"]).sum() / sk.sum(), 3)
            rec["in_turn_overlap_share"] = _r((sk & masks[s.name]["turn_overlap"]).sum() / sk.sum(), 3)
            rec["examples"] = _examples(s, beyond if beyond.any() else sk,
                                        lambda r, c, tb=tb, k=k: _side(tb, r, c, k, names, vu))
        rec["flagged"] = flagged(int(sk.sum()), s.n)
        skips.append(rec)

    # e. stack ends
    ends = []
    for k in range(1, n - 1):
        s = segs[k]
        tolz = float(S["tol_cells"]) * s.step
        rec = {"segment": s.name, "z": [_r(s.zmin, 0), _r(s.zmax, 0)]}
        inner = [j for j in range(k) if segs[j].zmin < s.zmin - tolz]
        outer = [j for j in range(k + 1, n) if segs[j].zmin < s.zmin - tolz]
        bands = []
        if inner and outer:
            i, o = max(inner), min(outer)
            zb = (max(segs[i].zmin, segs[o].zmin), s.zmin)
            rec["missing_below"] = {"z": [_r(zb[0], 0), _r(zb[1], 0)],
                                    "between": [names[i], names[o]], "windings_without_segment": o - i - 1}
            bands.append((i, o, zb))
        inner = [j for j in range(k) if segs[j].zmax > s.zmax + tolz]
        outer = [j for j in range(k + 1, n) if segs[j].zmax > s.zmax + tolz]
        if inner and outer:
            i, o = max(inner), min(outer)
            za = (s.zmax, min(segs[i].zmax, segs[o].zmax))
            rec["missing_above"] = {"z": [_r(za[0], 0), _r(za[1], 0)],
                                    "between": [names[i], names[o]], "windings_without_segment": o - i - 1}
            bands.append((i, o, za))
        rec["flagged"] = any(
            key in rec and rec[key]["z"][1] - rec[key]["z"][0] > tolz for key in ("missing_below", "missing_above"))
        for i, o, (lo, hi) in bands:          # the segments either side, at the heights where this one has none
            if hi - lo <= tolz:
                continue
            for j in (i, o):
                zj = segs[j].xyz[..., 2]
                masks[names[j]]["stack_end"] |= segs[j].ok & (zj >= lo) & (zj <= hi)
        ends.append(rec)

    for s in segs:
        m = masks[s.name]
        m["any"] = np.zeros(s.ok.shape, bool)
        for key in MASKS:
            m["any"] |= m[key]

    flags = {"order": [f"{p['inner']}/{p['outer']}" for p in pairs if p["flagged"]],
             "order_vertices": [r["segment"] for r in order_v if r["flagged"]],
             "coincident_pairs": [f"{p['inner']}/{p['outer']}" for p in pairs if p["coincident_flagged"]],
             "pair_spacing": [f"{p['inner']}/{p['outer']}" for p in pairs if p["spacing_flagged"]],
             "missing_sectors": [r["segment"] for r in missing if r["flagged"]],
             "missing_runs": [f"{r['between'][0]}/{r['between'][1]}" for r in missing_runs if r["flagged"]],
             "skipped_windings": [r["segment"] for r in skips if r["flagged"]],
             "turn_overlaps": [r["segment"] for r in overlaps if r["flagged"]],
             "stack_ends": [r["segment"] for r in ends if r["flagged"]]}
    report = {
        "tool": "kit stackcheck", "version": 1, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "frame": {"positions": "tifxyz values, voxels of the umbilicus's volume", "voxel_um": vu,
                  "angles": "degrees about the umbilicus at the same z, atan2(y - y_u, x - x_u), 0 to 360",
                  "distances": "micrometres, radial along rays from the umbilicus or along vertex normals",
                  "rows_cols": "examples' row and col are on each segment's input grid"},
        "umbilicus": umb.source,
        "settings": {**{k: (list(v) if isinstance(v, tuple) else v) for k, v in S.items()},
                     "pair_spacing_ratio": list(PAIR_SPACING)},
        "rays": {"planes": len(planes), "z": [_r(planes[0], 0), _r(planes[-1], 0)], "rays_per_plane": len(angles),
                 "ray_step_deg": _r(step_deg, 6)},
        "segments": [{"name": s.name, "path": s.path, "input_grid": list(s.input_shape), "stride": s.stride,
                      "vertices": s.n, "area_cm2": _r(s.area[s.ok].sum() * (vu * 1e-4) ** 2, 2),
                      "z": [_r(s.zmin, 0), _r(s.zmax, 0)], "median_radius_um": _r(s.rmed * vu, 0),
                      "grid_step_um": _r(s.step * vu), "local_pitch_um": _r(pitch[k] * vu)}
                     for k, s in enumerate(segs)],
        "summary": {"clean": not any(flags.values()) and not not_checked, "flagged": flags,
                    "not_checked": not_checked,
                    "not_covered": [f"missing sectors of {names[0]} and {names[-1]}: the innermost and outermost "
                                    f"segments have a neighbour on one side only",
                                    f"missing runs that include {names[0]} or {names[-1]}"]},
        "order": {"pairs": pairs, "vertices": order_v},
        "missing_sectors": missing, "missing_runs": missing_runs, "skipped_windings": skips,
        "turn_overlaps": overlaps, "stack_ends": ends,
        "seconds": _r(time.time() - t0),
    }
    return report, masks


def _side(tb, r, c, k, names, vu):
    out = {}
    for side, J, D in (("outer", tb["out_j"], tb["out_d"]), ("inner", tb["in_j"], tb["in_d"])):
        j = int(J[r, c])
        if j >= 0:
            out[f"nearest_{side}"] = {"segment": names[j], "distance_um": _r(D[r, c] * vu)}
    return out


# ---------------------------------------------------------------- output

def write_flags(path, segs, masks, voxel_um):
    """One boolean mask per segment and check on the segment's input grid (a strided vertex's flag covers the
    stride x stride block starting at it). Returns the path written, with .npz added when it lacks it."""
    np = _np()
    out = {"names": np.array([s.name for s in segs]), "voxel_um": np.float64(voxel_um)}
    for s in segs:
        H, W = s.input_shape
        for key, m in masks[s.name].items():
            full = np.repeat(np.repeat(m, s.stride, 0), s.stride, 1)[:H, :W] if s.stride > 1 else m
            out[f"{s.name}/{key}"] = full
    path = Path(path)
    if path.suffix != ".npz":
        path = path.with_name(path.name + ".npz")      # numpy would add it anyway: name the file actually written
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **out)
    return str(path)


def format_report(rep):
    L = []
    f = rep["frame"]
    L.append(f"kit stackcheck: {len(rep['segments'])} segments, voxel {f['voxel_um']} um; "
             f"{rep['rays']['planes']} planes z {rep['rays']['z'][0]} to {rep['rays']['z'][1]}, "
             f"{rep['rays']['rays_per_plane']} rays each")
    for s in rep["segments"]:
        L.append(f"  {s['name']}: {s['vertices']} vertices, {s['area_cm2']} cm2, z {s['z'][0]} to {s['z'][1]}, "
                 f"radius {s['median_radius_um']} um, local pitch {s['local_pitch_um']} um")
    L.append("a. order (rays crossing both once; inner outside outer)")
    for p in rep["order"]["pairs"]:
        mark = "  FLAG" if p["flagged"] else ""
        sp = p["spacing_um_q10_25_50_75_90"]
        L.append(f"  {p['inner']}/{p['outer']}: {p['inverted_rays']} of {p['rays']} rays inverted "
                 f"({100 * (p['inverted_share'] or 0):.1f} %; {100 * (p['inverted_beyond_coincide_share'] or 0):.1f} % "
                 f"by more than {rep['settings']['coincide_um']} um), spacing median {sp[2] if sp else None} um{mark}")
    for r in rep["order"]["vertices"]:
        if r["vertices"]:
            top = r["groups"][0]
            L.append(f"  {r['segment']}: {r['vertices']} vertices out of order ({r['area_cm2']} cm2), most with "
                     f"{top['neighbour']} on the {top['side']} side{'  FLAG' if r['flagged'] else ''}")
    L.append("a2. pair spacing (rays crossing both once; within --coincide-um, and median against nearby pairs)")
    for p in rep["order"]["pairs"]:
        mark = "".join(f"  FLAG {w}" for w, f in (("coincident", p["coincident_flagged"]),
                                                   ("spacing", p["spacing_flagged"])) if f)
        L.append(f"  {p['inner']}/{p['outer']}: within {rep['settings']['coincide_um']} um on "
                 f"{100 * (p['within_coincide_share'] or 0):.1f} % of rays; median "
                 f"{p['spacing_against_nearby_pairs']} times the nearby pairs'{mark}")
    L.append("b. missing sectors (neighbours crossed, segment not)")
    for r in rep["missing_sectors"]:
        if not r["gap_rays"] and not r["gap_rays_outside_own_height"]:
            continue
        g, p = r["neighbour_spacing"]["gap"], r["neighbour_spacing"]["present"]
        ext = r.get("gap_extent")
        L.append(f"  {r['segment']}: {r['gap_rays']} gap rays ({100 * (r['gap_share'] or 0):.1f} %) in its height, "
                 f"{r['gap_rays_outside_own_height']} beyond it; {r['neighbours'][0]} to {r['neighbours'][1]} median "
                 f"{g.get('median_um')} um in the gap vs {p.get('median_um')} um elsewhere"
                 + (f"; gap z {ext['z'][0]} to {ext['z'][1]}, starts {ext['start_deg_q10_50_90'][0]} to "
                    f"{ext['start_deg_q10_50_90'][2]} and ends {ext['end_deg_q10_50_90'][0]} to "
                    f"{ext['end_deg_q10_50_90'][2]} deg (10th to 90th percentile)" if ext else "")
                 + ("  FLAG" if r["flagged"] else ""))
    L.append("b2. missing runs (two or more adjacent windings not crossed, the windings either side crossed)")
    for r in rep.get("missing_runs", []):
        if r["rays"]:
            h = r["spacing"]["hole"]
            L.append(f"  {r['between'][0]} to {r['between'][1]} ({', '.join(r['missing'])} missing): {r['rays']} rays "
                     f"({100 * (r['share'] or 0):.1f} %), z {r['z'][0]} to {r['z'][1]}, angle {r['angle_deg'][0]} to "
                     f"{r['angle_deg'][1]} deg; spacing median {h.get('median_um')} um there vs "
                     f"{r['spacing']['all_present'].get('median_um')} um with all present"
                     + ("  FLAG" if r["flagged"] else ""))
    L.append("c. skipped windings (nearest along the normal two or more windings away, under half a pitch)")
    for r in rep["skipped_windings"]:
        if r["vertices"]:
            L.append(f"  {r['segment']}: {r['vertices']} vertices ({r['area_cm2']} cm2), median "
                     f"{(r['distance_um_q25_50_75'] or [None] * 3)[1]} um, limit {r['limit_um']} um"
                     f"{'  FLAG' if r['flagged'] else ''}")
    L.append("d. turn overlaps (angle past a full turn per grid line)")
    for r in rep["turn_overlaps"]:
        if r["lines_past_full_turn"]:
            q = r["past_full_turn_deg_q10_25_50_75_90"]
            nx = r.get("neighbour") or {}
            dq = nx.get("distance_um_q5_25_50_75_95")
            L.append(f"  {r['segment']}: {r['lines_past_full_turn']} of {r['lines']} lines, median {q[2]} deg past; "
                     f"doubly traced end ({r['doubly_traced_end']['piece']} piece) at "
                     f"{(r['doubly_traced_end'].get('angle_deg') or [None])[:2]} deg"
                     + (f", median {dq[2]} um from {nx['segment']}" if dq else "")
                     + ("  FLAG" if r["flagged"] else ""))
    L.append("e. stack ends (a winding between traced ones has no segment)")
    for r in rep["stack_ends"]:
        for key in ("missing_below", "missing_above"):
            if key in r:
                m = r[key]
                L.append(f"  {r['segment']} (z {r['z'][0]} to {r['z'][1]}): none from z {m['z'][0]} to {m['z'][1]} "
                         f"between {m['between'][0]} and {m['between'][1]}{'  FLAG' if r['flagged'] else ''}")
    fl = {k: v for k, v in rep["summary"]["flagged"].items() if v}
    for msg in rep["summary"].get("not_checked", []):
        L.append(f"not checked: {msg}")
    for msg in rep["summary"].get("not_covered", []):
        L.append(f"not covered by any check: {msg}")
    if rep["summary"]["clean"]:
        L.append("clean: every check looked and none flagged (see 'not covered' above)")
    elif fl:
        L.append(f"flagged: {json.dumps(fl)}")
    else:
        L.append("not clean: nothing flagged, but some checks had nothing to look at")
    return "\n".join(L)


def transform_volumes(spec):
    """(from, to) volume ids a --transform names: catalog:SAMPLE:FROM:TO, or a matrix JSON object's
    "from_volume_id" and "to_volume_id" when it has them; (None, None) otherwise."""
    if spec is None:
        return None, None
    if str(spec).startswith("catalog:"):
        bits = str(spec).split(":")
        return (bits[2], bits[3]) if len(bits) == 4 else (None, None)
    try:
        data = json.loads(Path(spec).read_text())
    except (OSError, ValueError):
        return None, None
    return (data.get("from_volume_id"), data.get("to_volume_id")) if isinstance(data, dict) else (None, None)


def check_frame(paths, umb, transform):
    """VerifyError when the segments' folder names, the transform and the umbilicus disagree about volumes."""
    vols = {folder_volume(p) for p in paths} - {None}
    sizes = {folder_voxel_um(p) for p in paths} - {None}
    if len(vols) > 1:
        raise VerifyError(f"the segments are on different volumes {sorted(vols)}; give copies on one volume")
    if len(sizes) > 1:
        raise VerifyError(f"the segments' folder names give different voxel sizes {sorted(sizes)} um")
    seg_vol = next(iter(vols)) if vols else None
    umb_vol = umbilicus_volume(umb)
    t_from, t_to = transform_volumes(transform)
    if transform is None:
        if seg_vol and umb_vol and seg_vol != umb_vol:
            raise VerifyError(f"the segments are on volume {seg_vol} and the umbilicus on {umb_vol}: map the "
                              f"segments with --transform")
        return
    if seg_vol and umb_vol and seg_vol == umb_vol:
        raise VerifyError(f"the segments are already on the umbilicus's volume {umb_vol}: leave out --transform")
    if t_from and seg_vol and t_from != seg_vol:
        raise VerifyError(f"the transform starts on volume {t_from} but the segments are on {seg_vol}")
    if t_to and umb_vol and t_to != umb_vol:
        raise VerifyError(f"the transform ends on volume {t_to} but the umbilicus is on {umb_vol}")


def run(specs, umbilicus, transform=None, catalog=None, voxel_um=None, stride=1, cache="work/stackcheck/cache",
        settings=None, log=None):
    """Load, check and return (report, segments, masks)."""
    if int(stride) < 1:
        raise VerifyError("--stride must be 1 or more")
    if voxel_um is not None and not (math.isfinite(float(voxel_um)) and float(voxel_um) > 0):
        raise VerifyError("--voxel-um must be above 0")
    check_settings(settings)
    umb = load_umbilicus(umbilicus)
    paths = [split_spec(s)[1] for s in specs]
    check_frame(paths, umb, transform)
    M = load_transform(transform, catalog)
    seg_um = {folder_voxel_um(p) for p in paths} - {None}
    if M is None and umb.voxel_um and seg_um and any(abs(v / umb.voxel_um - 1) > 0.01 for v in seg_um):
        raise VerifyError(f"the segments are in a {sorted(seg_um)} um volume and the umbilicus in a "
                          f"{umb.voxel_um} um one: map the segments with --transform")
    if voxel_um is not None and umb.voxel_um and abs(float(voxel_um) / umb.voxel_um - 1) > 0.01:
        raise VerifyError(f"--voxel-um {voxel_um} differs from the umbilicus's metadata.voxelsize_um {umb.voxel_um}")
    if voxel_um is not None and M is None and seg_um and any(abs(v / float(voxel_um) - 1) > 0.01 for v in seg_um):
        raise VerifyError(f"--voxel-um {voxel_um} differs from the segments' folder names ({sorted(seg_um)} um): "
                          f"map the segments with --transform")
    vu = voxel_um or umb.voxel_um or (min(seg_um) if M is None and len(seg_um) == 1 else None)
    if not vu:
        raise VerifyError("give --voxel-um: the umbilicus has no metadata.voxelsize_um")
    segs = load_segments(specs, M, int(stride), cache, log)
    report, masks = check_stack(segs, umb, vu, settings, log)
    report["settings"]["stride"] = int(stride)
    report["transform"] = M.round(9).tolist() if M is not None else None
    report["frame"]["voxel_um_from"] = ("--voxel-um" if voxel_um else "umbilicus metadata" if umb.voxel_um
                                        else "segment folder name")
    report["frame"]["volumes"] = {"segments": folder_volume(paths[0]) if paths else None,
                                  "umbilicus": umbilicus_volume(umb)}
    return report, segs, masks
