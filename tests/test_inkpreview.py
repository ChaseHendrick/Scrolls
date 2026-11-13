"""Tests for scripts/ane/inkpreview.py and flat_contract.py: the contract functions, path mode and stack mode against
a whole-canvas map written here from villa's flat rule, the patch cache, the allow list, the HTTP server and the
backends. The model is the fake backend (a depth-weighted mean), so these test the tiling, never a model's numbers.
The inkrs backend runs against a stand-in inkrs module written here (fake_inkrs), never the real package."""
import contextlib, http.client, importlib.util, io, json, os, subprocess, sys, tempfile, threading, types, unittest
import urllib.error, urllib.parse, urllib.request
from unittest import mock

try:
    import numpy as np
except ImportError:  # pragma: no cover - the whole module needs numpy, like the other map tests
    raise unittest.SkipTest("needs numpy (python -m pip install numpy)")

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "ane", "inkpreview.py")
SPEC = importlib.util.spec_from_file_location("inkpreview", SCRIPT)
ip = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(ip)
FC = ip.FC

try:
    import torch
except ImportError:
    torch = None
try:
    import tifffile
except ImportError:
    tifffile = None
try:
    import zarr
except ImportError:
    zarr = None


# ---------------------------------------------------------------- an independent reference, from villa's rule

def ref_positions(length, patch, stride):
    """villa's patch positions on one axis: 0, stride, ... and a last one flush to the edge."""
    if length <= patch:
        return [0]
    pos = list(range(0, length - patch + 1, stride))
    if pos[-1] != length - patch:
        pos.append(length - patch)
    return pos


def ref_normalize(patch):
    """Robust normalization from its definition: clip to the 1st and 99th percentiles, subtract the median, divide
    by 1.4826 MAD (or the spread before clipping when the MAD is 0)."""
    a = np.asarray(patch, np.float32)
    std = float(a.std())
    lo, hi = np.percentile(a, [1.0, 99.0])
    a = np.clip(a, lo, hi).astype(np.float32)
    med = float(np.median(a))
    scale = 1.4826 * float(np.median(np.abs(a - med)))
    if not np.isfinite(scale) or scale < 1e-6:
        scale = next((c for c in (abs(std), abs(hi - lo) / 2.0) if np.isfinite(c) and c >= 1e-6), 1.0)
    return np.nan_to_num((a - med) / scale).astype(np.float32)


def ref_hann(n):
    """The floored Hann blend window from the Hann formula."""
    w = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1))).astype(np.float32)
    m = np.outer(w, w)
    return np.maximum(m / m.max(), 0.001).astype(np.float32)


def fake_model(depth, patch):
    fb = ip.FakeBackend(batch=1, depth=depth, patch=patch)
    return lambda x: fb(x[None, None])[0, 0]


def ref_full_map(vol, depth, patch, stride, reverse=False, model=None, exact=False):
    """A whole-canvas map by villa's flat rule: center crop of the layers to the model depth, patches at villa's
    positions (zero filled past the edge of a small canvas), all-zero patches skipped, per-patch robust
    normalization, the model, sigmoid, and a Hann-weighted mean of the overlapping patches in float32, summed in
    row-major patch order. exact: normalize and weight with flat_contract's own functions instead of the
    definitions, so the result can be compared bit for bit."""
    n, H, W = vol.shape
    start = n // 2 - depth // 2 if n > depth else 0
    layers = vol[start:start + depth]
    if reverse:
        layers = layers[::-1]
    model = model or fake_model(depth, patch)
    win = FC.hann2d(patch) if exact else ref_hann(patch)
    norm = FC.normalize_robust if exact else ref_normalize
    acc = np.zeros((H, W), np.float32)
    wsum = np.zeros((H, W), np.float32)
    for y in ref_positions(H, patch, stride):
        for x in ref_positions(W, patch, stride):
            blk = layers[:, y:y + patch, x:x + patch]
            vh, vw = blk.shape[1:]
            p = np.zeros((depth, patch, patch), vol.dtype)
            p[:, :vh, :vw] = blk
            if not p.any():
                continue
            prob = (1.0 / (1.0 + np.exp(-np.asarray(model(norm(p)), np.float32)))).astype(np.float32)
            acc[y:y + vh, x:x + vw] += prob[:vh, :vw] * win[:vh, :vw]
            wsum[y:y + vh, x:x + vw] += win[:vh, :vw]
    return np.where(wsum > 1e-6, acc / np.maximum(wsum, 1e-6), 0).astype(np.float32)


def volume(shape, dtype=np.uint8, seed=0):
    """A layer stack with structure across the canvas (so each patch normalizes differently) and a trend along
    depth (so the reversed order gives another result)."""
    rng = np.random.default_rng(seed)
    d, h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    base = 90 + 60 * np.sin(yy / 23.0) * np.cos(xx / 31.0) + 0.2 * xx
    v = base[None] + rng.normal(0, 25, shape) + 6.0 * np.arange(d)[:, None, None]
    if dtype == np.uint8:
        return np.clip(v, 1, 255).astype(np.uint8)
    return np.clip(v * 200, 1, 65535).astype(np.uint16)


class FakeSurface:
    """A surface volume held in memory, with the read method of inkpreview.Surface."""

    def __init__(self, vol):
        self.vol = vol; self.shape = vol.shape; self.dtype = vol.dtype

    def window(self, order, y0, y1, x0, x1):
        D, H, W = self.shape
        out = np.zeros((len(order), y1 - y0, x1 - x0), self.dtype)
        ya, yb, xa, xb = max(y0, 0), min(y1, H), max(x0, 0), min(x1, W)
        if ya < yb and xa < xb:
            out[:, ya - y0:yb - y0, xa - x0:xb - x0] = self.vol[list(order), ya:yb, xa:xb]
        return out


DEPTH, PATCH, STRIDE = 5, 128, 64
SEG = os.path.join(os.sep, "data", "PHerc0139", "w035")


def previewer(vol=None, depth=DEPTH, patch=PATCH, **kw):
    """A Previewer on the fake backend; with vol, its path mode reads that array whatever the segment path."""
    pv = ip.Previewer(ip.FakeBackend(batch=4, depth=depth, patch=patch), **kw)
    if vol is not None:
        pv.surface = lambda seg: FakeSurface(vol)
    return pv


def stack_query(key, cw, ch, x, y, w, h, up=None, **more):
    q = {"key": key, "cw": cw, "ch": ch, "x": x, "y": y, "w": w, "h": h}
    if up is not None:
        q.update(sx=up[0], sy=up[1], sw=up[2], sh=up[3])
    q.update(more)
    return {k: str(v) for k, v in q.items()}


def cut(vol, depth, rect):
    """The body a client uploads for a canvas rectangle (x, y, w, h): the model's layers in forward order."""
    n = vol.shape[0]
    start = n // 2 - depth // 2 if n > depth else 0
    x, y, w, h = rect
    return np.ascontiguousarray(vol[start:start + depth, y:y + h, x:x + w]).tobytes()


def rect_of(need):
    return need["x"], need["y"], need["w"], need["h"]


def quiet(fn, *args):
    """fn(*args) with what it prints kept off the test output; a SystemExit passes through."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args)


# ---------------------------------------------------------------- a stand-in for the inkrs package

def villa_map(layers, patch, stride):
    """A whole map of the layers (D, H, W), in the order given, by villa's flat rule, written here as the stand-in for
    a reader: villa's positions with the flush last patch (zero filled past the edge of an axis no longer than the
    patch), flat_contract's robust normalization per patch, a depth-weighted mean times 2 as the logit, sigmoid, the
    Hann window floored at 0.001, all-zero patches skipped, patches summed in row-major order, then trunc(255 p) to
    uint8. Returns (map, coverage, patches run)."""
    D, H, W = layers.shape
    wz = np.linspace(0.5, 1.5, D, dtype=np.float32) / np.float32(D)
    win = ref_hann(patch)
    acc = np.zeros((H, W), np.float32)
    wsum = np.zeros((H, W), np.float32)
    ran = 0
    for y in ref_positions(H, patch, stride):
        for x in ref_positions(W, patch, stride):
            blk = layers[:, y:y + patch, x:x + patch]
            vh, vw = blk.shape[1:]
            t = np.zeros((D, patch, patch), layers.dtype)
            t[:, :vh, :vw] = blk
            if not t.any():
                continue
            ran += 1
            n = FC.normalize_robust(t)
            logit = np.zeros((patch, patch), np.float32)
            for z in range(D):
                logit += n[z] * wz[z]
            p = (np.float32(1) / (np.float32(1) + np.exp(np.float32(-2) * logit))).astype(np.float32)
            acc[y:y + vh, x:x + vw] += p[:vh, :vw] * win[:vh, :vw]
            wsum[y:y + vh, x:x + vw] += win[:vh, :vw]
    prob = np.zeros((H, W), np.float32)
    np.divide(acc, wsum, out=prob, where=wsum > 1e-6)
    return (np.clip(prob, 0, 1) * np.float32(255)).astype(np.uint8), (wsum > 1e-6).astype(np.uint8), ran


def fake_inkrs():
    """A module that stands in for inkrs (installed into sys.modules by the tests): Engine reads the export's JSON
    sidecar as inkrs does (crop_size gives the patch; reader; architecture_family), refuses what inkrs refuses (not
    uint8, a side under the patch, a v8-in export in run), and Engine.run maps each (first_layer, step) window of a
    volume with villa_map. Every run is logged in engine.calls with its volume shape, window, stride and patch count.
    Set module.fail or module.load_error to an exception to make run or Engine() raise it."""
    mod = types.ModuleType("inkrs")
    mod.__version__ = "0.0.0+fake"

    class InkrsError(RuntimeError):
        pass

    class UnsupportedError(InkrsError):
        pass
    mod.InkrsError, mod.UnsupportedError = InkrsError, UnsupportedError
    mod.fail = mod.load_error = None
    mod.engines = []
    mod.build_info = lambda: {"backend": "fake"}

    class Engine:
        def __init__(self, checkpoint, *, device=0, batch_size=None, algo="find", max_workspace_mib=1024,
                     weights_dir=None, precision="fp16"):
            if mod.load_error is not None:
                raise mod.load_error
            self.weights = os.fspath(checkpoint)
            side = os.path.splitext(self.weights)[0] + ".json"
            meta = {}
            if os.path.exists(side):
                with open(side) as fh:
                    meta = json.load(fh)
            crop = meta.get("crop_size", [17, 128, 128])
            self.depth, self.patch = int(crop[0]), int(crop[-1])
            self.reader = meta.get("reader")
            self.architecture = "v8in" if meta.get("architecture_family") == "v8in" else "villa"
            self.batch_size = batch_size or (8 if self.patch == 384 else 64)
            self.device = device
            self.calls = []
            mod.engines.append(self)

        def run(self, volume, windows, *, stride=None, occupancy="auto", coverage=False, outputs=None):
            if self.architecture != "villa":
                raise UnsupportedError("Engine.run runs villa's readers")
            vol = np.asarray(volume)
            if vol.dtype != np.uint8:
                raise UnsupportedError("volume dtype %s: inkrs reads uint8 only" % vol.dtype)
            Z, H, W = vol.shape
            if H < self.patch or W < self.patch:
                raise UnsupportedError("volume %dx%d is smaller than a %d px tile" % (H, W, self.patch))
            if mod.fail is not None:
                raise mod.fail
            stride = self.patch // 2 if stride is None else int(stride)
            out = []
            for first, step in windows:
                idx = [first + step * k for k in range(self.depth)]
                if step not in (1, -1) or min(idx) < 0 or max(idx) >= Z:
                    raise ValueError("window (%d, %d) leaves the volume's %d layers" % (first, step, Z))
                m, cov, ran = villa_map(vol[idx], self.patch, stride)
                self.calls.append({"shape": vol.shape, "window": (first, step), "stride": stride, "patches": ran})
                out.append((m, cov) if coverage else m)
            return out
    mod.Engine = Engine
    return mod


def write_export(folder, name="fake-reader", crop=(17, 128, 128), sidecar=True, **more):
    """An inkrs export as the stand-in reads it: NAME.safetensors (empty) and its JSON sidecar."""
    path = os.path.join(folder, name + ".safetensors")
    open(path, "wb").close()
    if sidecar:
        with open(os.path.join(folder, name + ".json"), "w") as fh:
            json.dump(dict({"reader": name, "crop_size": list(crop)}, **more), fh)
    return path


# ---------------------------------------------------------------- the contract functions

class Contract(unittest.TestCase):
    def test_sliding_positions(self):
        self.assertEqual(FC.sliding_positions(300, 128, 64), [0, 64, 128, 172])
        self.assertEqual(FC.sliding_positions(200, 128, 64), [0, 64, 72])
        self.assertEqual(FC.sliding_positions(256, 128, 64), [0, 64, 128])
        self.assertEqual(FC.sliding_positions(128, 128, 64), [0])
        self.assertEqual(FC.sliding_positions(100, 128, 64), [0])
        self.assertEqual(FC.sliding_positions(129, 128, 64), [0, 1])
        rng = np.random.default_rng(1)
        for _ in range(500):
            length, patch = int(rng.integers(1, 900)), int(rng.choice([32, 128]))
            stride = int(rng.integers(1, patch + 1))
            pos = FC.sliding_positions(length, patch, stride)
            self.assertEqual(pos, ref_positions(length, patch, stride))
            if length > patch:
                self.assertEqual(pos[-1] + patch, length)  # flush: no patch overhangs the edge

    def test_view_positions_are_the_overlapping_ones(self):
        rng = np.random.default_rng(2)
        for _ in range(3000):
            length, patch = int(rng.integers(1, 700)), int(rng.choice([32, 128]))
            stride = int(rng.choice([8, 16, 24, 32]))
            lo = int(rng.integers(-60, length + 60)); hi = lo + int(rng.integers(1, 300))
            want = [p for p in ref_positions(length, patch, stride) if p < hi and min(p + patch, length) > lo]
            self.assertEqual(ip.view_positions(length, patch, stride, lo, hi), want, (length, patch, stride, lo, hi))

    def test_normalize_robust(self):
        rng = np.random.default_rng(3)
        cases = [rng.integers(0, 256, (5, 32, 32)).astype(np.uint8),
                 rng.integers(0, 65536, (5, 32, 32)).astype(np.uint16),
                 (rng.normal(100, 20, (5, 32, 32))).astype(np.float32)]
        half = cases[0].copy(); half[:, :, :20] = 0  # over half zeros: the median and the MAD are 0
        cases.append(half)
        for p in cases:
            got = FC.normalize_robust(p)
            self.assertEqual(got.dtype, np.float32)
            self.assertEqual(got.shape, p.shape)
            self.assertTrue(np.isfinite(got).all())
            np.testing.assert_allclose(got, ref_normalize(p), atol=1e-6)
            np.testing.assert_array_equal(got, FC._normalize_robust_direct(p))  # the histogram route is exact
        self.assertTrue((FC.normalize_robust(np.zeros((5, 8, 8), np.uint8)) == 0).all())
        self.assertTrue((FC.normalize_robust(np.full((5, 8, 8), 7, np.uint16)) == 0).all())
        self.assertGreater(float(np.abs(FC.normalize_robust(half)).max()), 0.5)  # the fallback scale, not zeros

    def test_slice_order(self):
        self.assertEqual(list(FC.slice_order((0, 7), 5, "f")), [1, 2, 3, 4, 5])
        self.assertEqual(list(FC.slice_order((0, 7), 5, "r")), [5, 4, 3, 2, 1])
        self.assertEqual(list(FC.slice_order((0, 21), 17, "f")), list(range(2, 19)))
        self.assertEqual(list(FC.slice_order((0, 28), 17, "f")), list(range(6, 23)))
        self.assertEqual(list(FC.slice_order((3, 8), 5, "f")), [3, 4, 5, 6, 7])
        with self.assertRaises(ValueError):
            FC.slice_order((0, 4), 5, "f")
        with self.assertRaises(ValueError):
            FC.slice_order((0, 5), 5, "x")

    def test_hann2d(self):
        for n in (32, 128):
            w = FC.hann2d(n)
            self.assertEqual(w.dtype, np.float32)
            np.testing.assert_allclose(w, ref_hann(n), atol=1e-6)
            self.assertAlmostEqual(float(w.min()), 0.001, places=6)
            self.assertLessEqual(float(w.max()), 1.0)
            np.testing.assert_array_equal(w, w.T)

    def test_u8_is_floor_and_png(self):
        p = np.array([[0.0, 0.5, 0.999, 1.0], [-0.2, 1.7, 1 / 255, 0.25]], np.float32)
        np.testing.assert_array_equal(ip.to_u8(p), [[0, 127, 254, 255], [0, 255, 1, 63]])  # rounding would give 128, 255, 64
        r = np.random.default_rng(4).random((40, 50)).astype(np.float32)
        np.testing.assert_array_equal(ip.to_u8(r), np.floor(r * np.float32(255)).astype(np.uint8))
        self.assertTrue(ip.png_gray(r).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(ip.encode(r, "u8")[0], ip.to_u8(r).tobytes())
        self.assertEqual(ip.encode(r, "f32")[0], r.astype("<f4").tobytes())
        self.assertEqual(ip.encode(r, "png")[1], "image/png")

    def test_upsample_identity_and_shape(self):
        y = np.arange(16, dtype=np.float32).reshape(1, 4, 4)
        self.assertIs(ip.upsample(y, 4), y)
        u = ip.upsample(y, 8)
        self.assertEqual(u.shape, (1, 8, 8))
        self.assertAlmostEqual(float(u.mean()), float(y.mean()), places=5)

    def test_importing_the_server_does_not_import_torch(self):
        code = ("import importlib.util, sys; s = importlib.util.spec_from_file_location('inkpreview', sys.argv[1]); "
                "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); print('torch' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code, SCRIPT], capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


# ---------------------------------------------------------------- path mode

class PathMode(unittest.TestCase):
    def check_canvas(self, shape, views, dtype=np.uint8):
        vol = volume(shape, dtype)
        want = ref_full_map(vol, DEPTH, PATCH, STRIDE)
        pv = previewer(vol)
        H, W = shape[1:]
        np.testing.assert_allclose(pv.preview(SEG, 0, 0, W, H), want, atol=1e-6)
        for x, y, w, h in views:
            got = previewer(vol).preview(SEG, x, y, w, h)  # a cold server for every view
            np.testing.assert_allclose(got, want[y:y + h, x:x + w], atol=1e-6, err_msg=str((shape, x, y, w, h)))
            self.assertGreater(float(got.std()), 0.01)  # a real picture, not a constant

    def test_equals_the_full_map_when_the_size_is_off_the_stride(self):
        # 300 - 128 = 172 and 200 - 128 = 72 are not multiples of 64: flush last column (172) and row (72)
        self.check_canvas((7, 200, 300), [(150, 110, 150, 90),     # touches the right and the bottom edge
                                          (37, 21, 120, 100),      # off the grid, in the interior
                                          (236, 0, 64, 200),       # the last 64 columns, all rows
                                          (0, 136, 300, 64)])      # the last 64 rows, all columns

    def test_equals_the_full_map_when_the_size_is_on_the_stride(self):
        self.check_canvas((7, 256, 320), [(200, 150, 120, 106), (33, 17, 90, 70)], np.uint16)

    def test_equals_the_full_map_on_a_canvas_smaller_than_the_patch(self):
        self.check_canvas((7, 100, 300), [(180, 30, 120, 70), (5, 0, 60, 100)])
        self.check_canvas((5, 90, 70), [(10, 20, 50, 60)])

    def test_a_view_past_the_edge_of_a_small_canvas_is_zero_there(self):
        # The one patch of a 70 by 90 canvas is zero filled to 128 by 128; only its part inside the canvas counts.
        vol = volume((5, 90, 70))
        got = previewer(vol).preview(SEG, 10, 20, 100, 100)
        self.assertEqual(got.shape, (100, 100))
        np.testing.assert_allclose(got[:70, :60], ref_full_map(vol, DEPTH, PATCH, STRIDE)[20:90, 10:70], atol=1e-6)
        self.assertTrue((got[:70, :60] > 0).all())
        self.assertTrue((got[70:] == 0).all() and (got[:, 60:] == 0).all())  # rows from 90 and columns from 70

    def test_blend_is_row_major_bit_for_bit(self):
        # Pinned to the bit: the same float32 sums in the same row-major patch order as a reference written here.
        for shape, dtype, views in (((7, 200, 300), np.uint8, [(100, 50, 120, 100), (0, 0, 300, 200)]),
                                    ((7, 256, 320), np.uint16, [(33, 17, 250, 200)])):
            vol = volume(shape, dtype)
            want = ref_full_map(vol, DEPTH, PATCH, STRIDE, exact=True)
            for x, y, w, h in views:
                np.testing.assert_array_equal(previewer(vol).preview(SEG, x, y, w, h), want[y:y + h, x:x + w])

    def test_displaced_grid_does_not_equal_the_full_map(self):
        # The control for the parity tests: the same pixels tiled on a grid moved by half a stride must differ.
        vol = volume((7, 200, 300))
        want = ref_full_map(vol, DEPTH, PATCH, STRIDE)
        s = STRIDE // 2
        moved = ref_full_map(vol[:, s:, s:], DEPTH, PATCH, STRIDE)  # grid origin at (32, 32) of the canvas
        x, y, w, h = 40, 40, 200, 120
        got = previewer(vol).preview(SEG, x, y, w, h)
        np.testing.assert_allclose(got, want[y:y + h, x:x + w], atol=1e-6)
        diff = np.abs(got - moved[y - s:y - s + h, x - s:x - s + w])
        self.assertGreater(float(diff.max()), 1e-2)
        self.assertGreater(float((diff > 1e-4).mean()), 0.5)
        self.assertFalse(np.allclose(got, moved[y - s:y - s + h, x - s:x - s + w], atol=1e-6))

    def test_reversed_control_equals_the_reversed_map_and_differs(self):
        vol = volume((7, 200, 300))
        pv = previewer(vol)
        f = pv.preview(SEG, 20, 10, 250, 180)
        r = pv.preview(SEG, 20, 10, 250, 180, variant="r")
        np.testing.assert_allclose(r, ref_full_map(vol, DEPTH, PATCH, STRIDE, reverse=True)[10:190, 20:270], atol=1e-6)
        self.assertGreater(float(np.abs(f - r).max()), 1e-2)

    def test_empty_patches_and_pixels_outside_are_zero(self):
        vol = volume((7, 200, 420))
        vol[:, :, :200] = 0  # the patches at columns 0 and 64 are all zero; the one at 128 is partly zero
        pv = previewer(vol)
        np.testing.assert_allclose(pv.preview(SEG, 0, 0, 420, 200), ref_full_map(vol, DEPTH, PATCH, STRIDE), atol=1e-6)
        self.assertTrue((pv.preview(SEG, 0, 0, 128, 200) == 0).all())   # only skipped patches cover these pixels
        self.assertTrue((pv.preview(SEG, 140, 0, 100, 200) > 0).any())
        out = pv.preview(SEG, 400, 180, 60, 50)  # reaches past the right and bottom edges
        self.assertEqual(out.shape, (50, 60))
        self.assertTrue((out[20:] == 0).all() and (out[:, 20:] == 0).all())
        self.assertTrue((out[:20, :20] > 0).all())

    def test_cache_reuses_patches_on_a_pan(self):
        pv = previewer(volume((7, 400, 600)))
        pv.preview(SEG, 0, 0, 200, 200)
        first = pv.b.patches
        _, (computed, cached) = pv.preview_path(SEG, 64, 0, 200, 200)
        self.assertGreater(cached, 0)
        self.assertLess(computed, first)
        self.assertEqual(pv.b.patches - first, computed)
        self.assertEqual(pv.stats()["hits"], cached)

    def test_result_does_not_depend_on_the_pan_history(self):
        vol = volume((7, 300, 500))
        cold = previewer(vol).preview(SEG, 90, 40, 300, 200)
        pv = previewer(vol)
        pv.preview(SEG, 250, 100, 200, 150); pv.preview(SEG, 0, 0, 180, 120)
        np.testing.assert_array_equal(pv.preview(SEG, 90, 40, 300, 200), cold)  # bit for bit

    def test_cache_cap(self):
        cap = PATCH * PATCH * 4 * 3
        pv = previewer(volume((7, 300, 400)), cache_mb=cap / 2 ** 20)
        full = pv.preview(SEG, 0, 0, 400, 300)
        self.assertLessEqual(pv.cache_bytes, cap)
        np.testing.assert_array_equal(pv.preview(SEG, 0, 0, 400, 300), full)  # evicted patches are computed again

    def test_scale_and_bad_requests(self):
        pv = previewer(volume((7, 200, 300)), max_view_px=10000)
        self.assertEqual(pv.preview(SEG, 0, 0, 64, 40, scale=4).shape, (10, 16))
        with self.assertRaises(ValueError):
            pv.preview(SEG, 0, 0, 0, 10)
        with self.assertRaises(ip.TooLarge):
            pv.preview(SEG, 0, 0, 101, 100)
        with self.assertRaises(ValueError):
            pv.preview(SEG, 0, 0, 10, 10, variant="s")
        with self.assertRaises(ValueError):
            pv.preview(SEG, 0, 0, 10, 10, window=(0, 3))  # fewer layers than the model depth

    def test_window_picks_the_layers(self):
        vol = volume((9, 200, 300))
        got = previewer(vol).preview(SEG, 0, 0, 300, 200, window=(0, 5))
        np.testing.assert_allclose(got, ref_full_map(vol[:5], DEPTH, PATCH, STRIDE), atol=1e-6)

    @unittest.skipIf(tifffile is None, "tifffile is needed to read a folder of layer TIFFs")
    def test_reads_a_layers_folder(self):
        vol = volume((7, 200, 300))
        with tempfile.TemporaryDirectory() as tmp:
            seg = os.path.join(tmp, "PHerc0139", "seg1")
            os.makedirs(os.path.join(seg, "layers"))
            for i, layer in enumerate(vol):
                tifffile.imwrite(os.path.join(seg, "layers", "%02d.tif" % i), layer)
            got = ip.Previewer(ip.FakeBackend(batch=4, depth=DEPTH, patch=PATCH)).preview(seg, 150, 110, 150, 90)
        np.testing.assert_array_equal(got, previewer(vol).preview(SEG, 150, 110, 150, 90))

    @unittest.skipIf(zarr is None, "zarr is needed to read a zarr surface volume")
    def test_reads_a_zarr(self):
        vol = volume((7, 200, 300))
        with tempfile.TemporaryDirectory() as tmp:
            seg = os.path.join(tmp, "PHerc0139", "seg1.zarr")
            g = zarr.open_group(seg, mode="w")
            make = getattr(g, "create_array", None) or g.create_dataset  # zarr 3, or zarr 2
            make("0", shape=vol.shape, dtype=vol.dtype, chunks=(7, 64, 64))[:] = vol
            got = ip.Previewer(ip.FakeBackend(batch=4, depth=DEPTH, patch=PATCH)).preview(seg, 150, 110, 150, 90)
        np.testing.assert_array_equal(got, previewer(vol).preview(SEG, 150, 110, 150, 90))


# ---------------------------------------------------------------- stack mode

class StackMode(unittest.TestCase):
    CW, CH = 300, 200
    VIEW = (100, 50, 120, 100)  # the worked example of the protocol: canvas 300 x 200, patch 128, stride 64

    def setUp(self):
        self.vol = volume((7, self.CH, self.CW))
        self.pv = previewer()

    def ask(self, pv, key, view, up=None, vol=None, cw=None, ch=None, **more):
        vol = self.vol if vol is None else vol
        q = stack_query(key, cw or self.CW, ch or self.CH, *view, up=up, **more)
        return pv.stack_request(q, cut(vol, pv.D, up) if up else b"")

    def test_empty_cache_names_the_rectangle_to_upload(self):
        with self.assertRaises(ip.NeedStack) as cm:
            self.ask(self.pv, "k1", self.VIEW)
        # columns 0, 64, 128, 172 and rows 0, 64, 72 overlap the view: the whole canvas is needed
        self.assertEqual(cm.exception.need, {"x": 0, "y": 0, "w": 300, "h": 200})
        self.assertEqual(cm.exception.depth, DEPTH)
        self.assertEqual(cm.exception.missing, 12)
        self.assertEqual(self.pv.b.patches, 0)  # nothing was computed
        self.assertEqual(self.pv.stats()["tiles"], 0)

    def test_upload_gives_the_view_and_equals_path_mode_bit_for_bit(self):
        with self.assertRaises(ip.NeedStack) as cm:
            self.ask(self.pv, "k1", self.VIEW)
        prob, tiles, fmt = self.ask(self.pv, "k1", self.VIEW, up=rect_of(cm.exception.need), format="f32")
        x, y, w, h = self.VIEW
        self.assertEqual((prob.shape, prob.dtype, tiles, fmt), ((h, w), np.float32, (12, 0), "f32"))
        np.testing.assert_array_equal(prob, previewer(self.vol).preview(SEG, x, y, w, h))  # bit for bit
        np.testing.assert_allclose(prob, ref_full_map(self.vol, DEPTH, PATCH, STRIDE)[y:y + h, x:x + w], atol=1e-6)
        again, tiles, _ = self.ask(self.pv, "k1", self.VIEW, format="f32")  # no body: all twelve patches are cached
        self.assertEqual(tiles, (0, 12))
        np.testing.assert_array_equal(again, prob)

    def test_uint16_upload_equals_path_mode(self):
        vol = volume((7, self.CH, self.CW), np.uint16)
        prob, _, _ = self.ask(self.pv, "k16", (150, 110, 150, 90), up=(0, 0, 300, 200), vol=vol, dtype="uint16")
        np.testing.assert_array_equal(prob, previewer(vol).preview(SEG, 150, 110, 150, 90))

    def test_a_pan_needs_only_the_new_strip(self):
        cw, ch = 1000, 600
        vol = volume((7, ch, cw))
        want = ref_full_map(vol, DEPTH, PATCH, STRIDE)
        with self.assertRaises(ip.NeedStack) as cm:
            self.ask(self.pv, "k", (100, 50, 120, 100), vol=vol, cw=cw, ch=ch)
        self.assertEqual(cm.exception.need, {"x": 0, "y": 0, "w": 320, "h": 256})  # columns 0..192, rows 0..128
        a, tiles, _ = self.ask(self.pv, "k", (100, 50, 120, 100), up=(0, 0, 320, 256), vol=vol, cw=cw, ch=ch, format="f32")
        self.assertEqual(tiles, (12, 0))
        np.testing.assert_allclose(a, want[50:150, 100:220], atol=1e-6)
        with self.assertRaises(ip.NeedStack) as cm:  # pan 200 px right: column 192 is cached, 256, 320, 384 are new
            self.ask(self.pv, "k", (300, 50, 120, 100), vol=vol, cw=cw, ch=ch)
        self.assertEqual(cm.exception.need, {"x": 256, "y": 0, "w": 256, "h": 256})
        self.assertEqual(cm.exception.missing, 9)
        b, tiles, _ = self.ask(self.pv, "k", (300, 50, 120, 100), up=(256, 0, 256, 256), vol=vol, cw=cw, ch=ch, format="f32")
        self.assertEqual(tiles, (9, 3))
        np.testing.assert_allclose(b, want[50:150, 300:420], atol=1e-6)
        np.testing.assert_array_equal(b, previewer(vol).preview(SEG, 300, 50, 120, 100))  # same as a cold path view

    def test_a_diagonal_pan_needs_the_bounding_box_of_the_new_patches(self):
        # One rectangle per 409: the new patches of a diagonal pan form an L, and need is its bounding box.
        cw, ch = 1300, 1200
        vol = volume((7, ch, cw))
        with self.assertRaises(ip.NeedStack) as cm:
            self.ask(self.pv, "k", (300, 300, 300, 300), vol=vol, cw=cw, ch=ch)
        self.assertEqual(cm.exception.need, {"x": 192, "y": 192, "w": 512, "h": 512})  # positions 192..576 each way
        self.ask(self.pv, "k", (300, 300, 300, 300), up=(192, 192, 512, 512), vol=vol, cw=cw, ch=ch)
        with self.assertRaises(ip.NeedStack) as cm:  # 100 px right and down: column 640 and row 640 are new
            self.ask(self.pv, "k", (400, 400, 300, 300), vol=vol, cw=cw, ch=ch)
        self.assertEqual((cm.exception.need, cm.exception.missing), ({"x": 320, "y": 320, "w": 448, "h": 448}, 11))
        got, tiles, _ = self.ask(self.pv, "k", (400, 400, 300, 300), up=(320, 320, 448, 448), vol=vol, cw=cw, ch=ch,
                                 format="f32")
        self.assertEqual(tiles, (11, 25))
        np.testing.assert_array_equal(got, previewer(vol).preview(SEG, 400, 400, 300, 300))

    def test_two_viewers_that_evict_each_other_get_their_views(self):
        # A cache of 16 patches. Viewer B's request evicts viewer A's patches between A's 409 and A's upload. The
        # next 409 asks for every patch A's view lacks, the ones A just uploaded included, so A's next upload is
        # enough. (A need of only the patches outside A's upload made A and the cache trade 409s forever.)
        cw = ch = 1000
        vol = volume((7, ch, cw))
        pv = previewer(cache_mb=16 * PATCH * PATCH * 4 / 2 ** 20)

        def view(key, rect, up=None):
            try:
                return self.ask(pv, key, rect, up=up, vol=vol, cw=cw, ch=ch, format="f32")
            except ip.NeedStack as e:
                return e

        a = (64, 0, 200, 200)
        self.assertIsInstance(view("A", (0, 0, 200, 200), up=(0, 0, 320, 320)), tuple)  # 16 patches, now cached
        need = view("A", a)
        self.assertEqual((need.need, need.missing), ({"x": 256, "y": 0, "w": 128, "h": 320}, 4))  # column 256 is new
        b = (500, 500, 200, 200)
        self.assertEqual(view("B", b, up=rect_of(view("B", b).need))[1], (25, 0))  # 25 patches evict all of A's
        again = view("A", a, up=rect_of(need.need))
        self.assertIsInstance(again, ip.NeedStack)
        self.assertEqual((again.need, again.missing), ({"x": 0, "y": 0, "w": 384, "h": 320}, 20))
        got = view("A", a, up=rect_of(again.need))
        self.assertIsInstance(got, tuple)
        self.assertEqual(got[1], (20, 0))
        np.testing.assert_array_equal(got[0], previewer(vol).preview(SEG, *a))
        self.assertLessEqual(len(pv.cache), 16)

    def test_a_different_key_shares_nothing(self):
        self.ask(self.pv, "k1", self.VIEW, up=(0, 0, 300, 200))
        with self.assertRaises(ip.NeedStack) as cm:
            self.ask(self.pv, "k2", self.VIEW)
        self.assertEqual((cm.exception.need, cm.exception.missing), ({"x": 0, "y": 0, "w": 300, "h": 200}, 12))
        other = volume((7, self.CH, self.CW), seed=9)  # other voxels under the other key
        b, tiles, _ = self.ask(self.pv, "k2", self.VIEW, up=(0, 0, 300, 200), vol=other, format="f32")
        self.assertEqual(tiles, (12, 0))
        a, tiles, _ = self.ask(self.pv, "k1", self.VIEW, format="f32")
        self.assertEqual(tiles, (0, 12))
        self.assertGreater(float(np.abs(a - b).max()), 1e-2)
        with self.assertRaises(ip.NeedStack):  # the same key on another canvas size shares nothing either
            self.ask(self.pv, "k1", self.VIEW, cw=301)
        # A view that touches only patch (0, 0), whose position is the same on every one of these canvases: only the
        # canvas size in the cache key keeps it apart.
        self.assertEqual(self.ask(self.pv, "k1", (0, 0, 50, 50))[1], (0, 1))
        for cw, ch in ((300, 199), (299, 200), (301, 200)):
            with self.assertRaises(ip.NeedStack, msg=str((cw, ch))) as cm:
                self.ask(self.pv, "k1", (0, 0, 50, 50), cw=cw, ch=ch)
            self.assertEqual((cm.exception.need, cm.exception.missing), ({"x": 0, "y": 0, "w": 128, "h": 128}, 1))

    def test_stack_view_is_row_major_bit_for_bit(self):
        # Stack mode against the reference written here, to the bit, forward and reversed, uint8 and uint16.
        for dtype in (np.uint8, np.uint16):
            vol = volume((7, self.CH, self.CW), dtype)
            pv = previewer()
            for variant in ("f", "r"):
                want = ref_full_map(vol, DEPTH, PATCH, STRIDE, reverse=(variant == "r"), exact=True)
                for x, y, w, h in (self.VIEW, (0, 0, 300, 200), (150, 110, 150, 90)):
                    got, _, _ = self.ask(pv, "k", (x, y, w, h), up=(0, 0, 300, 200), vol=vol, format="f32",
                                         variant=variant, dtype=np.dtype(dtype).name)
                    np.testing.assert_array_equal(got, want[y:y + h, x:x + w], err_msg=str((dtype, variant, x, y)))

    def test_variant_r_equals_the_reversed_map_and_differs_from_forward(self):
        x, y, w, h = self.VIEW
        f, _, _ = self.ask(self.pv, "k1", self.VIEW, up=(0, 0, 300, 200), format="f32")
        with self.assertRaises(ip.NeedStack):  # the reversed view has its own cache entries
            self.ask(self.pv, "k1", self.VIEW, variant="r")
        r, _, _ = self.ask(self.pv, "k1", self.VIEW, up=(0, 0, 300, 200), variant="r", format="f32")
        rev = ref_full_map(self.vol, DEPTH, PATCH, STRIDE, reverse=True)
        np.testing.assert_allclose(r, rev[y:y + h, x:x + w], atol=1e-6)
        np.testing.assert_array_equal(r, previewer(self.vol).preview(SEG, x, y, w, h, variant="r"))
        self.assertGreater(float(np.abs(r - f).max()), 1e-2)
        self.assertFalse(np.allclose(r, f, atol=1e-6))

    def test_u8_is_floor_of_255_p(self):
        f, _, _ = self.ask(self.pv, "k1", self.VIEW, up=(0, 0, 300, 200), format="f32")
        u, _, fmt = self.ask(self.pv, "k1", self.VIEW)
        self.assertEqual(fmt, "u8")  # the default in stack mode
        body, ctype = ip.encode(u, fmt)
        got = np.frombuffer(body, np.uint8).reshape(f.shape)
        np.testing.assert_array_equal(got, np.floor(f * np.float32(255)).astype(np.uint8))
        self.assertTrue((got != np.rint(f * 255).astype(np.uint8)).any())  # not rounding to nearest

    def test_canvas_smaller_than_the_patch_is_zero_filled(self):
        vol = volume((7, 90, 70))
        with self.assertRaises(ip.NeedStack) as cm:
            self.ask(self.pv, "small", (10, 20, 50, 60), vol=vol, cw=70, ch=90)
        self.assertEqual((cm.exception.need, cm.exception.missing), ({"x": 0, "y": 0, "w": 70, "h": 90}, 1))
        got, _, _ = self.ask(self.pv, "small", (10, 20, 50, 60), up=(0, 0, 70, 90), vol=vol, cw=70, ch=90, format="f32")
        np.testing.assert_allclose(got, ref_full_map(vol, DEPTH, PATCH, STRIDE)[20:80, 10:60], atol=1e-6)

    def test_an_upload_that_misses_a_patch_computes_nothing(self):
        with self.assertRaises(ip.NeedStack) as cm:
            self.ask(self.pv, "k1", self.VIEW, up=(0, 0, 200, 200))  # the patches at columns 128 and 172 stick out
        # need covers every patch that is not cached, the six this upload covers too: the next upload replaces it
        self.assertEqual(cm.exception.need, {"x": 0, "y": 0, "w": 300, "h": 200})
        self.assertEqual(cm.exception.missing, 12)
        self.assertEqual(self.pv.b.patches, 0)
        _, tiles, _ = self.ask(self.pv, "k1", self.VIEW, up=rect_of(cm.exception.need))
        self.assertEqual(tiles, (12, 0))
        # Cached patches stay out of need: on a 600 px wide canvas the view (200, 0, 200, 200) has columns 128 to
        # 384; 128 and 192 are cached from the first view, and an upload of column 256 alone leaves 320 and 384 out.
        vol = volume((7, 200, 600))
        self.ask(self.pv, "w", (0, 0, 200, 200), up=(0, 0, 320, 200), vol=vol, cw=600)
        with self.assertRaises(ip.NeedStack) as cm:
            self.ask(self.pv, "w", (200, 0, 200, 200), up=(256, 0, 128, 200), vol=vol, cw=600)
        self.assertEqual((cm.exception.need, cm.exception.missing), ({"x": 256, "y": 0, "w": 256, "h": 200}, 9))
        _, tiles, _ = self.ask(self.pv, "w", (200, 0, 200, 200), up=(256, 0, 256, 200), vol=vol, cw=600)
        self.assertEqual(tiles, (9, 6))

    def test_empty_patches_are_cached_as_empty(self):
        vol = self.vol.copy(); vol[:, :, :200] = 0
        got, tiles, _ = self.ask(self.pv, "z", (0, 0, 300, 200), up=(0, 0, 300, 200), vol=vol, format="f32")
        self.assertEqual(tiles, (12, 0))
        self.assertEqual(self.pv.b.patches, 6)  # columns 0 and 64 hold only zeros and never reach the model
        self.assertTrue((got[:, :128] == 0).all())
        _, tiles, _ = self.ask(self.pv, "z", (0, 0, 100, 60))
        self.assertEqual(tiles, (0, 2))  # the two empty patches of row 0, straight from the cache

    def test_413_over_max_view_px(self):
        pv = previewer(max_view_px=10000)
        with self.assertRaisesRegex(ip.TooLarge, "over max_view_px 10000"):
            self.ask(pv, "k", (0, 0, 101, 100))
        with self.assertRaises(ip.NeedStack):
            self.ask(pv, "k", (0, 0, 100, 100))
        self.assertEqual(pv.max_upload_px, 2 * 10000 + 16 * 128 * 128)
        big = np.zeros((DEPTH, 600, 1000), np.uint8)
        with self.assertRaisesRegex(ip.TooLarge, "upload has 600000 px"):  # an upload far larger than any view needs
            self.ask(pv, "k", (0, 0, 100, 100), up=(0, 0, 1000, 600), vol=big, cw=1000, ch=600)
        with self.assertRaisesRegex(ip.TooLarge, "needs an upload"):       # a 10000 x 1 view: its patches cover 1.28 Mpx
            self.ask(pv, "k", (0, 0, 10000, 1), cw=10000, ch=600)
        self.assertEqual(pv.b.patches, 0)

    def test_400_bad_requests(self):
        ok = stack_query("k", 300, 200, 100, 50, 120, 100, up=(0, 0, 300, 200))
        body = cut(self.vol, DEPTH, (0, 0, 300, 200))
        for change, text in (({"__body": body[:-1]}, "bytes"), ({"__body": body + b"\0"}, "bytes"),
                             ({"__body": b""}, "bytes"), ({"dtype": "uint16"}, "bytes"),
                             ({"dtype": "float32"}, "dtype"), ({"sw": None}, "sx, sy, sw and sh"),
                             ({"key": None}, "key"), ({"key": "k" * 201}, "key"), ({"w": None}, "w is required"),
                             ({"x": "ten"}, "integer"), ({"x": "250"}, "inside the canvas"),
                             ({"w": "0"}, "at least 1 px"), ({"variant": "s"}, "variant"),
                             ({"format": "jpg"}, "format"), ({"cw": "0"}, "inside the canvas|at least 1"),
                             ({"sx": "100"}, "inside the canvas")):
            q = dict(ok); b = change.pop("__body", body)
            for k, v in change.items():
                if v is None:
                    q.pop(k)
                else:
                    q[k] = v
            with self.assertRaisesRegex(ValueError, text, msg=str(change)) as cm:
                self.pv.stack_request(q, b)
            self.assertNotIsInstance(cm.exception, ip.TooLarge)
        self.assertEqual(self.pv.b.patches, 0)

    def test_403_from_the_allow_list(self):
        pv = previewer(allow="PHerc0139,ScrollX")
        with self.assertRaisesRegex(ip.Refused, "no scroll parameter"):
            self.ask(pv, "k", self.VIEW)
        with self.assertRaisesRegex(ip.Refused, "PHerc0841 is not on the preview allow list"):
            self.ask(pv, "k", self.VIEW, scroll="PHerc0841")
        for name in ("PHerc0139", "pherc139", "scrollx"):
            with self.assertRaises(ip.NeedStack):
                self.ask(pv, "k", self.VIEW, scroll=name)
        with self.assertRaises(ip.NeedStack):  # no allow list: no scroll needed
            self.ask(self.pv, "k", self.VIEW)


# ---------------------------------------------------------------- the allow list and extra guards

class Allow(unittest.TestCase):
    def tearDown(self):
        del ip.EXTRA_GUARDS[:]

    def test_scroll_ids(self):
        self.assertEqual(ip.scroll_id("pherc_139"), "PHerc0139")
        self.assertEqual(ip.scroll_id(" pherc9001b "), "PHerc9001B")
        self.assertEqual(ip.scroll_id("ScrollX"), "ScrollX")
        self.assertIsNone(ip.scroll_id(""))
        self.assertEqual(ip.scroll_of("/x/PHerc139/w035"), "PHerc0139")
        self.assertEqual(ip.scroll_of("/x/pherc_9001b/seg"), "PHerc9001B")
        self.assertIsNone(ip.scroll_of("/x/seg"))
        self.assertIsNone(ip.parse_allow("any"))
        self.assertIsNone(ip.parse_allow(None))
        self.assertEqual(ip.parse_allow("pherc139, ScrollX"), ("PHerc0139", "ScrollX"))
        self.assertEqual(ip.parse_allow(["PHerc0841"]), ("PHerc0841",))
        with self.assertRaises(ValueError):
            ip.parse_allow(" , ")

    def test_path_mode(self):
        vol = volume((7, 200, 300))
        pv = previewer(vol, allow="PHerc0139,ScrollX")
        self.assertEqual(pv.preview("/data/PHerc0139/w035", 0, 0, 10, 10).shape, (10, 10))
        self.assertEqual(pv.preview("/data/scrollx/seg", 0, 0, 10, 10).shape, (10, 10))
        with self.assertRaisesRegex(ip.Refused, "PHerc0841 is not on the preview allow list PHerc0139,ScrollX"):
            pv.preview("/data/PHerc0841/w00", 0, 0, 10, 10)
        with self.assertRaisesRegex(ip.Refused, "no scroll id in the path"):
            pv.preview("/data/seg", 0, 0, 10, 10)
        # the last PHerc id in a path is its scroll, whatever folders sit above it
        with self.assertRaisesRegex(ip.Refused, "PHerc0841 is not on the preview allow list"):
            pv.preview("/data/PHerc0139/copies/PHerc0841/w00", 0, 0, 10, 10)
        with self.assertRaisesRegex(ip.Refused, "PHerc0841 is not on the preview allow list"):
            pv.preview("/data/ScrollX/PHerc0841/w00", 0, 0, 10, 10)
        self.assertEqual(ip.scroll_in_path("/data/PHerc0841/PHerc0139/seg", ("PHerc0139",)), "PHerc0139")
        self.assertEqual(ip.scroll_in_path("/data/Scrollx/seg", ("ScrollX",)), "ScrollX")
        self.assertIsNone(ip.scroll_in_path("/data/Scrollx/seg"))
        self.assertEqual(previewer(vol).preview("/data/seg", 0, 0, 10, 10).shape, (10, 10))  # default: any

    def test_extra_guards_see_the_request_and_can_refuse(self):
        seen = []

        def rule(info):
            seen.append(info)
            if info["query"].get("surface") == "closed":
                raise ip.Refused("closed by a wrapper rule")
        ip.EXTRA_GUARDS.append(rule)
        pv = previewer(volume((7, 200, 300)), allow="PHerc0139")
        q = stack_query("k", 300, 200, 0, 0, 10, 10, scroll="pherc139", surface="open")
        with self.assertRaises(ip.NeedStack):
            pv.stack_request(q)
        self.assertEqual((seen[-1]["mode"], seen[-1]["scroll"], seen[-1]["key"], seen[-1]["segment"]),
                         ("stack", "PHerc0139", "k", None))
        self.assertEqual(seen[-1]["query"]["surface"], "open")
        self.assertEqual(seen[-1]["allow"], ("PHerc0139",))
        with self.assertRaisesRegex(ip.Refused, "closed by a wrapper rule"):
            pv.stack_request(dict(q, surface="closed"))
        pv.preview("/data/PHerc0139/w035", 0, 0, 10, 10)
        self.assertEqual((seen[-1]["mode"], seen[-1]["scroll"], seen[-1]["key"]), ("path", "PHerc0139", None))
        self.assertEqual(seen[-1]["segment"], os.path.abspath("/data/PHerc0139/w035"))
        with self.assertRaisesRegex(ip.Refused, "closed by a wrapper rule"):
            pv.path_request({"segment": "/data/PHerc0139/w035", "x": 0, "y": 0, "w": 5, "h": 5, "surface": "closed"})

    def test_check_command_exit_codes(self):
        self.assertEqual(quiet(ip.main, ["check", "--segment", "/data/seg"]), 0)
        self.assertEqual(quiet(ip.main, ["check", "--segment", "/data/PHerc0139/a", "--allow", "PHerc0139,PHerc0841"]), 0)
        self.assertEqual(quiet(ip.main, ["check", "--segment", "/data/PHerc0841/a", "--allow", "PHerc0139"]), 3)
        self.assertEqual(quiet(ip.main, ["check", "--segment", "/data/seg", "--allow", "PHerc0139"]), 3)
        with self.assertRaises(SystemExit):
            quiet(ip.main, ["check", "--segment", "/data/seg", "--allow", ","])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ip.main(["check", "--segment", "/data/PHerc0841/a", "--allow", "PHerc0139"])
        self.assertEqual(out.getvalue(), "refused: PHerc0841 is not on the preview allow list PHerc0139\n")

    def test_a_start_with_no_allow_list_says_so(self):
        def stderr_of(argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                ip.main(argv)
            return out.getvalue(), err.getvalue()
        out, err = stderr_of(["check", "--segment", "/data/PHerc0841/a"])
        self.assertEqual(out, "ok: PHerc0841 may preview\n")  # stdout is unchanged
        self.assertIn("no allow list and no extra rules: every scroll may preview", err)
        self.assertEqual(stderr_of(["check", "--segment", "/data/PHerc0139/a", "--allow", "PHerc0139"])[1], "")
        ip.EXTRA_GUARDS.append(lambda info: None)  # a wrapper's rules: then it is not the unrestricted server
        self.assertEqual(stderr_of(["check", "--segment", "/data/PHerc0139/a"])[1], "")


# ---------------------------------------------------------------- the HTTP server

class Server(unittest.TestCase):
    def setUp(self):
        from http.server import ThreadingHTTPServer
        self.vol = volume((7, 200, 300))
        self.pv = previewer(self.vol, model_name="ink_9um", voxel_um=9.36)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), ip.make_handler(self.pv))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()

    def post(self, path, body=b""):
        """(status, headers, body) of a POST, errors included."""
        try:
            r = urllib.request.urlopen(urllib.request.Request(self.base + path, data=body, method="POST"))
            return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def query(self, view=(100, 50, 120, 100), up=None, **more):
        return "/preview?" + urllib.parse.urlencode(stack_query("k1", 300, 200, *view, up=up, **more))

    def test_health(self):
        h = json.load(urllib.request.urlopen(self.base + "/health"))
        for k, v in (("service", "ink-preview"), ("api", 1), ("backend", "fake"), ("model", "ink_9um"), ("patch", 128),
                     ("stride", 64), ("depth", DEPTH), ("voxel_um", 9.36), ("max_view_px", 16777216),
                     ("input_shape", [4, 1, DEPTH, 128, 128]), ("output_shape", [4, 1, 128, 128]), ("allow", ["any"])):
            self.assertEqual(h[k], v, k)
        self.assertEqual(sorted(h["cache"]), ["cap_mb", "hits", "mb", "misses", "tiles"])
        self.assertIsNone(previewer().health()["voxel_um"])

    def test_stack_mode_end_to_end(self):
        code, headers, body = self.post(self.query())
        self.assertEqual(code, 409)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body), {"need": {"x": 0, "y": 0, "w": 300, "h": 200}, "depth": DEPTH, "missing": 12})
        up = (0, 0, 300, 200)
        code, headers, body = self.post(self.query(up=up, dtype="uint8"), cut(self.vol, DEPTH, up))
        self.assertEqual(code, 200)
        self.assertEqual((headers["X-Shape"], headers["X-Backend"], headers["X-Tiles"]), ("100,120", "fake", "12,0"))
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        u8 = np.frombuffer(body, np.uint8).reshape(100, 120)
        code, headers, body = self.post(self.query(format="f32"))  # cached now: no body needed
        self.assertEqual((code, headers["X-Tiles"]), (200, "0,12"))
        f32 = np.frombuffer(body, "<f4").reshape(100, 120)
        np.testing.assert_allclose(f32, ref_full_map(self.vol, DEPTH, PATCH, STRIDE)[50:150, 100:220], atol=1e-6)
        np.testing.assert_array_equal(u8, np.floor(f32 * np.float32(255)).astype(np.uint8))
        code, headers, body = self.post(self.query(format="png"))
        self.assertEqual((code, headers["Content-Type"]), (200, "image/png"))
        self.assertTrue(body.startswith(b"\x89PNG"))
        code, headers, body = self.post(self.query(variant="r"))
        self.assertEqual(code, 409)

    def test_path_mode_end_to_end(self):
        req = {"segment": SEG, "x": 150, "y": 110, "w": 150, "h": 90}
        code, headers, body = self.post("/preview", json.dumps(req).encode())
        self.assertEqual((code, headers["X-Shape"], headers["X-Backend"], headers["X-Tiles"]), (200, "90,150", "fake", "9,0"))
        a = np.frombuffer(body, "<f4").reshape(90, 150)
        np.testing.assert_allclose(a, ref_full_map(self.vol, DEPTH, PATCH, STRIDE)[110:200, 150:300], atol=1e-6)
        code, headers, body = self.post("/preview", json.dumps(dict(req, format="png")).encode())
        self.assertTrue(code == 200 and body.startswith(b"\x89PNG"))
        code, headers, body = self.post("/preview", json.dumps(dict(req, format="u8")).encode())
        np.testing.assert_array_equal(np.frombuffer(body, np.uint8).reshape(90, 150), ip.to_u8(a))

    def test_error_statuses(self):
        self.pv.allow = ip.parse_allow("PHerc0139")
        code, _, body = self.post(self.query(scroll="PHerc0841"))
        self.assertEqual(code, 403)
        self.assertIn("allow list", json.loads(body)["refused"])
        code, _, body = self.post("/preview", json.dumps({"segment": "/data/PHerc0841/w00", "x": 0, "y": 0, "w": 5, "h": 5}).encode())
        self.assertEqual(code, 403)
        self.assertIn("PHerc0841", json.loads(body)["refused"])
        self.pv.allow = None
        self.pv.max_view_px = 10000
        code, _, body = self.post(self.query(view=(0, 0, 120, 100)))
        self.assertEqual(code, 413)
        self.assertIn("max_view_px", json.loads(body)["error"])
        code, _, body = self.post("/preview", json.dumps({"segment": SEG, "x": 0, "y": 0, "w": 120, "h": 100}).encode())
        self.assertEqual(code, 413)
        up = (0, 0, 300, 200)
        code, _, body = self.post(self.query(view=(0, 0, 50, 50), up=up), cut(self.vol, DEPTH, up)[:-7])
        self.assertEqual(code, 400)
        self.assertIn("bytes", json.loads(body)["error"])
        code, _, body = self.post(self.query(view=(280, 0, 50, 50)))
        self.assertEqual(code, 400)
        code, _, body = self.post("/preview", b"{not json")
        self.assertEqual(code, 400)
        code, _, body = self.post("/preview", json.dumps({"x": 0, "y": 0, "w": 5, "h": 5}).encode())
        self.assertEqual(code, 400)
        self.assertIn("segment", json.loads(body)["error"])
        code, _, body = self.post("/nothing?key=k")
        self.assertEqual(code, 404)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/nothing")
        self.assertEqual(cm.exception.code, 404)
        code, _, body = self.post(self.query(view=(0, 0, 50, 50)))  # the server is still up
        self.assertEqual(code, 409)

    def test_missing_segment_is_a_400(self):
        del self.pv.surface  # back to the real reader
        code, _, body = self.post("/preview", json.dumps({"segment": "/nonexistent/seg", "x": 0, "y": 0, "w": 5, "h": 5}).encode())
        self.assertEqual((code, json.loads(body)), (400, {"error": "no surface volume at /nonexistent/seg"}))

    def test_500_keeps_the_server_up(self):
        def broken(seg):
            raise RuntimeError("disk went away")
        self.pv.surface = broken
        code, _, body = self.post("/preview", json.dumps({"segment": SEG, "x": 0, "y": 0, "w": 5, "h": 5}).encode())
        self.assertEqual(code, 500)
        self.assertIn("disk went away", json.loads(body)["error"])
        self.assertEqual(json.load(urllib.request.urlopen(self.base + "/health"))["api"], 1)

    def test_one_connection_serves_many_requests(self):
        self.pv.max_body = 1000
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        for _ in range(2):
            c.request("GET", "/health"); r = c.getresponse()
            self.assertEqual((r.status, json.loads(r.read())["api"]), (200, 1))
            c.request("POST", self.query()); r = c.getresponse()
            self.assertEqual((r.status, json.loads(r.read())["missing"]), (409, 12))
            c.request("POST", self.query(up=(0, 0, 300, 200)), body=b"\0" * 2000); r = c.getresponse()
            self.assertEqual(r.status, 413)  # a body over the limit is dropped unread into memory; the connection goes on
            self.assertIn("over the limit", json.loads(r.read())["error"])
        c.close()

    def test_chunked_upload_is_read_like_one_with_a_length(self):
        up = (0, 0, 300, 200)
        body = cut(self.vol, DEPTH, up)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        pieces = [body[i:i + 70001] for i in range(0, len(body), 70001)]
        c.request("POST", self.query(up=up, format="f32"), body=iter(pieces))  # no length given: sent chunked
        r = c.getresponse()
        got = r.read()
        self.assertEqual((r.status, r.headers["X-Tiles"]), (200, "12,0"))
        np.testing.assert_array_equal(np.frombuffer(got, "<f4").reshape(100, 120),
                                      previewer(self.vol).preview(SEG, 100, 50, 120, 100))
        c.request("GET", "/health"); r = c.getresponse()  # the same connection goes on
        self.assertEqual((r.status, json.loads(r.read())["api"]), (200, 1))
        c.putrequest("POST", self.query(up=up)); c.putheader("Transfer-Encoding", "chunked"); c.endheaders()
        c.send(b"zz\r\nnot a chunk\r\n")
        r = c.getresponse()
        self.assertEqual(r.status, 400)
        self.assertIn("malformed", json.loads(r.read())["error"])
        c.close()
        self.assertEqual(json.load(urllib.request.urlopen(self.base + "/health"))["api"], 1)

    def test_serve_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = os.path.join(tmp, "stack.bin")
            vol = volume((5, 64, 80))
            vol.tofile(body)
            p = subprocess.Popen([sys.executable, SCRIPT, "serve", "--backend", "fake", "--port", "0",
                                  "--input-shape", "2,1,5,32,32", "--model-name", "ink_9um"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                line = p.stdout.readline()
                self.assertIn("inkpreview serving http://127.0.0.1:", line, p.stderr.read() if not line else "")
                base = line.split()[2]
                h = json.load(urllib.request.urlopen(base + "/health"))
                self.assertEqual((h["backend"], h["model"], h["voxel_um"], h["patch"], h["stride"], h["depth"]),
                                 ("fake", "ink_9um", 9.36, 32, 16, 5))
                url = base + "/preview?" + urllib.parse.urlencode(
                    stack_query("k", 80, 64, 10, 8, 50, 40, up=(0, 0, 80, 64), format="f32"))
                with open(body, "rb") as fh:
                    r = urllib.request.urlopen(urllib.request.Request(url, data=fh.read(), method="POST"))
                got = np.frombuffer(r.read(), "<f4").reshape(40, 50)
                self.assertEqual(r.headers["X-Shape"], "40,50")
                np.testing.assert_allclose(got, ref_full_map(vol, 5, 32, 16)[8:48, 10:60], atol=1e-6)
            finally:
                p.terminate(); p.wait(timeout=30)
                p.stdout.close(); p.stderr.close()


# ---------------------------------------------------------------- snapshot and the backends

class Commands(unittest.TestCase):
    def test_snapshot_png_and_refusal(self):
        vol = volume((7, 200, 300))
        real = ip.Surface
        ip.Surface = lambda path: FakeSurface(vol)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "view.png")
                args = ["snapshot", "--backend", "fake", "--input-shape", "4,1,5,128,128", "--segment", SEG,
                        "--x", "150", "--y", "110", "--w", "150", "--h", "90", "--out", out]
                self.assertEqual(quiet(ip.main, args), 0)
                with open(out, "rb") as fh:
                    self.assertEqual(fh.read(), ip.png_gray(previewer(vol).preview(SEG, 150, 110, 150, 90)))
                os.remove(out)
                self.assertEqual(quiet(ip.main, args + ["--allow", "PHerc0841"]), 3)
                self.assertFalse(os.path.exists(out))
                with self.assertRaisesRegex(SystemExit, "snapshot: window has 3 slices, model needs 5"):
                    quiet(ip.main, args + ["--window", "0,3"])
                self.assertFalse(os.path.exists(out))
        finally:
            ip.Surface = real

    def test_backend_options(self):
        ap = ip.build_parser()
        a = ap.parse_args(["serve", "--backend", "fake"])
        self.assertEqual((a.allow, a.input_shape, a.device, a.port, a.max_view_px), ("any", (16, 1, 17, 128, 128), "auto", 8765, 16777216))
        self.assertEqual(ip.model_label(a), "fake")
        a = ap.parse_args(["serve", "--package", "/models/ink9um_b16.mlpackage/"])
        self.assertEqual(ip.model_label(a), "ink9um_b16")
        a = ap.parse_args(["serve", "--backend", "torchscript", "--model", "/models/ink_9um.pt"])
        self.assertEqual(ip.model_label(a), "ink_9um")
        self.assertEqual(ip.model_label(ap.parse_args(["serve", "--model-name", "mine"])), "mine")
        for bad in (["--input-shape", "16,17,128,128"], ["--input-shape", "16,1,17,128,64"], ["--overlap", "1"],
                    ["--backend", "other"]):
            with self.assertRaises(SystemExit):
                quiet(ap.parse_args, ["serve"] + bad)
        with self.assertRaisesRegex(SystemExit, "--package"):
            ip.build_backend(ap.parse_args(["serve"]))
        with self.assertRaisesRegex(SystemExit, "--model"):
            ip.build_backend(ap.parse_args(["serve", "--backend", "torchscript"]))

    def test_models_with_a_smaller_output_are_resized(self):
        fb = ip.FakeBackend(batch=4, depth=DEPTH, patch=PATCH, out_stride=4)
        self.assertEqual(fb.oshape, (4, 1, 32, 32))
        pv = ip.Previewer(fb)
        vol = volume((7, 200, 300))
        pv.surface = lambda seg: FakeSurface(vol)
        got = pv.preview(SEG, 0, 0, 300, 200)
        want = ref_full_map(vol, DEPTH, PATCH, STRIDE)  # the full-resolution map: got is a blurred copy of it

        def pooled(a):
            return a.reshape(50, 4, 75, 4).mean(axis=(1, 3)).ravel()
        self.assertEqual(got.shape, want.shape)
        self.assertGreater(float(np.corrcoef(pooled(got), pooled(want))[0, 1]), 0.99)


# ---------------------------------------------------------------- the window rule

def enum_exact(a, e, L, P, S):
    """The pixels of the window [a, e) whose covering patches are the whole axis's, by enumeration: every patch
    position of the whole axis and of the window (villa's rule on each) that covers the pixel."""
    whole = ref_positions(L, P, S)
    own = [a + q for q in ref_positions(e - a, P, S)]
    return [p for p in range(a, e)
            if {q for q in whole if q <= p < q + P} == {q for q in own if q <= p < q + P}]


def valid_windows(L, P, S):
    """Every window a window backend can run: on the grid (a a multiple of the stride, e one too or the axis end) and
    at least one patch long; the whole axis when it is no longer than the patch."""
    if L <= P:
        return [(0, L)]
    ends = sorted(set(range(S, L, S)) | {L})
    return [(a, e) for a in range(0, L, S) for e in ends if e - a >= P]


RULE_CASES = [(8, 4), (12, 4), (6, 4), (9, 4), (6, 3), (8, 8), (4, 2)]  # (patch, stride): 2s, 3s, off multiples, s = p


class WindowRule(unittest.TestCase):
    def test_exact_span_is_the_enumerated_rule(self):
        n = 0
        for P, S in RULE_CASES:
            for L in range(1, 30):
                for a, e in valid_windows(L, P, S):
                    want = enum_exact(a, e, L, P, S)
                    lo, hi = ip.exact_span(a, e, L, P, S)
                    msg = "L=%d P=%d S=%d window=(%d, %d)" % (L, P, S, a, e)
                    self.assertEqual(list(range(lo, hi)), want, msg)  # also: the exact pixels are one run
                    n += 1
        self.assertGreater(n, 2000)

    def test_off_grid_or_short_windows_keep_nothing(self):
        self.assertEqual(ip.exact_span(32, 288, 1000, 128, 64), (32, 32))   # off the grid
        self.assertEqual(ip.exact_span(64, 160, 1000, 128, 64), (64, 64))   # under one patch
        self.assertEqual(ip.exact_span(0, 90, 100, 128, 64), (0, 0))        # not the whole of a short axis
        self.assertEqual(ip.exact_span(0, 100, 100, 128, 64), (0, 100))

    def test_window_span_is_the_smallest_window_that_keeps_the_cells(self):
        n = 0
        for P, S in RULE_CASES:
            for L in range(1, 30):
                runs = valid_windows(L, P, S)
                cells = -(-L // S)
                for c0 in range(cells):
                    for c1 in range(c0 + 1, cells + 1):
                        lo, hi = c0 * S, min(c1 * S, L)
                        a, e = ip.window_span(lo, hi, L, P, S)
                        msg = "L=%d P=%d S=%d cells [%d, %d)" % (L, P, S, c0, c1)
                        self.assertIn((a, e), runs, msg)
                        ok = [w for w in runs if set(range(lo, hi)) <= set(enum_exact(w[0], w[1], L, P, S))]
                        self.assertIn((a, e), ok, msg)
                        # the smallest: every window that keeps the cells starts no later and ends no earlier
                        self.assertEqual((max(w[0] for w in ok), min(w[1] for w in ok)), (a, e), msg)
                        n += 1
        self.assertGreater(n, 1000)

    def test_worked_examples(self):
        # patch 128, stride 64: a margin of one stride on each side that is not the canvas edge
        self.assertEqual(ip.window_span(256, 512, 1000, 128, 64), (192, 576))
        self.assertEqual(ip.exact_span(192, 576, 1000, 128, 64), (256, 512))
        self.assertEqual(ip.window_span(0, 64, 1000, 128, 64), (0, 128))         # the canvas start: no margin
        self.assertEqual(ip.window_span(64, 192, 300, 128, 64), (0, 300))        # 192 > 300 - 128: to the end
        self.assertEqual(ip.window_span(256, 300, 300, 128, 64), (128, 300))     # a last partial cell, one patch
        self.assertEqual(ip.exact_span(128, 300, 300, 128, 64), (192, 300))
        self.assertEqual(ip.window_span(0, 100, 100, 128, 64), (0, 100))         # a canvas under one patch
        self.assertEqual(ip.window_span(0, 128, 128, 128, 64), (0, 128))         # a canvas of one patch
        # patch 384, stride 192 (Reader V3)
        self.assertEqual(ip.window_span(384, 576, 1100, 384, 192), (192, 768))
        self.assertEqual(ip.exact_span(192, 768, 1100, 384, 192), (384, 576))
        # patch 128, stride 96 (overlap 0.25): the high side needs a whole patch, rounded up to the grid
        self.assertEqual(ip.window_span(192, 288, 1000, 128, 96), (96, 480))
        self.assertEqual(ip.exact_span(96, 480, 1000, 128, 96), (128, 352))

    def test_cells_inside(self):
        self.assertEqual(ip.cells_inside(64, 320, 1000, 64), [1, 2, 3, 4])
        self.assertEqual(ip.cells_inside(65, 320, 1000, 64), [2, 3, 4])
        self.assertEqual(ip.cells_inside(192, 300, 300, 64), [3, 4])              # the last cell ends at 300
        self.assertEqual(ip.cells_inside(192, 299, 300, 64), [3])
        self.assertEqual(ip.cells_inside(0, 0, 300, 64), [])


# ---------------------------------------------------------------- the inkrs backend, on the stand-in module

class Inkrs(unittest.TestCase):
    def setUp(self):
        self.mod = fake_inkrs()
        p = mock.patch.dict(sys.modules, {"inkrs": self.mod})
        p.start()
        self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.export = write_export(self.tmp)

    def pv(self, export=None, **kw):
        return ip.Previewer(ip.InkrsBackend(export or self.export), **kw)

    def calls(self):
        return [c for e in self.mod.engines for c in e.calls]

    def ask(self, pv, vol, view, key="k", variant="f", fmt="u8"):
        """What a viewer does: ask; on a 409 upload need and ask again. (view, tiles, need or None)."""
        _, ch, cw = vol.shape
        try:
            got, tiles, _ = pv.stack_request(stack_query(key, cw, ch, *view, variant=variant, format=fmt))
            return got, tiles, None
        except ip.NeedStack as e:
            need = e.need
            self.assertEqual(e.depth, vol.shape[0])
        up = rect_of(need)
        got, tiles, _ = pv.stack_request(stack_query(key, cw, ch, *view, up=up, variant=variant, format=fmt),
                                         cut(vol, vol.shape[0], up))
        return got, tiles, need

    def check_views(self, vol, views, patch=128, stride=64, variant="f"):
        """Each view, cold and on one shared server, equals the stand-in's whole map of the canvas exactly."""
        D, H, W = vol.shape
        layers = vol[::-1] if variant == "r" else vol
        whole = villa_map(layers, patch, stride)[0]
        shared = self.pv()
        for x, y, w, h in views:
            for pv in (self.pv(), shared):
                got, _, need = self.ask(pv, vol, (x, y, w, h), variant=variant)
                msg = "canvas %dx%d view %s" % (W, H, (x, y, w, h))
                self.assertEqual(got.dtype, np.uint8, msg)
                np.testing.assert_array_equal(got, whole[y:y + h, x:x + w], err_msg=msg)
                if need is not None:  # the window is on the grid, at least one patch long, inside the canvas
                    for start, size, L in ((need["x"], need["w"], W), (need["y"], need["h"], H)):
                        self.assertEqual(start % stride, 0, msg)
                        self.assertTrue((start + size) % stride == 0 or start + size == L, msg)
                        self.assertTrue(size >= patch or (start, size) == (0, L), msg)
                        self.assertLessEqual(start + size, L, msg)
        return whole

    def test_health_and_the_backend(self):
        pv = self.pv(model_name="fake-reader")
        h = pv.health()
        for k, v in (("backend", "inkrs"), ("model", "fake-reader"), ("patch", 128), ("stride", 64), ("depth", 17),
                     ("tiling", "window"), ("quantized", True), ("dtypes", ["uint8"]), ("output_shape", None),
                     ("input_shape", [16, 1, 17, 128, 128])):
            self.assertEqual(h[k], v, k)
        self.assertEqual(h["engine"], {"version": "0.0.0+fake", "reader": "fake-reader", "gpu": "fake",
                                       "batch_size": 16, "weights": "fake-reader.safetensors"})
        h = previewer().health()  # a batch backend says what it is too
        self.assertEqual((h["tiling"], h["quantized"], h["dtypes"]), ("patch", False, ["uint8", "uint16"]))

    def test_views_equal_the_whole_map_on_and_off_the_stride(self):
        # 700 - 128 and 500 - 128 are not multiples of 64 (flush last patches); 640 - 128 and 448 - 128 are
        for W, H in ((700, 500), (640, 448)):
            vol = volume((17, H, W), seed=W)
            views = [(130, 90, 200, 150),                                     # inside, off the grid
                     (200, 0, 150, 60), (200, H - 60, 150, 60),               # top and bottom edges
                     (0, 200, 70, 100), (W - 60, 200, 60, 100),               # left and right edges
                     (0, 0, 90, 70), (W - 90, 0, 90, 70),                     # the four corners
                     (0, H - 70, 90, 70), (W - 90, H - 70, 90, 70),
                     (0, 0, W, H), (1, 1, 1, 1), (W - 1, H - 1, 1, 1)]        # the whole canvas, single pixels
            self.check_views(vol, views)

    def test_a_pan_computes_only_the_new_cells(self):
        vol = volume((17, 900, 1200), seed=3)
        whole = villa_map(vol, 128, 64)[0]
        pv = self.pv()
        steps = [  # view, need, cells (computed, cached), patches the run tiled
            ((130, 100, 300, 200), {"x": 64, "y": 0, "w": 448, "h": 384}, (20, 0), 30),   # cold
            ((230, 100, 300, 200), {"x": 384, "y": 0, "w": 256, "h": 384}, (8, 16), 15),  # 100 px right
            ((130, 100, 300, 200), None, (0, 20), 0),                                     # back: all cached
            ((130, 300, 300, 200), {"x": 64, "y": 256, "w": 448, "h": 320}, (15, 5), 24), # 200 px down
        ]
        for view, need, tiles, patches in steps:
            before = len(self.calls())
            got, t, n = self.ask(pv, vol, view)
            x, y, w, h = view
            np.testing.assert_array_equal(got, whole[y:y + h, x:x + w], err_msg=str(view))
            self.assertEqual((n, t), (need, tiles), str(view))
            runs = self.calls()[before:]
            self.assertEqual(len(runs), 0 if need is None else 1, str(view))  # one engine run per upload
            if runs:
                self.assertEqual(runs[0]["shape"], (17, need["h"], need["w"]))
                self.assertEqual((runs[0]["patches"], runs[0]["stride"], runs[0]["window"]), (patches, 64, (0, 1)))
        # every exact cell of every window is kept: rows 0 to 4 by columns 2 to 6, then by columns 7 and 8
        # (row 0 too, outside the view), then rows 5 to 7 by columns 2 to 6
        self.assertEqual(pv.stats()["tiles"], 25 + 10 + 15)

    def test_reverse_variant_is_villas_reverse_direction(self):
        vol = volume((17, 500, 700), seed=5)
        whole_r = self.check_views(vol, [(130, 90, 200, 150), (610, 430, 90, 70), (0, 0, 90, 70)], variant="r")
        eng = ip.InkrsBackend(self.export).eng
        # inkrs window (D - 1, -1) on the uploaded forward layers, and (0, 1) on the reversed array: the same map
        a = eng.run(vol, [(16, -1)], stride=64)[0]
        b = eng.run(np.ascontiguousarray(vol[::-1]), [(0, 1)], stride=64)[0]
        np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(a, whole_r)
        pv = self.pv()
        f, _, _ = self.ask(pv, vol, (130, 90, 200, 150))
        r, _, need = self.ask(pv, vol, (130, 90, 200, 150), variant="r")
        self.assertIsNotNone(need)  # the reversed view has cells of its own
        self.assertGreater(int((f != r).sum()), 1000)
        self.assertEqual(self.calls()[-1]["window"], (16, -1))

    def test_patch_384_stride_192(self):
        export = write_export(self.tmp, "reader-v3-fake", crop=(17, 384, 384))
        vol = volume((17, 900, 1100), seed=7)  # 1100 - 384 and 900 - 384 are not multiples of 192
        whole = villa_map(vol, 384, 192)[0]
        pv = ip.Previewer(ip.InkrsBackend(export))
        self.assertEqual((pv.P, pv.stride, pv.health()["input_shape"]), (384, 192, [8, 1, 17, 384, 384]))
        self.assertEqual(self.mod.engines[-1].batch_size, 8)  # the default for 384 px tiles
        for view in ((400, 300, 300, 200), (0, 0, 250, 200), (1100 - 250, 900 - 200, 250, 200), (900, 0, 200, 100),
                     (0, 0, 1100, 900)):
            for p in (pv, ip.Previewer(ip.InkrsBackend(export))):
                got, _, _ = self.ask(p, vol, view)
                x, y, w, h = view
                np.testing.assert_array_equal(got, whole[y:y + h, x:x + w], err_msg=str(view))
        got, tiles, need = self.ask(ip.Previewer(ip.InkrsBackend(export)), vol, (400, 300, 300, 200))
        # rows 192..576 reach past 900 - 384 = 516, so the window runs to the canvas end; columns 384..768 too
        self.assertEqual((need, tiles), ({"x": 192, "y": 0, "w": 908, "h": 900}, (4, 0)))

    def test_canvases_no_larger_than_one_patch(self):
        # inkrs refuses a side under the patch; the server zero fills that axis to one patch, as villa fills the one
        # patch there, and keeps the canvas part
        for W, H, view in ((100, 90, (10, 20, 50, 60)), (128, 300, (5, 100, 100, 150)), (700, 100, (300, 10, 200, 80)),
                           (128, 128, (0, 0, 128, 128)), (64, 64, (0, 0, 64, 64))):
            vol = volume((17, H, W), seed=W + H)
            whole = villa_map(vol, 128, 64)[0]  # villa's rule, zero filled past the edge
            got, _, need = self.ask(self.pv(), vol, view)
            x, y, w, h = view
            np.testing.assert_array_equal(got, whole[y:y + h, x:x + w], err_msg=str((W, H)))
            if W <= 128:
                self.assertEqual((need["x"], need["w"]), (0, W))
            if H <= 128:
                self.assertEqual((need["y"], need["h"]), (0, H))
            self.assertTrue(all(min(c["shape"][1:]) >= 128 for c in self.calls()))

    def test_controls_differ_so_the_check_can_fail(self):
        vol = volume((17, 900, 1200), seed=11)
        whole = villa_map(vol, 128, 64)[0]
        pv = self.pv()
        x, y, w, h = 130, 100, 300, 200
        want = whole[y:y + h, x:x + w]
        # the window without the margin: the view's cells alone, rows 64..320, columns 128..448
        m = pv.b.window(vol[:, 64:320, 128:448], False, 64)
        self.assertGreater(int((m[y - 64:y - 64 + h, x - 128:x - 128 + w] != want).sum()), 0)
        # the right window (rows 0..384, columns 64..512) shifted half a stride off the grid
        m = pv.b.window(vol[:, 32:416, 96:544], False, 64)
        self.assertGreater(int((m[y - 32:y - 32 + h, x - 96:x - 96 + w] != want).sum()), 0)
        # and through the server: a rule without the margin that calls every pixel exact serves other pixels
        bare = lambda lo, hi, L, P, S: (lo // S * S, min(max(-(-hi // S) * S, lo // S * S + P), L))
        with mock.patch.object(ip, "window_span", bare), mock.patch.object(ip, "exact_span", lambda a, e, *r: (a, e)):
            got, _, _ = self.ask(self.pv(), vol, (x, y, w, h))
        self.assertGreater(int((got != want).sum()), 0)
        got, _, _ = self.ask(self.pv(), vol, (x, y, w, h))  # the real rule
        np.testing.assert_array_equal(got, want)

    def test_formats(self):
        vol = volume((17, 200, 300), seed=13)
        pv = self.pv()
        u8, tiles, _ = self.ask(pv, vol, (100, 50, 120, 100))
        f32, tiles2, _ = self.ask(pv, vol, (100, 50, 120, 100), fmt="f32")
        self.assertEqual((tiles, tiles2), ((9, 0), (0, 9)))  # cells: rows 0 to 2 by columns 1 to 3
        body, _ = ip.encode(f32, "f32")
        np.testing.assert_array_equal(np.frombuffer(body, "<f4").reshape(100, 120),
                                      u8.astype(np.float32) / np.float32(255))   # f32 is u8 / 255
        self.assertEqual(ip.encode(u8, "u8")[0], u8.tobytes())                    # u8 as inkrs gave it
        png = ip.encode(u8, "png")[0]
        self.assertTrue(png.startswith(b"\x89PNG"))
        raw = zlib_rows(png, 100, 120)
        np.testing.assert_array_equal(raw, u8)                                    # png holds the u8 pixels
        np.testing.assert_array_equal(ip.to_u8(u8), u8)

    def test_uint16_is_a_400_and_the_dtype_is_checked_first(self):
        vol = volume((17, 200, 300), np.uint16)
        q = stack_query("k", 300, 200, 100, 50, 120, 100, up=(0, 0, 300, 200), dtype="uint16")
        with self.assertRaisesRegex(ValueError, "inkrs backend reads uint8 layers only; send dtype=uint8"):
            self.pv().stack_request(q, cut(vol, 17, (0, 0, 300, 200)))
        pv = self.pv()
        pv.surface = lambda seg: FakeSurface(vol)
        with self.assertRaisesRegex(ValueError, "uint8"):
            pv.preview(SEG, 0, 0, 200, 150)
        self.assertEqual(self.calls(), [])

    def test_engine_errors_are_500_and_the_server_stays_up(self):
        from http.server import ThreadingHTTPServer
        vol = volume((17, 200, 300), seed=17)
        pv = self.pv()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), ip.make_handler(pv))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close); self.addCleanup(srv.shutdown)
        base = "http://127.0.0.1:%d" % srv.server_address[1]

        def post(view, up=None, **more):
            url = base + "/preview?" + urllib.parse.urlencode(stack_query("k", 300, 200, *view, up=up, **more))
            body = cut(vol, 17, up) if up else b""
            try:
                r = urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST"))
                return r.status, r.headers, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.headers, e.read()
        code, _, body = post((100, 50, 120, 100))
        self.assertEqual((code, json.loads(body)), (409, {"need": {"x": 0, "y": 0, "w": 300, "h": 200}, "depth": 17,
                                                          "missing": 9}))
        for err, text in ((self.mod.InkrsError("out of GPU memory"),
                           "inkrs failed on this window (InkrsError): out of GPU memory"),
                          (self.mod.UnsupportedError("no kernels for this GPU"),
                           "inkrs does not support this window (UnsupportedError): no kernels for this GPU")):
            self.mod.fail = err
            code, _, body = post((100, 50, 120, 100), up=(0, 0, 300, 200))
            self.assertEqual((code, json.loads(body)), (500, {"error": text}))
        self.mod.fail = None
        self.assertEqual(json.load(urllib.request.urlopen(base + "/health"))["backend"], "inkrs")
        code, headers, body = post((100, 50, 120, 100), up=(0, 0, 300, 200))
        self.assertEqual((code, headers["X-Backend"], headers["X-Tiles"], headers["X-Shape"]),
                         (200, "inkrs", "9,0", "100,120"))
        np.testing.assert_array_equal(np.frombuffer(body, np.uint8).reshape(100, 120),
                                      villa_map(vol, 128, 64)[0][50:150, 100:220])
        code, headers, body = post((100, 50, 120, 100), format="png")
        self.assertEqual((code, headers["Content-Type"], headers["X-Tiles"]), (200, "image/png", "0,9"))
        code, _, body = post((10, 10, 20, 20), up=(0, 0, 300, 200), dtype="uint16")
        self.assertEqual(code, 400)  # a uint8 body sent as uint16: half the bytes it would need
        self.assertEqual(stats_of(base)["tiles"], 20)  # the window was the whole canvas: all 4 x 5 cells are exact

    def test_path_mode(self):
        vol = volume((19, 300, 400), seed=19)  # 19 layers: the center crop 1..17 is what the model reads
        pv = self.pv()
        pv.surface = lambda seg: FakeSurface(vol)
        for variant, layers in (("f", vol[1:18]), ("r", vol[1:18][::-1])):
            whole = villa_map(layers, 128, 64)[0]
            got = pv.preview(SEG, 150, 110, 150, 90, variant=variant)
            np.testing.assert_array_equal(got, whole[110:200, 150:300], err_msg=variant)
        prob, counts = pv.preview_path(SEG, 150, 110, 150, 90)
        self.assertEqual(counts, (0, 9))  # cached: rows 1 to 3 by columns 2 to 4
        pooled = pv.preview(SEG, 150, 110, 150, 90, scale=2)
        self.assertEqual((pooled.dtype, pooled.shape), (np.float32, (45, 75)))
        np.testing.assert_allclose(pooled, (prob.astype(np.float32) / 255).reshape(45, 2, 75, 2).mean(axis=(1, 3)),
                                   atol=1e-6)

    def test_command_line_and_start_refusals(self):
        ap = ip.build_parser()
        a = ap.parse_args(["serve", "--backend", "inkrs", "--model", self.export, "--batch-size", "8",
                           "--device", "mps"])
        b = ip.build_backend(a)
        self.assertEqual((b.eng.batch_size, b.eng.device, b.depth, b.patch, ip.model_label(a, b)),
                         (8, "mps", 17, 128, "fake-reader"))
        b = ip.build_backend(ap.parse_args(["serve", "--backend", "inkrs", "--model", self.export]))
        self.assertEqual((b.eng.device, b.eng.batch_size), (0, 16))  # the default for 128 px tiles
        pth = os.path.join(self.tmp, "step-075000.pth")
        open(pth, "wb").close()
        self.assertEqual(ip.default_batch(pth), 8)  # no sidecar to read: the batch that fits either tile size
        self.assertEqual(ip.default_batch(write_export(self.tmp, "v3", crop=(17, 384, 384))), 8)
        self.assertEqual(ip.model_label(ap.parse_args(["serve", "--backend", "inkrs", "--model", self.export,
                                                       "--model-name", "ink_9um"]), b), "ink_9um")
        with self.assertRaisesRegex(SystemExit, "--model"):
            ip.build_backend(ap.parse_args(["serve", "--backend", "inkrs"]))
        for bad in (["--batch-size", "0"], ["--batch-size", "x"]):
            with self.assertRaises(SystemExit):
                quiet(ap.parse_args, ["serve", "--backend", "inkrs", "--model", self.export] + bad)
        refusals = [
            (dict(device="cpu"), "runs on a GPU"),
            (dict(model=write_export(self.tmp, "bare", sidecar=False)), "cannot tell how many layers"),
            (dict(model=write_export(self.tmp, "odd", crop=(17, 128, 64))), "is not \\[depth, 64, 64\\]"),
            (dict(model=write_export(self.tmp, "v8", crop=(24, 128, 128), architecture_family="v8in")),
             "v8in export"),
        ]
        for kw, text in refusals:
            with self.assertRaisesRegex(SystemExit, text, msg=str(kw)):
                ip.InkrsBackend(kw.get("model", self.export), kw.get("device", "auto"))
        self.mod.load_error = self.mod.UnsupportedError("no kernels for this GPU")
        with self.assertRaisesRegex(SystemExit, "cannot run .* here \\(UnsupportedError\\): no kernels"):
            ip.InkrsBackend(self.export)
        self.mod.load_error = self.mod.InkrsError("corrupt export")
        with self.assertRaisesRegex(SystemExit, "could not load .*: corrupt export"):
            ip.InkrsBackend(self.export)
        self.mod.load_error = None
        with mock.patch.dict(sys.modules, {"inkrs": None}):  # not installed
            with self.assertRaisesRegex(SystemExit, "pip install inkrs"):
                ip.InkrsBackend(self.export)

    def test_snapshot_through_the_command_line(self):
        vol = volume((17, 200, 300), seed=23)
        real = ip.Surface
        ip.Surface = lambda path: FakeSurface(vol)
        try:
            out = os.path.join(self.tmp, "view.png")
            args = ["snapshot", "--backend", "inkrs", "--model", self.export, "--segment", SEG,
                    "--x", "150", "--y", "110", "--w", "150", "--h", "90", "--out", out]
            self.assertEqual(quiet(ip.main, args), 0)
            with open(out, "rb") as fh:
                self.assertEqual(fh.read(), ip.png_gray(villa_map(vol, 128, 64)[0][110:200, 150:300]))
        finally:
            ip.Surface = real

    def test_the_mac_check_script_passes_and_can_fail(self):
        chk = load_check()
        vol = volume((21, 700, 900), seed=29)  # the center 17 layers are 2..18
        path = os.path.join(self.tmp, "seg.npy")
        np.save(path, vol)
        rep_path = os.path.join(self.tmp, "check.json")
        args = ["--model", self.export, "--segment", path, "--view", "300,200", "--json", rep_path]
        self.assertEqual(quiet(chk.main, args), 0)
        with open(rep_path) as fh:
            rep = json.load(fh)
        self.assertEqual((rep["pass"], rep["layers"], rep["canvas"], len(rep["views"])), (True, [2, 18], [700, 900], 16))
        self.assertTrue(all(v["differ"] == 0 for v in rep["views"]))
        self.assertTrue(all(c["differ"] > 0 for c in rep["controls"]))
        np.testing.assert_array_equal(  # its whole map is the stand-in's map of the same layers
            chk.ip.InkrsBackend(self.export).window(vol[2:19], False, 64), villa_map(vol[2:19], 128, 64)[0])
        with mock.patch.object(chk.ip, "window_span", lambda lo, hi, L, P, S: (lo // S * S, min(L, max(
                -(-hi // S) * S, lo // S * S + P)))), mock.patch.object(chk.ip, "exact_span", lambda a, e, *r: (a, e)):
            self.assertEqual(quiet(chk.main, args), 1)  # a rule without the margin fails the check
        with open(rep_path) as fh:
            self.assertFalse(json.load(fh)["equal"])
        self.assertEqual(quiet(chk.main, args + ["--allow", "PHerc0139"]), 3)  # the path names no allowed scroll


def stats_of(base):
    return json.load(urllib.request.urlopen(base + "/health"))["cache"]


def zlib_rows(png, h, w):
    """The 8-bit gray pixels of a PNG from png_gray (one IDAT stream, filter 0 on every row)."""
    import struct, zlib
    i, data = 8, b""
    while i < len(png):
        n = struct.unpack(">I", png[i:i + 4])[0]
        if png[i + 4:i + 8] == b"IDAT":
            data += png[i + 8:i + 8 + n]
        i += 12 + n
    return np.frombuffer(zlib.decompress(data), np.uint8).reshape(h, w + 1)[:, 1:]


def load_check():
    spec = importlib.util.spec_from_file_location(
        "inkpreview_inkrs_check", os.path.join(HERE, "..", "scripts", "ane", "inkpreview_inkrs_check.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


@unittest.skipIf(torch is None, "torch is needed for the torchscript backend")
class TorchScript(unittest.TestCase):
    def setUp(self):
        import warnings
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", FutureWarning)  # newer torch versions call torch.jit deprecated

    def test_traced_module_through_the_backend_and_a_preview(self):
        class Tiny(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.w = torch.nn.Parameter(torch.linspace(0.2, 1.0, 5).view(1, 1, 5, 1, 1))

            def forward(self, x):
                return (x * self.w).sum(dim=2) * 0.5

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tiny.pt")
            torch.jit.trace(Tiny().eval(), torch.zeros(3, 1, 5, 32, 32)).save(path)
            b = ip.TorchScriptBackend(path, device="cpu", input_shape=(3, 1, 5, 32, 32))
        self.assertEqual((b.name, b.ishape, b.oshape), ("torchscript", (3, 1, 5, 32, 32), (3, 1, 32, 32)))
        w = np.linspace(0.2, 1.0, 5, dtype=np.float32)

        def model(x):  # the same function in numpy
            return np.tensordot(w, x, axes=([0], [0])) * 0.5
        rng = np.random.default_rng(5)
        for n in (1, 3, 4, 7):  # short last batches are padded and cut back
            x = rng.normal(size=(n, 1, 5, 32, 32)).astype(np.float32)
            y = b(x)
            self.assertEqual(y.shape, (n, 1, 32, 32))
            np.testing.assert_allclose(y[:, 0], np.stack([model(p[0]) for p in x]), atol=1e-5)
        vol = volume((5, 70, 90))
        pv = ip.Previewer(b, model_name="tiny")
        self.assertEqual((pv.P, pv.stride, pv.D, pv.health()["backend"]), (32, 16, 5, "torchscript"))
        q = stack_query("k", 90, 70, 11, 7, 60, 50, up=(0, 0, 90, 70), format="f32")
        got, tiles, _ = pv.stack_request(q, vol.tobytes())
        self.assertEqual(tiles, (20, 0))
        np.testing.assert_allclose(got, ref_full_map(vol, 5, 32, 16, model=model)[7:57, 11:71], atol=1e-5)

    def test_upsample_is_torch_bilinear_with_half_pixel_centers(self):
        y = np.random.default_rng(6).normal(size=(3, 32, 32)).astype(np.float32)
        for size in (128, 48, 32):
            want = torch.nn.functional.interpolate(torch.from_numpy(y)[None], size=(size, size), mode="bilinear",
                                                   align_corners=False)[0].numpy()
            np.testing.assert_allclose(ip.upsample(y, size), want, atol=1e-5)

    def test_cli_builds_the_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ink_9um.pt")
            torch.jit.trace(torch.nn.Conv3d(1, 1, (5, 1, 1)).eval(), torch.zeros(2, 1, 5, 32, 32)).save(path)
            a = ip.build_parser().parse_args(["serve", "--backend", "torchscript", "--model", path, "--device", "cpu",
                                              "--input-shape", "2,1,5,32,32"])
            b = ip.build_backend(a)
        self.assertEqual((b.ishape, b.oshape, ip.model_label(a)), ((2, 1, 5, 32, 32), (2, 1, 1, 32, 32), "ink_9um"))


if __name__ == "__main__":
    unittest.main()
