"""Lasagna Fields (spaces/lasagna-fields): the box it makes, villa's command line for it, and the ZeroGPU worker fix.

Runs without network or the model: the scan's metadata is faked, and villa is never imported."""

import importlib.util
import multiprocessing as mp
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "lasagna-fields"

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:  # pragma: no cover
    HAVE_NUMPY = False


def _load():
    spec = importlib.util.spec_from_file_location("lasfield_under_test", SPACE / "lasfield.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _square(x):
    return x * x


def _pool_in_daemon(q):
    L = sys.modules.get("lasfield_under_test") or _load()
    try:
        with mp.Pool(2) as pool:
            pool.map(_square, [1])
        q.put("plain pool started")
    except AssertionError:
        q.put("plain pool refused")
    with L._pool_friendly():
        with mp.Pool(2) as pool:
            q.put(("friendly", pool.map(_square, [1, 2, 3])))


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.L = _load()
        # PHerc0139 2.399 um: level 0 and level 2 shapes as the open data lists them (25 Oct 2026)
        shapes = {0: [76945, 26511, 26511], 2: [19237, 6628, 6628]}
        cls.L.volume = lambda vid: {"volume": vid, "sample": "PHerc0139", "long_id": "x", "voxel_um": 2.399,
                                    "url": "https://example.invalid/x.zarr/", "level": 2}
        cls.L.zarray = lambda v, level: {"shape": shapes[level], "chunks": [128, 128, 128], "dtype": "|u1"}

    def test_box_holds_the_point_on_whole_blocks(self):
        for point in ([39424, 10752, 13824], [100, 100, 100], [76944, 26510, 26510]):
            for size in (256, 512):
                p = self.L.plan("20260930100252", *point, size=size)
                for c, o, s in zip(point, p["origin_level0_zyx"], p["size_level0_zyx"]):
                    self.assertTrue(o <= c < o + s or s < size * 4, (point, size, p["origin_level0_zyx"]))
                    self.assertEqual(o % (self.L.ALIGN * 4), 0)

    def test_plan_names_the_point_in_american_english(self):
        """plan_field's JSON and the receipt name the point center_level0_zyx (American spelling since 27 Oct 2026);
        the zip's name is built from it."""
        p = self.L.plan("20260930100252", 39424, 10752, 13824)
        self.assertEqual(p["center_level0_zyx"], [39424, 10752, 13824])
        self.assertEqual(sorted(k for k in p if "level0" in k),
                         ["center_level0_zyx", "origin_level0_zyx", "size_level0_zyx"])

    def test_refuses_points_outside_and_sizes_not_offered(self):
        with self.assertRaises(self.L.FieldError):
            self.L.plan("20260930100252", 80000, 10, 10)
        with self.assertRaises(self.L.FieldError):
            self.L.plan("20260930100252", 39424, 10752, 13824, size=300)

    def test_crop_is_level0_x_y_z(self):
        p = self.L.plan("20260930100252", 39424, 10752, 13824)
        argv = self.L.predict3d_argv(p, "ct", "out.lasagna.json", "w.pt", "cuda")
        i = argv.index("--crop")
        self.assertEqual(argv[i + 1:i + 7], ["13312", "10240", "38912", "1024", "1024", "1024"])
        self.assertEqual(argv[argv.index("--tile-size") + 1], "192")

    def test_selftest(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("needs Pillow")
        self.assertTrue(self.L.selftest()["passed"])

    def test_own_fields_are_the_ten_scans_of_the_card(self):
        card = (SPACE / "README.md").read_text(encoding="utf-8")
        samples = sorted(s for s, _ in self.L.OWN_FIELDS.values())
        self.assertEqual(len(samples), 10)
        for s in samples:
            self.assertIn(s, card)
        for vid, (_, run) in self.L.OWN_FIELDS.items():
            self.assertTrue(run.startswith(vid + "-lasagna-de45f011"), run)


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestGuidePictures(unittest.TestCase):
    def test_guide_pictures_point_at_the_file_route(self):
        """The guide's previews are built as assets/... in its script; inside the page they must use Gradio's file
        route (a <base> of /gradio_api/file= turned them into /gradio_api/assets/..., which 404s)."""
        import html
        raw = (SPACE / "guide" / "index.html").read_text(encoding="utf-8")
        self.assertIn("'assets/", raw)                      # the control: the guide itself uses relative paths
        app = _load_app()
        page = html.unescape(app.guide_html())
        self.assertNotIn("<base", page)
        self.assertNotIn("'assets/", page)
        self.assertNotIn('"assets/', page)
        self.assertIn("'/gradio_api/file=assets/", page)


def _load_app():
    sys.path.insert(0, str(SPACE))
    try:
        spec = importlib.util.spec_from_file_location("lasagna_app_under_test", SPACE / "app.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
    finally:
        sys.path.remove(str(SPACE))
    return app


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestOneScrollBar(unittest.TestCase):
    """User decision, 27 October 2026: the page scrolls as a whole, and nothing inside it keeps a vertical scroll bar."""

    def test_head_carries_the_one_scroll_fragment(self):
        app = _load_app()
        frag = (SPACE / "onescroll.html").read_text(encoding="utf-8")
        self.assertIn("<!-- space-onescroll:start -->", frag)
        self.assertIn(frag, app.HEAD)

    def test_guide_frame_has_no_fixed_height(self):
        import re
        app = _load_app()
        rule = re.search(r"\.lf-guide iframe\s*\{([^}]*)\}", app.CSS)
        self.assertIsNotNone(rule)                           # the control: the rule the old fixed height lived in
        self.assertNotIn("100vh", app.CSS)
        self.assertNotRegex(rule.group(1), r"(^|[;\s])height\s*:")

    def test_guide_code_blocks_grow(self):
        import re
        raw = (SPACE / "guide" / "index.html").read_text(encoding="utf-8")
        rule = re.search(r"(?m)^pre\{([^}]*)\}", raw)
        self.assertIsNotNone(rule)                           # the control: the guide still styles its code blocks
        self.assertNotIn("max-height", rule.group(1))
        self.assertIn("overflow-x:auto", rule.group(1))
        self.assertNotRegex(rule.group(1), r"(^|;)overflow:(auto|scroll)")

    def test_receipt_and_download_grow(self):
        """After a run, the receipt (Gradio's JSON caps itself at 500 px) and the download's file row (height=88)
        would scroll inside the page; both grow instead."""
        app = _load_app()
        src = (SPACE / "app.py").read_text(encoding="utf-8")
        self.assertIn('elem_id="lf-dl"', src)                # the control: the boxes the rules name exist
        self.assertIn('gr.JSON(max_height=None, elem_id="lf-receipt")', src)
        self.assertRegex(app.CSS, r"#lf-dl \.file-preview-holder\s*\{[^}]*max-height:none !important;[^}]*overflow:visible")
        self.assertRegex(app.CSS, r"#lf-receipt\s*\{[^}]*max-height:none !important;[^}]*overflow:visible")


class TestFieldList(unittest.TestCase):
    """fields.json: every whole-scan field the first tab lists, by scroll (30 Oct 2026)."""

    @classmethod
    def setUpClass(cls):
        import json
        cls.doc = json.loads((SPACE / "fields.json").read_text(encoding="utf-8"))
        cls.rows = cls.doc["fields"]
        prizes = json.loads((ROOT / "kit" / "data" / "prizes-2026-10-11.json").read_text(encoding="utf-8"))
        cls.eligible = {e["scroll"] for p in prizes["prizes"] for e in (p.get("eligible") or [])}

    def test_rows_are_complete_and_sorted(self):
        self.assertGreater(len(self.rows), 10)                # the control: more than the ten of 24 Oct
        keys = [(r["scroll"].lower(), r["volume"], r["model"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))
        for r in self.rows:
            self.assertRegex(r["volume"], r"^\d{14}$")
            self.assertTrue(r["zarr"].startswith(r["volume"] + "-"), r)
            self.assertIn(r["model"], ("villa predict3d", "Lasagnetta 0.1.1"))
            self.assertIn(r["source"], ("open-data", "dataset"))
            self.assertGreater(r["bytes"], 0)
            self.assertTrue(r["url"].startswith("https://"), r)
            if r["source"] == "dataset":
                self.assertEqual(r["url"], "https://huggingface.co/datasets/" + r["dataset"])
            else:
                self.assertTrue(r["manifest"].endswith(".lasagna.json"), r)
                self.assertIn(f"/{r['scroll']}/representations/predictions/lasagna/", r["stream"])

    def test_never_lists_a_scroll_the_space_refuses(self):
        never = _load().REFUSED_SAMPLES
        rows = self.rows + self.doc.get("pending_not_public", {}).get("items", [])
        self.assertTrue(never and rows)                       # the control: there is something to compare
        self.assertFalse(never & {r["scroll"].lower() for r in rows})
        text = (SPACE / "fields.json").read_text(encoding="utf-8").lower()
        for s in never:
            self.assertNotIn(s, text)

    def test_prize_scrolls_only_as_listed_before(self):
        """No new entry for a scroll on a prize list: only the ten SharpMeow datasets listed since 24 Oct 2026."""
        L = _load()
        ten = {s for s, _ in L.OWN_FIELDS.values()}
        listed = {r["scroll"] for r in self.rows}
        self.assertTrue(self.eligible & listed)               # the control: the ten include prize-list scrolls
        for r in self.rows:
            if r["scroll"] in self.eligible:
                self.assertIn(r["scroll"], ten, r)
                self.assertEqual((r["source"], r["model"]), ("dataset", "villa predict3d"), r)
        for r in self.doc.get("pending_not_public", {}).get("items", []):
            self.assertNotIn(r["scroll"], self.eligible, r)

    def test_ten_bucket_fields_are_listed_with_their_stream(self):
        L = _load()
        own = {vid: run for vid, (_, run) in L.OWN_FIELDS.items()}
        rows = {r["volume"]: r for r in self.rows if r.get("gallery")}
        self.assertEqual(set(rows), set(own))
        for vid, r in rows.items():
            self.assertTrue(r["stream"].endswith("/" + own[vid]), r)

    def test_card_names_every_dataset(self):
        card = (SPACE / "README.md").read_text(encoding="utf-8")
        for r in self.rows:
            if r["dataset"]:
                self.assertIn("- " + r["dataset"] + "\n", card)

    def test_pending_are_never_links(self):
        pend = self.doc.get("pending_not_public")
        if not pend:
            self.skipTest("no fields waiting")
        for r in pend["items"]:
            self.assertFalse({"url", "dataset", "stream", "manifest"} & set(r), r)
        live = {(r["scroll"], r["volume"]) for r in self.rows}
        self.assertFalse(live & {(r["scroll"], r["volume"]) for r in pend["items"]})


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestFieldListOnThePage(unittest.TestCase):
    def test_guide_ids_are_unique(self):
        """The list's data block once took the hero drawing's id, so the page read the drawing instead."""
        import collections
        import re
        raw = (SPACE / "guide" / "index.html").read_text(encoding="utf-8")
        ids = collections.Counter(re.findall(r'\sid="([^"]+)"', raw))
        self.assertIn("fieldlist", ids)                       # the control: the ids are found
        self.assertEqual([k for k, n in ids.items() if n > 1], [])

    def test_guide_gets_the_list_and_the_api_leaves_pending_out(self):
        import html
        import json
        app = _load_app()
        raw = (SPACE / "guide" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script id="fieldlist" type="application/json">null</script>', raw)   # the control
        page = html.unescape(app.guide_html())
        got = json.loads(page.split('<script id="fieldlist" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(got, app.field_doc())
        rows = app.list_fields()
        self.assertEqual(len(rows), len(app.field_doc()["fields"]))
        pend = {(r["scroll"], r["volume"]) for r in app.field_doc().get("pending_not_public", {}).get("items", [])}
        self.assertFalse(pend & {(r["scroll"], r["volume"]) for r in rows})
        self.assertTrue(all("139" in r["scroll"] for r in app.list_fields("pherc0139")))
        self.assertTrue(app.list_fields("pherc0139"))
        self.assertIn(f'{app.field_counts()["scrolls"]} Herculaneum scrolls', app.HEAD)

    def test_make_a_field_names_a_listed_dataset(self):
        app = _load_app()
        row = next(r for r in app.field_doc()["fields"] if r["dataset"] and not r.get("stream"))
        fake = {"volume": row["volume"], "sample": row["scroll"], "voxel_um": row["voxel_um"], "level": 0,
                "shape_zyx": [1, 1, 1]}
        app.L.volume = lambda vid: dict(fake, volume=vid)
        app.L.published_field = lambda v: None
        self.assertIn(row["dataset"], app.volume_text(row["volume"]))
        self.assertNotIn("SharpMeow/", app.volume_text("20000101000000"))   # the control: a volume not listed


@unittest.skipUnless(HAVE_NUMPY and "fork" in mp.get_all_start_methods(), "needs numpy and fork")
class TestZeroGpuWorker(unittest.TestCase):
    def test_pool_starts_inside_a_daemon_process(self):
        """ZeroGPU runs the GPU call in a daemon process, where villa's pyramid pool would be refused."""
        _load()
        ctx = mp.get_context("fork")
        q = ctx.Queue()
        proc = ctx.Process(target=_pool_in_daemon, args=(q,), daemon=True)
        proc.start()
        proc.join(60)
        got = [q.get(timeout=5), q.get(timeout=5)]
        self.assertEqual(got[0], "plain pool refused")
        self.assertEqual(got[1], ("friendly", [1, 4, 9]))


if __name__ == "__main__":
    unittest.main()
