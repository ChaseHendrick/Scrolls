# tooldocs: check, index, show and start the tool pages

`python -m kit.tooldocs` checks every page in `docs/tools/` against the standard in `docs/TOOL-DOCS.md` and against the code, writes the index, prints a page or one section of it for agents, and starts new pages prefilled from the code.

| Field | Value |
| --- | --- |
| Id | `tooldocs` |
| Status | Current |
| Kind | kit entry point |
| Area | Releases and repository |
| Run | `python -m kit.tooldocs check`, `python -m kit.tooldocs index`, `python -m kit.tooldocs list`, `python -m kit.tooldocs show`, `python -m kit.tooldocs new`, `python -m kit.tooldocs stale`, `from kit import tooldocs` |
| Code | `kit/tooldocs.py`, `templates/tool-doc.md`, `templates/tool-doc-branch.md`, `docs/TOOL-DOCS.md` |
| Tests | `tests/test_tooldocs.py` |
| Needs | Python 3.10 or newer, standard library only. git, for the tracked-file list, commit checks, `stale` and the history that `new` prefills; a clone with full history for the commit checks (a shallow clone skips them). It imports `kit.cli` to read the `python -m kit` parser |
| Runs on | Any CPU. The full check took 2.1 s wall and one page (`check --page auc`) 0.2 s, with 41 pages in `docs/tools/`; `stale` took 0.5 s (measured 2026-10-16, 4-core cloud container) |
| Network | None. It runs git locally and reads `git remote get-url origin` only to tell public Scrolls from Scrolls-private |
| Writes | `check`, `list`, `show` and `stale`: nothing (they print). `index`: rewrites the generated block of `docs/tools/README.md` and all of `docs/tools/index.json`. `new`: creates `docs/tools/ID.md`, and refuses when it exists |
| Go-ahead | Not needed |
| Released | Not yet on public `main`: on the branch `claude/tool-docs-k5afs7` since 2026-10-16 (`1d07cb3` onwards) |
| Guide | [TOOL-DOCS.md](../TOOL-DOCS.md), the standard the pages follow |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

Every tool in the repository has one page in `docs/tools/` (the tool-pages rule, hard rule 16). Pages drift: an option is added, a default changes, an error message is reworded, and the page still says the old thing. `kit.tooldocs` is the checker that catches that drift. It reads each page, checks its shape against the standard in [`docs/TOOL-DOCS.md`](../TOOL-DOCS.md), and checks what it names against the code: that every path and function exists, that every option, positional argument and default of each `python -m kit` command it runs matches the parser, that every public function, error message and environment variable of the code it names is on the page, and that every kit module, package, script, command, action, project skill, CI workflow and release has a page. `tests/test_tooldocs.py` runs the full check, so the tests fail when a page is missing or out of step.

It also does four smaller jobs. `index` writes the generated tables of [`docs/tools/README.md`](README.md) and the machine-readable [`docs/tools/index.json`](index.json). `list` and `show` print the index, a page, one section or one field, so an agent can read only what it needs. `new` starts a page from [`templates/tool-doc.md`](../../templates/tool-doc.md) (or [`templates/tool-doc-branch.md`](../../templates/tool-doc-branch.md) for a Branch only tool), prefilled from the code. `stale` lists pages whose main code file has a newer commit than the page.

It cannot check that the prose is true. A page that passes has the right shape and names things that exist and match the code; whether its Quick start runs, its How it works matches the method and its numbers match their sources is for a reviewer. `tool docs pass` is not a review.

Scrolls-private carries an identical copy of `kit/tooldocs.py` and its own copy of the standard; the module's docstring asks that the two copies stay the same. This page covers the public copy.

## When to use it

- While writing or changing a page: `python -m kit.tooldocs check --page ID` until it prints `tool docs pass`.
- Before a commit that changes a tool or a page: `python -m kit.tooldocs check` (the tests run the same check).
- To start a page for a new tool: `python -m kit.tooldocs new`.
- To read one tool's rules quickly as an agent: `python -m kit.tooldocs show ID --section "For agents"` and `--field NAME`.
- After pages are added or changed, once, by the lead of a batch of pages: `python -m kit.tooldocs index`.
- To find pages that may need a review after code changes: `python -m kit.tooldocs stale`.

Do not use it:

- To check the repository's other rules (dashes in every file, documented commands existing, the `w045` wording): `tests/test_repo.py` does that, with `python -m unittest tests.test_repo`.
- To check the README's "Released tools" section: use [`releases`](releases.md) (`python -m kit releases check`).
- To learn what a page must say: read [`docs/TOOL-DOCS.md`](../TOOL-DOCS.md); this tool only enforces it.

## Quick start

```bash
python -m kit.tooldocs new ID --kind "KIND" --area "AREA" --command "CMD [ACTION]" --code PATH
python -m kit.tooldocs check --page ID
python -m kit.tooldocs show ID --section "For agents"
python -m kit.tooldocs check
```

- `ID`: the page id, lowercase letters, digits and hyphens, such as `auc`.
- `KIND`: one or more kind words of the standard, comma-separated, such as `kit command, kit module`.
- `AREA`: one area word of the standard, such as `Scoring and controls`.
- `CMD [ACTION]`: a `python -m kit` command, and its action where it has actions, such as `auc` or `run init`; repeat `--command` for more. Leave it out for a tool that is not a kit command.
- `PATH`: a file or folder of the tool, main file first; repeat `--code` for more.

Run on 2026-10-16 in the checkout (real pages, not synthetic), `new` printed:

```
wrote docs/tools/cli.md; replace every <!-- Write: ... --> with the text, then run python -m kit.tooldocs check --page cli
```

`check --page auc` printed `tool docs pass (pages auc)` with exit code 0. `show auc --field Writes` printed the field's value alone. While other pages were still being written, the full `check` printed one line per problem, such as `docs/tools/experiment-records.md: a page of kind data needs the field 'License'`, then `130 problem(s); the standard is docs/TOOL-DOCS.md` on stderr, with exit code 1.

It worked when `check` prints `tool docs pass (...)` and exits with 0.

## Checks and controls

- **The checker must be able to fail.** `tests/test_tooldocs.py` builds pages and small repositories with known faults (a missing, doubled, empty or out-of-order section, a wrong field, a leftover `<!-- Write:`, a U+2014 dash, an unclosed code block, a usage block or a default that differs from the parser, an option row the command does not have, a missing public function or error message, an undocumented environment variable, an uncovered module or command) and asserts that each is reported, and that a correct page passes. `new` is tested to produce a page that fails the check until it is written.
- **Gaps** (found while writing this page, 2026-10-16, by reading the code):
  - Error messages are found only as string literals or f-strings in `raise`, `sys.exit`, `parser.error` and some `print(..., file=sys.stderr)` calls, and only their longest literal stretch of at least `MIN_MESSAGE` = 12 characters. A message built another way is missed: this module's own `no tool page 'ID'; close: ...` (a string concatenation) and `no section 'NAME'; sections: ...` (no literal stretch of 12 characters) are not required on this page by the checker.
  - A `kit/` file named in Code with functions in brackets skips the public-function check: only the named functions' error messages and environment variables are checked.
  - A Run entry that is not `python -m kit COMMAND`, `python -m kit.MODULE` or a script path, such as `python -m kit` alone, is not checked against anything.
  - Commits named in Checked and Branch are checked only in a clone with full history; CI clones at depth 1 and skips them.
  - The link rule for public pages looks only for GitHub links to a file, folder, commit or pull request of the private repository (its `blob`, `tree`, `commit` and `pull` pages); it does not read the words on the page.

Claim label: None; a pass means the pages match the standard's shape and the code's names, options and messages, not that their prose or numbers are true.

## Commands and options

### `python -m kit.tooldocs`

```
usage: python -m kit.tooldocs [-h] {check,index,list,show,new,stale} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `action` | required | One of `check`, `index`, `list`, `show`, `new`, `stale` |

### `python -m kit.tooldocs check`

```
usage: python -m kit.tooldocs check [-h] [--page ID] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--page ID` | none (every page, plus coverage and the index) | Check only this page; repeatable. With `--page`, coverage, `pending.json` and the index are not checked |
| `--json` | off | Print the problems as a JSON list of `{"page", "problem"}` instead of lines; prints `[]` and no pass line when there are none |

### `python -m kit.tooldocs index`

```
usage: python -m kit.tooldocs index [-h]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-h`, `--help` | off | The only option. It rewrites the block between the two marker lines of `docs/tools/README.md` (keeping the text above and below) and all of `docs/tools/index.json`; with no README it writes the default intro and the block |

### `python -m kit.tooldocs list`

```
usage: python -m kit.tooldocs list [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | Print the index as JSON, the same text as `docs/tools/index.json` would hold now, instead of one line per tool |

### `python -m kit.tooldocs show`

```
usage: python -m kit.tooldocs show [-h] [--section NAME | --field NAME] id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The page id, the file name without `.md` |
| `--section NAME` | none | Print only this `##` section, as `## NAME` and its body, such as `For agents`. Not with `--field` |
| `--field NAME` | none | Print only this At a glance field's value, such as `Writes`. Not with `--section` |

### `python -m kit.tooldocs new`

```
usage: python -m kit.tooldocs new [-h] [--kind KIND]
                                  [--area {Pipeline and agents,Data and downloads,Surfaces and tracing,Ink maps and models,Scoring and controls,Letters and titles,Training,Compute and cost,Records and provenance,Planning and prizes,Releases and repository,Viewers and apps}]
                                  [--status {Current,Experimental,Retired,Branch only}]
                                  [--command CMD [ACTION]] [--code PATH]
                                  id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The new page's id: lowercase letters, digits and hyphens (`ID_RE`) |
| `--kind KIND` | `kit command` | One or more of the kind words (`KINDS`), comma-separated, such as `kit command, kit module` |
| `--area AREA` | none (the field is left for you to write) | One of the twelve area words (`AREAS`); argparse refuses any other |
| `--status STATUS` | `Current` | `Current`, `Experimental`, `Retired` or `Branch only`. `Branch only` uses the branch template and does not need `--code` paths to exist |
| `--command CMD [ACTION]` | none | A `python -m kit` command, and its action, that the page documents, such as `auc` or `run init`; repeatable. Fills Run, the usage blocks and option tables, and adds the command's `cmd_` function to Code as `kit/cli.py` (`cmd_X`) |
| `--code PATH` | none | A file or folder of the tool, main file first; repeatable. Fills Code, Tests, the Python API rows, error messages, environment variables and history |

### `python -m kit.tooldocs stale`

```
usage: python -m kit.tooldocs stale [-h]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-h`, `--help` | off | The only option. Compares, for each page, the last commit of the first path in its Code field with the last commit of the page |

### Environment variables

None. The module reads no environment variables.

## Python API

```python
from kit import tooldocs
problems = tooldocs.check_all(page_ids=["auc"])      # [] when the page passes
pages = tooldocs.load_pages(tooldocs.ROOT / "docs" / "tools")
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `Page(path, text)` | A parsed page: `title`, `summary`, `fields` (dict), `order`, `sections`, `bodies`, `lines` (first and last line of each section), `problems` (parse problems); methods `field(name)`, `spans(name)`, `code_items()`, `runs()`, `body(name)`, `prose()`, `code_text()`, `subsections(section)`; property `id` (the file stem) | Nothing; shape faults go to `problems` | Headings inside fenced blocks are not sections |
| `Commands(parser)` | `parsers`: canonical command to `{None: parser, ACTION: parser}`, and `aliases`: name to canonical name; method `target(span)` gives `(command, action or None)` for a `python -m kit ...` text, or `None` | `StopIteration` when the parser has no sub-commands | A word after a command without actions is taken as a positional argument, not an action |
| `Context(root=ROOT, commands=None, pending=(), kind=None, git=False)` | What a page check needs: the repository root, the `Commands`, the pending ids, `"public"`, `"private"` or `None`, and whether commits can be looked up | Nothing | |
| `kit_commands()` | `Commands` of `kit.cli.build_parser()` | Whatever building the parser raises | |
| `check_page(page, ctx)` | list of str, one problem each | Nothing for a well-formed `ctx` | Shape, sections, leftovers, links, code and commands of one page |
| `check_all(root=ROOT, page_ids=None, commands=None)` | list of str: problems prefixed `docs/tools/ID.md: ` where they belong to a page | Nothing; a parser that will not build and a `pending.json` that does not parse come back as one problem each | With `page_ids`, only those pages. Without, also coverage, `pending.json` and the index. Builds kit's parser only when `root` is this checkout |
| `coverage(pages, files, commands, releases=(), pending=None)` | list of str: targets no page covers and `pending.json` does not list, and pending entries that are done or no longer needed | Nothing | |
| `coverage_targets(files, commands, releases=())` | list of str: every thing that needs a page, such as `kit/auc.py`, `scripts/umbilicus`, `python -m kit run init`, `release unroll` | Nothing | `files` are paths relative to the root |
| `uncovered(pages, files, commands, releases=())` | list of str: the targets no page names | Nothing | Ignores `pending.json` |
| `load_pages(pages_dir)` | list of `Page`, sorted by file name, `README.md` left out | `OSError` for an unreadable file | A page that is not UTF-8 becomes a `Page` with one problem |
| `load_pending(root)` | dict: id to `{"group", "covers"}` from `docs/tools/pending.json`, or `{}` when there is no file | `ValueError` (a `json.JSONDecodeError`) when it does not parse | |
| `render_index(pages, current=None)` | str: the README text with a new generated block, or the default intro and block when `current` has no markers | Nothing | |
| `render_json(pages, root, kind=None)` | str: the `index.json` text (fields under Outputs) | Nothing | |
| `write_index(root=ROOT)` | int: the number of pages | `ValueError` when `docs/tools/README.md` exists without its marker lines | Writes both index files |
| `stale(root=ROOT)` | list of `(page id, main file)` | Nothing | Skips Branch only pages and pages with no Code paths; a page git does not track yet is listed |
| `new_page(page_id, kind='kit command', status='Current', root=ROOT, today=None, area=None, commands=(), code=(), command_parser=None)` | `Path` of the new page | `ValueError` for a bad id, status, kind or area, an existing page, a `--code` path not in the repository (unless Branch only), or a command that is not a kit command | What `new` runs |
| `main(argv=None)` | int: the exit code | `SystemExit` from argparse on a usage error or `--help` | `if __name__ == "__main__": sys.exit(main())` |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Pages | `docs/tools/*.md`, UTF-8 Markdown, every file except `README.md` | The id is the file name without `.md` |
| Pending list | `docs/tools/pending.json`: `{"about": TEXT, "pages": {ID: {"group": NAME, "covers": [TARGET, ...]}}}` | Optional. Each target is a coverage target as `coverage_targets` writes it |
| Releases | `docs/releases.json`: the `id` of each entry in `releases` | A missing or broken file counts as no releases |
| The tree | `git ls-files --cached --others --exclude-standard` (or every file when git fails) | Leaves out `__pycache__` and dot-folders except `.claude` and `.github` |
| kit's parser | `kit.cli.build_parser()` | Built only when checking this checkout |
| Templates | `templates/tool-doc.md`, `templates/tool-doc-branch.md` | `new` only; tokens such as `{id}`, `{run}` and `{commands_block}` are replaced |
| git | `rev-parse --is-shallow-repository`, `cat-file -e`, `remote get-url origin`, `log`, `rev-parse --short HEAD` | Each call times out after 60 s; a failed call counts as unknown |

## Outputs

`check` prints one problem per line: `docs/tools/ID.md: PROBLEM` for a page's problem, the bare problem otherwise. With no problems it prints `tool docs pass (N pages)`, or `tool docs pass (pages ID, ID)` with `--page`. With problems it also prints `N problem(s); the standard is docs/TOOL-DOCS.md` on stderr. With `--json` it prints a list of objects:

| Field | Type | Meaning |
| --- | --- | --- |
| `page` | str or null | `docs/tools/ID.md` when the problem belongs to a page, else null |
| `problem` | str | The problem sentence |

`list` prints one line per tool: the id (24 columns), the status (13), the first Run entry (40, cut to 40 characters) and the summary cut to 80 characters. `list --json` and `index.json` hold one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | `SCHEMA_VERSION`, 1 |
| `repo` | str or null | `Scrolls`, `Scrolls-private`, or null when the origin remote is unknown |
| `about` | str | What the file is and that it is generated |
| `tools[].id`, `.name`, `.tagline`, `.summary` | str | The id; the title split at its first `: ` into name and tagline; the summary sentence |
| `tools[].status`, `.area` | str | The Status and Area fields |
| `tools[].kind` | list of str | The Kind words |
| `tools[].commands`, `.imports` | list of str | Run entries in code, without and with a leading `from ` or `import ` |
| `tools[].code` | list of `{"path", "symbols"}` | The Code field's paths and bracketed names |
| `tools[].tests` | list of str | Test paths from the Tests field |
| `tools[].go_ahead` | `{"needed": bool, "text": str}` | Whether the Go-ahead field starts with Needed, and its text |
| `tools[].checked` | `{"date", "commit"}` or null | From the Checked field |
| `tools[].license` | str or null | The License field |
| `tools[].fields` | object | Every At a glance field, in page order |
| `tools[].page` | str | The page's path from the root |
| `tools[].sections` | list of `{"name", "start_line", "end_line", "applicable"}` | Each `##` section with its 1-based first and last line, and false when it is `Not applicable: ...` |

`index` prints `wrote docs/tools/README.md and docs/tools/index.json from N pages`. The README's generated block has one `### AREA` table per area, in the order of the area words, then Other, with the columns Tool, Status, Run, Go-ahead and What it does; rows are sorted by status (Current, Experimental, Retired, Branch only) then id.

`show` prints the page, `## NAME` and the section's body, or the field's value. `new` prints `wrote docs/tools/ID.md; replace every <!-- Write: ... --> with the text, then run python -m kit.tooldocs check --page ID`. `stale` prints `ID: FILE changed after docs/tools/ID.md; check the page against it` per stale page, or `no page is older than its main code file`.

| Exit code | Meaning |
| --- | --- |
| `0` | `check`: no problems. `index`, `list`, `show`, `new`: done. `stale`: always, even when it lists pages (it is a report) |
| `1` | `check`: one or more problems (with or without `--json`); also any uncaught error with a traceback, such as a missing template for `new` |
| `2` | A usage error from argparse; `index` refusing a README without markers; `show` with an unknown id, section or field; `new` refusing its input |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, or an `--area` or `--status` that is not one of the words | Check the command against Commands and options |
| `N problem(s); the standard is docs/TOOL-DOCS.md` on stderr, exit code 1 | `check` found problems; each is a line above it | Fix each line; the table below gives the common ones |
| `no page docs/tools/ID.md`, exit code 1 | `check --page` with an id that has no page | Fix the id, or start the page with `new` |
| `cannot build kit's parser: ...` | `kit/cli.py` raised while building the parser | Run `python -m kit --help` to see the error and fix `kit/cli.py` |
| `docs/tools/pending.json does not parse: ...` | Broken JSON in the pending list | Fix the JSON |
| `docs/tools/README.md has no generated block; refusing to overwrite its text`, exit code 2 | `index` found a README without the two marker lines | Add the marker lines `START` and `END` of `kit/tooldocs.py` around the tables, or delete the README and run `index` again |
| `no tool page 'ID'; close: ID, ID`, exit code 2 | `show` with an unknown id; up to five close ids follow | Use one of the close ids, or `list` |
| `no section 'NAME'; sections: ...`, exit code 2 | `show --section` with a section the page does not have | Use one of the names listed; section names are exact, such as `For agents` |
| `no field 'NAME'; fields: ...`, exit code 2 | `show --field` with a field the page does not have | Use one of the names listed |
| `'ID': an id is lowercase letters, digits and hyphens`, exit code 2 | `new` with capitals, spaces or underscores in the id | Use a short lowercase id, such as `run-ledger` |
| `status 'S' is not one of [...]` or `area 'A' is not one of [...]`, exit code 2 | `new_page` called from Python with a word that is not in the standard (the command line refuses these earlier) | Use one of the listed words |
| `kind [...] is not in [...]`, exit code 2 | `new --kind` with a word that is not a kind word | Use the kind words of the standard, comma-separated |
| `docs/tools/ID.md already exists`, exit code 2 | `new` never overwrites a page | Edit the page, or delete it first if you mean to start over |
| `--code 'PATH' is not in the repository`, exit code 2 | `new --code` with a path that does not exist | Fix the path; for code that lives only on another branch, use `--status "Branch only"` |
| `` `python -m kit SPEC` is not a kit command ``, exit code 2 | `new --command` with a command or action that is not in the parser | Check `python -m kit --help` |
| `BrokenPipeError` traceback after `list` output | `list` piped into a command that closes early, such as `head` | Harmless; use `list --json` and read the file, or ignore it |

### Problems `check` prints

Each line below is a problem `check` reports for a page, with CAPITALS for the parts that vary. Fix the page, not the checker.

| What you see | Why | What to do |
| --- | --- | --- |
| `the first line is not a '# Title' heading` | The page does not start with `# ` | Start with `# ID: what it does in a few words` |
| `` the title must read `# NAME: what it does in a few words` `` | The title has no `: ` | Add the colon and the short description |
| `no one-sentence summary between the title and the table` | No paragraph after the title | Write one sentence of at most 300 characters (`SUMMARY_MAX`) |
| `the summary is N characters; keep it to 300 (one sentence)` | The summary is too long | Shorten it |
| `no 'At a glance' table with the header \| Field \| Value \| after the summary` | The table is missing or has another header | Copy the table from the template |
| `the At a glance table needs \| --- \| --- \| under its header` | The separator row is missing | Add it |
| `table row '...' does not have exactly two cells (write a \| inside a value as \\|)` | A value holds a bare pipe | Write it as `\|` |
| `field 'NAME' appears twice`, `missing fields [...]`, `unknown fields [...]; allowed: [...]`, `fields out of order; the order is [...]` | The At a glance fields differ from the standard's list and order | Use exactly the fields of the standard, in order; optional fields may go anywhere |
| `empty fields [...]; write 'None' and why when there is nothing` | A field has no value | Write None and why |
| `Id is '...'; write ` + the id in code + `, the file name without .md` | The Id field differs from the file name | Write the id in code |
| `Status '...' is not one of [...]`, `Kind '...' is not one of [...]`, `Area '...' is not one of [...]` | A word that is not in the standard | Use the standard's words |
| `Go-ahead must start with 'Not needed' or 'Needed'` | The Go-ahead field starts otherwise | Start it with one of the two |
| `Checked must read` and the expected form | The Checked field is not a date, the word against, and a commit hash in code | Write it as the template does |
| `Checked date D is not a real date`, `Checked names commit C, which is not in this repository` | A bad date, or a commit git does not know | Fix the date; name a commit of this repository |
| `a page of kind KIND needs the field 'License'` | Kinds model, app, package and data need a License | Add the License field |
| `a Retired tool needs the field 'Replaced by' (write 'Nothing' if nothing replaced it)` | Retired without Replaced by | Add the field |
| `` a Branch only tool needs the field 'Branch': `BRANCH` at `COMMIT` `` and `Branch names commit C, which is not in this repository (fetch the branch, or the code is in another repository)` | The Branch field is missing, or its commit is unknown | Add the field; fetch the branch |
| `a page with a Public page field needs '### Differences from the public copy'` | A private page of a public tool, in Scrolls-private | Add the subsection |
| `template guidance (<!-- Write: ...) is still on the page; replace it with the text` | A template placeholder is left | Replace it with real text |
| `'WORD' is still on the page; finish that part` | `TODO`, `TBD`, `FIXME`, `XXX` or a template token such as `{id}` outside code | Finish that part, or put the word in code if it is meant literally |
| `the page has U+2014; use plain sentences, commas or 'to' (style rule)` (or U+2013) | A long dash | Rewrite the sentence |
| `a code block opened with` three backticks `or ~~~ is never closed` | An unclosed fenced block | Close it |
| `sections appear twice: [...]`, `missing section '## NAME'`, `section '## NAME' is out of order; the order is in docs/TOOL-DOCS.md`, `section '## NAME' is empty` | The `##` sections differ from the standard's list | Use the standard's section names, in order, each once and not empty |
| `section '## NAME' cannot be 'Not applicable' on this page` | Not applicable used where the standard forbids it, such as Quick start on a runnable tool | Write the section |
| `section '## Failure modes' needs a table with the header \| What you see \| Why \| What to do \|` (or the Python API header) | The fixed table header is missing or differs | Copy the header exactly |
| `'## Checks and controls' needs a line 'Claim label: LABEL' (one of [...])`, `claim label '...' is not one of [...]` | No claim line, or an unknown label | Add `Claim label:` with a label of the standard |
| `'## For agents' needs one bullet per label, in this order: ... (found [...])` | Bullets missing, renamed or out of order | Use the seven labels (three on a Branch only page), in order |
| `'## Quick start' needs a` bash block `that can be pasted` | A runnable tool's Quick start has no fenced block marked bash | Add one |
| `'## Outputs' needs an exit code table with the header \| Exit code \| Meaning \|` | A runnable tool's Outputs has no exit code table | Add it |
| `` '## History' needs dated bullets: - YYYY-MM-DD: what changed (`COMMIT` or a PR link) ``, `History bullet '...' does not start with '- YYYY-MM-DD: '`, `` History bullet '...' names no commit (`abc1234`) or PR link `` | History bullets missing, undated or without a source | Write `- DATE: what changed (` + commit in code + `)` |
| `link (TARGET) does not resolve` | A relative link to a file that does not exist and is not a pending page | Fix the path; link pages as `id.md` only when the page exists or is pending |
| `a public page links into Scrolls-private; name a private tool in words only (hard rule 1)` | A link into the private repository from a public page | Remove the link; name the tool in words |
| `Tests names 'PATH', which is not in the repository`, `Code names 'PATH', which is not in the repository` | A path that does not exist | Fix the path |
| `` Code names `SYM` in FILE, which defines no such top-level name `` | A bracketed name that the file does not define at top level | Fix the name |
| `` public `NAME` of FILE is not in '## Python API' in code `` | A public function or class (or a name in `__all__`) of a `kit/` file named without brackets is not in the Python API section | Add a row for it, in code |
| `error message 'TEXT' from FILE is not in '## Failure modes'` and `error message 'TEXT' from FILE is on the page but not in '## Failure modes'` | An error message of the code is missing from Failure modes | Add a row with the message copied exactly |
| `` environment variable `NAME`, read by FILE, is not on the page in code `` | The code reads a variable the page does not name in code | Add it to an Environment variables table |
| `` option `OPT` of FILE has no row in a table under '## Commands and options' ``, and the same for `` `python -m kit.MODULE` `` | A script's or entry point's option has no row | Add a row whose first cell names the option |
| `` Run names `python -m kit CMD`, which is not a kit command ``, `` Run names `...`, which is not an action of CMD ``, `` Run names `python -m kit.MODULE`, but FILE is not in the repository `` | The Run field names something that does not exist | Fix the Run field |
| ``no '### `NAME`' heading under '## Commands and options'`` | A command or action in Run has no heading | Add `### ` and the command in code |
| ``the usage block under '### `NAME`' differs from --help; paste `NAME --help`'s usage line: ...`` | The usage block is not the parser's usage (line breaks aside) | Paste the usage from `--help` |
| `` option `ARG` of `NAME` has no row in the table under its heading `` (or positional) | An argument of the command has no row | Add a row |
| ``default of `ARG` in `NAME` is `EXPECTED` in the code; the page says '...'`` | The Default cell differs from the parser | Write required, off, on, none, or the value in code |
| ``row `OPT` under '### `NAME`' is not an option of that command`` | A row for an option the command does not have | Remove or fix the row |
| `` `python -m kit CMD` is on no tool page's Run field (docs/TOOL-DOCS.md) ``, `TARGET has no tool page: ...`, `docs/releases.json entry 'ID' has no tool page with that id or Release id` | Something that needs a page has none and is not pending | Write the page, or ask the lead to add a pending entry |
| `docs/tools/pending.json lists 'ID', which now has a page: remove it`, and `docs/tools/pending.json lists 'TARGET' under 'ID', which a page now covers: remove it` (or `which no longer needs a page`) | The pending list must shrink as pages land | The lead removes the entry |
| `docs/tools/README.md is out of date: run python -m kit.tooldocs index`, `docs/tools/index.json is out of date: run python -m kit.tooldocs index`, `docs/tools/README.md has no generated block; add the two marker lines or delete the file and run python -m kit.tooldocs index` | The index does not match the pages | The lead runs `index` once after a batch of pages |
| `the page is not valid UTF-8` | The file is not UTF-8 | Save it as UTF-8 |

## How it works

1. **Parse.** `Page` reads the title (the first line), the summary (the first paragraph after it), the At a glance table (two cells per row, `\|` as a literal pipe), and the `##` sections with their bodies and line numbers. Headings inside fenced blocks do not count. Code spans and fenced blocks are kept apart from prose, so a placeholder or a dash inside code is checked differently from one in prose.
2. **Shape.** `check_page` checks the title, the summary length (`SUMMARY_MAX` = 300), the fields (`FIELDS`, then `OPTIONAL_FIELDS` anywhere), the Status, Kind and Area words (`STATUSES`, `KINDS`, `AREAS`), Go-ahead, Checked (`CHECKED_RE`), and the fields that some kinds and statuses require.
3. **Sections.** It checks the sections against `SECTIONS` (or `BRANCH_SECTIONS` for a Branch only page) in order, with Python API allowed in place of or after Commands and options (`ALTERNATIVES`). It checks `Not applicable: REASON.` only where it is allowed (`NEVER_NOT_APPLICABLE`, and Quick start and Commands and options on a runnable page, `RUNNABLE`), the fixed table headers (`HEADERS`, `EXIT_HEADER`), the claim label (`CLAIM_LABELS`), the For agents labels (`AGENT_LABELS`, `BRANCH_AGENT_LABELS`), a bash block in a runnable tool's Quick start, and dated History bullets with a commit or a link.
4. **Leftovers and links.** No `<!-- Write:` and no `TODO`, `TBD`, `FIXME`, `XXX` or template token in prose, no U+2014 or U+2013 anywhere, no unclosed fence; every relative link resolves (pending ids count); on a public repository, no link into Scrolls-private.
5. **Code.** For each path in Code and Tests it checks that the path exists. For each `.py` file it parses the code with `ast`: bracketed names must be top-level names; without brackets, a `kit/` module's public names (`__all__`, or top-level functions and classes without a leading `_`) must be in the Python API section; error messages (`error_messages`: the longest literal stretch, at least `MIN_MESSAGE` = 12 characters, of `raise X("...")`, `sys.exit("...")`, `parser.error("...")`, and a `print(..., file=sys.stderr)` inside an `except` block or right before a nonzero return, an exit or a raise) must be in Failure modes; environment variables read with `os.environ` or `os.getenv` (and `${NAME:-...}` in shell scripts) must be on the page in code; long options of a script, or of a `python -m kit.MODULE` entry point, must each have a row under Commands and options. A data page is checked only for its paths, and a Branch only page for none.
6. **Commands.** For each `python -m kit COMMAND [ACTION]` in Run, it finds the parser through `Commands`, requires a `###` heading with the command in code, a fenced usage block equal to the parser's usage with whitespace collapsed, a row for every argument (help-suppressed ones aside), a Default cell that matches `render_default` (`required`, `off`, `on`, `none`, or the value in code, with an absolute path inside the checkout written relative to it), and no row for an option the command does not have.
7. **Coverage** (full check only). `coverage_targets` lists every `kit/*.py` module except `cli.py`, `__init__.py` and `__main__.py`, every `kit/` package, every entry directly under `scripts/`, every project skill, every CI workflow, `pyproject.toml`, every `python -m kit` command (or each action of a command that has them) and every release id. A target is covered when a page names it in Code without brackets (a folder covers its files), in Run, or by id or Release id. `pending.json` excuses a target until its page exists, then must lose the entry.
8. **Index.** `render_index` replaces only the block between `START` and `END` in `docs/tools/README.md`; `render_json` writes `index.json` with `SCHEMA_VERSION` = 1. The full check fails when either differs from what `index` would write.
9. **New page.** `new_page` copies the template, fills Run, Code and Tests (test files that import the module, `tests_for`), the usage blocks and option tables from the parser, Python API rows from the public names and first docstring lines, the Failure modes rows from the error messages, the environment variables, and up to 12 history lines from `git log` (`history_block`), and leaves `<!-- Write: ... -->` everywhere a person must write. It drops the Python API section for a command with no public functions, and Commands and options for a library that is not runnable.
10. **Stale.** `stale` compares `git log -1 --format=%ct` of the first Code path with that of the page, and lists the page when the code's commit is newer or the page has no commit yet.

## Cost and time

| Run | Wall time | Source |
| --- | --- | --- |
| `check` (full: 41 pages, coverage and index) | 2.1 s | This page, 2026-10-16, 4-core cloud container |
| `check --page auc` | 0.2 s | Same |
| `stale` (41 pages) | 0.5 s | Same |
| `python -m unittest tests.test_tooldocs` (41 tests) | 2.7 s | Same |

Memory: Not measured. It runs anywhere; nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit.tooldocs check --page ID` while writing a page; `python -m kit.tooldocs check --json` for the full check in machine-readable form; `python -m kit.tooldocs show ID --section "For agents"` and `python -m kit.tooldocs list --json` to read pages.
- **Parse:** `check`: each line or each `problem` (with `page`) of the JSON list; the last line `tool docs pass (...)` on success. `list --json`: `tools[]` with `id`, `status`, `commands`, `code`, `go_ahead.needed` and `sections[].start_line`/`end_line`.
- **Rerun:** `check`, `list`, `show` and `stale` only read and are safe to rerun. `index` overwrites the generated block and `index.json` with the same result for the same pages. `new` refuses to overwrite an existing page.
- **Success:** `check` exit code 0 and `tool docs pass (...)`; with `--json`, exit code 0 and `[]`.
- **Not a pass:** `tool docs pass` read as proof that a page's prose, numbers or Quick start are right; a pass with `--page` only, which skips coverage, `pending.json` and the index; a commit check that passed in a shallow clone, where it is skipped.
- **Go-ahead:** Nothing.
- **Never:** Edit the generated block of `docs/tools/README.md` or `index.json` by hand; run `index` or edit `pending.json` when you are one of several writers (the lead does that once); weaken the checker or the standard to make a page pass; link a public page into Scrolls-private.

## Tests

```bash
python -m unittest tests.test_tooldocs -v
```

41 tests in seven classes. `RepositoryPages` runs the full check on this repository, checks that `index.json` lists every page, and that both templates carry every section and label. `PageShape` covers a good page, sections (missing, out of order, doubled, empty), Python API in place of Commands and options, Not applicable, fields, ids, titles, summaries, Checked, Status and Kind rules, Branch only pages, leftovers, dashes, fences, headings inside code, fixed tables, the claim label, For agents labels, History bullets, links, code paths, symbols, public API, error messages, environment variables, data pages and script options. `CommandChecks` covers usage blocks, defaults, unknown option rows, unknown commands and actions, missing headings, aliases and positionals. `Coverage` covers uncovered targets, folders, releases and the pending list. `IndexAndNew` covers the README and JSON index, a README without markers, and `new` (prefill, a lambda handler, refusals). `CommandLine` covers the exit codes of `check`, `show` and `list`. `CodeScanners` covers the environment variable, default and error message scanners. On 2026-10-16, while pages were being written in this checkout, the two `RepositoryPages` tests that read the real pages failed (index out of date, pages still pending) and the other 39 passed; they pass once the lead runs `index` and clears `pending.json`. The tests do not check that any page's prose is true.

## History

- 2026-10-16: defaults written as the checker expects: an empty string or list is none, and a path inside the checkout is written relative to it (`63ee638`).
- 2026-10-16: standard v2, the tool-pages rule (hard rule 16), index rows and glossary terms (`29e7e8c`).
- 2026-10-16: checker v2: options, defaults, error messages, public API, environment variables and coverage checked against the code; `new` prefills from the code (`f4a3193`).
- 2026-10-16: first version of the standard, the two templates and the checker (`1d07cb3`).

## Related

- [TOOL-DOCS.md](../TOOL-DOCS.md): the standard this tool enforces.
- [Tool pages index](README.md) and [index.json](index.json): what `index` writes; `pending.json`, when it exists, lists pages still to be written.
- [cli](cli.md): the `python -m kit` parser that the command checks read.
- [releases](releases.md): the other generated README section, for released tools.
- [AGENTS.md](../../AGENTS.md): the tool-pages rule (hard rule 16) and the docs-index rule.
- [MAP.md](../MAP.md): one line per module, to find a path.
