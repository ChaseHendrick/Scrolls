"""kit snap: technique D, the band-face snap (snap_face), on synthetic bands in small zarr arrays.

The fixtures and helpers are tests/test_snap.py's. Numerical tests skip without numpy.
"""

import tempfile
import unittest
from pathlib import Path

from kit import snap

try:
    import numpy as np
except ImportError:  # the core kit is standard library only
    np = None

if np is not None:
    from tests.test_snap import plane_mesh, write_zarr


def band(shape, ranges, value=200, background=20):
    v = np.full(shape, background, np.uint8)
    for lo, hi in ranges:
        v[lo:hi + 1] = value
    return v


@unittest.skipIf(np is None, "needs numpy")
class FaceSnapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.axis = ("line", (20.0, 20.0, -400.0), (1.0, 0.0, 0.0))   # far below: outward and the normal are +z

    def tearDown(self):
        self.tmp.cleanup()

    def sampler(self, vol, name):
        return snap.Sampler(snap.open_volume(write_zarr(self.root / name, vol)))

    def mesh(self, z, H=9, W=9):
        xs, ys, zs = plane_mesh(H, W, z, step=1.0, x0=16.0, y0=16.0)
        return xs, ys, zs, np.ones(xs.shape, bool)

    def test_faces_and_midline_of_one_band(self):
        sm = self.sampler(band((48, 40, 40), [(20, 25)]), "one.zarr")     # faces at 19.5 and 25.5 (trilinear)
        for z0 in (21.0, 18.0, 24.7):
            for target, want in (("recto", 19.5), ("mid", 22.5), ("verso", 25.5)):
                xs, ys, zs, valid = self.mesh(z0)
                r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts={"target": target})
                self.assertTrue(r["apply"].all(), (z0, target))
                self.assertLess(float(np.abs(r["zs"] - want).max()), 0.05, (z0, target))

    def test_recto_sign_without_an_axis(self):
        sm = self.sampler(band((48, 40, 40), [(20, 25)]), "one.zarr")
        xs, ys, zs, valid = self.mesh(22.0)
        up = snap.snap_face(xs, ys, zs, valid, sm, recto_sign=1)
        down = snap.snap_face(xs, ys, zs, valid, sm, recto_sign=-1)
        self.assertLess(abs(float(up["zs"].mean()) - 19.5), 0.05)
        self.assertLess(abs(float(down["zs"].mean()) - 25.5), 0.05)
        none = snap.snap_face(xs, ys, zs, valid, sm)              # no axis and no sign: the recto side is unknown
        self.assertFalse(none["apply"].any())
        self.assertEqual(none["report"]["abstained"]["side not named"], 81)
        mid = snap.snap_face(xs, ys, zs, valid, sm, opts={"target": "mid"})
        self.assertLess(abs(float(mid["zs"].mean()) - 22.5), 0.05)

    def test_global_level_matches_on_a_clean_band(self):
        sm = self.sampler(band((48, 40, 40), [(20, 25)]), "one.zarr")
        xs, ys, zs, valid = self.mesh(23.0)
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts={"level": 110.0})
        self.assertLess(float(np.abs(r["zs"] - 19.5).max()), 0.05)
        for lv, want in ((50.0, 18.936), (170.0, 20.064)):       # the face moves with the level
            r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts={"level": lv})
            self.assertLess(float(np.abs(r["zs"] - want).max()), 0.05, lv)

    def test_two_bands_about_as_near_abstain(self):
        sm = self.sampler(band((48, 40, 40), [(10, 14), (20, 24)]), "two.zarr")   # faces 14.5 and 19.5
        xs, ys, zs, valid = self.mesh(17.2)                     # 2.7 and 2.3 voxels away: ambiguous
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis)
        self.assertFalse(r["apply"].any())
        np.testing.assert_array_equal(r["zs"], zs)
        self.assertEqual(r["report"]["abstained"]["ambiguous or off the profile"], 81)
        xs, ys, zs, valid = self.mesh(18.8)                     # 4.3 and 0.7 away: the upper band, recto 19.5
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis)
        self.assertLess(float(np.abs(r["zs"] - 19.5).max()), 0.05)

    def test_far_band_and_bad_target(self):
        sm = self.sampler(band((48, 40, 40), [(30, 35)]), "far.zarr")
        xs, ys, zs, valid = self.mesh(22.0)                     # 7.5 voxels from the band: past max_move 4
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts={"half": 16.0})
        self.assertFalse(r["apply"].any())
        self.assertEqual(r["report"]["abstained"]["too far"], 81)
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts={"half": 16.0, "max_move": 8.0})
        self.assertLess(float(np.abs(r["zs"] - 29.5).max()), 0.05)
        with self.assertRaises(snap.SnapError):
            snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts={"target": "edge"})

    def test_lone_hop_is_rejected_and_a_hole_is_filled(self):
        v = band((48, 40, 40), [(20, 25)])
        v[:, 20, 20] = 20
        v[23:29, 20, 20] = 200      # the center column's band is 3 voxels higher: a lone hop, rejected by jump 2
        v[:, 18, 18] = 20           # a column with no band: abstains, then filled from its neighbors
        xs, ys, zs, valid = self.mesh(21.0)
        r = snap.snap_face(xs, ys, zs, valid, self.sampler(v, "hop.zarr"), axis=self.axis)
        self.assertTrue(r["apply"].all())
        self.assertLess(float(np.abs(r["zs"] - 19.5).max()), 0.05)

    def test_per_vertex_form_follows_a_real_step_the_defaults_reject(self):
        v = band((48, 40, 40), [(20, 25)])
        v[:, 20, 20] = 20
        v[23:29, 20, 20] = 200      # one column's band is truly 3 voxels higher
        xs, ys, zs, valid = self.mesh(21.0)
        sm = self.sampler(v, "step.zarr")
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts=dict(snap.FACE_SNAP_PER_VERTEX))
        self.assertTrue(r["apply"].all())
        self.assertLess(abs(float(r["zs"][4, 4]) - 22.5), 0.05)    # the stepped vertex sits on its own recto face
        rest = np.ones(xs.shape, bool)
        rest[4, 4] = False
        self.assertLess(float(np.abs(r["zs"][rest] - 19.5).max()), 0.05)
        d = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis)
        self.assertLess(abs(float(d["zs"][4, 4]) - 19.5), 0.05)    # the defaults treat it as a lone hop

    def test_one_measured_vertex_does_not_drag_abstaining_neighbours(self):
        sm = self.sampler(band((48, 40, 40), [(10, 14), (20, 24)]), "two.zarr")
        xs, ys, zs = plane_mesh(11, 11, 17.0, step=1.0, x0=14.0, y0=14.0)
        zs = zs.copy()
        zs[5, 5] = 16.0                                         # only this vertex sees one band clearly
        valid = np.ones(xs.shape, bool)
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis)
        self.assertFalse(r["apply"].any())
        np.testing.assert_array_equal(r["zs"], zs)

    def test_noise_without_a_sheet_does_not_move_a_mesh_beside_papyrus(self):
        rng = np.random.default_rng(3)
        v = np.clip(np.rint(rng.normal(20, 3, (48, 40, 40))), 0, 255).astype(np.uint8)
        v[30:36] = 200                                          # papyrus far from the mesh sets the window
        xs, ys, zs, valid = self.mesh(12.0)                     # in noise, 17.5 voxels below the band
        r = snap.snap_face(xs, ys, zs, valid, self.sampler(v, "noise.zarr"), axis=self.axis,
                           opts={"min_contrast": 60.0})
        self.assertFalse(r["apply"].any())
        self.assertEqual(r["report"]["abstained"]["low contrast"], 81)

    def test_tangent_normal_abstains_for_a_face_target(self):
        sm = self.sampler(band((48, 40, 40), [(20, 25)]), "one.zarr")
        xs, ys, zs, valid = self.mesh(21.0)
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=("line", (20.0, 20.0, 0.0), (0.0, 0.0, 1.0)))
        self.assertFalse(r["apply"].any())
        self.assertEqual(r["report"]["abstained"]["side not named"], 81)

    def test_smoothing_keeps_a_flat_answer(self):
        sm = self.sampler(band((48, 40, 40), [(20, 25)]), "one.zarr")
        xs, ys, zs, valid = self.mesh(22.0)
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts={"sigma": 1.0})
        self.assertLess(float(np.abs(r["zs"] - 19.5).max()), 0.05)

    def test_invalid_vertices_stay(self):
        sm = self.sampler(band((48, 40, 40), [(20, 25)]), "one.zarr")
        xs, ys, zs, valid = self.mesh(21.0)
        valid[4, 4] = False
        xs[4, 4] = ys[4, 4] = zs[4, 4] = -1.0
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis)
        self.assertFalse(r["apply"][4, 4])
        self.assertEqual(float(r["zs"][4, 4]), -1.0)
        self.assertLess(float(np.abs(r["zs"][valid] - 19.5).max()), 0.05)


GAPS = (4.0, 2.0, 1.0, 0.5, 0.0)     # gap between the target sheet and its neighbor on the recto side, voxels
LADDER_W = 16                        # grid columns per gap


def ladder_volume(psf=1.0, noise=0.0, seed=0):
    """Three 6-voxel sheets along z, blurred: the target [28, 34), a neighbor on its recto side (below, toward the
    axis) whose gap to the target steps through GAPS across x (LADDER_W voxels each, from x = 4), and one above at a
    gap of 4. Rendered at 8 sub-samples per voxel in z, so a fractional gap is a partial-volume dip."""
    nx = LADDER_W * len(GAPS) + 8
    Z, Y, ss = 64, 24, 8
    v = np.zeros((Z, Y, nx))
    for k in range(ss):
        zc = np.arange(Z) + (k + 0.5) / ss
        val = np.full((Z, Y, nx), 20.0)
        for j in range(nx):
            g = GAPS[min(len(GAPS) - 1, max(0, (j - 4) // LADDER_W))]
            for lo, hi in ((28 - g - 6, 28 - g), (28, 34), (38, 44)):
                val[(zc >= lo) & (zc < hi), :, j] = 200.0
        v += val / ss
    if psf > 0:
        v = snap.gaussian_filter(v, psf)
    if noise > 0:
        v = v + np.random.default_rng(seed).normal(0, noise, v.shape)
    return np.clip(np.rint(v), 0, 255).astype(np.uint8)


@unittest.skipIf(np is None, "needs numpy")
class GapLadderTest(unittest.TestCase):
    """The synthetic gap ladder (20 October 2026): a grid inside the target sheet, 0.4 of its thickness from the recto
    face (z 30.4, recto face 27.5 after the trilinear half step), with the recto-side neighbor at gaps of 4, 2, 1,
    0.5 and 0 voxels. Interior columns of each step are scored (3 columns from each edge, past the 5 x 5 fill)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.axis = ("line", (20.0, 12.0, -400.0), (1.0, 0.0, 0.0))

    def tearDown(self):
        self.tmp.cleanup()

    def snap_ladder(self, opts, psf=1.0, noise=0.0):
        sm = snap.Sampler(snap.open_volume(write_zarr(self.root / f"l{psf}{noise}.zarr", ladder_volume(psf, noise))))
        xs, ys, zs = plane_mesh(9, LADDER_W * len(GAPS), 30.4, step=1.0, x0=4.0, y0=8.0)
        valid = np.ones(xs.shape, bool)
        r = snap.snap_face(xs, ys, zs, valid, sm, axis=self.axis, opts=opts, face_opts={"sigma": 1.0})
        out = {}
        for b, g in enumerate(GAPS):
            cols = slice(b * LADDER_W + 3, b * LADDER_W + LADDER_W - 3)
            out[g] = (r["zs"][:, cols], r["apply"][:, cols])
        return out, r

    def test_merged_rule_snaps_from_two_voxels_and_abstains_under_one(self):
        for noise in (0.0, 10.0):
            out, r = self.snap_ladder(dict(snap.FACE_SNAP_PER_VERTEX_MERGED), noise=noise)
            for g in (4.0, 2.0):
                z, app = out[g]
                self.assertTrue(app.all(), (noise, g))
                self.assertLess(float(np.abs(z - 27.5).max()), 0.75, (noise, g))
            for g in (0.5, 0.0):                         # under a 1 voxel gap: the band is two sheets, so stay put
                z, app = out[g]
                self.assertFalse(app.any(), (noise, g))
                np.testing.assert_allclose(z, 30.4, atol=1e-5)
            self.assertGreater(r["report"]["abstained"]["too thick"], 0)
            self.assertLess(abs(r["report"]["ref_band_thick"] - 5.5), 0.6)

    def test_plain_per_vertex_form_lands_on_the_wrong_sheet_under_one_voxel(self):
        out, r = self.snap_ladder(dict(snap.FACE_SNAP_PER_VERTEX))
        self.assertEqual(r["report"]["abstained"]["too thick"], 0)
        for g in (0.5, 0.0):
            z, app = out[g]
            self.assertTrue(app.all())
            self.assertGreater(float(np.median(np.abs(z - 27.5))), 4.0, g)   # the merged band's recto: the neighbor

    def test_absolute_cap_and_too_few_bands(self):
        out, r = self.snap_ladder({"jump": 1e9, "min_support": 1, "max_thick": 9.0})
        self.assertFalse(out[0.0][1].any())
        self.assertTrue(out[4.0][1].all())
        out, r = self.snap_ladder({"jump": 1e9, "min_support": 1, "max_thick_ratio": 1.8, "thick_min_bands": 10 ** 6})
        self.assertIsNone(r["report"]["thick_cap"])         # the ratio rule is off without enough bands
        self.assertTrue(out[0.0][1].all())


if __name__ == "__main__":
    unittest.main()
