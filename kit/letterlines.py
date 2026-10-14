"""Training lines for the letter reader from your own transcribed lines: records in, LINES.npz out.

A record names one text line of an image and what is written on it, in Greek capitals:

  image      the image file (any format the reader loads; a relative path is relative to the records file)
  text       the line's letters; '?' for a letter you cannot see or restore (a wildcard in training)
  y          the line's centre row in image pixels (halfway between the letters' tops and feet)
  letter_px  the letters' height in image pixels
  x0, x1     optional: the columns where the line starts and ends (default: the whole width)
  crop       optional: [Y0, Y1, X0, X1], a window of the image as in the reader's --crop; y, x0 and x1 are
             then relative to Y0 and X0, and the image is normalised over that window, as a read of it is
  key        optional: the array of a .npz or zarr, as the reader's --key
  polarity   optional: bright (ink brighter than the ground, as in ink maps; the default) or dark
  split      optional: any label, such as train or test, so one records file can hold lines to train on and
             lines kept apart to test the result (build --split NAME keeps one of them)
  id         optional: your own name for the line, kept in LINES.npz

Records are a JSON list of objects, a JSON object {"lines": [...]} whose other keys (image, letter_px,
crop, key, polarity, split) are defaults for every line, or a CSV with a header row of these field
names (crop as four numbers separated by spaces). check_records() validates every record before any
image is decoded and reports every problem at once; plan_text() is the dry run.

cut_lines() cuts each line as the reader sees it: the image (or crop) loaded as the reader loads it
(block-averaged while loading when over the pixel budget), normalised once, resized so letters are
the network's working height (16 px), and the band of 36 rows the reader reads on a line given as
--lines Y with --deskew 0, from the line's first to its last column. The band is level: for a
tilted line, give x0 and x1 close to its letters or a crop around it.

LINES.npz is the format scripts/letters/p1667_align.py writes and finetune_maps.py trains on (uint8
bands, texts with '?', where each came from, and meta). score_lines() decodes held-out lines with
one or more models and reports the character error against your text.

Text is cleaned as the letter language model cleans it (accents and breathings dropped, capitals,
lunate sigma for every sigma) and spaces are dropped (the reader reads scriptio continua). Anything
else, such as punctuation, brackets, a Latin letter that looks Greek or the reader's own '·', is an
error naming the character: write the letter, or '?' when you cannot see it.

A model fine-tuned on these lines is a new model: its output is still a hypothesis for a person to
check, and it must be judged on lines it did not train on.

check_references() is the stricter check the benchmark scripts make on reference texts, which are
compared letter for letter and so are not cleaned: every character must be one the reader writes
(or '?' where a script allows it); a Latin or Cyrillic look-alike, a final or capital sigma, a small
letter or an accent stops the run with what to write instead and the reader's alphabet.
"""

import csv
import hashlib
import json
import math
import unicodedata
from pathlib import Path

import numpy as np

from . import __version__ as KIT_VERSION
from . import letterread as R

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"
WILDCARD = "?"
NET_LETTER_PX = 16          # the released network's working letter height (its weights' meta letter_px)
BAND = (1.1, 1.15)          # band rows above and below the line centre, in letter heights (meta band)
STRIDE = 4                  # input pixels per output frame at the working scale (meta stride)
FIELDS = ("image", "text", "y", "letter_px", "x0", "x1", "crop", "key", "polarity", "split", "id")
DEFAULT_FIELDS = ("image", "letter_px", "crop", "key", "polarity", "split")
IGNORED = ("note", "comment")
PITCH_RANGE = (0.5, 2.0)    # letter pitch at the working scale, in working letter heights, outside which a warning
NOTE = ("Training lines cut from your own transcribed lines. A model fine-tuned on them is a new model: its "
        "output is still a hypothesis for a person to check; judge it on lines it did not train on.")


class RecordsError(ValueError):
    """Problems with a records file; .errors lists every one."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


# ------------------------------------------------------------------ text

def clean_text(text):
    """(cleaned, problems): the line in the network's alphabet with '?' kept, and each character that has no place there.

    Accents, breathings and dots under letters are dropped, letters made capital, every sigma
    lunate, spaces dropped. problems lists the other characters as "'X' (UNICODE NAME)"."""
    d = unicodedata.normalize("NFD", str(text))
    d = "".join(c for c in d if not unicodedata.combining(c)).upper()
    d = d.replace("Σ", "Ϲ").replace("ς", "Ϲ")
    out, bad = [], []
    for c in d:
        if c in ALPHABET or c == WILDCARD:
            out.append(c)
        elif c.isspace():
            continue
        else:
            name = unicodedata.name(c, f"U+{ord(c):04X}")
            if c == "·":
                name += "; the reader's mark for a letter under its confidence floor: write the letter, or '?'"
            elif "LATIN" in name:
                name += "; a Latin letter: type the Greek one"
            item = f"'{c}' ({name})"
            if item not in bad:
                bad.append(item)
    return "".join(out), bad


LUNATE_SIGMA = "Ϲ"
# Latin and Cyrillic capitals that look like a Greek capital, and the Greek capital the reader writes for each
# (Latin C and Cyrillic С look like the lunate sigma the reader writes for every sigma).
LOOKALIKES = {"A": "Α", "B": "Β", "C": "Ϲ", "E": "Ε", "H": "Η", "I": "Ι", "K": "Κ", "M": "Μ", "N": "Ν", "O": "Ο",
              "P": "Ρ", "T": "Τ", "X": "Χ", "Y": "Υ", "Z": "Ζ",
              "А": "Α", "В": "Β", "Г": "Γ", "Е": "Ε", "К": "Κ", "Л": "Λ", "М": "Μ", "Н": "Η", "О": "Ο", "П": "Π",
              "Р": "Ρ", "С": "Ϲ", "Т": "Τ", "Ф": "Φ", "Х": "Χ"}


def letter_problem(c, alphabet=ALPHABET, wildcard=WILDCARD):
    """None when the reader writes c (or c is the allowed wildcard); else its Unicode name and what to write instead.

    Reference texts are compared letter for letter, so nothing is cleaned here: a final sigma, a Latin
    look-alike or an accented letter would only ever count as an error."""
    if c in alphabet or (wildcard and c == wildcard):
        return None
    name = unicodedata.name(c, f"U+{ord(c):04X}")
    base = "".join(ch for ch in unicodedata.normalize("NFD", c) if not unicodedata.combining(ch)).upper()
    foreign = "LATIN" in name or "CYRILLIC" in name
    look = LOOKALIKES.get(c) or LOOKALIKES.get(c.upper())
    if c in "Σσς" or base in ("Σ", LUNATE_SIGMA):
        hint = f"the reader writes every sigma as the lunate sigma {LUNATE_SIGMA}"
    elif foreign and look is not None and look in alphabet:
        hint = f"a {'Latin' if 'LATIN' in name else 'Cyrillic'} letter that looks Greek: type the Greek {look}"
    elif foreign:
        hint = "not a Greek letter: the reader proposes Greek capitals only"
    elif len(base) == 1 and base in alphabet:
        hint = f"write the plain capital {base} (no accents, breathings or small letters)"
    elif c == "·":
        hint = "the reader's mark for a letter under its confidence floor: write the letter" + (
            f", or {wildcard!r}" if wildcard else "")
    elif c.isspace():
        hint = "references are written without spaces, in scriptio continua"
    elif c == WILDCARD:
        hint = "this script scores no unsure letters: leave the line out, or write the letter"
    else:
        hint = "not a letter the reader writes"
    return f"{c!r} ({name}; {hint})"


def reference_problems(text, alphabet=ALPHABET, wildcard=WILDCARD):
    """Each character of text that the reader does not write, once, as "'X' (NAME; what to write instead)"."""
    out = []
    for c in str(text):
        item = letter_problem(c, alphabet, wildcard)
        if item is not None and item not in out:
            out.append(item)
    return out


def alphabet_text(alphabet=ALPHABET, wildcard=WILDCARD):
    """The sentence that tells a person which characters a reference may hold."""
    s = (f"The reader writes these {len(alphabet)} Greek capitals, every sigma as the lunate sigma "
         f"{LUNATE_SIGMA}: {alphabet}")
    return s + (f"; {wildcard!r} marks a letter you cannot see or restore." if wildcard else ".")


def check_references(refs, alphabet=ALPHABET, wildcard=WILDCARD, source="references", limit=20):
    """Raise ValueError when a reference text holds a character the reader does not write; return refs otherwise.

    refs: {id: text}, or (id, text) pairs. The message names each faulty reference (up to limit of them)
    with every character at fault and what to write instead, then the reader's alphabet. wildcard is
    the unsure-letter mark the calling script accepts ('?'), or None when it accepts none."""
    items = list(refs.items()) if isinstance(refs, dict) else list(refs)
    bad = []
    for key, text in items:
        problems = reference_problems(text, alphabet, wildcard)
        if problems:
            bad.append(f"  {key}: {text!r}: " + ", ".join(problems))
    if bad:
        more = f"\n  ... and {len(bad) - limit} more" if len(bad) > limit else ""
        raise ValueError(f"{source}: {len(bad)} reference text(s) hold characters outside the reader's alphabet:\n"
                         + "\n".join(bad[:limit]) + more + "\n" + alphabet_text(alphabet, wildcard))
    return refs


def ctc_frames_needed(text):
    """The fewest output frames a CTC line reader needs for text: one per letter and one blank between doubled letters.

    A '?' may stand for nothing, so it needs no frame of its own."""
    vis = [c for c in text if c != WILDCARD]
    return len(vis) + sum(1 for a, b in zip(vis, vis[1:]) if a == b)


def wild_edit_distance(hyp, ref):
    """Edit distance from a read to a reference whose '?' each stand for any one letter or none, at no cost.

    The same meaning a '?' has in finetune_maps.py's training loss. Divide by the reference's
    visible letters for a character error."""
    n, m = len(hyp), len(ref)
    prev = [0] * (m + 1)
    for j in range(1, m + 1):
        prev[j] = prev[j - 1] + (0 if ref[j - 1] == WILDCARD else 1)
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            wild = ref[j - 1] == WILDCARD
            cur[j] = min(prev[j] + 1,                                                   # a letter read, none there
                         cur[j - 1] + (0 if wild else 1),                               # a letter there, none read
                         prev[j - 1] + (0 if wild or hyp[i - 1] == ref[j - 1] else 1))  # one for one
        prev = cur
    return prev[m]


# ------------------------------------------------------------------ records

def _number(v):
    if isinstance(v, bool):
        raise ValueError
    if isinstance(v, str):
        v = v.strip()
    return float(v)


def _crop(v):
    """A crop as four ints from a list or a string of four numbers (spaces or commas); ValueError otherwise."""
    if isinstance(v, str):
        v = v.replace(",", " ").split()
    vals = [_number(x) for x in v]
    if len(vals) != 4 or any(x != int(x) for x in vals):
        raise ValueError
    return [int(x) for x in vals]


def load_records(path):
    """[(where, record)] from a JSON or CSV records file, with defaults applied; where is "FILE record N" or "FILE line N".

    Raises RecordsError for a file it cannot parse, a field it does not know or a default it does not take."""
    path = Path(path)
    name = path.name
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecordsError([f"{path}: {exc}"]) from None
    out, errors = [], []
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(raw.splitlines())
        header = [h.strip() for h in (reader.fieldnames or [])]
        unknown = [h for h in header if h not in FIELDS and h not in IGNORED]
        if not header:
            raise RecordsError([f"{name}: empty, or no header row (give a first row of field names: "
                                f"{', '.join(FIELDS)})"])
        if unknown:
            raise RecordsError([f"{name}: unknown column{'s' if len(unknown) > 1 else ''} {', '.join(unknown)}; the "
                                f"fields are {', '.join(FIELDS)}"])
        for i, row in enumerate(reader, start=2):
            rec = {k.strip(): v.strip() for k, v in row.items() if k and v is not None and str(v).strip() != ""}
            if rec:
                out.append((f"{name} line {i}", rec))
        return out
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecordsError([f"{name}: not JSON ({exc}); give a JSON list of records, an object with \"lines\", or a "
                            ".csv file"]) from None
    defaults = {}
    if isinstance(data, dict):
        if "lines" not in data or not isinstance(data["lines"], list):
            raise RecordsError([f"{name}: a JSON object needs \"lines\", a list of records"])
        extra = [k for k in data if k not in DEFAULT_FIELDS and k != "lines" and k not in IGNORED]
        if extra:
            raise RecordsError([f"{name}: {', '.join(extra)} cannot be a default; the defaults are "
                                f"{', '.join(DEFAULT_FIELDS)}"])
        defaults = {k: v for k, v in data.items() if k in DEFAULT_FIELDS}
        data = data["lines"]
    if not isinstance(data, list):
        raise RecordsError([f"{name}: give a JSON list of records, an object with \"lines\", or a .csv file"])
    for i, rec in enumerate(data, start=1):
        where = f"{name} record {i}"
        if not isinstance(rec, dict):
            errors.append(f"{where}: a record is an object such as {{\"image\": ..., \"text\": ..., \"y\": ..., "
                          "\"letter_px\": ...}")
            continue
        unknown = [k for k in rec if k not in FIELDS and k not in IGNORED]
        if unknown:
            errors.append(f"{where}: unknown field{'s' if len(unknown) > 1 else ''} {', '.join(unknown)}; the fields "
                          f"are {', '.join(FIELDS)}")
            continue
        out.append((where, {**defaults, **rec}))
    if errors:
        raise RecordsError(errors)
    return out


def check_records(records, base_dir=".", split=None, net_letter_px=NET_LETTER_PX, band=BAND, stride=STRIDE):
    """Validate records (load_records) without decoding any image. Returns (plans, errors, warnings).

    Each plan is the line to cut: where, image (path), key, crop, the window's (H, W), y, x0, x1,
    letter_px, polarity, split, id, text, visible (letters other than '?'), wildcards, band_rows (the
    band's first and last row in image pixels, crop included), width (the band's width at the
    working scale, about), frames and frames_needed, pitch (working pixels per letter). split keeps
    only records whose split is that label. errors: a record that cannot be cut or trained on (a
    missing field, a bad number, an image that does not exist, a row outside the image, a character
    outside the alphabet, a band too narrow for its letters); warnings: a record that can be cut but
    looks wrong (letters much narrower or wider than the network's, band rows beyond the image, two
    lines on one band)."""
    base_dir = Path(base_dir)
    plans, errors, warnings = [], [], []
    shapes = {}
    for where, rec in records:
        if split is not None and str(rec.get("split", "")) != str(split):
            continue
        bad = [f for f in ("image", "text", "y", "letter_px") if f not in rec or rec[f] in (None, "")]
        if bad:
            errors.append(f"{where}: missing {', '.join(bad)}")
            continue
        try:
            y, lp = _number(rec["y"]), _number(rec["letter_px"])
            x0 = None if rec.get("x0") in (None, "") else _number(rec["x0"])
            x1 = None if rec.get("x1") in (None, "") else _number(rec["x1"])
        except (TypeError, ValueError):
            errors.append(f"{where}: y, letter_px, x0 and x1 must be numbers")
            continue
        if not (math.isfinite(y) and math.isfinite(lp)) or lp <= 0:
            errors.append(f"{where}: letter_px {rec['letter_px']}: give the letter height in image pixels, over 0")
            continue
        crop = None
        if rec.get("crop") not in (None, ""):
            try:
                crop = _crop(rec["crop"])
            except (TypeError, ValueError):
                errors.append(f"{where}: crop {rec['crop']!r}: give four whole numbers, Y0 Y1 X0 X1")
                continue
        polarity = str(rec.get("polarity") or "bright")
        if polarity not in ("bright", "dark"):
            errors.append(f"{where}: polarity {polarity!r}: give bright (ink brighter than the ground, as in ink maps) "
                          "or dark (dark ink on a light ground, as in photographs)")
            continue
        text, problems = clean_text(rec["text"])
        if problems:
            errors.append(f"{where}: text has characters the reader does not write: {', '.join(problems)}. Write "
                          f"Greek capitals ({ALPHABET}), and '?' for a letter you cannot see or restore")
            continue
        visible = sum(1 for c in text if c != WILDCARD)
        if not visible:
            errors.append(f"{where}: text has no letters (only '?' or nothing): nothing to learn from")
            continue
        image = Path(str(rec["image"])).expanduser()
        if not image.is_absolute():
            image = base_dir / image
        key = None if rec.get("key") in (None, "") else str(rec["key"])
        if not image.exists():
            errors.append(f"{where}: {image}: no such file or folder (a relative path is relative to the records "
                          f"file's folder, {base_dir})")
            continue
        try:
            if (image, key) not in shapes:
                shapes[(image, key)] = R.image_shape(image, key)
            full = shapes[(image, key)]
            wy0, wy1, wx0, wx1 = R._window(crop, full, image.name)
        except (ImportError, OSError, KeyError, ValueError) as exc:
            errors.append(f"{where}: {exc}")
            continue
        H, W = wy1 - wy0, wx1 - wx0
        x0 = 0.0 if x0 is None else x0
        x1 = float(W) if x1 is None else x1
        if not 0 <= y < H:
            errors.append(f"{where}: y {y:g} is outside the {'crop' if crop else 'image'} (rows 0 to {H - 1})")
            continue
        if not 0 <= x0 < x1 <= W:
            errors.append(f"{where}: x0 {x0:g} and x1 {x1:g}: give 0 <= x0 < x1 <= {W}, the "
                          f"{'crop' if crop else 'image'}'s width")
            continue
        f = net_letter_px / lp
        width = int(round((x1 - x0) * f))
        frames = width // stride
        need = ctc_frames_needed(text)
        lo, hi = y - band[0] * lp, y + band[1] * lp
        plan = {"where": where, "image": str(image), "key": key, "crop": crop, "window": [H, W], "y": y,
                "x0": x0, "x1": x1, "letter_px": lp, "polarity": polarity, "split": rec.get("split"),
                "id": rec.get("id"), "text": text, "visible": visible, "wildcards": len(text) - visible,
                "band_rows": [round(lo + wy0, 1), round(hi + wy0, 1)], "width": width, "frames": frames,
                "frames_needed": need, "pitch": round(width / len(text), 1)}
        if width < 8 or frames < need:
            errors.append(f"{where}: the band from x0 {x0:g} to x1 {x1:g} is {width} px wide at the network's scale "
                          f"({frames} frames), too narrow for {visible} letters (CTC needs at least {need}); check "
                          "x0, x1, letter_px and the text")
            continue
        lo_p, hi_p = PITCH_RANGE[0] * net_letter_px, PITCH_RANGE[1] * net_letter_px
        if not lo_p <= plan["pitch"] <= hi_p:
            warnings.append(f"{where}: {len(text)} letters on a band {width} px wide at the network's scale, "
                            f"{plan['pitch']:g} px a letter, where letters are usually {lo_p:g} to {hi_p:g}: check "
                            "letter_px, the text, and x0 and x1 (the line's first and last letter columns; without "
                            "them the band is the whole width, and may hold other text)")
        if lo < 0 or hi > H:
            warnings.append(f"{where}: band rows {lo:g} to {hi:g} reach beyond the {'crop' if crop else 'image'} (rows "
                            f"0 to {H}); those rows are cut as 0, as the reader reads them")
        plans.append(plan)
    by_image = {}
    for p in plans:
        by_image.setdefault((p["image"], p["key"], tuple(p["crop"] or ())), []).append(p)
    for group in by_image.values():
        group = sorted(group, key=lambda p: p["y"])
        for a, b in zip(group, group[1:]):
            if b["y"] - a["y"] < 0.5 * min(a["letter_px"], b["letter_px"]) and a["x0"] < b["x1"] and b["x0"] < a["x1"]:
                warnings.append(f"{a['where']} and {b['where']}: rows {a['y']:g} and {b['y']:g} are under half a letter "
                                "apart on overlapping columns: the same line twice?")
    if split is not None and not plans and not errors:
        errors.append(f"no record has split {split!r}")
    return plans, errors, warnings


def plan_text(plans, warnings=(), errors=()):
    """The dry run: one line per band to cut, then totals, warnings and errors."""
    out = []
    for p in plans:
        win = f" crop {' '.join(map(str, p['crop']))}," if p["crop"] else ""
        split = f" [{p['split']}]" if p.get("split") is not None else ""
        out.append(f"{p['where']}{split}: {Path(p['image']).name},{win} y {p['y']:g}, x {p['x0']:g} to {p['x1']:g}, "
                   f"letters {p['letter_px']:g} px; band rows {p['band_rows'][0]:g} to {p['band_rows'][1]:g} -> "
                   f"{p['width']} x {int(round((BAND[0] + BAND[1]) * NET_LETTER_PX))} px at the network's scale, "
                   f"{p['pitch']:g} px a letter: {p['text']}")
    vis = sum(p["visible"] for p in plans)
    wild = sum(p["wildcards"] for p in plans)
    out.append(f"{len(plans)} line{'' if len(plans) == 1 else 's'} from {len({p['image'] for p in plans})} image(s), "
               f"{vis} letters and {wild} '?'")
    out += ["warning: " + w for w in warnings]
    out += ["error: " + e for e in errors]
    return "\n".join(out)


# ------------------------------------------------------------------ cutting and the file

def cut_lines(plans, net_letter_px=NET_LETTER_PX, band=BAND, max_pixels=R.MAX_PIXELS, progress=None):
    """The bands of check_records()'s plans as float32 arrays in 0..1 (36 rows by default), with texts and where.

    Each image (or crop, polarity and letter size) is loaded once with load_reduced, normalised once
    (normalize_for_reading) and resized to the working scale as analyze() resizes it; a line's band
    is the rows read_bands() reads at its row, from x0 to x1."""
    rows = int(round((band[0] + band[1]) * net_letter_px))
    groups = {}
    for i, p in enumerate(plans):
        groups.setdefault((p["image"], p["key"], tuple(p["crop"] or ()), p["polarity"], p["letter_px"]), []).append(i)
    imgs, texts, where = [None] * len(plans), [None] * len(plans), [None] * len(plans)
    for (image, key, crop, polarity, lp), idx in groups.items():
        if progress:
            progress(f"{Path(image).name}: {len(idx)} line(s) at letter height {lp:g} px")
        img, k, _ = R.load_reduced(image, key, crop=list(crop) or None, letter_px=lp, net_letter_px=net_letter_px,
                                   max_pixels=max_pixels, progress=progress)
        a0 = R.normalize_for_reading(img, polarity, max_pixels=max_pixels)
        del img
        f = net_letter_px / (lp / k)
        a = R.resize(a0, (max(8, int(round(a0.shape[0] * f))), max(8, int(round(a0.shape[1] * f)))))
        del a0
        for i in idx:
            p = plans[i]
            lo = int(round(p["y"] / k * f - band[0] * net_letter_px))
            c0 = min(max(0, int(round(p["x0"] / k * f))), a.shape[1] - 1)
            c1 = min(max(c0 + 1, int(round(p["x1"] / k * f))), a.shape[1])
            b = np.zeros((rows, c1 - c0), np.float32)
            s0, s1 = max(0, lo), min(a.shape[0], lo + rows)
            if s1 > s0:
                b[s0 - lo:s1 - lo] = a[s0:s1, c0:c1]
            imgs[i], texts[i] = b, p["text"]
            where[i] = {"where": p["where"], "image": Path(image).name, "y": p["y"], "x0": p["x0"], "x1": p["x1"],
                        "letter_px": lp, "crop": p["crop"], "split": p.get("split"), "id": p.get("id")}
    return imgs, texts, where


def save_lines(path, imgs, texts, where, meta):
    """Write bands in LINES.npz's format (scripts/letters/p1667_align.py save_lines): uint8, column-major per band."""
    H = imgs[0].shape[0]
    flat = np.concatenate([(np.clip(a, 0, 1) * 255).round().astype(np.uint8).T.reshape(-1) for a in imgs])
    np.savez(path, flat=flat, widths=np.array([a.shape[1] for a in imgs], np.int32), height=H,
             texts=np.array(json.dumps(texts, ensure_ascii=False)), where=np.array(json.dumps(where, ensure_ascii=False)),
             meta=np.array(json.dumps(meta, ensure_ascii=False)))
    return path


def load_lines(path):
    """(bands as uint8 arrays, texts, where, meta) of a LINES.npz (this module's or p1667_align.py's)."""
    z = np.load(path, allow_pickle=False)
    H, flat, o, imgs = int(z["height"]), z["flat"], 0, []
    for w in z["widths"]:
        imgs.append(flat[o:o + H * w].reshape(w, H).T)
        o += H * w
    return imgs, json.loads(str(z["texts"])), json.loads(str(z["where"])), json.loads(str(z["meta"]))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(records_path, out=None, split=None, dry_run=False, max_pixels=R.MAX_PIXELS, progress=None):
    """Records file to LINES.npz. Returns (plans, warnings, meta); raises RecordsError listing every problem.

    dry_run: validate and plan only (no image is decoded and nothing is written)."""
    records_path = Path(records_path)
    plans, errors, warnings = check_records(load_records(records_path), records_path.parent, split)
    if errors:
        raise RecordsError(errors)
    if not plans:
        raise RecordsError([f"{records_path.name}: no records"])
    meta = {"note": NOTE, "made_by": "kit.letterlines", "version": KIT_VERSION,
            "records": {"file": records_path.name, "sha256": _sha256(records_path)}, "split": split,
            "net_letter_px": NET_LETTER_PX, "band": list(BAND), "lines": len(plans),
            "letters": sum(p["visible"] for p in plans), "wildcards": sum(p["wildcards"] for p in plans),
            "images": sorted({Path(p["image"]).name for p in plans})}
    if dry_run:
        return plans, warnings, meta
    if out is None:
        raise ValueError("give the output file (LINES.npz), or a dry run")
    imgs, texts, where = cut_lines(plans, max_pixels=max_pixels, progress=progress)
    save_lines(out, imgs, texts, where, meta)
    return plans, warnings, meta


def preview(path, imgs, texts, max_lines=100, scale=2):
    """A PNG of the first max_lines bands, each above its text, for checking by eye that every band holds its line (Pillow)."""
    from PIL import Image, ImageDraw
    imgs, texts = imgs[:max_lines], texts[:max_lines]
    widest = max(a.shape[1] for a in imgs)
    s = max(0.25, min(float(scale), 3000.0 / widest))
    font = R._greek_font(18) or R._banner_font(18)
    rows = [max(1, int(round(a.shape[0] * s))) for a in imgs]
    th = 26
    W = max(200, int(round(widest * s)) + 8)
    canvas = Image.new("RGB", (W, sum(r + th + 6 for r in rows) + 4), (255, 255, 255))
    d = ImageDraw.Draw(canvas)
    y = 4
    for a, t, r in zip(imgs, texts, rows):
        g = np.asarray(a, np.float32) / (255.0 if np.asarray(a).dtype.kind in "ui" else 1.0)
        w = max(1, int(round(a.shape[1] * s)))
        canvas.paste(Image.fromarray((np.clip(R.resize(g, (r, w)), 0, 1) * 255).round().astype(np.uint8)).convert("RGB"),
                     (4, y))
        d.text((4, y + r + 2), t, fill=(0, 0, 0), font=font)
        y += r + th + 6
    canvas.save(path)
    return path


# ------------------------------------------------------------------ scoring held-out lines

def score_lines(path, weights, boot=2000, seed=0):
    """Read every band of a LINES.npz with each model and score it against its text. Returns a JSON-able dict.

    weights: a list of models (released names, paths or LineNets). Each band is decoded by best
    path with every letter (no confidence floor: the reader's ink_only before letters under the
    floor become '·'), and the character error is wild_edit_distance() over the text's visible
    letters, summed over lines. With two models or more, diff is each later model's error minus the
    first's, with a 95% interval from a bootstrap over lines (boot draws, seed)."""
    imgs, texts, where, meta = load_lines(path)
    vis = [sum(1 for c in t if c != WILDCARD) for t in texts]
    models, per = [], []
    for spec in weights:
        net = R.load_weights(spec)
        reads, dists = [], []
        for a, t in zip(imgs, texts):
            lp = net.log_probs(np.asarray(a, np.float32) / 255.0)
            s = "".join(ch for ch, _, _, _ in R.ctc_greedy(lp, net.alphabet))
            reads.append(s)
            dists.append(wild_edit_distance(s, t))
        per.append((reads, dists))
        models.append({"weights": R.weights_info(net), "errors": int(sum(dists)), "letters": int(sum(vis)),
                       "cer": round(sum(dists) / max(1, sum(vis)), 4)})
    lines = [{"line": i, "text": t, "where": where[i] if i < len(where) else None,
              "reads": [p[0][i] for p in per], "errors": [p[1][i] for p in per]} for i, t in enumerate(texts)]
    out = {"note": R.NOTE, "lines_file": {"file": Path(path).name, "meta": meta}, "models": models, "lines": lines,
           "decode": "best path, every letter (no confidence floor); '?' in the text matches any one letter or none"}
    if len(per) > 1 and len(texts) > 1:
        rng = np.random.default_rng(seed)
        v = np.array(vis, float)
        d0 = np.array(per[0][1], float)
        out["diff"] = []
        for j in range(1, len(per)):
            dj = np.array(per[j][1], float)
            draws = []
            for _ in range(boot):
                i = rng.integers(0, len(texts), len(texts))
                draws.append((dj[i].sum() - d0[i].sum()) / max(1.0, v[i].sum()))
            lo, hi = np.percentile(draws, [2.5, 97.5])
            out["diff"].append({"model": j, "minus_model": 0, "cer_diff": round((dj.sum() - d0.sum()) / max(1, v.sum()), 4),
                                "ci95": [round(float(lo), 4), round(float(hi), 4)], "boot": boot, "seed": seed})
    return out


def score_text(res):
    """Plain text of score_lines()'s result."""
    out = [res["note"], f"{res['lines_file']['file']}: {len(res['lines'])} lines, {res['models'][0]['letters']} letters "
                        f"({res['decode']})"]
    for j, m in enumerate(res["models"]):
        w = m["weights"]
        out.append(f"model {j}: {w.get('name') or w.get('file')}: character error {m['cer']:.4f} "
                   f"({m['errors']} edits over {m['letters']} letters)")
    for L in res["lines"]:
        out.append(f"line {L['line']:>3}: {L['text']}")
        for j, (s, e) in enumerate(zip(L["reads"], L["errors"])):
            out.append(f"   model {j}: {s or '(none)'}  [{e} edits]")
    for d in res.get("diff", []):
        out.append(f"model {d['model']} minus model {d['minus_model']}: {d['cer_diff']:+.4f} character error "
                   f"(95% interval {d['ci95'][0]:+.4f} to {d['ci95'][1]:+.4f}, bootstrap over lines)")
    return "\n".join(out)
