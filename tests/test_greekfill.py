"""Tests for the Greek gap restoration benchmark (kit/greekfill.py) and its letter model (kit/greekkn.py)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "greek-restoration-20261022"

try:
    import numpy as np
    from kit import greekfill as g
    from kit import greekkn as tl
    HAVE_NP = True
except ImportError:  # numpy missing
    HAVE_NP = False

TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>
</fileDesc></teiHeader><text><body><div><p>τὸν δὲ λό-
γον <note>σχόλιον</note>οὐκ ἔχει [μουσι]κὴ περὶ τῶν ἠθῶν . . . καὶ ταῦτα μὲν οὕτως.</p>
<p>{BODY}</p></div></body></text></TEI>
"""


@unittest.skipUnless(HAVE_NP, "numpy needed")
class GreekFillTest(unittest.TestCase):
    def test_normalise_reply(self):
        self.assertEqual(g.normalise_reply(" λόγος "), "ΛΟΓΟϹ")
        self.assertEqual(g.normalise_reply("ΣΩΜΑ, ok"), "ϹΩΜΑ")
        self.assertEqual(g.normalise_reply(""), "")

    def test_letter_hits_positionwise(self):
        self.assertEqual(g.letter_hits("ΑΒΓ", "ΑΒΓ"), 3)
        self.assertEqual(g.letter_hits("ΒΓ", "ΑΒΓ"), 0)
        self.assertEqual(g.letter_hits("ΑΒΓΔΕ", "ΑΒΓ"), 3)

    def test_items_hide_exact_letters(self):
        rng = np.random.default_rng(1)
        text = ("ΤΟΝ ΔΕ ΛΟΓΟΝ ΟΥΚ ΕΧΕΙ ΜΟΥϹΙΚΗ ΠΕΡΙ ΤΩΝ ΗΘΩΝ " * 900).strip()
        gaps, memos = g.make_items(text, rng)
        self.assertEqual(len(gaps), g.PER_LEN * len(g.GAP_LENS))
        self.assertEqual(len(memos), g.MEMO_N)
        for it in gaps:
            self.assertEqual(len(it["truth"]), it["L"])
            self.assertNotIn("[", it["left"] + it["right"])
            self.assertIn("[%d]" % it["L"], g.gap_prompt(it))
        self.assertTrue(all(30 <= len(m["truth"]) <= g.MEMO_LETTERS for m in memos))
        self.assertTrue(all(len(it["left"]) + it["L"] + len(it["right"]) <= g.WINDOW for it in gaps))

    def test_verdict_rules(self):
        good = {"parsed_share": 1.0, "diff": 0.10, "diff_lower": 0.02, "memo_acc": 0.1}
        self.assertEqual(g.verdict({"a": good})[0], "PASS")
        self.assertEqual(g.verdict({"a": dict(good, memo_acc=0.6)})[0], "INCONCLUSIVE")
        self.assertEqual(g.verdict({"a": dict(good, diff=0.03)})[0], "FAIL")
        self.assertEqual(g.verdict({"a": dict(good, diff_lower=-0.01)})[0], "FAIL")
        self.assertEqual(g.verdict({"a": dict(good, parsed_share=0.5)})[0], "VOID")

    def test_boot_lower_sign(self):
        lo = g.boot_lower([0.2] * 50 + [0.0] * 50, [1] * 100, 0.01, 2000, 0)
        self.assertGreater(lo, 0.0)
        lo = g.boot_lower([0.1, -0.1] * 50, [1] * 100, 0.01, 2000, 0)
        self.assertLess(lo, 0.0)

    def test_kn_fill_recovers_repeated_text(self):
        text = "ΤΟΝ ΔΕ ΛΟΓΟΝ ΟΥΚ ΕΧΕΙ ΜΟΥϹΙΚΗ ΠΕΡΙ ΤΩΝ ΗΘΩΝ "
        lm = tl.MixtureLM([tl.NgramLM(tl.KNModel(5).fit_texts([text * 50]))], [1.0])
        self.assertEqual(g.kn_fill(lm, "ΤΟΝ ΔΕ ΛΟ", "ΟΝ ΟΥΚ ΕΧΕΙ", 1), "Γ")
        self.assertEqual(g.kn_fill(lm, "ΤΟΝ ΔΕ ΛΟ", " ΟΥΚ ΕΧΕΙ", 3), "ΓΟΝ")
        self.assertEqual(g.kn_continue(lm, "ΤΟΝ ΔΕ ΛΟΓΟΝ ΟΥΚ", 5), "ΕΧΕΙΜ")

    def test_test_text_is_second_half_of_de_musica(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "c.tsv")
            p.write_text("tlg0001.tlg001.x\tΑΒΓ\ntlg1595.tlg221.1st1K-grc1\tΑΑ ΒΒ ΓΓ ΔΔ\n", encoding="utf-8")
            self.assertEqual(g.test_text(p), "ΒΒ ΓΓ ΔΔ")  # cut at the last space before the middle
            p.write_text("tlg0001.tlg001.x\tΑΒΓ\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                g.test_text(p)


@unittest.skipUnless(HAVE_NP, "numpy needed")
class LetterModelTest(unittest.TestCase):
    def test_next_letter_distribution_sums_to_one(self):
        m = tl.KNModel(4).fit_texts(["ΤΟΝ ΔΕ ΛΟΓΟΝ ΟΥΚ ΕΧΕΙ " * 20, "ΠΕΡΙ ΜΟΥϹΙΚΗϹ"])
        lp = tl.NgramLM(m).next_logprobs(["   ΤΟΝ", "   ΞΨ"])
        self.assertEqual(lp.shape, (2, tl.V))
        np.testing.assert_allclose(np.exp(lp).sum(1), 1.0, atol=1e-9)

    def test_mixture_and_save_load(self):
        a = tl.KNModel(3).fit_texts(["ΑΒΓ ΑΒΓ ΑΒΓ"])
        b = tl.KNModel(3).fit_texts(["ΔΕΖ ΔΕΖ"])
        with tempfile.TemporaryDirectory() as d:
            a.save(Path(d, "a.npz"))
            a2 = tl.KNModel.load(Path(d, "a.npz"))
        self.assertAlmostEqual(tl.NgramLM(a).score("ΑΒΓ"), tl.NgramLM(a2).score("ΑΒΓ"))
        mix = tl.MixtureLM([tl.NgramLM(a), tl.NgramLM(b)], [0.5, 0.5])
        self.assertGreater(mix.score("ΑΒΓ"), tl.NgramLM(b).score("ΑΒΓ"))
        self.assertGreater(tl.NgramLM(a).score("ΑΒΓ"), mix.score("ΑΒΓ"))

    def test_corpus_builder_normalises_tei(self):
        long = "καὶ ταῦτα μὲν οὕτως ἔχει " * 12
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "src", "tlg9999", "tlg001")
            src.mkdir(parents=True)
            (src / "tlg9999.tlg001.test-grc1.xml").write_text(TEI.replace("{BODY}", long), encoding="utf-8")
            (src / "tlg9999.tlg002.test-grc1.xml").write_text(TEI.replace("{BODY}", ""), encoding="utf-8")
            (src / "broken-grc1.xml").write_text("<TEI><body>", encoding="utf-8")
            stats = tl.build_corpus(Path(d, "c.tsv"), [Path(d, "src")], nproc=1)
            lines = Path(d, "c.tsv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(stats["files"], 3)
        self.assertEqual(stats["kept"], 1)  # the short document and the broken file are left out
        docid, text = lines[0].split("\t")
        self.assertEqual(docid, "tlg9999.tlg001.test-grc1")
        self.assertTrue(text.startswith("ΤΟΝ ΔΕ ΛΟΓΟΝ ΟΥΚ ΕΧΕΙ ΜΟΥϹΙΚΗ ΠΕΡΙ ΤΩΝ ΗΘΩΝ ΚΑΙ ΤΑΥΤΑ"))
        self.assertNotIn("ϹΧΟΛΙΟΝ", text)  # <note> dropped
        self.assertEqual(set(text) - set(tl.ALPHABET), {" "})


@unittest.skipUnless(HAVE_NP, "numpy needed")
class FrozenEvidenceTest(unittest.TestCase):
    def test_pins_match(self):
        res = g.check_pins(EVIDENCE)
        self.assertTrue(res["ok"], res)
        self.assertTrue(all(f["match"] for f in res["files"].values()))

    def test_check_fails_on_a_changed_file(self):
        with tempfile.TemporaryDirectory() as d:
            for n in g.PINS:
                shutil.copy(EVIDENCE / n, Path(d, n))
            with open(Path(d, "baseline.json"), "a", encoding="utf-8") as f:
                f.write(" ")
            self.assertFalse(g.check_pins(d)["ok"])
            self.assertEqual(g.main(["check", d]), 1)
            Path(d, "key.json").unlink()
            self.assertFalse(g.check_pins(d)["files"]["key.json"]["present"])

    def test_score_reproduces_frozen_score_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            res = g.score(EVIDENCE, Path(d, "score.json"))
            self.assertEqual(Path(d, "score.json").read_bytes(), (EVIDENCE / "score.json").read_bytes())
        self.assertEqual(res["verdict"], "FAIL")
        self.assertEqual(res["kn"]["letter_acc"], 0.331)
        self.assertEqual(res["replies"], 690)

    def test_score_moves_when_a_reply_changes(self):
        # control: the reproduction is not a constant; one reply set to the truth raises that model's score
        key = json.loads((EVIDENCE / "key.json").read_text(encoding="utf-8"))
        truth = {x["id"]: x["truth"] for x in key["gaps"]}
        model = "Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra"
        with tempfile.TemporaryDirectory() as d:
            for n in ("manifest.json", "key.json", "baseline.json"):
                shutil.copy(EVIDENCE / n, Path(d, n))
            rows = [json.loads(x) for x in (EVIDENCE / "replies.jsonl").read_text(encoding="utf-8").splitlines()]
            for r in rows:
                m, item = r["id"].split("|")
                if m == model and item in truth:
                    r["reply"] = truth[item]
            Path(d, "replies.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                                encoding="utf-8")
            res = g.score(d)
        self.assertEqual(res["per_model"][model]["letter_acc"], 1.0)
        self.assertEqual(res["verdict"], "PASS")


@unittest.skipUnless(HAVE_NP, "numpy needed")
class TextRunnerTest(unittest.TestCase):
    def test_priced_and_body(self):
        m = {"models": {"x:p": {"input": 1.0, "output": 2.0}}, "per_call_worst_usd": 0.5, "max_tokens": 9}
        self.assertAlmostEqual(g.priced(m, "x:p", {"prompt_tokens": 1000, "completion_tokens": 10}), 0.00102)
        self.assertEqual(g.priced(m, "x:p", {}), 0.5)
        b = g.body(m, {"model": "x:p", "prompt": "hi"})
        self.assertEqual(b["model"], "x:p")
        self.assertEqual(b["max_tokens"], 9)
        self.assertEqual(b["temperature"], 0)

    def _manifest(self, d, cap=1.0):
        man = {"models": {"a": {"input": 1, "output": 1}, "b": {"input": 1, "output": 1}},
               "max_tokens": 4, "per_call_worst_usd": 0.01, "cap_usd": cap,
               "requests": [{"id": i, "model": mo, "prompt": "p"} for i, mo in
                            (("1", "a"), ("2", "a"), ("3", "b"), ("4", "b"))]}
        Path(d, "manifest.json").write_text(json.dumps(man))
        Path(d, "replies.jsonl").write_text(json.dumps({"id": "1", "reply": "x", "usd": 0.0}) + "\n")

    def test_per_model_and_resume_without_network(self):
        orig = (g.token, g.send)
        try:
            with tempfile.TemporaryDirectory() as d:
                self._manifest(d)
                calls = []
                g.token = lambda: "t"
                g.send = lambda payload, tok: (calls.append(payload["model"]) or
                                               {"choices": [{"message": {"content": "Α"}}], "usage": {}}, None)
                res = g.run(d, per_model=1)
                self.assertEqual(calls, ["a", "b"])
                self.assertIsNone(res["stopped"])
                ids = [json.loads(x)["id"] for x in Path(d, "replies.jsonl").read_text().splitlines()]
                self.assertEqual(ids, ["1", "2", "3"])
        finally:
            g.token, g.send = orig

    def test_cap_and_failure_stop(self):
        orig = (g.token, g.send)
        try:
            with tempfile.TemporaryDirectory() as d:
                self._manifest(d, cap=0.015)
                g.token = lambda: "t"
                g.send = lambda payload, tok: ({"choices": [{"message": {"content": "Α"}}], "usage": {}}, None)
                res = g.run(d)
                self.assertEqual((res["sent"], res["stopped"]), (1, "cap"))
            with tempfile.TemporaryDirectory() as d:
                self._manifest(d)
                g.send = lambda payload, tok: (None, "HTTP 400")
                self.assertEqual(g.main(["run", d]), 3)
        finally:
            g.token, g.send = orig

    def test_dry_run_sends_nothing(self):
        orig = (g.token, g.send)
        try:
            with tempfile.TemporaryDirectory() as d:
                self._manifest(d, cap=0.035)
                g.token = g.send = None  # any call would raise
                res = g.run(d, dry_run=True)
                self.assertEqual(res["would_send"], 3)
                self.assertTrue(res["fits_cap"])
                self.assertEqual(g.main(["run", d, "--dry-run", "--per-model", "1"]), 0)
                self._manifest(d, cap=0.02)
                self.assertEqual(g.main(["run", d, "--dry-run"]), 3)
                self.assertEqual(len(Path(d, "replies.jsonl").read_text().splitlines()), 1)
        finally:
            g.token, g.send = orig


if __name__ == "__main__":
    unittest.main()
