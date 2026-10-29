# Connect your tool: Vesuvius Radar

Everything this page shows is open JSON, CSV and RSS over HTTPS, and the whole radar is also an MCP server, so a script, a spreadsheet, a feed reader or an agent can use it. No key, no login and no GPU quota: anyone can call it, logged in or not.

Checked 2026-10-29. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## MCP server for agents

`https://sharpmeow-vesuvius-radar.hf.space/mcp`

License: Item titles, summaries and links belong to their sources (arXiv, GitHub, Hugging Face, PyPI, Zenodo, Crossref, the Vesuvius Challenge blog); the radar's code is Apache 2.0. Streamable HTTP, no session, JSON replies, no key. Nine tools: search_items (by words or by meaning), get_item, find_similar, briefing, overview, source_status, check_now, list_views, get_settings.

### Links and embed (tested 2026-10-24)

```text
MCP endpoint (Streamable HTTP, POST): https://sharpmeow-vesuvius-radar.hf.space/mcp
```

## JSON API, CSV and RSS

`https://sharpmeow-vesuvius-radar.hf.space/api/items?since=1d`

License: Item titles, summaries and links belong to their sources; the radar's code is Apache 2.0. since takes 1m up to 30d (default 1d); view takes all, research, team or builders. The same filters work on items, overview, briefing, export.csv and feed.xml. The OpenAPI page lists every parameter.

### Links and embed (tested 2026-10-24)

```text
Items from the last day (JSON): https://sharpmeow-vesuvius-radar.hf.space/api/items?since=1d
Papers and methods from the last week, score 35 or more (JSON): https://sharpmeow-vesuvius-radar.hf.space/api/items?since=7d&view=research&min_score=35
Search by meaning (JSON): https://sharpmeow-vesuvius-radar.hf.space/api/items?since=30d&q=ink+detection+in+x-ray+ct&by_meaning=true
The strongest items per topic (JSON): https://sharpmeow-vesuvius-radar.hf.space/api/briefing?since=7d
Counts behind the charts (JSON): https://sharpmeow-vesuvius-radar.hf.space/api/overview?since=1d
The collector: each source's last and next check (JSON): https://sharpmeow-vesuvius-radar.hf.space/api/sources
The last week as CSV: https://sharpmeow-vesuvius-radar.hf.space/api/export.csv?since=7d
RSS feed: last week, score 60 or more: https://sharpmeow-vesuvius-radar.hf.space/feed.xml
Reader views and their rules (JSON): https://sharpmeow-vesuvius-radar.hf.space/api/views
Sources, keywords, weights and anchor sentences (JSON): https://sharpmeow-vesuvius-radar.hf.space/api/config
OpenAPI page with every parameter: https://sharpmeow-vesuvius-radar.hf.space/docs
```
