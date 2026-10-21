"""Exact-reference parity for the optional UV overlap broad phase.

All data are tiny synthetic geometry. Fixtures include every distinct triangle
configuration in test_uvgate, test_meshgate and test_uvgate_cli. Timing belongs
in the separate benchmark, not in these correctness tests.
"""

from fractions import Fraction
import json
import math
import random
import sys
import unittest
from unittest.mock import patch

from kit.uvgate import UvGateError, load_uv_csv, uv_overlap_gate

try:
    import numpy as np
except ImportError:
    np = None


_UNIT = ((0, 0), (1, 0), (0, 1))
_SQUARE = [_UNIT, ((1, 0), (1, 1), (0, 1))]
_BOX = [((0, 0), (2, 0), (0, 2)), ((2, 0), (2, 2), (0, 2))]
_CONTAINED = [((0, 0), (4, 0), (0, 4)), ((1, 1), (2, 1), (1, 2))]
_DEGENERATE = ((0, 0), (1, 0), (2, 0))
_DISJOINT = [_UNIT, ((3, 0), (4, 0), (3, 1))]
_LEGACY_KEYS = {"pass", "pairs", "degenerate", "witness", "rule"}
_METHODS = ("reference", "grid", "auto") if np is not None else ("reference", "auto")


def _existing_fixtures():
    # test_uvgate.py: overlap, coverage and sheet-verdict geometries.
    yield "contained", _CONTAINED
    yield "shared_edge_unit", _SQUARE
    yield "inner_third", _SQUARE + [((0.2, 0.2), (0.8, 0.2), (0.2, 0.8))]
    yield "degenerate", [_DEGENERATE]
    yield "crossing", [((0, 0), (2, 0), (1, 2)), ((0, 1), (2, 1), (1, -1))]
    yield "coverage_box", _BOX
    yield "published_short_sheet", [((0, 0), (1, 0), (0, 0.948))]
    yield "clean_plus_overlap", _BOX + [((0.2, 0.2), (1.2, 0.2), (0.2, 1.2))]
    yield "zero_source_area_input", [_UNIT]
    # test_meshgate.py: connectivity, winding, multiplicity and empty input.
    yield "disjoint", _DISJOINT
    yield "three_on_one_edge", [
        _UNIT, ((0, 0), (1, 0), (0, -1)), ((0, 0), (1, 0), (1, 1))
    ]
    yield "clockwise", [((0, 0), (0, 1), (1, 0))]
    yield "duplicate_face", [_UNIT, _UNIT]
    yield "empty", []
    # Actual CSV parsing keeps the float conversion exercised in both files.
    for scale in (1, 2):
        yield f"csv_shared_edge_{scale}", load_uv_csv(
            f"tri,u,v\na,0,0\na,{scale},0\na,0,{scale}\n"
            f"b,{scale},0\nb,{scale},{scale}\nb,0,{scale}\n"
        )
    # The JSON CLI fixtures arrive as lists, not the API's tuple examples.
    for name, triangles in (("box", _BOX), ("contained", _CONTAINED),
                            ("disjoint", _DISJOINT)):
        yield f"cli_json_{name}", json.loads(json.dumps(triangles))


class UvGateFastEquivalenceTest(unittest.TestCase):
    def assertEquivalent(self, triangles, abs_eps=1e-12):
        """Compare every field, including the exact legacy first witness."""
        reference = uv_overlap_gate(
            triangles, abs_eps, method="reference", collect_pairs=True
        )
        pairs = reference["overlapping_pairs"]
        self.assertEqual(pairs, sorted(set(pairs)))
        self.assertEqual(reference["pairs"], len(pairs))
        if pairs:
            self.assertEqual(reference["witness"][:2], pairs[0])
        else:
            self.assertIsNone(reference["witness"])
        without_pairs = dict(reference)
        without_pairs.pop("overlapping_pairs")
        self.assertEqual(set(without_pairs), _LEGACY_KEYS)
        for method in _METHODS:
            with self.subTest(method=method, collect_pairs=True):
                got = uv_overlap_gate(
                    triangles, abs_eps, method=method, collect_pairs=True
                )
                self.assertEqual(got, reference)
            with self.subTest(method=method, collect_pairs=False):
                self.assertEqual(
                    uv_overlap_gate(triangles, abs_eps, method=method), without_pairs
                )
        self.assertEqual(uv_overlap_gate(triangles, abs_eps), without_pairs)
        return reference

    def test_all_existing_geometry_fixtures(self):
        for name, triangles in _existing_fixtures():
            with self.subTest(fixture=name):
                self.assertEquivalent(triangles)

    def test_default_schema_and_known_reference_witness(self):
        # Pin legacy behavior independently of the new method selector.
        expected = {
            "pass": False, "pairs": 1, "degenerate": 0,
            "witness": (0, 1, 0.5),
            "rule": "fail when any pair has interior intersection area above abs_eps",
        }
        self.assertEqual(uv_overlap_gate(_CONTAINED), expected)
        for method in _METHODS:
            with self.subTest(method=method):
                self.assertEqual(
                    uv_overlap_gate(_CONTAINED, method=method, collect_pairs=True),
                    dict(expected, overlapping_pairs=[(0, 1)]),
                )

    def test_pair_order_and_witness_use_original_indices(self):
        # Spatial order is deliberately opposite input order, with skipped faces.
        right = ((20, 0), (22, 0), (20, 2))
        left = ((-20, 0), (-18, 0), (-20, 2))
        triangles = [right, _DEGENERATE, right, left, tuple(reversed(left)),
                     ((0, 0), (0, 0), (0, 0)), right]
        got = self.assertEquivalent(triangles, 0)
        self.assertEqual(got["overlapping_pairs"], [(0, 2), (0, 6), (2, 6), (3, 4)])
        self.assertEqual(got["witness"], (0, 2, 2.0))
        self.assertEqual(got["degenerate"], 2)

    def test_shared_vertices_edges_and_collinear_contacts(self):
        fixtures = {
            "single_vertex": [_UNIT, ((1, 0), (2, 0), (1, 1))],
            "partial_edge": [_UNIT, ((0, 0), (Fraction(1, 2), 0), (0, -1))],
            "collinear_degenerate": [_UNIT, _DEGENERATE],
            "bounding_boxes_overlap_only": [
                _UNIT, ((1, 1), (Fraction(3, 4), 1), (1, Fraction(3, 4)))
            ],
        }
        for name, triangles in fixtures.items():
            with self.subTest(fixture=name):
                self.assertEqual(self.assertEquivalent(triangles, 0)["pairs"], 0)

    def test_grid_cell_boundaries_and_large_face(self):
        triangles = []
        # A connected tiling across negative and positive coordinates.
        for y in range(-3, 4):
            for x in range(-3, 4):
                triangles.extend([
                    ((x, y), (x + 1, y), (x, y + 1)),
                    ((x + 1, y), (x + 1, y + 1), (x, y + 1)),
                ])
        # This triangle crosses many cells and contains many existing faces.
        triangles.extend([((-4, -4), (12, -4), (-4, 12)), _DEGENERATE])
        got = self.assertEquivalent(triangles)
        self.assertGreater(got["pairs"], 50)

    def test_exact_fraction_coordinates_and_strict_epsilon(self):
        small = ((0, 0), (Fraction(1, 2), 0), (0, Fraction(1, 2)))
        triangles = [small, tuple(reversed(small))]
        for epsilon, expected_pairs in [
            (0, 1), (Fraction(1, 8) - Fraction(1, 10**20), 1),
            (Fraction(1, 8), 0), (Fraction(1, 8) + Fraction(1, 10**20), 0),
        ]:
            with self.subTest(abs_eps=epsilon):
                self.assertEqual(self.assertEquivalent(triangles, epsilon)["pairs"],
                                 expected_pairs)

    def test_negative_epsilon_includes_disjoint_pairs(self):
        triangles = [_DISJOINT[0], _DEGENERATE, _DISJOINT[1],
                     ((100, 100), (101, 100), (100, 101))]
        for epsilon in (-1e-12, Fraction(-1, 10**30)):
            with self.subTest(abs_eps=epsilon):
                got = self.assertEquivalent(triangles, epsilon)
                self.assertEqual(got["overlapping_pairs"], [(0, 2), (0, 3), (2, 3)])
                self.assertEqual(got["witness"], (0, 2, 0.0))

    def test_float_slivers_at_and_across_a_shared_edge(self):
        # nextafter distinguishes exact touching from a tiny positive overlap.
        for start in (math.nextafter(1.0, 0.0), 1.0, math.nextafter(1.0, 2.0)):
            triangles = [((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
                         ((start, 0.0), (2.0, 0.0), (start, 1.0))]
            for epsilon in (0, 1e-12):
                with self.subTest(start=start, abs_eps=epsilon):
                    self.assertEquivalent(triangles, epsilon)
        got = self.assertEquivalent([
            ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
            ((math.nextafter(1.0, 0.0), 0.0), (2.0, 0.0),
             (math.nextafter(1.0, 0.0), 1.0))
        ], 0)
        self.assertEqual(got["pairs"], 1)

    def test_extreme_origins_scales_and_mixed_numeric_types(self):
        tiny = math.ulp(0.0)
        rational_tiny = Fraction(1, 10**200)
        fixtures = {
            "beyond_float_integer_precision": (2**60, 1),
            "integer_origin_exceeds_float_range": (10**400, 1),
            "subnormal_float": (0, tiny),
            "underflowing_rational_area": (0, rational_tiny),
            "ordinary_mixed_types": (Fraction(-7, 3), 0.5),
        }
        for name, (origin, scale) in fixtures.items():
            triangle = ((origin, origin), (origin + 4 * scale, origin),
                        (origin, origin + 4 * scale))
            inner = ((origin + scale, origin + scale),
                     (origin + 2 * scale, origin + scale),
                     (origin + scale, origin + 2 * scale))
            with self.subTest(fixture=name):
                got = self.assertEquivalent([triangle, inner], 0)
                self.assertEqual(got["pairs"], 1)

    def test_seeded_dense_random_meshes(self):
        for seed in (0, 7, 1912):
            rng = random.Random(seed)
            triangles = [tuple((rng.uniform(-2, 2), rng.uniform(-2, 2))
                               for _ in range(3)) for _ in range(20)]
            triangles.extend([triangles[4], tuple(reversed(triangles[8])), _DEGENERATE])
            with self.subTest(seed=seed):
                self.assertEquivalent(triangles)

    def test_seeded_sparse_integer_and_fraction_meshes(self):
        for seed in (5, 41, 2026):
            rng = random.Random(seed)
            triangles = []
            for _ in range(36):
                x, y = rng.randrange(-100, 100), rng.randrange(-100, 100)
                scale = rng.choice((1, 2, Fraction(1, 3)))
                tri = ((x, y), (x + scale, y), (x, y + scale))
                triangles.append(tuple(reversed(tri)) if rng.randrange(2) else tri)
            triangles.extend([triangles[3], triangles[20], _DEGENERATE])
            with self.subTest(seed=seed):
                self.assertEquivalent(triangles, 0)

    def test_mixed_large_integer_and_float_preserves_unit_width(self):
        base = 2**53
        triangles = [[(base, 0.0), (base + 1, 0.0), (base, 1.0)]]
        got = self.assertEquivalent(triangles)
        self.assertTrue(got["pass"])
        self.assertEqual(got["degenerate"], 0)

    def test_string_epsilon_accepted_by_fraction(self):
        for epsilon in ("0", "1e-12", "-0.01"):
            with self.subTest(abs_eps=epsilon):
                self.assertEquivalent(_CONTAINED + _DISJOINT, epsilon)

    @unittest.skipIf(np is None, "NumPy is optional")
    def test_numpy_float_and_integer_inputs(self):
        for dtype in (np.float64, np.int64, np.uint64):
            with self.subTest(dtype=dtype):
                self.assertEquivalent(np.asarray(_CONTAINED, dtype=dtype))
        # Strided array views must keep original triangle indices.
        array = np.asarray(_CONTAINED + _BOX + _DISJOINT, dtype=np.float64)
        self.assertEquivalent(array[::2])
        self.assertEquivalent(array[::-1])

    def test_auto_falls_back_without_numpy_and_grid_requires_it(self):
        for collect_pairs in (False, True):
            expected = uv_overlap_gate(
                _CONTAINED, method="reference", collect_pairs=collect_pairs
            )
            with self.subTest(collect_pairs=collect_pairs):
                # Simulate an absent optional dependency even on a NumPy host.
                with patch.dict(sys.modules, {"numpy": None}):
                    self.assertEqual(
                        uv_overlap_gate(_CONTAINED, method="auto",
                                        collect_pairs=collect_pairs), expected
                    )
                    with self.assertRaises(ImportError):
                        uv_overlap_gate(_CONTAINED, method="grid",
                                        collect_pairs=collect_pairs)

    def test_no_positive_area_does_not_parse_invalid_epsilon(self):
        for triangles in ([], [_DEGENERATE]):
            for epsilon in (None, "invalid", float("nan"), float("inf")):
                with self.subTest(triangles=triangles, abs_eps=epsilon):
                    got = self.assertEquivalent(triangles, epsilon)
                    self.assertFalse(got["pass"])
                    self.assertEqual(got["pairs"], 0)
                    self.assertEqual(got["degenerate"], len(triangles))
                    self.assertEqual(got["rule"], "fail when no triangle has positive area")

    def test_one_pass_iterable_input(self):
        expected = uv_overlap_gate(_CONTAINED, method="reference", collect_pairs=True)
        for method in _METHODS:
            with self.subTest(method=method):
                self.assertEqual(
                    uv_overlap_gate((tri for tri in _CONTAINED), method=method,
                                    collect_pairs=True), expected
                )

    def test_bad_geometry_raises_the_same_error(self):
        fixtures = [
            [((0, 0), (1, 0))],  # Existing meshgate bad-shape fixture.
            [((0, 0), (1, 0), (0, 1, 2))],
            [((0, 0), (1, 0), (0, float("nan")))],
            [((0, 0), (1, 0), (0, float("inf")))],
        ]
        for triangles in fixtures:
            with self.subTest(triangles=triangles):
                try:
                    uv_overlap_gate(triangles, method="reference")
                except (UvGateError, ValueError, OverflowError) as exc:
                    expected_type, expected_message = type(exc), str(exc)
                else:
                    self.fail("Malformed reference fixture unexpectedly accepted")
                for method in (name for name in _METHODS if name != "reference"):
                    with self.subTest(method=method):
                        with self.assertRaises(expected_type) as caught:
                            uv_overlap_gate(triangles, method=method)
                        self.assertEqual(str(caught.exception), expected_message)


if __name__ == "__main__":
    unittest.main()
