"""kit.scroll2ink: the stage chain against a stand-in Headless VC3D that records every call."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from kit import scroll2ink

ROOT = Path(__file__).resolve().parents[1]

# A stand-in for `vc3d-agent`: `vc3d call TOOL JSON` appends the call to $FAKE_LOG and answers like the real tool.
# $FAKE_MODE changes one answer: badseed, badcheck, badextend, noextend, inkfail, inward.
FAKE = textwrap.dedent('''
    import json, os, sys
    from pathlib import Path
    _, _, tool, args = sys.argv[1:5]
    a = json.loads(args)
    mode = os.environ.get("FAKE_MODE", "")
    with open(os.environ["FAKE_LOG"], "a") as fh:
        fh.write(json.dumps({"tool": tool, "args": a}) + "\\n")
    B = "https://bucket/PHerc0139/"
    def surf(path, area):
        Path(path).mkdir(parents=True, exist_ok=True)
        for n in ("x.tif", "y.tif", "z.tif", "meta.json"):
            (Path(path) / n).write_text("0")
        return {"path": path, "area_cm2": area}
    def out(d, rc=0):
        print(json.dumps(d)); sys.exit(rc)
    if tool == "catalog" and a["action"] == "transforms":
        # 222 to 111 only: the umbilicus of 111 needs the inverse; x is doubled and shifted, y and z kept
        out({"sample": a["sample"], "transforms": [
            {"from": "222", "to": "111", "matrix_xyz": [[2, 0, 0, 10], [0, 1, 0, 0], [0, 0, 1, 0]]}]})
    if tool == "catalog":
        out({"sample": a["sample"], "volumes": [
            {"volume": "111", "long_id": "111-2.4um.zarr", "voxel_um": 2.4, "url": B + "111/",
             "umbilicus": [{"url": os.environ["FAKE_UMB"]}]},
            {"volume": "222", "long_id": "222-9.362um.zarr", "voxel_um": 9.362, "url": B + "222/",
             "license": "CC BY-NC 4.0",
             "surface_prediction_zarr": [{"url": B + "recto.zarr/", "model": "1"}, {"url": B + "m7.zarr/", "model": "7"}],
             "normal_grids": [{"url": B + "m7.normal-grids/", "model": "7"}]}]})
    if tool == "seed_check":
        ok = mode != "badseed"
        out({"ok": ok, "value": 255 if ok else 0, "nearest_on": [1, 2, 3], "nearest_distance": 4.0,
             "ct": {"verdict": "papyrus" if ok else "air"}, "horizon": {"class": "HEALTHY"}})
    if tool == "trace":
        p = os.path.join(a["out"], a["name"])
        out({"exit": 0, "surfaces": [surf(p, 2.5)], "stop": {"reason": "generations"}, "log": "t.log"})
    if tool == "check_surface":
        bad = (mode == "badcheck") or (mode == "badextend" and "extend" in a["surface"])
        if mode == "inward":
            out({"verdict": "look closer", "findings": ["orientation: +N points toward the center (standard)"],
                 "orientation": {"normal": {"vote": "inward"}}, "seating": {"verdict": "seated"}})
        out({"verdict": "look closer" if bad else "ok", "findings": ["seating: not seated"] if bad else [],
             "seating": {"verdict": "not seated" if bad else "seated", "seated_windows": "0 of 5" if bad else "5 of 5"},
             "selfcross": {"transverse": 0}})
    if tool == "extend":
        if mode == "noextend":
            out({"error": "vc_extend_edge is not in /opt/bin (build it from the VC3D fork branch)"}, 1)
        out({"exit": 0, "out": a["out"], "surface": surf(a["out"], 6.0), "seconds": 3})
    if tool == "flatten":
        out({"exit": 0, "out": a["out"], "surface": surf(a["out"], 6.1)})
    if tool == "render":
        z = os.path.join(a["out"], "render.zarr"); Path(z).mkdir(parents=True, exist_ok=True)
        out({"zarr": z, "shape": [21, 100, 80], "order": "team (--flip-normals)"})
    if tool == "models":
        out({"models": {}})
    if tool == "fetch_model":
        out({"name": a["name"], "path": "ckpt.pth"})
    if tool == "ink":
        if mode == "inkfail":
            out({"exit": 1, "maps": {}, "log_tail": "CUDA out of memory"}, 1)
        o = a.get("out", "exp")
        out({"exit": 0, "out": o, "device": a["device"], "maps": {"f": {"path": o + "/f.tif"}, "r": {"path": o + "/r.tif"}},
             "comparison": {"r": {"mean_diff": 0.1}}})
    if tool == "preview":
        Path(a["out"]).write_text("png"); out({"png": a["out"]})
    out({"error": "unknown tool " + tool}, 2)
''')


class Scroll2InkTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.fake = self.tmp / "fake_agent.py"
        self.fake.write_text(FAKE)
        self.log = self.tmp / "calls.jsonl"
        self.umb = self.tmp / "111-umbilicus.json"
        self.umb.write_text(json.dumps({"control_points": [{"x": 30, "y": 5, "z": 900, "score": 100},
                                                           {"x": 50, "y": 6, "z": 100, "score": 100}]}))
        self.env = {**os.environ, "FAKE_LOG": str(self.log), "FAKE_MODE": "", "FAKE_UMB": str(self.umb)}

    def kit(self, *args, mode="", out=None):
        env = {**self.env, "FAKE_MODE": mode}
        argv = [sys.executable, "-m", "kit", "scroll2ink", "run", "--sample", "PHerc0139", "--seed", "10", "20", "30",
                "--out", str(out or self.tmp / "run"), "--agent", f"{sys.executable} {self.fake}", *args]
        return subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True)

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def state(self, out=None):
        return json.loads(((out or self.tmp / "run") / "state.json").read_text())["stages"]

    def test_whole_chain(self):
        p = self.kit("--device", "cuda")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        st = self.state()
        self.assertEqual([st[k]["status"] for k in scroll2ink.STAGES], ["done"] * 10)
        tools = [c["tool"] for c in self.calls()]
        self.assertEqual(tools, ["catalog", "catalog", "seed_check", "trace", "check_surface", "extend", "check_surface",
                                 "flatten", "render", "models", "fetch_model", "ink", "preview", "preview", "preview",
                                 "preview"])
        by = {c["tool"]: c["args"] for c in self.calls()}
        # the volume with a prediction that has normal grids, and that prediction (not the first listed)
        self.assertEqual(by["trace"]["volume"], "https://bucket/PHerc0139/m7.zarr/")
        self.assertEqual(by["trace"]["normal_grids"], "https://bucket/PHerc0139/m7.normal-grids/")
        self.assertEqual(by["trace"]["seed"], [10.0, 20.0, 30.0])
        self.assertEqual(by["extend"]["normals"], "https://bucket/PHerc0139/m7.zarr/")
        self.assertTrue(by["flatten"]["surface"].endswith("extend/extended"))
        self.assertEqual(by["render"]["preset"], "9um")
        # the other scan's umbilicus, carried into this scan's frame by the inverted transform, sorted by z
        umb = self.tmp / "run" / "umbilicus.json"
        self.assertEqual(by["render"]["umbilicus"], str(umb))
        self.assertEqual(by["check_surface"]["umbilicus"], str(umb))
        pts = json.loads(umb.read_text())["control_points"]
        self.assertEqual([(p["x"], p["y"], p["z"]) for p in pts], [(20, 6, 100), (10, 5, 900)])
        self.assertIn("111's published umbilicus", self.state()["inputs"]["umbilicus_from"])
        self.assertEqual(by["ink"]["variants"], ["f", "r"])
        self.assertEqual(by["ink"]["purpose"], "benchmark")
        self.assertEqual(by["ink"]["device"], "cuda")
        sm = json.loads((self.tmp / "run" / "summary.json").read_text())
        self.assertEqual(sm["area_cm2"], 6.0)
        self.assertTrue(sm["extension_kept"])
        self.assertIn("model output, not a reading", (self.tmp / "run" / "report.md").read_text())

    def test_split_run_resumes_and_device_may_change(self):
        p = self.kit("--until", "render")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("stopped after render", p.stdout)
        self.assertNotIn("ink", self.state())
        n = len(self.calls())
        p = self.kit("--device", "cuda")
        self.assertEqual(p.returncode, 0, p.stderr)
        later = [c["tool"] for c in self.calls()[n:]]
        self.assertEqual(later[0], "models")              # nothing before ink ran again
        self.assertNotIn("trace", later)
        self.assertEqual(self.state()["ink"]["device"], "cuda")

    def test_changed_settings_refused(self):
        self.assertEqual(self.kit("--until", "seed").returncode, 0)
        p = self.kit("--generations", "50")
        self.assertEqual(p.returncode, 1)
        self.assertIn("other settings (generations)", p.stderr)

    def test_bad_seed_stops_before_trace(self):
        p = self.kit(mode="badseed")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not on the surface prediction", p.stderr)
        self.assertEqual(self.state()["seed"]["status"], "failed")
        self.assertNotIn("trace", [c["tool"] for c in self.calls()])

    def test_failed_check_stops_before_render(self):
        p = self.kit(mode="badcheck")
        self.assertEqual(p.returncode, 1)
        self.assertIn("look closer", p.stderr)
        self.assertNotIn("render", [c["tool"] for c in self.calls()])

    def test_failed_extension_is_dropped(self):
        p = self.kit(mode="badextend")
        self.assertEqual(p.returncode, 0, p.stderr)
        ext = self.state()["extend"]
        self.assertFalse(ext["kept"])
        self.assertTrue(ext["surface"].endswith("trace/trace"))
        flat = [c for c in self.calls() if c["tool"] == "flatten"][0]
        self.assertTrue(flat["args"]["surface"].endswith("trace/trace"))

    def test_no_extend_tool_skips(self):
        p = self.kit(mode="noextend")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.state()["extend"]["status"], "skipped")
        self.assertIn("no vc_extend_edge", self.state()["extend"]["why"])

    def test_ink_failure_is_recorded(self):
        p = self.kit(mode="inkfail")
        self.assertEqual(p.returncode, 1)
        self.assertIn("CUDA out of memory", self.state()["ink"]["error"])

    def test_eligible_scan_needs_an_experiment(self):
        self.assertEqual(scroll2ink.eligible_prizes("PHerc0139"), [])
        self.assertIn("first-letters-2027", scroll2ink.eligible_prizes("PHerc0175"))
        self.assertIn("grand-prize-2027", scroll2ink.eligible_prizes("PHerc. 1447"))
        out = self.tmp / "elig"
        p = subprocess.run([sys.executable, "-m", "kit", "scroll2ink", "run", "--sample", "PHerc1447", "--seed", "1",
                            "2", "3", "--out", str(out), "--agent", f"{sys.executable} {self.fake}"],
                           cwd=ROOT, env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("needs a preregistered experiment", p.stderr)
        self.assertEqual(self.state(out)["render"]["status"], "done")

    def test_status_and_dry_run(self):
        p = self.kit("--dry-run")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["stages"], list(scroll2ink.STAGES))
        self.assertFalse((self.tmp / "run").exists())
        self.kit("--until", "trace")
        p = subprocess.run([sys.executable, "-m", "kit", "scroll2ink", "status", str(self.tmp / "run"), "--json"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["stages"]["trace"], "done")
        p = subprocess.run([sys.executable, "-m", "kit", "scroll2ink", "status", str(self.tmp)], cwd=ROOT,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_missing_agent(self):
        with self.assertRaises(scroll2ink.Scroll2InkError) as cm:
            scroll2ink.agent_command(None, env={"PATH": str(self.tmp)})
        self.assertIn("vc3d-agent", str(cm.exception))
        self.assertEqual(scroll2ink.agent_command(None, env={"SCROLL2INK_AGENT": "a b"}), ["a", "b"])

    def test_inward_normal_goes_on_with_an_umbilicus(self):
        # the render votes the layer order from the same normal, so an inward one is a note, not a stop
        p = self.kit("--until", "render", mode="inward")
        self.assertEqual(p.returncode, 0, p.stderr)
        ch = self.state()["check"]
        self.assertEqual((ch["verdict"], ch["findings"]), ("ok", []))
        self.assertTrue(ch["notes"][0].startswith(scroll2ink.INWARD))
        self.assertEqual(ch["orientation"]["vote"], "inward")
        self.assertIn("umbilicus", [c for c in self.calls() if c["tool"] == "render"][0]["args"])

    def test_given_umbilicus_wins(self):
        p = self.kit("--until", "check", "--umbilicus", "my-umb.txt")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([c["tool"] for c in self.calls()][:2], ["catalog", "seed_check"])
        self.assertEqual(self.state()["inputs"]["umbilicus"], "my-umb.txt")
        self.assertEqual([c for c in self.calls() if c["tool"] == "check_surface"][0]["args"]["umbilicus"],
                         "my-umb.txt")

    def test_umbilicus_helpers(self):
        self.assertEqual(scroll2ink.parse_umbilicus('{"control_points": [{"x": 1, "y": 2, "z": 3, "score": 9}]}'),
                         [(1.0, 2.0, 3.0, 9)])
        self.assertEqual(scroll2ink.parse_umbilicus("# z, y, x\n3, 2, 1\n"), [(1.0, 2.0, 3.0, None)])
        self.assertEqual(scroll2ink.parse_umbilicus("[[3, 2, 1]]"), [(1.0, 2.0, 3.0, None)])
        with self.assertRaises(ValueError):
            scroll2ink.parse_umbilicus("{}")
        m = [[0, -3, 0, 7], [2, 0, 0, -1], [0, 0, 4, 2]]
        inv = scroll2ink.invert_affine(m)
        back = scroll2ink.apply_affine(inv, *scroll2ink.apply_affine(m, 5, -2, 11))
        for a, b in zip(back, (5, -2, 11)):
            self.assertAlmostEqual(a, b)
        with self.assertRaises(ValueError):
            scroll2ink.invert_affine([[1, 0, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0]])
        rows = [{"volume": "A", "umbilicus": [{"url": "a.json"}]}, {"volume": "B"}]
        direct = [{"from": "A", "to": "B", "matrix_xyz": m}]
        self.assertEqual(scroll2ink.map_umbilicus(rows, direct, "B"), ("A", "a.json", m))
        self.assertIsNone(scroll2ink.map_umbilicus(rows, direct, "C"))
        self.assertIsNone(scroll2ink.map_umbilicus(rows, [], "B"))

    def test_pure_helpers(self):
        self.assertEqual(scroll2ink.preset_for(9.362), "9um")
        self.assertEqual(scroll2ink.preset_for(2.4), "2um")
        self.assertEqual(scroll2ink.preset_for(1.1), "1um")
        vols = {"sample": "S", "volumes": [{"volume": "1", "url": "u", "surface_prediction_zarr": [{"url": "p",
                                                                                                    "model": "m"}]}]}
        with self.assertRaises(scroll2ink.Scroll2InkError):
            scroll2ink.pick_volume(vols)
        v, pred, grids = scroll2ink.pick_volume(vols, "1")
        self.assertEqual((pred, grids), ("p", None))
        with self.assertRaises(scroll2ink.Scroll2InkError):
            scroll2ink.pick_volume(vols, "9")


if __name__ == "__main__":
    unittest.main()
