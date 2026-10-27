"""AFV Fibers (spaces/afv-fibers): the box around a point, which tiles a box needs, reading fibres from tiles that share
fibre ids, and writing a box as its own .afv.

Runs without network: two small synthetic tiles in the AFV schema sit in the Space's cache, so nothing is downloaded."""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "afv-fibers"

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:  # pragma: no cover
    HAVE_NUMPY = False

SCHEMA = """
PRAGMA application_id=0x56434643;
PRAGMA user_version=1;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE fibers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,family TEXT NOT NULL,
 point_count INTEGER NOT NULL CHECK(point_count>=2),length REAL NOT NULL,
 min_x REAL NOT NULL,max_x REAL NOT NULL,min_y REAL NOT NULL,max_y REAL NOT NULL,
 min_z REAL NOT NULL,max_z REAL NOT NULL,annotation TEXT NOT NULL);
CREATE TABLE blocks(id INTEGER PRIMARY KEY,fiber_id INTEGER NOT NULL REFERENCES fibers(id),
 first_segment INTEGER NOT NULL,points BLOB NOT NULL,UNIQUE(fiber_id,first_segment));
CREATE VIRTUAL TABLE block_bounds USING rtree(id,min_x,max_x,min_y,max_y,min_z,max_z);
"""


def _load():
    sys.path.insert(0, str(SPACE))
    spec = importlib.util.spec_from_file_location("afv_fibers_under_test", SPACE / "fibers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tile(path, fibres, box):
    """A tile with whole fibres {id: (family, points xyz)}, one block per 3 segments (blocks share end points)."""
    db = sqlite3.connect(str(path))
    db.executescript(SCHEMA)
    bid = 0
    for fid, (fam, q) in fibres.items():
        q = np.asarray(q, float)
        L = float(np.linalg.norm(np.diff(q, axis=0), axis=1).sum())
        b = (q[:, 0].min(), q[:, 0].max(), q[:, 1].min(), q[:, 1].max(), q[:, 2].min(), q[:, 2].max())
        db.execute("INSERT INTO fibers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (fid, f"fiber_{fid}.json", fam, len(q), L, *b, json.dumps({"type": "vc3d_fiber"})))
        for first in range(0, len(q) - 1, 3):
            blk = q[first:first + 4]
            bid = fid * 100 + first
            db.execute("INSERT INTO blocks VALUES(?,?,?,?)", (bid, fid, first, blk.astype("<f8").tobytes()))
            db.execute("INSERT INTO block_bounds VALUES(?,?,?,?,?,?,?)",
                       (bid, blk[:, 0].min(), blk[:, 0].max(), blk[:, 1].min(), blk[:, 1].max(), blk[:, 2].min(),
                        blk[:, 2].max()))
    meta = {"complete": True, "fiber_count": len(fibres), "tile_box_zyx": box,
            "root": {"voxel_size_mm": 0.009362, "coordinate_order": "XYZ"}, "frame": {}}
    db.executemany("INSERT INTO metadata VALUES(?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    db.commit()
    db.close()


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class AfvFibersSpace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AFV_CACHE"] = self.tmp.name
        self.F = _load()
        t = Path(self.tmp.name) / "PHerc0139" / "tiles"
        t.mkdir(parents=True)
        # fibre 1 crosses from tile a into tile b, so both tiles hold it whole; fibre 2 is in a only, 3 in b only
        cross = ("H", [[1000, 500, 500], [1010, 500, 500], [1020, 500, 500], [1030, 500, 500], [1040, 500, 500]])
        _tile(t / "a.afv", {1: cross, 2: ("V", [[900, 400, 500], [900, 400, 510], [900, 400, 520]])},
              [0, 1024, 0, 1024, 0, 1024])
        _tile(t / "b.afv", {1: cross, 3: ("V", [[1100, 400, 500], [1100, 400, 510]])},
              [0, 1024, 0, 1024, 1024, 2048])
        index = {"tiles": [{"id": "a", "box_zyx_l0": [0, 1024, 0, 1024, 0, 1024], "fibres": 2},
                           {"id": "b", "box_zyx_l0": [0, 1024, 0, 1024, 1024, 2048], "fibres": 2}]}
        (t / "index.json").write_text(json.dumps(index))

    def tearDown(self):
        os.environ.pop("AFV_CACHE", None)
        self.tmp.cleanup()

    def test_box_is_clamped_and_scaled_by_level(self):
        F = self.F
        self.assertEqual(F.box_l0("PHerc0139", 500, 500, 1000, 64), [436, 564, 436, 564, 936, 1064])
        self.assertEqual(F.box_l0("PHerc0139", 0, 0, 0, 5000)[1], F.MAX_HALF)
        self.assertEqual(F.box_l0("PHerc0332", 400, 400, 400, 16), [336, 464, 336, 464, 336, 464])
        with self.assertRaises(F.FibreError):
            F.box_l0("PHercNope", 1, 1, 1, 64)

    def test_box_across_tiles_reads_each_fibre_once(self):
        F = self.F
        box = F.box_l0("PHerc0139", 500, 500, 1000, 128)
        fib, tiles = F.fibres_in_box("PHerc0139", box)
        self.assertEqual(sorted(tiles), ["a", "b"])
        self.assertEqual(sorted(fib), [1, 2, 3])
        fam, pts = fib[1]
        self.assertEqual(fam, "H")
        self.assertEqual(pts.shape, (5, 3))          # blocks joined without repeating the shared point
        self.assertTrue((np.diff(pts[:, 0]) == 10).all())

    def test_box_in_one_tile_needs_one(self):
        F = self.F
        box = F.box_l0("PHerc0139", 400, 400, 700, 32)
        self.assertEqual([t["id"] for t in F.tiles_for("PHerc0139", box)], ["a"])

    def test_box_afv_holds_whole_fibres_once(self):
        F = self.F
        out = Path(self.tmp.name) / "box.afv"
        n = F.write_box_afv("PHerc0139", F.box_l0("PHerc0139", 500, 500, 1000, 128), out)
        self.assertEqual(n, 3)
        db = sqlite3.connect(str(out))
        self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0], 0x56434643)
        self.assertEqual(sorted(r[0] for r in db.execute("SELECT id FROM fibers")), [1, 2, 3])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM blocks WHERE fiber_id = 1").fetchone()[0], 2)
        self.assertEqual(db.execute("SELECT rtreecheck('block_bounds')").fetchone()[0], "ok")
        meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM metadata")}
        self.assertEqual(meta["fiber_count"], 3)
        self.assertNotIn("tile_box_zyx", meta)

    def test_space_files_are_consistent(self):
        cat = json.loads((SPACE / "catalog.json").read_text())
        self.assertTrue(all(e["links"] for e in cat["sets"]))
        self.assertFalse(any("paris4" in json.dumps(e).lower() for e in cat["sets"]))
        readme = (SPACE / "README.md").read_text()
        for scan, s in self.F.SCANS.items():
            self.assertIn(s["repo"], readme)


if __name__ == "__main__":
    unittest.main()
