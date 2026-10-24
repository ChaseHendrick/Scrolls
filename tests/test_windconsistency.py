import contextlib
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from kit.windconsistency import wind_check


class WindConsistencyTest(unittest.TestCase):
    def test_one_step_passes(self):
        got = wind_check([[{"a": "p0", "b": "p1", "k": 1}]])
        self.assertTrue(got["pass"])
        self.assertEqual(got["breaks"], 0)
        self.assertTrue(got["rule"])

    def test_reverse_mismatch_fails(self):
        chains = [
            [{"a": "p0", "b": "p1", "k": 1}],
            [{"a": "p1", "b": "p0", "k": 1}],
        ]
        got = wind_check(chains)
        self.assertFalse(got["pass"])
        self.assertGreater(got["breaks"], 0)

    def test_duplicate_pair_with_different_k_fails(self):
        chains = [
            [{"a": "p0", "b": "p1", "k": 1}],
            [{"a": "p0", "b": "p1", "k": 2}],
        ]
        got = wind_check(chains)
        self.assertFalse(got["pass"])
        self.assertGreater(got["breaks"], 0)

    def test_empty_fails(self):
        none = wind_check([])
        self.assertFalse(none["pass"])
        self.assertEqual(none["breaks"], 0)
        blank = wind_check([[]])
        self.assertFalse(blank["pass"])
        self.assertGreater(blank["breaks"], 0)

    def test_two_steps_that_agree_pass(self):
        chains = [[
            {"a": "p0", "b": "p1", "k": 1},
            {"a": "p0", "b": "p1", "k": 1},
        ]]
        got = wind_check(chains)
        self.assertTrue(got["pass"])
        self.assertEqual(got["breaks"], 0)

    def test_path_of_two_steps_passes(self):
        chains = [[
            {"a": "p0", "b": "p1", "k": 1},
            {"a": "p1", "b": "p2", "k": 2},
        ]]
        got = wind_check(chains)
        self.assertTrue(got["pass"])
        self.assertEqual(got["breaks"], 0)

    def test_same_pair_same_k_across_chains_passes(self):
        chains = [
            [{"a": "p0", "b": "p1", "k": 3}],
            [{"a": "p0", "b": "p1", "k": 3}],
        ]
        self.assertTrue(wind_check(chains)["pass"])

    def test_reverse_match_passes(self):
        chains = [
            [{"a": "p0", "b": "p1", "k": 2}],
            [{"a": "p1", "b": "p0", "k": -2}],
        ]
        got = wind_check(chains)
        self.assertTrue(got["pass"])
        self.assertEqual(got["breaks"], 0)

    def test_non_integer_k_fails(self):
        got = wind_check([[{"a": "p0", "b": "p1", "k": 1.5}]])
        self.assertFalse(got["pass"])
        self.assertGreater(got["breaks"], 0)

    def test_repeated_point_nonzero_fails_and_zero_passes(self):
        bad = wind_check([[{"a": "p0", "b": "p0", "k": 1}]])
        self.assertFalse(bad["pass"])
        self.assertGreater(bad["breaks"], 0)
        good = wind_check([[{"a": "p0", "b": "p0", "k": 0}]])
        self.assertTrue(good["pass"])
        self.assertEqual(good["breaks"], 0)

    def test_one_chain_stating_two_k_fails(self):
        chains = [[
            {"a": "p0", "b": "p1", "k": 1},
            {"a": "p0", "b": "p1", "k": 4},
        ]]
        self.assertFalse(wind_check(chains)["pass"])


class ClosedPathTest(unittest.TestCase):
    def test_three_step_nonzero_loop_fails(self):
        # Regression: the original pair-only checker passes all three unique pairs.
        triangle = [{"a": "p0", "b": "p1", "k": 1},
                    {"a": "p1", "b": "p2", "k": 1},
                    {"a": "p2", "b": "p0", "k": 1}]
        got = wind_check([triangle])
        self.assertFalse(got["pass"])
        self.assertGreater(got["breaks"], 0)

    def test_consistent_triangle_passes_in_any_order_or_direction(self):
        triangle = [{"a": "p0", "b": "p1", "k": 2},
                    {"a": "p1", "b": "p2", "k": -5},
                    {"a": "p2", "b": "p0", "k": 3}]
        for order in itertools.permutations(triangle):
            for reverse in itertools.product((False, True), repeat=3):
                edges = [{"a": s["b"], "b": s["a"], "k": -s["k"]} if r else dict(s)
                         for s, r in zip(order, reverse)]
                with self.subTest(edges=edges):
                    self.assertEqual(wind_check([edges])["breaks"], 0)
                    self.assertTrue(wind_check([[s] for s in edges])["pass"])

    def test_contradiction_across_chains_fails_in_any_order(self):
        steps = [{"a": "p0", "b": "p1", "k": 4},
                 {"a": "p1", "b": "p2", "k": -2},
                 {"a": "p0", "b": "p2", "k": 3}]
        for order in itertools.permutations(steps):
            with self.subTest(order=order):
                self.assertFalse(wind_check([[s] for s in order])["pass"])

    def test_longer_loop_with_consistent_and_inconsistent_closure(self):
        path = [{"a": "a", "b": "b", "k": 1}, {"a": "b", "b": "c", "k": 3},
                {"a": "c", "b": "d", "k": -2}, {"a": "d", "b": "e", "k": 4}]
        self.assertTrue(wind_check([path + [{"a": "e", "b": "a", "k": -6}]])["pass"])
        self.assertFalse(wind_check([path + [{"a": "e", "b": "a", "k": -5}]])["pass"])

    def test_disconnected_components_have_independent_origins(self):
        chains = [[{"a": "a", "b": "b", "k": 10**30}],
                  [{"a": "x", "b": "y", "k": -7}, {"a": "y", "b": "z", "k": 5},
                   {"a": "z", "b": "x", "k": 2}]]
        self.assertTrue(wind_check(chains)["pass"])
        chains[1][-1]["k"] = 3
        self.assertFalse(wind_check(chains)["pass"])

    def test_multiple_consistent_cycles_and_one_bad_constraint(self):
        graph = [{"a": "a", "b": "b", "k": 2}, {"a": "b", "b": "c", "k": 3},
                 {"a": "a", "b": "c", "k": 5}, {"a": "b", "b": "d", "k": 4},
                 {"a": "c", "b": "d", "k": 1}]
        self.assertTrue(wind_check([graph])["pass"])
        graph[-1]["k"] = 2
        self.assertFalse(wind_check([graph])["pass"])

    def test_large_loop_uses_exact_integer_counts_without_recursion(self):
        n = 2000
        path = [{"a": str(i), "b": str(i+1), "k": 1} for i in range(n)]
        path.append({"a": str(n), "b": "0", "k": -n})
        self.assertTrue(wind_check([path])["pass"])
        path[-1]["k"] += 1
        self.assertFalse(wind_check([path])["pass"])

    def test_malformed_steps_and_boolean_counts_fail(self):
        for chains in (None, {}, [None], [[None]], [[{"a": "a", "b": "b", "k": True}]],
                       [[{"a": 0, "b": "b", "k": 1}]], [[{"a": "a", "b": "b"}]]):
            with self.subTest(chains=chains):
                self.assertFalse(wind_check(chains)["pass"])


class CommandTest(unittest.TestCase):
    def test_json_cli_pass_failure_and_file_error(self):
        from kit.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chains.json"
            for closed, expected in ((-2, 0), (1, 1)):
                path.write_text(json.dumps([[{"a": "a", "b": "b", "k": 1},
                                             {"a": "b", "b": "c", "k": 1},
                                             {"a": "c", "b": "a", "k": closed}]]))
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = main(["windconsistency", str(path)])
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(out.getvalue())["pass"], expected == 0)
            path.write_text("not JSON")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(main(["windconsistency", str(path)]), 2)
            self.assertIn("windconsistency:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
