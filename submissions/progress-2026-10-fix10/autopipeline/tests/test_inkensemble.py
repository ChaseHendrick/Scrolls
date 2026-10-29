"""kit inkensemble: AutoPipeline's ink-ensemble stage (member maps z-scored inside the mask, then combined).

The checks that must be able to fail: an ensemble of a map with scrambled copies of itself must not beat the map
alone on a planted-signal fixture; with the depth order of every member reversed, the ensemble of the reverse maps
must sit near 0.5 while the forward ensemble reads the planted ink; and an ensemble of independent noisy readers
must beat each of them, so the first check is not passed by an ensemble that never helps.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import auc, autopipe, cli, ensemble, inkensemble, provenance
from kit.verify import VerifyError

try:
    import numpy as np
    import tifffile
except ImportError:  # the core kit is standard library only
    np = tifffile = None


def planted(shape=(120, 120), seed=0):
    """A boolean ink pattern: strokes on a few text rows, about a fifth of the pixels."""
    rng = np.random.default_rng(seed)
    ink = np.zeros(shape, bool)
    for r0 in (14, 44, 74, 100):
        for c0 in range(6, shape[1] - 10, 9):
            if rng.random() < 0.7:
                ink[r0:r0 + 10, c0:c0 + 4] = True
    return ink


def reader(ink, strength, noise, seed, dtype="uint8"):
    """A map that sees the ink with this strength under independent noise, in one of three file types."""
    rng = np.random.default_rng(seed)
    v = strength * ink + rng.normal(0.0, noise, ink.shape)
    v = (v - v.min()) / (v.max() - v.min())
    if dtype == "uint8":
        return (1 + np.round(v * 254)).astype(np.uint8)
    if dtype == "uint16":
        return (1 + np.round(v * 65534)).astype(np.uint16)
    return (0.01 + 0.98 * v).astype(np.float32)


def score(m, ink, mask=None):
    return auc.score_array(np.asarray(m), ink, np.ones(ink.shape, bool) if mask is None else mask)["auc"]


def scrambled(m, seed):
    rng = np.random.default_rng(seed)
    flat = np.asarray(m).ravel().copy()
    return flat[rng.permutation(flat.size)].reshape(np.asarray(m).shape)


@unittest.skipIf(tifffile is None, "numpy and tifffile are needed for kit inkensemble")
class ArithmeticTest(unittest.TestCase):
    def test_member_stats_mean_sd_and_median_mad(self):
        v = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
        m = inkensemble.member_stats(v, "mean")
        self.assertAlmostEqual(m["center"], 22.0)
        self.assertAlmostEqual(m["scale"], float(np.std(v)) + 1e-6)
        r = inkensemble.member_stats(v, "median")
        self.assertEqual(r["center"], 3.0)
        self.assertEqual(r["mad"], 1.0)                       # |v - 3| = 2 1 0 1 97
        self.assertAlmostEqual(r["scale"], 1.482602218505602 + 1e-6)

    def test_median_and_mad_shrug_off_outliers_that_inflate_the_sd(self):
        rng = np.random.default_rng(1)
        v = np.concatenate([rng.normal(0.0, 1.0, 20000), np.full(400, 1000.0)])
        self.assertGreater(inkensemble.member_stats(v, "mean")["scale"], 50)
        r = inkensemble.member_stats(v, "median")
        self.assertLess(abs(r["center"]), 0.1)
        self.assertLess(abs(r["scale"] - 1.0), 0.1)

    def test_a_member_whose_mad_is_zero_is_refused(self):
        v = np.array([5.0] * 6 + [1.0, 9.0])
        with self.assertRaisesRegex(inkensemble.MADZeroError, "MAD is 0"):
            inkensemble.member_stats(v, "median")
        self.assertTrue(issubclass(inkensemble.MADZeroError, VerifyError))     # the command line still exits 2
        self.assertEqual(inkensemble.member_stats(v, "mean")["center"], 5.0)    # mean and SD take it

    def test_trimmed_mean_drops_each_pixel_s_extremes_and_carries_weights(self):
        z = np.array([[0.0, 10.0], [1.0, -5.0], [2.0, 0.0], [100.0, 1.0]])   # 4 members x 2 pixels
        np.testing.assert_allclose(inkensemble.combine_z(z, [1, 1, 1, 1], 1), [1.5, 0.5])
        np.testing.assert_allclose(inkensemble.combine_z(z, [1, 1, 3, 1], 1), [1.75, 0.25])
        np.testing.assert_allclose(inkensemble.combine_z(z, [1, 1, 1, 1], 0), [25.75, 1.5])
        np.testing.assert_allclose(inkensemble.combine_z(z, [2, 0, 0, 0], 0), [0.0, 10.0])

    def test_trim_count(self):
        self.assertEqual(inkensemble.trim_count(4, 0.25), 1)
        self.assertEqual(inkensemble.trim_count(8, 0.125), 1)
        self.assertEqual(inkensemble.trim_count(8, 0.25), 2)
        self.assertEqual(inkensemble.trim_count(3, 0.34), 1)
        for n, t in ((2, 0.25), (3, 0.25)):
            with self.assertRaisesRegex(VerifyError, "drops nobody"):
                inkensemble.trim_count(n, t)
        for t in (0, 0.5, -0.1, True, "0.2"):
            with self.assertRaisesRegex(VerifyError, "share above 0 and below 0.5"):
                inkensemble.trim_count(8, t)

    def test_weights_are_checked(self):
        self.assertEqual(inkensemble.check_weights(None, 3, "mean"), [1.0, 1.0, 1.0])
        self.assertEqual(inkensemble.check_weights([2, 0], 2, "mean"), [2.0, 0.0])
        for w, n, combine, msg in (([1], 2, "mean", "one weight per member"), ([1, -1], 2, "mean", "at least 0"),
                                   ([0, 0], 2, "mean", "all 0"), ([1, float("nan")], 2, "mean", "finite"),
                                   ([1, 0, 1], 3, "trimmed", "every weight above 0")):
            with self.subTest(msg=msg), self.assertRaisesRegex(VerifyError, msg):
                inkensemble.check_weights(w, n, combine)


@unittest.skipIf(tifffile is None, "numpy and tifffile are needed for kit inkensemble")
class PlantedSignalTest(unittest.TestCase):
    def setUp(self):
        self.ink = planted()

    def test_a_map_with_its_scrambled_copies_never_beats_the_map_alone(self):
        a = reader(self.ink, 1.0, 0.8, seed=3)
        alone = score(a, self.ink)
        self.assertGreater(alone, 0.7)
        s1, s2, s3 = (scrambled(a, seed) for seed in (11, 12, 13))
        cases = [([("a", a), ("s", s1)], {}),
                 ([("a", a), ("s", s1)], {"center": "median"}),
                 ([("a", a), ("s1", s1), ("s2", s2)], {"combine": "trimmed", "trim": 0.34}),
                 ([("a", a), ("s1", s1), ("s2", s2), ("s3", s3)], {"center": "median", "combine": "trimmed"})]
        for members, opts in cases:
            out, ok, _ = inkensemble.combine_members(members, **opts)
            got = score(np.where(ok, out, 0.0) - out[ok].min() + 1e-3, self.ink)
            with self.subTest(opts=opts, members=len(members)):
                self.assertLessEqual(got, alone + 1e-9)
                self.assertLess(got, alone - 0.02)        # the scrambled copies only add noise

    def test_a_zero_weight_on_the_scrambled_copy_gives_the_map_alone(self):
        a = reader(self.ink, 1.0, 0.8, seed=3)
        out, ok, _ = inkensemble.combine_members([("a", a), ("s", scrambled(a, 5))], weights=[1, 0])
        self.assertEqual(round(score(out - out.min() + 1e-3, self.ink), 4), round(score(a, self.ink), 4))

    def test_independent_readers_do_better_together(self):
        # without this the scrambled-copy check could be passed by an ensemble that never helps
        members = [(f"r{i}", reader(self.ink, 1.0, 1.2, seed=20 + i, dtype=t))
                   for i, t in enumerate(("uint8", "uint16", "float32", "uint8"))]
        best = max(score(m, self.ink) for _, m in members)
        for opts in ({}, {"center": "median"}, {"center": "median", "combine": "trimmed"}):
            out, ok, _ = inkensemble.combine_members(members, **opts)
            with self.subTest(opts=opts):
                self.assertGreater(score(out - out.min() + 1e-3, self.ink), best + 0.03)

    def test_reversing_depth_on_every_member_gives_a_control_near_one_half(self):
        # A depth stack: ink in layers 2 to 4 (as stored), quiet front layers and noisy back ones. Each reader weighs
        # the front layers with its own kernel and the back six a little, so reading the stack in reverse puts the
        # ink where every reader still sees some of it, under the shared noise of the (reversed) front layers: each
        # reverse map carries a weak real signal, as real reverse maps do, so a combiner cannot pass by default.
        rng = np.random.default_rng(7)
        depth, back = 16, 0.3
        sd = np.r_[np.full(8, 0.3), np.full(8, 2.0)][:, None, None]
        vol = rng.normal(0.0, 1.0, (depth,) + self.ink.shape) * sd
        vol[2:5] += 1.5 * self.ink
        kernels = [np.r_[np.linspace(1.0, 0.2, 8), np.zeros(2), np.full(6, back)],
                   np.r_[np.ones(6), np.zeros(4), np.full(6, back)],
                   np.r_[0.5, np.ones(5), 0.3, np.zeros(3), np.full(6, back)],
                   np.r_[np.linspace(1.0, 0.0, 10), np.full(6, back)]]

        def read(stack, kern, seed):
            v = np.tensordot(kern, stack, axes=1) + np.random.default_rng(seed).normal(0.0, 2.5, self.ink.shape)
            v = (v - v.min()) / (v.max() - v.min())
            return (1 + np.round(v * 254)).astype(np.uint8)

        fwd = [(f"m{i}", read(vol, k, 100 + i)) for i, k in enumerate(kernels)]
        rev = [(f"m{i}", read(vol[::-1], k, 200 + i)) for i, k in enumerate(kernels)]
        single = [(score(f, self.ink), score(r, self.ink)) for (_, f), (_, r) in zip(fwd, rev)]
        best_f, best_r = max(single)
        self.assertTrue(all(0.55 < r < 0.62 for _, r in single), single)   # weak, real reverse signal

        def both(members_f, members_r, opts):
            f, _, _ = inkensemble.combine_members(members_f, **opts)
            r, _, _ = inkensemble.combine_members(members_r, **opts)
            return score(f - f.min() + 1e-3, self.ink), score(r - r.min() + 1e-3, self.ink)

        for opts in ({}, {"center": "median", "combine": "trimmed"}):
            af, ar = both(fwd, rev, opts)
            with self.subTest(opts=opts):
                self.assertGreater(af, max(0.85, best_f))
                self.assertLess(abs(ar - 0.5), 0.1)
                # the prereg's control: the ensemble's forward minus reverse gap is at least its best member's
                self.assertGreaterEqual(af - ar, best_f - best_r)
                # and it can fail: one forward map leaked into the reverse ensemble breaks it
                for j in range(len(rev)):
                    leaky = [(n, fwd[j][1] if i == j else m) for i, (n, m) in enumerate(rev)]
                    lf, lr = both(fwd, leaky, opts)
                    self.assertLess(lf - lr, best_f - best_r, f"leak of m{j}")

    def test_statistics_come_from_inside_the_mask_only(self):
        a = reader(self.ink, 1.0, 0.8, seed=3).astype(np.float32)
        b = reader(self.ink, 1.0, 0.8, seed=4).astype(np.float32)
        mask = np.zeros(self.ink.shape, bool)
        mask[:, :60] = True
        out1, ok1, st1 = inkensemble.combine_members([("a", a), ("b", b)], center="median", valid=mask)
        a2, b2 = a.copy(), b.copy()
        a2[:, 60:] = 1e6           # wild values outside the mask must change nothing
        b2[:, 60:] = -3.0
        out2, ok2, st2 = inkensemble.combine_members([("a", a2), ("b", b2)], center="median", valid=mask)
        np.testing.assert_array_equal(ok1, mask)
        np.testing.assert_allclose(out1, out2)
        self.assertEqual(st1["a"]["center"], st2["a"]["center"])
        self.assertTrue((out1[:, 60:] == 0).all())

    def test_pixels_some_member_did_not_predict_are_left_out(self):
        a = reader(self.ink, 1.0, 0.8, seed=3)
        b = reader(self.ink, 1.0, 0.8, seed=4)
        b[:10] = 0
        out, ok, st = inkensemble.combine_members([("a", a), ("b", b)])
        self.assertFalse(ok[:10].any())
        self.assertTrue(ok[10:].all())
        self.assertEqual(st["a"]["n_px"], int(ok.sum()))
        _, ok0, _ = inkensemble.combine_members([("a", a), ("b", b)], keep_zero=True)
        self.assertTrue(ok0.all())


@unittest.skipIf(tifffile is None, "numpy and tifffile are needed for kit inkensemble")
class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.ink = planted()
        self.paths = []
        for i, t in enumerate(("uint8", "uint16", "float32")):
            p = self.d / f"m{i}.tif"
            tifffile.imwrite(str(p), reader(self.ink, 1.0, 1.0, seed=40 + i, dtype=t))
            self.paths.append(p)

    def tearDown(self):
        self.tmp.cleanup()

    def members(self):
        return [(f"m{i}", str(p)) for i, p in enumerate(self.paths)]

    def test_defaults_reproduce_kit_ensemble_zscore_on_the_maps_own_statistics(self):
        a, b = self.d / "kit-ensemble.tif", self.d / "inkensemble.tif"
        ensemble.zscore_files(a, self.members())
        res = inkensemble.run(b, self.members())
        x, y = tifffile.imread(str(a)).astype(np.int64), tifffile.imread(str(b)).astype(np.int64)
        self.assertLessEqual(int(np.abs(x - y).max()), 1)
        self.assertEqual(res["settings"]["center"], "mean")
        self.assertEqual(res["valid_px"], self.ink.size)

    def test_writes_a_map_and_a_provenance_record_that_checks(self):
        out, raw = self.d / "ens.tif", self.d / "ens.npy"
        res = inkensemble.run(out, self.members(), center="median", combine="trimmed", trim=0.34,
                              weights=[1, 2, 1], raw_out=raw)
        u = tifffile.imread(str(out))
        self.assertEqual(u.dtype, np.uint16)
        self.assertEqual((int(u.min()), int(u.max())), (1, 65535))
        z = np.load(str(raw))
        self.assertAlmostEqual(float(np.nanmin(z)), res["combined_z_min"], places=5)
        prov = Path(res["provenance"]["path"])
        self.assertEqual(prov, self.d / "ens.provenance.json")
        rec = json.loads(prov.read_text())
        self.assertEqual(rec["digest"], res["provenance"]["digest"])
        self.assertEqual(provenance.verify(rec, recheck_files=True), [])
        self.assertEqual([i["sha256"] for i in rec["inputs"]], [provenance.sha256_file(p) for p in self.paths])
        self.assertEqual([o["path"] for o in rec["outputs"]], [str(out), str(raw)])
        self.assertEqual(rec["notes"]["settings"]["trimmed_each_end"], 1)
        self.assertEqual(rec["notes"]["settings"]["weights"], [1.0, 2.0, 1.0])
        self.assertEqual([m["name"] for m in rec["notes"]["members"]], ["m0", "m1", "m2"])
        tifffile.imwrite(str(out), np.ones_like(u))          # the record catches a changed output
        self.assertIn(f"outputs: {out} changed", provenance.verify(rec, recheck_files=True))

    def test_a_mask_file_limits_the_pixels(self):
        mask = np.zeros(self.ink.shape, np.uint8)
        mask[20:80, 20:80] = 1
        mp = self.d / "mask.tif"
        tifffile.imwrite(str(mp), mask)
        res = inkensemble.run(self.d / "ens.tif", self.members(), mask=mp)
        u = tifffile.imread(str(self.d / "ens.tif"))
        self.assertEqual(res["valid_px"], 3600)
        self.assertTrue((u[mask == 0] == 0).all() and (u[mask == 1] > 0).all())
        rec = json.loads(Path(res["provenance"]["path"]).read_text())
        self.assertEqual(rec["inputs"][-1]["sha256"], provenance.sha256_file(mp))

    def test_refusals(self):
        m = self.members()
        for kwargs, msg in (({"members": m[:1]}, "at least two"),
                            ({"members": [("a", m[0][1]), ("a", m[1][1])]}, "repeat"),
                            ({"members": m[:2], "combine": "trimmed"}, "drops nobody"),
                            ({"members": m, "weights": [1, 1]}, "one weight per member"),
                            ({"members": m, "center": "mode"}, "center is one of"),
                            ({"members": m, "combine": "max"}, "combine is one of"),
                            ({"members": m, "decode": "x"}, "decode is one of")):
            with self.subTest(msg=msg), self.assertRaisesRegex(VerifyError, msg):
                inkensemble.run(self.d / "x.tif", **kwargs)
        small = self.d / "small.tif"
        tifffile.imwrite(str(small), np.ones((4, 4), np.uint8))
        with self.assertRaisesRegex(VerifyError, "is \\(4, 4\\), not"):
            inkensemble.run(self.d / "x.tif", m[:1] + [("s", str(small))])
        with self.assertRaisesRegex(VerifyError, "also an input"):
            inkensemble.run(m[0][1], m)
        with self.assertRaisesRegex(VerifyError, "raw output is a .npy"):
            inkensemble.run(self.d / "x.tif", m, raw_out=self.d / "x.tif.raw")
        zero = self.d / "zero.tif"
        tifffile.imwrite(str(zero), np.zeros(self.ink.shape, np.uint8))
        with self.assertRaisesRegex(VerifyError, "no pixel is valid"):
            inkensemble.run(self.d / "x.tif", m[:1] + [("z", str(zero))])

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["inkensemble", *map(str, argv)])
        return code, out.getvalue(), err.getvalue()

    def test_command_line(self):
        out = self.d / "cli.tif"
        code, text, err = self.run_cli(out, *[f"{n}={p}" for n, p in self.members()], "--robust", "--combine",
                                       "trimmed", "--trim", "0.34", "--weights", "1", "1", "2", "--json")
        self.assertEqual(code, 0, err)
        res = json.loads(text)
        self.assertEqual((res["settings"]["center"], res["settings"]["combine"]), ("median", "trimmed"))
        self.assertEqual([m["name"] for m in res["members"]], ["m0", "m1", "m2"])
        self.assertTrue(Path(res["provenance"]["path"]).exists())
        code, text, _ = self.run_cli(self.d / "plain.tif", *self.paths)
        self.assertEqual(code, 0)
        self.assertIn("3 members, mean and SD z-scores, weighted mean", text)
        self.assertIn("map1: weight 1", text)
        for argv, msg in (([self.d / "t.tif", *self.paths, "--trim", "0.3"], "--trim goes with --combine trimmed"),
                          ([f"a={self.paths[0]}", *self.paths], "the output map comes first"),
                          ([self.d / "t.tif", self.paths[0]], "at least two member maps"),
                          ([self.d / "t.tif", *self.paths, "--decode", "zz=ls"], "names members that are not given")):
            code, _, err = self.run_cli(*argv)
            with self.subTest(msg=msg):
                self.assertEqual(code, 2)
                self.assertIn(msg, err)


class PlanTest(unittest.TestCase):
    """AutoPipeline's ink.ensemble with method zscore (standard library: no maps are made)."""

    def test_plan_options(self):
        self.assertIsNone(inkensemble.check_plan({"method": "zscore"}, ["a", "b"]))
        self.assertIsNone(inkensemble.check_plan({"method": "zscore", "robust": True, "combine": "trimmed",
                                                  "trim": 0.25, "weights": {"a": 1, "b": 2, "c": 1, "d": 1}},
                                                 ["a", "b", "c", "d"]))
        for cfg, models, msg in (({"robust": 1}, ["a", "b"], "robust is true or false"),
                                 ({"combine": "max"}, ["a", "b"], "combine is one of"),
                                 ({"trim": 0.2}, ["a", "b"], "trim goes with combine trimmed"),
                                 ({"combine": "trimmed"}, ["a", "b"], "drops nobody"),
                                 ({"weights": {"a": 1}}, ["a", "b"], "names every planned model once"),
                                 ({"weights": [1, 1]}, ["a", "b"], "names every planned model once"),
                                 ({"weights": {"a": 1, "b": -1}}, ["a", "b"], "at least 0"),
                                 ({"other": 1}, ["a", "b"], "unknown plan setting ink.ensemble.other"),
                                 # names kit inkensemble would refuse at the ink stage are refused at the plan
                                 ({}, ["my model", "b"], "letters, digits and _ . + - only: ['my model']"),
                                 ({}, ["a/b", "b"], "letters, digits and _ . + - only"),
                                 ({}, ["a", "a", "b"], "planned twice")):
            with self.subTest(msg=msg):
                self.assertIn(msg, inkensemble.check_plan({"method": "zscore", **cfg}, models))

    def test_plan_flags(self):
        self.assertEqual(inkensemble.plan_flags({"method": "zscore"}, ["a", "b"]), ["--combine", "mean"])
        self.assertEqual(inkensemble.plan_flags({"method": "zscore", "robust": True, "combine": "trimmed",
                                                 "weights": {"b": 2, "a": 1, "c": 3, "d": 1}}, ["a", "b", "c", "d"]),
                         ["--robust", "--combine", "trimmed", "--trim", "0.25", "--weights", "1.0", "2.0", "3.0",
                          "1.0"])

    def test_backend_entry_names_the_plan_setting(self):
        self.assertEqual(inkensemble.BACKEND["zscore"]["settings"], {"ink": {"ensemble": {"method": "zscore"}}})
        self.assertEqual(inkensemble.BACKEND["zscore"]["compute"], "cpu")


if __name__ == "__main__":
    unittest.main()
