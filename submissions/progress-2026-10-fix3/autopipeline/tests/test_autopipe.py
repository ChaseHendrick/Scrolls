"""The automatic pipeline (kit/autopipe.py): its pure parts, its four agent tools on fake volumes and fake VC3D
tools, and whole runs end to end on fakes, with the checks that must be able to fail made to fail."""

import hashlib
import json
import math
import os
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_vc3d_agent import Base
from test_vc3d_catalog import CATALOG
import vc3d_fakes as fakes

from kit import autopipe, surfacepred, surfbench, vc3d_agent, vc3d_orient

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
try:
    import numpy  # noqa: F401,F811
    import tifffile  # noqa: F401
    HAVE_TIFF = True        # kit rowscore on TIFF maps (triage)
except ImportError:
    HAVE_TIFF = False
try:
    import numpy as np
    import scipy.spatial  # noqa: F401
    import tifffile  # noqa: F401
    import zarr
    HAVE_LABELXFER = True
except ImportError:
    HAVE_LABELXFER = False

ROOT = Path(__file__).resolve().parent.parent
AXIS = (64.0, 64.0)        # x, y of the fake scroll's axis
FALLBACK = {"fallback": "unturned"}     # ink.orient on, a trace whose turn fails inked as rendered
RADIUS = 40.0              # the fake sheet's distance from it (the orientation vote skips the 20 voxels nearest
SHAPE = [64, 128, 128]     # the axis)


def cylinder_pred(z, y, x):
    """A surface prediction: one sheet, a cylinder of radius 40 around the axis."""
    return 200 if abs(math.hypot(x - AXIS[0], y - AXIS[1]) - RADIUS) <= 1.0 else 0


def cylinder_ct(z, y, x):
    """CT of the same sheet (papyrus 180 over air 40), with nothing scanned (0) where x >= 80."""
    if x >= 80:
        return 0
    return 180 if abs(math.hypot(x - AXIS[0], y - AXIS[1]) - RADIUS) <= 2.0 else 40


def catalog():
    """The catalog tests' synthetic catalog, with V1's prediction and normal grids typed as the published catalog
    types them (surface-prediction-zarr, normal-grids)."""
    cat = json.loads(json.dumps(CATALOG))
    v1 = cat["samples"]["PHercTest"]["volumes"]["V1"]["data"]
    v1[1]["type"] = "surface-prediction-zarr"
    v1.append({"type": "normal-grids", "parameters": {"model_id": "M1"},
               "origins": [{"path": "PHercTest/pred/V1-surface.normal-grids/"}]})
    return cat


def scroll(folder):
    """The fake scroll: prediction, CT and a straight axis file."""
    pred = fakes.write_group(folder / "pred.zarr", SHAPE, cylinder_pred)
    ct = fakes.write_group(folder / "ct.zarr", SHAPE, cylinder_ct)
    axis = write_axis(folder / "umbilicus.json", [(0.0, AXIS[1], AXIS[0]), (63.0, AXIS[1], AXIS[0])])
    return pred, ct, axis


def write_axis(path, points):
    path.write_text(json.dumps(autopipe.umbilicus_json(points)))
    return path


def pred_headers(folder, shape, chunk=64, levels=2, meta=True, run=None, short_level=None):
    """The header files of a prediction volume as kit surfacepred package writes them (ceil-shaped levels,
    meta.json, run.json when given), with no chunks: every voxel reads as the fill value. short_level writes that
    level one voxel short in x, as villa's round-half-even pyramid can."""
    p = Path(folder)
    p.mkdir(parents=True, exist_ok=True)
    (p / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (p / ".zattrs").write_text(json.dumps({"multiscales": [{
        "axes": [{"name": a, "type": "space"} for a in "zyx"], "version": "0.4", "name": "/",
        "datasets": [{"path": str(k), "coordinateTransformations": [{"type": "scale", "scale": [2.0 ** k] * 3}]}
                     for k in range(levels)]}]}))
    for k in range(levels):
        s = surfacepred.ceil_shape(shape, k)
        if k == short_level:
            s[2] -= 1
        (p / str(k)).mkdir(exist_ok=True)
        (p / str(k) / ".zarray").write_text(json.dumps(surfacepred._zarray(s, (chunk,) * 3)))
    if meta:
        write_meta(p, shape)
    if run is not None:
        (p / "run.json").write_text(json.dumps(run))
    return p


def write_meta(folder, shape, **extra):
    (Path(folder) / "meta.json").write_text(json.dumps({
        "type": "vol", "format": "zarr", "slices": shape[0], "height": shape[1], "width": shape[2],
        "voxelsize": 9.362, "min": 0.0, "max": 255.0, **extra}))


def grid_folder(folder, level=0, slices=(), multiscale=False, metadata=True):
    """A vc_gen_normalgrids output folder: metadata.json recording the input level (None leaves it out), and
    empty xy/NNNNNN.grid files for the given slices."""
    g = Path(folder)
    (g / "xy").mkdir(parents=True, exist_ok=True)
    meta = {"spiral-step": 20.0, "grid-step": 64, "sparse-volume": 1}
    if level is not None:
        meta["input-level"] = level
    if multiscale:
        meta = {"format": "normal-grid-multiscale", "version": 1, "min-level": 0, "max-level": 2,
                "source-metadata": meta}
    if metadata:
        (g / "metadata.json").write_text(json.dumps(meta))
    for z in slices:
        (g / "xy" / f"{z:06d}.grid").write_bytes(b"grid")
    return g


class TestPureParts(unittest.TestCase):
    def test_who_stopped_a_trace(self):
        ours = [autopipe.trace_failure(exc=vc3d_agent.ToolError("seed [1.0, 2.0, 3.0] is off the surface prediction "
                                                                 "(value 0, the tracer needs 1)")),
                autopipe.trace_failure(exc=vc3d_agent.ToolError("seed [1, 2, 3] is on air in the CT (x)")),
                autopipe.trace_failure(res={"exit": 0}), autopipe.trace_failure(res={"exit": 1}),
                autopipe.trace_failure(res={"exit": "timeout"})]
        self.assertEqual([f["kind"] for f in ours], ["ours"] * 5)
        self.assertIn("seed check refused it", ours[0]["reason"])
        infra = [autopipe.trace_failure(exc=vc3d_agent.ToolError("chunk fetch failed: connection reset")),
                 autopipe.trace_failure(exc=vc3d_agent.ToolError("seed [1, 2, 3]: HTTP 404 reading the prediction")),
                 autopipe.trace_failure(res={"exit": "cancelled"}),
                 autopipe.trace_failure(res={"exit": "could not start: no such file"}), autopipe.trace_failure(res={})]
        self.assertEqual([f["kind"] for f in infra], ["infrastructure"] * 5)
        self.assertEqual(set(autopipe.FAILURE_KINDS), {"ours", "infrastructure"})

    def test_trace_ids_and_entries(self):
        self.assertEqual([autopipe.trace_sid(0, 0, 1), autopipe.trace_sid(1, 2, 3)], ["t00", "t01-r2"])
        planned = [{"sid": autopipe.trace_sid(i, k, 2), "seed_index": i, "repeat": k} for i in range(2) for k in range(2)]
        state = {"planned_traces": planned, "stages": {"trace": {"status": "done"}, "qa": {"status": "done"},
                                                        "render": {"status": "done"}},
                 "trace_failures": {"t01-r1": {"kind": "ours", "reason": "the tracer exited 1"}},
                 "surfaces": {"t00-r0": {"qa": {"reasons": ["partly seated"]}, "accepted": False},
                              "t00-r1": {"qa": {}, "accepted": True, "render": {"failure": {
                                  "kind": "infrastructure", "reason": "the render tools could not run"}}},
                              "t01-r0": {"qa": {}, "accepted": True, "render": {"zarr": "r.zarr"}}}}
        got = {e["sid"]: e for e in autopipe.trace_entries(state)}
        self.assertEqual(list(got), ["t00-r0", "t00-r1", "t01-r0", "t01-r1"])
        self.assertEqual((got["t00-r0"]["accepted"], got["t00-r0"]["failure"]["stage"], got["t00-r0"]["failure"]["kind"]),
                         (False, "qa", "ours"))
        self.assertEqual((got["t00-r1"]["accepted"], got["t00-r1"]["failure"]["kind"]), (True, "infrastructure"))
        self.assertEqual((got["t01-r0"]["rendered"], got["t01-r0"]["failure"]), (True, None))
        self.assertEqual((got["t01-r1"]["failure"]["stage"], got["t01-r1"]["failure"]["kind"]), ("trace", "ours"))
        # a planned trace with no record: the infrastructure's, whatever the stage says
        state["trace_failures"] = {}
        self.assertEqual(autopipe.trace_entries(state)[3]["failure"]["kind"], "infrastructure")
        self.assertEqual(autopipe.trace_entries({}), [])

    def test_grid_slices(self):
        self.assertEqual(autopipe.grid_slices(2000, 500), [0, 500, 1000, 1500])
        self.assertEqual(autopipe.grid_slices(2000, 500, [600, 1600]), [1000, 1500])
        with self.assertRaises(autopipe.AutoError):
            autopipe.grid_slices(2000, 500, [900, 900])
        with self.assertRaises(autopipe.AutoError):
            autopipe.grid_slices(2000, 0)

    def test_robust_axis_drops_a_planted_outlier_and_keeps_a_clean_axis(self):
        clean = [(z, 30.0 + 0.002 * z, 40.0 + 0.001 * z) for z in range(0, 5000, 250)]
        kept, dropped = autopipe.robust_axis(clean)
        self.assertEqual((len(kept), dropped), (len(clean), []))
        bad = clean[:7] + [(1750, 30.0 + 3.5, 40.0 + 600.0)] + clean[8:]
        kept, dropped = autopipe.robust_axis(bad)
        self.assertEqual([d["z"] for d in dropped], [1750.0])
        self.assertEqual(len(kept), len(clean) - 1)
        kept, dropped = autopipe.robust_axis(bad, max_jump=1000)    # a fixed limit above the jump keeps it
        self.assertEqual(dropped, [])

    def test_axis_distance(self):
        a = [(0, 10.0, 20.0), (100, 10.0, 20.0)]
        self.assertEqual(autopipe.axis_distance(a, a)["max"], 0)
        b = [(0, 13.0, 24.0), (100, 13.0, 24.0)]
        d = autopipe.axis_distance(a, b)
        self.assertEqual((d["n"], d["median"]), (2, 5.0))

    def test_umbilicus_json_reads_back(self):
        pts = [(0.0, 1.0, 2.0), (10.0, 3.0, 4.0)]
        text = json.dumps(autopipe.umbilicus_json(pts, {"method": "test"}))
        self.assertEqual(vc3d_orient.load_umbilicus(text), pts)


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestDistortion(Base):
    def test_isometric_passes_and_stretch_and_shear_fail(self):
        limits = autopipe.DEFAULTS["flatten"]
        iso = fakes.write_tifxyz(self.d / "iso.tifxyz", fakes.plane(32))         # 4 voxels a step, scale 0.25
        d = autopipe.grid_distortion(iso)
        self.assertAlmostEqual(d["stretch_col"]["median"], 1.0, places=4)
        self.assertAlmostEqual(d["shear_deg"]["p95"], 0.0, places=3)
        self.assertAlmostEqual(d["area_ratio"], 1.0, places=4)
        self.assertEqual(autopipe.distortion_passes(d, limits), (True, []))
        wide = fakes.write_tifxyz(self.d / "wide.tifxyz", lambda r, c: (8 + 6 * c, 8 + 4 * r, 32))
        ok, why = autopipe.distortion_passes(autopipe.grid_distortion(wide), limits)
        self.assertFalse(ok)
        self.assertTrue(any("stretch" in w for w in why) and any("area" in w for w in why))
        sheared = fakes.write_tifxyz(self.d / "shear.tifxyz", lambda r, c: (8 + 4 * c + 2 * r, 8 + 4 * r, 32))
        ok, why = autopipe.distortion_passes(autopipe.grid_distortion(sheared), limits)
        self.assertFalse(ok)
        self.assertTrue(any("shear" in w for w in why))

    def test_an_oversized_grid_is_refused_before_it_is_decoded(self):
        # the size comes from x.tif's header: no grid is decoded (three float64 copies, 24 bytes a vertex) first
        iso = fakes.write_tifxyz(self.d / "iso.tifxyz", fakes.plane(32), rows=9, cols=12)
        with mock.patch.object(autopipe.vc3d_io, "read_tiff", side_effect=AssertionError("decoded a grid")):
            with self.assertRaisesRegex(autopipe.AutoError, r"9 x 12 grid is over 107 vertices"):
                autopipe.grid_distortion(iso, max_vertices=107)
        self.assertEqual(autopipe.grid_distortion(iso, max_vertices=108)["grid"], [9, 12])
        # a truncated x.tif is still the format error the distortion tool reports, not a struct.error
        (iso / "x.tif").write_bytes((iso / "x.tif").read_bytes()[:12])
        with self.assertRaisesRegex(vc3d_agent.ToolError, "truncated TIFF"):
            self.call("distortion", {"surface": str(iso)})

    def test_tool(self):
        iso = fakes.write_tifxyz(self.d / "iso.tifxyz", fakes.plane(32))
        res = self.call("distortion", {"surface": str(iso)})
        self.assertTrue(res["passes"])
        res = self.call("distortion", {"surface": str(iso), "limits": {"max_area_ratio": 0.9}})
        self.assertFalse(res["passes"])
        no_scale = fakes.write_tifxyz(self.d / "noscale.tifxyz", fakes.plane(32), meta={"scale": None})
        with self.assertRaisesRegex(vc3d_agent.ToolError, "no grid scale"):
            self.call("distortion", {"surface": str(no_scale)})


class TestPlan(unittest.TestCase):
    def test_resolves_and_freezes(self):
        plan = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        r = plan["resolved"]
        self.assertEqual((r["volume"], r["voxel_um"], r["prediction_model"]), ("V1", 9.362, "M1"))
        self.assertIsNone(r["catalog_umbilicus"])
        self.assertTrue(r["normal_grids_url"].endswith("PHercTest/pred/V1-surface.normal-grids/"))
        self.assertEqual(autopipe.check_plan(plan), plan)
        again = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-10T00:00:00Z")
        self.assertEqual(again["digest"], plan["digest"])    # the creation time is not part of what decides
        edited = json.loads(json.dumps(plan))
        edited["settings"]["qa"]["min_valid_fraction"] = 0.1
        with self.assertRaisesRegex(autopipe.AutoError, "edited after it was made"):
            autopipe.check_plan(edited)

    def test_reserved_segments_are_never_planned_or_run(self):
        # the report surface by its key or its segment id, and a segment this checkout reserves in its reserve file,
        # refused before any catalog; the file is read when a plan is made, so a missing one leaves the built-in list
        with tempfile.TemporaryDirectory() as tmp:
            extra = Path(tmp) / "reserved.json"
            extra.write_text(json.dumps([{"sample": "PHercTest", "segment": "s01", "why": "kept for one final"}]))
            with mock.patch.object(autopipe, "RESERVED_FILE", extra):
                for sample, seg in (("PHerc0841", "0841-ag405"), ("PHerc0841", "auto_grown_20260220174252405"),
                                    ("PHercTest", "s01")):
                    with self.subTest(seg=seg), self.assertRaisesRegex(
                            autopipe.AutoError, f"segment {seg} stays unscored here: it is reserved"):
                        autopipe.make_plan(sample, {"segment": seg}, cat={})
                self.assertIn("kept for one final", autopipe.reserved("PHercTest", "s01"))
                self.assertIsNone(autopipe.reserved("PHerc0841", "0841-w00"))
                self.assertIsNone(autopipe.reserved("PHerc0841", "s01"))        # only on its own sample
                for bad in ("{", '{"sample": "PHercTest"}', '[{"sample": "PHercTest", "segment": "s01"}]'):
                    extra.write_text(bad)
                    with self.subTest(bad=bad), self.assertRaisesRegex(autopipe.AutoError, "fix it before planning"):
                        autopipe.make_plan("PHercTest", {"segment": "s02"}, cat={})
            with mock.patch.object(autopipe, "RESERVED_FILE", Path(tmp) / "absent.json"):
                self.assertIsNone(autopipe.reserved("PHercTest", "s01"))
                self.assertIn("report surface", autopipe.reserved("PHerc0841", "0841-ag405"))
        # a plan frozen before the list (as kit 0.1.0 made one) is refused when it runs
        old = autopipe.make_plan("PHercTest", {"segment": "x"}, cat=catalog(), created="2026-10-09T00:00:00Z")
        old = json.loads(json.dumps(old))
        old["settings"]["segment"], old["resolved"]["sample"] = "0841-ag405", "PHerc0841"
        old["digest"] = autopipe.digest({k: old[k] for k in ("version", "settings", "resolved")})
        with self.assertRaisesRegex(autopipe.AutoError, "segment 0841-ag405 stays unscored here.*does not run"):
            autopipe.check_plan(old)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(autopipe.AutoError, "stays unscored here"):
            autopipe.Run(None, None, tmp, old)

    def test_model_names_are_checked_against_the_machine(self):
        def plan(models, registered, where="auto"):
            return autopipe.make_plan("PHercTest", {"ink": {"models": models, "where": where}}, cat=catalog(),
                                      models=registered)
        self.assertEqual(plan(["ink_9um-seed42", "reader-v2"], {})["settings"]["ink"]["models"],
                         ["ink_9um-seed42", "reader-v2"])                   # fetchable: fine with none registered
        self.assertEqual(plan(["mine"], {"mine": {"engine": "villa"}})["settings"]["ink"]["models"], ["mine"])
        with self.assertRaisesRegex(autopipe.AutoError, "ink_9um-seed24 is neither a model kit can fetch .*"
                                                        "ink_9um-seed42.* check the spelling"):
            plan(["ink_9um-seed42", "ink_9um-seed24"], {"mine": {}})
        with self.assertRaisesRegex(autopipe.AutoError, "ink.models is a list of model names"):
            plan([], {})
        # not checked with no machine to ask (None), nor when no model runs
        self.assertEqual(plan(["fake"], None)["settings"]["ink"]["models"], ["fake"])
        self.assertEqual(plan(["fake"], {}, where="skip")["settings"]["ink"]["models"], ["fake"])
        # the digest is the same whichever way the names were checked
        self.assertEqual(plan(["mine"], {"mine": {}})["digest"], plan(["mine"], None)["digest"])

    def test_refusals(self):
        def plan(settings, sample="PHercTest"):
            return autopipe.make_plan(sample, settings, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "needs experiment"):
            plan({"purpose": "target"})
        with self.assertRaisesRegex(autopipe.AutoError, "purpose target only"):
            plan({"experiment": "x"})
        with self.assertRaisesRegex(autopipe.AutoError, "reverse-depth control"):
            plan({"ink": {"variants": ["f"]}})
        with self.assertRaisesRegex(autopipe.AutoError, "qa.windaudit is one of"):
            plan({"qa": {"windaudit": True}})
        with self.assertRaisesRegex(autopipe.AutoError, "qa.published is one of"):
            plan({"qa": {"published": "skip"}})
        with self.assertRaisesRegex(autopipe.AutoError, "unknown plan setting qa.windowz"):
            plan({"qa": {"windowz": 3}})
        with self.assertRaisesRegex(autopipe.AutoError, "is on PHerc0841"):
            plan({"segment": "0841-w00"})
        with self.assertRaisesRegex(autopipe.AutoError, "no volumes in the catalog"):
            plan({}, sample="PHercOther")
        with self.assertRaisesRegex(autopipe.AutoError, "no scan with a published surface prediction"):
            autopipe.pick_volume(CATALOG, "PHercTest")
        with self.assertRaisesRegex(autopipe.AutoError, "trace.normal_grids is one of"):
            plan({"trace": {"normal_grids": True}})
        with self.assertRaisesRegex(autopipe.AutoError, "seeds.points is a list"):
            plan({"seeds": {"points": [[1, 2]]}})
        with self.assertRaisesRegex(autopipe.AutoError, "trace.params is an object"):
            plan({"trace": {"params": 3}})
        self.assertEqual(plan({"trace": {"params": {"z_min": 5, "anything": [1]}}})["settings"]["trace"]["params"],
                         {"z_min": 5, "anything": [1]})
        self.assertEqual(plan({"volume": "V2", "segment": "x"})["resolved"]["catalog_umbilicus"],
                         "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercTest/representations/"
                         "umbilicus/V2-umbilicus.json")

    def test_a_prediction_on_a_coarser_level_is_refused_and_its_grids_never_mixed(self):
        cat = catalog()
        data = cat["samples"]["PHercTest"]["volumes"]["V1"]["data"]
        data[1].setdefault("parameters", {})["level"] = 2
        with self.assertRaisesRegex(autopipe.AutoError, "level 2 of the scan"):
            autopipe.make_plan("PHercTest", cat=cat)
        data[1]["parameters"]["level"] = 0
        data[-1]["parameters"]["level"] = 2             # grids made on level 2: not the level-0 prediction's
        plan = autopipe.make_plan("PHercTest", cat=cat)
        self.assertEqual((plan["resolved"]["prediction_level"], plan["resolved"]["normal_grids_url"]), (0, None))
        with self.assertRaisesRegex(autopipe.AutoError, "publishes no normal grids"):
            autopipe.make_plan("PHercTest", {"trace": {"normal_grids": "required"}}, cat=cat)
        data[-1]["parameters"]["level"] = 0
        plan = autopipe.make_plan("PHercTest", {"trace": {"normal_grids": "required"}}, cat=cat)
        self.assertEqual(plan["resolved"]["normal_grids_model"], "M1")

    def test_traces_in_the_frame_of_the_published_windings_get_the_benchmark_rule(self):
        with mock.patch.object(surfbench, "SAMPLE", "PHercTest"), mock.patch.object(surfbench, "VOLUME", "V1"):
            plan = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
            self.assertEqual(plan["resolved"]["winding_bench"]["rule_digest"], surfbench.RULE_DIGEST)
            seg = autopipe.make_plan("PHercTest", {"segment": "x"}, cat=catalog())
            self.assertNotIn("winding_bench", seg["resolved"])     # a published segment is not a trace
        other = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertNotIn("winding_bench", other["resolved"])        # other scans keep the digest they had
        self.assertNotEqual(plan["digest"], other["digest"])

    def test_picks_the_scan_nearest_9um_with_a_prediction(self):
        self.assertEqual(autopipe.pick_volume(catalog(), "PHercTest")["volume"], "V1")
        with self.assertRaisesRegex(autopipe.AutoError, "no volume V9"):
            autopipe.pick_volume(catalog(), "PHercTest", "V9")

    def test_optional_settings_are_absent_unless_asked_for(self):
        base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertNotIn("trim", base["settings"]["render"])
        self.assertNotIn("external_prediction", base["settings"])
        off = autopipe.make_plan("PHercTest", {"external_prediction": None, "render": {"trim": None}}, cat=catalog())
        self.assertEqual(off["digest"], base["digest"])                 # null leaves a setting out: same plan
        self.assertEqual(autopipe.make_plan("PHercTest", {"render": {"trim": False}}, cat=catalog())["digest"],
                         base["digest"])
        on = autopipe.make_plan("PHercTest", {"render": {"trim": True}}, cat=catalog())
        self.assertEqual(on["settings"]["render"]["trim"], autopipe.OPTIONAL["render.trim"])
        self.assertNotEqual(on["digest"], base["digest"])               # the thresholds used enter the digest
        mine = autopipe.make_plan("PHercTest", {"render": {"trim": {"min_area_share": 0.8}}}, cat=catalog())
        self.assertEqual(mine["settings"]["render"]["trim"], {**autopipe.OPTIONAL["render.trim"], "min_area_share": 0.8})
        self.assertNotEqual(mine["digest"], on["digest"])
        # merging twice (a plan's settings over the defaults again) keeps or drops it the same way
        twice = autopipe._merge(on["settings"], {"render": {"trim": {"dilate": 3}}})
        self.assertEqual(twice["render"]["trim"]["dilate"], 3)
        self.assertNotIn("trim", autopipe._merge(on["settings"], {"render": {"trim": None}})["render"])

    def test_trace_repeats_is_absent_unless_asked_for_and_a_small_whole_number(self):
        base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertNotIn("repeats", base["settings"]["trace"])
        self.assertEqual(autopipe.make_plan("PHercTest", {"trace": {"repeats": None}}, cat=catalog(),
                                            created="2026-10-09T00:00:00Z")["digest"], base["digest"])
        three = autopipe.make_plan("PHercTest", {"trace": {"repeats": 3}}, cat=catalog())
        self.assertEqual(three["settings"]["trace"]["repeats"], 3)
        self.assertNotEqual(three["digest"], base["digest"])
        for bad in (0, autopipe.MAX_REPEATS + 1, True, 2.5, "3"):
            with self.assertRaisesRegex(autopipe.AutoError, "trace.repeats is a whole number"):
                autopipe.make_plan("PHercTest", {"trace": {"repeats": bad}}, cat=catalog())

    def test_strict_is_absent_unless_asked_for_and_takes_true_or_false(self):
        base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertNotIn("strict", base["settings"])          # plans without it keep their digest and their rule
        self.assertEqual(autopipe.make_plan("PHercTest", {"strict": None}, cat=catalog())["digest"], base["digest"])
        on = autopipe.make_plan("PHercTest", {"strict": True}, cat=catalog())
        self.assertEqual(on["settings"]["strict"], {"windaudit_unfit": True, "render_distortion": True})
        self.assertNotEqual(on["digest"], base["digest"])
        one = autopipe.make_plan("PHercTest", {"strict": {"render_distortion": False}}, cat=catalog())
        self.assertEqual(one["settings"]["strict"], {"windaudit_unfit": True, "render_distortion": False})
        with self.assertRaisesRegex(autopipe.AutoError, "strict.windaudit_unfit is true or false"):
            autopipe.make_plan("PHercTest", {"strict": {"windaudit_unfit": "yes"}}, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "unknown plan setting strict.seating"):
            autopipe.make_plan("PHercTest", {"strict": {"seating": True}}, cat=catalog())

    def test_ink_recipe_settings_are_absent_unless_asked_for(self):
        base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertNotIn("snap", base["settings"]["render"])
        self.assertNotIn("layers", base["settings"]["ink"])
        self.assertNotIn("ensemble", base["settings"]["ink"])
        off = autopipe.make_plan("PHercTest", {"render": {"snap": None}, "ink": {"layers": False, "ensemble": None}},
                                 cat=catalog())
        self.assertEqual(off["digest"], base["digest"])
        snap = autopipe.make_plan("PHercTest", {"render": {"snap": True}}, cat=catalog())
        self.assertEqual(snap["settings"]["render"]["snap"], autopipe.OPTIONAL["render.snap"])
        self.assertNotEqual(snap["digest"], base["digest"])
        sham = autopipe.make_plan("PHercTest", {"render": {"snap": {"sham": True}}}, cat=catalog())
        self.assertTrue(sham["settings"]["render"]["snap"]["sham"])
        self.assertNotEqual(sham["digest"], snap["digest"])          # the sham arm is another plan
        four = [[0, 20], [3, 23], [5, 25], [8, 27]]
        lay = autopipe.make_plan("PHercTest", {"ink": {"layers": {"windows": four}}}, cat=catalog())
        self.assertEqual(lay["settings"]["ink"]["layers"], {"windows": four, "combine": "mean"})
        ens = autopipe.make_plan("PHercTest", {"ink": {"models": ["reader-v2", "d9v2"], "ensemble": True}},
                                 cat=catalog())
        self.assertEqual(ens["settings"]["ink"]["ensemble"], {"method": "mean"})
        self.assertEqual(len({p["digest"] for p in (base, snap, sham, lay, ens)}), 5)

    def test_ink_recipe_refusals(self):
        def plan(**over):
            return autopipe.make_plan("PHercTest", over, cat=catalog())
        for bad, msg in (({"source": "mesh"}, "render.snap.source is pred"),
                         ({"check": "maybe"}, "render.snap.check is one of"),
                         ({"check_reference": "neither"}, "check_reference is snapped or original"),
                         ({"sham": 1}, "render.snap.sham is true or false"),
                         ({"max_off": 0}, "max_off is a whole number"), ({"max_off": 2.5}, "max_off is a whole"),
                         ({"level": -1}, "render.snap.level is a whole number"),
                         ({"threshold": 0}, "render.snap.threshold is a number above 0"),
                         ({"sigma": True}, "render.snap.sigma is a number above 0"),
                         ({"bogus": 1}, "unknown plan setting render.snap.bogus")):
            with self.assertRaisesRegex(autopipe.AutoError, msg):
                plan(render={"snap": bad})
        for bad in ([], [[5, 5]], [[-1, 3]], [[0, 3, 4]], [[0.5, 3]], "0:20", [[0, 3], [0, 3]]):
            with self.assertRaisesRegex(autopipe.AutoError, "ink.layers.windows"):
                plan(ink={"layers": {"windows": bad}})
        with self.assertRaisesRegex(autopipe.AutoError, "ink.layers.combine is one of"):
            plan(ink={"layers": {"combine": "zscore"}})
        with self.assertRaisesRegex(autopipe.AutoError, "plan at least two models"):
            plan(ink={"ensemble": True})
        with self.assertRaisesRegex(autopipe.AutoError, "may not be named ensemble"):
            plan(ink={"models": ["a", "ensemble"], "ensemble": True})
        with self.assertRaisesRegex(autopipe.AutoError, "ink.ensemble.method is one of"):
            plan(ink={"models": ["a", "b"], "ensemble": {"method": "max"}})
        # a snap onto the prediction needs one: a scan without a prediction, planned from a published segment
        cat = catalog()
        cat["samples"]["PHercTest"]["volumes"]["V1"]["data"] = [
            d for d in cat["samples"]["PHercTest"]["volumes"]["V1"]["data"]
            if d.get("type") not in ("surface-prediction-zarr", "normal-grids")]
        seg = {"segment": "S1", "volume": "V1", "render": {"snap": True}}
        ct = autopipe.make_plan("PHercTest", dict(seg, render={"snap": {"source": "ct"}}), cat=cat)
        self.assertIsNone(ct["resolved"]["prediction_url"])
        with self.assertRaisesRegex(autopipe.AutoError, "render.snap with source pred needs a surface prediction"):
            autopipe.make_plan("PHercTest", seg, cat=cat)

    def test_render_trim_refusals(self):
        def plan(trim, **render):
            return autopipe.make_plan("PHercTest", {"render": {"trim": trim, **render}}, cat=catalog())
        for bad in (0, 1.5, True, "half"):
            with self.assertRaisesRegex(autopipe.AutoError, "min_area_share is a share"):
                plan({"min_area_share": bad})
        with self.assertRaisesRegex(autopipe.AutoError, "render.trim.dilate is a whole number"):
            plan({"dilate": -1})
        with self.assertRaisesRegex(autopipe.AutoError, "render.trim.level is a whole number"):
            plan({"level": 1.5})
        with self.assertRaisesRegex(autopipe.AutoError, "unknown plan setting render.trim.bogus"):
            plan({"bogus": 1})
        with self.assertRaisesRegex(autopipe.AutoError, "render.trim is an object"):
            plan("yes")
        with self.assertRaisesRegex(autopipe.AutoError, "needs render.audit and render.max_missing"):
            plan(True, audit=False)
        with self.assertRaisesRegex(autopipe.AutoError, "needs render.audit and render.max_missing"):
            plan(True, max_missing=None)


class TestTransferPlan(unittest.TestCase):
    """score.transfer (kit/labelxfer.py): absent unless asked for, refused when it would score a report surface,
    replace the trace, touch a target run or carry labels from another scan."""

    TEST_SEGMENTS = {
        "test-a": {"sample": "PHercTest", "segment": "a", "volume": "V1", "labels": "PHercTest/segments/a/labels",
                   "crop": [0, 64, 0, 64], "surface_shape": [64, 240], "surface_volume": None},
        "test-b": {"sample": "PHercTest", "segment": "b", "volume": "V2", "labels": "PHercTest/segments/b/labels",
                   "crop": [0, 64, 0, 64], "surface_shape": [64, 240], "surface_volume": None}}

    def plan(self, transfer, **over):
        with mock.patch.dict(autopipe.BENCHMARKS, self.TEST_SEGMENTS):
            return autopipe.make_plan("PHercTest", {"score": {"transfer": transfer}, **over}, cat=catalog(),
                                      created="2026-10-09T00:00:00Z")

    def test_absent_unless_asked_for(self):
        base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertNotIn("transfer", base["settings"]["score"])
        self.assertNotIn("transfer", base["resolved"])
        self.assertNotIn("transfer", autopipe.DEFAULTS["score"])
        self.assertEqual(autopipe.make_plan("PHercTest", {"score": {"transfer": None}}, cat=catalog())["digest"],
                         base["digest"])

    def test_resolves_the_segments_and_enters_the_digest(self):
        plan = self.plan({"segments": ["test-a"], "references": {"test-a": "run"}})
        t = plan["settings"]["score"]["transfer"]
        self.assertEqual({k: t[k] for k in ("max_gap_vox", "max_normal_deg", "min_area_cm2", "displace_mm")},
                         {"max_gap_vox": 4.0, "max_normal_deg": 30.0, "min_area_cm2": 0.25, "displace_mm": 2.0})
        self.assertEqual(t["bootstrap"], {"draws": 2000, "block_px": 107, "seed": 20261009})
        self.assertEqual(plan["resolved"]["transfer"]["test-a"]["surface_shape"], [64, 240])
        base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertNotEqual(plan["digest"], base["digest"])
        tighter = self.plan({"segments": ["test-a"], "references": {"test-a": "run"}, "max_gap_vox": 3.0})
        self.assertNotEqual(tighter["digest"], plan["digest"])
        given = self.plan({"segments": ["test-a"], "references": {"test-a": {"reader-v2": "/maps/a.tif"}}})
        self.assertEqual(given["settings"]["score"]["transfer"]["references"]["test-a"],
                         {"reader-v2": "/maps/a.tif"})

    def test_report_surfaces_on_the_scan_are_resolved_for_their_overlap_only(self):
        report = {"0841-ag405": {"sample": "PHercTest", "segment": "r", "volume": "V1", "labels": "PHercTest/r/l",
                                 "crop": [0, 64, 0, 64], "surface_shape": [64, 240], "surface_volume": None}}
        with mock.patch.dict(autopipe.BENCHMARKS, report):
            plan = self.plan({"segments": ["test-a"]})
            self.assertEqual(plan["resolved"]["report_overlap"], {"0841-ag405": {"segment": "r", "volume": "V1"}})
            self.assertNotIn("labels", plan["resolved"]["report_overlap"]["0841-ag405"])
            base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
            self.assertNotIn("report_overlap", base["resolved"])            # only with score.transfer
        report["0841-ag405"]["volume"] = "V2"                                # another scan: nothing to overlap
        with mock.patch.dict(autopipe.BENCHMARKS, report):
            self.assertNotIn("report_overlap", self.plan({"segments": ["test-a"]})["resolved"])

    def test_refusals(self):
        with self.assertRaisesRegex(autopipe.AutoError, "0841-ag405 stays unscored.*report surface.*never read here"):
            self.plan({"segments": ["0841-ag405"]})
        with self.assertRaisesRegex(autopipe.AutoError, "not a labelled segment kit knows"):
            self.plan({"segments": ["w045"]})
        with self.assertRaisesRegex(autopipe.AutoError, "0841-w00 is on PHerc0841, not PHercTest"):
            self.plan({"segments": ["0841-w00"]})
        with self.assertRaisesRegex(autopipe.AutoError, "labels sit on scan V2, not V1"):
            self.plan({"segments": ["test-b"]})
        with self.assertRaisesRegex(autopipe.AutoError, "segments is a list"):
            self.plan({"segments": []})
        with self.assertRaisesRegex(autopipe.AutoError, "names a segment twice"):
            self.plan({"segments": ["test-a", "test-a"]})
        with self.assertRaisesRegex(autopipe.AutoError, "scores the run's own traces"):
            self.plan({"segments": ["test-a"]}, segment="a")
        with self.assertRaisesRegex(autopipe.AutoError, "target runs are never scored"):
            self.plan({"segments": ["test-a"]}, purpose="target", experiment="x")
        for k, bad in (("max_gap_vox", 0), ("max_normal_deg", 90), ("max_normal_deg", True), ("min_area_cm2", -1),
                       ("displace_mm", "2"), ("lattice_px", 0), ("lattice_px", 2.5)):
            with self.assertRaisesRegex(autopipe.AutoError, f"score.transfer.{k}"):
                self.plan({"segments": ["test-a"], k: bad})
        with self.assertRaisesRegex(autopipe.AutoError, "bootstrap.draws is a whole number, at least 20"):
            self.plan({"segments": ["test-a"], "bootstrap": {"draws": 10}})
        with self.assertRaisesRegex(autopipe.AutoError, "not in score.transfer.segments"):
            self.plan({"segments": ["test-a"], "references": {"test-b": "run"}})
        with self.assertRaisesRegex(autopipe.AutoError, "for models in ink.models"):
            self.plan({"segments": ["test-a"], "references": {"test-a": {"other-model": "/m.tif"}}})
        with self.assertRaisesRegex(autopipe.AutoError, "unknown plan setting score.transfer.tolerance"):
            self.plan({"segments": ["test-a"], "tolerance": 3})


class TestTrimRule(unittest.TestCase):
    """Run.trim_for_render's decision with the tools stubbed: the trim tool's counts, the areas and the second audit
    are given, so the limits can be put exactly at their edges."""

    class Agent:
        ToolError = vc3d_agent.ToolError

        def __init__(self, area_after, missing=0, on=10):
            self.area_after, self.missing, self.on, self.calls = area_after, missing, on, []

        def call(self, name, args, ctx):
            self.calls.append((name, args))
            if name == "trim":
                return {"out": args["out"], "valid_vertices": 100, "trimmed_vertices": 50, "kept_vertices": 50,
                        "crop": {"exit": 0}, "missing_chunks": 0}
            return {"verdict": "clean" if not self.missing else "defects", "footprint": {"levels": [
                {"chunks_on_surface": self.on, "missing_on_surface": self.missing}]}}

        def tifxyz_stats(self, path):
            return {"area_voxels2": self.area_after if "trims" in Path(path).parts else 100000.0}

    def decide(self, area_after, levels=6, trim=None, **kw):
        import tempfile
        trim = {**autopipe.OPTIONAL["render.trim"], **(trim or {})}
        plan = autopipe.make_plan("PHercTest", {"render": {"trim": trim}}, cat=catalog(),
                                  created="2026-10-09T00:00:00Z")
        agent = self.Agent(area_after, **kw)
        with tempfile.TemporaryDirectory() as tmp:
            run = autopipe.Run(agent, None, tmp, plan)
            run.state["stages"]["acquire"] = {"record": {"volume_levels": [[1, 1, 1]] * levels}}
            rec = run.trim_for_render("t00", Path(tmp) / "flat" / "t00.tifxyz", plan["settings"]["render"]["trim"],
                                      plan["settings"]["render"]["max_missing"])
        return rec, agent

    def test_the_area_share_is_compared_before_it_is_rounded(self):
        rec, agent = self.decide(49999.6)          # 0.499996: rounds to 0.5 for the record, but is under 0.5
        self.assertEqual(rec["area_share"], 0.5)
        self.assertFalse(rec["used"])
        self.assertIn("keeps 50.0% of the area, under render.trim.min_area_share 50%", rec["why"])
        self.assertEqual([c[0] for c in agent.calls], ["trim"])         # no second audit
        rec, agent = self.decide(50000.0)
        self.assertTrue(rec["used"], rec)
        self.assertEqual([c[0] for c in agent.calls], ["trim", "audit"])

    def test_the_second_audit_limit_and_the_level_read(self):
        rec, _ = self.decide(90000.0, missing=1, on=20)                 # 5 %: at render.max_missing, not over it
        self.assertTrue(rec["used"], rec)
        rec, _ = self.decide(90000.0, missing=2, on=20)                 # 10 %
        self.assertFalse(rec["used"])
        self.assertIn("still has 2 of 20 chunks under it missing (10.0%), over render.max_missing 5%", rec["why"])
        rec, _ = self.decide(90000.0, on=0)                             # nothing under it: the share is unknown
        self.assertFalse(rec["used"])
        self.assertIn("share unknown", rec["why"])
        rec, agent = self.decide(90000.0, levels=2, trim={"level": 3, "min_area_share": 0.9})
        self.assertEqual((rec["level"], rec["level_read"], agent.calls[0][1]["level"]), (3, 1, 1))
        self.assertTrue(rec["used"], rec)                               # 0.9 of the area is at the limit


def spiral_surface(path, crush=1.0, turns=2.0, centre=(500.0, 400.0), pitch=20.0, w0=10.0, step=5.0, rows=6):
    """A tifxyz on the spiral r = pitch (w0 + theta / 2 pi) about centre (x, y), theta along the columns (arc step
    about `step` voxels), rows 5 voxels apart in z; crush scales x about the centre (a scroll flattened along x)."""
    th_max = turns * 2 * math.pi
    cols = int(th_max * pitch * (w0 + turns / 2) / step) + 1

    def point(r, c):
        th = th_max * c / (cols - 1)
        rad = pitch * (w0 + th / (2 * math.pi))
        return centre[0] + crush * rad * math.cos(th), centre[1] + rad * math.sin(th), 100.0 + 5 * r
    return fakes.write_tifxyz(path, point, rows=rows, cols=cols, scale=0.2)


class TestQaRule(unittest.TestCase):
    """Run.qa_one's winding-audit and grid-fetch rules with check_surface and the tracer stubbed, on synthetic
    spirals the real winding audit (kit/meshqa.py) reads."""

    class Agent:
        ToolError = vc3d_agent.ToolError

        def __init__(self, grids=None, check=None):
            self.grids, self.check = grids, check

        def call(self, name, args, ctx):
            if name == "check_surface":
                return {"verdict": "ok", "findings": [], "grid": {"valid_fraction": 1.0},
                        "selfcross": {"transverse": 0}, "seating": {"verdict": "seated"}, **(self.check or {})}
            if name == "trace":     # the trace tool's record of the grids it streamed (kit/vc3d_agent.py)
                return {"exit": 0, "surfaces": [{"path": str(Path(args["out"]) / args["name"])}],
                        "normal_grids": self.grids}
            raise AssertionError(f"unexpected tool {name}")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_for(self, qa=None, strict=None, grids=None):
        settings = {"qa": {"validity": False, **(qa or {})}}
        if strict is not None:
            settings["strict"] = strict
        plan = autopipe.make_plan("PHercTest", settings, cat=catalog(), created="2026-10-09T00:00:00Z")
        out = self.d / f"run{len(list(self.d.glob('run*')))}"
        out.mkdir()
        write_axis(out / "umbilicus.json", [(0.0, 400.0, 500.0), (200.0, 400.0, 500.0)])
        return autopipe.Run(self.Agent(grids), None, out, plan)

    def qa(self, surface, **kw):
        return self.run_for(**kw).qa_one("t00", {"surface": str(surface)})

    @unittest.skipUnless(HAVE_NUMPY, "needs numpy")
    def test_a_turn_the_audit_fits_no_pitch_to_is_not_taken_for_a_small_patch(self):
        # Two turns crushed to 70 % along x: meshqa finds no pitch (concentration under 0.4). Before 9 Oct 2026
        # qa recorded this as "too little of a turn" and passed it unaudited, without a word
        crushed = spiral_surface(self.d / "crushed.tifxyz", crush=0.7)
        rec = self.qa(crushed)
        w = rec["windaudit"]
        self.assertEqual((rec["accepted"], w["audited"], w["pitch_fit"]), (True, False, "concentration"))
        self.assertNotIn("too little of a turn", w["why"])
        self.assertIn("strict.windaudit_unfit would reject it", w["why"])
        self.assertEqual(len(rec["warnings"]), 1, rec["warnings"])
        self.assertIn("winding concentration of 0.", rec["warnings"][0])
        rec = self.qa(crushed, strict=True)
        self.assertFalse(rec["accepted"])
        self.assertEqual(len(rec["reasons"]), 1)
        self.assertIn("fitted no pitch to a patch of a turn or more", rec["reasons"][0])
        rec = self.qa(crushed, strict={"windaudit_unfit": False})
        self.assertTrue(rec["accepted"])
        self.assertFalse(self.qa(crushed, qa={"windaudit": "required"})["accepted"])

    @unittest.skipUnless(HAVE_NUMPY, "needs numpy")
    def test_a_small_patch_and_a_clean_turn_are_decided_as_before(self):
        small = spiral_surface(self.d / "small.tifxyz", turns=0.5)
        for strict in (None, True):
            rec = self.qa(small, strict=strict)
            self.assertEqual((rec["accepted"], rec["windaudit"]["pitch_fit"], rec["warnings"]), (True, "span", []))
            self.assertIn("too little of a turn", rec["windaudit"]["why"])
        rec = self.qa(small, qa={"windaudit": "required"})
        self.assertFalse(rec["accepted"])
        self.assertIn("winding audit could not run", rec["reasons"][0])
        whole = spiral_surface(self.d / "whole.tifxyz")             # the same two turns uncrushed: audited, clean
        rec = self.qa(whole, strict=True)
        self.assertEqual((rec["accepted"], rec["warnings"]), (True, []))
        self.assertFalse(rec["windaudit"]["gate"]["local_failed"])

    @unittest.skipUnless(HAVE_NUMPY, "needs numpy")
    def test_the_pitch_the_audit_used_is_on_record(self):
        whole = spiral_surface(self.d / "whole.tifxyz")             # pitch 20 about the plan's axis
        p = self.qa(whole)["windaudit"]["pitch"]
        self.assertEqual(p["source"], "auto (grid)")
        self.assertAlmostEqual(p["value"], 20.0, delta=0.05)
        self.assertGreater(p["concentration"], 0.99)
        self.assertAlmostEqual(p["span_turns"], 2.0, places=2)
        self.assertEqual(p["handedness"], 1)
        # The same spiral 20 voxels off the axis: meshqa fits a wrong pitch at a concentration it accepts, and the
        # audit passes with nothing said. Only the record shows it
        off = spiral_surface(self.d / "off.tifxyz", centre=(480.0, 400.0))
        rec = self.qa(off, strict=True)
        p = rec["windaudit"]["pitch"]
        self.assertEqual((rec["accepted"], rec["warnings"], "pitch_fit" in rec["windaudit"]), (True, [], False))
        self.assertGreater(abs(p["value"] - 20.0), 5.0, p)
        self.assertGreaterEqual(p["concentration"], 0.4)
        given = self.qa(whole, qa={"wind_pitch": 20.0})["windaudit"]["pitch"]
        self.assertEqual(given, {"source": "given", "value": 20.0})

    SEATED = {"verdict": "seated", "exit": 0, "score": 120.0, "contrast": 140.0, "coverage": 0.9}
    UNCLEAR = {"verdict": "unclear", "exit": 0, "score": 9.0, "contrast": 10.0, "coverage": 0.9}
    NOT_SEATED = {"verdict": "not seated", "exit": 0, "score": -1.0, "contrast": None, "coverage": 0.1}
    LOST = {"verdict": "not seated", "exit": 1, "score": -1.0, "contrast": None, "coverage": None}

    def kind(self, seating, need="all", selfcross=None, windaudit="off"):
        """qa_one's record for a stubbed check_surface result, and the failure kind s_qa would record."""
        run = self.run_for(qa={"windaudit": windaudit, "require_seated": need})
        run.agent.check = {"seating": seating, "selfcross": selfcross or {"transverse": 0}}
        rec = run.qa_one("t00", {"surface": "unused.tifxyz"})
        return rec, None if rec["accepted"] else (rec.get("failure") or {"kind": "ours"})["kind"]

    def test_a_rejection_resting_only_on_checks_that_did_not_run_is_the_infrastructures(self):
        def windows(*ws):
            seated = sum(w["verdict"] == "seated" for w in ws)
            verdict = "seated" if seated == len(ws) else "partly seated" if seated else "not seated"
            return {"verdict": verdict, "seated_windows": f"{seated} of {len(ws)}", "windows": list(ws)}
        # "all": the windows that ran are all seated, so only the lost one rejects it
        rec, kind = self.kind(windows(self.SEATED, self.LOST, self.SEATED))
        self.assertEqual(kind, "infrastructure")
        self.assertEqual(rec["reasons"], ["seating: partly seated (1 of 3 windows not measured: the probe exited 1)"])
        self.assertIn("rejected only by checks that could not run: seating", rec["failure"]["reason"])
        # a window that ran is not seated (unclear): the rule decided, whatever the lost window would have said
        rec, kind = self.kind(windows(self.SEATED, self.LOST, self.UNCLEAR))
        self.assertEqual((kind, "unmeasured" in rec), ("ours", False))
        # "any": no window that ran is seated, and the lost one might have been
        self.assertEqual(self.kind(windows(self.NOT_SEATED, dict(self.LOST, exit="could not start: no such file")),
                                   need="any")[1], "infrastructure")
        self.assertEqual(self.kind(windows(self.NOT_SEATED, self.NOT_SEATED), need="any")[1], "ours")
        self.assertIsNone(self.kind(windows(self.SEATED, self.LOST), need="any")[1])        # accepted
        # one window (no windows list, its record in candidates): a time limit, or a stack that could not be read
        one = {"verdict": "not seated", "candidates": [{"scale_segmentation": 1.0, "exit": "timeout", "score": -1.0}]}
        self.assertEqual(self.kind(one), (mock.ANY, "infrastructure"))
        rec, kind = self.kind(dict(one, candidates=[{"scale_segmentation": 1.0, "exit": 0, "score": -1.0}]))
        self.assertEqual((kind, rec["reasons"]), ("infrastructure", ["seating: not seated (1 of 1 windows not "
                                                                     "measured: the probe wrote no readable stack)"]))
        # measured on air (coverage 0): a verdict, ours
        self.assertEqual(self.kind({"verdict": "not seated", "candidates": [dict(self.NOT_SEATED, coverage=0.0)]})[1],
                         "ours")
        self.assertEqual(self.kind({})[1], "infrastructure")                     # no seating record at all
        # self-intersections: not measured (tool missing, or no report) is the infrastructure's; a count is ours
        rec, kind = self.kind(windows(self.SEATED), selfcross={"exit": 1, "error": "no such file"})
        self.assertEqual(kind, "infrastructure")
        self.assertIn("vc_tifxyz_selfcross exited 1 with no readable report", rec["reasons"][0])
        run = self.run_for(qa={"windaudit": "off"})
        run.agent.check = {"selfcross": None}
        rec = run.qa_one("t00", {"surface": "unused.tifxyz"})
        self.assertEqual((rec["failure"]["kind"], rec["reasons"]),
                         ("infrastructure", ["self-intersections: not measured (vc_tifxyz_selfcross is not installed)"]))
        self.assertEqual(self.kind(windows(self.SEATED), selfcross={"transverse": 2})[1], "ours")
        # both: one check that ran rejects it, so the rule decided
        rec, kind = self.kind(windows(self.SEATED, self.LOST), selfcross={"transverse": 2})
        self.assertEqual((kind, len(rec["reasons"]), rec["unmeasured"]), ("ours", 2, rec["reasons"][1:]))

    @unittest.skipUnless(HAVE_NUMPY, "needs numpy")
    def test_a_winding_audit_that_could_not_run_is_the_infrastructures_and_a_pitch_fit_is_ours(self):
        whole = spiral_surface(self.d / "whole.tifxyz")
        run = self.run_for()
        (run.out / "umbilicus.json").unlink()                           # the axis file is gone: no audit ran
        rec = run.qa_one("t00", {"surface": str(whole)})
        self.assertEqual(len(rec["reasons"]), 1, rec["reasons"])
        self.assertIn("winding audit could not run: umbilicus", rec["reasons"][0])
        self.assertEqual((rec.get("failure") or {}).get("kind"), "infrastructure")
        small = spiral_surface(self.d / "small.tifxyz", turns=0.5)     # audited: no pitch fits, and required rejects
        rec = self.qa(small, qa={"windaudit": "required"})
        self.assertEqual((rec["accepted"], rec["windaudit"]["pitch_fit"], "failure" in rec), (False, "span", False))

    def traced(self, grids):
        """A one-seed trace stage with the trace tool's grid record given, then qa (winding audit off) and the
        report."""
        run = self.run_for(qa={"windaudit": "off"}, grids=grids)
        run.state["stages"]["seeds"] = {"record": {"seeds": [[1.0, 2.0, 3.0]]}}
        run.s_trace()
        stage = run.s_qa()
        return run.state["surfaces"]["t00"], stage, run.s_report()

    def test_grid_fetches_lost_during_a_trace_are_reported(self):
        lost = {"remote": True, "files": 40, "missing": 2, "false_missing": 1, "fetch_failed": 2,
                "fetch_failed_sample": ["xy/000041.grid: HTTP 0", "xy/000099.grid: HTTP 0"], "refetched": 1,
                "refetch_failed": 1}
        s, stage, report = self.traced(lost)
        self.assertEqual((s["trace"]["grid_fetch_failed"], s["trace"]["grid_refetch_failed"]), (2, 1))
        self.assertTrue(s["accepted"])                               # require_data_term holds: grids were used
        self.assertEqual(s["qa"]["reasons"], [])
        self.assertEqual(len(s["qa"]["warnings"]), 1)
        self.assertIn("the normals of 3 grid files: 2 failed to fetch (xy/000041.grid: HTTP 0, xy/000099.grid: "
                      "HTTP 0) and 1 answered a false 404", s["qa"]["warnings"][0])
        self.assertEqual(stage["warnings"], {"t00": s["qa"]["warnings"]})
        self.assertEqual(report["surfaces"]["t00"]["warnings"], s["qa"]["warnings"])
        s, stage, report = self.traced({**lost, "fetch_failed": 0, "false_missing": 0})
        self.assertEqual((s["qa"]["warnings"], report["surfaces"]["t00"]["warnings"]), ([], []))
        self.assertNotIn("warnings", stage)
        s, _, _ = self.traced({"remote": False, "files": 40})       # a local grid folder: nothing was fetched
        self.assertEqual(s["qa"]["warnings"], [])
        s, _, _ = self.traced({"remote": True, "files": 40})        # streamed, count missing: said, not taken as 0
        self.assertIn("does not say whether normal-grid fetches failed", s["qa"]["warnings"][0])

    def test_unchecked_404_markers_and_the_files_a_trace_fetched_are_on_record(self):
        # as the trace tool records streamed grids: files is the shared cache's total, files_fetched this trace's
        grids = {"remote": True, "files": 40, "files_before": 30, "files_fetched": 10, "missing": 3,
                 "false_missing": 0, "unchecked": 2, "fetch_failed": 0}
        s, stage, report = self.traced(grids)
        t = s["trace"]
        self.assertEqual((t["grid_files"], t["grid_files_fetched"], t["grid_fetch_failed"], t["grid_unchecked"]),
                         (40, 10, 0, 2))
        self.assertEqual((s["qa"]["grid_fetches"]["grid_files_fetched"], s["qa"]["grid_fetches"]["grid_unchecked"]),
                         (10, 2))
        self.assertTrue(s["accepted"])                               # a warning, never a reason
        self.assertEqual(len(s["qa"]["warnings"]), 1, s["qa"]["warnings"])
        self.assertIn("2 grid files answered 404 during the trace and could not be checked against the bucket",
                      s["qa"]["warnings"][0])
        self.assertEqual(report["surfaces"]["t00"]["warnings"], s["qa"]["warnings"])
        s, _, _ = self.traced({**grids, "fetch_failed": 1, "fetch_failed_sample": ["xy/000041.grid: HTTP 0"]})
        self.assertEqual(len(s["qa"]["warnings"]), 1, s["qa"]["warnings"])     # one warning that says both
        self.assertIn("1 failed to fetch (xy/000041.grid: HTTP 0)", s["qa"]["warnings"][0])
        self.assertIn("2 grid files answered 404", s["qa"]["warnings"][0])
        s, _, _ = self.traced({**grids, "unchecked": 0})
        self.assertEqual(s["qa"]["warnings"], [])


class TestExternalPrediction(unittest.TestCase):
    """A prediction and normal grids from outside the catalog (kit surfacepred's output), against the test
    catalog's scan V1 of shape [100, 200, 300], whose own prediction and grids it replaces."""

    SCAN = [100, 200, 300]

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, pred, grids=None, volume="V1", **over):
        ext = {"zarr": str(pred), **({"normal_grids": str(grids)} if grids else {})}
        settings = {"external_prediction": ext, **({"volume": volume} if volume else {}), **over}
        return autopipe.make_plan("PHercTest", settings, cat=catalog(), created="2026-10-09T00:00:00Z")

    def test_resolves_records_and_enters_the_digest(self):
        pred = pred_headers(self.d / "pred.zarr", self.SCAN)
        grids = grid_folder(self.d / "pred.normal-grids")
        base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        plan = self.plan(pred, grids)
        r = plan["resolved"]
        self.assertEqual((r["volume"], r["prediction_url"], r["prediction_model"], r["prediction_level"]),
                         ("V1", str(pred.resolve()), "external", 0))
        self.assertEqual((r["normal_grids_url"], r["normal_grids_model"]), (str(grids.resolve()), "external"))
        ext = r["external_prediction"]
        self.assertEqual((ext["level0_shape"], ext["level0_chunks"], ext["levels"], ext["grids_input_level"]),
                         (self.SCAN, [64, 64, 64], 2, 0))
        self.assertEqual(ext["headers"], [".zattrs", ".zgroup", "0/.zarray", "1/.zarray", "meta.json"])
        self.assertIsNone(ext["axis_grids"])        # the catalog has grids for V1: the axis estimate reads those
        self.assertIsNone(ext["run_record"])
        self.assertEqual(autopipe.check_plan(plan), plan)
        self.assertNotEqual(plan["digest"], base["digest"])
        # a relative location is taken from root (the settings keep it as given)
        rel = autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": {
            "zarr": "pred.zarr", "normal_grids": "pred.normal-grids"}}, cat=catalog(), root=self.d,
            created="2026-10-09T00:00:00Z")
        self.assertEqual(rel["resolved"], plan["resolved"])
        self.assertEqual(rel["settings"]["external_prediction"], {"zarr": "pred.zarr",
                                                                  "normal_grids": "pred.normal-grids",
                                                                  "box": "auto", "seed_margin": 16,
                                                                  "axis_slices": 9})
        self.assertEqual((r["external_prediction"]["box"], r["external_prediction"]["box_source"]),
                         (None, "the prediction's run.json names no box"))
        # the headers and the grids' metadata enter the digest: another package is another plan
        write_meta(pred, self.SCAN, name="another run")
        self.assertNotEqual(self.plan(pred, grids)["digest"], plan["digest"])
        write_meta(pred, self.SCAN)
        self.assertEqual(self.plan(pred, grids)["digest"], plan["digest"])
        grid_folder(self.d / "pred.normal-grids", multiscale=True)
        self.assertNotEqual(self.plan(pred, grids)["digest"], plan["digest"])

    def test_a_prediction_whose_level_0_is_not_the_scans_is_refused(self):
        coarse = pred_headers(self.d / "l1.zarr", surfacepred.ceil_shape(self.SCAN, 1))
        with self.assertRaisesRegex(autopipe.AutoError, r"level-0 shape \[50, 100, 150\] is not scan V1's level-0 "
                                                        r"shape \[100, 200, 300\].*made on level 1"):
            self.plan(coarse)
        short = pred_headers(self.d / "short.zarr", [100, 199, 300])
        with self.assertRaisesRegex(autopipe.AutoError, "no level of this scan either"):
            self.plan(short)
        # VC3D's rule allows a level padded by less than one chunk, and no more
        self.assertEqual(self.plan(pred_headers(self.d / "pad.zarr", [100, 200, 363]))["resolved"]
                         ["external_prediction"]["level0_shape"], [100, 200, 363])
        with self.assertRaisesRegex(autopipe.AutoError, "is not scan V1's level-0 shape"):
            self.plan(pred_headers(self.d / "pad64.zarr", [100, 200, 364]))
        # chunks of another length would leave axes out of the comparison: y and x here are another scan's
        one = pred_headers(self.d / "onechunk.zarr", [100, 999, 999], levels=1)
        z = json.loads((one / "0" / ".zarray").read_text())
        for chunks in ([64], None, [64, 64, 0]):
            (one / "0" / ".zarray").write_text(json.dumps({**z, "chunks": chunks}))
            write_meta(one, [100, 999, 999])
            with self.assertRaisesRegex(autopipe.AutoError, "not three positive whole numbers"):
                self.plan(one)

    def test_a_prediction_vc3d_would_not_open_is_refused(self):
        with self.assertRaisesRegex(autopipe.AutoError, "VC3D would not open.*no meta.json"):
            self.plan(pred_headers(self.d / "nometa.zarr", self.SCAN, meta=False))
        with self.assertRaisesRegex(autopipe.AutoError, r"VC3D would not open.*level 1: shape \[50, 100, 149\]"):
            self.plan(pred_headers(self.d / "round.zarr", self.SCAN, short_level=1))
        with self.assertRaisesRegex(autopipe.AutoError, "VC3D would not open.*no OME multiscales"):
            self.plan(self.d)                         # a folder that is not a volume
        with self.assertRaisesRegex(autopipe.AutoError, "not a directory"):
            self.plan(self.d / "nothing.zarr")

    def test_grids_made_on_another_level_are_refused(self):
        pred = pred_headers(self.d / "pred.zarr", self.SCAN)
        with self.assertRaisesRegex(autopipe.AutoError, "made on level 2 of their prediction"):
            self.plan(pred, grid_folder(self.d / "g2", level=2))
        with self.assertRaisesRegex(autopipe.AutoError, "made on level 1 of their prediction"):
            self.plan(pred, grid_folder(self.d / "g1m", level=1, multiscale=True))
        with self.assertRaisesRegex(autopipe.AutoError, "records no input-level"):
            self.plan(pred, grid_folder(self.d / "gnone", level=None))
        with self.assertRaisesRegex(autopipe.AutoError, "no readable metadata.json"):
            self.plan(pred, grid_folder(self.d / "gnometa", metadata=False))
        plan = self.plan(pred, grid_folder(self.d / "g0m", level=0, multiscale=True))
        self.assertEqual(plan["resolved"]["external_prediction"]["grids_input_level"], 0)

    def test_a_box_prediction_bounds_the_plan(self):
        run = {"scan": "V1", "level": 0, "bbox": "10:90,20:180,100:400"}
        pred = pred_headers(self.d / "box.zarr", self.SCAN, run=run)
        ext = self.plan(pred)["resolved"]["external_prediction"]
        # from run.json, clipped to the scan (x stops at 300)
        self.assertEqual((ext["box"], ext["box_source"]), ([[10, 90], [20, 180], [100, 300]], "run.json"))
        given = {"zarr": str(pred), "box": "0:50,0:50,0:50"}
        self.assertEqual(autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": given},
                                            cat=catalog())["resolved"]["external_prediction"]["box"],
                         [[0, 50], [0, 50], [0, 50]])
        off = autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": {"zarr": str(pred),
                                                                                       "box": "off"}}, cat=catalog())
        self.assertEqual(off["resolved"]["external_prediction"]["box"], None)
        self.assertNotEqual(off["digest"], self.plan(pred)["digest"])
        with self.assertRaisesRegex(autopipe.AutoError, "outside the prediction's box"):
            self.plan(pred, seeds={"points": [[150.0, 100.0, 50.0], [50.0, 100.0, 50.0]]})
        self.plan(pred, seeds={"points": [[150.0, 100.0, 50.0]]})            # x 150, y 100, z 50: inside
        with self.assertRaisesRegex(autopipe.AutoError, "leaves nothing inside"):
            autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": {
                "zarr": str(pred), "box": "0:20,0:50,0:50"}}, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "axis_slices"):
            autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": {
                "zarr": str(pred), "axis_slices": 1}}, cat=catalog())

    def test_the_run_record_names_the_scan_and_level(self):
        url = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercTest/volumes/V1-9.362um-test.zarr/"
        run = {"scan": url, "level": 0, "bbox": "0:64,0:64,0:64", "threshold": 0.2, "note": "kept out"}
        plan = self.plan(pred_headers(self.d / "a.zarr", self.SCAN, run=run), volume=None)
        self.assertEqual(plan["resolved"]["volume"], "V1")              # the scan comes from run.json
        self.assertEqual(plan["resolved"]["external_prediction"]["run_record"],
                         {"scan": url, "level": 0, "bbox": "0:64,0:64,0:64", "threshold": 0.2})
        with self.assertRaisesRegex(autopipe.AutoError, "made on level 2 of the scan"):
            self.plan(pred_headers(self.d / "b.zarr", self.SCAN, run={**run, "level": 2}))
        other = {**run, "scan": url.replace("V1-9.362um-test", "V2-2.4um")}
        with self.assertRaisesRegex(autopipe.AutoError, "made from scan V2, not V1"):
            self.plan(pred_headers(self.d / "c.zarr", self.SCAN, run=other))
        with self.assertRaisesRegex(autopipe.AutoError, "the catalog gives no shape"):
            self.plan(pred_headers(self.d / "c.zarr", self.SCAN, run=other), volume=None)
        with self.assertRaisesRegex(autopipe.AutoError, "name the scan it was made from"):
            self.plan(pred_headers(self.d / "d.zarr", self.SCAN), volume=None)

    def test_settings_that_cannot_go_together_are_refused(self):
        pred = pred_headers(self.d / "pred.zarr", self.SCAN)
        with self.assertRaisesRegex(autopipe.AutoError, "published segment replaces seeds and trace"):
            self.plan(pred, segment="x")
        with self.assertRaisesRegex(autopipe.AutoError, "replaces it: give one"):
            self.plan(pred, prediction="M1")
        with self.assertRaisesRegex(autopipe.AutoError, "needs zarr"):
            autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": True}, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "unknown plan setting external_prediction.grids"):
            autopipe.make_plan("PHercTest", {"external_prediction": {"zarr": str(pred), "grids": "x"}}, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "external_prediction is an object"):
            autopipe.make_plan("PHercTest", {"external_prediction": str(pred)}, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "a local folder, or an https or s3 URL"):
            self.plan("ftp://example.org/pred.zarr")
        # trace.normal_grids required: the plan must name grids, and then it is made
        with self.assertRaisesRegex(autopipe.AutoError, "names no normal_grids"):
            self.plan(pred, trace={"normal_grids": "required"})
        plan = self.plan(pred, grid_folder(self.d / "g"), trace={"normal_grids": "required"})
        self.assertEqual(plan["resolved"]["normal_grids_url"], str((self.d / "g").resolve()))
        # no grids named: none from the catalog either (the catalog's go with its own prediction)
        self.assertIsNone(self.plan(pred)["resolved"]["normal_grids_url"])

    def test_locations(self):
        self.assertEqual(autopipe._location("s3://bucket/a/pred.zarr"), "https://bucket.s3.amazonaws.com/a/pred.zarr/")
        self.assertEqual(autopipe._location("https://h/x.zarr"), "https://h/x.zarr/")
        self.assertEqual(autopipe._location("x.zarr", root=self.d), str((self.d / "x.zarr").resolve()))
        with self.assertRaisesRegex(autopipe.AutoError, "empty location"):
            autopipe._location("")

    def test_a_url_is_read_over_http_with_false_404s_asked_again(self):
        pred = pred_headers(self.d / "pred.zarr", self.SCAN)
        grid_folder(self.d / "pred.normal-grids")
        local = self.plan(pred, self.d / "pred.normal-grids")
        kw = {"opener": fakes.no_proxy_opener(), "rate": 0}
        with fakes.S3LikeServer(self.d, false=1) as srv:
            plan = autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": {
                "zarr": srv.url + "/pred.zarr", "normal_grids": srv.url + "/pred.normal-grids"}},
                cat=catalog(), store_kw=kw)
        r = plan["resolved"]
        self.assertEqual((r["prediction_url"], r["normal_grids_url"]),
                         (srv.url + "/pred.zarr/", srv.url + "/pred.normal-grids/"))
        ext, lext = r["external_prediction"], local["resolved"]["external_prediction"]
        self.assertEqual((ext["headers_sha256"], ext["grids_metadata_sha256"]),
                         (lext["headers_sha256"], lext["grids_metadata_sha256"]))
        self.assertGreater(srv.hits["pred.zarr/meta.json"], 1)          # the first answer was a false 404

    def test_a_url_needs_no_meta_json_but_the_same_shape(self):
        # VC3D opens a URL with Volume::NewFromUrl, which takes its sizes from the first level and needs no meta.json
        # (the published predictions have none); the same folder on disk goes through its local open, which needs one
        bare = pred_headers(self.d / "bare.zarr", self.SCAN, meta=False)
        pred_headers(self.d / "coarse.zarr", surfacepred.ceil_shape(self.SCAN, 2), meta=False)
        kw = {"opener": fakes.no_proxy_opener(), "rate": 0}
        with fakes.S3LikeServer(self.d, false=0) as srv:
            def plan(name):
                return autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": {
                    "zarr": f"{srv.url}/{name}"}}, cat=catalog(), store_kw=kw)
            self.assertEqual(plan("bare.zarr")["resolved"]["external_prediction"]["headers"],
                             [".zattrs", ".zgroup", "0/.zarray", "1/.zarray"])
            with self.assertRaisesRegex(autopipe.AutoError, "made on level 2"):
                plan("coarse.zarr")
            with self.assertRaisesRegex(autopipe.AutoError, "no OME multiscales"):
                plan("nothing.zarr")
        with self.assertRaisesRegex(autopipe.AutoError, "no meta.json"):
            self.plan(bare)

    def test_only_the_local_open_rules_are_dropped_for_a_url(self):
        # A metadata.json with no "scan" key (as the published predictions have) and a level that breaks the ceil
        # rule pass as a URL (NewFromUrl reads metadata only for other fields and checks no level shapes) and fail
        # as a folder; a wrong dtype fails both ways
        pub = pred_headers(self.d / "pub.zarr", self.SCAN, short_level=1)
        (pub / "metadata.json").write_text(json.dumps({"kind": "surface prediction", "model": "m7"}))
        bad = pred_headers(self.d / "bad.zarr", self.SCAN, meta=False)
        z = json.loads((bad / "0" / ".zarray").read_text())
        (bad / "0" / ".zarray").write_text(json.dumps({**z, "dtype": "<f4"}))
        kw = {"opener": fakes.no_proxy_opener(), "rate": 0}
        with fakes.S3LikeServer(self.d, false=0) as srv:
            def plan(name):
                return autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": {
                    "zarr": f"{srv.url}/{name}"}}, cat=catalog(), store_kw=kw)
            self.assertIn("metadata.json", plan("pub.zarr")["resolved"]["external_prediction"]["headers"])
            with self.assertRaisesRegex(autopipe.AutoError, r"level 0: dtype <f4, not \|u1"):
                plan("bad.zarr")
        with self.assertRaisesRegex(autopipe.AutoError, r"level 1: shape \[50, 100, 149\].*\(ceil rule\)"):
            self.plan(pub)
        with self.assertRaisesRegex(autopipe.AutoError, r"level 0: dtype <f4, not \|u1"):
            self.plan(bad)

    def test_the_axis_reads_the_catalogs_grids_only_when_they_are_level_0(self):
        pred = pred_headers(self.d / "pred.zarr", self.SCAN)
        grids = grid_folder(self.d / "pred.normal-grids")
        for level, axis in ((None, None), (0, None), (2, str(grids.resolve()))):
            cat = catalog()
            g = cat["samples"]["PHercTest"]["volumes"]["V1"]["data"][-1]
            if level is not None:
                g["parameters"]["level"] = level
            plan = autopipe.make_plan("PHercTest", {"volume": "V1", "external_prediction": {
                "zarr": str(pred), "normal_grids": str(grids)}}, cat=cat)
            self.assertEqual(plan["resolved"]["external_prediction"]["axis_grids"], axis, level)


class TestUmbilicusTool(Base):
    def grids(self, zs):
        g = self.d / "grids"
        (g / "xy").mkdir(parents=True)
        for z in zs:
            (g / "xy" / f"{z:06d}.grid").write_bytes(b"grid")
        return g

    def args(self, **kw):
        return {"grids": str(self.grids(range(0, 1200, 100))), "voxel_um": 9.0, "shape_zyx": [1200, 64, 64],
                "every": 100, **kw}

    def test_estimate_and_its_outlier_rule(self):
        res = self.call("umbilicus", self.args())
        self.assertEqual((res["source"], res["estimates"], res["dropped"]), ("estimated", 12, 0))
        pts = vc3d_orient.load_umbilicus(res["umbilicus"])
        self.assertAlmostEqual(vc3d_orient.centre_at(pts, 500)[0], 37.0, places=3)   # the fake's x = 32 + z / 100
        saved = json.loads(Path(res["umbilicus"]).read_text())["kit_autopipe"]
        self.assertEqual(saved["slices"], 12)

    def test_a_planted_outlier_is_dropped(self):
        ctx = self.context(FAKE_UMB_OUTLIERS="500")
        res = vc3d_agent.call("umbilicus", self.args(), ctx)
        self.assertEqual((res["kept"], res["dropped"]), (11, 1))
        dropped = json.loads(Path(res["umbilicus"]).read_text())["kit_autopipe"]["dropped"]
        self.assertEqual([d["z"] for d in dropped], [500.0])

    def test_too_few_grids_and_missing_arguments(self):
        with self.assertRaisesRegex(vc3d_agent.ToolError, "only 2 normal grids"):
            self.call("umbilicus", {"grids": str(self.grids([0, 100])), "voxel_um": 9.0,
                                    "shape_zyx": [1200, 64, 64], "every": 100})
        with self.assertRaisesRegex(vc3d_agent.ToolError, "needs voxel_um and shape_zyx"):
            self.call("umbilicus", {"grids": str(self.d)})
        with self.assertRaisesRegex(vc3d_agent.ToolError, "needs sample"):
            self.call("umbilicus", {})


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestSeeds(Base):
    def setUp(self):
        super().setUp()
        self.pred, self.ct, self.axis = scroll(self.d)

    def seeds(self, **kw):
        a = {"prediction": str(self.pred), "umbilicus": str(self.axis), "voxel_um": 10.0, "count": 3,
             "radius_um": [300.0, 500.0], "min_spacing_um": 80.0, "z_range": [20, 44], "level": 0, **kw}
        return self.call("seeds", a)

    def test_on_the_sheet_in_the_band_and_spaced(self):
        res = self.seeds()
        self.assertEqual(len(res["seeds"]), 3)
        for s in res["seeds"]:
            x, y, z = s["xyz"]
            self.assertGreaterEqual(s["value"], autopipe.SURFACE_THRESHOLD)
            self.assertLessEqual(abs(math.hypot(x - AXIS[0], y - AXIS[1]) - RADIUS), 1.5)
            self.assertTrue(20 <= z < 44)
        xyz = [s["xyz"] for s in res["seeds"]]
        self.assertTrue(all(math.dist(a, b) >= 8 for i, a in enumerate(xyz) for b in xyz[i + 1:]))
        self.assertEqual([s["xyz"] for s in self.seeds()["seeds"]], xyz)       # same data and seed, same points

    def test_the_ct_check_refuses_seeds_over_no_scan(self):
        res = self.seeds(ct=str(self.ct), count=6, max_planes=24)
        self.assertTrue(res["seeds"])
        self.assertTrue(all(s["xyz"][0] < 80 for s in res["seeds"]))
        self.assertGreater(res["stats"]["refused"], 0)

    def test_a_band_with_no_sheet_gives_no_seed(self):
        res = self.seeds(radius_um=[500.0, 600.0])
        self.assertEqual(res["seeds"], [])


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestRun(Base):
    """Whole runs on fakes: a cylinder sheet around a known axis, traced by the fake tracer as a piece of that
    cylinder, so the normal has a clear sign against the axis."""

    def setUp(self):
        super().setUp()
        self.pred, self.ct, self.axis = scroll(self.d)
        self.ctx = self.context(FAKE_TRACE_ARC=f"{AXIS[0]},{AXIS[1]}")

    def grids(self):
        """A local normal-grid folder for the fake tracer (it only needs metadata.json to be there)."""
        g = self.d / "grids"
        (g / "xy").mkdir(parents=True, exist_ok=True)
        (g / "metadata.json").write_text(json.dumps({"spiral-step": 20, "grid-step": 64}))
        return g

    def plan(self, grids=True, bench=None, external=None, **over):
        # the fake runs here ink their renders as rendered unless a test asks for the upright turn (ink.orient, opt in)
        ink = dict(over.pop("ink", {"where": "modal"}))
        settings = autopipe._merge(autopipe.DEFAULTS, {
            "purpose": "smoke", "umbilicus": {"source": str(self.axis)},
            "seeds": {"count": 2, "z_range": [20, 44], "radius_um": [300.0, 500.0], "level": 0,
                      "min_spacing_um": 80.0},
            "qa": {"require_seated": "none", "windaudit": "off", "windows": 1},
            "ink": ink, **over})
        resolved = {"sample": "PHercFake", "volume": "V1", "volume_url": str(self.ct), "voxel_um": 10.0,
                    "shape_zyx": SHAPE, "license": None, "prediction_url": str(self.pred),
                    "prediction_model": "fake", "prediction_level": 0,
                    "normal_grids_url": str(self.grids()) if grids else None, "normal_grids_model": "fake",
                    "catalog_umbilicus": None, "benchmark": None}
        if bench:
            resolved["winding_bench"] = {"references": "fake", "rule_digest": bench}
        if external:
            # as make_plan resolves external_prediction (resolve_external's record, made on the fake scan)
            settings = autopipe._merge(settings, {"external_prediction": {"zarr": external["zarr"],
                                                                          "normal_grids": external["normal_grids"]}})
            resolved.update(prediction_url=external["zarr"], prediction_model="external", prediction_level=0,
                            normal_grids_url=external["normal_grids"],
                            normal_grids_model="external" if external["normal_grids"] else None,
                            external_prediction=external)
        plan = {"version": autopipe.PLAN_VERSION, "created": "2026-10-09T00:00:00Z", "settings": settings,
                "resolved": resolved}
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        return plan

    def run_plan(self, plan, out=None, **kw):
        out = out or self.d / "run"
        out.mkdir(parents=True, exist_ok=True)
        return autopipe.Run(vc3d_agent, self.ctx, out, plan).run(**kw), out

    def test_end_to_end_to_the_modal_handoff(self):
        st, out = self.run_plan(self.plan())
        status = {k: v["status"] for k, v in st["stages"].items()}
        self.assertEqual(status, {"acquire": "done", "umbilicus": "done", "seeds": "done", "trace": "done",
                                  "bench": "skipped", "qa": "done", "flatten": "done", "render": "done", "ink": "handoff",
                                  "report": "done"}, st["stages"])
        surf = st["surfaces"]
        self.assertEqual(sorted(surf), ["t00", "t01"])
        for s in surf.values():
            self.assertTrue(s["accepted"], s["qa"])
            self.assertEqual(s["qa"]["orientation"]["checked"], True)
            self.assertEqual(s["flatten"]["used"], "flattened")      # the fake flattener changes nothing: passes
            self.assertNotIn("render_distortion", s["flatten"])     # the flattening's own check is the one
            self.assertTrue(Path(s["render"]["zarr"]).exists())
            self.assertTrue(str(s["render"]["order"]).startswith("team"))
            self.assertEqual(s["render"]["audit"]["missing_fraction"], 0.0)
        job = json.loads((out / "modal-job.json").read_text())
        self.assertEqual(sorted(job["renders"]), ["t00", "t01"])
        report = json.loads((out / "report.json").read_text())
        self.assertIn("not a reading", report["note"])
        self.assertEqual([s["warnings"] for s in report["surfaces"].values()], [[], []])
        # a second run resumes: nothing is traced again
        log = self.d / "fake.log"
        self.ctx.env["FAKE_LOG"] = str(log)
        st2, _ = self.run_plan(self.plan())
        self.assertFalse(log.exists() and "vc_grow_seg_from_seed" in log.read_text())
        self.assertEqual(st2["surfaces"]["t00"]["render"], surf["t00"]["render"])

    def test_a_surface_over_missing_scan_chunks_is_not_rendered(self):
        plan = self.plan()
        st, out = self.run_plan(plan, until="flatten")
        self.assertEqual(st["stages"]["flatten"]["status"], "done")
        import shutil
        for f in (self.ct / "0").iterdir():          # the scan's chunks under the surfaces go missing
            if not f.name.startswith("."):
                shutil.rmtree(f) if f.is_dir() else f.unlink()
        st, _ = self.run_plan(plan, out)
        self.assertEqual(st["stages"]["render"]["status"], "failed")
        self.assertIn("no render finished", st["stages"]["render"]["error"])
        for s in st["surfaces"].values():
            self.assertEqual(s["render"]["audit"]["missing_fraction"], 1.0)
            self.assertIn("render.max_missing", s["render"]["refused"])
            self.assertNotIn("zarr", s["render"])
        self.assertFalse((out / "renders").exists())

    # A trace through a given seed on the sheet at (24, 64, 40) is a 9 x 9 piece of the cylinder with rows 4
    # voxels apart along z (z 24 to 56) and columns 4 voxels apart along the arc (y 48 to 80, x 24 to 27). The
    # fake scan's 32^3 chunks put rows 0 and 1 (z 24, 28) in chunk row z = 0 and rows 2 to 8 (z 32 to 56) in z = 1,
    # so the trace sits on 4 chunks (z 0 and 1, y 1 and 2, x 0); taking away the scan's z = 0 (or z = 1) chunks
    # leaves half of them missing, over render.max_missing.
    TRIM_SEED = [AXIS[0] - RADIUS, AXIS[1], 40]

    def trim_run(self, gone, trim, out=None, seg=False):
        """A one-trace run to flatten; then the scan's level-0 chunks with z index `gone` go missing, and render
        runs under render.trim (None: not asked for)."""
        import shutil
        render = autopipe._merge(autopipe.DEFAULTS["render"], {"trim": trim}, "render.")
        plan = self.plan(seeds={**autopipe.DEFAULTS["seeds"], "points": [self.TRIM_SEED]}, render=render)
        out = out or self.d / f"trim-{gone}"
        st, _ = self.run_plan(plan, out, until="flatten" if not seg else "trace")
        if seg:     # the trace stands in for a published segment
            st = json.loads((out / "state.json").read_text())
            st["surfaces"] = {"seg": dict(st["surfaces"]["t00"], origin="published segment (stand-in)")}
            (out / "state.json").write_text(json.dumps(st))
            st, _ = self.run_plan(plan, out, until="flatten")
        self.assertEqual(st["stages"]["flatten"]["status"], "done", st["stages"])
        shutil.rmtree(self.ct / "0" / str(gone))
        return self.run_plan(plan, out)

    def test_a_surface_over_missing_chunks_is_trimmed_to_the_scanned_part_when_asked(self):
        st, out = self.trim_run(0, True)     # the defaults: keep half the area, one ring of cells, CT level 2
        self.assertEqual(st["stages"]["render"]["status"], "done", st["stages"]["render"])
        r = st["surfaces"]["t00"]["render"]
        self.assertEqual((r["audit"]["missing_on_surface"], r["audit"]["chunks_on_surface"]), (2, 4))
        t = r["trim"]
        self.assertTrue(t["used"], t)
        # rows 0 and 1 lie over chunks the scan does not hold, row 2 within one cell of them: 27 of 81 dropped
        self.assertEqual((t["valid_vertices"], t["trimmed_vertices"], t["kept_vertices"]), (81, 27, 54))
        self.assertAlmostEqual(t["area_share"], 5 / 8, places=3)        # 5 of the 8 rows of cells are left
        self.assertEqual((t["level"], t["level_read"], t["dilate"]), (2, 0, 1))   # the fake scan has one level
        self.assertEqual((t["audit"]["missing_on_surface"], t["audit"]["missing_fraction"]), (0, 0.0))
        self.assertEqual(r["surface"], t["surface"])
        self.assertTrue(str(r["surface"]).startswith(str(out / "trims" / "t00")))
        self.assertTrue(Path(r["zarr"]).exists())
        self.assertNotIn("refused", r)
        self.assertNotEqual(r["surface"], st["surfaces"]["t00"]["render_surface"])     # the original is kept
        self.assertTrue(Path(st["surfaces"]["t00"]["render_surface"], "x.tif").is_file())
        report = json.loads((out / "report.json").read_text())
        self.assertTrue(report["surfaces"]["t00"]["trim"]["used"])

    def test_without_the_setting_the_same_surface_is_refused(self):
        st, out = self.trim_run(0, None)
        self.assertEqual(st["stages"]["render"]["status"], "failed")
        r = st["surfaces"]["t00"]["render"]
        self.assertIn("over render.max_missing 5%", r["refused"])
        self.assertNotIn("trim", r)
        self.assertFalse((out / "trims").exists())

    def test_a_trim_that_leaves_too_little_is_refused(self):
        st, out = self.trim_run(1, True)     # rows 2 to 8 over missing chunks, row 1 within one cell: row 0 left
        self.assertEqual(st["stages"]["render"]["status"], "failed")
        self.assertIn("no render finished", st["stages"]["render"]["error"])
        r = st["surfaces"]["t00"]["render"]
        self.assertFalse(r["trim"]["used"])
        self.assertEqual((r["trim"]["kept_vertices"], r["trim"]["area_share"]), (9, 0.0))
        self.assertIn("over render.max_missing 5%", r["refused"])
        self.assertIn("partly zeros; not trimmed: the trimmed copy keeps 0.0% of the area, under "
                      "render.trim.min_area_share 50%", r["refused"])
        self.assertNotIn("audit", r["trim"])                            # too little left: no second audit
        self.assertNotIn("zarr", r)
        self.assertFalse((out / "renders").exists())

    def test_a_trimmed_copy_whose_audit_still_fails_is_refused(self):
        # with no ring of cells dropped, row 2 (z = 32) stays, and the audit counts the missing chunks within half
        # a sample spacing and a voxel of it (z 29 to 35): the copy keeps 75 % of the area but still sits on them
        st, out = self.trim_run(0, {"dilate": 0})
        self.assertEqual(st["stages"]["render"]["status"], "failed")
        r = st["surfaces"]["t00"]["render"]
        t = r["trim"]
        self.assertFalse(t["used"])
        self.assertAlmostEqual(t["area_share"], 6 / 8, places=3)
        self.assertEqual((t["audit"]["missing_on_surface"], t["audit"]["chunks_on_surface"]), (2, 4))
        self.assertIn("not trimmed: the trimmed copy still has 2 of 4 chunks under it missing (50.0%), over "
                      "render.max_missing 5%", r["refused"])
        self.assertFalse((out / "renders").exists())

    def test_a_published_segment_is_never_trimmed(self):
        st, out = self.trim_run(0, True, seg=True)
        self.assertEqual(st["stages"]["render"]["status"], "failed")
        r = st["surfaces"]["seg"]["render"]
        self.assertEqual(r["trim"], {"used": False, "why": "a published segment is never trimmed: its labels sit on "
                                                           "its grid"})
        self.assertIn("not trimmed: a published segment", r["refused"])
        self.assertFalse((out / "trims").exists())

    def snap_run(self, snap, name, until=None):
        """A one-trace run (the trace sits on the fake prediction's sheet) with render.snap set."""
        render = autopipe._merge(autopipe.DEFAULTS["render"], {"snap": snap}, "render.")
        plan = self.plan(seeds={**autopipe.DEFAULTS["seeds"], "points": [self.TRIM_SEED]}, render=render)
        return self.run_plan(plan, self.d / name, until=until)

    @unittest.skipUnless(HAVE_NUMPY, "kit snap needs numpy")
    def test_a_snap_that_passes_its_check_is_rendered_on_the_same_grid(self):
        st, out = self.snap_run(True, "snap")
        self.assertEqual(st["stages"]["render"]["status"], "done", st["stages"]["render"])
        s = st["surfaces"]["t00"]
        r = s["render"]
        sn = r["snap"]
        self.assertEqual((sn["source"], sn["sham"]), ("pred", False))
        self.assertTrue(sn["check"]["passed"], sn["check"])
        self.assertEqual(sn["check"]["reference"], "snapped")
        self.assertTrue(sn["check"]["control_shifted"]["caught"] and sn["check"]["control_empty"]["caught"])
        self.assertTrue(sn["grid"]["kept"], sn["grid"])
        self.assertLess(sn["grid"]["moved_voxels"]["max"], 1.5)        # the trace was on the sheet already
        self.assertTrue(sn["render_shape"]["kept"], sn["render_shape"])
        self.assertEqual(r["surface"], sn["surface"])
        self.assertTrue(sn["surface"].startswith(str(out / "snaps" / "t00")))
        self.assertTrue(Path(r["zarr"]).exists())
        meta = json.loads(Path(sn["surface"], "meta.json").read_text())
        self.assertEqual(meta["snap"]["tool"], "kit snap")
        self.assertNotEqual(sn["surface"], s["render_surface"])        # the original is kept
        self.assertTrue(Path(out / "snaps" / "t00" / "check" / "snap_check.json").is_file())

    @unittest.skipUnless(HAVE_NUMPY, "kit snap needs numpy")
    def test_a_snap_whose_check_fails_is_not_rendered_unless_the_check_is_recorded_only(self):
        # a threshold above every prediction value: no sheet anywhere, so the planted offset is never recovered
        st, out = self.snap_run({"threshold": 255.0}, "nosheet")
        self.assertEqual(st["stages"]["render"]["status"], "failed")
        r = st["surfaces"]["t00"]["render"]
        self.assertFalse(r["snap"]["check"]["passed"])
        self.assertIn("kit snap --check did not pass (the snap did not recover", r["refused"])
        self.assertNotIn("zarr", r)
        self.assertFalse((out / "renders").exists())
        st, _ = self.snap_run({"threshold": 255.0, "check": "record"}, "recorded")
        r = st["surfaces"]["t00"]["render"]
        self.assertEqual(st["stages"]["render"]["status"], "done", st["stages"]["render"])
        self.assertFalse(r["snap"]["check"]["passed"])
        self.assertEqual(r["snap"]["grid"]["moved_voxels"]["max"], 0.0)  # nothing to snap to: nothing moved
        st, _ = self.snap_run({"check": "off", "sham": True}, "sham")
        sn = st["surfaces"]["t00"]["render"]["snap"]
        self.assertIsNone(sn["check"])
        self.assertTrue(sn["sham"] and sn["report"]["sham"])
        self.assertTrue(json.loads(Path(sn["surface"], "meta.json").read_text())["snap"]["sham"])

    @unittest.skipUnless(HAVE_NUMPY, "kit snap needs numpy")
    def test_a_snapped_grid_that_changes_is_refused(self):
        a = fakes.write_tifxyz(self.d / "a.tifxyz", fakes.plane(32))
        b = fakes.write_tifxyz(self.d / "b.tifxyz", fakes.plane(34))
        g = autopipe.grid_kept(a, b)
        self.assertTrue(g["kept"], g)
        self.assertEqual(g["moved_voxels"]["median"], 2.0)
        import tifffile
        z = tifffile.imread(str(b / "z.tif"))
        z[0, 0] = -1.0
        tifffile.imwrite(str(b / "z.tif"), z)
        g = autopipe.grid_kept(a, b)
        self.assertFalse(g["kept"])
        self.assertIn("1 vertices changed between valid and invalid", g["why"])
        c = fakes.write_tifxyz(self.d / "c.tifxyz", fakes.plane(32), cols=8)
        self.assertIn("grid [9, 8] instead of [9, 9]", autopipe.grid_kept(a, c)["why"])
        d = fakes.write_tifxyz(self.d / "d.tifxyz", fakes.plane(32), scale=0.5)
        self.assertIn("declared scale [0.5, 0.5] instead of [0.25, 0.25]", autopipe.grid_kept(a, d)["why"])

    def windows_run(self, ink, name="windows"):
        """Ink as the Modal runner does it, with two command-engine fake models (the traces of the default seeds,
        whose renders give the fake model maps that vary, as test_the_runner_runs_a_handed_off_ink_stage)."""
        plan = self.plan(ink=autopipe._merge(autopipe.DEFAULTS["ink"], {"orient": None, **ink}, "ink."))
        out = self.d / name
        model = self.d / "model.py"
        model.write_text(fakes.INK_MODEL)
        self.home.mkdir(parents=True, exist_ok=True)
        cmd = {"engine": "command", "command": [sys.executable, str(model), "{layers}", "{output}", "{reverse}"]}
        (self.home / "models.json").write_text(json.dumps({"fake": cmd, "fake2": cmd}))
        self.ctx = self.context(FAKE_TRACE_ARC=f"{AXIS[0]},{AXIS[1]}", KIT_AUTOPIPE_RUNNER="modal")
        return self.run_plan(plan, out)

    @unittest.skipUnless(HAVE_NUMPY, "kit ensemble needs numpy")
    def test_layer_windows_and_a_model_ensemble(self):
        import numpy as np
        import tifffile
        st, out = self.windows_run({"where": "modal", "models": ["fake", "fake2"], "variants": ["f", "r"],
                                    "layers": {"windows": [[0, 24], [4, 28]]}, "ensemble": True})
        self.assertEqual(st["stages"]["ink"]["status"], "done", st["stages"]["ink"])
        ink = st["surfaces"]["t00"]["ink"]
        self.assertEqual(sorted(ink), ["ensemble", "fake", "fake2"])
        for m in ("fake", "fake2"):
            self.assertEqual(ink[m]["exit"], 0, ink[m])
            self.assertEqual(sorted(ink[m]["windows"]), ["w00-24", "w04-28"])
            for tag, (a, b) in (("w00-24", (0, 24)), ("w04-28", (4, 28))):
                job = json.loads(Path(ink[m]["windows"][tag]["out"], "ink.json").read_text())
                self.assertEqual(job["window"]["layers"], [a, b])
            f = ink[m]["maps"]["f"]
            self.assertEqual(f["path"], str(out / "ink" / "t00" / m / "ink_f.tif"))
            parts = [tifffile.imread(p).astype(np.float64) for p in f["inputs"]]
            got = tifffile.imread(f["path"]).astype(np.float64)
            ok = got > 0
            self.assertTrue(ok.any())
            want = 1 + np.round(np.clip((parts[0] + parts[1]) / 2, 0, 1) * 65534)
            self.assertLessEqual(float(np.abs(got[ok] - want[ok]).max()), 1.0)
            self.assertFalse(np.array_equal(parts[0], parts[1]))        # the two windows read different layers
        e = ink["ensemble"]
        self.assertEqual((e["exit"], e["method"], e["models"]), (0, "mean", ["fake", "fake2"]))
        self.assertEqual(e["maps"]["r"]["inputs"], [ink["fake"]["maps"]["r"]["path"], ink["fake2"]["maps"]["r"]["path"]])

    def orient_run(self, turn_deg, orient, name, layers=None, models=("fake",), ensemble=None, until="ink"):
        """A run whose fake traces are turned in plane by turn_deg (+z along that grid direction), inked as the Modal
        runner does with the command-engine fake model (each of `models` the same fake), with ink.orient as given
        (None: off; FALLBACK: on, a failed turn inked as rendered)."""
        ink = {"where": "modal", "models": list(models), "variants": ["f", "r", "s"], "orient": orient}
        if layers is not None:
            ink["layers"] = layers
        if ensemble is not None:
            ink["ensemble"] = ensemble
        plan = self.plan(ink=autopipe._merge(autopipe.DEFAULTS["ink"], ink, "ink."))
        model = self.d / "model.py"
        model.write_text(fakes.INK_MODEL)
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({m: {"engine": "command", "command": [
            sys.executable, str(model), "{layers}", "{output}", "{reverse}"]} for m in models}))
        self.ctx = self.context(FAKE_TRACE_ARC=f"{AXIS[0]},{AXIS[1]}", KIT_AUTOPIPE_RUNNER="modal",
                                FAKE_TRACE_TURN_DEG=str(turn_deg))
        st, out = self.run_plan(plan, self.d / name, until=until)
        return st, out, plan

    @unittest.skipUnless(HAVE_LABELXFER, "kit canvasorient needs numpy, tifffile and zarr")
    def test_ink_orient_turns_the_render_and_takes_the_maps_back(self):
        import tifffile
        st0, out0, plan0 = self.orient_run(40.0, None, "plain")
        st1, out1, plan1 = self.orient_run(40.0, True, "upright")
        self.assertNotIn("orient", plan0["settings"]["ink"])
        self.assertEqual(plan1["settings"]["ink"]["orient"], autopipe.OPTIONAL["ink.orient"])
        # without the option nothing is measured, turned or written beside the maps
        self.assertFalse((out0 / "orient").exists() or (out0 / "ink-turned").exists())
        for sid, s in st0["surfaces"].items():
            self.assertNotIn("orient", s)
            self.assertNotIn("turned", s["ink"]["fake"])
        saved = json.loads((out1 / "state.json").read_text())
        for sid in ("t00", "t01"):
            s = st1["surfaces"][sid]
            o = s["orient"]
            self.assertEqual(saved["surfaces"][sid]["orient"], o)
            self.assertTrue(o["used"], o)
            self.assertFalse(o["mirror"])
            self.assertLess(abs(o["measured"]["phi_deg"] - 40.0), 3.0, o["measured"])
            self.assertEqual(o["angle_deg"], o["measured"]["angle_deg"])
            self.assertEqual(o["source"], s["render"]["zarr"])
            self.assertEqual(o["source_shape"], [36, 36])
            from kit import canvasorient
            self.assertEqual(o["turned_shape"], canvasorient.plan_turn([36, 36], o["angle_deg"])["turned_shape"])
            self.assertGreater(o["turned_shape"][0], 46)          # about 36 (cos 40 + sin 40) = 50.7
            t = json.loads(Path(o["transform"]).read_text())
            self.assertEqual((t["angle_deg"], t["mirror"], t["order"]), (o["angle_deg"], False, 1))
            m = s["ink"]["fake"]
            self.assertEqual(m["exit"], 0, m)
            self.assertEqual(m["orient"]["transform"], o["transform"])
            self.assertEqual(sorted(m["maps"]), ["f", "r", "s"])
            for v in ("f", "r", "s"):
                back = m["maps"][v]["path"]
                self.assertEqual(back, str(out1 / "ink" / sid / "fake" / f"ink_{v}.tif"))
                turned = m["turned"]["maps"][v]["path"]
                self.assertTrue(turned.startswith(str(out1 / "ink-turned" / sid / "fake")))
                self.assertEqual(list(tifffile.imread(turned).shape), o["turned_shape"])
                self.assertEqual(m["maps"][v]["invalid_px"], 0)
            # the per-pixel fake model on the turned render, taken back, is the map of the render itself
            got = tifffile.imread(m["maps"]["f"]["path"]).astype("float64")
            want = tifffile.imread(st0["surfaces"][sid]["ink"]["fake"]["maps"]["f"]["path"]).astype("float64")
            self.assertEqual(got.shape, want.shape)
            import numpy as np
            self.assertGreater(float(np.corrcoef(got.ravel(), want.ravel())[0, 1]), 0.9)
            self.assertLess(float(np.median(np.abs(got - want))), 0.02)
            # the reverse control is made on the turned canvas and taken back too: it differs from the forward
            rev = tifffile.imread(m["maps"]["r"]["path"]).astype("float64")
            self.assertGreater(float(np.abs(rev - got).mean()), 0.01)
        # a second run of the stage keeps everything: nothing is turned, inked or taken back again
        files = [Path(st1["surfaces"]["t00"]["orient"]["zarr"]) / ".zattrs",
                 Path(st1["surfaces"]["t00"]["ink"]["fake"]["maps"]["f"]["path"]),
                 Path(st1["surfaces"]["t00"]["ink"]["fake"]["turned"]["maps"]["f"]["path"])]
        before = [f.stat().st_mtime_ns for f in files]
        st2, _ = self.run_plan(plan1, out1, until="ink")
        self.assertEqual([f.stat().st_mtime_ns for f in files], before)
        self.assertEqual(st2["surfaces"]["t00"]["orient"], st1["surfaces"]["t00"]["orient"])
        self.assertEqual(st2["surfaces"]["t00"]["ink"], st1["surfaces"]["t00"]["ink"])

    @unittest.skipUnless(HAVE_LABELXFER, "kit canvasorient needs numpy, tifffile and zarr")
    def test_ink_orient_not_applicable_inks_the_render_and_a_failure_inks_nothing(self):
        import tifffile
        from kit import canvasorient
        st0, out0, _ = self.orient_run(40.0, None, "plain")
        real = canvasorient.measure

        def refused(*a, **k):
            rec = real(*a, **k)
            rec.update(applicable=False, why=["consistency 0.500 under 0.9: planted"])
            return rec
        with mock.patch.object(canvasorient, "measure", refused):
            st1, out1, _ = self.orient_run(40.0, {"min_consistency": 0.95}, "refused")
        for sid in ("t00", "t01"):
            o = st1["surfaces"][sid]["orient"]
            self.assertFalse(o["used"])
            self.assertIn("not turned: consistency 0.500", o["why"])
            m = st1["surfaces"][sid]["ink"]["fake"]
            self.assertEqual(m["exit"], 0)
            self.assertNotIn("turned", m)
            for v in ("f", "r"):
                self.assertEqual(tifffile.imread(m["maps"][v]["path"]).tobytes(),
                                 tifffile.imread(st0["surfaces"][sid]["ink"]["fake"]["maps"][v]["path"]).tobytes())
        self.assertFalse((out1 / "orient").exists())

        def broken(*a, **k):
            raise canvasorient.OrientError("planted: no grid scale")
        with mock.patch.object(canvasorient, "measure", broken):
            st2, out2, _ = self.orient_run(40.0, True, "broken")
        for sid in ("t00", "t01"):
            self.assertIn("planted: no grid scale", st2["surfaces"][sid]["orient"]["failed"])
            self.assertIn("not inked: the canvas turn failed", st2["surfaces"][sid]["ink"]["fake"]["exit"])
        self.assertFalse((out2 / "ink").exists())

    @unittest.skipUnless(HAVE_LABELXFER, "kit canvasorient needs numpy, tifffile and zarr")
    def test_with_the_fallback_a_failed_turn_inks_the_render(self):
        import tifffile
        from kit import canvasorient
        st0, out0, _ = self.orient_run(40.0, None, "plain")
        st1, out1, plan1 = self.orient_run(40.0, FALLBACK, "turned")
        self.assertEqual(plan1["settings"]["ink"]["orient"], dict(autopipe.OPTIONAL["ink.orient"], fallback="unturned"))
        for sid in ("t00", "t01"):
            o = st1["surfaces"][sid]["orient"]
            self.assertTrue(o["used"], o)
            self.assertLess(abs(o["measured"]["phi_deg"] - 40.0), 3.0, o["measured"])
            m = st1["surfaces"][sid]["ink"]["fake"]
            self.assertEqual(m["exit"], 0, m)
            self.assertEqual(m["orient"]["transform"], o["transform"])
            self.assertNotIn("inked as rendered", " ".join(m.get("warnings") or []))

        def broken(*a, **k):
            raise canvasorient.OrientError("planted: no grid scale")
        with mock.patch.object(canvasorient, "measure", broken):
            st2, out2, plan2 = self.orient_run(40.0, FALLBACK, "fallback")
        self.assertFalse((out2 / "orient").exists() or (out2 / "ink-turned").exists())
        for sid in ("t00", "t01"):
            self.assertIn("planted: no grid scale", st2["surfaces"][sid]["orient"]["failed"])
            self.assertFalse(st2["surfaces"][sid]["orient"]["used"])
            m = st2["surfaces"][sid]["ink"]["fake"]
            self.assertEqual(m["exit"], 0, m)                   # inked as rendered, not left uninked
            self.assertNotIn("turned", m)
            self.assertEqual(sum("inked as rendered: the canvas turn failed (OrientError: planted" in w
                                 for w in m["warnings"]), 1, m["warnings"])
            for v in ("f", "r", "s"):
                self.assertEqual(tifffile.imread(m["maps"][v]["path"]).tobytes(),
                                 tifffile.imread(st0["surfaces"][sid]["ink"]["fake"]["maps"][v]["path"]).tobytes())
        # a second run of the stage keeps the record and the maps: the failed turn is not tried again
        with mock.patch.object(canvasorient, "measure", side_effect=AssertionError("measured again")):
            st3, _ = self.run_plan(plan2, out2, until="ink")
        self.assertEqual(st3["surfaces"]["t00"]["ink"], st2["surfaces"]["t00"]["ink"])

    @unittest.skipUnless(HAVE_LABELXFER, "kit canvasorient needs numpy, tifffile and zarr")
    def test_the_fallback_is_marked_on_the_ensemble_and_in_the_report(self):
        from kit import canvasorient

        def broken(*a, **k):
            raise canvasorient.OrientError("planted: no grid scale")
        with mock.patch.object(canvasorient, "measure", broken):
            st, out, _ = self.orient_run(40.0, FALLBACK, "ens-fallback", models=("fake", "fake2"), ensemble=True,
                                         until="report")
        rep = json.loads((out / "report.json").read_text())
        for sid in ("t00", "t01"):
            e = st["surfaces"][sid]["ink"]["ensemble"]
            self.assertEqual(e["exit"], 0, e)
            self.assertEqual(len(e["warnings"]), 1, e)
            self.assertIn("inked as rendered: the canvas turn failed (OrientError: planted", e["warnings"][0])
            o = rep["surfaces"][sid]["orient"]
            self.assertEqual((o["used"], o["then"]), (False, "inked as rendered"), o)
            self.assertIn("planted: no grid scale", o["failed"])
        # turned: the report gives the angle; a plan without the fallback leaves a failed trace uninked
        st, out, _ = self.orient_run(40.0, FALLBACK, "ens-turned", models=("fake", "fake2"), ensemble=True,
                                     until="report")
        rep = json.loads((out / "report.json").read_text())
        o = rep["surfaces"]["t00"]["orient"]
        self.assertTrue(o["used"])
        self.assertLess(abs(o["angle_deg"] - 40.0), 3.0, o)
        self.assertNotIn("warnings", st["surfaces"]["t00"]["ink"]["ensemble"])
        with mock.patch.object(canvasorient, "measure", broken):
            st, out, _ = self.orient_run(40.0, True, "explicit-fail", until="report")
        rep = json.loads((out / "report.json").read_text())
        self.assertEqual(rep["surfaces"]["t00"]["orient"]["then"], "not inked")
        _, out, _ = self.orient_run(40.0, None, "off", until="report")
        self.assertNotIn("orient", json.loads((out / "report.json").read_text())["surfaces"]["t00"])

    @unittest.skipUnless(HAVE_LABELXFER, "kit canvasorient needs numpy, tifffile and zarr")
    def test_ink_orient_with_layer_windows(self):
        st, out, _ = self.orient_run(-25.0, True, "windows", layers={"windows": [[0, 24], [4, 28]]})
        m = st["surfaces"]["t00"]["ink"]["fake"]
        self.assertEqual(m["exit"], 0, m)
        self.assertEqual(sorted(m["turned"]["windows"]), ["w00-24", "w04-28"])
        self.assertTrue(m["turned"]["out"].startswith(str(out / "ink-turned" / "t00" / "fake")))
        self.assertEqual(m["maps"]["f"]["path"], str(out / "ink" / "t00" / "fake" / "ink_f.tif"))
        self.assertLess(abs(st["surfaces"]["t00"]["orient"]["angle_deg"] + 25.0), 3.0)

    @unittest.skipUnless(HAVE_NUMPY, "kit ensemble needs numpy")
    def test_one_window_and_a_window_outside_the_render(self):
        st, out = self.windows_run({"where": "modal", "models": ["fake"], "variants": ["f", "r"],
                                    "layers": {"windows": [[6, 23]]}}, "one")
        m = st["surfaces"]["t00"]["ink"]["fake"]
        self.assertEqual((m["exit"], list(m["windows"])), (0, ["w06-23"]))
        self.assertEqual(json.loads(Path(m["out"], "ink.json").read_text())["window"]["layers"], [6, 23])
        self.assertTrue(m["maps"]["f"]["path"].startswith(str(out / "ink" / "t00" / "fake" / "w06-23")))
        st, _ = self.windows_run({"where": "modal", "models": ["fake", "fake2"], "variants": ["f", "r"],
                                  "layers": {"windows": [[0, 14], [20, 40]]}, "ensemble": True}, "outside")
        ink = st["surfaces"]["t00"]["ink"]
        self.assertNotEqual(ink["fake"]["windows"]["w20-40"]["exit"], 0)
        self.assertIn("not combined: 1 of 2 inputs did not finish", ink["fake"]["exit"])
        self.assertIn("not combined: 2 of 2 inputs did not finish", ink["ensemble"]["exit"])

    def external(self, grids=True, catalog_grids=False, slices=()):
        """The fake scroll's prediction as an external one: meta.json beside it (as kit surfacepred package writes
        it) and a grid folder made from its level 0, resolved as make_plan would against the fake scan."""
        write_meta(self.pred, SHAPE)
        g = grid_folder(self.d / "ext.normal-grids", slices=slices) if grids else None
        return autopipe.resolve_external(str(self.pred), str(g) if g else None,
                                         {"volume": "V1", "shape_zyx": SHAPE}, catalog_grids=catalog_grids)

    def test_an_external_prediction_is_traced_with_its_own_grids(self):
        ext = self.external()
        self.assertEqual((ext["zarr"], ext["normal_grids"]), (str(self.pred.resolve()),
                                                              str((self.d / "ext.normal-grids").resolve())))
        st, out = self.run_plan(self.plan(external=ext), until="qa")
        self.assertEqual(st["stages"]["qa"]["status"], "done", st["stages"])
        acq = st["stages"]["acquire"]["record"]
        self.assertEqual(acq["prediction"], ext["zarr"])
        self.assertEqual(acq["external_prediction"]["headers_sha256"], ext["headers_sha256"])
        rc = json.loads((out / "traces" / "receipt.json").read_text())     # the last trace's receipt
        self.assertEqual(rc["params"]["normal_grid_path"], ext["normal_grids"])
        self.assertEqual((rc["args"]["volume"], rc["args"]["normal_grids"]), (ext["zarr"], ext["normal_grids"]))
        for s in st["surfaces"].values():
            self.assertEqual(s["qa"]["data_term"], "normal grids")

    def test_an_external_prediction_changed_after_the_plan_is_refused(self):
        ext = self.external()
        plan = self.plan(external=ext)
        write_meta(self.pred, SHAPE, name="packaged again")
        st, _ = self.run_plan(plan, self.d / "changed", until="trace")
        self.assertEqual(st["stages"]["acquire"]["status"], "failed")
        self.assertIn("headers changed after the plan was made", st["stages"]["acquire"]["error"])
        self.assertNotIn("trace", st["stages"])
        write_meta(self.pred, SHAPE)
        grid_folder(self.d / "ext.normal-grids", level=0, multiscale=True)
        st, _ = self.run_plan(plan, self.d / "grids-changed", until="trace")
        self.assertEqual(st["stages"]["acquire"]["status"], "failed")
        self.assertIn("metadata.json changed after the plan was made", st["stages"]["acquire"]["error"])

    def test_the_axis_is_estimated_from_external_grids_when_the_catalog_has_none(self):
        ext = self.external(slices=range(0, 64, 10))
        self.assertEqual(ext["axis_grids"], ext["normal_grids"])
        self.assertIsNone(self.external(catalog_grids=True)["axis_grids"])   # the catalog's when it has some
        umb = {**autopipe.DEFAULTS["umbilicus"], "source": "estimate", "every": 10}
        st, out = self.run_plan(self.plan(external=ext, umbilicus=umb), until="umbilicus")
        rec = st["stages"]["umbilicus"]["record"]
        self.assertEqual((st["stages"]["umbilicus"]["status"], rec["source"], rec["estimates"]), ("done", "estimated", 7))
        saved = json.loads((out / "umbilicus.json").read_text())["kit_autopipe"]
        self.assertEqual(saved["grids"], ext["normal_grids"])

    def test_a_box_prediction_keeps_seeds_traces_and_the_axis_inside_its_box(self):
        ext = self.external(slices=range(0, 64))
        ext["box"], ext["box_source"] = [[8, 56], [0, 128], [0, 64]], "run.json"   # the half of the scroll at x < 64
        umb = {**autopipe.DEFAULTS["umbilicus"], "source": "estimate"}
        seeds = {**autopipe.DEFAULTS["seeds"], "count": 4, "z_range": None, "radius_um": [300.0, 500.0],
                 "level": 0, "min_spacing_um": 80.0}
        st, out = self.run_plan(self.plan(external=ext, umbilicus=umb, seeds=seeds), until="trace")
        self.assertEqual(st["stages"]["trace"]["status"], "done", st["stages"])
        u = st["stages"]["umbilicus"]["record"]
        # every 500th slice would meet this box never; 9 slices inside it are read instead
        self.assertEqual(u["box_axis"], {"z_range": [8, 56], "every": 5, "quality": "direction only"})
        self.assertEqual(u["estimates"], len(range(10, 56, 5)))
        sd = st["stages"]["seeds"]["record"]
        self.assertEqual((sd["box"]["z_range"], sd["box"]["yx"]), ([24, 40], [[16, 112], [16, 48]]))
        self.assertEqual(sd["box"]["margin"], 16)
        self.assertIn("left out", sd["box"]["radius_band"])
        for x, y, z in sd["seeds"]:
            self.assertTrue(16 <= x < 48 and 16 <= y < 112 and sd["box"]["z_range"][0] <= z < sd["box"]["z_range"][1],
                            (x, y, z))
        rc = json.loads((out / "traces" / "receipt.json").read_text())
        self.assertEqual({k: rc["params"][k] for k in ("z_min", "z_max", "y_min", "y_max", "x_min", "x_max")},
                         {"z_min": 8, "z_max": 55, "y_min": 0, "y_max": 127, "x_min": 0, "x_max": 63})

    def test_a_bound_the_plan_gives_wins_over_the_box(self):
        self.assertEqual(autopipe.box_trace_params([[0, 10], [0, 20], [0, 30]], {"z_max": 5, "step_size": 10}),
                         {"z_min": 0, "z_max": 5, "y_min": 0, "y_max": 19, "x_min": 0, "x_max": 29, "step_size": 10})
        self.assertTrue(autopipe.in_box([5, 5, 5], [[0, 10], [0, 10], [0, 10]]))
        self.assertFalse(autopipe.in_box([5, 5, 5], [[0, 10], [0, 10], [0, 10]], margin=6))
        self.assertFalse(autopipe.in_box([5, 5, 10], [[0, 10], [0, 20], [0, 20]]))   # z is the last of x, y, z

    def repair_run(self, name, share=0.5, fail_after=False, reasons=None, unmeasured=()):
        """A one-trace run whose trace qa rejects for a sheet switch (an extra reason added to the real record),
        under qa.repair; fail_after makes the cut copy fail too. reasons replaces the extra reason, and the ones
        in unmeasured are marked as checks that could not run."""
        real = autopipe.Run.qa_one

        def qa_one(run, sid, s):
            rec = real(run, sid, s)
            if "/repaired/" not in s["surface"] or fail_after:
                rec["reasons"].extend(reasons or ["winding audit: 2 full-turn fusions, 0 broad (a sheet switch or "
                                                  "merger)"])
                if unmeasured:
                    rec["unmeasured"] = rec.get("unmeasured", []) + list(unmeasured)
                rec["accepted"] = False
            return rec

        qa = {**autopipe.DEFAULTS["qa"], "require_seated": "none", "windaudit": "off", "windows": 1,
              "repair": {"method": "switchfix", "min_area_share": share}}
        plan = self.plan(seeds={**autopipe.DEFAULTS["seeds"], "points": [self.TRIM_SEED]}, qa=qa)
        with mock.patch.object(autopipe.Run, "qa_one", qa_one):
            return self.run_plan(plan, self.d / name, until="qa")

    @unittest.skipUnless(HAVE_LABELXFER, "needs numpy, scipy and tifffile")
    def test_a_trace_with_a_sheet_switch_is_repaired_and_checked_again(self):
        st, out = self.repair_run("repair")
        s = st["surfaces"]["t00"]
        self.assertTrue(s["accepted"], s["qa"])
        self.assertEqual(s["surface"], str(out / "repaired" / "t00"))
        self.assertTrue(s["surface_traced"].endswith("t00"))
        self.assertNotEqual(s["surface_traced"], s["surface"])
        rep = s["qa"]["repair"]
        self.assertEqual((rep["done"], rep["taken"], rep["method"]), (True, True, "switchfix"))
        self.assertGreaterEqual(rep["area_share"], 0.5)
        self.assertIn("winding audit: 2 full-turn fusions", s["qa"]["before_repair"]["reasons"][-1])
        self.assertTrue((out / "repaired" / "t00.json").is_file())
        self.assertTrue(Path(s["surface_traced"], "x.tif").is_file())        # the trace itself is kept

    @unittest.skipUnless(HAVE_LABELXFER, "needs numpy, scipy and tifffile")
    def test_no_repair_when_the_switch_check_could_not_run(self):
        # rejected for its seating, which the rule decided, while its self-crossings went unmeasured: the cut is
        # not made, and the rejection stands as the rule's
        miss = "self-intersections: not measured (vc_tifxyz_selfcross is not installed)"
        st, out = self.repair_run("repair-unmeasured", reasons=["seating: unseated", miss], unmeasured=[miss])
        s = st["surfaces"]["t00"]
        self.assertFalse(s["accepted"])
        self.assertNotIn("repair", s["qa"])
        self.assertEqual(s["qa"]["failure"]["kind"], "ours")
        self.assertFalse((out / "repaired").exists())

    @unittest.skipUnless(HAVE_LABELXFER, "needs numpy, scipy and tifffile")
    def test_a_repair_that_fails_qa_or_keeps_too_little_leaves_the_rejection(self):
        st, _ = self.repair_run("repair-fails", fail_after=True)
        self.assertEqual(st["stages"]["qa"]["status"], "failed")
        q = st["surfaces"]["t00"]["qa"]
        self.assertFalse(q["accepted"])
        self.assertFalse(q["repair"]["taken"])
        self.assertIn("the cut copy fails qa", q["repair"]["why"])
        self.assertNotIn("surface_traced", st["surfaces"]["t00"])
        st, _ = self.repair_run("repair-small", share=1.0)
        q = st["surfaces"]["t00"]["qa"]
        if q["repair"]["area_share"] < 1.0:
            self.assertFalse(q["repair"]["taken"])
            self.assertIn("of the area, under 1.0", q["repair"]["why"])

    def test_no_repair_without_a_switch_or_when_not_asked(self):
        self.assertEqual(autopipe.switch_reasons({"reasons": ["seating: unseated", "self-intersections: 3"]}),
                         ["self-intersections: 3"])
        self.assertEqual(autopipe.switch_reasons({"reasons": ["self-intersections: not measured (x)"],
                                                  "failure": {"kind": "infrastructure"}}), [])
        # a decided rejection (seating) beside a switch check that could not run: no measured switch to repair
        miss = "self-intersections: not measured (x)"
        self.assertEqual(autopipe.switch_reasons({"reasons": ["seating: unseated", miss], "unmeasured": [miss]}), [])
        self.assertEqual(autopipe.switch_reasons({"reasons": ["winding audit: 2 full-turn fusions", miss],
                                                  "unmeasured": [miss]}), ["winding audit: 2 full-turn fusions"])
        with self.assertRaisesRegex(autopipe.AutoError, "qa.repair.method"):
            autopipe.make_plan("PHercTest", {"qa": {"repair": {"method": "glue"}}}, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "min_area_share"):
            autopipe.make_plan("PHercTest", {"qa": {"repair": {"min_area_share": 0}}}, cat=catalog())
        base = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertNotIn("repair", base["settings"]["qa"])                    # absent: frozen digests unchanged
        on = autopipe.make_plan("PHercTest", {"qa": {"repair": True}}, cat=catalog(), created="2026-10-09T00:00:00Z")
        self.assertEqual(on["settings"]["qa"]["repair"], {"method": "switchfix", "min_area_share": 0.5})
        self.assertNotEqual(on["digest"], base["digest"])

    def published(self, mode):
        """A run whose only surface stands in for a published segment ("seg"), under a rule it fails."""
        plan = self.plan(qa={"require_seated": "none", "windaudit": "off", "windows": 1, "max_selfcross": -1,
                             "published": mode})
        out = self.d / f"run-{mode}"
        self.run_plan(plan, out, until="trace")
        st = json.loads((out / "state.json").read_text())
        st["surfaces"] = {"seg": dict(st["surfaces"]["t00"], origin="published segment (stand-in)")}
        (out / "state.json").write_text(json.dumps(st))
        return self.run_plan(plan, out, until="qa")[0]

    def test_a_published_segment_is_checked_but_not_gated_by_default(self):
        st = self.published("record")
        self.assertEqual(st["stages"]["qa"]["status"], "done")
        qa = st["surfaces"]["seg"]["qa"]
        self.assertEqual((qa["accepted"], qa["gated"], qa["rule_verdict"]), (True, False, "rejected"))
        self.assertIn("self-intersections: 0", qa["reasons"])

    def test_a_published_segment_can_be_gated_like_a_trace(self):
        st = self.published("gate")
        self.assertEqual(st["stages"]["qa"]["status"], "failed")
        self.assertIn("self-intersections", st["stages"]["qa"]["error"])

    def test_the_runner_runs_a_handed_off_ink_stage(self):
        plan = self.plan(ink={"where": "modal", "models": ["fake"], "variants": ["f", "r"]})
        st, out = self.run_plan(plan)
        self.assertEqual(st["stages"]["ink"]["status"], "handoff")
        model = self.d / "model.py"
        model.write_text(fakes.INK_MODEL)
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({"fake": {"engine": "command", "command": [
            sys.executable, str(model), "{layers}", "{output}", "{reverse}"]}}))
        self.ctx = self.context(FAKE_TRACE_ARC=f"{AXIS[0]},{AXIS[1]}", KIT_AUTOPIPE_RUNNER="modal")
        st, _ = self.run_plan(plan, out)
        self.assertEqual(st["stages"]["ink"]["status"], "done", st["stages"]["ink"])
        for s in st["surfaces"].values():
            maps = s["ink"]["fake"]
            self.assertEqual(maps["exit"], 0, maps)
            self.assertEqual(sorted(maps["maps"]), ["f", "r"])
        self.assertEqual(st["stages"]["score"]["status"], "skipped")     # no labels on a traced surface

    def test_a_rerun_that_can_ink_takes_back_a_handed_off_ink_stage(self):
        # the release README's path: with no ink Python a run stops at ink; the same folder run again where the
        # models are registered and the ink Python has torch does ink and score itself, with no Modal runner
        plan = self.plan(ink={"where": "auto", "models": ["fake"], "variants": ["f", "r"]})
        without = mock.patch.object(vc3d_agent, "ink_env", return_value={"python": "py", "torch": None})
        with without:
            st, out = self.run_plan(plan)
        self.assertEqual(st["stages"]["ink"]["status"], "handoff")
        self.assertIn("run the same folder again", st["stages"]["ink"]["record"]["why"])
        model = self.d / "model.py"
        model.write_text(fakes.INK_MODEL)
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({"fake": {"engine": "command", "command": [
            sys.executable, str(model), "{layers}", "{output}", "{reverse}"]}}))
        with without:      # registered, but still no torch: it stays handed off and nothing is scored
            st, _ = self.run_plan(plan, out)
        self.assertEqual(st["stages"]["ink"]["status"], "handoff")
        self.assertNotIn("score", st["stages"])
        with mock.patch.object(vc3d_agent, "ink_env", return_value={"python": sys.executable, "torch": "2"}):
            st, _ = self.run_plan(plan, out)
        self.assertEqual(st["stages"]["ink"]["status"], "done", st["stages"]["ink"])
        for s in st["surfaces"].values():
            self.assertEqual(sorted(s["ink"]["fake"]["maps"]), ["f", "r"], s["ink"]["fake"])
        self.assertEqual(st["stages"]["score"]["status"], "skipped")     # no labels on a traced surface
        # a plan that sends ink to Modal keeps it there, whatever this machine has
        plan = self.plan(ink={"where": "modal", "models": ["fake"], "variants": ["f", "r"]})
        with mock.patch.object(vc3d_agent, "ink_env", return_value={"python": sys.executable, "torch": "2"}):
            st, _ = self.run_plan(plan, self.d / "run2")
            st, _ = self.run_plan(plan, self.d / "run2")
        self.assertEqual(st["stages"]["ink"]["status"], "handoff")

    # score.transfer on fakes: published w00 stands in as a 16 x 60 piece of the fake cylinder (z 0 to 60, most of
    # the way round, 4 voxels between vertices: canvas 64 x 240); ag896 as a piece 16 voxels outside it, beyond
    # the gap tolerance, so nothing is carried from it.
    XFER_KEYS = {"0841-w00": (RADIUS, 16, 60), "0841-ag896": (RADIUS + 16.0, 16, 20)}

    def transfer_plan(self, min_area_cm2=0.0002, **tr):
        transfer = {"segments": list(self.XFER_KEYS), "min_area_cm2": min_area_cm2, "displace_mm": 0.1,
                    "references": {"0841-w00": "run"}, "bootstrap": {"draws": 50, "block_px": 8, "seed": 7}, **tr}
        plan = self.plan(qa={"require_seated": "none", "windaudit": "off", "windows": 1},
                         ink={"where": "modal", "models": ["fake"], "variants": ["f", "r", "s"]},
                         score={"inner": 4, "transfer": transfer})
        plan["resolved"]["transfer"] = {
            key: {"segment": key, "volume": "V1", "labels": f"fake/{key}", "crop": [0, 64, 0, 64],
                  "surface_shape": [rows * 4, cols * 4], "surface_volume": None}
            for key, (_, rows, cols) in self.XFER_KEYS.items()}
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        return plan

    def place_published(self, out):
        """What acquire would fetch: each segment's mesh in the scan's frame and its labels (ink in 2 x 2 blocks
        at level 2, half the canvas), so no fetch is made."""
        rng = np.random.default_rng(11)
        for key, (rad, rows, cols) in self.XFER_KEYS.items():
            def point(r, c, rad=rad):
                a = 0.25 + c * 4.0 / rad
                return AXIS[0] + rad * math.cos(a), AXIS[1] + rad * math.sin(a), 4.0 * r
            fakes.write_tifxyz(out / "published" / f"{key}.tifxyz", point, rows, cols, 0.25)
            ink = np.kron(rng.random((rows, cols)) > 0.5, np.ones((2, 2), bool))
            sup = np.ones_like(ink)
            sup[:2], sup[-2:] = False, False
            for name, data in (("inklabels", ink), ("supervision", sup)):
                g = zarr.open_group(str(out / "labels" / key / f"{name}.zarr"), mode="w")
                g.create_array("2", data=data.astype(np.uint8) * 255)

    def use_runner(self):
        model = self.d / "model.py"
        model.write_text(fakes.INK_MODEL)
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({"fake": {"engine": "command", "command": [
            sys.executable, str(model), "{layers}", "{output}", "{reverse}"]}}))
        self.ctx = self.context(FAKE_TRACE_ARC=f"{AXIS[0]},{AXIS[1]}", KIT_AUTOPIPE_RUNNER="modal",
                                FAKE_RENDER_VC3D_MASK="1")

    def vc3d_mask(self):
        """The fake renderer leaving empty the pixels VC3D leaves empty, so the canvas check passes."""
        self.ctx = self.context(FAKE_TRACE_ARC=f"{AXIS[0]},{AXIS[1]}", FAKE_RENDER_VC3D_MASK="1")

    @unittest.skipUnless(HAVE_LABELXFER, "needs numpy, scipy, tifffile and zarr")
    def test_own_traces_are_scored_on_carried_labels(self):
        self.vc3d_mask()
        plan = self.transfer_plan()
        # a report surface on this scan (as make_plan resolves 0841-ag405 on PHerc0841): its mesh, here w00's own
        # piece, so the trace overlaps it; its labels are never fetched
        plan["resolved"]["report_overlap"] = {"0841-ag405": {"segment": "ag405", "volume": "V1"}}
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        out = self.d / "run-xfer"
        self.place_published(out)
        import shutil
        shutil.copytree(out / "published" / "0841-w00.tifxyz", out / "report-surfaces" / "0841-ag405.tifxyz")
        st, _ = self.run_plan(plan, out, until="qa")
        self.assertEqual(sorted(st["surfaces"]), ["ref-0841-w00", "t00", "t01"])
        acq = st["stages"]["acquire"]["record"]["transfer"]
        self.assertEqual(acq["0841-w00"]["reference_surface"], "ref-0841-w00")
        for key in self.XFER_KEYS:       # the carrying's identity and displaced checks, on the run's own copies
            self.assertTrue(acq[key]["check"]["passes"], acq[key]["check"])
        # t01 is rejected: it must still be on record in the scores, with the reason
        state = json.loads((out / "state.json").read_text())
        state["surfaces"]["t01"]["accepted"] = False
        state["surfaces"]["t01"]["qa"]["reasons"] = ["planted rejection"]
        (out / "state.json").write_text(json.dumps(state))
        st, _ = self.run_plan(plan, out)
        self.assertEqual(st["stages"]["ink"]["status"], "handoff")
        carried = st["stages"]["render"]["record"]["label_transfer"]
        self.assertEqual(sorted(carried), ["t00"])                   # traces only, accepted and rendered
        self.assertGreater(carried["t00"]["0841-w00"], 0.0002)
        self.assertEqual(carried["t00"]["0841-ag896"], 0.0)          # the sheet 16 voxels out lends nothing
        t00 = st["surfaces"]["t00"]
        self.assertEqual(t00["transfer"]["0841-w00"]["share_refused_by_normal_test"], 0.0)
        self.assertTrue((out / "transfer" / "t00" / "0841-w00" / "record.json").is_file())
        self.assertEqual(st["surfaces"]["ref-0841-w00"]["flatten"]["used"], "original")
        self.assertEqual(sorted(json.loads((out / "modal-job.json").read_text())["renders"]), ["ref-0841-w00", "t00"])
        # the runner inks every rendered surface and scores
        self.use_runner()
        st, _ = self.run_plan(plan, out)
        self.assertEqual(st["stages"]["score"]["status"], "done", st["stages"]["score"])
        sc = json.loads((out / "scores.json").read_text())
        self.assertEqual(sc["rule"]["segments"], ["0841-w00", "0841-ag896"])
        ref = sc["references"]["0841-w00"]["models"]["fake"]
        self.assertTrue(0.0 <= ref["whole"]["forward"]["auc"] <= 1.0 and "auc" in ref["whole"]["control"], ref)
        self.assertEqual(sc["surfaces"]["t01"]["scorable"], False)
        self.assertIn("rejected by qa: planted rejection", sc["surfaces"]["t01"]["why"])
        segs = sc["surfaces"]["t00"]["segments"]
        self.assertEqual(segs["0841-ag896"]["scorable"], False)
        self.assertIn("under score.transfer.min_area_cm2", segs["0841-ag896"]["why"])
        w00 = segs["0841-w00"]
        self.assertTrue(w00["scorable"])
        m = w00["models"]["fake"]
        for k in ("forward", "reverse", "shuffled"):
            self.assertTrue(0.0 <= m[k]["auc"] <= 1.0, m)
            self.assertEqual(m[k]["ink_px"] + m[k]["background_px"], m["labelled_px"])
        self.assertEqual(len(m["displaced"]["directions"]), 4)
        self.assertEqual(m["reference"]["map"], st["surfaces"]["ref-0841-w00"]["ink"]["fake"]["maps"]["f"]["path"])
        self.assertEqual(m["reference"]["on_carried_pixels"]["ink_px"], m["forward"]["ink_px"])
        self.assertEqual((m["paired"]["draws"], m["paired"]["block_px"], m["paired"]["seed"]), (50, 8, 7))
        self.assertEqual(len(m["paired"]["ci95"]), 2)
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(set(report["surfaces"]["t00"]["transfer"]), set(self.XFER_KEYS))
        # every planned trace on record, in launch order, with its seed; the canvas check and coverage per trace
        self.assertEqual(sc["traces"], {"planned": ["t00", "t01"], "repeats": 1, "seeds": {"t00": 0, "t01": 1}})
        self.assertEqual(sc["surfaces"]["t01"]["failure"]["kind"], "ours")
        self.assertTrue(sc["surfaces"]["t00"]["canvas_check"]["passes"], sc["surfaces"]["t00"]["canvas_check"])
        self.assertEqual(sc["surfaces"]["t00"]["canvas_check"]["agreement"], 1.0)
        cov = w00["coverage"]
        for k in ("share_of_published_supervision_reached", "carried_cm2", "rendered_cm2", "gap_vox_median",
                  "abs_offset_labelled_vox", "carried_share_of_rendered"):
            self.assertIsNotNone(cov[k], k)
        # the report surface: where the trace lies on it, from its mesh alone
        over = sc["surfaces"]["t00"]["report_overlap"]["0841-ag405"]
        self.assertEqual(over["labels"], "never read")
        self.assertGreater(over["overlap_cm2"], 0.0)
        self.assertTrue(Path(over["mask"]).is_file())
        self.assertFalse((out / "labels" / "0841-ag405").exists())
        self.assertIn("never fetched", st["stages"]["acquire"]["record"]["transfer"]["0841-ag405"]["labels"])
        self.assertIn("0841-ag405", report["surfaces"]["t00"]["report_overlap"])
        # the preregistered readout reads this record: the fake reader is not the published w00 run, so the
        # pipeline check (0.7479 on w00's own labels) voids it, as it must; it is read for t00 by name, since
        # this plan grows one trace a seed, not the preregistered three
        from kit import labelxfer
        self.assertEqual(sc["checks"]["0841-w00"]["passes"], True)
        self.assertEqual(sc["plan"], plan["digest"])
        res = labelxfer.readout(sc, model="fake")
        self.assertEqual(res["verdict"], "VOID")
        self.assertTrue(any("not the preregistered plan" in r for r in res["reasons"]), res)
        res = labelxfer.readout(sc, surface="t00", model="fake")
        self.assertEqual(res["verdict"], "VOID")
        self.assertTrue(any("pipeline check" in r for r in res["reasons"]), res)
        self.assertEqual(res["numbers"]["forward"], m["forward"]["auc"])
        self.assertEqual(res["numbers"]["coverage"]["report_overlap_cm2"], {"0841-ag405": over["overlap_cm2"]})

    @unittest.skipUnless(HAVE_LABELXFER, "needs numpy, scipy, tifffile and zarr")
    def test_a_render_off_the_canvas_formula_carries_nothing(self):
        # the fake renderer as it is fills the grid's border ring, which VC3D leaves empty: the canvas check
        # sees the render disagree with the formula, and no label is carried (an infrastructure failure: VOID)
        plan = self.transfer_plan(references=None)
        out = self.d / "run-xfer-canvas"
        self.place_published(out)
        st, _ = self.run_plan(plan, out)
        for sid in ("t00", "t01"):
            cc = st["surfaces"][sid]["canvas_check"]
            self.assertFalse(cc["passes"])
            self.assertLess(cc["agreement"], 0.999)
            for key in self.XFER_KEYS:
                self.assertIn("canvas check failed", st["surfaces"][sid]["transfer"][key]["error"])
        self.use_runner()
        st, _ = self.run_plan(plan, out)
        sc = json.loads((out / "scores.json").read_text())
        for e in sc["surfaces"]["t00"]["segments"].values():
            self.assertFalse(e["scorable"])
            self.assertEqual(e["failure"]["kind"], "infrastructure")
            self.assertIn("canvas check failed", e["why"])

    @unittest.skipUnless(HAVE_LABELXFER, "needs numpy, scipy, tifffile and zarr")
    def test_a_trace_under_the_minimum_area_is_recorded_not_scorable(self):
        self.vc3d_mask()
        plan = self.transfer_plan(min_area_cm2=1.0, references=None)
        out = self.d / "run-xfer-small"
        self.place_published(out)
        self.use_runner()
        st, _ = self.run_plan(plan, out)
        self.assertEqual(st["stages"]["score"]["status"], "done", st["stages"]["score"])
        sc = json.loads((out / "scores.json").read_text())
        self.assertEqual(sorted(sc["surfaces"]), ["t00", "t01"])
        for entry in sc["surfaces"].values():
            for e in entry["segments"].values():
                self.assertFalse(e["scorable"])
                self.assertIn("under score.transfer.min_area_cm2 1.0", e["why"])
                self.assertIn("labelled_cm2", e["coverage"])
                self.assertEqual(e["failure"]["kind"], "ours")

    def test_repeats_and_every_planned_trace_on_record_with_who_stopped_it(self):
        # seed 0 on the sheet, seed 1 on the axis (off the prediction, nothing near it): two traces each
        off = [AXIS[0], AXIS[1], 40]
        plan = self.plan(seeds={**autopipe.DEFAULTS["seeds"], "points": [self.TRIM_SEED, off]},
                         trace={**autopipe.DEFAULTS["trace"], "repeats": 2})
        st, out = self.run_plan(plan, until="render")
        self.assertEqual([p["sid"] for p in st["planned_traces"]], ["t00-r0", "t00-r1", "t01-r0", "t01-r1"])
        self.assertEqual(sorted(st["surfaces"]), ["t00-r0", "t00-r1"])
        self.assertEqual((st["surfaces"]["t00-r1"]["seed_index"], st["surfaces"]["t00-r1"]["repeat"]), (0, 1))
        self.assertIn("repeat 1 of 2", st["surfaces"]["t00-r1"]["origin"])
        for sid in ("t01-r0", "t01-r1"):
            f = st["trace_failures"][sid]
            self.assertEqual(f["kind"], "ours")
            self.assertIn("seed check refused it", f["reason"])
        entries = {e["sid"]: e for e in autopipe.trace_entries(st)}
        self.assertTrue(entries["t00-r0"]["rendered"] and entries["t00-r1"]["rendered"])
        self.assertEqual(entries["t01-r0"]["failure"]["stage"], "trace")

    def test_who_stopped_the_trace_stage_decides_its_kind_and_a_retry(self):
        self.ctx.env["FAKE_TRACE_EMPTY"] = "1"          # the tracer runs and writes nothing: ours, and final
        st, out = self.run_plan(self.plan(), until="trace")
        self.assertEqual((st["stages"]["trace"]["status"], st["stages"]["trace"]["kind"]), ("failed", "ours"))
        self.assertEqual({f["kind"] for f in st["trace_failures"].values()}, {"ours"})
        log = self.d / "fake.log"
        self.ctx.env.pop("FAKE_TRACE_EMPTY")
        self.ctx.env["FAKE_LOG"] = str(log)
        st, _ = self.run_plan(self.plan(), out, until="trace")
        self.assertEqual(st["stages"]["trace"]["status"], "failed")
        self.assertFalse(log.exists() and "vc_grow_seg_from_seed" in log.read_text())
        # the trace tool could not run: the infrastructure's, tried again when the stage runs again
        real = autopipe.Run.call

        def broken(run, name, args):
            if name == "trace":
                raise vc3d_agent.ToolError("normal-grid fetch returned HTTP 0: connection reset")
            return real(run, name, args)
        out2 = self.d / "run2"
        with mock.patch.object(autopipe.Run, "call", broken):
            st, _ = self.run_plan(self.plan(), out2, until="trace")
        self.assertEqual((st["stages"]["trace"]["status"], st["stages"]["trace"]["kind"]), ("failed", "infrastructure"))
        self.assertEqual({f["kind"] for f in st["trace_failures"].values()}, {"infrastructure"})
        st, _ = self.run_plan(self.plan(), out2, until="trace")
        self.assertEqual(st["stages"]["trace"]["status"], "done")
        self.assertEqual(sorted(st["surfaces"]), ["t00", "t01"])
        self.assertEqual(st["trace_failures"], {})

    def test_a_render_tool_error_is_the_infrastructures(self):
        real = autopipe.Run.call

        def broken(run, name, args):
            if name == "render" and Path(str(args.get("surface"))).name.startswith("t00"):
                raise vc3d_agent.ToolError("cannot open remote volume: HTTP 503")
            return real(run, name, args)
        with mock.patch.object(autopipe.Run, "call", broken):
            st, out = self.run_plan(self.plan(), until="render")
        self.assertEqual(st["stages"]["render"]["status"], "done")          # t01 rendered
        f = st["surfaces"]["t00"]["render"]["failure"]
        self.assertEqual(f["kind"], "infrastructure")
        e = {x["sid"]: x for x in autopipe.trace_entries(st)}
        self.assertEqual((e["t00"]["failure"]["stage"], e["t00"]["failure"]["kind"]), ("render", "infrastructure"))
        self.assertTrue(e["t01"]["rendered"])
        # a rerun of the stage renders it (an infrastructure failure is tried again)
        st["stages"].pop("render")
        (out / "state.json").write_text(json.dumps(st))
        st, _ = self.run_plan(self.plan(), out, until="render")
        self.assertTrue(st["surfaces"]["t00"]["render"].get("zarr"))
        self.assertNotIn("failure", st["surfaces"]["t00"]["render"])

    # Who decided a failure, end to end on the fakes and read back by the preregistered readout from the state
    # alone (kit labelxfer readout --state): one seed traced three times, as own0841's arm A, so the readout takes
    # the run for the preregistered plan and its primary is the first t00 repeat qa accepts

    def three_repeats(self, **over):
        return self.plan(seeds={**autopipe.DEFAULTS["seeds"], "points": [self.TRIM_SEED]},
                         trace={**autopipe.DEFAULTS["trace"], "repeats": 3}, **over)

    @staticmethod
    def per_trace(setups):
        """A stand-in for Run.call that runs each trace's check_surface under its own fake environment: setups maps
        a surface id to extra environment, or to an exception check_surface raises for it instead."""
        real = autopipe.Run.call

        def call(run, name, args):
            sid = next((k for k in setups if k in Path(str(args.get("surface"))).parts), None)
            if name != "check_surface" or sid is None:
                return real(run, name, args)
            if isinstance(setups[sid], BaseException):
                raise setups[sid]
            saved = dict(run.ctx.env)
            run.ctx.env.update(setups[sid])
            try:
                return real(run, name, args)
            finally:
                run.ctx.env.clear()
                run.ctx.env.update(saved)
        return call

    def qa_readout(self, plan, setups, name):
        from kit import labelxfer
        with mock.patch.object(autopipe.Run, "call", self.per_trace(setups)):
            st, out = self.run_plan(plan, self.d / name, until="qa")
        self.assertEqual([p["sid"] for p in st["planned_traces"]], ["t00-r0", "t00-r1", "t00-r2"])
        return st, {e["sid"]: e for e in autopipe.trace_entries(st)}, labelxfer.readout(None, state=st)

    def test_a_seating_window_whose_probe_did_not_run_is_the_infrastructures(self):
        # t00-r0: the probe exits 1 in its first window (a dropped chunk fetch) and its other window is seated, so
        # the rejection rests only on a window that was never measured; t00-r1 and t00-r2: rejected by a check
        # that ran (3 transverse self-intersections)
        plan = self.three_repeats(qa={"require_seated": "all", "windaudit": "off", "windows": 2})
        probe = {"FAKE_FAIL_FILE": str(self.d / "probe-fails"), "FAKE_FAIL_TIMES": "1"}
        dirty = {"FAKE_SELFCROSS": "dirty"}
        st, e, res = self.qa_readout(plan, {"t00-r0": probe, "t00-r1": dirty, "t00-r2": dirty}, "seat")
        q = st["surfaces"]["t00-r0"]["qa"]
        wins = st["surfaces"]["t00-r0"]["qa"]["seating"]
        self.assertEqual((q["accepted"], wins["verdict"], wins["seated_windows"]), (False, "partly seated", "1 of 2"))
        self.assertEqual(q["reasons"], ["seating: partly seated (1 of 2 windows not measured: the probe exited 1)"])
        self.assertEqual(q["failure"]["kind"], "infrastructure")
        self.assertEqual(q["unmeasured"], q["reasons"])
        self.assertEqual((e["t00-r0"]["failure"]["stage"], e["t00-r0"]["failure"]["kind"]), ("qa", "infrastructure"))
        for sid in ("t00-r1", "t00-r2"):
            self.assertEqual((st["surfaces"][sid]["qa"]["failure"]["kind"], e[sid]["failure"]["kind"]),
                             ("ours", "ours"), sid)
        self.assertEqual((st["stages"]["qa"]["status"], st["stages"]["qa"]["kind"]), ("failed", "infrastructure"))
        self.assertEqual(res["verdict"], "VOID", res)
        self.assertIn("t00-r0 stopped for a reason of the infrastructure", res["reasons"][0])
        # the same lost window beside a check that ran and rejects it: the rule decided, ours, and the readout FAILs
        st, e, res = self.qa_readout(plan, {"t00-r0": {**probe, "FAKE_FAIL_FILE": str(self.d / "probe-fails-2"),
                                                       **dirty}, "t00-r1": dirty, "t00-r2": dirty}, "seat-decided")
        q = st["surfaces"]["t00-r0"]["qa"]
        self.assertEqual(q["reasons"], ["self-intersections: 3", "seating: partly seated (1 of 2 windows not "
                                                                  "measured: the probe exited 1)"])
        self.assertEqual((q["failure"]["kind"], e["t00-r0"]["failure"]["kind"]), ("ours", "ours"))
        self.assertEqual(res["verdict"], "FAIL", res)

    def test_a_self_intersection_check_with_no_report_is_the_infrastructures(self):
        # t00-r0: vc_tifxyz_selfcross exits 1 and writes no report; the others have 3 self-intersections
        plan = self.three_repeats()
        dirty = {"FAKE_SELFCROSS": "dirty"}
        st, e, res = self.qa_readout(plan, {"t00-r0": {"FAKE_SELFCROSS": "crash"}, "t00-r1": dirty, "t00-r2": dirty},
                                     "selfcross")
        q = st["surfaces"]["t00-r0"]["qa"]
        self.assertFalse(q["accepted"])
        self.assertEqual(len(q["reasons"]), 1, q["reasons"])
        self.assertIn("self-intersections: not measured (vc_tifxyz_selfcross exited 1 with no readable report",
                      q["reasons"][0])
        self.assertEqual((q["failure"]["kind"], e["t00-r0"]["failure"]["kind"]), ("infrastructure", "infrastructure"))
        self.assertEqual(e["t00-r1"]["failure"]["kind"], "ours")
        self.assertEqual(res["verdict"], "VOID", res)
        # all three rejected by the check that ran: FAIL
        st, e, res = self.qa_readout(plan, {"t00-r0": dirty, "t00-r1": dirty, "t00-r2": dirty}, "selfcross-ran")
        self.assertEqual({x["failure"]["kind"] for x in e.values()}, {"ours"})
        self.assertEqual(res["verdict"], "FAIL", res)

    def test_a_qa_tool_error_is_the_infrastructures(self):
        plan = self.three_repeats()
        dirty = {"FAKE_SELFCROSS": "dirty"}
        st, e, res = self.qa_readout(plan, {"t00-r0": vc3d_agent.ToolError("cannot open remote volume: HTTP 503"),
                                            "t00-r1": dirty, "t00-r2": dirty}, "qa-error")
        q = st["surfaces"]["t00-r0"]["qa"]
        self.assertEqual((q["accepted"], q["failure"]["kind"]), (False, "infrastructure"))
        self.assertIn("check failed: cannot open remote volume", q["reasons"][0])
        self.assertEqual((e["t00-r0"]["failure"]["stage"], e["t00-r0"]["failure"]["kind"]), ("qa", "infrastructure"))
        self.assertEqual(res["verdict"], "VOID", res)

    def test_a_renderer_that_exits_non_zero_is_ours(self):
        # every repeat accepted, so t00-r0 is the primary; the fake renderer exits 1 on the render stage's first
        # call, which is t00-r0's (no retries on a local volume)
        from kit import labelxfer
        plan = self.three_repeats()
        st, out = self.run_plan(plan, until="flatten")
        self.assertTrue(all(s["accepted"] for s in st["surfaces"].values()))
        self.ctx.env.update(FAKE_FAIL_FILE=str(self.d / "render-fails"), FAKE_FAIL_TIMES="1")
        st, _ = self.run_plan(plan, out, until="render")
        self.assertEqual(st["stages"]["render"]["status"], "done")        # t00-r1 and t00-r2 rendered
        f = st["surfaces"]["t00-r0"]["render"]["failure"]
        self.assertEqual((f["kind"], f["reason"]), ("ours", "the renderer exited 1"))
        e = {x["sid"]: x for x in autopipe.trace_entries(st)}
        self.assertEqual((e["t00-r0"]["failure"]["stage"], e["t00-r0"]["failure"]["kind"]), ("render", "ours"))
        self.assertTrue(e["t00-r1"]["rendered"] and e["t00-r2"]["rendered"])
        res = labelxfer.readout(None, state=st)
        self.assertEqual((res["verdict"], res["numbers"]["surface"]), ("FAIL", "t00-r0"), res)

    def test_a_stage_error_that_names_no_kind_is_the_infrastructures(self):
        from kit import labelxfer
        for k, (stage, exc) in enumerate((("acquire", OSError("No space left on device")),
                                          ("umbilicus", autopipe.AutoError("the axis fit failed")),
                                          ("umbilicus", autopipe.AutoError("no axis", kind="ours")))):
            with mock.patch.object(autopipe.Run, f"s_{stage}", side_effect=exc):
                st, _ = self.run_plan(self.three_repeats(), self.d / f"stage{k}", until="seeds")
            want = getattr(exc, "kind", None) or "infrastructure"
            self.assertEqual((st["stages"][stage]["status"], st["stages"][stage]["kind"]), ("failed", want), k)
            self.assertNotIn("seeds", st["stages"])
            res = labelxfer.readout(None, state=st)
            self.assertEqual(res["verdict"], "VOID" if want == "infrastructure" else "FAIL", res)
            self.assertIn(f"the {stage} stage failed", res["reasons"][0])

    def test_another_plan_in_the_same_folder_is_refused(self):
        self.run_plan(self.plan(), until="seeds")
        with self.assertRaisesRegex(autopipe.AutoError, "run of another plan"):
            self.run_plan(self.plan(trace={"generations": 9}))

    def test_a_failing_check_rejects_and_stops_the_run(self):
        self.ctx.env["FAKE_SELFCROSS"] = "dirty"
        st, _ = self.run_plan(self.plan())
        self.assertEqual(st["stages"]["qa"]["status"], "failed")
        self.assertIn("self-intersections: 3", st["stages"]["qa"]["error"])
        self.assertNotIn("render", st["stages"])
        self.assertFalse(any(s["accepted"] for s in st["surfaces"].values()))

    def test_a_flattening_that_distorts_is_not_used(self):
        stretched = autopipe._merge(autopipe.DEFAULTS["flatten"], {"max_area_ratio": 0.5})
        st, _ = self.run_plan(self.plan(flatten=stretched), until="flatten")
        for s in st["surfaces"].values():
            self.assertEqual(s["flatten"]["used"], "original")
            self.assertFalse(s["flatten"]["passes"])
            self.assertEqual(s["render_surface"], s["surface"])
            # the original that goes on instead is held to the same limits, from the measurement already made
            d = s["flatten"]["render_distortion"]
            self.assertFalse(d["passes"])
            self.assertNotIn("distortion", d)                        # it is the record's "before"
            self.assertIn("fails the flatten limits: area ratio 0.9996 is outside [0.8, 0.5]", d["warning"])

    def stretched(self, out, strict=None, scale=(0.5, 0.5), seg=False, flatten=False):
        """A one-trace run with flattening disabled (unless flatten) whose trace declares a grid scale that is not
        its vertex spacing (scale given; the fake tracer's vertices are 4 voxels apart, scale 0.25), as villa's
        spiral fit writes its windings; then the rest of the run. scale None leaves the trace as it is; () drops
        the scale."""
        over = {"seeds": {**autopipe.DEFAULTS["seeds"], "points": [self.TRIM_SEED]},
                "flatten": {**autopipe.DEFAULTS["flatten"], "enabled": flatten}}
        if strict is not None:
            over["strict"] = strict
        plan = self.plan(**over)
        self.run_plan(plan, out, until="trace" if seg else "qa")
        st = json.loads((out / "state.json").read_text())
        sid = "t00"
        if seg:     # the trace stands in for a published segment
            st["surfaces"] = {"seg": dict(st["surfaces"]["t00"], origin="published segment (stand-in)")}
            (out / "state.json").write_text(json.dumps(st))
            sid = "seg"
        if scale is not None:
            mf = Path(st["surfaces"][sid]["surface"], "meta.json")
            meta = json.loads(mf.read_text())
            if scale:
                meta["scale"] = list(scale)
            else:
                del meta["scale"]
            mf.write_text(json.dumps(meta))
        st, _ = self.run_plan(plan, out)
        return st, st["surfaces"][sid]

    def test_an_unflattened_surface_is_measured_and_warned_about(self):
        st, s = self.stretched(self.d / "warned")
        self.assertEqual(s["flatten"]["used"], "original")
        d = s["flatten"]["render_distortion"]
        self.assertFalse(d["passes"])
        self.assertAlmostEqual(d["distortion"]["stretch_col"]["median"], 2.0, places=2)
        self.assertTrue(any("stretch" in r for r in d["reasons"]) and any("area ratio" in r for r in d["reasons"]))
        self.assertIn("goes to render fails the flatten limits", d["warning"])
        self.assertEqual(st["stages"]["render"]["status"], "done")  # a plan without strict renders it as before
        self.assertTrue(Path(s["render"]["zarr"]).exists())
        report = json.loads((self.d / "warned" / "report.json").read_text())
        self.assertEqual(report["surfaces"]["t00"]["warnings"], [d["warning"]])
        st, s = self.stretched(self.d / "isometric", strict=True, scale=None)   # as traced: passes, rendered
        d = s["flatten"]["render_distortion"]
        self.assertEqual((d["passes"], d["reasons"]), (True, []))
        self.assertNotIn("warning", d)
        self.assertTrue(Path(s["render"]["zarr"]).exists())

    def test_strict_refuses_to_render_a_distorted_or_unmeasured_surface(self):
        st, s = self.stretched(self.d / "refused", strict=True)
        self.assertEqual(st["stages"]["render"]["status"], "failed")
        self.assertIn("no render finished", st["stages"]["render"]["error"])
        self.assertIn("the unflattened surface fails the flatten limits (", s["render"]["refused"])
        self.assertIn("strict.render_distortion refuses it", s["render"]["refused"])
        self.assertNotIn("audit", s["render"])                      # refused before the chunk audit
        self.assertFalse((self.d / "refused" / "renders").exists())
        st, s = self.stretched(self.d / "unmeasured", strict=True, scale=())
        self.assertIsNone(s["flatten"]["render_distortion"]["passes"])
        self.assertIn("could not be measured", s["flatten"]["render_distortion"]["warning"])
        self.assertIn("could not be measured (", s["render"]["refused"])
        self.assertIn("no grid scale", s["render"]["refused"])

    def test_a_malformed_meta_json_is_recorded_not_a_failed_stage(self):
        # A one-element scale makes grid_distortion raise IndexError; the measurement is evidence, so the flatten
        # stage records it and goes on: sent to render without strict (the fake renderer then fails on that scale
        # itself), refused as unmeasured before the chunk audit with it
        st, s = self.stretched(self.d / "onescale", scale=(0.25,))
        d = s["flatten"]["render_distortion"]
        self.assertEqual((st["stages"]["flatten"]["status"], d["passes"], d["error_type"]), ("done", None, "IndexError"))
        self.assertIn("could not be measured: IndexError: ", d["warning"])
        self.assertNotIn("refused", s["render"])
        self.assertEqual(s["render"]["audit"]["verdict"], "clean")
        st, s = self.stretched(self.d / "onescale-strict", strict=True, scale=(0.25,))
        self.assertIn("could not be measured (IndexError: ", s["render"]["refused"])
        # what else a grid can raise, a dict scale's KeyError and a huge grid's MemoryError, is recorded the same way
        (self.d / "direct").mkdir()
        run = autopipe.Run(vc3d_agent, self.ctx, self.d / "direct", self.plan())
        mf = Path(s["surface"], "meta.json")
        mf.write_text(json.dumps({**json.loads(mf.read_text()), "scale": {"x": 0.25}}))
        self.assertEqual(run.render_distortion(s["surface"])["error_type"], "KeyError")
        with mock.patch.object(autopipe, "grid_distortion", side_effect=MemoryError("no room")):
            self.assertEqual(run.render_distortion(s["surface"])["error"], "MemoryError: no room")

    def test_a_malformed_meta_json_does_not_fail_the_flatten_stage_with_flattening_on(self):
        # The flatten stage measures the surface before flattening; that measurement must not raise either
        st, s = self.stretched(self.d / "onescale-flat", scale=(0.25,), flatten=True)
        self.assertEqual(st["stages"]["flatten"]["status"], "done", st["stages"]["flatten"])
        self.assertIn("IndexError", s["flatten"]["before_error"])
        self.assertEqual(s["flatten"]["used"], "original")
        self.assertEqual(s["flatten"]["render_distortion"]["error_type"], "IndexError")
        st, s = self.stretched(self.d / "onescale-flat-strict", strict=True, scale=(0.25,), flatten=True)
        self.assertEqual(st["stages"]["flatten"]["status"], "done")
        self.assertIn("could not be measured (IndexError: ", s["render"]["refused"])

    def test_a_published_segment_is_measured_but_never_refused_for_distortion(self):
        st, s = self.stretched(self.d / "seg", strict=True, seg=True)
        self.assertEqual(s["flatten"]["why"], "labels sit on the published grid")
        self.assertFalse(s["flatten"]["render_distortion"]["passes"])
        self.assertEqual(st["stages"]["render"]["status"], "done", st["stages"]["render"])
        self.assertTrue(Path(s["render"]["zarr"]).exists())

    def test_no_seed_on_the_sheet_fails_at_seeds(self):
        far = autopipe._merge(autopipe.DEFAULTS["seeds"], {"count": 2, "z_range": [20, 44], "level": 0,
                                                            "radius_um": [500.0, 600.0]})
        st, _ = self.run_plan(self.plan(seeds=far))
        self.assertEqual(st["stages"]["seeds"]["status"], "failed")
        self.assertNotIn("trace", st["stages"])

    def test_traces_read_the_plans_normal_grids(self):
        st, out = self.run_plan(self.plan(trace={**autopipe.DEFAULTS["trace"], "params": {"z_max": 60}}),
                                until="qa")
        for sid, s in st["surfaces"].items():
            self.assertTrue(s["trace"]["normal_grids"])
            self.assertEqual(s["qa"]["data_term"], "normal grids")
        # the trace tool keeps one receipt per output folder, the last trace's (a glob for receipt-*.json found
        # none, so this check could not fail before)
        p = json.loads((out / "traces" / "receipt.json").read_text())["params"]
        self.assertEqual(p["normal_grid_path"], str(self.d / "grids"))
        self.assertEqual((p["z_max"], p["min_area_cm"]), (60, 0.0))

    def test_a_trace_without_normal_grids_is_rejected_unless_allowed(self):
        st, _ = self.run_plan(self.plan(grids=False))
        self.assertEqual(st["stages"]["qa"]["status"], "failed")
        self.assertIn("traced without normal grids", st["stages"]["qa"]["error"])
        for s in st["surfaces"].values():
            self.assertEqual((s["trace"]["normal_grids"], s["qa"]["data_term"]), (False, "none"))
        qa = {**autopipe.DEFAULTS["qa"], "require_seated": "none", "windaudit": "off", "windows": 1,
              "require_data_term": False}
        st, _ = self.run_plan(self.plan(grids=False, qa=qa), out=self.d / "allowed", until="qa")
        self.assertEqual(st["stages"]["qa"]["status"], "done")
        required = {**autopipe.DEFAULTS["trace"], "normal_grids": "required"}
        st, _ = self.run_plan(self.plan(grids=False, trace=required), out=self.d / "required", until="trace")
        self.assertEqual(st["stages"]["trace"]["status"], "failed")
        self.assertIn("plan resolved none", st["stages"]["trace"]["error"])

    def fake_bench(self, verdict="one winding", fail=None):
        """kit surfbench stand-ins: references built on first use, each surface scored, every call recorded."""
        calls = []

        def build_refs(dest, log=None, workers=2):
            calls.append(("refs", str(dest), workers))
            Path(dest).mkdir(parents=True, exist_ok=True)
            (Path(dest) / "manifest.json").write_text("{}")

        def audit(dest, cache_dir=None, log=None, workers=2):
            calls.append(("audit", str(dest), workers))
            (Path(dest) / "audit.json").write_text("{}")

        def score(surface, refs, workers=2, log=None):
            calls.append(("score", str(surface), str(refs)))
            if fail:
                raise surfbench.BenchError(fail)
            return {"verdict": verdict, "valid": True, "invalid_reasons": [], "rule_digest": surfbench.RULE_DIGEST,
                    "manifest_digest": "m", "audit_digest": "a",
                    "metrics": {"d4": {"dominant_precision": 0.9}, "d2": {}, "switches": {"switch_edges": 0},
                                "recall_d4": 0.1, "dominant_covered_cm2": 1.0, "dominant_split": "report"}}
        return calls, mock.patch.multiple(surfbench, build_refs=build_refs, audit=audit, score=score)

    def test_traces_among_published_windings_are_measured_but_not_gated(self):
        refs = self.d / "refs"
        self.ctx.env["KIT_SURFBENCH_REFS"] = str(refs)
        calls, patch = self.fake_bench(verdict="not one winding")
        with patch:
            st, out = self.run_plan(self.plan(bench=surfbench.RULE_DIGEST), until="qa")
            self.assertEqual(st["stages"]["bench"]["status"], "done", st["stages"]["bench"])
            self.assertEqual([c[0] for c in calls], ["refs", "audit", "score", "score"])
            for sid in ("t00", "t01"):
                b = st["surfaces"][sid]["bench"]
                self.assertEqual((b["verdict"], b["d4"]["dominant_precision"]), ("not one winding", 0.9))
                self.assertTrue(Path(b["path"]).is_file())
                self.assertTrue(st["surfaces"][sid]["accepted"])        # recorded only: qa decides
            self.assertEqual(st["stages"]["bench"]["record"], {"t00": "not one winding", "t01": "not one winding"})
            calls.clear()
            self.run_plan(self.plan(bench=surfbench.RULE_DIGEST), out)   # a resumed run scores nothing again
            self.assertEqual(calls, [])
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(report["surfaces"]["t00"]["bench"], {"verdict": "not one winding", "valid": True})

    def test_a_benchmark_that_cannot_measure_stops_the_run(self):
        self.ctx.env["KIT_SURFBENCH_REFS"] = str(self.d / "refs")
        calls, patch = self.fake_bench(fail="controls could not run")
        with patch:
            st, _ = self.run_plan(self.plan(bench=surfbench.RULE_DIGEST))
        self.assertEqual(st["stages"]["bench"]["status"], "failed")
        self.assertIn("winding benchmark: controls could not run", st["stages"]["bench"]["error"])
        self.assertNotIn("qa", st["stages"])
        calls, patch = self.fake_bench()
        with patch:
            st, _ = self.run_plan(self.plan(bench="0" * 64), self.d / "other")
        self.assertEqual(st["stages"]["bench"]["status"], "failed")
        self.assertIn("make a new plan", st["stages"]["bench"]["error"].lower())
        self.assertEqual(calls, [])                                       # a rule other than the plan's never scores

    def test_seeds_given_in_the_plan_are_traced(self):
        seeds = {**autopipe.DEFAULTS["seeds"], "points": [[AXIS[0] - RADIUS, AXIS[1], 32]]}
        st, _ = self.run_plan(self.plan(seeds=seeds), until="trace")
        self.assertEqual(st["stages"]["seeds"]["record"], {"seeds": [[AXIS[0] - RADIUS, AXIS[1], 32.0]],
                                                           "stats": {"given": 1}})
        self.assertEqual(sorted(st["surfaces"]), ["t00"])

    def test_a_given_seed_just_off_the_prediction_moves_onto_it(self):
        off = [AXIS[0] + RADIUS + 2.5, AXIS[1], 32]          # 2.5 voxels outside the sheet, where the CT is 0
        seeds = {**autopipe.DEFAULTS["seeds"], "points": [off]}
        st, _ = self.run_plan(self.plan(seeds=seeds), until="trace")
        self.assertEqual(st["stages"]["trace"]["status"], "failed")     # the CT air check refuses it
        self.assertIn("on air in the CT", st["stages"]["trace"]["error"])
        st, _ = self.run_plan(self.plan(seeds={**seeds, "ct_check": False}), self.d / "nocheck", until="trace")
        self.assertEqual(st["stages"]["trace"]["status"], "done", st["stages"]["trace"])
        self.assertIn(f"(moved from {[float(v) for v in off]})", st["surfaces"]["t00"]["origin"])
        self.assertTrue(st["surfaces"]["t00"]["origin"].startswith(f"trace from seed [{int(AXIS[0] + RADIUS + 1)}"))

    def test_a_version_1_plan_still_reads_and_traced_without_grids(self):
        plan = self.plan(grids=False)
        for k in ("seeds", "trace", "qa"):
            plan["settings"][k] = {kk: v for kk, v in plan["settings"][k].items()
                                   if kk not in ("points", "normal_grids", "params", "require_data_term")}
        del plan["resolved"]["prediction_level"], plan["resolved"]["normal_grids_model"]
        plan["version"] = 1
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        st, _ = self.run_plan(plan, until="qa")
        self.assertEqual(st["stages"]["qa"]["status"], "done")
        self.assertTrue(all(s["qa"]["data_term"] == "none" for s in st["surfaces"].values()))
        plan["version"] = 3
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        with self.assertRaisesRegex(autopipe.AutoError, "not one of"):
            autopipe.check_plan(plan)

    def test_target_runs_need_their_experiment(self):
        plan = self.plan(purpose="target", experiment="no-such-run")
        with self.assertRaisesRegex(autopipe.AutoError, "Preregister it first"):
            autopipe.check_target(vc3d_agent, self.ctx, plan)

    @unittest.skipUnless(HAVE_TIFF, "kit rowscore needs numpy, and tifffile for the fake TIFF maps")
    def test_triage_on_a_whole_run_waits_for_maps_and_keeps_rowscores_reason(self):
        # the fake renders are a few dozen pixels across: rowscore gives no score, and says why. PHercFake has no
        # published labels, so its list is private: written in the run folder (outside the repository here, so git
        # never sees it), and the stage record names the file only
        plan = self.plan(ink={"where": "modal", "models": ["fake"], "variants": ["f", "r", "s"]}, triage=True)
        st, out = self.run_plan(plan)
        self.assertNotIn("ranking", st["stages"]["report"]["record"]["triage"])
        self.assertIn("AGENTS.md rule 1", st["stages"]["report"]["record"]["triage"]["private"])
        self.assertEqual(st["stages"]["ink"]["status"], "handoff")
        self.assertEqual(set(st["stages"]), set(autopipe.STAGES) - {"score"})     # no stage of its own
        rows = json.loads((out / "report.json").read_text())["triage"]["ranking"]
        self.assertEqual([r["surface"] for r in rows], ["t00", "t01"])
        self.assertTrue(all(r["score"] is None and r["why"] == "no ink maps (the ink stage is handoff)"
                            and r["rank"] is None for r in rows), rows)
        self.use_runner()
        st, _ = self.run_plan(plan, out)
        self.assertEqual(st["stages"]["ink"]["status"], "done", st["stages"]["ink"])
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(report["triage"]["ranking"], json.loads((out / "triage.json").read_text())["ranking"])
        for r in report["triage"]["ranking"]:
            self.assertIsNone(r["score"])
            self.assertIn("too small", r["why"])
            self.assertEqual(r["controls"], {"r": None, "s": None})
            self.assertIsNone(r["beats_controls"])


def fixed_plan(sample="PHercFixed", **over):
    """A smoke plan with two models and nothing taken from a temporary folder, so its digest and its report are
    the same on every machine."""
    settings = autopipe._merge(autopipe.DEFAULTS, {"purpose": "smoke", "ink": {"models": ["a", "b"], "orient": None},
                                                   **over})
    resolved = {"sample": sample, "volume": "V1", "volume_url": "https://example.invalid/V1.zarr/",
                "voxel_um": 10.0, "shape_zyx": [64, 128, 128], "license": None,
                "prediction_url": "https://example.invalid/pred.zarr/", "prediction_model": "M1",
                "prediction_level": 0, "normal_grids_url": None, "normal_grids_model": None,
                "catalog_umbilicus": None, "benchmark": None}
    plan = {"version": autopipe.PLAN_VERSION, "created": "2026-10-13T00:00:00Z", "settings": settings,
            "resolved": resolved}
    plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
    return plan


def fixed_state(plan, maps=None, extra=None, exits=None):
    """A state.json of a run that finished every stage before report: t00 accepted, with maps of models a and b
    (`maps`: {sid: {model: {variant: path}}}; by default paths that do not exist), t01 rejected. Each model's ink
    exited 0, or as `exits` ({sid: {model: exit}}) says."""
    maps = maps or {"t00": {m: {v: f"ink/t00/{m}/ink_{v}.tif" for v in "frs"} for m in ("a", "b")}}
    exits = exits or {}
    surfaces = {sid: {"origin": "trace", "accepted": True, "qa": {"reasons": [], "warnings": ["w"]},
                      "flatten": {"used": "flattened"}, "render": {"zarr": f"renders/{sid}.zarr"},
                      "ink": {m: {"exit": (exits.get(sid) or {}).get(m, 0),
                                  "maps": {v: {"path": str(p)} for v, p in per.items()}}
                              for m, per in models.items()}}
                for sid, models in maps.items()}
    surfaces["t01"] = {"origin": "trace", "accepted": False, "qa": {"reasons": ["not seated"]}}
    surfaces.update(extra or {})
    return {"plan_digest": plan["digest"],
            "stages": {k: {"status": "skipped" if k in ("bench", "score") else "done"} for k in autopipe.STAGES[:-1]},
            "surfaces": surfaces}


def before_15oct(settings):
    """settings with the ink default of before 15 Oct 2026 written out where they do not name their own models
    (ink_9um seed 42), so a plan made from them has the content and digest it had then."""
    s = json.loads(json.dumps(settings))
    s.setdefault("ink", {}).setdefault("models", ["ink_9um-seed42"])
    return s


class TestTriagePlan(unittest.TestCase):
    """triage: absent unless asked for, so every plan made without it keeps its content and digest."""

    # make_plan on the synthetic catalog at 73113c4, before triage existed
    BEFORE = {"default": ({}, "33dcf5a71f050b5e12d556f8ef3f59d4cbece1a6f673099842255a512d37566c"),
              "smoke": ({"purpose": "smoke"}, "c45614274fe03e44b24be22ba31bd5b847f9f75bc4e1a231ca294f62e4b12126"),
              "target": ({"purpose": "target", "experiment": "some-run"},
                         "0472f470064ddfa90eeecf51ff53746254f8b766f923255f06cf55286db19503"),
              "segment": ({"volume": "V2", "segment": "x"},
                          "39febaab2533c11a58c49d4a2f14f10c3ece72f68efd869f5f171895199aae32"),
              "recipe": ({"render": {"trim": True, "snap": True}, "strict": True, "trace": {"repeats": 3},
                          "qa": {"repair": True}, "ink": {"models": ["a", "b"], "ensemble": True,
                                                          "layers": {"windows": [[0, 20], [8, 27]]}}},
                         "8c2155e60217f0ace756310bfc6dd32a606ef9b4ae24072bca04e5132c0c07a5")}

    def test_plans_without_it_keep_their_digests(self):
        self.assertEqual(autopipe.PLAN_VERSION, 2)
        for name, (settings, want) in self.BEFORE.items():
            plan = autopipe.make_plan("PHercTest", before_15oct(settings), cat=catalog(),
                                      created="2026-10-13T00:00:00Z")
            self.assertEqual(plan["digest"], want, name)
            self.assertNotIn("triage", plan["settings"], name)
        self.assertEqual(fixed_plan()["digest"], "82662c01f2db4be68272d380f5bc60ad5d606f4d876019c3098c971b984882fe")
        base = self.BEFORE["default"][1]
        for off in (None, False):
            self.assertEqual(autopipe.make_plan("PHercTest", before_15oct({"triage": off}), cat=catalog())["digest"],
                             base)
        on = autopipe.make_plan("PHercTest", {"triage": True}, cat=catalog())
        self.assertEqual(on["settings"]["triage"], {"method": "rowscore"})
        self.assertNotEqual(on["digest"], base)
        self.assertEqual(autopipe.make_plan("PHercTest", {"triage": {"method": "rowscore"}}, cat=catalog())["digest"],
                         on["digest"])
        self.assertNotIn("triage", autopipe.DEFAULTS)

    def test_refusals(self):
        def plan(**over):
            return autopipe.make_plan("PHercTest", over, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "triage.method is one of"):
            plan(triage={"method": "fft"})
        with self.assertRaisesRegex(autopipe.AutoError, "unknown plan setting triage.bogus"):
            plan(triage={"bogus": 1})
        with self.assertRaisesRegex(autopipe.AutoError, "triage is an object"):
            plan(triage="yes")
        with self.assertRaisesRegex(autopipe.AutoError, "needs ink.variants f, r and s"):
            plan(triage=True, ink={"variants": ["f", "r"]})
        with self.assertRaisesRegex(autopipe.AutoError, "ink.where skip makes none"):
            plan(triage=True, ink={"where": "skip"})

    def test_the_command_line_and_the_agent_tool_take_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / "cache").mkdir(parents=True)
            (home / "cache" / "open-data-metadata.json").write_text(json.dumps(catalog()))
            ctx = vc3d_agent.Context(home=home, env={})
            res = vc3d_agent.call("autopipeline", {"action": "plan", "sample": "PHercTest", "out": str(Path(tmp) / "a"),
                                                   "settings": {"purpose": "smoke", "triage": True}}, ctx)
            # the tool checks the planned models against this machine's (none registered here)
            with self.assertRaisesRegex(vc3d_agent.ToolError, "ink_9um-seed24 is neither a model kit can fetch"):
                vc3d_agent.call("autopipeline", {"action": "plan", "sample": "PHercTest", "out": str(Path(tmp) / "c"),
                                                 "settings": {"purpose": "smoke",
                                                              "ink": {"models": ["ink_9um-seed24"]}}}, ctx)
            ctx.close()
            self.assertEqual(json.loads(Path(res["plan"]).read_text())["settings"]["triage"], {"method": "rowscore"})
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            p = subprocess.run([sys.executable, "-m", "kit", "autopipeline", "plan", "PHercTest", "--settings",
                                '{"purpose": "smoke", "triage": true}', "--out", str(Path(tmp) / "b")],
                               capture_output=True, text=True, cwd=str(ROOT), env=dict(env, KIT_VC3D_HOME=str(home)))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads((Path(tmp) / "b" / "plan.json").read_text())["digest"], res["digest"])


class TestOrientPlan(unittest.TestCase):
    """ink.orient: opt in, since a check of it as the default read NO-GO on 15 Oct 2026; a plan that does not ask
    for it has the content and digest such a plan had before."""

    SEED42 = {"models": ["ink_9um-seed42"]}
    ON = {"method": "upright", "min_consistency": 0.9, "min_vertical": 0.5, "order": 1}

    def test_plans_that_leave_it_off_keep_their_digests(self):
        self.assertEqual(autopipe.PLAN_VERSION, 2)
        for name, (settings, want) in TestTriagePlan.BEFORE.items():
            plan = autopipe.make_plan("PHercTest", before_15oct(settings), cat=catalog(),
                                      created="2026-10-13T00:00:00Z")
            self.assertEqual(plan["digest"], want, name)
            self.assertNotIn("orient", plan["settings"]["ink"], name)
        self.assertEqual(fixed_plan()["digest"], "82662c01f2db4be68272d380f5bc60ad5d606f4d876019c3098c971b984882fe")
        base = TestTriagePlan.BEFORE["default"][1]
        for off in (None, False):
            self.assertEqual(autopipe.make_plan("PHercTest", {"ink": dict(self.SEED42, orient=off)},
                                                cat=catalog())["digest"], base)
        # asked for by the plan itself: the settings of 13 Oct, no fallback, as the preregistered recipes give them
        on = autopipe.make_plan("PHercTest", {"ink": dict(self.SEED42, orient=True)}, cat=catalog())
        self.assertEqual(on["settings"]["ink"]["orient"], self.ON)
        self.assertNotEqual(on["digest"], base)
        for given in ({"method": "upright"}, dict(self.ON)):
            self.assertEqual(autopipe.make_plan("PHercTest", {"ink": dict(self.SEED42, orient=given)},
                                                cat=catalog())["digest"], on["digest"])
        other = autopipe.make_plan("PHercTest", {"ink": dict(self.SEED42, orient={"min_consistency": 0.95})},
                                   cat=catalog())
        self.assertNotEqual(other["digest"], on["digest"])      # the digest covers every threshold

    def test_off_by_default_and_the_fallback_on_request(self):
        self.assertNotIn("orient", autopipe.DEFAULTS["ink"])
        self.assertEqual(autopipe.DEFAULTS["ink"]["models"], ["reader-v2"])
        d = autopipe.make_plan("PHercTest", cat=catalog(), created="2026-10-15T00:00:00Z")
        self.assertNotIn("orient", d["settings"]["ink"])
        self.assertEqual(d["settings"]["ink"]["models"], ["reader-v2"])
        self.assertNotEqual(d["digest"], TestTriagePlan.BEFORE["default"][1])     # the default reader changed
        # the fallback is asked for with an object, kept as given, and a plan's settings merge again to themselves
        fb = autopipe.make_plan("PHercTest", {"ink": {"orient": FALLBACK}}, cat=catalog(),
                                created="2026-10-15T00:00:00Z")
        self.assertEqual(fb["settings"]["ink"]["orient"], dict(self.ON, fallback="unturned"))
        self.assertNotEqual(fb["digest"], autopipe.make_plan("PHercTest", {"ink": {"orient": True}}, cat=catalog(),
                                                             created="2026-10-15T00:00:00Z")["digest"])
        self.assertEqual(autopipe._merge(autopipe.DEFAULTS, fb["settings"]), fb["settings"])
        self.assertEqual(autopipe.make_plan("PHercTest", fb["settings"], cat=catalog(),
                                            created="2026-10-15T00:00:00Z")["digest"], fb["digest"])
        tight = autopipe.make_plan("PHercTest", {"ink": {"orient": {"min_consistency": 0.95, "fallback": "unturned"}}},
                                   cat=catalog())
        self.assertEqual(tight["settings"]["ink"]["orient"], dict(self.ON, min_consistency=0.95, fallback="unturned"))
        # published segments and plans that run no model have nothing to turn, as before 15 Oct
        for settings in ({"volume": "V2", "segment": "x"}, {"ink": {"where": "skip"}}):
            self.assertNotIn("orient", autopipe.make_plan("PHercTest", settings, cat=catalog())["settings"]["ink"])
        seg = TestTriagePlan.BEFORE["segment"]
        self.assertEqual(autopipe.make_plan("PHercTest", dict(seg[0], ink=self.SEED42), cat=catalog(),
                                            created="2026-10-13T00:00:00Z")["digest"], seg[1])

    def test_refusals(self):
        def plan(**over):
            return autopipe.make_plan("PHercTest", over, cat=catalog())
        with self.assertRaisesRegex(autopipe.AutoError, "ink.orient.method is one of"):
            plan(ink={"orient": {"method": "rot90"}})
        with self.assertRaisesRegex(autopipe.AutoError, "unknown plan setting ink.orient.bogus"):
            plan(ink={"orient": {"bogus": 1}})
        with self.assertRaisesRegex(autopipe.AutoError, "ink.orient is an object"):
            plan(ink={"orient": "upright"})
        with self.assertRaisesRegex(autopipe.AutoError, "min_consistency is a number above 0"):
            plan(ink={"orient": {"min_consistency": 0}})
        with self.assertRaisesRegex(autopipe.AutoError, "min_vertical is a number from 0 to 10"):
            plan(ink={"orient": {"min_vertical": -1}})
        with self.assertRaisesRegex(autopipe.AutoError, "order is 0 .nearest. or 1"):
            plan(ink={"orient": {"order": 3}})
        with self.assertRaisesRegex(autopipe.AutoError, "order is 0 .nearest. or 1"):
            plan(ink={"orient": {"order": True}})
        with self.assertRaisesRegex(autopipe.AutoError, "ink.where skip runs none"):
            plan(ink={"orient": True, "where": "skip"})
        with self.assertRaisesRegex(autopipe.AutoError, "ink.where skip runs none"):
            plan(ink={"orient": {"fallback": "unturned"}, "where": "skip"})
        with self.assertRaisesRegex(autopipe.AutoError, "ink.orient.fallback is one of"):
            plan(ink={"orient": {"fallback": "skip"}})
        with self.assertRaisesRegex(autopipe.AutoError, "a published segment is in the published layout"):
            plan(volume="V2", segment="x", ink={"orient": True})


@unittest.skipUnless(HAVE_TIFF, "kit rowscore needs numpy, and tifffile for the stand-in TIFF maps")
class TestTriage(Base):
    """The triage step of report on stand-in maps: text-like rows 4 mm apart (rowscore's band is 2.5 to 8 mm) at
    10 um a pixel, and noise. Plans on PUBLIC (a scroll with published labels) keep their list in the open; any other
    scroll's list is private."""

    PUBLIC = "PHerc0841"

    @staticmethod
    def rows(seed, contrast, size=1200):
        import numpy as np
        rng = np.random.default_rng(seed)
        y = np.arange(size)[:, None] * 10.0 / 1000.0
        a = 0.5 + contrast * np.sin(2 * np.pi * y / 4.0) + rng.normal(0, 0.1, (size, size))
        return np.clip(a, 0.02, 1.0).astype(np.float32)

    def write(self, name, array):
        import tifffile
        p = self.d / "maps" / f"{name}.tif"
        p.parent.mkdir(parents=True, exist_ok=True)
        tifffile.imwrite(str(p), array)
        return p

    def surface(self, sid, forward, reverse=0.0, size=1200, models=("a", "b")):
        """{model: {variant: path}}: forward maps with rows of contrast `forward`, the reverse map with `reverse`,
        the shuffled map noise; each model's maps from its own noise."""
        out = {}
        for k, m in enumerate(models):
            seed = 100 * len(sid) + 10 * int(sid[1:]) + k
            out[m] = {"f": self.write(f"{sid}-{m}-f", self.rows(seed, forward, size)),
                      "r": self.write(f"{sid}-{m}-r", self.rows(seed + 5, reverse, size)),
                      "s": self.write(f"{sid}-{m}-s", self.rows(seed + 7, 0.0, size))}
        return out

    def run_report(self, plan, maps=None, out=None, root=None, extra=None, exits=None):
        out = out or self.d / "run"
        out.mkdir(parents=True, exist_ok=True)
        if not (out / "state.json").exists():
            (out / "state.json").write_text(json.dumps(fixed_state(plan, maps, extra, exits)))
        ctx = self.context(root=root or self.d)
        return autopipe.Run(vc3d_agent, ctx, out, plan).run(), out

    def test_surfaces_are_ranked_by_their_row_score_with_both_controls_beside(self):
        from kit import rowscore
        from kit.verify import load_map
        maps = {"t00": self.surface("t00", 0.3), "t02": self.surface("t02", 0.05),
                "t03": self.surface("t03", 0.0, reverse=0.3),             # a control with rows: forward loses
                "t04": self.surface("t04", 0.3, size=200),                 # too small for rowscore
                "t05": self.surface("t05", 0.1)}
        maps["t05"]["b"]["s"] = self.d / "maps" / "gone.tif"              # model b's shuffled map does not read
        plan = fixed_plan(self.PUBLIC, triage=True)
        st, out = self.run_report(plan, maps)
        self.assertEqual(st["stages"]["report"]["status"], "done", st["stages"]["report"])
        self.assertEqual(set(st["stages"]), set(autopipe.STAGES))
        report = json.loads((out / "report.json").read_text())
        tri = json.loads((out / "triage.json").read_text())
        rows = report["triage"]["ranking"]
        self.assertEqual(rows, tri["ranking"])
        self.assertEqual([r["surface"] for r in rows], ["t00", "t05", "t02", "t03", "t04"])   # t01 was rejected
        self.assertEqual([r["rank"] for r in rows], [1, 2, 3, 4, None])
        self.assertEqual([r["beats_controls"] for r in rows], [True, True, True, False, None])
        self.assertIn("too small", rows[-1]["why"])
        self.assertIsNone(rows[-1]["score"])
        scores = [r["score"] for r in rows[:4]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertGreater(rows[0]["score"], 100 * rows[3]["score"])
        self.assertAlmostEqual(rows[0]["period_mm"], 4.0, delta=0.5)
        # the mean of the two models' maps, scored as rowscore scores it; a model whose maps do not all read is left
        # out of the mean, and says why
        t00 = tri["surfaces"]["t00"]
        self.assertEqual(t00["mean_of"], ["a", "b"])
        want = rowscore.score_array(rowscore.mean_map([load_map(maps["t00"][m]["f"]) for m in ("a", "b")]), 10.0)
        self.assertEqual(t00["mean"]["f"]["score"], want["score"])
        self.assertEqual(set(t00["models"]["a"]), {"f", "r", "s"})
        t05 = tri["surfaces"]["t05"]
        self.assertEqual(t05["mean_of"], ["a"])
        self.assertIn("cannot read", t05["models"]["b"]["s"]["error"])
        self.assertEqual(t05["mean"]["f"]["score"], t05["models"]["a"]["f"]["score"])
        # what it says: a reading order, never a finding (the source's address is Bullo27's repository's name)
        self.assertEqual(tri["source"], autopipe.TRIAGE_SOURCE)
        for text in (json.dumps(report["triage"]), json.dumps({k: v for k, v in tri.items() if k != "source"})):
            self.assertIn("A reading order, not a verdict", text)
            self.assertIn("a place to look, not ink", text)
            self.assertNotIn("letter", text.lower())
        self.assertEqual((tri["method"], tri["voxel_um"], tri["plan"]), ("rowscore", 10.0, plan["digest"]))
        self.assertEqual((tri["sample"], tri["version"]), (self.PUBLIC, autopipe.TRIAGE_VERSION))
        self.assertNotIn("private", tri)
        self.assertEqual(st["stages"]["report"]["record"]["triage"]["ranking"], rows)   # a public list: in the open
        self.assertFalse(TestTriageNotInGit.private_lists(tri))

    def test_a_report_run_again_reuses_the_scores_of_maps_that_did_not_change(self):
        from kit import rowscore
        maps = {"t00": self.surface("t00", 0.3, models=("a",)), "t02": self.surface("t02", 0.0, models=("a",))}
        plan = fixed_plan(self.PUBLIC, triage=True, ink={"models": ["a"]})
        _, out = self.run_report(plan, maps)
        first = json.loads((out / "triage.json").read_text())
        with mock.patch.object(rowscore, "score_array", side_effect=AssertionError("scored again")):
            self.run_report(plan, out=out)
        self.assertEqual(json.loads((out / "triage.json").read_text()), first)
        p = self.write("t02-a-f", self.rows(1, 0.3))                 # a map rewritten: that surface is scored again
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10 ** 9))
        calls = []
        real = rowscore.score_array
        with mock.patch.object(rowscore, "score_array", side_effect=lambda *a, **k: calls.append(1) or real(*a, **k)):
            self.run_report(plan, out=out)
        self.assertEqual(len(calls), 3)
        rows = json.loads((out / "report.json").read_text())["triage"]["ranking"]
        self.assertEqual({r["surface"] for r in rows if r["beats_controls"]}, {"t00", "t02"})

    def test_a_plan_without_triage_reports_exactly_as_before(self):
        plan = fixed_plan()
        st, out = self.run_report(plan)
        # report.json of this state at 73113c4, before triage existed: the same bytes
        self.assertEqual(hashlib.sha256((out / "report.json").read_bytes()).hexdigest(),
                         "cd57bfa3a96967c4263c40b9121cbed866882750f66a2c810b0aa45517d97513")
        self.assertFalse((out / "triage.json").exists())
        self.assertEqual(list(st["stages"]), list(autopipe.STAGES))
        self.assertEqual(autopipe.STAGES, ("acquire", "umbilicus", "seeds", "trace", "bench", "qa", "flatten",
                                           "render", "ink", "score", "report"))
        for stage in autopipe.STAGES:          # run --until takes every stage name it took
            autopipe.Run(vc3d_agent, self.context(root=self.d), out, plan).run(until=stage)

    def test_npy_maps_are_read_as_kit_auc_reads_them(self):
        # scripts/vc3d/ink.py's v8in and TorchScript engines write ink_<v>.npy; villa's writes TIFF
        import numpy as np
        from kit import rowscore
        from kit.verify import load_map
        maps = {}
        for sid, c in (("t00", 0.3), ("t02", 0.05)):
            per = self.surface(sid, c, models=("a",))
            per["v8in"] = {}
            for v, cc in (("f", c), ("r", 0.0), ("s", 0.0)):
                p = self.d / "maps" / f"{sid}-v8in" / f"ink_{v}.npy"
                p.parent.mkdir(parents=True, exist_ok=True)
                np.save(p, self.rows(50 + len(per["v8in"]) + 10 * int(sid[1:]), cc))
                per["v8in"][v] = p
            maps[sid] = per
        plan = fixed_plan(self.PUBLIC, triage=True, ink={"models": ["v8in", "a"]})
        _, out = self.run_report(plan, maps)
        tri = json.loads((out / "triage.json").read_text())
        self.assertEqual([(r["surface"], r["rank"], r["beats_controls"]) for r in tri["ranking"]],
                         [("t00", 1, True), ("t02", 2, True)])
        t00 = tri["surfaces"]["t00"]
        self.assertEqual(t00["mean_of"], ["v8in", "a"])
        self.assertEqual(t00["models"]["v8in"]["f"]["score"],
                         rowscore.score_array(np.load(maps["t00"]["v8in"]["f"]), 10.0)["score"])
        want = rowscore.mean_map([np.load(maps["t00"]["v8in"]["f"]), load_map(maps["t00"]["a"]["f"])])
        self.assertEqual(t00["mean"]["f"]["score"], rowscore.score_array(want, 10.0)["score"])

    def test_unreadable_maps_never_rank_and_no_nan_reaches_the_json(self):
        # t00: model a's ink exited 3 (NaN on the surface), so only b is read. t02: a's forward map has NaN off the
        # surface (ink.py's exit 0 allows that), read as rowscore's off-surface 0. t03: both models exited 3. t04: flat
        # maps (power 0 over 0: rowscore's ratio is NaN)
        import numpy as np
        from kit import rowscore
        maps = {sid: self.surface(sid, c) for sid, c in (("t00", 0.05), ("t02", 0.3), ("t03", 0.3))}
        bad = self.rows(3, 0.3)
        bad[300:900, 300:900] = np.nan
        maps["t00"]["a"]["f"] = self.write("t00-a-f-nan", bad)
        edge, other = self.rows(4, 0.3), self.rows(5, 0.3)
        edge[:, :150] = other[:, :150] = 0.0                # off the surface in both models' maps, as a render gives
        edge[:20, :20] = np.nan
        maps["t02"]["a"]["f"] = self.write("t02-a-f-edge", edge)
        maps["t02"]["b"]["f"] = self.write("t02-b-f-edge", other)
        flat = self.write("flat", np.full((1200, 1200), 0.5, np.float32))
        maps["t04"] = {m: {v: flat for v in "frs"} for m in ("a", "b")}
        plan = fixed_plan(self.PUBLIC, triage=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            st, out = self.run_report(plan, maps, exits={"t00": {"a": 3}, "t03": {"a": 3, "b": 3}})
        self.assertEqual(st["stages"]["report"]["status"], "done", st["stages"]["report"])

        def strict(text):
            return json.loads(text, parse_constant=lambda c: self.fail(f"{c} in the JSON"))

        report, tri = strict((out / "report.json").read_text()), strict((out / "triage.json").read_text())
        rows = report["triage"]["ranking"]
        self.assertEqual(rows, tri["ranking"])
        self.assertEqual([r["surface"] for r in rows], ["t02", "t00", "t03", "t04"])
        self.assertEqual([r["rank"] for r in rows], [1, 2, None, None])
        t00 = tri["surfaces"]["t00"]
        self.assertEqual(t00["mean_of"], ["b"])
        self.assertEqual(t00["score"], t00["models"]["b"]["f"]["score"])
        self.assertIn("ink exit 3", t00["models"]["a"]["f"]["skipped"])
        self.assertIsNone(rows[1]["models"]["a"])
        t02 = tri["surfaces"]["t02"]["models"]["a"]["f"]
        self.assertEqual(t02["nonfinite_px"], 400)
        self.assertEqual(t02["score"], rowscore.score_array(np.nan_to_num(edge, nan=0.0), 10.0)["score"])
        self.assertIn("ink exit 3", rows[2]["why"])
        self.assertIn("not a finite number", rows[3]["why"])
        self.assertIsNone(rows[3]["score"])

    def test_a_failed_scoring_is_scored_again_and_a_reason_is_kept(self):
        # a scoring that failed (too little memory, say) is never reused; rowscore's own reason (too small) is
        from kit import rowscore
        maps = {"t00": self.surface("t00", 0.3, models=("a",)), "t02": self.surface("t02", 0.3, size=200, models=("a",))}
        plan = fixed_plan(self.PUBLIC, triage=True, ink={"models": ["a"]})
        with mock.patch.object(rowscore, "score_array", side_effect=MemoryError("Unable to allocate 9.1 GiB")):
            _, out = self.run_report(plan, maps)
        rows = json.loads((out / "report.json").read_text())["triage"]["ranking"]
        self.assertTrue(all(r["score"] is None and "MemoryError" in r["why"] for r in rows), rows)
        self.run_report(plan, out=out)
        rows = json.loads((out / "report.json").read_text())["triage"]["ranking"]
        self.assertEqual([(r["surface"], r["rank"]) for r in rows], [("t00", 1), ("t02", None)])
        self.assertIn("too small", rows[1]["why"])
        with mock.patch.object(rowscore, "score_array", side_effect=AssertionError("scored again")):
            self.run_report(plan, out=out)
        self.assertEqual(json.loads((out / "report.json").read_text())["triage"]["ranking"], rows)

    def test_a_list_on_a_scroll_without_published_labels_is_private_whatever_the_purpose(self):
        # the purpose does not decide: a smoke or benchmark plan on an unlabelled scroll keeps its list in a folder
        # git ignores, and its stage record names the file only. The kit home is a git repository here: one that no
        # repository holds may write anywhere (vc3d_agent.ignored), so its docs/evidence would not be a tracked folder
        subprocess.run(["git", "init", "-q", str(self.d)], check=True, capture_output=True)
        maps = {"t00": self.surface("t00", 0.3, models=("a",))}
        for purpose in ("smoke", "benchmark"):
            plan = fixed_plan(purpose=purpose, triage=True, ink={"models": ["a"]})
            out = self.d / "work" / "autopipe" / purpose
            st, out = self.run_report(plan, maps, out=out)
            tri = json.loads((out / "triage.json").read_text())
            self.assertEqual((tri["sample"], tri["ranking"][0]["surface"]), ("PHercFixed", "t00"))
            self.assertIn("AGENTS.md rule 1", tri["private"])
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["triage"]["ranking"], tri["ranking"])
            rec = st["stages"]["report"]["record"]["triage"]
            self.assertEqual((rec["file"], rec["surfaces"], rec["scored"]), (str(out / "triage.json"), 1, 1))
            self.assertNotIn("ranking", (out / "state.json").read_text())
            self.assertTrue(TestTriageNotInGit.private_lists(tri))       # the scan of tracked files would catch it
            self.assertTrue(TestTriageNotInGit.private_lists(report))
            where = self.d / "docs" / "evidence" / purpose               # a folder git does not ignore
            st, _ = self.run_report(plan, maps, out=where)
            self.assertEqual(st["stages"]["report"]["status"], "done")
            self.assertFalse((where / "triage.json").exists())
            self.assertIn("AGENTS.md rule 1", json.loads((where / "report.json").read_text())["triage"]["withheld"])
            for f in where.iterdir():
                self.assertNotIn("ranking", f.read_text(), f)

    def target(self, out, ignored=None):
        """A target run's report, in `out`; ignored, when given, is what git says of the run folder."""
        maps = {"t00": self.surface("t00", 0.3, models=("a",))}
        plan = fixed_plan(purpose="target", experiment="exp1", triage=True, ink={"models": ["a"]})
        with mock.patch.object(vc3d_agent, "ignored", wraps=vc3d_agent.ignored) if ignored is None else \
                mock.patch.object(vc3d_agent, "ignored", return_value=ignored):
            st, _ = self.run_report(plan, maps, out=out, root=self.d)
        return st, json.loads((out / "report.json").read_text())

    def test_a_target_runs_triage_stays_in_its_ignored_run_folder(self):
        # a target scroll's triage list is private (AGENTS.md rule 1): written under experiments/<slug>/ only, and the
        # stage record (state.json, what the tool and the command line return) names the file, never the list
        out = self.d / "experiments" / "exp1" / "autopipe" / "run"
        st, report = self.target(out)
        tri = json.loads((out / "triage.json").read_text())
        self.assertEqual(tri["ranking"][0]["surface"], "t00")
        self.assertIn("AGENTS.md rule 1", tri["private"])
        self.assertEqual(report["triage"]["ranking"], tri["ranking"])
        rec = st["stages"]["report"]["record"]["triage"]
        self.assertEqual((rec["file"], rec["surfaces"], rec["scored"]), (str(out / "triage.json"), 1, 1))
        self.assertIn("AGENTS.md rule 1", rec["private"])
        self.assertNotIn("ranking", (out / "state.json").read_text())
        # anywhere else (a run folder copied into a tracked folder), or a folder git does not ignore: nothing written
        for where, ignored in ((self.d / "docs" / "evidence" / "run", None),
                               (self.d / "experiments" / "exp1" / "autopipe" / "run2", False)):
            st, report = self.target(where, ignored)
            self.assertEqual(st["stages"]["report"]["status"], "done")
            self.assertFalse((where / "triage.json").exists(), where)
            self.assertIn("AGENTS.md rule 1", report["triage"]["withheld"])
            for f in where.iterdir():
                self.assertNotIn("ranking", f.read_text(), f)


class TestTriageNotInGit(unittest.TestCase):
    """No file git tracks holds a private triage list (AGENTS.md rule 1): a target run's, or any run's on a scroll
    without published labels. This is where a run's triage.json or report.json copied into an evidence folder would
    be caught. Needs no numpy."""

    @staticmethod
    def private_lists(node):
        """True when a JSON value holds a triage ranking (triage.json's, or report.json's under triage) of a target
        run or of a scroll not in TRIAGE_PUBLIC; a record without its sample counts as private."""
        if isinstance(node, dict):
            tri = node.get("triage") if isinstance(node.get("triage"), dict) else {}
            lists = ("ranking" in node and node.get("method") in autopipe.TRIAGE_METHODS) or "ranking" in tri
            if lists and (node.get("purpose") == "target" or node.get("sample") not in autopipe.TRIAGE_PUBLIC):
                return True
            return any(TestTriageNotInGit.private_lists(v) for v in node.values())
        if isinstance(node, list):
            return any(TestTriageNotInGit.private_lists(v) for v in node)
        return False

    def test_the_public_scrolls_are_those_with_published_labels(self):
        self.assertEqual(set(autopipe.TRIAGE_PUBLIC),
                         {b["sample"] for b in autopipe.BENCHMARKS.values()} | {surfbench.SAMPLE})

    def test_the_scan_can_fail(self):
        rows = [{"surface": "t00", "score": 120.0, "rank": 1}]
        for bad in ({"method": "rowscore", "sample": "PHercX", "purpose": "smoke", "ranking": rows},
                    {"method": "rowscore", "sample": "PHerc0841", "purpose": "target", "ranking": rows},
                    {"method": "rowscore", "ranking": rows},
                    {"sample": "PHercX", "purpose": "benchmark", "triage": {"ranking": rows}},
                    {"runs": [{"sample": "PHerc0139", "purpose": "target", "triage": {"ranking": rows}}]}):
            self.assertTrue(self.private_lists(bad), bad)
        for fine in ({"method": "rowscore", "sample": "PHerc0841", "purpose": "benchmark", "ranking": rows},
                     {"sample": "PHerc0139", "purpose": "smoke", "triage": {"ranking": rows}},
                     {"sample": "PHercX", "purpose": "target", "triage": {"file": "triage.json", "surfaces": 1}},
                     {"method": "other", "ranking": rows}):
            self.assertFalse(self.private_lists(fine), fine)

    def test_no_file_git_tracks_holds_a_private_triage_list(self):
        p = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "*.json"], capture_output=True, text=True)
        if p.returncode != 0 or not p.stdout:
            self.skipTest("not a git checkout")
        for rel in filter(None, p.stdout.split("\0")):
            try:
                data = json.loads((ROOT / rel).read_text())
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            self.assertFalse(self.private_lists(data), rel)


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestScoreMaps(unittest.TestCase):
    def test_whole_and_crop_and_a_render_of_another_shape(self):
        try:
            import numpy as np
            import tifffile
        except ImportError:
            self.skipTest("needs tifffile")
        import tempfile
        calls = []
        real = autopipe._auc
        autopipe._auc = lambda ctx, f, r, lab, extra: calls.append((Path(f), list(extra))) or {"ok": True}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                bench = {"crop": [2, 6, 1, 4], "surface_shape": [8, 10]}
                f = np.arange(80, dtype=np.float32).reshape(8, 10)
                tifffile.imwrite(str(d / "f.tif"), f)
                tifffile.imwrite(str(d / "r.tif"), -f)
                out = autopipe.score_maps(None, d / "f.tif", d / "r.tif", d, bench, 64, d / "s")
                self.assertEqual(set(out), {"whole", "crop"})
                self.assertEqual(calls[0][1], [])
                self.assertEqual(calls[1][1], ["--crop", 2, 6, 1, 4, "--surface-shape", 8, 10, "--inner", 64])
                self.assertTrue((tifffile.imread(str(calls[1][0])) == f[2:6, 1:4]).all())
                bench["surface_shape"] = [9, 10]
                out = autopipe.score_maps(None, d / "f.tif", d / "r.tif", d, bench, 64, d / "s")
                self.assertIn("skipped", out["crop"])
        finally:
            autopipe._auc = real


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestRenderCheck(unittest.TestCase):
    """render_check against a stand-in published render: the same voxels pass, other voxels fail, and a render
    whose layers were reversed fails on its own control."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def texture(seed):
        return lambda z, y, x: (((x * 73856093) ^ (y * 19349663) ^ (z * 83492791) ^ seed) % 251)

    def write(self, name, value):
        return fakes.write_group(self.d / name, [8, 96, 96], value, chunk=(8, 32, 32), levels=2)

    def test_the_same_render_passes_with_both_controls_caught(self):
        ours, pub = self.write("ours.zarr", self.texture(0)), self.write("pub.zarr", self.texture(0))
        r = autopipe.render_check(ours, pub, [8, 40, 8, 40], shift=16)
        self.assertTrue(r["passes"], r)
        self.assertEqual((r["corr"], r["equal_fraction"]), (1.0, 1.0))
        self.assertLess(abs(r["control_layers_reversed"]), 0.5)
        self.assertLess(abs(r["control_moved_16px"]), 0.5)

    def test_another_render_fails(self):
        ours, pub = self.write("ours.zarr", self.texture(0)), self.write("pub.zarr", self.texture(12345))
        self.assertFalse(autopipe.render_check(ours, pub, [8, 40, 8, 40], shift=16)["passes"])

    def test_a_render_with_its_layers_reversed_fails(self):
        t = self.texture(0)
        ours = self.write("ours.zarr", lambda z, y, x: t(7 - z, y, x))
        pub = self.write("pub.zarr", t)
        r = autopipe.render_check(ours, pub, [8, 40, 8, 40], shift=16)
        self.assertFalse(r["passes"])
        self.assertEqual(r["control_layers_reversed"], 1.0)

    def test_a_shape_mismatch_fails_with_its_reason(self):
        ours = self.write("ours.zarr", self.texture(0))
        pub = fakes.write_group(self.d / "pub.zarr", [8, 96, 64], self.texture(0), chunk=(8, 32, 32))
        r = autopipe.render_check(ours, pub, [8, 40, 8, 40], shift=16)
        self.assertFalse(r["passes"])
        self.assertIn("published one", r["why"])


class TestCommandLine(unittest.TestCase):
    def test_defaults_and_help(self):
        for name in ("autopipeline", "autopipe"):     # AutoPipeline's command, and its earlier name
            out = subprocess.run([sys.executable, "-m", "kit", name, "defaults"], capture_output=True, text=True,
                                 cwd=str(ROOT))
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout), autopipe.DEFAULTS)
        out = subprocess.run([sys.executable, "-m", "kit", "autopipe", "run", "--help"], capture_output=True,
                             text=True, cwd=str(ROOT))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("--until", out.stdout)

    def test_the_tool_answers_to_its_earlier_name(self):
        self.assertIn("autopipeline", vc3d_agent.TOOLS)
        self.assertNotIn("autopipe", vc3d_agent.TOOLS)          # one tool, so the count of 45 stands
        with tempfile.TemporaryDirectory() as d:
            ctx = vc3d_agent.Context(root=ROOT, home=Path(d))
            for name in ("autopipeline", "autopipe"):
                with self.assertRaisesRegex(vc3d_agent.ToolError, "has no plan.json"):
                    vc3d_agent.call(name, {"action": "status", "out": d}, ctx)
            ctx.close()


if __name__ == "__main__":
    unittest.main()
