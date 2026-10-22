"""kit/planted.py: planted sheet switches, holes and mergers with known answers on synthetic tifxyz surfaces, and kit
stackcheck tested against them. Every known answer here comes from the plant's truth, never from the tool under test;
the controls are the clean twin of every plant (nothing flagged), a plant that silently did nothing (caught by check)
and coordinates moved behind the record's back (caught by check). Synthetic data only. The same kit/planted.py is in
Scrolls-private, where more tools are tested against it."""

import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None
try:
    import scipy  # noqa: F401
    HAVE_SCIPY = True
except ImportError:  # pragma: no cover
    HAVE_SCIPY = False

if np is not None:
    from kit import planted as pl

ROOT = Path(__file__).resolve().parent.parent


def run_cli(argv):
    """`python -m kit.planted ARGS`; argv starts with "planted", as the command's name."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pl.main(argv[1:])
    return code, out.getvalue(), err.getvalue()


TWO_PI = 2 * math.pi


def spiral_base(shape=(20, 160), **kw):
    return pl.surface(pl.Sheets(**kw), shape)


def planes_sheets():
    return pl.Sheets("planes", pitch=14.0, step=4.0, zstep=4.0, z0=10.0)


@unittest.skipIf(np is None, "numpy is needed for kit planted")
class Geometry(unittest.TestCase):
    def test_measure_inverts_point_for_both_hands_and_planes(self):
        rng = np.random.default_rng(0)
        for sheets in (pl.Sheets(), pl.Sheets(hand=-1, w0=12.0), planes_sheets(), pl.Sheets(theta0=3.0)):
            k = rng.uniform(-2, 2, (6, 300))
            rr, cc = np.meshgrid(np.arange(6), np.arange(300), indexing="ij")
            xyz = sheets.point(k, rr, cc)
            self.assertLess(np.abs(sheets.measure(xyz, cc) - k).max(), 1e-9, sheets.params())

    def test_columns_cross_the_branch_line(self):
        sheets = pl.Sheets()
        self.assertGreater(float(sheets.theta(159)), math.pi / 2)      # 160 columns pass theta = pi / 2 and beyond
        p = spiral_base((6, 300))
        self.assertGreater(float(p.sheets.theta(299)), math.pi)        # and the atan2 branch line
        self.assertLess(np.abs(p.sheets.measure(p.xyz, p.cols())).max(), 1e-9)

    def test_distance_is_zero_on_every_sheet_and_half_pitch_between(self):
        s = pl.Sheets()
        on = s.point(np.array([-1.0, 0.0, 2.0]), 0, 10)
        mid = s.point(np.array([0.5]), 0, 10)
        self.assertLess(s.distance(on).max(), 1e-9)
        self.assertAlmostEqual(float(s.distance(mid)[0]), s.pitch / 2, places=6)

    def test_prediction_volume_has_five_voxel_sheets(self):
        """The planes geometry's prediction: 5 voxel sheets at x 40 and 54."""
        vol = pl.prediction_volume(planes_sheets(), (20, 10, 70), kmin=0, kmax=1)
        xs = np.unique(np.nonzero(vol)[2]).tolist()
        self.assertEqual(xs, [38, 39, 40, 41, 42, 52, 53, 54, 55, 56])
        self.assertEqual(set(np.unique(vol).tolist()), {0, 255})
        self.assertTrue((vol[:, :, 40] == 255).all())


@unittest.skipIf(np is None, "numpy is needed for kit planted")
class Truth(unittest.TestCase):
    def setUp(self):
        self.base = spiral_base()
        self.h, self.w = self.base.shape

    def test_every_family_gets_its_expected_truth(self):
        for fam, spec in pl.FAMILIES.items():
            t = pl.truth(pl.plant(self.base, fam))
            self.assertEqual(t["expected"], spec["expected"], fam)
        planes = pl.surface(planes_sheets(), (30, 40))
        self.assertEqual(pl.truth(pl.plant(planes, "bridge"))["expected"], "CORRECT")   # a plane over a plane

    def test_family_ids_follow_the_plant_table(self):
        ids = {f: s["id"] for f, s in pl.FAMILIES.items()}
        self.assertEqual(ids, {"clean": None, "switch": "N2", "lens": "N7", "skip": "N6", "merger": "N3",
                               "hole": "Q4", "bridge": "N12"})

    def test_switch_counts_follow_from_the_site(self):
        r0, r1, c0 = 5, 15, 64
        t = pl.truth(pl.plant(self.base, "switch", rows=(r0, r1), cols=(c0, self.w)))
        n, m = r1 - r0, self.w - c0
        self.assertEqual(t["wrong"], n * m)
        self.assertEqual(t["jump_edges_rowwise"], n)           # one jump per row at c0
        self.assertEqual(t["jump_edges_colwise"], 2 * m)       # the block's top and bottom edges
        self.assertEqual(t["wrong_box"], [r0, r1, c0, self.w])
        self.assertEqual((t["off"], t["holes"], t["components"], t["max_offset"]), (0, 0, 1, 1.0))

    def test_skip_moves_two_windings_and_lens_returns(self):
        self.assertEqual(pl.truth(pl.plant(self.base, "skip"))["max_offset"], 2.0)
        lens = pl.plant(self.base, "lens", rows=(5, 15), cols=(60, 80))
        self.assertTrue(np.all(lens.k[:, 80:] == 0))
        self.assertEqual(pl.truth(lens)["wrong"], 200)

    def test_merger_has_no_jump_edge_but_ends_on_the_neighbour(self):
        p = pl.plant(self.base, "merger")
        t = pl.truth(p)
        self.assertEqual(t["jump_edges"], 0)
        self.assertGreater(t["wrong"], 0)
        self.assertTrue(np.allclose(p.k[:, -1], 1.0))
        steps = np.abs(np.diff(p.k, axis=1))
        self.assertLess(steps.max(), 0.5)

    def test_hole_keeps_one_component_and_a_full_height_hole_splits(self):
        t = pl.truth(pl.plant(self.base, "hole", rows=(5, 15), cols=(60, 80)))
        self.assertEqual((t["holes"], t["components"], t["wrong"]), (200, 1, 0))
        t2 = pl.truth(pl.plant(self.base, "hole", rows=(0, self.h), cols=(60, 62)))
        self.assertEqual(t2["components"], 2)

    def test_bridge_leaves_the_curved_sheet(self):
        t = pl.truth(pl.plant(self.base, "bridge"))
        self.assertGreater(t["off"], 0)
        self.assertEqual(t["holes"], 0)

    def test_plants_on_another_base_winding_move_relative_to_it(self):
        """A plant on winding k0 = 3 moves to k0 + dk, not to dk: its vertices sit on winding 2 or 4."""
        base = pl.surface(pl.Sheets(), (20, 160), k0=3)
        for dk in (-1, 1):
            p = pl.plant(base, "lens", rows=(5, 15), cols=(60, 80), dk=dk)
            got = p.sheets.measure(p.xyz, p.cols())
            self.assertLess(np.abs(got[5:15, 60:80] - (3 + dk)).max(), 1e-9)
            self.assertLess(np.abs(got[:, :60] - 3).max(), 1e-9)
            self.assertEqual(pl.truth(p)["wrong"], 200)

    def test_plants_stack_and_bad_sites_are_refused(self):
        p = pl.plant(pl.plant(self.base, "switch"), "hole", rows=(0, 3), cols=(0, 5))
        self.assertEqual(p.family, "switch+hole")
        self.assertEqual([h["family"] for h in p.history], ["switch", "hole"])
        for kw in (dict(rows=(5, 5)), dict(cols=(0, 999)), dict(dk=0)):
            with self.assertRaises(pl.PlantError):
                pl.plant(self.base, "switch", **kw)
        with self.assertRaises(pl.PlantError):
            pl.plant(self.base, "nonsense")
        with self.assertRaises(pl.PlantError):
            pl.plant(self.base, "bridge", rows=(0, 5), cols=(10, 20))


@unittest.skipIf(np is None, "numpy is needed for kit planted")
class WriteAndCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.base = spiral_base()

    def tearDown(self):
        self._tmp.cleanup()

    def test_every_family_round_trips_and_agrees(self):
        for fam in pl.FAMILIES:
            d = pl.write(pl.plant(self.base, fam), self.d / fam)
            self.assertEqual(pl.check(d), [], fam)
            rec = json.loads((d / "planted.json").read_text())
            self.assertTrue(rec["synthetic"])
            self.assertEqual(json.loads((d / "meta.json").read_text())["format"], "tifxyz")
        d = pl.write(pl.plant(pl.surface(pl.Sheets(), (20, 160), k0=2), "switch", dk=-1), self.d / "k2")
        self.assertEqual(pl.check(d), [])

    def test_control_coordinates_moved_behind_the_record_are_caught(self):
        d = pl.write(pl.plant(self.base, "clean"), self.d / "c")
        p, rec = pl.load(d)
        xyz = p.xyz.copy()
        xyz[5:10, 20:30] = p.sheets.point(1.0, p.rows(), p.cols())[5:10, 20:30]   # one winding out, record unchanged
        for i, c in enumerate("xyz"):
            pl._write_grid(d / f"{c}.tif", xyz[..., i])
        bad = pl.check(d)
        self.assertTrue(any("winding offset" in b for b in bad))
        self.assertTrue(any(b.startswith("truth wrong") for b in bad))
        code, out, _ = run_cli(["planted", "check", str(d)])
        self.assertEqual(code, pl.EXIT_DISAGREE)
        self.assertIn("DISAGREES", out)

    def test_control_a_plant_that_did_nothing_is_caught(self):
        with mock.patch.object(pl.Plant, "reproject", lambda self, mask: None):
            p = pl.plant(self.base, "switch")
        bad = pl.check(pl.write(p, self.d / "noop"))
        self.assertTrue(bad)

    def test_cli_make_families_and_check(self):
        code, out, _ = run_cli(["planted", "families", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(set(json.loads(out)), set(pl.FAMILIES))
        code, out, _ = run_cli(["planted", "make", str(self.d / "m"), "--family", "lens", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["truth"]["expected"], "INCORRECT")
        self.assertEqual(run_cli(["planted", "check", str(self.d / "m")])[0], 0)
        code, _, err = run_cli(["planted", "make", str(self.d / "m"), "--family", "lens"])
        self.assertEqual(code, 2)                                   # refuses to overwrite
        self.assertIn("not empty", err)
        code, out, _ = run_cli(["planted", "make", str(self.d / "p"), "--family", "switch", "--geometry", "planes"])
        self.assertEqual(code, 0)
        self.assertEqual(pl.load(self.d / "p")[0].sheets.kind, "planes")


@unittest.skipUnless(np is not None and HAVE_SCIPY, "numpy and scipy are needed for kit stackcheck")
class StackcheckOnPlants(unittest.TestCase):
    """kit stackcheck on a stack of six windings built by kit planted, each one turn of the spiral: the clean stack
    passes, a hole in w02 is its missing sector and nothing else, and a lens of w03 on w02's sheet, a switch of w02
    onto w03 and a merger of w02 onto w03 are each the coincident pair w02/w03 and nothing else."""

    CX = CY = 2000.0
    VOXEL_UM = 2.0

    @classmethod
    def setUpClass(cls):
        from kit import stackcheck as sc
        cls.sc = sc
        cls.sheets = pl.Sheets(pitch=50.0, w0=8.0, step=10.0, zstep=10.0, z0=0.0, centre=(cls.CX, cls.CY),
                               theta0=math.radians(17.3))
        cls.ncol = int(round(TWO_PI / cls.sheets.dtheta())) + 1          # one turn per segment
        cls.umb = sc.parse_umbilicus({"control_points": [{"x": cls.CX, "y": cls.CY, "z": float(z)}
                                                         for z in range(-100, 501, 50)],
                                      "metadata": {"voxelsize_um": cls.VOXEL_UM}})

    def flagged(self, index=None, family=None, **kw):
        segs = [pl.surface(self.sheets, (41, self.ncol), k0=k) for k in range(6)]
        if family:
            segs[index] = pl.plant(segs[index], family, **kw)
        objs = [self.sc.Segment(f"w{k:02d}", p.xyz, p.valid) for k, p in enumerate(segs)]
        rep, _ = self.sc.check_stack(objs, self.umb, self.VOXEL_UM, {"planes": 40})
        return rep["summary"], {k: v for k, v in rep["summary"]["flagged"].items() if v}

    def test_clean_stack_passes(self):
        summary, f = self.flagged()
        self.assertTrue(summary["clean"])
        self.assertEqual(f, {})

    def test_hole_is_a_missing_sector(self):
        self.assertEqual(self.flagged(2, "hole", rows=(10, 31), cols=(25, 60))[1], {"missing_sectors": ["w02"]})

    def test_sheet_switches_onto_a_neighbour_are_coincident_pairs(self):
        for index, family, kw in ((3, "lens", dict(rows=(10, 31), cols=(25, 60), dk=-1)), (2, "merger", {})):
            self.assertEqual(self.flagged(index, family, **kw)[1], {"coincident_pairs": ["w02/w03"]}, family)


if __name__ == "__main__":
    unittest.main()
