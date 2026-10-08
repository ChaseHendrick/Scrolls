import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

from kit import cli

try:
    import numpy as np
    from kit import letterread as R
except ImportError:  # the core kit is standard library only
    np = R = None

ROOT = Path(__file__).resolve().parent.parent
ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"


def random_weights(path, c=(4, 4, 6, 6, 8), letter_px=16, seed=0):
    """A linenet-v1 file with random weights and the training script's layer layout."""
    rng = np.random.default_rng(seed)
    c1, c2, c3, c4, c5 = c
    arrs, layers, k = {}, [], 0

    def add(shape, op, **kw):
        nonlocal k
        arrs[f"w{k}"] = rng.normal(0, 0.3, shape).astype(np.float32)
        arrs[f"b{k}"] = rng.normal(0, 0.05, shape[0]).astype(np.float32)
        layers.append(dict(op=op, id=k, **kw))
        k += 1

    add((c1, 1, 3, 3), "conv2d", pad=1)
    layers.append({"op": "maxpool", "k": [2, 2]})
    add((c2, c1, 3, 3), "conv2d", pad=1)
    layers.append({"op": "maxpool", "k": [2, 2]})
    add((c3, c2, 3, 3), "conv2d", pad=1)
    add((c3, c3, 3, 3), "conv2d", pad=1)
    layers.append({"op": "maxpool", "k": [2, 1]})
    add((c4, c3, 3, 3), "conv2d", pad=1)
    add((c5, c4, 4, 1), "collapse")
    add((c5, c5, 3), "conv1d_res", dilation=1)
    add((c5, c5, 3), "conv1d_res", dilation=2)
    add((len(ALPHABET) + 1, c5, 1), "head")
    meta = {"alphabet": ALPHABET, "blank": 0, "letter_px": letter_px, "band": [1.1, 1.15], "stride": 4,
            "layers": layers, "format": "linenet-v1"}
    np.savez(path, meta=np.array(json.dumps(meta, ensure_ascii=False)), **arrs)
    return path


def lined_image(n_lines=4, pitch=30, letter=16, width=400, seed=0):
    rng = np.random.default_rng(seed)
    a = rng.normal(0.1, 0.03, (n_lines * pitch + pitch, width))
    for i in range(n_lines):
        y = pitch // 2 + i * pitch + pitch // 2
        for x in range(10, width - 20, 22):
            a[y - letter // 2:y + letter // 2, x:x + 3] = 0.9
            a[y - letter // 2:y - letter // 2 + 3, x:x + 12] = 0.9
    return a.astype(np.float32)


@unittest.skipIf(np is None, "numpy not installed")
class NetworkTest(unittest.TestCase):
    def test_conv2d_matches_direct_sum(self):
        rng = np.random.default_rng(1)
        x = rng.normal(size=(3, 7, 9)).astype(np.float32)
        w = rng.normal(size=(2, 3, 3, 3)).astype(np.float32)
        b = rng.normal(size=2).astype(np.float32)
        got = R._conv2d(x, w, b, 1)
        xp = np.pad(x, ((0, 0), (1, 1), (1, 1)))
        want = np.zeros((2, 7, 9))
        for o in range(2):
            for i in range(7):
                for j in range(9):
                    want[o, i, j] = (xp[:, i:i + 3, j:j + 3] * w[o]).sum() + b[o]
        self.assertTrue(np.allclose(got, want, atol=1e-4))

    def test_conv1d_dilated_same_padding(self):
        rng = np.random.default_rng(2)
        x = rng.normal(size=(2, 11)).astype(np.float32)
        w = rng.normal(size=(3, 2, 3)).astype(np.float32)
        b = np.zeros(3, np.float32)
        got = R._conv1d(x, w, b, 2)
        xp = np.pad(x, ((0, 0), (2, 2)))
        want = np.stack([sum(w[o, :, j] @ xp[:, j * 2:j * 2 + 11] for j in range(3)) for o in range(3)])
        self.assertTrue(np.allclose(got, want, atol=1e-5))

    def test_log_probs_shape_and_normalised(self):
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
            self.assertEqual(net.band_rows, 36)
            lp = net.log_probs(np.random.default_rng(0).random((36, 101)).astype(np.float32))
            self.assertEqual(lp.shape, (26, 25))       # ceil(101 / 4) frames, 24 letters plus blank
            self.assertTrue(np.allclose(np.exp(lp).sum(axis=1), 1, atol=1e-5))

    def test_rejects_other_formats(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.npz"
            np.savez(p, meta=np.array(json.dumps({"format": "other"})))
            with self.assertRaises(ValueError):
                R.LineNet(p)

    def test_matches_torch_export(self):
        try:
            import torch
        except ImportError:
            self.skipTest("torch not installed")
        sys.path.insert(0, str(ROOT / "scripts" / "letters"))
        try:
            import train_linenet as T
        except ImportError as exc:
            self.skipTest(f"training script needs {exc.name}")
        finally:
            sys.path.pop(0)
        torch.manual_seed(0)
        model = T.LineNet(c=(4, 4, 6, 6, 8))
        for m in model.modules():          # non-trivial BatchNorm statistics, so folding is tested
            if isinstance(m, (torch.nn.BatchNorm1d, torch.nn.BatchNorm2d)):
                m.running_mean.uniform_(-0.2, 0.2)
                m.running_var.uniform_(0.5, 2.0)
                m.weight.data.uniform_(0.5, 1.5)
                m.bias.data.uniform_(-0.1, 0.1)
        model.eval()
        x = torch.rand(1, 1, 36, 64)
        with torch.no_grad():
            want = model(x)[0].numpy().T
        with tempfile.TemporaryDirectory() as d:
            T.export_npz(model, Path(d) / "w.npz")
            got = R.LineNet(Path(d) / "w.npz").logits(x[0, 0].numpy())
        self.assertLess(float(np.abs(got - want).max()), 1e-4)


@unittest.skipIf(np is None, "numpy not installed")
class DecodeTest(unittest.TestCase):
    def frames(self, seq):
        """Log-probs that put nearly all mass on the given class per frame (0 = blank)."""
        lp = np.full((len(seq), 25), math.log(1e-4))
        for t, k in enumerate(seq):
            lp[t, k] = math.log(1 - 24e-4)
        return lp

    def test_greedy_collapses_repeats_and_blanks(self):
        a, b = ALPHABET.index("Α") + 1, ALPHABET.index("Β") + 1
        out = R.ctc_greedy(self.frames([0, a, a, 0, a, b, b, 0]), ALPHABET)
        self.assertEqual("".join(o[0] for o in out), "ΑΑΒ")
        self.assertEqual((out[0][2], out[0][3]), (1, 2))
        self.assertGreater(out[0][1], 0.99)

    def test_beam_without_lm_agrees_with_greedy(self):
        a, b = ALPHABET.index("Ε") + 1, ALPHABET.index("Ν") + 1
        lp = self.frames([0, a, 0, b, b, 0])
        self.assertEqual(R.ctc_beam(lp, ALPHABET)[0], "ΕΝ")

    def test_lm_breaks_a_tie_and_only_then(self):
        e, o = ALPHABET.index("Ε") + 1, ALPHABET.index("Ο") + 1
        lp = np.full((3, 25), math.log(1e-4))
        lp[0, 0] = lp[2, 0] = math.log(1 - 24e-4)
        lp[1, e] = lp[1, o] = math.log(0.5 - 12e-4)    # an ambiguous letter

        class PreferO:
            def logp_next(self, prefix):
                p = np.full(24, 0.01)
                p[ALPHABET.index("Ο")] = 1 - 0.23
                return np.log(p)

        self.assertEqual(R.ctc_beam(lp, ALPHABET, PreferO(), lm_weight=1.0)[0], "Ο")
        # a clear letter is not overruled by a modest weight
        lp2 = self.frames([0, e, 0])
        self.assertEqual(R.ctc_beam(lp2, ALPHABET, PreferO(), lm_weight=0.5)[0], "Ε")

    def test_force_align_finds_each_letter(self):
        a, b, c = (ALPHABET.index(x) + 1 for x in "ΚΑΙ")
        lp = self.frames([0, a, a, 0, 0, b, 0, c, c, c, 0])
        al = R.force_align(lp, "ΚΑΙ", ALPHABET)
        self.assertEqual([(x[0], x[1], x[2]) for x in al], [("Κ", 1, 2), ("Α", 5, 5), ("Ι", 7, 9)])
        self.assertGreater(min(x[3] for x in al), 0.99)
        # a repeated letter needs a blank between its two copies
        n = ALPHABET.index("Ν") + 1
        al = R.force_align(self.frames([n, 0, n]), "ΝΝ", ALPHABET)
        self.assertEqual([(x[1], x[2]) for x in al], [(0, 0), (2, 2)])
        self.assertIsNone(R.force_align(self.frames([n, n]), "ΝΝ", ALPHABET))
        self.assertEqual(R.force_align(self.frames([0]), "", ALPHABET), [])

    def test_locate_finds_a_line_with_errors(self):
        text = "ΚΑΙΤΟΝΘΕΟΝΚΑΙΤΟΥϹΘΕΟΥϹΑΡΕΤΗΝΔΕΚΑΙϹΟΦΙΑΝΕΧΕΙΝΤΟΥϹΑΝΘΡΩΠΟΥϹ"
        start = text.index("ϹΟΦΙΑΝΕΧΕΙΝ")
        hits = R.locate("ϹΟΦΙΑΝΕΧΕΙΝ", text)
        self.assertEqual(hits[0], (start, start + 11, 0))
        noisy = R.locate("ϹΟΦΙΛΝΕΧΙΝ", text)          # one substitution, one deletion
        self.assertEqual(noisy[0][2], 2)
        self.assertLessEqual(abs(noisy[0][0] - start), 1)
        self.assertEqual(R.locate("", text), [])

    def test_edit_distance(self):
        self.assertEqual(R.edit_distance("ΚΑΙ", "ΚΑΙ"), 0)
        self.assertEqual(R.edit_distance("ΚΑΙ", "ΚΙ"), 1)
        self.assertEqual(R.edit_distance("", "ΑΒ"), 2)


@unittest.skipIf(np is None, "numpy not installed")
class PageTest(unittest.TestCase):
    def test_nulls_keep_grey_levels(self):
        a = lined_image()
        for kind, b in R.null_images(a, 16, n=2, seed=3):
            self.assertEqual(b.shape, a.shape)
            if kind == "phase":
                self.assertTrue(np.allclose(np.sort(b, axis=None), np.sort(a, axis=None)))
            else:
                self.assertAlmostEqual(float(b.sum()), float(a.sum()), places=0)
            self.assertFalse(np.allclose(a, b))

    def test_find_lines_and_pitch(self):
        a = lined_image(n_lines=5, pitch=30)
        pitch = R.line_pitch(a, lo=10)
        self.assertTrue(28 <= pitch <= 32, pitch)
        self.assertEqual(len(R.find_lines(a, 16, pitch)), 5)

    def test_deskew_undoes_a_shear(self):
        a = lined_image(n_lines=5, pitch=30)
        tilted = R.shear(a, -3.0)
        angle, _ = R.deskew(tilted, 16, max_deg=6, step=0.5)
        self.assertAlmostEqual(angle, 3.0, delta=0.6)

    def test_normalize_polarity(self):
        a = np.linspace(0, 1, 100).reshape(10, 10)
        self.assertGreater(R.normalize(a, "bright")[9, 9], 0.9)
        self.assertLess(R.normalize(a, "dark")[9, 9], 0.1)

    def test_verdict_needs_nulls(self):
        self.assertIn("no control", R.verdict(10, []))
        self.assertIn("NOT above", R.verdict(3, [3, 1]))
        self.assertIn("well above", R.verdict(40, [2, 5]))

    def test_read_runs_end_to_end_with_controls(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            res = R.read(lined_image(), w, letter_px=16, nulls=2)
        self.assertIn("not a reading", res["note"])
        self.assertEqual(len(res["control"]["nulls"]), 2)
        self.assertEqual(set(res["orientation"]["letters_kept"]), {"as_is", "mirrored", "rot180"})
        self.assertGreaterEqual(res["p_min"], 0.5)
        for line in res["lines"]:
            self.assertEqual(len(line["ink_only"]), len(line["letters"]))
            for letter in line["letters"]:
                self.assertIn(letter["glyph"], ALPHABET)
                self.assertEqual(len(letter["box"]), 4)
        self.assertIn("control:", R.text_summary(res))

    def test_scale_search_reports_its_table(self):
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
            res = R.analyze(lined_image(), net, nulls=2)
            given = R.analyze(lined_image(), net, nulls=2, letter_px=16)
        self.assertEqual(len(res["scale_search"]), len(R.SCALE_STEPS))
        self.assertIn(res["letter_px"], [t["letter_px"] for t in res["scale_search"]])
        self.assertIn("scale search", res["letter_px_from"])
        self.assertNotIn("scale_search", given)
        self.assertFalse(given["letter_px_estimated"])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "img.npy"
            np.save(img, lined_image())
            out = Path(d) / "res.json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.main(["letterread", str(img), "--weights", str(w), "--letter-px", "16", "--nulls", "2",
                                 "--no-orientation", "--json", "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(buf.getvalue())["engine"], "linenet")
            self.assertTrue(out.exists())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["letterread", str(img), "--weights", str(Path(d) / "missing.npz")]), 2)


if __name__ == "__main__":
    unittest.main()
