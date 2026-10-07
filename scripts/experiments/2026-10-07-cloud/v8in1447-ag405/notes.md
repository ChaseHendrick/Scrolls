# v8in1447-ag405 (CPU, 2026-10-07): partial, stopped by the user

Job: v8in-1447 (`YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062` at `2bf9f42`) on the PHerc0841 ag405 crop (rows 1024 to 1664, columns 2496 to 3136; surface 3760 x 4900; 9.366 um), forward stride 21, reverse stride 42, forward stride 42; d9v2 on the same crop; ensembles v8in-1447 + d9v2 (mean and rank). Scored with `kit auc` and `kit hpscore` at label level 2, `--inner 64`.

## What ran

- Shared setup: `SMOKE=1 EXPECT_GPU=cpu SEGMENT=0841-ag405 MODEL=v8in-1447 bash scripts/mac-w045.sh` (about 20 min; its smoke numbers are a script test only).
- d9v2: `d9v2_ft-012000.pth` from the v1.0 release of TAUIL-Abd-Elilah/pherc0826-first-letters-search, SHA-256 `50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966`. villa PR #1865, overlap 0.5, hann, both directions: 74 s on 4 CPUs.
- `run.sh` (resumable) then started v8in-1447 forward stride 42. It ran at about 7.6 s per tile (172 of 196 tiles in 1313 s) when the session was stopped by the user (out of usage). No v8in-1447 map finished, so no v8in-1447 or ensemble number exists yet.

## Results so far

| Map | AUC as stored | AUC reversed | hp_r | hp_r reversed |
| --- | --- | --- | --- | --- |
| d9v2 | 0.8319 | 0.6572 | 0.0248 | 0.003 |
| v8in-1447 s42 | not finished | | | |
| v8in-1447 s21 | not run | | | |
| v8in-1447 + d9v2 mean, rank | not run | | | |

d9v2 forward reproduces the earlier CPU bar (0.8319) to four decimals, so the pipeline matches. Its reversed control at 0.657 is well above 0.5 on this crop; worth noting when comparing controls across readers.

## To finish

Rerun the shared setup, fetch the d9v2 checkpoint into `$W/checkpoints/d9v2/`, then `nohup bash scripts/experiments/2026-10-07-cloud/v8in1447-ag405/run.sh > $W/logs/job.log 2>&1 &` and `python make_results.py`. Expected CPU time at about 8 s per tile: 27 min per stride 42 map (two) and about 1.75 h for stride 21.

## Review correction: partial coverage and controls

The checked-in `results.json` and `scores/*.json` remain the historical d9v2-only
record. Neither a completed v8in map nor a completed ensemble was produced in that
run. The table's missing rows are not zero scores or completed negative results.

The corrected primary plan is d9v2, v8in1447_s42, and the mean/rank ensembles using
v8in1447_s42 plus d9v2. Both primary depth directions use stride 42. An existing
stride 64 reverse map is preserved as a provisional fallback; varying stride and
direction together cannot establish a direction effect. The optional s21 row is
also provisional against an s42 control, and now requires `RUN_S21=1` to generate.
Reverse ensembles use explicit `_reverse_s42` or `_reverse_s64` names. Legacy score
pairs without a reverse-stride metadata file are reported as unverified, not matched.

New scores, results and `status.json` are written under the runtime job directory;
checked-in historical JSON is not overwritten. Collection defaults to
`results.current.json` and `status.current.json` when called directly. Status lists
all five declared rows, distinguishing the four primary maps from optional s21,
missing score pairs, and missing/provisional controls. Successful collection means
available pairs were collected, not that inference completed. Interrupted runs
retain the last successfully collected partial status.

The prior rough completion-time estimates are not measurements of this corrected
plan; they should not be used to claim a completed or validated comparison. No model
inference or real-data validation was run for this correction. Run
`python -m unittest discover -s scripts/experiments/2026-10-07-cloud/v8in1447-ag405 -p 'test_*.py' -v`
for bounded provenance and coverage tests with temporary score files.
