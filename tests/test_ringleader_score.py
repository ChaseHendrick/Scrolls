"""scripts/ringleader: the shared helpers (rlcommon), the seam-free truth (wtruth) and the scorer's metrics (score).

Synthetic data only. Spiral windings traced a little past one turn, in both hands, with two winding numbers left
out, are matched back from points on the sheets of one slice: the truth must find the spiral's hand from the
meshes alone, give every matched point the same label-minus-turn offset, and leave the left-out turns unmatched.
The scorer's on-winding E0 must be 1 for a perfect labelling up to a constant, and its planted and jitter controls
must fail on it. Skipped without numpy and scipy.
"""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ringleader"))

try:
    import numpy as np
    import scipy  # noqa: F401
    import rlcommon
    import score
    import wtruth
    from kit import sheetrefs as sr
except ImportError:          # pragma: no cover
    rlcommon = None

CX, CY, R0, P = 300.0, 310.0, 40.0, 16.0


def mesh(n, hand, over=0.15, nz=30):
    """Winding n of an Archimedean spiral (radius R0 + P (n + theta / 2 pi)), traced from theta 0 to (1 + over)
    turns, as a tifxyz-like grid: rows are heights, columns the angle."""
    th = np.linspace(0, 2 * np.pi * (1 + over), int(2 * np.pi * (R0 + P * (n + 1)) / 3) + 1)
    T, Z = np.meshgrid(th, np.arange(0, nz, 3.0))
    r = R0 + P * (n + T / (2 * np.pi))
    xyz = np.stack([CX + r * np.cos(hand * T), CY + r * np.sin(hand * T), Z], -1)
    return xyz, np.ones(T.shape, bool)


def sheet_points(hand, turns, z=12.0, per_turn=400):
    phi = np.linspace(0, 2 * np.pi, per_turn, endpoint=False)
    pts, k = [], []
    for n in turns:
        r = R0 + P * (n + phi / (2 * np.pi))
        pts.append(np.stack([CX + r * np.cos(hand * phi), CY + r * np.sin(hand * phi), np.full(per_turn, z)], 1))
        k.append(np.full(per_turn, n))
    return np.concatenate(pts), np.concatenate(k).astype(float)


@unittest.skipIf(rlcommon is None, "needs numpy and scipy")
class TestHelpers(unittest.TestCase):
    def test_ranges_and_exclusion(self):
        self.assertEqual(rlcommon.parse_ranges("10:20, 30"), [(10, 20), (30, 30)])
        self.assertEqual(rlcommon.parse_ranges(None), [])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "ex.txt"
            f.write_text("# held out\n100:110\n")
            self.assertEqual(rlcommon.parse_ranges(str(f)), [(100, 110)])
        rlcommon.check_z([5, 50], [(10, 20)])
        with self.assertRaises(SystemExit):
            rlcommon.check_z([5, 15], [(10, 20)])
        with self.assertRaises(SystemExit):
            rlcommon.parse_ranges("20:10")

    def test_axis_affine_and_catalog(self):
        A = np.array([[2.0, 0, 0, 1], [0, 2.0, 0, 2], [0, 0, 2.0, 3]])
        self.assertTrue(np.allclose(rlcommon.apply(rlcommon.invert(A), rlcommon.apply(A, [[1.0, 2, 3]])), [[1, 2, 3]]))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "umb.json"
            f.write_text(json.dumps({"control_points": [{"x": 1, "y": 2, "z": 0}, {"x": 3, "y": 6, "z": 10}]}))
            ax = rlcommon.Axis.from_json(f)
            x, y = ax.at(5.0)
            self.assertAlmostEqual(float(x), 2.0)
            self.assertAlmostEqual(float(y), 4.0)
            ax2 = rlcommon.Axis.from_json(f, affine=A)
            self.assertTrue(np.allclose(ax2.pts[0], [3, 6, 3]))
        M = rlcommon.catalog_matrix("PHerc0139", "20250728140407", "20260102150214")      # the shipped copy
        self.assertEqual(M.shape, (3, 4))
        self.assertTrue(3.8 < abs(np.linalg.det(M[:, :3])) ** (1 / 3) < 4.0)

    def test_turn_angles_unwrap_past_a_turn(self):
        xyz, v = mesh(5, 1)
        a = rlcommon.turn_angles(xyz, v, np.array([[-10.0, CY, CX], [100.0, CY, CX]]))
        row = a[0]
        self.assertAlmostEqual(row[-1] - row[0], 360 * 1.15, delta=1.0)
        self.assertTrue(np.all(np.diff(row) > 0))

    def test_missing_sides(self):
        self.assertEqual(wtruth.missing_sides(["w305", "w306", "w308"]),
                         {"w305": [-1], "w306": [1], "w308": [1, -1]})


@unittest.skipIf(rlcommon is None, "needs numpy and scipy")
class TestTruth(unittest.TestCase):
    def test_hand_offset_and_gaps(self):
        axis = rlcommon.Axis([[CX, CY, -10], [CX, CY, 100]])
        for hand in (1, -1):
            refs = [sr.Ref(f"w{300 + n:03d}", gid, *mesh(n, hand)) for gid, n in enumerate((5, 6, 7, 9, 10))]
            T = wtruth.Truth(refs, axis)
            self.assertEqual(T.hand, hand)
            Pp, K = sheet_points(hand, range(5, 12))
            rank, alpha, amb, contact = T.label(Pp, amb=True)
            thp = np.mod(hand * np.arctan2(Pp[:, 1] - CY, Pp[:, 0] - CX), 2 * np.pi)
            turn, resid = wtruth.turns(rank, alpha, thp, T.hand)
            ok = np.isfinite(turn)
            self.assertGreater(ok[np.isin(K, (5, 6, 7, 9, 10))].mean(), 0.8)
            self.assertFalse(ok[np.isin(K, (8, 11))].any())          # no winding loaded there
            self.assertEqual(len(np.unique((turn - K)[ok])), 1)      # one offset: seam-free
            self.assertLess(float(np.nanmax(resid)), 0.05)
            self.assertFalse(amb.any())                              # sheets are 16 voxels apart

    def test_misnamed_windings_break_the_offset(self):
        # the check can fail: with two windings' names swapped, their ranks are wrong and the offset is not one
        axis = rlcommon.Axis([[CX, CY, -10], [CX, CY, 100]])
        names = {5: "w307", 6: "w306", 7: "w305"}
        refs = [sr.Ref(names[n], gid, *mesh(n, -1)) for gid, n in enumerate((5, 6, 7))]
        T = wtruth.Truth(refs, axis)
        Pp, K = sheet_points(-1, (5, 6, 7))
        rank, alpha = T.label(Pp)
        thp = np.mod(-np.arctan2(Pp[:, 1] - CY, Pp[:, 0] - CX), 2 * np.pi)
        turn, _ = wtruth.turns(rank, alpha, thp, T.hand)
        ok = np.isfinite(turn)
        _, c = np.unique((turn - K)[ok], return_counts=True)
        self.assertLess(c.max() / c.sum(), 0.6)


@unittest.skipIf(rlcommon is None, "needs numpy and scipy")
class TestMetrics(unittest.TestCase):
    def test_e0_and_controls(self):
        rng = np.random.default_rng(0)
        n = 6000
        turn = rng.integers(0, 12, n).astype(float)
        th = rng.uniform(0, 2 * math.pi, n)
        L = turn + 7                                               # perfect up to a constant
        rows = np.stack([np.arange(0, n - 1, 2), np.arange(1, n, 2)], 1)
        r = score.score_labels(L, turn, th, rows[:, 0], rows[:, 1], np.random.default_rng(1), n_pairs=5000)
        self.assertEqual(r["on_winding"], 1.0)
        self.assertEqual(r["offset"], 7)
        self.assertEqual(r["pair"], 1.0)
        self.assertEqual(r["step_acc"], 1.0)
        pl, phi = score.planted(L, th, turn)
        rp = score.score_labels(pl, turn, th, rows[:, 0], rows[:, 1], np.random.default_rng(1), n_pairs=10)
        self.assertLessEqual(rp["on_winding"], 1 - 0.8 * 0.25)     # the planted control drops as required
        pid = np.arange(n) // 40
        jit = L + rng.integers(-1, 2, pid.max() + 1)[pid]
        rj = score.score_labels(jit, turn, th, rows[:, 0], rows[:, 1], np.random.default_rng(1), n_pairs=10)
        self.assertLessEqual(rj["on_winding"], 0.4)                # the jitter control stays low
        # unmatched pixels (NaN turn) are not scored
        t2 = turn.copy()
        t2[:100] = np.nan
        L2 = L.copy()
        L2[:100] = -50
        self.assertEqual(score.score_labels(L2, t2, th, rows[:, 0], rows[:, 1], np.random.default_rng(1),
                                            n_pairs=10)["on_winding"], 1.0)


if __name__ == "__main__":
    unittest.main()
