"""AutoPipeline's backends (kit/apbackends.py): the `backends` shorthand, the axis estimators in a fallback order,
shadow comparisons, and the listing and preflight agents read. Fakes only: no villa build, no torch."""

import json
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

import test_autopipe as TA
from test_vc3d_agent import Base

from kit import apbackends, autopipe, surfacepred, vc3d_agent, vc3d_orient

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

ROOT = Path(__file__).resolve().parent.parent


class TestTranslate(unittest.TestCase):
    def test_each_stage_stands_for_ordinary_settings(self):
        t = apbackends.translate
        self.assertEqual(t({"umbilicus": "catalog"}), {"umbilicus": {"source": "catalog"}})
        self.assertEqual(t({"umbilicus": "centrenet"}), {"umbilicus": {"source": "estimate", "estimator": "centrenet"}})
        self.assertEqual(t({"umbilicus": ["catalog", "centrenet", "villa"]}),
                         {"umbilicus": {"source": "auto", "estimator": ["centrenet", "villa"]}})
        self.assertEqual(t({"snap": "ct"}), {"render": {"snap": {"source": "ct"}}})
        self.assertEqual(t({"snap": "off", "repair": "switchfix", "triage": "rowscore", "flatten": "off"}),
                         {"render": {"snap": None}, "qa": {"repair": {"method": "switchfix"}},
                          "triage": {"method": "rowscore"}, "flatten": {"enabled": False}})
        self.assertEqual(t({"ink": ["reader-v2", "d9v2"]}), {"ink": {"models": ["reader-v2", "d9v2"]}})
        self.assertEqual(t({"umbilicus": "catalog", "shadow": {"umbilicus": ["villa", "centrenet"]}}),
                         {"umbilicus": {"source": "catalog", "shadow": ["villa", "centrenet"]}})

    def test_refusals(self):
        for bad, why in (({"umbilicus": ["villa", "catalog"]}, "catalog can only come first"),
                         ({"umbilicus": "magic"}, "no backend magic"), ({"nope": "x"}, "no stage nope"),
                         ({"snap": ["pred", "ct"]}, "takes one backend"), ({"umbilicus": ["villa", "villa"]}, "twice"),
                         ({"shadow": {"trace": ["villa"]}}, "only umbilicus"), ("villa", "is an object")):
            with self.assertRaisesRegex(apbackends.BackendError, why):
                apbackends.translate(bad)

    def test_a_setting_given_both_ways_must_agree(self):
        same = apbackends.apply({"backends": {"snap": "ct"}, "render": {"snap": {"source": "ct", "max_off": 9}}})
        self.assertEqual(same["render"]["snap"], {"source": "ct", "max_off": 9})
        self.assertNotIn("backends", same)
        with self.assertRaisesRegex(apbackends.BackendError, "render.snap.source"):
            apbackends.apply({"backends": {"snap": "ct"}, "render": {"snap": {"source": "pred"}}})
        self.assertIsNone(apbackends.apply(None))

    def test_explicit_villa_refuses_an_enabled_trace_extension(self):
        from test_autopipe_extensions import Doubler
        with mock.patch.dict(autopipe.TRACE_METHODS), mock.patch.dict(autopipe.OPTIONAL):
            autopipe.register_trace_method(Doubler)
            with self.assertRaisesRegex(apbackends.BackendError, "backends sets trace.testdouble"):
                apbackends.apply({"backends": {"trace": "villa"}, "trace": {"testdouble": True}})
            plain = autopipe.make_plan("PHercTest", cat=TA.catalog())
            villa = autopipe.make_plan("PHercTest", {"backends": {"trace": "villa"}}, cat=TA.catalog())
        self.assertEqual(plain["digest"], villa["digest"])
        self.assertNotIn("settings", apbackends.STAGES["trace"]["choices"]["villa"])

    def test_swap_settings_changes_one_stage_and_holds_the_rest(self):
        s = autopipe._merge(autopipe.DEFAULTS, {"render": {"snap": {"source": "pred", "max_off": 9}},
                                                "umbilicus": {"source": "estimate", "estimator": "villa"}})
        a = apbackends.swap_settings(s, "snap", "ct")
        self.assertEqual(a["render"]["snap"], autopipe._merge(autopipe.OPTIONAL["render.snap"], {"source": "ct"}))
        self.assertEqual({k: v for k, v in a.items() if k != "render"}, {k: v for k, v in s.items() if k != "render"})
        b = apbackends.swap_settings(s, "snap", "off")
        self.assertNotIn("snap", b["render"])
        c = apbackends.swap_settings(s, "umbilicus", "catalog")
        self.assertEqual(c["umbilicus"]["source"], "catalog")
        self.assertNotIn("estimator", c["umbilicus"])
        self.assertEqual(apbackends.swap_settings(s, "ink", "d9v2")["ink"]["models"], ["d9v2"])
        self.assertEqual(s["render"]["snap"]["source"], "pred")      # the frozen settings are not touched


class TestEnsembleChoices(unittest.TestCase):
    def test_the_ensemble_stage_lists_its_own_choices_without_an_extension(self):
        # the public AutoPipeline release ships apbackends with no extension that adds an ensemble choice
        with mock.patch.dict(apbackends.ENSEMBLE_EXTENSIONS, clear=True):
            out = apbackends.ensemble_choices()
        self.assertEqual(set(out), {"mean", "rank", "zscore", "off"})

    def test_an_extension_choice_is_listed_and_named_from_its_settings(self):
        entry = {"settings": {"ink": {"models": ["a", "b"], "ensemble": {"method": "zscore", "weights": [2, 1]}}}}
        with mock.patch.dict(apbackends.ENSEMBLE_EXTENSIONS, {"ext": lambda: entry, "absent": lambda: None},
                             clear=True):
            self.assertEqual(set(apbackends.ensemble_choices()), {"mean", "rank", "zscore", "off", "ext"})
            s = {"ink": {"models": ["a", "b"], "ensemble": {"method": "zscore", "weights": [2, 1]}}}
            self.assertEqual(apbackends.ensemble_name(s), "ext")
            s["ink"]["ensemble"] = {"method": "zscore"}
            self.assertEqual(apbackends.ensemble_name(s), "zscore")


class TestPlans(unittest.TestCase):
    def plan(self, settings):
        return autopipe.make_plan("PHercTest", settings, cat=TA.catalog())

    def test_the_shorthand_and_the_settings_it_stands_for_make_the_same_plan(self):
        a = self.plan({"backends": {"umbilicus": "normals", "repair": "switchfix"}})
        b = self.plan({"umbilicus": {"source": "estimate", "estimator": "normals"},
                       "qa": {"repair": {"method": "switchfix"}}})
        self.assertEqual(a["digest"], b["digest"])
        self.assertNotIn("backends", a["settings"])
        # a plan that names no backend keeps the settings and digest it had before backends existed
        plain = self.plan({})
        self.assertNotIn("estimator", plain["settings"]["umbilicus"])
        self.assertNotIn("shadow", plain["settings"]["umbilicus"])

    def test_refusals(self):
        with self.assertRaisesRegex(autopipe.AutoError, "goes with umbilicus.source auto or estimate"):
            self.plan({"umbilicus": {"source": "catalog", "estimator": "villa"}})
        with self.assertRaisesRegex(autopipe.AutoError, "no estimator magic"):
            self.plan({"umbilicus": {"estimator": "magic"}})
        with self.assertRaisesRegex(autopipe.AutoError, "backends sets umbilicus.source"):
            self.plan({"backends": {"umbilicus": "villa"}, "umbilicus": {"source": "catalog"}})
        cat = TA.catalog()
        cat["samples"]["PHercTest"]["volumes"]["V1"]["properties"]["pixel_size_um"] = 2.4
        with self.assertRaisesRegex(autopipe.AutoError, "centrenet takes 8 to 10 um scans"):
            autopipe.make_plan("PHercTest", {"backends": {"umbilicus": "centrenet"}}, cat=cat)

    def test_in_effect_names_each_stages_backend(self):
        p = self.plan({"backends": {"umbilicus": ["catalog", "centrenet", "villa"], "snap": "ct"}})
        s = p["settings"]
        u = apbackends.in_effect("umbilicus", s)
        self.assertEqual((u["name"], u["origin"], u["kind"], u["fallback"]), ("centrenet", "ours", "learned", ["villa"]))
        self.assertEqual(apbackends.in_effect("umbilicus", s, {"source": "catalog"})["origin"], "community")
        self.assertEqual(apbackends.in_effect("render", s)["snap"]["name"], "ct")
        self.assertEqual(apbackends.in_effect("trace", s)["name"], "villa")
        self.assertEqual(apbackends.in_effect("ink", s)["models"][0]["name"], "reader-v2")


class TestListing(Base):
    def test_selected_repair_is_checked_and_command_engines_do_not_require_torch(self):
        settings = json.loads(json.dumps(autopipe.DEFAULTS))
        settings["segment"] = "public-fixture"
        settings["umbilicus"]["source"] = "fixture-axis.json"
        settings["ink"]["where"] = "skip"
        settings["qa"]["repair"] = {"method": "switchfix"}
        plan = {"settings": settings, "resolved": {"sample": "PHercTest"}}
        with mock.patch.object(apbackends, "_has_module", return_value=False):
            result = apbackends.preflight(plan, self.ctx, vc3d_agent)
        self.assertFalse(result["ready"])
        self.assertIn("repair", {r["stage"] for r in result["missing"]})
        settings["qa"].pop("repair")
        settings["ink"].update(where="auto", models=["cpu-command"])
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({"cpu-command": {
            "engine": "command", "command": [sys.executable, "-c", "pass"]}}))
        with mock.patch.object(vc3d_agent, "ink_env", return_value={"torch": False, "python": sys.executable}):
            result = apbackends.preflight(plan, self.ctx, vc3d_agent)
            runner = object.__new__(autopipe.Run)
            runner.s, runner.agent, runner.ctx = settings, vc3d_agent, self.ctx
            self.assertEqual(runner.ink_where(), "local")
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["rows"][0]["where"]["kind"], "external command")
        self.assertEqual(result["ink"]["placement"]["kind"], "per model")
        self.assertNotIn("torch", {n["need"] for n in result["rows"][0]["needs"]})
        (self.home / "models.json").write_text(json.dumps({"reader-v2": {
            "engine": "command", "command": [sys.executable, "-c", "pass"]}}))
        registered = apbackends.availability("ink", "reader-v2", self.ctx, vc3d_agent)
        self.assertEqual((registered["origin"], registered["kind"]), ("registered", "command"))
        self.assertEqual(registered["catalog_reference"]["origin"], "community")

    def test_no_villa_install_is_a_missing_requirement_not_an_exception(self):
        bare = self.context()
        with mock.patch.object(vc3d_agent.vc3d, "find_tools", side_effect=vc3d_agent.vc3d.SetupError("no binaries")):
            result = apbackends.availability("flatten", "villa", bare, vc3d_agent)
        self.assertEqual(result["status"], "missing")
        self.assertIn("VC_BIN", result["needs"][0]["fix"])

    def test_preflight_checks_custom_models_and_reports_missing_files(self):
        checkpoint = self.d / "model.pt"
        spec = {"engine": "torchscript", "checkpoint": str(checkpoint)}
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({"custom-fixture": spec}))
        settings = json.loads(json.dumps(autopipe.DEFAULTS))
        settings["segment"] = "public-fixture"
        settings["umbilicus"]["source"] = "fixture-axis.json"
        settings["ink"].update(models=["custom-fixture"], where="local")
        autopipe.check_models(settings, {"custom-fixture": spec})
        plan = {"settings": settings, "resolved": {"sample": "PHercTest", "volume": "V1"}}
        with mock.patch.object(vc3d_agent, "ink_env", return_value={"torch": True, "python": sys.executable}):
            missing = apbackends.preflight(plan, self.ctx, vc3d_agent)
            self.assertFalse(missing["ready"])
            self.assertEqual(missing["rows"][0]["backend"], "custom-fixture")
            self.assertIn("model:custom-fixture", {x["need"] for x in missing["missing"]})
            checkpoint.write_bytes(b"synthetic checkpoint; preflight checks availability, not inference")
            self.assertTrue(apbackends.preflight(plan, self.ctx, vc3d_agent)["ready"])
            listed = apbackends.listing(self.ctx, vc3d_agent)["stages"]["ink"]["backends"]
            self.assertIn("custom-fixture", listed)
            settings["ink"]["models"] = ["not-registered"]
            self.assertFalse(apbackends.preflight(plan, self.ctx, vc3d_agent)["ready"])

    def test_a_model_registered_under_another_of_its_names_is_found(self):
        """The backends listing and preflight find a registered model by any name the aliases file gives it, as the
        plan check, the runner's ink_where and the ink tool do; a malformed aliases file is a missing need with its
        reason. The names are synthetic."""
        aliases = self.d / "aliases.json"
        aliases.write_text(json.dumps([{"name": "fam-r1", "aliases": ["old.w"], "why": "synthetic"}]))
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({"fam-r1": {
            "engine": "command", "command": [sys.executable, "-c", "pass"]}}))
        settings = json.loads(json.dumps(autopipe.DEFAULTS))
        settings["segment"] = "public-fixture"
        settings["umbilicus"]["source"] = "fixture-axis.json"
        settings["ink"].update(where="auto", models=["old.w"])
        plan = {"settings": settings, "resolved": {"sample": "PHercTest", "volume": "V1"}}
        with mock.patch.object(autopipe.vc3d_catalog, "ALIASES_FILE", aliases), \
                mock.patch.object(vc3d_agent, "ink_env", return_value={"torch": False, "python": sys.executable}):
            got = apbackends.availability("ink", "old.w", self.ctx, vc3d_agent)
            self.assertEqual((got["status"], got["origin"], got["kind"]), ("ready", "registered", "command"))
            self.assertEqual([(n["need"], n["status"]) for n in got["needs"]], [("model:old.w", "ready")])
            self.assertIn("registered as fam-r1", got["needs"][0]["detail"])
            self.assertTrue(apbackends.preflight(plan, self.ctx, vc3d_agent)["ready"])
            aliases.write_text("{not json")
            st, detail, fix = apbackends.need_status("model:old.w", self.ctx, vc3d_agent)
            self.assertEqual(st, "missing")
            self.assertRegex(detail, "model aliases: .* is not a JSON list")
            self.assertEqual(apbackends.availability("ink", "old.w", self.ctx, vc3d_agent)["status"], "missing")
        self.assertEqual(apbackends.need_status("model:old.w", self.ctx, vc3d_agent)[0], "missing")   # no file

    def test_malformed_custom_registration_is_reported_as_missing(self):
        self.home.mkdir(parents=True, exist_ok=True)
        for spec in ([], {"engine": "unknown"}, {"engine": "command", "command": "not-an-argv-list"}):
            with self.subTest(spec=spec):
                (self.home / "models.json").write_text(json.dumps({"custom-fixture": spec}))
                result = apbackends.need_status("model:custom-fixture", self.ctx, vc3d_agent)
                self.assertEqual(result[0], "missing")

    def test_listing_and_preflight_say_what_is_missing_and_where_work_belongs(self):
        ctx = self.context()
        lst = apbackends.listing(ctx, vc3d_agent)
        villa = lst["stages"]["umbilicus"]["backends"]["villa"]
        self.assertEqual(villa["status"], "ready")          # the fake bin has vc_gen_umbilicus
        self.assertEqual(villa["origin"], "community")
        self.assertEqual(lst["stages"]["ink"]["backends"]["reader-v2"]["where"]["gpu"][0], "B300")
        self.assertEqual(lst["compute"]["cpu"]["local_max_minutes"], 10)
        empty = self.d / "nobin"
        empty.mkdir()
        bare = vc3d_agent.Context(env=dict(self.env, VC_BIN=str(empty)))
        v = apbackends.availability("umbilicus", "villa", bare, vc3d_agent)
        self.assertEqual(v["status"], "missing")
        self.assertIn("vc_gen_umbilicus", v["needs"][0]["detail"])
        self.assertTrue(v["needs"][0]["fix"])
        plan = autopipe.make_plan("PHercTest", {"backends": {"umbilicus": ["villa", "normals"]}}, cat=TA.catalog())
        pf = apbackends.preflight(plan, bare, vc3d_agent)
        row = pf["rows"][0]
        self.assertEqual(row["will_use"], "normals" if HAVE_NUMPY else None)
        self.assertFalse(pf["ready"])                       # no tracer in an empty bin
        self.assertIn("trace", {m["stage"] for m in pf["missing"]})


def spiral_grids(folder, centres):
    """xy normal-grid files of a planted spiral per slice: {z: (cx, cy)}."""
    from kit import normalaxis
    (folder / "xy").mkdir(parents=True, exist_ok=True)
    for z, (cx, cy) in centres.items():
        surfacepred.write_grid(folder / "xy" / f"{z:06d}.grid", normalaxis.spiral_lines(cx, cy, r1=700.0),
                               (0, 0, 1600, 1600))
    return folder


class TestFallbackErrors(Base):
    def test_malformed_native_axis_files_are_recorded_and_fall_back(self):
        row = {"volume": "fixture", "voxel_um": 9.0, "shape_zyx": [1500, 100, 100]}
        out = self.d / "axis-output"
        out.mkdir()
        for raw in ('{"control_points": [', '{"control_points": [{"z": 0, "x": "bad", "y": 1}]}',
                    '{"control_points": [{"z": 0, "x": NaN, "y": 1}]}'):
            def run_logged(*args, **kwargs):
                (out / "raw.json").write_text(raw)
                return 0, 0.0
            with self.subTest(raw=raw), \
                    mock.patch.object(autopipe, "fetch_grids", return_value=([0, 500, 1000], [])), \
                    mock.patch.object(vc3d_agent, "run_logged", side_effect=run_logged), \
                    mock.patch.dict(autopipe.AXIS_ESTIMATORS, normals=self.valid_axis):
                result = autopipe.estimate_umbilicus(vc3d_agent, self.ctx, row, "fixture-grids", out,
                                                     estimator=["villa", "normals"])
                self.assertEqual(result["estimator"], "normals")
                self.assertIn("invalid axis output", result["fell_back"][0]["error"])
                with self.assertRaisesRegex(vc3d_agent.ToolError, "invalid axis output"):
                    autopipe.estimate_umbilicus(vc3d_agent, self.ctx, row, "fixture-grids", out,
                                               estimator=["villa"])

    def run_chain(self, estimators):
        out = self.d / "out"
        out.mkdir(exist_ok=True)
        return autopipe.estimate_umbilicus(vc3d_agent, self.ctx, {"voxel_um": 9.0}, None, out,
                                           estimator=estimators)

    @staticmethod
    def valid_axis(*args, **kwargs):
        return [(0, 30, 40), (100, 30, 40), (200, 30, 40)], {}, {}

    def test_missing_numpy_falls_back_and_single_estimator_is_a_tool_error(self):
        from kit import normalaxis
        with mock.patch.object(normalaxis, "_np", side_effect=normalaxis.NormalAxisError("numpy missing")), \
                mock.patch.dict(autopipe.AXIS_ESTIMATORS, villa=self.valid_axis):
            result = self.run_chain(["normals", "villa"])
            self.assertEqual(result["estimator"], "villa")
            self.assertIn("numpy", result["fell_back"][0]["error"])
            with self.assertRaisesRegex(vc3d_agent.ToolError, "numpy"):
                self.run_chain(["normals"])

    def test_invalid_axis_output_falls_back_and_single_estimator_is_a_tool_error(self):
        bad = mock.Mock(side_effect=vc3d_orient.OrientError("no axis points"))
        with mock.patch.dict(autopipe.AXIS_ESTIMATORS, villa=bad, normals=self.valid_axis):
            result = self.run_chain(["villa", "normals"])
            self.assertEqual(result["estimator"], "normals")
            self.assertIn("no axis points", result["fell_back"][0]["error"])
            with self.assertRaisesRegex(vc3d_agent.ToolError, "no axis points"):
                self.run_chain(["villa"])

    def test_axis_backend_frame_metadata_survives_the_shared_writer(self):
        points, provenance, _ = self.valid_axis()
        metadata = {"voxelsize_um": 9.0, "volume": "public-fixture", "volume_width": 100}
        with mock.patch.dict(autopipe.AXIS_ESTIMATORS,
                             villa=lambda *a, **kw: (points, provenance, {"_axis_metadata": metadata})):
            result = self.run_chain(["villa"])
        saved = json.loads(Path(result["umbilicus"]).read_text())
        self.assertEqual(saved["metadata"], {**metadata, "total_points": 3})
        self.assertNotIn("_axis_metadata", result)


@unittest.skipIf(not HAVE_NUMPY, "needs numpy")
class TestEstimators(Base):
    ROW = {"volume": "V1", "voxel_um": 9.0, "shape_zyx": [400, 1600, 1600],
           "url": "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercTest/volumes/V1.zarr/"}

    def grids(self):
        return spiral_grids(self.d / "grids", {z: (800.0 + 0.05 * z, 760.0) for z in range(0, 400, 100)})

    def test_normals_estimates_the_planted_axis_and_says_it_is_ours(self):
        res = self.call("umbilicus", {"grids": str(self.grids()), "voxel_um": 9.0, "shape_zyx": [400, 1600, 1600],
                                      "every": 100, "estimator": ["normals"]})
        self.assertEqual((res["estimator"], res["backend"]["origin"], res["kept"]), ("normals", "ours", 4))
        pts = vc3d_orient.load_umbilicus(res["umbilicus"])
        x, y = vc3d_orient.centre_at(pts, 200)
        self.assertLess(math.hypot(x - 810.0, y - 760.0), 2.0)
        saved = json.loads(Path(res["umbilicus"]).read_text())["kit_autopipe"]
        self.assertEqual(saved["estimator"], "normals")
        self.assertIn("kit normalaxis", saved["method"])

    def test_a_missing_villa_build_falls_back_to_the_next_estimator(self):
        empty = self.d / "nobin"
        empty.mkdir()
        ctx = vc3d_agent.Context(env=dict(self.env, VC_BIN=str(empty)))
        args = {"grids": str(self.grids()), "voxel_um": 9.0, "shape_zyx": [400, 1600, 1600], "every": 100}
        with self.assertRaisesRegex(vc3d_agent.ToolError, "vc_gen_umbilicus is not in"):
            vc3d_agent.call("umbilicus", args, ctx)          # villa alone, as before: the same error
        res = vc3d_agent.call("umbilicus", {**args, "estimator": ["villa", "normals"]}, ctx)
        self.assertEqual(res["estimator"], "normals")
        self.assertEqual(res["fell_back"][0]["estimator"], "villa")
        self.assertIn("vc_gen_umbilicus is not in", res["fell_back"][0]["error"])
        # every estimator failing is one error naming each
        with self.assertRaisesRegex(vc3d_agent.ToolError, "villa: .*centrenet: "):
            vc3d_agent.call("umbilicus", {**args, "estimator": ["villa", "centrenet"]}, ctx)

    def fake_predict(self, offset=0.0):
        script = self.d / "predict.py"
        script.write_text(
            "import json, os, sys\n"
            "a = sys.argv[1:]\n"
            "s, out = a[0], a[a.index('--out') + 1]\n"
            "os.makedirs(out, exist_ok=True)\n"
            "json.dump({'control_points': [{'x': 500 + " + repr(offset) + ", 'y': 600, 'z': z} for z in "
            "range(0, 400, 50)], 'argv': a}, open(os.path.join(out, s + '_umbilicus.json'), 'w'))\n")
        return script

    def centrenet(self, row=None, torch=True, grids_url=None, **kw):
        ctx = self.context(KIT_CENTRENET_PREDICT=self.fake_predict())
        w = {"first": self.d / "first.pt", "zoom": self.d / "zoom.pt"}
        env = {"python": sys.executable, "torch": torch, "cuda": False}
        with mock.patch.object(autopipe, "centrenet_weights", lambda c: w), \
                mock.patch.object(vc3d_agent, "ink_env", lambda c, refresh=False: env):
            return autopipe.estimate_umbilicus(vc3d_agent, ctx, row or self.ROW, grids_url, self.d / "out",
                                               sample="PHercTest", **kw)

    def test_centrenet_runs_the_centre_finder_with_the_scan_and_weights_it_names(self):
        res = self.centrenet(estimator=["centrenet"])
        self.assertEqual((res["estimator"], res["backend"]["kind"], res["device"]), ("centrenet", "learned", "cpu"))
        line = json.loads((self.d / "out" / "centrenet" / "PHercTest_umbilicus.json").read_text())
        argv = line["argv"]
        self.assertEqual(argv[argv.index("--volume") + 1], "PHercTest/volumes/V1.zarr")
        self.assertEqual(argv[argv.index("--first") + 1], str(self.d / "first.pt"))
        saved = json.loads(Path(res["umbilicus"]).read_text())["kit_autopipe"]
        self.assertIn("not on the 13 scrolls", saved["held_out"])
        self.assertEqual(saved["weights"]["first"]["sha256"], apbackends.CENTRENET_WEIGHTS["first"][1])

    def test_centrenet_refusals_fall_back_in_a_list(self):
        with self.assertRaisesRegex(vc3d_agent.ToolError, "needs torch"):
            self.centrenet(torch=False, estimator=["centrenet"])
        with self.assertRaisesRegex(vc3d_agent.ToolError, "takes 8 to 10 um scans"):
            self.centrenet(row={**self.ROW, "voxel_um": 2.4}, estimator=["centrenet"])
        with self.assertRaisesRegex(vc3d_agent.ToolError, "open-data bucket"):
            self.centrenet(row={**self.ROW, "url": "/local/scan.zarr"}, estimator=["centrenet"])
        res = self.centrenet(torch=False, estimator=["centrenet", "normals"], every=100,
                             grids_url=str(self.grids()))
        self.assertEqual(res["estimator"], "normals")
        self.assertIn("needs torch", res["fell_back"][0]["error"])

    def test_bucket_path(self):
        self.assertEqual(autopipe.bucket_path(self.ROW["url"]), "PHercTest/volumes/V1.zarr")
        self.assertIsNone(autopipe.bucket_path("https://example.org/x.zarr"))
        self.assertIsNone(autopipe.bucket_path(None))


@unittest.skipIf(not HAVE_NUMPY, "needs numpy")
class TestShadow(TA.TestRun):
    """umbilicus.shadow in a whole run: the other backends measured against the axis the run uses, recorded only."""

    def test_shadow_backends_are_measured_against_the_axis_the_run_uses(self):
        ext = self.external(slices=range(0, 64, 10))
        umb = {**autopipe.DEFAULTS["umbilicus"], "source": str(self.axis), "every": 10,
               "shadow": ["villa", "catalog"]}
        st, out = self.run_plan(self.plan(external=ext, umbilicus=umb), until="umbilicus")
        self.assertEqual(st["stages"]["umbilicus"]["status"], "done", st["stages"])
        rec = st["stages"]["umbilicus"]["record"]
        self.assertEqual(rec["source"], "file")
        v = rec["shadow"]["villa"]
        # the fake vc_gen_umbilicus answers x = 32 + 0.01 z, y = 30; the run's axis is (64, 64)
        self.assertAlmostEqual(v["voxels"]["median"], math.hypot(64 - 32.3, 64 - 30), delta=1.0)
        self.assertEqual(v["um"]["median"], round(v["voxels"]["median"] * 10.0, 1))
        self.assertIn("no umbilicus", rec["shadow"]["catalog"]["error"])     # recorded, the stage goes on
        self.assertEqual(vc3d_orient.load_umbilicus(str(out / "umbilicus.json"))[0][1:], (TA.AXIS[1], TA.AXIS[0]))


for _name in dir(TA.TestRun):      # TestShadow borrows TestRun's fixtures, not its tests
    if _name.startswith("test_"):
        setattr(TestShadow, _name, None)


if __name__ == "__main__":
    unittest.main()
