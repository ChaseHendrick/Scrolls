"""Regression oracle for the original map-by-map high-pass scoring formula."""
import unittest
from unittest.mock import patch

from kit import hpscore, verify

try:
    import numpy as np
    from scipy.ndimage import gaussian_filter
except ImportError:
    np = None


def original_score(prediction, ink, supervised, voxel_um, inner=0):
    # Keep the original, independent per-map calculation as a numerical oracle.
    sigma = 48.0 / voxel_um
    pred = prediction.astype(np.float64)
    valid = supervised.astype(bool)
    key = np.where(valid, ink.astype(np.float64), 0.0)
    def high_pass(img, mask):
        weight = gaussian_filter(mask.astype(np.float64), sigma)
        return img - gaussian_filter(img * mask, sigma) / np.maximum(weight, 1e-3)
    kh = high_pass(key, valid)
    core = valid & (gaussian_filter(valid.astype(np.float64), 2 * sigma) > 0.999)
    covered = pred > 0
    selected = core & covered
    if inner:
        if 2 * inner >= min(pred.shape):
            raise verify.VerifyError('inner leaves nothing')
        edge = np.zeros_like(selected)
        edge[inner:-inner, inner:-inner] = True
        selected &= edge
    ph = high_pass(pred, covered)
    def corr(a, b):
        if a.size < 3 or float(a.std()) == 0 or float(b.std()) == 0:
            return None
        return float(np.corrcoef(a, b)[0, 1])
    nulls = []
    for shift in (150, 300, -300):
        shift = int(round(shift * 9.362 / voxel_um))
        both = selected & np.roll(selected, shift, 0)
        value = corr(ph[both], np.roll(kh, shift, 0)[both])
        if value is not None:
            nulls.append(abs(value))
    def rounded(value):
        return None if value is None else round(value, 4)
    return {'hp_r': rounded(corr(ph[selected], kh[selected])),
            'raw_r': rounded(corr(pred[selected], key[selected])),
            'null_max_abs': rounded(max(nulls) if nulls else None),
            'px': int(selected.sum()), 'sigma_px': round(sigma, 3), 'inner': inner}


@unittest.skipIf(np is None, 'numpy and scipy are required')
class HpReuseTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(20261007)
        self.ink = rng.random((192, 208)) > .7
        self.mask = np.ones(self.ink.shape, dtype=bool)
        self.mask[70:85, 50:80] = False
        self.forward = rng.integers(1, 256, self.ink.shape, dtype=np.uint8)
        self.control = rng.integers(1, 256, self.ink.shape, dtype=np.uint8)
        self.forward[:30] = 0
        self.control[:, :40] = 0

    def files(self, control=True, voxel=9.362, inner=8):
        with patch.object(hpscore, '_load', side_effect=lambda p: self.forward if p == 'f' else self.control), \
             patch.object(hpscore, 'labels_on_map', return_value=(self.ink, self.mask)):
            return hpscore.score_files('f', 'labels', 'mask', voxel,
                                       control='c' if control else None, inner=inner)

    def assert_oracle(self, result, voxel=9.362, inner=8):
        self.assertEqual(result['forward'], original_score(self.forward, self.ink, self.mask, voxel, inner))
        if 'control' in result:
            self.assertEqual(result['control'], original_score(self.control, self.ink, self.mask, voxel, inner))

    def test_independent_zero_coverage_and_rolled_nulls_match_original(self):
        result = self.files()
        self.assert_oracle(result)
        self.assertNotEqual(result['forward']['px'], result['control']['px'])
        self.assertIsNotNone(result['control']['null_max_abs'])
        self.assertEqual(hpscore.format_result(result), hpscore.format_result({
            'forward': original_score(self.forward, self.ink, self.mask, 9.362, 8),
            'control': original_score(self.control, self.ink, self.mask, 9.362, 8)}))

    def test_unknown_ink_values_do_not_enter_label_fields(self):
        before = self.files()
        self.ink = self.ink.astype(float)
        self.ink[~self.mask] = np.nan
        after = self.files()
        self.assertEqual(before, after)
        self.assert_oracle(after)

    def test_empty_control_and_empty_supervision_abstain(self):
        self.control[:] = 0
        result = self.files()
        self.assert_oracle(result)
        self.assertEqual(result['control']['px'], 0)
        self.assertIsNone(result['control']['hp_r'])
        self.mask[:] = False
        result = self.files()
        self.assert_oracle(result)
        self.assertEqual(result['forward']['px'], 0)
        self.assertIsNone(result['forward']['null_max_abs'])

    def test_no_control_keeps_original_single_map_result(self):
        result = self.files(control=False)
        self.assert_oracle(result)
        self.assertNotIn('control', result)
        self.assertEqual(hpscore.score_array(self.forward, self.ink, self.mask, 9.362, 8), result['forward'])

    def test_reuse_is_per_call_and_never_caches_changed_labels_or_sigma(self):
        first = self.files()
        self.ink = ~self.ink
        self.mask[:, 100:] = False
        result = self.files(voxel=5.0, inner=3)
        self.assert_oracle(result, voxel=5.0, inner=3)
        self.assertNotEqual(first['forward'], result['forward'])

    def test_only_label_filters_are_reused_and_validation_remains(self):
        ink, mask = self.ink.copy(), self.mask.copy()
        with patch.object(hpscore, '_gaussian', return_value=gaussian_filter) as imported:
            with patch.object(hpscore, '_label_fields', wraps=hpscore._label_fields) as prepared:
                self.assert_oracle(self.files())
                self.assertEqual(prepared.call_count, 1)
                self.assertEqual(imported.call_count, 1)
        np.testing.assert_array_equal(ink, self.ink)
        np.testing.assert_array_equal(mask, self.mask)
        with self.assertRaises(verify.VerifyError):
            self.files(inner=100)
        self.control = self.control[:-1]
        with self.assertRaisesRegex(verify.VerifyError, 'control shape'):
            self.files()


if __name__ == '__main__':
    unittest.main()
