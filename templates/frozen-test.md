# Frozen test: TITLE, the question in one line

<!-- Template for the frozen-test protocol, docs/standards/frozen-test.md. Copy it to a file such as
prereg/YYYY-MM-DD-SLUG.md, fill every CAPITAL placeholder, delete these comments and commit it as a Draft.
Freeze it in a commit that changes only this file: the status line reads Frozen and section 10's hash blocks are
filled. Nothing above "Amendments" changes after that commit. The review pin and the result live outside this file (see the note at the end). -->

**Status: Draft** (written YYYY-MM-DD, before any output of this test on its test data exists). It becomes frozen at the commit titled "SLUG: freeze", which changes this line to **Status: Frozen** and fills section 10. Changes after that go in dated amendments at the end.

**What had been seen when this was written.** MAPS, SCORES, LABELS AND MODEL OUTPUTS LOOKED AT, AND ON WHICH DATA.

**Authors.** WHO WROTE AND COMMITTED THIS TEST (people, and agent sessions by their session link).

## 1. Question

QUESTION, and the answers the run can give.

## 2. Prior records and prior work

RECORDS AND PAPERS SEARCHED, WHERE AND WITH WHICH TERMS; the nearest earlier work. What this test does that they did not: ONE LINE.

## 3. Never touched

SCROLLS, SEGMENTS AND REGIONS THIS TEST MUST NOT READ, and the code or check that refuses them.

## 4. Data and its history

- Test sites: EACH SITE WITH ITS EXTENT (scroll, segment, or a box in a named scan frame) AND LINE OF WORK.
- Labels or truth: FILES, SHA-256 AND SOURCE.
- Registry check: RESULT OF CHECKING EACH SITE AGAINST THE SPENT AND RESERVED REGISTRY, WITH A LINK.
- Training exposure: FOR EACH COMPARED MODEL, WHETHER ITS TRAINING DATA MEETS ANY TEST SITE, WITH THE SOURCE.
- Claim level: held out | development (reads before: N, WHICH).

## 5. Method

MODEL, SETTINGS AND STEPS, FIXED ENOUGH THAT SOMEONE ELSE COULD RUN THEM.

## 6. Measures, bars and verdict rule

- Measures: METRIC, SCORER FILE AND COMMIT.
- Bars, each with its source outside the test data: BAR = VALUE (SOURCE).
- VOID if: CONDITIONS, at least one of them a control floor.
- PASS if: ALL OF THESE HOLD.
- Otherwise FAIL.

## 7. Controls (each can fail; a missing value fails)

CONTROL, ITS FLOOR, AND THE DEVELOPMENT RECORD SHOWING IT CATCHES A KNOWN-BAD INPUT.

## 8. Pass-first checks (development or spent data only)

```passfirst
ceiling: pass|fail: REFERENCE, ITS SCORE AND INTERVAL, THE BAR, THE MARGIN; RECORD
controls: pass|fail: EVIDENCE
noise: pass|fail: EVIDENCE
power: pass|fail: EVIDENCE
smoke: pass|fail|pending: RECORD OF A RUN OF THE EXACT CODE
```

## 9. Arms tried before this test

```arms
log: PATH TO THE APPEND-ONLY LOG
tried: N
distinct: N
failed: N
sha256: SHA-256 OVER THE COUNTED LOG LINES
```

## 10. Code and hashes

The run executes exactly these files and refuses any other repository file.

```code-sha256 readout
SHA256  PATH/TO/SCORER.py
SHA256  PATH/TO/LABELS.json
```

```code-sha256 plumbing
SHA256  PATH/TO/LAUNCHER.py
```

Deviations to plumbing files, only before any output exists: `YYYY-MM-DD  NEW_SHA256  PATH  REASON`.

## 11. Limits, stated before the result

LIMITS.

## 12. Rerun

Attempt: 1 | N, with the earlier freezes, their results and the technical reason or new preregistered seeds or sites.

## Amendments

None.

<!-- Kept outside this file, so its hash stays fixed after the freeze:

The review pin, in a verdict log or as a PR review, written by someone not listed under Authors:
  {"pr": N, "commit": "FULL FREEZING COMMIT HASH", "verdict": "GO | GO-WITH-NOTES | NO-GO",
   "reviewer": "WHO (session link for an agent)", "utc": "YYYY-MM-DDTHH:MM:SSZ",
   "note": "verdict rule can give PASS, FAIL and VOID; bar sources; sites not spent; arms block matches log; hashes match"}

The result, in the run's record and the report:
  verdict PASS | FAIL | VOID, the record's path and SHA-256, the named numbers as the record writes them,
  the arms count from section 9, the claim level from section 4, and the link to the sites marked spent. -->
