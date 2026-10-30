"""Tests for kit zarrbox on synthetic zarr volumes built here (standard library only, no downloads).

plan widens a level-0 box to the chosen level's chunk grid and counts present and absent chunks; copy writes the
metadata and exactly the box's chunk files, byte for byte, with a sha256 row each, and a rerun skips them; verify
passes a clean copy and fails, each by its own field, a changed chunk, a missing one, an extra one, an edited
manifest, a source chunk that changed and an absent chunk that appeared; bad boxes and oversized boxes refuse."""

import contextlib
import hashlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from kit import cli, zarrbox as zb
from kit.verify import VerifyError

SHAPE = (64, 48, 80)
CHUNK = 16


def chunk_bytes(level, iz, iy, ix):
    return bytes([level, iz, iy, ix]) * (25 + iz)


def make_v2(root, levels=2, absent=(), sep="/"):
    """A zarr v2 OME pyramid with distinct bytes per chunk; level-0 chunk indices in absent are left out."""
    root = Path(root)
    root.mkdir(parents=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}')
    ds = [{"path": str(L), "coordinateTransformations": [{"type": "scale", "scale": [2.0 ** L] * 3}]}
          for L in range(levels)]
    (root / ".zattrs").write_text(json.dumps({"multiscales": [{"datasets": ds}]}))
    for L in range(levels):
        shp = [math.ceil(s / 2 ** L) for s in SHAPE]
        d = root / str(L)
        d.mkdir()
        (d / ".zarray").write_text(json.dumps({"shape": shp, "chunks": [CHUNK] * 3, "dtype": "|u1",
                                               "compressor": None, "fill_value": 0, "order": "C", "filters": None,
                                               "dimension_separator": sep, "zarr_format": 2}))
        n = [math.ceil(s / CHUNK) for s in shp]
        for iz in range(n[0]):
            for iy in range(n[1]):
                for ix in range(n[2]):
                    if L == 0 and (iz, iy, ix) in absent:
                        continue
                    k = d / sep.join(map(str, (iz, iy, ix)))
                    k.parent.mkdir(parents=True, exist_ok=True)
                    k.write_bytes(chunk_bytes(L, iz, iy, ix))
    return root


def make_v3(root):
    root = Path(root)
    (root / "0").mkdir(parents=True)
    (root / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "group", "attributes": {
        "ome": {"multiscales": [{"datasets": [{"path": "0"}]}]}}}))
    (root / "0" / "zarr.json").write_text(json.dumps({
        "zarr_format": 3, "node_type": "array", "shape": list(SHAPE), "data_type": "uint8",
        "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": [CHUNK] * 3}},
        "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}}}))
    for iz in range(4):
        for iy in range(3):
            for ix in range(5):
                k = root / "0" / "c" / str(iz) / str(iy) / str(ix)
                k.parent.mkdir(parents=True, exist_ok=True)
                k.write_bytes(chunk_bytes(0, iz, iy, ix))
    return root


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestBox(unittest.TestCase):
    def test_parse_box(self):
        self.assertEqual(zb.parse_box("0-16, *, 5-40"), [[0, 16], None, [5, 40]])
        for bad in ("0-16,0-16", "a-b,*,*", "16-16,*,*", "20-10,*,*", "-5-3,*,*", "4,*,*"):
            with self.assertRaises(VerifyError, msg=bad):
                zb.parse_box(bad)


class TestZarrbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vol = make_v2(self.root / "v.zarr", absent={(1, 1, 1)})

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_widens_to_grid_and_counts_absent(self):
        r, keys, sizes = zb.plan(str(self.vol), zb.parse_box("17-31,20-36,0-5"))
        self.assertEqual(r["box_level"], [[16, 32], [16, 48], [0, 16]])
        self.assertEqual(sorted(keys), ["0/1/1/0", "0/1/2/0"])
        self.assertEqual((r["chunks"], r["present"], r["absent"]), (2, 2, 0))
        r, keys, _ = zb.plan(str(self.vol), zb.parse_box("16-32,16-32,16-32"))
        self.assertEqual((keys, r["present"], r["absent"], r["bytes"]), (["0/1/1/1"], 0, 1, 0))

    def test_level_one_halves_the_box(self):
        r, keys, _ = zb.plan(str(self.vol), zb.parse_box("32-64,*,0-10"), level=1)
        self.assertEqual(r["box_level"], [[16, 32], [0, 24], [0, 16]])
        self.assertEqual(sorted(keys), ["1/1/0/0", "1/1/1/0"])

    def test_outside_and_oversized_refuse(self):
        with self.assertRaises(VerifyError):
            zb.plan(str(self.vol), zb.parse_box("64-80,*,*"))
        with self.assertRaises(VerifyError):
            zb.plan(str(self.vol), zb.parse_box("*,*,*"), max_requests=10)

    def test_copy_is_byte_exact_and_only_the_box(self):
        dest = self.root / "c.zarr"
        m = zb.copy(str(self.vol), zb.parse_box("0-32,0-16,0-80"), dest, now="2026-10-30T00:00:00Z")
        self.assertEqual((m["chunks"], m["present"], m["absent"], m["written"]), (10, 10, 0, 10))
        chunk_files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")
                             if p.is_file() and not p.name.startswith((".", "zarr")))
        self.assertEqual(chunk_files, sorted(r["key"] for r in m["files"]))
        for r in m["files"]:
            raw = (self.vol / r["key"]).read_bytes()
            self.assertEqual((dest / r["key"]).read_bytes(), raw)
            self.assertEqual(r["sha256"], hashlib.sha256(raw).hexdigest())
        for k in (".zattrs", ".zgroup", "0/.zarray", "1/.zarray"):
            self.assertTrue((dest / k).is_file(), k)
        self.assertFalse((dest / "1" / "0").exists())
        again = zb.copy(str(self.vol), zb.parse_box("0-32,0-16,0-80"), dest)
        self.assertEqual((again["written"], again["skipped"]), (0, 10))
        self.assertEqual(again["chunks_sha256"], m["chunks_sha256"])

    def test_absent_chunk_is_recorded_not_written(self):
        dest = self.root / "c.zarr"
        m = zb.copy(str(self.vol), zb.parse_box("16-32,16-48,16-32"), dest)
        self.assertEqual(m["absent_keys"], ["0/1/1/1"])
        self.assertFalse((dest / "0/1/1/1").exists())
        self.assertTrue(zb.verify(dest, source=True)[1])

    def test_verify_catches_each_fault(self):
        box = zb.parse_box("0-32,0-32,0-32")
        dest = self.root / "c.zarr"
        zb.copy(str(self.vol), box, dest)
        self.assertTrue(zb.verify(dest)[1])
        self.assertTrue(zb.verify(dest, source=True)[1])

        (dest / "0/0/0/0").write_bytes(b"x")
        r, ok = zb.verify(dest)
        self.assertEqual((ok, r["changed"]), (False, ["0/0/0/0"]))
        (dest / "0/0/0/0").write_bytes(chunk_bytes(0, 0, 0, 0))

        (dest / "0/0/0/1").unlink()
        r, ok = zb.verify(dest)
        self.assertEqual((ok, r["missing"]), (False, ["0/0/0/1"]))
        (dest / "0/0/0/1").write_bytes(chunk_bytes(0, 0, 0, 1))

        (dest / "0/3/0/0").parent.mkdir(parents=True, exist_ok=True)
        (dest / "0/3/0/0").write_bytes(b"planted")
        r, ok = zb.verify(dest)
        self.assertEqual((ok, r["extra"]), (False, ["0/3/0/0"]))
        (dest / "0/3/0/0").unlink()

        man = json.loads((dest / zb.MANIFEST).read_text())
        man["files"][0]["sha256"] = "0" * 64
        (dest / zb.MANIFEST).write_text(json.dumps(man))
        r, ok = zb.verify(dest)
        self.assertFalse(ok)
        self.assertFalse(r["chunks_sha256_ok"])

    def test_verify_source_catches_changes_upstream(self):
        dest = self.root / "c.zarr"
        zb.copy(str(self.vol), zb.parse_box("16-32,16-32,0-32"), dest)
        (self.vol / "0/1/1/0").write_bytes(b"changed upstream")
        (self.vol / "0/1/1/1").write_bytes(b"now present")
        r, ok = zb.verify(dest, source=True)
        self.assertFalse(ok)
        self.assertEqual(r["source"]["differ"], ["0/1/1/0"])
        self.assertEqual(r["source"]["now_present"], ["0/1/1/1"])
        self.assertTrue(zb.verify(dest)[1])          # the copy itself still matches its manifest

    def test_dot_separator_and_v3_layout(self):
        dot = make_v2(self.root / "dot.zarr", levels=1, sep=".")
        _, keys, _ = zb.plan(str(dot), zb.parse_box("0-16,0-16,16-32"))
        self.assertEqual(keys, ["0/0.0.1"])
        v3 = make_v3(self.root / "v3.zarr")
        dest = self.root / "c3.zarr"
        m = zb.copy(str(v3), zb.parse_box("0-16,0-16,16-32"), dest)
        self.assertEqual([r["key"] for r in m["files"]], ["0/c/0/0/1"])
        self.assertTrue((dest / "zarr.json").is_file() and (dest / "0/zarr.json").is_file())
        self.assertTrue(zb.verify(dest, source=True)[1])

    def test_cli_exit_codes(self):
        dest = self.root / "c.zarr"
        code, out, _ = run_cli(["zarrbox", "plan", str(self.vol), "--box", "0-16,0-16,0-16", "--json"])
        self.assertEqual((code, json.loads(out)["chunks"]), (0, 1))
        code, out, _ = run_cli(["zarrbox", "copy", str(self.vol), "--box", "0-16,0-16,0-16", "--to", str(dest)])
        self.assertEqual(code, 0)
        self.assertIn("manifest", out)
        self.assertEqual(run_cli(["zarrbox", "verify", str(dest)])[0], 0)
        (dest / "0/0/0/0").write_bytes(b"x")
        code, out, _ = run_cli(["zarrbox", "verify", str(dest)])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL"))
        code, _, err = run_cli(["zarrbox", "plan", str(self.vol), "--box", "0-16"])
        self.assertEqual(code, 2)
        self.assertIn("three ranges", err)
        self.assertEqual(run_cli(["zarrbox", "verify", str(self.root)])[0], 2)


if __name__ == "__main__":
    unittest.main()
