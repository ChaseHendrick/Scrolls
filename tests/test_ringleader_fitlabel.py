"""scripts/ringleader/fitlabel.py: a spiral fit read as one integer turn per m7 skeleton piece.

Synthetic slices only. A spiral's continuous outward position P (in turns) puts a point at image angle
2 pi P (times the spiral's hand) about the axis; Ringleader's turn there is floor(P) when theta' is measured in the
spiral's own hand from the start ray. A synthetic fit gives u = P + c and theta_f = 2 pi P + phi0, with noise, an
arbitrary offset c and a rotation phi0. The labels must equal the true turn up to one constant offset per slice,
whichever hand the geometry was built with, and must fail (not be constant) when the fit's angle is scrambled.
Skipped without numpy.
"""

import math
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ringleader"))

try:
    import numpy as np
    import fitlabel
except ImportError:          # pragma: no cover
    fitlabel = None


def synthetic(h_true=-1, hand_geo=-1, c=17.3, phi0=1.1, n_turns=12, per_turn=900, noise_u=0.08, noise_th=0.15,
              seed=0):
    rng = np.random.default_rng(seed)
    P = np.sort(rng.uniform(3.0, 3.0 + n_turns, n_turns * per_turn))
    TH = np.mod(h_true * 2 * math.pi * P, 2 * math.pi)                  # image angle about the axis
    T = np.floor(P)                                                     # Ringleader's turn in the spiral's hand
    theta_p = np.mod(hand_geo * TH, 2 * math.pi)                        # the geometry's theta' (its own hand)
    u = P + c + rng.normal(0, noise_u, len(P))
    theta_f = np.mod(2 * math.pi * P + phi0 + rng.normal(0, noise_th, len(P)), 2 * math.pi)
    # pieces: runs of 40 consecutive points that never cross the start ray (as slicelab.make_pieces cuts them)
    pid = np.zeros(len(P), np.int64)
    k, prev_t, cnt = 0, T[0], 0
    for i in range(len(P)):
        if T[i] != prev_t or cnt == 40:
            k, cnt, prev_t = k + 1, 0, T[i]
        pid[i] = k
        cnt += 1
    return P, T, TH, theta_p, u, theta_f, pid


@unittest.skipIf(fitlabel is None, "needs numpy")
class FitLabelTest(unittest.TestCase):
    def check_constant_offset(self, h_true, hand_geo, phi0=1.1, c=17.3):
        P, T, TH, theta_p, u, theta_f, pid = synthetic(h_true, hand_geo, c=c, phi0=phi0)
        lab, px, h, theta_h, f0, spread = fitlabel.labels(u, theta_f, theta_p, hand_geo, pid)
        self.assertEqual(h, h_true)
        # theta_h is theta' in the fit's hand with the same start ray: the spiral's own theta'
        self.assertTrue(np.allclose(np.mod(theta_h - np.mod(h_true * TH, 2 * math.pi) + 1, 2 * math.pi), 1))
        off = lab - T
        self.assertEqual(len(np.unique(off)), 1, f"offsets {np.unique(off, return_counts=True)}")
        self.assertAlmostEqual(f0, c % 1.0, delta=0.02)
        self.assertLess(spread, 0.1)
        # per piece: one label
        for k in np.unique(pid)[:50]:
            self.assertEqual(len(np.unique(lab[pid == k])), 1)

    def test_hands_and_rotations(self):
        for h_true in (1, -1):
            for hand_geo in (1, -1):
                for phi0 in (0.0, 1.1, 4.0):
                    with self.subTest(h_true=h_true, hand_geo=hand_geo, phi0=phi0):
                        self.check_constant_offset(h_true, hand_geo, phi0=phi0)

    def test_phase_near_half(self):
        # sheets sitting at the fit's half-turn: the phase moves with them, no pixel is split between two turns
        self.check_constant_offset(-1, -1, c=5.49)
        self.check_constant_offset(-1, -1, c=5.01)

    def test_piece_vote_overrides_stray_pixels(self):
        P, T, TH, theta_p, u, theta_f, pid = synthetic()
        bad = np.flatnonzero(pid == 7)[:5]          # 5 of a 40-pixel piece pushed one turn out
        u = u.copy()
        u[bad] += 1.0
        lab, px, h, *_ = fitlabel.labels(u, theta_f, theta_p, -1, pid)
        self.assertTrue((px[bad] - T[bad] != (lab - T)[0]).all())
        self.assertEqual(len(np.unique(lab - T)), 1)

    def test_scrambled_fit_fails(self):
        # the check can fail: a fit whose position carries no turn information gives no constant offset
        P, T, TH, theta_p, u, theta_f, pid = synthetic()
        rng = np.random.default_rng(3)
        u_bad = rng.uniform(0, 20, len(u))
        lab, *_ = fitlabel.labels(u_bad, theta_f, theta_p, -1, pid)
        vals, cnt = np.unique(lab - T, return_counts=True)
        self.assertLess(cnt.max() / cnt.sum(), 0.3)

    def test_piece_mode_ties_and_missing(self):
        lab = np.array([1, 2, 2, 1, 5, np.nan, 3, 3])
        pid = np.array([0, 0, 0, 1, 1, 2, 3, -1])
        out = fitlabel.piece_mode(lab, pid)
        self.assertEqual(out[0], 2)                  # 2 beats 1 in piece 0
        self.assertEqual(out[3], 1)                  # tie 1 and 5: the lower
        self.assertTrue(np.isnan(out[5]))            # piece 2 has no finite label
        self.assertEqual(out[6], 3)
        self.assertTrue(np.isnan(out[7]))            # pid -1

    def test_fit_coords_axis_order(self):
        # to_sp takes z, y, x (villa's slice-to-spiral input) and returns (w, a, b) with r = hypot(a, b) and
        # theta = arctan2(a, b); a frame that maps q to fit with x + 10, y + 20, z / 2
        class Frame:
            def to_fit(self, q):
                return q * np.array([1.0, 1.0, 0.5]) + np.array([10.0, 20.0, 0.0])

        cx, cy = 110.0, 220.0

        def to_sp(zyx):
            z, y, x = zyx[:, 0], zyx[:, 1], zyx[:, 2]
            return np.stack([z, y - cy, x - cx], 1)

        xs, ys = np.array([100, 100, 200]), np.array([300, 200, 200])
        u, th, f = fitlabel.fit_coords(to_sp, 2.0, xs, ys, 40, Frame())
        self.assertTrue(np.allclose(f[:, 2], 20.0))
        ex = np.hypot(ys + 20 - cy, xs + 10 - cx) / 2.0
        self.assertTrue(np.allclose(u, ex))
        self.assertTrue(np.allclose(th, np.arctan2(ys + 20 - cy, xs + 10 - cx)))

    def test_frame_is_catalog_matrix_over_scale(self):
        M = np.array([[2.0, 0.1, 0.0, 10.0], [0.0, 2.0, 0.0, -4.0], [0.0, 0.0, 2.0, 6.0]])
        q = np.array([[100.0, 200.0, 300.0], [0.0, 0.0, 0.0]])
        f = fitlabel.Frame(M, 4.0).to_fit(q)
        self.assertTrue(np.allclose(f, (q @ M[:, :3].T + M[:, 3]) / 4.0))


if __name__ == "__main__":
    unittest.main()
