"""scripts/strokenet/gridpilot.py: the region rule, the chunk reader on a fake store, villa's
tiling helpers, the offset measurement on stand-in networks (one that ignores where its tiles fall
must show no tiling effect at any stride; one that is less sure near tile edges must show one that
shrinks as the stride falls), the readout's void branches and the full re-render count. No network
or GPU. The cloud runner's tests are in test_gridpilot_modal.py."""
from pathlib import Path
import sys
import unittest

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "strokenet"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridpilot as G  # noqa: E402

TILE = 32                                    # small tiles keep the stand-in renders fast


def blurred(rng, n):
    a = rng.random((n, n))
    for _ in range(3):
        a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5
    return a


def volume(n=256, c=4, seed=0):
    rng = np.random.default_rng(seed)
    v = (blurred(rng, n)[..., None] * 255 * np.linspace(0.6, 1.0, c)).astype(np.uint8)
    v[v == 0] = 1
    return v


def ideal(xb):
    """Probability from the voxels alone: where the tile sits does not matter."""
    return G.to_input(xb).mean(axis=1)


def edgy(xb):
    """Less sure near the tile edges, as a network with little context there."""
    t = xb.shape[1]
    r = np.minimum(np.arange(t), np.arange(t)[::-1]) / (t / 2)
    fall = 0.6 + 0.4 * np.minimum(r[:, None], r[None, :]) ** 0.5
    return G.to_input(xb).mean(axis=1) * fall


def effects(net, arr, strides=(16, 8, 4), tile=TILE):
    L = arr.shape[0]
    lo, hi = tile, L - tile
    out = {}
    for s in strides:
        a, _ = G.render(arr, net, G.axis_positions(L, s, 0, lo, hi, tile), G.axis_positions(L, s, 0, lo, hi, tile), tile)
        b, _ = G.render(arr, net, G.axis_positions(L, s, s // 2, lo, hi, tile),
                        G.axis_positions(L, s, s // 2, lo, hi, tile), tile)
        m = np.zeros(a.shape, bool)
        m[lo:hi, lo:hi] = True
        out[s] = G.rms(a, b, m)
    return out


class RegionTest(unittest.TestCase):
    def test_most_usable_then_most_text_inside_the_margin(self):
        lab = np.zeros((256, 256), np.uint8)
        lab[0:64, 0:64] = 2                   # the border step: never chosen
        lab[64:128, 96:160] = 1
        lab[128:192, 32:96] = 2
        self.assertEqual(G.choose_region(lab, size=64, lattice=32), (128, 32))
        lab[64:128, 96:160] = 2
        self.assertEqual(G.choose_region(lab, size=64, lattice=32), (64, 96))     # same counts: smaller y wins

    def test_too_small_raises(self):
        with self.assertRaises(ValueError):
            G.choose_region(np.ones((100, 100)), size=64, lattice=32)


class ReaderTest(unittest.TestCase):
    def store(self, depth=G.DEPTH, missing=()):
        rng = np.random.default_rng(1)
        full = rng.integers(0, 255, (depth, 3 * G.CHUNK, 3 * G.CHUNK), dtype=np.uint8)
        calls = []

        def fetch(url, rng_):
            cy, cx = map(int, url.rsplit("/", 2)[-2:])
            calls.append((url, rng_))
            if (cy, cx) in missing:
                return None
            chunk = np.ascontiguousarray(full[:, cy * G.CHUNK:(cy + 1) * G.CHUNK, cx * G.CHUNK:(cx + 1) * G.CHUNK])
            return chunk.tobytes()[rng_[0]:rng_[1] + 1]
        return full, fetch, calls

    def test_crop_matches_the_volume_and_missing_chunks_are_zero(self):
        full, fetch, calls = self.store(missing={(2, 2)})
        out = G.read_crop("BASE", 128, 128, 256, 256, fetch=fetch, workers=2)
        self.assertEqual(out.shape, (256, 256, G.Z1 - G.Z0))
        want = full[G.Z0:G.Z1, 128:384, 128:384].transpose(1, 2, 0).copy()
        want[128:, 128:] = 0
        np.testing.assert_array_equal(out, want)
        self.assertTrue(all(u.startswith("BASE/0/") for u, _ in calls))
        self.assertEqual({r for _, r in calls}, {(G.Z0 * 128 * 128, G.Z1 * 128 * 128 - 1)})

    def test_off_grid_raises(self):
        with self.assertRaises(ValueError):
            G.read_crop("B", 64, 0, 128, 128, fetch=lambda *a: None)

    def test_short_chunk_raises(self):
        with self.assertRaises(IOError):
            G.read_crop("B", 0, 0, 128, 128, fetch=lambda *a: b"\0" * 10, workers=1)


class TilingTest(unittest.TestCase):
    def test_villa_helpers(self):
        self.assertEqual(G.grid_1d(600, 256, 128), [0, 128, 256, 344])
        self.assertEqual(G.grid_1d(100, 256, 128), [0])
        w = G.hann2d(8, 8)
        self.assertAlmostEqual(float(w.sum()), 1.0, places=6)
        self.assertEqual(float(w[0].max()), 0.0)

    def test_positions_cover_the_region_from_both_offsets(self):
        L, lo, hi = 4608, 384, 4224
        for s in (128, 64, 32):
            for off in (0, s // 2):
                p = G.axis_positions(L, s, off, lo, hi)
                self.assertTrue(all((q - off) % s == 0 for q in p))
                for y in (lo, (lo + hi) // 2, hi - 1):      # every tile of the infinite grid over y is there
                    want = [q for q in range(off - 10 * s, L, s) if q <= y < q + G.TILE]
                    self.assertEqual([q for q in p if q <= y < q + G.TILE], want)
        with self.assertRaises(ValueError):
            G.axis_positions(L, 128, 0, 100, hi)

    def test_plan_order_and_counts(self):
        L = G.REGION * 20 + 2 * G.MARGIN
        pl = G.plan(L, G.MARGIN, L - G.MARGIN)
        self.assertEqual([n for n, *_ in pl], ["A128", "R128", "B128", "A64", "B64", "A32", "B32"])
        self.assertEqual(pl[0][3], 31 * 31)
        self.assertEqual(sum(n for *_, n in pl), 43524)
        self.assertTrue(all((G.REGION * 20) % 640 == 0 and G.MARGIN % G.CHUNK == 0 for _ in pl))

    def test_render_skips_empty_batches_and_masks_empty_columns(self):
        arr = volume(96)
        arr[:, :48] = 0
        seen = []

        def net(xb):
            seen.append(len(xb))
            return ideal(xb)
        out, st = G.render(arr, net, [0, 32, 64], [0, 32, 64], tile=TILE, batch=3)
        self.assertEqual(st["tiles"], 9)
        self.assertEqual(st["forwarded"], 9)                 # every row of three touches the nonzero half
        self.assertTrue((out[:, :48] == 0).all())
        out, st = G.render(arr, net, [0, 32, 64], [0], tile=TILE, batch=1)
        self.assertEqual(st["forwarded"], 0)

    def test_render_matches_a_direct_blend(self):
        arr = volume(64)
        out, _ = G.render(arr, ideal, [0, 16, 32], [0, 16, 32], tile=TILE)
        # the ideal net's probability is position free, so the blend returns it wherever weight > 0
        want = (np.clip(np.minimum(arr, G.CLIP).astype(np.float32).mean(-1) / G.CLIP, 0, 1) * 255).astype(np.uint8)
        inner = (slice(8, 56), slice(8, 56))
        self.assertLessEqual(int(np.abs(out[inner].astype(int) - want[inner]).max()), 1)


class EffectTest(unittest.TestCase):
    def test_a_position_free_net_shows_no_tiling_effect(self):
        e = effects(ideal, volume(192))
        self.assertTrue(all(v < 0.6 for v in e.values()), e)      # uint8 truncation only

    def test_an_edge_falloff_net_shows_one_that_shrinks_with_the_stride(self):
        e = effects(edgy, volume(192))
        self.assertGreater(e[16], 2.0, e)
        self.assertLess(e[8], 0.5 * e[16], e)
        self.assertLess(e[4], e[8], e)


class VerdictTest(unittest.TestCase):
    def maps(self, seed=2, grid=6.0, shares=(0.3, 0.02)):
        rng = np.random.default_rng(seed)
        n = 64
        base = blurred(rng, n) * 200
        g = np.zeros((n, n))
        g[:, ::6] = grid
        g[::6, :] = grid
        m = {"A128": base + g, "R128": base + g + rng.normal(0, 0.05, (n, n)), "B128": base + np.roll(g, 3, (0, 1))}
        for s, k in zip((64, 32), shares):
            m[f"A{s}"] = base + k * g
            m[f"B{s}"] = base + k * np.roll(g, 3, (0, 1))
        return base + g, m, np.ones((n, n), bool)

    def test_readout(self):
        pub, m, u = self.maps()
        v = G.verdict(pub, m, u)
        self.assertNotIn("void", v)
        self.assertEqual(v["strides"][64]["status"], "reduced")
        self.assertEqual(v["strides"][32]["status"], "gone")
        self.assertTrue(v["strides"][64]["content_kept"])
        self.assertIn("stride 64: reduced", v["line"])

    def test_not_reduced_and_missing_stride(self):
        pub, m, u = self.maps(shares=(0.8, 0.8))
        del m["B32"]
        v = G.verdict(pub, m, u)
        self.assertEqual(v["strides"][64]["status"], "not reduced")
        self.assertNotIn(32, v["strides"])
        self.assertIn("not run: stride 32", v["line"])

    def test_void_without_reproduction(self):
        pub, m, u = self.maps()
        v = G.verdict(np.random.default_rng(9).random(pub.shape), m, u)
        self.assertTrue(v["line"].startswith("VOID: the stride-128 render does not reproduce"))

    def test_void_without_a_tiling_effect(self):
        pub, m, u = self.maps(grid=0.0)
        v = G.verdict(pub, m, u)
        self.assertTrue(v["line"].startswith("VOID: no tiling effect at stride 128"), v["line"])

    def test_void_without_the_stride_128_renders(self):
        pub, m, u = self.maps()
        del m["R128"]
        self.assertTrue(G.verdict(pub, m, u)["line"].startswith("VOID: the stride-128 renders"))


class CostTest(unittest.TestCase):
    def test_full_render_tiles(self):
        m = np.zeros((40, 40), np.uint8)               # 800 x 800 native
        self.assertEqual(G.full_render_tiles([m], 128), 0)
        m[:] = 1
        self.assertEqual(G.full_render_tiles([m], 128), len(G.grid_1d(800, 256, 128)) ** 2)
        m[:] = 0
        m[0, 0] = 1                                    # native 0..19: only tiles starting at 0
        self.assertEqual(G.full_render_tiles([m], 128), 1)
        self.assertEqual(G.full_render_tiles([m, m], 64), 2)

    def test_projection(self):
        p = G.projection(1000.0, 8.3652)
        self.assertEqual(p[64]["tiles"], G.FULL_TILES[64])
        self.assertAlmostEqual(p[64]["gpu_hours"], round(G.FULL_TILES[64] / 1000 / 3600, 1))
        self.assertTrue(3.9 < G.FULL_TILES[64] / G.FULL_TILES[128] < 4.1)
        self.assertTrue(3.9 < G.FULL_TILES[32] / G.FULL_TILES[64] < 4.1)
