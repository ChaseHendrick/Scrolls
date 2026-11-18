import json
import tempfile
import unittest
from pathlib import Path

from kit import cpudiag as c


class CgroupTest(unittest.TestCase):
    def _root(self, files):
        d = Path(tempfile.mkdtemp())
        for name, text in files.items():
            p = d / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return d

    def test_v2_quota(self):
        self.assertEqual(c.cgroup_cpus(self._root({"cpu.max": "3200000 100000\n"})), 32.0)

    def test_v2_unlimited(self):
        self.assertIsNone(c.cgroup_cpus(self._root({"cpu.max": "max 100000\n"})))

    def test_v1_quota(self):
        root = self._root({"cpu/cpu.cfs_quota_us": "150000", "cpu/cpu.cfs_period_us": "100000"})
        self.assertEqual(c.cgroup_cpus(root), 1.5)

    def test_v1_unlimited_and_missing(self):
        root = self._root({"cpu/cpu.cfs_quota_us": "-1", "cpu/cpu.cfs_period_us": "100000"})
        self.assertIsNone(c.cgroup_cpus(root))
        self.assertIsNone(c.cgroup_cpus(self._root({})))


class ParseTest(unittest.TestCase):
    def test_lscpu_fields(self):
        text = ("Architecture: x86_64\nCPU(s):  32\nModel name:   AMD EPYC 7R13 Processor\n"
                "Thread(s) per core:  2\nNUMA node0 CPU(s): 0-31\n")
        f = c.lscpu_fields(text)
        self.assertEqual(f["CPU(s)"], "32")
        self.assertEqual(f["Thread(s) per core"], "2")
        self.assertEqual(f["Model name"], "AMD EPYC 7R13 Processor")
        self.assertNotIn("Architecture", f)

    def test_compare_and_reading(self):
        here = {"scaling": {"compute": {"1": {"median_s": 2.0}, "4": {"median_s": 2.0}}},
                "scrollsim2": {"by_procs": {"1": {"median_s": 5.0}}}}
        there = {"scaling": {"compute": {"1": {"median_s": 3.0}, "32": {"median_s": 6.0}}},
                 "scrollsim2": {"by_procs": {"1": {"median_s": 10.0}, "32": {"error": "x"}}},
                 "blas": {"procs": 32, "inherited": {"median_s": 40.0}, "one_thread": {"median_s": 4.0}}}
        self.assertEqual(c.compare(here, there), {"compute P=1": 1.5, "scrollsim2 P=1": 2.0})
        r = c.reading(there)
        self.assertIn("compute: 2.00 x slower per process at P=32 than at P=1", r)
        self.assertTrue(any("10.00 x" in x for x in r))


class RunTest(unittest.TestCase):
    def test_tiny_run_shape(self):
        res = c.run(procs=(1, 2), scale=0.002, mount=tempfile.mkdtemp(), progress=lambda m: None)
        json.dumps(res)
        for k in ("pyloop", "compute", "stream"):
            self.assertEqual(set(res["scaling"][k]), {"1", "2"})
            self.assertEqual(res["scaling"][k]["2"]["n"], 2)
        self.assertGreater(res["scaling"]["stream"]["1"]["gb_s_per_proc"], 0)
        self.assertEqual(res["io"]["mount"]["files_landed"], res["io"]["mount"]["files_expected"])
        self.assertEqual(res["blas"]["one_thread"]["n"], 2)

    def test_blas_timeout_kills_the_group(self):
        import subprocess
        with self.assertRaises(subprocess.TimeoutExpired):
            c.blas_subprocess(2, None, 50.0, timeout=0.5)

    def test_kernels_none_skips_kernels(self):
        out = Path(tempfile.mkdtemp()) / "r.json"
        res = c.run(procs=(1,), scale=0.002, kernels=(), out=str(out), progress=lambda m: None)
        self.assertEqual(res["scaling"], {})
        self.assertNotIn("blas", res)
        self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
