# Handoff for the next repository session

Use plain sentences. Do not put U+2014 or U+2013 in new text. Inspect `git log` before quoting a SHA.

## Session 7 October 2026 (morning): where this stands as a contribution

**Nothing has been shared outside this repository yet.** The Challenge pays for work that is released and used, so none of the below counts until it is out. Nothing is posted, commented or submitted without the user's go-ahead.

User decisions (2026-10-07):

- **Progress Prize:** submit near the 31 Oct deadline, not before. The draft is [`contrib/progress-prize-2026-10-draft.md`](contrib/progress-prize-2026-10-draft.md); keep it updated, do not send it.
- **villa #1865 draft comment** ([`contrib/villa-1865-m1pro-comment.md`](contrib/villa-1865-m1pro-comment.md)): leave it alone.
- Keep researching and building in the meantime.

What is new and worth sharing once the user agrees:

1. **v8in on Apple Silicon, checked against the CPU.** On the user's M1 Pro, `scripts/mac-w045.sh` step 5 passed (`kit verify`, reverse as control; MPS map mean 0.2430, same as CPU). MPS about 1.1 to 1.3 s per tile against 25 s on the M1 Pro's CPU. Not seen published elsewhere.
2. **A labelled, controlled test of ink models** (`kit auc` with a reverse control, `kit rowscore`, one command per segment), with CPU references: w045 (seen scroll) 0.872 / 0.887; PHerc0841 (unseen scroll) 0.720 to 0.751, rows only on ag405. Numbers in [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md).
3. **An independent reproduction** of Bullo27's PHerc0841 calibration and his w045 row score.

Ways to contribute, cheapest first (propose each to the user; do none unasked):

- **Post the v8in on MPS result** on the v8in model's Hugging Face discussion page, after the w045 summary arrives.
- **v8in vs `ink_9um` on PHerc0841** (`SEGMENT=0841-w00 QUICK=1 bash scripts/mac-w045.sh`, then ag896 and ag405). A clear v8in win on an unseen scroll is news the community would act on; a loss is useful too.
- **Upstream the scoring tool:** villa has no simple command that scores an ink map against a segment's labels with a reverse control. A small tested PR there is the most "used by others" piece.
- **Progress Prize write-up** at the deadline.

Next: the user's `QUICK=1` w045 run (in progress at the time of writing) prints a summary to compare with the CPU reference (crop 0.914 / 0.910). Then the PHerc0841 quick runs. The user must `git pull` first: the Mac checkout predates `SEGMENT=` and resumable reruns.

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
