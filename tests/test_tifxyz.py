"""Tests for kit.tifxyz on synthetic grids built here (no downloads).

A flat isometric sheet has the area of its plane, every edge at the promised step and no flags; a planted hole, a
planted fold and a planted stretch are each caught by their own check, so every check can fail; a cylinder about a
known center line faces away from it, and its flipped copy faces toward it; the OBJ and PNG writers produce files
that read back; bad inputs exit 2."""

import contextlib
import io
import json
import math
import tempfile
import unittest
import zlib
from pathlib import Path

try:
    import numpy as np
    import tifffile
except ImportError:  # pragma: no cover
    np = None

from kit import cli, tifxyz as tx
from kit.verify import VerifyError

STEP = 20.0


def plane(h=40, w=30):
    r, c = np.mgrid[0:h, 0:w].astype(float)
    return np.stack([1000 + c * STEP, 2000 + r * STEP, np.full_like(r, 500.0)], -1)


def cylinder(h=30, w=60, radius=800.0, cx=3000.0, cy=3000.0):
    r, c = np.mgrid[0:h, 0:w].astype(float)
    th = c * STEP / radius
    return np.stack([cx + radius * np.cos(th), cy + radius * np.sin(th), 100 + r * STEP], -1)


def seg(xyz, um=2.0, source="synthetic-on-20260102150214-2.000um.tifxyz"):
    valid = (xyz > -0.5).all(-1)
    return tx.Segment(xyz, valid, {"scale": [1 / STEP, 1 / STEP], "area_vx2": None}, source, um)


def write(folder, xyz, meta=None):
    folder.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate("xyz"):
        tifffile.imwrite(folder / f"{c}.tif", xyz[..., i].astype(np.float32))
    (folder / "meta.json").write_text(json.dumps(meta or {"scale": [1 / STEP, 1 / STEP], "format": "tifxyz"}))


class UmbilicusStub:
    def __init__(self, cx, cy, volume="20260102150214"):
        self.cx, self.cy, self.source, self.volume = cx, cy, "stub", volume
        self.z = np.array([-1e6, 1e6])

    def at(self, z):
        return np.full_like(z, self.cx), np.full_like(z, self.cy)


@unittest.skipIf(np is None, "needs numpy and tifffile")
class TestGeometry(unittest.TestCase):
    def test_flat_sheet_area_and_isometry(self):
        s = seg(plane())
        r = tx.info(s)
        self.assertAlmostEqual(r["area_vox2"], 39 * 29 * STEP * STEP, places=3)
        self.assertAlmostEqual(r["area_cm2"], 39 * 29 * STEP * STEP * (2e-4) ** 2, places=3)
        self.assertEqual(r["filled_share"], 1.0)
        st = tx.stretch(s)
        self.assertEqual(st["edge_columns"]["p50"], 1.0)
        self.assertEqual(st["within_10pct"], 1.0)
        self.assertEqual(st["grid_angle_deg"]["p50"], 90.0)
        rep, _ = tx.check(s)
        self.assertTrue(rep["clean"])

    def test_meta_area_ratio(self):
        s = seg(plane())
        s.meta["area_vx2"] = 39 * 29 * STEP * STEP
        self.assertEqual(tx.info(s)["meta_area_ratio"], 1.0)

    def test_planted_hole(self):
        xyz = plane()
        xyz[10:13, 10:14] = -1
        rep, m = tx.check(seg(xyz))
        self.assertEqual(rep["holes"]["nodes"], 12)
        self.assertFalse(rep["clean"])
        # a gap at the border is not a hole
        xyz = plane()
        xyz[0:3, :] = -1
        self.assertEqual(tx.check(seg(xyz))[0]["holes"]["nodes"], 0)

    def test_planted_fold(self):
        xyz = plane()
        xyz[20:, :, 2] = 500 + (xyz[20:, :, 1] - xyz[20, 0, 1]) * 1.0
        xyz[20:, :, 1] = xyz[20, 0, 1] - (xyz[20:, :, 1] - xyz[20, 0, 1]) * 0.01
        rep, m = tx.check(seg(xyz))
        self.assertGreater(rep["folds"]["nodes"], 0)
        self.assertTrue(m["folds"][19:22].any())
        self.assertFalse(m["folds"][:15].any())

    def test_planted_stretch(self):
        xyz = plane()
        xyz[:, 15:, 0] += 2 * STEP
        rep, m = tx.check(seg(xyz))
        self.assertGreater(rep["stretched"]["nodes"], 0)
        self.assertTrue(m["stretched"][:, 14:16].all())
        self.assertGreater(tx.stretch(seg(xyz))["edge_columns"]["p99"], 2.5)

    def test_holes_without_scipy_match(self):
        valid = np.ones((20, 20), bool)
        valid[5:8, 5:9] = False
        valid[0, :] = False
        import builtins
        real = builtins.__import__

        def no_scipy(name, *a, **k):
            if name.startswith("scipy"):
                raise ImportError
            return real(name, *a, **k)

        builtins.__import__ = no_scipy
        try:
            h = tx._holes(valid)
        finally:
            builtins.__import__ = real
        self.assertEqual(int(h.sum()), 12)

    def test_facing_cylinder_and_control(self):
        u = UmbilicusStub(3000.0, 3000.0)
        r = tx.facing(seg(cylinder()), u)
        flipped = cylinder()[:, ::-1]
        f = tx.facing(seg(flipped), u)
        self.assertNotEqual(r["normals"], "mixed")
        self.assertNotEqual(f["normals"], r["normals"])
        self.assertAlmostEqual(r["normals_away_share"] + f["normals_away_share"], 1.0, places=3)
        self.assertEqual(r["angle_grows_along_columns_share"], 1.0)
        self.assertEqual(f["angle_grows_along_columns_share"], 0.0)
        self.assertAlmostEqual(r["median_radius_vox"], 800.0, delta=1.0)
        self.assertNotIn("warning", r)
        self.assertIn("warning", tx.facing(seg(cylinder()), UmbilicusStub(3000.0, 3000.0, volume="20250728140407")))

    def test_bad_settings(self):
        with self.assertRaises(VerifyError):
            tx.check(seg(plane()), max_stretch=1.0)
        with self.assertRaises(VerifyError):
            tx.check(seg(plane()), fold_deg=200)
        with self.assertRaises(VerifyError):
            tx.Segment(plane(), np.ones((40, 30), bool), {"scale": [0, 1]}, "x")


@unittest.skipIf(np is None, "needs numpy and tifffile")
class TestFilesAndCli(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "s-on-20260102150214-2.399um.tifxyz"
            write(folder, plane())
            code, out, _ = self.run_cli(["tifxyz", "info", str(folder), "--json"])
            self.assertEqual(code, 0)
            r = json.loads(out)
            self.assertEqual(r["voxel_um"], 2.399)
            self.assertEqual(r["volume"], "20260102150214")
            code, out, _ = self.run_cli(["tifxyz", "check", str(folder), "--png", f"{d}/c.png"])
            self.assertEqual(code, 0)
            self.assertIn("clean", out)
            png = Path(d, "c.png").read_bytes()
            self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
            code, out, _ = self.run_cli(["tifxyz", "obj", str(folder), f"{d}/s.obj"])
            self.assertEqual(code, 0)
            lines = Path(d, "s.obj").read_text().splitlines()
            self.assertEqual(sum(l.startswith("v ") for l in lines), 40 * 30)
            self.assertEqual(sum(l.startswith("vt ") for l in lines), 40 * 30)
            self.assertEqual(sum(l.startswith("f ") for l in lines), 2 * 39 * 29)
            code, out, _ = self.run_cli(["tifxyz", "preview", str(folder), f"{d}/p.png", "--size", "0"])
            self.assertEqual(code, 0)
            self.assertIn("30 x 40 px", out)

    def test_png_reads_back(self):
        img = np.zeros((3, 4, 3), np.uint8)
        img[1, 2] = (10, 20, 30)
        with tempfile.TemporaryDirectory() as d:
            data = Path(tx.write_png(f"{d}/a.png", img)).read_bytes()
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        self.assertEqual(len(raw), 3 * (1 + 4 * 3))
        self.assertEqual(raw[1 * 13 + 1 + 2 * 3:1 * 13 + 1 + 3 * 3], bytes([10, 20, 30]))

    def test_flagged_check_exits_1_and_missing_folder_2(self):
        with tempfile.TemporaryDirectory() as d:
            xyz = plane()
            xyz[10:13, 10:14] = -1
            write(Path(d) / "s", xyz)
            self.assertEqual(self.run_cli(["tifxyz", "check", f"{d}/s"])[0], 1)
            code, _, err = self.run_cli(["tifxyz", "info", f"{d}/nothing"])
            self.assertEqual(code, 2)
            self.assertIn("no tifxyz folder at", err)


if __name__ == "__main__":
    unittest.main()
