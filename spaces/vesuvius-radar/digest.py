"""The radar's weekly digest, top picks and shareable item pages. Pure functions over stored items: no network, no
model, no key. Other radars built on this code may copy it unchanged.

  week_digest(items, week)     one ISO week (Monday 00:00 UTC to the next Monday): totals against the week before,
                               topics rising and falling, the ten best items, and lists by what people can use
  week_markdown(d, base)       the same digest as Markdown, ready to paste into a forum or chat
  top_picks(items)             the best item of each kind of work (paper, code, data and models, community)
  item_page(item, sims, ...)   one item as a standalone page with link-preview tags, for sharing
"""

from __future__ import annotations

import datetime as dt
import html
import re
import urllib.parse

PAPER_KINDS = {"paper", "daily-paper", "journal article", "posted content", "preprint", "proceedings article",
               "book chapter", "book", "publication", "conference paper", "report", "thesis", "presentation", "poster",
               "conference proceeding"}
CODE_KINDS = {"repo", "release", "package", "software", "computational notebook"}
DATA_KINDS = {"dataset", "model", "space"}
COMMUNITY_KINDS = {"pr", "issue", "post", "news", "video", "thread", "event"}
GROUPS = [("paper", "Paper", PAPER_KINDS), ("code", "Code", CODE_KINDS), ("data", "Data and models", DATA_KINDS),
          ("community", "Community", COMMUNITY_KINDS)]
KEEP = ("id", "title", "url", "source", "kind", "date", "first_seen", "score", "band", "who", "who_name", "topics",
        "summary", "state", "stars", "downloads", "likes", "category", "new_repo", "code", "views", "cites_field")


def group_of(i: dict) -> str:
    k = i.get("kind") or ""
    for key, _, kinds in GROUPS:
        if k in kinds:
            return key
    return "community" if i.get("source") in ("github", "blog") else "paper"


def slim(i: dict, summary: int = 280) -> dict:
    out = {k: i.get(k) for k in KEEP if i.get(k) not in (None, "", [])}
    if "summary" in out:
        s = out["summary"]
        out["summary"] = s if len(s) <= summary else s[:summary].rsplit(" ", 1)[0] + "..."
    out["group"] = group_of(i)
    return out


# ---------------------------------------------------------------- weeks

WEEK_RX = re.compile(r"(\d{4})-?W(\d{1,2})", re.I)


def week_start(t: dt.datetime) -> dt.datetime:
    d = t.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return d - dt.timedelta(days=d.weekday())


def week_name(start: dt.datetime) -> str:
    y, w, _ = start.isocalendar()
    return f"{y}-W{w:02d}"


def parse_week(s: str | None, now: dt.datetime) -> dt.datetime:
    """'2026-W48', 'this', 'last' or empty (this week) as the Monday the week starts. ValueError otherwise."""
    s = (s or "this").strip()
    if s in ("this", "current", ""):
        return week_start(now)
    if s in ("last", "previous"):
        return week_start(now) - dt.timedelta(days=7)
    m = WEEK_RX.fullmatch(s)
    if not m:
        raise ValueError(f"week '{s}' is not like 2026-W48, this or last")
    try:
        d = dt.datetime.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError as e:
        raise ValueError(f"week '{s}' does not exist") from e
    return d.replace(tzinfo=dt.timezone.utc)


def _in(i: dict, a: str, b: str, by: str) -> bool:
    """Active in [a, b): published, updated or (by="found") first seen by the radar in that span."""
    w = (i.get("first_seen") if by == "found" else i.get("date")) or ""
    return a <= w < b


def _new(i: dict, a: str, b: str, by: str) -> bool:
    """New in [a, b): opened, created or published then (an item's date moves when it is updated, so counting by it
    would empty older weeks; the creation time stays put, so two weeks compare fairly)."""
    w = (i.get("first_seen") if by == "found" else (i.get("created") or i.get("date"))) or ""
    return a <= w < b


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def week_digest(items: list[dict], start: dt.datetime, now: dt.datetime, *, by: str = "date", top: int = 10,
                per_list: int = 6, oldest: str | None = None, name=lambda i: i) -> dict:
    """One ISO week of the store against the week before. Totals, topics and the comparison count items new in each
    week (_new); the top items and the lists take everything active in the week (_in), best score first. `items` is
    every stored item; `oldest` is the earliest time the store still covers (a week that starts before it is marked
    partial); `name` maps an item to its public copy."""
    end = start + dt.timedelta(days=7)
    prev = start - dt.timedelta(days=7)
    a, b, p = _iso(start), _iso(end), _iso(prev)
    this = sorted((i for i in items if _in(i, a, b, by)), key=lambda i: (-i["score"], i.get("date") or ""))
    born = [i for i in items if _new(i, a, b, by)]
    last = [i for i in items if _new(i, p, a, by)]

    def counts(its):
        """Raw totals, then counts over the items scored medium or high: arXiv's daily lists bring hundreds of
        low-scored papers a week, which would drown a comparison."""
        rel = [i for i in its if i.get("band") in ("high", "medium")]
        topics: dict[str, int] = {}
        for i in rel:
            for t in i.get("topics") or []:
                topics[t] = topics.get(t, 0) + 1
        return {"items": len(its), "relevant": len(rel), "high": sum(1 for i in rel if i.get("band") == "high"),
                "papers": sum(1 for i in rel if group_of(i) == "paper"),
                "code": sum(1 for i in rel if group_of(i) == "code"),
                "data": sum(1 for i in rel if group_of(i) == "data"),
                "villa_merged": sum(1 for i in its if i.get("kind") == "pr" and i.get("state") == "merged"),
                "new_repos": sum(1 for i in its if i.get("kind") == "repo"),
                "contributors": len({(i.get("who_name") or i.get("who") or "").split(",")[0].strip().lower()
                                     for i in rel if i.get("who") and group_of(i) != "paper"} - {""}),
                "topics": topics}

    c, l = counts(born), counts(last)
    rising = []
    for t in sorted(set(c["topics"]) | set(l["topics"])):
        n, m = c["topics"].get(t, 0), l["topics"].get(t, 0)
        rising.append({"topic": t, "this": n, "last": m, "change": n - m})
    rising.sort(key=lambda r: (-r["change"], -r["this"], r["topic"]))
    good = [i for i in this if i.get("band") in ("high", "medium")] or this

    def pick(test, n=per_list):
        return [slim(name(i)) for i in good if test(i)][:n]

    lists = [
        ("papers", "Papers and articles", pick(lambda i: group_of(i) == "paper")),
        ("code", "Code and releases", pick(lambda i: group_of(i) == "code")),
        ("data", "Data, models and Spaces", pick(lambda i: group_of(i) == "data")),
        ("villa", "Merged in villa", [slim(name(i)) for i in this if i.get("kind") == "pr" and i.get("state") == "merged"][:per_list]),
        ("posts", "Posts, news and videos", pick(lambda i: i.get("kind") in ("post", "news", "video", "thread"))),
    ]
    complete = now >= end
    return {"week": week_name(start), "start": a, "end": b, "by": by, "complete": complete,
            "through": _iso(min(now, end)), "partial": bool(oldest and oldest > a),
            "previous_partial": bool(oldest and oldest > p), "active": len(this),
            "previous": week_name(prev), "next": week_name(end) if complete else None,
            "totals": {k: v for k, v in c.items() if k != "topics"},
            "last_week": {k: v for k, v in l.items() if k != "topics"},
            "topics": rising,
            "top": [slim(name(i)) for i in this[:top]],
            "lists": [{"key": k, "title": t, "items": v} for k, t, v in lists if v]}


def _ago_word(n: int, one: str) -> str:
    return f"{n} {one}" + ("" if n == 1 else "s")


def _delta(n: int, m: int) -> str:
    if n == m:
        return "same as the week before"
    return f"{'up' if n > m else 'down'} from {m}"


def week_markdown(d: dict, base: str, site: str = "Vesuvius Radar") -> str:
    """The digest as Markdown: a heading, the totals, the top items with links, and the lists."""
    t, l = d["totals"], d["last_week"]
    s = dt.datetime.strptime(d["start"], "%Y-%m-%dT%H:%M:%SZ")
    e = dt.datetime.strptime(d["end"], "%Y-%m-%dT%H:%M:%SZ") - dt.timedelta(days=1)
    span = f"{s.day} {s:%b} to {e.day} {e:%b %Y}"
    lines = [f"# {site}: week {d['week']} ({span})", ""]
    if not d["complete"]:
        lines += [f"_Week in progress, through {d['through'][:16].replace('T', ' ')} UTC._", ""]
    lines += [f"- **{t['relevant']}** new items scored medium or high ({_delta(t['relevant'], l['relevant'])}), "
              f"**{t['high']}** of them high; {t['items']} new items in all",
              f"- Among them {_ago_word(t['papers'], 'paper')}, {_ago_word(t['code'], 'piece')} of code and "
              f"{_ago_word(t['data'], 'dataset or model')}, from {_ago_word(t['contributors'], 'contributor')} "
              f"outside papers; {t['new_repos']} new repositories; {t['villa_merged']} villa pull requests merged"]
    up = [r for r in d["topics"] if r["change"] > 0][:3]
    if up:
        lines.append("- Busier topics: " + ", ".join(f"{r['topic']} ({r['this']}, +{r['change']})" for r in up))
    if d.get("previous_partial"):
        lines.append("- The week before is only partly inside the 30 days the radar keeps, so the comparison runs low.")
    lines += ["", "## Top items", ""]
    for i in d["top"]:
        who = f" ({(i.get('who_name') or i.get('who') or '').split(',')[0]})" if i.get("who") else ""
        lines.append(f"1. [{i['title']}]({i['url']}){who}, score {i['score']}")
    for g in d["lists"]:
        lines += ["", f"## {g['title']}", ""]
        lines += [f"- [{i['title']}]({i['url']})" for i in g["items"]]
    lines += ["", f"Scores are a triage aid, not a judgment. Full list: {base}/?since=7d#week"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- top picks

def top_picks(items: list[dict], name=lambda i: i, min_score: int = 40) -> list[dict]:
    """The best item of each kind of work in `items` (already filtered to a window and view), at or above
    min_score: one paper, one piece of code, one dataset or model, one community item. Fewer when a kind has none."""
    out = []
    for key, label, _ in GROUPS:
        best = max((i for i in items if group_of(i) == key and i["score"] >= min_score),
                   key=lambda i: (i["score"], i.get("date") or ""), default=None)
        if best:
            out.append({"group": key, "label": label, **slim(name(best), 220)})
    return out


# ---------------------------------------------------------------- item pages

def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def item_page(i: dict, sims: list[dict], *, site: str, base: str, labels: dict, image: str = "") -> str:
    """One item as a small standalone page: title, meta line, score with its band, summary, links, the closest
    items in meaning, and Open Graph tags so a pasted link shows a preview. `base` is the radar's public address."""
    url = f"{base}/item?id={urllib.parse.quote(i['id'], safe='')}"
    who = (i.get("who_name") or i.get("who") or "").strip()
    desc = (i.get("summary") or "")[:280]
    src = labels.get(i["source"], i["source"])
    date = (i.get("date") or "")[:10]
    meta = " · ".join(x for x in (src, i.get("kind"), date, who[:80], i.get("category")) if x)
    topics = "".join(f'<span class="tag">{_e(t)}</span>' for t in i.get("topics") or [])
    links = [f'<a class="btn primary" href="{_e(i["url"])}" rel="noopener">Open the source</a>']
    for k, lab in (("pdf", "PDF"), ("hf_url", "Hugging Face papers"), ("doi_url", "DOI")):
        if i.get(k):
            links.append(f'<a class="btn" href="{_e(i[k])}" rel="noopener">{lab}</a>')
    for u in (i.get("code") or [])[:3]:
        links.append(f'<a class="btn" href="{_e(u)}" rel="noopener">Code</a>')
    near = "".join(
        f'<li><a href="{_e(base)}/item?id={urllib.parse.quote(s["id"], safe="")}">{_e(s["title"])}</a>'
        f'<span>{_e(labels.get(s["source"], s["source"]))} · score {_e(s.get("score"))}</span></li>' for s in sims[:6])
    band = i.get("band") or "low"
    og_img = f'<meta property="og:image" content="{_e(image)}">\n<meta name="twitter:image" content="{_e(image)}">' if image else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(i['title'])} · {_e(site)}</title>
<meta name="description" content="{_e(desc)}">
<link rel="canonical" href="{_e(url)}">
<meta property="og:type" content="article"><meta property="og:site_name" content="{_e(site)}">
<meta property="og:title" content="{_e(i['title'])}"><meta property="og:description" content="{_e(meta)}. Score {_e(i.get('score'))}. {_e(desc)}">
<meta property="og:url" content="{_e(url)}"><meta name="twitter:card" content="summary_large_image">
{og_img}
<style>
:root{{--bg:#f6f4ef;--card:#fff;--ink:#1d2330;--muted:#5b6475;--line:#e3dfd6;--a:#3d6fd1;--o:#e08a3c;--hi:#1c5cab;--me:#e08a3c;--lo:#9aa3b2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#12151c;--card:#1a1f29;--ink:#e8ebf1;--muted:#a3abba;--line:#2b3240;--a:#7aa2f0}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Inter,sans-serif}}
main{{max-width:46rem;margin:0 auto;padding:2rem 1.25rem 3rem}}a{{color:var(--a)}}
.top{{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin-bottom:1.5rem;font-weight:600}}
.top a{{text-decoration:none;color:var(--ink)}}.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:1.5rem}}
h1{{font:700 1.75rem/1.25 Fraunces,Georgia,serif;margin:.25rem 0 .75rem;overflow-wrap:anywhere}}
.meta{{color:var(--muted);font-size:.9rem}}.score{{display:inline-flex;gap:.5rem;align-items:center;font-weight:700;margin:.75rem 0}}
.score i{{width:.75rem;height:.75rem;border-radius:50%;background:var(--lo)}}.score.high i{{background:var(--hi)}}.score.medium i{{background:var(--me)}}
.tag{{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:.1rem .6rem;margin:0 .35rem .35rem 0;font-size:.8rem;color:var(--muted)}}
.btn{{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:.5rem .9rem;margin:.25rem .4rem .25rem 0;text-decoration:none;color:var(--ink);font-weight:600;font-size:.9rem}}
.btn.primary{{background:var(--a);border-color:var(--a);color:#fff}}h2{{font-size:1rem;margin:1.75rem 0 .5rem}}
ul{{list-style:none;padding:0;margin:0}}li{{padding:.6rem 0;border-top:1px solid var(--line)}}li span{{display:block;color:var(--muted);font-size:.82rem}}
.foot{{color:var(--muted);font-size:.8rem;margin-top:2rem}}
</style></head>
<body><main>
<div class="top"><a href="{_e(base)}/">{_e(site)}</a><a href="{_e(base)}/?since=7d">See this week</a></div>
<article class="card">
<div class="meta">{_e(meta)}</div>
<h1>{_e(i['title'])}</h1>
<div class="score {_e(band)}"><i></i>Score {_e(i.get('score'))} of 100 ({_e(band)})</div>
<div>{topics}</div>
{f'<p>{_e(i.get("summary"))}</p>' if i.get("summary") else ''}
<div>{''.join(links)}</div>
</article>
{f'<h2>Closest in meaning</h2><ul>{near}</ul>' if near else ''}
<p class="foot">Found by {_e(site)} {_e((i.get('first_seen') or '')[:10])}. The title, summary and links belong to the
source; the score is a triage aid, not a judgment.</p>
</main></body></html>"""
