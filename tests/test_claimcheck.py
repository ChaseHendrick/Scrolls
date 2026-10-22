"""kit.claimcheck: README Novel findings numbers traced to pinned sources, and results units to files."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import claimcheck as cc

ROOT = Path(__file__).resolve().parent.parent

README = """# Repo

## Novel findings

> [!NOTE]
> **Latest evidence review: 11 October 2026.**

- **Alpha holds** (2026-10-07). Reader AUC 0.738 against 0.914 on the 640 px crop; see [log](docs/logs/a.md).
- **Beta also holds** (15 and 16 October 2026). The gap was -1.64 to -0.80 mm, about 96 % missing.

Related note without numbers.

## Next section

- **Gamma** 0.555 is outside the section.
"""


def make_repo(base):
    root = Path(base)
    (root / "docs" / "logs").mkdir(parents=True)
    (root / "docs" / "evidence" / "x").mkdir(parents=True)
    (root / "README.md").write_text(README)
    (root / "docs" / "logs" / "a.md").write_text("AUC 0.9141 for ink_9um; v8in 0.7382.\n")
    (root / "docs" / "evidence" / "x" / "r.json").write_text(json.dumps({"lo": -1.6422, "hi": -0.8002}))
    results = {"schema": 1, "about": "x",
               "results": [{"auc": 0.7382, "source": "docs/logs/a.md"}, {"auc": 0.5, "note": "no file"}],
               "community": [{"auc": 0.81, "source": "https://example.org/paper"}]}
    (root / "docs" / "results.json").write_text(json.dumps(results))
    return root


class ExtractTest(unittest.TestCase):
    def test_numbers_leave_out_dates_ids_and_refs(self):
        text = ("On PHerc0841 w045 (2026-10-07, 15 and 16 October 2026) `ink_9um` at 25f3c93 scored 0.738 "
                "against 0.914, [villa #2058](https://x/2058), finding 12, -1.64 mm, 96 %, 2.07x faster, 1,223 "
                "vertices, 12.7 cm², at 10:30 UTC in 2026, trainer lines 200-207 and 292-293.")
        toks = [n["token"] for n in cc.numbers(text)]
        self.assertEqual(toks, ["0.738", "0.914", "-1.64", "96%", "2.07", "1,223", "12.7"])

    def test_blocks_stop_at_next_section(self):
        blocks = cc.section_blocks(README)
        self.assertEqual([b["key"] for b in blocks],
                         ["alpha-holds", "beta-also-holds", "related-note-without-numbers"])
        self.assertEqual(blocks[0]["kind"], "item")
        self.assertEqual(blocks[2]["kind"], "paragraph")

    def test_matches_rounding_integers_percent(self):
        n = cc.numbers("0.738 96 % 13")
        self.assertTrue(cc.matches(n[0], [0.7382]))
        self.assertFalse(cc.matches(n[0], [0.7392]))
        self.assertTrue(cc.matches(n[1], [0.96]))
        self.assertTrue(cc.matches(n[2], [13.0]))
        self.assertFalse(cc.matches(n[2], [12.6]))   # an integer matches only an equal integer


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self.tmp.name)
        cc.add_entry(self.root, "alpha-holds", ["docs/logs/a.md"],
                     ["640=setting: the crop size"], write=True)
        cc.add_entry(self.root, "beta-also-holds", ["docs/evidence/x"],
                     ["96%=derived: from the source's shares"], write=True)
        doc = cc.load_ledger(self.root)
        doc["results_baseline"] = [u["sha12"] for u in cc.results_unsourced(self.root)["unsourced"]]
        cc.save_ledger(self.root, doc)

    def tearDown(self):
        self.tmp.cleanup()

    def codes(self, **kw):
        return sorted({f["code"] for f in cc.check(self.root, **kw)["findings"]})

    def test_clean_repo_passes(self):
        out = cc.check(self.root)
        self.assertEqual(out["exit"], 0, out["findings"])
        self.assertEqual(out["counts"]["numbers"], 6)
        self.assertEqual(out["counts"]["reasoned"], 2)

    def test_unsourced_number_fails(self):
        text = README.replace("0.914 on", "0.914 and 0.123 on")
        out = cc.check(self.root, readme_text=text)
        self.assertEqual(out["exit"], 1)
        self.assertEqual([f["code"] for f in out["findings"]], ["C2"])
        self.assertIn("0.123", out["findings"][0]["text"])

    def test_new_claim_without_entry_fails(self):
        text = README.replace("Related note", "- **Delta** scored 0.42.\n\nRelated note")
        self.assertEqual(self.codes(readme_text=text), ["C1"])

    def test_edited_source_fails_until_repinned(self):
        (self.root / "docs" / "logs" / "a.md").write_text("AUC 0.9141 for ink_9um; v8in 0.7382. More.\n")
        self.assertEqual(self.codes(), ["C4"])
        self.assertEqual(len(cc.pin(self.root, write=True)["changes"]), 1)
        self.assertEqual(self.codes(), [])

    def test_changed_number_in_source_fails(self):
        (self.root / "docs" / "logs" / "a.md").write_text("AUC 0.9241 for ink_9um; v8in 0.7382.\n")
        cc.pin(self.root, write=True)
        self.assertEqual(self.codes(), ["C2"])

    def test_missing_source_and_stale_reason_and_stale_block(self):
        (self.root / "docs" / "evidence" / "x" / "r.json").unlink()
        (self.root / "docs" / "evidence" / "x").rmdir()
        text = README.replace("640 px crop", "crop").replace("Beta also holds", "Beta renamed")
        codes = self.codes(readme_text=text)
        self.assertIn("C5", codes)     # reason for 640, no longer stated
        self.assertIn("C6", codes)     # ledger names beta-also-holds, gone
        self.assertIn("C1", codes)     # beta-renamed has no entry
        self.assertEqual(self.codes(), ["C2", "C3"])

    def test_documents_are_checked_and_a_moved_block_keeps_its_entry(self):
        doc = cc.load_ledger(self.root)
        doc["documents"] = ["docs/FINDINGS.md"]
        cc.save_ledger(self.root, doc)
        with self.assertRaises(cc.ClaimError):
            cc.check(self.root)                                                # a listed document must exist
        alpha = next(ln for ln in README.splitlines() if ln.startswith("- **Alpha holds**"))
        findings = ("# Findings\n\n## Held up\n\n" + alpha.replace("](docs/logs/a.md)", "](logs/a.md)") +
                    "\n\n## Failed\n\n- **Epsilon failed** at 0.3141.\n")
        (self.root / "docs" / "FINDINGS.md").write_text(findings)
        moved = README.replace(alpha + "\n", "")
        codes = self.codes(readme_text=moved)
        self.assertEqual(codes, ["C1"])                                       # alpha's entry carries; epsilon has none
        out = cc.check(self.root, readme_text=moved)
        self.assertTrue(any(f["where"].startswith("docs/FINDINGS.md:") and "epsilon-failed" in f["where"]
                            for f in out["findings"]))
        (self.root / "README.md").write_text(moved)
        self.assertEqual(cc.suggest(self.root, "alpha-holds")["chosen"][0]["ref"], "docs/logs/a.md")
        (self.root / "docs" / "logs" / "e.md").write_text("the run gave 0.31409\n")
        entry = cc.add_entry(self.root, "epsilon-failed", ["docs/logs/e.md"], write=True)["entry"]
        self.assertEqual(entry["doc"], "docs/FINDINGS.md")
        with self.assertRaises(cc.ClaimError):
            cc.add_entry(self.root, "epsilon-failed", ["docs/FINDINGS.md"])     # a checked file cannot be a source
        self.assertEqual(self.codes(), [])
        self.assertEqual(self.codes(readme_text=README), ["C1"])             # the same key in both: alpha-holds-2
        doc = cc.load_ledger(self.root)
        doc["blocks"]["epsilon-failed"]["sources"]["docs/FINDINGS.md"] = "0" * 64
        cc.save_ledger(self.root, doc)
        self.assertEqual(self.codes(), ["C3"])                                # the control: a self-citation fails

    def test_add_refuses_untraced_numbers_and_bad_reasons(self):
        with self.assertRaises(cc.ClaimError):
            cc.add_entry(self.root, "alpha-holds", ["docs/logs/a.md"])          # 640 untraced
        with self.assertRaises(cc.ClaimError):
            cc.add_entry(self.root, "alpha-holds", ["docs/logs/a.md"], ["640=because"])
        with self.assertRaises(cc.ClaimError):
            cc.add_entry(self.root, "alpha-holds", ["../outside.md"], ["640=setting: x"])
        with self.assertRaises(cc.ClaimError):
            cc.add_entry(self.root, "alpha-holds", ["r:results/9"], ["640=setting: x"])

    def test_results_unit_refs_and_ratchet(self):
        self.assertEqual(cc.Sources(self.root).resolve("r:results/0")[1], [0.7382])
        res = json.loads((self.root / "docs" / "results.json").read_text())
        res["results"].append({"auc": 0.6})
        (self.root / "docs" / "results.json").write_text(json.dumps(res))
        self.assertEqual(self.codes(), ["C7"])
        # the community row cites its publication's URL, which counts for an external row only
        self.assertEqual([u["ref"] for u in cc.results_unsourced(self.root)["unsourced"]],
                         ["r:results/1", "r:results/2"])

    def test_unit_sha_matches_kit_causal_rule(self):
        u = {"auc": 0.7, "id": "x", "causal": ["a"]}
        self.assertEqual(cc.unit_sha256(u), cc.unit_sha256({"auc": 0.7}))
        self.assertNotEqual(cc.unit_sha256(u), cc.unit_sha256({"auc": 0.71}))

    def test_causal_claims_sources_are_read(self):
        (self.root / "docs" / "causal").mkdir()
        (self.root / "docs" / "causal" / "claims.json").write_text(json.dumps({"schema": "causal-claims/1", "claims": [
            {"id": "b", "readme_item": 2, "quote": "The gap was", "label": "Measurement",
             "causal": ["source docs/evidence/x/ sha256:abc"]}]}))
        blocks = cc.section_blocks(README)
        self.assertEqual(cc.causal_sources(self.root, blocks), {"beta-also-holds": ["docs/evidence/x"]})

    def write_causal(self, doc):
        (self.root / "docs" / "causal").mkdir(exist_ok=True)
        path = self.root / "docs" / "causal" / "claims.json"
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc))

    def test_causal_ledger_is_optional_and_says_so(self):
        # kit causal is not merged: without its file the check runs on this ledger alone and says so in one line
        out = cc.check(self.root)
        self.assertEqual(out["exit"], 0, out["findings"])
        self.assertIn("absent", out["causal"])
        # a file it cannot read is reported, never a crash or a failure
        for bad in ("{not json", json.dumps([1, 2]), json.dumps({"schema": "other/9", "claims": []})):
            self.write_causal(bad)
            out = cc.check(self.root)
            self.assertEqual(out["exit"], 0, out["findings"])
            self.assertIn("not read", out["causal"])
            self.assertEqual(cc.causal_sources(self.root, cc.section_blocks(README)), {})
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(cc.main(["--root", str(self.root), "check"]), 0)
        self.assertIn("causal ledger", buf.getvalue())

    def test_control_causal_source_is_read_unless_switched_off(self):
        # a number only kit causal's source holds: traced with the causal ledger, C2 with --no-causal
        (self.root / "docs" / "logs" / "b.md").write_text("spread 0.123\n")
        text = README.replace("0.914 on", "0.914 and 0.123 on")
        self.write_causal({"schema": "causal-claims/1", "claims": [
            {"id": "a", "quote": "Reader AUC 0.738", "causal": ["source docs/logs/b.md sha256:abc", 7, "note x"]}]})
        out = cc.check(self.root, readme_text=text)
        self.assertEqual(out["exit"], 0, out["findings"])
        self.assertIn("read, 1 claims", out["causal"])
        out = cc.check(self.root, readme_text=text, causal=False)
        self.assertEqual([f["code"] for f in out["findings"]], ["C2"])
        self.assertIn("--no-causal", out["causal"])

    def test_bad_causal_source_does_not_block_add(self):
        self.write_causal({"schema": "causal-claims/1", "claims": [
            {"id": "a", "quote": "Reader AUC 0.738", "causal": ["source docs/logs/gone.md"]}]})
        got = cc.add_entry(self.root, "alpha-holds", ["docs/logs/a.md"], ["640=setting: the crop size"])
        self.assertEqual(list(got["causal_bad"]), ["docs/logs/gone.md"])
        with self.assertRaises(cc.ClaimError):       # a source the reviewer gave still has to exist
            cc.add_entry(self.root, "alpha-holds", ["docs/logs/gone.md"], ["640=setting: x"])

    def test_suggest_and_cli(self):
        s = cc.suggest(self.root, "alpha-holds")
        self.assertEqual(s["chosen"][0]["ref"], "docs/logs/a.md")
        self.assertEqual(s["left"], ["640"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cc.main(["--root", str(self.root), "check"]), 0)
            self.assertEqual(cc.main(["--root", str(self.root), "trace", "nope"]), 2)


class RepositoryTest(unittest.TestCase):
    """This repository's README: every number in Novel findings has a pinned source or a reason, and the check
    catches an unsourced number put into it (the control)."""

    def setUp(self):
        if not (ROOT / cc.LEDGER).exists():
            self.skipTest("no claims ledger")

    def test_readme_claims_traced(self):
        out = cc.check(ROOT)
        self.assertEqual(out["findings"], [], "run python -m kit.claimcheck check")
        self.assertGreater(out["counts"]["numbers"], 100)

    def test_control_unsourced_number_in_readme_fails(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        blocks = cc.section_blocks(text)
        first = next(b for b in blocks if cc.numbers(b["text"]))
        line = text.splitlines()[first["line"] - 1]
        mutated = text.replace(line, line + " It also scored 0.987654.", 1)
        out = cc.check(ROOT, readme_text=mutated)
        self.assertEqual(out["exit"], 1)
        self.assertTrue(any(f["code"] == "C2" and "0.987654" in f["text"] for f in out["findings"]))


if __name__ == "__main__":
    unittest.main()
