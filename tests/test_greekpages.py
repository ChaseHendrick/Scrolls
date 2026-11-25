"""Tests for kit.greekpages (synthetic Greek book-hand pages as ink-probability maps)."""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

HAVE_SCIPY = np is not None and importlib.util.find_spec("scipy") is not None
TEXT = ("Μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος οὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε, πολλὰς δ᾽ ἰφθίμους ψυχὰς "
        "Ἄϊδι προΐαψεν ἡρώων, αὐτοὺς δὲ ἑλώρια τεῦχε κύνεσσιν οἰωνοῖσί τε πᾶσι, Διὸς δ᾽ ἐτελείετο βουλή.")


@unittest.skipIf(np is None, "needs numpy")
class TestTextAndStyle(unittest.TestCase):
    def setUp(self):
        from kit import greekpages
        self.G = greekpages

    def test_clean_text(self):
        G = self.G
        self.assertEqual(G.clean_text("Μῆνιν ἄειδε, θεά!"), "ΜΗΝΙΝΑΕΙΔΕΘΕΑ")
        self.assertEqual(G.clean_text("σοφός ς Σ abc 123"), "ϹΟΦΟϹϹϹ")
        self.assertTrue(set(G.clean_text(TEXT)) <= set(G.ALPHABET))

    def test_every_letter_has_a_shape(self):
        G = self.G
        self.assertEqual(set(G.GLYPHS), set(G.ALPHABET))
        for ch in G.ALPHABET:
            w, strokes = G.glyph_strokes(ch)
            self.assertGreaterEqual(w, 0.0)
            self.assertTrue(strokes and all(s.shape[1] == 2 and len(s) >= 2 for s in strokes))
        with self.assertRaises(G.PagesError):
            G.glyph_strokes("Q")

    def test_text_bank_and_exclude(self):
        G = self.G
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.txt", "eval.txt"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write(TEXT)
            with open(os.path.join(d, "short.txt"), "w", encoding="utf-8") as f:
                f.write("ΑΒΓ")
            pieces, stats = G.text_bank(d, exclude=["eval.txt"])
            self.assertEqual((stats["files"], stats["excluded"], stats["pieces"]), (3, 1, 1))
            self.assertEqual(pieces[0], G.clean_text(TEXT))
            with self.assertRaises(G.PagesError):
                G.text_bank(os.path.join(d, "short.txt"))
            with self.assertRaises(G.PagesError):
                G.text_bank(os.path.join(d, "missing"))

    def test_style_is_pluggable(self):
        G = self.G
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            with open(p, "w") as f:
                json.dump({"name": "mine", "hand": {"letter_height_mm": 2.5, "nib_contrast": [1.5, 2.0]}}, f)
            s = G.load_style(p)
            self.assertEqual(s["name"], "mine")
            self.assertEqual(s["hand"]["letter_height_mm"], 2.5)
            self.assertEqual(s["map"], G.default_style()["map"])
            for bad in ({"hand": {"letter_hieght_mm": 2}}, {"hand": {"nib_contrast": [2.0, 1.0]}},
                        {"map": {"dropout": "high"}}, [1, 2]):
                with open(p, "w") as f:
                    json.dump(bad, f)
                with self.assertRaises(G.PagesError):
                    G.load_style(p)

    def test_draw_ranges(self):
        G = self.G
        rng = np.random.default_rng(0)
        for _ in range(20):
            v = G.draw({"a": [1.0, 2.0], "b": [0, 3], "c": 7.5}, rng)
            self.assertTrue(1.0 <= v["a"] <= 2.0)
            self.assertIsInstance(v["b"], int)
            self.assertTrue(0 <= v["b"] <= 3)
            self.assertEqual(v["c"], 7.5)


@unittest.skipUnless(HAVE_SCIPY, "needs scipy")
class TestPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kit import greekpages
        cls.G = greekpages
        cls.pieces = [greekpages.clean_text(TEXT)]

    def test_deterministic_and_seeded(self):
        G = self.G
        a, b, c = G.page(3, self.pieces, size_px=128), G.page(3, self.pieces, size_px=128), G.page(4, self.pieces,
                                                                                                    size_px=128)
        self.assertTrue(np.array_equal(a["map"], b["map"]))
        self.assertEqual(a["boxes"], b["boxes"])
        self.assertFalse(np.array_equal(a["map"], c["map"]))

    def test_labels_agree(self):
        G = self.G
        for seed in range(4):
            pg = G.page(seed, self.pieces, size_px=192)
            m = pg["map"]
            self.assertTrue(np.isfinite(m).all() and m.min() >= 0.0 and m.max() <= 1.0)
            self.assertEqual("".join(b[0] for b in pg["boxes"]), "".join(pg["text"]))
            self.assertTrue(set("".join(pg["text"])) <= set(G.ALPHABET))
            cover = np.zeros(m.shape, bool)
            for _, y0, x0, y1, x1 in pg["boxes"]:
                self.assertTrue(0 <= y0 < y1 <= m.shape[0] and 0 <= x0 < x1 <= m.shape[1])
                cover[y0:y1, x0:x1] = True
            self.assertTrue(pg["mask"].any())
            self.assertFalse((pg["mask"] & ~cover).any(), "ink outside every letter box")

    def test_ink_shows_in_the_map_and_a_blank_page_does_not(self):
        G = self.G
        s = G.default_style()
        s["hand"].update(letter_height_mm=2.5, nib_thick_mm=0.4, ink_load_drop=0.0)
        s["map"].update(dropout=0.0, warp_mm=0.0, blur_sigma_mm=0.03, ink_amp=0.9, tone_gain=4.0)
        s["background"].update(level=0.1, noise=0.02, fibre_amp=0.0, blotches=0, strokes=0)
        pg = G.page(1, self.pieces, s, size_px=192)
        on, off = pg["map"][pg["mask"]].mean(), pg["map"][~pg["mask"]].mean()
        self.assertGreater(on - off, 0.4)
        s["map"]["ink_amp"] = 0.0
        blank = G.page(1, self.pieces, s, size_px=192)
        self.assertLess(abs(blank["map"][blank["mask"]].mean() - blank["map"][~blank["mask"]].mean()), 0.05)

    def test_save_load_generate(self):
        G = self.G
        with tempfile.TemporaryDirectory() as d:
            msgs = []
            paths = G.generate(d, self.pieces, 2, 7, size_px=96, progress=msgs.append)
            self.assertEqual(msgs, ["PROGRESS 1/2 page-7-00000.npz", "PROGRESS 2/2 page-7-00001.npz"])
            pg = G.load_page(paths[0])
            ref = G.page(700000, self.pieces, size_px=96)
            self.assertEqual(pg["boxes"], ref["boxes"])
            self.assertEqual(pg["text"], ref["text"])
            self.assertTrue(np.allclose(pg["map"], ref["map"], atol=1e-3))
            mt = os.path.getmtime(paths[0])
            G.generate(d, self.pieces, 2, 7, size_px=96, progress=None)
            self.assertEqual(os.path.getmtime(paths[0]), mt)

    def test_bad_size(self):
        with self.assertRaises(self.G.PagesError):
            self.G.page(1, self.pieces, size_px=16)

    def test_cli(self):
        G = self.G
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(G.main(["style"]), 0)
        self.assertEqual(json.loads(out.getvalue())["name"], "generic-bookhand")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(G.main(["gen", "/nonexistent-out", "--text", "/nonexistent-text"]), 1)
        self.assertIn("no text at", err.getvalue())


if __name__ == "__main__":
    unittest.main()
