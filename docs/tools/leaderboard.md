# leaderboard: write and check the ink reader leaderboard from results.json

`python -m kit leaderboard render` writes `docs/leaderboard.md`, every released ink reader's AUC on PHerc0841 and PHerc0139 w045 beside its controls and held-out status, from `docs/results.json`; `check` fails when the page and the data disagree.

| Field | Value |
| --- | --- |
| Id | `leaderboard` |
| Status | Current |
| Kind | kit command, kit module, kit entry point |
| Area | Scoring and controls |
| Run | `python -m kit leaderboard render`, `python -m kit leaderboard check`, `python -m kit.leaderboard`, `from kit import leaderboard` |
| Code | `kit/leaderboard.py`, `docs/leaderboard.md`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_leaderboard.py` |
| Needs | Python 3.10 or newer, standard library only (argparse, json, re, pathlib). A clone of the repository, because it reads `docs/results.json` and writes `docs/leaderboard.md` next to `kit/` (an installed `scrolls-workbench` package has neither), or `--results` and `--out` pointing at the two files |
| Runs on | Any machine. 0.12 to 0.14 s per `check` and 0.13 to 0.17 s per `render` (5 runs each, measured 2026-10-17, 4-core Intel Xeon cloud container at 2.80 GHz, Python 3.13), almost all of it Python start-up and imports |
| Network | None |
| Writes | `render`: `docs/leaderboard.md` (or the `--out` file), replaced whole. `check`: nothing |
| Go-ahead | Not needed: it reads and writes files in the checkout only. Committing the page is an ordinary repository change |
| Released | Not on public `main` yet (checked 2026-10-17): on branch `claude/project-thread-8zzi1i` since 2026-10-16 (`da27520`), in the open [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100) |
| Guide | [leaderboard.md](../leaderboard.md), the generated board itself, with its "How to read it" list |
| Checked | 2026-10-17 against commit `1b620c6` |

## What it does

An ink reader here is a released ink detection model, such as the team's `ink_9um` and Hecate, Youssef Nader's v8in and v8in-1447, and the community fine-tunes d9v2 and Reader v2 (glossary in [`AGENTS.md`](../../AGENTS.md)). Their scores on the labelled test segments sat in many rows of `docs/results.json`, measured with different windows and controls, next to scores other people reported with their own settings. Some readers also trained on a test segment, which makes their score there no test at all. A bare table of AUCs invites a ranking those numbers cannot support.

`python -m kit leaderboard render` reads `docs/results.json` and writes `docs/leaderboard.md`. For each test segment (PHerc0841 w00, ag896 and ag405, and PHerc0139 w045) it writes one table per window: `whole` (the whole segment) or `crop, inner N` (the 640 px window where the labels mark the most ink, with an N px edge left out). Each row gives the forward AUC (depth layers in stored order), the reversed AUC (the reverse-depth control), the gap between them, the shuffled-depth AUC where one was run, whether the reader's training data left that segment out, where the map came from, the device, a link to the source and the date. A second table lists scores reported by others. `python -m kit leaderboard check` renders the page in memory and fails when the file on disk differs by one byte; the tests and the daily [routines](routines.md) run it.

The held-out column comes from `held_out_by_reader` in `results.json`: one word per reader family and test group (`held out`, `possibly not held out` or `not held out`). The family is read from the start of the reader name (`FAMILIES`), and an ensemble written `A + B mean` takes the least held-out status of its parts. A row whose reader has no word there stops the render with an error, so a new reader cannot reach the board without a held-out status.

It computes no score: the numbers are entered in `results.json` from [auc](auc.md) runs and from other people's published reports, each with its source. It ranks nothing and declares no winner: [gate](gate.md) applies Gate A's Phase 0 rule to the crop rows. It leaves out `finetune_checks` (this repository's own fine-tunes, which are not released readers) and every result row without `auc_as_stored`, such as row scores. Every number on the board is an AUC of a model's ink map against human labels: an ink map is model output, not a reading, and a higher AUC does not mean letters were read.

## When to use it

- After adding or changing a row in `results.json` `results` or `community`, or a word in `held_out_by_reader`: run `render`, then commit `docs/results.json` and `docs/leaderboard.md` together.
- Before quoting one reader against another: read the board's Reversed, Gap and Held out columns first, and compare only rows with the same window.
- In tests and scheduled checks: `check` (exit 1 when the page is stale).

Do not use it:

- To score an ink map against labels: use [auc](auc.md); then copy its numbers and source into `results.json`.
- To decide whether one reader beats another by Gate A's rule: use [gate](gate.md).
- To average two readers' maps: use [ensemble](ensemble.md).
- To make the shuffled-depth control map: use [layers](layers.md) (`--shuffle`, `kit shuffle`).
- To edit the board by hand: edit `results.json` and run `render`; `check` fails on a hand edit.
- For a target-scroll score: it never goes into `results.json` or onto the board (the no-findings rule, hard rule 1).

## Quick start

```bash
python -m kit leaderboard check
python -m kit leaderboard render
```

Run on 2026-10-17 at commit `1b620c6`: `check` printed nothing and exited 0. `render`, run with `--out` set to a scratch file so the checkout stayed as it was, printed

```
{"out": "SCRATCH/board.md", "rows": 42, "tables": 13}
```

(`SCRATCH` stands for the scratch folder's full path) and wrote a file identical to `docs/leaderboard.md` (`cmp` found no difference). The page it writes starts:

```
# Ink reader leaderboard
...
Written from results.json of 2026-10-16.

## Measured in this repository

### PHerc0841 w00

Segment `20260220213127-w00`, 9.366 um surface volume, crop `[2624, 3264, 2688, 3328]` (y0, y1, x0, x1).

Window: whole

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| ink_9um seed42 | held out | 0.7479 | 0.5010 | +0.2469 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
```

It worked when both commands exit 0 and, after `render`, `git diff docs/leaderboard.md` shows only the rows you changed in `results.json`. `rows` counts table rows without header lines (42 on 2026-10-17) and `tables` the tables (13).

## Checks and controls

- **The check can fail, and is tested failing.** `check` compares the rendered text with the file byte for byte. `CheckTest.test_check_fails_until_rendered_and_after_a_change` shows it exits 1 with no page, after one number changes in the data, and after a hand edit of the page. On 2026-10-17 a scratch copy of the page with one number changed (0.7479 to 0.7480) made it exit 1 with `differs from what ... renders to`.
- **A missing held-out status fails.** With `v8in` removed from `held_out_by_reader.w045` in a scratch copy of `results.json`, `render` exited 2 and `check` exited 1, both printing `held_out_by_reader has no status for 'v8in'` (run 2026-10-17; also `StatusTest`).
- **Every row carries its control.** Reversed should sit near or below 0.5 and well below Forward. A gap under `MIN_GAP` (0.10, the same threshold as `MIN_GAP` in `kit/gate.py`) is marked `weak control`. On the board of 2026-10-17 no measured row is marked: the smallest measured gap is +0.1015 (`ink_9um seed42`, PHerc0841 ag896, crop inner 64). One measured row (`ink_9um seed42` on w045, crop inner 64) and most community rows have no reversed score, so their Gap cell is empty: those rows have no control on the board.
- **Not checked here:** that the numbers in `results.json` are right (each row names its source), or that a held-out word is right. `RepositoryTest.test_every_held_out_family_is_in_the_prose` checks only that every family in `held_out_by_reader` is named in the matching `held_out` text, whose sources are in the [exposure log](../logs/2026-10-16-reader-exposure.md).

Claim label: Model output, for the AUCs of the measured tables, copied from `results.json` with their sources; the "Reported by others" table is Community report; the Held out column restates `held_out_by_reader`, whose sources and labels are in `held_out` and the exposure log.

## Commands and options

### Options of `python -m kit leaderboard` (before the action)

```
usage: python -m kit leaderboard [-h] [--results RESULTS] [--out OUT]
                                 {render,check} ...
```

These options belong to `leaderboard` itself, so they go before the action: `python -m kit leaderboard --results R --out O check`. After the action they are refused (`unrecognized arguments`, exit 2).

| Option | Default | Meaning |
| --- | --- | --- |
| `{render,check}` | required | The action: `render` writes the page, `check` compares it |
| `--results RESULTS` | `docs/results.json` of the checkout that holds `kit/` (`RESULTS`, an absolute path, so it works from any directory) | The scores to read |
| `--out OUT` | `docs/leaderboard.md` of the checkout that holds `kit/` (`BOARD`, an absolute path) | The page to write (`render`) or compare with (`check`) |

`python -m kit.leaderboard` takes the same options and actions and prints the same usage (its program name is `python -m kit leaderboard`).

### `python -m kit leaderboard render`

```
usage: python -m kit leaderboard render [-h]
```

No options of its own. It renders the page from `--results`, writes it to `--out` (UTF-8, replacing the file) and prints one JSON line (Outputs). On bad data it writes nothing and exits 2.

### `python -m kit leaderboard check`

```
usage: python -m kit leaderboard check [-h]
```

No options of its own. Exit 0, silently, when `--out` holds exactly what `--results` renders to; exit 1, with the problem on stderr, otherwise. It writes nothing.

## Python API

```python
from kit import leaderboard
data = leaderboard.load()                       # docs/results.json
text = leaderboard.render(data)                 # the page as a string
problems = leaderboard.check()                  # [] when docs/leaderboard.md is in step
leaderboard.status("Hecate + Reader v2 mean", "PHerc0841", data["held_out_by_reader"])   # 'not held out'
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `BoardError` | A `ValueError` subclass | | Raised for data the board cannot show; `run` prints it as `leaderboard: MESSAGE` |
| `family(reader)` | str, one of `FAMILIES`, or `None` | Nothing | The first family the name starts with; `FAMILIES` lists `v8in-1447` before `v8in`, so `v8in-1447 stride 42` is `v8in-1447` |
| `parts(reader)` | list of family names (or `None` for an unknown part) | Nothing | An ensemble `A + B mean` gives two parts; a trailing ` mean` is dropped first |
| `status(reader, group, table)` | str, one of `STATUSES` | `BoardError` for a part with no known family, or with no status word in `table[group]` | The least held-out status of the parts (`STATUSES` runs best to worst) |
| `row_date(row)` | str `YYYY-MM-DD`, or `None` | `BoardError` when `row["date"]` is set but not `YYYY-MM-DD` | The row's `date`, else the first `20YY-MM-DD` in its `source` |
| `window(row)` | str: `whole`, or `crop, inner N` | Nothing | Any `window` other than `whole` counts as a crop; `N` is `inner_px`, 0 when missing |
| `measured(data)` | list of the `results` rows on the board, each copied with `_status`, `_date` and `_window` | `BoardError` for a row with no date, or a reader with no status | Keeps rows whose `segment` is in `GROUPS` and that have `auc_as_stored` |
| `community(data)` | list of the `community` rows on the board, each copied with `_status` and `_date` (`not recorded` when there is none) | `BoardError` as `status` and `row_date` | Keeps rows whose `test` names `PHerc0841` or `w045` |
| `render(data)` | str, the whole page | `BoardError` with no `held_out_by_reader`, or when a long dash reaches the text, and those of `measured` and `community`; `KeyError` for a row without `reader`, or a community row without `auc` | Pure: reads nothing but `data` |
| `load(path=RESULTS)` | dict, the parsed JSON | `OSError` for a missing file, `json.JSONDecodeError` for a broken one | |
| `check(results_path=RESULTS, board_path=BOARD)` | list of str, empty when the page is in step | Nothing: `OSError`, `ValueError` and a `KeyError` from a row missing a field come back as problems | Problems start `leaderboard: ` |
| `add_arguments(p)` | None | Nothing | Adds `--results`, `--out` and the `render` and `check` actions to an argparse parser; `kit/cli.py` builds the command with it |
| `run(args)` | int, the exit code (0, 1 or 2) | Nothing: a failed write of `--out` or a row missing a field is printed and gives exit 2 | Prints to stdout and stderr as under Outputs |
| `main(argv=None)` | int, the exit code | `SystemExit` (code 2) from argparse on a usage error | Its own parser, program name `python -m kit leaderboard` |

Module constants: `ROOT` (the checkout), `RESULTS` (`docs/results.json`), `BOARD` (`docs/leaderboard.md`), `GROUPS` (segment key to test group: `0841-w00`, `0841-ag896`, `0841-ag405` to `PHerc0841`, `w045` to `w045`), `SEGMENT_ORDER`, `SEGMENT_TITLE`, `FAMILIES` (`v8in-1447`, `Reader v2`, `ink_9um`, `Hecate`, `d9v2`, `v8in`), `STATUSES`, `STATUS_CELL` (how each status is written: bold for the two not held out words), `MIN_GAP` (0.10), `DATE`, `LONG_DASHES` and `HEADER` (the page's fixed opening text).

## Inputs

One JSON file, `docs/results.json` (or `--results`), over 200 KB; on 2026-10-17 it held 32 `results` rows and 11 `community` rows. The board reads only these parts:

| Key | Fields read | Notes |
| --- | --- | --- |
| `updated` | str (date) | Printed as `Written from results.json of DATE.`; `unknown date` when missing |
| `held_out_by_reader` | `{GROUP: {FAMILY: STATUS}}` for the groups `PHerc0841` and `w045` | Required. `STATUS` is one of `held out`, `possibly not held out`, `not held out`. Its `about` text is ignored |
| `segments` | `0841-w00`, `0841-ag896`, `0841-ag405`, `w045`, each with `segment` (folder name), `voxel_um` and `crop` (`[y0, y1, x0, x1]` in surface pixels) | Optional; gives each section's first line |
| `results[]` | `segment` (one of the four keys), `reader`, `auc_as_stored`, `auc_reversed`, `auc_shuffled`, `window` (`whole` or `crop`), `inner_px`, `map_from`, `device`, `source`, `date` | `reader`, `segment` and `auc_as_stored` are needed for a row to appear; `date` (`YYYY-MM-DD`) or a dated `source` is required for it |
| `community[]` | `reader`, `test` (must contain `PHerc0841` or `w045`), `auc`, `auc_reversed`, `source`, `date`, `note` | `auc` is required for every row whose `test` matches |

AUCs are unitless, 0 to 1. A `source` that starts `https://` becomes a link shortened to 60 characters, one that starts `docs/` a link relative to `docs/`, one that starts `scripts/`, `kit/` or `tests/` a link from `docs/` up to the repository root; anything else is printed as it is.

## Outputs

`render` prints one JSON line to stdout and writes the page:

| Field | Type | Meaning |
| --- | --- | --- |
| `out` | str | The page written, as given by `--out` (the absolute default path otherwise) |
| `rows` | int | Table rows on the page, without header and separator lines (42 on 2026-10-17) |
| `tables` | int | Tables on the page (13 on 2026-10-17) |

The page: the fixed opening (`HEADER`, with `MIN_GAP`), the `Written from results.json of DATE.` line, then `## Measured in this repository` with one `### SEGMENT` section per segment in `SEGMENT_ORDER`, each with its segment line, one `Window: W` table per window (whole first, then crops) with the columns Reader, Held out, Forward, Reversed, Gap, Shuffled, Map from, Device, Source and Date, and a `Not scored here yet:` line naming families that have a status for the group but no row on that segment (`No row yet.` when the segment has none); last, `## Reported by others (Community report)` with the columns Reader, Test, Held out, Forward, Reversed, Gap, Source, Date and Note. AUCs and gaps have 4 decimals; a gap below `MIN_GAP` reads `+0.0769 (weak control)`.

`check` prints nothing on success and each problem on stderr otherwise.

| Exit code | Meaning |
| --- | --- |
| `0` | `render`: the page was written. `check`: the page is exactly what the data renders to |
| `1` | `check`: the page is missing or differs, or the data cannot be rendered (including a row without `reader` or `auc`) |
| `2` | A usage error from the argument parser; no `--results` file (either action); `render`: data it cannot render, or an `--out` it cannot write (nothing is written) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as `python -m kit leaderboard: error: the following arguments are required: action` or `argument action: invalid choice: 'nope' (choose from 'render', 'check')` | Give `render` or `check` |
| `python -m kit: error: unrecognized arguments: --results docs/results.json`, exit code 2 | `--results` or `--out` after the action | Put them before it: `python -m kit leaderboard --results R check` |
| `leaderboard: no RESULTS; it reads the repository's docs/results.json, so run it from a clone or give --results`, exit code 2 | The results file is not there: an installed package without `docs/`, or a wrong `--results` | Run from a clone, or give `--results` |
| `leaderboard: results.json has no held_out_by_reader` | The data has no held-out table | Add `held_out_by_reader` to `results.json` (its `about` says what goes in it) |
| `leaderboard: reader 'NAME': no known family; add it to kit/leaderboard.py FAMILIES` | The reader name starts with no name in `FAMILIES` | Write the reader name as its family's name first (such as `v8in d89166b`), or, for a new released reader, add the family to `FAMILIES` with a test |
| `leaderboard: reader 'NAME' on GROUP: held_out_by_reader has no status for 'FAMILY' (one of held out, possibly not held out, not held out)` | That family has no word, or an unknown word, for that test group | Add the word to `held_out_by_reader`, and the reason with its source to `held_out` |
| `leaderboard: date 'VALUE' is not YYYY-MM-DD` | A row's `date` is set but not written `YYYY-MM-DD` | Write it as `2026-10-07` |
| `leaderboard: READER on SEGMENT: no date (add a "date" field or a dated source)` | A measured row has no `date` and no date in its `source` | Add `"date"` to the row |
| `leaderboard: a long dash reached the leaderboard; fix the results.json text it came from` | A U+2014 or U+2013 in a field the page shows | Replace it in `results.json` (the style rule, hard rule 10) |
| `leaderboard: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)` (or another JSON message) | `results.json` does not parse | Fix the JSON; `python -m json.tool docs/results.json` shows where |
| `leaderboard: no OUT; run python -m kit leaderboard render`, exit code 1 | `check` found no page at `--out` | Run `render` |
| `leaderboard: OUT differs from what RESULTS renders to; run python -m kit leaderboard render (edit results.json, not the page)`, exit code 1 | The page is stale, or was edited by hand | Run `render` and commit both files |
| `leaderboard: a row in RESULTS has no 'auc' field` (or `'reader'`), exit code 1 from `check`, 2 from `render` | A `community` row that names PHerc0841 or w045 without `auc`, or a result row without `reader` | Add the field to the row |
| `leaderboard: [Errno 2] No such file or directory: 'OUT'`, exit code 2 | `render` with an `--out` whose folder does not exist | Create the folder, or give another `--out` |

`RESULTS`, `OUT`, `NAME`, `GROUP`, `FAMILY`, `READER`, `SEGMENT` and `VALUE` stand for the paths and values in the actual message.

## How it works

1. `run` stops with exit 2 when `--results` is not a file. For `check` it calls `check()`; for `render`, `render(load(...))`.
2. `measured` keeps each `results` row whose `segment` is a key of `GROUPS` and that has `auc_as_stored`. Each gets its date (`row_date`: the `date` field, else the first date in `source`), its held-out status (`status`, from the row's test group) and its window (`window`).
3. `status` splits an ensemble name on ` + ` (after dropping a trailing ` mean`), finds each part's family by prefix in `FAMILIES` (longest first), looks each up in `held_out_by_reader[GROUP]`, and returns the worst of them in the order of `STATUSES`: `held out`, `possibly not held out`, `not held out`.
4. `render` writes `HEADER`, then for each segment in `SEGMENT_ORDER` its windows (`whole` first, then crops in name order: `crop, inner 0` before `crop, inner 64`). Rows sort by Forward, highest first, then reader and device. Gap is Forward minus Reversed; under `MIN_GAP` = 0.10 it is flagged `weak control`, the threshold `kit/gate.py` uses for its control test (`MIN_GAP` there too).
5. After each segment it lists, in `FAMILIES` order, the families with a status for that group and no row on that segment. Then come the community rows whose `test` names `PHerc0841` or `w045`, sorted by test, then AUC (highest first), then reader.
6. Cells escape `|` as `\|` and turn line breaks into spaces. When the finished text holds a U+2014 or U+2013 dash, it raises instead of writing it.
7. `check` renders in memory and compares with the file's text exactly, so any byte the data does not produce fails.

## Cost and time

Measured 2026-10-17 in a 4-core Intel Xeon cloud container at 2.80 GHz with Python 3.13: 0.12 to 0.14 s per `check` and 0.13 to 0.17 s per `render` (5 runs each), with a peak resident memory of about 25 MB. The input is one JSON file of a few hundred KB. It rents nothing and runs anywhere; no Modal job is ever needed.

## For agents

- **Command:** `python -m kit leaderboard check` (exit code only); `python -m kit leaderboard render` after changing `results.json` (machine-readable: one JSON line on stdout).
- **Parse:** from `render`, `out` (the page written) and `rows` (table rows plus one header line per table). From `check`, the exit code and the stderr lines, each starting `leaderboard: `. From the page, per row: Reader, Held out, Forward, Reversed, Gap, Shuffled, Window (the table's `Window:` line), Source and Date.
- **Rerun:** Safe. `check` writes nothing; `render` rewrites the whole page from the data, so a rerun on unchanged data writes the same bytes.
- **Success:** Exit code 0. For `render`, a JSON line with `out`; then `check` exits 0.
- **Not a pass:** A row marked **NOT held out** or **possibly NOT held out**, which is no test of that reader; a row with an empty Reversed cell, which has no control; a `weak control` gap; comparing rows across windows, or a measured row with a community one; a passing `check`, which says only that page and data agree, not that the numbers are right.
- **Go-ahead:** Nothing. Posting the board or its numbers anywhere outside the repository needs Chase's yes (the go-ahead rule, hard rule 8).
- **Never:** Edit `docs/leaderboard.md` by hand; add a reader without a `held_out_by_reader` word; put a target-scroll score into `results.json` (the no-findings rule, hard rule 1); call a higher AUC a reading or say letters were found.

## Tests

```bash
python -m unittest tests.test_leaderboard -v
```

19 tests in 0.08 s (run 2026-10-17). `StatusTest` covers family matching (`v8in-1447` before `v8in`), the ensemble's least held-out status, and the errors for a reader with no family or no status, a row with no date and data with no status table. `RenderTest` checks the held-out markings, the column values and the `weak control` flag, the window split and sort, that rows without `auc_as_stored` stay out and missing families are named, the source links, and the long-dash refusal. `CheckTest` runs `main` on a scratch copy: `check` fails before `render`, after a data change and after a hand edit, bad data fails both actions (exit 1 and 2), a row missing `auc` is a problem for `check` and exit 2 for `render`, `rows` plus `tables` equals the page's table lines and an `--out` in a missing folder gives exit 2, a missing results file gives exit 2, and `kit/cli.py` registers the command. `RepositoryTest` checks that the committed page matches the committed `results.json`, and that every family in `held_out_by_reader` is named in the matching `held_out` text. They do not run the command through `python -m kit` in a subprocess, and they cannot check that the numbers in `results.json` are right.

## History

- 2026-10-17: this page; `render` prints `rows` without header lines and a `tables` count, and a row missing a field or an `--out` it cannot write gives a `leaderboard:` message instead of a traceback ([PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).
- 2026-10-16: Hecate's PHerc0841 status in `held_out_by_reader` goes from `possibly not held out` to `not held out`, after the [exposure log](../logs/2026-10-16-reader-exposure.md), and the page is re-rendered (`05017e7`, [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).
- 2026-10-16: first version: `python -m kit leaderboard render` and `check`, `docs/leaderboard.md`, `held_out_by_reader` in `results.json` and `tests/test_leaderboard.py` (`da27520`, [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).

## Related

- [leaderboard.md](../leaderboard.md): the board this command writes.
- [auc](auc.md): makes the forward and reversed scores the board shows.
- [gate](gate.md): applies Gate A's rule to the PHerc0841 crop scores; shares `MIN_GAP`.
- [ensemble](ensemble.md): averages two readers' maps, the kind of map an `A + B mean` row scores.
- [layers](layers.md): writes the shuffled-depth control behind the Shuffled column.
- [heldout](heldout.md): the Hecate split script behind the PHerc0841 and w045 held-out words.
- [routines](routines.md): runs `python -m kit leaderboard check` daily.
- [Reader exposure log](../logs/2026-10-16-reader-exposure.md): which released reader trained on which segment, the source of `held_out_by_reader`.
- [w045 log](../logs/2026-10-08-w045-not-held-out.md): why w045 is not held out from `ink_9um`, d9v2 and Reader v2.
- [`results.json`](../results.json): keys `results`, `community`, `segments`, `held_out` and `held_out_by_reader`.
