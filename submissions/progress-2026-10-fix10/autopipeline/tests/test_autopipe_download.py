"""kit.autopipe.download: workers fetching the same object at once never collide (a layer-separation run's
extraction, 12 Oct 2026)."""
import io
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kit import autopipe  # noqa: E402

PAYLOAD = b"chunk-bytes " * 1000


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener(req, timeout=None):
    return _Resp(PAYLOAD)


def race(dest, part_name):
    """Two threads download dest; both finish writing their temporary file before either renames it."""
    barrier = threading.Barrier(2, timeout=10)
    real_replace = pathlib.Path.replace

    def replace(self, target):
        if str(self).endswith(".part"):
            barrier.wait()
        return real_replace(self, target)

    errors = []

    def one():
        try:
            autopipe.download("https://example.invalid/k", dest, opener)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with mock.patch.object(pathlib.Path, "replace", replace), mock.patch.object(autopipe, "part_name", part_name):
        ts = [threading.Thread(target=one) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
    return errors


class DownloadRaceTest(unittest.TestCase):
    def test_concurrent_downloads_of_one_object(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "zarr" / "0" / ".zarray"
            errors = race(dest, autopipe.part_name)
            self.assertEqual(errors, [])
            self.assertEqual(dest.read_bytes(), PAYLOAD)
            self.assertEqual([p.name for p in dest.parent.iterdir()], [".zarray"])   # no temporary file left

    def test_the_old_shared_name_fails_the_same_race(self):
        """The control: with every worker on dest.part, the second rename finds nothing to rename."""
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "zarr" / "0" / ".zarray"
            errors = race(dest, lambda p: Path(p).with_name(Path(p).name + ".part"))
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], FileNotFoundError)

    def test_part_names_differ_by_thread_and_end_in_part(self):
        names = set()
        alive = threading.Barrier(4, timeout=10)    # all four alive at once, so no thread id is reused

        def one():
            names.add(autopipe.part_name("/x/y/0.0.0"))
            alive.wait()

        ts = [threading.Thread(target=one) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        names.add(autopipe.part_name("/x/y/0.0.0"))
        self.assertEqual(len(names), 5)
        self.assertTrue(all(n.name.startswith("0.0.0.") and n.name.endswith(".part") for n in names))
        self.assertIn(f".{os.getpid()}.", autopipe.part_name("/x/y/0.0.0").name)

    def test_a_failed_write_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "k"
            with mock.patch.object(pathlib.Path, "replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    autopipe.download("https://example.invalid/k", dest, opener)
            self.assertEqual(list(Path(d).iterdir()), [])


def not_found(code):
    """An opener that answers every request with HTTP 404 and an S3 error body naming `code` (None: no body)."""
    import urllib.error

    def op(req, timeout=None):
        body = b"" if code is None else f"<Error><Code>{code}</Code></Error>".encode()
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(body))
    return op


class OptionalDownloadTest(unittest.TestCase):
    """optional=True turns a missing key into False; a key S3 keeps answering with a false 404 is not missing."""

    def setUp(self):
        sleep = mock.patch("time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_a_real_404_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            for code in ("NoSuchKey", None):
                self.assertFalse(autopipe.download("https://example.invalid/k", Path(d) / "k", not_found(code),
                                                   tries=2, optional=True))

    def test_a_persistent_false_404_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(autopipe.AutoError) as cm:
                autopipe.download("https://example.invalid/k", Path(d) / "k", not_found("NoSuchBucket"), tries=2,
                                  optional=True)
            self.assertIn("NoSuchBucket", str(cm.exception))
            self.assertEqual(list(Path(d).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
