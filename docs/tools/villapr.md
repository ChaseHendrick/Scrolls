# villapr: villa PR deadlines and a template check before you post

`python -m kit prclock USER` shows how many days each of a person's open PRs on ScrollPrize/villa has before villa's time-limit workflow closes it; `python -m kit prtext BODY.md` checks a PR or issue body against villa's templates and CONTRIBUTING before it is posted.

| Field | Value |
| --- | --- |
| Id | `villapr` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Releases and repository |
| Run | `python -m kit prclock`, `python -m kit prtext`, `from kit import villapr` |
| Code | `kit/villapr.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_qol_tools.py` |
| Needs | Python 3.10 or newer, standard library only (`zoneinfo` for the Pacific time zone; a fixed UTC-7 is used where the time zone database is missing) |
| Runs on | Any machine. `prtext` reads one local file in well under a second; `prclock` makes one GitHub search request per 100 PRs |
| Network | `prclock` only: `api.github.com/search/issues`, anonymous (60 requests an hour) or with `GITHUB_TOKEN`. `prtext`: none |
| Writes | Nothing |
| Go-ahead | Not needed: both only read. Posting the checked text to villa still needs its author's own go-ahead |
| Released | Public `main` from the change that adds it (23 Oct 2026) |
| Checked | 2026-10-23 against commit `3376687` |

## What it does

**prclock.** villa's workflow `.github/workflows/pr-time-limits.yml` (main 6f2024569, read 23 Oct 2026) runs every day at 00:00 America/Los_Angeles and closes an open PR that has had no activity for 14 days (GitHub's `updatedAt`) or has been open for 28 days (`createdAt`), unless it carries the label `keep-open`. Contributors with several PRs lose track. `prclock` lists a person's open villa PRs with the date of the run that would close each, the rule that would do it, and the days left, soonest first, and marks those within `--soon` days. It never comments, bumps or relabels.

**prtext.** villa's PR template asks for **In one sentence**, **One real example**, **Before**, **After this PR**, **Proof** and **Why / where this is useful**, and a ticked "I personally verified" box; the issue template has its own fields and box; CONTRIBUTING asks for pictures or video on real scroll data, a motivation, and human-written commentary, and maintainers close PRs that read as machine-written. `prtext` lists what is missing: an empty field or a template placeholder, leftover `<!-- -->` comments, an unticked box, no picture, no motivation, a vague title, a toy example, and long dashes (U+2014, U+2013). It cannot judge whether the commentary is the person's own, and says so on every run.

Neither is a villa tool, and passing `prtext` does not mean a maintainer will merge.

## When to use it

- `prclock`: weekly, or before a holiday, to see which PRs need a real update.
- `prtext`: on every PR or issue body before posting to villa.

Do not use it:

- To keep a PR alive with an empty bump: villa's rule is about activity, but an update with nothing in it wastes maintainers' time.
- For another repository's time limits: `--repo` changes where it searches, not the rule.

## Quick start

```bash
python -m kit prclock YOUR_GITHUB_LOGIN
python -m kit prtext pr-body.md --title "Your planned title"
```

For two example PRs on 23 Oct 2026 at 23:00 UTC (one ready, last updated 22:47 that day; one draft, last updated 12 Oct), `prclock`'s text is:

```
someone: 2 open PRs on ScrollPrize/villa, soonest close first (rule: https://github.com/ScrollPrize/villa/blob/main/.github/workflows/pr-time-limits.yml)
  #2060     3.3 days (14 days without activity, 2026-10-27)  draft  Example older draft
  #2269    14.4 days (14 days without activity, 2026-11-07)  ready  Example ready PR
Activity restarts the 14-day clock (a real update, not an empty bump); the 28-day limit does not move.
```

(The cloud container these pages were written in cannot reach `api.github.com`; this output is from `format_clock` on those two fixed PRs, and the live command was not run here.) On a body that still had the template's placeholder, an unticked box and no pictures, with the title "Fix crash", `prtext` printed `9 to fix`, one `fix` line per problem (for example `fix   no image or video: villa asks for before/after pictures or a video on real scroll data`) and two `note` lines, and exited 1. It worked when `prtext` prints `ready to post` and exits 0.

## Checks and controls

- **The clock follows the workflow's own rule.** The tests check that the 14-day rule closes at the first Pacific midnight on or after 14 days of quiet, that the 28-day rule wins when it is sooner, and that `keep-open` exempts a PR.
- **prtext passes a good body and fails a bad one.** The tests run a filled-in body (ready) and a copy with the box unticked, a long dash and a vague title, which fails with exactly those problems named; an issue body missing its fields fails too.

Claim label: Sourced fact for the rule (quoted from villa's workflow on the date above); Interpretation for prtext's reminders.

## Commands and options

### `python -m kit prclock`

```
usage: python -m kit prclock [-h] [--repo REPO] [--soon SOON] [--json] user
```

| Option | Default | Meaning |
| --- | --- | --- |
| `user` | required | GitHub login, for example ChaseHendrick |
| `--repo REPO` | `ScrollPrize/villa` | owner/name (the rule is villa's; other repos differ) |
| `--soon SOON` | `3` | mark PRs closing within this many days |
| `--json` | off | print the PRs as JSON |

| Variable | Default | Meaning |
| --- | --- | --- |
| `GITHUB_TOKEN` | unset | Sent as a bearer token for a higher search limit; never printed |

### `python -m kit prtext`

```
usage: python -m kit prtext [-h] [--issue] [--title TITLE] [--json] file
```

| Option | Default | Meaning |
| --- | --- | --- |
| `file` | required | the PR or issue body, as Markdown (- reads standard input) |
| `--issue` | off | check against the issue template instead |
| `--title TITLE` | none | the title you plan to use |
| `--json` | off | print the problems and reminders as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `next_run(at, tz=None)` | datetime (UTC) | Nothing | The first 00:00 America/Los_Angeles at or after `at` |
| `clock(pr, now=None, tz=None)` | dict: `number`, `title`, `url`, `draft`, `created_at`, `updated_at`, `keep_open`, `closes_at`, `reason`, `days_left`, `age_limit_at` | `KeyError` without `created_at` or `updated_at` | One GitHub search item |
| `search(user, repo=REPO, token=None, opener=urllib.request.urlopen)` | list of search items | `VerifyError` for a bad login; `OSError`, `ValueError` | All pages, 100 per page |
| `prclock(user, repo=REPO, now=None, token=None, opener=...)` | {"user", "repo", "rule", "prs"} soonest first | As `search` | |
| `format_clock(r, soon=3)` | the printed text | Nothing | |
| `prtext(body, kind="pr", title=None)` | {"kind", "problems", "reminders", "ok"} | Nothing | `kind` is `pr` or `issue` |
| `format_text(r, path)` | the printed text | Nothing | |
| `build_parser(p, action)` | the parser | Nothing | `action` is `prclock` or `prtext` |
| `cmd_prclock(args)`, `cmd_prtext(args)` | exit code | Nothing | |

Constants: `REPO`, `IDLE_DAYS` (14), `AGE_DAYS` (28), `EXEMPT_LABEL` (`keep-open`), `RUN_TZ`, `WORKFLOW`, `PR_FIELDS`, `ISSUE_FIELDS`.

## Inputs

`prclock`: a GitHub login. `prtext`: a Markdown file in villa's template layout (`**Field:**` lines and `- [x]` boxes), or standard input.

## Outputs

`prclock --json`: `user`, `repo`, `rule`, and `prs` (fields as `clock`). `prtext --json`: `kind`, `problems`, `reminders`, `ok`.

| Exit code | Meaning |
| --- | --- |
| `0` | `prclock`: listed, none within `--soon`; `prtext`: nothing to fix |
| `1` | `prtext`: something to fix |
| `2` | A bad login, GitHub unreachable, an unreadable file, or a usage error |
| `3` | `prclock`: a PR closes within `--soon` days |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit prclock: not a GitHub login: 'X'` | Characters a login cannot have | Use the login as on github.com |
| `kit prclock could not read the GitHub search API: HTTP Error 403: Forbidden` | The anonymous rate limit (60 an hour), or a network that blocks `api.github.com` | Wait an hour, set `GITHUB_TOKEN`, or run it on another network |
| `kit prclock could not read the GitHub search API: ...` with another error | No network or a timeout | Check the network |
| `kit prtext could not read the file: ERROR` | The file does not exist or is not readable | Check the path |
| `USER has no open PRs on REPO` | The search found none | Check the login and `--repo` |

## How it works

1. `prclock` searches `repo:REPO is:pr is:open author:USER`, then for each PR computes the first daily run after `updated_at` + 14 days and after `created_at` + 28 days, in Pacific time, and keeps the sooner.
2. `prtext` finds each `**Field:**` up to the next field, heading or checkbox, strips template comments, and applies the checks listed under What it does; picture detection looks for Markdown images, `<img>`, `<video>`, GitHub attachment links and image or video file names.

## Cost and time

Free. One HTTPS request per 100 PRs, or none for `prtext`.

## For agents

- **Command:** `python -m kit prclock LOGIN --json`; `python -m kit prtext BODY.md --title "TITLE" --json`.
- **Parse:** `prs[].days_left`, `prs[].reason`; `ok`, `problems`.
- **Rerun:** Safe; read-only.
- **Success:** exit 0 (or 3 from `prclock`, which is a result).
- **Not a pass:** `prtext` `ok` does not make machine-written commentary acceptable to villa; its last reminder always says so.
- **Go-ahead:** Nothing to run. Posting to villa needs the PR author's own go-ahead on the exact text.
- **Never:** post an empty bump to restart the clock.

## Tests

`python -m unittest tests.test_qol_tools.TestVillaPr -v`: the 14-day rule and the Pacific midnight, the 28-day rule winning when sooner, `keep-open`, the search paging and login check with a fake opener, and `prtext` on a filled body (ready), on a copy with the box unticked, a long dash and a vague title (each named), and on an issue body missing its fields. The other checks (placeholder, comment, no picture, no motivation) were run by hand on the body in Quick start. No network.

## History

- 2026-10-23: added `prclock` and `prtext` (`3376687`).

## Related

- [AI-AGENTS.md, public writing for villa](../AI-AGENTS.md#public-writing-for-villa-and-the-community): our own rules for villa text.
