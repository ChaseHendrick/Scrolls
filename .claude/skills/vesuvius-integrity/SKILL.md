---
name: vesuvius-integrity
description: >
  Use when measuring, writing up or posting a Vesuvius Challenge result: an ink-detection score, a comparison of
  ink readers, a surface or fiber tracing check, a preregistration, a Discord or forum post, a villa PR, or a
  Progress Prize form. Keeps every claim inside its evidence: an ink map is model output, not a reading; every
  score carries its reverse-depth control on the same pixels; held-out means held out from that reader; numbers
  are copied from the run; readout rules are fixed before looking; possible findings on prize scrolls stay
  private until announced. Builds on the general Research-Integrity skill. Skip casual questions.
license: Apache-2.0
---

# Research integrity for Vesuvius Challenge claims

Release: 1.0.0 (2026-10-23)

## Goal

Keep every Vesuvius claim inside its evidence. This skill adds the failure modes of scroll work to the general
[Research-Integrity](https://github.com/ChaseHendrick/Research-Integrity) skill (release 1.5.0), whose rules 1 to 7
still apply: label how each claim is known, record what could not be searched, never infer novelty from a search,
every check must be able to fail, review adversarially, label review honestly, never bend a gate to fit a release.

Not claimed. Following these rules does not make a result true. Nothing here measures whether the rules reduce
errors. The exposure table below is one repository's reading of public sources on 23 October 2026, not an
organizer statement.

A program gate is optional (general skill, section 8). Where the Scrolls workbench is checked out,
`python -m kit integrity` checks ink-score records, wording, preregistration order and citations, and plants
faults it must catch before it reports anything. Use it only when the user asks for a program gate or the project
already runs it.

## 1. An ink map is model output, not a reading

Keep three words apart (Scrolls `docs/QUALITY.md`): **ink detected** (a model's map), **letters visible** (a person
sees letterforms in it), **legible** (papyrologists read them letter by letter). Only the last counts for the
prizes: the Grand Prize counts characters "legible ... on a letter-by-letter basis without papyrological
interpolation" (https://scrollprize.org/prizes, read 2026-10-23).

- Never write that letters, words or a title were found, read, revealed or recovered from a map. Write what the map
  shows ("ink-like strokes in rows about 3 mm apart") and who would have to read it.
- A larger model window makes invented letterforms easier, as the prize page warns. A text-like map needs a
  control that a hallucinating model would fail (blank papyrus, a held-out region, the reversed depth order).
- Do not attribute a transcription to a model. Papyrologists transcribe.

## 2. Every ink score carries its control

- Report the reverse-depth score of the same reader, on the same pixels, beside every forward score (`kit auc
  --control`). An AUC without it is uncontrolled, not passed.
- Report the gap. At or below 0 the map scores as well read backwards. Under 0.10 do not call it ink detection
  without more controls (Scrolls `kit/gate.py`, whose docstring says the 0.10 was set after the committed gaps were
  seen; treat it as a convention, not a frozen bar).
- Score inside the segment's supervision mask only: the labelers marked ink and non-ink there and nowhere else.
  Pixels the model never predicted (exactly 0) are left out and counted.
- Device agreement (CPU against MPS or CUDA) counts only if a deliberately wrong map is caught by the same
  comparison (`kit verify --control`). A surface or fiber check counts only if planted defects with a known answer
  are caught (`kit planted`).

## 3. Held out means held out from that reader

A labeled segment tests a reader only if that reader's training data, and its starting weights' training data,
left the segment out. Check before you write "held out", "unseen" or "generalizes". The Grand Prize rules: "No
overlap between training and prediction regions" (https://scrollprize.org/prizes, read 2026-10-23).

Snapshot of public sources, from Scrolls `docs/results.json` (`held_out`, `held_out_by_reader`; reasons and sources
there; exposure log `docs/logs/2026-10-16-reader-exposure.md`):

| Test group | Held out from | Not held out from |
| --- | --- | --- |
| PHerc0841 w00, ag896, ag405 | `ink_9um`, v8in, v8in-1447, d9v2, Reader v2 | Hecate (its base weights' trainer lists all three) |
| PHerc0139 w045 | v8in | `ink_9um` (trained on its 2.4 µm render, named w029 in the label dataset), d9v2 and Reader v2 (inherit it), Hecate |

- A score on a training surface is a pipeline or cross-scan check. Say so in the same sentence.
- Dataset names do not always match public segment names (w045 appears as w029 in the `ink_9um` label dataset). Match
  by source volume and segment id, not by name.
- An ensemble is held out only where every member is.

## 4. Compare like with like

- Same window (whole segment or the 640 px densest-ink crop), same edge left out, same render. Crop scores run
  higher than whole-map scores, controls included.
- A difference needs its own interval: a block bootstrap of the paired difference (`kit auc --compare
  --bootstrap`), not two separate intervals. If the interval reaches 0, the readers are not distinguishable.
- One run per setting says so. Seeds are fixed and reported, for training and inference (a Grand Prize rule).
- Count every variant tried, and report the ones not promoted.

## 5. Preregister before looking, read held-out data once

- Fix the readout rule (threshold and its source, control, decision, data) in a committed file before any map of
  the test data exists. Commit it before the result: git order is the evidence.
- Change a preregistration only by a dated amendment appended at its end. Never edit the rule above it.
- A held-out set is read once. After the read it is spent: report the result, pass or fail, and do not tune on it.
- Publish nulls and failures with their controls. A missing failure is selective reporting.

## 6. Numbers come from the run

- Copy every public number from a named field of the run output (`forward.auc` of `kit auc --json`), at the
  precision you quote. Say when you round.
- Do not take a number from a chart, a chat message, a rounded display or memory.
- Bind each number to the code and data version that produced it (commit, checkpoint hash, volume id).

## 7. Possible findings stay private

The prize page: "Do not make your discovery public until winning the prize is officially announced", and for First
Letters, "you must not make your discovery public until the prize is officially announced"
(https://scrollprize.org/prizes, read 2026-10-23).

- Maps, triage lists, crops and verdicts of prize-eligible scrolls that might show letters stay out of public repos,
  posts, PRs, CI logs and screenshots. Check eligibility on the prize page first.
- Public examples use public labeled data that is not prize-eligible, or synthetic data.

## 8. Label sources

| Label | Meaning |
| --- | --- |
| Sourced fact | An organizer page, official repository or paper, with its URL and the date read |
| Organizer result | A reading announced by the Vesuvius Challenge after papyrological review |
| Community report | Someone else's run, model card or post, cited to its own page; not checked by you |
| Model output | A map or score from a model; never a reading |
| Interpretation | Your reading of the evidence |
| Untested idea | No run and no source |

A Discord message is a Community report at best; quote it only with the author's consent.

## Records

```
Ink claim: <reader> on <segment>, <window>, <edge>
Forward AUC: <value>   Reverse AUC: <value>   Gap: <value>
Mask: supervision      Pixels: <ink> ink, <background> background
Held out from this reader: yes | no | possibly not   Source: <file or URL>
Number taken from: <file>:<field>   Code: <commit>   Weights: <hash>
Interval: <method>, <low> to <high>   Runs: <n>, seeds <list>
Not claimed: <what this does not show>
```

`python -m kit integrity ink` reads the same record as JSON.

## Before you post, open a PR or send a prize form

- [ ] No sentence says letters were found or read; maps are called model output.
- [ ] Every ink score has its reverse-depth control on the same pixels, and the gap is stated.
- [ ] Every "held out" names the reader, and the exposure table supports it.
- [ ] Comparisons use the same window, edge and render, with an interval of the difference.
- [ ] The preregistration was committed before the result; amendments are dated and appended.
- [ ] Every number names the run field it came from; seeds are stated.
- [ ] Failures and nulls from the same work are reported.
- [ ] Nothing shows a possible finding on a prize-eligible scroll.
- [ ] Every citation was opened; titles and ids are copied, not reconstructed.
- [ ] AI help is disclosed by tool and role; an AI reading is not called a review.

## Phrases to avoid, and what to write instead

| Avoid | Write |
| --- | --- |
| "Letters found in the new map" | "The map shows ink-like strokes in rows; nobody has read them" |
| "We read the title" | "Papyrologists read ... (link to the organizer post)" or nothing |
| "Generalizes to held-out w045" | "On w045, a training surface for this reader, it scored ..." |
| "AUC 0.92" (alone) | "AUC 0.92 forward, 0.48 reversed, same pixels, supervision mask" |
| "Beats reader B" | "0.03 above B, 95 % interval of the difference 0.01 to 0.05, same crop" |
| "State of the art" | "Highest of the N readers we scored on PHerc0841 crops (list)" |
| "Verified on GPU" | "Matches the CPU map within 2 gray levels; a shifted map fails the same check" |
| "Independently reviewed" | "Read by a separate AI session in this project; not an outside review" |
