# vesuvius-radar: new papers, code, models and data for the Herculaneum scrolls, scored and searchable

A Hugging Face Space that collects new papers, repositories, models, datasets, package versions and posts from public sources around the clock, scores each for relevance to reading the Herculaneum scrolls, and serves them as a page, a JSON API, CSV, RSS and an MCP server.

| Field | Value |
| --- | --- |
| Id | `vesuvius-radar` |
| Status | Current |
| Kind | app |
| Area | Viewers and apps |
| Run | [huggingface.co/spaces/SharpMeow/vesuvius-radar](https://huggingface.co/spaces/SharpMeow/vesuvius-radar) (page); `https://sharpmeow-vesuvius-radar.hf.space/api/items?since=1d` (JSON); `/mcp` (MCP, Streamable HTTP); locally `uvicorn app:app --port 7860` in `spaces/vesuvius-radar`; `python scanner.py --days 3 --out scan.json` (one scan, no server); in the page, `window.vesuviusRadar` |
| Code | `spaces/vesuvius-radar/app.py`, `spaces/vesuvius-radar/scanner.py`, `spaces/vesuvius-radar/radar_mcp.py`, `spaces/vesuvius-radar/radar.json`, `spaces/vesuvius-radar/index.html`, `spaces/vesuvius-radar/static/app.js`, `spaces/vesuvius-radar/static/style.css`, `spaces/vesuvius-radar/connect.json` |
| Tests | `tests/test_vesuvius_radar.py` (scoring, lookbacks, views, filters, API, CSV, RSS, MCP, the vector cache, and that no key or private material is in the Space's files); `python -m kit spaceconnect check` checks its Connect panel |
| Needs | A browser, or any HTTP client. To run it yourself: Python 3.10+, `fastapi` 0.115.6, `uvicorn` 0.34.0, `fastembed` 0.9.1 and `numpy` (`requirements.txt`); the model BAAI/bge-small-en-v1.5 (MIT, about 130 MB) downloads on first use |
| Runs on | A free Hugging Face CPU Space (2 vCPU, 16 GB); no GPU and no GPU quota. The page and API answer at once; see Cost and time for the collector |
| Network | `rss.arxiv.org`, `arxiv.org`, `export.arxiv.org` (papers), `api.github.com` (repositories, ScrollPrize/villa), `huggingface.co` (models, datasets, Spaces, daily papers, the embedding model), `pypi.org`, `zenodo.org`, `api.crossref.org`, `scrollprize.substack.com` (the Challenge blog); all read logged out |
| Writes | In the Space: `/data/radar` with persistent storage, else `/tmp/radar` (`store.json`, `vectors.npz`); `RADAR_DATA` moves it. `scanner.py --out` writes the file you name |
| Go-ahead | Not needed to use. Making the Space public was Chase's yes (29 Oct 2026); later redeploys from merged `main` fall under the standing yes (rule 8) |
| Released | Public on Hugging Face since 2026-10-29; README "Released tools" entry `vesuvius-radar` |
| License | Code Apache 2.0; item titles, summaries and links belong to their sources |
| Checked | 2026-10-30 against commit `b803ece` |

## What it does

Work that could help read the scrolls appears in many places: arXiv, GitHub, Hugging Face, PyPI, Zenodo, journals and the Challenge's own blog. Most of it never says "Herculaneum". The radar reads all of those sources on a schedule, keeps 30 days of items, and scores each from 0 to 100 so the few relevant ones rise to the top.

Each item gets two scores. The keyword score adds points for scroll terms (Vesuvius, Herculaneum, PHerc, papyrus, Volume Cartographer and similar) and for terms in eight topics (sheets and surfaces, ink and imaging, fibers and tracing, compression and storage, registration, 3D encoders, text and reading, speed and scale), and every item shows which terms gave which points. The meaning score comes from a small sentence-embedding model run on the Space's CPU, which compares the item with sentences that describe the work the scrolls need; it catches items that use none of the keywords. A small learned model sets the final score: a ridge regression on the item's embedding plus its keyword and meaning scores, source, kind and popularity, fitted to blind ratings of what 588 collected items are worth to scroll work and calibrated so each band holds about as many items as the ratings put there. Which items are kept is still decided by keywords and meaning (the higher of the keyword score and a blend of both).

The page shows the window you pick (1 minute to 30 days, default 1 day), by publish or update time or by when the radar first found the item, with charts (items over time by source, topics, the score histogram, sources, a topic by source grid and the top contributors, ranked by distinct pieces of work so many small related items count as one), a briefing of the strongest items per topic, and three reader views: researchers, the Challenge team, and contributors. The list opens on the newest items, 10 per page (10, 20, 50 or 100), with sources, topics, relevance and browser-only toggles in four dropdowns and the active filters shown as removable pills. Stars, hides and the last visit stay in your own browser.

A villa issue or pull request often comes back on the radar because someone commented on it, reviewed it or closed it, long after it was opened. Its card then says who made that latest update and what it said ("Comment by X, 50 min ago" with the comment's words and a link to it), and names the original author separately as "opened by". "Why this score" opens the score's breakdown and "More like this" opens the closest items in meaning; each button opens and closes its own panel.

A score is a triage aid. It says an item may be worth reading, not that it is useful or correct.

## When to use it

- Keeping up with new methods (segmentation, ink detection, fiber tracing, compression, 3D encoders) without reading every arXiv list.
- Seeing what the community shipped this week: villa pull requests, issues and releases, new repositories and Hugging Face uploads.
- Feeding an agent or a script: the MCP server and the JSON API take the same filters as the page.

Do not use it:

- As a literature review: it holds 30 days and reads titles, abstracts and descriptions only.
- For Discord or social media: it reads none of them.
- To judge a method: read the paper and its results.

## Quick start

```bash
curl -s "https://sharpmeow-vesuvius-radar.hf.space/api/items?since=7d&view=research&min_score=35&limit=5&compact=true"
```

It returns JSON with `matched` (items in the window that pass the filters), `items` (each with `score`, `band`, `title`, `url`, `source`, `topics`) and `window`. It worked when `matched` is a number and every item's `score` is at least 35.

From an agent, add the MCP server `https://sharpmeow-vesuvius-radar.hf.space/mcp` (Streamable HTTP, no key) and call `search_items` with `{"since": "7d", "view": "research"}`.

## Checks and controls

- Meaning score calibration (29 Oct 2026, Model output): on items the keyword score had labeled, the meaning score with the bge query prefix separated relevant from unrelated items with AUC 0.873, against 0.811 without the prefix. On 39 arXiv abstracts (4 on scroll imaging, 35 recent cs.CV), the score from the first 600 characters correlated 0.93 with the score from 1,500 characters at the same AUC (0.957), at about three times the speed, so the Space reads 600.
- Learned head (29 Oct 2026, Model output): two language-model raters scored all 588 items of a 30-day window from 0 to 100 for value to scroll work, without seeing the radar's score, and agreed at Spearman 0.95 (both are the same model family, so this is an upper bound on reliability). Against their mean, the keyword score alone ranked items at 0.73 and the old final score (keyword and meaning) at 0.70. The learned head reached 0.86 in nested 5-fold cross-validation (5 repeats; calibration fitted inside each training fold), 0.84 without the embedding. Its high band held 61 items with precision 0.60 and recall 0.55 against the ratings' 66 high items; the old score put 124 items in high at precision 0.39. The biggest corrections: ScrollPrize/villa pull requests and the Challenge blog rose (a merged object-store PR from 30 to 81, a prize announcement from 50 to 94), and empty repositories named after the Challenge and off-topic archaeology preprints fell. `train_head.py` refits it from a ratings file and prints the same figures; `head.json` stores them.
- Without the learned head, meaning alone cannot reach the high band: a test feeds a perfect meaning score to an item with no keywords and requires medium.
- Every check of the collector reports its state per source (ok, partial or error) with its notes, on the Sources tab and at `/api/sources`; a rate limit or an error shows as partial, never as an empty ok.
- `tests/test_vesuvius_radar.py` fails if any file in the Space names a token variable, an authorization header, Discord, or a long dash, or if `scanner.py` reads a host outside the public list above.

Claim label: Model output (relevance scores, topics by meaning and similar items). Item titles, summaries, dates and links are Sourced facts from each source, read on the date shown.

## Commands and options

### The Space

[huggingface.co/spaces/SharpMeow/vesuvius-radar](https://huggingface.co/spaces/SharpMeow/vesuvius-radar): Radar (KPIs, charts, filters and the list, newest first, in pages of 10, 20, 50 or 100; each item opens "Why this score" and "More like this"), Briefing, Sources (each source's last and next check, with Check now), API and MCP (the Connect your tool panel), How it works. Themes: Auto, Light, Dark and Vesuvius. URL parameters mirror the API filters (`since`, `by`, `view`, `q`, `sources`, `topics`, `bands`, `min`, plus `sort` and `per` for the page), so a filtered page can be shared as a link.

### HTTP API

| Endpoint | Returns |
| --- | --- |
| `GET /api/items` | Items in the window, filtered; `sort` score, date or popularity; `limit` up to 500; `offset`; `compact` |
| `GET /api/item?id=ID` | One item with its score breakdown and the closest items in meaning |
| `GET /api/counts` | How many items each standard lookback holds, for the same filters |
| `GET /api/overview` | The counts behind the charts |
| `GET /api/briefing` | The strongest items per topic (`per_topic`, default 3; score 35 or more unless `min_score` is set) |
| `GET /api/sources` | Each source's state, last and next check, notes and recent runs |
| `POST /api/check` | Check every source now: 200, or 409 while a check runs, or 429 with `retry_after` within 300 s of the last |
| `GET /api/views`, `/api/config` | The reader views' rules; sources, keywords, weights and anchor sentences |
| `GET /api/export.csv`, `/feed.xml` | The window as CSV, or as RSS (default 7 days, score 60 or more) |
| `POST /mcp` | MCP over Streamable HTTP: `search_items`, `get_item`, `find_similar`, `briefing`, `overview`, `source_status`, `check_now`, `list_views`, `get_settings` |

| Filter | Default | Meaning |
| --- | --- | --- |
| `since` | `1d` | Lookback: a number with m, h, d or w (1m to 30d; longer is cut to 30 days), or an ISO time |
| `by` | `date` | `date` (published or last updated) or `found` (first seen by the radar) |
| `view` | `all` | `all`, `research`, `team` or `builders` |
| `q` | empty | Words that must all appear (title, summary, people, topics); with `by_meaning=true`, a phrase ranked by meaning |
| `sources`, `kinds`, `topics`, `bands`, `ids` | empty | Comma lists |
| `min_score` | `0` | 0 to 100 |
| `has_code` | `false` | Only items that link code |

### `python scanner.py`

```
usage: scanner.py [-h] [--days DAYS] [--sources SOURCES] [--semantic] [--out OUT]
```

One check of the sources you name, without the server, run in `spaces/vesuvius-radar`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--days` | `1` | Read items from this many days back |
| `--sources` | every source | Comma list of arxiv, github, hf, pypi, zenodo, journals, blog |
| `--semantic` | off | Load the embedding model and add meaning scores |
| `--out` | `-` | `-` prints; otherwise write the items and each source's status as JSON to this file |

### `python train_head.py`

```
usage: train_head.py [-h] --items ITEMS --ratings RATINGS [--out OUT] [--models MODELS] [--calibration {quantile,isotonic}]
```

Refits `head.json` from collected items (as `/api/items` returns them) and a ratings file (item id to one or more raters' `{"value": 0..100}`). Needs scikit-learn, scipy and fastembed; the Space only needs numpy to apply the result. Prints the nested cross-validation figures it stores.

| Option | Default | Meaning |
| --- | --- | --- |
| `--items` | required | JSON list of items |
| `--ratings` | required | JSON object: item id to rating, or to several raters' ratings (averaged) |
| `--out` | `head.json` beside the script | Where to write the head |
| `--models` | the fastembed cache | Where the embedding model is kept |
| `--calibration` | `quantile` | `quantile`: bands hold as many items as the ratings put there; `isotonic`: scores are the expected rating (fewer, surer high items) |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `RADAR_COLLECT` | `1` | `0` turns the background collector off (the tests use it) |
| `RADAR_SEMANTIC` | `1` | `0` skips the embedding model: keyword scores only |
| `RADAR_DATA` | `/data/radar` if `/data` is writable, else `/tmp/radar` | Where the store and the vectors are kept |
| `RADAR_MODELS` | the fastembed cache | Where the embedding model is kept; the Dockerfile sets `/opt/models` and downloads the model at build time |

## Python API

The Space is the interface; these are the pieces of `scanner.py` that `app.py` uses, for anyone running their own copy.

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `collect(source, since, cfg, scorer, sem, state, progress, head)` | `(items, status_row)` | Nothing: a failure becomes `state: error` with its note | One check of one source |
| `Scorer(cfg).score(text, base, base_label, core_terms)` | `{keyword, topics, matched, parts}` | Nothing | The keyword score and its breakdown |
| `Semantic(cfg).load()` | `True` when the model loaded | Nothing: the error is kept in `error` | Then `score_many(texts)`, `embed(texts)`, `embed_query(text)` |
| `Head(path)` | `ready` is `True` when `head.json` loaded | Nothing: a missing or unreadable file leaves `ready` False | Then `score(item, vec)`: the learned score, with or without the item's embedding |
| `finish(items, scorer, sem, head=None)` | the items, with `score`, `band`, `rule` and meaning fields | Nothing | Rule score (keywords and meaning) for the keep gate; with a head, the learned score as `score` and `learned` set to `full` or `meta` |

## Inputs

The public sources listed under Network, read logged out. `radar.json` holds every source's schedule and queries, the keywords, weights, bands and the anchor sentences of the meaning score; edit it to change what the radar reads and how it scores.

## Outputs

Each item: `id` (source and its own id), `source`, `kind`, `title`, `url`, `date` (UTC), `first_seen`, `summary` (up to 900 characters), `score` (0 to 100), `band` (high 60 or more, medium 35 or more, low), `keyword`, `semantic` and `sim` (when the model is on), `rule` (the keyword and meaning score that decides whether an item is kept), `learned` (`full` or `meta` when the learned head set the score), `topics`, `topics_by_meaning`, `matched` (terms), `parts` (the keyword breakdown as label and points), `who` (the author; for a GitHub issue or pull request, who opened it), `activity` (a GitHub issue or pull request whose latest update came after its opening: `what` such as `comment`, `edited comment`, `review comment`, `review`, `approved`, `changes requested`, `closed`, `merged`, `label added` or `new commits`; `who` made it; `date`; `text`, what it said as plain text up to 600 characters with quoted text, code and images left out; `url` of the comment or review; `also`, up to three other kinds of update in the same two minutes), and per kind `code`, `pdf`, `stars`, `downloads`, `likes`, `upvotes`, `license`, `version`.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `lookback must be above zero` | `since` was 0 or negative | Use a positive lookback such as `15m` |
| `lookback '...' is not like 15m, 6h, 1d or an ISO time` | `since` was not a number with m, h, d or w, nor an ISO time | Use `1m` to `30d` or an ISO time |
| `by must be date (published or updated) or found (first seen by the radar)` | Another value of `by` | Use `date` or `found` |
| GitHub `partial` with `network error (IncompleteRead)` | A villa listing was cut off three times in a row; the repository search results of the same check are still kept | Nothing: the next check reads it again |
| GitHub `partial` with `HTTP 403 (rate limited)` | GitHub allows few logged-out calls per hour from one address | Nothing: the next check catches up; unchanged listings come from the ETag cache |
| `semantic` missing on items | The model has not loaded yet, or is off | Wait for the first check; keyword scores still apply |
| 429 from `/api/check` | A check started under 5 minutes ago | Wait `retry_after` seconds |
| A villa item shows "opened by" but no Latest update | Nothing the radar read explains its newest update: a push the commit dates do not match, a review on a pull request past the per-check lookup budget, or a comment older than the three pages of comments the first check reads | Nothing: the card never credits an older comment for a later change; the next check that sees an explaining update fills it in |

## How it works

1. A collector thread checks each source on its own schedule (`every_min` in `radar.json`: GitHub and Hugging Face 20 minutes, arXiv, PyPI and the blog 60, Zenodo 120, journals 180). Each check reads from 6 hours before the last good one; the first reads `backfill_days`.
2. For ScrollPrize/villa, the latest update of each issue and pull request comes from three repository-wide listings since the check's start time (issue and pull request comments, review comments, up to three pages of 100 each, and the newest 100 issue events), so their cost does not grow with the number of items. An update counts as the one that moved an item when it falls within 2 minutes of the item's updated time and after its opening (30 minutes for a pull request's newest commit, whose own time can sit before the push); a comment or review is preferred to a bare event in that window. A pull request those listings do not explain gets its reviews and newest commit read one by one, at most `pr_lookups` (2) per check, and the answer is remembered until the pull request changes again. The item's own text and score still come from the issue or pull request itself.
3. Each item is scored by keywords (`Scorer` in `scanner.py`): scroll terms add 45 plus 5 for each more (at most 15 more); in each topic a strong term counts on its own and a weak term counts half and only with a context term; negative terms take points off.
4. The meaning model (`Semantic`) embeds the title and the first 600 characters of the summary (`embed_chars`) and takes the cosine to the nearest anchor sentence; 0.70 maps to 0 and 0.80 to 100. The rule score is the higher of the keyword score and 0.55 meaning plus 0.45 keywords. A cosine of 0.76 or more adds that anchor's topic.
5. The learned head (`Head`, `head.json`) sets the shown score: ridge coefficients on the 384-number embedding and on eight metadata features (keyword and meaning scores, stars, likes and upvotes, new repository, links code, summary length, merged pull request) plus a one-hot of source and kind, then a monotone map to 0 to 100. Items with no embedding use the metadata-only head. Without `head.json` the rule score is shown.
6. Items whose rule score is `keep_score` (12) or more are merged into the store, which keeps `first_seen` and drops items older than 30 days.
7. Every request filters the store, so changing the lookback is instant.

## Cost and time

Free: a CPU Space (cpu-basic), no paid compute. The first collection after a start (30 days of backfill, every item read by meaning) took about 4 minutes on the Space (29 Oct 2026, private preview): arXiv 226 s for 1,000 listings (136 kept), Hugging Face 211 s for 1,255 (223 kept), GitHub 116 s for 205 (158 kept), Zenodo 111 s, journals 43 s, PyPI and the blog under 2 s; 591 items in 30 days. Later checks embed only items they have not seen, and the vectors are kept beside the store. Since 30 Oct 2026 a GitHub check reads villa's comments, review comments and issue events too: 3 more logged-out calls on a quiet check and up to 9 on a busy one (with the two pull request lookups), still within GitHub's 60 logged-out calls an hour at the 20 minute schedule. The page and API answer in well under a second meanwhile. In a 4-core cloud container the same model read about 2.5 texts of 600 characters per second while other sources were running.

## For agents

- **Command:** `curl -s "https://sharpmeow-vesuvius-radar.hf.space/api/items?since=1d&min_score=35&compact=true"`, or the MCP tool `search_items`.
- **Parse:** `matched` and `items[].{score,band,title,url,source,topics}`; `/api/sources` for whether each source is current.
- **Rerun:** safe; reads only. `POST /api/check` starts a check for everyone, at most once in 5 minutes.
- **Success:** HTTP 200 and `matched` present.
- **Not a pass:** a source in state `partial` or `error` means its items may be missing; a high score is relevance, not quality.
- **Go-ahead:** Nothing.
- **Never:** present a score as a judgment of a paper, or copy item text without its source link.

## Tests

`python -m unittest tests.test_vesuvius_radar -v`. Covers the scorer and its breakdown, text cleaning and unsafe links, lookbacks from 1 minute to 30 days, the `found` window, views, filters and sorting, overview and briefing, CSV and RSS, merging, the check cooldown, the MCP server, the shared embedding text and the vector cache, the villa watch's latest-update credit against a faked GitHub (the commenter and what they said, the opener kept, an approval found by the bounded lookup and remembered, an old comment never credited for a newer update), the comment-to-text cleaning, and the public-safety scan of the Space's files. It does not fetch any source or load the model.

## History

- 2026-10-29: first version (1.0.0), built from `8491642`, tested in a private Space, then made public.
- 2026-10-30: version 1.1.0 ([PR #285](https://github.com/ChaseHendrick/Scrolls/pull/285)). Villa issue and pull request cards say who made the latest update and what it said, with the opener kept as "opened by" (a card for villa #193 credited only the issue's opener for a newer comment by someone else); "Why this score" and "More like this" open separate panels (they opened the same one); long titles wrap on phones. Items gain `activity`; CSV gains `update`, `update_by`, `update_said` and `update_url`; RSS and the briefing name the update.
- 2026-10-30: version 1.1.1 (PR_PENDING). A cut-off download (`IncompleteRead`) is retried like a refused one, and a villa listing that still fails is a `partial` note that keeps the check's repository search results; the first check after the 1.1.0 redeploy had lost every GitHub item to one cut-off download.

## Related

- [`docs/tools/README.md`](README.md): the other tools and Spaces.
- [`docs/logs/2026-10-07-literature.md`](../logs/2026-10-07-literature.md): the literature note, which the radar can feed.
