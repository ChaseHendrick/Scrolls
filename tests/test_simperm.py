import unittest

from kit import simperm as sp

try:
    import numpy as np
    import scipy  # noqa: F401
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False


def unit_rows(rng, n_units, shift=0.0, rows=16, dim=8, spread=0.3):
    """Per-unit feature rows: each unit has its own offset (a group effect), plus SHIFT for a different source."""
    return [rng.normal(rng.normal(0, spread, dim) + shift, 1.0, (rows, dim)) for _ in range(n_units)]


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class UnitsAndFolds(unittest.TestCase):
    def test_deal_puts_both_kinds_in_every_fold(self):
        f = sp.deal([f"r{i}" for i in range(6)], [f"s{i}" for i in range(7)], 3, 0)
        for k in range(3):
            kinds = {u[0] for u, v in f.items() if v == k}
            self.assertEqual(kinds, {"r", "s"})

    def test_deal_refuses_too_few_units(self):
        with self.assertRaises(sp.PermError):
            sp.deal(["r0", "r1"], ["s0", "s1", "s2"], 3, 0)

    def test_sim_units_consecutive_and_short_tail_dropped(self):
        tile = np.repeat(np.arange(10), 4)  # 10 tiles of 4 windows
        uid = sp.sim_units(tile, 10, 12)  # 3 tiles a unit, the 10th tile is a short tail
        self.assertEqual(uid.tolist(), [0, 0, 0, 1, 1, 1, 2, 2, 2, -1])


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class PermTest(unittest.TestCase):
    def _scores(self, rng, sep):
        real = [f"r{i}" for i in range(6)]
        sim = [f"s{i}" for i in range(6)]
        fold = sp.deal(real, sim, 3, 0)
        sc = {c: {u: float(rng.normal(sep if u in real else 0.0, 1.0)) for u in fold} for c in ("a", "b")}
        return sc, real, fold

    def test_separated_units_fail(self):
        sc, real, fold = self._scores(np.random.default_rng(1), 6.0)
        r = sp.permtest(sc, real, fold, perms=999, seed=3)
        self.assertLessEqual(r["p"], sp.ALPHA)
        self.assertEqual(r["auc_unit"]["a"], 1.0)

    def test_one_critic_is_enough(self):
        sc, real, fold = self._scores(np.random.default_rng(2), 0.0)
        sc["b"] = {u: (10.0 if u in real else 0.0) + 0.01 * i for i, u in enumerate(sorted(fold))}
        r = sp.permtest(sc, real, fold, perms=999, seed=3)
        self.assertLessEqual(r["p"], sp.ALPHA)
        self.assertGreater(r["z"]["b"], r["z"]["a"])

    def test_exchangeable_scores_fail_near_alpha(self):
        rng = np.random.default_rng(5)
        ps = []
        for _ in range(300):
            sc, real, fold = self._scores(rng, 0.0)
            ps.append(sp.permtest(sc, real, fold, perms=199, seed=int(rng.integers(1 << 30)))["p"])
        rate = float(np.mean(np.array(ps) <= sp.ALPHA))
        self.assertLess(rate, 0.11)  # the rule's alpha is 0.05; 300 draws, binomial slack
        self.assertGreater(float(np.median(ps)), 0.3)

    def test_fold_with_one_kind_is_refused(self):
        fold = {"r0": 0, "r1": 1, "s0": 1, "s1": 0, "r2": 2, "s2": 2, "r3": 2}
        fold["s2"] = 0
        with self.assertRaises(sp.PermError):
            sp.permtest({"a": {u: 0.0 for u in fold}}, ["r0", "r1", "r2", "r3"], fold, perms=9, seed=0)


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class FeatCritic(unittest.TestCase):
    def test_shifted_simulator_fails(self):
        rng = np.random.default_rng(7)
        real, sim = unit_rows(rng, 6), unit_rows(rng, 6, shift=1.0)
        self.assertLessEqual(sp._feat_test(real, sim, 999, 1, 0)["p"], sp.ALPHA)

    def test_same_source_simulator_mostly_passes(self):
        rng = np.random.default_rng(8)
        ps = [sp._feat_test(unit_rows(rng, 6), unit_rows(rng, 6), 199, i, i)["p"] for i in range(30)]
        self.assertLessEqual(float(np.mean(np.array(ps) <= sp.ALPHA)), 0.2)


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class StatusAndCheck(unittest.TestCase):
    def test_status_rules(self):
        ok = {"planted_blur": True, "planted_noise": True, "self_split": True}
        self.assertEqual(sp.status(0.01, 6, ok, admit=6)[0], "FAIL")
        self.assertEqual(sp.status(0.4, 6, ok, admit=6)[0], "PASS")
        self.assertEqual(sp.status(0.4, 6, ok, admit=12)[0], "INCONCLUSIVE")
        self.assertEqual(sp.status(0.4, 6, ok, admit=None)[0], "INCONCLUSIVE")
        self.assertEqual(sp.status(0.4, 6, dict(ok, planted_blur=False), admit=6)[0], "VOID")
        self.assertEqual(sp.status(0.01, 6, ok, admit=6, smoke=True)[0], "SMOKE")

    def test_gates_can_fail(self):
        self.assertEqual(sp.gates({"blur": {"p": 0.001}, "noise": {"p": 0.001}, "split": {"p": 0.5}}),
                         {"planted_blur": True, "planted_noise": True, "self_split": True})
        self.assertFalse(sp.gates({"blur": {"p": 0.3}, "noise": {"p": 0.001}, "split": {"p": 0.5}})["planted_blur"])
        self.assertFalse(sp.gates({"blur": {"p": 0.001}, "noise": {"p": 0.001}, "split": {"p": 0.001}})["self_split"])

    def test_no_pass_before_calibration(self):
        self.assertIsNone(sp.ADMIT_GROUPS)

    def _record(self):
        rng = np.random.default_rng(9)
        real = [f"r{i}" for i in range(6)]
        sim = [f"s{i}" for i in range(9)]
        fold = sp.deal(real, sim, 3, 0)
        scores = {c: {u: float(rng.normal()) for u in fold} for c in sp.CRITICS}
        res = sp.permtest(scores, real, fold, sp.PERMS, sp.PERM_SEED)
        res["scores"] = {c: {u: v for u, v in s.items()} for c, s in scores.items()}
        planted = {"blur": {"p": 0.0001}, "noise": {"p": 0.0001}, "split": {"p": 0.6}}
        g = sp.gates(planted)
        st, why = sp.status(res["p"], 6, g, admit=None)
        rec = {"standard": sp.STANDARD, "settings": dict(sp.SETTINGS), "smoke": False, "result": res,
               "fold_of": fold, "planted": planted, "gates": g, "status": st, "reason": why,
               "reference": {"n_real_units": 6}, "calibration": {"admit_groups": None}}
        rec["record_sha256"] = sp.record_digest(rec)
        return rec

    def test_check_recomputes_a_record(self):
        self.assertEqual(sp.check(self._record()), [])

    def test_check_catches_a_changed_p(self):
        rec = self._record()
        rec["result"]["p"] = 0.001
        rec["status"] = "FAIL"
        rec["record_sha256"] = sp.record_digest(rec)
        probs = sp.check(rec)
        self.assertTrue(any("result p" in x for x in probs), probs)


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class ScoreSmoke(unittest.TestCase):
    def _img(self, rng, shape, sigma):
        from scipy import ndimage as nd
        return nd.gaussian_filter(rng.normal(0, 1, shape), sigma).astype(np.float32)

    def _run(self, sim_sigma):
        rng = np.random.default_rng(11)
        ref = {"id": "t", "ct": [self._img(rng, (384, 384), 2.0) for _ in range(6)], "cover": None,
               "name": [f"z{i}" for i in range(6)]}
        tiles = [self._img(rng, (256, 256), sim_sigma) for _ in range(27)]
        return sp.score(ref, tiles, {"name": "test"}, 0, smoke=True, steps=1, perms=499, critics=("feat",),
                        progress=lambda *_: None)

    def test_score_record_checks_and_catches_a_wrong_texture(self):
        rec = self._run(4.0)
        self.assertEqual(rec["set"]["n_sim_units"], 9)
        self.assertLessEqual(rec["result"]["p"], sp.ALPHA)
        self.assertEqual(rec["status"], "SMOKE")
        self.assertEqual(sp.check(rec), [])


if __name__ == "__main__":
    unittest.main()
