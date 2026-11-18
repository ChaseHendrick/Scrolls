import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import scipy  # noqa: F401  (pyflakes: needed only to skip)
    HAVE = True
except ImportError:
    HAVE = False
try:
    import zarr  # noqa: F401
    HAVE_ZARR = True
except ImportError:
    HAVE_ZARR = False

TINY = {"shape": [48, 160, 160], "pitch": 12.0, "thick": 5.0, "r0": 16.0, "warp": 3.0, "seed": 4,
        "squash": 0.7, "contact_share": 0.2, "noise": 6.0, "rings": 1.5, "noise_corr": 0.8, "edge": 0.3}


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class ScrollSim2GeometryTest(unittest.TestCase):
    def test_binary_search_finds_the_turn_a_full_scan_finds(self):
        # the binary-search lookup gives the largest turn k with R_k <= rho, as a scan over every turn does, so the
        # labels it builds on are the full-scan ones
        from kit import scrollsim2 as s2
        b = s2.Scroll2({"shape": [64, 208, 208], "fiber": 0.0, "seed": 5})
        zz, yy, xx = np.mgrid[10:13, 0:208, 0:208]
        out = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], 1).astype(float)
        rho, phi, z, j = b.locate_turn(b.rolled(out))
        ks = np.arange(b.max_k + 2)[:, None]
        Rk = b.R_at(phi[None] + 2 * np.pi * ks, np.broadcast_to(z, (len(ks), len(z))))
        full = np.where((Rk <= rho[None]).any(0), (Rk <= rho[None]).sum(0) - 1, -1)
        self.assertTrue((j == full).all())
        d, lab, th, near = b.voxels(out)
        self.assertGreater(len(np.unique(lab[lab >= 0])), 3)
        self.assertTrue(np.isfinite(near[lab >= 0]).all())
        self.assertLess(float(np.abs(np.where(lab >= 0, th - (phi + 2 * np.pi * lab), 0)).max()), 1e-9)

    def test_params_refuse(self):
        from kit import scrollsim2 as s2
        with self.assertRaises(s2.SimError):
            s2.params({"pitch": 5.0})                  # pitch must exceed thick
        with self.assertRaises(s2.SimError):
            s2.params({"nope": 1})
        with self.assertRaises(s2.SimError):
            s2.params({"supersample": 0})
        with self.assertRaises(s2.SimError):
            s2.params(preset="huge")
        with self.assertRaises(s2.SimError):
            s2.params({"squash": 0.1})                  # the geometry's own refusal
        with self.assertRaises(s2.SimError):
            s2.Scroll2({"shape": [32, 40, 208], "alpha": 0.0})     # too short in y for this crush

    def test_fixed_axis_box_is_narrow(self):
        from kit import scrollsim2 as s2
        sc = s2.Scroll2({"shape": [32, 128, 208], "alpha": 0.0, "squash": 0.5, "seed": 2})
        self.assertEqual((sc.Z, sc.Y, sc.X), (32, 128, 208))
        ct, labels, air = sc.scan_block(8, 24, 0, 128, 0, 208)
        self.assertFalse(air)
        ys = np.flatnonzero(labels.any((0, 2)))
        self.assertGreater(ys.min(), 0)                 # the crushed roll fits inside the narrow box
        self.assertLess(ys.max(), 127)

    def test_hashed_noise_depends_on_position_only(self):
        from kit import scrollsim2 as s2
        a = s2.hashed_normal(3, 0, 8, 0, 8, 0, 8)
        b = s2.hashed_normal(3, 4, 12, 2, 10, 1, 9)
        self.assertTrue(np.array_equal(a[4:, 2:, 1:], b[:4, :6, :7]))
        big = s2.hashed_normal(3, 0, 40, 0, 40, 0, 40)
        self.assertLess(abs(float(big.mean())), 0.02)
        self.assertLess(abs(float(big.std()) - 1.0), 0.02)
        self.assertFalse(np.array_equal(a, s2.hashed_normal(4, 0, 8, 0, 8, 0, 8)))

    def test_block_render_is_block_independent(self):
        # a voxel's value never depends on which block rendered it: noise is hashed by position and every block
        # is rendered with a halo that covers each filter
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(TINY))
        whole, lw, _ = sc.scan_block(8, 40, 20, 140, 20, 140)
        parts = np.zeros_like(whole)
        lp = np.zeros_like(lw)
        for z0 in (8, 24):
            for y0 in (20, 80):
                for x0 in (20, 80):
                    c, lab, _ = sc.scan_block(z0, z0 + 16, y0, y0 + 60, x0, x0 + 60)
                    parts[z0 - 8:z0 + 8, y0 - 20:y0 + 40, x0 - 20:x0 + 40] = c
                    lp[z0 - 8:z0 + 8, y0 - 20:y0 + 40, x0 - 20:x0 + 40] = lab
        self.assertTrue(np.array_equal(whole, parts))
        self.assertTrue(np.array_equal(lw, lp))

    def test_air_skip_changes_nothing(self):
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(TINY, rings=0.0))
        box = (0, 16, -400, -376, -400, -376)          # far outside the roll (blocks may lie beyond the box)
        self.assertTrue(sc.block_is_air(*box))
        a, la, air = sc.scan_block(*box)
        b, lb, air2 = sc.scan_block(*box, air=False)
        self.assertTrue(air and not air2)
        self.assertTrue(np.array_equal(a, b))
        self.assertFalse(lb.any())


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class ScrollSim2LibraryTest(unittest.TestCase):
    def test_library_from_ct_and_applied(self):
        from kit import scrollsim2 as s2
        donor = s2.Scroll2(dict(TINY, noise=4.0, seed=9))
        ct, _, _ = donor.scan_block(0, 48, 0, 160, 0, 160)
        lib = s2.build_library(ct, patch=8, count=200, seed=1)
        self.assertGreater(len(lib["sheet"]), 20)
        self.assertGreater(len(lib["gap"]), 20)
        self.assertGreater(lib["contrast"], 0)
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "lib.npz"
            np.savez_compressed(path, **lib)
            plain = s2.Scroll2(dict(TINY, noise=0.0, rings=0.0))
            tex = s2.Scroll2(dict(TINY, noise=0.0, rings=0.0, library=str(path)))
            a, _, _ = plain.scan_block(8, 40, 20, 140, 20, 140)
            b, _, _ = tex.scan_block(8, 40, 20, 140, 20, 140)
            self.assertGreater(float(np.abs(a.astype(int) - b).mean()), 0.1)
            # block independence holds with the library too
            c1, _, _ = tex.scan_block(8, 24, 20, 80, 20, 80)
            self.assertTrue(np.array_equal(b[:16, :60, :60], c1))
        with self.assertRaises(s2.SimError):
            s2.build_library(np.zeros((8, 8, 8)), patch=8)


@unittest.skipUnless(HAVE and HAVE_ZARR, "needs numpy, scipy and zarr")
class ScrollSim2MakeTest(unittest.TestCase):
    def test_make_writes_pyramid_and_is_deterministic(self):
        import zarr
        from kit import scrollsim2 as s2
        with tempfile.TemporaryDirectory() as t:
            a = Path(t) / "a"
            b = Path(t) / "b"
            doc = s2.make(a, dict(TINY), workers=2, block=32, levels=3, chunk=32, surfaces=True, progress=None)
            s2.make(b, dict(TINY), workers=1, block=64, levels=3, chunk=32, progress=None)
            ga, gb = zarr.open_group(str(a / "ct.zarr"), mode="r"), zarr.open_group(str(b / "ct.zarr"), mode="r")
            self.assertEqual(ga["0"].shape, (48, 160, 160))
            self.assertEqual(ga["3"].shape, (6, 20, 20))
            for lev in "0123":
                self.assertTrue(np.array_equal(ga[lev][:], gb[lev][:]), lev)
            la = zarr.open_group(str(a / "truth" / "labels.zarr"), mode="r")["0"][:]
            self.assertGreater(len(np.unique(la)), 3)
            self.assertEqual(len(ga.attrs["multiscales"][0]["datasets"]), 4)
            l1 = ga["1"][:].astype(float)
            self.assertLess(abs(l1.mean() - ga["0"][:].astype(float).mean()), 1.0)
            self.assertTrue((a / "truth" / "surfaces" / "spiral-center" / "winding.npy").exists())
            self.assertLess(doc["surface_residual_vox"], 1e-6)
            info = json.loads((a / "truth.json").read_text())
            self.assertEqual(info["tool"], "kit.scrollsim2")
            self.assertEqual(info["render"]["blocks"], 2 * 5 * 5)
            with self.assertRaises(s2.SimError):
                s2.make(a, dict(TINY), progress=None)                  # never overwrites
            with self.assertRaises(s2.SimError):
                s2.make(Path(t) / "c", dict(TINY), block=48, chunk=32, progress=None)

    def test_stop_and_resume_give_the_same_volume(self):
        import zarr
        from kit import scrollsim2 as s2
        with tempfile.TemporaryDirectory() as t:
            a, b = Path(t) / "a", Path(t) / "b"
            s2.make(a, dict(TINY), workers=1, block=32, levels=2, chunk=32, progress=None)
            d1 = s2.make(b, dict(TINY), workers=2, block=32, levels=2, chunk=32, progress=None, max_blocks=7,
                         order="middle")
            self.assertFalse(d1["complete"])
            self.assertEqual(d1["render"]["stopped"], "max_blocks")
            self.assertEqual(d1["render"]["blocks_done"], 7)
            self.assertEqual(len((b / "truth" / "done.txt").read_text().split()), 7)
            # a deadline already inside the reserve renders nothing more
            d2 = s2.make(b, dict(TINY), workers=1, block=32, levels=2, chunk=32, progress=None, resume=True,
                         environ={"KIT_JOB_DEADLINE": "1", "KIT_CKPT_RESERVE_S": "60"})
            self.assertEqual(d2["render"]["stopped"], "deadline")
            self.assertEqual(d2["render"]["blocks_done"], 7)
            d3 = s2.make(b, dict(TINY), workers=2, block=32, levels=2, chunk=32, progress=None, resume=True,
                         environ={})
            self.assertTrue(d3["complete"])
            self.assertEqual(d3["render"]["blocks_this_run"], 50 - 7)
            ga, gb = zarr.open_group(str(a / "ct.zarr"), mode="r"), zarr.open_group(str(b / "ct.zarr"), mode="r")
            for lev in "012":
                self.assertTrue(np.array_equal(ga[lev][:], gb[lev][:]), lev)
            done = [int(x) for x in (b / "truth" / "done.txt").read_text().split()][:7]
            self.assertNotIn(0, done)                                  # middle first: not the corner block
            with self.assertRaises(s2.SimError):
                s2.make(Path(t) / "d", dict(TINY), progress=None, order="spiral")
            with self.assertRaises(s2.SimError):                       # other parameters refuse to resume
                s2.make(b, dict(TINY, seed=99), block=32, levels=2, chunk=32, progress=None, resume=True)
            with self.assertRaises(s2.SimError):                       # not a scrollsim2 folder
                (Path(t) / "c").mkdir()
                (Path(t) / "c" / "x").write_text("x")
                s2.make(Path(t) / "c", dict(TINY), progress=None, resume=True)

    def test_verify_finds_lost_chunks_and_pyramid_repairs(self):
        import os
        import zarr
        from kit import scrollsim2 as s2
        with tempfile.TemporaryDirectory() as t:
            a = Path(t) / "a"
            doc = s2.make(a, dict(TINY), workers=1, block=32, levels=2, chunk=32, progress=None)
            self.assertTrue(doc["render"]["verified"]["ok"])
            ref = zarr.open_group(str(a / "ct.zarr"), mode="r")["2"][:]
            # a lost pyramid chunk, as a rename that never landed on a bucket mount leaves it
            os.rename(a / "ct.zarr" / "1" / "0.1.1", a / "ct.zarr" / "1" / "0.1.1.abc.partial")
            v = s2.verify(a)
            self.assertFalse(v["ok"])
            self.assertEqual(v["levels"]["1"]["missing"], 1)
            self.assertEqual(len(v["partial"]), 1)
            os.remove(a / "ct.zarr" / "1" / "0.1.1.abc.partial")
            r = s2.pyramid(a, workers=1)
            self.assertTrue(r["ok"])
            self.assertTrue(np.array_equal(zarr.open_group(str(a / "ct.zarr"), mode="r")["2"][:], ref))
            self.assertEqual(s2.main(["verify", str(a)]), 0)

    def test_write_checked_refuses_a_chunk_that_never_lands(self):
        from unittest import mock
        import zarr
        from kit import scrollsim2 as s2
        with tempfile.TemporaryDirectory() as t:
            g = zarr.open_group(str(Path(t) / "z"), mode="w", zarr_format=2)
            arr = g.create_array("0", shape=(32, 32, 32), chunks=(16, 16, 16), dtype="uint8", fill_value=0)
            s2._write_checked(Path(t) / "z" / "0", arr, (0, 16, 0, 16, 0, 16), np.ones((16, 16, 16), np.uint8))
            with mock.patch.object(s2, "_landed", return_value=["0.0.0"]):
                with self.assertRaises(s2.SimError):
                    s2._write_checked(Path(t) / "z" / "0", arr, (0, 16, 0, 16, 0, 16), np.ones((16, 16, 16), np.uint8))

    def test_publish_copies_plainly_and_clears_partials(self):
        import zarr
        from kit import scrollsim2 as s2
        with tempfile.TemporaryDirectory() as t:
            a, d = Path(t) / "a", Path(t) / "dst"
            s2.make(a, dict(TINY), workers=1, block=32, levels=2, chunk=32, progress=None)
            r = s2.publish(a, d)
            self.assertTrue(r["ok"])
            for lev in "012":
                self.assertTrue(np.array_equal(zarr.open_group(str(a / "ct.zarr"), mode="r")[lev][:],
                                               zarr.open_group(str(d / "ct.zarr"), mode="r")[lev][:]))
            la = zarr.open_group(str(a / "truth" / "labels.zarr"), mode="r")["0"][:]
            self.assertTrue(np.array_equal(la, zarr.open_group(str(d / "truth" / "labels.zarr"), mode="r")["0"][:]))
            # a repair: a lost level-1 chunk and its leftover .partial in DST, then only levels 1 and 2 published
            (d / "ct.zarr" / "1" / "0.1.1").rename(d / "ct.zarr" / "1" / "0.1.1.x.partial")
            self.assertFalse(s2.verify(d)["ok"])
            r = s2.publish(a, d, levels=[1, 2], labels=False)
            self.assertTrue(r["ok"])
            self.assertEqual(r["partial"], [])
            with self.assertRaises(s2.SimError):
                s2.publish(Path(t) / "nope", d)

    def test_estimate_reports(self):
        from kit import scrollsim2 as s2
        e = s2.estimate(dict(TINY), workers=2, block=32, sample=1, progress=None)
        self.assertEqual(e["blocks"], 2 * 5 * 5)
        self.assertGreater(e["sheet_blocks"], 0)
        self.assertGreater(e["seconds_per_sheet_block"], 0)


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class ScrollSim2StatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kit import scrollsim2 as s2
        cls.s2 = s2
        cls.crops = []
        for seed, noise in ((11, 4.0), (12, 4.0), (13, 12.0)):
            sc = s2.Scroll2(dict(TINY, seed=seed, noise=noise))
            ct, _, _ = sc.scan_block(0, 48, 20, 140, 20, 140)
            cls.crops.append(ct)

    def test_stats_are_finite_and_label_free(self):
        d = self.s2.ctstats(self.crops[0], 8.64)
        self.assertEqual(len(d["sheet_runs"]), self.s2.QN)
        self.assertGreater(d["runs"][0], 20)
        for k in self.s2.STATS_SCALAR:
            self.assertIsNotNone(d[k], k)
        self.assertTrue(0 <= d["touching_share"] <= 1)
        self.assertAlmostEqual(np.percentile(np.asarray(d["sheet_gray"]), 50), 1.0, delta=0.05)

    def test_distance_zero_to_itself_and_grows_with_noise(self):
        a, b, c = (self.s2.ctstats(x, 8.64) for x in self.crops)
        self.assertTrue(all(v == 0 for v in self.s2.stats_distance(a, a).values()))
        self.assertGreater(self.s2.stats_distance(a, c)["gap_noise"], self.s2.stats_distance(a, b)["gap_noise"])

    def test_compare_spread_and_inside(self):
        st = [dict(self.s2.ctstats(x, 8.64), scan=f"s{i}") for i, x in enumerate(self.crops)]
        r = self.s2.stats_compare(st[:2], st[2])
        self.assertEqual(r["scan_pairs"], 1)
        self.assertFalse(r["sim"]["gap_noise"]["inside"])      # three times the noise lies outside a 4-to-4 spread
        same = self.s2.stats_compare([st[0], dict(st[1], scan="s0")])
        self.assertEqual(same["scan_pairs"], 0)                  # crops of one scan give no spread

    def test_resample_and_refusals(self):
        v = self.s2.resample(self.crops[0], 4.32, 8.64)
        self.assertEqual(v.shape, (24, 60, 60))
        with self.assertRaises(self.s2.SimError):
            self.s2.ctstats(v[:4], 8.64)
        with self.assertRaises(self.s2.SimError):
            self.s2.ctstats(self.crops[0], 2.0)                  # shrinks below twice the tile


class ScrollSim2WorkersTest(unittest.TestCase):
    def test_worker_cap_and_blas_threads(self):
        from unittest import mock
        from kit import scrollsim2 as s2
        with mock.patch("os.cpu_count", return_value=32):
            self.assertEqual(s2.default_workers(), 16)
        with mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(s2.default_workers(), 4)
        env = {"OMP_NUM_THREADS": "8"}
        s2.single_thread_blas(env)
        self.assertEqual(env, {"OMP_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})


if __name__ == "__main__":
    unittest.main()
