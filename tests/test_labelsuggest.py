"""kit/labelsuggest.py on synthetic readers' maps: tied ranks, a planted region where readers disagree, the
shuffle control, the matched random and agree arms, the vote, margin and edge measures, the files `map` writes and
the command line. No published data, no network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import numpy as np
    import tifffile  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

if np is not None:
    from kit import labelsuggest as ls

H = W = 256
BLOCK = (slice(64, 128), slice(128, 192))      # where reader 3 disagrees: tiles (64, 128) of a 64 px grid


def need():
    if np is None:
        raise unittest.SkipTest("needs numpy and tifffile")


def readers(seed=0, planted=True):
    """Three readers of one smooth 'ink' field: two agree everywhere; the third agrees except in BLOCK, where it
    is inverted. Each has its own small noise and its own scale and dtype."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W]
    base = 0.5 + 0.5 * np.sin(xx / 9.0) * np.cos(yy / 13.0)
    r1 = base + 0.03 * rng.standard_normal((H, W))
    r2 = base + 0.03 * rng.standard_normal((H, W))
    r3 = base + 0.03 * rng.standard_normal((H, W))
    if planted:
        r3[BLOCK] = 1.0 - r3[BLOCK]
    to_u8 = lambda a: np.clip(np.rint(a * 255), 0, 255).astype(np.uint8)          # noqa: E731
    return [to_u8(r1), (r2 * 60000).astype(np.uint16), r3.astype(np.float32)], base


def in_block(t):
    return BLOCK[0].start <= t["y"] < BLOCK[0].stop and BLOCK[1].start <= t["x"] < BLOCK[1].stop


class Ranks(unittest.TestCase):
    def setUp(self):
        need()

    def test_ties_share_a_rank_and_scale_does_not_matter(self):
        a = np.array([[0, 0, 5], [5, 5, 9]], np.float32)
        valid = np.ones_like(a, bool)
        r = ls.midranks(a, valid)
        self.assertEqual(r[0, 0], r[0, 1])
        self.assertEqual(len({float(v) for v in r[a == 5]}), 1)
        self.assertAlmostEqual(float(r.max()), 1.0)
        self.assertTrue(np.array_equal(r, ls.midranks(a * 7 + 3, valid)))
        valid[1, 2] = False
        self.assertEqual(ls.midranks(a, valid)[1, 2], 0.0)

    def test_identical_readers_have_no_spread(self):
        maps, _ = readers()
        s, _ = ls.spread([maps[0], maps[0].astype(np.float32) * 3], np.ones((H, W), bool))
        self.assertEqual(float(s.max()), 0.0)


class Suggest(unittest.TestCase):
    def setUp(self):
        need()

    def test_planted_disagreement_is_suggested_and_the_controls_are_not(self):
        maps, _ = readers()
        res, s, valid = ls.suggest(maps, names=["a", "b", "c"], tile=32, top=4, nulls=5, measure="rank")
        self.assertEqual(res["tiles_eligible"], (H // 32) * (W // 32))
        # the four tiles of the planted 64 px block are exactly the suggestions
        self.assertEqual(sum(in_block(t) for t in res["top"]), 4, res["top"])
        self.assertEqual(res["structure"]["verdict"], "targeted")
        self.assertGreater(res["structure"]["top_mean_spread"], res["structure"]["null_max"])
        # controls: the agree arm never lands there, the matched random arm mostly does not
        self.assertEqual(sum(in_block(t) for t in res["controls"]["agree"]), 0)
        self.assertLess(sum(in_block(t) for t in res["controls"]["random"]), 4)
        self.assertEqual(len(res["controls"]["random"]), 4)

    def test_without_planted_disagreement_the_structure_control_says_flat(self):
        maps, _ = readers(planted=False)
        same = [maps[0], maps[0].astype(np.float32) * 2.0 + 1.0]
        res, _, _ = ls.suggest(same, tile=32, top=4, measure="rank")
        self.assertEqual(res["structure"]["verdict"], "flat")
        res2, _, _ = ls.suggest(maps, tile=32, top=4, nulls=5, seed=3, measure="rank")
        self.assertNotEqual(sum(in_block(t) for t in res2["top"]), 4)

    def test_valid_mask_and_errors(self):
        maps, _ = readers()
        valid = np.ones((H, W), np.uint8)
        valid[:, 128:] = 0                       # the planted block is outside: it cannot be suggested
        res, _, _ = ls.suggest(maps, valid=valid, tile=32, top=4, nulls=0, measure="rank")
        self.assertFalse(any(in_block(t) for t in res["top"]))
        self.assertEqual(res["structure"]["verdict"], "unchecked")
        with self.assertRaises(ls.SuggestError):
            ls.suggest(maps[:1])
        with self.assertRaises(ls.SuggestError):
            ls.suggest([maps[0], maps[1][:128]])
        with self.assertRaises(ls.SuggestError):
            ls.suggest(maps, tile=512)


class Files(unittest.TestCase):
    def setUp(self):
        need()

    def write_maps(self, d, maps):
        import tifffile
        paths = []
        for i, m in enumerate(maps):
            p = Path(d) / f"r{i + 1}.tif"
            tifffile.imwrite(str(p), m)
            paths.append(p)
        return paths

    def test_map_writes_the_masks_and_the_record(self):
        from kit import vc3d_io
        maps, _ = readers()
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.write_maps(tmp, maps)
            out = Path(tmp) / "out"
            res = ls.run_map(out, paths, tile=32, top=4, measure="rank")
            self.assertEqual([i["name"] for i in res["inputs"]], ["r1", "r2", "r3"])
            h, w, ch, data = vc3d_io.read_png_gray((out / ls.OUT_FILES["suggest"]).read_bytes())
            mask = np.frombuffer(data, np.uint8).reshape(h, w)
            self.assertEqual((h, w, ch), (H, W, 1))
            self.assertEqual(int((mask == 255).sum()), 4 * 32 * 32)
            self.assertTrue((mask[BLOCK] == 255).all())
            for key in ("random", "agree", "disagreement"):
                self.assertTrue((out / ls.OUT_FILES[key]).is_file(), key)
            rec = ls.load_result(out / "suggest.json")
            self.assertEqual(rec["settings_digest"], res["settings_digest"])
            (out / "bad.json").write_text(json.dumps({"kind": "other", "version": 2}))
            with self.assertRaises(ls.SuggestError):
                ls.load_result(out / "bad.json")

    def test_command_line_prints_the_verdict_and_refuses_bad_input(self):
        import contextlib
        import io
        maps, _ = prob_readers()
        with tempfile.TemporaryDirectory() as tmp:
            paths = [str(p) for p in self.write_maps(tmp, maps)]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = ls.main(["map", str(Path(tmp) / "out"), *paths, "--tile", "32", "--top", "4"])
            self.assertEqual(code, 0)
            self.assertIn("4 tiles of 64 suggested; structure targeted", buf.getvalue())
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = ls.main(["map", str(Path(tmp) / "out2"), paths[0]])
            self.assertEqual(code, 2)
            self.assertIn("labelsuggest: disagreement needs at least two readers' maps", err.getvalue())


def prob_readers(seed=0, planted=True, n=5):
    """n probability readers (uint8, 0..255) of one ink field: ink where base > 0.5, plus a low-valued, noisy
    background in which each reader's noise orders the pixels differently. Inside BLOCK, half the readers (rounded
    down) call the opposite. The rank measure is drawn to the background noise; the vote measure is not."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W]
    ink = (np.sin(xx / 9.0) * np.cos(yy / 13.0)) > 0.3
    out = []
    for i in range(n):
        p = np.where(ink, 0.9, 0.05) + np.where(ink, 0.02, 0.04) * rng.standard_normal((H, W))
        if planted and i < n // 2:
            p[BLOCK] = 1.0 - p[BLOCK]
        out.append(np.clip(np.rint(np.clip(p, 0, 1) * 255), 0, 255).astype(np.uint8))
    return out, ink


class Vote(unittest.TestCase):
    """Version 2's measures: vote (the default), margin and edge, with the full-scale rule."""

    def setUp(self):
        need()

    def test_full_scale_rule(self):
        v = np.ones((2, 2), bool)
        self.assertEqual(ls.full_scale(np.array([[0, 0.5], [1.0, 0.2]]), v), 1.0)
        self.assertEqual(ls.full_scale(np.array([[0, 7], [255, 3]], np.float32), v), 255.0)
        self.assertEqual(ls.full_scale(np.array([[0, 7], [60000, 3]], np.float32), v), 65535.0)
        with self.assertRaises(ls.SuggestError):
            ls.full_scale(np.array([[0, 7], [70000, 3]], np.float32), v)

    def test_value_scale_rule(self):
        self.assertEqual(ls.value_scale(0.9), 1.0)
        self.assertEqual(ls.value_scale(254), 255.0)
        self.assertEqual(ls.value_scale(60000), 65535.0)
        self.assertIsNone(ls.value_scale(70000))

    def test_vote_finds_planted_disagreement_and_the_controls_do_not(self):
        maps, _ = prob_readers()
        res, s, _ = ls.suggest(maps, tile=32, top=4, nulls=5)
        self.assertEqual(res["settings"]["measure"], "vote")
        self.assertEqual(res["version"], 2)
        self.assertEqual(res["full_scales"], [255.0] * 5)
        self.assertEqual(sum(in_block(t) for t in res["top"]), 4, res["top"])
        self.assertEqual(res["structure"]["verdict"], "targeted")
        self.assertEqual(sum(in_block(t) for t in res["controls"]["agree"]), 0)
        self.assertLessEqual(float(s.max()), 1.0)
        m, _, _ = ls.suggest(maps, tile=32, top=4, nulls=0, measure="margin")
        self.assertEqual(sum(in_block(t) for t in m["top"]), 4, m["top"])

    def test_vote_is_flat_without_disagreement_where_rank_is_drawn_to_background_noise(self):
        maps, ink = prob_readers(planted=False)
        res, s, _ = ls.suggest(maps, tile=32, top=4, nulls=5)
        self.assertEqual(float(s.max()), 0.0)                    # every reader calls every pixel the same way
        self.assertEqual(res["structure"]["verdict"], "flat")
        # why rank is not the default: its spread is highest where the maps are lowest (the background noise)
        r, rs, _ = ls.suggest(maps, tile=32, top=4, nulls=0, measure="rank")
        self.assertGreater(float(rs[~ink].mean()), float(rs[ink].mean()))

    def test_edge_scores_committee_ink_edges(self):
        call = np.zeros((128, 128), bool)
        call[40:80, 40:80] = True
        valid = np.ones(call.shape, bool)
        e = ls.ink_edge(call, valid)
        self.assertEqual(float(e[60, 60]), 0.0)                  # inside the ink: no edge
        self.assertEqual(float(e[40, 60]), 1.0)                  # on the boundary
        self.assertEqual(int(e.sum()), (4 * 40 - 4) + 4 * 40)     # the square's border ring and the ring outside it
        valid[:, :50] = False                                    # an invalid neighbor never makes an edge
        self.assertEqual(float(ls.ink_edge(call, valid)[60, 39]), 0.0)
        maps = [np.where(call, 200, 10).astype(np.uint8) for _ in range(3)]
        res, s, _ = ls.suggest(maps, tile=32, top=4, nulls=0, measure="edge")
        self.assertEqual(res["settings"]["measure"], "edge")
        for t in res["top"]:                                     # every picked tile touches the square's boundary
            self.assertTrue(float(s[t["y"]:t["y"] + 32, t["x"]:t["x"] + 32].sum()) > 0, t)

    def test_cut_and_measure_are_checked_and_recorded(self):
        maps, _ = prob_readers()
        with self.assertRaises(ls.SuggestError):
            ls.suggest(maps, measure="entropy")
        with self.assertRaises(ls.SuggestError):
            ls.suggest(maps, cut=1.0)
        a, _, _ = ls.suggest(maps, tile=32, top=4, nulls=0)
        b, _, _ = ls.suggest(maps, tile=32, top=4, nulls=0, cut=0.3)
        self.assertNotEqual(a["settings_digest"], b["settings_digest"])
        self.assertEqual(a["settings_digest"], ls._digest({"version": 2, **ls.DEFAULTS, "nulls": 0, "tile": 32,
                                                             "top": 4}))


if __name__ == "__main__":
    unittest.main()
