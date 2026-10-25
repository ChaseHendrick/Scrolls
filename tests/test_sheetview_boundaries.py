"""Synthetic boundary tests for the local sampling rule used by Unroll Live sheet.

These exercise kit.sheetview only. They neither load nor test the separate Unroll
Space, its JavaScript implementation, or its browser interface.
"""

import unittest
from unittest import mock

try:
    import numpy as np
except ImportError:
    np = None

from kit import sheetview as sv
from kit.verify import VerifyError


@unittest.skipIf(np is None, "needs numpy")
class SheetviewBoundaryTests(unittest.TestCase):
    def volume(self):
        # Use the real chunk reader on a tiny in-memory array, without zarr or I/O.
        volume = object.__new__(sv.Volume)
        volume.shape = [5, 6, 7]
        volume.chunks = [3, 4, 4]
        volume.factor = [1.0, 1.0, 1.0]
        z, y, x = np.indices(volume.shape)
        volume._data = (100 * z + 10 * y + x).astype(np.float32)
        volume._cache, volume._cache_bytes = {}, 0
        volume.fetch = mock.Mock()
        return volume

    @staticmethod
    def sheet(z):
        y, x = np.mgrid[1:4, 1:4]
        return np.stack([x, y, np.full_like(x, z)], axis=-1).astype(float)

    def test_chunk_edges_preserve_xyz_and_outside_indices_do_not_wrap(self):
        volume = self.volume()
        idx = np.array([[[0, 0, 0], [2, 3, 3], [3, 4, 4], [4, 5, 6], [-1, 0, 0], [5, 0, 0]]])
        np.testing.assert_array_equal(volume.sample(idx), [[0, 233, 344, 456, np.nan, np.nan]])
        np.testing.assert_array_equal(volume.need(idx), [[0, 0, 0], [1, 1, 1]])
        self.assertEqual(volume.chunk([1, 1, 1]).shape, (2, 2, 3))

    def test_chunk_cache_reuses_a_read_then_evicts_when_full(self):
        volume = self.volume()
        reader = mock.Mock(wraps=volume._array)
        with mock.patch.object(volume, "_array", reader), mock.patch.object(sv, "CHUNK_CACHE_BYTES", 192):
            first = volume.chunk([0, 0, 0])
            self.assertIs(volume.chunk([0, 0, 0]), first)
            self.assertEqual(reader.call_count, 1)
            volume.chunk([1, 1, 1])
            self.assertNotIn((0, 0, 0), volume._cache)
            np.testing.assert_array_equal(volume.chunk([0, 0, 0]), first)
            self.assertEqual(reader.call_count, 3)

    def test_mean_at_a_volume_edge_ignores_missing_samples(self):
        volume = self.volume()
        xyz = self.sheet(0)
        values, chunks, samples = sv.sample_sheet(xyz, np.ones((3, 3), bool), volume, depth=2, reduce="mean")
        # z = -2 and -1 are absent, so the mean is over z = 0, 1 and 2 only.
        np.testing.assert_array_equal(values, 100 + 10 * xyz[..., 1] + xyz[..., 0])
        self.assertEqual((chunks, samples), (1, 5))
        volume.fetch.assert_called_once()

    def test_all_samples_outside_stay_nan_and_request_no_chunks(self):
        volume = self.volume()
        values, chunks, samples = sv.sample_sheet(self.sheet(-5), np.ones((3, 3), bool), volume, depth=2)
        self.assertTrue(np.isnan(values).all())
        self.assertEqual((chunks, samples), (0, 5))
        self.assertEqual(volume.fetch.call_args.args[0].shape, (0, 3))

    def test_anisotropic_level_factors_and_missing_normal_use_center_voxel(self):
        indices = sv._sample_index(np.array([[6.0, 10.0, 12.0]]),
                                   np.array([[np.nan, np.nan, np.nan]]), np.array([-8.0, 0.0, 8.0]), [4, 2, 1])
        np.testing.assert_array_equal(indices, [[[3, 5, 6], [3, 5, 6], [3, 5, 6]]])

    def test_invalid_depth_or_reducer_refuses_before_sampling(self):
        for depth in (-1, float("nan"), float("inf")):
            with self.subTest(depth=depth), self.assertRaisesRegex(VerifyError, "--depth"):
                sv._offsets(depth, 1)
        volume = self.volume()
        with mock.patch.object(volume, "sample") as sample:
            with self.assertRaisesRegex(VerifyError, "--reduce"):
                sv.sample_sheet(self.sheet(0), np.ones((3, 3), bool), volume, reduce="median")
            sample.assert_not_called()
        volume.fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
