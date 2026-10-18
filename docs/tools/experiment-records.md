# experiment-records: saved scripts and scores of the 7 October public-data jobs

`scripts/experiments/` keeps, word for word, the scripts, logs and result JSON of the public-data jobs run on 7 October 2026 (the CPU cloud jobs, Grok's lanes A to I, the tricks runs and the mesh study), so their numbers can be traced and their checks rerun.

| Field | Value |
| --- | --- |
| Id | `experiment-records` |
| Status | Retired |
| Kind | data |
| Area | Records and provenance |
| Run | None: saved records. Their regression tests run as under Tests |
| Code | `scripts/experiments/` |
| Tests | `tests/test_grok_synthesis.py`, `tests/test_laneb.py`, `tests/test_laneb_archive.py`, `tests/test_lane_f_regression.py`, `tests/test_lane_g_regression.py`, `tests/test_laneh_job.py`, `tests/test_cropscan.py`, and the test files inside seven record folders (see Tests) |
| Needs | Nothing to read them. The regression tests: Python 3.10 or newer; CI runs them with every extra of the package installed. A rerun of a job: what its folder's README or notes name, usually villa with PR #1865, the released checkpoints and data from the open-data bucket |
| Runs on | Reading: anywhere. The 45 tests inside the record folders take about 3 s, and six of the `tests/` files above (lanes A, B, F, G and H) under 2 s (measured 2026-10-16, cloud container). The original jobs ran in 4-CPU cloud containers and on Chase's Mac ([cloud README](../../scripts/experiments/2026-10-07-cloud/README.md)) |
| Network | None to read or test. A rerun downloads what its scripts name: the open-data bucket, Hugging Face checkpoints, GitHub releases |
| Writes | Nothing when read or tested. A rerun writes where its script says (most under `$HOME/scrolls-work` or `$HOME/scrolls-cpu`); several scripts refuse to overwrite the saved outputs |
| Go-ahead | Not needed to read or test. Running the lane H fine-tune would rent GPUs and needs Chase's budget decision first (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-07 |
| License | Apache-2.0, like the rest of the repository ([LICENSE](../../LICENSE)); no scroll data, maps or weights are in these folders |
| Replaced by | Nothing |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

On 7 October 2026 many agents ran jobs on public labeled data at once: twelve CPU cloud jobs on PHerc0841 and PHerc0139 w045 crops, Grok's lanes A to I (label-free signals, a fiber reader, crop placement, a fine-tune plan), the "tricks" runs (checkpoint soup, depth windows, mirror test-time augmentation, ensembles) and the mesh-placement study. Each job committed its scripts, its `results.json` or JSON outputs, its logs and its `notes.md` under `scripts/experiments/`. This folder is that record. The dated logs in `docs/logs/` interpret the numbers; this folder holds what produced them.

The records are frozen: they keep their original wording, even where later reviews corrected an interpretation. `tests/test_repo.py` exempts `scripts/experiments/` from its wording and link checks for that reason (its `HISTORICAL` list), and corrections live in new logs or in the record's own review notes. Some scripts were later guarded so they cannot be run by accident as if they were current analyses (see Failure modes).

It is not a tool to run for new work, which is why its status is Retired. Several jobs stopped early or were never run; the table below says which. Every score in it is model output against published labels, not a reading, and nothing here touches a target scroll.

Two terms used below: a "lane" is one of Grok's parallel research tracks of 7 October (A to I); a "crop" is the 640 px window of densest labeled ink per segment, scored with a 64 px edge left out (`--inner 64`).

## When to use it

- To trace a number in a log, `docs/results.json` or `docs/tricks.md` back to the script and settings that produced it.
- To rerun the saved regression tests after a change to a `kit` function they import.
- To reuse a job's crop coordinates, settings or scoring commands as a starting point, copied into a new place.

Do not use it:

- To run new experiments: start a ledger record with `python -m kit run init` ([run-ledger](run-ledger.md)) and wrap local runs in `python -m kit run local` ([run-local](run-local.md)); GPU jobs get a Modal run spec in `docs/compute/modal-specs/`.
- To score maps: use [`auc`](auc.md) and [`hpscore`](hpscore.md), which these jobs called.
- To edit a record, even to fix a wrong claim: write the correction in a new dated log.
- As evidence on its own: read the record's log first, since several lane conclusions were later qualified (lanes A, B, I).

## The records

Every job used public labeled data only: PHerc0841 w00, ag896 and ag405, and PHerc0139 w045. PHerc0841 is in the training data of none of `ink_9um`, v8in, d9v2 and Reader v2, but possibly in Hecate's ([log](../logs/2026-10-09-pherc0841-hecate.md)). w045 is not held out from `ink_9um`, which trained on its 2.4 um render, nor from its fine-tunes ([log](../logs/2026-10-08-w045-not-held-out.md)).

### `2026-10-07-cloud/`: twelve CPU cloud jobs

Their shared rules, setup, crops and result-row format are in [the folder's README](../../scripts/experiments/2026-10-07-cloud/README.md).

| Folder | What it ran | State in the record | Where the results are |
| --- | --- | --- | --- |
| `baseline/` | Raw CT brightness baselines, segment overlap, collation of two traces of one sheet, sampling noise | Done | Its JSON and text outputs; [overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md) |
| `tricks/` | Soup, depth windows, mirror TTA, depth shuffle, Reader v2, ensembles on the PHerc0841 crops | Stopped early: w00 and ag896 scored, ag405 unfinished, w045 dropped | `results.json` (56 rows), `tables.md`, `notes.md`; [`tricks.md`](../tricks.md), [cloud partial log](../logs/2026-10-07-cloud-partial.md) |
| `thresholds/` | Leave-one-sheet-out ink threshold, published null rules on known text, how much surface a null needs | Parts 2 and 3 on w00; part 1 not run in the record; the script was corrected later and not rerun | `results.json` (10 rows), `part2_w00.json`, `part3_w00.json`, `notes.md`; [novel checks log](../logs/2026-10-07-novel-checks.md) |
| `finetune/` | Smoke test of v8in's PHerc1447 fine-tune loop, a data inventory and GPU-hour estimates | Smoke test not run (blocked); inventory done | `results.json`, `idea2_inventory.json`, `notes.md`; [training plan](../plans/2026-10-07-training.md) |
| `laneH-finetune/` | Preregistered fine-tune of `ink_9um` seed 42 as a Modal GPU job | Never run; no numbers exist | `README.md` (the preregistration), `results.json` ("not run"); [lane H log](../logs/2026-10-07-grok-laneH.md) |
| `v8in-w00/` | Base v8in, `ink_9um` and d9v2 on the w00 crop, with ensembles | In progress when saved; no `results.json` | `notes.md` |
| `v8in-ag896/` | The same on ag896 | Only the `ink_9um` and d9v2 bars scored | `results.json` (2 rows), `notes.md`, `status.json` |
| `v8in-ag405/` | The same on ag405 | Only the `ink_9um` and d9v2 bars scored | `results.json` (2 rows) |
| `v8in1447-w00/` | Youssef Nader's PHerc1447 fine-tune of v8in (v8in-1447) and d9v2 on the w00 crop, with ensembles | Done at forward stride 42 and reverse stride 64 | `results.json` (4 rows), `timings.json`, `notes.md`; [cloud partial log](../logs/2026-10-07-cloud-partial.md) |
| `v8in1447-ag896/` | The same on ag896 | Scripts only; no results | `notes.md` |
| `v8in1447-ag405/` | The same on ag405 | Partial: d9v2 scored, v8in-1447 unfinished | `results.json` (1 row), `scores/`, `notes.md` |
| `v8inwin-ag405/` | v8in on each 24-layer depth window of ag405 | Scripts only; no results | Nothing saved beyond the scripts |

### Lanes, tricks and the mesh study

| Folder | What it ran | Outcome as recorded | Where the results are |
| --- | --- | --- | --- |
| `2026-10-07-grok-laneA/` | Cross-analysis of the cloud jobs' records against bootstrap noise (`synth.py`) | Kept byte for byte; its significance verdicts were withdrawn on review | `synth.json`, `synth.out`; [lane A log](../logs/2026-10-07-grok-laneA.md) |
| `2026-10-07-grok-laneB/` | Label-free checks of ink maps on w00 and w045 (stroke width, fibers, geometry, depth), with reverse controls | Historical and preliminary; predates the mesh-hole and supervision corrections | `results/*.json`, `results/run_mac.log`; [lane B log](../logs/2026-10-07-grok-laneB.md) |
| `2026-10-07-grok-laneC/` | A model-free texture feature and its rank fusion with `ink_9um` | Both null (commit `d3074de`) | `results.json`; [lane C log](../logs/2026-10-07-grok-laneC.md) |
| `2026-10-07-grok-laneD/` | The fiber-orientation reader, [`fibertensor`](fibertensor.md), trained on one segment and scored on another, against brightness and `ink_9um` | Null against brightness and `ink_9um` (commit `ca9c8c4`) | `results/*.json`; [lane D log](../logs/2026-10-07-grok-laneD.md) |
| `2026-10-07-grok-laneF/` | Four experiments: histogram matching across scrolls, two-reader disagreement, depth-profile transfer, self-training | All four null (commit `4d8dfee`) | `results.json`, `logs/`; [lane F log](../logs/2026-10-07-grok-laneF.md) |
| `2026-10-07-laneG/` | Five model-free pixel signals and a line-period cue, preregistered in [`prereg/2026-10-07-grok-laneG.md`](../prereg/2026-10-07-grok-laneG.md) | Five signals null on both segments, the line-period cue inconclusive (commit `18ea482`) | `results.json`, `signals.log`; [lane G log](../logs/2026-10-07-grok-laneG.md) |
| `2026-10-07-grok-laneI/` | Crop placement sensitivity, a downsampled proxy and crop scan speed on w00, preregistered in [`prereg/2026-10-07-grok-laneI.md`](../prereg/2026-10-07-grok-laneI.md) | Its R1 and R2 conclusions are not validated (nonfinite intervals); P1 is descriptive | `results.json`, `run.log`; [lane I log](../logs/2026-10-07-grok-laneI.md); the tested helper is [`cropscan`](cropscan.md) |
| `2026-10-07-tricks/` | The scripts behind the measured table in `docs/tricks.md` (crops and bars, soup, z windows, mirror TTA, shuffle, Reader v2, the fine-tune smoke test) | Scripts only; Linux bash with associative arrays, not for macOS bash 3.2 | [its README](../../scripts/experiments/2026-10-07-tricks/README.md); numbers in [`tricks.md`](../tricks.md) and `2026-10-07-cloud/tricks/` |
| `2026-10-07-mesh-hypothesis/` | Whether published meshes and cross-scan renders sit where the metadata says: depth, geometry and shift checks | Done | [mesh hypothesis log](../logs/2026-10-07-mesh-hypothesis.md), [`data/mesh-hypothesis/`](../data/mesh-hypothesis/README.md); the module is [`meshaudit`](meshaudit.md) |

Lane E has no folder here, and lane H's job lives under `2026-10-07-cloud/laneH-finetune/`. The review of the merged lanes is in [`evidence/2026-10-07-merge-review/`](../evidence/2026-10-07-merge-review/README.md).

## Quick start

```bash
# read one saved result row
python3 -c "import json; r = json.load(open('scripts/experiments/2026-10-07-cloud/v8in1447-w00/results.json'))[0]; print({k: r[k] for k in ('job', 'segment', 'reader', 'auc_as_stored', 'auc_reversed')})"

# rerun the regression tests kept inside the record folders, as CI does
for d in $(find scripts/experiments -name 'test_*.py' -not -path '*__pycache__*' -exec dirname {} \; | sort -u); do
  python3 -m unittest discover -s "$d" -p 'test_*.py'
done
```

Run from the repository root on 2026-10-16, it printed:

```
{'job': 'v8in1447-w00', 'segment': '0841-w00', 'reader': 'v8in-1447', 'auc_as_stored': 0.8381, 'auc_reversed': 0.5932}
Ran 11 tests in 0.024s
OK
Ran 1 test in 0.058s
OK
...
Ran 8 tests in 0.019s
OK
```

It worked when every folder ends with `OK`. Seven folders hold tests, 45 in all.

## Checks and controls

- **Each job's own control.** Every scored map in the cloud jobs has its reverse-depth map scored the same way (`auc_reversed`), and many have a depth-shuffled one (`auc_shuffled`). A forward AUC here means something only next to its control: for example v8in-1447 on the w00 crop, 0.8381 as stored against 0.5932 reversed, with forward stride 42 and reverse stride 64, so the strides do not match ([cloud partial log](../logs/2026-10-07-cloud-partial.md)).
- **Reproduction bars.** The cloud README fixes bars a rerun must match to about three decimals: `ink_9um` seed 42 forward 0.8061 (w00), 0.6594 (ag896), 0.7838 (ag405); d9v2 0.8994, 0.8230, 0.8319 ([cloud README](../../scripts/experiments/2026-10-07-cloud/README.md)). The `v8in-ag405` job's `ink_9um` score matched the 0.7838 bar (commit `69a4e11`).
- **Preregistration.** Lanes G and I and the lane H job wrote their readout rules before any run (their logs name the commits); lane C and lane F record theirs in their logs.
- **Regression tests.** The `test_*.py` files and the `tests/` files above check the saved scripts' logic and guards, and CI runs them on every push, so a later change to a `kit` function they use cannot silently change them.

Claim label: Model output and Null, as each record's log labels them, on public labeled data; the records make no claim of their own.

## Commands and options

Not applicable: these are saved records, not a tool with options; each script's own arguments are in its source and in its folder's README or notes.

## Python API

Not applicable: the scripts are frozen records, not a library; import nothing from them in new work.

## Inputs

| Input | Where it came from | Notes |
| --- | --- | --- |
| Surface volumes and labels | The Vesuvius Challenge open-data bucket, fetched with `python -m kit fetch` | Not in git. Crops and surface shapes per segment are in the cloud README |
| Checkpoints | `ink_9um` seeds 42 and 43 (Hugging Face `scrollprize/ink_9um`), v8in and v8in-1447 (Hugging Face), d9v2 (TAUIL-Abd-Elilah's v1.0 GitHub release), Reader v2 (Hugging Face `domenicor046/reader-v2`) | Not in git; the record names revisions and SHA-256 where the job wrote them |
| Ink maps | Made by the jobs with villa PR #1865 or `scripts/v8in_run.py` | Not in git (no maps in git, hard rule 6) |

## Outputs

The cloud jobs' `results.json` files are JSON lists of rows with these keys, leaving out what does not apply ([cloud README](../../scripts/experiments/2026-10-07-cloud/README.md), "Result rows"):

| Field | Type | Meaning |
| --- | --- | --- |
| `job` | str | The job's folder name |
| `segment` | str | `0841-w00`, `0841-ag896`, `0841-ag405` or `w045` |
| `window` | str | `crop` |
| `inner_px` | int | Edge left out, 64 |
| `map_from` | str | `bare-crop` (inferred on the crop) or `full` (cut from a whole-segment map) |
| `reader` | str | The model or ensemble |
| `settings` | object | Checkpoint, revision, stride, layer window, ensemble method |
| `device` | str | `cpu` |
| `auc_as_stored`, `auc_reversed`, `auc_shuffled` | float | AUC of the map, its reverse-depth control and its depth-shuffled control |
| `hp_r`, `hp_r_reversed` | float | Letter-scale score ([`hpscore`](hpscore.md)) of the map and its reverse |
| `ink_px` | int | Labeled ink pixels scored |
| `seconds` | float | Wall time |
| `notes` | str | Anything odd |

The lanes write their own JSON layouts, described in their logs. `laneH-finetune/results.json` holds one row with `"status": "not run"`.

## Failure modes

These are the guards later added to stop a frozen script from being rerun by accident as if it were current.

| What you see | Why | What to do |
| --- | --- | --- |
| `Archival run only: R1/R2 used nonfinite bootstrap intervals. New validated runs require corrected interval handling and input provenance. For a deliberate unvalidated replay, set SCROLLS_REPLAY_HISTORICAL_LANEI=1.`, exit code 1 | `2026-10-07-grok-laneI/run.py` run without the replay flag | For new crop scans use [`cropscan`](cropscan.md); set the variable only to replay the old analysis on purpose |
| `Archival launcher only: these calculations predate the support corrections.`, exit code 2 | `2026-10-07-grok-laneB/run_mac.sh` run without `SCROLLS_RUN_HISTORICAL_LANEB=1` | Use the corrected `checks.py` and `laneb.py` for new work; set the variable only for a deliberate historical replay |
| `Historical synth.json is immutable; use a new output path.` | Lane A's `synth.py` asked to write over the saved `synth.json` | Give a new output path |
| `results must stay outside the tracked job directory`, `refusing to overwrite historical collected output` | Lane H's `collect.py` pointed at the record folder or the saved output | Write to a new folder outside the repository |
| `Not run: explicit LANEH_EXECUTE=1 required`, `No GPU execution without prior budget authorization and LANEH_GPU_AUTHORIZED=1` | Lane H's `run_job.sh` run without its execution flags; `PHASE=check` (the default) only prints `Not run.` and exits 0 | Do not run it without Chase's budget decision; it was never validated end to end |
| `not run: --execute is required for authorized training`, `GPU training requires explicit --allow-gpu and prior budget authorization`, `Not run: no remote launch without --allow-gpu and separate budget authorization` | Lane H's `finetune_ink9um.py` or `modal_app.py` run without their flags | As above |
| `villa checkout differs from the pinned compatible revision`, `base checkpoint SHA256 differs from the pinned published seed42 artifact` | Lane H's trainer found another villa revision or checkpoint than the one it was written for | Use the pinned revision and checkpoint, or treat the run as a new experiment with its own preregistration |
| `calibration cannot use another trace of the held-out sheet`, `calibration cannot pool duplicate traces of one sheet` | The corrected `thresholds/analyze.py` refuses to calibrate on a trace of the same sheet (w00 and ag896 trace one sheet) | Calibrate on an independent sheet, as its notes say |
| `No experiment regression tests found` | The CI step found no `test_*.py` under `scripts/experiments/` | The folder or its tests were removed; restore them |

Other scripts in these folders stop with Python errors when their inputs (the `$W` work folder, maps, checkpoints) are missing; read their notes for the layout they expect.

## How it works

1. On 7 October each job ran in its own container or on Chase's Mac, following its brief (for the cloud jobs, [the cloud README](../../scripts/experiments/2026-10-07-cloud/README.md)), and committed only scripts, small JSON, logs and Markdown to its own branch.
2. The branches were reviewed and merged (PRs #6 to #18, and later record branches); the review receipts are in [`evidence/2026-10-07-merge-review/`](../evidence/2026-10-07-merge-review/README.md). Where a review found a wrong interpretation, the saved outputs stayed byte for byte, the script was corrected or guarded, and the correction went into notes or logs.
3. `tests/test_repo.py` leaves `scripts/experiments/` out of its wording and link checks (`HISTORICAL`), so old wording and old links stay as written.
4. The CI's `verify` job (`.github/workflows/check.yml`, step "Experiment regression tests") runs `unittest discover` in every folder under `scripts/experiments/` that holds a `test_*.py`, and fails when none is found.

## Cost and time

The regression tests take about 3 s (45 tests in seven folders, measured 2026-10-16, cloud container). The original jobs' times are in each job's `notes.md` and `seconds` fields; the cloud README estimated about 8 s per v8in tile on 4 cores. Rerunning the CPU jobs takes hours of CPU each and so belongs on Modal under the Modal rule (hard rule 11), with a run spec; the lane H fine-tune needs a GPU. Nothing here was measured for this page beyond the tests.

## For agents

- **Command:** `python3 -m unittest discover -s scripts/experiments/FOLDER -p 'test_*.py'` for one folder's tests; read `results.json` with `json.load`.
- **Parse:** In a cloud job's `results.json`, `reader`, `segment`, `auc_as_stored` with `auc_reversed` (and `auc_shuffled`), and `settings` for strides and windows.
- **Rerun:** The tests are safe and write nothing. Do not rerun the jobs inside these folders: several refuse to overwrite saved outputs, and any rerun goes to a new folder outside `scripts/experiments/`.
- **Success:** Every test folder ends with `OK`.
- **Not a pass:** A forward AUC without its reverse; a score on w045 for `ink_9um` or its fine-tunes; any lane B or lane I conclusion taken without its review notes; lane A's withdrawn significance verdicts; any number from `laneH-finetune` (none exist).
- **Go-ahead:** Running the lane H GPU job, or any rerun that rents compute, needs Chase's budget decision.
- **Never:** Edit, reword or delete these records; add new jobs here; describe a score as a reading; copy a target-scroll result into public records.

## Tests

```bash
python -m unittest tests.test_grok_synthesis tests.test_laneb tests.test_laneb_archive tests.test_lane_f_regression tests.test_lane_g_regression tests.test_laneh_job tests.test_cropscan -v
for d in $(find scripts/experiments -name 'test_*.py' -not -path '*__pycache__*' -exec dirname {} \; | sort -u); do python3 -m unittest discover -s "$d" -p 'test_*.py' -v; done
```

The `tests/` files cover lane A's descriptive synthesis, lane B's statistics and its guarded launcher, the prospective code of lanes F and G (without CT or inference) while their archived measurements stay unchanged, lane H's guards (no run without its flags, pinned inputs, no overwrite), and, in `tests/test_cropscan.py`, lane I's guarded script. The seven record folders with their own tests are `2026-10-07-cloud/thresholds`, `tricks`, `v8in-ag896`, `v8in1447-ag405`, `v8in1447-ag896`, `v8in1447-w00` and `2026-10-07-grok-laneC`; they check the corrected calibration, collection, status and control-matching logic. None of them reruns inference or scores a real map.

## History

- 2026-10-07: the mesh hypothesis scripts, the last record folder added (`e14b033`). No folder has been added since; this page marks the records Retired (saved history, not a tool for new work).
- 2026-10-07: experiment regression tests run in CI (`b768319`).
- 2026-10-07: lane I's `run.py` and lane B's `run_mac.sh` guarded against accidental prospective use, their conclusions qualified (`210e023`, `da95aa0`).
- 2026-10-07: lane H's fine-tune preregistered as a Modal GPU job and guarded; never run (`3a9e06c`, `0c40f6c`, [PR #25](https://github.com/ChaseHendrick/Scrolls/pull/25)).
- 2026-10-07: lanes A to G recorded; lanes C, D and F null, and lane G null but for one inconclusive cue (`84a9ef2`, `d3074de`, `ca9c8c4`, `4d8dfee`, `18ea482`).
- 2026-10-07: the cloud jobs merged ([PR #6](https://github.com/ChaseHendrick/Scrolls/pull/6) to [PR #10](https://github.com/ChaseHendrick/Scrolls/pull/10)) and the remaining job branches brought in for review (`b68f30f`, `393bc75`, `eb2aca0`, `69054e9`, `1be88ee`).

## Related

- [The cloud jobs' README](../../scripts/experiments/2026-10-07-cloud/README.md): the rules, setup, crops and bars every cloud job followed.
- [Cloud partial log](../logs/2026-10-07-cloud-partial.md) and [`tricks.md`](../tricks.md): the reviewed numbers from these records.
- [Merge review evidence](../evidence/2026-10-07-merge-review/README.md): what each review changed.
- [`run-ledger`](run-ledger.md) and [`run-local`](run-local.md): where new jobs are recorded now.
- [`auc`](auc.md), [`hpscore`](hpscore.md), [`fibertensor`](fibertensor.md), [`cropscan`](cropscan.md), [`meshaudit`](meshaudit.md): the tools these jobs used or produced.
- `held_out` in [`results.json`](../results.json): which segment is held out from which model.
