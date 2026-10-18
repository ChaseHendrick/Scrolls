# Tool docs: the standard every tool page follows

Chase asked on 16 October 2026 (09:58 UTC) for "all current, past, and future tool docs" to be "extremely detailed and readable by both human and agent". This page says how. Every tool in this repository has one page in [`tools/`](tools/README.md), written to this standard, and `python -m kit.tooldocs check`, which the tests run, fails when a tool has no page or a page breaks the rules below. The tool-pages rule in [`AGENTS.md`](../AGENTS.md) points here.

Two readers use every page. A person reads it top to bottom to learn what the tool is for and whether to trust its output. An agent jumps to one section by its fixed name, copies a command, and needs every option, default, output field, exit code and error message written out exactly. The rules below serve both: the same fields and sections in the same order on every page, plain sentences, and exact text, checked against the code, wherever something will be pasted or parsed.

## Headless workflows and competitive evidence

Chase's standing requirement of 17 October 2026 covers all tools and techniques in both repositories. Every new or changed tool must provide its complete supported workflow through a noninteractive CLI and/or programmatic API; GUIs are optional. Document explicit inputs and output paths, machine-readable status and results, useful exit codes or structured API errors, and a dry run or preflight for costly or destructive actions. An agent must be able to configure, run, inspect and export the work without manual GUI steps.

Competitive performance against community tools is the goal, not an assumed result. Claims need fair comparisons with the strongest relevant eligible released baselines: identify versions and eligibility, record training/evaluation exposure and provenance, and report correctness or quality, cost, speed and negative controls under comparable conditions. Limit conclusions to the measured task, data and resources; never claim a blanket win. Match validation to the change and use existing evidence where applicable, rather than requiring new costly benchmarks for every edit.

Record existing interface and evidence gaps on the tool page and improve them when touching the tool. This requirement does not assert that all current tools comply, and does not relax scientific, privacy or compute-authorization rules.

## What counts as a tool

Anything a person or an agent runs or calls. The checker finds the first eight in the tree and fails when no page names one:

| Thing | A page covers it when |
| --- | --- |
| Each `kit/*.py` module, except `kit/cli.py`, `kit/__init__.py` and `kit/__main__.py` | Its Code field names the file without symbols |
| Each `kit/` package (a folder with `__init__.py`) | Its Code field names the folder |
| Each `python -m kit` command, and each action of a command that has actions (such as `run init`) | Its Run field names the command, or the command and action. One page may cover a family, such as the experiment ledger's `run init`, `run status` and `run check` |
| Each script or folder directly under `scripts/` | Its Code field names it (a folder covers its files) |
| Each project skill in `.claude/skills/` | Its Code field names the skill's folder |
| Each CI workflow in `.github/workflows/` | Its Code field names the file |
| The installable package, `pyproject.toml` | Its Code field names the file |
| Each released tool in [`releases.json`](releases.json) | The page's id, or its Release id field, is the release's id |
| Agent (MCP) tools, apps and Spaces, released weights and patches to villa | By hand: write the page when the thing is made |
| Past tools: retired ones still in the tree, and tools whose code lives only on another branch or in history | By hand: a Retired or Branch only page |

A module whose name starts with `_` (a private helper, such as `kit/_surface_geometry.py`) is named in the Code field of the page of the tool that uses it. `kit/cli.py` is covered command by command: each page names its own `cmd_` function, as in `` `kit/cli.py` (`cmd_auc`) ``.

## Two repositories

Public Scrolls and Scrolls-private each have their own `docs/tools/`, this standard, and an identical copy of `kit/tooldocs.py`; keep the two copies the same. A page lives in the repository whose code it describes.

- **Public pages carry nothing private** (the no-findings rule, hard rule 1): no target-scroll maps, triage or verdicts, and no private tools' internals. A public page may say that a private tool exists, in words only; the checker refuses a public page that links into Scrolls-private.
- **A private copy of a public tool** has its own private page, with the field **Public page** (the public page's URL) and a `### Differences from the public copy` subsection, under What it does, saying what the private copy adds or changes. Find the differences with `git diff --no-index`, or by reading both files.
- A private page may link to public pages by URL; a public page never links to a private one.

## Where pages live

- **`docs/tools/ID.md`**, one page per tool. The id is lowercase letters, digits and hyphens: the command name where there is one (`auc`, `letterread`), otherwise a short name (`run-ledger`, `mac-w045`).
- **[`docs/tools/README.md`](tools/README.md)** is the index, grouped by Area. Its tables, and [`docs/tools/index.json`](tools/index.json) for agents, are generated by `python -m kit.tooldocs index`; edit the pages, never the generated parts. The README's text above the generated block is free.
- **`docs/tools/pending.json`**, when it exists, lists pages still to be written, each with the things it will cover. While a page is listed there, the checker accepts its things as covered and accepts links to it. When the page exists, the checker asks for its entry to be removed, so the list can only shrink; delete the file when it is empty.
- **Templates:** [`../templates/tool-doc.md`](../templates/tool-doc.md), and [`../templates/tool-doc-branch.md`](../templates/tool-doc-branch.md) for a Branch only tool. `python -m kit.tooldocs new` copies the right one and fills in what the code can tell.

## Relation to other homes

One home per topic (the docs-index rule, hard rule 13). The tool page is the **reference**: every option, input, output, exit code and failure, checked against the code. Other homes keep their jobs:

| Home | What it keeps | What the tool page does |
| --- | --- | --- |
| [`MAP.md`](MAP.md) | One line per module, script and docs area, to find a path | Links nothing back; the map row may link the page |
| A guide, such as [`letter-reader.md`](letter-reader.md), [`strokenet.md`](strokenet.md) or [`unroll-space.md`](unroll-space.md) | The tutorial, the model card, the evidence | Links it in the Guide field instead of copying it |
| [`results.json`](results.json) and the dated logs | Every measured number with its settings and source | Quotes a number with its key or log as the source |
| The README's "Released tools" section | Generated from `releases.json` (the releases rule, hard rule 15) | Covers the release by id |
| [`../GLOSSARY.md`](../GLOSSARY.md) | Terms, A to Z | Defines internal names on first use; new terms go in the glossary too |

## A page, top to bottom

1. **Title**, one line: `# ID: what it does in a few words`, such as `# auc: score an ink map against a segment's published labels`.
2. **Summary**: one sentence, at most 300 characters, the first paragraph after the title. The index shows it.
3. **At a glance**: a two-column table with the header `| Field | Value |` and the fields below, in this order.
4. **Sections**: level-2 headings with exactly the names below, in this order. You may add other `##` sections between them; `###` subsections are free.

### At a glance fields

| Field | What to write | Example |
| --- | --- | --- |
| Id | The file name without `.md`, in code | `` `auc` `` |
| Status | One of the four status words below | Current |
| Kind | One or more kind words below, comma-separated | kit command, kit module |
| Area | One of the area words below | Scoring and controls |
| Run | Every entry point, each in code: `python -m kit CMD [ACTION]`, `python -m kit.MODULE`, `bash scripts/X.sh`, `python scripts/X.py`; for a library also its import, such as `` `from kit import auc` ``; for an app, its URL as a link | `` `python -m kit auc`, `from kit import auc` `` |
| Code | Every file of the tool, each in code, paths from the repository root; a folder ends with `/`. Name only some functions of a shared file by following it with the names in brackets, each in code | `` `kit/auc.py`, `kit/cli.py` (`cmd_auc`) `` |
| Tests | Test files in code, or None and why | `` `tests/test_auc.py` `` |
| Needs | Python version, packages, outside tools and data, with versions where they matter | Python 3.10 or newer, numpy, tifffile, zarr |
| Runs on | Where it runs and how long it takes, with the source of the number | Any CPU, about 5 s per segment (measured 2026-10-16) |
| Network | None, or every host it contacts and why | None |
| Writes | Nothing (prints only), or every file and folder it creates or changes | Nothing; with `--slug`, a check in `experiments/SLUG/run.json` |
| Go-ahead | Starts with Not needed or Needed, then why (posting, uploading, submitting, renting compute: the go-ahead rule, hard rule 8) | Not needed |
| Released | Where it is public and since when | Public `main` since 2026-10-07 |
| Checked | `YYYY-MM-DD against commit `HASH``: the day you checked the page against the code, and the commit you read | 2026-10-16 against commit `27d0e96` |

Optional fields, placed anywhere in the table:

| Field | When | What to write |
| --- | --- | --- |
| Guide | A longer guide exists | A link to it |
| License | Required for kinds model, app, package and data | The license and its link |
| Replaced by | Required when Status is Retired | The tool that replaced it, linked, or Nothing |
| Branch | Required when Status is Branch only | `` `BRANCH` at `COMMIT` `` (the branch and the commit that hold the code) |
| Public page | A private page of a tool that is also public | The public page's URL |
| Release id | The page covers a release whose id differs from the page id | The release id, in code |

A `|` inside a value is written `\|`.

### Status words

| Status | Meaning |
| --- | --- |
| Current | In the tree and fit to use |
| Experimental | In the tree and works, but its result has not passed its own bar or its interface may change; say which in What it does |
| Retired | Still in the tree but not for new work: superseded, or a measured null. The page stays so old results can be read and rerun |
| Branch only | Not on the default branch: the code lives only on another branch, or only in history. The page says where and why |

### Kind words

`kit command` (a `python -m kit` command), `kit module` (a library inside `kit/`), `kit entry point` (a `python -m kit.MODULE` entry point, such as `python -m kit.cloudcost`), `script`, `script folder`, `agent tool` (an MCP tool), `app` (a Space or a web page), `model` (weights), `package` (an installable package), `skill`, `patch` (a patch to someone else's code, such as villa), `workflow` (a CI workflow or a multi-step routine), `data` (a dataset, a manifest a tool reads, or saved records such as `scripts/experiments/`).

### Area words

The index groups pages by area: `Pipeline and agents`, `Data and downloads`, `Surfaces and tracing`, `Ink maps and models`, `Scoring and controls`, `Letters and titles`, `Training`, `Compute and cost`, `Records and provenance`, `Planning and prizes`, `Releases and repository`, `Viewers and apps`.

### Sections, in order

| Section | What it must hold |
| --- | --- |
| `## What it does` | Two to five short paragraphs in plain words: the problem, what the tool does about it, what it does not do, and what its output must not be called (an ink map is model output, not a reading). Define every internal name on first use |
| `## When to use it` | The situations it fits, then the cases where it does not, each with the tool to use instead |
| `## Quick start` | The shortest real run, in a `bash` block that can be pasted (a Python snippet for a library), a short excerpt of what it printed when you ran it, and how to tell it worked. Placeholders are CAPITALS, each explained under the block |
| `## Checks and controls` | The control that lets the result fail (the rule that every check must be able to fail, hard rule 4), how to run it, what a pass and a fail look like, with numbers and their sources, and a line `Claim label: LABEL` |
| `## Commands and options` | One `###` heading per command or action, in code, such as `` ### `python -m kit run init` ``. Under each, the usage block exactly as `--help` prints it, then a table `\| Option \| Default \| Meaning \|` with a row for every positional argument and every option. A script's options get the same table under a heading of their own. Environment variables go in a `### Environment variables` table |
| `## Python API` | For a library: a table `\| Function \| Returns \| Raises \| Notes \|` with a row for every public function and class, each in code. A page has Commands and options, Python API, or both, in that order |
| `## Inputs` | Every input: format, shape, dtype, units, coordinate convention, where to get it, size limits |
| `## Outputs` | What it prints, every file it writes, every JSON field (`\| Field \| Type \| Meaning \|`, with units), and for anything runnable a table `\| Exit code \| Meaning \|` |
| `## Failure modes` | A table `\| What you see \| Why \| What to do \|` with every error message the code can show, copied exactly |
| `## How it works` | The method step by step, the constants that matter (name and value from the code) and the source of any published method it follows |
| `## Cost and time` | Measured times and memory with date, machine and source; where it must run (GPU work and long CPU jobs go to Modal: the Modal rule, hard rule 11); the cost if it rents anything. Write Not measured rather than guess |
| `## For agents` | The labeled bullets in the next section |
| `## Tests` | The command that runs this tool's tests, what they cover and what they do not |
| `## History` | Dated bullets, newest first: `- YYYY-MM-DD: what changed (`COMMIT` or a PR link)`. For a retired tool, why it was retired |
| `## Related` | Links to related tool pages, guides, logs and `results.json` keys, each with a few words on why |

A **Branch only** page has its own list, since its code is not in the tree: `## What it does`, `## Where the code is` (branch, commit, paths, PR, and the `git` commands that fetch it), `## How to run it`, `## Inputs and outputs`, `## Why it is not on the default branch` (with its source, or Not recorded), `## For agents`, `## History`, `## Related`.

### Not applicable

A section that cannot apply holds exactly one line, `Not applicable: REASON.`, such as `Not applicable: the model has no options; see Inputs.` What it does, When to use it, For agents, History and Related always apply, as do Where the code is and Why it is not on the default branch on a Branch only page. A runnable tool (a kit command, kit entry point, script or script folder) always has a Quick start and Commands and options. Typical cases by kind:

| Kind | Usually Not applicable |
| --- | --- |
| kit module (a library) | Commands and options (use Python API instead, or leave the section out) |
| model, data | Commands and options, Python API |
| app, agent tool | Python API; Commands and options lists its settings or tool calls instead |
| skill, workflow, patch | Python API; Quick start shows how it is invoked |

## Claim labels

Every page's Checks and controls section ends its claims with one line, `Claim label: LABEL`, where LABEL starts with one of the labels of [NOVELTY.md](NOVELTY.md) and the claims rule (hard rule 5): Sourced fact, Organizer result, Community report, Model output, Null, Candidate (private), Interpretation, Untested idea, or None (for a tool whose output makes no claim, such as a downloader). Say after the label what it applies to.

## The For agents section

An agent may read only this section and the At a glance table, so it holds one bullet per label, in this order, each starting with the label in bold:

- **Command:** the exact command for the common case, and its machine-readable form (`--json`, an output file), copied from the code.
- **Parse:** what to read from the output: the JSON fields or lines and what each means.
- **Rerun:** whether a rerun is safe (idempotent), and what it overwrites or appends.
- **Success:** the exit code and the output values that mean it worked.
- **Not a pass:** results that look fine but must not be trusted, such as a score with no control, or a score on a segment the model trained on.
- **Go-ahead:** what needs the user's yes first (posting, uploading, submitting, renting compute), or Nothing.
- **Never:** what never to do with the tool or its output, such as calling an ink map a reading or running a GPU job on a laptop CPU.

A Branch only page has three: **Revive:** (whether it is safe to bring back, and how), **Check first:** (what to check before using it), **Never:**.

## Writing rules

- **Exact where it is pasted or parsed.** Commands, option names, defaults, file names, JSON fields, exit codes and error messages are copied from the code, in code formatting. Placeholders are CAPITALS (`MAP.tif`), each explained under its block.
- **Plain sentences elsewhere.** Short paragraphs, one idea each. Tables for comparisons and for lists an agent will scan.
- **Numbers carry their source.** A default names its constant; a measured time or score gives its date, machine and source (a log, a `results.json` key, a commit). Never invent a number, a flag or a field: write Not measured or Not recorded.
- **Run it before you write it.** The Quick start and the output excerpts come from a real run (small synthetic inputs are fine; say so).
- **Each page stands alone.** An agent that reads only one page can run that tool correctly; link to background, but do not make the reader assemble the basics from other pages.
- **Terms.** Define internal names on first use and add new terms to [`../GLOSSARY.md`](../GLOSSARY.md). Use villa and VC3D terms where they exist.
- **Style.** Plain sentences, never U+2014 or U+2013 dashes (the style rule, hard rule 10), relative links that resolve.
- **Name rules by name.** Write "the go-ahead rule (hard rule 8)", not a bare number, because the two repositories number their rules differently.

## Writing many pages at once

Agents that fan out over many tools follow these, so their work merges cleanly:

1. Start each page with `python -m kit.tooldocs new ID --kind KIND --area AREA --command "CMD [ACTION]" --code PATH` (repeat `--command` and `--code` as needed). It fills the Run, Code and Tests fields, the usage blocks and option tables with their defaults, the Python API rows, the error messages, the environment variables and the history from git, and leaves `<!-- Write: ... -->` where a person must write.
2. Replace every `<!-- Write: ... -->`, then run `python -m kit.tooldocs check --page ID` until it prints `tool docs pass`.
3. Edit only your own pages. Link other tools' pages by id even if they are not written yet; ids in `pending.json` resolve.
4. Leave `pending.json`, the index and every other file to the lead, who removes the done entries, runs `python -m kit.tooldocs index` once, and runs the full check and the tests.

## Keeping pages current

- **Change a tool, change its page** in the same change: options, defaults, outputs, errors and the Checked field. The checker fails when an option, a default, a public function or an error message no longer matches. `python -m kit.tooldocs stale` lists pages whose main code file changed after the page did.
- **New tool, new page** in the same PR: `python -m kit.tooldocs new`, fill in every section, then `python -m kit.tooldocs index`. The check fails on a new kit module, command, action, script, skill, workflow or release without a page, so it cannot be skipped.
- **Retire a tool** by setting Status to Retired and filling Replaced by; keep the page.
- **Delete a tool's code** only after its page says Branch only, with the branch or commit that still holds it.

## For agents: reading the pages

- `python -m kit.tooldocs list` prints one line per tool; `--json` prints the index.
- `python -m kit.tooldocs show ID` prints a page; `--section "For agents"` prints one section; `--field Writes` prints one field.
- [`docs/tools/index.json`](tools/index.json) holds, per tool: id, name, tagline, summary, status, kind, area, commands, imports, code (paths and symbols), tests, go-ahead, checked date and commit, license, every field, the page's path, and each section's first and last line with whether it applies.

## What the checker checks

`python -m kit.tooldocs check` (and `tests/test_tooldocs.py`, which runs it) prints one line per problem and exits 1 when there is any. `--page ID` checks only that page; `--json` prints the problems as JSON.

- **Shape:** the title reads `# NAME: ...`; the summary is there and at most 300 characters; the At a glance table has every field, in order, none empty, none unknown or doubled; the Status, Kind and Area words; Go-ahead starts with Not needed or Needed; Checked reads a real date and a commit that exists (when git has the full history; a shallow clone skips the commit); License, Replaced by, Branch and Public page where they are required.
- **Sections:** every required section, in order, none doubled, none empty; Not applicable only where allowed; the fixed table headers in Failure modes, Python API and (when runnable) Outputs; a `Claim label:` line with a known label; the For agents labels in order; a `bash` block in a runnable tool's Quick start; dated History bullets that name a commit or link a PR.
- **Leftovers:** no `<!-- Write:` guidance, TODO, TBD, FIXME, XXX or template token outside code; no U+2014 or U+2013; no unclosed code block.
- **Links:** every relative link resolves (ids in `pending.json` count); a public page has no link into Scrolls-private.
- **Code:** every path in Code and Tests exists; every function named in brackets is defined at the top level of its file; every public function and class of a `kit/` module named without brackets is in Python API, in code; every error message of the code it names (each `raise`, `sys.exit`, `parser.error`, and `print(..., file=sys.stderr)` in an `except` block or before a failing return) is in Failure modes; every environment variable it reads is on the page in code; every option of a script, and of a `python -m kit.MODULE` entry point, has a row in a table under Commands and options. A `data` page is checked only for its paths, and a Branch only page for none; instead, its Branch commit must not already be in the checked-out branch's history, since then the tool has merged and the page becomes Current (or Retired if its code was removed since).
- **Commands:** every `python -m kit` command and action in Run exists; each has its `###` heading, a usage block equal to `--help`'s (line breaks aside), a row for every positional argument and option, defaults that match the parser (`required`, `off`, `on`, `none`, or the value in code), and no row for an option the command does not have.
- **Coverage:** everything in "What counts as a tool" has a page, or a pending entry; each pending entry is still needed.
- **Index:** `docs/tools/README.md` and `docs/tools/index.json` match the pages.

It cannot check that the prose is true. Reviewers check that: run the Quick start, read the code against How it works, and check every number against its source.
