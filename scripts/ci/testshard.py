"""Run one shard of the unit test suite, so CI can split the slow `verify` job across parallel runners.

    python scripts/ci/testshard.py --shard 1 --of 4      # run shard 1 of 4 (verbose, exit 1 on any failure)
    python scripts/ci/testshard.py --list --of 4         # print every shard's units and estimated seconds

A unit is one `tests/test_*.py` module; for the slow modules named in `SPLIT`, one test class of that module; and
for the slow classes named in `SPLIT_TESTS`, one test of that class.
Units are placed longest first onto the shard with the least estimated time so far (greedy longest-processing-time
packing), from the measured seconds in `SECONDS`; any unit not listed counts `DEFAULT_SECONDS`. Every shard
computes the same plan from the file names, the loaded classes and this table, and every test lands in exactly one
shard: a split module's tests are grouped by the class each loaded test belongs to, so nothing the loader returns
is dropped. A new slow test only makes the shards uneven.
"""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
DEFAULT_SECONDS = 1.0
# Modules whose test classes become separate units (the slow ones; a module's own setUpModule then runs in each
# shard that holds one of its classes), and classes whose tests do (only classes with no setUpClass of their own,
# which would otherwise run once per shard).
SPLIT = ("test_scrollsim2",)
SPLIT_TESTS = ("test_scrollsim2.ScrollSim2MakeTest", "test_scrollsim2.ScrollSim2ScanModelTest")
# Seconds per unit with every extra installed (Linux container, Python 3.13, 26 Nov 2026). Only units over about
# 5 s are listed; refresh them when one shard runs much longer than the others.
SECONDS: dict[str, float] = {
    "test_altrain": 19,
    "test_aucreport": 11,
    "test_autocrop": 6,
    "test_axispolish": 22,
    "test_claimcheck": 7,
    "test_finesnap": 18,
    "test_hubcall": 6,
    "test_inkcompare": 9,
    "test_inklens": 16,
    "test_keepalive": 5,
    "test_letterdata": 6,
    "test_letterread": 22,
    "test_parting": 6,
    "test_planted": 12,
    "test_reviewpin": 5,
    "test_scroll2ink": 14,
    "test_scroll_lens": 74,
    "test_scrollsim2.ScrollSim2AllFeaturesTest": 89,
    "test_scrollsim2.ScrollSim2G1Test": 3,
    "test_scrollsim2.ScrollSim2GeometryTest": 27,
    "test_scrollsim2.ScrollSim2InkTest": 43,
    "test_scrollsim2.ScrollSim2MakeTest.test_estimate_reports": 3,
    "test_scrollsim2.ScrollSim2MakeTest.test_make_with_the_scan_model_and_the_nps_command": 78,
    "test_scrollsim2.ScrollSim2MakeTest.test_make_writes_pyramid_and_is_deterministic": 21,
    "test_scrollsim2.ScrollSim2MakeTest.test_publish_copies_plainly_and_clears_partials": 17,
    "test_scrollsim2.ScrollSim2MakeTest.test_stop_and_resume_give_the_same_volume": 31,
    "test_scrollsim2.ScrollSim2MakeTest.test_vc3d_export_round_trips": 18,
    "test_scrollsim2.ScrollSim2MakeTest.test_verify_finds_lost_chunks_and_pyramid_repairs": 18,
    "test_scrollsim2.ScrollSim2PhysicsTest": 47,
    "test_scrollsim2.ScrollSim2ScanModelTest.test_cupping_darkens_the_middle_of_the_roll": 9,
    "test_scrollsim2.ScrollSim2ScanModelTest.test_scan_model_is_block_independent": 74,
    "test_scrollsim2.ScrollSim2ScanModelTest.test_slabs_step_the_gain_and_change_the_rings": 13,
    "test_scrollsim2.ScrollSim2TextureTest": 40,
    "test_scrollsim2.ScrollSim2TruthExtrasTest": 36,
    "test_sheetcheck": 6,
    "test_snap_face": 7,
    "test_sqrecipe": 10,
    "test_stackcheck": 66,
    "test_strokenet": 39,
    "test_strokenet_stats": 13,
    "test_surfacefix": 8,
    "test_termstyle": 5,
    "test_tooldocs": 10,
    "test_umbilicus": 6,
    "test_vc3d_audit": 5,
    "test_vc3d_cache": 10,
    "test_vc3dfix": 7,
}


def modules(tests: Path = TESTS) -> list[str]:
    return sorted(p.stem for p in tests.glob("test_*.py"))


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def _setup_path() -> None:
    # Same import layout as `unittest discover -s tests`: tests/ first on sys.path, modules by their bare names.
    for p in (str(ROOT), str(TESTS)):
        if p not in sys.path:
            sys.path.insert(0, p)


def units(names: list[str], loader: unittest.TestLoader | None = None) -> dict[str, list]:
    """Unit name to its tests (None for a whole module, loaded when its shard runs)."""
    loader = loader or unittest.TestLoader()
    out: dict[str, list] = {}
    for name in names:
        if name not in SPLIT:
            out[name] = None
            continue
        _setup_path()
        for test in _flatten(loader.loadTestsFromName(name)):
            unit = f"{name}.{type(test).__name__}"
            if unit in SPLIT_TESTS:
                unit = f"{unit}.{getattr(test, '_testMethodName', str(test))}"
            out.setdefault(unit, []).append(test)
    return out


def plan(names: list[str], shards: int, seconds: dict[str, float] | None = None) -> list[list[str]]:
    if shards < 1:
        raise ValueError("--of must be at least 1")
    seconds = SECONDS if seconds is None else seconds
    load = [0.0] * shards
    out: list[list[str]] = [[] for _ in range(shards)]
    for name in sorted(names, key=lambda n: (-seconds.get(n, DEFAULT_SECONDS), n)):
        k = min(range(shards), key=lambda i: (load[i], i))
        out[k].append(name)
        load[k] += seconds.get(name, DEFAULT_SECONDS)
    return [sorted(s) for s in out]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shard", type=int, help="1-based shard to run")
    ap.add_argument("--of", type=int, required=True, help="number of shards")
    ap.add_argument("--list", action="store_true", help="print the plan and run nothing")
    args = ap.parse_args(argv)
    if args.of < 1 or (not args.list and (args.shard is None or not 1 <= args.shard <= args.of)):
        ap.error("--of must be at least 1 and --shard between 1 and --of")
    loader = unittest.TestLoader()
    table = units(modules(), loader)
    shards = plan(list(table), args.of)
    if args.list:
        for i, names in enumerate(shards, 1):
            est = sum(SECONDS.get(n, DEFAULT_SECONDS) for n in names)
            print(f"shard {i}: {len(names)} units, about {est:.0f} s: {' '.join(names)}")
        return 0
    names = shards[args.shard - 1]
    print(f"shard {args.shard} of {args.of}: {len(names)} units", flush=True)
    _setup_path()
    suite = unittest.TestSuite()
    for name in names:
        tests = table[name]
        suite.addTests(tests if tests is not None else [loader.loadTestsFromName(name)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun == 0:
        print("no tests ran in this shard", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
