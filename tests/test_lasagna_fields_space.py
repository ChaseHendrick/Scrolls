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
        sys.path.insert(0, str(SPACE))
        try:
            spec = importlib.util.spec_from_file_location("lasagna_app_under_test", SPACE / "app.py")
            app = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(app)
        finally:
            sys.path.remove(str(SPACE))
        page = html.unescape(app.guide_html())
        self.assertNotIn("<base", page)
        self.assertNotIn("'assets/", page)
        self.assertNotIn('"assets/', page)
        self.assertIn("'/gradio_api/file=assets/", page)


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
