# claimcheck: trace every README number to a pinned source

Checks that every number in the README's "Novel findings" section matches a results unit or repository file pinned by sha256 (or carries a stated reason), and that new results units cite a file; fails when a claim has no source.

| Field | Value |
| --- | --- |
| Id | `claimcheck` |
| Status | Experimental |
| Kind | kit module |
| Area | Records and provenance |
| Run | `python -m kit.claimcheck`, `from kit import claimcheck` |
| Code | `kit/claimcheck.py` |
| Tests | `tests/test_claimcheck.py` |
| Needs | Python 3.10 or newer, standard library only; this checkout's `README.md`, `docs/results.json` and the files the ledger cites |
| Runs on | CPU; `check` on this repository took 0.8 s on the 4-core cloud container (21 Oct 2026) |
| Network | None |
| Writes | Nothing for `items`, `trace`, `suggest` and `check`. `add --write`, `pin --write` and `results --write` rewrite `docs/claims/sources.json` (atomically, through `sources.tmp`) |
| Go-ahead | Not needed |
| Released | Public `main` from 21 Oct 2026 |
| Checked | 2026-10-21 against commit `2601c1f` |

## What it does

The README's "Novel findings" section states about 190 numbers (AUCs, distances, counts, shares). AGENTS.md asks that the README claim, `docs/results.json` and the linked source stay in step. Nothing checked that until now: a number could be edited, rounded wrongly or left behind when its source changed.

`kit.claimcheck` splits the section into blocks (each list item and each paragraph, up to the next `## ` heading) and pulls out every number a block states. It leaves out dates, years, times, issue and PR numbers (`#2058`), references such as "finding 12" or "lines 200-207", code spans, link targets and identifiers with digits in them (PHerc0841, w045, `ink_9um`, commit hashes). The ledger, `docs/claims/sources.json`, names each block's sources: results units (`r:results/7`, `r:axis_parity_checks/1`, `r:community/8`) or repository files and folders (a log, an evidence folder), each pinned to its sha256 at the time it was reviewed. A number passes when one of its block's sources holds a number that rounds to it at the README's precision (0.738 matches a stored 0.7382; an integer matches only an equal integer; "96 %" also matches 0.96). A number no source holds (a setting such as the 640 px crop, or a value derived from the source, such as a difference) needs a reason in the ledger that starts with `setting:`, `count:`, `derived:`, `external:` or `context:`.

For `docs/results.json` it checks the other direction too: every unit should cite an existing repository file in one of its string values (`source`, `evidence`, ...), and a community row may cite its publication's URL instead. The units that do not today are listed in the ledger's `results_baseline` (by the first 12 hex digits of their unit sha256), and any other unit that cites no file fails the check, so the gap cannot grow.

The results unit digest is kit causal's `unit_sha256` (the unit's canonical JSON without `id` and `causal`). When `docs/causal/claims.json` (written by kit causal, where that tool is installed) exists, its `source` lines for a Novel findings item are read as that block's sources too, so the two tools share one list of causes. kit causal checks each claim as a whole (its quote, label and pinned causes); this tool checks each number.

What it does not do: a match shows that a pinned source holds the number, not that it is the right quantity there; a small integer can match by chance in a long log, and a reason is the reviewer's statement. It does not check words, labels or whether a finding is true.

## When to use it

- Before merging a change to the README's Novel findings or to a results unit, log or evidence folder the ledger cites: run `check`.
- When adding a Novel findings item or paragraph with numbers: `suggest KEY`, read the candidates, then `add KEY --source ... --write`.
- When `check` reports a changed source (C4): read what changed, fix the README if a number moved, then `pin --write`.

Do not use it:

- To link results to preregistrations, decisions and runs: use kit causal where it is installed.
- To record or check one run's inputs, outputs and their hashes: use [provenance](provenance.md).

## Quick start

```bash
python -m kit.claimcheck check
python -m kit.claimcheck trace scoring-a-crop-needs-an-edge-margin
```

On 21 Oct 2026 `check` printed `187 numbers in 17 blocks: 177 sourced, 10 with a reason; 2 of 92 results units cite no file (baseline 2); ok` and exited 0. `trace` printed one line per number:

```text
       640  reason: setting: the crop is a 640 px window (the glossary's Crop)
      0.03  reason: derived: 0.821 minus 0.793 is 0.028, rounded
     0.821  r:results/20
     0.793  r:results/17
        64  r:results/9, r:results/26
```

It worked when `check` exits 0 and ends in `ok`.

## Checks and controls

The check has to be able to fail, so the tests feed it what it must catch. `tests/test_claimcheck.py` builds a small repository and shows each finding firing: a number added to a claimed item with no source (C2), a new item with numbers and no entry (C1), a missing source (C3), an edited source until it is re-pinned (C4), a reason for a number the README no longer states (C5), a ledger entry for a block that is gone (C6), and a new results unit with no file (C7); `add` refuses an entry that leaves a number untraced. On this repository, `RepositoryTest` asserts that the real README passes and, as the control, that the same README with ` It also scored 0.987654.` appended to the first claimed item fails with C2. With `matches` replaced by one that always says yes, that control test fails (checked by hand on 21 Oct 2026), so the pass depends on the match.

Claim label: None for the tool's own output (it makes no scientific claim); the counts above describe this repository's README on 2026-10-21.

## Commands and options

Every command takes the global options before the command name.

### `python -m kit.claimcheck`

```text
usage: python -m kit.claimcheck [-h] [--root ROOT] [--ledger LEDGER] [--json]
                                {items,trace,suggest,add,pin,check,results} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--root ROOT` | `.` | Repository root |
| `--ledger LEDGER` | `docs/claims/sources.json` | Ledger path under the root |
| `--json` | off | Print JSON instead of text |

### `python -m kit.claimcheck items`

```text
usage: python -m kit.claimcheck items [-h]
```

Lists each block's line, key and numbers. No options.

### `python -m kit.claimcheck trace`

```text
usage: python -m kit.claimcheck trace [-h] [--source SOURCE] key
```

| Option | Default | Meaning |
| --- | --- | --- |
| `key` | required | Block key from `items` |
| `--source SOURCE` | the ledger's | A results unit `r:ID` or a repository path; repeatable |

### `python -m kit.claimcheck suggest`

```text
usage: python -m kit.claimcheck suggest [-h] key
```

| Option | Default | Meaning |
| --- | --- | --- |
| `key` | required | Block key; prints a greedy cover of its numbers, files its links name first, then results units, and the numbers left |

### `python -m kit.claimcheck add`

```text
usage: python -m kit.claimcheck add [-h] --source SOURCE [--reason REASON]
                                    [--write]
                                    key
```

| Option | Default | Meaning |
| --- | --- | --- |
| `key` | required | Block key |
| `--source SOURCE` | required | `r:ID` or a repository path; repeatable; each is pinned to its sha256 now |
| `--reason REASON` | none | `TOKEN=KIND: text` for a number no source holds, KIND one of setting, count, derived, external, context; repeatable |
| `--write` | off | Store the entry; without it the entry is printed only |

### `python -m kit.claimcheck pin`

```text
usage: python -m kit.claimcheck pin [-h] [--write]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--write` | off | Store every source's current sha256; run only after reading what changed |

### `python -m kit.claimcheck check`

```text
usage: python -m kit.claimcheck check [-h]
```

Exit 1 on any finding (codes under Outputs). No options.

### `python -m kit.claimcheck results`

```text
usage: python -m kit.claimcheck results [-h] [--write]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--write` | off | Store today's unsourced units as the baseline; a reviewer's step, since it accepts every unit listed |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `ClaimError()` | an exception | | Bad ref, ledger or reason |
| `section_blocks(text)` | list of dict | | [{key, kind, line, text}] for the list items and paragraphs under the README's "## Novel findings" heading, |
| `numbers(text)` | list of dict | | [{"token", "value", "decimals", "percent"}] for each number the text states, in order. |
| `unit_sha256(entry)` | str | | sha256 of a results unit's canonical JSON without `id` and `causal` (kit causal's unit_sha256). |
| `results_units(data)` | dict | | {ref: entry} for every unit of a results file: r:SECTION for a dict section, r:SECTION/INDEX for each object |
| `Sources(root)` | resolver | | Resolves source refs in one repository root, caching results.json and file reads. |
| `matches(num, values)` | bool | | True when some source value rounds to the README number at its precision (an integer: equals it). |
| `load_ledger(root, path=LEDGER)` | dict | `ClaimError` | An empty ledger when the file is missing |
| `save_ledger(root, doc, path=LEDGER)` | None | | Sorted, atomic write |
| `causal_sources(root, blocks)` | dict | | {block key: [refs]} from docs/causal/claims.json (kit causal), matched by quote; empty when absent. |
| `trace_block(src, block, refs, reasons=None)` | (rows, bad) | | [{token, sources, reason}] for each number of a block against the refs (errors per ref in 'bad'). |
| `check(root='.', ledger=LEDGER, readme_text=None)` | dict | `ClaimError` | {"exit", "findings": [{code, where, text}], "counts"} for the README's Novel findings and results units |
| `results_unsourced(root)` | dict | `ClaimError` | {"units", "unsourced": [{ref, sha12}]}: results units none of whose string values names an existing |
| `suggest(root, key, ledger=LEDGER, limit=8)` | dict | `ClaimError` | {"chosen": [{ref, covers}], "left": [tokens]}: a greedy cover of one block's numbers, linked files first. |
| `add_entry(root, key, refs, reasons=(), ledger=LEDGER, write=False)` | dict | `ClaimError` | Build (and with write, store) one block's ledger entry; ClaimError when a number stays untraced. |
| `pin(root, ledger=LEDGER, write=False)` | dict | `ClaimError` | {"changes": [{block, ref, old, new}], "written"} |
| `main(argv=None)` | int | | The command line; returns the exit code |

## Inputs

- `README.md`: the `## Novel findings` section, up to the next `## ` heading. Blockquotes, headings and HTML comments are skipped.
- `docs/results.json`: units are dict sections (`r:SECTION`), object rows of list sections (`r:SECTION/INDEX`) and rows with an explicit `id` (`r:ID`); `schema`, `updated`, `about`, `held_out`, `segments` and `pending` are not units.
- Repository files and folders the ledger cites. Text files (`.md`, `.json`, `.jsonl`, `.csv`, `.tsv`, `.txt`, `.log`, `.yaml`, `.yml`, `.xml`) up to 8 MB are read for numbers; every file is hashed.
- `docs/causal/claims.json` when present (schema `causal-claims/1`).

## Outputs

Text by default, JSON with `--json`. The ledger, `docs/claims/sources.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | str | `claimcheck/1` |
| `readme` | str | The README checked, `README.md` |
| `blocks.KEY.line` | int | The block's line when it was added (informational) |
| `blocks.KEY.sources` | dict | ref to sha256 pin |
| `blocks.KEY.reasons` | dict | number token to `KIND: text` |
| `results_baseline` | list | sha12 of the results units that cited no file when the baseline was stored |

`check --json` prints `exit`, `findings` (each `code`, `where`, `text`) and `counts` (`blocks`, `numbers`, `sourced`, `reasoned`, `sources`, `results_units`, `results_unsourced`). Codes: C1 a block with numbers and no entry; C2 a number no source holds and no reason covers; C3 a source that does not exist; C4 a source whose sha256 differs from its pin; C5 a reason for a number no longer stated, or a reason without a kind; C6 an entry for a block the README no longer has; C7 a results unit that cites no file and is not in the baseline.

| Exit code | Meaning |
| --- | --- |
| `0` | Every number is traced and every pin is current (`check`), or the command finished |
| `1` | `check` found at least one problem |
| `2` | Bad arguments, a ledger or results file that cannot be read, or a refused `add` |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `'s Novel findings (python -m kit.claimcheck items)` | The key names no block | Run `items` and copy the key |
| `must be {"schema": "` | The ledger is malformed | Restore `{"schema": "claimcheck/1", "blocks": {...}}` from git |
| `not found under` | No README at the root | Pass `--root` |
| `does not state` | A `--reason` names a number the block does not have | Copy the token from `trace` |
| `match none of the sources and have no --reason` | `add` would leave numbers untraced | Add the source that holds them, or a reason |
| `is not JSON:` | `docs/results.json` does not parse | Fix the JSON |
| `: write TOKEN=KIND: text, KIND one of` | A reason without `=` or a known kind | Write `640=setting: the crop size` |
| `is not a unit of` | `r:ID` names no results unit | Check the section, index or id |
| `: a source is a results unit or a path inside the repository` | An absolute path, `..` or a URL | Cite the results unit or the file in this repository |
| `does not exist` | The cited path is gone | Cite where the number lives now, then `pin --write` |

## How it works

1. `section_blocks` reads the lines after `## Novel findings` and groups them into list items (a top-level `-`, `*`, `+` or `N.` marker) and paragraphs. A block's key is the first 8 words of its bold lead, or of its text, lowercased and joined by `-`.
2. `numbers` replaces links by their text, drops the patterns in `_DROP` (dates, years, times, `#N`, references, code spans, URLs) and takes each remaining number not glued to a letter, `.`, `-` or `/`, with its sign, its decimals and a trailing `%`.
3. `Sources.resolve` gives each ref its sha256 (a file's bytes; a folder's sorted `path, sha256` lines; a unit's `unit_sha256`) and the numbers in it (JSON values and numbers inside strings, or every number in a text file).
4. `matches` compares at the README's precision: with d decimals, a source value matches when it rounds to the README value at d decimals; with none, only an equal integer matches. A percent also tries the source value times 100.
5. `check` runs C1 to C7 as listed under Outputs. `results_unsourced` looks for paths under `docs/`, `scripts/`, `kit/`, `tests/`, `patches/` and the other top-level folders in every string value of a unit.

## Cost and time

Local and free. `check` on this repository: 0.8 s wall on the 4-core cloud container (21 Oct 2026); the tests take about 3 s.

## For agents

- **Command:** `python -m kit.claimcheck check` (`--json` for the findings as JSON).
- **Parse:** with `--json`, `exit` and `findings[].code`, `where`, `text`; `counts.numbers`, `sourced`, `reasoned`.
- **Rerun:** safe; `check`, `items`, `trace` and `suggest` write nothing.
- **Success:** exit 0 and `findings` empty.
- **Not a pass:** a number traced only to a long log by a small integer (read the source); `pin --write` or `results --write` run without reading what changed.
- **Go-ahead:** Nothing.
- **Never:** add a reason to silence a number you have not traced; cite a file outside the repository; treat a pass as proof the finding is right.

## Tests

`python -m unittest tests.test_claimcheck`: extraction (dates, identifiers, references left out), block splitting, rounding rules, every finding C1 to C7 on a synthetic repository, `add` refusals, the results ratchet, kit causal compatibility, `suggest`, the CLI, and this repository's README with its control. They do not check that a reason is true.

## History

- 2026-10-21: first version, with the ledger for this README's 17 claimed blocks ([PR #147](https://github.com/ChaseHendrick/Scrolls/pull/147)).

## Related

- kit causal, where installed: claim-level links from README items to results units; this tool reads its `claims.json`.
- [provenance](provenance.md): hashes for one run's record.
- [`docs/NOVELTY.md`](../NOVELTY.md): claim labels.
- [`docs/results.json`](../results.json): the units cited.
