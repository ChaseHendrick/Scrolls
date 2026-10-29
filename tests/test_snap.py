"""kit snap: the port of Nieuwlaar's snap_meshes.py, the RectoRefine midline port and the self-check.

Synthetic fixtures only (binary sheets and bright bands in small zarr arrays written here, tifxyz grids), in
temporary folders. Numerical tests skip without numpy; the scipy cross-checks skip without scipy. The his_*
helpers copy parts of snap_meshes.py, Copyright (c) 2026 Erwin Nieuwlaar, MIT license (full text in kit/snap.py).
"""

import contextlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kit import cli, snap

ROOT = Path(__file__).resolve().parents[1]

try:
    import numpy as np
except ImportError:  # the core kit is standard library only
    np = None

try:
    from scipy import ndimage
except ImportError:
    ndimage = None


def write_zarr(root, vol, chunk=(16, 16, 16), levels=1):
    """An OME-Zarr v2 group of uint8 levels (level k samples level 0 every 2**k), uncompressed, '/' keys."""
    root = Path(root)
    datasets = []
    for k in range(levels):
        a = vol[::2 ** k, ::2 ** k, ::2 ** k]
        d = root / str(k)
        d.mkdir(parents=True, exist_ok=True)
        (d / ".zarray").write_text(json.dumps({
            "zarr_format": 2, "shape": list(a.shape), "chunks": list(chunk), "dtype": "|u1", "compressor": None,
            "fill_value": 0, "filters": None, "order": "C", "dimension_separator": "/"}))
        for i in range(-(-a.shape[0] // chunk[0])):
            for j in range(-(-a.shape[1] // chunk[1])):
                for m in range(-(-a.shape[2] // chunk[2])):
                    blk = np.zeros(chunk, np.uint8)
                    sub = a[i * chunk[0]:(i + 1) * chunk[0], j * chunk[1]:(j + 1) * chunk[1],
                            m * chunk[2]:(m + 1) * chunk[2]]
                    blk[:sub.shape[0], :sub.shape[1], :sub.shape[2]] = sub
                    if not blk.any():
                        continue                      # a missing chunk reads as the fill value
                    p = d / str(i) / str(j)
                    p.mkdir(parents=True, exist_ok=True)
                    (p / str(m)).write_bytes(blk.tobytes())
        datasets.append({"path": str(k), "coordinateTransformations": [
            {"type": "scale", "scale": [float(2 ** k)] * 3}]})
    (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (root / ".zattrs").write_text(json.dumps({"multiscales": [{"version": "0.4", "datasets": datasets,
                                                               "axes": [{"name": a} for a in "zyx"]}]}))
    return root


def write_mesh(folder, xs, ys, zs, meta=None):
    from kit import vc3d_io
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, a in (("x", xs), ("y", ys), ("z", zs)):
        vc3d_io.write_tiff(folder / f"{name}.tif", vc3d_io.raster_from_numpy(a))
    (folder / "meta.json").write_text(json.dumps(meta or {"format": "tifxyz", "type": "seg", "source": "test"}))
    return folder


def plane_mesh(H, W, z, step=2.0, x0=6.0, y0=6.0):
    r, c = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    xs = (x0 + step * c).astype(np.float32)
    ys = (y0 + step * r).astype(np.float32)
    zs = np.full((H, W), z, np.float32) if np.isscalar(z) else np.asarray(z, np.float32)
    return xs, ys, zs


def slab(shape, z_lo, z_hi, value=255, background=0):
    """A volume with value on whole z planes z_lo..z_hi (inclusive)."""
    v = np.full(shape, background, np.uint8)
    v[z_lo:z_hi + 1] = value
    return v


def his_choose(prof, K):
    """The per-vertex loop of snap_meshes.py (Nieuwlaar, MIT, commit e8370f1), verbatim but for names."""
    nv = prof.shape[0]
    L = prof.shape[1]
    d = np.full(nv, np.nan, np.float32)
    padded = np.concatenate([np.zeros((nv, 1), bool), prof, np.zeros((nv, 1), bool)], 1).astype(np.int8)
    dif = np.diff(padded, axis=1)
    has = prof.any(1)
    for i in np.nonzero(has)[0]:
        st_ = np.nonzero(dif[i] == 1)[0]
        en_ = np.nonzero(dif[i] == -1)[0]
        centres = (st_ + en_ - 1) / 2.0 - K
        j = int(np.argmin(np.abs(centres)))
        sm = np.convolve(prof[i].astype(np.float32), [1, 2, 1], mode='same')
        c = int(round(centres[j] + K))
        c = min(max(c, 1), L - 2)
        y0_, y1_, y2_ = sm[c - 1], sm[c], sm[c + 1]
        den = (y0_ - 2 * y1_ + y2_)
        frac = 0.5 * (y0_ - y2_) / den if abs(den) > 1e-6 else 0.0
        d[i] = centres[j] if abs(frac) > 0.5 else 0.5 * (centres[j] + (c - K + frac))
    return d, has


def his_normals(xs, ys, zs, valid):
    """normals() of snap_meshes.py (Nieuwlaar, MIT, commit e8370f1), verbatim but for names."""
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


def his_snap(xs, ys, zs, vol, level=0, K=15, jump=6.0, sigma=1.0):
    """One winding through snap_meshes.py (Nieuwlaar, MIT, commit e8370f1): his sampling (zyx points / 2**level,
    bounds, rint, values copied into uint8), his_choose, his regularization with scipy and his update, verbatim but
    for names and for reading the level from a numpy array instead of zarr chunks."""
    import warnings
    valid = (xs > -0.5) & (ys > -0.5) & (zs > -0.5) & np.isfinite(xs) & np.isfinite(ys) & np.isfinite(zs)
    n, ok = his_normals(xs, ys, zs, valid)
    ds = 2 ** level
    Z, Y, X = vol.shape
    offs = np.arange(-K, K + 1, dtype=np.float32)
    vy, vx = np.nonzero(ok)
    base = np.stack([zs[vy, vx], ys[vy, vx], xs[vy, vx]], -1)
    nz = n[vy, vx][:, ::-1]
    S = base[:, None, :] + offs[None, :, None] * nz[:, None, :]
    pts = (S.reshape(-1, 3) / ds).astype(np.float32)
    vals = np.zeros(len(pts), np.uint8)
    inb = ((pts[:, 0] >= 0) & (pts[:, 0] < Z - 0.5) & (pts[:, 1] >= 0) & (pts[:, 1] < Y - 0.5) & (pts[:, 2] >= 0)
           & (pts[:, 2] < X - 0.5))
    pi = np.rint(pts).astype(np.int64)
    pi[:, 0] = np.clip(pi[:, 0], 0, Z - 1)
    pi[:, 1] = np.clip(pi[:, 1], 0, Y - 1)
    pi[:, 2] = np.clip(pi[:, 2], 0, X - 1)
    v = vol[pi[:, 0], pi[:, 1], pi[:, 2]]
    h = v > 0
    vals[np.nonzero(h)[0]] = v[h]
    vals[~inb] = 0
    nv = len(vy)
    prof = vals.reshape(nv, len(offs)) > 0
    d, has = his_choose(prof, K)
    D = np.full(xs.shape, np.nan, np.float32)
    D[vy, vx] = d

    def normconv(a, s):
        m = np.isfinite(a).astype(np.float32)
        w = np.where(np.isfinite(a), a, 0).astype(np.float32)
        num = ndimage.gaussian_filter(w, s)
        den = ndimage.gaussian_filter(m, s)
        out = np.full_like(a, np.nan)
        okk = den > 1e-3
        out[okk] = num[okk] / den[okk]
        return out
    Hh, Ww = D.shape
    pad = np.pad(D, 2, constant_values=np.nan)
    st = np.stack([pad[i:i + Hh, j:j + Ww] for i in range(5) for j in range(5)], 0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(st, axis=0)
    with np.errstate(invalid="ignore"):
        rej = np.isfinite(D) & np.isfinite(med) & (np.abs(D - med) > jump)
    D2 = D.copy()
    D2[rej] = np.nan
    filled = normconv(D2, max(sigma, 1.0))
    D3 = np.where(np.isfinite(D2), D2, filled)
    D3 = normconv(D3, sigma)
    D3 = np.clip(D3, -K, K)
    apply = ok & np.isfinite(D3) & np.isfinite(filled)
    xo, yo, zo = xs.copy(), ys.copy(), zs.copy()
    xo[apply] += D3[apply] * n[apply][:, 0]
    yo[apply] += D3[apply] * n[apply][:, 1]
    zo[apply] += D3[apply] * n[apply][:, 2]
    return xo, yo, zo, apply


def run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(argv)
    return code, out.getvalue()


class HelpTest(unittest.TestCase):
    def test_help_needs_no_numpy(self):
        # numpy blocked in a child interpreter: --help must not import it, and a run must stop with a message
        block = "import sys; sys.modules['numpy'] = None; from kit import cli; sys.exit(cli.main(%r))"
        r = subprocess.run([sys.executable, "-c", block % (["snap", "--help"],)], cwd=ROOT, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--source", r.stdout)
        self.assertIn("--check", r.stdout)
        r = subprocess.run([sys.executable, "-c", block % (["snap", "m", "--volume", "v", "--out", "o"],)], cwd=ROOT,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("needs numpy", r.stderr)


@unittest.skipIf(np is None, "numpy is needed for kit snap")
class FilterTest(unittest.TestCase):
    def test_gaussian_interior_impulse_is_the_kernel(self):
        a = np.zeros((1, 21), np.float32)
        a[0, 10] = 1.0
        out = snap.gaussian_filter(a, 1.0)
        k = snap.gaussian_kernel1d(1.0, 4)
        np.testing.assert_allclose(out[0, 6:15], k.astype(np.float32), rtol=1e-6)
        self.assertEqual(out.dtype, np.float32)

    def test_gaussian_keeps_constants_and_sigma_zero_is_identity(self):
        a = np.full((5, 3), 2.5, np.float32)
        np.testing.assert_allclose(snap.gaussian_filter(a, 1.7), a, rtol=1e-6)
        b = np.arange(12, dtype=np.float32).reshape(3, 4)
        self.assertTrue(np.array_equal(snap.gaussian_filter(b, 0.0), b))

    def test_reflect_index_is_period_2n(self):
        # positions -4..6 of a, b, c: (c c b a) a b c (c b a a)
        self.assertEqual(snap._reflect_index(3, 4).tolist(), [2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0])
        self.assertEqual(snap._reflect_index(1, 3).tolist(), [0] * 7)

    @unittest.skipIf(ndimage is None, "scipy is not installed")
    def test_gaussian_matches_scipy_bit_for_bit(self):
        rng = np.random.default_rng(0)
        for shape in [(1, 1), (1, 5), (2, 3), (3, 7), (9, 9), (40, 33)]:
            for sigma in (0.5, 1.0, 1.5, 2.0, 3.3):
                a = (rng.normal(size=shape) * 10).astype(np.float32)
                want = ndimage.gaussian_filter(a, sigma)
                got = snap.gaussian_filter(a, sigma)
                self.assertTrue(np.array_equal(want, got), (shape, sigma, np.abs(want - got).max()))

    @unittest.skipIf(ndimage is None, "scipy is not installed")
    def test_normconv_matches_scipy_version(self):
        rng = np.random.default_rng(1)
        d = rng.normal(size=(12, 15)).astype(np.float32)
        d[rng.random(d.shape) < 0.3] = np.nan
        m = np.isfinite(d).astype(np.float32)
        v = np.where(np.isfinite(d), d, 0).astype(np.float32)
        num, den = ndimage.gaussian_filter(v, 1.0), ndimage.gaussian_filter(m, 1.0)
        want = np.full_like(d, np.nan)
        okk = den > 1e-3
        want[okk] = num[okk] / den[okk]
        self.assertTrue(np.array_equal(snap.normconv(d, 1.0), want, equal_nan=True))

    def test_nanmedian_filter_ignores_nan(self):
        d = np.full((5, 5), 2.0, np.float32)
        d[2, 2] = np.nan
        d[0, 0] = 50.0
        med = snap.nanmedian_filter(d, 5)
        self.assertEqual(float(med[2, 2]), 2.0)

    def test_nanmedian_filter_equals_np_nanmedian_bit_for_bit(self):
        import warnings

        def his(d, size):
            H, W = d.shape
            r = size // 2
            pad = np.pad(d, r, constant_values=np.nan)
            st = np.stack([pad[i:i + H, j:j + W] for i in range(size) for j in range(size)], 0)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                return np.nanmedian(st, axis=0)

        rng = np.random.default_rng(13)
        for dt in (np.float64, np.float32, np.float16):
            fin = np.finfo(dt)
            d = rng.normal(0, 3, (37, 41)).astype(dt)
            d[rng.random(d.shape) < 0.3] = np.nan
            d[:9, :9] = np.nan                                    # windows with no value at all
            for v, p in ((np.inf, 0.03), (-np.inf, 0.03), (0.0, 0.06), (-0.0, 0.06), (fin.max, 0.02),
                         (-fin.max, 0.02), (fin.smallest_subnormal, 0.02), (1.5, 0.05)):
                d[rng.random(d.shape) < p] = v                    # inf pairs, signed zeros, overflow, ties
            grids = [d, np.full((4, 6), np.nan, dt), np.full((3, 3), -0.0, dt), np.zeros((0, 5), dt),
                     np.zeros((5, 0), dt), np.array([[7.0]], dt), np.array([[np.inf, -np.inf]], dt)]
            for g in grids:
                for size in (1, 2, 3, 5):
                    with np.errstate(all="ignore"):
                        want = his(g, size)
                    got = snap.nanmedian_filter(g, size)
                    self.assertEqual((got.dtype, got.shape), (want.dtype, want.shape))
                    self.assertEqual(got.tobytes(), want.tobytes(), (dt, g.shape, size))
            # numpy leaves np.ma.median at a 600-deep stack (size 25): odd counts, overflow and float16 sums differ
            # there, so both sides of that line must still match
            small = rng.normal(0, 3, (6, 7)).astype(dt)
            small[rng.random(small.shape) < 0.3] = np.nan
            deep = [small, np.full((3, 3), fin.max, dt), np.full((3, 4), -fin.max, dt), np.full((3, 3), -0.0, dt),
                    np.full((2, 2), np.nan, dt)]
            for g in deep:
                for size in (24, 25):
                    with np.errstate(all="ignore"):
                        want = his(g, size)
                    got = snap.nanmedian_filter(g, size)
                    self.assertEqual((got.dtype, got.shape), (want.dtype, want.shape))
                    self.assertEqual(got.tobytes(), want.tobytes(), (dt, g.shape, size))


@unittest.skipIf(np is None, "numpy is needed for kit snap")
class ChooseTest(unittest.TestCase):
    def test_vectorised_choice_equals_his_loop(self):
        rng = np.random.default_rng(2)
        for K in (1, 3, 15):
            L = 2 * K + 1
            prof = rng.random((3000, L)) < rng.uniform(0.05, 0.6, (3000, 1))
            prof[:20] = False
            prof[20:40] = True
            got, has = snap.choose_offsets(prof, K)
            want, whas = his_choose(prof, K)
            self.assertTrue(np.array_equal(has, whas))
            self.assertTrue(np.array_equal(got, want, equal_nan=True), K)

    def test_ties_take_the_earlier_run_and_parabola_rules(self):
        K = 5
        prof = np.zeros((3, 11), bool)
        prof[0, [2, 8]] = True            # runs at -3 and +3: the first wins
        prof[1, 6:10] = True              # an even run centered at +2.5
        prof[2, 0:11] = True              # all sheet: center 0
        d, has = snap.choose_offsets(prof, K)
        self.assertEqual(d.tolist(), [-3.0, 2.5, 0.0])
        self.assertTrue(has.all())


@unittest.skipIf(np is None, "numpy is needed for kit snap")
class PredSnapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def sampler(self, vol, name="v.zarr", **kw):
        return snap.Sampler(snap.open_volume(write_zarr(self.root / name, vol, **kw)))

    def test_planar_sheet_odd_and_even_thickness_land_on_the_centre(self):
        for lo, hi, centre in ((29, 31, 30.0), (29, 32, 30.5)):
            sm = self.sampler(slab((48, 40, 40), lo, hi), f"s{lo}{hi}.zarr")
            xs, ys, zs = plane_mesh(14, 14, 26.0)
            r = snap.snap_pred(xs, ys, zs, np.ones(xs.shape, bool), sm)
            self.assertTrue(np.allclose(r["zs"], centre, atol=1e-5), (lo, hi, float(r["zs"].mean())))
            self.assertTrue(np.array_equal(r["xs"], xs) and np.array_equal(r["ys"], ys))
            self.assertAlmostEqual(r["report"]["frac_snapped"], 1.0)
            self.assertAlmostEqual(r["report"]["median_abs_off"], centre - 26.0, places=5)
            self.assertEqual(r["report"]["frac_already_on"], 0.0)

    def test_subvoxel_start_keeps_its_fraction(self):
        sm = self.sampler(slab((48, 40, 40), 29, 32))
        xs, ys, zs = plane_mesh(10, 10, 26.2)
        r = snap.snap_pred(xs, ys, zs, np.ones(xs.shape, bool), sm)
        # nearest-voxel samples at 26.2 + k: the run is k = 3..6, so the offset is 4.5 and the vertex lands at 30.7
        self.assertTrue(np.allclose(r["zs"], 30.7, atol=1e-5))

    def test_curved_sheet_within_rounding(self):
        Z, Y, X = 48, 52, 52
        zz, yy, xx = np.meshgrid(np.arange(Z), np.arange(Y), np.arange(X), indexing="ij")
        def surf(x, y):
            return 24 + 4 * np.sin(x / 9.0) + 0.01 * (y - 26) ** 2
        vol = (np.abs(zz - surf(xx, yy)) <= 1.5).astype(np.uint8) * 255
        sm = self.sampler(vol)
        xs, ys, zs = plane_mesh(20, 20, 0.0)
        zs = (surf(xs.astype(float), ys.astype(float)) + 3.0).astype(np.float32)
        r = snap.snap_pred(xs, ys, zs, np.ones(xs.shape, bool), sm)
        err = np.abs(r["zs"] - surf(r["xs"].astype(float), r["ys"].astype(float)))
        self.assertLess(float(np.median(err)), 0.35)
        self.assertLess(float(err.max()), 0.8)

    def test_second_sheet_is_rejected(self):
        sm = self.sampler(slab((60, 44, 44), 29, 31) | slab((60, 44, 44), 41, 43))
        xs, ys, zs = plane_mesh(16, 16, 34.0)
        zs[6:9, 6:9] = 38.0               # nearer the upper sheet (+4) than the lower one (-8)
        r = snap.snap_pred(xs, ys, zs, np.ones(xs.shape, bool), sm)
        self.assertGreater(r["report"]["frac_rejected"], 0.0)
        self.assertLess(float(r["zs"].max()), 36.0)          # nothing hopped onto z = 42
        self.assertLess(float(r["zs"][6:9, 6:9].max()), 36.0)
        self.assertGreater(float(r["zs"][6:9, 6:9].min()), 32.0)   # moved down with its neighbors instead
        away = np.ones(xs.shape, bool)
        away[2:13, 2:13] = False                               # the step tilts the normals around it
        self.assertTrue(np.allclose(r["zs"][away], 30.0, atol=1e-4))
        # without the patch nothing is rejected
        clean = snap.snap_pred(*plane_mesh(16, 16, 34.0), np.ones(xs.shape, bool), sm)
        self.assertEqual(clean["report"]["frac_rejected"], 0.0)

    def test_hole_in_the_sheet_is_filled_from_neighbours(self):
        vol = slab((48, 44, 44), 29, 31)
        vol[:, 16:24, 16:24] = 0          # no sheet under a 4 x 4 block of vertices
        sm = self.sampler(vol)
        xs, ys, zs = plane_mesh(16, 16, 26.0)
        hole = (xs >= 16) & (xs < 24) & (ys >= 16) & (ys < 24)
        self.assertGreater(int(hole.sum()), 9)
        r = snap.snap_pred(xs, ys, zs, np.ones(xs.shape, bool), sm)
        self.assertTrue(np.allclose(r["zs"][hole], 30.0, atol=1e-4))
        self.assertLess(r["report"]["frac_with_sheet"], 1.0)
        self.assertEqual(r["report"]["frac_snapped"], 1.0)

    def test_no_sheet_vertices_keep_their_position(self):
        vol = slab((48, 44, 64), 29, 31)
        vol[:, :, 22:] = 0                # sheet only under x < 22
        sm = self.sampler(vol)
        xs, ys, zs = plane_mesh(16, 28, 26.0)
        r = snap.snap_pred(xs, ys, zs, np.ones(xs.shape, bool), sm)
        far = xs >= 22 + 2 * 6            # more than the fill radius from any sheet vertex
        self.assertTrue(far.any())
        self.assertTrue(np.array_equal(r["zs"][far], zs[far]))
        self.assertTrue(np.allclose(r["zs"][xs < 20], 30.0, atol=1e-4))
        self.assertFalse(r["apply"][far].any())

    def test_level_one_uses_his_coordinates(self):
        sm1 = self.sampler(slab((48, 40, 40), 28, 31), levels=2)
        sm1 = snap.Sampler(sm1.vol, level=1)
        xs, ys, zs = plane_mesh(10, 10, 24.0)
        r = snap.snap_pred(xs, ys, zs, np.ones(xs.shape, bool), sm1)
        # level 1 holds level-0 planes 28 and 30 as z 14 and 15. His rule rint(z / 2), half to even, maps
        # z = 27, 28, 29, 30 there (31 -> 15.5 -> 16), so the run is centered at 28.5
        self.assertTrue(np.allclose(r["zs"], 28.5, atol=1e-5), float(r["zs"].mean()))
        pts = np.array([[3.0, 5.0, 7.0]], np.float32)
        self.assertEqual(sm1._level(pts).tolist(), [[1.5, 2.5, 3.5]])
        c = snap.Sampler(sm1.vol, level=1, centres=True)
        self.assertEqual(np.round(c._level(pts), 6).tolist(), [[1.25, 2.25, 3.25]])
        # aligned centers, rint(z / 2 - 0.25): z = 28..31 map to 14 and 15, centered at 29.5
        rc = snap.snap_pred(xs, ys, zs, np.ones(xs.shape, bool), c)
        self.assertTrue(np.allclose(rc["zs"], 29.5, atol=1e-5), float(rc["zs"].mean()))

    def test_files_holes_bbox_and_record(self):
        z = write_zarr(self.root / "v.zarr", slab((48, 40, 40), 29, 31))
        xs, ys, zs = plane_mesh(12, 12, 26.0)
        for a in (xs, ys, zs):
            a[0, 0] = -1.0
            a[5, 5] = -1.0
        src = write_mesh(self.root / "meshes" / "w01", xs, ys, zs,
                         {"format": "tifxyz", "source": "fit", "bbox": [[0, 0, 0], [1, 1, 1]], "uuid": "w01"})
        out = self.root / "out"
        code, text = run_cli(["snap", str(src), "--volume", str(z), "--out", str(out)])
        self.assertEqual(code, 0, text)
        got = snap.load_mesh(out / "w01")
        self.assertFalse(got[3][0, 0] or got[3][5, 5])
        from kit import vc3d_io
        x_raw = vc3d_io.read_tiff(out / "w01" / "x.tif")
        self.assertEqual(x_raw.kind, "f32")
        self.assertEqual(x_raw.at(0, 0), -1.0)
        self.assertEqual(vc3d_io.read_tiff(out / "w01" / "z.tif").at(5, 5), -1.0)
        v = got[3]
        self.assertTrue(np.allclose(got[2][v], 30.0, atol=1e-4))
        meta = json.loads((out / "w01" / "meta.json").read_text())
        self.assertEqual(meta["uuid"], "w01")
        self.assertEqual(meta["bbox"], [[float(got[0][v].min()), float(got[1][v].min()), float(got[2][v].min())],
                                        [float(got[0][v].max()), float(got[1][v].max()), float(got[2][v].max())]])
        self.assertTrue(meta["source"].startswith("fit + snap_meshes_local"))
        for key in ("max_off", "jump", "sigma", "frac_snapped", "median_abs_off"):
            self.assertIn(key, meta["snap"])
        self.assertEqual(meta["snap"]["max_off"], 15)
        tsv = (out / "snap_report.tsv").read_text().splitlines()
        self.assertEqual(tsv[0].split("\t"), list(snap.REPORT_COLUMNS))
        self.assertTrue(tsv[1].startswith("w01\t142\t"))
        rep = json.loads((out / "snap_report.json").read_text())
        self.assertEqual(rep["meshes"][0]["n_valid"], 142)
        self.assertIn("w01\t142", text)
        # input untouched, and the output may not overwrite it
        self.assertTrue(np.array_equal(snap.load_mesh(src)[2], zs))
        code, _ = run_cli(["snap", str(src), "--volume", str(z), "--out", str(src.parent)])
        self.assertEqual(code, 2)

    def test_sham_moves_every_vertex_the_other_way(self):
        # the sheet is at z 30, the mesh at 26 with one hole: the snap moves it to 30, the sham to 22, and a vertex
        # the snap leaves alone (none here) or a hole stays where it is
        z = write_zarr(self.root / "v.zarr", slab((48, 40, 40), 29, 31))
        xs, ys, zs = plane_mesh(10, 10, 26.0)
        for a in (xs, ys, zs):
            a[4, 4] = -1.0
        src = write_mesh(self.root / "m" / "w", xs, ys, zs)
        code, text = run_cli(["snap", str(src), "--volume", str(z), "--out", str(self.root / "real")])
        self.assertEqual(code, 0, text)
        code, text = run_cli(["snap", str(src), "--volume", str(z), "--out", str(self.root / "sham"), "--sham",
                              "--json"])
        self.assertEqual(code, 0, text)
        self.assertTrue(json.loads(text)["meshes"][0]["sham"])
        real, fake = snap.load_mesh(self.root / "real" / "w"), snap.load_mesh(self.root / "sham" / "w")
        self.assertTrue(np.array_equal(real[3], fake[3]))
        self.assertFalse(fake[3][4, 4])
        v = real[3]
        self.assertTrue(np.allclose(real[2][v], 30.0, atol=1e-4))
        self.assertTrue(np.allclose(fake[2][v], 22.0, atol=1e-4))
        self.assertTrue(np.allclose(fake[0][v], xs[v]) and np.allclose(fake[1][v], ys[v]))
        meta = json.loads((self.root / "sham" / "w" / "meta.json").read_text())
        self.assertTrue(meta["snap"]["sham"])
        self.assertTrue(meta["source"].endswith(snap.SHAM_NOTE))
        self.assertNotIn("sham", json.loads((self.root / "real" / "w" / "meta.json").read_text())["snap"])
        # a sham is a written mesh, not a check
        self.assertEqual(run_cli(["snap", str(src), "--volume", str(z), "--check", "--sham"])[0], 2)

    def test_windings_layout_and_report_appends(self):
        z = write_zarr(self.root / "v.zarr", slab((48, 40, 40), 29, 31))
        for name in ("wa", "wb"):
            write_mesh(self.root / "m" / name, *plane_mesh(8, 8, 27.0))
        (self.root / "list.txt").write_text("# windings\nwa\nwb\nnot_there\n")
        out = self.root / "out"
        for _ in range(2):
            code, text = run_cli(["snap", str(self.root / "m"), "--windings", str(self.root / "list.txt"),
                                  "--volume", str(z), "--out", str(out)])
            self.assertEqual(code, 0, text)
        lines = (out / "snap_report.tsv").read_text().splitlines()
        self.assertEqual(len(lines), 5)           # one header, two rows per run
        self.assertTrue((out / "wa" / "z.tif").exists() and (out / "wb" / "z.tif").exists())

    def test_cli_errors(self):
        z = write_zarr(self.root / "v.zarr", slab((24, 24, 24), 10, 12))
        m = write_mesh(self.root / "m" / "w", *plane_mesh(4, 4, 8.0))
        self.assertEqual(run_cli(["snap", str(m), "--volume", str(z), "--out", str(self.root / "o"),
                                  "--source", "ct", "--mode", "nearest"])[0], 2)
        self.assertEqual(run_cli(["snap", str(m), "--volume", str(z), "--out", str(self.root / "o"),
                                  "--mode", "midline"])[0], 2)
        self.assertEqual(run_cli(["snap", str(m), "--volume", str(z)])[0], 2)          # no --out, no --check
        self.assertEqual(run_cli(["snap", str(self.root / "nothing"), "--volume", str(z),
                                  "--out", str(self.root / "o")])[0], 2)
        bad = write_mesh(self.root / "bad" / "w", *plane_mesh(4, 4, 11.0))
        (bad / "meta.json").write_text("{not json")
        self.assertEqual(run_cli(["snap", str(bad), "--volume", str(z), "--out", str(self.root / "ob")])[0], 2)
        self.assertFalse((self.root / "ob" / "w" / "x.tif").exists())          # no half-written mesh


@unittest.skipIf(np is None, "numpy is needed for kit snap")
class MidlineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # their RectoRefine_selftest fixture, along z: a bright band on planes 20..24 (200) in 20
        self.vol = slab((48, 40, 40), 20, 24, value=200, background=20)
        self.sm = snap.Sampler(snap.open_volume(write_zarr(self.root / "ct.zarr", self.vol)))
        self.axis = ("line", (20.0, 20.0, -400.0), (1.0, 0.0, 0.0))   # far below: outward is +z here

    def tearDown(self):
        self.tmp.cleanup()

    def mesh(self, z, H=9, W=9):
        return plane_mesh(H, W, z, step=1.0, x0=16.0, y0=16.0)

    def test_moves_onto_the_band_midline_smoothly(self):
        for z0 in (20.5, 19.0, 22.0):
            xs, ys, zs = self.mesh(z0)
            r = snap.snap_midline(xs, ys, zs, np.ones(xs.shape, bool), self.sm, {"normal_blend": 0.0}, self.axis,
                                  window=(20, 200))
            self.assertLess(abs(float(r["zs"].mean()) - 22.0), 0.2, z0)
            jump = max(np.abs(np.diff(r["zs"], axis=0)).max(), np.abs(np.diff(r["zs"], axis=1)).max())
            self.assertLess(float(jump), 0.1)
            self.assertEqual(r["recto"]["recto_supported"], 81)
            again = snap.snap_midline(r["xs"], r["ys"], r["zs"], np.ones(xs.shape, bool), self.sm,
                                      {"normal_blend": 0.0}, self.axis, window=(20, 200))
            self.assertLess(again["recto"]["recto_mean_disp"], 0.2)      # near-idempotent

    def test_abstains_beyond_the_range_and_without_a_falling_edge(self):
        xs, ys, zs = self.mesh(23.5)      # verso side: the rising edge is over 3 voxels behind
        r = snap.snap_midline(xs, ys, zs, np.ones(xs.shape, bool), self.sm, None, self.axis, window=(20, 200))
        self.assertEqual(r["recto"]["recto_supported"], 0)
        self.assertTrue(np.array_equal(r["zs"], zs))
        thick = snap.Sampler(snap.open_volume(write_zarr(self.root / "thick.zarr",
                                                         slab((48, 40, 40), 20, 47, 200, 20))))
        xs, ys, zs = self.mesh(19.0)      # a bright half-space: no falling crossing within 6 voxels
        r = snap.snap_midline(xs, ys, zs, np.ones(xs.shape, bool), thick, None, self.axis, window=(20, 200))
        self.assertEqual(r["recto"]["recto_supported"], 0)
        self.assertTrue(np.array_equal(r["zs"], zs))

    def test_sign_of_the_normal_without_an_axis(self):
        # with no axis the outward line is the stored normal, cross(d/dcol, d/drow) = +z for this grid
        xs, ys, zs = self.mesh(20.5)
        r = snap.snap_midline(xs, ys, zs, np.ones(xs.shape, bool), self.sm, None, None, window=(20, 200))
        self.assertLess(abs(float(r["zs"].mean()) - 22.0), 0.2)

    def test_holes_stay_and_window_rule(self):
        xs, ys, zs = self.mesh(20.5)
        valid = np.ones(xs.shape, bool)
        valid[4, 4] = False
        for a in (xs, ys, zs):
            a[4, 4] = -1.0
        r = snap.snap_midline(xs, ys, zs, valid, self.sm, None, self.axis, window=(20, 200))
        self.assertEqual(float(r["zs"][4, 4]), -1.0)
        self.assertLess(abs(float(r["zs"][valid].mean()) - 22.0), 0.2)
        vals = np.array([10.0] * 50 + [200.0] * 50)
        self.assertEqual(snap.stretch_window(vals, np.uint8), (10.0, 200.0))
        self.assertEqual(snap.stretch_window(np.full(10, 7.0), np.uint8), (0.0, 255.0))

    def test_occupancy_guard(self):
        start = np.array([[0, 0, 0], [5, 0, 0], [20, 0, 0]], np.float32)
        src, dst = snap._edges(np.array([[0, 1, 2]]), 3)
        occ = snap._Occupancy(start, src, dst, 0.9, 2.0)
        q = np.array([[0.2, 0, 0], [19.6, 0, 0], [4.5, 0, 0]], np.float32)
        # near itself: fine; near vertex 2 (a one-ring neighbor but 20 voxels away): hit; near vertex 1: hit
        self.assertEqual(occ.hits(np.array([0, 0, 0]), q).tolist(), [False, True, True])

    def test_cli_midline_round_trip(self):
        m = write_mesh(self.root / "m" / "band", *self.mesh(20.5))
        out = self.root / "out"
        code, text = run_cli(["snap", str(m), "--source", "ct", "--volume", str(self.root / "ct.zarr"),
                              "--out", str(out), "--window", "20", "200", "--axis-point", "20", "20", "-400",
                              "--axis-dir", "1", "0", "0", "--json"])
        self.assertEqual(code, 0, text)
        res = json.loads(text)
        self.assertEqual(res["mode"], "midline")
        self.assertIn("recto", res["meshes"][0])
        got = snap.load_mesh(out / "band")
        self.assertLess(abs(float(got[2].mean()) - 22.0), 0.2)
        meta = json.loads((out / "band" / "meta.json").read_text())
        self.assertIn("RectoRefine midline", meta["source"])
        self.assertEqual(meta["snap"]["mode"], "midline")


@unittest.skipIf(np is None, "numpy is needed for kit snap")
class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.z = write_zarr(self.root / "v.zarr", slab((56, 40, 40), 29, 31))
        self.sm = snap.Sampler(snap.open_volume(self.z))

    def tearDown(self):
        self.tmp.cleanup()

    def pred(self, *a):
        return snap.snap_pred(*a)

    def test_passes_on_a_mesh_on_the_sheet(self):
        xs, ys, zs = plane_mesh(14, 14, 30.0)
        res = snap.self_check(xs, ys, zs, np.ones(xs.shape, bool), self.sm, self.pred)
        self.assertTrue(res["passed"], res["why"])
        self.assertAlmostEqual(res["planted"]["median"], 4.0, delta=0.3)
        self.assertLess(res["recovery"]["median"], 0.5)
        self.assertGreater(res["control_shifted"]["median"], 2.0)
        self.assertTrue(res["control_empty"]["caught"])

    def test_shifted_control_puts_the_sheet_on_the_planted_side(self):
        xs, ys, zs = plane_mesh(14, 14, 30.0)              # normals +z, planted +4: the sheet must appear at z = 33
        res = snap.self_check(xs, ys, zs, np.ones(xs.shape, bool), self.sm, self.pred)
        vec = res["control_shifted"]["shift_xyz"]
        self.assertEqual(vec, [0.0, 0.0, -3.0])            # reading at p + v shows the sheet at -v
        r = snap.snap_pred(xs, ys, (zs + 4).astype(np.float32), np.ones(xs.shape, bool), self.sm.derive(shift=vec))
        self.assertTrue(np.allclose(r["zs"], 33.0, atol=1e-4))

    def test_fails_off_the_sheet_and_when_a_control_passes(self):
        xs, ys, zs = plane_mesh(14, 14, 45.0)          # 14 voxels above the sheet: the displaced mesh sees none
        res = snap.self_check(xs, ys, zs, np.ones(xs.shape, bool), self.sm, self.pred)
        self.assertFalse(res["passed"])
        self.assertFalse(res["recovery"]["passed"])

        def cheat(xs_, ys_, zs_, valid, sampler):          # returns the answer whatever the volume says
            return {"xs": xs, "ys": ys, "zs": zs}
        xs, ys, zs = plane_mesh(14, 14, 30.0)
        res = snap.self_check(xs, ys, zs, np.ones(xs.shape, bool), self.sm, cheat)
        self.assertTrue(res["recovery"]["passed"])
        self.assertFalse(res["control_shifted"]["caught"])
        self.assertFalse(res["control_empty"]["caught"])
        self.assertFalse(res["passed"])

    def test_cli_check_exit_codes(self):
        good = write_mesh(self.root / "m" / "on", *plane_mesh(12, 12, 30.0))
        bad = write_mesh(self.root / "m" / "off", *plane_mesh(12, 12, 45.0))
        code, text = run_cli(["snap", str(good), "--volume", str(self.z), "--check"])
        self.assertEqual(code, 0, text)
        self.assertIn("PASS", text)
        code, text = run_cli(["snap", str(bad), "--volume", str(self.z), "--check", "--out", str(self.root / "o")])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", text)
        rep = json.loads((self.root / "o" / "snap_check.json").read_text())
        self.assertFalse(rep["passed"])
        self.assertFalse((self.root / "o" / "off").exists())      # --check writes no meshes

    def test_cli_check_midline(self):
        ct = write_zarr(self.root / "ct.zarr", slab((48, 40, 40), 20, 24, 200, 20))
        m = write_mesh(self.root / "m" / "band", *plane_mesh(9, 9, 22.0, step=1.0, x0=16.0, y0=16.0))
        code, text = run_cli(["snap", str(m), "--source", "ct", "--volume", str(ct), "--window", "20", "200",
                              "--check", "--json"])
        self.assertEqual(code, 0, text)
        res = json.loads(text)["checks"][0]
        self.assertTrue(res["control_empty"]["caught"] and res["control_shifted"]["caught"])
        self.assertAlmostEqual(res["planted"]["median"], 2.0, delta=0.3)

    def test_planted_field_is_gentle(self):
        for shape, step in (((10, 12), 2.0), ((200, 150), 20.0)):
            f = snap.planted_field(shape, 4.0, 1.0, step, step)
            self.assertLessEqual(float(f.max()), 5.0)
            self.assertGreaterEqual(float(f.min()), 3.0)
            self.assertAlmostEqual(float(np.median(f)), 4.0, delta=0.05)
            slope = max(np.abs(np.diff(f, axis=0)).max(), np.abs(np.diff(f, axis=1)).max()) / step
            self.assertLessEqual(float(slope), snap.CHECK_MAX_SLOPE + 1e-6)
        big = snap.planted_field((200, 150), 4.0, 1.0, 20.0, 20.0)
        self.assertGreater(float(big.max() - big.min()), 1.5)          # a full period over a large mesh
        self.assertTrue(math.isclose(float(snap.planted_field((3, 3), 2.0, 0.0).std()), 0.0, abs_tol=1e-7))
        self.assertEqual(snap.grid_steps(*plane_mesh(4, 5, 1.0, step=3.0), np.ones((4, 5), bool)), [3.0, 3.0])



@unittest.skipIf(np is None or ndimage is None, "numpy and scipy are needed to run his code")
class HisPipelineTest(unittest.TestCase):
    """kit snap --source pred against his whole per-winding pipeline, bit for bit, on rough synthetic fixtures."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self):
        rng = np.random.default_rng(7)
        Z, Y, X = 40, 46, 52
        zz, yy, xx = np.meshgrid(np.arange(Z), np.arange(Y), np.arange(X), indexing="ij")
        surf = 18 + 4 * np.sin(xx / 8.0) + 0.02 * (yy - 20) ** 2
        vol = (np.abs(zz - surf) <= 1.0 + (xx % 3 == 0)) | (np.abs(zz - surf - 8) <= 1.0)
        vol[:, 18:28, 20:30] = False                          # no sheet under part of the mesh
        vol |= rng.random(vol.shape) < 0.01                   # speckle
        vol[:, :, X - 1] = True                               # the last x plane: read only inside his bounds
        vol = vol.astype(np.uint8) * np.uint8(rng.integers(1, 256, vol.shape))
        H, W = 17, 23
        r, c = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
        th = np.deg2rad(25)
        u, v = 2.3 * c, 2.9 * r
        xs = (2 + u * np.cos(th) - v * np.sin(th) + 20).astype(np.float32)   # reaches past x = 51.5
        ys = (1 + u * np.sin(th) + v * np.cos(th)).astype(np.float32)
        zs = (18 + 4 * np.sin(xs / 8.0) + 0.02 * (ys - 20) ** 2 + rng.uniform(-4, 4, (H, W))).astype(np.float32)
        zs[4, 9] += 7.0                                       # a spike for the jump rule
        for a in (xs, ys, zs):
            a[7:9, 2:5] = -1.0
            a[0, 0] = -1.0
        xs[12, 15] = np.nan
        return vol, xs, ys, zs

    def test_equals_his_pipeline(self):
        vol, xs, ys, zs = self.fixture()
        vols = snap.open_volume(write_zarr(self.root / "p.zarr", vol, levels=2))
        valid = snap.load_mesh(write_mesh(self.root / "m", xs, ys, zs))[3]
        for level in (0, 1):
            sm = snap.Sampler(vols, level=level)
            for K, jump, sigma in ((15, 6.0, 1.0), (7, 3.0, 0.6), (15, 6.0, 1.7), (10, 6.0, 0.0)):
                want = his_snap(xs, ys, zs, vol[::2 ** level, ::2 ** level, ::2 ** level], level, K, jump, sigma)
                got = snap.snap_pred(xs, ys, zs, valid, sm, K, 1.0, jump, sigma)
                key = (level, K, jump, sigma)
                self.assertTrue(np.array_equal(got["apply"], want[3]), key)
                for g, w in zip((got["xs"], got["ys"], got["zs"]), want[:3]):
                    self.assertTrue(np.array_equal(g, w, equal_nan=True), (key, np.nanmax(np.abs(g - w))))
                self.assertTrue(0 < got["apply"].sum() < valid.sum(), key)    # some vertices keep their place


@unittest.skipIf(np is None, "numpy is needed for kit snap")
class MidlineRulesTest(unittest.TestCase):
    """RectoRefine rules a port could silently lose. The numbers pinned here are what recto_refine.c (commit
    bce8a65, built with a stub sampler over the same voxels, axis and window) gives on these fixtures, and the
    window rule is surface_snap.c's stretch_window; kit snap matched them to the float32 bit. The no-axis run is
    kit's own mode (theirs always has an axis)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.axis = ("line", (20.0, 20.0, -400.0), (1.0, 0.0, 0.0))     # far below: outward is +z
        self.band = self.sampler(slab((48, 40, 40), 20, 24, 200, 20), "band.zarr")

    def tearDown(self):
        self.tmp.cleanup()

    def sampler(self, vol, name):
        return snap.Sampler(snap.open_volume(write_zarr(self.root / name, vol)))

    def mesh(self, z, H=9, W=9):
        return plane_mesh(H, W, z, step=1.0, x0=16.0, y0=16.0)

    def run_(self, sm, xs, ys, zs, opts=None, axis="default"):
        return snap.snap_midline(xs, ys, zs, np.ones(xs.shape, bool), sm, opts,
                                 self.axis if axis == "default" else axis, window=(20, 200))

    def test_total_displacement_is_capped(self):
        xs, ys, zs = self.mesh(18.6)           # the rising edge is in range, the midline 3.4 voxels away
        r = self.run_(self.band, xs, ys, zs)
        self.assertEqual(r["recto"]["recto_supported"], 81)
        self.assertLessEqual(r["recto"]["recto_max_disp"], 3.0 + 1e-5)
        self.assertTrue(np.allclose(r["zs"], 21.6, atol=1e-4))          # C: 21.599997 everywhere

    def test_band_thinner_than_min_thick_abstains(self):
        sm = self.sampler(slab((48, 40, 40), 20, 20, 200, 20), "thin.zarr")     # one plane: 1.3 voxels at 0.35
        xs, ys, zs = self.mesh(19.0)
        self.assertEqual(self.run_(sm, xs, ys, zs)["recto"]["recto_supported"], 81)
        r = self.run_(sm, xs, ys, zs, {"midline_min_thick": 2.0})
        self.assertEqual(r["recto"]["recto_supported"], 0)
        self.assertTrue(np.array_equal(r["zs"], zs))

    def test_the_axis_sets_outward_whatever_the_stored_normal(self):
        xs, ys, zs = self.mesh(20.5)
        xs, ys, zs = xs.T.copy(), ys.T.copy(), zs.T.copy()        # transposed grid: the stored normal is -z
        n, _ = snap.normals(xs, ys, zs, np.ones(xs.shape, bool))
        self.assertLess(float(n[..., 2].max()), 0.0)
        self.assertEqual(self.run_(self.band, xs, ys, zs, None, None)["recto"]["recto_supported"], 0)  # no axis
        r = self.run_(self.band, xs, ys, zs)                          # blend 0.85, flipped outward by the axis
        self.assertAlmostEqual(float(r["zs"].mean()), 21.9533, places=3)

    def test_distance_bias_prefers_the_nearer_rising_edge(self):
        vol = slab((48, 40, 40), 16, 17, 200, 20) | slab((48, 40, 40), 19, 21, 200, 20)
        xs, ys, zs = self.mesh(18.0)          # equal rising edges at -2.65 and +0.35: the nearer, band 19..21
        r = self.run_(self.sampler(vol, "two.zarr"), xs, ys, zs)
        self.assertAlmostEqual(float(r["zs"].mean()), 19.9686, places=3)

    def test_slope_limit_where_the_band_ends(self):
        vol = slab((48, 40, 40), 20, 24, 200, 20)
        vol[:, :, 21:] = 20                    # no band under x >= 21: those vertices abstain and anchor
        xs, ys, zs = self.mesh(19.5)
        r = self.run_(self.sampler(vol, "half.zarr"), xs, ys, zs)
        disp = r["zs"] - zs
        step = max(np.abs(np.diff(disp, axis=1)).max(), np.abs(np.diff(disp, axis=0)).max())
        self.assertEqual(r["recto"]["recto_slope_limited"], 54)
        self.assertAlmostEqual(float(step), 0.5890, places=3)          # C: 0.589003 (0.55 per sweep, damped)
        self.assertAlmostEqual(float(disp[:, 0].min()), 2.3722, places=3)

    def test_occupancy_guard_reverts_onto_a_fold(self):
        xs, ys, zs = self.mesh(19.0, H=12)
        xs[6:], ys[6:], zs[6:] = xs[:6], ys[:6], 20.0            # a second layer 1 voxel above the first
        r = self.run_(self.band, xs, ys, zs)
        self.assertEqual(r["recto"]["recto_reverted"], 216)
        self.assertTrue(np.array_equal(r["zs"][:6], zs[:6]))     # the lower layer cannot pass the upper one
        self.assertAlmostEqual(float(r["zs"][6:].mean()), 21.9378, places=3)

    def test_uint8_window_is_their_256_bin_rule(self):
        # 100 values 0..99: lo is the first bin past 1% (bin 1), hi the first reaching 99% (bin 98), as
        # surface_snap.c's stretch_window gives; other dtypes take numpy's interpolated percentiles
        self.assertEqual(snap.stretch_window(np.arange(100.0), np.uint8), (1.0, 98.0))
        lo, hi = snap.stretch_window(np.arange(100.0), np.uint16)
        self.assertAlmostEqual(lo, 0.99, places=9)
        self.assertAlmostEqual(hi, 98.01, places=9)


if __name__ == "__main__":
    unittest.main()
