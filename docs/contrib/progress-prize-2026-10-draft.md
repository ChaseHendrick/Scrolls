# Draft: October 2026 Progress Prize submission

Status: draft, not submitted. The user submits it through the [form](https://docs.google.com/forms/d/e/1FAIpQLSc4flEfgK2nyjoczz2_U_XrIGMlgrnSknWatLqrFPnbtKfZwg/viewform) by 31 Oct 2026, 11:59pm Pacific. Blanks marked **[MAC]** wait on `scripts/mac-w045.sh`; **[ATLAS]** waits on `scripts/mac-atlas-v8in.sh` and is filled only if that run is a null (a candidate is never described here; see [`../WORKFLOW.md`](../WORKFLOW.md) 3b).

---

## Title

v8in against labels on a seen and an unseen scroll, with a reverse-depth control

## Problem

Ink models are usually judged by eye, often on segments they were trained on. On PHerc0139 w035, the segment most tutorials use as the control, the clean letters `ink_9um` shows are its own training labels reproduced: every clean letterform lies inside a supervised label region, and two letters painted outside those regions do not appear ([log](../logs/2026-10-07-w035-cpu.md)). That proves a pipeline runs, not that a model reads unseen ink. v8in (YoussefMoNader/ink-8um-v8in, released 28 September) has been checked on PHerc1447 by its author and reproduced there by others, including on Apple Silicon ([afraazali42](https://github.com/afraazali42/vesuvius-challenge), M3 Max, 3 October). It has not been scored against labels on other scrolls. The closest prior work is [TAUIL-Abd-Elilah's held-out benchmark](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search): eight labelled segments including PHerc0841, scoring `ink_9um`, d9v2 and Reader v2, with v8in used only to check seven leads.

## What this adds

One command on an Apple Silicon Mac, `scripts/mac-w045.sh` (`QUICK=1` for under an hour; `SEGMENT=` picks w045 or one of PHerc0841's three segments), and three tested `kit` tools it is built from:

| Tool | What it does | Checked against |
| --- | --- | --- |
| `kit auc` | Pixel AUC of an ink map against a segment's published `inklabels.zarr`, only inside `supervision.zarr`, with the reverse-depth map as the control. Maps the 2.4 µm label grid onto the 9 µm surface by a uniform scale and refuses anisotropic grids; works on a cropped map | Pairwise definition (unit test); a cropped map and the same window on the full grid give the same AUC on the same 78,047 ink pixels |
| `kit rowscore` | Text-row periodicity score (port of Bullo27's), forward against reverse, averaged over checkpoints | The original script to float rounding on six maps; 79.8 on w045 against Bullo27's published 84 for the same checkpoint on his own render |
| `kit layers` | Surface-volume zarr (OME or bare) to the numbered layer TIFFs v8in reads, optionally cropped | Unit tests; 23 s for all of w045, reading row bands across layers (per-layer reads decompress every chunk 28 times) |

w045 is held out from both models: `ink_9um` per Bullo27's survey, and v8in per its patch pack, whose PHerc0139 segments are w033, w035, w041 and w044.

## Results

`ink_9um`, CPU reference (villa `e0bbb8b`, step 75,000), on the team's published surface volumes. PHerc0841 is in neither model's training set; its `ink_9um` numbers agree with Bullo27's calibration and TAUIL's benchmark (0.736):

| | AUC as stored | AUC reversed | Row score as stored / reversed |
| --- | --- | --- | --- |
| Seed 42, whole supervised region (149,192 ink px) | 0.872 | 0.443 | 79.8 / 8.1 |
| Seed 43, whole supervised region | 0.887 | 0.502 | 68.3 / 10.6 |
| Seed 42, 640 px crop of densest text (78,047 ink px) | 0.914 | 0.370 | |
| Seed 43, same crop | 0.910 | 0.435 | |
| PHerc0841 w00, seed 42, whole (crop) | 0.748 (0.770) | 0.501 (0.514) | 13.7 / 23.6 |
| PHerc0841 ag896, seed 42, whole (crop) | 0.720 (0.655) | 0.570 (0.540) | 17.5 / 8.8 |
| PHerc0841 ag405, seed 42, whole (crop) | 0.751 (0.793) | 0.601 (0.653) | 46.4 / 7.5 |

Mac (Apple M1 Pro, MPS):

| | AUC as stored | AUC reversed |
| --- | --- | --- |
| `ink_9um` seed 42 via villa PR #1865, w045 crop | 0.9136 | 0.3704 |
| `ink_9um` seed 43 via villa PR #1865, w045 crop | 0.9098 | 0.4347 |
| v8in, w045 crop, stride 21 | 0.7382 | 0.3269 |
| v8in, PHerc0841 crops (w00, ag896, ag405) | **[MAC]** | **[MAC]** |
| v8in CPU vs MPS (`kit verify`, reverse as control; a second-chip confirmation of afraazali42's M3 Max result) | pass, max diff 1, Pearson 0.99999998 | |
| Time, M1 Pro | `ink_9um` about 11 min per seed (whole segment, both directions); v8in about 1.1 s per tile on MPS, 25 s on CPU | |

MPS `ink_9um` equals the CPU reference to four decimals. On w045, a segment of a main `ink_9um` training scroll, v8in reads ink but scores well below `ink_9um`; v8in saw about 1 % of its training patches from PHerc0139.

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
