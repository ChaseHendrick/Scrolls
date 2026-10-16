"""kit/scancatalog.py and kit/autobatch.py on a synthetic catalog: no network, no Modal."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from kit import autobatch, scancatalog
from kit import cloudcost

LISTING_XML = """<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
<IsTruncated>false</IsTruncated>{}</ListBucketResult>"""


def vol(vid, um, shape, superseded=None, root="s3://vesuvius-challenge-open-data", pred=True, path=None):
    name = f"{vid}-{um}um-0.2m-78keV-masked.zarr"
    data = [{"type": "ome-zarr", "origins": [{"path": path or f"S1/volumes/{name}/",
                                                "access_roots": [{"type": "s3", "url": root}]}]}]
    if pred:
        data.append({"type": "surface-prediction-zarr", "origins": [{"path": "x"}],
                     "parameters": {"model_id": "m7", "level": 2}})
        data.append({"type": "normal-grids", "origins": [{"path": "y"}]})
    return {"id": vid, "long_id": name, "scan_id": "sc" + vid, "data": data,
            "properties": {"pixel_size_um": um, "energy_keV": 78.0, "shape": shape, "superseded_by": superseded,
                           "license": {"name": "CC BY-NC 4.0"}}}


def catalog():
    return {"samples": {"S1": {
        "volumes": {"20250101000001": vol("20250101000001", 2.4, [1000, 1000, 1000]),
                    "20250101000002": vol("20250101000002", 9.362, [500, 500, 500], pred=False),
                    "20250101000003": vol("20250101000003", 7.91, [500, 500, 500], superseded="20250101000002"),
                    "20230101000004": vol("20230101000004", 3.24, [500, 500, 500], root="https://data.aws.ash2txt.org",
                                          path="samples/S1/volumes/20230101000004-3.24um-0.2m-78keV-masked.zarr/")},
        "segments": {"g1": {"original_volume_id": "20250101000001",
                            "data": [{"type": "ink-detection"}, {"type": "ink-labels"}]}},
        "scans": {"orphan": {"long_id": "orphan-9um", "properties": {"pixel_size_um": 9.0}}}}}}


LISTED = {"S1": ["20250101000001-2.4um-0.2m-78keV-masked.zarr", "20250101000002-9.362um-0.2m-78keV-masked.zarr",
                 "20250101000003-7.91um-0.2m-78keV-masked.zarr", "20260101000009-4.8um-0.2m-80keV-masked.zarr"]}
SNAP = {"prizes": [{"id": "grand", "eligible": [{"volume": "20250101000002"}]}]}
ZATTRS = json.dumps({"multiscales": [{"datasets": [{"path": str(i), "coordinateTransformations": [
    {"type": "scale", "scale": [2 ** i] * 3}]} for i in range(6)]}]}).encode()


def no_net(url):
    if url.endswith(".zattrs"):
        return ZATTRS
    raise OSError("no network in tests")


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.doc = scancatalog.build(catalog(), LISTED, SNAP, live_html="<p>20250101000002</p>", checked="t")

    def test_rows_past_present_listing(self):
        rows = {r["volume"]: r for r in self.doc["volumes"]}
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows["20250101000003"]["era"], "superseded")
        self.assertEqual(rows["20260101000009"]["era"], "listing-only")
        self.assertEqual(rows["20260101000009"]["voxel_um"], 4.8)
        self.assertEqual(rows["20230101000004"]["access"], "outside-bucket")
        self.assertIsNone(rows["20230101000004"]["zarr_url"])
        self.assertTrue(rows["20250101000002"]["prize_eligible"])
        self.assertFalse(rows["20250101000001"]["prize_eligible"])
        self.assertEqual(rows["20250101000001"]["segments"], 1)
        self.assertEqual(rows["20250101000001"]["ink_labels"], 1)
        self.assertEqual(rows["20250101000001"]["license"], "CC BY-NC 4.0")
        self.assertEqual(len(self.doc["scans_without_volume"]), 1)
        for r in self.doc["volumes"]:
            self.assertNotIn("ash2txt", str(r["zarr_url"]))

    def test_forbidden_host(self):
        with self.assertRaises(scancatalog.ScanCatalogError):
            scancatalog.check_url("https://dl.ash2txt.org/full-scrolls/")
        with self.assertRaises(scancatalog.ScanCatalogError):
            scancatalog.http_get("https://dl.ash2txt.org/x")

    def test_listing_parse(self):
        def get(url):
            if "prefix=&" in url or url.endswith("prefix="):
                return LISTING_XML.format("<CommonPrefixes><Prefix>S1/</Prefix></CommonPrefixes>"
                                          "<CommonPrefixes><Prefix>_thumbnails/</Prefix></CommonPrefixes>").encode()
            return LISTING_XML.format("<CommonPrefixes><Prefix>S1/volumes/a.zarr/</Prefix></CommonPrefixes>").encode()
        self.assertEqual(scancatalog.listing(get), {"S1": ["a.zarr"]})

    def test_diff(self):
        old = json.loads(json.dumps(self.doc))
        old["volumes"] = [r for r in old["volumes"] if r["volume"] != "20260101000009"]
        old["volumes"][0]["normal_grids"] = 0
        d = scancatalog.diff(old, self.doc)
        self.assertEqual([r["volume"] for r in d["new"]], ["20260101000009"])
        self.assertEqual(len(d["changed"]), 1)


class BatchTest(unittest.TestCase):
    def setUp(self):
        self.doc = scancatalog.build(catalog(), LISTED, SNAP, live_html="20250101000002", checked="t")
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.rates = cloudcost.load_rates()

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, **kw):
        return autobatch.plan_all(self.state, catalog=self.doc, levels_get=no_net, rates=self.rates, **kw)

    def test_readers_by_resolution(self):
        self.assertEqual(autobatch.readers_for(2.4)[0], ["hecate-2.4um"])
        self.assertEqual(autobatch.readers_for(9.362)[0], ["ink_9um-seed42", "hecate-9.6um"])
        self.assertIn("hecate-9.6um", autobatch.readers_for(4.8)[0])
        self.assertEqual(autobatch.readers_for(None)[0], [])

    def test_plan_prices_and_statuses(self):
        plan = self.plan()
        by = {s["key"]: s for s in plan["scans"]}
        self.assertEqual(by["S1/20250101000003"]["skip"], "superseded by 20250101000002")
        self.assertIn("not in the open-data bucket", by["S1/20230101000004"]["block"])
        self.assertIn("not in metadata.json", by["S1/20260101000009"]["block"])
        fine, coarse = by["S1/20250101000001"], by["S1/20250101000002"]
        self.assertEqual(fine["levels"], ["0", "1", "2", "3", "4", "5"])
        self.assertEqual(fine["trace_level"], 2)
        self.assertTrue(coarse["needs_surface_prediction"])
        self.assertIn("surfacepred", coarse["hours"])
        for s in (fine, coarse):
            self.assertLess(s["usd"]["low"], s["usd"]["typical"])
            self.assertLess(s["usd"]["typical"], s["usd"]["high"])
        self.assertAlmostEqual(plan["total_usd"]["typical"], fine["usd"]["typical"] + coarse["usd"]["typical"], 2)
        self.assertEqual(plan["counts"], {"planned": 2, "skipped": 1, "blocked": 2})
        settings = json.loads((self.state / "scans/S1/20250101000001/settings.json").read_text())
        self.assertEqual(settings["purpose"], "benchmark")
        self.assertIn("f", settings["ink"]["variants"])
        self.assertIn("r", settings["ink"]["variants"])

    def test_idempotent_and_resumable(self):
        p1 = self.plan()
        rows1 = (self.state / "batch-ledger.csv").read_text()
        p2 = self.plan()
        self.assertEqual(p1["digest"], p2["digest"])
        self.assertEqual(rows1, (self.state / "batch-ledger.csv").read_text())
        with open(self.state / "batch-ledger.csv", newline="") as fh:
            self.assertEqual(len(list(csv.DictReader(fh))), 5)
        sp = self.state / "scans/S1/20250101000001/status.json"
        doc = json.loads(sp.read_text())
        doc["status"] = "done"
        sp.write_text(json.dumps(doc))
        self.plan()
        self.assertEqual(json.loads(sp.read_text())["status"], "done")

    def test_approve_needs_exact_digest(self):
        plan = self.plan()
        with self.assertRaises(autobatch.BatchError):
            autobatch.approve(self.state, "0" * 16)
        self.assertEqual(autobatch.approve(self.state, plan["digest"]), 2)
        st = {r["key"]: r["status"] for r in autobatch.status_table(self.state)}
        self.assertEqual(st["S1/20250101000001"], "approved")
        self.plan()
        st = {r["key"]: r["status"] for r in autobatch.status_table(self.state)}
        self.assertEqual(st["S1/20250101000001"], "approved")

    def test_title_refused(self):
        with self.assertRaises(autobatch.BatchError):
            autobatch.refuse_title({"ink": {"titlecheck": True}})
        with self.assertRaises(autobatch.BatchError):
            autobatch.refuse_title({"purpose": "title hunt"})

    def test_watch_queues_new(self):
        first = autobatch.watch(self.state, fetch=lambda: self.doc, levels_get=no_net, rates=self.rates)
        self.assertTrue(first["first_run"])
        self.assertEqual(len(first["queued"]), 5)
        again = autobatch.watch(self.state, fetch=lambda: self.doc, levels_get=no_net, rates=self.rates)
        self.assertEqual(again["queued"], [])
        cat = catalog()
        cat["samples"]["S1"]["volumes"]["20270101000010"] = vol("20270101000010", 2.4, [800, 800, 800])
        newer = scancatalog.build(cat, {"S1": LISTED["S1"] + ["20270101000010-2.4um-0.2m-78keV-masked.zarr"]},
                                  SNAP, live_html="", checked="t2")
        res = autobatch.watch(self.state, fetch=lambda: newer, levels_get=no_net, rates=self.rates)
        self.assertEqual([q["key"] for q in res["queued"]], ["S1/20270101000010"])
        self.assertEqual(res["queued"][0]["status"], "planned")
        self.assertGreater(res["queued"][0]["usd"]["typical"], 0)

    def test_no_modal_import(self):
        src = Path(autobatch.__file__).read_text() + Path(scancatalog.__file__).read_text()
        self.assertNotIn("import modal", src)
        self.assertNotIn("subprocess", src)


if __name__ == "__main__":
    unittest.main()
