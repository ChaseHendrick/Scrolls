# Testing

A passing run means the prize snapshot is internally consistent, the planner prints the official commands with the right volume paths, the doctor's thresholds behave, and the ledger enforces its rules. It does not mean the GPU pipeline runs on your machine, or that any scroll contains ink.

## What "ALL PASS" means

The standard-library runner does **not** print the words `ALL PASS`. A clean run ends like this:

```text
----------------------------------------------------------------------
Ran N tests in …s

OK
```

**ALL PASS** in a checklist means all three:

1. The process exit status is **0**.
2. The last line is `OK`, not `FAILED (failures=…)` or `FAILED (errors=…)`.
3. The `Ran N tests` line matches the tests you think you ran. Say which command you ran.

## Commands

From the repository root, Python 3.10 or newer, no dependencies:

```bash
python -m unittest discover -s tests -v          # verify tests skip without numpy/tifffile
python -m pip install numpy tifffile imagecodecs  # to run them
python -m kit prizes
python -m kit doctor        # exit 1 when a check fails (e.g. no GPU); that is a report, not a test failure
```

CI ([`.github/workflows/check.yml`](../.github/workflows/check.yml)) runs the tests on Python 3.10 and 3.13 (standard library only), again on 3.13 with numpy, tifffile and imagecodecs so the `verify` tests run, and smoke-runs `prizes` and `plan`.

## What the tests pin

| Test | Pins |
| --- | --- |
| `PrizeSnapshotTest` | Totals and tiers, 13 Grand Prize and 22 First Letters volumes, PHerc1447 moved off First Letters, every volume resolved to an S3 Zarr name, scroll-name normalization, deadline arithmetic |
| `DoctorTest` | `nvidia-smi` parsing, the 12 GB threshold, Apple Silicon reported as a path not a failure, memory rounding, villa checkout detection |
| `PlanTest` | Mac setup (VC3D.app tools, MPS check, PR branch, batch 1), control segment present, resolved target path, `--direction both`, privacy instruction, 8.64 µm resampling note, rejection of ineligible scrolls, cost arithmetic against bnleft's published A10 figure |
| `LedgerTest` | Readout hash and tamper detection, legal transitions, candidate cannot go public before `--announced`, null can, costs, slug safety |
| `CliTest` | End-to-end CLI for `prizes`, `plan` and `run` |
| `VerifyArraysTest`, `VerifyFilesTest` | Verdict logic (a control that agrees invalidates the check), block statistics equal whole-array numpy, villa-style tiled LZW BigTIFF reading, exit codes, results attached to the ledger. Skipped without numpy and tifffile |
| `ProvenanceTest` | SHA-256 of recorded files, missing files refused |

## When the snapshot changes

Add a new `kit/data/prizes-YYYY-MM-DD.json`, point `prizes.SNAPSHOT` at it, and update the counts in the tests in the same commit. Keep the old snapshot for history.
