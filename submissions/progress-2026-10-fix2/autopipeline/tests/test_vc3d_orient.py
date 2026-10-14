"""Tests for kit.vc3d_orient: does a surface's normal point toward the scroll's centre, one sign per patch.

The surfaces are arcs of a cylinder around the axis x = y = 100, written as tifxyz grids with their rows
and columns in each of the four directions (and transposed), so the right answer follows from
N = d/dcol x d/drow by hand: columns turning from +x toward +y with rows along +z give N = r_hat, outward.
"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import vc3d_orient  # noqa: E402

AXIS = [(0.0, 100.0, 100.0), (500.0, 100.0, 100.0)]   # umbilicus control points (z, y, x)


def arc(radius=50.0, deg0=0.0, ddeg=3.0, cols_back=False, rows_back=False, transpose=False, cx=100.0, cy=100.0):
    def point(r, c):
        if transpose:
            r, c = c, r
        t = math.radians(deg0 + ddeg * (-c if cols_back else c))
        return (cx + radius * math.cos(t), cy + radius * math.sin(t), 60.0 + 4.0 * (-r if rows_back else r))
    return point


def zfold(r, c):
    """A Z fold: forward around the axis at radius 50 (columns 0 to 11), back at 46 (12 to 19), forward at 42."""
    if c < 12:
        rad, t = 50.0, 3.0 * c
    elif c < 20:
        rad, t = 46.0, 33.0 - 3.0 * (c - 11)
    else:
        rad, t = 42.0, 9.0 + 3.0 * (c - 19)
    t = math.radians(t)
    return (100 + rad * math.cos(t), 100 + rad * math.sin(t), 60.0 + 4.0 * r)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def surface(self, point, rows=9, cols=12, name="s.tifxyz"):
        return fakes.write_tifxyz(self.d / name, point, rows=rows, cols=cols)


class TestVote(Base):
    def test_standard_arc_points_outward(self):
        res = vc3d_orient.orientation(self.surface(arc()), umbilicus=AXIS)
        self.assertEqual((res["centre"], res["normal"]["vote"], res["normal"]["outward_share"],
                          res["normal"]["confidence"]), ("umbilicus", "outward", 1.0, "clear"))
        self.assertEqual(res["team_order"], "--flip-normals")
        self.assertEqual((res["rows"]["run"], res["rows"]["along_z_share"], res["columns"]["turn"]), ("+z", 1.0, "positive"))
        self.assertEqual(res["layout"], "villa's standard orientation (rows along +z, +N outward)")
        self.assertEqual((res["folds"]["flipped_pairs"], res["disagreeing_tiles"]), (0, []))
        self.assertEqual(res["vertices"], 9 * 12)

    def test_the_four_layouts_and_a_transposed_grid(self):
        cases = [({"cols_back": True}, "inward", "+z", "negative", "standard mirrored left to right"),
                 ({"rows_back": True}, "inward", "-z", "positive", "standard mirrored top to bottom"),
                 ({"cols_back": True, "rows_back": True}, "outward", "-z", "negative", "standard turned 180 degrees")]
        for kw, vote, run, turn, layout in cases:
            with self.subTest(**kw):
                res = vc3d_orient.orientation(self.surface(arc(**kw), name=f"{sorted(kw)}.tifxyz"), umbilicus=AXIS)
                self.assertEqual((res["normal"]["vote"], res["rows"]["run"], res["columns"]["turn"]), (vote, run, turn))
                self.assertTrue(res["layout"].startswith(layout), res["layout"])
                self.assertEqual(res["team_order"], "--flip-normals" if vote == "outward" else
                                 "no flag (+N already points to the centre)")
        res = vc3d_orient.orientation(self.surface(arc(transpose=True), rows=12, cols=9, name="t.tifxyz"), umbilicus=AXIS)
        # rows now turn around the axis and columns run along +z: N = z x theta_hat = -r_hat
        self.assertEqual((res["normal"]["vote"], res["rows"]["run"]), ("inward", "across z"))
        self.assertTrue(res["layout"].startswith("rows do not run along z"))

    def test_a_far_centre_gives_no_clear_sign(self):
        ring = self.surface(arc(ddeg=360 / 40), rows=4, cols=40, name="ring.tifxyz")
        res = vc3d_orient.orientation(ring, centre_xy=[1000.0, 100.0])
        # seen from far along -x, the near half of the ring faces the centre and the far half faces away
        self.assertEqual((res["centre"], res["normal"]["confidence"], res["team_order"]), ("axis", "ambiguous", None))
        self.assertLess(abs(res["normal"]["outward_share"] - 0.5), 0.05)
        self.assertIn("split it into patches", res["advice"])

    def test_points_near_the_axis_and_normals_along_it_do_not_vote(self):
        flat = self.surface(fakes.plane(60.0, x0=60.0, step=6.0), name="flat.tifxyz")   # N along +z, across the axis
        res = vc3d_orient.orientation(flat, umbilicus=AXIS)
        self.assertEqual((res["normal"]["vote"], res["normal"]["confidence"], res["team_order"]), (None, "ambiguous", None))
        self.assertGreater(res["normal"]["near_axis"], 0)
        self.assertGreater(res["normal"]["along_axis"], 0)

    def test_fitted_centre(self):
        res = vc3d_orient.orientation(self.surface(arc(ddeg=10.0), cols=12))
        fit = res["fit"]
        self.assertEqual((fit["centre_xy"], fit["radius"], fit["reliable"]), ([100.0, 100.0], 50.0, True))
        self.assertEqual(fit["arc_degrees"], 110.0)
        self.assertEqual((res["centre"], res["normal"]["vote"]), ("fitted circle (an estimate)", "outward"))
        small = vc3d_orient.orientation(self.surface(arc(ddeg=0.5), name="small.tifxyz"))
        self.assertFalse(small["fit"]["reliable"])
        self.assertIn("unreliable", small["centre"])

    def test_a_fold_back_is_outvoted_and_mapped(self):
        surf = self.surface(zfold, rows=8, cols=32, name="z.tifxyz")
        res = vc3d_orient.orientation(surf, umbilicus=AXIS, tiles=8)
        n = res["normal"]
        # by area the forward arms (radius 50 and 42, 12 columns each) outweigh the fold back (46, 8 columns): 3 to 1
        self.assertEqual((n["vote"], n["confidence"]), ("outward", "weak"))
        self.assertAlmostEqual(n["outward_share"], 0.75, delta=0.03)
        self.assertGreaterEqual(res["folds"]["flipped_pairs"], 8)
        # the fold back is columns 12 to 19: exactly the tiles of 4 columns that vote inward, in every row
        tiles = res["disagreeing_tiles"]
        self.assertEqual((len(tiles), sorted({tuple(t["cols"]) for t in tiles})), (16, [(12, 15), (16, 19)]))
        self.assertIn("faces the other way", res["advice"])
        # coarser tiles average the fold with its neighbours: columns 8 to 15 hold 4 of its columns and the
        # sharper turn, and lean inward; 16 to 23 lean outward
        coarse = vc3d_orient.orientation(surf, umbilicus=AXIS, tiles=4)["disagreeing_tiles"]
        self.assertEqual([t["cols"] for t in coarse], [[8, 15]] * 4)

    def test_a_grid_box_votes_on_one_patch(self):
        surf = self.surface(zfold, rows=8, cols=32, name="z.tifxyz")
        back = vc3d_orient.orientation(surf, umbilicus=AXIS, grid_box=[0, 8, 13, 19])
        self.assertEqual((back["grid_box"], back["normal"]["vote"], back["normal"]["confidence"],
                          back["normal"]["outward_share"], back["vertices"]), ([0, 8, 13, 19], "inward", "clear", 0.0, 48))
        front = vc3d_orient.orientation(surf, umbilicus=AXIS, grid_box=[0, 99, 0, 11])   # clipped to the grid
        self.assertEqual((front["grid_box"], front["normal"]["vote"], front["normal"]["outward_share"]),
                         ([0, 8, 0, 11], "outward", 1.0))
        # 8 forward and 8 fold-back columns: no clear sign; tiles are cut inside the box and reported in the
        # whole grid's columns (12 to 19 are the fold back)
        mixed = vc3d_orient.orientation(surf, umbilicus=AXIS, grid_box=[0, 8, 4, 20], tiles=4)
        self.assertEqual(mixed["normal"]["confidence"], "ambiguous")
        self.assertEqual(sorted({tuple(t["cols"]) for t in mixed["disagreeing_tiles"]}), [(12, 15), (16, 19)])
        with self.assertRaises(vc3d_orient.OrientError):
            vc3d_orient.orientation(surf, umbilicus=AXIS, grid_box=[0, 8, 40, 50])

    def test_scale_segmentation_and_affine(self):
        surf = self.surface(arc(radius=25.0, cx=50.0, cy=50.0))
        res = vc3d_orient.orientation(surf, umbilicus=AXIS, scale_segmentation=2.0)
        self.assertEqual((res["normal"]["vote"], res["normal"]["outward_share"]), ("outward", 1.0))
        turn = [[-1, 0, 0, 300], [0, -1, 0, 300], [0, 0, 1, 0]]   # 180 degrees about z: still outward around (200, 200)
        res = vc3d_orient.orientation(self.surface(arc(), name="r.tifxyz"), centre_xy=[200, 200], affine=turn)
        self.assertEqual(res["normal"]["vote"], "outward")
        mirror = [[-1, 0, 0, 300], [0, 1, 0, 0], [0, 0, 1, 0]]   # a mirror flips the handedness, so +N turns inward
        res = vc3d_orient.orientation(self.surface(arc(), name="m.tifxyz"), centre_xy=[200, 100], affine=mirror)
        self.assertEqual(res["normal"]["vote"], "inward")
        with self.assertRaises(vc3d_orient.OrientError):
            vc3d_orient.orientation(surf, umbilicus=AXIS, affine=[[1, 0, 0]])


class TestUmbilicus(Base):
    def test_villa_formats(self):
        want = [(10.0, 20.0, 30.0), (50.0, 60.0, 70.0)]
        forms = ["# z, y, x\n50, 60, 70\n\n10, 20, 30\n",
                 json.dumps([[50, 60, 70], [10, 20, 30]]),
                 json.dumps([{"x": 70, "y": 60, "z": 50}, {"x": 30, "y": 20, "z": 10}]),
                 json.dumps({"control_points": [{"x": 30, "y": 20, "z": 10, "score": 100}, {"x": 70, "y": 60, "z": 50}],
                             "metadata": {"annotated_level": 2}}),
                 json.dumps({"points": [[10, 20, 30], [50, 60, 70]]})]
        for i, text in enumerate(forms):
            with self.subTest(form=i):
                f = self.d / f"u{i}.{'txt' if i == 0 else 'json'}"
                f.write_text(text)
                self.assertEqual(vc3d_orient.load_umbilicus(f), want)
        self.assertEqual(vc3d_orient.load_umbilicus(self.d / "u1.json", scale=4), [(40.0, 80.0, 120.0), (200.0, 240.0, 280.0)])
        for bad in ("1, 2\n", "[]", '{"other": []}', '[{"x": 1}]', "[7]"):
            with self.subTest(bad=bad), self.assertRaises((vc3d_orient.OrientError, ValueError)):
                vc3d_orient.parse_umbilicus(bad)

    def test_centre_is_linear_in_z_and_held_past_the_ends(self):
        pts = [(10.0, 20.0, 30.0), (50.0, 60.0, 70.0)]
        self.assertEqual(vc3d_orient.centre_at(pts, 30.0), (50.0, 40.0))
        self.assertEqual(vc3d_orient.centre_at(pts, 0.0), (30.0, 20.0))
        self.assertEqual(vc3d_orient.centre_at(pts, 99.0), (70.0, 60.0))
        self.assertEqual(vc3d_orient.centre_at([(5.0, 1.0, 2.0)], 40.0), (2.0, 1.0))

    def test_circle_fit(self):
        xs = [3 + 2 * math.cos(math.radians(a)) for a in range(0, 90, 10)]
        ys = [-1 + 2 * math.sin(math.radians(a)) for a in range(0, 90, 10)]
        cx, cy, r, rms, span = vc3d_orient.fit_circle(xs, ys)
        self.assertEqual((round(cx, 6), round(cy, 6), round(r, 6), round(rms, 9), round(span, 6)), (3.0, -1.0, 2.0, 0.0, 80.0))
        with self.assertRaises(vc3d_orient.OrientError):
            vc3d_orient.fit_circle([0, 1, 2], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
