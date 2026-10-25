"""kit canvasorient: the upright angle of a render canvas from its mesh, the turn of a surface volume and the map
back, on synthetic sheets and stacks. Each check here must be able to fail: the sabotage tests flip a sign or a
matrix and require the self-check to catch it."""

import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import canvasorient as co
from kit import cli

try:
    import numpy as np
    import tifffile
    import zarr  # noqa: F401
except ImportError:  # the core kit is standard library only
    np = tifffile = zarr = None

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "2026-10-13-canvasorient" / "published-meshes.json"


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(argv))
    return code, out.getvalue()


class StandardLibrary(unittest.TestCase):
    def test_wrap(self):
        self.assertEqual(co.wrap(180.0), 180.0)
        self.assertEqual(co.wrap(-180.0), 180.0)
        self.assertEqual(co.wrap(190.0), -170.0)
        self.assertEqual(co.wrap(-541.0), 179.0)

    def test_complex_angle_is_the_negative(self):
        self.assertEqual(co.from_complex_angle(63.749), -63.749)
        self.assertEqual(co.from_complex_angle(-180.0), 180.0)

    def test_plan_turn_shapes_and_matrices(self):
        t = co.plan_turn((10, 30), 0.0)
        self.assertEqual(t["turned_shape"], [10, 30])
        self.assertEqual(t["matrix"], [[1.0, 0.0], [0.0, 1.0]])
        t = co.plan_turn((10, 30), 90.0)
        self.assertEqual(t["turned_shape"], [30, 10])
        self.assertEqual(t["matrix"], [[0.0, -1.0], [1.0, 0.0]])        # +row turned toward +col
        t = co.plan_turn((10, 30), 0.0, mirror=True)
        self.assertEqual(t["matrix"], [[1.0, 0.0], [0.0, -1.0]])
        t = co.plan_turn((100, 100), 45.0)
        self.assertEqual(t["turned_shape"], [142, 142])                  # the bounding box of the whole canvas
        with self.assertRaises(co.OrientError):
            co.plan_turn((10, 10), 10.0, order=3)
        with self.assertRaises(co.OrientError):
            co.check_transform(dict(co.plan_turn((10, 30), 30.0), turned_shape=[10, 30]))

    def test_matrix_and_inverse(self):
        for angle, mirror in ((37.0, False), (-112.5, True), (63.75, False)):
            t = co.plan_turn((20, 31), angle, mirror)
            m, mi = t["matrix"], t["inverse"]
            for i in range(2):
                for j in range(2):
                    self.assertAlmostEqual(sum(m[i][k] * mi[k][j] for k in range(2)), float(i == j), places=12)

    def test_canvas_shape_is_labelxfers(self):
        from kit import labelxfer
        for grid, scale, r in (((211, 238), (0.05, 0.05), 1.0), ((9, 9), (0.25, 0.5), 1.0),
                               ((40, 33), (0.1, 0.2), 0.5)):
            self.assertEqual(co.canvas_shape(grid, scale, r),
                             labelxfer.canvas_shape({"shape": list(grid), "scale": list(scale)}, r))

    def test_cli_registered(self):
        self.assertIn("canvasorient", cli.__doc__)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                cli.main(["canvasorient", "--help"])
        self.assertEqual(cm.exception.code, 0)


@unittest.skipIf(np is None, "numpy, tifffile and zarr are needed")
class Estimator(unittest.TestCase):
    def test_synthetic_sheets_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            recs = co.check_synthetic(tmp)
        self.assertTrue(all(r["passes"] for r in recs), [r for r in recs if not r["passes"]])
        sheets = [r for r in recs if "planted_deg" in r]
        self.assertEqual(len(sheets), 2 * len(co.CHECK_ANGLES))
        for r in sheets:
            self.assertLessEqual(abs(co.wrap(r["phi_deg"] - r["planted_deg"])), co.CHECK_TOL_DEG)
            self.assertIs(r["mirror"], r["planted_mirror"])
            # psi = phi, or -phi after the mirror
            self.assertAlmostEqual(r["angle_deg"], co.wrap(-r["phi_deg"] if r["mirror"] else r["phi_deg"]), 3)
        across = recs[-1]
        self.assertFalse(across["applicable"])
        self.assertTrue(any("vertical" in w for w in across["why"]))

    def test_measure_reads_the_render_canvas_with_anisotropic_scale(self):
        # rows and columns with different grid scales: the angle on the grid is not the angle on the canvas; the
        # estimator must give the canvas's (the rendered z image's) angle
        rows, cols = 60, 50
        ii, jj = np.mgrid[0:rows, 0:cols].astype(np.float64)
        sx, sy = 0.25, 0.5                     # 4 canvas px per grid column, 2 per grid row
        # canvas offsets of each vertex
        cr, cc = ii / sy, jj / sx
        alpha = math.radians(35.0)             # +z along canvas direction 35 degrees
        along = cr * math.cos(alpha) + cc * math.sin(alpha)
        across = -cr * math.sin(alpha) + cc * math.cos(alpha)
        theta = 0.2 + across / 400.0
        xyz = np.stack([800 + 400 * np.cos(theta), 800 + 400 * np.sin(theta), 1000 + along], -1)
        valid = np.ones((rows, cols), bool)
        got = co.measure_grid(xyz, valid, [sx, sy])
        self.assertAlmostEqual(got["phi_deg"], 35.0, delta=0.3)
        img = co.canvas_z(xyz, valid, [sx, sy])
        self.assertEqual(list(img.shape), got["canvas"])
        on_canvas = co.measure_image(img)["phi_deg"]
        self.assertAlmostEqual(on_canvas, got["phi_deg"], delta=0.5)
        # swapping the scales (the row/column pitfall) reads a different angle
        swapped = co.measure_grid(xyz, valid, [sy, sx])
        self.assertGreater(abs(co.wrap(swapped["phi_deg"] - 35.0)), 10.0)

    def test_holes_and_too_few_vertices(self):
        xyz, valid, scale = co.synthetic_sheet(20.0, rows=12, cols=12)
        valid[:, 5] = False
        got = co.measure_grid(xyz, valid, scale)
        self.assertAlmostEqual(got["phi_deg"], 20.0, delta=0.5)
        small = co.measure_grid(xyz[:4, :4], valid[:4, :4], scale)
        self.assertIsNone(small["phi_deg"])
        self.assertTrue(small["why"])

    def test_inconsistent_canvas_is_not_applicable(self):
        # two halves with +z in opposite directions: no single turn makes it upright
        xyz, valid, scale = co.synthetic_sheet(0.0, rows=40, cols=40)
        xyz[:, 20:, 2] = 4000.0 - xyz[:, 20:, 2]
        got = co.decide(co.measure_grid(xyz, valid, scale), {"vote": "outward", "confidence": "clear"})
        self.assertFalse(got["applicable"])
        self.assertTrue(any("consistency" in w for w in got["why"]))

    def test_ambiguous_vote_is_not_applicable(self):
        xyz, valid, scale = co.synthetic_sheet(10.0)
        got = co.decide(co.measure_grid(xyz, valid, scale), {"vote": None, "confidence": "ambiguous"})
        self.assertFalse(got["applicable"])
        self.assertIsNone(got["angle_deg"])

    def test_measure_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            xyz, valid, scale = co.synthetic_sheet(-40.0, axis=(500.0, 500.0))
            p = co.write_tifxyz(Path(tmp) / "s.tifxyz", xyz, scale)
            umb = Path(tmp) / "umbilicus.json"
            umb.write_text(json.dumps([{"x": 500.0, "y": 500.0, "z": 0.0}, {"x": 500.0, "y": 500.0, "z": 5000.0}]))
            code, out = run_cli("canvasorient", "measure", str(p), "--umbilicus", str(umb))
        self.assertEqual(code, 0)
        rec = json.loads(out)
        self.assertTrue(rec["applicable"], rec["why"])
        self.assertFalse(rec["mirror"])
        self.assertAlmostEqual(rec["angle_deg"], -40.0, delta=co.CHECK_TOL_DEG)

    def test_read_tifxyz_without_tifffile_codecs(self):
        # tifffile failing (a codec it lacks) falls back to the standard-library reader
        with tempfile.TemporaryDirectory() as tmp:
            xyz, valid, scale = co.synthetic_sheet(15.0, rows=9, cols=11)
            p = co.write_tifxyz(Path(tmp) / "s.tifxyz", xyz, scale)
            want = co.read_tifxyz(p)
            with mock.patch.object(tifffile, "imread", side_effect=ValueError("requires the 'imagecodecs' package")):
                got = co.read_tifxyz(p)
        np.testing.assert_array_equal(got["valid"], want["valid"])
        np.testing.assert_allclose(got["xyz"], want["xyz"])


@unittest.skipIf(np is None, "numpy, tifffile and zarr are needed")
class Transform(unittest.TestCase):
    def test_round_trip_record(self):
        rt = co.check_round_trip()
        self.assertTrue(rt["passes"], rt)
        self.assertLess(rt["positions_max_error_px"], 1e-9)
        self.assertTrue(rt["right_angles_exact"])
        self.assertLessEqual(rt["smooth_round_trip_max_levels"], co.ROUND_TRIP_MAX_LEVELS)
        self.assertEqual(rt["fit_angle_deg"], 63.75)
        self.assertEqual(rt["complex_fit_angle_deg"], -63.75)

    def test_right_angles_are_numpy_rotations(self):
        a = np.arange(3 * 5 * 7, dtype=np.uint8).reshape(3, 5, 7)
        for k, angle in enumerate((0.0, 90.0, 180.0, 270.0)):
            for mirror in (False, True):
                t = co.plan_turn(a.shape[1:], angle, mirror)
                turned, inside, how = co.turn_stack(a, t)
                self.assertEqual(how, "exact copy")
                self.assertTrue(inside.all())
                src = a[:, :, ::-1] if mirror else a
                np.testing.assert_array_equal(turned, np.rot90(src, -k, axes=(1, 2)))
                back, valid = co.back_map(turned[2], t)
                np.testing.assert_array_equal(back, a[2])
                self.assertTrue(valid.all())

    def test_direction_on_the_turned_canvas(self):
        # a ramp growing along canvas direction phi reads phi - psi after the turn, and -phi - psi after a mirror
        ii, jj = np.mgrid[0:80, 0:90].astype(np.float64)
        phi = math.radians(50.0)
        ramp = ii * math.cos(phi) + jj * math.sin(phi)
        for psi, mirror, want in ((50.0, False, 0.0), (20.0, False, 30.0), (-50.0, True, 0.0), (0.0, True, -50.0)):
            t = co.plan_turn(ramp.shape, psi, mirror)
            turned, inside, _ = co.turn_plane(ramp, t)
            strict = co.turned_valid(t, halo=False)
            self.assertTrue((inside | ~strict).all())         # the halo only adds pixels
            got = co.measure_image(turned, strict, 0.0, 0.0)["phi_deg"]
            self.assertAlmostEqual(got, want, delta=0.05, msg=(psi, mirror))

    def test_float_maps_keep_nan_outside_and_dtype(self):
        m = np.random.default_rng(1).random((30, 40)).astype(np.float32)
        t = co.plan_turn(m.shape, 33.0)
        turned, inside, _ = co.turn_plane(m, t)
        self.assertEqual(turned.dtype, np.float32)
        self.assertTrue(np.isnan(turned[~inside]).all())
        self.assertFalse(np.isnan(turned[inside]).any())
        back, valid = co.back_map(turned, t)
        self.assertEqual(back.shape, m.shape)
        self.assertEqual(back.dtype, np.float32)
        self.assertTrue(valid.all())
        self.assertFalse(np.isnan(back).any())

    def test_back_ignores_the_empty_corners(self):
        m = np.random.default_rng(2).random((40, 50)).astype(np.float32)
        for order in co.ORDERS:
            t = co.plan_turn(m.shape, -71.0, order=order)
            turned, inside, _ = co.turn_plane(m, t)
            np.testing.assert_array_equal(inside, co.turned_valid(t))
            clean, _ = co.back_map(np.where(inside, turned, 0.5).astype(np.float32), t)
            dirty, valid = co.back_map(np.where(inside, turned, 1e6).astype(np.float32), t)
            self.assertTrue(valid.all())
            np.testing.assert_array_equal(clean, dirty)
            self.assertLess(float(np.abs(dirty).max()), 2.0)

    def test_nearest_round_trip_at_any_angle_on_constant_patches(self):
        m = np.zeros((64, 64), np.uint8)
        m[16:48, 16:48] = 200
        t = co.plan_turn(m.shape, 27.0, order=0)
        turned, _, how = co.turn_plane(m, t)
        self.assertEqual(how, "nearest")
        back, _ = co.back_map(turned, t)
        self.assertTrue(set(np.unique(back)) <= {0, 200})
        self.assertTrue((back[20:44, 20:44] == 200).all())

    def test_fit_angle_returns_psi(self):
        for psi, mirror in ((63.75, False), (-30.0, False), (120.0, True)):
            t = co.plan_turn((50, 70), psi, mirror)
            rows, cols = co.positions(t)
            ii, jj = np.mgrid[0:t["turned_shape"][0]:7, 0:t["turned_shape"][1]:7]
            src = np.stack([ii.ravel(), jj.ravel()], 1).astype(np.float64)
            dst = np.stack([rows[::7, ::7].ravel(), cols[::7, ::7].ravel()], 1)
            fit = co.fit_angle(src, dst)
            self.assertIs(fit["mirror"], mirror)
            if not mirror:
                self.assertAlmostEqual(fit["angle_deg"], psi, places=3)

    def test_apply_and_back_cli(self):
        yy, xx = np.mgrid[0:70, 0:90].astype(np.float64)
        stack = np.stack([(120 + 50 * np.sin(yy / 9.0 + k) * np.cos(xx / 11.0)) for k in range(4)]).astype(np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = co.write_stack(tmp / "render.zarr", stack)
            code, out = run_cli("canvasorient", "apply", str(src), "41.5", str(tmp / "turned"))
            self.assertEqual(code, 0, out)
            rec = json.loads(out)
            t = json.loads((tmp / "turned" / "transform.json").read_text())
            self.assertEqual(rec["turned_shape"], t["turned_shape"])
            self.assertEqual(t["source_shape"], [70, 90])
            self.assertEqual(t["sampler"], "bilinear")
            turned = co.read_stack(tmp / "turned" / "layers.zarr")
            self.assertEqual(list(turned.shape), [4, *t["turned_shape"]])
            self.assertEqual(turned.dtype, np.uint8)
            self.assertEqual(co._array_sha256(turned), t["turned_sha256"])
            self.assertEqual(co._array_sha256(stack), t["source_sha256"])
            valid = tifffile.imread(str(tmp / "turned" / "valid.tif"))
            self.assertEqual(int((valid == 255).sum()), t["valid_px"])
            # an ink map on the turned canvas: here layer 2 as float, so the round trip can be compared
            co.write_map(tmp / "ink_f.tif", turned[2].astype(np.float32) / 255.0)
            code, out = run_cli("canvasorient", "back", str(tmp / "ink_f.tif"), str(tmp / "turned" / "transform.json"),
                                str(tmp / "back.tif"))
            self.assertEqual(code, 0, out)
            b = tifffile.imread(str(tmp / "back.tif"))
            self.assertEqual(b.shape, (70, 90))
            self.assertEqual(json.loads(out)["invalid_px"], 0)
            err = np.abs(b * 255.0 - stack[2].astype(np.float64))[2:-2, 2:-2]
            self.assertLessEqual(float(err.max()), co.ROUND_TRIP_MAX_LEVELS + 0.5)
            # a map of the wrong shape is refused
            co.write_map(tmp / "wrong.tif", np.zeros((70, 90), np.float32))
            code, _ = run_cli("canvasorient", "back", str(tmp / "wrong.tif"), str(tmp / "turned" / "transform.json"),
                              str(tmp / "x.tif"))
            self.assertEqual(code, 2)
            # a transform whose turned canvas does not follow from its angle is refused
            bad = dict(t, angle_deg=t["angle_deg"] + 30.0)
            (tmp / "bad.json").write_text(json.dumps(bad))
            code, _ = run_cli("canvasorient", "back", str(tmp / "ink_f.tif"), str(tmp / "bad.json"),
                              str(tmp / "x.tif"))
            self.assertEqual(code, 2)


@unittest.skipIf(np is None, "numpy, tifffile and zarr are needed")
class SelfCheckCanFail(unittest.TestCase):
    def test_check_passes(self):
        code, out = run_cli("canvasorient", "check")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["passes"])

    def test_sign_flipped_turn_is_caught(self):
        real = co.decide

        def flipped(rec, vote, *a, **k):
            rec = real(rec, vote, *a, **k)
            if rec["angle_deg"] is not None:
                rec["angle_deg"] = co.wrap(-rec["angle_deg"])
            return rec
        with mock.patch.object(co, "decide", flipped), tempfile.TemporaryDirectory() as tmp:
            recs = co.check_synthetic(tmp)
        self.assertFalse(all(r["passes"] for r in recs))

    def test_mirror_ignored_is_caught(self):
        real = co.decide

        def no_mirror(rec, vote, *a, **k):
            rec = real(rec, vote, *a, **k)
            if rec["mirror"]:
                rec["angle_deg"] = rec["phi_deg"]
            return rec
        with mock.patch.object(co, "decide", no_mirror), tempfile.TemporaryDirectory() as tmp:
            recs = co.check_synthetic(tmp)
        self.assertFalse(all(r["passes"] for r in recs if r.get("planted_mirror")))

    def test_rows_and_columns_swapped_is_caught(self):
        real = co.gradients

        def swapped(z, valid=None):
            gr, gc = real(z, valid)
            return gc, gr
        with mock.patch.object(co, "gradients", swapped), tempfile.TemporaryDirectory() as tmp:
            recs = co.check_synthetic(tmp)
        self.assertFalse(all(r["passes"] for r in recs))

    def test_transposed_rotation_is_caught(self):
        real = co._rot

        def transposed(deg):
            m = real(deg)
            return [[m[0][0], m[1][0]], [m[0][1], m[1][1]]]
        with mock.patch.object(co, "_rot", transposed):
            self.assertFalse(co.check_round_trip()["passes"])

    def test_off_centre_turn_is_caught(self):
        real = co.plan_turn

        def shifted(*a, **k):
            t = real(*a, **k)
            t["turned_centre"] = [t["turned_centre"][0] + 0.5, t["turned_centre"][1]]
            return t
        with mock.patch.object(co, "plan_turn", shifted):
            rt = co.check_round_trip()
        self.assertFalse(rt["passes"])

    def test_check_exits_1_when_a_check_fails(self):
        with mock.patch.object(co, "check_round_trip", return_value={"passes": False}):
            code, out = run_cli("canvasorient", "check")
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["passes"])

    def test_check_mesh_standard_and_planted(self):
        with tempfile.TemporaryDirectory() as tmp:
            xyz, valid, scale = co.synthetic_sheet(1.0, rows=60, cols=70, noise=0.5)
            p = co.write_tifxyz(Path(tmp) / "pub.tifxyz", xyz, scale)
            r = co.check_mesh(p)
            self.assertTrue(r["passes"], r)
            self.assertTrue(r["standard"])
            self.assertEqual(len(r["planted"]), 4)
            # a canvas turned by 40 degrees is not the published layout: --require-standard fails it
            xyz, valid, scale = co.synthetic_sheet(40.0, rows=60, cols=70, noise=0.5)
            q = co.write_tifxyz(Path(tmp) / "turned.tifxyz", xyz, scale)
            r = co.check_mesh(q)
            self.assertTrue(r["passes"])
            self.assertFalse(r["standard"])
            code, out = run_cli("canvasorient", "check", "--mesh", str(q), "--require-standard")
            self.assertEqual(code, 1)
            code, out = run_cli("canvasorient", "check", "--mesh", str(p), "--require-standard",
                                "--out", str(Path(tmp) / "rec.json"))
            self.assertEqual(code, 0)
            self.assertTrue(json.loads((Path(tmp) / "rec.json").read_text())["passes"])

    def test_non_square_grid_skips_planting(self):
        with tempfile.TemporaryDirectory() as tmp:
            xyz, valid, _ = co.synthetic_sheet(5.0, rows=30, cols=30)
            p = co.write_tifxyz(Path(tmp) / "s.tifxyz", xyz, [0.25, 0.5])
            r = co.check_mesh(p)
        self.assertIn("planted_skipped", r)
        self.assertEqual(r["planted"], [])


@unittest.skipUnless(EVIDENCE.is_file(), "the published-mesh evidence is not in this checkout")
class PublishedEvidence(unittest.TestCase):
    """The committed measurement of published open-data meshes (geometry only): each reads as the published
    layout, within the stated tolerance, with its planted turns recovered."""

    def test_published_meshes_read_standard(self):
        doc = json.loads(EVIDENCE.read_text())
        self.assertTrue(doc["self_check_passes"])
        self.assertEqual(doc["tolerances_deg"]["published"], co.PUBLISHED_TOL_DEG)
        self.assertGreaterEqual(len(doc["meshes"]), 3)
        for m in doc["meshes"]:
            self.assertTrue(m["passes"], m["segment"])
            self.assertTrue(m["standard"], m["segment"])
            self.assertLessEqual(abs(m["phi_deg"]), co.PUBLISHED_TOL_DEG)
            self.assertFalse(m["mirror"])
        w00 = next(m for m in doc["meshes"] if m["segment"] == "0841-w00")
        self.assertAlmostEqual(w00["phi_deg"], -2.31, delta=0.05)


if __name__ == "__main__":
    unittest.main()
