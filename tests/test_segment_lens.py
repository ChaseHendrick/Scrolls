"""Segment Lens (spaces/segment-lens): its preview reader matches kit.atlas's writer, and the page keeps its promises."""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from kit import atlas

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "segment-lens"
APP = (SPACE / "app.js").read_text(encoding="utf-8")

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def _parse_lens_source():
    """The page's parseLens function, as text."""
    m = re.search(r"function parseLens\(raw\) \{.*?\n\}\n", APP, re.S)
    assert m, "parseLens not found in app.js"
    return m.group(0)


class TestPage(unittest.TestCase):
    def test_header_offsets_match_the_python_format(self):
        self.assertIn(f"'{atlas.LENS_MAGIC.decode()}'", APP)
        # magic (4) + three uint16 (6) + six float32 (24) = 34 bytes before the planes
        self.assertEqual(4 + 6 + 24, 34)
        src = _parse_lens_source()
        for needle in ("getUint16(4, true)", "getUint16(6, true)", "getUint16(8, true)", "getFloat32(10 + 4 * i",
                       "getFloat32(22 + 4 * i", "34 + 2 * n * i", "34 + 6 * n"):
            self.assertIn(needle, src)

    def test_card_links_the_dataset_and_page_reads_only_it(self):
        card = (SPACE / "README.md").read_text(encoding="utf-8")
        self.assertIn(atlas.DATASET, card)
        self.assertIn(f"https://huggingface.co/datasets/{atlas.DATASET}/resolve/main/", APP)
        # meshes are drawn only from the atlas's lens files, never fetched from the bucket
        self.assertNotRegex(APP, r"fetch\([^)]*(S3|amazonaws)")
        self.assertIn("if (!row.lens)", APP)

    def test_no_long_dashes(self):
        for f in SPACE.iterdir():
            if f.suffix in (".js", ".html", ".css", ".md") or f.name == "NOTICE":
                text = f.read_text(encoding="utf-8")
                self.assertNotIn("\u2014", text, f.name)
                self.assertNotIn("\u2013", text, f.name)

    def test_one_scroll_bar_at_a_time(self):
        """A one-screen viewer keeps one scrolling box (user decision, 27 October 2026): the segment list scrolls, the card never
        does, and the table or the guide takes over while it is open."""
        css = (SPACE / "style.css").read_text(encoding="utf-8")
        for card in re.findall(r"\.br \{([^}]*)\}", css):
            self.assertNotRegex(card, r"overflow(-y)?:\s*(auto|scroll|overlay)")
        # on a window too short for it the card is cut, not scrolled, so its top (and the NUMBERS fold) stays on screen
        self.assertIn("overflow: clip;", re.search(r"^\.br \{([^}]*)\}", css, re.M).group(1))
        self.assertIn("html.covered .list { overflow: hidden; }", css)
        self.assertIn("html.guide .tablewrap { overflow: hidden; }", css)
        self.assertIn("$('picker').hidden = $('card').hidden = table;", APP)
        self.assertIn("document.documentElement.classList.toggle('guide', guide);", APP)
        self.assertIn("$('about').addEventListener('close', cover);", APP)
        head = (SPACE / "index.html").read_text(encoding="utf-8").split("</head>")[0]
        self.assertIn("<!-- space-onescroll:start -->", head)

    def test_agent_calls_are_documented(self):
        page = (ROOT / "docs" / "tools" / "segment-lens.md").read_text(encoding="utf-8")
        block = re.search(r"window\.segmentLens = \{(.*?)\n\};", APP, re.S).group(1)
        calls = re.findall(r"^\s{2}(\w+):", block, re.M)
        self.assertTrue(calls)
        for c in calls:
            self.assertIn(f"`{c}", page, c)


@unittest.skipIf(np is None or not shutil.which("node"), "needs numpy and Node.js")
class TestReaderRoundTrip(unittest.TestCase):
    def test_page_reads_what_the_atlas_writes(self):
        from kit import tifxyz
        r, c = np.mgrid[0:300, 0:140].astype(float)
        xyz = np.stack([1000 + c * 20, 2000 + r * 20, 500 + 300 * np.sin(c / 20)], -1)
        xyz[100:110, 50:60] = -1
        seg = tifxyz.Segment(xyz, (xyz > -0.5).all(-1), {"scale": [0.05, 0.05]}, "t", 2.0)
        _, m = atlas.measure(seg)
        blob = atlas.lens_grid(seg, m, side=64)
        h, w, k, lo, hi, back, flags = atlas.read_lens(blob)
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw.bin"
            import gzip
            raw.write_bytes(gzip.decompress(blob))
            js = Path(d) / "t.mjs"
            js.write_text(_parse_lens_source() + f"""
import {{ readFileSync }} from 'fs';
const g = parseLens(new Uint8Array(readFileSync({json.dumps(str(raw))})));
let fl = 0; for (const f of g.flags) if (f & 1) fl++;
let miss = 0; for (const v of g.q[0]) if (v === 65535) miss++;
console.log(JSON.stringify({{h: g.h, w: g.w, k: g.k, lo: g.lo, hi: g.hi, holes: fl, missing: miss, q0: g.q[2][5 * g.w + 7]}}));
""")
            out = json.loads(subprocess.run(["node", str(js)], capture_output=True, text=True, check=True).stdout)
        self.assertEqual((out["h"], out["w"], out["k"]), (h, w, k))
        np.testing.assert_allclose(out["lo"], lo, rtol=1e-6)
        np.testing.assert_allclose(out["hi"], hi, rtol=1e-6)
        self.assertEqual(out["holes"], int((flags & 1).astype(bool).sum()))
        self.assertGreater(out["holes"], 0)
        self.assertEqual(out["missing"], int(np.isnan(back[..., 0]).sum()))
        z = lo[2] + out["q0"] / 65534 * (hi[2] - lo[2])
        self.assertAlmostEqual(z, back[5, 7, 2], places=3)


def _load_server():
    """spaces/segment-lens/app.py as a module, without starting it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("segment_lens_server", SPACE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(np is None, "needs numpy")
class TestAgentTools(unittest.TestCase):
    """The server's API and MCP tools (app.py) against a small atlas built here with kit.atlas."""

    def setUp(self):
        from kit import tifxyz
        self.srv = _load_server()
        r, c = np.mgrid[0:120, 0:90].astype(float)
        xyz = np.stack([1000 + c * 20, 2000 + r * 20, 500 + 200 * np.sin(c / 15)], -1)
        xyz[40:48, 30:38] = -1
        seg = tifxyz.Segment(xyz, (xyz > -0.5).all(-1), {"scale": [0.05, 0.05]}, "t", 2.0)
        _, m = atlas.measure(seg)
        self.blob = atlas.lens_grid(seg, m, side=48)
        base = {"kind": "mesh", "url": self.srv.S3 + "PHerc0139/segments/a/mesh/a.tifxyz", "prize_lists": []}
        self.rows = [dict(base, id="PHerc0139/a/a.tifxyz", scroll="PHerc0139", segment="a", area_cm2=10.0,
                          lens="a.slg.gz"),
                     dict(base, id="PHerc0139/b/b.tifxyz", scroll="PHerc0139", segment="b", area_cm2=20.0,
                          lens="b.slg.gz"),
                     dict(base, id="PHercParis4/c/c.tifxyz", scroll="PHercParis4", segment="c", area_cm2=30.0,
                          lens=None, prize_lists=["first-letters"])]
        blob = self.blob

        def get(url):
            if url.endswith("atlas.jsonl"):
                return "\n".join(json.dumps(r) for r in self.rows).encode()
            if url.endswith(".slg.gz"):
                return blob
            raise AssertionError(url)
        self.srv._get = get
        self.srv._atlas.update(rows=None, at=0.0)
        self.srv.atlas_rows.__defaults__ = (get,)
        self.srv.load_lens.__defaults__ = (get,)

    def test_reader_matches_kit(self):
        h, w, k, xyz, flags = self.srv.parse_lens(self.blob)
        h2, w2, k2, lo, hi, xyz2, flags2 = atlas.read_lens(self.blob)
        self.assertEqual((h, w, k), (h2, w2, k2))
        np.testing.assert_array_equal(flags, flags2)
        np.testing.assert_allclose(np.nan_to_num(xyz), np.nan_to_num(xyz2))
        with self.assertRaises(self.srv.LensError):
            self.srv.parse_lens(__import__("gzip").compress(b"NOPE" + bytes(40)))

    def test_lists_and_sorting(self):
        sc = self.srv.list_scrolls()
        self.assertEqual([s["scroll"] for s in sc["scrolls"]], ["PHerc0139", "PHercParis4"])
        self.assertEqual(sc["scrolls"][0]["previews"], 2)
        segs = self.srv.list_segments("PHerc0139", "area_cm2", 5, False)
        self.assertEqual([r["segment"] for r in segs["segments"]], ["b", "a"])
        allp = self.srv.list_segments("", "area_cm2", 5, True)
        self.assertNotIn("PHercParis4/c/c.tifxyz", [r["id"] for r in allp["segments"]])
        for bad in (("PHerc0139", "nope", 5, False), ("PHerc0139", "area_cm2", 0, False), ("X", "area_cm2", 5, False)):
            with self.assertRaises(self.srv.LensError):
                self.srv.list_segments(*bad)

    def test_get_segment_and_pictures(self):
        g = self.srv.get_segment("PHerc0139/a/a.tifxyz")
        self.assertIn("s3://vesuvius-challenge-open-data/", g["kit_command"])
        self.assertGreater(g["preview"]["flags"]["hole"], 0)
        self.assertTrue(g["open_in_browser"].endswith("#id=PHerc0139/a/a.tifxyz"))
        self.assertIn("prize list", self.srv.get_segment("PHercParis4/c/c.tifxyz")["preview"]["none"])
        with self.assertRaises(self.srv.LensError):
            self.srv.get_segment("nope")
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("needs Pillow")
        for view in ("3d", "grid"):
            img, info = self.srv.segment_picture("PHerc0139/a/a.tifxyz", view, 30, 20)
            self.assertGreater(img.size[0], 100)
            self.assertEqual(info["flags"], g["preview"]["flags"])
        # a prize-list scroll never gets a picture
        with self.assertRaisesRegex(self.srv.LensError, "prize list"):
            self.srv.segment_picture("PHercParis4/c/c.tifxyz", "3d", 30, 20)
        for bad in (("PHerc0139/a/a.tifxyz", "side", 30, 20), ("PHerc0139/a/a.tifxyz", "3d", 30, 120)):
            with self.assertRaises(self.srv.LensError):
                self.srv.segment_picture(*bad)

    def test_server_serves_the_page_files(self):
        for name in self.srv.WEB_FILES:
            self.assertTrue((SPACE / name).is_file(), name)
        card = (SPACE / "README.md").read_text(encoding="utf-8")
        self.assertIn("app_file: app.py", card)
        self.assertIn("/agents/gradio_api/mcp/", card)
        self.assertEqual(re.search(r"const VERSION = '([\d.]+)'", APP).group(1), self.srv.VERSION)
        # with SSR on, Spaces gives port 7860 to a Node server and uvicorn cannot bind (24 Oct 2026)
        self.assertIn("ssr_mode=False", (SPACE / "app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
