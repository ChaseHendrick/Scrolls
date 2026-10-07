"""Checks for prospective lane F code, without CT, sklearn fits or inference."""
import ast
import os
import pathlib
import subprocess
import tempfile
import unittest

try:
    import numpy as np
    from scipy import ndimage as ndi
    from scipy.stats import rankdata
except ImportError:
    np = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "scripts/experiments/2026-10-07-grok-laneF"


@unittest.skipIf(np is None, "numpy and scipy required")
class NumericTests(unittest.TestCase):
    @staticmethod
    def functions():
        tree = ast.parse((EXPERIMENT / "e234.py").read_text())
        names = {"rank", "profiles", "shuffled_test_score"}
        nodes = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in names]
        scope = {"np": np, "ndi": ndi, "rankdata": rankdata, "PAD": 8}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "e234.py", "exec"), scope)
        return scope

    def test_equal_predictions_have_equal_ranks(self):
        rank = self.functions()["rank"]
        np.testing.assert_array_equal(rank(np.ones((8, 8))), np.full((8, 8), 32.5 / 64))
        values = np.array([[1., 2.], [1., 3.]])
        np.testing.assert_array_equal(rank(values), [[.375, .75], [.375, 1.]])

    def test_rank_does_not_depend_on_raster_order(self):
        rank = self.functions()["rank"]
        values = np.array([[1., 2., 1.], [3., 2., 1.]])
        np.testing.assert_array_equal(rank(values)[::-1, ::-1], rank(values[::-1, ::-1]))

    def test_control_keeps_classifier_fixed_and_only_permutes_test_depth(self):
        scope = self.functions()
        volume = np.random.default_rng(42).normal(size=(4, 20, 20))
        permutation = np.array([2, 0, 3, 1])
        class FixedClassifier:
            def __init__(self):
                self.seen = []
            def decision_function(self, features):
                self.seen.append(features.copy())
                return features @ np.array([1., 2., 4., 8.])
        clf = FixedClassifier()
        result = scope["shuffled_test_score"](clf, volume, permutation)
        expected = scope["profiles"](volume[permutation])
        np.testing.assert_array_equal(clf.seen[0], expected)
        self.assertEqual(len(clf.seen), 1)
        self.assertEqual(result.shape, (4, 4))
        real = scope["profiles"](volume) @ np.array([1., 2., 4., 8.])
        self.assertGreater(float(np.max(np.abs(result.ravel() - real))), .1)


class WrapperTests(unittest.TestCase):
    def test_failed_inference_stops_before_other_runs(self):
        with tempfile.TemporaryDirectory() as work:
            work = pathlib.Path(work)
            (work / "laneF").mkdir()
            (work / "venv/bin").mkdir(parents=True)
            python = work / "venv/bin/python"
            python.write_text('#!/bin/bash\necho run >> "$SCROLLS_TEST_MARKER"\nexit 7\n')
            python.chmod(0o755)
            script = (EXPERIMENT / "e1_infer.sh").read_text().replace('cd ~/scrolls-work', 'cd "$SCROLLS_TEST_WORK"')
            # The Mac timing binary is absent in some cloud environments;
            # child exit propagation is the behavior under test here.
            script = script.replace("/usr/bin/time -p", "command")
            env = dict(os.environ, SCROLLS_TEST_WORK=str(work), SCROLLS_TEST_MARKER=str(work / "runs"))
            result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((work / "runs").exists(), result.stderr + result.stdout)
            self.assertEqual((work / "runs").read_text().splitlines(), ["run"])
            self.assertTrue((work / "laneF/maps").is_dir())


if __name__ == "__main__":
    unittest.main()
