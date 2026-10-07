# Handoff for the next repository session

Use plain sentences. Do not put U+2014 or U+2013 in new text. Inspect `git log` before quoting a SHA.

## Session 7 October 2026: cloud setup, PR repairs and surface correction

The checkout already contains merged PRs #1 to #5. Earlier instructions to merge those branches are stale. The user authorized subagents, fixing the open PRs, community research and real papyrus validation. Microtuning is deferred by the user; this cloud instance has neither CUDA nor MPS, and has no connection to the Mac. Do not start training or rent compute.

[scan-status.md](scan-status.md) now separates our processing from community CT availability: completed controls, partial jobs and the planned 81-mesh atlas queue; 45 scanned samples in the versioned official catalogue and 23 distinct prize volumes. Future CT acquisitions are not publicly documented by these sources. The user requested both views. The October submission draft must name Chase Hendrick. Existing cloud CPUs only; no paid compute.

The README findings are now below the quick start and repository information, at the user's request. Findings about trace gaps, benchmark area and collation are qualified as observational or untested where appropriate. The cloud-partial log now reports Reader v2's high-pass controls alongside pixel AUC and marks stride-mismatched v8in controls provisional.

Implemented in commit `cc880c6`: `kit surfacefix prepare/apply`, documented in [surfacefix.md](surfacefix.md). It proposes bounded normal offsets, accepts them only with frozen geometric matches, selection and held-back subsets, matched controls and topology checks, and writes a new corrected surface plus uncertain-region flags. Sources remain intact. 131 tests passed, including 20 surfacefix tests. Real-input rejection tests also completed; successful real correction and accuracy are not established. A combined accepted surface must be rerendered before claiming improvement.

PR repairs preserve historical metrics. #6 fixes independent-sheet calibration, boundary coverage and unknown-label reporting; #7 and #10 use matched strides for future controls and label legacy comparisons provisional; #8 corrects window and Reader v2 interpretations. #9 reports the actual ag405 plan's partial coverage and matched/provisional controls. A separate `v8in-ag896` branch also received partial-status reporting improvements. All five open PR heads were updated and verified by Git read: #6 `814563f`, #7 `c4a5ead`, #8 `a295168`, #9 `97d26e7`, #10 `d288c58`. No PR was merged and nothing was submitted upstream.

CPU development setup: Python 3.12 with map dependencies in `.venv`; no services are required. Setup instructions are saved in the environment draft, which still requires user review/publication. Public S3 mesh and metadata downloads work through approved network commands. Default urllib requests can fail even when an approved command works. GitHub Git read/push works; the GitHub API remains denied. Hugging Face metadata is readable, but its checkpoint CDN/Xet requests were denied. Official d9v2 weights downloaded from the GitHub release, passed checksum and strict CPU load checks, and generated the twelve real maps. Do not confuse a saved allowlist draft with a live runtime change.

Real validation completed on public PHerc0841: 12 actual CT-rendered d9v2 maps, four evaluable regions, zero corrections accepted, 16 flags. Eight full-search translated-reference nulls accepted zero corrections, with evaluable coverage in each. Tangential and excessive edits were rejected; output geometry, holes and metadata were preserved. The frozen patch has zero supervision, so no accuracy or successful recovery claim is supported. See [real validation](logs/2026-10-07-real-surfacefix-validation.md). An additional 82-chunk PHerc0139 reconstruction pilot passed four shift-recovery controls but failed a shared-translation assumption by 18.724 um on held-back CT. No phase ink maps were run; see [reconstruction tests](logs/2026-10-07-reconstruction-tests.md).

Community demand and reusable patterns from GENChase/Undeciphered-Texts are recorded in [the research log](logs/2026-10-07-community-needs.md). Existing Lasagna snapping must be the comparison for future correction evaluation. Worldwide novelty and a groundbreaking result are not established.

## Session 7 October 2026 (end of day): read this first

**The user had about 8 % of weekly usage left when this was written. Keep the next session small: one task at a time, no fleets of agents, no multi-hour jobs without asking.**

Done today (all on branch `claude/gallant-pasteur-b1y2si`, not yet merged; open a PR to `main` when the user says so):

- README findings 5 to 9 (new): PHerc0841 w00 and ag896 are one sheet traced twice; raw CT brightness is not ink (AUC at most 0.58 per layer); ink readings of one sheet agree only within about 50 um of trace offset; the PHerc0841 benchmark is 3.4 cm² with +-0.01 to +-0.04 AUC sampling noise; collation of two traces as a label-free check. Log: [`logs/2026-10-07-overlap-and-baseline.md`](logs/2026-10-07-overlap-and-baseline.md).
- New checks in `kit` (tested in `tests/test_overlap.py`): `kit overlap MESH_A MESH_B --voxel-um 9.366 [--labels-a DIR --labels-b DIR]` (same sheet?), `kit collate MESH_A MESH_B MAP_A MAP_B --voxel-um 9.366 [--control-a C --control-b C] [--box Y0 Y1 X0 X1]` (do two traces' maps agree, against a control?), `kit auc ... --bootstrap 300 [--compare MAP2]` (95 % interval, paired difference). Checked on the real PHerc0841 data: they reproduce the log's numbers.
- Progress Prize draft rewritten to lead with these findings ([`contrib/progress-prize-2026-10-draft.md`](contrib/progress-prize-2026-10-draft.md)). Still: submit near 31 Oct, only with the user's go-ahead.
- Name removed from the README findings heading (user request).

Still running or unfinished:

- Partial cloud results (w00 only) are in [`logs/2026-10-07-cloud-partial.md`](logs/2026-10-07-cloud-partial.md): Reader v2 has by far the highest reverse (0.729) and shuffle (0.568) controls, so much of its lead is not depth-ordered ink; check on ag405 first. v8in-1447 equals base v8in on w00 (0.838).

- Cloud jobs `v8in1447-w00/ag896/ag405`, `tricks`, `thresholds` may have pushed results to `origin/claude/gallant-pasteur-b1y2si-<job>` (`scripts/experiments/2026-10-07-cloud/<job>/results.json` and `notes.md`). `git fetch origin` and look; fold any results into `docs/results.json`, `docs/tricks.md` and the README (v8in-1447 on PHerc0841 is unpublished). `finetune` finished without running the smoke test (permission denied for Hub code); its notes say w062 has no public labels and most of the 385 GB pre-training set is target scrolls: update `plans/2026-10-07-training.md` from them.
- w045's raw-brightness baseline ran out of memory; not redone.

What to do next, in order (cheapest first):

1. Merge this branch (PR) so `main` has findings 5 to 9 and the new checks.
2. Fold the cloud job results (above). No new compute.
3. On the Mac, when the user wants: `bash scripts/mac-phase0.sh` (now a reproduction of Bullo27 plus the device check), then the preregistered atlas run `scripts/mac-atlas-v8in.sh`. Target outputs stay private.
4. Use `kit collate` on overlapping automatic meshes of a target scroll as a candidate filter (private outputs); preregister the rule first (`docs/prereg/`).
5. Before 31 Oct: finish the Progress Prize draft; ask the user about a small villa PR upstreaming `kit auc --bootstrap/--compare` and `kit overlap`.

## Session 7 October 2026 (afternoon): cloud jobs, two new findings, prior work found

**The user is short on usage (weekly limit warning).** Keep runs short and agents few; ask before starting anything that takes hours.

New findings (README 5 and 6; [log](logs/2026-10-07-overlap-and-baseline.md)): PHerc0841's w00 and ag896 are the same papyrus traced twice (meshes 81 um apart, labels agree, Dice 0.83), so PHerc0841 has two independent labelled surfaces, not three; raw CT brightness alone scores at most 0.58 AUC per layer on PHerc0841; the team's ink maps of the two traces of that sheet agree only where the traces are within about 50 um (README 7); the PHerc0841 benchmark is 3.4 cm² of labelled papyrus with +-0.01 to +-0.04 AUC of sampling noise per segment (README 8).

Prior work found by a web scan (same log, section 3): **v8in on PHerc0841 is already published** (Bullo27, [v8in-12gb](https://github.com/Bullo27/v8in-12gb), 2026-10-01: 0.837, 0.807, 0.810, ahead of `ink_9um`), so step A.4 on the Mac is now a reproduction and device check, not a novel result; window averaging on PHerc0841 has related prior work (README finding 4 now cites it).

Cloud jobs (spec: [`scripts/experiments/2026-10-07-cloud/README.md`](../scripts/experiments/2026-10-07-cloud/README.md)), each in its own container, pushing to `claude/gallant-pasteur-b1y2si-<job>`: `v8in1447-w00`, `v8in1447-ag896`, `v8in1447-ag405` (stride 42 forward, 64 reverse, ensembles with d9v2), `tricks` (handoff B.1 and lead d, PHerc0841 crops only), `thresholds` (lead c, published null rules on known text, row score by area), `finetune` (B.2). Stopped to save usage: the base v8in jobs (a reproduction now) and the v8in depth-window jobs (lead a; about 3 hours of CPU each). Fold each finished job's `results.json` and `notes.md` into `docs/results.json`, `docs/tricks.md`, the README findings and a dated log, then delete nothing from the job branches (they are the record).

Next leads, cheapest first: (a) score `ink_9um` on the shared w00/ag896 sheet from both traces with one label set carried across by the meshes (does an 80 um trace offset change AUC?); (b) report PHerc0841 results per independent surface (w00/ag896 sheet, ag405) rather than as a three-segment mean; (c) the window sensitivity on whole segments against crops, to reconcile with villa #1867.

## Session 7 October 2026 (midday): an agent runs everything from here

**The user does not want to type or paste commands.** Copying commands into the terminal was too much (user, 2026-10-07). Whoever picks this up runs the steps themselves and reports results in plain words. PR [ChaseHendrick/Scrolls#2](https://github.com/ChaseHendrick/Scrolls/pull/2) was merged into `main` at the user's request.

### A. On the user's Mac (needs an agent running on the Mac, such as Claude Code in Terminal: only the Mac has the GPU)

1. Find the checkout: `find ~ -maxdepth 4 -path "*/scripts/mac-w045.sh"`, then `cd` to the folder above `scripts/`. Not `~/scrolls-work`: that is the data folder.
2. Make sure no old run is going: `ps aux | grep -E "v8in_run|ink_detection" | grep -v grep`. An fp16 run of `SEGMENT=0841-w00` was going at 6.2 s per tile; if it is still alive, stop it (it is safe: maps are recomputed, the lock is taken over).
3. `git checkout main && git pull`.
4. `bash scripts/mac-phase0.sh` and let it run (about 2 hours: v8in, then `v8in-1447`, on the three PHerc0841 crops; fp32; resumable; keeps the Mac awake; notification at the end). Do not set `V8IN_FP16` (5x slower on the M1 Pro).
5. Then `python3 -m kit gate` (Gate A table). Record the Mac numbers: each `~/scrolls-work/0841-*/results/auc_v8in*.json` becomes a row in `docs/results.json` (window `crop`, `inner_px` 64, `map_from` `bare-crop`, device `mps`, reader `v8in d89166b` or `v8in-1447 2bf9f42`); `kit gate` must report "match" for the `ink_9um` check. Update the README's "Novel findings" (v8in on PHerc0841 is unpublished), `docs/tricks.md` if relevant, `docs/contrib/progress-prize-2026-10-draft.md`, and this handoff. Commit on a new branch and open a PR; tell the user the Gate A line in one sentence.

### B. In a cloud session (no GPU needed)

1. **Tricks results.** A job left running in the 7 Oct container scores every map and pushes `docs/logs/2026-10-07-tricks-results.md` to branch `claude/jolly-rubin-n55p5t` (restarted from `main`). If that file exists, open a PR for it, fold its table into `docs/tricks.md` ("Measured here") and `docs/results.json`, and delete it. If it does not exist, the container was reclaimed before the runs ended: rebuild with `scripts/experiments/2026-10-07-tricks/` (its README lists the layout) and score with `score.py`. Measured so far (w00 crop only): soup plus 4 z windows lifts `ink_9um` 0.806 to 0.847; z windows or mirror TTA lift d9v2 0.899 to 0.920; mixing d9v2 with the weaker `ink_9um` lowers it to 0.868; depth-shuffled input drops all readers to 0.48 to 0.50 (a cleaner null than reverse).
2. **Fine-tune smoke test** (v8in's PHerc1447 loop on CPU, 2 train and 2 val batches): its status is in the same results file; to redo it, `scripts/experiments/2026-10-07-tricks/finetune_smoke.sh`. It only shows that the loop runs; it matters right before renting a GPU, which needs the user's budget decision.
3. **Gate A** (after A.5): if d9v2 or an ensemble beats v8in by 0.02 or more, write an atlas script variant on villa's inference and a second preregistration (same readout rule) before any map; the user's Mac then runs it like step A.4.
4. Open items from the plan: idea 1 depends on `v8in-1447`'s PHerc0841 number (step A.4); ideas 2 and 3 are in `plans/2026-10-07-training.md`. Progress Prize draft: submit near 31 Oct, only with the user's go-ahead.

### Novel checks done after the merge (README findings 3 and 4; [log](logs/2026-10-07-novel-checks.md))

Training-segment thresholds miss about 96 % of real ink on PHerc0841; averaging four depth windows matches the label-chosen best window (0.820 vs 0.819); depth-shuffled input scores at or below reversed input. These commits are on `claude/jolly-rubin-n55p5t` after the merge and need a new PR to reach `main` (with the tricks results file, B.1).

Next leads for novel results, cheapest first: (a) the same window test for v8in (it reads 24 of 28 layers; `kit layers --start/--count` moves its window), on the Mac; (b) the shuffle control for v8in (`kit layers --shuffle 20261007`), on the Mac; (c) a threshold calibrated on PHerc0841 instead of a training segment, then re-run other published null rules (nerln, bnleft) on PHerc0841 to measure what they would have caught; (d) whether window averaging also helps the letter-scale score, not just pixel AUC.

### New tools this session

`kit gate` (Gate A), `kit ensemble` (map averaging, rank mean across models), `kit hpscore` (Scheirer's letter-scale score), `kit shuffle` and `kit layers --shuffle` (depth-shuffle control), `scripts/soup.py` (checkpoint soup within one run, refuses mixed seeds; rebuilds Nieuwlaar's `soup42_last4` bit-identically), `scripts/mac-phase0.sh` (the Phase 0 queue), `tests/test_repo.py` (repo checks in CI). Community tricks with sources: [`tricks.md`](tricks.md).

## Session 7 October 2026 (late morning): the plan the user agreed

User decisions (2026-10-07): do steps 1 to 5 below; **no Hugging Face or forum posting**. The longer view, steps 6 onwards, is in [`plans/roadmap.md`](plans/roadmap.md).

1. The user pastes the `SEGMENT=0841-w00` summary (v8in, QUICK; the fp16 run was 6.2 s per tile against 1.1 to 1.2 in fp32, so it was to be restarted without `V8IN_FP16`); compare with the bars on the same crop with a 64 px edge left out: d9v2 0.8994, `ink_9um` seed 42 0.8061 (the summary's `ink_9um` line should match 0.8061 exactly).
2. The same for `0841-ag896` and `0841-ag405` (bars: d9v2 0.8230 / 0.8319, `ink_9um` 0.6594 / 0.7838), one run at a time.
3. `MODEL=v8in-1447` on the three crops: Youssef's PHerc1447 fine-tune, idea 1 with no training.
4. Choose the reader for the targets: the v8in atlas run stays preregistered; if d9v2 stays clearly ahead, propose a second preregistered run with d9v2 on PHerc0813 and 0358 (TAUIL ran it on 0826 only).
5. Training prep: stage data, CPU smoke test of the fine-tune loop, then ask the user about GPU budget.

Mac runs are guarded by a shared lock (one GPU job at a time) after two concurrent runs swapped the M1 Pro to 56 s per tile.

**Automation (2026-10-07):** steps 1 to 3 are one command, `bash scripts/mac-phase0.sh` (resumable; skips scored jobs; keeps the Mac awake; notifies at the end), and step 4's Gate A table is `python -m kit gate` (reads `docs/results.json` and `~/scrolls-work/*/results/auc_*.json`, applies the 0.02 rule, checks the Mac's `ink_9um` against the CPU bar). `mac-w045.sh` drops fp16 by itself when it is slower, and writes `provenance_v8in1447.json` and `summary_v8in1447.txt` for the fine-tune so it no longer overwrites the base model's record. CI runs `tests/test_repo.py` (scripts parse, bash 3.2, house style, docs JSON, documented commands).

## Session 7 October 2026 (morning, later): training our own reader, all three ideas

The user decided (2026-10-07) to pursue all three training ideas in [`plans/2026-10-07-training.md`](plans/2026-10-07-training.md): (1) train on PHerc1447, the scroll whose text was just found, at the First Letters scan protocol; (2) learn from the team's 1 µm ink maps instead of the 2.4 µm ones every public fine-tune used; (3) self-supervised pre-training on the eligible scans themselves. The plan fixes the test (PHerc0841, labels, reverse control) and the bar (Hecate 0.855, d9v2 0.828, Reader v2 0.824, `ink_9um` about 0.74) before any training.

State: nothing trained. Downloaded and checked: d9v2 (sha256 matches TAUIL's) and Reader v2 (matches its card), both load with `weights_only=True`. v8in's `finetune_loo_w062.py` reads plain layer folders and labels, takes a starting checkpoint and has `--smoke-test`, so each idea mostly needs its data staged. A CPU comparison of `ink_9um` and d9v2 on the four crops (and Reader v2 on PHerc0841's) is running here.

Next: (a) the user's v8in PHerc0841 number decides the base model; (b) score Youssef's released PHerc1447 fine-tune on PHerc0841 (no training); (c) stage data and smoke-test here; (d) renting a GPU needs the user's decision on provider and budget.

## Session 7 October 2026 (morning): where this stands as a contribution

**Nothing has been shared outside this repository yet.** The Challenge pays for work that is released and used, so none of the below counts until it is out. Nothing is posted, commented or submitted without the user's go-ahead.

User decisions (2026-10-07):

- **Progress Prize:** submit near the 31 Oct deadline, not before. The draft is [`contrib/progress-prize-2026-10-draft.md`](contrib/progress-prize-2026-10-draft.md); keep it updated, do not send it.
- **villa #1865 draft comment** ([`contrib/villa-1865-m1pro-comment.md`](contrib/villa-1865-m1pro-comment.md)): leave it alone.
- Keep researching and building in the meantime.

What is new and worth sharing once the user agrees:

1. **v8in on Apple Silicon, checked against the CPU** on the user's M1 Pro (`scripts/mac-w045.sh` step 5 passed; MPS about 1.1 to 1.3 s per tile against 25 s on the M1 Pro's CPU). **Not a first:** afraazali42 published v8in MPS vs CPU on an M3 Max on 2026-10-03. Ours is a second-chip confirmation; mention it as that, if at all.
2. **A labelled, controlled test of ink models** (`kit auc` with a reverse control, `kit rowscore`, one command per segment), with CPU references: w045 (seen scroll) 0.872 / 0.887; PHerc0841 (unseen scroll) 0.720 to 0.751, rows only on ag405. Numbers in [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md).
3. **An independent reproduction** of Bullo27's PHerc0841 calibration and his w045 row score.

Ways to contribute, cheapest first (propose each to the user; do none unasked):

- ~~Post on Hugging Face~~: **the user declined (2026-10-07). Do not suggest Hugging Face or forum posts.**
- **v8in on TAUIL's held-out benchmark segments.** TAUIL-Abd-Elilah's benchmark (8 labelled segments incl. PHerc0841) scores `ink_9um`, d9v2 and Reader v2 but not v8in. Adding v8in to the same segments is the unpublished piece. Consider also running d9v2 (released, loads like `ink_9um`) in `mac-w045.sh` as a third model.
- **v8in vs `ink_9um` on PHerc0841** (`SEGMENT=0841-w00 QUICK=1 bash scripts/mac-w045.sh`, then ag896 and ag405). A clear v8in win on an unseen scroll is news the community would act on; a loss is useful too.
- **Upstream the scoring tool:** villa has no simple command that scores an ink map against a segment's labels with a reverse control. A small tested PR there is the most "used by others" piece.
- **Progress Prize write-up** at the deadline.

**w045 result (user's M1 Pro, 2026-10-07):** on the crop, `ink_9um` 0.9136 / 0.9098 (equal to the CPU reference), v8in 0.7382 (reversed 0.3269). v8in reads ink but trails `ink_9um` on this seen-scroll test, which favours `ink_9um`. Details in the log.

Next: `git pull`, then `SEGMENT=0841-w00 QUICK=1 bash scripts/mac-w045.sh`, then `0841-ag896` and `0841-ag405`. Other segments reuse w045's device check, so each run is about 20 min of `ink_9um` plus about 30 min of v8in. That decides whether v8in is the better reader on an unseen scroll, and therefore whether the atlas run should use it.

## Session 7 October 2026 (late night): first target run, preregistered

The user chose the target set and the readout rule (2026-10-07): v8in on all 81 public automatic meshes of PHerc0813, 0358 and 0826 (rodriguescarson's atlas renders, which include his 5 held-back meshes), with the rule in [`prereg/2026-10-07-v8in-atlas.md`](prereg/2026-10-07-v8in-atlas.md). One variable changes from published reads of these surfaces: the model. `scripts/mac-atlas-v8in.sh` runs it on the Mac after `scripts/mac-w045.sh` passes; tested here end to end on fake meshes built from w045 (PHerc0139), never on target data. No target map has been made in this repository's sessions.

Next: the user runs `mac-w045.sh`, then `mac-atlas-v8in.sh`. Target results stay private: do not commit triage numbers, maps or verdicts on target meshes before the user decides (WORKFLOW.md 3b). After that, hand-fix whichever surfaces the run points to.

## Session 7 October 2026 (night): the w045 check is one command on the Mac

`bash scripts/mac-w045.sh` (see [`mac.md`](mac.md)) runs `ink_9um` seeds 42 and 43 and v8in on PHerc0139 w045 on the Mac GPU, checks v8in CPU vs MPS on a crop first, and prints AUC against w045's published labels (reverse as control) and row scores. It ran end to end here in CPU smoke mode; numbers and caveats in [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md). New: `kit layers`, `kit auc`, `scripts/v8in_run.py` (fp16 on MPS, opt-in). 71 tests.

Next: the user runs `scripts/mac-w045.sh` and pastes the summary. If v8in's forward AUC on w045 is clearly above `ink_9um`'s, v8in is the reader for the PHerc0826 / 0358 / 0813 / 1545 attempt. If MPS fails the crop check, report it (that is itself useful on the v8in model page).

## Session 7 October 2026 (evening): community scan, rowscore, new models

Read 16 winners' and contributors' repositories, Hugging Face, and villa's history and branches. Notes: [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md).

What changed the plan:

- **v8in** (YoussefMoNader/ink-8um-v8in, 2026-09-28) is newer than every published First Letters null, and no eligible-scroll run of it was found. Use it alongside `ink_9um`. **Hecate** (team, 2026-09-15) was already run over 340 automatic meshes by rodriguescarson, who holds back 5 screen-passing meshes.
- PHerc0139 **w045 is held out from both** models (`kit fetch w045`). Run it first with both models; that is the generalization baseline.
- The organizers stopped asking for sheet-switch detectors (#1937, 2026-09-30). Do not build another checker for a Progress Prize; a hand-fixed surface or tracing that avoids switches is what they want.

Added: `kit rowscore` (Bullo27's score, matches the original to float rounding), `kit plan` step 1b (w045), surface QA (windcheck, tifxyz-doctor), v8in commands, `--flip-normals` on the target render. 51 tests.

Next, in order:

1. On the M1 Pro: `kit fetch w045`; `ink_9um` both directions; `kit rowscore` (expect about 73 to 148 forward per Bullo27). Then v8in on w045 with `--device mps` (needs the zarr exported as 24 layer TIFFs; write that step and test it).
2. Preregister (`kit run init`), then hand-trace and fix one surface on PHerc0826, 0358, 0813 or 1545 in VC3D; check it with windcheck; render with `--flip-normals`; read with v8in and `ink_9um`, both directions.
3. By 31 Oct: Progress Prize submission (new form on the prizes page).

## Next steps (set 7 October 2026)

Done: the M1 Pro runs villa ink inference on MPS via PR #1865, verified against CPU (see [`logs/2026-10-07-w035-cpu.md`](logs/2026-10-07-w035-cpu.md)). The draft #1865 comment is in [`contrib/villa-1865-m1pro-comment.md`](contrib/villa-1865-m1pro-comment.md); the user posts it.

Next 2 to 3 weeks, the real attempt:

1. **Generalization test.** Run the model on held-out segment PHerc0139 w045 instead of w035. If text rows are readable there, the model finds ink it was not trained on. That is the honest baseline the w035 run could not give (w035's letters are memorized training labels).
2. **One real First Letters attempt** on PHerc0826, 0358, 0813 or 1545 (the scan atlas ranks these most like scrolls where ink was found).
   - The step that matters is tracing the papyrus surface in VC3D and **fixing sheet jumps by hand**. Every published null used automatic surfaces that wander between layers; hand-fixed surfaces are the gap nobody has filled.
   - Write down what counts as ink before looking (`python -m kit run init`), then run both seeds and both directions.
   - If letters appear: tell no one publicly and follow [`WORKFLOW.md`](WORKFLOW.md).

By 31 Oct: submit to the October Progress Prize (the #1865 verification, `scripts/mac-verify.sh`, and the First Letters write-up, null or not).

## Session 7 October 2026 (later): kit verify and the Mac runbook

Added `kit verify` (two ink maps, tolerance, a control that must be caught, verdicts pass / pass-uncontrolled / fail / control-not-caught), `kit run record` (command lines and SHA-256), and a CI job with numpy, tifffile and imagecodecs. 35 tests. `kit verify` was run on the real published w035 2.4 µm ink map (462 Mpx): correct verdicts, 36 s, 2.25 GB peak.

Corrections found: PR #1812 changes `ink-detection/optimized_inference`, not the tutorial's `vesuvius.ink_detection`; for the tutorial path the PR is #1865 (four lines, `get_accelerator()`). All runbook flags were checked against `infer.py` on `main` and on `pr-1865`.

Next: the user runs the runbook in [`mac.md`](mac.md) on the M1 Pro. If the verdicts pass, ask nerln (the #1865 author) before posting the JSON on the PR.

## Session 7 October 2026: M1 Pro path and repo transfer

The user's machine is an Apple M1 Pro. Added `doctor` Apple Silicon handling (warn, not fail; memory check; VC3D.app tool path), `plan --mac`, [`mac.md`](mac.md), and [`logs/2026-10-07-mac-and-repos.md`](logs/2026-10-07-mac-and-repos.md). 25 tests pass.

Key facts: stock villa ink inference is CUDA or CPU. MPS support is in open PRs #1865 and #1812; do not write a duplicate. Lasagna has MPS (#1639). The VC3D stable build crashes opening PHerc0826 on macOS (#1910); use the latest build.

From Chase's repositories, the GENChase Apple GPU verification method and the Research-Integrity skill transfer. Nothing else does in a meaningful way; see the log.

Next: the user runs `python -m kit doctor` and the w035 control on the Mac (CPU), then on the #1865 branch (MPS), and compares.

## Session 6 October 2026: repository set up

Work is on branch `claude/youthful-heisenberg-gdjttc`. The repository went from a one-line README to a workbench modeled on [Undeciphered-Texts](https://github.com/ChaseHendrick/Undeciphered-Texts): README, governance docs, research docs, and the `kit/` package with 22 passing tests.

What exists:

- `kit/data/prizes-2026-10-06.json`: prize snapshot from villa commit `e0bbb8b40a2d`, with all 13 Grand Prize and 22 First Letters volumes resolved to their S3 Zarr names by listing the public bucket.
- `kit plan`: official tutorial commands per scroll. Not executed here (no GPU in this container).
- `kit run`: local ledger with readout hash and a disclosure gate.
- Docs: start-here, prizes, pipeline, state-of-play, compute, engine, external, sources, workflow.

What was not done:

- No pipeline step was run. Nothing here has touched a CT volume beyond listing bucket prefixes.
- scrollprize.org and the Substack were blocked from this session. Prize facts come from the website source in villa. The Substack First Letters workflow post was not read in full.

Next steps, in order:

1. User runs `python -m kit doctor` on their machine and joins the Discord.
2. Run the PHerc0139 w035 control end to end.
3. Pick one variable to test on one eligible scroll (see `docs/state-of-play.md`); preregister; run; record.
4. Look for a small villa issue (good first issue or help wanted) to fix for an October Progress Prize. Deadline 31 Oct 2026, 11:59pm Pacific.
5. Grow `kit/` per the list in `docs/engine.md`, with tests.
