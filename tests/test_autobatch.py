"""kit/scancatalog.py and kit/autobatch.py on a synthetic catalog: no network, no Modal."""

import csv
import json
import shlex
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

    def test_unsafe_ids_rejected_and_nothing_written_outside(self):
        for good in ("PHerc0172", "20250101000001-2.4um-0.2m-78keV-masked.zarr", "a.b_c-d"):
            self.assertTrue(scancatalog.safe_id(good), good)
        for bad in ("..", ".", "../x", "a/b", "", "a b", "a;b", "-x", None, 5, "x" * 200):
            self.assertFalse(scancatalog.safe_id(bad), bad)
        cat = catalog()
        cat["samples"]["S1"]["volumes"]["../../../ESC1"] = vol("20250101000007", 2.4, [100, 100, 100])
        cat["samples"]["../ESC2"] = {"volumes": {"20250101000008": vol("20250101000008", 2.4, [100, 100, 100])}}
        listed = {"S1": LISTED["S1"] + ["../../../../ESC3-7.91um.zarr"], "../ESC4": ["v.zarr"]}
        doc = scancatalog.build(cat, listed, SNAP, live_html="", checked="t")
        self.assertEqual(len(doc["volumes"]), 5)
        self.assertEqual(len(doc["rejected"]), 4)
        state = self.state / "a" / "b" / "state"
        plan = autobatch.plan_all(state, catalog=doc, levels_get=no_net, rates=self.rates)
        self.assertEqual(len(plan["scans"]), 5)
        # a crafted catalog.json that skips build() is refused row by row, not written outside the state folder
        doc["volumes"].append({**doc["volumes"][0], "volume": "../../../ESC5"})
        plan = autobatch.plan_all(state, catalog=doc, levels_get=no_net, rates=self.rates)
        self.assertEqual(len(plan["scans"]), 5)
        self.assertEqual(len(plan["rejected"]), 1)
        outside = [p for p in self.state.rglob("*") if "ESC" in str(p)]
        self.assertEqual(outside, [])
        with self.assertRaises(autobatch.BatchError):
            autobatch._status_path(state, {"sample": "S1", "volume": ".."})

    def test_launch_command_quotes_ids(self):
        cmd = autobatch.launch_command({"sample": "S1", "volume": "v$(touch x)"})
        self.assertEqual(shlex.split(cmd)[3], "S1")
        self.assertIn("'@work/autobatch/scans/S1/v$(touch x)/settings.json'", cmd)

    def test_duplicate_keys_get_unique_ids(self):
        listed = {"S1": LISTED["S1"] + ["20250101000001.zarr"]}
        doc = scancatalog.build(catalog(), listed, SNAP, live_html="", checked="t")
        keys = [scancatalog.key(r) for r in doc["volumes"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("S1/20250101000001.zarr", keys)
        plan = autobatch.plan_all(self.state, catalog=doc, levels_get=no_net, rates=self.rates)
        self.assertEqual(len(plan["scans"]), 6)
        doc["volumes"].append(dict(doc["volumes"][0]))   # a crafted repeat: the first row wins
        plan = autobatch.plan_all(self.state, catalog=doc, levels_get=no_net, rates=self.rates)
        self.assertEqual(len(plan["scans"]), 6)
        self.assertIn("duplicate key", plan["rejected"][0]["reason"])

    def test_bad_rows_block_and_title_in_id_does_not_stop_the_batch(self):
        cat = catalog()
        bad = {"20250101000011": [100, 100], "20250101000012": ["a", "b", "c"], "20250101000013": [-1, 1000, 1000],
               "20250101000014": [0, 10, 10]}
        for vid, shape in bad.items():
            cat["samples"]["S1"]["volumes"][vid] = vol(vid, 2.4, shape)
        cat["samples"]["S1"]["volumes"]["20250101000015-subtitle"] = vol("20250101000015-subtitle", 2.4, [10, 10, 10])
        doc = scancatalog.build(cat, LISTED, SNAP, live_html="", checked="t")
        plan = autobatch.plan_all(self.state, catalog=doc, levels_get=no_net, rates=self.rates)
        by = {s["key"]: s for s in plan["scans"]}
        for vid in bad:
            self.assertIn("is not three positive integers", by["S1/" + vid]["block"])
            self.assertEqual(by["S1/" + vid]["usd"]["high"], 0.0)
        self.assertIsNone(by["S1/20250101000015-subtitle"]["block"])
        self.assertTrue((self.state / "plan.json").is_file())
        with self.assertRaises(autobatch.BatchError):
            autobatch.refuse_title({"ink": {"titlecheck": True}})

    def test_watch_survives_a_malformed_row(self):
        doc = json.loads(json.dumps(self.doc))
        doc["volumes"].append({"sample": "S1", "volume": "20250101000020", "in_bucket": True, "in_metadata": True,
                               "voxel_um": "x", "shape_zyx": {"z": 1}})
        doc["volumes"].append({"sample": "S1", "volume": "../../../ESC6", "in_bucket": False})
        res = autobatch.watch(self.state, fetch=lambda: doc, levels_get=no_net, rates=self.rates)
        self.assertEqual(len(res["queued"]), 6)
        self.assertEqual([q["key"] for q in res["rejected"]], ["S1/../../../ESC6"])
        self.assertTrue((self.state / "catalog.json").is_file())
        again = autobatch.watch(self.state, fetch=lambda: doc, levels_get=no_net, rates=self.rates)
        self.assertEqual(again["queued"], [])

    def test_watch_retries_a_row_that_failed_and_flags_it(self):
        """A row whose planning failed is not saved as seen: the next run plans it again, and the run that
        failed exits 3 with --exit-code like one that queued something."""
        import contextlib
        import io
        from unittest import mock
        from kit import cli
        autobatch.watch(self.state, fetch=lambda: self.doc, levels_get=no_net, rates=self.rates)
        cat = catalog()
        cat["samples"]["S1"]["volumes"]["20270101000011"] = vol("20270101000011", 2.4, [800, 800, 800])
        newer = scancatalog.build(cat, {"S1": LISTED["S1"] + ["20270101000011-2.4um-0.2m-78keV-masked.zarr"]},
                                  SNAP, live_html="", checked="t2")

        prepare = autobatch._prepare

        def broken(r, *a):
            if r["volume"] == "20270101000011":
                raise ValueError("Expecting value: an empty zattrs cache")
            return prepare(r, *a)
        with mock.patch.object(autobatch, "_prepare", side_effect=broken):
            failed = autobatch.watch(self.state, fetch=lambda: newer, levels_get=no_net, rates=self.rates)
        self.assertEqual(failed["queued"], [])
        self.assertEqual([q["key"] for q in failed["rejected"]], ["S1/20270101000011"])
        self.assertEqual(failed["failed"], 1)
        fixed = autobatch.watch(self.state, fetch=lambda: newer, levels_get=no_net, rates=self.rates)
        self.assertEqual([q["key"] for q in fixed["queued"]], ["S1/20270101000011"])
        out = io.StringIO()
        with mock.patch.object(autobatch, "watch", return_value=failed), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["run", "watch", "--state", str(self.state), "--exit-code"]), 3)
        self.assertIn("rejected S1/20270101000011", out.getvalue())

    def test_watch_prints_names_the_catalog_left_out(self):
        """build() leaves out an unsafe bucket name; watch gives it a key, so the plain-text output prints it
        instead of failing with KeyError."""
        import contextlib
        import io
        from unittest import mock
        from kit import cli
        listed = {"S1": LISTED["S1"] + ["bad name.zarr"]}
        doc = scancatalog.build(catalog(), listed, SNAP, live_html="", checked="t")
        self.assertEqual(len(doc["rejected"]), 1)
        res = autobatch.watch(self.state, fetch=lambda: doc, levels_get=no_net, rates=self.rates)
        self.assertEqual(res["failed"], 0)
        self.assertTrue(all("key" in q for q in res["rejected"]))
        out = io.StringIO()
        with mock.patch.object(autobatch, "watch", return_value=res), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["run", "watch", "--state", str(self.state), "--exit-code"]), 3)
        self.assertIn("rejected S1/", out.getvalue())

    def test_approve_checks_plan_contents_settings_and_cost(self):
        plan = self.plan()
        pj = self.state / "plan.json"
        edited = json.loads(pj.read_text())
        edited["total_usd"] = {"low": 0.01, "typical": 0.01, "high": 0.01}
        pj.write_text(json.dumps(edited))
        with self.assertRaisesRegex(autobatch.BatchError, "edited after it was priced"):
            autobatch.approve(self.state, plan["digest"])
        self.plan()
        sp = self.state / "scans/S1/20250101000001/settings.json"
        sp.write_text(json.dumps({"purpose": "smoke", "volume": "x"}))
        with self.assertRaisesRegex(autobatch.BatchError, "settings.json"):
            autobatch.approve(self.state, plan["digest"])
        self.assertNotIn("approved", {r["status"] for r in autobatch.status_table(self.state)})
        sp.unlink()
        self.plan()
        self.assertEqual(autobatch.approve(self.state, plan["digest"]), 2)
        dear = {**self.rates, "cpu_usd_per_core_s": self.rates["cpu_usd_per_core_s"] * 10,
                "mem_usd_per_gib_s": self.rates["mem_usd_per_gib_s"] * 10}   # prices rise 10x; configs unchanged
        p2 = autobatch.plan_all(self.state, catalog=self.doc, levels_get=no_net, rates=dear)
        self.assertNotEqual(p2["digest"], plan["digest"])
        st = {r["key"]: r["status"] for r in autobatch.status_table(self.state)}
        self.assertEqual(st["S1/20250101000001"], "planned")

    def test_failed_zattrs_read_is_retried_not_priced_at_level_0(self):
        def flaky(url):
            raise OSError("connection reset")
        plan = autobatch.plan_all(self.state, catalog=self.doc, levels_get=flaky, rates=self.rates)
        keys = {s["key"] for s in plan["scans"]}
        self.assertNotIn("S1/20250101000001", keys)
        reasons = {r["key"]: r["reason"] for r in plan["rejected"]}
        self.assertIn(".zattrs", reasons["S1/20250101000001"])
        first = autobatch.watch(self.state, fetch=lambda: self.doc, levels_get=flaky, rates=self.rates)
        self.assertIn("S1/20250101000001", {r["key"] for r in first["rejected"]})
        again = autobatch.watch(self.state, fetch=lambda: self.doc, levels_get=no_net, rates=self.rates)
        fine = [q for q in again["queued"] if q["key"] == "S1/20250101000001"]
        self.assertEqual(len(fine), 1)
        cfg = autobatch.plan_all(self.state, catalog=self.doc, levels_get=no_net, rates=self.rates)
        self.assertEqual({s["key"]: s["levels"] for s in cfg["scans"]}["S1/20250101000001"],
                         ["0", "1", "2", "3", "4", "5"])

    def test_et_times_are_eastern_on_a_utc_machine(self):
        from datetime import datetime, timezone
        from unittest import mock

        class UtcMachine(datetime):
            @classmethod
            def now(cls, tz=None):
                at = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
                return at.astimezone(tz) if tz else at.replace(tzinfo=None)   # local clock reads UTC
        with mock.patch.object(autobatch, "datetime", UtcMachine):
            self.assertEqual(autobatch._now_et(), "2026-10-16 08:00 ET")   # EDT, UTC-4

    def test_readers_comment_does_not_call_w043_held_out(self):
        # w043 is ink_9um training data (docs/logs/2026-10-08-w045-not-held-out.md).
        comments = [l for l in Path(autobatch.__file__).read_text().splitlines() if l.lstrip().startswith("#")]
        self.assertFalse([l for l in comments if "held-out" in l and ("w043" in l or "segment" in l)])

    def test_no_modal_import(self):
        src = Path(autobatch.__file__).read_text() + Path(scancatalog.__file__).read_text()
        self.assertNotIn("import modal", src)
        self.assertNotIn("subprocess", src)


if __name__ == "__main__":
    unittest.main()
