"""kit.simgan: the learned sim-to-real texture, its loss terms, steering, line keep and command line."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAVE = all(importlib.util.find_spec(m) is not None for m in ("numpy", "scipy", "skimage"))
HAVE_TORCH = HAVE and all(importlib.util.find_spec(m) is not None for m in ("torch", "safetensors"))
HAVE_SS = HAVE and all(importlib.util.find_spec(m) is not None for m in ("synthetic_slices", "cv2"))


@unittest.skipUnless(HAVE, "needs numpy, scipy, scikit-image")
class LineF1Test(unittest.TestCase):
    def test_f1_tolerance_mask_and_empty(self):
        import numpy as np
        from kit import simgan
        ref = np.zeros((32, 32), bool)
        ref[10, :] = True
        self.assertEqual(simgan.f1(ref, ref), 1.0)
        near = np.roll(ref, 2, axis=0)
        far = np.roll(ref, 3, axis=0)
        self.assertEqual(simgan.f1(near, ref), 1.0)       # within 2 px
        self.assertEqual(simgan.f1(far, ref), 0.0)        # beyond 2 px
        self.assertEqual(simgan.f1(np.zeros_like(ref), np.zeros_like(ref)), 1.0)
        self.assertEqual(simgan.f1(np.zeros_like(ref), ref), 0.0)
        m = np.zeros_like(ref)
        m[:, :16] = True
        half = ref.copy()
        half[:, 16:] = False
        self.assertEqual(simgan.f1(half, ref, m), 1.0)    # outside the mask does not count

    def test_extract_refuses_non_finite_maps(self):
        import numpy as np
        from kit import simgan
        bad = np.zeros((16, 16), np.float32)
        bad[3, 3] = np.nan
        with self.assertRaises(simgan.GanError):
            simgan.extract(bad, np.ones((16, 16), bool))

    def test_ridge_peaks_on_a_bright_line(self):
        import numpy as np
        from kit import simgan
        x = np.zeros((64, 64), np.float32)
        x[30:33, :] = 1
        r = simgan.ridge(x)
        self.assertGreater(r[31, 32], 10 * r[10, 32] + 1e-3)

    def test_presets_are_valid_hardcases_bounds(self):
        from kit import simgan, simreal
        for name, p in simgan.PRESETS.items():
            self.assertEqual(set(p), set(simreal.SPACE), name)
            for k, (lo, hi) in p.items():
                self.assertLessEqual(lo, hi, (name, k))
                s_lo, s_hi = simreal.SPACE[k]
                self.assertTrue(s_lo <= lo and hi <= s_hi, (name, k))


@unittest.skipUnless(HAVE_SS, "needs synthetic_slices")
class LineKeepTest(unittest.TestCase):
    def test_line_keep_high_on_clean_lines_and_lower_on_noise(self):
        import numpy as np
        from kit import simgan
        ln = np.zeros((2, 128, 128), np.uint8)
        ln[:, 20::16, :] = 1
        y = np.arange(128)[:, None]
        d = np.minimum((y - 20) % 16, 16 - (y - 20) % 16)
        clean = np.broadcast_to((np.exp(-d * d / 4.0) * 255), (2, 128, 128)).astype(np.uint8)
        rng = np.random.default_rng(0)
        noisy = rng.integers(0, 255, (2, 128, 128)).astype(np.uint8)
        self.assertGreater(simgan.line_keep(clean, ln), 0.9)
        self.assertLess(simgan.line_keep(noisy, ln), simgan.line_keep(clean, ln) - 0.3)


@unittest.skipUnless(HAVE_TORCH, "needs torch and safetensors")
class SimganTest(unittest.TestCase):
    def test_train_realize_keeps_shape_and_wider_discriminator(self):
        import numpy as np
        from kit import simgan
        rng = np.random.default_rng(0)
        sim = rng.integers(0, 255, (4, 32, 32)).astype(np.uint8)
        real = np.stack([simgan.unit(rng.normal(size=(32, 32))) for _ in range(4)])
        G = simgan.train(sim, real, steps=2, batch=2, progress=None, width=8, d_width=16)
        _, D = simgan.build(8, 16)
        self.assertEqual(D.net[0].out_channels, 16)
        out = simgan.realize(G, sim)
        self.assertEqual(out.shape, sim.shape)
        self.assertEqual(out.dtype, np.uint8)
        self.assertEqual(len(G.kit_log), 2)
        G2 = simgan.train(sim, real, steps=2, batch=2, progress=None, width=8, d_width=16, spec_w=1.0, grain_w=1.0)
        self.assertEqual(simgan.realize(G2, sim).shape, sim.shape)

    def test_oriented_residual_runs_with_the_sheets_and_round_trips(self):
        import numpy as np
        import torch
        from kit import simgan
        g = torch.Generator().manual_seed(0)
        stripes = torch.sin(torch.arange(64.0) / 1.5)[None, None, :, None].expand(2, 1, 64, 64).contiguous()
        noise = torch.randn(2, 1, 64, 64, generator=g)
        steered = simgan.steer_t(noise, stripes)
        self.assertGreater(float(simgan.grain_stats_t(steered)[1]), float(simgan.grain_stats_t(noise)[1]) + 0.2)
        rows = steered[0, 0]
        self.assertGreater(float(rows.diff(dim=1).std()), 0)
        self.assertLess(float(rows.diff(dim=1).std()), float(rows.diff(dim=0).std()))
        rng = np.random.default_rng(1)
        sim = rng.integers(0, 255, (2, 32, 32)).astype(np.uint8)
        real = np.stack([simgan.unit(rng.normal(size=(32, 32))) for _ in range(2)])
        G = simgan.train(sim, real, steps=2, batch=2, progress=None, oriented=True)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.safetensors")
            simgan.save(G, p)
            back = simgan.load(p)
        self.assertTrue(back.oriented)
        self.assertEqual(simgan.realize(back, sim).shape, sim.shape)

    def test_steer_modes_band_and_mix(self):
        import numpy as np
        import torch
        from kit import simgan
        self.assertEqual(simgan.steer_mode(False), "")
        self.assertEqual(simgan.steer_mode(True), "full")
        self.assertEqual(simgan.steer_mode("band:3.0"), "band:3")
        self.assertEqual(simgan.steer_mode("mix:0.5"), "mix:0.5")
        for bad in ("band:0", "mix:1.5", "mix:x", "twist:2"):
            with self.assertRaises(simgan.GanError):
                simgan.steer_mode(bad)
        g = torch.Generator().manual_seed(0)
        stripes = torch.sin(torch.arange(64.0) / 1.5)[None, None, :, None].expand(2, 1, 64, 64).contiguous()
        noise = torch.randn(2, 1, 64, 64, generator=g)
        self.assertTrue(torch.equal(simgan.steer_residual(noise, stripes, ""), noise))
        full = simgan.steer_residual(noise, stripes, "full")
        mix = simgan.steer_residual(noise, stripes, "mix:0.5")
        self.assertTrue(torch.allclose(mix, 0.5 * noise + 0.5 * full, atol=1e-6))
        band = simgan.steer_residual(noise, stripes, "band:3")
        # the fine texture above the band stays free: band minus its own blur equals noise minus its blur
        hi_b = band - simgan.blur_t(band, 3.0)
        hi_n = noise - simgan.blur_t(noise, 3.0)
        self.assertGreater(float(torch.corrcoef(torch.stack([hi_b.flatten(), hi_n.flatten()]))[0, 1]), 0.8)
        self.assertFalse(torch.allclose(band, noise))
        rng = np.random.default_rng(2)
        sim = rng.integers(0, 255, (2, 32, 32)).astype(np.uint8)
        real = np.stack([simgan.unit(rng.normal(size=(32, 32))) for _ in range(2)])
        G = simgan.train(sim, real, steps=2, batch=2, progress=None, width=8, d_width=16, oriented="band:3")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.safetensors")
            simgan.save(G, p)
            from safetensors import safe_open
            with safe_open(p, "pt") as f:
                self.assertEqual(f.metadata()["steer"], "band:3")

    def test_spectrum_and_grain_stats_see_the_difference(self):
        import numpy as np
        import torch
        from kit import simgan
        g = torch.Generator().manual_seed(0)
        white = torch.randn(4, 1, 64, 64, generator=g)
        smooth = simgan.blur_t(white, 2.0)
        self.assertGreater(float(simgan.radial_profile_t(white)[-1]), float(simgan.radial_profile_t(smooth)[-1]) + 1)
        stripes = torch.sin(torch.arange(64.0) / 2)[None, None, :, None].expand(4, 1, 64, 64) + 0.05 * white
        self.assertGreater(float(simgan.grain_stats_t(stripes)[1]), float(simgan.grain_stats_t(white)[1]) + 0.3)


@unittest.skipUnless(HAVE_TORCH, "needs torch and safetensors")
class SimganLoopTermsTest(unittest.TestCase):
    """An edit inside the training loop, a score prior and the high-band spectrum term."""

    def test_straight_through_forward_is_edit_backward_is_identity(self):
        import torch
        from kit import simgan
        x = torch.randn(2, 1, 8, 8, requires_grad=True)
        e = torch.zeros(2, 1, 8, 8)
        y = simgan.straight_through(x, e)
        self.assertTrue(torch.equal(y.detach(), e))
        (y * 3).sum().backward()
        self.assertTrue(torch.allclose(x.grad, torch.full_like(x, 3.0)))

    def test_hi_band_is_the_top_share_of_the_profile(self):
        import torch
        from kit import simgan
        p = torch.arange(32.0)
        self.assertEqual(simgan.hi_band_t(p).tolist(), list(range(12, 32)))
        self.assertEqual(len(simgan.hi_band_t(p, 0.5)), 16)

    def test_edit_reaches_discriminator_and_realize_and_score_is_weighted(self):
        import numpy as np
        import torch
        from kit import simgan
        rng = np.random.default_rng(2)
        sim = rng.integers(0, 255, (4, 32, 32)).astype(np.uint8)
        real = np.stack([simgan.unit(rng.normal(size=(32, 32))) for _ in range(4)])
        seen = []

        def edit(x):
            seen.append(x.requires_grad)
            return torch.flip(x, (3,))
        G = simgan.train(sim, real, steps=2, batch=2, progress=None, width=8, d_width=16, edit=edit, hi_w=1.0)
        self.assertEqual(seen, [False, False])          # the edit never sees a gradient
        out = simgan.realize(G, sim, edit=edit)
        plain = simgan.realize(G, sim)
        self.assertEqual(out.shape, sim.shape)
        self.assertFalse(np.array_equal(out, plain))

        def score(x):
            return (x * x).mean()
        G2 = simgan.train(sim, real, steps=2, batch=2, progress=None, width=8, d_width=16, score=score,
                          score_ratio=0.5)
        self.assertIn("score_w", G2.kit_log[0])
        self.assertGreater(G2.kit_log[0]["score_w"], 0)
        G3 = simgan.train(sim, real, steps=2, batch=2, progress=None, width=8, d_width=16, score=score,
                          score_ratio=0.0)
        self.assertEqual(G3.kit_log[0]["score_w"], 0.0)


@unittest.skipUnless(HAVE_TORCH, "needs torch and safetensors")
class SimganInitTest(unittest.TestCase):
    def test_init_starts_from_saved_weights(self):
        import numpy as np
        import torch
        from kit import simgan
        rng = np.random.default_rng(4)
        sim = rng.integers(0, 255, (4, 32, 32)).astype(np.uint8)
        real = np.stack([simgan.unit(rng.normal(size=(32, 32))) for _ in range(4)])
        G = simgan.train(sim, real, steps=3, batch=2, progress=None)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.safetensors")
            simgan.save(G, p)
            G2 = simgan.train(sim, real, steps=1, batch=2, progress=None, init=p, lr=0.0)
        for k, v in G.state_dict().items():
            self.assertTrue(torch.allclose(v, G2.state_dict()[k]), k)


@unittest.skipUnless(HAVE_TORCH, "needs torch and safetensors")
class SimganCliTest(unittest.TestCase):
    def test_real_tiles_train_realize_on_tiny_inputs(self):
        import numpy as np
        from kit import simgan
        rng = np.random.default_rng(5)
        with tempfile.TemporaryDirectory() as d:
            ref = os.path.join(d, "ref.npz")
            np.savez(ref, ct=rng.normal(size=(4, 96, 96)).astype(np.float32))
            real = os.path.join(d, "real.npz")
            self.assertEqual(simgan.main(["real", ref, real, "--n", "6", "--win", "32"]), 0)
            r = np.load(real)
            self.assertEqual(r["real"].shape, (6, 32, 32))
            self.assertEqual(r["slices"].tolist(), [0, 2])           # even slices only
            tiles = os.path.join(d, "tiles.npz")
            np.savez(tiles, image=rng.integers(0, 255, (6, 32, 32)).astype(np.uint8),
                     lines=np.zeros((6, 32, 32), np.uint8), sheet_id=np.zeros((6, 32, 32), np.uint16))
            g = os.path.join(d, "g.safetensors")
            self.assertEqual(simgan.main(["train", tiles, real, g, "--steps", "2", "--hold", "2", "--d-width", "16",
                                          "--steer", "band:4"]), 0)
            meta = json.load(open(g + ".json"))
            self.assertEqual((meta["steer"], meta["steps"], meta["hold"]), ("band:4", 2, 2))
            out = os.path.join(d, "out.npz")
            self.assertEqual(simgan.main(["realize", g, tiles, out, "--n", "3"]), 0)
            o = np.load(out)
            self.assertEqual(o["image"].shape, (3, 32, 32))
            self.assertEqual(o["image"].dtype, np.uint8)
            self.assertTrue(np.array_equal(o["phys"], np.load(tiles)["image"][:3]))
            with self.assertRaises(SystemExit):
                simgan.main(["train", tiles, real, g, "--steps", "1", "--hold", "6"])

    def test_physics_tiles_drop_tiles_with_air(self):
        import numpy as np
        from unittest import mock
        from kit import simgan, hardcases
        air = np.zeros((3, 8, 8), bool)
        air[1] = True
        fake = {"image": np.arange(3)[:, None, None] * np.ones((3, 8, 8), np.uint8), "lines": np.zeros((3, 8, 8)),
                "sheet_id": np.zeros((3, 8, 8)), "air": air}
        with mock.patch.object(hardcases, "tiles", return_value=fake) as t:
            out = simgan.physics_tiles(3, 41, "r4")
        self.assertEqual(out["image"][:, 0, 0].tolist(), [0, 2])
        self.assertEqual(t.call_args.kwargs["dense_look"], simgan.PRESETS["r4"])


if __name__ == "__main__":
    unittest.main()
