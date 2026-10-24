"""Tests for kit/spaceconnect.py: the Connect your tool panel every Space carries."""

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

    def test_neuroglancer_link_round_trips(self):
        link = sc.neuroglancer_link(ZARR["url"], "CT")
        state = json.loads(urllib.parse.unquote(link.split("#!", 1)[1]))
        self.assertEqual(state["layers"][0]["source"], f"zarr://{ZARR['url']}/")
        ng = dict((t[0], t[3]) for t in sc._tools(dict(ZARR, ng_path="1")))["neuroglancer"]
        self.assertIn(urllib.parse.quote(f"{ZARR['url']}/1/", safe=""), ng)


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
            self.assertEqual(len(sc.render(d)), 3)
            self.assertEqual(sc.render(d, write=False), [])
            self.assertIn('id="connect"', (d / "index.html").read_text())
            self.assertTrue(sc.wired(d, "static"))
            self.assertFalse(sc.wired(d, "gradio"))

    def test_runnable_skips_paused_and_large_downloads(self):
        got = list(sc.runnable(spec(dict(DATASET, size="50 GB"), dict(API, status="paused"))))
        self.assertEqual([g[1] for g in got], ["hub", "datasets", "pandas", "cli", "curl"])
        hub = got[0][3]
        self.assertFalse(any(l.startswith("pip install") for c in got for l in c[3].splitlines()))
        self.assertNotIn("folder = snapshot_download", hub)


class Repository(unittest.TestCase):
    def test_every_space_has_a_current_wired_panel(self):
        self.assertEqual(sc.check(), [])


if __name__ == "__main__":
    unittest.main()
