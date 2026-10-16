"""Tests for kit.vc3d_seat: is a surface seated on a sheet, and in which frame.

The stacks are synthetic, built layer by layer from a depth profile, so every score below is worked
out by hand in the comments.
"""
import array
import random
import unittest

from kit import vc3d_seat


def stack(profile, h=40, w=40, holes=0):
    """(shape, data) of len(profile) layers, every pixel following the profile; the first `holes`
    pixels are 0 in layer 0 (off the surface)."""
    n = len(profile)
    data = bytearray()
    for k, v in enumerate(profile):
        layer = bytearray([v]) * (h * w)
        if k == 0:
            layer[:holes] = bytes(holes)
        data += layer
    return (n, h, w), bytes(data)


def windings(n=33, centre=200, neighbour=150, void=20, spacing=12, offset=0):
    """A sheet 3 layers thick at the middle (shifted by offset) between neighbours `spacing` away."""
    mid = n // 2 + offset
    out = []
    for k in range(n):
        d = k - mid
        out.append(centre if abs(d) <= 1 else neighbour if abs(abs(d) - spacing) <= 1 else void)
    return out


class TestSeating(unittest.TestCase):
    def test_seated_surface(self):
        res = vc3d_seat.seating(*stack(windings()))
        # the two-sided profile walking out is 20 until the neighbours at 12 layers; its smoothed
        # (zero padded) curve first bottoms out at 6 layers, so the gap is 6 and the contrast is the
        # centre 200 minus the void 20 at +-6, over every pixel (coverage 1)
        self.assertEqual((res["gap"], res["coverage"], res["contrast"], res["score"]), (6, 1.0, 180.0, 180.0))
        self.assertEqual(res["sheet_contrast"], 180.0)  # middle minus the mean of the layers 25 out (here 16, the ends)
        self.assertEqual((res["valid_pixels"], res["layers"]), (1600, 33))
        self.assertEqual(res["profile"][16], 200.0)
        self.assertEqual(vc3d_seat.verdict(res), "seated")

    def test_surface_between_windings_is_not_seated(self):
        res = vc3d_seat.seating(*stack(windings(offset=6)))  # centre layer in the void
        self.assertEqual((res["score"], res["contrast"], res["coverage"], res["surface_mean"]), (-1.0, None, 0.0, 20.0))
        self.assertEqual(vc3d_seat.verdict(res), "not seated")

    def test_weak_contrast_is_unclear(self):
        profile = [45] * 33
        profile[16] = 50
        res = vc3d_seat.seating(*stack(profile))
        self.assertEqual((res["gap"], res["contrast"], res["score"]), (6, 5.0, 5.0))
        self.assertEqual(vc3d_seat.verdict(res), "unclear")

    def test_material_threshold_and_gap_override(self):
        profile = [10] * 33
        profile[16] = 30
        self.assertEqual(vc3d_seat.seating(*stack(profile))["score"], -1.0)  # 30 is not material at 40
        res = vc3d_seat.seating(*stack(profile), material=25)
        self.assertEqual((res["coverage"], res["contrast"]), (1.0, 20.0))
        self.assertEqual(vc3d_seat.seating(*stack(profile), gap=40)["gap"], 16)  # at most the middle

    def test_off_surface_pixels_are_left_out(self):
        res = vc3d_seat.seating(*stack(windings(), holes=600))
        self.assertEqual(res["valid_pixels"], 1000)
        res = vc3d_seat.seating(*stack(windings(), h=4, w=4, holes=16))
        self.assertEqual((res["valid_pixels"], res["score"], res["gap"], res["profile"]), (0, -1.0, None, []))

    def test_sheet_contrast_needs_enough_pixels(self):
        res = vc3d_seat.seating(*stack(windings(), h=10, w=10))
        self.assertIsNone(res["sheet_contrast"])
        self.assertEqual(res["contrast"], 180.0)
        self.assertEqual(vc3d_seat.sheet_contrast([1, 5, 1], span=1), 4.0)

    def test_probe_gap_on_short_profiles(self):
        self.assertEqual(vc3d_seat.probe_gap([0, 1, 2, 9, 2, 1, 0]), 3)  # too short to search: the middle
        self.assertEqual(vc3d_seat.probe_gap([1] * 61, fallback=25), 6)  # flat: the first minimum clear of the zero-padded end

    def test_verdict_thresholds(self):
        self.assertEqual(vc3d_seat.verdict({"score": -1.0, "contrast": None}), "not seated")
        self.assertEqual(vc3d_seat.verdict({"score": 10.0, "contrast": vc3d_seat.SEATED_CONTRAST}), "seated")
        self.assertEqual(vc3d_seat.verdict({"score": 3.0, "contrast": vc3d_seat.UNSEATED_CONTRAST}), "not seated")
        self.assertEqual(vc3d_seat.verdict({"score": 6.0, "contrast": 6.0}), "unclear")

    def test_best_frame(self):
        rows = [{"scale_segmentation": 1.0, "score": -1.0}, {"scale_segmentation": 2.0, "score": 30.0},
                {"scale_segmentation": 0.5, "score": 12.0}]
        ranked, margin = vc3d_seat.best_frame(rows)
        self.assertEqual([r["scale_segmentation"] for r in ranked], [2.0, 0.5, 1.0])
        self.assertEqual(margin, 18.0)
        self.assertIsNone(vc3d_seat.best_frame(rows[:1])[1])


class TestFastPaths(unittest.TestCase):
    def test_bytes_and_arrays_score_the_same(self):
        rng = random.Random(7)
        n, h, w = 21, 30, 30
        data = bytes(0 if rng.random() < 0.02 else rng.randrange(256) for _ in range(n * h * w))
        fast = vc3d_seat.seating((n, h, w), data)
        self.assertEqual(vc3d_seat.seating((n, h, w), array.array("B", data)), fast)
        self.assertEqual(vc3d_seat.seating((n, h, w), array.array("H", list(data))), fast)
        self.assertEqual(vc3d_seat.valid_pixels((n, h, w), data), vc3d_seat.valid_pixels((n, h, w), array.array("B", data)))
        self.assertEqual(vc3d_seat.profile((n, h, w), data, [0, 5, 9]),
                         [sum(data[k * h * w + i] for i in (0, 5, 9)) / 3 for k in range(n)])


class TestSLocal(unittest.TestCase):
    def test_one_profile_everywhere(self):
        # at 9.362 um: columns of round(300 / 9.362) = 32 px, +-round(131 / 9.362) = 14 layers, no smoothing.
        # Layers 2 to 30 of the windings profile: 20 voids, 6 neighbours at 150, 3 centre layers at 200, so the
        # median is 20 and every column scores (200 - 20) / 20 = 9
        res = vc3d_seat.s_local([stack(windings())], 9.362)
        self.assertEqual((res["s_local"], res["columns"], res["column_px"], res["half_layers"], res["smooth_layers"]),
                         (9.0, 40, 32, 14, 1))
        self.assertEqual(res["quartiles"], [9.0, 9.0])
        self.assertNotIn("note", res)

    def test_smoothing_over_about_ten_um(self):
        # at 10/3 um: 3 layers of smoothing turn a one-layer spike of 210 over 30 into 90, so (90 - 30) / 30 = 2
        profile = [30] * 81
        profile[40] = 210
        res = vc3d_seat.s_local([stack(profile, h=20, w=20)], 10 / 3, columns=5)
        self.assertEqual((res["s_local"], res["smooth_layers"], res["half_layers"], res["column_px"]), (2.0, 3, 39, 90))

    def test_columns_need_the_surface_under_them(self):
        shape, data = stack(windings(), h=64, w=64)
        half = bytearray(data)
        plane = 64 * 64
        for k in range(shape[0]):          # the left half is off the surface in every layer
            for r in range(64):
                half[k * plane + r * 64:k * plane + r * 64 + 32] = bytes(32)
        rng = random.Random(1)
        vals = vc3d_seat.s_local_columns(shape, bytes(half), 9.362, 10, rng)
        self.assertEqual(vals, [9.0] * 10)   # only columns at least half on the surface count
        self.assertEqual(vc3d_seat.s_local_columns(*stack([0] * 33), 9.362, 3, rng), [])

    def test_stacks_share_the_columns_and_short_stacks_are_noted(self):
        a, b = stack(windings()), stack(windings(), h=50, w=50)
        res = vc3d_seat.s_local([a, b], 9.362, seed=3, columns=7)
        self.assertEqual((res["columns"], res["seed"]), (7, 3))
        self.assertEqual(vc3d_seat.s_local([a, b], 9.362, seed=3, columns=7), res)
        short = vc3d_seat.s_local([stack(windings(n=9, spacing=3))], 9.362)
        self.assertIn("short of +-131.0 um", short["note"])
        with self.assertRaises(ValueError):
            vc3d_seat.s_local([a], 0)


if __name__ == "__main__":
    unittest.main()
