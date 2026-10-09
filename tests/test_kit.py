import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from kit import cli, doctor, fetch, ledger, plan, prizes


class PrizeSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.snap = prizes.load()

    def test_snapshot_matches_prize_page_totals(self):
        self.assertEqual(self.snap["checked"], "2026-10-09")
        grand = prizes.find(self.snap, "grand-prize-2027")
        self.assertEqual(grand["total_usd"], 1_000_000)
        self.assertEqual(sum(grand["tiers_usd"].values()), 1_000_000)
        letters = prizes.find(self.snap, "first-letters-2027")
        self.assertEqual(letters["per_scroll_usd"] * letters["max_scrolls"], letters["total_usd"])

    def test_every_eligible_volume_has_a_resolved_zarr(self):
        for prize_id in ("grand-prize-2027", "first-letters-2027"):
            for entry in prizes.find(self.snap, prize_id)["eligible"]:
                self.assertTrue(entry["zarr"].startswith(entry["volume"] + "-"), entry)
                self.assertIn(entry["voxel_um"], (8.64, 9.362))

    def test_eligible_counts(self):
        self.assertEqual(len(prizes.find(self.snap, "grand-prize-2027")["eligible"]), 13)
        self.assertEqual(len(prizes.find(self.snap, "first-letters-2027")["eligible"]), 22)

    def test_pherc1447_left_first_letters_but_stays_grand_prize(self):
        self.assertIsNone(prizes.eligible_volume(self.snap, "PHerc1447"))
        self.assertEqual(prizes.eligible_volume(self.snap, "PHerc1447", "grand-prize-2027"), "20250521151220")

    def test_scroll_name_normalization(self):
        for name in ("PHerc0826", "pherc0826", "PHerc. 826", "PHERC 826"):
            self.assertEqual(prizes.eligible_volume(self.snap, name), "20250821151701")
        self.assertEqual(prizes.normalize_scroll("PHerc. 175A"), "PHERC0175A")

    def test_days_left(self):
        grand = prizes.find(self.snap, "grand-prize-2027")
        self.assertEqual(prizes.days_left(grand, date(2027, 6, 24)), 1)
        self.assertIn("deadline passed", prizes.format_table(self.snap, date(2027, 7, 1)))


class DoctorTest(unittest.TestCase):
    def test_parse_nvidia_smi(self):
        out = "NVIDIA GeForce RTX 3060, 12288\nNVIDIA A10, 23028\n"
        self.assertEqual(doctor.parse_nvidia_smi(out), [("NVIDIA GeForce RTX 3060", 12288), ("NVIDIA A10", 23028)])

    def test_gpu_thresholds(self):
        self.assertEqual(doctor.check_gpu([])[0], doctor.FAIL)
        self.assertEqual(doctor.check_gpu([("small", 8192)])[0], doctor.WARN)
        self.assertEqual(doctor.check_gpu([("ok", 12288)])[0], doctor.PASS)

    def test_apple_silicon_is_a_path_not_a_failure(self):
        self.assertTrue(doctor.is_apple_silicon("Darwin", "arm64"))
        self.assertFalse(doctor.is_apple_silicon("Linux", "arm64"))
        status, detail = doctor.check_gpu([], apple_silicon=True)
        self.assertEqual(status, doctor.WARN)
        self.assertIn("docs/mac.md", detail)

    def test_ram_rounding(self):
        self.assertEqual(doctor.check_ram(15.6)[0], doctor.PASS)
        self.assertEqual(doctor.check_ram(8.0)[0], doctor.WARN)
        self.assertIn("shared with the GPU", doctor.check_ram(32.0, apple_silicon=True)[1])
        self.assertEqual(doctor.check_ram(None)[0], doctor.WARN)

    def test_villa_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(doctor.check_villa(tmp)[0], doctor.FAIL)
            (Path(tmp) / "vesuvius").mkdir()
            (Path(tmp) / "volume-cartographer").mkdir()
            self.assertEqual(doctor.check_villa(tmp)[0], doctor.PASS)
        self.assertEqual(doctor.check_villa(None)[0], doctor.WARN)

    def test_report_overall(self):
        _, worst = doctor.format_report([("a", doctor.PASS, ""), ("b", doctor.WARN, "")])
        self.assertEqual(worst, doctor.WARN)


class AgentFilesTest(unittest.TestCase):
    """The machine-readable files agents rely on stay parseable and consistent."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_results_json_parses_and_rows_have_sources(self):
        data = json.loads((self.ROOT / "docs" / "results.json").read_text())
        self.assertEqual(data["schema"], 1)
        for row in data["results"]:
            self.assertIn(row["segment"], data["segments"])
            self.assertTrue(row["source"])
            for k in ("auc_as_stored", "auc_reversed"):
                if k in row:
                    self.assertTrue(0.0 <= row[k] <= 1.0)

    def test_agent_entry_points_link_to_existing_files(self):
        import re
        for name in ("AGENTS.md", "llms.txt"):
            text = (self.ROOT / name).read_text()
            for link in re.findall(r"\]\(([^)#]+)\)", text):
                if not link.startswith("http"):
                    self.assertTrue((self.ROOT / link).exists(), f"{name} links to missing {link}")


class PlanTest(unittest.TestCase):
    def test_plan_has_control_target_and_privacy_rule(self):
        text = plan.first_letters("PHerc. 826", batch=1)
        self.assertIn("PHerc0139", text)
        self.assertIn("20250821151701", text)
        self.assertIn("--batch-size 1", text)
        self.assertIn("--direction both", text)
        self.assertIn("tell nobody in public", text)
        self.assertIn("PHerc0826/volumes/20250821151701-9.362um-1.2m-113keV-masked.zarr/", text)
        self.assertNotIn("resampling", text)

    def test_plan_flags_resampling_for_864um_scans(self):
        text = plan.first_letters("PHerc0800")
        self.assertIn("--voxel-size 8.64 ", text)
        self.assertIn("resampling to 9.362 um", text)

    def test_mac_plan(self):
        text = plan.first_letters("PHerc0826", mac=True)
        self.assertIn("/Applications/VC3D.app/Contents/MacOS", text)
        self.assertIn("torch.backends.mps.is_available()", text)
        self.assertIn("pull/1865/head", text)
        self.assertIn("--batch-size 1", text)
        self.assertNotIn("cuda:', torch.cuda.is_available()", text)

    def test_plan_has_held_out_check_surface_qa_and_v8in(self):
        text = plan.first_letters("PHerc0826")
        self.assertIn("python -m kit fetch w045", text)
        self.assertIn("predictions/w045_seed42_reverse.tif", text)
        self.assertLess(text.index("w045"), text.index("# 2. Target"))
        self.assertIn("windcheck check work/pherc0826/surface.tifxyz", text)
        self.assertIn("YoussefMoNader/ink-8um-v8in", text)
        target = text[text.index("# 2. Target"):]
        self.assertIn("--voxel-unit micrometer --flip-normals", target)
        self.assertIn("v8in_reverse.tif --reverse\n", text)
        self.assertIn("--reverse --device mps", plan.first_letters("PHerc0826", mac=True))

    def test_plan_names_hecate_caveat_for_pherc0841(self):
        # PHerc0841 is held out from the readers this repository scores, but possibly not from
        # Hecate (docs/logs/2026-10-09-pherc0841-hecate.md).
        text = plan.first_letters("PHerc0826")
        step = text[text.index("# 1b."):text.index("python -m kit fetch w045")]
        self.assertIn("PHerc0841 is the held-out test for ink_9um, v8in, d9v2 and Reader v2", step)
        self.assertIn("Hecate", step)

    def test_fetch_aliases_point_at_9um_surface_volumes(self):
        from kit import fetch
        self.assertIn("w045_2026012619/surface-volumes/9.362um", fetch.ALIASES["w045"])
        self.assertEqual(fetch.ALIASES["w035"], fetch.W035_9UM)

    def test_plan_rejects_ineligible_scroll(self):
        with self.assertRaises(ValueError):
            plan.first_letters("PHerc1667")

    def test_cost_matches_published_run(self):
        # bnleft/first-light-pherc0211: about 6.5 GPU hours on an A10 at $1.10/h, "about $7".
        self.assertEqual(plan.cost(6.5, 1.10), 7.15)


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        ledger.init("t1", "PHerc0826", "does the 9um model show rows?", "rows in forward, not reverse", root=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_records_volume_and_hash(self):
        record = ledger.load("t1", self.root)
        self.assertEqual(record["first_letters_volume"], "20250821151701")
        self.assertEqual(ledger.check("t1", self.root), [])

    def test_readout_edit_is_detected(self):
        path = ledger.path_for("t1", self.root)
        record = json.loads(path.read_text())
        record["readout_rule"] = "anything bright"
        path.write_text(json.dumps(record))
        self.assertIn("readout rule was edited after the run was created", ledger.check("t1", self.root))

    def test_candidate_cannot_be_published_directly(self):
        ledger.set_status("t1", "running", root=self.root)
        ledger.set_status("t1", "candidate", root=self.root)
        with self.assertRaises(ledger.LedgerError):
            ledger.set_status("t1", "published", root=self.root)
        ledger.set_status("t1", "submitted", root=self.root)
        with self.assertRaises(ledger.LedgerError):
            ledger.set_status("t1", "published", root=self.root)
        ledger.set_status("t1", "published", announced=True, root=self.root)
        self.assertEqual(ledger.check("t1", self.root), [])

    def test_null_can_be_published(self):
        ledger.set_status("t1", "running", root=self.root)
        ledger.set_status("t1", "null", root=self.root)
        self.assertEqual(ledger.set_status("t1", "published", root=self.root)["status"], "published")

    def test_costs(self):
        ledger.add_cost("t1", 7.15, "A10 6.5h", root=self.root)
        record = ledger.add_cost("t1", 1.0, "egress", root=self.root)
        self.assertEqual(ledger.total_cost(record), 8.15)
        with self.assertRaises(ledger.LedgerError):
            ledger.add_cost("t1", -1, "refund", root=self.root)

    def test_requires_readout_and_safe_slug(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.init("t2", "PHerc0826", "q", "  ", root=self.root)
        with self.assertRaises(ledger.LedgerError):
            ledger.init("../escape", "PHerc0826", "q", "r", root=self.root)


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_prizes_and_plan(self):
        code, out = self.run_cli("prizes", "--today", "2026-10-06")
        self.assertEqual(code, 0)
        self.assertIn("262 days left", out)
        self.assertEqual(self.run_cli("plan", "PHerc1667")[0], 2)

    def test_run_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = self.run_cli("run", "--root", tmp, "init", "x", "--scroll", "PHerc0211",
                                   "--question", "q", "--readout", "r")
            self.assertEqual(code, 0)
            self.assertEqual(self.run_cli("run", "--root", tmp, "check", "x"), (0, "x: ok\n"))
            code, out = self.run_cli("run", "--root", tmp, "list")
            self.assertIn("planned", out)


if __name__ == "__main__":
    unittest.main()


class FetchTest(unittest.TestCase):
    PAGE1 = ("<ListBucketResult><Contents><Key>p/a.zarr/.zarray</Key><LastModified>x</LastModified>"
             "<Size>3</Size></Contents><Contents><Key>p/a.zarr/0/0</Key><Size>5</Size></Contents>"
             "<NextContinuationToken>tok/1</NextContinuationToken></ListBucketResult>")
    PAGE2 = "<ListBucketResult><Contents><Key>p/a.zarr/0/1</Key><Size>2</Size></Contents></ListBucketResult>"
    BODIES = {"p/a.zarr/.zarray": b"abc", "p/a.zarr/0/0": b"12345", "p/a.zarr/0/1": b"xy"}

    def opener(self, url, timeout=None):
        self.calls.append(url)
        if "list-type=2" in url:
            body = self.PAGE2 if "continuation-token=tok%2F1" in url else self.PAGE1
            return io.BytesIO(body.encode())
        key = url.split(".com/", 1)[1].replace("%2F", "/")
        return io.BytesIO(self.BODIES[key])

    def test_paged_listing_download_and_resume(self):
        self.calls = []
        with tempfile.TemporaryDirectory() as tmp:
            objects, fetched, total = fetch.fetch_prefix("p/a.zarr", tmp, workers=2, opener=self.opener,
                                                         base="https://bucket.example.com")
            self.assertEqual((objects, fetched, total), (3, 10, 10))
            self.assertEqual((Path(tmp) / "0" / "0").read_bytes(), b"12345")
            again = fetch.fetch_prefix("p/a.zarr", tmp, opener=self.opener, base="https://bucket.example.com")
            self.assertEqual(again[1], 0)

    def test_short_read_is_an_error(self):
        self.calls = []
        self.BODIES = dict(self.BODIES, **{"p/a.zarr/0/0": b"123"})
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(fetch.FetchError):
            fetch.fetch_prefix("p/a.zarr", tmp, opener=self.opener, base="https://bucket.example.com")

    def test_unsafe_keys_refused(self):
        with self.assertRaises(fetch.FetchError):
            fetch.local_path("/tmp/x", "p/", "p/../../etc/passwd")
