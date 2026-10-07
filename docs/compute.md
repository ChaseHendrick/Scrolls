# Compute: what you need, what it costs, and what AI agents can do

Checked 2026-10-06. Every number has a source; prices change.

## Two different kinds of "AI compute"

1. **GPU compute** runs the vision models: surface prediction, ink detection, training. This needs an NVIDIA GPU with CUDA (the tutorials assume Linux or WSL2). A chat subscription does not provide this.
2. **An AI coding agent** (Claude Code and similar) writes and debugs pipelines, reads villa's code, runs experiments, and drafts reports. It does not see ink any better than the ink model does.

You need the first to run anything. The second makes you faster. Neither replaces a good surface on the right sheet.

## Hardware that has worked

| Setup | What ran | Source |
| --- | --- | --- |
| RTX 3060 12 GB, 14-core Xeon, home Wi-Fi | Grow, render and 9 µm inference survey of 21 eligible scrolls | [Bullo27/first-letters-survey](https://github.com/Bullo27/first-letters-survey) |
| RTX 5090 | Four experiment reports incl. a PHerc0826 run | [ShribyrLabs/vesuvius-reports](https://github.com/ShribyrLabs/vesuvius-reports) |
| Modal A10 (cloud) | Full PHerc0211 First Letters run, about 6.5 h GPU + 1.5 h CPU, **$13.53** | [bnleft/first-light-pherc0211](https://github.com/bnleft/first-light-pherc0211) |
| 12 GB consumer cards | The official spiral fitter, after a July 2026 progress-prize fix | [winners](https://scrollprize.org/winners) |
| Apple Silicon (M1 Max, M4, M5 Pro) | Ink inference on MPS through open villa PRs, 2.4x to 7.6x faster than CPU | [docs/mac.md](mac.md) |
| CPU only, 2 cores | Scan-visibility atlas of 31 scans, about 400 MB streamed per scroll | [first-letters-scan-atlas](https://github.com/claudepro1515/first-letters-scan-atlas) |

`python -m kit doctor` checks for 12 GB of GPU memory and 25 GB of free disk. Disk: one tutorial training segment is about 25 GB, the full ink label set is hundreds of GB ([tutorial](https://scrollprize.org/tutorial5)), and VC3D's streaming cache under `~/.VC3D/remote_cache` grows by gigabytes.

## Cost notes from published runs

- bnleft: "Modal bills per second with no idle-pod cost; the Aug team's $56 was ~90 % idle RunPod time." Pay-per-second serverless GPUs avoid paying for idle pods.
- Inference on a full segment takes "on the order of an hour on a single GPU" ([tutorial](https://scrollprize.org/tutorial5)).
- Data is streamed from the public bucket, so you do not need to download whole scrolls. The bucket is part of AWS Open Data ([ScrollPrize/open-data](https://github.com/ScrollPrize/open-data)) and reads anonymously with `--no-sign-request`.
- `python -m kit cost --gpu-hours H --rate R` and `python -m kit run cost` keep your own tally.

## Where extra GPU hours help

- Running all 14 released `ink_9um` checkpoints and averaging them. On a held-out PHerc0139 segment this raised Bullo27's row score from 84 and 111 (single checkpoints) to 148, at seven times the inference cost.
- Training or fine-tuning ink models on the public label sets, with real held-out validation.
- Architecture and hyperparameter search. The organizers report an agent swarm, adapted from karpathy/autoresearch, that nearly doubled pseudo-label validation Dice on PHerc. 1667 while training only on PHerc. 139 ([open problems, section 5](https://scrollprize.org/2026_open_problems)).
- 3D models (surface prediction, DINO-style pretraining with [dinovol](https://github.com/ScrollPrize/dinovol)) on large volumes.

## Where they do not

- Running the public model on more automatically grown patches. That has been done at scale, with nulls, because the patches leave the sheet.
- Deciding whether a blob is a letter. That is the papyrologists' call, under the prize rules.

## Using an AI agent well here

Lessons from the published, agent-assisted runs:

- **Preregister.** Write what counts as ink before looking (bnleft's `prereg/readout.md`; `python -m kit run init` here). Agents and humans both see letters in noise.
- **Run the control first** (PHerc0139 w035) and keep it in every report. It checks the pipeline, not generalization: the letters it shows are memorized training labels ([log](logs/2026-10-07-w035-cpu.md)). For a generalization check use a held-out labelled segment; Bullo27 reports clear rows on held-out PHerc0139 w045.
- **Compare forward and reverse depth.** Ink should appear in one direction, not both.
- **`set -o pipefail`.** bnleft lost a run when `cmd | tee log` hid a failed render.
- **Build tools from current villa main.** The published VC3D container was months stale and lacked flags the recipe needs ([villa #1588](https://github.com/ScrollPrize/villa/issues/1588)).
- **Disclose AI assistance** in your report. The published runs do.
- **Keep positives private.** An agent with push access to a public repo must not commit a candidate image. This repo's `.gitignore` and ledger enforce that; see [`WORKFLOW.md`](WORKFLOW.md).

## Local runs: time and electricity

Initialize the experiment with `python -m kit run init` first. Wrap every local run so its time and electricity cost land in the experiment ledger:

```
python -m kit run local SLUG -- COMMAND ARGS...
python -m kit run local SLUG --device apple-silicon-gpu -- COMMAND   # MPS-heavy run
python -m kit run local SLUG --watts 45 -- COMMAND                   # override the average draw
```

It records start and end (UTC), wall time, CPU time from the child-process resource counter when available, the device class and its average watts, estimated kWh (watts times hours) and USD (kWh times the rate). Normal child exit codes are passed through and stored. A signalled child returns the shell convention, 128 plus the signal number, and records the original negative return code. Failed command launches are recorded with exit 127 (missing executable) or 126 (other launch error). Wall power is not measured: macOS `powermetrics` needs sudo, so the energy is an estimate from a device-class average (`kit/localcost.py`, `DEVICE_WATTS`).

The rate is the local electricity rate (set in your local config), never in git: env var `SCROLLS_ELECTRICITY_USD_PER_KWH`, or `electricity_usd_per_kwh` in `~/.config/scrolls/local.json` (or a gitignored `scrolls.local.json`). The same file may set `device` and `device_watts`. The run fails before starting if no rate is set. The ledger stores the rate, device assumptions, command arguments, time and estimated energy/cost, without copying the config file. Values must be finite and nonnegative. An explicitly selected config file must exist and contain a JSON object. Default watts are illustrative assumptions, not measured device power.

Past runs can be added from logged durations with `python -m kit run backfill SLUG --file scripts/backfill/2026-10-07-local-runs.json`; each entry is marked "estimated from logs". The full batch is validated before any entries are committed. Sub-cent estimates retain six decimals and are added before the ledger rounds its displayed total to cents. On Mac/Linux, local-cost writers use an advisory lock and atomic ledger replacement; other ledger commands do not share that lock. On other platforms, use serial ledger writes. Do not backfill durations that a wrapper has already recorded.
