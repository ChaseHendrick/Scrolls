"""Bootstrap optimization checked against explicit resampled pixels and ties."""
import unittest
from unittest.mock import patch

from kit import auc, verify

try:
    import numpy as np
except ImportError:
    np = None


def pixel_oracle(prediction, ink, mask, other, draws, block_px, seed, keep_zero, inner):
    """Direct sampled-pixel Mann-Whitney statistic, independent of block histograms."""
    valid = mask.copy()
    if inner:
        valid[:inner] = valid[-inner:] = False
        valid[:, :inner] = valid[:, -inner:] = False
    if not keep_zero:
        valid &= (prediction != 0) & (other != 0)
    ys, xs = np.nonzero(valid)
    groups = {}
    for index, (y, x) in enumerate(zip(ys, xs)):
        groups.setdefault((int(y) // block_px, int(x) // block_px), []).append(index)
    groups = [np.asarray(groups[key]) for key in sorted(groups)]
    labels = ink[ys, xs]
    scores = []
    for image in (prediction, other):
        if image.dtype in (np.uint8, np.uint16):
            values = image.astype(np.int64)
            scale = 255 if image.dtype == np.uint8 else 65535
        else:
            values = image.astype(float)
            top = float(values.max())
            if top > 1:
                values /= 255 if top <= 255 else 65535
            values = np.clip(np.round(values * 65535), 0, 65535).astype(np.int64)
            scale = 65535
        scores.append(values[ys, xs] * 1023 // scale)

    def mann_whitney(values, lab):
        positive, negative = values[lab], values[~lab]
        wins = (positive[:, None] > negative).sum()
        ties = (positive[:, None] == negative).sum()
        return float((wins + .5 * ties) / (positive.size * negative.size))

    rng = np.random.default_rng(seed)
    sampled = [np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
               for _ in range(draws)]
    distributions = [np.asarray([mann_whitney(values[index], labels[index]) for index in sampled])
                     for values in scores]
    point = [mann_whitney(values, labels) for values in scores]
    lo, hi = np.percentile(distributions[0], [2.5, 97.5])
    difference = distributions[0] - distributions[1]
    dlo, dhi = np.percentile(difference, [2.5, 97.5])
    return {"draws": draws, "block_px": block_px, "blocks": len(groups), "seed": seed,
            "ci95": [round(float(lo), 4), round(float(hi), 4)], "half_width": round(float(hi - lo) / 2, 4),
            "compare": {"auc_map": round(point[0], 4), "auc_other": round(point[1], 4),
                        "difference": round(point[0] - point[1], 4), "ci95": [round(float(dlo), 4), round(float(dhi), 4)],
                        "share_draws_map_not_ahead": round(float((difference <= 0).mean()), 4), "pixels": len(ys)}}


@unittest.skipIf(np is None, "numpy is required")
class ExactBootstrapTests(unittest.TestCase):
    def setUp(self):
        y, x = np.mgrid[:13, :17]
        self.ink = (y + x) % 3 == 0
        self.mask = np.ones_like(self.ink)
        rng = np.random.default_rng(710)
        self.prediction = rng.integers(0, 256, self.ink.shape, dtype=np.uint8)
        self.other = rng.integers(0, 256, self.ink.shape, dtype=np.uint8)
        self.prediction[::4, ::5] = 0
        self.other[::5, ::4] = 0

    def test_paired_pixel_oracle_covers_quantization_zeros_and_partial_blocks(self):
        pairs = [(self.prediction, self.other),
                 (self.prediction.astype(np.uint16) * 257, self.other.astype(np.uint16) * 257),
                 (self.prediction.astype(float) / 255, self.other.astype(float) / 255),
                 (self.prediction.astype(float), self.other.astype(float)),
                 (self.prediction.astype(float) * 257, self.other.astype(float) * 257)]
        for first, second in pairs:
            for keep_zero in (False, True):
                for inner in (0, 1):
                    with self.subTest(dtype=first.dtype, maximum=first.max(), zeros=keep_zero, inner=inner):
                        expected = pixel_oracle(first, self.ink, self.mask, second, 40, 5, 711, keep_zero, inner)
                        actual = auc.block_bootstrap(first, self.ink, self.mask, 40, 5, 711, second, keep_zero, inner)
                        self.assertEqual(actual, expected)

    def test_tied_identity_difference_is_exactly_zero(self):
        image = np.full(self.ink.shape, 127, np.uint8)
        result = auc.block_bootstrap(image, self.ink, self.mask, 40, 5, 19, image, True)
        self.assertEqual(result["ci95"], [.5, .5])
        self.assertEqual(result["compare"]["ci95"], [0., 0.])
        self.assertEqual(result["compare"]["share_draws_map_not_ahead"], 1.)

    def test_sparse_huge_coordinate_range_never_allocates_by_canvas_extent(self):
        keys = np.array([1, 10 ** 12, 1, 10 ** 12 + 3], np.int64)
        with patch.object(np, "bincount", side_effect=AssertionError("unbounded allocation")):
            blocks, inverse = auc._block_ids(np, keys)
        np.testing.assert_array_equal(blocks, [1, 10 ** 12, 10 ** 12 + 3])
        np.testing.assert_array_equal(inverse, [0, 1, 0, 2])

    def test_empty_columns_are_shared_across_compared_maps(self):
        a = np.zeros((2, 1024)); b = a.copy(); c = a.copy(); d = a.copy()
        a[:, 0] = [3, 1]; b[:, 1023] = [2, 4]
        c[:, 500] = [3, 1]; d[:, 501] = [2, 4]
        weights = np.array([[1., 1.], [2., 0.]])
        compact = auc._compact_histograms(np, [(a, b), (c, d)], weights)
        self.assertEqual(compact[0][0].shape, (2, 4))
        for original, reduced in zip([(a, b), (c, d)], compact):
            np.testing.assert_array_equal(auc._auc_hist(np, weights @ original[0], weights @ original[1]),
                                          auc._auc_hist(np, weights @ reduced[0], weights @ reduced[1]))

    def test_large_population_keeps_historical_float_reduction_layout(self):
        a = np.zeros((2, 1024)); b = a.copy()
        a[0, 1] = 2 ** 25; b[1, 1000] = 2 ** 25
        original = [(a, b)]
        # Source population is safe, but this draw duplicates its large block.
        weights = np.array([[3., 0.]])
        self.assertIs(auc._compact_histograms(np, original, weights), original)
        a[0, 1] += 1
        self.assertIs(auc._compact_histograms(np, original, np.array([[1., 1.]])), original)

    def test_existing_validation_errors_remain(self):
        for changes in [{"draws": 19}, {"block_px": 0}, {"other": np.zeros((2, 3))}]:
            with self.assertRaises(verify.VerifyError):
                auc.block_bootstrap(self.prediction, self.ink, self.mask, **changes)
        with self.assertRaisesRegex(verify.VerifyError, "no supervised"):
            auc.block_bootstrap(self.prediction, self.ink, np.zeros_like(self.mask))
        with self.assertRaisesRegex(verify.VerifyError, "one class"):
            auc.block_bootstrap(self.prediction, np.ones_like(self.ink), self.mask)


if __name__ == "__main__":
    unittest.main()
