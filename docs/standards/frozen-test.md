# Frozen-test protocol for Vesuvius Challenge claims

**Status: Draft 0.1, 26 November 2026.** A short community spec for claims other people can trust: "method A beats method B on held-out data", "this tracer keeps winding order on a new scroll", "this reader generalizes". It writes down the rules this repository runs its own tests under, so any team can follow them, check someone else's claim against them, or point to them in a submission. It is not an organizer rule and no prize requires it.

The protocol has six core rules. A claim is trusted when a reader can check, from public records alone, that:

1. the readout rule was **preregistered** before any result on the test data existed;
2. the test was **frozen**: the rule and the exact code it runs were hashed in one commit before launch;
3. an **independent reviewer pinned** a verdict to that frozen commit before launch;
4. the **reviewer was never the author**;
5. **spent seeds and truth stayed out** of the test: nothing scored had been looked at, tuned on, selected on or trained on before;
6. the **arms tried** before the tested one were counted and reported.

Four supporting rules (section 2, rules 7 to 10) cover controls, reporting every outcome, matching the claim to the data's history, and searching prior work before a novelty claim. A one-page checklist is in [section 4](#4-checklist), and a fill-in template is [`templates/frozen-test.md`](../../templates/frozen-test.md).

An ink map is model output, not a reading. Nothing in this protocol turns a model's output into a reading of a scroll; it only makes a test result checkable.

## 1. Terms

| Term | Meaning in this spec |
| --- | --- |
| Preregistration | A committed text file that fixes the question, data, method, measures, bars, controls and verdict rule of one test before any output on the test data exists. |
| Development data | Data the author may look at, tune on and choose on. Results on it are development results, never held-out results. |
| Test data | The sites (scrolls, segments, regions, synthetic seeds or label sets) a frozen test scores. Read once. |
| Freeze, freezing commit | The commit that sets the preregistration's status to Frozen and lists the SHA-256 of every file the run executes. It changes nothing else. |
| Readout set, plumbing set | Hashed files that decide the result (labels, splits, scoring code, bars, model configuration) and files that only move data (container image, I/O, retries). A readout file never changes under a freeze; a plumbing file may be fixed by a dated, disclosed deviation before any output exists. |
| Review pin | A reviewer's verdict (GO, GO-WITH-NOTES or NO-GO) recorded with the full commit hash it covered, the reviewer's identity, the time and an optional file scope. |
| Author | Every person or agent session that wrote or committed to the test's preregistration or code. An AI subagent counts as its parent session. |
| Arm | One candidate tried: a model, setting, recipe, gate, threshold or seed. |
| Spent | A site that any earlier test, tuning step, selection, bar setting, training run or viewing has read. Spent data can carry development results only. |
| Reserved | A site set aside for a named future test, so no one reads it first. |
| Verdict | PASS, FAIL or VOID, computed by the frozen rule. VOID means a control or validity condition failed, so the run says nothing about the method. |

## 2. Rules

"Must" marks a requirement; "should" marks strong advice.

### Rule 1. Preregister before looking

The preregistration must be committed before any map, score or model output on the test data exists, and must state:

- the question, and the answers the run can give;
- what had been seen when it was written (maps, scores, labels looked at);
- the never-touched list: scrolls, segments and regions the test must not read, and the code that refuses them;
- the data: splits, labels and their SHA-256 and source;
- the method, fixed enough that someone else could run it;
- the measures and bars, with the source of every bar (a bar must not be fitted to the data it scores);
- the controls (rule 7);
- the verdict rule: which conditions make the run VOID, which make it PASS, and that anything else is FAIL;
- the limits, written before the result.

After the freeze, nothing above the Amendments section changes. An amendment is dated and says what had been seen when it was written.

### Rule 2. Freeze the test

The freezing commit must change only the preregistration: its status line reads Frozen and its hash blocks list every repository file the run executes, split into a readout set and a plumbing set. A folder is never listed; each file is. The run should refuse to launch when a listed file differs from its hash, and should refuse to load any repository file that is not listed (an import made inside a function is the usual leak). Files the run opens without importing (data, shell scripts, binaries) are listed by hand.

A freeze ends when its run is collected. A rerun of a spent freeze launches from the freezing commit itself, never from the current branch.

### Rule 3. Pin an independent review before launch

Before any launch, a reviewer who meets rule 4 must read the frozen preregistration and its code and record a review pin at the frozen commit. The run may launch only under a GO or GO-WITH-NOTES pin at that commit. A pin covers a later head of the same change only when the change's own patch is unchanged: merging the base branch in does not void a pin, but any edit to the change does. A NO-GO pin is published like any other.

The reviewer checks at least: the verdict rule can produce each of PASS, FAIL and VOID; each bar's source is real and outside the test data; the test sites are not spent (rule 5); the arms block matches its log (rule 6); and the hashes match the files.

### Rule 4. The reviewer is never the author

A review counts as independent only when the reviewer is not among the test's authors (section 1). For AI agents this is checked by session identity, not by name: a subagent of the authoring session is the author, and a review whose commits carry the same session trailer as the reviewed change is refused. The author's own pre-submission review is useful and should be done, but it never counts as the independent review. Whoever merges the pin into the record is neither the author nor the pin's writer.

### Rule 5. Keep spent seeds and truth out of tests

- Keep one registry of reserved and spent sites, with each site's extent (a scroll, segment, or a box in a named scan frame), the line of work it was read for (ink, surface, tracing and so on) and what read it.
- Before the freeze, check every test site against the registry and against the training data of every model the test compares. A clash refuses the freeze; it is not waived to save time.
- A synthetic seed used during development is spent, like a real site.
- Truth (labels, human traces, organizer answers) used to choose, tune or set a bar is spent for every later held-out claim.
- New labeled data should be reserved on arrival: register it as reserved for a test before anyone opens it.
- A registry that records a site by name only cannot prove two regions apart; record extents.

### Rule 6. Report the arms tried

Every arm tried on development data before the tested one was chosen must be logged, one line per try, failures and refusals included. The preregistration carries a block with the count tried, the count of distinct arms, the count that failed and a SHA-256 over the counted log lines, so a reviewer can check that nothing was dropped or edited. The result is reported beside that count: "PASS, 1 arm frozen after 14 tried on development data" reads very differently from "PASS".

Searching many arms on development data is fine and often the fastest route. Choosing the winner on the test data is not.

### Rule 7. Every check must be able to fail

Each test must have at least one control that a wrong result would fail, and the verdict rule must make the run VOID when a control misses its floor. Each control should be shown, on development data, to catch a known-bad input (shifted, swapped, depth-reversed or sham). For ink AUC the reverse-depth map scored on the same pixels is the standard control; for device agreement, a deliberately wrong map that must be caught.

### Rule 8. Report every outcome, once

FAIL and VOID results are published with the same prominence as PASS. A spent test stays spent. A frozen test may be rerun only after a technical break, or after a noise-limited near miss on new seeds or sites preregistered first; each rerun is a new, disclosed freeze that states its attempt number and the earlier result, and is never tuned on the spent result.

### Rule 9. Match the claim to the data's history

A result is called held out only when the rule 5 check is clean for every scored site. Otherwise it is a development result and says so, with the count of earlier reads ("development, on truth read 3 times before"). Words such as "fresh", "unseen", "new" and "held out" follow the record, not memory.

### Rule 10. Search prior records and prior work before a novelty claim

Before building a test, search your own records for the same idea under other names, and say in the preregistration what this test does that the earlier ones did not. Before any public claim that a result is new, search other fields' names for the same object, across several source kinds with at least one full-text search, read the nearest documents in full, and cite the nearest prior work. No hit is not proof of novelty. A case from this repository: a math note's 2D closed form turned out to be a worked example in a July 2026 statistics paper on circular expectiles that our own search terms had missed, so the published note credits it and offers only the parts not found elsewhere ([note](../manuscripts/finite-window-axis/README.md)).

## 3. The protocol, step by step

| Step | What happens | What it leaves behind |
| --- | --- | --- |
| 0. Search | Prior records and prior work (rule 10). | A list of what was read and how this test differs. |
| 1. Draft | Fill in the template as a Draft. | A committed Draft preregistration. |
| 2. Pass-first checks | On development or spent data only: an oracle or best honest reference clears the bars through the exact scoring path (a ceiling check, so a bar is not above what can be reached); noise sits below the margin; every control meets its floors; a size or power check; a smoke run of the exact code. A failed check means redesign, not launch. Bars do not move after a result. | Evidence files cited in the preregistration. |
| 3. Sites | Check every test site against the registry and the compared models' training data (rule 5); reserve them. | Registry entries naming this test. |
| 4. Freeze | The freezing commit (rule 2). | A commit hash and the hash list. |
| 5. Review | An independent reviewer pins GO, GO-WITH-NOTES or NO-GO at the frozen commit (rules 3 and 4). | A review pin. |
| 6. Run | Launch once, under the hash check. A second launch of the same freeze is refused unless it is a disclosed rerun (rule 8). | The run's record, with its own SHA-256. |
| 7. Collect | Compute the verdict by the frozen rule. When the rule only compares named numbers in the record with fixed bars, a code replay that reproduces the verdict and every written file byte for byte may stand in for a second review; anything else goes back to a reviewer. Mark the sites spent. | The verdict, the collected record, the spent registry entries. |
| 8. Report | State the fields in the checklist below, with links. | A public report a reader can check. |

## 4. Checklist

Copy this into a report, PR description or submission and tick each line with a link.

```text
[ ] Preregistration committed before any test output     link: COMMIT
[ ] What had been seen when it was written is stated
[ ] Never-touched list and the code that refuses it
[ ] Every bar has a source outside the test data
[ ] Verdict rule can give PASS, FAIL and VOID
[ ] At least one control, shown to catch a known-bad input on development data
[ ] Ceiling check: a reference clears the bars through the exact scorer
[ ] Test sites checked against the spent and reserved registry: clean
[ ] Test sites checked against every compared model's training data: clean
[ ] Arms tried: N tried, N distinct, N failed, log SHA-256 SHA
[ ] Freezing commit changes only the preregistration      link: COMMIT
[ ] Every executed file hashed (readout and plumbing sets)
[ ] Independent review pin at the frozen commit: GO       reviewer: WHO
[ ] Reviewer is not an author (session identity checked for AI agents)
[ ] Run launched once under the hash check                record SHA-256: SHA
[ ] Verdict computed by the frozen rule: PASS | FAIL | VOID
[ ] Claim level: held out | development (reads before: N)
[ ] Attempt number and earlier results, if a rerun
[ ] Prior records and prior work searched; nearest work cited
[ ] Sites marked spent after collection
```

## 5. How this repository runs it

Some of these checks are public `kit` commands; the rest run in our private tooling and are described here by what they do. The protocol does not need any of them: `git`, `sha256sum`, a second person and a text file of verdicts are enough.

| Rule | Public command or record | What our own tooling adds |
| --- | --- | --- |
| 1, 2 | `python -m kit freeze add`, `check`, `collect` ([page](../tools/freeze.md)): registers a freeze with every executed file's SHA-256 at the freezing commit; `freeze.launch_check` and `freeze.executed_check` refuse a changed or unlisted file at launch and inside the run. `python -m kit freeze prereg PATH` checks a preregistration's readout and plumbing hash blocks against the files, counting dated deviation lines. `python -m kit integrity` (check `prereg-order`) reads git history and fails a result committed before its preregistration or a preregistration that lost lines after it. | The repository tests refuse a preregistration past Draft that lacks its known-mistakes answers and its pass-first block; every launch runs inside a run-once guard that refuses a second launch with the same id. |
| 3, 4 | `python -m kit reviewpin record PR SHA VERDICT` ties a verdict to the full commit, and `reviewpin delta` says whether it still covers the head by comparing the change's own patch. | A review queue hands each request to a reviewer session that is not among the request's authors (read from the commits' session trailers), and the merge step refuses a pin whose commits share a session with the reviewed change. A separate session checks and lands each pin. |
| 5, 9 | | A registry of reserved and spent sites with extents in scan frames, checked before every freeze; a use log (view, score, tune, select, bar, train) that refuses a held-out claim on any site it meets (being added 26 November 2026); labeled data reserved on arrival. |
| 6 | | An append-only candidate log per search helper and a check that the preregistration's arms block matches it by count and hash. |
| 7, 8 | `python -m kit verify --control`, `python -m kit auc --control`; [`integrity.md`](../integrity.md) and `python -m kit integrity` for wording and order. | VOID and FAIL results feed a lessons list that later preregistrations must answer before their freeze. |
| 10 | | A search of our own records before a test is built, and a check that refuses a public novelty claim unless a prior-art record shows several phrasings, at least four searches over three source kinds with one full-text kind, three documents read and the nearest prior work named (being added 26 November 2026). |

## 6. What the protocol cannot do

- It cannot make a wrong method right. It shows that a result was not shaped after the fact; the method can still be poor.
- A review is only as good as the reviewer. A pin records that a review happened at a commit, not that it was thorough.
- A registry only knows what was written into it. A site read but never registered looks fresh.
- It does not judge legibility. A PASS on an ink measure is a test outcome under a frozen rule, not a reading.

## 7. Changes to this spec

This draft changes by pull request. Each change gets a dated line here.

- 26 November 2026: Draft 0.1.
