"""Learned Greek letter reader for 2D images of scroll text (ink maps, ink labels, photographs).

A small convolutional line reader, trained with CTC on synthetic lines
(scripts/letters/train_linenet.py), runs here in numpy with no torch. Each text line becomes
per-position letter probabilities, decoded into letters with boxes and confidences, with or
without a separate letter language model (kit/greeklm.py). Every string it returns is model
output: a hypothesis for a person to check, never a reading of a papyrus.

Controls travel with every result, and each can fail:
- nulls: the same reader on tile-shuffled and phase-randomised copies of the image. The
  confidence threshold is set so the nulls give few letters, and the result says how many
  letters the real image kept above it against each null;
- orientation: text the right way round should keep more letters as stored than mirrored or
  turned 180 degrees (weak for Greek capitals, many of which are symmetric);
- language off: the ink-only decode is always reported, and a language-model decode, when
  asked for, sits beside it and never replaces it.

Weights are a .npz exported by the training script (format linenet-v1, BatchNorm folded into
the convolutions). They are not in git.
"""

import json
import math
from pathlib import Path

import numpy as np

NOTE = ("Model output: letter hypotheses from a learned line reader, not a reading. "
        "A papyrologist decides what is legible.")
FORMAT = "linenet-v1"
# Line pitch over letter height for the body hand of PHerc. Paris 4 (6.6 mm over 3.5 mm),
# used only when the image gives no line pitch of its own.
PITCH_PER_H = 6.6 / 3.5


# ------------------------------------------------------------------ numpy network

class LineNet:
    """numpy inference of the exported CTC line reader."""

    def __init__(self, path):
        z = np.load(path, allow_pickle=False)
        self.meta = json.loads(str(z["meta"]))
        if self.meta.get("format") != FORMAT:
            raise ValueError(f"{path}: not a {FORMAT} weight file")
        self.w = {k: z[k].astype(np.float32) for k in z.files if k != "meta"}
        self.alphabet = self.meta["alphabet"]
        self.letter_px = int(self.meta["letter_px"])
        self.band = tuple(self.meta["band"])
        self.stride = int(self.meta["stride"])

    @property
    def band_rows(self):
        return int(round((self.band[0] + self.band[1]) * self.letter_px))

    def logits(self, band):
        """band: (H, W) float32 in [0, 1] -> (T, K) logits with T = ceil(W / stride)."""
        x = np.asarray(band, np.float32)[None]
        W0 = x.shape[2]
        Wp = int(math.ceil(W0 / self.stride) * self.stride)
        if Wp != W0:
            x = np.pad(x, ((0, 0), (0, 0), (0, Wp - W0)), constant_values=float(np.median(band)))
        for layer in self.meta["layers"]:
            op = layer["op"]
            w = self.w.get(f"w{layer.get('id')}")
            b = self.w.get(f"b{layer.get('id')}")
            if op == "conv2d":
                x = np.maximum(_conv2d(x, w, b, layer["pad"]), 0)
            elif op == "maxpool":
                ky, kx = layer["k"]
                C, H, W = x.shape
                x = x[:, :H // ky * ky, :W // kx * kx].reshape(C, H // ky, ky, W // kx, kx).max(axis=(2, 4))
            elif op == "collapse":
                x = np.maximum(_conv2d(x, w, b, 0), 0)[:, 0, :]
            elif op == "conv1d_res":
                x = x + np.maximum(_conv1d(x, w, b, layer["dilation"]), 0)
            elif op == "head":
                x = w[:, :, 0] @ x + b[:, None]
            else:
                raise ValueError(f"unknown layer op {op!r}")
        return x.T

    def log_probs(self, band):
        lg = self.logits(band)
        lg = lg - lg.max(axis=1, keepdims=True)
        return lg - np.log(np.exp(lg).sum(axis=1, keepdims=True))


def _conv2d(x, w, b, pad):
    """x: C x H x W, w: O x C x kh x kw -> O x H' x W' (stride 1)."""
    O, C, kh, kw = w.shape
    if pad:
        x = np.pad(x, ((0, 0), (pad, pad), (pad, pad)))
    x = np.ascontiguousarray(x)
    _, H, W = x.shape
    Ho, Wo = H - kh + 1, W - kw + 1
    s = x.strides
    cols = np.lib.stride_tricks.as_strided(x, (C, kh, kw, Ho, Wo), (s[0], s[1], s[2], s[1], s[2]))
    return np.tensordot(w, cols, axes=([1, 2, 3], [0, 1, 2])) + b[:, None, None]


def _conv1d(x, w, b, dilation):
    """x: C x T, w: O x C x k, same padding, dilated."""
    O, C, k = w.shape
    p = dilation * (k - 1) // 2
    xp = np.pad(x, ((0, 0), (p, p)))
    T = x.shape[1]
    out = np.zeros((O, T), np.float32)
    for j in range(k):
        out += w[:, :, j] @ xp[:, j * dilation:j * dilation + T]
    return out + b[:, None]


# ------------------------------------------------------------------ CTC decoding

def ctc_greedy(lp, alphabet, blank=0):
    """Best-path decode with per-letter confidence and frame span: [(letter, p, t0, t1)]."""
    best = lp.argmax(axis=1)
    out = []
    prev = blank
    for t, k in enumerate(best):
        if k != blank and k != prev:
            out.append([alphabet[k - 1], float(np.exp(lp[t, k])), t, t])
        elif k != blank and k == prev and out:
            out[-1][1] = max(out[-1][1], float(np.exp(lp[t, k])))
            out[-1][3] = t
        prev = k
    return [tuple(o) for o in out]


def ctc_beam(lp, alphabet, lm=None, lm_weight=0.0, beam=32, blank=0, insert_bonus=0.0, top_k=8):
    """CTC prefix beam search, optionally with shallow fusion of a letter language model.

    lm: any object with logp_next(prefix) -> log-probabilities over the alphabet, in order.
    Returns (best string, its log score)."""
    T, K = lp.shape
    beams = {"": (0.0, -np.inf)}               # prefix -> (log p ending in blank, ending in a letter)
    for t in range(T):
        nxt = {}
        top = np.argsort(-lp[t])[:top_k]
        for pre, (pb, pnb) in beams.items():
            tot = np.logaddexp(pb, pnb)
            b_, nb_ = nxt.get(pre, (-np.inf, -np.inf))
            nxt[pre] = (np.logaddexp(b_, tot + lp[t, blank]), nb_)
            lmlp = lm.logp_next(pre) if (lm is not None and lm_weight) else None
            for k in top:
                if k == blank:
                    continue
                c = alphabet[k - 1]
                if pre and pre[-1] == c:
                    b_, nb_ = nxt.get(pre, (-np.inf, -np.inf))
                    nxt[pre] = (b_, np.logaddexp(nb_, pnb + lp[t, k]))
                    src = pb
                else:
                    src = tot
                new = pre + c
                bonus = insert_bonus + (lm_weight * lmlp[k - 1] if lmlp is not None else 0.0)
                b_, nb_ = nxt.get(new, (-np.inf, -np.inf))
                nxt[new] = (b_, np.logaddexp(nb_, src + lp[t, k] + bonus))
        beams = dict(sorted(nxt.items(), key=lambda kv: -np.logaddexp(*kv[1]))[:beam])
    best = max(beams.items(), key=lambda kv: np.logaddexp(*kv[1]))
    return best[0], float(np.logaddexp(*best[1]))


def force_align(lp, text, alphabet, blank=0):
    """CTC forced alignment (Viterbi): the frames of each letter of a known text in one line's log-probs.

    Returns [(letter, t0, t1, mean p)] in text order, or None when the line has too few frames for
    the text. This turns a line-level transcription into letter positions without drawing boxes."""
    idx = [alphabet.index(c) + 1 for c in text]
    T = lp.shape[0]
    if not idx:
        return []
    ext = [blank]
    for k in idx:
        ext += [k, blank]
    S = len(ext)
    need = len(idx) + sum(1 for a, b in zip(idx, idx[1:]) if a == b)
    if T < need:
        return None
    ext = np.array(ext)
    em = lp[:, ext]                                   # T x S
    alpha = np.full((T, S), -np.inf)
    back = np.zeros((T, S), np.int8)                  # 0 stay, 1 from s-1, 2 from s-2
    alpha[0, 0] = em[0, 0]
    alpha[0, 1] = em[0, 1]
    skip = np.zeros(S, bool)
    skip[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])
    for t in range(1, T):
        a0 = alpha[t - 1]
        a1 = np.concatenate([[-np.inf], a0[:-1]])
        a2 = np.where(skip, np.concatenate([[-np.inf, -np.inf], a0[:-2]]), -np.inf)
        stack = np.stack([a0, a1, a2])
        back[t] = stack.argmax(axis=0)
        alpha[t] = stack.max(axis=0) + em[t]
    s = S - 1 if alpha[T - 1, S - 1] >= alpha[T - 1, S - 2] else S - 2
    if not np.isfinite(alpha[T - 1, s]):
        return None
    path = np.empty(T, int)
    for t in range(T - 1, -1, -1):
        path[t] = s
        s -= int(back[t, s])
    out = []
    for i, c in enumerate(text):
        frames = np.nonzero(path == 2 * i + 1)[0]
        out.append((c, int(frames[0]), int(frames[-1]), float(np.exp(lp[frames, idx[i]]).mean())))
    return out


def locate(query, text, top=3):
    """Where a short letter string best matches inside a long text, allowing edits (semi-global alignment).

    Returns up to top (start, end, edit distance) with end exclusive, best first, non-overlapping.
    Used to find which published line a read line belongs to before forced alignment."""
    if not query:
        return []
    t = np.frombuffer(text.encode("utf-32-le"), dtype=np.uint32)
    q = np.frombuffer(query.encode("utf-32-le"), dtype=np.uint32)
    n = len(t)
    ar = np.arange(n + 1)
    D = np.zeros(n + 1)                               # free start anywhere in the text
    for ch in q:
        sub = D[:-1] + (t != ch)
        E = np.concatenate([[D[0] + 1], np.minimum(D[1:] + 1, sub)])
        D = np.minimum.accumulate(E - ar) + ar       # horizontal moves cost 1 each
    found = []
    order = np.argsort(D[1:], kind="stable") + 1
    for end in order:
        if len(found) >= top:
            break
        if any(abs(int(end) - e) < len(query) for _, e, _ in found):
            continue
        d = int(D[end])
        start = _locate_start(q, t, int(end), d)
        found.append((start, int(end), d))
    return found


def _locate_start(q, t, end, d):
    """Start of the best match ending at end: align the reversed query to the reversed text before end."""
    lo = max(0, end - len(q) - d)
    seg = t[lo:end][::-1]
    rq = q[::-1]
    n = len(seg)
    ar = np.arange(n + 1)
    D = ar.astype(float)                              # anchored at end
    for ch in rq:
        sub = D[:-1] + (seg != ch)
        E = np.concatenate([[D[0] + 1], np.minimum(D[1:] + 1, sub)])
        D = np.minimum.accumulate(E - ar) + ar
    k = int(np.argmin(D))
    return end - k


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ------------------------------------------------------------------ image and page geometry

def load_image(path, key=None):
    """2D float array from .npy, .npz (first or named array), .tif/.tiff (tifffile) or .png/.jpg (Pillow)."""
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".npy":
        a = np.load(p, allow_pickle=False)
    elif suf == ".npz":
        z = np.load(p, allow_pickle=False)
        a = z[key or z.files[0]]
    elif suf in (".tif", ".tiff"):
        import tifffile
        a = tifffile.imread(str(p))
    else:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        a = np.asarray(Image.open(p).convert("F"))
    a = np.squeeze(np.asarray(a))
    if a.ndim == 3 and a.shape[-1] in (3, 4):
        a = a[..., :3].mean(axis=-1)
    if a.ndim != 2:
        raise ValueError(f"{path}: expected a 2D image, got shape {a.shape}")
    return a.astype(np.float32)


def normalize(a, polarity="bright"):
    """Robust 0..1 scaling with ink bright. polarity: bright (ink maps), dark (photographs) or auto."""
    a = np.asarray(a, dtype=np.float64)
    finite = np.isfinite(a)
    if not finite.any():
        raise ValueError("image has no finite values")
    a = np.where(finite, a, np.median(a[finite]))
    lo, med, hi = np.percentile(a, [0.5, 50, 99.8])
    if hi <= lo:
        return np.zeros_like(a, dtype=np.float32)
    if polarity == "auto":
        polarity = "dark" if (med - lo) > (hi - med) else "bright"
    a = np.clip((a - lo) / (hi - lo), 0, 1)
    return (1.0 - a if polarity == "dark" else a).astype(np.float32)


def resize(a, shape):
    """Area-average by an integer factor, then bilinear to the exact shape."""
    h, w = a.shape
    H, W = int(shape[0]), int(shape[1])
    if (H, W) == (h, w):
        return a.astype(np.float32, copy=True)
    if H < h and W < w:
        f = max(1, int(min(h / H, w / W)))
        if f > 1:
            hh, ww = (h // f) * f, (w // f) * f
            a = a[:hh, :ww].reshape(hh // f, f, ww // f, f).mean(axis=(1, 3))
            h, w = a.shape
    ys = np.clip((np.arange(H) + 0.5) * h / H - 0.5, 0, h - 1)
    xs = np.clip((np.arange(W) + 0.5) * w / W - 0.5, 0, w - 1)
    y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
    y1, x1 = np.minimum(y0 + 1, h - 1), np.minimum(x0 + 1, w - 1)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    top = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx
    bot = a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    return (top * (1 - fy) + bot * fy).astype(np.float32)


def _smooth1d(v, sigma):
    if sigma <= 0.3:
        return v
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(v, r, mode="reflect"), k, mode="valid")


def line_pitch(a, lo=8):
    """Line spacing in pixels from the first autocorrelation peak of the row profile, or None."""
    prof = a.mean(axis=1)
    prof = prof - prof.mean()
    n = len(prof)
    if n < 3 * lo or not prof.any():
        return None
    f = np.fft.rfft(prof, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    ac = ac / (ac[0] or 1)
    for k in range(lo, n // 2):
        if ac[k] > ac[k - 1] and ac[k] >= ac[k + 1] and ac[k] > 0.15:
            return k
    return None


def shear(a, deg):
    """Vertical shear: out[y, x] = a[y + (x - w/2) tan(deg), x]."""
    if not deg:
        return a
    h, w = a.shape
    shift = np.round((np.arange(w) - w / 2) * math.tan(math.radians(deg))).astype(int)
    rows = np.arange(h)[:, None] + shift[None, :]
    ok = (rows >= 0) & (rows < h)
    out = np.zeros_like(a)
    cols = np.broadcast_to(np.arange(w)[None, :], (h, w))
    out[ok] = a[rows[ok], cols[ok]]
    return out


def deskew(a, h, max_deg=6.0, step=0.5):
    """Shear angle that makes the row profile most peaked (lines level)."""
    best = (0.0, -1.0)
    for ang in np.arange(-max_deg, max_deg + 1e-9, step):
        prof = _smooth1d(shear(a, ang).mean(axis=1), 0.1 * h)
        v = float(prof.var())
        if v > best[1] + 1e-12:
            best = (float(ang), v)
    return best[0], shear(a, best[0])


def find_lines(a, h, pitch):
    """Centre rows of text lines: row-profile peaks at least 0.7 pitch apart."""
    prof = _smooth1d(a.mean(axis=1), 0.12 * h)
    base = np.percentile(prof, 30)
    top = prof.max()
    if top <= base:
        return []
    level = base + 0.25 * (top - base)
    cand = [y for y in range(1, len(prof) - 1) if prof[y] >= prof[y - 1] and prof[y] > prof[y + 1] and prof[y] > level]
    cand.sort(key=lambda y: -prof[y])
    keep = []
    for y in cand:
        if all(abs(y - k) >= 0.7 * pitch for k in keep):
            keep.append(y)
    return sorted(keep)


# ------------------------------------------------------------------ nulls

def null_images(a, h, n=4, seed=0):
    """Alternating tile-shuffle (letter-sized tiles, random flips) and phase-randomised copies.

    Both keep the image's grey levels; the first also keeps local texture and breaks letters
    and lines, the second keeps the power spectrum (so line spacing survives) and breaks shapes."""
    rng = np.random.default_rng(seed)
    out = []
    t = max(4, int(round(h)))
    H, W = (a.shape[0] // t) * t, (a.shape[1] // t) * t
    for k in range(n):
        if k % 2 == 0 and H and W:
            tiles = a[:H, :W].reshape(H // t, t, W // t, t).transpose(0, 2, 1, 3).reshape(-1, t, t).copy()
            rng.shuffle(tiles)
            for i in range(len(tiles)):
                if rng.random() < 0.5:
                    tiles[i] = tiles[i][:, ::-1]
                if rng.random() < 0.5:
                    tiles[i] = tiles[i][::-1]
            b = a.copy()
            b[:H, :W] = tiles.reshape(H // t, W // t, t, t).transpose(0, 2, 1, 3).reshape(H, W)
            out.append(("tile_shuffle", b))
        else:
            f = np.fft.rfft2(a - a.mean())
            ph = np.exp(1j * rng.uniform(0, 2 * np.pi, f.shape))
            b = np.fft.irfft2(np.abs(f) * ph, s=a.shape) + a.mean()
            order = np.argsort(b, axis=None)
            flat = np.empty(a.size)
            flat[order] = np.sort(a, axis=None)
            out.append(("phase", flat.reshape(a.shape).astype(np.float32)))
    return out


# ------------------------------------------------------------------ the reader

def read_bands(net, a, ys, h):
    """Per line: log-probs (T, K) from a band around centre row y of image a (letters h px tall)."""
    res = []
    for y in ys:
        lo = int(round(y - net.band[0] * h))
        rows = net.band_rows
        band = np.zeros((rows, a.shape[1]), np.float32)
        s0, s1 = max(0, lo), min(a.shape[0], lo + rows)
        if s1 > s0:
            band[s0 - lo:s1 - lo] = a[s0:s1]
        res.append(net.log_probs(band))
    return res


SCALE_STEPS = (0.5, 0.63, 0.8, 1.0, 1.25, 1.6)


def estimate_letter_px(a):
    """First guess of the letter height (px) of a normalised image, and how it was made.

    From the line pitch (row-profile autocorrelation) over PITCH_PER_H; without a pitch, a quarter
    of the image height. Octave errors (a pitch of two lines) are common, which is why analyze()
    searches scales around this guess."""
    f0 = max(1, int(max(a.shape) // 1500))
    small = resize(a, (a.shape[0] // f0, a.shape[1] // f0)) if f0 > 1 else a
    p = line_pitch(small, lo=6)
    if p:
        return p * f0 / PITCH_PER_H, "line pitch"
    return a.shape[0] / 4.0, "image height / 4"


def analyze(img, weights, *, letter_px=None, polarity="bright", nulls=4, seed=0, deskew_deg=6.0, lines=None,
            p_min=None, null_rate=0.05, lm=None, lm_weight=0.0, beam=32, scale_search=True):
    """Read every text line of a 2D image. Returns a JSON-able dict with letters, boxes, confidences and controls.

    letter_px: letter height in image pixels. When None it is estimated, and with scale_search the
    reader is run at SCALE_STEPS times the estimate (up to 8 lines, 2 nulls each) and the scale with
    the most confident letters above its own nulls is kept; the table is in the result.
    lines: centre rows of the lines in image pixels (found from the row profile when None).
    p_min: letters below this confidence are dropped ('·'); when None it is set from the nulls so
    they keep at most null_rate letters per letter-width of line, and never below 0.5."""
    net = weights if isinstance(weights, LineNet) else LineNet(weights)
    a0 = normalize(img, polarity)
    how, search = "given", None
    if letter_px is None:
        h0, how = estimate_letter_px(a0)
        letter_px = h0
        if scale_search:
            search = []
            for k in SCALE_STEPS:
                r = _analyze_at(a0, net, h0 * k, nulls=2, seed=seed, deskew_deg=deskew_deg, lines=lines, p_min=p_min,
                                null_rate=null_rate, max_lines=8)
                c = r["control"]
                search.append({"letter_px": round(h0 * k, 2), "letters_kept": c["letters_kept"],
                               "null_letters_kept": c["null_letters_kept"],
                               "margin": c["letters_kept"] - max(c["null_letters_kept"])})
            best = max(search, key=lambda t: (t["margin"], -abs(math.log(t["letter_px"] / h0))))
            letter_px = best["letter_px"]
            how += ", then scale search"
    res = _analyze_at(a0, net, letter_px, nulls=nulls, seed=seed, deskew_deg=deskew_deg, lines=lines, p_min=p_min,
                      null_rate=null_rate, lm=lm, lm_weight=lm_weight, beam=beam)
    res["input_shape"] = list(np.shape(img))
    res["letter_px_from"] = how
    res["letter_px_estimated"] = how != "given"
    if search is not None:
        res["scale_search"] = search
    return res


def _analyze_at(a0, net, letter_px, *, nulls, seed, deskew_deg, lines, p_min, null_rate, lm=None, lm_weight=0.0,
                beam=32, max_lines=None):
    h = float(net.letter_px)
    f = h / float(letter_px)
    a = resize(a0, (max(8, int(round(a0.shape[0] * f))), max(8, int(round(a0.shape[1] * f)))))
    angle, a = deskew(a, h, deskew_deg) if deskew_deg else (0.0, a)
    if lines is None:
        pitch = line_pitch(a, lo=int(0.9 * h)) or PITCH_PER_H * h
        ys = find_lines(a, h, min(pitch, 2.4 * h))
    else:
        ys = [float(y) * f for y in lines]
    if max_lines and len(ys) > max_lines:
        mid = len(ys) // 2
        ys = ys[max(0, mid - max_lines // 2):max(0, mid - max_lines // 2) + max_lines]
    lps = read_bands(net, a, ys, h)
    null_lps = [(kind, read_bands(net, b, ys, h)) for kind, b in null_images(a, h, nulls, seed)]
    width_letters = max(1.0, a.shape[1] / (1.15 * h)) * max(1, len(ys))
    null_conf = sorted((c for _, L in null_lps for lp in L for _, c, _, _ in ctc_greedy(lp, net.alphabet)), reverse=True)
    if p_min is None:
        allowed = int(null_rate * width_letters * max(1, len(null_lps)))
        p_min = float(null_conf[allowed]) if len(null_conf) > allowed else 0.0
        p_min = max(p_min, 0.5)
    out_lines = []
    for li, (y, lp) in enumerate(zip(ys, lps)):
        letters = []
        for ch, c, t0, t1 in ctc_greedy(lp, net.alphabet):
            x0 = (t0 * net.stride - 0.3 * h) / f
            x1 = ((t1 + 1) * net.stride + 0.3 * h) / f
            letters.append({"glyph": ch, "p": round(c, 3), "kept": c >= p_min,
                            "box": _unshear_box(x0, x1, (y - 0.5 * h) / f, (y + 0.5 * h) / f, angle, a.shape[1] / f)})
        row = {"line": li, "y": round(y / f, 1), "ink_only": "".join(l["glyph"] if l["kept"] else "·" for l in letters),
               "letters": letters, "n_kept": sum(l["kept"] for l in letters)}
        if lm is not None and lm_weight:
            row["with_lm"], _ = ctc_beam(lp, net.alphabet, lm, lm_weight, beam)
        out_lines.append(row)
    null_out = [{"kind": kind, "letters_kept": sum(1 for lp in L for _, c, _, _ in ctc_greedy(lp, net.alphabet) if c >= p_min)}
                for kind, L in null_lps]
    n_data = sum(r["n_kept"] for r in out_lines)
    n_null = [r["letters_kept"] for r in null_out]
    return {"note": NOTE, "engine": "linenet", "letter_px": round(float(letter_px), 2), "working_scale": round(f, 5),
            "deskew_deg": angle, "p_min": round(p_min, 3), "lines": out_lines,
            "control": {"letters_kept": n_data, "null_letters_kept": n_null, "nulls": null_out,
                        "verdict": verdict(n_data, n_null)}}


def verdict(n, null_n):
    if not null_n:
        return "no control run (nulls=0): nothing here can be trusted"
    m = max(null_n)
    if n > 3 * max(1, m):
        return "confident letters well above every null"
    if n > m:
        return "more confident letters than every null, but within a factor of three"
    return "confident letters NOT above the nulls: treat every letter here as noise"


def _unshear_box(x0, x1, y0, y1, angle, width):
    """Box [y0, y1, x0, x1] in input pixels, undoing the deskew shear at the box centre."""
    dy = (0.5 * (x0 + x1) - width / 2) * math.tan(math.radians(angle))
    return [round(y0 + dy, 1), round(y1 + dy, 1), round(x0, 1), round(x1, 1)]


def read(img, weights, *, orientation=True, **kw):
    """analyze() plus orientation evidence: confident letters as stored, mirrored and turned 180 degrees."""
    net = weights if isinstance(weights, LineNet) else LineNet(weights)
    res = analyze(img, net, **kw)
    if orientation:
        kw2 = dict(kw, nulls=0, p_min=res["p_min"], letter_px=res["letter_px"])
        kw2.pop("lines", None)
        ev = {"as_is": res["control"]["letters_kept"]}
        img = np.asarray(img)
        for name, b in (("mirrored", img[:, ::-1]), ("rot180", img[::-1, ::-1])):
            ev[name] = analyze(b, net, **kw2)["control"]["letters_kept"]
        res["orientation"] = {"letters_kept": ev, "best": max(ev, key=ev.get),
                              "note": "text the right way round should keep the most letters as_is"}
    return res


def text_summary(res):
    """Plain-text rendering of an analyze()/read() result."""
    out = [res["note"], f"letter height {res['letter_px']} px ({res['letter_px_from']}), "
           f"deskew {res['deskew_deg']} deg, confidence floor {res['p_min']}"]
    for r in res["lines"]:
        s = f"line {r['line']:>2} y={r['y']:>7}: {r['ink_only'] or '(none)'}"
        if "with_lm" in r:
            s += f"   | with LM: {r['with_lm']}"
        out.append(s)
    c = res["control"]
    out.append(f"control: {c['letters_kept']} letters kept vs nulls {c['null_letters_kept']}: {c['verdict']}")
    if "orientation" in res:
        out.append(f"orientation: {res['orientation']['letters_kept']} (best {res['orientation']['best']})")
    return "\n".join(out)
