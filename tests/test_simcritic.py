import unittest

try:
    import numpy as np
    import scipy  # noqa: F401
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False

try:
    import torch  # noqa: F401
    HAVE_TORCH = True
except ImportError:  # pragma: no cover
    HAVE_TORCH = False


def texture(rng, n, size=64, sigma=2.0, noise=0.0):
    from scipy import ndimage as nd
    out = []
    for _ in range(n):
        w = nd.gaussian_filter(rng.standard_normal((size, size)), sigma)
        out.append(w + noise * rng.standard_normal((size, size)))
    return out


@unittest.skipUnless(HAVE, "numpy and scipy needed")
class SimCriticTest(unittest.TestCase):
    def setUp(self):
        from kit import simcritic
        self.sc = simcritic

    def test_auc_known(self):
        self.assertEqual(self.sc.auc([1, 2, 3, 4], [0, 0, 1, 1]), 1.0)
        self.assertEqual(self.sc.auc([4, 3, 2, 1], [0, 0, 1, 1]), 0.0)
        self.assertEqual(self.sc.auc([1, 1, 1, 1], [0, 1, 0, 1]), 0.5)
        with self.assertRaises(self.sc.CriticError):
            self.sc.auc([1, 2], [1, 1])

    def test_grid_windows_groups_and_mask(self):
        imgs = [np.arange(64 * 96, dtype=float).reshape(64, 96), np.ones((40, 40))]
        W, g = self.sc.grid_windows(imgs, 32)
        self.assertEqual(W.shape, (6 + 1, 32, 32))
        self.assertEqual(g.tolist(), [0] * 6 + [1])
        m = [np.zeros((64, 96), bool), np.ones((40, 40), bool)]
        m[0][:32, :32] = True
        W, g = self.sc.grid_windows(imgs, 32, masks=m)
        self.assertEqual(g.tolist(), [0, 1])
        H, gh = self.sc.half(imgs, win=16)
        self.assertEqual(H.shape[1:], (16, 16))
        self.assertEqual(gh.tolist(), [0] * 6 + [1])

    def test_folds_keep_groups_whole(self):
        groups = np.repeat(np.arange(9), 5)
        f = self.sc.folds_of(groups, 3, seed=4)
        for gg in range(9):
            self.assertEqual(len(set(f[groups == gg])), 1)
        self.assertEqual(sorted(set(f.tolist())), [0, 1, 2])
        with self.assertRaises(self.sc.CriticError):
            self.sc.folds_of(np.zeros(5), 3, 0)

    def test_views_shapes_and_effects(self):
        rng = np.random.default_rng(0)
        X = np.stack([self.sc.unit(w) for w in texture(rng, 4, 32)]).astype(np.float32)
        ref = self.sc.pooled_amplitude(X)
        for v in self.sc.VIEWS:
            Y = self.sc.view(X, v, ref, seed=1)
            self.assertEqual(Y.shape, X.shape, v)
            self.assertTrue(np.isfinite(Y).all(), v)
        M = self.sc.view(X, "marginal")
        self.assertTrue(np.allclose(np.sort(M[0].ravel()), np.sort(M[1].ravel())))
        with self.assertRaises(self.sc.CriticError):
            self.sc.view(X, "whiten")
        with self.assertRaises(self.sc.CriticError):
            self.sc.view(X, "nope")

    def test_feat_critic_can_fail_and_pass(self):
        rng = np.random.default_rng(1)
        A = np.stack([self.sc.unit(w) for w in texture(rng, 40, 48)]).astype(np.float32)
        same = np.stack([self.sc.unit(w) for w in texture(rng, 40, 48)]).astype(np.float32)
        other = np.stack([self.sc.unit(w) for w in texture(rng, 40, 48, sigma=1.0, noise=0.3)]).astype(np.float32)
        g = np.arange(40)
        hi = self.sc.critic_auc(A, g, other, g, "feat", folds=3, seed=0)["auc"]
        lo = self.sc.critic_auc(A, g, same, g, "feat", folds=3, seed=0)["auc"]
        self.assertGreater(hi, 0.95)
        self.assertLess(abs(lo - 0.5), 0.2)

    def test_judge_refuses_trained_groups(self):
        rng = np.random.default_rng(2)
        A = np.stack([self.sc.unit(w) for w in texture(rng, 9, 32)]).astype(np.float32)
        g = np.arange(9)
        with self.assertRaises(self.sc.CriticError):
            self.sc.judge(A, g, A, g, critics=("feat",), trained_on=(3,), progress=lambda *_: None)

    def test_judge_and_verdict(self):
        rng = np.random.default_rng(3)
        A = np.stack([self.sc.unit(w) for w in texture(rng, 30, 48)]).astype(np.float32)
        B = np.stack([self.sc.unit(w) for w in texture(rng, 30, 48, sigma=1.0, noise=0.3)]).astype(np.float32)
        g = np.arange(30)
        r = self.sc.judge(A, g, B, g, critics=("feat",), seeds=(0,), progress=lambda *_: None)
        self.assertEqual(r["worst_critic"], "feat")
        self.assertEqual(len(r["digest_real"]), 64)
        c = {"worst": 0.52}
        self.assertEqual(self.sc.verdict(r, c)["verdict"], "FAIL")
        self.assertEqual(self.sc.verdict({"worst": 0.55}, c)["verdict"], "PASS")
        self.assertEqual(self.sc.verdict({"worst": 0.58}, c)["verdict"], "FAIL")
        self.assertEqual(self.sc.verdict({"worst": 0.62}, {"worst": 0.60})["verdict"], "FAIL")
        self.assertEqual(self.sc.verdict({"worst": 0.61234567}, {"worst": 0.5})["gap_to_bar"], 0.0623)
        self.assertIsNone(self.sc.verdict({"worst": None}, c)["gap_to_bar"])

    def test_sink_sees_each_item(self):
        rng = np.random.default_rng(6)
        A = np.stack([self.sc.unit(w) for w in texture(rng, 9, 32)]).astype(np.float32)
        g = np.arange(9)
        seen = []
        self.sc.judge(A, g, A, g, critics=("feat",), seeds=(0,), progress=lambda *_: None,
                      sink=lambda r: seen.append(sorted(r["critics"])))
        self.assertEqual(seen, [["feat"]])

    def test_merge_equals_one_call(self):
        rng = np.random.default_rng(5)
        A = np.stack([self.sc.unit(w) for w in texture(rng, 18, 32)]).astype(np.float32)
        B = np.stack([self.sc.unit(w) for w in texture(rng, 18, 32, sigma=1.0, noise=0.2)]).astype(np.float32)
        g = np.arange(18)
        q = dict(critics=("feat",), progress=lambda *_: None)
        one = self.sc.judge(A, g, B, g, seeds=(0, 1), **q)
        m = self.sc.merge([self.sc.judge(A, g, B, g, seeds=(0,), **q), self.sc.judge(A, g, B, g, seeds=(1,), **q)])
        self.assertAlmostEqual(one["critics"]["feat"]["auc"], m["critics"]["feat"]["auc"])
        self.assertEqual(m["seeds"], [0, 1])
        self.assertEqual(one["worst"], m["worst"])
        other = self.sc.judge(A[:9], g[:9], B, g, seeds=(1,), **q)
        with self.assertRaises(self.sc.CriticError):
            self.sc.merge([one, other])

    @unittest.skipUnless(HAVE_TORCH, "torch needed")
    def test_cnn_critic_runs(self):
        rng = np.random.default_rng(4)
        A = np.stack([self.sc.unit(w) for w in texture(rng, 12, 32)]).astype(np.float32)
        B = np.stack([self.sc.unit(w) for w in texture(rng, 12, 32, sigma=0.7, noise=0.5)]).astype(np.float32)
        g = np.arange(12)
        r = self.sc.critic_auc(A, g, B, g, "cnn", folds=2, seed=0, steps=30)
        self.assertTrue(0.0 <= r["auc"] <= 1.0)
        self.assertEqual(len(r["per_fold"]), 2)


if __name__ == "__main__":
    unittest.main()
