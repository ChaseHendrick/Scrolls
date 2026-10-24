"""kit normalaxis: the scroll axis from normal grids with numpy alone (AutoPipeline's umbilicus backend "normals")."""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kit import normalaxis  # noqa: E402


@unittest.skipIf(np is None, "needs numpy")
class TestEstimate(unittest.TestCase):
    def test_a_spiral_off_the_slice_centre_is_found_and_the_slice_centre_is_not(self):
        lines = normalaxis.spiral_lines(1300.0, 900.0, r1=1200.0)
        r = normalaxis.estimate_slice(lines)
        self.assertLess(math.hypot(r["x"] - 1300.0, r["y"] - 900.0), 2.0)
        # the control the test can fail on: the middle of the polylines' extent is far from the axis here
        m, _, _ = normalaxis.segments(lines)
        mid = (m.min(0) + m.max(0)) / 2
        self.assertGreater(math.hypot(mid[0] - 1300.0, mid[1] - 900.0), 10.0)

    def test_the_answer_moves_with_the_spiral(self):
        a = normalaxis.estimate_slice(normalaxis.spiral_lines(700.0, 800.0, r1=900.0))
        b = normalaxis.estimate_slice(normalaxis.spiral_lines(760.0, 830.0, r1=900.0))
        self.assertAlmostEqual(b["x"] - a["x"], 60.0, delta=2.0)
        self.assertAlmostEqual(b["y"] - a["y"], 30.0, delta=2.0)

    def test_crushed_and_cluttered_slices(self):
        r = normalaxis.estimate_slice(normalaxis.spiral_lines(800.0, 1000.0, squash=0.6, r1=1200.0))
        self.assertLess(math.hypot(r["x"] - 800.0, r["y"] - 1000.0), 5.0)
        lines = normalaxis.spiral_lines(1000.0, 1000.0, r1=1200.0, seed=1) + normalaxis.clutter_lines(
            500, -400.0, 2400.0, seed=2)
        r = normalaxis.estimate_slice(lines)
        self.assertLess(math.hypot(r["x"] - 1000.0, r["y"] - 1000.0), 3.0)

    def test_slices_without_one_centre_give_none_with_a_reason(self):
        spokes = [[(round(1000 + r * math.cos(a)), round(1000 + r * math.sin(a))) for r in range(100, 1500, 20)]
                  for a in (2 * math.pi * k / 48 for k in range(48))]
        for lines in (spokes, normalaxis.clutter_lines(200, 0.0, 2000.0, seed=5), [[(0, 0), (40, 0)]]):
            r = normalaxis.estimate_slice(lines)
            self.assertIsNone(r["x"])
            self.assertTrue(r["reason"])

    def test_deterministic(self):
        lines = normalaxis.spiral_lines(1000.0, 1000.0, r1=900.0, noise=1.5, seed=4)
        self.assertEqual(normalaxis.estimate_slice(lines), normalaxis.estimate_slice(lines))

    def test_selfcheck_passes_and_a_broken_estimator_fails_it(self):
        self.assertTrue(normalaxis.selfcheck()["passes"])
        real = normalaxis.estimate_slice
        try:
            # an estimator that always answers the middle of the polylines must fail the planted checks
            def middle(lines, bounds=None):
                m, _, _ = normalaxis.segments(lines)
                c = (m.min(0) + m.max(0)) / 2
                return {"x": float(c[0]), "y": float(c[1]), "segments": len(m)}
            normalaxis.estimate_slice = middle
            self.assertFalse(normalaxis.selfcheck()["passes"])
        finally:
            normalaxis.estimate_slice = real


@unittest.skipIf(np is None, "needs numpy")
class TestGridFiles(unittest.TestCase):
    def test_grid_files_round_trip_and_the_axis_command(self):
        from kit import surfacepred
        centres = {0: (1000.0, 1100.0), 500: (1010.0, 1105.0), 1000: (1020.0, 1110.0), 1500: (1030.0, 1115.0),
                   2000: (1040.0, 1120.0)}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "xy").mkdir()
            for z, (cx, cy) in centres.items():
                surfacepred.write_grid(Path(tmp) / "xy" / f"{z:06d}.grid", normalaxis.spiral_lines(cx, cy, r1=900.0),
                                       (0, 0, 2400, 2400))
            r = normalaxis.grid_file_estimate(Path(tmp) / "xy" / "000500.grid")
            self.assertLess(math.hypot(r["x"] - 1010.0, r["y"] - 1105.0), 2.0)
            pts, per = normalaxis.estimate_axis(tmp, [0, 500, 1000, 1500, 2000, 2500])
            self.assertEqual(len(pts), 5)
            self.assertEqual(per[2500]["reason"], "no grid file")
            out = Path(tmp) / "axis.json"
            proc = subprocess.run([sys.executable, "-m", "kit", "normalaxis", "axis", tmp, "--slices",
                                   "0,500,1000,1500,2000", "--out", str(out)], cwd=ROOT, capture_output=True,
                                  text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            res = json.loads(proc.stdout)
            self.assertEqual(res["kept"], 5)
            from kit import vc3d_orient
            axis = vc3d_orient.load_umbilicus(str(out))
            self.assertEqual([p[0] for p in axis], [0.0, 500.0, 1000.0, 1500.0, 2000.0])
            x, y = vc3d_orient.centre_at(axis, 1250)
            self.assertLess(math.hypot(x - 1025.0, y - 1112.5), 2.0)

    def test_an_empty_or_broken_file_gives_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty, bad = Path(tmp) / "e.grid", Path(tmp) / "b.grid"
            empty.write_bytes(b"")
            bad.write_bytes(b"not a grid file at all, and long enough to have a header of fifty-two bytes")
            self.assertIsNone(normalaxis.grid_file_estimate(empty)["x"])
            self.assertIsNone(normalaxis.grid_file_estimate(bad)["x"])


if __name__ == "__main__":
    unittest.main()
