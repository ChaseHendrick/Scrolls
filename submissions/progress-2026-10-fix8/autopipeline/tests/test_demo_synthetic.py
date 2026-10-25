"""The install demo must not announce success when a fake ink subprocess or its outputs fail."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/demo_synthetic.py"
if not SCRIPT.is_file():
    SCRIPT = ROOT / "a script of the source repository"
SPEC = importlib.util.spec_from_file_location("demo_synthetic", SCRIPT)
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


class TestDemoResult(unittest.TestCase):
    def test_completed_stage_statuses_do_not_hide_missing_maps(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"stages": {k: {"status": v} for k, v in demo.WANT.items()}, "surfaces": {
                sid: {"accepted": True, "ink": {"fake-ink": {"exit": 0, "maps": {}}}}
                for sid in ("t00", "t01")}}
            errors = demo.result_errors(state, Path(tmp))
            self.assertEqual(len(errors), 6)
            self.assertTrue(all("map" in err for err in errors))

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in ("numpy", "zarr", "tifffile")),
                         "ink dependencies required to exercise the failed model command")
    def test_failed_fake_command_causes_demo_fail_despite_completed_ink_stage(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(demo, "INK_MODEL", "raise SystemExit(7)\n"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = demo.main(["--out", tmp])
            self.assertEqual(code, 1)
            self.assertIn("DEMO FAIL", output.getvalue())
            self.assertIn("fake ink exited", output.getvalue())
            self.assertNotIn("DEMO PASS", output.getvalue())
            self.assertIn("command engine exited 7", (Path(tmp) / "run/ink/t00/fake-ink/ink.log").read_text())

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in ("numpy", "zarr", "tifffile")),
                         "ink dependencies required to run the demo")
    def test_planted_strokes_show_in_the_forward_map_and_not_in_its_control(self):
        import numpy as np
        import tifffile
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(demo.main(["--out", tmp]), 0)
            for sid in ("t00", "t01"):
                base = Path(tmp) / "run/ink" / sid / "fake-ink"
                f, r = (tifffile.imread(str(base / f"ink_{v}.tif")) for v in "fr")
                on = f > 0
                self.assertTrue(on.mean() > 0.5 and np.array_equal(on, r > 0))   # 0 only off the surface
                paper = np.median(f[on])
                strokes = f[on] > paper + 0.15                  # the planted strokes, well above bare papyrus
                self.assertGreater(strokes.mean(), 0.03)
                self.assertLess((r[on] > paper + 0.15).mean(), 0.2 * strokes.mean())

    def test_strokes_are_rows_of_shapes_over_the_whole_sheet(self):
        segs = demo.strokes()
        self.assertEqual(segs, demo.strokes())                  # fixed seed: the same CT every run
        zs = [z for seg in segs for z, _ in seg]
        ss = [s for seg in segs for _, s in seg]
        self.assertTrue(min(zs) >= 0 and max(zs) < demo.SHAPE[0])
        self.assertGreater(max(ss) - min(ss), 1.8 * 3.14159 * demo.RADIUS)

    def test_empty_and_external_files_are_not_demo_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            root.mkdir()
            external = Path(tmp) / "external.tif"
            external.write_bytes(b"not a demo output")
            empty = root / "empty.tif"
            empty.touch()
            state = {"stages": {k: {"status": v} for k, v in demo.WANT.items()}, "surfaces": {
                sid: {"accepted": True, "ink": {"fake-ink": {"exit": 0, "maps": {
                    "f": {"path": str(empty)}, "r": {"path": str(external)}, "s": {"path": str(root / "absent.tif")}}}}}
                for sid in ("t00", "t01")}}
            self.assertEqual(len(demo.result_errors(state, root)), 6)
