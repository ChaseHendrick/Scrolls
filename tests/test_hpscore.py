import unittest

from kit import hpscore, verify

try:
    import numpy as np
    import scipy  # noqa: F401
except ImportError:  # the core kit is standard library only
    np = None


def letters(shape=(320, 320), seed=0):
    """A key of small strokes (letter scale, a few px wide) on a blank sheet."""
    rng = np.random.default_rng(seed)
    ink = np.zeros(shape, bool)
    for _ in range(140):
        y, x = rng.integers(10, shape[0] - 10), rng.integers(10, shape[1] - 10)
        if rng.random() < 0.5:
            ink[y:y + 2, x:x + 8] = True
        else:
            ink[y:y + 8, x:x + 2] = True
    return ink


@unittest.skipIf(np is None, "numpy and scipy are needed for kit hpscore")
class HpScoreTest(unittest.TestCase):
    def setUp(self):
        self.ink = letters()
        self.mask = np.ones_like(self.ink)

    def test_sharp_read_beats_a_blob_read_with_the_same_pixels_lit(self):
        from scipy.ndimage import gaussian_filter
        sharp = 0.2 + 0.6 * self.ink.astype(float)
        blob = gaussian_filter(sharp, 12)  # ink smeared over its neighbourhood
        s = hpscore.score_array(sharp, self.ink, self.mask, voxel_um=9.362)
        b = hpscore.score_array(blob, self.ink, self.mask, voxel_um=9.362)
        self.assertGreater(s["hp_r"], 0.9)
        self.assertLess(b["hp_r"], s["hp_r"] / 3)
        self.assertLess(s["null_max_abs"], 0.2)

    def test_noise_scores_near_zero(self):
        noise = np.random.default_rng(1).random(self.ink.shape) + 0.01
        r = hpscore.score_array(noise, self.ink, self.mask, voxel_um=9.362)
        self.assertLess(abs(r["hp_r"]), 0.05)

    def test_unlabelled_and_unpredicted_pixels_are_left_out(self):
        mask = self.mask.copy()
        mask[:, :160] = False
        pred = 0.2 + 0.6 * self.ink.astype(float)
        pred[:40] = 0
        r = hpscore.score_array(pred, self.ink, mask, voxel_um=9.362, inner=8)
        full = hpscore.score_array(pred, self.ink, self.mask, voxel_um=9.362)
        self.assertLess(r["px"], full["px"] / 2)
        with self.assertRaises(verify.VerifyError):
            hpscore.score_array(pred, self.ink, mask, voxel_um=9.362, inner=200)


if __name__ == "__main__":
    unittest.main()
