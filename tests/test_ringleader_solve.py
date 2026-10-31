"""scripts/ringleader/slicelab: the minimum-cost-flow route ("mcf") reaches the LP's optimum, and whole synthetic
slices and stacks are labelled with their true turns.

Random small labelling problems (continuity edges with shifts, radial edges with convex costs, several
components) are solved both ways; the objectives must agree, and the flow labels must be integers with each
component's first piece at 0. Synthetic Archimedean spirals (both hands, a sheet missing over a sector, small
gaps) are labelled end to end with the v1 settings; label minus true turn must be one constant, and counting
sheets along rays must score badly on the same slices. Skipped without numpy, scipy, scikit-image or OR-tools.
"""

import random
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ringleader"))

try:
    import numpy as np
    import ortools  # noqa: F401
    import scipy  # noqa: F401
    import skimage  # noqa: F401
    import slab3d
    import slicelab
except ImportError:          # pragma: no cover
    slicelab = None


def problem(seed, n=60, ncont=90, nrad=120, ncomp=3):
    rng = random.Random(seed)
    groups = [list(range(k, n, ncomp)) for k in range(ncomp)]
    cont, rad = [], []
    for _ in range(ncont):
        g = rng.choice(groups)
        a, b = rng.sample(g, 2)
        cont.append((a, b, rng.choice((-1, 0, 0, 0, 1)), rng.choice((1.0, 2.5, 10.0))))
    for _ in range(nrad):
        g = rng.choice(groups)
        a, b = rng.sample(g, 2)
        wh, wl = rng.uniform(0.1, 20), rng.uniform(0.1, 3)
        extra = rng.uniform(0, 2)
        sh = rng.choice((0, 0, 0, 1, -1))                          # start-ray shift of the step
        rad.append((a, b, wh, 0.0, wl, 2 * wl + extra, sh))     # convex: slopes -wh, wl, wl + extra
    return n, cont, rad


@unittest.skipIf(slicelab is None, "needs numpy, scipy, scikit-image and OR-tools")
class TestMcf(unittest.TestCase):
    def test_same_objective_as_lp(self):
        for seed in range(12):
            n, cont, rad = problem(seed)
            p = dict(slicelab.PARAMS, lp_method="highs")
            lab_lp, comp_lp, info_lp = slicelab.solve(n, cont, rad, p)
            lab_f, comp_f, info_f = slicelab.solve(n, cont, rad, dict(p, lp_method="mcf", mcf_scale=1e4))
            self.assertEqual(info_lp["status"], 0)
            self.assertEqual(info_f["status"], 0)
            o_lp = slicelab.objective(np.nan_to_num(lab_lp), cont, rad, p)
            o_f = slicelab.objective(np.nan_to_num(lab_f), cont, rad, p)
            self.assertAlmostEqual(o_f, o_lp, delta=1e-6 * max(1.0, abs(o_lp)) + 1e-3, msg=f"seed {seed}")
            ok = np.isfinite(lab_f)
            self.assertTrue(np.array_equal(ok, np.isfinite(lab_lp)))
            self.assertTrue(np.all(lab_f[ok] == np.rint(lab_f[ok])))
            self.assertTrue(np.array_equal(comp_f, comp_lp))
            for c in np.unique(comp_f[ok]):
                first = np.flatnonzero(comp_f == c)[0]
                self.assertEqual(lab_f[first], 0.0)

    def test_objective_matches_lp_value(self):
        n, cont, rad = problem(99)
        p = dict(slicelab.PARAMS, lp_method="highs")
        lab, _, info = slicelab.solve(n, cont, rad, p)
        self.assertAlmostEqual(slicelab.objective(np.nan_to_num(lab), cont, rad, p), info["objective"], places=4)

    def test_radial_step_across_the_start_ray(self):
        # one radial term whose samples cross theta' = 0 outward: the next sheet's label is 2 higher (s = +1),
        # or 0 higher the other way (s = -1)
        for sh, want in ((1, 2.0), (0, 1.0), (-1, 0.0)):
            for method in ("highs", "mcf"):
                p = dict(slicelab.PARAMS, lp_method=method)
                lab, _, info = slicelab.solve(2, [], [(0, 1, 20.0, 0.0, 1.0, 2.0, sh)], p)
                self.assertEqual(info["status"], 0)
                self.assertEqual(lab[1] - lab[0], want, msg=f"{method} shift {sh}")

    def test_row_shifts_and_flip(self):
        th = np.array([6.2, 0.05, 1.0, 1.2, 0.1, 6.25])
        geo = {"rows": np.array([[0, 1, 0, 0, 5], [2, 3, 0, 0, 5], [4, 5, 0, 0, 5]], float), "theta_p": th,
               "hand": 1, "pieces": [np.array([0, 2]), np.array([1, 3]), np.array([4]), np.array([5])],
               "cont": [(0, 1, 0)], "pid": np.array([0, 1, 0, 1, 2, 3])}
        self.assertEqual(slicelab.row_shifts(geo).tolist(), [1, 0, -1])
        g = slicelab.flip_hand(geo)
        self.assertEqual(g["hand"], -1)
        self.assertEqual(slicelab.row_shifts(g).tolist(), [-1, 0, 1])
        self.assertTrue(np.allclose(np.mod(g["theta_p"] + th, 2 * np.pi), 0))
        self.assertIs(slicelab.with_hand(geo, 1), geo)
        self.assertEqual(slicelab.with_hand(geo, -1)["hand"], -1)

    def test_track_hand_on_synthetic_spirals(self):
        # thin Archimedean spirals: radius growing with the atan2 angle is hand +1, shrinking is -1
        n, cx, cy = 820, 410.0, 405.0
        p = dict(slicelab.PARAMS, r_min=40.0, track_r_max=400.0, track_r_lo=90.0, track_r_hi=330.0,
                 track_rays=720)
        for hand in (1, -1):
            S = np.zeros((n, n), bool)
            th = np.linspace(0, 2 * np.pi * 26, 400000)
            r = 30.0 + 14.0 * th / (2 * np.pi)
            ang = hand * th
            X = np.rint(cx + r * np.cos(ang)).astype(int)
            Y = np.rint(cy + r * np.sin(ang)).astype(int)
            ok = (X >= 0) & (X < n) & (Y >= 0) & (Y < n)
            S[Y[ok], X[ok]] = True
            h = slicelab.track_hand(S, cx, cy, p)
            self.assertEqual(h["hand"], hand, msg=str(h))
            self.assertGreater(max(h["outward"], h["inward"]), 10)

    def test_edge_cost_is_convex_hinge(self):
        g = slicelab.edge_cost(np.array([-1.0, 0.0, 1.0, 2.0, 3.0]), (-5.0, 1.0, 2.0), (1, 2))
        self.assertTrue(np.allclose(np.diff(g), [-5.0, -5.0, 1.0, 2.0]))


    def test_no_private_options(self):
        # v1 as frozen: no detector, fiber or grad_mag costs; the v1 settings are mcf with the tracked hand
        for k in ("det", "gm", "cont_weak_q"):
            self.assertNotIn(k, slicelab.PARAMS)
        self.assertEqual(slicelab.V1, {"lp_method": "mcf", "hand": "track"})


CX, CY, R0, PITCH = 352.0, 347.0, 40.0, 16.0


def spiral_slice(hand, n=700, width=1.6, turns=18, drop=None, gaps=0, seed=0, dx=0.0):
    """A binary slice of an Archimedean spiral about (CX + dx, CY), sheets PITCH apart. drop: (turn, lo, hi) leaves
    out that turn's sheet for theta' in [lo, hi) radians (a sheet the prediction missed); gaps: that many small
    holes cut into the sheets."""
    yy, xx = np.mgrid[0:n, 0:n]
    R = np.hypot(xx - CX - dx, yy - CY)
    th = np.mod(hand * np.arctan2(yy - CY, xx - CX - dx), 2 * np.pi)
    u = (R - R0) / PITCH - th / (2 * np.pi)
    k = np.rint(u)
    S = (np.abs(u - k) * PITCH <= width) & (k >= 0) & (R < R0 + PITCH * turns)
    if drop is not None:
        t, lo, hi = drop
        S &= ~((k == t) & (th >= lo) & (th < hi))
    rng = np.random.default_rng(seed)
    for _ in range(gaps):
        y, x = rng.integers(60, n - 60, 2)
        S[y - 3:y + 4, x - 3:x + 4] = False
    return (S * 255).astype(np.uint8)


def true_turn(geo):
    return np.rint((geo["r"] - R0) / PITCH - geo["theta_p"] / (2 * np.pi))


def params(**kw):
    p = dict(slicelab.PARAMS, **slicelab.V1)
    p.update(r_min=60.0, track_r_max=330.0, track_r_lo=80.0, track_r_hi=300.0, track_rays=720, **kw)
    return p


def e0(L, k):
    ok = np.isfinite(L) & np.isfinite(k)
    _, c = np.unique((L - k)[ok], return_counts=True)
    return c.max() / c.sum()


@unittest.skipIf(slicelab is None, "needs numpy, scipy, scikit-image and OR-tools")
class TestSyntheticSlices(unittest.TestCase):
    def label(self, m7, p):
        geo = slicelab.geometry(m7, CX, CY, p, log=lambda m: None)
        geo["track_hand"] = slicelab.track_hand(slicelab.clean_slice(m7, p), CX, CY, p)
        return slicelab.label_geometry(geo, p, log=lambda m: None)

    def test_both_hands_label_every_turn(self):
        for hand in (1, -1):
            R = self.label(spiral_slice(hand), params())
            g = R["geo"]
            self.assertEqual(g["hand"], hand)
            self.assertGreater(np.isfinite(R["label"]).mean(), 0.95)
            self.assertGreater(e0(R["label"], true_turn(g)), 0.99, f"hand {hand}")

    def test_missed_sheet_and_gaps(self):
        # one turn missing over a quarter turn, and holes: the asymmetric radial costs let the step of 2 there
        R = self.label(spiral_slice(-1, drop=(9, 1.0, 2.6), gaps=25, seed=4), params())
        self.assertGreater(e0(R["label"], true_turn(R["geo"])), 0.97)

    def test_naive_count_fails_where_the_solve_does_not(self):
        # the check can fail: counting sheets on the straight ray from the axis (slicelab.naive_counts) loses a
        # turn behind every hole and missed sheet, so it scores far below the solve on the same slice
        m7 = spiral_slice(-1, drop=(9, 1.0, 2.6), gaps=25, seed=4)
        p = params()
        R = self.label(m7, p)
        g = R["geo"]
        naive = slicelab.naive_counts(slicelab.clean_slice(m7, p), g["ys"], g["xs"], CX, CY, p["r_min"])
        self.assertLess(e0(naive.astype(float), true_turn(g)), 0.8)
        self.assertGreater(e0(R["label"], true_turn(g)), 0.97)

    def test_stack_solve(self):
        p = dict(params(), **slab3d.ZPARAMS)
        geos = []
        for i, dx in enumerate((0.0, 0.4, 0.8)):
            m7 = spiral_slice(1, dx=dx, drop=(6, 2.0, 3.0) if i == 1 else None)
            g = slicelab.geometry(m7, CX, CY, p, log=lambda m: None)
            g["track"] = slicelab.track_hand(slicelab.clean_slice(m7, p), CX, CY, p)
            geos.append((i, g))
        lab, comp, info, base, gs = slab3d.label_stack(geos, p, lambda z: geos[z][1]["track"])
        self.assertEqual(info["status"], 0)
        self.assertGreater(info["z_edges"], 0)
        L = np.concatenate([lab[b0:b1][g["pid"]] for (z, g), b0, b1 in zip(gs, base[:-1], base[1:])])
        k = np.concatenate([true_turn(g) for _, g in gs])
        self.assertGreater(e0(L, k), 0.99)       # one offset across all three slices


if __name__ == "__main__":
    unittest.main()
