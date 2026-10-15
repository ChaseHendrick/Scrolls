"""Tests for kit.vc3d_catalog: the open-data catalog and model downloads, offline.

The catalog here is a small synthetic one in the published layout (metadata.json: samples with
volumes, segments and transforms; models), and the network is a fake opener, so nothing is fetched.
"""
import gzip
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from kit import vc3d_catalog as cat_mod

ORIGIN = lambda path: [{"path": path, "access_roots": [{"type": "s3", "url": "s3://vesuvius-challenge-open-data"}]}]  # noqa: E731

CATALOG = {
    "$schema": "test",
    "samples": {
        "PHercTest": {
            "sample": {"id": "PHercTest", "properties": {"type": "scroll", "volume_transforms": [
                {"from_volume_id": "V1", "transforms": [{"to_volume_id": "V2", "matrix": [[2, 0, 0, 1], [0, 2, 0, 2], [0, 0, 2, 3]]}]},
                {"from_volume_id": "V2", "transforms": [{"to_volume_id": "V1", "matrix": [[0.5, 0, 0, -0.5], [0, 0.5, 0, -1], [0, 0, 0.5, -1.5]]}]}]}},
            "volumes": {
                "V1": {"id": "V1", "long_id": "V1-9.362um-test.zarr",
                       "properties": {"pixel_size_um": 9.362, "shape": [100, 200, 300], "energy_keV": 77.0,
                                      "license": {"name": "CC BY-NC 4.0"}},
                       "data": [{"type": "ome-zarr", "origins": ORIGIN("PHercTest/volumes/V1-9.362um-test.zarr/")},
                                {"type": "surface-prediction", "origins": ORIGIN("PHercTest/pred/V1-surface.zarr/"),
                                 "parameters": {"model_id": "M1"}}]},
                "V2": {"id": "V2", "long_id": "V2-2.4um.zarr", "properties": {"pixel_size_um": 2.4, "superseded_by": "V3"},
                       "data": [{"type": "ome-zarr", "origins": ORIGIN("PHercTest/volumes/V2-2.4um.zarr/")},
                                {"type": "umbilicus", "origins": ORIGIN("PHercTest/representations/umbilicus/V2-umbilicus.json")}]},
            },
            "segments": {
                "S1": {"id": "S1", "long_id": "S1-w001_abc", "suffix": "w001_abc", "original_volume_id": "V1",
                       "creation": {"date": "2026-01-02T00:00:00Z"}, "properties": {"width": 800, "height": 600},
                       "data": [
                           {"type": "tifxyz", "origins": ORIGIN("PHercTest/segments/S1-w001_abc/tifxyz/")},
                           {"type": "tifxyz-transformed", "parameters": {"target_volume": "V2"},
                            "origins": ORIGIN("PHercTest/segments/S1-w001_abc/on-V2/tifxyz/")},
                           {"type": "layers-zarr", "parameters": {"target_volume": "V1"},
                            "origins": ORIGIN("PHercTest/segments/S1-w001_abc/layers.zarr/")},
                           {"type": "ink-detection", "origins": ORIGIN("PHercTest/segments/S1-w001_abc/ink.tif"),
                            "properties": {"model": "ink_9um"}},
                           {"type": "ink-labels", "parameters": {"target_volume": "V1"},
                            "origins": ORIGIN("PHercTest/segments/S1-w001_abc/inklabels.zarr/")}]},
                "S2": {"id": "S2", "long_id": "S2-w002_def", "suffix": "w002_def", "data": []},
                "S3": {"id": "S3", "long_id": "S3-w002_xyz", "suffix": "w002_xyz", "data": []},
            },
        },
        "PHercOther": {"sample": {"properties": {"type": "fragment"}}, "volumes": {}, "segments": {}},
    },
    "models": {"M1": {"long_id": "M1-surface", "properties": {"task": "surface-prediction", "architecture": "nnunet",
                                                             "patch_size": [256, 256, 256]}}},
}


class Response(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = dict(headers or {})


class Opener:
    """A stand-in for urllib.request.urlopen: URL -> (body, headers); records what was asked."""

    def __init__(self, routes):
        self.routes, self.asked = routes, []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.asked.append(url)
        if url not in self.routes:
            raise OSError(f"no route to {url}")
        body, headers = self.routes[url]
        return Response(body, headers)


class TestCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        self.cat = json.loads(json.dumps(CATALOG))

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_caches_refreshes_and_falls_back_offline(self):
        body = gzip.compress(json.dumps(CATALOG).encode())
        net = Opener({cat_mod.CATALOG_URL: (body, {"Content-Encoding": "gzip"})})
        self.assertEqual(cat_mod.load(self.cache, opener=net)["models"], CATALOG["models"])
        self.assertTrue((self.cache / "open-data-metadata.json").is_file())
        offline = Opener({})
        self.assertIn("PHercTest", cat_mod.load(self.cache, opener=offline)["samples"])  # fresh cache: no request
        self.assertEqual(offline.asked, [])
        self.assertIn("PHercTest", cat_mod.load(self.cache, refresh=True, opener=offline)["samples"])  # stale copy
        self.assertEqual(offline.asked, [cat_mod.CATALOG_URL])
        old = time.time() - 2 * cat_mod.MAX_AGE
        os.utime(self.cache / "open-data-metadata.json", (old, old))
        cat_mod.load(self.cache, opener=net)
        self.assertEqual(len(net.asked), 2)
        with self.assertRaises(cat_mod.CatalogError):
            cat_mod.load(self.cache / "empty", opener=offline)

    def test_a_volume_under_another_access_root(self):
        cat = json.loads(json.dumps(CATALOG))
        cat["samples"]["PHercTest"]["volumes"]["V0"] = {
            "properties": {"pixel_size_um": 7.91},
            "data": [{"type": "ome-zarr", "origins": [{"path": "samples/PHercTest/volumes/V0-7.910um.zarr/",
                                                       "access_roots": [{"type": "https",
                                                                         "url": "https://data.aws.ash2txt.org"}]}]}]}
        row = next(v for v in cat_mod.volumes(cat, "PHercTest") if v["volume"] == "V0")
        self.assertEqual(row["url"], "https://data.aws.ash2txt.org/samples/PHercTest/volumes/V0-7.910um.zarr/")
        self.assertEqual(cat_mod.volume_by_id(cat, "V0")[1]["url"], row["url"])

    def test_samples_and_volumes(self):
        self.assertEqual(cat_mod.samples(self.cat), [
            {"sample": "PHercOther", "type": "fragment", "volumes": 0, "segments": 0},
            {"sample": "PHercTest", "type": "scroll", "volumes": 2, "segments": 3}])
        v1, v2 = cat_mod.volumes(self.cat, "phercTEST")
        self.assertEqual(v1["url"], f"{cat_mod.BUCKET_URL}/PHercTest/volumes/V1-9.362um-test.zarr/")
        self.assertEqual((v1["voxel_um"], v1["shape_zyx"], v1["license"]), (9.362, [100, 200, 300], "CC BY-NC 4.0"))
        self.assertEqual(v1["surface_prediction"], [{"url": f"{cat_mod.BUCKET_URL}/PHercTest/pred/V1-surface.zarr/", "model": "M1"}])
        self.assertEqual((v2["volume"], v2["superseded_by"]), ("V2", "V3"))
        with self.assertRaises(cat_mod.CatalogError) as err:
            cat_mod.volumes(self.cat, "PHerc9999")
        self.assertIn("PHercOther, PHercTest", str(err.exception))

    def test_segments_and_lookup(self):
        rows, total = cat_mod.segments(self.cat, "PHercTest", query="w002", limit=1)
        self.assertEqual((len(rows), total, rows[0]["segment"]), (1, 2, "S2"))
        for key in ("S1", "S1-w001_abc", "w001_abc", "W001"):
            self.assertEqual(cat_mod.find_segment(self.cat, "PHercTest", key)[0], "S1", key)
        with self.assertRaises(cat_mod.CatalogError) as err:
            cat_mod.find_segment(self.cat, "PHercTest", "w002")
        self.assertIn("2 segments", str(err.exception))
        with self.assertRaises(cat_mod.CatalogError):
            cat_mod.find_segment(self.cat, "PHercTest", "w404")
        seg = cat_mod.segment(self.cat, "PHercTest", "w001_abc")
        self.assertEqual((seg["frames"], seg["surface_volumes"], seg["ink_maps"], seg["labels_on"], seg["size_px"]),
                         (["V2"], ["V1"], 1, ["V1"], [800, 600]))
        self.assertEqual(seg["created"], "2026-01-02T00:00:00Z")
        ink = next(d for d in seg["data"] if d["type"] == "ink-detection")
        self.assertEqual((ink["url"], ink["properties"]), (f"{cat_mod.BUCKET_URL}/PHercTest/segments/S1-w001_abc/ink.tif",
                                                           {"model": "ink_9um"}))

    def test_tifxyz_frames(self):
        self.assertEqual(cat_mod.tifxyz_prefix(self.cat, "PHercTest", "S1"),
                         ("S1-w001_abc", "PHercTest/segments/S1-w001_abc/tifxyz/"))
        self.assertEqual(cat_mod.tifxyz_prefix(self.cat, "PHercTest", "S1", "V2")[1], "PHercTest/segments/S1-w001_abc/on-V2/tifxyz/")
        with self.assertRaises(cat_mod.CatalogError) as err:
            cat_mod.tifxyz_prefix(self.cat, "PHercTest", "S1", "V9")
        self.assertIn("['V2']", str(err.exception))

    def test_transforms_models_and_url_lookup(self):
        self.assertEqual(len(cat_mod.transforms(self.cat, "PHercTest")), 2)
        self.assertEqual(cat_mod.transforms(self.cat, "PHercTest", "V1"),
                         [{"from": "V1", "to": "V2", "matrix_xyz": [[2, 0, 0, 1], [0, 2, 0, 2], [0, 0, 2, 3]]}])
        self.assertEqual(cat_mod.models(self.cat), [{"model": "M1", "long_id": "M1-surface", "task": "surface-prediction",
                                                     "architecture": "nnunet", "patch_size": [256, 256, 256]}])
        for url in ("https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercTest/volumes/V2-2.4um.zarr",
                    f"{cat_mod.BUCKET_URL}/PHercTest/volumes/V2-2.4um.zarr/",
                    "s3://vesuvius-challenge-open-data/PHercTest/volumes/V2-2.4um.zarr/"):
            sample, row = cat_mod.volume_for_url(self.cat, url)
            self.assertEqual((sample, row["volume"], row["voxel_um"]), ("PHercTest", "V2", 2.4), url)
        self.assertIsNone(cat_mod.volume_for_url(self.cat, "https://example.org/other.zarr"))

    def test_umbilicus_by_url_id_or_folder(self):
        want = f"{cat_mod.BUCKET_URL}/PHercTest/representations/umbilicus/V2-umbilicus.json"
        # a mirror or a local copy is matched by the volume id that starts its name
        for volume in (f"{cat_mod.BUCKET_URL}/PHercTest/volumes/V2-2.4um.zarr/", "V2", "/data/V2-2.4um.zarr/",
                       "https://mirror.example.org/V2-2.4um.zarr"):
            self.assertEqual(cat_mod.umbilicus_for(self.cat, volume), want, volume)
        self.assertEqual(cat_mod.volume_by_id(self.cat, "V1")[1]["voxel_um"], 9.362)
        for volume in ("V1", "https://example.org/other.zarr", "nothing"):
            self.assertIsNone(cat_mod.umbilicus_for(self.cat, volume), volume)


class TestModelDownloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_file_checkpoint(self):
        url = f"{cat_mod.HF}/scrollprize/ink_9um/resolve/main/hybrid_3d2d-seed42/step-075000.pth"
        net = Opener({url: (b"weights", {"X-Repo-Commit": "abc123"})})
        lines = []
        digest = hashlib.sha256(b"weights").hexdigest()
        with mock.patch.dict(cat_mod.KNOWN_MODELS["ink_9um-seed42"]["sha256"],
                             {"hybrid_3d2d-seed42/step-075000.pth": digest}):
            rec = cat_mod.fetch_model("ink_9um-seed42", self.dest / "m", opener=net, log=lines.append)
        self.assertEqual(rec["files"], [{"path": "hybrid_3d2d-seed42/step-075000.pth", "bytes": 7, "sha256": digest,
                                         "sha256_checked": True}])
        ckpt = Path(rec["checkpoint"])
        self.assertEqual((ckpt.read_bytes(), rec["resolved_commit"], rec["engine"]), (b"weights", "abc123", "villa"))
        self.assertEqual(ckpt, self.dest / "m" / "hybrid_3d2d-seed42" / "step-075000.pth")
        self.assertFalse(list((self.dest / "m").rglob("*.part")))
        self.assertIsNone(rec["model_dir"])
        self.assertEqual(lines, ["downloading scrollprize/ink_9um/hybrid_3d2d-seed42/step-075000.pth"])

    def test_a_checkpoint_with_other_bytes_is_refused(self):
        url = f"{cat_mod.HF}/scrollprize/ink_9um/resolve/main/hybrid_3d2d-seed43/step-075000.pth"
        net = Opener({url: (b"other weights", {})})
        with self.assertRaises(cat_mod.CatalogError) as err:
            cat_mod.fetch_model("ink_9um-seed43", self.dest / "m", opener=net, log=lambda m: None)
        self.assertIn("expected 2aeaa85a", str(err.exception))

    @unittest.skipUnless((Path(__file__).resolve().parent.parent / "scripts" / "firstletters" / "readers.tsv").is_file(),
                         "the readers table is not in this checkout")
    def test_checksums_match_the_readers_table(self):
        rows = {}
        with open(Path(__file__).resolve().parent.parent / "scripts" / "firstletters" / "readers.tsv") as f:
            for line in f.read().splitlines()[1:]:
                name, _kind, _file, sha, url = line.split("\t")
                rows[url] = sha
        checked = 0
        for spec in cat_mod.KNOWN_MODELS.values():
            for path, sha in spec.get("sha256", {}).items():
                self.assertEqual(rows[cat_mod.file_url(spec, path)], sha, path)
                checked += 1
        self.assertEqual(checked, 4)
        # the two readers of the ink bar (docs/plans/2026-10-09-autopipeline-bars.md) are pinned
        for name in ("reader-v2", "d9v2"):
            self.assertEqual(len(cat_mod.KNOWN_MODELS[name]["sha256"]), 1, name)

    def test_github_release_checkpoint(self):
        spec = cat_mod.KNOWN_MODELS["d9v2"]
        url = ("https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search/releases/download/v1.0/"
               "d9v2_ft-012000.pth")
        self.assertEqual(cat_mod.file_url(spec, "d9v2_ft-012000.pth"), url)
        net = Opener({url: (b"d9v2 weights", {})})
        digest = hashlib.sha256(b"d9v2 weights").hexdigest()
        with mock.patch.dict(spec["sha256"], {"d9v2_ft-012000.pth": digest}):
            rec = cat_mod.fetch_model("d9v2", self.dest / "d", opener=net, log=lambda m: None)
        self.assertEqual((rec["engine"], rec["revision"], rec["resolved_commit"]), ("villa", "v1.0", None))
        self.assertEqual(Path(rec["checkpoint"]).read_bytes(), b"d9v2 weights")
        self.assertTrue(rec["files"][0]["sha256_checked"])
        # the pinned hash is the check that can fail: other bytes at the same URL are refused
        net = Opener({url: (b"another file", {})})
        with self.assertRaises(cat_mod.CatalogError) as err:
            cat_mod.fetch_model("d9v2", self.dest / "e", opener=net, log=lambda m: None)
        self.assertIn("expected 50d2ad0e", str(err.exception))
        with self.assertRaises(cat_mod.CatalogError):
            cat_mod.file_url(dict(spec, host="ftp"), "x")

    def test_snapshot_skips_excluded_and_complete_files(self):
        spec = cat_mod.KNOWN_MODELS["v8in"]
        base = f"{cat_mod.HF}/{spec['repo']}"
        tree = [{"type": "file", "path": "inference.py", "size": 5}, {"type": "file", "path": "training/log.txt", "size": 3},
                {"type": "directory", "path": "weights"}, {"type": "file", "path": "weights/model.ckpt", "size": 4}]
        routes = {f"{base.replace('/' + spec['repo'], '/api/models/' + spec['repo'])}/tree/{spec['revision']}?recursive=1":
                  (json.dumps(tree).encode(), {}),
                  f"{base}/resolve/{spec['revision']}/inference.py": (b"print", {}),
                  f"{base}/resolve/{spec['revision']}/weights/model.ckpt": (b"abcd", {})}
        net = Opener(routes)
        rec = cat_mod.fetch_model("v8in", self.dest / "v8in", opener=net, log=lambda m: None)
        self.assertEqual([f["path"] for f in rec["files"]], ["inference.py", "weights/model.ckpt"])
        self.assertEqual((rec["engine"], rec["model_dir"], rec["checkpoint"]), ("v8in", str(self.dest / "v8in"), None))
        self.assertFalse((self.dest / "v8in" / "training").exists())
        net.asked.clear()
        cat_mod.fetch_model("v8in", self.dest / "v8in", opener=net, log=lambda m: None)
        self.assertEqual(len(net.asked), 1)  # only the file list; both files are already complete

    def test_download_asks_for_the_stored_bytes(self):
        url = "https://example.org/.gitattributes"
        body = b"*.safetensors filter=lfs\n"

        class Gzipping(Opener):  # gzips the body when the request accepts it, as Hugging Face does
            def __call__(self, req, timeout=None):
                self.asked.append(req.get_header("Accept-encoding"))
                gz = "gzip" in (req.get_header("Accept-encoding") or "")
                return Response(gzip.compress(body) if gz else body, {"Content-Encoding": "gzip"} if gz else {})

        net = Gzipping({})
        n, _ = cat_mod.download(url, self.dest / "a", opener=net, expect_size=len(body))
        self.assertEqual(((self.dest / "a").read_bytes(), n, net.asked), (body, len(body), ["identity"]))

    def test_short_download_is_an_error(self):
        url = "https://example.org/w.bin"
        with self.assertRaises(cat_mod.CatalogError):
            cat_mod.download(url, self.dest / "w.bin", opener=Opener({url: (b"abc", {})}), expect_size=4)
        self.assertFalse((self.dest / "w.bin").exists())


if __name__ == "__main__":
    unittest.main()
