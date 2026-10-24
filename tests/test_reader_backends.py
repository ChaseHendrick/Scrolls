"""Explicit reader routing, local-only models, word provenance and controls that can fail."""
import contextlib
import copy
import hashlib
import io
import json
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, reader_backends as B

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    np = None

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
WORD = "5\t1\t1\t1\t1\t1\t2\t3\t10\t5\t95.25\tROMA\n"


class RoutingTest(unittest.TestCase):
    def test_no_cross_script_fallback(self):
        self.assertEqual(B.validate_route("linenet", "greek"), ["grc"])
        self.assertEqual(B.validate_route("tesseract", "latin+grc"), ["lat", "grc"])
        for backend, language in (("linenet", "lat"), ("linenet", "grc+lat"), ("cloud", "grc")):
            with self.subTest(backend=backend, language=language), self.assertRaises(ValueError):
                B.read(None, backend=backend, language=language)
        for language in ("../lat", "eng+", "osd", "lat+latin", "--help", ""):
            with self.subTest(language=language), self.assertRaises(ValueError):
                B.languages(language)

    def test_missing_engine_is_a_capability_not_a_fallback(self):
        with mock.patch.object(B.shutil, "which", return_value=None):
            report = B.capabilities()
        self.assertFalse(report["tesseract"]["available"])
        self.assertIn("not installed", report["tesseract"]["reason"])
        self.assertEqual(report["linenet"]["languages"], ["grc"])

    def test_checkpoint_alphabet_must_match_the_greek_route(self):
        for alphabet in ("ABC", "ΑΒC"):
            net = SimpleNamespace(alphabet=alphabet)
            with self.subTest(alphabet=alphabet), self.assertRaisesRegex(ValueError, "alphabet is not Greek"):
                B.validate_linenet(net)
            self.assertEqual(net.alphabet, alphabet)
        net = SimpleNamespace(alphabet="ΑΒΓϹΩ·")
        self.assertIs(B.validate_linenet(net), net)
        for alphabet in (None, [], ["ΑΒ"], ""):
            with self.subTest(alphabet=alphabet), self.assertRaisesRegex(ValueError, "nonempty string"):
                B.validate_linenet(SimpleNamespace(alphabet=alphabet))

    def test_tesseract_uses_reported_model_directory(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(B.shutil, "which", return_value="/bin/tesseract"):
            with mock.patch.object(B, "_run", side_effect=[f'List of available languages in "{tmp}/" (2):\nlat\nosd\n',
                                                         "tesseract 5.5.0\n"]) as run:
                info = B.tesseract_info(tmp)
            self.assertEqual(info["languages"], ["lat"])
            self.assertEqual(info["directory"], Path(tmp).resolve())
            self.assertIn("--tessdata-dir", run.call_args_list[0].args[0])

    def test_raw_word_confidence_is_not_a_glyph_probability(self):
        word = B.parse_tsv(HEADER + WORD, (20, 40))[0]
        self.assertEqual(word["confidence"], 95.25)
        self.assertNotIn("p", word)
        self.assertEqual(word["box"], [3, 8, 2, 12])
        self.assertFalse(B.parse_tsv(HEADER + WORD, (20, 40), 99)[0]["kept"])
        for bad in (WORD.replace("95.25", "nan"), WORD.replace("95.25", "101"),
                    WORD.replace("\t10\t5\t", "\t100\t5\t")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                B.parse_tsv(HEADER + bad, (20, 40))
        with self.assertRaisesRegex(ValueError, "malformed TSV"):
            B.parse_tsv("not TSV", (20, 40))
        with self.assertRaisesRegex(ValueError, "malformed TSV"):
            B.parse_tsv(HEADER + "5\t1\n", (20, 40))

    def test_missing_version_is_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(B.shutil, "which", return_value="/bin/tesseract"), \
                mock.patch.object(B, "_run", side_effect=[f'List of available languages in "{tmp}" (1):\neng\n', ""]):
            with self.assertRaisesRegex(ValueError, "did not report its version"):
                B.tesseract_info()

    def test_timeout_is_bounded_and_reported(self):
        with mock.patch.object(B.subprocess, "run", side_effect=B.subprocess.TimeoutExpired("tesseract", 2)):
            with self.assertRaisesRegex(ValueError, "2 second timeout"):
                B._run(["tesseract"], 2)

    def test_success_exit_cannot_hide_a_failed_language(self):
        finished = SimpleNamespace(returncode=0, stdout=HEADER + WORD,
                                   stderr="Error opening data file qaa.traineddata\nFailed loading language 'qaa'\n")
        with mock.patch.object(B.subprocess, "run", return_value=finished):
            with self.assertRaisesRegex(ValueError, "could not load every requested language pack"):
                B._run(["tesseract"], 2)


@unittest.skipIf(np is None, "needs numpy and Pillow")
class ReaderTest(unittest.TestCase):
    def test_session_switches_greek_latin_greek_and_keeps_state_on_failure(self):
        net = SimpleNamespace(alphabet="ΑΒΓ", sha256="a" * 64, file="greek.npz")
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "lat.traineddata"
            pack.write_bytes(b"local Latin pack")
            model = {"file": pack.name, "sha256": hashlib.sha256(pack.read_bytes()).hexdigest()}
            ocr = {"models": [model], "backend": {"version": "tesseract test"}, "text": "ROMA"}
            with mock.patch("kit.letterread.load_weights", return_value=net), \
                    mock.patch.object(B, "_probe_linenet"), \
                    mock.patch("kit.letterread.read", side_effect=lambda *a, **kw: {"text": "ΑΒΓ"}), \
                    mock.patch.object(B, "tesseract_info", return_value={"directory": Path(tmp)}), \
                    mock.patch.object(B, "read_tesseract", side_effect=lambda *a, **kw: copy.deepcopy(ocr)):
                session = B.ReaderSession(weights=net)
                first = session.read(np.zeros((20, 40)))
                self.assertEqual(first["selection"]["backend"], "linenet")
                session.switch(backend="tesseract", language="lat", tessdata=tmp)
                self.assertEqual(session.read(np.zeros((20, 40)))["selection"]["languages"], ["lat"])
                saved = session.selection
                with self.assertRaises(ValueError):
                    session.switch(backend="linenet", language="lat", weights=net)
                self.assertEqual(session.selection, saved)
                with mock.patch.object(B, "read_tesseract", side_effect=ValueError("language packs not installed")):
                    with self.assertRaises(ValueError):
                        session.switch(backend="tesseract", language="qaa", tessdata=tmp)
                self.assertEqual(session.selection, saved)
                self.assertEqual(session.read(np.zeros((20, 40)))["text"], "ROMA")
                session.switch(weights=net)
                self.assertEqual(session.read(np.zeros((20, 40)))["selection"], first["selection"])
                detached = session.selection
                detached["languages"].append("lat")
                self.assertEqual(session.selection["languages"], ["grc"])

    def test_broken_greek_weights_do_not_replace_a_working_session(self):
        from tests.test_letterread import random_weights
        with tempfile.TemporaryDirectory() as tmp:
            valid = random_weights(Path(tmp) / "valid.npz")
            with np.load(valid, allow_pickle=False) as archive:
                fields = {name: archive[name] for name in archive.files if name != "w0"}
            broken = Path(tmp) / "broken.npz"
            np.savez(broken, **fields)
            session = B.ReaderSession(weights=valid)
            previous = session.selection
            with self.assertRaisesRegex(ValueError, "failed its initialization check"):
                session.switch(weights=broken)
            self.assertEqual(session.selection, previous)
            output = session.read(np.zeros((40, 80)), letter_px=16, nulls=1, orientation=False)
            self.assertEqual(output["weights"]["sha256"], previous["weights"]["sha256"])

    def test_session_refuses_model_changes_until_explicit_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "lat.traineddata"
            pack.write_bytes(b"old pack")
            model = {"file": pack.name, "sha256": hashlib.sha256(pack.read_bytes()).hexdigest()}
            with mock.patch.object(B, "tesseract_info", return_value={"directory": Path(tmp)}), \
                    mock.patch.object(B, "read_tesseract", return_value={"models": [model], "backend": {"version": "test"}}):
                session = B.ReaderSession(backend="tesseract", language="lat", tessdata=tmp)
            pack.write_bytes(b"new pack")
            with mock.patch.object(B, "read_tesseract") as inference:
                with self.assertRaisesRegex(ValueError, "pack changed"):
                    session.read(np.zeros((20, 40)))
                inference.assert_not_called()

    def test_model_hash_and_fixed_controls_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "lat.traineddata"
            pack.write_bytes(b"one local model")
            info = {"directory": Path(tmp), "languages": ["lat"], "version": "tesseract test", "executable": "/bin/tesseract"}
            with mock.patch.object(B, "tesseract_info", return_value=info), \
                    mock.patch.object(B, "_run", side_effect=[HEADER + WORD, HEADER, HEADER]) as run:
                result = B.read(np.arange(800).reshape(20, 40), backend="tesseract", language="lat")
            self.assertEqual(result["models"][0]["sha256"], hashlib.sha256(pack.read_bytes()).hexdigest())
            self.assertEqual(result["models"][0]["file"], "lat.traineddata")
            self.assertNotIn(tmp, json.dumps(result))
            self.assertEqual(result["text"], "ROMA")
            self.assertTrue(result["above_controls"])
            self.assertEqual(set(result["controls"]), {"blank", "tile_shuffle"})
            self.assertEqual(result["status"], "unverified_model_output")
            self.assertEqual(run.call_count, 3)
            self.assertIn("tessedit_create_tsv=1", run.call_args.args[0])
            # An equally confident control must make the check fail.
            with mock.patch.object(B, "tesseract_info", return_value=info), \
                    mock.patch.object(B, "_run", return_value=HEADER + WORD):
                result = B.read(np.arange(800).reshape(20, 40), backend="tesseract", language="lat")
            self.assertFalse(result["above_controls"])

    def test_invalid_requests_never_start_an_ocr_run(self):
        image = np.zeros((20, 40))
        for options in ({"psm": 0}, {"timeout": 0}, {"timeout": float("nan")}, {"timeout": 601},
                        {"min_confidence": 101}, {"polarity": "auto"}, {"seed": -1}, {"weights": "greek.npz"}):
            with self.subTest(options=options), mock.patch.object(B, "tesseract_info") as info:
                with self.assertRaises(ValueError):
                    B.read(image, backend="tesseract", language="lat", **options)
                info.assert_not_called()
        with mock.patch.object(B, "tesseract_info", return_value={"languages": ["eng"]}), \
                mock.patch.object(B, "_run") as run:
            with self.assertRaisesRegex(ValueError, "language packs not installed: lat"):
                B.read(image, backend="tesseract", language="lat")
            run.assert_not_called()

    def test_cli_refuses_incompatible_options_without_loading_weights(self):
        for flags in (["--weights", "letters-v2-real"], ["--weight-profile", "permissive"], ["--lm", "lm.npz"],
                      ["--csv", "words.csv"], ["--nulls", "0"]):
            with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()) as err, \
                    mock.patch("kit.letterread.load_weights") as load:
                code = cli.main(["letterread", "missing.png", "--backend", "tesseract", "--language", "lat", *flags])
            self.assertEqual(code, 2)
            self.assertIn("does not support", err.getvalue())
            load.assert_not_called()

    def test_cli_boxes_return_to_the_whole_input_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.png"
            Image.new("L", (60, 40), 255).save(source)
            out = Path(tmp) / "out.json"
            fake = {"text": "ROMA", "words": [{"box": [1, 5, 2, 8]}], "controls": {}, "options": {}}
            with mock.patch.object(B, "read", return_value=copy.deepcopy(fake)) as read, \
                    contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(["letterread", str(source), "--backend", "tesseract", "--language", "lat",
                                 "--polarity", "dark", "--crop", "-30", "-10", "5", "35", "--rotate", "90",
                                 "--out", str(out), "--json"])
            self.assertEqual(code, 0)
            result = json.loads(out.read_text())
            self.assertEqual(read.call_args.args[0].shape, (30, 20))
            self.assertEqual(result["words"][0]["box"], [22, 28, 6, 10])
            self.assertEqual(result["source"]["file"], "input.png")

    @unittest.skipUnless(shutil.which("tesseract"), "needs local Tesseract")
    def test_installed_engine_refuses_partial_language_loading_and_keeps_session(self):
        info = B.tesseract_info()
        if "eng" not in info["languages"]:
            self.skipTest("needs an installed eng pack")
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copyfile(info["directory"] / "eng.traineddata", Path(tmp) / "eng.traineddata")
            (Path(tmp) / "qaa.traineddata").write_bytes(b"corrupt model")
            session = B.ReaderSession(backend="tesseract", language="eng", tessdata=tmp)
            previous = session.selection
            with self.assertRaisesRegex(ValueError, "could not load every requested language pack"):
                session.switch(backend="tesseract", language="eng+qaa", tessdata=tmp)
            self.assertEqual(session.selection, previous)
            output = session.read(np.full((64, 128), 255, dtype=np.uint8))
            self.assertEqual(output["selection"], previous)

    @unittest.skipUnless(shutil.which("tesseract"), "needs local Tesseract")
    def test_installed_engine_on_printed_text_and_negative_controls(self):
        info = B.tesseract_info()
        if "eng" not in info["languages"]:
            self.skipTest("needs an installed eng pack")
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 42)
        except OSError:
            self.skipTest("needs DejaVuSans for the known-answer printed fixture")
        image = Image.new("L", (800, 130), 255)
        ImageDraw.Draw(image).text((25, 30), "SCROLLS TEST", font=font, fill=0)
        result = B.read(np.asarray(image), backend="tesseract", language="eng", psm=7)
        self.assertEqual(result["text"], "SCROLLS TEST")
        self.assertTrue(result["above_controls"])
        self.assertEqual(result["controls"]["blank"]["characters_kept"], 0)
        self.assertEqual(result["controls"]["tile_shuffle"]["characters_kept"], 0)
        blank = B.read(np.full((130, 800), 255, dtype=np.uint8), backend="tesseract", language="eng", psm=7)
        self.assertFalse(blank["above_controls"])
        self.assertEqual(blank["text"], "")


if __name__ == "__main__":
    unittest.main()
