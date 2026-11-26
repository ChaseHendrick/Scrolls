import json
import os
import tempfile
import unittest

from kit import simscore as ss

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


def judged(worst_by_critic, seeds=(0, 1)):
    crit = {c: {"auc": a, "runs": [{"auc": a, "per_fold": [a]} for _ in seeds]} for c, a in worst_by_critic.items()}
    w = max(worst_by_critic.values())
    return {"critics": crit, "worst": w, "worst_critic": max(worst_by_critic, key=worst_by_critic.get)}


def record(set_auc=0.52, control_auc=0.48, same=0.5, shift=0.99, n_groups=12, admit=12, d99=None, smoke=False):
    names = [f"z{i}" for i in range(n_groups)]
    rec = {"standard": ss.STANDARD, "settings": dict(ss.SETTINGS), "smoke": smoke,
           "reference": {"id": "test", "slices": names, "n_groups": n_groups, "trained_on": []},
           "set": {"n_tiles": ss.MIN_SIM_TILES}, "attempts": 0,
           "planted": {"same": {"feat": same, "cnn": same}, "noise": {"feat": shift, "cnn": shift},
                       "blur": {"feat": shift, "cnn": shift}},
           "control": judged({c: control_auc for c in ss.CRITICS}),
           "result": judged({"feat": set_auc, "cnn": set_auc - 0.01, "cnn_half": set_auc - 0.02}),
           "calibration": {"admit_groups": admit, "d99": {str(k): v for k, v in (d99 or {}).items()}}}
    rec["gates"] = ss.gates(rec["planted"], rec["control"])
    rec["verdict"] = ss.verdict(rec["result"]["worst"], rec["control"]["worst"])
    table = {int(k): v for k, v in rec["calibration"]["d99"].items()}
    rec["status"], rec["reason"] = ss.status(rec["verdict"], n_groups, admit=admit, table=table, gate=rec["gates"],
                                             smoke=smoke)
    rec["record_sha256"] = ss.record_digest(rec)
    return rec


class RuleTest(unittest.TestCase):
    """Numpy-free: the fixed rule, the gates, the status and the record check."""

    def test_verdict_bar_inclusive_and_none_safe(self):
        self.assertEqual(ss.verdict(0.53, 0.48)["verdict"], "PASS")
        self.assertEqual(ss.verdict(0.5301, 0.48)["verdict"], "FAIL")
        self.assertEqual(ss.verdict(0.61, 0.58)["verdict"], "FAIL")  # ceiling 0.60 binds
        v = ss.verdict(0.5, None)
        self.assertEqual((v["verdict"], v["gap_to_bar"]), ("FAIL", None))

    def test_gates(self):
        g = ss.gates({"same": {"feat": 0.5}, "noise": {"feat": 0.95}, "blur": {"feat": 0.91}}, {"worst": 0.5})
        self.assertTrue(all(g.values()))
        g = ss.gates({"same": {"feat": 0.7}, "noise": {"feat": 0.95}, "blur": {"feat": 0.5}}, {"worst": 0.66})
        self.assertEqual(g, {"planted_same": False, "planted_noise": True, "planted_blur": False, "control": False})
        self.assertFalse(ss.gates({}, {})["planted_same"])

    def test_status(self):
        ok = {k: True for k in ("planted_same", "planted_noise", "planted_blur", "control")}
        p, f = ss.verdict(0.5, 0.48), ss.verdict(0.9, 0.48)
        self.assertEqual(ss.status(p, 12, admit=12, table={}, gate=ok)[0], "PASS")
        self.assertEqual(ss.status(p, 6, admit=12, table={6: 0.1}, gate=ok)[0], "INCONCLUSIVE")
        self.assertEqual(ss.status(f, 6, admit=12, table={6: 0.1}, gate=ok)[0], "FAIL")
        self.assertEqual(ss.status(ss.verdict(0.62, 0.48), 6, admit=12, table={6: 0.1}, gate=ok)[0], "INCONCLUSIVE")
        self.assertEqual(ss.status(f, 6, admit=None, table={}, gate=ok)[0], "INCONCLUSIVE")
        self.assertEqual(ss.status(p, 12, admit=12, table={}, gate=dict(ok, control=False))[0], "VOID")
        self.assertEqual(ss.status(p, 12, admit=12, table={}, gate=ok, smoke=True)[0], "SMOKE")

    def test_d99_nearest_at_or_above(self):
        t = {6: 0.2, 12: 0.1, 24: 0.05}
        self.assertEqual(ss.d99_for(6, t), 0.2)
        self.assertEqual(ss.d99_for(7, t), 0.1)
        self.assertEqual(ss.d99_for(30, t), None)

    def test_check_passes_a_consistent_record(self):
        self.assertEqual(ss.check(record()), [])
        self.assertEqual(ss.check(record(set_auc=0.95, n_groups=6, d99={6: 0.2})), [])

    def test_check_catches_tampering(self):
        rec = record()
        rec["status"] = "PASS"
        rec["result"]["critics"]["feat"]["auc"] = 0.9
        rec["record_sha256"] = ss.record_digest(rec)
        probs = ss.check(rec)
        self.assertTrue(any("not the mean" in p for p in probs), probs)
        rec = record()
        rec["settings"]["margin"] = 0.10
        rec["record_sha256"] = ss.record_digest(rec)
        self.assertTrue(any("margin" in p for p in ss.check(rec)))
        rec = record()
        rec["attempts"] = 5
        self.assertTrue(any("record_sha256" in p for p in ss.check(rec)))
        rec = record()
        rec["reference"]["trained_on"] = ["z1"]
        rec["record_sha256"] = ss.record_digest(rec)
        self.assertTrue(any("odd slices" in p for p in ss.check(rec)))
        rec = record(same=0.8)
        self.assertEqual(rec["status"], "VOID")
        rec["status"] = "PASS"
        rec["record_sha256"] = ss.record_digest(rec)
        self.assertTrue(any("status" in p for p in ss.check(rec)))

    def test_pass_needs_an_admitted_size(self):
        rec = record(admit=None)
        self.assertEqual(rec["status"], "INCONCLUSIVE")
        self.assertEqual(ss.check(rec), [])

    def test_calibration_constants_match_the_evidence(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(ss.__file__)))
        with open(os.path.join(root, "docs", "evidence", "srs1-calibration-1126", "calibration.json")) as f:
            cal = json.load(f)
        self.assertEqual(cal["admit_groups"], ss.ADMIT_GROUPS)
        self.assertEqual({int(k): v for k, v in cal["d99"].items()}, ss.D99)
        for G, r in cal["by_groups"].items():
            self.assertEqual(r["admitted"], r["false_fail"] <= 0.10)

    def test_settings_match_simcritic(self):
        with open(os.path.join(os.path.dirname(ss.__file__), "simcritic.py")) as f:
            src = f.read()
        self.assertIn('CRITICS = ("feat", "cnn", "cnn_half")', src)
        self.assertIn("WIN = 128", src)
        self.assertIn("def verdict(result, control, margin=0.05, ceiling=0.60)", src)


@unittest.skipUnless(HAVE, "numpy and scipy needed")
class InputTest(unittest.TestCase):
    def test_reference_roundtrip(self):
        rng = np.random.default_rng(1)
        ref = {"id": "t", "ct": [rng.random((300, 300), dtype=np.float32) for _ in range(3)],
               "cover": [np.ones((300, 300), bool)] * 3, "name": ["a", "b", "c"]}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.npz")
            ss.save_reference(ref, p)
            back = ss.load_reference(p)
        self.assertEqual(back["name"], ["a", "b", "c"])
        self.assertEqual(back["id"], "t")
        self.assertTrue(np.array_equal(back["ct"][1], ref["ct"][1]))

    def test_refusals(self):
        rng = np.random.default_rng(2)
        ref = {"id": "t", "ct": [rng.random((256, 256), dtype=np.float32) for _ in range(6)], "cover": None,
               "name": [f"z{i}" for i in range(6)]}
        tiles = [rng.random((256, 256), dtype=np.float32) for _ in range(10)]
        with self.assertRaises(ss.ScoreError):  # too few tiles
            ss.score(ref, tiles, {"name": "t"}, 0, progress=lambda *_: None)
        with self.assertRaises(ss.ScoreError):  # odd slice trained on
            ss.score(ref, tiles, {"name": "t"}, 0, trained_on=["z1"], smoke=True, steps=2, progress=lambda *_: None)
        with self.assertRaises(ss.ScoreError):  # unknown slice
            ss.score(ref, tiles, {"name": "t"}, 0, trained_on=["q"], smoke=True, steps=2, progress=lambda *_: None)
        with self.assertRaises(ss.ScoreError):  # steps off standard without smoke
            ss.score(ref, tiles * 30, {"name": "t"}, 0, steps=2, progress=lambda *_: None)
        with self.assertRaises(ss.ScoreError):  # attempts missing
            ss.score(ref, tiles, {"name": "t"}, None, smoke=True, steps=2, progress=lambda *_: None)

    @unittest.skipUnless(HAVE_TORCH, "torch needed")
    def test_smoke_score_writes_a_checkable_record(self):
        rng = np.random.default_rng(3)
        from scipy import ndimage as nd
        ref = {"id": "t", "ct": [nd.gaussian_filter(rng.standard_normal((256, 256)), 2).astype(np.float32)
                                 for _ in range(6)], "cover": None, "name": [f"z{i}" for i in range(6)]}
        tiles = [nd.gaussian_filter(rng.standard_normal((256, 256)), 2).astype(np.float32) for _ in range(6)]
        rec = ss.score(ref, tiles, {"name": "t"}, 0, trained_on=["z0"], smoke=True, steps=2,
                       progress=lambda *_: None)
        self.assertEqual(rec["status"], "SMOKE")
        self.assertTrue(rec["size_problems"])
        self.assertEqual(ss.check(json.loads(json.dumps(rec))), [])
        self.assertEqual(rec["reference"]["n_groups"], 6)
        self.assertEqual(len(rec["scorer"]["simscore.py"]), 64)


if __name__ == "__main__":
    unittest.main()
