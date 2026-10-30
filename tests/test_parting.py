"""Tests for Parting (scripts/parting/), on synthetic data only: no scan, no network, no model download."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts" / "parting"))

try:
    import numpy as np
except ImportError:          # the map tools' dependencies are optional for the repository's tests
    np = None
try:
    import scipy  # noqa: F401
except ImportError:
    scipy = None


@unittest.skipIf(np is None, "needs numpy")
class AucTest(unittest.TestCase):
    def test_auc_counts_ties_half_and_matches_the_sorting_form(self):
        import partmodel as M
        rng = np.random.default_rng(0)
        same = rng.integers(0, 5, 40).astype(float)
        cross = rng.integers(0, 5, 30).astype(float)
        brute = np.mean([(s > c) + 0.5 * (s == c) for s in same for c in cross])
        self.assertAlmostEqual(M.auc(same, cross), brute, places=12)
        self.assertAlmostEqual(M.fast_auc(same, cross), brute, places=12)

    def test_auc_of_separated_scores(self):
        import partmodel as M
        self.assertEqual(M.auc([2, 3], [0, 1]), 1.0)
        self.assertEqual(M.auc([0, 1], [2, 3]), 0.0)


def synthetic_run(n=6, seed=0):
    rng = np.random.default_rng(seed)
    F = {"tok": rng.normal(size=(n, 3, 288)).astype(np.float32),
         "ct_n": rng.normal(size=(n, 3, 17)).astype(np.float32),
         "ct_seg": rng.normal(size=(n, 2, 16)).astype(np.float32),
         "p_tok": rng.uniform(-1, 1, size=(n, 2, 2, 16)).astype(np.float32)}
    rows = [{"id": i, "pair": f"L{i % 2}-L{i % 2 + 1}", "stratum": "touching",
             "scores": {"dino_base": [float(rng.uniform()), float(rng.uniform())],
                        "ct_valley": [float(rng.uniform()), float(rng.uniform())]}} for i in range(n)]
    return rows, F


@unittest.skipIf(np is None, "needs numpy")
class RowsTest(unittest.TestCase):
    def test_design_has_the_released_layout(self):
        import partmodel as M
        rows, F = synthetic_run()
        X, y, grp, strat, ctrl = M.design(rows, F)
        self.assertEqual(X.shape, (12, M.COLUMNS))
        self.assertEqual(list(y[:4]), [1, 0, 1, 0])
        self.assertEqual(ctrl[1], rows[0]["scores"]["dino_base"][1])

    def test_rows_do_not_depend_on_the_sign_of_a_normal(self):
        import partmodel as M
        rows, F = synthetic_run()
        G = dict(F, ct_n=F["ct_n"][..., ::-1].copy())     # every normal flipped: each profile runs the other way
        np.testing.assert_allclose(M.design(rows, F)[0], M.design(rows, G)[0], atol=1e-6)


@unittest.skipIf(np is None, "needs numpy")
class ResampleTest(unittest.TestCase):
    def test_box_weights_sum_to_one(self):
        import partct
        for ratio in (1.0, 2.0, 7.91 / 3.24):
            i0, w = partct.box_weights(37, 128, ratio)
            np.testing.assert_allclose(w.sum(1), 1.0, atol=1e-9)
            self.assertTrue((w >= 0).all())

    def test_resampled_shape_of_a_3_24_um_array_at_7_91_um(self):
        import partct
        self.assertEqual(partct.resampled_shape((6656, 1440, 6312), 7.91 / 3.24), [2727, 590, 2586])

    def test_a_constant_volume_stays_constant(self):
        import partct

        class Flat:
            shape = (1000, 1000, 1000)
            url = "synthetic"

            def read(self, lo, size):
                return np.full(tuple(size), 77, np.uint8)

        rw = partct.ResampledWindow.__new__(partct.ResampledWindow)
        rw.src_um, rw.dst_um, rw.ratio, rw.src, rw.url = 3.24, 7.91, 7.91 / 3.24, Flat(), "synthetic"
        out = rw.read((5, 6, 7), 16)
        self.assertEqual(out.shape, (16, 16, 16))
        self.assertTrue((out == 77).all())

    def test_parse_resample_refuses_a_finer_target(self):
        import partct
        self.assertEqual(partct.parse_resample("3.24:7.91"), (3.24, 7.91))
        self.assertIsNone(partct.parse_resample(None))
        with self.assertRaises(SystemExit):
            partct.parse_resample("7.91:3.24")


@unittest.skipIf(np is None, "needs numpy")
class GateTest(unittest.TestCase):
    def scored(self, sites=120, pairs=5, gain=True, seed=1):
        rng = np.random.default_rng(seed)
        n = 2 * sites
        y = np.tile([1, 0], sites)
        grp = np.repeat([f"P{i % pairs}" for i in range(sites)], 2)
        ctrl = rng.normal(size=n) + 0.6 * y
        s = ctrl + (1.5 * y if gain else 0.0)
        strat = np.array(["touching"] * n)
        apart = np.array(["apart"] * 40)
        ya = np.tile([1, 0], 20)
        ga = np.repeat([f"P{i % pairs}" for i in range(20)], 2)
        ca = 5.0 * ya + rng.normal(size=40) * 0.1
        return (np.concatenate([s, ca]), np.concatenate([y, ya]), np.concatenate([grp, ga]),
                np.concatenate([strat, apart]), np.concatenate([ctrl, ca]))

    def test_a_clear_gain_passes(self):
        import partmodel as M
        s, y, grp, strat, ctrl = self.scored()
        doc = M.readout(None, s, y, grp, strat, ctrl, boot=500, permutations=200)
        self.assertEqual(doc["verdict"], "PASS", doc)

    def test_no_gain_over_the_control_fails(self):
        import partmodel as M
        s, y, grp, strat, ctrl = self.scored(gain=False)
        doc = M.readout(None, s, y, grp, strat, ctrl, boot=500, permutations=200)
        self.assertEqual(doc["verdict"], "FAIL", doc)

    def test_too_few_sites_is_void(self):
        import partmodel as M
        s, y, grp, strat, ctrl = self.scored(sites=40)
        doc = M.readout(None, s, y, grp, strat, ctrl, boot=200, permutations=100)
        self.assertEqual(doc["verdict"], "VOID")

    def test_the_permutation_gate_sits_near_one_half(self):
        import partmodel as M
        rng = np.random.default_rng(3)
        ok, mean, half = M.perm_gate(rng.normal(size=300), np.tile([1, 0], 150), k=300)
        self.assertTrue(ok)
        self.assertLess(abs(mean - 0.5), 0.02)


@unittest.skipIf(np is None, "needs numpy")
class ModelFileTest(unittest.TestCase):
    def test_an_unknown_model_file_is_refused_before_it_is_unpickled(self):
        import partmodel as M
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "other.joblib"
            p.write_bytes(b"not a released model")
            with self.assertRaises(SystemExit) as cm:
                M.load_model(p)
            self.assertIn("--trust-model", str(cm.exception))


@unittest.skipIf(np is None or scipy is None, "needs numpy and scipy")
class SitesTest(unittest.TestCase):
    def planes(self, gap):
        z, x = np.meshgrid(np.arange(100, 400, 4.0), np.arange(100, 400, 4.0), indexing="ij")
        lower = np.stack([x, np.full_like(x, 200.0), z], -1)
        upper = np.stack([x, np.full_like(x, 200.0 + gap), z], -1)
        return {"L0": lower, "L1": upper}

    def test_two_layers_five_voxels_apart_give_touching_sites(self):
        import partgeom as G
        rule = G.Rule(seed=7, dense=2, caps={"touching": 5, "apart": 5, "fused": 5, "mixed": 5})
        sites = G.make_sites(self.planes(5.0), (500, 500, 500), rule)
        self.assertTrue(sites)
        self.assertEqual({s["stratum"] for s in sites}, {"touching"})
        for s in sites:
            self.assertAlmostEqual(s["gap_a"], 5.0, places=1)
            self.assertAlmostEqual(s["dist"], s["dist_same"], delta=1.0)    # matched distance

    def test_the_site_hash_ignores_key_order(self):
        import partgeom as G
        a = [{"id": 0, "pair": "L0-L1", "a": [1, 2, 3]}]
        b = [{"a": [1, 2, 3], "pair": "L0-L1", "id": 0}]
        self.assertEqual(G.sites_sha256(a), G.sites_sha256(b))

    def test_crossings_are_reported_and_an_unordered_stack_is_refused(self):
        import partgeom as G
        g = self.planes(5.0)
        report, cross = G.stack_layers(g, min_matched=10)
        self.assertEqual(len(cross), 0)
        with self.assertRaises(ValueError):
            G.stack_layers({"L0": g["L1"], "L1": g["L0"]}, min_matched=10)


@unittest.skipIf(np is None, "needs numpy")
class FeatureTest(unittest.TestCase):
    def test_site_features_have_the_stored_shapes(self):
        import partfeat as FE
        rng = np.random.default_rng(0)
        site = {"id": 0, "pair": "L0-L1", "stratum": "touching", "centre": [64, 64, 64],
                "a": [60.0, 64.0, 64.0], "a2": [70.0, 64.0, 64.0], "b": [64.0, 70.0, 64.0],
                "n_a": [0, 1, 0], "n_a2": [0, 1, 0], "n_b": [0, 1, 0]}
        ct = rng.integers(0, 255, (128, 128, 128)).astype(np.uint8)
        tokens = np.ones((288, 16, 16, 16), np.float32)
        f, sc = FE.site_features(site, ct, tokens)
        for k, shape in FE.GROUPS.items():
            self.assertEqual(f[k].shape, shape, k)
        self.assertAlmostEqual(sc["dino_base"][0], 1.0, places=6)       # constant tokens: cosine 1
        with tempfile.TemporaryDirectory() as td:
            FE.save_run(td, [site], {0: f}, {0: sc}, {"kind": "test"})
            feats, scores = FE.load_done(td)
            self.assertEqual(sorted(feats), [0])
            self.assertEqual(json.loads((Path(td) / "run.json").read_text())["kind"], "test")


if __name__ == "__main__":
    unittest.main()
