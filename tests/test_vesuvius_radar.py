"""Vesuvius Radar Space (spaces/vesuvius-radar): scoring stays explainable, lookbacks and views filter as documented,
the API, feed and MCP server answer, and nothing private or secret is in the Space's files. Offline: no source is
fetched and the embedding model is not loaded."""

import datetime as dt
import email.utils
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "spaces" / "vesuvius-radar"
NAMES = ("scanner", "app", "radar_mcp")


def _load():
    """Import the Space's modules under their own names without disturbing other Spaces' modules of the same names
    (another Space may also have a scanner.py or app.py): swap sys.modules in, import, swap the old ones back."""
    saved = {n: sys.modules.pop(n) for n in NAMES if n in sys.modules}
    sys.path.insert(0, str(HERE))
    os.environ["RADAR_DATA"] = tempfile.mkdtemp(prefix="vradar-test-")
    os.environ["RADAR_COLLECT"] = "0"
    os.environ["RADAR_SEMANTIC"] = "0"
    try:
        sc = importlib.import_module("scanner")
        try:
            ap = importlib.import_module("app")
        except ImportError:  # fastapi not installed: the scanner tests still run
            ap = None
        return sc, ap
    finally:
        sys.path.remove(str(HERE))
        for n in NAMES:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


scanner, app = _load()
CFG = json.loads((HERE / "radar.json").read_text())


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class ScorerTest(unittest.TestCase):
    def setUp(self):
        self.s = scanner.Scorer(CFG)

    def test_scroll_terms_rank_high_and_parts_sum(self):
        r = self.s.score("Virtual unwrapping of Herculaneum papyrus from micro-CT volumes")
        self.assertGreaterEqual(r["keyword"], 60)
        self.assertIn("Scroll work", r["topics"])
        self.assertEqual(r["keyword"], max(0, min(100, sum(p for _, p in r["parts"]))))

    def test_weak_terms_need_context(self):
        bare = self.s.score("A compression method for chat transcripts")["keyword"]
        ctx = self.s.score("A lossless compression method for 3D CT volumes")
        self.assertEqual(bare, 0)
        self.assertGreater(ctx["keyword"], 0)
        self.assertIn("Compression and storage", ctx["topics"])

    def test_short_terms_are_whole_words(self):
        r = self.s.score("We think about linking blinking pinks")
        self.assertNotIn("ink", r["matched"])

    def test_negative_terms_take_points_off(self):
        plain = self.s.score("Deformable image registration of 3D volumes")["keyword"]
        llm = self.s.score("Deformable image registration of 3D volumes with a large language model")
        self.assertLess(llm["keyword"], plain)
        self.assertTrue(any(l.startswith("off-topic") for l, _ in llm["parts"]))

    def test_meaning_alone_cannot_reach_high(self):
        blend = CFG["semantic"]["blend"]
        self.assertLess(round(blend * 100), CFG["bands"]["high"])
        items = [{"keyword": 0, "topics": [], "_text": "x"}]

        class FakeSem:
            ready = True

            def score_many(self, texts, progress=None, what="items"):
                return [{"semantic": 100, "sim": 0.9, "near": "Ink and imaging"} for _ in texts]
        scanner.finish(items, self.s, FakeSem())
        self.assertEqual(items[0]["band"], "medium")
        self.assertIn("Ink and imaging", items[0]["topics"])
        self.assertNotIn("_text", items[0])

    def test_long_unrelated_text_stays_below_high_unless_watched(self):
        class FarSem:
            ready = True

            def score_many(self, texts, progress=None, what="items"):
                return [{"semantic": 0, "sim": 0.65, "near": "Scroll work"} for _ in texts]
        stuffed = "Herculaneum papyri papyrology palimpsest cultural heritage greek latin epigraphy 3d volume " * 6
        spam = scanner.make_item(self.s, source="zenodo", kind="preprint", id="z", title="Ipotesi", url="",
                                 date="2026-10-29T00:00:00Z", text=stuffed)
        villa = scanner.make_item(self.s, source="github", kind="pr", id="v", title="villa #1", url="",
                                  date="2026-10-29T00:00:00Z", text=stuffed, base=30, base_label="ScrollPrize/villa")
        self.assertGreaterEqual(spam["keyword"], 60)
        scanner.finish([spam, villa], self.s, FarSem())
        self.assertEqual((spam["score"], spam["band"]), (59, "medium"))
        self.assertIn("capped", spam)
        self.assertEqual(villa["band"], "high")
        self.assertNotIn("_base", spam)

    def test_items_without_text_keep_keyword_score(self):
        items = [{"keyword": 25, "topics": ["Software releases"]}]
        scanner.finish(items, self.s, None)
        self.assertEqual(items[0]["score"], 25)

    def test_scoring_and_similarity_embed_the_same_text(self):
        it = scanner.make_item(self.s, source="arxiv", kind="paper", id="a", title="T", url="", date="2026-10-29T00:00:00Z",
                               text="word " * 400)
        self.assertEqual(it["_text"], scanner.embed_text(CFG, it["title"], it["summary"]))
        self.assertEqual(len(it["_text"]), CFG["semantic"]["embed_chars"])

    @unittest.skipIf(importlib.util.find_spec("numpy") is None, "numpy is not installed")
    def test_learned_head_file_is_consistent(self):
        import numpy as np
        h = scanner.Head()
        self.assertTrue(h.ready)
        info = h.info
        self.assertEqual(info["meta_features"], scanner.META_FEATURES)
        width = len(scanner.META_FEATURES) + len(info["sources"]) + len(info["kinds"])
        for name in ("full", "meta"):
            self.assertEqual(len(info[name]["coef_meta"]), width)
            cx, cy = np.array(info[name]["cal_x"]), np.array(info[name]["cal_y"])
            self.assertTrue(np.all(np.diff(cx) > 0))  # np.interp needs increasing x; the mapping must be monotone
            self.assertTrue(np.all(np.diff(cy) >= 0) and cy.min() >= 0 and cy.max() <= 100)
        self.assertEqual(len(info["full"]["coef_emb"]), 384)
        ev = info["evaluation"]
        self.assertGreater(ev["full"]["spearman"], ev["rule_score"])  # held-out agreement beats the rule score
        self.assertEqual(sorted(info["sources"]), info["sources"])
        self.assertLessEqual(set(info["sources"]), set(scanner.SOURCES))

    @unittest.skipIf(importlib.util.find_spec("numpy") is None, "numpy is not installed")
    def test_finish_with_learned_head(self):
        import numpy as np
        h = scanner.Head()
        stuffed = "Herculaneum papyri papyrology palimpsest cultural heritage greek latin epigraphy 3d volume " * 6
        villa = scanner.make_item(self.s, source="github", kind="pr", id="v", title="villa #1: VC3D object store",
                                  url="", date="2026-10-29T00:00:00Z", text="Volume Cartographer surfaces", base=30,
                                  base_label="ScrollPrize/villa", state="merged")
        spam = scanner.make_item(self.s, source="zenodo", kind="preprint", id="z", title="Ipotesi", url="",
                                 date="2026-10-29T00:00:00Z", text=stuffed)
        pkg = {"keyword": 25, "topics": [], "source": "pypi", "kind": "package"}

        class VecSem:
            ready = True

            def score_many(self, texts, progress=None, what="items"):
                return [{"semantic": 40, "sim": 0.74, "near": "Scroll work"} for _ in texts]

            def embed(self, texts):
                v = np.ones((len(texts), 384), "float32")
                return v / np.linalg.norm(v, axis=1, keepdims=True)
        scanner.finish([villa, spam, pkg], self.s, VecSem(), head=h)
        self.assertEqual((villa["learned"], spam["learned"], pkg["learned"]), ("full", "full", "meta"))
        for it in (villa, spam, pkg):
            self.assertTrue(0 <= it["score"] <= 100)
            self.assertEqual(it["band"], self.s.band(it["score"]))
            self.assertIn("rule", it)  # the keep gate stays the rule score
            self.assertNotIn("capped", it)
        self.assertEqual(pkg["rule"], 25)
        # Without head.json the rule score stays the final score.
        none = scanner.Head(Path(tempfile.mkdtemp()) / "missing.json")
        self.assertFalse(none.ready)
        items = [{"keyword": 25, "topics": []}]
        scanner.finish(items, self.s, None, head=none)
        self.assertEqual((items[0]["score"], items[0].get("learned")), (25, None))

    @unittest.skipIf(importlib.util.find_spec("numpy") is None, "numpy is not installed")
    def test_vector_cache_survives_a_restart(self):
        import numpy as np
        sem = scanner.Semantic(CFG)
        sem.cache = {"k1": np.ones(384, "float32") / np.sqrt(384)}
        path = Path(tempfile.mkdtemp()) / "vectors.npz"
        sem.save_cache(path)
        again = scanner.Semantic(CFG)
        self.assertEqual(again.load_cache(path), 1)
        self.assertAlmostEqual(float(np.linalg.norm(again.cache["k1"])), 1.0, places=3)
        other = dict(CFG, semantic=dict(CFG["semantic"], model="another/model"))
        self.assertEqual(scanner.Semantic(other).load_cache(path), 0)  # vectors of another model are not reused


class TextTest(unittest.TestCase):
    def test_clean_and_links(self):
        self.assertEqual(scanner.clean("<p>Caf\\'e &amp; <b>ink</b></p>"), "Cafe & ink")
        links = scanner.code_links("Code at https://github.com/org/repo. Paper at https://example.org/x")
        self.assertEqual(links, ["https://github.com/org/repo"])

    def test_unsafe_urls_dropped(self):
        it = scanner.make_item(scanner.Scorer(CFG), source="blog", kind="post", id="x", title="t",
                               url="javascript:alert(1)", date="2026-10-29T00:00:00Z")
        self.assertEqual(it["url"], "")

    def test_config_matches_collectors(self):
        self.assertEqual(set(CFG["sources"]), set(scanner.SOURCES))
        self.assertEqual(set(scanner.COLLECTORS), set(scanner.SOURCES))
        for s in CFG["sources"].values():
            self.assertGreaterEqual(s["every_min"], 15)  # polite to every source

    def test_daily_paper_merges_into_arxiv_row(self):
        rows = [{"id": "arxiv:1", "kind": "paper", "url": "a"},
                {"id": "hfp:1", "kind": "daily-paper", "arxiv": "arxiv:1", "upvotes": 7, "url": "h"}]
        out = scanner.merge_daily_papers(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["upvotes"], 7)

    def test_said_keeps_the_words_of_a_comment(self):
        body = ("<!-- template -->\n> quoted earlier text\n## Update\nI tried **this** on [PHerc0332](https://x.org/a):\n"
                "```py\nprint(1)\n```\n![shot](https://x.org/s.png) ![two](https://x.org/t.png)\nWorks `well`.")
        self.assertEqual(scanner.said(body), "Update I tried this on PHerc0332: [code] [image] Works well.")
        long = scanner.said("word " * 300, 50)
        self.assertTrue(long.endswith("...") and len(long) <= 53)


T0 = dt.datetime(2026, 10, 30, 2, 13, tzinfo=dt.timezone.utc)


def ago_iso(minutes):
    return iso(T0 - dt.timedelta(minutes=minutes))


class GitHubActivityTest(unittest.TestCase):
    """The villa watch credits whoever made an item's latest update, says what it said, and keeps the opener; an
    update it cannot explain is not pinned on an older comment. GitHub is faked: no network."""

    U = "https://api.github.com/repos/ScrollPrize/villa"

    def fake(self):
        user = lambda n: {"login": n}  # noqa: E731
        issue = lambda n, mins_open, mins_upd, who, **kw: dict(  # noqa: E731
            number=n, title=f"Item {n}", body="Label generation methods for surface models", user=user(who),
            html_url=f"https://github.com/ScrollPrize/villa/issues/{n}", created_at=ago_iso(mins_open),
            updated_at=ago_iso(mins_upd), state="open", labels=[], comments=21, **kw)
        pr = lambda n, mins_open, mins_upd, who: dict(  # noqa: E731
            issue(n, mins_open, mins_upd, who), html_url=f"https://github.com/ScrollPrize/villa/pull/{n}", draft=False,
            merged_at=None)
        routes = {
            "/pulls?": [pr(2400, 600, 30, "opener-a"), pr(2401, 5, 5, "opener-b"), pr(2402, 900, 60, "opener-c")],
            "/issues?": [issue(193, 900000, 49, "bruniss"), issue(194, 9000, 300, "opener-d"),
                         {"number": 2400, "pull_request": {"url": "p"}, "updated_at": ago_iso(30)}],
            "/releases?": [],
            "/issues/comments?": [
                {"issue_url": f"{self.U}/issues/193", "user": user("commenter"), "created_at": ago_iso(49),
                 "updated_at": ago_iso(49), "html_url": "https://github.com/ScrollPrize/villa/issues/193#issuecomment-9",
                 "body": "> old text\nHere is a new label set from the PHerc1667 fibers."},
                {"issue_url": f"{self.U}/issues/194", "user": user("early"), "created_at": ago_iso(2000),
                 "updated_at": ago_iso(2000), "html_url": "u", "body": "an older comment"}],
            "/pulls/comments?": [],
            "/issues/events?": [{"event": "labeled", "actor": user("maint"), "created_at": ago_iso(48.5),
                                 "label": {"name": "data"}, "issue": {"number": 193, "html_url": "x"}},
                                {"event": "subscribed", "actor": user("noise"), "created_at": ago_iso(1),
                                 "issue": {"number": 194}}],
            "/pulls/2400/reviews?": [{"user": user("reviewer"), "state": "APPROVED", "body": "",
                                      "submitted_at": ago_iso(30), "html_url": "https://github.com/r"}],
            "/pulls/2400/commits?": [{"author": user("opener-a"), "html_url": "c",
                                      "commit": {"message": "first\n\nbody", "committer": {"date": ago_iso(400)}}}],
            "/pulls/2402/reviews?": [], "/pulls/2402/commits?": [],
        }
        calls = []

        def get(url):
            calls.append(url)
            for k in sorted(routes, key=len, reverse=True):
                if k in url.replace(self.U, ""):
                    return routes[k]
            raise AssertionError("unexpected call " + url)
        return get, calls

    def run_github(self, state):
        get, calls = self.fake()
        orig = scanner._gh_get
        scanner._gh_get = get
        self.addCleanup(setattr, scanner, "_gh_get", orig)
        sc = dict(CFG["sources"]["github"], queries=[])
        items, info = scanner.c_github(sc, {"scorer": scanner.Scorer(CFG), "since": T0 - dt.timedelta(hours=8),
                                            "progress": lambda m: None, "state": state})
        return {i["id"]: i for i in items}, info, calls

    def test_comment_author_and_words_credited_and_opener_kept(self):
        items, info, _ = self.run_github({})
        it = items["github:scrollprize/villa#193"]
        self.assertEqual(it["who"], "bruniss")  # still the opener
        a = it["activity"]
        self.assertEqual((a["what"], a["who"]), ("comment", "commenter"))  # the comment, not the later bare label
        self.assertEqual(a["text"], "Here is a new label set from the PHerc1667 fibers.")
        self.assertTrue(a["url"].endswith("#issuecomment-9"))
        self.assertEqual(a["also"], ["label added"])
        self.assertTrue(scanner.parse_time(a["date"]) < T0)

    def test_approval_found_by_lookup_and_remembered(self):
        state = {}
        items, _, calls = self.run_github(state)
        a = items["github:scrollprize/villa#2400"]["activity"]
        self.assertEqual((a["what"], a["who"]), ("approved", "reviewer"))
        self.assertNotIn("activity", items["github:scrollprize/villa#2401"])  # only opened
        self.assertNotIn("activity", items["github:scrollprize/villa#2402"])  # nothing explains it
        self.assertNotIn("activity", items["github:scrollprize/villa#194"])   # the old comment is not credited
        self.assertEqual(sum("/reviews?" in u for u in calls), 2)  # the lookup budget
        _, _, again = self.run_github(state)
        self.assertEqual(sum("/reviews?" in u or "/commits?" in u for u in again), 0)  # same updated time: remembered

    def test_cut_off_download_is_retried(self):
        import http.client
        import urllib.request
        tries = []

        class Resp:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"ok": 1}'

        def urlopen(req, timeout=None):
            tries.append(req.full_url)
            if len(tries) == 1:
                raise http.client.IncompleteRead(b"x" * 10)
            return Resp()
        orig, sleep = urllib.request.urlopen, scanner.time.sleep
        urllib.request.urlopen, scanner.time.sleep = urlopen, lambda s: None
        self.addCleanup(setattr, urllib.request, "urlopen", orig)
        self.addCleanup(setattr, scanner.time, "sleep", sleep)
        self.assertEqual(scanner.Fetcher().json("https://api.github.com/x"), {"ok": 1})
        self.assertEqual(len(tries), 2)

    def test_villa_network_error_keeps_the_search_results(self):
        import http.client

        def get(url):
            if "/search/repositories" in url:
                return {"items": [{"full_name": "someone/vesuvius-tools", "html_url": "https://github.com/someone/vesuvius-tools",
                                   "pushed_at": ago_iso(10), "created_at": ago_iso(9000), "description": "Vesuvius Challenge segmentation tools",
                                   "owner": {"login": "someone"}, "topics": []}]}
            raise http.client.IncompleteRead(b"x")
        orig, sleep = scanner._gh_get, scanner.time.sleep
        scanner._gh_get, scanner.time.sleep = get, lambda s: None
        self.addCleanup(setattr, scanner, "_gh_get", orig)
        self.addCleanup(setattr, scanner.time, "sleep", sleep)
        sc = dict(CFG["sources"]["github"], queries=["vesuvius challenge"])
        items, info = scanner.c_github(sc, {"scorer": scanner.Scorer(CFG), "since": T0 - dt.timedelta(hours=8),
                                            "progress": lambda m: None, "state": {}})
        self.assertEqual([i["id"] for i in items], ["github:someone/vesuvius-tools"])
        self.assertIn("ScrollPrize/villa: network error (IncompleteRead)", info["notes"])

    def test_lookup_budget_and_partial_listing(self):
        state = {}
        sc_budget = CFG["sources"]["github"].get("pr_lookups")
        self.assertLessEqual(sc_budget, 3)  # logged out: 60 calls an hour for every listing together
        _, info, calls = self.run_github(state)
        self.assertLessEqual(len(calls), 6 + 2 * sc_budget)
        self.assertFalse(any("HTTP" in n for n in info["notes"]))


class NewsFeedTest(unittest.TestCase):
    """News searches go through the scorer, a story found by several searches is kept once, Bing's click counter is
    unwrapped to the article, Google's outlet suffix comes off the title, and a feed that fails is a note while the
    others still count. The blog's own posts keep their base. Feeds are faked: no network."""

    @staticmethod
    def rss(*items, ns=""):
        return f'<?xml version="1.0"?><rss version="2.0"{ns}><channel>' + "".join(items) + "</channel></rss>"

    @staticmethod
    def item(title, link, mins, extra=""):
        when = email.utils.format_datetime(T0 - dt.timedelta(minutes=mins))
        return f"<item><title>{title}</title><link>{link}</link><pubDate>{when}</pubDate>{extra}</item>"

    def run_blog(self, feeds, pages):
        def get(url, *a, **kw):
            body = pages[url]
            if isinstance(body, Exception):
                raise body
            return body.encode()
        scanner.FETCH.get = get  # an instance attribute shadows the method for this test
        self.addCleanup(delattr, scanner.FETCH, "get")
        items, info = scanner.c_blog({"feeds": feeds}, {"scorer": scanner.Scorer(CFG), "since": T0 - dt.timedelta(days=2),
                                                        "progress": lambda m: None})
        return items, info

    def test_searches_scored_deduplicated_and_unwrapped(self):
        bing_ns = ' xmlns:News="https://www.bing.com/news/search?q=x"'
        click = "http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fwww.example.org%2fscrolls&amp;mkt=en-us"
        pages = {
            "https://blog/feed": self.rss(self.item("Monthly update", "https://blog/p/october", 60)),
            "https://google/rss": self.rss(
                self.item("Scientists decipher charred Herculaneum scrolls - BBC", "https://news.google.com/rss/articles/A", 90,
                          '<source url="https://www.bbc.com">BBC</source>'),
                self.item("How ancient DNA is rewriting history - Quillette", "https://news.google.com/rss/articles/B", 95,
                          '<source url="https://quillette.com">Quillette</source>'),
                self.item("Old Herculaneum story - BBC", "https://news.google.com/rss/articles/C", 60 * 24 * 5)),
            "https://bing/rss": self.rss(
                self.item("Scientists decipher charred Herculaneum scrolls", click, 80, "<News:Source>Irish Examiner</News:Source>"),
                self.item("Virtual unwrapping reads a Herculaneum papyrus", click, 70,
                          "<News:Source>Irish Examiner</News:Source><description>X-ray CT of the scroll</description>"),
                ns=bing_ns),
            "https://hn/rss": urllib.error.HTTPError("https://hn/rss", 503, "busy", {}, None),
            "https://html/page": "<!doctype html><html><body>not a feed</body></html>",
        }
        feeds = [["Vesuvius Challenge", "https://blog/feed"],
                 {"name": "Google News", "url": "https://google/rss", "search": True},
                 {"name": "Bing News", "url": "https://bing/rss", "search": True},
                 {"name": "Hacker News", "url": "https://hn/rss", "search": True},
                 {"name": "Bing News", "url": "https://html/page", "search": True}]
        items, info = self.run_blog(feeds, pages)
        by = {i["title"]: i for i in items}
        self.assertEqual(by["Monthly update"]["kind"], "post")                       # the blog's own post keeps its base
        self.assertGreaterEqual(by["Monthly update"]["keyword"], CFG["keep_score"])
        story = by["Scientists decipher charred Herculaneum scrolls"]                  # outlet suffix off, found once
        self.assertEqual((story["kind"], story["who"], story["feed"]), ("news", "BBC", "Google News"))
        self.assertEqual(sum(i["title"] == story["title"] for i in items), 1)
        self.assertGreaterEqual(story["keyword"], CFG["keep_score"])
        self.assertLess(by["How ancient DNA is rewriting history"]["keyword"], CFG["keep_score"])   # scored, so dropped
        self.assertNotIn("Old Herculaneum story", by)                                # outside the window
        other = by["Virtual unwrapping reads a Herculaneum papyrus"]
        self.assertEqual((other["url"], other["who"]), ("https://www.example.org/scrolls", "Irish Examiner"))
        self.assertEqual(info["notes"], ["Hacker News: HTTP 503", "Bing News: skipped, the answer was not RSS"])

    def test_config_reads_news_searches_and_the_scrollprize_org(self):
        feeds = CFG["sources"]["blog"]["feeds"]
        self.assertEqual(feeds[0][0], "Vesuvius Challenge")
        names = {f["name"] for f in feeds[1:] if f.get("search")}
        self.assertEqual(names, {"Google News", "Bing News", "Hacker News"})
        self.assertIn("org:ScrollPrize", CFG["sources"]["github"]["queries"])


@unittest.skipIf(app is None, "fastapi is not installed")
class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        now = dt.datetime.now(dt.timezone.utc)
        sc = scanner.Scorer(CFG)

        def item(i, src, kind, title, mins, **kw):
            it = scanner.make_item(sc, source=src, kind=kind, id=f"{src}:{i}", title=title, url=f"https://example.org/{i}",
                                   date=iso(now - dt.timedelta(minutes=mins)), **kw)
            scanner.finish([it], sc, None)
            it["first_seen"] = iso(now - dt.timedelta(minutes=min(mins, 30)))
            return it
        items = [
            item(1, "arxiv", "paper", "Virtual unwrapping of Herculaneum scrolls from X-ray CT", 3,
                 text="Code at https://github.com/a/b"),
            item(2, "arxiv", "paper", "Ink detection in phase-contrast synchrotron tomography of papyrus", 600),
            item(3, "github", "repo", "someone/vesuvius-tools", 2000, text="Vesuvius Challenge segmentation tools"),
            item(4, "hf", "model", "someone/papyrus-ink-3d", 5000, text="ink detection model for herculaneum papyri"),
            item(5, "journals", "journal article", "Old article on Herculaneum papyri", 60 * 24 * 40),
        ]
        with app.LOCK:
            app.STORE["items"] = {i["id"]: i for i in items}
        cls.c = TestClient(app.app)
        cls.items = items

    def get(self, url, code=200):
        r = self.c.get(url)
        self.assertEqual(r.status_code, code, r.text)
        return r

    def test_lookbacks(self):
        self.assertEqual(self.get("/api/items?since=1m").json()["matched"], 0)
        self.assertEqual(self.get("/api/items?since=5m").json()["matched"], 1)
        self.assertEqual(self.get("/api/items?since=1d").json()["matched"], 2)  # 3 min and 10 h ago; 2000 min is past a day
        self.assertEqual(self.get("/api/items?since=30d").json()["matched"], 4)  # the 40-day item is outside
        self.assertEqual(self.get("/api/items?since=90d").json()["matched"], 4)  # capped at 30 days
        self.get("/api/items?since=yesterday", 400)
        self.get("/api/items?since=0m", 400)

    def test_found_by_radar(self):
        # by=found uses first_seen (at most 30 minutes ago here), so every item but the old one is inside 1h
        self.assertEqual(self.get("/api/items?since=1h&by=found").json()["matched"], 5 - 0)
        self.get("/api/items?by=later", 400)

    def test_views(self):
        r = self.get("/api/items?since=30d&view=research").json()
        self.assertTrue(all(i["source"] in ("arxiv", "journals") for i in r["items"]))
        r = self.get("/api/items?since=30d&view=builders").json()
        kinds = {i["kind"] for i in r["items"]}
        self.assertTrue({"repo", "model"} <= kinds)
        self.assertIn("arxiv:1", [i["id"] for i in r["items"]])  # a paper that links code
        self.get("/api/items?view=nobody", 400)

    def test_filters_and_sort(self):
        # word search covers titles, summaries and topic names, so the X-ray CT paper (topic Ink and imaging) matches
        r = self.get("/api/items?since=30d&q=ink&sources=arxiv,hf").json()
        self.assertEqual({i["id"] for i in r["items"]}, {"arxiv:1", "arxiv:2", "hf:4"})
        r = self.get("/api/items?since=30d&q=synchrotron&sources=arxiv,hf").json()
        self.assertEqual({i["id"] for i in r["items"]}, {"arxiv:2"})
        r = self.get("/api/items?since=30d&sort=date").json()
        dates = [i["date"] for i in r["items"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        r = self.get("/api/items?since=30d&ids=github:3,hf:4").json()
        self.assertEqual(r["matched"], 2)
        r = self.get("/api/items?since=30d&has_code=true").json()
        self.assertEqual([i["id"] for i in r["items"]], ["arxiv:1"])

    def test_overview_briefing_counts(self):
        o = self.get("/api/overview?since=7d").json()
        self.assertEqual(o["items"], 4)
        self.assertEqual(sum(sum(b["n"].values()) for b in o["timeline"]["bins"]), 4)
        self.assertEqual(sum(o["score_hist"]), 4)
        self.assertEqual(self.get("/api/overview?since=15m").json()["timeline"]["bin_seconds"], 60)
        b = self.get("/api/briefing?since=30d&min_score=0").json()
        ids = [i["id"] for t in b["topics"].values() for i in t]
        self.assertEqual(len(ids), len(set(ids)))
        c = self.get("/api/counts").json()["lookbacks"]
        self.assertEqual((c["1m"], c["5m"], c["1d"], c["30d"]), (0, 1, 2, 4))

    def test_top_people_count_pieces_of_work(self):
        # Without the meaning model, one person's items from one source on one day are one piece of work, so many small
        # pull requests on one day do not outrank someone with two separate pieces.
        day = "2026-10-28T1"
        many = [{"who": "busy", "source": "github", "kind": "pr", "date": f"{day}{k % 10}:00:00Z", "score": 30} for k in range(9)]
        two = [{"who": "Builder", "source": "github", "kind": "repo", "date": "2026-10-27T10:00:00Z", "score": 80},
               {"who": "builder", "source": "hf", "kind": "model", "date": "2026-10-28T10:00:00Z", "score": 70}]
        rows = app.top_people(many + two + [{"who": "pkg", "source": "pypi", "kind": "package", "date": day + "0:00:00Z", "score": 90}])
        self.assertEqual([r["name"] for r in rows], ["Builder", "busy"])  # names merge across case; packages have no author
        self.assertEqual((rows[0]["works"], rows[0]["items"], rows[0]["value"]), (2, 2, 150))
        self.assertEqual((rows[1]["works"], rows[1]["items"], rows[1]["value"]), (1, 9, 30))
        o = self.get("/api/overview?since=30d").json()
        self.assertEqual(set(o["community"]), {"villa_merged", "new_scroll_repos"})
        self.assertEqual(list(o["top_people"]), [r["name"] for r in o["people"]])

    def test_builders_view_is_called_contributors(self):
        self.assertEqual(self.get("/api/views").json()["builders"]["label"], "Contributors")
        page = (HERE / "index.html").read_text()
        self.assertNotIn("competitor", page.lower())
        js = (HERE / "static" / "app.js").read_text()
        self.assertIn('sort: "date"', js)  # the page's list opens on Newest
        self.assertIn("PER = [10, 20, 50, 100]", js)

    def test_item_csv_feed_docs(self):
        it = self.get("/api/item?id=arxiv:1").json()
        self.assertEqual(it["similar"], [])  # no model in tests
        self.get("/api/item?id=nope", 404)
        csv_text = self.get("/api/export.csv?since=30d").text
        self.assertTrue(csv_text.startswith("score,band,keyword"))
        root = ET.fromstring(self.get("/feed.xml?since=30d&min_score=0").text)
        self.assertEqual(len(root.findall("channel/item")), 4)
        self.get("/openapi.json")
        for p in ("/", "/connect.json", "/connect.html", "/CONNECT.md", "/api/views", "/api/config", "/api/sources", "/healthz"):
            self.get(p)

    def test_one_person_under_several_accounts(self):
        # Chase Hendrick is ChaseHendrick on GitHub and SharpMeow on Hugging Face: one person in counts, names and search.
        now = dt.datetime.now(dt.timezone.utc)
        sc = scanner.Scorer(CFG)
        made = []
        for n, (src, kind, who) in enumerate((("github", "repo", "ChaseHendrick"), ("hf", "space", "SharpMeow"))):
            it = scanner.make_item(sc, source=src, kind=kind, id=f"{src}:chase{n}", title=f"{who}/herculaneum-tool-{n}",
                                   url=f"https://example.org/chase{n}", date=iso(now - dt.timedelta(minutes=4 + n)),
                                   text=f"Vesuvius Challenge scroll segmentation tool number {n}", who=who)
            scanner.finish([it], sc, None)
            it["first_seen"] = it["date"]
            made.append(it)
        with app.LOCK:
            app.STORE["items"].update({i["id"]: i for i in made})
        for i in made:
            self.addCleanup(app.STORE["items"].pop, i["id"])
        people = [r["name"] for r in self.get("/api/overview?since=1h").json()["people"]]
        self.assertIn("Chase Hendrick", people)
        self.assertFalse({"ChaseHendrick", "SharpMeow"} & set(people))
        got = self.get("/api/items?since=1h&q=chase+hendrick").json()["items"]
        self.assertEqual({(i["who"], i["who_name"]) for i in got},
                         {("ChaseHendrick", "Chase Hendrick"), ("SharpMeow", "Chase Hendrick")})
        self.assertEqual(self.get("/api/items?since=1h&q=sharpmeow").json()["matched"], 1)   # the account still finds it
        b = self.get("/api/briefing?since=1h&per_topic=10").json()
        self.assertEqual({i.get("who_name") for t in b["topics"].values() for i in t if i["id"].endswith(("chase0", "chase1"))},
                         {"Chase Hendrick"})

    def test_latest_update_reaches_search_csv_feed_and_mcp(self):
        now = dt.datetime.now(dt.timezone.utc)
        it = scanner.make_item(scanner.Scorer(CFG), source="github", kind="issue", id="github:scrollprize/villa#193",
                               title="ScrollPrize/villa #193: Methods for generating surface, fiber, or ink labels",
                               url="https://github.com/ScrollPrize/villa/issues/193", date=iso(now - dt.timedelta(minutes=9)),
                               text="Label generation methods", base=22, core_terms=False, who="bruniss",
                               activity={"what": "comment", "who": "commenter", "date": iso(now - dt.timedelta(minutes=9)),
                                         "text": "Here is a new label set.", "url": "https://github.com/c"})
        scanner.finish([it], scanner.Scorer(CFG), None)
        it["first_seen"] = it["date"]
        with app.LOCK:
            app.STORE["items"][it["id"]] = it
        self.addCleanup(app.STORE["items"].pop, it["id"])
        got = self.get("/api/items?since=1h&q=commenter").json()
        self.assertEqual(got["matched"], 1)
        self.assertEqual((got["items"][0]["who"], got["items"][0]["activity"]["who"]), ("bruniss", "commenter"))
        csv_text = self.get("/api/export.csv?since=1h&q=commenter").text
        self.assertIn("update_by", csv_text.splitlines()[0])
        self.assertIn("Here is a new label set.", csv_text)
        self.assertIn("Comment by commenter: Here is a new label set. Opened by bruniss.",
                      self.get("/feed.xml?since=1h&min_score=0").text)
        r = self.mcp({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                      "params": {"name": "search_items", "arguments": {"since": "1h", "query": "commenter", "min_score": 0}}})
        self.assertEqual(r["result"]["structuredContent"]["items"][0]["activity"]["who"], "commenter")

    def test_merge_keeps_first_seen(self):
        it = dict(self.items[0])
        saved = dict(app.STORE["items"][it["id"]])
        self.addCleanup(app.STORE["items"].__setitem__, it["id"], saved)  # other tests count this item by its date
        first = app.STORE["items"][it["id"]]["first_seen"]
        it["date"] = iso(dt.datetime.now(dt.timezone.utc))
        self.assertEqual(app.merge([it]), 0)
        self.assertEqual(app.STORE["items"][it["id"]]["first_seen"], first)
        self.assertTrue(app.STORE["items"][it["id"]]["updated"])

    def test_check_is_one_at_a_time_with_cooldown(self):
        app.CHECK.update(last=0.0, requested=None)
        self.assertEqual(self.c.post("/api/check").status_code, 200)
        self.assertEqual(self.c.post("/api/check").status_code, 409)
        app.CHECK["requested"] = None
        r = self.c.post("/api/check")
        self.assertEqual(r.status_code, 429)
        self.assertIn("retry_after", r.json())
        app.CHECK.update(last=0.0, requested=None)

    def mcp(self, body, code=200):
        r = self.c.post("/mcp", json=body)
        self.assertEqual(r.status_code, code, r.text)
        return r.json() if r.content else None

    def test_mcp(self):
        init = self.mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "vesuvius-radar")
        tools = self.mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual(len(tools), 9)
        call = lambda n, a: self.mcp({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": n, "arguments": a}})["result"]  # noqa: E731
        r = call("search_items", {"since": "30d", "query": "ink", "min_score": 0})
        self.assertFalse(r["isError"])
        self.assertEqual(r["structuredContent"]["matched"], 3)
        self.assertTrue(call("search_items", {"since": "soon"})["isError"])
        self.assertTrue(call("get_item", {"item_id": "nope"})["isError"])
        self.assertFalse(call("briefing", {"since": "30d", "view": "team"})["isError"])
        self.assertNotIn("timeline", call("overview", {"since": "7d"})["structuredContent"])
        self.assertIsNone(self.mcp({"jsonrpc": "2.0", "method": "notifications/initialized"}, 202))
        self.assertEqual(self.mcp({"jsonrpc": "2.0", "id": 4, "method": "nope"})["error"]["code"], -32601)
        self.assertEqual(self.mcp([{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(21)], 400)["error"]["code"], -32600)
        self.assertEqual(self.c.get("/mcp").status_code, 405)


class PageTest(unittest.TestCase):
    def test_saved_filters_survive_hugging_faces_own_parameters(self):
        js, css = (HERE / "static" / "app.js").read_text(), (HERE / "static" / "style.css").read_text()
        # Hugging Face opens the Space as ?__theme=system (and ?__sign=... when private). That once counted as a shared
        # link and reset every filter, the minimum score snapping back to 20; now only a filter parameter does.
        self.assertNotIn("if (![...p.keys()].length) return;", js)
        self.assertIn('.some((k) => p.has(k))) return;', js)
        self.assertIn("const f = Object.assign(defaults(), { min: S.f.min });", js)   # a link without min keeps the saved one
        self.assertIn('    p.set("min", f.min);', js)                                    # a shared link always names its minimum
        self.assertIn("${esc(clip(byline(i), 80))}", js)     # the person's name replaces the first author only, co-authors stay
        rule = re.search(r"#checkBtn \{([^}]*)\}", css).group(1)                     # Refresh wears a halo in every theme
        self.assertIn("box-shadow", rule)
        self.assertIn("var(--accent)", rule)
        page = (HERE / "index.html").read_text()
        self.assertIn("Match ideas, not words", page)
        self.assertNotIn(">By meaning<", page)

    def test_each_card_button_opens_its_own_panel_and_updates_name_their_author(self):
        js, css = (HERE / "static" / "app.js").read_text(), (HERE / "static" / "style.css").read_text()
        # "Why this score" and "More like this" once opened the same panel; each now has its own.
        self.assertIn('if (act === "why") {', js)
        self.assertIn('if (act === "like") {', js)
        self.assertNotIn('act === "why" || act === "like"', js)
        self.assertIn("data-similar", js)
        self.assertNotIn("data-sims", js)
        self.assertIn("${updateHTML(i)}", js)          # the update's author and words on the card
        self.assertIn('issue: "opened by"', js)        # the opener is named as the opener
        for cls in (".update-row", ".usaid"):
            self.assertIn(cls, css)


class PublicSafetyTest(unittest.TestCase):
    """The Space is public: no key handling, no private links, no Discord, no internal marks."""

    FILES = [p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".png"]

    def test_no_secrets_or_private_material(self):
        # The repository's pre-push leak check covers private repository and storage names; this covers the rest.
        bad = [r"discord", r"HF_TOKEN", r"GITHUB_TOKEN", r"Authorization", r"\bours\b", r"own_accounts",
               r"hf_[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"paris ?4", r"PHercParis", "\u2014", "\u2013"]
        for p in self.FILES:
            text = p.read_text(errors="replace")
            if p.name == "LICENSE":
                continue
            for pat in bad:
                self.assertIsNone(re.search(pat, text, re.I), f"{p.relative_to(HERE)} contains {pat}")

    def test_only_public_hosts_are_read(self):
        src = (HERE / "scanner.py").read_text()
        hosts = set(re.findall(r"https://([a-z0-9.-]+)/", src))
        self.assertLessEqual(hosts, {"rss.arxiv.org", "arxiv.org", "export.arxiv.org", "api.github.com", "huggingface.co",
                                     "pypi.org", "zenodo.org", "api.crossref.org", "doi.org"})


if __name__ == "__main__":
    unittest.main()
