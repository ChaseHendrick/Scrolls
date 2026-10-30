"""kit labelsnap: the recto-face label snap with its abstain mask, confidence, OME-Zarr label and review queue.

Synthetic volumes only: the gap ladder of tests/test_snap_face.py (three blurred sheets, the recto-side neighbor at
gaps of 4, 2, 1, 0.5 and 0 voxels) and flat sheets. Numerical tests skip without numpy.
"""

import contextlib
import io
import json
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
    from tests.test_snap import plane_mesh, write_zarr
    from tests.test_snap_face import GAPS, LADDER_W, ladder_volume

AXIS = ("line", (20.0, 12.0, -400.0), (1.0, 0.0, 0.0))     # far below: outward is +z, so the recto face is below


@unittest.skipIf(np is None, "needs numpy")
class LabelSnapCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.vol = snap.open_volume(write_zarr(cls.root / "ladder.zarr", ladder_volume(1.0, 0.0)))
        xs, ys, zs = plane_mesh(9, LADDER_W * len(GAPS), 30.4, step=1.0, x0=4.0, y0=8.0)
        cls.mesh = (xs, ys, zs, np.ones(xs.shape, bool))
        cls.res = L.label_snap(*cls.mesh, snap.Sampler(cls.vol), axis=AXIS, merged=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cols(self, g):
        b = GAPS.index(g)
        return slice(b * LADDER_W + 3, b * LADDER_W + LADDER_W - 3)

    def test_clear_gaps_snap_to_the_recto_face_and_merged_bands_abstain(self):
        r = self.res
        for g in (4.0, 2.0):
            c = self.cols(g)
            self.assertTrue((r["abstain"][:, c] == L.ABSTAIN_OK).all(), g)
            self.assertLess(float(np.abs(r["zs"][:, c] - 27.5).max()), 0.75, g)
            self.assertTrue((r["confidence"][:, c] > 0).all(), g)
            self.assertTrue((r["reason"][:, c] == 0).all(), g)
        for g in (0.5, 0.0):
            c = self.cols(g)
            self.assertTrue((r["abstain"][:, c] == L.ABSTAIN_YES).all(), g)
            self.assertTrue((r["reason"][:, c] == 7).all(), g)            # too thick: two sheets merged
            self.assertTrue((r["confidence"][:, c] == 0).all(), g)
            np.testing.assert_allclose(r["zs"][:, c], 30.4, atol=1e-5)

    def test_default_has_no_merged_band_rule(self):
        self.assertFalse(L.DEFAULTS["merged"])
        self.assertNotIn("max_thick_ratio", L.face_opts())
        self.assertEqual(L.face_opts(merged=True)["max_thick_ratio"], 1.8)
        r = L.label_snap(*self.mesh, snap.Sampler(self.vol), axis=AXIS)
        self.assertFalse((r["reason"] == 7).any())                      # no vertex abstains as too thick

    def test_detail_grids_follow_the_reasons(self):
        det = self.res["detail"]
        meas = np.isfinite(det["measured"])
        self.assertTrue(np.array_equal(meas, det["reason"] == 0))
        self.assertGreater(det["floor"], 0)
        self.assertIsNotNone(det["cap"])
        self.assertTrue(np.isfinite(det["thick"][det["reason"] == 7]).all())   # the merged band's width is kept

    def test_confidence_falls_with_thickness_toward_the_cap(self):
        det = {"floor": 10.0, "ambiguous": 2.0, "cap": 10.0, "ref_thick": 5.0,
               "contrast": np.array([[40.0, 40.0, 15.0]]), "sep": np.array([[np.inf, np.inf, np.inf]]),
               "thick": np.array([[5.0, 9.0, 5.0]])}
        c = L.confidence(det, np.array([[True, True, True]]))
        self.assertAlmostEqual(float(c[0, 0]), 1.0)
        self.assertAlmostEqual(float(c[0, 1]), 0.2, places=5)
        self.assertAlmostEqual(float(c[0, 2]), 0.5, places=5)
        self.assertEqual(float(L.confidence(det, np.array([[False, True, True]]))[0, 0]), 0.0)

    def test_no_axis_and_no_sign_is_refused_for_a_face_target(self):
        r = L.label_snap(*self.mesh, snap.Sampler(self.vol))
        self.assertEqual(int((r["abstain"] == L.ABSTAIN_OK).sum()), 0)     # snap_face: no side, nothing measured
        self.assertGreater(r["report"]["abstained"]["side not named"], 0)


@unittest.skipIf(np is None, "needs numpy")
class ReviewQueueTest(unittest.TestCase):
    def test_components_join_runs_across_rows(self):
        m = np.array([[1, 1, 0, 1],
                      [0, 1, 0, 1],
                      [1, 1, 0, 0],
                      [0, 0, 0, 1]], bool)
        lab = L.components(m)
        self.assertEqual(int(lab.max()), 3)
        self.assertEqual(len({int(lab[0, 0]), int(lab[1, 1]), int(lab[2, 0])}), 1)
        self.assertNotEqual(int(lab[0, 3]), int(lab[0, 0]))
        self.assertEqual(int((lab > 0).sum()), int(m.sum()))

    def test_u_shape_is_one_component(self):
        m = np.zeros((5, 5), bool)
        m[:, 0] = m[:, 4] = m[4, :] = True
        self.assertEqual(int(L.components(m).max()), 1)

    def test_regions_largest_first_with_a_point_inside(self):
        ab = np.zeros((10, 10), np.uint8)
        ab[1:4, 1:4] = L.ABSTAIN_YES       # 9 vertices
        ab[6:8, 6:9] = L.ABSTAIN_YES       # 6 vertices
        ab[0, 9] = L.ABSTAIN_YES           # 1 vertex: under review_min
        reason = np.where(ab == L.ABSTAIN_YES, 7, 0).astype(np.uint8)
        xs, ys, zs = plane_mesh(10, 10, 5.0, step=1.0, x0=0.0, y0=0.0)
        regs = L.review_regions(xs, ys, zs, ab, reason, min_size=4)
        self.assertEqual([r["size"] for r in regs], [9, 6])
        self.assertEqual((regs[0]["row"], regs[0]["col"]), (2, 2))
        self.assertEqual(regs[0]["reason"], "too thick")
        doc = L.review_collection(regs)
        pts = doc["collections"]["1"]["points"]
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts["1"]["p"], [2.0, 2.0, 5.0])
        self.assertEqual(doc["vc_pointcollections_json_version"], "1")
        self.assertEqual(L.review_collection([])["collections"]["1"]["points"], {})


@unittest.skipIf(np is None, "needs numpy")
class SurfaceLabelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, ab, halo=2.0, scale=1.0, shape=(40, 40, 40), z=20.0):
        xs, ys, zs = plane_mesh(ab.shape[0], ab.shape[1], z, step=2.0, x0=6.0, y0=6.0)
        valid = np.ones(xs.shape, bool)
        n, ok = snap.normals(xs, ys, zs, valid)
        summ = L.write_surface_label(self.root / name, xs, ys, zs, valid, ab, n, shape, scale=scale, halo=halo,
                                     chunk=16)
        shp, blocks = L.read_label_chunks(self.root / name)
        full = np.zeros(shp, np.uint8)
        for (cz, cy, cx), b in blocks.items():
            sl = tuple(slice(k * 16, k * 16 + 16) for k in (cz, cy, cx))
            full[sl] = b[:full[sl].shape[0], :full[sl].shape[1], :full[sl].shape[2]]
        return summ, full

    def test_measured_surface_is_one_on_its_plane_only(self):
        ab = np.zeros((6, 6), np.uint8)
        summ, full = self.write("a.zarr", ab)
        self.assertEqual(summ["cells_ignore"], 0)
        self.assertEqual(set(np.unique(full).tolist()), {0, 1})
        zz = np.nonzero(full == 1)[0]
        self.assertTrue((zz == 20).all())
        self.assertEqual(int((full[20, 6:17, 6:17] == 1).sum()), 11 * 11)     # 5 cells of 2 voxels: x, y 6 to 16
        attrs = json.loads((self.root / "a.zarr" / ".zattrs").read_text())
        self.assertEqual([p["label-value"] for p in attrs["image-label"]["properties"]], [0, 1, 2])

    def test_abstaining_corner_makes_ignore_with_a_halo_and_surface_wins(self):
        ab = np.zeros((6, 6), np.uint8)
        ab[0, 0] = L.ABSTAIN_YES                     # the one cell touching (0, 0) is ignore
        summ, full = self.write("b.zarr", ab, halo=2.0)
        self.assertEqual(summ["cells_ignore"], 1)
        self.assertEqual(set(np.unique(full).tolist()), {0, 1, 2})
        self.assertTrue((full[18:23, 7, 7] == 2).all())                  # halo of 2 along the normal (z)
        self.assertEqual(int(full[24, 7, 7]), 0)
        self.assertEqual(int(full[20, 8, 10]), 1)                        # shared edge with a good cell: surface wins

    def test_level_scale_and_refusal_to_overwrite(self):
        ab = np.zeros((6, 6), np.uint8)
        summ, full = self.write("c.zarr", ab, scale=0.5, shape=(20, 20, 20))
        self.assertTrue((np.nonzero(full == 1)[0] == 10).all())
        with self.assertRaises(L.LabelSnapError):
            self.write("c.zarr", ab)

    def test_label_reads_back_through_kit_volume(self):
        ab = np.zeros((6, 6), np.uint8)
        self.write("d.zarr", ab)
        vol = snap.open_volume(self.root / "d.zarr")
        sm = snap.Sampler(vol)
        v = sm.nearest(np.array([[10.0, 10.0, 20.0], [10.0, 10.0, 25.0]], np.float32))
        self.assertEqual(v.tolist(), [1, 0])


@unittest.skipIf(np is None, "needs numpy")
class CommandLineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        write_zarr(cls.root / "ladder.zarr", ladder_volume(1.0, 0.0))
        xs, ys, zs = plane_mesh(9, LADDER_W * len(GAPS), 30.4, step=1.0, x0=4.0, y0=8.0)
        snap.write_mesh(None, cls.root / "label", xs, ys, zs, np.ones(xs.shape, bool), {}, "synthetic")
        cls.out = cls.root / "out"
        cls.code, cls.text = cls.run_cli(["snap", "--merged", str(cls.root / "label"), "--volume", str(cls.root / "ladder.zarr"),
                                          "--out", str(cls.out), "--axis-point", "20", "12", "-400",
                                          "--axis-dir", "1", "0", "0", "--self-check", "--ignore-halo", "2"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def run_cli(argv):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = L.main(argv)
        return code, buf.getvalue() + err.getvalue()

    def test_snap_writes_every_product_and_check_passes(self):
        self.assertEqual(self.code, 0, self.text)
        rec = json.loads((self.out / "labelsnap.json").read_text())
        self.assertEqual(rec["opts"]["max_thick_ratio"], 1.8)
        self.assertGreater(rec["vertices"]["abstained"], 0)
        self.assertGreater(rec["review"]["regions"], 0)
        self.assertGreater(rec["label"]["voxels"]["surface"], 0)
        self.assertGreater(rec["label"]["voxels"]["ignore"], 0)
        self.assertIn("self_check", rec)
        code, text = self.run_cli(["check", str(self.out)])
        self.assertEqual(code, 0, text)
        xs, ys, zs, valid = snap.load_mesh(self.out / "snapped.tifxyz")
        self.assertEqual(xs.shape, (9, LADDER_W * len(GAPS)))
        meta = json.loads((self.out / "snapped.tifxyz" / "meta.json").read_text())
        self.assertEqual(meta["snap"]["mode"], "face")

    def test_check_catches_a_tampered_mask_and_a_missing_file(self):
        bad = self.root / "bad"
        import shutil
        shutil.copytree(self.out, bad)
        ab = L._read_grid_tif(bad / "abstain.tif").astype(np.uint8)
        ab[0, 0] = L.ABSTAIN_YES if ab[0, 0] == L.ABSTAIN_OK else L.ABSTAIN_OK
        L._write_grid_tif(bad / "abstain.tif", ab)
        code, text = self.run_cli(["check", str(bad)])
        self.assertEqual(code, 1, text)
        self.assertIn("disagree", text)
        (bad / "review.json").unlink()
        code, text = self.run_cli(["check", str(bad)])
        self.assertEqual(code, 1)
        self.assertIn("missing", text)

    def test_label_level_one_halves_the_coordinates(self):
        """--label-level 1 on a 2-level pyramid: the label array is level 1's, a level-0 point p sits at p / 2, and
        the OME scale is 2 (review of PR #807: the scale was upside down, so nothing landed inside the array)."""
        write_zarr(self.root / "ladder2.zarr", ladder_volume(1.0, 0.0), levels=2)
        out = self.root / "out_l1"
        code, text = self.run_cli(["snap", "--merged", str(self.root / "label"), "--volume", str(self.root / "ladder2.zarr"),
                                   "--out", str(out), "--axis-point", "20", "12", "-400", "--axis-dir", "1", "0", "0",
                                   "--label-level", "1", "--ignore-halo", "2", "--json"])
        self.assertEqual(code, 0, text)
        rec = json.loads((out / "labelsnap.json").read_text())
        lb = rec["label"]
        self.assertEqual(lb["shape_zyx"], snap.open_volume(self.root / "ladder2.zarr").shape(1))
        self.assertGreater(lb["chunks_written"], 0)
        self.assertGreater(lb["voxels"]["surface"], 0)
        self.assertEqual(lb["samples_outside_volume"], 0)
        attrs = json.loads((out / "surface_label.zarr" / ".zattrs").read_text())
        tr = attrs["multiscales"][0]["datasets"][0]["coordinateTransformations"][0]
        self.assertEqual(tr["scale"], [2.0, 2.0, 2.0])
        shp, blocks = L.read_label_chunks(out / "surface_label.zarr")
        zz = np.concatenate([np.nonzero(b == L.LABEL_SURFACE)[0] + cz * L.LABEL_CHUNK
                             for (cz, cy, cx), b in blocks.items()])
        self.assertGreater(len(zz), 0)
        # the measured steps snap to the recto face at level-0 z 27.5, so level-1 z 13.75 (rounded: 13 or 14)
        self.assertTrue(((zz >= 13) & (zz <= 14)).all(), sorted(set(zz.tolist())))
        code, text = self.run_cli(["check", str(out)])
        self.assertEqual(code, 0, text)

    def test_level_scale_reads_the_factor_and_refuses_anisotropy(self):
        class Vol:
            factors = [[1.0, 1.0, 1.0], [0.5, 0.5, 0.5], [1.0, 0.5, 0.5]]
        self.assertEqual(L.level_scale(Vol, 0), 1.0)
        self.assertEqual(L.level_scale(Vol, 1), 0.5)
        with self.assertRaises(L.LabelSnapError):
            L.level_scale(Vol, 2)

    def test_snap_exits_1_when_its_outputs_fail_the_check(self):
        out = self.root / "out_bad"
        orig = L.check_outputs
        L.check_outputs = lambda o: ["synthetic problem"]
        try:
            code, text = self.run_cli(["snap", str(self.root / "label"), "--volume", str(self.root / "ladder.zarr"),
                                       "--out", str(out), "--recto-sign", "1", "--no-label"])
        finally:
            L.check_outputs = orig
        self.assertEqual(code, 1, text)
        self.assertIn("fail their own check", text)

    def test_refusals(self):
        code, text = self.run_cli(["snap", str(self.root / "label"), "--volume", str(self.root / "ladder.zarr"),
                                   "--out", str(self.out), "--recto-sign", "1"])
        self.assertEqual(code, 2)
        self.assertIn("not empty", text)
        code, text = self.run_cli(["snap", str(self.root / "label"), "--volume", str(self.root / "ladder.zarr"),
                                   "--out", str(self.root / "fresh")])
        self.assertEqual(code, 2)
        self.assertIn("recto face is named", text)


if __name__ == "__main__":
    unittest.main()
