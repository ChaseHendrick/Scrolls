"""kit.fiberstream: stream shards built from an .afv give the same fibers, rows and .afv bytes as filtering the .afv.

A synthetic .afv with the schema Qual's AVF_SPLINE_GENERATOR writes stands in for a scan. Every check here can fail:
a box with no fibers must return none, a missing row group must break parity, a box across shard edges must not drop
or duplicate a fiber, and the HTTP path goes through a redirect and range requests like Hugging Face's.
"""
import hashlib
import http.server
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

try:
    import numpy as np
    import pyarrow  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False

from kit import fiberstream as fs

SCHEMA = [
    "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    "CREATE TABLE fibers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,family TEXT NOT NULL,\n point_count INTEGER NOT "
    "NULL CHECK(point_count>=2),length REAL NOT NULL,\n min_x REAL NOT NULL,max_x REAL NOT NULL,min_y REAL NOT NULL,"
    "max_y REAL NOT NULL,\n min_z REAL NOT NULL,max_z REAL NOT NULL,annotation TEXT NOT NULL)",
    "CREATE TABLE blocks(id INTEGER PRIMARY KEY,fiber_id INTEGER NOT NULL REFERENCES fibers(id),\n first_segment "
    "INTEGER NOT NULL,points BLOB NOT NULL,UNIQUE(fiber_id,first_segment))",
    "CREATE VIRTUAL TABLE block_bounds USING rtree(id,min_x,max_x,min_y,max_y,min_z,max_z)",
    "CREATE INDEX fibers_length ON fibers(length DESC,id)",
]
UM = 9.0


def make_afv(path, n=400, seed=0, extent=3000.0):
    """A synthetic whole-scan .afv: random-walk fibers, some long (several blocks), some crossing the grid's cells
    and files, written the way afv_stitch.write_afv writes them."""
    rng = np.random.default_rng(seed)
    db = sqlite3.connect(str(path))
    for s in SCHEMA[:4]:
        db.execute(s)
    db.execute("PRAGMA application_id=1447249475")
    db.execute("PRAGMA user_version=1")
    nblk = 0
    for fid in range(1, n + 1):
        npts = int(rng.choice([2, 5, 40, 257, 300, 700, 1500], p=[.1, .2, .3, .1, .1, .1, .1]))
        step = rng.normal(0, 1, (npts, 3)) + rng.normal(0, 3, 3)
        q = rng.uniform(100, extent, 3) + np.cumsum(step, axis=0) * 1.3
        q[:, 2] = np.abs(q[:, 2])
        fam = "H" if rng.random() < 0.5 else "V"
        L = float(np.linalg.norm(np.diff(q, axis=0), axis=1).sum())
        ann = {"type": "vc3d_fiber", "version": 1, "sequence": fid, "filename": f"fiber_{fid}.json",
               "hv_classification": {"manual_tag": fam}, "control_points": [q[0].tolist(), q[-1].tolist()],
               "length_voxels": L, "length_mm": L * UM / 1000}
        mn, mx = q.min(0), q.max(0)
        db.execute("INSERT INTO fibers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (fid, ann["filename"], fam, len(q), L, mn[0], mx[0], mn[1], mx[1], mn[2], mx[2],
                    json.dumps(ann, separators=(",", ":"))))
        for first in range(0, len(q) - 1, 256):
            blk = q[first:first + 257].astype("<f8")
            nblk += 1
            bmn, bmx = blk.min(0), blk.max(0)
            db.execute("INSERT INTO blocks VALUES(?,?,?,?)", (nblk, fid, first, blk.tobytes()))
            db.execute("INSERT INTO block_bounds VALUES(?,?,?,?,?,?,?)",
                       (nblk, bmn[0], bmx[0], bmn[1], bmx[1], bmn[2], bmx[2]))
    meta = {"complete": True, "uuid": "00000000-0000-0000-0000-000000000000",
            "root": {"type": "vc3d_fiber_collection", "version": 1, "voxel_size_mm": UM / 1000},
            "geometry": "XYZ binary64 little-endian native L0", "block_segments": 256, "fiber_count": n,
            "minimum_length_mm": 0.0}
    db.executemany("INSERT INTO metadata VALUES(?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    db.execute(SCHEMA[4])
    db.commit()
    db.close()
    return path


class RangeHandler(http.server.BaseHTTPRequestHandler):
    """Serves a folder with range requests behind a redirect, like huggingface.co's resolve URLs."""
    root = None
    log = []

    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        if self.path.startswith("/resolve/"):
            self.send_response(302)
            self.send_header("Location", "/cdn/" + self.path[len("/resolve/"):])
            self.end_headers()
            return
        p = Path(self.root) / self.path[len("/cdn/"):]
        if not p.is_file():
            self.send_response(404)
            self.end_headers()
            return
        data = p.read_bytes()
        rng = self.headers.get("Range")
        if rng:
            a, b = rng.split("=")[1].split("-")
            a, b = int(a), min(int(b), len(data) - 1)
            body = data[a:b + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        RangeHandler.log.append((self.path, rng, len(body)))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)


@unittest.skipUnless(HAVE, "needs numpy and pyarrow")
class FiberStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.afv = make_afv(cls.dir / "SCAN_afv_v2.afv")
        cls.ds = cls.dir / "ds"
        cls.index = fs.build(cls.afv, cls.ds, level=0, scan="SCAN", workers=1, say=lambda m: None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def stream(self, box, **kw):
        fibers, st, src = fs.stream(box, local=self.ds, **kw)
        return fibers, st, src

    def ref(self, box, **kw):
        return list(fs.read_afv(self.afv, box, **kw))

    def assert_parity(self, box, **kw):
        got, st, src = self.stream(box, **kw)
        ref = self.ref(box, **kw)
        self.assertEqual([f.id for f in got], [f.id for f in ref])
        self.assertEqual(fs.records_digest(got), fs.records_digest(ref))
        a = self.dir / "a.afv"
        b = self.dir / "b.afv"
        fs.write_afv(got, a, src, box=box, **kw)
        fs.write_afv(ref, b, fs.afv_source_info(self.afv), box=box, **kw)
        self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(b.read_bytes()).hexdigest())
        return got, st

    def test_build_checks_out(self):
        v = fs.verify_build(self.ds, self.afv)
        self.assertTrue(v["ok"], v["problems"])
        self.assertEqual(v["rows"], 400)
        self.assertGreater(len(self.index["files"]), 4)
        self.assertGreater(len({e["level"] for e in self.index["files"]}), 1)

    def test_boxes_match_the_full_file(self):
        for box in ([500, 700, 500, 700, 500, 700], [0, 3000, 0, 3000, 0, 3000], [1000, 1100, 900, 1300, 1500, 1520],
                    [100.5, 2000.25, 300, 2500, 1200, 1900]):
            got, _ = self.assert_parity(box)
            self.assertTrue(got or box[1] - box[0] < 300)

    def test_box_across_shard_edges(self):
        # centered on a corner where 8 files of level 0 meet (file edge = 4 * 256 voxels)
        box = [1024 - 300, 1024 + 300, 1024 - 300, 1024 + 300, 1024 - 300, 1024 + 300]
        got, st = self.assert_parity(box)
        self.assertGreater(st["files"], 1)
        self.assertEqual(len({f.id for f in got}), len(got))

    def test_control_box_returns_nothing(self):
        box = [-5000, -4000, -5000, -4000, -5000, -4000]
        got, st = self.assert_parity(box)
        self.assertEqual(got, [])
        self.assertEqual(st["row_groups"], 0)

    def test_filters(self):
        box = [0, 3000, 0, 3000, 0, 3000]
        for kw in ({"family": "H"}, {"family": "V"}, {"min_len": 1.0}, {"family": "V", "min_len": 0.5}):
            got, _ = self.assert_parity(box, **kw)
            self.assertTrue(got)
            if "family" in kw:
                self.assertTrue(all(f.family == kw["family"] for f in got))

    def test_whole_scan(self):
        src = fs.Source(local=self.ds)
        got = [f for part in fs.iter_stream(None, src) for f in part]
        self.assertEqual(fs.multiset_digest(got), fs.multiset_digest(fs.read_afv(self.afv)))

    def test_missing_row_group_breaks_parity(self):
        box = [0, 3000, 0, 3000, 0, 3000]
        src = fs.Source(local=self.ds)
        st = {}
        full = [f for part in fs.iter_stream(box, src, stats=st) for f in part]
        self.assertEqual(fs.multiset_digest(full), fs.multiset_digest(self.ref(box)))
        got = [f for part in fs.iter_stream(box, src, skip={st["read"][0]}) for f in part]
        self.assertNotEqual(fs.multiset_digest(got), fs.multiset_digest(self.ref(box)))

    def test_order_free_digest_catches_a_duplicate(self):
        ref = self.ref([0, 3000, 0, 3000, 0, 3000])
        self.assertNotEqual(fs.multiset_digest(ref), fs.multiset_digest(ref + ref[:1]))
        self.assertEqual(fs.multiset_digest(ref), fs.multiset_digest(list(reversed(ref))))

    def test_written_afv_reads_back(self):
        box = [400, 1400, 400, 1400, 400, 1400]
        got, _, src = self.stream(box)
        out = self.dir / "box.afv"
        counts = fs.write_afv(got, out, src, box=box)
        db = sqlite3.connect(str(out))
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(db.execute("SELECT rtreecheck('block_bounds')").fetchone()[0], "ok")
        meta = dict(db.execute("SELECT key, value FROM metadata"))
        db.close()
        self.assertEqual(json.loads(meta["fiber_count"]), counts["fiber_count"])
        self.assertEqual(json.loads(meta["box_zyx_l0"]), box)
        back = list(fs.read_afv(out))
        self.assertEqual(fs.records_digest(back), fs.records_digest(got))

    def test_files_in_parts(self):
        # tiny row groups and files force every cell into several parts; the boxes must still match the full file
        old = (fs.POINTS_PER_GROUP, fs.GROUPS_PER_FILE)
        fs.POINTS_PER_GROUP, fs.GROUPS_PER_FILE = 2000, 2
        try:
            ds = self.dir / "parts"
            idx = fs.build(self.afv, ds, level=0, scan="SCAN", workers=1, say=lambda m: None)
        finally:
            fs.POINTS_PER_GROUP, fs.GROUPS_PER_FILE = old
        self.assertTrue(any("-p1." in e["path"] for e in idx["files"]))
        self.assertTrue(all(e["row_groups"] <= 2 for e in idx["files"]))
        self.assertTrue(fs.verify_build(ds, self.afv)["ok"])
        for box in ([0, 3000, 0, 3000, 0, 3000], [1024 - 300, 1024 + 300, 1024 - 300, 1024 + 300, 724, 1324]):
            got, _, _ = fs.stream(box, local=ds)
            self.assertEqual(fs.records_digest(got), fs.records_digest(self.ref(box)))

    def test_small_box_reads_a_small_part(self):
        _, st, _ = self.stream([500, 540, 500, 540, 500, 540])
        self.assertLess(st["bytes"], self.index["totals"]["bytes"] / 2)

    def test_http_with_redirect_and_ranges(self):
        RangeHandler.root = self.ds
        RangeHandler.log = []
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}/resolve"
            box = [800, 1300, 800, 1300, 800, 1300]
            got, st, _ = fs.stream(box, base_url=base)
            self.assertEqual(fs.records_digest(got), fs.records_digest(self.ref(box)))
            self.assertTrue(any(r for _, r, _ in RangeHandler.log))
            self.assertEqual(st["bytes"], sum(n for _, _, n in RangeHandler.log))
            self.assertLess(st["bytes"], self.index["totals"]["bytes"])
        finally:
            srv.shutdown()

    def test_cli_stream_filter_parity(self):
        out = self.dir / "cli.afv"
        ref = self.dir / "cli-ref.afv"
        box = ["600", "1600", "600", "1600", "600", "1600"]
        self.assertEqual(fs.main(["stream", "--source", str(self.ds), "--box", *box, "--out", str(out)]), 0)
        self.assertEqual(fs.main(["filter", str(self.afv), "--box", *box, "--out", str(ref)]), 0)
        self.assertEqual(out.read_bytes(), ref.read_bytes())
        self.assertEqual(fs.main(["parity", str(self.afv), "--source", str(self.ds), "--box", *box,
                                  "--out", str(self.dir / "p.afv")]), 0)

    def test_refusals(self):
        with self.assertRaises(fs.FiberStreamError):
            fs.parse_box([5, 1, 0, 1, 0, 1])
        with self.assertRaises(fs.FiberStreamError):
            fs.stream([0, 1, 0, 1, 0, 1], scan="PHerc9999")
        self.assertEqual(fs.main(["stream", "--source", str(self.dir / "nowhere"), "--box", "0", "1", "0", "1", "0",
                                  "1"]), 2)


class FiberStreamPlainTest(unittest.TestCase):
    """Checks that need neither numpy nor pyarrow."""

    def test_scans_point_at_public_datasets(self):
        self.assertEqual(len(fs.SCANS), 6)
        for scan, s in fs.SCANS.items():
            self.assertEqual(s["repo"], f"SharpMeow/{scan.lower()}-afv-fibers")

    def test_box_parse(self):
        self.assertEqual(fs.parse_box(["0", "10", "1.5", "2", "3", "4"]), [0, 10, 1.5, 2, 3, 4])
        with self.assertRaises(fs.FiberStreamError):
            fs.parse_box([0, 0, 0, 1, 0, 1])

    def test_revision_is_quoted(self):
        src = fs.Source(repo="SharpMeow/x", revision="refs/pr/3")
        self.assertEqual(src.url("stream/index.json"),
                         "https://huggingface.co/datasets/SharpMeow/x/resolve/refs%2Fpr%2F3/stream/index.json")


if __name__ == "__main__":
    unittest.main()
