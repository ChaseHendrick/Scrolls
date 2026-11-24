"""kit runlength cpu: the measured CPU flavor table scales a container-timed task to a cloud CPU flavor."""
import io
import json
import math
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from kit import runlength as R

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence" / "2026-11-18-hf-cpu-diag"


class CpuFlavorTest(unittest.TestCase):
    """18 Nov 2026 (kit.cpudiag, docs/evidence/2026-11-18-hf-cpu-diag): cpu-performance is 16 physical cores with
    memory bandwidth saturated from 8 processes, so a container-timed task does not scale to 32 vCPU."""

    def test_slowdown_interpolates_and_extrapolates(self):
        self.assertEqual(R.cpu_slowdown("cpu-performance", 1, "scrollsim2"), 1.0)
        self.assertEqual(R.cpu_slowdown("cpu-performance", 16, "scrollsim2"), 1.9)
        self.assertAlmostEqual(R.cpu_slowdown("cpu-performance", 24, "scrollsim2"), (1.9 + 4.8) / 2)
        self.assertAlmostEqual(R.cpu_slowdown("cpu-performance", 64, "scrollsim2"), 9.6)   # time-shared past vCPUs
        self.assertEqual(R.cpu_slowdown("cpu-performance", 4, "compute"), 1.9)
        self.assertIsNone(R.cpu_slowdown("cpu-basic", 2))
        self.assertIsNone(R.cpu_slowdown("cpu-performance", 2, "disk"))

    def test_max_is_the_default_and_covers_every_kind(self):
        for w in (1, 4, 8, 12, 16, 24, 32, 48):
            m = R.cpu_slowdown("cpu-performance", w)
            for k in ("stream", "scrollsim2", "compute"):
                self.assertGreaterEqual(m, R.cpu_slowdown("cpu-performance", w, k))

    def test_table_matches_the_evidence(self):
        """The stream and compute rows are the first job's seconds per process over the container's P=1 seconds."""
        here = json.loads((EVIDENCE / "container-4core.json").read_text())["scaling"]
        lines = (EVIDENCE / "hf-cpu-performance-a1-kernels.txt").read_text().splitlines()
        hf = {}
        for line in lines:
            head, body = line.split(": ", 1)
            _, kernel, p = head.split()
            hf[(kernel, int(p[2:]))] = json.loads(body)["median_s"]
        for kind in ("stream", "compute"):
            base = here[kind]["1"]["median_s"]
            for w, f in R.CPU_FLAVORS["cpu-performance"]["slowdown"][kind].items():
                self.assertAlmostEqual(hf[(kind, w)] / base, f, delta=0.06, msg=(kind, w))

    def test_default_cap_covers_the_stream_measured_time(self):
        """A bandwidth-bound job sized with the default kind must fit its cap: cpudiag's triad took 1.95 s in the
        container and 3.90, 7.58, 14.83 s per process at 8, 16, 32 on the flavor."""
        hf = {8: 3.904, 16: 7.581, 32: 14.834}
        for w, per in hf.items():
            tasks = 8000
            true_s = math.ceil(tasks / w) * per
            est = R.cpu_wall_s(1.947, tasks, "cpu-performance", w)
            self.assertGreaterEqual(R.cap_minutes(est / 60) * 60, true_s)
            self.assertLess(abs(est - true_s) / true_s, 0.05)
        # the scrollsim2 row alone would not cover it (32.5 min predicted, about 65 true)
        self.assertLess(R.cap_minutes(R.cpu_wall_s(1.947, 8000, "cpu-performance", 8, "scrollsim2") / 60) * 60,
                        math.ceil(8000 / 8) * hf[8])

    def test_scrollsim2_row_matches_the_measured_pilot(self):
        """A 32-worker pilot rendered all 2,912 blocks, 2,458 of them sheet, in 1,512 s. The scrollsim2 row, from the
        same 32 blocks' 4.33 s median in the container, must land within 15 percent and must not reproduce the
        core-seconds-over-vCPU guess."""
        src = (EVIDENCE / "scrollsim2-pilot-timing.txt").read_text()
        self.assertIn("PROGRESS 2912/2912 blocks 1512s", src)
        self.assertAlmostEqual(json.loads((EVIDENCE / "container-4core-scrollsim2-32blocks.json").read_text())
                               ["median_s"], 4.33, places=2)
        wall = R.cpu_wall_s(4.33, 2458, "cpu-performance", 32, "scrollsim2")
        self.assertLess(abs(wall - 1512) / 1512, 0.15)
        self.assertGreater(wall / (4.33 * 2458 / 32), 3)
        self.assertLess(R.cpu_wall_s(4.33, 2458, "cpu-performance", 8, "scrollsim2"), wall)
        self.assertIsNone(R.cpu_wall_s(1, 1, "cpu-xl", 4))

    def test_best_workers(self):
        self.assertEqual(R.cpu_best_workers("cpu-performance", "scrollsim2"), 8)
        self.assertEqual(R.cpu_best_workers("cpu-performance", "compute"), 32)   # SMT still adds a little
        self.assertIn(R.cpu_best_workers("cpu-performance"), (8, 16, 32))
        self.assertIsNone(R.cpu_best_workers("cpu-xl"))
        self.assertIsNone(R.cpu_best_workers("cpu-performance", "disk"))

    def test_cap_minutes(self):
        self.assertEqual(R.cap_minutes(1), 10)
        self.assertEqual(R.cap_minutes(20), 35)

    def test_cli(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(R.main(["cpu", "--task-s", "4.33", "--tasks", "2458", "--kind", "scrollsim2",
                                     "--json"]), 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["workers"], 8)
        self.assertEqual(out["cap_min"], R.cap_minutes(out["wall_s"] / 60))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(R.main(["cpu", "--task-s", "1.95", "--tasks", "8000", "--workers", "8", "--json"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["kind"], "max")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(R.main(["cpu", "--task-s", "1", "--tasks", "1", "--flavor", "cpu-xl"]), 2)


if __name__ == "__main__":
    unittest.main()
