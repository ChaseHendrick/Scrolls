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
| Checked | 2026-10-29 against commit `8491642` |

## What it does

Work that could help read the scrolls appears in many places: arXiv, GitHub, Hugging Face, PyPI, Zenodo, journals and the Challenge's own blog. Most of it never says "Herculaneum". The radar reads all of those sources on a schedule, keeps 30 days of items, and scores each from 0 to 100 so the few relevant ones rise to the top.

Each item gets two scores. The keyword score adds points for scroll terms (Vesuvius, Herculaneum, PHerc, papyrus, Volume Cartographer and similar) and for terms in eight topics (sheets and surfaces, ink and imaging, fibers and tracing, compression and storage, registration, 3D encoders, text and reading, speed and scale), and every item shows which terms gave which points. The meaning score comes from a small sentence-embedding model run on the Space's CPU, which compares the item with sentences that describe the work the scrolls need; it catches items that use none of the keywords. The final score is the higher of the keyword score and a blend of both, so meaning alone can lift an item to medium but never to high.

The page shows the window you pick (1 minute to 30 days, default 1 day), by publish or update time or by when the radar first found the item, with charts (items over time by source, topics, the score histogram, sources, a topic by source grid and the top contributors, ranked by distinct pieces of work so many small related items count as one), a briefing of the strongest items per topic, and three reader views: researchers, the Challenge team, and contributors. The list opens on the newest items, 10 per page (10, 20, 50 or 100), with sources, topics, relevance and browser-only toggles in four dropdowns and the active filters shown as removable pills. Stars, hides and the last visit stay in your own browser.

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
- Meaning alone cannot reach the high band: a test feeds a perfect meaning score to an item with no keywords and requires medium.
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
| `collect(source, since, cfg, scorer, sem, state, progress)` | `(items, status_row)` | Nothing: a failure becomes `state: error` with its note | One check of one source |
| `Scorer(cfg).score(text, base, base_label, core_terms)` | `{keyword, topics, matched, parts}` | Nothing | The keyword score and its breakdown |
| `Semantic(cfg).load()` | `True` when the model loaded | Nothing: the error is kept in `error` | Then `score_many(texts)`, `embed(texts)`, `embed_query(text)` |
| `finish(items, scorer, sem)` | the items, with `score`, `band` and meaning fields | Nothing | Blends keyword and meaning scores |

## Inputs

The public sources listed under Network, read logged out. `radar.json` holds every source's schedule and queries, the keywords, weights, bands and the anchor sentences of the meaning score; edit it to change what the radar reads and how it scores.

## Outputs

Each item: `id` (source and its own id), `source`, `kind`, `title`, `url`, `date` (UTC), `first_seen`, `summary` (up to 900 characters), `score` (0 to 100), `band` (high 60 or more, medium 35 or more, low), `keyword`, `semantic` and `sim` (when the model is on), `topics`, `topics_by_meaning`, `matched` (terms), `parts` (the keyword breakdown as label and points), `who`, and per kind `code`, `pdf`, `stars`, `downloads`, `likes`, `upvotes`, `license`, `version`.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `lookback must be above zero` | `since` was 0 or negative | Use a positive lookback such as `15m` |
| `lookback '...' is not like 15m, 6h, 1d or an ISO time` | `since` was not a number with m, h, d or w, nor an ISO time | Use `1m` to `30d` or an ISO time |
| `by must be date (published or updated) or found (first seen by the radar)` | Another value of `by` | Use `date` or `found` |
| GitHub `partial` with `HTTP 403 (rate limited)` | GitHub allows few logged-out calls per hour from one address | Nothing: the next check catches up; unchanged listings come from the ETag cache |
| `semantic` missing on items | The model has not loaded yet, or is off | Wait for the first check; keyword scores still apply |
| 429 from `/api/check` | A check started under 5 minutes ago | Wait `retry_after` seconds |

## How it works

1. A collector thread checks each source on its own schedule (`every_min` in `radar.json`: GitHub and Hugging Face 20 minutes, arXiv, PyPI and the blog 60, Zenodo 120, journals 180). Each check reads from 6 hours before the last good one; the first reads `backfill_days`.
2. Each item is scored by keywords (`Scorer` in `scanner.py`): scroll terms add 45 plus 5 for each more (at most 15 more); in each topic a strong term counts on its own and a weak term counts half and only with a context term; negative terms take points off.
3. The meaning model (`Semantic`) embeds the title and the first 600 characters of the summary (`embed_chars`) and takes the cosine to the nearest anchor sentence; 0.70 maps to 0 and 0.80 to 100. The final score is the higher of the keyword score and 0.55 meaning plus 0.45 keywords. A cosine of 0.76 or more adds that anchor's topic.
4. Items at `keep_score` (12) or more are merged into the store, which keeps `first_seen` and drops items older than 30 days.
5. Every request filters the store, so changing the lookback is instant.

## Cost and time

Free: a CPU Space (cpu-basic), no paid compute. The first collection after a start (30 days of backfill, every item read by meaning) took about 4 minutes on the Space (29 Oct 2026, private preview): arXiv 226 s for 1,000 listings (136 kept), Hugging Face 211 s for 1,255 (223 kept), GitHub 116 s for 205 (158 kept), Zenodo 111 s, journals 43 s, PyPI and the blog under 2 s; 591 items in 30 days. Later checks embed only items they have not seen, and the vectors are kept beside the store. The page and API answer in well under a second meanwhile. In a 4-core cloud container the same model read about 2.5 texts of 600 characters per second while other sources were running.

## For agents

- **Command:** `curl -s "https://sharpmeow-vesuvius-radar.hf.space/api/items?since=1d&min_score=35&compact=true"`, or the MCP tool `search_items`.
- **Parse:** `matched` and `items[].{score,band,title,url,source,topics}`; `/api/sources` for whether each source is current.
- **Rerun:** safe; reads only. `POST /api/check` starts a check for everyone, at most once in 5 minutes.
- **Success:** HTTP 200 and `matched` present.
- **Not a pass:** a source in state `partial` or `error` means its items may be missing; a high score is relevance, not quality.
- **Go-ahead:** Nothing.
- **Never:** present a score as a judgment of a paper, or copy item text without its source link.

## Tests

`python -m unittest tests.test_vesuvius_radar -v`. Covers the scorer and its breakdown, text cleaning and unsafe links, lookbacks from 1 minute to 30 days, the `found` window, views, filters and sorting, overview and briefing, CSV and RSS, merging, the check cooldown, the MCP server, the shared embedding text and the vector cache, and the public-safety scan of the Space's files. It does not fetch any source or load the model.

## History

- 2026-10-29: first version (1.0.0), built from `8491642`, tested in a private Space, then made public.

## Related

- [`docs/tools/README.md`](README.md): the other tools and Spaces.
- [`docs/logs/2026-10-07-literature.md`](../logs/2026-10-07-literature.md): the literature note, which the radar can feed.
