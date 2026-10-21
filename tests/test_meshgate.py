import unittest

from kit.meshgate import MeshGateError, mesh_verdict


class MeshVerdictTest(unittest.TestCase):
    def test_shared_edge_passes(self):
        tris = [((0, 0), (2, 0), (0, 2)), ((2, 0), (2, 2), (0, 2))]
        got = mesh_verdict(tris)
        self.assertTrue(got["pass"])
        self.assertEqual(got["components"], 1)
        self.assertEqual(got["nonmanifold"], 0)
        self.assertEqual(got["same_dir"], 0)
        self.assertEqual(got["cw"], 0)

    def test_disjoint_fails(self):
        tris = [((0, 0), (1, 0), (0, 1)), ((3, 0), (4, 0), (3, 1))]
        got = mesh_verdict(tris)
        self.assertFalse(got["pass"])
        self.assertEqual(got["components"], 2)

    def test_three_on_one_edge_fails(self):
        tris = [
            ((0, 0), (1, 0), (0, 1)),
            ((0, 0), (1, 0), (0, -1)),
            ((0, 0), (1, 0), (1, 1)),
        ]
        got = mesh_verdict(tris)
        self.assertFalse(got["pass"])
        self.assertGreaterEqual(got["nonmanifold"], 1)

    def test_clockwise_fails(self):
        got = mesh_verdict([((0, 0), (0, 1), (1, 0))])
        self.assertFalse(got["pass"])
        self.assertEqual(got["cw"], 1)

    def test_duplicate_face_fails(self):
        tri = ((0, 0), (1, 0), (0, 1))
        got = mesh_verdict([tri, tri])
        self.assertFalse(got["pass"])
        self.assertGreaterEqual(got["same_dir"], 1)

    def test_empty_and_degenerate_fail(self):
        self.assertFalse(mesh_verdict([])["pass"])
        got = mesh_verdict([((0, 0), (1, 0), (2, 0))])
        self.assertFalse(got["pass"])
        self.assertEqual(got["degenerate"], 1)

    def test_bad_shape_raises(self):
        with self.assertRaises(MeshGateError):
            mesh_verdict([((0, 0), (1, 0))])


if __name__ == "__main__":
    unittest.main()
