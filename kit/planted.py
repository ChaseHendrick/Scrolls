"""Planted defects with known answers on synthetic tifxyz surfaces: `python -m kit planted`.

  kit planted families [--json]
        the families, their short ids and the truth each one must get
  kit planted make OUT --family F [--geometry spiral|planes] [--rows R0 R1] [--cols C0 C1] [--dk K] [--ramp N]
                  [--json]
        write OUT as a tifxyz (x.tif, y.tif, z.tif, meta.json) plus OUT/planted.json: the family, the site, the
        sheet geometry, the true winding of every vertex and the summary truth
  kit planted check DIR [--json]
        recompute the true winding of every vertex from the geometry alone and the summary truth from it, and
        compare both with DIR/planted.json; exit 3 on any disagreement

What it is. One shared generator of sheet switches, holes and mergers whose answer is known, so switch detectors,
mesh audits, stack checks and reference labelers test against the same plants instead of each building its own. Every
surface lies on a family of concentric sheets (an Archimedean spiral about a center, or parallel planes for tools
that read a small prediction volume), and every vertex records the winding it truly sits on. A plant moves vertices
between windings (switch, lens, skip, merger), removes them (hole) or replaces them by a chord that leaves the sheet
(bridge). The truth is computed from the moved vertices, never from any tool's output, and `check` recomputes it
from the coordinates alone, so a plant that silently did nothing is caught.

Families (short id in brackets: N for a planted error, Q for a planted change that is still correct; expected truth
of the planted cell):
  clean   [none]  no defect, the control twin of every plant                          CORRECT
  switch  [N2]    rows r0..r1 jump dk windings at column c0 and stay there              INCORRECT
  lens    [N7]    switch and return: a block of the neighbour inside the patch         INCORRECT
  skip    [N6]    a hard switch two windings out (dk = 2)                              INCORRECT
  merger  [N3]    the trace slides onto the neighbour over `ramp` columns, with no
                  single jump edge, and stays there (sheets fused in the trace)        INCORRECT
  hole    [Q4]    a punched hole; the rest stays on its sheet                          CORRECT (on the rest)
  bridge  [N12]   a hole filled by the bilinear plane over its four corners; on a spiral the
                  chord leaves the curved sheet                                        INCORRECT where it leaves

Truth fields: wrong (valid vertices at least half a winding from the base winding), off (valid vertices farther
than tol from every sheet; tol is a quarter pitch), jump_edges (grid edges whose two
ends differ by at least half a winding), rim (valid vertices that are not wrong but share a grid edge with a wrong
one), holes, components (4-connected valid parts) and the expected label.

This is synthetic data only: no scan, no label and no model output is read or written. It needs numpy; tifxyz
files are written with kit's own TIFF writer when it is present, otherwise with tifffile.
"""

import argparse
import json
import math
import sys
from pathlib import Path

SCHEMA = "kit-planted/1"
TWO_PI = 2.0 * math.pi
EXIT_DISAGREE = 3

FAMILIES = {
    "clean": {"id": None, "expected": "CORRECT", "moves": False,
              "what": "no defect: the control twin of every plant"},
    "switch": {"id": "N2", "expected": "INCORRECT", "moves": True,
               "what": "hard switch: rows r0..r1 jump dk windings at column c0 and stay there"},
    "lens": {"id": "N7", "expected": "INCORRECT", "moves": True,
             "what": "switch and return: rows r0..r1, columns c0..c1 on the neighbouring winding"},
    "skip": {"id": "N6", "expected": "INCORRECT", "moves": True,
             "what": "skip-wrap: a hard switch two windings out (dk 2)"},
    "merger": {"id": "N3", "expected": "INCORRECT", "moves": True,
               "what": "the trace slides onto the neighbour over ramp columns (no single jump edge) and stays there"},
    "hole": {"id": "Q4", "expected": "CORRECT", "moves": False,
             "what": "punched hole: the block is invalid, the rest stays on its sheet"},
    "bridge": {"id": "N12", "expected": "INCORRECT", "moves": False,
               "what": "bridged hole: the block is replaced by the bilinear plane over its four corners (leaves a "
                       "curved sheet; on the planes geometry it stays on the sheet)"},
}
GEOMETRIES = ("spiral", "planes")


class PlantError(ValueError):
    pass


def _np():
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - the core kit is standard library only
        raise PlantError("kit planted needs numpy") from exc
    return numpy


class Sheets:
    """Concentric sheets with a continuous winding coordinate f: sheet k (an offset from the base winding) is the
    level set f = k.

    spiral: r = pitch (w0 + k + hand (theta - theta0) / 2 pi) about `centre`; column c sits at theta0 + c dtheta
            (an arc step of about `step` voxels on the base winding), row r at z0 + zstep r.
    planes: x = x0 + pitch k; column c at y0 + step c, row r at z0 + zstep r (for tools that read a small prediction volume)."""

    def __init__(self, kind="spiral", pitch=20.0, step=5.0, zstep=5.0, z0=100.0, w0=10.0, centre=(500.0, 400.0),
                 hand=1, theta0=0.0, x0=40.0, y0=10.0):
        if kind not in GEOMETRIES:
            raise PlantError(f"geometry must be one of {GEOMETRIES}, not {kind!r}")
        if not pitch > 0 or not step > 0 or not zstep > 0:
            raise PlantError("pitch, step and zstep must be positive")
        if hand not in (1, -1):
            raise PlantError("hand must be 1 or -1")
        self.kind, self.pitch, self.step, self.zstep, self.z0 = kind, float(pitch), float(step), float(zstep), float(z0)
        self.w0, self.centre, self.hand, self.theta0 = float(w0), (float(centre[0]), float(centre[1])), int(hand), float(theta0)
        self.x0, self.y0 = float(x0), float(y0)

    def params(self):
        p = {"kind": self.kind, "pitch": self.pitch, "step": self.step, "zstep": self.zstep, "z0": self.z0}
        if self.kind == "spiral":
            p.update(w0=self.w0, centre=list(self.centre), hand=self.hand, theta0=self.theta0)
        else:
            p.update(x0=self.x0, y0=self.y0)
        return p

    @classmethod
    def from_params(cls, p):
        p = dict(p)
        return cls(**p)

    def dtheta(self):
        return self.step / (self.pitch * self.w0)

    def theta(self, col):
        return self.theta0 + _np().asarray(col, float) * self.dtheta()

    def point(self, k, row, col):
        """xyz (..., 3) of winding offset k (float allowed) at grid (row, col)."""
        np = _np()
        k, row, col = np.broadcast_arrays(np.asarray(k, float), np.asarray(row, float), np.asarray(col, float))
        z = self.z0 + self.zstep * row
        if self.kind == "planes":
            return np.stack([self.x0 + self.pitch * k, self.y0 + self.step * col, z], -1)
        th = self.theta(col)
        rad = self.pitch * (self.w0 + k + self.hand * (th - self.theta0) / TWO_PI)
        return np.stack([self.centre[0] + rad * np.cos(th), self.centre[1] + rad * np.sin(th), z], -1)

    def _f(self, xyz, col=None):
        """Continuous winding coordinate of points; with col (the column's nominal angle) the spiral's angle is
        unwrapped to that column, so f is the sheet offset itself, otherwise f is known only modulo whole turns."""
        np = _np()
        xyz = np.asarray(xyz, float)
        if self.kind == "planes":
            return (xyz[..., 0] - self.x0) / self.pitch
        dx, dy = xyz[..., 0] - self.centre[0], xyz[..., 1] - self.centre[1]
        r, th = np.hypot(dx, dy), np.arctan2(dy, dx)
        if col is not None:
            tc = self.theta(col)
            th = th + TWO_PI * np.round((tc - th) / TWO_PI)
        return r / self.pitch - self.w0 - self.hand * (th - self.theta0) / TWO_PI

    def measure(self, xyz, col):
        """True winding offset of each vertex from its coordinates and its column's nominal angle alone."""
        return self._f(xyz, col)

    def distance(self, xyz):
        """Voxels from each point to the nearest sheet (radial on the spiral, along x for the planes)."""
        np = _np()
        f = self._f(xyz)
        return self.pitch * np.abs(f - np.round(f))


def prediction_volume(sheets, shape, thickness=5.0, kmin=None, kmax=None, origin=(0, 0, 0)):
    """A binary (z, y, x) uint8 sheet prediction (255 on a sheet) for the same sheets: every voxel within
    thickness / 2 of a sheet whose offset lies in [kmin, kmax] (all sheets when both are None)."""
    np = _np()
    zz, yy, xx = np.meshgrid(*(np.arange(n, dtype=float) + o for n, o in zip(shape, origin)), indexing="ij")
    xyz = np.stack([xx, yy, zz], -1)
    f = sheets._f(xyz)
    k = np.round(f)
    on = sheets.pitch * np.abs(f - k) <= thickness / 2.0
    if kmin is not None:
        on &= k >= kmin
    if kmax is not None:
        on &= k <= kmax
    return np.where(on, 255, 0).astype(np.uint8)


class Plant:
    """A grid surface on `sheets` with the true winding offset k of every vertex (NaN where invalid)."""

    def __init__(self, sheets, xyz, valid, k, k0=0, family="clean", site=None, history=None):
        self.sheets, self.xyz, self.valid, self.k, self.k0 = sheets, xyz, valid, k, int(k0)
        self.family, self.site, self.history = family, dict(site or {}), list(history or [])

    @property
    def shape(self):
        return self.valid.shape

    def copy(self):
        return Plant(self.sheets, self.xyz.copy(), self.valid.copy(), self.k.copy(), self.k0, self.family,
                     self.site, self.history)

    def cols(self):
        np = _np()
        return np.broadcast_to(np.arange(self.shape[1])[None, :], self.shape)

    def rows(self):
        np = _np()
        return np.broadcast_to(np.arange(self.shape[0])[:, None], self.shape)

    def reproject(self, mask):
        """Recompute xyz from the base winding k0 plus the offsets k where mask is set."""
        p = self.sheets.point(self.k0 + self.k, self.rows(), self.cols())
        self.xyz[mask] = p[mask]


def surface(sheets=None, shape=(20, 120), k0=0):
    """A clean surface: every vertex on winding k0 (the base, offset 0)."""
    np = _np()
    sheets = sheets or Sheets()
    h, w = int(shape[0]), int(shape[1])
    if h < 4 or w < 8:
        raise PlantError("a surface needs at least 4 rows and 8 columns")
    k = np.zeros((h, w))
    valid = np.ones((h, w), bool)
    rr, cc = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    return Plant(sheets, sheets.point(k + k0, rr, cc), valid, k, k0)


def _default_site(family, shape):
    h, w = shape
    rows = (h // 4, h - h // 4)
    if family == "merger":
        return (0, h), (int(w * 0.6), w)        # the whole height slides: no hard edge anywhere
    if family in ("switch", "skip"):
        cols = (int(w * 0.4), w)
    else:
        cols = (int(w * 0.4), int(w * 0.6))
    return rows, cols


def plant(base, family, rows=None, cols=None, dk=None, ramp=4):
    """A copy of `base` with one defect of `family` planted at rows r0..r1-1 and columns c0..c1-1."""
    np = _np()
    if family not in FAMILIES:
        raise PlantError(f"unknown family {family!r}; families: {sorted(FAMILIES)}")
    h, w = base.shape
    drows, dcols = _default_site(family, (h, w))
    r0, r1 = (int(v) for v in (rows or drows))
    c0, c1 = (int(v) for v in (cols or dcols))
    if not (0 <= r0 < r1 <= h and 0 <= c0 < c1 <= w):
        raise PlantError(f"site rows {r0}..{r1} cols {c0}..{c1} is outside the {h} x {w} grid or empty")
    if dk is None:
        dk = 2 if family == "skip" else 1
    dk = int(dk)
    if FAMILIES[family]["moves"] and dk == 0:
        raise PlantError(f"{family} needs a nonzero dk")
    out = base.copy()
    site = {"rows": [r0, r1], "cols": [c0, c1]}
    block = np.zeros((h, w), bool)
    block[r0:r1, c0:c1] = True
    block &= out.valid
    if family in ("switch", "skip", "lens"):
        out.k[block] += dk
        site["dk"] = dk
        out.reproject(block)
    elif family == "merger":
        ramp = int(ramp)
        if ramp < 1 or c0 + ramp >= c1:
            raise PlantError("merger needs ramp >= 1 and room after the ramp inside the site")
        cc = np.arange(w)
        t = np.clip((cc - c0 + 1) / (ramp + 1.0), 0.0, 1.0)
        prof = dk * (t * t * (3 - 2 * t))
        out.k[block] += np.broadcast_to(prof[None, :], (h, w))[block]
        site.update(dk=dk, ramp=ramp)
        out.reproject(block)
    elif family == "hole":
        out.valid[block] = False
    elif family == "bridge":
        if r0 == 0 or c0 == 0 or r1 == h or c1 == w:
            raise PlantError("a bridge needs a border on all four sides")
        A, B = out.xyz[r0 - 1, c0 - 1].copy(), out.xyz[r0 - 1, c1].copy()
        C, D = out.xyz[r1, c0 - 1].copy(), out.xyz[r1, c1].copy()
        nr, nc = r1 - r0 + 1, c1 - c0 + 1
        for i in range(r0, r1):
            for j in range(c0, c1):
                u, v = (j - c0 + 1) / nc, (i - r0 + 1) / nr
                # the bilinear plane over the hole's four corners, as a plain hole filler would put there
                out.xyz[i, j] = (1 - u) * (1 - v) * A + u * (1 - v) * B + (1 - u) * v * C + u * v * D
        f = out.sheets.measure(out.xyz, out.cols())
        out.k[block] = f[block] - out.k0
    if family != "clean":
        out.family = family if base.family == "clean" else f"{base.family}+{family}"
    out.site = site
    out.history = base.history + [{"family": family, **site}]
    out.k[~out.valid] = np.nan
    out.xyz[~out.valid] = -1.0
    return out


def _components(valid):
    np = _np()
    lab = np.full(valid.shape, -1, int)
    n = 0
    h, w = valid.shape
    for r in range(h):
        for c in range(w):
            if valid[r, c] and lab[r, c] < 0:
                stack = [(r, c)]
                lab[r, c] = n
                while stack:
                    a, b = stack.pop()
                    for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        y, x = a + da, b + db
                        if 0 <= y < h and 0 <= x < w and valid[y, x] and lab[y, x] < 0:
                            lab[y, x] = n
                            stack.append((y, x))
                n += 1
    return n


def _rim(wrong, valid):
    """Valid vertices that are not wrong but share a grid edge with a wrong one: what a cut at the jump edges takes
    with it on the seed's side."""
    np = _np()
    nb = np.zeros_like(wrong)
    nb[1:, :] |= wrong[:-1, :]
    nb[:-1, :] |= wrong[1:, :]
    nb[:, 1:] |= wrong[:, :-1]
    nb[:, :-1] |= wrong[:, 1:]
    return valid & ~wrong & nb


def truth(p, tol=None):
    """The known answer of a plant, from its true winding offsets and coordinates only."""
    np = _np()
    tol = p.sheets.pitch / 4.0 if tol is None else float(tol)
    v = p.valid
    off_base = np.where(v, np.abs(p.k), 0.0)
    wrong = v & (off_base >= 0.5)
    dist = np.where(v, p.sheets.distance(np.where(v[..., None], p.xyz, 0.0)), 0.0)
    off = v & (dist > tol)
    eh = v[:, 1:] & v[:, :-1] & (np.abs(np.nan_to_num(p.k[:, 1:] - p.k[:, :-1])) >= 0.5)
    ev = v[1:, :] & v[:-1, :] & (np.abs(np.nan_to_num(p.k[1:, :] - p.k[:-1, :])) >= 0.5)
    nv = int(v.sum())
    out = {
        "family": p.family, "ids": [FAMILIES[h["family"]]["id"] for h in p.history] or [None],
        "grid": list(p.shape), "vertices": nv, "holes": int((~v).sum()),
        "wrong": int(wrong.sum()), "wrong_share": round(float(wrong.sum()) / nv, 6) if nv else None,
        "off": int(off.sum()), "off_tol_vox": round(tol, 6),
        "jump_edges": int(eh.sum() + ev.sum()), "jump_edges_rowwise": int(eh.sum()), "jump_edges_colwise": int(ev.sum()),
        "rim": int(_rim(wrong, v).sum()),
        "max_offset": round(float(off_base.max()), 6) if nv else 0.0,
        "components": _components(v),
    }
    if wrong.any():
        rr, cc = np.nonzero(wrong)
        out["wrong_box"] = [int(rr.min()), int(rr.max()) + 1, int(cc.min()), int(cc.max()) + 1]
    out["expected"] = "INCORRECT" if (out["wrong"] or out["off"]) else "CORRECT"
    return out


def masks(p, tol=None):
    """(wrong, off) boolean grids of a plant, the per-vertex form of truth()."""
    np = _np()
    tol = p.sheets.pitch / 4.0 if tol is None else float(tol)
    v = p.valid
    wrong = v & (np.where(v, np.abs(p.k), 0.0) >= 0.5)
    off = v & (np.where(v, p.sheets.distance(np.where(v[..., None], p.xyz, 0.0)), 0.0) > tol)
    return wrong, off


def neighbours(p, ks=(-2, -1, 1, 2)):
    """Clean grids of the windings at offsets ks next to the plant's base: the true references a labeler matches the
    plant against. Returns {offset: (xyz, valid)}."""
    np = _np()
    out = {}
    for dk in (0,) + tuple(ks):
        q = surface(p.sheets, p.shape, p.k0 + int(dk))
        out[int(dk)] = (q.xyz, np.ones(p.shape, bool))
    return out


def _write_grid(path, arr):
    np = _np()
    a = np.asarray(arr, np.float32)
    try:
        from . import vc3d_io
    except ImportError:
        vc3d_io = None
    if vc3d_io is not None and hasattr(vc3d_io, "write_tiff"):
        vc3d_io.write_tiff(path, vc3d_io.raster_from_numpy(a))
        return
    try:
        import tifffile
    except ImportError as exc:  # pragma: no cover
        raise PlantError("writing a tifxyz needs kit.vc3d_io or tifffile") from exc
    tifffile.imwrite(str(path), a)


def _read_grid(path):
    np = _np()
    try:
        import tifffile
    except ImportError as exc:  # pragma: no cover
        raise PlantError("reading a tifxyz needs tifffile") from exc
    return np.asarray(tifffile.imread(str(path)), float)


def write(p, out, overwrite=False):
    """Write the plant as a tifxyz folder with planted.json beside meta.json."""
    np = _np()
    out = Path(out)
    if out.exists() and any(out.iterdir()) and not overwrite:
        raise PlantError(f"{out} exists and is not empty")
    out.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate("xyz"):
        _write_grid(out / f"{c}.tif", np.where(p.valid, p.xyz[..., i], -1.0))
    pts = p.xyz[p.valid]
    meta = {"format": "tifxyz", "type": "seg", "uuid": out.name, "scale": [0.05, 0.05],
            "bbox": [pts.min(0).tolist(), pts.max(0).tolist()] if len(pts) else None, "source": "kit planted"}
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    k = [[None if not ok else round(float(x), 6) for x, ok in zip(rk, rv)] for rk, rv in zip(p.k, p.valid)]
    rec = {"schema": SCHEMA, "synthetic": True, "family": p.family, "site": p.site, "history": p.history,
           "sheets": p.sheets.params(), "k0": p.k0, "truth": truth(p), "k": k}
    (out / "planted.json").write_text(json.dumps(rec) + "\n")
    return out


def load(path):
    """(plant, record) from a folder written by write()."""
    np = _np()
    path = Path(path)
    rp = path / "planted.json"
    if not rp.is_file():
        raise PlantError(f"{path} has no planted.json")
    rec = json.loads(rp.read_text())
    if rec.get("schema") != SCHEMA:
        raise PlantError(f"{rp}: schema {rec.get('schema')!r} is not {SCHEMA}")
    xyz = np.stack([_read_grid(path / f"{c}.tif") for c in "xyz"], -1)
    valid = ~(xyz == -1).all(-1)
    k = np.array([[np.nan if x is None else x for x in row] for row in rec["k"]], float)
    p = Plant(Sheets.from_params(rec["sheets"]), xyz, valid, k, rec["k0"], rec["family"], rec["site"], rec["history"])
    return p, rec


def check(path, atol=1e-3):
    """Disagreements between a written plant's record and what its coordinates say. Empty means it agrees."""
    np = _np()
    p, rec = load(path)
    bad = []
    stored_valid = np.array([[x is not None for x in row] for row in rec["k"]])
    if stored_valid.shape != p.valid.shape or (stored_valid != p.valid).any():
        bad.append("valid vertices in the tifxyz differ from planted.json")
        return bad
    measured = p.sheets.measure(p.xyz, p.cols()) - p.k0
    err = np.abs(np.where(p.valid, measured - p.k, 0.0))
    if err.max() > atol:
        r, c = np.unravel_index(int(err.argmax()), err.shape)
        bad.append(f"vertex ({r}, {c}) sits at winding offset {measured[r, c]:.4f}, planted.json says {p.k[r, c]:.4f}")
    p.k = np.where(p.valid, measured, np.nan)
    now = truth(p)
    for key in ("wrong", "off", "jump_edges", "holes", "components", "expected"):
        if now[key] != rec["truth"].get(key):
            bad.append(f"truth {key}: coordinates give {now[key]}, planted.json says {rec['truth'].get(key)}")
    exp = FAMILIES.get(rec["family"], {}).get("expected")
    if rec["family"] == "bridge" and p.sheets.kind == "planes":
        exp = "CORRECT"                          # a plane over a plane stays on the sheet
    if exp and now["expected"] != exp:
        bad.append(f"family {rec['family']} must be {exp} but its truth is {now['expected']}")
    return bad


def build_parser(p):
    sub = p.add_subparsers(dest="planted_cmd", required=True)
    js = "print the result as JSON"
    f = sub.add_parser("families", help="the families, their short ids and expected truth")
    f.add_argument("--json", action="store_true", help=js)
    m = sub.add_parser("make", help="write one planted tifxyz with its truth")
    m.add_argument("out", help="output tifxyz folder (must not exist or be empty)")
    m.add_argument("--family", required=True, choices=sorted(FAMILIES), help="the defect to plant")
    m.add_argument("--geometry", default="spiral", choices=GEOMETRIES,
                   help="spiral (pitch 20, 20 x 120 grid) or planes (pitch 14, 30 x 40 grid, for prediction-volume tests)")
    m.add_argument("--shape", type=int, nargs=2, metavar=("H", "W"), help="grid rows and columns")
    m.add_argument("--rows", type=int, nargs=2, metavar=("R0", "R1"), help="rows of the site, R1 excluded")
    m.add_argument("--cols", type=int, nargs=2, metavar=("C0", "C1"), help="columns of the site, C1 excluded")
    m.add_argument("--dk", type=int, help="windings the plant moves by (default 1, 2 for skip)")
    m.add_argument("--ramp", type=int, default=4, help="columns a merger takes to slide across")
    m.add_argument("--overwrite", action="store_true", help="write into a folder that is not empty")
    m.add_argument("--json", action="store_true", help=js)
    c = sub.add_parser("check", help="recompute a written plant's truth from its coordinates")
    c.add_argument("dir", help="a folder written by make")
    c.add_argument("--json", action="store_true", help=js)
    return p


def main(argv=None):
    args = build_parser(argparse.ArgumentParser(prog="python -m kit.planted",
                                                description=__doc__.split("\n\n")[0])).parse_args(argv)
    return cmd_planted(args)


def cmd_planted(args):
    try:
        if args.planted_cmd == "families":
            if args.json:
                print(json.dumps(FAMILIES, indent=2))
            else:
                for name, f in FAMILIES.items():
                    print(f"{name:7s} {f['id'] or '-':4s} {f['expected']:9s} {f['what']}")
            return 0
        if args.planted_cmd == "make":
            if args.geometry == "planes":
                sheets, shape = Sheets("planes", pitch=14.0, step=4.0, zstep=4.0, z0=10.0), args.shape or (30, 40)
            else:
                sheets, shape = Sheets(), args.shape or (20, 120)
            p = plant(surface(sheets, shape), args.family, args.rows, args.cols, args.dk, args.ramp)
            out = write(p, args.out, overwrite=args.overwrite)
            t = truth(p)
            print(json.dumps({"out": str(out), "truth": t}, indent=2) if args.json else
                  f"{out}: {p.family}, wrong {t['wrong']}, off {t['off']}, jump edges {t['jump_edges']}, "
                  f"holes {t['holes']}, components {t['components']}, {t['expected']}")
            return 0
        bad = check(args.dir)
        print(json.dumps({"dir": args.dir, "agrees": not bad, "disagreements": bad}, indent=2) if args.json else
              ("agrees" if not bad else "\n".join(["DISAGREES"] + bad)))
        return EXIT_DISAGREE if bad else 0
    except PlantError as exc:
        print(f"kit planted: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
