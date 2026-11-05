"""scripts/autocrop/autocrop.py: the crop rule, its controls and readout, on generated data only.

The rule's pure parts (ranks, smoothing, top half, components, point collections, the shifted control, random
crops, the shuffled-signals control and the readout bars) need numpy only. The signals and the synthetic demo also
need scipy, tifffile, zarr and spiralfiteval (github.com/jo-tud/spiralfiteval, commit 217947a); those tests skip
without them.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "autocrop" / "autocrop.py"
sys.path.insert(0, str(SCRIPT.parent))

try:
    import numpy as np
    import autocrop as ac
except ImportError:          # pragma: no cover
    ac = None

try:
    import scipy  # noqa: F401
    import tifffile  # noqa: F401
    import zarr  # noqa: F401
    from spiralfiteval import fit as _sf
    HAVE_ALL = True
except ImportError:          # pragma: no cover
    HAVE_ALL = False


@unittest.skipIf(ac is None, "numpy is not installed")
class RuleTests(unittest.TestCase):
    def test_ranks_direction_and_missing(self):
        r = ac.ranks({"a": 1.0, "b": 2.0, "c": float("nan"), "d": 3.0}, True)
        self.assertEqual(set(r), {"a", "b", "d"})
        self.assertEqual(r["d"], 1.0)
        self.assertEqual(r["a"], 0.0)
        r = ac.ranks({"a": 1.0, "b": 2.0, "d": 3.0}, False)
        self.assertEqual(r["a"], 1.0)

    def test_average_ranks_share_ties(self):
        self.assertEqual(ac.average_ranks([3.0, 1.0, 3.0, 2.0]).tolist(), [3.5, 1.0, 3.5, 2.0])
        try:
            from scipy.stats import rankdata
        except ImportError:
            return
        v = np.random.default_rng(3).integers(0, 9, 200).astype(float)
        self.assertTrue(np.array_equal(ac.average_ranks(v), rankdata(v, method="average")))

    def test_scores_combined_and_smoothing(self):
        sig = {(1, 0, 0): {"seed": 1.0, "normal": 1.0, "spacing": 0.0, "regularity": 0.0},
               (1, 0, 1): {"seed": 0.0, "normal": 0.0, "spacing": 1.0, "regularity": 1.0},
               (2, 0, 0): {"seed": 0.5, "normal": 0.5, "spacing": 0.5, "regularity": 0.5}}
        sc = ac.scores(sig)
        self.assertEqual(sc["combined"][(1, 0, 0)], 1.0)
        self.assertEqual(sc["combined"][(1, 0, 1)], 0.0)
        self.assertEqual(sc["smooth"][(1, 0, 0)], 0.5)            # its own and its neighbor on winding 1
        self.assertEqual(sc["smooth"][(2, 0, 0)], 0.5)            # alone on winding 2

    def test_keep_top_share_and_ties(self):
        zone = [(1, 0, i) for i in range(4)]
        kept = ac.keep_top({zone[0]: 0.1, zone[1]: 0.9, zone[2]: 0.9}, zone, 0.5)
        self.assertEqual(kept, {zone[1], zone[2]})
        self.assertEqual(ac.keep_top({}, zone, 0.5), {zone[0], zone[1]})


@unittest.skipIf(ac is None, "numpy is not installed")
class OutcomeTests(unittest.TestCase):
    def make(self, n=400, seed=1):
        rng = np.random.default_rng(seed)
        zone = [(1, 0, i) for i in range(40)]
        ca = [zone[i] for i in rng.integers(0, 40, n)]
        cb = [zone[i] for i in rng.integers(0, 40, n)]
        good = set(zone[:20])
        exact = np.array([(a in good and b in good) or rng.random() < 0.3 for a, b in zip(ca, cb)])
        dw = rng.integers(1, 7, n)
        return zone, ca, cb, good, exact, dw

    def test_rule_on_good_cells_beats_random_crops(self):
        zone, ca, cb, good, exact, dw = self.make()
        inside, n, E = ac.outcome(exact, ca, cb, good)
        rnd = ac.random_crops(exact, ca, cb, zone, len(good), dw, draws=200)
        self.assertEqual(E, 1.0)
        self.assertGreater(E, rnd["p975"])
        self.assertAlmostEqual(ac.dw_standardized(exact, inside, dw, np.array(rnd["dw_mix"])), 1.0)

    def test_bad_cells_do_not_beat_random_crops(self):
        zone, ca, cb, good, exact, dw = self.make()
        bad = set(zone[20:])
        _, _, E = ac.outcome(exact, ca, cb, bad)
        self.assertLess(E, ac.random_crops(exact, ca, cb, zone, len(bad), dw, draws=200)["mean"])

    def test_random_crops_deterministic(self):
        zone, ca, cb, good, exact, dw = self.make()
        self.assertEqual(ac.random_crops(exact, ca, cb, zone, 20, dw, draws=50, seed=0),
                         ac.random_crops(exact, ca, cb, zone, 20, dw, draws=50, seed=0))


def table(rng, good_signal=True, n=3000):
    """A crops file and pair table: 2 windings of 20 by 10 cells; pairs inside the left half of each winding are
    right, others right 40 % of the time. With good_signal the signals say so; without, they are noise."""
    cells = [(w, r, c) for w in (5, 6) for r in range(20) for c in range(10)]
    good = {c for c in cells if c[2] < 5}
    sig = {}
    for c in cells:
        q = (1.0 if c in good else 0.0) if good_signal else rng.random()
        sig[ac.cell_key(c)] = {"seed": q + 0.1 * rng.random(), "normal": q + 0.1 * rng.random(),
                               "spacing": 1 - q + 0.1 * rng.random(), "regularity": 1 - q + 0.1 * rng.random()}
    ia, ib = rng.integers(0, len(cells), n), rng.integers(0, len(cells), n)
    ca, cb = [cells[i] for i in ia], [cells[i] for i in ib]
    exact = [int((a in good and b in good) or rng.random() < 0.4) for a, b in zip(ca, cb)]
    crops = {"fit": "T", "signals": sig, "kept": []}
    pairs = {"cell_a": [list(c) for c in ca], "cell_b": [list(c) for c in cb], "exact": exact,
             "dw": rng.integers(1, 7, n).tolist()}
    return crops, pairs


@unittest.skipIf(ac is None, "numpy is not installed")
class ScoreTests(unittest.TestCase):
    def test_good_signals_beat_both_controls(self):
        crops, pairs = table(np.random.default_rng(0))
        r = ac.score_fit(crops, pairs, draws=100, shuffles=10)
        m = r["rules"]["main"]
        self.assertTrue(m["above_p975"])
        self.assertGreater(m["G_rand"], 0.2)
        self.assertLess(abs(r["shuffled"]["shuffled_minus_rand"]), 0.02)
        out = ac.readout({"A": r, "B": ac.score_fit(*table(np.random.default_rng(1)), draws=100, shuffles=10)})
        self.assertEqual(out["verdict"], "BEATS_CONTROL")

    def test_noise_signals_do_not_pass(self):
        recs = {k: ac.score_fit(*table(np.random.default_rng(k), good_signal=False), draws=100, shuffles=10)
                for k in range(3)}
        self.assertIn(ac.readout(recs)["verdict"], ("NO_GAIN", "WEAK"))

    def test_missing_cells_refused(self):
        crops, pairs = table(np.random.default_rng(0))
        del crops["signals"]["5,0,0"]
        with self.assertRaises(ac.CropError):
            ac.score_fit(crops, pairs, draws=10, shuffles=2)

    def test_readout_void_on_shuffled_control_and_few_pairs(self):
        crops, pairs = table(np.random.default_rng(0))
        r = ac.score_fit(crops, pairs, draws=50, shuffles=5)
        r["shuffled"]["shuffled_minus_rand"] = 0.03
        out = ac.readout({"A": r})
        self.assertEqual(out["verdict"], "VOID")
        self.assertIn("shuffled control", out["why"][0])
        r["rules"]["main"]["kept_pairs"] = 10
        self.assertEqual(ac.readout({"A": r})["why"], ["no fit has enough kept pairs"])


@unittest.skipIf(ac is None, "numpy is not installed")
class GridTests(unittest.TestCase):
    def grids(self):
        P = np.zeros((8, 32, 3), np.float32)
        for i in range(8):
            for j in range(32):
                P[i, j] = (j * 20.0, 5.0, i * 20.0)
        valid = np.ones((8, 32), bool)
        valid[4:8, 24:32] = False
        return {250: (P, valid)}

    def test_regularity_flags_a_stretched_vertex(self):
        P = np.zeros((6, 6, 3), np.float32)
        for i in range(6):
            for j in range(6):
                P[i, j] = (j * 20.0, 0.0, i * 20.0)
        P[3, 4, 0] += 40.0
        v = ac.regularity(P, np.ones((6, 6), bool), np.array([1, 3]), np.array([1, 4]))
        self.assertAlmostEqual(v[0], 0.0, places=6)
        self.assertGreater(v[1], 0.5)

    def test_radius_at_wraps_angle(self):
        th = np.linspace(-np.pi, np.pi, 9)[:-1]
        prof = [(th, np.full(len(th), 100.0))]
        self.assertAlmostEqual(ac.radius_at(prof, 0, 3.1), 100.0)
        self.assertTrue(np.isnan(ac.radius_at(prof, 5, 0.0)))

    def test_components_four_connected_and_min_size(self):
        kept = {(250, 0, 0), (250, 0, 1), (250, 1, 1), (250, 1, 2), (250, 0, 3), (251, 0, 0)}
        self.assertEqual(ac.components(kept), [[(250, 0, 0), (250, 0, 1), (250, 1, 1), (250, 1, 2)]])
        self.assertEqual(len(ac.components(kept, min_cells=1)), 3)
        self.assertEqual(ac.components({(250, 0, 0), (250, 1, 1), (250, 2, 2), (250, 3, 3)}), [])

    def test_cell_point_is_a_valid_vertex_near_the_center(self):
        g = self.grids()
        p = ac.cell_point(g, (250, 0, 1))
        self.assertIn(p[0], (220.0, 240.0))
        self.assertIn(p[2], (20.0, 40.0))
        self.assertIsNone(ac.cell_point(g, (250, 1, 3)))

    def test_shifted_keeps_shape_and_winding_and_moves(self):
        g = self.grids()
        comp = [[(250, 0, 0), (250, 0, 1), (250, 1, 0), (250, 1, 1)]]
        a = ac.shifted(comp, g, seed=0)
        self.assertEqual(a, ac.shifted(comp, g, seed=0))
        self.assertTrue(all(c[0] == 250 for c in a[0]))
        self.assertNotEqual(a[0], comp[0])
        moves = [k for k in (1, 2, 3) if a[0] == sorted((w, r, (c + k) % 4) for w, r, c in comp[0])]
        self.assertEqual(len(moves), 1)

    def test_crop_collections_same_winding_relative_points(self):
        g = self.grids()
        comps = [[(250, 0, 0), (250, 0, 1), (250, 1, 0), (250, 1, 1)],
                 [(250, 1, 2), (250, 1, 3), (250, 0, 2), (250, 0, 3)]]
        doc, n = ac.crop_collections(comps, g, "crop")
        self.assertEqual(n, 4)            # the second keeps 3 points (a cell with no valid vertex): dropped
        col = doc["collections"]["1"]
        self.assertIs(col["metadata"]["winding_is_absolute"], False)
        self.assertEqual({q["wind_a"] for q in col["points"].values()}, {0.0})
        self.assertEqual(doc["vc_pointcollections_json_version"], "1")

    def test_axis_from_villa_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "u.json"
            p.write_text(json.dumps({"control_points": [{"x": 0, "y": 0, "z": 0}, {"x": 10, "y": 20, "z": 10}]}))
            x, y = ac.Axis.from_json(p).at([5.0])
            self.assertEqual((float(x[0]), float(y[0])), (5.0, 10.0))
            p.write_text(json.dumps([[1, 1, 0]]))
            with self.assertRaises(ac.CropError):
                ac.Axis.from_json(p)


@unittest.skipUnless(ac is not None and HAVE_ALL, "needs numpy, scipy, tifffile, zarr and spiralfiteval")
class FitTests(unittest.TestCase):
    def test_same_fit_as_spiralfiteval_build_fit(self):
        g = {}
        for w in range(10, 14):
            th = np.linspace(0, 2 * np.pi, 24, endpoint=False)
            P = np.zeros((9, 24, 3), np.float32)
            for i in range(9):
                P[i, :, 0] = (100.0 + 15.0 * w) * np.cos(th)
                P[i, :, 1] = (100.0 + 15.0 * w) * np.sin(th)
                P[i, :, 2] = 20.0 * i
            valid = np.ones((9, 24), bool)
            valid[0, :3] = False
            g[w] = (P, valid)
        for bbox in (None, ((-400.0, -400.0, 0.0), (0.0, 400.0, 100.0))):
            ref = _sf.build_fit(g, name="t", column_sense=1, bbox_xyz=bbox)
            fit, cells = ac.build_fit_cells(g, "t", bbox, 1)
            self.assertTrue(np.array_equal(ref.xyz, fit.xyz))
            self.assertTrue(np.array_equal(ref.f, fit.f))
            self.assertEqual(len(cells), len(fit.xyz))

    def test_demo_drops_the_planted_patch(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(SCRIPT), "demo", "--out-dir", str(Path(d) / "demo")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            res = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(res["check"], "PASS")
            self.assertLessEqual(res["planted_kept_share"], 0.5 * res["other_kept_share"])
            crop = json.loads((Path(d) / "demo" / "crops" / "relative_windings_crop_fitA.json").read_text())
            self.assertTrue(crop["collections"])
            r = subprocess.run([sys.executable, str(SCRIPT), "demo", "--out-dir", str(Path(d) / "demo")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn("exists and is not empty", r.stderr)

    def test_crops_refuses_windings_outside_the_fit(self):
        with tempfile.TemporaryDirectory() as d:
            rng = np.random.default_rng(0)
            ac.write_demo_fit(Path(d) / "a", rng, 0.3, bad=False)
            with self.assertRaises(ac.CropError):
                ac.run_crops(Path(d) / "a", Path(d) / "a", Path(d), (40, 41), Path(d) / "o", log=lambda s: None)
            with self.assertRaises(ac.CropError):
                ac.export_grids(Path(d))


if __name__ == "__main__":
    unittest.main()
