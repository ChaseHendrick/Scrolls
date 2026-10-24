"""A transfer cut off mid-body (http.client.IncompleteRead, which a proxy sometimes causes) is a network failure:
retried where the code retries network failures, reported where it reports them, never a crash. On 9 Oct 2026
three of four runs of one repair tool died on one such read of a prediction chunk."""

import http.client
import io
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kit import s3relay, s3retry, vc3d_audit


class Cut:
    """An opener whose first `cuts` answers stop partway through the body."""

    def __init__(self, body=b"0123456789", cuts=1):
        self.body, self.cuts, self.calls = body, cuts, 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        cut, body = self.calls <= self.cuts, self.body

        class Answer:
            status = 200
            headers = http.client.HTTPMessage()

            def read(self, *a):
                if cut:
                    raise http.client.IncompleteRead(body[:3], len(body) - 3)
                return body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return Answer()


class CutErrorBody:
    """An opener whose first `cuts` answers are HTTP errors (404, as S3 gives for a false 404 too) whose body
    stops partway through, then 200 with the body."""

    def __init__(self, body=b"0123456789", cuts=1, code=404):
        self.body, self.cuts, self.code, self.calls = body, cuts, code, 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        if self.calls <= self.cuts:
            class Error(urllib.error.HTTPError):
                def read(self, *a):
                    raise http.client.IncompleteRead(b"<?xml", 200)
            raise Error(req.full_url, self.code, "Not Found", http.client.HTTPMessage(), io.BytesIO(b""))
        return Cut(self.body, cuts=0)(req, timeout)


class TestCutOffReads(unittest.TestCase):
    def test_the_chunk_store_retries_a_cut_off_read(self):
        opener = Cut(b"chunk bytes")
        store = vc3d_audit.HttpStore("http://bucket.invalid/v.zarr", rate=0, retries=2, timeout=2, opener=opener)
        self.assertEqual(store.read("0/0/0"), b"chunk bytes")
        self.assertEqual(opener.calls, 2)
        always = vc3d_audit.HttpStore("http://bucket.invalid/v.zarr", rate=0, retries=0, timeout=2, opener=Cut(cuts=9))
        status, why = always._request("http://bucket.invalid/v.zarr/k")
        self.assertIsNone(status)
        self.assertIn("IncompleteRead", why)

    def test_the_relay_retries_a_cut_off_read(self):
        opener = Cut(b"grid file")
        relay = s3relay.Relay("http://bucket.invalid/x", opener=opener, sleep=lambda s: None)
        status, _, body = relay.fetch("http://bucket.invalid/x/xy/000001.grid")
        self.assertEqual((status, body, relay.stats["network_errors"]), (200, b"grid file", 1))
        status, _, _ = s3relay.Relay("http://bucket.invalid/x", opener=Cut(cuts=99), sleep=lambda s: None).fetch(
            "http://bucket.invalid/x/k")
        self.assertEqual(status, 502)

    def test_the_relay_retries_a_cut_off_error_body(self):
        # The 404's body is cut off, so its S3 code is unknown: a network failure to retry, never a missing key
        opener = CutErrorBody(b"chunk bytes")
        relay = s3relay.Relay("http://bucket.invalid/x", opener=opener, sleep=lambda s: None)
        status, _, body = relay.fetch("http://bucket.invalid/x/0/0/0/0")
        self.assertEqual((status, body, opener.calls), (200, b"chunk bytes", 2))
        self.assertEqual((relay.stats["network_errors"], relay.stats["missing"]), (1, 0))
        for code in (404, 503):
            always = s3relay.Relay("http://bucket.invalid/x", opener=CutErrorBody(cuts=99, code=code),
                                   sleep=lambda s: None)
            status, _, body = always.fetch("http://bucket.invalid/x/k")
            self.assertEqual((status, always.stats["network_errors"], always.stats["missing"]),
                             (502, s3relay.NETWORK_TRIES, 0), code)
            self.assertIn(b"IncompleteRead", body)

    def test_key_state_calls_a_cut_off_read_unknown(self):
        state, _ = s3retry.key_state("http://bucket.invalid/k", opener=Cut(cuts=9), sleep=lambda s: None)
        self.assertEqual(state, s3retry.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
