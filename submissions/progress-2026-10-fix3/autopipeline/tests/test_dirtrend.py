import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, dirtrend

try:
    import numpy as np
except ImportError:
    np = None
try:
    import zarr
except ImportError:
    zarr = None

LEVELS = (0.55, 0.65, 0.75, 0.85, 0.95)   # one level between each pair of the default thresholds


def counted(above, shape=(100, 100), offset=0):
    """A float map whose count of pixels at or above each default threshold is `above` (non-increasing); the ink
    pixels start at `offset` so two maps can hold different pixels."""
    a = np.full(shape[0] * shape[1], 0.1, np.float32)
    pos = offset
    for i, level in enumerate(LEVELS):
        n = above[i] - (above[i + 1] if i + 1 < len(above) else 0)
        a[pos:pos + n] = level
        pos += n
    return a.reshape(shape)


@unittest.skipIf(np is None, "numpy is needed for kit dirtrend")
class TestReadout(unittest.TestCase):
    def test_strengthening_by_trend(self):
        f = counted([1000, 800, 600, 400, 200])
        r = counted([800, 400, 200, 100, 60], offset=5000)
        res = dirtrend.readout(f, r)
        self.assertEqual((res["call"], res["basis"], res["aa_check"]), ("strengthening", "trend", "pass"))
        self.assertGreater(res["slope"], 0)
        self.assertEqual([row["kind"] for row in res["rows"]], ["paired"] * 5)
        self.assertEqual(res["rows"][0]["forward_px"], 1000)
        self.assertEqual(res["rows"][0]["jaccard"], 0.0)
        self.assertIn("not ink evidence", res["meaning"])     # it did not track the labels on PHerc0841

    def test_weakening_as_on_1447(self):
        f = counted([1000, 600, 300, 150, 60])
        r = counted([500, 400, 300, 200, 100], offset=5000)
        res = dirtrend.readout(f, r)
        self.assertEqual(res["call"], "weakening")
        self.assertLess(res["gain"], 1)

    def test_equal_areas_in_other_places_are_flat(self):
        # freek's 1447 case: the reversed run lights up as much, elsewhere
        f = counted([1000, 800, 600, 400, 200])
        r = counted([1000, 800, 600, 400, 200], offset=5000)
        res = dirtrend.readout(f, r)
        self.assertEqual(res["call"], "flat")
        self.assertTrue(all(row["ratio"] == 1.0 for row in res["rows"]))
        self.assertIn("do not treat", res["meaning"])

    def test_symmetric_noise_never_reads_strengthening(self):
        for seed in range(12):
            rng = np.random.default_rng(seed)
            f = np.clip(rng.normal(0.4, 0.15, (200, 200)), 0, 1).astype(np.float32)
            r = np.clip(rng.normal(0.4, 0.15, (200, 200)), 0, 1).astype(np.float32)
            self.assertEqual(dirtrend.readout(f, r)["call"], "flat", seed)

    def test_reverse_that_empties_is_the_limit_of_strengthening(self):
        f = counted([1000, 800, 600, 400, 200])
        r = counted([500, 200, 40, 10, 0], offset=5000)
        res = dirtrend.readout(f, r)
        self.assertEqual((res["call"], res["basis"]), ("strengthening", "reverse-empties"))
        self.assertEqual([row["kind"] for row in res["rows"]][2:], ["reverse-empty"] * 3)
        # a saturated map with nothing in reverse at any threshold, as the ink script's fake model writes
        res = dirtrend.readout(counted([400] * 5), counted([0] * 5))
        self.assertEqual((res["call"], res["basis"]), ("strengthening", "reverse-empties"))

    def test_a_reverse_empty_top_row_does_not_rescue_weakening(self):
        f = counted([1000, 600, 300, 150, 60])
        r = counted([500, 400, 300, 200, 20], offset=5000)
        self.assertEqual(dirtrend.readout(f, r)["call"], "weakening")

    def test_a_forward_map_that_runs_out_first_is_not_strengthening(self):
        f = counted([1000, 800, 600, 40, 10])
        r = counted([800, 400, 200, 100, 60], offset=5000)
        res = dirtrend.readout(f, r)
        self.assertEqual(res["rows"][3]["kind"], "forward-empty")
        self.assertEqual(res["call"], "flat")

    def test_too_few_pixels(self):
        f = counted([300, 40, 20, 10, 5])
        r = counted([300, 30, 20, 10, 5], offset=5000)
        self.assertEqual(dirtrend.readout(f, r)["call"], "too-few-pixels")

    def test_blank_needs_ct_coverage(self):
        f = counted([10, 0, 0, 0, 0])
        r = counted([10, 0, 0, 0, 0], offset=5000)
        self.assertEqual(dirtrend.readout(f, r)["call"], "blank-unchecked")      # coverage unknown
        ct = np.ones(f.shape, bool)
        ct[:5] = False                                                          # 95 % covered
        res = dirtrend.readout(f, r, ct=ct)
        self.assertEqual((res["call"], res["ct_coverage"]), ("blank", 0.95))
        ct[:50] = False                                                         # half the grid has no scan
        res = dirtrend.readout(f, r, ct=ct)
        self.assertEqual((res["call"], res["ct_coverage"]), ("blank-unchecked", 0.5))
        self.assertEqual(dirtrend.EXIT[res["call"]], 3)

    def test_region_sets_the_coverage_denominator_and_ct_limits_the_count(self):
        f = counted([1000, 800, 600, 400, 200])
        r = counted([800, 400, 200, 100, 60], offset=5000)
        region = np.zeros(f.shape, bool)
        region[:60] = True
        ct = np.zeros(f.shape, bool)
        ct[:57] = True
        res = dirtrend.readout(f, r, ct=ct, region=region)
        self.assertEqual((res["coverage_of"], res["ct_coverage"], res["pixels"]), ("region", 0.95, 5700))
        res = dirtrend.readout(f, r, ct=ct)
        self.assertEqual((res["coverage_of"], res["ct_coverage"]), ("grid", 0.57))
        self.assertIn("warning", res)
        self.assertEqual(res["call"], "strengthening")     # a suspect or trend call stays valid at partial coverage

    def test_no_pixels(self):
        f = counted([1000, 800, 600, 400, 200])
        res = dirtrend.readout(f, f, region=np.zeros(f.shape, bool))
        self.assertEqual(res["call"], "no-pixels")

    def test_aa_check_can_fail(self):
        f = counted([1000, 800, 600, 400, 200])
        r = counted([1000, 800, 600, 400, 200], offset=5000)
        broken = lambda rows, min_gain, min_z=None: (1.0, 2.0, "strengthening", "trend")   # noqa: E731
        with mock.patch.object(dirtrend, "_trend", broken):
            res = dirtrend.readout(f, r)
        self.assertEqual((res["call"], res["aa_check"]), ("void", "fail"))
        self.assertEqual(dirtrend.EXIT["void"], 1)

    def test_uint8_maps_and_label_smoothing(self):
        f8 = (counted([1000, 800, 600, 400, 200]) * 255).round().astype(np.uint8)
        r8 = (counted([800, 400, 200, 100, 60], offset=5000) * 255).round().astype(np.uint8)
        self.assertEqual(dirtrend.readout(f8, r8)["call"], "strengthening")
        # ls: uint8 v -> (v - 64) / 128, so 0.55 * 255 = 140 decodes to 0.59 and still counts above 0.5
        res = dirtrend.readout(f8, r8, decode="ls")
        self.assertEqual(res["decode"], "ls")
        self.assertEqual(res["rows"][0]["forward_px"], 1000)

    def test_bad_input(self):
        f = counted([1000, 800, 600, 400, 200])
        with self.assertRaises(dirtrend.VerifyError):
            dirtrend.readout(f, f[:50])
        with self.assertRaises(dirtrend.VerifyError):
            dirtrend.readout(f, f, thresholds=[0.5, 1.0])
        with self.assertRaises(dirtrend.VerifyError):
            dirtrend.readout(f, f, ct=np.ones((3, 3), bool))

    def test_non_finite_pixels_are_not_counted(self):
        f = counted([1000, 800, 600, 400, 200])
        r = counted([800, 400, 200, 100, 60], offset=5000)
        f[-1, :] = np.nan
        self.assertEqual(dirtrend.readout(f, r)["pixels"], 9900)


@unittest.skipIf(np is None or zarr is None, "numpy and zarr are needed for kit dirtrend files")
class TestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        np.save(self.d / "f.npy", counted([1000, 800, 600, 400, 200]))
        np.save(self.d / "r.npy", counted([800, 400, 200, 100, 60], offset=5000))
        np.save(self.d / "blank.npy", counted([10, 0, 0, 0, 0]))
        vol = np.full((4, 100, 100), 90, np.uint8)
        vol[2, :3] = 0          # 3 rows with a zero layer: 97 % of the grid has CT in every layer
        z = zarr.open(str(self.d / "surface.zarr"), mode="w", shape=vol.shape, chunks=(4, 32, 32), dtype="u1")
        z[:] = vol

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["dirtrend", *argv])
        return code, out.getvalue()

    def test_files_with_surface_and_crop(self):
        res = dirtrend.readout_files(self.d / "f.npy", self.d / "r.npy", surface=self.d / "surface.zarr")
        self.assertEqual((res["call"], res["ct_coverage"], res["pixels"]), ("strengthening", 0.97, 9700))
        res = dirtrend.readout_files(self.d / "f.npy", self.d / "r.npy", surface=self.d / "surface.zarr",
                                     crop=(0, 50, 0, 100))
        self.assertEqual((res["ct_coverage"], res["inputs"]["crop"]), (0.94, [0, 50, 0, 100]))

    def test_cli_exit_codes(self):
        code, text = self.run_cli(str(self.d / "f.npy"), str(self.d / "r.npy"), "--surface",
                                  str(self.d / "surface.zarr"))
        self.assertEqual(code, 0)
        self.assertIn("direction readout: strengthening", text)
        code, _ = self.run_cli(str(self.d / "blank.npy"), str(self.d / "blank.npy"))
        self.assertEqual(code, 3)       # blank, coverage unknown: no call
        code, text = self.run_cli(str(self.d / "blank.npy"), str(self.d / "blank.npy"), "--surface",
                                  str(self.d / "surface.zarr"), "--json")
        self.assertEqual(code, 0)
        self.assertIn('"call": "blank"', text)
        code, _ = self.run_cli(str(self.d / "f.npy"), str(self.d / "missing.npy"))
        self.assertEqual(code, 2)
        code, _ = self.run_cli(str(self.d / "f.npy"), str(self.d / "r.npy"), "--crop", "0", "500", "0", "10")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
