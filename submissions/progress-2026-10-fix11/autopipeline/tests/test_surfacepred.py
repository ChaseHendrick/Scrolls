"""kit/surfacepred.py: the patch grid of a box run, the level choice, packaging for VC3D, the Dice, grid, seating and
contrast checks on synthetic volumes. The Modal runner's tests (a script of the source repository) are in
test_surfacepred_modal.py, which AutoPipeline's public cut leaves out with the runners. No network, no GPU, no Modal
call. Map tests skip without numpy (and scipy, numcodecs, tifffile where they
need them); the VC3D open test skips without vc_gen_normalgrids (set VC_BIN to a villa build).
"""
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from kit import surfacepred as sp  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None
try:
    import scipy  # noqa: F401
except ImportError:  # pragma: no cover
    scipy = None
try:
    import numcodecs
except ImportError:  # pragma: no cover
    numcodecs = None
try:
    import tifffile
except ImportError:  # pragma: no cover
    tifffile = None

TEST_A = "9408:9984,3648:4224,3648:4224"
SHAPE_A = [19400, 7703, 7703]


def brute_patches(shape, box, patch=192, overlap=0.5):
    """Every patch of the whole-volume grid that touches the box, counted the slow way."""
    starts = [sp.sliding_steps(n, patch, overlap) for n in shape]
    roi = sp.clamp_bbox(box, shape, patch)
    n = 1
    for axis in range(3):
        n *= sum(1 for s in starts[axis] if s < roi[axis][1] and s + patch > roi[axis][0])
    return n


class LevelTest(unittest.TestCase):
    def test_catalog_bands(self):
        self.assertEqual(sp.choose_level(9.366), (0, 9.366))
        self.assertEqual(sp.choose_level(8.64), (0, 8.64))
        self.assertEqual(sp.choose_level(7.91), (0, 7.91))
        self.assertEqual(sp.choose_level(2.403), (2, 9.612))     # 2.403 rounds to 2.40, inside the band
        self.assertEqual(sp.choose_level("2.215")[0], 2)
        self.assertEqual(sp.choose_level(2.399), (2, 9.596))

    def test_refusals(self):
        for um in (4.0, 9.6, 3.24, 1.0, 12.0, "abc", None):
            with self.assertRaises(sp.SurfacePredError, msg=um):
                sp.choose_level(um)


class ShapeTest(unittest.TestCase):
    def test_ceil_levels_of_the_published_predictions(self):
        self.assertEqual([s[0] for s in sp.pyramid_shapes(SHAPE_A)], [19400, 9700, 4850, 2425, 1213, 607])
        self.assertEqual([s[0] for s in sp.pyramid_shapes([3781, 7618, 7618])], [3781, 1891, 946, 473, 237, 119])
        self.assertEqual(sp.pyramid_shapes([3781, 7618, 7618])[5], [119, 239, 239])

    def test_villas_round_rule_comes_out_short_and_vc3d_refuses_it(self):
        rnd = sp.round_shapes(SHAPE_A)
        self.assertEqual([s[0] for s in rnd], [19400, 9700, 4850, 2425, 1212, 606])
        self.assertFalse(sp.shape_ok(rnd[4][0], sp.ceil_shape(SHAPE_A, 4)[0], 192))
        rnd2 = sp.round_shapes([3781, 7618, 7618])
        self.assertEqual([s[0] for s in rnd2], [3781, 1890, 945, 472, 236, 118])
        for k in range(1, 6):
            self.assertFalse(sp.shape_ok(rnd2[k][0], sp.ceil_shape([3781], k)[0], 192), k)

    def test_shape_ok_allows_padding_under_one_chunk(self):
        self.assertTrue(sp.shape_ok(1213, 1213, 192))
        self.assertTrue(sp.shape_ok(1213 + 191, 1213, 192))
        self.assertFalse(sp.shape_ok(1213 + 192, 1213, 192))
        self.assertFalse(sp.shape_ok(1212, 1213, 192))


class PatchGridTest(unittest.TestCase):
    def test_sliding_steps_reproduce_villas_uniform_grid(self):
        steps = sp.sliding_steps(19400)
        self.assertEqual((steps[0], steps[-1]), (0, 19400 - 192))
        self.assertEqual(len(steps), math.ceil((19400 - 192) / 96) + 1)
        self.assertEqual(sp.sliding_steps(192), [0])
        self.assertEqual(sp.sliding_steps(300, 192, 0.5), [0, 54, 108])
        with self.assertRaises(sp.SurfacePredError):
            sp.sliding_steps(100)
        with self.assertRaises(sp.SurfacePredError):
            sp.sliding_steps(1000, 192, 1.5)

    def test_overlap_is_overlap_as_villa_1989(self):
        # villa #1989: the step is 1 - overlap of the patch; before it 0.25 and 0.75 swapped places
        self.assertEqual(len(sp.sliding_steps(1000, 192, 0.25)), math.ceil(808 / 144) + 1)
        self.assertEqual(len(sp.sliding_steps(1000, 192, 0.75)), math.ceil(808 / 48) + 1)
        self.assertEqual(len(sp.sliding_steps(1000, 192, 0.0)), math.ceil(808 / 192) + 1)
        self.assertEqual(sp.sliding_steps(1000, 192, 0.5), sp.sliding_steps(1000))
        with self.assertRaises(sp.SurfacePredError):
            sp.sliding_steps(1000, 192, 1.0)

    def test_test_a_is_512_patches_on_27_published_chunks(self):
        plan = sp.plan_box(SHAPE_A, sp.parse_bbox(TEST_A))
        self.assertEqual(plan["patches"], 512)
        self.assertEqual([len(s) for s in plan["patch_starts"]], [8, 8, 8])
        self.assertEqual((plan["patch_starts"][0][0], plan["patch_starts"][0][-1]), (9270, 9938))
        self.assertEqual((plan["patch_starts"][1][0], plan["patch_starts"][1][-1]), (3518, 4183))
        self.assertTrue(plan["chunk_aligned"])
        self.assertEqual(plan["chunks"], [[49, 51], [19, 21], [19, 21]])
        self.assertEqual(plan["chunk_count"], 27)
        self.assertEqual(plan["voxels"], 576 ** 3)
        self.assertAlmostEqual(plan["tflop"], 512 * sp.TFLOP_PER_PATCH, places=1)
        self.assertLess(plan["gpu_seconds"][0], plan["gpu_seconds"][1])

    def test_every_preset_box_matches_the_slow_count_and_covers_its_box(self):
        for shape, bbox in ((SHAPE_A, TEST_A), ([3781, 7618, 7618], "1728:2304,3456:4032,3456:4032"),
                            ([21000, 6700, 9100], "6912:7488,1152:1728,4992:5568")):
            box = sp.parse_bbox(bbox)
            plan = sp.plan_box(shape, box)
            self.assertEqual(plan["patches"], brute_patches(shape, box), bbox)
            self.assertTrue(plan["chunk_aligned"], bbox)
            for axis, starts in enumerate(plan["patch_starts"]):
                lo, hi = box[axis]
                covered = set()
                for s in starts:
                    covered.update(range(max(lo, s), min(hi, s + 192)))
                self.assertEqual(covered, set(range(lo, hi)), (bbox, axis))

    def test_clamp_grows_a_short_box_and_refuses_one_outside(self):
        self.assertEqual(sp.clamp_bbox([[0, 50], [10, 20], [0, 400]], [1000, 1000, 300]),
                         [[0, 192], [10, 202], [0, 300]])
        self.assertEqual(sp.clamp_bbox([[990, 1000], [0, 192], [0, 192]], [1000, 1000, 1000])[0], [808, 1000])
        with self.assertRaises(sp.SurfacePredError):
            sp.clamp_bbox([[2000, 2100], [0, 192], [0, 192]], [1000, 1000, 1000])
        self.assertFalse(sp.plan_box([1000, 1000, 1000], [[10, 400], [0, 384], [0, 384]])["chunk_aligned"])

    def test_bbox_text(self):
        self.assertEqual(sp.parse_bbox(TEST_A), [[9408, 9984], [3648, 4224], [3648, 4224]])
        self.assertEqual(sp.format_bbox(sp.parse_bbox(TEST_A)), TEST_A)
        for bad in ("1:2,3:4", "1:2,3:4,5", "a:b,1:2,1:2", "5:5,1:2,1:2", "-1:2,1:2,1:2", "1:2,3:4,5:6,7:8"):
            with self.assertRaises(sp.SurfacePredError, msg=bad):
                sp.parse_bbox(bad)

    def test_chunk_box_stays_inside(self):
        self.assertEqual(sp.chunk_box([9700, 3900, 3900], SHAPE_A), [[9408, 9984], [3648, 4224], [3648, 4224]])
        self.assertEqual(sp.chunk_box([5, 5, 7700], SHAPE_A), [[0, 576], [0, 576], [7296, 7703]])


class CommandTest(unittest.TestCase):
    def test_urls_and_names(self):
        url = f"{sp.BUCKET_URL}/PHerc0841/volumes/20260319124803-2.403um-0.2m-77keV-masked.zarr/"
        self.assertEqual(sp.s3_url(url), f"s3://{sp.BUCKET}/PHerc0841/volumes/20260319124803-2.403um-0.2m-77keV-"
                                         "masked.zarr/")
        self.assertTrue(sp.predict_input(url, 2).endswith("masked.zarr/2/"))
        self.assertTrue(sp.predict_input(url, 0).endswith("masked.zarr/"))
        with self.assertRaises(sp.SurfacePredError):
            sp.s3_url("https://example.org/x.zarr")
        self.assertEqual(sp.prediction_name("20250821151531", 0),
                         "20250821151531-surface-20260413222639-surface-m7-L0-th0.2.zarr")
        self.assertEqual(sp.prediction_name("20260319124803", 2, 0.5),
                         "20260319124803-surface-20260413222639-surface-m7-L2-th0.5.zarr")

    def test_argv(self):
        a = sp.predict_argv("/m", "s3://b/v.zarr/", "/o", TEST_A)
        self.assertEqual(a[:3], ["python", "-c", sp.PUBLISHED_LAUNCHER])
        plans = sp.predict_argv("/m", "s3://b/v.zarr/", "/o", TEST_A, normalization="plans")
        self.assertEqual(plans[0], "vesuvius.predict")
        self.assertEqual(plans[1:], a[3:])
        with self.assertRaises(sp.SurfacePredError):
            sp.predict_argv("/m", "s3://b/v.zarr/", "/o", TEST_A, normalization="ct")
        self.assertNotIn("--normalization", a)
        for flag in ("--disable_tta", "--input_anon", "--verbose"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--bbox") + 1], TEST_A)
        self.assertEqual(a[a.index("--model_type") + 1], "nnunet")
        self.assertEqual(a[a.index("--overlap") + 1], "0.5")
        self.assertEqual(a[a.index("--batch_size") + 1], "4")
        f = sp.finalize_argv("/l", "/f.zarr", 0.5)
        self.assertEqual(f[:3], ["vesuvius.blend_and_finalize", "/l", "/f.zarr"])
        self.assertIn("--threshold", f)
        self.assertEqual(f[f.index("--threshold_value") + 1], "0.5")
        self.assertEqual(f[f.index("--chunk_size") + 1], "192,192,192")
        g = sp.normalgrids_argv("/p.zarr", "/g", threads=8)
        self.assertEqual(g[:2], ["vc_gen_normalgrids", "generate"])
        for flag, value in (("--level", "0"), ("--spiral-step", "20"), ("--grid-step", "64"),
                            ("--sparse-volume", "1"), ("--prune-min-length-px", "20")):
            self.assertEqual(g[g.index(flag) + 1], value)

    def test_normalization_problem(self):
        note = "Using model-declared normalization 'ct' instead of CLI/default 'instance_zscore'.\n"
        self.assertIsNone(sp.normalization_problem("loading\n" + note, "plans"))
        self.assertIsNone(sp.normalization_problem("loading\n", "published"))
        self.assertIn("not applied", sp.normalization_problem("loading\n", "plans"))
        self.assertIn("did not restore", sp.normalization_problem(note, "published"))
        self.assertIn("not one of", sp.normalization_problem("", "ct"))

    def test_published_launcher_turns_the_plans_off(self):
        # A stand-in for villa e0bbb8b's inference module: main() asks the module-level lookup, as
        # Inferer does (models/run/inference.py 534-547), and prints the note when the plans win.
        fake = (
            "import sys\n"
            "def _nnunet_normalization_from_model_info(model_info):\n"
            "    return 'ct', {'mean': 87.5}\n"
            "def main():\n"
            "    scheme, _ = _nnunet_normalization_from_model_info({})\n"
            "    if scheme is not None and scheme != 'instance_zscore':\n"
            "        print(f\"Using model-declared normalization {scheme!r} instead of CLI/default 'instance_zscore'.\")\n"
            "    print('ARGV', sys.argv[0], ' '.join(sys.argv[1:]))\n"
            "    return 0\n")
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp, "vesuvius", "models", "run")
            pkg.mkdir(parents=True)
            for d in (Path(tmp, "vesuvius"), Path(tmp, "vesuvius", "models"), pkg):
                (d / "__init__.py").write_text("")
            (pkg / "inference.py").write_text(fake)
            env = {**os.environ, "PYTHONPATH": tmp}
            argv = sp.predict_argv("/m", "s3://b/v.zarr/", "/o", TEST_A)
            run = subprocess.run([sys.executable, *argv[1:]], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIsNone(sp.normalization_problem(run.stdout, "published"))
            self.assertIn("ARGV vesuvius.predict --model_path /m", run.stdout)
            # The same module run as the console script does: the plans win, and the check catches it.
            plain = subprocess.run([sys.executable, "-c", "import vesuvius.models.run.inference as i; i.main()"],
                                   env=env, capture_output=True, text=True)
            self.assertIsNone(sp.normalization_problem(plain.stdout, "plans"))
            self.assertIsNotNone(sp.normalization_problem(plain.stdout, "published"))

    @unittest.skipUnless(os.environ.get("KIT_VILLA_SRC") and
                         os.path.isfile(os.path.join(os.environ["KIT_VILLA_SRC"],
                                                     "vesuvius/src/vesuvius/models/run/inference.py")),
                         "no villa checkout (set KIT_VILLA_SRC to one)")
    def test_villa_source_has_what_the_launcher_patches(self):
        src = Path(os.environ["KIT_VILLA_SRC"], "vesuvius/src/vesuvius/models/run/inference.py").read_text()
        self.assertIn("def _nnunet_normalization_from_model_info(model_info):", src)
        self.assertIn("_nnunet_normalization_from_model_info(model_info)\n", src)
        self.assertIn(sp.PLANS_NOTE, src)
        self.assertIn("def main():", src)

    def test_cli_plan_and_level(self):
        env = {**os.environ, "PYTHONPATH": str(REPO)}
        out = subprocess.run([sys.executable, "-m", "kit", "surfacepred", "plan", "--shape", "19400", "7703", "7703",
                              "--bbox", TEST_A], capture_output=True, text=True, cwd=REPO, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["patches"], 512)
        out = subprocess.run([sys.executable, "-m", "kit", "surfacepred", "level", "2.403"], capture_output=True,
                             text=True, cwd=REPO, env=env)
        self.assertEqual(json.loads(out.stdout)["level"], 2)
        out = subprocess.run([sys.executable, "-m", "kit", "surfacepred", "level", "4.0"], capture_output=True,
                             text=True, cwd=REPO, env=env)
        self.assertNotEqual(out.returncode, 0)


def blosc(cname="zstd", clevel=1):
    return {"blocksize": 0, "clevel": clevel, "cname": cname, "id": "blosc", "shuffle": 1}


def write_final(root, data, chunk=16, codec=None):
    """A vesuvius-style final.zarr: one zarr v2 array (1, Z, Y, X), dot-separated keys, no empty chunks."""
    codec = codec or blosc()
    root = Path(root)
    root.mkdir(parents=True)
    shape = [1, *data.shape]
    (root / ".zarray").write_text(json.dumps({
        "chunks": [1, chunk, chunk, chunk], "compressor": codec, "dtype": "|u1", "fill_value": 0, "filters": None,
        "order": "C", "shape": shape, "zarr_format": 2}))
    c = numcodecs.get_codec(dict(codec))
    n = [-(-s // chunk) for s in data.shape]
    for z in range(n[0]):
        for y in range(n[1]):
            for x in range(n[2]):
                block = np.zeros((chunk,) * 3, dtype=np.uint8)
                part = data[z * chunk:(z + 1) * chunk, y * chunk:(y + 1) * chunk, x * chunk:(x + 1) * chunk]
                block[:part.shape[0], :part.shape[1], :part.shape[2]] = part
                if block.any():
                    (root / f"0.{z}.{y}.{x}").write_bytes(c.encode(block.tobytes()))


def read_level(out, k, shape, chunk=16):
    """Decode one packaged level by hand ("z/y/x" keys), padding cut off."""
    c = numcodecs.get_codec(dict(sp.BLOSC))
    n = [-(-s // chunk) for s in shape]
    full = np.zeros([a * chunk for a in n], dtype=np.uint8)
    for z in range(n[0]):
        for y in range(n[1]):
            for x in range(n[2]):
                p = Path(out, str(k), str(z), str(y), str(x))
                if p.is_file():
                    full[z * chunk:(z + 1) * chunk, y * chunk:(y + 1) * chunk, x * chunk:(x + 1) * chunk] = \
                        np.frombuffer(c.decode(p.read_bytes()), dtype=np.uint8).reshape((chunk,) * 3)
    return full[:shape[0], :shape[1], :shape[2]]


@unittest.skipIf(np is None or numcodecs is None, "needs numpy and numcodecs")
class PackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        d = np.zeros((50, 70, 90), dtype=np.uint8)
        d[10:22] = 255                                  # a thick slab, so every coarse level keeps some surface
        d[30:46, 5:60, 40:88] = 255
        d[0, 0, 0] = 255                                # an even index: kept down to the last level
        self.data = d

    def tearDown(self):
        self.tmp.cleanup()

    def package(self, codec=None):
        final, out = self.root / "final.zarr", self.root / "pred.zarr"
        write_final(final, self.data, codec=codec)
        rec = {"preset": "unit", "threshold": 0.2}
        with redirect_stdout(io.StringIO()):
            info = sp.package(final, out, 9.366, record=rec, name="unit")
        return info, out

    def test_round_trip_levels_meta_and_record(self):
        info, out = self.package()
        self.assertTrue(info["level0_copied"])
        shapes = sp.pyramid_shapes([50, 70, 90])
        self.assertEqual(info["level_shapes"], shapes)
        self.assertEqual(shapes[5], [2, 3, 3])
        for k in range(6):
            z = json.loads((out / str(k) / ".zarray").read_text())
            self.assertEqual(z["shape"], shapes[k])
            self.assertEqual((z["dtype"], z["fill_value"], z["dimension_separator"]), ("|u1", 0, "/"))
            want = self.data[::2 ** k, ::2 ** k, ::2 ** k]
            self.assertTrue(np.array_equal(read_level(out, k, shapes[k]), want), k)
        self.assertTrue((out / "0" / "0" / "0" / "0").is_file())        # z/y/x keys, not 0.z.y.x
        self.assertFalse((out / "0" / "3" / "4" / "0").exists())        # an empty chunk is not written
        meta = json.loads((out / "meta.json").read_text())
        self.assertEqual((meta["slices"], meta["height"], meta["width"], meta["voxelsize"], meta["type"]),
                         (50, 70, 90, 9.366, "vol"))
        self.assertEqual(json.loads((out / "run.json").read_text()), {"preset": "unit", "threshold": 0.2})
        self.assertFalse((out / "metadata.json").exists())
        attrs = json.loads((out / ".zattrs").read_text())["multiscales"][0]
        self.assertEqual([d["coordinateTransformations"][0]["scale"][0] for d in attrs["datasets"]],
                         [1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
        self.assertEqual(sp.check_package(out), [])

    def test_another_codec_is_decoded_and_written_again(self):
        info, out = self.package(codec=blosc("lz4", 5))
        self.assertFalse(info["level0_copied"])
        self.assertTrue(np.array_equal(read_level(out, 0, [50, 70, 90]), self.data))
        self.assertEqual(sp.check_package(out), [])

    def test_check_catches_what_vc3d_refuses(self):
        _, out = self.package()
        z = json.loads((out / "3" / ".zarray").read_text())
        z["shape"] = [6, 9, 11]                               # villa's round rule at level 3: one short
        (out / "3" / ".zarray").write_text(json.dumps(z))
        self.assertTrue(any("level 3" in p and "ceil" in p for p in sp.check_package(out)))
        z["shape"] = [7, 9, 12]
        (out / "3" / ".zarray").write_text(json.dumps(z))
        # VC3D reads metadata.json only when there is no meta.json (Volume.cpp 1031-1034), so one with no "scan"
        # beside a meta.json is not a problem (volume_meta writes a meta.json beside such a file)
        (out / "metadata.json").write_text(json.dumps({"run": "x"}))
        self.assertEqual(sp.check_package(out), [])
        meta = (out / "meta.json").read_text()
        (out / "meta.json").unlink()
        self.assertTrue(any("scan" in p for p in sp.check_package(out)))
        (out / "metadata.json").unlink()
        self.assertTrue(any("meta.json" in p for p in sp.check_package(out)))
        (out / "meta.json").write_text(meta)
        self.assertEqual(sp.check_package(out), [])

    def fake_volume(self, verdict="PASS"):
        """A stand-in for the surface-predict Modal volume: runs/testX/ with a receipt, the package and its grids,
        and a runner that copies off it as `modal volume get` does (a folder lands under the destination)."""
        import shutil
        _, out = self.package()
        vol = self.root / "vol"
        arm = vol / "runs" / "testX"
        arm.mkdir(parents=True)
        name = "X-surface-m7-L0-th0.2"
        shutil.copytree(out, arm / f"{name}.zarr")
        (arm / f"{name}.normal-grids" / "xy").mkdir(parents=True)
        (arm / f"{name}.normal-grids" / "metadata.json").write_text(json.dumps({"input-level": 0}))
        (arm / "receipt.json").write_text(json.dumps({"verdict": verdict, "why": "unit",
                                                      "package": {"path": f"/volume/surface-predict/runs/testX/{name}.zarr"}}))
        calls = []

        def run(argv):
            calls.append(argv)
            self.assertEqual(argv[:5], ["modal", "volume", "get", "--force", "surface-predict"])
            src, dest = vol / argv[5], Path(argv[6])
            if src.is_file():
                shutil.copyfile(src, dest)
            elif src.is_dir():
                shutil.copytree(src, dest / src.name)
            else:
                return 1
            return 0
        return run, calls, name

    def test_fetch_copies_a_passing_arm_off_the_volume_and_checks_it(self):
        run, calls, name = self.fake_volume()
        dest = self.root / "fetched"
        res = sp.fetch("testX", dest, run=run)
        self.assertEqual(res["problems"], [])
        self.assertEqual(res["external_prediction"], {"zarr": str(dest / f"{name}.zarr"),
                                                      "normal_grids": str(dest / f"{name}.normal-grids")})
        self.assertTrue((dest / f"{name}.normal-grids" / "metadata.json").is_file())
        self.assertTrue((dest / "receipt.json").is_file())
        self.assertFalse((dest / ".fetch").exists())
        self.assertEqual([c[5] for c in calls], ["runs/testX/receipt.json", f"runs/testX/{name}.zarr",
                                                 f"runs/testX/{name}.normal-grids"])
        with self.assertRaisesRegex(sp.SurfacePredError, "not empty"):
            sp.fetch("testX", dest, run=run)

    def test_fetch_refuses_a_failed_arm_and_needs_modal_allowed(self):
        run, calls, _ = self.fake_volume(verdict="FAIL")
        with self.assertRaisesRegex(sp.SurfacePredError, "receipt verdict FAIL"):
            sp.fetch("testX", self.root / "f1", run=run)
        self.assertEqual(len(calls), 1)                                  # the receipt only
        res = sp.fetch("testX", self.root / "f2", run=run, allow_fail=True)
        self.assertIn("not for tracing", res["warning"])
        with self.assertRaisesRegex(sp.SurfacePredError, "no receipt.json|exited 1"):
            sp.fetch("testY", self.root / "f3", run=run)
        env = {k: v for k, v in os.environ.items() if k != "KIT_ALLOW_MODAL"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(sp.SurfacePredError, "KIT_ALLOW_MODAL=1"):
                sp.fetch("testX", self.root / "f4")

    def test_refuses_a_folder_with_an_earlier_package(self):
        """Packaging into an old package would keep its chunks wherever the new prediction is empty."""
        _, out = self.package()
        stale = out / "0" / "3" / "4" / "5"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"old")
        with self.assertRaises(sp.SurfacePredError) as cm:
            sp.package(self.root / "final.zarr", out, 9.366)
        self.assertIn("not empty", str(cm.exception))
        empty = self.root / "empty.zarr"
        empty.mkdir()
        with redirect_stdout(io.StringIO()):
            sp.package(self.root / "final.zarr", empty, 9.366)            # an empty folder is fine
        self.assertEqual(sp.check_package(empty), [])

    def test_refusals(self):
        final, out = self.root / "final.zarr", self.root / "pred.zarr"
        write_final(final, self.data)
        out.mkdir()
        (out / "metadata.json").write_text("{}")
        with self.assertRaises(sp.SurfacePredError):
            sp.package(final, out, 9.366)
        z = json.loads((final / ".zarray").read_text())
        for key, value in (("dtype", "<f4"), ("fill_value", 255), ("shape", [2, 50, 70, 90])):
            bad = self.root / f"bad-{key}.zarr"
            bad.mkdir()
            (bad / ".zarray").write_text(json.dumps({**z, key: value}))
            with self.assertRaises(sp.SurfacePredError, msg=key):
                sp.package(bad, self.root / f"out-{key}", 9.366)

    def test_vc3d_opens_the_package(self):
        from kit import vc3d
        tools = vc3d.find_tools()
        if tools is None or not tools.has("vc_gen_normalgrids"):
            self.skipTest("no vc_gen_normalgrids (set VC_BIN to a villa build)")
        _, out = self.package()
        ok, text = sp.vc3d_open(out, tools)
        self.assertTrue(ok, text)
        z = json.loads((out / "4" / ".zarray").read_text())
        z["shape"] = [3, 4, 5]                                # under the ceil rule
        (out / "4" / ".zarray").write_text(json.dumps(z))
        ok, text = sp.vc3d_open(out, tools)
        self.assertFalse(ok, text)


def sheets(shape, period=12, thick=3, phase=0):
    """Oblique sheets: (z + y + x + phase) mod period < thick, so a shift along any axis moves them."""
    g = np.indices(shape).sum(0) + phase
    return ((g % period) < thick).astype(np.uint8) * 255


@unittest.skipIf(np is None or scipy is None, "needs numpy and scipy")
class DiceTest(unittest.TestCase):
    def test_identical_passes_and_controls_score_low(self):
        a = sheets((128, 128, 128))
        r = sp.compare_box(a, a, chunk=64)
        self.assertEqual((r["dice"], r["verdict"]["verdict"]), (1.0, "PASS"))
        for name in ("shift_z1", "shift_y1", "shift_x1"):
            self.assertAlmostEqual(r["controls"][name], 2 / 3, places=2)
        self.assertEqual(r["controls"]["shift_x4"], 0.0)
        self.assertEqual(r["controls"]["other_slab_z"], 0.0)          # 64 is 4 mod 12, past the 3 voxel sheets
        self.assertEqual(r["controls"], r["published_self_controls"])
        self.assertEqual(len(r["per_chunk"]), 8)
        self.assertEqual(r["per_chunk_min"], 1.0)
        self.assertEqual(r["ours_within_2_of_published"], 1.0)

    def test_a_one_voxel_offset_fails_and_is_found(self):
        a, b = sheets((128, 128, 128)), sheets((128, 128, 128), phase=1)
        r = sp.compare_box(a, b, chunk=64)
        self.assertEqual(r["verdict"]["verdict"], "FAIL")
        self.assertLess(r["dice"], 0.7)
        self.assertEqual(r["best_shift"]["dice"], 1.0)
        self.assertEqual(sum(abs(s) for s in r["best_shift"]["shift"]), 1)
        self.assertEqual(r["ours_within_2_of_published"], 1.0)          # close, but not the same voxels

    def test_thick_sheets_cannot_tell_a_shift_so_the_box_is_void(self):
        a = sheets((128, 128, 128), period=32, thick=30)
        r = sp.compare_box(a, a, chunk=64)
        self.assertEqual(r["verdict"]["verdict"], "VOID")

    def test_each_rule_can_fail_on_its_own(self):
        """dice_verdict: a high Dice does not pass when one control is high, VOID wins over everything, and a
        missing Dice fails."""
        low = {"shift_z1": 0.9, "shift_y1": 0.9, "shift_x1": 0.7, "shift_x4": 0.04, "other_slab_z": 0.18}
        ok = {"dice": 0.99, "controls": dict(low), "published_self_controls": dict(low)}
        self.assertEqual(sp.dice_verdict(ok)["verdict"], "PASS")
        high = {**ok, "controls": {**low, "shift_z1": 0.95}}
        v = sp.dice_verdict(high)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertIn("shift_z1", v["why"])
        self.assertEqual(sp.dice_verdict({**ok, "dice": 0.969})["verdict"], "FAIL")
        self.assertEqual(sp.dice_verdict({**ok, "dice": None})["verdict"], "FAIL")
        blind = {**ok, "published_self_controls": {**low, "other_slab_z": 0.93}}
        self.assertEqual(sp.dice_verdict(blind)["verdict"], "VOID")

    def test_a_thicker_map_with_a_good_dice_is_caught_by_a_control(self):
        """Ours = published plus 5 % extra voxels on the +z side: Dice still passes 0.97, but ours against the
        published map moved 1 voxel in z climbs past the 0.93 bar, so the run fails."""
        rng = np.random.default_rng(3)
        b = sheets((128, 128, 128), period=24, thick=12) > 0
        extra = np.roll(b, 1, axis=0) & ~b & (rng.random(b.shape) < 0.6)
        a = b | extra
        r = sp.compare_box(a, b, chunk=64)
        self.assertGreaterEqual(r["dice"], 0.97)
        self.assertLess(r["published_self_controls"]["shift_z1"], 0.93)
        self.assertGreaterEqual(r["controls"]["shift_z1"], 0.93)
        self.assertEqual(r["verdict"]["verdict"], "FAIL")

    def test_shape_errors(self):
        with self.assertRaises(sp.SurfacePredError):
            sp.compare_box(np.zeros((100, 100, 100)), np.zeros((100, 100, 99)))
        with self.assertRaises(sp.SurfacePredError):
            sp.compare_box(np.zeros((60, 100, 100)), np.zeros((60, 100, 100)))

    def test_threshold_order(self):
        self.assertEqual(sp.threshold_order(0.98, 0.91)["verdict"], "PASS")
        self.assertEqual(sp.threshold_order(0.91, 0.95)["verdict"], "FAIL")
        self.assertEqual(sp.threshold_order(0.91, 0.91)["verdict"], "FAIL")
        self.assertEqual(sp.threshold_order(None, 0.5)["verdict"], "FAIL")


def vertical_lines(s, lo=0, hi=576, spacing=13, step=8):
    """Polylines along v at u = 7 * s mod 13 + 13 k: a slice 100 away puts them 2 px off every line."""
    off = (7 * s) % spacing
    return [np.array([[u, v] for v in range(lo, hi, step)]) for u in range(lo + off, hi, spacing)]


@unittest.skipIf(np is None, "needs numpy")
class GridTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_and_read_back(self):
        lines = [np.array([[10, 10], [20, 15], [30, 30]]), np.array([[100, 5], [100, 105], [-20, 105]])]
        path = Path(self.tmp.name, "000100.grid")
        sp.write_grid(path, lines, (0, 0, 256, 256), meta={"slice": 100})
        head, got = sp.read_grid(path)
        self.assertEqual((head["version"], head["paths"], head["cell"], head["meta"]), (3, 2, 64, {"slice": 100}))
        self.assertEqual(head["buckets"], 16)
        for want, have in zip(lines, got):
            self.assertTrue(np.array_equal(want, have))
        self.assertEqual(sp.read_grid(b""), (None, []))
        with self.assertRaises(sp.SurfacePredError):
            sp.read_grid(b"\x00" * 60)
        with self.assertRaises(sp.SurfacePredError):
            sp.write_grid(path, [np.array([[0, 0], [200, 0]])], (0, 0, 256, 256))

    def test_agreement_and_shift(self):
        a = vertical_lines(100)
        r = sp.grid_agreement(a, a, (64, 512, 64, 512))
        self.assertEqual((r["a_within_1px"], r["b_within_1px"]), (1.0, 1.0))
        r = sp.grid_agreement(a, a, (64, 512, 64, 512), shift=(3, 0))
        self.assertEqual(r["a_within_1px"], 0.0)
        r = sp.grid_agreement(a, a, (64, 512, 64, 512), shift=(0, 3))   # along the lines: still on them
        self.assertGreater(r["a_within_1px"], 0.9)

    def test_seg_dist_equals_brute_force(self):
        # _seg_dist prunes segments far from each chunk of points; it must give the brute force distances exactly,
        # also where a point has no segment nearby (the full fallback) and for zero-length segments
        def brute(pts, segs):
            a, ab = segs[:, :2], segs[:, 2:] - segs[:, :2]
            ll = (ab ** 2).sum(1)
            ll[ll == 0] = 1e-9
            q = pts[:, None, :]
            t = np.clip(((q - a) * ab).sum(-1) / ll, 0, 1)
            return np.sqrt(((a + t[..., None] * ab - q) ** 2).sum(-1)).min(1)
        rng = np.random.default_rng(7)
        for span, short in ((40, False), (600, True), (600, False), (5000, False)):
            pts = rng.integers(0, span, (700, 2)).astype(float)
            segs = rng.integers(0, span, (500, 4)).astype(float)
            if short:
                segs[:, 2:] = segs[:, :2] + rng.integers(-8, 9, (500, 2))
            self.assertEqual(sp._seg_dist(pts, segs).tobytes(), brute(pts, segs).tobytes(), span)
        lines = vertical_lines(100)
        pts, segs = sp._points(lines, (0, 0), (64, 512, 64, 512)), sp._segments(lines, (3, 0), (64, 512, 64, 512), 8)
        self.assertEqual(sp._seg_dist(pts, segs).tobytes(), brute(pts, segs).tobytes())
        far = np.array([[10000.0, 10000.0], [0.0, 0.0]])
        self.assertEqual(sp._seg_dist(far, segs).tobytes(), brute(far, segs).tobytes())
        self.assertEqual(sp._seg_dist(far, np.zeros((0, 4))).tolist(), [np.inf, np.inf])
        # cases a review found: a pruned segment whose computed distance rounds just under 16 px, a NaN or
        # infinite segment (every brute force distance is NaN), and narrow integer dtypes, which wrap
        cases = [
            (np.array([[-0.1337461195270524, 0.0]]),
             np.array([[2499.446231076003, 0, 15.866253880472966, 0], [-16.133746119527054, -1, -16.133746119527054, 1]])),
            (np.array([[5.0, 5.0], [50.0, 50.0]]), np.array([[0, 0, 10, 10], [40, 40, 60, 60], [np.nan, 1, 2, 3]])),
            (np.array([[5.0, 5.0], [50.0, 50.0]]), np.array([[0, 0, 10, 10], [40, 40, 60, 60], [np.inf, 0, np.inf, 1]])),
            (np.array([[200, 10]], dtype=np.uint8), np.array([[190, 0, 210, 10]], dtype=np.uint8)),
        ]
        for dtype in (np.uint8, np.int8, np.uint16, np.int16):
            cases.append((rng.integers(0, 120, (300, 2)).astype(dtype), rng.integers(0, 120, (200, 4)).astype(dtype)))
        with np.errstate(all="ignore"):
            for pts, segs in cases:
                self.assertEqual(sp._seg_dist(pts, segs).tobytes(), brute(pts, segs).tobytes(), (pts.dtype, segs[:2]))

    def compare(self, ours_shift=0, same_every_slice=False):
        box = [[0, 576], [0, 576], [0, 576]]

        def load(which, direction, s):
            lines = vertical_lines(0 if same_every_slice else s)
            if which == "ours" and ours_shift:
                lines = [p + np.array([ours_shift, 0]) for p in lines]
            return lines
        return sp.compare_grids(load, box)

    def test_compare_grids_rules(self):
        r = self.compare()
        self.assertEqual(r["verdict"]["verdict"], "PASS", r["verdict"])
        self.assertEqual(len(r["slices"]), 6)                           # 4 xy and 2 xz slices
        self.assertLess(r["highest_control"], 0.2)
        self.assertEqual(self.compare(ours_shift=2)["verdict"]["verdict"], "FAIL")
        self.assertEqual(self.compare(same_every_slice=True)["verdict"]["verdict"], "VOID")

    def test_a_box_with_no_fixed_slice_fails_instead_of_passing_empty(self):
        def load(which, direction, s):
            raise AssertionError("nothing should be read")
        r = sp.compare_grids(load, [[0, 250], [0, 250], [0, 250]])
        self.assertEqual((r["slices"], r["verdict"]["verdict"]), ([], "FAIL"))
        self.assertIn("no fixed slice", r["verdict"]["why"])

    def test_ours_with_no_polylines_fails(self):
        box = [[0, 576], [0, 576], [0, 576]]

        def load(which, direction, s):
            return [] if which == "ours" else vertical_lines(s)
        self.assertEqual(sp.compare_grids(load, box)["verdict"]["verdict"], "FAIL")

    def test_fixed_slices_and_local_loader(self):
        plan = sp.grid_slices(sp.parse_bbox(TEST_A))
        self.assertEqual(plan["xy"]["slices"], [9600, 9700, 9800, 9900])
        self.assertEqual(plan["xz"]["slices"], [3900, 3950])
        self.assertEqual(plan["xy"]["window"], [3712, 4160, 3712, 4160])
        self.assertEqual(plan["xz"]["window"], [3712, 4160, 9472, 9920])
        d = Path(self.tmp.name, "g")
        (d / "xy").mkdir(parents=True)
        sp.write_grid(d / "xy" / "009600.grid", vertical_lines(9600, 3600, 4200), (3600, 3600, 640, 640))
        load = sp.grid_loader(d, d)
        self.assertEqual(len(load("ours", "xy", 9600)), len(vertical_lines(9600, 3600, 4200)))
        with self.assertRaises(sp.SurfacePredError):
            load("ours", "xy", 9700)


def planes(shape, first=10, spacing=14, thick=3):
    m = np.zeros(shape, dtype=np.uint8)
    for z in range(first, shape[0], spacing):
        m[z:z + thick] = 255
    return m


@unittest.skipIf(np is None or scipy is None, "needs numpy and scipy")
class SeatingTest(unittest.TestCase):
    def points(self, z):
        g = np.array([[x, y, z] for x in range(8, 56, 4) for y in range(8, 56, 4)], dtype=float)
        return g, np.tile([0.0, 0.0, 1.0], (len(g), 1))

    def test_on_the_sheet_passes_and_between_sheets_fails(self):
        pred = planes((160, 64, 64))                      # sheets at z 80..82 among others; spacing 14
        pts, nrm = self.points(81.0)
        r = sp.seating(pred, [0, 0, 0], pts, nrm)
        self.assertEqual(r["sheet_spacing_vox"], 14.0)
        self.assertEqual((r["seated"], r["displaced_plus"], r["displaced_minus"]), (1.0, 0.0, 0.0))
        self.assertEqual(r["verdict"]["verdict"], "PASS")
        pts, nrm = self.points(88.0)
        self.assertEqual(sp.seating(pred, [0, 0, 0], pts, nrm, spacing=14.0)["verdict"]["verdict"], "FAIL")

    def test_origin_and_empty_prediction(self):
        pred = planes((160, 64, 64))
        pts, nrm = self.points(1081.0)
        r = sp.seating(pred, [1000, 0, 0], pts, nrm, spacing=14.0)
        self.assertEqual(r["seated"], 1.0)
        r = sp.seating(np.zeros((160, 64, 64), np.uint8), [0, 0, 0], *self.points(81.0))
        self.assertEqual(r["verdict"]["verdict"], "VOID")

    def test_normals_of_a_plane(self):
        h, w = 6, 7
        xyz = np.zeros((h, w, 3))
        xyz[..., 0] = np.arange(w)[None, :] * 20
        xyz[..., 1] = np.arange(h)[:, None] * 20
        xyz[..., 2] = 50
        valid = np.ones((h, w), bool)
        valid[0, 0] = False
        pts, nrm = sp.surface_normals(xyz, valid)
        self.assertEqual(len(pts), (h - 2) * (w - 2))
        self.assertTrue(np.allclose(np.abs(nrm[:, 2]), 1.0))


@unittest.skipIf(np is None or tifffile is None, "needs numpy and tifffile")
class SurfaceFileTest(unittest.TestCase):
    def test_tifxyz_box_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, w = 9, 11
            x = np.tile(np.arange(w, dtype=np.float32) * 20 + 1000, (h, 1))
            y = np.tile((np.arange(h, dtype=np.float32) * 20 + 500)[:, None], (1, w))
            z = np.full((h, w), 4000.0, np.float32)
            for a in (x, y, z):
                a[0, :] = -1                               # an invalid row
            for name, a in zip("xyz", (x, y, z)):
                tifffile.imwrite(Path(tmp, f"{name}.tif"), a)
            xyz, valid = sp.read_surface(tmp)
            self.assertEqual((xyz.shape, int(valid.sum())), ((h, w, 3), (h - 1) * w))
            box, centre = sp.box_at_centre(xyz, valid, [21000, 6700, 9100])
            self.assertEqual(centre, [1100.0, 580.0, 4000.0])
            self.assertEqual(box, [[3648, 4224], [384, 960], [768, 1344]])
            box2, n = sp.box_from_points(xyz[valid], [21000, 6700, 9100])
            self.assertEqual(n, (h - 1) * w)
            pts, nrm = sp.surface_in_box(tmp, box)
            self.assertGreater(len(pts), 0)
            self.assertTrue(np.allclose(np.abs(nrm[:, 2]), 1.0))


@unittest.skipIf(np is None, "needs numpy")
class ContrastTest(unittest.TestCase):
    def volume(self, seed=0):
        rng = np.random.default_rng(seed)
        shape = (128, 96, 96)
        pred = np.zeros(shape, np.uint8)
        z = 3
        while z < shape[0] - 3:                            # irregular spacing: no half-box shift lines them up
            pred[z:z + 3] = 255
            z += int(rng.integers(9, 17))
        ct = rng.normal(80, 12, shape)
        ct[pred > 0] += 40
        return np.clip(ct, 1, 255).astype(np.uint8), pred, rng

    def test_a_prediction_on_the_sheets_passes(self):
        ct, pred, _ = self.volume()
        r = sp.ct_contrast(ct, pred)
        self.assertGreater(r["auc"], 0.9)
        self.assertLess(abs(r["other_slab_z"] - 0.5), 0.15)
        self.assertEqual(r["verdict"]["verdict"], "PASS")
        self.assertEqual(set(r["moved_reported_only"]), {"z+4", "z-4", "y+4", "y-4", "x+4", "x-4"})

    def test_a_prediction_off_the_sheets_fails(self):
        ct, pred, rng = self.volume()
        noise = (rng.random(ct.shape) < 0.2).astype(np.uint8)
        self.assertEqual(sp.ct_contrast(ct, noise)["verdict"]["verdict"], "FAIL")
        other, _, _ = self.volume(seed=5)
        _, pred5, _ = self.volume(seed=5)
        self.assertEqual(sp.ct_contrast(ct, pred5)["verdict"]["verdict"], "FAIL")
        self.assertEqual(sp.ct_contrast(ct, np.zeros_like(pred))["verdict"]["verdict"], "FAIL")

    def test_errors(self):
        ct, pred, _ = self.volume()
        with self.assertRaises(sp.SurfacePredError):
            sp.ct_contrast(ct.astype(np.float32), pred)
        with self.assertRaises(sp.SurfacePredError):
            sp.ct_contrast(ct[:, :, :90], pred)

if __name__ == "__main__":
    unittest.main()
