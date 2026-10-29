import json
import os
import tempfile
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

if np is not None:
    from kit.seamswitch import demo_sheet, local_switches, main, pool, seam_switches, sheet_switches


def sheet(j, k, angle=None, z=None):
    j = np.asarray(j)
    h, w = j.shape
    if angle is None:
        angle = np.tile(np.linspace(0, 359, w), (h, 1))
    if z is None:
        z = np.tile(np.arange(h)[:, None] * 10.0, (1, w))
    return {"j": j, "k": np.full(j.shape, k) if np.isscalar(k) else np.asarray(k),
            "valid": np.ones(j.shape, bool), "angle": angle, "z": z}


@unittest.skipIf(np is None, "numpy missing")
class SeamSwitchTests(unittest.TestCase):
    def test_a_constant_offset_has_no_switch(self):
        r = seam_switches([sheet(np.full((4, 36), 7), 3), sheet(np.full((4, 36), 8), 4)])
        self.assertEqual(r["switches_per_1000"], 0.0)
        self.assertEqual(r["wrong_area"], 0.0)
        self.assertEqual(r["pairs"], 2 * (4 * 35 + 3 * 36))

    def test_the_fits_own_seam_is_not_a_switch_but_counts_globally(self):
        j = np.full((4, 36), 7)
        j[:, 18:] = 8                      # the fit's seam at 180 degrees: d steps by one there, on a cell boundary
        r = seam_switches([sheet(j, 3)])
        self.assertEqual(r["switches_per_1000"], 0.0)
        self.assertGreater(r["switches_per_1000_global"], 0.0)

    def test_an_island_on_the_wrong_winding_is_counted(self):
        j = np.full((20, 72), 7)
        j[8:10, 30:32] = 8                 # a 2 x 2 island inside one cell
        r = seam_switches([sheet(j, 3, z=np.zeros((20, 72)))])
        self.assertEqual(r["vertices"], 20 * 72)
        self.assertAlmostEqual(r["wrong_area"], 4 / (20 * 72))
        n = 20 * 71 + 19 * 72
        self.assertAlmostEqual(r["switches_per_1000"], 1000 * 8 / n)

    def test_reversed_label_order_picks_the_negative_sign(self):
        r = seam_switches([sheet(np.full((3, 36), 10 - k), k) for k in range(5)])
        self.assertEqual(r["sign"], -1)
        self.assertEqual(r["wrong_area"], 0.0)

    def test_invalid_vertices_and_pairs_are_left_out(self):
        s = sheet(np.full((2, 3), 5), 1)
        s["valid"][0, 1] = False
        r = seam_switches([s])
        self.assertEqual(r["vertices"], 5)
        self.assertEqual(r["pairs"], 2 + 2)   # row pairs (1,0)-(1,1), (1,1)-(1,2); columns 0 and 2

    def test_nothing_valid(self):
        s = sheet(np.zeros((2, 2), int), 0)
        s["valid"][:] = False
        self.assertEqual(seam_switches([s])["vertices"], 0)


@unittest.skipIf(np is None, "numpy missing")
class LocalSwitchTests(unittest.TestCase):
    def spiral_sheet(self, k, h=5, w=90):
        theta = np.tile(np.linspace(-np.pi, 3 * np.pi, w), (h, 1))      # two turns, crossing the fit's seam twice
        rho = k + theta / (2 * np.pi)                                    # w = rho - theta / 2 pi = k everywhere
        return rho, np.mod(theta + np.pi, 2 * np.pi) - np.pi             # theta as atan2 gives it, with the seam

    def test_a_sheet_on_one_winding_has_no_switch_even_across_the_seam(self):
        rho, th = self.spiral_sheet(4)
        r = local_switches(rho, th, np.ones(rho.shape, bool))
        self.assertEqual(r["switches"], 0)
        self.assertEqual(r["pairs"], 5 * 89 + 4 * 90)

    def test_a_patch_moved_one_winding_out_is_counted_on_its_border(self):
        rho, th = self.spiral_sheet(4)
        rho[1:3, 40:45] += 1.0
        r = local_switches(rho, th, np.ones(rho.shape, bool))
        self.assertEqual(r["switches"], 2 * 2 + 2 * 5)                  # left and right edges, top and bottom edges

    def test_invalid_and_non_finite_vertices_are_left_out(self):
        rho, th = self.spiral_sheet(4, h=2, w=3)
        valid = np.ones(rho.shape, bool)
        rho[0, 1] = np.nan
        r = local_switches(rho, th, valid)
        self.assertEqual(r["pairs"], 4)


@unittest.skipIf(np is None, "numpy missing")
class SheetSwitchTests(unittest.TestCase):
    def sheet(self, h=30, w=400, turns=4.0, k=6.3):
        theta = np.tile(np.linspace(0, 2 * np.pi * turns, w), (h, 1))
        rho = k + theta / (2 * np.pi)                                    # one sheet winding four turns
        z = np.tile(np.arange(h)[:, None] * 20.0, (1, w))
        return rho, np.mod(theta + np.pi, 2 * np.pi) - np.pi, z, np.ones((h, w), bool)

    def test_a_sheet_kept_on_one_winding_has_no_switch(self):
        r = sheet_switches(*self.sheet())
        self.assertEqual(r["trees"], 1)
        self.assertEqual(r["switches_per_1000"], 0.0)
        self.assertEqual(r["wrong_area_global"], 0.0)
        self.assertEqual(r["jumps_per_1000"], 0.0)

    def test_slow_drift_across_half_a_winding_is_counted_where_jumps_are_not(self):
        rho, th, z, v = self.sheet()
        rho = rho + np.linspace(0, 1.6, rho.shape[1])[None, :]          # the fit drifts 1.6 windings along the sheet
        r = sheet_switches(rho, th, z, v, bin_deg=360.0, bin_z=1e9)    # one cell: offset is the mode
        self.assertEqual(r["jumps_per_1000"], 0.0)
        self.assertGreater(r["switches_per_1000_global"], 0.0)
        self.assertAlmostEqual(r["wrong_area_global"], 0.375, delta=0.01)

    def test_an_island_one_winding_out_is_counted_on_its_border(self):
        rho, th, z, v = self.sheet()
        rho[10:14, 100:110] += 1.0
        r = sheet_switches(rho, th, z, v)
        n = 30 * 399 + 29 * 400
        self.assertAlmostEqual(r["switches_per_1000_global"], 1000 * (2 * 4 + 2 * 10) / n)
        self.assertAlmostEqual(r["wrong_area_global"], 40 / (30 * 400))
        self.assertAlmostEqual(r["jumps_per_1000"], r["switches_per_1000_global"])

    def test_small_trees_are_left_out(self):
        rho, th, z, v = self.sheet(h=5, w=40)
        v[:, 20] = False                                                # trees of 100 and 95 vertices
        v[0, 0:20] = False                                              # the left one now 80
        r = sheet_switches(rho, th, z, v, min_tree=90)
        self.assertEqual(r["trees"], 1)
        self.assertEqual(r["vertices"], 95)

    def test_pool_adds_counts_and_recomputes_rates(self):
        rho, th, z, v = self.sheet()
        rho2 = rho.copy()
        rho2[10:14, 100:110] += 1.0
        a, b = sheet_switches(rho, th, z, v), sheet_switches(rho2, th, z, v)
        p = pool([a, b, {"vertices": 0, "pairs": 0, "trees": 0}])
        self.assertEqual(p["pairs"], a["pairs"] + b["pairs"])
        self.assertEqual(p["switches_global"], 28)
        self.assertAlmostEqual(p["switches_per_1000_global"], 1000 * 28 / (2 * a["pairs"]))


@unittest.skipIf(np is None, "numpy missing")
class CommandLineTest(unittest.TestCase):
    """The headless entry point: demo, sheet and labeled grids from .npz files, exit codes 0, 1 and 2."""

    def run_main(self, argv):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_demo_counts_the_planted_patch_border_and_nothing_on_the_clean_sheet(self):
        code, out, _ = self.run_main(["demo", "--json"])
        r = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["clean"]["switches"], 0)
        self.assertEqual(r["planted"]["switches"], r["planted_cut_pairs"])
        self.assertEqual(r["planted_cut_pairs"], 2 * 20 + 2 * 40)

    def test_sheet_grids_are_scored_and_pooled(self):
        with tempfile.TemporaryDirectory() as d:
            clean, _ = demo_sheet()
            bad, cut = demo_sheet(patch=(20, 40, 100, 140))
            a, b = os.path.join(d, "a.npz"), os.path.join(d, "b.npz")
            np.savez(a, **clean)
            np.savez(b, **bad)
            code, out, _ = self.run_main(["sheet", a, b, "--json"])
        r = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(r["grids"][a]["switches"], 0)
        self.assertEqual(r["pooled"]["switches"], cut)
        self.assertEqual(r["pooled"]["pairs"], 2 * r["grids"][a]["pairs"])

    def test_labeled_grids_match_the_library(self):
        j = np.full((20, 72), 7)
        j[8:10, 30:32] = 8
        g = {"j": j, "k": np.full(j.shape, 3), "valid": np.ones(j.shape, bool),
             "angle": np.tile(np.linspace(0, 359, 72), (20, 1)), "z": np.zeros(j.shape)}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.npz")
            np.savez(p, **g)
            code, out, _ = self.run_main(["labeled", p, "--json"])
        r = json.loads(out)
        self.assertEqual(code, 0)
        self.assertAlmostEqual(r["switches_per_1000"], seam_switches([g])["switches_per_1000"])

    def test_missing_array_and_unreadable_file_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.npz")
            np.savez(p, rho=np.zeros((3, 3)), theta=np.zeros((3, 3)))
            code, _, err = self.run_main(["sheet", p])
            self.assertEqual(code, 2)
            self.assertIn("no array z, valid", err)
            q = os.path.join(d, "not.npz")
            with open(q, "w") as f:
                f.write("text")
            code, _, err = self.run_main(["sheet", q])
            self.assertEqual(code, 2)
            self.assertIn("not a readable .npz", err)
            np.savez(p, rho=np.zeros((3, 3)), theta=np.zeros((3, 4)), z=np.zeros((3, 3)), valid=np.ones((3, 3)))
            code, _, err = self.run_main(["sheet", p])
            self.assertEqual(code, 2)
            self.assertIn("same shape", err)

    def test_a_grid_with_nothing_valid_is_not_ok(self):
        g = {"j": np.zeros((4, 4)), "k": np.zeros((4, 4)), "valid": np.zeros((4, 4), bool),
             "angle": np.zeros((4, 4)), "z": np.zeros((4, 4))}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.npz")
            np.savez(p, **g)
            code, _, _ = self.run_main(["labeled", p])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
