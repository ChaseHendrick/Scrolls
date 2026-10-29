"""Tests for kit/snaptruth.py: registration along the normal, sheet faces, gains and the site bootstrap.

Synthetic profiles only. Each measuring step is shown recovering a planted answer and failing where it should."""

import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover - the map tests skip without numpy
    np = None

if np is not None:
    from kit import snaptruth as T


def sheets(t, centres, half=3.0, edge=0.4, lo=30.0, hi=120.0):
    """A profile of bright bands of half width `half` around each center, soft edges of width `edge`."""
    p = np.full_like(t, lo, dtype=float)
    for c in centres:
        p += (hi - lo) / (1 + np.exp((np.abs(t - c) - half) / edge))
    return p


@unittest.skipIf(np is None, "needs numpy")
class SmoothTest(unittest.TestCase):
    def test_constant_and_symmetry(self):
        p = np.full(50, 7.0)
        np.testing.assert_allclose(T.smooth(p, 2.0), p)
        d = np.zeros(41)
        d[20] = 1.0
        s = T.smooth(d, 3.0)
        np.testing.assert_allclose(s, s[::-1], atol=1e-12)
        self.assertAlmostEqual(float(s.sum()), 1.0, places=6)

    def test_shifted_reads_offsets(self):
        t_ext = np.arange(-10, 10.01, 0.125)
        prof = np.atleast_2d(2.0 * t_ext)
        t = np.arange(-5, 5.01, 0.25)
        np.testing.assert_allclose(T.shifted(t_ext, prof, t, 0.3)[0], 2.0 * (t + 0.3), atol=1e-9)
        self.assertTrue(np.isnan(T.shifted(t_ext, prof, np.array([9.9]), 0.5)[0, 0]))


@unittest.skipIf(np is None, "needs numpy")
class RegisterTest(unittest.TestCase):
    def setUp(self):
        self.t = np.arange(-26, 26.001, 0.25)
        self.t_ext = np.arange(-31, 31.001, 0.125)
        rng = np.random.default_rng(0)
        self.lines = []
        for _ in range(20):
            base = rng.uniform(-2, 2)
            self.lines.append([base - 32, base - 16 + rng.uniform(-1, 1), base, base + 16 + rng.uniform(-1, 1),
                               base + 32])

    def make(self, true_shift, centre_extra=0.0, noise=2.0, seed=1):
        rng = np.random.default_rng(seed)
        ref = np.stack([sheets(self.t, c) + rng.normal(0, noise, len(self.t)) for c in self.lines])
        # the moving scan shows each feature at t + true_shift, so reading it at t + true_shift lines it up;
        # centre_extra moves only the middle sheet of the moving scan
        mov = []
        for c in self.lines:
            cc = [x + true_shift for x in c]
            cc[2] += centre_extra
            mov.append(sheets(self.t_ext, cc, edge=0.25) * 0.8 + 10 + rng.normal(0, noise, len(self.t_ext)))
        return ref, np.stack(mov)

    def test_recovers_planted_shift(self):
        for s in (-1.3, 0.0, 0.37, 2.2):
            ref, mov = self.make(s)
            r = T.register_shift(self.t, ref, self.t_ext, mov, np.abs(self.t) >= 12)
            self.assertAlmostEqual(r["shift"], s, delta=0.06, msg=f"planted {s}")
            self.assertGreater(r["peak"], 0.9)
            self.assertFalse(r["edge"])

    def test_leave_band_out_ignores_the_middle_sheet(self):
        # the middle sheet alone is displaced by 1.5 in the moving scan; leaving it out keeps the true shift,
        # while using every sample is pulled toward the displaced sheet
        ref, mov = self.make(0.5, centre_extra=1.5)
        out = T.register_shift(self.t, ref, self.t_ext, mov, np.abs(self.t) >= 12)
        full = T.register_shift(self.t, ref, self.t_ext, mov, np.ones_like(self.t, bool))
        self.assertAlmostEqual(out["shift"], 0.5, delta=0.06)
        self.assertGreater(full["shift"], out["shift"] + 0.2)

    def test_structureless_profiles_fail(self):
        rng = np.random.default_rng(5)
        ref = rng.normal(0, 1, (20, len(self.t)))
        mov = rng.normal(0, 1, (20, len(self.t_ext)))
        r = T.register_shift(self.t, ref, self.t_ext, mov, np.abs(self.t) >= 12)
        self.assertLess(r["peak"], 0.3)

    def test_shift_beyond_range_is_at_the_edge(self):
        ref, mov = self.make(6.0)
        r = T.register_shift(self.t, ref, self.t_ext, mov, np.abs(self.t) >= 12, s_max=2.0)
        self.assertTrue(r["edge"])


@unittest.skipIf(np is None, "needs numpy")
class FacesTest(unittest.TestCase):
    t = np.arange(-16, 16.001, 0.25) if np is not None else None

    def test_faces_of_a_clean_band(self):
        p = sheets(self.t, [-20, 4.0, 22], half=3.0)
        up = T.sheet_faces(self.t, p, recto_sign=1)
        self.assertTrue(up["ok"])
        self.assertAlmostEqual(up["recto"], 1.0, delta=0.2)    # recto_sign +1: the lower face
        self.assertAlmostEqual(up["verso"], 7.0, delta=0.2)
        self.assertAlmostEqual(up["mid"], 4.0, delta=0.1)
        self.assertAlmostEqual(up["dist"], 1.0, delta=0.2)
        down = T.sheet_faces(self.t, p, recto_sign=-1)
        self.assertAlmostEqual(down["recto"], 7.0, delta=0.2)  # recto_sign -1: the upper face
        self.assertFalse(up["split"])

    def test_noise_does_not_move_faces_much(self):
        rng = np.random.default_rng(3)
        p = sheets(self.t, [-14, 2.0, 18], half=3.5) + rng.normal(0, 6, len(self.t))
        r = T.sheet_faces(self.t, p, recto_sign=1)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["mid"], 2.0, delta=0.3)

    def test_ambiguous_between_two_bands(self):
        p = sheets(self.t, [-6.0, 6.0], half=3.0)          # label at 0, both bands 3 away
        r = T.sheet_faces(self.t, p, recto_sign=1)
        self.assertFalse(r["ok"])
        self.assertIn("two bands", r["why"])

    def test_band_off_the_profile_is_not_ok(self):
        p = sheets(self.t, [14.0], half=4.0)
        r = T.sheet_faces(self.t, p, recto_sign=1)
        self.assertFalse(r["ok"])

    def test_split_and_gaps(self):
        # a band made of two layers with a 1.5-wide dark gap: the coarse finder closes nothing (gap > fill), so
        # with fill 2.0 it is one band that splits at fine scale
        p = sheets(self.t, [-2.0, 3.0], half=1.75, edge=0.2)
        p = np.minimum(p, 200)
        coarse = T.sheet_faces(self.t, p, recto_sign=1, opts={"sigma": 0.5, "fill": 2.5})
        self.assertTrue(coarse["split"])
        clean = T.sheet_faces(self.t, sheets(self.t, [-18, 0.0, 15], half=3.0), recto_sign=1)
        self.assertFalse(clean["split"])
        self.assertAlmostEqual(clean["gap_verso"], 15 - 3 - 3.0, delta=0.3)


@unittest.skipIf(np is None, "needs numpy")
class GradientFacesTest(unittest.TestCase):
    """gradient_faces: the second face rule (steepest edge), which shares only the band's identity with sheet_faces."""
    t = np.arange(-16, 16.001, 0.25) if np is not None else None

    def test_symmetric_band_agrees_with_the_half_level(self):
        p = sheets(self.t, [-20, 4.0, 22], half=3.0)
        h = T.sheet_faces(self.t, p, 1, opts={"sigma": 1.0})
        g = T.gradient_faces(self.t, p, 1, opts={"sigma": 1.0})
        self.assertTrue(g["ok"])
        self.assertAlmostEqual(g["recto"], 1.0, delta=0.15)
        self.assertAlmostEqual(g["verso"], 7.0, delta=0.15)
        # the half-level face sits a little outside the true face here (its 90th percentile falls on the soft edge
        # of a band that fills a fifth of the profile); the steepest edge does not depend on that level
        self.assertAlmostEqual(g["recto"], h["recto"], delta=0.3)
        self.assertEqual(g["recto_half"], h["recto"])
        down = T.gradient_faces(self.t, p, -1, opts={"sigma": 1.0})
        self.assertAlmostEqual(down["recto"], 7.0, delta=0.15)

    def test_a_raised_floor_moves_the_half_level_but_not_the_steepest_edge(self):
        # papyrus bright on the verso side of the gap: the 10th percentile rises, the half level climbs the soft
        # recto edge, and the half-level face moves inward; the steepest edge stays at the true face (1.0)
        p = sheets(self.t, [4.0], half=3.0, edge=0.9)
        p = np.where(self.t > 9.0, 110.0, p)
        h = T.sheet_faces(self.t, p, 1, opts={"sigma": 1.0, "ambiguous": 0.0})
        g = T.gradient_faces(self.t, p, 1, opts={"sigma": 1.0, "ambiguous": 0.0})
        self.assertTrue(g["ok"])
        self.assertAlmostEqual(g["recto"], 1.0, delta=0.3)
        self.assertGreater(abs(h["recto"] - 1.0), abs(g["recto"] - 1.0))

    def test_no_band_or_no_edge_is_not_ok(self):
        flat = np.full_like(self.t, 50.0)
        self.assertFalse(T.gradient_faces(self.t, flat, 1)["ok"])
        ramp = np.clip(self.t * 10 + 100, 0, 400)          # one rising edge and no falling one inside the profile
        self.assertFalse(T.gradient_faces(self.t, ramp, 1)["ok"])

    def test_noise_keeps_the_edge_near(self):
        rng = np.random.default_rng(5)
        p = sheets(self.t, [-14, 2.0, 18], half=3.5) + rng.normal(0, 6, len(self.t))
        g = T.gradient_faces(self.t, p, 1, opts={"sigma": 1.0})
        self.assertTrue(g["ok"])
        self.assertAlmostEqual(g["recto"], -1.5, delta=0.5)
        self.assertAlmostEqual(g["verso"], 5.5, delta=0.5)


@unittest.skipIf(np is None, "needs numpy")
class GainTest(unittest.TestCase):
    def test_depth_and_offsheet(self):
        np.testing.assert_allclose(T.depth([1.0, 4.0, 7.0], 1.0, 7.0), [0.0, 0.5, 1.0])
        np.testing.assert_allclose(T.depth([1.0], 7.0, 1.0), [1.0])
        np.testing.assert_allclose(T.offsheet([0.0, 2.0, 9.0], 1.0, 7.0), [1.0, 0.0, 2.0])
        np.testing.assert_allclose(T.offsheet([0.0], 7.0, 1.0), [1.0])

    def test_gains_sign(self):
        g = T.gains(x_arm=[0.5, 3.0], x_id=[0.0, 0.0], truth=[1.0, 1.0])
        np.testing.assert_allclose(g, [0.5, -1.0])

    def test_random_sign_cannot_gain_on_average(self):
        # the random-sign control moves each label by the snap's distance in a random direction; its expected
        # gain is never positive (triangle inequality), so it is a fair null
        rng = np.random.default_rng(11)
        e = rng.normal(0, 2, 20000)          # label error before
        d = rng.normal(0, 1.5, 20000)        # snap displacement
        s = rng.choice([-1, 1], 20000)
        g = np.abs(e) - np.abs(e - s * d)
        self.assertLess(float(g.mean()), 0.0)

    def test_site_bootstrap_and_classes(self):
        ids, means, counts = T.site_means([1.0, 3.0, 2.0, np.nan], [0, 0, 1, 1])
        self.assertEqual(ids, [0, 1])
        np.testing.assert_allclose(means, [2.0, 2.0])
        np.testing.assert_array_equal(counts, [2, 1])
        ci = T.site_bootstrap([0.5] * 10)
        self.assertAlmostEqual(ci["lo"], 0.5)
        self.assertEqual(T.classify(ci, 0.1), "GAIN")
        self.assertEqual(T.classify(T.site_bootstrap([-0.5] * 10), 0.1), "HARM")
        self.assertEqual(T.classify(T.site_bootstrap([0.01, -0.01] * 10), 0.1), "NULL")
        rng = np.random.default_rng(2)
        self.assertEqual(T.classify(T.site_bootstrap(rng.normal(0.05, 1.0, 12)), 0.1), "INCONCLUSIVE")
        self.assertEqual(T.classify(T.site_bootstrap([]), 0.1), "NO DATA")

    def test_small_positive_gain_is_not_called_gain(self):
        ci = T.site_bootstrap([0.05] * 20)
        self.assertEqual(T.classify(ci, 0.1), "NULL")


if __name__ == "__main__":
    unittest.main()
