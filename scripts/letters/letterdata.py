"""Synthetic text lines for training and testing a Greek letter reader on ink maps.

Every image here is synthetic: rendered letters with known truth, degraded to look like
an ink-model map (or like a hand-drawn ink label). Nothing here is a reading of a papyrus.

A line sample is a band of fixed height around one text line, with letters about H_PX px
tall, the line's letter string, and each letter's horizontal extent. Glyphs come from two
independent sources so a reader cannot overfit one geometry:

- "skeleton": centreline strokes of a Herculaneum-style formal bookhand written here
  (bilinear capitals, lunate sigma and epsilon, a small floating omicron, descending rho
  and phi), swept with a broad nib at a random pen angle.
- "font": Greek capitals from whatever TrueType fonts are installed (DejaVu, FreeFont,
  Liberation, Noto ...), with random weight, width and slant.

Domains:
- "map": blur, ink dropout, crackle, papyrus fibre texture, false-ink speckle, faint
  ghost text one line away, saturating tone, contrast compression and noise, like the
  output of an ink model.
- "mask": thresholded strokes of a fairly even width, like hand-drawn ink labels.

Text is uniform random letters by default, so a reader trained on it learns letter shapes
and not Greek: language belongs in a separate, switchable language model.

numpy only; Pillow is needed for rendering (optional import).
"""

import math
from functools import lru_cache
from pathlib import Path

import numpy as np

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"   # lunate sigma U+03F9
H_PX = 16                    # letter height in the working band, px
BAND_TOP = 1.1               # band rows from the letter centre line: [-BAND_TOP h, +BAND_BOT h)
BAND_BOT = 1.15
SS = 3                       # supersampling for rendering

# ------------------------------------------------------------------ skeleton hand
# Centrelines in letter units: x right from the letter's left edge, y down, y = 0 top line,
# y = 1 base line. Each glyph: (advance width, [strokes]); a stroke is a list of points or
# ("arc", cx, cy, rx, ry, a0_deg, a1_deg) with angles counterclockwise from +x, y up.


def _arc(cx, cy, rx, ry, a0, a1, n=24):
    t = np.radians(np.linspace(a0, a1, n))
    return [(cx + rx * math.cos(u), cy - ry * math.sin(u)) for u in t]


def _skeletons():
    S = {}
    S["Α"] = [(0.85, [[(0.0, 1.0), (0.42, 0.0), (0.85, 1.0)], [(0.18, 0.62), (0.68, 0.62)]]),
              (0.85, [[(0.05, 1.0), (0.45, 0.0), (0.85, 1.0)], _arc(0.36, 0.72, 0.2, 0.17, 20, 340)])]
    S["Β"] = [(0.62, [[(0.0, 0.0), (0.0, 1.0)], [(0.0, 0.0)] + _arc(0.22, 0.24, 0.32, 0.24, 90, -90) + [(0.0, 0.48)],
                     [(0.0, 0.48)] + _arc(0.25, 0.74, 0.36, 0.26, 90, -90) + [(0.0, 1.0)]])]
    S["Γ"] = [(0.62, [[(0.0, 1.0), (0.0, 0.0), (0.62, 0.0)]])]
    S["Δ"] = [(0.9, [[(0.0, 1.0), (0.45, 0.0), (0.9, 1.0), (0.0, 1.0)]])]
    S["Ε"] = [(0.7, [_arc(0.45, 0.5, 0.45, 0.5, 60, 300), [(0.02, 0.5), (0.5, 0.5)]]),
              (0.65, [[(0.62, 0.0), (0.0, 0.0), (0.0, 1.0), (0.65, 1.0)], [(0.0, 0.5), (0.5, 0.5)]])]
    S["Ζ"] = [(0.75, [[(0.03, 0.0), (0.72, 0.0), (0.03, 1.0), (0.75, 1.0)]])]
    S["Η"] = [(0.75, [[(0.0, 0.0), (0.0, 1.0)], [(0.75, 0.0), (0.75, 1.0)], [(0.0, 0.5), (0.75, 0.5)]])]
    S["Θ"] = [(0.85, [_arc(0.42, 0.5, 0.42, 0.5, 0, 360, 36), [(0.12, 0.5), (0.72, 0.5)]]),
              (0.85, [_arc(0.42, 0.5, 0.42, 0.5, 0, 360, 36), [(0.32, 0.5), (0.52, 0.5)]])]
    S["Ι"] = [(0.08, [[(0.04, 0.0), (0.04, 1.0)]])]
    S["Κ"] = [(0.72, [[(0.0, 0.0), (0.0, 1.0)], [(0.68, 0.0), (0.03, 0.56)], [(0.22, 0.42), (0.72, 1.0)]]),
              (0.72, [[(0.08, 0.0), (0.0, 0.5), (0.04, 1.0)], [(0.65, 0.02), (0.05, 0.55), (0.72, 1.0)]])]
    S["Λ"] = [(0.85, [[(0.0, 1.0), (0.42, 0.0), (0.85, 1.0)]])]
    S["Μ"] = [(1.0, [[(0.0, 1.0), (0.06, 0.0), (0.5, 0.75), (0.94, 0.0), (1.0, 1.0)]]),
              (1.05, [[(0.0, 1.0), (0.2, 0.0), (0.52, 0.85), (0.85, 0.0), (1.05, 1.0)]]),
              (0.95, [[(0.0, 1.0)] + _arc(0.25, 0.45, 0.24, 0.45, 180, 0, 12) + _arc(0.72, 0.45, 0.23, 0.45, 180, 0, 12)[1:] + [(0.95, 1.0)]])]
    S["Ν"] = [(0.75, [[(0.0, 1.0), (0.0, 0.0), (0.75, 1.0), (0.75, 0.0)]]),
              (0.75, [[(0.0, 1.0), (0.08, 0.0), (0.7, 1.0), (0.78, -0.05)]])]
    S["Ξ"] = [(0.72, [[(0.04, 0.0), (0.68, 0.0)], [(0.14, 0.5), (0.58, 0.5)], [(0.0, 1.0), (0.72, 1.0)]]),
              (0.72, [[(0.04, 0.0), (0.68, 0.0)], [(0.14, 0.5), (0.58, 0.5)], [(0.0, 1.0), (0.72, 1.0)], [(0.36, 0.38), (0.36, 0.62)]])]
    S["Ο"] = [(0.62, [_arc(0.31, 0.44, 0.31, 0.38, 0, 360, 32)]), (0.8, [_arc(0.4, 0.5, 0.4, 0.5, 0, 360, 32)])]
    S["Π"] = [(0.8, [[(0.0, 0.0), (0.0, 1.0)], [(-0.06, 0.0), (0.82, 0.0)], [(0.72, 0.0), (0.74, 0.9), (0.84, 1.0)]]),
              (0.8, [[(0.04, 0.0), (0.0, 1.0)], [(-0.06, 0.02), (0.8, 0.0)], [(0.7, 0.0), (0.72, 1.0)]])]
    S["Ρ"] = [(0.62, [[(0.0, 0.0), (0.0, 1.3)], [(0.0, 0.0)] + _arc(0.25, 0.26, 0.35, 0.26, 90, -90) + [(0.0, 0.52)]])]
    S["Ϲ"] = [(0.7, [_arc(0.45, 0.5, 0.45, 0.5, 55, 305)])]
    S["Τ"] = [(0.8, [[(0.0, 0.0), (0.8, 0.0)], [(0.4, 0.0), (0.4, 1.0)]]),
              (0.8, [[(0.0, 0.08), (0.1, 0.0), (0.8, 0.0)], [(0.4, 0.0), (0.4, 0.96), (0.5, 1.0)]])]
    S["Υ"] = [(0.8, [[(0.0, 0.0), (0.4, 0.5), (0.8, 0.0)], [(0.4, 0.5), (0.4, 1.0)]]),
              (0.8, [_arc(0.2, 0.0, 0.2, 0.5, 180, 270, 8) + _arc(0.6, 0.0, 0.2, 0.5, 270, 360, 8), [(0.4, 0.5), (0.4, 1.0)]])]
    S["Φ"] = [(0.95, [[(0.48, -0.28), (0.48, 1.28)], _arc(0.48, 0.48, 0.48, 0.32, 0, 360, 32)])]
    S["Χ"] = [(0.8, [[(0.0, 0.0), (0.8, 1.0)], [(0.8, 0.0), (0.0, 1.0)]])]
    S["Ψ"] = [(0.95, [[(0.48, -0.25), (0.48, 1.0)], _arc(0.48, 0.0, 0.46, 0.6, 180, 360, 16)])]
    S["Ω"] = [(1.0, [[(0.08, 0.15)] + _arc(0.27, 0.55, 0.22, 0.45, 160, 360, 10)[1:] + _arc(0.73, 0.55, 0.22, 0.45, 180, 380, 10)[1:]]),
              (0.9, [_arc(0.45, 0.45, 0.4, 0.45, -60, 240, 28), [(0.0, 1.0), (0.25, 1.0)], [(0.65, 1.0), (0.9, 1.0)]])]
    return S


SKELETONS = _skeletons()


def _sweep(draw, pts, half, thin_px, value=255):
    """Draw a broad nib (segment of half-length vector `half`) swept along pts, plus a round pen thin_px wide."""
    n = max(1, int(math.ceil(2 * math.hypot(*half) / max(1.0, thin_px * 0.5))))
    for k in range(n + 1):
        f = -1 + 2 * k / n
        off = (half[0] * f, half[1] * f)
        q = [(x + off[0], y + off[1]) for x, y in pts]
        if len(q) > 1:
            draw.line(q, fill=value, width=max(1, int(round(thin_px))), joint="curve")
        r = thin_px / 2
        for x, y in (q[0], q[-1]):
            draw.ellipse([x - r, y - r, x + r, y + r], fill=value)


def render_skeleton_glyph(ch, h, rng, style):
    """(uint8 image, x0, x1, baseline row) of one glyph h px tall at the supersampled scale."""
    from PIL import Image, ImageDraw
    variants = SKELETONS[ch]
    adv, strokes = variants[rng.integers(len(variants))]
    wf = style["width"] * (1 + rng.normal(0, 0.06))
    hh = h * (1 + rng.normal(0, style["height_cv"]))
    if ch == "Ο":
        hh *= style["omicron"]
    slant = math.tan(math.radians(style["slant"] + rng.normal(0, 2.0)))
    rot = math.radians(rng.normal(0, style["rot_sd"]))
    pad = int(0.6 * h)
    W = int(adv * wf * hh + 2 * pad + 4)
    H = int(1.9 * h + 2 * pad)
    base = int(pad + 1.35 * h)
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    cx = adv * wf * hh / 2
    for st in strokes:
        pts = []
        for x, y in st:
            x = x * wf * hh
            yy = (y - 1.0) * hh                       # relative to the base line
            x = x + slant * (-yy)
            # rotate about the base centre
            xr, yr = x - cx, yy
            x2 = cx + xr * math.cos(rot) - yr * math.sin(rot)
            y2 = xr * math.sin(rot) + yr * math.cos(rot)
            ej = rng.normal(0, style["jitter"] * hh, 2)
            pts.append((pad + x2 + ej[0], base + y2 + ej[1]))
        if len(pts) > 2:  # smooth bend of the whole stroke
            e0, e1 = rng.normal(0, style["bend"] * hh, 2), rng.normal(0, style["bend"] * hh, 2)
            m = len(pts)
            pts = [(x + e0[0] * (1 - i / (m - 1)) + e1[0] * i / (m - 1), y + e0[1] * (1 - i / (m - 1)) + e1[1] * i / (m - 1))
                   for i, (x, y) in enumerate(pts)]
        _sweep(d, pts, style["nib_half"], style["thin"])
    a = np.asarray(img)
    cols = np.nonzero(a.max(axis=0) > 127)[0]
    if cols.size == 0:
        return a, 0, 1, base
    return a, int(cols[0]), int(cols[-1]) + 1, base


@lru_cache(maxsize=1)
def font_files():
    """Installed fonts that draw all 24 capitals (lunate sigma may be drawn as Latin C)."""
    roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
             Path("/System/Library/Fonts"), Path("/Library/Fonts")]
    out = []
    try:
        from PIL import ImageFont
    except ImportError:
        return ()
    for r in roots:
        if not r.exists():
            continue
        for p in sorted(r.rglob("*")):
            if p.suffix.lower() not in (".ttf", ".otf") or "mono" in p.name.lower() or "unifont" in p.name.lower():
                continue
            try:
                f = ImageFont.truetype(str(p), 48)
                ok = all(f.getmask(c).getbbox() for c in "ΑΒΓΔΘΛΞΠΣΦΨΩ")
                # a font without Greek often draws the same .notdef box for every letter
                ok = ok and f.getmask("Ψ").getbbox() != f.getmask("Ξ").getbbox()
            except Exception:
                ok = False
            if ok:
                out.append(str(p))
    return tuple(out)


@lru_cache(maxsize=1)
def font_families():
    """font_files() grouped by family (file name before the first '-'), so big families do not dominate."""
    fam = {}
    for p in font_files():
        fam.setdefault(Path(p).stem.split("-")[0].lower(), []).append(p)
    return tuple(tuple(v) for _, v in sorted(fam.items()))


@lru_cache(maxsize=256)
def _font(path, size):
    from PIL import ImageFont
    return ImageFont.truetype(path, size)


def render_font_glyph(ch, h, rng, style):
    """(uint8 image, x0, x1, baseline row) of one font glyph whose cap height is about h px."""
    from PIL import Image, ImageDraw
    path = style["font"]
    probe = _font(path, 100)
    cap = probe.getbbox("Η", anchor="ls")
    cap_h = max(1, -cap[1])
    size = max(8, int(round(100 * h / cap_h * (1 + rng.normal(0, style["height_cv"])))))
    f = _font(path, size)
    c = "C" if ch == "Ϲ" and not _has_glyph(path, "Ϲ") else ch
    pad = int(0.6 * h)
    bb = f.getbbox(c, anchor="ls")
    W = int(bb[2] - min(0, bb[0]) + 2 * pad + 2)
    H = int(1.9 * h + 2 * pad)
    base = int(pad + 1.35 * h)
    img = Image.new("L", (W, H), 0)
    ImageDraw.Draw(img).text((pad - min(0, bb[0]), base), c, font=f, fill=255, anchor="ls")
    a = np.asarray(img).astype(np.float32)
    # width and slant by an affine resample
    wf = style["width"] * (1 + rng.normal(0, 0.05))
    sl = math.tan(math.radians(style["slant"] + rng.normal(0, 2.0)))
    a = _affine_x(a, wf, sl, base)
    a = np.clip(a, 0, 255).astype(np.uint8)
    cols = np.nonzero(a.max(axis=0) > 127)[0]
    if cols.size == 0:
        return a, 0, 1, base
    return a, int(cols[0]), int(cols[-1]) + 1, base


@lru_cache(maxsize=64)
def _has_glyph(path, ch):
    f = _font(path, 48)
    return f.getmask(ch).getbbox() is not None and f.getmask(ch).getbbox() != f.getmask("￿").getbbox()


def _affine_x(a, wf, shear, base):
    """x' = wf * x + shear * (base - y): widen and slant about the base line (bilinear)."""
    H, W = a.shape
    W2 = int(math.ceil(W * wf + abs(shear) * H)) + 2
    yy, xx = np.mgrid[0:H, 0:W2].astype(np.float32)
    off = shear * (base - yy)
    shift = max(0.0, -float(off.min()))
    xs = (xx - off - shift) / wf
    x0 = np.floor(xs).astype(int)
    fx = xs - x0
    ok0 = (x0 >= 0) & (x0 < W)
    ok1 = (x0 + 1 >= 0) & (x0 + 1 < W)
    v0 = np.where(ok0, a[yy.astype(int), np.clip(x0, 0, W - 1)], 0)
    v1 = np.where(ok1, a[yy.astype(int), np.clip(x0 + 1, 0, W - 1)], 0)
    return v0 * (1 - fx) + v1 * fx


def random_style(rng, source=None):
    """A random writing style: glyph source, pen and spacing."""
    fonts = font_files()
    if source is None:
        source = "font" if fonts and rng.random() < 0.35 else "skeleton"
    if source == "font" and not fonts:
        source = "skeleton"
    st = {"source": source,
          "width": float(rng.uniform(0.82, 1.18)),
          "slant": float(rng.normal(2.0, 4.0)),
          "rot_sd": float(rng.uniform(0.0, 3.0)),
          "height_cv": float(rng.uniform(0.02, 0.09)),
          "omicron": float(rng.uniform(0.72, 1.0)),
          "jitter": float(rng.uniform(0.0, 0.025)),
          "bend": float(rng.uniform(0.0, 0.04)),
          "gap": float(rng.uniform(0.12, 0.5)),
          "gap_sd": float(rng.uniform(0.02, 0.12)),
          "baseline_sd": float(rng.uniform(0.0, 0.05)),
          "tilt_deg": float(rng.normal(0, 1.2))}
    if source == "font":
        fams = font_families()
        fam = fams[rng.integers(len(fams))]
        st["font"] = fam[rng.integers(len(fam))]
        st["weight"] = float(rng.uniform(-0.03, 0.08))     # dilation in letter heights
    else:
        thick = float(rng.uniform(0.09, 0.2))               # broad-nib width, letter heights
        thin = thick / float(rng.uniform(1.0, 2.2))
        ang = math.radians(rng.uniform(0, 180))
        st["nib_thick"], st["nib_thin"], st["pen_angle"] = thick, thin, ang
        st["weight"] = 0.0
    return st


def _scale_style(st, h):
    st = dict(st)
    if st["source"] == "skeleton":
        L = max(0.0, (st["nib_thick"] - st["nib_thin"]) * h)
        st["nib_half"] = (0.5 * L * math.cos(st["pen_angle"]), -0.5 * L * math.sin(st["pen_angle"]))
        st["thin"] = max(1.0, st["nib_thin"] * h)
    return st


def render_line(text, rng, style, h):
    """Supersampled line image (float32 0..1, ink high) with the letter centre line at row h * 1.25 + pad,
    plus per-letter (x0, x1) in that image and the centre row."""
    st = _scale_style(style, h)
    glyphs = []
    for ch in text:
        if st["source"] == "font":
            g = render_font_glyph(ch, h, rng, st)
        else:
            g = render_skeleton_glyph(ch, h, rng, st)
        glyphs.append(g)
    H = int(1.9 * h + 2 * int(0.6 * h))
    base_ref = int(0.6 * h) + int(1.35 * h)
    total = int(sum(g[2] - g[1] for g in glyphs) + len(glyphs) * (st["gap"] + 0.6) * h + 4 * h)
    out = np.zeros((H, max(total, int(8 * h))), np.float32)
    x = int(rng.uniform(0.3, 1.5) * h)
    boxes = []
    for ch, (a, x0, x1, base) in zip(text, glyphs):
        dy = int(round(rng.normal(0, st["baseline_sd"]) * h)) + (base_ref - base)
        w = x1 - x0
        if x + w + 2 >= out.shape[1]:
            out = np.pad(out, ((0, 0), (0, int(w + 4 * h))))
        y0 = max(0, dy)
        ys = slice(y0, min(H, a.shape[0] + dy))
        src = a[ys.start - dy:ys.stop - dy, x0:x1].astype(np.float32) / 255.0
        np.maximum(out[ys, x:x + w], src, out=out[ys, x:x + w])
        boxes.append((x, x + w))
        gap = max(0.03, rng.normal(st["gap"], st["gap_sd"])) * h
        x += w + int(round(gap))
    out = out[:, :x + int(rng.uniform(0.3, 1.5) * h)]
    if st.get("weight", 0) and st["source"] == "font":
        r = st["weight"] * h
        out = dilate(out, r) if r > 0 else erode(out, -r)
    if abs(st["tilt_deg"]) > 0.05:
        out = _tilt(out, st["tilt_deg"])
    centre = base_ref - 0.5 * h
    return out, boxes, centre


def _tilt(a, deg):
    t = math.tan(math.radians(deg))
    H, W = a.shape
    shift = np.round((np.arange(W) - W / 2) * t).astype(int)
    rows = np.arange(H)[:, None] - shift[None, :]
    ok = (rows >= 0) & (rows < H)
    out = np.zeros_like(a)
    cols = np.broadcast_to(np.arange(W)[None, :], (H, W))
    out[ok] = a[rows[ok], cols[ok]]
    return out


# ------------------------------------------------------------------ image ops (numpy only)

def gaussian(a, sigma):
    """Separable Gaussian blur, reflect padding."""
    if sigma <= 0.05:
        return a
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    p = np.pad(a, ((r, r), (0, 0)), mode="reflect")
    a = sum(k[i] * p[i:i + a.shape[0]] for i in range(2 * r + 1))
    p = np.pad(a, ((0, 0), (r, r)), mode="reflect")
    return sum(k[i] * p[:, i:i + a.shape[1]] for i in range(2 * r + 1))


def dilate(a, r):
    """Grey dilation by a disc of radius r px."""
    ri = int(math.floor(r))
    if ri < 1:
        return a
    out = a.copy()
    p = np.pad(a, ri)
    for dy in range(-ri, ri + 1):
        for dx in range(-ri, ri + 1):
            if dy * dy + dx * dx <= r * r:
                np.maximum(out, p[ri + dy:ri + dy + a.shape[0], ri + dx:ri + dx + a.shape[1]], out=out)
    return out


def erode(a, r):
    return 1.0 - dilate(1.0 - a, r)


def smooth_noise(shape, corr, rng):
    """Zero-mean unit-sd noise with correlation length corr px (anisotropic: corr=(cy, cx))."""
    cy, cx = (corr, corr) if np.isscalar(corr) else corr
    n = rng.standard_normal(shape).astype(np.float32)
    f = np.fft.rfft2(n)
    ky = np.fft.fftfreq(shape[0])[:, None]
    kx = np.fft.rfftfreq(shape[1])[None, :]
    f *= np.exp(-2 * (math.pi ** 2) * ((ky * cy) ** 2 + (kx * cx) ** 2))
    out = np.fft.irfft2(f, s=shape)
    sd = out.std()
    return (out / sd if sd > 0 else out).astype(np.float32)


def downsample(a, f):
    H, W = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    return a[:H, :W].reshape(H // f, f, W // f, f).mean(axis=(1, 3))


# ------------------------------------------------------------------ degradations

def to_mask_domain(clean, h, rng):
    """Hand-drawn label look: even-width strokes, binary, rough edges."""
    a = gaussian(clean, rng.uniform(0.01, 0.04) * h)
    a = a + 0.25 * smooth_noise(a.shape, 0.05 * h, rng) * rng.uniform(0, 1)
    m = (a > rng.uniform(0.35, 0.6)).astype(np.float32)
    r = rng.uniform(-0.01, 0.05) * h
    m = dilate(m, r) if r > 0 else (erode(m, -r) if r < -0.5 else m)
    return m


def to_map_domain(clean, h, rng, ghost=None):
    """Ink-model map look (values roughly 0..1, ink high)."""
    H, W = clean.shape
    ink = clean.copy()
    # crackle: multiplicative plates and cracks
    if rng.random() < 0.6:
        cr = smooth_noise((H, W), rng.uniform(0.04, 0.12) * h, rng)
        ink = ink * np.clip(1 + rng.uniform(0.1, 0.45) * cr, 0, 2)
        cracks = np.abs(smooth_noise((H, W), rng.uniform(0.05, 0.12) * h, rng)) < rng.uniform(0.0, 0.12)
        ink[cracks] *= rng.uniform(0.0, 0.5)
    # dropout patches
    if rng.random() < 0.8:
        d = smooth_noise((H, W), rng.uniform(0.08, 0.3) * h, rng)
        q = np.quantile(d, rng.uniform(0.0, 0.35))
        ink = ink * np.clip((d - q) / 0.6 + 0.5, 0, 1)
    # blur (the ink model's footprint)
    ink = gaussian(ink, rng.uniform(0.02, 0.14) * h)
    # saturating tone
    gain = rng.uniform(0.8, 5.0)
    p = (1 - np.exp(-gain * ink)) / (1 - math.exp(-gain))
    amp = rng.uniform(0.45, 1.0)
    p = amp * p
    # background: papyrus fibres (anisotropic), slow shading, false-ink speckle
    bg = np.zeros((H, W), np.float32)
    if rng.random() < 0.85:
        horiz = rng.random() < 0.5
        corr = (rng.uniform(0.02, 0.08) * h, rng.uniform(0.8, 4.0) * h)
        f = smooth_noise((H, W), corr if horiz else corr[::-1], rng)
        bg += rng.uniform(0.02, 0.12) * f
    bg += rng.uniform(0.0, 0.12) * smooth_noise((H, W), rng.uniform(1.0, 4.0) * h, rng)
    if rng.random() < 0.7:
        sp = smooth_noise((H, W), rng.uniform(0.04, 0.15) * h, rng)
        bg += np.clip(sp - rng.uniform(1.8, 3.2), 0, None) * rng.uniform(0.2, 0.8)
    if ghost is not None and rng.random() < 0.5:
        bg += rng.uniform(0.05, 0.3) * gaussian(ghost, rng.uniform(0.05, 0.2) * h)
    base = rng.uniform(0.0, 0.3)
    img = base + p + bg
    # contrast compression like a probability map squeezed into a band
    if rng.random() < 0.4:
        lo, hi = rng.uniform(0.15, 0.4), rng.uniform(0.6, 0.85)
        img = lo + (hi - lo) * np.clip(img, 0, 1.2) / 1.2
    img = img + rng.uniform(0.01, 0.06) * rng.standard_normal((H, W)).astype(np.float32)
    if rng.random() < 0.3:
        img = np.clip(img, 0, None) ** rng.uniform(0.6, 1.6)
    return img.astype(np.float32)


def normalize(a):
    """The reader's own normalisation: 0.5 and 99.8 percentiles to [0, 1], clipped."""
    lo, hi = np.percentile(a, [0.5, 99.8])
    if hi <= lo:
        return np.zeros_like(a, dtype=np.float32)
    return np.clip((a - lo) / (hi - lo), 0, 1).astype(np.float32)


# ------------------------------------------------------------------ text

def random_text(rng, n, lm=None):
    """n uniform random letters (lm=None) or a sample from a letter model with .sample(rng, n)."""
    if lm is not None:
        return lm.sample(rng, n)
    return "".join(ALPHABET[i] for i in rng.integers(0, len(ALPHABET), n))


# ------------------------------------------------------------------ one training sample

def band_height(h=H_PX):
    return int(round((BAND_TOP + BAND_BOT) * h))


def make_sample(rng, h=H_PX, domain=None, n_range=(3, 18), p_blank=0.07, lm=None, style=None):
    """One band: (float32 image band_height x W in [0, 1] after normalize, text, [(x0, x1)] per letter)."""
    hs = h * SS
    if domain is None:
        domain = "mask" if rng.random() < 0.2 else "map"
    style = style or random_style(rng)
    scale = rng.uniform(0.86, 1.18)              # letter size the reader must tolerate
    hl = hs * scale
    n = int(rng.integers(n_range[0], n_range[1] + 1))
    blank = rng.random() < p_blank
    text = "" if blank else random_text(rng, n, lm)
    if blank:
        line, _, centre = render_line(random_text(rng, n), rng, style, hl)
        line[:] = 0
        boxes = []
    else:
        line, boxes, centre = render_line(text, rng, style, hl)
    Hb = band_height(h) * SS
    W = line.shape[1]
    dyc = rng.normal(0, 0.12) * hs                 # line centre off the band centre
    top = int(round(centre - BAND_TOP * hs + dyc))
    band = np.zeros((Hb, W), np.float32)
    _paste(band, line, -top, 0)
    # neighbouring lines above and below
    pitch = rng.uniform(1.55, 2.4) * hs
    ghost = None
    for sgn in (-1, 1):
        if rng.random() < 0.85:
            st2 = style if rng.random() < 0.8 else random_style(rng)
            other, _, c2 = render_line(random_text(rng, int(n * 1.5) + 4), rng, st2, hl)
            dy = int(round(centre - top + sgn * pitch - c2))
            _paste(band, other, dy, int(rng.integers(-2 * hs, 2 * hs)))
    if domain == "map":
        g, _, cg = render_line(random_text(rng, n + 4), rng, style, hl)
        ghost = np.zeros_like(band)
        _paste(ghost, g, int(rng.uniform(-0.6, 0.6) * hs) - top, int(rng.uniform(-3, 3) * hs))
    if blank and rng.random() < 0.5:   # non-letter ink: cracks, fibre bundles, blobs
        band = np.maximum(band, _clutter(band.shape, hs, rng))
    if domain == "mask":
        img = to_mask_domain(band, hs, rng)
    else:
        img = to_map_domain(band, hs, rng, ghost)
    img = downsample(img, SS)
    img = normalize(img)
    boxes = [(x0 / SS, x1 / SS) for x0, x1 in boxes]
    return img, text, boxes


def _paste(dst, src, dy, dx):
    H, W = dst.shape
    h, w = src.shape
    y0, y1 = max(0, dy), min(H, dy + h)
    x0, x1 = max(0, dx), min(W, dx + w)
    if y1 > y0 and x1 > x0:
        np.maximum(dst[y0:y1, x0:x1], src[y0 - dy:y1 - dy, x0 - dx:x1 - dx], out=dst[y0:y1, x0:x1])


def _clutter(shape, h, rng):
    from PIL import Image, ImageDraw
    img = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(img)
    for _ in range(int(rng.integers(1, 6))):
        x0, y0 = rng.uniform(0, shape[1]), rng.uniform(0, shape[0])
        L = rng.uniform(0.3, 3.0) * h
        a = rng.uniform(0, math.pi)
        d.line([(x0, y0), (x0 + L * math.cos(a), y0 + L * math.sin(a))], fill=int(rng.uniform(120, 255)),
               width=max(1, int(rng.uniform(0.05, 0.25) * h)))
    for _ in range(int(rng.integers(0, 5))):
        x0, y0, r = rng.uniform(0, shape[1]), rng.uniform(0, shape[0]), rng.uniform(0.05, 0.4) * h
        d.ellipse([x0 - r, y0 - r * rng.uniform(0.4, 1.0), x0 + r, y0 + r], fill=int(rng.uniform(120, 255)))
    return np.asarray(img).astype(np.float32) / 255.0


# ------------------------------------------------------------------ whole pages (end-to-end tests)

def make_page(rng, n_lines=6, h=40.0, n_letters=(8, 16), domain="map", lm=None, pitch_ratio=None, tilt_deg=None,
              style=None):
    """A synthetic column: (float32 image, [line texts], [centre rows], letter height in px).

    One style per page, lines pitch_ratio * h apart, the whole page tilted by tilt_deg. For testing
    the full reader (scale estimate, deskew, line finding) rather than the band network alone."""
    style = style or random_style(rng)
    pitch_ratio = pitch_ratio or float(rng.uniform(1.6, 2.3))
    tilt = float(rng.normal(0, 1.5)) if tilt_deg is None else float(tilt_deg)
    hs = h * SS
    pitch = pitch_ratio * hs
    lines, rendered = [], []
    for _ in range(n_lines):
        t = random_text(rng, int(rng.integers(n_letters[0], n_letters[1] + 1)), lm)
        img, _, c = render_line(t, rng, style, hs)
        lines.append(t)
        rendered.append((img, c))
    W = max(r[0].shape[1] for r in rendered) + int(2 * hs)
    H = int(pitch * (n_lines + 1))
    page = np.zeros((H, W), np.float32)
    centres = []
    for i, (img, c) in enumerate(rendered):
        y = (i + 1) * pitch
        _paste(page, img, int(round(y - c)), int(rng.uniform(0.2, 1.0) * hs))
        centres.append(y / SS)
    if abs(tilt) > 0.05:
        page = _tilt(page, tilt)
    ghost = None
    if domain == "map":
        g, _, cg = render_line(random_text(rng, 40), rng, style, hs)
        ghost = np.zeros_like(page)
        _paste(ghost, g, int(rng.uniform(0.5, 1.5) * pitch - cg), int(rng.uniform(-2, 2) * hs))
    page = to_mask_domain(page, hs, rng) if domain == "mask" else to_map_domain(page, hs, rng, ghost)
    return downsample(page, SS).astype(np.float32), lines, centres, float(h)
