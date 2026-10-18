"""A 404 is a missing key only when S3 says NoSuchKey (kit/s3retry.py)."""

import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import fetch, s3retry, vc3d_audit  # noqa: E402

BUCKET = b"<?xml version='1.0'?><Error><Code>NoSuchBucket</Code><Message>x</Message></Error>"
NOKEY = b"<Error><Code>NoSuchKey</Code></Error>"


def http_error(code, body):
    return urllib.error.HTTPError("https://bucket.example/k", code, "x", {}, io.BytesIO(body))


class Opener:
    """Answers from a list: bytes are a 200 body, an int and body an HTTPError."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, tuple):
            raise http_error(*a)
        return io.BytesIO(a)


class TestCodes(unittest.TestCase):
    def test_error_codes(self):
        self.assertEqual(s3retry.error_code(BUCKET), "NoSuchBucket")
        self.assertEqual(s3retry.error_code("<Code> NoSuchKey </Code>"), "NoSuchKey")
        self.assertIsNone(s3retry.error_code(b""))
        self.assertIsNone(s3retry.error_code(b"<html>not found</html>"))
        self.assertTrue(s3retry.false_404(404, BUCKET))
        self.assertFalse(s3retry.false_404(404, NOKEY))
        self.assertFalse(s3retry.false_404(404, b"plain not found"))   # a server that is not S3: missing
        self.assertFalse(s3retry.false_404(403, BUCKET))

    def test_remote_zarr_is_refused(self):
        for url in ("https://a/b.zarr", "s3://bucket/x.zarr", "GS://b/c"):
            with self.assertRaises(ValueError):
                s3retry.refuse_remote(url)
        self.assertEqual(s3retry.refuse_remote("/data/x.zarr"), "/data/x.zarr")


class TestOpenUrl(unittest.TestCase):
    def test_false_404s_are_asked_again(self):
        op, count = Opener([(404, BUCKET), (404, BUCKET), b"data"]), {}
        resp = s3retry.open_url("u", op, sleep=lambda s: None, counter=count)
        self.assertEqual((resp.read(), op.calls, count["false_404"]), (b"data", 3, 2))

    def test_a_missing_key_is_raised_at_once_with_its_body(self):
        op = Opener([(404, NOKEY), b"never"])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            s3retry.open_url("u", op, sleep=lambda s: None)
        self.assertEqual((op.calls, cm.exception.read()), (1, NOKEY))

    def test_a_false_404_every_time_is_not_a_missing_key(self):
        op = Opener([(404, BUCKET)] * 4)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            s3retry.open_url("u", op, tries=4, sleep=lambda s: None)
        self.assertEqual(op.calls, 4)
        self.assertIn("not taken as a missing key", str(cm.exception.reason))

    def test_other_errors_pass_through(self):
        op = Opener([(500, b"oops")])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            s3retry.open_url("u", op, sleep=lambda s: None)
        self.assertEqual((cm.exception.code, op.calls), (500, 1))


class TestAgainstAServer(unittest.TestCase):
    """A local server that answers like S3, false 404s included."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "k").write_bytes(b"0123456789")
        self.opener = fakes.no_proxy_opener()

    def tearDown(self):
        self.tmp.cleanup()

    def test_key_state(self):
        with fakes.S3LikeServer(self.d, false=2, always_false={"bad"}) as srv:
            st = lambda key: s3retry.key_state(f"{srv.url}/{key}", self.opener, sleep=lambda s: None)[0]  # noqa
            self.assertEqual(st("k"), s3retry.PRESENT)
            self.assertEqual(st("gone"), s3retry.MISSING)
            self.assertEqual(st("bad"), s3retry.UNKNOWN)
            self.assertEqual(srv.hits["k"], 3)   # two false 404s, then the byte

    def test_audit_store_retries_and_confirms(self):
        with fakes.S3LikeServer(self.d, false=1, always_false={"bad"}) as srv:
            store = vc3d_audit.HttpStore(srv.url, rate=0, opener=self.opener, false_404_tries=3)
            self.assertEqual(store.read("k", 2, 3), b"234")
            self.assertIsNone(store.read("gone"))
            with self.assertRaises(vc3d_audit.AuditError):
                store.read("bad")
            self.assertEqual(store.states(["k", "gone", "bad"]),
                             {"k": "present", "gone": "missing", "bad": "unknown"})
            self.assertGreaterEqual(store.false_404s, 3)

    def test_fetch_survives_false_404s(self):
        listing = ("<ListBucketResult><Contents><Key>p/a.zarr/k</Key><Size>10</Size></Contents>"
                   "</ListBucketResult>")
        (self.d / "p" / "a.zarr").mkdir(parents=True)
        (self.d / "p" / "a.zarr" / "k").write_bytes(b"0123456789")
        with fakes.S3LikeServer(self.d, false=3) as srv:
            def opener(url, timeout=None):
                if "list-type=2" in str(url):
                    return io.BytesIO(listing.encode())
                return self.opener(url, timeout=timeout)
            out = self.d / "out"
            self.assertEqual(fetch.fetch_prefix("p/a.zarr", out, workers=1, opener=opener, base=srv.url),
                             (1, 10, 10))
            self.assertEqual((out / "k").read_bytes(), b"0123456789")


if __name__ == "__main__":
    unittest.main()
