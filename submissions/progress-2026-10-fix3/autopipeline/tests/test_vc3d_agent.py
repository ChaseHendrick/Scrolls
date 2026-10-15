"""Tests for kit.vc3d_agent (the tools behind `kit vc3d mcp` and `kit vc3d call`), kit.vc3d_bridge and the
new `kit vc3d` actions, against the stand-in VC3D of tests/vc3d_fakes.py.

What is checked is the layer above VC3D: arguments, the repository's rules (outputs stay out of git, a
target needs its preregistration, the reverse control runs next to the forward map), layer order on
new and old binaries, retries, receipts, background jobs and cancellation, previews, seating and the
frame search, the app bridge. VC3D itself is checked by `kit vc3d selftest` (tests/test_vc3d.py).
"""
import contextlib
import importlib.util
import io
import json
import math
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402
from test_vc3d import FAKE_RENDER  # noqa: E402
from test_vc3d_catalog import CATALOG  # noqa: E402

from kit import cli, fetch, ledger, vc3d, vc3d_agent, vc3d_bridge, vc3d_cache, vc3d_catalog, vc3d_io  # noqa: E402

ROOT = fakes.ROOT
HAVE_NUMPY = importlib.util.find_spec("numpy") is not None
HAVE_STACK = vc3d_agent.numpy_stack()


def middle(shape, data):
    """Value of the centre pixel in each layer."""
    n, h, w = shape
    return [data[k * h * w + (h // 2) * w + w // 2] for k in range(n)]


class Base(unittest.TestCase):
    """A temp folder with the fake bin, a work home outside the repository and a Context on them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.bin = self.d / "bin"
        fakes.make_bin(self.bin)
        self.home = self.d / "home"
        self.env = fakes.env_for(self.bin, self.home)
        self.ctx = vc3d_agent.Context(env=self.env)

    def tearDown(self):
        self.tmp.cleanup()

    def context(self, home=None, root=None, **extra):
        return vc3d_agent.Context(root=root, env=dict(self.env, KIT_VC3D_HOME=str(home or self.home),
                                                      **{k: str(v) for k, v in extra.items()}))

    def call(self, name, args=None, ctx=None):
        return vc3d_agent.call(name, args or {}, ctx or self.ctx)

    def volume(self, value=fakes.ramp, name="vol.zarr", **kw):
        return fakes.write_group(self.d / name, [64, 64, 64], value, **kw)

    def surface(self, z=32, name="plane.tifxyz", **kw):
        return fakes.write_tifxyz(self.d / name, fakes.plane(z), **kw)


# The core's 41 tools are defined in these modules. Optional tool sets (kit/vc3d_ext_*.py beside
# kit/vc3d_agent.py, loaded when present) may add more; the test does not depend on which, if any, are here.
CORE_MODULES = ("kit.vc3d_agent", "kit.vc3d_prep_tools", "kit.autopipe")
N_CORE_TOOLS = 41


def extension_modules():
    import pkgutil
    kit = Path(vc3d_agent.__file__).resolve().parent
    return [m.name for m in pkgutil.iter_modules([str(kit)]) if m.name.startswith("vc3d_ext_")]


class TestSchemas(unittest.TestCase):
    def test_every_tool_has_a_closed_schema(self):
        core = [t.name for t in vc3d_agent.TOOLS.values() if t.handler.__module__ in CORE_MODULES]
        self.assertEqual(len(core), N_CORE_TOOLS, sorted(core))
        added = [t.name for t in vc3d_agent.TOOLS.values() if t.handler.__module__ not in CORE_MODULES]
        self.assertEqual(bool(added), bool(extension_modules()), (added, extension_modules()))
        for t in vc3d_agent.TOOLS.values():
            s = t.schema()
            self.assertEqual((s["type"], s["additionalProperties"]), ("object", False), t.name)
            self.assertLessEqual(set(s["required"]), set(s["properties"]), t.name)
            self.assertEqual("background" in s["properties"], t.background, t.name)
            self.assertTrue(t.description and t.title, t.name)
            self.assertEqual(set(t.annotations()), {"title", "readOnlyHint", "destructiveHint", "idempotentHint",
                                                    "openWorldHint"})
            for key, spec in s["properties"].items():
                self.assertIn(spec["type"], ("string", "integer", "number", "boolean", "array", "object"), (t.name, key))

    def test_validation(self):
        bad = [
            ("nope", {}, "no tool"),
            ("render", {"surface": "s"}, "missing required argument(s) volume"),
            ("render", {"surface": "s", "volume": "v", "colour": 1}, "unknown argument(s) colour"),
            ("render", {"surface": "s", "volume": "v", "layers": "28"}, "layers should be integer"),
            ("render", {"surface": "s", "volume": "v", "layers": True}, "layers should be integer"),
            ("render", {"surface": "s", "volume": "v", "layers": 0}, "layers must be minimum 1"),
            ("render", {"surface": "s", "volume": "v", "preset": "5um"}, "preset must be one of"),
            ("render", {"surface": "s", "volume": "v", "crop": [1, 2, 3]}, "crop needs 4 to 4 items"),
            ("render", {"surface": "s", "volume": "v", "crop": [1, 2, 3, "4"]}, "every item of crop should be integer"),
            ("ink", {"input": "i", "purpose": "smoke", "variants": ["f", "x"]}, "items of variants must be in"),
            ("preview", {"path": "p", "max_side": 8000}, "max_side must be maximum 4096"),
            ("jobs", [], "takes a JSON object"),
        ]
        for name, args, message in bad:
            with self.subTest(name=name, args=args), self.assertRaises(vc3d_agent.ToolError) as err:
                vc3d_agent.call(name, args, vc3d_agent.Context(env={}))
            self.assertIn(message, str(err.exception))
        t = vc3d_agent.TOOLS["render"]
        vc3d_agent.validate(t, {"surface": "s", "volume": "v", "layers": 28.0, "scale": 2, "voxel_um": None})


class TestPaths(Base):
    def test_fresh_never_reuses_a_name(self):
        first = vc3d_agent.fresh(self.d / "out", create=True)
        second = vc3d_agent.fresh(self.d / "out", create=True)
        self.assertEqual((first.name, second.name), ("out", "out-2"))
        (self.d / "p.png").write_bytes(b"")
        self.assertEqual(vc3d_agent.fresh(self.d / "p.png").name, "p-2.png")
        self.assertFalse((self.d / "p-2.png").exists())

    def test_outputs_stay_out_of_git(self):
        ctx = vc3d_agent.Context(env=self.env)  # the real repository
        with self.assertRaises(vc3d_agent.ToolError) as err:
            vc3d_agent.writable(ctx, "docs/should-not-exist")
        self.assertIn("rule 6", str(err.exception))
        for ok in ("work/vc3d/x", "experiments/slug/maps", "checkpoints/m", str(self.d / "outside")):
            self.assertTrue(vc3d_agent.ignored(ctx, vc3d_agent.resolve(ctx, ok)), ok)
        self.assertFalse(vc3d_agent.ignored(ctx, ROOT / "experiments" / "README.md"))
        self.assertFalse((ROOT / "docs" / "should-not-exist").exists())

    def test_small_helpers(self):
        self.assertEqual(vc3d_agent.slug("PHerc 0139 / w035.tifxyz"), "PHerc-0139-w035.tifxyz")
        self.assertTrue(vc3d_agent.is_url("s3://bucket/x") and vc3d_agent.is_url("HTTPS://a/b"))
        self.assertFalse(vc3d_agent.is_url("/data/x.zarr"))
        self.assertEqual(vc3d_agent.resolve(self.ctx, "work/x"), ROOT / "work" / "x")
        with self.assertRaises(vc3d_agent.ToolError):
            vc3d_agent.existing(self.ctx, self.d, "surface", "tifxyz")


class TestRunLogged(Base):
    def run_sleep(self, *args, ctx=None, timeout=30):
        log = self.d / "run.log"
        argv = [self.bin / "vc_sleep", *args]
        return vc3d_agent.run_logged(ctx or self.ctx, argv, log, env=self.env, timeout=timeout), log

    def test_exit_codes_timeout_and_progress(self):
        said = []
        ctx = vc3d_agent.Context(env=self.env, progress=said.append)
        (rc, seconds), log = self.run_sleep("1", "--exit", "3", ctx=ctx)
        self.assertEqual(rc, 3)
        self.assertIn("tick", log.read_text())
        self.assertTrue(said and said[0].startswith("vc_sleep:"), said)
        (rc, seconds), _ = self.run_sleep("30", timeout=1)
        self.assertEqual(rc, "timeout")
        self.assertLess(seconds, 15)
        rc, _ = vc3d_agent.run_logged(self.ctx, [self.d / "missing-tool"], self.d / "x.log")
        self.assertTrue(rc.startswith("could not start"))

    def test_cancel_kills_the_child(self):
        cancel = threading.Event()
        ctx = vc3d_agent.Context(env=self.env, cancel=cancel)
        pid = self.d / "pid"
        threading.Timer(0.8, cancel.set).start()
        (rc, seconds), _ = self.run_sleep("30", "--pid", pid, ctx=ctx)
        self.assertEqual(rc, "cancelled")
        self.assertFalse(vc3d_bridge._alive(int(pid.read_text())))


class TestDiscovery(Base):
    def test_status_with_and_without_tools(self):
        st = self.call("status")
        self.assertEqual(st["tools"], f"VC_BIN: {self.bin} (started directly)")
        self.assertTrue(all(st["has"].values()), st["has"])
        self.assertTrue(st["renderer"]["flip_normals"])
        self.assertIn("never run", st["last_selftest"])
        self.assertEqual((st["jobs_running"], st["app"], st["models"]), ([], None, []))
        self.assertEqual(st["ink_python"]["python"], sys.executable)
        bare = vc3d_agent.Context(env={"PATH": "/usr/bin:/bin", "KIT_VC3D_HOME": str(self.home)})
        with mock.patch.object(vc3d, "MAC_BIN", self.d / "absent"):
            st = self.call("status", ctx=bare)
            self.assertIsNone(st["tools"])
            self.assertIn("VC_BIN", st["fix"])
            with self.assertRaises(vc3d_agent.ToolError) as err:
                self.call("render", {"surface": "s", "volume": "v"}, ctx=bare)
        self.assertIn("no VC3D tools found", str(err.exception))

    def test_list_tools_and_help(self):
        listed = {r["tool"]: r["summary"] for r in self.call("list_tools")["tools"]}
        self.assertEqual(sorted(listed), ["VC3D", "vc_flatten", "vc_gen_umbilicus", "vc_grow_seg_from_seed", "vc_render_tifxyz",
                                          "vc_sleep", "vc_tifxyz_selfcross"])
        self.assertIn("stand-in for a long VC3D run", listed["vc_sleep"])
        self.assertEqual(self.call("list_tools")["tools"][0]["tool"], "VC3D")  # the cached copy
        helped = self.call("tool_help", {"tool": "vc_render_tifxyz"})
        self.assertEqual(helped["exit"], 0)
        self.assertIn("--flip-normals", helped["help"])
        for name in ("vc_missing", "rm"):
            with self.assertRaises(vc3d_agent.ToolError):
                self.call("tool_help", {"tool": name})

    def test_guide(self):
        top = self.call("guide")
        self.assertIn("preregistered", top["instructions"])
        self.assertGreaterEqual(len(top["topics"]), 5)
        rules = self.call("guide", {"topic": "rules"})
        self.assertIn("rules", rules["topic"].lower())
        self.assertTrue(rules["text"].startswith("## "))
        # a heading that starts with the topic wins over one that merely contains it
        self.assertEqual(self.call("guide", {"topic": "ink"})["topic"], "Ink detection")
        self.assertEqual(self.call("guide", {"topic": "the vc3d app"})["topic"], "The VC3D app")
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("guide", {"topic": "no such topic at all"})

    def test_selftest_tool_records_its_verdict(self):
        only_render = self.d / "selftest-bin"
        only_render.mkdir()
        exe = only_render / vc3d.PROBE
        exe.write_text(FAKE_RENDER)
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        ctx = vc3d_agent.Context(env=dict(self.env, VC_BIN=str(only_render)))
        report = self.call("selftest", {"timeout": 60}, ctx)
        self.assertEqual(report["verdict"], "PASS", report["summary"])
        self.assertEqual(self.call("status", ctx=ctx)["last_selftest"]["verdict"], "PASS")


class TestRender(Base):
    def stack_of(self, result):
        return vc3d.read_layers(result["tif_dir"])

    def test_team_order_by_default(self):
        vol, surf = self.volume(), self.surface()
        team = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 5, "format": "both"})
        self.assertEqual((team["exit"], team["order"], team["shape"]), (0, "team (--flip-normals)", [5, 36, 36]))
        # ramp 4 + 3 z with the plane at z = 32: team order starts 2 voxels toward the scroll centre (-N)
        shape, data = self.stack_of(team)
        self.assertEqual(middle(shape, data), [106, 103, 100, 97, 94])
        z = vc3d_io.open_zarr(team["zarr"])
        buf, _ = z.read([(0, 5), (18, 19), (18, 19)])
        self.assertEqual(list(buf), [106, 103, 100, 97, 94])
        self.assertEqual([n for n, _ in team["levels"]], ["0", "1"])
        receipt = json.loads(Path(team["receipt"]).read_text())
        self.assertEqual((receipt["tool"], receipt["layers"], receipt["order"]), ("render", 5, "team (--flip-normals)"))
        self.assertIn("sha256", receipt["inputs"]["surface"])
        argv = receipt["steps"][0]["argv"]
        self.assertIn("--flip-normals", argv)
        self.assertEqual(argv[argv.index("--zarr-compressor") + 1], "blosc" if vc3d_agent._have("numcodecs") else "gzip")
        normal = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 5, "format": "tif",
                                      "order": "normal"})
        self.assertEqual(middle(*self.stack_of(normal)), [94, 97, 100, 103, 106])
        self.assertNotEqual(team["out"], normal["out"])

    def test_old_binary_gets_team_order_from_kit(self):
        vol, surf = self.volume(), self.surface()
        old = self.context(home=self.d / "home-old", FAKE_OLD="1")
        res = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 5, "format": "tif"}, old)
        self.assertIn("reversed by kit", res["order"])
        self.assertEqual(middle(*self.stack_of(res)), [106, 103, 100, 97, 94])
        self.assertNotIn("--flip-normals", json.loads(Path(res["receipt"]).read_text())["steps"][0]["argv"])
        if HAVE_STACK:
            res = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 5}, old)
            z = vc3d_io.open_zarr(res["zarr"])
            self.assertEqual(list(z.read([(0, 5), (18, 19), (18, 19)])[0]), [106, 103, 100, 97, 94])
            self.assertNotIn("tif_dir", res)
        else:
            with self.assertRaises(vc3d_agent.ToolError) as err:
                self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 5}, old)
            self.assertIn("format=tif", str(err.exception))

    def test_crop_level_frame_and_composite(self):
        vol = self.volume(binned="zyx", levels=2)
        surf = self.surface()
        crop = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 3, "format": "tif",
                                    "crop": [4, 6, 10, 8]})
        self.assertEqual(crop["shape"], [3, 8, 10])
        level = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 3, "format": "tif", "level": 1})
        self.assertEqual(level["shape"], [3, 18, 18])
        self.assertEqual(middle(*self.stack_of(level))[1], 100)  # z 32 at level 0 is z 16 at level 1: same value
        doubled = fakes.write_tifxyz(self.d / "x2.tifxyz", fakes.plane(64, x0=16.0, step=8.0), scale=0.125)
        frame = self.call("render", {"surface": str(doubled), "volume": str(vol), "layers": 3, "format": "tif",
                                     "scale_segmentation": 0.5})
        self.assertEqual((frame["shape"], middle(*self.stack_of(frame))), ([3, 36, 36], [103, 100, 97]))
        comp = self.call("render", {"surface": str(surf), "volume": str(vol), "format": "tif",
                                    "composite": {"start": -2, "end": 2, "reducer": "max"}})
        self.assertEqual((comp["order"], comp["shape"], middle(*self.stack_of(comp))), ("composite", [1, 36, 36], [106]))

    def test_volcomp_copy_is_refused_unless_allowed(self):
        vol, surf = self.volume(), self.surface()
        url = "https://dl.ash2txt.org/community-uploads/forrest/volcomp/PHercTest/volumes/vol.zarr"
        ctx = self.context(FAKE_REMOTE_MAP=json.dumps({url: str(vol)}))
        with self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("render", {"surface": str(surf), "volume": url, "layers": 3}, ctx)
        self.assertIn("volcomp", str(err.exception))
        self.assertIn("allow_lossy", str(err.exception))
        res = self.call("render", {"surface": str(surf), "volume": url, "layers": 3, "allow_lossy": True,
                                   "voxel_um": 9.362}, ctx)
        self.assertEqual(res["exit"], 0)
        self.assertIn("volcomp", res["warnings"][0])
        self.assertIn("volcomp", json.loads(Path(res["receipt"]).read_text())["lossy_source"])
        render, warnings = vc3d_agent.render_provenance(res["zarr"])
        self.assertTrue(render["lossy_source"])
        self.assertTrue(any("lossy source" in w for w in warnings))

    def test_remote_volume_is_retried_with_resume(self):
        vol, surf = self.volume(), self.surface()
        url = "https://example.invalid/PHercTest/volumes/vol.zarr"
        log = self.d / "argv.log"
        ctx = self.context(FAKE_REMOTE_MAP=json.dumps({url: str(vol)}), FAKE_FAIL_FILE=self.d / "fails",
                           FAKE_FAIL_TIMES=1, FAKE_LOG=log)
        res = self.call("render", {"surface": str(surf), "volume": url, "layers": 3, "voxel_um": 9.362}, ctx)
        self.assertEqual((res["exit"], res["attempts"]), (0, 2))
        runs = [json.loads(line) for line in log.read_text().splitlines() if '"--volume"' in line]
        self.assertEqual(["--resume" in r for r in runs], [False, True])
        self.assertEqual(runs[0][runs[0].index("--remote-url") + 1], url)
        self.assertEqual(runs[0][runs[0].index("--voxel-size") + 1], "9.362")
        ctx = self.context(FAKE_REMOTE_MAP=json.dumps({url: str(vol)}), FAKE_FAIL_FILE=self.d / "fails2",
                           FAKE_FAIL_TIMES=9)
        res = self.call("render", {"surface": str(surf), "volume": url, "layers": 3}, ctx)
        self.assertEqual((res["exit"], res["attempts"]), (1, 3))
        self.assertIn("connection reset", res["log_tail"])
        local = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 3},
                          self.context(FAKE_FAIL_FILE=self.d / "fails3", FAKE_FAIL_TIMES=1))
        self.assertEqual((local["exit"], local["attempts"]), (1, 1))  # local volumes are not retried by default

    def test_output_inside_the_repository_is_refused(self):
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("render", {"surface": str(self.surface()), "volume": str(self.volume()),
                                 "out": str(ROOT / "docs" / "render-here")})
        self.assertFalse((ROOT / "docs" / "render-here").exists())
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("render", {"surface": str(self.d), "volume": str(self.volume())})


class TestTraceFlattenInspect(Base):
    def test_trace_seed_named_and_resume(self):
        vol = self.volume(fakes.sheet)
        res = self.call("trace", {"volume": str(vol), "seed": [24, 24, 32]})
        self.assertEqual(res["exit"], 0)
        (s,) = res["surfaces"]
        self.assertEqual((s["valid_vertices"], s["grid_rows_cols"], s["area_voxels2"], s["meta_area_vx2"]),
                         (81, [9, 9], 1024.0, 1024.0))
        self.assertEqual(s["bbox_xyz"], [[8.0, 8.0, 32.0], [40.0, 40.0, 32.0]])
        self.assertEqual(s["render_px_at_scale_1"], [36, 36])
        receipt = json.loads(Path(res["receipt"]).read_text())
        self.assertEqual((receipt["params"]["mode"], receipt["params"]["thread_limit"]), ("seed", min(4, vc3d.cpu_limit())))
        named = self.call("trace", {"volume": str(vol), "name": "w-test", "out": str(self.d / "traces")})
        self.assertEqual(named["surfaces"][0]["path"], str(self.d / "traces" / "w-test"))
        resumed = self.call("trace", {"volume": str(vol), "mode": "resume", "resume": s["path"], "generations": 50})
        self.assertEqual(resumed["surfaces"][0]["bbox_xyz"][0][2], 36.0)
        params = json.loads(Path(resumed["receipt"]).read_text())["params"]
        self.assertEqual((params["mode"], params["generations"]), ("seed", 50))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("trace", {"volume": str(vol), "mode": "resume"})

    def test_trace_reads_local_normal_grids_and_says_when_it_has_none(self):
        vol = self.volume(fakes.sheet)
        bare = self.call("trace", {"volume": str(vol), "seed": [24, 24, 32], "seed_check": False})
        self.assertIn("extrapolated by smoothness", bare["data_term"])
        self.assertNotIn("normal_grid_path", json.loads(Path(bare["receipt"]).read_text())["params"])
        grids = self.d / "grids"
        (grids / "xy").mkdir(parents=True)
        with self.assertRaisesRegex(vc3d_agent.ToolError, "not a normal-grid folder"):
            self.call("trace", {"volume": str(vol), "seed": [24, 24, 32], "seed_check": False,
                                "normal_grids": str(grids)})
        (grids / "metadata.json").write_text(json.dumps({"spiral-step": 20, "grid-step": 64}))
        (grids / "xy" / "000032.grid").write_bytes(b"grid")
        res = self.call("trace", {"volume": str(vol), "seed": [24, 24, 32], "seed_check": False,
                                  "normal_grids": str(grids)})
        self.assertEqual(res["exit"], 0)
        self.assertNotIn("data_term", res)
        self.assertEqual(res["normal_grids"], {"source": str(grids), "remote": False, "files": 1})
        self.assertEqual(json.loads(Path(res["receipt"]).read_text())["params"]["normal_grid_path"], str(grids))
        self.assertIn(f"normal grids {grids} remote None", res["log_tail"])

    def test_streamed_normal_grids_keep_a_cache_and_drop_false_missing_markers(self):
        vol = self.volume(fakes.sheet)
        bucket = self.d / "bucket"
        (bucket / "pred.normal-grids" / "xy").mkdir(parents=True)
        (bucket / "pred.normal-grids" / "metadata.json").write_text("{}")
        (bucket / "pred.normal-grids" / "xy" / "000040.grid").write_bytes(b"grid")
        with fakes.S3LikeServer(bucket, false=1) as srv:
            url = srv.url + "/pred.normal-grids/"
            ctx = self.context(KIT_VC3D_RELAY="0",
                               FAKE_GRID_FETCH=json.dumps(["xy/000032.grid"]),
                               FAKE_GRID_MISSING=json.dumps(["xy/000040.grid", "xy/009999.grid"]))
            res = self.call("trace", {"volume": str(vol), "seed": [24, 24, 32], "seed_check": False,
                                      "normal_grids": url}, ctx)
        ng = res["normal_grids"]
        cache = Path(ng["cache"])
        self.assertEqual(cache.parent, ctx.home / "normal-grids")
        # VC3D streamed through a view of its own (the marker), and what it fetched landed in the shared cache
        view = Path(json.loads(Path(res["receipt"]).read_text())["params"]["normal_grid_path"])
        self.assertNotEqual(view, cache)
        self.assertFalse(view.exists())             # removed after the run
        self.assertFalse((cache / vc3d_agent.GRID_MARKER).exists())
        self.assertIn(f"normal grids {view} remote {url.rstrip('/')}", res["log_tail"])
        self.assertTrue((cache / "xy" / "000032.grid").is_file())
        # 000040 is in the bucket (a false 404 during the run): its marker goes; 009999 is not: its marker stays
        self.assertEqual((ng["files"], ng["missing"], ng["false_missing"], ng["unchecked"]), (1, 2, 1, 0))
        self.assertIn("went without their normals", ng["warning"])
        self.assertEqual(ng["fetch_failed"], 0)
        self.assertEqual(vc3d_agent.grid_missing(cache), ["xy/009999.grid"])
        again, info = vc3d_agent.normal_grids_dir(ctx, url)
        self.assertEqual(info["cache"], str(cache))  # one cache folder per published grid set
        vc3d_agent.close_grid_view(again, cache)

    def test_trace_counts_the_grid_files_its_run_fetched_beside_the_cache_total(self):
        vol = self.volume(fakes.sheet)
        bucket = self.d / "bucket"
        (bucket / "pred.normal-grids" / "xy").mkdir(parents=True)
        (bucket / "pred.normal-grids" / "metadata.json").write_text("{}")
        with fakes.S3LikeServer(bucket) as srv:
            url = srv.url + "/pred.normal-grids/"

            def trace(fetched):
                ctx = self.context(KIT_VC3D_RELAY="0", FAKE_GRID_FETCH=json.dumps(fetched))
                return self.call("trace", {"volume": str(vol), "seed": [24, 24, 32], "seed_check": False,
                                           "normal_grids": url}, ctx)["normal_grids"]
            runs = [trace(["xy/000032.grid", "xz/000020.grid"]),
                    trace(["xy/000032.grid", "xy/000052.grid"]),   # 000032 is in the cache from the run before
                    trace([])]
        # files stays the shared cache's total over every run; files_fetched is the part this run added
        self.assertEqual([(ng["files_before"], ng["files_fetched"], ng["files"]) for ng in runs],
                         [(0, 2, 2), (2, 1, 3), (3, 0, 3)])
        self.assertEqual(vc3d_agent.grid_files(runs[0]["cache"]), 3)

    def test_each_run_streams_grids_through_its_own_view(self):
        # two traces of one grid set in two processes have two relays: each VC3D must keep reading its own
        cache = self.d / "cache"
        a = vc3d_agent.open_grid_view(cache, "http://127.0.0.1:1111/g")
        b = vc3d_agent.open_grid_view(cache, "http://127.0.0.1:2222/g")
        self.assertNotEqual(a, b)
        self.assertEqual(json.loads((a / vc3d_agent.GRID_MARKER).read_text()), {"url": "http://127.0.0.1:1111/g"})
        self.assertEqual(json.loads((b / vc3d_agent.GRID_MARKER).read_text()), {"url": "http://127.0.0.1:2222/g"})
        self.assertFalse((cache / vc3d_agent.GRID_MARKER).exists())
        (a / "xy" / "000007.grid").write_bytes(b"g")        # written through the link: in the cache at once
        self.assertTrue((cache / "xy" / "000007.grid").is_file())
        self.assertTrue((b / "xy" / "000007.grid").is_file())
        (a / "xy" / "000008.grid.tmp-1-2").write_bytes(b"partial")
        (a / "2" / "xy").mkdir(parents=True)                # a multiscale level VC3D made in the view itself
        (a / "2" / "xy" / "000009.grid").write_bytes(b"g")
        vc3d_agent.close_grid_view(a, cache)
        self.assertFalse(a.exists())
        self.assertTrue((cache / "2" / "xy" / "000009.grid").is_file())
        self.assertTrue((b / "xy" / "000007.grid").is_file())  # the other view is untouched
        vc3d_agent.close_grid_view(b, cache)
        self.assertEqual(sorted(p.name for p in (cache / "xy").iterdir()), ["000007.grid", "000008.grid.tmp-1-2"])

    def test_grid_view_falls_back_to_the_cache_where_links_fail(self):
        cache = self.d / "cache"
        with mock.patch.object(Path, "symlink_to", side_effect=OSError("no links here")):
            (cache / "xy").mkdir(parents=True)
            (cache / "metadata.json").write_text("{}")
            view = vc3d_agent.open_grid_view(cache, "http://127.0.0.1:1111/g")
        self.assertEqual(view, cache)
        self.assertEqual(json.loads((cache / vc3d_agent.GRID_MARKER).read_text()), {"url": "http://127.0.0.1:1111/g"})
        vc3d_agent.close_grid_view(view, cache)
        self.assertTrue(cache.is_dir())

    def test_grid_fetch_failures_are_read_from_the_log(self):
        text = ("t: normal-grid fetch for xy/002300.grid returned HTTP 0\n"
                "normal-grid fetch failed for xz/000100.grid: Couldn't connect to server\n"
                "normal-grid fetch for xy/002300.grid returned HTTP 503\n")
        self.assertEqual(vc3d_agent.grid_fetch_failures(text),
                         {"xy/002300.grid": "HTTP 503", "xz/000100.grid": "Couldn't connect to server"})
        self.assertEqual(vc3d_agent.grid_fetch_failures("[GridStore Cache] Hit Rate: 96.6%"), {})

    def test_trace_reports_grid_fetches_that_failed_and_fetches_them_again(self):
        vol = self.volume(fakes.sheet)
        bucket = self.d / "bucket"
        (bucket / "pred.normal-grids" / "xy").mkdir(parents=True)
        (bucket / "pred.normal-grids" / "metadata.json").write_text("{}")
        (bucket / "pred.normal-grids" / "xy" / "000041.grid").write_bytes(b"grid41")
        with fakes.S3LikeServer(bucket, false=1) as srv:
            url = srv.url + "/pred.normal-grids/"
            ctx = self.context(KIT_VC3D_RELAY="0", FAKE_GRID_FAIL=json.dumps(["xy/000041.grid", "xy/000099.grid"]))
            res = self.call("trace", {"volume": str(vol), "seed": [24, 24, 32], "seed_check": False,
                                      "normal_grids": url}, ctx)
            ng = res["normal_grids"]
            self.assertEqual((ng["fetch_failed"], ng["refetched"], ng["refetch_failed"]), (2, 1, 1))
            self.assertEqual(ng["fetch_failed_sample"], ["xy/000041.grid: HTTP 0", "xy/000099.grid: HTTP 0"])
            self.assertIn("went without those slices' normals", ng["fetch_warning"])
            self.assertEqual((Path(ng["cache"]) / "xy" / "000041.grid").read_bytes(), b"grid41")
            # a second run reads only its own part of the log: nothing failed this time
            again = self.call("trace", {"volume": str(vol), "seed": [24, 24, 32], "seed_check": False,
                                        "normal_grids": url, "out": res["out"]}, self.context(KIT_VC3D_RELAY="0"))
        self.assertEqual(again["normal_grids"]["fetch_failed"], 0)

    def test_refetch_stops_asking_when_everything_fails(self):
        import urllib.error
        calls = []

        def down(req, timeout=None):
            calls.append(req.full_url)
            raise urllib.error.URLError("network is unreachable")
        info = {"source": "https://bucket.invalid/g", "cache": str(self.d / "c")}
        rels = [f"xy/{i:06d}.grid" for i in range(8)]
        fetched, failed = vc3d_agent.refetch_grids(info, rels, down, sleep=lambda s: None, give_up=2)
        self.assertEqual((fetched, len(failed)), ([], 8))
        self.assertEqual(len(calls), 2 * vc3d_agent.GRID_REFETCH_TRIES)
        self.assertIn("not asked", failed["xy/000007.grid"])

    def test_trace_explains_empty_results(self):
        vol = self.volume(fakes.sheet)
        src = self.surface()
        nothing = self.call("trace", {"volume": str(vol), "mode": "gen_neighbor", "resume": str(src)})
        self.assertEqual(nothing["surfaces"][0]["valid_vertices"], 0)
        self.assertIn("neighbor_max_distance", nothing["note"])
        found = self.call("trace", {"volume": str(vol), "mode": "gen_neighbor", "resume": str(src),
                                    "params": {"neighbor_max_distance": 40}})
        self.assertEqual((found["surfaces"][0]["bbox_xyz"][0][2], "note" in found), (44.0, False))
        empty = self.call("trace", {"volume": "https://example.invalid/pred.zarr"}, self.context(FAKE_TRACE_EMPTY=1))
        self.assertIn("wrote no surface", empty["note"])

    def test_remote_runs_go_through_the_relay_and_repair_false_empty_chunks(self):
        vol, surf, log = self.volume(), self.surface(), self.d / "argv.log"
        with fakes.S3LikeServer(self.d, false=1) as srv:
            url = srv.url + "/vol.zarr"
            # the fake renderer leaves two markers for chunk 0/0/0/0, which exists, on its first run only
            ctx = self.context(KIT_VC3D_RELAY="1", FAKE_REMOTE_MAP=json.dumps({"/vol.zarr": str(vol)}),
                               FAKE_EMPTY_MARKERS=json.dumps(["level_0/0/0/0.empty", "0/0/0/0.empty"]),
                               FAKE_EMPTY_ONCE=self.d / "once", FAKE_LOG=log)
            self.addCleanup(ctx.close)
            res = self.call("render", {"surface": str(surf), "volume": url, "layers": 3, "format": "tif"}, ctx)
            cache = res["cache"]
            self.assertEqual((res["exit"], cache["runs"], cache["false_deleted"], "warning" in cache), (0, 2, 2, False))
            given = cache["relay"]["vc3d_url"]
            self.assertTrue(given.startswith("http://127.0.0.1:") and given.endswith("/vol.zarr") and given != url)
            runs = [json.loads(line) for line in log.read_text().splitlines() if '"--remote-url"' in line]
            self.assertEqual([r[r.index("--remote-url") + 1] for r in runs], [given, given])
            self.assertEqual(vc3d_cache.markers(cache["cache"]), [])
            self.assertEqual(json.loads(Path(res["receipt"]).read_text())["cache"]["runs"], 2)
            # with no reruns left, the result says the run may have read zeros
            ctx2 = self.context(KIT_VC3D_RELAY="1", FAKE_REMOTE_MAP=json.dumps({"/vol.zarr": str(vol)}),
                                FAKE_EMPTY_MARKERS=json.dumps(["level_0/0/1/0.empty"]))
            self.addCleanup(ctx2.close)
            res = self.call("render", {"surface": str(surf), "volume": url, "layers": 3, "format": "tif",
                                       "cache_reruns": 0}, ctx2)
            self.assertEqual(res["cache"]["read_as_empty"], ["level_0/0/1/0.empty"])
            self.assertIn("running it again reads them", res["cache"]["warning"])
            # a trace is given the relay's URL too, and reports instead of tracing again
            ctx3 = self.context(KIT_VC3D_RELAY="1", FAKE_TRACE_EMPTY=1, FAKE_LOG=log)
            self.addCleanup(ctx3.close)
            tr = self.call("trace", {"volume": url}, ctx3)
            traced = [json.loads(line) for line in log.read_text().splitlines() if '"-v"' in line][-1]
            self.assertEqual(traced[traced.index("-v") + 1], tr["cache"]["relay"]["vc3d_url"])
            # cache_check finds the relay's folder from the volume URL and repairs it
            folder = Path(tr["cache"]["cache"])
            (folder / "level_0" / "1" / "0").mkdir(parents=True, exist_ok=True)
            (folder / "level_0" / "1" / "0" / "0.empty").write_bytes(b"")
            chk = self.call("cache_check", {"volume": url})
            self.assertEqual((chk["false_found"], chk["false_deleted"]), (1, 1))
            listed = self.call("cache_check", {"all": True})
            self.assertTrue(all(v["url"] == url for v in listed["volumes"] if v.get("markers")))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("cache_check", {})

    def test_flatten(self):
        res = self.call("flatten", {"surface": str(self.surface()), "iterations": 3})
        self.assertEqual(res["exit"], 0)
        meta = json.loads((Path(res["out"]) / "meta.json").read_text())
        self.assertEqual((meta["flattened"], meta["iterations"]), (True, 3))
        self.assertEqual(res["surface"]["valid_vertices"], 81)
        self.assertTrue(Path(res["receipt"]).is_file())

    def test_inspect_every_kind(self):
        surf, vol = self.surface(), self.volume()
        self.assertEqual(self.call("inspect", {"path": str(surf), "voxel_um": 10})["area_cm2"], round(1024 * 1e-6, 4))
        z = self.call("inspect", {"path": str(vol)})
        self.assertEqual((z["kind"], z["levels"], z["dtype"], z["zarr_format"]), ("zarr", [("0", [64, 64, 64])], "u8", 2))
        render = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 3, "format": "tif"})
        folder = self.call("inspect", {"path": render["tif_dir"]})
        self.assertEqual((folder["kind"], folder["layers"], folder["height"]), ("layer folder", 3, 36))
        tif = self.call("inspect", {"path": str(Path(render["tif_dir"]) / "00.tif")})
        self.assertEqual((tif["kind"], tif["dtype"], tif["width"]), ("tiff", "u8", 36))
        self.assertEqual(folder["dtype"], "u8")
        self.assertEqual(self.call("inspect", {"path": render["receipt"]})["content"]["tool"], "render")
        (self.d / "notes.bin").write_bytes(b"1234")
        self.assertEqual(self.call("inspect", {"path": str(self.d / "notes.bin")}), {"kind": "file", "bytes": 4})
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("inspect", {"path": str(self.d / "missing")})

    def test_area_of_a_grid_over_the_sampling_threshold(self):
        # a plane tilted along x (z = x / 2) on 1501 x 1501 vertices 2 voxels apart: 2,253,001 vertices, over the
        # 2,000,000 read whole, so every second row and column is read. Its area is known exactly; each sampled
        # quad spans 2 x 2 cells, and multiplying by step squared again gave 4 times it
        n, s = 1501, 2.0
        p = self.d / "big.tifxyz"
        p.mkdir()
        grids = {"x": [s * c for _ in range(n) for c in range(n)], "y": [s * r for r in range(n) for _ in range(n)]}
        grids["z"] = [10 + v / 2 for v in grids["x"]]
        for a, g in grids.items():
            vc3d_io.write_tiff(p / f"{a}.tif", vc3d_io.Raster(n, n, "f32", vc3d_io.array.array("f", g)))
        (p / "meta.json").write_text(json.dumps({"scale": [0.5, 0.5], "format": "tifxyz", "type": "seg"}))
        true = (n - 1) * s * (n - 1) * s * math.sqrt(1.25)
        st = vc3d_agent.tifxyz_stats(p, voxel_um=10)
        self.assertEqual((st["grid_rows_cols"], st["sampled_every"]), ([n, n], 2))
        self.assertAlmostEqual(st["area_voxels2"], true, delta=0.1)
        self.assertEqual(st["area_cm2"], round(round(true, 1) * 1e-6, 4))
        self.assertAlmostEqual(st["edge_voxels"]["max"], s * math.sqrt(1.25), places=3)   # per cell, as unsampled
        # every vertex is valid, and each one read stands for its own block of vertices, cut short at the edges
        self.assertEqual(st["valid_vertices"], n * n)

    def test_a_malformed_scale_is_reported_not_raised(self):
        surf = fakes.write_tifxyz(self.d / "onescale.tifxyz", lambda r, c: (8 + 2 * c, 8 + 2 * r, 10.0), 8, 8)
        mf = Path(surf, "meta.json")
        for scale in ([0.25], {"x": 0.25}, "0.25"):
            mf.write_text(json.dumps({**json.loads(mf.read_text()), "scale": scale}))
            st = vc3d_agent.tifxyz_stats(surf)
            self.assertIn("is not two numbers", st["meta_scale_problem"])
            self.assertIsNone(st["grid_step_voxels"])
            self.assertNotIn("render_px_at_scale_1", st)
            self.assertGreater(st["area_voxels2"], 0)
        mf.write_text(json.dumps({**json.loads(mf.read_text()), "scale": [0.5, 0.5]}))
        st = vc3d_agent.tifxyz_stats(surf)
        self.assertNotIn("meta_scale_problem", st)
        self.assertEqual((st["grid_step_voxels"], st["render_px_at_scale_1"]), ([2.0, 2.0], [16, 16]))

    def test_sampled_and_whole_grids_give_one_area(self):
        # the same 61 x 61 tilted plane read whole and at every fourth vertex (max_vertices 400): one area, the true one
        surf = fakes.write_tifxyz(self.d / "tilted.tifxyz", lambda r, c: (8 + 2 * c, 8 + 2 * r, 10 + c),
                                  rows=61, cols=61)
        whole = vc3d_agent.tifxyz_stats(surf)
        sampled = vc3d_agent.tifxyz_stats(surf, max_vertices=400)
        self.assertEqual((whole["sampled_every"], sampled["sampled_every"]), (1, 4))
        true = round(120 * 120 * math.sqrt(1.25), 1)
        self.assertAlmostEqual(whole["area_voxels2"], true, delta=0.1)
        self.assertAlmostEqual(sampled["area_voxels2"], true, delta=0.1)

    def test_a_sampled_grid_leaves_out_its_last_row_and_column_strips(self):
        # a flat 62 x 62 grid at every second vertex (max_vertices 1000): 61 cells a side, so the last row of cells
        # and the last column are left out, 1 - (60 / 61) ** 2 = 3.252 % of the area. That is more than step / rows
        # (3.226 %) but within step / rows + step / cols, the bound the docs give
        surf = fakes.write_tifxyz(self.d / "flat62.tifxyz", fakes.plane(20, step=1.0), rows=62, cols=62)
        st = vc3d_agent.tifxyz_stats(surf, max_vertices=1000)
        self.assertEqual(st["sampled_every"], 2)
        lost = 1 - st["area_voxels2"] / (61 * 61)
        self.assertAlmostEqual(lost, 1 - (60 / 61) ** 2, places=6)
        self.assertAlmostEqual(round(100 * lost, 3), 3.252)
        self.assertGreater(lost, 2 / 62)
        # the bound holds on grids whose sides leave strips of every width, including a side shorter than the step
        for rows, cols, cap in ((62, 62, 1000), (47, 90, 500), (61, 61, 400), (30, 101, 300), (3, 400, 100),
                                (35, 35, 40)):
            with self.subTest(rows=rows, cols=cols):
                g = fakes.write_tifxyz(self.d / f"flat{rows}x{cols}.tifxyz", fakes.plane(20, step=1.0),
                                       rows=rows, cols=cols)
                st = vc3d_agent.tifxyz_stats(g, max_vertices=cap)
                k = st["sampled_every"]
                self.assertGreater(k, 1)
                kept = ((rows - 1) - (rows - 1) % k) * ((cols - 1) - (cols - 1) % k)
                self.assertAlmostEqual(st["area_voxels2"], kept, delta=0.1)
                self.assertLessEqual(1 - st["area_voxels2"] / ((rows - 1) * (cols - 1)), k / rows + k / cols)
                self.assertEqual(st["valid_vertices"], rows * cols)

    def test_valid_vertices_of_a_sampled_grid_count_each_block_once(self):
        # 61 x 61 at every fourth vertex: 16 x 16 vertices read, the last row and column of them standing for one
        # row or column of the grid, not four. Fully valid gives 3721 (it was 16 * 16 * 16 = 4096)
        full = fakes.write_tifxyz(self.d / "full61.tifxyz", fakes.plane(20), rows=61, cols=61)
        st = vc3d_agent.tifxyz_stats(full, max_vertices=400)
        self.assertEqual((st["sampled_every"], st["valid_vertices"], st["valid_fraction"]), (4, 61 * 61, 1.0))
        self.assertEqual(vc3d_agent.tifxyz_stats(full)["valid_vertices"], 61 * 61)
        # rows 32 to 60 invalid: 8 rows read stand for the 32 valid rows, so the count is exact (it was 2048)
        half = fakes.write_tifxyz(self.d / "half61.tifxyz", lambda r, c: None if r >= 32 else fakes.plane(20)(r, c),
                                  rows=61, cols=61)
        st = vc3d_agent.tifxyz_stats(half, max_vertices=400)
        self.assertEqual((st["sampled_every"], st["valid_vertices"]), (4, 32 * 61))
        self.assertEqual(vc3d_agent.tifxyz_stats(half)["valid_vertices"], 32 * 61)


def gradient(z, y, x):
    return min(255, 2 * x + 3 * z)


class TestPreview(Base):
    def png_of(self, res):
        h, w, channels, data = vc3d_io.read_png_gray(Path(res["png"]).read_bytes())
        self.assertEqual([h, w], res["shown_shape"])
        self.assertEqual(res["_images"], [res["png"]])
        return data

    def test_render_views(self):
        vol, surf = self.volume(gradient), self.surface()
        render = self.call("render", {"surface": str(surf), "volume": str(vol), "layers": 5, "format": "both"})
        res = self.call("preview", {"path": render["zarr"]})
        self.assertEqual((res["view"], res["level"], res["downsample"]), ("layer 2 of 5", "0", 1))
        data = self.png_of(res)
        self.assertLess(data[18 * 36 + 2], data[18 * 36 + 30])  # brighter to the right, as the volume
        coarse = self.call("preview", {"path": render["zarr"], "max_side": 16})
        self.assertEqual((coarse["level"], coarse["level_shape"], coarse["shown_shape"]), ("1", [5, 18, 18], [9, 9]))
        res = self.call("preview", {"path": render["zarr"], "mode": "max", "layers": [0, 5], "box": [0, 10, 0, 20],
                                    "range": [0, 255]})
        self.assertEqual((res["view"], res["shown_shape"], res["stretch"]), ("max over layers 0..4", [10, 20], [0, 255]))
        self.png_of(res)
        res = self.call("preview", {"path": render["tif_dir"], "layer": 0, "invert": True})
        self.assertEqual(res["view"], "layer 0 of 5 (00.tif)")
        self.png_of(res)
        self.assertIn("tifxyz z", self.call("preview", {"path": str(surf)})["view"])
        for args in ({"path": render["zarr"], "layer": 9}, {"path": render["zarr"], "level": "7"},
                     {"path": render["tif_dir"], "box": [100, 200, 0, 5]}):
            with self.subTest(args=args), self.assertRaises(vc3d_agent.ToolError):
                self.call("preview", args)
        with self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("preview", {"path": str(Path(render["out"]))})
        self.assertIn("no numbered layer TIFFs", str(err.exception))

    def test_maps_and_the_preregistration_guard(self):
        root = self.d / "repo"
        ctx = vc3d_agent.Context(root=root, env=self.env)
        maps = root / "experiments" / "probe" / "ink"
        maps.mkdir(parents=True)
        probs = vc3d_io.Raster(8, 8, "f32", vc3d_io.array.array("f", [i / 64 for i in range(64)]))
        vc3d_io.write_tiff(maps / "ink_f.tif", probs)
        with self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("preview", {"path": str(maps / "ink_f.tif")}, ctx)
        self.assertIn("preregister before looking", str(err.exception))
        ledger.init("probe", "PHerc0826", "does the probe work?", "ink in forward, not reverse", root=root / "experiments")
        res = self.call("preview", {"path": str(maps / "ink_f.tif"), "range": [0, 1]}, ctx)
        self.assertEqual((res["view"], res["values"]["max"]), ("image", 63 / 64))
        data = self.png_of(res)
        self.assertEqual((data[0], data[63]), (0, round(63 / 64 * 255)))
        npy = self.d / "m.npy"
        header = repr({"descr": "|u1", "fortran_order": False, "shape": (2, 3, 4)}).encode()
        header += b" " * (64 - (10 + len(header) + 1) % 64) + b"\n"
        npy.write_bytes(b"\x93NUMPY\x01\x00" + len(header).to_bytes(2, "little") + header + bytes(range(24)))
        res = self.call("preview", {"path": str(npy), "layer": 1})
        self.assertEqual((res["view"], res["values"]["min"], res["values"]["max"]), ("array", 12.0, 23.0))


class TestCheckSurface(Base):
    ARGS = {"half_layers": 16, "window": 24}

    def test_seated_and_unseated(self):
        vol = self.volume(fakes.sheet)
        seated = self.call("check_surface", {"surface": str(self.surface()), "volume": str(vol), **self.ARGS})
        seat = seated["seating"]
        self.assertEqual((seated["verdict"], seated["findings"]), ("ok", []), seated)
        self.assertEqual((seat["verdict"], seat["gap_layers"], seat["contrast"], seat["coverage"]), ("seated", 6, 180.0, 1.0))
        self.assertEqual(seated["selfcross"]["transverse"], 0)
        off = self.call("check_surface", {"surface": str(self.surface(z=26, name="off.tifxyz")), "volume": str(vol),
                                          "selfcross": False, **self.ARGS})
        self.assertEqual((off["verdict"], off["seating"]["verdict"]), ("look closer", "not seated"))
        self.assertNotIn("selfcross", off)

    def test_frame_search_finds_the_right_binning(self):
        vol = self.volume(fakes.sheet)
        doubled = fakes.write_tifxyz(self.d / "x2.tifxyz", fakes.plane(64, x0=16.0, step=8.0), scale=0.125)
        res = self.call("check_surface", {"surface": str(doubled), "volume": str(vol), "frame_search": True,
                                          **self.ARGS}, self.context(FAKE_SELFCROSS="dirty"))
        seat = res["seating"]
        self.assertEqual([c["scale_segmentation"] for c in seat["candidates"]], [1.0, 2.0, 4.0, 0.5, 0.25])
        self.assertEqual((seat["verdict"], seat["best_frame"], seat["better_frame"]), ("not seated", 0.5, 0.5))
        self.assertEqual(seat["margin_over_next"], 181.0)
        self.assertTrue(any("3 transverse" in f for f in res["findings"]))
        self.assertTrue(any("scale_segmentation 0.5" in f for f in res["findings"]))

    def test_windows_show_where_a_trace_leaves_its_sheet(self):
        vol = self.volume(fakes.sheet)
        # on the sheet (z 32) for columns 0 to 8, then 6 voxels off it, between windings (z 26)
        step = fakes.write_tifxyz(self.d / "step.tifxyz", lambda r, c: (4.0 + 3 * c, 4.0 + 3 * r, 32.0 if c < 9 else 26.0),
                                  rows=9, cols=17)
        res = self.call("check_surface", {"surface": str(step), "volume": str(vol), "windows": 3, "half_layers": 16,
                                          "window": 16, "selfcross": False})
        seat = res["seating"]
        wins = seat["windows"]
        # the central vertex, then the lattice cells (3 x 3 over rows 0 to 8, columns 0 to 16) farthest from it,
        # ties going to the cell farthest from all chosen so far: two opposite corners
        self.assertEqual([w["grid_row_col"] for w in wins], [[4, 8], [1, 3], [7, 13]])
        self.assertEqual([w["xyz"] for w in wins], [[28.0, 16.0, 32.0], [13.0, 7.0, 32.0], [43.0, 25.0, 26.0]])
        self.assertEqual([w["verdict"] for w in wins][1:], ["seated", "not seated"])
        self.assertEqual(seat["verdict"], "partly seated")
        self.assertTrue(any(f.startswith("seating: partly seated (") for f in res["findings"]), res["findings"])

    def test_s_local_and_depth_follow_the_voxel_size(self):
        vol = self.volume(fakes.sheet)
        res = self.call("check_surface", {"surface": str(self.surface()), "volume": str(vol), "s_local": True,
                                          "voxel_um": 9.362, "selfcross": False})
        seat = res["seating"]
        # 280 um is 30 layers at 9.362 um; S_local columns are 32 px; the sheet profile scores 9 everywhere
        # (see test_vc3d_seat.TestSLocal)
        self.assertEqual((seat["half_layers"], seat["window"], seat["voxel_um"], len(seat["windows"])), (30, 192, 9.362, 9))
        self.assertEqual((seat["s_local"]["s_local"], seat["s_local"]["columns"], seat["s_local"]["column_px"]), (9.0, 40, 32))
        self.assertEqual((seat["verdict"], seat["seated_windows"]), ("seated", "9 of 9"))
        deep = self.call("check_surface", {"surface": str(self.surface()), "volume": str(vol), "s_local": True,
                                           "voxel_um": 2.4, "windows": 1, "selfcross": False})["seating"]
        self.assertEqual((deep["half_layers"], deep["window"]), (117, 314))   # deeper than this 64-voxel volume
        with self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("check_surface", {"surface": str(self.surface()), "volume": str(vol), "s_local": True})
        self.assertIn("voxel size", str(err.exception))
        named = fakes.write_group(self.d / "20260101000000-2.400um-test.zarr", [8, 8, 8], fakes.ramp)
        self.assertEqual(vc3d_agent._voxel_for(self.ctx, str(named)), 2.4)

    def test_orientation_is_part_of_the_check(self):
        vol = self.volume(fakes.sheet)
        umb = self.d / "umb.txt"
        umb.write_text("0, 24, -100\n63, 24, -100\n")   # an axis far off at x = -100: the plane's +z normal does not vote
        res = self.call("check_surface", {"surface": str(self.surface()), "volume": str(vol), "umbilicus": str(umb),
                                          "selfcross": False, **self.ARGS})
        self.assertEqual((res["orientation"]["checked"], res["orientation"]["normal"]["confidence"]), (True, "ambiguous"))
        self.assertTrue(any(f.startswith("orientation: no clear normal sign") for f in res["findings"]))
        wall = fakes.write_tifxyz(self.d / "wall.tifxyz", lambda r, c: (40.0, 8.0 + 4 * (8 - c), 8.0 + 4 * r))
        umb.write_text("0, 24, 10\n63, 24, 10\n")
        res = self.call("check_surface", {"surface": str(wall), "umbilicus": str(umb), "selfcross": False})
        self.assertEqual(res["orientation"]["normal"]["vote"], "inward")
        self.assertTrue(any("+N points toward the centre" in f for f in res["findings"]))
        res = self.call("check_surface", {"surface": str(wall), "volume": str(vol), "selfcross": False, **self.ARGS})
        self.assertEqual(res["orientation"]["checked"], False)


class TestOrientation(Base):
    """render's team order follows the surface's own normal when an umbilicus is known. The surface is a wall
    of papyrus at x = 40, the axis runs along z at x = 10, and the volume brightens with x, so layers that step
    toward the centre darken."""

    def setUp(self):
        super().setUp()
        self.vol = self.volume(lambda z, y, x: min(255, 4 + 3 * x), name="xramp.zarr")
        self.umb = self.d / "umb.txt"
        self.umb.write_text("0, 32, 10\n63, 32, 10\n")

    def wall(self, name, mirrored=False):
        # columns along +y (or -y when mirrored), rows along +z: N = y x z = +x, away from the axis (or -x)
        return fakes.write_tifxyz(self.d / name, lambda r, c: (40.0, 8.0 + 4 * (8 - c if mirrored else c), 8.0 + 4 * r))

    def stack_of(self, result):
        return vc3d.read_layers(result["tif_dir"])

    def test_tool_reports_the_vote(self):
        res = self.call("orientation", {"surface": str(self.wall("w.tifxyz")), "umbilicus": str(self.umb)})
        self.assertEqual((res["normal"]["vote"], res["team_order"], res["umbilicus"]["points"]),
                         ("outward", "--flip-normals", 2))
        res = self.call("orientation", {"surface": str(self.wall("m.tifxyz", True)), "centre_xy": [10, 32]})
        self.assertEqual((res["normal"]["vote"], res["centre"], res["layout"]),
                         ("inward", "axis", "standard mirrored left to right (rows along +z, +N inward)"))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("orientation", {"surface": str(self.wall("w.tifxyz")), "umbilicus": str(self.d / "none.txt")})

    def test_render_team_order_follows_the_geometry(self):
        for name, mirrored in (("w.tifxyz", False), ("m.tifxyz", True)):
            res = self.call("render", {"surface": str(self.wall(name, mirrored)), "volume": str(self.vol), "layers": 5,
                                       "format": "tif", "umbilicus": str(self.umb)})
            # the wall's value is 4 + 3 x 40 = 124; team order starts 2 voxels out (x 42) and steps toward the centre
            self.assertEqual(middle(*self.stack_of(res)), [130, 127, 124, 121, 118], name)
            self.assertEqual((res["orientation"]["vote"], res["orientation"]["confidence"]),
                             ("inward" if mirrored else "outward", "clear"))
            receipt = json.loads(Path(res["receipt"]).read_text())
            self.assertEqual("--flip-normals" in receipt["steps"][0]["argv"], not mirrored)
            self.assertEqual(receipt["orientation"]["vote"], res["orientation"]["vote"])
        self.assertIn("no flag", res["order"])
        plain = self.call("render", {"surface": str(self.wall("m2.tifxyz", True)), "volume": str(self.vol), "layers": 5,
                                     "format": "tif"})
        # no umbilicus: VC3D's usual flag, which is wrong for a mirrored grid; the result says it was not checked
        self.assertEqual((plain["orientation"]["checked"], plain["order"]), (False, "team (--flip-normals)"))
        self.assertEqual(middle(*self.stack_of(plain)), [118, 121, 124, 127, 130])

    def test_a_cropped_render_votes_on_the_cropped_patch(self):
        # columns 0 to 8 run along +y at x = 40 (+N outward), 9 to 17 come back along -y at x = 46 (+N inward):
        # the whole surface has no clear sign, and the part a crop covers has one
        fold = fakes.write_tifxyz(self.d / "fold.tifxyz", lambda r, c: (40.0, 8.0 + 4 * c, 8.0 + 4 * r) if c <= 8
                                  else (46.0, 8.0 + 4 * (17 - c), 8.0 + 4 * r), cols=18)
        args = {"surface": str(fold), "volume": str(self.vol), "layers": 5, "format": "tif", "umbilicus": str(self.umb)}
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("render", args)
        res = self.call("render", dict(args, crop=[40, 8, 24, 16]))   # output pixels 4 to a grid step: columns 10 to 15
        self.assertEqual((res["orientation"]["vote"], res["orientation"]["confidence"], res["orientation"]["grid_box"]),
                         ("inward", "clear", [1, 7, 9, 17]))
        # no flag: +N is -x, so the layers step from x 48 toward the centre across the back sheet at 46 (142)
        self.assertEqual(middle(*self.stack_of(res)), [148, 145, 142, 139, 136])
        self.assertEqual(vc3d_agent.crop_grid_box(fold, {"crop": [40, 8, 24, 16], "scale": 2}), [0, 4, 4, 9])
        self.assertIsNone(vc3d_agent.crop_grid_box(fold, {}))

    def test_no_clear_sign_is_refused_unless_overridden(self):
        flat = self.surface()   # N along z: nothing votes
        args = {"surface": str(flat), "volume": str(self.vol), "layers": 3, "format": "tif", "umbilicus": str(self.umb)}
        with self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("render", args)
        self.assertIn("orientation_check=false", str(err.exception))
        res = self.call("render", dict(args, orientation_check=False))
        self.assertEqual((res["exit"], res["order"], res["orientation"]["checked"]), (0, "team (--flip-normals)", False))
        normal = self.call("render", dict(args, order="normal"))
        self.assertNotIn("orientation", normal)


class TestJobs(Base):
    def tearDown(self):
        for proc in list(vc3d_agent._children):
            proc.wait(timeout=30)
        vc3d_agent._reap()
        super().tearDown()

    def test_background_run_wait_and_log(self):
        job = self.call("run", {"tool": "vc_sleep", "args": ["0.3"], "background": True})
        self.assertEqual(job["status"], "running")
        done = self.call("jobs", {"action": "wait", "id": job["job"], "timeout": 60})
        self.assertEqual((done["status"], done["result"]["exit"]), ("succeeded", 0), done)
        self.assertIn("tick", done["result"]["log_tail"])
        self.assertIn("job succeeded", self.call("jobs", {"action": "log", "id": job["job"]})["log_tail"])
        self.assertEqual(self.call("jobs")["jobs"][0]["job"], job["job"])
        failed = self.call("run", {"tool": "vc_nope", "background": True})
        info = self.call("jobs", {"action": "wait", "id": failed["job"], "timeout": 60})
        self.assertEqual(info["status"], "failed")
        self.assertIn("not a vc_* tool", info["error"])

    def test_cancel_stops_a_child_that_ignores_sigterm(self):
        pid, child = self.d / "pid2", self.d / "child"
        job = self.call("run", {"tool": "vc_sleep", "args": ["60", "--pid", str(pid), "--stubborn-child", str(child)],
                                "background": True})
        deadline = time.time() + 30
        while not (pid.exists() and child.exists()) and time.time() < deadline:
            time.sleep(0.1)
        self.assertTrue(child.exists())
        self.assertEqual(self.call("jobs", {"action": "cancel", "id": job["job"]})["cancelled"], True)
        deadline = time.time() + 10
        while vc3d_bridge._alive(int(child.read_text())) and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse(vc3d_bridge._alive(int(child.read_text())))

    def test_cancel_stops_the_tool(self):
        pid = self.d / "pid"
        job = self.call("run", {"tool": "vc_sleep", "args": ["60", "--pid", str(pid)], "background": True})
        deadline = time.time() + 30
        while not pid.exists() and time.time() < deadline:
            time.sleep(0.1)
        self.assertTrue(pid.exists())
        waited = self.call("jobs", {"action": "wait", "id": job["job"], "timeout": 0})
        self.assertIn("still running", waited["waited"])
        self.assertEqual(self.call("jobs", {"action": "cancel", "id": job["job"]})["cancelled"], True)
        self.assertEqual(self.call("jobs", {"action": "status", "id": job["job"]})["status"], "cancelled")
        deadline = time.time() + 10
        while vc3d_bridge._alive(int(pid.read_text())) and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse(vc3d_bridge._alive(int(pid.read_text())))
        self.assertFalse(self.call("jobs", {"action": "cancel", "id": job["job"]})["cancelled"])
        for args in ({"action": "status"}, {"action": "status", "id": "no-such-job"}):
            with self.assertRaises(vc3d_agent.ToolError):
                self.call("jobs", args)


class TestPassthroughs(Base):
    def test_kit_and_modal(self):
        res = self.call("kit", {"args": ["vc3d", "env", "--threads", "2"]})
        self.assertEqual(res["exit"], 0)
        self.assertIn("OMP_NUM_THREADS=2", res["output"])
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("kit", {"args": ["vc3d", "mcp"]})
        with self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("modal", {"entrypoint": "selftest"})
        self.assertIn("KIT_ALLOW_MODAL", str(err.exception))


class TestData(Base):
    def setUp(self):
        super().setUp()
        (self.home / "cache").mkdir(parents=True)
        (self.home / "cache" / "open-data-metadata.json").write_text(json.dumps(CATALOG))

    def test_catalog(self):
        self.assertEqual([s["sample"] for s in self.call("catalog", {"action": "samples"})["samples"]],
                         ["PHercOther", "PHercTest"])
        vols = self.call("catalog", {"action": "volumes", "sample": "PHercTest"})["volumes"]
        self.assertEqual([v["volume"] for v in vols], ["V1", "V2"])
        segs = self.call("catalog", {"action": "segments", "sample": "PHercTest", "query": "w002"})
        self.assertEqual(segs["total"], 2)
        self.assertEqual(self.call("catalog", {"action": "segment", "sample": "PHercTest", "segment": "w001"})["frames"], ["V2"])
        self.assertEqual(len(self.call("catalog", {"action": "transforms", "sample": "PHercTest"})["transforms"]), 2)
        self.assertEqual(self.call("catalog", {"action": "models"})["models"][0]["model"], "M1")
        for args in ({"action": "volumes"}, {"action": "volumes", "sample": "PHerc9999"},
                     {"action": "segment", "sample": "PHercTest"}):
            with self.subTest(args=args), self.assertRaises(vc3d_agent.ToolError):
                self.call("catalog", args)

    def test_catalog_umbilicus_for_an_open_data_volume(self):
        url = f"{vc3d_catalog.BUCKET_URL}/PHercTest/volumes/V2-2.4um.zarr"
        cached = self.home / "cache" / "umbilicus" / "V2-umbilicus.json"
        cached.parent.mkdir(parents=True)
        cached.write_text(json.dumps({"control_points": [{"x": 10, "y": 32, "z": 0}, {"x": 10, "y": 32, "z": 63}]}))
        wall = fakes.write_tifxyz(self.d / "w.tifxyz", lambda r, c: (40.0, 8.0 + 4 * c, 8.0 + 4 * r))
        res = self.call("orientation", {"surface": str(wall), "volume": url})
        self.assertEqual((res["normal"]["vote"], res["umbilicus"]["from"]), ("outward", "catalog"))
        self.assertTrue(res["umbilicus"]["source"].endswith("/PHercTest/representations/umbilicus/V2-umbilicus.json"))
        vol = fakes.write_group(self.d / "xramp.zarr", [64, 64, 64], lambda z, y, x: min(255, 4 + 3 * x))
        ctx = self.context(FAKE_REMOTE_MAP=json.dumps({url: str(vol)}))
        mirrored = fakes.write_tifxyz(self.d / "m.tifxyz", lambda r, c: (40.0, 8.0 + 4 * (8 - c), 8.0 + 4 * r))
        res = self.call("render", {"surface": str(mirrored), "volume": url, "layers": 5, "format": "tif"}, ctx)
        self.assertEqual((res["orientation"]["vote"], res["orientation"]["umbilicus"]["from"]), ("inward", "catalog"))
        self.assertEqual(middle(*vc3d.read_layers(res["tif_dir"])), [130, 127, 124, 121, 118])
        # a local volume the catalog does not know: no umbilicus, and a flat wall gives no circle to fit either
        with self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("orientation", {"surface": str(wall), "volume": str(vol)})
        self.assertIn("no umbilicus or centre_xy given", str(err.exception))
        arc = fakes.write_tifxyz(self.d / "arc.tifxyz", lambda r, c: (10 + 30 * math.cos(c / 4), 32 + 30 * math.sin(c / 4),
                                                                       8.0 + 4 * r))
        other = self.call("orientation", {"surface": str(arc), "volume": str(vol)})
        self.assertEqual((other["centre"], other["normal"]["vote"], other["umbilicus"]["used"]),
                         ("fitted circle (an estimate)", "outward", False))

    def test_render_reads_the_voxel_size_from_the_catalog(self):
        url = f"{vc3d_catalog.BUCKET_URL}/PHercTest/volumes/V1-9.362um-test.zarr/"
        self.assertEqual(vc3d_agent._catalog_voxel(self.ctx, url), 9.362)
        self.assertIsNone(vc3d_agent._catalog_voxel(self.ctx, "https://example.org/x.zarr"))

    def test_fetch_segment(self):
        got = []

        def fake_fetch(prefix, dest, workers=8):
            got.append(prefix)
            fakes.write_tifxyz(Path(dest), fakes.plane(32))
            return 4, 4, 4096

        with mock.patch.object(fetch, "fetch_prefix", fake_fetch):
            res = self.call("fetch_segment", {"sample": "PHercTest", "segment": "w001_abc", "frame": "V2"})
        self.assertEqual(got, ["PHercTest/segments/S1-w001_abc/on-V2/tifxyz"])
        self.assertEqual(Path(res["surface"]), self.home / "segments" / "PHercTest" / "S1-w001_abc-on-V2.tifxyz")
        self.assertEqual((res["stats"]["valid_vertices"], res["bytes"]), (81, 4096))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("fetch_segment", {"sample": "PHercTest", "segment": "w001_abc", "frame": "V9"})

    def test_models_and_fetch_model(self):
        ckpt = self.d / "model.pth"
        ckpt.write_bytes(b"w")
        self.call("models", {"action": "add", "name": "mine", "engine": "villa", "checkpoint": str(ckpt), "notes": "test"})
        self.call("models", {"action": "add", "name": "snap", "engine": "v8in", "model_dir": str(self.d)})
        self.assertEqual(sorted(self.call("models")["models"]), ["mine", "snap"])
        self.assertEqual(self.call("models", {"action": "remove", "name": "snap"})["removed"]["engine"], "v8in")
        self.assertIn("v8in", self.call("models", {"action": "known"})["known"])
        for args in ({"action": "add", "name": "x"}, {"action": "add", "name": "x", "engine": "villa"},
                     {"action": "remove"}):
            with self.subTest(args=args), self.assertRaises(vc3d_agent.ToolError):
                self.call("models", args)

        def fake_fetch_model(name, dest, log=print, opener=None):
            Path(dest).mkdir(parents=True, exist_ok=True)
            (Path(dest) / "w.pth").write_bytes(b"w")
            return {"model": name, "repo": "scrollprize/ink_9um", "revision": "main", "resolved_commit": "abc",
                    "dest": str(dest), "files": [], "engine": "villa", "checkpoint": str(Path(dest) / "w.pth"),
                    "model_dir": None}

        with mock.patch.object(vc3d_catalog, "fetch_model", fake_fetch_model):
            self.call("fetch_model", {"name": "ink_9um-seed42", "dest": str(self.d / "ckpt")})
        entry = self.call("models")["models"]["ink_9um-seed42"]
        self.assertEqual((entry["revision"], entry["source"], entry["checkpoint"]),
                         ("abc", "scrollprize/ink_9um", str(self.d / "ckpt" / "w.pth")))
        self.assertTrue((self.d / "ckpt" / "kit-download.json").is_file())
        with mock.patch.object(vc3d_catalog, "fetch_model", side_effect=OSError("no route to host")), \
                self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("fetch_model", {"name": "v8in", "dest": str(self.d / "v8in")})
        self.assertIn("huggingface.co reachable", str(err.exception))


class TestInk(Base):
    def model(self):
        script = self.d / "ink_model.py"
        script.write_text(fakes.INK_MODEL)
        return [sys.executable, str(script), "{layers}", "{output}", "{reverse}"]

    def test_rules_are_enforced_before_anything_runs(self):
        inp = self.d / "layers"
        inp.mkdir()
        cases = [
            ({"purpose": "benchmark", "variants": ["f"], "engine": "command", "command": ["x"]}, "reverse-depth control"),
            ({"purpose": "target", "engine": "command", "command": ["x"]}, "needs experiment"),
            ({"purpose": "target", "experiment": "unknown-slug", "engine": "command", "command": ["x"]}, "Preregister"),
            ({"purpose": "smoke"}, "say which model"),
            ({"purpose": "smoke", "model": "nothing"}, "no registered model"),
            ({"purpose": "smoke", "engine": "villa"}, "needs checkpoint"),
            ({"purpose": "smoke", "engine": "v8in"}, "needs model_dir"),
        ]
        for args, message in cases:
            with self.subTest(args=args), self.assertRaises(vc3d_agent.ToolError) as err:
                self.call("ink", {"input": str(inp), **args})
            self.assertIn(message, str(err.exception))
        self.assertFalse((self.home / "ink").exists())

    def test_render_receipt_warnings(self):
        surf, vol = self.surface(), self.volume(levels=2, binned="zyx")
        info, warnings = vc3d_agent.render_provenance(
            self.call("render", {"surface": str(surf), "volume": str(vol), "format": "tif", "layers": 3,
                                 "level": 1, "voxel_um": 2.4})["tif_dir"])
        self.assertEqual((info["level"], info["voxel_um"], info["order_checked"]), (1, 2.4, False))
        self.assertIn("2x downsampled", warnings[0])
        self.assertIn("not checked against an umbilicus", warnings[1])
        _, warnings = vc3d_agent.render_provenance(
            self.call("render", {"surface": str(surf), "volume": str(vol), "format": "tif", "layers": 3,
                                 "order": "normal"})["tif_dir"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("not the team order", warnings[0])
        self.assertEqual(vc3d_agent.render_provenance(self.d), (None, []))

    @unittest.skipUnless(HAVE_NUMPY, "the ink script needs numpy")
    def test_forward_and_controls_on_a_render(self):
        # the textured ramp, since the ink script refuses a map of one value on the surface
        render = self.call("render", {"surface": str(self.surface()), "volume": str(self.volume(fakes.textured_ramp)),
                                      "format": "tif"})
        res = self.call("ink", {"input": render["tif_dir"], "purpose": "smoke", "engine": "command",
                                "command": self.model(), "variants": ["f", "r", "s"]})
        self.assertEqual(res["exit"], 0, res.get("log_tail"))
        self.assertEqual(sorted(res["maps"]), ["f", "r", "s"])
        # team order puts the brighter (deeper) half of the ramp first: the model calls all of it ink
        # forward, none of it reversed, and the depth shuffle lands in between
        self.assertEqual(res["maps"]["f"]["stats"]["above_threshold"], 1.0)
        self.assertEqual(res["comparison"]["r"]["above_threshold"]["control"], 0.0)
        self.assertEqual(res["comparison"]["r"]["forward_minus_control"], 1.0)
        self.assertIn("s", res["comparison"])
        self.assertIn("not a reading", res["note"])
        self.assertEqual((res["render"]["level"], res["render"]["order"]), (0, "team (--flip-normals)"))
        self.assertEqual(len(res["warnings"]), 1)   # the order was not checked: no umbilicus here
        self.assertFalse((Path(res["out"]) / "work").exists())
        receipt = json.loads(Path(res["receipt"]).read_text())
        self.assertEqual(receipt["engine"]["engine"], "command")
        # the device asked for, and the one the engine named (the stand-in names none)
        self.assertEqual(res["device"], {"asked": "cpu", "reported": None})
        self.assertEqual(receipt["device"], res["device"])
        look = self.call("preview", {"path": res["maps"]["f"]["path"], "range": [0, 1]})
        # 28 layers 1 voxel apart in a ramp of 3 per voxel: the front half is 42 brighter on the surface, less the
        # texture (0 to 2, and 0 at some pixels); off it both halves are 0 and the model says 0.5
        self.assertAlmostEqual(look["values"]["max"], 1 / (1 + math.exp(-42 / 8)), places=5)
        self.assertEqual(look["values"]["min"], 0.5)
        self.assertLess(res["maps"]["f"]["stats"]["p50"], res["maps"]["f"]["stats"]["p99"])  # it varies on the surface

    @unittest.skipUnless(HAVE_NUMPY, "the ink script needs numpy")
    def test_target_runs_go_to_the_experiment(self):
        root = self.d / "repo"
        ctx = vc3d_agent.Context(root=root, env=self.env)
        ledger.init("t1", "PHerc0826", "is there ink here?", "ink in forward, not in reverse", root=root / "experiments")
        render = self.call("render", {"surface": str(self.surface()), "volume": str(self.volume(fakes.textured_ramp)),
                                      "format": "tif", "layers": 6})
        args = {"input": render["tif_dir"], "purpose": "target", "experiment": "t1", "engine": "command",
                "command": self.model()}
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("ink", dict(args, out=str(root / "work" / "elsewhere")), ctx)
        res = self.call("ink", args, ctx)
        self.assertEqual(res["exit"], 0, res.get("log_tail"))
        self.assertTrue(Path(res["out"]).is_relative_to(root / "experiments" / "t1" / "ink"))
        record = ledger.load("t1", root=root / "experiments")
        self.assertEqual(len(record["provenance"]), 1)
        self.assertEqual(sorted(Path(p).name for p in record["provenance"][0]["sha256"]), ["ink_f.tif", "ink_r.tif"])
        ledger.set_status("t1", "null", root=root / "experiments")
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("ink", args, ctx)

    @unittest.skipUnless(HAVE_NUMPY, "the probe needs numpy")
    def test_detectability(self):
        selftest = self.call("detectability", {"self_test": True})
        self.assertEqual((selftest["exit"], selftest["verdict"]), (0, "PASS"))
        render = self.call("render", {"surface": str(self.surface()), "volume": str(self.volume(fakes.sheet)),
                                      "format": "tif", "layers": 21})
        res = self.call("detectability", {"stack": render["tif_dir"], "purpose": "smoke", "engine": "command",
                                          "command": self.model(), "micron_per_pixel": 200, "amplitudes": [4, 8]})
        self.assertEqual(res["exit"], 0, res.get("log_tail"))
        # the stand-in model reads ink as a brighter near half: strokes planted on the near face come back
        # at the smallest contrast, on the far face never
        self.assertEqual((res["verdict"], res["sensitivity"]), ("sensitive", 4.0))
        self.assertIsNone(res["faces"]["far"]["sensitivity"])
        self.assertEqual(res["model_runs"], 5)
        strided = self.call("detectability", {"stack": render["tif_dir"], "purpose": "smoke", "engine": "command",
                                              "command": self.model(), "micron_per_pixel": 200, "amplitudes": [4],
                                              "face": "near", "stride": 32})
        argv = json.loads(Path(strided["receipt"]).read_text())["steps"][0]["argv"]
        self.assertEqual(argv[argv.index("--stride") + 1], "32")
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("detectability", {"stack": render["tif_dir"], "engine": "command", "command": self.model()})


class TestApp(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(lambda: vc3d_bridge.App(self.home).stop(grace=5))

    def test_drive_the_app(self):
        project = self.d / "scroll.volpkg"
        project.mkdir()
        rec = self.call("app_start", {"name": "kit-test", "open": str(project), "timeout": 30})
        self.assertEqual((rec["name"], rec["ping"], rec["opened"]), ("kit-test", {"pong": True}, {"opened": str(project)}))
        self.assertTrue(self.call("app_start", {})["already_running"])
        state = self.call("app_call", {"method": "state.get"})
        self.assertEqual((state["volume"], state["platform"], state["display"]), (str(project), "offscreen", None))
        methods = self.call("app_methods")
        self.assertEqual(methods["count"], 5)
        shot = next(m for m in methods["methods"] if m["method"] == "screenshot.capture")
        self.assertEqual((shot["mcp_tool"], shot["params"]), ("vc3d_screenshot", {"target": "string", "maxDim": "integer"}))
        self.assertEqual(self.call("app_methods", {"prefix": "volume."})["methods"][0]["required"], ["path"])
        img = self.call("app_screenshot", {"max_dim": 64})
        self.assertEqual(vc3d_io.read_png_gray(Path(img["png"]).read_bytes())[:2], (4, 6))
        self.assertEqual(img["_images"], [img["png"]])
        self.assertTrue(img["base64"].startswith("(saved to"))
        for method, code in (("no.such.method", "-32601"), ("volume.open", "-32004")):
            with self.subTest(method=method), self.assertRaises(vc3d_agent.ToolError) as err:
                self.call("app_call", {"method": method, "params": {"path": str(self.d / "missing")}})
            self.assertIn(code, str(err.exception))
        self.assertTrue(self.call("app_stop")["stopped"])
        with mock.patch.object(vc3d_bridge, "discover", return_value=None), self.assertRaises(vc3d_agent.ToolError) as err:
            self.call("app_call", {"method": "ping"})
        self.assertIn("app_start", str(err.exception))
        self.assertFalse(self.call("app_stop")["stopped"])

    def test_bridge_client(self):
        self.assertEqual(vc3d_bridge.parse_handshake("x\nVC3D-AGENT-BRIDGE: listening name=a path=/s/b.sock\n"),
                         ("a", "/s/b.sock"))
        self.assertIsNone(vc3d_bridge.parse_handshake("Qt: no display"))
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        reg = self.d / "registry"
        reg.mkdir()
        for name, pid, path, started in (("a", os.getpid(), "/a.sock", 1000), ("b", os.getpid(), "/b.sock", 2000),
                                         ("c", dead.pid, "/c.sock", 3000)):
            (reg / f"{name}.json").write_text(json.dumps({"pid": pid, "path": path, "startedAt": started}))
        (reg / "broken.json").write_text("{")
        self.assertEqual(vc3d_bridge.discover(reg)["path"], "/b.sock")
        self.assertIsNone(vc3d_bridge.discover(self.d / "none"))

        sock_dir = tempfile.mkdtemp(prefix="vcb", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(lambda: __import__("shutil").rmtree(sock_dir, ignore_errors=True))
        path = os.path.join(sock_dir, "s")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(4)
        self.addCleanup(server.close)

        def serve():
            for behaviour in ("silent", "close"):
                conn, _ = server.accept()
                conn.recv(4096)
                if behaviour == "silent":
                    time.sleep(1.5)
                conn.close()

        threading.Thread(target=serve, daemon=True).start()
        with self.assertRaises(TimeoutError):
            vc3d_bridge.call(path, "ping", timeout=0.5)
        with self.assertRaises(vc3d_bridge.BridgeError) as err:
            vc3d_bridge.call(path, "ping", timeout=5)
        self.assertEqual(err.exception.code, -32010)


class TestCli(Base):
    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["vc3d", *argv])
        return code, out.getvalue()

    def test_tools_and_call(self):
        code, text = self.run_cli("tools")
        self.assertEqual(code, 0)
        self.assertRegex(text, r"(?m)^render +Render the layer stack along a tifxyz surface")
        code, text = self.run_cli("tools", "--json")
        listed = json.loads(text)
        self.assertEqual((code, len(listed)), (0, len(vc3d_agent.TOOLS)))
        self.assertGreaterEqual(len(listed), N_CORE_TOOLS)
        self.assertEqual(listed[0]["inputSchema"]["type"], "object")
        surf = self.surface()
        code, text = self.run_cli("call", "inspect", json.dumps({"path": str(surf)}))
        self.assertEqual((code, json.loads(text)["kind"]), (0, "tifxyz"))
        args = self.d / "args.json"
        args.write_text(json.dumps({"tool": "vc_sleep", "args": ["0", "--exit", "3"]}))
        code, text = self.run_cli("call", "run", f"@{args}")
        self.assertEqual((code, json.loads(text)["exit"]), (1, 3))
        code, text = self.run_cli("call", "jobs", '{"action": "status"}')
        self.assertEqual(code, 2)
        self.assertIn("needs id", json.loads(text)["error"])
        self.assertEqual(self.run_cli("call", "inspect", "{not json")[0], 2)
        code, text = self.run_cli("call", "run", '{"tool": "vc_sleep", "args": ["0"]}', "--background")
        job = json.loads(text)["job"]
        done = self.call("jobs", {"action": "wait", "id": job, "timeout": 60})
        self.assertEqual(done["status"], "succeeded")

    def test_app_mcp_finds_villa_and_execs_it(self):
        villa = self.d / "villa"
        run = villa / "volume-cartographer" / "tools" / "vc3d-mcp" / "run.sh"
        run.parent.mkdir(parents=True)
        run.write_text("#!/bin/bash\n")
        self.assertEqual(vc3d.find_villa_mcp(None, villa), run)
        self.assertEqual(vc3d.find_villa_mcp(None, None, {"VILLA_DIR": str(villa)}), run)
        build = vc3d.Tools("VC_BIN", villa / "volume-cartographer" / "build" / "bin")
        self.assertEqual(vc3d.find_villa_mcp(build, None, {}), run)
        tools = vc3d.Tools("VC_BIN", self.bin)
        parser = cli.build_parser()
        args = parser.parse_args(["vc3d", "app-mcp", "--villa", str(villa), "--", "--volpkg", "/data/x.volpkg"])
        with mock.patch.object(os, "execvpe") as execvpe, mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
            vc3d.app_mcp(args, tools)
        prog, argv, env = execvpe.call_args[0]
        self.assertEqual(argv, ["bash", str(run), "--launch", str(self.bin / "VC3D"), "--volpkg", "/data/x.volpkg"])
        self.assertEqual((env["QT_QPA_PLATFORM"], env["VC3D_BINARY"], "DISPLAY" in env), ("offscreen", str(self.bin / "VC3D"), False))
        with contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(vc3d, "find_villa_mcp", return_value=None):
                self.assertEqual(vc3d.app_mcp(args, tools), 2)
            self.assertEqual(vc3d.app_mcp(args, vc3d.Tools("VC_BIN", self.d)), 2)


if __name__ == "__main__":
    unittest.main()
