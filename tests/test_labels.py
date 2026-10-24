"""Tests for kit.labels against a fake bucket built here (no network).

The fake answers S3 ListObjectsV2 (with and without a delimiter, paged) and object reads. A segment with ink labels
is listed with its arrays' shapes and stored bytes, one without is left out; exposure comes from the records and is
scoped (PHerc0139's w045 record does not reach a w045 of another scroll, and a segment with no record is "unknown");
a held_out key the code does not place is reported, not dropped; a listing cut at its page limit says so."""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from kit import cli, find, labels


class FakeBucket:
    def __init__(self, objects, page=1000):
        self.objects, self.page, self.calls = dict(objects), page, 0

    def __call__(self, url):
        self.calls += 1
        if url == find.METADATA:
            return json.dumps({"samples": {"PHerc0139": {}, "PHerc1667": {}}}).encode()
        base = find.BUCKET + "/"
        rest = url[len(base):]
        if rest.startswith("?"):
            q = dict(urllib.parse.parse_qsl(rest[1:]))
            pre, delim = q.get("prefix", ""), q.get("delimiter")
            keys = sorted(k for k in self.objects if k.startswith(pre))
            start = int(q.get("continuation-token", 0))
            prefixes, items = set(), []
            for k in keys:
                tail = k[len(pre):]
                if delim and delim in tail:
                    prefixes.add(pre + tail.split(delim)[0] + delim)
                else:
                    items.append(k)
            chunk = items[start:start + self.page]
            xml = "".join(f"<Contents><Key>{k}</Key><Size>{len(self.objects[k])}</Size></Contents>" for k in chunk)
            xml += "".join(f"<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>" for p in sorted(prefixes))
            if start + self.page < len(items):
                xml += f"<NextContinuationToken>{start + self.page}</NextContinuationToken>"
            return f"<ListBucketResult><Prefix>{pre}</Prefix>{xml}</ListBucketResult>".encode()
        key = urllib.parse.unquote(rest)
        if key not in self.objects:
            raise OSError(f"404 {key}")
        return self.objects[key]


def label_zarr(prefix, shape=(400, 600)):
    root = {"zarr_format": 3, "node_type": "group", "attributes": {"ome": {"multiscales": [
        {"datasets": [{"path": "0"}, {"path": "1"}]}]}}}
    arr = {"zarr_format": 3, "node_type": "array", "shape": list(shape), "data_type": "uint8"}
    return {prefix + "zarr.json": json.dumps(root).encode(), prefix + "0/zarr.json": json.dumps(arr).encode(),
            prefix + "0/c/0/0": b"x" * 1000, prefix + "1/zarr.json": json.dumps(arr).encode(),
            prefix + "1/c/0/0": b"y" * 250}


def bucket():
    obj = {}
    s = "PHerc0139/segments/20260126000000-w045_2026012619/"
    d = s + "ink-labels/2.399um-volume-20260102150214/20260918/"
    obj.update(label_zarr(d + "inklabels.zarr/"))
    obj.update(label_zarr(d + "supervision.zarr/"))
    obj[s + "mesh/m.tifxyz/x.tif"] = b"0"
    s2 = "PHerc0139/segments/20250108000005-w030_2025010818/"
    obj.update(label_zarr(s2 + "ink-labels/2.399um-volume-20260102150214/20260918/inklabels.zarr/", (10, 20)))
    obj["PHerc0139/segments/20250101000000-w099_x/mesh/m.tifxyz/x.tif"] = b"0"     # no labels: left out
    s3 = "PHerc1667/segments/20240304141531-w045_flatboi/"                          # a w045 of another scroll
    obj.update(label_zarr(s3 + "ink-labels/2.399um-volume-20251217075048/20260918/inklabels.zarr/"))
    return FakeBucket(obj)


RECS = [{"key": "w045", "scroll": "PHerc0139", "segment": "w045", "text": "held out from v8in only. More text.",
         "by_reader": {"v8in": "held out", "ink_9um": "not held out"}, "source": "docs/results.json held_out.w045"}]


class TestLabels(unittest.TestCase):
    def test_inventory(self):
        r = labels.inventory("PHerc0139", get=bucket(), recs=RECS)
        self.assertEqual((r["segments"], r["labeled"]), (3, 2))
        row = next(x for x in r["rows"] if x["short_id"] == "w045")
        s = row["label_sets"][0]
        self.assertEqual((s["volume"], s["voxel_um"], s["date"]), ("20260102150214", 2.399, "20260918"))
        self.assertEqual(sorted(s["arrays"]), ["inklabels", "supervision"])
        a = s["arrays"]["inklabels"]
        self.assertEqual((a["shape"], a["dtype"], a["levels"]), ([400, 600], "uint8", 2))
        self.assertEqual(a["bytes"], sum(len(v) for v in label_zarr("").values()))
        self.assertEqual(a["files"], 5)
        self.assertEqual(row["exposure"][0]["by_reader"]["v8in"], "held out")
        self.assertEqual(row["exposure"][0]["summary"], "held out from v8in only")
        other = next(x for x in r["rows"] if x["short_id"] == "w030")
        self.assertTrue(other["exposure"].startswith("unknown"))
        text = labels.format_inventory(r)
        self.assertIn("No record means unknown, not held out", text)

    def test_scope_stays_on_its_scroll(self):
        r = labels.inventory("PHerc1667", get=bucket(), recs=RECS)
        self.assertEqual(r["labeled"], 1)
        self.assertTrue(r["rows"][0]["exposure"].startswith("unknown"))

    def test_records_from_files(self):
        with tempfile.TemporaryDirectory() as t:
            res, std = Path(t, "results.json"), Path(t, "STANDARDS.md")
            res.write_text(json.dumps({"held_out": {"w045": "x", "w999": "y"},
                                       "held_out_by_reader": {"w045": {"v8in": "held out"}}}))
            std.write_text("## 5. Data splits and held-out sets\n\n| Data | Role here | Defined in |\n| --- | --- |"
                           " --- |\n| PHerc0139 w035 | Training segment. | x |\n\n## 6. Next\n| Other | no |\n")
            recs, unmatched = labels.records(res, std)
            self.assertEqual(unmatched, ["w999"])
            keys = {r["key"]: r for r in recs}
            self.assertEqual(keys["w045"]["by_reader"], {"v8in": "held out"})
            self.assertEqual(keys["PHerc0139 w035"]["text"], "Training segment.")
            self.assertNotIn("Other", labels.standards_rows(std))

    def test_repository_records_are_placed(self):
        recs, unmatched = labels.records()
        self.assertEqual(unmatched, [], "a held_out record in docs/results.json needs a scope in kit/labels.py SCOPES")
        self.assertIn("PHerc0139 w035", {r["key"] for r in recs})

    def test_listing_page_limit(self):
        b = FakeBucket({f"p/k{i}": b"ab" for i in range(5)}, page=2)
        keys, cut = labels.list_all("p/", b, max_pages=2)
        self.assertEqual((len(keys), cut), (4, True))
        keys, cut = labels.list_all("p/", b, max_pages=3)
        self.assertEqual((len(keys), cut), (5, False))

    def test_short_id(self):
        self.assertEqual(labels.short_id("20260317000000-w035_2026031718"), "w035")
        self.assertEqual(labels.short_id("20260220213127-w00"), "w00")
        self.assertIsNone(labels.short_id("20260220214732-auto_grown_20260220144552896"))

    def test_retry(self):
        import urllib.error
        calls = []

        def flaky(url):
            calls.append(url)
            if len(calls) < 3:
                raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
            return b"ok"
        orig = find.http_get
        find.http_get = flaky
        try:
            self.assertEqual(labels.http_get("u", sleep=lambda s: None), b"ok")
            calls.clear()
            find.http_get = lambda url: (_ for _ in ()).throw(urllib.error.HTTPError(url, 404, "nf", {}, None))
            with self.assertRaises(urllib.error.HTTPError):
                labels.http_get("u", sleep=lambda s: None)
        finally:
            find.http_get = orig

    def test_cli_bad_id(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["labels", "bad id!"]), 2)
        self.assertIn("not a scroll id", err.getvalue())


if __name__ == "__main__":
    unittest.main()
