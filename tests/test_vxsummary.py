"""kit/vxsummary.py and the Snapped Labels Space's Voxel exact tab (docs/tools/snapped-labels.md).

Every check of the data contract is shown failing on a summary that breaks it, so a private exporter cannot ship a
file the page would draw wrong or one that carries something it should not. The media script's guards run everywhere;
its rendering needs numpy and Pillow.
"""

import contextlib
import copy
import importlib.util
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import vxsummary as vx

ROOT = Path(__file__).resolve().parent.parent
SPACE = ROOT / "spaces" / "snapped-labels"
FIXTURE = SPACE / "vx" / "fixture"
MEDIA = ROOT / "scripts" / "media"
HAVE_NUMPY = importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("PIL") is not None


class Contract(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.doc = vx.fixture(self.tmp)

    def problems(self, doc, **kw):
        return vx.check(doc, base=self.tmp, **kw)

    def assertFails(self, doc, needle, **kw):
        found = self.problems(doc, **kw)
        self.assertTrue(any(needle in p for p in found), f"{needle!r} not in {found}")

    def c0(self, doc):
        return doc["scrolls"][0]["strata"][0]

    def test_fixture_is_valid_but_never_deploys(self):
        self.assertEqual(self.problems(self.doc), [])
        found = self.problems(self.doc, deploy=True)
        self.assertTrue(any("fixture is true" in p for p in found))
        self.assertTrue(any("placeholder" in p for p in found))
        self.assertTrue(any("SYNTH" in p for p in found))

    def test_committed_fixture_is_the_generated_one(self):
        for f in sorted(p for p in self.tmp.rglob("*") if p.is_file()):
            rel = f.relative_to(self.tmp)
            self.assertEqual((FIXTURE / rel).read_bytes(), f.read_bytes(), f"{rel} differs: rerun "
                             "python -m kit vxsummary fixture spaces/snapped-labels/vx/fixture")
        committed = {p.relative_to(FIXTURE) for p in FIXTURE.rglob("*") if p.is_file()}
        generated = {p.relative_to(self.tmp) for p in self.tmp.rglob("*") if p.is_file()}
        self.assertEqual(committed, generated)

    def test_unknown_keys_are_refused(self):
        d = copy.deepcopy(self.doc)
        d["scrolls"][0]["site_positions"] = [[1, 2, 3]]
        self.assertFails(d, "keys not in the contract: site_positions")
        d = copy.deepcopy(self.doc)
        self.c0(d)["within"]["1"]["sites"] = []
        self.assertFails(d, "keys not in the contract: sites")

    def test_shares_and_intervals_must_add_up(self):
        d = copy.deepcopy(self.doc)
        self.c0(d)["within"]["1"]["share"] = 0.99
        self.assertFails(d, "but k/n is")
        d = copy.deepcopy(self.doc)
        self.c0(d)["within"]["1"]["lower"] = 0.99
        self.assertFails(d, "is above the share")
        d = copy.deepcopy(self.doc)
        self.c0(d)["within"]["1"]["upper"] = 0.5
        self.assertFails(d, "is below the share")
        d = copy.deepcopy(self.doc)
        self.c0(d)["within"]["1"]["k"] = 99
        self.assertFails(d, "0 <= k <= n")
        d = copy.deepcopy(self.doc)
        self.c0(d)["within"]["2"]["n"] = 60
        self.c0(d)["within"]["2"]["share"] = round(58 / 60, 6)
        self.assertFails(d, "its basis scorable has 58 sites")

    def test_a_tolerance_not_measured_is_null_never_missing(self):
        d = copy.deepcopy(self.doc)
        self.c0(d)["within"]["0.5"] = None
        self.assertEqual(self.problems(d), [])
        del self.c0(d)["within"]["0.5"]
        self.assertFails(d, "exactly the slots")
        d = copy.deepcopy(self.doc)
        self.c0(d)["within"]["1"] = None
        self.assertFails(d, "primary stratum reports the share within 1 voxel")

    def test_controls_must_agree_with_their_numbers(self):
        d = copy.deepcopy(self.doc)
        self.c0(d)["controls"][0]["holds"] = False
        self.assertFails(d, "but holds says False")
        d = copy.deepcopy(self.doc)
        self.c0(d)["controls"][0]["observed"] = None
        self.assertFails(d, "holds is null when nothing was observed")

    def test_histograms_are_checked(self):
        d = copy.deepcopy(self.doc)
        self.c0(d)["residual_hist"]["counts"].pop()
        self.assertFails(d, "one count per bin")
        d = copy.deepcopy(self.doc)
        del self.c0(d)["residual_hist"]["sign"]
        self.assertFails(d, "what a positive residual means")

    def test_claim_levels_carry_what_they_need(self):
        d = copy.deepcopy(self.doc)
        d["scrolls"][2]["why_not_shown"] = None
        self.assertFails(d, "says why")
        d = copy.deepcopy(self.doc)
        d["scrolls"][1]["truth"] = {"kind": "finer_scan", "volume_id": "x", "voxel_um": 1.1}
        self.assertFails(d, "has no truth scan")
        d = copy.deepcopy(self.doc)
        d["scrolls"][1]["certificate"]["assumptions"] = []
        self.assertFails(d, "the stated assumptions")
        d = copy.deepcopy(self.doc)
        d["scrolls"][0]["truth"] = None
        self.assertFails(d, "names its truth scan")
        d = copy.deepcopy(self.doc)
        for s in d["scrolls"][0]["strata"]:
            s["primary"] = False
        self.assertFails(d, "at least one primary stratum")
        d = copy.deepcopy(self.doc)
        d["scrolls"][1]["strata"] = copy.deepcopy(d["scrolls"][0]["strata"][1:2])
        self.assertFails(d, "carries its certificate, not strata")
        d = copy.deepcopy(self.doc)
        d["scrolls"][0]["vertices"]["by_code"]["0"] += 1
        self.assertFails(d, "by_code adds to")

    def test_a_void_test_has_every_verdict_void(self):
        d = copy.deepcopy(self.doc)
        d["scrolls"][0]["void"] = ["the oracle control failed"]
        self.assertFails(d, "every stratum's verdict is VOID")
        for s in d["scrolls"][0]["strata"]:
            s["verdict"] = "VOID"
        self.assertFails(d, "with none it is not shown")
        d["scrolls"][0]["claim"] = "not_shown"
        d["scrolls"][0]["why_not_shown"] = "the test was void"
        self.assertEqual(self.problems(d), [])

    def test_a_measured_claim_needs_a_pass_and_not_shown_carries_none(self):
        d = copy.deepcopy(self.doc)
        for s in d["scrolls"][0]["strata"]:
            if s["verdict"] == "PASS":
                s["verdict"] = "NOT SHOWN"
        self.assertFails(d, "with none it is not shown")
        # the same scroll, not shown, keeps its numbers, intervals and controls: they make no claim
        d["scrolls"][0]["claim"] = "not_shown"
        d["scrolls"][0]["why_not_shown"] = "no stratum cleared the bar"
        self.assertEqual(self.problems(d), [])
        d["scrolls"][0]["strata"][0]["verdict"] = "PASS"
        self.assertFails(d, "a PASS makes it measured")

    def test_public_text_rules(self):
        for text, needle in (("about 3 USD per scroll", "a cost"), ("$0.40", "a cost"),
                             ("one" + chr(0x2014) + "two", "a long dash"), ("letters found here", "letter")):
            d = copy.deepcopy(self.doc)
            self.c0(d)["why"] = text
            self.assertFails(d, needle)

    def test_a_prize_eligible_scroll_is_refused(self):
        for name in ("PHerc0125", "PHerc. 1447", "PHerc0175", "PHercParis4"):
            d = copy.deepcopy(self.doc)
            d["scrolls"][2]["scroll"] = name
            self.assertFails(d, "prize-eligible")
        d = copy.deepcopy(self.doc)
        d["scrolls"][2]["scroll"] = "PHerc0814"
        self.assertEqual(self.problems(d), [])

    def test_showcase_guards(self):
        d = copy.deepcopy(self.doc)
        d["showcase"][0]["spent"] = False
        self.assertFails(d, "spent for later tests")
        d = copy.deepcopy(self.doc)
        d["showcase"][0]["file"] = "show/../../secret.json"
        self.assertFails(d, "a .json path under show/")
        d = copy.deepcopy(self.doc)
        d["showcase"][0]["scroll"] = "SYNTH-Z"
        self.assertFails(d, "is not in scrolls")
        show = self.tmp / "show" / "SYNTH-A" / "synthetic-sheet.json"
        meta = json.loads(show.read_text(encoding="utf-8"))
        meta["residual"][meta["state"].index(2)] = 0.5
        show.write_text(json.dumps(meta), encoding="utf-8")
        self.assertFails(self.doc, "held-back cells carry a residual")
        meta["residual"][meta["state"].index(2)] = None
        meta["residual"][meta["state"].index(0)] = None
        show.write_text(json.dumps(meta), encoding="utf-8")
        self.assertFails(self.doc, "measured cells have no residual")
        meta["rows"] = meta["rows"][:-1]
        show.write_text(json.dumps(meta), encoding="utf-8")
        self.assertFails(self.doc, "per line piece")

    def test_no_binary_files_in_the_space(self):
        # binaries go to Hugging Face, never public Git: the showcase grids are JSON number lists
        self.assertEqual([p for p in SPACE.rglob("*.bin")], [])

    def test_online_check_reads_the_revision(self):
        good = io.BytesIO(json.dumps({"sha": self.doc["dataset"]["revision"]}).encode())
        with mock.patch("urllib.request.urlopen", return_value=contextlib.nullcontext(good)):
            self.assertEqual(vx.online_problems(self.doc), [])
        bad = io.BytesIO(json.dumps({"sha": "f" * 40}).encode())
        with mock.patch("urllib.request.urlopen", return_value=contextlib.nullcontext(bad)):
            self.assertTrue(vx.online_problems(self.doc))

    def test_command_line_exit_codes(self):
        run = lambda *a: subprocess.run([sys.executable, "-m", "kit", "vxsummary", *a], cwd=ROOT,  # noqa: E731
                                        capture_output=True, text=True)
        path = str(self.tmp / "summary.json")
        self.assertEqual(run("check", path).returncode, 0)
        r = run("check", path, "--deploy")
        self.assertEqual(r.returncode, 1)
        self.assertIn("never deploys", r.stderr)
        (self.tmp / "broken.json").write_text("{", encoding="utf-8")
        self.assertEqual(run("check", str(self.tmp / "broken.json")).returncode, 2)


class Space(unittest.TestCase):
    def test_tab_is_hidden_until_a_summary_loads(self):
        html = (SPACE / "index.html").read_text(encoding="utf-8")
        self.assertIn('<button data-tab="exact" role="tab" id="vx-tabbtn" hidden>', html)
        self.assertIn('<section data-pane="exact" hidden', html)
        self.assertLess(html.index('<script src="app.js">'), html.index('<script src="vx.js">'))
        self.assertEqual(html.count('class="vx-fixture vx-banner'), 2, "the fixture banner, page top and tab")
        js = (SPACE / "vx.js").read_text(encoding="utf-8")
        self.assertIn("b.hidden = !VX.fixture", js)
        self.assertIn("'vx/fixture/summary.json'", js)

    def test_a_shipped_summary_passes_the_deploy_check(self):
        # vx/summary.json is added only in the change Chase approves; whenever it is there, it must be real and valid.
        real = SPACE / "vx" / "summary.json"
        if not real.exists():
            self.skipTest("no vx/summary.json yet: the tab stays hidden")
        self.assertEqual(vx.check(vx.load(real), deploy=True, base=real.parent), [])

    def test_space_text_carries_no_costs_or_long_dashes(self):
        for name in ("index.html", "vx.js", "app.js", "style.css", "README.md"):
            text = (SPACE / name).read_text(encoding="utf-8")
            self.assertNotIn("USD", text, name)
            for ch in (chr(0x2014), chr(0x2013)):
                self.assertNotIn(ch, text, name)

    def test_page_scripts_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        for name in ("app.js", "vx.js"):
            r = subprocess.run([node, "--check", str(SPACE / name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


class Media(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(MEDIA))
        spec = importlib.util.spec_from_file_location("snap_media", MEDIA / "snap_media.py")
        cls.sm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.sm)
        import common
        cls.common = common

    def test_timeline_is_the_pages_motion(self):
        tl = self.sm.timeline(back=True)
        self.assertEqual(tl[0], (0.0, 1.2))
        self.assertTrue(math.isclose(sum(d for _, d in tl), 1.2 + 2.4 + 1.6 + 2.4, abs_tol=0.15))
        self.assertIn((1.0, 1.6), tl)
        self.assertTrue(all(0 <= t <= 1 for t, _ in tl))

    def test_real_media_is_model_output_and_never_goes_to_docs_assets(self):
        view = {"scroll": "PHerc0139", "voxel_um": 9.362, "frame": "20250728140407"}
        meta = self.sm.real_meta(view, "PHerc0139/20260206000002-w054_2026020617", 8048)
        self.assertEqual(meta["label"], "Model output")
        self.assertEqual(self.common.real_data_problems(meta), [])
        with self.assertRaises(self.common.MediaError):
            self.common.write_guard(meta["label"], ROOT / "docs" / "assets" / "x.gif", meta)

    def test_real_media_refuses_eligible_scrolls_and_held_out_labels(self):
        eligible = self.sm.real_meta({"scroll": "PHerc0125", "voxel_um": 9.4, "frame": ""}, "PHerc0125/x-w001", 10)
        self.assertTrue(any("prize-eligible" in p for p in self.common.real_data_problems(eligible)))
        held = self.sm.real_meta({"scroll": "PHerc0841", "voxel_um": 9.4, "frame": ""},
                                 "PHerc0841/20260220174252405-ag405_x", 10)
        held["data"]["labels"] = "published and snapped labels of ag405"
        self.assertTrue(any("held-out" in p for p in self.common.real_data_problems(held)))
        with mock.patch.object(self.sm, "_get", return_value=json.dumps(
                {"scroll": "PHerc0125", "voxel_um": 9.4, "frame": "", "planes": []}).encode()):
            with self.assertRaises(self.common.MediaError):
                self.sm.real("PHerc0125/x-w001", 10, tempfile.mkdtemp())

    @unittest.skipUnless(HAVE_NUMPY, "needs numpy and Pillow")
    def test_concept_frames_render(self):
        a = self.sm.concept_scene(0.0, 0.0, size=(320, 180))
        b = self.sm.concept_scene(1.0, 1.0, size=(320, 180))
        self.assertEqual(a.size, (320, 180))
        self.assertNotEqual(a.tobytes(), b.tobytes())


if __name__ == "__main__":
    unittest.main()
