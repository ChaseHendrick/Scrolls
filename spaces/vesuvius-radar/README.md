---
title: Vesuvius Radar
emoji: 🌋
colorFrom: red
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: New papers, code and data on the Herculaneum scrolls
thumbnail: https://huggingface.co/spaces/SharpMeow/vesuvius-radar/resolve/main/static/og-vesuvius.jpg
tags:
  - vesuvius-challenge
  - herculaneum
  - papers
  - mcp-server
  - research-feed
models:
  - BAAI/bge-small-en-v1.5
---

# Vesuvius Radar

New papers, code, models, data, posts and videos that could help read the Herculaneum scrolls of the
[Vesuvius Challenge](https://scrollprize.org/), collected around the clock from public sources and scored for
relevance. Every week gets a digest against the week before, every item gets a page you can share, and the whole
radar is open as JSON, CSV, RSS and an MCP server. No key, no login, no GPU quota.

![Vesuvius Radar: a radar sweep over Mount Vesuvius and the bay](https://huggingface.co/spaces/SharpMeow/vesuvius-radar/resolve/main/static/og.jpg)

## At a glance

| | |
| --- | --- |
| Sources | arXiv, GitHub (with ScrollPrize/villa pull requests, issues and releases), Hugging Face, PyPI, Zenodo, Crossref, OpenAlex, the Challenge blog and YouTube channel, Google News, Bing News, Hacker News |
| Kept | 30 days, so any lookback from 1 minute to 30 days is a filter, not a new scan |
| Checks | every 20 minutes (GitHub, Hugging Face) to every 3 hours (journals), plus Check now for anyone |
| Score | 0 to 100 from a small model fitted to blind ratings of 588 items; high is 60 or more, medium 35 or more |
| Views | Everyone, Researchers, Challenge team, Contributors |
| Outputs | page, JSON API, CSV, two RSS feeds, weekly Markdown, MCP server (11 tools) |
| Runs on | free CPU; holds no keys; the page keeps stars, hides and your last visit in your own browser |
| Version | 2.1.0 |

## Quick start

Open the Space, pick who is reading and how far back to look. The **Radar** tab shows top picks, charts and the list;
**This week** compares the current week with the week before; **Briefing** gives the best few items per topic.

From a terminal or a script, everything is a plain GET:

```bash
# the best paper, code, data or model, and community item of the last week
curl -s "https://sharpmeow-vesuvius-radar.hf.space/api/picks?since=7d"

# last week as Markdown, ready to paste into a forum or chat
curl -s "https://sharpmeow-vesuvius-radar.hf.space/week.md?week=last"

# papers and methods from the last week, score 35 or more, as CSV
curl -s -o radar.csv "https://sharpmeow-vesuvius-radar.hf.space/api/export.csv?since=7d&view=research&min_score=35"
```

```python
import json, urllib.request

base = "https://sharpmeow-vesuvius-radar.hf.space"
week = json.load(urllib.request.urlopen(f"{base}/api/week?week=this"))
print(week["week"], week["totals"]["relevant"], "new items scored medium or high")
for item in week["top"][:5]:
    print(item["score"], item["title"], item["url"])
```

Feeds: [`feed.xml`](https://sharpmeow-vesuvius-radar.hf.space/feed.xml) (last week, score 60 or more; every filter
works on it) and [`week.xml`](https://sharpmeow-vesuvius-radar.hf.space/week.xml) (one entry per finished week).

For agents, add the MCP server (Streamable HTTP, no session, no key):

```json
{"mcpServers": {"vesuvius-radar": {"type": "http", "url": "https://sharpmeow-vesuvius-radar.hf.space/mcp"}}}
```

Its tools: `search_items` (by words or by meaning), `get_item`, `find_similar`, `weekly_digest`, `top_picks`,
`briefing`, `overview`, `source_status`, `check_now`, `list_views`, `get_settings`. Every endpoint and parameter is on
the [OpenAPI page](https://sharpmeow-vesuvius-radar.hf.space/docs); tested snippets for more tools are in
[CONNECT.md](CONNECT.md).

## What it reads

| Source | What | Every |
| --- | --- | --- |
| arXiv | today's announcements in eight categories, past-week lists, a search of every category for scroll terms | 1 h |
| GitHub | repository searches for scroll terms; pull requests, issues and releases of ScrollPrize/villa with their latest comment or review | 20 min |
| Hugging Face | models, datasets and Spaces matching scroll terms, everything by scrollprize, daily papers | 20 min |
| PyPI | new versions of 18 libraries the work uses (vesuvius, zarr, tensorstore, nnunetv2 and others) | 1 h |
| Zenodo | records matching scroll terms: datasets, software, preprints, articles | 2 h |
| Journals | Crossref works created in the window, and OpenAlex works matching scroll terms or citing the field's founding papers ([Seales et al. 2016](https://doi.org/10.1126/sciadv.1601247), [Parker et al. 2019](https://doi.org/10.1371/journal.pone.0215775), [Mocella et al. 2015](https://doi.org/10.1038/ncomms6895)) | 3 h |
| News, blogs and videos | the Challenge's blog and YouTube channel (every post and video counts), Google News, Bing News and Hacker News searches | 1 h |

Only public pages and APIs are read, logged out. Chat servers and social media are not read.

## How an item is scored

- **Keywords.** Scroll terms add the most; topic terms count when a context term such as CT or volume is present; terms
  like chatbot take points off. Each item lists every term group and its points (Why this score).
- **Meaning.** A small sentence-embedding model, [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5),
  compares the item with sentences that describe the work the scrolls need. It also powers search by meaning and
  More like this.
- **Final score.** A ridge model on the embedding plus a few metadata features (keyword and meaning scores, source,
  kind, stars, likes), fitted to blind ratings of 588 collected items and calibrated to the rated bands. On held-out
  items its rank agreement with the ratings is 0.86 (Spearman), against 0.73 for keywords alone and 0.70 for the
  earlier rule score. The details are in `head.json` and [`/api/config`](https://sharpmeow-vesuvius-radar.hf.space/api/config).

Scores are a triage aid, not a judgment: open the item before acting on it.

## The weekly digest

Each ISO week runs Monday 00:00 to Monday 00:00 UTC. Counts compare items **new** in each week (opened, created or
published then) and scored medium or high, because an item's date moves when it is updated, and arXiv's daily lists
bring hundreds of low-scored papers a week. The best items and the lists take everything **active** in the week. A
week that reaches past the 30 days kept says so.

## Limits

- The store lives in the Space's memory and on its temporary disk. After a restart the collector backfills 30 days
  within minutes, but "Found by the radar" times restart from that moment.
- Logged-out GitHub search allows a few requests a minute, so a busy hour can miss a repository until the next check.
- OpenAlex limits logged-out calls per address per day, and a Space shares its address, so OpenAlex can answer "429"
  for a while; Journals then shows partial on the Sources tab and still keeps Crossref's rows.
- OpenAlex dates a work by its publication day, so a work indexed late shows under "Found by the radar" rather than
  by date.
- The learned model was fitted to items from October 2026 and has never seen a video or an OpenAlex-only work, so
  their scores rest on the embedding and keyword features it learned from other kinds of items.

## License and credit

Code: [Apache 2.0](LICENSE), in [ChaseHendrick/Scrolls, spaces/vesuvius-radar](https://github.com/ChaseHendrick/Scrolls/tree/main/spaces/vesuvius-radar).
Titles, summaries and links belong to their sources; the radar keeps titles, short summaries and links, never the papers, data or code themselves.
The embedding model is [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) (MIT). Made by Chase
Hendrick.

## Citation

```bibtex
@misc{sharpmeow2026vesuviusradar,
  author       = {SharpMeow},
  title        = {Vesuvius Radar: new work on the Herculaneum scrolls, scored for relevance},
  year         = {2026},
  howpublished = {\url{https://huggingface.co/spaces/SharpMeow/vesuvius-radar}},
  note         = {Version 2.1.0}
}
```

## Changelog

- **2.1.0 (November 2026)**: a paper, article or news story that names the Herculaneum scrolls specifically
  (Herculaneum, PHerc, virtual unwrapping and similar) and that the meaning model reads as scroll work now counts its
  rule score half (final = max(learned, (learned + rule) / 2)). The learned head had ranked such papers by their source:
  a paper on virtually unwrapping a Herculaneum scroll scored 47, below minor villa pull requests. "Why this score"
  says when a score was raised.
- **2.0.0 (November 2026)**: new This week tab with a week-against-week digest, also as Markdown (`/week.md`), RSS
  (`/week.xml`), JSON (`/api/week`) and the MCP tool `weekly_digest`; top picks for any window (`/api/picks`,
  `top_picks`); a shareable page per item (`/item?id=`) with link previews; OpenAlex as a second scholarly index,
  with works citing the field's founding papers marked "cites the field"; the Challenge's YouTube channel; a social
  card and Space thumbnail; this card. Every 1.x address still answers the same way.
- **1.2 (30 and 31 October 2026)**: news searches (Google News, Bing News, Hacker News) beside the Challenge blog;
  licenses GitHub cannot identify shown in words; the page follows Hugging Face's theme.
- **1.1 (30 October 2026)**: villa issue and pull request cards name who made the latest update and what it said.
- **1.0 (29 October 2026)**: first public release: seven sources, keyword and meaning scores, the learned final
  score, four reader views, charts, the briefing, JSON API, CSV, RSS and MCP.
