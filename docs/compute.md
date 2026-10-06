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
- **Run the control first** (PHerc0139 w035) and keep it in every report.
- **Compare forward and reverse depth.** Ink should appear in one direction, not both.
- **`set -o pipefail`.** bnleft lost a run when `cmd | tee log` hid a failed render.
- **Build tools from current villa main.** The published VC3D container was months stale and lacked flags the recipe needs ([villa #1588](https://github.com/ScrollPrize/villa/issues/1588)).
- **Disclose AI assistance** in your report. The published runs do.
- **Keep positives private.** An agent with push access to a public repo must not commit a candidate image. This repo's `.gitignore` and ledger enforce that; see [`WORKFLOW.md`](WORKFLOW.md).
