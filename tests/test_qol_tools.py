"""Tests for kit find, cite, centerline, the fetch plan, the new doctor checks, prclock and prtext, and the grouped
help, all offline: every network read goes through a fake that serves fixed bytes."""

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from kit import centerline, cli, doctor, fetch, find, villapr
from kit.verify import VerifyError

LINE = {"control_points": [{"x": 10, "y": 20, "z": 100}, {"x": 11, "y": 21, "z": 900}],
        "metadata": {"voxelsize_um": 9.362}}
LINE_BYTES = json.dumps(LINE).encode()
META = {"samples": {"PHerc0001": {
    "sample": {"id": "PHerc0001"},
    "volumes": {"20250101000000": {"long_id": "20250101000000-9.362um-1.2m-113keV-masked.zarr",
                                   "properties": {"pixel_size_um": 9.362, "shape": [3000, 2000, 2100],
                                                  "license": {"name": "CC BY-NC 4.0",
                                                              "url": "https://creativecommons.org/licenses/by-nc/4.0/"},
                                                  "superseded_by": None}}},
    "segments": {"a": {"original_volume_id": "20250101000000"}, "b": {"original_volume_id": "20250101000000"}}}}}
INDEX = {"files": [{"scroll": "PHerc0001", "scan": "20250101000000", "file": "lines/PHerc0001/a_umbilicus.json",
                    "source": "drobkov", "kind": "person", "credit": "Someone", "licence": "MIT", "points": 2,
                    "volume": "20250101000000-9.362um-1.2m-113keV-masked.zarr",
                    "sha256": hashlib.sha256(LINE_BYTES).hexdigest()}]}


def listing(prefixes=(), keys=()):
    p = "".join(f"<CommonPrefixes><Prefix>{x}</Prefix></CommonPrefixes>" for x in prefixes)
    k = "".join(f"<Contents><Key>{x}</Key><Size>{s}</Size></Contents>" for x, s in keys)
    return f"<ListBucketResult>{p}{k}</ListBucketResult>".encode()


def fake_get(url, timeout=60):
    if url == find.METADATA:
        return json.dumps(META).encode()
    if url == find.CENTERLINES_INDEX:
        return json.dumps(INDEX).encode()
    if url.endswith("a_umbilicus.json"):
        return LINE_BYTES
    if "/api/datasets" in url:
        return json.dumps([{"id": "someone/pherc0001-thing", "private": False},
                           {"id": "x/secret", "private": True}]).encode()
    if "/api/" in url:
        return b"[]"
    if "prefix=PHerc0001%2Frepresentations%2Fpredictions%2Flasagna%2F" in url:
        return listing(["PHerc0001/representations/predictions/lasagna/run1/"])
    if "prefix=PHerc0001%2Frepresentations%2Fpredictions%2F" in url:
        return listing(["PHerc0001/representations/predictions/lasagna/"])
    if "prefix=PHerc0001%2Frepresentations%2Fumbilicus%2F" in url:
        return listing(keys=[("PHerc0001/representations/umbilicus/20250101000000-umbilicus-1.json", 50)])
    if "prefix=PHerc0001%2Frepresentations%2F" in url:
        return listing(["PHerc0001/representations/predictions/", "PHerc0001/representations/umbilicus/"])
    if url.endswith("20250101000000-umbilicus-1.json"):
        return LINE_BYTES
    return listing()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestFind(unittest.TestCase):
    def test_find_lists_everything(self):
        r = find.find("pherc0001", get=fake_get)
        self.assertEqual(r["scroll"], "PHerc0001")
        self.assertEqual(r["segments"]["count"], 2)
        self.assertEqual(r["representations"]["predictions/lasagna"], ["run1"])
        self.assertEqual(r["representations"]["umbilicus"], ["20250101000000-umbilicus-1.json"])
        self.assertEqual([h["id"] for h in r["hub"]], ["someone/pherc0001-thing"])
        self.assertEqual(len(r["centerlines"]), 1)
        self.assertIn("predictions/lasagna: 1", find.format_find(r))

    def test_unknown_and_bad_ids(self):
        with self.assertRaises(VerifyError):
            find.find("PHerc9999", get=fake_get)
        with self.assertRaises(VerifyError):
            find.check_id("../etc")

    def test_cite(self):
        r = find.cite("PHerc0001", get=fake_get, with_centerlines=True)
        text = find.format_cite(r)
        self.assertIn("Vesuvius Challenge open data, CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/)", text)
        self.assertIn("center line (drobkov): Someone, MIT", text)
        with self.assertRaises(VerifyError):
            find.cite("PHerc0001", get=fake_get, volume="20990101000000")


class TestCenterline(unittest.TestCase):
    def test_list_order_and_get(self):
        found = centerline.lines("PHerc0001", get=fake_get)
        self.assertEqual([l["source"] for l in found], ["drobkov", "bucket-file"])
        with tempfile.TemporaryDirectory() as d:
            r = centerline.get_line("PHerc0001", folder=d, get=fake_get)
            data = json.loads(Path(d, "umbilicus.json").read_text())
            self.assertTrue(r["sha256_checked"])
            self.assertTrue(r["stamped_grid"])
            self.assertEqual((data["metadata"]["volume_slices"], data["metadata"]["volume_height"],
                              data["metadata"]["volume_width"]), (3000, 2000, 2100))
            with self.assertRaises(VerifyError):            # never overwrites without --force
                centerline.get_line("PHerc0001", folder=d, get=fake_get)
            Path(d, "estimated_umbilicus.json").write_text("{}")
            with self.assertRaises(VerifyError):            # VC3D refuses two files: so do we, even with force
                centerline.get_line("PHerc0001", folder=d, get=fake_get, force=True)

    def test_polished_finder_line_comes_before_the_original(self):
        found = [{"source": s, "kind": k} for s, k in
                 (("finder", "model"), ("finder-polished", "model"), ("bucket-file", "bucket"), ("tauil", "person"))]
        self.assertEqual([l["source"] for l in centerline.order(found)],
                         ["tauil", "bucket-file", "finder-polished", "finder"])
        self.assertEqual(centerline.pick(centerline.order(found))["source"], "tauil")
        self.assertEqual(centerline.pick(centerline.order(found[:2]))["source"], "finder-polished")
        # a line the dataset marks superseded_by a newer version comes after it, whatever the source names
        later = [{"source": "finder-polished", "kind": "model", "superseded_by": "lines/x_finder-polished-2.json"},
                 {"source": "finder-polished-2", "kind": "model"}]
        self.assertEqual(centerline.pick(centerline.order(later))["source"], "finder-polished-2")

    def test_hash_mismatch_refused(self):
        def bad(url, timeout=60):
            return LINE_BYTES + b" " if url.endswith("a_umbilicus.json") else fake_get(url)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(VerifyError):
                centerline.get_line("PHerc0001", folder=d, get=bad)
            self.assertFalse(Path(d, "umbilicus.json").exists())

    def test_no_stamp_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            centerline.get_line("PHerc0001", out=f"{d}/u.json", get=fake_get, do_stamp=False)
            self.assertEqual(Path(d, "u.json").read_bytes(), LINE_BYTES)


class TestFetchPlan(unittest.TestCase):
    def test_plan_counts_missing_and_fit(self):
        page = listing(keys=[("p/a.bin", 10), ("p/b.bin", 20)]).decode()

        class R:
            def read(self):
                return page.encode()

        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.bin").write_bytes(b"x" * 10)
            pl = fetch.plan("p", d, opener=lambda url, timeout=60: R())
            self.assertEqual((pl["objects"], pl["total_bytes"], pl["missing_bytes"]), (2, 30, 20))
            with mock.patch.object(fetch.shutil, "disk_usage", return_value=mock.Mock(free=100)):
                self.assertFalse(fetch.plan("p", d, opener=lambda url, timeout=60: R())["fits"])
        self.assertEqual(fetch.human(1_500_000_000), "1.5 GB")


class TestDoctor(unittest.TestCase):
    def test_rosetta(self):
        self.assertIsNone(doctor.check_rosetta("Linux", "x86_64"))
        sc = {"hw.optional.arm64": "1", "sysctl.proc_translated": "1"}.get
        self.assertEqual(doctor.check_rosetta("Darwin", "x86_64", read=sc)[0], doctor.FAIL)
        native = {"hw.optional.arm64": "1", "sysctl.proc_translated": "0"}.get
        self.assertEqual(doctor.check_rosetta("Darwin", "arm64", read=native, torch_info=lambda: (True, True))[0],
                         doctor.PASS)
        self.assertEqual(doctor.check_rosetta("Darwin", "arm64", read=native, torch_info=lambda: (False, False))[0],
                         doctor.WARN)
        self.assertEqual(doctor.check_rosetta("Darwin", "x86_64", read={"hw.optional.arm64": "0"}.get)[0], doctor.PASS)

    def test_threads(self):
        self.assertEqual(doctor.check_threads(visible=8, quota=None, env={})[0], doctor.PASS)
        st, detail = doctor.check_threads(visible=8, quota=2.0, env={})
        self.assertEqual(st, doctor.WARN)
        self.assertIn("NUMBA_NUM_THREADS=2", detail)
        env = {k: "2" for k in doctor.THREAD_VARS}
        self.assertEqual(doctor.check_threads(visible=8, quota=2.0, env=env)[0], doctor.PASS)

    def test_cpu_quota_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "cpu" / "job").mkdir(parents=True)
            (root / "cpu" / "job" / "cpu.cfs_quota_us").write_text("150000")
            (root / "cpu" / "job" / "cpu.cfs_period_us").write_text("100000")
            proc = root / "cgroup"
            proc.write_text("4:cpu,cpuacct:/job\n")
            self.assertEqual(doctor.cpu_quota(root, proc), 1.5)
            (root / "cpu.max").write_text("max 100000")
            proc.write_text("0::/\n")
            self.assertIsNone(doctor.cpu_quota(root, proc))
            (root / "cpu.max").write_text("200000 100000")
            self.assertEqual(doctor.cpu_quota(root, proc), 2.0)

    def test_disk_speed_runs_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            st, detail = doctor.check_disk_speed(d, nbytes=4 << 20)
            self.assertIn("MB/s", detail)
            self.assertEqual(os.listdir(d), [])
            slow = iter([0.0, 0.01, 0.0, 10.0])
            st, detail = doctor.check_disk_speed(d, nbytes=4 << 20, clock=lambda: next(slow))
            self.assertEqual(st, doctor.WARN)


def pr(n, created, updated, labels=(), draft=False):
    return {"number": n, "title": f"PR {n}", "html_url": f"https://github.com/ScrollPrize/villa/pull/{n}",
            "created_at": created, "updated_at": updated, "labels": [{"name": l} for l in labels], "draft": draft}


class TestVillaPr(unittest.TestCase):
    NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

    def test_idle_rule_and_next_run(self):
        r = villapr.clock(pr(1, "2026-10-20T00:00:00Z", "2026-10-20T15:00:00Z"), self.NOW)
        self.assertEqual(r["reason"], "14 days without activity")
        # 14 days after 20 Oct 15:00 UTC is 3 Nov 15:00 UTC = 07:00 Pacific; the next run is 4 Nov 00:00 PST
        self.assertEqual(r["closes_at"], "2026-11-04T08:00:00Z")

    def test_age_rule_wins_when_sooner(self):
        r = villapr.clock(pr(2, "2026-09-30T00:00:00Z", "2026-10-23T00:00:00Z"), self.NOW)
        self.assertEqual(r["reason"], "28 days open")
        self.assertLess(r["days_left"], 5)

    def test_keep_open(self):
        r = villapr.clock(pr(3, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", labels=("keep-open",)), self.NOW)
        self.assertIsNone(r["closes_at"])

    def test_search_paginates_and_checks_login(self):
        pages = [{"total_count": 101, "items": [pr(i, "2026-10-20T00:00:00Z", "2026-10-21T00:00:00Z")
                                                 for i in range(100)]},
                 {"total_count": 101, "items": [pr(100, "2026-10-20T00:00:00Z", "2026-10-21T00:00:00Z")]}]

        class R:
            def __init__(self, d):
                self.d = d

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self.d).encode()

        it = iter(pages)
        r = villapr.prclock("someone", now=self.NOW, opener=lambda req, timeout=30: R(next(it)))
        self.assertEqual(len(r["prs"]), 101)
        with self.assertRaises(VerifyError):
            villapr.search("bad login!")

    def test_prtext(self):
        good = ("**In one sentence:** VC3D can now save ink labels.\n\n**One real example:** Starting with PHerc0139 "
                "w035, I painted labels and saved them.\n\n**Before:** labels were lost.\n\n**After this PR:** they "
                "are kept.\n\n**Proof:** ![before](a.png) ![after](b.png)\n\n**Why / where this is useful:** I was "
                "trying to label ink while tracing.\n\n- [x] I personally verified that the example and proof above "
                "were produced by this PR on the stated data.\n\n## Details\n\nTested on main.\n")
        r = villapr.prtext(good, title="Keep ink labels when VC3D saves a segment")
        self.assertTrue(r["ok"], r["problems"])
        bad = villapr.prtext(good.replace("[x]", "[ ]").replace("![after](b.png)", "") + "\u2014", title="Fix")
        self.assertFalse(bad["ok"])
        self.assertTrue(any("not ticked" in p for p in bad["problems"]))
        self.assertTrue(any("long dash" in p for p in bad["problems"]))
        self.assertTrue(any("too vague" in p for p in bad["problems"]))
        issue = villapr.prtext("**In one sentence:** x", kind="issue")
        self.assertTrue(any("I was trying to" in p for p in issue["problems"]))


class TestHelp(unittest.TestCase):
    def test_every_command_grouped(self):
        parser = cli._parser()
        sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
        grouped = {n for _, names in cli.GROUPS for n in names}
        self.assertEqual(set(sub.choices) - grouped, set())
        self.assertNotIn("Other:", parser.format_help())

    def test_did_you_mean(self):
        code, _, err = run(["tifxzy"])
        self.assertEqual(code, 2)
        self.assertIn("Did you mean: tifxyz?", err)

    def test_help_command_shows_quick_start(self):
        code, out, _ = run(["help", "auc"])
        self.assertEqual(code, 0)
        self.assertIn("Worked example", out)
        self.assertIn("docs/tools/auc.md", out)


if __name__ == "__main__":
    unittest.main()
