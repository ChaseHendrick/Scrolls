"""kit ink3d: a 3D ink volume read onto a traced sheet on the render's own canvas, the model-free sheet pitch, the
moved-sheet control and the engines, on a flat synthetic surface between parallel synthetic sheets."""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
    import tifffile
    HAVE = True
except ImportError:
    HAVE = False

from kit import ink3d  # noqa: E402

PITCH = 12          # voxels between synthetic sheets
Z0 = 40             # the traced sheet
VOXEL_UM = 2.4


def ct_value(z, y, x):
    d = (z - Z0) % PITCH
    d = min(d, PITCH - d)
    return int(round(200 * math.exp(-(d * d) / 2.0))) + 10


def ink_on_traced(z, y, x):
    """Ink in stripes of x on the traced sheet only."""
    return 255 if abs(z - Z0) <= 1 and (x // 8) % 2 == 0 else 0


def ink_on_neighbour(z, y, x):
    """The same stripes two sheets out, none on the traced sheet: a model that reads the wrong sheet."""
    return 255 if abs(z - (Z0 + 2 * PITCH)) <= 1 and (x // 8) % 2 == 0 else 0


@unittest.skipUnless(HAVE, "kit ink3d needs numpy and tifffile")
class TestInk3D(unittest.TestCase):
    def setUp(self):
        import vc3d_fakes as fakes
        self.fakes = fakes
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.mesh = fakes.write_tifxyz(self.d / "mesh", fakes.plane(float(Z0), x0=8.0, step=4.0), rows=9, cols=9,
                                       scale=0.25)
        self.ct = fakes.write_group(self.d / "ct.zarr", (96, 64, 64), ct_value, binned="zyx")
        self.render = fakes.write_group(self.d / "render.zarr", (5, 36, 36), lambda z, y, x: 100)
        self.ink = fakes.write_group(self.d / "ink.zarr", (96, 64, 64), ink_on_traced, binned="zyx")
        self.wrong = fakes.write_group(self.d / "wrong.zarr", (96, 64, 64), ink_on_neighbour, binned="zyx")
        ink3d.EXTENSIONS.clear()

    def tearDown(self):
        ink3d.EXTENSIONS.clear()
        self.tmp.cleanup()

    def published(self, name, vol):
        ink3d.register(name, {"engine": "published", "origin": "ours", "licence": "test", "status": "experimental",
                              "why": "synthetic", "volumes": {str(self.ct): str(vol)}, "map_factor": 1,
                              "value_range": [0, 255], "needs": ["numpy"], "compute": "cpu"})

    def test_pitch_is_read_from_the_ct_alone(self):
        M, shape = ink3d.canvas(self.mesh, self.render)
        self.assertEqual(shape, (36, 36))
        p = ink3d.sheet_pitch(ink3d.open_volume(self.ct, VOXEL_UM), M, shape, VOXEL_UM)
        self.assertAlmostEqual(p["pitch_um"], PITCH * VOXEL_UM, places=3)
        self.assertEqual((p["minus_um"], p["plus_um"]), (-PITCH * VOXEL_UM, PITCH * VOXEL_UM))

    def test_a_flat_ct_has_no_pitch_and_refuses(self):
        flat = self.fakes.write_group(self.d / "flat.zarr", (96, 64, 64), lambda z, y, x: 50)
        M, shape = ink3d.canvas(self.mesh)
        with self.assertRaisesRegex(ink3d.Ink3DError, "no sheet peak"):
            ink3d.sheet_pitch(ink3d.open_volume(flat, VOXEL_UM), M, shape, VOXEL_UM)

    def test_render_on_another_canvas_is_refused(self):
        other = self.fakes.write_group(self.d / "other.zarr", (5, 30, 36), lambda z, y, x: 1)
        with self.assertRaisesRegex(ink3d.Ink3DError, "not layers by the mesh's canvas"):
            ink3d.canvas(self.mesh, other)

    def test_on_sheet_ink_lights_f_and_not_the_moved_sheet_control(self):
        self.published("synthetic-3d", self.ink)
        rec = ink3d.run("synthetic-3d", self.mesh, self.render, self.ct, VOXEL_UM, self.d / "out")
        self.assertEqual((rec["exit"], rec["dims"], rec["engine"]), (0, "3d", "published"))
        self.assertAlmostEqual(rec["pitch"]["pitch_um"], PITCH * VOXEL_UM, places=3)
        self.assertAlmostEqual(rec["control_shift_um"], 2 * PITCH * VOXEL_UM, places=3)
        f = tifffile.imread(rec["maps"]["f"]["path"]).astype(float)
        r = tifffile.imread(rec["maps"]["r"]["path"]).astype(float)
        self.assertEqual(f.shape, (36, 36))
        ok = f > 0                                              # rendered pixels (not the border, which has no normal)
        self.assertGreater(ok.mean(), 0.5)
        self.assertTrue(np.array_equal(ok, r > 0))
        # the canvas column c samples x = 8 + c (scale 0.25, step 4): stripes of x // 8 even are ink
        x = 8 + np.arange(36)
        stripes = ((x // 8) % 2 == 0)[None, :].repeat(36, 0)
        self.assertGreater(f[stripes & ok].mean(), 55000)
        self.assertLess(f[~stripes & ok].mean(), 6000)
        self.assertLess(r[ok].max(), 2.0)                         # 1 + round(0 * 65534): no ink two pitches away
        self.assertIn("moved-sheet", rec["maps"]["r"]["control"])
        saved = json.loads((self.d / "out" / "ink.json").read_text())
        self.assertEqual(saved["maps"]["f"]["path"], rec["maps"]["f"]["path"])
        self.assertEqual(saved["model"]["status"], "experimental")

    def test_ink_on_the_wrong_sheet_shows_in_the_control_not_f(self):
        self.published("wrong-sheet", self.wrong)
        rec = ink3d.run("wrong-sheet", self.mesh, self.render, self.ct, VOXEL_UM, self.d / "out")
        f = tifffile.imread(rec["maps"]["f"]["path"]).astype(float)
        r = tifffile.imread(rec["maps"]["r"]["path"]).astype(float)
        self.assertLess(f.max(), 2.0)
        self.assertGreater(r[r > 0].mean(), 20000)                     # the control can fail a model: it sees this one
        self.assertLess(rec["comparison"]["r"]["f_mean_minus_r_mean"], 0)

    def test_a_scan_with_no_published_volume_is_refused(self):
        ink3d.register("nothing-here", {"engine": "published", "volumes": {}, "status": "experimental"})
        with self.assertRaisesRegex(ink3d.Ink3DError, "no published 3D prediction"):
            ink3d.run("nothing-here", self.mesh, self.render, self.ct, VOXEL_UM, self.d / "out", pitch_um=28.8)

    def test_command_engine_gets_the_chunks_it_must_infer(self):
        script = self.d / "model.py"
        script.write_text(
            "import json, shutil, sys\n"
            "src, out, targets, mesh = sys.argv[1:5]\n"
            "t = json.load(open(targets))\n"
            "assert t and all(len(k) == 3 for k in t), t\n"
            "open(out + '.seen', 'w').write(json.dumps({'targets': t, 'mesh': mesh}))\n"
            "shutil.copytree(src, out)\n")
        ink3d.register("cmd-3d", {"engine": "command", "status": "experimental", "map_factor": 1,
                                  "chunk": 32, "value_range": [0, 255],
                                  "command": [sys.executable, str(script), str(self.ink), "{output}", "{targets}",
                                              "{mesh}"]})
        rec = ink3d.run("cmd-3d", self.mesh, self.render, self.ct, VOXEL_UM, self.d / "out")
        seen = json.loads(Path(rec["prediction"] + ".seen").read_text())
        self.assertEqual(seen["mesh"], str(self.mesh))
        # level 0 of the CT has 32^3 chunks: the sheet at z 40 and the moved sheets at 40 -+ 24 sit in z chunks 0 and 1,
        # x and y 8 to 43 in chunks 0 and 1
        self.assertEqual(sorted({k[0] for k in seen["targets"]}), [0, 1, 2])
        self.assertEqual(rec["targets"], len(seen["targets"]))
        f = tifffile.imread(rec["maps"]["f"]["path"]).astype(float)
        self.assertGreater(f.max(), 60000)

    def test_a_failing_engine_is_an_error_not_a_map(self):
        ink3d.register("broken", {"engine": "command", "status": "experimental", "map_factor": 1,
                                  "command": [sys.executable, "-c", "import sys; sys.exit(3)", "{output}"]})
        with self.assertRaisesRegex(ink3d.Ink3DError, "exited 3"):
            ink3d.run("broken", self.mesh, self.render, self.ct, VOXEL_UM, self.d / "out", pitch_um=28.8)
        self.assertFalse((self.d / "out" / "ink_f.tif").exists())

    def test_specs_are_checked(self):
        with self.assertRaisesRegex(ink3d.Ink3DError, "engine is one of"):
            ink3d.register("x", {"engine": "magic"})
        with self.assertRaisesRegex(ink3d.Ink3DError, "must name"):
            ink3d.register("x", {"engine": "command", "command": ["prog"]})
        with self.assertRaisesRegex(ink3d.Ink3DError, "status is one of"):
            ink3d.register("x", {"engine": "published", "status": "great"})
        for name, spec in ink3d.MODELS.items():
            self.assertEqual(ink3d.check_spec(name, spec), [], name)
            self.assertIn(spec["status"], ("experimental", "pending", "failed"), name)   # none has beaten 2.5D
            self.assertTrue(spec.get("licence") and spec.get("why"), name)

    def test_registered_3d_model_and_listing(self):
        reg = {"mine": {"dims": "3d", "engine": "villa-full3d", "checkpoint": str(self.d / "absent.pth"),
                        "status": "experimental"}, "reader-v3": {"engine": "villa"}}
        self.assertTrue(ink3d.is_3d("mine", reg))
        self.assertFalse(ink3d.is_3d("reader-v3", reg))
        lst = ink3d.listing(reg, env={})
        self.assertFalse(lst["models"]["mine"]["needs"]["weights"])
        self.assertFalse(lst["models"]["team-3d-paris4"]["needs"]["env:KIT_GAMBIARRA"])

    def test_g_codes_decode_before_blending(self):
        codes = self.fakes.write_group(self.d / "codes.zarr", (8, 8, 8), lambda z, y, x: 0 if x < 4 else 255)
        dec = ink3d.Decoded(ink3d.open_volume(codes))
        v = dec.sample(0, np.array([[1.0, 4.0, 4.0], [6.0, 4.0, 4.0], [3.5, 4.0, 4.0]]))
        self.assertAlmostEqual(v[0], 0.0)
        self.assertGreater(v[1], 254.0)
        self.assertAlmostEqual(v[2], v[1] / 2, delta=1.0)     # half a no-prediction voxel, never a low logit

    def test_villa_entry_point_patches_only_the_point_reader(self):
        import types
        calls = {}
        mod = types.ModuleType("vesuvius.ink_detection.inference.infer_full3d_tifxyz")
        mod.read_volume_source = lambda d: "VOL"
        mod._open_shared_volume = lambda src, lvl, cache_dir=None, cache_max_gb=None: types.SimpleNamespace(
            chunks=(64, 64, 64))
        mod.read_tifxyz_points = None

        def main(argv):
            calls["argv"] = argv
            calls["points"] = mod.read_tifxyz_points("mesh")
            return 0
        mod.main = main
        names = ["vesuvius", "vesuvius.ink_detection", "vesuvius.ink_detection.inference",
                 "vesuvius.ink_detection.inference.infer_full3d_tifxyz"]
        saved = {n: sys.modules.get(n) for n in names}
        for n in names[:-1]:
            sys.modules[n] = types.ModuleType(n)
        sys.modules[names[-1]] = mod
        sys.modules["vesuvius.ink_detection.inference"].infer_full3d_tifxyz = mod
        try:
            t = self.d / "t.json"
            t.write_text(json.dumps([[0, 1, 2], [1, 1, 2]]))
            self.assertEqual(ink3d.villa_main(["ck.pth", "m", "o.zarr", "--targets", str(t), "--level", "1"]), 0)
        finally:
            for n, m in saved.items():
                if m is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = m
        self.assertEqual(calls["argv"][:5], ["m", "ck.pth", "o.zarr", "--resolution", "1"])
        x, y, z, ok = calls["points"]
        self.assertEqual(z.tolist(), [[32.0, 96.0]])
        self.assertEqual(x.tolist(), [[160.0, 160.0]])


if __name__ == "__main__":
    unittest.main()
