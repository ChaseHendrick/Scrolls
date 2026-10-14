"""CSV and PAGE XML exports of a letter-reader result (kit/letterexport.py), on synthetic images with random weights."""
import contextlib
import csv
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET

from kit import cli

try:
    import numpy as np
    from kit import letterexport as E
    from kit import letterread as R
    try:
        from test_letterread import lined_image, random_weights, run_cli, two_column_image
    except ImportError:   # run as tests.test_letterexport
        from tests.test_letterread import lined_image, random_weights, run_cli, two_column_image
except ImportError:  # the core kit is standard library only
    np = E = R = None

NS = {"pc": "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"}
POINTS = re.compile(r"([0-9]+,[0-9]+ )+([0-9]+,[0-9]+)")   # PAGE's PointsType
# The children each element may have, in the order the 2019 schema's sequences give them (only those the export
# writes): an element's children must come in this order, and no others.
ORDER = {"PcGts": ["Metadata", "Page"],
         "Metadata": ["Creator", "Created", "LastChange", "Comments", "MetadataItem"],
         "MetadataItem": ["Labels"], "Labels": ["Label"],
         "Page": ["ReadingOrder", "TextRegion"], "ReadingOrder": ["OrderedGroup"], "OrderedGroup": ["RegionRefIndexed"],
         "TextRegion": ["Coords", "TextLine", "TextEquiv"], "TextLine": ["Coords", "Baseline", "Word", "TextEquiv"],
         "Word": ["Coords", "Glyph", "TextEquiv"], "Glyph": ["Coords", "TextEquiv"], "TextEquiv": ["Unicode"]}
REQUIRED = {"Page": ["imageFilename", "imageWidth", "imageHeight"], "TextRegion": ["id"], "TextLine": ["id"],
            "Word": ["id"], "Glyph": ["id"], "Coords": ["points"], "Baseline": ["points"], "OrderedGroup": ["id"],
            "RegionRefIndexed": ["index", "regionRef"], "MetadataItem": ["value"], "Label": ["value"]}


def schema_order_problems(root):
    """Elements whose children are out of the schema's order or not allowed there, and missing required attributes."""
    bad = []
    for e in root.iter():
        name = e.tag.split("}")[1]
        if not e.tag.startswith("{%s}" % NS["pc"]):
            bad.append(f"{e.tag} is not in the PAGE namespace")
        kids = [c.tag.split("}")[1] for c in e]
        allowed = ORDER.get(name, [])
        if any(k not in allowed for k in kids) or [allowed.index(k) for k in kids] != sorted(allowed.index(k) for k in kids):
            bad.append(f"{name}: children {kids}")
        bad += [f"{name} lacks {a}" for a in REQUIRED.get(name, []) if e.get(a) is None]
    return bad


def points(e):
    """The integer (x, y) points of an element's Coords or Baseline."""
    s = e.get("points")
    assert POINTS.fullmatch(s), s
    return [tuple(int(v) for v in p.split(",")) for p in s.split()]


def corners(box, oy=0, ox=0):
    """A JSON box [y0, y1, x0, x1] as the four (x, y) corners PAGE gets: offset, rounded."""
    y0, y1, x0, x1 = box
    r = lambda v: int(round(v))
    return [(r(x0 + ox), r(y0 + oy)), (r(x1 + ox), r(y0 + oy)), (r(x1 + ox), r(y1 + oy)), (r(x0 + ox), r(y1 + oy))]


@unittest.skipIf(np is None, "numpy not installed")
class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = random_weights(self.d / "w.npz")
        self.net = R.LineNet(self.w)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, img=None, **kw):
        kw = dict(dict(letter_px=16, nulls=1, p_min=0.3, orientation=False), **kw)
        return R.read(lined_image() if img is None else img, self.net, **kw)

    def check_page(self, xml, res, oy=0, ox=0, H=None, W=None):
        """Well-formed PAGE 2019 whose glyphs are the result's boxes in the image file's pixels; returns the root."""
        root = ET.fromstring(xml.encode("utf-8"))
        self.assertEqual(root.tag, "{%s}PcGts" % NS["pc"])
        self.assertEqual(schema_order_problems(root), [])
        self.assertIn(E.PAGE_XSD, root.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"))
        md = root.find("pc:Metadata", NS)
        self.assertEqual([c.tag.split("}")[1] for c in md], ["Creator", "Created", "LastChange", "Comments", "MetadataItem"])
        self.assertIn(R.NOTE, md.find("pc:Comments", NS).text)
        item = md.find("pc:MetadataItem", NS)
        self.assertEqual((item.get("type"), item.get("value")), ("processingStep", R.NOTE))
        self.assertIn("Model output, not a reading", [l.get("value") for l in item.iter("{%s}Label" % NS["pc"])])
        page = root.find("pc:Page", NS)
        self.assertEqual((int(page.get("imageHeight")), int(page.get("imageWidth"))), (H, W))
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        self.assertEqual(len(ids), len(set(ids)))
        regions = page.findall("pc:TextRegion", NS)
        self.assertEqual(len(regions), len(res["columns"]))
        self.assertEqual([r.get("regionRef") for r in page.iter("{%s}RegionRefIndexed" % NS["pc"])],
                         [r.get("id") for r in regions])
        lines = [tl for r in regions for tl in r.findall("pc:TextLine", NS)]
        self.assertEqual(len(lines), len(res["lines"]))
        for tl, L in zip(lines, res["lines"]):
            self.assertEqual([c.tag.split("}")[1] for c in tl][:2], ["Coords", "Baseline"])
            band = points(tl.find("pc:Coords", NS))
            for x, y in band + points(tl.find("pc:Baseline", NS)):
                self.assertTrue(0 <= x < W and 0 <= y < H, (x, y))
            self.assertEqual(tl.find("pc:TextEquiv/pc:Unicode", NS).text or "", L["ink_only"])
            glyphs = tl.findall("pc:Word/pc:Glyph", NS)
            self.assertEqual(len(glyphs), len(L["letters"]))
            if glyphs:
                self.assertEqual(tl.find("pc:Word/pc:TextEquiv/pc:Unicode", NS).text, L["ink_only"])
            self.assertEqual("".join(g.find("pc:TextEquiv/pc:Unicode", NS).text for g in glyphs), L["ink_only"])
            bx = [p[0] for p in band]
            by = [p[1] for p in band]
            for g, l in zip(glyphs, L["letters"]):
                want = [(min(max(x, 0), W - 1), min(max(y, 0), H - 1)) for x, y in corners(l["box"], oy, ox)]
                self.assertEqual(points(g.find("pc:Coords", NS)), want)
                te = g.find("pc:TextEquiv", NS)
                if l["kept"]:
                    self.assertEqual((te.find("pc:Unicode", NS).text, float(te.get("conf"))), (l["glyph"], l["p"]))
                else:
                    self.assertEqual((te.find("pc:Unicode", NS).text, te.get("conf")), ("·", None))
                    self.assertIn(f"best letter {l['glyph']}", g.get("comments"))
                # every glyph sits in its line's band: the box rows are the band's rows at the box, and a box reaches
                # at most half a letter height past the column's edge (its last frame and a 0.3 letter margin)
                gx = [p[0] for p in want]
                gy = [p[1] for p in want]
                m = 0.5 * res["letter_px"] + 1
                self.assertTrue(min(bx) - m <= min(gx) and max(gx) <= max(bx) + m, (gx, bx))
                self.assertTrue(min(by) - 2 <= min(gy) and max(gy) <= max(by) + 2, (gy, by))
        return root

    def test_csv_has_a_row_per_letter_in_input_pixels(self):
        res = self.read()
        text = E.letters_csv(res)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(tuple(rows[0].keys()) if rows else (), E.CSV_FIELDS)
        letters = [(L, i, l) for L in res["lines"] for i, l in enumerate(L["letters"])]
        self.assertTrue(letters)
        self.assertEqual(len(rows), len(letters))
        for row, (L, i, l) in zip(rows, letters):
            self.assertEqual((int(row["column"]), int(row["line"]), int(row["index"]), row["letter"], float(row["p"])),
                             (L["column"], L["line"], i, l["glyph"], l["p"]))
            self.assertEqual(row["kept"], "true" if l["kept"] else "false")
            self.assertEqual([float(row[k]) for k in ("y0", "y1", "x0", "x1")], l["box"])
        path = E.write_csv(res, self.d / "letters.csv")
        self.assertEqual(Path(path).read_bytes(), text.encode("utf-8"))      # UTF-8, no byte-order mark
        self.assertNotIn(b"\r\n", Path(path).read_bytes())

    def test_page_xml_well_formed_and_in_input_pixels(self):
        res = self.read()
        xml = E.page_xml(res, image_filename="page.png", created="2026-10-14T12:00:00Z")
        root = self.check_page(xml, res, H=150, W=400)
        self.assertEqual(root.find("pc:Page", NS).get("imageFilename"), "page.png")
        self.assertEqual(root.find("pc:Metadata/pc:Created", NS).text, "2026-10-14T12:00:00Z")
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        # a level line: its baseline is the band's lower edge, y + letter_px / 2, left to right
        tl = root.find(".//pc:TextLine", NS)
        L, col = res["lines"][0], res["columns"][0]
        if col["deskew_deg"] == 0:
            yb = int(round(L["y"] + res["letter_px"] / 2))
            self.assertEqual(points(tl.find("pc:Baseline", NS)), [(int(round(col["x0"])), yb),
                                                                  (min(399, int(round(col["x1"]))), yb)])
        # the order check can fail: a line's Coords moved after its text is caught
        broken = ET.fromstring(xml.encode("utf-8"))
        tl = broken.find(".//pc:TextLine", NS)
        coords = tl.find("pc:Coords", NS)
        tl.remove(coords)
        tl.append(coords)
        self.assertEqual(schema_order_problems(broken), [f"TextLine: children {['Baseline', 'Word', 'TextEquiv', 'Coords']}"])
        path = E.write_page_xml(res, self.d / "page.xml", image_filename="page.png", created="2026-10-14T12:00:00Z")
        self.assertEqual(Path(path).read_text(encoding="utf-8"), xml)

    def test_turned_and_two_column_reads(self):
        two = self.read(two_column_image(), columns=2)
        self.check_page(E.page_xml(two), two, H=two["input_shape"][0], W=two["input_shape"][1])
        img = R.normalize(lined_image())
        turned = self.read(np.rot90(img, 1), normalized=True, rotate=90)          # stored a quarter turn anticlockwise
        root = self.check_page(E.page_xml(turned), turned, H=400, W=150)
        for tl in root.iter("{%s}TextLine" % NS["pc"]):
            (xa, ya), (xb, yb) = points(tl.find("pc:Baseline", NS))
            self.assertLessEqual(abs(xb - xa), 1)                                  # the line runs up the image
            self.assertGreater(ya - yb, 300)                                       # from bottom to top, as it reads

    def test_crop_and_block_averaged_read_from_the_command_line(self):
        small = lined_image()                                                     # 150 x 400, letters 16 px
        big = np.kron(small, np.ones((4, 4), np.float32))                         # letters 64 px
        oy, ox = 37, 51
        canvas = np.full((big.shape[0] + 90, big.shape[1] + 120), 0.1, np.float32)
        canvas[oy:oy + big.shape[0], ox:ox + big.shape[1]] = big
        img = self.d / "canvas.npy"
        np.save(img, canvas)
        out, csv_out, xml_out = self.d / "res.json", self.d / "res.csv", self.d / "res.xml"
        code, _, err = run_cli(["letterread", str(img), "--weights", str(self.w), "--letter-px", "64", "--nulls", "1",
                                "--p-min", "0.3", "--no-orientation", "--max-mpx", "0.5", "--quiet",
                                "--crop", str(oy), str(oy + big.shape[0]), str(ox), str(ox + big.shape[1]),
                                "--out", str(out), "--csv", str(csv_out), "--page-xml", str(xml_out)])
        self.assertEqual(code, 0, err)
        res = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((res["input_scale"], res["image_shape"], res["crop"][:1]), (2, list(canvas.shape), [oy]))
        self.assertTrue(sum(len(L["letters"]) for L in res["lines"]))
        self.check_page(xml_out.read_text(encoding="utf-8"), res, oy, ox, H=canvas.shape[0], W=canvas.shape[1])
        rows = list(csv.DictReader(io.StringIO(csv_out.read_text(encoding="utf-8"))))
        flat = [l for L in res["lines"] for l in L["letters"]]
        self.assertEqual(len(rows), len(flat))
        for row, l in zip(rows, flat):
            y0, y1, x0, x1 = l["box"]
            self.assertEqual([float(row[k]) for k in ("y0", "y1", "x0", "x1")],
                             [round(y0 + oy, 1), round(y1 + oy, 1), round(x0 + ox, 1), round(x1 + ox, 1)])
        # the same letters as reading the image block-averaged by 2, with every number doubled; the exports add
        # the crop's offset, so their coordinates point at the input file's pixels
        ref = R.read(np.kron(small, np.ones((2, 2), np.float32)), self.net, letter_px=32, nulls=1, p_min=0.3,
                     orientation=False)
        self.assertEqual(len(res["lines"]), len(ref["lines"]))
        for L, L0 in zip(res["lines"], ref["lines"]):
            self.assertEqual([l["glyph"] for l in L["letters"]], [l["glyph"] for l in L0["letters"]])
            for l, l0 in zip(L["letters"], L0["letters"]):
                np.testing.assert_allclose(l["box"], [2 * v for v in l0["box"]], atol=0.2)

    def test_a_crop_needs_the_whole_image_size(self):
        res = dict(self.read(), crop=[10, 160, 0, 400])
        with self.assertRaisesRegex(ValueError, "image_shape"):
            E.page_xml(res)
        rows = E.letter_rows(res, image_shape=(200, 400))
        self.assertEqual(rows[0]["y0"], round(res["lines"][0]["letters"][0]["box"][0] + 10, 1))
        res["crop"] = [-150, None, 0, 400]                       # numpy's rules: the last 150 rows of 200
        self.assertEqual(E.image_frame(res, (200, 400)), (50, 0, 200, 400))

    def test_command_line_checks_export_folders_before_reading(self):
        img = self.d / "img.npy"
        np.save(img, lined_image())
        for opt in ("--csv", "--page-xml"):
            with mock.patch.object(R, "read", side_effect=AssertionError("read before checking outputs")):
                code, _, err = run_cli(["letterread", str(img), "--weights", str(self.w), "--letter-px", "16",
                                        opt, str(self.d / "missing" / "x")])
            self.assertEqual(code, 2)
            self.assertIn("no such folder", err)
        code, out, err = run_cli(["letterread", str(img), "--weights", str(self.w), "--letter-px", "16", "--nulls", "1",
                                  "--no-orientation", "--quiet", "--page-xml", str(self.d / "p.xml"), "--csv",
                                  str(self.d / "p.csv")])
        self.assertEqual(code, 0, err)
        page = ET.parse(self.d / "p.xml").getroot().find("pc:Page", NS)
        self.assertEqual((page.get("imageFilename"), page.get("imageHeight"), page.get("imageWidth")), ("img.npy", "150", "400"))
        self.assertTrue((self.d / "p.csv").read_text(encoding="utf-8").startswith(",".join(E.CSV_FIELDS)))


if __name__ == "__main__":
    unittest.main()
