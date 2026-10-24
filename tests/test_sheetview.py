"""Tests for kit.sheetview on synthetic sheets and volumes built here (no downloads).

A flat sheet over a volume whose value is its own x index samples exactly that index at every vertex; a bright slab
6 voxels behind a sheet is missed at depth 0 and found by the max along the normal at depth 8, so the depth search
can fail; the VTK file has one point per valid node and two triangles per complete cell (a planted hole removes
its cells); the state looks at the sheet face on; bad inputs exit 2."""

import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import tifffile
    import zarr
except ImportError:  # pragma: no cover
    np = None

from kit import cli
from kit import sheetview as sv
from kit.verify import VerifyError

STEP = 4.0
SHAPE = (64, 64, 64)          # z, y, x
Z0 = 30.0


def write_seg(folder, xyz):
    folder.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate("xyz"):
        tifffile.imwrite(folder / f"{c}.tif", xyz[..., i].astype(np.float32))
    (folder / "meta.json").write_text(json.dumps({"scale": [1 / STEP, 1 / STEP], "format": "tifxyz"}))
    return folder


def flat(h=10, w=12, z=Z0):
    r, c = np.mgrid[0:h, 0:w].astype(float)
    return np.stack([8 + c * STEP, 8 + r * STEP, np.full_like(r, z)], -1)


def write_volume(folder, data):
    folder.mkdir(parents=True, exist_ok=True)
    arr = zarr.create_array(str(folder / "0"), shape=data.shape, chunks=(16, 16, 16), dtype=data.dtype,
                            zarr_format=2, fill_value=0)
    arr[:] = data
    (folder / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (folder / ".zattrs").write_text(json.dumps({"multiscales": [{"axes": [{"name": a, "type": "space"}
                                                                         for a in "zyx"],
                                                                "datasets": [{"path": "0", "coordinateTransformations":
                                                                              [{"type": "scale",
                                                                                "scale": [1.0, 1.0, 1.0]}]}]}]}))
    return folder


def x_ramp():
    z, y, x = np.indices(SHAPE)
    return x.astype(np.uint8)


def slab(offset=6, value=200):
    v = np.zeros(SHAPE, np.uint8)
    v[int(Z0) + offset] = value
    return v


def read_vtk(path):
    lines = Path(path).read_text().split("\n")
    head = {l.split()[0]: l.split() for l in lines if l[:1].isalpha()}
    i = next(k for k, l in enumerate(lines) if l.startswith("LOOKUP_TABLE"))
    n = int(head["POINTS"][1])
    values = np.array([float(v) for v in lines[i + 1:i + 1 + n]])
    p = next(k for k, l in enumerate(lines) if l.startswith("POINTS"))
    pts = np.array([[float(t) for t in l.split()] for l in lines[p + 1:p + 1 + n]])
    return head, pts, values


@unittest.skipIf(np is None, "needs numpy, tifffile and zarr")
class SheetviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.seg = write_seg(self.root / "sheet-on-20260102150214-2.000um.tifxyz", flat())

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, volume, **kw):
        return sv.build(self.seg, volume, self.root / "out", cache=self.root / "cache",
                        seg_cache=self.root / "segcache", **kw)

    def test_values_are_the_voxels_under_each_vertex(self):
        vol = write_volume(self.root / "ramp.zarr", x_ramp())
        rec = self.build(vol)
        head, pts, values = read_vtk(self.root / "out" / "sheet.vtk")
        self.assertEqual(rec["vertices"], 120)
        self.assertEqual(int(head["POINTS"][1]), 120)
        np.testing.assert_array_equal(values, np.rint(pts[:, 0]))      # the volume's value is its x index
        self.assertEqual(rec["vertices_outside_volume"], 0)
        self.assertEqual(rec["files"]["sheet.vtk"]["bytes"], (self.root / "out" / "sheet.vtk").stat().st_size)

    def test_depth_search_finds_a_slab_behind_the_sheet_and_misses_it_without(self):
        vol = write_volume(self.root / "slab.zarr", slab(offset=6))
        self.build(vol, depth=0)
        _, _, at0 = read_vtk(self.root / "out" / "sheet.vtk")
        self.assertTrue((at0 == 0).all())                              # control: the sheet itself is empty
        self.build(vol, depth=8)
        _, _, at8 = read_vtk(self.root / "out" / "sheet.vtk")
        self.assertTrue((at8 == 200).all())
        self.build(vol, depth=8, reduce="mean")
        _, _, mean8 = read_vtk(self.root / "out" / "sheet.vtk")
        np.testing.assert_allclose(mean8, 200 / 17, rtol=1e-4)         # one of 17 samples hits the slab
        self.build(vol, depth=5)
        _, _, at5 = read_vtk(self.root / "out" / "sheet.vtk")
        self.assertTrue((at5 == 0).all())                              # the search stops at the depth asked

    def test_triangles_skip_holes_and_crop_and_stride_thin_the_grid(self):
        xyz = flat()
        xyz[4, 5] = -1.0
        write_seg(self.seg, xyz)
        vol = write_volume(self.root / "ramp.zarr", x_ramp())
        rec = self.build(vol)
        self.assertEqual(rec["vertices"], 119)
        self.assertEqual(rec["triangles"], 2 * (9 * 11 - 4))
        rec = self.build(vol, crop=(0, 6, 0, 8), stride=2)
        self.assertEqual((rec["vertices"], rec["triangles"]), (12, 2 * 2 * 3))

    def test_upsample_adds_midpoints(self):
        xyz, valid = sv.upsample(flat(3, 3), np.ones((3, 3), bool), 2)
        self.assertEqual(valid.shape, (5, 5))
        np.testing.assert_allclose(xyz[1, 1], [8 + STEP / 2, 8 + STEP / 2, Z0])
        holed = np.ones((3, 3), bool)
        holed[0, 0] = False
        _, ok = sv.upsample(flat(3, 3), holed, 2)
        self.assertFalse(ok[:2, :2].any())                             # inside the cell with the missing corner
        self.assertTrue(ok[2:, 2:].all())

    def test_state_is_a_mesh_layer_looked_at_face_on(self):
        vol = write_volume(self.root / "ramp.zarr", x_ramp())
        self.build(vol, base_url="https://example.org/sheet/")
        state = json.loads((self.root / "out" / "state.json").read_text())
        mesh = [l for l in state["layers"] if l["type"] == "mesh"]
        self.assertEqual(len(mesh), 1)
        self.assertEqual(mesh[0]["source"]["url"], "vtk://https://example.org/sheet/sheet.vtk")
        self.assertEqual(mesh[0]["source"]["transform"]["inputDimensions"]["x"], [2e-6, "m"])
        self.assertIn("value", mesh[0]["shader"])
        self.assertFalse(state["showSlices"])
        self.assertTrue((self.root / "out" / "link.txt").read_text().startswith(sv.VIEWER))
        # the view's x axis is the grid's column direction and its z axis the sheet normal
        x, y, z, w = state["projectionOrientation"]
        rot = lambda v: np.array(v) + 2 * w * np.cross([x, y, z], v) + 2 * np.cross([x, y, z], np.cross([x, y, z], v))
        np.testing.assert_allclose(rot([1, 0, 0]), [1, 0, 0], atol=1e-5)
        np.testing.assert_allclose(rot([0, 0, 1]), [0, 0, 1], atol=1e-5)

    def test_face_on_follows_a_tilted_sheet(self):
        a = math.radians(30)
        du, dv = [math.cos(a), 0, math.sin(a)], [0, 1, 0]
        x, y, z, w = sv.face_on(du, dv)
        rot = lambda v: np.array(v) + 2 * w * np.cross([x, y, z], v) + 2 * np.cross([x, y, z], np.cross([x, y, z], v))
        np.testing.assert_allclose(rot([1, 0, 0]), du, atol=1e-6)
        np.testing.assert_allclose(rot([0, 0, 1]), np.cross(du, dv), atol=1e-6)

    def test_sampling_at_a_coarser_level_divides_by_its_factor(self):
        idx = sv._sample_index(np.array([[8.0, 12.0, 28.0]]), np.array([[0.0, 0.0, 1.0]]), np.array([0.0, 8.0]),
                               [4.0, 4.0, 4.0])
        np.testing.assert_array_equal(idx[0], [[7, 3, 2], [9, 3, 2]])       # z, y, x at the level

    def test_bad_inputs_exit_2(self):
        vol = write_volume(self.root / "ramp.zarr", x_ramp())
        out = self.root / "o"
        for extra in (["--crop", "0", "50", "0", "5"], ["--depth", "-1"], ["--name", "not valid"],
                      ["--stride", "0"], ["--max-vertices", "10"]):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()) as err:
                code = cli.main(["sheetview", "build", str(self.seg), "--volume", str(vol), "--out", str(out),
                                 "--cache", str(self.root / "c")] + extra)
                self.assertEqual(code, 2, err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["sheetview", "build", str(self.seg), "--volume", str(self.root / "none.zarr"),
                                       "--out", str(out)]), 2)
        with self.assertRaises(VerifyError):
            sv.serve(self.root / "empty")

    def test_cli_prints_a_summary(self):
        vol = write_volume(self.root / "ramp.zarr", x_ramp())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(["sheetview", "build", str(self.seg), "--volume", str(vol), "--out",
                             str(self.root / "o"), "--cache", str(self.root / "c"), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["vertices"], 120)


if __name__ == "__main__":
    unittest.main()
