"""Two-way VC3D adapters of the report tools through the tool registry: view, hpscore and doctor (started from
VC3D's selection), and overlap, verify and stackcheck (a second segment, ordered segments or ink detection labels
read through the agent bridge of the VC3D that started the launcher).

Each tool is started the way VC3D's plugin host starts it (tests/fake_vc3d_host.py expands the committed plugin
entry, writes plugin-run.json into the run folder and calls the launcher), its report comes back as the entry's
result file, and its inputs are unchanged. The bridge is a recording stand-in (host.App) that answers only the
read-only calls the selection uses. None of these tools is an AutoPipeline stage, so none opens that door.
Everything is synthetic and local: small maps, labels, tifxyz grids and an Archimedean spiral stack."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, toolreg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_vc3d_host as host  # noqa: E402

try:
    import numpy as np
    import scipy  # noqa: F401
    import tifffile
    import zarr
except ImportError:
    np = tifffile = zarr = None

needs_maps = unittest.skipIf(np is None, "needs numpy, scipy, tifffile and zarr")
# public Scrolls' manifests (auc.json marks them); Scrolls-private keeps only its own manifests
needs_registry = unittest.skipUnless((ROOT / "kit" / "data" / "registry" / "auc.json").is_file(),
                                     "this checkout has no public Scrolls manifests in kit/data/registry")
IDS = ("view", "hpscore", "doctor", "overlap", "verify", "stackcheck")
RESULTS = {"view": "{output}/view.html", "hpscore": "{output}/hpscore.json", "doctor": "{output}/doctor.txt",
           "overlap": "{output}/overlap.json", "verify": "{output}/verify.json",
           "stackcheck": "{output}/stackcheck.json"}


def sha(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="toolreg-reports-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        cfg = self.tmp / "local.json"
        cfg.write_text("{}")
        env = {"SCROLLS_ELECTRICITY_USD_PER_KWH": "0.2", "SCROLLS_LOCAL_CONFIG": str(cfg),
               toolreg.ENV_LEDGER: str(self.tmp / "ledger"), "HOME": str(self.tmp / "home")}
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(toolreg.shutil, "disk_usage", return_value=mock.Mock(free=50e9))):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(toolreg.ENV_BRIDGE, None)
        self.reg = toolreg.load(ROOT, {})

    def plugins(self):
        found, problems = host.scan([ROOT / toolreg.PLUGINS_REL])
        self.assertEqual(problems, [])
        return found

    def launch(self, plugin, ctx, app=None):
        """VC3D's plugin host in this process: expand the committed entry, write plugin-run.json, run the launcher
        (with app as the parent VC3D's agent bridge when given) and load the declared result; returns (exit code,
        what VC3D loaded, vc3d-result.json)."""
        out = Path(ctx["output"])
        out.mkdir(parents=True, exist_ok=True)
        args, rpath = host.expand(plugin, ctx)
        (out / "plugin-run.json").write_text("{}")
        env = {"HOME": str(self.tmp / "nohome")}
        patches = []
        if app is not None:
            sock = self.tmp / "vc3d-bridge.sock"
            sock.write_text("")
            env[toolreg.ENV_BRIDGE] = str(sock)
            patches.append(mock.patch.object(toolreg, "_rpc", app.call))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = toolreg.launch(args, env, 1)
        loaded = host.load_result(plugin["doc"]["result"]["kind"], rpath) if code == 0 and Path(rpath).exists() \
            else None
        res = json.loads((out / "vc3d-result.json").read_text())
        return code, loaded, res

    def assert_ok(self, code, res):
        self.assertEqual(code, toolreg.EXIT_OK, json.dumps({k: res.get(k) for k in (
            "status", "warnings", "stderr_tail", "format_gate", "violations", "refused_by")}, default=str))
        self.assertEqual(res["status"], "ok")

    # ---- synthetic data

    def grid(self, name, z, shape=(30, 40), meta=None):
        """A flat tifxyz segment at height z, 20 voxels per grid step."""
        d = self.tmp / name
        d.mkdir()
        yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
        for c, a in zip("xyz", (xx * 20 + 100, yy * 20 + 100, np.full_like(xx, z))):
            tifffile.imwrite(d / f"{c}.tif", a)
        (d / "meta.json").write_text(json.dumps(dict({"type": "seg", "format": "tifxyz", "uuid": name,
                                                      "scale": [0.05, 0.05]}, **(meta or {}))))
        return d

    def letters(self, shape=(160, 160), seed=0):
        rng = np.random.default_rng(seed)
        ink = np.zeros(shape, bool)
        for _ in range(60):
            y, x = rng.integers(10, shape[0] - 10), rng.integers(10, shape[1] - 10)
            if rng.random() < 0.5:
                ink[y:y + 2, x:x + 8] = True
            else:
                ink[y:y + 8, x:x + 2] = True
        return ink

    def mapped_segment(self, name="seg", labels_tif=True, zarr_labels=False):
        """A segment with a forward map that follows the labels, a flat reverse-depth twin beside it, and its ink
        labels as a TIFF (view) or as villa's zarrs (hpscore)."""
        seg = self.grid(name, 500, shape=(16, 16))
        ink = self.letters()
        tifffile.imwrite(seg / "map.tif", (0.2 + 0.6 * ink).astype(np.float32))
        tifffile.imwrite(seg / "map_reverse.tif", np.full(ink.shape, 0.4, np.float32))
        if labels_tif:
            tifffile.imwrite(seg / f"{name}_inklabels.tif", (ink * 255).astype(np.uint8))
        if zarr_labels:
            for stem, data in (("inklabels", ink), ("supervision_mask", np.ones_like(ink))):
                g = zarr.open_group(str(seg / f"{name}_{stem}.zarr"), mode="w")
                lev = (data * 255).astype(np.uint8)
                g.create_array("0", data=np.repeat(np.repeat(lev, 4, 0), 4, 1))
                g.create_array("2", data=lev)
        return seg, ink

    def volume(self, voxel=9.362):
        vol = self.tmp / "vol.zarr"
        vol.mkdir(exist_ok=True)
        (vol / "meta.json").write_text(json.dumps({"voxelsize": voxel}))
        return vol


@needs_registry
class ManifestTest(Base):
    def test_each_gets_a_run_entry_returns_a_file_and_is_no_pipeline_step(self):
        self.assertEqual(toolreg.check(ROOT), [])
        found = self.plugins()
        with mock.patch.dict(toolreg.HOOKS, {"ap_available": lambda: True}):
            for tid in IDS:
                tool = self.reg.get(tid)
                self.assertEqual(toolreg.vc3d_entries(tool), ["run"], tid)
                self.assertNotIn("ap", toolreg.doors(tool), tid)            # viewers and checks, not stages
                self.assertIsNone(tool["pipeline"], tid)
                self.assertEqual(tool.safety["paid_compute"], "never")
                self.assertEqual(tool.safety["network"], "none")
                doc = found[f"scrolls.{tid}"]["doc"]
                self.assertEqual(doc["result"], {"kind": "file", "path": RESULTS[tid]}, tid)
                self.assertEqual(toolreg.stage_choices("repair", self.reg).get(f"reg:{tid}"), None)

    def test_vc3d_enables_each_entry_only_with_what_it_needs(self):
        found = self.plugins()
        sel = {"segment": "/s", "ink_overlay": "/s/map.tif", "volume": "/v.zarr"}
        self.assertIn("an active segment", host.enabled(found["scrolls.view"], {"ink_overlay": "/s/m.tif"})[1])
        self.assertIn("ink detection", host.enabled(found["scrolls.view"], {"segment": "/s"})[1])
        self.assertTrue(host.enabled(found["scrolls.view"], sel)[0])
        self.assertIn("an open volume", host.enabled(found["scrolls.hpscore"], dict(sel, volume=""))[1])
        self.assertTrue(host.enabled(found["scrolls.hpscore"], sel)[0])
        self.assertTrue(host.enabled(found["scrolls.doctor"], {})[0])               # needs nothing
        self.assertIn('"mesh_b"', host.enabled(found["scrolls.overlap"], sel)[1])
        self.assertTrue(host.enabled(found["scrolls.overlap"], dict(sel, inputs={"mesh_b": "w01"}))[0])
        # verify's control is optional on the command line, but VC3D's entry asks for all three labels: a device
        # check from VC3D always carries the map that must not agree
        three = {"reference": "cpu", "candidate": "mps", "control": "cpu reverse"}
        self.assertIn('"control"', host.enabled(found["scrolls.verify"], {
            "inputs": dict(three, control="")})[1])
        self.assertTrue(host.enabled(found["scrolls.verify"], {"inputs": three})[0])
        self.assertIn("an attached umbilicus", host.enabled(found["scrolls.stackcheck"], {
            "inputs": {"segments": "a,b"}})[1])
        self.assertTrue(host.enabled(found["scrolls.stackcheck"], {"umbilicus": "/u.json",
                                                                    "inputs": {"segments": "a,b"}})[0])
        for tid in ("verify", "stackcheck"):
            self.assertIn("--exit-zero", self.reg.get(tid)["run"]["argv"])


@needs_registry
@needs_maps
class FromVC3DTest(Base):
    """view, hpscore and doctor started from what VC3D has selected."""

    def test_view_writes_one_offline_page_with_the_control_and_the_labels(self):
        seg, ink = self.mapped_segment()
        before = sha(seg)
        found = self.plugins()
        code, loaded, res = self.launch(found["scrolls.view"], {
            "segment": str(seg), "ink_overlay": str(seg / "map.tif"), "output": str(self.tmp / "v")})
        self.assert_ok(code, res)
        self.assertEqual(loaded["kind"], "file")
        page = Path(loaded["path"]).read_text()
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)                                  # nothing to fetch: it opens offline
        self.assertIn('id="labels"', page)
        self.assertIn(f"reverse={seg / 'map_reverse.tif'}", res["argv"])
        self.assertIn(str(seg / "seg_inklabels.tif"), res["argv"])
        self.assertEqual(res["controls"]["verdict"], "present")
        stats = json.loads((self.tmp / "v" / "view.json").read_text())
        self.assertEqual(stats["shape"], list(ink.shape))
        self.assertEqual(sha(seg), before)
        # no labels file and no twin: the page still comes back, and the result says the control is missing
        bare, _ = self.mapped_segment("bare", labels_tif=False)
        (bare / "map_reverse.tif").unlink()
        code, loaded, res = self.launch(found["scrolls.view"], {
            "segment": str(bare), "ink_overlay": str(bare / "map.tif"), "output": str(self.tmp / "v2")})
        self.assert_ok(code, res)
        self.assertNotIn("--labels", res["argv"])
        self.assertEqual(res["controls"]["verdict"], toolreg.NO_CONTROL)
        # labels on another grid: view refuses them, the run fails and VC3D loads nothing
        odd, _ = self.mapped_segment("odd", labels_tif=False)
        tifffile.imwrite(odd / "odd_inklabels.tif", np.zeros((40, 40), np.uint8))
        code, loaded, res = self.launch(found["scrolls.view"], {
            "segment": str(odd), "ink_overlay": str(odd / "map.tif"), "output": str(self.tmp / "v3")})
        self.assertEqual((code, res["status"], loaded), (toolreg.EXIT_FAILED, "failed", None))
        self.assertIn("labels shape", " ".join(res["stderr_tail"]))

    def test_hpscore_reads_labels_mask_and_the_volumes_voxel_size(self):
        seg, _ = self.mapped_segment(labels_tif=False, zarr_labels=True)
        before = sha(seg)
        code, loaded, res = self.launch(self.plugins()["scrolls.hpscore"], {
            "segment": str(seg), "ink_overlay": str(seg / "map.tif"), "volume": str(self.volume(9.362)),
            "output": str(self.tmp / "hp")})
        self.assert_ok(code, res)
        rep = json.loads(Path(loaded["path"]).read_text())
        self.assertEqual(rep["voxel_um"], 9.362)                            # "auto": from the open volume
        self.assertGreater(rep["forward"]["hp_r"], 0.5)
        self.assertLess(abs(rep["control"]["hp_r"] or 0.0), 0.1)            # the flat twin scores nothing
        self.assertEqual(res["controls"]["verdict"], "present")
        self.assertEqual(sha(seg), before)
        # a volume with no voxel size: the entry's "auto" cannot be looked up, so nothing runs
        bare = self.tmp / "bare.zarr"
        bare.mkdir()
        code, _, res = self.launch(self.plugins()["scrolls.hpscore"], {
            "segment": str(seg), "ink_overlay": str(seg / "map.tif"), "volume": str(bare),
            "output": str(self.tmp / "hp2")})
        self.assertEqual((code, res["status"]), (toolreg.EXIT_BAD, "bad"))
        self.assertIn("voxel_um", res["error"])

    def test_doctor_needs_nothing_and_writes_only_its_report(self):
        code, loaded, res = self.launch(self.plugins()["scrolls.doctor"], {"output": str(self.tmp / "doc")})
        self.assert_ok(code, res)                       # a machine that fails a check still gets its report
        self.assertIn("overall:", Path(loaded["path"]).read_text())
        self.assertIn("--exit-zero", res["argv"])
        made = {p.name for p in (self.tmp / "doc").iterdir()}
        self.assertLessEqual(made - set(toolreg.HOST_FILES), {
            "doctor.txt", "stderr.txt", "selection.json", "registry-run.json", "provenance.json", "graph.json",
            "vc3d-result.json", "tmp", "vc3d"})


@needs_registry
@needs_maps
class BridgeTest(Base):
    """overlap, verify and stackcheck: the second segment, the ordered segments or the maps are named in VC3D's
    entry by segment id or ink detection label, and the launcher reads them once from its parent VC3D's bridge."""

    def app(self, segs, active, volume=None):
        state = {"volume": {"id": "vol", "voxelSize": 9.362, **({"path": str(volume)} if volume else {})},
                 "activeSurface": {"id": active}}
        return host.App(state=state, segments=[{"id": k, "path": str(v)} for k, v in segs.items()])

    def test_overlap_takes_the_second_segment_by_its_id(self):
        a, b, far = self.grid("w00", 500), self.grid("w01", 503), self.grid("w02", 700)
        before = sha(b)
        vol = self.volume()
        app = self.app({"w00": a, "w01": b, "w02": far}, "w00", vol)
        found = self.plugins()
        code, loaded, res = self.launch(found["scrolls.overlap"], {
            "segment": str(a), "volume": str(vol), "inputs": {"mesh_b": "w01"},
            "output": str(self.tmp / "o")}, app=app)
        self.assert_ok(code, res)
        rep = json.loads(Path(loaded["path"]).read_text())
        self.assertEqual(rep["same_sheet_share"], 1.0)
        self.assertAlmostEqual(rep["a_to_b"]["median_gap_vox"], 3.0, places=1)
        self.assertEqual({m for m, _ in app.calls}, {"state.get", "segments.list"})   # read only
        self.assertEqual(sha(b), before)
        code, loaded, res = self.launch(found["scrolls.overlap"], {
            "segment": str(a), "volume": str(vol), "inputs": {"mesh_b": "w02"},
            "output": str(self.tmp / "o2")}, app=app)
        self.assert_ok(code, res)
        self.assertEqual(json.loads(Path(loaded["path"]).read_text())["same_sheet_share"], 0.0)
        # without a bridge an id cannot become a path: nothing runs, and the reason says how to fix it
        code, _, res = self.launch(found["scrolls.overlap"], {
            "segment": str(a), "volume": str(vol), "inputs": {"mesh_b": "w01"}, "output": str(self.tmp / "o3")})
        self.assertEqual((code, res["status"]), (toolreg.EXIT_BAD, "bad"))
        self.assertIn("--agent-bridge", res["error"])                         # in the run folder VC3D names

    def test_verify_compares_maps_named_by_label_and_a_fail_comes_back_as_a_result(self):
        seg = self.grid("w00", 500, shape=(8, 8))
        rng = np.random.default_rng(3)
        cpu = (rng.random((64, 64)) * 255).astype(np.uint8)
        maps = {"cpu.tif": cpu, "mps.tif": cpu.copy(), "noise.tif": (rng.random((64, 64)) * 255).astype(np.uint8),
                "cpu_reverse.tif": (255 - cpu)}
        for n, a in maps.items():
            tifffile.imwrite(seg / n, a)
        (seg / "ink-detections.json").write_text(json.dumps([
            {"local_file": "cpu.tif", "label": "cpu"}, {"local_file": "mps.tif", "label": "mps"},
            {"local_file": "noise.tif", "label": "noise"},
            {"local_file": "cpu_reverse.tif", "label": "cpu reverse-depth control"}]))
        app = self.app({"w00": seg}, "w00")
        found = self.plugins()
        code, loaded, res = self.launch(found["scrolls.verify"], {
            "inputs": {"reference": "cpu", "candidate": "mps", "control": "cpu reverse-depth control"},
            "output": str(self.tmp / "ok")}, app=app)
        self.assert_ok(code, res)
        rep = json.loads(Path(loaded["path"]).read_text())
        self.assertEqual(rep["verdict"], "pass")
        self.assertEqual(res["controls"]["verdict"], "present")
        # a candidate that disagrees: verify says FAIL in its report, and VC3D still gets the report
        code, loaded, res = self.launch(found["scrolls.verify"], {
            "inputs": {"reference": "cpu", "candidate": "noise", "control": "cpu reverse-depth control"},
            "output": str(self.tmp / "fail")}, app=app)
        self.assert_ok(code, res)
        self.assertEqual(json.loads(Path(loaded["path"]).read_text())["verdict"], "fail")
        # a label the active segment does not have is refused before anything runs
        code, _, res = self.launch(found["scrolls.verify"], {
            "inputs": {"reference": "cpu", "candidate": "gpu", "control": "cpu reverse-depth control"},
            "output": str(self.tmp / "nolabel")}, app=app)
        self.assertEqual((code, res["status"]), (toolreg.EXIT_BAD, "bad"))
        self.assertIn("no ink detection labelled", res["error"])

    def stack(self, n=3):
        import test_stackcheck as tsc
        segs = {}
        for k in range(n):
            xyz, valid, _ = tsc.winding(k)
            tsc.write_tifxyz(self.tmp / "stack" / f"w{k:02d}", xyz, valid)
            segs[f"w{k:02d}"] = self.tmp / "stack" / f"w{k:02d}"
        umb = self.tmp / "umbilicus.json"
        umb.write_text(json.dumps(tsc.umbilicus()))
        return segs, umb

    def test_stackcheck_takes_ordered_ids_and_flags_come_back_as_a_result(self):
        segs, umb = self.stack()
        app = self.app(segs, "w00")
        found = self.plugins()
        code, loaded, res = self.launch(found["scrolls.stackcheck"], {
            "umbilicus": str(umb), "inputs": {"segments": "w00,w01,w02"}, "output": str(self.tmp / "s")},
            app=app)
        self.assert_ok(code, res)
        rep = json.loads(Path(loaded["path"]).read_text())
        self.assertTrue(rep["summary"]["clean"])
        bound = json.loads((self.tmp / "s" / "registry-run.json").read_text())["inputs"]["segments"]
        self.assertEqual(bound["value"], [str(segs[k]) for k in ("w00", "w01", "w02")])
        # the same stack named out of order: stackcheck flags the order, and VC3D still gets the report
        code, loaded, res = self.launch(found["scrolls.stackcheck"], {
            "umbilicus": str(umb), "inputs": {"segments": "w00,w02,w01"}, "output": str(self.tmp / "s2")},
            app=app)
        self.assert_ok(code, res)
        rep = json.loads(Path(loaded["path"]).read_text())
        self.assertFalse(rep["summary"]["clean"])
        self.assertTrue(rep["summary"]["flagged"]["order"])
        self.assertTrue((self.tmp / "s2" / "flags.npz").is_file())


class RefusalRecordTest(Base):
    """A run refused before it starts leaves its reason in vc3d-result.json, but only in a fresh VC3D run folder."""

    def test_only_a_fresh_plugin_folder_gets_the_record(self):
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        (fresh / "plugin-run.json").write_text("{}")
        with contextlib.redirect_stderr(io.StringIO()):
            code = toolreg.main(["run", "overlap", "--input", "mesh_b=w01", "--out", str(fresh), "--json"])
        self.assertEqual(code, toolreg.EXIT_BAD)
        doc = json.loads((fresh / "vc3d-result.json").read_text())
        self.assertEqual((doc["schema"], doc["status"], doc["tool"]), (toolreg.RESULT_SCHEMA, "bad", "overlap"))
        mine = self.tmp / "mine"
        mine.mkdir()
        (mine / "notes.txt").write_text("keep")
        missing = self.tmp / "missing"
        for out in (mine, missing):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(toolreg.main(["run", "overlap", "--input", "mesh_b=w01", "--out", str(out)]),
                                 toolreg.EXIT_BAD)
        self.assertEqual(sorted(p.name for p in mine.iterdir()), ["notes.txt"])
        self.assertFalse(missing.exists())


@needs_maps
class ExitZeroTest(Base):
    """The flags VC3D's entries rely on: verify --exit-zero and stackcheck --exit-zero keep the verdict in the
    report and exit 0; bad inputs still exit 2."""

    def cli(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(argv)
        return code, buf.getvalue()

    def test_verify(self):
        rng = np.random.default_rng(0)
        a = (rng.random((32, 32)) * 255).astype(np.uint8)
        b = (rng.random((32, 32)) * 255).astype(np.uint8)
        for n, m in (("a.tif", a), ("b.tif", b)):
            tifffile.imwrite(self.tmp / n, m)
        code, _ = self.cli(["verify", str(self.tmp / "a.tif"), str(self.tmp / "b.tif"), "--json"])
        self.assertEqual(code, 1)
        code, out = self.cli(["verify", str(self.tmp / "a.tif"), str(self.tmp / "b.tif"), "--json", "--exit-zero"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verdict"], "fail")
        code, _ = self.cli(["verify", str(self.tmp / "a.tif"), str(self.tmp / "a.tif"), "--json"])
        self.assertEqual(code, 3)                                            # agrees, but no control
        code, _ = self.cli(["verify", str(self.tmp / "a.tif"), str(self.tmp / "missing.tif"), "--exit-zero"])
        self.assertEqual(code, 2)

    def test_stackcheck(self):
        import test_stackcheck as tsc
        segs = []
        for k in (0, 2, 1):                                                  # out of order: flagged
            xyz, valid, _ = tsc.winding(k)
            tsc.write_tifxyz(self.tmp / f"w{k:02d}", xyz, valid)
            segs.append(str(self.tmp / f"w{k:02d}"))
        umb = self.tmp / "umb.json"
        umb.write_text(json.dumps(tsc.umbilicus()))
        base = ["stackcheck", *segs, "--umbilicus", str(umb), "--stride", "2", "--json"]
        self.assertEqual(self.cli(base)[0], 1)
        code, out = self.cli(base + ["--exit-zero"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["summary"]["clean"])
        self.assertEqual(self.cli(["stackcheck", str(self.tmp / "nope"), "--umbilicus", str(umb),
                                   "--exit-zero"])[0], 2)

    def test_doctor(self):
        from kit import doctor
        with mock.patch.object(doctor, "run_checks", return_value=[("gpu", doctor.FAIL, "none here")]):
            code, out = self.cli(["doctor", "--disk", str(self.tmp)])
            self.assertEqual(code, 1)
            code, out = self.cli(["doctor", "--disk", str(self.tmp), "--exit-zero"])
            self.assertEqual(code, 0)
            self.assertIn("overall: fail", out)


if __name__ == "__main__":
    unittest.main()
