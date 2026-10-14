"""Standard exports of a letter-reader result: a CSV table of its letters and a PAGE XML file.

Both are written from a result of kit.letterread.read() (or the JSON the command line writes) and
carry nothing but the reader's output: letter hypotheses with boxes and confidences. Every one of
them is Model output, not a reading (letterread.NOTE), and the PAGE file says so in its metadata.

Coordinates. A result's boxes are in input pixels: the pixels of the image file as given (after a
JPEG's or PNG's EXIF orientation), mapped back through block-averaging (input_scale) and through a
turned read (rotate, mirror), and relative to the crop's first row and column when the command
line's --crop was given. Both exports add that crop offset, so every coordinate they write is in
the pixels of the whole image file, which is what a PAGE file's imageFilename, imageWidth and
imageHeight describe. The command line records the whole image's size as image_shape; a result
read from a crop without it needs image_shape given.

CSV (letter_rows, write_csv): one row per decoded letter, CSV_FIELDS: column, line, index (the
letter's place on its line, from 0), letter, p (its confidence), kept (true when p is at or above
the read's confidence floor p_min; the line's ink_only string writes '·' for the others), and its
box y0, y1, x0, x1. UTF-8, no byte-order mark.

PAGE XML (page_xml, write_page_xml): the 2019-07-15 schema of PRImA (PAGE_XSD), which eScriptorium
lists among the PAGE versions it imports. A TextRegion per reader column (Coords: the bounding box
of its line bands), a TextLine per line (Coords: its band, one letter height along the column with
the column's deskew; Baseline: the band's lower edge, left to right as read, so a turned read's
baseline runs the way its text does), one Word per line holding a Glyph per letter (Herculaneum
texts have no word division) and TextEquiv at every level. A glyph under the confidence floor has
'·' as its text, no conf, and its best letter and p in its comments attribute, so the text of
glyphs, words and lines is the reader's ink_only string; a kept glyph's TextEquiv conf is its p.
Integer coordinates, clipped to the image. ReadingOrder lists the columns left to right as read;
each TextRegion and TextLine also carries Transkribus's readingOrder custom attribute.
"""

import csv
import io
import math
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from . import __version__ as KIT_VERSION
from . import letterread as R

CSV_FIELDS = ("column", "line", "index", "letter", "p", "kept", "y0", "y1", "x0", "x1")
PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"
PAGE_XSD = PAGE_NS + "/pagecontent.xsd"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
UNKEPT = "·"   # the text of a glyph under the confidence floor, as in a line's ink_only string


def image_frame(res, image_shape=None):
    """(oy, ox, H, W): the row and column of the whole image file where the result's input pixels start, and its size.

    image_shape: (H, W) of the whole image file; by default the result's image_shape (the command
    line records it), else its input_shape. A read of a --crop window needs the whole image's size
    to place the crop (a negative crop counts from the far edge, as in numpy)."""
    shape = image_shape if image_shape is not None else res.get("image_shape")
    crop = res.get("crop")
    if crop:
        if shape is None:
            raise ValueError("this result was read from a --crop window and does not record the whole image's size "
                             "(image_shape); give image_shape=(H, W) of the image file")
        y0, _, x0, _ = R._window(crop, shape, "image")
        return y0, x0, int(shape[0]), int(shape[1])
    shape = shape if shape is not None else res["input_shape"]
    return 0, 0, int(shape[0]), int(shape[1])


def letter_rows(res, image_shape=None):
    """One dict per decoded letter, line by line in the result's order, with CSV_FIELDS; boxes in the image file's pixels."""
    oy, ox, _, _ = image_frame(res, image_shape)
    rows = []
    for L in res["lines"]:
        for i, l in enumerate(L["letters"]):
            y0, y1, x0, x1 = l["box"]
            rows.append({"column": L["column"], "line": L["line"], "index": i, "letter": l["glyph"], "p": l["p"],
                         "kept": bool(l["kept"]), "y0": round(y0 + oy, 1), "y1": round(y1 + oy, 1),
                         "x0": round(x0 + ox, 1), "x1": round(x1 + ox, 1)})
    return rows


def letters_csv(res, image_shape=None):
    """The CSV text of letter_rows(): a header of CSV_FIELDS, then a row per letter; kept is true or false."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    w.writeheader()
    for row in letter_rows(res, image_shape):
        w.writerow(dict(row, kept="true" if row["kept"] else "false"))
    return buf.getvalue()


def write_csv(res, path, image_shape=None):
    """Write letters_csv() to path in UTF-8; returns path."""
    Path(path).write_text(letters_csv(res, image_shape), encoding="utf-8", newline="")
    return path


# ------------------------------------------------------------------ PAGE XML

def _view(res):
    """(rotate, mirror, (H, W)) of a turned read: the image as read, unturned, in input pixels; (0, False, None) otherwise."""
    v = res.get("view")
    if not v or (not v.get("rotate") and not v.get("mirror")):
        return 0, False, None
    k = res.get("input_scale", 1)
    shape = [n * k for n in res["reduced_shape"]] if "reduced_shape" in res else res["input_shape"]
    return v["rotate"], bool(v["mirror"]), (shape[0], shape[1])


def view_points(res, line):
    """A line's band and baseline in the image as read (the turned image after a turned read), input pixels, as (y, x).

    The band is one letter height (letter_px) centred on the line's row y, which is its row at the
    column's horizontal middle; at column x the row moves by (x - middle) * tan(the column's deskew).
    Returns (band corners: top left, top right, bottom right, bottom left; baseline: left, right)."""
    col = res["columns"][line["column"]]
    x0, x1 = float(col["x0"]), float(col["x1"])
    t = math.tan(math.radians(col.get("deskew_deg") or 0.0))
    xm, h = 0.5 * (x0 + x1), float(res["letter_px"])
    yl, yr = line["y"] + (x0 - xm) * t, line["y"] + (x1 - xm) * t
    return ([(yl - h / 2, x0), (yr - h / 2, x1), (yr + h / 2, x1), (yl + h / 2, x0)],
            [(yl + h / 2, x0), (yr + h / 2, x1)])


def to_image_points(res, pts, frame, turned=True):
    """Points (y, x) in input pixels (in the image as read when turned) as integer (x, y) in the whole image file, clipped."""
    rot, mir, shape = _view(res) if turned else (0, False, None)
    oy, ox, H, W = frame
    out = []
    for y, x in pts:
        if shape is not None:
            y, _, x, _ = R.view_box_to_input([y, y, x, x], rot, mir, shape)
        out.append((min(max(int(round(x + ox)), 0), W - 1), min(max(int(round(y + oy)), 0), H - 1)))
    return out


def _points(xy):
    return " ".join(f"{x},{y}" for x, y in xy)


def _box_points(box, frame):
    """A letter box [y0, y1, x0, x1] in input pixels as four integer (x, y) corners in the image file, clockwise."""
    y0, y1, x0, x1 = box
    return to_image_points(None, [(y0, x0), (y0, x1), (y1, x1), (y1, x0)], frame, turned=False)


def _bbox(xy):
    xs, ys = [p[0] for p in xy], [p[1] for p in xy]
    return [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]


def _sub(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items() if v is not None})
    if text is not None:
        e.text = text
    return e


def _text_equiv(parent, text, conf=None):
    te = _sub(parent, "TextEquiv", conf=None if conf is None else f"{float(conf):.3f}")
    _sub(te, "Unicode", text)
    return te


def _status(res):
    c = res.get("control") or {}
    return R.status_line(c) if "status" in c else None


def _metadata(root, res, created):
    md = _sub(root, "Metadata")
    _sub(md, "Creator", f"kit.letterread {res.get('reader', {}).get('version', KIT_VERSION)} "
                        "(https://github.com/ChaseHendrick/Scrolls)")
    _sub(md, "Created", created)
    _sub(md, "LastChange", created)
    lines = [R.NOTE, "Every letter, line and region in this file is the reader's hypothesis for a person to check."]
    if _status(res):
        lines.append("Controls: " + _status(res))
    if "weights" in res and "reader" in res:
        lines.append(R.provenance_line(res))
    _sub(md, "Comments", "\n".join(lines))
    item = _sub(md, "MetadataItem", type="processingStep", name="kit.letterread", value=R.NOTE, date=created)
    labels = _sub(item, "Labels")
    w = res.get("weights") or {}
    c = res.get("control") or {}
    found = [("output", "Model output, not a reading"), ("reader_version", (res.get("reader") or {}).get("version")),
             ("weights_name", w.get("name")), ("weights_file", w.get("file")), ("weights_sha256", w.get("sha256")),
             ("seed", res.get("seed")), ("source", (res.get("source") or {}).get("file")),
             ("letter_px", res.get("letter_px")), ("p_min", res.get("p_min")), ("status", c.get("status")),
             ("letters_kept", c.get("letters_kept")),
             ("null_letters_kept", ",".join(map(str, c["null_letters_kept"])) if c.get("null_letters_kept") else None),
             ("ratio", c.get("ratio"))]
    if "control_map" in c:
        found.append(("control_map_letters_kept", c["control_map"].get("letters_kept")))
    for kind, value in found:
        if value is not None:
            _sub(labels, "Label", type=kind, value=value)


def page_xml(res, image_filename=None, image_shape=None, created=None):
    """The result as a PAGE XML 2019-07-15 document (a str), with integer coordinates in the image file's pixels.

    image_filename: the Page's imageFilename (default: the result's source file, as the command line
    records it, else "image"); eScriptorium matches a PAGE file to its image by this name.
    image_shape: (H, W) of the whole image file (image_frame). created: the Metadata time stamp, an
    xs:dateTime such as 2026-10-14T12:00:00Z (default: now, UTC)."""
    frame = image_frame(res, image_shape)
    if image_filename is None:
        image_filename = (res.get("source") or {}).get("file") or "image"
    if created is None:
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Plain tag names with the namespace declarations written as attributes: the default namespace without
    # ElementTree's global prefix registry (register_namespace), and xsi:schemaLocation as eScriptorium reads it.
    root = ET.Element("PcGts", {"xmlns": PAGE_NS, "xmlns:xsi": XSI_NS, "xsi:schemaLocation": f"{PAGE_NS} {PAGE_XSD}"})
    _metadata(root, res, created)
    page = _sub(root, "Page", imageFilename=image_filename, imageWidth=frame[3], imageHeight=frame[2])
    cols = res.get("columns") or []
    if cols:
        group = _sub(_sub(page, "ReadingOrder"), "OrderedGroup", id="ro", caption="reader columns, left to right as read")
        for ci in range(len(cols)):
            _sub(group, "RegionRefIndexed", index=ci, regionRef=f"r{ci}")
    Hv = _view_shape(res)[0]
    for ci, col in enumerate(cols):
        lines = [L for L in res["lines"] if L["column"] == ci]
        bands = []
        for L in lines:
            band, base = view_points(res, L)
            bands.append((L, to_image_points(res, band, frame), to_image_points(res, base, frame)))
        if bands:
            region_pts = _bbox([p for _, b, _ in bands for p in b])
        else:   # a column with no lines: the column over the whole height of the image as read
            region_pts = _bbox(to_image_points(res, [(0, col["x0"]), (Hv, col["x1"])], frame))
        region = _sub(page, "TextRegion", id=f"r{ci}", custom=f"readingOrder {{index:{ci};}}",
                      primaryScript="Grek - Greek")
        _sub(region, "Coords", points=_points(region_pts))
        for li, (L, band_pts, base_pts) in enumerate(bands):
            note = f"{L['n_kept']} letters kept"
            if L.get("chance") is not None:
                note += f"; chance {L['chance']:g} (the column's mean null count over its lines)"
            if "control_map_kept" in L:
                note += f"; control map {L['control_map_kept']}"
            if "with_lm" in L:
                note += f"; with the language model: {L['with_lm']}"
            tl = _sub(region, "TextLine", id=f"r{ci}l{li}", custom=f"readingOrder {{index:{li};}}", comments=note)
            _sub(tl, "Coords", points=_points(band_pts))
            _sub(tl, "Baseline", points=_points(base_pts))
            if L["letters"]:
                word = _sub(tl, "Word", id=f"r{ci}l{li}w0")
                _sub(word, "Coords", points=_points(band_pts))
                for gi, l in enumerate(L["letters"]):
                    if l["kept"]:
                        g = _sub(word, "Glyph", id=f"r{ci}l{li}g{gi}")
                        _sub(g, "Coords", points=_points(_box_points(l["box"], frame)))
                        _text_equiv(g, l["glyph"], l["p"])
                    else:
                        g = _sub(word, "Glyph", id=f"r{ci}l{li}g{gi}",
                                 comments=f"under the confidence floor {res['p_min']:g}: best letter {l['glyph']}, "
                                          f"p {l['p']:g}")
                        _sub(g, "Coords", points=_points(_box_points(l["box"], frame)))
                        _text_equiv(g, UNKEPT)
                _text_equiv(word, L["ink_only"])
            _text_equiv(tl, L["ink_only"])
        _text_equiv(region, "\n".join(L["ink_only"] for L, _, _ in bands))
    ET.indent(root, space=" ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _view_shape(res):
    """(H, W) of the image as read (turned after a turned read), in input pixels."""
    v = res.get("view")
    if v and "shape" in v:
        return tuple(v["shape"])
    k = res.get("input_scale", 1)
    shape = [n * k for n in res["reduced_shape"]] if "reduced_shape" in res else res["input_shape"]
    return tuple(shape)


def write_page_xml(res, path, image_filename=None, image_shape=None, created=None):
    """Write page_xml() to path in UTF-8; returns path."""
    Path(path).write_text(page_xml(res, image_filename, image_shape, created), encoding="utf-8")
    return path
