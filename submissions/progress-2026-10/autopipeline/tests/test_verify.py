import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import cli, ledger, verify

try:
    import numpy as np
    import tifffile
except ImportError:  # the core kit is standard library only
    np = tifffile = None

try:
    import imagecodecs  # noqa: F401
    HAVE_LZW = True
except ImportError:
    HAVE_LZW = False


def synthetic_map(seed=0, shape=(300, 400)):
    """Background near 64 (label smoothing puts background low), rows of bright strokes."""
    rng = np.random.default_rng(seed)
    image = np.full(shape, 64, dtype=np.uint8)
    image += rng.integers(0, 4, size=shape, dtype=np.uint8)
    for row in range(40, shape[0] - 40, 60):
        for col in range(20, shape[1] - 30, 35):
            image[row:row + 25, col:col + 6] = 190
    return image


@unittest.skipIf(np is None, "numpy and tifffile are needed for kit verify")
class VerifyArraysTest(unittest.TestCase):
    def setUp(self):
        self.reference = synthetic_map()
        rng = np.random.default_rng(1)
        self.candidate = self.reference.copy()
        # Like the PR #1865 report: a few pixels off by one grey level.
        idx = rng.choice(self.reference.size, size=3, replace=False)
        self.candidate.flat[idx] += 1
        # A wrong-method control: the map with its strokes moved, as a reverse read would.
        self.control = np.roll(self.reference, 17, axis=1)

    def test_pass_needs_agreement_and_a_caught_control(self):
        result = verify.verify_arrays(self.reference, self.candidate, self.control)
        self.assertEqual(result["verdict"], verify.PASS)
        self.assertEqual(result["candidate"]["max_abs_diff"], 1.0)
        self.assertGreater(result["control"]["fraction_over_tolerance"], 0.01)

    def test_without_control_the_verdict_says_so(self):
        result = verify.verify_arrays(self.reference, self.candidate)
        self.assertEqual(result["verdict"], verify.PASS_UNCONTROLLED)

    def test_control_that_agrees_invalidates_the_check(self):
        result = verify.verify_arrays(self.reference, self.candidate, self.candidate)
        self.assertEqual(result["verdict"], verify.CONTROL_NOT_CAUGHT)

    def test_a_different_map_fails(self):
        result = verify.verify_arrays(self.reference, self.control, self.control)
        self.assertEqual(result["verdict"], verify.FAIL)

    def test_shape_mismatch_fails(self):
        result = verify.verify_arrays(self.reference, self.reference[:-1])
        self.assertFalse(result["candidate"]["shape_match"])
        self.assertEqual(result["verdict"], verify.FAIL)

    def test_block_statistics_match_whole_array(self):
        old = verify.ROWS_PER_BLOCK
        verify.ROWS_PER_BLOCK = 7
        try:
            blocked = verify.compare(self.reference, self.control)
        finally:
            verify.ROWS_PER_BLOCK = old
        whole = verify.compare(self.reference, self.control)
        for key in ("max_abs_diff", "pixels_over_tolerance"):
            self.assertEqual(blocked[key], whole[key])
        self.assertAlmostEqual(blocked["mean_abs_diff"], whole["mean_abs_diff"], places=9)
        self.assertAlmostEqual(blocked["pearson"], whole["pearson"], places=9)
        expected = np.corrcoef(self.reference.ravel().astype(float), self.control.ravel().astype(float))[0, 1]
        self.assertAlmostEqual(whole["pearson"], expected, places=9)

    def test_constant_maps_have_no_pearson(self):
        flat = np.zeros((10, 10), dtype=np.uint8)
        self.assertIsNone(verify.compare(flat, flat)["pearson"])


@unittest.skipIf(np is None, "numpy and tifffile are needed for kit verify")
class VerifyFilesTest(unittest.TestCase):
    def write(self, path, array):
        kwargs = {"tile": (128, 128), "bigtiff": True}
        if HAVE_LZW:
            kwargs["compression"] = "lzw"  # what villa's write_output_tiff uses
        tifffile.imwrite(path, array, **kwargs)

    def test_cli_on_villa_style_tiffs_and_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = synthetic_map()
            candidate = reference.copy()
            candidate[0, 0] += 1
            self.write(tmp / "cpu.tif", reference)
            self.write(tmp / "mps.tif", candidate)
            self.write(tmp / "cpu_reverse.tif", np.roll(reference, 17, axis=1))
            root = tmp / "experiments"
            ledger.init("mps", "PHerc0826", "q", "r", root=root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["verify", str(tmp / "cpu.tif"), str(tmp / "mps.tif"),
                                 "--control", str(tmp / "cpu_reverse.tif"), "--json",
                                 "--slug", "mps", "--root", str(root)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["verdict"], verify.PASS)
            record = ledger.load("mps", root)
            self.assertEqual(record["checks"][0]["result"]["verdict"], verify.PASS)
            self.assertEqual(ledger.check("mps", root), [])

    def test_uncontrolled_exit_code_and_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.tif"
            self.write(path, synthetic_map())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["verify", str(path), str(path)]), 3)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["verify", str(path), str(Path(tmp) / "missing.tif")]), 2)


class ProvenanceTest(unittest.TestCase):
    def test_record_hashes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ckpt = tmp / "step-075000.pth"
            ckpt.write_bytes(b"weights")
            ledger.init("p", "PHerc0826", "q", "r", root=tmp)
            record = ledger.add_provenance("p", "infer ...", [str(ckpt)], root=tmp)
            self.assertEqual(record["provenance"][0]["sha256"][str(ckpt)],
                             hashlib.sha256(b"weights").hexdigest())
            with self.assertRaises(ledger.LedgerError):
                ledger.add_provenance("p", "x", [str(tmp / "nope")], root=tmp)


if __name__ == "__main__":
    unittest.main()
