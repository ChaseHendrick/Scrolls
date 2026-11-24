# finite: refuse speeds, scores and maps taken from NaN or Inf output

Checks that a model's output, an array or a saved map holds no NaN or Inf (and, with `--half`, nothing past fp16's 65,504), and whether an fp16 sum can overflow, so no speed or score is ever recorded on broken output.

| Field | Value |
| --- | --- |
| Id | `finite` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Scoring and controls |
| Run | `python -m kit.finite check PATHS [--half] [--json]`; `python -m kit.finite sum --count N --max V [--dtype DTYPE] [--json]` |
| Code | `kit/finite.py` |
| Tests | `tests/test_finite.py` |
| Needs | Python 3.10 or newer and numpy; tifffile for .tif, zarr for .zarr (both optional) |
| Runs on | Any CPU; one pass over each map. Not measured beyond the tests (7 tests in about 0.02 s, 4-core cloud container, 2026-11-19) |
| Network | None |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed |
| Released | Public `main` from the PR that adds this page (2026-11-19) |
| Checked | 2026-11-19 against commit `a846745` |

## What it does

A model that returns NaN still runs, so a benchmark will time it and a scorer will score it. A common cause is a sum or mean taken in fp16, whose largest finite value is 65,504: the mean of one 128 x 128 x 128 tile of values in 0 to 1 (2,097,152 voxels) passes that limit, so the sum becomes Inf and every output after it NaN, while the run still finishes and prints a speed. A timing of a model that returns NaN is not a timing, and a score over NaN is not a score.

`kit.finite` makes the check one line. `check` reads saved maps and exits 1 when any value is NaN or Inf (or, with `--half`, past the fp16 range). `sum` says whether an fp16 (or other) sum of N values up to a magnitude can overflow. In code, `finite.require(out, name)` raises before a number is taken, and `finite.timed(fn, ...)` times a call and refuses its speed when the output is not finite.

It does not judge whether finite output is right: a map of all zeros is finite (the report flags a constant map), and an ink map is model output, not a reading.

## When to use it

- Before any bench records a speed: time with `finite.timed`, or run `check` on the output first.
- Before any score or agreement figure: `finite.require` on both sides, and count non-finite output as a failure.
- Before exporting a model to fp16 (Core ML, MPS or CUDA half precision): `python -m kit.finite sum --count VOXELS --max MAX` for every in-graph sum or mean; accumulate on the host in fp32 when it overflows.

Do not use it:

- To judge whether a finite map is right: a blank or wrong map can be finite. Score it against labels with its control (`python -m kit auc ... --control`).

## Quick start

```bash
python -m kit.finite sum --count 2097152 --max 1
python -m kit.finite check OUT/normals.npy OUT/ink.npy --half
```

`OUT` is the folder a run wrote its maps to. On 19 Nov 2026 the first command printed:

```
OVERFLOWS: a float16 sum of 2.09715e+06 values up to 1 can reach 2.09715e+06 (limit 65504); accumulate in fp32 on the host
```

and exited 1. `check` prints `finite PATH: n=... min=... max=...` per file and exits 0 only when every file is finite.

## Checks and controls

The control is a planted fault: the tests save a float16 array with one NaN and check that `check` exits 1, and that `timed` refuses a function returning a NaN array. For `sum`, the rule is checked against numpy's own fp16 reduction: the sum of one 128 x 128 x 128 tile of ones in fp16 is Inf, as the rule says it can be, and the sum of 512 ones is exact, as the rule says it fits. The same tile summed in fp32 is reported as fitting.

Cross-scroll validation: not applicable (a software check on arrays; it makes no scientific claim about any scroll).

Claim label: Sourced fact for the fp16 limit (IEEE 754 half precision, 65,504); any map it reads stays model output.

## Commands and options

### `python -m kit.finite check`

```
usage: python -m kit.finite check [-h] [--half] [--json] paths [paths ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `paths` | required | saved maps: .npy, .npz (first array), .tif or .tiff, .zarr (first array) |
| `--half` | off | also refuse finite values past the fp16 range |
| `--json` | off | print one JSON list, a record per file |

### `python -m kit.finite sum`

```
usage: python -m kit.finite sum [-h] --count COUNT --max MAX_VALUE
                                [--dtype DTYPE] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--count COUNT` | required | how many values the sum adds (the voxels of a tile, the pixels of a map) |
| `--max MAX_VALUE` | required | the largest magnitude one value can have (1 for values in 0 to 1, 255 for uint8 cast to float) |
| `--dtype DTYPE` | `float16` | the accumulator: float16, bfloat16 or float32 |
| `--json` | off | print one JSON record |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `NonFinite()` | an exception | | An output with NaN or Inf values (or past the fp16 range when half was asked): no number may be taken from it |
| `stats(arr, half=False)` | dict | ImportError without numpy | {"n", "nan", "inf", "finite_fraction", "min", "max", "absmax", "constant", "fp16_over", "ok", "why"}; an empty array is not ok |
| `require(arr, name='output', half=False)` | stats dict | NonFinite | Call before taking any number from an output |
| `timed(fn, *args, name='output', half=False, repeat=1, clock=time.perf_counter, check=None, **kw)` | (seconds per call, last output) | NonFinite | Checks every array in a tuple, list or dict output; torch tensors are moved to the host; `check=lambda: BUFFER` for a function that writes in place |
| `sum_overflows(count, max_value, dtype='float16')` | bool | ValueError for an unknown dtype | True when count times max_value passes the dtype's largest finite value |
| `load(path)` | array | ValueError for an unknown suffix | .npy is memory mapped |
| `add_arguments(p)` | None | | the command line |
| `run(args, say=print)` | exit code | | 0, 1 or 2 |
| `main(argv=None)` | exit code | | |

## Inputs

Saved arrays of any shape and dtype: .npy, .npz (its first array), .tif or .tiff (tifffile), .zarr (the array itself, or its first array). Integer arrays are always finite; only float and complex arrays are scanned for NaN and Inf.

## Outputs

`check` prints one line per file: `finite`, `NOT FINITE` (with the counts) or `UNREADABLE`, and `constant` when every finite value is the same. With `--json`, a list of records:

| Field | Type | Meaning |
| --- | --- | --- |
| `path` | string | the file |
| `n` | int | values in the array |
| `nan`, `inf` | int | NaN and Inf counts |
| `finite_fraction` | float | share of finite values, 0 to 1 |
| `min`, `max`, `absmax` | float or null | over the finite values |
| `constant` | bool | more than one finite value and all equal |
| `fp16_over` | int | finite values past 65,504 (only with `--half`) |
| `ok` | bool | no NaN, no Inf, and (with `--half`) nothing past the fp16 range |
| `why` | string | what made it not ok |

| Exit code | Meaning |
| --- | --- |
| `0` | every file finite (check) or the sum fits (sum) |
| `1` | a file is not finite, or the sum can overflow |
| `2` | a file could not be read (never a pass) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `UNREADABLE PATH: ...: not .npy, .npz, .tif, .tiff or .zarr` | an unknown suffix | save the map as .npy or .tif |
| `UNREADABLE PATH: No module named 'tifffile'` | the optional reader is not installed | install tifffile (or zarr), or save as .npy |
| `NonFinite: NAME: 3 NaN of 4096 values: no speed, score or map may be taken from it` | the output is broken | find the overflow (`python -m kit.finite sum`), move sums and means to fp32 on the host, rerun; never record the number |
| `unknown --dtype 'int8': one of bfloat16, float16, float32, ...` (exit 2), or `ValueError: dtype 'int8': one of ...` from `sum_overflows` | an accumulator type it has no limit for | pass float16, bfloat16 or float32 (or their short names) |
| `TypeError: not a numeric array (dtype ...): nothing to check` (`check`: exit 2) | the array holds strings or objects, not numbers | pass the numeric output array, not metadata |
| `NonFinite: NAME: the call returned no numeric array to check; pass check=lambda: BUFFER for a function that writes in place` | `timed` found no numeric array in the return value (an in-place kernel) | pass `check=lambda: BUFFER` naming the output buffer |

## How it works

`stats` counts `isnan` and `isinf`, takes min and max over the finite values and, with `half`, counts finite values whose magnitude passes `FP16_MAX` (65,504). `timed` runs the function `repeat` times, divides the elapsed `perf_counter` time and checks every array of the last output. `sum_overflows` compares count times max_value with `DTYPE_MAX` (float16 65,504; bfloat16 and float32 about 3.4e38).

## Cost and time

Not measured beyond the tests (7 tests in about 0.02 s, 4-core cloud container, 19 Nov 2026). Reading a map costs one pass over it.

## For agents

- **Command:** `python -m kit.finite check MAP.npy --json`; in code `finite.require(out, "NAME")` or `sec, out = finite.timed(model, x, name="NAME")`.
- **Parse:** `ok` per record; exit code.
- **Rerun:** safe; it writes nothing.
- **Success:** exit 0 and `ok` true for every file.
- **Not a pass:** exit 2 (unreadable); `constant` true (finite but blank); a finite map that is still wrong.
- **Go-ahead:** Nothing.
- **Never:** record a speed, score or agreement from output that failed it; count non-finite output as agreeing.

## Tests

`python -m unittest tests.test_finite -v`: planted NaN and Inf, the fp16 range, an empty array, integer and string arrays, `timed` on a tuple output and on an in-place call, the fp16 sum rule against numpy's own fp16 reduction, and the command line's exit codes. Not covered: tifffile and zarr reads (the container has neither).

## History

- 2026-11-19: released to public Scrolls, on top of `a846745`.

## Related

- [auc](auc.md): scoring an ink map against labels, with its reverse-depth control.
