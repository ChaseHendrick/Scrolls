"""Synthetic controlled geometry tests, never target-scroll inference."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import numpy as np
    import scipy
    import tifffile
except ImportError:
    np = None

from kit.surfacefix import correct, prepare
from kit.verify import VerifyError


@unittest.skipIf(np is None, "numpy, scipy and tifffile required")
class SurfaceFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "baseline.tifxyz"
        self.reference = self.root / "reference.tifxyz"
        rows, cols = np.indices((32, 32))
        self.xyz = np.stack([100 + cols * 10, 100 + rows * 10, np.full_like(rows, 50)], -1).astype(float)
        self.xyz[3, 4] = -1
        self._mesh(self.base, self.xyz)
        ref = self.xyz.copy()
        ref[..., 2][ref[..., 2] >= 0] -= 1
        self._mesh(self.reference, ref)
        self.rng = np.random.default_rng(17)
        self.signal = self._noise()

    def _noise(self):
        return self.rng.uniform(.2, .8, (320, 320)).astype("float32")

    def _mesh(self, path, xyz):
        path.mkdir()
        for axis, c in enumerate("xyz"):
            tifffile.imwrite(path / f"{c}.tif", xyz[..., axis].astype("float32"))
        (path / "meta.json").write_text(json.dumps({"scale": [.1, .1], "custom": "preserve this metadata"}))
        (path / "notes.txt").write_text("native mesh sidecar\n")

    def _maps(self, label, forward, artifact=False):
        maps = {}
        for kind in ("forward", "reverse", "shuffle"):
            path = self.root / f"{label}-{kind}.npy"
            np.save(path, forward if kind == "forward" or artifact else self._noise())
            maps[kind] = {"path": str(path), "model": "synthetic-model-digest", "stride": 42}
        return maps

    def _manifest(self, offsets=(1,), artifact=False):
        manifest = prepare(self.base, self.root / "prepared", 10, offsets)
        manifest.update(model="synthetic-model-digest", stride=42)
        manifest["baseline"]["maps"] = self._maps("base", self._noise(), artifact)
        manifest["reference"] = {"mesh": str(self.reference), "maps": self._maps("reference", self.signal, artifact)}
        for i, candidate in enumerate(manifest["candidates"]):
            candidate["maps"] = self._maps(f"candidate{i}", self.signal if candidate["offset_vox"] == 1 else self._noise(), artifact)
        path = self.root / "prepared" / "manifest.json"
        self._save(path, manifest)
        return path, manifest

    def _save(self, path, manifest):
        path.write_text(json.dumps(manifest))

    def _xyz(self, path):
        return np.stack([tifffile.imread(path / f"{c}.tif") for c in "xyz"], -1)

    def test_recovers_known_normal_shift_and_preserves_inputs_holes_metadata(self):
        manifest, _ = self._manifest(offsets=(-1, 1))
        source_bytes = {p.name: p.read_bytes() for p in self.base.iterdir()}
        out = self.root / "corrected"
        report = correct(manifest, out)
        self.assertGreater(report["accepted_regions"], 0)
        self.assertEqual(report["status"], "corrections_require_rerender")
        result = self._xyz(out / "corrected.tifxyz")
        self.assertTrue(np.array_equal(result[3, 4], self.xyz[3, 4]))
        valid = self.xyz[..., 2] >= 0
        self.assertTrue(np.array_equal(result[..., :2], self.xyz[..., :2]))
        self.assertTrue((result[..., 2][valid] <= self.xyz[..., 2][valid]).all())
        self.assertTrue((result[..., 2][valid] == 49).any())
        self.assertEqual({p.name: p.read_bytes() for p in self.base.iterdir()}, source_bytes)
        self.assertEqual((out / "corrected.tifxyz" / "meta.json").read_bytes(), source_bytes["meta.json"])
        self.assertEqual((out / "corrected.tifxyz" / "notes.txt").read_bytes(), source_bytes["notes.txt"])
        self.assertIn("rerendered and rechecked", report["notice"])
        self.assertEqual(report, json.loads((out / "report.json").read_text()))

    def test_shared_artifact_controls_refuse_correction(self):
        manifest, _ = self._manifest(artifact=True)
        report = correct(manifest, self.root / "out")
        self.assertEqual(report["status"], "no_corrections")
        self.assertEqual(report["accepted_regions"], 0)
        self.assertGreater(report["flagged_regions"], 0)
        self.assertTrue(any("controls agree" in reason for r in report["regions"] for reason in r["reasons"]))
        self.assertTrue(np.array_equal(self._xyz(self.root / "out" / "corrected.tifxyz"), self.xyz))

    def test_healthy_baseline_is_unchanged_and_not_flagged(self):
        path, manifest = self._manifest()
        np.save(manifest["baseline"]["maps"]["forward"]["path"], self.signal)
        report = correct(path, self.root / "out", region_points=16)
        self.assertEqual(report["status"], "unchanged")
        self.assertEqual(report["accepted_regions"], 0)
        self.assertEqual(report["flagged_regions"], 0)
        self.assertTrue(all("winner" not in region for region in report["regions"]))
        self.assertTrue(all("no correction needed" in region["reasons"][0] for region in report["regions"]))
        self.assertTrue(np.array_equal(self._xyz(self.root / "out" / "corrected.tifxyz"), self.xyz))

    def test_nonvarying_negative_control_refuses_correction(self):
        path, manifest = self._manifest()
        np.save(manifest["baseline"]["maps"]["reverse"]["path"], np.ones((320, 320), dtype="float32"))
        report = correct(path, self.root / "out")
        self.assertEqual(report["accepted_regions"], 0)
        self.assertTrue(any("inadequate baseline negative controls" in r["reasons"] for r in report["regions"]))

    def test_control_contaminated_baseline_stays_flagged_without_usable_candidate(self):
        path, manifest = self._manifest(artifact=True)
        for spec in manifest["baseline"]["maps"].values():
            np.save(spec["path"], self.signal)
        for spec in manifest["candidates"][0]["maps"].values():
            np.save(spec["path"], np.ones((320, 320), dtype="float32"))
        report = correct(path, self.root / "out", region_points=16)
        self.assertEqual(report["status"], "no_corrections")
        self.assertEqual(report["accepted_regions"], 0)
        self.assertTrue(all(region["flagged"] for region in report["regions"]))
        self.assertTrue(any("baseline fails negative-control margin" in r["reasons"]
                            and "no candidate with usable selection variation" in r["reasons"]
                            for r in report["regions"]))

    def test_winner_rejected_on_held_back_without_trying_runner_up(self):
        path, manifest = self._manifest(offsets=(1, -1))
        bad = self.signal.copy()
        # The selected candidate reverses contrast around every held-back row.
        for row in range(1, 32, 2):
            band = slice(max(0, row * 10 - 4), row * 10 + 5)
            bad[band] = 1 - self.signal[band]
        np.save(manifest["candidates"][0]["maps"]["forward"]["path"], bad)
        good_but_second = .5 * self.signal + .5 * self._noise()
        np.save(manifest["candidates"][1]["maps"]["forward"]["path"], good_but_second)
        report = correct(path, self.root / "out")
        self.assertEqual(report["accepted_regions"], 0)
        winners = [r["winner"] for r in report["regions"] if "winner" in r]
        self.assertTrue(winners)
        self.assertTrue(all(w["offset_vox"] == 1 for w in winners))

    def test_no_reference_coverage_flags_without_geometry_change(self):
        path, manifest = self._manifest()
        ref = self._xyz(self.reference)
        ref[..., 2][ref[..., 2] >= 0] += 100
        for axis, c in enumerate("xyz"):
            tifffile.imwrite(self.reference / f"{c}.tif", ref[..., axis])
        report = correct(path, self.root / "out")
        self.assertEqual(report["accepted_regions"], 0)
        self.assertTrue(all("coverage" in r["reasons"][0] for r in report["regions"]))
        self.assertTrue(np.array_equal(self._xyz(self.root / "out" / "corrected.tifxyz"), self.xyz))

    def test_missing_control_and_mixed_stride_rejected(self):
        path, manifest = self._manifest()
        del manifest["candidates"][0]["maps"]["shuffle"]
        self._save(path, manifest)
        with self.assertRaisesRegex(VerifyError, "shuffle"):
            correct(path, self.root / "out")
        manifest["candidates"][0]["maps"]["shuffle"] = manifest["reference"]["maps"]["shuffle"].copy()
        manifest["candidates"][0]["maps"]["shuffle"]["stride"] = 64
        self._save(path, manifest)
        with self.assertRaisesRegex(VerifyError, "stride"):
            correct(path, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_invalid_map_nan_and_wrong_shape_rejected(self):
        path, manifest = self._manifest()
        target = manifest["baseline"]["maps"]["forward"]["path"]
        for array in (np.full((320, 320), np.nan), np.ones((12, 12))):
            np.save(target, array)
            with self.assertRaisesRegex(VerifyError, "full-surface map"):
                correct(path, self.root / "out")

    def test_prepare_rejects_invalid_offsets_and_overlap(self):
        for offsets in ((1, 1), (float("nan"),), (0,), (6,)):
            with self.assertRaises(VerifyError):
                prepare(self.base, self.root / "prepared", 10, offsets)
        with self.assertRaisesRegex(VerifyError, "overlap"):
            prepare(self.base, self.base / "nested", 10, (1,))
        with self.assertRaisesRegex(VerifyError, "already exists"):
            prepare(self.base, self.base, 10, (1,))
        self.assertFalse((self.root / "prepared").exists())

    def test_changed_candidate_hash_rejected(self):
        path, manifest = self._manifest()
        candidate = path.parent / manifest["candidates"][0]["mesh"]
        (candidate / "notes.txt").write_text("changed")
        with self.assertRaisesRegex(VerifyError, "hashes"):
            correct(path, self.root / "out")

    def test_same_reference_mesh_and_apply_output_overlap_rejected(self):
        path, manifest = self._manifest()
        with self.assertRaisesRegex(VerifyError, "overlap"):
            correct(path, self.base / "nested")
        manifest["reference"]["mesh"] = str(self.base)
        self._save(path, manifest)
        with self.assertRaisesRegex(VerifyError, "separate trace"):
            correct(path, self.root / "out")

    def test_candidate_tangential_change_rejected_even_with_updated_hash(self):
        from kit.surfacefix import _hashes
        path, manifest = self._manifest()
        candidate = path.parent / manifest["candidates"][0]["mesh"]
        x = tifffile.imread(candidate / "x.tif")
        x[10, 10] += 1
        tifffile.imwrite(candidate / "x.tif", x)
        manifest["candidates"][0]["hashes"] = _hashes(candidate)
        self._save(path, manifest)
        with self.assertRaisesRegex(VerifyError, "normal offset"):
            correct(path, self.root / "out")

    def test_offset_boundary_above_limit_refused(self):
        path, manifest = self._manifest()
        partly_good = self.signal.copy()
        partly_good[:, 160:] = self._noise()[:, 160:]
        np.save(manifest["candidates"][0]["maps"]["forward"]["path"], partly_good)
        report = correct(path, self.root / "out", max_step_vox=.5)
        self.assertEqual(report["accepted_regions"], 0)
        self.assertTrue(any("discontinuity" in reason for r in report["regions"] for reason in r["reasons"]))

    def test_invalid_offset_leaves_no_partial_output(self):
        low = self.xyz.copy()
        low[..., 2][low[..., 2] >= 0] = .5
        source = self.root / "near-edge.tifxyz"
        self._mesh(source, low)
        with self.assertRaisesRegex(VerifyError, "negative"):
            prepare(source, self.root / "prepared", 10, (-1, 1))
        self.assertFalse((self.root / "prepared").exists())

    def test_large_coordinate_angled_normal_roundoff(self):
        from kit.surfacefix import _geometry, _mesh, _normals, _roundoff
        rows, cols = np.indices((32, 32))
        angled = np.stack([60000 + cols * 10, 60000 + rows * 10,
                            50000 + cols * 3 + rows * 2], -1).astype("float32")
        source = self.root / "large.tifxyz"
        self._mesh(source, angled)
        manifest = prepare(source, self.root / "prepared", 10, (1,))
        base = _mesh(source)
        candidate = _mesh(self.root / "prepared" / manifest["candidates"][0]["mesh"])
        normals, supported = _normals(base)
        _geometry(base, candidate, 1, 10, 50, normals, supported)
        self.assertGreater(_roundoff(base), .001)

    def test_native_triangle_jacobian_catches_local_fold(self):
        from kit.surfacefix import _mesh, _unfolded
        base = _mesh(self.base)
        folded = self.xyz.copy()
        folded[10, 10] = self.xyz[10, 12]
        self.assertFalse(_unfolded(base, dict(base, xyz=folded)))

    def test_anisotropic_xy_scale_and_exact_native_map_registration(self):
        from kit.surfacefix import _mesh, _sample_native
        (self.base / "meta.json").write_text(json.dumps({"scale": [.1, .2]}))
        mesh = _mesh(self.base)
        self.assertEqual(mesh["map_shape"], (160, 320))
        rows, cols = np.indices(mesh["map_shape"], dtype=float)
        samples, coverage = _sample_native(rows + 10 * cols, np.ones(mesh["map_shape"], dtype=bool), mesh)
        self.assertAlmostEqual(samples[2, 3], (2 / .2 - .5) + 10 * (3 / .1 - .5))
        self.assertFalse(coverage[0, 1])
        self.assertFalse(coverage[1, 0])
        self.assertTrue(coverage[2, 3])
        partial = np.ones(mesh["map_shape"], dtype=bool)
        partial[9, 29] = False
        _, coverage = _sample_native(rows + 10 * cols, partial, mesh)
        self.assertFalse(coverage[2, 3])

    def test_invalid_config_and_missing_scale(self):
        path, _ = self._manifest()
        for kwargs in ({"min_corr": float("nan")}, {"min_gain": -1}, {"max_step_vox": 0},
                       {"region_points": 1}, {"min_points": True}):
            with self.assertRaises(VerifyError):
                correct(path, self.root / "out", **kwargs)
        (self.base / "meta.json").write_text("{}")
        with self.assertRaisesRegex(VerifyError, "scale"):
            prepare(self.base, self.root / "other", 10, (1,))

    def test_fractional_geometry_matches_recover_shifted_dense_maps_and_legacy_abstains(self):
        path, manifest = self._manifest()
        ref = self._xyz(self.reference)
        ref[ref[..., 2] >= 0, :2] += 5
        for axis, c in enumerate("xyz"):
            tifffile.imwrite(self.reference / f"{c}.tif", ref[..., axis])
        # Reference pixel (r,c) observes source physical position (r+5,c+5).
        # Wrap is outside the interior used in this fixture's correspondences.
        shifted = np.roll(self.signal, (-5, -5), axis=(0, 1))
        np.save(manifest["reference"]["maps"]["forward"]["path"], shifted)
        report = correct(path, self.root / "continuous")
        self.assertEqual(report["schema"], 2)
        self.assertGreater(report["accepted_regions"], 0)
        self.assertGreater(report["correspondence"]["all_maps_covered_points"], 500)
        manifest["schema"] = 1
        self._save(path, manifest)
        legacy = correct(path, self.root / "legacy")
        self.assertEqual(legacy["schema"], 1)
        self.assertNotIn("correspondence", legacy)
        self.assertEqual(legacy["accepted_regions"], 0)
        self.assertTrue(all("coverage" in r["reasons"][0] for r in legacy["regions"]))

    def test_fractional_samples_use_original_dense_hp_not_coarse_native_interpolation(self):
        from scipy.ndimage import map_coordinates
        from kit.surfacefix import _mesh, _sample_native, _sample_projected
        mesh = _mesh(self.reference)
        r, c = np.indices(mesh["map_shape"], dtype=float)
        field = np.sin(r * .7) + np.cos(c * .9)
        covered = np.ones_like(field, dtype=bool)
        uv = np.array([[[10.25, 11.75]]])
        values, valid = _sample_projected(field, covered, mesh, uv)
        position = np.moveaxis(uv / mesh["scale"][::-1] - .5, -1, 0)
        expected = map_coordinates(field, position, order=1, prefilter=False)
        np.testing.assert_allclose(values, expected)
        native, _ = _sample_native(field, covered, mesh)
        coarse = map_coordinates(native, np.moveaxis(uv, -1, 0), order=1, prefilter=False)
        self.assertGreater(abs(float(values[0, 0] - coarse[0, 0])), .1)
        self.assertTrue(valid.all())
        covered[102, 117] = False
        _, valid = _sample_projected(field, covered, mesh, uv)
        self.assertFalse(valid.any())
        _, valid = _sample_projected(field, np.ones_like(covered), mesh, np.array([[[0., 1.]]]))
        self.assertFalse(valid.any())

    def test_schema2_geometry_freezes_before_first_map_record(self):
        from unittest.mock import patch
        from kit import surfacefix
        from kit import _surface_geometry
        path, _ = self._manifest()
        record = surfacefix._record
        with patch.object(_surface_geometry, "project", wraps=_surface_geometry.project) as projection:
            def read_record(*args, **kwargs):
                self.assertEqual(projection.call_count, 1)
                return record(*args, **kwargs)
            with patch.object(surfacefix, "_record", side_effect=read_record):
                report = correct(path, self.root / "out")
        self.assertTrue(report["correspondence"]["geometry_frozen_before_maps"])

    def test_schema2_rejects_unknown_matching_and_bicubic_render_geometry(self):
        path, manifest = self._manifest()
        self.assertEqual(manifest["schema"], 2)
        manifest["render_geometry"]["position_interpolation"] = "smooth"
        self._save(path, manifest)
        with self.assertRaisesRegex(VerifyError, "render_geometry"):
            correct(path, self.root / "out")
        manifest["render_geometry"]["position_interpolation"] = "linear"
        manifest["matching_mode"] = "nearest_native_vertex"
        self._save(path, manifest)
        with self.assertRaisesRegex(VerifyError, "matching_mode"):
            correct(path, self.root / "out")

    def test_cli_prepare_and_apply(self):
        dest = self.root / "prepared"
        proc = subprocess.run([sys.executable, "-m", "kit", "surfacefix", "prepare", str(self.base), str(dest),
                               "--voxel-um", "10", "--offsets", "1"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        path = dest / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest.update(model="synthetic-model-digest", stride=42)
        manifest["baseline"]["maps"] = self._maps("base", self._noise())
        manifest["reference"] = {"mesh": str(self.reference), "maps": self._maps("reference", self.signal)}
        manifest["candidates"][0]["maps"] = self._maps("candidate", self.signal)
        self._save(path, manifest)
        proc = subprocess.run([sys.executable, "-m", "kit", "surfacefix", "apply", str(path), str(self.root / "out")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads((self.root / "out" / "report.json").read_text())
        self.assertGreater(report["accepted_regions"], 0)


if __name__ == "__main__":
    unittest.main()
