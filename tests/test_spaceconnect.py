"""Tests for kit/spaceconnect.py: the Connect your tool panel every Space carries."""

import html
import importlib.util
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from kit import spaceconnect as sc

OD = sc.OPEN_DATA


def spec(*sources, **kw):
    return {"schema": sc.SCHEMA, "space": "SharpMeow/demo", "title": "Demo", "checked": "2026-10-24",
            "sources": list(sources), **kw}


ZARR = {"id": "ct", "title": "CT", "kind": "ome-zarr", "url": f"{OD}/PHerc0139/volumes/x.zarr",
        "license": "CC BY-NC 4.0", "zarr_format": 2, "example": {"level": "2", "start": [10, 20, 30]}}
DATASET = {"id": "lines", "title": "Lines", "kind": "hf-dataset", "url": "https://huggingface.co/datasets/A/b",
           "repo": "A/b", "file": "index.json", "configs": ["lines"], "table": "t.jsonl", "license": "MIT"}
API = {"id": "api", "title": "API", "kind": "gradio-api", "url": "https://huggingface.co/spaces/A/c", "space": "A/c",
       "host": "https://a-c.hf.space", "status": "running", "license": "Apache-2.0",
       "endpoints": [{"api": "/go", "args": {"n": 3, "name": "x"}}]}


class Validate(unittest.TestCase):
    def test_good_spec_passes(self):
        self.assertEqual(sc.validate(spec(ZARR, DATASET, API)), [])

    def test_missing_and_unknown(self):
        errs = sc.validate(spec({"id": "a", "title": "A", "kind": "nope", "url": "https://x", "license": "MIT"},
                                {"id": "b", "kind": "hf-dataset", "url": "https://x", "license": "MIT"}))
        self.assertTrue(any("unknown kind" in e for e in errs))
        self.assertTrue(any("b: missing title" in e for e in errs))
        self.assertTrue(any("needs repo" in e for e in errs))

    def test_https_only_and_unique_ids(self):
        errs = sc.validate(spec(dict(ZARR, url="http://example.org/a.zarr"), ZARR))
        self.assertTrue(any("must be https" in e for e in errs))
        self.assertTrue(any("duplicate id" in e for e in errs))

    def test_refuses_rehosted_educelab_scan(self):
        rehost = dict(ZARR, url="https://huggingface.co/datasets/A/scroll4/resolve/main/v.zarr", scroll="PHerc1667",
                      scan_year=2023)
        self.assertTrue(any("EduceLab" in e for e in sc.validate(spec(rehost))))
        self.assertEqual(sc.validate(spec(dict(rehost, scan_year=2025))), [])
        self.assertEqual(sc.validate(spec(dict(ZARR, scroll="PHerc1667", scan_year=2023))), [])  # linked, not copied


class Tools(unittest.TestCase):
    def ids(self, src):
        return [t[0] for t in sc._tools(src)]

    def test_kinds_offer_their_tools(self):
        self.assertEqual(self.ids(ZARR), ["zarr", "vesuvius", "vc3d", "neuroglancer", "curl"])
        self.assertEqual(self.ids(DATASET), ["hub", "datasets", "pandas", "cli", "curl"])
        self.assertEqual(self.ids(API), ["python", "curl", "mcp"])
        self.assertEqual(self.ids(dict(ZARR, tools=["zarr", "curl"])), ["zarr", "curl"])

    def test_zarr_snippet_uses_level_and_block(self):
        code = dict((t[0], t[3]) for t in sc._tools(ZARR))
        self.assertIn('root["2"]', code["zarr"])
        self.assertIn("a[10:74, 20:84, 30:94]", code["zarr"])
        self.assertIn(f'path="{ZARR["url"]}/2"', code["vesuvius"])
        self.assertIn("/.zattrs", code["curl"])
        self.assertIn("/zarr.json", dict((t[0], t[3]) for t in sc._tools(dict(ZARR, zarr_format=3)))["curl"])

    def test_gradio_snippets(self):
        code = dict((t[0], t[3]) for t in sc._tools(API))
        self.assertIn('client.predict(n=3, name="x", api_name="/go")', code["python"])
        self.assertIn('{"data": [3, "x"]}', code["curl"])
        self.assertIn("https://a-c.hf.space/gradio_api/mcp/sse", code["mcp"])
        self.assertNotIn("HF_TOKEN", code["python"] + code["curl"] + code["mcp"])

    def test_zerogpu_snippets_pass_the_callers_token(self):
        code = dict((t[0], t[3]) for t in sc._tools(dict(API, zerogpu=True)))
        self.assertIn('Client("A/c", token=os.environ.get("HF_TOKEN"))', code["python"])
        self.assertEqual(code["curl"].count('${HF_TOKEN:+-H "Authorization: Bearer $HF_TOKEN"}'), 2)
        cfg = json.loads(code["mcp"].split("\n\n")[0])
        self.assertEqual(cfg["mcpServers"]["c"], {"url": "https://a-c.hf.space/gradio_api/mcp/sse",
                                                  "headers": {"Authorization": "Bearer YOUR_HF_TOKEN"}})
        self.assertIn("ZeroGPU quota", code["mcp"])

    def test_neuroglancer_link_round_trips(self):
        link = sc.neuroglancer_link(ZARR["url"], "CT")
        state = json.loads(urllib.parse.unquote(link.split("#!", 1)[1]))
        self.assertEqual(state["layers"][0]["source"], f"zarr://{ZARR['url']}/")
        ng = dict((t[0], t[3]) for t in sc._tools(dict(ZARR, ng_path="1")))["neuroglancer"]
        self.assertIn(urllib.parse.quote(f"{ZARR['url']}/1/", safe=""), ng)


class Probe(unittest.TestCase):
    def test_folders_are_probed_by_their_metadata(self):
        self.assertEqual(sc.probe_url(ZARR, ZARR["url"]), ZARR["url"] + "/.zattrs")
        self.assertEqual(sc.probe_url(dict(ZARR, zarr_format=3), ZARR["url"] + "/"), ZARR["url"] + "/zarr.json")
        mesh = {"kind": "tifxyz", "url": "https://x/m.tifxyz"}
        self.assertEqual(sc.probe_url(mesh, mesh["url"]), "https://x/m.tifxyz/meta.json")
        self.assertEqual(sc.probe_url(DATASET, DATASET["url"]), DATASET["url"])


class Render(unittest.TestCase):
    def test_html_is_scriptless_escaped_and_badged(self):
        out = sc.render_html(spec(ZARR, dict(API, status="paused"), intro="<b>&</b>"))
        self.assertNotIn("<script", out.lower())
        self.assertIn("&lt;b&gt;&amp;&lt;/b&gt;", out)
        self.assertIn("tested 2026-10-24", out)
        self.assertIn("Space paused", out)
        self.assertIn("from villa&#x27;s source", out)
        self.assertIn('class="scc-copy"', out)

    def test_no_long_dashes(self):
        for text in (sc.render_html(spec(ZARR, DATASET, API)), sc.render_md(spec(ZARR, DATASET, API))):
            self.assertNotIn(chr(0x2014), text)
            self.assertNotIn(chr(0x2013), text)

    def test_splice_is_idempotent(self):
        page = f"<p>a</p>{sc.START}\nold\n{sc.END}<p>b</p>"
        once = sc.splice(page, "NEW\n")
        self.assertEqual(once, f"<p>a</p>{sc.START}\nNEW\n{sc.END}<p>b</p>")
        self.assertEqual(sc.splice(once, "NEW\n"), once)

    def test_render_writes_then_reports_current(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "connect.json").write_text(json.dumps(spec(ZARR)))
            (d / "index.html").write_text(f"<body>{sc.START}{sc.END}</body>")
            self.assertEqual(len(sc.render(d)), 4)
            self.assertEqual(sc.render(d, write=False), [])
            self.assertIn('id="connect"', (d / "index.html").read_text())
            self.assertTrue(sc.wired(d, "static"))
            self.assertFalse(sc.wired(d, "gradio"))
            self.assertTrue((d / "onescroll.html").read_text().startswith(sc.SCROLL_START))

    def test_runnable_skips_paused_and_large_downloads(self):
        got = list(sc.runnable(spec(dict(DATASET, size="50 GB"), dict(API, status="paused"))))
        self.assertEqual([g[1] for g in got], ["hub", "datasets", "pandas", "cli", "curl"])
        hub = got[0][3]
        self.assertFalse(any(l.startswith("pip install") for c in got for l in c[3].splitlines()))
        self.assertNotIn("folder = snapshot_download", hub)


HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None


class OneScroll(unittest.TestCase):
    def test_static_page_gets_the_fragment_spliced_and_kept_current(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "connect.json").write_text(json.dumps(spec(ZARR)))
            (d / "index.html").write_text(f"<head>{sc.SCROLL_START}{sc.SCROLL_END}</head><body>{sc.START}{sc.END}</body>")
            sc.render(d)
            page = (d / "index.html").read_text()
            self.assertEqual(page.count(sc.SCROLL_START), 1)
            self.assertIn("__oneScroll", page)
            self.assertTrue(sc.scroll_wired(d, "static"))
            self.assertEqual(sc.render(d, write=False), [])
            (d / "index.html").write_text(page.replace("__oneScroll", "__old"))
            self.assertIn(str(d / "index.html"), sc.render(d, write=False))

    def test_gradio_app_is_wired_when_it_reads_the_fragment(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "app.py").write_text("HEAD = ''\n")
            self.assertFalse(sc.scroll_wired(d, "gradio"))
            (d / "app.py").write_text('HEAD = (HERE / "onescroll.html").read_text()\n')
            self.assertTrue(sc.scroll_wired(d, "gradio"))

    def test_verdict(self):
        page = {"frame": "top", "box": "page", "shown": 900, "content": 2000}
        box = {"frame": "srcdoc", "box": "page", "shown": 700, "content": 4000}
        panel = {"frame": "app", "box": "aside#rail", "shown": 600, "content": 1200}
        self.assertEqual(sc.verdict([page]), [])
        self.assertTrue(sc.verdict([page, box]))                      # a guide frame scrolling inside the page
        self.assertTrue(any("inside the page" in p for p in sc.verdict([page, panel])))
        self.assertEqual(sc.verdict([panel], one_screen=True), [])     # a one-screen viewer keeps one list
        self.assertTrue(sc.verdict([panel, dict(panel, box="aside#card")], one_screen=True))

    @unittest.skipUnless(HAVE_PLAYWRIGHT, "needs playwright and a Chromium")
    def test_fragment_fits_frames_to_their_content(self):
        from playwright.sync_api import sync_playwright
        guide = "<html><body style='margin:20px'>" + "".join(f"<p id=p{i}>line {i}</p>" for i in range(120)) + "</body></html>"
        short = "<html><body><p>short</p></body></html>"
        tall = "<html><body><div style='height:100vh'></div><p>more</p></body></html>"
        page = (f"<html><head>{sc.onescroll_html()}<style>iframe{{width:100%;height:calc(100vh - 150px);"
                f"min-height:640px;border:0}}</style></head><body><h1>App</h1>"
                f'<iframe id="g" srcdoc="{html.escape(guide, quote=True)}"></iframe>'
                f'<iframe id="s" srcdoc="{html.escape(short, quote=True)}"></iframe>'
                f'<iframe id="k" data-scroll="inner" srcdoc="{html.escape(guide, quote=True)}"></iframe></body></html>')
        size = ("(id) => { const f = document.getElementById(id); "
                "return [f.clientHeight, f.contentDocument.documentElement.scrollHeight]; }")
        with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
            f = Path(d) / "page.html"
            f.write_text(page)
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1000, "height": 800})
                pg.goto(f.as_uri())
                pg.wait_for_timeout(800)
                h, content = pg.evaluate(size, "g")
                self.assertGreater(h, 2000)                            # grew past the 640 px box to its content
                self.assertLessEqual(content, h + 1)
                self.assertLess(pg.evaluate(size, "s")[0], 200)       # shrank below min-height to a short page
                frames = {x["shown"] for x in sc.scan_page(pg) if x["frame"] == "srcdoc"}
                self.assertEqual(len(frames), 1)                       # only the opted-out frame still scrolls
                pg.evaluate("() => { const d = document.getElementById('g').contentDocument;"
                            " for (let i = 20; i < 120; i++) d.getElementById('p' + i).remove(); }")
                pg.wait_for_timeout(400)
                self.assertLess(pg.evaluate(size, "g")[0], 1000)      # shrank with its content
                pg.evaluate(f"() => {{ document.getElementById('s').srcdoc = {json.dumps(tall)}; }}")
                pg.wait_for_timeout(1500)                              # a page sized in vh: gives up, keeps its scroll
                self.assertIsNone(pg.evaluate("() => document.getElementById('s').getAttribute('scrolling')"))
            finally:
                b.close()


    @unittest.skipUnless(HAVE_PLAYWRIGHT, "needs playwright and a Chromium")
    def test_scan_looks_inside_frames_sized_from_outside(self):
        from playwright.sync_api import sync_playwright
        inner = ("<html><body style='margin:0'><div id=box style='height:120px;overflow:auto'>"
                 + "<p>row</p>" * 60 + "</div>" + "<p>tall</p>" * 80 + "</body></html>")
        page = (f'<html><body><iframe scrolling="no" style="width:600px;height:300px;border:0" '
                f'srcdoc="{html.escape(inner, quote=True)}"></iframe></body></html>')
        with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
            f = Path(d) / "page.html"
            f.write_text(page)
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 800, "height": 600})
                pg.goto(f.as_uri())
                pg.wait_for_timeout(300)
                found = sc.scan_page(pg)
            finally:
                b.close()
        boxes = [(x["frame"], x["box"]) for x in found]
        self.assertIn(("srcdoc", "div#box"), boxes)                # a box inside a frame sized from outside counts
        self.assertNotIn(("srcdoc", "page"), boxes)                # the frame's own document has no scroll bar
        self.assertTrue(sc.verdict(found))

    @unittest.skipUnless(HAVE_PLAYWRIGHT, "needs playwright and a Chromium")
    def test_tabs_are_listed_with_their_depth_and_only_when_shown(self):
        from playwright.sync_api import sync_playwright
        page = ("<html><body><div role=tablist><button role=tab>A</button><button role=tab>B</button></div>"
                "<div role=tabpanel><div role=tablist><button role=tab>A1</button></div></div>"
                "<div role=tabpanel style='display:none'><div role=tablist><button role=tab>B1</button></div></div>"
                "</body></html>")
        with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
            f = Path(d) / "page.html"
            f.write_text(page)
            b = pw.chromium.launch()
            try:
                pg = b.new_page()
                pg.goto(f.as_uri())
                tabs = pg.evaluate(sc.TABS_JS)
            finally:
                b.close()
        self.assertEqual([(t["label"], t["depth"]) for t in tabs], [("A", 0), ("B", 0), ("A1", 1)])

    @unittest.skipUnless(HAVE_PLAYWRIGHT, "needs playwright and a Chromium")
    def test_tabs_folded_into_more_tabs_are_found_and_opened(self):
        # Gradio's markup on a phone: the tabs that do not fit leave the tablist for a "More tabs" menu of plain
        # buttons, which the role=tab walk alone never opened
        from playwright.sync_api import sync_playwright
        page = ("<html><body><div class=tabs><div class=tab-wrapper>"
                "<div class='tab-container visually-hidden' aria-hidden=true><button>A</button><button>B</button>"
                "<button>C</button></div>"
                "<div role=tablist><button role=tab>A</button></div>"
                "<span class=overflow-menu><button aria-label='More tabs'>...</button>"
                "<div class='overflow-dropdown hide' style='display:none'>"
                "<button onclick=\"document.title='B'\">B</button><button onclick=\"document.title='C'\">C</button>"
                "</div></span></div></div>"
                "<div role=tabpanel><span class=overflow-menu style='display:none'><button>...</button>"
                "<div class=overflow-dropdown><button>hidden</button></div></span></div></body></html>")
        with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
            f = Path(d) / "page.html"
            f.write_text(page)
            b = pw.chromium.launch()
            try:
                pg = b.new_page()
                pg.goto(f.as_uri())
                more = pg.evaluate(sc.OVERFLOW_JS)
                pg.evaluate(sc.OPEN_OVERFLOW_JS, more[1]["j"])
                title = pg.title()
            finally:
                b.close()
        self.assertEqual([(t["label"], t["depth"]) for t in more], [("B", 0), ("C", 0)])
        self.assertEqual(title, "C")

    @unittest.skipUnless(HAVE_PLAYWRIGHT, "needs playwright and a Chromium")
    def test_wide_content_is_cut_off_unless_a_box_scrolls_sideways(self):
        from playwright.sync_api import sync_playwright
        row = "<tr>" + "".join(f"<td style='min-width:120px'>c{i}</td>" for i in range(5)) + "</tr>"
        page = ("<html><body style='margin:0'>"
                f"<table id=bare>{row}</table>"
                f"<div style='overflow-x:auto'><table id=wrapped>{row}</table></div>"
                f"<div style='position:relative;left:900px'><table id=offscreen>{row}</table></div>"
                "<table id=fits><tr><td>a</td><td>b</td></tr></table></body></html>")
        with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
            f = Path(d) / "page.html"
            f.write_text(page)
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 390, "height": 844})
                pg.goto(f.as_uri())
                cut = sc.scan_cut(pg)
            finally:
                b.close()
        # the bare table, and the page, which now pans sideways
        self.assertEqual([x["box"] for x in cut], ["table#bare", "page"])
        self.assertGreater(cut[0]["width"], cut[0]["room"])

    @unittest.skipUnless(HAVE_PLAYWRIGHT, "needs playwright and a Chromium")
    def test_a_long_link_that_does_not_wrap_pans_the_page(self):
        from playwright.sync_api import sync_playwright
        link = "<p style='margin:0 16px'>Weights <a href=#>" + "scrollprize/dinovol_8um_ps192_102126" * 2 + "</a></p>"
        got = {}
        with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                for name, css in (("bare", ""), ("wraps", "a{overflow-wrap:anywhere}")):
                    f = Path(d) / f"{name}.html"
                    f.write_text(f"<html><head><style>{css}</style></head><body style='margin:0'>{link}</body></html>")
                    pg = b.new_page(viewport={"width": 390, "height": 844})
                    pg.goto(f.as_uri())
                    got[name] = sc.scan_cut(pg)
                    pg.close()
            finally:
                b.close()
        self.assertEqual([x["box"] for x in got["bare"]], ["page"])
        self.assertEqual(got["wraps"], [])


class Spelling(unittest.TestCase):
    def test_british_words_are_found_in_prose_and_code(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "app.py").write_text("class FibreError(Exception):\n    pass\n"
                                      "def fibres_box(colour='grey'):\n    \"\"\"Labelled centres, normalised.\"\"\"\n")
            got = sc.spelling([d], root=d)
            words = sorted(x.split(": ")[1].split(" ->")[0] for x in got)
            self.assertEqual(words, ["Fibre", "Labelled", "centres", "colour", "fibres", "grey", "normalised"])
            self.assertIn("app.py:3: colour -> color", got)

    def test_less_common_british_words_are_known(self):
        for gb, us in (("smouldering", "smoldering"), ("sceptical", "skeptical"), ("splendour", "splendor"),
                       ("synchronised", "synchronized"), ("manoeuvring", "maneuvering"), ("speciality", "specialty")):
            self.assertEqual(sc.BRITISH.get(gb), us)

    def test_american_and_shared_words_pass(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.md").write_text("Fibers, colors and centers, labeled and modeled. The analyses advertise an "
                                    "exercise: realize, organize, travel toward the catalog. License: MIT.\n")
            self.assertEqual(sc.spelling([d], root=d), [])

    def test_allow_list_keeps_names_from_others(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "NOTICE").write_text("Data under the Open Government Licence v3.0.\n")
            old = list(sc.ALLOW_SPELLING)
            try:
                sc.ALLOW_SPELLING.append(("NOTICE", "Open Government Licence", "a license's own name"))
                self.assertEqual(sc.spelling([d], root=d), [])
            finally:
                sc.ALLOW_SPELLING[:] = old
            self.assertEqual(len(sc.spelling([d], root=d)), 1)

    def test_allow_entry_covers_every_occurrence_on_a_line(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.md").write_text("Keys: `licence`, `file`; `licence` is the dataset's own spelling.\n")
            old = list(sc.ALLOW_SPELLING)
            try:
                sc.ALLOW_SPELLING.append(("a.md", "`licence`", "a published key named twice on one line"))
                self.assertEqual(sc.spelling([d], root=d), [])
            finally:
                sc.ALLOW_SPELLING[:] = old
            self.assertEqual(len(sc.spelling([d], root=d)), 2)

    def test_every_allow_entry_has_a_reason(self):
        for glob, text, reason in sc.ALLOW_SPELLING:
            self.assertTrue(glob and text and len(reason) > 8, (glob, text, reason))


class Repository(unittest.TestCase):
    def test_every_space_has_a_current_wired_panel(self):
        self.assertEqual(sc.check(), [])


if __name__ == "__main__":
    unittest.main()
