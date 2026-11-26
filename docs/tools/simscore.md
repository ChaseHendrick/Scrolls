# simscore: score simulated CT under the Sim Realism Standard

Reference scorer of SRS-1: runs the released simcritic judge with every setting fixed, gates it on planted checks and a real-against-real control, applies the fixed bar and the calibrated sample-size rule, and writes a JSON record anyone can check.

| Field | Value |
| --- | --- |
| Id | `simscore` |
| Status | Experimental |
| Kind | kit entry point |
| Area | Scoring and controls |
| Run | `python -m kit.simscore reference`, `score`, `check`, `calibrate`; `from kit import simscore` |
| Code | `kit/simscore.py` |
| Tests | `tests/test_simscore.py` |
| Needs | Python 3.10 or newer, numpy, scipy, torch (CPU or CUDA) and scikit-image for the critics (as [simcritic](simcritic.md)); `check` needs only the standard library; a reference npz (R343-v1 from `reference`, or your own slices) and an npz of at least 240 simulated tiles of 256 px or more |
| Runs on | CPU or GPU. `reference`: 14 s; a `--smoke --steps 2` score: 25 s; `calibrate`: 290 s (all in a 4-core cloud container, 26 Nov 2026). A full score: about 5 hours on one CPU worker at simcritic's 25 Nov rate (not timed end to end); a GPU is faster |
| Network | `reference` only: `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (PHerc0343P CT) and `huggingface.co` (the organizers' public surface labels, for the gray-value scale); the rest is offline |
| Writes | `reference`: the npz named; `score`: the record named by `--out`; `calibrate`: the JSON named by `--out`; `check`: nothing |
| Go-ahead | Not needed to run; publishing a record is the scorer's owner's choice |
| Released | Not yet: draft PR, waiting for the owner's yes |
| Checked | 2026-11-26 against commit `51e816f` |

## What it does

The [Sim Realism Standard SRS-1](../standards/sim-realism.md) fixes one way to rate how real a set of simulated scroll CT tiles looks, so sets from different teams can be compared. This tool is its reference implementation. It calls [simcritic](simcritic.md) with SRS-1's settings (128 px windows, the `feat`, `cnn` and `cnn_half` critics, 3 grouped folds, seeds 0 and 1, 800 CNN steps), in a fixed order: size checks, planted checks, the even-against-odd control, then the odd slices against the set.

It turns the result into a status. PASS and FAIL come from simcritic's fixed bar (the set's worst critic AUC at most the control's worst plus 0.05, and at most 0.60). Then the sample-size rule of the preregistered null calibration applies: no reference size tried was admitted, so a PASS is reported as INCONCLUSIVE and a FAIL counts only beyond D99 (0.2454 on R343-v1's 6 slices). A failed gate gives VOID; a run below SRS-1's sizes or steps gives SMOKE.

The record holds every AUC, the window digests, the scorer's file digests, the generator, the attempt count and a SHA-256 over the record. `check` recomputes the gates, verdict and status from those numbers, so a reader can test a published record without a GPU.

A PASS would mean no SRS-1 critic told the set from that reference: Model output, not proof that the set is real. It scores gray values only.

## When to use it

- Before you publish or train on simulated tiles and want a realism number others can compare with.
- To check someone else's SRS-1 record (`check`).
- To rerun the calibration behind the sample-size rule (`calibrate`).

Do not use it:

- as a training loss or tuning target (see the standard's fair play rules); to explore what gives a set away, call [simcritic](simcritic.md) with its attribution views instead;
- to score ink or surfaces against labels: use [auc](auc.md);
- on scans you may not use for development.

## Quick start

```bash
python -m kit.simscore score --reference REF.npz --sim SIM.npz --generator "NAME VERSION" --attempts 0 \
    --smoke --steps 2 --out record.json
python -m kit.simscore check record.json
```

`REF.npz` holds `ct` (slices) and optionally `cover` and `name`; `SIM.npz` holds tiles under `image`. With 6 stand-in slices and 8 `kit.hardcases` tiles it printed (26 Nov 2026, 25 s in a 4-core cloud container):

```
SRS-1 SMOKE: worst 0.6944444444444444, control 0.19791666666666669, gap to bar 0.4465
a smoke run (sizes or steps below SRS-1) is never a verdict
SRS-1 record record.json: OK (status SMOKE)
```

`check` exiting 0 means the record is internally consistent. Drop `--smoke --steps 2` and pass 240 or more tiles for a real score; get R343-v1 with `python -m kit.simscore reference R343.npz`.

## Checks and controls

- **Planted gate:** two random halves of the reference must stay under 0.65 (feat and cnn), and a noised half (sd 0.08) and a blurred half (sigma 1.0) must reach 0.90. On R343-v1 on 25 Nov 2026 (simcritic, the same windows): 0.506 and 0.496; 1.0 and 0.993; 1.0 and 0.999.
- **Control gate:** even against odd slices, worst AUC under 0.65. R343-v1: 0.473 (25 Nov 2026).
- **Null calibration:** a perfect simulator fails the fixed bar 0.595, 0.485 and 0.285 of the time at 6, 12 and 24 stand-in slices; hence the sample-size rule ([evidence](../evidence/srs1-calibration-1126/README.md)).
- **Record check:** `check` fails a record whose settings, critic means, worsts, gates, verdict, status or digest do not recompute (tests plant each kind of tampering).

Cross-scroll validation: claim-dependent. SRS-1 rates a set against one named reference; a realism claim across scans needs a record on each. The calibration is synthetic.

Claim label: Model output (critic AUCs and the status); Interpretation where the standard reads them.

## Commands and options

### reference

`python -m kit.simscore reference OUT`: fetches R343-v1 and prints its slice count, window count and digest (`0c18a31a...4ad7`).

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | npz path to write |

### score

| Option | Default | Meaning |
| --- | --- | --- |
| `--reference` | required | reference npz |
| `--sim` | required | npz of simulated tiles |
| `--key` | `image` | npz key of the tiles |
| `--generator` | required | simulator name and version, for the record |
| `--attempts` | required | sets your team scored under SRS-1 on this reference before this one |
| `--trained-on` | none | even slice names the generator was fitted to (odd ones are refused) |
| `--device` | `cpu` | `cpu` or `cuda` |
| `--smoke` | off | allow small sizes and `--steps`; status SMOKE |
| `--steps` | 800 | CNN steps; other values only with `--smoke` |
| `--out` | required | record path |

### check

`python -m kit.simscore check RECORD [--json]`: prints OK or the problems.

| Option | Default | Meaning |
| --- | --- | --- |
| `record` | required | the record JSON |
| `--json` | off | print `{"ok", "problems", "status"}` |

### calibrate

`python -m kit.simscore calibrate --out OUT.json`: reruns the preregistered null calibration on the same seeds.

| Option | Default | Meaning |
| --- | --- | --- |
| `--out` | required | JSON path to write |
| `--reps` | 200 | null replicates per size |
| `--power-reps` | 100 | replicates per shifted simulator |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `ScoreError` | exception | | ValueError subclass for every refusal |
| `file_sha256(path)` | hex SHA-256 | `OSError` | Of a file's bytes |
| `scorer_digests()` | dict | | SHA-256 of `simcritic.py` and `simscore.py` |
| `reference_r343(progress=print)` | dict `ct`, `cover`, `name`, `id`, `lo_hi` | `ScoreError`, network errors | Fetches R343-v1 |
| `save_reference(ref, path)` | None | | Writes the reference npz |
| `load_reference(path)` | dict | `KeyError` without `ct` | Slices in file order |
| `load_sim(path, key="image", n=240)` | list of 2D arrays | `ScoreError` on a missing key | The first N tiles, no picking |
| `gates(planted, control)` | dict of bools | | `planted_same`, `planted_noise`, `planted_blur`, `control` |
| `verdict(worst, control_worst)` | dict | | The fixed bar; FAIL with gap None when either is None |
| `d99_for(n_groups, table=None)` | float or None | | D99 of the nearest calibrated size at or above |
| `status(v, n_groups, admit=..., table=None, gate=None, smoke=False)` | (status, reason) | | PASS, FAIL, INCONCLUSIVE, VOID or SMOKE |
| `score(ref, tiles, generator, attempts, trained_on=(), device="cpu", steps=800, smoke=False, progress=print)` | record dict | `ScoreError` | The SRS-1 scoring |
| `record_digest(rec)` | hex SHA-256 | | Over the record without `record_sha256` |
| `check(rec)` | list of problems | | Empty when consistent |
| `calibrate(groups=(6, 12, 24), reps=200, power_reps=100, ...)` | dict | | The preregistered null calibration |
| `main(argv=None)` | exit code | | The command line |

Constants: `STANDARD`, `SETTINGS`, `MIN_GROUPS` (6), `MIN_SIM_TILES` (240), `MIN_TILE` (256), `PLANTED_SAME_MAX` (0.65), `PLANTED_SHIFT_MIN` (0.90), `CONTROL_MAX` (0.65), `MARGIN` (0.05), `CEILING` (0.60), `ADMIT_GROUPS` (None), `D99` ({6: 0.2454, 12: 0.2045, 24: 0.0788}), `R343`.

## Inputs

- Reference npz: `ct`, a stack (N, H, W) or object array of 2D float slices (any gray scale; each window is rescaled), optional `cover` (bool, same shapes; windows need 0.98 cover), optional `name` and `id`. At least 6 slices. Even and odd mean position in file order.
- Set npz: 2D tiles under `--key`, uint8 or float, at least 256 px a side; the first 240 are used.

## Outputs

`score` writes the record described in the standard ([fields](../standards/sim-realism.md#the-record)) and prints one status line, the reason and the path. `calibrate` writes per-size replicates, `false_fail`, `d99`, power rows, `admit_groups`.

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `check`, the record is consistent (whatever its status) |
| `1` | `check` found problems |
| `2` | A bad argument, or `check` could not read the record |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `reference has N slices; SRS-1 needs at least 6` and the tile count line | Sizes below SRS-1 | More slices or tiles, or `--smoke` for a pipeline check |
| `CT...and labels...differ` | The R343 stores no longer match | Report it; R343-v1 cannot be rebuilt as published |
| `...: no key...(keys...)` | The tiles are under another npz key | Pass `--key` |
| `SRS-1 uses...CNN steps; other values need smoke=True` | `--steps` changed without `--smoke` | Use 800, or `--smoke` |
| `attempts must be the count of sets scored before this one (0 for the first)` | `attempts` missing or negative | Pass the true count |
| `odd slices...trained the generator; SRS-1 scores sets on the odd slices` | The generator saw test slices | Refit on even slices only, or use another reference |
| `trained_on names...are not slices of the reference` | A typo, or names from another reference | Use the reference's slice names |
| `cannot read record...:` (exit 2) | `check` got a missing or broken file | Pass the record path |

## How it works

1. Size checks (`MIN_GROUPS`, `MIN_SIM_TILES`, `MIN_TILE`), then windows with `simcritic.grid_windows` and `half`.
2. `simcritic.planted` on all reference windows (feat and cnn, 800 steps).
3. `simcritic.judge` for even against odd (control) and odd against the set, all three critics, seeds 0 and 1.
4. `gates`, `verdict`, then `status` with `ADMIT_GROUPS` and `D99`, which come from the calibration (`tests/test_simscore.py` checks them against its evidence file).
5. The record gets the scorer's file digests and a SHA-256 over itself.

The method is a classifier two-sample test (Lopez-Paz and Oquab, [arXiv 1610.06545](https://arxiv.org/abs/1610.06545), ICLR 2017), with grouped folds and the worst of several critics.

## Cost and time

Measured 26 Nov 2026 in a 4-core cloud container: `reference` 14 s; a smoke score of 6 slices and 8 tiles at 2 steps 25 s; `calibrate` 290 s on one core (0.0052 kWh). A full score was not timed: it runs 11 CNN critic runs, and simcritic measured 25 to 30 minutes for one 3-fold CNN critic on a Hugging Face `cpu-upgrade` machine (25 Nov 2026), so expect about 5 hours on one CPU worker. No rented compute is needed for `check`.

## For agents

- **Command:** `python -m kit.simscore score --reference R343.npz --sim SIM.npz --generator NAME --attempts N --out rec.json`, then `python -m kit.simscore check rec.json --json`.
- **Parse:** the record's `status`, `reason`, `verdict.gap_to_bar`, `result.worst`, `control.worst`; `check --json` gives `ok` and `problems`.
- **Rerun:** safe; `score` overwrites `--out`. CNN AUCs differ slightly by device and torch version.
- **Success:** `check` exit 0 and a status that is not VOID or SMOKE.
- **Not a pass:** a PASS from the bar (SRS-1 reports it as INCONCLUSIVE); any SMOKE record; a record whose `check` fails; a set scored against odd slices its generator saw.
- **Go-ahead:** Nothing to run; posting records follows the repository's rules for outward posts.
- **Never:** use the critics or the scores as a training loss; edit a record by hand; call an INCONCLUSIVE a pass.

## Tests

`python3 -m unittest tests.test_simscore` (12 tests, about 25 s on CPU with torch): the bar and its None case, the gates, every status, D99 lookup, record checks against planted tampering (critic means, settings, digest, odd trained slices, status), the calibration constants against the evidence file, settings against simcritic, reference npz round trip, refusals, and a smoke score whose record passes `check`. Rule tests need no numpy. Not covered: `reference` (network) and a full score.

## History

- 2026-11-26: first version with the SRS-1 draft and its null calibration (`51e816f` preregistration; PR to follow).

## Related

- [Sim Realism Standard SRS-1](../standards/sim-realism.md): the spec this tool implements.
- [simcritic](simcritic.md): the judge it runs; [simreal](simreal.md) and [hardcases](hardcases.md): the realism statistics and simulator the reference results came from.
- [Calibration evidence](../evidence/srs1-calibration-1126/README.md) and its [preregistration](../prereg/2026-11-26-srs1-null-calibration.md).
