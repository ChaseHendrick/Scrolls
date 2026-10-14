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
- control map (optional): a second image of the same surface, such as its reverse-depth ink map,
  read on the same lines at the same confidence floor;
- status: one code for the whole read and one per column (strong, weak, none, too_few or
  no_control; control_status), the ratio to the largest null, and per line the count expected by
  chance from the nulls, so a person or a pipeline can act on the controls;
- orientation: text the right way round should keep more letters as stored than mirrored or
  turned 180 degrees (weak for Greek capitals, many of which are symmetric);
- language off: the ink-only decode is always reported, and a language-model decode, when
  asked for, sits beside it and never replaces it.

Weights are a .npz exported by the training script (format linenet-v1, BatchNorm folded into
the convolutions). They are not in git: pass a file, or the name of a released model in
kit/data/letter-weights.json, which resolve_weights() downloads once and checks by SHA-256.

Big images: load_reduced() block-averages an image over MAX_PIXELS by an integer factor while
loading it in row bands (memory maps, zarr, or the stored integer type; never a float copy of the
whole image), so a whole native ink map can be read; analyze() and read() take that factor as
input_scale and report every row, column, box and letter height in input pixels.
"""

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

NOTE = ("Model output: letter hypotheses from a learned line reader, not a reading. "
        "A papyrologist decides what is legible.")
FORMAT = "linenet-v1"
WEIGHTS_REGISTRY = Path(__file__).parent / "data" / "letter-weights.json"
# Default line pitch in letter heights (6.6 / 3.5, about 1.89), used only when the image gives no
# line pitch of its own.
PITCH_PER_H = 6.6 / 3.5
DOWNLOAD_TIMEOUT = 120  # seconds without data before a weights download gives up
# Pixel budget. An image with more pixels than this is block-averaged while it loads (load_reduced):
# 64 Mpx is 256 MB as float32, and normalising it takes a few such copies, which fits a laptop.
MAX_PIXELS = 64_000_000
BAND_PIXELS = 64_000_000   # input pixels per band read while block-averaging (rounded up to whole tiles)
OVERLAY_MAX_SIDE = 4000
NO_LETTER_SIZE = ("no letter size: the image shows no regular line spacing to estimate it from. Give the letter "
                  "height with --letter-px H (image pixels), or with --letter-mm MM and --um-per-px UM (for "
                  "example --letter-mm 3.3 --um-per-px 38.4), or read a window that holds several lines with "
                  "--crop Y0 Y1 X0 X1")
# Controls. A read (or a column) needs at least MIN_LETTERS confident letters before its counts can
# pass, and more than STRONG_FACTOR times every control's count (the largest null, and the control
# map when one is read) to be "strong"; docs/letter-reader.md says why these values.
MIN_LETTERS = 10
STRONG_FACTOR = 3
STATUS_TEXT = {
    "strong": "Confident letters more than three times every control: worth a person's check, still model output "
              "and not a reading.",
    "weak": "Confident letters above every control, but not three times above all of them: weak evidence.",
    "none": "Confident letters NOT above the controls: treat every letter here as noise.",
    "too_few": "Too few confident letters to judge (fewer than {min_letters}).",
    "no_control": "No control run (nulls=0): nothing here can be trusted.",
}


# ------------------------------------------------------------------ released weights

def weights_cache():
    """Folder for downloaded weights: $KIT_LETTER_WEIGHTS, else ~/.cache/scrolls-kit/letters."""
    env = os.environ.get("KIT_LETTER_WEIGHTS")
    return Path(env) if env else Path.home() / ".cache" / "scrolls-kit" / "letters"


def released_weights(registry=None):
    """{name: entry} of released reader weights (file, sha256, url, licence, notes)."""
    data = json.loads(Path(registry or WEIGHTS_REGISTRY).read_text(encoding="utf-8"))
    return data["models"]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def resolve_weights(spec, cache=None, registry=None, download=True):
    """A weights file path from a path or a released model name.

    A name from kit/data/letter-weights.json is looked up in the cache folder and downloaded from its
    URL when missing; either way its SHA-256 must match the registry, so a damaged or swapped file is
    refused. An existing path is returned unchanged."""
    p = Path(spec)
    if p.exists():
        return p
    models = released_weights(registry)
    if spec not in models:
        raise ValueError(f"{spec}: no such file, and not a released model ({', '.join(sorted(models))})")
    m = models[spec]
    dest = Path(cache or weights_cache()) / m["file"]
    if not dest.exists():
        if not download:
            raise ValueError(f"{spec}: not in {dest.parent}")
        if not m.get("url"):
            raise ValueError(f"{spec}: no download address yet; see docs/letter-reader.md for where to get it")
        import tempfile
        import urllib.request
        dest.parent.mkdir(parents=True, exist_ok=True)
        # A file of this process's own, so two first runs never write one file, and no partial file is
        # left behind on any error; the timeout turns a stalled connection into an error.
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".part")
        tmp = Path(tmp)
        try:
            with os.fdopen(fd, "wb") as f, urllib.request.urlopen(m["url"], timeout=DOWNLOAD_TIMEOUT) as r:
                for block in iter(lambda: r.read(1 << 20), b""):
                    f.write(block)
            if _sha256(tmp) != m["sha256"]:
                raise ValueError(f"{spec}: download from {m['url']} does not match its SHA-256; nothing kept")
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
    if _sha256(dest) != m["sha256"]:
        raise ValueError(f"{spec}: {dest} does not match its SHA-256 {m['sha256']}; delete it and retry")
    return dest


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

RGB_MEAN = (1 / 3, 1 / 3, 1 / 3)        # colour TIFF and .npy: the plain mean of the first three channels
RGB_LUMA = (0.299, 0.587, 0.114)        # colour PNG and JPEG: Pillow's grey ("F") conversion


class _Source:
    """A 2D image (or a 2D colour image) read window by window in its stored type.

    arr is anything with .shape and numpy slicing: an array, a memory map or a zarr array. Size-1
    axes are dropped as np.squeeze would, without reading the data; chunk_rows is the height of the
    source's tiles or chunks, when it has them."""

    def __init__(self, arr, name, weights=RGB_MEAN, chunk_rows=None, store=None):
        self.arr, self.name, self.weights, self.chunk_rows, self.store = arr, name, weights, chunk_rows, store
        self.full = tuple(int(n) for n in arr.shape)
        kept = tuple(n for n in self.full if n != 1)
        self.rgb = len(kept) == 3 and kept[-1] in (3, 4)
        if len(kept) != 2 and not self.rgb:
            raise ValueError(f"{name}: expected a 2D image, got shape {kept}")
        self.shape = kept[:2]

    def read(self, y0, y1, x0, x1):
        """Rows y0:y1 and columns x0:x1 as a numpy array in the stored type: (h, w), or (h, w, c) in colour."""
        sl = [slice(y0, y1), slice(x0, x1), slice(None)]
        return np.asarray(self.arr[tuple(0 if n == 1 else sl.pop(0) for n in self.full)])

    def as_float(self, y0, y1, x0, x1):
        """The window as float32 grey, exactly as load_image has always converted it."""
        a = self.read(y0, y1, x0, x1)
        if a.ndim == 3:
            a = a[..., :3].mean(axis=-1)
        return a.astype(np.float32)

    def close(self):
        """Close the file a TIFF's zarr view keeps open."""
        if self.store is not None and hasattr(self.store, "close"):
            self.store.close()


def _is_zarr(p):
    p = Path(p)
    return p.suffix.lower() == ".zarr" or (p.is_dir() and any((p / n).exists() for n in (".zarray", ".zgroup", "zarr.json")))


def _ome_level0(attrs):
    """Path of an OME-Zarr group's full-resolution level (its first dataset), or None."""
    try:
        ms = attrs.get("multiscales") or (attrs.get("ome") or {}).get("multiscales")
        return str(ms[0]["datasets"][0]["path"]) if ms else None
    except (AttributeError, IndexError, KeyError, TypeError):
        return None


def _zarr_array(store, key, name, strict_key=True):
    """The zarr array at `key` (an array path, or an OME-Zarr level such as "0") of a store or path.

    Without a key: the array itself, an OME-Zarr group's full-resolution level, or a group's only array."""
    try:
        import zarr
    except ImportError as exc:
        raise ImportError(f"{name}: reading zarr needs the zarr package (python -m pip install zarr)") from exc
    z = zarr.open(store, mode="r")
    if not isinstance(z, zarr.Group):
        if key and strict_key:
            raise ValueError(f"{name}: a single zarr array, so --key {key} does not apply")
        return z
    names = sorted(z.array_keys())
    if not key:
        key = _ome_level0(z.attrs) or (names[0] if len(names) == 1 else None)
        if key is None:
            raise ValueError(f"{name}: a zarr group with arrays {names or 'none'}; pick one with --key "
                             "(an array path, or an OME-Zarr level such as 0)")
    try:
        arr = z[key]
    except KeyError:
        raise ValueError(f"{name}: no array {key!r} in this zarr (arrays: {', '.join(names) or 'none'})") from None
    if isinstance(arr, zarr.Group):
        raise ValueError(f"{name}: {key!r} is a zarr group, not an array; give its level, such as {key}/0")
    return arr


def _chunk_rows(arr):
    chunks = getattr(arr, "chunks", None)
    try:
        return int(chunks[-2]) if chunks and len(chunks) >= 2 else None
    except (TypeError, ValueError):
        return None


def _open(path, key=None, whole=False):
    """A _Source for an image file or zarr; whole=True when every pixel will be read at full resolution.

    Windows and bands are read without decoding the rest where the format allows: .npy and
    uncompressed TIFF by memory map, zarr (and OME-Zarr levels) by chunk, compressed tiled TIFF
    through tifffile's zarr view when zarr is installed. A compressed TIFF without zarr, a .npz and
    a PNG or JPEG are decoded whole, in their stored type."""
    p = Path(path)
    if _is_zarr(p):
        if not p.exists():
            raise FileNotFoundError(f"{p}: no such file or folder")
        arr = _zarr_array(str(p), key, p)
        return _Source(arr, p, chunk_rows=_chunk_rows(arr))
    suf = p.suffix.lower()
    if suf == ".npy":
        return _Source(np.load(p, allow_pickle=False, mmap_mode="r"), p)
    if suf == ".npz":
        z = np.load(p, allow_pickle=False)
        return _Source(z[key or z.files[0]], p)
    if suf in (".tif", ".tiff"):
        import tifffile
        if whole:
            return _Source(tifffile.imread(str(p)), p)
        try:
            return _Source(tifffile.memmap(str(p), mode="r"), p)
        except ValueError:  # a compressed TIFF cannot be memory-mapped
            pass
        try:
            import zarr  # noqa: F401
        except ImportError:
            return _Source(tifffile.imread(str(p)), p)
        store = tifffile.imread(str(p), aszarr=True)
        try:
            arr = _zarr_array(store, key, p, strict_key=False)
        except BaseException:
            store.close()
            raise
        return _Source(arr, p, chunk_rows=_chunk_rows(arr), store=store)
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(p)
    if whole:
        return _Source(np.asarray(im.convert("F")), p)
    if im.mode in ("1", "LA"):
        im = im.convert("L")
    elif im.mode not in ("L", "I", "F") and not im.mode.startswith("I;16"):
        im = im.convert("RGB")
    return _Source(np.asarray(im), p, weights=RGB_LUMA)


def _is_pillow(p):
    return not _is_zarr(p) and Path(p).suffix.lower() not in (".npy", ".npz", ".tif", ".tiff")


def _window(crop, shape, name):
    """(y0, y1, x0, x1) of a crop inside an image of this shape, with numpy's slicing rules."""
    H, W = shape
    if not crop:
        return 0, H, 0, W
    y0, y1, x0, x1 = crop
    ys, xs = range(H)[slice(y0, y1)], range(W)[slice(x0, x1)]
    if not len(ys) or not len(xs):
        raise ValueError(f"{name}: crop {list(crop)} is empty for an image of shape {tuple(shape)}")
    return ys.start, ys.stop, xs.start, xs.stop


def load_image(path, key=None, crop=None):
    """2D float array from .npy, .npz (first or named array), .tif/.tiff (tifffile), .png/.jpg (Pillow) or zarr.

    crop: (Y0, Y1, X0, X1), applied before the conversion to float; a .npy file and an uncompressed
    TIFF are memory-mapped, and a zarr or (with zarr installed) a compressed tiled TIFF is read by
    chunk, so only the window is read. zarr: key is the array path, or the OME-Zarr level ("0" is
    full resolution, the default)."""
    src = _open(path, key, whole=not crop or _is_pillow(path))    # Pillow images: always its grey ("F") conversion
    try:
        return src.as_float(*_window(crop, src.shape, path))
    finally:
        src.close()


def reduce_factor(shape, letter_px=None, net_letter_px=16, max_pixels=MAX_PIXELS):
    """Integer block size for reading an image of this shape: 1 within the pixel budget.

    Over the budget with a known letter height: the largest factor that keeps letters at least
    twice the network's working letter height (net_letter_px), so the reader's own resize still
    averages several pixels into each of its pixels; with small letters that can leave the image
    over the budget. Over the budget with no letter height: the smallest factor that fits it."""
    n = int(shape[0]) * int(shape[1])
    if n <= max_pixels:
        return 1
    if letter_px:
        return max(1, int(float(letter_px) // (2 * net_letter_px)))
    return max(1, math.ceil(math.sqrt(n / max_pixels)))


def _block_mean(src, y0, y1, x0, x1, k, progress=None, band_pixels=BAND_PIXELS):
    """Block mean by k of src's window, float32, read in row bands (rows left over from the last block are dropped).

    Bands follow the source's tiles, so each tile is decoded once; the rows of a band that do not
    fill a block are carried into the next band."""
    ny, nx = (y1 - y0) // k, (x1 - x0) // k
    out = np.empty((ny, nx), np.float32)
    yend, xend = y0 + ny * k, x0 + nx * k
    rows = max(k, band_pixels // (8 if src.rgb else 1) // max(1, xend - x0))   # colour is summed in float64
    if src.chunk_rows:
        rows = max(1, -(-rows // src.chunk_rows)) * src.chunk_rows
    done, carry, r, tick = 0, None, y0, y0
    while r < yend:
        r1 = min(yend, (r // rows + 1) * rows)
        part = src.read(r, r1, x0, xend)
        if src.rgb:
            part = sum(part[..., c].astype(np.float64) * w for c, w in enumerate(src.weights))
        if carry is not None:
            part = np.concatenate([carry, part])
        n = part.shape[0] // k
        if n:
            out[done:done + n] = _blocks(part[:n * k], k, nx)
            done += n
        carry = part[n * k:].copy()
        r = r1
        if progress and (r - tick >= 0.1 * (yend - y0) or r >= yend):
            tick = r
            progress(f"block-averaging: rows {r - y0} of {y1 - y0}")
    return out


def _blocks(part, k, nx, piece_bytes=64 << 20):
    """Block means by k of a band k * n rows tall and k * nx columns wide, summed in float64 a few rows at a time."""
    n = part.shape[0] // k
    out = np.empty((n, nx), np.float32)
    step = max(1, piece_bytes // (8 * k * nx * k))
    for i in range(0, n, step):
        piece = part[i * k:(i + step) * k]
        s = piece.reshape(-1, k, nx, k).sum(axis=3, dtype=np.float64).sum(axis=1)
        out[i:i + step] = s / (k * k)
    return out


def load_reduced(path, key=None, crop=None, letter_px=None, net_letter_px=16, max_pixels=MAX_PIXELS, progress=None):
    """An image for reading, block-averaged while it loads when it is over the pixel budget.

    Returns (image, k, shape): the float32 image, the integer block size k (reduce_factor; 1 when
    the image fits the budget, and then the image is exactly load_image's) and the (H, W) of the
    input window in input pixels. Pass k to analyze() or read() as input_scale, with letter_px and
    lines in input pixels; they report rows, columns, boxes and letter heights in input pixels.
    The crop is applied in input pixels, before the reduction, so boxes stay relative to Y0, X0."""
    p = Path(path)
    if _is_pillow(p):          # Pillow reads the size without decoding; the pixels are decoded once, below
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(p) as im:
            shape, src = (im.height, im.width), None
    else:
        src = _open(p, key)
        shape = src.shape
    try:
        y0, y1, x0, x1 = _window(crop, shape, path)
        h, w = y1 - y0, x1 - x0
        k = min(reduce_factor((h, w), letter_px, net_letter_px, max_pixels), h, w)
        if k == 1:
            if progress and h * w > max_pixels:
                progress(f"{p.name}: {h} x {w} px is over the {max_pixels / 1e6:g} Mpx budget, but its letters are "
                         "too small to block-average; loading it whole")
            img = load_image(p, key, crop) if src is None else src.as_float(y0, y1, x0, x1)
            return img, 1, (h, w)
        if progress:
            why = (f"letters {float(letter_px) / k:.1f} px tall after it" if letter_px else
                   f"letter size unknown, so only enough to fit the budget; if letters are under "
                   f"{2 * net_letter_px * k} px tall in the input, give their size")
            progress(f"{p.name}: {h} x {w} px is over the {max_pixels / 1e6:g} Mpx budget: block-averaging by {k} "
                     f"while loading ({why})")
        if src is None:
            src = _open(p, key)
        return _block_mean(src, y0, y1, x0, x1, k, progress), k, (h, w)
    finally:
        if src is not None:
            src.close()


def normalize(a, polarity="bright", dtype=np.float64):
    """Robust 0..1 scaling with ink bright. polarity: bright (ink maps), dark (photographs) or auto.

    dtype is the arithmetic precision; the result is always float32. normalize_for_reading uses
    float32 arithmetic for images over the pixel budget, to halve the memory."""
    a = np.asarray(a, dtype=dtype)
    finite = np.isfinite(a)
    if not finite.any():
        raise ValueError("image has no finite values")
    a = np.where(finite, a, np.median(a[finite]))
    lo, med, hi = np.percentile(a, [0.5, 50, 99.8])
    if hi <= lo:  # sparse binary or quantised image, such as an ink label with under 0.2% ink
        lo, hi = float(a.min()), float(a.max())
        if hi <= lo:
            return np.zeros_like(a, dtype=np.float32)
    if polarity == "auto":
        polarity = "dark" if (med - lo) > (hi - med) else "bright"
    a = np.clip((a - lo) / (hi - lo), 0, 1)
    return (1.0 - a if polarity == "dark" else a).astype(np.float32)


def normalize_for_reading(a, polarity="bright", max_pixels=MAX_PIXELS):
    """normalize() once for a whole read: float64 arithmetic within the pixel budget (as analyze() does), float32 above it.

    read() and the command line normalise once and hand the result to the main read, its nulls, the
    orientation reads and the overlay (each with normalized=True)."""
    return normalize(a, polarity, dtype=np.float64 if np.size(a) <= max_pixels else np.float32)


def letter_px_from_units(letter_mm, um_per_px):
    """Letter height in image pixels from a letter height in millimetres and the pixel size in micrometres."""
    if letter_mm is None or um_per_px is None:
        raise ValueError("give the letter height in millimetres and the pixel size in micrometres together "
                         "(--letter-mm MM --um-per-px UM)")
    if not (letter_mm > 0 and um_per_px > 0):
        raise ValueError(f"letter height ({letter_mm} mm) and pixel size ({um_per_px} um) must both be positive")
    return float(letter_mm) * 1000.0 / float(um_per_px)


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



def find_columns(a, h, min_gap=2.0, n=None, level=0.05, min_width=3.0):
    """Spans (x0, x1) of the text columns of image a (letters h px tall), left to right.

    A gutter is a run of image columns, touching neither edge, whose ink (the mean over the full
    height, smoothed over a quarter letter) stays below `level` of the way from the background to
    the median inked column, so it is close to empty in every row: the ragged ends of lines in one
    column do not make a gutter. With n, the n - 1 widest gutters split the image (a known number
    of columns); otherwise every gutter at least min_gap letter heights wide does. Spans meet in
    the middle of each gutter, and none is narrower than min_width letter heights: gutters are
    taken widest first, and one whose cut would leave a narrower piece is dropped (the piece stays
    with its neighbour). One span when there is no gutter, so a single column reads exactly as it
    did before columns were looked for."""
    w = a.shape[1]
    if (n is not None and n <= 1) or w < 2 * min_width * h:
        return [(0, w)]
    prof = _smooth1d(np.asarray(a, np.float64).mean(axis=0), 0.25 * h)
    base, top = float(np.percentile(prof, 5)), float(prof.max())
    if top <= base:
        return [(0, w)]
    ref = float(np.median(prof[prof > base + 0.05 * (top - base)]))
    low = prof < base + level * (ref - base)
    gaps, x = [], 0
    while x < w:
        if low[x]:
            r = x
            while r < w and low[r]:
                r += 1
            if x > 0 and r < w:
                gaps.append((r - x, x, r))
            x = r
        else:
            x += 1
    gaps = sorted(gaps, reverse=True)[:n - 1] if n is not None else [g for g in gaps if g[0] >= min_gap * h]
    edges = [0, w]
    for _, x, r in sorted(gaps, reverse=True):
        c = (x + r) // 2
        if all(abs(c - e) >= min_width * h for e in edges):
            edges.append(c)
    edges = sorted(edges)
    return list(zip(edges[:-1], edges[1:]))

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
            p_min=None, null_rate=0.05, lm=None, lm_weight=0.0, beam=32, scale_search=True, columns="auto",
            normalized=False, input_scale=1, letter_px_fallback=True, progress=None, control=None,
            min_letters=MIN_LETTERS):
    """Read every text line of a 2D image. Returns a JSON-able dict with letters, boxes, confidences and controls.

    letter_px: letter height in image pixels. When None it is estimated, and with scale_search the
    reader is run at SCALE_STEPS times the estimate (up to 8 lines, at least one per column, 2 nulls
    each) and the scale with the most confident letters above its own nulls is kept; the table is in
    the result. Without a line pitch the estimate is a quarter of the image height; with
    letter_px_fallback=False that raises ValueError(NO_LETTER_SIZE) instead (the command line does).
    lines: centre rows of the lines in image pixels (found from the row profile when None).
    columns: "auto" splits the image at empty vertical gutters (find_columns) and finds lines in each
    column, so a line never runs across two columns; an integer asks for that many columns (a known
    layout); "off" (or 1) reads the whole width as one column. Lines come out column by column, left
    to right. Given `lines` always means one column.
    p_min: letters below this confidence are dropped ('·'); when None it is set from the nulls so
    they keep at most null_rate letters per letter-width of line, and never below 0.5.
    normalized: img is already normalize()d (read() and the command line normalise once).
    input_scale: img was block-averaged by this integer from the input (load_reduced); letter_px and
    lines are then in input pixels, and so are every row, column, box and letter height returned.
    progress: optional callable taking a short message, for long reads.
    control: a second image of the same shape (the reverse-depth map of the same surface, say),
    normalised like img; it is read on the image's own columns, deskew and lines at the same letter
    size and confidence floor, and its kept letters go into the status (control_status).
    min_letters: the fewest kept letters a read or a column needs before its counts can pass."""
    net = weights if isinstance(weights, LineNet) else LineNet(weights)
    a0 = np.asarray(img, dtype=np.float32) if normalized else normalize(img, polarity)
    c0 = None
    if control is not None:
        if np.shape(control) != np.shape(img):
            raise ValueError(f"the control image is {' x '.join(map(str, np.shape(control)))} px but the image is "
                             f"{' x '.join(map(str, np.shape(img)))}; give a map of the same surface on the same grid "
                             "(such as its reverse-depth map), cropped the same way")
        c0 = np.asarray(control, dtype=np.float32) if normalized else normalize(control, polarity)
    k_in = input_scale
    if k_in != 1:
        letter_px = None if letter_px is None else float(letter_px) / k_in
        lines = None if lines is None else [float(y) / k_in for y in lines]
    how, search, h0 = "given", None, None
    if letter_px is None:
        h0, how = estimate_letter_px(a0)
        if how != "line pitch" and not letter_px_fallback:
            raise ValueError(NO_LETTER_SIZE)
        letter_px = h0
        if scale_search:
            search = []
            for i, k in enumerate(SCALE_STEPS):
                if progress:
                    progress(f"scale search {i + 1}/{len(SCALE_STEPS)}: letter height {h0 * k * k_in:.1f} px")
                r = _analyze_at(a0, net, h0 * k, nulls=2, seed=seed, deskew_deg=deskew_deg, lines=lines, p_min=p_min,
                                null_rate=null_rate, max_lines=8, columns=columns)
                c = r["control"]
                search.append({"letter_px": round(h0 * k * k_in, 2), "letters_kept": c["letters_kept"],
                               "null_letters_kept": c["null_letters_kept"],
                               "margin": c["letters_kept"] - max(c["null_letters_kept"])})
            best = max(search, key=lambda t: (t["margin"], -abs(math.log(t["letter_px"] / (h0 * k_in)))))
            letter_px = best["letter_px"] / k_in if k_in != 1 else best["letter_px"]
            how += ", then scale search"
    if progress:
        progress(f"reading at letter height {letter_px * k_in:.1f} px, with {nulls} null copies"
                 + (" and the control image on the same lines" if c0 is not None else ""))
    res = _analyze_at(a0, net, letter_px, nulls=nulls, seed=seed, deskew_deg=deskew_deg, lines=lines, p_min=p_min,
                      null_rate=null_rate, lm=lm, lm_weight=lm_weight, beam=beam, columns=columns, scale_out=k_in,
                      control=c0, min_letters=min_letters)
    res["input_shape"] = list(np.shape(img)) if k_in == 1 else [n * k_in for n in np.shape(img)]
    res["input_scale"] = k_in
    if k_in != 1:
        res["reduced_shape"] = list(np.shape(img))
    res["letter_px_from"] = how
    res["letter_px_estimated"] = how != "given"
    if h0 is not None:
        res["letter_px_first_guess"] = round(h0 * k_in, 2)
    if search is not None:
        res["scale_search"] = search
    return res


def _analyze_at(a0, net, letter_px, *, nulls, seed, deskew_deg, lines, p_min, null_rate, lm=None, lm_weight=0.0,
                beam=32, max_lines=None, columns="auto", scale_out=1, control=None, min_letters=MIN_LETTERS):
    """One read at one letter height of a normalised image; scale_out multiplies every row, column and box on the way out.

    control: a normalised image of a0's shape, read on a0's columns, deskew and lines at the same floor."""
    h = float(net.letter_px)
    f = h / float(letter_px)
    so = scale_out
    a = resize(a0, (max(8, int(round(a0.shape[0] * f))), max(8, int(round(a0.shape[1] * f)))))
    if lines is not None or columns in (None, "off", 1, "1"):
        spans = [(0, a.shape[1])]
    else:
        spans = find_columns(a, h, n=None if columns == "auto" else int(columns))
    blocks = []                       # per column: x offset, deskew angle, deskewed image, line centres
    for x0, x1 in spans:
        angle, sub = deskew(a[:, x0:x1], h, deskew_deg) if deskew_deg else (0.0, a[:, x0:x1])
        if lines is None:
            pitch = line_pitch(sub, lo=int(0.9 * h)) or PITCH_PER_H * h
            ys = find_lines(sub, h, min(pitch, 2.4 * h))
        else:
            ys = [float(y) * f for y in lines]
        if max_lines:
            per = max(1, max_lines // len(spans))
            if len(ys) > per:
                mid = len(ys) // 2
                ys = ys[max(0, mid - per // 2):max(0, mid - per // 2) + per]
        blocks.append((x0, x1, angle, sub, ys))
    lps = [read_bands(net, sub, ys, h) for _, _, _, sub, ys in blocks]
    # Nulls are made column by column, like the data, and pooled by kind (one block: as before).
    per_block = [null_images(sub, h, nulls, seed + bi) for bi, (_, _, _, sub, _) in enumerate(blocks)]
    widest = max(range(len(blocks)), key=lambda bi: blocks[bi][1] - blocks[bi][0])
    # null_dec[k][bi]: best-path decodes of null k on column bi's lines
    null_dec = [[[ctc_greedy(lp, net.alphabet) for lp in read_bands(net, nb[k][1], ys, h)]
                 for (_, _, _, _, ys), nb in zip(blocks, per_block)] for k in range(nulls)]
    width_letters = sum(max(1.0, sub.shape[1] / (1.15 * h)) * max(1, len(ys)) for _, _, _, sub, ys in blocks)
    null_conf = sorted((c for D in null_dec for col in D for dec in col for _, c, _, _ in dec), reverse=True)
    if p_min is None:
        allowed = int(null_rate * width_letters * max(1, nulls))
        p_min = float(null_conf[allowed]) if len(null_conf) > allowed else 0.0
        p_min = max(p_min, 0.5)

    def n_kept(decs):
        return sum(1 for dec in decs for _, c, _, _ in dec if c >= p_min)

    null_col = [[n_kept(null_dec[k][bi]) for k in range(nulls)] for bi in range(len(blocks))]   # per column, per null
    ctrl_lines = None                 # per column, per line: the control image's kept letters
    if control is not None:
        cr = resize(control, a.shape)
        ctrl_lines = [[n_kept([ctc_greedy(lp, net.alphabet)]) for lp in read_bands(net, shear(cr[:, x0:x1], angle), ys, h)]
                      for x0, x1, angle, _, ys in blocks]
    out_lines = []
    for ci, ((x0, _, angle, sub, ys), L) in enumerate(zip(blocks, lps)):
        # The nulls scramble positions across the whole column, so their letters say nothing about which
        # line they came from: a line's chance count is the column's mean null count over its lines.
        chance = round(float(np.mean(null_col[ci])) / len(ys), 2) if nulls and ys else None
        for li, (y, lp) in enumerate(zip(ys, L)):
            letters = []
            for ch, c, t0, t1 in ctc_greedy(lp, net.alphabet):
                lx0 = (t0 * net.stride - 0.3 * h) / f * so
                lx1 = ((t1 + 1) * net.stride + 0.3 * h) / f * so
                box = _unshear_box(lx0, lx1, (y - 0.5 * h) / f * so, (y + 0.5 * h) / f * so, angle, sub.shape[1] / f * so)
                if x0:
                    box[2], box[3] = round(box[2] + x0 / f * so, 1), round(box[3] + x0 / f * so, 1)
                letters.append({"glyph": ch, "p": round(c, 3), "kept": c >= p_min, "box": box})
            row = {"line": len(out_lines), "column": ci, "y": round(y / f * so, 1),
                   "ink_only": "".join(l["glyph"] if l["kept"] else "·" for l in letters),
                   "letters": letters, "n_kept": sum(l["kept"] for l in letters), "chance": chance}
            if ctrl_lines is not None:
                row["control_map_kept"] = ctrl_lines[ci][li]
            if lm is not None and lm_weight:
                row["with_lm"], _ = ctc_beam(lp, net.alphabet, lm, lm_weight, beam)
            out_lines.append(row)
    n_data = sum(r["n_kept"] for r in out_lines)
    n_null = [sum(col[k] for col in null_col) for k in range(nulls)]
    null_out = [{"kind": per_block[widest][k][0], "letters_kept": n_null[k]} for k in range(nulls)]
    n_ctrl = None if ctrl_lines is None else sum(map(sum, ctrl_lines))
    columns_out = []
    for ci, (x0, x1, angle, _, ys) in enumerate(blocks):
        col = control_report(sum(r["n_kept"] for r in out_lines if r["column"] == ci), null_col[ci],
                             None if ctrl_lines is None else sum(ctrl_lines[ci]), min_letters)
        col["chance"] = round(float(np.mean(null_col[ci])), 2) if nulls else None
        columns_out.append({"x0": round(x0 / f * so, 1), "x1": round(x1 / f * so, 1), "deskew_deg": angle,
                            "lines": len(ys), "control": col})
    control_out = {"letters_kept": n_data, "null_letters_kept": n_null, "nulls": null_out,
                   "verdict": verdict(n_data, n_null)}
    control_out.update(control_report(n_data, n_null, n_ctrl, min_letters))
    return {"note": NOTE, "engine": "linenet", "letter_px": round(float(letter_px) * so, 2), "working_scale": round(f / so, 5),
            "deskew_deg": blocks[0][2], "p_min": round(p_min, 3), "lines": out_lines, "columns": columns_out,
            "control": control_out}


def verdict(n, null_n):
    if not null_n:
        return "no control run (nulls=0): nothing here can be trusted"
    m = max(null_n)
    if n > 3 * max(1, m):
        return "confident letters well above every null"
    if n > m:
        return "more confident letters than every null, but within a factor of three"
    return "confident letters NOT above the nulls: treat every letter here as noise"


def control_status(n, null_n, control_n=None, min_letters=MIN_LETTERS):
    """Status code of n kept letters against the nulls' counts and, when one was read, the control map's count.

    no_control: no nulls were run. none: n is not above the largest null, or not above the control
    map. too_few: above them, but fewer than min_letters letters, too few to judge. strong: more
    than STRONG_FACTOR times every control (a count of 0 counts as 1, as in verdict()). weak: the
    rest. Without a control map and with at least min_letters letters, none, weak and strong are
    verdict()'s three cases; verdict() itself is unchanged."""
    if not null_n:
        return "no_control"
    refs = [max(null_n)] + ([control_n] if control_n is not None else [])
    if any(n <= r for r in refs):
        return "none"
    if n < min_letters:
        return "too_few"
    if all(n > STRONG_FACTOR * max(1, r) for r in refs):
        return "strong"
    return "weak"


def control_report(n, null_n, control_n=None, min_letters=MIN_LETTERS):
    """The controls of one read or one column as JSON: counts, ratio to the largest null, status code and sentence.

    ratio is n / max(1, largest null), so a ratio over STRONG_FACTOR is verdict()'s "well above";
    control_map (when control_n is given) holds the control image's kept letters and n over them."""
    st = control_status(n, null_n, control_n, min_letters)
    out = {"letters_kept": n, "null_letters_kept": list(null_n), "min_letters": min_letters,
           "ratio": round(n / max(1, max(null_n)), 2) if null_n else None,
           "status": st, "status_text": STATUS_TEXT[st].format(min_letters=min_letters)}
    if control_n is not None:
        out["control_map"] = {"letters_kept": control_n, "ratio": round(n / max(1, control_n), 2)}
    return out


def status_line(c, sentence=True):
    """One line of text for a control block (res["control"], or a column's "control"): status, counts, sentence.

    For example: weak (122 letters kept; nulls 43, 33, 27, 28, ratio 2.84 to the largest). Confident
    letters above every control, but not three times above all of them: weak evidence."""
    bits = [f"{c['letters_kept']} letters kept"]
    if c["null_letters_kept"]:
        bits.append(f"nulls {', '.join(map(str, c['null_letters_kept']))}, ratio {c['ratio']:g} to the largest")
    if "control_map" in c:
        bits.append(f"control map {c['control_map']['letters_kept']}, ratio {c['control_map']['ratio']:g}")
    out = f"{c['status']} ({'; '.join(bits)})"
    return f"{out}. {c['status_text']}" if sentence else out


def _unshear_box(x0, x1, y0, y1, angle, width):
    """Box [y0, y1, x0, x1] in input pixels, undoing the deskew shear at the box centre."""
    dy = (0.5 * (x0 + x1) - width / 2) * math.tan(math.radians(angle))
    return [round(y0 + dy, 1), round(y1 + dy, 1), round(x0, 1), round(x1, 1)]


def letter_px_check(a0, letter_px, input_scale=1):
    """A given letter height against the line-pitch estimate of a normalised image, or None without a pitch.

    The estimate (estimate_letter_px) is often a factor of two off, when it takes the spacing of
    two lines for one, so only a difference over 2x carries a warning."""
    est, how = estimate_letter_px(a0)
    if how != "line pitch":
        return None
    est *= input_scale
    ratio = float(letter_px) / est
    out = {"line_pitch_estimate": round(est, 2), "ratio": round(ratio, 3)}
    if ratio > 2 or ratio < 0.5:
        out["warning"] = (f"the given letter height ({float(letter_px):g} px) is {ratio:.2f} times the line-pitch "
                          f"estimate ({est:.1f} px); check it (the estimate itself can be 2x off)")
    return out


def read(img, weights, *, orientation=True, normalized=False, progress=None, control=None, **kw):
    """analyze() plus orientation evidence: confident letters as stored, mirrored and turned 180 degrees.

    The image is normalised once (normalize_for_reading) and that one image serves the main read, its
    nulls and the orientation reads. When a letter height is given, it is checked against the
    line-pitch estimate (letter_px_check; a warning in the result when they differ by over 2x).
    control: a second image of the same shape, such as the reverse-depth map of the same surface,
    normalised on its own (or already normalised, with normalized=True); analyze() reads it on the
    image's lines at the same letter size and confidence floor, and the status counts it."""
    net = weights if isinstance(weights, LineNet) else LineNet(weights)
    polarity = kw.get("polarity", "bright")
    a0 = np.asarray(img, dtype=np.float32) if normalized else normalize_for_reading(img, polarity)
    c0 = None
    if control is not None:
        c0 = np.asarray(control, dtype=np.float32) if normalized else normalize_for_reading(control, polarity)
    res = analyze(a0, net, normalized=True, progress=progress, control=c0, **kw)
    if res["letter_px_from"] == "given":
        check = letter_px_check(a0, res["letter_px"], kw.get("input_scale", 1))
        if check is not None:
            res["letter_px_check"] = check
            if "warning" in check and progress:
                progress("warning: " + check["warning"])
    if orientation:
        # Only the ink-only letter count is used here, so the language model stays off.
        kw2 = dict(kw, nulls=0, p_min=res["p_min"], letter_px=res["letter_px"], lm=None, lm_weight=0.0)
        kw2.pop("lines", None)
        ev = {"as_is": res["control"]["letters_kept"]}
        for name, flip in (("mirrored", (slice(None), slice(None, None, -1))),
                           ("rot180", (slice(None, None, -1), slice(None, None, -1)))):
            if progress:
                progress(f"orientation read: {name}")
            # A contiguous copy, so the flipped read sees exactly the array normalising the flipped input gives.
            ev[name] = analyze(np.ascontiguousarray(a0[flip]), net, normalized=True, **kw2)["control"]["letters_kept"]
        res["orientation"] = {"letters_kept": ev, "best": max(ev, key=ev.get),
                              "note": "text the right way round should keep the most letters as_is"}
    return res


def text_summary(res):
    """Plain-text rendering of an analyze()/read() result."""
    size = f"{res['letter_px']} px ({res['letter_px_from']}"
    if "letter_mm" in res:
        size += f", {res['letter_mm']:g} mm at {res['um_per_px']:g} um per pixel"
    out = [res["note"], f"letter height {size}), deskew {res['deskew_deg']} deg, confidence floor {res['p_min']}"]
    if res.get("input_scale", 1) != 1:
        shape = " x ".join(str(n) for n in res["input_shape"])
        red = " x ".join(str(n) for n in res.get("reduced_shape", []))
        out.append(f"input {shape} px block-averaged by {res['input_scale']} while loading (read as {red}); "
                   "rows, columns and boxes are in input pixels")
    if "scale_search" in res:
        out.append(f"scale search around the first guess of {res.get('letter_px_first_guess', '?')} px "
                   "(* = kept: most letters above its own nulls):")
        for t in res["scale_search"]:
            mark = "*" if t["letter_px"] == res["letter_px"] else " "
            out.append(f"  {mark} {t['letter_px']:>9} px: {t['letters_kept']:>4} kept, nulls "
                       f"{t['null_letters_kept']}, margin {t['margin']}")
    if "warning" in res.get("letter_px_check", {}):
        out.append("warning: " + res["letter_px_check"]["warning"])
    multi = len(res.get("columns", [])) > 1
    if multi:
        out.append(f"{len(res['columns'])} columns at x " + ", ".join(f"{c['x0']} to {c['x1']}" for c in res["columns"]))
    for r in res["lines"]:
        s = (f"col {r['column']} " if multi else "") + f"line {r['line']:>2} y={r['y']:>7}{_line_counts(r)}: " \
            f"{r['ink_only'] or '(none)'}"
        if "with_lm" in r:
            s += f"   | with LM: {r['with_lm']}"
        out.append(s)
    if multi and all("control" in col for col in res["columns"]):
        for i, col in enumerate(res["columns"]):
            chance = "" if col["control"].get("chance") is None else f", chance {col['control']['chance']:g}"
            out.append(f"column {i} (x {col['x0']} to {col['x1']}): {status_line(col['control'], sentence=False)}{chance}")
    c = res["control"]
    out.append(f"control: {c['letters_kept']} letters kept vs nulls {c['null_letters_kept']}: {c['verdict']}")
    if "control_map" in c:
        name = f" {c['control_map']['file']}" if "file" in c["control_map"] else ""
        out.append(f"control map{name}: {c['control_map']['letters_kept']} letters kept on the same lines at the same "
                   "confidence floor")
    if "status" in c:
        out.append("status: " + status_line(c))
    if "orientation" in res:
        out.append(f"orientation: {res['orientation']['letters_kept']} (best {res['orientation']['best']})")
    return "\n".join(out)


def _line_counts(r):
    """A line's kept letters beside its chance count for the summary, such as " [ 15 kept, chance  2.52]"; "" for older results."""
    if "chance" not in r and "control_map_kept" not in r:
        return ""
    bits = [f"{r['n_kept']:>3} kept"]
    if r.get("chance") is not None:
        bits.append(f"chance {r['chance']:>5.2f}")
    if "control_map_kept" in r:
        bits.append(f"control map {r['control_map_kept']:>3}")
    return " [" + ", ".join(bits) + "]"


GREEK_FONTS = ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial Unicode.ttf",
               "C:/Windows/Fonts/arial.ttf", "FreeSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSans.ttf")


def _greek_font(size):
    from PIL import ImageFont
    for name in GREEK_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return None


def _banner_font(size):
    font = _greek_font(size)
    if font is None:
        from PIL import ImageFont
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:  # Pillow before 10.1 has one bitmap size
            font = ImageFont.load_default()
    return font


def _wrap(text, font, width, draw):
    """Lines of whole words, each at most width pixels wide; None when a word alone is wider."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}" if cur else word
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        elif not cur or draw.textlength(word, font=font) > width:
            return None
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


def _wrap_paragraphs(text, font, width, draw):
    """_wrap() for each paragraph (newline-separated) of text, each starting on a new line; None as _wrap()."""
    out = []
    for para in text.split("\n"):
        lines = _wrap(para, font, width, draw)
        if lines is None:
            return None
        out += lines
    return out


def banner_text(res):
    """The overlay banner's words: the model-output note, then the status of the controls and its counts when res has them."""
    c = res.get("control") or {}
    return NOTE + ("\nControls: " + status_line(c) if "status" in c else "")


def banner_layout(width, text=NOTE):
    """(font, lines, line height, top offset, canvas width) that show all of `text` above an image `width` px wide.

    The font is about 1.2% of the width (10 to 40 px) and the words wrap onto as many lines as they
    need, each paragraph (a newline in text) on new lines; a word too wide for a narrow image first
    shrinks the font (down to 6 px), then widens the canvas, so the whole text is always there."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    size = max(10, min(40, int(0.012 * width)))
    while True:
        font = _banner_font(size)
        lines = _wrap_paragraphs(text, font, width - 8, d)
        if lines is not None or size <= 6:
            break
        size -= 1
    if lines is None:
        width = int(math.ceil(max(d.textlength(w, font=font) for w in text.split()))) + 8
        lines = _wrap_paragraphs(text, font, width - 8, d)
    _, top, _, bottom = d.textbbox((0, 0), "MgΩ|", font=font)
    return font, lines, (bottom - top) + max(2, (bottom - top) // 4), top, width


def _overlay_layout(shape, res, max_side):
    s = min(1.0, max_side / max(shape))
    H, W = max(1, int(round(shape[0] * s))), max(1, int(round(shape[1] * s)))
    font, lines, lh, top, cw = banner_layout(W, banner_text(res))
    band = 6 + len(lines) * lh
    reduced = res.get("input_scale", 1) != 1 and list(shape) == res.get("reduced_shape")
    scale = s / res["input_scale"] if reduced else s          # overlay pixels per input pixel
    return {"s": s, "H": H, "W": W, "font": font, "lines": lines, "lh": lh, "top": top, "band": band,
            "canvas": (max(W, cw), H + band), "scale": scale}


def overlay_geometry(shape, res, max_side=OVERLAY_MAX_SIDE):
    """Where overlay() puts things, as JSON: overlay pixels per input pixel, banner rows and PNG size.

    shape is the shape of the image to be drawn (the block-averaged one, after a reduced read). A box
    edge at input row y and column x lands at overlay row banner_rows + y * scale, column x * scale."""
    g = _overlay_layout(shape, res, max_side)
    return {"scale": round(g["scale"], 6), "banner_rows": g["band"], "size": [g["canvas"][1], g["canvas"][0]],
            "max_side": max_side}


def overlay(img, res, path, polarity="bright", max_side=OVERLAY_MAX_SIDE, normalized=False):
    """Write a PNG of the image with the reader's letters drawn on it, for a person to check.

    Kept letters get a box and their glyph (green when p >= 0.8, yellow below); letters under the
    confidence floor get a grey box and no glyph; every outline is at least 2 px wide. A banner
    above the image always carries the whole model-output note, wrapped to the width, and then the
    status of the controls with its counts (banner_text). The image is
    shrunk to max_side pixels on its longer side; overlay_geometry() gives the scale. img may be the
    block-averaged image of a reduced read (boxes are mapped from input pixels), and normalized=True
    skips normalising it again. Glyphs need a font with Greek (DejaVu, Arial or FreeSans); without
    one only the boxes are drawn. Never use this image as a prize image: it carries machine letter
    annotations."""
    from PIL import Image, ImageDraw
    a = np.asarray(img, dtype=np.float32) if normalized else normalize(img, polarity)
    g = _overlay_layout(a.shape, res, max_side)
    H, W, band, sb = g["H"], g["W"], g["band"], g["scale"]
    base = Image.fromarray((resize(a, (H, W)) * 255).round().astype(np.uint8)).convert("RGB")
    canvas = Image.new("RGB", g["canvas"], (255, 255, 255))
    canvas.paste(base, (0, band))
    d = ImageDraw.Draw(canvas)
    for i, text in enumerate(g["lines"]):
        d.text((4, 3 + i * g["lh"] - g["top"]), text, fill=(0, 0, 0), font=g["font"])
    letter = res["letter_px"] * sb                   # letter height in overlay pixels
    font = _greek_font(max(10, int(letter * 0.6)))
    lw = max(2, int(round(letter / 24)))
    for L in res["lines"]:
        for l in L["letters"]:
            y0, y1, x0, x1 = (v * sb for v in l["box"])
            y0, y1 = y0 + band, y1 + band
            if l["kept"]:
                col = (40, 200, 70) if l["p"] >= 0.8 else (230, 190, 40)
                d.rectangle([x0, y0, x1, y1], outline=col, width=lw)
                if font is not None:
                    d.text((x0 + 1, max(band, y0 - font.size - 1)), l["glyph"], fill=col, font=font)
            else:
                d.rectangle([x0, y0, x1, y1], outline=(120, 120, 120), width=max(2, lw - 1))
    canvas.save(path)
    return path
