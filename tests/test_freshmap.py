"""kit.freshmap: classes, distances, boxes, mesh naming, tar filtering and query, on a small
synthetic m7 volume (no network)."""

import json
import math
import tarfile
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import scipy  # noqa: F401
    import tifffile
except ImportError:  # pragma: no cover
    np = None

from kit import freshmap as F

LEVEL = 1          # synthetic m7 at level 1 (2 level-0 voxels a side)
CH = 16            # chunk side
SHAPE = (32, 32, 32)
PLANES_Y = (8, 20)  # papyrus sheets: the x-z planes y = 8 and y = 20 (level-1 voxels)


def write_zarr(root):
    a = np.zeros(SHAPE, np.uint8)
    for y in PLANES_Y:
        a[:, y, :] = 255
    lv = Path(root) / str(LEVEL)
    lv.mkdir(parents=True)
    (lv / ".zarray").write_text(json.dumps({"chunks": [CH] * 3, "compressor": None, "dtype": "|u1", "fill_value": 0,
                                            "filters": None, "order": "C", "shape": list(SHAPE), "zarr_format": 2,
                                            "dimension_separator": "/"}))
    for cz in range(2):
        for cy in range(2):
            for cx in range(2):
                c = a[cz * CH:(cz + 1) * CH, cy * CH:(cy + 1) * CH, cx * CH:(cx + 1) * CH]
                if not c.any():
                    continue           # a missing chunk reads as fill
                p = lv / str(cz) / str(cy)
                p.mkdir(parents=True, exist_ok=True)
                (p / str(cx)).write_bytes(np.ascontiguousarray(c).tobytes())
    return a


def write_mesh(folder, y_l1, z0=0, z1=64, x0=0, x1=64, step=4.0):
    """A flat tifxyz on the level-1 plane y = y_l1 (level-0 y at that voxel's centre), x and z in level-0 voxels."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    zs = np.arange(z0, z1, step) + 0.5
    xs = np.arange(x0, x1, step) + 0.5
    Z, X = np.meshgrid(zs, xs, indexing="ij")
    Y = np.full(Z.shape, (y_l1 + 0.5) * 2 ** LEVEL)
    for n, v in (("x", X), ("y", Y), ("z", Z)):
        tifffile.imwrite(str(folder / f"{n}.tif"), v.astype(np.float32))
    (folder / "meta.json").write_text("{}")
    return folder


@unittest.skipIf(np is None, "numpy, scipy and tifffile needed")
class FreshMapTest(unittest.TestCase):
    def setUp(self):
        self._thick = F.THICK_L0
        F.THICK_L0 = 16             # 2 coarse cells of the synthetic map
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        write_zarr(self.d / "m7")

    def tearDown(self):
        F.THICK_L0 = self._thick
        self.tmp.cleanup()

    def _build(self, read, traced=(), **kw):
        return F.build("PHercTEST", [str(x) for x in read], [str(x) for x in traced], self.d / "out", level=LEVEL,
                       sum_level=LEVEL + 2, jobs=1, volume=str(self.d / "m7"), voxel_um=500.0, n_targets=5,
                       cache=self.d / "cache", say=None, frame="F", **kw)

    def test_read_sheet_is_read_other_is_fresh(self):
        m = write_mesh(self.d / "read" / "segA", PLANES_Y[0])
        rec = self._build([m.parent])
        t = rec["totals_cm2"]
        # each plane: 32 x 32 voxels of 1 mm (level 1 of 500 um), two exposed faces each: 32 * 32 / (4 / pi) mm2
        plane = 32 * 32 * 2 / 2 / (4 / math.pi) * 0.1 ** 2
        self.assertAlmostEqual(t["read"], round(plane, 1), places=1)
        self.assertAlmostEqual(t["fresh"], round(plane, 1), places=1)
        self.assertEqual(t["traced"], 0.0)
        self.assertEqual(rec["faces_by_axis"]["z"], 0)
        self.assertEqual(rec["faces_by_axis"]["x"], 0)
        self.assertTrue(rec["targets"])
        self.assertGreater(rec["targets"][0]["fresh"], 0)
        y0, y1 = rec["targets"][0]["region"]["y"]
        self.assertTrue(y0 <= PLANES_Y[1] * 2 < y1)
        for n in ("summary.json", "grid.npz", "occ-read.bits", "occ-traced.bits", "unrolled.png", "side.png",
                  "meshes.json"):
            self.assertTrue((self.d / "out" / n).is_file(), n)

    def test_fresh_distance_is_exact(self):
        # a read mesh on sheet y 8 lies 12 level-1 voxels (24 level-0) from sheet y 20: fresh at 20, read at 25
        m = write_mesh(self.d / "read" / "segB", PLANES_Y[1] - 12)
        t20 = self._build([m.parent])["totals_cm2"]
        self.assertGreater(t20["fresh"], 0.0)
        self.assertEqual(t20["read"], t20["fresh"])
        t25 = self._build([m.parent], fresh_vox=25.0)["totals_cm2"]
        self.assertEqual(t25["fresh"], 0.0)
        self.assertAlmostEqual(t25["read"], 2 * t20["read"], delta=0.2)

    def test_traced_and_box_classes(self):
        m = write_mesh(self.d / "traced" / "fitA", PLANES_Y[0])
        boxes = self.d / "boxes.json"
        boxes.write_text(json.dumps([{"id": "keep-out", "z": [0, 32], "y": [0, 64], "x": [0, 64]}]))
        rec = self._build([], [m.parent], boxes_path=boxes)
        t = rec["totals_cm2"]
        self.assertGreater(t["traced"], 0)
        self.assertEqual(t["read"], 0.0)
        # half the second sheet (z 0 to 32 level 0 = level-1 z 0 to 16) is boxed, the rest fresh
        self.assertAlmostEqual(t["boxed"], t["fresh"], places=1)
        self.assertEqual(rec["boxes"], 1)

    def test_bad_boxes_and_unknown_scroll(self):
        bad = self.d / "bad.json"
        bad.write_text(json.dumps([{"id": "x", "z": [0]}]))
        with self.assertRaises(F.FreshMapError):
            F.load_boxes(bad)
        self.assertEqual(F.load_boxes(None), [])
        with self.assertRaises(F.FreshMapError):
            F.m7_url("PHercNOPE")
        self.assertIn("PHerc0343/representations/predictions/surfaces/20250521140437-", F.m7_url("PHerc0343"))

    def test_query(self):
        m = write_mesh(self.d / "read" / "segA", PLANES_Y[0])
        self._build([m.parent])
        q1 = write_mesh(self.d / "q" / "onfresh", PLANES_Y[1], z0=8, z1=40)
        q2 = write_mesh(self.d / "q" / "onread", PLANES_Y[0], z0=8, z1=40)
        q3 = write_mesh(self.d / "q" / "offsheet", 14, z0=8, z1=40)
        rows = {r["name"]: r for r in F.query(self.d / "out", [self.d / "q"])["meshes"]}
        self.assertEqual(rows["onfresh"]["fresh_share"], 1.0)
        self.assertEqual(rows["onfresh"]["seated_share"], 1.0)
        self.assertEqual(rows["onread"]["near_read_share"], 1.0)
        self.assertEqual(rows["onread"]["fresh_cm2"], 0.0)
        self.assertEqual(rows["offsheet"]["seated_share"], 0.0)
        self.assertEqual(rows["offsheet"]["fresh_cm2"], 0.0)

    def test_near_mask_ball(self):
        occ = F.Occ(self.d / "n.bits", (11, 11, 11), create=True)
        occ.add(occ.key(np.array([[5, 5, 5]])))
        m = F.near_mask(occ, (0, 0, 0), (11, 11, 11), 3.0)
        self.assertTrue(m[5, 5, 8] and m[5, 5, 2])
        self.assertFalse(m[5, 5, 9])
        self.assertFalse(m[7, 7, 7])          # sqrt(12) > 3, inside the cube
        self.assertTrue(m[6, 7, 7])            # 3.0 exactly
        self.assertFalse(F.near_mask(None, (0, 0, 0), (4, 4, 4), 3.0).any())

    def test_occ_bits_round_trip(self):
        o = F.Occ(self.d / "o.bits", (5, 6, 13), create=True)
        self.assertEqual(o.dims, (5, 6, 16))
        rows = np.array([[0, 0, 0], [4, 5, 12], [2, 3, 7], [2, 3, 8]])
        o.add(np.sort(o.key(rows)))
        o.mm.flush()
        r = F.Occ(self.d / "o.bits")
        self.assertEqual(r.count(), 4)
        b = r.box((-1, -1, -1), (6, 7, 14))
        self.assertEqual(sorted(map(tuple, np.argwhere(b) - 1)), sorted(map(tuple, rows)))
        self.assertTrue(r.box((2, 3, 8), (3, 4, 9)).all())
        self.assertFalse(r.box((10, 10, 10), (12, 12, 12)).any())

    def test_valid_of_threshold(self):
        v = np.array([0.0, -0.4, -0.5, -0.6, -1.0, np.nan])
        ok = np.zeros_like(v)
        self.assertEqual(F.valid_of(v, ok, ok).tolist(), [True, True, False, False, False, False])
        self.assertEqual(F.valid_of(ok, ok, v).tolist(), [True, True, False, False, False, False])
        self.assertEqual(F.valid_of(ok, v, ok).tolist(), [True, True, False, False, False, False])

    def test_thick_fresh_drops_slivers(self):
        g = np.zeros((4, 10, 3, 3))
        g[3, 2:7, 1, 1] = 1.0        # a run of 5 coarse cells: kept with 3
        g[3, 8, 0, 0] = 1.0          # one cell thick: a seam sliver, dropped
        g[0, 2, 1, 1] = 2.0          # READ dominates this cell: it breaks the run there
        th = F.thick_fresh(g, 3)
        self.assertEqual(th[8, 0, 0], 0.0)
        self.assertEqual(th[3:7, 1, 1].tolist(), [1.0] * 4)
        self.assertEqual(th[2, 1, 1], 0.0)
        self.assertEqual(F.thick_fresh(g, 1)[8, 0, 0], 1.0)

    def test_names_and_tar_filter(self):
        self.assertEqual(F.mesh_name("a/seat/unitB/snap"), "unitB")
        self.assertIsNone(F.mesh_name("a/w12/sham_trim"))
        src = self.d / "src"
        write_mesh(src / "seat" / "unitA" / "snap", 3)
        write_mesh(src / "w1" / "sham", 3)
        (src / "seat" / "unitA" / "snap" / "maps.npz").write_bytes(b"not for us")
        tar = self.d / "in.tar"
        with tarfile.open(tar, "w") as t:
            t.add(src, arcname="inputs")
        ms = F.find_meshes([tar], self.d / "cache")
        self.assertEqual([n for n, _ in ms], ["unitA"])
        self.assertFalse(list((self.d / "cache").rglob("maps.npz")))


if __name__ == "__main__":
    unittest.main()
