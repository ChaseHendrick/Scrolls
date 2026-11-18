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
    def test_turn_search_matches_all_turns(self):
        # the binary-search turn lookup gives the reference all-turns lookup's labels, density and angles exactly
        from kit import scrollsim2 as s2
        b = s2.Scroll2({"shape": [64, 208, 208], "seed": 5})
        zz, yy, xx = np.mgrid[10:13, 0:208, 0:208]
        out = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], 1).astype(float)
        d1, l1, t1 = b.voxels_all_turns(out)
        d2, l2, t2, ink, near = b.voxels(out)
        self.assertTrue((l1 == l2).all())
        self.assertGreater(int((l2 >= 0).sum()), 1000)
        self.assertLess(float(np.abs(d1 - d2).max()), 1e-9)
        self.assertLess(float(np.abs(np.where(l1 >= 0, t1 - t2, 0)).max()), 1e-9)
        self.assertFalse(ink.any())                     # ink is off by default
        self.assertTrue(np.isfinite(near[l2 >= 0]).all())

    def test_same_parameters_same_scroll(self):
        from kit import scrollsim2 as s2
        a = s2.Scroll2(dict(TINY)).scan_block(8, 24, 20, 80, 20, 80)
        b = s2.Scroll2(dict(TINY)).scan_block(8, 24, 20, 80, 20, 80)
        c = s2.Scroll2(dict(TINY, seed=5)).scan_block(8, 24, 20, 80, 20, 80)
        self.assertTrue(np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]))
        self.assertFalse(np.array_equal(a[0], c[0]))

    def test_params_refuse(self):
        from kit import scrollsim2 as s2
        with self.assertRaises(s2.SimError):
            s2.params({"nope": 1})
        with self.assertRaises(s2.SimError):
            s2.params({"supersample": 0})
        with self.assertRaises(s2.SimError):
            s2.params(preset="huge")
        with self.assertRaises(s2.SimError):
            s2.params({"squash": 0.1})
        with self.assertRaises(s2.SimError):
            s2.params({"thick": 20.0})                  # pitch must exceed thick
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


# every scan-model feature on at once, at sizes a unit test renders quickly
SCAN = dict(TINY, noise=0.0, phase_mm=220.0, db_object=2000.0, nps=[1.0, 2.0, 1.5, 1.0, 0.5, 0.3, 0.2],
            cupping=0.3, slab_z=16, slab_gain=0.05, axis_yx=[70.0, 90.0])


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class ScrollSim2ScanModelTest(unittest.TestCase):
    def test_scan_presets_and_refusals(self):
        from kit import scrollsim2 as s2
        p = s2.params({"scan": "synchrotron"})
        self.assertEqual(p["scan"], "synchrotron")
        self.assertEqual(p["phase_mm"], 220.0)
        self.assertEqual(s2.params({"scan": "synchrotron", "phase_mm": 100.0})["phase_mm"], 100.0)   # --set wins
        self.assertEqual(s2.params(p), p)                                                          # idempotent
        self.assertEqual(s2.params(preset="smoke")["phase_mm"], 0.0)                               # off by default
        off = s2.params()
        self.assertTrue(off["nps"] == [] and off["cupping"] == 0 and off["slab_z"] == 0 and off["phase_mm"] == 0)
        for bad in ({"scan": "medical"}, {"nps": [1.0, 2.0]}, {"nps": [-1.0] * 7}, {"cupping": 1.0},
                    {"voxel_um": 0}, {"axis_yx": [1.0]}, {"phase_halo": 1}, {"slab_gain": -0.1}):
            with self.assertRaises(s2.SimError, msg=str(bad)):
                s2.params(bad)

    def test_scan_model_is_block_independent(self):
        # phase, noise bands, cupping, slabs (a slab edge at z 16 inside the box) and rings about an off-center
        # axis: any block split gives the same volume, bit for bit
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(SCAN))
        whole, lw, _ = sc.scan_block(8, 40, 20, 140, 20, 140)
        parts = np.zeros_like(whole)
        for z0 in (8, 24):
            for y0 in (20, 80):
                for x0 in (20, 80):
                    c, _, _ = s2.Scroll2(dict(SCAN)).scan_block(z0, z0 + 16, y0, y0 + 60, x0, x0 + 60)
                    parts[z0 - 8:z0 + 8, y0 - 20:y0 + 40, x0 - 20:x0 + 40] = c
        self.assertTrue(np.array_equal(whole, parts))
        plain, _, _ = s2.Scroll2(dict(TINY, noise=0.0)).scan_block(8, 40, 20, 140, 20, 140)
        self.assertFalse(np.array_equal(whole, plain))

    def test_phase_filter_matches_the_exact_transfer(self):
        # the Gaussian sum against the exact (1 + a_o k^2) / (1 + a_r k^2) applied by FFT on a periodic field
        from kit import scrollsim2 as s2
        rng = np.random.default_rng(1)
        n = 96
        v = ndi_smooth(rng.standard_normal((n, n, n)), 1.0) * 40 + 100
        for over in ({"phase_mm": 220.0, "db_object": 2000.0}, {"phase_mm": 220.0, "db_object": 500.0},
                     {"phase_mm": 220.0, "db_object": 1500.0, "voxel_um": 6.0, "phase_halo": 32}):
            ph = s2.phase_model(s2.params(over))
            self.assertLessEqual(ph["max_error"], s2.PHASE_TOL)
            k = 2 * np.pi * np.fft.fftfreq(n)
            k2 = k[:, None, None] ** 2 + k[None, :, None] ** 2 + k[None, None, :] ** 2
            exact = np.real(np.fft.ifftn(np.fft.fftn(v) * (1 + ph["a_object_vox2"] * k2)
                                         / (1 + ph["a_recon_vox2"] * k2)))
            got = s2.apply_phase(v, ph)
            h = ph["halo"]
            core = (slice(h, n - h),) * 3
            self.assertLess(float(np.abs(got[core] - exact[core]).max()), 0.03 * float(v.std()) + 0.05, over)
        self.assertIsNone(s2.phase_model(s2.params()))

    def test_phase_edges_follow_the_retrieval_mismatch(self):
        # a bright slab: an under-corrected retrieval (db_object above db_recon) and raw phase contrast overshoot
        # at the edge, an over-corrected one smooths it; every version keeps the slab's mean
        from kit import scrollsim2 as s2
        v = np.full((24, 24, 64), 60.0, np.float32)
        v[:, :, 26:38] = 150.0
        peaks = {}
        for name, over in (("under", {"db_object": 2000.0}), ("over", {"db_object": 500.0}),
                           ("raw", {"db_recon": 0.0})):
            out = s2.apply_phase(v, s2.phase_model(s2.params(dict(over, phase_mm=220.0))))
            line = out[12, 12]
            peaks[name] = float(line.max())
            self.assertAlmostEqual(float(line.mean()), float(v[12, 12].mean()), delta=0.5)
        self.assertGreater(peaks["under"], 152.0)
        self.assertGreater(peaks["raw"], 152.0)
        self.assertLess(peaks["over"], 150.0)

    def test_noise_spectrum_measured_and_fitted_back(self):
        # pure noise from known bands (an air box), measured label-free and fitted: the fit recovers the variance
        # and the spectrum's shape; a ramp-like set has more power at high frequency than at low
        from kit import scrollsim2 as s2
        sds = s2.SCANS["synchrotron"]["nps"]
        self.assertEqual(sds, s2.ramp_nps(3.5, 0.5))
        sc = s2.Scroll2(dict(TINY, noise=0.0, rings=0.0, bias=0.0, nps=sds))   # no slow drift: noise only
        box = (0, 96, -500, -404, -500, -404)
        self.assertTrue(sc.block_is_air(*box))
        ct = sc.scan_block(*box)[0].astype(float)
        m = s2.measure_nps(ct, tile=32, share=1.0)
        fit = s2.fit_nps(m["freq"], m["psd"], m["count"], 32)
        want = sum(x * x for x in sds) + 1 / 12.0                     # plus rounding to 8 bits
        self.assertAlmostEqual(m["variance"], want, delta=0.12 * want)
        self.assertAlmostEqual(fit["variance_fit"], m["variance"], delta=0.08 * want)
        self.assertLess(fit["relative_error"], 0.15)
        psd = np.array(m["psd"])
        fr = np.array(m["freq"])
        self.assertGreater(psd[(fr > 0.2) & (fr < 0.35)].mean(), psd[(fr > 0) & (fr < 0.06)].mean())
        white = s2.Scroll2(dict(TINY, noise=4.0, noise_corr=0.0, rings=0.0, bias=0.0)).scan_block(*box)[0].astype(float)
        fw = s2.fit_nps(**{k: v for k, v in s2.measure_nps(white, 32, 1.0).items() if k in ("freq", "psd", "count")})
        self.assertAlmostEqual(fw["variance_fit"], 16.0 + 1 / 12.0, delta=1.6)   # white noise, sd 4, fits too
        self.assertLess(fw["relative_error"], 0.15)
        with self.assertRaises(s2.SimError):
            s2.measure_nps(ct[:16])
        cut = s2.phase_model(s2.params({"phase_mm": 220.0, "voxel_um": 2.4}))     # a halo too small says so
        self.assertGreater(cut["max_error"], s2.PHASE_TOL)

    def test_cupping_darkens_the_middle_of_the_roll(self):
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(TINY, noise=0.0, rings=0.0, bias=0.0, cupping=0.4))
        cup = sc._cup_field()
        self.assertAlmostEqual(float(cup.max()), 1.0, places=6)
        ny, nx = cup.shape[1:]
        self.assertGreater(float(cup[:, ny // 2, nx // 2].mean()), float(cup[:, ny // 2, 1].mean()) + 0.3)
        a, lab, _ = sc.scan_block(16, 32, 0, 160, 0, 160)
        b, _, _ = s2.Scroll2(dict(TINY, noise=0.0, rings=0.0, bias=0.0)).scan_block(16, 32, 0, 160, 0, 160)
        sheet = lab > 0
        yy, xx = np.mgrid[0:160, 0:160]
        mid = np.broadcast_to(np.hypot(yy - 80, xx - 80) < 30, a.shape) & sheet
        rim = np.broadcast_to(np.hypot(yy - 80, xx - 80) > 50, a.shape) & sheet
        lost = lambda m: float(b[m].astype(float).mean() - a[m].astype(float).mean())   # noqa: E731
        self.assertGreater(lost(mid), lost(rim) + 1.0)
        self.assertTrue(np.array_equal(a[~sheet & (b == 60)], b[~sheet & (b == 60)]))     # air keeps its value

    def test_slabs_step_the_gain_and_change_the_rings(self):
        from kit import scrollsim2 as s2
        base = dict(TINY, noise=0.0, rings=0.0, bias=0.0)
        flat = s2.Scroll2(dict(base)).scan_block(0, 48, 0, 160, 0, 160)[0].astype(float)
        st = s2.Scroll2(dict(base, slab_z=16, slab_gain=0.1)).scan_block(0, 48, 0, 160, 0, 160)[0].astype(float)
        g = [st[z0:z0 + 16].mean() / flat[z0:z0 + 16].mean() for z0 in (0, 16, 32)]
        self.assertGreater(max(g) - min(g), 0.02)
        sc = s2.Scroll2(dict(base, rings=2.0, slab_z=16))
        _, _, rings = sc._slabs()
        self.assertEqual(rings.shape[0], 3)
        one = s2.Scroll2(dict(base, rings=2.0))
        _, _, r1 = one._slabs()
        self.assertTrue(np.array_equal(r1[0], one._rings0))           # one slab: the release-1 rings
        self.assertTrue(np.array_equal(rings[0][:len(one._rings0)], one._rings0))
        self.assertFalse(np.array_equal(rings[0], rings[1][:len(rings[0])]))


def ndi_smooth(a, s):
    from scipy import ndimage
    return ndimage.gaussian_filter(a, s, mode="wrap")


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
            scales = [d["coordinateTransformations"][0]["scale"] for d in ga.attrs["multiscales"][0]["datasets"]]
            self.assertEqual(scales[0], [8.0] * 3)                     # micrometers: voxel_um at level 0
            self.assertEqual(scales[3], [64.0] * 3)
            l1 = ga["1"][:].astype(float)
            self.assertLess(abs(l1.mean() - ga["0"][:].astype(float).mean()), 1.0)
            sd = a / "truth" / "surfaces" / "spiral-center"
            for f in ("x.tif", "y.tif", "z.tif", "meta.json", "winding.npy"):
                self.assertTrue((sd / f).exists(), f)
            self.assertEqual(json.loads((sd / "meta.json").read_text())["format"], "tifxyz")
            self.assertLess(doc["surface_residual_vox"], 1e-6)
            info = json.loads((a / "truth.json").read_text())
            self.assertEqual(info["tool"], "kit.scrollsim2")
            self.assertEqual(info["render"]["blocks"], 2 * 5 * 5)
            self.assertEqual(info["scan_model"]["version"], 2)
            self.assertIsNone(info["scan_model"]["phase"])
            with self.assertRaises(s2.SimError):
                s2.make(a, dict(TINY), progress=None)                  # never overwrites
            with self.assertRaises(s2.SimError):
                s2.make(Path(t) / "c", dict(TINY), block=48, chunk=32, progress=None)

    def test_make_with_the_scan_model_and_the_nps_command(self):
        import contextlib
        import io
        import zarr
        from kit import scrollsim2 as s2
        with tempfile.TemporaryDirectory() as t:
            a = Path(t) / "a"
            doc = s2.make(a, dict(SCAN, voxel_um=4.0), workers=2, block=32, levels=1, chunk=32, progress=None)
            g = zarr.open_group(str(a / "ct.zarr"), mode="r")
            ds = g.attrs["multiscales"][0]["datasets"]
            self.assertEqual([d["coordinateTransformations"][0]["scale"][0] for d in ds], [4.0, 8.0])
            sm = json.loads((a / "truth.json").read_text())["scan_model"]
            self.assertEqual(sm, json.loads(json.dumps(doc["scan_model"])))
            self.assertAlmostEqual(sm["phase"]["ratio"], 2.0)
            self.assertEqual(sm["voxel_um"], 4.0)
            ct = Path(t) / "ct.npy"
            np.save(ct, g["0"][:])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(s2.main(["nps", str(ct), "--tile", "16", "--out", str(Path(t) / "nps.json")]), 0)
            got = json.loads(buf.getvalue())
            self.assertTrue(got["set"].startswith("nps=["))
            self.assertEqual(len(got["fit"]["nps"]), len(s2.NPS_SIGMAS))
            s2.params({"nps": got["fit"]["nps"]})                     # the printed value is a valid --set

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
            # a deadline already inside the spare renders nothing more
            d2 = s2.make(b, dict(TINY), workers=1, block=32, levels=2, chunk=32, progress=None, resume=True,
                         environ={"KIT_JOB_DEADLINE": "1", "KIT_JOB_SPARE_S": "60"})
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

    def test_vc3d_export_round_trips(self):
        # the exported folder is a VC3D project: villafmt's checks of VC3D's loaders pass, each volume's meta.json has
        # the fields VC3D's Volume requires and reads back the same voxels, and each surface keeps its winding numbers
        import uuid
        import zarr
        from kit import scrollsim2 as s2, villafmt
        with tempfile.TemporaryDirectory() as t:
            sim, out = Path(t) / "sim", Path(t) / "vc3d"
            s2.make(sim, dict(TINY), workers=1, block=32, levels=1, chunk=32, surfaces=True, progress=None)
            rep = s2.export_vc3d(sim, out)
            proj = Path(rep["project"])
            self.assertEqual(proj.name, "scrollsim2.volpkg.json")
            check = villafmt.check_project(json.loads(proj.read_text()), proj.parent, pixels=True)
            self.assertTrue(check["ok"], check["errors"])
            self.assertEqual([r["found"] for r in check["segments"]], [2])
            for v, src in zip(rep["volumes"], (sim / "ct.zarr", sim / "truth" / "labels.zarr")):
                d = Path(v["location"])
                meta = json.loads((d / "meta.json").read_text())
                self.assertEqual(meta["type"], "vol")
                self.assertEqual((meta["slices"], meta["height"], meta["width"]), (48, 160, 160))
                self.assertEqual(meta["uuid"], d.name)
                self.assertGreater(meta["voxelsize"], 0)
                g, ref = zarr.open_group(str(d), mode="r"), zarr.open_group(str(src), mode="r")
                self.assertEqual(sorted(g.array_keys()), sorted(ref.array_keys()))
                self.assertTrue(np.array_equal(g["0"][:], ref["0"][:]))
                self.assertEqual(len(g.attrs["multiscales"][0]["datasets"]), len(list(ref.array_keys())))
            for srf in rep["surfaces"]:
                d = Path(srf["location"])
                self.assertEqual(str(uuid.UUID(srf["uuid"])), srf["uuid"])
                self.assertEqual(json.loads((d / "meta.json").read_text())["uuid"], srf["uuid"])
                w0 = np.load(sim / "truth" / "surfaces" / d.name / "winding.npy")
                self.assertTrue(np.array_equal(np.load(d / "winding.npy"), w0, equal_nan=True))
            # copies instead of links give the same project
            rep2 = s2.export_vc3d(sim, Path(t) / "copy", copy=True)
            self.assertFalse(rep2["linked"])
            self.assertFalse(any(p.is_symlink() for p in (Path(t) / "copy").rglob("*")))
            with self.assertRaises(s2.SimError):
                s2.export_vc3d(sim, out)                       # never into a non-empty folder
            with self.assertRaises(s2.SimError):
                s2.export_vc3d(sim, Path(t) / "bad", voxel_um=0)

    def test_estimate_reports(self):
        from kit import scrollsim2 as s2
        e = s2.estimate(dict(TINY), workers=2, block=32, sample=1, progress=None)
        self.assertEqual(e["blocks"], 2 * 5 * 5)
        self.assertGreater(e["sheet_blocks"], 0)
        self.assertGreater(e["seconds_per_sheet_block"], 0)


# the ink writer at sizes a unit test renders quickly: 8 um deposit and 8 um absorbed at 8 um voxels (one voxel
# each), small letters so a 48-voxel-tall box holds two lines
INK = {"ink_um": 8.0, "ink_depth_um": 8.0, "ink_rho": 0.3, "ink_tex": 0.5, "ink_letter": 14.0, "ink_line": 20.0,
       "ink_col": 200.0, "ink_gap": 40.0, "ink_margin": 4.0}


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class ScrollSim2InkTest(unittest.TestCase):
    def test_ink_is_off_by_default_and_refuses_bad_values(self):
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(TINY))
        self.assertFalse(sc.ink_on)
        self.assertEqual(sc.ink_report(), {"on": False})
        self.assertTrue(s2.Scroll2(dict(TINY, ink_um=4.0)).ink_on)
        for bad in ({"ink_um": -1.0}, {"ink_rho": -1.0}, {"ink_tex": 1.5}, {"ink_off": 2}, {"ink_line": 10.0},
                    {"ink_glyphs": "cursive"}, {"ink_space": 1.0}, {"ink_col": 5.0}):
            with self.assertRaises(s2.SimError, msg=str(bad)):
                s2.params(dict(INK, **bad))
        a, src = s2.ink_glyphs("strokes")
        self.assertEqual(src, "strokes")
        self.assertEqual(a.shape, (24, s2.INK_PX, round(0.8 * s2.INK_PX)))
        self.assertTrue(0.05 < a.mean() < 0.6 and a.max() == 1.0)
        # partial volume: the share of a slab conserves its thickness over every voxel position and is at most 1
        d = np.linspace(-6, 6, 24001)
        for a_, b_ in ((1.0, 0.0), (1.2, 0.7), (0.3, 1.9)):
            sh = s2.ink_share(np, d, -0.4, 0.1, a_, b_)
            self.assertAlmostEqual(float(sh.sum() * (d[1] - d[0])), 0.5, places=3)
            self.assertLessEqual(float(sh.max()), 1.0 + 1e-12)

    def test_inked_voxels_lie_at_the_recto_face(self):
        # every 3D ink voxel center lies within the deposit plus the absorbed depth plus one voxel of the recto
        # surface (the verso face of the same winding lies about 4.8 voxels away at this thickness and crush)
        from scipy.spatial import cKDTree
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(TINY, thick=7.0, pitch=14.0, **INK))
        box = (8, 40, 20, 140, 20, 140)
        _, _, _, ink = sc.scan_block(*box, with_ink=True)
        self.assertGreater(int(ink.sum()), 300)
        zz, yy, xx = np.nonzero(ink)
        pts = np.stack([xx + box[4], yy + box[2], zz + box[0]], 1).astype(float)
        rec = sc.surface(0.25, "recto")
        P = rec["P"][rec["valid"]]
        P = P[(P[:, 2] > box[0] - 4) & (P[:, 2] < box[1] + 4)]
        dist = cKDTree(P).query(pts)[0]
        bound = (INK["ink_um"] + INK["ink_depth_um"]) / 8.0 + 1.0
        self.assertLessEqual(float(dist.max()), bound)
        cen = sc.surface(0.25, "center")
        C = cen["P"][cen["valid"]]
        dc = cKDTree(C[(C[:, 2] > box[0] - 4) & (C[:, 2] < box[1] + 4)]).query(pts)[0]
        self.assertGreater(float(np.median(dc)), float(np.median(dist)))     # the recto side, not the middle

    def test_gray_excess_matches_the_ink_mass(self):
        # no blur, noise, crush or bend: the CT excess over the noink twin, summed, equals the deposit's mass
        # (thickness times 1 + ink_rho times the inked area of the recto surface). The deposit is half a voxel thick,
        # so only an honest partial volume gets this right at one sample per voxel.
        from kit import scrollsim2 as s2
        p = dict(TINY, shape=[24, 128, 128], squash=1.0, warp=0.0, thick_sd=0.0, delam=0.0, holes=0.0, fiber=0.0,
                 contact_share=0.0, noise=0.0, rings=0.0, bias=0.0, blur=0.0, edge=0.0, noise_corr=0.0,
                 ink_um=4.0, ink_rho=0.25, ink_letter=14.0, ink_line=20.0, ink_col=200.0, ink_gap=40.0,
                 ink_margin=2.0)
        box = (0, 24, 0, 128, 0, 128)
        sc = s2.Scroll2(dict(p))
        ct, _, _, ink = sc.scan_block(*box, with_ink=True)
        tw, _, _, ink2 = s2.Scroll2(s2.noink(p)).scan_block(*box, with_ink=True)
        self.assertTrue(np.array_equal(ink, ink2))
        diff = ct.astype(float) - tw
        gain = float(s2.DEFAULTS["bright"]) - float(s2.DEFAULTS["air"])
        measured = diff.sum() / gain
        rec = sc.surface(0.5, "recto")
        cov = sc.ink_cover(sc.s_at(rec["theta"].ravel()), rec["z_rolled"].ravel()).reshape(rec["theta"].shape)
        P = rec["P"]
        ds = np.gradient(P, axis=1)
        dz = np.gradient(P, axis=0)
        area = np.linalg.norm(np.cross(ds, dz), axis=-1)
        expected = 0.5 * 1.25 * float((cov * area)[rec["valid"]].sum())
        self.assertGreater(expected, 50)
        self.assertLess(abs(measured / expected - 1), 0.05, (measured, expected))
        on = diff[ink > 0]
        self.assertGreater(float(on.mean()), 2.0)                 # the truth voxels carry the excess
        self.assertGreater(float(on.sum()), 0.85 * float(diff.sum()))

    def test_noink_twin_differs_only_near_inked_recto_faces(self):
        from scipy import ndimage
        from kit import scrollsim2 as s2
        p = dict(TINY, edge=0.0, **INK)                           # blur 0.9: a change spreads 4 voxels at most
        box = (8, 40, 20, 140, 20, 140)
        ct, lab, _, ink = s2.Scroll2(dict(p)).scan_block(*box, with_ink=True)
        tw, lab2, _, ink2 = s2.Scroll2(s2.noink(p)).scan_block(*box, with_ink=True)
        plain, lab3, _ = s2.Scroll2(dict(TINY, edge=0.0)).scan_block(*box)
        self.assertTrue(np.array_equal(tw, plain))                # the twin is the scroll without ink
        self.assertTrue(np.array_equal(lab, lab3) and np.array_equal(lab2, lab3))
        self.assertTrue(np.array_equal(ink, ink2))
        changed = ct != tw
        self.assertGreater(int(changed.sum()), 1000)
        near = ndimage.binary_dilation(ink > 0, np.ones((3, 3, 3), bool), iterations=6)
        self.assertEqual(int((changed & ~near).sum()), 0)
        self.assertGreater(float(np.abs(ct.astype(float) - tw)[ink > 0].mean()), 3.0)

    @unittest.skipUnless(HAVE_ZARR, "needs zarr")
    def test_ink_tif_matches_the_3d_truth_and_the_pattern_share(self):
        import zarr
        from kit import scrollsim2 as s2
        from kit import vc3d_io
        with tempfile.TemporaryDirectory() as t:
            a = Path(t) / "a"
            # wide procedural strokes (8 voxels), so letter edges, where a voxel center and a vertex may fall on
            # either side, are a small share
            p = dict(TINY, **dict(INK, ink_letter=28.0, ink_line=36.0, ink_glyphs="strokes", ink_stroke=0.3))
            doc = s2.make(a, p, workers=4, block=32, levels=1, chunk=32, surfaces=True, progress=None)
            ink3 = zarr.open_group(str(a / "truth" / "ink.zarr"), mode="r")["0"][:]
            sd = a / "truth" / "surfaces" / "spiral-recto"
            r = vc3d_io.read_tiff(sd / "ink.tif")
            tif = np.frombuffer(bytes(r.data), np.uint8).reshape(r.h, r.w)
            self.assertEqual((sd.parent / "spiral-center" / "ink.tif").read_bytes(), (sd / "ink.tif").read_bytes())
            xyz = []
            for c in "xyz":
                q = vc3d_io.read_tiff(sd / f"{c}.tif")
                xyz.append(np.frombuffer(bytes(q.data), np.float32).reshape(q.h, q.w))
            x, y, z = xyz
            valid = x >= 0
            self.assertEqual(tif.shape, x.shape)
            self.assertFalse(tif[~valid].any())
            vi = np.clip(np.rint(np.stack([z[valid], y[valid], x[valid]], 1)).astype(int), 0,
                         np.array(ink3.shape) - 1)
            at = ink3[vi[:, 0], vi[:, 1], vi[:, 2]]
            t2 = tif[valid]
            self.assertGreater(int(t2.sum()), 100)
            self.assertGreater(float((at == t2).mean()), 0.95)
            self.assertGreater(float(at[t2 > 0].mean()), 0.9)       # where the surface is inked the volume is too
            info = json.loads((a / "truth.json").read_text())
            self.assertTrue(info["ink"]["on"] and info["ink"]["painted"])
            self.assertEqual(info["ink"]["thickness_vox"], 1.0)
            share = info["ink"]["pattern_share"]
            self.assertGreater(share, 0.01)
            self.assertLess(abs(doc["ink_surface_share"] / share - 1), 0.25)
            self.assertLess(abs(float(at.mean()) / share - 1), 0.25)
            rep = s2.publish(a, Path(t) / "pub")
            self.assertTrue(rep["ok"])
            pub = zarr.open_group(str(Path(t) / "pub" / "truth" / "ink.zarr"), mode="r")["0"][:]
            self.assertTrue(np.array_equal(pub, ink3))

    def test_ink_render_is_block_independent(self):
        from kit import scrollsim2 as s2
        p = dict(TINY, edge=0.0, **INK)                           # a narrower halo keeps the test quick
        whole, lw, _, iw = s2.Scroll2(dict(p)).scan_block(8, 40, 40, 120, 40, 120, with_ink=True)
        self.assertGreater(int(iw.sum()), 300)
        parts, lp, ip = np.zeros_like(whole), np.zeros_like(lw), np.zeros_like(iw)
        sc = s2.Scroll2(dict(p))                                  # another instance: the ink comes from the seed
        for z0 in (8, 24):
            for y0 in (40, 80):
                for x0 in (40, 80):
                    c, lab, _, ik = sc.scan_block(z0, z0 + 16, y0, y0 + 40, x0, x0 + 40, with_ink=True)
                    sl = (slice(z0 - 8, z0 + 8), slice(y0 - 40, y0), slice(x0 - 40, x0))
                    parts[sl], lp[sl], ip[sl] = c, lab, ik
        self.assertTrue(np.array_equal(whole, parts))
        self.assertTrue(np.array_equal(lw, lp))
        self.assertTrue(np.array_equal(iw, ip))


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
