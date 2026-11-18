# mpsparity: check that a small training gives the same result on Apple MPS as on the CPU

`kit.mpsparity` checks that a torch network computes and trains the same on one device (Apple's MPS, or CUDA) as on another (the CPU), with forward, gradient and short-training checks that each carry a control that must be able to fail.

| Field | Value |
| --- | --- |
| Id | `mpsparity` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Compute and cost |
| Run | `python -m kit.mpsparity run`, `python -m kit.mpsparity ops`, `python -m kit.mpsparity list`, `from kit import mpsparity` |
| Code | `kit/mpsparity.py` |
| Tests | `tests/test_mpsparity.py` |
| Needs | Python 3.10 or newer and torch (checked with torch 2.15.0+cpu and Python 3.13.18). An Apple silicon Mac with an MPS build of torch for `--device mps`, a CUDA card for `cuda` |
| Runs on | CPU, MPS or CUDA. The CPU self check of the three built-in networks took 3.1 s wall at 10 steps (measured 2026-11-18, 4 logical CPU Intel Xeon cloud container) |
| Network | None |
| Writes | Nothing, unless `--out FILE` (one JSON record; parent folders created) |
| Go-ahead | Not needed on a machine you already have |
| Released | Public `main` from the PR that adds this page (2026-11-18) |
| Checked | 2026-11-18 against commit `c2cb575` |

## What it does

A torch training script that gains a `--device` flag can run on Apple's GPU (MPS, "Metal Performance Shaders"), but MPS kernels are not the CPU's kernels: an operator can be missing, can round differently, or can drift through an optimizer. `kit.mpsparity` answers one question before a GPU run counts: does this network compute the same thing on DEV as on REF (by default `mps` against `cpu`)?

It builds one seeded copy of the network on each device and compares three things on identical synthetic inputs: the eval-mode forward output, one train-mode gradient, and the weights after a short AdamW run. Each comparison has a control that must differ by at least ten times the tolerance, or the check is VOID rather than a pass. Three built-in networks cover common layers (`conv3d`: 3D convolutions with GroupNorm and Dropout3d; `conv2d`: a 2D network with BatchNorm2d that reads depth slices as channels; `unet3d`: a small 3D U-Net with InstanceNorm3d, a strided convolution and ConvTranspose3d). `--script PATH --build NAME --shape B,C,D,H,W` checks a network of your own. `ops` probes operators that 3D data paths use, such as 3D `grid_sample` and generators on the device.

It says nothing about a model's quality, and nothing about the data loading, which a script may keep on the CPU. A PASS says this network trains like the reference on synthetic inputs; a number measured on one device still needs its own check before it is quoted for another.

## When to use it

- Before trusting a training or fine-tuning run on a Mac's GPU (or a new CUDA card) whose earlier runs were on the CPU or another device.
- After a torch upgrade, to see whether an operator gained or lost an MPS kernel (`ops`, and a `run` FAIL with `NotImplementedError`).
- To estimate seconds per training step on the device at a real batch and shape (`--bench N`).

Do not use it:

- To check that one model's ink maps agree between devices: use [`verify`](verify.md) (`python -m kit verify --control`) on a real map pair.
- To pick the device and precision a script runs with: use `kit.accel` ([#359](https://github.com/ChaseHendrick/Scrolls/pull/359)), whose `--check` compares a toy forward pass only.
- To time two implementations of the same function: use `kit.accelbench` ([#359](https://github.com/ChaseHendrick/Scrolls/pull/359)).

## Quick start

```bash
python -m kit.mpsparity run --device cpu                                         # the self check, any machine with torch
python -m kit.mpsparity run --device mps --steps 10 --bench 5 --out OUT.json     # on a Mac
python -m kit.mpsparity run --device mps --script mynet.py --build Net --shape 2,1,16,32,32   # your own network
python -m kit.mpsparity ops --device mps                                         # data-path operators on MPS
```

- `OUT.json`: where the record goes.
- `mynet.py`, `Net`: a Python file and a callable in it that takes no arguments and returns the `torch.nn.Module`.

The self check printed (2026-11-18, 4 logical CPU cloud container, torch 2.15.0+cpu, 3.1 s wall):

```
conv3d: PASS: forward PASS 0.00e+00 (control 5.75e+00), grad PASS 0.00e+00 (control 4.00e-01), train PASS 0.00e+00 (control 4.65e-01)
conv2d: PASS: forward PASS 0.00e+00 (control 5.36e+00), grad PASS 0.00e+00 (control 9.95e-01), train PASS 0.00e+00 (control 9.12e-01)
unet3d: PASS: forward PASS 0.00e+00 (control 5.73e+00), grad PASS 0.00e+00 (control 9.45e-01), train PASS 0.00e+00 (control 9.89e-01)
ALL PASS
```

On the CPU against the CPU every value is 0: this only shows the checks run and their controls are far past ten times the tolerance. It worked when the last line is `ALL PASS` and the exit status is 0.

## Checks and controls

| Check | Value | Tolerance | Control (must reach 10 times the tolerance, else VOID) |
| --- | --- | --- | --- |
| forward | largest output difference over the reference output's standard deviation (eval mode) | 1e-3 | the reference output for the input with its depth order (axis 2) reversed |
| grad | norm of the gradient difference over the reference gradient's norm (train mode, dropout off, MSE to a seeded target) | 1e-3 | the reference gradient for the reversed input |
| train | distance between the two final weight sets over the distance the reference moved, after `--steps` AdamW steps (lr 1e-3) on identical batches | 0.02 | the reference trained on the same batches in reverse order |

The tests show each check fails when the device copy's weights carry 5 % noise and is VOID when the network ignores its input.

**The bf16 bar** (`--bar bf16`). The fixed tolerances can be stricter than the rounding noise of fp32 itself. On an Apple M5 Pro (7 Nov 2026), four small 3D training networks were checked on the fixed tolerances: one passed and three failed at about the CPU's own fp32 rounding. The bf16 bar was then set, before it was applied to fresh seeds 1 and 2: DEV in fp32 must sit nearer the REF fp32 result than bf16 autocast does on REF, a precision many CUDA training runs already use. On it all four passed on both seeds (one forward check VOID, which the bar allows: an untrained network's output can barely depend on its input). Those networks are not in this repository, so this is a measurement of them, not of the built-in ones.

Claim label: Model output (the check's numbers are measurements of networks on synthetic inputs, not of any scroll); Sourced fact for the M5 Pro results as recorded from those runs.

## Commands and options

### `python -m kit.mpsparity run`

```
usage: python -m kit.mpsparity run [-h] [--models MODELS] [--script SCRIPT]
                                   [--build BUILD] [--shape SHAPE]
                                   [--real-shape REAL_SHAPE] [--device DEVICE]
                                   [--ref REF] [--steps STEPS] [--bench BENCH]
                                   [--bench-batch BENCH_BATCH]
                                   [--max-gb MAX_GB] [--bar {fixed,bf16}]
                                   [--seed SEED] [--out OUT] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--models MODELS` | all built-in, or none with `--script` | comma list of `conv3d`, `conv2d`, `unet3d` |
| `--script SCRIPT` | none | a Python file that defines your network; it is imported with its folder on `sys.path` |
| `--build BUILD` | none | the callable in `--script` that takes no arguments and returns the network |
| `--shape SHAPE` | none | with `--script`: the small check shape `B,C,D,H,W`; axis 2 is reversed for the control |
| `--real-shape REAL_SHAPE` | `--shape` | with `--script`: the batch and shape `--bench` times |
| `--device DEVICE` | `mps` | DEV: `mps`, `cuda`, `cuda:N` or `cpu` |
| `--ref REF` | `cpu` | REF, the same names |
| `--steps STEPS` | `10` | AdamW steps in the train check |
| `--bench BENCH` | `0` | also time N training steps at the real shape on DEV |
| `--bench-batch BENCH_BATCH` | the real batch | `--bench` with this batch instead (`s_per_sample` scales it) |
| `--max-gb MAX_GB` | `12` | on MPS, refuse allocations past this many GB, so an oversized bench is an out-of-memory error, not swap |
| `--bar {fixed,bf16}` | `fixed` | `fixed`: the tolerances above; `bf16`: DEV must beat bf16 autocast on REF |
| `--seed SEED` | `0` | seed for networks, inputs and targets |
| `--out OUT` | none | write the record here as JSON |
| `--json` | off | print the record instead of one line per network |

### `python -m kit.mpsparity ops`

```
usage: python -m kit.mpsparity ops [-h] [--device DEVICE] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--device DEVICE` | `mps` | the device to probe against the CPU |
| `--json` | off | print the record as JSON |

### `python -m kit.mpsparity list`

Prints the built-in networks with their small and real shapes. No options.

## Python API

```python
from kit import mpsparity as M
r = M.forward_check(build, (2, 1, 16, 16, 16), "cpu", "mps")   # build: a callable returning the network
rec = M.run_model("unet3d", ref="cpu", dev="mps", steps=10)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `load_script(name, models=None)` | the network's script as a module, or None for a built-in | `ValueError` when the script is missing; `ImportError` when its imports are | its folder is on `sys.path` while it imports |
| `check_device(name)` | the name | `ValueError` for an unknown or unavailable device | `mps`, `cuda`, `cuda:N`, `cpu` |
| `sync(device)` | None | | waits for MPS or CUDA work before a timing |
| `make_input(shape, seed, mask_channel=None)` | a seeded CPU tensor | | normal noise; `mask_channel` holds 0 or 1 |
| `flat_out(out)` | one flat float tensor | | joins tuple outputs |
| `no_dropout(net)` | the network, dropout p set to 0 | | so neither device draws at random |
| `pair(build, ref, dev, seed, mutate_dev=None)` | (base, ref copy, dev copy) | | two copies of one seeded network; `mutate_dev` changes the DEV copy (tests only) |
| `outcome(value, tol, control)` | `PASS`, `FAIL` or `VOID` | | VOID when the control is under 10 times the tolerance |
| `forward_check(build, small, ref, dev, seed=0, mask_channel=None, mutate_dev=None, tol=FWD_TOL, dev_amp=False)` | dict: `check`, `value`, `tol`, `control`, `outcome` | torch errors | `dev_amp` runs DEV under bf16 autocast (the bar) |
| `grad_check(build, small, ref, dev, seed=0, mask_channel=None, mutate_dev=None, tol=GRAD_TOL, dev_amp=False)` | the same | torch errors | |
| `train_check(build, small, ref, dev, seed=0, steps=10, mask_channel=None, mutate_dev=None, tol=TRAIN_TOL, dev_amp=False)` | the same, plus both loss curves and their largest relative difference | torch errors | |
| `device_type(device)` | `'mps'` for `'mps'`, `'cuda'` for `'cuda:1'` | | for autocast |
| `bar_outcome(value, bar, control)` | `PASS`, `FAIL` or `VOID` | | PASS when value is under the bar; VOID when the control is not past it |
| `cap_memory(dev, max_gb=MAX_GB)` | the MPS memory fraction set, or None off MPS | | |
| `bench(build, real, dev, steps, mask_channel=None, seed=0, batch=None)` | dict: `batch_shape`, `steps`, `s_per_step`, `s_per_sample`, `mps_driver_gb` on MPS | torch errors, out of memory | first step left out as warm-up |
| `run_model(name, ref='cpu', dev='mps', steps=10, bench_steps=0, seed=0, bench_batch=None, bar='fixed', models=None)` | dict per network with its checks and `outcome` | `ValueError` from `load_script` | an error inside a check is recorded as a FAIL with its text |
| `custom_model(script, build, shape, real=None)` | a `MODELS`-style entry for your own network | `ValueError` when an argument is missing or the script is not a file | pass it in `models` under a name of your choice |
| `parse_shape(text)` | a tuple of ints | `ValueError` for fewer than 3 positive ints | `2,1,16,32,32` |
| `ops(dev='mps', tol=0.0001)` | dict of operators, `ok` and `rel` or the error | | each operator on DEV against the CPU |
| `environment(dev)` | dict: `torch`, `python`, `machine`, `system`, `device`, `fallback_env`, `threads` | | |
| `main(argv=None)` | exit status | `SystemExit` 2 on a usage error | |

Constants: `FWD_TOL = 1e-3`, `GRAD_TOL = 1e-3`, `TRAIN_TOL = 0.02`, `CONTROL_FACTOR = 10.0`, `MAX_GB = 12.0`, `MODELS` (the built-in networks).

## Inputs

No files, unless `--script`. Inputs are seeded normal noise drawn on the CPU (`make_input`) and copied to each device; targets are seeded normal noise of the output's size.

## Outputs

One line per network and `ALL PASS` or `NOT ALL PASS`; with `--json` the record instead, and `--out` writes the same record.

| Field | Type | Meaning |
| --- | --- | --- |
| `environment` | object | torch and Python versions, machine, device, `PYTORCH_ENABLE_MPS_FALLBACK`, CPU threads |
| `ref`, `bar`, `seed`, `mps_memory_fraction` | str, str, int, float or null | the settings |
| `tolerances` | object | the three tolerances and the control factor |
| `models[].checks[]` | list | `check`, `value`, `tol`, `control`, `outcome`; train adds `loss_ref`, `loss_dev`, `loss_max_rel_diff`; with `--bar bf16`, `bar` and `fixed_tol_outcome`; an exception adds `error` |
| `models[].outcome` | str | `PASS`, `FAIL` or `VOID` for the network |
| `models[].bench` | object | `s_per_step` (seconds, median of N steps), `s_per_sample`, `mps_driver_gb` |
| `ops` | object | each data-path operator: `ok` and `rel`, or `error` (null for `--device cpu`) |
| `seconds` | float | wall time |
| `ok` | bool | every network PASS |

| Exit code | Meaning |
| --- | --- |
| `0` | every check of every network passed |
| `1` | a check failed or was VOID (or, for `ops`, an operator failed) |
| `2` | usage error: unknown device, model or shape, or a missing script |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `mps requested but torch.backends.mps.is_available() is False` | not Apple silicon, or a torch without MPS | run with an MPS build of torch on a Mac |
| `requested but this torch sees no CUDA device` | no CUDA card | use `mps` or `cpu` |
| `unknown device 'NAME': use mps, cuda, cuda:N or cpu` | a typo in `--device` or `--ref` | fix the name |
| `unknown model(s) NAME: use conv3d, conv2d, unet3d` | a name not in `MODELS` | `python -m kit.mpsparity list`, or `--script` for your own |
| `--script, --build and --shape go together` | one of the three is missing | give all three |
| `no script at PATH` | `--script` is not a file | fix the path |
| `bad shape 'TEXT': use B,C,D,H,W (at least batch, channels and depth; all positive)` | `--shape` or `--real-shape` is not a comma list of positive ints | fix the shape |
| `no network to check: name --models or give --script, --build and --shape` | `--models` is empty | name a network |
| a check FAIL with `NotImplementedError` in `error` | an operator torch has no MPS kernel for | rerun with `PYTORCH_ENABLE_MPS_FALLBACK=1` (that operator runs on the CPU) and say so |
| bench `error` with `MPS backend out of memory` | the real batch needs more than `--max-gb` | rerun with `--bench-batch` 1 to 4 and read `s_per_sample`; keep `--max-gb` under the Mac's memory |
| `train` FAIL while forward and grad pass | small differences grew through the optimizer | compare `loss_ref` and `loss_dev`; do not loosen the tolerance after a read; `--bar bf16` is the bar for fp32 rounding noise |

## How it works

`pair` seeds torch, builds the network once on the CPU and deep-copies it to each device, so both start from the same weights. Inputs and targets are drawn on the CPU with their own generators and copied, so both devices see the same numbers. Dropout is set to 0 for the gradient and training checks; batch and instance norms run in train mode on both. With `--bar bf16`, each check is run a second time with REF against REF under bf16 autocast, and that difference becomes the tolerance. On MPS `cap_memory` sets torch's per-process memory fraction to `--max-gb` over the recommended maximum, so an oversized bench fails instead of swapping (an uncapped first bench of a real-batch 3D network reached about 28 GB on a 7 Nov 2026 run).

## Cost and time

CPU self check: 3.1 s wall for the three built-in networks at 10 steps; `--bench 3` of `unet3d` at batch 2 of 64 cubed: 0.21 s a step (2026-11-18, 4 logical CPU cloud container, torch 2.15.0+cpu, 4 threads). MPS times depend on the Mac and the network; on an M5 Pro (16 Nov 2026) four small 3D training networks of our own took 0.019 to 2.18 s per sample. It rents nothing.

## For agents

- **Command:** on a Mac, `python -m kit.mpsparity run --device mps --steps 10 --bench 5 --out FILE`; for a script's own network, add `--script PATH --build NAME --shape B,C,D,H,W`.
- **Parse:** `ok`; per network `models[].outcome` and each check's `value` against `tol` and `control`; `bench.s_per_step` for time estimates.
- **Rerun:** safe; it only writes `--out`.
- **Success:** exit 0, `ok` true, every check PASS.
- **Not a pass:** a VOID check; a run with `PYTORCH_ENABLE_MPS_FALLBACK=1` that hides a CPU fallback without saying so; `--device cpu` (that is the self check, not a device check).
- **Go-ahead:** Nothing.
- **Never:** loosen a tolerance or switch bars after seeing a device's result; quote a PASS on the built-in networks for a different network.

## Tests

```bash
python -m unittest tests.test_mpsparity -v
```

16 tests, 1.3 s with torch 2.15.0+cpu (2026-11-18): each check passes on identical devices, fails on a noisy device copy and is VOID when the control cannot fail; the bf16 bar; the built-in networks build and pass on the CPU; a network from a temporary script runs through `--script`, and the usage errors exit 2. They skip without torch and do not touch MPS.

## History

- 2026-11-18: released to public Scrolls with three built-in synthetic networks and `--script`, `--build` and `--shape` for your own (`RELEASE_COMMIT`). Before that it was developed outside this repository from 7 Nov 2026 for four trainers of our own: the fixed tolerances, then the bf16 bar after the M5 Pro read, applied on fresh seeds on 16 Nov.

## Related

- `kit.accel` and `kit.accelbench` ([#359](https://github.com/ChaseHendrick/Scrolls/pull/359)): the device and precision rule, and correctness-gated timing.
- [verify](verify.md): device agreement for real maps, with a control.
