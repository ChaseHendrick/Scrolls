"""Vesuvius Radar: a public Space that keeps collecting new work that could help read the Herculaneum scrolls, and serves
it as a page, a JSON API, an RSS feed and an MCP server.

A background collector checks each source on its own schedule (radar.json, every_min) and keeps every item from the
last 30 days in one store, so a lookback from 1 minute to 30 days is a filter, not a new scan. Anyone may ask for a
check now (POST /api/check), at most once every few minutes for the whole Space. The Space holds no keys and needs
no login: every source is public and read logged out.

  GET  /                      the page
  GET  /api/items             items in a lookback window, filtered and sorted (since=1m..30d, view, q, ...)
  GET  /api/item?id=ID        one item in full, with the items closest to it in meaning
  GET  /api/overview          counts behind the charts for a window and view
  GET  /api/briefing          the strongest items per topic for a window and view
  GET  /api/sources           the collector: each source's last check, next check and recent runs
  POST /api/check             check every source now (one at a time for the whole Space, with a cooldown)
  GET  /api/views, /api/config   the reader views and the scoring settings
  GET  /api/export.csv        a window as CSV
  GET  /feed.xml              a window as RSS
  POST /mcp                   the same as an MCP server (radar_mcp.py)
  GET  /docs                  the API's OpenAPI page
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

import scanner

HERE = Path(__file__).resolve().parent
SEED = HERE / "data" / "seed-store.json"
DATA_DIR = Path(os.environ.get("RADAR_DATA") or ("/data/radar" if os.access("/data", os.W_OK) else "/tmp/radar"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE_FILE = DATA_DIR / "store.json"
VECS_FILE = DATA_DIR / "vectors.npz"
COLLECT = os.environ.get("RADAR_COLLECT", "1") != "0"  # tests set 0: no background collector
SEMANTIC = os.environ.get("RADAR_SEMANTIC", "1") != "0"
PUBLIC_URL = "https://sharpmeow-vesuvius-radar.hf.space"
VERSION = "1.1.2"

CFG = scanner.load_config()
SCORER = scanner.Scorer(CFG)
SEM = scanner.Semantic(CFG)
HEAD = scanner.Head()
LOCK = threading.RLock()
STORE: dict = {"saved": None, "items": {}, "sources": {}, "runs": [], "state": {}}
CHECK = {"last": 0.0, "requested": None}
BOOT = scanner.iso(scanner.utcnow())


# ---------------------------------------------------------------- views (who is reading)

VIEWS = {
    "all": {"label": "Everyone", "about": "Everything the radar kept, from every source.", "any": []},
    "research": {"label": "Researchers",
                 "about": "New papers and methods: imaging, sheet and surface segmentation, ink detection, fibers, "
                          "registration, 3D encoders and reading damaged text. arXiv, journals, Hugging Face daily "
                          "papers and Zenodo publications.",
                 "any": [{"sources": ["arxiv", "journals"]},
                         {"kinds": ["daily-paper", "publication", "preprint", "journal article", "conference paper",
                                    "book chapter", "report", "thesis", "presentation", "poster"]}]},
    "team": {"label": "Challenge team",
             "about": "What the community shipped and said about the scrolls: villa pull requests, issues and releases, "
                      "new repositories, Hugging Face uploads and Zenodo records that name the scrolls, and the "
                      "Challenge blog.",
             "any": [{"sources": ["github", "blog"]},
                     {"sources": ["hf", "zenodo", "journals", "arxiv"], "topics": ["Scroll work"]}]},
    "builders": {"label": "Contributors",
                 "about": "Things you can use today: new and updated repositories, releases, models, datasets and "
                          "Spaces, package versions, and papers that link their code.",
                 "any": [{"kinds": ["repo", "release", "model", "dataset", "space", "package", "software"]},
                         {"has_code": True}]},
}


def in_view(i: dict, view: str) -> bool:
    v = VIEWS.get(view or "all")
    if v is None:
        raise KeyError(f"unknown view {view}; one of " + ", ".join(VIEWS))
    if not v["any"]:
        return True
    for c in v["any"]:
        if "sources" in c and i["source"] not in c["sources"]:
            continue
        if "kinds" in c and i["kind"] not in c["kinds"]:
            continue
        if "topics" in c and not any(t in i["topics"] for t in c["topics"]):
            continue
        if c.get("has_code") and not i.get("code"):
            continue
        return True
    return False


# ---------------------------------------------------------------- time windows

UNITS = {"m": 60, "min": 60, "h": 3600, "d": 86400, "w": 604800}
LOOKBACKS = ["1m", "5m", "15m", "30m", "1h", "3h", "6h", "12h", "1d", "2d", "3d", "7d", "14d", "30d"]


def parse_since(s: str | None, default: str = "1d") -> dt.datetime:
    """A lookback such as 1m, 15m, 6h, 1d or 30d (or an ISO time) as the moment the window starts, at most 30 days
    ago. ValueError on anything else."""
    s = (s or default).strip().lower()
    now = scanner.utcnow()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|min|h|d|w)", s)
    if m:
        secs = float(m.group(1)) * UNITS[m.group(2)]
        if secs <= 0:
            raise ValueError("lookback must be above zero")
        t = now - dt.timedelta(seconds=secs)
    else:
        t = scanner.parse_time(s)
        if not t:
            raise ValueError(f"lookback '{s}' is not like 15m, 6h, 1d or an ISO time")
    return max(t, now - dt.timedelta(days=CFG["retention_days"]))


# ---------------------------------------------------------------- store

def _load(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d.get("items"), dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def load_store():
    """The newest of the saved store and the one built into the image."""
    cands = [d for d in (_load(STORE_FILE), _load(SEED)) if d]
    if cands:
        best = max(cands, key=lambda d: d.get("saved") or "")
        with LOCK:
            STORE.update({k: best.get(k, STORE[k]) for k in STORE})
            STORE.setdefault("state", {})
    prune()


def save_store():
    with LOCK:
        STORE["saved"] = scanner.iso(scanner.utcnow())
        text = json.dumps(STORE, ensure_ascii=False, separators=(",", ":"))
    tmp = STORE_FILE.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(STORE_FILE)


def prune():
    cut = scanner.iso(scanner.utcnow() - dt.timedelta(days=CFG["retention_days"] + 1))
    with LOCK:
        for k in [k for k, i in STORE["items"].items() if i["date"] < cut and i.get("last_seen", "") < cut]:
            del STORE["items"][k]
        STORE["runs"] = STORE["runs"][-400:]


def merge(items: list[dict]) -> int:
    """Add or update items; returns how many were new to the store."""
    now = scanner.iso(scanner.utcnow())
    new = 0
    with LOCK:
        for i in items:
            old = STORE["items"].get(i["id"])
            if old:
                i["first_seen"] = old.get("first_seen", now)
                if old.get("date") != i["date"]:
                    i["updated"] = True
            else:
                i["first_seen"] = now
                new += 1
            i["last_seen"] = now
            STORE["items"][i["id"]] = i
    return new


# ---------------------------------------------------------------- collector

RUNNING: dict[str, dict] = {}


def _due(src: str, now: float) -> bool:
    s = STORE["sources"].get(src) or {}
    if src in RUNNING:
        return False
    if CHECK["requested"] and (s.get("finished") or "") < CHECK["requested"]:
        return True
    last = scanner.parse_time(s.get("finished"))
    return not last or now - last.timestamp() >= 60 * CFG["sources"][src]["every_min"]


def run_source(src: str):
    sc = CFG["sources"][src]
    now = scanner.utcnow()
    prev = STORE["sources"].get(src) or {}
    last_ok = scanner.parse_time(prev.get("ok_since_started"))
    floor = now - dt.timedelta(days=sc["backfill_days"])
    since = max(floor, last_ok - dt.timedelta(hours=6)) if last_ok else floor  # overlap so late listings are not missed
    state = STORE["state"].setdefault(src, {})
    RUNNING[src] = {"source": src, "label": sc["label"], "state": "running", "started": scanner.iso(now), "step": "starting"}

    def prog(row):
        RUNNING[src] = dict(row)

    try:
        items, row = scanner.collect(src, since, CFG, SCORER, SEM if SEM.ready else None, state, prog, HEAD)
        row["new"] = merge(items)
        with LOCK:
            if row["state"] != "error":
                row["ok_since_started"] = row["started"]
            else:
                row["ok_since_started"] = prev.get("ok_since_started")
            row["every_min"] = sc["every_min"]
            STORE["sources"][src] = row
            STORE["runs"].append({k: row[k] for k in ("source", "started", "finished", "since", "state", "read", "kept", "new", "ms")}
                                 | {"notes": row["notes"][:3]})
        prune()
        save_store()
    finally:
        RUNNING.pop(src, None)
    warm_vectors()


def collector_loop():
    if SEMANTIC:
        SEM.load()
        SEM.load_cache(VECS_FILE)
        warm_vectors()
    while True:
        now = time.time()
        for src in scanner.SOURCES:
            if _due(src, now):
                threading.Thread(target=run_source, args=(src,), daemon=True, name=f"collect-{src}").start()
        if CHECK["requested"] and not RUNNING and all(
                (STORE["sources"].get(s) or {}).get("finished", "") >= CHECK["requested"] for s in scanner.SOURCES):
            CHECK["requested"] = None
        time.sleep(5)


def request_check() -> tuple[int, dict]:
    with LOCK:
        wait = CFG["check_cooldown_s"] - (time.time() - CHECK["last"])
        if CHECK["requested"] or RUNNING:
            return 409, {"ok": False, "reason": "a check is already running", "sources": sources_status()}
        if wait > 0:
            return 429, {"ok": False, "reason": f"the last check started under {CFG['check_cooldown_s'] // 60} minutes ago; "
                                                f"try again in {int(wait) + 1} s", "retry_after": int(wait) + 1}
        CHECK["last"] = time.time()
        CHECK["requested"] = scanner.iso(scanner.utcnow())
    return 200, {"ok": True, "requested": CHECK["requested"], "next": "GET /api/sources until every source has finished"}


def sources_status() -> dict:
    now = scanner.utcnow()
    out = {}
    for src in scanner.SOURCES:
        s = dict(STORE["sources"].get(src) or {})
        last = scanner.parse_time(s.get("finished"))
        nxt = (last + dt.timedelta(minutes=CFG["sources"][src]["every_min"])) if last else now
        out[src] = {"label": scanner.LABELS[src], "every_min": CFG["sources"][src]["every_min"],
                    "state": "running" if src in RUNNING else s.get("state", "waiting"),
                    "step": (RUNNING.get(src) or {}).get("step", ""),
                    "last_check": s.get("finished"), "next_check": scanner.iso(max(nxt, now)),
                    "read": s.get("read", 0), "kept": s.get("kept", 0), "new": s.get("new", 0),
                    "seconds": round(s.get("ms", 0) / 1000, 1), "notes": s.get("notes", []),
                    "items_stored": sum(1 for i in STORE["items"].values() if i["source"] == src)}
    return out


# ---------------------------------------------------------------- queries

def _vec_text(i: dict) -> str:
    return scanner.embed_text(CFG, i["title"], i.get("summary", ""))


def warm_vectors():
    """Embed every stored item in the background, so similarity and meaning search answer at once."""
    if not SEM.ready:
        return
    with LOCK:
        texts = [_vec_text(i) for i in STORE["items"].values()]
    for k in range(0, len(texts), 256):
        SEM.embed(texts[k:k + 256])
    SEM.save_cache(VECS_FILE)


def public(i: dict) -> dict:
    return named({k: v for k, v in i.items() if not k.startswith("_")})


class Filters:
    """One set of filters, shared by the page, the API and MCP. Lists are any-of; everything else must hold."""

    FIELDS = ("since", "by", "view", "q", "by_meaning", "sources", "kinds", "topics", "bands", "min_score", "has_code", "ids")

    def __init__(self, since="1d", by="date", view="all", q="", by_meaning=False, sources=None, kinds=None, topics=None,
                 bands=None, min_score=0, has_code=False, ids=None):
        if view not in VIEWS:
            raise KeyError(f"unknown view {view}; one of " + ", ".join(VIEWS))
        if by not in ("date", "found"):
            raise ValueError("by must be date (published or updated) or found (first seen by the radar)")
        self.start = parse_since(since)
        self.since, self.by, self.view, self.q = since, by, view, (q or "").strip()
        self.by_meaning = bool(by_meaning) and bool(self.q)
        self.sources, self.kinds, self.topics, self.bands = sources or [], kinds or [], topics or [], bands or []
        self.min_score, self.has_code, self.ids = int(min_score), bool(has_code), set(ids or [])

    def when(self, i: dict) -> str:
        return i.get("first_seen", i["date"]) if self.by == "found" else i["date"]

    def keep(self, i: dict, t0: str, words: list[str]) -> bool:
        if self.when(i) < t0 or i["score"] < self.min_score or not in_view(i, self.view):
            return False
        if self.ids and i["id"] not in self.ids:
            return False
        if self.sources and i["source"] not in self.sources:
            return False
        if self.kinds and i["kind"] not in self.kinds:
            return False
        if self.topics and not any(t in i["topics"] for t in self.topics):
            return False
        if self.bands and i["band"] not in self.bands:
            return False
        if self.has_code and not i.get("code"):
            return False
        if words:
            act = i.get("activity") or {}
            hay = " ".join([i["title"], i.get("summary", ""), " ".join(i.get("matched", [])), i.get("who", ""),
                            " ".join(i["topics"]), i["id"], i.get("category", ""), act.get("who", ""),
                            act.get("text", ""), " ".join(person(w) for w in i.get("who", "").split(",")),
                            person(act.get("who", ""))]).lower()
            if not all(w in hay for w in words):
                return False
        return True


def query(f: Filters, sort: str = "score") -> list[dict]:
    """Items that pass the filters. sort: score, date, popularity; a meaning search ranks by meaning instead and adds
    match (cosine similarity to the query) to each item."""
    t0 = scanner.iso(f.start)
    meaning = f.by_meaning and SEM.ready
    words = [] if meaning else [w for w in f.q.lower().split() if w]
    with LOCK:
        out = [i for i in STORE["items"].values() if f.keep(i, t0, words)]
    if meaning and out:
        qv = SEM.embed_query(f.q)
        sims = SEM.embed([_vec_text(i) for i in out]) @ qv
        out = [dict(i, match=round(float(s), 3)) for i, s in zip(out, sims)]
        out.sort(key=lambda i: -i["match"])
        return out
    if sort == "date":
        out.sort(key=lambda i: f.when(i), reverse=True)
    elif sort == "popularity":
        out.sort(key=lambda i: (-((i.get("stars") or 0) + (i.get("likes") or 0) + (i.get("upvotes") or 0)), -i["score"]))
    else:
        out.sort(key=lambda i: f.when(i), reverse=True)
        out.sort(key=lambda i: i["score"], reverse=True)
    return out


def similar(item_id: str, limit: int = 8) -> list[dict]:
    with LOCK:
        it = STORE["items"].get(item_id)
        pool = [i for i in STORE["items"].values() if i["id"] != item_id]
    if not it:
        raise KeyError(f"no item {item_id}")
    if not SEM.ready or not pool:
        return []
    import numpy as np
    v = SEM.embed([_vec_text(it)])[0]
    sims = SEM.embed([_vec_text(i) for i in pool]) @ v
    order = np.argsort(-sims)[:limit]
    return [{"id": pool[k]["id"], "title": pool[k]["title"], "url": pool[k]["url"], "source": pool[k]["source"],
             "kind": pool[k]["kind"], "date": pool[k]["date"], "score": pool[k]["score"], "band": pool[k]["band"],
             "similarity": round(float(sims[k]), 3)} for k in order]


def tally(items, keys) -> dict:
    out: dict = {}
    for i in items:
        for k in keys(i):
            if k:
                out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


BIN_STEPS = [(900, 60), (3600, 300), (6 * 3600, 900), (12 * 3600, 1800), (2 * 86400, 3600), (3 * 86400, 3 * 3600),
             (7 * 86400, 6 * 3600), (14 * 86400, 12 * 3600)]


def timeline(f: Filters, items: list[dict]) -> dict:
    """Items per time bin, per source. The bin width grows with the window (1 minute up to 1 day)."""
    now = scanner.utcnow()
    span = (now - f.start).total_seconds()
    step = next((b for lim, b in BIN_STEPS if span <= lim + 1), 86400)  # +1 s: the request itself takes time
    first = int(f.start.timestamp() // step * step)
    n = int((now.timestamp() - first) // step) + 1
    bins = [{"t": scanner.iso(dt.datetime.fromtimestamp(first + k * step, dt.timezone.utc)), "n": {}} for k in range(n)]
    for i in items:
        t = scanner.parse_time(f.when(i))
        k = int((t.timestamp() - first) // step) if t else -1
        if 0 <= k < n:
            b = bins[k]["n"]
            b[i["source"]] = b.get(i["source"], 0) + 1
    return {"bin_seconds": step, "bins": bins}


WORK_SIM = 0.80  # two items by one person whose texts are this close in meaning are one piece of work


# One name per person: an account or nickname listed under "people" in radar.json counts and shows as that person.
PEOPLE = {a.strip().lower(): name for name, accounts in CFG.get("people", {}).items() for a in [name, *accounts]}


def person(name: str) -> str:
    return PEOPLE.get(name.strip().lower(), name.strip())


def named(i: dict) -> dict:
    """A copy of the item with who_name (and activity.who_name) when its author is listed under another name; who
    keeps the account as the source gave it."""
    out = dict(i)
    w = author(out) if "source" in out else ""
    if w and person(w) != w:
        out["who_name"] = person(w)
    a = out.get("activity")
    if a and a.get("who") and person(a["who"]) != a["who"]:
        out["activity"] = {**a, "who_name": person(a["who"])}
    return out


def author(i: dict) -> str:
    return i.get("who", "").split(",")[0].strip() if i["source"] not in ("pypi", "blog") else ""


def top_people(items: list[dict], limit: int = 10) -> list[dict]:
    """People and organizations ranked by distinct pieces of work, not raw item counts. A person's items are grouped
    when their texts are close in meaning (cosine >= WORK_SIM, same source), so twenty small related pull requests
    count as one piece of work; each piece is worth its best score, and the person's total is the sum. Without the
    meaning model, items from one source on the same day form one piece."""
    by: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for i in items:
        w = person(author(i))
        if w:
            by.setdefault(w.lower(), []).append(i)
            names.setdefault(w.lower(), w)
    rows = []
    for key, its in by.items():
        n = len(its)
        parent = list(range(n))

        def root(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        if SEM.ready and n > 1:
            v = SEM.embed([_vec_text(i) for i in its])
            sims = v @ v.T
            for a in range(n):
                for b in range(a + 1, n):
                    if sims[a, b] >= WORK_SIM and its[a]["source"] == its[b]["source"]:
                        parent[root(a)] = root(b)
        elif n > 1:
            first: dict = {}
            for a, i in enumerate(its):
                parent[a] = first.setdefault((i["source"], i["date"][:10]), a)
        groups: dict[int, list[dict]] = {}
        for a in range(n):
            groups.setdefault(root(a), []).append(its[a])
        value = sum(max(i["score"] for i in g) for g in groups.values())
        rows.append({"name": names[key], "value": value, "works": len(groups), "items": n})
    rows.sort(key=lambda r: (-r["value"], -r["works"], r["name"].lower()))
    return rows[:limit]


def overview(f: Filters) -> dict:
    items = query(f)
    people = top_people(items)
    hist = [0] * 20
    for i in items:
        hist[min(19, i["score"] // 5)] += 1
    matrix: dict = {}
    for i in items:
        for t in i["topics"]:
            row = matrix.setdefault(t, {})
            row[i["source"]] = row.get(i["source"], 0) + 1
    return {"since": scanner.iso(f.start), "until": scanner.iso(scanner.utcnow()), "view": f.view, "by": f.by,
            "items": len(items), "high": sum(1 for i in items if i["band"] == "high"),
            "medium": sum(1 for i in items if i["band"] == "medium"),
            "by_source": tally(items, lambda i: [i["source"]]), "by_band": tally(items, lambda i: [i["band"]]),
            "by_topic": tally(items, lambda i: i["topics"]), "by_kind": tally(items, lambda i: [i["kind"]]),
            "topic_source": matrix, "score_hist": hist, "top_people": {p["name"]: p["value"] for p in people},
            "people": people,
            "community": {"villa_merged": sum(1 for i in items if i["kind"] == "pr" and i.get("state") == "merged"),
                          "new_scroll_repos": sum(1 for i in items if i.get("new_repo") and "Scroll work" in i["topics"])},
            "with_code": sum(1 for i in items if i.get("code")),
            "new_repos": sum(1 for i in items if i.get("new_repo")),
            "lifted_by_meaning": sum(1 for i in items if i.get("semantic") is not None and not i.get("learned")
                                     and i["score"] > i["keyword"]),
            "learned": {"ready": HEAD.ready, "items": sum(1 for i in items if i.get("learned")),
                        "trained_on": HEAD.info.get("items"),
                        "spearman": (HEAD.info.get("evaluation") or {}).get("full", {}).get("spearman")},
            "timeline": timeline(f, items),
            "semantic": {"model": CFG["semantic"]["model"], "ready": SEM.ready, "error": SEM.error},
            "store": {"items": len(STORE["items"]), "saved": STORE.get("saved"), "booted": BOOT}}


def update_line(i: dict) -> str:
    """The latest update in words, for text outputs: 'Comment by X: what it said. Opened by Y. ' or ''."""
    a = i.get("activity") or {}
    if not a.get("who"):
        return ""
    said = f": {a['text']}" if a.get("text") else ""
    end = "" if said[-1:] in (".", "!", "?") else "."
    return f"{a['what'][:1].upper()}{a['what'][1:]} by {a['who']}{said}{end} Opened by {i.get('who') or 'unknown'}. "


def briefing(f: Filters, per_topic: int = 3) -> dict:
    items = query(f)
    used, topics = set(), {}
    for t in tally(items, lambda i: i["topics"]):
        pick = [i for i in items if t in i["topics"] and i["id"] not in used][:per_topic]
        if pick:
            topics[t] = [{k: i.get(k) for k in ("id", "title", "url", "source", "kind", "date", "score", "band", "who",
                                                 "who_name", "activity", "summary", "code", "keyword", "semantic")
                          if i.get(k) not in (None, "", [])} for i in map(named, pick)]
            used.update(i["id"] for i in pick)
    return {"since": scanner.iso(f.start), "view": f.view, "label": VIEWS[f.view]["label"], "about": VIEWS[f.view]["about"],
            "items": len(items), "topics": topics}


# ---------------------------------------------------------------- app

app = FastAPI(title="Vesuvius Radar API", version=VERSION, docs_url="/docs", redoc_url=None,
              description="New papers, code, models and data that could help read the Herculaneum scrolls, collected "
                          "from public sources and scored for relevance. No key or login needed. See /CONNECT.md.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


def _list(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    return FileResponse(HERE / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/connect.json", include_in_schema=False)
def connect_json():
    return FileResponse(HERE / "connect.json")


@app.get("/connect.html", response_class=HTMLResponse, include_in_schema=False)
def connect_html():
    return FileResponse(HERE / "connect.html")


@app.get("/CONNECT.md", response_class=PlainTextResponse, include_in_schema=False)
def connect_md():
    return (HERE / "CONNECT.md").read_text()


@app.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
def healthz():
    return "ok"


def filters(since: str = Query("1d", description="Lookback: 1m, 5m, 15m, 30m, 1h, 3h, 6h, 12h, 1d, 2d, 3d, 7d, 14d, 30d "
                                                  "(any number with m, h, d or w, at most 30 days) or an ISO time"),
            by: str = Query("date", description="date: when the item was published or last updated; found: when the radar "
                                                "first saw it"),
            view: str = Query("all", description="all, research, team or builders (see /api/views)"),
            q: str = Query("", description="Words that must all appear, or with by_meaning a phrase ranked by meaning"),
            by_meaning: bool = Query(False, description="Rank by closeness in meaning to q (sentence embeddings)"),
            sources: str = Query("", description="Comma list of " + ", ".join(scanner.SOURCES)),
            kinds: str = Query("", description="Comma list, such as paper,repo,pr,issue,release,model,dataset,space,package"),
            topics: str = Query("", description="Comma list of topics, such as Scroll work,Ink and imaging"),
            bands: str = Query("", description="Comma list of high, medium, low"),
            min_score: int = Query(0, ge=0, le=100), has_code: bool = Query(False, description="Only items that link code"),
            ids: str = Query("", description="Comma list of item ids (for example, your starred items)")) -> Filters:
    try:
        return Filters(since, by, view, q, by_meaning, _list(sources), _list(kinds), _list(topics), _list(bands), min_score,
                       has_code, _list(ids))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e).strip("'\""))


@app.get("/api/items", summary="Items in a lookback window, filtered and sorted")
def api_items(f: Filters = Depends(filters), sort: str = Query("score", pattern="^(score|date|popularity)$"),
              limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
              compact: bool = Query(False, description="Drop the score breakdown and cut summaries to 400 characters")):
    items = query(f, sort)
    page = [public(i) for i in items[offset:offset + limit]]
    if compact:
        page = [{**{k: v for k, v in i.items() if k != "parts"}, "summary": i.get("summary", "")[:400]} for i in page]
    return JSONResponse({"since": scanner.iso(f.start), "until": scanner.iso(scanner.utcnow()), "view": f.view, "by": f.by,
                         "matched": len(items), "offset": offset, "returned": len(page),
                         "by_meaning": f.by_meaning and SEM.ready, "items": page}, headers={"Cache-Control": "no-cache"})


@app.get("/api/counts", summary="How many items each standard lookback holds, for the same filters")
def api_counts(f: Filters = Depends(filters)):
    items = query(f.__class__("30d", f.by, f.view, f.q if not f.by_meaning else "", False, f.sources, f.kinds, f.topics,
                              f.bands, f.min_score, f.has_code, f.ids))
    now = scanner.utcnow()
    whens = [f.when(i) for i in items]
    out = {}
    for lb in LOOKBACKS:
        t0 = scanner.iso(parse_since(lb))
        out[lb] = sum(1 for w in whens if w >= t0)
    return JSONResponse({"lookbacks": out, "at": scanner.iso(now)}, headers={"Cache-Control": "no-cache"})


@app.get("/api/item", summary="One item in full, with the closest items in meaning")
def api_item(id: str):
    with LOCK:
        it = STORE["items"].get(id)
    if not it:
        raise HTTPException(404, f"no item {id}")
    return {**public(it), "similar": similar(id)}


@app.get("/api/overview", summary="Counts behind the charts, for the same filters as /api/items")
def api_overview(f: Filters = Depends(filters)):
    return JSONResponse(overview(f), headers={"Cache-Control": "no-cache"})


@app.get("/api/briefing", summary="The strongest items per topic")
def api_briefing(f: Filters = Depends(filters), per_topic: int = Query(3, ge=1, le=10)):
    if f.min_score == 0:
        f.min_score = 35
    return briefing(f, per_topic)


@app.get("/api/sources", summary="The collector: each source's last and next check")
def api_sources():
    return JSONResponse({"sources": sources_status(), "check_requested": CHECK["requested"],
                         "check_cooldown_s": CFG["check_cooldown_s"], "runs": STORE["runs"][-60:][::-1],
                         "semantic": {"model": CFG["semantic"]["model"], "ready": SEM.ready, "error": SEM.error},
                         "store": {"items": len(STORE["items"]), "saved": STORE.get("saved"), "booted": BOOT}},
                        headers={"Cache-Control": "no-store"})


@app.post("/api/check", summary="Check every source now (cooldown for the whole Space)")
def api_check():
    code, body = request_check()
    return JSONResponse(body, status_code=code)


@app.get("/api/views", summary="The reader views")
def api_views():
    return {k: {"label": v["label"], "about": v["about"], "rule": v["any"]} for k, v in VIEWS.items()}


def head_summary() -> dict:
    """What the learned head is, for the page and agents: no coefficients, just how it was fitted and how it did."""
    if not HEAD.ready:
        return {"ready": False}
    i = HEAD.info
    return {"ready": True, "trained": i.get("trained"), "items": i.get("items"), "target": i.get("target"),
            "calibration": i.get("calibration"), "meta_features": i.get("meta_features"),
            "evaluation": i.get("evaluation")}


@app.get("/api/config", summary="Sources, keywords, weights, anchor sentences and the learned head's summary")
def api_config():
    return {**CFG, "learned": head_summary()}


@app.get("/api/export.csv", summary="A window as CSV, for the same filters as /api/items")
def export_csv(f: Filters = Depends(filters), sort: str = Query("score", pattern="^(score|date|popularity)$")):
    items = query(f, sort)
    buf = io.StringIO()
    cols = ["score", "band", "keyword", "semantic", "rule", "source", "kind", "date", "first_seen", "title", "url", "who", "topics",
            "matched", "code", "summary", "update", "update_by", "update_said", "update_url"]
    w = csv.writer(buf)
    w.writerow(cols)
    for i in items:
        a = i.get("activity") or {}
        i = {**i, "update": a.get("what", ""), "update_by": a.get("who", ""), "update_said": a.get("text", ""),
             "update_url": a.get("url", "")}
        w.writerow([("; ".join(i.get(c) or []) if c in ("topics", "matched", "code") else i.get(c, "")) for c in cols])
    name = f"vesuvius-radar-{f.view}-{re.sub(r'[^0-9a-z]', '', f.since.lower())[:12]}-{scanner.iso(scanner.utcnow())[:10]}.csv"
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/feed.xml", summary="A window as RSS (default: 7 days, score 60 or more)")
def feed(f: Filters = Depends(filters)):
    if f.since == "1d" and f.min_score == 0:  # the defaults of /api/items are too loose for a feed
        f = Filters("7d", f.by, f.view, f.q, f.by_meaning, f.sources, f.kinds, f.topics, f.bands, 60, f.has_code)
    items = query(f, "date")
    rows = []
    for i in items[:200]:
        d = scanner.parse_time(f.when(i)) or scanner.utcnow()
        desc = f"Score {i['score']} ({i['band']}), {scanner.LABELS.get(i['source'], i['source'])} {i['kind']}. " + update_line(i) + i.get("summary", "")
        rows.append(f"<item><title>{xml_escape(i['title'])}</title><link>{xml_escape(i['url'])}</link>"
                    f'<guid isPermaLink="false">{xml_escape(i["id"])}</guid>'
                    f"<pubDate>{d.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
                    f"<category>{xml_escape(scanner.LABELS.get(i['source'], i['source']))}</category>"
                    f"<description>{xml_escape(desc)}</description></item>")
    title = f"Vesuvius Radar: {VIEWS[f.view]['label']}, score {f.min_score} or more"
    body = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            f"<title>{xml_escape(title)}</title><link>{PUBLIC_URL}/</link>"
            "<description>New work that could help read the Herculaneum scrolls, scored for relevance.</description>"
            + "".join(rows) + "</channel></rss>")
    return Response(body, media_type="application/rss+xml")


import radar_mcp  # noqa: E402  (needs the functions above)

radar_mcp.bind(sys.modules[__name__])
app.include_router(radar_mcp.router)


@app.on_event("startup")
def _start():
    load_store()
    if COLLECT:
        threading.Thread(target=collector_loop, daemon=True, name="collector").start()
    elif SEMANTIC:
        threading.Thread(target=lambda: (SEM.load(), warm_vectors()), daemon=True).start()
