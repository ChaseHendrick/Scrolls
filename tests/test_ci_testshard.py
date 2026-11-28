import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ci_testshard", ROOT / "scripts" / "ci" / "testshard.py")
testshard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(testshard)


class TestShardPlan(unittest.TestCase):
    def test_every_module_lands_in_exactly_one_shard(self):
        names = testshard.modules()
        self.assertIn("test_ci_testshard", names)
        for shards in (1, 2, 4, 7):
            plan = testshard.plan(names, shards)
            self.assertEqual(len(plan), shards)
            flat = [n for shard in plan for n in shard]
            self.assertEqual(sorted(flat), sorted(names))
            self.assertEqual(len(flat), len(set(flat)))

    def test_split_modules_keep_every_loaded_test(self):
        import unittest as ut
        loader = ut.TestLoader()
        table = testshard.units(testshard.modules(), loader)
        for name in testshard.SPLIT:
            whole = {t.id() for t in testshard._flatten(loader.loadTestsFromName(name))}
            parts = [t.id() for unit, tests in table.items() if unit.startswith(name + ".") for t in tests]
            self.assertTrue(whole)
            self.assertEqual(sorted(parts), sorted(whole))
            self.assertNotIn(name, table)

    def test_known_units_exist(self):
        table = testshard.units(testshard.modules())
        self.assertEqual([n for n in testshard.SECONDS if n not in table], [])

    def test_greedy_packing_balances_known_slow_modules(self):
        seconds = {"a": 10.0, "b": 9.0, "c": 2.0, "d": 1.0}
        plan = testshard.plan(["a", "b", "c", "d"], 2, seconds)
        loads = sorted(sum(seconds[n] for n in shard) for shard in plan)
        self.assertEqual(loads, [11.0, 11.0])

    def test_plan_is_deterministic_and_rejects_zero_shards(self):
        names = testshard.modules()
        self.assertEqual(testshard.plan(names, 4), testshard.plan(list(reversed(names)), 4))
        with self.assertRaises(ValueError):
            testshard.plan(names, 0)

    def test_workflow_shard_count_matches_the_verify_matrix(self):
        text = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/ci/testshard.py --shard ${{ matrix.shard }} --of 6", text)
        self.assertIn("shard: [1, 2, 3, 4, 5, 6]", text)


if __name__ == "__main__":
    unittest.main()
