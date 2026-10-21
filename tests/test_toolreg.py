"""The tool registry (kit/toolreg.py): manifests, doors, selection, binding, gates, the runner and its write audit,
VC3D's handoff, the AutoPipeline door, and VC3D's plugin host (tests/fake_vc3d_host.py, no VC3D build).

Every run here uses small fake tools on PATH and a temporary ledger; the disk check is mocked, so the tests do not
depend on the free space of the machine that runs them."""

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

from kit import cli, ledger, toolreg

ROOT = Path(__file__).resolve().parent.parent
# Scrolls-private carries the engine (kit/toolreg.py, byte-identical) and this file, but its kit/data/registry holds
# only its private tools' manifests, so the tests of public Scrolls' own manifests and plugin entries run only where
# those manifests are (auc.json marks them)
needs_registry = unittest.skipUnless((ROOT / "kit" / "data" / "registry" / "auc.json").is_file(),
                                     "this checkout has no public Scrolls manifests in kit/data/registry")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_vc3d_host as host  # noqa: E402

try:
    import numpy as np
    import tifffile
except ImportError:  # the map tests skip without them
    np = tifffile = None

FAKE = '''#!{py}
import json, os, sys
from pathlib import Path
mode = sys.argv[1]
if os.environ.get("FAKE_COUNT"):
    with open(os.environ["FAKE_COUNT"], "a") as fh:
        fh.write(mode + "\\n")
if mode == "ok":
    src, run = sys.argv[2], Path(sys.argv[3])
    seen = [k for k in os.environ if k == "KIT_ALLOW_MODAL" or k.startswith("MODAL_")]
    (run / "report.json").write_text(json.dumps({{"cwd": os.getcwd(), "tmpdir": os.environ.get("TMPDIR"),
                                                 "modal": seen, "src": src, "score": 0.5}}))
elif mode == "touch":
    with open(sys.argv[2], "a") as fh:
        fh.write("changed")
    (Path(sys.argv[3]) / "report.json").write_text("{{}}")
elif mode == "fail":
    sys.exit(1)
elif mode == "nooutput":
    pass
elif mode == "points":
    (Path(sys.argv[3]) / "points.json").write_text(json.dumps([[1, 2, 3], {{"xyz": [4, 5, 6]}}]))
elif mode == "badpoints":
    (Path(sys.argv[3]) / "points.json").write_text(json.dumps([[1, 2, 3], [4, "x", 6]]))
elif mode == "conv":
    pts = json.loads(Path(sys.argv[2]).read_text())
    doc = {{"vc_pointcollections_json_version": "1", "collections": {{"1": {{"name": "c", "points": {{
        str(i + 1): {{"p": [float(v) for v in (q["xyz"] if isinstance(q, dict) else q)]}} for i, q in enumerate(pts)}}}}}}}}
    (Path(sys.argv[3]) / "collection.json").write_text(json.dumps(doc))
elif mode == "nometa":
    (Path(sys.argv[3]) / "seg").mkdir()
elif mode in ("goodseg", "badseg"):
    import numpy as np, tifffile
    seg = Path(sys.argv[3]) / "seg"
    seg.mkdir()
    (seg / "meta.json").write_text(json.dumps({{"type": "seg", "format": "tifxyz", "uuid": "s", "scale": [1, 1]}}))
    g = np.ones((8, 10), np.float32) * 5
    z = g.copy()
    z[2, 3] = 0 if mode == "badseg" else 5
    x = g.copy()
    x[0, 0] = -1
    for name, a in (("x", x), ("y", g), ("z", z)):
        tifffile.imwrite(seg / (name + ".tif"), a)
elif mode == "map":
    import numpy as np, tifffile
    out = Path(sys.argv[3])
    ramp = np.tile(np.linspace(0.0, 1.0, 64, dtype=np.float32), (32, 1))
    tifffile.imwrite(out.with_name(out.stem + ".tif"), ramp)
    tifffile.imwrite(out.with_name(out.stem + "_reverse.tif"), np.full((32, 64), 0.5, np.float32))
elif mode == "u8map":
    import numpy as np, tifffile
    out = Path(sys.argv[3])
    a = np.zeros((32, 64), np.uint8)
    a[4:8, 4:8] = 200
    tifffile.imwrite(out.with_name(out.stem + ".tif"), a)
    tifffile.imwrite(out.with_name(out.stem + "_reverse.tif"), np.zeros((32, 64), np.uint8))
'''

# a stand-in for the released scrolls-inkfilter command line (submission/progress-2026-10-inkfilter, cli.py): VOLUME
# --output MAP [--crop Y0 Y1 X0 X1] writes MAP, MAP_reverse and MAP.json; a crop gives a map of the crop's size
FAKE_INKFILTER = '''#!{py}
import json, sys
from pathlib import Path
import numpy as np, tifffile
args = sys.argv[1:]
out = Path(args[args.index("--output") + 1])
h, w = 40, 60
crop = None
if "--crop" in args:
    i = args.index("--crop")
    crop = [int(v) for v in args[i + 1:i + 5]]
    h, w = crop[1] - crop[0], crop[3] - crop[2]
ramp = np.tile(np.linspace(0.0, 1.0, w, dtype=np.float32), (h, 1))
tifffile.imwrite(out, ramp)
tifffile.imwrite(out.with_name(out.stem + "_reverse" + out.suffix), np.full((h, w), 0.5, np.float32))
out.with_suffix(".json").write_text(json.dumps({{"crop": crop, "volume": args[0]}}))
'''


def manifest(tool_id="fake", mode="ok", **over):
    m = {"schema": toolreg.SCHEMA, "id": tool_id, "repo": "community", "title": f"Fake tool {tool_id}",
         "inputs": {"src": {"from": "path"}},
         "run": {"argv": ["fake-tool", mode, "{in.src}", "{run}"], "timeout_s": 60},
         "outputs": {"report": {"kind": "report", "format": "json", "path": "{run}/report.json"}},
         "compute": {"where": "local-cpu", "typical_s": 1, "disk_mb": 1},
         "safety": {"model_output": False, "paid_compute": "never", "network": "none"}}
    m.update(over)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="toolreg-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        fake = self.bin / "fake-tool"
        fake.write_text(FAKE.format(py=sys.executable))
        fake.chmod(0o755)
        self.reg_dir = self.tmp / "manifests"
        self.reg_dir.mkdir()
        self.ledger = self.tmp / "experiments"
        cfg = self.tmp / "local.json"
        cfg.write_text("{}")
        patches = [mock.patch.dict(os.environ, {"SCROLLS_ELECTRICITY_USD_PER_KWH": "0.2", "SCROLLS_LOCAL_CONFIG":
                                                str(cfg), toolreg.ENV_LEDGER: str(self.ledger),
                                                "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}),
                   mock.patch.object(toolreg.shutil, "disk_usage", return_value=mock.Mock(free=50e9))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.src = self.tmp / "input.txt"
        self.src.write_text("data")

    def add(self, m):
        (self.reg_dir / f"{m['id']}.json").write_text(json.dumps(m))
        return self.registry().get(m["id"])

    def registry(self):
        return toolreg.load(self.tmp / "norepo", {toolreg.ENV_PATH: str(self.reg_dir)})

    def go(self, tool, explicit=None, params=None, sel=None, **kw):
        sel = sel or toolreg.selection_from()
        job = toolreg.prepare(tool, sel, explicit if explicit is not None else {"src": str(self.src)}, params,
                              kind="public", **kw)
        return toolreg.run(tool, job, run_dir=self.tmp / "run" / tool.id, root=self.tmp)


class ManifestTest(Base):
    @needs_registry
    def test_repository_manifests_load_and_pass_the_check(self):
        reg = toolreg.load(ROOT, {})
        self.assertEqual(reg.problems, [])
        self.assertIn("auc", reg)
        self.assertIn("villa-render-tifxyz", reg)
        self.assertEqual(toolreg.check(ROOT), [])

    @needs_registry
    def test_public_manifests_name_only_public_kit_commands(self):
        commands = toolreg._kit_commands()
        for tool in toolreg.load(ROOT, {}):
            if tool.kind != "tool":
                continue
            self.assertEqual(tool["repo"], "public", tool.id)
            argv = tool["run"]["argv"]
            if argv[0] != "{python}":            # a released package's own program, named on its page
                self.assertIn(argv[0], (ROOT / tool.facts["page"]).read_text(), tool.id)
                continue
            if argv[2].startswith("kit."):       # a kit module, such as kit.inklens for a tool kept outside kit/
                self.assertTrue((ROOT / "kit" / f"{argv[2][4:]}.py").is_file(), tool.id)
                continue
            self.assertEqual(argv[:3], ["{python}", "-m", "kit"], tool.id)
            self.assertIn(argv[3], commands.parsers, tool.id)

    def test_shape_errors_are_reported(self):
        cases = {
            "unknown key": dict(manifest(), extra=1),
            "names a fixed path": manifest(run={"argv": ["fake-tool", "/etc/passwd"]}),
            "start with {run}/": manifest(outputs={"r": {"kind": "report", "format": "json", "path": "/tmp/r"}}),
            "which inputs does not declare": manifest(run={"argv": ["fake-tool", "{in.nope}"]}),
            "a bare program name": manifest(run={"argv": ["./tool", "x"]}),
            "a community manifest needs a title": {k: v for k, v in manifest().items() if k != "title"},
            "at least one control output": manifest(outputs={"map": {"kind": "overlay", "format": "tiff-float32",
                                                                     "path": "{run}/m.tif"}},
                                                    safety={"model_output": True, "paid_compute": "never",
                                                            "network": "none"}),
            "pipeline.reverse": manifest(pipeline={"stage": "ink", "contract": "ink-command", "input": "src"}),
            "no generic registry runner": manifest(pipeline={"stage": "flatten", "contract": "flatten"}),
            "pipeline.stage": manifest(pipeline={"stage": "score", "existing": "auc"}),
            "safety.paid_compute": manifest(safety={"model_output": False, "paid_compute": "sometimes",
                                                    "network": "none"}),
        }
        for want, m in cases.items():
            problems = toolreg.validate_manifest(m)
            self.assertTrue(any(want in p for p in problems), f"{want}: {problems}")
        self.assertEqual(toolreg.validate_manifest(manifest()), [])

    def test_bad_manifests_become_problems_and_ids_are_unique(self):
        (self.reg_dir / "broken.json").write_text("{not json")
        (self.reg_dir / "wrongname.json").write_text(json.dumps(manifest("other")))
        self.add(manifest("fake"))
        second = self.tmp / "more"
        second.mkdir()
        (second / "fake.json").write_text(json.dumps(manifest("fake", mode="fail")))
        reg = toolreg.load(self.tmp / "norepo", {toolreg.ENV_PATH: f"{self.reg_dir}{os.pathsep}{second}"})
        self.assertEqual(sorted(reg.tools), ["fake"])
        joined = "\n".join(reg.problems)
        self.assertIn("does not parse", joined)
        self.assertIn("named wrongname.json", joined)
        self.assertIn("already taken", joined)
        self.assertEqual(reg.tools["fake"]["run"]["argv"][1], "ok")

    @needs_registry
    def test_doors_are_worked_out(self):
        reg = toolreg.load(ROOT, {})
        self.assertIn("vc3d", toolreg.doors(reg.get("auc")))
        self.assertIn("vc3d", toolreg.doors(reg.get("verify")))          # its maps bind through the parent bridge
        self.assertNotIn("vc3d", toolreg.doors(self.add(manifest("pathonly"))))     # a plain path input: no entry
        self.assertEqual(toolreg.doors(reg.get("villa-flatten")), ["native"])
        planned = self.add(manifest("gpu", compute={"where": "modal-gpu"}))
        self.assertIn("planned only", " ".join(toolreg.vc3d_plan_reasons(planned)))
        self.assertEqual(toolreg.vc3d_entries(planned), [])                          # its input is a plain path
        quota = self.add(manifest("quota", safety={"model_output": False, "paid_compute": "never",
                                                   "network": "public-read", "quota": "zerogpu"}))
        self.assertIn("quota", " ".join(toolreg.vc3d_reasons(quota)))
        with mock.patch.dict(toolreg.HOOKS, {"ap_available": lambda: True}):
            self.assertIn("ap", toolreg.doors(reg.get("rowscore")))
        self.assertNotIn("ap", toolreg.doors(reg.get("rowscore")))

    def test_a_manifest_may_belong_to_another_tools_page(self):
        root = self.tmp / "repo"
        (root / "docs" / "tools").mkdir(parents=True)
        shutil.copy(ROOT / "docs" / "tools" / "toolreg.md", root / "docs" / "tools" / "toolreg.md")
        folder = root / toolreg.REGISTRY_REL
        folder.mkdir(parents=True)
        for tid, page in (("toolreg-extra", "toolreg"), ("orphan", "nope")):
            m = {k: v for k, v in manifest(tid).items() if k != "title"}
            (folder / f"{tid}.json").write_text(json.dumps(dict(m, repo="public", page=page)))
        toolreg.write_facts(root)
        extra = json.loads((folder / "toolreg-extra.json").read_text())
        self.assertEqual(extra["facts"]["page"], "docs/tools/toolreg.md")      # the shared page's facts
        self.assertEqual(toolreg.Tool(extra, "x.json", "kit").title, "toolreg")
        self.assertEqual(toolreg.Tool(dict(extra, title="extra entry"), "x.json", "kit").title, "extra entry")
        self.assertEqual(toolreg.Tool(dict(manifest(), title="own", facts={"title": "page"}), "x.json", "kit").title,
                         "page")                                              # without page, the page's name wins
        problems = "\n".join(toolreg.check(root, commands=None))
        self.assertNotIn("toolreg-extra.json: no tool page", problems)
        self.assertNotIn("toolreg-extra.json: facts are out of date", problems)
        self.assertIn("no tool page docs/tools/nope.md", problems)
        # a page whose Network field is "None for local inputs. ..." fits none and public-read, never download
        page = root / "docs" / "tools" / "toolreg.md"
        text = page.read_text()
        field = next(line for line in text.splitlines() if line.startswith("| Network |"))
        page.write_text(text.replace(field, "| Network | None for local inputs. A URL is read anonymously |"))
        toolreg.write_facts(root)
        for net, ok in (("none", True), ("public-read", True), ("download", False)):
            doc = json.loads((folder / "toolreg-extra.json").read_text())
            doc["safety"]["network"] = net
            (folder / "toolreg-extra.json").write_text(json.dumps(doc))
            problems = "\n".join(toolreg.check(root, commands=None))
            self.assertEqual("toolreg-extra.json: the page's Network field" not in problems, ok, net)
        page.write_text(text.replace(field, "| Network | Reads the bucket |"))
        doc["safety"]["network"] = "none"
        (folder / "toolreg-extra.json").write_text(json.dumps(doc))
        toolreg.write_facts(root)
        self.assertIn("toolreg-extra.json: the page's Network field", "\n".join(toolreg.check(root, commands=None)))
        self.assertIn("page names a tool page", " ".join(toolreg.validate_manifest(dict(manifest(), page="A B"))))

    def test_digest_ignores_generated_facts(self):
        a = toolreg.Tool(manifest(), "a.json", "kit")
        b = toolreg.Tool(dict(manifest(), facts={"title": "x"}), "a.json", "kit")
        self.assertEqual(a.digest, b.digest)


class SelectionAndBindingTest(Base):
    def segment(self, name="w00"):
        seg = self.tmp / name
        seg.mkdir()
        (seg / "meta.json").write_text(json.dumps({"type": "seg", "uuid": "u1", "format": "tifxyz", "scale": [0.5, 0.5],
                                                   "vc_open_data_segment_id": "abc"}))
        (seg / "layers").mkdir()
        (seg / "layers" / "00.tif").write_bytes(b"x")
        for n in ("map.tif", "map_reverse.tif"):
            (seg / n).write_bytes(b"x")
        (seg / f"{name}_inklabels.zarr").mkdir()
        (seg / f"{name}_supervision_mask.zarr").mkdir()
        return seg

    def test_selection_reads_the_segment_folder(self):
        seg = self.segment()
        (seg / "ink-detections.json").write_text(json.dumps([{"local_file": "map.tif", "label": "fwd"},
                                                            {"local_file": "map_reverse.tif",
                                                             "label": "map reverse-depth control"}]))
        vol = self.tmp / "vol.zarr"
        vol.mkdir()
        (vol / "meta.json").write_text(json.dumps({"voxelsize": 7.91}))
        sel = toolreg.selection_from(volume=str(vol), segment=str(seg), point="1,2,3", region="10,0,5,0,20,6")
        self.assertEqual(sel["schema"], toolreg.SELECTION_SCHEMA)
        self.assertEqual(sel["volume"]["voxel_um"], 7.91)
        self.assertEqual(sel["segment"]["render"], str((seg / "layers").resolve()))
        self.assertEqual([o["role"] for o in sel["segment"]["overlays"]], ["forward", "control:reverse"])
        self.assertEqual(sel["segment"]["catalog"], {"vc_open_data_segment_id": "abc"})
        self.assertEqual(sel["region"], {"space": "volume", "low": [0.0, 0.0, 5.0], "high": [10.0, 20.0, 6.0]})
        self.assertEqual(len(sel["digest"]), 64)
        with self.assertRaises(toolreg.RegistryError):
            toolreg.selection_from(point="1,2")
        with self.assertRaises(toolreg.RegistryError):
            toolreg.selection_from(crop="5,1,0,4")

    def test_selection_from_a_running_vc3d_uses_read_calls_only(self):
        seg = self.segment()
        app = host.App(state={"vpkg": {"path": "/p.volpkg.json"}, "volume": {"id": "v1", "path": "",
                                                                             "voxelSize": 2.4},
                              "activeSurface": {"id": "w00"}, "focusPoi": {"position": {"x": 1, "y": 2, "z": 3}}},
                       segments=[{"id": "w00", "path": str(seg)}])
        sel = toolreg.selection_from_app("bridge", call=app.call)
        self.assertEqual([c[0] for c in app.calls], ["state.get", "segments.list"])
        self.assertEqual(sel["source"], "bridge")
        self.assertEqual(sel["segment"]["id"], "w00")
        self.assertEqual(sel["point"], [1.0, 2.0, 3.0])
        self.assertEqual(sel["volume"]["voxel_um"], 2.4)

    @needs_registry
    def test_binding_finds_the_twin_labels_and_mask(self):
        seg = self.segment()
        tool = toolreg.load(ROOT, {}).get("auc")
        sel = toolreg.selection_from(segment=str(seg), ink_overlay=str(seg / "map.tif"))
        values, record = toolreg.bind(tool, sel)
        self.assertEqual(Path(values["in.control"]).name, "map_reverse.tif")
        self.assertEqual(Path(values["in.labels"]).name, "w00_inklabels.zarr")
        self.assertEqual(Path(values["in.mask"]).name, "w00_supervision_mask.zarr")
        self.assertEqual(record["control"]["from"], "segment.overlay.reverse")
        (seg / "map_reverse.tif").unlink()
        values, record = toolreg.bind(tool, sel)       # the control is optional: the result says not a pass
        self.assertNotIn("in.control", values)

    @needs_registry
    def test_binding_refusals_name_what_is_missing(self):
        tool = toolreg.load(ROOT, {}).get("auc")
        with self.assertRaisesRegex(toolreg.BindError, "selected ink detection overlay"):
            toolreg.bind(tool, toolreg.selection_from())
        seg = self.segment()
        shutil.rmtree(seg / "w00_inklabels.zarr")
        with self.assertRaisesRegex(toolreg.BindError, "ink labels"):
            toolreg.bind(tool, toolreg.selection_from(segment=str(seg), ink_overlay=str(seg / "map.tif")))
        with self.assertRaisesRegex(toolreg.BindError, "no input"):
            toolreg.bind(tool, toolreg.selection_from(), {"nope": "x"})

    @needs_registry
    def test_params_take_defaults_types_and_the_volume_voxel_size(self):
        tool = toolreg.load(ROOT, {}).get("hpscore")
        with self.assertRaisesRegex(toolreg.BindError, "voxel_um"):
            toolreg.bind_params(tool, {}, toolreg.selection_from())
        vals, rec = toolreg.bind_params(tool, {"voxel_um": "auto"}, toolreg.selection_from(voxel_um=7.91))
        self.assertEqual(vals["param.voxel_um"], "7.91")
        with self.assertRaisesRegex(toolreg.BindError, "not a number"):
            toolreg.bind_params(tool, {"voxel_um": "big"}, toolreg.selection_from())
        auc = toolreg.load(ROOT, {}).get("auc")
        vals, _ = toolreg.bind_params(auc, {}, toolreg.selection_from())
        self.assertEqual(vals["param.bootstrap"], "0")

    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_a_focus_region_becomes_a_box_on_the_canvas(self):
        seg = self.tmp / "grid"
        seg.mkdir()
        rows, cols = np.mgrid[0:20, 0:30].astype(np.float32)
        tifffile.imwrite(seg / "x.tif", cols * 4)
        tifffile.imwrite(seg / "y.tif", rows * 4)
        tifffile.imwrite(seg / "z.tif", np.full((20, 30), 100, np.float32))
        (seg / "meta.json").write_text(json.dumps({"type": "seg", "uuid": "g", "format": "tifxyz",
                                                   "scale": [0.25, 0.25]}))
        m = manifest(inputs={"src": {"from": "path"}, "crop": {"from": "region", "space": "segment_canvas"}},
                     run={"argv": ["fake-tool", "ok", "{in.src}", "{run}", "{in.crop.y0}", "{in.crop.x1}"]})
        tool = self.add(m)
        sel = toolreg.selection_from(segment=str(seg), region="8,4,0,20,12,200")
        values, _ = toolreg.bind(tool, sel, {"src": str(self.src)})
        # vertices 2..5 (x) and 1..3 (y) are inside; the canvas is the grid over scale 0.25
        self.assertEqual((values["in.crop.y0"], values["in.crop.y1"]), ("4", "16"))
        self.assertEqual((values["in.crop.x0"], values["in.crop.x1"]), ("8", "24"))


class GateTest(Base):
    def gate_list(self, tool, sel=None, record=None, **kw):
        return {g["rule"]: g["verdict"] for g in toolreg.gates(tool, sel or toolreg.selection_from(), record or {},
                                                                root=self.tmp, **kw)}

    def test_each_rule_can_refuse_or_plan(self):
        g = self.gate_list(self.add(manifest("a", facts={"go_ahead": True})))
        self.assertEqual(g["go-ahead"], "refused")
        g = self.gate_list(self.add(manifest("b", safety={"model_output": False, "paid_compute": "plan-only",
                                                          "network": "none"})))
        self.assertEqual(g["paid-compute"], "planned")
        g = self.gate_list(self.add(manifest("c", compute={"typical_s": 99999})))
        self.assertEqual(g["local-time"], "planned")
        tool = self.add(manifest("d", safety={"model_output": False, "paid_compute": "never", "network": "none",
                                              "writes_outside": ["segment-folder"]}))
        self.assertEqual(self.gate_list(tool)["writes-outside"], "refused")
        self.assertEqual(self.gate_list(tool, allow_outside=("segment-folder",))["writes-outside"], "pass")
        tool = self.add(manifest("e", safety={"model_output": False, "paid_compute": "never", "network": "download",
                                              "downloads_mb": 3}))
        self.assertEqual(self.gate_list(tool)["downloads"], "refused")
        self.assertEqual(self.gate_list(tool, yes_download=True)["downloads"], "pass")
        with mock.patch.object(toolreg.shutil, "disk_usage", return_value=mock.Mock(free=10e6)):
            self.assertEqual(self.gate_list(self.add(manifest("f")))["disk"], "refused")

    def test_target_scrolls_are_refused_in_public_and_need_a_prereg_in_private(self):
        tool = self.add(manifest("t", safety={"model_output": False, "readout": True, "paid_compute": "never",
                                              "network": "none"}))
        rec = {"src": {"value": "/data/PHerc0826/segments/a/map.tif"}}
        self.assertEqual(self.gate_list(tool, record=rec, kind="public")["target"], "refused")
        self.assertEqual(self.gate_list(tool, record=rec, kind="private")["target"], "refused")
        self.assertEqual(self.gate_list(tool, record={"src": {"value": "/d/PHerc0841/w00.tif"}},
                                        kind="public")["target"], "pass")
        self.assertEqual(self.gate_list(tool, kind="public")["target"], "warn")
        ledger.init("t-826", "PHerc0826", "q", "fixed readout rule", root=self.ledger)
        with mock.patch.object(toolreg, "_ledger_root", return_value=self.ledger):
            g = self.gate_list(tool, record=rec, kind="private", purpose="target", experiment="t-826")
            self.assertEqual(g["target"], "pass")
            g = self.gate_list(tool, record={"src": {"value": "/d/PHerc1447/m.tif"}}, kind="private",
                               purpose="target", experiment="t-826")
            self.assertEqual(g["target"], "refused")
        self.assertEqual(toolreg.scrolls_named("x/pherc_826/y", "PHercParis4"), {"PHERC0826", "PHERCPARIS4"})


class RunTest(Base):
    def test_a_run_is_ledgered_audited_and_handed_over(self):
        tool = self.add(manifest())
        with mock.patch.dict(os.environ, {"KIT_ALLOW_MODAL": "1", "MODAL_TOKEN_ID": "x"}):
            res, code = self.go(tool)
        self.assertEqual((res["status"], code), ("ok", 0))
        run = Path(res["run"])
        report = json.loads((run / "report.json").read_text())
        self.assertEqual(Path(report["cwd"]).resolve(), run.resolve())
        self.assertEqual(Path(report["tmpdir"]), run / "tmp")
        self.assertEqual(report["modal"], [])
        for name in ("selection.json", "registry-run.json", "provenance.json", "graph.json", "vc3d-result.json"):
            self.assertTrue((run / name).is_file(), name)
        self.assertEqual(json.loads((run / "vc3d-result.json").read_text())["status"], "ok")
        costs = ledger.load(res["cost"]["slug"], self.ledger)["costs"]
        self.assertEqual(costs[-1]["local"]["exit_code"], 0)
        graph = json.loads((run / "graph.json").read_text())
        self.assertIn({"from": f"file:{self.src.resolve()}", "to": "stage:tool:fake", "rel": "read"}, graph["edges"])
        self.assertIn({"from": "stage:tool:fake", "to": "file:report.json", "rel": "made"}, graph["edges"])
        self.assertEqual(res["vc3d"]["plugin_result"], {"kind": "file", "path": "{output}/vc3d-result.json"})

    def test_a_tool_that_changes_its_input_is_marked_violated(self):
        res, code = self.go(self.add(manifest(mode="touch")))
        self.assertEqual((res["status"], code), ("violated", toolreg.EXIT_VIOLATED))
        self.assertIn(str(self.src.resolve()), res["violations"]["changed_outside"])
        self.assertEqual(res["open"], [])

    def test_failures_and_missing_outputs_fail(self):
        res, code = self.go(self.add(manifest("f1", mode="fail")))
        self.assertEqual((res["status"], code, res["tool_exit"]), ("failed", 1, 1))
        res, code = self.go(self.add(manifest("f2", mode="nooutput")))
        self.assertEqual((res["status"], code), ("failed", 1))
        self.assertIn("missing output(s): report", res["warnings"])

    def test_refusals_and_plans_write_a_result_and_run_nothing(self):
        count = self.tmp / "count.txt"
        with mock.patch.dict(os.environ, {"FAKE_COUNT": str(count)}):
            res, code = self.go(self.add(manifest("g", facts={"go_ahead": True})))
            self.assertEqual((res["status"], code, res["refused_by"]), ("refused", 3, ["go-ahead"]))
            res, code = self.go(self.add(manifest("p", compute={"where": "modal-gpu"})))
            self.assertEqual((res["status"], code), ("planned", 4))
        self.assertFalse(count.exists())
        self.assertEqual(json.loads((Path(res["run"]) / "vc3d-result.json").read_text())["status"], "planned")

    def test_an_identical_rerun_is_reused_and_out_must_be_empty(self):
        tool = self.add(manifest())
        sel = toolreg.selection_from()
        job = toolreg.prepare(tool, sel, {"src": str(self.src)}, kind="public")
        res, _ = toolreg.run(tool, job, root=self.tmp)
        job = toolreg.prepare(tool, sel, {"src": str(self.src)}, kind="public")
        again, code = toolreg.run(tool, job, root=self.tmp)
        self.assertTrue(again.get("reused"))
        self.assertEqual(again["run"], res["run"])
        busy = self.tmp / "busy"
        busy.mkdir()
        (busy / "x").write_text("x")
        with self.assertRaisesRegex(toolreg.RegistryError, "not empty"):
            toolreg.run(tool, job, run_dir=busy, root=self.tmp)

    def test_the_cost_ledger_must_have_a_rate(self):
        with mock.patch.dict(os.environ, {"SCROLLS_ELECTRICITY_USD_PER_KWH": ""}):
            res, code = self.go(self.add(manifest()))
        self.assertEqual(code, toolreg.EXIT_BAD)
        self.assertIn("SCROLLS_ELECTRICITY_USD_PER_KWH", res["error"])

    def test_controls_are_checked(self):
        m = manifest(inputs={"src": {"from": "path"}, "ctl": {"from": "path", "required": False}},
                     safety={"model_output": False, "readout": True, "controls": ["ctl"], "paid_compute": "never",
                             "network": "none"})
        res, _ = self.go(self.add(m))
        self.assertEqual(res["controls"]["verdict"], toolreg.NO_CONTROL)
        res, _ = self.go(self.add(dict(m, id="fake2")), {"src": str(self.src), "ctl": str(self.src)})
        self.assertEqual(res["controls"]["verdict"], "present")

    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_maps_get_8_bit_views_on_one_shared_scale(self):
        m = manifest(run={"argv": ["fake-tool", "map", "{in.src}", "{run}/map"]},
                     outputs={"map": {"kind": "overlay", "format": "tiff-float32", "path": "{run}/map.tif",
                                      "role": "forward"},
                              "map_reverse": {"kind": "overlay", "format": "tiff-float32",
                                              "path": "{run}/map_reverse.tif", "role": "control:reverse"}},
                     safety={"model_output": True, "controls": ["map_reverse"], "paid_compute": "never",
                             "network": "none"})
        res, code = self.go(self.add(m))
        self.assertEqual(code, 0, res)
        fwd = tifffile.imread(res["views"]["map"])
        rev = tifffile.imread(res["views"]["map_reverse"])
        self.assertEqual(fwd.dtype, np.uint8)
        self.assertGreater(int(fwd.max()) - int(fwd.min()), 250)
        self.assertLess(int(rev.max()) - int(rev.min()), 2)      # a flat control stays flat, not stretched
        scale = json.loads((Path(res["run"]) / "vc3d" / "scale.json").read_text())
        self.assertEqual(scale["from"], "map")
        self.assertEqual(res["claim"], toolreg.CLAIM)


class OpenTest(Base):
    def run_points(self):
        m = manifest(outputs={"points": {"kind": "points", "format": "json-points", "path": "{run}/points.json"}},
                     run={"argv": ["fake-tool", "points", "{in.src}", "{run}"]}, vc3d={"menu": "tools",
                                                                                      "result": "points"})
        return self.go(self.add(m))

    def test_points_become_a_collection_and_open_calls_are_allow_listed(self):
        res, code = self.run_points()
        self.assertEqual(code, 0, res)
        call = res["open"][0]
        self.assertEqual(call["method"], "points.load_json")
        doc = json.loads(Path(call["params"]["path"]).read_text())
        self.assertEqual(doc["vc_pointcollections_json_version"], "1")
        self.assertEqual([p["p"] for p in doc["collections"]["1"]["points"].values()], [[1, 2, 3], [4, 5, 6]])
        self.assertEqual(res["vc3d"]["plugin_result"], {"kind": "points", "path": "{output}/vc3d/points/points.json"})
        app = host.App()
        out = toolreg.open_run(res["run"])
        self.assertEqual(out["applied"], [])
        out = toolreg.open_run(res["run"], live="x", apply=True, call=app.call)
        self.assertEqual(app.calls, [])                          # it would replace every collection
        self.assertIn("replace-points", out["applied"][0]["skipped"])
        toolreg.open_run(res["run"], live="x", apply=True, replace_points=True, call=app.call)
        self.assertEqual([c[0] for c in app.calls], ["points.load_json"])
        self.assertTrue((Path(res["run"]) / "vc3d" / "open-log.json").is_file())

    def test_a_tampered_result_is_refused_whole(self):
        res, _ = self.run_points()
        path = Path(res["run"]) / "vc3d-result.json"
        doc = json.loads(path.read_text())
        doc["open"] = [{"method": "segments.delete", "params": {}}]
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(toolreg.RegistryError, "allow-list"):
            toolreg.open_run(res["run"])
        doc["open"] = [{"method": "segments.attach", "params": {"location": "/home/someone/segments"}}]
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(toolreg.RegistryError, "outside the run folder"):
            toolreg.open_run(res["run"])

    def test_run_folder_handlers_come_first(self):
        seen = []
        with mock.patch.object(toolreg, "RUN_FOLDERS", [lambda run, **kw: seen.append(run) or {"handled": True}]):
            self.assertEqual(toolreg.open_run(self.tmp), {"handled": True})
        self.assertEqual(seen, [self.tmp])


class PipelineTest(Base):
    def ink_manifest(self):
        return manifest("inky", run={"argv": ["fake-tool", "map", "{in.src}", "{run}/map"]},
                        outputs={"map": {"kind": "overlay", "format": "tiff-float32", "path": "{run}/map.tif",
                                         "role": "forward"},
                                 "map_reverse": {"kind": "overlay", "format": "tiff-float32",
                                                 "path": "{run}/map_reverse.tif", "role": "control:reverse"}},
                        safety={"model_output": True, "controls": ["map_reverse"], "paid_compute": "never",
                                "network": "none"},
                        pipeline={"stage": "ink", "contract": "ink-command", "input": "src", "reverse": "pair",
                                  "pair_output": "map_reverse"})

    @needs_registry
    def test_stage_choices_and_in_memory_ink_models(self):
        tool = self.add(self.ink_manifest())
        reg = self.registry()
        choices = toolreg.stage_choices("ink", reg)
        self.assertEqual(choices["reg:inky"]["registry"]["manifest_sha256"], tool.digest)
        self.assertEqual(choices["reg:inky"]["settings"], {"ink": {"models": ["reg:inky"]}})
        models = toolreg.ink_models(reg)
        cmd = models["reg:inky"]["command"]
        self.assertEqual(models["reg:inky"]["engine"], "command")
        self.assertEqual(cmd[-4:], ["--", "{input}", "{output}", "{reverse}"])
        self.assertEqual(cmd[cmd.index("--sha256") + 1], tool.digest[:16])
        triage = toolreg.stage_choices("triage", toolreg.load(ROOT, {}))
        self.assertEqual(list(triage), ["rowscore"])
        self.assertEqual(triage["rowscore"]["registry"]["id"], "rowscore")

    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_exec_runs_a_pair_tool_once_per_input(self):
        tool = self.add(self.ink_manifest())
        count = self.tmp / "count.txt"
        work = self.tmp / "ap"
        with mock.patch.dict(os.environ, {"FAKE_COUNT": str(count)}):
            self.assertEqual(toolreg.exec_ink(tool, str(self.src), str(work / "fwd.tif"), "0", root=self.tmp), 0)
            self.assertEqual(toolreg.exec_ink(tool, str(self.src), str(work / "rev.npy"), "1", root=self.tmp), 0)
        self.assertEqual(count.read_text().split(), ["map"])
        self.assertGreater(float(tifffile.imread(work / "fwd.tif").max()), 0.9)
        self.assertTrue(np.allclose(np.load(work / "rev.npy"), 0.5))
        with self.assertRaisesRegex(toolreg.RegistryError, "changed after the plan"):
            toolreg.exec_ink(tool, str(self.src), str(work / "x.tif"), "0", sha="0" * 16, root=self.tmp)
        with self.assertRaisesRegex(toolreg.RegistryError, "not an ink-command"):
            toolreg.exec_ink(self.add(manifest()), str(self.src), str(work / "y.tif"), "0", root=self.tmp)


class RepairContractTest(Base):
    """The repair contract: AutoPipeline's qa stage hands a rejected trace, the plan's prediction and the trace's
    seed to a registry tool and takes its repaired tifxyz copy back (exec_repair, stage choices reg:ID)."""

    def repair_manifest(self, mode="goodseg", **pipe):
        return manifest("fixy", run={"argv": ["fake-tool", mode, "{in.surface}", "{run}"]},
                        inputs={"surface": {"from": "segment", "format": ["tifxyz"]},
                                "prediction": {"from": "volume"},
                                "seed": {"from": "point", "required": False}},
                        outputs={"repaired": {"kind": "surface", "format": "tifxyz", "path": "{run}/seg"}},
                        pipeline={"stage": "repair", "contract": "repair", "input": "surface",
                                  "prediction": "prediction", "seed": "seed", "output": "repaired", **pipe})

    def trace(self):
        seg = self.tmp / "trace"
        seg.mkdir(exist_ok=True)
        (seg / "x.tif").write_text("x")
        (seg / "meta.json").write_text(json.dumps({"format": "tifxyz", "uuid": "trace"}))
        return seg

    def test_the_contract_is_checked(self):
        self.assertEqual(toolreg.validate_manifest(self.repair_manifest()), [])
        bad = self.repair_manifest()
        bad["pipeline"]["extra"] = 1
        self.assertIn("pipeline must be an object", " ".join(toolreg.validate_manifest(bad)))
        del bad["pipeline"]["extra"]
        bad["pipeline"].update(input="prediction", output="nope", seed="surface")
        bad["inputs"]["other"] = {"from": "path"}
        bad["params"] = {"k": {"type": "integer"}}
        text = " ".join(toolreg.validate_manifest(bad))
        for want in ("from segment, format tifxyz", "kind surface, format tifxyz", "an optional input from point",
                     "required input(s) other", "param(s) k need a default"):
            self.assertIn(want, text)

    def test_a_repair_tool_is_a_stage_choice_and_runs_into_its_run_folder(self):
        tool = self.add(self.repair_manifest())
        choices = toolreg.stage_choices("repair", self.registry())
        self.assertEqual(choices["reg:fixy"]["settings"], {"qa": {"repair": {"method": "reg:fixy"}}})
        self.assertEqual(choices["reg:fixy"]["registry"]["manifest_sha256"], tool.digest)
        if np is None:
            self.skipTest("needs numpy and tifffile for the stand-in's tifxyz")
        trace, run_dir = self.trace(), self.tmp / "ap" / "repaired" / "t00.fixy"
        (run_dir / "stale").mkdir(parents=True)
        res, code, out = toolreg.exec_repair(tool, trace, run_dir, str(self.src), seed=[1, 2, 3], sha=tool.digest,
                                             root=self.tmp)
        self.assertEqual(code, toolreg.EXIT_OK, res.get("warnings"))
        self.assertEqual(out, run_dir / "seg")
        self.assertFalse((run_dir / "stale").exists())                    # the run folder is made fresh
        seed = json.loads((run_dir / "registry-run.json").read_text())["inputs"]["seed"]["value"]
        self.assertEqual(seed, [1.0, 2.0, 3.0])
        self.assertEqual([g["verdict"] for g in res["format_gate"]], ["pass"])
        self.assertEqual(json.loads((trace / "meta.json").read_text())["uuid"], "trace")
        bad = self.add(self.repair_manifest("badseg"))
        res, code, out = toolreg.exec_repair(bad, trace, self.tmp / "ap" / "bad", str(self.src), root=self.tmp)
        self.assertEqual((code, out), (toolreg.EXIT_REFUSED, None))      # a copy that fails the gate is not handed on
        with self.assertRaisesRegex(toolreg.RegistryError, "changed after the plan"):
            toolreg.exec_repair(tool, trace, run_dir, str(self.src), sha="0" * 64, root=self.tmp)
        with self.assertRaisesRegex(toolreg.RegistryError, "not a repair backend"):
            toolreg.exec_repair(self.add(manifest()), trace, run_dir, str(self.src), root=self.tmp)


class PluginHostTest(Base):
    @needs_registry
    def test_committed_plugin_manifests_are_current_and_parse_in_the_host(self):
        plugins = ROOT / toolreg.PLUGINS_REL
        self.assertEqual(toolreg.export_vc3d(plugins, toolreg.load(ROOT, {}), root=ROOT, check_only=True), [])
        found, problems = host.scan([plugins])
        self.assertEqual(problems, [])
        self.assertIn("scrolls.auc", found)
        self.assertIn("mesh_b={input:mesh_b}", found["scrolls.overlap"]["doc"]["args"])   # a bridge-bound input
        self.assertEqual(found["scrolls.inkfilter"]["doc"]["result"]["kind"], "ink_overlay")
        self.assertEqual(found["scrolls.take-points"]["doc"]["result"]["kind"], "points")
        auc = found["scrolls.auc"]
        ok, why = host.enabled(auc, {"segment": "/s"})
        self.assertFalse(ok)
        self.assertIn("a selected ink detection overlay", why)
        self.assertTrue(host.enabled(auc, {"segment": "/s", "ink_overlay": "/s/m.tif"})[0])
        self.assertTrue(os.access(plugins / "bin" / toolreg.LAUNCHER, os.X_OK))

    @needs_registry
    def test_export_writes_removes_stale_and_checks(self):
        dest = self.tmp / "plugins"
        files = toolreg.export_vc3d(dest, toolreg.load(ROOT, {}), root=ROOT)
        self.assertIn("bin/scrolls-tool", files)
        (dest / "scrolls.gone.json").write_text("{}")
        self.assertIn("scrolls.gone.json", toolreg.export_vc3d(dest, toolreg.load(ROOT, {}), root=ROOT,
                                                               check_only=True))
        toolreg.export_vc3d(dest, toolreg.load(ROOT, {}), root=ROOT)
        self.assertFalse((dest / "scrolls.gone.json").exists())
        self.assertIn(repr(str(toolreg.KIT_ROOT)), (dest / "bin" / "scrolls-tool").read_text())

    @needs_registry
    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_vc3d_starts_a_tool_through_the_launcher_and_loads_its_result(self):
        seg = self.tmp / "seg"
        seg.mkdir()
        (seg / "meta.json").write_text(json.dumps({"type": "seg", "uuid": "s", "format": "tifxyz"}))
        y = np.arange(200)[:, None] * np.ones((1, 300))
        tifffile.imwrite(seg / "map.tif", (0.5 + 0.4 * np.sin(2 * np.pi * y / 40)).astype(np.float32))
        tifffile.imwrite(seg / "map_reverse.tif", np.full((200, 300), 0.5, np.float32))
        vol = self.tmp / "vol.zarr"
        vol.mkdir()
        (vol / "meta.json").write_text(json.dumps({"voxelsize": 7.91}))
        found, _ = host.scan([ROOT / toolreg.PLUGINS_REL])
        out = host.run(found["scrolls.rowscore"], {"segment": str(seg), "ink_overlay": str(seg / "map.tif"),
                                                   "volume": str(vol), "output": str(self.tmp / "vc3d-run"),
                                                   "inputs": {"voxel_um": "auto"}})
        self.assertEqual(out["exit"], 0, out["stderr"])
        self.assertEqual(out["loaded"]["kind"], "file")
        res = json.loads((self.tmp / "vc3d-run" / "vc3d-result.json").read_text())
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["controls"]["verdict"], "present")
        self.assertIn("--reverse", res["argv"])
        self.assertEqual(res["argv"][res["argv"].index("--voxel-um") + 1], "7.91")


class FormatGateTest(Base):
    def seg_tool(self, mode):
        return self.add(manifest(f"seg-{mode}", mode=mode, outputs={
            "seg": {"kind": "surface", "format": "tifxyz", "path": "{run}/seg"}}))

    def test_a_segment_folder_without_meta_fails_the_gate_and_nothing_opens(self):
        res, code = self.go(self.seg_tool("nometa"))
        self.assertEqual(code, toolreg.EXIT_REFUSED)
        self.assertEqual(res["refused_by"], ["format-gate"])
        self.assertEqual(res["open"], [])
        self.assertIn("meta.json", res["format_gate"][0]["detail"])

    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_z_at_or_below_zero_without_the_missing_mark_fails(self):
        res, code = self.go(self.seg_tool("badseg"))
        self.assertEqual(code, toolreg.EXIT_REFUSED, res)
        self.assertIn("z <= 0", res["format_gate"][0]["detail"])
        res, code = self.go(self.seg_tool("goodseg"))
        self.assertEqual(code, toolreg.EXIT_OK, res)
        self.assertEqual(res["format_gate"][0]["verdict"], "pass")
        self.assertEqual(toolreg.plugin_result(self.seg_tool("goodseg"))["kind"], "file")

    def test_points_that_are_not_three_finite_numbers_fail(self):
        tool = self.add(manifest("badpts", mode="badpoints", outputs={
            "pts": {"kind": "points", "format": "json-points", "path": "{run}/points.json"}}))
        res, code = self.go(tool)
        self.assertEqual(code, toolreg.EXIT_REFUSED)
        self.assertIn("1 of 2 points", res["format_gate"][0]["detail"])
        with self.assertRaises(toolreg.RegistryError):
            toolreg.open_run(res["run"])

    def test_check_false_turns_the_gate_off_for_that_output(self):
        tool = self.add(manifest("unchecked", mode="badpoints", outputs={
            "pts": {"kind": "points", "format": "json-points", "path": "{run}/points.json", "check": False}}))
        res, code = self.go(tool)
        self.assertEqual(res["format_gate"], [])

    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_an_overlay_must_fit_the_segment_canvas(self):
        tool = self.add(manifest("maps", mode="map", outputs={
            "fwd": {"kind": "overlay", "format": "tiff-float32", "path": "{run}/m.tif", "role": "forward"},
            "rev": {"kind": "overlay", "format": "tiff-float32", "path": "{run}/m_reverse.tif",
                    "role": "control:reverse"}},
            run={"argv": ["fake-tool", "map", "{in.src}", "{run}/m"]},
            safety={"model_output": True, "paid_compute": "never", "network": "none", "controls": ["rev"]}))
        for rows, cols, want in ((10, 20, toolreg.EXIT_OK), (20, 20, toolreg.EXIT_REFUSED)):
            seg = self.tmp / f"seg{rows}x{cols}"
            seg.mkdir()
            (seg / "meta.json").write_text(json.dumps({"type": "seg", "format": "tifxyz", "scale": [0.5, 0.5]}))
            tifffile.imwrite(seg / "x.tif", np.ones((rows, cols), np.float32))
            res, code = toolreg.run(tool, toolreg.prepare(tool, toolreg.selection_from(segment=str(seg)),
                                                          {"src": str(self.src)}, kind="public"),
                                    run_dir=self.tmp / "run" / f"maps{rows}", root=self.tmp)
            self.assertEqual(code, want, res.get("format_gate"))


class ConvertTest(Base):
    def test_a_declared_converter_runs_in_the_run_folder_and_is_a_stage(self):
        conv = manifest("to-collection", mode="conv", kind="converter", outputs={
            "doc": {"kind": "points", "format": "vc3d-point-collection", "path": "{run}/collection.json"}})
        self.add(conv)
        tool = self.add(manifest("pts", mode="points", outputs={
            "pts": {"kind": "points", "format": "json-points", "path": "{run}/points.json",
                    "convert": "to-collection"}}, vc3d={"menu": "tools", "result": "pts"}))
        reg = self.registry()
        job = toolreg.prepare(tool, toolreg.selection_from(), {"src": str(self.src)}, kind="public")
        res, code = toolreg.run(tool, job, run_dir=self.tmp / "run" / "pts", root=self.tmp, registry=reg)
        self.assertEqual(code, toolreg.EXIT_OK, res)
        self.assertEqual(res["conversions"][0]["converter"], "to-collection")
        self.assertTrue(res["outputs"][0]["path"].endswith("convert/pts/collection.json"))
        self.assertEqual(res["format_gate"][0]["format"], "vc3d-point-collection")   # checked as converted
        graph = json.loads((self.tmp / "run" / "pts" / "graph.json").read_text())
        self.assertIn("stage:convert:pts", [n["id"] for n in graph["nodes"]])
        self.assertEqual(toolreg.plugin_result(tool, reg),
                         {"kind": "points", "path": "{output}/convert/pts/collection.json"})
        self.assertIn("never reaches a menu", " ".join(toolreg.validate_manifest(dict(conv, vc3d={"menu": "tools"}))))


class PlanConfirmTest(Base):
    def test_a_written_plan_runs_only_with_the_same_digest(self):
        tool = self.add(manifest())
        job = toolreg.prepare(tool, toolreg.selection_from(), {"src": str(self.src)}, kind="public")
        plan = toolreg.write_plan(tool, job, self.tmp / "plans" / "p.json", {"src": str(self.src)})
        self.assertEqual(plan["would"], "run")
        self.assertFalse((self.tmp / "run").exists())                       # a plan runs nothing
        res, code = toolreg.confirm(self.registry(), plan["plan_digest"][:12], self.tmp / "plans" / "p.json",
                                    run_dir=self.tmp / "run" / "c1", root=self.tmp, kind="public")
        self.assertEqual(code, toolreg.EXIT_OK, res)
        self.assertEqual(res["confirmed_plan"]["digest"], plan["plan_digest"])
        os.utime(self.src, ns=(1, 1))                                        # the input changed after the plan
        res, code = toolreg.confirm(self.registry(), plan["plan_digest"][:12], self.tmp / "plans" / "p.json",
                                    run_dir=self.tmp / "run" / "c2", root=self.tmp, kind="public")
        self.assertEqual(code, toolreg.EXIT_REFUSED)
        self.assertIn("changed since the plan", res["error"])
        with self.assertRaises(toolreg.RegistryError):
            toolreg.find_plan("zz", root=self.tmp)

    def test_plan_entries_for_gated_tools_and_confirm_entries(self):
        argv = {"argv": ["fake-tool", "ok", "{in.seg}", "{run}"]}
        self.add(manifest("dl", inputs={"seg": {"from": "segment"}}, run=argv,
                          safety={"model_output": False, "paid_compute": "never", "network": "download",
                                  "downloads_mb": 300}))
        self.add(manifest("careful", inputs={"seg": {"from": "segment"}}, run=argv,
                          vc3d={"menu": "segment", "confirm": True}))
        got = toolreg.plugin_manifests(self.registry())
        self.assertIn("dl.plan", got)
        self.assertNotIn("dl", got)                                          # a download never gets a run entry
        self.assertIn("--write", got["dl.plan"]["args"])
        self.assertEqual(got["dl.plan"]["result"], {"kind": "file", "path": "{output}/plan.json"})
        self.assertEqual(sorted(k for k in got if k.startswith("careful")), ["careful.confirm", "careful.plan"])
        self.assertIn("{input:digest}", got["careful.confirm"]["args"])
        dest = self.tmp / "plugins"
        toolreg.export_vc3d(dest, self.registry(), root=self.tmp)
        found, problems = host.scan([dest])
        self.assertEqual(problems, [])
        self.assertIn("scrolls.careful.confirm", found)

    def test_plan_write_exits_0_for_vc3d(self):
        tool = self.add(manifest("p", inputs={"seg": {"from": "segment"}}, run={
            "argv": ["fake-tool", "ok", "{in.seg}", "{run}"]}))
        out = self.tmp / "vc3d-run"
        out.mkdir()
        (out / "plugin-run.json").write_text("{}")                          # VC3D writes it before the program
        seg = self.tmp / "segp"
        seg.mkdir()
        with mock.patch.dict(os.environ, {toolreg.ENV_PATH: str(self.reg_dir)}):
            with contextlib.redirect_stdout(io.StringIO()):
                code = toolreg.main(["plan", "p", "--segment", str(seg), "--write", str(out / "plan.json")])
            self.assertEqual(code, toolreg.EXIT_OK)
            doc = json.loads((out / "plan.json").read_text())
            self.assertEqual(doc["schema"], toolreg.PLAN_SCHEMA)
            out2 = self.tmp / "vc3d-run2"
            out2.mkdir()
            (out2 / "plugin-run.json").write_text("{}")
            with contextlib.redirect_stdout(io.StringIO()):
                code = toolreg.main(["run", "p", "--segment", str(seg), "--out", str(out2)])
            self.assertEqual(code, toolreg.EXIT_OK)                          # plugin-run.json does not count


class BridgeTest(Base):
    def test_the_launcher_finds_only_its_parent_vc3d(self):
        home = self.tmp / "home"
        reg = home / ".vc3d" / "agent_bridge"
        reg.mkdir(parents=True)
        sock = self.tmp / "mine.sock"
        sock.write_text("")
        other = self.tmp / "other.sock"
        other.write_text("")
        (reg / "4242.json").write_text(json.dumps({"pid": 4242, "name": "mine", "path": str(sock)}))
        (reg / "9999.json").write_text(json.dumps({"pid": 9999, "name": "newest", "path": str(other),
                                                   "startedAt": 9e15}))
        self.assertEqual(toolreg.parent_bridge(4242, {"HOME": str(home)})["path"], str(sock))
        self.assertIsNone(toolreg.parent_bridge(1234, {"HOME": str(home)}))       # never the newest bridge
        env = {"HOME": str(home), toolreg.ENV_BRIDGE: str(other)}
        self.assertEqual(toolreg.parent_bridge(4242, env)["path"], str(other))
        seen = []
        with mock.patch.object(toolreg, "main", lambda argv: seen.append(argv) or 0):
            toolreg.launch(["run", "auc", "--out", "x"], {"HOME": str(home)}, 4242)
            toolreg.launch(["take", "file", "--out", "x"], {"HOME": str(home)}, 4242)
        self.assertEqual(seen[0][-2:], ["--bridge-path", str(sock)])
        self.assertNotIn("--bridge-path", seen[1])

    def test_bridge_bound_inputs_resolve_from_the_frozen_selection(self):
        segs = {}
        for sid in ("inner", "outer"):
            d = self.tmp / sid
            d.mkdir()
            (d / "meta.json").write_text(json.dumps({"uuid": sid}))
            (d / "map.tif").write_text("m")
            (d / "ink-detections.json").write_text(json.dumps([{"local_file": "map.tif", "label": "ink v1"}]))
            segs[sid] = str(d)
        app = host.App(state={"volume": {"id": "v", "voxelSize": 7.91}, "activeSurface": {"id": "inner"}},
                       segments=[{"id": k, "path": v} for k, v in segs.items()])
        sel = toolreg.enrich_from_bridge(toolreg.selection_from(), "sock", call=app.call)
        self.assertEqual([m for m, _ in app.calls], ["state.get", "segments.list"])   # read-only calls
        self.assertEqual(sel["segment"]["id"], "inner")
        self.assertEqual(sel["volume"]["voxel_um"], 7.91)
        tool = self.add(manifest("two", inputs={"segs": {"from": "segments", "bind": "bridge"},
                                                "m": {"from": "path", "bind": "bridge", "format": ["tiff"]}},
                                 run={"argv": ["fake-tool", "ok", "{in.m}", "{run}"]}))
        values, record = toolreg.bind(tool, sel, {"segs": "inner,outer", "m": "ink v1"})
        self.assertEqual(values["in.segs"], [segs["inner"], segs["outer"]])
        self.assertEqual(record["m"]["from"], "bridge")
        with self.assertRaises(toolreg.BindError) as cm:
            toolreg.bind(tool, toolreg.selection_from(), {"segs": "inner", "m": "ink v1"})
        self.assertIn("--agent-bridge", str(cm.exception))
        with self.assertRaises(toolreg.BindError):
            toolreg.bind(tool, sel, {"segs": "nope", "m": "ink v1"})
        vol = self.tmp / "vol.zarr"
        vol.mkdir()
        other = host.App(state={"volume": {"path": str(self.tmp)}})
        with self.assertRaises(toolreg.RegistryError):
            toolreg.enrich_from_bridge(toolreg.selection_from(volume=str(vol)), "sock", call=other.call)

    def test_a_zyx_tool_gets_the_point_reversed(self):
        tool = self.add(manifest("zyx", inputs={"p": {"from": "point", "axis_order": "zyx"}},
                                 run={"argv": ["fake-tool", "ok", "{in.p}", "{run}"]}))
        values, _ = toolreg.bind(tool, toolreg.selection_from(point="1,2,3"))
        self.assertEqual(values["in.p"], "3.0,2.0,1.0")
        self.assertEqual(values["in.p.x"], "1.0")


class TakeAndQuotaTest(Base):
    def test_take_copies_a_checked_output_and_refuses_a_changed_one(self):
        tool = self.add(manifest("pts", mode="points", outputs={
            "pts": {"kind": "points", "format": "json-points", "path": "{run}/points.json"}}))
        res, code = self.go(tool)
        self.assertEqual(code, toolreg.EXIT_OK, res)
        doc = toolreg.take("points", self.tmp / "vc3d-out", res["run"])
        coll = json.loads((self.tmp / "vc3d-out" / "points.json").read_text())
        self.assertEqual(coll["vc_pointcollections_json_version"], "1")
        self.assertEqual(doc["output"], "pts")
        with self.assertRaises(toolreg.RegistryError):
            toolreg.take("segment", self.tmp / "vc3d-out2", res["run"])           # nothing loads as a segment
        Path(res["run"], "points.json").write_text("[[9, 9, 9]]")
        with self.assertRaises(toolreg.RegistryError):
            toolreg.take("points", self.tmp / "vc3d-out3", res["run"])

    def test_quota_tools_are_refused(self):
        tool = self.add(manifest("q", safety={"model_output": False, "paid_compute": "never",
                                              "network": "public-read", "quota": "anthropic-api"}))
        res, code = self.go(tool)
        self.assertEqual(code, toolreg.EXIT_REFUSED)
        self.assertIn("quota", res["refused_by"])
        bad = manifest("q2", safety={"model_output": False, "paid_compute": "never", "network": "none",
                                     "quota": "zerogpu"}, facts={"go_ahead": False})
        self.assertIn("needs a yes", " ".join(toolreg.validate_manifest(bad)))


class AdapterTest(Base):
    """The adapters of inkfilter, auc and Ink Lens (and the engine pieces they need): VC3D starts them from its
    selection through the committed plugin files, their outputs come back into VC3D on the segment's canvas, and the
    AutoPipeline door lists the ink tools."""

    def grid_segment(self, name="w00"):
        seg = self.tmp / name
        seg.mkdir()
        rows, cols = np.mgrid[0:20, 0:30].astype(np.float32)
        tifffile.imwrite(seg / "x.tif", cols * 4)
        tifffile.imwrite(seg / "y.tif", rows * 4)
        tifffile.imwrite(seg / "z.tif", np.full((20, 30), 100, np.float32))
        (seg / "meta.json").write_text(json.dumps({"type": "seg", "uuid": name, "format": "tifxyz",
                                                   "scale": [0.5, 0.5]}))       # a 40 x 60 canvas
        (seg / "layers").mkdir()
        tifffile.imwrite(seg / "layers" / "00.tif", np.zeros((40, 60), np.uint8))
        return seg

    def launch(self, plugin, ctx):
        """VC3D's plugin host, in this process (so the mocked disk check holds): expand the entry's arguments as the
        host does, write its plugin-run.json, run the launcher's action, load the declared result."""
        out = Path(ctx["output"])
        out.mkdir(parents=True, exist_ok=True)
        args, rpath = host.expand(plugin, ctx)
        (out / "plugin-run.json").write_text("{}")
        with contextlib.redirect_stdout(io.StringIO()):
            code = toolreg.launch(args, {"HOME": str(self.tmp / "home")}, 1)
        loaded = host.load_result(plugin["doc"]["result"]["kind"], rpath) if Path(rpath).exists() else None
        return code, loaded

    @needs_registry
    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_inkfilter_from_vc3d_whole_and_region_then_its_control_back(self):
        fake = self.bin / "scrolls-inkfilter"
        fake.write_text(FAKE_INKFILTER.format(py=sys.executable))
        fake.chmod(0o755)
        seg = self.grid_segment()
        found, problems = host.scan([ROOT / toolreg.PLUGINS_REL])
        self.assertEqual(problems, [])
        code, loaded = self.launch(found["scrolls.inkfilter"], {"segment": str(seg), "output": str(self.tmp / "r1")})
        self.assertEqual(code, toolreg.EXIT_OK)
        self.assertEqual((loaded["shape"], loaded["dtype"]), ([40, 60], "uint8"))
        # the region entry is enabled only with a focus region; its crop map is placed at its box on the canvas
        self.assertFalse(host.enabled(found["scrolls.inkfilter.region"], {"segment": str(seg)})[0])
        code, loaded = self.launch(found["scrolls.inkfilter.region"], {"segment": str(seg), "region":
                                                                       [8, 4, 0, 20, 12, 200],
                                                                       "output": str(self.tmp / "r2")})
        self.assertEqual(code, toolreg.EXIT_OK)
        res = json.loads((self.tmp / "r2" / "vc3d-result.json").read_text())
        self.assertIn("--crop", res["argv"])
        self.assertEqual(res["argv"][res["argv"].index("--crop") + 1:][:4], ["2", "8", "4", "12"])
        view = tifffile.imread(loaded["path"])
        self.assertEqual(view.shape, (40, 60))
        self.assertGreater(int(view[2:8, 4:12].max()), 200)
        self.assertEqual(int(view[:2].max()), 0)
        self.assertEqual(int(view[:, 12:].max()), 0)
        scale = json.loads((self.tmp / "r2" / "vc3d" / "scale.json").read_text())
        self.assertEqual(scale["placed"], {"box": [2, 8, 4, 12], "canvas": [40, 60]})
        # the reverse-depth control comes back through "Open run output as ink overlay": placed, on the same scale
        doc = toolreg.take("ink_overlay", self.tmp / "r3", run=self.tmp / "r2", output="reverse")
        rev = tifffile.imread(doc["path"])
        self.assertEqual(rev.shape, (40, 60))
        self.assertEqual(int(rev[:2].max()), 0)
        inside = rev[2:8, 4:12]
        self.assertLessEqual(int(inside.max()) - int(inside.min()), 1)       # a flat control stays flat
        with open(scale["sha256"] and res["views"]["reverse"], "ab") as fh:
            fh.write(b"0")
        with self.assertRaisesRegex(toolreg.RegistryError, "changed after its run"):
            toolreg.take("ink_overlay", self.tmp / "r4", run=self.tmp / "r2", output="reverse")

    @needs_registry
    def test_inkfilter_is_an_autopipeline_ink_backend(self):
        reg = toolreg.load(ROOT, {})
        self.assertIn("reg:inkfilter", toolreg.stage_choices("ink", reg))
        cmd = toolreg.ink_models(reg)["reg:inkfilter"]["command"]
        self.assertEqual(cmd[-4:], ["--", "{input}", "{output}", "{reverse}"])

    def test_records_pair_controls_and_name_labels(self):
        seg = self.tmp / "s1"
        (seg / "ink").mkdir(parents=True)
        (seg / "labels").mkdir()
        (seg / "meta.json").write_text(json.dumps({"type": "seg", "uuid": "s1", "format": "tifxyz"}))
        for f in ("ink/ink_9um-seed42-f.tif", "ink/ink_9um-seed42-r.tif", "ink/ink_9um-seed42-s.tif",
                  "ink/reader-v2-r.tif"):
            (seg / f).write_bytes(b"x")
        for d in ("labels/mine_inklabels.zarr", "labels/mine_mask.zarr", "s1_inklabels.zarr",
                  "s1_supervision_mask.zarr"):
            (seg / d).mkdir()

        def rec(f, label, model=None, **kw):
            r = {"local_file": f, "label": label, "segment_id": "s1", "artifact_type": "ink detection", **kw}
            if model:
                r["kit_villafmt"] = {"model": model, "variant": f[-5]}
            return r
        records = [rec("ink/reader-v2-r.tif", "reader-v2 reverse-depth control", "reader-v2"),
                   rec("ink/ink_9um-seed42-f.tif", "ink_9um-seed42 forward", "ink_9um-seed42"),
                   rec("ink/ink_9um-seed42-r.tif", "ink_9um-seed42 reverse-depth control", "ink_9um-seed42"),
                   rec("ink/ink_9um-seed42-s.tif", "ink_9um-seed42 depth-shuffled control", "ink_9um-seed42"),
                   dict(rec("labels/mine_inklabels.zarr", "labels"), artifact_type="ink-labels"),
                   dict(rec("labels/mine_mask.zarr", "mask"), artifact_type="supervision")]
        (seg / "catalog-origin.json").write_text(json.dumps({"ink_detections": records}))
        sel = toolreg.selection_from(segment=str(seg))      # VC3D's fallback: catalog-origin.json, no ink-detections
        roles = {Path(o["path"]).name: o["role"] for o in sel["segment"]["overlays"]}
        self.assertEqual(roles["ink_9um-seed42-s.tif"], "control:shuffle")
        self.assertEqual(roles["mine_inklabels.zarr"], "labels")
        fwd = str(seg / "ink" / "ink_9um-seed42-f.tif")
        self.assertEqual(Path(toolreg._twin(fwd, sel)).name, "ink_9um-seed42-r.tif")     # its own model's, not another
        tool = self.add(manifest("scorer", inputs={
            "prediction": {"from": "segment.overlay", "role": "forward"},
            "control": {"from": "segment.overlay.reverse", "pair_of": "prediction", "required": False},
            "labels": {"from": "segment.labels", "format": ["zarr"]},
            "mask": {"from": "segment.mask", "format": ["zarr"]}},
            run={"argv": ["fake-tool", "ok", "{in.prediction}", "{run}"]}))
        values, _ = toolreg.bind(tool, toolreg.selection_from(segment=str(seg), ink_overlay=fwd))
        self.assertEqual(Path(values["in.labels"]).name, "mine_inklabels.zarr")       # records before villa's names
        self.assertEqual(Path(values["in.mask"]).name, "mine_mask.zarr")
        (seg / "ink-detections.json").write_text("[]")          # an empty file: VC3D still reads the catalog list
        self.assertEqual(len(toolreg.selection_from(segment=str(seg))["segment"]["overlays"]), 6)
        (seg / "catalog-origin.json").unlink()
        values, _ = toolreg.bind(tool, toolreg.selection_from(segment=str(seg), ink_overlay=fwd))
        self.assertEqual(Path(values["in.labels"]).name, "s1_inklabels.zarr")         # then villa's names
        # ink.py's own names, with no record: ink_f's twin is ink_r beside it
        run = self.tmp / "inkrun"
        run.mkdir()
        for f in ("ink_f.npy", "ink_r.npy"):
            (run / f).write_bytes(b"x")
        self.assertEqual(Path(toolreg._twin(str(run / "ink_f.npy"), toolreg.selection_from())).name, "ink_r.npy")

    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_8_bit_maps_keep_their_values_in_vc3d(self):
        m = manifest(run={"argv": ["fake-tool", "u8map", "{in.src}", "{run}/map"]},
                     outputs={"map": {"kind": "overlay", "format": "tiff-uint8", "path": "{run}/map.tif",
                                      "role": "forward"},
                              "map_reverse": {"kind": "overlay", "format": "tiff-uint8",
                                              "path": "{run}/map_reverse.tif", "role": "control:reverse"}},
                     safety={"model_output": True, "controls": ["map_reverse"], "paid_compute": "never",
                             "network": "none"}, vc3d={"menu": "segment", "result": "map"})
        tool = self.add(m)
        res, code = self.go(tool)
        self.assertEqual(code, 0, res)
        view = tifffile.imread(res["views"]["map"])
        self.assertEqual(int(view.max()), 200)          # not stretched to 255
        self.assertEqual(toolreg.plugin_result(tool)["path"], "{output}/vc3d/views/map_u8.tif")

    @needs_registry
    def test_region_entries_and_the_auc_window(self):
        plugins = toolreg.plugin_manifests(toolreg.load(ROOT, {}))
        self.assertIn("--region", plugins["auc.region"]["args"])
        self.assertNotIn("--region", plugins["auc"]["args"])
        self.assertIn("--region", plugins["ink-lens"]["args"])          # Ink Lens needs one: no whole-segment entry
        self.assertNotIn("ink-lens.region", plugins)
        from kit import auc
        cut, on_map = auc._window_cut((2, 8, 4, 12), None, None, (20, 30), (40, 60))
        self.assertEqual(on_map, [1, 4, 2, 6])
        self.assertEqual(auc._window_cut((2, 8, 4, 12), None, None, (40, 60), (0, 0))[1], [2, 8, 4, 12])
        with self.assertRaises(Exception):
            auc._window_cut((2, 8, 4, 12), (0, 1, 0, 1), None, (40, 60))

    @needs_registry
    @unittest.skipIf(np is None, "needs numpy and tifffile")
    def test_ink_lens_binds_from_vc3d_in_local_offline_mode_into_its_run_folder(self):
        seg = self.grid_segment()
        vol = self.tmp / "scan.zarr"
        vol.mkdir()
        (vol / "meta.json").write_text(json.dumps({"voxelsize": 7.91}))
        tool = toolreg.load(ROOT, {}).get("ink-lens")
        self.assertEqual(toolreg.vc3d_entries(tool), ["run"])
        sel = toolreg.selection_from(segment=str(seg), volume=str(vol), region="8,4,0,20,12,200")
        job = toolreg.prepare(tool, sel, None, {"voxel_um": "auto"}, kind="public", root=self.tmp)
        job.run = self.tmp / "lens-run"
        argv = job.argv()
        self.assertEqual(argv[argv.index("--crop") + 1:][:4], ["2", "8", "4", "12"])
        self.assertEqual(argv[argv.index("--um-per-px") + 1], "7.91")
        for flag in ("--local", "--offline", "--out"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--device") + 1], "cpu")
        self.assertNotIn("--space", argv)
        from kit import inklens
        run_parser = inklens.load().parser()._subparsers._group_actions[0].choices["run"]
        known = {o for act in run_parser._actions for o in act.option_strings}
        self.assertLessEqual({w for w in argv if w.startswith("--")}, known)
        self.assertEqual([o for o in tool.outputs if tool.outputs[o]["path"].startswith("{run}/")],
                         list(tool.outputs))

    def test_existing_may_name_a_param_whose_values_are_the_backends(self):
        m = manifest("anyink", params={"model": {"type": "string", "enum": ["m1", "m2"], "default": "m1"}},
                     pipeline={"stage": "ink", "existing": "{param.model}"})
        tool = self.add(m)
        self.assertEqual(toolreg.existing_backends(tool), ["m1", "m2"])
        choices = toolreg.stage_choices("ink", self.registry())
        self.assertEqual(choices["m2"]["registry"]["id"], "anyink")
        self.assertTrue(toolreg.validate_manifest(dict(m, pipeline={"stage": "ink", "existing": "{param.nope}"})))


class CliTest(Base):
    def capture(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(argv)
        return code, buf.getvalue()

    @needs_registry
    def test_list_show_plan_and_errors(self):
        code, out = self.capture(["tools", "list", "--json"])
        self.assertEqual(code, 0)
        ids = [t["id"] for t in json.loads(out)["tools"]]
        self.assertIn("auc", ids)
        code, out = self.capture(["tools", "list", "--door", "native", "--json"])
        self.assertEqual({t["id"] for t in json.loads(out)["tools"]} - {"villa-flatten", "villa-gen-umbilicus",
                                                                       "villa-grow-seg-from-seed",
                                                                       "villa-render-tifxyz"}, set())
        code, out = self.capture(["tools", "show", "auc"])
        self.assertEqual(json.loads(out)["id"], "auc")
        code, out = self.capture(["tools", "plan", "doctor", "--json"])
        self.assertEqual(code, toolreg.EXIT_PLANNED)
        self.assertEqual(json.loads(out)["argv"][:4], [sys.executable, "-m", "kit", "doctor"])
        code, _ = self.capture(["tools", "plan", "auc", "--json"])
        self.assertEqual(code, toolreg.EXIT_BAD)
        code, _ = self.capture(["tools", "show", "nope"])
        self.assertEqual(code, toolreg.EXIT_BAD)
        code, _ = self.capture(["tools", "exec", "auc", "--", "a", "b"])
        self.assertEqual(code, toolreg.EXIT_BAD)

    @needs_registry
    def test_list_with_a_selection_says_what_is_missing(self):
        code, out = self.capture(["tools", "list", "--door", "vc3d", "--segment", str(self.tmp), "--json"])
        rows = {r["id"]: r for r in json.loads(out)["tools"]}
        self.assertTrue(rows["doctor"]["enabled"])
        self.assertFalse(rows["auc"]["enabled"])
        self.assertIn("ink", rows["auc"]["missing"])

    def test_check_passes_on_the_repository(self):
        code, out = self.capture(["tools", "check", "--json"])
        self.assertEqual(json.loads(out), {"ok": True, "problems": []})
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
