"""The install demo must not announce success when a fake ink subprocess or its outputs fail."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/demo_synthetic.py"
if not SCRIPT.is_file():
    SCRIPT = ROOT / "scripts/release/autopipeline-files/demo_synthetic.py"
SPEC = importlib.util.spec_from_file_location("demo_synthetic", SCRIPT)
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


class TestDemoResult(unittest.TestCase):
    def test_completed_stage_statuses_do_not_hide_missing_maps(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"stages": {k: {"status": v} for k, v in demo.WANT.items()}, "surfaces": {
                sid: {"accepted": True, "ink": {"fake-ink": {"exit": 0, "maps": {}}}}
                for sid in ("t00", "t01")}}
            errors = demo.result_errors(state, Path(tmp))
            self.assertEqual(len(errors), 6)
            self.assertTrue(all("map" in err for err in errors))

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in ("numpy", "zarr", "tifffile")),
                         "ink dependencies required to exercise the failed model command")
    def test_failed_fake_command_causes_demo_fail_despite_completed_ink_stage(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(demo.fakes, "INK_MODEL", "raise SystemExit(7)\n"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = demo.main(["--out", tmp])
            self.assertEqual(code, 1)
            self.assertIn("DEMO FAIL", output.getvalue())
            self.assertIn("fake ink exited", output.getvalue())
            self.assertNotIn("DEMO PASS", output.getvalue())
            self.assertIn("command engine exited 7", (Path(tmp) / "run/ink/t00/fake-ink/ink.log").read_text())

    def test_empty_and_external_files_are_not_demo_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            root.mkdir()
            external = Path(tmp) / "external.tif"
            external.write_bytes(b"not a demo output")
            empty = root / "empty.tif"
            empty.touch()
            state = {"stages": {k: {"status": v} for k, v in demo.WANT.items()}, "surfaces": {
                sid: {"accepted": True, "ink": {"fake-ink": {"exit": 0, "maps": {
                    "f": {"path": str(empty)}, "r": {"path": str(external)}, "s": {"path": str(root / "absent.tif")}}}}}
                for sid in ("t00", "t01")}}
            self.assertEqual(len(demo.result_errors(state, root)), 6)
