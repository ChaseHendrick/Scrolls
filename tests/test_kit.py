import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from kit import cli, doctor, fetch, ledger, plan, prizes


class PrizeSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.snap = prizes.load()

    def test_snapshot_matches_prize_page_totals(self):
        self.assertEqual(self.snap["checked"], "2026-10-11")
        grand = prizes.find(self.snap, "grand-prize-2027")
        self.assertEqual(grand["total_usd"], 1_000_000)
        self.assertEqual(grand["tiers_usd"], {"1st": 800_000, "2nd": 100_000, "3rd": 50_000, "4th": 50_000})
        self.assertEqual(sum(grand["tiers_usd"].values()), 1_000_000)
        self.assertTrue(grand["deadline"].startswith("2027-06-25T23:59:00"))
        letters = prizes.find(self.snap, "first-letters-2027")
        self.assertEqual(letters["per_scroll_usd"], 50_000)
        self.assertEqual(letters["max_scrolls"], 9)
        self.assertEqual(letters["total_usd"], 450_000)
        self.assertEqual(letters["awarded_count"], 1)
        self.assertEqual(letters["per_scroll_usd"] * letters["max_scrolls"], letters["total_usd"])
        self.assertEqual(letters["awarded"][0]["scroll"], "PHerc0343")
        self.assertEqual(letters["awarded"][0]["winner"], "Erwin Nieuwlaar")
        self.assertEqual(letters["awarded"][0]["date"], "2026-10-08")
        self.assertEqual(letters["awarded"][0]["usd"], 50_000)
        paris = prizes.find(self.snap, "first-title")
        self.assertEqual(paris["total_usd"], 50_000)
        self.assertTrue(paris["deadline"].startswith("2027-06-25T23:59:00"))
        progress = prizes.find(self.snap, "progress-prizes")
        self.assertEqual(progress["monthly_best_usd"], 20_000)
        self.assertEqual(progress["typical_tiers_usd"][0], 20_000)
        self.assertEqual(progress["typical_tiers_usd"][-1], 250)
        self.assertTrue(progress["deadline"].startswith("2026-10-31T23:59:00"))

    def test_every_eligible_volume_has_a_resolved_zarr(self):
        for prize_id in ("grand-prize-2027", "first-letters-2027"):
            for entry in prizes.find(self.snap, prize_id)["eligible"]:
                self.assertTrue(entry["zarr"].startswith(entry["volume"] + "-"), entry)
                self.assertIn(entry["voxel_um"], (8.64, 9.362))

    def test_eligible_counts(self):
        self.assertEqual(len(prizes.find(self.snap, "grand-prize-2027")["eligible"]), 13)
        letters = prizes.find(self.snap, "first-letters-2027")["eligible"]
        self.assertEqual(len(letters), 21)
        self.assertNotIn("PHerc0343", [entry["scroll"] for entry in letters])
        self.assertIsNone(prizes.eligible_volume(self.snap, "PHerc0343"))

    def test_october_6_snapshot_still_has_22_including_pherc0343(self):
        old = prizes.load(prizes.DATA_DIR / "prizes-2026-10-06.json")
        self.assertEqual(old["checked"], "2026-10-06")
        letters = prizes.find(old, "first-letters-2027")
        self.assertEqual(len(letters["eligible"]), 22)
        self.assertEqual(letters["max_scrolls"], 10)
        self.assertEqual(letters["total_usd"], 500_000)
        self.assertEqual(letters["per_scroll_usd"] * letters["max_scrolls"], letters["total_usd"])
        self.assertEqual(prizes.eligible_volume(old, "PHerc0343"), "20250521140437")
        self.assertIn("PHerc0343", [entry["scroll"] for entry in letters["eligible"]])
        grand_old = [entry["scroll"] for entry in prizes.find(old, "grand-prize-2027")["eligible"]]
        grand_new = [entry["scroll"] for entry in prizes.find(self.snap, "grand-prize-2027")["eligible"]]
        self.assertEqual(grand_old, grand_new)
        self.assertEqual(len(grand_new), 13)
        self.assertIn("PHerc1447", grand_new)

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
        # PHerc0841 is held out from the readers this repository scores, but not from Hecate
        # (docs/logs/2026-10-16-reader-exposure.md).
        text = plan.first_letters("PHerc0826")
        step = text[text.index("# 1b."):text.index("python -m kit fetch w045")]
        self.assertIn("PHerc0841 is the held-out test for ink_9um, v8in, v8in-1447, d9v2 and\n#     Reader v2", step)
        self.assertIn("Hecate", step)

    def test_fetch_aliases_point_at_9um_surface_volumes(self):
        from kit import fetch
        self.assertIn("w045_2026012619/surface-volumes/9.362um", fetch.ALIASES["w045"])
        self.assertEqual(fetch.ALIASES["w035"], fetch.W035_9UM)

    def test_plan_rejects_ineligible_scroll(self):
        with self.assertRaises(ValueError):
            plan.first_letters("PHerc1667")
        with self.assertRaises(ValueError):
            plan.first_letters("PHerc0343")

    def test_plan_names_the_award_when_it_rejects_an_awarded_scroll(self):
        # The 2026-10-11 snapshot records PHerc0343's award in First Letters' "awarded" list.
        with self.assertRaisesRegex(ValueError, r"awarded on 2026-10-08 \(https://scrollprize\.substack\.com/"):
            plan.first_letters("PHerc. 343")
        # A scroll that was never eligible gets no award sentence, so the check can fail.
        with self.assertRaises(ValueError) as ctx:
            plan.first_letters("PHerc1667")
        self.assertNotIn("awarded", str(ctx.exception))

    def test_plan_award_sentence_survives_an_entry_without_sources(self):
        # A snapshot entry missing its date or sources still gives the clean refusal, not a KeyError.
        import copy
        from kit import prizes
        snapshot = copy.deepcopy(prizes.load())
        letters = prizes.find(snapshot, "first-letters-2027")
        letters["awarded"] = [{"scroll": "PHerc0343"}]
        with self.assertRaisesRegex(ValueError, r"awarded on an unrecorded date \(no source recorded\)"):
            plan.first_letters("PHerc0343", snapshot=snapshot)

    def test_cost_matches_published_run(self):
        # bnleft/first-light-pherc0211: about 6.5 GPU hours on an A10 at $1.10/h, "about $7".
        self.assertEqual(plan.cost(6.5, 1.10), 7.15)

    def test_render_commands_pass_the_bucket_url_as_volume(self):
        # villa e2254eb's vc_render_tifxyz exits with an error for a local --volume next to a different --remote-url.
        for text in (plan.first_letters("PHerc0826"), plan.first_letters("PHerc0826", mac=True),
                     plan.spiral_chain("PHerc0826")):
            self.assertNotIn("--remote-url s3", text)
            self.assertNotIn("--volume volume-cache/", text)
        self.assertIn("--volume s3://vesuvius-challenge-open-data/PHerc0826/volumes/"
                      "20250821151701-9.362um-1.2m-113keV-masked.zarr/", plan.first_letters("PHerc0826"))


class SpiralChainTest(unittest.TestCase):
    def test_inputs_cover_exactly_the_eligible_volumes(self):
        from kit import prizes
        letters = prizes.find(prizes.load(), "first-letters-2027")
        inputs = plan.spiral_inputs()
        self.assertEqual(set(inputs["scans"]), {e["scroll"] for e in letters["eligible"]})
        for e in letters["eligible"]:
            row = inputs["scans"][e["scroll"]]
            self.assertEqual(row["volume"], e["volume"])
            self.assertGreater(row["slices"], 0)
            self.assertEqual(len([k for k in ("bucket", "dataset") if k in row["lasagna"]]), 1, e["scroll"])
        self.assertEqual((inputs["normal_zarr_group"], inputs["lasagna_scale"]), ("2", 4))

    def test_bucket_scan_chain_in_order(self):
        text = plan.spiral_chain("PHerc. 826")
        steps = ["python -m kit centerline get PHerc0826 --into \"$DS\"",
                 "aws s3 sync --no-sign-request \"s3://vesuvius-challenge-open-data/PHerc0826/representations/"
                 "predictions/lasagna/20250821151701-lasagna-20260419180421/PHerc0826_$c.ome.zarr/\"",
                 '"spiral_outward_sense": "ACW"', "pack_resident_pools.py", "fit_spiral.py --dataset",
                 "flatten_spiral_checkpoint.py", "experiments/pherc0826/run.json", "vc_render_tifxyz \\\n  --volume",
                 "spaces/ink-lens/inklens.py run", "tell nobody in public"]
        at = [text.index(s) for s in steps]
        self.assertEqual(at, sorted(at))
        self.assertIn(plan.VILLA_SPIRAL, text)
        self.assertIn('--include "2/*"', text)
        self.assertIn('Z1="${Z1:-16920}"', text)
        self.assertIn('\\"z_begin\\": $Z0, \\"z_end\\": $Z1', text)
        self.assertIn("--um-per-px 9.362 --local --json", text)
        self.assertIn("--voxel-unit micrometer --flip-normals", text)
        self.assertIn("# Status: experimental. Not yet run end to end", text)
        self.assertIn("not yet shown to keep the surface", text)
        self.assertNotIn("hf download", text)

    def test_hf_scan_reads_the_public_dataset(self):
        text = plan.spiral_chain("PHerc0846B")
        self.assertIn("hf download SharpMeow/pherc0846b-lasagna --repo-type dataset", text)
        self.assertIn("tar -xf PHerc0846B-lasagna-pyramid-fix.tar", text)
        self.assertIn("sha256sum -c SHA256SUMS", text)
        self.assertNotIn("aws s3 sync", text)
        self.assertIn('"spiral_outward_sense": "CW"', text)

    def test_spec_follows_villas_sense_rule(self):
        row = {"z_direction_is_top_to_bottom": True, "left_handed_coordinates": True}
        self.assertEqual(plan.spiral_spec("S", 9.0, row)["spiral_outward_sense"], "CW")
        row["left_handed_coordinates"] = False
        self.assertEqual(plan.spiral_spec("S", 9.0, row)["spiral_outward_sense"], "ACW")
        spec = plan.spiral_spec("S", 9.0, {"z_direction_is_top_to_bottom": None, "left_handed_coordinates": False})
        self.assertEqual(spec["spiral_outward_sense"], "$SENSE")
        self.assertNotIn("z_direction_is_top_to_bottom", spec)

    def test_unknown_sense_needs_the_user(self):
        text = plan.spiral_chain("PHerc0490A")
        self.assertIn('SENSE="${SENSE:?', text)
        self.assertIn('"spiral_outward_sense": "$SENSE"', text)
        self.assertLess(text.index('SENSE="${SENSE:?'), text.index('cat > "$DS/spiral-scroll.json"'))
        self.assertNotIn("SENSE:?", plan.spiral_chain("PHerc0826"))

    def test_fit_uses_the_lasagna_field_and_center_line_alone(self):
        o = plan.SPIRAL_OVERRIDES
        self.assertEqual(o["dense_spacing_mode"], "grad_mag")
        used = [k for k, v in o.items() if k.startswith("input_use_") and v]
        self.assertEqual(used, [])
        self.assertTrue(o["input_disable_patches"])
        self.assertEqual(o["loss_weight_shell_outer"], 0.0)

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "awarded on 2026-10-08"):
            plan.spiral_chain("PHerc0343")
        inputs = plan.spiral_inputs()
        inputs["scans"]["PHerc0826"]["volume"] = "19990101000000"
        with self.assertRaisesRegex(ValueError, "no public spiral-fit inputs recorded for volume 20250821151701"):
            plan.spiral_chain("PHerc0826", inputs=inputs)

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_every_chain_is_valid_bash(self):
        for scroll in plan.spiral_inputs()["scans"]:
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
                fh.write(plan.spiral_chain(scroll))
            try:
                r = subprocess.run(["bash", "-n", fh.name], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{scroll}: {r.stderr}")
            finally:
                os.unlink(fh.name)


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

    def test_history_must_start_at_planned(self):
        path = ledger.path_for("t1", self.root)
        record = json.loads(path.read_text())
        record["history"] = [{"at": "x", "status": "running", "note": ""}, {"at": "y", "status": "candidate", "note": ""}]
        record["status"] = "candidate"
        path.write_text(json.dumps(record))
        self.assertIn("history does not start at planned", ledger.check("t1", self.root))
        record["history"] = []
        path.write_text(json.dumps(record))
        self.assertIn("history does not start at planned", ledger.check("t1", self.root))

    def test_cost_must_be_a_finite_number(self):
        for usd in (float("nan"), float("inf")):
            with self.assertRaises(ledger.LedgerError):
                ledger.add_cost("t1", usd, "bad", root=self.root)
        self.assertEqual(ledger.load("t1", self.root)["costs"], [])

    def test_corrupt_record_and_unknown_status_are_ledger_errors(self):
        path = ledger.path_for("t1", self.root)
        record = json.loads(path.read_text())
        record["status"] = "Running"
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ledger.LedgerError, "Running"):
            ledger.set_status("t1", "null", root=self.root)
        for text in ("{not json", "[]"):
            path.write_text(text)
            for call in (lambda: ledger.load("t1", self.root), lambda: ledger.list_runs(self.root)):
                with self.assertRaisesRegex(ledger.LedgerError, "run.json"):
                    call()

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

    def test_run_reports_a_corrupt_record_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli("run", "--root", tmp, "init", "x", "--scroll", "PHerc0211", "--question", "q", "--readout", "r")
            (Path(tmp) / "x" / "run.json").write_text("{not json")
            for argv in (("check", "x"), ("status", "x", "running"), ("cost", "x", "--usd", "1", "--what", "w"), ("list",)):
                self.assertEqual(self.run_cli("run", "--root", tmp, *argv)[0], 2, argv)

    def test_docstring_names_every_command(self):
        listed = cli.__doc__.split("{", 1)[1].split("}", 1)[0].split(",")
        commands = next(a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual(sorted(listed), sorted(commands.choices))

    def test_a_reader_that_stops_early_ends_the_command_quietly(self):
        # python -m kit prizes --json | head -1: head closes the pipe before the output is written
        root = Path(__file__).resolve().parents[1]
        for argv in (["prizes", "--json"], ["cost", "--gpu-hours", "1", "--rate", "2"]):
            read, write = os.pipe()
            os.close(read)
            try:
                done = subprocess.run([sys.executable, "-m", "kit"] + argv, cwd=root, stdout=write,
                                      stderr=subprocess.PIPE, timeout=60)
            finally:
                os.close(write)
            self.assertNotIn(b"Traceback", done.stderr, argv)
            self.assertNotIn(b"BrokenPipeError", done.stderr, argv)
            self.assertEqual(done.returncode, 1, argv)


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
