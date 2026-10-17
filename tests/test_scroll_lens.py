"""Scroll Lens (spaces/scroll-lens): the core's checks, with numpy only. No network, no torch, no gradio."""

import contextlib
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
        try:
            key = tuple(int(p) for p in parts[-4:])
        except ValueError:          # a bucket listing (random_point's fallback): this fake bucket lists nothing
            return None
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
        # ZeroGPU reserves 1.5 times the duration from the visitor's quota before a call starts
        self.assertLessEqual(1.5 * lens.gpu_seconds(256, lens.LAYERS, tta=True), 120)
        self.assertLessEqual(1.5 * lens.gpu_seconds(256, lens.LAYERS), 25)
        self.assertGreaterEqual(lens.gpu_seconds(256, lens.LAYERS), 12)     # slowest 256 call seen: 8.0 s of models
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

    def test_read_cube_refuses_bad_chunks_and_outside(self):
        fetch = fake_bucket({(0, 0, 0, 0): b"x" * 10})
        with self.assertRaises(lens.LensError):
            lens.read_cube("PHerc0139", (0, 0, 0), 128, fetch=fetch)
        with self.assertRaises(lens.LensError):
            lens.read_cube("PHerc0139", (-1, 0, 0), 128, fetch=fetch)
        shape = lens.VOLUMES["PHerc0139"]["shape"]
        with self.assertRaises(lens.LensError):
            lens.read_cube("PHerc0139", (shape[0] - 100, 0, 0), 128, fetch=fetch)

    def test_read_cube_off_the_chunk_grid(self):
        # a CPU-fallback receipt's origin is the 256 cube's corner plus 64: the read crops the chunks it overlaps
        c = lens.CHUNK
        z = np.arange(2 * c, dtype=np.uint8)
        chunks = {}
        for cz in (8, 9):
            for cy in (8, 9):
                for cx in (8, 9):
                    a = np.broadcast_to(z[(cz - 8) * c:(cz - 7) * c, None, None], (c, c, c)) + (cy - 8) + 2 * (cx - 8)
                    chunks[(0, cz, cy, cx)] = np.ascontiguousarray(a, np.uint8).tobytes()
        cube = lens.read_cube("PHerc0139", (8 * c + 64,) * 3, 128, fetch=fake_bucket(chunks))
        self.assertEqual(int(cube[0, 0, 0]), 64)                 # z 64 of the first chunk, y and x offsets 0
        self.assertEqual(int(cube[127, 0, 0]), 191)
        self.assertEqual(int(cube[0, 127, 127]), 64 + 1 + 2)     # far corner lies in chunk (8, 9, 9)

    def test_scan_ids_and_layers_in_receipts(self):
        self.assertEqual(lens.volume_id("pherc0139"), "PHerc0139")
        with self.assertRaises(lens.LensError) as cm:
            lens.volume("PHerc1447")
        self.assertIn("choose from PHercParis4", str(cm.exception))
        self.assertTrue(lens.volume_url("pherc0139").startswith(f"{lens.BUCKET}/PHerc0139/"))
        res = {"grid": 1, "ink": 1, "surface": 1}
        self.assertEqual(lens.receipt("pherc0139", (0, 0, 0), 128, (1, 2, 3), res)["layers"], list(lens.LAYERS))
        self.assertEqual(lens.layers_in({"grid_reduced": 1, "ink": 1}), ["dino", "ink"])

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

    def test_auc_matches_a_slow_reference_with_ties(self):
        rng = np.random.default_rng(5)
        s = rng.integers(0, 6, 400).astype(np.float64)          # many ties
        y = rng.random(400) < 0.3
        pos, neg = s[y], s[~y]
        slow = ((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()) / (len(pos) * len(neg))
        self.assertAlmostEqual(lens.auc(s, y), float(slow), places=12)
        self.assertIsNone(lens.auc([0.1, float("nan"), 0.3], [0, 1, 1]))

    def test_agreement_control_range(self):
        ink = np.zeros((64, 64, 64), np.uint8)
        ink[8:24, 8:24, 8:24] = 255
        sim = (ink.reshape(8, 8, 8, 8, 8, 8).mean(axis=(1, 3, 5)) / 255.0).astype(np.float32)
        a = lens.agreement(sim, ink)
        self.assertLessEqual(a["auc_control_p05"], a["auc_control_mean"])
        self.assertLessEqual(a["auc_control_mean"], a["auc_control_p95"])
        self.assertLess(a["auc_control_p95"], a["auc"])
        self.assertEqual(a, lens.agreement(sim, ink))             # the shifts are fixed

    def test_load_concept_refuses_crafted_files(self):
        with tempfile.TemporaryDirectory() as d:
            npz = Path(d) / "z.npy"
            with open(npz, "wb") as fh:
                np.savez(fh, a=np.ones(lens.EMBED_DIM, np.float32))
            huge = Path(d) / "h.npy"
            with open(huge, "wb") as fh:
                np.lib.format.write_array_header_1_0(fh, {"descr": "<f4", "fortran_order": False,
                                                          "shape": (2 ** 40, lens.EMBED_DIM)})
                fh.write(b"\0" * 64)
            empty = Path(d) / "e.npy"
            np.save(empty, np.zeros((0, lens.EMBED_DIM), np.float32))
            v = np.ones(lens.EMBED_DIM, np.float32)
            cancel = Path(d) / "c.npy"
            np.save(cancel, np.stack([v, -v]))
            big = Path(d) / "b.npy"
            np.save(big, np.full(lens.EMBED_DIM, 3e38, np.float32))
            for path in (npz, huge, empty, cancel):
                with self.assertRaises(lens.LensError, msg=path.name):
                    lens.load_concept(path)
            self.assertAlmostEqual(float(np.linalg.norm(lens.load_concept(big))), 1.0, places=5)

    def test_whole_numbers(self):
        self.assertEqual(lens.as_int("256", "x"), 256)
        self.assertEqual(lens.as_int(128.0, "x"), 128)
        for bad in (None, float("nan"), float("inf"), "12.5", 256.7, True, "abc"):
            with self.assertRaises(lens.LensError, msg=repr(bad)):
                lens.as_int(bad, "x")
        with self.assertRaises(lens.LensError):
            lens.check_size(None)
        with self.assertRaises(lens.LensError):
            lens.cube_origin("PHerc0139", (float("nan"), 0, 0), 128)
        with self.assertRaises(lens.LensError):
            lens.cube_origin("PHerc0139", (1, 2), 128)

    def test_bucket_errors(self):
        import urllib.error
        from unittest import mock

        def refuse(code):
            def urlopen(req, timeout=None):
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
            return urlopen
        with mock.patch.object(lens.urllib.request, "urlopen", refuse(404)):
            self.assertIsNone(lens._get("https://x/a/volumes/s/0/1/2/3"))
        with mock.patch.object(lens.urllib.request, "urlopen", refuse(403)):
            with self.assertRaises(lens.LensError) as cm:
                lens._get("https://x/a/volumes/s/0/1/2/3")
            self.assertIn("HTTP 403", str(cm.exception))
        with mock.patch.object(lens.urllib.request, "urlopen", refuse(503)), mock.patch.object(lens.time, "sleep"):
            with self.assertRaises(lens.LensError) as cm:
                lens._get("https://x/a/volumes/s/0/1/2/3", tries=2)
            self.assertIn("try again", str(cm.exception))

    def test_random_point_falls_back_to_stored_chunks(self):
        # a scan whose blind draws all miss: only chunks listed in the bucket are stored
        c = lens.CHUNK
        chunk = np.zeros((c, c, c), np.uint8)
        chunk[20:110, 20:110, 20:110] = np.arange(90, dtype=np.uint8)[None, None, :] + 100
        vid = "PHerc0500P2"
        prefix = f"{vid}/volumes/{lens.VOLUMES[vid]['scan']}/3/"
        stored = {(y, x) for y in range(3, 8) for x in range(3, 8)}

        def fetch(url):
            if "list-type=2" in url:
                import urllib.parse
                pre = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["prefix"][0]
                cz = pre[len(prefix):].strip("/")
                keys = "".join(f"<Key>{prefix}{cz}/{y}/{x}</Key>" for y, x in sorted(stored))
                return f"<ListBucketResult>{keys}<IsTruncated>false</IsTruncated></ListBucketResult>".encode()
            parts = url.split("/")
            return chunk.tobytes() if (int(parts[-2]), int(parts[-1])) in stored and parts[-4] == "3" else None
        p = lens.random_point(vid, np.random.default_rng(3), fetch=fetch, tries=6)
        self.assertIn(((p[1] // 8) // c, (p[2] // 8) // c), stored)

    def test_pca_colours(self):
        col = lens.pca_colours(self.grid)
        self.assertEqual(col.shape, (8, 8, 8, 3))
        self.assertEqual(col.dtype, np.uint8)
        self.assertTrue(np.array_equal(col, lens.pca_colours(self.grid)))

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
                self.assertEqual(m["layers"], ["dino", "ink", "surface"])
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
            (Path(d) / "a.npz").write_bytes(b"")
            (Path(d) / "index.json").write_text(json.dumps({"cubes": [entry]}))
            self.assertEqual(len(lens.gallery(d)), 1)
            for bad in ({"file": "../x.npz"}, {"file": "a.tif"}, {"volume": "PHerc1447"}, {"file": "b.npz"},
                        {"size": 64}, {"point_zyx": [1, 2]}, {"point_zyx": [10 ** 9, 0, 0]}):
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
    def test_plan_uses_only_the_organisers_paris4_points(self):
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

    def test_later_batches_skip_paris4_and_scans_without_papyrus(self):
        build = load("build_gallery", SPACE / "tools" / "build_gallery.py")
        c = lens.CHUNK
        chunk = np.random.default_rng(0).integers(100, 200, (c, c, c), dtype=np.uint8).tobytes()
        empty = lens.volume_url("PHerc1667", 3)

        def fetch(url):
            return chunk if "/3/" in url and not url.startswith(empty) else None
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            items = build.plan(2026, fetch=fetch, batch=3)
        self.assertIn("PHerc1667: skipped", printed.getvalue())
        self.assertEqual(len(items), len(lens.VOLUMES) - 2)
        self.assertNotIn("PHercParis4", {i[1] for i in items})
        self.assertTrue(all(i[0].endswith("-random-2028") and i[3].endswith("random papyrus point 3") for i in items))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(items, build.plan(2026, fetch=fetch, batch=3))
        ids = ["pherc0139-random-2027", "paris4-train-2", "pherc0139-random-2026", "paris4-train-1",
               "pherc0332-random-2027"]
        order = build.gallery_order(ids, 2026)
        self.assertEqual(sorted(ids, key=order.get), ["paris4-train-1", "pherc0139-random-2026", "paris4-train-2",
                                                      "pherc0139-random-2027", "pherc0332-random-2027"])


@unittest.skipIf(np is None, "needs numpy")
class Page(unittest.TestCase):
    """app.py's cubes, viewer data, drawing and text, without gradio or the models."""

    def setUp(self):
        self.app = load("scroll_lens_app", SPACE / "app.py")
        self.app.REFERENCE = lens.unit(np.ones(lens.EMBED_DIM, np.float32))
        self.app.CUBES = self.app.CubeCache()
        self.tmp = tempfile.TemporaryDirectory()
        self.app.VIEW_DIR = Path(self.tmp.name) / "view"
        self.app.OUT = Path(self.tmp.name) / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def cube(self, size=128, compact=False, key="run:t"):
        res = Files().result(size)
        meta = lens.receipt("PHerc0139", (1024, 1024, 1024), size, (1030, 1040, 1050), res,
                            extra={"source": "gpu", "foreground": 0.9})
        if compact:
            res = dict(res)
            res["grid_reduced"], res["grid_basis"] = lens.reduce_grid(res.pop("grid"))
        return self.app.CUBES.put(self.app.Cube(key, meta, res))

    def state(self, cube, clicks=()):
        app = self.app
        view = app.new_view(cube, (1030, 1040, 1050), "gpu")
        pos = [{"volume": "PHerc0139", "cube": app.cube_key(view), "voxel": list(v),
                "voxel_zyx": [a + 1024 for a in v], "vec": cube.vector(v)} for v in clicks]
        return {"view": view, "pos": pos, "neg": [], "rev": 1}

    def test_reduced_search_matches_the_rebuilt_embeddings(self):
        cube = self.cube(compact=True)
        vec = cube.vector((10, 20, 30))
        self.assertAlmostEqual(float(np.linalg.norm(vec)), 1.0, places=5)
        full = lens.similarity(lens.grid_of(cube.result), vec)
        self.assertLess(float(np.abs(cube.similarity(vec) - full).max()), 1e-4)
        # the projection is not rescaled: its length is the share of each embedding the 128 directions keep
        lengths = np.linalg.norm(lens.grid_of(cube.result), axis=-1)
        self.assertLessEqual(float(lengths.max()), 1.0 + 1e-4)
        self.assertEqual(cube.pca().shape, (16, 16, 16, 3))

    def test_layers_file_is_what_the_viewer_reads(self):
        import gzip
        cube = self.cube()
        path = cube.layers_file(self.app.VIEW_DIR / "c.bin")
        self.assertEqual(path, cube.layers_file(self.app.VIEW_DIR / "other.bin"))   # written once
        raw = gzip.decompress(Path(path).read_bytes())
        hlen = int.from_bytes(raw[:4], "little")
        header = json.loads(raw[4:4 + hlen])
        start = (4 + hlen + 3) & ~3                                            # viewer.js: dataStart
        names = [a["name"] for a in header["arrays"]]
        self.assertEqual(names, ["ink", "surface", "pca", "ref"])
        for a in header["arrays"]:
            self.assertEqual((start + a["offset"]) % 4, 0, a["name"])
        ink = header["arrays"][0]
        got = np.frombuffer(raw, np.uint8, ink["nbytes"], start + ink["offset"]).reshape(ink["shape"])
        self.assertTrue(np.array_equal(got, cube.result["ink"]))
        ref = header["arrays"][3]
        got = np.frombuffer(raw, "<f4", ref["nbytes"] // 4, start + ref["offset"]).reshape(ref["shape"])
        self.assertTrue(np.allclose(got, cube.ref_sim))

    def test_viewer_value_and_click_map(self):
        app = self.app
        cube = self.cube()
        state = self.state(cube, clicks=[(10, 20, 30)])
        v = json.loads(app.viewer_value(state))
        self.assertEqual(v["key"], cube.key)
        self.assertEqual(v["size"], 128)
        self.assertEqual(v["origin"], [1024, 1024, 1024])
        self.assertTrue(v["data"].startswith("gradio_api/file="))
        self.assertTrue(v["ct"]["base"].endswith("/0"))
        self.assertEqual(v["clicks"]["pos"], [[10, 20, 30]])
        import base64
        sim = np.frombuffer(base64.b64decode(v["clicks"]["sim"]), "<i2").astype(np.float32) / app.SIM_SCALE
        want = app.click_sim(state).ravel()
        self.assertLess(float(np.abs(sim - want).max()), 1.0 / app.SIM_SCALE)
        self.assertEqual(app.viewer_value(app.empty_state()), "")

    def test_render_numbers_3d_and_save(self):
        app = self.app
        cube = self.cube()
        state = self.state(cube, clicks=[(10, 20, 30)])
        ct = np.random.default_rng(3).integers(1, 256, (128, 128, 128), dtype=np.uint8)
        for axis in range(3):
            img = app.render_slice(ct, cube, axis, 64, list(app.OVERLAYS), click=app.click_sim(state),
                                   marks={"pos": [[10, 20, 30]]})
            self.assertEqual(img.shape, (128, 128, 3))
        text = app.numbers(state)
        self.assertIn("not a reading", text)
        self.assertIn("1 positive", text)
        self.assertEqual(len(app.figure_3d(state, list(app.OVERLAYS), 8).data) > 0, True)
        names = sorted(Path(f).name for f in app.save_files(state))
        self.assertIn("concept.npy", names)
        self.assertIn("clicks.json", names)

    def test_concept_upload_has_no_voxel(self):
        app = self.app
        cube = self.cube()
        state = self.state(cube)
        state["pos"] = [{"volume": "file", "cube": "file", "voxel": None, "voxel_zyx": None,
                         "vec": lens.unit(np.ones(lens.EMBED_DIM, np.float32))}]
        v = json.loads(app.viewer_value(state))
        self.assertEqual(v["clicks"]["pos"], [])
        self.assertIsNotNone(v["clicks"]["sim"])
        self.assertIn("0 positive", app.numbers(state))
        self.assertIn("concept.npy", app.numbers(state))

    def test_cache_is_bounded_and_drops_run_files(self):
        app = self.app
        app.CUBES = app.CubeCache(size=2)
        a = self.cube(key="run:a")
        path = Path(a.layers_file(app.VIEW_DIR / "a.bin"))
        self.cube(key="run:b")
        self.cube(key="run:c")
        self.assertFalse(path.exists())
        with self.assertRaises(lens.LensError):
            app.CUBES.get("run:a")
        self.assertEqual(app.CUBES.get("run:c").key, "run:c")

    def test_cpu_fallback_cube_is_recentred(self):
        app = self.app
        res = Files().result(128)

        class Eng:
            def describe(self):
                return {}
        from unittest import mock
        app.engine = lambda wait_s=5.0: Eng()
        app.run_models = lambda ct, layers, tta, allow_cpu=True: (dict(res, device="cpu"), "ran on the CPU")
        with mock.patch.object(app.lens, "read_cube", lambda vid, origin, size: np.ones((size,) * 3, np.uint8)):
            cube, note = app.run_cube("PHerc0139", 1100, 1100, 1100, 256, ["dino", "ink", "surface"], False)
        self.assertEqual(note, "ran on the CPU")
        self.assertEqual(cube.meta["cube_origin_zyx"], [1088, 1088, 1088])
        self.assertEqual(cube.size, 128)
        self.assertEqual(cube.meta["requested_size"], 256)
        self.assertEqual(app.ran_size(res), 128)

    def test_point_must_be_whole_numbers(self):
        with self.assertRaises(lens.LensError):
            self.app.check_point("a", 1, 2)
        self.assertEqual(self.app.check_point(1.0, 2, 3), (1, 2, 3))

    def test_reference_layer_has_the_organisers_floor(self):
        app = self.app
        sim = np.full((16, 16, 16), 0.2, np.float32)
        sim[0, 0, 0] = 0.4                                         # nothing reaches tau = 0.5
        self.assertFalse(app._top_alpha(sim[0], sim, 8, floor=lens.TAU).any())
        sim[0, 0, 1] = 0.9
        a = app._top_alpha(sim[0], sim, 8, floor=lens.TAU)
        self.assertGreater(float(a[0, 1]), 0)
        self.assertEqual(float(a[0, 0]), 0.0)                      # in the top 8 % but below tau

    def test_public_api_and_mcp(self):
        import os
        os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
        try:
            import gradio  # noqa: F401
        except ImportError:
            self.skipTest("needs gradio")
        app = self.app
        app.GALLERY = []
        demo = app.build_demo()
        info = demo.get_api_info()
        self.assertEqual(sorted(info["named_endpoints"]), ["/gallery", "/gallery_cube", "/look", "/random_point",
                                                            "/reference", "/search", "/view", "/volumes"])
        self.assertEqual(info["unnamed_endpoints"], {})
        look = [p["parameter_name"] for p in info["named_endpoints"]["/look"]["parameters"]]
        self.assertEqual(look, ["vid", "z", "y", "x", "size", "layers", "tta", "compact", "allow_cpu"])
        kw = app.launch_kwargs()
        self.assertTrue(kw["mcp_server"])
        self.assertEqual(kw["max_file_size"], "5mb")

    def test_viewer_js_parses(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("needs node")
        js = ("const src = require('fs').readFileSync(process.argv[1], 'utf8');"
              "new Function('element', 'trigger', 'props', 'server', 'upload', 'watch', src);")
        subprocess.run([node, "-e", js, str(SPACE / "viewer.js")], check=True, capture_output=True, timeout=60)


if __name__ == "__main__":
    unittest.main()
