# Public repository handoff

Updated 7 October 2026. Read [AGENTS.md](../AGENTS.md), [the workflow](WORKFLOW.md) and the current Git/PR state before continuing. Use plain sentences and preserve historical evidence bytes and hashes.

## Before any long job: GPU work goes to Modal (user decision, 8 October 2026)

The user does not want hours spent on CPU for work a GPU does in minutes. Before starting a job, estimate its time. Anything that needs a GPU, or more than about an hour on CPU, runs on Modal. Claude's cloud sessions cannot reach Modal, even with the CLI installed, because their proxy does not carry Modal's gRPC traffic, so do not try to sign in from one. Write the exact run spec in [`compute/modal-specs/`](compute/modal-specs/README.md) and give the user a short prompt to paste into Codex, or commands to run on their own computer. The rule is AGENTS.md hard rule 11.

## Session 8 October 2026: optional development host

[The DigitalOcean workspace guide](compute/digitalocean-workspace.md) records an optional development host for preparing work and controlling Modal jobs. DigitalOcean is not a dependency of Modal. The procedure remains unvalidated end to end; installation and sign-in alone do not prove callable tools or a provisioned workspace. Hosting costs and Modal compute authorization must be checked separately. This documentation does not launch or authorize compute.

## Session 7 October 2026 (evening): mesh hypothesis study

The user asked for a deep dive on the mesh question with the data public. Protocol first ([plan](plans/2026-10-07-mesh-hypothesis.md), four dated amendments committed before each measurement), then `kit meshaudit` (26 tests) and runs on existing cloud CPUs. Results: [log](logs/2026-10-07-mesh-hypothesis.md), [data](data/mesh-hypothesis/README.md), README findings 10 and 11.

- All 692 published surface volumes reproduce their canvas from a published mesh (villa #1727's gap is closed in today's bucket).
- One stored matrix (PHerc1667 1.129 to 2.399 um) misses its own landmarks by 42 to 212 um. Post hoc, the published PHerc1667 1.129 um renders follow the landmark refit, not the matrix: misplaced by a median 158 um on five segments. The pre-registered H5 failed its control bar, so this needs a calibrated rerun.
- 1.129 um renders on three other scrolls sit a constant 16 um from their 2.4 um renders; the cause is unexplained.
- 2023 DLS scans appear about 1 % smaller in voxel size than nominal (Interpretation).

Nothing was posted upstream. Reporting the PHerc1667 matrix to the organisers needs the user's go-ahead. The same branch also carries the five 2026-10-07 cloud job record branches ([PR #29](https://github.com/ChaseHendrick/Scrolls/pull/29)).

## Repository routing

This repository holds tools, public-data benchmarks and material cleared for public release. Private investigations, target-run rules, candidate outputs, operational plans and submission material live in [ChaseHendrick/Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private) (access required). Read its handoff and relevant branches before continuing private work. Keep private content out of public commits, PRs, documentation and CI logs. Earlier mixed operational history has been preserved privately; public benchmark logs and evidence remain here.

Standing public decisions: no Hugging Face or forum posts; leave `docs/contrib/villa-1865-m1pro-comment.md` unchanged; no paid compute without the user's budget decision. Subagents and existing cloud CPUs were authorized for the completed work. These results do not authorize an outward post, submission or new rental.

## Merged review closure

[PR #25](https://github.com/ChaseHendrick/Scrolls/pull/25), [PR #26](https://github.com/ChaseHendrick/Scrolls/pull/26) and [PR #27](https://github.com/ChaseHendrick/Scrolls/pull/27) are merged. Their combined main commit is `25dd450dda3a3da69b02374198fe28055c3b66cc`. The [integration record](logs/2026-10-07-merged-review-closure.md) preserves checks and hashes without changing earlier sealed evidence.

- PR #25 keeps the fine-tuning job unrun. It fixes unknown-label pooling, probability scaling and strict checkpoint loading; explicit execution gates, isolated pinned worker checkouts and verified input/crop/inference receipts prevent accidental execution or stale-cache adoption. No training or paid compute occurred. A precise family-level decision rule must still be frozen before a separately authorized research launch. The original status-only results remain unchanged.
- PR #26 adds tested crop-scan input and memory guards and gates the historical runner. Nonfinite bootstrap intervals invalidate the archived R1/R2 decisions; those results are unresolved, not recoverable from the saved summary. The downsampled point-AUC proxy remains descriptive for its measured overlapping crops and brightness readers. It does not establish general inference accuracy or a production speedup. See the [qualified lane I log](logs/2026-10-07-grok-laneI.md).
- PR #27 merges the performance changes below and the public/private routing. Generic tools and public benchmark evidence stay here; private material belongs in Scrolls-private. Earlier public versions remain in Git history.

Combined validation ran 253 unit tests with numerical dependencies: 252 passed and one Torch-only test skipped. All 17 fine-tuning guard tests passed separately in the existing CPU Torch runtime. The combined-main workflow passed its Python 3.10, Python 3.13 and numerical jobs, including all 39 experiment regressions. These checks validate software behavior and integration, not an end-to-end GPU fine-tune or a new research result.

## Current public performance work

PRs #6-19, #20 and #22 were reviewed and merged; PR #24 is the baseline for the latest scaling comparisons (`c43c41a59ac3793b9a653fa236165f6f6b9d47a4`). Inspect current Git/PR state for the later integration rather than assuming an old branch is still open. The [scaling log](logs/2026-10-07-production-scaling.md) and [evidence](evidence/2026-10-07-production-scaling/) record the current measurements on public PHerc0841 inputs.

- Optional `kit rowscore --fast-resize` reduced complete file-scoring operation time from 39.7320 to 5.6701 seconds median on a public 16460 by 18560 map, 7.0073x across three alternating fresh-worker pairs. This timer includes imports, reads, scoring and JSON construction, but excludes interpreter startup/shutdown and evidence writes. Parent process-wall timings are also retained. Dense and sparse use the same build. Historical fields and resized arrays matched on the tested real inputs, but other shapes differ by float32 rounding and near-tied FFT peaks can change angle or period. Dense remains the default; [compatibility and usage](rowscore.md).
- Exact triangle-edge batching reduced complete correction-process time from 2.5138 to 2.2761 seconds median, 1.1044x relative to PR #24. Five alternating pairs and controls preserve report fields, projections, output hashes and refusal rules. The larger 4096-point correspondence test improved 1.1238x. The real correction still accepts zero edits and flags 16 regions; no recovery improvement is established.
- Exact high-pass reuse reduced fresh paired HP CLI time from 11.2761 to 7.9506 seconds median on a public 2560-pixel crop, 1.4183x across five alternating pairs. The second map in this large test is a synthetic roll used for computation/parity, not a depth control. Real 640-pixel paired tests also matched every field. No persistent cache was added.
- A fixed CPU channels-last inference experiment was rejected: three-map median time increased from 5.3590 to 6.9713 seconds, and shuffled output changed by one uint8 pixel. No inference setting was promoted.

The original scaling integration passed 229 unit tests and 39 experiment regressions; the combined merged validation above includes the later review tests. Fresh real correction and HP CLIs preserve stdout, stderr, files and statuses; correction retains expected abstention exit code 1. Row CLI checks preserve default output and identify both directions' backend when opted in. All tests used existing cloud CPUs and cached public inputs. Raw scans, maps, labels and weights stay outside Git. These ratios are operation-specific and must not be multiplied into total pipeline throughput.

Earlier [production-speed work](logs/2026-10-07-production-speed.md) measured a 2.0744x complete continuous-correction speedup and a 1.25x fresh AUC CLI speedup against its earlier baseline. PR #24 already contains those changes. The inherited 14x layer-export claim was removed: the old 23-second complete export and 72-second read measurement had different scopes. Input preloading saved only 0.71 seconds across three cached-crop maps and was not shipped. Existing banded layer export remains unchanged.

## Public geometry and reader evidence

The [controlled follow-up](logs/2026-10-07-followup-tests.md), [real validation](logs/2026-10-07-real-surfacefix-validation.md), [support-mask review](logs/2026-10-07-coarse-support-mask.md) and [adaptive-resolution experiment](logs/2026-10-07-adaptive-resolution.md) retain successes and failures.

- Schema 2 surface correspondence uses certified continuous bilinear patches and fractional map sampling. It admitted 479 geometry matches on the labelled PHerc0841 crop, 444 within reference coverage, where nearest-vertex matching admitted zero at the same 50 um limit. Ambiguous, singular and uncertified matches are rejected. Historical schema 1 replay remains unchanged.
- Twelve matched actual CT-derived d9v2 maps on a fresh supervised w00/ag896 crop produced four evaluable regions, zero accepted edits and 16 flags. The +1 voxel AUC gain 0.00889 had simultaneous paired interval [-0.00461, 0.02239], failing the frozen bar. All eight full-search displaced-reference nulls accepted zero. Successful correction and combined-rerender improvement remain unestablished.
- Six w045 maps checked published and fresh official stacks. Fresh forward/reverse/shuffle AUC was 0.9255/0.3346/0.5814; pixel controls passed and high-pass detail controls failed. Corresponding maps differed by at most one uint8 level. w045 is a training-scroll pipeline control, not an independent-scroll result.
- Local pag0-to-pag50 CT filtering predicted a disjoint cube with correlation 0.99724, but transport to the original reconstruction failed. The new affine estimator passed 34 algorithm controls, then failed 7/16 held-back checks and four calibration disagreements. No original-to-phase matrix is renderer-approved. The earlier 18.724 um value was an integer-peak discrepancy, not a calibrated physical warp; preserve old records with that qualification.
- Public villa [PR #1996](https://github.com/ScrollPrize/villa/pull/1996) was reviewed at `d651f04d2f5c73fc5ba46c5f859392391cc59b43`. Its tests and saved tables rebuilt. Near-98% public coverage uses a 38.4 um tolerance; the roughly 2x timing refers to one flattening comparison with a distortion tradeoff. Our PHerc0841 stress test uses different native spacing, establishes local support/geometry behavior only, and does not reproduce flattening or ink throughput. Support mode is not enabled in our defaults.
- Adaptive experiments reduced hypothetical primitive counts, but their original retention or reduction gates failed. No conforming adaptive export, global geometry guarantee, measured adaptive speedup or better ink reading is established.

Public model/threshold history is in [results.json](results.json), [scan status](scan-status.md), [cloud partials](logs/2026-10-07-cloud-partial.md) and the dated logs. w00 and ag896 trace the same sheet; their scores are correlated descriptive measurements. Preserve stride-mismatched historical controls as provisional. Published v8in results from Bullo27 are prior art, not a new finding here. No cloud queue is asserted to be currently running.

## Evidence and next public work

Evidence archives contain fixed rules, append-only amendments, source/input receipts, raw timings, failures and independent reviews. SHA-256 checks establish integrity, not scientific validity or external pre-run timestamping. Old provenance seals describe historical commits; verify them against the corresponding exports rather than replacing hashes after a documentation change. Generic tools and public benchmarks remain public even when an artifact's filename includes `candidate`.

Useful next public checks are larger end-to-end pipeline and memory measurements; independently selected supervised correction with Lasagna as comparator and an actual combined-surface rerender for any accepted edit; and conforming adaptive geometry with transition/global-collision costs. Phase rendering remains blocked until a new independently validated registration method passes fresh gates. A full upstream spacing-5/10 support benchmark requires its pinned working grids/tracks and runtime; cached native20 meshes cannot substitute for it.

## Environment

CPU development uses Python 3.12 and numerical dependencies in `.venv`; no services are required. The reusable cloud setup was already tested and saved. Do not restart onboarding or create a worktree merely to resume. Git read/push and public GitHub, S3 and Hugging Face metadata access worked during this session; older denial reports in dated logs describe their earlier attempts. Access to metadata does not prove every checkpoint/CDN route works. This cloud environment has no CUDA, MPS or connection to the user's Mac.

Run `python -m unittest discover -s tests -v` and the separate numerical experiment regressions when changing code. Consult [mac.md](mac.md) for public device controls and [surfacefix.md](surfacefix.md) for correction conventions. Inspect current Git state before editing shared files, preserve any pending user changes and do not modify scripts while they are running.
