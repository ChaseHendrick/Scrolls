"""Geometry-only certificates, with adversarial holes, folds and search order."""
import unittest

try:
    import numpy as np
    import scipy
except ImportError:
    np = None

from kit._surface_geometry import bilinear, closest_quad, project, quad_mask, sample_geometry


@unittest.skipIf(np is None, "numpy and scipy required")
class SurfaceGeometryTests(unittest.TestCase):
    def test_batched_children_preserve_scalar_bounds_and_seed_ties(self):
        from kit._surface_geometry import _cell_bounds, _child_bounds
        rng = np.random.default_rng(911074)
        boxes = ((0., .5, 0., .5), (0., .5, .5, 1.),
                 (.5, 1., 0., .5), (.5, 1., .5, 1.))
        plane = np.array([[0., 0., 0.], [20., 0., 0.],
                          [0., 20., 0.], [20., 20., 0.]])
        cases = [(plane, np.array([10., 10., 1.])),
                 (np.zeros((4, 3)), np.ones(3))]
        cases += [(rng.normal(size=(4, 3)) * scale + shift,
                   rng.normal(size=3) * scale + shift)
                  for scale, shift in ((.01, 0.), (30., 100.), (1000., 1e7))
                  for _ in range(8)]
        for corners, point in cases:
            batched = _child_bounds(point, corners, boxes)
            for box, actual in zip(boxes, batched):
                expected = _cell_bounds(point, corners, box)
                self.assertEqual(actual[:2], expected[:2])
                np.testing.assert_array_equal(actual[2], expected[2])

    def mesh(self, xyz, valid=None):
        xyz = np.asarray(xyz, dtype=float)
        return {"xyz": xyz, "valid": np.ones(xyz.shape[:2], bool) if valid is None else valid}

    def point(self, xyz):
        return self.mesh(np.asarray(xyz, dtype=float).reshape(1, 1, 3))

    def plane(self, n=8, spacing=20):
        r, c = np.indices((n, n))
        return np.stack([100 + r * spacing, 100 + c * spacing, r * 0 + 50], -1).astype(float)

    def test_half_grid_plane_projection_removes_tangential_quantization(self):
        source = self.mesh(self.plane())
        reference = self.mesh(self.plane() + [10, 10, 1])
        result = project(source, reference, 5, .001)
        self.assertTrue(result["valid"][3, 4])
        self.assertAlmostEqual(result["distance"][3, 4], 1)
        np.testing.assert_allclose(result["uv"][3, 4], [2.5, 3.5], atol=1e-10)
        native_gap = np.linalg.norm(np.array([10., 10., 1.]))
        self.assertGreater(native_gap, 5)
        position, covered = sample_geometry(reference, result["uv"])
        np.testing.assert_allclose(position[3, 4], source["xyz"][3, 4] + [0, 0, 1])
        self.assertTrue(covered[3, 4])

    def test_actual_physical_bound_is_never_expanded_by_tolerance(self):
        reference = self.mesh(self.plane())
        for gap, expected in ((5, True), (5.0001, False)):
            result = project(self.point([125, 125, 50 + gap]), reference, 5, .01)
            self.assertEqual(bool(result["valid"][0, 0]), expected)

    def test_holes_and_folded_quad_do_not_supply_correspondences(self):
        xyz = self.plane(2)
        valid = np.ones((2, 2), bool)
        valid[1, 1] = False
        reference = self.mesh(xyz, valid)
        self.assertFalse(quad_mask(reference).any())
        self.assertFalse(project(self.point([110, 110, 50]), reference, 5, .001)["valid"].any())
        xyz[1, 1] = [90, 110, 50]
        reference = self.mesh(xyz)
        self.assertFalse(quad_mask(reference).any())
        _, covered = sample_geometry(reference, np.array([[[.5, .5]]]))
        self.assertFalse(covered.any())

    def test_bilinear_saddle_distance_bracket_contains_dense_search(self):
        corners = np.array([[100, 100, 50], [120, 100, 50], [100, 120, 50], [120, 120, 62]], float)
        point = np.array([109, 110, 49.])
        result = closest_quad(point, corners, .002)
        self.assertTrue(result["converged"])
        self.assertLessEqual(result["upper"] - result["lower"], .002 + 1e-10)
        uv = np.stack(np.meshgrid(np.linspace(0, 1, 401), np.linspace(0, 1, 401)), -1)
        dense = np.linalg.norm(bilinear(corners, uv) - point, axis=-1).min()
        self.assertLessEqual(result["lower"], dense + 1e-10)
        self.assertLessEqual(result["upper"], dense + .002)
        self.assertAlmostEqual(result["upper"], np.linalg.norm(bilinear(corners, result["uv"]) - point))

    def test_budget_exhaustion_is_explicit_and_not_a_certificate(self):
        corners = np.array([[0, 0, 0], [20, 0, 0], [0, 20, 0], [20, 20, 12]], float)
        result = closest_quad(np.array([9, 10, -1.]), corners, 1e-8, budget=1)
        self.assertFalse(result["converged"])
        self.assertGreater(result["upper"] - result["lower"], 1e-8)

    def test_shared_quad_edge_has_one_stable_uv(self):
        reference = self.mesh(self.plane(3))
        first = project(self.point([120, 110, 51]), reference, 5, .001)
        second = project(self.point([120, 110, 51]), reference, 5, .001)
        self.assertTrue(first["valid"].all())
        np.testing.assert_array_equal(first["uv"], second["uv"])
        np.testing.assert_allclose(first["uv"][0, 0], [1, .5])

    def test_unique_near_edge_plane_match_is_not_a_tolerance_tie(self):
        reference = self.mesh(self.plane(3))
        for column in (.999, .9999):
            result = project(self.point([106, 100 + column * 20, 53]), reference, 5, .001)
            self.assertTrue(result["valid"].all())
            self.assertFalse(result["ambiguous"].any())
            np.testing.assert_allclose(result["uv"][0, 0], [.3, column], atol=1e-10)

    def test_remote_uv_tie_is_ambiguous_even_in_one_mesh(self):
        xyz = self.plane(6)
        valid = np.zeros((6, 6), bool)
        valid[:2, :2] = valid[4:, 4:] = True
        xyz[4:, 4:] = xyz[:2, :2]
        result = project(self.point([110, 110, 51]), self.mesh(xyz, valid), 5, .001)
        self.assertTrue(result["ambiguous"].all())
        self.assertFalse(result["valid"].any())

    def test_unresolved_remote_rival_inside_radius_prevents_acceptance(self):
        from unittest.mock import patch
        from kit import _surface_geometry
        xyz = self.plane(6)
        valid = np.zeros((6, 6), bool)
        valid[:2, :2] = valid[4:, 4:] = True
        xyz[4:, 4:] = xyz[:2, :2] + [0, 0, 4]
        original = _surface_geometry.closest_quad
        def unresolved_remote(point, corners, tolerance):
            if corners[:, 2].min() == 54:
                return {"lower": 3., "upper": 3.1, "uv": np.array([.5, .5]), "converged": False}
            return original(point, corners, tolerance)
        with patch.object(_surface_geometry, "closest_quad", side_effect=unresolved_remote):
            result = project(self.point([110, 110, 51]), self.mesh(xyz, valid), 5, .001)
        self.assertTrue(result["unresolved"].all())
        self.assertFalse(result["valid"].any())

    def test_one_unfolded_saddle_with_two_nearest_uvs_abstains(self):
        from kit._surface_geometry import _unique_minimum
        xyz = np.array([[[99, 99, 102], [99, 101, 98]],
                        [[101, 99, 98], [101, 101, 102]]], float)
        reference = self.mesh(xyz)
        point = np.array([100, 100, 101.])
        self.assertTrue(quad_mask(reference).all())
        corners = xyz[[0, 1, 0, 1], [0, 0, 1, 1]]
        self.assertFalse(_unique_minimum(point, corners))
        distances = np.linalg.norm(bilinear(corners, np.array([[.25, .25], [.75, .75]])) - point, axis=-1)
        np.testing.assert_allclose(distances, np.sqrt(.75))
        result = project(self.point(point), reference, 2, .001)
        self.assertTrue(result["unresolved"].all())
        self.assertFalse(result["valid"].any())

    def test_complete_radius_search_finds_large_quad_with_far_centroid(self):
        # Nearby small quads have closer centers, but a large, distant-centered
        # quad contains the true nearest point. Fixed nearest-center counts fail.
        xyz = self.plane(20)
        valid = np.ones((20, 20), bool)
        xyz[:2, :2] = np.array([[[100, 100, 50], [100, 1100, 50]],
                                [[1100, 100, 50], [1100, 1100, 50]]])
        valid[2, :2] = valid[:2, 2] = False
        xyz[3:, 3:, 2] += 4
        result = project(self.point([110, 110, 51]), self.mesh(xyz, valid), 2, .001)
        self.assertTrue(result["valid"].all())
        self.assertAlmostEqual(result["distance"][0, 0], 1)
        np.testing.assert_allclose(result["uv"][0, 0], [.01, .01])


if __name__ == "__main__":
    unittest.main()
