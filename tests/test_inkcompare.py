"""Ink Lens's model comparison (spaces/ink-lens: zoo.py, runners.py, compare.py, tools/gallery_job.py): the model
registry and its pins, ink-sdk's scale and window rules, the run with stand-in models of every family (controls,
liveness, scores, ensemble, stability, mosaic, record), and parity with ink-sdk where it is installed. numpy only,
except the checks against ink-sdk (skipped without it). No network, no gradio, no real model."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "ink-lens"
for p in (str(SPACE), str(SPACE / "tools"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import zoo  # noqa: E402  (standard library only)

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import ink_sdk  # noqa: F401
    from ink_sdk import battery as sdk_battery
    from ink_sdk import liveness as sdk_liveness
    from ink_sdk.prepare import plan_scale as sdk_plan_scale
    from ink_sdk.registry import get_profile, list_profiles
except ImportError:
    ink_sdk = None

if np is not None:
    import compare  # noqa: E402
    import runners  # noqa: E402


class Zoo(unittest.TestCase):
    def test_every_model_is_well_formed(self):
        names = zoo.models()
        self.assertGreaterEqual(len(names), 11)
        for n in names:
            spec = zoo.get(n)
            self.assertEqual(zoo.check(n, spec), True, n)
            self.assertIn(spec["family"], zoo.FAMILIES)
            for scroll, (status, why, src) in spec["exposure"].items():
                self.assertIn(status, zoo.EXPOSURES, (n, scroll))
                self.assertTrue(why and src, (n, scroll))
                self.assertTrue(zoo.exposure(n, scroll)[2].startswith("http"), (n, scroll))
            w = spec["weights"]
            if w["kind"] == "hf":
                self.assertRegex(w["sha256"], r"^[0-9a-f]{64}$", n)
                self.assertRegex(w["revision"], r"^[0-9a-f]{40}$", n)

    def test_both_3d_and_2d_families_are_present(self):
        fams = {zoo.get(n)["family"] for n in zoo.models()}
        self.assertEqual(fams, set(zoo.FAMILIES))

    def test_controls(self):
        self.assertEqual(zoo.control_of("gambiarra-3d"), "moved-sheet")
        self.assertEqual(zoo.control_of("reader-v2"), "reverse-depth")
        self.assertEqual(zoo.control_of("canonical-2um"), "none")

    def test_unknown_exposure_is_said_so(self):
        self.assertEqual(zoo.exposure("reader-v2", "PHercNone")[0], "unknown")

    def test_scale_rule(self):
        self.assertEqual(zoo.scale_plan(2.403, "ink_9um-s42"), ("pool", 4))
        self.assertEqual(zoo.scale_plan(9.366, "ink_9um-s42"), ("native", 1))
        self.assertEqual(zoo.scale_plan(2.403, "hecate-9.6"), ("pool", 4))
        self.assertEqual(zoo.scale_plan(2.403, "hecate-2.4"), ("native", 1))
        self.assertEqual(zoo.scale_plan(2.399, "canonical-2um"), ("native", 1))
        for src, name in ((9.366, "canonical-2um"), (9.366, "hecate-2.4"), (4.8, "ink_9um-s42"),
                          (1.2, "canonical-2um")):
            with self.assertRaises(zoo.ZooError):
                zoo.scale_plan(src, name)

    def test_register_refuses_a_malformed_model(self):
        with self.assertRaises(zoo.ZooError):
            zoo.register("bad", {"title": "x"})

    def test_listing_is_json(self):
        json.dumps(zoo.listing())


@unittest.skipIf(ink_sdk is None, "ink-sdk is not installed")
class AgainstInkSDK(unittest.TestCase):
    def test_pins_match_ink_sdk_profiles(self):
        have = {p.id for p in list_profiles()}
        for n in zoo.models():
            spec = zoo.get(n)
            prof = spec.get("sdk_profile")
            if not prof:
                continue
            self.assertIn(prof, have, n)
            if spec["weights"]["kind"] == "hf":
                p = get_profile(prof)
                self.assertEqual(p.checkpoint.sha256, spec["weights"]["sha256"], n)
                self.assertEqual(p.source.revision, spec["weights"]["revision"], n)

    def test_scale_rule_matches(self):
        for n in zoo.models():
            spec = zoo.get(n)
            if not spec.get("sdk_profile"):
                continue
            p = get_profile(spec["sdk_profile"])
            for src in (2.403, 2.399, 9.366, 8.64, 4.8, 7.91):
                try:
                    sp = sdk_plan_scale(src, p)
                    theirs = (sp.mode, sp.factors_zyx[0] if sp.mode == "pool" else 1)
                except Exception:  # noqa: BLE001
                    theirs = None
                try:
                    ours = zoo.scale_plan(src, n)
                except zoo.ZooError:
                    ours = None
                self.assertEqual(ours, theirs, (n, src))

    @unittest.skipIf(np is None, "numpy")
    def test_windows_match_the_battery(self):
        for n_layers, depth in ((27, 17), (109, 64), (27, 16), (109, 62)):
            for c in (-6, -2, 0, 3, 8):
                for s in (1, 2, 3):
                    ours = runners.window(n_layers, depth, c, s)
                    try:
                        theirs = list(sdk_battery.window(n_layers, depth, c, s))
                    except Exception:  # noqa: BLE001
                        theirs = None
                    self.assertEqual(ours, theirs, (n_layers, depth, c, s))

    @unittest.skipIf(np is None, "numpy")
    def test_local_liveness_matches(self):
        rng = np.random.default_rng(3)
        for m in (rng.random((64, 64)), np.full((64, 64), 0.5) + rng.normal(0, 0.001, (64, 64)),
                  np.zeros((64, 64))):
            ok = np.ones(m.shape, bool)
            self.assertEqual(compare._assess_local(m, ok)["verdict"],
                             sdk_liveness.assess_liveness(m, valid=ok)["verdict"])


# ---------------------------------------------------------------- stand-ins

class StandInVilla9:
    """Reads depth order: high where the window's first half is brighter than its second (like a real reader)."""
    info = {"name": "stand-in villa9"}

    def run(self, volume, windows, orders=("forward", "reverse"), device=None):
        out = {}
        for k, idx in windows.items():
            for o in orders:
                ids = idx if o == "forward" else idx[::-1]
                sub = volume[ids].astype(np.float32)
                d = sub[: len(ids) // 2].mean(0) - sub[len(ids) // 2:].mean(0)
                out[(k, o)] = (1 / (1 + np.exp(-d / 10))).astype(np.float32)
        self.last_patches = len(windows) * len(orders)
        return out


class StandInRender(StandInVilla9):
    """A 2.4 um reader (Hecate 2.4 or canonical): same rule, full resolution; with output_3d a volume too."""

    def run(self, volume, windows, orders=("forward", "reverse"), pixel_um=None, output_3d=False, device=None):
        maps = StandInVilla9.run(self, volume, windows, orders)
        if output_3d:
            vols = {(k, "both"): (volume[idx] // 2).astype(np.uint8) for k, idx in windows.items()}
            return maps, vols
        return maps


def scan24(size=128, layers=109, seed=0):
    """A 2.4 um region: 4 * size px a side; ink strokes where the shallow layers are brighter. Labels on the 9.6 grid."""
    rng = np.random.default_rng(seed)
    big = 4 * size
    v = rng.normal(120, 10, (layers, big, big))
    ink = np.zeros((size, size), bool)
    for r in range(8, size - 8, 20):
        ink[r:r + 6, 8:size - 8] = True
    up = np.kron(ink, np.ones((4, 4), bool))
    v[: layers // 2, up] += 30
    return np.clip(v, 1, 255).astype(np.uint8), (ink, np.ones((size, size), bool))


@unittest.skipIf(np is None, "numpy")
class Run(unittest.TestCase):
    def setUp(self):
        self.vol, self.labels = scan24()
        self.loaded = {"ink_9um-s42": StandInVilla9(), "reader-v2": StandInVilla9(), "hecate-2.4": StandInRender(),
                       "canonical-2um": StandInRender()}

    def run_compare(self, models, **kw):
        return compare.run(self.vol, "2.4", models, labels=self.labels, loaded=self.loaded, draws=40,
                           sample={"id": "test", "scroll": "PHerc0841"}, say=lambda *_: None, **kw)

    def test_every_family_runs_with_its_control(self):
        res, maps, vols = self.run_compare(["ink_9um-s42", "hecate-2.4", "canonical-2um"], output_3d=True)
        for n in ("ink_9um-s42", "hecate-2.4", "canonical-2um"):
            row = res["models"][n]
            self.assertNotIn("error", row, row.get("error"))
            self.assertEqual(maps[(n, "c+0_s1", "forward")].shape, (128, 128))
            sc = row["cells"]["c+0_s1"]["score"]
            self.assertGreater(sc["auc"]["auc"], 0.9, n)          # reads the strokes
            self.assertLess(sc["control"]["auc"], 0.2, n)        # its control is the reverse and fails
            self.assertGreater(sc["gap"], 0.7, n)
            self.assertEqual(row["exposure"]["scroll"], "PHerc0841")
        self.assertIn("reversed by Ink Lens", res["models"]["canonical-2um"]["control"])
        self.assertEqual(res["models"]["hecate-2.4"]["scale"]["map_pool"], 4)
        self.assertEqual(res["models"]["ink_9um-s42"]["scale"]["pool"], 4)
        self.assertEqual(len(res["models"]["hecate-2.4"]["depth_profile"]["c+0_s1"]["ink"]), 64)

    def test_ensemble_stability_and_record(self):
        res, maps, _ = self.run_compare(["ink_9um-s42", "reader-v2", "hecate-2.4"])
        e = res["ensemble"]
        self.assertEqual(len(e["members"]), 3)
        self.assertGreater(e["score"]["auc"]["auc"], 0.9)
        self.assertIn(("ensemble", "c+0_s1", "reverse"), maps)
        self.assertIsNotNone(res["stability"]["0.5"])
        with tempfile.TemporaryDirectory() as d:
            p = compare.record(res, Path(d) / "r.json")
            json.loads(Path(p).read_text())
        self.assertIn("| Ensemble of 3", compare.table(res))

    def test_sweep_keys_are_in_grid_layers(self):
        res, maps, _ = self.run_compare(["ink_9um-s42", "hecate-2.4"], centres=(-2, 0, 2), steps=(1,))
        for n in ("ink_9um-s42", "hecate-2.4"):
            self.assertEqual(sorted(res["models"][n]["windows"]), ["c+0_s1", "c+2_s1", "c-2_s1"], n)
        self.assertEqual(res["models"]["hecate-2.4"]["windows"]["c+2_s1"][32] -
                         res["models"]["hecate-2.4"]["windows"]["c+0_s1"][32], 8)    # 2 grid layers = 8 layers

    def test_one_failure_does_not_hide_the_others(self):
        class Broken:
            def run(self, *a, **k):
                raise RuntimeError("boom")
        self.loaded["reader-v2"] = Broken()
        res, _, _ = self.run_compare(["reader-v2", "ink_9um-s42", "gambiarra-3d"])
        self.assertIn("boom", res["models"]["reader-v2"]["error"])
        self.assertIn("gallery", res["models"]["gambiarra-3d"]["skipped"])
        self.assertTrue(res["models"]["ink_9um-s42"]["alive"])

    def test_native_scan_refuses_render_models(self):
        res, _, _ = compare.run(self.vol[:28, :256, :256], "native", ["hecate-2.4", "ink_9um-s42"], loaded=self.loaded,
                                say=lambda *_: None)
        self.assertIn("skipped", res["models"]["hecate-2.4"])
        self.assertNotIn("skipped", res["models"]["ink_9um-s42"])

    def test_degenerate_map_is_flagged(self):
        flat = np.full((64, 64), 0.5, np.float32)
        self.assertEqual(compare.liveness(flat)["verdict"], "DEGENERATE")

    def test_scores_count_exact_zeros(self):
        ink = np.zeros((128, 128), bool)
        ink[40:80] = True
        m = np.where(ink, 0.9, 0.0).astype(np.float32)      # a model that writes exact zeros on background
        sc = compare.score(m, ink, np.ones_like(ink), draws=0)
        self.assertEqual(sc["auc"]["auc"], 1.0)

    def test_mosaic_and_estimate(self):
        _, maps, _ = self.run_compare(["ink_9um-s42", "reader-v2"])
        img = compare.mosaic(maps, ["ink_9um-s42", "reader-v2"], [("c+0_s1", "forward"), ("c+0_s1", "reverse")],
                             labels=self.labels, thumb=64)
        self.assertEqual(img.dtype, np.uint8)
        self.assertEqual(img.shape[2], 3)
        self.assertGreater(compare.estimate(["hecate-2.4", "reader-v3"], 512, 512),
                           compare.estimate(["reader-v3"], 512, 512))

    def test_plan_refuses_scan_space_models(self):
        with self.assertRaises(compare.CompareError):
            compare.plan("dino-guided-3d", "2.4")


@unittest.skipIf(np is None, "numpy")
class Gallery(unittest.TestCase):
    def test_crop_canvas_offsets_every_lookup(self):
        import gallery_job
        seen = []

        class FakeInk3D:
            @staticmethod
            def canvas(mesh, render=None):
                return "M", (400, 500)

            @staticmethod
            def points(M, r0, r1, c0, c1):
                seen.append((r0, r1, c0, c1))
                return None

        shape = gallery_job.crop_canvas(FakeInk3D, (10, 20, 30, 45), (400, 500))
        self.assertEqual(shape, (40, 60))
        self.assertEqual(FakeInk3D.canvas("mesh")[1], (40, 60))
        FakeInk3D.points("M", 0, 8, 0, 8)
        self.assertEqual(seen[-1], (40, 48, 120, 128))

    def test_ct3d_specs_are_valid_for_kit_ink3d(self):
        import gallery_job
        for n in ("gambiarra-3d", "dino-guided-3d"):
            spec = gallery_job._ct3d_spec(n, "/w/x")
            self.assertIn(spec["engine"], ("gambiarra", "villa-full3d"))
            self.assertIn(spec["map_factor"], (1, 2))


if __name__ == "__main__":
    unittest.main()
