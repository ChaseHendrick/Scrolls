# {id}: <!-- Write: what it does in a few words, such as "score an ink map against labels" -->

<!-- Write: one sentence, at most 300 characters, saying what the tool does and what it is for. The index shows it. -->

| Field | Value |
| --- | --- |
| Id | `{id}` |
| Status | {status} |
| Kind | {kind} |
| Area | {area} |
| Run | {run} |
| Code | {code} |
| Tests | {tests} |
| Needs | <!-- Write: Python version, packages, outside tools (villa, VC3D) and data, with versions --> |
| Runs on | <!-- Write: where it runs and how long it takes, with the source, such as CPU, about 5 s per segment (measured 2026-10-16, 4-core Xeon) --> |
| Network | <!-- Write: None, or every host it contacts and why --> |
| Writes | <!-- Write: Nothing (prints only), or every file and folder it creates or changes --> |
| Go-ahead | <!-- Write: Not needed, or Needed and why (posting, uploading, renting compute) --> |
| Released | <!-- Write: where it is public and since when, such as Public `main` since 2026-10-07, or Private only --> |
| Checked | {date} against commit `{commit}` |

## What it does

<!-- Write: two to five short paragraphs in plain words: the problem, what the tool does about it, what it does not do,
and what its output must not be called (an ink map is model output, not a reading). Define every internal name. -->

## When to use it

<!-- Write: the situations it fits, then a "Do not use it" list, each case with the tool to use instead. -->

## Quick start

<!-- Write: the shortest real run in a bash block, a short excerpt of what it printed when you ran it, and how to tell
it worked. Placeholders are CAPITALS, each explained under the block. -->

## Checks and controls

<!-- Write: the control that lets the result fail, how to run it, what a pass and a fail look like, with the numbers
and their source. -->

Claim label: <!-- Write: one of the claim labels in docs/TOOL-DOCS.md, and what it applies to -->

## Commands and options

{commands_block}

{env_block}

## Python API

{api_block}

## Inputs

<!-- Write: every input: format, shape, dtype, units, coordinate convention, where to get it, size limits. -->

## Outputs

<!-- Write: what it prints, every file it writes, every JSON field (| Field | Type | Meaning |, with units). -->

| Exit code | Meaning |
| --- | --- |
| `0` | <!-- Write: success, and what success means here --> |
| `1` | <!-- Write: what exit 1 means, or delete the row --> |
| `2` | <!-- Write: what exit 2 means, or delete the row --> |

## Failure modes

{failures_block}

## How it works

<!-- Write: the method step by step, the constants that matter (name and value from the code) and the source of any
published method it follows. -->

## Cost and time

<!-- Write: measured times and memory with date, machine and source; where it must run; the cost if it rents
anything. Write "Not measured" rather than guess. -->

## For agents

- **Command:** <!-- Write: the exact command for the common case, and its machine-readable form -->
- **Parse:** <!-- Write: what to read from the output: the JSON fields or lines and what each means -->
- **Rerun:** <!-- Write: safe to rerun or not, and what a rerun overwrites -->
- **Success:** <!-- Write: the exit code and the output values that mean it worked -->
- **Not a pass:** <!-- Write: results that look fine but must not be trusted, such as a score with no control -->
- **Go-ahead:** <!-- Write: what needs the user's yes first, or "Nothing" -->
- **Never:** <!-- Write: what never to do with the tool or its output -->

## Tests

<!-- Write: the command that runs this tool's tests, what they cover and what they do not. -->

## History

{history_block}

## Related

<!-- Write: links to related tool pages, guides, logs and results.json keys, each with a few words on why. -->
