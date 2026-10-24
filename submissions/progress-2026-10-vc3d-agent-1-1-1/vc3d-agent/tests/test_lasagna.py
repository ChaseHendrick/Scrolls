"""Tests for kit.lasagna (`python -m kit lasagna`, the lasagna_* agent tools) and scripts/lasagna/fit_cpu_shim.py.

villa's lasagna is replaced by a stand-in folder (make_villa): a fit.py that merges its JSON arguments as villa's
does, loads its volume through fit_data.load_3d_streaming, prints PROGRESS lines and writes the out-dir layout
(snapshots, model_final.pt, tifxyz/winding_0000.tifxyz); a fit2tifxyz.py; a fit_data.py whose streaming loader
fails off CUDA as villa's does; and a torch package with just what the shim and the probe touch. So the real shim
runs, without torch, and what is checked is the layer above villa: arguments, merge order, the CPU crop, refusals,
the readout, the export, receipts, the manifest mirror, the fit service client and the command line. villa's fit
itself is checked by `kit lasagna selftest` on a machine with villa (docs/lasagna-agents.md).
"""
import contextlib
import http.client
import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import cli, lasagna, vc3d_agent  # noqa: E402

ROOT = fakes.ROOT
HAVE_DATA_STACK = all(importlib.util.find_spec(m) is not None for m in ("numpy", "zarr", "tifffile"))

FIT = f'''import json, os, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
import fit_data
from kit import vc3d_io


def merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def grids(path):
    return [vc3d_io.read_tiff(Path(path) / f"{{a}}.tif") for a in "xyz"]


def write(path, rows, cols, xs, ys, zs, meta):
    path.mkdir(parents=True, exist_ok=True)
    for a, g in zip("xyz", (xs, ys, zs)):
        vc3d_io.write_tiff(path / f"{{a}}.tif", vc3d_io.Raster(rows, cols, "f32", __import__("array").array("f", g)))
    (path / "meta.json").write_text(json.dumps(meta))


def main(argv):
    configs = [a for a in argv if a.endswith(".json")]
    flags = [a for a in argv if not a.endswith(".json")]
    if flags:
        print("fit.py: error: unrecognized arguments: " + " ".join(flags), file=sys.stderr)
        return 2
    cfg = {{}}
    for c in configs:
        cfg = merge(cfg, json.loads(Path(c).read_text()))
    args = {{k.lstrip("-").replace("_", "-"): v for k, v in cfg.get("args", {{}}).items()}}   # villa's cli_json
    out = Path(args["out-dir"])
    out.mkdir(parents=True, exist_ok=True)
    if os.environ.get("FAKE_FIT_FAIL"):
        print("Traceback (most recent call last):")
        print(os.environ["FAKE_FIT_FAIL"])
        return 1
    loaded = None
    if args.get("model-init") != "flatten":
        loaded = fit_data.load_3d_streaming(path=args["input"], device=args.get("device", "cuda"))
    (out / "fake_seen.json").write_text(json.dumps({{"argv": argv, "cfg": cfg, "loaded": loaded, "cwd": os.getcwd()}}))
    steps = sum(int(s.get("steps", 0)) for s in cfg.get("stages", []))
    for i in range(1, steps + 1):
        print(f"PROGRESS {{i}} {{steps}} {{1.0 / i:.6f}}", flush=True)
    (out / "model_snapshots").mkdir(exist_ok=True)
    for i, st in enumerate(cfg.get("stages", [])):       # villa names snapshots by stage; run order is by time
        snap = out / "model_snapshots" / f"model_{{st.get('name', i)}}_{{int(st.get('steps', 0)):06d}}.pt"
        snap.write_bytes(b"fake")
        os.utime(snap, (1_700_000_000 + i, 1_700_000_000 + i))
    (out / "model_final.pt").write_bytes(b"fake")
    start = args.get("tifxyz-init")
    if start:
        x, y, z = grids(start)
        rows, cols, xs, ys, zs = x.h, x.w, list(x.data), list(y.data), list(z.data)
    else:
        sx, sy, sz = args.get("seed") or (32, 32, 32)
        rows = cols = 3
        xs = [sx + 4 * (c - 1) for r in range(3) for c in range(3)]
        ys = [sy] * 9
        zs = [sz + 4 * (r - 1) for r in range(3) for c in range(3)]
    if float((cfg.get("base") or {{}}).get("normal", 0)) > 0 and not os.environ.get("FAKE_FIT_IGNORE_NORMAL"):
        mean = sum(ys) / len(ys)
        ys = [mean] * len(ys)       # the normal term turns the start surface to the sheets: flat in y
    write(out / "tifxyz" / "winding_0000.tifxyz", rows, cols, xs, ys, zs,
          {{"format": "tifxyz", "type": "seg", "uuid": "fake", "scale": [0.25, 0.25]}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

FIT_DATA = '''def load_3d_streaming(*, path, device, skip_channels=None, sparse_prefetch_backend="tensorstore",
                      require_umbilicus=False):
    if str(getattr(device, "type", device)).startswith("cuda"):
        return {"loader": "streaming", "device": "cuda"}
    raise RuntimeError("torch.cuda.Stream requires CUDA support")


def load_3d(*, path, device, crop=None, cuda_gridsample=True, skip_channels=None, require_umbilicus=False):
    return {"loader": "dense", "device": str(getattr(device, "type", device)), "crop": list(crop) if crop else None,
            "cuda_gridsample": cuda_gridsample}
'''

TORCH = '''import os
__version__ = "0.0+fake"


class device:
    def __init__(self, text):
        self.type = str(text).split(":")[0]

    def __str__(self):
        return self.type


class cuda:
    @staticmethod
    def is_available():
        return os.environ.get("FAKE_CUDA") == "1"

    @staticmethod
    def device_count():
        return 1 if cuda.is_available() else 0

    @staticmethod
    def get_device_name(i):
        return "Fake GPU"


class backends:
    class mps:
        @staticmethod
        def is_available():
            return False
'''

EXPORT = f'''import json, os, sys, array
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from kit import vc3d_io


def main():
    argv = sys.argv[1:]
    opts = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    out = Path(opts["output"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "fake_export_argv.json").write_text(json.dumps(argv))
    if os.environ.get("FAKE_EXPORT_FAIL"):
        print("RuntimeError: export failed")
        sys.exit(1)
    name = opts.get("output-name", "agent.tifxyz") if "--single-segment" in argv else "winding_0000.tifxyz"
    t = out / name
    t.mkdir(parents=True, exist_ok=True)
    for a, g in (("x", [8, 12, 8, 12]), ("y", [32] * 4), ("z", [8, 8, 12, 12])):
        vc3d_io.write_tiff(t / f"{{a}}.tif", vc3d_io.Raster(2, 2, "f32", array.array("f", g)))
    meta = {{"format": "tifxyz", "type": "seg", "uuid": name, "scale": [0.25, 0.25]}}
    if "voxel-size-um" in opts:
        meta["area_vx2"], meta["area_cm2"] = 16.0, 16 * (float(opts["voxel-size-um"]) * 1e-4) ** 2
    (t / "meta.json").write_text(json.dumps(meta))


if __name__ == "__main__":
    main()
'''

# The self-test's data step, standard library only: the same files scripts/lasagna/selftest_data.py writes, with
# only the level arrays' metadata (the stand-in fit never reads voxels; kit sizes the dense load from it).
SELFTEST_DATA = f'''import array, json, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from kit import vc3d_io
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
n = 64
(out / "vol.lasagna.json").write_text(json.dumps({{"version": 2, "base_shape_zyx": [n, n, n], "groups": {{
    c: {{"zarr": c + ".zarr", "scaledown": 0, "channels": [c]}} for c in ("cos", "grad_mag", "nx", "ny")}}}}))
for c in ("cos", "grad_mag", "nx", "ny"):
    (out / (c + ".zarr")).mkdir(exist_ok=True)
    (out / (c + ".zarr") / ".zarray").write_text(json.dumps({{"shape": [n, n, n], "chunks": [32, 32, 32],
                                                            "dtype": "|u1"}}))
t = out / "init_tilted.tifxyz"
t.mkdir(exist_ok=True)
vals = list(range(12, 53, 4))
m = len(vals)
grid = {{"x": [x for z in vals for x in vals], "y": [32 + 0.3 * (x - 32) for z in vals for x in vals],
        "z": [z for z in vals for x in vals]}}
for a, g in grid.items():
    vc3d_io.write_tiff(t / f"{{a}}.tif", vc3d_io.Raster(m, m, "f32", array.array("f", g)))
(t / "meta.json").write_text(json.dumps({{"format": "tifxyz", "type": "seg", "uuid": "t", "scale": [0.25, 0.25]}}))
for name, normal in (("stages.json", 1.0), ("stages_control.json", 0.0)):
    (out / name).write_text(json.dumps({{"base": {{"normal": normal, "step": 1.0, "smooth": 1.0}},
                                        "stages": [{{"name": "selftest", "steps": 5, "lr": 0.1}}]}}))
'''

CONFIGS = {
    "init.json": {"args": {"model-init": "seed", "init-mode": "shell-dir-crop", "mesh-step": 100},
                  "base": {"normal": 1.0, "data": 0.0, "smooth": 1.0},
                  "stages": [{"name": "stage1", "steps": 3, "lr": 0.1}, {"name": "stage2", "steps": 2}]},
    "offset.json": {"args": {"model-init": "model"}, "base": {"normal": 1.0},
                    "stages": [{"name": "stage1", "steps": 2}]},
    "auto.json": {"args": {"model-init": "atlas"}, "base": {"normal": 1.0},
                  "stages": [{"name": "relax", "opt": {"steps": "auto"}}, {"name": "fit", "opt": {"steps": 4}}]},
    "data.json": {"args": {"model-init": "ext"}, "base": {"normal": 1.0, "data": 1.0},
                  "stages": [{"name": "s", "steps": 1}]},
}


def make_villa(folder):
    """A stand-in villa checkout: lasagna/ with fit.py, fit2tifxyz.py, fit_data.py, torch/ and configs/, and an
    empty vesuvius/src."""
    villa = Path(folder)
    las = villa / "lasagna"
    (las / "configs").mkdir(parents=True)
    (las / "torch").mkdir()
    (villa / "vesuvius" / "src").mkdir(parents=True)
    (las / "fit.py").write_text(FIT)
    (las / "fit_data.py").write_text(FIT_DATA)
    (las / "fit2tifxyz.py").write_text(EXPORT)
    (las / "torch" / "__init__.py").write_text(TORCH)
    for name, cfg in CONFIGS.items():
        (las / "configs" / name).write_text(json.dumps(cfg))
    (las / "configs" / "broken.json").write_text('{"stages": [{"name": "a"} {"name": "b"}]}')   # as offset_snap.json
    return villa


def write_manifest(folder, name="vol.lasagna.json", shape=(64, 64, 64), groups=None, arrays=True, **extra):
    """A local manifest with one uint8 level array per channel at scaledown 0 (or as given)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    groups = groups or {c: {"zarr": f"{c}.zarr/0", "scaledown": 0, "channels": [c]} for c in ("cos", "grad_mag",
                                                                                             "nx", "ny")}
    doc = {"version": 2, "base_shape_zyx": list(shape), "source_to_base": 1.0, "groups": groups}
    doc.update(extra)
    if arrays:
        for spec in groups.values():
            lvl = [lasagna.ceil_half(v, spec["scaledown"]) for v in shape]
            fakes.write_array(folder / spec["zarr"], lvl, lambda z, y, x: 7, [32, 32, 32])
    (folder / name).write_text(json.dumps(doc))
    return folder / name


def plane(path, y=32.0, rows=5, cols=5, x0=20, z0=20, step=4):
    return fakes.write_tifxyz(path, lambda r, c: (x0 + step * c, y, z0 + step * r), rows=rows, cols=cols)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.villa = make_villa(self.d / "villa")
        self.las = self.villa / "lasagna"
        self.home = self.d / "home"
        self.userhome = self.d / "user"
        self.userhome.mkdir()
        self.env = fakes.env_for(self.d / "bin", self.home, LASAGNA_DIR=self.las, LASAGNA_PYTHON=sys.executable,
                                 HOME=self.userhome)
        self.env.pop("VILLA_DIR", None)
        self.ctx = vc3d_agent.Context(env=self.env)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, args=None, **env):
        ctx = vc3d_agent.Context(env=dict(self.env, **{k: str(v) for k, v in env.items()})) if env else self.ctx
        return vc3d_agent.call(name, args or {}, ctx)

    def seen(self, result):
        return json.loads((Path(result["out"]) / "fake_seen.json").read_text())


# ---------------------------------------------------------------- pure helpers

class TestHelpers(unittest.TestCase):
    def test_deep_merge_is_fit_pys(self):
        a = {"args": {"a": 1, "b": 2}, "stages": [1, 2], "base": {"x": 1}}
        b = {"args": {"b": 3}, "stages": [9], "base": 5}
        self.assertEqual(lasagna.deep_merge(a, b), {"args": {"a": 1, "b": 3}, "stages": [9], "base": 5})
        self.assertEqual(a["args"], {"a": 1, "b": 2})            # inputs untouched

    def test_stage_list_reads_steps_on_the_stage_or_its_opt(self):
        self.assertEqual(lasagna.stage_list(CONFIGS["auto.json"]), [("relax", "auto"), ("fit", 4)])
        self.assertEqual(lasagna.stage_list({"stage1": {"steps": 7}, "args": {"steps": 1}}), [("stage1", 7)])

    def test_ceil_half_matches_published_levels(self):
        # a published lasagna run (14 Oct 2026): base 17998 x 8595 x 8595, level 1 8999 x 4298, level 2 4500 x 2149
        self.assertEqual([lasagna.ceil_half(v, 1) for v in (17998, 8595)], [8999, 4298])
        self.assertEqual([lasagna.ceil_half(v, 2) for v in (17998, 8595)], [4500, 2149])

    def test_chunk_keys_of_a_crop(self):
        # a crop mirrored from that run on 15 Oct 2026 copied 125 cos chunks (level 1) and 27 per level-2 group
        crop = (3000, 4000, 9000, 256, 256, 256)
        za = {"shape": [8999, 4298, 4298], "chunks": [32, 32, 32]}
        self.assertEqual(lasagna.level_box(crop, 2), [(4500, 4628), (2000, 2128), (1500, 1628)])
        self.assertEqual(len(lasagna.chunk_keys(za, lasagna.level_box(crop, 2))), 125)
        za2 = {"shape": [4500, 2149, 2149], "chunks": [32, 32, 32], "dimension_separator": "/"}
        keys = lasagna.chunk_keys(za2, lasagna.level_box(crop, 4))
        self.assertEqual(len(keys), 27)
        self.assertIn("70/31/23", keys)
        self.assertEqual(lasagna.chunk_keys(za2, [(5000, 5100), (0, 1), (0, 1)]), [])     # outside the array

    def test_dense_gib(self):
        doc = {"groups": {"a": {"scaledown": 0, "channels": ["a"]}, "b": {"scaledown": 1, "channels": ["b"]}}}
        za = {"a": {"shape": [1024] * 3, "chunks": [64] * 3}, "b": {"shape": [512] * 3, "chunks": [64] * 3}}
        self.assertAlmostEqual(lasagna.dense_gib(doc, za), 1.125)
        self.assertAlmostEqual(lasagna.dense_gib(doc, za, (0, 0, 0, 512, 512, 512)), 0.125 + 0.125 / 8)

    def test_crop_around(self):
        self.assertEqual(lasagna.crop_around([[10, 20, 30], [40, 50, 60]], 5), [5, 15, 25, 41, 41, 41])
        self.assertEqual(lasagna.crop_around([[10, 20, 30], [40, 50, 60]], 100, [64, 64, 64]), [0, 0, 0, 64, 64, 64])
        with self.assertRaises(lasagna.LasagnaError):
            lasagna.crop_around([[100, 100, 100], [110, 110, 110]], 2, [64, 64, 64])

    def test_crop_around_takes_the_volume_in_base_voxels(self):
        # base_shape_zyx is in source voxels: with source_to_base 4 a volume 2000 wide is 8000 base voxels wide
        self.assertEqual(lasagna.crop_around([[6000, 10, 10], [6010, 20, 20]], 5, [100, 100, 2000], 4.0),
                         [5995, 5, 5, 21, 21, 21])

    def test_snap_crop_to_the_coarsest_group(self):
        doc = {"source_to_base": 1.0, "groups": {"cos": {"scaledown": 1}, "nx": {"scaledown": 2}}}
        self.assertEqual(lasagna.snap_crop([3002, 4001, 9000, 256, 256, 256], doc), [3000, 4000, 9000, 260, 260, 256])
        self.assertEqual(lasagna.snap_crop([3000, 4000, 9000, 256, 256, 256], doc), [3000, 4000, 9000, 256, 256, 256])
        doc["source_to_base"] = 2.0
        self.assertEqual(lasagna.snap_crop([3, 0, 0, 1, 8, 8], doc), [0, 0, 0, 8, 8, 8])

    def test_level_metadata_is_checked_before_use(self):
        good = {"shape": [64, 64, 64], "chunks": [32, 32, 32]}
        self.assertIsNone(lasagna.check_zarray(good))
        for bad in (dict(good, dimension_separator="/../../escape/"), dict(good, chunks=[0, 32, 32]),
                    dict(good, shape=[64, 64]), [1, 2], dict(good, chunks=[32.5, 32, 32])):
            self.assertIsNotNone(lasagna.check_zarray(bad), bad)
            with self.assertRaises(lasagna.LasagnaError):
                lasagna.chunk_keys(bad, [(0, 8), (0, 8), (0, 8)])
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(lasagna.LasagnaError):
                lasagna.mirror_chunks("http://127.0.0.1:9/", "a", good, ["../../out"], Path(t) / "level")

    def test_bad_manifests_are_problems_not_crashes(self):
        self.assertEqual(lasagna.check_manifest_doc([1, 2]), ["the manifest is not a JSON object"])
        doc = {"groups": {"a": {"zarr": "a/0", "channels": ["grad_mag"]}}, "source_to_base": "x"}
        probs = " | ".join(lasagna.check_manifest_doc(doc))
        self.assertIn("needs zarr, scaledown and channels", probs)
        self.assertIn("source_to_base", probs)
        self.assertEqual(lasagna.group_rows(doc, {}), ([], []))
        self.assertEqual(lasagna.local_zarrays(Path("/nowhere/x.lasagna.json"), doc), {})

    def test_parse_progress(self):
        text = "noise\nPROGRESS 1 3 0.5\n[fit] x\nPROGRESS 2 3 nan\nPROGRESS 3 3 0.25\nPROGRESS x y z\n"
        p = lasagna.parse_progress(text)
        self.assertEqual((p["lines"], p["last_step"], p["total_steps"]), (3, 3, 3))
        self.assertEqual((p["first_loss"], p["last_loss"], p["min_loss"], p["non_finite"]), (0.5, 0.25, 0.25, 1))
        self.assertEqual(lasagna.parse_progress("nothing"), {"lines": 0})

    def test_hints(self):
        self.assertTrue(any("CUDA" in h for h in lasagna.hints_for("RuntimeError: torch.cuda.Stream requires CUDA")))
        self.assertEqual(lasagna.hints_for("all fine"), [])

    def test_check_manifest_doc(self):
        good = {"groups": {c: {"zarr": f"{c}.zarr/0", "scaledown": 0, "channels": [c]} for c in ("grad_mag", "nx",
                                                                                               "ny")},
                "base_shape_zyx": [8, 8, 8]}
        self.assertEqual(lasagna.check_manifest_doc(good), [])
        self.assertEqual(lasagna.check_manifest_doc({}), ["no groups"])
        bad = json.loads(json.dumps(good))
        del bad["groups"]["ny"]
        bad["groups"]["nx"]["zarr"] = "../elsewhere/0"
        bad["groups"]["grad_mag"]["scaledown"] = -1
        bad["base_shape_zyx"] = [8, 8]
        probs = " | ".join(lasagna.check_manifest_doc(bad))
        for want in ("['ny'] missing", "relative path", "not an OME-Zarr level", "not three positive integers"):
            self.assertIn(want, probs)

    def test_group_rows_checks_shapes_and_dtype(self):
        doc = {"base_shape_zyx": [65, 64, 64],
               "groups": {"a": {"zarr": "a/1", "scaledown": 1, "channels": ["grad_mag", "nx"]},
                          "b": {"zarr": "b/1", "scaledown": 1, "channels": ["ny"]}}}
        rows, probs = lasagna.group_rows(doc, {"a": {"shape": [33, 32, 32], "chunks": [32] * 3, "dtype": "|u1"},
                                               "b": {"shape": [32, 32, 32], "chunks": [32] * 3, "dtype": "<f4"}})
        self.assertEqual(rows[0]["spacing_base_voxels"], 2.0)
        self.assertEqual(len(probs), 2, probs)
        self.assertIn("dtype <f4", probs[0])
        self.assertIn("halved 1 times ([33, 32, 32])", probs[1])

    def test_resolve_config(self):
        with tempfile.TemporaryDirectory() as t:
            las = make_villa(Path(t) / "villa") / "lasagna"
            self.assertEqual(lasagna.resolve_config(las, "init.json"), las / "configs" / "init.json")
            self.assertEqual(lasagna.resolve_config(las, "init"), las / "configs" / "init.json")
            (Path(t) / "mine.json").write_text("{}")
            got = lasagna.resolve_config(las, "mine.json", base=t)
            self.assertTrue(got.is_absolute())
            self.assertEqual(got, (Path(t) / "mine.json").resolve())
            with self.assertRaises(lasagna.LasagnaError) as cm:
                lasagna.resolve_config(las, "nope.json")
            self.assertIn("init.json", str(cm.exception))

    def test_safe_extract_refuses_paths_outside_and_links(self):
        def tar_of(members):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for name, kind in members:
                    info = tarfile.TarInfo(name)
                    if kind == "link":
                        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
                        tar.addfile(info)
                    else:
                        info.size = 2
                        tar.addfile(info, io.BytesIO(b"ok"))
            return buf.getvalue()
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(lasagna.safe_extract(tar_of([("a.tifxyz/x.tif", "file")]), Path(t) / "ok"),
                             ["a.tifxyz/x.tif"])
            for bad in ([("../evil", "file")], [("/abs", "file")], [("link", "link")]):
                with self.assertRaises(lasagna.LasagnaError):
                    lasagna.safe_extract(tar_of(bad), Path(t) / "bad")
            self.assertFalse((Path(t) / "evil").exists())

    def test_find_lasagna(self):
        with tempfile.TemporaryDirectory() as t:
            villa = make_villa(Path(t) / "villa")
            las, py, root, how = lasagna.find_lasagna({"VILLA_DIR": str(villa), "HOME": t})
            self.assertEqual((las, root, how, py), (villa / "lasagna", villa, "VILLA_DIR", sys.executable))
            (villa / "lasagna" / ".venv" / "bin").mkdir(parents=True)
            (villa / "lasagna" / ".venv" / "bin" / "python").write_text("")
            self.assertEqual(lasagna.find_lasagna({"VILLA_DIR": str(villa), "HOME": t})[1],
                             str(villa / "lasagna" / ".venv" / "bin" / "python"))
            with self.assertRaises(lasagna.LasagnaError) as cm:
                lasagna.find_lasagna({"HOME": str(Path(t) / "nobody"), "LASAGNA_DIR": t})
            self.assertIn("LASAGNA_DIR", str(cm.exception))

    def test_surface_scale_is_fit_pys(self):
        self.assertEqual(lasagna.surface_scale({}, [64] * 3), 1.0)
        self.assertEqual(lasagna.surface_scale({"base_shape_zyx": [128] * 3}, [64] * 3), 0.5)
        self.assertEqual(lasagna.surface_scale({}, [64] * 3, [32] * 3), 2.0)        # the config's vc3d shape
        self.assertEqual(lasagna.surface_scale({"base_shape_zyx": [128] * 3}, None), 1.0)
        self.assertEqual(lasagna.surface_scale({"base_shape_zyx": [129, 128, 128]}, [64] * 3), 0.5)   # within 1 %
        for meta in ({"base_shape_zyx": [128, 64, 64]}, {"base_shape_zyx": [96] * 3}, {"base_shape_zyx": [0, 1, 1]},
                     {"base_shape_zyx": "big"}):
            with self.assertRaises(lasagna.LasagnaError, msg=meta):
                lasagna.surface_scale(meta, [64] * 3)

    def test_box_overlap(self):
        bb = [[20, 32, 20], [36, 32, 36]]
        self.assertEqual(lasagna.box_overlap(bb, [0, 0, 0, 64, 64, 64]), 1.0)
        self.assertEqual(lasagna.box_overlap(bb, [0, 0, 0, 8, 8, 8]), 0.0)
        self.assertEqual(lasagna.box_overlap(bb, [16, 28, 16, 12, 8, 12]), 0.5)
        self.assertEqual(lasagna.box_overlap(bb, [16, 33, 16, 30, 8, 30]), 0.0)     # the plane's y is outside

    def test_negative_crop_starts_are_clipped(self):
        # villa's load_3d reads from max(0, start) but sets the origin from the start: a negative start would
        # shift every channel by |start| voxels
        one = {"groups": {"a": {"scaledown": 0, "channels": ["a"]}}}
        self.assertEqual(lasagna.snap_crop([-8, 0, 0, 24, 8, 8], one), [0, 0, 0, 16, 8, 8])
        four = {"groups": {"a": {"scaledown": 2, "channels": ["a"]}}}
        self.assertEqual(lasagna.snap_crop([-6, 5, 0, 16, 8, 8], four), [0, 4, 0, 12, 12, 8])
        with self.assertRaises(lasagna.LasagnaError):
            lasagna.snap_crop([-20, 0, 0, 8, 8, 8], one)

    def test_flat_czyx_groups(self):
        # villa still reads older flat (C, Z, Y, X) groups
        za = {"shape": [4, 128, 128, 128], "chunks": [4, 32, 32, 32], "dtype": "|u1"}
        self.assertIsNone(lasagna.check_zarray(za))
        self.assertIsNotNone(lasagna.check_zarray(dict(za, chunks=[32, 32, 32])))
        doc = {"base_shape_zyx": [128] * 3, "groups": {"all": {"zarr": "all.zarr", "scaledown": 0,
                                                               "channels": ["cos", "grad_mag", "nx", "ny"]}}}
        rows, probs = lasagna.group_rows(doc, {"all": za})
        self.assertEqual((rows[0]["shape_zyx"], probs), ([128, 128, 128], []))
        self.assertAlmostEqual(lasagna.dense_gib(doc, {"all": za}), 4 * 128 ** 3 / 2 ** 30)
        self.assertAlmostEqual(lasagna.dense_gib(doc, {"all": za}, skip=("cos",)), 3 * 128 ** 3 / 2 ** 30)
        self.assertEqual(lasagna.chunk_keys(za, [(0, 32), (0, 32), (0, 40)]), ["0.0.0.0", "0.0.0.1"])
        with self.assertRaises(lasagna.LasagnaError):                # a group it cannot size: refuse
            lasagna.dense_gib(doc, {})

    def test_malformed_metadata_is_a_problem_not_a_crash(self):
        good = {"zarr": "a.zarr", "channels": ["grad_mag", "nx", "ny"]}
        for doc, want in (({"groups": {"a": dict(good, scaledown=2000)}}, "OME-Zarr level"),
                          ({"source_to_base": 0.25, "groups": {"a": dict(good, scaledown=1)}}, "under one base voxel"),
                          ({"source_to_base": float("inf"), "groups": {"a": dict(good, scaledown=0)}},
                           "positive number")):
            self.assertTrue(any(want in q for q in lasagna.check_manifest_doc(doc)), doc)
        doc = {"groups": {"a": dict(good, scaledown=0)}}
        rows, probs = lasagna.group_rows(doc, {"a": [1, 2]})
        self.assertIn("not a JSON object", probs[0])
        with self.assertRaises(lasagna.LasagnaError):
            lasagna.dense_gib(doc, {"a": "oops"})

    def test_config_needs(self):
        def needs(args, **top):
            return lasagna.config_needs(dict({"args": args}, **top))
        self.assertEqual(needs({"model-init": "flatten"}), ("flatten", None, ["external_surfaces"]))
        self.assertEqual(needs({"model-init": "flatten"}, external_surfaces=[{}])[2], [])
        self.assertEqual(needs({"model_init": "atlas"})[2], ["atlas"])
        self.assertEqual(needs({"model-init": "model"})[2], ["model_input"])
        self.assertEqual(needs({}), ("seed", "cylinder_seed (villa's default)",
                                     ["seed", "model_h", "umbilicus (the manifest's umbilicus_json)"]))
        self.assertEqual(needs({"seed": [1, 2, 3], "model_h": 64, "init-mode": "shell-dir-crop"})[2],
                         ["init_shell_dir"])
        # corr-point-roi works out the seed and model-h; approval-inpaint works out model-h but needs its tifxyz
        self.assertEqual(needs({"init-mode": "shell-dir-crop", "corr-point-roi": "true"})[2],
                         ["init_shell_dir", "corr_points"])
        self.assertEqual(needs({"init-mode": "shell-dir-crop", "approval-inpaint": True})[2],
                         ["seed", "approval-inpaint-tifxyz", "init_shell_dir"])
        self.assertEqual(needs({"model-init": "ext", "tifxyz-init": "a.tifxyz"})[2], [])


class TestFlags(unittest.TestCase):
    schema = vc3d_agent.TOOLS["lasagna_fit"].schema()

    def test_flags_follow_the_schema(self):
        got = lasagna.parse_flags(["--config", "a.json", "--config", "b.json,c.json", "--seed", "1,2,3.5",
                                   "--crop=0,0,0,8,8,8", "--dry-run", "--depth", "3", "--args", '{"mesh-step": 50}',
                                   "--model_w_unit", "wraps"], self.schema)
        self.assertEqual(got, ({"config": ["a.json", "b.json", "c.json"], "seed": [1, 2, 3.5],
                                "crop": [0, 0, 0, 8, 8, 8], "dry_run": True, "depth": 3, "args": {"mesh-step": 50},
                                "model_w_unit": "wraps"}, []))
        self.assertEqual(lasagna.parse_flags(["--dry-run", "false"], self.schema), ({"dry_run": False}, []))
        self.assertEqual(lasagna.parse_flags(["--out=", "--depth", "2"], self.schema), ({"out": "", "depth": 2}, []))

    def test_repeated_flags(self):
        flags, _ = lasagna.parse_flags(["--external-surfaces", '{"path": "a.tifxyz", "offset": 0}',
                                        "--external-surfaces", '{"path": "b.tifxyz", "offset": 1}',
                                        "--seed", "1", "--seed", "2", "--seed", "3"], self.schema)
        self.assertEqual(flags, {"external_surfaces": [{"path": "a.tifxyz", "offset": 0},
                                                       {"path": "b.tifxyz", "offset": 1}], "seed": [1, 2, 3]})
        self.assertEqual(lasagna.parse_flags(["--seed", "1,2", "--seed", "3"], self.schema)[0], {"seed": [1, 2, 3]})
        with self.assertRaises(ValueError) as cm:
            lasagna.parse_flags(["--depth", "2", "--depth", "3"], self.schema)
        self.assertIn("given twice", str(cm.exception))

    def test_a_boolean_takes_only_a_true_false_word(self):
        self.assertEqual(lasagna.parse_flags(["--dry-run", "@spec.json"], self.schema), ({"dry_run": True},
                                                                                       ["@spec.json"]))
        self.assertEqual(lasagna.parse_flags(["--dry-run", "off", "x"], self.schema), ({"dry_run": False}, ["x"]))

    def test_bad_flags(self):
        for tokens in (["--nope", "1"], ["--depth"], ["--args", "{oops"], ["--depth", "two"]):
            with self.assertRaises(ValueError, msg=tokens):
                lasagna.parse_flags(tokens, self.schema)


# ---------------------------------------------------------------- the tools on a stand-in villa

class TestStatusAndConfigs(Base):
    def test_status(self):
        r = self.call("lasagna_status", {"check_import": True})
        self.assertTrue(r["found"])
        self.assertEqual((r["found_by"], r["villa"]), ("LASAGNA_DIR", str(self.villa)))
        self.assertEqual(r["probe"]["packages"]["torch"], "0.0+fake")
        self.assertEqual(r["probe"]["fit_import"], "ok")
        self.assertEqual(r["default_device"], "cpu")
        self.assertIn("CUDA machine", r["note"])
        self.assertEqual(r["configs"], 5)
        self.assertEqual(self.call("lasagna_status", FAKE_CUDA=1)["default_device"], "cuda")

    def test_status_without_villa(self):
        empty = self.d / "empty"
        empty.mkdir()
        r = self.call("lasagna_status", LASAGNA_DIR=empty)
        self.assertFalse(r["found"])
        self.assertIn("LASAGNA_DIR", r["problem"])

    def test_configs(self):
        r = self.call("lasagna_configs")
        by = {c["name"]: c for c in r["configs"]}
        self.assertEqual(by["init.json"]["total_steps"], 5)
        self.assertEqual(by["init.json"]["loss_terms"], ["normal", "smooth"])      # zero weights left out
        self.assertEqual(by["init.json"]["init_mode"], "shell-dir-crop")
        self.assertIsNone(by["auto.json"]["total_steps"])
        self.assertEqual([b["name"] for b in r["invalid"]], ["broken.json"])
        one = self.call("lasagna_configs", {"name": "offset"})
        self.assertEqual(one["config"]["model_init"], "model")
        self.assertEqual(one["json"], CONFIGS["offset.json"])
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("lasagna_configs", {"name": "nope.json"})
        self.assertEqual(by["init.json"]["needs"], ["seed", "model_h", "init_shell_dir"])
        self.assertEqual(by["offset.json"]["needs"], ["model_input"])
        self.assertEqual((by["auto.json"]["model_init"], by["auto.json"]["needs"]), ("atlas", ["atlas"]))


class TestFit(Base):
    def setUp(self):
        super().setUp()
        self.manifest = write_manifest(self.d / "in")
        self.start = plane(self.d / "start.tifxyz")

    def test_cuda_runs_villa_fit_directly_with_kits_args_last(self):
        r = self.call("lasagna_fit", {"config": ["init.json"], "input": str(self.manifest), "seed": [30, 31, 32],
                                      "model_h": 64, "depth": 2, "args": {"mesh-step": 50}, "device": "cuda",
                                      "voxel_um": 7.91})
        self.assertEqual(r["exit"], 0, r)
        seen = self.seen(r)
        self.assertEqual(seen["cwd"], str(self.las))
        self.assertEqual(Path(seen["argv"][0]), self.las / "configs" / "init.json")      # absolute, villa's folder
        args = seen["cfg"]["args"]
        self.assertEqual((args["model-init"], args["init-mode"]), ("seed", "shell-dir-crop"))   # from the config
        self.assertEqual((args["seed"], args["model-h"], args["depth"], args["mesh-step"]), ([30, 31, 32], 64, 2, 50))
        self.assertEqual((args["device"], args["progress"], args["out-dir"]), ("cuda", True, r["out"]))
        self.assertNotIn("cuda-gridsample", args)
        self.assertEqual(seen["cfg"]["voxel_size_um"], 7.91)
        self.assertEqual(seen["loaded"]["loader"], "streaming")
        self.assertEqual(r["progress"]["lines"], 5)
        self.assertEqual(r["progress"]["last_loss"], 0.2)
        self.assertEqual(r["checkpoints"]["count"], 2)
        self.assertTrue(r["checkpoints"]["last"].endswith("model_stage2_000002.pt"))
        self.assertTrue(r["checkpoints"]["final"].endswith("model_final.pt"))
        self.assertEqual(len(r["tifxyz"]), 1)
        self.assertEqual(r["tifxyz"][0]["valid_vertices"], 9)
        self.assertIsNone(r["crop"])
        merged = json.loads(Path(r["config_merged"]).read_text())
        self.assertEqual(merged["stages"], CONFIGS["init.json"]["stages"])
        receipt = json.loads((Path(r["out"]) / "receipt.json").read_text())
        self.assertEqual((receipt["tool"], receipt["device"], receipt["steps"][0]["exit"]), ("lasagna_fit", "cuda", 0))

    def test_cpu_runs_the_shim_on_the_manifests_crop(self):
        m = write_manifest(self.d / "mirror", kit_crop=[4, 8, 12, 32, 32, 32])
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(m), "mode": "ext",
                                      "tifxyz_init": str(self.start), "device": "cpu"})
        self.assertEqual(r["exit"], 0, r)
        self.assertEqual(r["crop"], [4, 8, 12, 32, 32, 32])
        self.assertIn("kit_crop", r["notes"][0])
        seen = self.seen(r)
        self.assertEqual(seen["loaded"], {"loader": "dense", "device": "cpu", "crop": [4, 8, 12, 32, 32, 32],
                                          "cuda_gridsample": False})
        self.assertEqual(seen["cfg"]["args"]["cuda-gridsample"], 0)
        self.assertEqual(seen["cfg"]["args"]["model-init"], "ext")
        self.assertIn("fit_cpu_shim.py", json.loads(Path(r["command"]).read_text())["argv"][1])

    def test_last_checkpoint_is_the_last_written_not_the_last_name(self):
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                      "tifxyz_init": str(self.start), "device": "cuda",
                                      "overrides": {"stages": [{"name": "stage1", "steps": 1},
                                                               {"name": "stage2", "steps": 1},
                                                               {"name": "snap", "steps": 1}]}})
        self.assertTrue(r["checkpoints"]["last"].endswith("model_snap_000001.pt"), r["checkpoints"])

    def test_arguments_from_configs_and_args_count(self):
        cfg = self.d / "with_input.json"
        cfg.write_text(json.dumps({"args": {"input": str(self.manifest), "model-init": "ext",
                                            "tifxyz-init": str(self.start)},
                                   "base": {"normal": 1.0}, "stages": [{"name": "s", "steps": 1}]}))
        r = self.call("lasagna_fit", {"config": [str(cfg)], "device": "cpu"})
        self.assertEqual(r["exit"], 0, r)
        self.assertEqual(r["mode"], "ext")
        self.assertIsNotNone(r["crop"])                         # the start surface came from the config
        r = self.call("lasagna_fit", {"config": ["init.json"], "input": str(self.manifest), "device": "cuda",
                                      "args": {"model-init": "ext", "tifxyz-init": str(self.start)}})
        self.assertEqual((r["exit"], r["mode"]), (0, "ext"), r)
        args = self.seen(r)["cfg"]["args"]
        self.assertEqual((args["model-init"], args["tifxyz-init"]), ("ext", str(self.start.resolve())))
        r = self.call("lasagna_fit", {"config": ["init.json"], "input": str(self.manifest), "device": "cuda",
                                      "seed": [1, 2, 3], "model_h": 64, "args": {"seed": [9, 9, 9], "depth": 4},
                                      "depth": 2})
        self.assertEqual((self.seen(r)["cfg"]["args"]["seed"], self.seen(r)["cfg"]["args"]["depth"]), ([1, 2, 3], 2))
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", {"config": ["offset.json"], "device": "cuda",
                                      "args": {"input": str(self.d / "nope.lasagna.json")}})
        self.assertIn("not found", str(cm.exception))

    def test_unaligned_crops_grow_to_the_coarsest_grid(self):
        groups = {"cos": {"zarr": "cos.zarr/1", "scaledown": 1, "channels": ["cos"]}}
        groups.update({c: {"zarr": f"{c}.zarr/2", "scaledown": 2, "channels": [c]} for c in ("grad_mag", "nx", "ny")})
        m = write_manifest(self.d / "levels", groups=groups)
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(m), "mode": "ext",
                                      "tifxyz_init": str(self.start), "crop": [18, 29, 18, 20, 8, 20]})
        self.assertEqual(r["crop"], [16, 28, 16, 24, 12, 24])
        self.assertEqual(self.seen(r)["loaded"]["crop"], [16, 28, 16, 24, 12, 24])
        self.assertTrue(any("coarsest group" in n for n in r["notes"]))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("lasagna_fit", {"config": ["offset.json"], "input": str(write_manifest(
                self.d / "badcrop", kit_crop=[0, 0, 0, 0, 8, 8])), "mode": "ext", "tifxyz_init": str(self.start)})

    def test_cpu_default_crop_is_the_start_surface_plus_margin(self):
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                      "tifxyz_init": str(self.start), "margin": 4})
        self.assertEqual(r["device"], "cpu")                                    # the lasagna Python has no CUDA
        self.assertEqual(r["crop"], [16, 28, 16, 25, 9, 25])                   # x 20..36, y 32, z 20..36
        self.assertEqual(self.seen(r)["loaded"]["crop"], [16, 28, 16, 25, 9, 25])
        explicit = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                             "tifxyz_init": str(self.start), "crop": [16, 28, 16, 12, 8, 12]})
        self.assertEqual(self.seen(explicit)["loaded"]["crop"], [16, 28, 16, 12, 8, 12])
        self.assertTrue(any("part of the start surface lies outside" in n for n in explicit["notes"]))
        with self.assertRaises(vc3d_agent.ToolError) as cm:        # nothing of the start surface in the box
            self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                      "tifxyz_init": str(self.start), "crop": [0, 0, 0, 8, 8, 8]})
        self.assertIn("lies outside crop", str(cm.exception))

    def test_cpu_refuses_a_streamed_manifest_and_a_large_dense_load(self):
        remote = write_manifest(self.d / "remote", arrays=False)
        (remote.parent / lasagna.MARKER).write_text(json.dumps({"artifact_url": "https://x/", "manifest_file": "v"}))
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", {"config": ["offset.json"], "input": str(remote), "mode": "ext",
                                      "tifxyz_init": str(self.start), "device": "cpu"})
        self.assertIn("needs CUDA", str(cm.exception))
        big = self.d / "big"
        for c in ("grad_mag", "nx", "ny"):
            (big / f"{c}.zarr" / "0").mkdir(parents=True)
            (big / f"{c}.zarr" / "0" / ".zarray").write_text(json.dumps({"shape": [2048, 2048, 2048],
                                                                        "chunks": [32] * 3, "dtype": "|u1"}))
        m = write_manifest(big, shape=(2048, 2048, 2048), arrays=False, groups={
            c: {"zarr": f"{c}.zarr/0", "scaledown": 0, "channels": [c]} for c in ("grad_mag", "nx", "ny")})
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", {"config": ["init.json"], "input": str(m), "seed": [5, 5, 5], "model_h": 64,
                                      "device": "cpu"})
        self.assertIn("24.0 GiB", str(cm.exception))
        r = self.call("lasagna_fit", {"config": ["init.json"], "input": str(m), "seed": [5, 5, 5], "model_h": 64,
                                      "device": "cpu", "crop": [0, 0, 0, 256, 256, 256]})
        self.assertEqual(r["exit"], 0)

    def test_argument_problems_are_tool_errors(self):
        base = {"config": ["offset.json"], "input": str(self.manifest), "device": "cuda"}
        cases = [
            (dict(base, mode="ext"), "needs tifxyz_init"),
            (dict(base, mode="model"), "needs model_input"),
            (dict(base, config=["init.json"]), "needs seed"),
            (dict(base, mode="flatten"), "exactly one external_surfaces"),
            (dict(base, input=str(self.start)), "*.lasagna.json"),
            ({"config": ["offset.json"], "device": "cuda"}, "input"),
            (dict(base, mode="ext", tifxyz_init=str(self.d / "missing")), "tifxyz_init not found"),
            (dict(base, overrides={"args": {"x": 1}}), "not overrides.args"),
            (dict(base, config=["nope.json"]), "villa ships"),
        ]
        for args, want in cases:
            with self.assertRaises(vc3d_agent.ToolError, msg=want) as cm:
                self.call("lasagna_fit", args)
            self.assertIn(want, str(cm.exception))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("lasagna_fit", dict(base, mode="sideways"))                # schema enum
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", dict(base, mode="ext", tifxyz_init=str(self.start), out=str(ROOT / "docs" / "x")))
        self.assertIn("rule 6", str(cm.exception))

    def test_flatten_and_overrides(self):
        r = self.call("lasagna_fit", {"config": ["offset.json"], "mode": "flatten", "device": "cpu",
                                      "external_surfaces": [{"path": str(self.start), "offset": 0}],
                                      "overrides": {"stages": [{"name": "only", "steps": 1}], "base": {"smooth": 2}}})
        self.assertEqual(r["exit"], 0, r)
        cfg = self.seen(r)["cfg"]
        self.assertEqual(cfg["stages"], [{"name": "only", "steps": 1}])               # lists replace
        self.assertEqual(cfg["base"], {"normal": 1.0, "smooth": 2})                  # objects merge
        self.assertEqual(cfg["external_surfaces"], [{"path": str(self.start.resolve()), "offset": 0}])
        self.assertIsNone(self.seen(r)["loaded"])
        self.assertEqual(r["progress"]["lines"], 1)

    def test_data_term_off_cuda_is_flagged(self):
        r = self.call("lasagna_fit", {"config": ["data.json"], "input": str(self.manifest),
                                      "tifxyz_init": str(self.start), "device": "cpu"})
        self.assertTrue(any("CUDA only" in n for n in r["notes"]))

    def test_failure_reports_log_and_hints(self):
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                      "tifxyz_init": str(self.start), "device": "cuda"},
                      FAKE_FIT_FAIL="RuntimeError: torch.cuda.Stream requires CUDA support")
        self.assertEqual(r["exit"], 1)
        self.assertEqual(r["error"], "fit.py exited 1")
        self.assertIn("torch.cuda.Stream", r["log_tail"])
        self.assertTrue(any("dense shim" in h for h in r["hints"]))
        self.assertEqual(r["checkpoints"]["count"], 0)

    def test_dry_run_writes_the_command_only(self):
        r = self.call("lasagna_fit", {"config": ["offset.json", "init.json"], "input": str(self.manifest),
                                      "seed": [1, 2, 3], "model_h": 64, "device": "cuda", "dry_run": True})
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["exit"], 0)
        self.assertEqual(r["mode"], "seed")                     # the later config's model-init wins
        self.assertFalse((Path(r["out"]) / "fit.log").exists())
        cmd = json.loads(Path(r["command"]).read_text())
        self.assertEqual(cmd["argv"], r["argv"])
        self.assertEqual(cmd["cwd"], str(self.las))
        self.assertEqual([Path(a).name for a in r["argv"][2:]], ["offset.json", "init.json", "kit_overrides.json"])

    def test_fit_with_export(self):
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                      "tifxyz_init": str(self.start), "voxel_um": 2.4,
                                      "export": {"single_segment": True, "output_name": "agent.tifxyz"}})
        self.assertEqual(r["export"]["exit"], 0, r["export"])
        argv = json.loads((Path(r["out"]) / "export" / "fake_export_argv.json").read_text())
        self.assertIn("--single-segment", argv)
        self.assertIn("--voxel-size-um=2.4", argv)
        self.assertTrue(r["export"]["tifxyz"][0]["path"].endswith("agent.tifxyz"))
        self.assertAlmostEqual(r["export"]["tifxyz"][0]["meta_area_cm2"], 16 * 2.4e-4 ** 2)
        bad = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                        "tifxyz_init": str(self.start), "export": {"single_segment": True}},
                        FAKE_EXPORT_FAIL=1)
        self.assertEqual(bad["exit"], 1)
        self.assertIn("export failed", bad["error"])

    def test_export_tool(self):
        model = self.d / "model.pt"
        model.write_bytes(b"x")
        r = self.call("lasagna_export", {"model": str(model), "target_volume_shape_zyx": [32, 32, 32]})
        self.assertEqual(r["exit"], 0)
        argv = json.loads((Path(r["out"]) / "fake_export_argv.json").read_text())
        self.assertEqual(argv[-4:], ["--target-volume-shape-zyx", "32", "32", "32"])
        self.assertTrue((Path(r["out"]) / "receipt.json").is_file())
        bad = self.call("lasagna_export", {"model": str(model)}, FAKE_EXPORT_FAIL=1)
        self.assertEqual(bad["exit"], 1)
        self.assertIn("export failed", bad["log_tail"])

    def test_start_surface_in_another_frame_is_scaled_as_fit_py_scales_it(self):
        # an export at twice the manifest's frame (fit2tifxyz --target-volume-shape-zyx): fit.py halves its
        # coordinates, so the default crop must be around the halved box (x 20..36, y 32, z 20..36)
        start = plane(self.d / "start2x.tifxyz", y=64.0, x0=40, z0=40, step=8)
        meta = json.loads((start / "meta.json").read_text())
        (start / "meta.json").write_text(json.dumps(dict(meta, base_shape_zyx=[128, 128, 128])))
        base = {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext", "tifxyz_init": str(start),
                "margin": 4, "device": "cpu"}
        r = self.call("lasagna_fit", base)
        self.assertEqual(r["crop"], [16, 28, 16, 25, 9, 25])
        self.assertTrue(any("scale by 0.5" in n for n in r["notes"]))
        (start / "meta.json").write_text(json.dumps(meta))          # no frame in meta: the config's vc3d shape
        r = self.call("lasagna_fit", dict(base, overrides={"vc3d_volume_shape_zyx": [128, 128, 128]}))
        self.assertEqual(r["crop"], [16, 28, 16, 25, 9, 25])
        (start / "meta.json").write_text(json.dumps(dict(meta, base_shape_zyx=[128, 64, 64])))
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", base)
        self.assertIn("anisotropic", str(cm.exception))

    def test_a_manifest_without_a_base_shape_takes_fit_pys_frame(self):
        # an older manifest without base_shape_zyx: fit.py takes its frame from the finest level array (64^3 at
        # scaledown 0) and halves a start surface written at twice that frame, so the default crop must too
        doc = json.loads(self.manifest.read_text())
        del doc["base_shape_zyx"]
        legacy = self.manifest.with_name("legacy.lasagna.json")
        legacy.write_text(json.dumps(doc))
        start = plane(self.d / "start2x.tifxyz", y=64.0, x0=40, z0=40, step=8)
        meta = json.loads((start / "meta.json").read_text())
        (start / "meta.json").write_text(json.dumps(dict(meta, base_shape_zyx=[128, 128, 128])))
        base = {"config": ["offset.json"], "input": str(legacy), "mode": "ext", "tifxyz_init": str(start),
                "margin": 4, "device": "cpu"}
        r = self.call("lasagna_fit", base)
        self.assertEqual(r["crop"], [16, 28, 16, 25, 9, 25])
        self.assertTrue(any("no base_shape_zyx" in n for n in r["notes"]))
        with self.assertRaises(vc3d_agent.ToolError) as cm:    # the box misses the halved surface (y 32)
            self.call("lasagna_fit", dict(base, crop=[0, 48, 0, 64, 16, 64]))
        self.assertIn("lies outside", str(cm.exception))
        bare = self.d / "bare" / "legacy.lasagna.json"         # no level array to read: refused, not guessed
        bare.parent.mkdir()
        bare.write_text(json.dumps(doc))
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", dict(base, input=str(bare)))
        self.assertIn("frame", str(cm.exception))

    def test_seed_mode_needs_model_h_unless_villa_works_it_out(self):
        base = {"config": ["init.json"], "input": str(self.manifest), "device": "cuda", "dry_run": True}
        with self.assertRaises(vc3d_agent.ToolError) as cm:        # fit.py: model-init=seed requires --model-h
            self.call("lasagna_fit", dict(base, seed=[1, 2, 3]))
        self.assertIn("model_h", str(cm.exception))
        self.assertNotIn("seed [x", str(cm.exception))
        self.assertEqual(self.call("lasagna_fit", dict(base, seed=[1, 2, 3], model_h=64))["exit"], 0)
        roi = dict(base, args={"corr-point-roi": True})            # works out the seed and model-h itself
        self.assertEqual(self.call("lasagna_fit", roi)["exit"], 0)
        with self.assertRaises(vc3d_agent.ToolError) as cm:        # needs the seed and its tifxyz
            self.call("lasagna_fit", dict(base, args={"approval-inpaint": "true"}))
        self.assertIn("seed [x", str(cm.exception))
        self.assertIn("approval-inpaint-tifxyz", str(cm.exception))
        self.assertNotIn("model_h", str(cm.exception))

    def test_the_fits_receipt_records_its_export(self):
        base = {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext", "tifxyz_init": str(self.start),
                "device": "cuda"}
        r = self.call("lasagna_fit", dict(base, export={"single_segment": True, "output_name": "seg.tifxyz"}))
        self.assertEqual(r["exit"], 0, r)
        rec = json.loads((Path(r["out"]) / "receipt.json").read_text())
        self.assertEqual([s["exit"] for s in rec["steps"]], [0, 0])
        self.assertTrue(any("fit2tifxyz" in str(x) for x in rec["steps"][1]["export"]))
        self.assertIn(r["export"]["tifxyz"][0]["path"], rec["outputs"])
        self.assertFalse((Path(r["export"]["out"]) / "receipt.json").exists())   # inside the fit's folder
        elsewhere = self.home / "exports" / "seg"
        r = self.call("lasagna_fit", dict(base, export={"single_segment": True, "out": str(elsewhere)}))
        self.assertTrue((elsewhere / "receipt.json").is_file())
        r = self.call("lasagna_fit", dict(base, export={"single_segment": True}),   # a failed export is recorded
                      FAKE_EXPORT_FAIL="1")
        rec = json.loads((Path(r["out"]) / "receipt.json").read_text())
        self.assertEqual((r["exit"], rec["steps"][1]["exit"]), (1, 1))

    def test_a_python_that_cannot_start_is_a_setup_error(self):
        # a ToolError is exit 2 (could not run), where a fit that ran and failed is exit 1
        gone = str(self.d / "no" / "python")
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                      "tifxyz_init": str(self.start), "device": "cuda"}, LASAGNA_PYTHON=gone)
        self.assertIn("LASAGNA_PYTHON", str(cm.exception))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("lasagna_export", {"model": str(self.start / "meta.json")}, LASAGNA_PYTHON=gone)

    def test_negative_crop_is_clipped_not_shifted(self):
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                      "tifxyz_init": str(self.start), "device": "cpu", "crop": [-8, 0, 0, 48, 48, 48]})
        self.assertEqual(r["crop"], [0, 0, 0, 40, 48, 48])
        self.assertEqual(self.seen(r)["loaded"]["crop"], [0, 0, 0, 40, 48, 48])

    def test_both_spellings_of_an_argument_count_as_fit_py_reads_them(self):
        cfg = self.d / "under.json"
        cfg.write_text(json.dumps({"args": {"model_init": "ext", "tifxyz_init": str(self.start)},
                                   "base": {"normal": 1.0}, "stages": [{"name": "s", "steps": 1}]}))
        r = self.call("lasagna_fit", {"config": [str(cfg)], "input": str(self.manifest), "device": "cuda"})
        self.assertEqual((r["exit"], r["mode"]), (0, "ext"), r)
        # a later underscore spelling beats the config's dash one, as villa's cli_json applies them
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "device": "cuda",
                                      "args": {"model_init": "ext", "tifxyz_init": str(self.start)}})
        self.assertEqual((r["exit"], r["mode"]), (0, "ext"), r)
        # kit's own fields win over every spelling, wherever it sits
        r = self.call("lasagna_fit", {"config": [str(cfg)], "input": str(self.manifest), "device": "cuda",
                                      "mode": "ext", "tifxyz_init": str(self.start),
                                      "args": {"model_init": "model", "out_dir": str(self.d / "elsewhere")}})
        self.assertEqual(r["exit"], 0, r)
        args = self.seen(r)["cfg"]["args"]
        self.assertEqual((args["model-init"], args["model_init"]), ("ext", "ext"))
        self.assertEqual((args["out-dir"], args["out_dir"]), (r["out"], r["out"]))
        self.assertFalse((self.d / "elsewhere").exists())
        # a relative path in either spelling resolves like every kit path
        rel = os.path.relpath(self.start, self.ctx.root)
        r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "device": "cuda",
                                      "mode": "ext", "args": {"tifxyz_init": rel}})
        self.assertEqual(self.seen(r)["cfg"]["args"]["tifxyz_init"], str(self.start.resolve()))

    def test_corr_point_roi_counts_its_second_dense_load(self):
        vol = self.d / "roi"
        for c in ("cos", "grad_mag", "nx", "ny"):
            (vol / f"{c}.zarr" / "0").mkdir(parents=True)
            (vol / f"{c}.zarr" / "0" / ".zarray").write_text(json.dumps({"shape": [1024] * 3, "chunks": [64] * 3,
                                                                       "dtype": "|u1"}))
        m = write_manifest(vol, shape=(1024, 1024, 1024), arrays=False)
        base = {"config": ["init.json"], "input": str(m), "seed": [5, 5, 5], "model_h": 64, "device": "cpu",
                "dry_run": True}
        self.assertEqual(self.call("lasagna_fit", base)["exit"], 0)                  # 4 GiB
        with self.assertRaises(vc3d_agent.ToolError) as cm:                         # 4 + 3 GiB
            self.call("lasagna_fit", dict(base, args={"corr_point_roi": True}))
        self.assertIn("7.0 GiB", str(cm.exception))

    def test_flatten_takes_its_surface_from_overrides(self):
        one = [{"path": str(self.start), "offset": 0}]
        r = self.call("lasagna_fit", {"config": ["offset.json"], "mode": "flatten", "device": "cuda",
                                      "dry_run": True, "overrides": {"external_surfaces": one}})
        self.assertEqual(r["exit"], 0)
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("lasagna_fit", {"config": ["offset.json"], "mode": "flatten", "device": "cuda",
                                      "dry_run": True, "overrides": {"external_surfaces": one + one}})

    def test_dry_run_without_a_device_is_a_gpu_command(self):
        remote = write_manifest(self.d / "remote", arrays=False)
        (remote.parent / lasagna.MARKER).write_text(json.dumps({"artifact_url": "https://x/", "manifest_file": "v"}))
        base = {"config": ["init.json"], "input": str(remote), "seed": [1, 2, 3], "model_h": 64}
        r = self.call("lasagna_fit", dict(base, dry_run=True))
        self.assertEqual((r["exit"], r["device"], Path(r["argv"][1]).name), (0, "cuda", "fit.py"))
        self.assertTrue(any("CUDA machine" in n for n in r["notes"]))
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", dict(base, device="cpu"))
        self.assertIn("device cuda with dry_run", str(cm.exception))

    def test_export_names_stay_inside_the_output_folder(self):
        model = self.d / "m.pt"
        model.write_bytes(b"x")
        for args in ({"output_name": "../../ESCAPED", "single_segment": True}, {"output_name": str(self.d / "abs")},
                     {"output_name": ".."}, {"prefix": "a/b_"}):
            with self.assertRaises(vc3d_agent.ToolError, msg=args) as cm:
                self.call("lasagna_export", dict(args, model=str(model)))
            self.assertIn("plain folder name", str(cm.exception))
        self.assertFalse((self.d / "abs").exists())
        self.assertEqual(list(self.d.rglob("ESCAPED")), [])

    def test_fit_export_is_checked_before_the_fit_runs(self):
        base = {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                "tifxyz_init": str(self.start), "device": "cuda"}
        for exp, want in (({"target_volume_shape_zyx": 4500}, "should be array"),
                          ({"timeout": "1h"}, "should be integer"),
                          ({"model": "/x.pt"}, "not model"),
                          ({"voxel_um": 2}, "not voxel_um"),
                          ({"output_name": "../x"}, "plain folder name"),
                          ({"out": str(self.ctx.root / "docs" / "lasagna_probe")}, "rule 6")):
            with self.assertRaises(vc3d_agent.ToolError, msg=exp) as cm:
                self.call("lasagna_fit", dict(base, export=exp))
            self.assertIn(want, str(cm.exception))
        self.assertFalse((self.home / "lasagna" / "fits").exists())                  # no fit ran

    def test_a_crashing_export_keeps_the_fits_result(self):
        real = vc3d_agent.run_logged

        def run(ctx, argv, *a, **kw):
            if any("fit2tifxyz" in str(x) for x in argv):
                raise RuntimeError("boom")
            return real(ctx, argv, *a, **kw)

        with mock.patch.object(vc3d_agent, "run_logged", run):
            r = self.call("lasagna_fit", {"config": ["offset.json"], "input": str(self.manifest), "mode": "ext",
                                          "tifxyz_init": str(self.start), "device": "cuda",
                                          "export": {"single_segment": True}})
        self.assertEqual(r["exit"], 1)
        self.assertIn("export crashed: RuntimeError: boom", r["error"])
        self.assertTrue(r["checkpoints"]["final"])
        self.assertTrue((Path(r["out"]) / "receipt.json").is_file())


class TestSelftest(Base):
    def setUp(self):
        super().setUp()
        self.script = self.d / "selftest_data_fake.py"
        self.script.write_text(SELFTEST_DATA)

    def test_passes_when_the_fit_turns_the_plane_and_the_control_does_not(self):
        with mock.patch.object(lasagna, "selftest_script", return_value=self.script):
            r = self.call("lasagna_selftest")
        self.assertTrue(r["passed"], r)
        self.assertEqual(r["exit"], 0)
        self.assertAlmostEqual(r["tilt"]["start"], 0.3, places=5)
        self.assertAlmostEqual(r["tilt"]["fit"], 0.0, places=5)
        self.assertAlmostEqual(r["tilt"]["control"], 0.3, places=5)
        self.assertTrue((Path(r["out"]) / "selftest.json").is_file())

    def test_fails_when_the_normal_term_does_nothing(self):
        with mock.patch.object(lasagna, "selftest_script", return_value=self.script):
            r = self.call("lasagna_selftest", FAKE_FIT_IGNORE_NORMAL=1)
        self.assertFalse(r["passed"])
        self.assertEqual(r["exit"], 1)
        self.assertFalse(r["checks"]["fit_turned_plane"])
        self.assertTrue(r["checks"]["control_kept_tilt"])

    def test_fails_when_a_fit_fails(self):
        with mock.patch.object(lasagna, "selftest_script", return_value=self.script):
            r = self.call("lasagna_selftest", FAKE_FIT_FAIL="boom")
        self.assertFalse(r["passed"])
        self.assertFalse(r["checks"]["fits_ran"])

    @unittest.skipUnless(HAVE_DATA_STACK, "needs numpy, zarr and tifffile")
    def test_real_data_script(self):
        r = self.call("lasagna_selftest")
        self.assertTrue(r["passed"], r)


# ---------------------------------------------------------------- manifests

class TestManifest(Base):
    def test_local_manifest_check(self):
        m = write_manifest(self.d / "in")
        r = self.call("lasagna_manifest", {"source": str(m)})
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["mode"], len(r["groups"])), ("local", 4))
        self.assertEqual(r["groups"][0]["shape_zyx"], [64, 64, 64])
        odd = write_manifest(self.d / "odd", name="odd.json", shape=(64, 64, 64))
        doc = json.loads(odd.read_text())
        doc["base_shape_zyx"] = [70, 64, 64]
        odd.write_text(json.dumps(doc))
        r = self.call("lasagna_manifest", {"source": str(odd)})
        self.assertFalse(r["ok"])
        self.assertEqual(r["exit"], 1)
        self.assertTrue(any(".lasagna.json" in p for p in r["problems"]))
        self.assertTrue(any("halved 0 times" in p for p in r["problems"]))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("lasagna_manifest", {"source": str(m), "crop": [0, 0, 0, 1, 1, 1]})
        listed = self.d / "list.lasagna.json"
        listed.write_text("[1, 2]")
        r = self.call("lasagna_manifest", {"source": str(listed)})
        self.assertEqual((r["ok"], r["exit"], r["problems"][0]), (False, 1, "the manifest is not a JSON object"))
        v3 = write_manifest(self.d / "v3", arrays=False)
        for c in ("cos", "grad_mag", "nx", "ny"):
            (self.d / "v3" / f"{c}.zarr" / "0").mkdir(parents=True)
            (self.d / "v3" / f"{c}.zarr" / "0" / "zarr.json").write_text("{not json")
        r = self.call("lasagna_manifest", {"source": str(v3)})
        self.assertFalse(r["ok"])
        self.assertIn("zarr.json", r["problems"][0])

    def published(self):
        """A published run folder served like S3: run/PHercX.lasagna.json with level-1 cos and level-0 others."""
        run = self.d / "bucket" / "run"
        groups = {"cos": {"zarr": "X_cos.ome.zarr/1", "scaledown": 1, "channels": ["cos"]}}
        groups.update({c: {"zarr": f"X_{c}.ome.zarr/0", "scaledown": 0, "channels": [c]} for c in ("grad_mag", "nx",
                                                                                                   "ny")})
        write_manifest(run, name="PHercX.lasagna.json", shape=(64, 64, 64), groups=groups)
        (run / "X_cos.ome.zarr" / ".zgroup").write_text('{"zarr_format": 2}')
        os.remove(run / "X_nx.ome.zarr" / "0" / "1" / "1" / "1")        # a chunk with no data
        return run

    def test_remote_and_mirror(self):
        self.published()
        with fakes.S3LikeServer(self.d / "bucket", false=0) as srv:
            url = f"{srv.url}/run/PHercX.lasagna.json"
            r = self.call("lasagna_manifest", {"source": url})
            self.assertEqual(r["mode"], "remote", r)
            marker = json.loads((Path(r["manifest"]).parent / lasagna.MARKER).read_text())
            self.assertEqual(marker, {"artifact_url": f"{srv.url}/run/", "manifest_file": "PHercX.lasagna.json"})
            self.assertTrue(r["ok"])

            r = self.call("lasagna_manifest", {"source": url, "crop": [24, 24, 24, 16, 16, 16]})
            self.assertEqual(r["mode"], "mirror", r)
            steps = {s["group"]: s for s in r["mirror"]}
            self.assertEqual(steps["cos"]["chunks"], 1)                    # level 1: voxels 12..20
            self.assertEqual(steps["grad_mag"]["chunks"], 8)               # level 0: 24..40 crosses 32 on each axis
            self.assertEqual((steps["nx"]["copied"], steps["nx"]["absent_no_data"]), (7, 1))
            folder = Path(r["manifest"]).parent
            self.assertTrue((folder / "X_cos.ome.zarr" / "1" / "0" / "0" / "0").is_file())
            self.assertTrue((folder / "X_cos.ome.zarr" / ".zgroup").is_file())
            self.assertFalse((folder / lasagna.MARKER).exists())
            doc = json.loads(Path(r["manifest"]).read_text())
            self.assertEqual(doc["kit_crop"], [24, 24, 24, 16, 16, 16])
            self.assertEqual(doc["kit_mirror_of"], url)
            again = self.call("lasagna_manifest", {"source": r["manifest"]})
            self.assertTrue(again["ok"], again)

            # the mirror fits on CPU with its crop
            start = plane(self.d / "s.tifxyz", y=32, x0=26, z0=26, step=2, rows=4, cols=4)
            fit = self.call("lasagna_fit", {"config": ["offset.json"], "input": r["manifest"], "mode": "ext",
                                            "tifxyz_init": str(start)})
            self.assertEqual(self.seen(fit)["loaded"]["crop"], [24, 24, 24, 16, 16, 16])

            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_manifest", {"source": url, "crop": [0, 0, 0, 64, 64, 64], "max_chunks": 3})
            self.assertIn("max_chunks 3", str(cm.exception))

            # cos is at level 1, so a crop starting on an odd voxel grows to an even one
            r = self.call("lasagna_manifest", {"source": url, "crop": [25, 24, 24, 15, 16, 16]})
            self.assertEqual(r["kit_crop"], [24, 24, 24, 16, 16, 16])
            self.assertEqual(r["crop_snapped"]["crop_asked"], [25, 24, 24, 15, 16, 16])

            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_manifest", {"source": f"{srv.url}/run/Missing.lasagna.json"})
            self.assertIn("HTTP 404", str(cm.exception))
            with self.assertRaises(vc3d_agent.ToolError):
                self.call("lasagna_manifest", {"source": url, "umbilicus": f"{srv.url}/run/nothing.json"})

    def test_hostile_level_metadata_is_refused(self):
        run = self.published()
        za = run / "X_nx.ome.zarr" / "0" / ".zarray"
        za.write_text(json.dumps(dict(json.loads(za.read_text()), dimension_separator="/../../../../escape/")))
        with fakes.S3LikeServer(self.d / "bucket", false=0) as srv:
            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_manifest", {"source": f"{srv.url}/run/PHercX.lasagna.json",
                                               "crop": [0, 0, 0, 8, 8, 8]})
        self.assertIn("dimension_separator", str(cm.exception))
        self.assertFalse(any(self.d.glob("**/escape")))

    def test_umbilicus(self):
        self.published()
        u = self.d / "umb.json"
        u.write_text(json.dumps({"control_points": [{"x": 32, "y": 32, "z": 0}, {"x": 32, "y": 32, "z": 63}]}))
        with fakes.S3LikeServer(self.d / "bucket", false=0) as srv:
            url = f"{srv.url}/run/PHercX.lasagna.json"
            r = self.call("lasagna_manifest", {"source": url, "umbilicus": str(u)})
            self.assertEqual(r["umbilicus_json"], "umbilicus.json")
            self.assertTrue((Path(r["manifest"]).parent / "umbilicus.json").is_file())
            u.write_text(json.dumps({"points": []}))
            with self.assertRaises(vc3d_agent.ToolError):
                self.call("lasagna_manifest", {"source": url, "umbilicus": str(u)})
            # the published manifest's own umbilicus comes along, but only from inside the run folder
            run = self.d / "bucket" / "run"
            doc = json.loads((run / "PHercX.lasagna.json").read_text())
            (run / "umb.json").write_text(json.dumps({"control_points": [{"x": 1, "y": 2, "z": 3}]}))
            (run / "PHercX.lasagna.json").write_text(json.dumps(dict(doc, umbilicus_json="umb.json")))
            r = self.call("lasagna_manifest", {"source": url})
            self.assertTrue((Path(r["manifest"]).parent / "umb.json").is_file())
            (run / "PHercX.lasagna.json").write_text(json.dumps(dict(doc, umbilicus_json="../../escape.json")))
            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_manifest", {"source": url})
            self.assertIn("inside the run folder", str(cm.exception))

    def test_run_folder_listing(self):
        doc = {"groups": {c: {"zarr": f"{c}/0", "scaledown": 0, "channels": [c]} for c in ("grad_mag", "nx", "ny")}}
        pages = {
            "https://b.s3.amazonaws.com/?list-type=2&prefix=run%2F&delimiter=%2F":
                b"<ListBucketResult><Key>run/A.lasagna.json</Key><Key>run/notes.txt</Key></ListBucketResult>",
            "https://b.s3.amazonaws.com/run/A.lasagna.json": json.dumps(doc).encode(),
        }

        def opener(req, timeout=None):
            return io.BytesIO(pages[req.full_url])
        base, name, got = lasagna.remote_manifest("s3://b/run/", opener=opener)
        self.assertEqual((base, name, got), ("https://b.s3.amazonaws.com/run/", "A.lasagna.json", doc))
        pages["https://b.s3.amazonaws.com/?list-type=2&prefix=run%2F&delimiter=%2F"] = b"<ListBucketResult/>"
        with self.assertRaises(lasagna.LasagnaError):
            lasagna.remote_manifest("s3://b/run/", opener=opener)


# ---------------------------------------------------------------- the fit service client
    def test_local_manifest_takes_no_url_only_arguments(self):
        m = write_manifest(self.d / "loc")
        for extra in ({"umbilicus": "u.json"}, {"out": str(self.d / "o")}, {"max_chunks": 5},
                      {"crop": [0, 0, 0, 8, 8, 8]}):
            with self.assertRaises(vc3d_agent.ToolError, msg=extra) as cm:
                self.call("lasagna_manifest", dict(extra, source=str(m)))
            self.assertIn("published (URL) source", str(cm.exception))
        self.assertFalse((self.d / "o").exists())
        m2 = write_manifest(self.d / "loc2", umbilicus_json="umbilicus.json")
        r = self.call("lasagna_manifest", {"source": str(m2)})
        self.assertFalse(r["ok"])
        self.assertIn("umbilicus_json", r["problems"][-1])
        (m2.parent / "umbilicus.json").write_text(json.dumps({"control_points": [{"x": 1, "y": 2, "z": 3}]}))
        r = self.call("lasagna_manifest", {"source": str(m2)})
        self.assertEqual((r["ok"], r["umbilicus_json"]), (True, "umbilicus.json"))

    def test_malformed_level_metadata_through_the_tools(self):
        m = write_manifest(self.d / "bad")
        (m.parent / "nx.zarr" / "0" / ".zarray").write_text("[1, 2]")
        (m.parent / "ny.zarr" / "0" / ".zarray").write_bytes(b"\xff\xfe{")
        r = self.call("lasagna_manifest", {"source": str(m)})
        self.assertEqual((r["ok"], r["exit"]), (False, 1))
        self.assertEqual(sum("nx" in q or "ny" in q for q in r["problems"]), 2, r["problems"])
        with self.assertRaises(vc3d_agent.ToolError) as cm:
            self.call("lasagna_fit", {"config": ["offset.json"], "input": str(m), "mode": "ext",
                                      "tifxyz_init": str(plane(self.d / "s.tifxyz")), "device": "cpu"})
        self.assertIn("cannot size group", str(cm.exception))

    def test_a_failed_mirror_says_how_to_resume(self):
        self.published()
        real = lasagna.http_get

        def flaky(url, *a, **kw):
            if "/X_nx.ome.zarr/0/" in url and not url.endswith((".zarray", ".zattrs", ".zgroup")):
                raise lasagna.urllib.error.URLError("connection reset")
            return real(url, *a, **kw)

        with fakes.S3LikeServer(self.d / "bucket", false=0) as srv, mock.patch.object(lasagna, "http_get", flaky):
            out = self.home / "mirror"
            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_manifest", {"source": f"{srv.url}/run/PHercX.lasagna.json",
                                               "crop": [24, 24, 24, 16, 16, 16], "out": str(out)})
        self.assertIn(f"out={out}", str(cm.exception))
        self.assertIn("resume", str(cm.exception))


    def test_a_cut_off_download_says_how_to_resume(self):
        self.published()
        real = lasagna.s3retry.open_url

        class Cut:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                raise http.client.IncompleteRead(b"x" * 16, 16)

        def cut(req, *a, **kw):
            url = req.full_url
            if "/X_nx.ome.zarr/0/" in url and not url.endswith((".zarray", ".zattrs", ".zgroup")):
                return Cut()
            return real(req, *a, **kw)

        with fakes.S3LikeServer(self.d / "bucket", false=0) as srv, mock.patch.object(lasagna.s3retry, "open_url", cut):
            out = self.home / "mirror"
            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_manifest", {"source": f"{srv.url}/run/PHercX.lasagna.json",
                                               "crop": [24, 24, 24, 16, 16, 16], "out": str(out)})
        self.assertIn("IncompleteRead", str(cm.exception))
        self.assertIn(f"out={out}", str(cm.exception))


class FakeService:
    """villa's fit service as far as the client uses it: the API header, health, datasets, jobs, results."""

    def __init__(self, results):
        import http.server
        self.bodies, self.headers, self.polls = [], [], {}
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, obj=None, raw=None):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def check(self):
                outer.headers.append(self.headers.get("X-Fit-Service-API-Version"))
                if self.headers.get("X-Fit-Service-API-Version") != "2":
                    self.reply(426, {"error": "upgrade"})
                    return False
                return True

            def do_GET(self):  # noqa: N802
                if not self.check():
                    return
                parts = self.path.strip("/").split("/")
                if self.path == "/health":
                    return self.reply(200, {"status": "ok", "api_version": "2"})
                if self.path == "/datasets":
                    return self.reply(200, {"datasets": [{"name": "v.lasagna.json", "path": "/data/v.lasagna.json"}]})
                if parts[0] == "jobs" and len(parts) == 2:
                    n = outer.polls[parts[1]] = outer.polls.get(parts[1], 0) + 1
                    if parts[1] == "bad":
                        return self.reply(200, {"job_id": "bad", "state": "error", "error": "model-init=ext requires "
                                                "exactly one external_surfaces entry, got 0"})
                    return self.reply(200, {"job_id": parts[1], "state": "running" if n < 3 else "finished",
                                            "step": n, "total_steps": 3, "loss": 0.1})
                if parts[0] == "jobs" and parts[2:] == ["results"]:
                    return self.reply(200, raw=results[parts[1]])
                self.reply(404, {"error": f"no {self.path}"})

            def do_POST(self):  # noqa: N802
                if not self.check():
                    return
                n = int(self.headers.get("Content-Length") or 0)
                outer.bodies.append(json.loads(self.rfile.read(n) or b"{}"))
                if self.path == "/jobs":
                    body = outer.bodies[-1]
                    init = ((body.get("config") or {}).get("args") or {}).get("model-init")
                    if init == "model" and not (body.get("model_input") or body.get("model_data")):
                        return self.reply(400, {"error": "model-init=model requires request model_data or "
                                                         "model_input"})
                    return self.reply(200, {"status": "queued", "job_id": "j1"})
                self.reply(200, {"status": "ok"})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def results_tar(member="agent.tifxyz"):
    with tempfile.TemporaryDirectory() as t:
        plane(Path(t) / "agent.tifxyz")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for f in sorted((Path(t) / "agent.tifxyz").iterdir()):
                tar.add(f, arcname=f"{member}/{f.name}")
        return buf.getvalue()


class TestService(Base):
    def test_discover_and_default_url(self):
        folder = self.userhome / ".fit_services"
        folder.mkdir()
        with FakeService({}) as svc:
            port = svc.url.rsplit(":", 1)[1]
            (folder / "1.json").write_text(json.dumps({"pid": 2 ** 22 + 12345, "port": 1, "host": "0.0.0.0"}))
            (folder / "2.json").write_text(json.dumps({"pid": os.getpid(), "port": int(port), "host": "127.0.0.1",
                                                       "datasets": ["v.lasagna.json"]}))
            # an older live service whose file name sorts last as text: the newest file wins, not the last name
            (folder / "9.json").write_text(json.dumps({"pid": os.getpid(), "port": 2, "host": "::"}))
            os.utime(folder / "9.json", (1_600_000_000, 1_600_000_000))
            r = self.call("lasagna_service", {"action": "discover"})
            self.assertEqual(r["live"], ["http://127.0.0.1:2", svc.url])
            self.assertEqual(r["services"][0]["url"], "http://127.0.0.1:2")
            self.assertEqual(self.call("lasagna_service", {"action": "health"})["url"], svc.url)
        empty = self.d / "nobody"
        empty.mkdir()
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("lasagna_service", {"action": "health"}, HOME=empty)

    def test_submit_wait_and_results(self):
        with FakeService({"j1": results_tar(), "evil": results_tar("../evil")}) as svc:
            self.assertEqual(self.call("lasagna_service", {"action": "datasets", "url": svc.url})["datasets"][0]["name"],
                             "v.lasagna.json")
            sub = {"action": "submit", "url": svc.url, "config": "offset.json", "data_input": "/data/v.lasagna.json",
                   "args": {"depth": 2}, "overrides": {"external_surfaces": [{"path": "/h/s.tifxyz", "offset": 1}]}}
            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_service", sub)                  # mode model without its checkpoint
            self.assertIn("model_file", str(cm.exception))
            ckpt = self.d / "model.pt"
            ckpt.write_bytes(b"\x00weights")
            r = self.call("lasagna_service", dict(sub, model_file=str(ckpt)))
            self.assertEqual(r["job_id"], "j1")
            body = svc.bodies[-1]
            self.assertEqual(body["model_data"], "AHdlaWdodHM=")
            self.call("lasagna_service", dict(sub, model_input="/host/model.pt"))
            self.assertEqual(svc.bodies[-1]["model_input"], "/host/model.pt")
            self.assertEqual(body["data_input"], "/data/v.lasagna.json")
            self.assertEqual((body["config_name"], body["single_segment"], body["output_name"]),
                             ("offset.json", True, "agent.tifxyz"))
            self.assertEqual(body["config"]["args"], {"model-init": "model", "depth": 2})
            self.assertEqual(body["config"]["external_surfaces"], [{"path": "/h/s.tifxyz", "offset": 1}])
            self.assertEqual(set(svc.headers), {"2"})

            job = self.call("lasagna_service", {"action": "job", "url": svc.url, "id": "j1", "wait": 30})
            self.assertEqual(job["state"], "finished")
            self.assertNotIn("exit", job)
            bad = self.call("lasagna_service", {"action": "job", "url": svc.url, "id": "bad"})
            self.assertEqual(bad["exit"], 1)
            self.assertTrue(any("external_surfaces" in h for h in bad["hints"]))

            got = self.call("lasagna_service", {"action": "results", "url": svc.url, "id": "j1"})
            self.assertEqual(got["files"], 4)
            self.assertEqual(got["tifxyz"][0]["valid_vertices"], 25)
            with self.assertRaises(vc3d_agent.ToolError):
                self.call("lasagna_service", {"action": "results", "url": svc.url, "id": "evil"})

            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_service", {"action": "submit", "url": svc.url, "config": "offset.json"})
            self.assertIn("data_input", str(cm.exception))
            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_service", {"action": "job", "url": svc.url})
            self.assertIn("needs id", str(cm.exception))
            with self.assertRaises(vc3d_agent.ToolError) as cm:
                self.call("lasagna_service", {"action": "health", "url": svc.url + "/nowhere"})
            self.assertIn("HTTP 404", str(cm.exception))

    def test_header_is_required_by_the_service(self):
        with FakeService({}) as svc:
            import urllib.error
            import urllib.request
            req = urllib.request.Request(svc.url + "/health")
            with self.assertRaises(urllib.error.HTTPError) as cm:
                lasagna.service_opener(svc.url).open(req, timeout=10)
            self.assertEqual(cm.exception.code, 426)
            self.assertEqual(lasagna.service_call(svc.url, "GET", "/health")["status"], "ok")


# ---------------------------------------------------------------- command line

class TestCommandLine(Base):
    def run_cli(self, argv, **env):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, dict(self.env, **{k: str(v) for k, v in env.items()}), clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = lasagna.main(argv)
        text = out.getvalue()
        return rc, (json.loads(text) if text.lstrip().startswith(("{", "[")) else text)

    def test_registered_in_kit(self):
        commands = set(next(a for a in cli.build_parser()._actions if a.dest == "command").choices)
        self.assertIn("lasagna", commands)

    def test_tools(self):
        rc, text = self.run_cli(["tools"])
        self.assertEqual(rc, 0)
        for name in lasagna.COMMANDS:
            self.assertIn(name, text)
        rc, schemas = self.run_cli(["tools", "--json"])
        self.assertEqual({s["name"] for s in schemas}, {f"lasagna_{c}" for c in lasagna.COMMANDS})

    def test_exit_codes(self):
        manifest = write_manifest(self.d / "in")
        start = plane(self.d / "start.tifxyz")
        rc, r = self.run_cli(["status"])
        self.assertEqual((rc, r["found"]), (0, True))
        rc, r = self.run_cli(["fit", "--config", "offset.json", "--input", str(manifest), "--mode", "ext",
                              "--tifxyz-init", str(start), "--device", "cuda"])
        self.assertEqual((rc, r["exit"]), (0, 0))
        args = self.d / "args.json"
        args.write_text(json.dumps({"config": ["offset.json"], "input": str(manifest), "mode": "ext",
                                    "tifxyz_init": str(start)}))
        rc, r = self.run_cli(["fit", f"@{args}", "--device", "cuda"], FAKE_FIT_FAIL="boom")
        self.assertEqual((rc, r["error"]), (1, "fit.py exited 1"))
        rc, r = self.run_cli(["fit", "--bogus", "1"])
        self.assertEqual(rc, 2)
        self.assertIn("bad arguments", r["error"])
        rc, r = self.run_cli(["configs", '{"name": "nope.json"}'])
        self.assertEqual(rc, 2)
        self.assertIn("villa ships", r["error"])
        rc, r = self.run_cli(["configs", "[1]"])
        self.assertEqual(rc, 2)

    def test_help_and_crashes(self):
        rc, r = self.run_cli(["fit", "--help"])
        self.assertEqual((rc, r["name"]), (0, "lasagna_fit"))
        self.assertIn("tifxyz_init", r["arguments"]["properties"])
        rc, r = self.run_cli(["status", "-h"])
        self.assertEqual(rc, 0)
        with mock.patch.dict(vc3d_agent.TOOLS["lasagna_configs"].__dict__,
                             {"handler": mock.Mock(side_effect=RuntimeError("boom"))}):
            rc, r = self.run_cli(["configs"])
        self.assertEqual(rc, 1)
        self.assertIn("crashed: RuntimeError: boom", r["error"])

    def test_background_job(self):
        model = self.d / "model.pt"
        model.write_bytes(b"x")
        rc, r = self.run_cli(["export", "--model", str(model), "--background"])
        self.assertEqual(rc, 0)
        done = vc3d_agent.job_wait(vc3d_agent.Context(env=self.env), r["job"], timeout=60)
        self.assertEqual(done["status"], "succeeded", done)
        self.assertEqual(done["result"]["exit"], 0)
        rc, r = self.run_cli(["status", "--background"])           # a quick tool has no background mode
        self.assertEqual(rc, 2)

    def test_flags_around_the_json_arguments(self):
        manifest = write_manifest(self.d / "in")
        start = plane(self.d / "start.tifxyz")
        spec = self.d / "spec.json"
        spec.write_text(json.dumps({"config": ["offset.json"], "input": str(manifest), "mode": "ext",
                                    "tifxyz_init": str(start), "device": "cuda"}))
        rc, r = self.run_cli(["fit", "--dry-run", f"@{spec}"])           # a boolean, then the arguments
        self.assertEqual((rc, r["dry_run"]), (0, True), r)
        rc, r = self.run_cli(["fit", "--dry-run", "--depth", "2", "--depth", "3", f"@{spec}"])
        self.assertEqual(rc, 2)
        self.assertIn("given twice", r["error"])
        rc, r = self.run_cli(["fit", "--config", "offset.json", "--external-surfaces", '{"path": "a.tifxyz"}',
                              "--external-surfaces", '{"path": "b.tifxyz"}', "--dry-run"])
        self.assertEqual(rc, 2)                       # a clean JSON error from the tool, not a traceback
        self.assertIn("error", r)
        rc, r = self.run_cli(["fit", f"@{spec}", "--dry-run", "stray"])
        self.assertEqual(rc, 2)
        self.assertIn("unexpected 'stray'", r["error"])


# ---------------------------------------------------------------- the shim itself

class TestShim(unittest.TestCase):
    def load(self):
        """scripts/lasagna/fit_cpu_shim.py with stand-ins for torch, fit and fit_data."""
        fake_torch = mock.MagicMock()
        fake_torch.device = lambda text: type("D", (), {"type": str(text).split(":")[0],
                                                       "__str__": lambda self: str(text)})()
        fake_data = mock.MagicMock()
        mods = {"torch": fake_torch, "fit": mock.MagicMock(), "fit_data": fake_data}
        with mock.patch.dict(sys.modules, mods):
            spec = importlib.util.spec_from_file_location("fit_cpu_shim", ROOT / "scripts/lasagna/fit_cpu_shim.py")
            shim = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(shim)
        return shim, fake_data

    def test_crop_from_env(self):
        shim, _ = self.load()
        self.assertIsNone(shim.crop_from_env(""))
        self.assertEqual(shim.crop_from_env("1, 2, 3, 4.0, 5, 6"), (1, 2, 3, 4, 5, 6))
        for bad in ("1,2,3", "0,0,0,0,1,1", "-8,0,0,24,8,8"):
            with self.assertRaises(SystemExit):
                shim.crop_from_env(bad)

    def test_dense_off_cuda_and_unchanged_on_cuda(self):
        shim, data = self.load()
        streaming = shim._orig_streaming
        with mock.patch.dict(os.environ, {"KIT_LASAGNA_CROP": "0,0,0,8,8,8"}), \
                contextlib.redirect_stdout(io.StringIO()):
            shim._dense_off_cuda(path="v.lasagna.json", device="cpu")
        kw = shim._orig_load_3d.call_args.kwargs
        self.assertEqual((kw["crop"], kw["cuda_gridsample"], kw["path"]), ((0, 0, 0, 8, 8, 8), False, "v.lasagna.json"))
        shim._dense_off_cuda(path="v.lasagna.json", device="cuda:0")
        streaming.assert_called_once()
        self.assertIs(data.load_3d_streaming, shim._dense_off_cuda)

    def test_dense_load_is_read_once_per_arguments(self):
        shim, data = self.load()
        with mock.patch.dict(os.environ, {"KIT_LASAGNA_CROP": "0,0,0,8,8,8"}), \
                contextlib.redirect_stdout(io.StringIO()):
            a = shim._dense_off_cuda(path="v.lasagna.json", device="cpu")
            b = shim._dense_off_cuda(path="v.lasagna.json", device="cpu")
            self.assertIs(a, b)
            self.assertEqual(shim._orig_load_3d.call_count, 1)
            shim._dense_off_cuda(path="v.lasagna.json", device="cpu", skip_channels={"cos"})
            self.assertEqual(shim._orig_load_3d.call_count, 2)
            self.assertEqual(len(shim._last), 1)               # only the latest load is kept

    def test_fit_pys_own_uncropped_load_gets_the_box(self):
        # fit.py's corr-point-roi stage calls fit_data.load_3d off CUDA with no crop: it must read the box only
        shim, data = self.load()
        self.assertIs(data.load_3d, shim._load_3d_in_box)
        orig = shim._orig_load_3d
        with mock.patch.dict(os.environ, {"KIT_LASAGNA_CROP": "0,0,0,8,8,8"}), \
                contextlib.redirect_stdout(io.StringIO()):
            data.load_3d(path="v.lasagna.json", device="cpu", skip_channels={"cos", "pred_dt"})
            self.assertEqual(orig.call_args.kwargs["crop"], (0, 0, 0, 8, 8, 8))
            data.load_3d(path="v.lasagna.json", device="cpu", crop=(8, 8, 8, 8, 8, 8))
            self.assertEqual(orig.call_args.kwargs["crop"], (8, 8, 8, 8, 8, 8))     # a caller's own crop stays
            data.load_3d(path="v.lasagna.json", device="cuda:0")
            self.assertIsNone(orig.call_args.kwargs.get("crop"))                     # CUDA: unchanged
        data.load_3d(path="v.lasagna.json", device="cpu")
        self.assertIsNone(orig.call_args.kwargs.get("crop"))                         # no box set: unchanged


if __name__ == "__main__":
    unittest.main()
