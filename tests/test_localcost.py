import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, ledger, localcost


class LocalCostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "experiments"
        rec = {"slug": "t1", "status": "planned", "history": [], "costs": [], "scroll": "s"}
        ledger.save(rec, self.root)
        config = Path(self.tmp.name) / "config.json"
        config.write_text("{}")
        self.env = mock.patch.dict(os.environ, {localcost.ENV_CONFIG: str(config)})
        self.env.start()
        os.environ.pop(localcost.ENV_RATE, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_estimate(self):
        kwh, usd = localcost.estimate(3600, 30, 0.5)
        self.assertAlmostEqual(kwh, 0.03)
        self.assertAlmostEqual(usd, 0.015)

    def test_rate_sources(self):
        cfg = Path(self.tmp.name) / "cfg.json"
        cfg.write_text(json.dumps({"electricity_usd_per_kwh": 0.2}))
        os.environ[localcost.ENV_CONFIG] = str(cfg)
        self.assertEqual(localcost.resolve_rate(), 0.2)
        os.environ[localcost.ENV_RATE] = "0.3"
        self.assertEqual(localcost.resolve_rate(), 0.3)
        self.assertEqual(localcost.resolve_rate(0.4), 0.4)
        del os.environ[localcost.ENV_RATE]

    def test_no_rate_fails_before_running(self):
        with self.assertRaises(localcost.CostError):
            localcost.run("t1", [sys.executable, "-c", "raise SystemExit(9)"], root=self.root)
        self.assertEqual(ledger.load("t1", self.root)["costs"], [])

    def test_watts(self):
        self.assertEqual(localcost.resolve_watts("apple-silicon-cpu")[0], 30.0)
        self.assertEqual(localcost.resolve_watts(watts=12)[0], 12.0)
        self.assertEqual(localcost.resolve_watts("x", config={"device_watts": {"x": 5}})[0], 5.0)
        with self.assertRaises(localcost.CostError):
            localcost.resolve_watts("nope")

    def test_cli_local_records_entry_and_exit_code(self):
        code = cli.main(["run", "--root", str(self.root), "local", "t1", "--rate", "0.25",
                         "--watts", "100", "--", sys.executable, "-c", "raise SystemExit(3)"])
        self.assertEqual(code, 3)
        cost = ledger.load("t1", self.root)["costs"][0]
        item = cost["local"]
        self.assertEqual(item["exit_code"], 3)
        self.assertEqual(item["rate_usd_per_kwh"], 0.25)
        self.assertGreater(item["wall_s"], 0)
        self.assertIsNotNone(item["cpu_s"])
        self.assertAlmostEqual(item["kwh"], 100 * item["wall_s"] / 3.6e6, places=5)

    def test_backfill_marks_estimated(self):
        f = Path(self.tmp.name) / "b.json"
        f.write_text(json.dumps([{"what": "a", "wall_s": 3600, "device": "apple-silicon-cpu"},
                                 {"what": "b", "wall_s": 1800, "watts": 60}]))
        self.assertEqual(cli.main(["run", "--root", str(self.root), "backfill", "t1",
                                   "--file", str(f), "--rate", "1"]), 0)
        costs = ledger.load("t1", self.root)["costs"]
        self.assertTrue(all("(estimated from logs)" in c["what"] for c in costs))
        self.assertTrue(all(c["local"]["estimated_from_logs"] for c in costs))
        self.assertAlmostEqual(sum(c["local"]["usd_exact"] for c in costs), 0.06)

    def test_repo_backfill_file_is_valid(self):
        items = json.loads(Path("scripts/backfill/2026-10-07-local-runs.json").read_text())
        for it in items:
            self.assertIn(it["device"], localcost.DEVICE_WATTS)
            self.assertGreater(it["wall_s"], 0)


if __name__ == "__main__":
    unittest.main()
