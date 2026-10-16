"""Training lines from your own records (kit/letterlines.py), on synthetic images with random weights."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent

try:
    import numpy as np
    from kit import letterlines as LL
    from kit import letterread as R
    try:
        from test_letterread import lined_image, random_weights, run_cli
    except ImportError:   # run as tests.test_letterlines
        from tests.test_letterread import lined_image, random_weights, run_cli
except ImportError:  # the core kit is standard library only
    np = LL = R = None

# lined_image(): 150 x 400, four lines of 16 px letters centred on rows 30, 60, 90 and 120
ROWS = (30, 60, 90, 120)


def load_script(name):
    sys.path.insert(0, str(ROOT / "scripts" / "letters"))
    try:
        return __import__(name)
    finally:
        sys.path.remove(str(ROOT / "scripts" / "letters"))


@unittest.skipIf(np is None, "numpy not installed")
class TextTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(LL.clean_text("ἐν ἀρχῇ ἦν ὁ λόγος"), ("ΕΝΑΡΧΗΗΝΟΛΟΓΟϹ", []))
        self.assertEqual(LL.clean_text("Σσς ϲ?Α"), ("ϹϹϹϹ?Α", []))
        self.assertEqual(LL.clean_text("ΑΒ̣Γ"), ("ΑΒΓ", []))         # a dot under a letter is dropped, the letter kept
        text, bad = LL.clean_text("ΑB[Γ]·")
        self.assertEqual(text, "ΑΓ")
        self.assertEqual(len(bad), 4)
        self.assertIn("Latin", bad[0])
        self.assertIn("LEFT SQUARE BRACKET", bad[1])
        self.assertIn("'?'", bad[3])                                         # the reader's '·': write the letter or '?'

    def test_reference_problems_name_each_fault_and_the_fix(self):
        self.assertEqual(LL.reference_problems("ΚΑΙΤΟΥϹ?"), [])
        latin = LL.reference_problems("KAI")
        self.assertEqual(len(latin), 3)
        self.assertIn("LATIN CAPITAL LETTER K", latin[0])
        self.assertIn("type the Greek Κ", latin[0])
        self.assertIn("type the Greek Ϲ", LL.reference_problems("C")[0])               # Latin C looks like lunate sigma
        self.assertIn("Cyrillic", LL.reference_problems("Р")[0])
        for sigma in "Σσςϲ":
            self.assertIn("lunate sigma Ϲ", LL.reference_problems(sigma)[0], sigma)
        self.assertIn("plain capital Α", LL.reference_problems("ἀ")[0])
        self.assertIn("plain capital Τ", LL.reference_problems("τ")[0])
        self.assertIn("without spaces", LL.reference_problems("Α Β")[0])
        self.assertIn("'?'", LL.reference_problems("Α·")[0])
        self.assertIn("Greek capitals only", LL.reference_problems("Q")[0])
        self.assertEqual(len(LL.reference_problems("ςςς")), 1)                              # each character once
        self.assertEqual(LL.reference_problems("Α?Β", wildcard=None)[0][:3], "'?'")      # no wildcard here
        self.assertEqual(LL.reference_problems("ΑΒ", alphabet="Α")[0][:3], "'Β'")        # another model's alphabet

    def test_check_references_refuses_with_the_alphabet(self):
        refs = {"g0": "ΚΑΙ", "g1": "KAI", "g2": "ΤΟΥς"}
        with self.assertRaises(ValueError) as cm:
            LL.check_references(refs, source="refs.json")
        msg = str(cm.exception)
        self.assertTrue(msg.startswith("refs.json: 2 reference text(s)"), msg)
        self.assertIn("g1: 'KAI'", msg)
        self.assertIn("g2: 'ΤΟΥς'", msg)
        self.assertNotIn("g0", msg)
        self.assertIn(LL.ALPHABET, msg)
        ok = {"g0": "ΚΑΙ?"}
        self.assertIs(LL.check_references(ok), ok)
        self.assertEqual(LL.check_references([("a", "ΑΒ")]), [("a", "ΑΒ")])
        with self.assertRaises(ValueError) as cm:
            LL.check_references({f"g{i}": "A" for i in range(30)}, limit=5)
        self.assertIn("and 25 more", str(cm.exception))
        self.assertEqual(len(LL.ALPHABET), 24)

    def test_wildcard_edit_distance(self):
        cases = [("ΑΒΓ", "ΑΒΓ", 0), ("ΑΓ", "ΑΒΓ", 1), ("ΑΧΓ", "ΑΒΓ", 1), ("ΑΧΓ", "Α?Γ", 0), ("ΑΓ", "Α?Γ", 0),
                 ("ΑΧΨΓ", "Α?Γ", 1), ("", "??", 0), ("", "Α?Β", 2), ("Α", "", 1), ("ΑΒΓ", "", 3)]
        for hyp, ref, d in cases:
            self.assertEqual(LL.wild_edit_distance(hyp, ref), d, (hyp, ref))
        self.assertEqual(LL.wild_edit_distance("ΑΒΓ", "ΑΒΓ"), R.edit_distance("ΑΒΓ", "ΑΒΓ"))
        self.assertEqual(LL.ctc_frames_needed("ΛΛΑ?Α"), 6)       # 4 letters, a blank between the Λs, one between the Αs
        self.assertEqual(LL.ctc_frames_needed("Α?Α"), 3)                      # the '?' may be nothing: Α, blank, Α


@unittest.skipIf(np is None, "numpy not installed")
class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        np.save(self.d / "page.npy", lined_image())

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        p = self.d / name
        p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def check(self, path, **kw):
        return LL.check_records(LL.load_records(path), path.parent, **kw)

    def test_three_ways_to_write_records(self):
        lines = [{"image": "page.npy", "text": "ΑΒΓΔΕ", "y": 30, "letter_px": 16, "x0": 0, "x1": 120},
                 {"image": "page.npy", "text": "ΖΗΘ?Κ", "y": 60, "letter_px": 16, "x0": 0, "x1": 120, "split": "test"}]
        a = self.check(self.write("a.json", lines))
        b = self.check(self.write("b.json", {"image": "page.npy", "letter_px": 16, "note": "mine",
                                             "lines": [{k: v for k, v in L.items() if k not in ("image", "letter_px")}
                                                       for L in lines]}))
        c = self.check(self.write("c.csv", "image,text,y,letter_px,x0,x1,split\npage.npy,ΑΒΓΔΕ,30,16,0,120,\n"
                                           "page.npy,ΖΗΘ?Κ,60,16,0,120,test\n"))
        for plans, errors, warnings in (a, b, c):
            self.assertEqual((errors, warnings), ([], []))
            self.assertEqual([(p["text"], p["y"], p["x1"], p["width"], p["visible"], p["wildcards"]) for p in plans],
                             [("ΑΒΓΔΕ", 30.0, 120.0, 120, 5, 0), ("ΖΗΘ?Κ", 60.0, 120.0, 120, 4, 1)])
        self.assertEqual(a[0][0]["band_rows"], [round(30 - 1.1 * 16, 1), round(30 + 1.15 * 16, 1)])
        self.assertEqual([p["where"] for p in c[0]], ["c.csv line 2", "c.csv line 3"])
        only = self.check(self.write("a.json", lines), split="test")[0]
        self.assertEqual([p["text"] for p in only], ["ΖΗΘ?Κ"])
        self.assertIn("no record has split 'dev'", self.check(self.write("a.json", lines), split="dev")[1][0])

    def test_every_problem_is_reported_at_once(self):
        recs = [{"image": "page.npy", "text": "ΑΒΓ", "y": 30},                                   # no letter_px
                {"image": "missing.png", "text": "ΑΒΓ", "y": 30, "letter_px": 16},
                {"image": "page.npy", "text": "ABΓ", "y": 30, "letter_px": 16},                  # Latin A and B
                {"image": "page.npy", "text": "ΑΒΓ", "y": 400, "letter_px": 16},                 # below the image
                {"image": "page.npy", "text": "ΑΒΓΔΕΖΗΘ", "y": 30, "letter_px": 16, "x0": 0, "x1": 20},   # too narrow
                {"image": "page.npy", "text": "???", "y": 30, "letter_px": 16},
                {"image": "page.npy", "text": "ΑΒΓ", "y": 30, "letter_px": -2},
                {"image": "page.npy", "text": "ΑΒΓ", "y": 30, "letter_px": 16, "polarity": "auto"},
                {"image": "page.npy", "text": "ΑΒΓ", "y": 30, "letter_px": 16, "crop": [0, 10]},
                {"image": "page.npy", "text": "ΑΒΓ", "y": 30, "letter_px": 16, "x0": 300, "x1": 200}]
        plans, errors, warnings = self.check(self.write("r.json", recs))
        self.assertEqual(plans, [])
        self.assertEqual(len(errors), len(recs), errors)
        for i, want in enumerate(["missing letter_px", "no such file", "Latin", "outside", "too narrow", "no letters",
                                  "letter_px", "polarity", "crop", "x0"]):
            self.assertIn(f"record {i + 1}:", errors[i])
            self.assertIn(want, errors[i])
        self.assertIn("relative to the records file's folder", errors[1])
        with self.assertRaisesRegex(LL.RecordsError, "unknown field.*letterpx"):
            LL.load_records(self.write("u.json", [{"image": "page.npy", "letterpx": 16}]))
        with self.assertRaisesRegex(LL.RecordsError, "cannot be a default"):
            LL.load_records(self.write("u.json", {"text": "Α", "lines": []}))
        with self.assertRaisesRegex(LL.RecordsError, "unknown column"):
            LL.load_records(self.write("u.csv", "image,txt\npage.npy,Α\n"))

    def test_warnings_for_lines_that_look_wrong(self):
        recs = [{"image": "page.npy", "text": "ΑΒ", "y": 30, "letter_px": 16},                    # 2 letters on 400 px
                {"image": "page.npy", "text": "ΑΒΓΔΕ", "y": 5, "letter_px": 16, "x1": 100},      # band above the image
                {"image": "page.npy", "text": "ΑΒΓΔΕ", "y": 64, "letter_px": 16, "x1": 100},
                {"image": "page.npy", "text": "ΑΒΓΔΕ", "y": 60, "letter_px": 16, "x1": 100}]     # the line above again
        plans, errors, warnings = self.check(self.write("w.json", recs))
        self.assertEqual((len(plans), errors), (4, []))
        self.assertTrue(any("record 1:" in w and "px a letter" in w for w in warnings), warnings)
        self.assertTrue(any("record 2:" in w and "beyond" in w for w in warnings), warnings)
        self.assertTrue(any("record 4 and" in w or "and w.json record 4" in w for w in warnings), warnings)
        self.assertIn("4 lines from 1 image(s), 17 letters and 0 '?'", LL.plan_text(plans, warnings))


@unittest.skipIf(np is None, "numpy not installed")
class CutTest(unittest.TestCase):
    """A cut band is exactly the band the reader reads on that row with --lines Y --deskew 0."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.net = R.LineNet(random_weights(self.d / "w.npz"))

    def tearDown(self):
        self.tmp.cleanup()

    def reader_bands(self, img, **kw):
        """The bands analyze() hands the network for its data lines (no nulls)."""
        seen = []
        real = R.LineNet.log_probs

        def spy(net, band):
            seen.append(np.array(band))
            return real(net, band)
        with mock.patch.object(R.LineNet, "log_probs", spy):
            R.analyze(img, self.net, nulls=0, deskew_deg=0, columns="off", scale_search=False, **kw)
        return seen

    def cut(self, recs, **kw):
        path = self.d / "r.json"
        path.write_text(json.dumps(recs), encoding="utf-8")
        plans, errors, _ = LL.check_records(LL.load_records(path), self.d)
        self.assertEqual(errors, [])
        return LL.cut_lines(plans, **kw)

    def test_bands_are_what_the_reader_reads(self):
        img = lined_image()
        np.save(self.d / "page.npy", img)
        imgs, texts, where = self.cut([{"image": "page.npy", "text": "ΑΒΓ", "y": y, "letter_px": 16} for y in ROWS])
        for y, band in zip(ROWS, imgs):
            (want,) = self.reader_bands(img, letter_px=16, lines=[y])
            self.assertEqual(band.shape, (36, 400))
            np.testing.assert_allclose(band, want, atol=1e-6)
        self.assertEqual(texts, ["ΑΒΓ"] * 4)
        self.assertEqual(where[0]["image"], "page.npy")
        # twice the size, letters 32 px, and part of the line: the same band, cut at x0 and x1
        big = np.kron(img, np.ones((2, 2), np.float32))
        np.save(self.d / "big.npy", big)
        imgs, _, _ = self.cut([{"image": "big.npy", "text": "ΑΒΓ", "y": 2 * ROWS[1], "letter_px": 32, "x0": 100,
                                "x1": 500}])
        (want,) = self.reader_bands(big, letter_px=32, lines=[2 * ROWS[1]])
        np.testing.assert_allclose(imgs[0], want[:, 50:250], atol=1e-6)

    def test_crop_and_block_averaged_loads(self):
        img = np.kron(lined_image(), np.ones((4, 4), np.float32))            # 600 x 1600, letters 64 px
        np.save(self.d / "big.npy", img)
        # a crop: y is relative to it, and the image is normalised over the crop, as a read of the crop is
        crop = [100, 500, 200, 1400]
        imgs, _, _ = self.cut([{"image": "big.npy", "text": "ΑΒΓ", "y": 4 * ROWS[1] - 100, "letter_px": 64,
                                "crop": crop}])
        (want,) = self.reader_bands(img[100:500, 200:1400], letter_px=64, lines=[4 * ROWS[1] - 100])
        np.testing.assert_allclose(imgs[0], want, atol=1e-6)
        # over the pixel budget: block-averaged by 2 while loading, as the reader loads it
        a, k, _ = R.load_reduced(self.d / "big.npy", letter_px=64, max_pixels=200_000)
        self.assertEqual(k, 2)
        imgs, _, _ = self.cut([{"image": "big.npy", "text": "ΑΒΓ", "y": 4 * ROWS[2], "letter_px": 64}],
                              max_pixels=200_000)
        (want,) = self.reader_bands(R.normalize_for_reading(a, max_pixels=200_000), letter_px=64, lines=[4 * ROWS[2]],
                                    input_scale=k, normalized=True)
        np.testing.assert_allclose(imgs[0], want, atol=1e-6)

    def test_dark_ink_is_inverted_as_the_reader_inverts_it(self):
        img = 1.0 - lined_image()
        np.save(self.d / "photo.npy", img)
        imgs, _, _ = self.cut([{"image": "photo.npy", "text": "ΑΒΓ", "y": ROWS[0], "letter_px": 16, "polarity": "dark"}])
        (want,) = self.reader_bands(img, letter_px=16, lines=[ROWS[0]], polarity="dark")
        np.testing.assert_allclose(imgs[0], want, atol=1e-6)


@unittest.skipIf(np is None, "numpy not installed")
class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        np.save(self.d / "page.npy", lined_image())
        self.recs = self.d / "lines.json"
        self.recs.write_text(json.dumps({"image": "page.npy", "letter_px": 16, "lines": [
            {"text": "ΑΒΓΔΕΖΗΘΙΚ", "y": 30, "split": "train", "id": "a"},
            {"text": "ΛΜΝΞΟ?ΡϹΤΥ", "y": 60, "split": "train"},
            {"text": "ΦΧΨΩΑΒΓΔΕΖ", "y": 90, "split": "test"},
            {"text": "ΗΘΙΚΛΜΝΞΟΠ", "y": 120, "split": "test"}]}, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_writes_the_format_finetune_maps_reads(self):
        out = self.d / "train.npz"
        plans, warnings, meta = LL.build(self.recs, out, split="train")
        self.assertEqual((len(plans), meta["lines"], meta["letters"], meta["wildcards"]), (2, 2, 19, 1))
        self.assertEqual(meta["records"]["file"], "lines.json")
        self.assertNotIn(str(self.d), json.dumps(meta))                          # file names, never a folder
        imgs, texts, where, meta2 = LL.load_lines(out)
        self.assertEqual(texts, ["ΑΒΓΔΕΖΗΘΙΚ", "ΛΜΝΞΟ?ΡϹΤΥ"])
        self.assertEqual((imgs[0].dtype, imgs[0].shape), (np.uint8, (36, 400)))
        self.assertEqual((where[0]["id"], where[0]["split"], meta2), ("a", "train", meta))
        # the script that fine-tunes reads it with p1667_align.load_lines, and encodes its texts
        align = load_script("p1667_align")
        imgs2, texts2, _, _ = align.load_lines(out)
        self.assertEqual(texts2, texts)
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(imgs, imgs2)))
        finetune = load_script("finetune_maps")
        self.assertEqual(finetune.ALPHABET, LL.ALPHABET)
        self.assertEqual(finetune.encode(texts[1])[5], finetune.WILD)
        # a dry run decodes no image and writes nothing
        with mock.patch.object(R, "load_reduced", side_effect=AssertionError("decoded")):
            plans, _, _ = LL.build(self.recs, None, dry_run=True)
        self.assertEqual(len(plans), 4)

    def test_command_line(self):
        out, test = self.d / "train.npz", self.d / "test.npz"
        code, stdout, err = run_cli(["letterlines", "build", str(self.recs), "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("4 lines from 1 image(s), 39 letters and 1 '?'", stdout)
        self.assertIn("dry run: nothing was cut or written", stdout)
        self.assertFalse(out.exists())
        code, stdout, err = run_cli(["letterlines", "build", str(self.recs), "--split", "train", "--out", str(out)])
        self.assertEqual(code, 0, err)
        self.assertIn("2 lines, 19 letters and 1 '?'", stdout)
        code, _, err = run_cli(["letterlines", "build", str(self.recs), "--split", "test", "--out", str(test)])
        self.assertEqual(code, 0, err)
        try:
            import PIL  # noqa: F401
            # every split, with a preview, into a file of its own: test.npz stays the held-out split scored below
            code, _, err = run_cli(["letterlines", "build", str(self.recs), "--out", str(self.d / "all.npz"),
                                    "--preview", str(self.d / "p.png")])
            self.assertEqual(code, 0, err)
            from PIL import Image
            with Image.open(self.d / "p.png") as im:
                self.assertGreater(im.size[1], 4 * 72)
        except ImportError:
            pass
        bad = self.d / "bad.json"
        bad.write_text(json.dumps([{"image": "page.npy", "text": "AB", "y": 30, "letter_px": 16},
                                   {"image": "nope.npy", "text": "ΑΒ", "y": 30, "letter_px": 16}]), encoding="utf-8")
        code, _, err = run_cli(["letterlines", "build", str(bad), "--out", str(self.d / "bad.npz")])
        self.assertEqual(code, 2)
        self.assertIn("2 problems in the records; nothing was cut", err)
        self.assertEqual(err.count("error: "), 2)
        self.assertFalse((self.d / "bad.npz").exists())
        code, _, err = run_cli(["letterlines", "build", str(self.recs)])
        self.assertEqual(code, 2)
        self.assertIn("--out LINES.npz, or --dry-run", err)
        # score held-out lines with two models: errors per line, totals and the paired difference
        w1, w2 = random_weights(self.d / "w1.npz"), random_weights(self.d / "w2.npz", seed=1)
        code, stdout, err = run_cli(["letterlines", "score", str(test), "--weights", str(w1), "--weights", str(w2),
                                     "--json", "--out", str(self.d / "score.json")])
        self.assertEqual(code, 0, err)
        res = json.loads(stdout)
        self.assertEqual(res["note"], R.NOTE)
        self.assertEqual([m["weights"]["file"] for m in res["models"]], ["w1.npz", "w2.npz"])
        self.assertEqual(res["models"][0]["letters"], 20)          # the two test lines, 10 letters each
        for m, j in zip(res["models"], range(2)):
            self.assertEqual(m["errors"], sum(L["errors"][j] for L in res["lines"]))
        for L in res["lines"]:
            for s, e in zip(L["reads"], L["errors"]):
                self.assertEqual(e, LL.wild_edit_distance(s, L["text"]))
        d = res["diff"][0]
        self.assertAlmostEqual(d["cer_diff"], res["models"][1]["cer"] - res["models"][0]["cer"], places=3)
        self.assertLessEqual(d["ci95"][0], d["ci95"][1])
        code, stdout, _ = run_cli(["letterlines", "score", str(test), "--weights", str(w1)])
        self.assertIn("model 0: w1.npz: character error", stdout)


    def test_build_makes_its_folders_as_the_guide_runs_it(self):
        """The guide's chain in a fresh clone, which has no work/ folder: build makes work/letters/ itself."""
        empty = self.d / "clone"
        empty.mkdir()
        one = self.d / "one.json"
        one.write_text(json.dumps({"image": str(self.d / "page.npy"), "letter_px": 16, "lines": [
            {"text": "ΑΒΓΔΕΖΗΘΙΚ", "y": 30, "split": "train"}, {"text": "ΦΧΨΩΑΒΓΔΕΖ", "y": 90, "split": "test"}]},
            ensure_ascii=False), encoding="utf-8")
        here = os.getcwd()
        os.chdir(empty)
        try:
            args = ["letterlines", "build", str(one), "--split", "test", "--out", "work/letters/mine-test.npz"]
            try:
                import PIL  # noqa: F401
                args += ["--preview", "work/previews/mine-test.png"]
            except ImportError:
                pass
            code, stdout, err = run_cli(args)
            self.assertEqual(code, 0, err)
            self.assertTrue((empty / "work" / "letters" / "mine-test.npz").is_file())
            if "--preview" in args:
                self.assertTrue((empty / "work" / "previews" / "mine-test.png").is_file())
            code, _, err = run_cli(["letterlines", "build", str(self.recs), "--out", "work/letters"])
            self.assertEqual(code, 2)
            self.assertIn("is a folder", err)
            # bad records make no folder
            code, _, _ = run_cli(["letterlines", "build", str(self.d / "missing.json"), "--out", "new/x.npz"])
            self.assertEqual(code, 2)
            self.assertFalse((empty / "new").exists())
            # one test line and two models: the plain difference, and a note that one line gives no interval
            w1, w2 = random_weights(self.d / "w1.npz"), random_weights(self.d / "w2.npz", seed=1)
            code, stdout, err = run_cli(["letterlines", "score", "work/letters/mine-test.npz", "--weights", str(w1),
                                         "--weights", str(w2), "--json"])
            self.assertEqual(code, 0, err)
            res = json.loads(stdout)
            (d,) = res["diff"]
            self.assertAlmostEqual(d["cer_diff"], res["models"][1]["cer"] - res["models"][0]["cer"], places=3)
            self.assertIsNone(d["ci95"])
            self.assertIn("one test line: no interval", d["note"])
            code, stdout, _ = run_cli(["letterlines", "score", "work/letters/mine-test.npz", "--weights", str(w1),
                                       "--weights", str(w2)])
            self.assertIn("model 1 minus model 0: ", stdout)
            self.assertIn("(one test line: no interval; give two lines or more)", stdout)
        finally:
            os.chdir(here)

if __name__ == "__main__":
    unittest.main()
