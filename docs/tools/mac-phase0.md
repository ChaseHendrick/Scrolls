# mac-phase0: queue v8in and v8in-1447 on the three PHerc0841 crops on a Mac, then print Gate A

`scripts/mac-phase0.sh` runs [mac-w045](mac-w045.md) in `QUICK=1` mode for every reader and PHerc0841 crop not yet scored, one job at a time on the Mac GPU, skips finished jobs, and ends with the Gate A table from `python -m kit gate`.

| Field | Value |
| --- | --- |
| Id | `mac-phase0` |
| Status | Current |
| Kind | script |
| Area | Scoring and controls |
| Run | `bash scripts/mac-phase0.sh` |
| Code | `scripts/mac-phase0.sh` |
| Tests | `tests/test_repo.py` (only that the script parses with `bash -n` and uses no bash 4 syntax) |
| Needs | `python3` (any version `kit gate` runs on; standard library only) for the skip check and the gate; everything [mac-w045](mac-w045.md) needs for each job: an Apple Silicon Mac, git, uv, and about 6 GB free in `WORK`; run it from a clone of the repository, since `kit gate` reads `docs/results.json` |
| Runs on | Apple Silicon Mac. About 20 min per job in fp32 on an M1 Pro (script header and [mac.md](../mac.md#generalization-check-on-w045-one-command); an estimate, not a recorded run of this queue), so about 2 h for the six default jobs. `DRY_RUN=1` with nothing to run took 0.5 s (measured 2026-10-16, Linux cloud container) |
| Network | None itself. Each job runs [mac-w045](mac-w045.md), which contacts GitHub, the open-data bucket, Hugging Face and the Python package index |
| Writes | `WORK/logs/` (created), one log per job at `WORK/logs/phase0_SEGMENT_MODEL.log` (overwritten), and the gate table at `WORK/phase0-gate.txt` (overwritten, also with `DRY_RUN=1`). Each job also writes everything mac-w045 writes, under `WORK/SEGMENT/` and the shared `WORK` folders |
| Go-ahead | Not needed to run it on your own Mac. Posting the gate table or the scores needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-07 |
| Guide | [mac.md, "All of Phase 0 in one command"](../mac.md#generalization-check-on-w045-one-command) |
| Checked | 2026-10-16 against commit `0747c06` |

## What it does

Phase 0 asks which released ink model (a "reader" here) is best on PHerc0841, by scoring each one against human labels on a scroll none of the main candidates trained on. PHerc0841 is that scroll: it is in the training data of none of `ink_9um`, v8in, d9v2 and Reader v2, but possibly in Hecate's, and the glossary in [`AGENTS.md`](../../AGENTS.md) lists v8in-1447 among the models that did not train on it. The team traced three PHerc0841 segments with labelled text: `0841-w00`, `0841-ag896` and `0841-ag405`. Gate A is the rule that picks the winner; its public statement is in `kit/gate.py` and on the [gate](gate.md) page.

The CPU scores of several readers are already committed in [`results.json`](../results.json). v8in (Youssef Nader's ResNet3D-50 model, `YoussefMoNader/ink-8um-v8in`) and v8in-1447 (its PHerc1447 fine-tune) cost about 50 times as much per pixel as `ink_9um` (mac-w045's comment) and so run on the Mac GPU. This script queues them: for each job `MODEL:SEGMENT` it runs `MODEL=MODEL SEGMENT=SEGMENT QUICK=1 bash scripts/mac-w045.sh`, which scores the reader on the segment's standard 640 px crop with a 64 px edge left out, with the reverse-depth map as the control. Then it runs `python -m kit gate WORK`, which merges those Mac scores with the committed ones and prints the table and verdict.

It is resumable. A job whose score `kit gate` already finds under `WORK/SEGMENT/results/` (on the standard crop with the 64 px edge) is skipped, so Ctrl-C and a rerun lose at most the job in progress, and mac-w045 reuses that job's finished passes too. It keeps the Mac awake with `caffeinate` (closing the lid still sleeps it) and sends a macOS notification when the queue ends or a job fails.

It does not run on Modal, does not score `ink_9um`, d9v2 or Reader v2 (their bars are committed), and does not commit anything. The scores are AUCs of model output against labels; the maps are model output, not readings.

## When to use it

- To fill the v8in and v8in-1447 cells of the Gate A table on a Mac with one command.
- To resume that queue after an interruption.
- With `DRY_RUN=1`, to see which jobs are left and the current table.

Do not use it:

- For one reader on one segment, or on w045: run [mac-w045](mac-w045.md) directly.
- To see the table without running anything: `python -m kit gate` ([gate](gate.md)) prints it at any time.
- For readers other than v8in and v8in-1447: jobs are limited to those two (`ink_9um` CPU bars come from `results.json`).
- On a machine without an Apple GPU: each job stops at mac-w045's machine check; GPU work belongs on Modal (the Modal rule, hard rule 11).

## Quick start

```bash
DRY_RUN=1 bash scripts/mac-phase0.sh    # the queue and the current table, runs nothing
bash scripts/mac-phase0.sh              # the real queue, on an Apple Silicon Mac
```

Run it from the Scrolls checkout. `DRY_RUN=1` with an empty `WORK` (`WORK=/tmp/claude-docs-public-mac-phase0/work`, so no Mac scores) printed this on 2026-10-16, on a Linux container, in 0.5 s:

```
[1/6] v8in on 0841-w00: would run MODEL=v8in SEGMENT=0841-w00 QUICK=1 bash scripts/mac-w045.sh
...
[6/6] v8in-1447 on 0841-ag405: would run MODEL=v8in-1447 SEGMENT=0841-ag405 QUICK=1 bash scripts/mac-w045.sh

== Gate A
| Reader | w00 | ag896 | ag405 | Mean | Control |
| --- | ---: | ---: | ---: | ---: | --- |
| d9v2 | 0.8994 (0.586) | 0.8230 (0.532) | 0.8319 (0.657) | 0.8514 | ok |
| ink_9um seed42 | 0.8061 (0.536) | 0.6594 (0.558) | 0.7838 (0.642) | 0.7498 | ok |

Forward AUC (reverse in brackets), 640 px crops less a 64 px edge.
Not ranked yet (missing crops): Reader v2
Gate A: d9v2 leads ink_9um seed42 by 0.1016 mean AUC: a clear win (at least 0.02)
```

The table rows are the committed CPU bars in `results.json`. A real run worked when the last line reads `Phase 0 done: N job(s) in M min. Gate table in WORK/phase0-gate.txt`, the exit code is 0, and the table has `v8in` and `v8in-1447` rows with all three crops.

## Checks and controls

- **Reverse-depth control, per crop.** Every job's AUC comes with the AUC of the reverse-direction map (mac-w045 step 6 and 7). Gate A ranks a reader only when its forward AUC beats its reverse AUC by at least `MIN_GAP` = 0.10 on every crop, and one reader beats another only by at least `MIN_LEAD` = 0.02 mean AUC (`kit/gate.py`). The table's Control column says `ok` when the gap holds.
- **Device check.** Each job inherits mac-w045's CPU against MPS check of v8in on a crop (`kit verify` with the reverse map as the control), run once on w045 and reused, or run on the job's own crop if w045's pass is missing.
- **Consistency check.** `kit gate` compares any Mac `ink_9um` seed 42 crop score with the committed CPU bar to four decimals and exits 1 on a mismatch, which means the crop, labels or code differ. This script then exits 1 too.
- **Standard crop only.** A Mac score counts only on the segment's committed crop (`segments` in `results.json`) with `inner` 64; others are listed as skipped by `kit gate`.

Claim label: Model output, for each AUC; the Gate A verdict is an Interpretation of those scores under the committed rule.

## Commands and options

### `bash scripts/mac-phase0.sh`

The script takes no arguments and has no `--help`: anything after the script name is ignored and the queue starts. It is configured only by the environment variables below.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORK` | `$HOME/scrolls-work` | The Mac work folder shared with [mac-w045](mac-w045.md) and passed on to it; `kit gate` reads `WORK/SEGMENT/results/auc_*.json` |
| `JOBS` | `v8in:0841-w00 v8in:0841-ag896 v8in:0841-ag405 v8in-1447:0841-w00 v8in-1447:0841-ag896 v8in-1447:0841-ag405` | Space-separated `MODEL:SEGMENT` jobs, run in this order. `MODEL` must be `v8in` or `v8in-1447` and `SEGMENT` one of `0841-w00`, `0841-ag896` and `0841-ag405`, the PHerc0841 segments mac-w045 accepts; every job is checked before any starts |
| `KEEP_GOING` | `0` | `1`: a failed job does not stop the queue; the script still exits 1 at the end. Otherwise the first failure stops it before the gate step |
| `DRY_RUN` | `0` | `1`: print each job that would run, start no job and no `caffeinate`, still print and save the gate table, and exit 0 |

mac-w045 reads its own variables (such as `V8IN_FP16`, `V8IN_BATCH` and `FRESH`) from the environment, so they pass through to every job.

## Python API

Not applicable: a shell script with no importable functions; see Commands and options.

## Inputs

| Input | Notes |
| --- | --- |
| `JOBS` | The queue; see Environment variables |
| `WORK/SEGMENT/results/auc_*.json` | Earlier Mac scores; a job counts as done when `kit gate` reads a score for its reader (`v8in` from `auc_v8in.json`, `v8in-1447` from `auc_v8in1447.json`) on that segment's standard crop with `inner` 64 |
| `docs/results.json` | The committed CPU bars and each segment's standard crop, read by `kit gate` through `gate.committed()` |

Each job's own inputs (surface volume, labels, checkpoints) are listed on the [mac-w045](mac-w045.md#inputs) page.

## Outputs

For each job it prints `[N/TOTAL] MODEL on SEGMENT: already scored, skipped`, or `== [N/TOTAL] MODEL on SEGMENT (about 20 min; log WORK/logs/phase0_SEGMENT_MODEL.log)` followed by mac-w045's own output and `[N/TOTAL] MODEL on SEGMENT: done in M min`. With `DRY_RUN=1` it prints `[N/TOTAL] MODEL on SEGMENT: would run MODEL=MODEL SEGMENT=SEGMENT QUICK=1 bash scripts/mac-w045.sh`. Then `== Gate A` and `kit gate`'s table (see [gate](gate.md#outputs)), saved to `WORK/phase0-gate.txt`.

| File | What it holds |
| --- | --- |
| `WORK/logs/phase0_SEGMENT_MODEL.log` | The full output of that job's mac-w045 run (`tee`), overwritten when the job reruns |
| `WORK/phase0-gate.txt` | The text Gate A table and verdict, overwritten on every run |
| `WORK/SEGMENT/results/auc_MTAG.json` and the rest | mac-w045's outputs per job; `MTAG` is `v8in` or `v8in1447` |

A macOS notification (title `Scrolls Phase 0`) and a terminal line report the end: `Phase 0 done: N job(s) in M min. Gate table in WORK/phase0-gate.txt`, or `Phase 0: N job(s) ran, failed: MODEL:SEGMENT ...`, or, at once, `MODEL on SEGMENT failed after M min; see its log`.

| Exit code | Meaning |
| --- | --- |
| `0` | Every job ran or was skipped and `kit gate` exited 0; or any `DRY_RUN=1` run that got past the job check |
| `1` | A job failed (at once, or at the end with `KEEP_GOING=1`), or `kit gate` exited 1 because a Mac score disagreed with its committed bar |
| `2` | A job in `JOBS` is not `v8in` or `v8in-1447` on `0841-w00`, `0841-ag896` or `0841-ag405`, or `kit gate` exited 2 because it could not read the scores |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `unknown job JOB (expected v8in\|v8in-1447:0841-w00\|0841-ag896\|0841-ag405)` on stderr, exit code 2 | A job that is not `v8in` or `v8in-1447` on `0841-w00`, `0841-ag896` or `0841-ag405`, such as `v8in:0841-w01` | Fix `JOBS`. Nothing ran |
| `MODEL on SEGMENT failed after M min; see its log` then `Stopping (KEEP_GOING=1 to continue past failures). Rerun to resume.`, exit code 1 | mac-w045 exited non-zero for that job: see its failure modes, such as the device check, a download, or exit code 3 for another GPU job holding the lock | Read `WORK/logs/phase0_SEGMENT_MODEL.log`, fix the cause and rerun; finished jobs are skipped |
| `Phase 0: N job(s) ran, failed: MODEL:SEGMENT ...`, exit code 1 | With `KEEP_GOING=1`, at least one job failed | As above, then rerun |
| `This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere).` in a job's log | Not run on an Apple Silicon Mac | Run it on the Mac; use `DRY_RUN=1` elsewhere |
| A job runs again although it finished | Its score is not on the standard crop with a 64 px edge (`kit gate` lists it under skipped), or the file is unreadable | Check `python -m kit gate WORK`; delete or move a non-standard file |
| `cannot read the scores: ...` after `== Gate A`, exit code 2 | `kit gate` could not read `docs/results.json` or a score file | Run from a clone; see [gate](gate.md#failure-modes) |
| No output at all, exit code 1 | `python3` is not on `PATH` (`command -v python3` fails under `set -e`) | Install Python 3 |

## How it works

1. Set `WORK`, `JOBS`, `KEEP_GOING`, `DRY_RUN`; find `python3`; create `WORK/logs`.
2. Check every job against the six accepted pairs (`v8in` or `v8in-1447` on `0841-w00`, `0841-ag896` or `0841-ag405`); exit 2 on the first that fails, before any job runs.
3. Unless `DRY_RUN=1`, start `caffeinate -i -w PID` in the background so the Mac does not idle-sleep while the script runs.
4. For each job in order: ask `kit gate` whether it is scored (`gate.committed()` for the standard crops, then `gate.from_mac(WORK, crops)`, which reads `WORK/SEGMENT/results/auc_*.json` and keeps only scores on the standard crop with `inner` 64); skip it if so; with `DRY_RUN=1` print what would run; otherwise run `MODEL=... SEGMENT=... QUICK=1 bash scripts/mac-w045.sh`, piped through `tee` into its log. A failure notifies and stops the queue unless `KEEP_GOING=1`.
5. Run `python -m kit gate WORK` with `PYTHONPATH` set to the checkout, piped into `WORK/phase0-gate.txt`, and keep its exit code.
6. With `DRY_RUN=1`, exit 0. Otherwise notify, exit 1 if any job failed, else exit with `kit gate`'s code.

There are no numeric constants in the script; the gate's are `MIN_LEAD` = 0.02, `MIN_GAP` = 0.10 and `INNER` = 64 in `kit/gate.py`.

## Cost and time

| Case | Time | Source |
| --- | --- | --- |
| One job, v8in in fp32 on a PHerc0841 crop, Apple M1 Pro | About 20 min | Script header and [mac.md](../mac.md#generalization-check-on-w045-one-command); an estimate from the per-step times below, not a recorded run |
| v8in on the 640 px crop at stride 21, 784 tiles | About 15 min per direction (1.1 to 1.2 s per tile) | [mac.md](../mac.md#watching-a-run), measured 2026-10-07 on the M1 Pro |
| Device check, CPU side, if w045's pass is missing | About 41 min (25 s per tile, 100 tiles) | Same |
| `DRY_RUN=1`, nothing to run | 0.5 s wall | This page, 2026-10-16, Linux cloud container |

The reverse control runs at stride 42 (a quarter of the tiles), so a job is less than two full passes. The whole queue runs locally on the Mac and rents nothing. Log it with `python -m kit run local SLUG -- bash scripts/mac-phase0.sh` (the local-compute rule, hard rule 9; see [run-local](run-local.md)).

## For agents

- **Command:** `DRY_RUN=1 bash scripts/mac-phase0.sh` to see the queue; `python -m kit run local SLUG -- bash scripts/mac-phase0.sh` for the real queue on the Mac. Machine-readable result afterwards: `python -m kit gate WORK --json`.
- **Parse:** each `[N/TOTAL]` line for skipped, would run or done; `WORK/phase0-gate.txt`, or `kit gate --json`, for the table and verdict; the per-job `WORK/SEGMENT/results/auc_v8in.json` and `auc_v8in1447.json` (`forward.auc`, `control.auc`).
- **Rerun:** Safe: finished jobs are skipped and mac-w045 reuses finished passes. A rerun overwrites the log of each job it runs and `WORK/phase0-gate.txt`.
- **Success:** Exit code 0, `Phase 0 done: ...`, and `v8in` and `v8in-1447` rows with all three crops and `ok` in the Control column.
- **Not a pass:** Exit code 0 from `DRY_RUN=1`; a reader listed as missing crops; a Control column that is not `ok`; a lead under 0.02; a gate exit code 1 (a Mac score that disagrees with its committed bar).
- **Go-ahead:** Nothing to run it on the user's Mac. Posting scores or the table needs Chase's yes first.
- **Never:** Run it on a laptop CPU in place of the Mac GPU; start it while another GPU job runs; call a map or an AUC a reading.

## Tests

```bash
python -m unittest tests.test_repo -v
```

`test_shell_scripts_parse` checks that the script exists and parses with `bash -n`; `test_mac_scripts_are_bash_32` checks that it uses no syntax macOS bash 3.2 lacks. Nothing tests the queue, the skip check or the exit codes. The gate it calls is tested by `tests/test_gate.py` ([gate](gate.md#tests)).

## History

- 2026-10-17: the job check accepts only the three PHerc0841 segments mac-w045 accepts; before, any `v8in:0841-*` or `v8in-1447:0841-*` passed, so a job such as `v8in:0841-w01` was queued and then failed in mac-w045 with `SEGMENT must be w045, 0841-w00, 0841-ag896 or 0841-ag405` in its log, after earlier jobs had run (`b112518`).
- 2026-10-07: first version: one Mac queue over v8in and v8in-1447 on the three PHerc0841 crops, resumable, with the Gate A table at the end (`bec6fb9`).

## Related

- [mac-w045](mac-w045.md): the script each job runs.
- [gate](gate.md): the Gate A rule and table.
- [mac.md](../mac.md#generalization-check-on-w045-one-command): the Mac guide, with per-step times.
- [w045 log](../logs/2026-10-08-w045-not-held-out.md): why the PHerc0841 crops, not w045, are the fair comparison.
- `results` and `segments` in [`results.json`](../results.json): the committed bars and standard crops.
