"""Umbilici (spaces/umbilici): the line table builder, the lasagna helpers and the page's own promises. No network."""

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "umbilici"

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build_lines = load("umbilici_build_lines", SPACE / "tools" / "build_lines.py")
# the dataset's own published spelling of its license key (index.json); data/lines.json and app.js keep it
PUBLISHED = "licence"


def fake_dataset(root):
    """A two-scan copy of the center-lines dataset: one scan with two people's lines, one with a finder line."""
    files = [
        {"scroll": "PHerc0001", "scan": "20250101000000", "source": "drobkov", "kind": "person", "credit": "Alexey Drobkov",
         PUBLISHED: "MIT", "upstream": "https://example.org/a", "file": "lines/PHerc0001/a.json", "sha256": "0" * 64,
         "z": [100.0, 300.0], "note": "", "volume": "20250101000000-9.362um-1.2m-113keV-masked.zarr"},
        {"scroll": "PHerc0001", "scan": "20250101000000", "source": "tauil", "kind": "person", "credit": "Abd Elilah",
         PUBLISHED: "CC BY 4.0", "upstream": "https://example.org/b", "file": "lines/PHerc0001/b.json", "sha256": "1" * 64,
         "z": [120.0, 280.0], "note": "withdrawn from recommended use by its author", "volume": None},
        {"scroll": "PHerc0002", "scan": "20250202000000", "source": "finder", "kind": "model", "credit": "Chase Hendrick",
         PUBLISHED: "CC BY-NC 4.0", "upstream": "made here", "file": "lines/PHerc0002/c.json", "sha256": "2" * 64,
         "z": [10.0, 50.0], "note": "end check FLAG; usable ends: high; no end checked on CT by a person",
         "volume": "20250202000000-8.640um-1.2m-116keV-masked.zarr"},
    ]
    scrolls = {"PHerc0001": {"scan": "20250101000000", "first_letters": True, "grand_prize": True},
               "PHerc0002": {"scan": "20250202000000", "first_letters": True, "grand_prize": False}}
    points = {"a": [(10, 20, 300), (11, 21, 100), (12, 22, 200)], "b": [(9, 19, 120), (9, 19, 280)],
              "c": [(5.4, 6.6, 50), (5, 6, 10)]}
    for f in files:
        p = root / f["file"]
        p.parent.mkdir(parents=True, exist_ok=True)
        cps = [{"x": x, "y": y, "z": z, "score": 100} for x, y, z in points[p.stem]]
        md = {"secret": "never copied"}
        if p.stem == "a":  # the frame stamp VC3D reads is copied; nothing else is
            md.update({"voxelsize_um": 9.362, "volume": f["volume"], "volume_width": 64, "volume_height": 64, "volume_slices": 400})
        p.write_text(json.dumps({"control_points": cps, "metadata": md}))
    (root / "index.json").write_text(json.dumps({"made": "test", "frame": "level-0 voxels", "scrolls": scrolls, "files": files}))


def fake_get_json(url):
    m = re.search(r"/(\d)/\.zarray$", url)
    if m:
        k = 2 ** int(m.group(1))
        return {"shape": [-(-400 // k), -(-64 // k), -(-64 // k)], "chunks": [128, 128, 128], "dtype": "|u1", "compressor": None}
    if url.endswith("/.zattrs"):
        return {"multiscales": [{"datasets": [{"path": str(i)} for i in range(6)]}]}
    raise AssertionError(url)


def solid_tile(shape, chunks, inside):
    """tile() for a synthetic level: inside(z, y, x) says which voxels are nonzero (value 7); others are zero."""
    def tile(zi, cy, cx):
        _, ch_y, ch_x = chunks
        return bytes(7 if (y < shape[1] and x < shape[2] and inside(zi, y, x)) else 0
                     for y in range(cy * ch_y, (cy + 1) * ch_y) for x in range(cx * ch_x, (cx + 1) * ch_x))
    return tile


def fake_open_slices(base, pyramid, um):
    # the fake scans' material: a 30 by 30 voxel block in the corner of every slice, where all the fake lines run
    shape, chunks = [400, 64, 64], [128, 32, 32]
    vol = build_lines.Volume(shape, chunks, solid_tile(shape, chunks, lambda z, y, x: y < 30 and x < 30))
    return build_lines.Slices(vol, 1, 1.0), 0


@contextmanager
def built(get_json=fake_get_json, open_slices=fake_open_slices):
    """build_lines.main without the network: the bucket's metadata from get_json, each scan's CT from open_slices."""
    with mock.patch.object(build_lines, "get_json", get_json), mock.patch.object(build_lines, "open_slices", open_slices), \
            mock.patch("builtins.print"):
        yield


class BuildLines(unittest.TestCase):
    def build(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_dataset(root)
            out = root / "lines.json"
            with built():
                build_lines.main(root, out)
            return json.loads(out.read_text())

    def test_scans_volumes_and_frames(self):
        t = self.build()
        self.assertEqual([s["scroll"] for s in t["scrolls"]], ["PHerc0001", "PHerc0002"])
        a, b = t["scrolls"]
        self.assertEqual(a["voxel_um"], 9.362)
        self.assertEqual(b["voxel_um"], 8.64)
        self.assertEqual(a["shape"], [400, 64, 64])
        self.assertEqual(a["levels"], 6)
        self.assertEqual([p["shape"] for p in a["pyramid"]][:3], [[400, 64, 64], [200, 32, 32], [100, 16, 16]])
        self.assertEqual({(p["dtype"], p["compressor"]) for p in a["pyramid"]}, {("|u1", None)})
        # a line with no volume of its own takes its scan's volume from another line of that scan
        self.assertTrue(a["zarr"].endswith("PHerc0001/volumes/20250101000000-9.362um-1.2m-113keV-masked.zarr"))
        self.assertTrue(a["zarr"].startswith(build_lines.S3))

    def test_points_sorted_by_height_and_rounded(self):
        a, b = self.build()["scrolls"]
        self.assertEqual(a["lines"][0]["points"], [11, 21, 100, 12, 22, 200, 10, 20, 300])
        self.assertEqual(b["lines"][0]["points"], [5, 6, 10, 5, 7, 50])

    def test_sources_grades_and_no_metadata(self):
        t = self.build()
        a, b = t["scrolls"]
        self.assertEqual([l["source"] for l in a["lines"]], ["drobkov", "tauil"])
        self.assertEqual([l["grade"] for l in a["lines"]], [None, None])
        self.assertEqual(b["lines"][0]["grade"], "FLAG")
        self.assertIn("withdrawn", a["lines"][1]["note"])
        self.assertNotIn("never copied", json.dumps(t))
        self.assertEqual(a["lines"][0]["stamp"], {"voxelsize_um": 9.362, "volume": "20250101000000-9.362um-1.2m-113keV-masked.zarr",
                                                  "volume_width": 64, "volume_height": 64, "volume_slices": 400})
        self.assertEqual(a["lines"][1]["stamp"], {})
        self.assertIsNone(b["lines"][0]["superseded_by"])  # copied from index.json; none in this copy
        # the license key is copied under the dataset's own spelling, so data/lines.json reads like index.json
        self.assertEqual([l[PUBLISHED] for l in a["lines"]], ["MIT", "CC BY 4.0"])
        self.assertEqual(set(t["sources"]), {"bucket", "drobkov", "tauil", "dopico", "finder", "finder-polished", "finder-v2"})

    def test_every_line_gets_the_ct_test_of_its_ends(self):
        # 1.13.0: a tested line carries per-end counts; one the test cannot judge carries null and the reason
        a, b = self.build()["scrolls"]
        o = a["lines"][0]["outside"]
        self.assertEqual((o["low"]["hidden"], o["high"]["hidden"]), (0, 0))
        self.assertEqual((o["level"], o["far_mm"], o["end_share"]), (0, 4.0, 0.25))
        self.assertIsNone(a["lines"][0]["outside_why"])
        self.assertIsNone(b["lines"][0]["outside"])  # two points: nothing to test
        self.assertIn("fewer than three points", b["lines"][0]["outside_why"])
        # the test never changes a line's points, file or hash
        self.assertEqual(a["lines"][0]["points"], [11, 21, 100, 12, 22, 200, 10, 20, 300])
        self.assertEqual(a["lines"][0]["sha256"], "0" * 64)

    def test_a_scan_the_test_cannot_read_is_marked_untested(self):
        def no_codec(base, pyramid, um):
            raise ImportError("numcodecs")
        def offline(base, pyramid, um):
            raise OSError("no network")
        for opener, why in ((no_codec, "no numcodecs"), (offline, "could not be opened (OSError)")):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                fake_dataset(root)
                with built(open_slices=opener):
                    build_lines.main(root, root / "lines.json")
                line = json.loads((root / "lines.json").read_text())["scrolls"][0]["lines"][0]
            self.assertIsNone(line["outside"])
            self.assertIn(why, line["outside_why"])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_dataset(root)
            with built(open_slices=mock.Mock(side_effect=AssertionError("opened"))):
                build_lines.main(root, root / "lines.json", "--no-ct")
            line = json.loads((root / "lines.json").read_text())["scrolls"][0]["lines"][0]
        self.assertIsNone(line["outside"])
        self.assertIn("--no-ct", line["outside_why"])

    def test_every_source_has_a_color_and_a_chip_style(self):
        app = (SPACE / "app.js").read_text()
        css = (SPACE / "style.css").read_text()
        hexes = app[app.index("const SRC_HEX"):].split("\n", 1)[0]
        for k in build_lines.SOURCES:
            self.assertIn(f"{k}: '#" if "-" not in k else f"'{k}': '#", hexes, k)
            self.assertIn(f".src.s-{k} ", css, k)


    def test_live_lines_keep_the_built_fields(self):
        # the page reads the dataset's newest revision at load (app.js liveData); its lines must carry the same
        # fields build_lines.py writes, so the rest of the page reads either the same way
        app = (SPACE / "app.js").read_text()
        live = app[app.index("async function liveLine"):]
        live = live[:live.index("\n}\n")]
        keys = app[app.index("const LINE_KEYS"):].split("\n", 1)[0]
        for k in ("source", "kind", "credit", "licence", "upstream", "file", "sha256", "z", "note"):
            self.assertIn(f"'{k}'", keys, k)
        for k in ("grade", "ends", "untested", "usable", "stamp", "points", "superseded_by", "outside", "outside_why"):
            self.assertIn(k, live, k)
        self.assertIn("data/lines.json", app[app.index("// ---------- boot"):])

    def test_per_end_ct_grades(self):
        # from v2.2 each Center Finder end has its own CT grade; a line is FLAG when either end is
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_dataset(root)
            ix = json.loads((root / "index.json").read_text())
            c = ix["files"][2]
            c["note"] = "CT end check: low PASS (CT recap), high FLAG; no end checked on CT by a person"
            c["ct_ends"] = {"low": {"grade": "PASS", "recapped": True, "D_mm": 1.1, "sweep_D_mm": 9.0},
                            "high": {"grade": "FLAG", "recapped": False, "D_mm": 10.7, "sweep_D_mm": 16.1}}
            (root / "index.json").write_text(json.dumps(ix))
            f = root / c["file"]
            doc = json.loads(f.read_text())
            doc["metadata"]["usable_ends"] = {"low": True, "high": False}
            f.write_text(json.dumps(doc))
            out = root / "lines.json"
            with built():
                build_lines.main(root, out)
            line = json.loads(out.read_text())["scrolls"][1]["lines"][0]
        self.assertEqual(line["grade"], "FLAG")
        self.assertEqual(line["ends"]["low"], {"grade": "PASS", "recapped": True, "D_mm": 1.1})
        self.assertEqual(line["usable"], ["low"])
        self.assertFalse(line["untested"])

    def test_scans_off_the_prize_page_come_last_and_untested_grades_are_marked(self):
        # v2.3 adds public scans that are not on the prize page; they follow the prize scans, and a Center Finder
        # line on a scan the CT end check was never tuned for (ct_untested_scan) carries untested
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_dataset(root)
            ix = json.loads((root / "index.json").read_text())
            ix["files"][0]["scroll"] = ix["files"][1]["scroll"] = "PHerc0000"
            ix["scrolls"]["PHerc0000"] = dict(ix["scrolls"].pop("PHerc0001"), first_letters=False, grand_prize=False)
            ix["files"][2].update(ct_untested_scan=True, ct_ends={"low": {"grade": "PASS", "recapped": False, "D_mm": 1.0}})
            (root / "index.json").write_text(json.dumps(ix))
            out = root / "lines.json"
            with built():
                build_lines.main(root, out)
            t = json.loads(out.read_text())
        self.assertEqual([s["scroll"] for s in t["scrolls"]], ["PHerc0002", "PHerc0000"])
        self.assertTrue(t["scrolls"][0]["lines"][0]["untested"])
        self.assertEqual([l["untested"] for l in t["scrolls"][1]["lines"]], [False, False])

    def test_a_compressed_pyramid_is_recorded(self):
        # center lines v2.6 adds PHerc0172, whose 7.91 um scan is stored with Blosc; the table names the codec so the
        # page knows it cannot range-read one plane of a chunk there
        def blosc(url):
            d = fake_get_json(url)
            return dict(d, compressor={"id": "blosc", "cname": "zstd"}) if url.endswith(".zarray") else d
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_dataset(root)
            out = root / "lines.json"
            with built(blosc):
                build_lines.main(root, out)
            t = json.loads(out.read_text())
        self.assertEqual({p["compressor"] for s in t["scrolls"] for p in s["pyramid"]}, {"blosc"})


class OutsideEnds(unittest.TestCase):
    """The CT test of line ends (build_lines.outside_ends) on synthetic masked scans: no network, no numpy."""

    SHAPE, CHUNKS = [200, 100, 100], [32, 32, 32]

    def slices(self, inside, vox_mm=0.5):
        vol = build_lines.Volume(self.SHAPE, self.CHUNKS, solid_tile(self.SHAPE, self.CHUNKS, inside))
        return build_lines.Slices(vol, 1, vox_mm)

    @staticmethod
    def disc(z, y, x):  # a scroll 20 voxels (10 mm) in radius about (50, 50), from z 20 to 179; air elsewhere
        return 20 <= z < 180 and (x + 0.5 - 50) ** 2 + (y + 0.5 - 50) ** 2 <= 400

    def line(self, shift=lambda i: 0, z0=20, z1=180, step=4):
        return [(50 + shift(i), 50, z) for i, z in enumerate(range(z0, z1, step))]

    def test_a_line_inside_the_scroll_hides_nothing(self):
        res, why = build_lines.outside_ends(self.line(), self.slices(self.disc))
        self.assertIsNone(why)
        self.assertEqual([res[k]["hidden"] for k in ("low", "high")], [0, 0])
        self.assertEqual([res[k]["far"] for k in ("low", "high")], [0, 0])

    def test_an_end_that_runs_off_sideways_is_hidden(self):
        # the first three points sit 15 voxels (7.5 mm) past the disc's edge, more than the 4 mm bar
        res, _ = build_lines.outside_ends(self.line(lambda i: 35 if i < 3 else 0), self.slices(self.disc))
        self.assertEqual(res["low"]["hidden"], 3)
        self.assertEqual(res["low"]["far"], 3)
        self.assertAlmostEqual(res["low"]["max_mm"], 7.5, delta=0.3)
        self.assertEqual(res["high"]["hidden"], 0)
        # 3 mm past the edge is under the bar, so nothing is hidden
        res, _ = build_lines.outside_ends(self.line(lambda i: 26 if i < 3 else 0), self.slices(self.disc))
        self.assertEqual(res["low"]["hidden"], 0)

    def test_an_excursion_that_comes_back_is_hidden_with_the_end(self):
        # points 1 and 2 run off, the end point is inside again: the run from the end to the innermost one is hidden
        res, _ = build_lines.outside_ends(self.line(lambda i: 35 if i in (1, 2) else 0), self.slices(self.disc))
        self.assertEqual((res["low"]["hidden"], res["low"]["far"]), (3, 2))

    def test_ends_in_slices_with_no_scroll(self):
        # the line runs from z 0 to 199; the scroll fills z 20 to 179 only
        res, _ = build_lines.outside_ends(self.line(z0=0, z1=200), self.slices(self.disc))
        self.assertEqual((res["low"]["hidden"], res["low"]["empty"]), (5, 5))
        self.assertEqual((res["high"]["hidden"], res["high"]["empty"]), (5, 5))
        self.assertIsNone(res["low"]["max_mm"])

    def test_a_gap_between_fragments_is_inside(self):
        # a tapering end breaks into two fragments; a point between them is near no voxel but inside the outline
        two = lambda z, y, x: 20 <= z < 180 and 30 <= y < 70 and (x < 35 or x >= 65)
        sl = self.slices(two)
        self.assertFalse(sl.material_near(50, 50, 40))
        res, _ = build_lines.outside_ends(self.line(), sl)
        self.assertEqual((res["low"]["hidden"], res["high"]["hidden"]), (0, 0))

    def test_the_interior_is_never_hidden(self):
        pts = self.line()
        n = len(pts)
        # every point but the middle one runs off: only the outer quarter at each end is hidden
        res, _ = build_lines.outside_ends(self.line(lambda i: 0 if i == n // 2 else 40), self.slices(self.disc))
        self.assertEqual((res["low"]["hidden"], res["high"]["hidden"]), (n // 4, n // 4))
        # one point inside the middle half runs off: nothing is hidden
        res, _ = build_lines.outside_ends(self.line(lambda i: 40 if i == n // 2 - 3 else 0), self.slices(self.disc))
        self.assertEqual((res["low"]["hidden"], res["high"]["hidden"]), (0, 0))

    def test_a_line_wholly_outside_is_untested(self):
        res, why = build_lines.outside_ends(self.line(lambda i: 40), self.slices(self.disc))
        self.assertIsNone(res)
        self.assertIn("middle point", why)

    def test_a_scan_whose_air_is_not_zero_is_untested(self):
        # the corner control: an unmasked scan reads as scroll everywhere, so the test cannot tell
        res, why = build_lines.outside_ends(self.line(), self.slices(lambda z, y, x: True))
        self.assertIsNone(res)
        self.assertIn("air is not zero", why)

    def test_short_lines_are_untested(self):
        res, why = build_lines.outside_ends(self.line()[:2], self.slices(self.disc))
        self.assertIsNone(res)
        self.assertIn("fewer than three", why)

    def test_hull_and_distance(self):
        h = build_lines.hull([(0, 0), (4, 0), (4, 4), (0, 4), (2, 2), (1, 3)])
        self.assertEqual(sorted(h), [(0, 0), (0, 4), (4, 0), (4, 4)])
        self.assertEqual(build_lines.hull_distance(h, (2, 2)), 0.0)
        self.assertAlmostEqual(build_lines.hull_distance(h, (7, 2)), 3.0)
        self.assertAlmostEqual(build_lines.hull_distance(h, (7, 8)), 5.0)
        self.assertAlmostEqual(build_lines.hull_distance([(0, 0), (4, 0)], (2, 3)), 3.0)

    def test_missing_chunks_read_as_air(self):
        vol = build_lines.Volume(self.SHAPE, self.CHUNKS, lambda zi, cy, cx: None)
        self.assertEqual(vol.rows(10, 0, 2, 95, 105), [bytes(10), bytes(10)])
        self.assertIsNone(build_lines.Slices(vol, 1, 0.5).hull_of(10))


@unittest.skipIf(np is None, "needs numpy")
class Lasagna(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.bl = load("umbilici_build_lasagna", SPACE / "tools" / "build_lasagna.py")
        except ImportError as e:  # numcodecs or Pillow missing
            raise unittest.SkipTest(str(e))

    def test_orientation_ignores_the_normal_sign(self):
        nx = np.array([[128 + 90, 128 - 90, 128 + 127]], np.uint8)
        ny = np.array([[128 + 89, 128 - 89, 128]], np.uint8)
        rgb = self.bl.orientation_rgb(nx, ny, np.ones((1, 3), np.float32))
        self.assertTrue(np.abs(rgb[0, 0].astype(int) - rgb[0, 1].astype(int)).max() <= 3)
        self.assertGreater(np.abs(rgb[0, 0].astype(int) - rgb[0, 2].astype(int)).max(), 40)

    def test_chunks_belong_to_the_part_that_owns_them(self):
        crop = [[1024, 2048], [0, 4608], [0, 2048]]
        self.assertTrue(self.bl.inside(crop, 8, (2, 0, 3)))      # level 3 chunk at z 1024, x 1536
        self.assertFalse(self.bl.inside(crop, 8, (2, 0, 4)))     # x 2048 belongs to the next part
        self.assertFalse(self.bl.inside(crop, 4, (3, 0, 0)))     # level 2 chunk at z 768


class Page(unittest.TestCase):
    def text(self, name):
        return (SPACE / name).read_text(encoding="utf-8")

    def test_no_long_dashes(self):
        for p in SPACE.rglob("*"):
            if p.is_file() and p.suffix in {".html", ".js", ".css", ".md", ".py", ""} and p.name != "LICENSE":
                t = p.read_text(encoding="utf-8")
                self.assertNotIn(chr(0x2014), t, p.name)
                self.assertNotIn(chr(0x2013), t, p.name)

    def test_agent_api_is_documented(self):
        api = re.search(r"window\.umbilici = \{(.*?)\n\};", self.text("app.js"), re.S).group(1)
        names = set(re.findall(r"^\s+(\w+):", api, re.M))
        self.assertEqual(names, {"version", "scans", "lines", "at", "select", "mode", "setZ", "state", "image", "slice",
                                 "stats", "table", "csv", "guide", "data", "settings", "bench", "show", "outside"})
        readme = self.text("README.md")
        for n in names - {"version"}:
            self.assertIn(f"`{n}(", readme, n)

    def test_every_setting_is_documented(self):
        # each key of the viewer's settings, including the slice panel's inset and turn, is named on the Space card
        keys = re.findall(r"(\w+):", re.search(r"const SET_DEFAULT = \{(.*?)\};", self.text("app.js")).group(1))
        row = next(l for l in self.text("README.md").splitlines() if l.startswith("| `settings(obj)`"))
        self.assertIn("inset", keys)
        for k in keys:
            self.assertIn(f"`{k}`", row, k)

    def test_no_ct_is_shipped(self):
        # CT is read by the visitor's browser from the open-data bucket; the Space ships no volume of its own
        self.assertIn("vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com", build_lines.S3)
        self.assertIn("data/", self.text(".gitignore"))
        for name in ("index.html", "app.js"):  # volume URLs are built from lines.json at run time, never hard-coded
            # except the Connect your tool panel (kit/spaceconnect.py), which links one example open-data volume
            text = re.sub(r"<!-- space-connect:start -->.*?<!-- space-connect:end -->", "", self.text(name), flags=re.S)
            self.assertNotRegex(text, r"https://[^\s\"'`]*\.zarr", name)

    def test_villa_reader_claims_cite_their_source(self):
        # the guide states how VC3D and spiral-fitting read these files; each claim names the villa file it came from
        html = self.text("index.html")
        self.assertIn("volume-cartographer/core/src/Umbilicus.cpp", html)
        self.assertIn("spiral-fitting/umbilicus.py", html)
        self.assertIn("scrollprize.org/tutorial_spiral", html)

    def test_center_finder_is_named_as_a_name(self):
        for name in ("index.html", "README.md", "NOTICE"):
            self.assertNotIn("center finder", self.text(name), name)
        self.assertEqual(build_lines.SOURCES["finder"]["label"], "Chase Hendrick's Center Finder")

    def test_a_compressed_scan_gets_no_ct_stream(self):
        # the page reads one axial plane of an uncompressed chunk per request; a scan with a compressor keeps its lines,
        # streams nothing and says why (1.10.0)
        app = self.text("app.js")
        self.assertIn("const streamable = (s) => !s.pyramid.some((p) => p.compressor);", app)
        self.assertIn("if (streamable(s)) loadVolume(s, scanGroup);", app)
        self.assertIn("} else if (!streamable(s)) {", app)
        self.assertIn("Blosc().decode(raw)", app)  # the guide's Python snippet decodes a whole chunk there
        # the Data dialog's scan rows have no source; reading one must not throw (the Scans tab was empty in 1.9.0)
        self.assertIn("class=\"${r.source?.startsWith('finder') ? 'cf' : ''}", app)

    def test_one_scrolling_panel_at_a_time(self):
        # user decision, 27 October 2026: the page never scrolls, and one panel scrolls at a time: the list in Array,
        # the scan card in X-ray and Lasagna (whose scan menu stands in for the list), an open dialog above both, and in
        # the Data dialog only its table
        html, css, app = self.text("index.html"), self.text("style.css"), self.text("app.js")
        head = html.split("</head>", 1)[0]
        self.assertRegex(head, r"(?s)<!-- space-onescroll:start -->.+<!-- space-onescroll:end -->")
        self.assertIn("html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg); overflow: hidden; }", css)
        top = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)  # rules outside media queries
        self.assertIn("body.focus .rail { display: none; }", top)
        self.assertIn("body.modal .rail, body.modal .card { overflow: hidden; }", top)
        self.assertIn(".sheet[open] { display: flex; flex-direction: column; overflow: hidden; }", top)
        self.assertNotIn("max-height", re.search(r"\.tbl-wrap \{([^}]*)\}", css).group(1))
        for fn in ("openGuide", "openSheet"):
            self.assertRegex(re.search(rf"function {fn}\(.*", app).group(0), r"showModal\(\); modalState\(\); \}$", fn)
        self.assertIn("document.querySelectorAll('dialog').forEach((d) => d.addEventListener('close', modalState));", app)
        self.assertIn('<select id="c-pick"', html)
        self.assertIn("buildRail(); buildPick();", app)

    def test_top_bar_fits_on_phones(self):
        # 1.10.0 ran the view buttons off a 390 px screen (Connect cut off, the settings gear unreachable). On phones they
        # wrap within the screen (two full-width rows on narrow phones), and the card, the first-visit hint and the
        # settings sit under them from where app.js measures they end (--nav-b), not from offsets fixed for one row
        css, app = self.text("style.css"), self.text("app.js")
        phone = "\n".join(m.group(1) for m in re.finditer(r"@media \(max-width: 860px\) \{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}", css))
        nav = re.search(r"(?m)^\s*\.tr \{([^}]*)\}", phone).group(1)
        self.assertIn("right: var(--gut)", nav)
        self.assertIn("flex-wrap: wrap", nav)
        self.assertIn("var(--head-b", nav)
        for sel in (".card", ".hint", ".settings"):
            rule = re.search(rf"(?m)(?:^|\{{)\s*{re.escape(sel)} \{{([^}}]*)\}}", phone).group(1)
            self.assertIn("var(--nav-b", rule, sel)
            self.assertNotRegex(rule, r"top: calc\(var\(--gut\) \+ \d+px\)", sel)
        narrow = re.search(r"@media \(max-width: 480px\) \{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}", css).group(1)
        self.assertIn(".tr .seg { flex: 1 1 100%; }", narrow)
        self.assertIn(".tr .tbtn { flex: 1 1 0;", narrow)
        wide = re.search(r"@media \(min-width: 861px\) \{([^}]*\})", css).group(1)
        self.assertIn(".kicker { max-width: calc(100vw - 2 * var(--gut) - var(--nav-w, 0px)", wide)
        place = re.search(r"function placeHud\(\) \{(.*?)\n\}", app, re.S).group(1)
        for var in ("--nav-w", "--head-b", "--nav-b"):
            self.assertIn(f"css.setProperty('{var}'", place)
        self.assertIn("document.body.classList.toggle('focus', m !== 'array'); placeHud();", app)

    def test_labels_say_license(self):
        # the page reads the dataset's key in one place and copies it in one more (the live lines keep the dataset's
        # fields, LINE_KEYS); its labels, tables and CSV columns say license
        app = self.text("app.js")
        uses = [l.strip() for l in app.splitlines() if PUBLISHED in l]
        self.assertEqual(uses[0], f"const lic = (l) => l.{PUBLISHED};")
        self.assertEqual(len(uses), 2)
        self.assertTrue(uses[1].startswith("const LINE_KEYS = ["), uses[1])
        self.assertIn("['license', 'license']", app)
        self.assertIn("${row('license', lic(l))}", app)
        self.assertIn("license: lic(l),", app)

    def test_ends_outside_the_scroll_are_hidden_and_can_be_shown(self):
        # 1.13.0: each line is drawn from its first to its last inside point; one named control (kept in the view link
        # as outside=1) draws the hidden end runs faded and dotted; drift statistics use the inside part
        app, html = self.text("app.js"), self.text("index.html")
        self.assertIn('id="t-outside"> show ends outside the scroll', html)
        self.assertIn("if (S.outside) q.set('outside', '1');", app)
        self.assertIn("S.outside = q.get('outside') === '1';", app)
        mesh = re.search(r"function lineMeshes\(.*?\n\}", app, re.S).group(0)
        self.assertIn("tube(pts3.slice(a, b)", mesh)
        self.assertIn("if (S.outside)", mesh)
        self.assertEqual(app.count("...lineMeshes(l, "), 2)  # the Array and the X-ray views
        self.assertNotRegex(app, r"tube\(linePts\(l\)")
        for fn in ("lineMean", "drift"):
            self.assertIn("insidePts(l)", re.search(rf"function {fn}\(.*", app).group(0), fn)
        self.assertIn("['outside_low', 'low out'], ['outside_high', 'high out']", app)
        self.assertIn("${outsideHTML(l)}", app)
        # the raw downloads stay the dataset's own files
        self.assertIn("const RAW = (l) => `${DATASET}/resolve/main/${l.file}`;", app)

    def test_card_links_both_datasets(self):
        readme = self.text("README.md")
        self.assertIn("SharpMeow/vesuvius-center-lines", readme)
        self.assertIn("SharpMeow/pherc0175a-lasagna", readme)


if __name__ == "__main__":
    unittest.main()
