"""Center Finder input failures with synthetic responses, without scans or weights."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, "needs numpy")
class CenterFinderInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "scripts/umbilicus/slices.py"
        spec = importlib.util.spec_from_file_location("centerfinder_io_under_test", path)
        cls.slices = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.slices)

    def setUp(self):
        # Even an unexpected request cannot reach the network.
        self.session = mock.Mock()
        self.session.get.side_effect = AssertionError("unexpected network request")
        patch = mock.patch.object(self.slices, "_session", return_value=self.session)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(self.slices.time, "sleep")
        patch.start()
        self.addCleanup(patch.stop)

    @staticmethod
    def response(status, body):
        return SimpleNamespace(status_code=status, content=body)

    def test_false_404_retries_instead_of_becoming_empty_data(self):
        for name, args in (("get", ()), ("get_range", (2, 4))):
            with self.subTest(reader=name):
                self.session.get.reset_mock()
                self.session.get.side_effect = [
                    self.response(404, b"<Error><Code>InternalError</Code></Error>"),
                    self.response(200, b"abcdef"),
                ]
                value = getattr(self.slices, name)("https://example.invalid/chunk", *args, retries=2)
                self.assertEqual(value, b"abcdef" if name == "get" else b"cde")
                self.assertEqual(self.session.get.call_count, 2)

    def test_only_no_such_key_is_treated_as_missing(self):
        for name, args in (("get", ()), ("get_range", (0, 2))):
            with self.subTest(reader=name):
                self.session.get.reset_mock()
                self.session.get.side_effect = [
                    self.response(404, b"<Error><Code>NoSuchKey</Code></Error>")
                ]
                self.assertIsNone(getattr(self.slices, name)("https://example.invalid/chunk", *args))
                self.session.get.assert_called_once()

    def test_range_response_and_full_response_have_same_inclusive_bytes(self):
        for status, body in ((206, b"cde"), (200, b"abcdef")):
            with self.subTest(status=status):
                self.session.get.reset_mock()
                self.session.get.side_effect = [self.response(status, body)]
                self.assertEqual(self.slices.get_range("https://example.invalid/chunk", 2, 4), b"cde")
                self.session.get.assert_called_once_with(
                    "https://example.invalid/chunk", headers={"Range": "bytes=2-4"}, timeout=60
                )

    def test_failed_requests_raise_after_the_retry_limit(self):
        for name, args in (("get", ()), ("get_range", (0, 2))):
            with self.subTest(reader=name):
                self.session.get.reset_mock()
                self.session.get.side_effect = [TimeoutError("timed out"), self.response(503, b"busy")]
                with self.assertRaisesRegex(RuntimeError, "503"):
                    getattr(self.slices, name)("https://example.invalid/chunk", *args, retries=2)
                self.assertEqual(self.session.get.call_count, 2)

    def test_grid_shape_rejects_boolean_zero_negative_and_noninteger_axes(self):
        for shape in ([True, 3, 4], [0, 3, 4], [2, -3, 4], [2.5, 3, 4], [2, 3], "2,3,4"):
            with self.subTest(shape=shape), mock.patch.object(
                self.slices, "get", return_value=json.dumps({"shape": shape}).encode()
            ):
                with self.assertRaisesRegex(ValueError, "three positive integers"):
                    self.slices.level0_shape("synthetic/volume")

    def test_missing_grid_is_distinct_from_a_valid_grid(self):
        with mock.patch.object(self.slices, "get", return_value=None):
            self.assertIsNone(self.slices.level0_shape("synthetic/volume"))
        with mock.patch.object(self.slices, "get", return_value=b'{"shape":[2,3,4]}'):
            self.assertEqual(self.slices.level0_shape("synthetic/volume"), [2, 3, 4])

    def test_unsupported_storage_is_refused_before_any_chunk_read(self):
        base = {"shape": [3, 4, 5], "chunks": [128, 128, 128], "compressor": None,
                "dtype": "|u1", "order": "C"}
        for change in ({"compressor": {"id": "blosc"}}, {"chunks": [64, 128, 128]},
                       {"dtype": "<u2"}, {"order": "F"}):
            with self.subTest(change=change), mock.patch.object(
                self.slices, "get", return_value=json.dumps({**base, **change}).encode()
            ), mock.patch.object(self.slices, "get_range") as read:
                with self.assertRaisesRegex(ValueError, "needs raw"):
                    self.slices.PlaneReader("synthetic/volume", 3)
                read.assert_not_called()

    def test_plane_outside_volume_returns_zeros_without_reading_chunks(self):
        meta = {"shape": [3, 4, 5], "chunks": [128, 128, 128], "compressor": None, "dtype": "|u1"}
        with mock.patch.object(self.slices, "get", return_value=json.dumps(meta).encode()):
            reader = self.slices.PlaneReader("synthetic/volume", 3)
        with mock.patch.object(self.slices, "get_range") as read:
            for z in (-1, 3):
                with self.subTest(z=z):
                    np.testing.assert_array_equal(reader.plane(z), np.zeros((4, 5), np.uint8))
            read.assert_not_called()
        self.assertEqual(reader.missing, 0)


if __name__ == "__main__":
    unittest.main()
