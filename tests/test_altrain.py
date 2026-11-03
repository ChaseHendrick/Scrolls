"""kit altrain: layout, label-free picks, histogram AUC, the paired bootstrap and the readout rule (synthetic)."""
import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

if np is not None:
    from kit import altrain as A


def synth_hists(n_blocks, sep, rng, n_px=600, ink_share=0.3):
    """(n_blocks, 2, BINS) histograms of uint8 scores: background ~ N(100, 30), ink ~ N(100 + sep, 30)."""
    h = np.zeros((n_blocks, 2, A.BINS), np.int64)
    for b in range(n_blocks):
        k = int(n_px * ink_share)
        bg = np.clip(np.rint(rng.normal(100, 30, n_px - k)), 0, 255).astype(int)
        ik = np.clip(np.rint(rng.normal(100 + sep, 30, k)), 0, 255).astype(int)
        h[b, 0] = np.bincount(bg, minlength=A.BINS)
        h[b, 1] = np.bincount(ik, minlength=A.BINS)
    return h


def synth_segment(seps, rev_sep=0.0, n_blocks=20, seed=0, drop=None):
    """Run ids of one segment (the plan's) with forward histograms at each arm's separation per budget; rev_sep a
    number or a per-arm dict."""
    rng = np.random.default_rng(seed)
    sel = {f"{f:.2f}": {"SUGGEST": [[0]], "UNCERTAIN": [[0]], "RANDOM": [[0]] * A.RANDOM_DRAWS,
                        "SHUF": [[0]] * A.SHUF_DRAWS} for f in A.BUDGETS}
    ids = [r["id"] for r in A.runs(sel)]
    fwd, rev = {}, {}
    for r in ids:
        arm = r.split("-")[1]
        fwd[r] = synth_hists(n_blocks, seps[arm] + rng.normal(0, 0.5), rng)
        rev[r] = synth_hists(n_blocks, rev_sep[arm] if isinstance(rev_sep, dict) else rev_sep, rng)
    if drop:
        fwd.pop(drop)
    return ids, fwd, rev


BASE = {"n_pool": 500, "n_test_blocks": 20, "auc_inplace": 0.80, "auc_displaced": 0.55, "plan_sha256": "x"}


@unittest.skipIf(np is None, "needs numpy")
class Layout(unittest.TestCase):
    def test_pool_never_touches_a_test_block_and_counts_follow_the_pattern(self):
        sup = np.ones((1024, 1536), bool)
        lay = A.layout(sup)
        self.assertTrue(A.disjoint(lay))
        # (by + bx) % 3 == 0 on a 4 x 6 block grid: 8 test blocks
        self.assertEqual(len(lay["test_blocks"]), 8)
        for y, x in lay["test_blocks"]:
            self.assertEqual((y // A.BLOCK + x // A.BLOCK) % A.PERIOD, 0)
        pm = A.pool_mask(sup.shape, lay["pool"])
        self.assertFalse((pm & lay["test_mask"]).any())
        self.assertGreater(len(lay["pool"]), 0)

    def test_disjoint_fails_when_a_pool_tile_is_moved_into_a_test_block(self):
        lay = A.layout(np.ones((1024, 1024), bool))
        bad = dict(lay, pool=lay["pool"] + [tuple(lay["test_blocks"][0])])
        self.assertFalse(A.disjoint(bad))

    def test_unsupervised_area_gives_no_pool_or_test(self):
        sup = np.zeros((768, 768), bool)
        sup[:, :256] = True
        lay = A.layout(sup)
        for y, x in lay["pool"]:
            self.assertLess(x, 256)
        for y, x in lay["test_blocks"]:
            self.assertEqual(x, 0)

    def test_footprint_shape_must_match(self):
        with self.assertRaises(A.ALError):
            A.layout(np.ones((512, 512), bool), np.ones((256, 512), bool))


@unittest.skipIf(np is None, "needs numpy")
class Picks(unittest.TestCase):
    def test_edge_map_equals_labelsuggest_edge(self):
        from kit import labelsuggest as L
        rng = np.random.default_rng(3)
        maps = [rng.random((64, 80)).astype(np.float32) for _ in range(2)]
        valid = np.ones((64, 80), bool)
        valid[:5] = False
        ref, _ = L.disagreement(maps, valid, measure="edge")
        self.assertTrue(np.array_equal(A.edge_map(maps, valid), ref))

    def test_selections_are_fixed_sized_and_suggest_is_the_top_of_edge(self):
        rng = np.random.default_rng(0)
        edge = rng.random(400)
        ent = rng.random(400)
        sel = A.selections(edge, ent)
        self.assertEqual(sel, A.selections(edge, ent))
        for f in A.BUDGETS:
            r = sel[f"{f:.2f}"]
            k = A.k_of(400, f)
            self.assertEqual(r["k"], k)
            self.assertEqual(sorted(r["SUGGEST"][0]), sorted(np.argsort(-edge)[:k].tolist()))
            self.assertEqual(sorted(r["UNCERTAIN"][0]), sorted(np.argsort(-ent)[:k].tolist()))
            self.assertEqual(len(r["RANDOM"]), A.RANDOM_DRAWS)
            self.assertEqual(len({tuple(s) for s in r["RANDOM"]}), A.RANDOM_DRAWS)
            self.assertEqual(len(r["SHUF"]), A.SHUF_DRAWS)
            self.assertNotEqual(r["SHUF"][0], r["SUGGEST"][0])
        self.assertEqual(len(A.runs(sel)), len(A.BUDGETS) * (3 + 3 + A.RANDOM_DRAWS + A.SHUF_DRAWS))

    def test_ties_are_broken_at_random_not_by_position(self):
        edge = np.zeros(300)
        sel = A.selections(edge, edge)
        s = sel["0.05"]["SUGGEST"][0]
        self.assertNotEqual(s, list(range(len(s))))


@unittest.skipIf(np is None, "needs numpy")
class Scoring(unittest.TestCase):
    def test_histogram_auc_equals_the_rank_auc_with_ties(self):
        rng = np.random.default_rng(1)
        sc = A.to_u8(rng.random((256, 256)) ** 2)
        ink = rng.random((256, 256)) < 0.2 + 0.3 * (sc > 128)
        sup = rng.random((256, 256)) < 0.8
        h = A.block_hists(sc, ink, sup, [(0, 0)])
        self.assertAlmostEqual(float(A.auc_counts(h[0])), A.auc_direct(sc, ink, sup), places=10)

    def test_bootstrap_covers_zero_for_equal_arms_and_excludes_it_for_a_better_one(self):
        rng = np.random.default_rng(2)
        same = {"SUGGEST": np.stack([synth_hists(20, 30, rng) for _ in range(3)]),
                "RANDOM": np.stack([synth_hists(20, 30, rng) for _ in range(5)])}
        b, p = A.boot_arm_means(same, nboot=400)
        d = A.diff(b, p, "SUGGEST", "RANDOM")
        self.assertLessEqual(d["lower"], 0)
        self.assertGreaterEqual(d["upper"], 0)
        better = dict(same, SUGGEST=np.stack([synth_hists(20, 45, rng) for _ in range(3)]))
        b, p = A.boot_arm_means(better, nboot=400)
        self.assertGreater(A.diff(b, p, "SUGGEST", "RANDOM")["lower"], 0)


@unittest.skipIf(np is None, "needs numpy")
class Readout(unittest.TestCase):
    SEPS = {"SUGGEST": 45, "UNCERTAIN": 30, "RANDOM": 30, "SHUF": 30}
    FLAT = {"SUGGEST": 30, "UNCERTAIN": 30, "RANDOM": 30, "SHUF": 30}

    def seg(self, seps, name="s", seed=0, base=BASE, **kw):
        ids, f, r = synth_segment(seps, seed=seed, **kw)
        return A.segment_readout(name, f, r, base, ids, nboot=300)

    def test_a_planted_better_suggest_passes_on_two_segments(self):
        segs = [self.seg(self.SEPS, "a", 1), self.seg(self.SEPS, "b", 2), self.seg(self.FLAT, "c", 3)]
        self.assertTrue(segs[0]["passes"] and segs[1]["passes"])
        self.assertFalse(segs[2]["passes"])
        v = A.verdict(segs)
        self.assertEqual(v["verdict"], "PASS")
        self.assertEqual(sorted(v["passing"]), ["a", "b"])

    def test_equal_arms_fail(self):
        segs = [self.seg(self.FLAT, n, i) for i, n in enumerate("abcd")]
        self.assertEqual(A.verdict(segs)["verdict"], "FAIL")

    def test_reverse_depth_above_the_bar_voids_the_segment(self):
        s = self.seg(self.SEPS, rev_sep=25)            # reverse AUC about 0.72
        self.assertEqual(s["state"], "VOID")
        self.assertTrue(any("reverse-depth" in w for w in s["void_why"]))

    def test_shuffled_suggestions_better_than_random_void_the_segment(self):
        s = self.seg(dict(self.FLAT, SHUF=45))
        self.assertFalse(s["shuffle_control"]["holds"])
        self.assertEqual(s["state"], "VOID")

    def test_labels_that_do_not_track_the_ct_void_the_segment(self):
        s = self.seg(self.SEPS, base=dict(BASE, auc_displaced=0.79))
        self.assertEqual(s["state"], "VOID")

    def test_a_small_pool_or_too_few_test_blocks_void_the_segment(self):
        self.assertEqual(self.seg(self.SEPS, base=dict(BASE, n_pool=50))["state"], "VOID")
        self.assertEqual(self.seg(self.SEPS, base=dict(BASE, n_test_blocks=5))["state"], "VOID")

    def test_one_counted_segment_is_void_and_a_missing_run_incomplete(self):
        good = self.seg(self.SEPS, "a", 1)
        bad = self.seg(self.SEPS, "b", 2, rev_sep=25)
        self.assertEqual(A.verdict([good, bad])["verdict"], "VOID")
        ids, f, r = synth_segment(self.SEPS, drop=None)
        f.pop(ids[0])
        inc = A.segment_readout("c", f, r, BASE, ids, nboot=50)
        self.assertEqual(inc["state"], "INCOMPLETE")
        self.assertEqual(A.verdict([good, inc])["verdict"], "INCOMPLETE")

    def test_a_gain_present_equally_with_reversed_depth_does_not_count(self):
        # forward: SUGGEST above RANDOM; reverse: SUGGEST above RANDOM by as much, both reverse AUCs at or below 0.55
        s = self.seg(self.SEPS, rev_sep={"SUGGEST": 0, "UNCERTAIN": -15, "RANDOM": -15, "SHUF": -15})
        self.assertEqual(s["state"], "COUNTED")
        r = s["budgets"]["0.05"]
        self.assertGreater(r["SUGGEST-RANDOM"]["lower"], 0)
        self.assertLessEqual(r["forward_minus_reverse_gain"]["lower"], 0)
        self.assertFalse(s["passes"])

    def test_a_missing_base_record_is_incomplete_not_counted(self):
        ids, f, r = synth_segment(self.SEPS, seed=1)
        for base in ({}, dict(BASE, auc_displaced=None), {k: v for k, v in BASE.items() if k != "n_pool"}):
            out = A.segment_readout("a", f, r, base, ids, nboot=50)
            self.assertEqual(out["state"], "INCOMPLETE")
            self.assertFalse(out["counted"])

    def write(self, root, name, seed=1, base=None, plan_name=None):
        ids, f, r = synth_segment(self.SEPS, seed=seed)
        d = Path(root) / name
        (d / "runs").mkdir(parents=True)
        (d / "plan.json").write_text(json.dumps({"segment": plan_name or name, "runs": [{"id": i} for i in ids]}))
        sha = A._sha256(d / "plan.json")
        (d / "base.json").write_text(json.dumps(dict(base or BASE, plan_sha256=sha)))
        for i in ids:
            np.savez(d / "runs" / f"{i}.npz", fwd=f[i], rev=r[i], revealed_px=np.int64(1000),
                     revealed_ink_px=np.int64(300 if "SUGGEST" in i else 100))
        return d

    def test_readout_from_files(self):
        with tempfile.TemporaryDirectory() as t:
            self.write(t, "a", 1)
            self.write(t, "b", 2)
            rec = A.readout(t, nboot=200, segments=("a", "b"))
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["constants_sha256"], A.constants_sha256())
            self.assertFalse(rec["frozen_segment_set"])
            self.assertAlmostEqual(rec["segments"][0]["budgets"]["0.05"]["revealed_ink_ratio_suggest_random"], 3.0)

    def test_readout_wants_exactly_the_segment_set(self):
        with tempfile.TemporaryDirectory() as t:
            self.write(t, "a", 1)
            rec = A.readout(t, nboot=50, segments=("a", "b"))           # b never arrived
            self.assertEqual(rec["verdict"], "INCOMPLETE")
            self.write(t, "smoke", 3, plan_name="frag1")
            with self.assertRaises(A.ALError):                          # a folder of another segment
                A.readout(t, nboot=50, segments=("a", "b"))
        with tempfile.TemporaryDirectory() as t:
            self.write(t, "a", 1)
            self.write(t, "a2", 2, plan_name="a")
            with self.assertRaises(A.ALError):                          # a second copy of one segment
                A.readout(t, nboot=50, segments=("a",))
        with tempfile.TemporaryDirectory() as t:
            d = self.write(t, "a", 1)
            (d / "plan.json").write_text((d / "plan.json").read_text() + " ")
            with self.assertRaises(A.ALError):                          # plan changed after base.json
                A.readout(t, nboot=50, segments=("a",))

    def test_the_default_segment_set_is_the_fragment_benchmark(self):
        self.assertEqual(A.TEST_SEGMENTS, ("frag2", "frag3", "frag4"))
        self.assertIn("TEST_SEGMENTS", A.constants())


if __name__ == "__main__":
    unittest.main()
