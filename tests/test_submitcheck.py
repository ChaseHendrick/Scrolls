"""Tests for kit.submitcheck on folders built here (no network).

A clean First Letters folder (one flat mesh, one image named after it) has no problem; each file rule fails on its
own planted fault: no mesh, a mesh missing z.tif, no image, an image named after no mesh, and for the Grand Prize a
mesh not named column_NN, a gap and a repeat in the column numbers. Grid numbers come from kit tifxyz; the file
checks run without numpy (--no-grids)."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import tifffile
except ImportError:  # pragma: no cover
    np = None

from kit import cli, submitcheck as sc
from kit.verify import VerifyError


def mesh(folder, files=("x.tif", "y.tif", "z.tif", "meta.json")):
    folder.mkdir(parents=True, exist_ok=True)
    if np is None:
        for f in files:
            (folder / f).write_bytes(b"")
        return folder
    r, c = np.mgrid[0:20, 0:16].astype(float)
    xyz = np.stack([1000 + c * 20, 2000 + r * 20, np.full_like(r, 500.0)], -1)
    for i, a in enumerate("xyz"):
        if f"{a}.tif" in files:
            tifffile.imwrite(folder / f"{a}.tif", xyz[..., i].astype(np.float32))
    if "meta.json" in files:
        (folder / "meta.json").write_text(json.dumps({"scale": [0.05, 0.05], "format": "tifxyz"}))
    return folder


def problems(rep):
    return [f["text"] for f in rep["flags"] if f["level"] == "problem"]


class TestSubmitcheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_first_letters(self):
        mesh(self.root / "patch_a.tifxyz")
        (self.root / "patch_a_ink.png").write_bytes(b"png")
        rep = sc.submitcheck(self.root, "first-letters", voxel_um=2.0, grids=np is not None)
        self.assertTrue(rep["ok"], rep["flags"])
        self.assertEqual(rep["images"][0]["mesh"], "patch_a")
        self.assertTrue(rep["manual"])
        if np is not None:
            self.assertAlmostEqual(rep["meshes"][0]["area_cm2"], 19 * 15 * 400 * 4e-8, delta=5e-4)  # kit tifxyz rounds cm2 to 3 places

    def test_each_file_rule_can_fail(self):
        rep = sc.submitcheck(self.root, "first-letters", grids=False)
        self.assertEqual(len(problems(rep)), 2)                       # no mesh, no image
        mesh(self.root / "a.tifxyz", files=("x.tif", "y.tif", "meta.json"))
        (self.root / "b.png").write_bytes(b"png")
        p = problems(sc.submitcheck(self.root, "first-letters", grids=False))
        self.assertTrue(any("missing z.tif" in t for t in p), p)
        self.assertTrue(any("b.png is named after no mesh" in t for t in p), p)
        for f in p:
            self.assertNotIn("no image", f)

    def test_name_after_needs_a_separator(self):
        self.assertEqual(sc._named_after("col1_render", {"col1"}), "col1")
        self.assertIsNone(sc._named_after("col10", {"col1"}))
        self.assertEqual(sc._named_after("col10", {"col1", "col10"}), "col10")

    def test_grand_prize_column_names(self):
        for n in ("column_01", "column_03", "column_03b", "extra"):
            mesh(self.root / f"{n}.tifxyz")
        (self.root / "column_01.png").write_bytes(b"png")
        (self.root / "banner.png").write_bytes(b"png")
        rep = sc.submitcheck(self.root, "grand", grids=False)
        p = problems(rep)
        self.assertIn("extra.tifxyz: not named column_NN.tifxyz", p)
        self.assertIn("column_03b.tifxyz: not named column_NN.tifxyz", p)
        self.assertTrue(any("missing between 1 and 3: [2]" in t for t in p), p)
        notes = [f["text"] for f in rep["flags"] if f["level"] == "note"]
        self.assertTrue(any(t.startswith("column_03.tifxyz has no image") for t in notes), notes)
        self.assertFalse(any("banner" in t for t in notes), notes)

    def test_grand_prize_repeat_and_banner(self):
        mesh(self.root / "column_01.tifxyz")
        mesh(self.root / "sub" / "column_01.tifxyz")
        (self.root / "column_01.png").write_bytes(b"png")
        rep = sc.submitcheck(self.root, "grand", grids=False)
        self.assertTrue(any("used twice: [1]" in t for t in problems(rep)))
        self.assertTrue(any(f["rule"] == "banner" for f in rep["flags"]))

    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_unreadable_grid_is_a_problem(self):
        m = mesh(self.root / "a.tifxyz")
        (m / "z.tif").write_bytes(b"not a tiff")
        (self.root / "a.png").write_bytes(b"png")
        p = problems(sc.submitcheck(self.root, "title"))
        self.assertTrue(any(t.startswith("a.tifxyz:") for t in p), p)

    def test_every_flag_quotes_a_stated_rule(self):
        for prize in sc.PRIZES:
            for rule, by in sc.RULES.items():
                for q in by.values():
                    self.assertNotIn("\u2014", q)
        mesh(self.root / "x.tifxyz")
        rep = sc.submitcheck(self.root, "first-letters", grids=False)
        for f in rep["flags"]:
            if f["rule"]:
                self.assertEqual(f["quote"], sc.RULES[f["rule"]]["first-letters"])

    def test_cli_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["submitcheck", str(self.root), "--no-grids"]), 1)
        mesh(self.root / "a.tifxyz")
        (self.root / "a.png").write_bytes(b"png")
        with contextlib.redirect_stdout(io.StringIO()) as o:
            self.assertEqual(cli.main(["submitcheck", str(self.root), "--no-grids", "--json"]), 0)
        self.assertTrue(json.loads(o.getvalue())["ok"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["submitcheck", str(self.root / "nope")]), 2)
        self.assertIn("kit submitcheck: no folder at", err.getvalue())
        with self.assertRaises(VerifyError):
            sc.submitcheck(self.root, "bogus")


if __name__ == "__main__":
    unittest.main()
