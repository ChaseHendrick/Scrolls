"""The support modules kit snap, kit labelsnap and kit finesnap read through: a local OME-Zarr read by
kit.vc3d_region, nearest-voxel samples by kit.vc3d_prep, an umbilicus by kit.vc3d_orient, and the 3 x 4 matrices of
kit.vc3d_landmarks. Synthetic data only; each check can fail."""

import json
import tempfile
import unittest
from pathlib import Path

from kit import vc3d_landmarks as L
from kit import vc3d_orient as O

try:
    import numpy as np
except ImportError:          # the numpy parts skip; the matrix and umbilicus parts are standard library
    np = None

if np is not None:
    from kit import vc3d_prep, vc3d_region
    from tests.test_snap import write_zarr


class MatrixTest(unittest.TestCase):
    def test_invert_undoes_an_affine_and_compose_chains_two(self):
        m = L.as_matrix([[0.5, 0, 0, 10], [0, 2, 0, -4], [0, 0.1, 1, 3]])
        inv = L.invert(m)
        p = (7.0, -3.0, 11.0)
        back = L.apply(inv, L.apply(m, p))
        for a, b in zip(back, p):
            self.assertAlmostEqual(a, b, places=9)
        ident = L.compose(inv, m)
        for i in range(3):
            for j in range(4):
                self.assertAlmostEqual(ident[i][j], 1.0 if i == j else 0.0, places=9)

    def test_a_bad_or_singular_matrix_is_refused(self):
        with self.assertRaises(L.LandmarkError):
            L.as_matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        with self.assertRaises(L.LandmarkError):
            L.invert([[1, 0, 0, 0], [2, 0, 0, 0], [0, 0, 1, 0]])


class UmbilicusTest(unittest.TestCase):
    def test_json_and_villa_text_give_the_same_sorted_points_and_scale_applies(self):
        a = O.parse_umbilicus(json.dumps([{"x": 5, "y": 6, "z": 20}, {"x": 1, "y": 2, "z": 10}]))
        b = O.parse_umbilicus("# z, y, x\n20, 6, 5\n10, 2, 1\n")
        self.assertEqual(a, [(10.0, 2.0, 1.0), (20.0, 6.0, 5.0)])
        self.assertEqual(a, b)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "umb.json"
            f.write_text(json.dumps({"control_points": [[10, 2, 1], [20, 6, 5]]}))
            self.assertEqual(O.load_umbilicus(f, scale=2.0), [(20.0, 4.0, 2.0), (40.0, 12.0, 10.0)])

    def test_centre_is_linear_between_points_and_constant_past_the_ends(self):
        pts = [(10.0, 2.0, 1.0), (20.0, 6.0, 5.0)]
        self.assertEqual(O.centre_at(pts, 15.0), (3.0, 4.0))
        self.assertEqual(O.centre_at(pts, 0.0), (1.0, 2.0))
        self.assertEqual(O.centre_at(pts, 99.0), (5.0, 6.0))

    def test_a_malformed_umbilicus_is_refused(self):
        with self.assertRaises(O.OrientError):
            O.parse_umbilicus("10, 2\n")
        with self.assertRaises(O.OrientError):
            O.parse_umbilicus("[]")


@unittest.skipIf(np is None, "needs numpy")
class VolumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vol = (np.arange(32 * 32 * 32) % 251).astype(np.uint8).reshape(32, 32, 32)
        write_zarr(Path(self.tmp.name) / "v.zarr", self.vol, levels=2)
        self.v = vc3d_region.Volume(str(Path(self.tmp.name) / "v.zarr"))

    def test_a_box_read_matches_the_array_and_level_1_is_half_size(self):
        self.assertEqual(self.v.shape(0), [32, 32, 32])
        self.assertEqual(self.v.shape(1), [16, 16, 16])
        box = self.v.read(0, ((3, 19), (5, 21), (7, 30)))
        self.assertTrue(np.array_equal(box, self.vol[3:19, 5:21, 7:30]))

    def test_nearest_samples_are_the_voxels_at_xyz_and_zero_outside(self):
        xyz = np.array([[1.2, 2.0, 3.0], [30.0, 0.0, 17.0], [40.0, 1.0, 1.0], [-2.0, 0.0, 0.0]])
        got = vc3d_prep.sample_nearest(self.v, 0, xyz)
        want = [self.vol[3, 2, 1], self.vol[17, 0, 30], 0, 0]
        self.assertEqual(got.tolist(), [int(w) for w in want])


if __name__ == "__main__":
    unittest.main()
