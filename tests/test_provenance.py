import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from kit import cli, provenance


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True)
        git("init", "-q")
        git("config", "user.name", "Test Operator")
        git("config", "user.email", "operator@example.invalid")
        (self.repo / "a.txt").write_text("a")
        git("add", "a.txt")
        git("commit", "-q", "-m", "init")
        self.store = self.root / "store.zarr"
        (self.store / "0" / "c").mkdir(parents=True)
        (self.store / "zarr.json").write_text("{}")
        (self.store / "0" / "c" / "0").write_bytes(b"\x00\x01\x02")
        self.model = self.root / "m.pth"
        self.model.write_bytes(b"weights")
        self.out = self.root / "map.tif"
        self.out.write_bytes(b"map")

    def tearDown(self):
        self.tmp.cleanup()

    def record(self):
        return provenance.build("t", self.repo, started="2026-10-07T00:00:00Z", inputs=[self.store],
                                models=[self.model], outputs=[self.out])

    def test_record_names_operator_code_and_hashes(self):
        r = self.record()
        self.assertEqual(r["operator"]["name"], "Test Operator")
        self.assertNotIn("email", json.dumps(r["operator"]))
        self.assertEqual(len(r["code"][0]["commit"]), 40)
        self.assertFalse(r["code"][0]["uncommitted_changes"])
        self.assertEqual(r["models"][0]["sha256"], provenance.sha256_file(self.model))
        self.assertEqual(r["inputs"][0]["files"], 2)
        self.assertEqual(provenance.verify(r, recheck_files=True), [])

    def test_directory_fingerprint_sees_content_and_names(self):
        a = provenance.fingerprint(self.store)["sha256"]
        (self.store / "0" / "c" / "0").write_bytes(b"\x00\x01\x03")
        b = provenance.fingerprint(self.store)["sha256"]
        self.assertNotEqual(a, b)
        (self.store / "0" / "c" / "0").rename(self.store / "0" / "c" / "1")
        self.assertNotEqual(provenance.fingerprint(self.store)["sha256"], b)

    def test_tampering_breaks_the_digest(self):
        r = self.record()
        r["operator"]["name"] = "Someone Else"
        self.assertIn("digest does not match the record", provenance.verify(r))

    def test_changed_output_is_caught(self):
        r = self.record()
        self.out.write_bytes(b"other map")
        self.assertTrue(any("changed" in p for p in provenance.verify(r, recheck_files=True)))

    def test_uncommitted_changes_are_flagged(self):
        (self.repo / "a.txt").write_text("edited")
        self.assertTrue(self.record()["code"][0]["uncommitted_changes"])

    def test_cli_writes_and_checks(self):
        path = self.root / "prov.json"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["provenance", "write", str(path), "--run", "t", "--repo", str(self.repo),
                             "--input", str(self.store), "--model", str(self.model), "--output", str(self.out)])
        self.assertEqual(code, 0)
        digest = json.loads(path.read_text())["digest"]
        self.assertIn(digest, out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["provenance", "check", str(path), "--files"]), 0)
        self.out.write_bytes(b"changed")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["provenance", "check", str(path), "--files"]), 1)

    def test_devices_and_fifos_are_refused_not_read(self):
        """A symlink to a device or a FIFO inside an input is refused at once (a link to /dev/zero used to hang)."""
        (self.store / "dev").symlink_to(os.devnull)
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            provenance.fingerprint(self.store)
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            provenance.fingerprint(self.store / "dev")
        (self.store / "dev").unlink()
        r = self.record()
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.store / "pipe")
            self.assertTrue(any("not a regular file" in p for p in provenance.verify(r, recheck_files=True)))
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(["provenance", "write", str(self.root / "p.json"), "--run", "t", "--repo", str(self.repo),
                                 "--input", str(self.store)])
            self.assertEqual(code, 2)
            self.assertIn("not a regular file", err.getvalue())

    def test_malformed_records_exit_2_and_ok_says_what_it_checked(self):
        def check(record, *flags):
            path = self.root / "r.json"
            path.write_text(record if isinstance(record, str) else json.dumps(record))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["provenance", "check", str(path), *flags])
            return code, out.getvalue() + err.getvalue()
        def sealed(body):
            return dict(body, digest=__import__("hashlib").sha256(provenance.canonical(body)).hexdigest())
        for bad in ([1, 2], sealed({"inputs": {"a": 1}}), sealed({"inputs": [{"path": "x"}]}),
                    sealed({"models": ["x"]}), "[" * 100000 + "]" * 100000):
            code, text = check(bad, "--files")
            self.assertEqual(code, 2, text)
            self.assertIn("malformed record", text)
        code, text = check(sealed({"schema": 1, "run": "x"}), "--files")
        self.assertEqual(code, 0)
        self.assertIn("no files listed to check", text)
        self.assertNotIn("files unchanged", text)
        self.assertIn("not proof of who wrote it", text)
        code, text = check(self.record(), "--files")
        self.assertEqual(code, 0)
        self.assertIn("3 listed files unchanged", text)


if __name__ == "__main__":
    unittest.main()
