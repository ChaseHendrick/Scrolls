"""kit.cloudcost: Modal rates file, container arithmetic, job estimates, budgets (stdlib only)."""

import io
import json
import unittest
from contextlib import redirect_stdout

from kit import cloudcost as cc


class RatesFileTest(unittest.TestCase):
    def setUp(self):
        self.r = cc.load_rates()

    def test_dated_and_sourced(self):
        self.assertEqual(self.r["accessed"], "2026-10-07")
        self.assertTrue(self.r["gpu_source"].startswith("https://modal.com/"))
        for key in ("cpu_mem_source", "volume_source", "egress_source", "region_source", "nonpreemptible_source"):
            self.assertTrue(self.r[key].startswith("https://"), key)
        for name, url in self.r["sources"].items():
            self.assertTrue(url.startswith("https://modal.com/"), name)

    def test_every_gpu_has_a_container_limit_entry(self):
        for g in self.r["gpu_usd_per_s"]:
            self.assertIn(g, self.r["max_gpus_per_container"])
            self.assertIn(g, self.r["speed_vs_a100_80gb"])

    def test_published_hourly_rates(self):
        self.assertAlmostEqual(cc.gpu_per_hour(self.r, "H100"), 3.9492, places=4)
        self.assertAlmostEqual(cc.gpu_per_hour(self.r, "A10"), 1.1016, places=4)
        self.assertAlmostEqual(cc.gpu_per_hour(self.r, "T4"), 0.5904, places=4)
        with self.assertRaises(ValueError):
            cc.gpu_per_hour(self.r, "V100")

    def test_rates_ordered_by_price(self):
        order = ["B300", "B200", "H200", "H100", "RTX-PRO-6000", "A100-80GB", "A100-40GB", "L40S", "A10", "L4", "T4"]
        prices = [self.r["gpu_usd_per_s"][g] for g in order]
        self.assertEqual(prices, sorted(prices, reverse=True))


class ContainerCostTest(unittest.TestCase):
    def setUp(self):
        self.r = cc.load_rates()

    def test_modal_faq_gpu_example(self):
        # Pricing FAQ: A10G, 1.5 s, 1 CPU, 4 GiB: about $0.000458 GPU, $0.000020 CPU, $0.000013 memory.
        c = cc.container_cost(self.r, 1.5 / 3600, gpu="A10", cpu=1, mem_gib=4)
        self.assertAlmostEqual(c["gpu"], 0.000458, delta=0.000002)
        self.assertAlmostEqual(c["cpu"], 0.000020, delta=0.000001)
        self.assertAlmostEqual(c["mem"], 0.000013, delta=0.000001)

    def test_modal_faq_memory_example(self):
        # Pricing FAQ: 256 MiB for one hour costs $0.00200.
        c = cc.container_cost(self.r, 1.0, cpu=0.5, mem_gib=0.25)
        self.assertAlmostEqual(c["mem"], 0.00200, delta=0.00001)

    def test_minimums(self):
        c = cc.container_cost(self.r, 1.0, cpu=0, mem_gib=0)
        self.assertAlmostEqual(c["cpu"], 0.125 * 0.0000131 * 3600)
        self.assertAlmostEqual(c["mem"], 0.125 * 0.00000222 * 3600)

    def test_containers_and_gpus_scale_linearly(self):
        one = cc.container_cost(self.r, 1.0, gpu="H100", cpu=4, mem_gib=32)["total"]
        four = cc.container_cost(self.r, 1.0, gpu="H100", cpu=4, mem_gib=32, containers=4)["total"]
        self.assertAlmostEqual(four, 4 * one)
        two = cc.container_cost(self.r, 1.0, gpu="H100", gpus=2, cpu=0, mem_gib=0)["gpu"]
        self.assertAlmostEqual(two, 2 * 3.9492, places=4)

    def test_region_and_nonpreemptible(self):
        base = cc.container_cost(self.r, 1.0, gpu="T4", cpu=1, mem_gib=1)["total"]
        narrow = cc.container_cost(self.r, 1.0, gpu="T4", cpu=1, mem_gib=1, region="narrow")["total"]
        self.assertAlmostEqual(narrow, 1.75 * base)
        cpu = cc.container_cost(self.r, 1.0, cpu=1, mem_gib=1)["total"]
        np_ = cc.container_cost(self.r, 1.0, cpu=1, mem_gib=1, nonpreemptible=True)["total"]
        self.assertAlmostEqual(np_, 3 * cpu)
        with self.assertRaises(ValueError):
            cc.container_cost(self.r, 1.0, gpu="H100", nonpreemptible=True)

    def test_gpu_count_limits(self):
        cc.container_cost(self.r, 1.0, gpu="H100", gpus=8)
        with self.assertRaises(ValueError):
            cc.container_cost(self.r, 1.0, gpu="H100", gpus=9)
        with self.assertRaises(ValueError):
            cc.container_cost(self.r, 1.0, gpu="A10", gpus=5)
        with self.assertRaises(ValueError):
            cc.container_cost(self.r, -1.0)

    def test_volume_and_egress_allowances(self):
        self.assertEqual(cc.volume_cost(self.r, 500), 0.0)
        self.assertAlmostEqual(cc.volume_cost(self.r, 1124), 100 * 0.09)
        self.assertEqual(cc.egress_cost(self.r, 1000), 0.0)
        self.assertAlmostEqual(cc.egress_cost(self.r, 1034), 10 * 0.04)
        self.assertAlmostEqual(cc.egress_cost(self.r, 10, already_used_gib=2000), 10 * 0.04)
        self.assertEqual(cc.egress_cost(self.r, 5000, plan="team"), 0.0)


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.r = cc.load_rates()
        self.doc = cc.load_jobs()

    def test_every_job_estimates_in_order(self):
        ids = set()
        for job in self.doc["jobs"]:
            self.assertNotIn(job["id"], ids)
            ids.add(job["id"])
            e = cc.estimate(self.r, job, self.doc["inference_profiles"])
            u = e["usd"]
            self.assertGreater(u["low"], 0, job["id"])
            self.assertLessEqual(u["low"], u["typical"], job["id"])
            self.assertLessEqual(u["typical"], u["high"], job["id"])

    def test_profiles_state_a_basis(self):
        for name, p in self.doc["inference_profiles"].items():
            self.assertIn(p["gpu"], self.r["gpu_usd_per_s"], name)
            self.assertGreater(len(p["basis"]), 40, name)

    def test_inference_scales_with_resolution(self):
        prof = {"gpu": "A10", "ref_um": 8.0, "layers": 20, "gpu_s_per_cm2": [10, 10, 10], "startup_h": 0}
        coarse, gb_c = cc.inference_phases(prof, 10, 8.0)
        fine, gb_f = cc.inference_phases(prof, 10, 4.0)
        self.assertAlmostEqual(fine[2]["hours"][1], 4 * coarse[2]["hours"][1])
        self.assertAlmostEqual(gb_f, 4 * gb_c)
        prof3 = dict(prof, scale_power=3)
        fine3, gb3 = cc.inference_phases(prof3, 10, 4.0)
        self.assertAlmostEqual(fine3[2]["hours"][1], 8 * coarse[2]["hours"][1])
        self.assertAlmostEqual(gb3, 8 * gb_c)

    def test_surface_volume_size(self):
        # 1 cm2 at 10 um is 1e6 pixels; 10 layers of uint8 is 10 MB.
        self.assertAlmostEqual(cc.surface_volume_gb(1, 10, 10), 0.01)

    def test_finetune_job_covers_four_parallel_h100(self):
        job = next(j for j in self.doc["jobs"] if j["id"] == "finetune_9um_4xh100")
        e = cc.estimate(self.r, job)
        # 4 variants x 25 min + 15 min base on H100: GPU alone is at least 7.6 USD.
        self.assertGreater(e["usd"]["typical"], (4 * 0.42 + 0.25) * 3.9492)

    def test_budget_hours(self):
        self.assertAlmostEqual(cc.budget_hours(self.r, 30, "H100", cpu=0, mem_gib=0),
                               30 / (3.9492 + 0.125 * 0.04716 + 0.125 * 0.007992), places=6)
        self.assertLess(cc.budget_hours(self.r, 30, "H100"), 30 / 3.9492)

    def test_work_cost_prefers_h100_for_compute_bound_training(self):
        self.assertLess(cc.work_cost(self.r, "H100"), cc.work_cost(self.r, "A10"))
        self.assertIsNone(cc.work_cost(self.r, "L4"))


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cc.main(list(argv)), 0)
        return buf.getvalue()

    def test_commands(self):
        self.assertIn("| H100 |", self.run_cli("rates"))
        out = json.loads(self.run_cli("cost", "--gpu", "H100", "--hours", "1", "--cpu", "0", "--mem", "0"))
        self.assertAlmostEqual(out["gpu"], 3.9492, places=3)
        self.assertIn("total USD", self.run_cli("infer", "--profile", "2p5d_9um", "--area", "10", "--um", "7.91"))
        self.assertIn("| Job |", self.run_cli("jobs"))
        self.assertEqual(len(json.loads(self.run_cli("jobs", "--json"))), len(cc.load_jobs()["jobs"]))
        self.assertIn("30 USD", self.run_cli("budget", "30", "100"))


if __name__ == "__main__":
    unittest.main()
