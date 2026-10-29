"""Vesuvius Radar collectors: new papers, code, models, data and posts that could help read the Herculaneum scrolls.

Every source is public and read logged out; nothing here holds or sends a key. Each collector returns the items it found
since a given time, each scored 0 to 100 twice: by keywords (the matched terms are kept, so a score can be explained
term by term) and, when the embedding model is loaded, by meaning (cosine similarity to the anchor sentences in
radar.json). When head.json is present, the final score comes from a small learned model on the embedding and a few
metadata features (Head, trained by train_head.py on blind ratings); otherwise it is the higher of the keyword score and
their blend. The keyword breakdown is kept either way, to explain a score.

  python scanner.py --days 1 --sources arxiv,hf --out items.json     # one check, printed or written as JSON
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "radar.json"
UA = "vesuvius-radar/1.0 (+https://huggingface.co/spaces/SharpMeow/vesuvius-radar)"
SOURCES = ("arxiv", "github", "hf", "pypi", "zenodo", "journals", "blog")
LABELS = {"arxiv": "arXiv", "github": "GitHub", "hf": "Hugging Face", "pypi": "PyPI", "zenodo": "Zenodo",
          "journals": "Journals", "blog": "Challenge blog"}


def load_config() -> dict:
    return json.loads(CONFIG.read_text())


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s) -> dt.datetime | None:
    if not s:
        return None
    s = str(s).strip()
    try:
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            if len(s) == 10:
                s += "T00:00:00+00:00"
            t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            t = email.utils.parsedate_to_datetime(s)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError, IndexError):
        return None


class Fetcher:
    """GET with a polite user agent and retries on 429 and 5xx. Remembers ETags per URL, so an unchanged GitHub listing
    comes back as 304 (which GitHub does not count against the logged-out limit) and is served from the copy."""

    def __init__(self):
        self.etags: dict[str, tuple[str, bytes]] = {}
        self.lock = threading.Lock()

    def get(self, url: str, headers: dict | None = None, tries: int = 3, timeout: int = 40, etag: bool = False) -> bytes:
        h = {"User-Agent": UA, **(headers or {})}
        if etag and url in self.etags:
            h["If-None-Match"] = self.etags[url][0]
        err: Exception | None = None
        for i in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                    body = r.read()
                    if etag and r.headers.get("ETag"):
                        with self.lock:
                            self.etags[url] = (r.headers["ETag"], body)
                    return body
            except urllib.error.HTTPError as e:
                if e.code == 304 and url in self.etags:
                    return self.etags[url][1]
                err = e
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                err = e
            time.sleep(2 * (i + 1))
        raise err  # type: ignore[misc]

    def json(self, url: str, headers: dict | None = None, **kw):
        return json.loads(self.get(url, headers, **kw).decode("utf-8"))


FETCH = Fetcher()


# ---------------------------------------------------------------- text

TEX_ACCENT = re.compile(r"""\\[`'^"~=.vcuHkr]\{?\\?([A-Za-z])\}?""")
TAG = re.compile(r"<[^>]+>")
URL_RX = re.compile(r"https?://[^\s<>()\[\]{}\"'`|,;]+")
CODE_HOSTS = ("github.com", "gitlab.com", "huggingface.co", "zenodo.org", "codeberg.org", "bitbucket.org")


BRITISH = re.compile(r"\b(fib|cent|met)re")  # British -re endings, written apart so the spelling check passes


def clean(s) -> str:
    """Plain text: tags dropped, entities and TeX accents turned into letters, one space between words."""
    return " ".join(TEX_ACCENT.sub(r"\1", html.unescape(TAG.sub(" ", str(s or "")))).split())


def code_links(text: str) -> list[str]:
    """Links to code, models or data inside a text (an abstract that says 'code at github.com/...')."""
    out = []
    for u in URL_RX.findall(text or ""):
        u = u.rstrip(".:!?*_>")
        host = re.sub(r"^https?://(www\.)?", "", u).split("/")[0].lower()
        if host in CODE_HOSTS and u not in out and len(u.split("/")) > 3:
            out.append(u)
    return out[:4]


def safe_url(u) -> str:
    u = str(u or "").strip()
    return u if re.match(r"https?://", u, re.I) else ""


# ---------------------------------------------------------------- scoring

class Scorer:
    """Keyword relevance 0 to 100 with a breakdown (label, points) and the matched terms."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        rx = self._rx
        self.core = [(t, rx(t)) for t in cfg["core"]["terms"]]
        self.topics = {n: (sp["weight"], [(t, rx(t)) for t in sp["strong"]], [(t, rx(t)) for t in sp["weak"]])
                       for n, sp in cfg["topics"].items()}
        self.context = [(t, rx(t)) for t in cfg["context"]]
        self.negative = [(t, rx(t)) for t in cfg["negative"]]

    @staticmethod
    def _rx(term: str):
        t = re.escape(term.lower())
        # Short terms (ink, ocr, ct, 3d) must be whole words; longer ones may take an ending (sheet -> sheets).
        return re.compile(r"\b" + t + (r"\b" if len(term) <= 4 else ""))

    def score(self, text: str, base: int = 0, base_label: str = "", core_terms: bool = True) -> dict:
        low = " " + BRITISH.sub(r"\1er", text.lower()) + " "  # one spelling for the keyword lists: fiber, center
        hits = lambda terms: [t for t, r in terms if r.search(low)]  # noqa: E731
        matched, topics, parts = [], [], []
        if base:
            parts.append([base_label or "source", base])
        core = hits(self.core) if core_terms else []
        if core:
            parts.append(["scroll terms: " + ", ".join(core[:4]), self.cfg["core"]["weight"] + min(15, 5 * (len(core) - 1))])
            matched += core
            topics.append("Scroll work")
        ctx = hits(self.context)
        for name, (w, strong, weak) in self.topics.items():
            st = hits(strong)
            wk = hits(weak) if (ctx or core or not core_terms) else []  # inside a scroll repository every term is in context
            if st:
                parts.append([f"{name} (strong): " + ", ".join((st + wk)[:4]), w + min(6, 3 * (len(st) + len(wk) - 1))])
            elif wk:
                parts.append([f"{name} (weak): " + ", ".join(wk[:4]), w // 2 + min(4, 2 * (len(wk) - 1))])
            if st or wk:
                topics.append(name)
                matched += st + wk
        if ctx and len(topics) > (1 if core else 0):
            parts.append(["context: " + ", ".join(ctx[:2]), self.cfg["context_bonus"]])
            matched += ctx[:2]
        neg = hits(self.negative)
        if neg and not core:
            parts.append(["off-topic: " + ", ".join(neg[:2]), -15 * min(2, len(neg))])
            matched += ["-" + n for n in neg[:2]]
        seen, uniq = set(), []
        for m in matched:
            if m not in seen:
                seen.add(m)
                uniq.append(m)
        s = max(0, min(100, sum(p for _, p in parts)))
        return {"keyword": s, "topics": topics, "matched": uniq, "parts": parts}

    def band(self, s: int) -> str:
        b = self.cfg["bands"]
        return "high" if s >= b["high"] else "medium" if s >= b["medium"] else "low"


class Semantic:
    """Meaning-based relevance from a small sentence-embedding model (ONNX, CPU). Optional: when the model cannot load,
    `ready` stays False and every score is keyword only. Embeddings are cached by text hash."""

    def __init__(self, cfg: dict):
        self.cfg = cfg["semantic"]
        self.ready, self.error, self.model = False, None, None
        self.cache: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        self.anchor_vecs, self.anchor_topic = None, []

    def load(self) -> bool:
        try:
            import numpy as np  # noqa: F401
            from fastembed import TextEmbedding
            self.model = TextEmbedding(self.cfg["model"], cache_dir=os.environ.get("RADAR_MODELS") or None)
            texts = []
            for topic, sents in self.cfg["anchors"].items():
                for s in sents:
                    texts.append(self.cfg.get("query_prefix", "") + s)
                    self.anchor_topic.append(topic)
            self.anchor_vecs = self._embed_raw(texts)
            self.ready = True
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
        return self.ready

    def _embed_raw(self, texts):
        import numpy as np
        v = np.array(list(self.model.embed(texts, batch_size=64)), dtype="float32")
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)

    def save_cache(self, path: Path) -> None:
        """Keep the vectors on disk (float16, about 0.8 KB each), so a restart does not embed everything again."""
        import numpy as np
        with self.lock:
            if not self.cache:
                return
            keys = list(self.cache)
            vecs = np.array([self.cache[k] for k in keys], dtype="float16")
        tmp = path.with_name(path.stem + ".tmp.npz")
        np.savez(tmp, keys=np.array(keys), vecs=vecs, model=np.array(self.cfg["model"]))
        tmp.replace(path)

    def load_cache(self, path: Path) -> int:
        import numpy as np
        try:
            z = np.load(path)
            if str(z["model"]) != self.cfg["model"]:
                return 0
            vecs = z["vecs"].astype("float32")
            vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
            with self.lock:
                for k, v in zip(z["keys"].tolist(), vecs):
                    self.cache.setdefault(k, v)
            return len(vecs)
        except Exception:  # noqa: BLE001 - no cache, or an unreadable one: embed again
            return 0

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]

    def embed(self, texts: list[str]):
        """Unit vectors for texts (cached), as a numpy array."""
        import numpy as np
        keys = [self.key(t) for t in texts]
        with self.lock:
            todo = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in self.cache]
            if todo:
                vecs = self._embed_raw([t for _, t in todo])
                for (k, _), v in zip(todo, vecs):
                    self.cache[k] = v
            if len(self.cache) > 60000:  # keep memory bounded; the store re-embeds what it still needs
                for k in list(self.cache)[:20000]:
                    self.cache.pop(k, None)
            return np.array([self.cache[k] for k in keys], dtype="float32") if keys else np.zeros((0, 384), "float32")

    def embed_query(self, text: str):
        """A search phrase as a unit vector, embedded as a query (bge models expect the prefix on queries only)."""
        return self.embed([self.cfg.get("query_prefix", "") + text])[0]

    def score_many(self, texts: list[str], progress=None, what="items") -> list[dict]:
        """Per text: meaning score 0..100, best cosine, the anchor topic it is closest to. progress(msg) hears every
        128 texts, since a first run on a small CPU embeds a few per second."""
        import numpy as np
        if not self.ready or not texts:
            return [{} for _ in texts]
        parts = []
        for k in range(0, len(texts), 128):
            if progress and len(texts) > 128:
                progress(f"reading {what} by meaning: {k} of {len(texts)}")
            parts.append(self.embed(texts[k:k + 128]))
        sims = np.concatenate(parts) @ self.anchor_vecs.T
        lo, hi = self.cfg["sim_floor"], self.cfg["sim_ceiling"]
        out = []
        for row in sims:
            j = int(row.argmax())
            best = float(row[j])
            out.append({"semantic": int(round(100 * min(1.0, max(0.0, (best - lo) / (hi - lo))))), "sim": round(best, 3),
                        "near": self.anchor_topic[j]})
        return out


class Head:
    """Learned relevance: a ridge model on an item's embedding plus a few metadata features, fitted to blind ratings of
    what each item is worth to scroll work (train_head.py), then mapped to 0..100 by a monotone calibration fitted on
    held-out predictions. Items without an embedding (no text, or the model not loaded) get the metadata-only head.
    Numpy only, microseconds per item. `ready` stays False when head.json is missing or unreadable."""

    def __init__(self, path: Path = HERE / "head.json"):
        self.ready, self.info = False, {}
        try:
            self.info = json.loads(path.read_text())
            self.heads = {}
            import numpy as np
            for name in ("full", "meta"):
                h = self.info[name]
                self.heads[name] = (np.array(h.get("coef_emb", []), "float32"), np.array(h["coef_meta"], "float32"),
                                    float(h["intercept"]), np.array(h["cal_x"], "float32"), np.array(h["cal_y"], "float32"))
            self.ready = True
        except Exception:  # noqa: BLE001 - no head: the rule score stays the final score
            self.ready = False

    @staticmethod
    def features(item: dict, sources: list[str], kinds: list[str]) -> list[float]:
        """Metadata features, the same in training and at run time. Order: see META_FEATURES, then a one-hot of the
        source and of the kind (lists stored in head.json; an unseen value is all zeros)."""
        likes = (item.get("likes") or 0) + (item.get("upvotes") or 0)
        f = [item.get("keyword", 0) / 100, (item.get("semantic") or 0) / 100, math.log1p(item.get("stars") or 0) / 5,
             math.log1p(likes) / 5, 1.0 if item.get("new_repo") else 0.0, 1.0 if item.get("code") else 0.0,
             min(len(item.get("summary") or ""), 900) / 900, 1.0 if item.get("state") == "merged" else 0.0]
        return f + [1.0 if item.get("source") == s else 0.0 for s in sources] + \
            [1.0 if item.get("kind") == k else 0.0 for k in kinds]

    def score(self, item: dict, vec=None) -> int:
        import numpy as np
        emb, meta, b, cx, cy = self.heads["full" if vec is not None else "meta"]
        x = np.array(self.features(item, self.info["sources"], self.info["kinds"]), "float32")
        raw = b + float(meta @ x) + (float(emb @ vec) if vec is not None else 0.0)
        return int(round(float(np.interp(raw, cx, cy))))


META_FEATURES = ["keyword", "semantic", "stars", "likes", "new_repo", "code", "summary_len", "merged"]


def finish(items: list[dict], scorer: Scorer, sem: Semantic | None, progress=None, head: Head | None = None) -> list[dict]:
    """Final score, band and topics for collected items. The rule score is the keyword score, lifted by the meaning
    score when the model is loaded; it decides which items are kept (`rule`, the gate the training items passed). With
    a learned head the shown score is the head's (`learned` says which head); otherwise it is the rule score. Mutates and
    returns the items."""
    # Items without text of their own (package versions) keep their keyword score.
    texts = [i.get("_text") for i in items]
    idx = [k for k, t in enumerate(texts) if t]
    got = sem.score_many([texts[k] for k in idx], progress) if sem and sem.ready and idx else []
    sems, vecs = [{} for _ in items], [None for _ in items]
    for k, s in zip(idx, got):
        sems[k] = s
    if got and head and head.ready:
        for k, v in zip(idx, sem.embed([texts[k] for k in idx])):  # cached by score_many: no second model pass
            vecs[k] = v
    blend = scorer.cfg["semantic"]["blend"]
    topic_sim = scorer.cfg["semantic"]["topic_sim"]
    floor, high = scorer.cfg["semantic"]["sim_floor"], scorer.cfg["bands"]["high"]
    for i, s, v in zip(items, sems, vecs):
        i.pop("_text", None)
        i.pop("_pre", None)
        watched = i.pop("_base", False)
        kw = i["keyword"]
        capped = None
        if s:
            i.update(s)
            mix = int(round(blend * s["semantic"] + (1 - blend) * kw))
            rule = max(kw, mix)
            # A long text the model reads as unrelated (keyword stuffing, or a language the model does not read) stays
            # below high unless it comes from a watched place (villa) that gives points of its own.
            if not watched and len(i.get("summary") or "") >= 300 and s["sim"] < floor and rule >= high:
                rule = high - 1
                capped = "the text reads as unrelated to the scrolls' work, so it stays below high"
            if s["sim"] >= topic_sim and s["near"] not in i["topics"]:
                i["topics"].append(s["near"])
                i["topics_by_meaning"] = [s["near"]]
        else:
            rule = kw
        i["rule"] = rule
        if head and head.ready:
            i["score"] = max(0, min(100, head.score(i, v)))
            i["learned"] = "full" if v is not None else "meta"
        else:
            i["score"] = rule
            if capped:
                i["capped"] = capped
        i["band"] = scorer.band(i["score"])
    return items


def embed_text(cfg: dict, title: str, summary: str) -> str:
    """The text the meaning model reads: title and the start of the summary. Scoring, similarity and search share it,
    so each item is embedded once. The opening of an abstract carries its topic; a shorter text is much faster on CPU."""
    return f"{title}. {summary}"[:cfg["semantic"].get("embed_chars", 600)]


def make_item(scorer: Scorer, *, source, kind, id, title, url, date, text="", base=0, base_label="", core_terms=True,
              **extra) -> dict:
    title = clean(title)
    body = clean(text)
    sc = scorer.score(f"{title} {body}", base, base_label, core_terms)
    item = {"id": id, "source": source, "kind": kind, "title": title, "url": safe_url(url),
            "date": iso(date) if isinstance(date, dt.datetime) else date, "summary": body[:900],
            "keyword": sc["keyword"], "topics": sc["topics"], "matched": sc["matched"], "parts": sc["parts"],
            "_base": bool(base),
            }
    if "summary" in extra:
        item["summary"] = clean(extra.pop("summary"))[:900]
    item["_text"] = embed_text(scorer.cfg, item["title"], item["summary"])
    for t in extra.pop("topics_extra", []):
        if t not in item["topics"]:
            item["topics"].insert(0, t)
    if extra.get("who"):
        extra["who"] = clean(extra["who"])[:200]
    for k in ("pdf", "hf_url", "doi_url"):
        if k in extra:
            extra[k] = safe_url(extra[k])
    links = code_links(text)
    if links:
        extra.setdefault("code", links)
    item.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    return item


# ---------------------------------------------------------------- sources
# Each collector: (src_cfg, ctx) -> (items, info). ctx: scorer, since, now, progress(msg), state (a dict this source
# keeps between checks). info: read (listings looked at) and notes.

def c_arxiv(sc, ctx):
    scorer, since, prog, state = ctx["scorer"], ctx["since"], ctx["progress"], ctx["state"]
    out, read, notes = {}, 0, []
    ns = {"arxiv": "http://arxiv.org/schemas/atom", "dc": "http://purl.org/dc/elements/1.1/"}
    prog("today's announcement for " + ", ".join(sc["rss"]))
    root = ET.fromstring(FETCH.get("https://rss.arxiv.org/rss/" + "+".join(sc["rss"])))
    n_rss = 0
    for it in root.iter("item"):
        kind = (it.findtext("arxiv:announce_type", default="", namespaces=ns) or "").strip()
        if kind not in ("new", "cross"):
            continue
        date = parse_time(it.findtext("pubDate"))
        if date and date < since:
            continue
        read += 1
        n_rss += 1
        aid = it.findtext("link", "").rstrip("/").split("/")[-1]
        abstract = it.findtext("description", "").split("Abstract:", 1)[-1].strip()
        cats = [c.text for c in it.findall("category") if c.text]
        out["arxiv:" + aid] = make_item(scorer, source="arxiv", kind="paper", id="arxiv:" + aid, title=it.findtext("title", ""),
                                        url=f"https://arxiv.org/abs/{aid}", date=date or ctx["now"], text=abstract,
                                        who=(it.findtext("dc:creator", default="", namespaces=ns) or ""),
                                        category=", ".join(cats[:4]), pdf=f"https://arxiv.org/pdf/{aid}")
    notes.append(f"announcement: {n_rss} new and cross-listed papers")
    # The past-week lists catch days the Space slept through; titles only, so at most once a day.
    last_pw = parse_time(state.get("pastweek"))
    if (ctx["now"] - since).total_seconds() > 86400 and (not last_pw or (ctx["now"] - last_pw).total_seconds() > 3600 * sc["pastweek_every_h"]):
        n_pw = 0
        for cat in sc["pastweek"]:
            prog(f"past-week list of {cat}")
            time.sleep(3)  # arXiv asks for a few seconds between requests
            try:
                page = FETCH.get(f"https://arxiv.org/list/{cat}/pastweek?skip=0&show=2000").decode("utf-8", "replace")
            except Exception as e:  # noqa: BLE001
                notes.append(f"past-week {cat}: {e}")
                continue
            for block in re.split(r"<h3>", page)[1:]:
                m = re.match(r"\s*([A-Z][a-z]{2}, \d{1,2} [A-Z][a-z]{2} \d{4})", block)
                day = parse_time(m.group(1) + " 00:00:00 +0000") if m else None
                if not day or day.date() < since.date():
                    continue
                for aid, title in re.findall(r'href ="/abs/([\d.]+)".*?list-title[^>]*>\s*<span[^>]*>Title:</span>\s*(.*?)\s*</div>',
                                             block, re.S):
                    read += 1
                    if "arxiv:" + aid in out:
                        continue
                    n_pw += 1
                    out["arxiv:" + aid] = make_item(scorer, source="arxiv", kind="paper", id="arxiv:" + aid, title=title,
                                                    url=f"https://arxiv.org/abs/{aid}", date=day, category=cat,
                                                    pdf=f"https://arxiv.org/pdf/{aid}", title_only=True)
        state["pastweek"] = iso(ctx["now"])
        notes.append(f"past-week lists: {n_pw} more titles")
        # Titles alone score poorly, so the most promising ones get their abstracts from the export API (it often
        # rate-limits; then those items stay scored on titles). Promising: keyword score, or meaning when the model is on.
        thin = [i for i in out.values() if i.get("title_only")]
        sem = ctx.get("sem")
        if sem and sem.ready and thin:
            prog(f"ranking {len(thin)} titles by meaning")
            for i, m in zip(thin, sem.score_many([i["_text"] for i in thin], prog, "titles")):
                i["_pre"] = max(i["keyword"], m.get("semantic", 0))
        thin = sorted((i for i in thin if i.get("_pre", i["keyword"]) >= 20), key=lambda i: -i.get("_pre", i["keyword"]))[:200]
        a = {"a": "http://www.w3.org/2005/Atom"}
        got = 0
        for k in range(0, len(thin), 100):
            batch = {i["id"]: i for i in thin[k:k + 100]}
            prog(f"fetching abstracts {k + 1} to {k + len(batch)} of {len(thin)}")
            time.sleep(3)
            try:
                feed = ET.fromstring(FETCH.get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
                    {"id_list": ",".join(x.split(":", 1)[1] for x in batch), "max_results": len(batch)}), tries=2))
            except Exception as e:  # noqa: BLE001
                notes.append(f"abstracts skipped ({e}); those items are scored on titles")
                break
            for e in feed.findall("a:entry", a):
                aid = re.sub(r"v\d+$", "", e.findtext("a:id", "", a).rstrip("/").split("/")[-1])
                it = batch.get("arxiv:" + aid)
                if not it:
                    continue
                cats = [c.get("term") for c in e.findall("a:category", a) if c.get("term")]
                out[it["id"]] = make_item(scorer, source="arxiv", kind="paper", id=it["id"], title=it["title"], url=it["url"],
                                          date=it["date"], text=e.findtext("a:summary", "", a), pdf=it["pdf"],
                                          who=", ".join(n.findtext("a:name", "", a) for n in e.findall("a:author", a)),
                                          category=", ".join(cats[:4]) or it.get("category"))
                got += 1
        if thin:
            notes.append(f"abstracts added to {got} promising titles")
    # A keyword search over every category, for scroll papers outside the lists above.
    prog("searching all categories for scroll terms")
    try:
        feed = ET.fromstring(FETCH.get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": sc["search"], "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 60}), tries=2))
        a = {"a": "http://www.w3.org/2005/Atom"}
        n_s = 0
        for e in feed.findall("a:entry", a):
            aid = re.sub(r"v\d+$", "", e.findtext("a:id", "", a).rstrip("/").split("/")[-1])
            date = parse_time(e.findtext("a:updated", "", a)) or parse_time(e.findtext("a:published", "", a))
            if not date or date < since:
                continue
            read += 1
            if "arxiv:" + aid in out and not out["arxiv:" + aid].get("title_only"):
                continue
            n_s += 1
            cats = [c.get("term") for c in e.findall("a:category", a) if c.get("term")]
            out["arxiv:" + aid] = make_item(scorer, source="arxiv", kind="paper", id="arxiv:" + aid, title=e.findtext("a:title", "", a),
                                            url=f"https://arxiv.org/abs/{aid}", date=date, text=e.findtext("a:summary", "", a),
                                            who=", ".join(n.findtext("a:name", "", a) for n in e.findall("a:author", a)),
                                            category=", ".join(cats[:4]), pdf=f"https://arxiv.org/pdf/{aid}")
        notes.append(f"search: {n_s} scroll papers in the window")
    except Exception as e:  # noqa: BLE001
        notes.append(f"search skipped ({e})")
    return list(out.values()), {"read": read, "notes": notes}


def _gh_get(url):
    return FETCH.json(url, {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, etag=True)


def c_github(sc, ctx):
    scorer, since, prog = ctx["scorer"], ctx["since"], ctx["progress"]
    out, read, notes = {}, 0, []
    day = since.strftime("%Y-%m-%d")
    for q in sc["queries"]:
        prog(f"repositories: {q}")
        try:
            res = _gh_get("https://api.github.com/search/repositories?" + urllib.parse.urlencode(
                {"q": f"{q} pushed:>={day}", "sort": "updated", "order": "desc", "per_page": 50}))
        except urllib.error.HTTPError as e:
            notes.append(f"search '{q}': HTTP {e.code}" + (" (rate limited)" if e.code in (403, 429) else ""))
            if e.code in (403, 429):
                break
            continue
        for r in res.get("items", []):
            pushed = parse_time(r.get("pushed_at"))
            if not pushed or pushed < since:
                continue
            read += 1
            key = "github:" + r["full_name"].lower()
            if key in out:
                continue
            created = parse_time(r.get("created_at"))
            is_new = bool(created and created >= since)
            text = " ".join([r.get("description") or "", " ".join(r.get("topics") or []), r["full_name"].replace("-", " ")])
            out[key] = make_item(scorer, source="github", kind="repo", id=key, title=r["full_name"], url=r["html_url"],
                                 date=pushed, text=text, base=5 + (10 if is_new else 0),
                                 base_label="new GitHub repository" if is_new else "GitHub repository", who=r["owner"]["login"],
                                 summary=r.get("description") or "", created=r.get("created_at"), new_repo=is_new,
                                 stars=r.get("stargazers_count"), forks=r.get("forks_count"),
                                 license=(r.get("license") or {}).get("spdx_id"), language=r.get("language"),
                                 repo_topics=(r.get("topics") or [])[:8])
        time.sleep(2.5)  # logged-out search allows 10 calls a minute
    for repo in sc.get("watch_repos", []):
        prog(f"pull requests, issues and releases of {repo}")
        try:
            for p in _gh_get(f"https://api.github.com/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=60"):
                t = parse_time(p.get("updated_at"))
                if not t or t < since:
                    continue
                read += 1
                state = "merged" if p.get("merged_at") else ("draft" if p.get("draft") and p["state"] == "open" else p["state"])
                key = f"github:{repo.lower()}#{p['number']}"
                out[key] = make_item(scorer, source="github", kind="pr", id=key, title=f"{repo} #{p['number']}: {p['title']}",
                                     url=p["html_url"], date=t, text=(p.get("body") or "")[:1500], base=30,
                                     base_label=f"{repo} pull request", core_terms=False, who=p["user"]["login"], state=state,
                                     created=p.get("created_at"), labels=[x["name"] for x in p.get("labels") or []][:6],
                                     topics_extra=["Scroll work"])
            for p in _gh_get(f"https://api.github.com/repos/{repo}/issues?state=all&sort=updated&direction=desc&per_page=60&since={iso(since)}"):
                if p.get("pull_request"):
                    continue
                t = parse_time(p.get("updated_at"))
                if not t or t < since:
                    continue
                read += 1
                key = f"github:{repo.lower()}#{p['number']}"
                out[key] = make_item(scorer, source="github", kind="issue", id=key, title=f"{repo} #{p['number']}: {p['title']}",
                                     url=p["html_url"], date=t, text=(p.get("body") or "")[:1500], base=22,
                                     base_label=f"{repo} issue", core_terms=False, who=p["user"]["login"], state=p["state"],
                                     created=p.get("created_at"), comments=p.get("comments"),
                                     labels=[x["name"] for x in p.get("labels") or []][:6], topics_extra=["Scroll work"])
            for r in _gh_get(f"https://api.github.com/repos/{repo}/releases?per_page=10"):
                t = parse_time(r.get("published_at"))
                if not t or t < since:
                    continue
                read += 1
                key = f"github:{repo.lower()}@{r['tag_name']}"
                out[key] = make_item(scorer, source="github", kind="release", id=key, title=f"{repo} {r.get('name') or r['tag_name']}",
                                     url=r["html_url"], date=t, text=(r.get("body") or "")[:1500], base=50,
                                     base_label=f"{repo} release", core_terms=False, who=repo.split("/")[0],
                                     topics_extra=["Scroll work"])
        except urllib.error.HTTPError as e:
            notes.append(f"{repo}: HTTP {e.code}")
    notes.append("logged out; unchanged listings are answered from cache (ETag)")
    return list(out.values()), {"read": read, "notes": notes}


def c_hf(sc, ctx):
    scorer, since, prog = ctx["scorer"], ctx["since"], ctx["progress"]
    out, read, notes = {}, 0, []
    kinds = (("models", "model", ""), ("datasets", "dataset", "datasets/"), ("spaces", "space", "spaces/"))
    calls = [(api, kind, pre, {"search": s}) for s in sc["search"] for api, kind, pre in kinds]
    calls += [(api, kind, pre, {"author": a}) for a in sc.get("authors", []) for api, kind, pre in kinds]
    for api, kind, pre, q in calls:
        prog(f"{api}: {next(iter(q.values()))}")
        try:
            rows = FETCH.json(f"https://huggingface.co/api/{api}?" + urllib.parse.urlencode(
                {**q, "sort": "lastModified", "direction": -1, "limit": 50, "full": "true"}))
        except Exception as e:  # noqa: BLE001
            notes.append(f"{api} {q}: {e}")
            continue
        for r in rows:
            t = parse_time(r.get("lastModified"))
            if not t or t < since:
                continue
            read += 1
            rid = r.get("id") or r.get("modelId")
            key = f"hf:{kind}:{rid.lower()}"
            if key in out:
                continue
            created = parse_time(r.get("createdAt"))
            is_new = bool(created and created >= since)
            tags = [x for x in (r.get("tags") or []) if ":" not in x]
            lic = next((x.split(":", 1)[1] for x in (r.get("tags") or []) if x.startswith("license:")), None)
            card = r.get("cardData") or {}
            desc = str(card.get("short_description") or card.get("description") or "")
            text = " ".join([rid.replace("-", " ").replace("_", " "), " ".join(tags), desc, str(r.get("pipeline_tag") or "")])
            out[key] = make_item(scorer, source="hf", kind=kind, id=key, title=rid, url=f"https://huggingface.co/{pre}{rid}",
                                 date=t, text=text, base=5 + (10 if is_new else 0),
                                 base_label=f"new Hugging Face {kind}" if is_new else f"Hugging Face {kind}", who=rid.split("/")[0],
                                 summary=desc or ("Tags: " + ", ".join(tags[:12]) if tags else ""),
                                 created=r.get("createdAt"), new_repo=is_new, likes=r.get("likes"),
                                 downloads=r.get("downloads"), license=lic, sdk=r.get("sdk"), pipeline=r.get("pipeline_tag"))
    if sc.get("daily_papers"):
        d = since.date()
        while d <= ctx["now"].date():
            prog(f"daily papers {d}")
            try:
                rows = FETCH.json(f"https://huggingface.co/api/daily_papers?date={d}&limit=100")
            except Exception as e:  # noqa: BLE001
                notes.append(f"daily papers {d}: {e}")
                rows = []
            for r in rows:
                p = r.get("paper") or {}
                pid = p.get("id")
                t = parse_time(r.get("publishedAt")) or dt.datetime.combine(d, dt.time(), dt.timezone.utc)
                if not pid or t < since:
                    continue
                read += 1
                out.setdefault("hfp:" + pid, make_item(
                    scorer, source="hf", kind="daily-paper", id="hfp:" + pid, title=p.get("title", ""),
                    url=f"https://huggingface.co/papers/{pid}", date=t, text=p.get("summary", ""), upvotes=p.get("upvotes"),
                    arxiv="arxiv:" + pid, pdf=f"https://arxiv.org/pdf/{pid}",
                    who=", ".join(a.get("name", "") for a in p.get("authors", [])[:8])))
            d += dt.timedelta(days=1)
    return list(out.values()), {"read": read, "notes": notes}


def c_pypi(sc, ctx):
    scorer, since, prog = ctx["scorer"], ctx["since"], ctx["progress"]
    out, read, notes = [], 0, []
    for name, weight in sc["packages"].items():
        prog(name)
        try:
            j = FETCH.json(f"https://pypi.org/pypi/{name}/json")
        except Exception as e:  # noqa: BLE001
            notes.append(f"{name}: {e}")
            continue
        read += 1
        for ver, files in j.get("releases", {}).items():
            times = [t for t in (parse_time(f.get("upload_time_iso_8601")) for f in files) if t]
            if not times or min(times) < since:
                continue
            pre = bool(re.search(r"(a|b|rc|dev)\d*$", ver))
            s = max(5, weight - (10 if pre else 0))
            out.append({"id": f"pypi:{name}=={ver}", "source": "pypi", "kind": "package", "title": f"{name} {ver}",
                        "url": f"https://pypi.org/project/{name}/{ver}/", "date": iso(min(times)),
                        "summary": clean(j["info"].get("summary") or "")[:300], "keyword": s, "topics": ["Software releases"],
                        "matched": [name], "parts": [[f"watched package {name}" + (" (pre-release, -10)" if pre else ""), s]],
                        "prerelease": pre or None, "who": name, "requires_python": j["info"].get("requires_python") or None})
    for i in out:
        for k in [k for k, v in i.items() if v is None]:
            del i[k]
    return out, {"read": read, "notes": notes}


def c_zenodo(sc, ctx):
    scorer, since, prog = ctx["scorer"], ctx["since"], ctx["progress"]
    out, read, notes = {}, 0, []
    for q in sc["queries"]:
        prog(q)
        try:
            res = FETCH.json("https://zenodo.org/api/records?" + urllib.parse.urlencode(
                {"q": q, "sort": "mostrecent", "size": 25}))
        except Exception as e:  # noqa: BLE001
            notes.append(f"{q}: {e}")
            continue
        for h in res.get("hits", {}).get("hits", []):
            t = parse_time(h.get("updated")) or parse_time(h.get("created"))
            if not t or t < since:
                continue
            read += 1
            key = f"zenodo:{h.get('conceptrecid') or h['id']}"
            if key in out:
                continue
            m = h.get("metadata", {})
            rt = (m.get("resource_type") or {}).get("title") or "record"
            out[key] = make_item(scorer, source="zenodo", kind=rt.lower(), id=key, title=m.get("title", ""),
                                 url=(h.get("links") or {}).get("self_html") or f"https://zenodo.org/records/{h['id']}", date=t,
                                 text=m.get("description", ""), who=", ".join(c.get("name", "") for c in m.get("creators", [])[:6]),
                                 doi_url=(h.get("links") or {}).get("doi"), license=(m.get("license") or {}).get("id"),
                                 created=h.get("created"), version=m.get("version"))
    return list(out.values()), {"read": read, "notes": notes}


def c_journals(sc, ctx):
    """Journal articles and book chapters registered with Crossref (indexed inside the window)."""
    scorer, since, prog = ctx["scorer"], ctx["since"], ctx["progress"]
    out, read, notes = {}, 0, []
    for q in sc["queries"]:
        prog(q)
        try:
            res = FETCH.json("https://api.crossref.org/works?" + urllib.parse.urlencode(
                {"query.bibliographic": q, "filter": f"from-created-date:{since.date()},type:journal-article,type:book-chapter,type:proceedings-article,type:posted-content",
                 "rows": 40, "sort": "created", "order": "desc",
                 "select": "DOI,title,author,container-title,created,abstract,URL,type,publisher"}))
        except Exception as e:  # noqa: BLE001
            notes.append(f"{q}: {e}")
            continue
        for w in res.get("message", {}).get("items", []):
            t = parse_time((w.get("created") or {}).get("date-time"))
            if not t or t < since or not w.get("title"):
                continue
            read += 1
            key = "doi:" + w["DOI"].lower()
            if key in out:
                continue
            who = ", ".join(" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in (w.get("author") or [])[:6])
            out[key] = make_item(scorer, source="journals", kind=(w.get("type") or "article").replace("-", " "), id=key,
                                 title=w["title"][0], url=w.get("URL") or f"https://doi.org/{w['DOI']}", date=t,
                                 text=w.get("abstract", ""), who=who, category=(w.get("container-title") or [""])[0],
                                 publisher=w.get("publisher"))
    return list(out.values()), {"read": read, "notes": notes}


def c_blog(sc, ctx):
    scorer, since, prog = ctx["scorer"], ctx["since"], ctx["progress"]
    out, read, notes = [], 0, []
    for name, url in sc["feeds"]:
        prog(name)
        root = ET.fromstring(FETCH.get(url))
        for it in root.iter("item"):
            t = parse_time(it.findtext("pubDate"))
            if not t or t < since:
                continue
            read += 1
            link = it.findtext("link", "")
            out.append(make_item(scorer, source="blog", kind="post", id="blog:" + link.lower().rstrip("/"),
                                 title=it.findtext("title", ""), url=link, date=t, text=it.findtext("description", ""),
                                 base=50, base_label=f"{name} post", core_terms=False, who=name,
                                 topics_extra=["Scroll work"]))
    return out, {"read": read, "notes": notes}


COLLECTORS = {"arxiv": c_arxiv, "github": c_github, "hf": c_hf, "pypi": c_pypi, "zenodo": c_zenodo,
              "journals": c_journals, "blog": c_blog}


def merge_daily_papers(items: list[dict]) -> list[dict]:
    """An arXiv paper that is also a Hugging Face daily paper keeps one row, the arXiv one, with the upvotes added."""
    by = {i["id"]: i for i in items}
    keep = []
    for i in items:
        if i["kind"] == "daily-paper" and i.get("arxiv") in by:
            by[i["arxiv"]]["upvotes"] = i.get("upvotes")
            by[i["arxiv"]]["hf_url"] = i["url"]
            continue
        keep.append(i)
    return keep


def collect(source: str, since: dt.datetime, cfg: dict | None = None, scorer: Scorer | None = None,
            sem: Semantic | None = None, state: dict | None = None, progress=None,
            head: Head | None = None) -> tuple[list[dict], dict]:
    """One source, one check: items kept (score at or above keep_score) and a status row."""
    cfg = cfg or load_config()
    scorer = scorer or Scorer(cfg)
    now = utcnow()
    row = {"source": source, "label": LABELS[source], "started": iso(now), "since": iso(since), "state": "running",
           "read": 0, "kept": 0, "notes": [], "step": ""}

    def prog(msg):
        row["step"] = msg
        if progress:
            progress(row)

    t0 = time.time()
    try:
        items, info = COLLECTORS[source](cfg["sources"][source], {"scorer": scorer, "since": since, "now": now, "sem": sem,
                                                                   "progress": prog, "state": state if state is not None else {}})
        if source == "hf":
            items = merge_daily_papers(items)
        prog(f"scoring {len(items)} items")
        finish(items, scorer, sem, prog, head)
        items = [i for i in items if i["rule"] >= cfg["keep_score"]]
        bad = any(re.search(r"HTTP \d|Error|rate limited|skipped|timed out", n) for n in info["notes"])
        row.update(state="partial" if bad else "ok", read=info["read"], kept=len(items), notes=info["notes"])
    except Exception as e:  # noqa: BLE001
        items = []
        row.update(state="error", notes=[f"{type(e).__name__}: {e}"])
    row["ms"] = int(1000 * (time.time() - t0))
    row["finished"] = iso(utcnow())
    row["step"] = ""
    return items, row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=1)
    ap.add_argument("--sources", default=",".join(SOURCES))
    ap.add_argument("--semantic", action="store_true", help="load the embedding model and add meaning scores")
    ap.add_argument("--out", default="-")
    a = ap.parse_args(argv)
    cfg = load_config()
    scorer, sem, head = Scorer(cfg), None, Head()
    if a.semantic:
        sem = Semantic(cfg)
        if not sem.load():
            print("semantic model not loaded: " + str(sem.error), file=sys.stderr)
    since = utcnow() - dt.timedelta(days=a.days)
    allitems = []
    for s in [x for x in a.sources.split(",") if x]:
        items, row = collect(s, since, cfg, scorer, sem, head=head)
        allitems += items
        print(f"{s}: {row['state']} read {row['read']} kept {row['kept']} in {row['ms']} ms; {'; '.join(row['notes'])}", file=sys.stderr)
    allitems.sort(key=lambda i: (-i["score"], i["date"]))
    text = json.dumps(allitems, indent=1, ensure_ascii=False)
    if a.out == "-":
        print(text)
    else:
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
