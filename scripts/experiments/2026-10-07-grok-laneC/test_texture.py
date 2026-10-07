"""Synthetic rank-fusion scoring checks; importing texture must not run experiments."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import numpy as np
from kit.auc import score_array

spec = importlib.util.spec_from_file_location("texture", Path(__file__).with_name("texture.py"))
texture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(texture)


class RankFusionTests(unittest.TestCase):
    def test_equal_values_have_average_ranks(self):
        actual = texture.rank(np.array([[3, 1], [1, 2]]))
        np.testing.assert_allclose(actual, [[0.875, 0.25], [0.25, 0.625]])

    def test_constant_map_has_no_pixel_position_signal(self):
        values = np.full((4, 4), 9, dtype=np.uint8)
        ranked = texture.rank(values)
        np.testing.assert_array_equal(ranked, np.full((4, 4), 0.5))
        ink = np.arange(16).reshape(4, 4) >= 8
        result = texture.fusion_comparison(values, values, ink, np.ones((4, 4), bool), 0, inner=0)
        self.assertEqual(result['baseline']['auc'], 0.5)
        self.assertEqual(result['fusion']['auc'], 0.5)

    def test_pixel_permutation_preserves_equal_value_scores(self):
        values = np.array([0, 3, 2, 2, 0, 9])
        order = np.array([4, 1, 5, 0, 3, 2])
        np.testing.assert_array_equal(texture.rank(values)[order], texture.rank(values[order]))

    def test_reference_zero_policy_is_common_to_both_maps(self):
        reference = np.array([[0, 1, 4], [0, 2, 3]], dtype=np.uint8)
        feature = np.array([[99, 0, 2], [88, 1, 3]])
        ink = np.array([[1, 0, 1], [0, 0, 1]], bool)
        result = texture.fusion_comparison(reference, feature, ink, np.ones_like(ink), 0.5, inner=0)
        for key in ('ink_px', 'background_px', 'zero_px_counted'):
            self.assertEqual(result['baseline'][key], result['fusion'][key])
        self.assertEqual(result['baseline']['ink_px'], 2)
        self.assertEqual(result['baseline']['background_px'], 2)

    def test_uint8_reference_auc_preserved_on_common_support(self):
        rng = np.random.default_rng(31)
        reference = rng.integers(0, 256, size=(32, 32), dtype=np.uint8)
        ink = rng.random(reference.shape) > 0.6
        sup = rng.random(reference.shape) > 0.2
        expected = score_array(reference, ink, sup, inner=1)
        actual = texture.fusion_comparison(reference, reference, ink, sup, 0, inner=1)
        self.assertEqual(actual['baseline']['auc'], expected['auc'])
        self.assertEqual(actual['fusion']['auc'], expected['auc'])
        for key in ('ink_px', 'background_px'):
            self.assertEqual(actual['baseline'][key], expected[key])

    def test_rank_fusion_does_not_clip_extreme_distinct_values(self):
        reference = np.arange(1, 1001, dtype=np.uint16).reshape(20, 50)
        ink = reference >= 501
        result = texture.fusion_comparison(reference, reference, ink, np.ones_like(ink), 0.25, inner=0)
        self.assertEqual(result['fusion']['auc'], 1.0)
        ranks = texture.rank(reference)
        self.assertEqual(np.unique(ranks).size, reference.size)

    def test_invalid_rank_inputs_rejected(self):
        for values in (np.array([]), np.array([np.nan]), np.array([np.inf])):
            with self.assertRaises(ValueError):
                texture.rank(values)

    def test_invalid_fusion_weight_or_grid_rejected(self):
        values = np.ones((2, 2))
        mask = np.ones((2, 2), bool)
        with self.assertRaises(ValueError):
            texture.fusion_comparison(values, values, mask, mask, 1.1, inner=0)
        with self.assertRaises(ValueError):
            texture.fusion_comparison(values, np.ones((2, 1)), mask, mask, 0.5, inner=0)


if __name__ == '__main__':
    unittest.main()
