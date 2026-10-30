"""kit finesnap (multi-scale label snap) and kit snapresolve (the abstaining vertices' resolver).

Synthetic volumes only: the gap ladder of tests/test_snap_face.py and flat meshes. The fine scan is the same ladder
read through a matrix with a known misregistration along the normal, which the per-tile registration must undo.
Numerical tests skip without numpy.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kit import labelsnap as L
from kit import snap

try:
    import numpy as np
except ImportError:  # the core kit is standard library only
    np = None

if np is not None:
    from kit import finesnap as F
    from kit import snapresolve as R
    from tests.test_snap import plane_mesh, write_zarr
    from tests.test_snap_face import GAPS, LADDER_W, ladder_volume

AXIS = ("line", (20.0, 12.0, -400.0), (1.0, 0.0, 0.0))     # far below: outward is +z, so the recto face is below
OFFSET = 1.25                                                # the fine scan's misregistration along z, voxels


class ParserWithoutNumpyTest(unittest.TestCase):
    def test_cli_parser_builds_without_numpy(self):
        """CI builds kit's whole parser without numpy (kit.tooldocs check); finesnap must import snaptruth lazily."""
        code = "\n".join([
            "import sys",
            "sys.modules['numpy'] = None",
            "from kit import cli",
            "p = cli.build_parser()",
            "from kit import finesnap",
            "assert 'kit.snaptruth' not in sys.modules",
            "print('ok')"])
        out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "ok")


@unittest.skipIf(np is None, "needs numpy")
class FineSnapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.vol = snap.open_volume(write_zarr(root / "ladder.zarr", ladder_volume(1.0, 0.0)))
        xs, ys, zs = plane_mesh(9, LADDER_W * 2, 30.4, step=1.0, x0=4.0, y0=8.0)   # the gap 4 and gap 2 columns
        cls.mesh = (xs, ys, zs, np.ones(xs.shape, bool))
        cls.M = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, OFFSET]])      # coarse to "fine": z + OFFSET

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_mapped_sampler_reads_through_the_matrix(self):
        s = snap.Sampler(self.vol)
        m = F.MappedSampler(s, self.M)
        p = np.array([[10.0, 12.0, 26.0], [10.0, 12.0, 31.0]])
        np.testing.assert_allclose(m.trilinear(p), s.trilinear(p + [0, 0, OFFSET]))

    def test_registration_undoes_the_misregistration_and_the_snap_lands_on_the_coarse_recto_face(self):
        s = snap.Sampler(self.vol)
        r = F.snap_fine(*self.mesh, s, s, s, self.M, axis=AXIS, opts={"tile": 8, "reg_window": 7, "finder": "labelsnap"})
        self.assertGreater(r["report"]["frac_registered"], 0.9)
        reg = np.isfinite(r["shift"])
        n, _ = snap.normals(*self.mesh)
        np.testing.assert_allclose(r["shift"][reg] * n[..., 2][reg], -OFFSET, atol=0.15)   # fine read at t + shift
        fine = r["source"] == 1
        self.assertGreater(fine.mean(), 0.8)
        self.assertLess(float(np.abs(r["zs"][fine] - 27.5).max()), 0.75)       # the target sheet's recto face

    def test_the_bands_finder_lands_on_the_recto_face_too(self):
        s = snap.Sampler(self.vol)
        r = F.snap_fine(*self.mesh, s, s, s, self.M, axis=AXIS, opts={"tile": 8, "reg_window": 7, "finder": "bands"})
        gap4 = r["xs"] < 4.0 + LADDER_W - 1.0                     # the gap 4 columns; at gap 2 this blur merges the
        fine = (r["source"] == 1) & gap4                          # two bands, and bands takes the merged band's face
        self.assertGreater(fine.sum(), 0.5 * gap4.sum())
        self.assertLess(float(np.abs(r["zs"][fine] - 27.5).max()), 0.75)

    def test_defaults_are_the_tested_setting_and_sampler_reads_voxel_centres(self):
        tested = {"tile": 1, "reg_window": 3, "min_lines": 6, "finder": "bands"}   # the PHerc0139 test's setting
        for k, v in tested.items():
            self.assertEqual(F.DEFAULTS[k], v, k)
        s = F.sampler(self.vol, 0)
        self.assertTrue(s.centres)
        self.assertEqual(s.level, 0)

    def test_bad_finder_and_bands_with_resolve_are_refused(self):
        s = snap.Sampler(self.vol)
        with self.assertRaises(snap.SnapError):
            F.snap_fine(*self.mesh, s, s, s, self.M, axis=AXIS, opts={"finder": "nope"})
        with self.assertRaises(snap.SnapError):
            F.snap_fine(*self.mesh, s, s, s, self.M, axis=AXIS, opts={"finder": "bands", "fine_resolve": "nearest"})

    def test_no_registration_falls_back_to_the_coarse_snap(self):
        s = snap.Sampler(self.vol)
        r = F.snap_fine(*self.mesh, s, s.derive(empty=True), s.derive(empty=True), self.M, axis=AXIS)
        self.assertEqual(r["report"]["tiles_registered"], 0)
        self.assertFalse((r["source"] == 1).any())
        c = r["coarse"]
        moved = np.asarray(c["apply"], bool)
        np.testing.assert_allclose(r["zs"][moved], c["zs"][moved])
        self.assertTrue((r["source"][moved] == 2).all())


@unittest.skipIf(np is None, "needs numpy")
class ResolveTest(unittest.TestCase):
    def test_candidates_are_recto_faces_nearest_first_within_reach(self):
        t = np.arange(-12, 12.001, 0.25)
        p = np.full(len(t), 20.0)
        for lo, hi in ((-7.0, -3.0), (2.0, 6.0), (9.0, 11.5)):
            p[(t >= lo) & (t < hi)] = 200.0
        c = R.candidates(t, p, 1.0, {"sigma": 0.5}, reach=8.0)       # recto faces are the lower faces
        self.assertEqual(len(c), 2)
        self.assertAlmostEqual(c[0], 2.0, delta=0.3)
        self.assertAlmostEqual(c[1], -7.0, delta=0.3)
        c = R.candidates(t, p, -1.0, {"sigma": 0.5}, reach=8.0)      # the upper faces
        self.assertAlmostEqual(c[0], -3.0, delta=0.3)

    def test_predict_fits_a_plane_and_falls_back_to_the_median(self):
        r, c = np.meshgrid(np.arange(9), np.arange(9), indexing="ij")
        K = 0.5 + 0.2 * r - 0.1 * c
        K[4, 4] = np.nan
        self.assertAlmostEqual(R.predict(K, 4, 4, R.DEFAULTS), 0.5 + 0.8 - 0.4, places=6)
        few = np.full((9, 9), np.nan)
        few[3:5, 3:5] = [[1.0, 2.0], [3.0, 10.0]]
        self.assertAlmostEqual(R.predict(few, 4, 4, R.DEFAULTS), 2.5)
        few[3, 3] = few[3, 4] = np.nan
        self.assertTrue(np.isnan(R.predict(few, 4, 4, R.DEFAULTS)))

    def test_resolve_touches_only_fixable_vertices_and_refuses_an_unknown_mode(self):
        with tempfile.TemporaryDirectory() as d:
            vol = snap.open_volume(write_zarr(Path(d) / "ladder.zarr", ladder_volume(1.0, 0.0)))
            xs, ys, zs = plane_mesh(9, LADDER_W * len(GAPS), 30.4, step=1.0, x0=4.0, y0=8.0)
            valid = np.ones(xs.shape, bool)
            s = snap.Sampler(vol)
            res = L.label_snap(xs, ys, zs, valid, s, axis=AXIS)
            for mode in ("consensus", "nearest", "both"):
                rr = R.resolve(xs, ys, zs, valid, s, res, axis=AXIS, opts={"mode": mode})
                fixable = np.isin(res["detail"]["reason"], R.FIXABLE) & ~np.isfinite(res["detail"]["measured"])
                self.assertFalse((rr["resolved"] & ~fixable).any(), mode)
                kept = np.isfinite(res["detail"]["measured"])
                np.testing.assert_allclose(rr["zs"][kept], res["zs"][kept], atol=1e-5)
                self.assertTrue((rr["reason"][rr["resolved"]] == R.RESOLVED).all())
            with self.assertRaises(snap.SnapError):
                R.resolve(xs, ys, zs, valid, s, res, axis=AXIS, opts={"mode": "guess"})


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(np is None, "needs numpy")
class FineSnapCommandLineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        write_zarr(cls.root / "ladder.zarr", ladder_volume(1.0, 0.0))
        xs, ys, zs = plane_mesh(9, LADDER_W * 2, 30.4, step=1.0, x0=4.0, y0=8.0)
        snap.write_mesh(None, cls.root / "label", xs, ys, zs, np.ones(xs.shape, bool), {}, "synthetic")
        (cls.root / "transform.json").write_text(json.dumps(
            {"transformation_matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, OFFSET], [0, 0, 0, 1]]}))
        cls.out = cls.root / "out"
        cls.code, cls.text = cls.run_cli([
            "snap", str(cls.root / "label"), "--volume", str(cls.root / "ladder.zarr"),
            "--fine", str(cls.root / "ladder.zarr"), "--matrix", str(cls.root / "transform.json"),
            "--fine-level", "0", "--reg-level", "0", "--opts", '{"tile": 8, "reg_window": 7}',
            "--out", str(cls.out), "--axis-point", "20", "12", "-400", "--axis-dir", "1", "0", "0",
            "--ignore-halo", "2"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def run_cli(argv):
        import contextlib
        import io
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = F.main(argv)
        return code, buf.getvalue() + err.getvalue()

    def test_snap_writes_labelsnaps_products_plus_source_and_check_passes(self):
        import json
        self.assertEqual(self.code, 0, self.text)
        rec = json.loads((self.out / "labelsnap.json").read_text())
        self.assertEqual(rec["finesnap"]["version"], F.VERSION)
        self.assertGreater(rec["finesnap"]["report"]["frac_fine"], 0.3)
        self.assertEqual(rec["volume"]["fine"]["matrix"][2][3], OFFSET)
        src = L._read_grid_tif(self.out / "source.tif")
        xs, ys, zs, valid = snap.load_mesh(self.out / "snapped.tifxyz")
        gap4 = (src == 1) & (xs < 4.0 + LADDER_W - 1.0)
        self.assertGreater(gap4.sum(), 0)
        self.assertLess(float(np.abs(zs[gap4] - 27.5).max()), 0.75)            # the recto face, in the coarse frame
        self.assertEqual(self.run_cli(["check", str(self.out)])[0], 0)

    def test_a_broken_source_grid_and_a_bad_matrix_are_caught(self):
        import shutil
        bad = self.root / "bad"
        shutil.copytree(self.out, bad)
        (bad / "source.tif").unlink()
        code, text = self.run_cli(["check", str(bad)])
        self.assertEqual(code, 1)
        self.assertIn("source.tif", text)
        (self.root / "m.json").write_text("[[1, 0, 0]]")
        code, text = self.run_cli(["snap", str(self.root / "label"), "--volume", str(self.root / "ladder.zarr"),
                                   "--fine", str(self.root / "ladder.zarr"), "--matrix", str(self.root / "m.json"),
                                   "--out", str(self.root / "o2"), "--recto-sign", "1"])
        self.assertEqual(code, 2)
        self.assertIn("not a usable matrix", text)
