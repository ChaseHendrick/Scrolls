import random
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "letters"))
    import eval_p1667_text as E
except ImportError:  # pragma: no cover
    np = None


@unittest.skipIf(np is None, "needs numpy")
class TextScoreTest(unittest.TestCase):
    def test_vector_alignment_matches_plain_dynamic_programming(self):
        rng = random.Random(0)
        abc = "ΑΒΓΔΕ"
        reads = ["".join(rng.choice(abc) for _ in range(rng.randint(0, 25))) for _ in range(40)]
        refs = ["".join(rng.choice(abc + "?") for _ in range(rng.randint(1, 18))) for _ in range(30)]
        S = E.local_scores(reads, refs)
        for i, a in enumerate(reads):
            for j, b in enumerate(refs):
                self.assertEqual(int(S[i, j]), E.naive_local(a, b), (a, b))

    def test_scores(self):
        S = E.local_scores(["ΚΑΙΤΗΝ", "ΚΑΤΗΝ", "ΚΑΙ"], ["ΧΧΚΑΙΤΗΝΧΧ", "Κ??ΤΗΝ"])
        self.assertEqual(S.tolist(), [[6, 4], [4, 3], [3, 1]])

    def test_decoys_keep_the_reference_shape(self):
        ref = {"columns": {"5": [{"line": 1, "letters": ""}, {"line": 2, "letters": "??ΑΒΓ?Δ"}],
                           "6": [{"line": 1, "letters": "ΕΖ?"}]}}
        corpus = "".join(random.Random(1).choice(E.ALPHABET) for _ in range(500))
        d = E.make_decoys(ref, corpus, n=5, seed=0)
        self.assertEqual(d["real"], ["??ΑΒΓ?Δ", "ΕΖ?"])
        self.assertEqual(d["lines"], [["5", 2], ["6", 1]])
        for t in d["corpus"] + d["shuffled"]:
            self.assertEqual([len(s) for s in t], [7, 3])
            self.assertEqual([[k for k, ch in enumerate(s) if ch == "?"] for s in t], [[0, 1, 5], [2]])
        for t in d["shuffled"]:
            self.assertEqual(sorted(c for s in t for c in s if c != "?"), sorted("ΑΒΓΔΕΖ"))

    def test_word_decoys_keep_words_whole(self):
        lines = [("ΚΑΙΤΗΝ??Α", "100100100"), ("ΤΟΝΔΕ", "10010")]
        self.assertEqual(E.word_chunks(lines), ["ΚΑΙ", "ΤΗΝ", "Α", "ΤΟΝ", "ΔΕ"])
        ref = {"columns": {"1": [{"line": 1, "letters": "ΚΑΙΤΗΝ??Α", "word_starts": "100100100"},
                                 {"line": 2, "letters": "ΤΟΝΔΕ", "word_starts": "10010"}]}}
        d = E.make_decoys(ref, "Α" * 200, n=4, seed=0)
        for t in d["words"]:
            self.assertEqual(t[0][6:8], "??")
            joined = "".join(t).replace("?", "")
            self.assertEqual(sorted(joined), sorted("ΚΑΙΤΗΝΑΤΟΝΔΕ"))
            self.assertIn("ΤΟΝ", joined)

    def test_real_text_beats_decoys_when_reads_carry_it(self):
        rng = random.Random(2)
        lines = ["".join(rng.choice(E.ALPHABET) for _ in range(15)) for _ in range(20)]
        ref = {"columns": {"1": [{"line": i + 1, "letters": s} for i, s in enumerate(lines)]}}
        corpus = "".join(rng.choice(E.ALPHABET) for _ in range(40000))
        d = E.make_decoys(ref, corpus, n=19, seed=0)
        noisy = ["".join(c if rng.random() < 0.7 else rng.choice(E.ALPHABET) for c in s) for s in lines[:8]]
        read = {"weights": "w", "letter_px": 86, "control": {"passes": True},
                "segments": {"wA": {"lines": [{"read": s, "column": 0} for s in noisy]}}}
        res = E.score(read, d)
        self.assertGreaterEqual(res["summary"]["pairs_real"], 4)
        self.assertEqual(res["summary"]["p_pairs_words"], 0.05)
        self.assertTrue(res["summary"]["pairs_pass"])
        self.assertEqual(sum(s["pairs"] for s in res["segments"].values()), res["summary"]["pairs_real"])
        self.assertEqual(res["summary"]["p_corpus"], 0.05)
        self.assertEqual(res["summary"]["p_shuffled"], 0.05)
        self.assertEqual(res["summary"]["p_words"], 0.05)
        junk = {"weights": "w", "letter_px": 86, "control": {"passes": True},
                "segments": {"wA": {"lines": [{"read": "".join(rng.choice(E.ALPHABET) for _ in range(15))}
                                              for _ in range(8)]}}}
        js = E.score(junk, d)["summary"]
        self.assertGreater(js["p_corpus"], 0.05)
        self.assertFalse(js["pairs_pass"])

    def test_compare_counts_pairs_per_segment(self):
        A = {"segments": {"a": {"pairs": 0, "excess": 1.0}, "b": {"pairs": 1, "excess": 0.0}}}
        B = {"segments": {"a": {"pairs": 3, "excess": 2.0}, "b": {"pairs": 4, "excess": 1.0}}}
        c = E.compare(A, B, n=200)
        self.assertEqual(c["pairs"]["diff_b_minus_a"], 6.0)
        self.assertGreater(c["pairs"]["ci95"][0], 0)
        self.assertEqual(c["excess"]["diff_b_minus_a"], 2.0)


if __name__ == "__main__":
    unittest.main()
