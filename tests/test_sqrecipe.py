"""Tests for kit/sqfid.py, kit/sqrecipe.py and scripts/sqrecipe/sqrecipe.py (paired acquisition-recipe fidelity).
Synthetic data only; nothing is read from the network."""

import importlib.util
import json
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import scipy.ndimage as nd
    HAVE = True
except ImportError:          # pragma: no cover
    HAVE = False

if HAVE:
    from kit import sqfid
    from kit import sqrecipe as rc


def _zarr_files(arr, chunk=16, prefix="https://x/a/0", compressor=None):
    meta = {"shape": list(arr.shape), "chunks": [chunk] * 3, "dtype": "|u1", "fill_value": 0, "order": "C",
            "filters": None, "dimension_separator": "/", "compressor": compressor, "zarr_format": 2}
    files = {f"{prefix}/.zarray": json.dumps(meta).encode()}
    n = [(s + chunk - 1) // chunk for s in arr.shape]
    for cz in range(n[0]):
        for cy in range(n[1]):
            for cx in range(n[2]):
                c = np.zeros((chunk,) * 3, np.uint8)
                part = arr[cz * chunk:(cz + 1) * chunk, cy * chunk:(cy + 1) * chunk, cx * chunk:(cx + 1) * chunk]
                c[:part.shape[0], :part.shape[1], :part.shape[2]] = part
                raw = c.tobytes()
                files[f"{prefix}/{cz}/{cy}/{cx}"] = zlib.compress(raw) if compressor else raw
    return files


def _fake_store(arr, chunk=16, compressor=None):
    files = _zarr_files(arr, chunk, compressor=compressor)
    return rc.Store("https://x/a", opener=lambda u: files.get(u))


def _load_script():
    spec = importlib.util.spec_from_file_location("sqrecipe_script", ROOT / "scripts/sqrecipe/sqrecipe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _field(seed=0, n=140, period=8.0, noise=0.0):
    rng = np.random.default_rng(seed)
    z = np.arange(n)[:, None, None]
    sheets = 100 + 40 * np.sin(2 * np.pi * z / period + 0.3 * np.sin(np.arange(n)[None, :, None] / 17.0))
    sheets = np.broadcast_to(sheets, (n, n, n)).astype(np.float32)
    return sheets + noise * rng.normal(size=(n, n, n)).astype(np.float32)


class Arr:
    """An in-memory array with block(lo, size), zero outside."""

    def __init__(self, a):
        self.a = a

    def block(self, lo, size):
        lo = np.asarray(lo)
        s = np.asarray(size if hasattr(size, "__len__") else (size,) * 3)
        out = np.zeros(tuple(s), self.a.dtype)
        a0 = np.maximum(lo, 0)
        b0 = np.minimum(lo + s, self.a.shape)
        out[a0[0] - lo[0]:b0[0] - lo[0], a0[1] - lo[1]:b0[1] - lo[1], a0[2] - lo[2]:b0[2] - lo[2]] = \
            self.a[a0[0]:b0[0], a0[1]:b0[1], a0[2]:b0[2]]
        return out, 0


# ---------------------------------------------------------------- kit.sqfid

@unittest.skipUnless(HAVE, "numpy and scipy needed")
class TestFidelity(unittest.TestCase):
    def test_fast_equals_direct(self):
        rng = np.random.default_rng(1)
        x = nd.gaussian_filter(rng.normal(size=(60, 60, 60)).astype(np.float32), 2)
        c = x[3:51, 5:53, 4:52] + 0.3 * x.std() * rng.normal(size=(48,) * 3).astype(np.float32)
        f = x[6:54, 3:51, 4:52].copy()
        rule = dict(sqfid.RULE, max_shift=4, inner=6)
        v1, s1 = sqfid.best_ncc_fast(c, f, rule)
        v2, s2 = sqfid.best_ncc(c, f, rule)
        self.assertEqual(s1, s2)
        self.assertEqual(s1, [-3, 2, 0])
        self.assertAlmostEqual(v1, v2, places=4)

    def test_shift_beyond_search_is_flagged_and_lower(self):
        rng = np.random.default_rng(2)
        x = nd.gaussian_filter(rng.normal(size=(150, 140, 140)).astype(np.float32), 2) * 50 + 100
        c = np.clip(x[5:133, 5:133, 5:133], 1, 255)
        near = np.clip(x[7:135, 5:133, 5:133], 1, 255)
        far = np.clip(x[17:145, 5:133, 5:133], 1, 255)
        o_near, o_far = sqfid.outcome(c, near), sqfid.outcome(c, far)
        self.assertFalse(o_near["at_border"])
        self.assertGreater(o_near["fidelity"], 0.9)
        self.assertTrue(o_far["at_border"])
        self.assertLess(o_far["fidelity"], o_near["fidelity"] - 0.3)

    def test_noise_lowers_fidelity(self):
        clean = np.clip(_field(0)[:128, :128, :128], 1, 255)
        noisy = np.clip(_field(0, noise=60.0)[:128, :128, :128], 1, 255)
        self.assertGreater(sqfid.outcome(clean, clean)["fidelity"], sqfid.outcome(noisy, clean)["fidelity"])

    def test_max_shift_cannot_exceed_inner(self):
        rule = dict(sqfid.RULE, max_shift=9, inner=8)
        with self.assertRaises(sqfid.FidError):
            sqfid.best_ncc_fast(np.ones((32,) * 3), np.ones((32,) * 3), rule)

    def test_coarse_to_fine_inverts(self):
        A = [[0.25, 0.01, 0.0, 100.0], [0.0, 0.25, 0.002, 50.0], [0.0, 0.0, 0.25, 3000.0]]
        M = sqfid.coarse_to_fine(A, "fine_to_coarse")
        v = np.array([400.0, 800.0, 1200.0])
        r = np.array(A)[:, :3] @ v + np.array(A)[:, 3]
        self.assertTrue(np.allclose(M[:, :3] @ r + M[:, 3], v))
        self.assertTrue(np.allclose(sqfid.coarse_to_fine(A, "coarse_to_fine"), np.array(A)))
        with self.assertRaises(sqfid.FidError):
            sqfid.coarse_to_fine(A, "sideways")

    def test_fine_on_coarse_identity_and_mask(self):
        rng = np.random.default_rng(3)
        vol = rng.integers(1, 255, (40, 40, 40)).astype(np.uint8)
        vol[:, :, 30:] = 0
        out = sqfid.fine_on_coarse(Arr(vol), 0, np.eye(4)[:3], (4, 4, 4), 32)
        self.assertTrue(np.array_equal(out, vol[4:36, 4:36, 4:36]))
        self.assertTrue((out[:, :, 26:] == 0).all())

    def test_region_codes_and_clusters(self):
        for zyx in [(0, 0, 0), (19, 15, 6), (1023, 1, 1023)]:
            self.assertEqual(sqfid.region_index(sqfid.region_code(zyx)), zyx)
        with self.assertRaises(sqfid.FidError):
            sqfid.region_code((1024, 0, 0))
        self.assertEqual(sqfid.cluster_of(sqfid.region_code((9, 4, 3))), "2_1_0")

    def test_outcome_control_holds_and_fails(self):
        rng = np.random.default_rng(4)
        cl = [str(i // 3) for i in range(90)]
        true = 0.8 + 0.05 * rng.standard_normal(90)
        self.assertTrue(sqfid.outcome_control(true, 0.1 + 0.05 * rng.standard_normal(90), cl)["holds"])
        self.assertFalse(sqfid.outcome_control(true, true + 0.01, cl)["holds"])

    def test_derangement_has_no_fixed_point(self):
        p = sqfid.derangement(10, 3)
        self.assertEqual(sorted(p), list(range(10)))
        self.assertTrue(all(p[i] != i for i in range(10)))

    def test_spearman_and_interval(self):
        self.assertAlmostEqual(sqfid.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertTrue(np.isnan(sqfid.spearman([1, 2], [1, 2])))
        self.assertTrue(np.isnan(sqfid.spearman([1, 1, 1], [1, 2, 3])))
        lo, hi = sqfid.interval(np.arange(1001, dtype=float))
        self.assertAlmostEqual(lo, 25.0)
        self.assertAlmostEqual(hi, 975.0)


# ---------------------------------------------------------------- kit.sqrecipe

@unittest.skipUnless(HAVE, "numpy and scipy needed")
class TestReading(unittest.TestCase):
    def test_parallel_block_equals_zarray_block(self):
        rng = np.random.default_rng(0)
        arr = rng.integers(1, 255, (40, 37, 33)).astype(np.uint8)
        st = _fake_store(arr)
        a, b = rc.ZArray(st, "0"), rc.ParallelZArray(st, "0", threads=4, cache=8)
        for o, s in [((0, 0, 0), 20), ((5, 7, 3), (30, 25, 29)), ((-3, 30, 20), 16)]:
            x, mx = a.block(o, s)
            y, my = b.block(o, s)
            self.assertTrue(np.array_equal(x, y))
            self.assertEqual(mx, my)
            want = np.zeros(np.broadcast_to(s, 3), np.uint8)
            self.assertEqual(x.shape, want.shape)
        self.assertLessEqual(len(b._lru), 8)
        x, _ = a.block((5, 7, 3), (30, 25, 29))
        self.assertTrue(np.array_equal(x, arr[5:35, 7:32, 3:32]))

    def test_compressed_chunks_and_missing_chunks(self):
        rng = np.random.default_rng(1)
        arr = rng.integers(1, 255, (32, 32, 32)).astype(np.uint8)
        files = _zarr_files(arr, compressor={"id": "zlib", "level": 1})
        del files["https://x/a/0/1/1/1"]
        st = rc.Store("https://x/a", opener=lambda u: files.get(u))
        out, missing = rc.ZArray(st, "0").block((0, 0, 0), 32)
        self.assertEqual(missing, 1)
        self.assertTrue(np.array_equal(out[:16, :16, :16], arr[:16, :16, :16]))
        self.assertTrue((out[16:, 16:, 16:] == 0).all())
        self.assertEqual(st.missing, 1)

    def test_local_store_and_missing_array(self):
        rng = np.random.default_rng(2)
        arr = rng.integers(1, 255, (20, 20, 20)).astype(np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            for key, raw in _zarr_files(arr, prefix="0").items():
                p = Path(tmp) / key
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(raw)
            out, _ = rc.ZArray(rc.Store(tmp), "0").block((2, 3, 4), 10)
            self.assertTrue(np.array_equal(out, arr[2:12, 3:13, 4:14]))
            with self.assertRaisesRegex(rc.RecipeError, "no .zarray"):
                rc.ZArray(rc.Store(tmp), "1")


@unittest.skipUnless(HAVE, "numpy and scipy needed")
class TestGeometry(unittest.TestCase):
    def test_compose_and_invert(self):
        A = [[2.0, 0.1, 0, 5], [0, 2.1, 0, -3], [0.05, 0, 1.9, 7]]
        B = [[0.5, 0, 0, 1], [0, 0.5, 0, 2], [0, 0, 0.5, 3]]
        p = np.array([3.0, 4.0, 5.0, 1.0])
        AB = rc.compose(B, A)
        want = np.array(B) @ np.append(np.array(A) @ p, 1.0)
        self.assertTrue(np.allclose(AB @ p, want))
        self.assertTrue(np.allclose(rc.compose(rc.invert(A), A), np.eye(4)[:3]))

    def test_round_trip_identity_is_exact(self):
        rng = np.random.default_rng(1)
        vol = rng.integers(1, 255, (48, 48, 48)).astype(np.uint8)
        out = rc.round_trip(Arr(vol), np.eye(4)[:3], 0, (8, 8, 8), 24)
        self.assertTrue(np.array_equal(out, vol[8:32, 8:32, 8:32]))

    def test_round_trip_matches_lattice_range_and_smooths(self):
        rng = np.random.default_rng(2)
        vol = rng.integers(1, 255, (64, 64, 64)).astype(np.uint8)
        M = np.array([[2.4, 0, 0, 3.0], [0, 2.4, 0, 1.0], [0, 0, 2.4, 2.0]])
        out = rc.round_trip(Arr(vol), M, 1, (16, 16, 16), 24)
        self.assertEqual(out.shape, (24, 24, 24))
        self.assertTrue((out > 0).all())
        # interpolation through the lattice smooths white noise
        self.assertLess(out.astype(float).std(), vol[16:40, 16:40, 16:40].astype(float).std())
        lo, hi = rc.lattice_range(M, 1, (16, 16, 16), 24)
        held = rc._Held(np.ones(tuple(hi - lo), np.uint8) * 7, lo)
        self.assertTrue((sqfid.fine_on_coarse(held, 1, M, (16, 16, 16), 24) == 7).all())
        with self.assertRaises(rc.RecipeError):
            held.block(lo + 1, hi - lo)

    def test_corners_inside_and_touches(self):
        M = np.eye(4)[:3]
        self.assertTrue(rc.corners_inside(M, (2, 2, 2), 10, (20, 20, 20)))
        self.assertFalse(rc.corners_inside(M, (12, 2, 2), 10, (20, 20, 20)))
        self.assertTrue(rc.touches(M, (0, 0, 0), 10, {"z": [5, 8]}))
        self.assertFalse(rc.touches(M, (0, 0, 0), 10, {"z": [11, 20]}))
        self.assertFalse(rc.touches(M, (0, 0, 0), 10, {"z": [0, 20], "x": [30, 40]}))
        S2 = np.array([[2.0, 0, 0, 0], [0, 2.0, 0, 0], [0, 0, 2.0, 0]])
        self.assertTrue(rc.touches(S2, (0, 0, 0), 10, {"z": [15, 30]}))


@unittest.skipUnless(HAVE, "numpy and scipy needed")
class TestDegradation(unittest.TestCase):
    def test_hf_noise_scales_with_white_noise(self):
        rng = np.random.default_rng(3)
        x = 128 + 10 * rng.standard_normal((48, 48, 48))
        self.assertAlmostEqual(rc.hf_noise(np.clip(x, 1, 255)) / (10 * rc.white_c()), 1.0, delta=0.08)

    def test_degrade_matches_target_noise(self):
        z = np.arange(48)[:, None, None] * np.ones((48, 48, 48))
        smooth = (128 + 40 * np.sin(z / 4.0)).astype(np.uint8)
        out, add = rc.degrade_to(smooth, 12.0, seed=4)
        self.assertGreater(add, 0)
        self.assertAlmostEqual(rc.hf_noise(out), 12.0, delta=1.5)
        _, add2 = rc.degrade_to(smooth, 0.0, seed=4)
        self.assertEqual(add2, 0.0)


@unittest.skipUnless(HAVE, "numpy and scipy needed")
class TestReadouts(unittest.TestCase):
    def setUp(self):
        self.cl = [f"c{i // 5}" for i in range(80)]

    def test_paired_bar(self):
        rng = np.random.default_rng(5)
        pos = 0.05 + 0.02 * rng.standard_normal(80)
        null = 0.02 * rng.standard_normal(80)
        self.assertTrue(rc.paired(pos, self.cl)["passes"])
        self.assertFalse(rc.paired(null, self.cl)["passes"])
        self.assertFalse(rc.paired(-pos, self.cl)["passes"])

    def test_signflip_can_hold_and_fail(self):
        rng = np.random.default_rng(6)
        pos = 0.05 + 0.01 * rng.standard_normal(80)
        cfg = {"draws": 40, "seed": 1, "resamples": 200, "max_pass_share": 0.10}
        self.assertTrue(rc.signflip(pos, self.cl, cfg)["holds"])
        # one cluster label for every row: a flip changes every sign together, so half the draws pass
        self.assertFalse(rc.signflip(pos, ["one"] * 80, cfg)["holds"])

    def test_processing_and_degradation(self):
        rng = np.random.default_rng(7)
        fn = 0.5 + 0.05 * rng.standard_normal(80)
        fb = fn + 0.05
        self.assertTrue(rc.processing_holds(fb, fn + 0.01, self.cl)["holds"])
        self.assertFalse(rc.processing_holds(fb, fn + 0.06, self.cl)["holds"])
        self.assertTrue(rc.degradation_holds(fn + 0.01, fn, 0.05)["holds"])
        self.assertFalse(rc.degradation_holds(fn + 0.04, fn, 0.05)["holds"])
        self.assertIsNone(rc.degradation_holds(fn, fn, -0.01)["holds"])

    def test_border_share_and_rho(self):
        self.assertTrue(rc.border_share([False] * 19 + [True])["holds"])
        self.assertFalse(rc.border_share([False] * 8 + [True] * 2)["holds"])
        rng = np.random.default_rng(8)
        x = rng.standard_normal(80)
        r = rc.rho_ci(x, x + 0.1 * rng.standard_normal(80), self.cl, {"bootstrap": {"resamples": 200, "seed": 0,
                                                                                     "level": 0.95}})
        self.assertGreater(r["rho_ci"][0], 0.8)

    def test_rule(self):
        r = rc.RULE
        self.assertEqual((r["max_shift"], r["inner"], r["band_sigmas"]), (10, 10, [0.7, 2.0]))
        self.assertEqual(sqfid.RULE["max_shift"], 6)          # the shared rule is not changed

    def test_rule_sees_blur_and_a_shift(self):
        rng = np.random.default_rng(8)
        z = np.arange(64)[:, None, None] * np.ones((64, 64, 64))
        ref = 128 + 40 * np.sin(2 * np.pi * z / 7.0) + 6 * rng.standard_normal((64, 64, 64))
        arm = np.roll(ref, 8, axis=0) + 6 * rng.standard_normal((64, 64, 64))
        cube = lambda a: np.clip(np.rint(a), 1, 255).astype(np.uint8)  # noqa: E731
        sharp = sqfid.outcome(cube(arm), cube(ref), rc.RULE)
        self.assertIn(sharp["shift"][0] % 7, (0, 1, 6))
        self.assertFalse(sharp["at_border"])
        blurred = sqfid.outcome(cube(nd.gaussian_filter(arm, 2.0)), cube(ref), rc.RULE)
        self.assertLess(blurred["fidelity"], sharp["fidelity"])


# ---------------------------------------------------------------- the script

class Ex:
    """A stand-in for ProcessPoolExecutor that maps in this process."""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, fn, it):
        return [fn(x) for x in it]


@unittest.skipUnless(HAVE, "numpy and scipy needed")
class TestScript(unittest.TestCase):
    def setUp(self):
        self.mod = _load_script()

    def test_matrices(self):
        mod = self.mod
        for M, scale in ((mod.M_791_TO_324, 7.910 / 3.240), (mod.M_791_TO_324_70, 7.910 / 3.240),
                         (mod.M_791_TO_2399, 7.910 / 2.399), (mod.M_0500_B, 9.362 / 4.317),
                         (mod.M_0500_REF, 9.362 / 2.215)):
            s = np.linalg.svd(np.asarray(M)[:, :3])[1]
            self.assertTrue(np.allclose(s, scale, rtol=0.03), (s, scale))
        for S in mod.SCROLLS.values():
            for u in [S["native"], S["ref"]["url"]] + [a["url"] for a in S["arms"].values()]:
                self.assertTrue(u.startswith(mod.DLS) or u.startswith(mod.OPEN), u)
            self.assertIn("B", S["arms"])

    def _o(self):
        ok = {"holds": True}
        return {"n": 120, "clusters": 40, "outcome_control": {a: dict(ok) for a in ("N", "B", "B70")},
                "border": {a: dict(ok) for a in ("N", "B", "B70")}, "primary": {"passes": True},
                "processing": dict(ok), "degradation": dict(ok), "signflip": dict(ok)}

    def test_dev_verdict(self):
        mod = self.mod
        o = self._o()
        self.assertEqual(mod.dev_verdict(o)["decision"], "GO")
        o["processing"] = {"holds": False}
        v = mod.dev_verdict(o)
        self.assertEqual((v["decision"], v["failed"]), ("NO-GO", ["5_processing"]))
        o["n"] = 50
        self.assertEqual(mod.dev_verdict(o)["decision"], "VOID")
        o.update(n=100, processing={"holds": True}, degradation={"holds": None})
        self.assertEqual(mod.dev_verdict(o)["decision"], "NO-GO")
        o = self._o()
        o["outcome_control"]["B70"] = {"holds": False}
        self.assertEqual(mod.dev_verdict(o)["decision"], "NO-GO")

    def test_test_verdict(self):
        mod = self.mod
        self.assertEqual(mod.test_verdict(self._o())["verdict"], "PASS")
        o = self._o()
        o["primary"] = {"passes": False}
        self.assertEqual(mod.test_verdict(o)["verdict"], "FAIL")
        o = self._o()
        o["degradation"] = {"holds": None}
        self.assertEqual(mod.test_verdict(o)["verdict"], "FAIL")
        for key, arm in (("border", "B"), ("outcome_control", "N")):
            o = self._o()
            o[key][arm] = {"holds": False}
            self.assertEqual(mod.test_verdict(o)["verdict"], "VOID")
        o = self._o()
        o["n"] = 40
        self.assertEqual(mod.test_verdict(o)["verdict"], "VOID")
        o = self._o()
        o["signflip"] = {"holds": False}
        self.assertEqual(mod.test_verdict(o)["verdict"], "VOID")
        # B70's controls are reported but are not instrument checks of the test
        o = self._o()
        o["outcome_control"]["B70"] = {"holds": False}
        o["border"]["B70"] = {"holds": False}
        self.assertEqual(mod.test_verdict(o)["verdict"], "PASS")

    def _toy_scroll(self):
        mod = self.mod
        shift = [[1.0, 0, 0, 10], [0, 1.0, 0, 10], [0, 0, 1.0, 10]]
        mod.SCROLLS["toy"] = {"native": "n", "arms": {"B": {"url": "b", "level": 1, "M": shift}},
                              "ref": {"url": "r", "level": 1, "M": shift}, "null_pair": False}
        mod.shape0 = lambda url: (448, 1024, 1024) if url == "n" else (1024, 1024, 1024)
        self.addCleanup(mod.SCROLLS.pop, "toy", None)

    def test_pool_and_test_pool(self):
        mod = self.mod
        self._toy_scroll()
        with tempfile.TemporaryDirectory() as tmp:
            boxes = Path(tmp) / "boxes.json"
            boxes.write_text(json.dumps([{"name": "a", "z": [0, 3], "y": [1, 1], "x": [0, 3], "seed": 3}]))
            excl = Path(tmp) / "excl.json"
            excl.write_text(json.dumps([{"name": "keep-out", "volume": "native", "z": [260, 300]},
                                        {"volume": "ref", "x": [400, 600]}]))
            out = Path(tmp) / "pool.json"
            self.assertEqual(mod.main(["pool", "--scroll", "toy", "--boxes", str(boxes), "--exclude", str(excl),
                                       "--out", str(out)]), 0)
            d = json.loads(out.read_text())
            zyx = sorted(sqfid.region_index(c["code"]) for c in d["candidates"])
            # z 3 ends past the native extent; z 2 meets the native exclusion, x 3 the reference one (x + 10)
            self.assertEqual(zyx, [(z, 1, x) for z in (0, 1) for x in (0, 1, 2)])
            self.assertEqual(d["dropped"], {"native_extent": 4, "excluded": 6})
            out2 = Path(tmp) / "tpool.json"
            self.assertEqual(mod.main(["test-pool", "--scroll", "toy", "--bands", str(boxes), "--seed", "1",
                                       "--out", str(out2)]), 0)
            t = json.loads(out2.read_text())
            self.assertEqual(t["n_candidates"], 12)
            self.assertEqual(t["seed"], 1)
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps([{"name": "b", "z": [3, 1], "y": [0, 0], "x": [0, 0]}]))
            self.assertEqual(mod.main(["pool", "--scroll", "toy", "--boxes", str(bad), "--out", str(out)]), 1)
            excl.write_text(json.dumps([{"volume": "elsewhere", "z": [0, 1]}]))
            self.assertEqual(mod.main(["pool", "--scroll", "toy", "--boxes", str(boxes), "--exclude", str(excl),
                                       "--out", str(Path(tmp) / "p3.json")]), 1)

    def _fake_measure(self, fake_one):
        mod = self.mod
        old = (mod.concurrent.futures.ProcessPoolExecutor, mod._measure_one, mod._mismatch)
        mod.concurrent.futures.ProcessPoolExecutor = Ex
        mod._measure_one, mod._mismatch = fake_one, lambda a: 0.5

        def restore():
            mod.concurrent.futures.ProcessPoolExecutor, mod._measure_one, mod._mismatch = old
        self.addCleanup(restore)

    def test_measure_records_every_region_read(self):
        mod = self.mod

        def fake_one(item):
            usable = item["code"] % 3 != 0
            row = {"code": item["code"]} if usable else None
            return item, row, ({"N": 0, "B": 0, "B70": 0}, 0) if usable else None, {"N": 1.0}
        self._fake_measure(fake_one)
        codes = [sqfid.region_code((z, 1, 2)) for z in range(20)]
        with tempfile.TemporaryDirectory() as tmp:
            pool = Path(tmp) / "pool.json"
            pool.write_text(json.dumps({"scroll": "PHerc0332", "candidates": [{"code": c, "box": "b"} for c in codes]}))
            out = Path(tmp) / "rows.json"
            mod.main(["measure", "--pool", str(pool), "--n", "4", "--max-candidates", "30", "--workers", "2",
                      "--out", str(out)])
            d = json.loads(out.read_text())
            side = json.loads((Path(tmp) / "rows-read.json").read_text())
            self.assertEqual(mod.main(["measure", "--pool", str(pool), "--out", str(out)]), 1)   # refuses to overwrite
        usable = [c for c in codes if c % 3 != 0]
        self.assertEqual([r["code"] for r in d["rows"]], usable[:4])
        last = codes.index(usable[3])
        # whole batches of 2 x workers are read, so the overrun after the 4th usable region is recorded too
        n_read = (last // 4 + 1) * 4
        self.assertEqual([r["code"] for r in d["read"]], codes[:n_read])
        self.assertEqual(d["n_read"], n_read)
        self.assertEqual(side["read"], d["read"])
        self.assertEqual(d["read"][0]["region"], "0_1_2")
        self.assertEqual(d["rule"], rc.RULE)

        # a run that dies in its second batch keeps both batches in the read log (written before measuring)
        calls = {"n": 0}

        def dying(item):
            calls["n"] += 1
            if calls["n"] > 4:
                raise RuntimeError("network")
            return fake_one(item)
        self.mod._measure_one = dying
        with tempfile.TemporaryDirectory() as tmp:
            pool = Path(tmp) / "pool.json"
            pool.write_text(json.dumps({"scroll": "PHerc0332", "candidates": [{"code": c, "box": "b"} for c in codes]}))
            with self.assertRaises(RuntimeError):
                mod.main(["measure", "--pool", str(pool), "--workers", "2", "--out", str(Path(tmp) / "rows.json")])
            side = json.loads((Path(tmp) / "rows-read.json").read_text())
        self.assertEqual([r["code"] for r in side["read"]], codes[:8])

    def test_test_runs_once_and_reads_out(self):
        mod = self.mod
        rng = np.random.default_rng(9)

        def fake_one(item):
            fn = 0.8 + 0.02 * rng.standard_normal()
            row = {"code": item["code"], "box": item["box"], "cluster": sqfid.cluster_of(item["code"]),
                   "hf": {"N": 1.0, "B": 0.8}, "F_N": fn, "F_B": fn + 0.04, "F_Np": fn - 0.004, "F_Bdeg": fn - 0.01}
            for a in ("N", "B", "Np", "Bdeg"):
                row[f"border_{a}"] = False
            return item, row, ({"N": 0, "B": 0}, 0), {"N": 1.0}
        self._fake_measure(fake_one)
        mod._mismatch = lambda a: 0.1
        fast = {"bootstrap": {"resamples": 200, "seed": 0, "level": 0.95}}
        old = (rc.BOOT, rc.SIGNFLIP)
        rc.BOOT, rc.SIGNFLIP = fast, dict(rc.SIGNFLIP, draws=20, resamples=100)
        self.addCleanup(lambda: setattr(rc, "BOOT", old[0]) or setattr(rc, "SIGNFLIP", old[1]))
        codes = [sqfid.region_code((z, y, 0)) for z in range(0, 40, 2) for y in range(0, 24, 4)]
        with tempfile.TemporaryDirectory() as tmp:
            pool = Path(tmp) / "pool.json"
            pool.write_text(json.dumps({"scroll": "PHerc0500P2",
                                        "candidates": [{"code": c, "box": "t"} for c in codes]}))
            out = Path(tmp) / "test"
            self.assertEqual(mod.main(["test", "--pool", str(pool), "--n", "100", "--workers", "1",
                                       "--out-dir", str(out)]), 0)
            res = json.loads((out / "result.json").read_text())
            self.assertEqual(res["verdict"], "PASS")
            self.assertEqual(res["n"], 100)
            self.assertEqual(res["n_read"], 100)
            self.assertNotIn("energy_B_minus_B70", res)
            # the folder exists now: a second run refuses before reading anything
            self.assertEqual(mod.main(["test", "--pool", str(pool), "--out-dir", str(out)]), 1)
            dev = Path(tmp) / "dev.json"
            self.assertEqual(mod.main(["dev", "--rows", str(out / "rows.json"), "--out", str(dev)]), 0)
            sets = json.loads(dev.read_text())["sets"]
            self.assertIn("null_pair_usable", sets["PHerc0500P2"])


if __name__ == "__main__":
    unittest.main()
