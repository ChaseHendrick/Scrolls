"""Tests for kit.vc3d_audit: is a zarr volume whole where a surface needs it, locally and over HTTP.

The volumes are small OME-Zarr groups written by tests/vc3d_fakes.py (64 cubed, 16 cubed chunks, so the
footprint arithmetic is worked out by hand below), damaged on purpose: a chunk removed under the surface
or only in the margin, a level emptied, a scale transform contradicting the shapes, a header removed, a
chunk overwritten with garbage, a sharded zarr v3 array with an empty inner chunk. The HTTP tests serve
the same folders from a local server that answers HEAD, ranges and an S3-style listing.
"""
import gzip
import http.server
import json
import re
import shutil
import struct
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import vc3d_audit  # noqa: E402

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({})).open


class Server:
    """A local HTTP server over a folder: GET, HEAD, byte ranges and ListObjectsV2 at /?list-type=2."""

    def __init__(self, root):
        self.root = Path(root)
        self.hits = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                self.serve(head=True)

            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                if q.get("list-type") == ["2"]:
                    return self.listing(q)
                self.serve()

            def serve(self, head=False):
                key = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path.lstrip("/"))
                server.hits.append((self.command, key, self.headers.get("Range")))
                p = server.root / key
                if not p.is_file():
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data, status = p.read_bytes(), 200
                rng = self.headers.get("Range")
                if rng:
                    m = re.match(r"bytes=(-?\d+)(?:-(\d+))?$", rng)
                    a = int(m.group(1))
                    data = data[a:] if a < 0 else data[a:int(m.group(2)) + 1]
                    status = 206
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if not head:
                    self.wfile.write(data)

            def listing(self, q):
                prefix, limit = q.get("prefix", [""])[0], int(q.get("max-keys", ["1000"])[0])
                server.hits.append(("LIST", prefix, None))
                keys = sorted(f.relative_to(server.root).as_posix() for f in server.root.rglob("*") if f.is_file())
                keys = [k for k in keys if k.startswith(prefix)][:limit]
                body = "<ListBucketResult>" + "".join(
                    f"<Contents><Key>{k}</Key><Size>{(server.root / k).stat().st_size}</Size></Contents>"
                    for k in keys) + "</ListBucketResult>"
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        class Httpd(http.server.ThreadingHTTPServer):
            request_queue_size = 64     # macOS refuses connects past the listen backlog (5 by default)

        self.httpd = Httpd(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def volume(self, name="vol.zarr", **kw):
        kw.setdefault("compressor", "gzip")
        return fakes.write_group(self.d / name, [64, 64, 64], fakes.sheet, chunk=(16, 16, 16), levels=2,
                                 binned="zyx", **kw)

    def surface(self, z=40.0, name="plane.tifxyz", x0=8.0, rows=9, cols=9):
        return fakes.write_tifxyz(self.d / name, fakes.plane(z, x0=x0), rows=rows, cols=cols)

    def run_audit(self, vol, **kw):
        kw.setdefault("margin", 8)
        return vc3d_audit.audit(str(vol), **kw)


class TestLocal(Base):
    def test_clean_volume_and_surface(self):
        vol = self.volume()
        rep = self.run_audit(vol, surface=str(self.surface()))
        self.assertEqual((rep["verdict"], rep["defects"], rep["warnings"]), ("clean", [], []), rep)
        self.assertEqual([r["level"] for r in rep["levels"]], ["0", "1"])
        self.assertEqual([r["populated"] for r in rep["levels"]], [True, True])
        self.assertEqual(rep["levels"][0]["chunk_grid"], [4, 4, 4])
        self.assertEqual(rep["levels"][1]["scale"], [2.0, 2.0, 2.0])
        fp = rep["footprint"]
        self.assertEqual((fp["samples"], fp["spacing_voxels"]), (81, 4.0))
        lv = fp["levels"][0]
        # the plane at z = 40, x and y 8 to 40: samples padded by 4 / 2 + 1 = 3 voxels reach z 37 to 43 (chunk
        # row 2 only) and x, y 5 to 43 (chunks 0 to 2), so 9 chunks lie on the surface; the margin of 8 more
        # reaches z 29 to 51 (chunk rows 1 to 3) and x, y up to 51 (chunk 3): 3 x 4 x 4 - 9 = 39 more
        self.assertEqual((lv["chunks_on_surface"], lv["chunks_in_margin"], lv["present"], lv["missing_on_surface"],
                          lv["unknown"]), (9, 39, 48, 0, 0))
        self.assertEqual([d["ok"] for d in lv["decoded"]], [True, True])
        self.assertEqual(lv["decoded"][0]["detail"], "4096 bytes")

    def test_missing_chunk_on_the_surface_is_a_defect(self):
        vol = self.volume()
        (vol / "0" / "2" / "1" / "1").unlink()
        rep = self.run_audit(vol, surface=str(self.surface()))
        self.assertEqual(rep["verdict"], "defects")
        lv = rep["footprint"]["levels"][0]
        self.assertEqual((lv["missing_on_surface"], lv["missing_in_margin"]), (1, 0))
        miss = lv["missing_on_surface_chunks"][0]
        # samples with y (and x) = 8 + 4 r within 3 voxels of 16..31 are r = 2 to 6
        self.assertEqual(miss, {"chunk": [2, 1, 1], "voxels_zyx": [[32, 48], [16, 32], [16, 32]],
                                "grid_rows": [2, 6], "grid_cols": [2, 6]})
        self.assertIn("1 of 9 chunks under the surface are missing", rep["defects"][0])

    def test_missing_chunk_in_the_margin_is_a_warning(self):
        vol = self.volume()
        (vol / "0" / "3" / "1" / "1").unlink()
        rep = self.run_audit(vol, surface=str(self.surface()))
        self.assertEqual((rep["verdict"], rep["defects"]), ("clean", []))
        self.assertEqual(rep["footprint"]["levels"][0]["missing_in_margin_chunks"], [[3, 1, 1]])
        self.assertIn("1 chunks within 8 voxels", rep["warnings"][0])

    def test_level_one_is_checked_in_its_own_voxels(self):
        vol = self.volume()
        (vol / "1" / "1" / "0" / "0").unlink()
        rep = self.run_audit(vol, surface=str(self.surface()), check_levels=[1])
        lv = rep["footprint"]["levels"][0]
        # at level 1 the plane sits at z 20 (chunk 1), x and y 4 to 20 padded by 4 x 0.5 / 2 + 1 = 2
        self.assertEqual((lv["level"], lv["factor_zyx"], lv["chunks_on_surface"], lv["missing_on_surface"]),
                         ("1", [0.5, 0.5, 0.5], 2 * 2, 1))
        self.assertEqual(rep["verdict"], "defects")

    def test_empty_level(self):
        vol = self.volume()
        for f in (vol / "1").rglob("*"):
            if f.is_dir() and f.parent == vol / "1":
                shutil.rmtree(f)
        rep = self.run_audit(vol)
        self.assertEqual(rep["levels"][1]["populated"], False)
        self.assertIn("level 1: header but no chunks; every read returns fill_value 0", rep["defects"])

    def test_scale_that_contradicts_the_shape(self):
        vol = self.volume()
        attrs = json.loads((vol / ".zattrs").read_text())
        attrs["multiscales"][0]["datasets"][1]["coordinateTransformations"][0]["scale"] = [4.0, 4.0, 4.0]
        (vol / ".zattrs").write_text(json.dumps(attrs))
        rep = self.run_audit(vol)
        self.assertEqual(rep["verdict"], "defects")
        self.assertTrue(any("contradicts its scale [4.0, 4.0, 4.0]" in d for d in rep["defects"]), rep["defects"])

    def test_listed_level_without_a_header(self):
        vol = self.volume()
        (vol / "1" / ".zarray").unlink()
        rep = self.run_audit(vol)
        self.assertIn("level 1: listed in the multiscales but has no header", rep["defects"])
        self.assertEqual(rep["levels"][1], {"level": "1", "header": False})

    def test_chunk_that_does_not_decode(self):
        vol = self.volume()
        (vol / "0" / "2" / "0" / "0").write_bytes(b"not gzip at all")
        rep = self.run_audit(vol, surface=str(self.surface()))
        self.assertEqual(rep["verdict"], "defects")
        self.assertTrue(any("chunk [2, 0, 0] does not decode" in d for d in rep["defects"]), rep["defects"])
        short = self.volume("short.zarr")
        (short / "0" / "2" / "0" / "0").write_bytes(gzip.compress(b"\x01" * 100))
        rep = self.run_audit(short, surface=str(self.surface()))
        self.assertTrue(any("decodes to 100 bytes, expected 4096" in d for d in rep["defects"]), rep["defects"])

    def test_without_a_surface_a_few_listed_chunks_are_decoded(self):
        vol = self.volume()
        rep = self.run_audit(vol)
        self.assertEqual(rep["levels"][0]["sample_keys"], ["0/0/0/0", "0/0/0/1", "0/0/0/2"])
        self.assertEqual([d["ok"] for d in rep["levels"][0]["decoded"]], [True, True])

    def test_surface_outside_the_volume(self):
        vol = self.volume()
        rep = self.run_audit(vol, surface=str(self.surface(x0=200.0)))
        self.assertEqual(rep["verdict"], "defects")
        self.assertIn("81 of 81 surface samples lie outside", rep["defects"][0])

    def test_grid_box_checks_part_of_the_surface(self):
        vol = self.volume()
        (vol / "0" / "2" / "1" / "1").unlink()
        part = self.run_audit(vol, surface=str(self.surface()), grid_box=[0, 2, 0, 9], margin=0)
        fp = part["footprint"]
        # rows 0 and 1 (y 8 and 12, padded to 5..15) touch chunk row 0 only, so the hole at y 16..31 is not under them
        self.assertEqual((fp["grid_box"], fp["samples"], fp["levels"][0]["chunks_on_surface"]), ([0, 2, 0, 9], 18, 3))
        self.assertEqual(part["verdict"], "clean")
        with self.assertRaises(vc3d_audit.AuditError):
            self.run_audit(vol, surface=str(self.surface()), grid_box=[20, 30, 0, 9])

    def test_scale_segmentation_moves_the_footprint(self):
        vol = self.volume()
        half = fakes.write_tifxyz(self.d / "half.tifxyz", fakes.plane(20.0, x0=4.0, step=2.0))
        rep = self.run_audit(vol, surface=str(half), scale_segmentation=2.0)
        self.assertEqual(rep["footprint"]["levels"][0]["chunks_on_surface"], 9)

    def test_bare_v2_array_with_dot_keys(self):
        arr = fakes.write_array(self.d / "a.zarr", [32, 32, 32], fakes.ramp, (16, 16, 16), sep=".")
        rep = self.run_audit(arr)
        self.assertEqual((rep["kind"], rep["levels"][0]["level"], rep["levels"][0]["populated"]), ("array", "", True))
        self.assertEqual(rep["levels"][0]["sample_keys"][0], "0.0.0")
        self.assertEqual(rep["verdict"], "clean")

    def test_no_zarr_metadata(self):
        with self.assertRaises(vc3d_audit.AuditError):
            vc3d_audit.audit(str(self.d))


def write_sharded(path, shape=(32, 32, 32), shard=(16, 16, 16), inner=(8, 8, 8), value=fakes.ramp, empty=()):
    """A sharded zarr v3 array (gzip inner chunks, index at the end with a crc32c slot); inner chunk
    indices listed in `empty` are left out of their shard."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    (p / "zarr.json").write_text(json.dumps({
        "zarr_format": 3, "node_type": "array", "shape": list(shape), "data_type": "uint8",
        "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": list(shard)}},
        "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}}, "fill_value": 0,
        "codecs": [{"name": "sharding_indexed", "configuration": {
            "chunk_shape": list(inner), "codecs": [{"name": "bytes", "configuration": {"endian": "little"}},
                                                   {"name": "gzip", "configuration": {"level": 1}}],
            "index_codecs": [{"name": "bytes", "configuration": {"endian": "little"}}, {"name": "crc32c"}],
            "index_location": "end"}}]}))
    per = [s // i for s, i in zip(shard, inner)]
    for sz in range(shape[0] // shard[0]):
        for sy in range(shape[1] // shard[1]):
            for sx in range(shape[2] // shard[2]):
                body, index = b"", []
                for lz in range(per[0]):
                    for ly in range(per[1]):
                        for lx in range(per[2]):
                            idx = (sz * per[0] + lz, sy * per[1] + ly, sx * per[2] + lx)
                            if idx in empty:
                                index += [vc3d_audit.EMPTY, vc3d_audit.EMPTY]
                                continue
                            raw = bytes(value(idx[0] * inner[0] + z, idx[1] * inner[1] + y, idx[2] * inner[2] + x)
                                        for z in range(inner[0]) for y in range(inner[1]) for x in range(inner[2]))
                            blob = gzip.compress(raw, 1)
                            index += [len(body), len(blob)]
                            body += blob
                out = p / "c" / str(sz) / str(sy) / str(sx)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(body + struct.pack(f"<{len(index)}Q", *index) + b"\0\0\0\0")
    return p


class TestSharded(Base):
    def test_inner_chunks_are_checked_through_the_index(self):
        arr = write_sharded(self.d / "s.zarr", empty={(1, 1, 1)})
        surf = self.surface(z=12.0, x0=2.0, rows=7, cols=7)   # x, y 2 to 26: inner chunks 0 to 3, z chunk 1
        rep = self.run_audit(arr, surface=str(surf), margin=0)
        lv = rep["footprint"]["levels"][0]
        self.assertEqual((lv["chunks_on_surface"], lv["missing_on_surface"]), (16, 1))
        self.assertEqual(lv["missing_on_surface_chunks"][0]["voxels_zyx"], [[8, 16], [8, 16], [8, 16]])
        self.assertEqual(rep["levels"][0]["inner_chunks"], [8, 8, 8])
        self.assertEqual([d["ok"] for d in lv["decoded"]], [True, True])
        self.assertEqual(lv["decoded"][0]["detail"], "512 bytes")
        whole = write_sharded(self.d / "w.zarr")
        self.assertEqual(self.run_audit(whole, surface=str(surf), margin=0)["verdict"], "clean")


class TestRender(Base):
    def test_zeros_inside_the_footprint(self):
        h = w = 10
        layers = []
        for k in range(5):
            img = bytearray([100] * (h * w))
            img[0:10] = bytes(10)                 # row 0 is off the surface in every layer
            if k == 2:
                for r in (4, 5):
                    img[r * w + 3:r * w + 6] = bytes(3)   # a hole on the center layer only
            layers.append(bytes(img))
        folder = fakes.write_layers(self.d / "layers", layers, h, w)
        rep = vc3d_audit.render_zeros(folder)
        self.assertEqual((rep["footprint_pixels"], rep["centre_layer"]), (90, 2))
        self.assertEqual(rep["zero_fraction"], [0.0, 0.0, round(6 / 90, 4), 0.0, 0.0])
        self.assertEqual(rep["centre_zero_box_rows_cols"], [[4, 5], [3, 5]])
        full = vc3d_audit.audit(None, render=str(folder))
        self.assertEqual(full["verdict"], "clean")
        self.assertIn("6.67% of the footprint is 0 on the center layer", full["warnings"][0])
        z = fakes.write_group(self.d / "r.zarr", [5, h, w], lambda k, r, c: layers[k][r * w + c], chunk=(5, 4, 4))
        self.assertEqual(vc3d_audit.render_zeros(z)["zero_fraction"], rep["zero_fraction"])


class TestHttp(Base):
    def setUp(self):
        super().setUp()
        self.server = Server(self.d)
        self.addCleanup(self.server.close)

    def test_remote_matches_local(self):
        vol = self.volume()
        (vol / "0" / "2" / "1" / "1").unlink()
        surf = str(self.surface())
        local = self.run_audit(vol, surface=surf)
        remote = self.run_audit(f"{self.server.url}/vol.zarr", surface=surf, rate=0, opener=NO_PROXY)
        self.assertEqual(remote["store"], "remote")
        self.assertEqual(remote["footprint"]["levels"], local["footprint"]["levels"])
        self.assertEqual(remote["defects"], local["defects"])
        self.assertEqual([r["populated"] for r in remote["levels"]], [None, None])  # no listing over plain HTTP
        heads = [h for h in self.server.hits if h[0] == "HEAD"]
        self.assertEqual(len(heads), 48)
        self.assertEqual(remote["requests"], len(self.server.hits))

    def test_listing_and_probe(self):
        vol = self.volume()
        for f in (vol / "1").iterdir():
            if f.is_dir():
                shutil.rmtree(f)
        listed = self.run_audit(f"{self.server.url}/vol.zarr", rate=0, opener=NO_PROXY,
                                listing=(self.server.url, "vol.zarr/"))
        self.assertEqual([r["populated"] for r in listed["levels"]], [True, False])
        self.assertIn("level 1: header but no chunks; every read returns fill_value 0", listed["defects"])
        probed = self.run_audit(f"{self.server.url}/vol.zarr", rate=0, opener=NO_PROXY)
        self.assertEqual(probed["levels"][0]["probe"], "27 of 27 lattice chunks present")
        self.assertEqual(probed["levels"][1]["probe"], "0 of 8 lattice chunks present")
        self.assertEqual(probed["verdict"], "clean")   # not provable without a listing or a surface
        self.assertTrue(any("none of 8 chunks probed" in w for w in probed["warnings"]))

    def test_request_cap_leaves_chunks_unknown(self):
        self.volume()
        rep = self.run_audit(f"{self.server.url}/vol.zarr", surface=str(self.surface()), rate=0, opener=NO_PROXY,
                             max_requests=5)
        lv = rep["footprint"]["levels"][0]
        self.assertEqual((lv["present"], lv["unknown"]), (5, 43))
        self.assertEqual(rep["verdict"], "incomplete")

    def test_sharded_over_http_uses_range_reads(self):
        write_sharded(self.d / "s.zarr", empty={(1, 1, 1)})
        surf = self.surface(z=12.0, x0=2.0, rows=7, cols=7)
        rep = self.run_audit(f"{self.server.url}/s.zarr", surface=str(surf), margin=0, rate=0, opener=NO_PROXY)
        self.assertEqual(rep["footprint"]["levels"][0]["missing_on_surface"], 1)
        ranges = [h for h in self.server.hits if h[2]]
        self.assertTrue(ranges and ranges[0][2].startswith("bytes=-"), self.server.hits)

    def test_missing_volume_and_failures(self):
        with self.assertRaises(vc3d_audit.AuditError):
            vc3d_audit.audit(f"{self.server.url}/nothing.zarr", rate=0, opener=NO_PROXY)
        store = vc3d_audit.HttpStore("http://127.0.0.1:9/x.zarr", rate=0, retries=0, timeout=2, opener=NO_PROXY)
        self.assertEqual(store.state("0/0/0/0"), vc3d_audit.UNKNOWN)
        with self.assertRaises(vc3d_audit.AuditError):
            store.read(".zattrs")


class TestHelpers(unittest.TestCase):
    def test_s3_urls(self):
        self.assertEqual(vc3d_audit.s3_https("s3://bucket/a/b.zarr/"), "https://bucket.s3.amazonaws.com/a/b.zarr")
        self.assertEqual(vc3d_audit.s3_listing("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/P/v.zarr"),
                         ("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com", "P/v.zarr/"))
        self.assertEqual(vc3d_audit.s3_listing("https://s3.us-east-1.amazonaws.com/bucket/P/v.zarr"),
                         ("https://s3.us-east-1.amazonaws.com/bucket", "P/v.zarr/"))
        self.assertEqual(vc3d_audit.s3_listing("https://example.org/v.zarr"), (None, None))

    def test_key_index(self):
        meta = vc3d_audit._meta_v3({"node_type": "array", "shape": [4, 4], "data_type": "uint8",
                                    "chunk_grid": {"configuration": {"chunk_shape": [2, 2]}}}, "2/")
        self.assertEqual(vc3d_audit.chunk_key(meta, (1, 0)), "2/c/1/0")
        self.assertEqual(vc3d_audit.key_index(meta, "2/c/1/0"), (1, 0))
        self.assertIsNone(vc3d_audit.key_index(meta, "2/zarr.json"))


if __name__ == "__main__":
    unittest.main()
