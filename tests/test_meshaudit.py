"""Tests for kit.meshaudit (protocol docs/plans/2026-10-07-mesh-hypothesis.md)."""

import json
import os
import struct
import tempfile
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from kit import meshaudit as ma


@unittest.skipIf(np is None, "numpy not installed")
class TransformTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        self.src = rng.uniform(0, 10000, (8, 3))
        self.m = np.array([[3.9, 0.01, 0.0, 300.0], [-0.01, 3.9, 0.002, 200.0], [0.0, 0.001, 3.9, -5000.0]])
        self.dst = ma.apply_affine(self.m, self.src)

    def test_exact_landmarks_refit_and_zero_error(self):
        rec = ma.audit_transform(self.m, self.src.tolist(), self.dst.tolist(), 9.36, 2.4)
        self.assertLess(rec["refit_max_diff"], 1e-6)
        self.assertLess(rec["fit_rms_um"], 1e-6)
        self.assertLess(rec["loo_rms_um"], 1e-6)
        self.assertEqual(rec["tier"], "tight")
        self.assertAlmostEqual(rec["scale_dev_pct"], 100 * (3.9 / (9.36 / 2.4) - 1), places=1)

    def test_noise_gives_loo_larger_than_fit(self):
        rng = np.random.default_rng(2)
        noisy = self.dst + rng.normal(0, 10, self.dst.shape)  # 10 voxels at 2.4 um = 24 um
        m = ma.fit_affine(self.src, noisy)
        rec = ma.audit_transform(m, self.src.tolist(), noisy.tolist(), 9.36, 2.4)
        self.assertGreater(rec["loo_rms_um"], rec["fit_rms_um"])
        self.assertGreater(rec["loo_rms_um"], 20)

    def test_flatness_flags_coplanar_landmarks(self):
        flat = self.src.copy()
        flat[:, 2] = 100.0 + flat[:, 0] * 1e-6
        rec = ma.audit_transform(self.m, flat.tolist(), ma.apply_affine(self.m, flat).tolist(), 9.36, 2.4)
        self.assertLess(rec["landmark_flatness"], 1e-3)
        good = ma.audit_transform(self.m, self.src.tolist(), self.dst.tolist(), 9.36, 2.4)
        self.assertGreater(good["landmark_flatness"], 0.1)

    def test_stored_matrix_not_fitting_its_landmarks_is_flagged(self):
        wrong = self.m.copy()
        wrong[0, 0] *= 1.01
        rec = ma.audit_transform(wrong, self.src.tolist(), self.dst.tolist(), 9.36, 2.4)
        self.assertFalse(rec["matrix_matches_landmarks"])
        self.assertLess(rec["loo_rms_um"], 1e-6)
        ok = ma.audit_transform(self.m, self.src.tolist(), self.dst.tolist(), 9.36, 2.4)
        self.assertTrue(ok["matrix_matches_landmarks"])

    def test_four_landmarks_untestable(self):
        rec = ma.audit_transform(self.m, self.src[:4].tolist(), self.dst[:4].tolist(), 9.36, 2.4)
        self.assertIsNone(rec["loo_rms_um"])
        self.assertEqual(rec["tier"], "untestable")

    def test_roundtrip_detects_inconsistent_reverse(self):
        inv = np.linalg.inv(np.r_[self.m, [[0, 0, 0, 1]]])[:3]
        good = ma.audit_transform(self.m, self.src.tolist(), self.dst.tolist(), 9.36, 2.4, reverse=inv)
        self.assertLess(good["roundtrip_max_um"], 1e-6)
        bad_inv = inv.copy()
        bad_inv[2, 3] += 5  # 5 voxels at 9.36 um
        bad = ma.audit_transform(self.m, self.src.tolist(), self.dst.tolist(), 9.36, 2.4, reverse=bad_inv)
        self.assertAlmostEqual(bad["roundtrip_max_um"], 5 * 9.36, places=3)

    def test_tiers(self):
        self.assertEqual(ma.tier(10), "tight")
        self.assertEqual(ma.tier(50), "loose")
        self.assertEqual(ma.tier(100), "coarse")

    def test_catalogue_audit_pairs_reverse(self):
        inv = np.linalg.inv(np.r_[self.m, [[0, 0, 0, 1]]])[:3]
        cat = {"samples": {"S": {"volumes": {
            "A": {"properties": {"pixel_size_um": 9.36, "transforms": [{
                "to_volume_id": "B", "transformation_matrix": self.m.tolist(),
                "from_landmarks": self.src.tolist(), "to_landmarks": self.dst.tolist()}]}},
            "B": {"properties": {"pixel_size_um": 2.4, "transforms": [{
                "to_volume_id": "A", "transformation_matrix": inv.tolist(),
                "from_landmarks": self.dst.tolist(), "to_landmarks": self.src.tolist()}]}},
        }}}}
        rows = ma.transforms_audit(cat)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["has_reverse"] for r in rows))
        self.assertTrue(all(r["roundtrip_max_um"] < 1e-6 for r in rows))


class CanvasTests(unittest.TestCase):
    def test_match_ratios(self):
        self.assertEqual(ma.canvas_match([4760, 4220], (238, 211), (0.05, 0.05)), 1.0)
        self.assertEqual(ma.canvas_match([2380, 2110], (238, 211), (0.05, 0.05)), 0.5)
        self.assertIsNone(ma.canvas_match([18560, 16460], (238, 211), (0.05, 0.05)))

    def test_parse_ifd(self):
        entries = [(256, 4, 1, 928), (257, 4, 1, 823), (258, 3, 1, 32)]
        ifd = struct.pack("<H", len(entries))
        for tag, typ, cnt, val in entries:
            ifd += struct.pack("<HHI", tag, typ, cnt) + (struct.pack("<HH", val, 0) if typ == 3 else struct.pack("<I", val))
        self.assertEqual(ma.parse_ifd_dims(ifd, "<"), (928, 823))

    def test_parse_bigtiff_ifd(self):
        entries = [(256, 16, 1, 3488), (257, 3, 1, 8500)]
        ifd = struct.pack("<Q", len(entries))
        for tag, typ, cnt, val in entries:
            ifd += struct.pack("<HHQ", tag, typ, cnt) + (struct.pack("<Q", val) if typ == 16 else struct.pack("<HHI", val, 0, 0))
        self.assertEqual(ma.parse_ifd_dims(ifd, "<", big=True), (3488, 8500))

    def test_volume_id(self):
        self.assertEqual(ma._volume_id_in("2.403um-0.22m-77keV-volume-20260319124803.zarr"), "20260319124803")


@unittest.skipIf(np is None, "numpy not installed")
class DepthTests(unittest.TestCase):
    def sheet(self, n, dz, centre_um, width_um=40.0, neighbour_um=None):
        z = ma.layer_positions_um(n, dz)
        p = 50 + 100 * np.exp(-0.5 * ((z - centre_um) / width_um) ** 2)
        if neighbour_um is not None:
            p += 60 * np.exp(-0.5 * ((z - neighbour_um) / width_um) ** 2)
        return p

    def test_c1_known_shift_recovered(self):
        for dz in (2.4, 9.366, 1.129):
            n = int(round(262 / dz)) | 1
            for shift in (-40.0, -12.5, 0.0, 7.3, 33.0):
                got = ma.sheet_peak_um(self.sheet(n, dz, shift), dz)
                self.assertIsNotNone(got)
                self.assertLess(abs(got - shift), 2.0, (dz, shift, got))

    def test_peak_outside_window_is_none(self):
        self.assertIsNone(ma.sheet_peak_um(self.sheet(109, 2.4, 110.0, width_um=10), 2.4))

    def test_c2_identity_and_shift_between_resolutions(self):
        nat = [self.sheet(28, 9.366, 5.0, neighbour_um=-110) for _ in range(8)]
        same = ma.compare_profiles(nat, nat, 9.366, 9.366)
        self.assertEqual(same["delta_median_um"], 0.0)
        cross = [self.sheet(109, 2.4, 5.0 + 20.0, neighbour_um=-90) for _ in range(8)]
        r = ma.compare_profiles(nat, cross, 9.366, 2.4)
        self.assertAlmostEqual(r["delta_median_um"], 20.0, delta=2.0)
        self.assertFalse(r["layer_order_opposite"])

    def test_flipped_layer_order_detected(self):
        rng = np.random.default_rng(3)
        nat, cross = [], []
        for _ in range(10):
            c = rng.uniform(-20, 20)
            nb = rng.choice([-100.0, 100.0])
            nat.append(self.sheet(28, 9.366, c, neighbour_um=nb))
            cross.append(self.sheet(109, 2.4, c + 10, neighbour_um=nb + 10)[::-1])
        r = ma.compare_profiles(nat, cross, 9.366, 2.4)
        self.assertTrue(r["layer_order_opposite"])
        self.assertAlmostEqual(r["delta_median_um"], 10.0, delta=2.0)

    def test_c3_location_control_can_fail(self):
        rng = np.random.default_rng(4)
        nat = [self.sheet(109, 2.4, rng.uniform(-30, 30), neighbour_um=rng.uniform(-110, -70)) for _ in range(12)]
        unrelated = [self.sheet(109, 2.4, rng.uniform(-30, 30), neighbour_um=rng.uniform(70, 110)) for _ in range(12)]
        rng.shuffle(unrelated)
        r = ma.compare_profiles(nat, nat, 2.4, 2.4)
        self.assertTrue(r["location_control_pass"])
        r2 = ma.compare_profiles(nat, unrelated, 2.4, 2.4)
        self.assertFalse(r2["location_control_pass"])
        self.assertFalse(r2["evaluable"])

    def test_too_few_tiles(self):
        r = ma.compare_profiles([None] * 5, [None] * 5, 2.4, 2.4)
        self.assertFalse(r["evaluable"])


@unittest.skipIf(np is None, "numpy not installed")
class ReaderTests(unittest.TestCase):
    def test_local_uncompressed_zarr_window(self):
        with tempfile.TemporaryDirectory() as d:
            L, H, W, c = 5, 300, 260, 128
            vol = (np.arange(L * H * W) % 251).astype(np.uint8).reshape(L, H, W)
            vol[:, :, :10] = 0
            os.makedirs(os.path.join(d, "0"))
            with open(os.path.join(d, ".zattrs"), "w") as f:
                json.dump({"multiscales": [{"datasets": [{"path": "0", "coordinateTransformations": [
                    {"type": "scale", "scale": [2.4, 2.4, 2.4]}]}]}]}, f)
            with open(os.path.join(d, "0", ".zarray"), "w") as f:
                json.dump({"zarr_format": 2, "shape": [L, H, W], "chunks": [L, c, c], "dtype": "|u1",
                           "compressor": None, "fill_value": 0, "order": "C", "filters": None,
                           "dimension_separator": "/"}, f)
            for yi in range((H + c - 1) // c):
                for xi in range((W + c - 1) // c):
                    blk = np.zeros((L, c, c), np.uint8)
                    part = vol[:, yi * c:(yi + 1) * c, xi * c:(xi + 1) * c]
                    blk[:, :part.shape[1], :part.shape[2]] = part
                    os.makedirs(os.path.join(d, "0", "0", str(yi)), exist_ok=True)
                    if (yi, xi) != (2, 1):  # one absent chunk reads as fill value
                        blk.tofile(os.path.join(d, "0", "0", str(yi), str(xi)))

            def fetch(u):
                with open(u, "rb") as f:
                    return f.read()

            sv = ma.SurfaceVolume(d, fetch=fetch)
            got = sv.read(0, 100, 290, 5, 250)
            want = vol[:, 100:290, 5:250].copy()
            want[:, 256 - 100:, 128 - 5:] = 0
            self.assertTrue(np.array_equal(got, want))
            self.assertEqual(sv.dz_um, 2.4)
            self.assertTrue(np.array_equal(sv.read_layer(0, 3, 100, 290, 5, 250), want[3]))
            prof = sv.profile(0.5, 0.3, target_um=2.4, window_mm=0.1)
            self.assertEqual(len(prof), L)


@unittest.skipIf(np is None, "numpy not installed")
class GeometryTests(unittest.TestCase):
    def surface(self, h, w, step):
        r, c = np.mgrid[0:h, 0:w].astype(float)
        x = 100 + c * step
        y = 200 + r * step
        z = 300 + 20 * np.sin(c * step / 400.0) + 10 * np.cos(r * step / 300.0)
        return np.stack([x, y, z], axis=-1)

    def test_pure_affine_and_known_normal_shift(self):
        m = np.array([[3.9, 0.0, 0.0, 50.0], [0.0, 3.9, 0.0, -20.0], [0.0, 0.0, 3.9, 10.0]])
        ref = self.surface(60, 80, 20.0)
        # the cross mesh: same parametrization, 4x denser grid, built from the affine image
        hc, wc = (60 - 1) * 4 + 1, (80 - 1) * 4 + 1
        rr, cc = np.mgrid[0:hc, 0:wc] / 4.0
        dense = np.stack([100 + cc * 20.0, 200 + rr * 20.0,
                          300 + 20 * np.sin(cc * 20.0 / 400.0) + 10 * np.cos(rr * 20.0 / 300.0)], axis=-1)
        cross = ma.apply_affine(m, dense.reshape(-1, 3)).reshape(hc, wc, 3)
        res = ma.affine_residuals(ref, cross, m, 2.4)
        self.assertGreater(res["matched"], 4000)
        self.assertLess(res["normal_p90_um"], 0.5)
        n = ma.grid_normals(cross)
        shifted = cross + 10.0 * n  # 10 cross voxels = 24 um along the normal
        res2 = ma.affine_residuals(ref, shifted, m, 2.4)
        self.assertAlmostEqual(res2["normal_median_um"], 24.0, delta=1.0)

    def test_holes_are_skipped(self):
        ref = self.surface(20, 20, 20.0)
        ref[5:10, 5:10] = np.nan
        m = np.c_[np.eye(3), np.zeros(3)]
        res = ma.affine_residuals(ref, ref.copy(), m, 9.0)
        self.assertEqual(res["points"], 20 * 20 - 25)
        self.assertLess(res["normal_max_um"], 1e-9)


@unittest.skipIf(np is None, "numpy not installed")
class ShiftTests(unittest.TestCase):
    def texture(self, n, seed=0):
        rng = np.random.default_rng(seed)
        f = np.fft.fft2(rng.normal(size=(n, n)))
        ky, kx = np.meshgrid(np.fft.fftfreq(n), np.fft.fftfreq(n), indexing="ij")
        return np.real(np.fft.ifft2(f * np.exp(-(kx ** 2 + ky ** 2) / (2 * 0.08 ** 2))))

    def test_phase_shift_sign_and_subpixel(self):
        big = self.texture(400)
        a = big[100:300, 100:300]
        b = big[100 - 7:300 - 7, 100 + 4:300 + 4]  # b(x) = a(x - s) with s = (7, -4)
        (sy, sx), psr = ma.phase_shift(a, b)
        self.assertAlmostEqual(sy, 7, delta=0.3)
        self.assertAlmostEqual(sx, -4, delta=0.3)
        self.assertGreater(psr, 6)
        noise = np.random.default_rng(9).normal(size=a.shape)
        self.assertLess(ma.phase_shift(a, noise)[1], 6)

    def test_area_resample_conserves_mean_and_bins(self):
        a = np.arange(40, dtype=float).reshape(1, 40)  # pixel i covers [2i, 2i+2) um
        out = ma.area_resample_1d(a, 2.0, 5.0, 10, 10.0, 1)
        self.assertEqual(out.shape, (1, 10))
        # first bin [10, 15) um: pixels 5, 6 full and half of 7
        self.assertAlmostEqual(out[0, 0], (5 * 2 + 6 * 2 + 7 * 1) / 5.0)

    def test_predicted_shift_zero_when_matrices_agree(self):
        r, c = np.mgrid[0:50, 0:60].astype(float)
        ref = np.stack([c * 20, r * 20, np.full_like(r, 500.0)], axis=-1)
        m = np.array([[2.0, 0, 0, 5], [0, 2.0, 0, -3], [0, 0, 2.0, 1]])
        inv = np.linalg.inv(np.r_[m, [[0, 0, 0, 1]]])[:3]
        dv, du, mag = ma.predicted_shift_um(ref, 0.5, 0.5, m, inv, 2.4)
        self.assertLess(mag, 1e-9)
        wrong = m.copy()
        wrong[0, 3] += 10  # stored matrix 10 cross voxels off along x
        dv, du, mag = ma.predicted_shift_um(ref, 0.5, 0.5, wrong, inv, 2.4)
        self.assertAlmostEqual(du, 5 * 2.4, places=6)  # 10 cross voxels = 5 ref voxels along u
        self.assertAlmostEqual(dv, 0.0, places=6)


@unittest.skipIf(np is None, "numpy not installed")
class LevelConsistencyTests(unittest.TestCase):
    def test_centre_patch_same_at_levels_with_rounded_sizes(self):
        rng = np.random.default_rng(5)
        H0, W0 = 1001, 1297  # odd sizes: coarser levels round up
        f = np.fft.fft2(rng.normal(size=(H0, W0)))
        ky, kx = np.meshgrid(np.fft.fftfreq(H0), np.fft.fftfreq(W0), indexing="ij")
        img = np.real(np.fft.ifft2(f * np.exp(-(kx ** 2 + ky ** 2) / (2 * 0.05 ** 2))))
        img = (img - img.min()) / (img.max() - img.min()) * 200 + 20

        def pyramid(a, k):
            for _ in range(k):
                h, w = a.shape
                a = np.pad(a, ((0, h % 2), (0, w % 2)), mode="edge")
                a = a.reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2).mean(axis=(1, 3))
            return a

        class Fake:
            pass

        sv = Fake()
        sv.levels = []
        for k in range(3):
            a = pyramid(img, k)
            sv.levels.append({"scale_um": [2.0, 2.0 * 2 ** k, 2.0 * 2 ** k],
                              "zarray": {"shape": [3, a.shape[0], a.shape[1]]}, "arr": a})
        sv.read_layer = lambda k, layer, r0, r1, c0, c1: sv.levels[k]["arr"][r0:r1, c0:c1]
        keep = sv.levels

        def at(level):
            sv.levels = [keep[0]] + ([keep[level]] if level else [])
            try:
                return ma.centre_patch(sv, 0.83, 0.77, size_mm=0.6, out_um=8.0)
            finally:
                sv.levels = keep

        p0, p2 = at(0), at(2)
        (sy, sx), psr = ma.phase_shift(p0, p2)
        self.assertLess(abs(sy) * 8.0, 1.5)
        self.assertLess(abs(sx) * 8.0, 1.5)


class PlanTests(unittest.TestCase):
    @unittest.skipIf(np is None, "numpy not installed")
    def test_plan_groups_by_native_and_cross(self):
        def seg(nat, vols):
            return {"original_volume_id": nat, "data": [
                {"type": "layers-zarr", "origins": [{"path": "S/segments/x/surface-volumes/2um-volume-%s.zarr/" % v}]}
                for v in vols]}
        cat = {"samples": {"S": {"segments": {
            "g%d" % i: seg("11111111111111", ["11111111111111", "22222222222222"]) for i in range(7)}}}}
        cat["samples"]["S"]["segments"]["h"] = seg("33333333333333", ["22222222222222"])
        plan = ma.plan_depth(cat, per_combo=5)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["segments_available"], 7)
        self.assertEqual(len(plan[0]["segments"]), 5)
        self.assertEqual(plan, ma.plan_depth(cat, per_combo=5))


if __name__ == "__main__":
    unittest.main()
