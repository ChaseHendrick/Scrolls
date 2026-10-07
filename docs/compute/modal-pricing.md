# Modal pricing and a cost calculator for scroll compute

Checked 2026-10-07. Every figure below was read on that date from the linked page. Prices change: re-check [modal.com/pricing](https://modal.com/pricing) before spending. Labels follow [`../NOVELTY.md`](../NOVELTY.md): **Sourced fact** (a published figure), **Community report**, **Interpretation** (our arithmetic or reading of sources), **Assumption** (not verified; used only to size estimates).

Files: run ledger template [`modal-ledger.csv`](modal-ledger.csv); rates and limits with source URLs in [`modal-rates.json`](modal-rates.json); job assumptions in [`modal-jobs.json`](modal-jobs.json); calculator [`kit/cloudcost.py`](../../kit/cloudcost.py) (standard library, no network). Nothing in this document was run on Modal; all job costs are estimates.

```
python3 -m kit.cloudcost rates                 # hourly rates, container cost, cost per unit of work
python3 -m kit.cloudcost jobs                  # every job below, low / typical / high
python3 -m kit.cloudcost infer --profile 2p5d_2um --area 25 --um 2.4 --passes 2
python3 -m kit.cloudcost cost --gpu H100 --gpus 1 --containers 4 --hours 0.5 --cpu 4 --mem 32
python3 -m kit.cloudcost budget 30 100 500
```

## Summary

- **GPU prices** (Sourced fact, [pricing](https://modal.com/pricing)): per second, from 0.000164 USD/s for a T4 (0.59 USD/h) to 0.001972 USD/s for a B300 (7.10 USD/h). H100 is 3.95 USD/h, A100 80 GB 2.50, L40S 1.95, A10 1.10, L4 0.80.
- **CPU and memory are billed on top of the GPU** (Sourced fact, same page): 0.0000131 USD per physical core per second and 0.00000222 USD per GiB per second. A GPU container with 4 cores and 32 GiB adds 0.44 USD/h: 11 % on an H100, 40 % on an A10 (Interpretation). A published A10 run paid about 7 USD of GPU and 6.5 USD of CPU, memory and image builds ([bnleft](https://github.com/bnleft/first-light-pherc0211)).
- **For compute-bound training the H100 is the cheapest per unit of work** on Modal: about 2.62 USD per A100-80GB-equivalent hour against 2.94 (A100 80 GB), 3.28 (L40S) and 3.96 (A10), using CNN training throughput ratios (Interpretation from Lambda and MLPerf benchmarks, below). For I/O-bound inference a cheaper card usually wins, because the GPU waits on data.
- **Typical job costs** (Interpretation from the assumptions in `modal-jobs.json`): a 2.5D 9 um-class reader over 100 cm2 at 7.91 um, both depth directions, about 0.50 USD; a 2.4 um 2.5D reader over 100 cm2, about 5.70 USD; fine-tuning a 9 um reader as 4 parallel H100 variants, about 9 USD (5 to 16); a 3D model from scratch with self-training, about 107 USD (67 to 161); a spiral-fit run, about 5 USD (2.40 to 10).
- **Budget cap**: set a Workspace budget (hard usage cap) and a spend limit on the Usage & Billing page before the first GPU run (Sourced fact, [budgets](https://modal.com/docs/guide/budgets)).

## 1. Modal rates

Modal list prices, accessed 2026-10-07 (https://modal.com/pricing).
Container column adds 4 cores and 32 GiB memory.

| GPU | USD/s | USD/h GPU only | USD/h container | USD per A100-80GB-equivalent hour |
| --- | ---: | ---: | ---: | ---: |
| B300 | 0.001972 | 7.0992 | 7.5436 | n/a |
| B200 | 0.001736 | 6.2496 | 6.6940 | n/a |
| H200 | 0.001261 | 4.5396 | 4.9840 | n/a |
| H100 | 0.001097 | 3.9492 | 4.3936 | 2.62 |
| RTX-PRO-6000 | 0.000842 | 3.0312 | 3.4756 | n/a |
| A100-80GB | 0.000694 | 2.4984 | 2.9428 | 2.94 |
| A100-40GB | 0.000583 | 2.0988 | 2.5432 | 2.92 |
| L40S | 0.000542 | 1.9512 | 2.3956 | 3.28 |
| A10 | 0.000306 | 1.1016 | 1.5460 | 3.96 |
| L4 | 0.000222 | 0.7992 | 1.2436 | n/a |
| T4 | 0.000164 | 0.5904 | 1.0348 | n/a |

CPU 0.04716 USD per core-hour; memory 0.007992 USD per GiB-hour.

The last column divides the container hourly cost by the CNN training speed relative to an A100 80 GB (section 4). It is blank where no comparable benchmark was found.

| Item | Rate or rule | Source |
| --- | --- | --- |
| Billing granularity | Per second, no minimum usage-time increments | [billing](https://modal.com/docs/guide/billing) |
| What is billed | Application load time, time processing inputs, and the idle window before scale-down (default 60 s) | [pricing FAQ](https://modal.com/pricing) |
| Idle window | `scaledown_window` from 2 s to 20 min; idle time is billed | [cold start](https://modal.com/docs/guide/cold-start) |
| CPU and memory metering | Higher of requested and used; minimum 0.125 cores and 128 MiB per container; 1 core = 2 vCPU | [pricing FAQ](https://modal.com/pricing) |
| Sandboxes and Notebooks | 0.00003942 USD per core-second and 0.00000667 USD per GiB-second, about 3x Function rates | [pricing](https://modal.com/pricing) |
| Volumes | 0.09 USD per GiB-month, 1 TiB per month included; usage snapshotted daily; deleted data may bill for up to 4 days | [pricing](https://modal.com/pricing), [volumes](https://modal.com/docs/guide/volumes) |
| Network egress | 0.04 USD per GiB beyond 1 TiB (Starter), 10 TiB (Team), 100 TiB (Enterprise) per cycle; charged from 2026-10-01; Volume reads and writes and downloads into a container (ingress) do not count | [egress](https://modal.com/docs/guide/network-egress-billing) |
| Region selection | 1.15x (broad, e.g. `us`) or 1.75x (narrow, e.g. `us-west`) on all resources; no multiplier if `region` is unset | [regions](https://modal.com/docs/guide/region-selection) |
| Non-preemptible | 3x CPU and memory price; not supported for GPU Functions | [preemption](https://modal.com/docs/guide/preemption) |
| Timeouts | Default 300 s per execution, settable from 1 s to 24 h; retries restart the timeout | [timeouts](https://modal.com/docs/guide/timeouts) |
| Automatic upgrades | `H100` may run on an H200 and `A100` (40 GB) on an 80 GB card at the requested price; `H100!` pins the H100 | [GPU guide](https://modal.com/docs/guide/gpu) |
| Payment method | Required to use Modal and to use GPUs | [GPU guide](https://modal.com/docs/guide/gpu), [billing](https://modal.com/docs/guide/billing) |

Pricing FAQ consistency check (Interpretation): the A10G example (1.5 s, 1 core, 4 GiB) reproduces with the listed rates (0.000459, 0.000020 and 0.000013 USD); the CPU example (0.5 core for 1 h) quotes 0.02365 USD where the listed rate gives 0.02358, a 0.3 % difference.

## 2. Plans, credits, limits and budgets

| | Starter | Team | Enterprise |
| --- | --- | --- | --- |
| Monthly fee | 0 USD | 250 USD | custom |
| Included compute per month | 30 USD | 100 USD | custom |
| Included egress | 1 TiB | 10 TiB | 100 TiB |
| Seats | up to 3 | unlimited | unlimited |
| Containers | 100 | 5,000 | custom |
| GPU concurrency | 10 | 50 | custom |
| Log retention | 1 day | 30 days | custom |
| Environment-level budgets | no | yes | yes |

Sourced fact: [pricing](https://modal.com/pricing). Included compute covers Functions, Sandboxes and Notebooks (CPU, memory, GPU), not per-token Shared Endpoints. Usage is pay as you go; no credit purchase is needed.

- **Credit programs** (Sourced fact): academics (graduate students, labs, researchers) can get up to 10,000 USD of credits ([pricing](https://modal.com/pricing), [academics](https://modal.com/academics)); startups need VC funding from a partner fund or more than 1 million USD raised, one-time grant ([startups](https://modal.com/startups)). AWS, GCP and Azure credits cannot be used ([pricing FAQ](https://modal.com/pricing)).
- **GPUs per container** (Sourced fact, [GPU guide](https://modal.com/docs/guide/gpu)): up to 8 for B300, B200, H200, H100, A100, L4, T4 and L40S; up to 4 for A10. More than 2 per container usually means longer waits. Multi-node training is private beta. Plan concurrency caps the total across containers (10 GPUs on Starter).
- **Budgets and spend limits** (Sourced fact, [budgets](https://modal.com/docs/guide/budgets)): a Workspace budget is a hard monthly cap on usage (before credits), set on the Usage & Billing page. A separate spend limit caps net out-of-pocket charges after credits; by default it is the usage limit minus credits, and when it is reached Modal stops workloads that would add out-of-pocket charges. Environment budgets need Team or Enterprise. The maximum budget depends on prior successful charges. Programmatic billing report export (API or `modal billing` CLI, by app and tag, before credits) is offered at the Team and Enterprise levels ([billing](https://modal.com/docs/guide/billing)); `modal billing summary` shows spend including egress ([egress](https://modal.com/docs/guide/network-egress-billing)).

## 3. Practical cost factors

- **Container CPU and memory.** Request what the data loader needs and no more; billing is on the higher of requested and used (Sourced fact). On cheap GPUs this overhead is a large share (40 % on an A10 at 4 cores and 32 GiB; Interpretation).
- **Image builds.** Builds run as containers on Modal's builder; a build step can attach a GPU (`gpu=` on a build step), and `run_function` is "equivalent to running a Modal Function" ([images](https://modal.com/docs/guide/images)). Whether CPU-only build time is billed at Function rates is not stated on the pages read (unverified). Layers are cached; put frequently changed layers last so rebuilds stay small (Sourced fact, same page). A published run spent about 25 min of CPU on three image builds that compiled tools from source ([bnleft](https://github.com/bnleft/first-light-pherc0211)).
- **Never download with a GPU attached.** Downloads into a container are free ingress but the container is billed while it waits. Stage data on a CPU-only Function into a Volume, then mount the Volume on the GPU Function (Interpretation from [egress](https://modal.com/docs/guide/network-egress-billing) and [volumes](https://modal.com/docs/guide/volumes)). Volumes target up to 2.5 GB/s and work best under 50,000 files (Volumes v1 hard limit 500,000 inodes); zarr stores with many small chunks fit Volumes v2 (beta) better (Sourced fact, [volumes](https://modal.com/docs/guide/volumes)). A published run measured 16 GiB fetched in about 12 min on a Modal CPU container, about 23 MB/s, and found mirroring zarr stores into a network volume "hours-slow" ([bnleft](https://github.com/bnleft/first-light-pherc0211)).
- **Preemption and checkpoints.** All Functions are preemptible by default; on preemption Modal restarts the input. GPU Functions cannot be made non-preemptible, so long training must checkpoint to a Volume and resume (Sourced fact, [preemption](https://modal.com/docs/guide/preemption), [volumes](https://modal.com/docs/guide/volumes)). There is no separate cheaper spot tier: the listed GPU price is the preemptible price (Interpretation; no spot tier appears on the pricing page).
- **Memory snapshots.** CPU memory snapshots (and alpha GPU snapshots) cut cold starts, "often 3-10x faster" for initialization-heavy Functions, but only for deployed apps and not for weight loading bound by storage (Sourced fact, [memory snapshots](https://modal.com/docs/guide/memory-snapshot)). For a few long batch jobs the saving is seconds to minutes per container (Interpretation).
- **Timeouts and idle.** Set `timeout=` per Function to the expected time plus a margin, so a hung job stops itself; keep `scaledown_window` short for batch work (Sourced fact, [timeouts](https://modal.com/docs/guide/timeouts), [cold start](https://modal.com/docs/guide/cold-start)).
- **Blackwell software.** Hopper GPUs have better library support than Blackwell; B300 needs CUDA 13.1 or newer; `B200+` may run on a B300 and is billed as B200 (Sourced fact, [GPU guide](https://modal.com/docs/guide/gpu)).

## 4. Throughput for estimates

| Ratio | Value | Source and label |
| --- | --- | --- |
| H100 SXM vs A100 80 GB SXM, CNN training fp16 | 1.71 (SSD), 1.65 (ResNet-50) | Lambda benchmark CSV, Sourced fact ([fp16 CSV](https://github.com/lambdal/deeplearning-benchmark/blob/master/pytorch/pytorch-train-throughput-fp16.csv)) |
| H100 vs A100, MLPerf Training 3D U-Net (KiTS19), 8 GPUs | 1.45 (7.6 vs 11.0 min, Dell) | MLPerf summary, Sourced fact ([Silverton](https://silvertonconsulting.com/2023/07/12/mlperf-results-show-h100-v-a100-and-v-habana-gaudi2-gpus/)) |
| A100 40 GB PCIe vs A100 80 GB SXM | 0.86 to 0.88 | Lambda fp16 CSV; Modal does not state the 40 GB form factor |
| L40S vs A100 80 GB | 0.72 to 0.74 | Proxy: RTX 6000 Ada (same AD102 chip family) in the Lambda CSV; Interpretation |
| A10 vs A100 80 GB | 0.38 to 0.40 | Lambda fp16 CSV (LambdaCloud A10) |
| H200, B200, B300, RTX PRO 6000, L4, T4 | no comparable training benchmark found | unverified; L4 has 300 GB/s memory bandwidth ([NVIDIA](https://www.nvidia.com/en-us/data-center/l4/)), so memory-bound 3D CNNs are likely slow on it (Interpretation) |

Official Vesuvius pipeline timings ([ink tutorial, updated 2026-09-06](https://scrollprize.org/tutorial5)), all Sourced fact:

- 2.5D training, 20,000 iterations, batch 2, patch 64 x 256 x 256, fp16: about 1.5 h on one H100.
- Full 9 um cross-scroll recipe, 78,125 iterations: about 5 h on one H100.
- Native 3D training (`full_3d_single_wrap`, level 2), 20,000 iterations at batch 8: about 10 h on one H100.
- 2.5D inference on a full segment: on the order of an hour on a single GPU.
- Native 3D inference at level 2: about 78,000 patches and about 2.5 h on an H100 for the tutorial segment; full resolution plans hundreds of thousands of patches.
- Rendering a 9 um segment surface volume (28 slices, 5820 x 5240): about 5 min, about 900 MB.

Apple M1 Pro (MPS) reference:

- Measured in this repository ([`../mac.md`](../mac.md)): public `ink_9um`, both seeds, both directions over w045 in 649 to 679 s per seed; w045's map is 40.0 cm2 ([log](../logs/2026-10-07-novel-checks.md)), so about 8 s per cm2 per pass (Interpretation).
- Community report: on a VGG16 CIFAR-10 (224 px) benchmark, one training epoch took about 42 min on an M1 Pro GPU against about 9 min on an RTX 3060, and the M1 Pro GPU was 3.5x faster than the M1 Pro CPU ([Raschka, PyTorch on M1](https://sebastianraschka.com/blog/2022/pytorch-m1-gpu.html); the per-epoch figures are in the post's results chart). A data-center GPU is therefore likely 10x or more faster than an M1 Pro for CNN training (Interpretation, unverified on ink models).

Data volume (Interpretation, arithmetic): a flattened surface volume holds (1 cm / voxel)^2 x layers voxels per cm2. Uncompressed uint8: about 1.13 GB per cm2 at 2.4 um with 65 layers; 0.045 GB per cm2 at 7.91 um with 28 layers. A 2.4 um volume has 10.9x the pixels of a 7.91 um one per cm2. The tutorial's training segment downloads as about 25 GB, compressed (Sourced fact, tutorial).

## 5. Cost models for typical jobs

Assumptions (all in [`modal-jobs.json`](modal-jobs.json), each with its basis): GPU containers request 4 cores and 32 GiB (8 cores and 64 GiB for 2 GPUs); data is staged on a CPU container at 100 / 50 / 20 MB/s (low / typical / high cost; the low end of the published 23 MB/s measurement sets the high case); a first-run image build of 0.1 to 0.5 CPU hours; Volume storage stays under the free 1 TiB; egress stays under the free allowance (outputs are small maps). Inference GPU time per cm2 scales with voxel count. No region, so no multiplier.

Inference profiles (Assumption, each anchored as stated):

| Profile | GPU | Reference GPU seconds per cm2 per pass (low / typical / high) | Anchor |
| --- | --- | --- | --- |
| `2p5d_9um`: 2.5D reader at about 9 um (public `ink_9um`, Hecate 9.6 um) | A10 | 1 / 3 / 10 at 9.4 um | M1 Pro measured about 8 s per cm2 |
| `2p5d_2um`: 2.5D reader at 2.4 um (organiser 2 um canonical model, PHerc. 1667 iteration models, Hecate 2.4 um) | L40S | 20 / 40 / 120 at 2.4 um | tutorial: about 1 GPU hour per full segment; tutorial segment canvas 51,960 x 31,960 px = 95.6 cm2 at 2.4 um (header of its public prediction TIFF) |
| `3d_l2`: native 3D reader at level 2 (9.6 um) | H100 | 60 / 95 / 200 at 9.6 um | tutorial: 2.5 h on an H100 over the 95.6 cm2 canvas |
| `3d_2um`: native 3D reader at 2.4 um (mesh-free readers such as `ink_3d_dino_guided` assumed similar or heavier) | H100 | 300 / 760 / 1500 at 2.4 um | tutorial patch counts: 3x to 16x level 2; not measured |

Estimates (Interpretation; output of `python3 -m kit.cloudcost jobs`):

| Job | GPU hours (low / typical / high) | USD low | USD typical | USD high |
| --- | --- | ---: | ---: | ---: |
| Inference, 2.5D 9 um-class reader, 10 cm2 at 7.91 um, forward + reversed | 0.06 / 0.07 / 0.13 | 0.102 | 0.146 | 0.264 |
| Inference, 2.5D 9 um-class reader, 100 cm2 at 7.91 um, forward + reversed | 0.13 / 0.29 / 0.83 | 0.215 | 0.481 | 1.37 |
| Inference, 2.5D 2.4 um reader, 10 cm2 at 2.4 um, forward + reversed | 0.16 / 0.27 / 0.72 | 0.409 | 0.704 | 1.83 |
| Inference, 2.5D 2.4 um reader, 100 cm2 at 2.4 um, forward + reversed | 1.16 / 2.27 / 6.72 | 2.89 | 5.67 | 16.65 |
| Inference, native 3D reader at level 2 (9.6 um), 100 cm2 | 1.77 / 2.74 / 5.66 | 7.78 | 12.08 | 24.95 |
| Inference, native 3D reader at 2.4 um, 10 cm2 | 0.93 / 2.21 / 4.27 | 4.13 | 9.77 | 18.87 |
| Fine-tune a 9 um 2.5D reader, 4 variants in parallel on 4 x H100 (prepare, base, variants) | 1.15 / 1.93 / 3.50 | 5.29 | 8.96 | 16.12 |
| Same fine-tune, smoke run (5 steps per variant, warm Volume) | 0.42 / 0.75 / 1.25 | 1.87 | 3.34 | 5.60 |
| Same fine-tune run sequentially on 1 x A10 (2 to 4 h) | 2.00 / 2.50 / 4.00 | 3.31 | 4.31 | 6.85 |
| Train a 3D ink model from scratch with pseudo-label self-training (2 x H100 for 6 to 12 h, plus tuning) | 15.00 / 24.00 / 36.00 | 66.55 | 106.74 | 160.76 |
| Surface tracing / spiral fit on one scroll region, both winding senses, render and infer (A10) | 1.50 / 3.10 / 6.20 | 2.44 | 5.02 | 10.02 |
| Character n-gram language model fit (CPU only, 4 cores, 16 GiB) | 0.00 / 0.00 / 0.00 | 0.158 | 0.317 | 0.950 |
| Small CNN classifier on patches (1 x T4, 2 cores, 16 GiB) | 0.25 / 0.50 / 1.00 | 0.203 | 0.406 | 0.813 |

Notes on the rows:

- **Inference.** 9 um-class readers are cents per 10 cm2 on Modal and run fine on a laptop GPU; 2.4 um readers are the first inference worth sending to a cloud GPU. Mesh-free or native 3D readers at 2.4 um cost about 1 USD per cm2 (typical) and should be timed on one batch before any wide run.
- **Fine-tune check.** A prior figure of "about 3 to 4.40 USD" for four variants on four H100s for 15 to 25 min does not hold. Four H100s for 15 to 25 min are 1.0 to 1.67 GPU hours, 3.95 to 6.58 USD of GPU alone, 4.39 to 7.32 USD with 4 cores and 32 GiB per container, before the base phase (1 x H100, about 1.10 USD) and CPU preparation (about 0.45 USD). The 3.30 to 4.40 USD figure matches a single A10 for 3 to 4 h of GPU at 1.10 USD/h (no CPU, memory or preparation); with those added that plan is 3.30 to 6.85 USD (row "1 x A10"). The 4 x H100 layout is about 9 USD typical (5.29 to 16.12); its 5-step smoke run about 3.30 USD. A pipeline-level estimate that assumes 45 min per variant gives about 15 USD.
- **3D from scratch.** The main 2 x H100 run is 70 % of the cost. Scaling down to one H100 for 9 h halves that line; tuning on short runs first is what keeps the high case near 160 USD.
- **Spiral fit.** Matches the published Modal run's order of magnitude: 13.53 USD for about 6.5 GPU hours and 1.5 CPU hours including verification passes ([bnleft](https://github.com/bnleft/first-light-pherc0211)).
- **Small models.** A character n-gram model or a small classifier costs well under 1 USD on Modal, and is free on a laptop CPU or GPU; cloud adds nothing for them.

### What a fixed budget buys

Wall hours of one GPU container (GPU only / with 4 cores and 32 GiB), from `python3 -m kit.cloudcost budget 30 100 500`:

| GPU | 30 USD: h GPU only / h container | 100 USD: h GPU only / h container | 500 USD: h GPU only / h container |
| --- | ---: | ---: | ---: |
| B300 | 4.2 / 4.0 | 14.1 / 13.3 | 70.4 / 66.3 |
| B200 | 4.8 / 4.5 | 16.0 / 14.9 | 80.0 / 74.7 |
| H200 | 6.6 / 6.0 | 22.0 / 20.1 | 110.1 / 100.3 |
| H100 | 7.6 / 6.8 | 25.3 / 22.8 | 126.6 / 113.8 |
| RTX-PRO-6000 | 9.9 / 8.6 | 33.0 / 28.8 | 165.0 / 143.9 |
| A100-80GB | 12.0 / 10.2 | 40.0 / 34.0 | 200.1 / 169.9 |
| A100-40GB | 14.3 / 11.8 | 47.6 / 39.3 | 238.2 / 196.6 |
| L40S | 15.4 / 12.5 | 51.3 / 41.7 | 256.3 / 208.7 |
| A10 | 27.2 / 19.4 | 90.8 / 64.7 | 453.9 / 323.4 |
| L4 | 37.5 / 24.1 | 125.1 / 80.4 | 625.6 / 402.1 |
| T4 | 50.8 / 29.0 | 169.4 / 96.6 | 846.9 / 483.2 |

Container hours include 4 cores and 32 GiB memory per GPU container.

Example (Interpretation): 100 USD buys about 23 H100 container hours, enough for two typical 9 um fine-tune rounds (about 18 USD), a 2.4 um reader over 500 cm2 in both directions (about 28 USD) and half of a 3D-from-scratch run; or one full 3D-from-scratch run (typical 107 USD) slightly over budget.

## 6. Alternatives

On-demand prices per GPU hour on 2026-10-07. Pods and instances bill while running, idle or not; Modal bills per second and scales to zero.

| GPU class | Modal | RunPod Secure / Community | Lambda (1x) | Vast.ai min / median (snapshot) | Lightning | Colab (community CU rates x 0.10 USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H100 SXM | 3.95 | 3.49 / 2.69 | 4.29 | 1.48 / 2.00 (7 offers) | 4.50 | Pro+ only, rate unknown |
| A100 80 GB | 2.50 | 1.59 / 1.39 (SXM) | 2.79 (8x only) | 0.38 / 0.76 (SXM4) | 2.71 | about 0.75 |
| A100 40 GB | 2.10 | n/a | 1.99 | 0.41 / 0.72 (PCIe, memory not filtered) | 2.19 | about 0.54 |
| L40S | 1.95 | 1.09 / 0.79 | n/a | 0.40 / 0.71 | 2.14 | n/a |
| A10 | 1.10 | n/a | 1.29 | no offers | n/a | n/a |
| L4 | 0.80 | 0.49 / 0.44 | n/a | 0.24 / 0.32 | 0.79 | about 0.17 |
| T4 | 0.59 | n/a | n/a | not queried | 0.55 | about 0.12 |

Sources: [Modal](https://modal.com/pricing); [RunPod](https://www.runpod.io/pricing) (page dated 2026-09-27; serverless H100 4.79, A100 2.72); [Lambda](https://lambda.ai/pricing) (plus tax; 8x H100 3.99 per GPU); Vast.ai public offers API `https://console.vast.ai/api/v0/bundles/` queried 2026-10-07 19:30 UTC (on-demand, single GPU; a live marketplace, hosts vary, interruptible offers are cheaper, [vast.ai/pricing](https://vast.ai/pricing)); Lightning from a third-party capture of its pricing page dated 2026-09-21 ([usagepricing](https://www.usagepricing.com/blueprint/lightning-ai); the official page renders by script and was not read directly; unverified), with 5 free credits at signup plus 25 after adding a card ([Lightning](https://api.lightning.ai/pricing/)); Colab Pro 9.99 USD/month, Pro+ 49.99, 100 compute units 9.99 USD ([Colab](https://colab.research.google.com/signup)), compute-unit burn rates are a community measurement from March 2026 ([mccormickml](http://mccormickml.com/2024/04/23/colab-gpus-features-and-pricing/)), the GPU type is not guaranteed and H100 is Pro+ only ([colabtools #6076](https://github.com/googlecolab/colabtools/issues/6076)); Kaggle gives about 30 free GPU hours per week (P100 or 2 x T4, floating quota, queues when busy) ([Kaggle docs](https://www.kaggle.com/docs/notebooks), [quota post](https://www.kaggle.com/product-feedback/173129)).

Which to use (Interpretation):

| Job type | Best value | Why |
| --- | --- | --- |
| Short, bursty GPU jobs (pilot runs, smoke tests, inference over tens of cm2) | Modal | Per-second billing, no idle pod, scale to zero; included monthly compute |
| Many parallel short variants | Modal | Up to 10 GPUs at once on Starter, no cluster setup |
| Long single-GPU training (many hours) with resumable checkpoints | Vast.ai or RunPod Community | H100 at 1.48 to 2.69 USD/h and A100 80 GB at 0.38 to 1.39 against 3.95 and 2.50 on Modal, if pods are stopped promptly |
| Small models, 9 um-class inference, notebooks | Kaggle free GPUs, Colab, or a local GPU | Free or cents; P100 or T4 is enough |
| Reproducible pipeline others can rerun | Modal | One Python file defines image, data staging and GPU steps |

## 7. Checklist: keeping costs down

1. Set a Workspace budget (hard cap) and a spend limit on the Usage & Billing page before the first GPU run.
2. Perfect and profile the job locally (CPU or laptop GPU) on a small crop first; cloud runs only repeat a pipeline that already works.
3. Run a pilot: a smoke run with a few steps, then a timed slice, and extrapolate before the full job.
4. Stage data on a CPU-only Function into a Volume; never download with a GPU attached. Keep Volume file counts low or use Volumes v2.
5. Right-size: H100 for compute-bound training, L40S or A10 for inference, CPU for small models. Request only the CPU and memory the loader needs.
6. Checkpoint to a Volume every few minutes and make jobs resumable; GPU Functions are always preemptible.
7. Set `timeout=` on every Function (expected time plus margin) and keep `scaledown_window` short for batch jobs.
8. Do not set `region=` unless required (1.15x to 1.75x) and do not use Notebooks or Sandboxes for batch work (about 3x CPU and memory rates).
9. Keep outputs small and in Volumes; download only final maps (egress beyond the allowance is 0.04 USD per GiB).
10. Check `modal app list` and stop anything still running; read the Usage page after each run and log the real cost next to the estimate in the run ledger (below).

## 8. Run ledger

Every Modal run is logged in [`modal-ledger.csv`](modal-ledger.csv), one row per run, appended before launch (estimate) and updated after it (actual cost). The file ships as a header only. Columns:

| Column | Meaning |
| --- | --- |
| `date_time_et` | Launch time, US Eastern, `YYYY-MM-DD HH:MM` |
| `purpose` | Short description of the job |
| `gpu_type` | Modal GPU string as requested (for example `H100`, `A10`), or `none` |
| `gpu_count` | GPUs per container times containers |
| `gpu_seconds` | Total GPU seconds billed |
| `cpu_seconds` | Total CPU-core seconds billed (containers and builds) |
| `est_cost_usd` | Estimate from `python3 -m kit.cloudcost` before launch |
| `actual_cost_usd_if_known` | From the Usage page or `modal billing`; blank until known |
| `cumulative_usd` | Running total of actual (or, if unknown, estimated) cost |
| `notes` | App name, timeout and budget settings, anything unexpected |

## 9. Not verified

- Whether CPU time of image builds is billed at Function rates (not stated on the pages read).
- Speed of H200, B200, B300, RTX PRO 6000, L4 and T4 for 3D CNN training; L40S speed is from a same-chip proxy.
- All inference GPU seconds per cm2 on CUDA GPUs: anchored to an M1 Pro measurement and to the tutorial's "order of an hour" and 2.5 h statements, not measured on Modal.
- The fraction of a segment canvas that is surface (estimates per cm2 of canvas may understate per cm2 of surface).
- Lightning prices (third-party capture), Colab compute-unit rates (community measurement), Kaggle session limits (third-party summary).
- Vast.ai figures are one snapshot of a live market.
- MLPerf and Lambda ratios are for standard benchmarks, not for ink models.
