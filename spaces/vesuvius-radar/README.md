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

New papers, code, models and data that could help read the Herculaneum scrolls, collected around the clock from
public sources and scored for relevance. Open to everyone, logged in or not; it runs on CPU and uses no GPU quota.

- **Sources:** arXiv (announcements, past-week lists and a search for scroll terms), GitHub (repository searches and
  ScrollPrize/villa pull requests, issues and releases), Hugging Face (models, datasets, Spaces, daily papers), PyPI
  (new versions of the libraries the work uses), Zenodo, Crossref journals and the Vesuvius Challenge blog.
- **Lookback:** 1 minute to 30 days (default 1 day), by publish or update time or by when the radar found an item.
- **Views:** researchers (papers and methods), the Challenge team (community activity about the scrolls), and
  contributors (tools, models, data, releases and papers with code).
- **Scores:** keyword matches with a per-term breakdown, a sentence-embedding model (BAAI/bge-small-en-v1.5) that
  scores meaning, finds "more like this" and searches by meaning, and a small learned model, fitted to blind ratings
  of 588 items, that sets the final score (rank agreement 0.86 on held-out items, against 0.70 for keywords and
  meaning alone).
- **For tools:** a JSON API (`/api/items`, `/api/overview`, `/api/briefing`, `/api/sources`; OpenAPI at `/docs`),
  CSV (`/api/export.csv`), RSS (`/feed.xml`) and an MCP server at `/mcp`. See CONNECT.md.

The Space holds no keys: every source is public and read logged out. Scores are a triage aid, not a judgment.
Source: [ChaseHendrick/Scrolls, spaces/vesuvius-radar](https://github.com/ChaseHendrick/Scrolls/tree/main/spaces/vesuvius-radar).
