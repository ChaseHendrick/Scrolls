# {id}: <!-- Write: what it did in a few words -->

<!-- Write: one sentence, at most 300 characters, saying what the tool does and that its code is on another branch. -->

| Field | Value |
| --- | --- |
| Id | `{id}` |
| Status | Branch only |
| Kind | {kind} |
| Area | {area} |
| Run | <!-- Write: the entry point as it was on its branch, in code --> |
| Code | <!-- Write: its files, in code, as paths on that branch --> |
| Tests | <!-- Write: its test files on that branch, in code, or None and why --> |
| Needs | <!-- Write: what it needed to run --> |
| Runs on | <!-- Write: where it ran and how long it took, with the source --> |
| Network | <!-- Write: None, or the hosts it contacted --> |
| Writes | <!-- Write: what it wrote --> |
| Go-ahead | <!-- Write: Not needed, or Needed and why --> |
| Released | <!-- Write: Private only, or where it is public --> |
| Branch | <!-- Write: the branch and the commit that hold the code, such as `grok/framefix-1912` at `1a2b3c4` --> |
| Checked | {date} against commit `{commit}` |

## What it does

<!-- Write: what the tool did and what it was for, in plain words, with every internal name defined. -->

## Where the code is

<!-- Write: the branch, the commit, each file's path, any open or closed PR, and the commands that fetch it, such as
git fetch origin BRANCH and git show COMMIT:kit/x.py. -->

## How to run it

<!-- Write: the exact commands to run it from that branch, with its options and defaults, as far as the code shows
them. -->

## Inputs and outputs

<!-- Write: what it read and what it wrote, with formats and fields. -->

## Why it is not on the default branch

<!-- Write: the reason, with its source: superseded (by what), a measured null (link), abandoned, or still in progress
(which handoff row). Write "Not recorded" when no source says. -->

## For agents

- **Revive:** <!-- Write: whether it is safe to bring back, and how (merge, cherry-pick, or rewrite) -->
- **Check first:** <!-- Write: what to check before using it, such as what changed on the default branch since -->
- **Never:** <!-- Write: what never to do with it or its output -->

## History

{history_block}

## Related

<!-- Write: links to the tools that replaced or use it, and its logs. -->
