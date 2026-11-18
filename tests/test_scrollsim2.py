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
        self.assertFalse(ink.any())                     # ink is off in this release
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


# ---------------------------------------------------------------------------------------------- texture and realism
def _donor_library(s2, path, **kw):
    """A texture library cut from a scrollsim2 render itself (synthetic: no real CT is read)."""
    donor = s2.Scroll2(dict(TINY, noise=4.0, seed=9))
    ct, _, _ = donor.scan_block(0, 48, 0, 160, 0, 160)
    lib = s2.build_library(ct, **dict(dict(patch=8, count=200, seed=1), **kw))
    s2.save_library(lib, path)
    return lib


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class ScrollSim2TextureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kit import scrollsim2 as s2
        cls.s2 = s2
        cls.tmp = tempfile.TemporaryDirectory()
        cls.lib_path = str(Path(cls.tmp.name) / "lib.npz")
        cls.lib = _donor_library(s2, cls.lib_path)
        cls.crops = []
        for seed, noise in ((11, 4.0), (12, 4.0), (13, 12.0)):
            ct, _, _ = s2.Scroll2(dict(TINY, seed=seed, noise=noise)).scan_block(0, 48, 20, 140, 20, 140)
            cls.crops.append(ct)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_build_library_finds_sheet_and_gap_and_refuses_a_blank_crop(self):
        s2, lib = self.s2, self.lib
        self.assertGreater(len(lib["sheet"]), 20)
        self.assertGreater(len(lib["gap"]), 20)
        self.assertEqual(lib["sheet"].shape[1:], (8, 8, 8))
        self.assertGreater(lib["contrast"], 0)
        self.assertTrue(0 < lib["sheet_share"] < 1 and 0 < lib["gap_share"] < 1)
        # sheet patches are a high-pass residual, small against the unit sheet-to-gap contrast; gap patches sit
        # well below the sheet (the gap median is 0 and the sheet median 1)
        sheet, gap = lib["sheet"].astype(float), lib["gap"].astype(float)
        self.assertLess(abs(float(sheet.mean())), 0.3)
        self.assertGreater(float(sheet.std()), 0.01)
        self.assertLess(float(gap.mean()), 0.5)
        # the same seed gives the same library
        again = s2.build_library(s2.Scroll2(dict(TINY, noise=4.0, seed=9)).scan_block(0, 48, 0, 160, 0, 160)[0],
                                 patch=8, count=200, seed=1)
        self.assertTrue(np.array_equal(lib["sheet"], again["sheet"]))
        for bad in (np.zeros((32, 32, 32)), np.full((32, 32, 32), 90.0), np.zeros((8, 8, 8))):
            with self.assertRaises(s2.SimError):
                s2.build_library(bad, patch=8)
        with self.assertRaises(s2.SimError):
            s2.build_library(self.crops[0], patch=7)                 # odd: Hann half-overlaps would not sum to 1

    def test_library_render_adds_only_the_residual(self):
        s2 = self.s2
        flat = dict(TINY, noise=0.0, rings=0.0, bias=0.0)            # nothing after the library but rounding
        plain = s2.Scroll2(dict(flat))
        tex = s2.Scroll2(dict(flat, library=self.lib_path))
        box = (8, 40, 20, 140, 20, 140)
        a, la, _ = plain.scan_block(*box)
        b, lb, _ = tex.scan_block(*box)
        self.assertTrue(np.array_equal(la, lb))                      # labels never change
        h = tex.halo()
        Z0, Y0, X0 = box[0] - h, box[2] - h, box[4] - h
        dens, _, near = tex.density_block(Z0, box[1] + h, Y0, box[3] + h, X0, box[5] + h)
        r = tex._library_block(Z0, Y0, X0, dens.shape, dens, near)
        r = r[h:h + 32, h:h + 120, h:h + 120]
        d = b.astype(float) - a
        ok = (a > 0) & (a < 255) & (b > 0) & (b < 255)
        self.assertLessEqual(float(np.abs(d - r)[ok].max()), 1.0)    # the difference is the residual, rounded
        self.assertGreater(float(np.abs(d).mean()), 0.1)
        air = r == 0
        self.assertGreater(int(air.sum()), 1000)                     # open air gets no texture
        self.assertTrue((d[air] == 0).all())
        zero = s2.Scroll2(dict(flat, library=self.lib_path, lib_gain=0.0)).scan_block(*box)[0]
        self.assertTrue(np.array_equal(zero, a))                     # gain 0 is the plain render

    def test_library_render_is_block_independent(self):
        sc = self.s2.Scroll2(dict(TINY, library=self.lib_path))
        whole, lw, _ = sc.scan_block(8, 40, 20, 140, 20, 140)
        parts = np.zeros_like(whole)
        for z0 in (8, 24):
            for y0 in (20, 80):
                for x0 in (20, 80):
                    c, _, _ = sc.scan_block(z0, z0 + 16, y0, y0 + 60, x0, x0 + 60)
                    parts[z0 - 8:z0 + 8, y0 - 20:y0 + 40, x0 - 20:x0 + 40] = c
        self.assertTrue(np.array_equal(whole, parts))
        # odd block edges that cut the 4-voxel tile grid in other places
        c, _, _ = sc.scan_block(13, 30, 37, 101, 51, 99)
        self.assertTrue(np.array_equal(whole[5:22, 17:81, 31:79], c))

    def test_library_refusals(self):
        s2 = self.s2
        with self.assertRaises(s2.SimError):
            s2.params({"lib_gain": -1.0})
        with self.assertRaises(s2.SimError):
            s2.params({"library": 3})
        with self.assertRaises(s2.SimError):
            s2.Scroll2(dict(TINY, library=str(Path(self.tmp.name) / "missing.npz"))).prepare()
        empty = str(Path(self.tmp.name) / "empty.npz")
        s2.save_library(dict(self.lib, gap=np.zeros((0, 8, 8, 8), np.float16)), empty)
        with self.assertRaises(s2.SimError):
            s2.Scroll2(dict(TINY, library=empty)).scan_block(8, 24, 20, 60, 20, 60)
        with self.assertRaises(s2.SimError):
            s2._file_sha256(str(Path(self.tmp.name) / "missing.npz"))

    def test_g1stats_is_deterministic_and_label_free(self):
        s2 = self.s2
        d = s2.g1stats(self.crops[0], 8.64)
        self.assertEqual(d, s2.g1stats(self.crops[0].copy(), 8.64))
        self.assertEqual(len(d["sheet_runs"]), s2.QN)
        self.assertGreater(d["runs"][0], 20)
        for k in s2.G1_SCALAR:
            self.assertIsNotNone(d[k], k)
        self.assertTrue(0 <= d["touching_share"] <= 1)
        self.assertAlmostEqual(float(np.percentile(np.asarray(d["sheet_gray"]), 50)), 1.0, delta=0.05)
        self.assertAlmostEqual(float(np.percentile(np.asarray(d["gap_gray"]), 50)), 0.0, delta=0.05)
        # a gray offset and gain leave the normalized statistics where they were
        shifted = s2.g1stats(self.crops[0].astype(np.float32) * 0.5 + 20.0, 8.64)
        self.assertLess(s2.g1distance(d, shifted)["sheet_gray"], 0.05)

    def test_g1distance_is_zero_to_itself_and_grows_with_noise(self):
        s2 = self.s2
        a, b, c = (s2.g1stats(x, 8.64) for x in self.crops)
        same = s2.g1distance(a, a)
        self.assertIn("gap_noise", same)
        self.assertTrue(all(v == 0 for v in same.values()))
        self.assertGreater(s2.g1distance(a, c)["gap_noise"], s2.g1distance(a, b)["gap_noise"])
        rng = np.random.default_rng(0)
        noisy = [s2.g1stats(np.clip(self.crops[0] + rng.normal(0, sd, self.crops[0].shape), 0, 255), 8.64)
                 for sd in (3.0, 9.0)]
        d1, d2 = (s2.g1distance(a, n)["gap_noise"] for n in noisy)
        self.assertGreater(d1, 0)
        self.assertGreater(d2, d1)

    def test_g1compare_inside_and_outside_the_real_spread(self):
        s2 = self.s2
        st = [dict(s2.g1stats(x, 8.64), scan=f"s{i}") for i, x in enumerate(self.crops)]
        inside = s2.g1compare(st[:2], st[0])          # one of the reals: mean distance is half the spread
        self.assertEqual(inside["scan_pairs"], 1)
        self.assertGreater(inside["judged"], 5)
        self.assertEqual(inside["inside"], inside["judged"])
        outside = s2.g1compare(st[:2], st[2])         # three times the noise lies outside a 4-to-4 spread
        self.assertFalse(outside["sim"]["gap_noise"]["inside"])
        self.assertLess(outside["inside"], outside["judged"])
        one = s2.g1compare([st[0], dict(st[1], scan="s0")], st[2])
        self.assertEqual(one["scan_pairs"], 0)        # crops of one scan give no spread and judge nothing
        self.assertEqual(one["judged"], 0)

    def test_resample_keeps_the_mean_and_g1_refuses_small_crops(self):
        s2 = self.s2
        v = self.crops[0].astype(np.float32)
        down = s2.resample(v, 4.32, 8.64)
        self.assertEqual(down.shape, (24, 60, 60))
        self.assertAlmostEqual(float(down.mean()), float(v.mean()), delta=0.01 * float(v.mean()))
        up = s2.resample(v[:16, :40, :40], 8.64, 4.32)
        self.assertEqual(up.shape, (32, 80, 80))
        self.assertAlmostEqual(float(up.mean()), float(v[:16, :40, :40].mean()), delta=0.01 * float(v.mean()))
        self.assertTrue(np.array_equal(s2.resample(v, 8.7, 8.64), v))   # within 2 percent: unchanged
        with self.assertRaises(s2.SimError):
            s2.g1stats(down[:4], 8.64)
        with self.assertRaises(s2.SimError):
            s2.g1stats(self.crops[0], 2.0)                            # shrinks below twice the tile
        with self.assertRaises(s2.SimError):
            s2.g1stats(np.full((16, 80, 80), 90.0), 8.64)             # blank: no sheet

    def test_library_g1_and_g1_compare_commands(self):
        import contextlib
        import io
        s2 = self.s2
        t = Path(self.tmp.name)
        np.save(t / "crop.npy", self.crops[0])
        np.save(t / "crop2.npy", self.crops[1])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(s2.main(["library", str(t / "crop.npy"), str(t / "cli.npz"), "--patch", "8",
                                      "--count", "50"]), 0)
        rep = json.loads(buf.getvalue())
        self.assertGreater(rep["sheet"], 0)
        self.assertEqual(len(s2.load_library(t / "cli.npz")["sheet"]), rep["sheet"])
        for name in ("crop", "crop2"):
            self.assertEqual(s2.main(["g1", str(t / f"{name}.npy"), "--voxel-um", "8.64", "--out",
                                      str(t / f"{name}.json")]), 0)
        self.assertEqual(json.loads((t / "crop.json").read_text())["scan"], "crop")
        self.assertEqual(s2.main(["g1-compare", "--real", str(t / "crop.json"), str(t / "crop2.json"),
                                  "--sim", str(t / "crop.json"), "--out", str(t / "cmp.json")]), 0)
        cmp = json.loads((t / "cmp.json").read_text())
        self.assertEqual(cmp["scan_pairs"], 1)
        self.assertEqual(cmp["inside"], cmp["judged"])
        with self.assertRaises(SystemExit):
            s2.main(["library", str(t / "crop.npy"), str(t / "bad.npz"), "--patch", "5"])


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
