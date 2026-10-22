# stale: what the live pages and registries still say that is no longer true

`python -m kit stale` checks the handoff, the live pages and the registries for staleness: old handoff rows, gone branches, retired names, dead links, map rows and waiting routines. Read-only; a daily routine, also run by the routines workflow.

| Field | Value |
| --- | --- |
| Id | `stale` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Releases and repository |
| Run | `python -m kit stale`, `python -m kit.stale`, `from kit import stale`; daily at session start, and in the daily routines workflow, as the routine `stale` in `docs/routines.json` |
| Code | `kit/stale.py`, `docs/renames.json`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_stale.py` |
| Needs | Python 3.10 or newer, standard library only; `git` on `PATH` for the checks that read history or refs (without it they are skipped and say so) |
| Runs on | Any CPU: 0.94 s wall, 28 MB peak memory for all nine checks on this repository (measured 2026-10-18, 4-core Intel Xeon at 2.10 GHz cloud container) |
| Network | None. Branch checks read the refs this clone already has, as of its last fetch |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed: it only reads. Fixing what it reports follows the usual rules (a post or a branch deletion still needs its own yes) |
| Released | Public `main` from the change that adds it (18 Oct 2026). The same file is in Scrolls-private, as with `kit/routines.py`; the two copies are kept byte-identical (history at the top of `kit/stale.py`) |
| Checked | 2026-10-18 against commit `b449398` plus this tool |

## What it does

The rules review Chase approved on 18 Oct 2026 lists a staleness check at session start among its tooling ([handoff](../HANDOFF.md), row "Rules relaxed and decisions file"), and he asked for both repositories to be kept from going stale. Many agents write to this repository in a day, from different accounts and containers, and the pages they leave behind drift: a handoff row that nobody updated, a branch that was merged and deleted, a tool that was renamed, a link that moved. `kit stale` finds those from committed files and local git history. It never fixes anything; each finding says what to look at.

It runs nine checks:

1. **handoff-rows**: rows of `docs/HANDOFF.md` whose text has not changed for over 7 days (by `git blame`).
2. **branches**: work branches (`claude/`, `codex/`, `grok/`, `mac-archive/`) that handoff rows name and this clone no longer has, since merged branches are deleted automatically from 18 Oct, unless a PR number or commit is named beside them; and branches merged into the default branch while the clause that names them does not say "merged" (or says "not merged", "unmerged" or "not pushed"). Each mention is judged by its own clause (from the previous cell border or sentence end to the next), so "fix merged (#85)" elsewhere in the row does not cover it. A pattern such as `claude/x-wip-<name>` is not a branch, and a branch with no commits of its own (its tip on the default branch's first-parent line) is not merged. In a clone that holds a single branch, such as the workflow's checkout, the check is skipped: there every other named branch would look deleted.
3. **names**: retired names listed in `docs/renames.json` (today the old name of Scroll Text Reader) on live pages. A table row is stale whenever the old name remains, even beside the new one, since a table names the thing; a prose line passes when it also gives the new name, unless the entry sets `allow_formerly` to false. Inline code spans and an entry's `keep` phrases (such as the sentence that records the rename) are left out first.
4. **links**: relative Markdown links on live pages that point at files git does not track.
5. **map**: paths `docs/MAP.md` names that are gone, and kit modules it has no row for. A path written right after "as" names a file in another tree, such as a released package, and is not checked.
6. **routines**: routines in `docs/routines.json` that have waited over 7 days for a `requires` path that never landed.
7. **handoff-paths**: handoff rows older than 2 days that name a worktree under `/home/user/` or a session scratchpad (`/tmp/claude-...`), which do not survive a cloud container. The two checkout roots, `/home/user/Scrolls` and `/home/user/Scrolls-private`, are allowed except under `work/` and `experiments/`.
8. **freezes** and 9. **approvals**: read Scrolls-private's registries of hash freezes and Modal approvals. This repository has neither file, so both are skipped here and say so.

A live page is one of `LIVE_PAGES`: `README.md`, `AGENTS.md`, `CLAUDE.md`, `GLOSSARY.md`, `docs/README.md`, `docs/MAP.md`, `docs/HANDOFF.md`, `docs/AI-AGENTS.md`, `docs/DECISIONS.md`, `docs/TOOLBOX.md` and `docs/VISION.md` when they exist, and every `docs/tools/*.md`. Published records (`docs/prereg/`, `docs/evidence/`, `docs/logs/`, archives) are byte-frozen and never checked for names or links.

A finding is a prompt to look, not a verdict: a row unchanged for a week may be correctly waiting on Chase.

### In the daily workflow

`.github/workflows/routines.yml` runs `python -m kit routines run --ci --strict`, which counts attention as a failure, so a finding fails the job and GitHub emails Chase. Its checkout has depth 1 and one branch (`main` on the schedule, or the branch picked when it is run by hand). There the branch check is skipped (above), and git dates every line to the tip commit, so handoff-rows, routines and handoff-paths can only flag after that many days without a commit on `main`, and each such finding is then true (the line is at least that old). Names, links and map read committed files and behave as anywhere else. In any shallow clone the three age checks add the info line `shallow clone: lines older than its first commit carry that commit's date, so ages are lower bounds`.

## When to use it

- At session start: the `stale` routine runs it daily through `python3 -m kit routines run --due`; read its findings in `python3 -m kit routines status`.
- After a rename or a merge, to see what still points at the old state: `python3 -m kit stale --only names` (or `branches`).
- When you rename something: add an entry to `docs/renames.json` in the same change, then run `python3 -m kit stale --only names` and fix the live pages it lists.

Do not use it:

- For the handoff's size and age as a whole: use `python3 -m kit routines check handoff` ([routines](routines.md)).
- For tool pages against their code: use `python -m kit.tooldocs check` ([tooldocs](tooldocs.md)).
- To quiet a finding in a dated log or evidence file: those are published records and stay as they are.

## Quick start

```bash
python3 -m kit stale                       # all nine checks; exit 3 when something needs a look
python3 -m kit stale --only names --json   # one check, machine-readable
```

On this repository's branch `claude/stale-guard` (this tool, from `main` at `b449398`), with `--now 2026-10-18T20:00:00Z`, the first command printed:

```
kit stale: 9 checks, 0 need a look (2026-10-18T20:00:00Z)
ok        handoff-rows  49 rows, 0 unchanged for over 7 days; shallow clone: lines older than its first commit carry that commit's date, so ages are lower bounds
ok        branches      10 branch mentions in rows; default branch origin/main; refs as of this clone's last fetch
ok        names         1 retired names on 69 live pages
ok        links         69 live pages against git's tracked files
ok        map           46 kit modules, 46 with a row
ok        routines      8 routines, 0 waiting for a missing path; shallow clone: lines older than its first commit carry that commit's date, so ages are lower bounds
ok        handoff-paths 0 rows name a container path; shallow clone: lines older than its first commit carry that commit's date, so ages are lower bounds
skipped   freezes       no docs/compute/freezes.json
skipped   approvals     no docs/compute/modal-approvals.json
```

and exited 0. Before the same change fixed them, it listed 13 lines on live pages still using `Greek letter reader` (the docs index, the tool index, the glossary, two handoff rows and seven tool pages) and 11 mentions in two handoff rows of branches GitHub had deleted after their merge. It worked when the first line counts nine checks and each check has a status line.

## Checks and controls

Each check can fail, and the tests show it does: on small synthetic git repositories with commits at chosen dates, every check flags a planted stale case and passes the matching fresh one (a row changed 10 days ago against one changed yesterday; a deleted branch against one whose PR is named beside it; a merged branch whose clause says "not merged", "unmerged" or "not pushed", or whose row says "merged" only about another item, against one whose own clause says "merged"; a placeholder pattern and a branch with no commits of its own, which must stay quiet; an old name in a table row beside the new one against the same words in prose). A malformed registry fails the run (exit 1) instead of passing it. The skip in a single-branch clone is itself tested both ways: a depth-1 single-branch clone skips, and the same repository with a work branch runs the check.

Ages come from git. A commit that rewrites every row (a spelling pass) makes them all young again, so a quiet handoff-rows check right after such a pass means little; in a shallow clone ages are lower bounds. Branch checks see only this clone's refs: run `git fetch` first when a branch's fate matters.

Claim label: None. The check reports repository state; it makes no scientific claim.

## Commands and options

### `python -m kit stale`

```
usage: python -m kit stale [-h]
                           [--only {handoff-rows,branches,names,links,map,routines,handoff-paths,freezes,approvals}]
                           [--json] [--now NOW]
                           [--handoff-rows-days DAYS_HANDOFF_ROWS]
                           [--routines-days DAYS_ROUTINES]
                           [--handoff-paths-days DAYS_HANDOFF_PATHS]
                           [--freezes-days DAYS_FREEZES]
                           [--approvals-days DAYS_APPROVALS]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--only ONLY` | none | Run only this check (repeatable); without it all nine run |
| `--json` | off | Print the report as JSON (Outputs) instead of the text view |
| `--now NOW` | none | Judge ages as of this UTC time, `YYYY-MM-DDTHH:MM:SSZ` (default: now); a time without a zone is UTC |
| `--handoff-rows-days DAYS_HANDOFF_ROWS` | `7` | Age threshold of the handoff-rows check in days |
| `--routines-days DAYS_ROUTINES` | `7` | Age threshold of the routines check in days |
| `--handoff-paths-days DAYS_HANDOFF_PATHS` | `2` | Age threshold of the handoff-paths check in days |
| `--freezes-days DAYS_FREEZES` | `14` | Age threshold of the freezes check in days (Scrolls-private only) |
| `--approvals-days DAYS_APPROVALS` | `14` | Age threshold of the approvals check in days (Scrolls-private only) |

It always reads the repository that holds `kit/stale.py`, not the current folder.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `StaleError()` | An exception (a `ValueError`) | Nothing | A registry this check reads is malformed: the check fails (exit 1) instead of guessing. |
| `utcnow()` | Aware `datetime` in UTC | Nothing | Now |
| `Git(root)` | A `Git` object; `ok` is False outside a git clone | Nothing | Read-only git queries on one clone; every method returns None (or empty) when git cannot answer. Methods: `blame_times`, `refs`, `default_branch` (the first of `DEFAULT_BRANCHES` the clone has), `has_branch`, `branch_ref`, `shallow` (True in a shallow clone), `has_commit`, `is_ancestor`, `first_parents` (the set of commits on a ref's first-parent line), `merged_into(ref, default)` (True when ref's tip is an ancestor of default but not on its first-parent line, that is, it came in through a merge), `commit_time`, `has_path`, `first_added`, `tracked` |
| `table_rows(text)` | list of (int, str, str) | Nothing | [(line number, row text, first cell)] of every Markdown table body row (headers and separators left out). The first cell is cut at 70 characters |
| `live_pages(root, patterns=LIVE_PAGES)` | list of repository-relative paths | Nothing | The live pages that exist, globs expanded, in pattern order |
| `check_handoff_rows(root, git, now, days=DAYS['handoff-rows'])` | dict result (Outputs) | Nothing | Check 1; skipped without the handoff or git |
| `branch_mentions(row)` | list of (str, int, int) | Nothing | [(name, start, end)] of the work branches a row names; a match followed by `<`, `*`, `{` or `[`, or ending in `-`, is a pattern and left out |
| `clause(row, start, end)` | (str, int, int) | Nothing | The clause around a mention (from the previous cell border or sentence end to the next) and the mention's offsets in it |
| `merge_wording(text, start, end)` | `"merged"`, `"not merged"` or None | Nothing | What the clause says about the mention: the merge word nearest to it counts; "not merged", "unmerged" and "not pushed" read as not merged |
| `check_branches(root, git, now)` | dict result | Nothing | Check 2; skipped without branch refs, or when the clone holds a single branch (a branch and its `origin/` copy count once). A branch named twice in one row is judged once: any mention that records it is enough |
| `load_renames(root)` | list of rename dicts, or None when `docs/renames.json` is absent | `StaleError` on a bad file | Each needs `old`, `new`, `since` (YYYY-MM-DD) and `source`; optional `keep` (a list of phrases) and `allow_formerly` (true or false) |
| `stale_name_hits(text, rename)` | list of (int, bool) | Nothing | [(line number, in a table row)] of lines that still use rename's old name: fenced code, inline code spans, `keep` phrases and dated history bullets from before the rename are left out; a table row counts even beside the new name; case-insensitive, and the old name must start a word |
| `stale_name_lines(text, rename)` | list of int | Nothing | Line numbers of `stale_name_hits` |
| `check_names(root, git=None, now=None)` | dict result | `StaleError` from `load_renames` | Check 3; renames are read in registry order, and a line a longer old name flags is not flagged again by a shorter one |
| `known_paths(root, git)` | set of tracked paths and their folders, or None without git | `StaleError` on a bad `docs/tools/pending.json` | Pages listed in `docs/tools/pending.json`, when it exists, count as known |
| `dead_links(root, rel, text, known)` | list of link targets | Nothing | Relative links in text (page rel) that do not resolve; URLs, anchors and fenced code are skipped; with `known` None the disk decides |
| `check_links(root, git, now=None)` | dict result | `StaleError` from `known_paths` | Check 4; skipped when no live page exists |
| `check_map(root, git, now=None)` | dict result | `StaleError` from `known_paths` | Check 5; skipped without `docs/MAP.md` |
| `check_routines(root, git, now, days=DAYS['routines'])` | dict result | `StaleError` on a bad registry | Check 6; a routine's age is when its `"name"` line first appeared in git |
| `container_paths(row)` | list of str | Nothing | Worktree and scratchpad paths in a row, the checkout roots left out |
| `check_handoff_paths(root, git, now, days=DAYS['handoff-paths'])` | dict result | Nothing | Check 7 |
| `load_freezes(root)` | list of freeze dicts, or None when the registry is absent | `StaleError` listing every problem | Scrolls-private's freeze registry; None here |
| `check_freezes(root, git, now, days=DAYS['freezes'])` | dict result | `StaleError` from `load_freezes` | Check 8; skipped here |
| `approval_date(a, git=None)` | Aware `datetime` (start of the UTC day), or None | Nothing | The day an approval was given: approved_on, else the first dated phrase in its approved text (`16 Oct 2026`, `2026-10-16`), else when its id first appeared in the approvals file (git) |
| `check_approvals(root, git, now, days=DAYS['approvals'])` | dict result | `StaleError` on a bad approvals file or ledger | Check 9; skipped here (no approvals file and no `kit/budget.py`) |
| `run_checks(root=ROOT, now=None, only=(), days=None, git=None)` | dict report (Outputs) | Nothing | {"exit": code, "checks": [results]}; a malformed registry makes its check "fail" and the exit 1. `days` overrides entries of `DAYS` |
| `format_report(report)` | str | Nothing | The text view: one status line per check, then each check that needs a look with its findings |
| `add_arguments(p)` | None | Nothing | Adds the options to an argparse parser |
| `run(args)` | int exit code | Nothing | The command line's work |
| `main(argv=None)` | int exit code | `SystemExit` on a bad argument | `python -m kit.stale` |

## Inputs

All read from the repository root; none is required (a check whose input is missing is skipped).

| Input | Used by | Format |
| --- | --- | --- |
| `docs/HANDOFF.md` and its git history | handoff-rows, branches, handoff-paths | Markdown tables; every body row counts |
| Live pages (`LIVE_PAGES`) | names, links | Markdown |
| `docs/renames.json` | names | `{"renames": [{"old", "new", "since", "source", "keep", "allow_formerly"}]}`; `since` is YYYY-MM-DD; `keep` (optional) lists phrases where the old name is meant, such as `letter reader renamed Scroll Text Reader`; `allow_formerly` (optional, default true) lets a prose line keep the old name beside the new one. The committed list (18 Oct 2026) retires `Greek letter reader` for Scroll Text Reader since 2026-10-17 (commit `d3dc343`). Scrolls-private also retires the shorter `letter reader`; this list does not yet, because about 50 public live-page lines use "the letter reader" as a plain description |
| `docs/tools/pending.json` | links, map | `{"pages": [ids]}`, when it exists: tool pages still to be written count as present |
| `docs/MAP.md` | map | Paths in backticks starting `kit/` or `scripts/` |
| `docs/routines.json` and its git history | routines | The routine registry ([routines](routines.md)) |

## Outputs

The text view prints `kit stale: N checks, K need a look (NOW)`, one line per check (`status`, name, a summary), then for each check marked attention or fail a `--- NAME (STATUS) ---` block with one `WHERE: TEXT` line per finding (or the error for a fail). `--json` prints:

| Field | Type | Meaning |
| --- | --- | --- |
| `exit` | int | The exit code |
| `now` | string | The time ages were judged at, `YYYY-MM-DDTHH:MM:SSZ` |
| `checks` | list | One object per check run, in order |
| `checks[].name` | string | The check |
| `checks[].status` | string | `ok`, `attention`, `skipped` or `fail` |
| `checks[].findings` | list | Objects with `where` (a path, with `:LINE` where it applies) and `text` (what is stale and what to do) |
| `checks[].info` | list of strings | A summary; for `skipped` why, for `fail` the registry error; in a shallow clone the lower-bound note |

| Exit code | Meaning |
| --- | --- |
| `0` | Every check that ran is ok (some may be skipped) |
| `1` | A registry is malformed (`fail`): fix it first |
| `2` | A bad argument, or `--now` is not an ISO time |
| `3` | At least one finding needs a look (the routines workflow fails on it) |
| `75` | Every check was skipped (no inputs and no git here) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `needs a list under "renames"` | `docs/renames.json` does not hold a `renames` list | Fix the file's shape |
| `needs a list under "routines"` | `docs/routines.json` does not hold a `routines` list | Fix the registry ([routines](routines.md)) |
| `needs a list under "freezes"` | A freeze registry exists but does not hold a `freezes` list (Scrolls-private only) | Fix the registry's shape |
| `is not JSON:` | A registry does not parse | Fix the JSON |
| `docs/renames.json renames[N] needs old, new, since and source` | A rename entry lacks a field | Fill it in |
| `docs/renames.json renames[N].keep must be a list of phrases` | A rename's `keep` is not a list of non-empty strings | Write a list of phrases |
| `docs/renames.json renames[N].allow_formerly must be true or false` | A rename's `allow_formerly` is not a boolean | Write `true` or `false` |
| `kit stale: --now is not an ISO time:` | `--now` did not parse (exit 2) | Write it as `2026-10-18T20:00:00Z` |
| `docs/renames.json renames[N].since is not YYYY-MM-DD: VALUE` | A rename's date is in another format | Write YYYY-MM-DD |
| `skipped` with `git cannot say when rows changed` or `no branch refs in this clone` | No git, or a clone without refs | Run from a clone |
| `skipped` with `this clone holds a single branch` | A CI checkout or a single-branch clone, where every other named branch would look deleted | Nothing in CI; locally, `git fetch origin` to get the other branches |
| `skipped` with `no docs/compute/freezes.json` (or another input) | The input is not in this repository | Nothing; that check does not apply here |
| `names branch B, which this clone does not have` | The branch was deleted after its merge, or never pushed, or not fetched, and no PR or commit is named beside it | Name the merge commit or PR beside the branch in the row; `git fetch` first if unsure |
| `names branch B, which is merged into D, but the row says not merged or not pushed beside it` | The row still describes the branch as open | Write "merged (#PR)" in the clause that names it, or move the row on |
| `says "OLD", renamed "NEW" on DATE` | A live page still uses a retired name | Write the new name on that line; a table row gives the new name alone |
| `link to X does not resolve` | A live page links to a file git does not track | Fix the link, or commit the file |
| `fail` on `approvals` with `cannot read docs/compute/modal-ledger.csv: REASON` | The Modal ledger exists but cannot be read or has a malformed row (Scrolls-private, where `kit.budget` exists; here the check is skipped) | Fix the row the reason names, or restore the file from git |

## How it works

1. `run_checks` builds one `Git` for the repository and runs the selected checks in order, catching `StaleError` as a `fail` for that check only.
2. Row ages: `git blame --line-porcelain docs/HANDOFF.md` gives each line's committer time; uncommitted lines count as new. `git rev-parse --is-shallow-repository` decides the lower-bound note.
3. Branches: when the clone holds at least two branches (a local branch and its `origin/` copy count once; `origin/HEAD` is left out), `BRANCH` finds work branch names in each table row (patterns left out); a name is gone when neither `NAME` nor `origin/NAME` is among `git for-each-ref` refs, and merged when `git merge-base --is-ancestor` puts its tip in the default branch (the first of `DEFAULT_BRANCHES` present: `origin/grok/laneJ-title`, `grok/laneJ-title`, `origin/main`, `main`) and the tip is not on that branch's first-parent line (`git rev-list --first-parent`). GitHub's merge button makes a merge commit, so a merged branch's tip is a second parent; a fast-forward merge would read as not merged. The merge word (`MERGE_WORD`) nearest to the mention within its clause (`CLAUSE_BREAK`) decides what the row says; `PR_OR_COMMIT` finds a PR number or commit beside a gone branch.
4. Names: each live page line, with fenced code blanked and inline code spans and `keep` phrases removed, that holds the old name (case-insensitive, at a word start); a table row counts even beside the new name, a prose line only without it (or always, with `allow_formerly` false); a history bullet dated before `since` is left alone.
5. Links and map: targets resolve against `git ls-files` (and their folders), as `tests/test_repo.py`'s link test does; a map path right after "as" (`OTHER_TREE`) is skipped.
6. Routines: `git log -S` finds when the routine's entry first appeared.

Constants: `DAYS = {"handoff-rows": 7, "routines": 7, "handoff-paths": 2, "freezes": 14, "approvals": 14}`; exit codes `EXIT_OK, EXIT_FAIL, EXIT_ATTENTION, EXIT_SKIPPED = 0, 1, 3, 75`.

## Cost and time

0.94 s wall and 28 MB peak memory for all nine checks on this repository (69 live pages, 70 remote refs; measured 2026-10-18 on a 4-core Intel Xeon at 2.10 GHz cloud container). The routine allows 120 s. Rents nothing.

## For agents

- **Command:** `python3 -m kit stale`; machine-readable: `python3 -m kit stale --json`.
- **Parse:** `exit`; per entry of `checks`, `status` (`attention` and `fail` need a look) and each finding's `where` and `text`.
- **Rerun:** Safe; it writes nothing.
- **Success:** Exit 0 and no check with `attention` or `fail`.
- **Not a pass:** A check `skipped` (it checked nothing); a quiet `branches` check in a clone that was not fetched; a quiet `handoff-rows` check right after a commit that rewrote every row, or in a shallow clone.
- **Go-ahead:** Nothing to run it. Acting on a finding follows the usual rules: deleting a branch others may need, or posting, still needs its own yes.
- **Never:** Edit a published record (`docs/prereg/`, `docs/evidence/`, `docs/logs/`) to quiet a finding; delete an unmerged, `submission/*` or `release-readme/*` branch; weaken a check, or drop the routine's `ci` mark, to make the workflow pass.

## Tests

```bash
python3 -m unittest discover -s tests -p "test_stale.py" -v
```

44 tests, passing on 2026-10-18, 4 of them skipped here (three approval checks that need `kit/budget.py` and the freeze registry test, Scrolls-private only). They build small git repositories with commits at fixed dates and cover each check's planted stale case and its fresh counterpart (for branches also negated merge words, another item merged in the same row, placeholder patterns, a gone branch with its PR or commit, a branch with no commits, and the skip in a depth-1 single-branch clone, on `main` or on a work branch, against a clone with two branches; for names also table rows, `keep`, inline code, `allow_formerly` and a longer old name flagging a line once), the shallow-clone note, the skips (no git, no input), every refusal of a malformed registry, approval dates, exit codes, the text view, the CLI wiring, the `stale` routine and its `ci` mark, that the committed `docs/renames.json` loads, and that the live pages use no retired name. The freeze and approval checks run on synthetic registries; the approval findings need `kit/budget.py` and are skipped here. They do not fetch.

## History

- 2026-10-18: first public version, from Scrolls-private's `kit/stale.py` (`7b2faa8e`) with two changes listed at the top of the file: the branch check skips in a clone that holds a single branch (the routines workflow's checkout), and the age checks note lower bounds in a shallow clone. The rename list `docs/renames.json` (the old name of Scroll Text Reader), the routine `stale` marked ci, and fixes for the 13 old-name lines and two handoff rows it found.

## Related

- [routines](routines.md): runs `stale` daily at session start, and the workflow runs it as a ci routine.
- [tooldocs](tooldocs.md): checks tool pages against their code.
- [letterread](letterread.md): Scroll Text Reader, whose old name the rename list retires.
- [HANDOFF.md](../HANDOFF.md): what the handoff checks read.
- [AI-AGENTS.md, Session start](../AI-AGENTS.md#session-start-repository-routines): the routines every agent runs.
