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
        self.assertTrue(np.allclose(np.abs(n[1:-1, 1:-1, 2]), 1.0))
        self.assertTrue(np.isnan(n[0]).all())

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

    def test_hole_invalidates_neighbor_differential_stencils(self):
        y, x = np.mgrid[:12, :12].astype(float)
        xyz = np.stack([x + 10, y + 10, np.full_like(x, 5)], -1)
        valid = np.ones((12, 12), bool)
        xyz[5, 5] = -1
        valid[5, 5] = False
        normals = self.L.normals_from_xyz(xyz, valid)
        area = self.L.stretch_from_xyz(xyz, valid)
        self.assertTrue(np.isnan(normals[4:7, 4:7]).all())
        self.assertTrue(np.isnan(area[4:7, 4:7]).all())
        self.assertTrue(np.allclose(np.abs(normals[2:4, 2:4, 2]), 1))
        self.assertTrue(np.allclose(area[2:4, 2:4], 1))

    def test_unknown_annotation_border_cannot_create_label_orientation(self):
        known = np.zeros((128, 128), bool)
        known[20:108, 20:108] = True
        labels = known.astype(float)
        angle, coherence = self.L.orientation(labels, 1, 2, known=known)
        self.assertTrue(np.isnan(coherence[20, 40]))
        self.assertEqual(float(np.nanmax(coherence)), 0)
        changed = np.where(known, labels, 1234.)
        a2, c2 = self.L.orientation(changed, 1, 2, known=known)
        self.assertTrue(np.allclose(angle, a2, equal_nan=True))
        self.assertTrue(np.allclose(coherence, c2, equal_nan=True))

    def test_known_high_pass_ignores_unknown_values_and_requires_support(self):
        known = np.zeros((80, 80), bool)
        known[10:70, 10:70] = True
        labels = np.where(known, 1., 0.)
        h1, core1 = self.L.known_high_pass(labels, known, 2)
        h2, core2 = self.L.known_high_pass(np.where(known, 1., -999.), known, 2)
        self.assertTrue(np.array_equal(core1, core2))
        self.assertTrue(np.allclose(h1[core1], h2[core2]))
        self.assertTrue(np.allclose(h1[core1], 0))
        self.assertFalse(core1[10, 30])
        self.assertTrue(core1[30, 30])

    def test_unknown_background_cannot_determine_stroke_width(self):
        known = np.zeros((100, 100), bool)
        known[20:80, 20:80] = True
        self.assertEqual(self.L.stroke_widths(known, known=known).size, 0)

    def test_stroke_width_survives_when_background_is_known(self):
        known = np.ones((100, 100), bool)
        ink = np.zeros_like(known)
        ink[20:80, 40:47] = True
        widths = self.L.stroke_widths(ink, known=known)
        self.assertGreater(widths.size, 0)
        self.assertTrue(6 <= np.median(widths) <= 9)

    def test_empty_and_constant_autocorrelation_abstain(self):
        image = np.ones((10, 10))
        for known in [np.zeros_like(image, bool), np.ones_like(image, bool)]:
            a, b = self.L.autocorr_profile(image, known, 3)
            self.assertTrue(np.isnan(a).all() and np.isnan(b).all())

    def test_constant_correlation_null_is_unavailable(self):
        image = np.ones((10, 10))
        r, null = self.L.block_shift_null(image, image, np.ones_like(image, bool), [(2, 2)])
        self.assertTrue(np.isnan(r) and np.isnan(null).all())

    def test_unavailable_statistics_are_strict_json_null(self):
        import json
        result = self.L.finite_json({"r": float("nan"), "null": [np.float64(np.inf), -.2]})
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), {"r": None, "null": [None, -.2]})

    def test_streamed_digest_includes_short_last_chunk_and_empty_file(self):
        import hashlib
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "input.tif"
            for payload in [b"", b"known input bytes" * 103]:
                path.write_bytes(payload)
                self.assertEqual(self.L.file_sha256(path, chunk_bytes=7), hashlib.sha256(payload).hexdigest())
            with self.assertRaises(ValueError):
                self.L.file_sha256(path, chunk_bytes=0)


if __name__ == "__main__":
    unittest.main()
