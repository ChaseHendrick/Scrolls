"""kit coverage: turns, heights, angles and untraced wraps on synthetic spiral sheets with known answers."""

import math
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

R0, PITCH, CENTER = 2000.0, 40.0, 1000.0


def sheet(k, turns=1.1, z0=100.0, z1=500.0, shift=0.0):
    """A tifxyz Segment on wrap k of an Archimedean spiral around (CENTER, CENTER): r = R0 + PITCH * (k + phi / 2 pi),
    grid rows along z every 10 voxels, columns along the sheet about every 10 voxels of arc."""
    from kit import tifxyz
    cols = int(turns * 2 * math.pi * (R0 + PITCH * k) / 10)
    phi = np.linspace(0, turns * 2 * math.pi, cols)
    z = np.arange(z0, z1, 10.0)
    r = R0 + PITCH * (k + phi / (2 * math.pi)) + shift
    zz, pp = np.meshgrid(z, phi, indexing="ij")
    rr = np.broadcast_to(r, zz.shape)
    xyz = np.stack([CENTER + rr * np.cos(pp), CENTER + rr * np.sin(pp), zz], -1)
    return tifxyz.Segment(xyz, np.ones(zz.shape, bool), {"scale": [0.1, 0.1]}, f"w{k}", None)


def line():
    from kit import stackcheck
    return stackcheck.Umbilicus([0.0, 2000.0], [CENTER, CENTER], [CENTER, CENTER])


@unittest.skipIf(np is None, "needs numpy")
class TestCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kit import coverage
        cls.cv = coverage
        umb = line()
        specs = {"w0": sheet(0), "w1": sheet(1), "w2": sheet(2), "w5": sheet(5), "w5copy": sheet(5, shift=1.0),
                 "high": sheet(9, z0=700.0, z1=900.0)}
        cls.ids = list(specs)
        cls.recs, cls.samples = [], []
        for name, seg in specs.items():
            rec, smp = coverage.mesh_record(name, seg, umb)
            cls.recs.append(rec)
            cls.samples.append(smp)

    def test_turns_and_own_pitch(self):
        for rec in self.recs:
            self.assertAlmostEqual(rec["turns"], 1.1, delta=0.03, msg=rec["id"])
            self.assertAlmostEqual(rec["own_step_p50"], PITCH, delta=1.0, msg=rec["id"])

    def test_untraced_wraps_between_pairs(self):
        w = self.cv.wraps(self.samples, self.ids, min_cells=20)
        self.assertAlmostEqual(w["pitch_vox"], PITCH, delta=1.0)
        self.assertTrue(w["pitch_from"].startswith("median step one turn"))
        pairs = {frozenset((g["inner"], g["outer"])): g for g in w["gaps"] + w["neighbors"]}
        self.assertEqual(pairs[frozenset(("w0", "w1"))]["wraps_missing"], 0)
        self.assertEqual(pairs[frozenset(("w1", "w2"))]["wraps_missing"], 0)
        gap = [g for g in w["gaps"] if {g["inner"], g["outer"]} <= {"w2", "w5", "w5copy"}]
        self.assertTrue(gap, w["gaps"])
        self.assertEqual(gap[0]["inner"], "w2")
        self.assertEqual(gap[0]["wraps_missing"], 2)
        self.assertEqual({w["overlaps"][0]["inner"], w["overlaps"][0]["outer"]}, {"w5", "w5copy"})
        self.assertLess(w["overlaps"][0]["step_vox"], 2)

    def test_a_given_pitch_changes_the_count(self):
        w = self.cv.wraps(self.samples, self.ids, pitch=PITCH / 2, min_cells=20)
        gap = [g for g in w["gaps"] if g["inner"] == "w2"][0]
        self.assertEqual(gap["wraps_missing"], 5)  # 120 voxels at a pitch of 20: six steps, five wraps between
        self.assertEqual(w["pitch_from"], "given")

    def test_heights_and_angles(self):
        grid = self.cv.accumulate(self.samples, 0.0, 1000.0, z_bins=10, theta_bins=36, r_step=20.0)
        g = self.cv.gaps(grid, voxel_um=2.0)
        spans = [(h["z0"], h["z1"]) for h in g["height_gaps"]]
        self.assertEqual(spans, [(0.0, 100.0), (500.0, 700.0), (900.0, 1000.0)])
        self.assertEqual(g["height_gaps"][1]["mm"], 0.4)
        traced = [r for r in g["rows"] if r["theta_share"] > 0]
        self.assertTrue(all(r["theta_share"] == 1.0 and r["largest_arc_deg"] == 0.0 for r in traced))
        self.assertEqual(g["full_turn_traced_heights"], 1.0)

    def test_largest_arc_wraps_around(self):
        row = [True] * 10 + [False] * 5 + [True] * 10 + [False] * 3
        self.assertEqual(self.cv._largest_arc(row), 5)
        row = [False] * 4 + [True] * 20 + [False] * 4  # 4 + 4 across 360 degrees
        self.assertEqual(self.cv._largest_arc(row), 8)
        self.assertEqual(self.cv._largest_arc([False] * 6), 6)

    def test_partial_turn_has_an_untraced_arc(self):
        seg = sheet(0, turns=0.5)
        rec, smp = self.cv.mesh_record("half", seg, line())
        self.assertAlmostEqual(rec["turns"], 0.5, delta=0.02)
        self.assertIsNone(rec["own_step_p50"])  # no row spans a turn
        grid = self.cv.accumulate([smp], 100.0, 500.0, z_bins=4, theta_bins=36, r_step=20.0)
        g = self.cv.gaps(grid)
        self.assertAlmostEqual(g["theta_share_median"], 0.5, delta=0.03)
        self.assertAlmostEqual(g["largest_arc_median_deg"], 180, delta=10)

    def test_picture_shape_and_background(self):
        # height bins must be coarser than the subsampled rows (60 voxels here), as the 600 voxel default bins are
        # on a real scan
        grid = self.cv.accumulate(self.samples, 0.0, 1000.0, z_bins=16, theta_bins=72, r_step=20.0)
        img = self.cv.picture(grid)
        self.assertEqual(img.dtype, np.uint8)
        self.assertEqual(img.shape[0], 512)
        self.assertGreaterEqual(img.shape[1], 360 + 16)
        bg = [8, 12, 16]
        self.assertFalse((img[200, 100] == bg).all())  # 32 rows per height bin: row 200 is z 375 to 437
        self.assertTrue((img[8, 100] == bg).all())     # z 0 to 62, below every mesh
        self.assertTrue((img[300, 100] == bg).all())   # z 562 to 625, in the gap between 500 and 700

    def test_refuses_a_picture_of_a_prize_scroll(self):
        from kit import coverage
        from kit.verify import VerifyError
        args = coverage.build_parser.__globals__["argparse"].Namespace(scroll="PHercParis4", volume=None, png="x.png")
        with self.assertRaises(VerifyError) as cm:
            coverage.cmd_coverage(args)
        self.assertIn("prize list", str(cm.exception))

    def test_cli_is_registered(self):
        from kit import cli
        self.assertIn("coverage", cli.__doc__.split("\n")[0])
        self.assertTrue(any("coverage" in names for _, names in cli.GROUPS))


if __name__ == "__main__":
    unittest.main()
