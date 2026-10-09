# Scrolls: Vesuvius Challenge workbench

![Hero](docs/assets/readme-hero.svg)

Research notes, a run planner, and an experiment ledger for the [Vesuvius Challenge](https://scrollprize.org/): reading the carbonized Herculaneum papyri from X-ray CT scans.

**This repository does not claim that any letters have been found in any scroll.**
The `kit/` package plans and records runs of the official open-source pipeline ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)). It does not reimplement that pipeline. Prize amounts, deadlines and eligible scrolls are a dated snapshot (checked 2026-10-06); [scrollprize.org/prizes](https://scrollprize.org/prizes) wins if they disagree.

## Start here (recommendation)

If you are new, **go for Progress Prizes first, then First Letters**. Leave the Grand Prize for later.

See [scan availability and our processing status](docs/scan-status.md) for completed controls, partial jobs, planned runs and the official CT inventory.

Private research and work that cannot be public live in **[Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private)** (access required). This repository contains public tools, public-data benchmarks and releasable reports.

1. **Read [`docs/start-here.md`](docs/start-here.md).** It is the plain-language path from "no idea" to a first submission, with what each step costs.
2. **Join the [Vesuvius Challenge Discord](https://discord.gg/V4fJhvtaQn).** Registration there is a condition of winning the Grand Prize, and most announcements land there first.
3. **On a Mac?** Read [`docs/mac.md`](docs/mac.md). VC3D, rendering and flattening run natively on Apple Silicon; ink inference runs on the CPU unless you use an open villa PR.
4. **Run the control.** Reproduce letters on PHerc. 0139 segment w035, which the released ink models were trained on. If you cannot see letters there, your pipeline is broken. If you can, that proves only that the pipeline runs: the clean letters are the model's training labels, reproduced ([log](docs/logs/2026-10-07-w035-cpu.md)). `python -m kit plan PHerc0826` prints the commands.
5. **Win something small and real.** In July and August 2026, 28 Progress Prizes went to merged bug fixes, QA tools, benchmarks, and one honest end-to-end First Letters run that found nothing but published its commands and costs. See [`docs/state-of-play.md`](docs/state-of-play.md).

Most of the money ($1.55M of the $2.14M pool) needs an image that papyrologists can read. Raw compute does not buy that by itself. In August and September 2026 at least five independent teams, at least three of them openly Claude-driven, ran the released 9 µm ink models on eligible scrolls (one survey covered all 21 that lacked catalog segments) and published **nulls**. On 8 October 2026 the first First Letters prize was awarded, for PHerc. 343 ([`docs/state-of-play.md`](docs/state-of-play.md)). The bottleneck is keeping a surface on one papyrus sheet, and getting ink models to generalize across scrolls. It is not GPU hours. See [`docs/compute.md`](docs/compute.md).

## Quick start (kit)

Python **3.10+**, standard library only (except `verify`, which reads TIFFs with numpy and tifffile from villa's environment). The heavy pipeline (VC3D, PyTorch, ink models) is installed from villa; `doctor` tells you what is missing.

```bash
# from repo root
python -m kit prizes                      # open prizes, deadlines, eligible scrolls (dated snapshot)
python -m kit doctor                      # GPU, disk, uv/docker/git, VILLA and VC_BIN paths
python -m kit plan PHerc0826              # control + target commands for one eligible scroll
python -m kit plan PHerc0800 --batch 1    # 8.64 um scan: prints the resampling note
python -m kit plan PHerc0826 --mac        # Apple Silicon: VC3D.app tools, CPU or MPS inference
python -m kit cost --gpu-hours 6.5 --rate 1.10
python -m kit run init p0826-a --scroll PHerc0826 \
  --question "Does ink_9um show rows on a hand-refined GrowPatch near the outer wraps?" \
  --readout "Rows of 2-4 mm strokes in forward depth, absent in reverse, on both seeds"
python -m kit run cost p0826-a --usd 7.15 --what "A10, 6.5 h"
python -m kit run status p0826-a running
python -m kit run check p0826-a
python -m kit verify cpu.tif mps.tif --control cpu_reverse.tif   # needs numpy + tifffile (villa's env)
python -m kit fetch w035 data/w035_9um.zarr   # mirror a public bucket prefix over HTTPS, resumable
python -m kit fetch w045 data/w045_9um.zarr   # unseen by v8in; ink_9um trained on its 2.4 um render
python -m kit rowscore f42.tif f43.tif --reverse r42.tif r43.tif --voxel-um 9.362   # row triage score
bash scripts/mac-verify.sh                    # Apple Silicon: CPU vs MPS on the control, one command
python -m unittest discover -s tests -v
```

`plan` prints commands; it never runs them. They are copied from the official [ink detection tutorial](https://scrollprize.org/tutorial5), with each eligible volume's real S3 path resolved from the public bucket. The `run` ledger writes `experiments/<slug>/run.json`, which is gitignored. It hashes your readout rule when the run is created, so a rule edited after you looked is caught by `check`. It refuses to mark a submitted candidate `published` until the prize has been announced: the prize terms forbid going public first.

## The open prizes (snapshot 2026-10-06)

| Prize | Money | Deadline | What wins |
| --- | --- | --- | --- |
| [2027 Grand Prize](https://scrollprize.org/prizes#2027-grand-prize) | $800k / $100k / $50k / $50k | 25 Jun 2027 | Fully unroll one of 13 sealed scrolls; at least 70% of each counted column's preserved characters legible |
| [First Letters](https://scrollprize.org/prizes#first-letters-prizes) | $50k per scroll, max 10 | 25 Jun 2027 | First team to show 10 legible letters in a single 4 cm² area of one of 22 eligible scrolls |
| [PHerc. Paris 4 title](https://scrollprize.org/prizes#first-title-prize) | $50k | 25 Jun 2027 | A papyrologist-readable image of Scroll 1's title |
| [Progress Prizes](https://scrollprize.org/prizes#progress-prizes) | $20k best of month, plus $250 to $20k awards | monthly (next: 31 Oct 2026) | Open-source tools, models, datasets, fixes, reports that help read the scrolls |

All prizes require open-sourcing your method (permissive license) to accept the money. Details, submission contents and the eligible-scroll lists: [`docs/prizes.md`](docs/prizes.md).

## What this repo does / does not

| Does | Does not |
| --- | --- |
| Keep a dated, tested snapshot of open prizes and eligible volumes (`kit/data/`) | Replace the live prize page |
| Print the official control and First Letters commands per eligible scroll, with resolved S3 paths | Run VC3D, render surfaces, or run ink models itself |
| Check a machine against thresholds from published runs (12 GB GPU, 25 GB disk) | Guarantee a run fits; streaming caches grow by gigabytes |
| Record preregistered readout rules, costs and status transitions locally | Decide whether an image shows letters |
| Block publishing a candidate before the prize is announced | Submit anything to the Vesuvius Challenge for you |
| Summarize the pipeline, the state of play, and costs, with sources | Claim a reading, a title, or letters in any scroll |
| Point to villa, community tools, and published nulls | Fork or vendor villa |

## Repository layout

| Path | Role |
| --- | --- |
| [`AGENTS.md`](AGENTS.md), [`CLAUDE.md`](CLAUDE.md), [`llms.txt`](llms.txt) | Entry points for AI agents: rules, map, commands, glossary |
| [`kit/`](kit/) | Planner, doctor, prize snapshot, map scoring (`auc`, `rowscore`, `verify`), `layers`, `provenance`, experiment ledger; CLI `python -m kit` |
| [`scripts/`](scripts/) | One-command Mac GPU runs: `mac-w045.sh` (labelled test), `mac-phase0.sh` (public model comparisons), `mac-verify.sh` |
| [`docs/results.json`](docs/results.json) | Every benchmark number with settings and source |
| [`docs/plans/`](docs/plans/), [`docs/prereg/`](docs/prereg/) | Public evaluation methodology and access-required private plan pointers |
| [`kit/data/prizes-2026-10-09.json`](kit/data/prizes-2026-10-09.json) | Dated prize snapshot: amounts, deadlines, 13 + 22 eligible volumes with S3 names, award notes (earlier snapshots kept beside it) |
| [`tests/test_kit.py`](tests/test_kit.py), [`tests/test_verify.py`](tests/test_verify.py), [`tests/test_rowscore.py`](tests/test_rowscore.py) | Snapshot, planner, doctor, ledger and map-comparison tests |
| [`docs/start-here.md`](docs/start-here.md) | Beginner path, week by week, with costs |
| [`docs/prizes.md`](docs/prizes.md) | Every open prize, its submission contents, eligible scrolls |
| [`docs/pipeline.md`](docs/pipeline.md) | Scan, unwrap, ink, papyrologist: what each stage is and where it fails |
| [`docs/state-of-play.md`](docs/state-of-play.md) | What has been read, what has been tried, recent winners and published nulls |
| [`docs/compute.md`](docs/compute.md) | Hardware, cloud costs, and what AI agents can and cannot do here |
| [`docs/mac.md`](docs/mac.md) | Apple Silicon: what runs locally, the open MPS PRs, useful Mac contributions |
| [`docs/engine.md`](docs/engine.md) | villa is the engine; how `kit/` sits on top of it |
| [`docs/external.md`](docs/external.md) | ScrollPrize repositories, community tools, datasets, models |
| [`docs/sources.md`](docs/sources.md) | Consolidated URLs |
| [`docs/WORKFLOW.md`](docs/WORKFLOW.md) | From experiment idea to private candidate to submission |
| [`experiments/README.md`](experiments/README.md), [`templates/experiment.json`](templates/experiment.json) | Local experiment records and their format |
| [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md) | Rules for AI (and human) editors |
| [`docs/QUALITY.md`](docs/QUALITY.md) | Citation / testing / honesty bar |
| [`docs/NOVELTY.md`](docs/NOVELTY.md) | Claim labels (sourced / model output / candidate / not a reading) |
| [`docs/TESTING.md`](docs/TESTING.md) | How to run tests; what green means |
| [`docs/UI-UX.md`](docs/UI-UX.md) | CLI and docs presentation |
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | State for the next session |
| [`docs/ERROR-LOG.md`](docs/ERROR-LOG.md), [`docs/logs/errors.md`](docs/logs/errors.md) | Real failures only |
| [`docs/logs/`](docs/logs/) | Dated research notes (not claims) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contribution ground rules |
| [`LICENSE`](LICENSE) | Apache-2.0 (permissive, so it meets the prizes' open-source condition) |

## Architecture (kit)

| Piece | Role |
| --- | --- |
| `prizes.py` | Load the snapshot, normalize scroll names (`PHerc. 826` = `PHerc0826`), days to deadline |
| `doctor.py` | `nvidia-smi` or Apple Silicon, memory, disk, tools, `VILLA` and `VC_BIN` checks with sourced thresholds |
| `plan.py` | Official command templates filled per scroll; cost arithmetic |
| `ledger.py` | `run.json` records, readout hash, legal status transitions, privacy gate, provenance hashes, attached checks |
| `fetch.py` | Paged anonymous listing and resumable download of a bucket prefix |
| `verify.py` | Compare two ink maps under a tolerance; pass only if a control map is caught (numpy, tifffile) |
| `rowscore.py` | Text-row periodicity triage score, port of Bullo27's (numpy, tifffile; scipy optional) |
| `cli.py` | `python -m kit` entry point |

## Novel findings

Measurements from this work, with related prior work and limits where known. Novelty remains provisional within our searches (web and the community repositories we read; GitHub search and Discord were not searchable from here). Public labelled data only, never target scrolls; model output, not readings. Proposed uses are untested ideas rather than findings. Reproductions of others' results are in [`docs/results.json`](docs/results.json) and the [log](docs/logs/2026-10-07-community-scan.md).

1. **v8in, scored against human labels on a segment it never saw, trails the older `ink_9um` there** (2026-10-07, corrected 2026-10-08 and 2026-10-09). On PHerc0139 w045, which v8in never saw, v8in (YoussefMoNader/ink-8um-v8in, released 2026-09-28) reaches pixel AUC 0.738 (0.327 with depth reversed, the control) against 0.907 (0.384 reversed) for `ink_9um` inferred on the same bare 640 px crop. v8in's author reports validation during training on PHerc0009B segment ag132115 and two fragments (Frag3, Frag4), and released predictions on PHerc1447 ([model card](https://huggingface.co/YoussefMoNader/ink-8um-v8in), read 2026-10-09); TAUIL's benchmark and Reader v2's scoreboard do not include it. Correction (2026-10-08): w045 is not held out from `ink_9um`. Its 2.399 um render, pooled to 9.6 um, is one of `ink_9um`'s training segments (named pherc0139-w029 in the [label dataset](https://huggingface.co/buckets/scrollprize/datasets/tree/ink_9um)), and this test scores the native 9.362 um render of the same surface against that segment's human labels. So `ink_9um`'s 0.907 is a cross-scan score on a training surface, the test favours it more than first stated, and it cannot say whether v8in trails `ink_9um` on a surface neither saw. [Log](docs/logs/2026-10-08-w045-not-held-out.md). Correction (2026-10-09): the first version set v8in's bare-crop map against 0.914, the same window cut from `ink_9um`'s whole-segment map, which is the mix finding 2 warns about; both `ink_9um` numbers (bare crop 0.9074, whole-segment window 0.9136) and v8in's 0.7382 are in [`docs/results.json`](docs/results.json).
2. **Scoring a crop needs an edge margin** (2026-10-07). A map inferred on a bare 640 px crop differs from the same window of a whole-segment map by up to 0.03 AUC (PHerc0841 ag405: 0.821 against 0.793); leaving a 64 px edge out makes the two identical to four decimals on all three segments tested. Crop-based comparisons that skip this can rank models wrongly by that much.
3. **A threshold taken from a training segment misses about 96 % of real ink on an unseen scroll** (2026-10-07). The 0.7843 cut-off one published PHerc0826 null used is the median `ink_9um` value on labelled ink of PHerc0139 w035, a training segment. On PHerc0841's three labelled segments only 2.3 to 3.7 % of human-labelled ink reaches it (median 0.39 to 0.44); on w045, a surface `ink_9um` trained on through its 2.4 um render, 9.5 %. The same rule still finds about one candidate per cm² on PHerc0841, a third or fewer on labelled ink. Such nulls say little about faint ink. [Log](docs/logs/2026-10-07-novel-checks.md).
4. **Averaging depth windows matches the best window chosen with labels, on an unseen scroll** (2026-10-07). The best 17-layer window moves by up to 4 layers between PHerc0841 segments and between readers (worth up to +0.085 AUC), and no label-free statistic we tried picks it reliably. The mean of four windows reaches the label-chosen optimum: 0.820 against 0.819 mean AUC over 8 reader-crop cases (0.785 with the default window). [Log](docs/logs/2026-10-07-novel-checks.md) Related prior work, found later: window averaging of Hecate on PHerc0841 ([ArcheyChen](https://github.com/ArcheyChen/vesuvius-eligible-scouting)), a smaller window effect on whole PHerc0841 segments ([villa #1867](https://github.com/ScrollPrize/villa/issues/1867), at most 0.023) and a negative result on training scrolls ([villa #1946](https://github.com/ScrollPrize/villa/pull/1946)); what is ours is the comparison with the label-chosen window at 9 um ([log](docs/logs/2026-10-07-overlap-and-baseline.md)).
5. **Two of PHerc0841's three labelled segments are the same papyrus** (2026-10-07). The published meshes of w00 and ag896 have median nearest-sampled-point distance 8.6 voxels (81 um) on a 47 um sampling grid, within 25 voxels over 98 % of their 12.7 cm², and where both are labelled their human ink labels agree (Dice 0.83, against 0.25 on average and at most 0.69 for 200 displaced matches); ag405 is a different surface (median gap 39 to 48 voxels). So PHerc0841 offers two independent labelled surfaces, not three: three-segment means count one sheet twice, and leave-one-segment-out between w00 and ag896 trains on the test sheet. Community reports had disagreed (different windings, or the same text); this measures it. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
6. **Raw CT brightness alone carries almost no ink signal on PHerc0841** (2026-10-07). Each of the 28 surface-volume layers, used as an ink map, scores pixel AUC 0.43 to 0.58 on the crops and 0.47 to 0.54 on whole segments, and 0.49 to 0.51 after a 48 um high-pass; depth maximum and standard deviation reach at most 0.57. Readers reach 0.66 to 0.93 on the same crops, outperforming these brightness-only baselines. The 0.56 to 0.61 retained by `ink_9um` on depth-shuffled ag405 is also higher than those baselines. These comparisons do not isolate which features the models use or establish ink identity. Analogues exist on Paris 4 and fragments (at most 0.55 to 0.56); not found for PHerc0841. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
7. **Ink-map agreement decreases with sampled-point distance between two traces** (2026-10-07, model output). On PHerc0841 w00/ag896, the team's maps correlate 0.86 within 28 um, 0.75 at 28 to 56 um, 0.45 at 56 to 84 um and 0.07 at 112 to 169 um. Thick-slab CT still correlates about 0.4 to 0.5 at the larger distances. These measurements use a 47 um point grid, so distance includes lateral sampling error. They do not isolate normal displacement, distance from the ink layer or a universal tracing tolerance. Whether a bounded correction restores common-label accuracy needs a controlled test. The team's maps are its published `new_canon_autoresearch_recipe` maps, and that recipe's committed trainer lists w00, ag896 and ag405 as training fragments, so these maps are probably in-sample on PHerc0841 (Interpretation; which checkpoint rendered them is not verified; [log](docs/logs/2026-10-09-pherc0841-hecate.md)). [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
8. **PHerc0841 has limited supervision, and reported AUCs need uncertainty** (2026-10-07, measurement). Supervision totals 3.4 cm² across the three segments (1.41, 0.86 and 1.12 cm²; 0.84 cm² of ink summed), covering 7 to 11 % of each. Overlap has not been deduplicated, and w00/ag896 share one sheet. A 1 mm block bootstrap on the team's published maps gives 95 % interval half-widths of 0.008 (w00) to 0.038 (ag405). Those maps come from the `new_canon_autoresearch_recipe`, whose committed trainer ([villa 94602c91](https://github.com/ScrollPrize/villa/blob/94602c91/ink-detection/train_resnet3d_3d_decoder.py), lines 200-207 and 292-293) lists w00, ag896 and ag405 as training fragments, so they are probably in-sample here (Interpretation; [log](docs/logs/2026-10-09-pherc0841-hecate.md)); these intervals describe that scoring setup, not a universal noise floor for model rankings. Reader differences need paired comparisons on common pixels and an independent-surface check. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
9. **Cross-trace agreement suggests a label-free triage experiment** (2026-10-07, model output and untested idea). On PHerc0841, a spot in the top 20 % of one ink map also lies in the other's top 20 % about 70 % of the time within 28 um, compared with 50 % for letter-scale CT texture and a 20 % independent-match expectation. The margin decreases with trace separation. Using this agreement to flag target surfaces is an untested hypothesis, requiring preregistration and held-out false-positive and sensitivity checks. Disagreement alone does not identify which trace is correctly placed or justify a correction. Related geometry and window studies are cited in the log; no claim of priority for agreement-based filtering is established. The maps compared are the team's, probably in-sample on PHerc0841 (see finding 8), so how far this agreement holds on a surface their model never trained on is untested. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
10. **Every published surface volume now matches a published mesh, but one stored cross-scan matrix contradicts its own landmarks** (2026-10-07, measurement on public geometry, no ink). All 692 surface volumes in the bucket catalogue reproduce their canvas exactly from a mesh variant naming the rendered volume, closing the gap reported in [villa #1727](https://github.com/ScrollPrize/villa/issues/1727). Of 29 stored transforms, PHerc1667 1.129 um to 2.399 um misses its six landmarks by 42 to 212 um, while a refit of the same landmarks fits them within 4 um. Transforms into the 2023 7.91 um scans imply scales 0.7 to 1.5 % above the nominal voxel ratio (Paris 4, PHerc0332, PHerc1667), which suggests those voxels are about 1 % smaller than stated. Cross meshes are exact affine images of the traced mesh, and where measurable they put the papyrus within a few micrometres of the native render. [Log](docs/logs/2026-10-07-mesh-hypothesis.md), [data](docs/data/mesh-hypothesis/README.md).
11. **PHerc1667's published 1.129 um renders appear misplaced, and 1.129 um renders on three other scrolls sit about 16 um from their 2.4 um renders** (2026-10-07, measurement; the PHerc1667 result is post hoc). Phase correlation of centre layers on 3 mm tiles: on three control scrolls the 1.129 um renders are offset by a constant (-11.9, -11.0) um from the 2.4 um renders (216 tiles, spread 1.7 um). On five PHerc1667 segments, tiles with clear matches follow the shift predicted if the landmarks are right and the matrix wrong (median miss 7.7 um, slope 0.93), and matches vanish where that predicted displacement is large (median 158 um, up to 475 um). The pre-registered version of this test failed its own control bar, so this needs a calibrated rerun before anyone relies on it. [Log](docs/logs/2026-10-07-mesh-hypothesis.md).

Further controlled tests repaired a continuous-surface matching defect and completed real labelled correction and reconstruction audits, including negative results. See the [follow-up evidence](docs/logs/2026-10-07-followup-tests.md) and [review of villa support masking](docs/logs/2026-10-07-coarse-support-mask.md). These do not establish a new reading or successful real correction.

Partial results: the PHerc1447 fine-tune on w00 is recorded in [PR #7](https://github.com/ChaseHendrick/Scrolls/pull/7), and the two-crop tricks table in [PR #8](https://github.com/ChaseHendrick/Scrolls/pull/8). Matched controls and the complete ag405 independent-surface comparison remain pending. v8in itself on PHerc0841 is published: Bullo27, [v8in-12gb](https://github.com/Bullo27/v8in-12gb) (2026-10-01), AUC 0.837, 0.807 and 0.810 on w00, ag896 and ag405, ahead of `ink_9um` there. The Mac Phase 0 queue (`scripts/mac-phase0.sh`) is meant to reproduce it; no Mac v8in score on PHerc0841 is recorded here yet ([scan status](docs/scan-status.md)).

A [further adaptive-geometry experiment and PR review](docs/logs/2026-10-07-adaptive-resolution.md) preserves a failed primary retention test alongside promising local coarsening results. Frozen evidence and an independent hash audit accompany it.

[Measured CPU optimizations](docs/logs/2026-10-07-production-speed.md) make the complete surface-correction process 2.07x faster on the real PHerc0841 test crop with identical outputs; fresh AUC CLI scoring is 1.25x faster. These measure the named operations, not total scroll-reading throughput.

## Guidelines

- [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md): cite URLs; no claimed letters; candidates stay private; tools need tests.
- [`docs/QUALITY.md`](docs/QUALITY.md): every claim about prizes or results has a dated source.
- [`docs/NOVELTY.md`](docs/NOVELTY.md): an ink map is model output, not a reading.
- [`docs/TESTING.md`](docs/TESTING.md): unittest; what green does and does not mean.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): PR ground rules.

## License note

Code here is Apache-2.0. Vesuvius Challenge data is CC BY-NC 4.0 (newer scans) or the EduceLab data license (older scans); check each volume in the [data browser](https://scrollprize.org/data_browser). Do not commit scroll data, renders or ink maps to this public repository.

[Further CPU scaling checks](docs/logs/2026-10-07-production-scaling.md) make full-map row scoring 7.01x faster on the tested public 305-million-pixel map with optional [`--fast-resize`](docs/rowscore.md). Its numerical mode is explicit; dense defaults remain unchanged. Exact geometry batching and label-filter reuse add smaller measured gains.
