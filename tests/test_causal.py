"""Tests for kit/causal.py on synthetic temporary git repositories: the link line, the alias map, transitive
satisfaction, RECORD_SHAPES joins, the ratchet, every check rule failing and passing (the check's own control,
hard rule 4), the writers and their frozen-path guard, the bounded backfill passes and the CLI.

Keep this file byte-identical in Scrolls and Scrolls-private, as kit/causal.py: it uses no real data, numbers or
names, and passes `public` explicitly wherever the public and private rules differ.
"""

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from kit import causal

GIT = shutil.which("git")
ENV = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="Test",
           GIT_COMMITTER_EMAIL="test@example.com")
SHA_A = "a" * 64


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=ENV, check=True).stdout


def write(root, rel, content):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(content, str):
        content = json.dumps(content, indent=1, ensure_ascii=False) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def commit(root, message="change"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


def linked_row(**extra):
    row = {"id": "checks/new", "auc": 0.7, "auc_reversed": 0.5, "source": "docs/logs/2026-01-01-note.md",
           "causal": ["run none:no-compute", "prereg none:benchmark-reproduction", "control field:auc_reversed"]}
    row.update(extra)
    return row


def base_files():
    return {
        "docs/logs/2026-01-01-note.md": "# A dated note\n",
        "docs/prereg/2026-01-01-rule.md": "# A rule\n\nFrozen.\n",
        "docs/compute/modal-specs/2026-01-01-spec.md": "# A spec\n",
        "docs/evidence/run1/result.json": {"value": 1},
        "docs/results.json": {
            "schema": 1, "about": "synthetic",
            "checks": [
                {"auc": 0.6, "auc_reversed": 0.4, "source": "docs/logs/2026-01-01-note.md"},
                {"what": "a count", "source": "https://example.com/report"},
            ],
            "single_20260101": {"date": "2026-01-01", "evidence": "docs/evidence/run1/result.json",
                                "prereg": "docs/prereg/2026-01-01-rule.md", "token": "20260101T000000Z",
                                "code_commit": "abcdef1"},
            "community": [{"auc": 0.8, "source": "https://example.com/forum", "villa_commit": "1234567"}],
            "pending": ["a check still to run"],
        },
        "docs/DECISIONS.md": ("# Decisions\n\n| Date | Decision |\n| --- | --- |\n"
                              "| 2026-01-01 | First rule (replaced on 2026-01-02, see that row) |\n"
                              "| 2026-01-02 | Second rule. Replaces D1 |\n"
                              "| 2026-01-02 | Another decision the same day |\n"),
        "README.md": ("# Repo\n\n## Novel findings\n\n- **A first finding about counts** (2026-01-01, model output). "
                      "[evidence](docs/evidence/run1/result.json)\n"
                      "1. **A second finding** (2026-01-02).\n\n## Other\n"),
        "tests/test_repo.py": 'HASH_PINNED_WITH_DASHES = {\n    "docs/pinned.md",\n}\n',
        "docs/pinned.md": "pinned\n",
    }


def run_record(token, causal_lines=(), commit_sha="abcdef1234567890abcdef1234567890abcdef12", public=True, **extra):
    """A minimal run record with a correct digest."""
    rec = {"schema": 1, "run": f"kit test {token}", "kind": "run", "runrecord_schema": 1, "token": token,
           "tool": "kit test", "public": public, "code": [{"repo": "repo", "commit": commit_sha,
                                                           "uncommitted_changes": False}],
           "inputs": [], "outputs": [], "causal": list(causal_lines), "exit_code": 0}
    rec.update(extra)
    rec["digest"] = causal._sha256_bytes(causal._canonical(rec))
    return rec


@unittest.skipIf(GIT is None, "git is not installed")
class Fixture(unittest.TestCase):
    """A temporary git repository with the base files committed."""

    files = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        for rel, content in (self.files or base_files()).items():
            write(self.root, rel, content)
        self.head = commit(self.root, "base")

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, public=False):
        return causal.load(self.root, public=public)

    def results(self):
        return json.loads((self.root / "docs/results.json").read_text(encoding="utf-8"))

    def set_results(self, data):
        write(self.root, "docs/results.json", data)

    def rules(self, report, level="error"):
        return sorted({f["rule"] for f in report["findings"] if f["level"] == level})

    def check(self, public=False, **kw):
        return causal.check(self.root, public=public, hash_pins=kw.pop("hash_pins", True), **kw)

    def cutover(self):
        out = causal.ratchet(self.root, write=True)
        self.assertTrue(out["created"])
        commit(self.root, "cutover")
        return out


class ParseTest(unittest.TestCase):
    def test_valid_lines(self):
        for line, kind in (("decision D41", "decision"), ("prereg docs/prereg/x.md@abc1234", "path"),
                           ("run 20261021T101500Z-slug", "token"), ("run ap-ABCDEFGHIJKLMNOPQRSTUV", "app"),
                           ("run sha256:" + SHA_A, "sha256"), ("code villa@6723ad1", "commit"),
                           ("code ChaseHendrick/Scrolls#12", "pr"), ("input https://example.com/m", "url"),
                           ("control field:auc_reversed", "field"), ("control none:not-a-score", "none"),
                           ("source c:a-claim", "claim"), ("source tool:auc", "tool"), ("corrects r:x/1", "result"),
                           ("decision private:" + SHA_A, "private"), ("approval approval:x", "approval")):
            with self.subTest(line=line):
                self.assertEqual(causal.parse(line)["kind"], kind)

    def test_pin_note_and_at(self):
        p = causal.parse(f"prereg docs/prereg/x.md@abc1234 sha256:{SHA_A} # frozen")
        self.assertEqual((p["path"], p["at"], p["pin"], p["note"]), ("docs/prereg/x.md", "abc1234", SHA_A, "frozen"))

    def test_removed_and_bad(self):
        for line in ("model https://x", "record sha256:" + SHA_A, "evidence docs/evidence/x", "qualifies r:x",
                     "nope D1", "run none:because", "decision", "run  x", "control r:x sha256:short",
                     "decision none:metadata", "source not a path"):
            with self.subTest(line=line):
                with self.assertRaises(causal.CausalError):
                    causal.parse(line)

    def test_fits(self):
        self.assertTrue(causal._fits("spec", "path", "docs/compute/modal-specs/x.md"))
        self.assertFalse(causal._fits("spec", "path", "docs/logs/x.md"))
        self.assertTrue(causal._fits("run", "sha256"))
        self.assertFalse(causal._fits("code", "path"))
        self.assertTrue(causal._fits("source", "decision"))

    def test_unit_sha256_ignores_links(self):
        a = {"auc": 0.5}
        self.assertEqual(causal.unit_sha256(a), causal.unit_sha256({**a, "id": "x/1", "causal": ["run none:pending"]}))
        self.assertNotEqual(causal.unit_sha256(a), causal.unit_sha256({"auc": 0.6}))

    def test_edge_sha8_is_order_free(self):
        a = {"effect": "D1", "line": "source docs/x.md", "basis": "review", "added": "2026-01-01"}
        b = dict(reversed(list(a.items())))
        self.assertEqual(causal.edge_sha8(a), causal.edge_sha8(b))


class GraphTest(Fixture):
    def test_alias_map_classes_and_defaults(self):
        g = self.load()
        causes = {(e["rel"], e["cause"], e["cls"], e["via"]) for e in g.causes("r:single_20260101")}
        self.assertIn(("source", "docs/evidence/run1/result.json", "typed", "alias"), causes)
        self.assertIn(("run", "20260101T000000Z", "typed", "alias"), causes)
        self.assertIn(("code", "abcdef1", "typed", "alias"), causes)
        com = {(e["rel"], e["ref"], e["via"]) for e in g.causes("r:community/0")}
        self.assertIn(("control", "none:community-report", "default"), com)
        self.assertTrue(all(e["external"] for e in g.causes("r:community/0") if e["rel"] == "code"))

    def test_control_only_for_scores(self):
        reqs = causal.requirements(self.load())
        self.assertNotIn("control", reqs["r:checks/1"]["missing"])        # a count, no score
        self.assertNotIn("control", reqs["r:checks/0"]["missing"])        # auc_reversed is its control
        self.assertEqual(reqs["r:community/0"]["missing"], [])            # section defaults, never written

    def test_transitive_satisfaction_through_a_record(self):
        rec = run_record("20260102T000000Z", ["control sha256:" + SHA_A, "prereg none:development"])
        write(self.root, "docs/causal/runs/20260102T000000Z.json", rec)
        data = self.results()
        data["checks"].append({"id": "checks/t", "auc": 0.7, "source": "docs/logs/2026-01-01-note.md",
                               "causal": ["run 20260102T000000Z", "prereg none:development"]})
        self.set_results(data)
        commit(self.root)
        g = self.load()
        req = causal.requirements(g)["r:checks/t"]
        self.assertEqual(req["missing"], [])
        self.assertIn("control sha256:", req["met"]["control"])           # inherited from the record
        self.assertIn(" > ", req["met"]["code"])
        shown = causal.show(g, "r:checks/t")["requirements"]
        self.assertEqual(shown["control"]["status"], "met")

    def test_hint_edges_never_satisfy(self):
        data = self.results()
        data["checks"].append({"id": "checks/h", "what": "x", "source": "docs/logs/2026-01-01-note.md",
                               "measured_by": "app ap-ABCDEFGHIJKLMNOPQRSTUV"})
        self.set_results(data)
        g = self.load()
        self.assertIn("run", causal.requirements(g)["r:checks/h"]["missing"])
        sug = causal.gaps(g, suggest=True)
        row = next(r for r in sug["gaps"] if r["node"] == "r:checks/h")
        self.assertTrue(row["suggest"] and row["suggest"][0]["weak"])

    def test_record_shapes_join(self):
        write(self.root, "docs/evidence/run1/driver.json", {"token": "20260101T000000Z", "commit": "abcdef2"})
        data = self.results()
        data["checks"].append({"id": "checks/r", "what": "x", "evidence": "docs/evidence/run1/"})
        self.set_results(data)
        commit(self.root)
        g = self.load()
        causes = {(e["rel"], e["cause"], e["via"]) for e in g.causes("r:checks/r")}
        self.assertIn(("run", "docs/evidence/run1/driver.json", "join"), causes)
        req = causal.requirements(g)["r:checks/r"]
        self.assertNotIn("run", req["missing"])
        self.assertNotIn("code", req["missing"])
        write(self.root, "docs/evidence/run1/launch.json", {"token": "20260101T000001Z"})
        commit(self.root)
        g = self.load()
        self.assertTrue(any("2 records" in a for a in g.ambiguous))         # never joined on two candidates

    def test_decisions_tokens_and_why(self):
        g = self.load()
        self.assertIn(("supersedes", "D1"), {(e["rel"], e["cause"]) for e in g.causes("D2")})
        out = causal.why(g, "r:single_20260101")
        self.assertIn("run", out["causes"])
        eff = causal.effects(g, "D1")
        self.assertEqual(eff["superseded_by"][0]["node"], "D2")
        with self.assertRaises(causal.CausalError) as cm:
            causal.resolve(g, "2026-01-02 row")
        self.assertEqual(cm.exception.candidates, ["D2", "D3"])

    def test_tool_page_tokens(self):
        write(self.root, "docs/tools/x.md", "# x: a tool\n\nSummary.\n\n## Related\n\n- r:checks/0 is its number\n")
        g = self.load()
        if "tool:x" in g.nodes:                                       # pages load only when kit.tooldocs parses them
            self.assertIn(("source", "r:checks/0", "token"),
                          {(e["rel"], e["cause"], e["via"]) for e in g.causes("tool:x")})


class RatchetTest(Fixture):
    def test_no_baseline_skips_the_ratchet(self):
        rep = self.check()
        self.assertNotIn("E10", self.rules(rep))

    def test_new_unlinked_result_fails_and_linked_passes(self):
        self.cutover()
        data = self.results()
        data["checks"].append({"id": "checks/new", "auc": 0.7, "source": "docs/logs/2026-01-01-note.md"})
        self.set_results(data)
        self.assertIn("E10", self.rules(self.check()))                    # an AUC with no control: must fail
        data["checks"][-1] = linked_row()
        self.set_results(data)
        self.assertEqual(self.rules(self.check()), [])

    def test_new_row_without_id(self):
        self.cutover()
        data = self.results()
        data["checks"].append({k: v for k, v in linked_row().items() if k != "id"})
        self.set_results(data)
        self.assertIn("E2", self.rules(self.check()))

    def test_old_rows_stay_old_when_edited_or_moved(self):
        self.cutover()
        data = self.results()
        data["checks"].reverse()
        self.set_results(data)
        self.assertEqual(self.rules(self.check()), [])                     # moved: matched by unit_sha256
        data["checks"].reverse()
        data["checks"][1]["note"] = "edited in place"
        self.set_results(data)
        self.assertEqual(self.rules(self.check()), [])                     # edited: matched by position

    def test_grown_baseline_fails(self):
        self.cutover()
        b = json.loads((self.root / causal.BASELINE).read_text())
        b["gaps"]["r:invented"] = ["run"]
        write(self.root, causal.BASELINE, json.dumps(b, indent=1, sort_keys=True) + "\n")
        self.assertIn("E11", self.rules(self.check()))
        b = json.loads((self.root / causal.BASELINE).read_text())
        del b["gaps"]["r:invented"]
        b["initial"]["gaps"]["r:invented"] = ["run"]
        write(self.root, causal.BASELINE, json.dumps(b, indent=1, sort_keys=True) + "\n")
        self.assertIn("E11", self.rules(self.check()))                    # initial no longer matches its hash

    def test_pins_in_the_test(self):
        out = self.cutover()
        rep = self.check(pinned_sha=out["initial_sha256"], pinned_max=out["counts"]["pairs"])
        self.assertNotIn("E11", self.rules(rep))
        rep = self.check(pinned_sha="0" * 64, pinned_max=0)
        self.assertIn("E11", self.rules(rep))

    def test_ratchet_shrinks_and_repin_needs_a_reason(self):
        self.cutover()
        data = self.results()
        data["checks"][1]["causal"] = ["run none:no-compute", "prereg none:not-a-readout"]
        self.set_results(data)
        self.assertIn("A8", self.rules(self.check(), "attention"))
        out = causal.ratchet(self.root, write=True)
        self.assertIn("r:checks/1", out["dropped"])
        with self.assertRaises(causal.CausalError):
            causal.ratchet(self.root, repin=True)
        out = causal.ratchet(self.root, repin=True, reason="test", write=True)
        self.assertTrue(out["repinned"])
        self.assertEqual(json.loads((self.root / causal.BASELINE).read_text())["repins"][0]["reason"], "test")


class RuleTest(Fixture):
    def test_structured_rules_fail(self):
        self.cutover()
        data = self.results()
        bad = [("E3", "source r:nope"), ("E4", "source docs/missing.md"), ("E4", "input work/x.json"),
               ("E6", "spec docs/logs/2026-01-01-note.md"), ("E7", "control field:nope"),
               ("E5", f"source docs/logs/2026-01-01-note.md sha256:{SHA_A}")]
        for rule, line in bad:
            data["checks"].append(linked_row(id=f"checks/{rule.lower()}", causal=linked_row()["causal"] + [line]))
        self.set_results(data)
        rep = self.check()
        for rule, line in bad:
            with self.subTest(rule=rule):
                self.assertIn(rule, self.rules(rep))

    def test_public_leak(self):
        data = self.results()
        data["checks"].append(linked_row(causal=linked_row()["causal"] + ["approval approval:x"]))
        self.set_results(data)
        self.assertIn("E9", self.rules(self.check(public=True)))
        self.assertNotIn("E9", self.rules(self.check(public=False)))

    def test_supersession_family_and_cycle(self):
        data = self.results()
        data["checks"].append(linked_row(id="checks/a", causal=linked_row()["causal"] + ["corrects r:checks/b"]))
        data["checks"].append(linked_row(id="checks/b", causal=linked_row()["causal"] + ["corrects r:checks/a"]))
        data["checks"].append(linked_row(id="checks/c", causal=linked_row()["causal"] + ["supersedes D1"]))
        self.set_results(data)
        rep = self.check()
        texts = [f["text"] for f in rep["findings"] if f["rule"] == "E8"]
        self.assertTrue(any("cycle" in t for t in texts))
        self.assertTrue(any("one family" in t for t in texts))

    def test_new_spec_and_frozen_prereg(self):
        self.cutover()
        write(self.root, "docs/compute/modal-specs/2026-01-03-new.md", "# New spec\n")
        commit(self.root)
        self.assertIn("E10", self.rules(self.check()))
        write(self.root, "docs/compute/modal-specs/2026-01-03-new.md", "# New spec\n\n```causal\ndecision D2\n```\n")
        self.assertEqual(self.rules(self.check()), [])
        write(self.root, "docs/prereg/2026-01-03-new.md", "# New rule\n")
        commit(self.root)
        self.assertIn("E10", self.rules(self.check()))
        out = causal.link(self.root, "docs/prereg/2026-01-03-new.md", "decision D3", basis="docs/DECISIONS.md:7")
        self.assertTrue(out["written"])
        self.assertEqual(self.rules(self.check()), [])

    def test_claims_pin_and_repin(self):
        self.cutover()
        out = causal.add_claim(self.root, 1, "A first finding about counts", "Model output", ["r:checks/1"],
                               write=True)
        self.assertEqual(out["claim"], "c:a-first-finding-about-counts")
        self.assertEqual(self.rules(self.check()), [])
        data = self.results()
        data["checks"][1]["what"] = "a different count"                    # an edited number under a pinned claim
        self.set_results(data)
        rep = self.check()
        self.assertIn("E17", self.rules(rep))
        self.assertTrue(any("--repin" in f["text"] for f in rep["findings"] if f["rule"] == "E17"))
        rp = causal.add_claim(self.root, repin="c:a-first-finding-about-counts", write=True)
        self.assertEqual(len(rp["changes"]), 1)
        self.assertNotIn("E17", self.rules(self.check()))

    def test_claim_bad_quote_label_and_external_only(self):
        with self.assertRaises(causal.CausalError):
            causal.add_claim(self.root, 1, "not in the item", "Model output", ["r:checks/1"])
        with self.assertRaises(causal.CausalError):
            causal.add_claim(self.root, 1, "A first finding about counts", "Opinion", ["r:checks/1"])
        write(self.root, causal.CLAIMS, {"schema": causal.CLAIMS_SCHEMA, "claims": [
            {"id": "ext", "readme_item": 1, "quote": "A first finding about counts", "label": "Model output",
             "causal": [f"source r:community/0 sha256:{causal.unit_sha256(self.results()['community'][0])}"]}]})
        rep = self.check()
        self.assertTrue(any("may not rest only" in f["text"] for f in rep["findings"] if f["rule"] == "E17"))

    def test_new_finding_needs_a_claim(self):
        self.cutover()
        text = (self.root / "README.md").read_text().replace("## Other", "- **A third finding**.\n\n## Other")
        write(self.root, "README.md", text)
        self.assertIn("E17", self.rules(self.check()))

    def test_runner_script_helper(self):
        write(self.root, "scripts/old_job.py", "import modal\napp = modal.App('x')\n")
        commit(self.root)
        self.cutover()
        self.assertEqual(self.rules(self.check()), [])                     # old runners sit in the baseline
        write(self.root, "scripts/new_job.py", "import modal\napp = modal.App('y')\n")
        commit(self.root)
        self.assertIn("E14", self.rules(self.check()))
        write(self.root, "scripts/new_job.py", "# causal: exempt library\nimport modal\napp = modal.App('y')\n")
        self.assertEqual(self.rules(self.check()), [])
        write(self.root, "scripts/new_job.py", "# causal: exempt because\nimport modal\napp = modal.App('y')\n")
        self.assertIn("E14", self.rules(self.check()))
        write(self.root, "scripts/new_job.py", "from kit import runrecord\nimport modal\napp = modal.App('y')\n")
        self.assertEqual(self.rules(self.check()), [])

    def test_new_evidence_folder_needs_a_record(self):
        self.cutover()
        write(self.root, "docs/evidence/run9/out.txt", "x\n")
        commit(self.root)
        self.assertIn("E10", self.rules(self.check()))
        write(self.root, "docs/evidence/run9/run.json", {"token": "20260109T000000Z", "commit": "abcdef3"})
        commit(self.root)
        self.assertNotIn("E10", self.rules(self.check()))

    def test_record_agreement_and_a10(self):
        rec = run_record("20260102T000000Z", ["prereg none:development"], commit_sha="1111111")
        write(self.root, "docs/causal/runs/20260102T000000Z.json", rec)
        data = self.results()
        data["checks"].append(linked_row(id="checks/e16", causal=linked_row()["causal"][1:] + [
            "run 20260102T000000Z", "code 2222222"]))
        self.set_results(data)
        commit(self.root)
        self.assertIn("E16", self.rules(self.check()))
        write(self.root, "docs/causal/runs/20260103T000000Z.json", run_record("20260103T000000Z"))
        self.assertIn("A10", self.rules(self.check(), "attention"))

    def test_history_bullet_after_cutover(self):
        self.cutover()
        g = self.load()
        g.history.append({"tool": "tool:x", "date": "2999-01-01", "line": 1, "where": "docs/tools/x.md:1",
                          "text": "- 2999-01-01: measured AUC 0.7 (`abcdef1`)"})
        self.assertIn("E10", self.rules(causal.check(self.root, graph=g, public=False)))

    def test_exit_codes(self):
        rep = self.check()
        self.assertEqual(rep["errors"], 0)
        self.assertEqual(rep["exit"], causal.EXIT_ATTENTION)               # A2: the fixture's commit is not in git
        self.assertEqual(self.check(strict=True)["exit"], causal.EXIT_FAIL)
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.assertEqual(causal.check(empty, public=True)["exit"], causal.EXIT_SKIPPED)


class WriterTest(Fixture):
    def test_link_retract_by_sha8_and_alias(self):
        out = causal.link(self.root, "docs/prereg/2026-01-01-rule.md", "decision D2", basis="review")
        sha8 = out["sha8"]
        g = self.load()
        self.assertIn(("decision", "D2", "overlay"),
                      {(e["rel"], e["cause"], e["via"]) for e in g.causes("docs/prereg/2026-01-01-rule.md")})
        with self.assertRaises(causal.CausalError):
            causal.link(self.root, "docs/prereg/2026-01-01-rule.md", "decision D2", basis="review")
        with self.assertRaises(causal.CausalError):
            causal.link(self.root, retract="00000000", reason="x")
        causal.link(self.root, retract=sha8, reason="wrong row")
        g = self.load()
        self.assertNotIn("D2", {e["cause"] for e in g.causes("docs/prereg/2026-01-01-rule.md")})
        causal.link(self.root, alias=("r:old", "r:checks/0"), basis="review")
        self.assertEqual(self.load().aliases["r:old"], "r:checks/0")

    def test_link_refusals(self):
        with self.assertRaises(causal.CausalError):
            causal.link(self.root, "r:checks/0", "decision D1", basis="review")      # has its own slot
        with self.assertRaises(causal.CausalError):
            causal.link(self.root, "docs/prereg/2026-01-01-rule.md", "approval approval:x", basis="r",
                        public=True)

    def test_frozen_guard(self):
        for rel in ("docs/evidence/run1/x.json", "docs/prereg/2026-01-01-rule.md", "docs/logs/x.md",
                    "docs/HANDOFF.md", "docs/pinned.md", "archive/x"):
            with self.subTest(rel=rel):
                with self.assertRaises(causal.CausalError):
                    causal._write_text(self.root, rel, "x")

    def test_backfill_passes_are_bounded_and_recorded(self):
        out = causal.backfill(self.root, "ids")
        self.assertEqual(len(out["changes"]), 3)
        with self.assertRaises(causal.CausalError):
            causal.backfill(self.root, "ids", write=True)                         # no baseline yet
        self.cutover()
        out = causal.backfill(self.root, "ids", write=True, limit=1)
        self.assertEqual(len(out["changes"]), 1)
        self.assertEqual(self.results()["checks"][0]["id"], "checks/0")
        again = causal.backfill(self.root, "ids")
        self.assertEqual(again["exit"], causal.EXIT_ATTENTION)
        with self.assertRaises(causal.CausalError):
            causal.backfill(self.root, "ids", again=True)
        out = causal.backfill(self.root, "ids", again=True, reason="finish", write=True)
        self.assertEqual(len(out["changes"]), 2)
        passes = json.loads((self.root / causal.BASELINE).read_text())["passes"]
        self.assertEqual(passes["ids"]["reason"], "finish")
        self.assertEqual(self.rules(self.check()), [])                           # ids keep units old
        with self.assertRaises(causal.CausalError):
            causal.backfill(self.root, "everything")

    def test_decision_ids_and_claims_passes(self):
        self.cutover()
        causal.backfill(self.root, "decision-ids", write=True)
        text = (self.root / causal.DECISIONS).read_text()
        self.assertIn("| Id | Date | Decision |", text)
        self.assertIn("| D3 | 2026-01-02 |", text)
        out = causal.backfill(self.root, "claims", write=True)
        self.assertEqual(len(out["changes"]), 1)                                 # the item with a label and evidence
        self.assertEqual(len(out["review"]), 1)
        self.assertNotIn("E17", self.rules(self.check()))

    def test_add_result_adopts_the_record(self):
        rec = run_record("20260104T000000Z", ["prereg none:development", "control sha256:" + SHA_A])
        write(self.root, "work/causal/runs/20260104T000000Z.json", rec)
        self.cutover()
        data = self.results()
        data["checks"].append({"auc": 0.7, "source": "docs/logs/2026-01-01-note.md"})
        self.set_results(data)
        out = causal.add_result(self.root, "checks", "20260104T000000Z", write=True)
        self.assertEqual(out["adopted"], "docs/causal/runs/20260104T000000Z.json")
        row = self.results()["checks"][-1]
        self.assertEqual(row["id"], "checks/2")
        self.assertIn("run 20260104T000000Z", row["causal"])
        self.assertEqual(self.rules(self.check()), [])


class CliTest(Fixture):
    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = causal.main(list(argv) + ["--root", str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def test_commands(self):
        code, out, _ = self.cli("gaps", "--counts", "--json")
        self.assertEqual(code, 0)
        self.assertIn("none_lines", json.loads(out)["counts"])
        code, out, _ = self.cli("why", "2026-01-02 row")
        self.assertEqual(code, causal.EXIT_ATTENTION)
        self.assertIn("D3", out)
        code, out, _ = self.cli("show", "r:single_20260101", "--json")
        self.assertEqual(json.loads(out)["kind"], "result")
        code, out, _ = self.cli("effects", "D1")
        self.assertEqual(code, 0)
        code, out, _ = self.cli("effects", "--since", "HEAD")
        self.assertEqual(code, 0)
        code, out, _ = self.cli("check", "--no-hash", "--json")
        self.assertEqual(json.loads(out)["errors"], 0)
        code, out, _ = self.cli("backfill", "--pass", "ids")
        self.assertEqual(code, 0)
        code, out, err = self.cli("add", "result")
        self.assertEqual(code, causal.EXIT_USAGE)

    def test_parse_cli(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(causal.main(["parse", "run none:pending", "--json"]), 0)
        self.assertIn("no-compute", json.loads(out.getvalue())["none_reasons"])
        with redirect_stderr(io.StringIO()):
            self.assertEqual(causal.main(["parse", "model x"]), causal.EXIT_FAIL)


if __name__ == "__main__":
    unittest.main()
