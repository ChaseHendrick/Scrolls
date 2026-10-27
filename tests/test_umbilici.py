"""Umbilici (spaces/umbilici): the line table builder, the lasagna helpers and the page's own promises. No network."""

import importlib.util
import json
import re
import sys
import tempfile
import unittest
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


def fake_dataset(root):
    """A two-scan copy of the center-lines dataset: one scan with two people's lines, one with a finder line."""
    files = [
        {"scroll": "PHerc0001", "scan": "20250101000000", "source": "drobkov", "kind": "person", "credit": "Alexey Drobkov",
         "licence": "MIT", "upstream": "https://example.org/a", "file": "lines/PHerc0001/a.json", "sha256": "0" * 64,
         "z": [100.0, 300.0], "note": "", "volume": "20250101000000-9.362um-1.2m-113keV-masked.zarr"},
        {"scroll": "PHerc0001", "scan": "20250101000000", "source": "tauil", "kind": "person", "credit": "Abd Elilah",
         "licence": "CC BY 4.0", "upstream": "https://example.org/b", "file": "lines/PHerc0001/b.json", "sha256": "1" * 64,
         "z": [120.0, 280.0], "note": "withdrawn from recommended use by its author", "volume": None},
        {"scroll": "PHerc0002", "scan": "20250202000000", "source": "finder", "kind": "model", "credit": "Chase Hendrick",
         "licence": "CC BY-NC 4.0", "upstream": "made here", "file": "lines/PHerc0002/c.json", "sha256": "2" * 64,
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


class BuildLines(unittest.TestCase):
    def build(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_dataset(root)
            out = root / "lines.json"
            with mock.patch.object(build_lines, "get_json", fake_get_json), mock.patch("builtins.print"):
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
        self.assertEqual(set(t["sources"]), {"bucket", "drobkov", "tauil", "dopico", "finder", "finder-polished"})

    def test_every_source_has_a_color_and_a_chip_style(self):
        app = (SPACE / "app.js").read_text()
        css = (SPACE / "style.css").read_text()
        hexes = app[app.index("const SRC_HEX"):].split("\n", 1)[0]
        for k in build_lines.SOURCES:
            self.assertIn(f"{k}: '#" if "-" not in k else f"'{k}': '#", hexes, k)
            self.assertIn(f".src.s-{k} ", css, k)


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
            with mock.patch.object(build_lines, "get_json", fake_get_json), mock.patch("builtins.print"):
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
            with mock.patch.object(build_lines, "get_json", fake_get_json), mock.patch("builtins.print"):
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
            with mock.patch.object(build_lines, "get_json", blosc), mock.patch("builtins.print"):
                build_lines.main(root, out)
            t = json.loads(out.read_text())
        self.assertEqual({p["compressor"] for s in t["scrolls"] for p in s["pyramid"]}, {"blosc"})


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
                                 "stats", "table", "csv", "guide", "data", "settings", "bench", "show"})
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

    def test_card_links_both_datasets(self):
        readme = self.text("README.md")
        self.assertIn("SharpMeow/vesuvius-center-lines", readme)
        self.assertIn("SharpMeow/pherc0175a-lasagna", readme)


if __name__ == "__main__":
    unittest.main()
