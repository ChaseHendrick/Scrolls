# AGENTS.md

Entry point for AI agents (and people) working in this repository. Read this file first, then the files in "Read first". Rules here bind every agent; the full rulebook is [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md).

## What this repository is

A workbench for the [Vesuvius Challenge](https://scrollprize.org/): reading carbonized Herculaneum scrolls from X-ray CT. It does not reimplement the official pipeline ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)); it plans runs of it, scores ink maps against published labels, checks results across devices, records provenance, and keeps dated research notes. Owner: Chase Hendrick (GitHub ChaseHendrick). Machine: Apple M1 Pro (MPS GPU, no CUDA).

## Public and private work

**[ChaseHendrick/Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private) is the home for all work that cannot be public** (user decision, 2026-10-07). Read its handoff and relevant branches before starting or continuing a private investigation. Keep candidate outputs, private research notes and submission material there or in its ignored local data directories. This public repository holds tools, public-data benchmarks and material cleared for public release. Never copy private findings into public commits, PRs, CI logs or documentation.

## Read first, in this order

When the private checkout is available, refresh the combined session context from that checkout with `python3 -m kit.repo_handoff context --private-root . --public-root ../Scrolls`. Its handoff helper installs local Git hooks in both checkouts and writes combined context only inside the private workspace. Hooks do not push, run hosted jobs or copy private notes into this repository. Read the generated private context before private work; never paste it into public artifacts.

1. [`docs/HANDOFF.md`](docs/HANDOFF.md): current state and the next steps, newest session first.
2. [`docs/plans/roadmap.md`](docs/plans/roadmap.md): phases, gates, timeline.
3. [`docs/results.json`](docs/results.json): every benchmark number with its settings and source.
   The README section "Novel findings" lists only results not published elsewhere; reproductions stay in results.json and the logs. Keep both in step when numbers change.
4. [`docs/logs/`](docs/logs/): dated research notes; the newest explains the latest numbers.
   Literature (arXiv, journals, Zenodo, Kaggle): [`docs/logs/2026-10-07-literature.md`](docs/logs/2026-10-07-literature.md) and machine-readable [`docs/papers.json`](docs/papers.json).
5. [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md): the rulebook.

## Hard rules (short form)

1. **Never publish or describe a possible finding.** Target-scroll maps, triage lists and verdicts belong in Scrolls-private or its ignored local data directories. The prize terms forbid disclosure before the official announcement. This repository is public.
2. **An ink map is model output, not a reading.** Never write that letters were found or read.
3. **Preregister before looking.** Readout rules are fixed (`python -m kit run init`, or a committed file in `docs/prereg/`) before any target map exists.
4. **Every check must be able to fail.** Device agreement needs a control (`kit verify --control`); AUC needs the reverse-depth map as control.
5. **Cite real URLs and dates** for facts about prizes, people and published results. Label claims: Sourced fact, Community report, Model output, Interpretation, Untested idea ([`docs/NOVELTY.md`](docs/NOVELTY.md)).
6. **No scroll data, maps or weights in git.**
7. **`kit/` changes need tests** in `tests/`.
8. **Nothing outward without the user's go-ahead:** no posting, submitting, renting compute or opening upstream PRs. **No Hugging Face or forum posts at all** (user decision, 2026-10-07).
9. **Log local compute.** Wrap every local run (Mac CPU or MPS) with `python -m kit run local SLUG -- COMMAND` so wall time and electricity cost reach the ledger ([`docs/compute.md`](docs/compute.md)).
10. **Style:** plain sentences; never U+2014 or U+2013 dashes; commit messages end with the session's attribution lines.
11. **GPU work goes to Modal, not hours of CPU** (user decision, 2026-10-08). Before starting any job, estimate its time. A job that needs a GPU, or more than about an hour on CPU, runs on Modal. Claude's cloud sessions cannot reach Modal, even with the CLI installed, because their proxy does not carry Modal's gRPC traffic, so never try to sign in to Modal from one. Write an exact run spec in [`docs/compute/modal-specs/`](docs/compute/modal-specs/README.md) and give the user a short prompt to paste into an agent that runs Modal, such as Codex, or commands to run on their own computer. Costs and rates: [`docs/compute/modal-pricing.md`](docs/compute/modal-pricing.md). Only generic, public-data jobs get a spec here; anything about a target scroll belongs in Scrolls-private's own `docs/compute/modal-specs/`.

## Standing user decisions

| Date | Decision |
| --- | --- |
| 2026-10-07 | Private operational plans and submission material live in Scrolls-private |
| 2026-10-07 | Leave `docs/contrib/villa-1865-m1pro-comment.md` alone |
| 2026-10-07 | No Hugging Face or forum posting |
| 2026-10-07 | No paid compute without the user's budget decision |
| 2026-10-08 | Use Modal for any job that needs a GPU or hours of CPU. Claude cloud sessions cannot reach Modal: write a run spec and hand it to Codex, or give the user commands for their computer (rule 11) |

## Repository map

| Path | What it is |
| --- | --- |
| `kit/` | Standard-library Python package, `python -m kit` (numpy, tifffile, zarr only for map tools) |
| `kit/prizes.py`, `kit/data/prizes-*.json` | Dated prize snapshot: amounts, deadlines, eligible volumes with S3 names and voxel sizes |
| `kit/doctor.py` | Machine check: GPU (CUDA or Apple Silicon), memory, disk, tools |
| `kit/plan.py` | Prints the official First Letters commands for one scroll (never runs them) |
| `kit/fetch.py` | Resumable anonymous download of a bucket prefix; aliases `w035`, `w045` |
| `kit/layers.py` | Surface-volume zarr to numbered layer TIFFs (v8in's input), banded reads, optional crop; `kit shuffle` and `kit layers --shuffle SEED` write the depth-shuffle control |
| `kit/verify.py` | Two maps agree within tolerance, valid only if a control map is caught |
| `kit/auc.py` | Pixel AUC against a segment's `inklabels.zarr` inside `supervision.zarr`; reverse map as control; `--crop`, `--inner` |
| `kit/rowscore.py` | Text-row periodicity triage score (port of Bullo27's); a reading order, not a verdict |
| `kit/provenance.py` | Who ran what, when, on which machine, from which inputs; one digest over the record |
| `kit/ensemble.py` | Average maps of one surface (`python -m kit ensemble OUT MAP MAP ... [--method rank]`); map-level, never cross-seed weights |
| `kit/fibertensor.py` | `kit fibertensor train/predict`: structure-tensor (fibre orientation) features plus a tiny numpy MLP, CPU; a measured null on PHerc0841 and w045 ([log](docs/logs/2026-10-07-grok-laneD.md)) |
| `kit/hpscore.py` | Letter-scale score (Scheirer's 48 um high-pass correlation) against the labels, rolled-key null; pixel AUC rewards blur, this does less |
| `kit/gate.py` | Gate A by the roadmap's rule (`python -m kit gate [WORK]`): committed bars plus Mac results, Mac `ink_9um` checked against the CPU bar |
| `kit/compute.py` | Time ledger per run from provenance records (`python -m kit compute DIR [--watts W]`), after GENChase's COMPUTE.md |
| `kit/overlap.py` | `kit overlap` (do two segments trace the same sheet? mesh gaps, label agreement) and `kit collate` (do two traces' ink maps agree, against a control and displaced matches); `kit auc --bootstrap/--compare` gives AUC intervals and paired differences |
| `kit/meshaudit.py` | `kit meshaudit transforms/canvas/plan/depth`: refit catalogue cross-scan affines from their landmarks, check every surface volume against its mesh, and measure papyrus depth between native and cross renders; [protocol](docs/plans/2026-10-07-mesh-hypothesis.md), [data](docs/data/mesh-hypothesis/README.md) |
| `kit/surfacefix.py` | Experimental bounded normal-offset suggestions, frozen correspondence checks and uncertain-region flags; see `docs/surfacefix.md` |
| `docs/scan-status.md` | Our completed/partial/planned processing, plus the dated official CT catalogue and documented acquisition unknowns |
| `kit/ledger.py` | Local experiment records in `experiments/<slug>/run.json` with readout-rule hash and status gate |
| `scripts/mac-w045.sh` | Mac GPU: score `ink_9um` and v8in-family models on a labelled segment (`SEGMENT=w045` or `0841-w00/ag896/ag405`; `QUICK=1`; `MODEL=v8in|v8in-1447`; `V8IN_FP16=1`) |
| `scripts/mac-phase0.sh` | Mac GPU: the whole Phase 0 queue (v8in and v8in-1447 on the three PHerc0841 crops), resumable, then `kit gate` |
| `scripts/mac-verify.sh` | Mac GPU: `ink_9um` CPU vs MPS on w035 (villa PR #1865) |
| `scripts/soup.py` | Weight average of checkpoints from ONE run (Nieuwlaar's soup42_last4, bit-identical); refuses mixed seeds |
| `scripts/v8in_run.py` | v8in inference wrapper with opt-in fp16 on MPS; logs `tiles=N done in Ns` |
| `docs/plans/` | Public evaluation methodology and access-required private roadmap pointer |
| `docs/prereg/` | Access-required pointer; private target rules belong in Scrolls-private |
| `docs/contrib/` | Public contribution notes and an access-required private submission pointer |
| `docs/logs/` | Dated research notes (not claims) |
| `docs/state-of-play.md`, `docs/prizes.md` | What has been read and tried; prize terms |
| `docs/mac.md` | Apple Silicon guide: commands, how to watch a run, measured timings |
| `tests/` | `python -m unittest discover -s tests`; map tests skip without numpy, tifffile, zarr. `test_repo.py` checks the repo itself: scripts parse, Mac scripts stay bash 3.2, no long dashes, docs JSON parses, documented `kit` commands exist |
| `experiments/` | Local ledger (gitignored except its README) |

## Commands

```bash
python -m unittest discover -s tests -v        # all tests; map tests skip without their numerical dependencies
python -m kit prizes                            # open prizes from the snapshot
python -m kit auc MAP.tif --control MAP_reverse.tif --labels L/inklabels.zarr --mask L/supervision.zarr \
    [--crop Y0 Y1 X0 X1 --surface-shape H W] [--inner 64] [--json]
python -m kit provenance write OUT.json --run NAME --model M --input I --output O
python -m kit provenance check OUT.json --files
bash -n scripts/*.sh                            # syntax check; scripts must stay bash 3.2 compatible (macOS)
```

Testing the Mac scripts off a Mac: `SMOKE=1 EXPECT_GPU=cpu WORK=<scratch dir> bash scripts/mac-w045.sh` (a 256 px window on CPU). Never edit a script in place while a run of it is going: bash reads scripts as it runs; replace files atomically.

## Glossary

| Term | Meaning here |
| --- | --- |
| `ink_9um` | The team's released 9 µm ink model (`scrollprize/ink_9um`), seeds 42 and 43 at step 75,000 |
| v8in | Youssef Nader's ResNet3D-50 ink model (`YoussefMoNader/ink-8um-v8in`, 2026-09-28); `v8in-1447` is its PHerc1447 fine-tune |
| d9v2, Reader v2 | Community fine-tunes of `ink_9um` (TAUIL-Abd-Elilah; Domenico Russo); drop-in `ink_9um` checkpoints |
| w035 | PHerc0139 training segment: a pipeline check only (the model reproduces its own labels there) |
| w045 | PHerc0139 segment unseen by v8in but not held out from `ink_9um`, which trained on its 2.4 um render (pherc0139-w029); d9v2 and Reader v2 inherit that, and Reader v2 also trained on it ([log](docs/logs/2026-10-08-w045-not-held-out.md)) |
| PHerc0841 | Scroll in no candidate's training set, with labelled segments w00, ag896, ag405: the fair generalization test |
| AUC | Probability a labelled ink pixel scores above a labelled background pixel, inside the supervision mask |
| As stored / reversed | Depth order of the surface volume; reversed is the control and should sit near or below 0.5 |
| Crop, `--inner 64` | The 640 px window of densest labelled ink per segment; 64 px edge left out so bare-crop and full-map scores match |
| QUICK | `mac-w045.sh` mode that scores everything on the crop only |
| Atlas | rodriguescarson's renders of 340 automatic meshes on eligible scrolls |
| Provenance digest | SHA-256 over a run's record; publishable alone as a timestamped commitment |
