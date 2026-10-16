# Tool name: what it does in a few words

<!-- Write: one sentence, at most 300 characters, saying what the tool does and what it is for. The index shows it. -->

| Field | Value |
| --- | --- |
| Id | `{id}` |
| Status | {status} |
| Kind | {kind} |
| Run | <!-- Write: each entry point in code, such as `python -m kit auc`; for a library, None (library) and the import, such as `from kit import auc` --> |
| Code | <!-- Write: every file of the tool, in code, such as `kit/auc.py`, `kit/cli.py` (`cmd_auc`) --> |
| Tests | <!-- Write: test files in code, or None and why --> |
| Needs | <!-- Write: Python version, packages, outside tools (villa, VC3D) and data, with versions --> |
| Runs on | <!-- Write: where it should run and how long it takes, such as CPU, seconds per segment (measured 2026-10-07, log link) --> |
| Network | <!-- Write: None, or every host it contacts and why --> |
| Writes | <!-- Write: Nothing (prints only), or every file and folder it creates or changes --> |
| Go-ahead | <!-- Write: Not needed, or Needed and why (posting, uploading, renting compute: AGENTS.md hard rule 8) --> |
| Released | <!-- Write: where it is public, such as Public `main` since 2026-10-07, or Private only --> |
| Checked | {date} against commit <!-- Write: the short commit you read --> |

## What it does

<!-- Write: two to five paragraphs in plain words: the problem, what the tool does about it, what it does not do and
what its output must not be called (an ink map is model output, not a reading). Define every internal name. -->

## When to use it

<!-- Write: the situations it fits, then "Do not use it" cases, each with the tool to use instead. -->

## Quick start

<!-- Write: the shortest real run, in a bash block that can be pasted, then what it prints (a short excerpt), then
how to tell it worked. Placeholders in CAPITALS, each explained below the block. -->

## Commands and options

<!-- Write: one ### heading per command or action. Under each, the usage line, then a table with every positional
argument and every option: | Option | Default | Meaning |. Defaults come from the code. For a library, use the
heading "## Python API" instead, with each public function's signature, arguments, return value and errors. -->

## Inputs

<!-- Write: every input: format, shape, dtype, units, coordinate convention, where to get it, size limits. -->

## Outputs

<!-- Write: what it prints, every file it writes, every JSON field (| Field | Type | Meaning |) and every exit code
(| Code | Meaning |). -->

## How it works

<!-- Write: the method step by step, with the constants that matter (name and value from the code) and sources for
any published method it follows. -->

## Checks and controls

<!-- Write: the control that lets the result fail (AGENTS.md hard rule 4), how to run it, what a pass and a fail look
like, and the claim label the output carries (docs/NOVELTY.md). -->

## Failure modes

<!-- Write: a table | What you see | Why | What to do |, with the exact error messages from the code. -->

## Cost and time

<!-- Write: measured times and memory with date, machine and source; where it must run (rule 11: GPU work and long
CPU jobs go to Modal); cost if it rents anything. Write "Not measured" rather than guess. -->

## For agents

<!-- Write: the exact command for the common case and its machine-readable form (--json), what it reads, writes and
sends, whether it is safe to rerun, what needs the user's go-ahead, how to tell success from failure, and what never
to do with it or its output. -->

## Tests

<!-- Write: the command that runs this tool's tests, what they cover and what they do not. -->

## History

<!-- Write: dated changes, newest first, with PR or commit links; for a retired tool, why it was retired. -->

## Related

<!-- Write: links to related tool pages, guides, logs and results.json keys, each with a few words on why. -->
