# verify: check that two ink maps of the same input agree, with a control

`python -m kit verify` compares a candidate ink map (such as an Apple GPU run) with a reference map (such as the CPU run) pixel by pixel, and counts agreement as a pass only when a control map that should differ is caught by the same test.

| Field | Value |
| --- | --- |
| Id | `verify` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Scoring and controls |
| Run | `python -m kit verify`, `from kit import verify` |
| Code | `kit/verify.py`, `kit/cli.py` (`cmd_verify`), `kit/ledger.py` (`add_check`, `load`, `path_for`) |
| Tests | `tests/test_verify.py`, `tests/test_scoring_guards.py` (`VerifyGuardsTest`), `tests/test_toolreg_reports.py` |
| Needs | Python 3.10 or newer, numpy, tifffile; imagecodecs for LZW-compressed TIFFs, which is how villa writes its maps. The maps extra installs all three (`python -m pip install "scrolls-workbench[maps]"`, `MAPS_INSTALL`); villa's environment has them too |
| Runs on | Any CPU. A 2.4 um w035 ink map of 22,640 x 20,400 px with a control took 36 s and 2.25 GB ([mac.md](../mac.md#runbook-verify-mps-against-cpu-on-the-control-segment), 2026-10-07); a 5,980 x 8,240 uint8 map with a control took 17 s and 512 MB (measured 2026-10-16, shared 4-core cloud container, synthetic maps) |
| Network | None |
| Writes | Nothing (prints only). With `--slug SLUG`, appends one check to `experiments/SLUG/run.json` (or `ROOT/SLUG/run.json` with `--root`) |
| Go-ahead | Not needed to run it. Posting its output, for example on a villa PR, needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-07 |
| Guide | [mac.md, "Runbook: verify MPS against CPU on the control segment"](../mac.md#runbook-verify-mps-against-cpu-on-the-control-segment) |
| Checked | 2026-10-21 against commit `8721373` |

## What it does

When ink detection moves to a new device or code path, such as villa's Apple GPU (MPS) backend in [villa PR #1865](https://github.com/ScrollPrize/villa/pull/1865), half precision, or a refactor, its maps should match the old path's maps on the same input. Two maps that come out of the same model on the same surface volume can be compared pixel by pixel. `kit verify` does that: it reports the largest and mean absolute difference, how many pixels differ by more than a tolerance, and the Pearson correlation.

A loose comparison passes everything, so agreement alone proves nothing. `kit verify` also takes a control: a map that must not agree with the reference, usually the reverse-direction map (the same model run with the surface volume's layers in reverse order). Agreement counts as a `pass` only when the same test also catches the control, which must have the reference's shape. Without a control the verdict is `pass-uncontrolled`, and when the control agrees too it is `control-not-caught`. This acceptance rule follows the [GENChase Apple GPU backend](https://github.com/ChaseHendrick/GENChase/blob/main/apps/validate/APPLE-GPU.md).

The default test is the one villa PR #1865's report sets: there CPU and MPS maps differed by at most 1 of 255 gray levels on 0.002 % of pixels. The defaults, at most 0.01 % of pixels more than 2 gray levels apart, leave margin above that without accepting a different map.

It does not look at labels or ink. A `pass` says that the candidate reproduces the reference within the tolerance on this input; it says nothing about whether either map shows ink. A map is model output, not a reading. The module is also where the shared map loader (`load_map`) and error class (`VerifyError`) of the other scoring commands live.

## When to use it

- CPU against MPS, or any two devices, on the same surface volume and checkpoint (`scripts/mac-verify.sh` and `scripts/mac-w045.sh` run it).
- Half precision against full precision on the same device.
- One run against a repeat, to check run-to-run repeatability.
- A refactor of an inference or rendering step whose output should not change.

Do not use it:

- To score a map against human labels: use [`auc`](auc.md) and [`hpscore`](hpscore.md).
- To compare two different models or settings, which are expected to differ: use `auc --compare` on a labeled segment.
- To compare two maps that are not on the same grid (another crop or render): the shapes must match exactly.
- On `.npy` maps: it reads TIFFs only.

## Quick start

```bash
python -m kit verify REF.tif CAND.tif --control CONTROL.tif
```

- `REF.tif`: the reference map, such as `predictions/w035_cpu.tif` from villa's inference on the CPU.
- `CAND.tif`: the map to check, the same input on the new device, such as `predictions/w035_mps_a.tif`.
- `CONTROL.tif`: a map that must not agree, such as `predictions/w035_cpu_reverse.tif` (villa writes it with `--direction both`).

On synthetic villa-style maps (300 x 400 uint8, tiled LZW TIFFs; the candidate is the reference with 3 pixels raised by 1, the control the reference shifted 17 px sideways) it printed, in 0.7 s:

```
candidate: max |diff| 1, mean 0.0000, 0.000000% of pixels over 2, pearson 1.000000
control  : max |diff| 126, mean 13.5730, 21.132500% of pixels over 2, pearson -0.052564
verdict: pass (candidate agrees with the reference, and the control was caught)
```

It worked when the exit code is 0 and the last line reads `verdict: pass`. Exit code 3 (`pass-uncontrolled`) means the run gave no control and proves nothing yet.

## Checks and controls

- **The control is built in** (`--control`). Without it the verdict is `pass-uncontrolled` and the exit code 3, never 0. A control that agrees turns the verdict into `control-not-caught` and the exit code 1 (the rule that every check must be able to fail, in [`AGENTS.md`](../../AGENTS.md)).
- **A real pass.** On an Apple M1 Pro (macOS 27.0, torch 2.14.1), `ink_9um` seed 42 on PHerc0139 w035: CPU against MPS `pass` with max |diff| 1, 0.000000 % of pixels over tolerance and Pearson 0.99999999; an MPS repeat bit-identical; the control 73.12 % over tolerance ([w035 log](../logs/2026-10-07-w035-cpu.md); `device_checks` in [`results.json`](../results.json)). v8in, CPU against MPS on a w045 crop at stride 64: `pass`, max |diff| 1, Pearson 0.99999998 (`device_checks`, [community scan log](../logs/2026-10-07-community-scan.md)).
- **What a caught control looks like.** On w035 the CPU forward map against its reverse: max |diff| 167, mean 21.6692, 73.117458 % of pixels over 2, Pearson 0.511578 ([w035 log](../logs/2026-10-07-w035-cpu.md)).
- **At full size.** On the published 2.4 um w035 ink map (about 462 million pixels) it passed a copy with 0.002 % of pixels changed by one level and caught a control shifted by 64 px (34 % of pixels beyond tolerance) ([mac.md](../mac.md#runbook-verify-mps-against-cpu-on-the-control-segment)).
- **Checks that cannot fail are refused** (since `521c648` and `136b5b2`, 2026-10-16). A control of another shape is an error (exit code 2), not a caught control. NaN or inf in one map and not the other counts as over the tolerance, so an all-NaN candidate fails (on a synthetic 300 x 400 float map: `max |diff| inf, mean nan, 100.000000% of pixels over 0.01`, `verdict: fail`). A float reference with no finite value is an error. NaN in both maps at the same pixel still counts as agreement. This page's earlier version listed the first two as open gaps; they are fixed.

Claim label: Model output, for the agreement of two runs of a model on one input; a `pass` is about the device or code path, not about ink.

## Commands and options

### `python -m kit verify`

```
usage: python -m kit verify [-h] [--control CONTROL] [--tolerance TOLERANCE]
                            [--max-fraction MAX_FRACTION] [--json]
                            [--slug SLUG] [--name NAME] [--root ROOT]
                            [--exit-zero]
                            reference candidate
```

| Option | Default | Meaning |
| --- | --- | --- |
| `reference` | required | The reference map, such as the CPU run: a TIFF that squeezes to 2D |
| `candidate` | required | The map to check, such as the MPS run, same shape as the reference |
| `--control CONTROL` | none | A map that must not agree with the reference, such as the reverse-direction output. Compared with the reference by the same test |
| `--tolerance TOLERANCE` | `2` | Largest absolute difference that still counts as agreeing, in the maps' own units (`DEFAULT_TOLERANCE`, gray levels of a uint8 map). A pixel is over when the difference is strictly larger. For float maps in 0 to 1 or uint16 maps, set it in their units |
| `--max-fraction MAX_FRACTION` | `0.0001` | Largest share of pixels allowed over the tolerance (`DEFAULT_MAX_FRACTION`, 0.01 %). A map agrees when its share is at most this |
| `--json` | off | Print the result as JSON (the fields under Outputs) instead of text |
| `--slug SLUG` | none | Attach the result as a check to the experiment SLUG in the ledger ([run-ledger](run-ledger.md)); the experiment must exist |
| `--name NAME` | `device-agreement` | Name of that check in `run.json` |
| `--root ROOT` | `experiments` | Ledger folder (`ledger.DEFAULT_ROOT`) |
| `--exit-zero` | off | Exit 0 whatever the verdict once the result is printed; the verdict stays in the result. Bad inputs still exit 2. VC3D's entry uses it so a `fail` comes back as a result |

## Python API

```python
from kit import verify
result = verify.verify_files("cpu.tif", "mps.tif", control="cpu_reverse.tif")
print(result["verdict"], verify.format_result(result), sep="\n")
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `verify_files(reference, candidate, control=None, tolerance=DEFAULT_TOLERANCE, max_fraction=DEFAULT_MAX_FRACTION)` | The result dict under Outputs, with `files` | `VerifyError` for a missing package or an unreadable or non-2D map | What the command runs |
| `verify_arrays(reference, candidate, control=None, tolerance=DEFAULT_TOLERANCE, max_fraction=DEFAULT_MAX_FRACTION)` | The result dict under Outputs, without `files` | `VerifyError` without numpy, for a control whose shape differs from the reference's, or for a float reference with no finite value | For arrays already in memory |
| `compare(reference, candidate, tolerance=DEFAULT_TOLERANCE)` | The statistics dict (`shape_match`, `shape`, `pixels`, `tolerance`, `max_abs_diff`, `mean_abs_diff`, `pixels_over_tolerance`, `fraction_over_tolerance`, `pearson`), or `{"shape_match": False, "reference_shape", "candidate_shape"}` | `VerifyError` without numpy | Candidate minus reference in blocks of `ROWS_PER_BLOCK` = 1024 rows, in float64, to bound memory. Equal values, and NaN in both maps at the same pixel, agree; NaN or inf in one map only is over the tolerance and makes `max_abs_diff` inf. `pearson` is `None` when either map is constant or holds NaN |
| `agrees(stats, max_fraction=DEFAULT_MAX_FRACTION)` | bool: the shapes match and `fraction_over_tolerance` is at most `max_fraction` | Nothing | |
| `verdict(candidate_agrees, control_agrees=None)` | One of `PASS` (`"pass"`), `PASS_UNCONTROLLED` (`"pass-uncontrolled"`), `FAIL` (`"fail"`), `CONTROL_NOT_CAUGHT` (`"control-not-caught"`) | Nothing | `fail` when the candidate disagrees, whatever the control; `pass-uncontrolled` when `control_agrees` is `None` |
| `load_map(path)` | A 2D numpy array, squeezed | `VerifyError` without numpy or tifffile, for an unreadable file, or for a map that is not 2D | Shared by `auc`, `hpscore`, `rowscore`, `overlap` and others |
| `missing(module)` | The `VerifyError` (not raised) for a missing package `module`, naming the command running now (`RUNNING`, which `kit.cli` sets while a command runs), the maps extra (`MAPS_INSTALL`) and villa's `uv run` line | Nothing | Shared by the map tools for their install hints; as a library (`RUNNING` is `None`) the message names no command and ends `python -m kit COMMAND ...` |
| `format_result(result)` | str | Nothing | The text the command prints; `EXPLAIN` holds each verdict's sentence |
| `VerifyError` | Exception class | | Raised for bad input here and by most map tools in `kit`; the commands print its message and exit with code 2 |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Reference, candidate, control | TIFF (tiled, BigTIFF and LZW are fine with imagecodecs), squeezed to 2D | Any dtype tifffile reads. Differences are computed on the raw values, so the tolerance is in the maps' own units: 2 is two gray levels of a uint8 map, two units of 65,535 in a uint16 map, and covers everything in a float map scaled 0 to 1. All three must have the same shape |

The whole of each map is read into memory in its own dtype; the comparison then runs in float64 blocks of 1,024 rows. `.npy` files are not read (`cannot read X.npy: not a TIFF file: ...`).

## Outputs

Text by default (see Quick start). The candidate and control lines give `max |diff|` (rounded to a whole number, so a float map's difference of 0.4 shows as 0), the mean absolute difference, the share of pixels over the tolerance and the Pearson correlation (`n/a` for a constant map). A shape mismatch prints `candidate: shape mismatch [H, W] vs [H, W]`. The last line is `verdict: VERDICT (sentence)`.

With `--json`, one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `candidate.shape_match` | bool | Whether the candidate has the reference's shape. When false, the object holds only `reference_shape` and `candidate_shape` |
| `candidate.shape` | [int, int] | Rows and columns |
| `candidate.pixels` | int | Pixels compared |
| `candidate.tolerance` | number | The tolerance used |
| `candidate.max_abs_diff` | float | Largest absolute difference, in map units; `Infinity` in the JSON when one map has NaN or inf where the other does not |
| `candidate.mean_abs_diff` | float | Mean absolute difference, in map units; `NaN` in the JSON when one map has NaN where the other does not |
| `candidate.pixels_over_tolerance` | int | Pixels whose difference is larger than the tolerance |
| `candidate.fraction_over_tolerance` | float | That count over `pixels`, from 0 to 1 |
| `candidate.pearson` | float or null | Pearson correlation of the two maps; null when either is constant |
| `max_fraction` | float | The allowed share used |
| `candidate_agrees` | bool | Shapes match and `fraction_over_tolerance` is at most `max_fraction` |
| `control` | object, the same fields | Only with `--control`, which must have the reference's shape |
| `control_agrees` | bool | Only with `--control`; true means the control was not caught |
| `verdict` | str | `pass`, `pass-uncontrolled`, `fail` or `control-not-caught` |
| `files.reference`, `files.candidate`, `files.control` | str, or null for `control` | The paths as given |

With `--slug`, the same object is stored as the check's `result` in `run.json`, with `at` (UTC time) and `name`.

| Exit code | Meaning |
| --- | --- |
| `0` | `pass`: the candidate agrees and the control was caught |
| `1` | `fail` or `control-not-caught` (read `verdict`); also an error the command does not catch, with a Python traceback, such as running out of memory |
| `2` | Bad input, with the message on stderr (see Failure modes), or a usage error from the argument parser |
| `3` | `pass-uncontrolled`: the candidate agrees but no control was given |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `numpy is required for python -m kit verify. Install the maps extra: python -m pip install "scrolls-workbench[maps]", or run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed. From Python (`verify_files`) the message reads `numpy is required. Install the maps extra: ...` and ends `python -m kit COMMAND ...` | Install the maps extra, or run inside villa's environment, as the message says |
| `tifffile is required for python -m kit verify. Install the maps extra: ...` (the rest as for numpy) | tifffile is missing | The same; imagecodecs, in the maps extra, reads LZW TIFFs |
| `cannot read MAP.tif: ...` | A missing file, a file that is not a TIFF (such as `.npy`), or an LZW TIFF without imagecodecs | Fix the path, install imagecodecs, or save the map as TIFF |
| `MAP.tif: expected a 2D map, got shape (...)` | A layer stack or an RGB image | Pass one 2D map |
| `no experiment at ROOT/SLUG/run.json` | `--slug` names an experiment that was never started | Start it with `python -m kit run init`, or fix `--slug` and `--root` |
| `bad slug: '...'` | A slug that is empty, holds `/` or starts with `.` | Use a plain name |
| `candidate: shape mismatch [...] vs [...]` and `verdict: fail`, exit code 1 | The two maps have different shapes: another crop, render or downsampling | Compare maps of the same input and grid |
| `verdict: fail (candidate does not agree with the reference)`, exit code 1 | More than `--max-fraction` of pixels differ by more than `--tolerance` | Look at `max_abs_diff` and the share; check the device's logs for a silent fallback or a numerical bug, and that both runs used the same settings |
| `verdict: control-not-caught (...)`, exit code 1 | The control also agreed: the tolerance is too loose for these maps (a float map with the uint8 tolerance does this) or the control is not different | Set `--tolerance` in the maps' units, or use a control that differs, such as the reverse-direction map |
| `verdict: pass-uncontrolled (...)`, exit code 3 | No `--control` given | Rerun with a control |
| `control shape (H, W) differs from the reference's (H, W); the control must be the same map made wrongly`, exit code 2 | The control is another crop, render or downsampling; a control of another shape would disagree by shape alone and pass any candidate | Use a control of the reference's shape, such as the reverse-direction map of the same input |
| `the reference map has no finite values; a broken reference cannot show agreement`, exit code 2 | A float reference that is all NaN or inf, such as a run that overflowed; NaN at the same pixel counts as agreement, so an all-NaN candidate would pass | Fix the reference run |
| `candidate: max \|diff\| inf, mean nan, ...` and `verdict: fail`, exit code 1 | The candidate has NaN or inf where the reference has a value (or the other way round) | Find why one run produced NaN or inf, such as half-precision overflow |

## How it works

1. Read each map with `tifffile.imread` and squeeze it to 2D (`load_map`).
2. Refuse a float reference with no finite value, and a control whose shape differs from the reference's (`verify_arrays`).
3. If the candidate's shape differs from the reference's, record a shape mismatch: it does not agree.
4. Otherwise, in blocks of `ROWS_PER_BLOCK` = 1024 rows, convert both to float64, take the absolute difference, and accumulate its maximum and sum, the count of pixels over the tolerance, and the sums needed for Pearson's r (`compare`). A pixel is over when its difference is not at most the tolerance and the two values are not equal and not both NaN, so NaN or inf in one map only is over.
5. The candidate agrees when the shapes match and the share over the tolerance is at most `--max-fraction` (`agrees`).
6. With a control, the control is compared with the reference in the same way; it is caught when it does not agree.
7. The verdict (`verdict`): `fail` if the candidate does not agree; else `pass-uncontrolled` without a control; else `control-not-caught` if the control agrees; else `pass`.

Constants: `DEFAULT_TOLERANCE = 2`, `DEFAULT_MAX_FRACTION = 1e-4`, `ROWS_PER_BLOCK = 1024`. The defaults leave margin above villa PR #1865's report of at most 1 of 255 on 0.002 % of pixels; the acceptance rule is GENChase's.

## Cost and time

| Case | Time | Memory | Source |
| --- | --- | --- | --- |
| Published 2.4 um w035 ink map, 22,640 x 20,400 px, a copy and a shifted control | 36 s | 2.25 GB peak | [mac.md](../mac.md#runbook-verify-mps-against-cpu-on-the-control-segment), setup container, 2026-10-07 |
| Synthetic 5,980 x 8,240 uint8 maps, candidate and control | 17 s wall | 512 MB peak | This page, 2026-10-16, 4-core Intel Xeon cloud container (lscpu: 2.80 GHz) shared with other jobs (load average about 16) |
| Synthetic 300 x 400 maps | 0.7 s wall | Not measured | Same |

Memory is about the three maps in their own dtype plus a few float64 blocks of 1,024 rows. It runs on any machine; nothing here needs Modal or a GPU. The inference runs it compares are the expensive part.

## Start from VC3D

Make the segment active and pick Scrolls > segment > "verify". VC3D asks for three ink detection labels of the active segment (as its Ink Detection overlay lists them): the reference map, the map to check and the control that must not agree. VC3D's entry asks for all three, so a device check started there always carries its control. Labels become paths only through the agent bridge of the VC3D that started the entry (start VC3D with its agent bridge on); without one, type file paths. The registry runs `kit verify ... --exit-zero`, so a `fail` comes back as a result with the verdict in the report. From a terminal or an agent ([toolreg](toolreg.md)):

```bash
python -m kit tools run verify --input reference=CPU.tif --input candidate=MPS.tif --input control=CPU_reverse.tif --out RUN
```

## Open in VC3D

VC3D shows `RUN/verify.json` as the run's result file: `verdict` (`pass`, `fail`, `control-not-caught` or `pass-uncontrolled`) and the statistics under Outputs. `RUN/vc3d-result.json` says `no control: not a pass` when the control was left out (possible only from a terminal). verify checks a run against another; it is not an AutoPipeline (AP) stage.

## For agents

- **Command:** `python -m kit verify REF.tif CAND.tif --control CONTROL.tif --json`.
- **Parse:** `verdict`; then `candidate.max_abs_diff`, `candidate.fraction_over_tolerance` and `candidate.pearson`; `control.fraction_over_tolerance`; `control.shape_match`.
- **Rerun:** Safe; it only reads its inputs and gives the same numbers. With `--slug`, each run appends one more check to `run.json`.
- **Success:** Exit code 0 and `verdict` equal to `pass`.
- **Not a pass:** Exit code 3 (`pass-uncontrolled`); `control-not-caught`; a `pass` on float maps with the default tolerance of 2; a `pass` with NaN statistics, which means NaN in both maps at the same pixels; any `pass` read as evidence that a map shows ink.
- **Go-ahead:** Nothing to run it. Posting its output on a villa PR or anywhere public needs Chase's yes first.
- **Never:** Call two agreeing maps a result about ink; report agreement without its control; drop the control to turn a failing check into exit code 3.

## Tests

```bash
python -m unittest tests.test_verify tests.test_scoring_guards.VerifyGuardsTest -v
```

`tests/test_verify.py` holds thirteen tests. Nine cover `kit verify`: a pass needs agreement and a caught control, no control gives `pass-uncontrolled`, a control that agrees gives `control-not-caught`, a different map fails, a shape mismatch fails, block statistics equal whole-array statistics (with 7-row blocks) and numpy's Pearson r, constant maps have no Pearson r, the command line on tiled BigTIFF maps (LZW when imagecodecs is there) stores a `pass` in the ledger, and the exit codes 3 and 2. One tests `ledger.add_provenance`. Three check the install hint of `missing`: as a library it names the maps extra, under `python -m kit` it names the command run, and under a console script it names that script. `VerifyGuardsTest` in `tests/test_scoring_guards.py` checks that a control of another shape is an error, an all-NaN candidate fails, NaN in both maps at the same pixels agrees, and an all-NaN reference is refused. The map tests skip without numpy and tifffile. They do not cover float maps with a tolerance in their own units.

## History

- 2026-10-16: missing numpy or tifffile names the command run and the maps extra (`missing`, `bb8cc06`).
- 2026-10-16: a float reference with no finite value is refused (`136b5b2`).
- 2026-10-16: a control of another shape is an error, not a caught control, and NaN or inf in one map only counts as disagreement (`521c648`).
- 2026-10-07: first version, with the control rule, the four verdicts, the ledger link and the Mac runbook (`99dba9e`).

## Related

- [`auc`](auc.md): scores a map against human labels, with the reverse-depth control.
- [`hpscore`](hpscore.md): the letter-scale score against human labels.
- [`mac-verify`](mac-verify.md): the Mac script that runs CPU against MPS on w035 and calls this command twice.
- [`mac-w045`](mac-w045.md): runs this command on a crop before a full v8in run on the Mac.
- [`run-ledger`](run-ledger.md): the experiment ledger that `--slug` writes to.
- [w035 log](../logs/2026-10-07-w035-cpu.md) and `device_checks` in [`results.json`](../results.json): the recorded device checks.
- [STANDARDS.md](../STANDARDS.md): the device-agreement row, with this tolerance and the four verdicts.
