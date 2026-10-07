# Roadmap (set 2026-10-07)

The long view, phase by phase: goal, steps, who does what, time and cost, the gate that decides the next phase, and risks. The handoff ([`../HANDOFF.md`](../HANDOFF.md)) holds the current session's detail. Dates are targets, not promises.

**Standing decisions (user, 2026-10-07):** no Hugging Face or forum posting; Progress Prize submitted near its deadline; target results stay private until a prize is announced ([`../WORKFLOW.md`](../WORKFLOW.md) 3b); nothing is rented, posted or submitted without the user's go-ahead.

**Who can do what.** The user's M1 Pro: GPU inference (v8in about 1 s per tile, `ink_9um` about 11 min per whole segment), VC3D (a desktop app, so only the user can trace). This container: CPU only (v8in about 7 s per tile; `ink_9um` and d9v2 on a 640 px crop in about 50 s), downloads, scoring, code, tests, write-ups. A rented GPU: training, and anything above a few thousand v8in tiles.

## Where we stand

| Reader | w045 crop (seen scroll for `ink_9um`) | PHerc0841 crops, w00 / ag896 / ag405 (unseen by all) |
| --- | --- | --- |
| `ink_9um` seed 42 | 0.914 | 0.806 / 0.659 / 0.784 |
| d9v2 (TAUIL) | 0.860 | **0.899 / 0.823 / 0.832** |
| v8in | 0.738 | running on the Mac |
| Hecate, Reader v2 | (Reader v2 trained on w045) | 0.855, 0.824 on whole PHerc0841 (Reader v2 card) |

PHerc0841 crop numbers leave a 64 px edge out (`kit auc --inner 64`). Published First Letters reads of eligible scrolls: all null, all on automatic surfaces.

## Phase 0: which reader is best on an unseen scroll? (this week)

Goal: an honest ranking of released readers on PHerc0841, the only labelled scroll no candidate trained on.

1. v8in on 0841 w00, then ag896, then ag405 (Mac, about 20 min each with `QUICK=1`, one at a time; fp16 is about 5x slower on the M1 Pro, so leave it off). Each summary's `ink_9um` seed 42 line must match the CPU bar to four decimals.
2. Youssef's PHerc1447 fine-tune on the same three crops (`MODEL=v8in-1447`, Mac, about 20 min each).
3. Reader v2 on the three 0841 crops (here, CPU, about 2 min each). Hecate optional: it needs villa's Hecate inference path and aviad12g found its eligible-scroll positives depth-order independent.
4. An ensemble (mean of the best two or three maps) on the same crops (here, seconds).

Steps 1 and 2 run as one queue: `bash scripts/mac-phase0.sh`.

**Gate A** (`python -m kit gate` applies it). Rank by mean forward AUC over the three crops, with the reverse AUC well below it on each. The winner reads the targets in Phase 1. A reader beats another only by at least 0.02 mean AUC (three crops are not many).

Risks: three crops of one scroll is a small sample; PHerc0841 is 113 keV, like half the targets but not the 116 keV half (PHerc1447's protocol), so idea 1 below matters.

## Phase 1: screen the targets with the best reader (weeks 1 to 2)

Goal: a private, preregistered read of every public automatic surface on PHerc0813, 0358 and 0826 with the best reader, so hand-fixing starts where it is most likely to pay.

1. The preregistered v8in atlas run (`scripts/mac-atlas-v8in.sh`, 81 meshes, overnight; [prereg](../prereg/2026-10-07-v8in-atlas.md)). It runs whatever Gate A says: a v8in null is a result too.
2. If Gate A's winner is not v8in: a second preregistration (same readout rule, new reader), committed before any map, then the same 81 meshes. d9v2 and Reader v2 load like `ink_9um`, so this needs an atlas script variant on villa's inference (here: write and test; Mac: run).
3. The user looks at the maps the rule lists (top 10 per direction plus the five meshes rodriguescarson held back) and records `null` or `candidate` per run.

**Gate B.** Any candidate: go to Phase 4 on it, privately. No candidate: Phase 2 starts on the highest-triage meshes anyway.

Risks: the atlas meshes are automatic (within about 5 voxels of the sheet at best, pscamillo); a null here says little about the scrolls. Hecate-rank ordering is only a reading order.

## Phase 2: hand-fixed surfaces (weeks 2 to 6; the user's hours)

Goal: the step no published read has done. Trace or fix a surface by hand so it stays on one sheet, then read it with the best reader.

1. **Learn VC3D on the Mac** with the latest build (the stable build crashes opening PHerc0826, villa #1910). Tutorial: scrollprize.org/tutorial_VC3D.
2. **Calibrate on PHerc0841 first.** Trace a region of 0841 w00 yourself, render it (`vc_render_tifxyz --flip-normals`), read it, and score it against the labels. Compare with the team's own surface over the same region. This measures our tracing before it matters.
3. **QA every traced surface** before reading it: windcheck (self-intersections), tifxyz-doctor (format and topology), and a look at cross-sections for sheet jumps.
4. **Targets:** the meshes Phase 1 ranks highest, then PHerc1545 (no public meshes at all: a first surface there is new ground).
5. Read each fixed surface with the Gate A reader (and the runner-up), both directions, under a preregistered rule; record provenance.

**Gate C.** The 0841 calibration surface scores within 0.03 AUC of the team's surface on the same region. If not, improve tracing before spending hours on targets.

Time: hours of human work per few cm²; the reads are minutes on the Mac. Risks: a learning curve; a hand-fixed sheet can still drift; the compressed core is the hardest.

## Phase 3: our own reader (weeks 3 to 8, in parallel with Phase 2)

Goal: a reader that beats Gate A's winner on PHerc0841. Details: [`2026-10-07-training.md`](2026-10-07-training.md).

1. **Prep, here, free:** stage PHerc1447's three windings in the fine-tune layout; inventory the team's 1.1 µm teacher maps and align them to 9 µm canvases; smoke-test v8in's `finetune_loo_w062.py --smoke-test` on CPU.
2. **Idea 1:** fine-tune on all three PHerc1447 windings (the 116 keV, 8.64 µm protocol of half the First Letters scrolls). Base model: Gate A's best v8in-family or `ink_9um`-family model.
3. **Idea 2:** a 9 µm student from 1.1 µm teacher maps, PHerc0841 and the held-out set excluded.
4. **Idea 3:** self-supervised pre-training on the eligible scans (nestorvfx sheets), only if ideas 1 and 2 show the scan protocol matters.

Compute: d9v2 took 1.3 to 2 hours on one RTX 3090; budget a few hours of a rented 24 GB GPU per run, roughly 1 to 3 USD an hour. Needs the user's go-ahead on provider and budget.

**Gate D (promotion gate, from Undeciphered-Texts).** Select among trained variants on PHerc0841 w00 and ag896 only; score the single winner once on ag405, the audit segment, after the choice is frozen. Promote it only if it beats the best released reader by at least 0.02 mean AUC on the selection pair and does not fall below it on ag405, with reverse AUC well below forward everywhere, and it was never shown PHerc0841 or the held-out segments. Report the number of variants tried. Promoted readers re-run Phase 1 and read Phase 2's surfaces. Details: [`2026-10-07-training.md`](2026-10-07-training.md).

Risks: overfitting to PHerc0841 by trying many variants (count every variant tried, report all); teacher maps carry their own errors; licences: Challenge data is CC BY-NC 4.0, so trained weights are shared under those terms.

## Phase 4: if something looks like letters

1. Mark the run `candidate` in the ledger; tell no one publicly; commit nothing about it.
2. Re-run the rule's checks: second stride, the other direction, a second reader, the render beside the map, the known artifacts (hole rims, onion rings, render seams).
3. Commit the provenance digest (it reveals nothing) to fix the date of the record.
4. Prepare the First Letters submission privately per the prize page: 10 legible letters in one 4 cm² area, with the method; follow WORKFLOW 3b.

## Phase 5: Progress Prizes, every month

- **31 Oct 2026:** submit the v8in evaluation (w045 and PHerc0841, with controls), the tools, and the atlas result if null, from [`../contrib/progress-prize-2026-10-draft.md`](../contrib/progress-prize-2026-10-draft.md). Near the deadline.
- **Later months:** whatever Phases 2 and 3 produce that others can use (a hand-tracing calibration protocol, a trained reader that wins Gate D, the 1 µm teacher pipeline). Prizes favour work that is released and used.

## Timeline

| When | Phase | Done when |
| --- | --- | --- |
| Week of 7 Oct | 0 | Gate A decided |
| By 21 Oct | 1 | Atlas run(s) recorded null or candidate |
| By 31 Oct | 5 | October submission sent |
| Oct to mid Nov | 2 | Gate C passed; first hand-fixed target surfaces read |
| Oct to Nov | 3 | Ideas 1 and 2 trained and scored (Gate D) |
| Nov 2026 to Jun 2027 | 2, 3, 4 | More surfaces, better readers; any candidate handled privately |
| 25 Jun 2027 | | First Letters and 2027 Grand Prize deadline |

## Records kept for attribution

`python -m kit compute ~/scrolls-work --watts 30` turns those records into a time ledger (GENChase-style; energy is an estimate). Every Mac run writes `provenance.json` and a digest: operator (git user.name), machine, UTC times, Scrolls and villa commits, model and input and output hashes. Preregistrations are committed before their maps exist. The ledger (`experiments/`, local) holds readout-rule hashes and verdicts. Keep the provenance files; commit digests when a date needs fixing.
