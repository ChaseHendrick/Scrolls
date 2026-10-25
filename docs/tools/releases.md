# releases: keep the README's Released tools section in step with the release list

`python -m kit releases` keeps `docs/releases.json`, the list of tools released from private work into this repository, and writes the README's "Released tools" section from it: pinned entries first, then newest first.

| Field | Value |
| --- | --- |
| Id | `releases` |
| Status | Current |
| Kind | kit command, kit module, kit entry point |
| Area | Releases and repository |
| Run | `python -m kit releases add`, `python -m kit releases render`, `python -m kit releases check`, `python -m kit releases list`, `python -m kit releases inventory`, `python -m kit releases pin`, `python -m kit releases unpin`, `python -m kit.releases`, `from kit import releases` |
| Code | `kit/releases.py`, `docs/releases.json`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_releases.py`, `tests/test_releases_inventory.py` |
| Needs | Python 3.10 or newer, standard library only. A clone of this repository (it reads `docs/releases.json` and `README.md` next to `kit/`), or `--list` and `--readme` pointing at the two files |
| Runs on | Any machine. `python -m kit releases check` takes about 0.5 s and `python -m kit.releases check` about 0.14 s, almost all of it Python start-up and imports (measured 2026-10-16, 4-core Xeon cloud container, on the 6-entry list) |
| Network | None. Links in an entry are written into the README, never fetched |
| Writes | `check` and `list` write nothing. `add`, `render`, `pin` and `unpin` rewrite the release list (`docs/releases.json`, or `--list`) in its written form and the README (`README.md`, or `--readme`) between its two marker lines; the rest of the README is kept byte for byte |
| Go-ahead | Not needed to run it. An entry merged into public `main` is a public release: its exact text is part of the file list Chase approves (the releases rule, hard rule 15), and pushing or merging it needs his yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-14 ([PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60)); pins since 2026-10-14 ([PR #83](https://github.com/ChaseHendrick/Scrolls/pull/83)). Scrolls-private's submission exporter carries an identical copy of the module |
| Guide | [AGENTS.md](../../AGENTS.md) (the releases rule, hard rule 15, and the standing decisions of 14 October 2026) |
| Checked | 2026-10-20 against commit `457fc5c` |

## What it does

Tools are built in the private repository, Scrolls-private, and some are later released into this public one. The README's "Released tools" section is where a visitor learns what has been released. Chase asked on 14 October 2026 that the README update itself on each release, so the section is no longer written by hand: it is generated from one list, [`docs/releases.json`](../releases.json), with one entry per standalone product. An entry is one JSON object with an id, a title, a release date, a one-paragraph summary, optional commands and a line of details, and where the files are. Chase asked on 20 October 2026 to consolidate releases that are really kit tools, so command-line tools that live in this repository share one grouped entry, Scrolls kit: its optional `tools` list holds one line per tool, each with its own id, release date, optional version, summary, command, tool page and evidence links. A tool's id is unique across entries and tools, so the id of an entry that became a tool (such as `letter-reader`) still names it: `find` resolves it to the grouped entry and the tool, and `add`, `pin` and `unpin` refuse it with the entry to edit instead.

`python -m kit releases` keeps the two in step. `add` puts an entry into the list, or replaces the entry with the same id (a new version or fix of a released tool replaces its entry under the same id and title, Chase's one-entry-per-tool decision of 14 October 2026, narrowed on 20 October 2026 to one entry per standalone product, with kit tools as lines of the Scrolls kit entry), and rewrites the section. `render` rewrites the section from the list. `check` exits 1 when the section is not what the list gives, which is how a hand edit gets caught: `tests/test_releases.py` runs it on the repository, so the unit tests and CI fail on drift. `list` prints the entries in the section's order. `pin ID` shows an entry first, above newer ones, until `unpin ID`; a pin belongs to the list, not to the entry, so a new version that replaces a pinned entry stays pinned. At commit `29e7e8c`, AutoPipeline is pinned first (Chase, 14 October 2026, so people see it) and Unroll second (added with Unroll's entry on 16 October 2026, `9896827`).

An entry's `where` is either `"main"`, for files merged into this repository's `main`, or a package: `{"branch": B, "commit": C, "path": P}`, a reviewed copy that lives on its own branch, such as the Progress Prize exporter's `submission/<submission_id>` branches. The section links a package at its exact commit. The exporter is a private tool; it writes its package's entry with its copy of this module and pushes it as a `release-readme/<submission_id>` branch for a PR into `main`.

It does not publish anything, push, open a PR, or decide what may be released. It checks the form of an entry (lengths, one paragraph, no long dashes, no raw HTML, links only to `https://` or relative targets, no Markdown that could swallow the rest of the README), not whether its links resolve, whether a package's branch and commit exist, or whether the summary's claims are true. A summary that mentions an ink map or ink layer must still say it is model output, not a reading; the tool cannot check that.

## When to use it

- Releasing a tool from private work into public `main`: add its entry in the same change, with `python -m kit releases add ENTRY.json` (the releases rule, hard rule 15).
- A new version or fix of a released tool: `add` an entry with the same `id` and `title`; it replaces the old entry in place and keeps its pin.
- After editing `docs/releases.json` by hand, such as fixing a typo in a summary: `render`, then `check`.
- Before committing anything that touches `README.md` or `docs/releases.json`: `check`.
- When Chase says to pin or unpin an entry: `pin ID` or `unpin ID`.

Do not use it:

- To change the README's "Released tools" section by hand: edit the list and `render` instead; `check` fails on a hand edit.
- To write a tool's reference page: every release also needs a tool page whose id, or Release id field, is the release's id; start it with [`tooldocs`](tooldocs.md) (`python -m kit.tooldocs new`).
- To publish a GitHub release, a Hugging Face Space or a post: those are outward actions that need Chase's yes; this tool only writes two local files.
- From an installed package (`scrolls-workbench releases`): it has no `docs/`; run it from a clone.
- For anything not released publicly: private work and target-scroll results never get an entry (the no-findings rule, hard rule 1).

## Quick start

```bash
# From the repository root: the section's order, then the check the tests run
python -m kit releases list
python -m kit releases check && echo "README and docs/releases.json agree"

# Add or replace an entry, then check again
python -m kit releases add ENTRY.json
python -m kit releases check
```

- `ENTRY.json`: one entry object (fields under Inputs), such as `{"id": "demo-tool", "title": "Demo tool", "released": "2026-10-16", "summary": "Does one thing on public data (Model output). Not a reading.", "commands": ["python -m pip install numpy", "python demo.py --help"], "details": "Guide: docs/demo.md.", "where": "main"}`. Use `-` to read it from stdin.

On the repository at `29e7e8c`, `list` printed:

```
2026-10-16  autopipeline             AutoPipeline  (pinned)
2026-10-16  unroll                   Unroll (interactive 3D scroll viewer)  (pinned)
2026-10-14  stackcheck               Segment stack check
2026-10-14  strokenet                StrokeNet text-likeness score
2026-10-14  umbilicus-finder         Scroll centre (umbilicus) finder
2026-10-14  letter-reader            Greek letter reader
```

and `check` printed nothing and exited 0. On scratch copies (an empty list and a README with an empty marker pair, passed with `--list` and `--readme`), `check` first exited 1, `render` fixed it, and `add` of the entry above printed, the first time and then the second:

```
{"releases": 1, "readme": "/tmp/claude-docs-public-releases/README.md", "id": "demo-tool", "action": "added"}
{"releases": 1, "readme": "/tmp/claude-docs-public-releases/README.md", "id": "demo-tool", "action": "replaced"}
```

It worked when the exit code is 0 and `python -m kit releases check` then exits 0. Review the README diff before committing: the section is what visitors read.

## Checks and controls

- **The check can fail, and does on drift.** `check` rebuilds the section from the list and compares it with the README byte for byte, and also checks that the list file is in its written form. On the scratch README above it printed `... README.md's releases section is not what ... releases.json gives; run python -m kit releases render` and exited 1 before `render`, and 0 after. `tests/test_releases.py` shows it catching a one-sentence hand edit of the intro and a valid list that was not written by the tool (`test_hand_edits_are_caught`).
- **The repository check.** `RepositoryTest.test_readme_section_matches_the_list` runs `check` on this repository's `README.md` and `docs/releases.json` with the unit tests, so CI fails when they disagree. It passed at `29e7e8c` (run 2026-10-16).
- **Bad entries change nothing.** Every action validates the whole list before writing; a refused entry leaves both files untouched (`test_bad_entry_changes_nothing`).
- **What a pass does not show.** A pass means only that the README section and the list agree. It does not show that the links resolve (the repository test of relative links in `tests/test_repo.py` covers those for `main` entries), that a package's branch and commit exist, that the summary is true, or that Chase approved the entry.

Claim label: None. The tool checks form only; the claims inside an entry's summary carry their own labels, written by people (such as "Model output"), which the tool does not check.

## Commands and options

### Options of `python -m kit releases` (before the action)

```
usage: python -m kit releases [-h] [--list REGISTRY] [--readme README]
                              {add,render,check,list,inventory,pin,unpin} ...
```

These two options belong to `releases` itself, so they go before the action: `python -m kit releases --list L --readme R check`. After the action they are refused (`unrecognized arguments`).

| Option | Default | Meaning |
| --- | --- | --- |
| `--list REGISTRY` | `docs/releases.json` of the checkout that holds `kit/` (`REGISTRY`, an absolute path) | The release list to read and rewrite |
| `--readme README` | `README.md` of the checkout that holds `kit/` (`README`, an absolute path) | The README whose generated section is rewritten or checked |

`python -m kit.releases` takes the same options and actions and prints the same usage (its program name is `python -m kit releases`).

### `python -m kit releases add`

```
usage: python -m kit releases add [-h] entry
```

| Option | Default | Meaning |
| --- | --- | --- |
| `entry` | required | A JSON file holding one entry object, or `-` to read it from stdin. An entry whose id is already listed replaces that entry in place (same position, same pin); otherwise it is added at the end of the list. Then both files are rewritten |

### `python -m kit releases render`

```
usage: python -m kit releases render [-h]
```

No options of its own. It validates the list, rewrites it in its written form and rewrites the README's section from it. Use it after editing the list by hand.

### `python -m kit releases check`

```
usage: python -m kit releases check [-h]
```

No options of its own. Exit 0 when the README section is what the list gives and the list is in its written form; exit 1, with each problem on stderr, otherwise. It writes nothing.

### `python -m kit releases list`

```
usage: python -m kit releases list [-h]
```

No options of its own. One line per entry, in the section's order: the release date, the id padded to 24 characters, the title, and `  (pinned)` for a pinned entry. Under a grouped entry, one line per tool: its date, the id indented two spaces and padded to 22 characters, its name, and `  (in ID)` naming the entry.

### `python -m kit releases inventory`

```
usage: python -m kit releases inventory [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | Print the compact inventory records as JSON instead of a Markdown table |

This reads the release list and writes nothing. It includes each standalone entry and each tool inside a grouped entry, in release display order. Every link points to public Scrolls. The same table appears before the detailed entries in the generated public README section.

### `python -m kit releases pin`

```
usage: python -m kit releases pin [-h] id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The id of an entry in the list. It is put at the end of the pins, so it shows after the entries already pinned and above every unpinned one. Pinning an id that is already pinned moves it to the end of the pins |

### `python -m kit releases unpin`

```
usage: python -m kit releases unpin [-h] id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The id of an entry in the list. It leaves the pins and takes its place among the rest by date. Unpinning an id that is not pinned changes nothing but still rewrites both files |

## Python API

```python
from kit import releases
registry_text, readme_text, action = releases.updated(open("docs/releases.json").read(),
                                                      open("README.md").read(), entry)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `ReleaseListError` | An exception class, a subclass of `ValueError` | Not applicable | Every rule below raises it with a message that names the entry id and the field |
| `validate(entry)` | The entry, unchanged | `ReleaseListError` naming the field | The entry rules under Inputs |
| `validate_list(registry)` | The list, unchanged | `ReleaseListError` | The list's shape, every entry, no id twice, and pins that name listed entries once each |
| `dumps(registry)` | str: the written form of the list | `ReleaseListError` | JSON with a 2-space indent, `ensure_ascii=False` and a final newline; keys `schema_version`, then `pinned` only when it is not empty, then `releases`. Both repositories' copies write the same bytes |
| `upsert(registry, entry)` | `(new list, "added" or "replaced")` | `ReleaseListError` | Does not change its input. A replacement keeps the old entry's position and pin |
| `find(registry, some_id)` | `(entry, None)` for an entry's id, or `(grouped entry, tool)` for a tool's id | `ReleaseListError`, including `no entry or tool with that id` | How an old entry id that became a tool still resolves |
| `pin(registry, entry_id, on=True)` | The new list, validated | `ReleaseListError`, including `no entry with that id` | `on=False` unpins. Pinning puts the id at the end of the pins |
| `render_tool(tool)` | str: one tool's Markdown list line | Nothing; `render_entry` validates first | The line format under Inputs |
| `render_entry(entry)` | list of str: one entry's Markdown lines | `ReleaseListError` | A `### TITLE` heading, the picture and its italic caption when the entry has an `image`, the release sentence, the summary, the commands as a `bash` block and the details |
| `ordered(entries, pinned=())` | list: the entries in the section's order | `KeyError` for a pinned id that is not among the entries (`validate_list` prevents it) | Pinned first in pin order; then the newest `released` first; on the same day, the entry later in the list first |
| `inventory(registry)` | list of dicts with `id`, `name`, `url` | `ReleaseListError` for an invalid registry | Includes standalone entries and grouped tools; preserves release order; links only to public Scrolls |
| `render_inventory(items)` | str: a Markdown table | Ordinary key errors for malformed inventory records | Formats inventory records without reading or writing files |
| `intro(registry)` | str: the section's first line | `KeyError` for a pin that is not listed | Names the pinned titles when there are pins |
| `render(registry)` | str: the whole section, marker lines included | `ReleaseListError` | What `render` writes between the markers |
| `apply(readme, registry)` | str: the README with its section rewritten | `ReleaseListError` when the markers are wrong or the list is invalid | Everything outside the markers is kept |
| `updated(registry_text, readme_text, entry)` | `(new list text, new README text, "added" or "replaced")` | `ReleaseListError`; `json.JSONDecodeError` for a list text that is not JSON | Touches no file; the private exporter uses it |
| `check(registry_path=REGISTRY, readme_path=README)` | list of str: problems, empty when the two agree | Nothing for unreadable files, bad JSON or an invalid list: each is returned as a problem | What `check` runs; it also reports an `image.src` under `docs/assets/` that is not a file next to the README |
| `write(registry_path, readme_path, registry)` | None | `OSError`; `ReleaseListError` | Reads the README, builds both texts, then writes the list and then the README |
| `add_arguments(p)` | None | Nothing | Adds `--list`, `--readme` and the actions to an argparse parser; `kit/cli.py` uses it for `python -m kit releases` |
| `run(args)` | int: the exit code, 0, 1 or 2 | Nothing for `OSError` and `ValueError`, which it prints | The command; `kit/cli.py` sets it as the command's function |
| `main(argv=None)` | int: the exit code | `SystemExit` with code 2 on a usage error | Builds its own parser; `python -m kit.releases` and the tests call it |

## Inputs

**The release list**, `docs/releases.json` (or `--list`): one JSON object.

| Key | Type | Rule |
| --- | --- | --- |
| `schema_version` | int | Must be `1` |
| `pinned` | list of str | Optional. Ids of listed entries, each once, shown first in this order. Left out of the written form when empty |
| `releases` | list of objects | The entries, in the order they were added. No id twice |

No other top-level key is allowed.

**An entry** (the object `add` reads, and each item of `releases`):

| Field | Type | Rule |
| --- | --- | --- |
| `id` | str | Required. Lowercase letters, digits and hyphens, starting with a letter or digit, at most 63 characters (`[a-z0-9][a-z0-9-]{0,62}`). A new version of a released tool keeps its id |
| `title` | str | Required. One line, at most 80 characters. Becomes the `### ` heading |
| `released` | str | Required. A real date, `YYYY-MM-DD`. Shown as, say, `16 October 2026` |
| `summary` | str | Required. One paragraph (no line breaks), at most 1,500 characters: what it does, the measured result with its claim label, the main limit |
| `commands` | list of str | Optional. At most 12 lines, each one non-empty line of at most 300 characters with no code fence; shown as a `bash` block |
| `details` | str | Optional. One line of at most 500 characters, such as links to the guide |
| `image` | object | Optional. `{"src": S, "alt": A, "caption": C}`, exactly those keys: a picture shown under the title, with the caption in italics below it. `src` is a path under `docs/assets/` (resolved from the README, so it serves package entries too: the README that shows it is on `main`) or a full `https://` URL, ending in `.webp`, `.png`, `.jpg`, `.jpeg` or `.gif`, with no `..` part. `alt` is one line of at most 300 characters with no square brackets, asterisks or backticks. `caption` is one line of at most 500 characters, with no asterisk and no leading or trailing space, that starts with its media label, one of `LABELS`: `Concept illustration`, `Real data render`, `Model output` or `Synthetic demo` ([media labels](../assets/README.md)). Both follow the rules for every text value below; a package's caption links are full `https://` URLs |
| `tools` | list of objects | Optional; makes a grouped entry (since 20 October 2026). 1 to 64 tools, shown after the commands as a Markdown list, one line each, in list order. The entry's `where` must be `"main"` and its `released` must be its newest tool's date; the release sentence then gives the range of the tools' dates |
| `where` | `"main"`, or an object | Required. `"main"` for files merged here, or `{"branch": B, "commit": C, "path": P}` for a package on its own branch |

**A tool** (each item of a grouped entry's `tools`), shown as one list line: the name in bold; in brackets the version, when given, and the release date; the summary; the word Run with the command as inline code; a link named tool page to its page; then the evidence links:

| Field | Type | Rule |
| --- | --- | --- |
| `id` | str | Required. The id pattern above; unique across every entry and tool in the list, and not the entry's own id. A tool that had an entry of its own keeps that id |
| `name` | str | Required. One line, at most 80 characters, no asterisks (it is shown in bold) |
| `released` | str | Required. A real date, `YYYY-MM-DD`: the tool's own release date |
| `version` | str | Optional. One line, at most 120 characters, such as ``weights `strokenet-paris4-v1` `` |
| `summary` | str | Required. One paragraph, at most 800 characters: what it does, its result with its claim label, its main limit |
| `command` | str | Required. One line, at most 300 characters, no backticks (it is shown as inline code) |
| `page` | str | Required. Its tool page, `docs/tools/NAME.md`; `check` fails when the file is missing |
| `evidence` | str | Optional. One line of links, at most 400 characters |

Every tool text follows the rules for every text value below (no HTML comment, no long dash, no raw HTML, links `https://` or relative) and has no leading or trailing space.

Rules for every text value: no HTML comment marker (`<!--` or `-->`), and no long dash (U+2014 or U+2013). The `title`, `summary` and `details` may not hold raw HTML anywhere (a `<` followed by a letter, `/`, `!` or `?`; an `https://` autolink such as `<https://example.org>` is allowed, and so is a bare `<` such as `x<3`), and every link target in them, inline (a target in round brackets after the link text) or as a reference definition (`[x]: TARGET`), is either `https://...` or relative (no scheme such as `http:`, `javascript:` or `data:`, no `//host`, no backslash). Commands are exempt from both, since they are shown in a `bash` block. The `summary` and `details` may not start with a space, a tab, a code fence (three backticks or three tildes) or `<`, because a code block or HTML block opened there would run past the end marker and swallow the rest of the README.

Rules for a package (`where` is an object): exactly the three keys; `branch` matches `[A-Za-z0-9_][A-Za-z0-9_./-]{0,99}`, has no `..` and is not `main`; `commit` is the full 40-character lowercase hex commit; `path` is a simple relative path (no leading `/`, no `.` or `..` parts); the summary, details and commands never use `python -m kit` or `python3 -m kit` (a package runs its own files, and the repository test of documented kit commands checks every `python -m kit` in the README against this repository's kit); and every link in the summary and details is a full `https://` URL, because a relative link would point into `main`, not into the package. A `"main"` entry may use relative links; they resolve from the README, at the repository root.

At `29e7e8c` the list holds 6 entries; the longest summary, AutoPipeline's, is 1,480 characters, near the 1,500 limit. Since 20 October 2026 it holds 6 entries, one of them Scrolls kit with 4 tools.

**The README** (or `--readme`): it must hold exactly one line that starts with `<!-- releases:start` and exactly one line that is `<!-- releases:end -->`, in that order. Everything between and including them is generated.

## Outputs

`inventory --json` prints a JSON array. Each object has `id` (stable tool or product id), `name` (display name) and `url` (public documentation link). Without `--json`, it prints the same records as a Markdown table. The inventory carries no benchmark values and does not fetch or validate its links.


What each action prints on stdout:

| Action | Prints |
| --- | --- |
| `add` | One JSON line: `{"releases": N, "readme": PATH, "id": ID, "action": "added" or "replaced"}` |
| `render`, `pin`, `unpin` | One JSON line: `{"releases": N, "readme": PATH}` |
| `list` | One line per entry: `RELEASED  ID TITLE`, with `  (pinned)` after a pinned one |
| `check` | Nothing; problems go to stderr |

| Field | Type | Meaning |
| --- | --- | --- |
| `releases` | int | Entries in the list after the action |
| `readme` | str | The README path written, as given or the default |
| `id` | str | `add` only: the entry's id |
| `action` | str | `add` only: `added` (new id, appended) or `replaced` (an entry with this id was there) |

**Files.** The list is rewritten in its written form (see `dumps` under Python API); entries keep the key order they were given in. The README's section reads, from top to bottom: the start marker line; the intro, `Released tools, newest first. Each entry comes from LINK.` (LINK is a Markdown link to `docs/releases.json`), which with pins names them, as in `..., AutoPipeline and Unroll (interactive 3D scroll viewer) first and the rest newest first. ...`; then for each entry a blank line, `### TITLE`, `Released 16 October 2026.` (for a package: `Released DATE as a reviewed package on branch `B`: ` and a link to `https://github.com/ChaseHendrick/Scrolls/tree/COMMIT/PATH` shown with the 7-character commit), the summary, the commands in a `bash` block and the details; and the end marker line.

| Exit code | Meaning |
| --- | --- |
| `0` | Done. For `check`: the README section and the list agree |
| `1` | `check` only: they disagree, or a file could not be read or parsed; each problem is on stderr |
| `2` | Any other action refused: no list file, a bad entry or list, an unknown id, wrong README markers, or a file it could not read or write, with `releases: ` and the reason on stderr; nothing was written. Also a usage error from the argument parser |

## Failure modes

Messages of `add`, `render`, `list`, `pin` and `unpin` start with `releases: ` (exit 2); `check` prints its problems without the prefix (exit 1). `ID`, `KEY` and `PATH` stand for the entry id, the field and the file.

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `python -m kit: error: unrecognized arguments: --list ...` | `--list` or `--readme` given after the action | Put them before the action: `python -m kit releases --list L --readme R check` |
| `python -m kit releases: error: the following arguments are required: action` | No action given | Add one of `add`, `render`, `check`, `list`, `pin`, `unpin` |
| `releases: no release list at PATH; it reads the repository's docs/releases.json and README.md, which an installed package does not have: run it from a clone (git clone https://github.com/ChaseHendrick/Scrolls), or give --list and --readme` | The list file is not there: an installed package (`scrolls-workbench releases`), or a wrong `--list` | Run it from a clone, or give `--list` and `--readme` |
| `PATH's releases section is not what PATH gives; run python -m kit releases render` | `check`: the README section was edited by hand, or the list changed without `render` | Run `python -m kit releases render` and review the README diff; move any wanted hand edit into the list first |
| `PATH is not in its written form; run python -m kit releases render` | `check`: the list is valid but was not written by the tool (other indentation, key order or no final newline) | Run `python -m kit releases render` |
| `README needs exactly one releases:start line followed by one releases:end line` | A marker line is missing, doubled or in the wrong order | Restore the two marker lines exactly as in `START` and `END` |
| `an entry must be a JSON object` | The entry file holds a list or a string | Give one object |
| `ID: unknown fields [...]` | A field outside `id`, `title`, `released`, `summary`, `commands`, `details`, `image`, `where` | Remove it |
| `ID: missing [...]` | A required field is missing | Add `id`, `title`, `released`, `summary` and `where` |
| `id 'X' must be lowercase letters, digits and hyphens` | The id has capitals, underscores, a leading hyphen, or is over 63 characters | Use a short id such as `letter-reader` |
| `ID: KEY must be a non-empty string` | A title, summary or details that is empty, blank or not a string | Write the text |
| `ID: KEY is longer than N characters` | Title over 80, summary over 1,500 or details over 500 characters | Shorten it; move detail to the tool's guide and link it |
| `ID: KEY must be one line or one paragraph` | A line break in the title, summary or details | Make it one paragraph |
| `ID: KEY may not hold an HTML comment` | `<!--` or `-->` in a value, which could fake or break the markers | Remove it |
| `ID: KEY has a long dash (house style: none)` | U+2014 or U+2013 in a value (the style rule, hard rule 10) | Use a comma, a colon or "to" |
| `ID: KEY may not hold raw HTML` | An HTML tag anywhere in the title, summary or details, such as `<details>`, `<a href=...>` or `<img ...>`, which could hide or relink the rest of the README | Write plain Markdown; an `https://` autolink in angle brackets is fine |
| `ID: KEY links must be https:// or relative, not 'TARGET'` | A link target with another scheme (`http:`, `javascript:`, `data:`), or starting with `//` or holding a backslash; TARGET is its first 40 characters | Link by `https://` URL, or by a relative path for a `main` entry |
| `ID: KEY may not start with a space, a code fence or an HTML tag` | The summary or details starts with whitespace, three backticks, three tildes or `<` | Start with a word |
| `ID: released must be a date, YYYY-MM-DD` | Not that form, or not a real date (such as `2026-02-30`) | Write the release date as `YYYY-MM-DD` |
| `ID: commands must be a list of at most 12 lines` | `commands` is a string, or has more than 12 lines | Give a list of at most 12 strings |
| `ID: each command is one non-empty line with no code fence` | An empty command, a line break or three backticks in one | One command per string |
| `ID: a command is longer than 300 characters` | A very long command line | Shorten it, or move it to the guide |
| `ID: where is "main" or {branch, commit, path}` | `where` is another string, or an object with other keys | Use `"main"` or exactly the three keys |
| `ID: where.branch is not a plain branch name` | The branch is `main`, starts with `-`, holds `..` or other characters | Give the package's own branch, such as `submission/<submission_id>` |
| `ID: where.commit must be a full 40-character commit` | A short or uppercase hash | Give the full lowercase hash (`git rev-parse COMMIT`) |
| `ID: where.path must be a simple relative path` | A leading `/`, `.` or `..` parts, or spaces | Give the package folder as a relative path |
| `ID: a package's commands run its own files (python scripts/...), never "python -m kit", which the README checks against this repository's kit` | A package entry mentions `python -m kit` or `python3 -m kit` | Use the package's own entry points, such as `python scripts/NAME.py` |
| `ID: a package's links are full https:// URLs at its commit` | A relative link in a package entry, including its image caption (an `http://` link is refused earlier, by the links rule for every entry) | Link the package's files by `https://` URL at its commit |
| `ID: image is {src, alt, caption}` | `image` is not an object, or has other or missing keys | Give exactly `src`, `alt` and `caption` |
| `ID: image.src is a docs/assets/ path or an https:// URL ending in .webp, .png, .jpg, .jpeg or .gif` | The picture is elsewhere in the tree, has a space, a `..` part, another scheme, or a format GitHub does not show inline (such as `.svg` or `.mp4`) | Put the picture under `docs/assets/` (see [its README](../assets/README.md)) or give its `https://` URL |
| `ID: image.KEY must be one line of at most N characters` | An empty, multi-line or too long `alt` (300) or `caption` (500), or not a string | Shorten it to one line |
| `ID: image.alt is plain text, without square brackets, asterisks or backticks` | Markdown in the alt text, which would break the picture's syntax | Describe the picture in plain words |
| `ID: image.caption has no asterisks and no leading or trailing space` | The caption is shown in italics, which an asterisk or edge space would break | Remove them |
| `ID: image.caption starts with its label, one of Concept illustration, Real data render, Model output, Synthetic demo` | The caption does not begin with its media label | Start it with the label, such as `Concept illustration. ...` |
| `PATH shows pictures that are not in the tree: SRC, ...` | `check`: an entry's `image.src` under `docs/assets/` names a file that is not there | Add the picture (with its row in `docs/assets/README.md`) or fix the path |
| `ID: listed twice` | Two entries with one id (a hand edit) | Keep one entry per tool |
| `the list is {"schema_version": 1, "pinned": [ids, optional], "releases": [...]}` | The list is not an object, `schema_version` is not 1, or it has other top-level keys | Restore the list's shape |
| `releases must be a list` | `releases` is not a list | Restore it |
| `pinned must list ids of entries in the list, each once` | A pin names an id that is not listed, an id twice, or a non-string | Fix `pinned`, or use `pin` and `unpin` |
| `ID: tools must be a list of 1 to 64 tools` | `tools` is not a list, is empty, or has more than 64 tools | Give 1 to 64 tool objects |
| `ID: an entry with tools lists tools merged here; its where is "main"` | A grouped entry with a package `where` | Group only tools merged into `main` |
| `ID: released is its newest tool's date, DATE` | A grouped entry's `released` differs from its newest tool's | Set it to DATE |
| `ID: each tool is a JSON object` | A tool is a string or a list | Give an object |
| `ID: tool TOOL: unknown fields [...]`, `ID: tool TOOL: missing [...]`, `ID: tool id 'X' must be lowercase letters, digits and hyphens` | A field outside the tool fields, a required tool field missing, or a bad tool id | Use the tool fields under Inputs |
| `ID: tool TOOL: listed twice`, `TOOL: listed twice` | A tool id used twice in the entry, equal to the entry's id, or equal to another entry's or tool's id | Keep one id per tool |
| `ID: tool TOOL: KEY has a leading or trailing space` | A tool text starts or ends with a space | Trim it |
| `ID: tool TOOL: name has no asterisks (it is shown in bold)` | An asterisk in the name | Remove it |
| `ID: tool TOOL: command has no backticks (it is shown as inline code)` | A backtick in the command | Remove it, or move the example to the tool page |
| `ID: tool TOOL: page is a tool page, docs/tools/NAME.md` | `page` is not a `docs/tools/` page path | Link the tool's page |
| `PATH links tool pages that are not in the tree: PAGE, ...` | `check`: a tool's page is missing | Write the page (`python -m kit.tooldocs new`) or fix the path |
| `TOOL: a tool in the ID entry, not an entry of its own; ...` | `add` of an entry, or `pin` or `unpin`, with a tool's id | Edit the tool's line in that entry's `tools` and `add` the whole entry, or pin the entry |
| `ID: no entry or tool with that id` | `find` of an id that is in neither the entries nor their tools | Check the id with `list` |
| `ID: no entry with that id` | `pin` or `unpin` of an id that is not in the list | Check the id with `list` |
| `releases: Expecting value: line 1 column 1 (char 0)`, or another JSON message | The entry or the list is not valid JSON | Fix the JSON |
| `releases: [Errno 2] No such file or directory: 'PATH'` | The entry file or the README is missing | Fix the path |
| `releases: [Errno 32] Broken pipe` | `list` piped into a command that stops reading early, such as `head` | Harmless; the list was only being printed |

## How it works

1. Read the list (`--list`); with no file there, stop with the clone hint (exit 2).
2. `check`: rebuild the section from the list (`apply`), compare it with the README, and compare the list file with its written form (`dumps`); report any difference.
3. `add`: parse the entry (from the file, or stdin for `-`), validate it and the whole list, then replace the entry with its id or append it (`upsert`). `pin` and `unpin` remove the id from the pins and, for `pin`, append it (`pin`).
4. Order the entries (`ordered`): pinned ids first, in pin order; then the rest sorted by `(released, position in the list)`, largest first, so the newest date comes first and, on the same day, the entry added later.
5. Render (`render`): the start marker, the intro (`intro`, which names the pinned titles), each entry (`render_entry`), the end marker.
6. Write (`write`): read the README, splice the section in place of the old one between the markers (`apply`), write the list, then the README.

Constants that matter, from `kit/releases.py`:

| Constant | Value |
| --- | --- |
| `START` | `<!-- releases:start (generated from docs/releases.json by python -m kit releases render; edit that list, not this section) -->` (a README line is found by its start, `<!-- releases:start`) |
| `END` | `<!-- releases:end -->` |
| `INTRO` | `Released tools, newest first. Each entry comes from LINK.` (LINK is a Markdown link to `docs/releases.json`) |
| `FIELDS`, `REQUIRED` | The eight entry fields (`image` since 18 October 2026); `id`, `title`, `released`, `summary`, `where` are required |
| `REPO_URL` | `https://github.com/ChaseHendrick/Scrolls`, the base of a package's link |
| `BLOCK_OPENER` | Whitespace, three backticks, three tildes or `<` at the start of a summary or details |
| `KIT_COMMAND` | `python3? -m kit ` (refused in a package entry) |
| `RELATIVE_LINK` | `](` not followed by `https://` (refused in a package entry) |
| `INLINE_HTML`, `HTTPS_AUTOLINK` | `<` followed by optional space and a letter, `/`, `!` or `?` (refused in a title, summary or details), after removing `<https://...>` autolinks |
| `LINK_TARGET`, `URL_SCHEME` | A link target, inline or in a reference definition, and the scheme, `//` or backslash that makes it refused unless it starts with `https://` |
| `IMAGE_FIELDS`, `IMAGE_SRC`, `LABELS` | An image's three keys; its `src` pattern (a `docs/assets/` path or an `https://` URL, ending in `.webp`, `.png`, `.jpg`, `.jpeg` or `.gif`); the four media labels a caption starts with |
| `TOOL_FIELDS`, `TOOL_REQUIRED`, `TOOL_PAGE`, `MAX_TOOLS` | A tool's eight fields and the six required ones; its page pattern (`docs/tools/NAME.md`); at most 64 tools in a grouped entry |
| Limits | id 63 characters, title 80, summary 1,500, details 500, 12 commands of 300 characters; a tool's name 80, version 120, summary 800, command 300, evidence 400 |

The write is not atomic across the two files: the list is written first, then the README. If the README write failed, `check` would report the mismatch and `render` would repair it.

## Cost and time

Measured 2026-10-16 in a 4-core Xeon cloud container (`/proc/cpuinfo` reports 2.80 GHz), on the 6-entry list at `29e7e8c`: `python -m kit releases check` 0.49 s, `python -m kit releases list` about 0.35 s, `python -m kit.releases check` 0.14 s; peak memory 23 MB through `python -m kit` and 12 MB through `python -m kit.releases`. The difference is `python -m kit` importing every command's module. Nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit releases add ENTRY.json` and then `python -m kit releases check`; `add` prints one JSON line. To see the order: `python -m kit releases list`.
- **Parse:** `add`'s `action` (`added` or `replaced`) and `releases` (the count); `check` by its exit code alone, with problems on stderr; `list` lines as date, id, title and an optional `(pinned)`.
- **Rerun:** Safe. `add` of the same file again replaces the entry with itself (`replaced`); `render` is idempotent; `pin` of an id that is already pinned moves it to the end of the pins, so it is not a no-op. Every writing action rewrites `docs/releases.json` and the README section in full.
- **Success:** Exit code 0, then `python -m kit releases check` exits 0, and the README diff shows only the intended entry change.
- **Not a pass:** `check` exit 0 shows only that the README and the list agree: not that links resolve, that a package's branch and commit exist, that the summary's claims are true and labelled, or that Chase approved the entry.
- **Go-ahead:** Committing an entry to a branch is fine; merging or pushing it into public `main` releases the tool and needs Chase's yes on the exact file list, entry included (the go-ahead rule, hard rule 8). `pin` and `unpin` only when Chase says so; AutoPipeline stays pinned first until he says otherwise (standing decision of 14 October 2026).
- **Never:** Edit the README's "Released tools" section by hand; add a second entry for a new version of a released tool (replace it under the same id and title; for a kit tool, replace its line in the Scrolls kit entry's `tools`); give a command-line kit tool an entry of its own (it joins the Scrolls kit entry); run `pin autopipeline` while it is already pinned (that moves it below Unroll); add an entry for private work or with target-scroll results; write `python -m kit` in a package entry; let a summary call an ink map or ink layer a reading.

## Tests

`python3 -m unittest tests.test_releases_inventory` checks the complete compact inventory, grouped tools, deterministic links and the command output. In the private repo, it checks that the snapshot has public provenance and the README matches its recorded rows.


```bash
python -m unittest tests.test_releases -v
```

29 tests, 0.2 s (2026-10-20). They cover good and bad entries (every validation rule, including the package rules), grouped entries (good and bad tools, one line per tool, unique and resolvable tool ids, `add` and `pin` refusing a tool's id, `list` and `check` with tool pages), the list's shape and pins, rendering of `main` and package entries, the order (newest first, later entry first on a day, pins first) and the intro, `apply` keeping the text outside the markers and refusing wrong markers, `upsert` adding then replacing without changing its input, pins surviving a new version, `updated`, the command line (the clone hint without a list, check, render, add, list, pin and unpin, hand edits caught, a bad entry changing nothing, the command registered in `kit/cli.py`), and `check` on this repository's own README and list. They do not cover `add -` (stdin), which was run by hand for this page, a README write failing halfway, or whether a package's branch and commit exist. `tests/test_repo.py` separately checks every `python -m kit` command written in the README and every relative link in it.

## History

- 2026-10-25: added the compact inventory API and command, with README consistency tests (`651231c` base).

- 2026-10-20: grouped entries: an entry's optional `tools` lists command-line tools that share it, one line each; Scrolls kit groups Scroll Text Reader, StrokeNet, the segment stack check and the Center Finder, whose old ids still resolve (`find`), and `list` shows each tool under its entry (Chase's decision of 20 October 2026) (`ba08f7e`).
- 2026-10-16: the letter reader's entry gives the plain character error beside the free-ends error on PHerc. 1667 maps (`2b8c445`).
- 2026-10-16: entries may not hold raw HTML in a title, summary or details, and their links must be `https://` or relative (`eb88e23`).
- 2026-10-16: Unroll's entry added and pinned after AutoPipeline (`9896827`).
- 2026-10-14: pins: `pin ID` and `unpin ID`, `list` marks pinned entries, and the intro names them; AutoPipeline pinned (`2bb459c`, [PR #83](https://github.com/ChaseHendrick/Scrolls/pull/83)).
- 2026-10-14: without `docs/releases.json` (an installed package) it says to run from a clone instead of a bare file error (`ca7b143`).
- 2026-10-14: review fixes: a summary or details may not open a code fence, an HTML block or an indented code block; a package entry may not use `python -m kit` or relative links (`2a7d961`).
- 2026-10-14: first version: `docs/releases.json`, `add`, `render`, `check` and `list`, and the README section generated from the list (`62049c7`, [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60)).

## Related

- [README "Released tools"](../../README.md#released-tools): the section this tool writes.
- [`releases.json`](../releases.json): the list itself.
- [`tooldocs`](tooldocs.md): every release also needs a tool page whose id or Release id is the release id.
- [`autopipeline`](autopipeline.md), [`unroll`](unroll.md), [`scroll-lens`](scroll-lens.md), [`inkfilter`](inkfilter.md), [`starter`](starter.md): the pages of the standalone products; [`cli`](cli.md) (Release id `scrolls-kit`), [`letterread`](letterread.md), [`strokenet`](strokenet.md), [`stackcheck`](stackcheck.md), [`umbilicus`](umbilicus.md): the Scrolls kit entry and its tools.
- [`cli`](cli.md): the `python -m kit` entry point that registers this command.
- [AGENTS.md](../../AGENTS.md): the releases rule and the standing decisions on one entry per standalone product (kit tools share Scrolls kit) and on AutoPipeline's pin.
- [Pull request template](../../.github/PULL_REQUEST_TEMPLATE.md): its checklist asks for the entry when a PR releases private work.
