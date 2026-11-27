import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:          # map tests skip without their numerical dependencies
    np = None

from kit import atlascomm as C


def record(scroll="PHerc0009B", h=20, w=30, hole=False):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x, y, z = 100 + 2 * xx, 200 + 0 * xx, 300 + 2 * yy          # a flat sheet, nodes 2 voxels apart
    if hole:
        x[5:8, 5:8] = -1
        y[5:8, 5:8] = -1
        z[5:8, 5:8] = -1
    return {"id": f"{scroll}-x1-y2-z3", "scroll": scroll,
            "scan": f"https://example.org/{scroll}/volumes/20250521125136-8.640um-1.2m-116keV-masked.zarr/0",
            "voxel_um": 8.64, "size_vx": [2 * w, 2 * h], "centre_xyz": [1, 2, 3], "box_min_xyz": [100, 200, 300],
            "box_max_xyz": [158, 200, 338], "area_cm2": 0.0, "x": x.tolist(), "y": y.tolist(), "z": z.tolist()}


@unittest.skipIf(np is None, "needs numpy")
class RowTest(unittest.TestCase):
    def test_flat_sheet_is_isometric_and_its_area_is_exact(self):
        r = C.row_of(record(), measure=True)
        self.assertTrue(r["measured"])
        self.assertIsNone(r["error"])
        self.assertEqual(r["edge_p50"], 1.0)
        self.assertEqual(r["within_10pct"], 1.0)
        self.assertEqual(r["holes_nodes"], 0)
        # 19 x 29 cells of 2 x 2 voxels at 8.64 um
        self.assertAlmostEqual(r["area_cm2_measured"], round(19 * 29 * 4 * (8.64e-4) ** 2, 3), places=3)
        self.assertEqual(r["volume"], "20250521125136-8.640um-1.2m-116keV-masked")

    def test_a_hole_is_counted_so_the_check_can_fail(self):
        r = C.row_of(record(hole=True), measure=True)
        self.assertGreater(r["holes_nodes"], 0)
        self.assertFalse(r["clean"])

    def test_unmeasured_rows_carry_metadata_only(self):
        r = C.row_of(record(), measure=False)
        self.assertFalse(r["measured"])
        self.assertIsNone(r["edge_p50"])
        self.assertEqual((r["box_max_x"], r["size_y"]), (158, 40))

    def test_write_and_summary(self):
        rows = [C.row_of(record(), True), C.row_of(record("PHerc0841"), False)]
        with tempfile.TemporaryDirectory() as d:
            C.write(d, rows)
            lines = Path(d, "atlas-15k.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(x)["scroll"] for x in lines], ["PHerc0009B", "PHerc0841"])
            head = Path(d, "atlas-15k.csv").read_text().splitlines()[0].split(",")
            self.assertEqual(tuple(head), C.COLUMNS)
        s = C.summary(rows)
        self.assertEqual([(x["scroll"], x["measured"]) for x in s], [("PHerc0009B", 1), ("PHerc0841", 0)])


if __name__ == "__main__":
    unittest.main()
