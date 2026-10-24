"""kit windcheck: winding coverage of a point in a slice's traced sheets, on synthetic spirals."""
import math
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kit import windcheck  # noqa: E402


@unittest.skipIf(np is None, "needs numpy")
class TestCoverage(unittest.TestCase):
    def test_the_self_check_passes(self):
        res = windcheck.selfcheck()
        self.assertTrue(res["passes"], res)

    def test_a_closed_loop_round_the_point_counts_one_turn_and_one_beside_it_less(self):
        loop = [[(500 + 100 * math.cos(t), 500 + 100 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 361)]]
        segs = windcheck.segments(loop)
        self.assertAlmostEqual(windcheck.coverage(segs, (500, 500)), 1.0, places=6)
        self.assertAlmostEqual(windcheck.coverage(segs, (560, 520)), 1.0, places=6)   # still inside
        # outside a circle of radius rho at distance r: 4 asin(rho / r) / (2 pi) turns
        self.assertAlmostEqual(windcheck.coverage(segs, (700, 500)), 4 * math.asin(100 / 200) / (2 * math.pi), places=3)

    def test_coverage_falls_as_the_point_leaves_the_core_of_a_spiral(self):
        segs = windcheck.segments([windcheck.spiral((0.0, 0.0), 30.0, 15)])
        cov = [windcheck.coverage(segs, (30.0 * k, 0.0)) for k in (0, 1, 3, 6)]
        self.assertTrue(all(a > b for a, b in zip(cov, cov[1:])), cov)
        # about 0.64 wraps lost per wrap of pitch moved out (concentric-circle estimate 2 / pi)
        self.assertAlmostEqual((cov[0] - cov[3]) / 6, 2 / math.pi, delta=0.15)

    def test_a_segment_through_the_point_is_left_out(self):
        segs = windcheck.segments([[(0, 0), (10, 0)]])
        self.assertEqual(windcheck.coverage(segs, (5, 0)), 0.0)
        self.assertEqual(windcheck.coverage(windcheck.segments([]), (5, 0)), 0.0)

    def test_the_ring_and_the_local_best(self):
        segs = windcheck.segments([windcheck.spiral((0.0, 0.0), 30.0, 15)])
        at = windcheck.coverage(segs, (0.0, 0.0))
        self.assertTrue(all(v < at for v in windcheck.ring(segs, (0.0, 0.0), 120.0)))
        best, where = windcheck.best_near(segs, [(150.0, 0.0)], 200.0, 25.0)
        self.assertLess(math.hypot(*where), 60.0)
        self.assertGreater(best, windcheck.coverage(segs, (150.0, 0.0)))


if __name__ == "__main__":
    unittest.main()
