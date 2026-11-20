"""Tests for kit.finite: planted NaN, Inf and fp16-range faults are refused, and the command line's exit codes."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    import numpy as np
except ImportError:   # the map tools' numerical dependency; these tests skip without it
    np = None


@unittest.skipIf(np is None, "numpy not installed")
class FiniteTest(unittest.TestCase):
    def test_nan_inf_and_fp16_range_are_refused(self):
        from kit import finite
        self.assertTrue(finite.stats(np.ones(4, dtype=np.float16))["ok"])
        s = finite.stats(np.array([1.0, np.nan, np.inf], dtype=np.float32))
        self.assertFalse(s["ok"])
        self.assertEqual((s["nan"], s["inf"]), (1, 1))
        self.assertTrue(finite.stats(np.array([7e4]))["ok"])
        self.assertFalse(finite.stats(np.array([7e4]), half=True)["ok"])
        self.assertFalse(finite.stats(np.array([], dtype=np.float32))["ok"])
        with self.assertRaises(finite.NonFinite):
            finite.require(np.array([np.nan]), "normals")

    def test_integer_arrays_are_finite_and_strings_are_refused(self):
        from kit import finite
        s = finite.stats(np.array([0, 255], dtype=np.uint8))
        self.assertTrue(s["ok"])
        self.assertEqual(s["absmax"], 255.0)
        with self.assertRaises(TypeError):
            finite.stats(np.array(["a", "b"]))

    def test_a_bench_records_no_speed_for_nan_output(self):
        from kit import finite
        sec, out = finite.timed(lambda x: x * 2, np.ones(3), name="ok")
        self.assertGreaterEqual(sec, 0.0)
        self.assertEqual(out.tolist(), [2.0, 2.0, 2.0])
        with self.assertRaisesRegex(finite.NonFinite, "model"):
            finite.timed(lambda: (np.ones(2), np.array([np.nan])), name="model")

    def test_timed_skips_metadata_and_refuses_an_unchecked_call(self):
        from kit import finite
        finite.timed(lambda: (np.ones(2), "meta", None, {"k": 1}), name="mixed")
        with self.assertRaisesRegex(finite.NonFinite, "no numeric array"):
            finite.timed(lambda: None, name="inplace")
        buf = np.array([np.nan])
        with self.assertRaises(finite.NonFinite):
            finite.timed(lambda: None, name="inplace", check=lambda: buf)
        self.assertFalse(finite.stats(np.array([3.0]))["constant"])
        self.assertTrue(finite.stats(np.array([3.0, 3.0]))["constant"])

    def test_an_fp16_sum_of_one_128_cubed_tile_overflows(self):
        from kit import finite
        self.assertTrue(finite.sum_overflows(2_097_152, 1.0))           # 128^3 values in [0, 1]
        self.assertFalse(finite.sum_overflows(2_097_152, 1.0, "float32"))
        self.assertFalse(finite.sum_overflows(1000, 1.0))
        with self.assertRaises(ValueError):
            finite.sum_overflows(1, 1.0, "int8")

    def test_a_real_fp16_sum_does_overflow(self):
        # the control for sum_overflows: numpy's own fp16 reduction of the same tile reaches Inf, and stats refuses it
        from kit import finite
        tile = np.ones((128, 128, 128), dtype=np.float16)
        with np.errstate(over="ignore"):
            total = np.sum(tile, dtype=np.float16)
            small = np.sum(tile[:8, :8, :8], dtype=np.float16)
        self.assertTrue(finite.sum_overflows(tile.size, 1.0))
        self.assertTrue(np.isinf(total))
        self.assertFalse(finite.stats(np.array([total]))["ok"])
        self.assertFalse(finite.sum_overflows(512, 1.0))
        self.assertEqual(float(small), 512.0)

    def test_cli_exit_codes(self):
        from kit import finite
        with tempfile.TemporaryDirectory() as d:
            good, bad = Path(d, "good.npy"), Path(d, "bad.npy")
            np.save(good, np.zeros((2, 2), dtype=np.float32))
            np.save(bad, np.array([np.nan], dtype=np.float16))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(finite.main(["check", str(good)]), 0)
                self.assertEqual(finite.main(["check", str(good), str(bad)]), 1)
                self.assertEqual(finite.main(["check", str(Path(d, "missing.npy"))]), 2)
                self.assertEqual(finite.main(["check", str(Path(d, "map.png"))]), 2)
                self.assertEqual(finite.main(["sum", "--count", "2097152", "--max", "1"]), 1)
                self.assertEqual(finite.main(["sum", "--count", "1000", "--max", "1"]), 0)
                self.assertEqual(finite.main(["sum", "--count", "4", "--max", "1", "--dtype", "bad"]), 2)


if __name__ == "__main__":
    unittest.main()
