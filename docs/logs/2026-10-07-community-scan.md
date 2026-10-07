# 2026-10-07: winners' and contributors' repositories, and what changed since the snapshot

Research notes, not claims. Labels per [`../NOVELTY.md`](../NOVELTY.md). Repositories were read from shallow clones on 2026-10-07; commit dates are given per item. GitHub search was not available from this session, so repositories nobody links to were not found. Discord was not read.

## The change that matters most: new ink models (Sourced fact)

| Model | Released | What it is | Run on an eligible scroll? |
| --- | --- | --- | --- |
| [YoussefMoNader/ink-8um-v8in](https://huggingface.co/YoussefMoNader/ink-8um-v8in) | 2026-09-28 | ResNet3D-50 encoder, 2D decoder, `InstanceNorm3d` input (less sensitive to scan contrast), 24 layers, 64 px tiles. Trained on 16 segments from Scroll 1, Scroll 5, PHerc1667, 0139, 0814, 0500P2 and Frag1. MIT. | Not in any repository read here. Bullo27 ran it on PHerc1447 only (Community report). |
| [ink-8um-v8in-pherc1447-loo-w062](https://huggingface.co/YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062) | 2026-09-28 | v8in fine-tuned on PHerc1447 w058 and w060 | Fine-tuned for one scroll; not for First Letters targets |
| [scrollprize/hecate](https://huggingface.co/scrollprize/hecate) | 2026-09-15 | Team model that predicts ink in 3D through the render and attends across depth, so it can follow the middle sheet when the surface wanders. 2.4 and 9.6 µm checkpoints. | Yes: rodriguescarson ran the 9.6 µm checkpoint over 340 automatic meshes (below) |

Probably the "new 9 µm recipe" the team announced on 24 September (nerln and Bullo27 READMEs) is v8in: the team's text-location announcement and the v8in release are four days apart, and Bullo27 shows v8in responding next to the announced PHerc1447 text, which it never saw (Community report). Not confirmed by an organizer statement here.

v8in's PHerc0139 training segments are w033, w035, w041 and w044 ([patch pack card](https://huggingface.co/datasets/YoussefMoNader/ink-8um-v8-patchpack)). **w045 is held out from both v8in and `ink_9um`**, so it is the right generalization check for either model.

v8in's `predict.py` takes `--device`; autocast is enabled only for CUDA, so `--device mps` should run in fp32 on the M1 Pro (Untested idea).

## Who has done what on eligible scrolls (Community reports)

| Who | What | Result | Unpublished part |
| --- | --- | --- | --- |
| [rodriguescarson/eligible-scroll-atlas](https://github.com/rodriguescarson/eligible-scroll-atlas) (2026-09-21) | 340 automatic meshes on eight eligible scrolls, rendered, `ink_9um` and Hecate in both directions, preregistered screens | 5, 2, 0 and 1 passes under four screen variants; none passes all four. The top two Hecate responses are their own candidate and a known false positive, both above real Greek text | **The ink maps of the 5 passing meshes are held back and went to the team privately.** Surface volumes and scores are public (`data/manifest.csv`, `maps_held`) |
| [pscamillo/vesuvius-eligible-meshes](https://github.com/pscamillo/vesuvius-eligible-meshes) (2026-09-27) | The 340 meshes themselves (spiral fits over z windows), 84 inspected | Surfaces only; [maps on HF](https://huggingface.co/datasets/pscamillo/vesuvius-eligible-meshes-ink9) | Their forward and reverse labels are swapped (rendered without `--flip-normals`; correction 2026-09-15) |
| [Bullo27/first-letters-survey](https://github.com/Bullo27/first-letters-survey) (2026-09-30) | 65 GrowPatch patches, 21 scrolls | No letters. Most patches cross sheets near the core | None |
| [millerandmuller](https://github.com/millerandmuller/first-light-pherc0826), [bnleft](https://github.com/bnleft/first-light-pherc0211), [nerln](https://github.com/nerln/vesuvius-first-letters-pherc0800), [ShribyrLabs](https://github.com/ShribyrLabs/vesuvius-reports) | Single-scroll runs | Nulls (already in `state-of-play.md`) | None |

What nobody in this set has done: a **hand-corrected** surface on an eligible scroll, read with **v8in**. Every surface above is automatic (GrowPatch, spiral fit), and every eligible-scroll read is `ink_9um` or Hecate.

## The team's own unmerged work (villa branches, Sourced fact)

- `distilled_3d_ink` (Giorgio Angelotti, last 2026-09-19): Hecate-compatible training, resolution distillation, multi-teacher reporting, 5,136 lines. Likely the next Hecate release.
- `fiber-neural-tracing` (Sean Johnson, pushed 2026-10-06): a learned fiber follower (`fiber_follow`), 18,464 lines. Most merged September work is also fibers (skyward7187 and Hendrik Schilling's VC3D fiber map and line annotation). The team is betting on fibers for connectivity.
- Several `spiral-gap-*` branches (Paul Henderson): spiral fitting refinements.

## Signals from the prize and open-problem pages (Sourced fact, villa history)

- **2026-09-30, [#1937](https://github.com/ScrollPrize/villa/pull/1937):** the open-problems page no longer lists the community's automatic sheet-switch *detection* tools and now asks for tracing that *avoids* sheet switches. Reading: another checker (windcheck, seamcheck, tifxyz-doctor, fit audits) is now less likely to be paid than a tracer or a fixed surface.
- **2026-09-24, [#1887](https://github.com/ScrollPrize/villa/pull/1887):** PHerc1447 left First Letters. First Letters winners must now open-source "code, data, model weights and results", and Progress Prizes favor releasing model weights and training data.
- **2026-10-03:** October Progress Prizes opened with a new submission form ([prizes page](https://scrollprize.org/prizes#progress-prizes)); the deadline is 31 Oct 2026, 11:59pm Pacific.

## Taken into `kit` (this session)

| From | What | Where |
| --- | --- | --- |
| Bullo27 `analysis/rowscore.py` | Text-row periodicity triage score; matches the original to float rounding on six synthetic maps | `python -m kit rowscore` |
| Bullo27, Nieuwlaar | Averaging checkpoints before scoring | `kit rowscore` takes several maps |
| v8in patch pack card | w045 is held out from both models | `python -m kit fetch w045`, step 1b of `kit plan` |
| windcheck, tifxyz-doctor | Read-only surface checks before rendering | step 2 of `kit plan` |
| pscamillo correction | `--flip-normals` on the target render too | step 2 of `kit plan` |

## Not taken, and why

- LimeGS [legibility proxy v5](https://huggingface.co/LimeGS/herculaneum-legibility-proxy-v5): a classifier that ranks 1 cm windows of ink maps by "legible text" likelihood. Self-labelled experimental, no held-out evaluation of the shipped refit. Worth trying as a second triage score once there is a map to triage (Untested idea).
- Nieuwlaar's checkpoint soup and z-window ensemble: real gains on the PHerc0139 title (0.81 to 0.86 AUC) but for `ink_9um`. If v8in is the stronger base, apply the same idea to it later.
- Physics vetoes (Nieuwlaar `vetoes.py`), Hecate depth concentration (rodriguescarson found it does not separate ink from non-ink).

## Later the same day: w045 tooling and a CPU smoke run (Sourced fact: commands and files below)

Added `kit layers`, `kit auc`, `scripts/v8in_run.py` and `scripts/mac-w045.sh`. The script ran end to end on this Linux container with `SMOKE=1 EXPECT_GPU=cpu` (villa PR #1865 at `6723ad158`, torch 2.14.1, v8in revision `d89166b`, model.safetensors SHA-256 `3b94548d…88c4cd`), on one 256 px window of w045 (rows 4000 to 4256, columns 2700 to 2956), v8in at stride 64:

| Map | AUC as stored | AUC reversed |
| --- | --- | --- |
| `ink_9um` seed 42 | 0.7631 | 0.3674 |
| `ink_9um` seed 43 | 0.6688 | 0.2478 |
| v8in | 0.5857 | 0.2791 |

These are a test of the script, not a result: 4,576 ink pixels in one window, and v8in at a quarter of its default tile density. Note for reading the real run: the reversed maps score well below 0.5, so they are not neutral. Compare forward and reverse distances from 0.5, not only their difference.

Measured on the way: v8in costs about 8 s per tile on 4 CPU cores (it upsamples each 64 px tile to 96 x 256 x 256), so full-segment v8in is a GPU job; fp32 at batch 8 used about 10 GB of RAM and was killed for memory next to another job on a 15 GB machine, so the script picks the batch from memory (4 at 16 GB). `kit layers` reads w045 in row bands, 23 s for the full export, against about 72 s of reads layer by layer.

## v8in's depth order on team-layout renders (Sourced fact)

The v8 patch pack's `segments.json` lists every PHerc0139 training segment (w033v5, w035v8, w041v8, w044v8) with `layer_range` [2, 26] and `reverse_layers: false`: v8in read the team's 28-layer 9 µm renders as stored, layers 2 to 25. `predict.py`'s default (the central 24 of 28) is that same window. The atlas renders have 31 planes with the surface at plane 15; their central 24 (planes 3 to 26) put the surface at the same position in the window (index 12). So on w045 and on the atlas meshes, "as stored" is the direction v8in was trained on, and "reversed" is the control.

## ink_9um on PHerc0139 w045, CPU reference (Sourced fact: run below)

villa `main` at `e0bbb8b`, CPU (4 cores), `python -m vesuvius.ink_detection.inference.infer` on the team's published w045 9.362 µm surface volume (`kit fetch w045`), `hybrid_3d2d-seed42/step-075000.pth` (sha256 `e635558a…2a9cab`) and `seed43/step-075000.pth` (`2aeaa85a…b4c28f`, 42 min for both directions), `--overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both`; 10,954 patches per direction, forward 20 min. Scored against w045's labels (`ink-labels/2.399um-volume-20260102150214/20260918`, level 2) inside the supervision mask:

| Window | AUC as stored | AUC reversed | Ink px | Row score as stored / reversed |
| --- | --- | --- | --- | --- |
| Seed 42, whole supervised region | 0.8722 | 0.4425 | 149,192 | 79.8 (4.67 mm, horizontal) / 8.1 |
| Seed 42, 640 px crop, rows 3840 to 4480, columns 2560 to 3200 | 0.9136 | 0.3704 | 78,047 | (too small) |
| Seed 43, whole supervised region | 0.8866 | 0.5024 | 149,192 | 68.3 (4.67 mm, horizontal) / 10.6 |
| Seed 43, 640 px crop | 0.9098 | 0.4347 | 78,047 | (too small) |
| Seeds 42 and 43 averaged, whole | | | | 95.9 (4.67 mm, horizontal) / 9.5 |

Model output on a training scroll's held-out segment, not a reading. It is the CPU reference for `scripts/mac-w045.sh` (the crop row is what `QUICK=1` scores) and the bar v8in is measured against. Bullo27 reports a row score of 84 for this checkpoint on his own w045 render (Community report); ours is 79.8 on the team's render. Scoring a map cut to the crop and the same window on the full grid gave the same AUC on the same 78,047 ink pixels, so `QUICK=1`'s cropping path is exact.

## ink_9um on PHerc0841, a scroll in neither model's training set, CPU reference (Sourced fact: run below)

Same command and seed 42 checkpoint as for w045, on the team's published 9.366 µm surface volumes of the three traced PHerc0841 segments (volume `20250821151531`), scored against their `ink-labels/2.403um-volume-20260319124803/20260918` labels inside the supervision masks (label grid 0.975 of the surface grid on both axes). The crops are the 640 px windows `scripts/mac-w045.sh SEGMENT=0841-*` uses. CPU time: 2,085 s, 817 s and 1,841 s for both directions (shared CPU for the first and third).

| Segment | Whole AUC as stored / reversed | Crop AUC as stored / reversed | Row score as stored / reversed |
| --- | --- | --- | --- |
| w00 (`20260220213127-w00`) | 0.748 / 0.501 | 0.770 / 0.514 | 13.7 / 23.6 |
| ag896 (`…144552896`) | 0.720 / 0.570 | 0.655 / 0.540 | 17.5 / 8.8 |
| ag405 (`…174252405`) | 0.751 / 0.601 | 0.793 / 0.653 | 46.4 (5.82 mm) / 7.5 |

This reproduces Bullo27's unseen-scroll calibration independently (Community report): AUC 0.74 to 0.81 against the labels, no rows on w00 and ag896 (his row scores at most 15.4), rows on ag405 only (his "ag174", 57.8 with two checkpoints). Compared with w045 (0.872, rows at 79.8), `ink_9um` on a new scroll still locates ink but mostly loses the row structure: the blob problem in numbers. Model output, not a reading; PHerc0841 is not First Letters eligible.

## Is this a contribution yet? (Note, 2026-10-07)

Not yet: everything is in this repository and the session. The Challenge pays for released, used work (prize page: "released or open-sourced early", "actually get used"). What is new here: v8in verified on Apple Silicon against the CPU; a labelled, reverse-controlled ink-model test with seen- and unseen-scroll references; an independent reproduction of Bullo27's PHerc0841 calibration. Ways to share, cheapest first: a Hugging Face discussion post on the v8in model page; the v8in vs `ink_9um` result on PHerc0841; a small villa PR for label-scoring with a reverse control; the Progress Prize write-up at the deadline. Each waits for the user's go-ahead (see [`../HANDOFF.md`](../HANDOFF.md)).

## Broader web search, later the same day (Community reports; corrects earlier notes)

A web search (GitHub's search API is blocked from this session) found work the first scan missed:

- **v8in on Apple Silicon is already published.** [afraazali42/vesuvius-challenge](https://github.com/afraazali42/vesuvius-challenge), 2026-10-03, Apple M3 Max: the released `predict.py` runs unmodified with `--device mps`; fp32 MPS and CPU probabilities equal to 5 decimals, fp16 autocast largest difference 0.0026; CPU 0.55, MPS fp32 3.5, MPS fp16 4.9 tiles/s; on PHerc1447 w062 only. Our M1 Pro check (step 5 of `mac-w045.sh`) is a confirmation on a second chip, not a first. [AndreasHad04/villa-apple-silicon](https://github.com/AndreasHad04/villa-apple-silicon) did `ink_9um` and Hecate on an M1 Max (MPS 7.6x and 5.8x the CPU; Hecate 13 of 1,048,576 pixels differ by one level).
- **A held-out benchmark that includes PHerc0841 exists.** [TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search): eight held-out segments with the 20260918 labels from six scrolls, all three PHerc0841 segments among them. AUC means: `ink_9um` 0.794 (0.736 on PHerc0841; ours 0.720 to 0.751, consistent), their fine-tune d9v2 0.856 (0.828), Domenico Russo's Reader v2 0.856 (0.826), the two ensembled 0.867 (0.840). Weights released (d9v2, d9v3; they load like `ink_9um` checkpoints). v8in was used there only to check seven PHerc0826 leads, **not scored on the benchmark**. 150 on-sheet PHerc0826 sites: no lead.
- **Hecate's positives are mostly not depth-specific on eligible surfaces.** [aviad12g/vesuvius-depth-order-control](https://github.com/aviad12g/vesuvius-depth-order-control): on all 10 public PHerc0800 and PHerc1203 surfaces, depth-shuffled input gives more Hecate positives than real input. Rank by Hecate (as `mac-atlas-v8in.sh` orders its meshes) is a reading order only, which is how it is used.
- Also: [ibarapascal/ink-disagree](https://github.com/ibarapascal/ink-disagree) (model disagreement against the 20260918 labels; notes PHerc0841's validation masks cover 66 to 74 % of the canvas), [TAUIL-Abd-Elilah/corpus-ink-survey](https://github.com/TAUIL-Abd-Elilah/corpus-ink-survey) (237 cm² of public First Letters surface, no text), [MasterLaplace/LplVesuvius](https://github.com/MasterLaplace/LplVesuvius) (PHerc0358 issues), [Svyable/scrollq](https://github.com/Svyable/scrollq/issues/172) (v8in reproduction on PHerc1447, open), [Ritwik-Gaur/vesuvius-energy-transfer](https://github.com/Ritwik-Gaur/vesuvius-energy-transfer).

What is still unpublished, as far as these searches reach: v8in scored against labels on PHerc0841 (or w045), and v8in on the eligible scrolls' meshes.
