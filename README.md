# Scrolls: Vesuvius Challenge workbench

![Hero](docs/assets/readme-hero.svg)

Research notes, a run planner, and an experiment ledger for the [Vesuvius Challenge](https://scrollprize.org/): reading the carbonized Herculaneum papyri from X-ray CT scans.

**This repository does not claim that any letters have been found in any scroll.**
The `kit/` package plans and records runs of the official open-source pipeline ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)). It does not reimplement that pipeline. Prize amounts, deadlines and eligible scrolls are a dated snapshot (checked 2026-10-06); [scrollprize.org/prizes](https://scrollprize.org/prizes) wins if they disagree.

## Novel findings

Only results that are new: found in this work and not published elsewhere, as far as our searches reach (web and the community repositories we read; GitHub search and Discord were not searchable from here). Public labelled data only, never target scrolls; model output, not readings. Reproductions of others' results are in [`docs/results.json`](docs/results.json) and the [log](docs/logs/2026-10-07-community-scan.md), not here.

1. **v8in, scored against human labels on a held-out segment, trails the older `ink_9um`** (2026-10-07). On PHerc0139 w045 (held out from both models), v8in (YoussefMoNader/ink-8um-v8in, released 2026-09-28) reaches pixel AUC 0.738 (0.327 with depth reversed, the control) against 0.914 for `ink_9um` on the same 640 px crop. v8in had been evaluated only on PHerc1447 by its author; TAUIL's benchmark and Reader v2's scoreboard do not include it. Caveat: w045's scroll is one of `ink_9um`'s main training scrolls, so this test favours `ink_9um`.
2. **Scoring a crop needs an edge margin** (2026-10-07). A map inferred on a bare 640 px crop differs from the same window of a whole-segment map by up to 0.03 AUC (PHerc0841 ag405: 0.821 against 0.793); leaving a 64 px edge out makes the two identical to four decimals on all three segments tested. Crop-based comparisons that skip this can rank models wrongly by that much.
3. **A threshold taken from a training segment misses about 96 % of real ink on an unseen scroll** (2026-10-07). The 0.7843 cut-off one published PHerc0826 null used is the median `ink_9um` value on labelled ink of PHerc0139 w035, a training segment. On PHerc0841's three labelled segments only 2.3 to 3.7 % of human-labelled ink reaches it (median 0.39 to 0.44); on w045, held out from the training scroll, 9.5 %. The same rule still finds about one candidate per cm² on PHerc0841, a third or fewer on labelled ink. Such nulls say little about faint ink. [Log](docs/logs/2026-10-07-novel-checks.md).
4. **Averaging depth windows matches the best window chosen with labels, on an unseen scroll** (2026-10-07). The best 17-layer window moves by up to 4 layers between PHerc0841 segments and between readers (worth up to +0.085 AUC), and no label-free statistic we tried picks it reliably. The mean of four windows reaches the label-chosen optimum: 0.820 against 0.819 mean AUC over 8 reader-crop cases (0.785 with the default window). [Log](docs/logs/2026-10-07-novel-checks.md) Related prior work, found later: window averaging of Hecate on PHerc0841 ([ArcheyChen](https://github.com/ArcheyChen/vesuvius-eligible-scouting)), a smaller window effect on whole PHerc0841 segments ([villa #1867](https://github.com/ScrollPrize/villa/issues/1867), at most 0.023) and a negative result on training scrolls ([villa #1946](https://github.com/ScrollPrize/villa/pull/1946)); what is ours is the comparison with the label-chosen window at 9 um ([log](docs/logs/2026-10-07-overlap-and-baseline.md)).
5. **Two of PHerc0841's three labelled segments are the same papyrus** (2026-10-07). The published meshes of w00 and ag896 run a median 8.6 voxels (81 um) apart, within 25 voxels over 98 % of their 12.7 cm², and where both are labelled their human ink labels agree (Dice 0.83, against 0.25 on average and at most 0.69 for 200 displaced matches); ag405 is a different surface (median gap 39 to 48 voxels). So PHerc0841 offers two independent labelled surfaces, not three: three-segment means count one sheet twice, and leave-one-segment-out between w00 and ag896 trains on the test sheet. Community reports had disagreed (different windings, or the same text); this measures it. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
6. **Raw CT brightness alone carries almost no ink signal on PHerc0841** (2026-10-07). Each of the 28 surface-volume layers, used as an ink map, scores pixel AUC 0.43 to 0.58 on the crops and 0.47 to 0.54 on whole segments, and 0.49 to 0.51 after a 48 um high-pass; depth maximum and standard deviation reach at most 0.57. Readers' 0.66 to 0.93 on the same crops comes from learned 3D texture, and the 0.56 to 0.61 that `ink_9um` keeps on depth-shuffled ag405 is more than brightness explains. Analogues exist on Paris 4 and fragments (at most 0.55 to 0.56); not found for PHerc0841. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
7. **An ink reading survives a surface offset of about 50 um, not 100 um** (2026-10-07). w00 and ag896 trace one PHerc0841 sheet at gaps from 0 to 0.3 mm, a natural experiment. The team's own ink maps from the two traces correlate 0.86 where the traces are within 28 um, 0.75 at 28 to 56 um, 0.45 at 56 to 84 um, and fall to chance (0.07) beyond 112 um, with the same contrast and the same share of labelled ink at every gap, while the raw CT of the two traces (a 200 um slab) still correlates 0.4 to 0.5 there: the traces see the same papyrus, and the ink reading is what is lost. A surface a tenth of a millimetre off the ink layer reads something else: this is how precise hand-fixed surfaces must be, and how far an automatic surface may wander before a null from it means nothing. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
8. **The PHerc0841 benchmark is 3.4 cm² of labelled papyrus, with about +-0.01 to +-0.04 AUC of sampling noise per segment** (2026-10-07). Supervision covers 7 to 11 % of each segment (1.41, 0.86 and 1.12 cm²; 0.84 cm² of ink in all), less than one 4 cm² First Letters area. A 1 mm block bootstrap puts 95 % intervals of +-0.008 (w00) to +-0.038 (ag405) on a strong map's AUC, so many published rankings on this scroll sit inside the noise. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).
9. **Collation, a label-free check from decipherment** (2026-10-07). Two traces of one sheet are two copies of one text. On PHerc0841 a strong ink spot on one trace reappears on the other 70 % of the time within 28 um (chance 20 %), against 50 % for a strong spot of letter-scale CT texture; the margin fades beyond about 60 um. So on overlapping automatic meshes of a target scroll, a candidate that does not reappear on a second trace within about 50 um is probably noise, and no labels are needed to say so. [Log](docs/logs/2026-10-07-overlap-and-baseline.md).

Pending: v8in's PHerc1447 fine-tune against the labels on PHerc0841 (nobody has published it), and the tricks table on all three crops (cloud CPU, 2026-10-07). v8in itself on PHerc0841 is published: Bullo27, [v8in-12gb](https://github.com/Bullo27/v8in-12gb) (2026-10-01), AUC 0.837, 0.807 and 0.810 on w00, ag896 and ag405, ahead of `ink_9um` there; the Mac run reproduces it.

## Start here (recommendation)

If you are new, **go for Progress Prizes first, then First Letters**. Leave the Grand Prize for later.

1. **Read [`docs/start-here.md`](docs/start-here.md).** It is the plain-language path from "no idea" to a first submission, with what each step costs.
2. **Join the [Vesuvius Challenge Discord](https://discord.gg/V4fJhvtaQn).** Registration there is a condition of winning the Grand Prize, and most announcements land there first.
3. **On a Mac?** Read [`docs/mac.md`](docs/mac.md). VC3D, rendering and flattening run natively on Apple Silicon; ink inference runs on the CPU unless you use an open villa PR.
4. **Run the control.** Reproduce letters on PHerc. 0139 segment w035, which the released ink models were trained on. If you cannot see letters there, your pipeline is broken. If you can, that proves only that the pipeline runs: the clean letters are the model's training labels, reproduced ([log](docs/logs/2026-10-07-w035-cpu.md)). `python -m kit plan PHerc0826` prints the commands.
5. **Win something small and real.** In July and August 2026, 28 Progress Prizes went to merged bug fixes, QA tools, benchmarks, and one honest end-to-end First Letters run that found nothing but published its commands and costs. See [`docs/state-of-play.md`](docs/state-of-play.md).

Most of the money ($1.55M of the $2.14M pool) needs an image that papyrologists can read. Raw compute does not buy that by itself. In August and September 2026 at least five independent teams, at least three of them openly Claude-driven, ran the released 9 µm ink models on eligible scrolls (one survey covered all 21 that lacked catalog segments) and published **nulls**. The bottleneck is keeping a surface on one papyrus sheet, and getting ink models to generalize across scrolls. It is not GPU hours. See [`docs/compute.md`](docs/compute.md).

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
python -m kit fetch w045 data/w045_9um.zarr   # held out from ink_9um and v8in: the generalization check
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
| [`scripts/`](scripts/) | One-command Mac GPU runs: `mac-w045.sh` (labelled test), `mac-atlas-v8in.sh` (preregistered target run), `mac-verify.sh` |
| [`docs/results.json`](docs/results.json) | Every benchmark number with settings and source |
| [`docs/plans/`](docs/plans/), [`docs/prereg/`](docs/prereg/) | Roadmap, training plan, preregistrations |
| [`kit/data/prizes-2026-10-06.json`](kit/data/prizes-2026-10-06.json) | Dated prize snapshot: amounts, deadlines, 13 + 22 eligible volumes with S3 names |
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

## Guidelines

- [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md): cite URLs; no claimed letters; candidates stay private; tools need tests.
- [`docs/QUALITY.md`](docs/QUALITY.md): every claim about prizes or results has a dated source.
- [`docs/NOVELTY.md`](docs/NOVELTY.md): an ink map is model output, not a reading.
- [`docs/TESTING.md`](docs/TESTING.md): unittest; what green does and does not mean.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): PR ground rules.

## License note

Code here is Apache-2.0. Vesuvius Challenge data is CC BY-NC 4.0 (newer scans) or the EduceLab data license (older scans); check each volume in the [data browser](https://scrollprize.org/data_browser). Do not commit scroll data, renders or ink maps to this public repository.
