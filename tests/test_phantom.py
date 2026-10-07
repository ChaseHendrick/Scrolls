import tempfile
import unittest
from pathlib import Path

try:
    import numpy  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, "needs numpy")
class PhantomTest(unittest.TestCase):
    def test_truth_detector_and_control(self):
        from kit import auc, phantom
        p = phantom.make_phantom((192, 192), depth=12, seed=3, letter_px=48)
        self.assertEqual(p["volume"].shape, (12, 192, 192))
        self.assertTrue(0.02 < p["meta"]["ink_fraction"] < 0.5)
        fwd = auc.score_array(phantom.surface_detector(p["volume"]), p["ink"], p["mask"])["auc"]
        rev = auc.score_array(phantom.surface_detector(p["volume"][::-1]), p["ink"], p["mask"])["auc"]
        self.assertGreater(fwd, 0.55)
        self.assertLess(rev, fwd - 0.05)
        good = auc.score_array(phantom.simulated_reader(p["ink"], quality=50, blur_px=0.5), p["ink"], p["mask"])["auc"]
        self.assertGreater(good, 0.95)

    def test_blur_keeps_mean_and_shape(self):
        import numpy as np
        from kit import phantom
        a = np.random.default_rng(0).standard_normal((40, 50))
        b = phantom.gaussian_blur(a, 3)
        self.assertEqual(b.shape, a.shape)
        self.assertLess(b.std(), a.std())
        self.assertAlmostEqual(phantom.gaussian_blur(np.ones((20, 20)), 4)[10, 10], 1.0, places=6)


@unittest.skipUnless(HAVE, "needs numpy")
class ViewerTest(unittest.TestCase):
    def test_png_and_html(self):
        import zlib
        import numpy as np
        from kit import viewer
        img = np.arange(12, dtype=np.uint8).reshape(3, 4)
        png = viewer.png_bytes(img)
        self.assertTrue(png.startswith(b"\x89PNG"))
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        self.assertEqual(raw, b"".join(b"\x00" + img[y].tobytes() for y in range(3)))
        rng = np.random.default_rng(1)
        lab = np.zeros((64, 64), bool); lab[20:40, 10:50] = True
        a = lab + 0.5 * rng.random((64, 64)) + 0.01
        b = rng.random((64, 64)) + 0.01
        page, stats = viewer.build_html([("good", a), ("noise", b)], labels=lab)
        self.assertIn("Model output, not a reading", page)
        self.assertGreater(stats["auc_on_view"]["good"], 0.9)
        self.assertLess(abs(stats["auc_on_view"]["noise"] - 0.5), 0.1)
        self.assertIn("good vs noise", stats["rank_correlation"])
        with self.assertRaises(Exception):
            viewer.build_html([("a", a), ("b", b[:10])])

    def test_cli_view(self):
        import numpy as np
        from kit import cli
        with tempfile.TemporaryDirectory() as d:
            np.save(Path(d) / "m.npy", np.random.default_rng(0).random((32, 32)) + 0.01)
            out = Path(d) / "v.html"
            self.assertEqual(cli.main(["view", str(out), f"m={d}/m.npy", "--png", f"{d}/v.png"]), 0)
            self.assertTrue(out.read_text().startswith("<!doctype html>"))
            self.assertTrue((Path(d) / "v.png").read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
