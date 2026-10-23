# integrity: research integrity checks for Vesuvius Challenge claims

Checks Vesuvius claims before they go out: ink scores need their reverse-depth control and a held-out status from that reader, wording must not call model output a reading, preregistrations must precede results, citations must match arXiv; it plants faults first.

| Field | Value |
| --- | --- |
| Id | `integrity` |
| Status | Current |
| Kind | kit command,skill |
| Area | Scoring and controls |
| Run | `python -m kit integrity` |
| Code | `kit/integrity.py`, `.claude/skills/vesuvius-integrity/`, `templates/ink-claim.json`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_integrity.py` |
| Needs | Python 3.10 or newer, standard library only. `git` on `PATH` and a clone with its history for `prereg`. Network access to export.arxiv.org for `cite` (not with `--offline`). The exposure table in `docs/results.json` (`held_out_by_reader`, `segments`), or another file in that form given with `--results` |
| Runs on | Any CPU. On this repository (4-core cloud container, 23 Oct 2026): `results` over 31 AUC rows 0.26 s; `text` over 149 Markdown files 1.5 s; `selftest` alone well under 1 s; `cite` over 8 arXiv ids one request plus a 3.5 s pause |
| Network | None, except `cite`: the arXiv export API (export.arxiv.org), 20 ids a request, 3.5 s between requests, backing off on HTTP 429 |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed to run it. What you post after it passes still needs whatever go-ahead posting needs |
| Released | Public `main` from the change that adds it (23 Oct 2026) |
| Guide | [Research integrity for Vesuvius Challenge claims](../integrity.md): the rules, real cases and how to install the Claude skill |
| Checked | 2026-10-23 against commit `b849745` plus this tool |

## What it does

Most mistakes in scroll work are claims that outrun their evidence: an ink score reported without its control, a "held-out" segment the model trained on, a map called a reading, a preregistration edited after the result, a title cited from memory. This tool turns the rules of the [Research-Integrity](https://github.com/ChaseHendrick/Research-Integrity) skill (release 1.5.0) and this repository's [standards](../STANDARDS.md) into checks that run on a claim before it is posted, put in a PR or sent with a prize form.

It has five checks and three helpers. `ink` reads one claim record per file (or `kit auc --json` output) and checks the control, the forward minus reverse gap, the reader's held-out status on that segment, the scored pixels, the source of the number and any "beats" comparison. `results` runs every AUC row of `results.json` through the same checks. `text` reads Markdown or plain text for overclaim wording, tuned to Vesuvius: letters "found" or "read" from a map, "held out" or "unseen" for a reader that trained on the named segment, novelty and ranking words, review claims, certainty words, and possible letters described in public. `prereg` reads git history to check that a preregistration was committed before its result files and was only appended to afterwards. `cite` checks that every arXiv id exists and that recorded titles match arXiv's. `rules` lists every rule, `exposure` prints the held-out table, and `selftest` runs only the planted faults.

Every command first runs the planted faults: 27 wrong inputs, at least one per rule, each of which must be caught as its own rule and severity by the same functions the real check uses, and five clean controls that must pass. If any fails, the command exits 1 and prints no result, so a broken checker cannot report a pass (skill rules 4 and 8).

A finding is FAIL or WARN. FAIL is a claim the evidence does not support as written; WARN is something a person must read (an in-sample score that is labeled as such, an amendment after a result, a novelty word). What it does not do: a pass means the record survives these rules, not that the claim is true. It cannot see pixels that were never scored, training data a model card does not list, or an overclaim in other words. Its output is a list of findings about text and records, not a judgment of any map.

## When to use it

- Before posting a result on Discord or the forum, opening a villa PR or sending a Progress Prize form: `text` on the draft.
- When reporting an ink score: write the claim record and run `ink`; use `exposure` before you write "held out".
- When a result arrives under a preregistration: `prereg` with the result files.
- When a notes file or `papers.json` gains citations: `cite`.
- In an agent session, with the `vesuvius-integrity` Claude skill (`.claude/skills/vesuvius-integrity/`), which states the same rules as instructions.

Do not use it:

- To compute an AUC: use [auc](auc.md); this tool reads its output.
- To compare two readers' maps: use `kit auc --compare --bootstrap` ([auc](auc.md)), then check the claim here.
- To trace README numbers to their sources: use [claimcheck](claimcheck.md).
- To check device agreement or surface tools: use [verify](verify.md) (`--control`) and [planted](planted.md).
- To decide whether a map shows letters: that is for papyrologists and the review teams.

## Quick start

```bash
python -m kit integrity ink templates/ink-claim.json
python -m kit integrity text docs/integrity.md --json
```

The first command printed (23 Oct 2026, this branch):

```
selftest: 27 of 27 planted faults caught, 5 clean controls passed
claims: 1
WARN ink-compare templates/ink-claim.json: no interval for the difference: noise not measured
0 FAIL, 1 WARN
```

and exited 0: the record (d9v2 on the PHerc0841 w00 crop, 0.8994 forward against 0.5855 reversed, copied from `results.27.auc_as_stored`) passes every rule, and its claim to beat `ink_9um` seed 42 on the same crop has no interval of the difference. Exit 3 with a FAIL line means the claim does not hold as written.

## Checks and controls

The control is the planted-fault selftest that runs before every command; `python -m kit integrity selftest` runs it alone. Its 27 plants include an ink score with no control, a reverse score above the forward one, a held-out claim for Hecate on PHerc0841, a comparison across windows, a number its run file does not hold, "we read three lines", "ink_9um generalizes to unseen w045", a result committed before its preregistration, a preregistration edited after its result, and an arXiv id arXiv does not return. The five clean controls are a held-out claim record, a careful paragraph, a correct commit order, a title that differs only in case and punctuation, and a sourced number at lower precision.

The tests check that the selftest has power: nine deliberate breaks of the checker (gap bar 0, margin 0, no reading patterns, no novelty patterns, no held-out words, a negation that matches everything, a number match that always agrees, a title comparison that always agrees, no content rules) must each make the selftest fail. A wording corpus of 13 invented overclaims must be caught and 16 careful sentences must pass.

Results on this repository (23 Oct 2026, this branch; checks of records and text, not of maps):

| Run | Result |
| --- | --- |
| `results` over 31 AUC rows of `docs/results.json` | 1 FAIL: `results/9` (`ink_9um` seed 42, w045 crop, 64 px edge, 0.9199) has no control; 9 WARN: rows of readers on w045, which they trained on |
| `text` over 149 Markdown files (README, `docs/`, `docs/tools/`, `docs/logs/`) | 1 WARN, a false alarm ("the first artifact to rule out", `docs/tricks.md`); the wording rules were tuned on these files |
| `prereg docs/prereg/2026-10-20-ink-lens-gate.md --result scripts/experiments/2026-10-20-ink-lens-gate/results.json` | 1 WARN: 13 lines appended in the result commit (a results section) |
| `prereg docs/prereg/2026-10-22-greek-restoration.md --result docs/evidence/greek-restoration-20261022/score.json` | 1 WARN: same commit, so this history cannot show the order |
| `cite docs/papers.json docs/logs/2026-10-07-literature.md` | 8 ids, 1 FAIL: the recorded title of arXiv 1602.08071 is not arXiv's ([PR #166](https://github.com/ChaseHendrick/Scrolls/pull/166) fixes it) |

Claim label: Interpretation, for every finding: it is the tool's reading of a record or a sentence against stated rules, to be read by a person.

## Commands and options

### `python -m kit integrity rules`

```
usage: python -m kit integrity rules [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | print one JSON object instead of lines |

### `python -m kit integrity exposure`

```
usage: python -m kit integrity exposure [-h] [--results RESULTS] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--results RESULTS` | `docs/results.json` | results.json with held_out_by_reader and segments (the exposure table) |
| `--json` | off | print one JSON object instead of lines |

### `python -m kit integrity ink`

```
usage: python -m kit integrity ink [-h] [--reader READER] [--segment SEGMENT]
                                   [--results RESULTS] [--json] [--strict]
                                   claims [claims ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `claims` | required | claim files (JSON): claim records or kit auc --json output |
| `--reader READER` | none | the reader, for kit auc output that does not name it |
| `--segment SEGMENT` | none | the segment key or test group, for kit auc output that does not name it |
| `--results RESULTS` | `docs/results.json` | results.json with held_out_by_reader and segments (the exposure table) |
| `--json` | off | print one JSON object instead of lines |
| `--strict` | off | exit 3 on a WARN finding too |

### `python -m kit integrity results`

```
usage: python -m kit integrity results [-h] [--results RESULTS] [--json]
                                       [--strict]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--results RESULTS` | `docs/results.json` | results.json with held_out_by_reader and segments (the exposure table) |
| `--json` | off | print one JSON object instead of lines |
| `--strict` | off | exit 3 on a WARN finding too |

### `python -m kit integrity text`

```
usage: python -m kit integrity text [-h] [--results RESULTS] [--json]
                                    [--strict]
                                    files [files ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `files` | required | Markdown or text files to read |
| `--results RESULTS` | `docs/results.json` | results.json with held_out_by_reader and segments (the exposure table) |
| `--json` | off | print one JSON object instead of lines |
| `--strict` | off | exit 3 on a WARN finding too |

### `python -m kit integrity prereg`

```
usage: python -m kit integrity prereg [-h] --result RESULT [--json] [--strict]
                                      prereg
```

| Option | Default | Meaning |
| --- | --- | --- |
| `prereg` | required | the preregistration, a path inside this git checkout |
| `--result RESULT` | required | a result file the preregistration governs (repeatable) |
| `--json` | off | print one JSON object instead of lines |
| `--strict` | off | exit 3 on a WARN finding too |

### `python -m kit integrity cite`

```
usage: python -m kit integrity cite [-h] [--offline] [--json] [--strict]
                                    files [files ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `files` | required | files to read for arXiv ids; a .json file in papers.json form also gives recorded titles |
| `--offline` | off | list the ids only; no network |
| `--json` | off | print one JSON object instead of lines |
| `--strict` | off | exit 3 on a WARN finding too |

### `python -m kit integrity selftest`

```
usage: python -m kit integrity selftest [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | print one JSON object instead of lines |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `IntegrityError()` | | | Bad input, or a planted fault not handled; the CLI exits 1 |
| `MissingData()` | | | The answer needs data this checkout does not have; the CLI exits 2 |
| `group_of(segment, results)` | Test group name or `None` | | A key of `held_out_by_reader`, the scroll of a `segments` key, or a group name inside the segment name |
| `exposure(reader, segment, results)` | `(group, status)`: status `held out`, `possibly not held out`, `not held out`, or `None` with no record | | Uses `kit.leaderboard.status`, so an ensemble takes its worst member |
| `claim_from(data, reader=None, segment=None)` | Claim dict | `IntegrityError` | From a claim record or `kit auc --json` output (which has `forward`) |
| `check_ink(claim, results, where='claim', root=ROOT)` | List of findings | `IntegrityError` (unreadable source, not a number) | `root` resolves a relative `source.file` |
| `result_rows(results)` | Iterator of `(where, claim)` | | Every row with `auc_as_stored` and a `reader`, in any list of results.json |
| `check_text(text, results, where='text')` | List of findings, `where` as `FILE:LINE` | | Skips code, quotations, links, block quotes, negated sentences, negated sections and lead-in lists, negated table columns, allow markers |
| `check_prereg(root, prereg, result_paths)` | List of findings | `MissingData`, `IntegrityError` (git failed) | Paths relative to the git root `root` |
| `arxiv_ids(text)` | Sorted list of ids | | `arXiv:ID`, `arxiv.org/abs/ID`, `arxiv.org/pdf/ID`, `[ID]`; version suffixes dropped |
| `arxiv_titles(ids, opener=urllib.request.urlopen, sleep=time.sleep)` | `{id: title}` | `MissingData` (429 five times), `urllib.error.HTTPError` | `opener` and `sleep` let tests run offline |
| `papers_titles(data)` | `{id: title}` | | From a `docs/papers.json`-style object |
| `check_citations(ids, recorded, titles, where='cite')` | List of findings | | Titles compared after lowercasing and dropping punctuation |
| `selftest(root=ROOT)` | `{"plants", "caught", "clean_controls", "rules"}` | `IntegrityError` | The planted faults and clean controls |
| `add_arguments(p)` | | | Adds the actions to an argparse parser |
| `run(args)` | Exit code | | Runs the selftest, then the action |
| `main(argv=None)` | Exit code | | `python -m kit.integrity` |

A finding is `{"rule", "severity", "where", "message"}`; `RULES` lists every rule as `{"id", "severity", "what", "fix", "source"}`.

## Inputs

- **Claim record** (JSON object, one per file): `reader` (a name starting with a reader family of `kit/leaderboard.py`: `ink_9um`, v8in, v8in-1447, d9v2, Reader v2, Hecate), `segment` (a `results.json` `segments` key such as `0841-w00`, or a group: `PHerc0841`, `w045`), `auc`, `control_auc`, `mask` (`supervision`), `window` (`whole` or `crop`), `claims_held_out` (true when the text calls it held out, unseen or a generalization test), `source` (`{"file", "field"}`, a dotted path with list indices; a relative file is resolved against the current directory), `beats` (`{"reader", "auc", "window", "ci95"}`, `ci95` the 95 % interval of the difference). Numbers may be strings to state their precision; a JSON number's precision is its shortest decimal form. Example: [`templates/ink-claim.json`](../../templates/ink-claim.json).
- **`kit auc --json` output**: `forward.auc`, `control.auc`, `files.mask` (any value means the supervision mask was used) and `crop` (present means a crop); give `--reader` and `--segment`.
- **Text**: Markdown or plain text, UTF-8. Fenced code blocks are not read, so a draft kept inside a fence (a form's paste block) must be checked without its fence lines. To accept a line the checker flags after reading it, end it with `<!-- integrity: allow RULE -->` (one or more rule ids; with none, the whole line is skipped).
- **Preregistration and results**: paths inside the current git checkout, with history.
- **Citations**: any text files; a `.json` file in `docs/papers.json` form (`{"entries": [{"id": "arXiv:ID", "title"}]}`) also supplies recorded titles.

## Outputs

Lines: `selftest: N of N planted faults caught, 5 clean controls passed`, one line per count (`claims`, `rows`, `files`, `results`, `arxiv_ids`, `opened` or `searched`), then one line per finding, `SEVERITY RULE WHERE: MESSAGE`, then `F FAIL, W WARN`. With `--json`: one object.

| Field | Type | Meaning |
| --- | --- | --- |
| `selftest` | object | `plants`, `caught`, `clean_controls`, `rules` |
| `findings` | list | `rule`, `severity` (`FAIL` or `WARN`), `where` (file, file:line, or results.json row), `message` |
| `claims`, `rows`, `files`, `results`, `arxiv_ids` | integer | How much was read |
| `opened`, `searched` | string | `cite`: the source opened, or `no (offline)` |
| `fail`, `warn` | integer | Counts of findings |
| `exit` | integer | The exit code |

| Exit code | Meaning |
| --- | --- |
| `0` | No FAIL finding (WARN findings may be printed), or a listing (`rules`, `exposure`, `selftest`) |
| `1` | Bad input, or a planted fault not caught (no result is printed) |
| `2` | Needs data this checkout does not have: shallow or missing git history (`prereg`), arXiv not reachable (`cite`) |
| `3` | At least one FAIL finding; with `--strict`, a WARN as well |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `a claim is a JSON object` | The claim file holds a list or a number | Write one JSON object per file, as in `templates/ink-claim.json` |
| `this clone is shallow: fetch its history first (git fetch --unshallow, or a bounded git fetch --depth=1000)` | `prereg` reads commit order, which a shallow clone does not have; exit 2 | Fetch the history and rerun |
| `...has no commit in this clone` | The preregistration or a result file is not committed; exit 2 | Commit it, or name the committed path |
| `the clean claim was flagged:...` | A code change made the checker flag a correct record; exit 1 | Fix the change; never edit the clean control to pass |
| `the clean text was flagged:...` | A code change made the wording check flag careful text; exit 1 | Fix the pattern; never edit the clean text to pass |
| `the clean preregistration order was flagged` | A code change broke the order rule; exit 1 | Fix the change |
| `the clean citation was flagged` | A code change broke the title comparison; exit 1 | Fix the change |
| `rules with no planted fault:...` | A rule was added without a planted fault, so nothing shows it can fire; exit 1 | Add a plant for it to `_plants()` |
| `selftest failed, no result reported:...` | A planted fault slipped through or a clean control was flagged; no real result is printed; exit 1 | Read the message that follows; the checker is broken, not your claim |
| `cannot answer:...` | The answer needs data this checkout does not have (history, network); exit 2 | Supply it, or report the check as not run |
| `...: not a number:...` | A score field holds text that is not a number | Give the number, as a string to state its precision |
| `the claim has no...` | `reader`, `segment` or `auc` is missing; `kit auc --json` output needs `--reader` and `--segment` | Add the field or the option |
| `arXiv kept answering 429; rerun later or pass --offline` | arXiv's rate limit outlasted five back-offs (0, 10, 30, 60 and 120 s); exit 2 | Rerun later; `--offline` lists the ids without checking them |
| `planted fault...was not caught as...: got...` | A rule no longer catches its planted fault; exit 1 | Fix the rule; never weaken the plant |
| `planted fault...also failed for another reason:...` | An ink plant failed a second rule, so it no longer isolates the rule it tests; exit 1 | Fix the plant or the rule so each plant fails for its own reason |
| `planted fault 'number not in its run' was not caught: got...` | `ink-source` accepted a number its run file does not hold; exit 1 | Fix the precision match |
| `the clean sourced claim was flagged` | `ink-source` refused a number its run file holds; exit 1 | Fix the precision match |
| `field...: no key...` | The `source.field` path names a key the run file does not have; exit 1 | Give the dotted path to the number, such as `forward.auc` or `results.27.auc_as_stored` |
| `...: source...:...` | The source file could not be read or parsed; exit 1 | Check the path (relative to the current directory) and the JSON |
| `field...: no item...` | A list index in `source.field` is out of range or not a number; exit 1 | Fix the index |
| `arXiv export API blocked:...` | No network, or a proxy refused export.arxiv.org; exit 2 | Record arXiv under Blocked; rerun where it loads, or use `--offline` |

## How it works

1. **Selftest.** `_plants()` lists each fault as an input and the rule and severity it must produce (some also a word the message must hold); `selftest()` runs them through `check_ink`, `check_text`, the order rule, the content rule and `check_citations`, then the clean controls, and checks every rule id has a plant.
2. **Ink.** Gap = forward minus reverse; FAIL at or below 0, WARN under `MIN_GAP` 0.10 (from `kit.leaderboard`, as in `kit/gate.py`). Exposure: the segment's group from `held_out_by_reader` and `segments`, the reader's status from `kit.leaderboard.status`. Source: the claimed number must round to the stored one at the claimed number of decimals (within half a unit of the last place). Comparison: window must match; the interval's lower end must be above 0; a margin under `MIN_MARGIN` 0.02 (from `kit/gate.py`) warns unless the interval is above 0.
3. **Text.** Line by line, outside fenced code; quotations, inline code and links are blanked; each sentence (or each table cell whose column heading is not negated) is matched against the patterns of `TEXT_PATTERNS`. A match is skipped when a negation (not, never, no, without, avoid, ...) comes earlier in the sentence, when the section heading or the list lead-in is negated ("Do not use it:", "**Never:**"), and, for reading claims, when the sentence is about organizers, papyrologists or prizes. The held-out rule fires when a sentence with "held out", "unseen", "generalizes" or "out of sample" names a reader family and a test group (or one of its segments) where that reader is not held out, unless the sentence carries a negation or an exception ("except", "only", "possibly", "but").
4. **Preregistration.** `git log --follow` gives each file's commits. A result whose first commit is the preregistration's first commit is a WARN (order not shown); an earlier one is a FAIL. The preregistration as of the last commit before the first result is diffed against its latest version: removed lines FAIL, added lines WARN.
5. **Citations.** Ids by pattern; titles from the arXiv export API (Atom), compared after lowercasing and replacing every run of other characters by one space.

## Cost and time

Measured on a 4-core cloud container, 23 Oct 2026: `results` 0.26 s wall; `text` on 149 files 1.5 s wall; `cite` on 8 ids one request and a 3.5 s pause. Nothing is rented; no GPU.

## For agents

- **Command:** `python -m kit integrity text DRAFT.md --json`; `python -m kit integrity ink CLAIM.json --json`.
- **Parse:** `exit`, `fail`, `warn` and each `findings[]` `rule`, `where`, `message`; `selftest.caught` must equal `selftest.plants`.
- **Rerun:** Safe; it writes nothing.
- **Success:** Exit 0 with `fail` 0; read every WARN before posting.
- **Not a pass:** Exit 0 from a file the tool could not read in full; a claim record whose fields were written to pass rather than copied from the run; a text allowed line by line without reading it; exit 2 (the check did not run).
- **Go-ahead:** Nothing to run it. Posting what it checked still needs Chase's yes where the rules say so.
- **Never:** Edit a planted fault, a clean control or a pattern so that a draft passes; add an allow marker to a sentence you have not read; call a passing draft verified.

## Tests

`python -m unittest tests.test_integrity -v`: the selftest and nine breaks of the checker that it must catch; the wording corpus; the ink rules on the committed exposure table, `kit auc` output and source precision; every AUC row of `results.json`; the preregistration order on small synthetic git repositories (clean, result first, same commit, edited, amended, no history); citations with a fake arXiv feed; the CLI's exit codes. They do not reach arXiv or check the wording rules on text unlike this repository's.

## History

- 2026-10-23: Added: `kit integrity`, the `vesuvius-integrity` Claude skill and the guide; `results.json` gains Hecate's w045 status (not held out, as `held_out.w045` already said) (`71a0840`)

## Related

- [Guide](../integrity.md): the rules with real cases from this repository, and the skill install.
- [auc](auc.md): the scores and controls this tool checks.
- [claimcheck](claimcheck.md): every README finding number against its pinned source.
- [leaderboard](leaderboard.md): the held-out column built from the same table.
- [heldout](heldout.md) and the [exposure log](../logs/2026-10-16-reader-exposure.md): where the held-out table comes from.
- [STANDARDS.md](../STANDARDS.md) and [NOVELTY.md](../NOVELTY.md): the standards and claim labels.
