"""kit.greekpages: synthetic Greek book-hand pages as ink-probability maps, for training letter readers.

Letter readers for the Herculaneum scrolls have few labelled letters to learn from. This module draws pages of
Greek majuscule text as a reader's ink map would show them: a pen-drawn letter layer from a hand description,
degraded by a map model (patchy dropout, smooth warp, anisotropic blur, saturating tone) and laid onto a
procedural papyrus background with fibres, blotches and non-letter strokes. Every page comes with exact labels:
the clean ink mask, each letter's box and character, and the parameters drawn.

The hand is pluggable. `default_style()` is a generic book hand: plain bilinear majuscule letter shapes and wide
ASSUMED parameter ranges, measured on no particular scroll. Anyone can load their own hand and map model from a
JSON file (`--style FILE`; `python -m kit.greekpages style > my-style.json` writes the default to edit). Each
parameter is a number or a [low, high] range drawn uniformly per page.

The text is pluggable too: any UTF-8 Greek text (a file or a folder of .txt files). It is cleaned to the 24
classical majuscules with lunate sigma, accents and breathings dropped, written as scriptio continua. Keep texts
you will evaluate on out of the training text (`--exclude`).

    python -m kit.greekpages gen OUT_DIR --text TEXT [--n 100] [--seed 1] [--style STYLE.json] [--size 512]
    python -m kit.greekpages preview PAGE.npz OUT.png
    python -m kit.greekpages style
    python -m kit.greekpages info

Everything here is synthetic. A page is a rendering aid for training and testing; nothing it makes is a reading
of any papyrus.
"""

import argparse
import json
import math
import os
import sys
import unicodedata
from pathlib import Path

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"
SIGMAS = {"Σ": "Ϲ", "ς": "Ϲ", "σ": "Ϲ"}
PX_MM = 0.0288           # default output pixel, mm (three times a 9.6 um map pixel)
SIZE = 512               # default page side, pixels
OVERSAMPLE = 2           # letters are drawn at this many times the output resolution, then averaged down
STROKE_STEP = 0.01       # centreline sample spacing in letter-height units
INK_T = 0.2              # clean ink above this is a stroke pixel in the mask


class PagesError(ValueError):
    """A refused input: bad style, no usable text, a bad page size."""


def _np():
    import numpy
    return numpy


def _ndi():
    try:
        from scipy import ndimage
    except ImportError as e:  # pragma: no cover
        raise PagesError("needs scipy (pip install scipy)") from e
    return ndimage


# ------------------------------------------------------------------ style (hand and map model)
def default_style():
    """The generic book hand and map model. Every range is ASSUMED (a wide box, measured on no scroll); replace it
    with your own measurements for a particular hand or scan."""
    return {
        "schema": "greekpages-style/1",
        "name": "generic-bookhand",
        "about": ("Generic Greek book hand: plain bilinear majuscule shapes, wide ASSUMED ranges, measured on no "
                  "particular scroll. Edit any value; a [low, high] pair is drawn uniformly per page."),
        "hand": {
            "letter_height_mm": [1.8, 5.0],
            "glyph_width_scale": [0.8, 1.25],
            "letter_gap_h": [0.10, 0.60],
            "gap_sd_h": [0.0, 0.18],
            "line_pitch_h": [1.5, 2.4],
            "nib_thick_mm": [0.15, 0.80],
            "nib_contrast": [1.0, 2.6],
            "pen_angle_deg": [90.0, 230.0],
            "slant_mean_deg": [-6.0, 12.0],
            "slant_sd_deg": [0.0, 6.0],
            "height_cv": [0.0, 0.15],
            "baseline_sd_mm": [0.0, 0.35],
            "ink_load_drop": [0.0, 0.4],
        },
        "map": {
            "dropout": [0.0, 0.6],
            "dropout_corr_mm": 0.6,
            "warp_mm": [0.0, 0.12],
            "warp_corr_mm": 3.0,
            "blur_sigma_mm": [0.02, 0.20],
            "blur_aniso": [0.6, 1.6],
            "tone_gain": [1.0, 6.0],
            "ink_amp": [0.15, 0.9],
        },
        "background": {
            "level": [0.0, 0.25],
            "noise": [0.02, 0.10],
            "fibre_amp": [0.0, 0.30],
            "fibre_angle_deg": [-5.0, 5.0],
            "blotches": [0, 6],
            "blotch_amp": [0.1, 0.5],
            "strokes": [0, 8],
            "stroke_amp": [0.2, 0.8],
        },
    }


def load_style(path=None):
    """The default style with the sections and keys of the JSON file at PATH laid over it. Unknown keys refuse."""
    style = default_style()
    if path is None:
        return style
    try:
        user = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PagesError(f"cannot read style {path}: {e}") from e
    if not isinstance(user, dict):
        raise PagesError(f"style {path} must be a JSON object")
    for sec in ("hand", "map", "background"):
        for k, v in (user.get(sec) or {}).items():
            if k not in style[sec]:
                raise PagesError(f"style {path}: unknown {sec} key {k!r} (known: {', '.join(style[sec])})")
            _check_value(f"{sec}.{k}", v)
            style[sec][k] = v
    for k in ("name", "about"):
        if k in user:
            style[k] = str(user[k])
    return style


def _check_value(name, v):
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if isinstance(v, (list, tuple)) and len(v) == 2:
        ok = all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v) \
            and v[0] <= v[1]
    if not ok:
        raise PagesError(f"style value {name} must be a finite number or a [low, high] pair with low <= high")


def draw(section, rng):
    """One value per key of SECTION: a number as is, a [low, high] pair uniformly (integers stay integers)."""
    out = {}
    for k, v in section.items():
        if isinstance(v, (list, tuple)):
            lo, hi = v
            if isinstance(lo, int) and isinstance(hi, int):
                out[k] = int(rng.integers(lo, hi + 1))
            else:
                out[k] = float(rng.uniform(lo, hi))
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ text
def clean_text(text):
    """Greek text to scriptio continua over ALPHABET: accents and breathings dropped, every sigma lunate, every
    other character removed."""
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.category(ch) == "Mn":
            continue
        ch = SIGMAS.get(ch, ch)
        up = ch.upper()
        up = SIGMAS.get(up, up)
        if up in ALPHABET:
            out.append(up)
    return "".join(out)


def text_bank(path, exclude=(), min_len=40):
    """Cleaned letter strings from PATH (a .txt file or a folder searched for *.txt), leaving out files whose name
    is in EXCLUDE. Returns (pieces, stats)."""
    p = Path(path)
    if p.is_dir():
        files = sorted(q for q in p.rglob("*.txt") if q.is_file())
    elif p.is_file():
        files = [p]
    else:
        raise PagesError(f"no text at {path}")
    ex = {os.path.basename(e) for e in exclude}
    pieces, skipped, letters = [], 0, 0
    for f in files:
        if f.name in ex:
            skipped += 1
            continue
        s = clean_text(f.read_text(encoding="utf-8", errors="replace"))
        if len(s) >= min_len:
            pieces.append(s)
            letters += len(s)
    if not pieces:
        raise PagesError(f"no Greek text of at least {min_len} letters in {path}")
    return pieces, {"files": len(files), "excluded": skipped, "pieces": len(pieces), "letters": letters}


def sample_lines(rng, pieces, n_lines, n_letters):
    """N_LINES consecutive lines of N_LETTERS from one random place in one random piece."""
    need = n_lines * n_letters
    long = [p for p in pieces if len(p) >= need] or pieces
    p = long[int(rng.integers(len(long)))]
    if len(p) < need:
        p = p * (need // len(p) + 1)
    s = int(rng.integers(0, len(p) - need + 1))
    t = p[s:s + need]
    return [t[i * n_letters:(i + 1) * n_letters] for i in range(n_lines)]


# ------------------------------------------------------------------ letter shapes (generic bilinear majuscule)
def _L(*pts):
    return ("L", [tuple(map(float, p)) for p in pts])


def _A(cx, cy, rx, ry, a0, a1):
    """Elliptical arc, angles in degrees (0 right, 90 down), from A0 to A1."""
    return ("A", float(cx), float(cy), float(rx), float(ry), float(a0), float(a1))


# advance width and strokes; each stroke a list of primitives drawn without a pen lift; unit letter height, y down
GLYPHS = {
    "Α": (0.80, [[_L((0.40, 0.0), (0.0, 1.0))], [_L((0.40, 0.0), (0.80, 1.0))], [_L((0.18, 0.60), (0.62, 0.60))]]),
    "Β": (0.62, [[_L((0, 0), (0, 1))],
                 [_L((0, 0), (0.30, 0)), _A(0.30, 0.24, 0.24, 0.24, -90, 90), _L((0.30, 0.48), (0, 0.48))],
                 [_L((0, 0.48), (0.34, 0.48)), _A(0.34, 0.74, 0.28, 0.26, -90, 90), _L((0.34, 1.0), (0, 1.0))]]),
    "Γ": (0.60, [[_L((0, 0), (0, 1))], [_L((0, 0), (0.60, 0))]]),
    "Δ": (0.84, [[_L((0.42, 0.0), (0.0, 1.0))], [_L((0.42, 0.0), (0.84, 1.0))], [_L((0.0, 1.0), (0.84, 1.0))]]),
    "Ε": (0.68, [[_A(0.44, 0.5, 0.44, 0.5, -45, -315)], [_L((0.02, 0.5), (0.40, 0.5))]]),
    "Ζ": (0.70, [[_L((0.0, 0.0), (0.70, 0.0), (0.0, 1.0), (0.70, 1.0))]]),
    "Η": (0.74, [[_L((0, 0), (0, 1))], [_L((0.74, 0), (0.74, 1))], [_L((0, 0.5), (0.74, 0.5))]]),
    "Θ": (0.78, [[_A(0.39, 0.5, 0.39, 0.5, -90, -450)], [_L((0.12, 0.5), (0.66, 0.5))]]),
    "Ι": (0.0, [[_L((0, 0), (0, 1))]]),
    "Κ": (0.70, [[_L((0, 0), (0, 1))], [_L((0.66, 0.0), (0.0, 0.56))], [_L((0.20, 0.42), (0.70, 1.0))]]),
    "Λ": (0.80, [[_L((0.40, 0.0), (0.0, 1.0))], [_L((0.40, 0.0), (0.80, 1.0))]]),
    "Μ": (0.98, [[_L((0.0, 0.0), (0.0, 1.0))], [_L((0.0, 0.0), (0.49, 0.85))], [_L((0.49, 0.85), (0.98, 0.0))],
                 [_L((0.98, 0.0), (0.98, 1.0))]]),
    "Ν": (0.80, [[_L((0.0, 0.0), (0.0, 1.0))], [_L((0.0, 0.0), (0.80, 1.0))], [_L((0.80, 1.0), (0.80, 0.0))]]),
    "Ξ": (0.70, [[_L((0, 0), (0.70, 0))], [_L((0.14, 0.5), (0.56, 0.5))], [_L((0, 1), (0.70, 1))]]),
    "Ο": (0.80, [[_A(0.40, 0.5, 0.40, 0.5, -90, -450)]]),
    "Π": (0.80, [[_L((0.0, 0.0), (0.0, 1.0))], [_L((0.0, 0.0), (0.80, 0.0))], [_L((0.80, 0.0), (0.80, 1.0))]]),
    "Ρ": (0.60, [[_L((0.0, 0.0), (0.0, 1.25))],
                 [_L((0.0, 0.0), (0.30, 0.0)), _A(0.30, 0.25, 0.28, 0.25, -90, 90), _L((0.30, 0.50), (0.0, 0.50))]]),
    "Ϲ": (0.68, [[_A(0.44, 0.5, 0.44, 0.5, -45, -315)]]),
    "Τ": (0.80, [[_L((0.0, 0.0), (0.80, 0.0))], [_L((0.40, 0.0), (0.40, 1.0))]]),
    "Υ": (0.80, [[_L((0.0, 0.0), (0.40, 0.50), (0.40, 1.0))], [_L((0.80, 0.0), (0.40, 0.50))]]),
    "Φ": (0.96, [[_L((0.48, -0.2), (0.48, 1.2))], [_A(0.48, 0.5, 0.48, 0.32, -90, -450)]]),
    "Χ": (0.80, [[_L((0, 0), (0.80, 1))], [_L((0.80, 0), (0, 1))]]),
    "Ψ": (0.88, [[_L((0.44, -0.1), (0.44, 1.1))], [_A(0.44, 0.10, 0.44, 0.45, 180, 0)]]),
    "Ω": (1.10, [[_A(0.28, 0.55, 0.28, 0.45, 170, 360), _A(0.28, 0.55, 0.28, 0.45, 0, 90),
                  _A(0.82, 0.55, 0.28, 0.45, 90, 180), _A(0.82, 0.55, 0.28, 0.45, 180, 370)]]),
}


def _sample(prim, step):
    np = _np()
    if prim[0] == "L":
        pts = np.asarray(prim[1], float)
        out = [pts[:1]]
        for a, b in zip(pts[:-1], pts[1:]):
            n = max(1, int(math.ceil(float(np.hypot(*(b - a))) / step)))
            out.append(a + (b - a) * np.linspace(0, 1, n + 1)[1:, None])
        return np.concatenate(out)
    _, cx, cy, rx, ry, a0, a1 = prim
    n = max(8, int(math.ceil(abs(math.radians(a1 - a0)) * max(rx, ry) / step)))
    t = np.radians(np.linspace(a0, a1, n + 1))
    return np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1)


def glyph_strokes(ch, step=STROKE_STEP):
    """(advance width, list of (N, 2) centrelines in letter units, x right and y down, height 1)."""
    np = _np()
    if ch not in GLYPHS:
        raise PagesError(f"no letter shape for {ch!r}")
    w, strokes = GLYPHS[ch]
    return w, [np.concatenate([_sample(p, step) for p in st]) for st in strokes]


# ------------------------------------------------------------------ drawing
def layout(lines, hand, rng, size_mm):
    """Place letters of LINES on a page SIZE_MM square. Returns a list of (char, centrelines in mm, ink load, line)."""
    np = _np()
    h0 = hand["letter_height_mm"]
    pitch = hand["line_pitch_h"] * h0
    placed = []
    y = 0.5 * pitch
    margin = 0.25 * h0
    for li, line in enumerate(lines):
        x = margin + float(rng.uniform(0, h0))
        base_jit = float(rng.normal(0, hand["baseline_sd_mm"])) if hand["baseline_sd_mm"] > 0 else 0.0
        for ch in line:
            cv = float(rng.normal(0, hand["height_cv"])) if hand["height_cv"] > 0 else 0.0
            h = h0 * max(0.5, 1.0 + cv)
            slant = math.radians(hand["slant_mean_deg"] + (float(rng.normal(0, hand["slant_sd_deg"]))
                                                            if hand["slant_sd_deg"] > 0 else 0.0))
            ws = hand["glyph_width_scale"]
            adv, strokes = glyph_strokes(ch)
            top = y + base_jit + (h0 - h)
            pts = []
            for st in strokes:
                yy = top + st[:, 1] * h
                xx = x + st[:, 0] * h * ws + (top + h - yy) * math.tan(slant)
                pts.append(np.stack([xx, yy], axis=1))
            load = 1.0 - float(rng.uniform(0, hand["ink_load_drop"]))
            placed.append((ch, pts, load, li))
            gap = hand["letter_gap_h"] + (float(rng.normal(0, hand["gap_sd_h"])) if hand["gap_sd_h"] > 0 else 0.0)
            x += (adv * ws + max(0.02, gap)) * h + hand["nib_thick_mm"]
            if x > size_mm:
                break
        y += pitch
        if y > size_mm + pitch:
            break
    return placed


def render_ink(placed, hand, size_px, px_mm):
    """Clean ink layer (float32, 0 to 1), letter boxes [(char, y0, x0, y1, x1) in pixels] of PLACED letters inside
    the page, and the text actually drawn (one string per line, letters inside the page only).
    The nib is broad: width runs from thick/contrast to thick with the stroke direction against the pen angle."""
    np = _np()
    nd = _ndi()
    up = OVERSAMPLE
    n = size_px * up
    pm = px_mm / up
    thick = hand["nib_thick_mm"]
    thin = thick / max(1.0, hand["nib_contrast"])
    pen = math.radians(hand["pen_angle_deg"])
    nbins = 8
    radii = np.linspace(thin / 2 / pm, thick / 2 / pm, nbins)
    ink = np.zeros((n, n), np.float32)
    boxes = []
    drawn = {}
    for ch, strokes, load, li in placed:
        allp = np.concatenate(strokes)
        y0, x0 = allp[:, 1].min() - thick / 2, allp[:, 0].min() - thick / 2
        y1, x1 = allp[:, 1].max() + thick / 2, allp[:, 0].max() + thick / 2
        if x1 <= 0 or y1 <= 0 or x0 >= n * pm or y0 >= n * pm:
            continue
        cells = [np.zeros((n, n), bool) for _ in range(nbins)]
        for st in strokes:
            d = np.gradient(st, axis=0) if len(st) > 1 else np.zeros_like(st)
            ang = np.arctan2(d[:, 1], d[:, 0])
            k = np.clip(np.round(np.abs(np.sin(ang - pen)) * (nbins - 1)).astype(int), 0, nbins - 1)
            iy = np.round(st[:, 1] / pm).astype(int)
            ix = np.round(st[:, 0] / pm).astype(int)
            ok = (iy >= 0) & (iy < n) & (ix >= 0) & (ix < n)
            for b in range(nbins):
                sel = ok & (k == b)
                cells[b][iy[sel], ix[sel]] = True
        letter = np.zeros((n, n), bool)
        for b in range(nbins):
            if cells[b].any():
                letter |= nd.distance_transform_edt(~cells[b]) <= radii[b]
        ink = np.maximum(ink, letter.astype(np.float32) * load)
        by0, bx0 = max(0, int(y0 / px_mm)), max(0, int(x0 / px_mm))
        by1, bx1 = min(size_px, int(math.ceil(y1 / px_mm))), min(size_px, int(math.ceil(x1 / px_mm)))
        if by1 > by0 and bx1 > bx0:
            boxes.append((ch, by0, bx0, by1, bx1))
            drawn.setdefault(li, []).append(ch)
    ink = ink.reshape(size_px, up, size_px, up).mean(axis=(1, 3))
    return ink, boxes, ["".join(drawn[k]) for k in sorted(drawn)]


def _smooth_field(shape, corr_px, rng):
    """Zero-mean, unit-variance Gaussian random field with correlation length CORR_PX."""
    np = _np()
    nd = _ndi()
    f = nd.gaussian_filter(rng.standard_normal(shape), max(0.5, corr_px), mode="wrap")
    sd = float(f.std())
    return (f - f.mean()) / (sd if sd > 0 else 1.0)


def map_model(ink, mp, rng, px_mm):
    """Ink-map model: patchy dropout, smooth warp, anisotropic blur, saturating tone. Returns ink probability."""
    np = _np()
    nd = _ndi()
    a = ink.astype(np.float32)
    if mp["dropout"] > 0:
        f = _smooth_field(a.shape, mp["dropout_corr_mm"] / px_mm, rng)
        a = a * (f > np.quantile(f, mp["dropout"]))
    if mp["warp_mm"] > 0:
        amp = mp["warp_mm"] / px_mm
        corr = mp["warp_corr_mm"] / px_mm
        dy = amp * _smooth_field(a.shape, corr, rng)
        dx = amp * _smooth_field(a.shape, corr, rng)
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]].astype(np.float32)
        a = nd.map_coordinates(a, [yy + dy, xx + dx], order=1, mode="nearest").astype(np.float32)
    sy = mp["blur_sigma_mm"] / px_mm
    a = nd.gaussian_filter(a, (sy, sy * mp["blur_aniso"]))
    return (mp["ink_amp"] * (1.0 - np.exp(-mp["tone_gain"] * a))).astype(np.float32)


def background(size_px, bg, rng, px_mm):
    """Procedural papyrus in probability space: level, noise, fibres along one axis, blotches and non-letter strokes."""
    np = _np()
    nd = _ndi()
    shape = (size_px, size_px)
    b = np.full(shape, bg["level"], np.float32)
    b += bg["noise"] * rng.standard_normal(shape).astype(np.float32)
    if bg["fibre_amp"] > 0:
        f = nd.gaussian_filter(rng.standard_normal(shape), (0.05 / px_mm, 2.0 / px_mm), mode="wrap")
        f = (f - f.mean()) / (f.std() or 1.0)
        f = nd.rotate(f, bg["fibre_angle_deg"], reshape=False, mode="wrap")
        b += bg["fibre_amp"] * np.clip(f, 0, None).astype(np.float32) / 3.0
    yy, xx = np.mgrid[0:size_px, 0:size_px]
    for _ in range(int(bg["blotches"])):
        cy, cx = rng.uniform(0, size_px, 2)
        r = float(rng.uniform(0.3, 2.0)) / px_mm
        b += float(rng.uniform(*_pair(bg["blotch_amp"]))) * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * r * r))
    if int(bg["strokes"]) > 0:
        s = np.zeros(shape, bool)
        for _ in range(int(bg["strokes"])):
            p = rng.uniform(0, size_px, 2)
            ang = float(rng.uniform(0, math.pi))
            length = float(rng.uniform(1.0, 8.0)) / px_mm
            t = np.linspace(0, 1, int(length) + 2)
            bend = float(rng.normal(0, 0.15)) * length
            py = p[0] + t * length * math.sin(ang) + bend * t * (1 - t) * math.cos(ang)
            px = p[1] + t * length * math.cos(ang) - bend * t * (1 - t) * math.sin(ang)
            ok = (py >= 0) & (py < size_px) & (px >= 0) & (px < size_px)
            s[py[ok].astype(int), px[ok].astype(int)] = True
        s = nd.binary_dilation(s, iterations=max(1, int(round(0.03 / px_mm))))
        b += float(rng.uniform(*_pair(bg["stroke_amp"]))) * nd.gaussian_filter(s.astype(np.float32), 1.0)
    return np.clip(b, 0.0, 1.0)


def _pair(v):
    return tuple(v) if isinstance(v, (list, tuple)) else (v, v)


def page(seed, pieces, style=None, size_px=SIZE, px_mm=PX_MM):
    """One synthetic page. Returns a dict: map (float32 ink probability), ink (clean ink, float32), mask (bool),
    boxes (list of (char, y0, x0, y1, x1)), text (the letters drawn, one string per line), params (everything
    drawn)."""
    np = _np()
    if size_px < 64 or size_px > 8192:
        raise PagesError(f"page size {size_px} px is outside 64 to 8192")
    style = style or default_style()
    rng = np.random.default_rng(int(seed))
    hand = draw(style["hand"], rng)
    mp = draw(style["map"], rng)
    bg = draw(style["background"], rng)
    size_mm = size_px * px_mm
    h = hand["letter_height_mm"]
    adv = (0.8 * hand["glyph_width_scale"] + hand["letter_gap_h"]) * h + hand["nib_thick_mm"]
    n_letters = max(1, int(size_mm / adv) + 2)
    n_lines = max(1, int(size_mm / (hand["line_pitch_h"] * h)) + 1)
    lines = sample_lines(rng, pieces, n_lines, n_letters)
    placed = layout(lines, hand, rng, size_mm)
    ink, boxes, drawn = render_ink(placed, hand, size_px, px_mm)
    p_ink = map_model(ink, mp, rng, px_mm)
    bgm = background(size_px, bg, rng, px_mm)
    m = 1.0 - (1.0 - bgm) * (1.0 - p_ink)
    if not np.isfinite(m).all():
        raise PagesError(f"page {seed}: non-finite map")
    return {"map": m.astype(np.float32), "ink": ink.astype(np.float32), "mask": ink > INK_T, "boxes": boxes,
            "text": drawn, "params": {"seed": int(seed), "px_mm": px_mm, "style": style.get("name"),
                                      "hand": hand, "map": mp, "background": bg}}


def save_page(pg, path):
    """Compressed .npz: map and ink as float16, mask, boxes (int32 y0 x0 y1 x1), chars, text and params as JSON."""
    np = _np()
    tmp = f"{path}.tmp.npz"
    np.savez_compressed(tmp, map=pg["map"].astype(np.float16), ink=pg["ink"].astype(np.float16), mask=pg["mask"],
                        boxes=np.asarray([b[1:] for b in pg["boxes"]], np.int32).reshape(-1, 4),
                        chars=np.asarray("".join(b[0] for b in pg["boxes"])),
                        meta=np.asarray(json.dumps({"text": pg["text"], "params": pg["params"]}, ensure_ascii=False)))
    os.replace(tmp, path)


def load_page(path):
    np = _np()
    with np.load(path) as z:
        meta = json.loads(str(z["meta"]))
        chars = str(z["chars"])
        boxes = [(c,) + tuple(int(v) for v in b) for c, b in zip(chars, z["boxes"])]
        return {"map": z["map"].astype(np.float32), "ink": z["ink"].astype(np.float32), "mask": z["mask"],
                "boxes": boxes, "text": meta["text"], "params": meta["params"]}


def generate(out_dir, pieces, n, seed, style=None, size_px=SIZE, px_mm=PX_MM, progress=print):
    """N pages with seeds SEED*100000 + i into OUT_DIR/page-SEED-I.npz; pages already written are kept."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i in range(int(n)):
        p = os.path.join(out_dir, f"page-{int(seed)}-{i:05d}.npz")
        if not os.path.exists(p):
            save_page(page(int(seed) * 100000 + i, pieces, style, size_px, px_mm), p)
        paths.append(p)
        if progress:
            progress(f"PROGRESS {i + 1}/{n} {os.path.basename(p)}")
    return paths


def preview(pg, path):
    """PNG of the map (left) and the clean ink (right), letter boxes outlined on the map. Needs Pillow."""
    np = _np()
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:  # pragma: no cover
        raise PagesError("preview needs Pillow (pip install pillow)") from e
    m = (255 * (1.0 - np.clip(pg["map"], 0, 1))).astype(np.uint8)
    k = (255 * (1.0 - np.clip(pg["ink"], 0, 1))).astype(np.uint8)
    img = Image.fromarray(np.concatenate([m, np.full((m.shape[0], 8), 255, np.uint8), k], axis=1)).convert("RGB")
    d = ImageDraw.Draw(img)
    for _, y0, x0, y1, x1 in pg["boxes"]:
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(40, 110, 200))
    img.save(path)


# ------------------------------------------------------------------ command line
def build_parser(ap=None):
    ap = ap or argparse.ArgumentParser(prog="python -m kit.greekpages", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="write N synthetic pages")
    g.add_argument("out")
    g.add_argument("--text", required=True, help="a Greek .txt file or a folder of them")
    g.add_argument("--exclude", nargs="*", default=[], help="file names to leave out of the text (evaluation texts)")
    g.add_argument("--n", type=int, default=100)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--style", default=None, help="style JSON (hand, map, background); default: generic book hand")
    g.add_argument("--size", type=int, default=SIZE, help="page side in pixels")
    g.add_argument("--px-mm", type=float, default=PX_MM, help="pixel size in mm")
    v = sub.add_parser("preview", help="PNG of one page")
    v.add_argument("page")
    v.add_argument("out")
    sub.add_parser("style", help="print the default style JSON to edit")
    sub.add_parser("info", help="print constants and the alphabet as JSON")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "gen":
            pieces, stats = text_bank(a.text, a.exclude)
            print(json.dumps({"text": stats}, ensure_ascii=False))
            paths = generate(a.out, pieces, a.n, a.seed, load_style(a.style), a.size, a.px_mm)
            print(f"DONE {len(paths)} pages in {a.out}")
        elif a.cmd == "preview":
            preview(load_page(a.page), a.out)
            print(a.out)
        elif a.cmd == "style":
            print(json.dumps(default_style(), indent=1, ensure_ascii=False))
        else:
            print(json.dumps({"alphabet": ALPHABET, "px_mm": PX_MM, "size": SIZE, "oversample": OVERSAMPLE,
                              "ink_t": INK_T, "letters": len(GLYPHS)}, ensure_ascii=False))
    except PagesError as e:
        print(f"greekpages: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
