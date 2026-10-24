# Research integrity for Vesuvius Challenge claims

A guide, a checker and a Claude skill for keeping scroll results inside their evidence. Written 23 October 2026.

Most mistakes in this field are not invented numbers. They are claims that outrun their evidence: an ink score with
no control, a "held-out" segment that the model trained on, a map called a reading, a preregistration edited after
the result, a title cited from memory. Each looks reasonable and none announces itself. This page collects the
rules that catch them, shows real cases from this repository's own public record, and gives three ways to apply
the rules:

| Part | What it is | Where |
| --- | --- | --- |
| The rules | Eight rules with the Vesuvius failure each one prevents | [below](#the-rules) |
| The checker | `python -m kit integrity`: ink-score records, wording, preregistration order and citations; it plants faults and must catch each one before it reports anything | [tool page](tools/integrity.md) |
| The Claude skill | `vesuvius-integrity`, plain instructions for Claude Code; builds on the general [Research-Integrity](https://github.com/ChaseHendrick/Research-Integrity) skill | [`.claude/skills/vesuvius-integrity/SKILL.md`](../.claude/skills/vesuvius-integrity/SKILL.md) |

The general skill (release 1.5.0, Apache-2.0) came out of 80 documented failures in AI-assisted mathematical
research. This page adds the failure modes of scroll work. Claim labels follow [`NOVELTY.md`](NOVELTY.md); the
measurement standards behind each rule are in [`STANDARDS.md`](STANDARDS.md).

## Quick start

```bash
git clone --depth 1 https://github.com/ChaseHendrick/Scrolls.git && cd Scrolls
python3 -m kit integrity selftest                     # the planted faults, nothing else
python3 -m kit integrity text MY_POST.md              # wording, before you post
python3 -m kit integrity ink templates/ink-claim.json # one ink-score claim record
python3 -m kit integrity exposure                     # which reader trained on which test group
```

`MY_POST.md` is any Markdown or text file: a Discord draft, a PR description, a prize form. Standard library only,
Python 3.10 or newer; nothing is written and only `cite` uses the network. Exit 0 means no FAIL finding, 3 means at
least one, 1 means bad input or a planted fault that slipped through (then nothing is reported).

To install the skill in Claude Code for one repository, copy `.claude/skills/vesuvius-integrity/` into that
repository's `.claude/skills/`; for every project, into `~/.claude/skills/`. Install the general skill as its own
README says.

## The rules

### 1. An ink map is model output, not a reading

Three words stay apart ([`QUALITY.md`](QUALITY.md#docs)): ink detected (a model's map), letters visible (a person
sees letterforms), legible (papyrologists read them letter by letter). The prize page counts only the last: the
Grand Prize counts characters "legible ... on a letter-by-letter basis without papyrological interpolation", and it
warns that "the larger your model's window size, the easier it is for it to invent plausible letterforms instead of
recovering real ink" ([scrollprize.org/prizes](https://scrollprize.org/prizes), read 2026-10-23; Sourced fact).

Checker: `text-reading` fails "letters were found", "we read three lines", "the model found the title" and similar.

### 2. Every ink score carries its control

An AUC is reported beside the same reader's reverse-depth map on the same pixels ([`kit auc --control`](tools/auc.md)).
The reversed map reads the same CT, so it sees the same brightness; a model that reads ink in the depth direction
scores well above it. In the 30 controlled rows of this repository's `results.json` `results` the gap runs from 0.1015 to 0.5432. A gap under 0.10 is flagged; the 0.10 comes from [`kit/gate.py`](../kit/gate.py), whose docstring says
it was set after the committed gaps were seen, so it is a convention, not a frozen bar.

Checker: `ink-control` fails a score with no control, `ink-gap` fails a gap at or below 0 and warns under 0.10,
`ink-mask` fails pixels scored outside the supervision mask.

Real case. Run over all 31 AUC rows of this repository's `results.json`, the checker finds one row with no control:
`results/9`, `ink_9um` seed 42 on the w045 crop with a 64 px edge left out (0.9199), a row recorded to show that the
bare-crop and full-map scores are identical. Its control was never scored at that edge. The row stays, and the
checker keeps reporting it as uncontrolled.

### 3. Held out means held out from that reader

A segment tests a reader only if the reader's training data, and its starting weights' training data, left it out.
The Grand Prize says "No overlap between training and prediction regions" (prize page, read 2026-10-23). The
exposure table, from `results.json` `held_out_by_reader` with reasons and sources in `held_out`:

| Test group | Held out from | Not held out from |
| --- | --- | --- |
| PHerc0841 w00, ag896, ag405 | `ink_9um`, v8in, v8in-1447, d9v2, Reader v2 | Hecate |
| PHerc0139 w045 | v8in | `ink_9um`, d9v2, Reader v2, Hecate |

Checker: `ink-heldout` fails a record that calls an in-sample score held out and warns on any in-sample score;
`text-heldout` fails a sentence such as "ink_9um generalizes to unseen w045".

Real cases, both from this repository's public logs (Interpretation where the logs say so):

- From 7 to 8 October this repository used w045 as a generalization check for v8in, d9v2 and `ink_9um`. It is held out <!-- integrity: allow text-heldout -->
  only from v8in: the `ink_9um` label dataset holds the same surface under another name (`pherc0139-w029`), because annotation
  names "do not track the public segment w-numbering" ([log](logs/2026-10-08-w045-not-held-out.md)). No number
  changed; the wording around the numbers did.
- PHerc0841 is validation-only under Hecate's own published split rule, but Hecate's starting weights come from a
  trainer that lists all three PHerc0841 segments as training data, so Hecate's PHerc0841 scores are treated as
  possibly in-sample ([exposure log](logs/2026-10-16-reader-exposure.md)).

### 4. Compare like with like

Same window (whole segment or the 640 px densest-ink crop), same edge, same render: crop scores run higher than
whole-map ones, controls included. A difference between two readers needs the interval of the paired difference (a
block bootstrap, `kit auc --compare MAP --bootstrap N`), and one reader beats another in [`kit gate`](tools/gate.md)
only by at least 0.02 mean AUC. Seeds are fixed and reported, which the Grand Prize also requires.

Checker: `ink-compare` fails a comparison across windows or an interval that reaches 0, and warns on a margin under
0.02 or a comparison with no interval. The example record [`templates/ink-claim.json`](../templates/ink-claim.json)
(d9v2 against `ink_9um` on the PHerc0841 w00 crop) gets exactly that warning: no interval was measured.

### 5. Preregister before looking, and read held-out data once

Fix the readout rule (threshold and its source, control, decision, data) in a committed file before any map of the
test data exists, and change it only by a dated amendment at its end ([`STANDARDS.md`](STANDARDS.md#1-rules-every-measurement-follows)).
A held-out set read once is spent: report the result, pass or fail.

Checker: `prereg-order` reads git history. It fails a result committed before its preregistration or a
preregistration that lost lines after the result, warns on lines only added (check they are a dated amendment)
and on a result that arrived in the same commit (the history cannot show the order). `prereg-content` warns when no
control, decision rule or test data is named.

Real cases. The Ink Lens gate ([preregistration](prereg/2026-10-20-ink-lens-gate.md)) was committed at 19:40 UTC on
20 October, about 43 minutes before its result; the result commit appended 13 lines of results and changed none, so the
checker gives one WARN, which a reader confirms by reading the appended section. The Greek restoration
preregistration and its score arrived in one commit: the file says it is a public copy made after the result, of a
rule frozen elsewhere at about 22:22 UTC on 22 October. This repository's history alone cannot show that order, and
the checker says exactly that.

### 6. Numbers come from the run

Every public number is copied from a named field of the run output at the precision quoted. Checker: `ink-source`
reads the named field and fails a claimed number that does not round to it.

### 7. Possible findings stay private

"Do not make your discovery public until winning the prize is officially announced", and for First Letters "you
must not make your discovery public until the prize is officially announced" (prize page, read 2026-10-23). Maps,
crops and verdicts of prize-eligible scrolls that might show letters stay out of public posts, repositories and
logs. Checker: `text-disclosure` warns on "possible letters in column 3 of ..." and "letters are visible in the map
of scroll ...".

### 8. Cite what you opened

Copy ids and titles from the source. Checker: `cite` looks up every arXiv id in the files on arXiv's export API and
compares recorded titles. Real case: on 23 October it found that `docs/papers.json` gives arXiv 1602.08071 a
shortened title that arXiv does not use; the fix is [Scrolls PR #166](https://github.com/ChaseHendrick/Scrolls/pull/166).

## How the checker keeps itself honest

Every command first runs 27 planted faults, one or more per rule, through the same functions the real check uses,
and five clean controls that must pass. A planted fault must be caught as its own rule and severity; if one slips
through, the command exits 1 and reports nothing. The tests go one step further: they break the checker on purpose
(a zero gap bar, a zero margin, an empty pattern list, a negation that swallows everything, a number match that
always agrees) and require each break to make the selftest fail ([`tests/test_integrity.py`](../tests/test_integrity.py)).

The wording check was tuned on this repository's own 149 public Markdown files (README, `docs/`, `docs/tools/`,
`docs/logs/`, 23 October 2026). After the tuning it reports one WARN there, a false alarm ("the first artifact to rule
out" in [`tricks.md`](tricks.md)), and the test corpus of 13 invented overclaims is caught in full while 16 careful
sentences pass. Those numbers describe the files it was tuned on; on new text expect both misses and false alarms.

## What none of this does

A pass means the stated record survives these rules, not that the claim is true. The checker cannot see pixels that
were never scored, training data a model card does not list, or an overclaim written in other words. The exposure
table is this repository's reading of public sources, not an organizer statement. The rules do not replace the
review teams: "The review bar is deliberately high" (prize page, First Letters).
