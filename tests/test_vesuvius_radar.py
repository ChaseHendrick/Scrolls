"""Vesuvius Radar Space (spaces/vesuvius-radar): scoring stays explainable, lookbacks and views filter as documented,
the API, feed and MCP server answer, and nothing private or secret is in the Space's files. Offline: no source is
fetched and the embedding model is not loaded."""

import datetime as dt
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
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
