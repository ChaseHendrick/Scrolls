"""Tests for kit tifxyz chunks and kit tifxyz diff on synthetic data built here (no downloads).

chunks: a flat sheet in a small two-level zarr touches exactly the chunk layer it lies in, a margin adds the layers
beside it and never a far one, absent chunks are counted as absent, the key layouts of zarr v2 ("/" and ".") and v3
("c/" prefix) are followed, level scaling divides the mesh's voxels, and --fetch copies the metadata and only the
touched chunks. diff: a copy is "same"; a planted removal, addition and shift are each counted by their own number;
across different grids an extension is counted as added and a far patch as not near."""

import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import tifffile  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

from kit import cli, tifxyz as tx
from kit.verify import VerifyError

STEP = 4.0


def sheet(h=16, w=26, z=40.0, x0=0.0, y0=0.0):
    r, c = np.mgrid[0:h, 0:w].astype(float)
    return np.stack([x0 + c * STEP, y0 + r * STEP, np.full_like(r, z)], -1)


def seg(xyz, source="planted-on-20260102150214-2.000um.tifxyz"):
    return tx.Segment(xyz, (xyz > -0.5).all(-1), {"scale": [1 / STEP, 1 / STEP]}, source, 2.0)


def make_v2(root, shape=(96, 96, 128), chunk=16, sep="/", levels=2, present=None):
    """A zarr v2 OME pyramid; level L has every chunk written unless present (a set of level-0 indices) says."""
    root = Path(root)
    root.mkdir(parents=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}')
    ds = [{"path": str(L), "coordinateTransformations": [{"type": "scale", "scale": [2.0 ** L] * 3}]}
          for L in range(levels)]
    (root / ".zattrs").write_text(json.dumps({"multiscales": [{"datasets": ds}]}))
    for L in range(levels):
        shp = [math.ceil(s / 2 ** L) for s in shape]
        d = root / str(L)
        d.mkdir()
        (d / ".zarray").write_text(json.dumps({"shape": shp, "chunks": [chunk] * 3, "dtype": "|u1",
                                               "compressor": None, "fill_value": 0, "order": "C", "filters": None,
                                               "dimension_separator": sep, "zarr_format": 2}))
        n = [math.ceil(s / chunk) for s in shp]
        for iz in range(n[0]):
            for iy in range(n[1]):
                for ix in range(n[2]):
                    if L == 0 and present is not None and (iz, iy, ix) not in present:
                        continue
                    k = d / sep.join(map(str, (iz, iy, ix)))
                    k.parent.mkdir(parents=True, exist_ok=True)
                    k.write_bytes(b"\x01" * (100 + iz))
    return root


@unittest.skipIf(np is None, "numpy and tifffile not installed")
class TestChunks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sheet_touches_its_layer_only(self):
        vol = make_v2(self.root / "v.zarr")
        r, keys, sizes = tx.chunks(seg(sheet()), str(vol))
        # z = 40 lies in chunk layer 2 (32..48); x 0..100 spans 7 chunks, y 0..60 spans 4
        self.assertEqual(r["chunks"], 7 * 4)
        self.assertTrue(all(k.startswith("0/2/") for k in keys))
        self.assertEqual(r["present"], 28)
        self.assertEqual(r["bytes"], 28 * 102)

    def test_margin_adds_neighbors_not_far_layers(self):
        vol = make_v2(self.root / "v.zarr")
        _, keys, _ = tx.chunks(seg(sheet()), str(vol), margin=10)
        layers = {int(k.split("/")[1]) for k in keys}
        self.assertEqual(layers, {1, 2, 3})          # 30..50 at least; never layer 0 or 5
        _, keys0, _ = tx.chunks(seg(sheet()), str(vol), margin=0)
        self.assertTrue(set(keys0) < set(keys))

    def test_level_scaling(self):
        vol = make_v2(self.root / "v.zarr")
        r, keys, _ = tx.chunks(seg(sheet()), str(vol), level=1)
        # at level 1 the sheet is at z 20 (layer 1), x 0..50 (4 chunks), y 0..30 (2 chunks)
        self.assertEqual(r["level_factor_zyx"], [2.0, 2.0, 2.0])
        self.assertEqual(sorted(keys)[0], "1/1/0/0")
        self.assertEqual(r["chunks"], 4 * 2)

    def test_absent_chunks_counted(self):
        keep = {(2, iy, ix) for iy in range(4) for ix in range(3)}
        vol = make_v2(self.root / "v.zarr", present=keep)
        r, _, _ = tx.chunks(seg(sheet()), str(vol))
        self.assertEqual((r["present"], r["absent"]), (12, 16))

    def test_dot_separator_and_v3_layout(self):
        vol = make_v2(self.root / "dot.zarr", sep=".")
        _, keys, _ = tx.chunks(seg(sheet()), str(vol))
        self.assertIn("0/2.0.0", keys)
        v3 = self.root / "v3.zarr"
        (v3 / "0").mkdir(parents=True)
        (v3 / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "group", "attributes": {"ome": {
            "multiscales": [{"datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1, 1, 1]}]}]}]}}}))
        (v3 / "0" / "zarr.json").write_text(json.dumps({
            "zarr_format": 3, "node_type": "array", "shape": [96, 96, 128], "data_type": "uint8",
            "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": [32, 32, 32]}},
            "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
            "codecs": [{"name": "sharding_indexed", "configuration": {"chunk_shape": [16, 16, 16]}}]}))
        r, keys, _ = tx.chunks(seg(sheet()), str(v3))
        self.assertTrue(r["sharded"])
        self.assertIn("0/c/1/0/0", keys)
        self.assertEqual(r["absent"], r["chunks"])

    def test_fetch_copies_only_touched(self):
        vol = make_v2(self.root / "v.zarr")
        dest = self.root / "copy.zarr"
        s = seg(sheet())
        r, keys, sizes = tx.chunks(s, str(vol))
        arr = tx.zarr_level(tx.ZarrSource(str(vol)), 0)
        written, skipped, nbytes = tx.fetch_chunks(tx.ZarrSource(str(vol)), arr["levels"], keys, sizes, dest)
        self.assertEqual((written, skipped, nbytes), (28, 0, 28 * 102))
        files = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
        self.assertEqual(files - set(keys), {".zgroup", ".zattrs", "0/.zarray", "1/.zarray"})
        self.assertEqual(tx.fetch_chunks(tx.ZarrSource(str(vol)), arr["levels"], keys, sizes, dest)[:2], (0, 28))

    def test_bad_inputs(self):
        vol = make_v2(self.root / "v.zarr")
        with self.assertRaises(VerifyError):
            tx.chunks(seg(sheet()), str(vol), level=5)
        with self.assertRaises(VerifyError):
            tx.chunks(seg(sheet()), str(vol), margin=-1)
        with self.assertRaises(VerifyError):
            tx.chunks(seg(sheet()), str(self.root))     # not a zarr

    def test_cli(self):
        vol = make_v2(self.root / "v.zarr")
        folder = self.root / "m-on-20260102150214-2.000um.tifxyz"
        _write(folder, sheet())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["tifxyz", "chunks", str(folder), str(vol), "--json", "--fetch", str(self.root / "c")])
        self.assertEqual(code, 0)
        r = json.loads(out.getvalue())
        self.assertEqual((r["chunks"], r["fetched"]["written"]), (28, 28))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["tifxyz", "chunks", str(folder), str(vol), "--max-requests", "3",
                             "--fetch", str(self.root / "d")])
        self.assertEqual(code, 2)
        self.assertIn("--fetch needs every chunk sized", err.getvalue())


def _write(folder, xyz):
    folder.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate("xyz"):
        tifffile.imwrite(folder / f"{c}.tif", xyz[..., i].astype(np.float32))
    (folder / "meta.json").write_text(json.dumps({"scale": [1 / STEP, 1 / STEP], "format": "tifxyz"}))


@unittest.skipIf(np is None, "numpy and tifffile not installed")
class TestDiff(unittest.TestCase):
    def test_copy_is_same(self):
        r, _ = tx.diff(seg(sheet()), seg(sheet()))
        self.assertTrue(r["same"])
        self.assertEqual((r["added"], r["removed"], r["moved"]), (0, 0, 0))

    def test_planted_edits_each_counted(self):
        a = sheet()
        b = a.copy()
        b[0:4, 0:5] = -1                    # 20 nodes removed
        a[10:12, 20:26] = -1                # 12 nodes b has that a lacks
        b[5:8, 5:9, 2] += 5.0               # 12 nodes moved 5 voxels
        r, masks = tx.diff(seg(a), seg(b))
        self.assertEqual((r["removed"], r["added"], r["moved"]), (20, 12, 12))
        self.assertAlmostEqual(r["displacement_vox"]["p100"], 5.0)
        self.assertFalse(r["same"])
        self.assertEqual(int(masks["moved"].sum()), 12)
        r2, _ = tx.diff(seg(a), seg(b), tol=6)
        self.assertEqual(r2["moved"], 0)    # the tolerance decides, so the check can pass and fail

    def test_area_change(self):
        a, b = sheet(), sheet()
        a[:, 13:] = -1
        r, _ = tx.diff(seg(a), seg(b))
        self.assertGreater(r["area_change_vox2"], 0)
        self.assertAlmostEqual(r["area_b_vox2"] - r["area_a_vox2"], 15 * 13 * STEP * STEP, delta=1)

    def test_different_grids(self):
        a = sheet(16, 20)
        b = sheet(16, 30)                   # the same sheet grown by 10 columns
        r, masks = tx.diff(seg(a), seg(b))
        self.assertTrue(r["method"].startswith("different grids"))
        self.assertGreaterEqual(r["added"], 8 * 16)
        self.assertLessEqual(r["added"], 10 * 16)
        self.assertEqual(r["removed"], 0)
        self.assertEqual(r["nearest_node_vox"]["p50"], 0.0)
        far = sheet(16, 21, z=400)
        r2, _ = tx.diff(seg(a), seg(far))
        self.assertEqual((r2["added"], r2["removed"]), (336, 320))

    def test_near_guarantee(self):
        rng = np.random.default_rng(1)
        a = rng.uniform(0, 200, (500, 3))
        q = rng.uniform(0, 200, (500, 3))
        d = 7.0
        near = tx._near(a, q, d)
        dist = tx._nearest(a, q)
        self.assertTrue((dist[~near] > d).all())
        self.assertTrue((dist[near] <= 2 * math.sqrt(3) * d + 1e-9).all())

    def test_cli_and_picture(self):
        with tempfile.TemporaryDirectory() as t:
            fa, fb = Path(t, "a-on-1-2.000um.tifxyz"), Path(t, "b-on-1-2.000um.tifxyz")
            a = sheet()
            b = a.copy()
            b[0:4, 0:5] = -1
            _write(fa, a)
            _write(fb, b)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["tifxyz", "diff", str(fa), str(fb), "--png", str(Path(t, "d.png"))])
            self.assertEqual(code, 0)
            self.assertIn("20 removed", out.getvalue())
            self.assertTrue(Path(t, "d.png").read_bytes().startswith(b"\x89PNG"))
            with self.assertRaises(VerifyError):
                tx.diff(seg(a), seg(b), tol=0)


if __name__ == "__main__":
    unittest.main()
