# routines: recurring read-only repository checks that any agent runs at session start

`python -m kit routines` runs the repository's recurring read-only checks, listed in `docs/routines.json`, whichever agent or account opens the clone, keeps each result in the ignored `work/routines/`, and is what the daily GitHub Actions check runs.

| Field | Value |
| --- | --- |
| Id | `routines` |
| Status | Current |
| Kind | kit command, kit module, kit entry point, workflow |
| Area | Releases and repository |
| Run | `python -m kit routines list`, `python -m kit routines due`, `python -m kit routines status`, `python -m kit routines run`, `python -m kit routines check`, `python -m kit.routines`, `from kit import routines` |
| Code | `kit/routines.py`, `docs/routines.json`, `.github/workflows/routines.yml`, `.claude/settings.json`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_routines.py`, `tests/test_routines_workflow.py` |
| Needs | Python 3.10 or newer (`requires-python` in `pyproject.toml`), standard library only. A clone of this repository, since the registry `docs/routines.json` is read next to `kit/`. `git` on the PATH for the handoff's age in `check handoff` (without it that line says git cannot say). Each routine has its own needs: `autopipeline-watch` needs the network ([batch](batch.md)) |
| Runs on | Any machine. `list`, `due`, `status` and `check handoff` took 0.11 to 0.15 s each (5 runs each), and `run --due` of six of the seven registered routines (all but `autopipeline-watch`) took 2.46 s wall, `prize-page` 0.6 s and `repo-tests` 1.2 s of it (measured 2026-10-17, 4-core Intel Xeon @ 2.80GHz cloud container, Python 3.13.16). `autopipeline-watch`: Not measured |
| Network | None for `list`, `due`, `status` and `check`. `run` contacts only what its routines contact: `prize-page` makes one HTTPS GET of `https://scrollprize.org/prizes` ([prizewatch](prizewatch.md)); `autopipeline-watch` reads `vesuvius-challenge-open-data.s3.amazonaws.com` and `https://scrollprize.org/prizes` ([batch](batch.md)); `prizes`, `releases`, `leaderboard`, `handoff` and `repo-tests` contact nothing. The daily workflow runs on GitHub's runner and fetches `actions/checkout` and `actions/setup-python` there |
| Writes | `list`, `due`, `status` and `check` write nothing. `run` writes in `work/routines/` (git-ignored by `/work/` in `.gitignore`), or in `--state DIR`: `state.json`, `summary.md`, `run.lock` while it runs, and with `--background` it appends to `last-run.log`; `.state.PID.tmp` and `.summary.PID.tmp` are renamed into place. The routines write their own files: `prize-page` rewrites `work/routines/prize-page.json`, and `autopipeline-watch` writes under `work/autobatch/` ([batch](batch.md)). With `GITHUB_STEP_SUMMARY` set, as in GitHub Actions, the summary is also appended to that file |
| Go-ahead | Not needed. Routines only check: the registry refuses any command that would post, upload, push, release or start Modal (`OUTWARD`), and every routine runs with credential variables removed from its environment |
| Released | Not on public `main` yet (checked 2026-10-17): added on branch `claude/project-thread-8zzi1i` (`5aed6e7`, 2026-10-16), in open [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100). The daily workflow starts running only once it is on `main`, because GitHub runs scheduled workflows on the default branch. Scrolls-private keeps an identical copy of the module with its own registry |
| Guide | [AI-AGENTS.md, "Session start: repository routines"](../AI-AGENTS.md#session-start-repository-routines) |
| Checked | 2026-10-17 against commit `1b620c6` |

## What it does

Chase moves between Claude accounts, ChatGPT and Codex during a day, sometimes every few hours because of usage limits (the rulebook quotes him, 16 October 2026, 10:02 UTC). A check scheduled in one account's scheduler stops when he switches, yet the repository's rules call for recurring checks: re-check the live prize page and add a new dated snapshot when it changes (rulebook rule 4), keep the README's release list in step with `docs/releases.json` (the releases rule, hard rule 15), keep the one handoff current and under its size limit (the one-handoff rule, hard rule 14), and look for new or changed scans in the open-data bucket. So the checks live in the repository, where every agent finds them.

A **routine** is one such check: a read-only command with a name, a cadence (`daily` or `weekly`, counted in UTC dates) and a timeout, listed in the registry [`docs/routines.json`](../routines.json) with a line on why the repository calls for it. `python -m kit routines run --due` runs the routines that are due, one after another, each in its own process group, with credential variables removed from its environment and a timeout that stops the whole group. It records each result as `ok`, `attention` (exit 3: something for an agent to look at), `skipped` (exit 75, offline, a missing third-party module, or a required file not here yet), `fail` or `timeout` in `work/routines/state.json`, and writes `work/routines/summary.md`, a table followed by the output of every routine that needs a look. `status` prints the same from the state file.

Three entry points start it. The Claude Code SessionStart hook in [`.claude/settings.json`](../../.claude/settings.json) runs `python3 -m kit routines run --due --background`, which returns at once and never fails the session (the hook ends with `exit 0`). The rulebook ([AI-AGENTS.md](../AI-AGENTS.md#session-start-repository-routines)) tells every other agent, such as Codex or ChatGPT, to run `python3 -m kit routines run --due` and read `python3 -m kit routines status` at session start. The daily workflow [`.github/workflows/routines.yml`](../../.github/workflows/routines.yml) runs the routines marked `ci` with `--strict`, then the whole unit test suite, on GitHub's runners with a read-only token and no secrets; GitHub states that "For public repositories, GitHub Actions minutes remain free" ([GitHub docs](https://docs.github.com/en/billing/concepts/product-billing/github-actions), read 2026-10-17), and the workflow's comment says a failed job makes GitHub notify the owner by email.

One routine is built in: `python -m kit routines check handoff` compares the sizes of `AGENTS.md` and `docs/HANDOFF.md` with the byte limits in `tests/test_repo.py` and says how long ago `docs/HANDOFF.md` was last committed.

It does not fix anything, post, comment, open issues, upload, push or start Modal. A row marked attention means an agent reads that routine's output and acts by hand, for example by adding a new prize snapshot. It is not a scheduler: nothing runs until a session starts or the workflow fires. A routine's result is the exit code of another tool, not a finding: `ok` says only that the command exited 0.

### The registered routines

At commit `1b620c6`, `docs/routines.json` lists seven, all daily:

| Routine | Timeout | `ci` | Command (after `{python} -m`) | What it checks |
| --- | --- | --- | --- | --- |
| `prize-page` | 60 s | yes | `kit.prizewatch --state work/routines/prize-page.json` | The live prize page against the dated snapshot ([prizewatch](prizewatch.md)) |
| `prizes` | 30 s | yes | `kit prizes` | The open prizes and days left from the snapshot ([prizes](prizes.md)) |
| `releases` | 30 s | yes | `kit releases check` | The README's Released tools section matches `docs/releases.json` ([releases](releases.md)) |
| `leaderboard` | 60 s | yes | `kit leaderboard check` (needs `kit/leaderboard.py`) | The ink reader leaderboard page matches `docs/results.json` ([leaderboard](leaderboard.md)) |
| `autopipeline-watch` | 300 s | no | `kit run watch --exit-code` | New or changed open-data bucket volumes, queued and priced in dry run; it launches nothing ([batch](batch.md)). Not in the workflow: a runner keeps no state, so every volume would look new |
| `handoff` | 60 s | no | `kit routines check handoff` | `AGENTS.md` and `docs/HANDOFF.md` sizes and the handoff's age |
| `repo-tests` | 300 s | no | `unittest tests.test_repo` | Size limits, no long dashes, relative links, the map and documented commands (the workflow runs the whole suite instead) |

## When to use it

- At the start of every session, whichever agent you are: `python3 -m kit routines run --due` (add `--background` to keep working), then `python3 -m kit routines status`, and act on any row marked attention, fail or timeout (the rulebook's session-start section).
- To rerun one check now, due or not: `python3 -m kit routines run --name NAME`.
- To reproduce a failed daily workflow on your machine: `python3 -m kit routines run --ci --strict`.
- To add a recurring check: add an entry to `docs/routines.json` (fields under Inputs) and its command to `READ_ONLY` in `tests/test_routines.py`, never to one account's scheduler.
- Before ending a session, to see that the handoff is current and under its limit: `python3 -m kit routines check handoff`.

Do not use it:

- To compare the prize page by hand, with its own options: run `python -m kit.prizewatch` ([prizewatch](prizewatch.md)).
- To plan, approve or launch AutoPipeline scans: use `python -m kit run all` and `run watch` directly ([batch](batch.md)); the routine runs the watcher in dry run only.
- For anything that posts, uploads, pushes or starts Modal: the registry refuses such commands, and each needs Chase's yes (the go-ahead rule, hard rule 8).
- For the whole test suite: `python -m unittest discover -s tests -v`; the `repo-tests` routine runs only `tests.test_repo`.
- To check the tool pages: `python -m kit.tooldocs check` ([tooldocs](tooldocs.md)).
- For long jobs: a routine's timeout is at most 3600 s (`MAX_TIMEOUT`); GPU work and long CPU jobs go to Modal (the Modal rule, hard rule 11).

## Quick start

```bash
python3 -m kit routines run --due
python3 -m kit routines status
```

On 2026-10-17 at 01:13 UTC this page's author ran the same `run --due` with `--registry` and `--state` pointing at scratch copies, so that the checkout's `work/` folder stayed untouched: the registry copy left out `autopipeline-watch` and gave `prize-page` a scratch `--state` path. It printed (the scratch path shortened):

```
kit routines: running 6: prize-page, prizes, releases, leaderboard, handoff, repo-tests
  prize-page             ok           0.6 s
  prizes                 ok           0.1 s
  releases               ok           0.1 s
  leaderboard            ok           0.1 s
  handoff                attention    0.1 s  needs a look (exit 3)
  repo-tests             ok           1.2 s
kit routines: results in /tmp/.../rt-docs/state6/summary.md
```

with exit code 0, and `status --brief` then printed:

```
kit routines: 1 of 6 need a look. Details: python3 -m kit routines status (work/routines/summary.md).
  handoff: attention at 2026-10-17T01:13:07Z. AGENTS.md: 19746 of 20000 bytes, only 254 left; keep new detail in docs/ (MAP.md, AI-AGENTS.md), not here
```

A second `run --due` printed `kit routines: nothing is due`. It worked when `run` exits 0 and every line reads `ok`. A line reading `attention`, `fail` or `timeout` is a result to act on: `python3 -m kit routines status` prints that routine's output under `--- NAME (STATUS) ---`.

## Checks and controls

- **A routine can fail, and the run says so.** On 2026-10-17 the `handoff` routine needed a look because `AGENTS.md` was 19,746 of its 20,000-byte limit (within the 0.9 warning fraction), and `python3 -m kit routines run --name handoff --strict` exited 1; without `--strict` the run exits 0 and records `attention`. The tests drive a fake routine through each outcome (`test_results_state_and_summary`: ok, attention, fail, timeout and two kinds of skipped) and pin the exit codes of `run` with and without `--strict` (`test_fail_and_strict_exit_codes`).
- **The registry guard can refuse.** `test_bad_entries_are_refused` checks that 20 bad entries are refused, among them a command that is not `{python} -m`, `pip install`, `kit hfsync`, `kit.submission_release`, `releases render`, `run all --approve`, `kit zerogpu` and an absolute or `..` path in `requires`, plus a doubled name and a registry without a `routines` list. `test_repo_registry_loads_and_holds_only_read_only_commands` fails when the real registry gains a command not in the test's `READ_ONLY` list, so a new routine needs someone to look at it.
- **Timeouts and credentials.** `test_timeout_stops_the_whole_process_group` starts a child that starts a grandchild, and checks both are gone after a 2 s timeout. `test_child_environment_has_no_credentials` and `test_a_routine_cannot_see_a_token` check that `GITHUB_TOKEN`, `KIT_ALLOW_MODAL` and other credential names never reach a routine.
- **The workflow stays read-only.** `tests/test_routines_workflow.py` checks the daily schedule and the hand trigger, `contents: read`, no `write` permission, no `secrets.`, no `pull_request_target`, `persist-credentials: false`, the `--ci --strict` step and the test step.
- **What a pass does not show.** `skipped` is not a pass: an offline machine, a missing third-party module, a required file not here yet, or a prize page that answers with an HTTP error (which [prizewatch](prizewatch.md) reports as exit 75) all record `skipped`, which never fails a run, even with `--strict`. A `fail` or `timeout` counts as done for that UTC day, so `--due` does not retry it until the next day; read `status`.

Claim label: None. The tool reports the exit codes of other tools; each routine's output carries its own claim, such as [prizewatch](prizewatch.md)'s comparison of the live page (Sourced fact).

## Commands and options

### Options of `python -m kit routines` (before the action)

```
usage: python -m kit routines [-h] [--registry REGISTRY] [--state STATE]
                              {list,due,status,run,check} ...
```

These two options belong to `routines` itself, so they go before the action: `python -m kit routines --registry R --state S run --due`. After the action they are refused (`unrecognized arguments`). `python -m kit.routines` takes the same options and actions and prints the same usage.

| Option | Default | Meaning |
| --- | --- | --- |
| `--registry REGISTRY` | `docs/routines.json` of the checkout that holds `kit/` (`REGISTRY`, an absolute path) | The routine list to read. `check` ignores it |
| `--state STATE` | `work/routines` of the checkout that holds `kit/` (`STATE_DIR`, an absolute path) | The results folder: `state.json`, `summary.md`, `run.lock`, `last-run.log`. `check` ignores it |

Whatever `--registry` says, `run` starts every routine with the checkout that holds `kit/` as its working directory, so relative paths in a command, such as `work/routines/prize-page.json`, land in that checkout.

### `python -m kit routines list`

```
usage: python -m kit routines list [-h]
```

No options of its own. Prints two lines per routine: the name (padded to 22), the cadence, the timeout in seconds, the command with `{python}` as written, `  (needs PATHS)` when it has `requires`, and `  [ci]` when it is marked `ci`; then its `why`, indented.

### `python -m kit routines due`

```
usage: python -m kit routines due [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | Print the due routines' names as one JSON list, such as `["prize-page", "prizes"]`, instead of one name per line or `nothing is due` |

### `python -m kit routines status`

```
usage: python -m kit routines status [-h] [--json] [--brief]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | Print one JSON object per routine (fields under Outputs) instead of the table. Takes precedence over `--brief` |
| `--brief` | off | One line, plus one per routine that needs a look: `kit routines: N of M need a look` or `none of M need a look`, the routines never run here, and for each attention, fail or timeout row its last output line (at most 160 characters) |

### `python -m kit routines run`

```
usage: python -m kit routines run [-h] [--due | --ci] [--name NAME]
                                  [--background] [--budget BUDGET] [--strict]
```

With none of `--due`, `--ci` and `--name`, it runs every routine in the registry, due or not, including `autopipeline-watch`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--due` | off | Only the routines due now (rules under How it works). Not with `--ci` |
| `--ci` | off | The routines marked `"ci": true`, due or not; what the daily workflow runs. Not with `--due` |
| `--name NAME` | none | Run this routine now, due or not. Repeatable, run in the order given. Wins over `--due` and `--ci`. An unknown name stops with exit 2 |
| `--background` | off | Start the run as a detached process with its output appended to `STATE/last-run.log`, print `kit routines: started in the background: NAMES.` (when anything is selected) and the `--brief` status from before the run, and exit 0 at once. The SessionStart hook uses it. `--strict` is not passed to the background run |
| `--budget BUDGET` | none | Seconds. Start no routine after this much time has passed since the run began; the ones not started print `left for next time` and stay due. A routine already running is not cut short (its own timeout does that) |
| `--strict` | off | Exit 1 when any routine needed attention, as well as on fail and timeout. The daily workflow uses it |

### `python -m kit routines check`

```
usage: python -m kit routines check [-h] [--max-age-days MAX_AGE_DAYS]
                                    [--warn-fraction WARN_FRACTION]
                                    {handoff}
```

The built-in check the `handoff` routine calls. It always checks the checkout that holds `kit/`.

| Option | Default | Meaning |
| --- | --- | --- |
| `what` | required | The check to run; the only choice is `handoff` |
| `--max-age-days MAX_AGE_DAYS` | `3.0` | Days since `docs/HANDOFF.md` was last committed after which it needs a look (exit 3). Not counted while the file has uncommitted changes |
| `--warn-fraction WARN_FRACTION` | `0.9` | A file at or above this fraction of its byte limit needs a look (exit 3); above the limit it fails (exit 1) |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `GITHUB_STEP_SUMMARY` | unset | When set (GitHub Actions sets it to a file path), each `run` also appends `summary.md`'s text to that file, so the workflow run's page shows the table. A write error is ignored |

Each routine runs with `SCROLLS_ROUTINE=1`, `GIT_TERMINAL_PROMPT=0` and `PYTHONUNBUFFERED=1` added, and without every variable whose name matches `SECRET_ENV`: names holding `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `API_KEY` or `APIKEY`, `ACCESS_KEY`, `PRIVATE_KEY` or `CREDENTIAL` (any case), names starting `MODAL_`, and `SSH_AUTH_SOCK` and `KIT_ALLOW_MODAL`. Proxy settings such as `HTTPS_PROXY` are kept.

## Python API

```python
from kit import routines
todo = routines.due(routines.load(), routines.load_state(routines.STATE_DIR), routines.utcnow())
print([r["name"] for r in todo])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `RoutineError` | An exception class, a subclass of `ValueError` | Not applicable | Every registry and `--name` problem; `run` prints it as `routines: MESSAGE` and returns 2 |
| `utcnow()` | `datetime`: now, aware, in UTC | Nothing | |
| `validate(registry)` | list of dict: the routines, each with `requires` (default `[]`) and `ci` (default `False`) filled in | `RoutineError` | The rules under Inputs; calls `check_command` |
| `check_command(name, cmd)` | None | `RoutineError` | Refuses a command that does not start `{python}`, `-m`, then `kit`, `unittest` or `kit.MODULE`, or that holds a word of `OUTWARD` (compared in lower case, whole arguments only) |
| `load(path=REGISTRY)` | list of dict: the validated routines | `RoutineError` for a missing file, bad JSON or a bad entry | |
| `load_state(state_dir)` | dict `{"version": 1, "routines": {...}}` | Nothing | A missing, unreadable or damaged `state.json` gives the empty state |
| `save_state(state_dir, state)` | None | `OSError` | Creates the folder, writes `.state.PID.tmp` (2-space indent, sorted keys) and renames it to `state.json` |
| `is_due(routine, entry, now)` | bool | `KeyError` for a cadence not in `CADENCE_DAYS` (`validate` prevents it) | Not due when last attempted less than `RETRY` (1 hour) ago; otherwise due when never completed, when `last_completed` is not a date, or when it is at least 1 (daily) or 7 (weekly) UTC dates before `now` |
| `due(routines, state, now)` | list of dict: the due routines, in registry order | Nothing | |
| `child_env(base=None)` | dict: a routine's environment | Nothing | `base` defaults to `os.environ`; see Environment variables |
| `execute(argv, cwd, timeout, env=None)` | `(exit code, output text)`; the code is `None` after a timeout | Nothing for the command's sake | stdin from the null device; stdout and stderr together; a new session on POSIX. On timeout: SIGTERM to the process group, SIGKILL after 5 s, and `stopped after the N s timeout` appended. A program that cannot start gives `(75, "cannot start PROGRAM: ERROR")` |
| `classify(code, output)` | `(status, note)` | Nothing | The rules under How it works |
| `run_one(routine, root, now=None, executor=execute)` | dict: `status`, `code`, `note`, `output`, `started`, `seconds` | Nothing | A missing `requires` path gives `skipped`, `not here yet: PATHS`, without running anything. `{python}` becomes `sys.executable`. `output` keeps the last `TAIL_LINES` (40) lines and at most `TAIL_CHARS` (4000) characters |
| `record(state, routine, result)` | dict: the routine's state entry | Nothing | Sets `last` and `last_attempt`, sets `last_completed` (the UTC date) unless the result is skipped, and keeps the last 10 `history` lines |
| `acquire_lock(state_dir, stale_after)` | bool: `True` when this run holds `run.lock` | `OSError` when the folder cannot be made | Takes over a lock older than `stale_after` seconds, one whose process is gone, or one it cannot read |
| `release_lock(state_dir)` | None | Nothing | Removes `run.lock` |
| `run_routines(selected, root=ROOT, state_dir=STATE_DIR, now=None, executor=execute, budget=None, log=None, clock=time.monotonic, registry=None)` | dict of results by name, or `None` when another run holds the lock | `OSError` from the state folder | Runs in order, saving state after each; writes the summary for every routine in `registry` (default: the selected ones); always releases the lock. The lock counts as stale after the selected routines' timeouts plus 120 s |
| `rows(routines, state, now)` | list of dict: one per routine, fields under Outputs | Nothing | What `status --json` prints |
| `summary_markdown(routines, state, now)` | str: the text of `summary.md` | Nothing | |
| `write_summary(state_dir, routines, state, now)` | str: the same text | `OSError` from the state folder | Writes `summary.md` through `.summary.PID.tmp`, and appends to `GITHUB_STEP_SUMMARY` when set |
| `status_text(routines, state, now, brief=False)` | str: what `status` or `status --brief` prints | Nothing | |
| `size_limits(root)` | dict `{path: bytes}`, or `{}` when none are found | Nothing | Reads the `for rel, limit in {...}.items()` literal of `test_agent_entry_files_stay_short` in `tests/test_repo.py` (`LIMITS`) |
| `check_handoff(root=ROOT, max_age_days=3, warn_fraction=0.9, now=None, last_change=_git_last_change, handoff='docs/HANDOFF.md')` | `(exit code, lines)`: 1, 3 or 0, problem lines last | Nothing | `_git_last_change` runs `git log -1 --format=%cI` and `git diff --quiet HEAD` on the file, 20 s timeout each |
| `add_arguments(p)` | None | Nothing | Adds `--registry`, `--state` and the five actions to an argparse parser; `kit/cli.py` uses it |
| `select(routines, state, now, args)` | list of dict: the routines to run | `RoutineError` for an unknown `--name` | `--name`, else `--ci`, else `--due`, else all |
| `spawn_background(args, root=ROOT, popen=subprocess.Popen)` | None | `OSError` | Starts `python -m kit routines --registry R --state S run` with the same selection and `--budget`, detached (a new session on POSIX), and appends a `== TIME ARGS` line and the child's output to `last-run.log` |
| `run(args)` | int: the exit code | Nothing for `RoutineError`, which it prints | The command; `kit/cli.py` sets it as the command's function |
| `main(argv=None)` | int: the exit code | `SystemExit` with code 2 on a usage error | Builds its own parser; `python -m kit.routines` and the tests call it |

Module constants: `ROOT`, `REGISTRY`, `STATE_DIR`, `CADENCE_DAYS` (`{"daily": 1, "weekly": 7}`), the statuses `OK`, `ATTENTION`, `SKIPPED`, `FAIL`, `TIMEOUT`, `EXIT_ATTENTION` (3), `EXIT_SKIPPED` (75), `COMPLETED`, `RETRY` (1 hour), `MAX_TIMEOUT` (3600), `TAIL_LINES` (40), `TAIL_CHARS` (4000), `NAME`, `OUTWARD`, `SECRET_ENV`, `OFFLINE`, `MISSING` and `LIMITS`.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| The registry | JSON at `docs/routines.json` (`REGISTRY`), or `--registry` | An object with `routines`, a list; other keys, such as the file's `about`, are ignored |
| The state folder | `work/routines/` (`STATE_DIR`), or `--state` | Read by `due`, `status` and `run`; fields under Outputs. A missing or damaged `state.json` counts as no runs yet |
| The size limits | The dict literal in `tests/test_repo.py`'s `test_agent_entry_files_stay_short` | Read by `check handoff`. At `1b620c6`: `AGENTS.md` 20,000 bytes and `docs/HANDOFF.md` 40,000 bytes |
| The handoff's history | `git log` and `git diff` of `docs/HANDOFF.md` | Read by `check handoff` |

Each routine in the registry:

| Field | Type | Rule |
| --- | --- | --- |
| `name` | str | Lower case letters, digits and `-`, starting with a letter or digit, at most 40 characters (`NAME`); unique |
| `cadence` | str | `daily` or `weekly` |
| `timeout_s` | number (seconds) | Greater than 0 and at most 3600 (`MAX_TIMEOUT`); not a boolean |
| `command` | list of non-empty str | `{python}` (replaced by the running interpreter), `-m`, then `kit`, `kit.MODULE` or `unittest`, then arguments; no argument may be a word of `OUTWARD`, such as `push`, `upload`, `post`, `submit`, `release`, `render`, `add`, `modal` or `--approve` |
| `why` | str | Not empty: where the repository calls for the check |
| `requires` | list of str, optional | Paths relative to the checkout, without `..`; while one is missing the routine is skipped as `not here yet` |
| `ci` | bool, optional | `true`: the daily workflow runs it (`run --ci`). Default `false` |

## Outputs

`run` prints `kit routines: running N: NAMES`, then one line per routine (name padded to 22, status, seconds, note), then `kit routines: results in STATE/summary.md`. `due` prints names or `nothing is due`. `list`, `status` and `check` are described under Commands and options.

`status --json` prints a list with one object per routine:

| Field | Type | Meaning |
| --- | --- | --- |
| `name`, `cadence` | str | From the registry |
| `last_run` | str or null | When the last run started, UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `status` | str | `ok`, `attention`, `skipped`, `fail`, `timeout`, or `never run` |
| `note` | str | Why, such as `needs a look (exit 3)` or `looks offline (exit 2)`; empty for ok |
| `due` | bool | Whether it is due now |
| `output` | str | The tail of its last output (40 lines, 4000 characters at most) |

`work/routines/state.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | int | 1 |
| `routines.NAME.last` | object | The last result: `status`, `code` (int, or null after a timeout or a skip for a missing path), `note`, `output`, `started` (UTC), `seconds` (float, wall time) |
| `routines.NAME.last_attempt` | str | When it last started, UTC |
| `routines.NAME.last_completed` | str | The UTC date of the last run that was not skipped |
| `routines.NAME.history` | list of str | The last 10 runs, each `TIME STATUS` |

`work/routines/summary.md` holds a `| Routine | Cadence | Last run (UTC) | Result | Note | Due now |` table for every routine in the registry, then, under `## Needs a look`, each attention, fail or timeout routine's output in a `text` block. `run.lock` holds `{"pid": PID, "t": UNIX_TIME}` while a run goes, and is removed after it. `last-run.log` collects the output of background runs and is never trimmed.

The statuses a routine gets:

| Status | From | Counts as done for the day |
| --- | --- | --- |
| `ok` | exit 0 | Yes |
| `attention` | exit 3 | Yes |
| `skipped` | exit 75; a program that cannot start; output with `ModuleNotFoundError` for a module outside `kit` and `tests`; output that looks offline; a `requires` path missing | No: due again an hour after the attempt |
| `fail` | any other exit code | Yes |
| `timeout` | still running at `timeout_s` | Yes |

| Exit code | Meaning |
| --- | --- |
| `0` | `list`, `due` and `status` printed. `run`: no routine failed or timed out (and, with `--strict`, none needed attention), or nothing was due, or another run holds the lock, or `--background` started it. `check`: nothing to report |
| `1` | `run`: a routine failed or timed out, or with `--strict` needed attention. `check`: a file is over its limit or missing |
| `2` | A usage error, a bad registry or an unknown `--name` |
| `3` | `check`: something needs a look: a file within the warning fraction of its limit, no limits found in `tests/test_repo.py`, or a handoff not committed for more than `--max-age-days` |

## Failure modes

Registry and `--name` problems print `routines: MESSAGE` on stderr and exit 2. `NAME` stands for the routine's name and `PATH` for a file.

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `python -m kit routines: error: the following arguments are required: action` | No action given | Add `list`, `due`, `status`, `run` or `check` |
| `python -m kit: error: unrecognized arguments: --registry x` | `--registry` or `--state` given after the action | Put them before the action |
| `python -m kit routines run: error: argument --ci: not allowed with argument --due` | `--due` and `--ci` together | Give one of them |
| `python -m kit routines check: error: argument what: invalid choice: 'nothing' (choose from 'handoff')` | A check other than `handoff` | Use `check handoff` |
| `routines: no routine registry at PATH; run kit routines from a clone of the repository` | The registry file is not there: an installed package (`scrolls-workbench routines`), or a wrong `--registry` | Run it from a clone of this repository, or give `--registry` |
| `routines: PATH is not JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)`, or another JSON message | The registry is not valid JSON | Fix the JSON |
| `routines: the registry needs a list under "routines"` | The file is not an object with a `routines` list | Restore the shape |
| `routines: routine name 'Has Space': lower case letters, digits and -, at most 40` | A missing name, or one with capitals, spaces or over 40 characters | Rename it |
| `routines: routine NAME is listed twice` | Two entries with one name | Keep one |
| `routines: routine NAME: cadence must be one of ['daily', 'weekly']` | Another cadence, such as `hourly` | Use `daily` or `weekly` |
| `routines: routine NAME: timeout_s must be a number of seconds, at most 3600` | Missing, zero, negative, a boolean, or over 3600 | Give seconds up to 3600; a longer job does not belong in a routine |
| `routines: routine NAME: command must be a list of strings` | Empty, a string, or with an empty argument | Give an argument list |
| `routines: routine NAME: the command must start with {python} -m` | A command such as `python3 -m ...` or `{python} -c ...` | Start it with `"{python}", "-m"` |
| `routines: routine NAME: only kit, kit.MODULE or unittest may run, not pip` | A module other than `kit`, `kit.MODULE` or `unittest` | Routines run only kit tools and tests |
| `routines: routine NAME: 'render' looks like an outward action; routines only check` | An argument in `OUTWARD`, such as `render`, `push`, `--approve` or `kit.hfsync` | Use the tool's checking action (such as `releases check`); outward actions need Chase's yes and stay out of routines |
| `routines: routine NAME: requires must list paths inside the repository` | An absolute path or one with `..` | Give a path relative to the checkout |
| `routines: routine NAME: say why the repository calls for it` | No `why` | Write where the repository asks for the check |
| `routines: no routine named nope; see python3 -m kit routines list` | `--name` with a name not in the registry | Check the names with `list` |
| `kit routines: another run is in progress (work/routines/run.lock); nothing started`, exit 0 | Another run holds the lock, such as the SessionStart hook's background run | Wait, then read `status`. A lock left by a dead process, or older than the selected timeouts plus 120 s, is taken over |
| `  NAME  left for next time (the N s budget is used)` | `--budget` ran out before this routine started | It stays due; run again later |
| `skipped`, note `not here yet: PATH` | A `requires` path is missing | Nothing; it runs once the file lands |
| `skipped`, note `looks offline (exit N)` | The output matched `OFFLINE`, such as `urlopen error` or `Name or service not known` | Run again with network |
| `skipped`, note `missing dependency MODULE (exit N)` | A third-party module is not installed | Install it if the routine matters here |
| `skipped`, note `not available here (exit 75)`; output `cannot start PROGRAM: ...` | The routine exited 75, or the interpreter could not start | Read its output in `status --json` |
| `timeout`, note `ran past its timeout and was stopped`; output ends `stopped after the N s timeout` | The routine ran past `timeout_s`; its process group was stopped | Read the output; raise `timeout_s` only if the check is meant to take that long |
| `fail`, note `exit N` | Any other exit code, including a `ModuleNotFoundError` for `kit` or `tests` | Read its output in `status`; it is not retried by `--due` until the next UTC day |
| `AGENTS.md: N of 20000 bytes, only N left; keep new detail in docs/ (MAP.md, AI-AGENTS.md), not here`, exit 3 | `check handoff`: the file is within the warning fraction of its limit | Move detail out of `AGENTS.md` before it fails `tests/test_repo.py` |
| `docs/HANDOFF.md: N of 40000 bytes, only N left; move its oldest dated sections, unchanged, to the top of docs/HANDOFF-archive.md`, exit 3 | The same for the handoff | Do what it says |
| `PATH: N bytes, over its N-byte limit; tests/test_repo.py fails`, exit 1 | The file is over its limit | Shorten it as above |
| `PATH: missing`, exit 1 | A file named in the limits does not exist in the checkout that holds `kit/` | Restore it |
| `no size limits found in tests/test_repo.py (test_agent_entry_files_stay_short); check by hand`, exit 3 | The limits literal was renamed or moved | Check the sizes by hand, and update `LIMITS` in `kit/routines.py` |
| `docs/HANDOFF.md: last committed TIME, N days ago; check its open items are current and update it on the default branch (AGENTS.md rule 14)`, exit 3 | The handoff was not committed for more than `--max-age-days` | Bring its open items up to date |
| `docs/HANDOFF.md: git cannot say when it last changed` | No git, not a git checkout, or the file was never committed | Nothing; the age is not checked |
| `docs/HANDOFF.md: has uncommitted changes (being edited now)` | The handoff has local edits | Nothing; the age is not checked |

## How it works

1. `load` reads the registry and `validate` checks every entry; `check_command` allows only `{python} -m kit ...`, `{python} -m kit.MODULE ...` and `{python} -m unittest ...`, and refuses any argument that is a word of `OUTWARD`.
2. `load_state` reads `STATE/state.json`. `is_due` decides per routine: a routine attempted less than `RETRY` (1 hour) ago is not due, so a skipped one is not retried at every session start; otherwise it is due when it never completed, or when its `last_completed` UTC date is at least `CADENCE_DAYS` (1 or 7) dates before today's UTC date.
3. `select` picks `--name`, else `--ci`, else `--due`, else every routine. With `--background`, `spawn_background` starts the same `run` as a detached process and returns.
4. `run_routines` takes `STATE/run.lock` (created with `O_EXCL`), then for each routine: if `--budget` seconds have passed since the start, it leaves the rest for next time; a missing `requires` path makes it `skipped`; otherwise `execute` runs the command from the checkout root with `child_env()`, in a new process group, with stdout and stderr together, and stops the group with SIGTERM, then SIGKILL after 5 s, when `timeout_s` runs out.
5. `classify` turns the exit code and output into a status: `None` is `timeout`, 0 `ok`, 3 `attention`, 75 `skipped`; for any other code, output matching `MISSING` for a module outside `kit` and `tests` is `skipped` (`missing dependency`), output matching `OFFLINE` is `skipped` (`looks offline`), and anything else is `fail`.
6. `record` stores the result and its UTC start, keeps the last 10 history lines, and marks the UTC date as completed unless the result was `skipped`. The state file is saved after each routine through a temporary file and a rename.
7. `write_summary` writes `summary.md` for every routine in the registry, and appends it to `GITHUB_STEP_SUMMARY` when that is set. The lock is released, and `run` exits 1 when a routine failed or timed out (or, with `--strict`, needed attention).
8. `check handoff` reads the limits from `tests/test_repo.py` with `LIMITS` and `ast.literal_eval`, compares each file's size in bytes, and asks git for the committer date of the last commit that touched `docs/HANDOFF.md`. The worst finding sets the exit code: 1 over 3 over 0.

## Cost and time

Measured 2026-10-17 in a 4-core Intel Xeon @ 2.80GHz cloud container (16 GB memory), Python 3.13.16:

| Run | Wall time | Source |
| --- | --- | --- |
| `list`, `due`, `status`, `status --brief`, `check handoff` | 0.11 to 0.15 s each, 5 runs each, peak resident memory about 24 MB | This page's author, with Python's `resource.getrusage` |
| `run --due` of six routines (all but `autopipeline-watch`) | 2.46 s: `prize-page` 0.6 s, `repo-tests` 1.2 s, the others 0.1 s each | The run under Quick start |
| `run --ci --strict` (the four `ci` routines) | 1.47 s | Same day and machine, scratch state |
| `run --background` | 0.17 s until the prompt returned | Same day and machine |
| `autopipeline-watch` | Not measured; its timeout is 300 s | |

It rents nothing and runs anywhere. The daily workflow runs on GitHub's standard runners, free for public repositories ([GitHub docs](https://docs.github.com/en/billing/concepts/product-billing/github-actions), read 2026-10-17), with a 15-minute job limit (`timeout-minutes: 15`).

## For agents

- **Command:** `python3 -m kit routines run --due` at session start (`--background` to keep working), then `python3 -m kit routines status --json` (machine-readable) or `status --brief`.
- **Parse:** from `status --json`, per routine `name`, `status` (`ok`, `attention`, `skipped`, `fail`, `timeout`, `never run`), `note`, `due`, `last_run` (UTC) and `output`. Act on `attention`, `fail` and `timeout`: the cause is in `output`. `due --json` is a list of names.
- **Rerun:** Safe. `run --due` runs nothing that already completed this UTC day or was attempted in the last hour; `run --name` reruns now, replacing that routine's `last` and adding a `history` line. `state.json` and `summary.md` are rewritten, `last-run.log` grows. A second run while one holds the lock starts nothing and exits 0.
- **Success:** `run` exits 0 and every routine line reads `ok`; with `--strict`, exit 0 means none needed attention, failed or timed out. `check handoff` exits 0.
- **Not a pass:** `skipped` (offline, missing module, a required file not here yet, or a prize page answering with an HTTP error), `never run`, and a `run` that exits 0 without `--strict` while a routine needed attention. A status from another machine or another `--state` folder says nothing about this one.
- **Go-ahead:** Nothing for running routines. Acting on what a routine reports, such as posting, uploading, submitting or launching on Modal, needs Chase's yes (the go-ahead rule, hard rule 8).
- **Never:** Add a routine that posts, comments, opens issues, uploads, pushes, releases or starts Modal; schedule a routine in one account's scheduler instead of `docs/routines.json`; copy anything private into the workflow, its logs or the public registry (the no-findings rule, hard rule 1).

## Tests

```bash
python -m unittest tests.test_routines tests.test_routines_workflow -v
```

40 tests in `tests/test_routines.py` and 4 in `tests/test_routines_workflow.py` (3.9 s on 2026-10-17, same machine). They cover the registry guard (the real registry's commands are pinned in `READ_ONLY`, no pull request keep-alive routine, 20 bad entries refused, a missing registry), cadence by UTC date (daily, weekly, the one-hour retry, damaged dates), classification of exit codes and of offline and missing-module output, `execute` (exit code, a missing program, a timeout that stops the grandchild, no credentials in the environment), `run_routines` (all outcomes, the state file, the summary, the lock and a stale lock, the budget, a damaged state file, history of 10), the status views, the command line (`due`, `run --due`, `--name`, `--ci --strict`, exit codes, `--background` finishing in the background, the detached spawn, `kit routines` in `kit/cli.py`), the handoff check with fake files and dates, the SessionStart hook, the rulebook's lines and the ignore rule for `work/routines/`; and the workflow's schedule, permissions, steps and `ci` marks. Fake `python -c` commands stand in for the real routines, so no test needs the network. They do not run the real routines' commands, check what they print, run the workflow on GitHub, or test Windows, where process groups and `_alive` work differently.

## History

- 2026-10-17: this page; the kit command line's docstring names `routines` (`68f0b0f`, [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).
- 2026-10-16: first version: `python -m kit routines` with `list`, `due`, `status`, `run` and `check handoff`, the registry with seven routines, the SessionStart hook and the daily workflow (`5aed6e7`, [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).

## Related

- [prizewatch](prizewatch.md): the `prize-page` routine, the live prize page against the snapshot.
- [prizes](prizes.md): the `prizes` routine and the snapshot both tools read.
- [releases](releases.md): the `releases` routine, `python -m kit releases check`.
- [leaderboard](leaderboard.md): the `leaderboard` routine, `python -m kit leaderboard check`.
- [batch](batch.md): `python -m kit run watch`, the `autopipeline-watch` routine.
- [tooldocs](tooldocs.md): the tool page check, which the whole test suite in the daily workflow runs.
- [cli](cli.md): the `python -m kit` command line that holds `routines`.
- [AI-AGENTS.md](../AI-AGENTS.md#session-start-repository-routines): the rulebook's session-start instruction for every agent.
- [GLOSSARY.md](../../GLOSSARY.md): the glossary entry for routine.
