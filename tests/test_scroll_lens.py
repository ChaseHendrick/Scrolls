"""Scroll Lens (spaces/scroll-lens): the core's checks, with numpy only. No network, no torch, no gradio."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "scroll-lens"

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lens = load("lens", SPACE / "lens.py")


def fake_bucket(chunks):
    """A fetch() serving `chunks` {(level, cz, cy, cx): bytes} for any volume, None for the rest."""
    def fetch(url):
        parts = url.rstrip("/").split("/")
        key = tuple(int(p) for p in parts[-4:])
        return chunks.get(key)
    return fetch


class Volumes(unittest.TestCase):
    def test_no_prize_eligible_scan(self):
        prizes = json.loads((ROOT / "kit" / "data" / "prizes-2026-10-11.json").read_text())["prizes"]
        eligible = {e["scroll"] for p in prizes if p["id"] in ("grand-prize-2027", "first-letters-2027")
                    for e in p["eligible"]}
        self.assertEqual(len(lens.VOLUMES), 12)
        self.assertFalse(eligible & set(lens.VOLUMES))

    def test_only_listed_volumes(self):
        with self.assertRaises(lens.LensError):
            lens.volume("PHerc1447")
        with self.assertRaises(lens.LensError):
            lens.cube_origin("PHerc0813", (100, 100, 100), 128)

    def test_scans_are_level0_2um(self):
        for vid, v in lens.VOLUMES.items():
            self.assertTrue(2.2 <= v["voxel_um"] <= 2.41, vid)
            self.assertIn(f"{v['voxel_um']:.3f}"[:4], v["scan"], vid)
            self.assertEqual(set(v["role"]), set(lens.LAYERS), vid)

    def test_paris4_points_are_inside(self):
        shape = lens.VOLUMES["PHercParis4"]["shape"]
        self.assertEqual(len(lens.PARIS4_TRAINING_POINTS), 8)
        for p in lens.PARIS4_TRAINING_POINTS:
            self.assertTrue(all(0 <= c < n for c, n in zip(p, shape)), p)


class Cubes(unittest.TestCase):
    def test_origin_snaps_to_chunks_and_holds_the_point(self):
        for size in lens.SIZES:
            p = (37628, 8793, 22167)
            o = lens.cube_origin("PHercParis4", p, size)
            for c, oo in zip(p, o):
                self.assertEqual(oo % lens.CHUNK, 0)
                self.assertTrue(oo <= c < oo + size)
            self.assertEqual(len(lens.chunk_keys(o, size)), (size // lens.CHUNK) ** 3)

    def test_origin_stays_inside_the_scan(self):
        shape = lens.VOLUMES["PHerc1667"]["shape"]
        o = lens.cube_origin("PHerc1667", tuple(n - 1 for n in shape), 256)
        self.assertTrue(all(oo + 256 <= n for oo, n in zip(o, shape)))
        with self.assertRaises(lens.LensError):
            lens.cube_origin("PHerc1667", (shape[0], 0, 0), 128)

    def test_sizes_and_layers(self):
        with self.assertRaises(lens.LensError):
            lens.check_size(64)
        with self.assertRaises(lens.LensError):
            lens.check_layers(["dino", "letters"])
        with self.assertRaises(lens.LensError):
            lens.check_layers([])
        self.assertEqual(lens.check_layers(["ink", "ink", "dino"]), ("ink", "dino"))

    def test_gpu_request_fits_a_space_call(self):
        self.assertLess(lens.gpu_seconds(256, lens.LAYERS, tta=True), 120)
        self.assertLess(lens.gpu_seconds(128, ["dino"]), lens.gpu_seconds(256, ["dino"]))


@unittest.skipIf(np is None, "needs numpy")
class Reading(unittest.TestCase):
    def test_read_cube_places_chunks(self):
        c = lens.CHUNK
        a = np.full(c ** 3, 7, np.uint8).tobytes()
        b = np.full(c ** 3, 9, np.uint8).tobytes()
        fetch = fake_bucket({(0, 1, 2, 3): a, (0, 2, 2, 3): b})
        cube = lens.read_cube("PHerc0139", (c, 2 * c, 3 * c), 256, fetch=fetch)
        self.assertEqual(cube.shape, (256, 256, 256))
        self.assertTrue((cube[:c, :c, :c] == 7).all())
        self.assertTrue((cube[c:, :c, :c] == 9).all())
        self.assertTrue((cube[:, c:, :] == 0).all())        # missing chunks read as 0
        self.assertAlmostEqual(lens.foreground(cube), 0.25)

    def test_read_cube_refuses_bad_chunks_and_grid(self):
        fetch = fake_bucket({(0, 0, 0, 0): b"x" * 10})
        with self.assertRaises(lens.LensError):
            lens.read_cube("PHerc0139", (0, 0, 0), 128, fetch=fetch)
        with self.assertRaises(lens.LensError):
            lens.read_cube("PHerc0139", (5, 0, 0), 128, fetch=fetch)

    def test_empty_cube_is_refused(self):
        with self.assertRaises(lens.LensError):
            lens.check_cube(np.zeros((128, 128, 128), np.uint8))

    def test_random_point_lands_on_papyrus(self):
        c = lens.CHUNK
        chunk = np.zeros((c, c, c), np.uint8)
        chunk[20:110, 20:110, 20:110] = np.arange(90, dtype=np.uint8)[None, None, :] + 100
        shape = lens.VOLUMES["PHerc1667"]["shape"]
        n = [-(-(-(-s // 8)) // c) for s in shape]          # level-3 chunk counts
        data = chunk.tobytes()
        chunks = {(3, z, y, x): data for z in range(n[0]) for y in range(n[1]) for x in range(n[2])}
        p = lens.random_point("PHerc1667", np.random.default_rng(1), fetch=fake_bucket(chunks))
        local = [(v // 8) % c for v in p]
        self.assertTrue(all(30 <= v < 100 for v in local), p)  # well inside the block, not at its edge
        with self.assertRaises(lens.LensError):
            lens.random_point("PHerc1667", np.random.default_rng(1), fetch=fake_bucket({}), tries=3)


@unittest.skipIf(np is None, "needs numpy")
class Embeddings(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.grid = lens.unit(rng.normal(size=(8, 8, 8, lens.EMBED_DIM))).astype(np.float32)

    def test_concept_and_similarity(self):
        t = (1, 2, 3)
        c = lens.concept(self.grid, [t])
        s = lens.similarity(self.grid, c)
        self.assertAlmostEqual(float(s[t]), 1.0, places=5)
        self.assertEqual(tuple(np.unravel_index(np.argmax(s), s.shape)), t)
        s2 = lens.similarity(self.grid, c, c)
        self.assertTrue(np.allclose(s2, 0, atol=1e-6))
        self.assertIsNone(lens.concept(self.grid, []))

    def test_token_of(self):
        self.assertEqual(lens.token_of((0, 7, 8), 64), (0, 0, 1))
        self.assertEqual(lens.token_of((63, 500, -3), 64), (7, 7, 0))

    def test_auc(self):
        self.assertEqual(lens.auc([0.1, 0.2, 0.9, 0.8], [0, 0, 1, 1]), 1.0)
        self.assertEqual(lens.auc([0.9, 0.8, 0.1, 0.2], [0, 0, 1, 1]), 0.0)
        self.assertEqual(lens.auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]), 0.5)
        self.assertIsNone(lens.auc([1, 2], [1, 1]))

    def test_agreement_has_a_control_that_fails(self):
        ink = np.zeros((64, 64, 64), np.uint8)
        ink[8:24, 8:24, 8:24] = 255                          # ink in one corner block of patches
        sim = (ink.reshape(8, 8, 8, 8, 8, 8).mean(axis=(1, 3, 5)) / 255.0).astype(np.float32)
        a = lens.agreement(sim, ink)
        self.assertEqual(a["auc"], 1.0)
        self.assertLess(a["auc_control_shifted"], 0.6)
        self.assertAlmostEqual(a["ink_patch_fraction"], 8 / 512)

    def test_pca_colors(self):
        col = lens.pca_colors(self.grid)
        self.assertEqual(col.shape, (8, 8, 8, 3))
        self.assertEqual(col.dtype, np.uint8)
        self.assertTrue(np.array_equal(col, lens.pca_colors(self.grid)))

    def test_reduce_grid_round_trip(self):
        rng = np.random.default_rng(1)
        low = lens.unit(rng.normal(size=(8, 8, 8, 16)) @ rng.normal(size=(16, lens.EMBED_DIM)))
        coef, basis = lens.reduce_grid(low, k=32)
        back = lens.grid_of({"grid_reduced": coef, "grid_basis": basis})
        self.assertGreater(float((back * low).sum(-1).min()), 0.99)

    def test_quantize(self):
        a = np.arange(256, dtype=np.uint8)
        q = lens.quantize(a)
        self.assertLessEqual(int(np.abs(q.astype(int) - a).max()), 8)
        self.assertEqual(len(np.unique(q)), 16)

    def test_load_concept(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "c.npy"
            np.save(good, np.ones((3, lens.EMBED_DIM), np.float32))
            self.assertAlmostEqual(float(np.linalg.norm(lens.load_concept(good))), 1.0, places=5)
            for bad in (np.ones(10, np.float32), np.ones(lens.EMBED_DIM, np.int32),
                        np.full(lens.EMBED_DIM, np.nan, np.float32), np.zeros(lens.EMBED_DIM, np.float32)):
                p = Path(d) / "bad.npy"
                np.save(p, bad)
                with self.assertRaises(lens.LensError):
                    lens.load_concept(p)
            pickled = Path(d) / "p.npy"
            np.save(pickled, np.array([{"a": 1}], dtype=object), allow_pickle=True)
            with self.assertRaises(lens.LensError):
                lens.load_concept(pickled)


@unittest.skipIf(np is None, "needs numpy")
class Files(unittest.TestCase):
    def result(self, size=128):
        rng = np.random.default_rng(2)
        n = size // lens.PATCH
        return {"grid": lens.unit(rng.normal(size=(n, n, n, lens.EMBED_DIM))).astype(np.float16),
                "ink": rng.integers(0, 256, (size,) * 3, dtype=np.uint8),
                "surface": rng.integers(0, 256, (size,) * 3, dtype=np.uint8), "seconds": {"dino": 1.0}}

    def test_save_and_load(self):
        res = self.result()
        meta = lens.receipt("PHerc0139", (0, 0, 0), 128, (5, 6, 7), res)
        self.assertIn("not a reading", meta["note"])
        with tempfile.TemporaryDirectory() as d:
            for compact in (False, True):
                p = lens.save_npz(Path(d) / f"c{compact}.npz", meta, res, compact=compact)
                m, arrays = lens.load_npz(p)
                self.assertEqual(m["compact"], compact)
                self.assertEqual(m["point_zyx"], [5, 6, 7])
                self.assertEqual(lens.grid_of(arrays).shape, (16, 16, 16, lens.EMBED_DIM))
                self.assertEqual("grid_reduced" in arrays, compact)
                self.assertEqual(arrays["ink"].shape, (128, 128, 128))

    def test_load_refuses_mismatched_shapes(self):
        res = self.result()
        res["ink"] = res["ink"][:64]
        meta = lens.receipt("PHerc0139", (0, 0, 0), 128, (0, 0, 0), res)
        with tempfile.TemporaryDirectory() as d:
            p = lens.save_npz(Path(d) / "c.npz", meta, res)
            with self.assertRaises(lens.LensError):
                lens.load_npz(p)

    def test_gallery_index(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(lens.gallery(d), [])
            entry = {"id": "a", "volume": "PHerc0139", "title": "t", "note": "n", "file": "a.npz",
                     "point_zyx": [1, 2, 3], "size": 128}
            (Path(d) / "index.json").write_text(json.dumps({"cubes": [entry]}))
            self.assertEqual(len(lens.gallery(d)), 1)
            for bad in ({"file": "../x.npz"}, {"file": "a.tif"}, {"volume": "PHerc1447"}):
                (Path(d) / "index.json").write_text(json.dumps({"cubes": [dict(entry, **bad)]}))
                with self.assertRaises(lens.LensError):
                    lens.gallery(d)

    def test_stage_holds_only_the_space_files(self):
        with tempfile.TemporaryDirectory() as d:
            out = lens.stage(Path(d) / "s")
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(lens.SPACE_FILES))
            with self.assertRaises(RuntimeError):
                lens.stage(out)

    def test_space_card(self):
        card = (SPACE / "README.md").read_text()
        head = card.split("---")[1]
        for line in ("sdk: gradio", "app_file: app.py", "license: apache-2.0", "suggested_hardware: zero-a10g"):
            self.assertIn(line, head)
        for name in ("dino", "ink", "surface"):
            self.assertIn(lens.MODELS[name]["repo"], head)
        short = [ln for ln in head.splitlines() if ln.startswith("short_description:")][0]
        self.assertLessEqual(len(short.split(":", 1)[1].strip()), 60)

    def test_no_long_dashes(self):
        for p in sorted(SPACE.rglob("*")):
            if p.is_file() and p.suffix in (".py", ".md", ".txt", "") and p.name != "LICENSE":
                text = p.read_text(encoding="utf-8")
                self.assertNotIn(chr(0x2014), text, p)
                self.assertNotIn(chr(0x2013), text, p)


@unittest.skipIf(np is None, "needs numpy")
class GalleryPlan(unittest.TestCase):
    def test_plan_uses_only_the_organizers_paris4_points(self):
        build = load("build_gallery", SPACE / "tools" / "build_gallery.py")
        c = lens.CHUNK
        chunk = np.random.default_rng(0).integers(100, 200, (c, c, c), dtype=np.uint8).tobytes()

        def fetch(url):
            return chunk if "/3/" in url else None
        items = build.plan(7, fetch=fetch)
        self.assertEqual(len(items), 8 + len(lens.VOLUMES) - 1)
        self.assertEqual(len({i[0] for i in items}), len(items))
        paris = [tuple(i[2]) for i in items if i[1] == "PHercParis4"]
        self.assertEqual(sorted(paris), sorted(lens.PARIS4_TRAINING_POINTS))
        self.assertNotEqual(items[1][1], "PHercParis4")      # an early stop still covers other scrolls
        self.assertEqual(items, build.plan(7, fetch=fetch))  # fixed by the seed


@unittest.skipIf(np is None, "needs numpy")
class Page(unittest.TestCase):
    """app.py's drawing and text, without gradio or the models."""

    def test_draw_and_numbers(self):
        app = load("scroll_lens_app", SPACE / "app.py")
        app.REFERENCE = lens.unit(np.ones(lens.EMBED_DIM, np.float32))
        rng = np.random.default_rng(3)
        res = Files().result(128)
        cube = rng.integers(1, 256, (128, 128, 128), dtype=np.uint8)
        view = app.new_view("PHerc0139", (0, 0, 0), 128, (10, 20, 30), cube, res, "gallery")
        self.assertEqual(view["slices"], [10, 20, 30])
        state = {"view": view, "pos": [], "neg": []}
        state["pos"].append({"volume": "PHerc0139", "cube": app.cube_key(view), "voxel": [10, 20, 30],
                             "voxel_zyx": [10, 20, 30], "vec": view["grid"][1, 2, 3].astype(np.float32)})
        for axis in range(3):
            img = app.draw_slice(state, axis, list(app.OVERLAYS), 8, 0.7)
            self.assertEqual(img.shape, (512, 512, 3))
        text = app.numbers(state, 8)
        self.assertIn("not a reading", text)
        self.assertIn("control", text)
        self.assertEqual(app.ran_size(res), 128)
        self.assertEqual(app._center(np.zeros((256,) * 3), 128).shape, (128,) * 3)

    def test_cpu_fallback_view_is_recentered(self):
        app = load("scroll_lens_app", SPACE / "app.py")
        app.REFERENCE = lens.unit(np.ones(lens.EMBED_DIM, np.float32))
        res = Files().result(128)
        view = app.new_view("PHerc0139", (1024, 1024, 1024), 256, (1100, 1100, 1100),
                            np.ones((128,) * 3, np.uint8), res, "cpu")
        self.assertEqual(view["origin"], (1088, 1088, 1088))
        self.assertEqual(view["size"], 128)


    def test_agent_tools_on_a_gallery_cube(self):
        app = load("scroll_lens_app", SPACE / "app.py")
        app.REFERENCE = lens.unit(np.ones(lens.EMBED_DIM, np.float32))
        rng = np.random.default_rng(5)
        res = Files().result(128)
        cube = rng.integers(1, 256, (128, 128, 128), dtype=np.uint8)
        origin = (1024, 2048, 3072)
        view = app.new_view("PHerc0139", origin, 128, (1030, 2050, 3080), cube, res, "gallery")
        view["receipt"]["gallery_id"] = "g1"
        app.VIEW_CACHE.clear()
        app.VIEW_CACHE[("gallery", "g1")] = view
        app.GALLERY = [{"id": "g1", "volume": "PHerc0139", "title": "t", "note": "", "file": "g1.npz",
                        "point_zyx": [1030, 2050, 3080], "size": 128}]
        img, info = app.inspect_cube("g1", overlays="ink,surface,reference,dino")
        self.assertEqual(img.shape, (512, 512 * 3 + 16, 3))
        self.assertEqual(info["slices_zyx"], [1030, 2050, 3080])
        self.assertIn("cube=g1", info["open_in_browser"])
        with self.assertRaises(lens.LensError):
            app.inspect_cube("g1", overlays="ink,letters")
        img, hits, concept = app.search_cube("g1", positive="1030,2050,3080", top_k=5)
        self.assertEqual(len(hits["matches"]), 5)
        self.assertEqual(hits["matches"][0]["score"], 1.0)              # the example matches itself best
        self.assertEqual(hits["matches"][0]["center_zyx"], [1028, 2052, 3084])
        self.assertIn("auc_control_shifted", hits["agreement_with_ink_model"])
        self.assertEqual(np.load(concept).shape, (lens.EMBED_DIM,))
        _, again, _ = app.search_cube("g1", concept=concept, top_k=5)  # the saved concept finds the same patches
        self.assertEqual(again["matches"], hits["matches"])
        _, ref, _ = app.search_cube("g1", top_k=3)
        self.assertEqual(ref["concept"], "the organizers' ink reference")
        for bad in ({"positive": "0,0,0"}, {"positive": "1,2"}, {"negative": "1030,2050,3080"}):
            with self.assertRaises(lens.LensError):
                app.search_cube("g1", **bad)
        with self.assertRaises(lens.LensError):
            app.inspect_cube("", "")                                     # neither a cube nor a scan
        self.assertEqual(app.next_gallery_id("g1", 1), "g1")
        self.assertEqual(app.list_gallery()["cubes"][0]["id"], "g1")
        self.assertEqual(len(app.list_scans()["scans"]), len(lens.VOLUMES))

    def test_parse_points_and_matches(self):
        self.assertEqual(lens.parse_points("1,2,3; 4 5 6\n7,8,9"), [(1, 2, 3), (4, 5, 6), (7, 8, 9)])
        self.assertEqual(lens.parse_points(""), [])
        for bad in ("1,2", "1,2,3,4", "a,b,c", "-1,2,3"):
            with self.assertRaises(lens.LensError):
                lens.parse_points(bad)
        self.assertEqual(lens.voxel_in_cube((110, 120, 130), (100, 100, 100), 128), [10, 20, 30])
        with self.assertRaises(lens.LensError):
            lens.voxel_in_cube((99, 120, 130), (100, 100, 100), 128)
        sim = np.zeros((4, 4, 4), np.float32)
        sim[1, 2, 3], sim[0, 0, 0] = 0.9, 0.5
        m = lens.top_matches(sim, (100, 200, 300), 2)
        self.assertEqual(m[0], {"center_zyx": [112, 220, 328], "score": 0.9})
        self.assertEqual(m[1]["center_zyx"], [104, 204, 304])


if __name__ == "__main__":
    unittest.main()
