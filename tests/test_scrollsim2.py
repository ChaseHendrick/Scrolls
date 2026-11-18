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


def _same(a, b):
    return a.shape == b.shape and a.dtype == b.dtype and bool(np.array_equal(a, b, equal_nan=a.dtype.kind == "f"))


@unittest.skipUnless(HAVE, "needs numpy and scipy")
class ScrollSim2TruthExtrasTest(unittest.TestCase):
    """The label pyramid, the contact map and the material coordinates (u, v, w) beside the CT."""

    def test_label_pyramid_takes_the_most_common_nonzero_label(self):
        from kit import scrollsim2 as s2
        cells = [([0] * 8, 0), ([0] * 7 + [5], 5), ([3, 3, 0, 0, 0, 0, 0, 5], 3),
                 ([3, 5, 5, 3, 0, 0, 0, 0], 3),                 # a tie goes to the smaller label
                 ([0, 0, 0, 0, 0, 9, 9, 7], 9),                 # zeros never win while a label is there
                 ([7, 7, 7, 9, 9, 9, 9, 0], 9), ([65535, 65535, 1, 0, 0, 0, 0, 0], 65535)]
        a = np.zeros((2, 2, 2 * len(cells)), np.uint16)
        for k, (vals, _) in enumerate(cells):
            for i, v in enumerate(vals):
                a[i // 4, (i // 2) % 2, 2 * k + i % 2] = v
        got = s2.label_down(a)
        self.assertEqual(got.shape, (1, 1, len(cells)))
        self.assertEqual(got.dtype, np.uint16)
        self.assertEqual(got[0, 0].tolist(), [want for _, want in cells])
        # a stacked case: the same rule on a larger random volume against a slow per-cell loop
        rng = np.random.default_rng(1)
        b = rng.choice(np.array([0, 0, 0, 2, 4, 7], np.uint16), size=(4, 6, 8))
        fast = s2.label_down(b)
        for z in range(2):
            for y in range(3):
                for x in range(4):
                    v = b[2 * z:2 * z + 2, 2 * y:2 * y + 2, 2 * x:2 * x + 2].ravel()
                    v = v[v > 0]
                    if len(v) == 0:
                        want = 0
                    else:
                        u, c = np.unique(v, return_counts=True)
                        want = int(u[c == c.max()].min())
                    self.assertEqual(int(fast[z, y, x]), want)

    def test_contact_share_matches_pressed_share(self):
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(TINY, contact_share=0.45))
        r = sc.truth_block(0, 48, 0, 160, 0, 160, kinds=("contact",))
        self.assertEqual(sorted(r), ["contact", "labels"])
        sheet = r["labels"] > 0
        self.assertTrue(np.array_equal(sheet, r["contact"] > 0))          # contact 0 exactly in air
        share = float((r["contact"][sheet] == 2).mean())
        pressed = float((sc.press[s2.ANG:sc.n_end] > 0.5).mean())      # as truth.json pressed_share
        self.assertGreater(pressed, 0.1)
        self.assertGreater(share, 0.6 * pressed)
        self.assertLess(share, 1.4 * pressed)
        with self.assertRaises(s2.SimError):
            s2.truth_kinds("contact,depth")
        self.assertEqual(s2.truth_kinds("uvw,contact"), ("contact", "uvw"))

    def test_uvw_follows_the_sheet(self):
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(TINY))
        # along a ray from the center line, u grows winding by winding, and w runs from recto (+) to verso (-)
        z = 24
        cx, cy = sc._center_at(sc.cl, float(z))
        cx, cy = int(round(float(cx))), int(round(float(cy)))
        r = sc.truth_block(z, z + 1, cy, cy + 1, cx, 160)
        lab, u, w = r["labels"][0, 0], r["u"][0, 0], r["w"][0, 0]
        self.assertTrue(np.array_equal(np.isnan(u), lab == 0))
        runs = []
        for i in np.flatnonzero(lab):
            if runs and runs[-1][-1] == i - 1 and lab[runs[-1][-1]] == lab[i]:
                runs[-1].append(i)
            else:
                runs.append([i])
        self.assertGreaterEqual(len(runs), 3)
        means = [float(u[k].mean()) for k in runs]
        self.assertTrue(all(b > a for a, b in zip(means, means[1:])), means)
        long_runs = [k for k in runs if len(k) >= 3]
        self.assertTrue(long_runs)
        flips = sum(1 for k in long_runs if w[k[0]] > 0 > w[k[-1]])
        self.assertGreaterEqual(flips, 0.8 * len(long_runs))
        # on sheet voxels |w| is at most half the thickness (plus half the delamination)
        b = sc.truth_block(16, 32, 20, 140, 20, 140)
        ws = b["w"][b["labels"] > 0]
        self.assertTrue(np.isfinite(ws).all())
        self.assertLessEqual(float(np.abs(ws).max()), 0.5 * float(sc.thick.max()) + 0.5 * float(sc.delam.max()) + 1e-4)
        # exact points: on the center surface w is 0, u the surface's s and v its rolled z; half way to the recto face
        # (surface(which="recto") lies on the inner side) w is positive, half way out on the verso side negative
        surf = sc.surface(8.0, "center")
        TH, ZZ = surf["theta"], surf["z_rolled"]
        S = np.broadcast_to(surf["s"][None], TH.shape)
        fo = sc.face_offset(TH, ZZ)
        R = sc.R_at(TH, ZZ)
        for frac, sign in ((0.0, 0), (0.5, 1), (-0.5, -1)):
            rr = R + frac * fo
            rolled = np.stack([sc.center[0] + rr * np.cos(TH), sc.center[1] + rr * np.sin(TH), ZZ], -1).reshape(-1, 3)
            out = sc.forward(rolled)[0]
            lim = np.array([sc.X - 1, sc.Y - 1, sc.Z - 1])
            ok = np.isfinite(out).all(1) & (out >= 0).all(1) & (out <= lim).all(1)
            ok &= TH.ravel() > 0.01                     # the inner end itself (theta 0) wraps to a turn before it
            t = sc.truth_points(out[ok], ("uvw",))
            self.assertTrue((t["labels"] > 0).all())
            self.assertGreater(ok.sum(), 200)
            self.assertTrue(np.allclose(t["w"], -frac * fo.ravel()[ok], atol=1e-3))
            if sign:
                self.assertTrue((np.sign(t["w"]) == sign).all())
            self.assertTrue(np.allclose(t["u"], S.ravel()[ok], atol=0.05))
            self.assertTrue(np.allclose(t["v"], ZZ.ravel()[ok], atol=1e-3))
        rec = sc.surface(8.0, "recto")
        self.assertTrue(np.allclose(np.hypot(*(sc.rolled(rec["P"].reshape(-1, 3))[:, :2] - sc.center).T),
                                    (R + fo).ravel(), atol=1e-3))      # the recto surface is R + fo: fo < 0, inner

    def test_truth_extras_are_block_independent(self):
        from kit import scrollsim2 as s2
        sc = s2.Scroll2(dict(TINY))
        whole = sc.truth_block(8, 40, 20, 140, 20, 140)
        self.assertEqual(sorted(whole), ["contact", "labels", "u", "v", "w"])
        _, lw, _ = sc.scan_block(8, 40, 20, 140, 20, 140)
        self.assertTrue(np.array_equal(whole["labels"], lw))            # the same labels as the CT's
        parts = {k: np.full_like(v, np.nan) if v.dtype.kind == "f" else np.zeros_like(v) for k, v in whole.items()}
        for z0 in (8, 24):
            for y0 in (20, 80):
                for x0 in (20, 80):
                    got = sc.truth_block(z0, z0 + 16, y0, y0 + 60, x0, x0 + 60)
                    for k, v in got.items():
                        parts[k][z0 - 8:z0 + 8, y0 - 20:y0 + 40, x0 - 20:x0 + 40] = v
        for k in whole:
            self.assertTrue(_same(whole[k], parts[k]), k)
        self.assertTrue((whole["contact"] == 2).any() and (whole["contact"] == 1).any())
        far = sc.truth_block(0, 16, -400, -376, -400, -376)            # an air box, skipped
        self.assertFalse(far["labels"].any())
        self.assertTrue(np.isnan(far["u"]).all())
        self.assertTrue(_same(far["w"], sc.truth_block(0, 16, -400, -376, -400, -376, air=False)["w"]))

    @unittest.skipUnless(HAVE_ZARR, "needs zarr")
    def test_make_writes_truth_extras_and_label_pyramid(self):
        import os
        import zarr
        from kit import scrollsim2 as s2
        with tempfile.TemporaryDirectory() as t:
            a = Path(t) / "a"
            doc = s2.make(a, dict(TINY), workers=4, block=32, levels=2, chunk=32, progress=None,
                          truth=("uvw", "contact"))
            self.assertTrue(doc["render"]["verified"]["ok"])
            self.assertTrue(doc["render"]["verified"]["labels"]["ok"])
            self.assertEqual(doc["truth_volumes"], ["contact", "uvw"])
            self.assertEqual(json.loads((a / "truth" / "make-key.json").read_text())["truth"], ["contact", "uvw"])
            ct = zarr.open_group(str(a / "ct.zarr"), mode="r")
            lg = zarr.open_group(str(a / "truth" / "labels.zarr"), mode="r")
            self.assertEqual(sorted(lg.array_keys()), ["0", "1", "2"])
            self.assertEqual(lg.attrs["multiscales"][0]["datasets"], ct.attrs["multiscales"][0]["datasets"])
            l0 = lg["0"][:]
            self.assertTrue(np.array_equal(lg["1"][:], s2.label_down(l0)))
            l1 = lg["1"][:]
            self.assertTrue(np.array_equal(lg["2"][:], s2.label_down(l1)))
            self.assertGreater(len(np.unique(lg["2"][:])), 3)
            contact = zarr.open_group(str(a / "truth" / "contact.zarr"), mode="r")["0"][:]
            uvw = zarr.open_group(str(a / "truth" / "uvw.zarr"), mode="r")
            self.assertEqual(contact.dtype, np.uint8)
            self.assertTrue(np.array_equal(contact > 0, l0 > 0))
            for k in "uvw":
                self.assertEqual(uvw[k].dtype, np.float32)
                self.assertTrue(np.array_equal(np.isnan(uvw[k][:]), l0 == 0), k)
            sc = s2.Scroll2(dict(TINY))
            ref = sc.truth_block(16, 48, 32, 96, 64, 128)
            self.assertTrue(_same(contact[16:48, 32:96, 64:128], ref["contact"]))
            self.assertTrue(_same(uvw["w"][16:48, 32:96, 64:128], ref["w"]))
            # resume checks the truth volumes
            with self.assertRaises(s2.SimError):
                s2.make(a, dict(TINY), block=32, levels=2, chunk=32, progress=None, resume=True)
            with self.assertRaises(s2.SimError):
                s2.make(a, dict(TINY), block=32, levels=2, chunk=32, progress=None, resume=True, truth="contact")
            with self.assertRaises(s2.SimError):
                s2.make(Path(t) / "e", dict(TINY), progress=None, truth=("ink",))
            # verify catches a lost label pyramid chunk and a lost contact chunk; pyramid repairs the labels
            key = sorted(f.name for f in (a / "truth" / "labels.zarr" / "1").iterdir() if f.name[0] != ".")[0]
            os.remove(a / "truth" / "labels.zarr" / "1" / key)
            v = s2.verify(a)
            self.assertFalse(v["ok"])
            self.assertEqual(v["labels"]["bad"], {"1": [key]})
            r = s2.pyramid(a, workers=1)
            self.assertTrue(r["ok"], r)
            self.assertTrue(np.array_equal(zarr.open_group(str(a / "truth" / "labels.zarr"), mode="r")["1"][:], l1))
            ck = sorted(f.name for f in (a / "truth" / "contact.zarr" / "0").iterdir() if f.name[0] != ".")[0]
            os.rename(a / "truth" / "contact.zarr" / "0" / ck, Path(t) / "lost")
            self.assertIn("truth/contact.zarr/0", s2.verify(a)["labels"]["bad"])
            os.rename(Path(t) / "lost", a / "truth" / "contact.zarr" / "0" / ck)
            # publish copies the label pyramid and the extras
            d = Path(t) / "dst"
            r = s2.publish(a, d)
            self.assertTrue(r["ok"] and r["labels"]["ok"], r)
            self.assertTrue(np.array_equal(zarr.open_group(str(d / "truth" / "contact.zarr"), mode="r")["0"][:], contact))
            self.assertEqual(sorted(zarr.open_group(str(d / "truth" / "labels.zarr"), mode="r").array_keys()),
                             ["0", "1", "2"])

    @unittest.skipUnless(HAVE_ZARR, "needs zarr")
    def test_make_command_line_truth_resume_and_block_split(self):
        # --truth on the command line; a run stopped early refuses to resume with other truth volumes, then resumes
        # with the same ones; 64-voxel blocks write what truth_block gives on the whole box
        import contextlib
        import io
        import zarr
        from kit import scrollsim2 as s2
        small = dict(TINY, shape=[16, 160, 160])
        sets = []
        for k, v in small.items():
            sets += ["--set", f"{k}={json.dumps(v)}"]
        with tempfile.TemporaryDirectory() as t:
            b = Path(t) / "b"
            args = ["make", str(b)] + sets + ["--workers", "4", "--block", "64", "--chunk", "32", "--levels", "1"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(s2.main(args + ["--truth", "contact,uvw", "--max-blocks", "3"]), s2.INCOMPLETE)
                with self.assertRaises(SystemExit):
                    s2.main(args + ["--truth", "uvw", "--resume"])
                with self.assertRaises(SystemExit):
                    s2.main(args + ["--truth", "bogus"])
                self.assertEqual(s2.main(args + ["--truth", "uvw,contact", "--resume"]), 0)
            ref = s2.Scroll2(small).truth_block(0, 16, 0, 160, 0, 160)
            self.assertTrue(np.array_equal(zarr.open_group(str(b / "truth" / "contact.zarr"), mode="r")["0"][:],
                                           ref["contact"]))
            ub = zarr.open_group(str(b / "truth" / "uvw.zarr"), mode="r")
            for k in "uvw":
                self.assertTrue(_same(ub[k][:], ref[k]), k)
            lb = zarr.open_group(str(b / "truth" / "labels.zarr"), mode="r")
            self.assertTrue(np.array_equal(lb["0"][:], ref["labels"]))
            self.assertTrue(np.array_equal(lb["1"][:], s2.label_down(ref["labels"])))
            self.assertTrue(s2.verify(b)["labels"]["ok"])


if __name__ == "__main__":
    unittest.main()
