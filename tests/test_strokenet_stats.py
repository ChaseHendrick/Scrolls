"""Tests for StrokeNet's metrics and baselines (scripts/strokenet/metrics.py, baselines.py).
numpy is needed; the scipy comparisons and the random-CNN baseline skip without scipy or torch."""
import itertools
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts" / "strokenet"

try:
    import numpy as np
    sys.path.insert(0, str(SCRIPTS))
    import baselines as BL
    import metrics as M
except ImportError:  # the core kit is standard library only
    np = BL = M = None
try:
    import torch
    sys.path.insert(0, str(SCRIPTS))
    import train as T
    torch.set_num_threads(2)
except ImportError:
    torch = T = None
try:
    from scipy import optimize, stats
except ImportError:
    optimize = stats = None
finally:
    while str(SCRIPTS) in sys.path:
        sys.path.remove(str(SCRIPTS))


def brute_auc(pos, neg):
    return float(np.mean([(p > n) + 0.5 * (p == n) for p in pos for n in neg]))


def platt_loss(a, b, z, y, w):
    """Weighted mean log loss of sigmoid(a z + b) against Platt's smoothed targets."""
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    t = np.where(y == 1, (n_pos + 1.0) / (n_pos + 2.0), 1.0 / (n_neg + 2.0))
    u = a * z + b
    w = w / w.sum()
    return float(w @ (t * np.logaddexp(0, -u) + (1 - t) * np.logaddexp(0, u)))


def review_mixture(rng):
    """Logits shaped like the 14 Oct review's example, where the old plain Newton diverged."""
    z = np.r_[rng.normal(6, 3, 4780), rng.normal(-15, 4, 2057), rng.normal(-3, 4, 4780),
              rng.normal(-5, 4, 4780), rng.normal(-6, 5, 4780)]
    y = np.r_[np.ones(4780), np.zeros(2057 + 3 * 4780)]
    return z, y


def numpy_iaaft(x, rng, iters=5):
    """A small IAAFT (value-keeping rank remap) for one float window: a permutation of x."""
    vals = np.sort(x.ravel())
    amp = np.abs(np.fft.rfft2(x))
    y = x.ravel()[rng.permutation(x.size)]
    for _ in range(iters):
        ph = np.angle(np.fft.rfft2(y.reshape(x.shape)))
        z = np.fft.irfft2(amp * np.exp(1j * ph), s=x.shape).ravel()
        y = np.empty_like(vals)
        y[np.argsort(z, kind="stable")] = vals
    return y.reshape(x.shape)


def text_like(rng, n, size=128, horizontal=True):
    """uint8 windows with horizontal (or vertical) bright bands and noise."""
    yy = np.arange(size)[:, None] + np.zeros((1, size))
    phase = rng.integers(0, 40, n)[:, None, None]
    w = ((yy[None] + phase) % 40 < 15) * 120.0 + 60 + rng.normal(0, 12, (n, size, size))
    w = np.clip(np.rint(w), 0, 255).astype(np.uint8)
    return w if horizontal else np.ascontiguousarray(np.rot90(w, 1, axes=(1, 2)))


# ------------------------------------------------------------------ metrics
@unittest.skipIf(M is None, "numpy not installed")
class MetricsTest(unittest.TestCase):
    def test_auc_with_ties_matches_brute_force(self):
        rng = np.random.default_rng(0)
        for _ in range(20):
            pos = rng.integers(0, 6, rng.integers(1, 15)).astype(float)
            neg = rng.integers(0, 6, rng.integers(1, 15)).astype(float)
            self.assertAlmostEqual(M.auc(pos, neg), brute_auc(pos, neg), places=12)
        self.assertTrue(np.isnan(M.auc([], [1.0])))
        self.assertEqual(M.paired_frac([2, 1, 3], [1, 1, 4]), 1 / 3)

    def test_average_precision(self):
        self.assertAlmostEqual(M.average_precision([3, 2], [1, 0]), 1.0)
        self.assertAlmostEqual(M.average_precision([1], [2]), 0.5)
        self.assertAlmostEqual(M.ap_at(np.arange(100) + 200.0, np.arange(100) * 1.0, 0.10, 5), 1.0)
        self.assertLess(M.ap_at(np.arange(100) + 50.0, np.arange(100) * 1.0, 0.10, 5), 0.9)

    def test_platt_recovers_parameters(self):
        rng = np.random.default_rng(1)
        x = rng.normal(0, 2, 20000)
        y = (rng.random(20000) < M.sigmoid(0.7 * x - 0.3)).astype(float)
        a, b = M.platt_fit(x, y)
        self.assertAlmostEqual(a, 0.7, delta=0.05)
        self.assertAlmostEqual(b, -0.3, delta=0.05)

    def test_platt_converges_on_wide_logits(self):
        # the old plain Newton from (1, 0) diverged here (a about 1e13); the optimum is near
        # (0.76, -2.16)
        z, y = review_mixture(np.random.default_rng(2))
        a, b = M.platt_fit(z, y)
        self.assertAlmostEqual(a, 0.763, delta=0.03)
        self.assertAlmostEqual(b, -2.158, delta=0.1)
        for sd in (5.0, 8.0, 20.0):
            rng = np.random.default_rng(int(sd))
            x = rng.normal(0, sd, 5000)
            y = (rng.random(5000) < M.sigmoid(0.4 * x - 0.3)).astype(float)
            a, b = M.platt_fit(x, y)
            self.assertAlmostEqual(a, 0.4, delta=0.08)

    def test_platt_separable_constant_and_weights(self):
        rng = np.random.default_rng(3)
        z = np.r_[rng.normal(5, 0.1, 100), rng.normal(-5, 0.1, 100)]
        y = np.r_[np.ones(100), np.zeros(100)]
        a, b = M.platt_fit(z, y)                       # smoothed targets keep it finite
        self.assertTrue(0 < a < 5 and abs(b) < 1)
        a, b = M.platt_fit(np.ones(10), np.r_[np.ones(3), np.zeros(7)])
        self.assertEqual(a, 0.0)
        tbar = (3 * 4 / 5 + 7 / 9) / 10
        self.assertAlmostEqual(b, math.log(tbar / (1 - tbar)), places=12)
        z, y = review_mixture(np.random.default_rng(4))
        w = np.where(y == 1, 3.0, 1.0)
        a1, b1 = M.platt_fit(z, y, w)
        a2, b2 = M.platt_fit(z, y, 7 * w)              # only relative weights matter
        self.assertAlmostEqual(a1, a2, places=9)
        self.assertAlmostEqual(b1, b2, places=9)
        self.assertGreater(b1, M.platt_fit(z, y)[1] + 0.5)   # up-weighted positives raise b
        with self.assertRaises(RuntimeError):
            M.platt_fit(z, y, iters=1)
        with self.assertRaises(ValueError):
            M.platt_fit([0.0, 1.0], [0.0, 0.5])

    @unittest.skipIf(optimize is None, "scipy not installed")
    def test_platt_matches_scipy(self):
        cases = []
        for i, sd in enumerate((0.5, 2.0, 5.0, 8.0)):
            rng = np.random.default_rng(10 + i)
            z = rng.normal(0.5, sd, 4000)
            y = (rng.random(4000) < M.sigmoid(0.6 * z - 0.4)).astype(float)
            w = rng.uniform(0.2, 2.0, 4000)
            cases += [(z, y, None), (z, y, w)]
        z, y = review_mixture(np.random.default_rng(5))
        cases.append((z, y, None))
        cases.append((z, y, np.where(y == 1, 0.5 / 4780, 0.5 / (len(y) - 4780))))
        for z, y, w in cases:
            ww = np.ones(len(z)) if w is None else w
            a, b = M.platt_fit(z, y, w)
            ref = optimize.minimize(lambda th: platt_loss(th[0], th[1], z, y, ww), [0.0, 0.0],
                                    method="Nelder-Mead",
                                    options={"xatol": 1e-10, "fatol": 1e-15, "maxiter": 20000})
            mine = platt_loss(a, b, z, y, ww)
            self.assertLessEqual(mine, ref.fun + 1e-12)
            self.assertAlmostEqual(a, ref.x[0], delta=1e-5 * max(1, abs(ref.x[0])))
            self.assertAlmostEqual(b, ref.x[1], delta=1e-5 * max(1, abs(ref.x[1])))

    def test_ece_brier_reliability(self):
        p = np.array([0.05] * 100 + [0.95] * 100)
        y = np.array([0] * 95 + [1] * 5 + [1] * 95 + [0] * 5, float)
        self.assertAlmostEqual(M.ece(p, y), 0.0, places=9)
        self.assertAlmostEqual(M.ece(np.full(10, 0.9), np.zeros(10)), 0.9, places=9)
        self.assertEqual(sum(r["n"] for r in M.reliability(p, y)), 200)
        # integer weights equal replicated samples
        rng = np.random.default_rng(6)
        p = rng.random(300)
        y = (rng.random(300) < p ** 2).astype(float)
        k = rng.integers(1, 4, 300)
        pr, yr = np.repeat(p, k), np.repeat(y, k)
        self.assertAlmostEqual(M.ece(p, y, k), M.ece(pr, yr), places=12)
        self.assertAlmostEqual(M.brier(p, y, k), M.brier(pr, yr), places=12)
        self.assertAlmostEqual(M.brier(p, y), float(np.mean((p - y) ** 2)), places=12)
        rw, rr = M.reliability(p, y, k), M.reliability(pr, yr)
        for a, b in zip(rw, rr):
            self.assertAlmostEqual(a["weight"], b["n"] / len(pr), places=12)
            if b["n"]:
                self.assertAlmostEqual(a["mean_p"], b["mean_p"], places=12)
                self.assertAlmostEqual(a["frac_pos"], b["frac_pos"], places=12)
        self.assertAlmostEqual(sum(r["weight"] for r in rw), 1.0, places=12)

    def test_mixture_weights(self):
        counts = {"text": 400, "blank": 50, "dense": 20, "iaaft_text": 400}
        shares = {"text": 0.5, "blank": 0.1, "dense": 0.1, "iaaft_text": 0.1}
        w = M.mixture_weights(counts, shares)
        for k in shares:
            self.assertAlmostEqual(w[k] * counts[k], shares[k] / 0.8, places=12)
        self.assertAlmostEqual(sum(w[k] * counts[k] for k in shares), 1.0, places=12)
        self.assertEqual(M.mixture_weights({"a": 0, "b": 3}, {"a": 0.0, "b": 1.0})["a"], 0.0)
        with self.assertRaises(ValueError):
            M.mixture_weights({"a": 0, "b": 3}, {"a": 0.5, "b": 0.5})

    def test_blocks(self):
        pos = np.array([[0, 0], [900, 511], [5, 512], [7, 1500], [3, 100]])
        ids = M.blocks([0, 0, 0, 2, 2], pos)
        self.assertEqual(ids.tolist(), [0, 0, 1, 200002, 200000])
        self.assertEqual(M.blocks([1], [[0, 300]], band_px=256).tolist(), [100001])
        with self.assertRaises(ValueError):
            M.blocks([0, 1], [[0, 0]])

    def test_block_bootstrap_takes_whole_clusters(self):
        rng = np.random.default_rng(7)
        ga = rng.choice([3, 5, 100001, 200007], 60)
        gb = np.r_[rng.choice([3, 5, 100001], 30), np.full(4, 999)]     # 999: only in group b
        universe = np.unique(np.r_[ga, gb])
        seen = []

        def fn(take):
            for name, g in (("a", ga), ("b", gb)):
                for c in universe:
                    members = np.nonzero(g == c)[0]
                    got = np.sort(take[name][g[take[name]] == c])
                    if len(members) == 0:
                        self.assertEqual(len(got), 0)
                        continue
                    reps = len(got) // len(members)
                    self.assertEqual(len(got), reps * len(members))
                    self.assertTrue(np.array_equal(got, np.repeat(members, reps)))
                    if name == "a":
                        seen.append(reps)
            return float(len(take["a"]))

        lo, hi, used = M.block_bootstrap(fn, {"a": ga, "b": gb}, n=50, seed=1)
        self.assertEqual(used, 50)
        self.assertLessEqual(lo, hi)
        # paired groups with equal ids get equal indices
        out = []
        M.block_bootstrap(lambda t: out.append(np.array_equal(t["p"], t["q"])) or 0.0,
                          {"p": ga, "q": ga.copy()}, n=20)
        self.assertTrue(all(out))
        # the same seed gives the same interval; a statistic constant over clusters has no width
        s = rng.normal(size=60)
        f = lambda t: float(s[t["a"]].mean())
        self.assertEqual(M.block_bootstrap(f, {"a": ga}, n=100, seed=3), M.block_bootstrap(f, {"a": ga}, n=100, seed=3))
        lo, hi, _ = M.block_bootstrap(lambda t: 1.0, {"a": ga}, n=30)
        self.assertEqual((lo, hi), (1.0, 1.0))
        lo, hi, used = M.block_bootstrap(lambda t: float("nan"), {"a": ga}, n=30)
        self.assertEqual(used, 0)
        self.assertTrue(np.isnan(lo))

    def test_segment_bootstrap(self):
        pos = np.array([2.0, 3.0, 4.0, 5.0])
        neg = np.array([0.0, 1.0, 1.5, 2.5])
        gp, gn = np.array([0, 0, 1, 1]), np.array([0, 0, 1, 1])
        fn = lambda t: M.auc(pos[t["p"]], neg[t["n"]])
        lo, hi, used = M.segment_bootstrap(fn, {"p": gp, "n": gn}, 2, n=200)
        self.assertEqual(used, 200)
        self.assertLessEqual(lo, M.auc(pos, neg))
        self.assertGreaterEqual(hi, M.auc(pos, neg) - 0.2)
        self.assertLessEqual(hi, 1.0)
        # with every segment present it is the cluster bootstrap over segment ids
        self.assertEqual(M.segment_bootstrap(fn, {"p": gp, "n": gn}, 2, n=200, seed=4),
                         M.block_bootstrap(fn, {"p": gp, "n": gn}, n=200, seed=4))

    def test_per_group(self):
        s = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        g = np.array([7, 7, 100000, 100000, 7])
        r = M.per_group(lambda t: float(s[t["a"]].sum()), {"a": g})
        self.assertEqual(r, {7: 8.0, 100000: 7.0})

    def test_sign_flip(self):
        self.assertAlmostEqual(M.sign_flip([0.1, 0.2, 0.05, 0.3, 0.02, 0.01]), 1 / 64, places=15)
        self.assertEqual(M.sign_flip([-0.1, -0.2, -0.3]), 1.0)
        rng = np.random.default_rng(8)
        for n in (1, 3, 5, 8):
            d = rng.normal(0.1, 0.2, n)
            ref = np.mean([sum(s * x for s, x in zip(sg, d)) >= d.sum() - 1e-12
                           for sg in itertools.product((1, -1), repeat=n)])
            self.assertAlmostEqual(M.sign_flip(d), ref, places=15)
        d = np.array([0.1, 0.1, 0.1])                   # equal flipped sums count as ties
        self.assertAlmostEqual(M.sign_flip(d), 1 / 8, places=15)
        self.assertAlmostEqual(M.sign_flip([0.1, float("nan"), 0.2]), 1 / 4, places=15)
        self.assertTrue(np.isnan(M.sign_flip([])))
        with self.assertRaises(ValueError):
            M.sign_flip(np.ones(13))

    def test_t_interval(self):
        lo, hi = M.t_interval([1, 2, 3, 4, 5, 6, float("nan")])
        half = 2.570582 * float(np.std([1, 2, 3, 4, 5, 6], ddof=1)) / math.sqrt(6)
        self.assertAlmostEqual(lo, 3.5 - half, places=5)
        self.assertAlmostEqual(hi, 3.5 + half, places=5)
        self.assertTrue(np.isnan(M.t_interval([1.0])[0]))
        for df in (1, 5, 30):
            self.assertEqual(M.t_quantile(df, 0.95, use_scipy=False), M.T_TABLE[0.95][df - 1])
        self.assertAlmostEqual(M.t_quantile(1000, 0.95, use_scipy=False), 1.962339, places=4)
        with self.assertRaises(ValueError):
            M.t_quantile(5, 0.8, use_scipy=False)

    @unittest.skipIf(stats is None, "scipy not installed")
    def test_t_table_matches_scipy(self):
        for level, row in M.T_TABLE.items():
            for df in range(1, 31):
                self.assertAlmostEqual(row[df - 1], stats.t.ppf(1 - (1 - level) / 2, df), delta=6e-7)
            for df in (31, 40, 60, 120, 500):
                self.assertAlmostEqual(M.t_quantile(df, level, use_scipy=False),
                                       stats.t.ppf(1 - (1 - level) / 2, df), delta=1e-4)


# ------------------------------------------------------------------ baselines
@unittest.skipIf(BL is None, "numpy not installed")
class BaselinesTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(BL.NAMES, ("density", "skew", "lines", "roughness", "seam8", "seam32", "grid",
                                    "spectrum", "nullspec", "texture", "randcnn"))
        self.assertEqual(BL.SINGLE + BL.FITTED, BL.NAMES)
        self.assertEqual(len(BL.HAND_NAMES), 21)

    def test_simple_scores(self):
        rng = np.random.default_rng(5)
        horiz = text_like(rng, 4)
        vert = text_like(rng, 4, horizontal=False)
        self.assertTrue((BL.lines(horiz) > BL.lines(vert)).all())
        self.assertTrue(np.allclose(BL.density(horiz), horiz.reshape(4, -1).mean(axis=1)))
        if stats is not None:
            self.assertTrue(np.allclose(BL.skew(horiz), stats.skew(horiz.reshape(4, -1).astype(float), axis=1),
                                        rtol=0, atol=1e-12))
            f = horiz.astype(np.float64) + rng.random(horiz.shape)
            self.assertTrue(np.allclose(BL.skew(f), stats.skew(f.reshape(4, -1), axis=1), rtol=0, atol=1e-12))
        self.assertEqual(BL.skew(np.full((2, 8, 8), 7, np.uint8)).tolist(), [0.0, 0.0])

    def test_skew_and_density_are_order_free_bit_for_bit(self):
        rng = np.random.default_rng(9)
        w = text_like(rng, 30)
        perm = np.stack([x.ravel()[rng.permutation(x.size)].reshape(x.shape) for x in w])
        self.assertTrue(np.array_equal(BL.skew(w), BL.skew(perm)))
        self.assertTrue(np.array_equal(BL.skew(w), BL.skew(w.astype(np.float32))))
        self.assertTrue(np.array_equal(BL.skew(w[::-1]), BL.skew(w)[::-1]))       # position free
        f = w.astype(np.float64) + rng.random(w.shape)                             # fsum path
        fp = np.stack([x.ravel()[rng.permutation(x.size)].reshape(x.shape) for x in f])
        self.assertTrue(np.array_equal(BL.skew(f), BL.skew(fp)))
        # IAAFT-like copies keep the value multiset, so skew and density tie: AUC exactly 0.5
        copies = np.stack([numpy_iaaft(x.astype(np.float64), rng) for x in w])
        copies = np.rint(copies).astype(np.uint8)
        self.assertTrue(np.array_equal(np.sort(copies.reshape(30, -1)), np.sort(w.reshape(30, -1))))
        self.assertFalse(np.array_equal(copies, w))
        self.assertEqual(M.auc(BL.skew(w), BL.skew(copies)), 0.5)
        self.assertEqual(M.auc(BL.density(w), BL.density(copies)), 0.5)
        self.assertEqual(M.auc(BL.skew(w), BL.skew(np.rot90(w, 1, axes=(1, 2)))), 0.5)

    def test_roughness_and_seams(self):
        rng = np.random.default_rng(10)
        w = text_like(rng, 6)
        z = BL.normalise(w).astype(np.float64)
        lap = (np.roll(z, 1, 1) + np.roll(z, -1, 1) + np.roll(z, 1, 2) + np.roll(z, -1, 2) - 4 * z)[:, 1:-1, 1:-1]
        self.assertTrue(np.allclose(BL.roughness(w), np.log((lap ** 2).mean(axis=(1, 2))), rtol=0, atol=1e-12))
        smooth = np.clip(np.rint(np.cumsum(rng.normal(0, 1, (6, 128, 128)), axis=2) + 128), 0, 255).astype(np.uint8)
        self.assertTrue((BL.roughness(rng.integers(0, 256, (6, 128, 128)).astype(np.uint8))
                         > BL.roughness(smooth)).all())
        # seam8 formula, written out for one window
        d = np.abs(np.diff(z[0], axis=1))
        seam = [7 + 8 * k for k in range(15)]
        other = [c for c in range(127) if c not in seam]
        ref = np.log(d[:, seam].mean() + 1e-6) - np.log(d[:, other].mean() + 1e-6)
        self.assertAlmostEqual(BL.seam8(w[:1])[0], ref, places=12)
        # cutting a smooth map into strips or tiles raises the matching seam score
        strips = smooth.reshape(6, 128, 16, 8)[:, :, rng.permutation(16)].reshape(6, 128, 128)
        self.assertTrue((BL.seam8(strips) > BL.seam8(smooth) + 0.5).all())
        t = smooth.reshape(6, 4, 32, 4, 32).transpose(0, 1, 3, 2, 4).reshape(6, 16, 32, 32)
        t = t[:, rng.permutation(16)].reshape(6, 4, 4, 32, 32).transpose(0, 1, 3, 2, 4).reshape(6, 128, 128)
        self.assertTrue((BL.seam32(t) > BL.seam32(smooth) + 0.5).all())
        cols = BL._seam_cols(128, 32).tolist()
        self.assertEqual(cols, [31, 63, 95])

    def test_grid_baseline(self):
        grid = BL._grid_cols(128).tolist()
        self.assertEqual(grid[:5], [5, 12, 18, 25, 31])
        self.assertEqual(len(grid), 19)
        self.assertIn("grid", BL.SINGLE)
        self.assertIs(BL.grid_step, BL.grid)
        # smaller steps across the grid lines along both axes, as in the pooled maps
        rng = np.random.default_rng(16)
        w = rng.normal(0, 1, (4, 128, 128))
        for c in grid:
            w[:, :, c + 1] = 0.5 * (w[:, :, c] + w[:, :, c + 1])
            w[:, c + 1, :] = 0.5 * (w[:, c, :] + w[:, c + 1, :])
        w = np.clip(np.rint(128 + 30 * w), 0, 255).astype(np.uint8)
        g = BL.grid_step(w)
        self.assertTrue((g < -0.5).all())
        perm = np.stack([x.ravel()[rng.permutation(x.size)].reshape(x.shape) for x in w])
        self.assertTrue((np.abs(BL.grid_step(perm)) < 0.1).all())

    def test_spectrum_features(self):
        sel, A, keep = BL._spectrum_bins(128, 128)
        self.assertEqual(len(keep), 84)
        self.assertEqual(len(sel), 128 * 128 - 1)            # every frequency but DC is in a band
        self.assertTrue(np.allclose(A.sum(axis=0), 1.0))
        self.assertEqual(BL.spectrum_bins().tolist(), keep.tolist())
        rng = np.random.default_rng(11)
        w = text_like(rng, 5)
        F = BL.spectrum_features(w)
        self.assertEqual(F.shape, (5, 84))
        # horizontal bands put their power at vertical frequencies (angle pi / 2, bin 4)
        col = {b: i for i, b in enumerate(keep)}
        r = np.digitize(128 / 40.0, BL.R_EDGES) - 1
        a4, a0 = col[r * BL.N_ANG + 4], col[r * BL.N_ANG + 0]
        self.assertTrue((F[:, a4] > F[:, a0] + 2).all())
        self.assertTrue(np.allclose(BL.spectrum_features(w.astype(np.float32)), F))
        self.assertEqual(BL.spectrum_features(w[:0]).shape, (0, 84))

    def test_hand_features(self):
        rng = np.random.default_rng(12)
        w = text_like(rng, 7)
        H = BL.hand_features(w)
        self.assertEqual(H.shape, (7, 21))
        for i, f in enumerate((BL.density, BL.skew, BL.lines, BL.roughness, BL.seam8, BL.seam32, BL.grid)):
            self.assertTrue(np.allclose(H[:, i], f(w), rtol=0, atol=1e-12))
        self.assertTrue(np.allclose(np.exp(H[:, 7:15]).sum(axis=1), 1 + 8e-6))
        # horizontal bands: gradients point down the window (orientation pi / 2, bin 4)
        self.assertTrue((H[:, 7 + 4] > H[:, 7 + 0]).all())
        z = BL.normalise(w[:1]).astype(np.float64).ravel()
        self.assertTrue(np.allclose(H[0, 15:], np.quantile(z, BL.QUANTILES)))

    def test_logistic(self):
        rng = np.random.default_rng(6)
        X = np.vstack([rng.normal(1, 1, (200, 3)), rng.normal(-1, 1, (200, 3))])
        y = np.r_[np.ones(200), np.zeros(200)]
        m = BL.fit_logistic(X, y)
        s = BL.logistic_score(m, X)
        self.assertGreater(M.auc(s[:200], s[200:]), 0.9)
        # integer sample weights equal replicated rows
        k = rng.integers(1, 4, 400)
        m1 = BL.fit_logistic(X, y, sample_weight=k)
        m2 = BL.fit_logistic(np.repeat(X, k, axis=0), np.repeat(y, k))
        self.assertTrue(np.allclose(BL.logistic_score(m1, X), BL.logistic_score(m2, X), atol=1e-7))
        # separable data stays finite under the penalty
        Xs = np.r_[np.full((50, 1), 2.0), np.full((50, 1), -2.0)] + rng.normal(0, 0.01, (100, 1))
        ms = BL.fit_logistic(Xs, np.r_[np.ones(50), np.zeros(50)])
        self.assertTrue(np.all(np.isfinite(ms["w"])))
        with self.assertRaises(RuntimeError):
            BL.fit_logistic(X, y, iters=0)
        # a constant feature gets sd 1 and coefficient 0, so new values of it change nothing
        mc = BL.fit_logistic(np.hstack([X, np.full((400, 1), 0.25)]), y)
        self.assertEqual(mc["sd"][-1], 1.0)
        self.assertAlmostEqual(mc["w"][-2], 0.0, places=12)

    @unittest.skipIf(optimize is None, "scipy not installed")
    def test_logistic_matches_scipy(self):
        rng = np.random.default_rng(13)
        X = rng.normal(0, 1, (500, 4)) * [1, 5, 0.2, 3]
        y = (rng.random(500) < M.sigmoid(X @ [1, -0.3, 2, 0.5] + 0.2)).astype(float)
        sw = rng.uniform(0.1, 2, 500)
        m = BL.fit_logistic(X, y, l2=1e-2, sample_weight=sw)
        w = sw / sw.sum()
        Z = np.hstack([(X - m["mu"]) / m["sd"], np.ones((500, 1))])

        def obj(b):
            u = Z @ b
            return float(w @ (np.logaddexp(0, u) - y * u) + 0.5 * 1e-2 * b[:-1] @ b[:-1])

        ref = optimize.minimize(obj, np.zeros(5), method="BFGS", options={"gtol": 1e-12})
        self.assertLessEqual(obj(m["w"]), ref.fun + 1e-12)
        self.assertTrue(np.allclose(m["w"], ref.x, atol=1e-5))

    def test_fit_save_load_score(self):
        rng = np.random.default_rng(14)
        pos, neg = text_like(rng, 40), text_like(rng, 40, horizontal=False)
        copies = np.rint(np.stack([numpy_iaaft(x.astype(np.float64), rng) for x in pos[:20]])).astype(np.uint8)
        models = {"spectrum": BL.fit_spectrum(pos, neg), "texture": BL.fit_texture(pos, neg),
                  "nullspec": BL.fit_nullspec(pos[:20], copies)}
        self.assertEqual(models["spectrum"]["n_features"], 84)
        self.assertEqual(models["texture"]["n_features"], 105)
        test = np.concatenate([text_like(rng, 10), text_like(rng, 10, horizontal=False)])
        s = BL.score_all(test, models)
        self.assertEqual(set(s), set(BL.NAMES) - {"randcnn"})
        self.assertTrue(all(v.dtype == np.float64 and v.shape == (20,) for v in s.values()))
        self.assertGreater(M.auc(s["spectrum"][:10], s["spectrum"][10:]), 0.9)
        self.assertGreater(M.auc(s["texture"][:10], s["texture"][10:]), 0.9)
        self.assertEqual(set(BL.score_all(test[:3])), set(BL.SINGLE))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "baselines.npz"
            BL.save_models(path, models)
            self.assertTrue(path.exists())
            loaded = BL.load_models(path)
            self.assertEqual(loaded["texture"]["kind"], "texture")
            self.assertEqual(loaded["spectrum"]["n_pos"], 40)
            s2 = BL.score_all(test, loaded)
            for k in s:
                self.assertTrue(np.array_equal(s[k], s2[k]), k)
            with self.assertRaises(ValueError):
                BL.save_models(Path(d) / "bad.npz", {"a/b": {"w": 1}})
        with self.assertRaises(ValueError):
            BL.score_all(test, {"w": np.zeros(3)})


@unittest.skipIf(BL is None or T is None, "numpy or torch not installed")
class RandCNNTest(unittest.TestCase):
    def test_randcnn_fit_and_round_trip(self):
        rng = np.random.default_rng(15)
        pos, neg = text_like(rng, 24), text_like(rng, 24, horizontal=False)
        torch.manual_seed(123)
        before = torch.rand(3)
        torch.manual_seed(123)
        m = BL.fit_randcnn(pos, neg, width=4, depth=2, seed=0, batch=16)
        self.assertTrue(torch.equal(torch.rand(3), before))            # caller's RNG untouched
        self.assertEqual(m["kind"], "randcnn")
        self.assertEqual(m["n_features"], 2 * 8)
        # the weights are those of torch.manual_seed(0); batch norm holds the cumulative average
        torch.manual_seed(0)
        ref = T.Net(4, 2)
        self.assertTrue(np.array_equal(m["state"]["features.0.weight"], ref.features[0].weight.detach().numpy()))
        x_all = np.concatenate([pos, neg])
        order = np.random.default_rng(0).permutation(48)
        means = []
        with torch.no_grad():
            for idx in np.array_split(order, 3):
                x = torch.from_numpy(x_all[np.sort(idx)].astype(np.float32))[:, None]
                means.append(ref.features[0](T.robust_norm_t(x)).mean(dim=(0, 2, 3)).numpy())
        self.assertTrue(np.allclose(m["state"]["features.1.running_mean"], np.mean(means, axis=0), atol=1e-5))
        self.assertEqual(int(m["state"]["features.1.num_batches_tracked"]), 3)
        m2 = BL.fit_randcnn(pos, neg, width=4, depth=2, seed=0, batch=16)
        self.assertTrue(np.array_equal(m["w"], m2["w"]))
        test = np.concatenate([text_like(rng, 6), text_like(rng, 6, horizontal=False)])
        s = BL.score_all(test, {"randcnn": m})["randcnn"]
        self.assertEqual(s.shape, (12,))
        with tempfile.TemporaryDirectory() as d:
            BL.save_models(Path(d) / "r.npz", {"randcnn": m})
            loaded = BL.load_models(Path(d) / "r.npz")
        self.assertEqual(loaded["randcnn"]["width"], 4)
        self.assertTrue(np.array_equal(BL.score_all(test, loaded)["randcnn"], s))


if __name__ == "__main__":
    unittest.main()
