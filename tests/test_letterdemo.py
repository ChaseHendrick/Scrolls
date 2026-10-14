import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import cli

try:
    import numpy as np
    from kit import letterdemo as D
    try:
        from test_letterread import random_weights
    except ImportError:   # run as tests.test_letterdemo
        from tests.test_letterread import random_weights
except ImportError:  # the core kit is standard library only
    np = D = random_weights = None

ROOT = Path(__file__).resolve().parent.parent


def letterdata():
    """scripts/letters/letterdata.py (numpy only at import), or None."""
    sys.path.insert(0, str(ROOT / "scripts" / "letters"))
    try:
        import letterdata as L
        return L
    except ImportError:
        return None
    finally:
        sys.path.remove(str(ROOT / "scripts" / "letters"))


def fake_result(lines, status, kept, nulls):
    """A read() result with only the fields the demo uses: lines (column, y, letters) and the control block."""
    return {"lines": [{"column": 0, "y": float(y), "letters": [{"glyph": c} for c in text]} for y, text in lines],
            "control": {"status": status, "letters_kept": kept, "null_letters_kept": list(nulls),
                        "ratio": round(kept / max(1, max(nulls)), 2)}}


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


@unittest.skipIf(np is None, "numpy not installed")
class GlyphsTest(unittest.TestCase):
    def test_skeleton_hand_is_letterdata_s(self):
        # The demo draws the training scripts' own skeleton hand; its copy must not drift from it.
        L = letterdata()
        if L is None:
            self.skipTest("scripts/letters/letterdata.py does not import")
        self.assertEqual(D.ALPHABET, L.ALPHABET)
        self.assertEqual(list(D.SKELETONS), list(L.SKELETONS))
        self.assertEqual(D.SKELETONS, L.SKELETONS)

    def test_every_letter_has_a_skeleton(self):
        self.assertEqual(len(D.ALPHABET), 24)
        self.assertEqual("".join(D.SKELETONS), D.ALPHABET)

    def test_page_lines_are_seeded_orders_of_the_alphabet(self):
        lines = D.page_lines()
        self.assertEqual(len(lines), D.N_LINES)
        for line in lines:
            self.assertEqual(sorted(line), sorted(D.ALPHABET))
        self.assertEqual(lines, D.page_lines())
        self.assertNotEqual(lines, D.page_lines(seed=D.SEED + 7))

    def test_draw_segments_is_a_round_pen(self):
        ink = D.draw_segments((21, 41), [((5.0, 10.0), (35.0, 10.0))], 4.0)
        self.assertEqual(ink.dtype, np.float32)
        self.assertEqual(float(ink[10, 20]), 1.0)          # on the stroke
        self.assertEqual(float(ink[11, 20]), 1.0)          # within the pen's radius
        self.assertEqual(float(ink[13, 20]), 0.0)          # beyond it
        self.assertEqual(float(ink[10, 39]), 0.0)          # past the stroke's end and the pen
        self.assertGreater(float(ink[10, 36]), 0.0)        # the round end
        self.assertTrue(0.0 <= float(ink.min()) and float(ink.max()) <= 1.0)
        # a segment off the image draws nothing and does not fail
        self.assertEqual(float(D.draw_segments((10, 10), [((50.0, 50.0), (60.0, 60.0))], 3.0).max()), 0.0)

    def test_render_page_is_fixed_and_bright_where_letters_are(self):
        lines = D.page_lines()
        img, truth = D.render_page(lines)
        img2, truth2 = D.render_page(lines)
        self.assertTrue(np.array_equal(img, img2))
        self.assertEqual(truth, truth2)
        self.assertEqual(img.dtype, np.float32)
        self.assertTrue(0.0 <= float(img.min()) and float(img.max()) <= 1.0)
        self.assertEqual([t["text"] for t in truth], lines)
        h = D.LETTER_PX
        for t in truth:
            self.assertEqual(len(t["x"]), len(t["text"]))
            self.assertEqual(t["x"], sorted(t["x"]))
            band = img[int(t["y"] - h / 2):int(t["y"] + h / 2)]
            gap = img[int(t["y"] + 0.75 * h):int(t["y"] + 1.25 * h)]     # between this line and the next
            self.assertGreater(float(band.mean()), float(gap.mean()) + 0.05)
        self.assertLess(max(x for t in truth for x in t["x"]), img.shape[1] - h)

    def test_noise_page_is_the_ground_without_letters(self):
        img, truth = D.render_page(D.page_lines())
        noise = D.noise_page(img.shape)
        self.assertEqual(noise.shape, img.shape)
        self.assertTrue(np.array_equal(noise, D.noise_page(img.shape)))
        self.assertLess(abs(float(noise.mean()) - 0.12), 0.03)
        h = D.LETTER_PX
        y = int(truth[0]["y"])
        self.assertLess(float(noise[y - h // 2:y + h // 2].mean()), float(img[y - h // 2:y + h // 2].mean()) - 0.05)


@unittest.skipIf(np is None, "numpy not installed")
class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.truth = [{"text": "ΑΒΓΔ", "y": 40.0, "x": []}, {"text": "ΕΖΗΘ", "y": 104.0, "x": []}]
        self.good = fake_result([(104, "ΕΖΗΘ"), (40, "ΑΒΓΔ")], "strong", 8, [0, 1, 0, 2])
        self.noise = fake_result([], "none", 0, [1, 0, 2, 0])

    def test_character_error_reads_lines_top_down_by_column(self):
        self.assertEqual(D.decoded(self.good), ["ΑΒΓΔ", "ΕΖΗΘ"])
        self.assertEqual(D.character_error(self.good, self.truth), 0.0)
        one_off = fake_result([(40, "ΑΒΓ"), (104, "ΕΖΗΘΙ")], "strong", 8, [0])
        self.assertAlmostEqual(D.character_error(one_off, self.truth), 2 / 8)
        two_columns = {"lines": [{"column": 1, "y": 10.0, "letters": [{"glyph": "Ε"}]},
                                 {"column": 0, "y": 50.0, "letters": [{"glyph": "Α"}]}]}
        self.assertEqual(D.decoded(two_columns), ["Α", "Ε"])

    def test_pass_needs_strong_text_low_error_and_quiet_noise(self):
        ok, numbers = D.judge(self.good, self.noise, self.truth)
        self.assertTrue(ok)
        self.assertEqual(numbers["checks"], {"text_status": True, "character_error": True, "noise_status": True})
        self.assertEqual(numbers["text"]["letters_drawn"], 8)
        self.assertEqual(numbers["rule"], D.RULE)
        json.dumps(numbers)
        # a weak text page fails
        weak = fake_result([(40, "ΑΒΓΔ"), (104, "ΕΖΗΘ")], "weak", 8, [3])
        self.assertEqual(D.judge(weak, self.noise, self.truth)[1]["checks"]["text_status"], False)
        # strong, but the wrong letters: fails on the character error
        wrong = fake_result([(40, "ΩΩΩΩ"), (104, "ΕΖΗΘ")], "strong", 8, [0])
        ok, numbers = D.judge(wrong, self.noise, self.truth)
        self.assertFalse(ok)
        self.assertEqual(numbers["checks"], {"text_status": True, "character_error": False, "noise_status": True})
        # noise that beats its nulls fails, weakly or strongly; too_few passes
        for status, passes in (("weak", False), ("strong", False), ("too_few", True), ("none", True)):
            noise = fake_result([], status, 5, [1])
            self.assertEqual(D.judge(self.good, noise, self.truth)[0], passes, status)

    def test_max_cer_boundary(self):
        one_wrong = fake_result([(40, "ΑΒΓΩ"), (104, "ΕΖΗΘ")], "strong", 8, [0])
        self.assertTrue(D.judge(one_wrong, self.noise, self.truth, max_cer=1 / 8)[0])
        self.assertFalse(D.judge(one_wrong, self.noise, self.truth, max_cer=0.1)[0])


@unittest.skipIf(np is None, "numpy not installed")
class DemoRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        cls.weights = random_weights(cls.d / "random.npz")
        cls.out = D.run(str(cls.weights))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_random_weights_fail(self):
        out = self.out
        self.assertFalse(out["passed"])
        self.assertFalse(out["numbers"]["checks"]["character_error"])
        self.assertEqual(out["note"], D.R.NOTE)
        self.assertEqual(out["weights"]["file"], "random.npz")
        self.assertEqual([t["text"] for t in out["truth"]], D.page_lines())
        self.assertEqual(out["drawing"]["letter_px"], D.LETTER_PX)
        img, noise = out["_images"]
        self.assertEqual(img.shape, noise.shape)
        self.assertEqual(out["text_result"]["options"]["letter_px"], D.LETTER_PX)
        json.dumps({k: v for k, v in out.items() if k != "_images"}, ensure_ascii=False)
        text = D.report(out)
        self.assertIn("DEMO FAIL", text)
        self.assertNotIn("DEMO PASS", text)
        self.assertIn(D.R.NOTE, text)
        self.assertNotIn(str(self.d), text)

    def test_command_exit_codes(self):
        code, out, err = run_cli(["letterdemo", "--weights", str(self.weights), "--quiet"])
        self.assertEqual(code, 1)
        self.assertIn("DEMO FAIL", out)
        self.assertEqual(err, "")
        code, out, err = run_cli(["letterdemo", "--weights", str(self.d / "missing.npz"), "--quiet"])
        self.assertEqual(code, 2)
        self.assertIn("DEMO ERROR", err)
        self.assertEqual(out, "")
        a_file = self.d / "a-file"
        a_file.write_text("x", encoding="utf-8")
        code, out, err = run_cli(["letterdemo", "--weights", str(self.weights), "--out", str(a_file), "--quiet"])
        self.assertEqual(code, 2)
        self.assertIn("not a folder", err)

    def test_pass_prints_demo_pass_and_exits_0(self):
        # A reader that returns the drawn letters on the page and nothing on the noise: the rule passes.
        truth = D.render_page(D.page_lines())[1]
        text = fake_result([(t["y"], t["text"]) for t in truth], "strong", 96, [7, 0, 13, 2])
        noise = fake_result([], "none", 0, [2, 0, 2, 1])
        with mock.patch.object(D.R, "read", side_effect=[text, noise]) as read:
            code, out, err = run_cli(["letterdemo", "--weights", str(self.weights), "--quiet"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("DEMO PASS", out)
        self.assertEqual(read.call_count, 2)
        self.assertEqual([c.kwargs["letter_px"] for c in read.call_args_list], [D.LETTER_PX, D.LETTER_PX])
        with mock.patch.object(D.R, "read", side_effect=[text, noise]):
            code, out, err = run_cli(["letterdemo", "--weights", str(self.weights), "--quiet", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["passed"])
        self.assertEqual(data["numbers"]["text"]["character_error"], 0.0)
        self.assertEqual(data["decoded"], [t["text"] for t in truth])

    def test_out_folder(self):
        folder = self.d / "demo"
        code, out, err = run_cli(["letterdemo", "--weights", str(self.weights), "--out", str(folder)])
        self.assertEqual(code, 1)
        data = json.loads((folder / "demo.json").read_text(encoding="utf-8"))
        self.assertEqual(data["note"], D.R.NOTE)
        self.assertFalse(data["passed"])
        self.assertIn("text_result", data)
        self.assertNotIn(str(self.d), json.dumps(data, ensure_ascii=False))
        self.assertIn("wrote", err)
        try:
            import PIL  # noqa: F401
        except ImportError:
            return
        self.assertTrue((folder / "demo-page.png").is_file())
        self.assertTrue((folder / "demo-overlay.png").is_file())

    def test_console_script(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.letterdemo_main(["--weights", str(self.weights), "--quiet"])
        self.assertEqual(code, 1)
        self.assertIn("DEMO FAIL", out.getvalue())


class DemoWithoutNumpyTest(unittest.TestCase):
    def test_missing_numpy_is_an_error_not_a_traceback(self):
        import kit
        saved = kit.__dict__.pop("letterdemo", None)   # an imported module would be found on the package
        try:
            with mock.patch.dict(sys.modules, {"kit.letterdemo": None}):   # as when numpy is missing
                code, out, err = run_cli(["letterdemo", "--quiet"])
        finally:
            if saved is not None:
                kit.letterdemo = saved
        self.assertEqual(code, 2)
        self.assertIn("DEMO ERROR", err)
        self.assertIn("numpy", err)


if __name__ == "__main__":
    unittest.main()
