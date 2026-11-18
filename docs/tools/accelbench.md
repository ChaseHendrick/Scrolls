# accelbench: time a faster version only after its output matches

`kit.accelbench` times a candidate implementation against a reference only after their outputs agree under a stated rule and a perturbed control fails that rule, and writes a re-checkable JSON receipt; `scripts/accelbench/mps_precision.py` times autocast precisions on a GPU.

| Field | Value |
| --- | --- |
| Id | `accelbench` |
| Status | Current |
| Kind | kit module, script folder |
| Area | Compute and cost |
| Run | `from kit import accelbench`, `python3 scripts/accelbench/mps_precision.py` |
| Code | `kit/accelbench.py`, `scripts/accelbench/` |
| Tests | `tests/test_accelbench.py` |
| Needs | Python 3.10 or newer (checked with 3.13.18). The module is standard library at import time. numpy when an output holds numpy arrays or scalars, or torch tensors (they are compared through numpy). torch for tensors and for any device other than `cpu`, with [`kit.accel`](accel.md) (its `resolve_device` and `synchronize`) for `cuda`, `cuda:N` and `mps`. git on `PATH` for the commit and dirty flag in a receipt (without it they are null). The script needs torch |
| Runs on | Any CPU; CUDA or MPS through `kit.accel` when torch sees the device. Time is the gate's two calls plus (warm-up + repeats) x number calls per arm: the Quick start example took 0.29 s wall (measured 2026-11-18, 4 logical CPU Intel Xeon cloud container) |
| Network | None |
| Writes | The library writes nothing unless you call `write_receipt(receipt, PATH)`, which creates PATH's parent folders and one JSON file at PATH (mode 0644), through a temporary `.NAME.*.tmp` beside it that it removes. The script writes `OUT_DIR/<net>-<mode>.json` and `OUT_DIR/summary.json` |
| Go-ahead | Not needed for a local run. GPU timing on rented hardware follows hard rule 11 (paid compute runs on Hugging Face) |
| Released | Public `main` from the PR that adds this page (2026-11-18) |
| Checked | 2026-11-18 against commit `c2cb575` |


## What it does

A speed claim is easy to get wrong in two ways: the faster code gives a different answer, or the clock is read while a GPU is still working. `kit.accelbench` (accelbench: accelerator benchmark) guards against both. `benchmark(reference, candidate, ...)` first runs each implementation once on the same inputs and compares the two outputs under a rule you state: `bitwise` (identical bytes), exact value equality (`atol` and `rtol` both 0, the default), or a tolerance. Only when they match does it time anything.

The comparison itself is tested. A control output, the reference's own output with one element moved just past the rule (the perturbed control), must fail the same comparison; if it passes, the rule cannot tell outputs apart and the receipt says `invalid-control`. After timing, the last outputs of the two arms are compared again, so an arm that changes state or drifts is caught (`refused-unstable`). A candidate that differs is never timed (`refused-mismatch`). Only a `pass` receipt carries a speedup, and it carries three: the ratio of the minimum per-call times (`speedup`), of the medians, and the median of the per-sample ratios.

Timing runs the two arms (reference and candidate) in ABBA order (A, B, then B, A, alternating each sample) with a device sync before every clock read, so neither arm always runs first and queued GPU work is counted. The receipt is a JSON-ready dict with the outputs' types and shapes, the rule, the control, every sample, the environment (Python, CPU, packages, torch's live flags) and the git state (commit, dirty flag, SHA-256 of named source files). `write_receipt` stores it as strict JSON without overwriting, and `check_receipt` re-checks a stored receipt, including recomputing every speedup from its samples. `time_callable` and `timing_receipt` time code with no correctness claim, for variants that differ by design; such a receipt has status `timing-only` and no speedup keys at all.

What it does not do: it says nothing about ink, surfaces or scroll content; it does not make a run faster; and a `pass` on one machine and one input is not a speedup on another machine or on real data.


## When to use it

- Any claim that new code is faster than old code: time it with `benchmark` so a faster but different output is refused.
- Checking a published or PR speed number on your own machine.
- GPU kernels or models on CUDA or MPS, where a missing sync would time only the launch: the sync comes from `kit.accel.synchronize`.
- Timing variants that are meant to give different outputs (two models, two precisions): `time_callable` and `timing_receipt`.

Do not use it:

- To measure accuracy or an AUC: use [auc](auc.md) and the scoring tools; accelbench compares outputs only to gate the timing.
- To check that a model gives the same result on MPS and CUDA: use [accel](accel.md) (`python -m kit.accel --check`).
- To price a cloud run: use [cloudcost](cloudcost.md).


## Quick start

The library, from the repository root (or with it on `PYTHONPATH`):

```python
import json
import numpy as np
from kit import accelbench

x = np.random.default_rng(0).random(1_000_000)

def reference(a):                       # the ten largest values, slow way: sort everything
    return np.sort(a)[-10:]

def candidate(a):                       # the same ten values, fast way: partition, then sort ten
    return np.sort(np.partition(a, -10)[-10:])

def wrong(a):                           # fast and wrong: the last ten of the input, not the largest
    return np.sort(a[-10:])

r = accelbench.benchmark(reference, candidate, args=(x,), bitwise=True, name='top-10')
print(r['status'], round(r['speedup'], 2), r['control']['failed_as_required'])
w = accelbench.benchmark(reference, wrong, args=(x,), bitwise=True, name='top-10 wrong')
print(w['status'], w['speedup'], w['timing'])
print(w['reason'])
path = accelbench.write_receipt(r, 'OUT.json')
print(accelbench.check_receipt(json.loads(path.read_text())))
```

- `OUT.json`: where to write the receipt; it must not exist yet (or pass `overwrite=True`).

On 2026-11-18 (4 logical CPU Intel Xeon cloud container, numpy only) it printed, in 0.29 s wall:

```
pass 4.47 True
refused-mismatch None None
the candidate output differs from the reference in 10 element(s) of 1 leaf or leaves; the candidate was not timed
[]
```

The wrong candidate was refused before timing, the control failed as required for the right one, and `check_receipt` found no problem in the stored receipt. It worked when the first word is `pass` and the last line is `[]` or holds only `warning:` entries. A speedup under 1 is a result: the candidate was slower.

The precision script, on a machine with torch and a GPU:

```bash
python3 scripts/accelbench/mps_precision.py OUT_DIR
```

- `OUT_DIR`: a folder for the receipts, such as `/tmp/mps-precision`; created if missing. Receipts already there stop the run unless you add `--overwrite`.


## Checks and controls

The gate has three checks, each able to fail, and the receipt records each:

- **Match before timing** (`comparison`): the candidate's first output against the reference's under the rule. A difference gives `refused-mismatch` and no timing. In the Quick start the wrong top-10 was refused with 10 differing elements.
- **The control** (`control`): the reference output with one element moved past the rule must fail it (`failed_as_required` true). With the default `control='perturb'` the first float leaf's first finite element moves up by at least 2 x (atol + rtol x abs(x)), and by at least one representable step in its dtype; else one integer element moves by 1, else one bool flips. Pass a callable to build your own control from a copy of the reference output, or `control=None` to skip it (the receipt then carries `warning: no control was run` from `check_receipt`). A control that passes gives `invalid-control`: the rule is too loose to mean anything.
- **Match after timing** (`post_check`): the last timed outputs compared again; a difference gives `refused-unstable` and no speedup.

`check_receipt` is the check on the record itself: it recomputes the three speedups from the stored samples (to a relative 1e-12, `_RELATIVE`), checks `min_s` and `median_s` against the samples, and refuses a receipt whose status and fields disagree (a speedup on a refusal, timing on a `refused-mismatch`, a `pass` without a failed control). A mutation check during development removed each of six gates in turn from a copy of the module, and at least one test failed every time.


Claim label: Sourced fact, for a `pass` receipt's match and speedup on the machine, input and commit it records (the stored receipt is the source); Interpretation, for any reason given for a ratio. A receipt says nothing about ink or a reading.

## Commands and options

The module has no command line; its interface is the Python API below.

### `python3 scripts/accelbench/mps_precision.py`

Which autocast precision is fastest on a GPU (MPS on a Mac, or CUDA) for three synthetic convolution networks: `conv2d` (16 depth slices as channels, batch 16 of 128 x 128), `conv3d` (batch 8 of 16 x 64 x 64) and `unet3d` (a small nnU-Net-like encoder and decoder, batch 2 of 64 x 64 x 64), for inference and for one training step, with the CPU in fp32 beside them. It exists because a five-step smoke test on an Apple M1 Pro (16 Oct 2026) had fp16 1.23 times faster for a 2D model and about 9 percent slower for a 3D one, while `kit.accel`'s `--precision auto` then picked fp16 on MPS for every model. Random weights and inputs, no scroll data. Arms the device refuses are recorded as skipped. Each net and mode is one `timing_receipt` (`OUT_DIR/<net>-<mode>.json`, status `timing-only`); `summary.json` adds per arm the median, the speed against fp32 on the same device (`x_vs_fp32`) and, for inference, the largest difference from the fp32 output (`max_diff_vs_fp32`). Needs torch.

```
usage: mps_precision.py [-h] [--device DEVICE] [--nets NETS]
                        [--precisions PRECISIONS] [--modes MODES]
                        [--repeats REPEATS] [--warmup WARMUP]
                        [--cpu-repeats CPU_REPEATS] [--no-cpu] [--overwrite]
                        out_dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out_dir` | required | Folder for the receipts and `summary.json`; created if missing |
| `--device DEVICE` | `auto` | auto (CUDA, then MPS, then CPU), mps, cuda, cuda:N or cpu, through `kit.accel.resolve_device` |
| `--nets NETS` | `conv2d,conv3d,unet3d` | comma-separated networks |
| `--precisions PRECISIONS` | `fp32,fp16,bf16` | comma-separated autocast precisions, through `kit.accel.autocast` |
| `--modes MODES` | `infer,train` | `infer` is a forward pass under `inference_mode`; `train` is forward, backward and an SGD step with `kit.accel.grad_scaler` |
| `--repeats REPEATS` | `20` | timed samples per device arm; at least 5 |
| `--warmup WARMUP` | `3` | untimed calls per device arm |
| `--cpu-repeats CPU_REPEATS` | `5` | timed samples of the CPU fp32 arm (it is slow); at least 5 |
| `--no-cpu` | off | skip the CPU fp32 arm |
| `--overwrite` | off | replace receipts already in `out_dir` |

Smoke run (23 Oct 2026, 4 logical CPU cloud container, torch 2.14.1+cpu, `--device cpu --nets conv2d --precisions fp32,bf16 --repeats 5`): conv2d inference 1.11 s per call in fp32 and 2.50 s in bf16 (0.445 times), training 4.09 and 7.36 s; this only shows the script runs. CPU autocast is not a speedup there, which is why `--precision auto` is fp32 on the CPU. On an Apple M1 Pro the same day (two runs) fp16 and bf16 ran inference at 0.82 to 1.04 times fp32 and training at 0.84 to 1.31 times, faster only for conv3d training; MPS fp32 was 3.6 to 26 times the CPU. `kit.accel`'s `auto` on MPS became fp32 after it.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `OMP_NUM_THREADS` | unset | Read only to record in `environment.thread_env`; never set |
| `MKL_NUM_THREADS` | unset | Likewise |
| `OPENBLAS_NUM_THREADS` | unset | Likewise |

## Python API

```python
from kit import accelbench
receipt = accelbench.benchmark(reference, candidate, args=(x,), device='cpu', bitwise=True,
                               name='NAME', source_files=('PATH/TO/CODE.py',))
accelbench.write_receipt(receipt, 'work/receipts/NAME.json')
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `DeviceSync(fn, description)` | A callable object: calling it calls `fn()`; `description` (str) names what it waits on | Nothing itself | What `sync_for` returns; the receipt's `settings.sync` is its description |
| `sync_for(device='cpu')` | `DeviceSync`: `none (cpu)` for a cpu device (no torch import), else `kit.accel.synchronize(DEVICE)` for the device `kit.accel.resolve_device` returned | `ValueError` for a missing, empty or `auto` device, when `kit.accel` or torch is missing, when this torch cannot use the device (kit.accel's own message), or for a device type other than cuda and mps | Device names are lowercased and stripped; `cuda:N` keeps its index |
| `time_callable(fn, *, args=(), kwargs=None, setup=None, device='cpu', warmup=DEFAULT_WARMUP, repeats=DEFAULT_REPEATS, number=1, clock=time.perf_counter, sync=None)` | dict: `seconds` (per-call seconds of each sample, in run order), `min_s`, `median_s`, `mean_s`, `max_s`, `spread`, `warmup`, `repeats`, `number`, `clock`, `sync` | `ValueError` for bad counts, a bad device, a non-callable `sync`, or a `setup()` that does not return (args, kwargs); anything `fn` raises | No correctness claim. `setup` runs outside the timed region before each warm-up call and each sample; with `number` above 1 the calls of one sample share one setup. `sync=None` means `sync_for(device)` |
| `compare_outputs(reference, candidate, *, atol=0.0, rtol=0.0, bitwise=False, equal_nan=False, check_dtype=True, max_reported=32)` | dict: `pass`, `rule`, `leaves`, `different_leaves`, `different_elements`, `max_abs_diff`, `max_rel_diff`, `differences` (at most `max_reported`, each `path`, `kind`, `elements`, `max_abs_diff`) | `ValueError` for a negative, non-finite or non-number tolerance, a tolerance with `bitwise`, or a bad `max_reported` | A difference in the outputs never raises: an unreadable or unsupported leaf is a difference (fails closed). Comparing torch tensors with numpy missing raises `ImportError`. Rule in How it works |
| `environment(device='cpu')` | dict: `python`, `implementation`, `platform`, `machine`, `processor`, `logical_cpus`, `packages` (numpy, torch, scipy versions or null), `thread_env`, `torch` (live flags or null), `device` | `ValueError` for a missing, empty or `auto` device | Imports torch only for a device other than cpu; on cpu reads torch's flags only if something already imported it. Each torch flag that cannot be read is null |
| `git_state(root=None, files=())` | dict: `commit` (40 hex or null), `dirty` (bool or null), `dirty_paths` (at most 32), `files_sha256` (path to SHA-256, or null for a missing file) | Never raises for git or a missing repository | `root` defaults to the repository (`ROOT`). With `files`, dirty means any of them changed or is untracked; without, any tracked file changed |
| `benchmark(reference, candidate, *, args=(), kwargs=None, setup=None, device='cpu', warmup=DEFAULT_WARMUP, repeats=DEFAULT_REPEATS, number=1, atol=0.0, rtol=0.0, bitwise=False, equal_nan=False, check_dtype=True, control='perturb', name=None, dtype=None, sizes=None, source_files=(), root=None, clock=time.perf_counter, sync=None)` | dict: the receipt (Outputs), with `status` one of `pass`, `refused-mismatch`, `refused-unstable`, `invalid-control` | `ValueError` for any bad argument (Failure modes), or when `control='perturb'` and the output has no numeric leaf; anything an arm or a control callable raises | A refusal is returned, not raised. `name` defaults to `REFERENCE vs CANDIDATE` (qualified names); `dtype` defaults to the first float dtype in the inputs |
| `timing_receipt(name, timings, *, device='cpu', dtype=None, sizes=None, source_files=(), root=None)` | dict: a receipt with status `timing-only`, `timing` holding the given `time_callable` results by label, and no `speedup`, `speedup_median` or `speedup_paired_median` keys | `ValueError` for empty or malformed `timings`, a result with fewer than 5 repeats, a non-dict `sizes`, or a bad device | A speedup can only come from `benchmark` |
| `write_receipt(receipt, path, *, overwrite=False)` | `pathlib.Path` of the written file | `FileExistsError` when `path` exists (or appears meanwhile) and `overwrite` is False; `TypeError` for a value JSON cannot hold; `OSError` from the file system | Strict JSON, indent 1, non-finite floats as null, tuples as lists, numpy scalars as Python; temporary file, fsync, mode 0644, then a no-clobber hard link (or `os.replace` with `overwrite`) |
| `check_receipt(receipt)` | list of str: problems, empty when valid; entries starting `warning:` are not errors | Nothing for a receipt as `benchmark` or `timing_receipt` writes it, or for a non-dict; a field of the wrong type (such as `comparison` or `control` stored as a list) can raise `AttributeError` | Problems listed under Outputs |

Module constants: `SCHEMA = 1`, `KIND = 'kit-accelbench'`, `MIN_REPEATS = 5`, `DEFAULT_WARMUP = 3`, `DEFAULT_REPEATS = 7`, `STATUSES` (the five status words), `SPEEDUP_KEYS` (`speedup`, `speedup_median`, `speedup_paired_median`), `ROOT` (the repository root).

## Inputs

- **reference, candidate**: callables. Each is called as `fn(*args, **kwargs)`. They should not change their inputs; if they do, pass `setup`, a zero-argument callable returning `(args, kwargs)`, which `benchmark` calls before the gate run of each arm, each warm-up call and each sample, outside the timed region.
- **Outputs they return**: nested dicts, lists and tuples (named tuples too) whose leaves are torch tensors, numpy arrays, numpy scalars, or Python `bool`, `int`, `float`, `complex`, `str`, `bytes` and `None`. Any other leaf type is always a difference. Tensors are detached and copied to the CPU for comparison; strides, layout and device are ignored. Tensor dtypes numpy lacks (bfloat16, the float8 types) are compared through float64 values and same-size integer bits. Object arrays are always a difference. The perturbed control needs at least one numeric leaf with at least one element.
- **device**: `cpu`, `cuda`, `cuda:N` or `mps` (case and spaces ignored); not `auto`, so the receipt names the device. Resolve `auto` first with `kit.accel.resolve_device`.
- **Rule**: `atol`, `rtol` (finite numbers at least 0), `bitwise`, `equal_nan`, `check_dtype` (always on with `bitwise`).
- **Counts**: `warmup` (int, at least 0, default 3), `repeats` (int, at least 5, default 7), `number` (int, at least 1, default 1). Booleans are refused.
- **Receipt labels**: `name` (str), `dtype` (str), `sizes` (a dict of JSON values, without the keys `inputs` and `outputs`, merged into the receipt's `sizes`), `source_files` (paths relative to `root`, or absolute, to hash), `root` (the git checkout; default the repository).
- **clock, sync**: a zero-argument clock (default `time.perf_counter`, seconds) and a zero-argument sync (default from `sync_for(device)`); for tests and special devices.

## Outputs

### The receipt from `benchmark`

| Field | Type | Meaning |
| --- | --- | --- |
| `schema`, `kind` | int, str | `1` and `kit-accelbench` |
| `name` | str | The `name` argument, or `REFERENCE vs CANDIDATE` |
| `created_utc` | str | When the gate started, `YYYY-MM-DDTHH:MM:SSZ` |
| `status` | str | `pass`, `refused-mismatch`, `refused-unstable` or `invalid-control` |
| `reason` | str or null | Why it was refused; null on `pass` |
| `speedup` | float or null | Reference `min_s` over candidate `min_s`; set only on `pass` |
| `speedup_median` | float or null | Reference `median_s` over candidate `median_s`; only on `pass` |
| `speedup_paired_median` | float or null | Median over samples of reference seconds over candidate seconds, pairing sample i of each arm; only on `pass` |
| `device` | str | The device name as given, lowercased |
| `dtype` | str or null | The `dtype` argument, or the first float dtype found in the inputs (`float` for a Python float), or null |
| `sizes` | object | `inputs` (a description of args and kwargs: type, shape, dtype, device, length; at most 32 dict items, 16 list items, 8 levels), `outputs.reference` and `outputs.candidate` (the same for each first output), then the keys of the `sizes` argument |
| `settings` | object | `warmup`, `repeats`, `number`, `order` (`ABBA`), `clock` (qualified name), `sync` (description) |
| `comparison` | object | The first-output comparison, as `compare_outputs` returns it |
| `control` | object | `kind` (`perturb`, `caller` or null), `comparison` (the control against the reference output, or null), `failed_as_required` (true, false, or null when skipped) |
| `post_check` | object or null | The comparison of the last timed outputs; null when nothing was timed |
| `timing` | object or null | `reference` and `candidate`, each a `time_callable`-style summary (`seconds` per call, `min_s`, `median_s`, `mean_s`, `max_s`, `spread` = (max minus min) over median, `warmup`, `repeats`, `number`, `clock`, `sync`); null when nothing was timed |
| `peak_device_bytes` | object or null | On CUDA, `reference` and `candidate`: peak allocated bytes during each arm's first call (including memory allocated before it); null on other devices |
| `callables` | object | `reference` and `candidate` qualified names |
| `environment` | object | `environment(device)` at the end of the run |
| `git` | object | `git_state(root, source_files)` at the start |

A `timing-only` receipt from `timing_receipt` has `schema`, `kind`, `name`, `created_utc`, `status` (`timing-only`), `reason` (`timing only: no output comparison, so no speedup`), `device`, `dtype`, `sizes`, `timing` (by label), `environment` and `git`, and no speedup keys.

### What `check_receipt` reports

| Entry | Meaning |
| --- | --- |
| `receipt is not a mapping` | Not a dict (the only entry then) |
| `schema is ..., expected 1`, `kind is ..., expected 'kit-accelbench'` | Not a receipt of this schema |
| `status ... is not one of (...)` | Unknown status; nothing else is checked |
| `a timing-only receipt carries [...]`, `timing-only receipt has no timings` | A timing-only receipt with speedup keys, or without timings |
| `missing [...]` | A gated receipt without all three speedup keys |
| `settings.repeats is under 5` | Too few samples recorded |
| `status S carries [...]`, `status S carries timing` | A refusal with a speedup, or a `refused-mismatch` or `invalid-control` with timing |
| `refused-mismatch without a failed comparison`, `invalid-control without a control that passed`, `refused-unstable without a failed post-check` | A status its own fields do not support |
| `pass without a passing comparison`, `pass without a passing post-check`, `pass without a control that failed as required`, `pass without timing` | A `pass` its fields do not support |
| `timing L is missing`, `timing L has no seconds`, `timing L has fewer than 5 repeats`, `timing L has N samples for R repeats`, `timing L min_s is not the minimum of its seconds`, `timing L median_s is not the median of its seconds` | A timing summary that does not match its samples (L is the arm or label) |
| `KEY VALUE does not match the timing (EXPECTED)` | A speedup that differs from the one recomputed from the samples by more than a relative 1e-12 |
| `warning: no control was run`, `warning: no git commit recorded`, `warning: the source tree differed from its commit` | Not errors, but a reader should know |

### The script

`mps_precision.py` writes one `timing-only` receipt per net and mode, `OUT_DIR/<net>-<mode>.json`, and `OUT_DIR/summary.json` with `device`, `torch`, `threads`, `nets` and `rows` (one per arm: `net`, `mode`, `arm`, `median_s`, `min_s`, `spread`, `x_vs_fp32` and, for inference, `max_diff_vs_fp32`, or `skipped` with the reason).

| Exit code | Meaning |
| --- | --- |
| `0` | Every requested arm ran or was recorded as skipped |
| `1` | An uncaught exception printed a traceback (no torch, an unknown net, a receipt already in `OUT_DIR` without `--overwrite`, `--repeats` under 5) |
| `2` | A missing or wrong argument (argparse) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument to the script | Check the command against Commands and options |
| `device is required (cpu, cuda, cuda:N or mps)` | `device=None` | Name the device |
| `device is empty` | `device=''` or spaces | Name the device |
| `resolve 'auto' first (kit.accel.resolve_device), so the receipt names the device` | `device='auto'` | Call `kit.accel.resolve_device('auto')` and pass what it returns |
| `device 'NAME' needs kit/accel.py for its synchronisation; only cpu works without it` | A non-cpu device on a checkout without `kit/accel.py` | Use a checkout that has it (this one does) |
| `unknown net 'NAME'; use conv2d, conv3d, unet3d` | `--nets` names a network the script does not build | Use the names in the message |
| `device 'NAME' needs torch` | A non-cpu device and torch is not installed (also any unknown name such as `tpu`, since torch is imported before the name is checked) | Install torch, or use `cpu` |
| `device 'NAME': ...` | torch rejected the device with a RuntimeError, AssertionError, AttributeError or TypeError | Read the rest of the message; check torch's build for that device |
| `cuda requested but this torch sees no CUDA device`, `mps requested but torch.backends.mps.is_available() is False`, `unknown device 'NAME'; use ...` | kit.accel's own `ValueError`, passed through unchanged | Run on a machine with that device, or use `cpu` |
| `no synchronisation known for device 'NAME': kit.accel.synchronize waits only on cuda and mps` | kit.accel accepted a device of another type, so no sync is known; with the current kit.accel this cannot happen | Use `cpu`, `cuda`, `cuda:N` or `mps` |
| `sync must be a zero-argument callable or None` | `sync` is not callable | Pass a callable or None |
| `warmup must be an int, got ...` (also `repeats`, `number`) | A count that is not an int, or is a bool | Pass ints |
| `repeats must be at least 5, got N` | Fewer than `MIN_REPEATS` samples | Use 5 or more; 7 is the default |
| `warmup must be at least 0, got N` | A negative warm-up | Use 0 or more |
| `number must be at least 1, got N` | `number` under 1 | Use 1 or more |
| `setup() must return (args, kwargs)` | `setup()` returned something other than a 2-item tuple or list | Return `(args, kwargs)` |
| `setup must be a zero-argument callable or None` | `setup` is not callable | Pass a callable or None |
| `atol must be a number, got ...` (or `rtol`) | A tolerance that is not an int or float, or is a bool | Pass a number |
| `atol must be finite and at least 0, got ...` (or `rtol`) | A negative, NaN or infinite tolerance | Pass a finite number at least 0 |
| `bitwise comparison takes no tolerance; set atol = rtol = 0` | `bitwise=True` with a tolerance | Drop the tolerance, or drop `bitwise` |
| `max_reported must be an int of at least 0, got ...` | A bad `max_reported` | Pass an int at least 0 |
| `control must be 'perturb', a callable or None` | Any other `control` | Use one of the three |
| `sizes must be a dict without the keys 'inputs' and 'outputs'` | `sizes` is not a dict, or would overwrite the receipt's own keys | Rename those keys |
| `dtype must be a string or None` | `dtype` given as a type, such as `np.uint8` | Pass `np.dtype(...).name` or another string |
| `the output has no numeric leaf to perturb; pass control=None or a callable` | `control='perturb'` and the reference output holds no number with at least one element (only strings, empty arrays or None) | Pass a control callable that changes the output, or `control=None` (and say so) |
| `could not move VALUE past the rule` | The perturbed control could not find a value in the dtype that the rule rejects within 4096 doublings | Pass a control callable |
| `timings must be a non-empty dict {label: time_callable result}` | `timing_receipt` got no timings | Pass `{label: time_callable(...)}` |
| `timings['LABEL'] is not a time_callable result` | A value without a `seconds` list | Pass `time_callable` results unchanged |
| `timings['LABEL'] has fewer than 5 repeats` | A timing with under `MIN_REPEATS` samples | Time with 5 or more repeats |
| `sizes must be a dict or None` | `timing_receipt` got a non-dict `sizes` | Pass a dict |
| `a receipt holds only JSON values; got TYPE` | `write_receipt` met a value JSON cannot hold, such as an array in `sizes` | Put only numbers, strings, lists and dicts in `sizes` |
| A receipt with status `refused-mismatch`, `invalid-control` or `refused-unstable` | Not an error: the gate refused (reason in `reason`) | Fix the candidate, tighten the rule, or find the state that changes between calls; never quote a speed from it |

## How it works

`benchmark`, in order:

1. Validate every argument; resolve the sync (`sync_for(device)` unless given); record `git_state(root, source_files)` and the start time; on CUDA prepare the peak-memory reader.
2. Make the reference's inputs (`setup()` when given), describe them, run the reference once and sync; make fresh inputs, run the candidate once and sync. Compare the two outputs under the rule.
3. Build the control: with `perturb`, the reference output with one element moved past the rule (below); with a callable, `control(copy of the reference output)`, the copy detaching tensors. Compare it with the reference output; it must fail. Skipped with `control=None`.
4. If the control passed, return `invalid-control`; else if the outputs differed, return `refused-mismatch`. Neither times anything.
5. Warm up: `warmup` rounds of reference then candidate, each with fresh inputs and a sync.
6. Time: for each of `repeats` samples, the two arms in the order A, B on even samples and B, A on odd ones (ABBA). Each sample makes fresh inputs, syncs, reads the clock, calls the arm `number` times, syncs, reads the clock, and stores the time divided by `number`.
7. Compare the last outputs of the two arms again; a difference returns `refused-unstable`.
8. Return `pass` with the three speedups (`_ratio` gives null for a zero denominator or a non-finite result).

The comparison walks both outputs together. Containers must have the same type; dicts the same keys, lists and tuples the same length. Leaves must have the same category (a tensor never equals an array), the same shape, and the same dtype when `check_dtype` or `bitwise`. With `bitwise`, the stored bytes must be identical, so 0.0 and -0.0 differ and identical NaN bits match. Otherwise each float element needs abs(c - r) <= atol + rtol x abs(r), with r from the reference; infinities must match exactly; NaN fails unless `equal_nan` and both are NaN. Integer and bool leaves are always exact, as is any pair where one side is integer. Strings, bytes and None compare by equality. `max_abs_diff` and `max_rel_diff` are recorded over finite elements of every numeric leaf, even when it matched.

The perturbed control: the first float leaf (in walk order) moves its first finite element x to a value y stored in x's own dtype with abs(y - x) above atol + rtol x abs(x). It starts from x + 2 x (atol + rtol x abs(x)), or with a zero limit from x + max(abs(x) x 2^-60, 2^-160), and doubles the step until the stored value moves, up to 4096 times. A leaf with no finite element gets a 0. With no float leaf, the first integer element moves by 1 (down by 1 at the dtype's maximum); with no integer leaf, the first bool flips. Only the path to that element is copied, so the reference output is never changed. On a constant uint8 patch the receipt shows a move of 1.4e-45, the smallest float32 step above 0.

Constants that matter: `MIN_REPEATS = 5`, `DEFAULT_WARMUP = 3`, `DEFAULT_REPEATS = 7`, `_RELATIVE = 1e-12` (the tolerance `check_receipt` allows on a recomputed speedup), `_MAX_PATHS = 32` (dict items described and dirty paths kept).

`environment` reads `/proc/cpuinfo` for the CPU name (on a Mac, `sysctl -n machdep.cpu.brand_string`, marked untested in the code), package versions from `importlib.metadata`, and torch's live flags (threads, deterministic algorithms, cuDNN benchmark and deterministic, TF32 for matmul and cuDNN, float32 matmul precision). On CUDA it adds the card's name, capability, memory and UUID.

`write_receipt` writes to a temporary file in the target folder, flushes, sets mode 0644 (mkstemp makes 0600), fsyncs, then hard-links it to the target, which fails if the target appeared meanwhile, and removes the temporary name.

## Cost and time

- 2026-11-18, 4 logical CPU Intel Xeon cloud container, numpy only: the Quick start example 0.29 s wall (top-10 of 1,000,000 float64: reference minimum 7.5 ms, candidate 1.7 ms per call); `tests.test_accelbench` and `tests.test_accel` together 0.21 s (39 tests, 17 skipped without torch).
- 23 Oct 2026, 4 logical CPU cloud container, torch 2.14.1+cpu: the precision script's smoke run (above).
- Memory: the module keeps one output per arm at a time plus the control; not measured otherwise. Peak device memory on CUDA is recorded per receipt.
- Where it runs: CPU timing of small functions runs locally. Note that a receipt's numbers belong to the machine that made it: a cloud card's receipt says nothing about a laptop.
- It rents nothing itself.


## For agents

- **Command:** in Python, `accelbench.benchmark(reference, candidate, args=(...), device='cpu', bitwise=True, name='NAME', source_files=('PATH',))` then `accelbench.write_receipt(receipt, 'work/.../NAME.json')`; on a GPU, `python3 scripts/accelbench/mps_precision.py OUT_DIR`. The receipt JSON is the machine-readable form.
- **Parse:** `status` first; only on `pass` read `speedup` (ratio of minima), `speedup_median` and `speedup_paired_median`. Also `comparison.max_abs_diff`, `control.failed_as_required`, `post_check.pass`, `timing.reference.min_s` and `timing.candidate.min_s` (seconds per call), `settings`, `environment.device`, `git.commit` and `git.dirty`. For the script, `summary.json` `rows[]`.
- **Rerun:** safe; timings differ from run to run. `write_receipt` refuses to overwrite unless asked, so write each run to a new path or folder.
- **Success:** status `pass` and `check_receipt` returning no entry without the `warning:` prefix; for the script, exit 0.
- **Not a pass:** a speedup from `timing-only`, or from any receipt whose `check_receipt` has errors; a `pass` with `control.kind` null; a `pass` with `git.dirty` true or `git.commit` null (the code is not pinned); one run on a shared CPU (rerun and compare minima); a CPU receipt quoted for a GPU or another machine; a receipt on synthetic inputs quoted as the speedup on real data.
- **Go-ahead:** GPU timing on rented hardware (hard rule 11). Nothing for a local run.
- **Never:** quote a speed for code whose receipt is a refusal; loosen `atol` or `rtol` until a candidate passes without saying so; skip the control and call it a pass; time GPU code without a device sync; call anything in a receipt a reading.

## Tests

```bash
python3 -m unittest tests.test_accelbench -v
```

The tests cover the gate (a faster wrong candidate is refused and never timed), the perturbed control for every leaf kind, ABBA order with a fake clock, the device sync with fake torch and `kit.accel` modules, receipt writing without overwrite, and `check_receipt` on altered receipts. They use fake clocks, so none can flake on a busy machine; the real CUDA and MPS checks skip on a machine without them. 2026-11-18: 23 tests, 3 skipped without torch, in 0.16 s.

## History

- 2026-11-18: released to public Scrolls with [accel](accel.md) and the precision script (`9f89964`). Before that it was developed outside this repository: the gate, the perturbed control and the receipts from 15 Oct 2026, the precision script from 23 Oct 2026.

## Related

- [accel](accel.md): device and precision choice, and the sync this module calls.
- [cloudcost](cloudcost.md): pricing a run before a GPU benchmark.
