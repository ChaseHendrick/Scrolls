"""Checks for prospective lane G code; archived measurements stay unchanged."""
import ast
import pathlib
import shlex
import subprocess
import tempfile
import unittest

try:
    import numpy as np
except ImportError:
    np = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "scripts/experiments/2026-10-07-laneG"


@unittest.skipIf(np is None, "numpy required")
class PeriodTests(unittest.TestCase):
    @staticmethod
    def function():
        tree = ast.parse((EXPERIMENT / "signals.py").read_text())
        node = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "period")
        scope = {"np": np}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "signals.py", "exec"), scope)
        return scope["period"]

    def test_first_positive_peak_instead_of_strongest(self):
        # Control the measured ACF to isolate the specified peak-selection rule.
        ac = np.zeros(100)
        ac[0], ac[20], ac[40] = 1., .3, .8
        class NumpyWithKnownCorrelation:
            correlate = staticmethod(lambda *_args: np.r_[np.zeros(99), ac])
        function = self.function()
        function.__globals__["np"] = NumpyWithKnownCorrelation
        lag, peak = function(np.zeros(100))
        self.assertEqual(lag, 20)
        self.assertAlmostEqual(peak, .3)

    def test_negative_peak_and_fewer_than_three_periods_abstain(self):
        ac = np.full(100, -.2)
        ac[0], ac[20], ac[40] = 1., -.1, .8
        class NumpyWithKnownCorrelation:
            correlate = staticmethod(lambda *_args: np.r_[np.zeros(99), ac])
        function = self.function()
        function.__globals__["np"] = NumpyWithKnownCorrelation
        self.assertEqual(function(np.zeros(100)), (None, None))

    def test_constant_profile_has_no_peak(self):
        self.assertEqual(self.function()(np.ones(640)), (None, None))


class WrapperTests(unittest.TestCase):
    def test_fresh_output_directory_before_tee(self):
        with tempfile.TemporaryDirectory() as work:
            work = pathlib.Path(work)
            (work / "laneG").mkdir()
            (work / "venv/bin").mkdir(parents=True)
            python = work / "venv/bin/python"
            python.write_text('#!/bin/bash\nif [ "$1" = -c ]; then echo "10 10"; else echo "{}"; fi\n')
            python.chmod(0o755)
            script = (EXPERIMENT / "run.sh").read_text().replace("W=~/scrolls-work;", "W=" + shlex.quote(str(work)) + ";")
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((work / "laneG/out/signals.log").exists())
            self.assertEqual(len(list((work / "laneG/out").glob("boot_*.json"))), 12)


if __name__ == "__main__":
    unittest.main()
