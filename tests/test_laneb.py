"""Tests for the lane B label-free statistics (scripts/experiments/2026-10-07-grok-laneB/laneb.py)."""
import os
import sys
import unittest

try:
    import numpy as np
    import scipy  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "experiments", "2026-10-07-grok-laneB"))


@unittest.skipIf(np is None, "needs numpy and scipy")
class LaneB(unittest.TestCase):
    def setUp(self):
        import laneb
        self.L = laneb

    def test_orientation_of_stripes(self):
        y, x = np.mgrid[0:64, 0:64]
        horiz = np.sin(y / 2.0)                    # lines along x
        vert = np.sin(x / 2.0)                     # lines along y
        a, c = self.L.orientation(horiz)
        self.assertLess(np.median(self.L.axial_diff(a[16:48, 16:48], 0.0)), 0.05)
        self.assertGreater(np.median(c[16:48, 16:48]), 0.9)
        a, _ = self.L.orientation(vert)
        self.assertLess(np.median(self.L.axial_diff(a[16:48, 16:48], np.pi / 2)), 0.05)

    def test_axial_diff(self):
        self.assertAlmostEqual(float(self.L.axial_diff(0.1, np.pi - 0.1)), 0.2, places=6)
        self.assertAlmostEqual(float(self.L.axial_diff(0.0, np.pi / 2)), np.pi / 2, places=6)

    def test_stroke_width_of_bars(self):
        m = np.zeros((100, 100), bool)
        m[10:90, 20:27] = True                     # 7 px wide bar
        w = self.L.stroke_widths(m)
        self.assertTrue(6 <= np.median(w) <= 9, np.median(w))

    def test_autocorr_finds_period(self):
        y, x = np.mgrid[0:200, 0:200]
        img = np.sin(2 * np.pi * y / 25.0)
        ay, ax = self.L.autocorr_profile(img, np.ones_like(img, bool), 60)
        lag, _ = self.L.first_peak(ay, 5)
        self.assertEqual(lag, 25)
        self.assertAlmostEqual(self.L.first_crossing(ay, 0.5), 25 / 6, delta=0.5)

    def test_normals_of_plane(self):
        y, x = np.mgrid[0:10, 0:10].astype(float)
        xyz = np.stack([x, y, np.full_like(x, 5.0)], -1)   # plane z = 5
        n = self.L.normals_from_xyz(xyz, np.ones((10, 10), bool))
        self.assertTrue(np.allclose(np.abs(n[..., 2]), 1.0))

    def test_otsu_splits_two_modes(self):
        v = np.r_[np.zeros(500), np.ones(500) * 10]
        t = self.L.otsu(v)
        self.assertTrue(0 < t < 10)

    def test_shift_null_breaks_correlation(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=(80, 80))
        real, null = self.L.block_shift_null(x, x, np.ones_like(x, bool), [(20, 0), (0, 30)])
        self.assertAlmostEqual(real, 1.0)
        self.assertTrue(np.all(np.abs(null) < 0.1))


if __name__ == "__main__":
    unittest.main()
