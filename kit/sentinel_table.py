"""Bucket Sentinel's offset table, for loaders: where a published canvas pixel really sits on its tifxyz.

Self-contained (standard library, numpy optional) so a training loader can vendor this one file. The table is what
`python -m kit sentinel table` writes (schema SCHEMA): one entry per checked segment folder, pinned to the exact
files it describes by sha256, with a map from canvas level-0 pixels to tifxyz full-resolution cells:

    cell_y = y + dy(y, x),  cell_x = x + dx(y, x)

where (y, x) is a pixel of the canvas (and of the label zarrs on the canvas grid) and (cell_y, cell_x) is the cell
of the tifxyz grid upsampled to full resolution (grid index times 1 / meta.json scale), the convention of villa
issue #2370: canvas content at (y, x) lies where the tifxyz puts cell (y + dy, x + dx). villa's `full_3d` ink loader
reads the label window at the same flat indices as the tifxyz window, so it needs this map when it is not zero.

Models, from simplest:
  aligned   dy = dx = 0 (measured within the table's tolerance; the renderer's own half pixel is not corrected)
  constant  dy = a_y, dx = a_x
  affine    d = a + b * y + c * x per axis (a canvas made on a grid of another size drifts linearly, #2370)
  regions   the affine plus a residual measured on a regular grid of windows, interpolated bilinearly; used when
            the affine leaves more than the table's residual bar

    from kit import sentinel_table as st
    table = st.load("docs/sentinel/offsets.json")
    entry = table.lookup("ink/phercparis4/w01_20230702185753_r15")
    cy, cx = entry.cell(y, x)            # scalars or numpy arrays
    y, x = entry.pixel(cy, cx)           # the inverse
    problems = entry.verify("/data/ink/phercparis4/w01_20230702185753_r15")   # [] when the local files match

An entry that does not verify describes other files: do not apply it. A folder with no entry is unmeasured, not
aligned.
"""

import hashlib
import json
import os
import urllib.request

SCHEMA = "bucket-sentinel-offsets/1"
MODELS = ("aligned", "constant", "affine", "regions")


class TableError(ValueError):
    pass


def _np():
    try:
        import numpy
        return numpy
    except ImportError:          # scalars still work without numpy
        return None


def _interp1(grid, v):
    """Fractional index of v in an increasing list (clamped)."""
    if v <= grid[0]:
        return 0.0
    if v >= grid[-1]:
        return float(len(grid) - 1)
    for i in range(len(grid) - 1):
        if grid[i] <= v <= grid[i + 1]:
            return i + (v - grid[i]) / (grid[i + 1] - grid[i])
    return float(len(grid) - 1)


class Entry:
    """One segment folder's map. `cell` and `pixel` take scalars or numpy arrays of level-0 canvas pixels."""

    def __init__(self, doc):
        self.doc = doc
        self.path = doc["path"]
        self.model = doc["model"]
        if self.model not in MODELS:
            raise TableError(f"{self.path}: model {self.model!r} is not one of {', '.join(MODELS)}")
        self.affine = doc.get("affine") or {"dy": [0.0, 0.0, 0.0], "dx": [0.0, 0.0, 0.0]}
        self.grid = doc.get("grid")
        self.pins = doc.get("pins") or {}

    def _residual(self, y, x, key):
        g = self.grid
        if not g:
            return 0.0
        fy, fx = _interp1(g["y"], y), _interp1(g["x"], x)
        i0, j0 = int(min(fy, len(g["y"]) - 2)) if len(g["y"]) > 1 else 0, \
            int(min(fx, len(g["x"]) - 2)) if len(g["x"]) > 1 else 0
        ty, tx = fy - i0, fx - j0
        vals = g[key]

        def at(i, j):
            i = min(i, len(g["y"]) - 1)
            j = min(j, len(g["x"]) - 1)
            v = vals[i][j]
            return 0.0 if v is None else float(v)
        return ((1 - ty) * (1 - tx) * at(i0, j0) + (1 - ty) * tx * at(i0, j0 + 1)
                + ty * (1 - tx) * at(i0 + 1, j0) + ty * tx * at(i0 + 1, j0 + 1))

    def offset(self, y, x):
        """(dy, dx) at canvas pixel (y, x)."""
        if self.model == "aligned":
            return 0.0 * y, 0.0 * x
        ay, ax = self.affine["dy"], self.affine["dx"]
        dy = ay[0] + ay[1] * y + ay[2] * x
        dx = ax[0] + ax[1] * y + ax[2] * x
        if self.model == "regions":
            np = _np()
            if np is not None and hasattr(y, "shape"):
                ry = np.vectorize(lambda a, b: self._residual(a, b, "dy"))(y, x)
                rx = np.vectorize(lambda a, b: self._residual(a, b, "dx"))(y, x)
            else:
                ry, rx = self._residual(y, x, "dy"), self._residual(y, x, "dx")
            dy, dx = dy + ry, dx + rx
        return dy, dx

    def cell(self, y, x):
        """tifxyz full-resolution cell (cell_y, cell_x) that canvas pixel (y, x) shows."""
        dy, dx = self.offset(y, x)
        return y + dy, x + dx

    def pixel(self, cy, cx, iterations=8):
        """The canvas pixel that shows tifxyz cell (cy, cx): the inverse of `cell`, by fixed-point iteration (the
        offsets change slowly with position, so a few steps converge to well under a pixel)."""
        y, x = cy, cx
        for _ in range(iterations):
            dy, dx = self.offset(y, x)
            y, x = cy - dy, cx - dx
        return y, x

    def verify(self, folder):
        """Problems (list of strings) between the pinned files and a local copy of the folder; [] when all match."""
        out = []
        for rel, want in sorted(self.pins.items()):
            p = os.path.join(folder, rel)
            if not os.path.isfile(p):
                out.append(f"{rel}: missing")
                continue
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            if h.hexdigest() != want:
                out.append(f"{rel}: sha256 differs from the table's pin")
        return out


class Table:
    def __init__(self, doc):
        if doc.get("schema") != SCHEMA:
            raise TableError(f"not a Bucket Sentinel offset table (schema {doc.get('schema')!r}, want {SCHEMA})")
        self.doc = doc
        self.entries = {e["path"].strip("/"): Entry(e) for e in doc.get("entries", [])}

    def lookup(self, path):
        """The entry for a bucket folder path such as ink/841/w00 (or a path ending in it), else None."""
        p = str(path).strip("/")
        if p in self.entries:
            return self.entries[p]
        for k, e in self.entries.items():
            if p.endswith("/" + k) or p.endswith(k):
                return e
        return None


def load(path_or_url):
    """A Table from a local path or an https:// URL."""
    s = str(path_or_url)
    if s.startswith("https://"):
        with urllib.request.urlopen(s, timeout=60) as r:
            doc = json.loads(r.read())
    else:
        with open(s) as f:
            doc = json.load(f)
    return Table(doc)


def label_cells(entry, y0, y1, x0, x1):
    """For a label window [y0, y1) x [x0, x1) on the canvas grid: two numpy arrays (cell_y, cell_x) of the tifxyz
    full-resolution cells its pixels show, for a loader that samples the tifxyz (or the CT through it) there instead
    of at the same flat indices."""
    np = _np()
    if np is None:
        raise TableError("label_cells needs numpy")
    yy, xx = np.meshgrid(np.arange(y0, y1, dtype=float), np.arange(x0, x1, dtype=float), indexing="ij")
    if entry is None or entry.model == "aligned":
        return yy, xx
    return entry.cell(yy, xx)
