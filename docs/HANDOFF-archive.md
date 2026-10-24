# Handoff archive: older dated sections

Sections moved out of [HANDOFF.md](HANDOFF.md) unchanged, newest first, so the handoff stays short to read. This is not a handoff and nothing here is open: open items live only in HANDOFF.md's table. Search this file (`grep -n "your words" docs/HANDOFF-archive.md`) instead of reading it whole. Line citations such as `docs/HANDOFF.md:120` written before 14 October 2026 point into the file as it was then; read that version with `git show f87726d:docs/HANDOFF.md` (the last commit before the split) or an older commit.

When HANDOFF.md grows long, move its oldest dated sections, unchanged, to the top of this file (below this paragraph).

## Open items added 16 October 2026 (checked 01:10 ET)

Public work only, neutral voice. PR numbers and SHAs were checked on GitHub when written.

```yaml
handoff:
  written: 2026-10-16T01:10-04:00
  repo: ChaseHendrick/Scrolls
  base: main
  merged_since_last_handoff:
    - {number: 91, branch: grok/glossary, merge: ad2c4f8, topic: GLOSSARY.md, an A to Z of technical terms}
    - {number: 92, branch: grok/perf-cli-parser, merge: dc6713b, topic: kit cli reuses one argparse parser per process}
    - {number: 93, branch: grok/autopipeline-every-scan, merge: 0a22f72, topic: AutoPipeline on every scan}
  open_prs:
    - none
  rules: [no_force_push, do_not_touch_main_claude_or_codex_branches, log_every_cloud_run, open_data_bucket_only]
```

| Item | State | Next step |
| --- | --- | --- |
| Unroll v1.0 (viewer Space, [unroll-space.md](unroll-space.md)) | Released. Control panel redesign (grouped Layers, Ink Bench, View, Destroy, Scrolls), Settings saved in localStorage and settable by URL, plain language glossary, agent API (`unrollView.actions/settings/state/glossary`), Ink Bench button, CPU pick fallback for Destroy on GPUs without float targets. The overlay layer is labeled `ink_9um (9 µm)`, credited to the Vesuvius Challenge. README entries updated | Fix the audit findings below |
| Unroll security and UX audit | Findings, highest first: HIGH stored HTML injection through the Ink Bench annotation id (the note field is escaped, the id is not); MED NaN or Infinity thresholds accepted and carried into share links; MED out-of-range alignment offsets accepted; MED malformed `?bench=` links fail silently or show raw errors; MED HUD collisions at 800x500 and 1100x700, and the readout has no backdrop. LOW: no minimum image size, wrong advice for non-image uploads, a double-escaped name, raw `atob` errors, "9.362 um" instead of µm, mixed UK and US spelling. Passed: bad uploads, zip bomb, path traversal, XSS in names and credits, resize and key spam | Escape the annotation id, reject non-finite thresholds and offsets, show share-link errors, then re-test |
| Glossary | Merged, PR #91 (`ad2c4f8`) | None |
| CLI speedup | Merged, PR #92 (`dc6713b`): one parser per process (about 119 ms to 13 ms per call) | None |
| AutoPipeline on every scan | Merged, PR #93 (`0a22f72`): catalog of every scan volume in the `vesuvius-challenge-open-data` bucket (75 volumes when checked), per-scan config, priced dry-run batch (`kit run all`) and watcher (`kit run watch`). Launches nothing; volumes not in the bucket are marked blocked | Paid batch runs each need the owner's approval |
| Unroll in the README release list | Merged, PR #94 (`590636c`): adds Unroll v1.0 to `docs/releases.json` and the README Released tools section | None |
| Stale branches | **Done** 18 Oct: Chase turned on automatic deletion of merged head branches, and every merged branch this row listed is gone from GitHub (`git ls-remote`, 18 Oct; the list is in this file's history). Still on GitHub and kept: `release-readme/progress-2026-10-fix1`, `-fix2` and `-fix3`, and the `submission/progress-2026-10*` snapshots | Nothing open. Agents may delete a merged branch (never `submission/*`, `release-readme/*` or unmerged branches); a Claude cloud session cannot delete remote branches |
| GPU inference speed probes (C reader) | `torch.compile` gives about 1.85x over eager fp16 per tile; max-autotune about 1.9x; TensorRT fp16, int8 and fp8 builds did not complete (missing ONNX file and `onnx_graphsurgeon`) | Fix the ONNX export before any further probe; no launch without approval |

## Umbilici Space row as of 24 October 2026 (moved here when 1.8.0 shipped)

| Item | State | Next step |
| --- | --- | --- |
| Umbilici Space (23 Oct) | `spaces/umbilici/` and [its page](tools/umbilici.md) on branch `claude/project-thread-xrkbs0`; Space [`SharpMeow/umbilici`](https://huggingface.co/spaces/SharpMeow/umbilici) 1.6.1 deployed (Space commit `c72b2cb0`; center lines v2.2 per-end CT grades, colored per end): guide for every level, VC3D and villa notes cited to villa source, Data tables with CSV and JSON, per-line statistics. CT streams from the open-data bucket in the visitor's browser; nothing is rehosted. Releases entry `umbilici` added | Public since 23 Oct (Chase switched it; live recheck passed: 22 scans, PHerc0846A CT 110 of 110 heights). SharpMeow/pherc0175a-lasagna public since 08:09 UTC; live recheck at 08:15 UTC: all three lasagna dataset links resolve, none fall back to "(soon)". PR #162 merged 23 Oct 08:30 UTC; 1.5.0 and 1.6.0 merged in #163; 1.6.1 (grade coloring) in the follow-up PR. Waiting on Chase: whether lag and black flashes are gone on his Mac |

## Open items added 15 October 2026 (checked 23:20 ET)

Public work only. Every PR and SHA below was checked on GitHub when written; anything not checked says **unverified**.

```yaml
handoff:
  written: 2026-10-15T23:30-04:00
  repo: ChaseHendrick/Scrolls
  base: main
  main_head_at_writing: 303c33f
  open_prs:
    - {number: 85, branch: grok/vesuvius-bible, head: 9229ff8522, topic: Vesuvius Challenge reference book, state: open}
    - {number: 87, branch: grok/unroll-link, head: 5b963dab59, topic: link to the Unroll viewer Space, state: open}
    - {number: 88, branch: grok/autopipe-readme, head: 9983e6f3df, topic: AutoPipeline reference README and agent rules, state: open}
  in_progress_not_pushed:
    - vesuvius_bible_layout_redesign
    - autopipeline_electricity_cli_and_modal_ledger_rows
    - unroll_destroy_mode_agent_api_ink_bench
  rules: [no_force_push, do_not_touch_main_claude_or_codex_branches, log_every_cloud_run, scan_images_not_in_this_repo]
```

| Item | State | Next step | Waits on | Where |
| --- | --- | --- | --- | --- |
| Vesuvius Challenge reference book | **Merged** 16 Oct in [PR #85](https://github.com/ChaseHendrick/Scrolls/pull/85) (merge `fafc316`), files under `docs/vesuvius-bible`, with the redrawn charts (`95ea240`); its branch `grok/vesuvius-bible` (#85) is deleted | Further layout work (the rebuilt PDF, if unfinished) starts on a new branch from `main` | Chase | PR #85 |
| AutoPipeline reference README | PR #88 open, head `9983e6f3df` (`docs/autopipeline/README.md`, `docs/autopipeline/AGENTS.md`, `docs/README.md`). Its commit is authored as Grok Bot, not Chase, against the identity rule below; fix by a new commit only if Chase wants it rewritten (no force-push) | Review and merge | Chase | PR #88 |
| AutoPipeline local-run and ledger tooling | In progress, not pushed: `kit run local` (wall time, CPU time and an electricity estimate, rate read from local config, never git), `kit run backfill`, and automatic one-row-per-app cloud ledger rows. `tests/test_letterlines.py` passes on `main` (13 tests); the pending letterlines change is **unverified** | Review, open a PR | agent | not yet in git |
| Unroll viewer link | PR #87 open, head `5b963dab59` (`README.md`, `docs/unroll-space.md`). The Space ([huggingface.co/spaces/SharpMeow/unroll](https://huggingface.co/spaces/SharpMeow/unroll)) serves commit `f6dcaa7`: multi-scroll registry (`scrolls/index.json` with one manifest per scroll) and Open your own (load your own meshes and ink maps in the browser). In progress, not deployed: Destroy mode (tear, crush, burn, water at any unroll amount), a `window.unroll` agent API, and an Ink Bench whose scores are agreement with the published ink layer, not ground truth | Merge the three working copies, test, deploy; then update `docs/unroll-space.md` | Chase | PR #87 |

## Open items (checked 14 October 2026, 22:45 UTC)

| Item | State | Next step | Waits on | Where |
| --- | --- | --- | --- | --- |
| Stranger account in the contributors | **Done** 14 October: public `main` was rewritten and force-pushed with Chase's approval, so the two exporter commits that GitHub credited to github.com/noreply (`5462ebf`, `301e12d`, now `1544c0f`, `7404735`) are authored by Chase; files and messages unchanged, 14 commits from that day got new IDs. Grok-Bot and codex stay listed for their older commits by his choice. Release branches and the `umbilicus-v1` and `letters-v2-real` tags were not moved, so `umbilicus-v1` points at a commit no longer on `main` (its download still works) | Any agent committing here follows the AGENTS.md identity rules (standing decisions, 14 October) | None | This row |
| Segment stack check and the PHerc0139 segment note | Released 14 October 2026 in PR #80 after Chase approved its 11-file list: `kit stackcheck` (`kit/stackcheck.py`, `tests/test_stackcheck.py`, CLI) checks a stack of consecutive tifxyz segments against the umbilicus from geometry alone and writes per-vertex masks; the note gives the PHerc0139 w033 to w037 measurements, example vertices and a by-eye CT look at 12 places; `stackcheck` entry in `releases.json`, `stackcheck_checks` in `results.json` | Run it on other published stacks when a spiral fit or winding count needs them | anyone | [`logs/2026-10-14-pherc0139-segment-defects.md`](logs/2026-10-14-pherc0139-segment-defects.md) |
| Reports to villa | Issues [#2058](https://github.com/ScrollPrize/villa/issues/2058) and [#2059](https://github.com/ScrollPrize/villa/issues/2059), draft fix [#2060](https://github.com/ScrollPrize/villa/pull/2060) and seed-anchor PR [#2063](https://github.com/ScrollPrize/villa/pull/2063) are open upstream. Issue [#2104](https://github.com/ScrollPrize/villa/issues/2104) (posted by Chase on 14 October): a `vc_grow_seg_from_seed` trace with x/y/z limits stops once a cell skipped at a limit lies inside `used_area`; its fix PR is drafted, not posted | Answer maintainers' reviews; any further post needs the owner's word | villa maintainers, then the owner | [`logs/2026-10-12-upstream-reports.md`](logs/2026-10-12-upstream-reports.md) |
| AutoPipeline public release | Released 14 October with Chase's approval of the exact file list: branch [`submission/progress-2026-10`](https://github.com/ChaseHendrick/Scrolls/tree/submission/progress-2026-10), commit `faada83` | Fixes go out as new file lists, each approved by Chase first | Chase | Branch `submission/progress-2026-10`; Scrolls-private |
| Scroll Text Reader release | **Done** 14 October. Released with Chase's approval in [PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57): `kit letterread`, `kit greeklm`, training and benchmark scripts in `scripts/letters/`. [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58), merged by Chase (merge `25914fb`), makes it installable, reads whole maps, adds controls and exports, and makes the CC BY 4.0 weights `letters-v2-ccby` the default. The letter reader thread installed the guide's pip line from `main` in a fresh venv afterward: it installs, fetches `letters-v2-ccby` and the demo passes. The weights are not in git. `letters-v2-ccby` is the release asset on tag [`letters-v2-ccby`](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-ccby) (sha256 `b14988852fc7...`, CC BY 4.0, published 14 October). `letters-v2-real-step030000.npz` stays on tag [`letters-v2-real`](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-real) (sha256 `44946dad...587477`, CC BY-NC 4.0), pinned in `kit/data/letter-weights.json`. Do not re-tag or delete either, because `--weights` downloads from them | Nothing open. Any new weights get a new tag and registry entry | Nobody | [`letter-reader.md`](letter-reader.md), [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) |
| Released tools in the README | **Done** 14 October: [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60) merged (`d1a34ff`) after Chase approved it. The README's "Released tools" section is generated from `docs/releases.json` | Nothing left open. Every later release from private work adds its entry with `python -m kit releases add` (AGENTS.md rule 15); Progress Prize releases arrive as a `release-readme/<submission_id>` branch from the private exporter, for a PR into `main` | None | [`releases.json`](releases.json), [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60) |
| PHerc0841 Hecate caveat and README finding 1 like for like | **Done** 14 October: [PR #37](https://github.com/ChaseHendrick/Scrolls/pull/37) merged after Chase left the call to Claude. PHerc0841 is now called held out for every reader except possibly Hecate, and finding 1 compares v8in 0.738 with `ink_9um` 0.907 on the same bare crop. Its own 2026-10-09 prize snapshot was dropped, since the 2026-10-11 snapshot already records the PHerc. 343 award | Nothing left open | None | [`logs/2026-10-09-pherc0841-hecate.md`](logs/2026-10-09-pherc0841-hecate.md) |

## 12 October 2026: findings reported upstream

Three findings went public on ScrollPrize/villa from ChaseHendrick's account on 12 October, with the owner's go-ahead on each: [#2058](https://github.com/ScrollPrize/villa/issues/2058) (VC3D caches a transient S3 404 as a permanent empty chunk), its draft fix [#2060](https://github.com/ScrollPrize/villa/pull/2060), [#2059](https://github.com/ScrollPrize/villa/issues/2059) (the tracer does not hold an explicit seed) and a [comment on #1843](https://github.com/ScrollPrize/villa/issues/1843#issuecomment-6130119937) (a CT check of the PHerc1667 transform). They are README findings 12 and 13 and an update to finding 10; numbers, controls and limits are in [the log](logs/2026-10-12-upstream-reports.md), and the false-404 test and render receipts in [`evidence/2026-10-12-false-404/`](evidence/2026-10-12-false-404/README.md). The relay that replays S3's false 404 is `scripts/false404/fault_relay.py`. #2060 is a draft: a merge, review answers or further upstream posts each need the owner's word. Nothing else was released.

## 11 October 2026: public community guidance

The existing Apache-2.0 license is retained, with a project NOTICE and explicit
README scope for code versus third-party data and models. Contributor Covenant
2.1 uses the owner's approved public reporting address. Contribution, support
and security guidance, issue templates, a PR template and CODEOWNERS are in
standard GitHub locations. Private vulnerability reporting is enabled. These
community changes do not release private research or authorize compute.

## Correction 9 October 2026: PHerc0841 may not be held out from Hecate

The glossary, rulebook, `results.json` and several docstrings called PHerc0841 a scroll no candidate or released reader trained on. That holds for `ink_9um`, v8in, v8in-1447, d9v2 and Reader v2. It is not established for Hecate. Hecate's card names [`scrollprize/ink_canonical_2um`](https://huggingface.co/scrollprize/ink_canonical_2um) as its base model; that model's recipe is `new_canon_autoresearch_recipe`, and its committed trainer ([villa 94602c91](https://github.com/ScrollPrize/villa/blob/94602c91/ink-detection/train_resnet3d_3d_decoder.py), lines 200-207 and 292-293) lists w00 and both PHerc0841 auto_grown segments as training fragments, holding out only `l5_0_crop` (line 794) (Sourced fact). That the released weights came from that list is Interpretation. The team's published `new_canon_autoresearch_recipe` maps of PHerc0841, used by README findings 7 to 9, are therefore probably in-sample too. PHerc0841 stays the held-out test for the five readers above; Hecate's PHerc0841 numbers, and anything built on the team's PHerc0841 maps, carry this caveat. No number changed. Evidence and what stays unverified: [log](logs/2026-10-09-pherc0841-hecate.md). `tests/test_repo.py` now fails if a live file calls PHerc0841 held out from every reader without naming Hecate. The same day, README finding 1 was set like for like (v8in 0.738 against `ink_9um` 0.907, both inferred on the same bare w045 crop, instead of 0.914 from a whole-segment map) and its line on v8in's evaluation history was corrected from the v8in card; both edits went to Chase for review in [PR #37](https://github.com/ChaseHendrick/Scrolls/pull/37).

## Correction 8 October 2026: w045 is not held out from `ink_9um`

`ink_9um` trained on PHerc0139 w045's 2.399 um render, pooled to 9.6 um (segment pherc0139-w029 in its label dataset). Our w045 test scores the native 9.362 um render of the same surface, so for `ink_9um`, d9v2 and Reader v2 it is a cross-scan check on a training surface; it is still unseen by v8in. Use PHerc0841 for held-out claims. Wording is corrected across the live docs and code comments, the numbers are unchanged, and the owner chose to keep README Novel finding 1 with its correction until v8in's PHerc0841 crop scores replace it ([log](logs/2026-10-08-w045-not-held-out.md)).

## Before any long job: GPU work goes to Modal (user decision, 8 October 2026)

The user does not want hours spent on CPU for work a GPU does in minutes. Before starting a job, estimate its time. Anything that needs a GPU, or more than about an hour on CPU, runs on Modal. Claude's cloud sessions cannot reach Modal, even with the CLI installed, because their proxy does not carry Modal's gRPC traffic, so do not try to sign in from one. Write the exact run spec in [`compute/modal-specs/`](compute/modal-specs/README.md) and give the user a short prompt to paste into Codex, or commands to run on their own computer. The rule is AGENTS.md hard rule 11.

## Session 8 October 2026: d9v2 fine-tune sweep

Four short fine-tunes of d9v2 on public human labels (PHerc0841 and w045 excluded) were trained on Modal and all 24 checkpoints scored on the PHerc0841 w00 and ag896 selection crops ([log](logs/2026-10-08-d9v2-finetune-sweep.md)). None beats Reader v2: the best, mean 0.8616, sits between d9v2 (0.8612) and Reader v2 (0.8620), far from the 0.8820 promotion line, and ag405 stays unscored (Model output). Arm A (anchor 1.0, lr 2e-5) held its mean; B and C lost about 0.01 to 0.015; unanchored D fell to 0.8218 (Interpretation). Depth windows of the best checkpoint peaked at 0.8666 (z8-27), below d9v2 at the same window (0.8761).

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
