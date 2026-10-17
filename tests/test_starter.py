"""Beginner workflows: real dependency probes, portable output and safe reader commands."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kit import cli, starter


class StarterTest(unittest.TestCase):
    def test_import_probe_distinguishes_installed_from_missing(self):
        with patch.dict(starter.PACKAGES, {"stdlib": "json", "absent": "scrolls_test_nonexistent_package"}, clear=True):
            result = starter._packages()
        self.assertTrue(result[0]["available"])
        self.assertFalse(result[1]["available"])
        self.assertIn("ModuleNotFoundError", result[1]["detail"])

    def test_broken_or_timed_out_probe_is_not_reported_ready(self):
        with patch.object(starter.subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 15)):
            result = starter._packages()
        self.assertTrue(result)
        self.assertFalse(any(p["available"] for p in result))
        self.assertIn("incomplete", result[0]["detail"])

    def test_cache_requires_the_registry_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weights = root / "sample.npz"
            weights.write_bytes(b"synthetic checkpoint bytes")
            registry = {"models": {"sample": {"file": weights.name, "sha256": hashlib.sha256(weights.read_bytes()).hexdigest(), "license_id": "test"}}}
            (root / "letter-weights.json").write_text(json.dumps(registry))
            with patch.object(starter, "DATA", root), patch.dict(os.environ, {"KIT_LETTER_WEIGHTS": str(weights)}):
                self.assertEqual(starter._weights()[0]["state"], "verified")
                weights.write_bytes(b"changed")
                self.assertEqual(starter._weights()[0]["state"], "hash mismatch")
                weights.unlink()
                self.assertEqual(starter._weights()[0]["state"], "missing")

    def test_portable_cli_never_probes_and_contains_no_host_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "portable.html"
            with patch.object(starter, "check_setup", side_effect=AssertionError("must not probe")), \
                    patch.object(starter.webbrowser, "open", side_effect=AssertionError("must not open")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.start_main(["--portable", "--no-open", "--out", str(out)]), 0)
            html = out.read_text()
            self.assertNotIn(sys.executable, html)
            self.assertNotIn(str(Path.home()), html)
            self.assertIn('"portable": true', html)
            self.assertIn("setup has not been checked", html)
            self.assertNotIn("__REPORT__", html)
            self.assertNotIn("__SCRIPT__", html)

    def test_json_report_cannot_break_out_of_script_element(self):
        report = starter.portable_report()
        report["executable"] = '</script><script>window.injected=true</script>&'
        with tempfile.TemporaryDirectory() as tmp:
            page = starter.write_app(Path(tmp) / "starter.html", report).read_text()
        self.assertNotIn(report["executable"], page)
        self.assertIn("\\u003c/script\\u003e", page)
        self.assertIn("connect-src 'none'", page)

    def test_outputs_never_replace_regular_files_or_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "existing.html"
            target.write_text("keep this")
            with self.assertRaises(FileExistsError):
                starter.write_app(target, starter.portable_report())
            for name, destination in (("linked", target), ("dangling", root / "absent")):
                link = root / name
                try:
                    link.symlink_to(destination)
                except (OSError, NotImplementedError):
                    continue  # Windows can require permission for symlinks.
                with self.assertRaises(FileExistsError):
                    starter.write_app(link, starter.portable_report())
            self.assertEqual(target.read_text(), "keep this")

    def test_check_prints_the_snapshot_without_writing_or_opening(self):
        report = {"schema": 1, "packages": [{"available": False}]}
        out = io.StringIO()
        with patch.object(starter, "check_setup", return_value=report), \
                patch.object(starter, "write_app", side_effect=AssertionError("must not write")), \
                contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["start", "--check"]), 0)
        self.assertEqual(json.loads(out.getvalue()), report)

    def test_conflicting_modes_are_refused_without_probes(self):
        with patch.object(starter, "check_setup", side_effect=AssertionError("must not probe")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.start_main(["--portable", "--check"]), 2)
        self.assertIn("choose --portable or --check", err.getvalue())

    def test_browser_failure_keeps_a_usable_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "app.html"
            with patch.object(starter.webbrowser, "open", side_effect=OSError("headless")), \
                    contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(cli.start_main(["--portable", "--out", str(out)]), 0)
            self.assertTrue(out.is_file())
            self.assertIn("Open the printed HTML file", stdout.getvalue())


@unittest.skipUnless(shutil.which("node"), "browser JavaScript unit checks use optional Node.js")
class BrowserLogicTest(unittest.TestCase):
    def evaluate(self, expression, payload=None):
        script = "const app=require(process.argv[1]);const data=JSON.parse(process.argv[2]);" + \
                 "try {console.log(JSON.stringify({result:(" + expression + ")}));}" + \
                 "catch(err){console.log(JSON.stringify({error:err.message}));}"
        result = subprocess.run([shutil.which("node"), "-e", script, str(starter.DATA / "starter.js"),
                                 json.dumps(payload)], capture_output=True, text=True, check=True, timeout=10)
        return json.loads(result.stdout)

    def form(self, **overrides):
        form = {"image": "/images/a map.png", "output": "/results/new result", "backend": "linenet",
                "language": "eng", "weights": "letters-v2-ccby", "localWeights": "", "scale": "px",
                "px": "24", "mm": "", "um": "", "lines": "", "polarity": "bright", "control": "",
                "overlay": True, "csv": True, "shell": "posix"}
        form.update(overrides)
        return {"form": form, "report": starter.portable_report()}

    def command(self, **overrides):
        return self.evaluate("app.readerCommand(data.form,data.report)", self.form(**overrides))

    def test_practice_passes_then_fails_with_bad_thresholds_and_control(self):
        result = self.evaluate("[app.practice(.35,.55,false), app.practice(.35,0,false), app.practice(.35,1,false), app.practice(.35,.55,true)]")["result"]
        self.assertEqual([r["pass"] for r in result], [True, False, False, False])
        self.assertEqual(result[0]["tp"], result[0]["total"])
        self.assertEqual(result[0]["nullKept"], 0)
        self.assertGreater(result[3]["nullKept"], 0)

    def test_greek_command_is_accepted_by_the_existing_parser(self):
        result = self.command(scale="mm", mm="1.6", um="100", lines="12, 42")["result"]
        args = cli.build_parser().parse_args(result["argv"][3:])
        self.assertEqual((args.backend, args.language, args.letter_mm, args.um_per_px), ("linenet", "grc", 1.6, 100))
        self.assertEqual(args.lines, [12, 42])
        self.assertEqual(result["argv"][0], ".venv/bin/python")

    def test_tesseract_omits_incompatible_greek_options_and_exports(self):
        result = self.command(backend="tesseract", language="lat+eng", shell="powershell")["result"]
        args = cli.build_parser().parse_args(result["argv"][3:])
        self.assertEqual((args.backend, args.language), ("tesseract", "lat+eng"))
        for field in ("weights", "letter_px", "letter_mm", "um_per_px", "lines", "overlay", "csv"):
            self.assertIsNone(getattr(args, field), field)
        self.assertEqual(result["argv"][0], ".venv\\Scripts\\python.exe")
        self.assertEqual(len(result["outputs"]), 1)

    def test_invalid_scale_language_and_control_characters_are_refused(self):
        for kwargs in ({"px": ""}, {"px": "3"}, {"px": "NaN"}, {"px": "Infinity"},
                       {"scale": "mm", "mm": "1e308", "um": "1e-308"},
                       {"backend": "tesseract", "language": "eng+eng"},
                       {"backend": "tesseract", "language": "osd"}, {"image": "bad\npath.png"},
                       {"weights": "local", "localWeights": "letters-v2-real"}):
            with self.subTest(kwargs=kwargs):
                self.assertIn("error", self.command(**kwargs))

    def test_obvious_and_lexical_output_aliases_are_refused(self):
        for kwargs in ({"image": "/results/new result.json"}, {"image": "/results/./new result-overlay.png"},
                       {"control": "/results/child/../new result-overlay.png"},
                       {"shell": "powershell", "image": "C:\\Data\\result.JSON", "output": "c:\\data\\RESULT"}):
            with self.subTest(kwargs=kwargs):
                self.assertIn("error", self.command(**kwargs))

    @unittest.skipIf(os.name == "nt", "POSIX shell round-trip runs on macOS/Linux")
    def test_posix_quoting_preserves_shell_metacharacters(self):
        args = [sys.executable, "-c", "import json,sys;print(json.dumps(sys.argv[1:]))", "a'b $(printf injected) `printf injected` $HOME", "spaces & | ; < >"]
        command = self.evaluate("app.shellCommand(data,'posix')", args)["result"]
        result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(json.loads(result.stdout), args[3:])

    def test_powershell_quoting_is_literal_and_uses_call_operator(self):
        result = self.evaluate("app.shellCommand(data,'powershell')", ["C:\\A B\\python.exe", "a'b $HOME `whoami`"])["result"]
        self.assertEqual(result, "& 'C:\\A B\\python.exe' 'a''b $HOME `whoami`'")


if __name__ == "__main__":
    unittest.main()
