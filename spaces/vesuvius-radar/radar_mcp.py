"""Vesuvius Radar as an MCP server, so an agent can read the radar, search it by words or meaning, and ask for a check.

Transport: MCP Streamable HTTP at POST /mcp, stateless, every reply plain JSON (no server-sent stream, so GET /mcp
answers 405 as the spec allows). Protocol versions 2024-11-05, 2025-03-26 and 2025-06-18. No key or login: the Space
is public and every tool is free to call. Nothing an agent does here changes what others see, except check_now, which
asks every source for its newest items (once every few minutes for the whole Space).
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

import scanner


core = None  # app.py, set by bind(): app imports this module at its end, so a top-level import would be circular


def bind(app_module):
    global core
    core = app_module

router = APIRouter()
VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = {"name": "vesuvius-radar", "title": "Vesuvius Radar", "version": "1.2.0"}
INSTRUCTIONS = (
    "Vesuvius Radar keeps collecting new work that could help read the Herculaneum scrolls (the Vesuvius Challenge): "
    "papers from arXiv and journals, GitHub repositories with ScrollPrize/villa pull requests, issues and releases, "
    "Hugging Face models, datasets, Spaces and daily papers, Zenodo records, PyPI versions of the libraries the work "
    "uses, the Challenge blog and news searches. Every item is scored 0 to 100 (60 or more is high) by a small model fitted to blind "
    "ratings, which reads keyword matches, a sentence-embedding model's sense of meaning, source and popularity; the "
    "item lists its keyword and meaning scores and the terms that matched. Start with briefing "
    "or search_items over a lookback (1m to 30d, default 1d). Views: research, team, builders, all. Scores are a "
    "triage aid, not judgment: read the item before acting on it."
)

SINCE = {"type": "string", "default": "1d",
         "description": "Lookback window: 1m, 5m, 15m, 30m, 1h, 3h, 6h, 12h, 1d, 2d, 3d, 7d, 14d or 30d (any number with "
                        "m, h, d or w, at most 30 days), or an ISO time."}
BY = {"type": "string", "enum": ["date", "found"], "default": "date",
      "description": "date: when the item was published or last updated; found: when the radar first saw it."}
VIEW = {"type": "string", "enum": ["all", "research", "team", "builders"], "default": "all",
        "description": "Who is reading: research (papers and methods), team (community activity about the scrolls), "
                       "builders (tools, models, data and releases you can use, papers with code), all."}
LIST = lambda d: {"type": "array", "items": {"type": "string"}, "description": d}  # noqa: E731

TOOLS = [
    {"name": "search_items",
     "title": "Search the radar",
     "description": "Items in the lookback window, filtered and sorted. With by_meaning true, query is a phrase and items "
                    "are ranked by how close they are in meaning (each gets a match value); otherwise every word of "
                    "query must appear. Each item has id, score, band, keyword and semantic scores, source, kind, "
                    "title, url, date, first_seen, topics, matched terms, who (the author, for an issue or pull request "
                    "who opened it), code links and a summary; a GitHub issue or pull request whose latest update "
                    "came after its opening also has activity: what (comment, review, approved, closed...), who made "
                    "it, date, text (what it said) and url.",
     "inputSchema": {"type": "object", "properties": {
         "since": SINCE, "by": BY, "view": VIEW,
         "query": {"type": "string", "description": "Words, or a phrase with by_meaning."},
         "by_meaning": {"type": "boolean", "default": False},
         "sources": LIST("Any of " + ", ".join(scanner.SOURCES) + ". Empty means all."),
         "kinds": LIST("Item kinds such as paper, repo, pr, issue, release, model, dataset, space, package, post."),
         "topics": LIST("Topics such as 'Scroll work', 'Sheets and surfaces', 'Ink and imaging', 'Fibers and tracing'."),
         "bands": {"type": "array", "items": {"type": "string", "enum": ["high", "medium", "low"]}},
         "min_score": {"type": "integer", "minimum": 0, "maximum": 100, "default": 20},
         "has_code": {"type": "boolean", "default": False, "description": "Only items that link code, models or data."},
         "sort": {"type": "string", "enum": ["score", "date", "popularity"], "default": "score"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
         "offset": {"type": "integer", "minimum": 0, "default": 0}}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "get_item",
     "title": "One item in full",
     "description": "Everything stored about one item, the score breakdown (each term group and its points) and the "
                    "eight items closest to it in meaning.",
     "inputSchema": {"type": "object", "required": ["item_id"], "properties": {
         "item_id": {"type": "string", "description": "An id from search_items, such as arxiv:2610.12345."}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "find_similar",
     "title": "Items like this one",
     "description": "Items in the store (last 30 days) closest in meaning to one item, with their cosine similarity.",
     "inputSchema": {"type": "object", "required": ["item_id"], "properties": {
         "item_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 8}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "briefing",
     "title": "Strongest items per topic",
     "description": "For a window and view, the best few items in each topic, with no item repeated: a quick read of "
                    "what matters.",
     "inputSchema": {"type": "object", "properties": {
         "since": SINCE, "view": VIEW,
         "per_topic": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
         "min_score": {"type": "integer", "minimum": 0, "maximum": 100, "default": 35}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "overview",
     "title": "Counts for a window",
     "description": "Counts behind the page's charts: items by source, band, topic and kind, the most active people and "
                    "organizations, items with code, new repositories, and the state of the embedding model and store.",
     "inputSchema": {"type": "object", "properties": {"since": SINCE, "view": VIEW,
                                                       "min_score": {"type": "integer", "minimum": 0, "maximum": 100, "default": 0}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "source_status",
     "title": "The collector",
     "description": "Each source's schedule, last and next check, listings read, items kept and new, notes, and the "
                    "most recent runs.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True}},
    {"name": "check_now",
     "title": "Check every source now",
     "description": "Ask every source for its newest items instead of waiting for the schedule. One check runs at a "
                    "time for the whole Space, with a few minutes between checks. With wait true it returns when the "
                    "check is done (up to about two minutes) with what was new.",
     "inputSchema": {"type": "object", "properties": {"wait": {"type": "boolean", "default": False}}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}},
    {"name": "list_views",
     "title": "Reader views",
     "description": "The views (research, team, builders, all): who each is for and the rule that picks its items.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True}},
    {"name": "get_settings",
     "title": "Sources, keywords and anchors",
     "description": "The settings (radar.json): scroll terms, topics with strong and weak terms and weights, context "
                    "and negative terms, the meaning model with its anchor sentences, and each source's queries and "
                    "schedule.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True}},
]


def _compact(i: dict) -> dict:
    keep = ("id", "score", "band", "keyword", "semantic", "match", "source", "kind", "title", "url", "date", "first_seen",
            "topics", "matched", "who", "code", "stars", "likes", "upvotes", "downloads", "license", "state", "category",
            "pdf", "hf_url", "new_repo", "who_name")
    i = core.named(i)
    out = {k: i[k] for k in keep if k in i and i[k] not in (None, "", [])}
    if i.get("activity"):  # who made the latest update and what it said; `who` is the opener
        a = i["activity"]
        out["activity"] = {**a, "text": a["text"] if len(a.get("text", "")) <= 320 else a["text"][:317] + "..."}
    s = i.get("summary", "")
    out["summary"] = s if len(s) <= 320 else s[:317] + "..."
    return out


def _filters(a: dict, min_default: int = 20):
    return core.Filters(a.get("since") or "1d", a.get("by") or "date", a.get("view") or "all", a.get("query", ""),
                        a.get("by_meaning", False), a.get("sources") or None, a.get("kinds") or None,
                        a.get("topics") or None, a.get("bands") or None, int(a.get("min_score", min_default)),
                        a.get("has_code", False))


def t_search_items(a):
    lim, off = int(a.get("limit", 20)), int(a.get("offset", 0))
    f = _filters(a)
    items = core.query(f, a.get("sort", "score"))
    out = {"since": scanner.iso(f.start), "matched": len(items), "offset": off, "returned": len(items[off:off + lim]),
           "items": [_compact(i) for i in items[off:off + lim]]}
    if f.by_meaning and not core.SEM.ready:
        out["note"] = "the embedding model is not loaded yet; matched by words instead"
    return out, False


def t_get_item(a):
    with core.LOCK:
        it = core.STORE["items"].get(a["item_id"])
    if not it:
        raise KeyError(f"no item {a['item_id']}")
    return {**core.public(it), "similar": core.similar(a["item_id"])}, False


def t_find_similar(a):
    return {"item_id": a["item_id"], "similar": core.similar(a["item_id"], int(a.get("limit", 8))),
            "model_ready": core.SEM.ready}, False


def t_briefing(a):
    return core.briefing(_filters(a, 35), int(a.get("per_topic", 3))), False


def t_overview(a):
    o = core.overview(_filters(a, 0))
    o.pop("timeline", None)  # the page draws it; an agent rarely needs a few hundred bins
    return o, False


def t_source_status(a):
    return {"sources": core.sources_status(), "runs": core.STORE["runs"][-20:][::-1]}, False


def t_check_now(a):
    before = len(core.STORE["items"])
    code, body = core.request_check()
    if code != 200 or not a.get("wait"):
        return body, code not in (200, 409, 429)
    t0 = time.time()
    while time.time() - t0 < 170:
        time.sleep(2)
        if not core.CHECK["requested"]:
            st = core.sources_status()
            return {"finished": True, "new_items": len(core.STORE["items"]) - before,
                    "sources": {k: {"state": v["state"], "kept": v["kept"], "new": v["new"]} for k, v in st.items()}}, False
    return {"finished": False, "note": "still running; call source_status"}, False


def t_list_views(a):
    return {k: {"label": v["label"], "about": v["about"], "rule": v["any"]} for k, v in core.VIEWS.items()}, False


def t_get_settings(a):
    return core.CFG, False


HANDLERS = {"search_items": t_search_items, "get_item": t_get_item, "find_similar": t_find_similar,
            "briefing": t_briefing, "overview": t_overview, "source_status": t_source_status, "check_now": t_check_now,
            "list_views": t_list_views, "get_settings": t_get_settings}


def _result(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle(msg) -> dict | None:
    """One JSON-RPC message in, its reply out (None for a notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if mid is None:
        return None  # notifications/initialized, notifications/canceled and the like: nothing to answer
    if not isinstance(params, dict):
        return _error(mid, -32602, "params must be an object")
    if method == "initialize":
        want = params.get("protocolVersion")
        return _result(mid, {"protocolVersion": want if want in VERSIONS else VERSIONS[0],
                             "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER,
                             "instructions": INSTRUCTIONS})
    if method == "ping":
        return _result(mid, {})
    if method == "tools/list":
        return _result(mid, {"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in HANDLERS:
            return _error(mid, -32602, f"unknown tool {name}")
        if not isinstance(args, dict):
            return _error(mid, -32602, "arguments must be an object")
        try:
            data, is_error = HANDLERS[name](args)
        except KeyError as e:
            data, is_error = {"error": str(e).strip("'\"")}, True
        except (TypeError, ValueError) as e:
            data, is_error = {"error": f"bad arguments: {e}"}, True
        return _result(mid, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}],
                             "structuredContent": data, "isError": is_error})
    if method in ("resources/list", "prompts/list"):
        return _result(mid, {method.split("/")[0]: []})
    return _error(mid, -32601, f"method not found: {method}")


@router.post("/mcp", include_in_schema=False)
async def mcp_post(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_error(None, -32700, "parse error"), status_code=400)
    if isinstance(body, list):
        if len(body) > 20:
            return JSONResponse(_error(None, -32600, "at most 20 messages per batch"), status_code=400)
        replies = [r for r in [await run_in_threadpool(handle, m) for m in body] if r is not None]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await run_in_threadpool(handle, body)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@router.get("/mcp", include_in_schema=False)
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp", include_in_schema=False)
def mcp_delete():
    return Response(status_code=405, headers={"Allow": "POST"})
