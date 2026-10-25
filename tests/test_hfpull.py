import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from kit import hfpull

PRIVATE = "owner/private-bucket"     # not in hfpull.PUBLIC, so it needs a token or a mount


class FakeApi:
    """A bucket as {path: bytes}; records the download call."""

    def __init__(self, files):
        self.files, self.calls = files, []

    def list_bucket_tree(self, bucket, prefix=None, recursive=None):
        yield SimpleNamespace(type="directory", path=prefix + "/sub")
        for path, data in self.files.items():
            if path.startswith(prefix):         # string prefix, as the Hub's bucket listing matches
                yield SimpleNamespace(type="file", path=path, size=len(data), xet_hash=hashlib.sha256(data).hexdigest())

    def download_bucket_files(self, bucket, files, raise_on_missing_files=False):
        self.calls.append((bucket, len(files), raise_on_missing_files))
        self.fetched = [f.path for f, _ in files]
        for f, local in files:
            Path(local).write_bytes(self.files[f.path])


class Pull(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.files = {"run/data/a.npy": b"a" * 5, "run/data/sub/b.npy": b"b" * 7, "run/data/sub/m.ckpt": b"c",
                      "run/data/x.part": b"partial", "run/other/z.npy": b"z", "run/data2/s.npy": b"sibling"}
        for path, data in self.files.items():
            p = self.d / "mnt" / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def got(self, root):
        return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*") if p.is_file())

    def test_api_and_mount_routes_pull_the_same_files(self):
        api = FakeApi(self.files)
        a = hfpull.pull("run/data", self.d / "api", exclude=("*.ckpt",), api=api, say=lambda m: None)
        m = hfpull.pull("run/data", self.d / "mnt-copy", exclude=("*.ckpt",), mount=self.d / "mnt", env={},
                        bucket=PRIVATE, say=lambda m: None)
        self.assertEqual(self.got(self.d / "api"), ["a.npy", "sub/b.npy"])
        self.assertEqual(self.got(self.d / "api"), self.got(self.d / "mnt-copy"))
        self.assertEqual((a["route"], a["files"], a["bytes"]), ("api", 2, 12))
        self.assertEqual((m["route"], m["files"], m["bytes"]), ("mount", 2, 12))
        self.assertEqual(api.calls, [("scrollprize/datasets", 2, True)])     # one call, missing files raise
        self.assertEqual((self.d / "api/sub/b.npy").read_bytes(), b"b" * 7)

    def test_a_prefix_naming_one_file_pulls_that_file(self):
        api = FakeApi(self.files)
        a = hfpull.pull("run/data/sub/b.npy", self.d / "one" / "b.npy", api=api, say=lambda m: None)
        m = hfpull.pull("run/data/sub/b.npy", self.d / "two" / "b.npy", mount=self.d / "mnt", env={},
                        bucket=PRIVATE, say=lambda m: None)
        self.assertEqual((a["files"], m["files"]), (1, 1))
        self.assertEqual((self.d / "one/b.npy").read_bytes(), b"b" * 7)
        self.assertEqual((self.d / "two/b.npy").read_bytes(), b"b" * 7)

    def test_identical_files_download_once_and_are_copied(self):
        files = {f"lab/s.zarr/0/{i}.0": b"empty" for i in range(50)}
        files.update({"lab/s.zarr/0/50.0": b"ink", "lab/s.zarr/1/0.0": b"empty", "lab/s.zarr/.zarray": b"{}"})
        api = FakeApi(files)
        got = hfpull.pull("lab/s.zarr", self.d / "dedup", api=api, say=lambda m: None)
        self.assertEqual((got["files"], got["downloaded"], got["bytes"]), (53, 3, 5 * 51 + 3 + 2))
        self.assertEqual(api.calls, [("scrollprize/datasets", 3, True)])
        self.assertEqual(len(self.got(self.d / "dedup")), 53)
        for rel, data in files.items():
            self.assertEqual((self.d / "dedup" / rel[len("lab/s.zarr/"):]).read_bytes(), data)

    def test_same_hash_with_another_size_or_no_hash_is_not_merged(self):
        a = SimpleNamespace(path="a", size=1, xet_hash="h")
        b = SimpleNamespace(path="b", size=2, xet_hash="h")
        c, d = SimpleNamespace(path="c", size=1), SimpleNamespace(path="d", size=1)
        first, copies = hfpull.unique([(a, "qa"), (b, "qb"), (c, "qc"), (d, "qd")])
        self.assertEqual(([f.path for f, _ in first], copies), (["a", "b", "c", "d"], []))

    def test_a_public_bucket_takes_the_api_route_without_a_token(self):
        api = FakeApi(self.files)
        made = []
        real = hfpull._api
        hfpull._api = lambda anonymous=False: made.append(anonymous) or api
        self.addCleanup(setattr, hfpull, "_api", real)
        got = hfpull.pull("run/data", self.d / "pub", bucket="scrollprize/datasets", mount=None, env={},
                          say=lambda m: None)
        self.assertEqual((got["route"], made), ("api", [True]))
        with self.assertRaises(hfpull.HfPullError):    # a private bucket without a token still needs the mount
            hfpull.pull("run/data", self.d / "priv", mount=self.d / "missing", env={}, bucket=PRIVATE,
                        say=lambda m: None)

    def test_exclude_matches_the_path_or_the_name(self):
        self.assertTrue(hfpull.excluded("seed2/A/step01000.ckpt", ("step01000*.ckpt",)))
        self.assertTrue(hfpull.excluded("seed2/A/x.npy", ("seed2/*",)))
        self.assertFalse(hfpull.excluded("seed1/A/x.npy", ("seed2/*", "*.ckpt")))

    def test_no_token_and_no_mount_is_refused(self):
        with self.assertRaises(hfpull.HfPullError):
            hfpull.pull("run/data", self.d / "out", mount=self.d / "missing", env={}, bucket=PRIVATE,
                        say=lambda m: None)

    def test_the_default_bucket_is_the_public_one(self):
        self.assertEqual(hfpull.BUCKET, "scrollprize/datasets")
        self.assertIn(hfpull.BUCKET, hfpull.PUBLIC)

    def test_token_is_read_from_the_environment(self):
        self.assertTrue(hfpull.has_token({"HF_TOKEN": "x"}))
        self.assertFalse(hfpull.has_token({}))


if __name__ == "__main__":
    unittest.main()
