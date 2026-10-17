import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scrolls_inkfilter import core as inkfilter

try:
    import numpy as np
except ImportError:  # the core kit is standard library only
    np = None

try:
    import tifffile
    import zarr
except ImportError:
    tifffile = zarr = None

BRIGHT = {"components": [{"kind": "bright", "face": "bot", "depths": [2], "sign": 1}], "smooth": 2, "background": 0}
TEXTURE = {"components": [{"kind": "texture", "face": "bot", "depths": [1], "sign": 1}], "smooth": 2, "background": 0}


def synthetic(seed=0, Z=40, H=96, W=96):
    """Air (20) around a papyrus sheet (120) from z=14 to z=25; inside the high-z face, in the ink square, the two
    voxels at z=23..24 are brighter (180) and carry a fine checker texture. Returns (vol, ink mask)."""
    rng = np.random.default_rng(seed)
    v = np.full((Z, H, W), 20.0)
    v[14:26] = 120.0
    ink = np.zeros((H, W), bool)
    ink[30:66, 30:66] = True
    checker = ((np.indices((H, W)).sum(0) % 2) * 2 - 1) * 25.0
    for z in (23, 24):
        v[z][ink] = 180.0 + checker[ink]
    v += rng.normal(0, 4, v.shape)
    return np.clip(v, 1, 255).astype(np.uint8), ink


def auc(m, ink):
    a, b = m[ink], m[~ink]
    return float((a[:, None] > b[None, :]).mean() + 0.5 * (a[:, None] == b[None, :]).mean())


@unittest.skipIf(np is None, "numpy is needed for inkfilter")
class FilterTest(unittest.TestCase):
    def test_gaussian_preserves_mean_and_smooths(self):
        rng = np.random.default_rng(0)
        a = rng.random((30, 40)).astype(np.float32)
        g = inkfilter.gaussian(a, 2.0)
        self.assertAlmostEqual(float(g.mean()), float(a.mean()), places=3)
        self.assertLess(float(g.std()), float(a.std()) / 2)
        k = inkfilter.gaussian_kernel(1.5)
        self.assertEqual(len(k), 2 * int(4 * 1.5 + 0.5) + 1)
        self.assertAlmostEqual(float(k.sum()), 1.0, places=6)

    def test_gaussian_kernel_longer_than_axis(self):
        a = np.arange(10, dtype=np.float32).reshape(1, 10)
        g = inkfilter.gaussian(a, (0, 8.0))
        self.assertEqual(g.shape, a.shape)
        self.assertTrue(np.all(np.isfinite(g)))

    def test_box_and_texture(self):
        img = np.ones((9, 9), np.float32) * 7
        self.assertTrue(np.allclose(inkfilter.box(img, 3), 7))
        self.assertTrue(np.allclose(inkfilter.texture(img), 0, atol=1e-3))
        checker = (np.indices((9, 9)).sum(0) % 2).astype(np.float32)
        self.assertGreater(float(inkfilter.texture(checker)[4, 4]), 0.4)
        with self.assertRaises(inkfilter.InkFilterError):
            inkfilter.box(img, 4)

    def test_otsu_splits_two_levels(self):
        x = np.concatenate([np.full(500, 20.0), np.full(500, 120.0)])
        self.assertTrue(20 < inkfilter.otsu(x) < 120)

    def test_faces_find_the_sheet_nearest_the_centre(self):
        v, _ = synthetic()
        g = inkfilter.gaussian(v, inkfilter.PRESMOOTH)
        top, bot, has = inkfilter.faces(g, 70.0)
        self.assertTrue(has.all())
        self.assertEqual(int(np.median(top)), 14)
        self.assertEqual(int(np.median(bot)), 25)

    def test_composite_alpha_follows_vc3d(self):
        stack = np.zeros((3, 2, 2), np.float32)
        stack[0, 0, 0] = 255           # opaque front layer: weight 1, value 1, nothing behind it counts
        stack[1, 0, 0] = 200
        stack[1, 0, 1] = 50            # half-way in the window [0, 100]: weight 0.5, value 0.5
        acc = inkfilter.composite_alpha(stack, 0.0, 100.0)
        self.assertAlmostEqual(float(acc[0, 0]), 1.0, places=5)
        self.assertAlmostEqual(float(acc[0, 1]), 0.25, places=5)
        self.assertEqual(float(acc[1, 1]), 0.0)
        with self.assertRaises(inkfilter.InkFilterError):
            inkfilter.check_recipe({"components": [{"kind": "composite", "face": "bot", "lo": 0.6, "hi": 0.5}]})

    def test_robust_z_ignores_outliers(self):
        m = np.concatenate([np.arange(100, dtype=np.float32), [1e6]])
        z = inkfilter.robust_z(m)
        self.assertAlmostEqual(float(np.median(z)), 0.0, places=4)
        self.assertLess(abs(float(z[50])), 0.1)


@unittest.skipIf(np is None, "numpy is needed for inkfilter")
class InkMapTest(unittest.TestCase):
    def test_bright_component_finds_ink_and_reverse_control_does_not(self):
        v, ink = synthetic()
        m = inkfilter.ink_map(v, BRIGHT)
        self.assertEqual(m.shape, ink.shape)
        self.assertEqual(m.dtype, np.float32)
        self.assertGreater(auc(m, ink), 0.95)
        self.assertLess(auc(inkfilter.ink_map(v, BRIGHT, reverse=True), ink), 0.7)

    def test_texture_component_finds_the_checker(self):
        v, ink = synthetic(1)
        self.assertGreater(auc(inkfilter.ink_map(v, TEXTURE), ink), 0.9)

    def test_signs_flip_the_map(self):
        v, ink = synthetic(2)
        neg = {**BRIGHT, "components": [{**BRIGHT["components"][0], "sign": -1}]}
        self.assertLess(auc(inkfilter.ink_map(v, neg), ink), 0.05)

    def test_background_subtraction_runs(self):
        v, ink = synthetic(3)
        m = inkfilter.ink_map(v, {**BRIGHT, "background": 16})
        self.assertTrue(np.all(np.isfinite(m)))

    def test_bad_recipes_and_windows(self):
        v, _ = synthetic()
        for bad in ({}, {"components": []}, {"components": [{"kind": "colour", "face": "bot", "depths": [1]}]},
                    {"components": [{"kind": "bright", "face": "side", "depths": [1]}]},
                    {"components": [{"kind": "bright", "face": "bot", "depths": []}]},
                    {"components": [{"kind": "bright", "face": "bot", "depths": [1], "sign": 2}]},
                    {**BRIGHT, "smooth": -1}):
            with self.assertRaises(inkfilter.InkFilterError):
                inkfilter.ink_map(v, bad)
        with self.assertRaises(inkfilter.InkFilterError):
            inkfilter.ink_map(v[0], BRIGHT)
        with self.assertRaises(inkfilter.InkFilterError):
            inkfilter.ink_map(np.zeros((10, 8, 8), np.uint8), BRIGHT)
        with self.assertRaises(inkfilter.InkFilterError):
            inkfilter.ink_map(v, "no-such-recipe")

    def test_shipped_recipes_are_valid(self):
        self.assertIn(inkfilter.DEFAULT_RECIPE, inkfilter.RECIPES)
        v, ink = synthetic(4)
        for name, rec in inkfilter.RECIPES.items():
            inkfilter.check_recipe(rec)
            m = inkfilter.ink_map(v, name)
            self.assertEqual(m.shape, ink.shape, name)


