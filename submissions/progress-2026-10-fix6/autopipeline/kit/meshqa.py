"""Mesh and prediction checks: VC3D-exact tifxyz validity and bbox, winding audit, garbage prediction cubes.

  kit meshqa validity PATH...  which vertices VC3D's loader keeps, the bbox it would derive against the one
                               stored in meta.json, the other sidecar checks of tifxyz-repair, and how many
                               vertices the private trim rule of kit/vc3d_prep.py classifies differently.
                               --fix OUT writes a corrected copy, never in place.
  kit meshqa windaudit SURF    edges of a tifxyz mesh whose winding coordinate w = r / pitch - theta / (2 pi)
                               about the umbilicus jumps by about one turn across one edge (a radial short circuit
                               between neighbouring wraps, the signature of a sheet switch), the component table,
                               split contacts and, opt in, broad fusions.
  kit meshqa predcubes VOL     surface-prediction cubes that are solid slabs or empty, on a local or remote zarr
                               region (kit.vc3d_region.Volume), or on a .npy or .tif cube.
  kit meshqa support SURF PRED share of a tifxyz's vertices on its surface prediction beside the same share for
                               random points in its neighbourhood (villa PR #1906's acceptance check, written
                               here from its description) and, with --shift, for the surface moved along its
                               normal. Report only; --strict exits 3 on a warning.
  kit meshqa crop SURF OUT     cut a trace's transverse self-crossings, unseated windows and off-sheet blobs and
                               write every piece left above a minimum area as its own VC3D tifxyz folder; see
                               kit/regioncrop.py.
  kit meshqa certify SURF      the cells no check faults (holes, folds onto the next winding, crossings with other
                               surfaces, rival traces adjudicated, steep clusters against the prediction), the
                               largest certified square in mm, and a fibre score of the raw scan along the sheet;
                               after Pellerano's PHerc. 0826 chain article, see kit/certify.py.

Coordinates are tifxyz (x, y, z) in level-0 voxels of the volume the mesh was traced on; zarr arrays are (z, y, x).
Needs numpy (imported when a check runs, so `python -m kit meshqa --help` works without it); tifffile is used when
present, else kit/vc3d_io's standard-library TIFF reader. A flagged edge or cube is a place to inspect, never a
reading and never evidence about ink.

validity
--------
Ported from tifxyz-repair (https://github.com/Nieuwlaar/tifxyz-repair, commit
4d6c98d95b71aa94dfed9398fbfe592419e62763, src/tifxyz_repair/core.py, checks.py, repair.py), under the MIT License
reproduced below. Sourced fact (villa volume-cartographer/core/src/QuadSurface.cpp, load_quad_from_tifxyz_impl and
QuadSurface::bbox(), read at villa commit a329895ea5e9bde78752e60dbc0a4878dd2ab909 of 2026-10-08): the loader reads
x, y and z as float32 (static_cast<float> of 8, 16 and 32-bit integers and of 32 and 64-bit floats), sets a vertex to
(-1, -1, -1) when z <= 0 ("Invalidate by z<=0"; NaN <= 0 is false, so a NaN z stays valid); then, unless told to
ignore it, reads channel 0 of the first directory of mask.tif and invalidates the vertex under every mask pixel whose
value is below 255 (8, 16 and 32-bit integers, 32 and 64-bit floats; any other sample type is judged by its first
byte, (*p) >= 255); a mask whose width and height are each the grid's or an integer multiple of it maps pixel
(sx, sy) to vertex (sx / scale, sy / scale), so one failing pixel anywhere in a block kills its vertex ("block-wise
mask decimation"); a mask of any other size is ignored. bbox() then spans the points with x != -1. meta.json's bbox
is [[min x, min y, min z], [max x, max y, max z]] and VC3D trusts a stored one, which is how a stale box silently
drops patches from bbox-filtered inputs (villa issue #1272, Community report).

Deliberate deviations from tifxyz-repair:
  - mask.tif is read from its first TIFF page only, as libtiff's TIFFOpen does, and a three-dimensional page is split
    by its PlanarConfiguration tag (separate: (C, H, W), contiguous: (H, W, C)); tifxyz-repair reads the first series
    with tifffile.imread and guesses the layout from the shape.
  - Coordinates are judged as the float32 values VC3D reads (tifxyz-repair compares a float64 grid as stored, so
    a z of 1e-46 or an x of -1.0000000001 counted as valid there). Other coordinate sample types (float16, 64-bit
    integers), whose bytes VC3D reinterprets, are converted by value and not modelled.
  - Each mask pixel is judged as VC3D's to_valid does, then a block survives only if all its pixels pass; int8 and
    bool masks never pass (VC3D's conversion of 255.0 to int8 is undefined behaviour in C++; 1-bit masks are not
    modelled).
  - Non-finite coordinates are left out of the recomputed bbox, as in tifxyz-repair; VC3D's std::min and std::max
    take an infinity in, skip a NaN met after the first counted vertex, and keep one in that first vertex for the
    whole box.
  - --fix writes a corrected copy to OUT (never in place, no .bak), staged in a temporary folder beside OUT and
    renamed into place only when complete, so an error leaves no partial copy and --overwrite keeps the old OUT;
    several patches go to OUT/<path relative to their tree> (OUT/<name> for a patch given by its own path), and
    targets that collide or touch a source patch are refused before anything is written. --bake-invalid, not in
    the source, also writes (-1, -1, -1) into x, y and z for every vertex VC3D drops, so readers with other
    validity rules agree.
  - The trim-rule comparison (kit/vc3d_prep.py trim_over_zero keeps (X, Y, Z != -1) & X > 0 and ignores mask.tif)
    is new; so is the note on how VC3D uses the mask in the mask-shape warning.
  - No report/audit-tree, inspect or point-set export (tifxyz-repair's deep.py needs scipy).

windaudit
---------
Ported from ScrollFiesta (https://github.com/Hob3rMallow/scrollfiesta_public, commit
bce8a65f97652316efb084171a17d2f1f8d3ae1a, src/tools/wind_audit.c and src/common/pitch_table.c), under the second MIT
License below. The pairwise winding step across an edge u -> v is the source's dwind():
    dr = r_v - r_u, dtheta = wrap(atan2(dy_v, dx_v) - atan2(dy_u, dx_u)) into (-pi, pi],
    dw = turns(r_u, r_v) - s * dtheta / (2 pi), turns = dr / pitch, or the integral of dr / pitch(r) for a table,
with (dx, dy) the vertex minus the umbilicus at the vertex's z. An edge is a merger when |dw| > --merge-tol (0.40);
the "full-turn fusions", |dw| in [0.70, 1.30] on outer edges (both ends at r >= --core-pitches * pitch), are the
source's reliable count and its local gate (exit 4 with --fail-on-local, as in the source), together with the
"multi-turn skips" (outer edges with |dw| above 1.30, a deviation listed below). The mesh is the one
vc_tifxyz2obj writes for the grid (villa apps/src/vc_tifxyz2obj.cpp at a329895: a quad of four valid vertices,
triangles (c10, c00, c01) and (c10, c01, c11), vertices numbered in first-use order), so the edges are the grid's
horizontal and vertical neighbours plus one diagonal per quad, and the audit is the source's audit of that OBJ with
each vertex written in wind_audit's (z, y, x) order. vc_tifxyz2obj itself writes "v x y z", which wind_audit would
read with x as the scroll axis, so its OBJ must be reordered before the source sees it.
Ported: mergers with the |dw| histogram and edge geometry, the component table (faces, radius span, turns, phase span,
z range, V/E/boundary loops/Euler characteristic/genus, full-turn fusions), broad fusions (adjacency-unwrapped phase
span of wholly outer components, opt in with --local-span-tol, part of the local gate), split contacts (vertex pairs
of different components within --split-gap voxels with |dw| <= --split-wtol, the source's spatial hash with its
96-entry chain scan), and the pitch table (CSV r,pitch[,count]; constant past its ends, analytic log integral).

Deliberate deviations from wind_audit.c:
  - Input is a tifxyz grid, not an OBJ; validity is VC3D's loader rule above, and non-finite vertices are dropped.
  - The umbilicus is read with kit.vc3d_orient.load_umbilicus and evaluated as kit.vc3d_orient.centre_at does
    (linear between control points, constant past the ends, villa's Umbilicus); the source's axis table extrapolates
    the end tangents. --centre X Y is the source's fixed --umb-x / --umb-y. There is no default centre.
  - --pitch auto (the default) and --handedness auto are not in the source (it assumes w = r/pitch - theta/2pi, one
    chirality, and a scalar pitch of 9.5 voxels that its own pitch_table.h calls wrong by more than 2x). Interpretation:
    on one spiral sheet w is constant modulo 1 and a sheet switch shifts it by a whole turn, so the pitch p and sign s
    that make exp(2 pi i (r / p - s theta_u / 2 pi)) most concentrated (theta_u unwrapped over the grid) are those of
    the patch, whole-turn switches included. Radial scatter biases the pitch upward, by about 12 (sd / p)^2 / U^2
    for a radial sd over U unwrapped turns (about 12 percent at sd = p / 10 over one turn, 3 percent over two;
    derived and checked on synthetic spirals, not on scroll data). It needs at least one unwrapped turn within one
    component; a weaker
    concentration than 0.4 is refused. With a pitch table and --pitch auto, the scalar pitch (used only for the core
    radius, as in the source) is the table's pitch at the median radius.
  - A non-finite axis (a NaN in the umbilicus or --centre) is refused; it would make every dw NaN and pass the gate.
  - The local gate also fails on multi-turn skips: outer edges with |dw| above FULL_TURN's upper end (1.30). The
    source gates on full-turn fusions only, so a trace that jumps two wraps at once (kit planted's skip family) showed
    in the histogram's 1.30 to 2.30 bin and still passed (found by the 23 Oct 2026 tech scan on planted spirals;
    tests/test_meshqa.py WindAuditTest checks both).
  - theta is unwrapped along grid rows and then across rows by breadth-first search over row runs, instead of the
    source's vertex BFS; both remove only whole 2 pi jumps, so phase spans agree when unwrapping is path independent.
  - Not ported: the axial-section local-shortcut audit and its seam repair (about 1,600 lines of C: contour sections,
    persistence tracking, cut search), the 128-voxel seam-plane classification (a property of ScrollFiesta's cube
    grid, not of a tifxyz), the boundary box, OBJ overlays and the cap of 4,096 distinct split component pairs.
    The vertex order (for the split chain cap) is vc_tifxyz2obj's. Components with equal face counts are ranked by
    their smallest vertex number; wind_audit ranks them by its union-find root (union by size), which can differ,
    so tied components may be numbered in another order.

predcubes
---------
Ported from ScrollFiesta (same repository and commit, src/extract/pred_reject.c, src/extract/pred_reject.h,
src/tools/pred_reject.c, thresholds from src/common/pipeline_constants.h), under the same licence. A cube is
rejected as EMPTY when its largest 6-connected foreground component has under MIN_CC_SIZE (500) voxels, and as a
SOLID SLAB when both hold: at least GARBAGE_INTERIOR_FRAC (0.50) of the foreground, and at least
GARBAGE_INTERIOR_MIN (2,000) voxels, survive GARBAGE_ERODE_R (2) 6-neighbour erosions (faces erode inward), and on
some axis at least GARBAGE_RECT_FRAC (0.20) of the slices, with a run of GARBAGE_RECT_RUN (12) consecutive ones, have
a largest 4-connected component covering at least GARBAGE_RECT_AREA_FRAC (0.10) of the slice and filling at least
GARBAGE_RECT_FILL (0.75) of its bounding box. Community report (ScrollFiesta's src/common/pipeline_constants.h): the
thresholds were calibrated on 2026-06-03 on a PHerc0139 grid of 128-voxel cubes (4 labelled garbage cubes against
one real dense tangle), real cubes at interior fraction <= 0.32 and garbage at >= 0.68; they are not recalibrated
here. Foreground is any nonzero voxel, as in the source; --threshold T uses value >= T
instead (128 is vc_grow_seg_from_seed's surface test, kit/vc3d_prep.py), compared in a float volume's own type, so a
float32 0.7 passes --threshold 0.7.

Deliberate deviations from pred_reject.c:
  - numpy instead of loops: the erosion is the same 6-neighbour test, and connected components are labelled by
    vectorised union-find (hooking to the smaller root, then pointer jumping) instead of flood fill; a slice's largest
    component on ties is the one its raster scan meets first, as in the source. Thresholds keep their float32 values.
  - Cubes come from a zarr region (local or remote) on the absolute grid of --cube voxels, or from a .npy/.tif file;
    the CSV appends largest_cc, empty and partial to the source's columns. Cubes cut by the array edge are scored as
    they are and marked partial.

    MIT License

    Copyright (c) 2026 tifxyz-repair contributors

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
"""

import csv
import json
import math
import os
import shutil
import struct
import sys
import tempfile
from collections import deque
from pathlib import Path

from . import vc3d_io, vc3d_orient

TWO_PI = 2.0 * math.pi


class MeshQAError(ValueError):
    pass


class PitchFitError(MeshQAError):
    """--pitch auto fitted no winding pitch. reason says why, so a caller need not read the message: "span", no
    component spans AUTO_PITCH_MIN_TURNS of unwrapped angle (too little of a turn to fix a pitch), or
    "concentration", one does, but no pitch leaves a concentration of MIN_CONCENTRATION (the grid follows no one
    spiral about this centre: a crushed sheet, an axis off the core, or a surface that is not one winding).
    The converse does not hold: an axis a few voxels off can also fit a wrong pitch whose concentration is 0.4 or
    more, which the audit then uses, so no PitchFitError does not mean the axis was right (wind_audit's "pitch"
    record keeps the fitted pitch and its concentration, to be checked against the expected wrap spacing)."""

    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason

    def __reduce__(self):
        # Exception's own reduce passes only self.args (the message) back to __init__, which needs the reason too:
        # without this, pickle (a process pool) and copy would fail with a TypeError that hides the real error
        return (type(self), (str(self), self.reason))


def _numpy():
    try:
        import numpy
    except ImportError as exc:
        raise MeshQAError("kit meshqa needs numpy (pip install numpy, or run it in villa's environment)") from exc
    return numpy


def _tifffile():
    try:
        import tifffile
    except ImportError:
        return None
    return tifffile


def _f32(x):
    """The double a C float constant such as 0.10f widens to."""
    return struct.unpack("f", struct.pack("f", x))[0]


# ================================================================ validity (tifxyz-repair)

COORD_FILES = ("x.tif", "y.tif", "z.tif")
INVALID_SENTINEL = -1.0
MASK_RETAIN_THRESHOLD = 255     # QuadSurface.cpp: channel-0 values >= this are kept
BBOX_TOLERANCE = 1e-3           # voxels; villa #1272 used 1e-3
SEVERITIES = ("error", "warning", "info")
_KIND_DTYPE = {"u8": "uint8", "i8": "int8", "u16": "uint16", "i16": "int16", "u32": "uint32", "i32": "int32",
               "f32": "float32", "f64": "float64"}
TRIM_RULE = "kit/vc3d_prep.py trim_over_zero: (X, Y, Z != -1) & X > 0, mask.tif ignored"


def is_tifxyz_dir(path):
    path = Path(path)
    return all((path / f).is_file() for f in COORD_FILES)


def find_patches(root):
    """Every tifxyz directory under root (root itself when it is one); tifxyz directories do not nest."""
    root = Path(root)
    if is_tifxyz_dir(root):
        return [root]
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        names = set(filenames)
        if all(f in names for f in COORD_FILES):
            found.append(Path(dirpath))
            dirnames.clear()
        else:
            dirnames.sort()
    return sorted(found)


def read_tiff_page(path):
    """(array, planar_separate) of the first TIFF page, the directory libtiff's TIFFOpen reads. tifffile when present,
    else kit/vc3d_io.read_tiff (single-sample pages only)."""
    np = _numpy()
    tf = _tifffile()
    if tf is not None:
        with tf.TiffFile(str(path)) as t:
            if not len(t.pages):
                raise MeshQAError(f"{path}: TIFF has no pages")
            page = t.pages[0]
            return page.asarray(), int(page.planarconfig) == 2
    r = vc3d_io.read_tiff(path)
    raw = r.data if isinstance(r.data, (bytes, bytearray)) else r.data.tobytes()
    return np.frombuffer(raw, dtype=_KIND_DTYPE[r.kind]).reshape(r.h, r.w).copy(), False


def _write_grid(path, arr):
    np = _numpy()
    arr = np.ascontiguousarray(arr, dtype=np.float32)
    tf = _tifffile()
    if tf is not None:
        tf.imwrite(str(path), arr)
    else:
        vc3d_io.write_tiff(path, vc3d_io.raster_from_numpy(arr))


def _mask_factor(mask_dim, grid_dim):
    """QuadSurface.cpp computeScaleFactor: 1 at grid size, the integer ratio for an integer multiple, else 0 (ignored)."""
    if mask_dim == grid_dim:
        return 1
    if grid_dim > 0 and mask_dim > 0 and mask_dim % grid_dim == 0:
        return mask_dim // grid_dim
    return 0


def vc3d_float(np, arr):
    """The float32 values QuadSurface.cpp's to_float reads from a coordinate TIFF (static_cast<float>)."""
    with np.errstate(over="ignore", invalid="ignore"):
        return np.asarray(arr).astype(np.float32)


_MASK_BY_VALUE = ("uint8", "uint16", "uint32", "int16", "int32", "float32", "float64")


def mask_pass(np, m):
    """QuadSurface.cpp to_valid per mask pixel: value >= 255 for the sample types it switches on, never for int8
    (undefined behaviour there) or bool (1-bit, not modelled), else its default: the sample's first byte >= 255."""
    name = m.dtype.newbyteorder("=").name
    if name in _MASK_BY_VALUE:
        with np.errstate(invalid="ignore"):
            return np.asarray(m, dtype=np.float64) >= MASK_RETAIN_THRESHOLD
    if name in ("int8", "bool"):
        return np.zeros(m.shape, dtype=bool)
    native = np.ascontiguousarray(m, dtype=m.dtype.newbyteorder("="))
    return native.view(np.uint8).reshape(m.shape + (m.dtype.itemsize,))[..., 0] >= MASK_RETAIN_THRESHOLD


class Patch:
    """A loaded tifxyz directory. Read failures are kept in read_errors (with a zero-size placeholder grid) so that
    checks report them instead of crashing."""

    def __init__(self, path, x, y, z, meta=None, meta_error=None, mask=None, mask_planar=False, read_errors=None,
                 dtypes=None):
        self.path = Path(path)
        self.x, self.y, self.z = x, y, z
        self.dtypes = dict(dtypes or {f"{n}.tif": a.dtype for n, a in zip("xyz", (x, y, z))})
        self.meta, self.meta_error = meta, meta_error
        self.mask, self.mask_planar = mask, mask_planar
        self.read_errors = dict(read_errors or {})
        self._valid = None
        self._mask = None

    @property
    def shape(self):
        return self.x.shape

    def shapes_agree(self):
        return self.x.shape == self.y.shape == self.z.shape

    def mask_valid(self):
        """(per-vertex validity from mask.tif or None, how VC3D uses the mask)."""
        if self._mask is None:
            self._mask = self._mask_valid()
        return self._mask

    def _mask_valid(self):
        np = _numpy()
        if self.mask is None:
            return None, "absent"
        if self.x.size == 0:
            return None, "not applied: the grid is empty"
        m = self.mask
        if m.ndim == 3:
            m = m[0] if self.mask_planar else m[..., 0]
        if m.ndim != 2:
            return None, f"ignored: mask.tif page has {self.mask.ndim} dimensions"
        h, w = self.x.shape
        mh, mw = m.shape
        sy, sx = _mask_factor(mh, h), _mask_factor(mw, w)
        if not sy or not sx:
            return None, f"ignored by VC3D: mask {mh}x{mw} is not the grid size {h}x{w} or an integer multiple of it"
        ok = mask_pass(np, m)
        if (sy, sx) != (1, 1):
            # Every mask pixel invalidates grid cell (src // scale): a block survives only if all its pixels pass.
            ok = ok[:h * sy, :w * sx].reshape(h, sy, w, sx).all(axis=(1, 3))
            note = f"decimated {sy}x{sx}: a vertex survives only if every mask pixel of its block is >= 255"
        else:
            note = "applied at grid size"
        return ok, note

    @property
    def valid(self):
        """VC3D's loader validity: not (z <= 0), mask.tif channel 0 >= 255 when usable, and x != -1 (on the float32
        grids load_patch keeps)."""
        if self._valid is None:
            np = _numpy()
            if not self.shapes_agree():
                self._valid = np.zeros(self.x.shape, dtype=bool)
            else:
                with np.errstate(invalid="ignore"):
                    valid = (self.x != INVALID_SENTINEL) & ~(self.z <= 0)
                mask, _ = self.mask_valid()
                if mask is not None:
                    valid = valid & mask
                self._valid = valid
        return self._valid

    def points(self):
        np = _numpy()
        return np.stack([self.x, self.y, self.z], axis=-1)


def load_patch(path, load_mask=True):
    """A Patch whose x, y and z are the float32 values VC3D's loader reads; the stored sample types are in dtypes."""
    np = _numpy()
    path = Path(path)
    arrays, errors, dtypes = {}, {}, {}
    for fname in COORD_FILES:
        try:
            arr, _ = read_tiff_page(path / fname)
            if arr.ndim != 2:
                raise MeshQAError(f"expected a 2-D grid, got shape {arr.shape}")
            dtypes[fname] = arr.dtype
            arrays[fname[0]] = vc3d_float(np, arr)
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            arrays[fname[0]] = np.zeros((0, 0), dtype=np.float32)
            dtypes[fname] = np.dtype(np.float32)
            errors[fname] = f"{type(exc).__name__}: {exc}"
    meta, meta_error = None, None
    meta_path = path / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_bytes())
            if not isinstance(meta, dict):
                meta, meta_error = None, "meta.json is not a JSON object"
        except Exception as exc:  # noqa: BLE001
            meta_error = f"{type(exc).__name__}: {exc}"
    else:
        meta_error = "meta.json not found"
    mask, planar = None, False
    if load_mask and (path / "mask.tif").is_file():
        try:
            mask, planar = read_tiff_page(path / "mask.tif")
        except Exception as exc:  # noqa: BLE001
            errors["mask.tif"] = f"{type(exc).__name__}: {exc}"
    return Patch(path, arrays["x"], arrays["y"], arrays["z"], meta, meta_error, mask, planar, errors, dtypes)


def compute_bbox(patch):
    """([min x, min y, min z], [max x, max y, max z]) over valid vertices, NaN left out; None when none is valid."""
    np = _numpy()
    valid = patch.valid
    if not valid.any():
        return None
    low, high = [], []
    for arr in (patch.x, patch.y, patch.z):
        vals = arr[valid]
        finite = vals[np.isfinite(vals)]
        if finite.size == 0:
            return None
        low.append(float(finite.min()))
        high.append(float(finite.max()))
    return low, high


def parse_meta_bbox(meta):
    raw = meta.get("bbox")
    if raw is None:
        return None
    try:
        low = [float(v) for v in raw[0]]
        high = [float(v) for v in raw[1]]
        if len(low) != 3 or len(high) != 3 or any(not math.isfinite(v) for v in low + high):
            return None
        return low, high
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def _finding(check, severity, message, **data):
    return {"check": check, "severity": severity, "message": message, **data}


def check_files(patch):
    out = [_finding("tif-read", "error", f"{f} unreadable: {e}", file=f) for f, e in patch.read_errors.items()]
    if patch.meta_error is not None:
        out.append(_finding("meta-parse", "error", f"meta.json problem: {patch.meta_error}"))
    return out


def check_grid_consistency(patch):
    np = _numpy()
    shapes = {"x.tif": patch.x.shape, "y.tif": patch.y.shape, "z.tif": patch.z.shape}
    if len(set(shapes.values())) > 1:
        return [_finding("grid-shape", "error", f"coordinate grids have mismatched shapes: {shapes}",
                         shapes={k: list(v) for k, v in shapes.items()})]
    out = []
    if patch.x.size == 0:
        if not patch.read_errors:
            out.append(_finding("grid-empty", "error", "coordinate grids are empty"))
        return out
    for name in COORD_FILES:
        dt = np.dtype(patch.dtypes.get(name, np.float32))
        if dt.newbyteorder("=") != np.float32:
            out.append(_finding("grid-dtype", "warning", f"{name} dtype is {dt}, expected float32 "
                                "(VC3D writes float32 and reads every grid as float32)", file=name, dtype=str(dt)))
    if patch.mask is not None and patch.mask.shape != patch.x.shape:
        _, note = patch.mask_valid()
        out.append(_finding("mask-shape", "warning", f"mask.tif shape {tuple(patch.mask.shape)} != grid shape "
                            f"{tuple(patch.x.shape)}; VC3D: {note}"))
    return out


def check_vertices(patch):
    np = _numpy()
    if patch.x.size == 0 or not patch.shapes_agree():
        return []
    valid = patch.valid
    n, n_valid = valid.size, int(valid.sum())
    if n_valid == 0:
        return [_finding("no-valid-vertices", "error", "patch has no valid vertices under the loader's rules "
                         "(x == -1, z <= 0, or masked out)")]
    out = []
    pts = patch.points()
    n_nan = int((~np.isfinite(pts).all(axis=-1) & valid).sum())
    if n_nan:
        out.append(_finding("nan-vertices", "warning", f"{n_nan} valid-flagged vertices contain NaN/Inf coordinates",
                            count=n_nan))
    n_partial = int((valid & (patch.y == -1)).sum())
    if n_partial:
        out.append(_finding("partial-sentinel", "warning", f"{n_partial} vertices have y == -1 but remain valid under "
                            "the loader's rules (x != -1, z > 0, mask retained), so likely corrupt", count=n_partial))
    out.append(_finding("valid-fraction", "info", f"{n_valid}/{n} vertices valid ({n_valid / n:.1%})",
                        valid=n_valid, total=n))
    return out


def check_meta_fields(patch):
    if patch.meta is None:
        return []
    out, meta = [], patch.meta
    fmt = meta.get("format")
    if fmt != "tifxyz":
        out.append(_finding("meta-format", "warning", f'format is {fmt!r}, expected "tifxyz"'))
    scale = meta.get("scale")
    if (not isinstance(scale, (list, tuple)) or len(scale) != 2
            or not all(isinstance(s, (int, float)) and s > 0 for s in scale)):
        out.append(_finding("meta-scale", "error", f"scale is {scale!r}, expected two positive numbers "
                            "(downstream area/size math divides by it)", scale=scale))
    for key in ("voxelsize", "voxelsize_um", "voxel_size"):
        if key in meta:
            v = meta[key]
            if not isinstance(v, (int, float)) or v <= 0:
                out.append(_finding("meta-voxelsize", "error", f"{key} is {v!r}. A zero or invalid voxel size "
                                    "silently discards segments downstream (villa #1226 failure class)",
                                    key=key, value=v))
    return out


def check_bbox(patch):
    """villa #1272: recompute the bbox from the grids as VC3D would and diff it against meta.json."""
    np = _numpy()
    if patch.meta is None or patch.x.size == 0 or not patch.shapes_agree():
        return []
    stored = parse_meta_bbox(patch.meta)
    if stored is None:
        if "bbox" in patch.meta:
            return [_finding("bbox-malformed", "error", f"bbox field is malformed: {patch.meta['bbox']!r}")]
        return [_finding("bbox-missing", "info", "meta.json has no bbox (recomputed lazily by VC3D)")]
    true = compute_bbox(patch)
    if true is None:
        return []
    (t_low, t_high), (s_low, s_high) = true, stored
    drift = [abs(a - b) for a, b in zip(t_low + t_high, s_low + s_high)]
    max_drift = max(drift)
    if max_drift <= BBOX_TOLERANCE:
        return []
    pts = patch.points()[patch.valid]
    pts = pts[np.isfinite(pts).all(axis=-1)]
    lo, hi = np.array(s_low, dtype=np.float64), np.array(s_high, dtype=np.float64)
    outside = ((pts < lo - BBOX_TOLERANCE) | (pts > hi + BBOX_TOLERANCE)).any(axis=-1)
    frac = float(outside.mean()) if pts.size else 0.0
    return [_finding("bbox-stale", "error", f"stored bbox is stale: max drift {max_drift:.1f} voxels, {frac:.1%} of "
                     "valid vertices outside the stored box (villa #1272)", max_drift=max_drift,
                     per_axis_drift=drift, stored=[s_low, s_high], recomputed=[t_low, t_high], frac_outside=frac)]


ALL_CHECKS = (check_files, check_grid_consistency, check_vertices, check_meta_fields, check_bbox)


def validate_patch(patch):
    findings = []
    for chk in ALL_CHECKS:
        findings.extend(chk(patch))
    return findings


def worst_severity(findings):
    sevs = {f["severity"] for f in findings}
    for s in SEVERITIES:
        if s in sevs:
            return s
    return "ok"


def trim_rule_valid(patch):
    """The validity rule of kit/vc3d_prep.py trim_over_zero."""
    np = _numpy()
    with np.errstate(invalid="ignore"):
        return (patch.x != -1) & (patch.y != -1) & (patch.z != -1) & (patch.x > 0)


def compare_trim_rule(patch):
    """How many vertices VC3D's loader and the private trim rule classify differently, and why."""
    np = _numpy()
    if patch.x.size == 0 or not patch.shapes_agree():
        return None
    v, t = patch.valid, trim_rule_valid(patch)
    mask, note = patch.mask_valid()
    vc3d_only, trim_only = v & ~t, t & ~v
    with np.errstate(invalid="ignore"):
        out = {
            "rule": TRIM_RULE, "vertices": int(v.size), "vc3d_valid": int(v.sum()), "trim_valid": int(t.sum()),
            "disagree": int((v != t).sum()),
            "vc3d_only": {"total": int(vc3d_only.sum()),
                          "y_sentinel": int((vc3d_only & (patch.y == -1)).sum()),
                          "x_not_positive": int((vc3d_only & ~(patch.x > 0)).sum())},
            "trim_only": {"total": int(trim_only.sum()),
                          "z_not_positive": int((trim_only & (patch.z <= 0)).sum()),
                          "masked": int((trim_only & ~mask).sum()) if mask is not None else 0},
            "mask": note,
        }
    return out


def repair_plan(patch, strip=False):
    """(new meta or None, change or None): what tifxyz-repair's repair_bbox would write. Only the bbox field changes;
    an absent bbox is legal (VC3D recomputes it lazily) and is not added."""
    if patch.meta is None:
        return None, None
    stored, true = parse_meta_bbox(patch.meta), compute_bbox(patch)
    if strip:
        if "bbox" not in patch.meta:
            return None, None
        return ({k: v for k, v in patch.meta.items() if k != "bbox"},
                "remove bbox field (recomputed lazily by VC3D on next load)")
    if true is None:
        return None, None
    if stored is not None:
        drift = max(abs(a - b) for a, b in zip(true[0] + true[1], stored[0] + stored[1]))
        if drift <= BBOX_TOLERANCE:
            return None, None
        change = f"recompute bbox (drift {drift:.1f} voxels)"
    elif "bbox" in patch.meta:
        change = "replace malformed bbox with recomputed bbox"
    else:
        return None, None
    new_meta = dict(patch.meta)
    new_meta["bbox"] = [list(true[0]), list(true[1])]
    return new_meta, change


def fix_copy(src, out, strip=False, bake=False, overwrite=False):
    """Copy a tifxyz to out with a corrected meta.json bbox (written as VC3D does: indent 4, trailing newline, temp
    file then rename); with bake, x, y and z of every vertex VC3D drops become -1. The source is never touched. The
    copy is built in a temporary folder beside out and renamed into place only when complete: an error leaves no
    partial copy, and with overwrite the previous out stays until the new copy is ready."""
    np = _numpy()
    src, out = Path(src), Path(os.path.abspath(out))
    rs, ro = src.resolve(), out.resolve()
    if ro == rs or rs in ro.parents or ro in rs.parents:
        raise MeshQAError(f"--fix writes a separate copy: {out} must be neither {src}, inside it, nor around it")
    patch = load_patch(src)
    if patch.read_errors or not patch.shapes_agree() or patch.x.size == 0:
        raise MeshQAError(f"{src}: cannot fix a patch whose grids do not read ({patch.read_errors or 'shapes differ'})")
    replace = out.exists() or out.is_symlink()
    if replace:
        if not overwrite:
            raise MeshQAError(f"{out} exists; pass --overwrite to replace it")
        if out.is_symlink() or not out.is_dir() or not (is_tifxyz_dir(out) or not any(out.iterdir())):
            raise MeshQAError(f"{out}: --overwrite replaces only an empty folder or a tifxyz folder (not a link)")
    new_meta, change = repair_plan(patch, strip)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{out.name}.", suffix=".meshqa-partial", dir=out.parent))
    stage, old = work / "copy", work / "old"
    try:
        shutil.copytree(src, stage)
        baked = 0
        if bake:
            valid = patch.valid
            sentinel = (patch.x == -1) & (patch.y == -1) & (patch.z == -1)
            baked = int((~valid & ~sentinel).sum())
            if baked:
                for name, arr in zip("xyz", (patch.x, patch.y, patch.z)):
                    _write_grid(stage / f"{name}.tif", np.where(valid, arr, -1.0))
        if new_meta is not None:
            tmp = stage / "meta.json.tmp"
            tmp.write_text(json.dumps(new_meta, indent=4) + "\n", encoding="utf-8")
            os.replace(tmp, stage / "meta.json")
        if replace:
            os.replace(out, old)
        try:
            os.replace(stage, out)
        except BaseException:
            if replace and not out.exists():
                os.replace(old, out)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"source": str(src), "out": str(out), "change": change, "baked_vertices": baked}


def fix_targets(out, pairs):
    """The --fix destination of each (root, patch): OUT for one patch given by its own path, else OUT/<path relative
    to its tree> (OUT/<name> for a patch given by its own path). Refuses, before anything is written, targets that
    collide or that are, lie inside or contain a source patch."""
    out = Path(out)
    targets = []
    for root, patch in pairs:
        root, patch = Path(root), Path(patch)
        if patch == root:
            targets.append(out if len(pairs) == 1 else out / patch.name)
        else:
            targets.append(out / patch.relative_to(root))
    sources = {Path(p).resolve() for _, p in pairs}
    around = {a for s in sources for a in s.parents}
    seen = {}
    for (_, patch), target in zip(pairs, targets):
        rt = target.resolve()
        if rt in seen:
            raise MeshQAError(f"--fix: {seen[rt]} and {patch} would both be written to {target}")
        seen[rt] = patch
        if rt in sources or rt in around or any(a in sources for a in rt.parents):
            raise MeshQAError(f"--fix: {target} is, lies inside or contains a source patch; choose an OUT apart "
                              "from the patches")
    return targets


def _collect(paths):
    """[(root, patch)] for the given paths, and exit code 2 when a path is missing or holds no tifxyz."""
    pairs, bad = [], False
    for target in paths:
        t = Path(target)
        if not t.exists():
            print(f"error: path does not exist: {t}", file=sys.stderr)
            bad = True
            continue
        found = find_patches(t)
        if not found:
            print(f"error: no tifxyz patches under {t}", file=sys.stderr)
            bad = True
        pairs.extend((t, p) for p in found)
    return pairs, (2 if bad else 0)


def _format_trim(cmp):
    if cmp is None:
        return "    trim rule: not compared (grids unreadable)"
    v, t = cmp["vc3d_only"], cmp["trim_only"]
    return (f"    trim rule ({cmp['rule']}): {cmp['disagree']} of {cmp['vertices']} vertices disagree; "
            f"{v['total']} valid only under VC3D (y == -1: {v['y_sentinel']}, x <= 0 or NaN: {v['x_not_positive']}), "
            f"{t['total']} valid only under trim (z <= 0: {t['z_not_positive']}, masked: {t['masked']}); "
            f"mask.tif {cmp['mask']}")


def run_validity(args):
    if not args.fix and (args.strip_bbox or args.bake_invalid or args.overwrite):
        raise MeshQAError("--strip-bbox, --bake-invalid and --overwrite act only with --fix OUT")
    pairs, code = _collect(args.paths)
    targets = fix_targets(args.fix, pairs) if args.fix else [None] * len(pairs)
    results = []
    for (root, path), target in zip(pairs, targets):
        try:
            patch = load_patch(path)
            findings = validate_patch(patch)
            cmp = compare_trim_rule(patch)
        except Exception as exc:  # noqa: BLE001 - one bad patch must not end the batch
            findings = [_finding("internal", "error", f"{type(exc).__name__}: {exc}")]
            cmp = None
        rec = {"path": str(path), "status": worst_severity(findings), "findings": findings, "trim_rule": cmp}
        if args.fix:
            try:
                rec["fix"] = fix_copy(path, target, strip=args.strip_bbox, bake=args.bake_invalid,
                                      overwrite=args.overwrite)
            except (MeshQAError, OSError) as exc:
                rec["fix"] = {"error": str(exc)}
                code = code or 1
        if code == 0 and rec["status"] == "error":
            code = 1
        results.append(rec)
        if not args.json:
            print(f"[{rec['status']:>7}] {path}")
            for f in findings:
                if args.verbose or f["severity"] != "info":
                    print(f"    {f['severity']} {f['check']}: {f['message']}")
            print(_format_trim(cmp))
            if "fix" in rec:
                fx = rec["fix"]
                if "error" in fx:
                    print(f"    fix failed: {fx['error']}")
                else:
                    print(f"    fix: wrote {fx['out']} ({fx['change'] or 'bbox unchanged'}"
                          f"{', baked ' + str(fx['baked_vertices']) + ' dropped vertices to -1' if args.bake_invalid else ''})")
    if args.json:
        print(json.dumps(results, indent=2))
    return code


# ================================================================ windaudit (ScrollFiesta wind_audit)

MERGE_TOL, SPLIT_WTOL, SPLIT_GAP = 0.40, 0.25, 14.0
CORE_PITCHES, MIN_FACES, TOP = 3.0, 64, 25
FULL_TURN = (0.70, 1.30)
HIST_EDGES = (0.40, 0.70, 1.30, 2.30)
HIST_LABELS = ("<0.40 (ok)", "0.40-0.70", "0.70-1.30 (~1 turn)", "1.30-2.30 (~2)", ">2.30")
SPLIT_SCAN = 96                  # wind_audit visits at most 96 entries of a hash cell's chain
PITCH_RANGE = (2.0, 400.0)       # voxels searched by --pitch auto
AUTO_PITCH_MIN_TURNS = 1.0       # Interpretation, not from the source: less than a turn does not fix the pitch
AUTO_HAND_MIN_TURNS = 0.5        # ... and half a turn already separates the two handednesses
MIN_CONCENTRATION = 0.4          # Interpretation: below this the patch does not follow one spiral about the centre
PITCH_SAMPLES = 8000


def _wrap_pmpi(np, a):
    """wrap_pmpi: into (-pi, pi]."""
    return a - TWO_PI * np.ceil((a - math.pi) / TWO_PI)


class ScalarPitch:
    def __init__(self, pitch):
        self.pitch = float(pitch)

    def turns_at(self, r):
        return r / self.pitch

    def describe(self):
        return f"scalar {self.pitch:.3f}"


class PitchTable:
    """pitch_table.c: pitch(r) piecewise linear between knots, constant past the ends; turns = integral of dr/pitch."""

    MAX_KNOTS, MIN_PITCH = 4096, 0.25

    def __init__(self, rows, path=None):
        rows = sorted((float(r), float(p)) for r, p in rows)
        if not rows or len(rows) > self.MAX_KNOTS:
            raise MeshQAError(f"pitch table needs 1 to {self.MAX_KNOTS} knots")
        for r, p in rows:
            if not (math.isfinite(r) and math.isfinite(p)) or p < self.MIN_PITCH:
                raise MeshQAError(f"pitch table: bad knot r={r} pitch={p} (finite, pitch >= {self.MIN_PITCH})")
        if any(not rows[i][0] > rows[i - 1][0] for i in range(1, len(rows))):
            raise MeshQAError("pitch table: duplicate radii")
        self.path = str(path) if path else None
        self.r = [r for r, _ in rows]
        self.p = [p for _, p in rows]
        self.turns = [0.0]
        for i in range(1, len(rows)):
            self.turns.append(self.turns[-1] + self._segment(self.r[i - 1], self.p[i - 1], self.r[i], self.p[i],
                                                             self.r[i]))

    @staticmethod
    def _segment(r0, p0, r1, p1, r):
        dr = r1 - r0
        if not dr > 0:
            return 0.0
        s = (p1 - p0) / dr
        x = r - r0
        return x / p0 if abs(s) < 1e-9 else math.log((p0 + s * x) / p0) / s

    @classmethod
    def load(cls, path):
        rows = []
        for line in Path(path).read_text().splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            parts = text.split(",")
            try:
                rows.append((float(parts[0]), float(parts[1])))
            except (ValueError, IndexError):
                if not rows and "," in text:
                    continue          # header line(s) such as "r,pitch,count"
                raise MeshQAError(f"{path}: cannot parse pitch table line {line!r}") from None
        return cls(rows, path)

    def pitch_at(self, r):
        np = _numpy()
        return np.interp(r, self.r, self.p)

    def turns_at(self, r):
        np = _numpy()
        r = np.asarray(r, dtype=np.float64)
        rs, ps, ts = (np.array(v, dtype=np.float64) for v in (self.r, self.p, self.turns))
        out = np.empty_like(r)
        lo, hi = r <= rs[0], r >= rs[-1]
        mid = ~lo & ~hi
        out[lo] = (r[lo] - rs[0]) / ps[0]
        out[hi & ~lo] = ts[-1] + (r[hi & ~lo] - rs[-1]) / ps[-1]
        if mid.any():
            rm = r[mid]
            k = np.searchsorted(rs, rm, side="left") - 1
            r0, p0, r1, p1 = rs[k], ps[k], rs[k + 1], ps[k + 1]
            s = (p1 - p0) / (r1 - r0)
            x = rm - r0
            flat = np.abs(s) < 1e-9
            with np.errstate(divide="ignore", invalid="ignore"):
                seg = np.where(flat, x / p0, np.log((p0 + s * x) / p0) / np.where(flat, 1.0, s))
            out[mid] = ts[k] + seg
        return out

    def dturns(self, ra, rb):
        return self.turns_at(rb) - self.turns_at(ra)

    def describe(self):
        return f"table {self.path or '<memory>'} ({len(self.r)} knots)"


class Axis:
    """The scroll axis: umbilicus control points [(z, y, x)] evaluated as kit.vc3d_orient.centre_at, or a fixed
    (x, y) centre."""

    def __init__(self, points=None, centre=None, label=""):
        if (points is None) == (centre is None):
            raise MeshQAError("give an umbilicus or a fixed centre")
        self.points = points
        self.fixed = tuple(float(v) for v in centre) if centre is not None else None
        self.label = label

    def centre(self, np, z):
        """(x, y) arrays at heights z, vectorised centre_at."""
        z = np.asarray(z, dtype=np.float64)
        if self.fixed is not None:
            return np.full(z.shape, self.fixed[0]), np.full(z.shape, self.fixed[1])
        pts = np.array(self.points, dtype=np.float64)
        zs, ys, xs = pts[:, 0], pts[:, 1], pts[:, 2]
        if len(zs) == 1:
            return np.full(z.shape, xs[0]), np.full(z.shape, ys[0])
        lo = np.clip(np.searchsorted(zs, z, side="right") - 1, 0, len(zs) - 2)
        hi = lo + 1
        dz = zs[hi] - zs[lo]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(dz != 0, (z - zs[lo]) / np.where(dz != 0, dz, 1.0), 0.0)
        cx, cy = xs[lo] + t * (xs[hi] - xs[lo]), ys[lo] + t * (ys[hi] - ys[lo])
        below, above = z <= zs[0], z >= zs[-1]
        cx = np.where(below, xs[0], np.where(above, xs[-1], cx))
        cy = np.where(below, ys[0], np.where(above, ys[-1], cy))
        return cx, cy

    def describe(self):
        if self.fixed is not None:
            return f"fixed centre (x {self.fixed[0]:.1f}, y {self.fixed[1]:.1f})"
        zs = [p[0] for p in self.points]
        return f"umbilicus {self.label} ({len(self.points)} points, z {min(zs):.1f}..{max(zs):.1f})"


def union_min(np, n, eu, ev):
    """Connected components of nodes 0..n-1 joined by edges (eu, ev): each node's root is its component's smallest
    node. Vectorised union-find: roots hook onto the smaller root across every edge, then pointer jumping."""
    parent = np.arange(n, dtype=np.int64)
    eu = np.asarray(eu, dtype=np.int64)
    ev = np.asarray(ev, dtype=np.int64)
    while eu.size:
        pu, pv = parent[eu], parent[ev]
        cross = pu != pv
        if not cross.any():
            break
        eu, ev, pu, pv = eu[cross], ev[cross], pu[cross], pv[cross]
        np.minimum.at(parent, np.maximum(pu, pv), np.minimum(pu, pv))
        while True:
            nxt = parent[parent]
            if np.array_equal(nxt, parent):
                break
            parent = nxt
    return parent


def _grid_mesh(np, valid):
    """The mesh vc_tifxyz2obj writes: quads of four valid vertices; edge counts of the horizontal and vertical edges
    (faces per edge); the mesh vertices in OBJ order; and the compact (OBJ) index of every grid vertex (-1 off mesh)."""
    H, W = valid.shape
    Q = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    cnt_h = np.zeros((H, W - 1), np.int8)
    cnt_h[:-1] += Q
    cnt_h[1:] += Q
    cnt_v = np.zeros((H - 1, W), np.int8)
    cnt_v[:, :-1] += Q
    cnt_v[:, 1:] += Q
    big = np.iinfo(np.int64).max
    key = np.full((H, W), big, np.int64)
    q = np.arange((H - 1) * (W - 1), dtype=np.int64).reshape(H - 1, W - 1) * 4
    corners = ((slice(None, -1), slice(None, -1)), (slice(None, -1), slice(1, None)),
               (slice(1, None), slice(None, -1)), (slice(1, None), slice(1, None)))
    for rank, (rs, cs) in enumerate(corners):     # c00, c01, c10, c11 of each quad, quads in raster order
        sub = key[rs, cs]
        np.minimum(sub, np.where(Q, q + rank, big), out=sub)
    on = np.flatnonzero(key.ravel() != big)
    order = on[np.argsort(key.ravel()[on], kind="stable")]
    cid = np.full(H * W, -1, np.int64)
    cid[order] = np.arange(order.size)
    return Q, cnt_h, cnt_v, order, cid.reshape(H, W)


def _unwrap(np, cnt_h, cnt_v, on_mesh, th_g):
    """theta unwrapped over mesh edges, and a component id per grid vertex (-1 off mesh). Rows are unwrapped along
    their horizontal edges into runs; runs are joined across vertical edges by breadth-first search, each new run
    shifted by the whole turns that bring it next to its neighbour."""
    H, W = on_mesh.shape
    eh = cnt_h > 0
    left = np.zeros((H, W), bool)
    left[:, 1:] = eh
    start = on_mesh & ~left
    flat_start = np.flatnonzero(start)
    run_of = np.cumsum(start.ravel()) - 1
    run_of[~on_mesh.ravel()] = -1
    with np.errstate(invalid="ignore"):
        dh = np.where(eh, _wrap_pmpi(np, th_g[:, 1:] - th_g[:, :-1]), 0.0)
    C = np.zeros((H, W))
    C[:, 1:] = np.cumsum(dh, axis=1)
    Cf, thf = C.ravel(), th_g.ravel()
    run_base = thf[flat_start] - Cf[flat_start]
    on = on_mesh.ravel()
    theta_run = np.full(H * W, np.nan)
    theta_run[on] = run_base[run_of[on]] + Cf[on]
    nruns = flat_start.size
    rr, cc = np.nonzero(cnt_v > 0)
    ua, ub = rr * W + cc, (rr + 1) * W + cc
    ra, rb = run_of[ua], run_of[ub]
    pair = ra * nruns + rb
    _, first = np.unique(pair, return_index=True)
    ra, rb = ra[first], rb[first]
    k = np.floor((theta_run[ua[first]] - theta_run[ub[first]]) / TWO_PI + 0.5).astype(np.int64)
    src = np.concatenate([ra, rb])
    dst = np.concatenate([rb, ra])
    kk = np.concatenate([k, -k])
    o = np.argsort(src, kind="stable")
    src, dst, kk = src[o], dst[o], kk[o]
    ptr = np.searchsorted(src, np.arange(nruns + 1)).tolist()
    dst, kk = dst.tolist(), kk.tolist()
    comp_run = [-1] * nruns
    off = [0] * nruns
    ncomp = 0
    for seed in range(nruns):
        if comp_run[seed] != -1:
            continue
        comp_run[seed] = ncomp
        queue = deque([seed])
        while queue:
            u = queue.popleft()
            for e in range(ptr[u], ptr[u + 1]):
                v = dst[e]
                if comp_run[v] == -1:
                    comp_run[v] = ncomp
                    off[v] = off[u] + kk[e]
                    queue.append(v)
        ncomp += 1
    comp_run = np.array(comp_run, dtype=np.int64)
    off = np.array(off, dtype=np.float64)
    comp = np.full(H * W, -1, np.int64)
    comp[on] = comp_run[run_of[on]]
    theta_u = theta_run.copy()
    theta_u[on] += TWO_PI * off[run_of[on]]
    return theta_u, comp, ncomp, nruns


def _span_turns(np, thu, comp, ncomp):
    lo = np.full(ncomp, np.inf)
    hi = np.full(ncomp, -np.inf)
    np.minimum.at(lo, comp, thu)
    np.maximum.at(hi, comp, thu)
    return float(((hi - lo) / TWO_PI).max()) if ncomp else 0.0


def _sample(np, n, samples, seed=0):
    if n <= samples:
        return np.arange(n)
    return np.sort(np.random.default_rng(seed).choice(n, samples, replace=False))


def _concentration(np, turns, thu, sgn):
    """|mean exp(2 pi i (turns - sgn theta_u / 2 pi))| over the given vertices."""
    return float(np.abs(np.mean(np.exp(2j * np.pi * turns - 1j * sgn * thu))))


def estimate_pitch(np, rad, thu, comp, ncomp, prange=PITCH_RANGE, samples=PITCH_SAMPLES):
    """Pitch and handedness from the grid (Interpretation, not in the source; see the module docstring)."""
    span = _span_turns(np, thu, comp, ncomp)
    if span < AUTO_PITCH_MIN_TURNS:
        raise PitchFitError(f"--pitch auto needs a component spanning at least {AUTO_PITCH_MIN_TURNS:g} turn of "
                            f"unwrapped angle about the axis; this grid spans {span:.2f}. Give --pitch (voxels between "
                            "wraps)", "span")
    idx = _sample(np, rad.size, samples)
    rr = rad[idx]
    e = np.exp(-1j * thu[idx])

    def conc(ps):
        """Concentrations for handedness +1 and -1 at each pitch."""
        out = np.empty((2, len(ps)))
        for k in range(0, len(ps), 32):
            z = np.exp((2j * np.pi / ps[k:k + 32])[:, None] * rr[None, :])
            out[0, k:k + 32] = np.abs(z @ e) / rr.size
            out[1, k:k + 32] = np.abs(z @ np.conj(e)) / rr.size
        return out

    ps = np.exp(np.arange(math.log(prange[0]), math.log(prange[1]), math.log(1.003)))
    c = conc(ps)
    row, k = np.unravel_index(int(np.argmax(c)), c.shape)
    sgn = 1 if row == 0 else -1
    fine = ps[k] * np.exp(np.linspace(-0.004, 0.004, 161))
    c = conc(fine)
    k = int(np.argmax(c[row]))
    pitch, conc_best, other = float(fine[k]), float(c[row, k]), float(c[1 - row, k])
    if conc_best < MIN_CONCENTRATION:
        raise PitchFitError(f"--pitch auto: the best pitch ({pitch:.2f} voxels) leaves a winding concentration of "
                            f"{conc_best:.2f} (under {MIN_CONCENTRATION}); the grid does not follow one spiral about "
                            "this centre. Check the umbilicus, or give --pitch", "concentration")
    return {"pitch": pitch, "handedness": sgn, "concentration": conc_best, "other_handedness": other,
            "span_turns": span, "samples": int(idx.size), "range": list(prange)}


def _split_pairs(np, P, crank, T, th, sgn, gap, wtol, scan=SPLIT_SCAN, chunk=4096):
    """wind_audit's split contacts: (i, j, gap, dw) for i < j in different components, |p_i - p_j| <= gap and
    |dw| <= wtol, j among the `scan` highest-numbered vertices of its hash cell (cell = gap voxels)."""
    n = P.shape[0]
    empty = (np.zeros(0, np.int64),) * 2 + (np.zeros(0),) * 2
    if n < 2 or int(crank.max()) == int(crank.min()):
        return empty
    cell = np.floor(P / gap).astype(np.int64)
    cmin = cell.min(axis=0) - 1
    dims = cell.max(axis=0) - cmin + 2
    sc = cell - cmin
    key = (sc[:, 0] * dims[1] + sc[:, 1]) * dims[2] + sc[:, 2]
    deltas = [(dz * int(dims[1]) + dy) * int(dims[2]) + dx for dz in (-1, 0, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    ncomp = int(crank.max()) + 1
    pk = np.unique(key * ncomp + crank)
    pcell, pcomp = pk // ncomp, pk % ncomp
    cand_cell = np.zeros(pk.size, bool)
    for d in deltas:
        nk = pcell + d
        lo = np.searchsorted(pcell, nk, "left")
        hi = np.searchsorted(pcell, nk, "right")
        cnt = hi - lo
        other = (cnt >= 2) | ((cnt == 1) & (pcomp[np.minimum(lo, pk.size - 1)] != pcomp))
        cand_cell |= other
    cand = np.flatnonzero(np.isin(key, np.unique(pcell[cand_cell])))
    if cand.size == 0:
        return empty
    order = np.lexsort((-np.arange(n), key))
    ks = key[order]
    first = np.r_[True, ks[1:] != ks[:-1]]
    pos = np.arange(n) - np.maximum.accumulate(np.where(first, np.arange(n), 0))
    keep = pos < scan
    vis, vis_key = order[keep], ks[keep]
    gap2 = gap * gap
    out = [[], [], [], []]
    for c0 in range(0, cand.size, chunk):
        ci = cand[c0:c0 + chunk]
        for d in deltas:
            nk = key[ci] + d
            lo = np.searchsorted(vis_key, nk, "left")
            cnt = np.searchsorted(vis_key, nk, "right") - lo
            tot = int(cnt.sum())
            if not tot:
                continue
            ii = np.repeat(ci, cnt)
            jj = vis[np.repeat(lo - (np.cumsum(cnt) - cnt), cnt) + np.arange(tot)]
            sel = (jj > ii) & (crank[jj] != crank[ii])
            ii, jj = ii[sel], jj[sel]
            if not ii.size:
                continue
            d2 = ((P[ii] - P[jj]) ** 2).sum(axis=1)
            dw = (T[jj] - T[ii]) - sgn * _wrap_pmpi(np, th[jj] - th[ii]) / TWO_PI
            sel = (d2 <= gap2) & (np.abs(dw) <= wtol)
            for lst, arr in zip(out, (ii[sel], jj[sel], np.sqrt(d2[sel]), dw[sel])):
                lst.append(arr)
    if not out[0]:
        return empty
    return tuple(np.concatenate(lst) for lst in out)


def _grid_rc(order, W, idx):
    flat = order[idx]
    return [int(flat // W), int(flat % W)]


def wind_audit(surface, umbilicus=None, umbilicus_scale=1.0, centre=None, pitch="auto", pitch_table=None,
               handedness="auto", merge_tol=MERGE_TOL, split_wtol=SPLIT_WTOL, split_gap=SPLIT_GAP, split_audit=True,
               core_pitches=CORE_PITCHES, min_faces=MIN_FACES, local_span_tol=0.0, top=TOP, list_limit=200, png=None):
    """The winding-coordinate audit of a tifxyz surface; returns a JSON-ready report (see the module docstring)."""
    np = _numpy()
    for name, v in (("merge_tol", merge_tol), ("split_wtol", split_wtol), ("split_gap", split_gap)):
        if not v > 0:
            raise MeshQAError(f"{name} must be positive")
    if core_pitches < 0 or local_span_tol < 0:
        raise MeshQAError("core_pitches and local_span_tol must not be negative")
    if handedness not in ("auto", 1, -1, "1", "-1"):
        raise MeshQAError("handedness is auto, 1 or -1")
    if umbilicus is not None:
        try:
            axis = Axis(points=vc3d_orient.load_umbilicus(umbilicus, umbilicus_scale), label=str(umbilicus))
        except (vc3d_orient.OrientError, ValueError, OSError) as exc:
            raise MeshQAError(f"umbilicus: {exc}") from exc
    else:
        axis = Axis(centre=centre)
    patch = load_patch(surface)
    if patch.read_errors:
        raise MeshQAError(f"{surface}: {patch.read_errors}")
    if not patch.shapes_agree():
        raise MeshQAError(f"{surface}: x, y and z grids differ in shape")
    X, Y, Z = (np.asarray(a, dtype=np.float64) for a in (patch.x, patch.y, patch.z))
    loader_valid = patch.valid
    finite = np.isfinite(X) & np.isfinite(Y) & np.isfinite(Z)
    valid = loader_valid & finite
    H, W = X.shape
    if H < 2 or W < 2:
        raise MeshQAError(f"{surface}: a {H}x{W} grid has no quads")
    Q, cnt_h, cnt_v, order, cid = _grid_mesh(np, valid)
    n = order.size
    if n == 0:
        raise MeshQAError(f"{surface}: no quad of four valid vertices")
    on_mesh = cid >= 0
    px, py, pz = X.ravel()[order], Y.ravel()[order], Z.ravel()[order]
    cx, cy = axis.centre(np, pz)
    off_axis = ~(np.isfinite(cx) & np.isfinite(cy))
    if off_axis.any():     # NaN radii would make every dw NaN, no edge a merger, and the gate pass
        raise MeshQAError(f"{axis.describe()}: the axis is not finite at z {float(pz[off_axis][0]):.1f}; check the "
                          "umbilicus or --centre")
    ddx, ddy = px - cx, py - cy
    rad = np.hypot(ddy, ddx)
    th = np.arctan2(ddy, ddx)
    th_g = np.full(H * W, np.nan)
    th_g[order] = th
    thu_g, comp_g, ncomp, nruns = _unwrap(np, cnt_h, cnt_v, on_mesh, th_g.reshape(H, W))
    thu, comp0 = thu_g[order], comp_g[order]

    # components ranked by faces descending, as wind_audit does; ties by smallest vertex number, where wind_audit
    # uses its union-find root (union by size), so tied components can be numbered differently
    root = np.full(ncomp, n, np.int64)
    np.minimum.at(root, comp0, np.arange(n))
    qr, qc = np.nonzero(Q)
    faces0 = 2 * np.bincount(comp_g[qr * W + qc], minlength=ncomp)
    rank_order = np.lexsort((root, -faces0))
    rank_of = np.empty(ncomp, np.int64)
    rank_of[rank_order] = np.arange(ncomp)
    vrank = rank_of[comp0]
    faces = faces0[rank_order]

    # pitch and handedness
    pitch_info = {}
    if pitch_table is not None:
        gauge = PitchTable.load(pitch_table) if not isinstance(pitch_table, PitchTable) else pitch_table
        if pitch == "auto":
            scalar = float(gauge.pitch_at(float(np.median(rad))))
            pitch_info = {"source": "table at the median radius", "value": scalar}
        else:
            scalar = float(pitch)
            pitch_info = {"source": "given", "value": scalar}
    elif pitch == "auto":
        est = estimate_pitch(np, rad, thu, comp0, ncomp)
        scalar = est["pitch"]
        gauge = ScalarPitch(scalar)
        pitch_info = {"source": "auto (grid)", "value": scalar, "auto": est}
    else:
        scalar = float(pitch)
        gauge = ScalarPitch(scalar)
        pitch_info = {"source": "given", "value": scalar}
    if not scalar > 0:
        raise MeshQAError("pitch must be positive")
    T = gauge.turns_at(rad)
    if handedness in (1, -1, "1", "-1"):
        sgn, hand_src = int(handedness), "given"
    elif "auto" in pitch_info:
        sgn, hand_src = pitch_info["auto"]["handedness"], "auto (grid)"
    else:
        span = _span_turns(np, thu, comp0, ncomp)
        if span >= AUTO_HAND_MIN_TURNS:
            idx = _sample(np, n, PITCH_SAMPLES)
            cp, cm = (_concentration(np, T[idx], thu[idx], s) for s in (1, -1))
            sgn = 1 if cp >= cm else -1
            hand_src = f"auto (grid; concentration +1: {cp:.3f}, -1: {cm:.3f})"
        else:
            sgn, hand_src = 1, f"source default (the grid spans {span:.2f} turns, too little to tell)"
    core_r = core_pitches * scalar
    phase = T - sgn * thu / TWO_PI

    # edges of the OBJ mesh: horizontal, vertical, one diagonal per quad
    kinds = []
    rr, cc = np.nonzero(cnt_h)
    kinds.append(("h", cid[rr, cc], cid[rr, cc + 1], cnt_h[rr, cc]))
    rr, cc = np.nonzero(cnt_v)
    kinds.append(("v", cid[rr, cc], cid[rr + 1, cc], cnt_v[rr, cc]))
    rr, cc = np.nonzero(Q)
    kinds.append(("d", cid[rr + 1, cc], cid[rr, cc + 1], np.full(rr.size, 2, np.int8)))
    P = np.stack([px, py, pz], axis=1)
    hist = np.zeros(5, np.int64)
    edges_total = outer_edges = merge_outer = merge_core = full_turn = multi_turn = 0
    olen_sum = mlen_sum = mdr_sum = 0.0
    comp_edges = np.zeros(ncomp, np.int64)
    comp_full = np.zeros(ncomp, np.int64)
    beu, bev, flagged = [], [], []
    for kind, a, b, cnt in kinds:
        edges_total += a.size
        dw = (T[b] - T[a]) - sgn * _wrap_pmpi(np, th[b] - th[a]) / TWO_PI
        adw = np.abs(dw)
        ra, rb = rad[a], rad[b]
        outer = np.minimum(ra, rb) >= core_r
        length = np.linalg.norm(P[a] - P[b], axis=1)
        outer_edges += int(outer.sum())
        olen_sum += float(length[outer].sum())
        hist += np.bincount(np.searchsorted(HIST_EDGES, adw[outer], side="right"), minlength=5)
        merger = adw > merge_tol
        merge_outer += int((merger & outer).sum())
        merge_core += int((merger & ~outer).sum())
        mlen_sum += float(length[merger & outer].sum())
        mdr_sum += float(np.abs(rb - ra)[merger & outer].sum())
        full = outer & (adw >= FULL_TURN[0]) & (adw <= FULL_TURN[1])
        full_turn += int(full.sum())
        multi_turn += int((outer & (adw > FULL_TURN[1])).sum())
        comp_full += np.bincount(vrank[a][full], minlength=ncomp)
        comp_edges += np.bincount(vrank[a], minlength=ncomp)
        bnd = cnt == 1
        beu.append(a[bnd])
        bev.append(b[bnd])
        sel = np.flatnonzero(merger | full)
        if sel.size:
            flagged.append((kind, a[sel], b[sel], dw[sel], length[sel], outer[sel], full[sel]))

    # topology per component (V - E + F = 2 - 2g - b)
    beu, bev = np.concatenate(beu), np.concatenate(bev)
    bdeg = np.bincount(np.concatenate([beu, bev]), minlength=n)
    broot = union_min(np, n, beu, bev)
    onb = bdeg > 0
    loops = np.bincount(np.unique(vrank[onb] * n + broot[onb]) // n, minlength=ncomp)
    irregular = np.bincount(vrank[onb & (bdeg != 2)], minlength=ncomp)
    nverts = np.bincount(vrank, minlength=ncomp)
    chi = nverts - comp_edges + faces
    genus = 0.5 * (2.0 - loops - chi)

    def per_comp(values, mask=None, fn="min"):
        out = np.full(ncomp, np.inf if fn == "min" else -np.inf)
        sel = slice(None) if mask is None else mask
        (np.minimum if fn == "min" else np.maximum).at(out, vrank[sel], values[sel])
        return out

    rmin, rmax = per_comp(rad), per_comp(rad, fn="max")
    zmin, zmax = per_comp(pz), per_comp(pz, fn="max")
    outer_v = rad >= core_r
    pmin, pmax = per_comp(phase, outer_v), per_comp(phase, outer_v, fn="max")
    n_outer = np.bincount(vrank[outer_v], minlength=ncomp)
    grow, gcol = order // W, order % W
    gr0, gr1 = per_comp(grow), per_comp(grow, fn="max")
    gc0, gc1 = per_comp(gcol), per_comp(gcol, fn="max")
    turns_span = (gauge.turns_at(rmax) - gauge.turns_at(rmin))
    pspan = np.where(n_outer > 0, pmax - pmin, 0.0)

    broad = []
    if local_span_tol > 0:
        for k in range(ncomp):
            if faces[k] >= min_faces and rmin[k] >= core_r and n_outer[k] > 0 and pspan[k] > local_span_tol:
                broad.append(k)

    components = []
    for k in range(min(top, ncomp)):
        components.append({
            "rank": k, "faces": int(faces[k]), "face_pct": round(100.0 * faces[k] / max(1, faces.sum()), 2),
            "r_min": float(rmin[k]), "r_max": float(rmax[k]), "r_span": float(rmax[k] - rmin[k]),
            "turns": float(turns_span[k]), "phase_span": float(pspan[k]), "z_min": float(zmin[k]),
            "z_max": float(zmax[k]), "rows": [int(gr0[k]), int(gr1[k])], "cols": [int(gc0[k]), int(gc1[k])],
            "vertices": int(nverts[k]), "edges": int(comp_edges[k]), "boundary_loops": int(loops[k]),
            "boundary_irregular_vertices": int(irregular[k]), "euler_chi": int(chi[k]), "genus": float(genus[k]),
            "full_turn_fusions": int(comp_full[k]), "broad_fusion": k in broad})

    # flagged edges: full-turn first, then outer, then by |dw|
    edges_out, flag_rows, flag_cols, png_codes = [], [], [], None
    if png:
        png_codes = np.zeros(H * W, np.uint8)
        png_codes[order] = 60
    if flagged:
        kind_a = np.concatenate([np.full(f[1].size, "hvd".index(f[0])) for f in flagged])
        fa, fb, fdw, flen, fout, ffull = (np.concatenate([f[i] for f in flagged]) for i in range(1, 7))
        pri = np.lexsort((np.minimum(order[fa], order[fb]), -np.round(np.abs(fdw), 2), ~fout, ~ffull))
        for i in pri[:list_limit]:
            a, b = int(fa[i]), int(fb[i])
            edges_out.append({"kind": "hvd"[int(kind_a[i])], "a": _grid_rc(order, W, a), "b": _grid_rc(order, W, b),
                              "xyz": [float(v) for v in (P[a] + P[b]) / 2], "r": [float(rad[a]), float(rad[b])],
                              "dw": float(fdw[i]), "length": float(flen[i]), "outer": bool(fout[i]),
                              "full_turn": bool(ffull[i])})
        sel = ffull
        if sel.any():
            ends = np.concatenate([fa[sel], fb[sel]])
            flag_rows = [int(grow[ends].min()), int(grow[ends].max())]
            flag_cols = [int(gcol[ends].min()), int(gcol[ends].max())]
        if png_codes is not None:
            for mask_, code in ((~fout, 140), (fout, 200), (ffull, 255)):
                ends = np.concatenate([fa[mask_], fb[mask_]])
                png_codes[order[ends]] = np.maximum(png_codes[order[ends]], code)
    if png_codes is not None:
        Path(png).write_bytes(vc3d_io.png_bytes(H, W, bytes(png_codes)))

    splits = {"enabled": bool(split_audit), "pairs": 0, "component_pairs": 0, "top": []}
    if split_audit:
        ii, jj, gaps, sdw = _split_pairs(np, P, vrank, T, th, sgn, split_gap, split_wtol)
        splits["pairs"] = int(ii.size)
        if ii.size:
            lo, hi = np.minimum(vrank[ii], vrank[jj]), np.maximum(vrank[ii], vrank[jj])
            gk = lo * ncomp + hi
            uk, inv = np.unique(gk, return_inverse=True)
            cnt = np.bincount(inv)
            gsum = np.bincount(inv, weights=gaps)
            o = np.lexsort((gaps, inv))
            firsts = o[np.r_[True, inv[o][1:] != inv[o][:-1]]]
            splits["component_pairs"] = int(uk.size)
            for g in np.argsort(-cnt, kind="stable")[:top]:
                rep = firsts[g]
                i = int(ii[rep])
                splits["top"].append({"a": int(uk[g] // ncomp), "b": int(uk[g] % ncomp), "pairs": int(cnt[g]),
                                      "min_gap": float(gaps[rep]), "mean_gap": float(gsum[g] / cnt[g]),
                                      "representative": {"grid": _grid_rc(order, W, i), "xyz": [float(v) for v in P[i]],
                                                         "r": float(rad[i]), "dw": float(sdw[rep])}})

    local_failed = full_turn > 0 or multi_turn > 0 or len(broad) > 0
    return {
        "surface": str(surface), "axis": axis.describe(), "pitch": pitch_info, "gauge": gauge.describe(),
        "handedness": {"value": sgn, "source": hand_src}, "merge_tol": merge_tol, "split_wtol": split_wtol,
        "split_gap": split_gap, "core_radius": core_r, "grid": [H, W], "valid_vertices": int(loader_valid.sum()),
        "non_finite_dropped": int((loader_valid & ~finite).sum()), "mesh_vertices": int(n),
        "valid_without_quad": int((valid & ~on_mesh).sum()), "faces": int(faces.sum()), "components": int(ncomp),
        "row_runs": int(nruns), "unique_edges": int(edges_total),
        "mergers": {"outer": merge_outer, "core": merge_core, "outer_edges": outer_edges,
                    "outer_fraction": merge_outer / outer_edges if outer_edges else 0.0,
                    "histogram": dict(zip(HIST_LABELS, (int(v) for v in hist))),
                    "mean_len": mlen_sum / merge_outer if merge_outer else 0.0,
                    "mean_dr": mdr_sum / merge_outer if merge_outer else 0.0,
                    "outer_mean_len": olen_sum / outer_edges if outer_edges else 0.0,
                    "full_turn": full_turn, "multi_turn": multi_turn, "full_turn_rows": flag_rows,
                    "full_turn_cols": flag_cols,
                    "listed": edges_out, "boundary_edges": int(beu.size)},
        "broad_fusion": {"enabled": local_span_tol > 0, "tol": local_span_tol, "components": len(broad),
                         "faces": int(faces[broad].sum()) if broad else 0,
                         "max_span": float(pspan[broad].max()) if broad else 0.0},
        "component_table": components,
        "splits": splits,
        "gate": {"local_failed": bool(local_failed), "full_turn_fusions": full_turn, "multi_turn_skips": multi_turn,
                 "broad_fusions": len(broad)},
        "png": str(png) if png else None,
        "note": "A flagged edge crosses about one turn of winding in one step: a place to inspect, not proof of a "
                "sheet switch (a wrong umbilicus or pitch also moves dw). Not a reading of anything.",
    }


def format_wind(rep, top=TOP):
    m, lines = rep["mergers"], []
    ph = rep["pitch"]
    lines.append(f"wind_audit: {rep['surface']}")
    lines.append(f"  axis={rep['axis']}  pitch={ph['value']:.3f} ({ph['source']})  gauge={rep['gauge']}")
    if "auto" in ph:
        a = ph["auto"]
        lines.append(f"    auto pitch: concentration {a['concentration']:.3f} (other handedness {a['other_handedness']:.3f}), "
                     f"span {a['span_turns']:.2f} turns, {a['samples']} vertices sampled")
    lines.append(f"  handedness={rep['handedness']['value']:+d} ({rep['handedness']['source']})  "
                 f"merge_tol={rep['merge_tol']:.2f}  split_wtol={rep['split_wtol']:.2f}  split_gap={rep['split_gap']:.1f}"
                 f"  core<{rep['core_radius']:.1f} vox")
    lines.append(f"  grid={rep['grid'][0]}x{rep['grid'][1]}  valid={rep['valid_vertices']}  mesh verts={rep['mesh_vertices']}"
                 f"  faces={rep['faces']}  components={rep['components']}  unique_edges={rep['unique_edges']}"
                 + (f"  non-finite dropped={rep['non_finite_dropped']}" if rep["non_finite_dropped"] else ""))
    lines.append("")
    lines.append(f"  == MERGERS (radial short-circuits, |dw|>{rep['merge_tol']:.2f} across one edge) ==")
    pct = 100.0 * m["outer_fraction"]
    lines.append(f"    outer (r>={rep['core_radius']:.0f}, reliable): {m['outer']} edges ({pct:.2f}% of {m['outer_edges']} outer)"
                 f"    core (r<{rep['core_radius']:.0f}): {m['core']} edges")
    lines.append("    outer |dw| histogram:  " + "  ".join(f"{k}={v}" for k, v in m["histogram"].items()))
    lines.append(f"    merger-edge geometry:  mean_len={m['mean_len']:.2f} vox  mean|dr|={m['mean_dr']:.2f} vox   "
                 f"(all outer edges mean_len={m['outer_mean_len']:.2f} vox; pitch={ph['value']:.2f})")
    lines.append(f"    FULL-TURN fusions (|dw| in [0.7,1.3], the reliable count): {m['full_turn']}"
                 + (f"   grid rows {m['full_turn_rows']} cols {m['full_turn_cols']}" if m["full_turn"] else ""))
    lines.append(f"    MULTI-TURN skips (|dw| > 1.3, gated here, not in the source): {m.get('multi_turn', 0)}")
    for k, e in enumerate([e for e in m["listed"] if e["full_turn"]][:8], 1):
        lines.append(f"      #{k} {e['kind']} edge grid {e['a']}->{e['b']} at (x {e['xyz'][0]:.0f}, y {e['xyz'][1]:.0f}, "
                     f"z {e['xyz'][2]:.0f})  r {e['r'][0]:.1f}->{e['r'][1]:.1f}  dw={e['dw']:+.2f} len={e['length']:.1f}")
    lines.append(f"    mesh boundary edges: {m['boundary_edges']}")
    bf = rep["broad_fusion"]
    if bf["enabled"]:
        lines.append("")
        lines.append(f"  == BROAD FUSIONS (adjacency-unwrapped phase span > {bf['tol']:.2f} turns) ==")
        lines.append(f"    wholly-outer components: {bf['components']}  faces involved: {bf['faces']}  "
                     f"max phase span: {bf['max_span']:.3f} turns")
    lines.append("")
    lines.append(f"  == COMPONENTS (top {top} by faces) ==")
    lines.append(f"    {'rank':<4} {'faces':>10} {'%':>6}   {'r_min':>8} {'r_max':>8} {'r_span':>8}  {'turns':>8} "
                 f"{'phase':>8}  {'z_min':>8} {'z_max':>8}   {'topology V/E/b/chi/g':<23} ft_fusions")
    for c in rep["component_table"][:top]:
        topo = f"{c['vertices']}/{c['edges']}/{c['boundary_loops']}/{c['euler_chi']}/{c['genus']:.1f}"
        lines.append(f"    #{c['rank']:<3} {c['faces']:>10} {c['face_pct']:>5.1f}%   {c['r_min']:>8.1f} {c['r_max']:>8.1f} "
                     f"{c['r_span']:>8.1f}  {c['turns']:>8.2f} {c['phase_span']:>8.2f}  {c['z_min']:>8.0f} {c['z_max']:>8.0f}"
                     f"   {topo:<23} {c['full_turn_fusions']}")
    s = rep["splits"]
    lines.append("")
    lines.append(f"  == SPLIT CONTACTS (same-turn |dw|<={rep['split_wtol']:.2f}, gap<={rep['split_gap']:.1f} vox, "
                 "DIFFERENT components) ==")
    if not s["enabled"]:
        lines.append("    disabled")
    else:
        lines.append(f"    diagnostic vertex pairs: {s['pairs']}   distinct component-pairs: {s['component_pairs']}")
        lines.append("    NOTE: proximity density is not a missing-seam count.")
        for g in s["top"][:top]:
            rp = g["representative"]
            lines.append(f"    #{g['a']}<->#{g['b']} pairs={g['pairs']} min_gap={g['min_gap']:.2f} mean_gap={g['mean_gap']:.2f}"
                         f"   grid {rp['grid']} r={rp['r']:.0f} dw={rp['dw']:+.3f}")
    gate = rep["gate"]
    lines.append("")
    lines.append(f"  local gate: {'FAIL' if gate['local_failed'] else 'pass'} ({gate['full_turn_fusions']} full-turn "
                 f"fusions, {gate.get('multi_turn_skips', 0)} multi-turn skips, {gate['broad_fusions']} broad fusions)")
    if rep.get("png"):
        lines.append(f"  wrote {rep['png']} (grey: mesh, 140: core merger, 200: outer merger, 255: full-turn edge ends)")
    lines.append(f"  {rep['note']}")
    return "\n".join(lines)


def run_windaudit(args):
    pitch = args.pitch
    if pitch != "auto":
        try:
            pitch = float(pitch)
        except ValueError:
            raise MeshQAError(f"--pitch is a number of voxels or auto, not {args.pitch!r}") from None
        if not pitch > 0:
            raise MeshQAError("--pitch must be positive")
    rep = wind_audit(args.surface, umbilicus=args.umbilicus, umbilicus_scale=args.umbilicus_scale, centre=args.centre,
                     pitch=pitch, pitch_table=args.pitch_table, handedness=args.handedness, merge_tol=args.merge_tol,
                     split_wtol=args.split_wtol, split_gap=args.split_gap, split_audit=not args.no_split_audit,
                     core_pitches=args.core_pitches, min_faces=args.min_faces, local_span_tol=args.local_span_tol,
                     top=args.top, list_limit=args.list, png=args.png)
    print(json.dumps(rep, indent=2) if args.json else format_wind(rep, args.top))
    return 4 if (args.fail_on_local and rep["gate"]["local_failed"]) else 0


# ================================================================ predcubes (ScrollFiesta pred_reject)

GARBAGE_ERODE_R = 2
GARBAGE_ERODE_MAXPASS = 16
GARBAGE_INTERIOR_FRAC = _f32(0.50)
GARBAGE_INTERIOR_MIN = 2000
GARBAGE_RECT_AREA_FRAC = _f32(0.10)
GARBAGE_RECT_FILL = _f32(0.75)
GARBAGE_RECT_FRAC = _f32(0.20)
GARBAGE_RECT_RUN = 12
MIN_CC_SIZE = 500
CUBE = 128
CSV_COLUMNS = ("cube_id", "verdict", "fill_frac", "interior_frac", "interior_count", "max_thickness", "rect_axis",
               "rect_frac", "max_rect_run", "reason", "largest_cc", "empty", "partial")


def erode6(np, src):
    """dst = src and all six face neighbours set; out-of-bounds neighbours are background. (dst, survivors)."""
    dst = np.zeros_like(src)
    if min(src.shape) >= 3:
        c = src[1:-1, 1:-1, 1:-1]
        dst[1:-1, 1:-1, 1:-1] = (c & src[:-2, 1:-1, 1:-1] & src[2:, 1:-1, 1:-1] & src[1:-1, :-2, 1:-1]
                                 & src[1:-1, 2:, 1:-1] & src[1:-1, 1:-1, :-2] & src[1:-1, 1:-1, 2:])
    return dst, int(dst.sum())


def _label(np, fg, idx, axes):
    """Root (smallest foreground index, which is raster order) of every foreground voxel, joined along `axes`."""
    shape = fg.shape
    cmap = np.full(fg.size, -1, np.int64)
    cmap[idx] = np.arange(idx.size)
    strides = (shape[1] * shape[2], shape[2], 1)
    eu, ev = [], []
    for ax in axes:
        if shape[ax] < 2:
            continue
        lo = [slice(None)] * 3
        hi = [slice(None)] * 3
        lo[ax], hi[ax] = slice(0, -1), slice(1, None)
        pair = np.zeros(shape, bool)
        pair[tuple(lo)] = fg[tuple(lo)] & fg[tuple(hi)]
        u = np.flatnonzero(pair)
        eu.append(cmap[u])
        ev.append(cmap[u + strides[ax]])
    if not eu:
        return np.arange(idx.size, dtype=np.int64)
    return union_min(np, idx.size, np.concatenate(eu), np.concatenate(ev))


def largest_cc6(np, fg, idx=None):
    idx = np.flatnonzero(fg) if idx is None else idx
    if idx.size == 0:
        return 0
    return int(np.bincount(_label(np, fg, idx, (0, 1, 2))).max())


def axis_rect_scan(np, fg, idx, axis):
    """(fraction of slices along `axis` that are solid-rectangle frames, longest run of consecutive ones)."""
    plane = tuple(a for a in range(3) if a != axis)
    n_slices = fg.shape[axis]
    slice_area = float(fg.shape[plane[0]] * fg.shape[plane[1]])
    rect = np.zeros(n_slices, bool)
    if idx.size:
        roots = _label(np, fg, idx, plane)
        uniq, inv = np.unique(roots, return_inverse=True)
        area = np.bincount(inv)
        coords = np.unravel_index(idx, fg.shape)
        a_c, b_c = coords[plane[0]], coords[plane[1]]
        big = np.iinfo(np.int64).max
        amin, bmin = np.full(uniq.size, big), np.full(uniq.size, big)
        amax, bmax = np.full(uniq.size, -1), np.full(uniq.size, -1)
        np.minimum.at(amin, inv, a_c)
        np.maximum.at(amax, inv, a_c)
        np.minimum.at(bmin, inv, b_c)
        np.maximum.at(bmax, inv, b_c)
        fill = area / ((amax - amin + 1) * (bmax - bmin + 1)).astype(np.float64)
        sl = coords[axis][uniq]                    # every voxel of a slice component shares its slice index
        o = np.lexsort((uniq, -area, sl))          # per slice: largest, then first met by the raster scan
        best = o[np.r_[True, sl[o][1:] != sl[o][:-1]]]
        ok = (area[best] / slice_area >= GARBAGE_RECT_AREA_FRAC) & (fill[best] >= GARBAGE_RECT_FILL)
        rect[sl[best][ok]] = True
    run = max_run = 0
    for v in rect.tolist():
        run = run + 1 if v else 0
        max_run = max(max_run, run)
    return (float(rect.sum()) / n_slices if n_slices else 0.0), max_run


def pred_reject(vol, threshold=None):
    """PredReject_is_garbage on one cube: a dict of the source's stats; verdict 1 = reject, empty 1 = EMPTY garbage."""
    np = _numpy()
    a = np.asarray(vol)
    if a.ndim != 3 or min(a.shape) < 1:
        raise MeshQAError(f"a prediction cube is a non-empty 3-D array, got shape {a.shape}")
    fg = (a != 0) if threshold is None else (a >= threshold)
    fg = np.ascontiguousarray(fg)
    st = {"n_vox": int(a.size), "fg_count": 0, "largest_cc": 0, "fill_frac": 0.0, "interior_count": 0,
          "interior_frac": 0.0, "max_thickness": 0, "rect_axis": 0, "rect_frac": 0.0, "max_rect_run": 0,
          "verdict": 0, "empty": 0, "reason": "keep"}
    idx = np.flatnonzero(fg)
    st["fg_count"] = int(idx.size)
    st["fill_frac"] = idx.size / a.size
    st["largest_cc"] = largest_cc6(np, fg, idx)
    if st["largest_cc"] < MIN_CC_SIZE:
        st.update(verdict=1, empty=1, reason="reject: empty (no meshable component)")
        return st
    cur, count, st["max_thickness"] = fg, idx.size, 1
    for p in range(1, GARBAGE_ERODE_MAXPASS + 1):
        if count <= 0:
            break
        cur, count = erode6(np, cur)
        if count > 0:
            st["max_thickness"] = p + 1
        if p == GARBAGE_ERODE_R:
            st["interior_count"] = count
    st["interior_frac"] = st["interior_count"] / idx.size
    any_rect, st["max_rect_run"] = False, -1
    for axis in range(3):
        frac, run = axis_rect_scan(np, fg, idx, axis)
        if frac >= GARBAGE_RECT_FRAC and run >= GARBAGE_RECT_RUN:
            any_rect = True
        if run > st["max_rect_run"]:
            st.update(max_rect_run=run, rect_frac=frac, rect_axis=axis)
    st["max_rect_run"] = max(0, st["max_rect_run"])
    thick = st["interior_frac"] >= GARBAGE_INTERIOR_FRAC and st["interior_count"] >= GARBAGE_INTERIOR_MIN
    if thick and any_rect:
        st.update(verdict=1, reason="reject: solid slab")
    elif not thick:
        st["reason"] = "keep: thin (low erosion interior)"
    else:
        st["reason"] = "keep: not a persistent rectangle"
    return st


def cube_boxes(shape, box, cube=CUBE):
    """[[z0, z1], [y0, y1], [x0, x1]] of every cube of the absolute grid of `cube` voxels that meets the box, cut by
    the array's edge."""
    box = box or [[0, s] for s in shape]
    lims = [(max(0, int(a)), min(int(s), int(b))) for (a, b), s in zip(box, shape)]
    if any(b <= a for a, b in lims):
        return []
    ranges = [range(a // cube * cube, b, cube) for a, b in lims]
    return [[[z, min(z + cube, shape[0])], [y, min(y + cube, shape[1])], [x, min(x + cube, shape[2])]]
            for z in ranges[0] for y in ranges[1] for x in ranges[2]]


def cube_id(b):
    return f"z{b[0][0]:05d}_y{b[1][0]:05d}_x{b[2][0]:05d}"


def _open_volume(location, level):
    """(shape, reader(box) -> array, description) for a zarr (local or remote), .npy or .tif."""
    np = _numpy()
    text = str(location)
    low = text.lower()
    if low.endswith(".npy"):
        arr = np.load(text, mmap_mode="r", allow_pickle=False)
    elif low.endswith((".tif", ".tiff")):
        tf = _tifffile()
        if tf is None:
            raise MeshQAError("reading a .tif cube needs tifffile")
        arr = tf.imread(text)
    else:
        from .vc3d_region import RegionError, Volume
        try:
            vol = Volume(text)
            shape = vol.shape(level)
        except Exception as exc:  # noqa: BLE001 - open_store and levels raise several types
            raise MeshQAError(f"{location}: cannot open as zarr ({exc})") from exc
        if len(shape) != 3:
            raise MeshQAError(f"{location} level {level}: expected a 3-D array, got shape {shape}")

        def read(b):
            try:
                return vol.read(level, b)
            except RegionError as exc:
                raise MeshQAError(str(exc)) from exc
        return shape, read, f"zarr {location} level {level}"
    if arr.ndim != 3:
        raise MeshQAError(f"{location}: expected a 3-D array, got shape {arr.shape}")
    return list(arr.shape), (lambda b: np.asarray(arr[b[0][0]:b[0][1], b[1][0]:b[1][1], b[2][0]:b[2][1]])), text


def pred_cubes(location, level=0, box=None, cube=CUBE, threshold=None, max_cubes=512):
    if cube < 3:
        raise MeshQAError("--cube must be at least 3 voxels")
    shape, read, desc = _open_volume(location, level)
    boxes = cube_boxes(shape, box, cube)
    if not boxes:
        raise MeshQAError(f"the box {box} does not meet the array (shape z, y, x {shape})")
    if len(boxes) > max_cubes:
        raise MeshQAError(f"{len(boxes)} cubes of {cube} voxels meet the box; narrow --box or raise --max-cubes "
                          f"(now {max_cubes})")
    cubes = []
    for b in boxes:
        rec = {"cube_id": cube_id(b), "box": b, "partial": any(hi - lo < cube for lo, hi in b)}
        try:
            rec.update(pred_reject(read(b), threshold))
        except MeshQAError as exc:
            rec.update(error=str(exc))
        cubes.append(rec)
    ok = [c for c in cubes if "error" not in c]
    counts = {"cubes": len(cubes), "reject": sum(c["verdict"] for c in ok),
              "reject_slab": sum(c["verdict"] and not c["empty"] for c in ok), "reject_empty": sum(c["empty"] for c in ok),
              "keep": sum(not c["verdict"] for c in ok), "error": len(cubes) - len(ok)}
    return {"location": desc, "shape": shape, "box": box, "cube": cube,
            "threshold": "nonzero" if threshold is None else threshold, "counts": counts, "cubes": cubes,
            "note": "A rejected cube is a prediction that is not a thin sheet (a solid slab) or has no meshable "
                    "component; thresholds calibrated on 128-voxel PHerc0139 cubes (Community report, ScrollFiesta)."}


def format_cube(c):
    if "error" in c:
        return f"{c['cube_id']:<30} error: {c['error']}"
    return (f"{c['cube_id']:<30} fg={c['fg_count']:<7} cc={c['largest_cc']:<7} fill={c['fill_frac']:.4f} "
            f"interior={c['interior_frac']:.3f}({c['interior_count']}) thick={c['max_thickness']} "
            f"rect[ax{c['rect_axis']}]={c['rect_frac']:.2f} run={c['max_rect_run']:<3}  {c['reason']}"
            + ("  [partial]" if c["partial"] else ""))


def run_predcubes(args):
    box = None
    if args.box:
        z0, z1, y0, y1, x0, x1 = args.box
        box = [[z0, z1], [y0, y1], [x0, x1]]
    rep = pred_cubes(args.location, level=args.level, box=box, cube=args.cube, threshold=args.threshold,
                     max_cubes=args.max_cubes)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        for c in rep["cubes"]:
            print(format_cube(c))
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_COLUMNS)
            for c in rep["cubes"]:
                if "error" in c:
                    continue
                w.writerow([c["cube_id"], c["verdict"], f"{c['fill_frac']:.4f}", f"{c['interior_frac']:.4f}",
                            c["interior_count"], c["max_thickness"], c["rect_axis"], f"{c['rect_frac']:.4f}",
                            c["max_rect_run"], c["reason"], c["largest_cc"], c["empty"], int(c["partial"])])
    if args.out:
        Path(args.out).write_text("".join(c["cube_id"] + "\n" for c in rep["cubes"] if c.get("verdict")))
    k = rep["counts"]
    print(f"scan: {k['cubes']} cubes -> {k['reject']} REJECT ({k['reject_slab']} slab, {k['reject_empty']} empty), "
          f"{k['keep']} keep, {k['error']} err", file=sys.stderr)
    return 1 if k["error"] else 0


# ================================================================ support (villa PR #1906, reimplemented)

# Defaults of villa PR #1906 (AleksaGavric, "vc_grow_seg_from_seed: post-growth on-prediction support check", open
# on 12 Oct 2026, head 681b086; Community report): 0.4 minimum share, 0.1 margin above the background share, 2000
# background points from a fixed seed in the surface's bounding box dilated by 64 voxels. That PR reports good
# (sheet-following) patches at 44.8 to 62.7 % and bad (swirl) patches at 25.9 to 34.8 % over a background near 20 %
# on 65 eye-labelled patches from 21 scrolls, with only 5 good patches: starting points, not validated thresholds.
# The code below is written here from that description (villa's volume-cartographer is GPL-3.0; nothing is copied).
SUPPORT_MIN_SHARE = 0.4
SUPPORT_MARGIN = 0.1
SUPPORT_BG_POINTS = 2000
SUPPORT_BG_DILATE = 64
SUPPORT_SEED = 42
# vc_grow_seg_from_seed's own on-prediction test (kit/vc3d_prep.py SURFACE_THRESHOLD); #1906 counts any nonzero.
SUPPORT_THRESHOLD = 128
SUPPORT_MAX_POINTS = 200000


def _lookup(vol, level, zyx):
    """Nearest-voxel values at integer (z, y, x) points of a level, read chunk by chunk (a chunk absent from the
    store reads the array's fill value, as zarr defines it). NaN outside the array."""
    np = _numpy()
    meta = vol.levels[level]["meta"]
    ch = np.array(meta["chunks"], dtype=np.int64)
    shape = np.array(meta["shape"], dtype=np.int64)
    fill = meta.get("fill_value")
    fill = float(fill) if isinstance(fill, (int, float)) and fill == fill else 0.0
    out = np.full(len(zyx), np.nan)
    inside = np.all((zyx >= 0) & (zyx < shape), axis=1)
    idx = np.nonzero(inside)[0]
    if not idx.size:
        return out
    from .vc3d_region import chunk_groups
    keys, order, bounds = chunk_groups(zyx[idx] // ch)
    for k, c in enumerate(keys):
        sel = idx[order[bounds[k]:bounds[k + 1]]]
        arr = vol._chunk(level, tuple(int(v) for v in c))
        if arr is None:
            out[sel] = fill
            continue
        loc = zyx[sel] - c * ch
        out[sel] = arr[loc[:, 0], loc[:, 1], loc[:, 2]]
    return out


def _on_share(vol, level, pts, dirs, threshold, within):
    """Share of points (x, y, z, level 0) whose prediction reads >= threshold at some integer offset |d| <= within
    along their direction (nearest voxel); points whose every sample falls outside the array are left out.
    `share` is rounded for display; `on` and `points` give the exact fraction."""
    np = _numpy()
    offs = np.arange(-int(within), int(within) + 1, dtype=float)
    samp = pts[:, None, :] + offs[None, :, None] * dirs[:, None, :]
    if level:
        samp = vol.to_level(level, samp.reshape(-1, 3)).reshape(samp.shape)
    zyx = np.rint(samp[..., ::-1]).astype(np.int64).reshape(-1, 3)
    vals = _lookup(vol, level, zyx).reshape(len(pts), len(offs))
    seen = ~np.all(np.isnan(vals), axis=1)
    on = np.any(np.nan_to_num(vals, nan=-np.inf) >= threshold, axis=1)
    n = int(seen.sum())
    return {"points": n, "outside": int(len(pts) - n), "on": int((on & seen).sum()),
            "share": round(float((on & seen).sum()) / n, 4) if n else None}


def _frac(d):
    """The exact on-prediction fraction of an _on_share result (None when nothing was sampled)."""
    return d["on"] / d["points"] if d.get("points") else None


def surface_support(X, Y, Z, vol, level=0, threshold=SUPPORT_THRESHOLD, within=0, stride=1,
                    background=SUPPORT_BG_POINTS, dilate=SUPPORT_BG_DILATE, seed=SUPPORT_SEED, shift=0.0,
                    min_share=SUPPORT_MIN_SHARE, margin=SUPPORT_MARGIN, max_points=SUPPORT_MAX_POINTS):
    """On-prediction support of a tifxyz grid (X, Y, Z in level-0 voxels of the prediction's scan) against the
    background rate: the same share for `background` uniform random points in the valid vertices' bounding box
    dilated by `dilate` voxels (clipped to the volume; each random point searches along a random direction when
    within > 0). With `shift`, also the share of the surface moved `shift` voxels along its grid normal, compared
    with the unmoved share on the same vertices: a control that should score lower when the shift is about half
    the sheet spacing and more than within plus half a sheet's thickness. Report only: `verdict` is "pass" or
    "warn" with reasons, never a statement about ink. As in villa PR #1906, a background that was not measured
    (off, or a box outside the volume) is reported and adds no warning."""
    np = _numpy()
    if background < 0 or within < 0 or stride < 1 or not (math.isfinite(dilate) and dilate >= 0):
        raise MeshQAError("background and within must be 0 or more, stride 1 or more, and dilate a finite number "
                          "of voxels, 0 or more")
    if not (math.isfinite(threshold) and math.isfinite(shift)):
        raise MeshQAError("threshold and shift must be finite")
    X, Y, Z = (np.asarray(a, dtype=np.float64) for a in (X, Y, Z))
    full = np.isfinite(X) & np.isfinite(Y) & np.isfinite(Z) & (X != -1) & (Z > 0)
    valid = full.copy()
    if stride > 1:
        keep = np.zeros_like(valid)
        keep[::stride, ::stride] = True
        valid &= keep
    P = np.stack([X, Y, Z], axis=-1)
    dr = np.zeros_like(P)
    dc = np.zeros_like(P)
    dr[1:-1] = P[2:] - P[:-2]
    dc[:, 1:-1] = P[:, 2:] - P[:, :-2]
    with np.errstate(invalid="ignore"):
        n = np.cross(dr, dc)
        nn = np.linalg.norm(n, axis=-1)
    has_n = np.zeros_like(full)
    has_n[1:-1, 1:-1] = full[2:, 1:-1] & full[:-2, 1:-1] & full[1:-1, 2:] & full[1:-1, :-2]
    has_n &= np.isfinite(nn) & (nn > 0)
    idx = np.argwhere(valid)
    if not len(idx):
        raise MeshQAError("the surface has no valid vertices")
    rng = np.random.default_rng(seed)
    if len(idx) > max_points:
        idx = idx[np.sort(rng.choice(len(idx), max_points, replace=False))]
    pts = P[idx[:, 0], idx[:, 1]]
    nrm = np.zeros_like(pts)
    hn = has_n[idx[:, 0], idx[:, 1]]
    nrm[hn] = n[idx[hn, 0], idx[hn, 1]] / nn[idx[hn, 0], idx[hn, 1]][:, None]
    if within > 0:                      # the search along the normal needs a normal; the plain share does not
        pts, nrm, hn = pts[hn], nrm[hn], hn[hn]
    if not len(pts) or (shift and not hn.any()):
        raise MeshQAError("no valid vertex has a grid normal (all four neighbours valid)")
    res = {"points_sampled": int(len(pts)), "threshold": threshold, "within": within, "level": level,
           "surface": _on_share(vol, level, pts, nrm, threshold, within)}
    shape0 = np.array(vol.shape(0)[::-1], dtype=float)          # x, y, z extent of level 0
    lo = np.maximum(pts.min(axis=0) - dilate, 0.0)
    hi = np.minimum(pts.max(axis=0) + dilate, shape0 - 1)
    res["background"] = {"points": 0, "share": None, "box_xyz": [lo.round(1).tolist(), hi.round(1).tolist()],
                         "seed": seed}
    if not background:
        res["background"]["unavailable"] = "off (background 0)"
    elif not np.all(hi >= lo):
        res["background"]["unavailable"] = "the dilated box does not meet the volume"
    else:
        bpts = rng.uniform(lo, hi, size=(int(background), 3))
        bdir = rng.normal(size=(int(background), 3))
        bdir /= np.linalg.norm(bdir, axis=1, keepdims=True)
        res["background"].update(_on_share(vol, level, bpts, bdir, threshold, within))
    if shift:
        base = _on_share(vol, level, pts[hn], nrm[hn], threshold, within)
        res["shifted"] = dict(_on_share(vol, level, pts[hn] + shift * nrm[hn], nrm[hn], threshold, within),
                              shift=shift, unshifted_share=base["share"], unshifted_points=base["points"])
    share, bg = _frac(res["surface"]), _frac(res["background"])
    reasons = []
    if share is None:
        reasons.append("no sampled vertex lies inside the prediction volume")
    else:
        if share < min_share:
            reasons.append(f"support {share:.4f} is under {min_share}: the surface may cut across windings")
        if bg is not None:
            res["margin_above_background"] = round(share - bg, 4)
            if share <= bg + margin:            # #1906's noBetterThanChance: support <= background + margin
                reasons.append(f"support {share:.4f} is no more than {margin} above the background {bg:.4f}: no "
                               "better than random points in its neighbourhood")
        if shift:
            sh, b0 = _frac(res["shifted"]), _frac(base)
            res["shifted"]["caught"] = sh is not None and b0 is not None and b0 > sh + margin
            if not res["shifted"]["caught"] and share >= min_share:
                reasons.append(f"the surface moved {shift} voxels along its normal still scores {res['shifted']['share']}: "
                               "the prediction does not discriminate at this offset, or the offset reaches a sheet "
                               "(a multiple of the sheet spacing, or not beyond within plus half the sheet "
                               "thickness), so this check cannot fail here")
    res.update(min_share=min_share, margin=margin, verdict="warn" if reasons else "pass", reasons=reasons,
               chunks_read=vol.chunks_read, chunks_absent=vol.missing)
    return res


def run_support(args):
    _numpy()
    from . import vc3d_prep, vc3d_region
    for name in ("min_share", "margin"):
        v = getattr(args, name)
        if not (v == v and 0.0 <= v <= 1.0):
            raise MeshQAError(f"--{name.replace('_', '-')} must be within [0, 1], got {v}")
    for name, low in (("background", 0), ("within", 0), ("stride", 1), ("dilate", 0)):
        v = getattr(args, name)
        if not (math.isfinite(v) and v >= low):
            raise MeshQAError(f"--{name} must be {low} or more, got {v}")
    try:
        X, Y, Z = vc3d_prep._read_xyz(args.surface)
    except (vc3d_prep.PrepError, ValueError) as exc:
        raise MeshQAError(f"{args.surface}: {exc}") from exc
    try:
        vol = vc3d_region.Volume(args.prediction, cache_chunks=args.cache_chunks)
    except ValueError as exc:                    # AuditError and RegionError are ValueErrors
        raise MeshQAError(f"{args.prediction}: cannot open as zarr ({exc})") from exc
    if not 0 <= args.level < len(vol.levels):
        raise MeshQAError(f"level {args.level} is not in the prediction ({len(vol.levels)} levels)")
    if len(vol.shape(args.level)) != 3:
        raise MeshQAError(f"{args.prediction} level {args.level}: expected a 3-D array, got shape "
                          f"{vol.shape(args.level)}")
    try:
        rep = surface_support(X, Y, Z, vol, level=args.level, threshold=args.threshold, within=args.within,
                              stride=args.stride, background=args.background, dilate=args.dilate, seed=args.seed,
                              shift=args.shift, min_share=args.min_share, margin=args.margin)
    except vc3d_region.RegionError as exc:       # a sharded, filtered, undecodable or unfetchable chunk
        raise MeshQAError(str(exc)) from exc
    rep["surface_path"], rep["prediction"] = str(args.surface), str(args.prediction)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        s, b = rep["surface"], rep["background"]
        bg = (f"background {b['share']} over {b['points']} points" if b["share"] is not None
              else f"background unavailable ({b.get('unavailable', 'nothing sampled inside the volume')})")
        line = f"support {s['share']} ({s['on']}/{s['points']}), {bg}"
        if "shifted" in rep:
            line += (f", moved {rep['shifted']['shift']} vx: {rep['shifted']['share']} "
                     f"(unmoved {rep['shifted']['unshifted_share']} on the same vertices)")
        print(f"{line}: {rep['verdict']}")
        for r in rep["reasons"]:
            print(f"  {r}")
    return 3 if args.strict and rep["verdict"] != "pass" else 0


# ================================================================ command line

def build_parser(p):
    p.description = ("Mesh and prediction checks. validity: which tifxyz vertices VC3D's loader keeps and the bbox it "
                     "would derive (tifxyz-repair); windaudit: edges whose winding coordinate jumps by about one turn "
                     "(ScrollFiesta wind_audit); predcubes: solid-slab or empty surface-prediction cubes (ScrollFiesta "
                     "pred_reject); certify: certified cells, largest certified square and fibre score (Pellerano); crop: the clean "
                     "pieces of a trace written as VC3D tifxyz folders (kit/regioncrop.py). Flagged items are places to "
                     "inspect, never readings.")
    act = p.add_subparsers(dest="action", required=True)

    v = act.add_parser("validity", help="VC3D loader validity (z <= 0, mask.tif, x == -1), stale bbox, sidecar checks")
    v.add_argument("paths", nargs="+", help="tifxyz folders, or folders to search for them")
    v.add_argument("--json", action="store_true", help="print JSON")
    v.add_argument("-v", "--verbose", action="store_true", help="also show info findings")
    v.add_argument("--fix", metavar="OUT", help="write a corrected copy to OUT (OUT/<relative path> for a tree, "
                                                "OUT/<name> for each of several patches); the source is never "
                                                "modified")
    v.add_argument("--strip-bbox", action="store_true", help="with --fix: remove the bbox instead of recomputing it")
    v.add_argument("--bake-invalid", action="store_true",
                   help="with --fix: also write -1 into x, y, z of every vertex VC3D drops")
    v.add_argument("--overwrite", action="store_true", help="with --fix: replace an existing tifxyz or empty OUT")

    w = act.add_parser("windaudit", help="winding-coordinate audit of a tifxyz: mergers (sheet switches), components, "
                                         "split contacts, broad fusions")
    w.add_argument("surface", help="tifxyz folder")
    g = w.add_mutually_exclusive_group(required=True)
    g.add_argument("--umbilicus", metavar="FILE", help="villa umbilicus (text z, y, x lines or JSON)")
    g.add_argument("--centre", nargs=2, type=float, metavar=("X", "Y"), help="fixed axis position")
    w.add_argument("--umbilicus-scale", type=float, default=1.0, help="multiply umbilicus coordinates (other binning)")
    w.add_argument("--pitch", default="auto", help="voxels between wraps, or auto (estimated from the grid; default)")
    w.add_argument("--pitch-table", metavar="CSV", help="measured pitch table r,pitch[,count]")
    w.add_argument("--handedness", choices=("auto", "1", "-1"), default="auto",
                   help="sign s in w = r/pitch - s theta/2pi (the source assumes 1)")
    w.add_argument("--merge-tol", type=float, default=MERGE_TOL)
    w.add_argument("--split-wtol", type=float, default=SPLIT_WTOL)
    w.add_argument("--split-gap", type=float, default=SPLIT_GAP)
    w.add_argument("--no-split-audit", action="store_true")
    w.add_argument("--core-pitches", type=float, default=CORE_PITCHES)
    w.add_argument("--min-faces", type=int, default=MIN_FACES)
    w.add_argument("--local-span-tol", type=float, default=0.0, help="broad-fusion phase-span gate in turns (0: off)")
    w.add_argument("--fail-on-local", action="store_true", help="exit 4 when full-turn or broad fusions are found")
    w.add_argument("--top", type=int, default=TOP)
    w.add_argument("--list", type=int, default=200, help="flagged edges listed in the JSON")
    w.add_argument("--png", metavar="OUT.png", help="grid-sized map of flagged edge ends")
    w.add_argument("--json", action="store_true", help="print JSON")

    c = act.add_parser("predcubes", help="garbage surface-prediction cubes: solid slabs or empty")
    c.add_argument("location", help="zarr folder or URL (s3:// or https://), or a .npy/.tif cube")
    c.add_argument("--level", type=int, default=0)
    c.add_argument("--box", nargs=6, type=int, metavar=("Z0", "Z1", "Y0", "Y1", "X0", "X1"),
                   help="region in voxels of the level (default: the whole array)")
    c.add_argument("--cube", type=int, default=CUBE, help="cube edge in voxels on the absolute grid (default 128)")
    c.add_argument("--threshold", type=float, help="foreground is value >= T (default: any nonzero, as the source)")
    c.add_argument("--max-cubes", type=int, default=512)
    c.add_argument("--csv", metavar="FILE", help="per-cube stats CSV")
    c.add_argument("--out", metavar="FILE", help="reject list, one cube id per line")
    c.add_argument("--json", action="store_true", help="print JSON")

    s = act.add_parser("support", help="share of a tifxyz's vertices on its surface prediction, against random "
                                       "points in its neighbourhood (villa PR #1906's check) and a moved copy")
    s.add_argument("surface", help="tifxyz folder")
    s.add_argument("prediction", help="surface-prediction zarr folder or URL (s3:// or https://) of the same scan")
    s.add_argument("--level", type=int, default=0, help="prediction level to sample (coordinates stay level 0)")
    s.add_argument("--threshold", type=float, default=SUPPORT_THRESHOLD,
                   help=f"on the prediction at value >= T (default {SUPPORT_THRESHOLD}, the tracer's own test; "
                        "#1906 counts any nonzero, --threshold 1)")
    s.add_argument("--within", type=int, default=0, help="on when any voxel within D along the normal reads >= T")
    s.add_argument("--stride", type=int, default=1, help="every Nth row and column of the grid")
    s.add_argument("--background", type=int, default=SUPPORT_BG_POINTS, help="random background points (0: off, and then no background warning)")
    s.add_argument("--dilate", type=float, default=SUPPORT_BG_DILATE, help="background box margin in voxels")
    s.add_argument("--seed", type=int, default=SUPPORT_SEED)
    s.add_argument("--shift", type=float, default=0.0,
                   help="also score the surface moved this many voxels along its normal, a control that should "
                        "score lower; use about half the sheet spacing, and more than --within plus half the sheet "
                        "thickness")
    s.add_argument("--min-share", type=float, default=SUPPORT_MIN_SHARE)
    s.add_argument("--margin", type=float, default=SUPPORT_MARGIN)
    s.add_argument("--cache-chunks", type=int, default=2048)
    s.add_argument("--strict", action="store_true", help="exit 3 when the verdict is warn")
    s.add_argument("--json", action="store_true", help="print JSON")

    from . import certify, regioncrop
    certify.add_parser(act)
    regioncrop.add_parser(act)
    return p


def cmd_meshqa(args):
    from . import certify, regioncrop
    run = {"validity": run_validity, "windaudit": run_windaudit, "predcubes": run_predcubes,
           "support": run_support, "certify": certify.run_certify, "crop": regioncrop.run_crop}[args.action]
    try:
        return run(args)
    except (MeshQAError, certify.CertifyError, regioncrop.CropError) as exc:
        print(f"kit meshqa {args.action}: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"kit meshqa {args.action}: {exc}", file=sys.stderr)
        return 1
