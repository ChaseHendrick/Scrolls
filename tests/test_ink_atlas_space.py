"""Ink Atlas (spaces/ink-atlas): the data layer on a tiny fake atlas laid out like the dataset, and the page's API.

Runs without network: atlasdata.Atlas(root=...) reads a local folder; gradio is not needed."""

import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "ink-atlas"

try:
    import numpy as np
    from PIL import Image
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False


def _load():
    spec = importlib.util.spec_from_file_location("atlasdata_under_test", SPACE / "atlasdata.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake(root, A):
    """One surface of 300 x 400 pixels: a covered rectangle, a model whose map is the ensemble plus noise, a flat
    model, and Hecate with the centre window only."""
    sid, path = "kbh-PHercTEST_1_2_3", "surfaces/PHercTEST/kbh-PHercTEST_1_2_3"
    d = root / path
    rng = np.random.default_rng(0)
    h, w = 300, 400
    cover = np.zeros((h, w), bool)
    cover[20:280, 30:370] = True
    signal = np.zeros((h, w))
    signal[100:140, 150:260] = 1
    def png(rel, a):
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(p)
    png("ct_mid.png", np.where(cover, 60 + rng.integers(0, 120, (h, w)), 0))
    for order in A.ORDERS:
        png(f"ensemble/{order}.png", 80 + 120 * signal + rng.normal(0, 5, (h, w)))
        png(f"ensemble-rev/{order}.png", 80 + 100 * signal + rng.normal(0, 5, (h, w)))
        for win in A.WINDOWS:
            png(f"maps/reader-v3/{win}_s1_{order}.png", 60 + 150 * signal + rng.normal(0, 10, (h, w)))
            png(f"maps/d9v2/{win}_s1_{order}.png", 128 + rng.normal(0, 1, (h, w)))
        png(f"maps/hecate-9.6/c+0_s1_{order}.png", 20 + 200 * signal)
    meta = {"schema": "inkatlas-surface/1", "id": sid, "scroll": "PHercTEST", "role": "eligible", "scan": "1",
            "voxel_um": 9.362, "canvas_um": 9.6, "ct": "https://example.invalid/ct.zarr/0",
            "mesh": {"base": "https://example.invalid/mesh"}, "credit": "test",
            "render": {"canvas_hw": [h, w], "layers": 65},
            "windows": {"centre_only": ["hecate-9.6"], "sweep": [-4, 0, 4]},
            "ensemble": {"ensemble": {"members": ["reader-v3", "hecate-9.6"], "recipe": "z mean"}},
            "ensemble_png_z_range": [-2, 4],
            "models": {"reader-v3": {"title": "Reader V3", "alive": True, "exposure": {"status": "unknown"}},
                       "d9v2": {"title": "d9v2", "alive": False},
                       "hecate-9.6": {"title": "Hecate", "alive": True}},
            "face_check": {"pairs": {"a/b": {"consistent_face": "reverse"}, "a/c": {"consistent_face": "reverse"},
                                     "b/c": {"consistent_face": "tie"}}},
            "files": ["ct_mid.png"]}
    (d / "meta.json").write_text(json.dumps(meta))
    (root / "atlas.json").write_text(json.dumps({"schema": "inkatlas-atlas/1", "per_scroll": {}, "surfaces": [
        {"id": sid, "scroll": "PHercTEST", "role": "eligible", "path": path}]}))
    return sid


@unittest.skipUnless(HAVE, "needs numpy and Pillow")
class TestAtlasData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.A = _load()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.A.OUT = Path(cls.tmp.name) / "out"
        cls.sid = _fake(Path(cls.tmp.name) / "atlas", cls.A)
        cls.at = cls.A.Atlas(root=Path(cls.tmp.name) / "atlas")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_lists_and_info(self):
        A, at = self.A, self.at
        self.assertEqual(A.list_scrolls(at), [{"scroll": "PHercTEST", "surfaces": 1, "role": "eligible"}])
        row = A.list_surfaces(at, "phercTEST")[0]
        self.assertEqual(row["alive_models"], ["reader-v3", "hecate-9.6"])
        self.assertEqual(row["opens_on"], "reverse")          # two reverse votes, no forward
        info = A.surface_info(at, self.sid)
        self.assertEqual(info["models"]["hecate-9.6"]["windows"], ["c+0"])
        self.assertTrue(info["files"]["ct_mid.png"].startswith(A.DATASET_URL))
        with self.assertRaises(A.AtlasError):
            A.surface_info(at, "nope")
        with self.assertRaises(A.AtlasError):
            A.list_surfaces(at, "PHerc9999")

    def test_layer_files(self):
        A, at = self.A, self.at
        self.assertTrue(A.layer_rel(at, self.sid, "ensemble", order="reverse")[0].endswith("ensemble-rev/reverse.png"))
        self.assertTrue(A.layer_rel(at, self.sid, "ensemble", order="forward")[0].endswith("ensemble/forward.png"))
        rel, used = A.layer_rel(at, self.sid, "hecate-9.6", "c+4", "forward")
        self.assertEqual(used, "c+0")                          # centre window only
        with self.assertRaises(A.AtlasError):
            A.layer_rel(at, self.sid, "reader-v3", "c+9")
        with self.assertRaises(A.AtlasError):
            A.layer_rel(at, self.sid, "not-a-model")

    def test_region_stays_inside(self):
        A, at = self.A, self.at
        self.assertIsNone(A.region(at, self.sid, -1, -1, 256))
        self.assertEqual(A.region(at, self.sid, 5, 5, 128), (0, 128, 0, 128))
        self.assertEqual(A.region(at, self.sid, 399, 299, 128), (172, 300, 272, 400))
        self.assertEqual(A.region(at, self.sid, 200, 150, 1024), (0, 300, 50, 350))   # capped by the canvas
        with self.assertRaises(A.AtlasError):
            A.region(at, self.sid, 500, 10, 64)

    def test_get_map_whole_and_crop(self):
        A, at = self.A, self.at
        png, rec = A.get_map(at, self.sid, "reader-v3", "c-4", "", max_side=200)
        self.assertEqual(rec["order"], "reverse")
        self.assertEqual(Image.open(png).size, (200, 150))
        png, rec = A.get_map(at, self.sid, "ensemble", x=200, y=120, size=64, colormap="papyrus")
        im = np.asarray(Image.open(png))
        self.assertEqual(im.shape, (64, 64, 3))
        self.assertEqual(rec["box_y0_y1_x0_x1"], [88, 152, 168, 232])
        _, rec = A.get_map(at, self.sid, "reader-v3", mode="overlay", colormap="ember")
        self.assertEqual(rec["mode"], "overlay")
        with self.assertRaises(A.AtlasError):
            A.get_map(at, self.sid, "ensemble", colormap="rainbow")

    def test_uncovered_pixels_are_marked(self):
        A, at = self.A, self.at
        img, _ = A.layer_picture(at, self.sid, "ensemble", box=(0, 10, 0, 10))
        self.assertTrue((np.asarray(img) == A.NO_SURFACE).all())

    def test_compare_numbers_can_fail(self):
        """The model built from the ensemble's signal correlates with it; the flat one does not."""
        A, at = self.A, self.at
        png, rec = A.compare_models(at, self.sid, 200, 120, 160)
        layers = rec["layers"]
        self.assertGreater(layers["reader-v3"]["r_with_ensemble"], 0.8)
        self.assertLess(abs(layers["d9v2"]["r_with_ensemble"] or 0), 0.2)
        self.assertFalse(layers["d9v2"]["alive"])
        self.assertIsNone(layers["ensemble"]["r_with_ensemble"])
        self.assertTrue(Path(png).is_file())

    def test_ramps(self):
        for name in self.A.RAMPS:
            lut = self.A.ramp(name)
            self.assertEqual(lut.shape, (256, 3))


class TestPage(unittest.TestCase):
    def test_api_tools_and_mcp(self):
        src = (SPACE / "app.py").read_text()
        tree = ast.parse(src)
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in ("atlas_summary", "list_scrolls", "list_surfaces", "surface_info", "get_map", "compare_models"):
            self.assertIn(name, funcs)
            doc = ast.get_docstring(funcs[name])
            self.assertTrue(doc, name)
            for line in doc.splitlines():                 # one line per argument: Gradio's MCP schema keeps one
                self.assertLessEqual(len(line), 120)
        self.assertIn("mcp_server=True", src)
        self.assertIn("connect.html", src)
        self.assertIn("api_name=fn.__name__", src)

    def test_card_and_files(self):
        card = (SPACE / "README.md").read_text()
        self.assertIn("sdk_version: 6.28.0", card)
        self.assertIn("mcp-server", card)
        for f in ("app.py", "atlasdata.py", "requirements.txt", "NOTICE", "LICENSE", "connect.json", "connect.html",
                  "CONNECT.md", "tools/deploy.py"):
            self.assertTrue((SPACE / f).is_file(), f)
        for f in SPACE.rglob("*"):
            if f.is_file() and f.suffix in (".py", ".md", ".json", ".html", ".txt"):
                self.assertNotIn("—", f.read_text(), f)
                self.assertNotIn("–", f.read_text(), f)


if __name__ == "__main__":
    unittest.main()
