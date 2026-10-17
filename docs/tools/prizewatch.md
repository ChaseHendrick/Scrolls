# prizewatch: check the live prize page against the dated prize snapshot

`python -m kit.prizewatch` fetches https://scrollprize.org/prizes once and checks that every deadline, amount and eligible volume in kit's dated prize snapshot is on it and no unlisted volume is, so an agent knows when to add a new snapshot.

| Field | Value |
| --- | --- |
| Id | `prizewatch` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Planning and prizes |
| Run | `python -m kit.prizewatch`, `from kit import prizewatch` |
| Code | `kit/prizewatch.py` |
| Tests | `tests/test_prizewatch.py`, `tests/test_routines.py` |
| Needs | Python 3.10 or newer (`requires-python` in `pyproject.toml`), standard library only (urllib, html, re, json, hashlib). The prize snapshot, `kit/data/prizes-2026-10-11.json`, read through `kit.prizes`. HTTPS access to scrollprize.org; urllib uses the proxy in `HTTPS_PROXY` when one is set |
| Runs on | Any machine with network. 0.36 to 0.59 s per call with `--state` and 0.27 to 0.36 s with `--json` (5 runs each), peak resident memory about 23 MB (measured 2026-10-17, 4-core Intel Xeon @ 2.80GHz cloud container, Python 3.13.16, through the container's HTTPS proxy; the page was 55,590 bytes of HTML that day) |
| Network | One HTTPS GET of `https://scrollprize.org/prizes` (`URL`), or of `--url`, with the User-Agent `scrolls-kit-prizewatch` and a 20 s timeout. No other host; it sends nothing but the request |
| Writes | Nothing, unless `--state FILE`: then it rewrites FILE, creating its folders, after every successful fetch, whatever the result. The `prize-page` routine passes `work/routines/prize-page.json`, which is git-ignored |
| Go-ahead | Not needed: one read of a public page; it posts and submits nothing. Adding a new snapshot after it reports a change is an ordinary repository change |
| Released | Not on public `main` yet (checked 2026-10-17): added on branch `claude/project-thread-8zzi1i` (`5aed6e7`, 2026-10-16), in open [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100). Scrolls-private has the same file |
| Checked | 2026-10-17 against commit `1b620c6` |

## What it does

The Vesuvius Challenge's open prizes change: PHerc1447 left First Letters on 24 September 2026 (the rulebook's rule 4), and after the award of 8 October 2026 the page offers First Letters for a maximum of 9 more scrolls instead of 10 ([prizes](prizes.md)). kit keeps a dated copy of the page as JSON, the prize snapshot (`kit/data/prizes-2026-10-11.json`, `prizes.SNAPSHOT`), which `kit prizes`, `kit plan` and `kit run init` read. The rulebook asks every agent to re-check prizes before acting on them and to add a new dated snapshot in `kit/data/` when the page changes (rule 4 of [AI-AGENTS.md](../AI-AGENTS.md)). This tool is the daily backup for that rule: the `prize-page` routine of [routines](routines.md) runs it at session start and in the daily workflow.

It makes one GET of the page, takes the visible text (scripts and styles dropped, tags removed, entities decoded), and picks out three kinds of fact: dollar amounts (`$1,000,000`, `$200k`, `$1 million`), long dates (`June 25th, 2027`, `Sept 1, 2027`) and 14-digit volume ids starting with `20`. Then it checks the snapshot against them: every deadline date, every prize total, per-scroll amount, best monthly amount and tier in the snapshot must appear among the page's amounts and dates; every eligible volume in the snapshot must appear on the page; every volume id on the page must be in the snapshot; and no deadline in the snapshot may have passed. With `--state` it also keeps what the page showed and reports what appeared or disappeared since the last run.

It exits 0 when the two agree (and, with `--state`, nothing changed), 3 when an agent should re-read the page (also when the site answers 4xx, since the page may have moved), and 75 when the page cannot be fetched. It prints what differs, in plain sentences.

It does not edit the snapshot or write a new one; an agent reads the page and does that by hand. It does not know which prize an amount belongs to: the page's amounts form one set, so a snapshot amount is found when any `$` figure on the page has that value. It does not check prose such as "a maximum of 9 more scrolls", the Progress Prizes' yearly total (`total_usd_per_year`, which the page does not show as a figure), or whether a scroll holds text. Eligibility is a dated fact about the prize rules, and the live page wins when the two disagree.

## When to use it

- Before acting on a prize amount, deadline or eligible scroll, to see whether the snapshot still matches the live page (rule 4 of the rulebook).
- When the `prize-page` routine reports attention, to rerun the same check by hand and read the differences.
- After adding a new snapshot in `kit/data/`, to check that it matches the page: `python -m kit.prizewatch --snapshot kit/data/prizes-YYYY-MM-DD.json`.

Do not use it:

- To list the open prizes, their money and days left: use `python -m kit prizes` ([prizes](prizes.md)).
- As the last word before submitting, spending money or telling Chase a scroll is eligible: read https://scrollprize.org/prizes itself. A pass shows only that the figures match.
- To find every bucket volume's prize status: use `python -m kit run catalog` ([batch](batch.md)).
- Offline: it needs the network and exits 75 without it; `python -m kit prizes` works offline.

## Quick start

```bash
python -m kit.prizewatch
python -m kit.prizewatch --json --state STATE.json
```

- `STATE.json`: a JSON file of your choice that keeps what the page showed, so the next run can report changes. The `prize-page` routine uses `work/routines/prize-page.json`.

Run on 2026-10-17 at 01:08 UTC, the first command printed:

```
prize page https://scrollprize.org/prizes against the snapshot of 2026-10-11: 13 amounts, dates 2026-10-31, 2027-06-25, 22 volume ids
  agrees with the snapshot, unchanged since the last check
```

and exited 0. With `--json` it printed:

```
{
  "snapshot_checked": "2026-10-11",
  "page_facts_digest": "fe5daa2fab9d39bb",
  "problems": [],
  "changes": [],
  "amounts": 13,
  "dates": [
    "2026-10-31",
    "2027-06-25"
  ],
  "volumes": 22
}
```

It worked when the exit code is 0 and the last line reads `agrees with the snapshot`. Exit 3 lists each difference and ends with `Re-read the page; ...`: read the page, and add a new dated snapshot if it changed. Exit 75 means the page was not fetched, so nothing was checked.

## Checks and controls

- **The previous snapshot must fail.** The 6 October snapshot offered First Letters for a maximum of 10 scrolls ($500,000) and listed PHerc0343's volume. On 2026-10-17, `python -m kit.prizewatch --snapshot kit/data/prizes-2026-10-06.json` exited 3 with `first-letters-2027: the snapshot's amount 500,000 USD is not on the page` and `first-letters-2027: the snapshot's volume 20250521140437 is not on the page`, while the current snapshot exited 0 against the same page. Run it to see that the check can still fail.
- **A passed deadline must fail.** `python -m kit.prizewatch --today 2026-11-02` exited 3 on 2026-10-17 with `progress-prizes: the snapshot's deadline 2026-10-31 has passed; the page should name the next one`.
- **A change report must fire.** With a state file edited so that `2140000` was missing and `1234` was added, the next run printed `new on the page since the last check: amounts 2140000` and `gone from the page since the last check: amounts 1234` and exited 3; the run after it exited 0.
- **The tests** check a synthetic page: amounts, dates and volumes picked out, scripts and styles ignored, short month names, a changed deadline, amount and volume each reported, a deadline passing at 00:00 Pacific on 1 November and not at 23:00 on 31 October, change reports through the state file, and exit codes 0, 3, 75 and 2.
- **What a pass does not show.** That the amounts belong to the right prizes (they are matched as a set), that the page's prose (such as the maximum number of scrolls) is unchanged, or that the page is the same an hour later. An HTTP error from the site, such as a 404 if the page moved, is reported as offline (exit 75), which the `prize-page` routine records as skipped, not as a failure.

Claim label: Sourced fact, for the amounts, dates and volume ids found on https://scrollprize.org/prizes at the time of the run and their comparison with the snapshot; whether a difference matters is for an agent to judge by reading the page.

## Commands and options

### `python -m kit.prizewatch`

```
usage: python -m kit.prizewatch [-h] [--url URL] [--snapshot SNAPSHOT]
                                [--state STATE] [--timeout TIMEOUT]
                                [--today TODAY] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--url URL` | `https://scrollprize.org/prizes` (`URL`) | The page to fetch |
| `--snapshot SNAPSHOT` | `kit/data/prizes-2026-10-11.json` (`prizes.SNAPSHOT`, an absolute path) | The snapshot to compare with, read with `prizes.load` |
| `--state STATE` | none | A JSON file that keeps the page's facts from the last run. The facts are compared with it and then written to it after every successful fetch. Without it nothing is written and no changes are reported |
| `--timeout TIMEOUT` | `20` | Seconds to wait for the page |
| `--today TODAY` | none (the current time, UTC) | Run as at 12:00 UTC on this day, written `YYYY-MM-DD`: it decides which deadlines have passed and the `checked` stamp in the state file. It is read before the fetch; a malformed date stops with exit 2 |
| `--json` | off | Print the report as JSON (fields under Outputs) instead of the text. The offline line stays plain text |

## Python API

```python
from kit import prizes, prizewatch
code, report = prizewatch.check(prizewatch.fetch(), prizes.load())
print(code, report["problems"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `page_text(raw)` | str: the page's visible text | Nothing | Drops `<script>` and `<style>` blocks, removes tags, decodes entities, turns zero-width spaces into spaces and folds whitespace |
| `facts(raw)` | dict `{"amounts": [int], "dates": [str], "volumes": [str]}`, each sorted and without repeats | Nothing | Amounts in USD (`AMOUNT`; `k`, `K`, `M` and `million` scale them) and dates as `YYYY-MM-DD` (`DATE`) from `page_text(raw)`; volume ids (`VOLUME`) from the raw HTML |
| `snapshot_expectations(snapshot)` | list of `(prize id, kind, value)`, kind `date`, `amount` or `volume` | `KeyError` without `prizes` or a prize's `id`; `ValueError` for a malformed `deadline` | Per prize: the deadline's date in its own time zone, `total_usd`, `per_scroll_usd`, `monthly_best_usd` (`AMOUNT_FIELDS`), each `tiers_usd` value, each `typical_tiers_usd` value, and each 14-digit eligible volume |
| `compare(snapshot, seen, now)` | list of str: the problems | As `snapshot_expectations` | `now` is an aware `datetime`; message forms under Outputs |
| `changes(old, new)` | list of str: what appeared or disappeared between two `facts` dicts | Nothing | |
| `fetch(url=URL, timeout=20, opener=None)` | str: the page, decoded as UTF-8 with replacement | `urllib.error.URLError` (including `HTTPError`), `OSError`, `ValueError` for a bad URL | `opener` defaults to `urllib.request.urlopen` |
| `check(raw, snapshot, now=None, state_path=None)` | `(exit code, report dict)`: 3 when there is a problem or a change, else 0 | As `compare`; `OSError` when the state file cannot be written | Reads and then rewrites the state file when `state_path` is given; a missing or broken state file counts as no previous run |
| `main(argv=None)` | int: the exit code | `SystemExit` with code 2 on a usage error; `ValueError` for a malformed `--today` | The command line |

Module constants: `URL` (`https://scrollprize.org/prizes`), `EXIT_ATTENTION` (3), `EXIT_OFFLINE` (75), `MONTHS`, the patterns `DATE`, `AMOUNT` and `VOLUME` (`(?<!\d)(20\d{12})(?!\d)`), and `AMOUNT_FIELDS`.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| The page | HTML from `--url`, decoded as UTF-8 | On 2026-10-17: 55,590 bytes of HTML, 27,079 characters of visible text |
| The snapshot | JSON, `kit/data/prizes-2026-10-11.json` or `--snapshot` | Fields read: `checked`, and per entry of `prizes`: `id`, `deadline` (ISO 8601 with offset), `total_usd`, `per_scroll_usd`, `monthly_best_usd`, `tiers_usd` (object), `typical_tiers_usd` (list) and `eligible[].volume`. The current snapshot gives 54 expectations: 4 deadlines (2 distinct dates), 16 amounts (11 distinct values) and 34 eligible volumes (22 distinct ids). Its fields are described on the [prizes](prizes.md) page |
| The state file | JSON from a previous run, `--state` | `{"checked": ..., "facts": {...}}`; anything else counts as no previous run |
| `--today` | `YYYY-MM-DD` | Optional |

## Outputs

The text report is a first line, `prize page URL against the snapshot of DATE: N amounts, dates DATES, N volume ids`, then each problem and each change on its own indented line, then either `Re-read the page; if it changed, add a new dated snapshot in kit/data (docs/AI-AGENTS.md rule 4) and update any prize notes the repository's AGENTS.md names. The live page wins.` or `  agrees with the snapshot`, followed by `, unchanged since the last check` when `--state` was given (also on a first run, when there was no last check).

The problem and change lines:

| Line | Meaning |
| --- | --- |
| `PRIZE_ID: the snapshot's date YYYY-MM-DD is not on the page` | The deadline moved, or the page writes it in another form |
| `PRIZE_ID: the snapshot's amount N USD is not on the page` | A total, per-scroll amount or tier changed, such as `500,000 USD` for the 6 October First Letters total |
| `PRIZE_ID: the snapshot's volume ID is not on the page` | An eligible volume left the page |
| `the page names volume ID, which the snapshot does not list (newly eligible?)` | A 14-digit id on the page that no snapshot prize lists |
| `PRIZE_ID: the snapshot's deadline YYYY-MM-DD has passed; the page should name the next one` | The snapshot is older than that deadline |
| `new on the page since the last check: KIND VALUES` | With `--state`: amounts, dates or volumes that the last run did not see |
| `gone from the page since the last check: KIND VALUES` | With `--state`: ones that the last run saw and this one did not |

With `--json`, the report:

| Field | Type | Meaning |
| --- | --- | --- |
| `snapshot_checked` | str or null | The snapshot's `checked` date |
| `page_facts_digest` | str | The first 16 hex digits of the SHA-256 of the page's facts as JSON with sorted keys; equal digests mean the same amounts, dates and volumes |
| `problems` | list of str | The problem lines above |
| `changes` | list of str | The change lines above; empty without `--state` |
| `amounts` | int | How many distinct dollar amounts the page shows |
| `dates` | list of str | The long dates on the page, `YYYY-MM-DD` |
| `volumes` | int | How many distinct volume ids the page shows |

The state file is `{"checked": "YYYY-MM-DDTHH:MM:SSZ", "facts": {"amounts": [...], "dates": [...], "volumes": [...]}}`, written with a 2-space indent.

| Exit code | Meaning |
| --- | --- |
| `0` | The page and the snapshot agree, and with `--state` nothing changed since the last run |
| `1` | A Python error with a traceback, such as a state file that cannot be written |
| `2` | A usage error, a snapshot that cannot be read, is not JSON or has no `prizes`, or a malformed `--today` |
| `3` | Something to look at: at least one problem or change line, or a 4xx answer from the site |
| `75` | The page could not be fetched: offline, a timeout, a bad URL, or a 5xx server error |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `prizewatch: cannot read the snapshot /nonexistent.json: [Errno 2] No such file or directory: '/nonexistent.json'` on stderr, exit 2 | The `--snapshot` file is not there, or a copy of `kit/` without `data/` | Give a real snapshot, or run from a clone |
| `prizewatch: cannot read the snapshot PATH: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)`, or another JSON message, exit 2 | The snapshot is not valid JSON | Fix or restore the file |
| `prizewatch: offline, https://scrollprize.org/prizes could not be fetched: <urlopen error timed out>`, exit 75 | No answer within `--timeout` | Run again later, or raise `--timeout` |
| `prizewatch: offline, URL could not be fetched: <urlopen error [Errno 111] Connection refused>`, or `<urlopen error Tunnel connection failed: 502 Bad Gateway>` from a proxy, exit 75 | No network, or the host cannot be reached | Run it where the network works |
| `prizewatch: https://scrollprize.org/no-such-page-xyz answered HTTP Error 404: Not Found; the prize page may have moved, so re-read https://scrollprize.org and fix --url or kit/prizewatch.py URL`, exit 3 | The site answered with a 4xx error | Open the URL in a browser: if the page moved, set the new address in `URL` (and the routine's command, if it gives `--url`) |
| `prizewatch: offline, URL could not be fetched: HTTP Error 503: Service Unavailable`, exit 75 | The site answered with a 5xx error | Run again later |
| `prizewatch: offline, not-a-url could not be fetched: unknown url type: 'not-a-url'`, exit 75 | `--url` is not a URL | Give a full `https://` URL |
| `prizewatch: --today is not YYYY-MM-DD: Invalid isoformat string: '17-10-2026'` on stderr, exit 2 | `--today` not written `YYYY-MM-DD` | Write the date as `2026-10-17` |
| `prizewatch: cannot read the snapshot PATH: 'prizes'` on stderr, exit 2 | The snapshot file has no `prizes` list | Use a prize snapshot from `kit/data/` |
| Any problem line under Outputs, exit 3 | The page and the snapshot differ, or a deadline has passed | Read https://scrollprize.org/prizes; if it changed, add a new dated snapshot in `kit/data/` (the steps on the [prizes](prizes.md) page) and update the prize notes `AGENTS.md` names |
| A change line, exit 3, and exit 0 on the next run | With `--state`, a change is reported once, then the state file holds the new facts | Act on it the first time; the routine's `status` keeps the run's output until its next run |

## How it works

1. `prizes.load` reads the snapshot; a read or JSON error ends with exit 2.
2. `fetch` makes one GET of `--url` with the User-Agent `scrolls-kit-prizewatch` and `--timeout` seconds; a 4xx `HTTPError` ends with exit 3 and the `may have moved` line; any other `URLError`, `OSError` or `ValueError` (a 5xx included) ends with exit 75 and the `offline` line.
3. `facts` reduces the page to three sets. Amounts: `AMOUNT` finds `$` followed by digits with comma groups or plain digits, an optional decimal part and an optional `million`, `M`, `k` or `K`, and rounds the value to whole dollars. Dates: `DATE` finds a month name or abbreviation (such as `Sept`), a day with an optional `st`, `nd`, `rd` or `th`, an optional comma and a year from 2000 to 2099. Both read the visible text from `page_text`. Volumes: `VOLUME` finds 14-digit numbers starting with `20` in the raw HTML. On 2026-10-17 the raw HTML and the visible text held the same 22 ids.
4. `snapshot_expectations` lists what the snapshot says the page shows, and `compare` reports each expectation not found, each page volume not listed, and each deadline earlier than `now`. A deadline counts as passed from its own time, such as 23:59 Pacific.
5. `check` compares the facts with the state file's facts when `--state` is given, writes the new facts there, and computes `page_facts_digest`. The exit code is 3 when there is any problem or change, else 0.

The comparison follows the rulebook's rule 4 (re-check prizes, add a new dated snapshot rather than edit the old one) and the snapshot steps in [TESTING.md](../TESTING.md).

## Cost and time

Measured 2026-10-17 in a 4-core Intel Xeon @ 2.80GHz cloud container (16 GB memory), Python 3.13.16, through the container's HTTPS proxy: 0.36 to 0.59 s per call with `--state` and 0.27 to 0.36 s with `--json` (5 runs each), peak resident memory about 23 MB; as the `prize-page` routine it took 0.6 to 1.0 s on three runs the same day. Most of it is the one fetch of a 55,590-byte page. It rents nothing and runs anywhere with network; in the daily workflow it runs on GitHub's free runners for public repositories.

## For agents

- **Command:** `python -m kit.prizewatch --json` (machine-readable); add `--state work/routines/prize-page.json` to get change reports as the routine does.
- **Parse:** `problems` and `changes` (lists of sentences; both empty on a pass), `snapshot_checked` (the snapshot's date), `dates`, `amounts` and `volumes` (counts), and `page_facts_digest`. On exit 75 the output is one plain-text line starting `prizewatch: offline`, not JSON.
- **Rerun:** Safe. Without `--state` it writes nothing. With `--state` it rewrites that file after every successful fetch, so a change is reported only by the first run that sees it.
- **Success:** Exit 0 and empty `problems` and `changes` (text: `agrees with the snapshot`).
- **Not a pass:** Exit 75, which checked nothing, even when a routine records it as skipped; a pass from another day; a pass read as proof that the prose or the money split per prize is unchanged; a snapshot passed with `--snapshot` that is not the one kit uses.
- **Go-ahead:** Nothing for running it. Submitting to a prize needs Chase's yes (the go-ahead rule, hard rule 8).
- **Never:** Edit an old snapshot to make the check pass (add a new dated one, rule 4); treat eligibility as a sign that a scroll holds text; publish or describe a possible finding on an eligible scroll (the no-findings rule, hard rule 1).

## Tests

```bash
python -m unittest tests.test_prizewatch -v
python -m unittest tests.test_routines.RegistryTest -v
```

`tests/test_prizewatch.py` has 14 tests (0.01 s on 2026-10-17, same machine). They run on a synthetic page and snapshot with no network: facts picked out (amounts, dates, volumes; scripts and styles ignored; short month names), comparison (an agreeing page; a changed deadline, amount and volume; a deadline passing at 00:00 Pacific; change reports through a state file; every prize of the real snapshot gives a date expectation), and the command line (exit 0 and `agrees with the snapshot`, exit 3, exit 75 on a `URLError` or a 503, exit 3 on a 404, exit 2 on a missing snapshot, a snapshot without `prizes` or a malformed `--today`). `RegistryTest` in `tests/test_routines.py` pins the routine's command, `kit.prizewatch --state work/routines/prize-page.json`. They do not fetch the live page, test a broken state file, or check that the real page still has the shape the patterns expect.

## History

- 2026-10-17: this page; a 4xx answer from the site is exit 3 (the page may have moved) instead of offline, and a malformed `--today` or a snapshot without `prizes` is exit 2 instead of a traceback ([PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).
- 2026-10-16: first version, with the `prize-page` routine that runs it daily (`5aed6e7`, [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).

## Related

- [prizes](prizes.md): the snapshot this tool checks, and how to add a new one.
- [routines](routines.md): the `prize-page` routine, at session start and in the daily workflow.
- [batch](batch.md): `python -m kit run catalog`, which reads the live page for each bucket volume's prize.
- [prizes.md](../prizes.md): the prize terms in prose.
- [AI-AGENTS.md](../AI-AGENTS.md): rule 4, re-check prizes before acting on them.
