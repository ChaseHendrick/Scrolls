"""The tool registry's converters and villa's native tools (public Scrolls manifests in kit/data/registry/).

canvas-points: boxes on a segment's canvas or tifxyz grid (canvas-boxes/1) come back into VC3D as a point
collection of their centers on the surface; a stand-in tool that writes boxes names it as its output's convert step
and is started the way VC3D's plugin host starts it (tests/fake_vc3d_host.py). layers: a stand-in tool's
surface-volume zarr becomes v8in's numbered layer TIFFs inside the run folder, recorded as its own stage in graph.json.
villa-tifxyz-selfcross and villa-tifxyz2obj: listed for agents with the native door, never run, never a VC3D entry.
Everything is synthetic and local."""

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

try:
    import numpy as np
    import tifffile
    import zarr
except ImportError:
    np = tifffile = zarr = None

needs_maps = unittest.skipIf(np is None, "needs numpy, tifffile and zarr")
needs_registry = unittest.skipUnless((ROOT / "kit" / "data" / "registry" / "auc.json").is_file(),
                                     "this checkout has no public Scrolls manifests in kit/data/registry")

# stand-in tools: `boxes RUN` writes canvas boxes on the grid; `render RUN` writes a small surface-volume zarr
FAKE = '''#!{py}
import json, sys
from pathlib import Path
mode, run = sys.argv[1], Path(sys.argv[2])
if mode == "boxes":
    (run / "boxes.json").write_text(json.dumps({{"schema": "canvas-boxes/1", "frame": "grid", "name": "stand-in",
        "boxes": [{{"y0": 10, "y1": 12, "x0": 20, "x1": 22, "label": "first"}},
                  {{"y0": 0, "y1": 3, "x0": 0, "x1": 3, "label": "in the hole"}}]}}))
elif mode == "render":
    import numpy as np, zarr
    a = zarr.open_array(str(run / "render.zarr"), mode="w", shape=(5, 24, 36), chunks=(5, 24, 36), dtype="u1")
    a[:] = (np.arange(5, dtype=np.uint8)[:, None, None] * 10 + np.zeros((5, 24, 36), np.uint8))
'''


def stand_in(tool_id, mode, inputs, outputs, vc3d=None):
    m = {"schema": toolreg.SCHEMA, "id": tool_id, "repo": "community", "title": f"stand-in {tool_id}",
         "inputs": inputs, "run": {"argv": ["fake-conv-tool", mode, "{run}"], "timeout_s": 60},
         "outputs": outputs, "compute": {"where": "local-cpu", "typical_s": 1, "disk_mb": 1},
         "safety": {"model_output": False, "paid_compute": "never", "network": "none"}}
    if vc3d:
        m["vc3d"] = vc3d
    return m


@needs_registry
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="toolreg-conv-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "fake-conv-tool"
        fake.write_text(FAKE.format(py=sys.executable))
        fake.chmod(0o755)
        self.extra = self.tmp / "manifests"
        self.extra.mkdir()
        cfg = self.tmp / "local.json"
        cfg.write_text("{}")
        env = {"SCROLLS_ELECTRICITY_USD_PER_KWH": "0.2", "SCROLLS_LOCAL_CONFIG": str(cfg),
               toolreg.ENV_LEDGER: str(self.tmp / "ledger"), toolreg.ENV_PATH: str(self.extra),
               "HOME": str(self.tmp / "home"), "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(toolreg.shutil, "disk_usage", return_value=mock.Mock(free=50e9))):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(toolreg.ENV_BRIDGE, None)

    def add(self, m):
        (self.extra / f"{m['id']}.json").write_text(json.dumps(m))
        return toolreg.load(ROOT)

    def segment(self):
        """A 30 x 40 tifxyz grid, 20 voxels per step at z = 500, with villa's hole mark in its corner."""
        seg = self.tmp / "w00"
        seg.mkdir()
        yy, xx = np.mgrid[0:30, 0:40].astype(np.float32)
        x = xx * 20 + 100
        x[0:5, 0:5] = -1
        for a, arr in (("x", x), ("y", yy * 20 + 100), ("z", np.full_like(xx, 500.0))):
            tifffile.imwrite(seg / f"{a}.tif", arr)
        (seg / "meta.json").write_text(json.dumps({"type": "seg", "format": "tifxyz", "uuid": "w00",
                                                   "scale": [0.05, 0.05]}))
        return seg


class ManifestTest(Base):
    def test_converters_and_natives_reach_no_menu_and_no_stage(self):
        reg = toolreg.load(ROOT, {})
        for tid in ("canvas-points", "layers"):
            tool = reg.get(tid)
            self.assertEqual(tool.kind, "converter")
            self.assertEqual(toolreg.vc3d_entries(tool), [])
            self.assertIsNone(tool["pipeline"])
            self.assertEqual(tool.safety["paid_compute"], "never")
        self.assertEqual(reg.get("canvas-points").facts["page"], "docs/tools/toolreg.md")
        self.assertNotIn("layers", reg.skip)                     # it has a manifest now
        for tid, prog in (("villa-tifxyz-selfcross", "vc_tifxyz_selfcross"), ("villa-tifxyz2obj", "vc_tifxyz2obj")):
            tool = reg.get(tid)
            self.assertEqual((tool.kind, tool["repo"], toolreg.doors(tool)), ("native", "community", ["native"]))
            self.assertEqual(tool["native"]["program"], prog)
            self.assertIn("never copied", tool["native"]["source"])
            gates = toolreg.gates(tool, toolreg.selection_from(), {}, root=ROOT)
            self.assertEqual([(g["rule"], g["verdict"]) for g in gates], [("native", "refused")])
            need = toolreg.availability(tool)
            self.assertEqual(need[0]["status"], "ready" if shutil.which(prog) else "missing")
        exported = toolreg.plugin_manifests(reg)
        for key in ("canvas-points", "layers", "villa-tifxyz-selfcross", "villa-tifxyz2obj"):
            self.assertNotIn(key, exported)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(toolreg.main(["list", "--door", "native", "--json"]), 0)
        listed = {r["id"] for r in json.loads(out.getvalue())["tools"]}
        self.assertLessEqual({"villa-flatten", "villa-gen-umbilicus", "villa-grow-seg-from-seed",
                              "villa-render-tifxyz", "villa-tifxyz-selfcross", "villa-tifxyz2obj"}, listed)


@needs_maps
class CanvasPointsTest(Base):
    def test_boxes_come_back_into_vc3d_as_points_on_the_surface(self):
        reg = self.add(stand_in(
            "boxer", "boxes", {"surface": {"from": "segment", "format": ["tifxyz"]}},
            {"boxes": {"kind": "points", "format": "json", "path": "{run}/boxes.json", "convert": "canvas-points"}},
            vc3d={"menu": "segment", "label": "Stand-in boxes", "result": "boxes"}))
        self.assertEqual(toolreg.plugin_result(reg.get("boxer"), reg),
                         {"kind": "points", "path": "{output}/convert/boxes/points.json"})
        dest = self.tmp / "plugins"
        toolreg.export_vc3d(dest, reg, root=ROOT)
        found, problems = host.scan([dest])
        self.assertEqual(problems, [])
        seg = self.segment()
        out = self.tmp / "vc3d-run"
        out.mkdir()
        args, rpath = host.expand(found["scrolls.boxer"], {"segment": str(seg), "output": str(out)})
        (out / "plugin-run.json").write_text("{}")                 # VC3D writes it before the tool starts
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = toolreg.launch(args, {"HOME": str(self.tmp / "nohome")}, 1)
        res = json.loads((out / "vc3d-result.json").read_text())
        self.assertEqual(code, toolreg.EXIT_OK, json.dumps(res.get("warnings")))
        conv = res["conversions"][0]
        self.assertEqual((conv["converter"], conv["status"]), ("canvas-points", "ok"))
        self.assertEqual([g["verdict"] for g in res["format_gate"]], ["pass"])   # the converted collection
        loaded = host.load_result("points", rpath)
        self.assertEqual(loaded["kind"], "points")
        doc = json.loads(Path(rpath).read_text())
        self.assertEqual(doc["collections"]["1"]["name"], "stand-in")
        self.assertEqual([q["p"] for q in doc["collections"]["1"]["points"].values()], [[510.0, 310.0, 500.0]])
        report = json.loads((out / "convert" / "boxes" / "canvas-points.json").read_text())
        self.assertEqual([q["label"] for q in report["skipped"]], ["in the hole"])
        nodes = [n["id"] for n in json.loads((out / "graph.json").read_text())["nodes"]]
        self.assertIn("stage:convert:boxes", nodes)


@needs_maps
class LayersTest(Base):
    def test_a_surface_volume_output_becomes_layer_tiffs_in_the_run_folder(self):
        reg = self.add(stand_in("render", "render", {}, {
            "volume": {"kind": "volume", "format": "zarr", "path": "{run}/render.zarr", "convert": "layers"}}))
        tool = reg.get("render")
        job = toolreg.prepare(tool, toolreg.selection_from(), {}, kind="public")
        res, code = toolreg.run(tool, job, run_dir=self.tmp / "run", root=ROOT, registry=reg)
        self.assertEqual(code, toolreg.EXIT_OK, json.dumps(res.get("warnings")))
        conv = res["conversions"][0]
        self.assertEqual((conv["converter"], conv["status"]), ("layers", "ok"))
        folder = self.tmp / "run" / "convert" / "volume" / "layers"
        self.assertEqual(res["outputs"][0]["path"], str(folder))
        files = sorted(p.name for p in folder.glob("*.tif"))
        self.assertEqual(files, ["00.tif", "01.tif", "02.tif", "03.tif", "04.tif"])
        self.assertEqual([int(tifffile.imread(folder / f).max()) for f in files], [0, 10, 20, 30, 40])  # as stored
        self.assertTrue((self.tmp / "run" / "render.zarr").is_dir())               # the zarr is kept
        graph = json.loads((self.tmp / "run" / "graph.json").read_text())
        stage = next(n for n in graph["nodes"] if n["id"] == "stage:convert:volume")
        self.assertEqual((stage["backend"], stage["status"]), ("layers", "done"))


if __name__ == "__main__":
    unittest.main()
