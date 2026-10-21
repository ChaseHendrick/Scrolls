"""Two-way adapters of rowscore and the scroll center finder (umbilicus) through the tool registry.

rowscore: VC3D starts it from the active segment and its selected ink map; the reverse-depth twin binds from the
segment's ink detection records (or beside the map), the report comes back as a file, and a prize-eligible scroll is
refused in public Scrolls. umbilicus: VC3D gets a "Plan:" entry only (a download and over the Mac's 10 minute rule);
the plan's run from a terminal, with --yes-download, writes RUN/umbilicus.json through kit/umbfind.py, which passes
the umbilicus check and comes back into VC3D through "Open run output as umbilicus"; a line VC3D cannot read fails
the format gate. Both are AutoPipeline backends already (pipeline.existing: triage rowscore, umbilicus centrenet).
Everything is synthetic: a stand-in predict.py, stand-in weights, the stand-in plugin host."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import toolreg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_vc3d_host as host  # noqa: E402
import test_umbfind as umb  # noqa: E402

try:
    import numpy as np
    import tifffile
except ImportError:
    np = tifffile = None

needs_maps = unittest.skipIf(np is None, "needs numpy and tifffile")
# public Scrolls' manifests (auc.json marks them); Scrolls-private keeps its own copies and tests
needs_registry = unittest.skipUnless((ROOT / "kit" / "data" / "registry" / "auc.json").is_file(),
                                     "this checkout has no public Scrolls manifests in kit/data/registry")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="toolreg-rowumb-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        cfg = self.tmp / "local.json"
        cfg.write_text("{}")
        self.script = umb.write_fake_predict(self.tmp / "fakebin")
        env = {"SCROLLS_ELECTRICITY_USD_PER_KWH": "0.2", "SCROLLS_LOCAL_CONFIG": str(cfg),
               toolreg.ENV_LEDGER: str(self.tmp / "ledger"), "KIT_CENTRENET_PREDICT": str(self.script),
               "KIT_UMBILICUS_WEIGHTS": str(self.tmp / "noweights"), "HOME": str(self.tmp / "home")}
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(toolreg.shutil, "disk_usage", return_value=mock.Mock(free=50e9)),
                  mock.patch.object(toolreg, "_platform_limit", return_value=toolreg.LOCAL_LIMIT_S["cloud"])):
            p.start()
            self.addCleanup(p.stop)
        self.reg = toolreg.load(ROOT, {})

    def plugins(self):
        found, problems = host.scan([ROOT / toolreg.PLUGINS_REL])
        self.assertEqual(problems, [])
        return found

    def launch(self, plugin, ctx):
        """VC3D's plugin host in this process: expand the entry, write its plugin-run.json, run the launcher, load
        the declared result; (exit code, what VC3D loaded, the result path)."""
        out = Path(ctx["output"])
        out.mkdir(parents=True, exist_ok=True)
        args, rpath = host.expand(plugin, ctx)
        (out / "plugin-run.json").write_text("{}")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = toolreg.launch(args, {"HOME": str(self.tmp / "nohome")}, 1)
        loaded = host.load_result(plugin["doc"]["result"]["kind"], rpath) if Path(rpath).exists() else None
        return code, loaded, rpath

    def scan(self, scroll="PHerc0332"):
        """A local copy of a 9.362 um scan kept under the bucket's layout."""
        vol = self.tmp / "mirror" / scroll / "volumes" / umb.SCAN
        (vol / "0").mkdir(parents=True, exist_ok=True)
        (vol / "0" / ".zarray").write_text(json.dumps({"shape": [1024, 3600, 4000], "chunks": [128, 128, 128],
                                                        "dtype": "|u1", "zarr_format": 2}))
        (vol / "meta.json").write_text(json.dumps({"voxelsize": 9.362}))
        return vol

    def weights(self):
        umb.write_weights(self.tmp / "fold")
        return {"first": str(self.tmp / "fold" / "umbilicus-first-all.pt"),
                "zoom": str(self.tmp / "fold" / "umbilicus-zoom-all.pt")}

    def run_umbilicus(self, mode="ok", name="umb"):
        tool = self.reg.get("umbilicus")
        sel = toolreg.selection_from(volume=str(self.scan()))
        job = toolreg.prepare(tool, sel, self.weights(), {}, yes_download=True, kind="public", root=self.tmp)
        with mock.patch.dict(os.environ, {"FAKE_PREDICT": mode}):
            return toolreg.run(tool, job, run_dir=self.tmp / "runs" / name, root=self.tmp, registry=self.reg)


@needs_registry
class ManifestTest(Base):
    def test_umbilicus_gets_a_plan_entry_only_and_rowscore_takes_the_segment(self):
        self.assertEqual(toolreg.check(ROOT), [])
        umbt, row = self.reg.get("umbilicus"), self.reg.get("rowscore")
        self.assertEqual(toolreg.vc3d_entries(umbt), ["plan"])
        why = " ".join(toolreg.vc3d_plan_reasons(umbt))
        self.assertIn("--yes-download", why)
        self.assertIn("600 s local rule", why)
        self.assertEqual(toolreg.vc3d_entries(row), ["run"])
        found = self.plugins()
        self.assertIn("scrolls.umbilicus.plan", found)
        self.assertNotIn("scrolls.umbilicus", found)
        plan = found["scrolls.umbilicus.plan"]
        self.assertIn("an open volume", host.enabled(plan, {})[1])
        self.assertTrue(host.enabled(plan, {"volume": umb.URL})[0])
        rs = found["scrolls.rowscore"]
        self.assertIn("{segment}", rs["doc"]["args"])
        self.assertIn("an active segment", host.enabled(rs, {"ink_overlay": "/s/m.tif", "volume": "/v"})[1])
        self.assertTrue(host.enabled(rs, {"segment": "/s", "ink_overlay": "/s/m.tif", "volume": "/v"})[0])

    def test_both_are_autopipeline_backends_already(self):
        self.assertEqual(toolreg.existing_backends(self.reg.get("umbilicus")), ["centrenet"])
        self.assertEqual(toolreg.existing_backends(self.reg.get("rowscore")), ["rowscore"])
        block = toolreg.stage_choices("umbilicus", self.reg)["centrenet"]["registry"]
        self.assertEqual(block["manifest_sha256"], self.reg.get("umbilicus").digest)
        self.assertIn("rowscore", toolreg.stage_choices("triage", self.reg))
        self.assertNotIn("ap", toolreg.doors(self.reg.get("umbilicus")))     # no AutoPipeline in public Scrolls


@needs_registry
class UmbilicusTest(Base):
    def test_vc3d_writes_a_plan_and_nothing_runs(self):
        vol = self.scan()
        found = self.plugins()
        code, loaded, rpath = self.launch(found["scrolls.umbilicus.plan"], {"volume": str(vol),
                                                                             "output": str(self.tmp / "vc3d-plan")})
        self.assertEqual(code, toolreg.EXIT_OK)
        self.assertEqual(loaded["kind"], "file")
        plan = json.loads(Path(rpath).read_text())
        self.assertEqual(plan["tool"], "umbilicus")
        gates = {g["rule"]: g for g in plan["plan"]["gates"]}
        self.assertEqual(plan["would"], "refuse")                 # as planned from VC3D: no download allowed
        self.assertEqual(gates["downloads"]["verdict"], "refused")
        self.assertIn("--yes-download", gates["downloads"]["detail"])
        self.assertEqual(plan["plan"]["argv"][2:5], ["kit.umbfind", str(vol.resolve()), "--out"])
        self.assertIn("--download", plan["plan"]["argv"])
        self.assertNotIn("target", gates)                       # a center line is geometry, not an ink readout
        self.assertFalse((self.tmp / "vc3d-plan" / "umbilicus.json").exists())
        self.assertFalse((self.tmp / "vc3d-plan" / "slices").exists())

    def test_the_run_writes_a_line_vc3d_reads_and_takes_back(self):
        res, code = self.run_umbilicus()
        self.assertEqual(code, toolreg.EXIT_OK, json.dumps({k: res.get(k) for k in ("warnings", "stderr_tail",
                                                                                    "format_gate")}, default=str))
        self.assertIn("--download", res["argv"])
        self.assertEqual([(g["output"], g["verdict"]) for g in res["format_gate"]], [("umbilicus", "pass")])
        run = Path(res["run"])
        call = json.loads((run / "umbfind.json").read_text())
        self.assertEqual(call["key"], f"PHerc0332/volumes/{umb.SCAN}")
        self.assertFalse(call["weights"]["first"]["pinned"])
        self.assertTrue((run / "slices").is_dir())
        self.assertEqual(res["vc3d"]["plugin_result"], {"kind": "umbilicus", "path": "{output}/umbilicus.json"})
        graph = json.loads((run / "graph.json").read_text())
        self.assertIn("stage:tool:umbilicus", [n["id"] for n in graph["nodes"]])
        found = self.plugins()
        code, loaded, rpath = self.launch(found["scrolls.take-umbilicus"], {
            "output": str(self.tmp / "vc3d-take"), "inputs": {"run": str(run), "output": "umbilicus"}})
        self.assertEqual(code, toolreg.EXIT_OK)
        self.assertEqual(loaded["kind"], "umbilicus")
        self.assertEqual(len(json.loads(Path(rpath).read_text())["control_points"]), 12)

    def test_a_line_vc3d_cannot_read_fails_the_gate_and_none_comes_back(self):
        res, code = self.run_umbilicus("bad", name="bad")
        self.assertEqual(code, toolreg.EXIT_REFUSED)
        self.assertEqual(res["refused_by"], ["format-gate"])
        with self.assertRaisesRegex(toolreg.RegistryError, "format gate failed|so nothing is taken"):
            toolreg.take("umbilicus", self.tmp / "t", run=res["run"])
        res, code = self.run_umbilicus("empty", name="empty")
        self.assertEqual(code, toolreg.EXIT_FAILED)

    def test_without_yes_download_the_run_is_refused_before_it_starts(self):
        tool = self.reg.get("umbilicus")
        job = toolreg.prepare(tool, toolreg.selection_from(volume=str(self.scan())), self.weights(), {},
                              kind="public", root=self.tmp)
        res, code = toolreg.run(tool, job, run_dir=self.tmp / "runs" / "no", root=self.tmp, registry=self.reg)
        self.assertEqual(code, toolreg.EXIT_REFUSED)
        self.assertEqual(res["refused_by"], ["downloads"])
        self.assertFalse((self.tmp / "runs" / "no" / "slices").exists())


@needs_registry
@needs_maps
class RowscoreTest(Base):
    def segment(self, name, records=True):
        seg = self.tmp / name
        seg.mkdir()
        (seg / "meta.json").write_text(json.dumps({"type": "seg", "uuid": name, "format": "tifxyz"}))
        y = np.arange(200)[:, None] * np.ones((1, 300))
        tifffile.imwrite(seg / "pred_a.tif", (0.5 + 0.4 * np.sin(2 * np.pi * y / 40)).astype(np.float32))
        tifffile.imwrite(seg / "depth_flipped_a.tif", np.full((200, 300), 0.5, np.float32))
        if records:
            meta = {"model": "model-a"}
            (seg / "ink-detections.json").write_text(json.dumps([
                {"local_file": "pred_a.tif", "label": "model a", "segment_id": name, "kit_villafmt": meta},
                {"local_file": "depth_flipped_a.tif", "label": "model a (control)", "kit_role": "control:reverse",
                 "segment_id": name, "kit_villafmt": meta}]))
        vol = self.tmp / f"{name}-vol.zarr"
        vol.mkdir()
        (vol / "meta.json").write_text(json.dumps({"voxelsize": 7.91}))
        return seg, vol

    def test_vc3d_finds_the_twin_through_the_segments_records(self):
        seg, vol = self.segment("PHerc0139-w099")
        found = self.plugins()
        code, loaded, rpath = self.launch(found["scrolls.rowscore"], {
            "segment": str(seg), "ink_overlay": str(seg / "pred_a.tif"), "volume": str(vol),
            "output": str(self.tmp / "vc3d-row"), "inputs": {"voxel_um": "auto"}})
        self.assertEqual(code, toolreg.EXIT_OK)
        self.assertEqual(loaded["kind"], "file")
        res = json.loads((self.tmp / "vc3d-row" / "vc3d-result.json").read_text())
        self.assertEqual(res["controls"]["verdict"], "present")
        self.assertEqual(res["argv"][res["argv"].index("--reverse") + 1], str(seg / "depth_flipped_a.tif"))
        self.assertEqual(res["claim"], "Score: a measurement against published labels or a control, not a reading")
        report = json.loads(Path(rpath).read_text())
        self.assertIn("forward", report)                       # a 200 x 300 map is too small for a score

    def test_without_records_there_is_no_control_and_eligible_scrolls_are_refused(self):
        seg, vol = self.segment("PHerc0139-w098", records=False)
        tool = self.reg.get("rowscore")
        sel = toolreg.selection_from(volume=str(vol), segment=str(seg), ink_overlay=str(seg / "pred_a.tif"))
        res, code = toolreg.run(tool, toolreg.prepare(tool, sel, None, {}, kind="public", root=self.tmp),
                                run_dir=self.tmp / "runs" / "nocontrol", root=self.tmp)
        self.assertEqual(code, toolreg.EXIT_OK)
        self.assertEqual(res["controls"]["verdict"], toolreg.NO_CONTROL)
        seg2, vol2 = self.segment("PHerc0125-w001")
        sel = toolreg.selection_from(volume=str(vol2), segment=str(seg2), ink_overlay=str(seg2 / "pred_a.tif"))
        res, code = toolreg.run(tool, toolreg.prepare(tool, sel, None, {}, kind="public", root=self.tmp),
                                run_dir=self.tmp / "runs" / "eligible", root=self.tmp)
        self.assertEqual(code, toolreg.EXIT_REFUSED)
        self.assertEqual(res["refused_by"], ["target"])


if __name__ == "__main__":
    unittest.main()
