# accel: pick the torch device and precision, and check them

`kit/accel.py` gives torch scripts one rule for the device (CUDA, then Apple MPS, then CPU) and the precision (bf16, fp16 or fp32 autocast); `python -m kit.accel --check` tests that choice on this machine against CPU fp32, with a control.

| Field | Value |
| --- | --- |
| Id | `accel` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Compute and cost |
| Run | `python -m kit.accel`, `from kit import accel` |
| Code | `kit/accel.py` |
| Tests | `tests/test_accel.py` |
| Needs | Python 3.10 or newer. `import kit.accel` needs only the standard library; every function that touches a device, and the command, needs torch (run with 2.14.1 on a cloud CPU and an Apple M1 Pro; older versions not tested). A CUDA card or Apple GPU only for those devices |
| Runs on | CUDA, MPS or CPU. The choice is instant; `--check` runs a toy network on a 2 x 1 x 16 x 64 x 64 input (not timed on its own) |
| Network | None |
| Writes | Nothing (prints one JSON object). The Python API changes torch state only where asked: `disable_tf32()` switches both global TF32 flags off |
| Go-ahead | Not needed to run it on a machine you already have. Running `--check` on a rented GPU follows hard rule 11 |
| Released | Public `main` from the PR that adds this page (2026-11-18), with [accelbench](accelbench.md). The scroll center finder (`scripts/umbilicus/`) carries its own copy of the device rule, not this module |
| Checked | 2026-11-18 against commit `c2cb575` |

## What it does

Torch scripts that hard-code `cuda` or `cpu` and `torch.autocast("cuda", ...)` run on the CPU on a Mac unless told otherwise, and on MPS they run plain fp32, because torch turns `autocast("cuda")` off where there is no CUDA. A trainer asked for `amp: bf16` on MPS can enter CPU autocast, which casts nothing on MPS tensors, so it runs fp32 while its log says bf16. `kit/accel.py` is one place that decides.

**Device.** `--device auto` (the default) takes CUDA when torch sees a CUDA card, else MPS (Apple's GPU, "Metal Performance Shaders") when torch sees it, else the CPU. A named device (`cuda`, `cuda:N`, `mps`, `cpu`) is checked and refused when this torch cannot use it, so a typo or a missing GPU never falls back to the CPU in silence.


**Check.** `python -m kit.accel --check` runs a small seeded 3D-to-2D network (a toy, not an ink model) on the chosen device and precision and on the CPU in fp32, and compares the output logits. Its control is the CPU fp32 output for the same input with the depth order reversed, which must differ by at least ten times the tolerance; otherwise the check could not fail and counts as failed. It shows that the device and autocast work on this machine. It says nothing about a given model's maps, and an ink map from any script that uses this module is model output, not a reading.

## When to use it

- Writing or changing a torch script that should run on CUDA, MPS or the CPU: call `accel.add_arguments(parser)`, then `accel.from_args(args)`, and wrap the forward pass in `accel.autocast(device, precision)`.
- Checking that a machine's GPU and autocast give the CPU's numbers before trusting a timing or a run there: `python -m kit.accel --check`.
- Recording what actually ran: put `accel.describe(device, precision)` in the run's record.
- Waiting for queued GPU work before reading a clock: `accel.synchronize(device)` ([accelbench](accelbench.md) does this for you).

Do not use it:

- To check that a real model's ink maps agree between devices: use [`verify`](verify.md) (`python -m kit verify --control`) on a real map pair.
- To time two implementations: use [accelbench](accelbench.md).
- To price a cloud run: use [`cloudcost`](cloudcost.md).
- Inside files whose bytes are pinned for a reproduction: change those only with the reproduction.

## Quick start

```bash
python -m kit.accel                              # what auto picks on this machine, as JSON
python -m kit.accel --check                      # the choice against CPU fp32, with its control; exit 0 when ok
python -m kit.accel --check --fp32               # the same device with autocast off
python -m kit.accel --check --precision bf16     # bf16 autocast; refused where the device cannot do it
```

Run it with a Python that has torch. On an Apple M1 Pro (16 October 2026, torch 2.14.1, when `auto` still picked fp16 on MPS), `python -m kit.accel` printed `"device": "mps"` and `"precision": "fp16"`, and `--check` printed, among its fields:

```
"device": "mps", "precision": "fp16", "max_diff": 0.006068, "tolerance": 0.03,
"control_max_diff": 6.602192, "control_caught": true, "agrees": true, "ok": true
```

Without torch, the command stops with `ModuleNotFoundError: No module named 'torch'` and exit code 1. It worked when the exit code is 0 and `ok` is `true`.

## Checks and controls

- **The check can fail both ways.** `agrees` is false when the device's logits differ from CPU fp32 by more than the tolerance over the reference's standard deviation; `control_caught` is false when the depth-reversed control differs by no more than `CONTROL_FACTOR` (10) times the tolerance. `ok` needs both. `tests/test_accel.py` shows each failing: a forward hook that shifts the device run's output by 1.0 makes `agrees` false, and a control factor of 1e6 makes `control_caught` false.
- **Tolerances** (`TOLERANCE` in the code, the largest logit difference over the reference's standard deviation): fp32 0.001, fp32 on CUDA with TF32 allowed 0.03, bf16 0.15, fp16 0.03. On a CPU with torch 2.14.1 the check measured 0 for fp32, 0.006 for fp16, 0.05 for bf16 and 6.6 for the control (code comment). TF32 emulated on the CPU, by rounding the convolutions' inputs and weights to 10 mantissa bits, gave 0.0065 (code comment).
- **Measured on real hardware.** An Apple M1 Pro, 16 October 2026, torch 2.14.1, macOS 27.0: fp16 0.006068 (tolerance 0.03), fp32 0.000004 (0.001), bf16 0.049663 (0.15), control 6.602192, caught each time, all `ok`. CUDA has not been run through `--check` on a real card; the tests simulate it with mocks.
- **What a pass does not show.** The toy network has three layers and random weights. A pass says the device and autocast give the CPU's numbers to within the tolerance on it, not that a trained ink or surface model's maps agree. That needs [`verify`](verify.md) with its control on a real map pair.

Claim label: Model output, for the check's differences on a toy network; Sourced fact, for the M1 Pro results as recorded from that run.
## Commands and options

### `python -m kit.accel`

```
usage: python -m kit.accel [-h] [--device DEVICE] [--precision PRECISION]
                           [--fp32] [--check]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--device DEVICE` | `auto` | `auto` (CUDA, then MPS, then CPU), `cpu`, `cuda`, `cuda:N` or `mps`. Case and spaces are ignored. A named device torch cannot use is refused with exit code 2 |
| `--precision PRECISION` | `auto` | `auto`, `bf16`, `fp16` or `fp32`; also the aliases `bfloat16` (bf16), `float16` and `half` (fp16), `float32`, `none`, `off` and `full` (fp32). `auto` resolves per device as under What it does |
| `--fp32` | off | Full fp32, no autocast; the same as `--precision fp32`. With `--precision bf16` or `fp16` it is refused (`--fp32 contradicts --precision ...`) |
| `--check` | off | Run the forward check against CPU fp32, with its control, and exit 1 when `ok` is false. Without it, print only what was chosen |

The same `--device`, `--precision` and `--fp32` flags, with the same meanings, are what `accel.add_arguments` adds to the scripts that use it. A script may pass other defaults (`add_arguments(parser, device=..., precision=..., fp32_flag=False)`), so check that script's `--help`.

## Python API

```python
import argparse
from kit import accel
ap = accel.add_arguments(argparse.ArgumentParser())
args = ap.parse_args()
device, precision = accel.from_args(args)          # such as ("mps", "fp16"); raises ValueError on a bad combination
model = model.to(device)
with accel.autocast(device, precision):
    out = model(batch.to(device))
scaler = accel.grad_scaler(device, precision)      # on only for fp16 on CUDA or MPS
record = accel.describe(device, precision)          # store in the run's record
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `device_type(device)` | str: the bare type, such as `'cuda'` for `'cuda:1'` | Nothing | Accepts a string or a `torch.device`; lowercases and strips a string. Needs no torch. `torch.autocast` and `GradScaler` want the bare type |
| `mps_available(torch=None)` | bool | `ModuleNotFoundError` without torch | False when this torch has no `torch.backends.mps` |
| `resolve_device(name='auto')` | str: `'cuda'`, `'mps'` or `'cpu'` for `auto`; otherwise the name, lowercased | `ValueError` for an unknown or unsupported device, a CUDA or MPS device torch cannot see, or a `cuda:N` past the card count; `ModuleNotFoundError` without torch | `None` counts as `auto` |
| `cuda_bf16_native(device='cuda', torch=None)` | bool: compute capability 8.0 or newer | Nothing (it returns False when torch cannot read the capability) | False without CUDA |
| `mps_autocast_available(torch=None)` | bool | `ModuleNotFoundError` without torch | Asks `torch.amp.is_autocast_available('mps')`; False when this torch has no such function |
| `normalize_precision(precision)` | str: `'auto'`, `'bf16'`, `'fp16'` or `'fp32'` | `ValueError` (`unknown precision ...`) | Maps the aliases in `ALIASES`; `None` counts as `auto`. Needs no torch. It is the `type` of `--precision`, so on the command line a bad value shows argparse's `invalid normalize_precision value` |
| `resolve_precision(device, precision='auto')` | str: `'bf16'`, `'fp16'` or `'fp32'` | `ValueError` for bf16 on a CUDA card without native bf16, a 16-bit precision on MPS with no MPS autocast, an unsupported device, or an unknown precision | `auto` on MPS without autocast gives `'fp32'`; an explicit `bf16` or `fp16` on the CPU is kept (CPU autocast) |
| `dtype(precision)` | `torch.bfloat16`, `torch.float16`, or `None` for fp32 | `ValueError` for an unknown precision; `KeyError` for `'auto'` (resolve it first) | |
| `autocast(device, precision)` | A context manager: `torch.autocast(device_type=..., dtype=...)`, or `contextlib.nullcontext()` for fp32 | As `resolve_precision` when given `auto`; torch's own errors where the device cannot autocast that dtype | Resolves `auto` itself; passes the bare device type |
| `grad_scaler(device, precision)` | `torch.amp.GradScaler`, enabled only for fp16 on CUDA or MPS | As `resolve_precision` when given `auto` | Disabled, `scaler.scale(loss).backward(); scaler.step(opt); scaler.update()` steps exactly as a plain `backward(); step()` (bitwise test in the PR) |
| `synchronize(device)` | None | Torch's errors for a device it cannot reach | `torch.cuda.synchronize` or `torch.mps.synchronize`; a no-op on the CPU. Call before reading a timer |
| `disable_tf32()` | None | `ModuleNotFoundError` without torch | Sets `torch.backends.cuda.matmul.allow_tf32` and `torch.backends.cudnn.allow_tf32` to False for the whole process |
| `add_arguments(parser, device='auto', precision='auto', fp32_flag=True)` | The parser | Nothing | Adds `--device`, `--precision` (typed by `normalize_precision`) and, unless `fp32_flag` is False, `--fp32` |
| `from_args(args)` | `(device, precision)`, both resolved and checked | `ValueError` for `--fp32` with `--precision bf16` or `fp16`, and as `resolve_device` and `resolve_precision` | Reads `args.device`, `args.precision` and `args.fp32` (when present) |
| `describe(device, precision)` | dict: `device`, `device_type`, `precision`, `autocast_dtype`, `torch`, and `gpu` on CUDA | As `resolve_precision` | JSON-ready; what the command prints without `--check` |
| `check(device, precision, seed=20261015, depth=16, size=64, batch=2)` | dict: the `describe` fields plus the check fields under Outputs | As `resolve_precision`; torch's errors on the device | Builds a new toy network each call and moves it to `device` |
| `main(argv=None)` | int: 0, or 1 when `--check` is not `ok` | `SystemExit(2)` from `parser.error` on a bad device or flag | The command; `argv` is a list of arguments, as on the command line |

Constants: `PRECISIONS = ('auto', 'bf16', 'fp16', 'fp32')`, `ALIASES`, `TOLERANCE = {'fp32': 1e-3, 'tf32': 0.03, 'bf16': 0.15, 'fp16': 0.03}`, `CONTROL_FACTOR = 10`, and the help strings `DEVICE_HELP` and `PRECISION_HELP`.

## Inputs

The command reads only its flags. `check` makes its own input: a seeded (`seed=20261015`) uniform random tensor of shape (batch 2, channel 1, depth 16, 64, 64), shifted by 0.5 and divided by 0.29, so about zero mean and unit variance. No file, scan or model is read.

## Outputs

One JSON object on stdout, indented by 2.

Without `--check` (`describe`):

| Field | Type | Meaning |
| --- | --- | --- |
| `device` | str | The resolved device, such as `mps` or `cuda:1` |
| `device_type` | str | Its bare type: `cuda`, `mps` or `cpu` |
| `precision` | str | The resolved precision: `bf16`, `fp16` or `fp32` |
| `autocast_dtype` | str or null | `bfloat16` or `float16`; null for fp32 (no autocast) |
| `torch` | str | `torch.__version__` |
| `gpu` | str | The CUDA card's name; only on CUDA |

With `--check`, the same fields and:

| Field | Type | Meaning |
| --- | --- | --- |
| `tf32_allowed` | bool | True for fp32 on CUDA with either TF32 flag on; then the `tf32` tolerance applies |
| `check` | str | `toy forward against CPU fp32: max logit difference over the reference std` |
| `max_diff` | float (6 decimals) | Largest absolute logit difference between the device run and CPU fp32, over the CPU fp32 logits' standard deviation |
| `tolerance` | float | The bound `max_diff` must not exceed, from `TOLERANCE` |
| `control` | str | `depth order reversed, CPU fp32` |
| `control_max_diff` | float (6 decimals) | The same measure for the depth-reversed input against the reference |
| `control_caught` | bool | `control_max_diff` above `CONTROL_FACTOR` times `tolerance` |
| `agrees` | bool | `max_diff` at most `tolerance` |
| `ok` | bool | `agrees` and `control_caught` |

| Exit code | Meaning |
| --- | --- |
| `0` | Printed the choice, or `--check` ran and `ok` is true |
| `1` | `--check` ran and `ok` is false (read `agrees` and `control_caught`), or an uncaught error with a traceback, such as no torch (`ModuleNotFoundError`) |
| `2` | A bad flag, an unknown or unusable device, a precision the device cannot do, or `--fp32` with a contradicting `--precision`; the message is on stderr after the usage line |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `ModuleNotFoundError: No module named 'torch'` and a traceback, exit code 1 | This Python has no torch | Run with villa's Python or another environment with torch |
| `error: argument --precision: invalid normalize_precision value: 'int8'`, exit code 2 | A precision that is not `auto`, `bf16`, `fp16`, `fp32` or an alias | Use one of those |
| `unknown precision 'int8'; use auto, bf16, fp16, fp32` | The same, from the Python API | Use one of those |
| `error: unknown device 'gpu'; use auto (CUDA, then MPS, then CPU; the default), cuda, cuda:N, mps or cpu`, exit code 2 | torch does not know the name | Use one of the listed names |
| `error: unsupported device 'meta'; use ...`, exit code 2 (from `resolve_precision` through the API: `unsupported device 'xla'`) | A device torch knows but this module does not drive | Use `cuda`, `mps` or `cpu` |
| `error: cuda requested but this torch sees no CUDA device`, exit code 2 | No CUDA card, or a torch built without CUDA | Use `--device auto` or `cpu`, or install a CUDA build of torch |
| `error: cuda:2 requested but this machine has 2 CUDA device(s)` | The index is past the last card (they count from 0) | Use an index below the count |
| `error: mps requested but torch.backends.mps.is_available() is False` | Not an Apple GPU, or a torch or macOS without MPS | Use `--device auto` or `cpu` |
| `error: this CUDA card has no native bf16; use --precision fp16 or fp32` | `--precision bf16` on a card older than compute capability 8.0. It is refused rather than emulated, which is slow and was never used for a recorded run | Use `fp16`, `fp32` or `auto` |
| `error: torch 2.1.0 has no MPS autocast; use --precision fp32` (the version varies) | `bf16` or `fp16` asked for on MPS with a torch that cannot autocast there (`auto` falls back to fp32 instead) | Use `--precision fp32`, or a newer torch |
| `error: --fp32 contradicts --precision bf16` | `--fp32` together with a 16-bit `--precision` | Drop one of them |
| `"ok": false` with `"agrees": false`, exit code 1 | The device's numbers differ from CPU fp32 beyond the tolerance: a broken device path, or a precision too coarse for the bound | Rerun with `--fp32` to see whether the device or the precision is at fault; do not trust timings or runs on that path until it agrees |
| `"ok": false` with `"control_caught": false`, exit code 1 | The control did not differ enough, so the check could not have failed: something is wrong with the check itself | Report it; do not count the run as a pass |

## How it works

1. `resolve_device`: `auto` asks `torch.cuda.is_available()`, then `torch.backends.mps.is_available()`. A named device goes through `torch.device(name)`; CUDA is checked for availability and index, MPS for availability, and any other type than `cpu` is refused.
2. `resolve_precision`: `fp32` is returned as it is. On CUDA, `auto` is bf16 when `torch.cuda.get_device_capability` gives a major version of 8 or more, else fp16; an explicit bf16 below 8 is refused. On MPS, without MPS autocast `auto` is fp32 and an explicit 16-bit precision is refused; with it, `auto` is fp16. On the CPU, `auto` is fp32 and an explicit bf16 or fp16 is kept.
3. `from_args` resolves the device first, then the precision; `--fp32` forces fp32 and is refused next to a 16-bit `--precision`.
4. `autocast` returns `torch.autocast(device_type=BARE_TYPE, dtype=...)` (torch 2.14 accepts `cuda:1` but then skips its check that CUDA is there, so the bare type matters), or a null context for fp32.
5. `check`: build the toy network from a seeded generator: `Conv3d(1, 4, 3)`, GELU, a flatten of channels and depth, `Conv2d(64, 8, 3)`, GELU, `Conv2d(8, 1, 1)`, each weight drawn as `randn * sqrt(2 / fan_in)`. Compute the CPU fp32 logits of the input (the reference) and of the input with its depth axis flipped (the control), then the logits on the device under `autocast`. Scale every difference by the reference's standard deviation. The tolerance is `TOLERANCE[precision]`, or `TOLERANCE['tf32']` for fp32 on CUDA while either TF32 flag is on.

Sources: torch's documentation of `torch.autocast` and `torch.amp.GradScaler` for what autocast casts on each device; the thresholds are this module's own, set from the CPU measurements in the code comment.

## Cost and time

The device and precision choice takes no measurable time. `--check` was not timed on its own anywhere; it is one forward pass of a three-layer network on a 2 x 16 x 64 x 64 input, three times (Interpretation, from the code). Without torch, `tests.test_accel` ran 16 tests (14 skipped) in 0.03 s (2026-11-18, 4 logical CPU Xeon cloud container). It rents nothing. Run it on the machine you are about to use.

## For agents


- **Command:** `python -m kit.accel --check` (add `--device D` and `--precision P` to test a specific path); `python -m kit.accel` alone prints the choice. Both print JSON.
- **Parse:** `device`, `precision` and `autocast_dtype` for what was chosen; with `--check`, `ok`, `agrees`, `max_diff`, `tolerance`, `control_caught` and `control_max_diff`.
- **Rerun:** Safe; it writes nothing and the check is seeded, so a rerun on the same machine and torch gives the same numbers.
- **Success:** Exit code 0; with `--check`, `"ok": true`.
- **Not a pass:** `ok` true says nothing about a real model's maps (use `verify --control`); a run without `--check` is not a check at all; `ok` from `--device cpu` says nothing about the GPU.
- **Go-ahead:** Nothing on a machine you already have. A run on rented hardware follows hard rule 11.
- **Never:** Change a recorded run's device or precision silently (pass `--fp32` or `--device cpu` to reproduce an fp32 or CPU number); call a passing check a statement about a real model's maps.

## Tests

```bash
python -m unittest tests.test_accel -v
```

`tests/test_accel.py` covers importing without torch, device and precision names and aliases, the device order and refusals (CUDA, `cuda:N`, MPS and unknown devices, simulated with mocks), the precision per device (CUDA with and without native bf16, MPS with and without autocast, CPU), that fp32 never autocasts, that CPU autocast really casts, the bare device type passed to `torch.autocast`, the GradScaler only for fp16 on a GPU, the flags and their contradictions, the command's JSON and exit codes, `--check` passing on the CPU in all three precisions with its control caught, `--check` failing on a shifted device output and on an uncatchable control, and the TF32 bound for fp32 on simulated CUDA. All but two tests need torch and are skipped without it (16 tests, 14 skipped, in a cloud container on 2026-11-18). No test runs on a real CUDA card; the MPS path ran for real only in the Mac check.

## History

- 2026-11-18: released to public Scrolls with [accelbench](accelbench.md) (`9f89964`). Before that it was developed outside this repository: first version 15 Oct 2026, `--check` with its control and the TF32 bound 16 Oct, `--precision auto` fp32 on MPS (was fp16) after the M1 Pro measurement, 23 Oct.

## Related

- [accelbench](accelbench.md): correctness-gated timing, which calls `synchronize`.
- [`verify`](verify.md): device agreement for real maps, with a control.
- [`umbilicus`](umbilicus.md): the scroll center finder, which carries its own copy of these rules.
