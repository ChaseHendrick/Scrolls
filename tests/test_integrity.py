"""kit integrity: every planted fault is caught as its own rule and the clean controls pass; mutations of the checks
make the selftest fail (so the selftest has power); a corpus of overclaims is caught and a corpus of careful
sentences is not; the committed results.json runs through the ink checks; the preregistration order on a small
synthetic git repository; citations with a fake arXiv; the CLI wiring and exit codes."""

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from kit import cli, integrity

ROOT = Path(__file__).resolve().parent.parent
HAS_GIT = shutil.which("git") is not None
RESULTS = json.loads((ROOT / "docs/results.json").read_text())

# Invented sentences of the kinds the text check must catch; the scroll ids are not real scrolls.
OVERCLAIMS = [
    ("We found letters in PHerc9999!", "text-reading"),
    ("The title was read from the ink map.", "text-reading"),
    ("On PHerc9999 we read three lines.", "text-reading"),
    ("Greek letters revealed in the new map.", "text-reading"),
    ("ink_9um generalizes well to w045.", "text-heldout"),
    ("Hecate reaches 0.85 AUC on held-out PHerc0841.", "text-heldout"),
    ("Our model achieves state-of-the-art AUC of 0.92.", "text-novelty"),
    ("The first fully automated unwrapping pipeline for Herculaneum scrolls.", "text-novelty"),
    ("Our method beats every published model.", "text-novelty"),
    ("This proves the model detects ink.", "text-certainty"),
    ("The results were independently verified.", "text-review"),
    ("There are possible letters in column 3 of PHerc9999.", "text-disclosure"),
    ("Letters are clearly visible in the new map of scroll PHerc9999.", "text-disclosure"),
]
CAREFUL = [
    "The ink map is model output, not a reading.",
    "ink_9um scored 0.80 on PHerc0841 w00, which it never trained on, against 0.45 reversed.",
    "On w045, a training surface for ink_9um, it scored 0.87: a pipeline check, not a generalization test.",
    "PHerc0841 is the held-out test for these readers, possibly except Hecate.",
    "Searches of arXiv and the villa repository found no earlier statement; Discord could not be searched.",
    "Read by a separate AI session in this project; not an outside review.",
    "Wait for the first job to finish before starting the second.",
    "Papyrologists read the title in 2026, as the organizers announced.",
    "A low score on a small patch proves little.",
    "Never:\n\n- say letters were found\n- call the map a reading",
    "## What it does not do\n\nIt does not show that letters were found.\n\n## Next\n\nIt runs on CPU.",
    "| Does | Does not |\n| --- | --- |\n| Score a map | Say letters were found |",
    "```\nletters were found\n```",
    'Do not write "letters were found".',
    "- **Never:** commit a map; say a letter was found or read from it.",
    "The network reads letters on synthetic pages. <!-- integrity: allow text-reading -->",
]


class SelftestTest(unittest.TestCase):
    def test_every_plant_caught_and_clean_passes(self):
        st = integrity.selftest()
        self.assertEqual(st["plants"], st["caught"])
        self.assertGreaterEqual(st["plants"], 26)
        self.assertEqual(sorted(st["rules"]), sorted(integrity.RULE_IDS))

    def test_mutations_break_the_selftest(self):
        """A check with no power would survive these; each must make the selftest raise."""
        mutations = [
            mock.patch.object(integrity, "MIN_GAP", 0.0),
            mock.patch.object(integrity, "MIN_MARGIN", 0.0),
            mock.patch.dict(integrity.TEXT_RE, {"text-reading": []}),
            mock.patch.dict(integrity.TEXT_RE, {"text-novelty": []}),
            mock.patch.object(integrity, "HELDOUT_WORDS", integrity.re.compile(r"(?!x)x")),
            mock.patch.object(integrity, "NEGATION", integrity.re.compile(r".")),
            mock.patch.object(integrity, "_same_at_precision", lambda a, b: True),
            mock.patch.object(integrity, "_norm", lambda s: ""),
            mock.patch.object(integrity, "CONTENT", {}),
        ]
        for m in mutations:
            with self.subTest(m=m), m:
                with self.assertRaises(integrity.IntegrityError):
                    integrity.selftest()

    def test_run_refuses_when_a_plant_slips(self):
        args = SimpleNamespace(action="rules", json=False)
        err = io.StringIO()
        with mock.patch.object(integrity, "MIN_GAP", 0.0), redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(integrity.run(args), integrity.EXIT_BAD)
        self.assertIn("selftest failed, no result reported", err.getvalue())


class TextTest(unittest.TestCase):
    def test_overclaims_caught(self):
        for sentence, rule in OVERCLAIMS:
            with self.subTest(sentence=sentence):
                got = {f["rule"] for f in integrity.check_text(sentence + "\n", RESULTS)}
                self.assertIn(rule, got)

    def test_careful_sentences_pass(self):
        for text in CAREFUL:
            with self.subTest(text=text):
                self.assertEqual(integrity.check_text(text + "\n", RESULTS), [])

    def test_line_numbers(self):
        got = integrity.check_text("fine\n\nWe found letters in PHerc9999.\n", RESULTS, "x.md")
        self.assertEqual([f["where"] for f in got], ["x.md:3"])


class InkTest(unittest.TestCase):
    def claim(self, **kw):
        return integrity.claim_from({**integrity.CLEAN_CLAIM, **kw})

    def rules(self, claim):
        return {(f["rule"], f["severity"]) for f in integrity.check_ink(claim, RESULTS)}

    def test_committed_exposure(self):
        self.assertEqual(integrity.exposure("ink_9um seed42", "0841-ag896", RESULTS), ("PHerc0841", "held out"))
        self.assertEqual(integrity.exposure("Hecate", "0841-w00", RESULTS), ("PHerc0841", "not held out"))
        self.assertEqual(integrity.exposure("d9v2", "w045", RESULTS), ("w045", "not held out"))
        self.assertEqual(integrity.exposure("v8in", "w045", RESULTS), ("w045", "held out"))
        self.assertEqual(integrity.exposure("ink_9um", "PHerc1667-w013", RESULTS), (None, None))

    def test_clean_claim_on_held_out_group(self):
        self.assertEqual(self.rules(self.claim()), {("ink-source", "WARN")})

    def test_held_out_claim_on_training_surface_fails(self):
        self.assertIn(("ink-heldout", "FAIL"), self.rules(self.claim(segment="w045")))

    def test_kit_auc_output(self):
        auc = {"forward": {"auc": 0.8013}, "control": {"auc": 0.4471}, "files": {"mask": "m.zarr"}, "crop": [0, 1]}
        c = integrity.claim_from(auc, reader="ink_9um seed43", segment="0841-ag405")
        self.assertEqual((c["auc"], c["control_auc"], c["mask"], c["window"]), (0.8013, 0.4471, "supervision", "crop"))
        self.assertEqual(self.rules(c), {("ink-source", "WARN")})
        nocontrol = integrity.claim_from({"forward": {"auc": 0.8}}, reader="ink_9um", segment="0841-w00")
        self.assertIn(("ink-control", "FAIL"), self.rules(nocontrol))

    def test_source_precision(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "run.json"
            p.write_text(json.dumps({"forward": {"auc": 0.73824}}))
            src = {"file": str(p), "field": "forward.auc"}
            for claimed, ok in (("0.738", True), ("0.7382", True), ("0.74", True), ("0.739", False), ("0.7383", False)):
                with self.subTest(claimed=claimed):
                    got = self.rules(self.claim(auc=claimed, source=src))
                    self.assertEqual(("ink-source", "FAIL") in got, not ok)
            with self.assertRaises(integrity.IntegrityError):
                integrity.check_ink(self.claim(source={"file": str(p), "field": "control.auc"}), RESULTS)

    def test_missing_fields_refused(self):
        with self.assertRaises(integrity.IntegrityError):
            integrity.claim_from({"auc": 0.8})
        with self.assertRaises(integrity.IntegrityError):
            integrity.check_ink(self.claim(control_auc="high"), RESULTS)

    def test_committed_results(self):
        rows = list(integrity.result_rows(RESULTS))
        self.assertGreaterEqual(len(rows), 31)
        found = [f for w, c in rows for f in integrity.check_ink(c, RESULTS, w)]
        self.assertFalse([f for f in found if f["rule"] in ("ink-gap", "ink-mask", "ink-source")
                          and f["severity"] == "FAIL"])
        # every w045 row of a reader that trained on it is flagged as a training-surface check
        w045 = [w for w, c in rows if c["segment"] == "w045" and not c["reader"].startswith("v8in")]
        flagged = {f["where"] for f in found if f["rule"] == "ink-heldout"}
        self.assertTrue(set(w045) <= flagged)


@unittest.skipUnless(HAS_GIT, "git not on PATH")
class PreregTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.t = 1_700_000_000
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")

    def tearDown(self):
        self.dir.cleanup()

    def git(self, *args):
        env = {"GIT_AUTHOR_DATE": f"{self.t} +0000", "GIT_COMMITTER_DATE": f"{self.t} +0000",
               "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": self.dir.name}
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, env=env)

    def commit(self, files, msg):
        self.t += 3600
        for name, text in files.items():
            (self.root / name).write_text(text)
        self.git("add", *files)
        self.git("commit", "-q", "-m", msg)

    PREREG = "Control: the reversed map. Rule: PASS above the threshold 0.6. Test data: held-out segment w00.\n"

    def rules(self):
        return {(f["rule"], f["severity"]) for f in integrity.check_prereg(self.root, "p.md", ["r.json"])}

    def test_clean_order(self):
        self.commit({"p.md": self.PREREG}, "prereg")
        self.commit({"r.json": "{}"}, "result")
        self.assertEqual(self.rules(), set())

    def test_result_first(self):
        self.commit({"r.json": "{}"}, "result")
        self.commit({"p.md": self.PREREG}, "prereg")
        self.assertIn(("prereg-order", "FAIL"), self.rules())

    def test_same_commit(self):
        self.commit({"p.md": self.PREREG, "r.json": "{}"}, "both")
        self.assertIn(("prereg-order", "WARN"), self.rules())

    def test_edited_after(self):
        self.commit({"p.md": self.PREREG}, "prereg")
        self.commit({"r.json": "{}"}, "result")
        self.commit({"p.md": self.PREREG.replace("0.6", "0.5")}, "move the bar")
        self.assertIn(("prereg-order", "FAIL"), self.rules())

    def test_amended_after(self):
        self.commit({"p.md": self.PREREG}, "prereg")
        self.commit({"r.json": "{}"}, "result")
        self.commit({"p.md": self.PREREG + "\n## Amendment, 2026-10-23\n\nResult: PASS.\n"}, "amend")
        self.assertEqual(self.rules(), {("prereg-order", "WARN")})

    def test_no_history(self):
        self.commit({"p.md": self.PREREG}, "prereg")
        with self.assertRaises(integrity.MissingData):
            integrity.check_prereg(self.root, "p.md", ["r.json"])


class CiteTest(unittest.TestCase):
    FEED = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2610.30495v2</id>'
            b'<title>From Prose to\n  Properties</title></entry></feed>')

    def test_titles_and_missing(self):
        calls = []

        def opener(url, timeout):
            calls.append(url)
            return io.BytesIO(self.FEED)

        titles = integrity.arxiv_titles(["2610.30495", "2610.99999"], opener=opener, sleep=lambda s: None)
        self.assertEqual(titles, {"2610.30495": "From Prose to Properties"})
        self.assertEqual(len(calls), 1)
        got = integrity.check_citations(["2610.99999"], {"2610.30495": "From prose to properties"}, titles)
        self.assertEqual([f["rule"] for f in got], ["cite-missing"])

    def test_ids_and_papers(self):
        text = "see arXiv:2610.30495v1, [2610.31372] and https://arxiv.org/abs/2502.16161 but not 2026.10230"
        self.assertEqual(integrity.arxiv_ids(text), ["2502.16161", "2610.30495", "2610.31372"])
        papers = {"entries": [{"id": "arXiv:2610.30495", "title": "T"}, {"id": "doi:10.1/x", "title": "U"}]}
        self.assertEqual(integrity.papers_titles(papers), {"2610.30495": "T"})


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        args = cli.build_parser().parse_args(["integrity", *argv])
        with redirect_stdout(out), redirect_stderr(err):
            code = args.func(args)
        return code, out.getvalue(), err.getvalue()

    def test_selftest_and_rules(self):
        code, out, _ = self.run_cli("selftest", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["plants"], json.loads(out)["caught"])
        code, out, _ = self.run_cli("rules", "--json")
        self.assertEqual([r["id"] for r in json.loads(out)], integrity.RULE_IDS)

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            bad, good = Path(d) / "bad.md", Path(d) / "good.md"
            bad.write_text("We found letters in PHerc9999.\n")
            good.write_text("The ink map is model output, not a reading.\nThis is the first tool to try it.\n")
            self.assertEqual(self.run_cli("text", str(bad))[0], 3)
            self.assertEqual(self.run_cli("text", str(good))[0], 0)
            self.assertEqual(self.run_cli("text", str(good), "--strict")[0], 3)
            code, out, _ = self.run_cli("text", str(bad), "--json")
            self.assertEqual((code, json.loads(out)["fail"]), (3, 1))
            self.assertEqual(self.run_cli("text", str(Path(d) / "missing.md"))[0], 1)
            claim = Path(d) / "c.json"
            claim.write_text(json.dumps({"forward": {"auc": 0.8}}))
            self.assertEqual(self.run_cli("ink", str(claim), "--reader", "ink_9um", "--segment", "0841-w00")[0], 3)
            self.assertEqual(self.run_cli("ink", str(claim))[0], 1)

    def test_results_and_exposure(self):
        code, out, _ = self.run_cli("results", "--json")
        self.assertIn(code, (0, 3))
        self.assertGreaterEqual(json.loads(out)["rows"], 31)
        code, out, _ = self.run_cli("exposure", "--json")
        self.assertIn({"group": "PHerc0841", "reader": "Hecate", "status": "not held out"}, json.loads(out))

    def test_cite_offline(self):
        code, out, _ = self.run_cli("cite", str(ROOT / "docs/papers.json"), "--offline", "--json")
        self.assertEqual(code, 0)
        self.assertGreater(json.loads(out)["arxiv_ids"], 0)


if __name__ == "__main__":
    unittest.main()
