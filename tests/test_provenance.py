import contextlib
import io
import json
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


if __name__ == "__main__":
    unittest.main()
