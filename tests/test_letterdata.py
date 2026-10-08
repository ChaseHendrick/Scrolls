import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    import numpy as np
    import PIL  # noqa: F401  (rendering needs Pillow)
    sys.path.insert(0, str(ROOT / "scripts" / "letters"))
    import gen_dataset
    import letterdata as L
except ImportError:  # synthetic data needs numpy and Pillow; the core kit does not
    np = L = gen_dataset = None
finally:
    if str(ROOT / "scripts" / "letters") in sys.path:
        sys.path.remove(str(ROOT / "scripts" / "letters"))


@unittest.skipIf(L is None, "numpy or Pillow not installed")
class LetterDataTest(unittest.TestCase):
    def test_every_letter_has_a_skeleton(self):
        self.assertEqual(len(L.ALPHABET), 24)
        self.assertEqual(set(L.SKELETONS), set(L.ALPHABET))

    def test_sample_shape_text_and_boxes(self):
        rng = np.random.default_rng(0)
        for domain in ("map", "mask"):
            for _ in range(4):
                img, text, boxes = L.make_sample(rng, domain=domain, p_blank=0.0, style=L.random_style(rng, "skeleton"))
                self.assertEqual(img.shape[0], L.band_height())
                self.assertTrue(0.0 <= img.min() and img.max() <= 1.0)
                self.assertTrue(text and set(text) <= set(L.ALPHABET))
                self.assertEqual(len(boxes), len(text))
                self.assertTrue(all(b[0] < b[1] for b in boxes))
                self.assertEqual([b[0] for b in boxes], sorted(b[0] for b in boxes))

    def test_blank_lines_have_no_text(self):
        rng = np.random.default_rng(1)
        img, text, boxes = L.make_sample(rng, p_blank=1.0, style=L.random_style(rng, "skeleton"))
        self.assertEqual((text, boxes), ("", []))
        self.assertEqual(img.shape[0], L.band_height())

    def test_seeded_samples_repeat(self):
        a = L.make_sample(np.random.default_rng(5), style=None)
        b = L.make_sample(np.random.default_rng(5), style=None)
        self.assertEqual(a[1], b[1])
        self.assertTrue(np.array_equal(a[0], b[0]))

    def test_page(self):
        rng = np.random.default_rng(2)
        img, lines, centres, h = L.make_page(rng, n_lines=3, h=20.0, style=L.random_style(rng, "skeleton"))
        self.assertEqual(len(lines), 3)
        self.assertEqual(centres, sorted(centres))
        self.assertTrue(img.shape[0] > 3 * h)

    def test_shard_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            out = gen_dataset.shard((str(Path(d) / "s.npz"), 3, 5, None))
            imgs, texts, boxes = gen_dataset.load_shard(out)
        self.assertEqual(len(imgs), 5)
        self.assertEqual(len(texts), 5)
        for im, t, b in zip(imgs, texts, boxes):
            self.assertEqual(im.dtype, np.uint8)
            self.assertEqual(im.shape[0], L.band_height())
            self.assertEqual(len(b), len(t))


if __name__ == "__main__":
    unittest.main()
