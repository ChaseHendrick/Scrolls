"""VC3D's remote cache: its folder for a URL, and checking its empty-chunk markers (kit/vc3d_cache.py)."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import vc3d_cache  # noqa: E402

OPEN = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/"


class TestWhere(unittest.TestCase):
    def test_folder_names_match_vc3d(self):
        # folders VC3D (villa e0bbb8b) made for these URLs in this project's cloud, 8 October 2026
        for name, digest in (("20250728140407-9.362um-1.2m-113keV-masked.zarr", "740e7d4163dba61a"),
                             ("20260102150214-2.399um-0.2m-78keV-masked.zarr", "f9800af75caa5598")):
            for url in (OPEN + name, OPEN + name + "/"):
                self.assertEqual(vc3d_cache.volume_dir(url, root="/c"), Path("/c") / f"{name}-{digest}")

    def test_cache_root_follows_vc3d(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, conf = Path(tmp) / "home", Path(tmp) / "conf"
            no_dirs = lambda p: False  # noqa: E731
            self.assertEqual(vc3d_cache.cache_root({"HOME": str(home)}, no_dirs), home / ".VC3D" / "remote_cache")
            self.assertEqual(vc3d_cache.cache_root({"HOME": str(home)}, lambda p: p == "/ephemeral"),
                             Path("/ephemeral/remote_cache"))
            conf.mkdir()
            (conf / "VC3D.ini").write_text('[mainWin]\nremote_cache_dir=/no\n[viewer]\nremote_cache_dir="/x y/c"\n')
            env = {"HOME": str(home), "VC3D_CONFIG_DIR": str(conf)}
            self.assertEqual(vc3d_cache.cache_root(env, no_dirs), Path("/x y/c"))

    def test_marker_layouts(self):
        self.assertEqual(vc3d_cache.parse_marker("level_2/10/6/7.empty"), ("chunk", 2, (10, 6, 7)))
        self.assertEqual(vc3d_cache.parse_marker("0/145/91/71.empty"), ("key", None, "0/145/91/71"))
        self.assertEqual(vc3d_cache.parse_marker(".vc_cache_empty/0/c/1/2/3.empty"), ("key", None, "0/c/1/2/3"))


class TestCheck(unittest.TestCase):
    """Markers against a local S3-like server: chunk 0/1/1/1 is really missing, the others exist."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        fakes.write_group(self.d / "vol.zarr", [64, 64, 64], fakes.ramp)   # 2 x 2 x 2 chunks of 32
        (self.d / "vol.zarr" / "0" / "1" / "1" / "1").unlink()
        self.root, self.ledgers = self.d / "cache", self.d / "ledgers"
        self.srv = fakes.S3LikeServer(self.d, false=1).__enter__()
        self.url = self.srv.url + "/vol.zarr"
        self.vdir = vc3d_cache.volume_dir(self.url, root=self.root)

    def tearDown(self):
        self.srv.__exit__()
        self.tmp.cleanup()

    def mark(self, *rels):
        for rel in rels:
            (self.vdir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.vdir / rel).write_bytes(b"")

    def check(self, **kw):
        return vc3d_cache.check(self.url, ledger_dir=self.ledgers, root=self.root, **kw)

    def test_false_markers_are_deleted_and_true_ones_remembered(self):
        false = ["level_0/0/0/0.empty", "0/0/0/1.empty", ".vc_cache_empty/0/1/0/0.empty"]
        true = ["level_0/1/1/1.empty", "0/1/1/1.empty"]
        self.mark(*false, *true, "level_9/0/0/0.empty")
        rep = self.check()
        self.assertEqual((rep["markers"], rep["checked"], rep["true"], rep["deleted"]), (6, 6, 2, 3))
        self.assertEqual(sorted(rep["false"]), sorted(false))
        self.assertEqual(rep["unknown"], ["level_9/0/0/0.empty"])
        self.assertEqual(sorted(vc3d_cache.markers(self.vdir)), sorted(true + ["level_9/0/0/0.empty"]))
        led = json.loads((self.ledgers / f"{self.vdir.name}.json").read_text())
        self.assertEqual((sorted(led["genuine"]), led["url"]), (sorted(true), self.url))
        again = self.check()
        self.assertEqual((again["known_true"], again["checked"]), (2, 1))
        self.assertEqual(self.check(recheck=True)["checked"], 3)

    def test_report_only(self):
        self.mark("level_0/0/0/0.empty")
        rep = self.check(delete=False)
        self.assertEqual((rep["false"], rep["deleted"]), (["level_0/0/0/0.empty"], 0))
        self.assertTrue((self.vdir / "level_0/0/0/0.empty").exists())

    def test_cache_url_names_the_folder(self):
        given = "http://127.0.0.1:1/vol.zarr"
        vdir = vc3d_cache.volume_dir(given, root=self.root)
        (vdir / "level_0" / "0" / "0").mkdir(parents=True)
        (vdir / "level_0" / "0" / "0" / "1.empty").write_bytes(b"")
        rep = self.check(cache_url=given)
        self.assertEqual((rep["cache"], rep["deleted"]), (str(vdir), 1))

    def test_guard_lists_what_a_run_may_have_read(self):
        self.mark("level_0/0/0/0.empty")
        g = vc3d_cache.Guard(self.url, ledger_dir=self.ledgers, root=self.root)
        self.assertEqual(g.before()["deleted"], 1)          # left by an earlier run: repaired, not this run's
        self.mark("level_0/1/0/0.empty", "level_0/1/1/1.empty")   # this run: one false, one true
        led = vc3d_cache.Ledger(self.ledgers / f"{self.vdir.name}.json")
        with led.locked() as data:   # another process deleted a false marker while this run went on
            data["deleted"].append({"marker": "0/0/1/0.empty", "at": time.time()})
        after = g.after()
        self.assertEqual(after["affected"], ["0/0/1/0.empty", "level_0/1/0/0.empty"])
        self.assertEqual(g.after()["affected"], [])
        s = g.summary()
        self.assertEqual((s["checked"], s["false_deleted"], s["unknown"]), (3, 2, []))

    def test_guard_never_raises(self):
        self.mark("level_0/0/0/0.empty")
        g = vc3d_cache.Guard("http://127.0.0.1:9/nothing.zarr", ledger_dir=self.ledgers, root=self.root,
                             cache_url=self.url, store_factory=lambda: None)
        rep = g.before()
        self.assertIn("error", rep)
        self.assertEqual(rep["unknown"], ["level_0/0/0/0.empty"])
        self.assertTrue((self.vdir / "level_0/0/0/0.empty").exists())


if __name__ == "__main__":
    unittest.main()
