# cloudcost: price a Modal job from dated list rates, offline

`python -m kit.cloudcost` turns GPU type, cores, memory and hours into a low, typical and high USD estimate at Modal's list prices from a dated JSON, and prints the default Modal GPU and CPU request for new jobs; it never contacts Modal.

| Field | Value |
| --- | --- |
| Id | `cloudcost` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Compute and cost |
| Run | `python -m kit.cloudcost`, `from kit import cloudcost` |
| Code | `kit/cloudcost.py` |
| Tests | `tests/test_cloudcost.py`, `tests/test_autobatch.py` |
| Needs | Python 3.10 or newer, standard library only. Reads `docs/compute/modal-rates.json` and `docs/compute/modal-jobs.json` from the checkout |
| Runs on | Any CPU, instantly. The 23 tests of `tests/test_cloudcost.py` and the 11 of `tests/test_autobatch.py` ran together in 0.15 s (measured 2026-10-16, cloud container) |
| Network | None. Rates come from the dated JSON, not from Modal |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed to run it: it prices, it rents nothing. Launching the job it prices needs Chase's yes and an approved budget (the go-ahead rule, hard rule 8, and the Modal rule, hard rule 11) |
| Released | Public `main` since 2026-10-07 |
| Guide | [modal-pricing.md](../compute/modal-pricing.md) (rates, plan limits, the default machine, worked estimates) |
| Checked | 2026-10-16 against commit `e49ec32` |

## What it does

GPU work here runs on [Modal](https://modal.com/), which bills per second for each GPU, each physical CPU core and each GiB of memory, plus storage on Volumes and network egress. Before anyone launches a job, the Modal rule (hard rule 11) asks for a time and cost estimate. `kit.cloudcost` makes that estimate offline: it reads Modal's list prices and limits from [`docs/compute/modal-rates.json`](../compute/modal-rates.json) (with source URLs and an access date, 2026-10-07) and the job assumptions from [`docs/compute/modal-jobs.json`](../compute/modal-jobs.json), and multiplies them out.

It has six actions. `rates` prints the hourly price of every GPU type alone and inside a container. `cost` prices one container shape for some hours. `infer` prices one ink reader over an area of surface at a voxel size, phase by phase (image build, staging the surface volume, GPU inference). `jobs` prices every job in the jobs file. `budget` turns budgets in USD into hours of each GPU. `defaults` prints the default Modal request for new jobs: B300 with fallbacks B200, H200 and H100, and reserved CPU cores (16 for CPU jobs, 8 in a GPU container).

Every multi-level estimate is low, typical and high, because GPU hours for these jobs are assumptions, not measurements. The numbers are list prices on the access date, not quotes and not bills. It does not read Modal's billing, check a budget, or launch anything. The module is also a library: [`batch`](batch.md) prices every scan of the open-data bucket through `container_cost` and `load_rates`.

## When to use it

- Before writing a run spec in `docs/compute/modal-specs/`: price the job, then ask for the go-ahead with the estimate.
- Choosing a GPU: `rates` shows the cost per hour and, for CNN training, per A100-80GB-equivalent hour.
- Writing a Modal app: `modal_gpu()` and `modal_cpu()` give the `gpu=` and `cpu=` values that follow the default-machine decision.
- Asking what a budget buys: `budget 30 100 500`.

Do not use it:

- To record what a job actually cost: use [`modal-row`](modal-row.md), which appends to a Modal cost ledger.
- To log local Mac runs and their electricity: use [`run-local`](run-local.md).
- To price AutoPipeline over every scan of the bucket: use [`batch`](batch.md) (`python -m kit run all --dry-run`), which calls this module per scan.
- As the final word on a price: check [modal.com/pricing](https://modal.com/pricing) before spending, since the JSON is dated.

## Quick start

```bash
python -m kit.cloudcost defaults
python -m kit.cloudcost cost --gpu B300 --hours 1 --cpu 8 --mem 32
python -m kit.cloudcost infer --profile 2p5d_9um --area 40 --um 7.91 --passes 2
```

No placeholders: these run as written from the repository root. `2p5d_9um` is a profile in `docs/compute/modal-jobs.json`; `--area` is in cm2 and `--um` is the surface volume's voxel size.

On 2026-10-16 with the committed rates (accessed 2026-10-07) they printed, in part:

```
{
 "gpu": [
  "B300",
  "B200",
  "H200",
  "H100"
 ],
 ...
 "usd_per_h_one_b300_8_cores_32_gib": 7.7322,
 "usd_per_h_cpu_16_cores_32_gib": 1.0103,
 "estimate_rate": "price a fallback list at its dearest entry (B300)"
}
{"gpu": 7.0992, "cpu": 0.3773, "mem": 0.2557, "total": 7.7322}
image build (CPU, first run only): hours 0.10 / 0.25 / 0.50, USD 0.013 / 0.032 / 0.063
stage 1.8 GB surface volume to a Volume (CPU): hours 0.00 / 0.01 / 0.02, USD 0.002 / 0.003 / 0.008
inference on A10, 2 pass(es): hours 0.08 / 0.14 / 0.36, USD 0.126 / 0.223 / 0.562
total USD low 0.140, typical 0.258, high 0.633
```

It worked when the exit code is 0 and a total is printed. An error ends in a Python traceback and exit code 1.

## Checks and controls

- **Against Modal's own worked examples.** `tests/test_cloudcost.py` reproduces the pricing FAQ: an A10G for 1.5 s with 1 core and 4 GiB costs about 0.000458 USD of GPU, 0.000020 of CPU and 0.000013 of memory, and 256 MiB for one hour 0.00200 USD. A wrong rate or formula fails these tests.
- **Rates are dated and sourced.** The tests require the access date 2026-10-07 and an `https://` source for every rate group. A price older than the job is the main risk: compare the GPU rows of `rates` with [modal.com/pricing](https://modal.com/pricing) before spending.
- **Estimates are not measurements.** GPU seconds per cm2 in each profile carry a `basis` field; some are measured on a Mac, some are taken from tutorials, some are Interpretation. A typical figure is a guess with a range, not a quote.
- **No control in the ink sense.** It makes no claim about ink or scrolls.

Claim label: Interpretation, for every estimate: list prices (Sourced fact, [modal.com/pricing](https://modal.com/pricing), accessed 2026-10-07) times assumed hours.

## Commands and options

The rates file option comes before the action: `python -m kit.cloudcost --rates FILE rates`.

### `python -m kit.cloudcost`

```
usage: python3 -m kit.cloudcost [-h] [--rates RATES]
                                {rates,cost,infer,jobs,budget,defaults} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--rates RATES` | `docs/compute/modal-rates.json` (`RATES`) | Rates JSON to price with, for every action |

### `python -m kit.cloudcost rates`

```
usage: python3 -m kit.cloudcost rates [-h] [--cpu CPU] [--mem MEM]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--cpu CPU` | `4` | Physical cores added to each GPU in the container column |
| `--mem MEM` | `32` | GiB of memory added in the container column |

### `python -m kit.cloudcost cost`

```
usage: python3 -m kit.cloudcost cost [-h] [--gpu GPU] [--gpus GPUS]
                                     [--containers CONTAINERS] --hours HOURS
                                     [--cpu CPU] [--mem MEM]
                                     [--region {none,broad,narrow}]
                                     [--nonpreemptible]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--gpu GPU` | none | GPU type, a key of `gpu_usd_per_s` such as `B300`, `H100`, `A10`, `L4`; none prices a CPU-only container |
| `--gpus GPUS` | `1` | GPUs per container; refused above the type's `max_gpus_per_container` (8 for most, 4 for A10) |
| `--containers CONTAINERS` | `1` | Identical containers running at once |
| `--hours HOURS` | required | Wall hours each container runs |
| `--cpu CPU` | `4` | Physical cores per container (each 2 vCPU); raised to Modal's minimum of 0.125 |
| `--mem MEM` | `32` | GiB of memory per container; raised to the minimum of 0.125 |
| `--region {none,broad,narrow}` | `none` | Region pinning multiplier: 1.0, 1.15 or 1.75 on everything. Never pin a region here (the Modal rule) |
| `--nonpreemptible` | off | Triple CPU and memory prices; refused with `--gpu`. Never used here (the Modal rule) |

### `python -m kit.cloudcost infer`

```
usage: python3 -m kit.cloudcost infer [-h] --profile PROFILE --area AREA
                                      --um UM [--passes PASSES] [--jobs JOBS]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--profile PROFILE` | required | A key of `inference_profiles` in the jobs JSON: `2p5d_9um`, `2p5d_2um`, `3d_l2` or `3d_2um` in the committed file |
| `--area AREA` | required | Surface area to read, in cm2 |
| `--um UM` | required | Voxel size of the surface volume, in um |
| `--passes PASSES` | `1` | Inference passes, such as 2 for forward plus reversed depth (the control) |
| `--jobs JOBS` | `docs/compute/modal-jobs.json` (`JOBS`) | Jobs JSON that holds the profiles |

### `python -m kit.cloudcost jobs`

```
usage: python3 -m kit.cloudcost jobs [-h] [--json] [file]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `file` | `docs/compute/modal-jobs.json` (`JOBS`) | Jobs JSON to price |
| `--json` | off | Print a JSON list of estimates (fields under Outputs) instead of the Markdown table |

### `python -m kit.cloudcost budget`

```
usage: python3 -m kit.cloudcost budget [-h] [--cpu CPU] [--mem MEM]
                                       budgets [budgets ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `budgets` | required | One or more budgets in USD |
| `--cpu CPU` | `4` | Physical cores per GPU container for the "h container" figure |
| `--mem MEM` | `32` | GiB per GPU container for the "h container" figure |

### `python -m kit.cloudcost defaults`

```
usage: python3 -m kit.cloudcost defaults [-h]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-h` | off | Help only; the action takes no options. It prices the B300 container at 8 cores and 32 GiB and the CPU container at 16 cores and 32 GiB |

## Python API

```python
from kit import cloudcost
rates = cloudcost.load_rates()
print(cloudcost.container_cost(rates, 2.0, gpu="H100", cpu=8, mem_gib=32)["total"])
gpu = cloudcost.modal_gpu()          # ["B300", "B200", "H200", "H100"] for modal.App.function(gpu=...)
cpu = cloudcost.modal_cpu()          # (16.0, 16.0)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `load(path)` | The parsed JSON document | `OSError` for a missing file, `json.JSONDecodeError` for bad JSON | Shared reader |
| `load_rates(path=None)` | The rates dict | As `load` | Default `RATES`, `docs/compute/modal-rates.json` |
| `load_jobs(path=None)` | The jobs dict (`inference_profiles`, `jobs`) | As `load` | Default `JOBS`, `docs/compute/modal-jobs.json` |
| `modal_gpu(count=1, fallback=True, cuda13=True)` | A list such as `["B300", "B200", "H200", "H100"]` (`"B300:2"` and so on when `count` is above 1), or the string `"B300"` with `fallback=False` | `ValueError` for `count` outside 1 to 8, or `fallback=False` with `cuda13=False` | The `gpu=` value for a new Modal Function. `cuda13=False` (an image built for CUDA 12) drops B300 and starts at B200 |
| `modal_cpu(cores=MODAL_CPU_CORES)` | `(float(cores), float(cores))`, `(16.0, 16.0)` by default | `ValueError` below 0.125 cores | The `cpu=` value: cores reserved, request equal to limit |
| `gpu_per_hour(rates, gpu)` | USD per hour for the GPU alone | `ValueError` for an unknown GPU, naming the known ones | |
| `container_cost(rates, hours, gpu=None, gpus=1, cpu=0.125, mem_gib=0.125, containers=1, region='none', nonpreemptible=False)` | `{"gpu", "cpu", "mem", "total"}` in USD, unrounded | `ValueError` for a negative input, `nonpreemptible` with a GPU, or too many GPUs per container; `KeyError` for an unknown GPU or region | USD for `containers` identical containers running `hours` each, with the per-container minimums applied |
| `volume_cost(rates, gib, months=1.0, free_gib=None)` | USD | Nothing of its own | Only GiB above the free allowance (`volume_free_gib`, 1024) are billed |
| `egress_cost(rates, gib, plan='starter', already_used_gib=0.0)` | USD | `KeyError` for an unknown plan | Only GiB beyond the plan's free egress (1024 on Starter) are billed |
| `surface_volume_gb(area_cm2, um, layers, bytes_per_voxel=1)` | GB (1e9 bytes), uncompressed | `ZeroDivisionError` when `um` is 0 | Uncompressed size of a flattened surface volume: area x (1 cm / voxel)^2 x layers |
| `inference_phases(profile, area_cm2, um, passes=1)` | `(phases, gb)`: three phase dicts and the surface volume's size | `KeyError` for a profile without `ref_um`, `gpu_s_per_cm2`, `layers` or `gpu`; `ValueError` for a range that is not three numbers | Phases (image build, staging on CPU, GPU inference) for one reader over `area_cm2` |
| `expand(job, profiles)` | A copy of the job with explicit `phases` (and `volume_gib` set from the surface volume) | `KeyError` for an unknown profile | An `inference` block is expanded through its profile |
| `estimate(rates, job, profiles=None, region='none', plan='starter')` | The estimate dict under Outputs | As `container_cost` and `expand` | Low, typical and high USD for a job, with a per-phase breakdown |
| `budget_hours(rates, budget, gpu, gpus=1, cpu=4, mem_gib=32)` | Wall hours | As `container_cost` | Hours of one container that `budget` USD buys |
| `work_cost(rates, gpu, cpu=4, mem_gib=32)` | USD per A100-80GB-equivalent hour, or `None` when the GPU has no speed figure | As `container_cost` | For CNN training only; speeds are not measured on ink models |
| `rates_table(rates, cpu=4, mem_gib=32)` | Markdown text | Nothing of its own | What `rates` prints |
| `jobs_table(rates, jobs_doc, region='none', plan='starter')` | Markdown text | As `estimate` | What `jobs` prints |
| `budget_table(rates, budgets, gpus=None, cpu=4, mem_gib=32)` | Markdown text | `ValueError` for an unknown GPU in `gpus` | What `budget` prints; every GPU when `gpus` is None |
| `build_parser()` | The `argparse.ArgumentParser` | Nothing | |
| `main(argv=None)` | `0` | Whatever the action raises, uncaught; `SystemExit` 2 for a usage error | The command line |

Constants: `MODAL_GPU = "B300"`, `MODAL_GPU_FALLBACK = ("B300", "B200", "H200", "H100")`, `MODAL_CPU_CORES = 16`, `MODAL_GPU_CPU_CORES = 8`, `LEVELS = ("low", "typical", "high")`.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Rates | JSON, default `docs/compute/modal-rates.json` | Fields read: `accessed`, `gpu_source`, `gpu_usd_per_s` (USD per GPU-second by type), `max_gpus_per_container`, `cpu_usd_per_core_s`, `mem_usd_per_gib_s`, `min_cpu_cores`, `min_mem_gib`, `region_multiplier`, `nonpreemptible_cpu_mem_multiplier`, `volume_usd_per_gib_month`, `volume_free_gib`, `egress_usd_per_gib`, `egress_free_gib` (by plan), `speed_vs_a100_80gb`. Each group names its source URL |
| Jobs | JSON, default `docs/compute/modal-jobs.json` | `inference_profiles`: per profile `gpu`, `ref_um`, `scale_power` (2 for 2.5D, 3 for native 3D), `layers`, `gpu_s_per_cm2` (low, typical, high at `ref_um`), `basis`, and optional `bytes_per_voxel` (1), `stage_mb_per_s` (100, 50, 20), `image_build_h` (0.1, 0.25, 0.5), `cpu` (4), `mem_gib` (32), `startup_h` (0.05). `jobs`: each with `id`, `name`, and `phases` (`name`, `gpu`, `gpus`, `containers`, `cpu`, `mem_gib`, `hours` as one number or three) or an `inference` block (`profile`, `area_cm2`, `um`, `passes`), plus optional `volume_gib`, `volume_months`, `egress_gib` |
| Command values | Numbers | Hours are wall hours; CPU is physical cores (2 vCPU each); memory is GiB; area is cm2; voxel size is um |

## Outputs

Text or JSON on stdout; it writes no file.

| Action | Prints |
| --- | --- |
| `rates` | A Markdown table, one row per GPU: USD/s, USD/h GPU only, USD/h container (with `--cpu` and `--mem`), USD per A100-80GB-equivalent hour (`n/a` without a speed figure), then CPU and memory hourly rates |
| `cost` | One JSON line: `gpu`, `cpu`, `mem`, `total`, in USD, rounded to 4 decimals |
| `infer` | One line per phase with hours and USD (low / typical / high), then `total USD low ..., typical ..., high ...` |
| `jobs` | A Markdown table: job, GPU hours (low / typical / high), USD low, typical, high; with `--json` the list below |
| `budget` | A Markdown table, one row per GPU: hours of the GPU alone and of a container, per budget |
| `defaults` | The JSON object below |

`jobs --json`, one object per job (the return value of `estimate`):

| Field | Type | Meaning |
| --- | --- | --- |
| `id`, `name` | str | From the jobs file |
| `phases[].name`, `.gpu`, `.gpus`, `.containers` | str, str or null, int, int | The phase and its machine |
| `phases[].hours` | [float, float, float] | Low, typical, high wall hours |
| `phases[].usd` | [float, float, float] | Low, typical, high USD, unrounded |
| `gpu_hours.low`, `.typical`, `.high` | float | GPU hours over all phases (hours x GPUs x containers) |
| `usd.low`, `.typical`, `.high` | float | Total USD, with Volume storage above the free 1 TiB and egress above the free allowance |
| `volume_gib` | [float, float, float] | Volume size assumed |

`defaults`:

| Field | Type | Meaning |
| --- | --- | --- |
| `gpu` | list of str | `modal_gpu()`: `["B300", "B200", "H200", "H100"]` |
| `gpu_container_cpu` | [float, float] | `modal_cpu(8)`: cores for a GPU container |
| `cpu` | [float, float] | `modal_cpu()`: 16 cores for a CPU job |
| `usd_per_h_one_b300_8_cores_32_gib` | float | USD per hour of one B300 container with 8 cores and 32 GiB |
| `usd_per_h_cpu_16_cores_32_gib` | float | USD per hour of a 16-core, 32 GiB CPU container |
| `estimate_rate` | str | How to price a fallback list: at its dearest entry, B300 |

| Exit code | Meaning |
| --- | --- |
| `0` | Printed |
| `1` | An error the module does not catch, with a Python traceback: a `ValueError`, `KeyError` or `FileNotFoundError` (see Failure modes) |
| `2` | A usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as `cost` without `--hours` | Check the command against Commands and options |
| `ValueError: negative input`, traceback, exit code 1 | A negative `--hours`, `--containers`, `--gpus`, `--cpu` or `--mem` | Use zero or more |
| `ValueError: Modal does not support nonpreemptible GPU Functions` | `cost --gpu ... --nonpreemptible` | Drop `--nonpreemptible`; GPU work is always preemptible and needs checkpoints |
| `ValueError: NAME allows at most LIMIT GPUs per container` | `--gpus` above the type's `max_gpus_per_container` | Use fewer GPUs per container, or more containers |
| `KeyError: 'NAME'`, traceback, from `cost` | A `--gpu` that is not in the rates file (the friendly `unknown GPU` message is not used on this path) | Use a name from `python -m kit.cloudcost rates` |
| `ValueError: unknown GPU 'NAME'; known: ...` | `gpu_per_hour` or `budget_table` asked for a GPU not in the rates file (library calls) | Use a known name |
| `KeyError: 'PROFILE'`, traceback, from `infer` | `--profile` not in the jobs file | Use `2p5d_9um`, `2p5d_2um`, `3d_l2` or `3d_2um`, or add the profile |
| `ValueError: expected [low, typical, high], got ...` | A range in the jobs file (`hours`, `gpu_s_per_cm2`, `volume_gib`, `egress_gib`, `stage_mb_per_s`, `image_build_h`) that is a list of other than three numbers | Give one number or exactly three |
| `FileNotFoundError: ...`, traceback | `--rates`, `--jobs` or the jobs `file` does not exist, or the module is run outside a full checkout | Fix the path; run from the repository root |
| `ValueError: Modal allows 1 to 8 of these GPUs per container` | `modal_gpu(count)` with `count` outside 1 to 8 (library call) | Use 1 to 8 |
| `ValueError: B300 needs a CUDA 13.1 or newer image` | `modal_gpu(fallback=False, cuda13=False)`: a lone B300 for a CUDA 12 image (library call) | Rebuild the image for CUDA 13, or use `modal_gpu(cuda13=False)` |
| `ValueError: Modal's minimum is 0.125 cores` | `modal_cpu(cores)` below 0.125 (library call) | Ask for at least 0.125 cores |

## How it works

1. **One container** (`container_cost`). Seconds billed are `hours x 3600 x containers`. GPU USD is `gpu_usd_per_s[gpu] x gpus x seconds`. CPU USD is `max(cpu, min_cpu_cores) x cpu_usd_per_core_s x seconds`, memory USD is `max(mem_gib, min_mem_gib) x mem_usd_per_gib_s x seconds`; with `nonpreemptible` both are multiplied by `nonpreemptible_cpu_mem_multiplier` (3.0). Everything is multiplied by `region_multiplier[region]` (`none` 1.0, `broad` 1.15, `narrow` 1.75). The committed rates: B300 0.001972 USD/s (7.0992 USD/h), H100 0.001097 (3.9492 USD/h), L4 0.000222 (0.7992 USD/h); CPU 1.31e-05 USD per core-second (0.04716 per core-hour); memory 2.22e-06 USD per GiB-second; minimums 0.125 cores and 0.125 GiB.
2. **Storage and egress.** `volume_cost` bills GiB above `volume_free_gib` (1024) at `volume_usd_per_gib_month` (0.09) per month. `egress_cost` bills GiB beyond the plan's free egress (Starter 1024) at `egress_usd_per_gib` (0.04).
3. **One reader over an area** (`inference_phases`). With `p = scale_power`, GPU seconds are `gpu_s_per_cm2 x (ref_um / um)^p x area x passes` for each of low, typical and high: p = 2 for a 2.5D reader (fixed layer count, so time follows pixel count), p = 3 for a native 3D reader (fixed physical thickness, so the layer count also grows). The surface volume is `area x (1e4 / um)^2 x layers x bytes_per_voxel / 1e9` GB, and staging takes that size over 100, 50 or 20 MB/s (an upper bound for compressed data). Three phases follow: image build (2 cores, 4 GiB), staging (4 cores, 16 GiB), inference on the profile's GPU with `startup_h` (0.05 h) added.
4. **A job** (`estimate`). Each phase is priced at its low, typical and high hours and summed, then Volume storage and egress are added. GPU hours count `hours x gpus x containers` for phases with a GPU.
5. **Budgets and work** (`budget_hours`, `work_cost`). A budget divided by one container's hourly cost gives hours. Work cost divides the hourly cost by `speed_vs_a100_80gb[gpu].value`, a relative CNN training throughput (A100 80GB = 1.0), which is not measured on ink models.
6. **Defaults** (`modal_gpu`, `modal_cpu`). Modal tries a list of GPUs in order ([GPU guide](https://modal.com/docs/guide/gpu)), so `modal_gpu()` returns `MODAL_GPU_FALLBACK`. B300 runs only images built for CUDA 13.1 or newer, so `cuda13=False` drops it. Modal offers no choice of CPU model, so the faster CPU request is more reserved physical cores, request equal to limit. The decision behind these is Chase's of 12 October 2026, in [modal-pricing.md](../compute/modal-pricing.md#default-gpu-and-cpu-for-new-jobs).

## Cost and time

Not measured beyond the test run above (34 tests of this module and `batch` in 0.15 s, 2026-10-16, cloud container); every action is arithmetic on two small JSON files. It runs anywhere and rents nothing. The estimates it prints are for jobs that run on Modal under the Modal rule (hard rule 11), at the Starter plan's limits: at most 10 GPUs and 100 containers at once ([plan limits](../compute/modal-pricing.md#2-plans-credits-limits-and-budgets)).

## For agents

- **Command:** `python -m kit.cloudcost cost --gpu B300 --hours HOURS --cpu 8 --mem 32` (one JSON line); `python -m kit.cloudcost jobs --json` for every job; `python -m kit.cloudcost defaults` for the default request. In Python, `cloudcost.estimate(cloudcost.load_rates(), job, profiles)`.
- **Parse:** `total` from `cost`; `usd.low`, `usd.typical`, `usd.high` and `gpu_hours` per job from `jobs --json`; `gpu` and `cpu` from `defaults`.
- **Rerun:** Safe; it reads two JSON files and writes nothing.
- **Success:** Exit code 0 and a number printed. Exit code 1 with a traceback is an input error.
- **Not a pass:** A typical figure quoted as the cost (it is an assumption with a low and high); a price from rates older than the job without a check against [modal.com/pricing](https://modal.com/pricing); a GPU-only price for a job that also pays for cores and memory; a `--region` other than `none` or `--nonpreemptible` in a real plan.
- **Go-ahead:** Nothing to run it. The job it prices needs Chase's yes and budget, with the estimate, before launch; Claude cloud sessions never launch Modal themselves (the Modal rule, hard rule 11).
- **Never:** Present an estimate as a bill or a quote; launch or sign in to Modal from a Claude cloud session; price a target-scroll job in a public file (those specs live privately).

## Tests

```bash
python -m unittest tests.test_cloudcost tests.test_autobatch -v
```

`tests/test_cloudcost.py` covers the rates file (dated, sourced, every GPU with a container limit and a speed entry, rates ordered by price, the published hourly rates), Modal's FAQ examples, minimums, linear scaling in containers and GPUs, region and nonpreemptible multipliers, GPU count limits, Volume and egress allowances, every job estimating low under typical under high, inference scaling with voxel size, surface volume size, budget hours, cost per unit of work, every command line action, and the defaults (B300 first, cheaper fallbacks, request equal to limit). `tests/test_autobatch.py` uses `load_rates` to price scans. They do not check the rates against Modal's live page. The file's `if __name__ == "__main__"` block sits above `ModalDefaultsTest`; run it through `python -m unittest` as above.

## History

- 2026-10-12: `defaults`, `modal_gpu` and `modal_cpu`: new jobs default to B300 with fallbacks and 16 reserved CPU cores (`e0ff3a3`).
- 2026-10-07: a nested-quote f-string that broke Python 3.10 and 3.11 fixed (`2005db9`).
- 2026-10-07: first version, with the dated rates and jobs files and the pricing guide (`f9abfc1`).

## Related

- [modal-pricing.md](../compute/modal-pricing.md): the guide, with the rates, the Starter plan's limits, the default machine and the job estimates this module prints.
- [`modal-rates.json`](../compute/modal-rates.json) and [`modal-jobs.json`](../compute/modal-jobs.json): the inputs.
- [`modal-specs/`](../compute/modal-specs/README.md): where a priced public job's run spec goes.
- [`batch`](batch.md): prices AutoPipeline over every scan with this module.
- [`modal-row`](modal-row.md): records what a Modal job actually cost.
- [`run-local`](run-local.md): local run time and electricity cost.
- [`compute`](compute.md): machine time per run from provenance records.
