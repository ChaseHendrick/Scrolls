# Draft: October 2026 Progress Prize submission

Status: draft, not submitted. The user submits it through the [form](https://docs.google.com/forms/d/e/1FAIpQLSc4flEfgK2nyjoczz2_U_XrIGMlgrnSknWatLqrFPnbtKfZwg/viewform) by 31 Oct 2026, 11:59pm Pacific. Blanks marked **[MAC]** wait on `scripts/mac-w045.sh`; **[ATLAS]** waits on `scripts/mac-atlas-v8in.sh` and is filled only if that run is a null (a candidate is never described here; see [`../WORKFLOW.md`](../WORKFLOW.md) 3b).

---

## Title

A labelled, controlled ink-model test on held-out PHerc0139 w045, and v8in on Apple Silicon

## Problem

Ink models are usually judged by eye, often on segments they were trained on. On PHerc0139 w035, the segment most tutorials use as the control, the clean letters `ink_9um` shows are its own training labels reproduced: every clean letterform lies inside a supervised label region, and two letters painted outside those regions do not appear ([log](../logs/2026-10-07-w035-cpu.md)). That proves a pipeline runs, not that a model reads unseen ink. When v8in (YoussefMoNader/ink-8um-v8in) was released on 28 September there was no quick, labelled, held-out way to compare it with `ink_9um`, and it had not been run on a Mac.

## What this adds

One command on an Apple Silicon Mac, `scripts/mac-w045.sh` (`QUICK=1` for under an hour), and three tested `kit` tools it is built from:

| Tool | What it does | Checked against |
| --- | --- | --- |
| `kit auc` | Pixel AUC of an ink map against a segment's published `inklabels.zarr`, only inside `supervision.zarr`, with the reverse-depth map as the control. Maps the 2.4 µm label grid onto the 9 µm surface by a uniform scale and refuses anisotropic grids; works on a cropped map | Pairwise definition (unit test); a cropped map and the same window on the full grid give the same AUC on the same 78,047 ink pixels |
| `kit rowscore` | Text-row periodicity score (port of Bullo27's), forward against reverse, averaged over checkpoints | The original script to float rounding on six maps; 79.8 on w045 against Bullo27's published 84 for the same checkpoint on his own render |
| `kit layers` | Surface-volume zarr (OME or bare) to the numbered layer TIFFs v8in reads, optionally cropped | Unit tests; 23 s for all of w045, reading row bands across layers (per-layer reads decompress every chunk 28 times) |

w045 is held out from both models: `ink_9um` per Bullo27's survey, and v8in per its patch pack, whose PHerc0139 segments are w033, w035, w041 and w044.

## Results

`ink_9um`, CPU reference (villa `e0bbb8b`, both seeds at step 75,000), on the team's published w045 surface volume:

| | AUC as stored | AUC reversed | Row score as stored / reversed |
| --- | --- | --- | --- |
| Seed 42, whole supervised region (149,192 ink px) | 0.872 | 0.443 | 79.8 / 8.1 |
| Seed 43, whole supervised region | 0.887 | 0.502 | 68.3 / 10.6 |
| Seed 42, 640 px crop of densest text (78,047 ink px) | 0.914 | 0.370 | |
| Seed 43, same crop | 0.910 | 0.435 | |

Mac (Apple M1 Pro, MPS):

| | AUC as stored | AUC reversed |
| --- | --- | --- |
| `ink_9um` seed 42 via villa PR #1865, crop | **[MAC]** | **[MAC]** |
| v8in, crop, stride 21 | **[MAC]** | **[MAC]** |
| v8in CPU vs MPS (`kit verify`, reverse as control) | **[MAC]** verdict, max diff, Pearson | |
| Time, M1 Pro | **[MAC]** | |

**[ATLAS]** If the preregistered v8in run over the 81 public automatic meshes of PHerc0813, 0358 and 0826 ([preregistration](../prereg/2026-10-07-v8in-atlas.md)) is a null: a short paragraph with the count, the meshes inspected, stride, time, and the statement that it is a null for v8in on automatic surfaces only.

## Limits

- w045 is a held-out segment of a training scroll. Bullo27 notes such segments can overstate sensitivity; an unseen scroll (his PHerc0841 calibration) is the harder test.
- Pixel AUC is not legibility. On PHerc0841 `ink_9um` reached AUC 0.74 to 0.81 and no letter was readable.
- The reverse map is not a neutral baseline: it can score below 0.5. Read how far each direction sits from 0.5.
- One segment, one crop for the quick comparison.

## Formats and integration

Input: OME-Zarr surface volumes as `vc_render_tifxyz` writes and the team publishes; the segment's `inklabels.zarr` and `supervision.zarr`. Output: uint8 TIFF ink maps, JSON results. Standard library plus numpy, tifffile and zarr, all in villa's environment. Apache-2.0.

## Links

- Repository: https://github.com/ChaseHendrick/Scrolls
- Mac guide: [`docs/mac.md`](../mac.md)
- Research log with every number above: [`docs/logs/2026-10-07-community-scan.md`](../logs/2026-10-07-community-scan.md)

## AI assistance

Built with Claude Code, directed and reviewed by the author; every number comes from a logged run.
