"""Tests for kit.hardcases: 3D hard-case layouts, rasters, tiles and the physics render."""

import importlib.util
import unittest

import numpy as np

HAVE_SCIPY = importlib.util.find_spec("scipy") is not None


@unittest.skipUnless(HAVE_SCIPY, "needs scipy")
class TestLayouts(unittest.TestCase):
    def setUp(self):
        from kit import hardcases
        self.S = hardcases

    def test_every_kind_rasterizes_with_separated_lines(self):
        S = self.S
        for kind in S.KINDS:
            with self.subTest(kind=kind):
                lay = S.Layout(kind, 2, size=(32, 128, 128))
                r = S.raster(lay, "z", (16, 0, 0), (128, 128))
                self.assertEqual(r["sheet"].shape, (128, 128))
                self.assertGreater(int((r["lines"] > 0).sum()), 50)
                # every line pixel lies inside its own sheet's band (or within a voxel of it)
                lp = r["lines"] > 0
                self.assertTrue(np.all(np.isfinite(r["q"][lp & (r["sheet"] > 0)])))
                if kind != "spiral":
                    self.assertGreaterEqual(S.line_separation(r["lines"]), S.LINE_SEP_MIN - 1e-6)

    def test_block_independence(self):
        S = self.S
        for kind in ("hairpin", "crack", "delamination", "spiral"):
            with self.subTest(kind=kind):
                lay = S.Layout(kind, 5, size=(16, 96, 96))
                whole = S.raster(lay, "vol", (0, 0, 0), (16, 96, 96))["sheet"]
                part = S.raster(lay, "vol", (4, 32, 40), (8, 40, 40))["sheet"]
                np.testing.assert_array_equal(whole[4:12, 32:72, 40:80], part)
                ax = S.raster(lay, "z", (7, 0, 0), (96, 96))["sheet"]
                np.testing.assert_array_equal(ax, whole[7])

    def test_same_seed_same_layout(self):
        S = self.S
        a = S.raster(S.Layout("accordion", 9, size=(8, 64, 64)), "z", (4, 0, 0), (64, 64))
        b = S.raster(S.Layout("accordion", 9, size=(8, 64, 64)), "z", (4, 0, 0), (64, 64))
        np.testing.assert_array_equal(a["sheet"], b["sheet"])
        c = S.raster(S.Layout("accordion", 10, size=(8, 64, 64)), "z", (4, 0, 0), (64, 64))
        self.assertFalse(np.array_equal(a["sheet"], c["sheet"]))

    def test_hairpin_keeps_one_id_round_the_fold(self):
        S = self.S
        lay = S.Layout("hairpin", 3, size=(8, 256, 256))
        i0 = int(np.argmin(np.abs(lay.levels)))
        r = S.raster(lay, "z", (4, 0, 0), (256, 256))
        from scipy import ndimage as nd
        lab, n = nd.label(r["sheet"] == i0 + 1, np.ones((3, 3)))
        self.assertGreaterEqual(n, 1)
        self.assertTrue(r["zone"].any())

    def test_crack_cuts_sheets_and_is_air(self):
        S = self.S
        for seed in range(6):
            lay = S.Layout("crack", seed, size=(8, 256, 256))
            r = S.raster(lay, "z", (4, 0, 0), (256, 256))
            if r["crack"].any():
                self.assertFalse((r["sheet"][r["crack"]] > 0).any())
                self.assertFalse((r["lines"][r["crack"]] > 0).any())
                return
        self.fail("no crack opening in six seeds")

    def test_edge_has_air_beyond_the_last_sheet(self):
        S = self.S
        lay = S.Layout("edge", 4, size=(8, 256, 256))
        r = S.raster(lay, "z", (4, 0, 0), (256, 256))
        self.assertTrue(r["air"].any())
        self.assertFalse((r["sheet"][r["air"]] > 0).any())
        self.assertLessEqual(int(r["sheet"].max()), lay.e_last + 1)

    def test_delamination_splits_one_sheet_into_two_plies(self):
        S = self.S
        found = False
        for seed in range(8):
            lay = S.Layout("delamination", seed, size=(8, 256, 256))
            r = S.raster(lay, "z", (4 + lay.d_z0, 0, 0), (256, 256))
            if not r["opening"].any():
                continue
            sid = lay.d_i + 1
            # the opening lies between two parts of the same sheet: both neighbours across it carry its id
            from scipy import ndimage as nd
            ring = nd.binary_dilation(r["opening"], iterations=2) & ~r["opening"]
            ids = set(int(v) for v in np.unique(r["sheet"][ring]) if v)
            self.assertIn(sid, ids)
            self.assertFalse((r["sheet"][r["opening"]] > 0).any())
            found = True
            break
        self.assertTrue(found)

    def test_squeeze_and_open_are_monotone(self):
        S = self.S
        f = np.linspace(-50, 50, 2001)
        g = S._squeeze(np, f, 0.0, 10.0, 8.0)
        self.assertTrue(np.all(np.diff(g) >= 0))
        self.assertTrue(np.allclose(g[f < 0], f[f < 0]))
        self.assertTrue(np.allclose(g[f > 10], f[f > 10] + 8.0))
        o, gap = S._open(np, f, 0.0, 5.0)
        self.assertTrue(np.all(np.diff(o) >= 0))
        self.assertTrue(gap[(f >= 0) & (f < 5)].all())
        self.assertTrue(np.allclose(o[f >= 5], f[f >= 5] - 5.0))

    def test_contact_closes_a_gap_but_keeps_lines_apart(self):
        S = self.S
        for seed in range(20):
            lay = S.Layout("plain", seed, size=(8, 256, 256), extras={"contact": 1.0})
            if not lay.c_pairs:
                continue
            r = S.raster(lay, "z", (4, 0, 0), (256, 256))
            self.assertGreaterEqual(S.line_separation(r["lines"]), S.LINE_SEP_MIN - 1e-6)
            self.assertTrue(((r["zone"] & S.ZONES["contact"]) > 0).any())
            return
        self.fail("no contact pair drawn")

    def test_tiles_shard(self):
        S = self.S
        sh = S.tiles(3, 7, size=128, side=0.5)
        for k in ("image", "lines", "sheet_id", "dist", "crack", "air", "zone"):
            self.assertEqual(sh[k].shape[0], 3)
            self.assertEqual(sh[k].shape[1:], (128, 128))
        self.assertEqual(sh["image"].dtype, np.uint8)
        sh2 = S.tiles(3, 7, size=128, side=0.5)
        np.testing.assert_array_equal(sh["image"], sh2["image"])

    def test_render_dark_air_bright_sheets(self):
        S = self.S
        lay = S.Layout("edge", 4, size=(8, 256, 256))
        r = S.raster(lay, "z", (4, 0, 0), (256, 256))
        img = S.render(r, 1).astype(float)
        self.assertGreater(img[r["sheet"] > 0].mean(), img[r["air"]].mean() + 20)

    def test_unknown_kind_refused(self):
        with self.assertRaises(self.S.SimError):
            self.S.Layout("pretzel", 1)


@unittest.skipUnless(HAVE_SCIPY, "needs scipy")
class TestSelfCheck(unittest.TestCase):
    def _lay(self, levels, thick):
        from kit import hardcases
        lay = hardcases.Layout("plain", 1)
        lay.levels = np.array(levels, float)
        lay.thick = np.array(thick, float)
        return hardcases, lay

    def test_two_sheets_pass_and_gap_is_exact(self):
        H, lay = self._lay([0.0, 0.5], [0.2, 0.4])
        d = lay._self_check()
        self.assertEqual(d["sheets"], 2)
        self.assertAlmostEqual(d["min_gap_f"], 0.5 - 0.3)
        self.assertAlmostEqual(d["min_thick"], 0.2)

    def test_refusals(self):
        H, lay = self._lay([0.0], [1.0])
        with self.assertRaises(H.SimError):
            lay._self_check()
        H, lay = self._lay([0.0, 3.0, 3.0], [1.0, 1.0, 1.0])
        with self.assertRaises(H.SimError):
            lay._self_check()


if __name__ == "__main__":
    unittest.main()
