"""StrokeNet: a small learned text-likeness score for 2D ink maps, with controls, numpy only.

A small CNN (scripts/strokenet/train.py) looks at 6.1 mm windows of an ink map (128 x 128 pixels
at 0.048 mm) and gives a logit for "looks like lines of body text of PHerc. Paris 4, as the
organisers' 2026 ink model draws it", against blank papyrus and copies of text windows with
their arrangement or orientation destroyed. It was trained and tested on one scroll's maps from
one ink model, with text and blank labels made by a rule from the maps themselves
(docs/strokenet.md gives the measured numbers and their limits). A high score is model output:
it is never a reading, and never evidence by itself that text exists where none is known.

Input, as in training:
- the map is resampled to 0.048 mm (to_working). An integer map (the organisers' uint8
  predictions) at a whole fraction of 0.048 mm, such as 2.4 um, is pooled exactly as the training
  windows were (block sums, rounded half to even); other inputs are area-averaged, then rounded
  when the map is integer. Values are on the organisers' 0 to 255 scale. Float or rescaled maps
  are outside the training distribution.
- only windows with at least 99 % core papyrus are scored, the rule the training windows met.
  Usable means a value above 3, opened three times with a cross and with holes filled
  (usable_mask); core is usable papyrus more than 1.5 mm from any unusable pixel (core_mask).
  NaN or infinite values read as 0, so they count as unusable. Skipped windows are counted in
  every summary, and a map smaller than 128 px at 0.048 mm is refused.

Controls travel with every map result (analyze), on a seeded random sample of the kept windows,
not the highest-scoring ones (choosing windows by the score under test biases a control toward
passing):
- rotation: each window turned by 90 degrees. Text lines in the trained orientation should score
  lower turned; if the turned windows score higher, the map is probably on its side;
- IAAFT: each window against an IAAFT copy of itself (200 iterations, as the evaluation copies):
  the same pixel values and nearly the same power spectrum, arrangement scrambled. The copies keep
  the values but carry a small excess of high-frequency power, so a score can drop on them
  without using arrangement. The share above the copy and the mean drop are therefore read
  against the validation reference values stored with the weights (meta["val_ref"]), not
  against 0.5 or 0.

No probability is reported: the Platt parameters in the weights are fitted on a fixed evaluation
mixture of text and null copies, so calibrate() is not P(text) on a real map.

Weights are an .npz exported by the training script (batch norm folded into the convolutions).
They are not in git: pass a file, or the name of a released model in
kit/data/strokenet-weights.json, which resolve_weights() downloads once and checks by SHA-256.

  net = load("strokenet-paris4-v1")              # or a path
  net.logits(windows)                            # (N, 128, 128) -> (N,) logits
  net.score_map(ink, pixel_mm, stride_px=32)     # logit grid over a map, NaN where skipped
  net.region_score(ink, pixel_mm)                # summary dict
  analyze(ink, pixel_mm, net)                    # summary plus both controls (python -m kit strokenet)
"""
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

NOTE = ("Model output: a text-likeness score from a small CNN trained on one scroll's ink maps, "
        "not a reading. It never shows by itself that text is present.")
WEIGHTS_REGISTRY = Path(__file__).parent / "data" / "strokenet-weights.json"
DEFAULT = os.environ.get("KIT_STROKENET_DEFAULT", "strokenet-paris4-v1")
PIXEL_MM = 0.048
CROP = 128
IAAFT_ITERS = 200              # as the evaluation copies (scripts/strokenet/nulls.py)
SAMPLE = 64                    # windows drawn for the controls
USABLE_MIN = 3                 # usable papyrus: map value above this (0 to 255 scale)
MIN_USABLE_FRAC = 0.99         # windows with fewer core pixels are skipped
CORE_MM = 1.5                  # core papyrus: more than this from any unusable pixel
STRIP_PX = 1 << 22             # source pixels read at a time by to_working
# Map pixel sizes StrokeNet takes, in mm. 1 mm is 21 times its 0.048 mm working pixel: a 6.1 mm window
# then spans about 6 source pixels and a letter 2 to 4, so no stroke is left to see, and a coarser map
# is only enlarged further. 0.0001 mm (0.1 um) is ten times finer than any scroll scan.
MIN_PIXEL_MM, MAX_PIXEL_MM = 1e-4, 1.0


# ------------------------------------------------------------------ released weights
def weights_cache():
    """Folder for downloaded weights: $KIT_STROKENET_WEIGHTS, else ~/.cache/scrolls-kit/strokenet."""
    env = os.environ.get("KIT_STROKENET_WEIGHTS")
    return Path(env) if env else Path.home() / ".cache" / "scrolls-kit" / "strokenet"


def released_weights(registry=None):
    """{name: entry} of released StrokeNet weights (file, sha256, url, licence, notes)."""
    return json.loads(Path(registry or WEIGHTS_REGISTRY).read_text(encoding="utf-8"))["models"]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def resolve_weights(spec=None, cache=None, registry=None, download=True):
    """A weights file path from a path or a released model name (default DEFAULT).

    A released name is looked up in the cache folder and downloaded from its URL when missing;
    either way its SHA-256 must match the registry, so a damaged or swapped file is refused."""
    spec = str(spec or DEFAULT)
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
            raise ValueError(f"{spec}: no download address yet; see docs/strokenet.md")
        import urllib.request
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        with urllib.request.urlopen(m["url"]) as r, open(tmp, "wb") as f:
            for block in iter(lambda: r.read(1 << 20), b""):
                f.write(block)
        if _sha256(tmp) != m["sha256"]:
            tmp.unlink()
            raise ValueError(f"{spec}: download from {m['url']} does not match its SHA-256; nothing kept")
        tmp.replace(dest)
    if _sha256(dest) != m["sha256"]:
        raise ValueError(f"{spec}: {dest} does not match its SHA-256 {m['sha256']}; delete it and retry")
    return dest


# ------------------------------------------------------------------ reading a map
def _plane(z):
    """A 2D map from an array or array-like; a 2D array-like stays lazy (read in strips later)."""
    if len(z.shape) == 2:
        return z
    a = np.squeeze(np.asarray(z))
    if a.ndim == 3 and a.shape[-1] in (3, 4):
        c = a[..., :3]
        # a grey map saved as colour keeps its integer values; a real colour image is averaged
        a = c[..., 0] if (c == c[..., :1]).all() else c.mean(axis=-1, dtype=np.float64).astype(np.float32)
    if a.ndim != 2:
        raise ValueError(f"expected a 2D map, got shape {a.shape}")
    return a


@contextlib.contextmanager
def open_map(path, key=None):
    """Open an ink map keeping its dtype (so an integer map gets the exact training pooling).

    .npy is memory-mapped and a TIFF is read lazily through zarr when zarr is installed, so a whole
    2.4 um segment never has to be in memory at once; .npz (named or first array) and images
    (Pillow) are read whole."""
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".npy":
        yield _plane(np.load(p, mmap_mode="r", allow_pickle=False))
    elif suf == ".npz":
        with np.load(p, allow_pickle=False) as z:
            a = z[key or z.files[0]]
        yield _plane(a)
    elif suf in (".tif", ".tiff"):
        import tifffile
        with tifffile.TiffFile(str(p)) as t:
            try:
                import zarr
            except ImportError:
                zarr = None
            if zarr is not None:
                z = zarr.open(t.aszarr(), mode="r")
                if not hasattr(z, "shape"):
                    z = z[sorted(z.keys())[0]]
            else:
                z = t.asarray()
            yield _plane(z)
    else:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(p) as im:
            if im.mode not in ("L", "I;16", "I;16B", "I;16L", "I", "F", "RGB", "RGBA"):
                im = im.convert("RGB")
            a = np.asarray(im)
        yield _plane(a)


# ------------------------------------------------------------------ resampling
def _area_edges(a, edges, width):
    """Area average along axis 0 over the cells [edges[j], edges[j + 1]) in input-row units, each
    `width` rows wide (exact for a piecewise-constant input)."""
    n = a.shape[0]
    c = np.concatenate([np.zeros((1,) + a.shape[1:]), np.cumsum(a, axis=0)])        # integral at 0..n
    lo = np.floor(edges).astype(int).clip(0, n)
    hi = np.minimum(lo + 1, n)
    frac = (edges - lo).reshape((-1,) + (1,) * (a.ndim - 1))
    ce = c[lo] + (c[hi] - c[lo]) * frac                                                # integral at each edge
    return (ce[1:] - ce[:-1]) / width


def _area_axis(a, n_out, axis):
    """Area-weighted resampling of one axis to n_out samples (exact for a piecewise-constant input)."""
    a = np.moveaxis(np.asarray(a, np.float64), axis, 0)
    n = a.shape[0]
    if n_out == n:
        return np.moveaxis(a, 0, axis)
    out = _area_edges(a, np.linspace(0, n, n_out + 1), n / n_out)
    return np.moveaxis(out, 0, axis)


def _source(ink):
    """(array or array-like, shape, dtype) without reading an array-like that has shape and dtype."""
    if hasattr(ink, "shape") and hasattr(ink, "dtype") and hasattr(ink, "__getitem__"):
        return ink, tuple(ink.shape), np.dtype(ink.dtype)
    a = np.asarray(ink)
    return a, a.shape, a.dtype


def _finite(blk):
    """NaN and infinite values read as 0 (below the usable threshold, as the organisers' maps mark
    no data), so they count as unusable and never spread through the pooling sums."""
    if np.issubdtype(blk.dtype, np.floating) and not np.isfinite(blk).all():
        return np.where(np.isfinite(blk), blk, 0).astype(blk.dtype)
    return blk


def check_pixel_mm(pixel_mm):
    """A ValueError when pixel_mm is not a map pixel size StrokeNet can use (MIN_PIXEL_MM to MAX_PIXEL_MM); else None."""
    try:
        ok = math.isfinite(float(pixel_mm)) and MIN_PIXEL_MM <= float(pixel_mm) <= MAX_PIXEL_MM
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise ValueError(f"pixel_mm {pixel_mm!r}: give the map's pixel size in mm, from {MIN_PIXEL_MM:g} to "
                         f"{MAX_PIXEL_MM:g} (0.0024 for a 2.4 um map; StrokeNet works at {PIXEL_MM} mm)")


def to_working(ink, pixel_mm, strip=None):
    """Resample a 2D map (array or array-like such as zarr) to 0.048 mm per pixel; float32.

    Integer factor (pixel_mm * k == 0.048): k x k block means, rows and columns past the last whole
    block dropped. For an integer map the block sums are rounded half to even, which reproduces
    scripts/strokenet/data.py pool_array (the training windows) exactly. Otherwise exact area
    averaging, then np.rint for an integer map. NaN and infinite source values read as 0. The source
    is read `strip` rows at a time (default about STRIP_PX pixels per strip), so no full float copy
    of it is made."""
    check_pixel_mm(pixel_mm)
    z, shape, dtype = _source(ink)
    if len(shape) != 2:
        raise ValueError(f"expected a 2D map, got shape {shape}")
    H, W = shape
    integer = np.issubdtype(dtype, np.integer)
    rows = int(strip) if strip else max(1, STRIP_PX // max(W, 1))
    k = int(round(PIXEL_MM / pixel_mm))
    if k >= 1 and abs(pixel_mm * k - PIXEL_MM) < 1e-9:
        Hk, Wk = (H // k) * k, (W // k) * k
        out = np.empty((Hk // k, Wk // k), np.float32)
        step = max(k, rows // k * k)
        for y in range(0, Hk, step):
            y1 = min(Hk, y + step)
            blk = _finite(np.asarray(z[y:y1, :Wk]))
            if k == 1:
                out[y:y1] = blk
                continue
            s = blk.reshape((y1 - y) // k, k, Wk // k, k).sum(axis=(1, 3), dtype=np.int64 if integer else np.float64)
            s = s / float(k * k)
            out[y // k:y1 // k] = np.round(s) if integer else s
        return out
    f = pixel_mm / PIXEL_MM                                         # output pixels per source pixel
    Ho, Wo = max(1, int(round(H * f))), max(1, int(round(W * f)))
    edges = np.linspace(0, H, Ho + 1)
    out = np.empty((Ho, Wo), np.float32)
    step = max(1, int((rows - 2) * Ho / H))                         # output rows per strip
    for j0 in range(0, Ho, step):
        j1 = min(Ho, j0 + step)
        lo, hi = int(np.floor(edges[j0])), min(H, int(np.floor(edges[j1])) + 1)
        blk = _area_axis(_finite(np.asarray(z[lo:hi])), Wo, 1)
        o = _area_edges(blk, edges[j0:j1 + 1] - lo, H / Ho)
        out[j0:j1] = np.rint(o) if integer else o
    return out


# ------------------------------------------------------------------ usable papyrus and windows
def _erode(m):
    """Binary erosion by the 3 x 3 cross, outside the array counted as 0 (scipy's default)."""
    out = m.copy()
    out[1:] &= m[:-1]
    out[:-1] &= m[1:]
    out[:, 1:] &= m[:, :-1]
    out[:, :-1] &= m[:, 1:]
    out[0] = out[-1] = False
    out[:, 0] = out[:, -1] = False
    return out


def _dilate(m):
    """Binary dilation by the 3 x 3 cross, outside the array counted as 0."""
    out = m.copy()
    out[1:] |= m[:-1]
    out[:-1] |= m[1:]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    return out


def _spread_rows(reach, bg):
    """reach grown to every whole run of bg along each row that holds a reached pixel."""
    start = bg.copy()
    start[:, 1:] &= ~bg[:, :-1]                     # a run starts at a bg pixel after a non-bg one
    rid = np.cumsum(start.ravel())                  # run number of every bg pixel
    hit = np.zeros(int(rid[-1]) + 1 if rid.size else 1, bool)
    hit[rid[reach.ravel()]] = True
    return bg & hit[rid].reshape(bg.shape)


def _fill_holes(m):
    """scipy.ndimage.binary_fill_holes with its default cross: background not 4-connected to the
    array's edge is filled. Runs along rows and columns are spread in turn until nothing changes."""
    bg = ~m
    reach = np.zeros_like(bg)
    reach[0], reach[-1] = bg[0], bg[-1]
    reach[:, 0], reach[:, -1] = bg[:, 0], bg[:, -1]
    while True:
        new = _spread_rows(_spread_rows(reach, bg).T, bg.T).T
        if np.array_equal(new, reach):
            return ~reach
        reach = new


def usable_mask(a, use_scipy=None):
    """Usable papyrus as scripts/strokenet/data.py label_map defines it: value above 3, binary
    opening with the cross structuring element (3 iterations, outside the map 0), holes filled.
    scipy.ndimage when importable (use_scipy None or True), else a numpy version with the same
    result (use_scipy False forces it)."""
    m = np.asarray(a) > USABLE_MIN
    if m.size == 0:
        return m
    if use_scipy is not False:
        try:
            from scipy import ndimage as ndi
        except ImportError:
            if use_scipy:
                raise
        else:
            return ndi.binary_fill_holes(ndi.binary_opening(m, iterations=3))
    for _ in range(3):
        m = _erode(m)
    for _ in range(3):
        m = _dilate(m)
    return _fill_holes(m)


def _core_numpy(u, r):
    """Pixels farther than r from every False pixel of u (Euclidean), the array's outside not
    counted: u eroded by the disk of the integer offsets within r, row by row from a prefix count."""
    H, W = u.shape
    r2, R = int(np.floor(r * r)), int(np.floor(r))           # offsets with dy^2 + dx^2 <= r2 are near
    Z = np.zeros((H, W + 1 + 2 * R), np.int32 if W < 2 ** 31 else np.int64)
    np.cumsum(~u, axis=1, out=Z[:, R + 1:R + 1 + W])          # Z[:, R + j]: unusable pixels left of column j
    Z[:, R + 1 + W:] = Z[:, R + W:R + W + 1]
    near = np.zeros((H, W), bool)
    rows = {}
    for dy in range(-R, R + 1):
        w = int(np.floor(np.sqrt(r2 - dy * dy)))
        while (w + 1) ** 2 + dy * dy <= r2:
            w += 1
        while w * w + dy * dy > r2:
            w -= 1
        if w not in rows:                                     # any unusable pixel in columns x - w .. x + w
            rows[w] = Z[:, R + w + 1:R + w + 1 + W] > Z[:, R - w:R - w + W]
        h = rows[w]
        if dy >= 0:
            near[:H - dy] |= h[dy:]
        else:
            near[-dy:] |= h[:H + dy]
    return ~near


def core_mask(a, use_scipy=None):
    """Core papyrus as scripts/strokenet/data.py label_map defines it (its labels are nonzero
    exactly here): usable_mask pixels whose Euclidean distance to the nearest unusable pixel is
    above 1.5 mm, pixels outside the map not counted as unusable. A map with no unusable pixel is
    all core (scipy's distance transform has no reference point there). scipy.ndimage when
    importable, else a numpy erosion by the same disk with the same result."""
    u = usable_mask(a, use_scipy)
    r = CORE_MM / PIXEL_MM
    if u.size == 0 or u.all():
        return u.copy()
    if use_scipy is not False:
        try:
            from scipy import ndimage as ndi
        except ImportError:
            if use_scipy:
                raise
        else:
            return ndi.distance_transform_edt(u) > r
    return _core_numpy(u, r)


def snap_crop(crop, pixel_mm, shape=None):
    """A crop (y0, y1, x0, x1) in source pixels with its origin moved down to the training lattice.

    The training windows start every 32 px (1.536 mm) from the segment's origin, and the
    organisers' ink maps carry a faint tile pattern (overlapping 256 px tiles at stride 128 on the
    2.4 um grid) that repeats every 32 px at 0.048 mm, so every training window saw it at the same
    phase. When pixel_mm is a whole fraction of 0.048 mm, y0 and x0 are moved down to multiples of
    32 x k source pixels (k = 0.048 / pixel_mm), so the crop's windows keep that lattice, phase and
    exact pooling. Otherwise the crop is used as given (the pooling is not exact anyway). With the
    map's shape, y1 and x1 are clipped to it. Returns (crop used, True when the origin was moved).

    The window rule is then applied to the crop alone: papyrus edges outside it are not seen, and
    the corners of the crop lose about 1.5 mm of core papyrus. For exactly the training rule, score
    the whole map and read the windows needed from the grid."""
    check_pixel_mm(pixel_mm)
    y0, y1, x0, x1 = (int(v) for v in crop)
    if shape is not None:
        y1, x1 = min(y1, int(shape[0])), min(x1, int(shape[1]))
    if y1 <= y0 or x1 <= x0 or min(y0, x0) < 0:
        raise ValueError(f"--crop needs 0 <= Y0 < Y1 and 0 <= X0 < X1 inside the map, got {list(crop)}")
    k = int(round(PIXEL_MM / pixel_mm))
    if not (k >= 1 and abs(pixel_mm * k - PIXEL_MM) < 1e-9):
        return [y0, y1, x0, x1], False
    step = 32 * k
    used = [y0 // step * step, y1, x0 // step * step, x1]
    return used, used[0] != y0 or used[2] != x0


def window_starts(n, stride_px):
    """Window starts along one axis: every stride_px, plus one aligned to the end of the map."""
    if n < CROP:
        raise ValueError(f"the map is {n} px at {PIXEL_MM} mm along one side; StrokeNet needs at least {CROP} "
                         f"({CROP * PIXEL_MM:.1f} mm)")
    if int(stride_px) < 1:
        raise ValueError("stride_px must be at least 1")
    s = list(range(0, n - CROP + 1, int(stride_px)))
    if s[-1] != n - CROP:
        s.append(n - CROP)
    return s


def layout(a, stride_px=32):
    """Window grid of a working map (0.048 mm): (ys, xs, keep), keep[i, j] True when the window at
    (ys[i], xs[j]) has at least 99 % core pixels (core_mask; the training rule). Windows start every
    stride_px from the map's origin; with the default 32 they sit on the training lattice (a crop
    keeps it through snap_crop), except the last window along each axis, which is aligned to the
    map's end. Raises ValueError for a map smaller than 128 px."""
    H, W = a.shape
    ys, xs = window_starts(H, stride_px), window_starts(W, stride_px)
    dt = np.int32 if H * W < 2 ** 31 else np.int64          # usable-pixel counts, integral image
    S = np.zeros((H + 1, W + 1), dt)
    np.cumsum(np.cumsum(core_mask(a), axis=0, dtype=dt), axis=1, out=S[1:, 1:])
    Y, X = np.asarray(ys)[:, None], np.asarray(xs)[None, :]
    cnt = S[Y + CROP, X + CROP] - S[Y, X + CROP] - S[Y + CROP, X] + S[Y, X]
    return ys, xs, cnt / float(CROP * CROP) >= MIN_USABLE_FRAC


def _windows(a, ys, xs, pos):
    return np.stack([a[ys[i]:ys[i] + CROP, xs[j]:xs[j] + CROP] for i, j in pos]) if len(pos) else \
        np.zeros((0, CROP, CROP), np.float32)


# ------------------------------------------------------------------ network
def _lower_median(f):
    """Per-row median taking the lower middle value for an even count, as torch.median does."""
    k = (f.shape[1] - 1) // 2
    return np.partition(f, k, axis=1)[:, k:k + 1]


def normalise(windows):
    """Per window (x - median) / (1.4826 MAD), clipped to -3..20 and divided by 5. The median is the
    lower middle value for an even count, as in torch, so numpy and torch scores agree."""
    x = np.asarray(windows, dtype=np.float32)
    f = x.reshape(len(x), -1)
    med = _lower_median(f)
    mad = _lower_median(np.abs(f - med)) * 1.4826
    sd = f.std(axis=1, ddof=1, keepdims=True)          # unbiased, as torch.std
    mad = np.where(mad < 1e-3, sd + 1e-3, mad)
    return (np.clip((f - med) / mad, -3, 20) / 5.0).reshape(x.shape).astype(np.float32)


def _conv3(x, w, b):
    """3 x 3 'same' convolution (cross-correlation, as in PyTorch). x: (N, C, H, W); w: (O, C, 3, 3)."""
    N, C, H, W = x.shape
    O = w.shape[0]
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    out = np.empty((N, O, H, W), np.float32)
    wm = w.reshape(O, C * 9).T
    for n in range(N):
        cols = np.lib.stride_tricks.sliding_window_view(xp[n], (3, 3), axis=(1, 2))
        cols = cols.transpose(1, 2, 0, 3, 4).reshape(H * W, C * 9)
        out[n] = (cols @ wm + b).T.reshape(O, H, W)
    return out


def _pool2(x):
    N, C, H, W = x.shape
    return x[:, :, :H // 2 * 2, :W // 2 * 2].reshape(N, C, H // 2, 2, W // 2, 2).max(axis=(3, 5))


def iaaft(windows, rng, iters=IAAFT_ITERS):
    """IAAFT copies (Schreiber and Schmitz 1996) of one window (H, W) or a stack (N, H, W), by default
    with 200 iterations as the evaluation copies. The algorithm of scripts/strokenet/nulls.py iaaft,
    in numpy and float64: start from a random permutation of each window's values, then alternate
    imposing the window's amplitude spectrum and an exact rank remap onto its sorted values (ties
    broken by position, stable argsort), ending on the remap.

    A copy keeps the window's pixel values exactly and nearly its amplitude spectrum, with the
    arrangement scrambled; on these narrow-range maps it keeps a small excess of high-frequency
    power, so a score that rejects copies may use that residue rather than arrangement."""
    x = np.asarray(windows, np.float64)
    single = x.ndim == 2
    if single:
        x = x[None]
    N, shape = len(x), x.shape[1:]
    if N == 0:
        return x.copy()
    size = shape[0] * shape[1]
    flat = x.reshape(N, size)
    vals = np.sort(flat, axis=1)
    amp = np.abs(np.fft.rfft2(x))
    y = np.stack([f[rng.permutation(size)] for f in flat])
    rows, ar = np.arange(N)[:, None], np.broadcast_to(np.arange(size), (N, size))
    ranks = np.empty((N, size), np.intp)
    for _ in range(iters):
        Y = np.fft.rfft2(y.reshape(x.shape))
        z = np.fft.irfft2(amp * np.exp(1j * np.angle(Y)), s=shape).reshape(N, -1)
        ranks[rows, np.argsort(z, axis=1, kind="stable")] = ar
        y = np.take_along_axis(vals, ranks, axis=1)
    y = y.reshape(x.shape)
    return y[0] if single else y


class StrokeNet:
    def __init__(self, path):
        z = np.load(path, allow_pickle=False)
        self.path = str(path)
        self.n_conv = int(z["n_conv"])
        self.w = [z[f"conv{i}_w"].astype(np.float32) for i in range(self.n_conv)]
        self.b = [z[f"conv{i}_b"].astype(np.float32) for i in range(self.n_conv)]
        self.pool_after = {i for i in range(self.n_conv) if f"pool_after_{i}" in z.files}
        self.head_w, self.head_b = z["head_w"].astype(np.float32), z["head_b"].astype(np.float32)
        self.meta = json.loads(str(z["meta"]))
        self.platt = self.meta.get("platt")                   # [a, b]: sigmoid(a * logit + b)
        self.null_q99 = self.meta.get("val_blank_logit_q99")   # 99th percentile, validation blank windows
        self.val_ref = self.meta.get("val_ref")               # validation values of the two controls

    def logits(self, windows, batch=16):
        """(N, 128, 128) windows -> (N,) float32 logits; each batch is normalised on its own, so
        memory stays bounded for any N."""
        out = []
        for i in range(0, len(windows), batch):
            h = normalise(windows[i:i + batch])[:, None]
            for k in range(self.n_conv):
                h = np.maximum(_conv3(h, self.w[k], self.b[k]), 0)
                if k in self.pool_after:
                    h = _pool2(h)
            g = np.concatenate([h.mean(axis=(2, 3)), h.max(axis=(2, 3))], axis=1)
            out.append(g @ self.head_w[0] + self.head_b[0])
        return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)

    def calibrate(self, logit):
        """Platt-scaled logits. The Platt parameters are fitted on a fixed evaluation mixture (text
        0.5; blank, dense, IAAFT, shuffle and rot90 copies 0.1 each), so the result is a probability
        only under that mixture and is not P(text) on a real map; summaries do not report it."""
        if not self.platt:
            raise ValueError("no Platt parameters in this weights file")
        a, b = self.platt
        return 1.0 / (1.0 + np.exp(-(a * np.asarray(logit, np.float64) + b)))

    def _kept_logits(self, a, ys, xs, pos, turn=False, batch=256):
        out = []
        for i in range(0, len(pos), batch):
            w = _windows(a, ys, xs, pos[i:i + batch])
            out.append(self.logits(np.rot90(w, 1, axes=(1, 2)) if turn else w))
        return np.concatenate(out) if out else np.zeros(0, np.float32)

    def score_map(self, ink, pixel_mm, stride_px=32):
        """Logit grid over the map's windows (rows ys, columns xs of layout()); NaN marks a window
        skipped for having less than 99 % core pixels."""
        a = to_working(ink, pixel_mm)
        ys, xs, keep = layout(a, stride_px)
        grid = np.full(keep.shape, np.nan, np.float32)
        pos = np.argwhere(keep)
        grid[keep] = self._kept_logits(a, ys, xs, pos)
        return grid

    def summarise(self, v, n_skipped=None):
        """Summary of window logits; NaN values count as skipped windows (unless n_skipped is given).
        The values are None when no window was kept, and the share above the validation blank q99
        is None when the weights carry no q99."""
        v = np.asarray(v, np.float64).ravel()
        kept = v[np.isfinite(v)]
        out = {"learned_mean": None, "learned_max": None, "learned_top10": None, "learned_n": int(kept.size),
               "learned_n_skipped": int(v.size - kept.size if n_skipped is None else n_skipped),
               "learned_frac_above_val_blank_q99": None}
        if kept.size:
            out.update(learned_mean=float(kept.mean()), learned_max=float(kept.max()),
                       learned_top10=float(np.mean(np.sort(kept)[-max(1, kept.size // 10):])))
            if self.null_q99 is not None:
                out["learned_frac_above_val_blank_q99"] = float(np.mean(kept > self.null_q99))
        return out

    def region_score(self, ink, pixel_mm, stride_px=32):
        return self.summarise(self.score_map(ink, pixel_mm, stride_px))


_CACHE = {}


def load(spec=None):
    """A StrokeNet from a weights path or a released model name (default DEFAULT)."""
    p = str(resolve_weights(spec))
    if p not in _CACHE:
        _CACHE[p] = StrokeNet(p)
    return _CACHE[p]


# ------------------------------------------------------------------ map analysis with controls
def _control(v, copy, ref, name):
    """Share of windows scoring above their copy and the mean logit drop, with the validation
    reference values of the same control when the weights carry them."""
    out = {"frac_above_copy": float(np.mean(v > copy)) if len(v) else None,
           "mean_logit_drop": float(np.mean(v - copy)) if len(v) else None}
    if isinstance(ref, dict):
        refs = {}
        for kind, r in ref.items():
            if isinstance(r, dict) and r.get(f"above_{name}") is not None:
                refs[kind] = {"frac_above_copy": r[f"above_{name}"]}
                if r.get(f"mean_drop_{name}") is not None:
                    refs[kind]["mean_logit_drop"] = r[f"mean_drop_{name}"]
        if refs:
            out["val_ref"] = refs
    return out


def analyze(ink, pixel_mm, net, stride_px=32, sample=SAMPLE, seed=0, iaaft_iters=IAAFT_ITERS, with_grid=False):
    """Score a map and run both controls. Returns a JSON-ready dict, or (dict, logit grid) with
    with_grid=True (grid as score_map: NaN where a window was skipped).

    map: summary of the kept windows (windows under 99 % core pixels are skipped and counted).
    rotated_90: the same windows, each turned by 90 degrees (orientation_hint compares the two).
    controls: on `sample` kept windows drawn at random with `seed`, the share scoring above their
    rot90 and IAAFT copies and the mean logit drop, next to the validation reference values in the
    weights' meta["val_ref"] when present. IAAFT copies keep the values but carry a small excess of
    high-frequency power, so the IAAFT control is read against those reference values.
    top_windows: positions (0.048 mm pixels) of the ten highest kept windows.
    window_y_px, window_x_px: the start of each grid row and column (0.048 mm pixels); every
    stride_px, except the last row and column, which end at the map's edge.
    orientation_hint compares the share above the blank threshold as given and turned, or the mean
    logit when the shares are equal or missing (orientation_hint_from names which)."""
    a = to_working(ink, pixel_mm)
    ys, xs, keep = layout(a, stride_px)
    pos = np.argwhere(keep)
    v = net._kept_logits(a, ys, xs, pos)
    vt = net._kept_logits(a, ys, xs, pos, turn=True)
    grid = np.full(keep.shape, np.nan, np.float32)
    grid[keep] = v
    skipped = int(keep.size - len(pos))
    rng = np.random.default_rng(seed)
    k = int(min(max(0, sample), len(pos)))
    idx = np.sort(rng.choice(len(pos), k, replace=False)) if k else np.zeros(0, int)
    sv = net.logits(iaaft(_windows(a, ys, xs, pos[idx]), rng, iaaft_iters)) if k else np.zeros(0, np.float32)
    res = {"note": NOTE, "weights": Path(net.path).name, "pixel_mm": float(pixel_mm), "stride_px": int(stride_px),
           "working_shape": list(a.shape), "grid_shape": list(keep.shape),
           "map": net.summarise(v, skipped), "rotated_90": net.summarise(vt, skipped),
           "controls": {"windows": k, "seed": int(seed),
                        "rot90": _control(v[idx], vt[idx], net.val_ref, "rot90"),
                        "iaaft": dict(iterations=int(iaaft_iters), **_control(v[idx], sv, net.val_ref, "iaaft"))}}
    m, r = res["map"], res["rotated_90"]
    key = "learned_frac_above_val_blank_q99"         # the share above the blank threshold, then the mean logit
    if m[key] is None or m[key] == r[key]:
        key = "learned_mean"
    if m[key] is None:
        hint = "no window was scored"
    elif r[key] > m[key]:
        hint = "the map scores higher turned by 90 degrees: its text lines may run vertically"
    elif r[key] < m[key]:
        hint = "the map scores higher as given"
    else:
        hint = "no difference between the map as given and turned by 90 degrees"
    res["orientation_hint"] = hint
    res["orientation_hint_from"] = key if m[key] is not None else None
    res["window_y_px"], res["window_x_px"] = [int(y) for y in ys], [int(x) for x in xs]   # grid rows and columns
    top = np.argsort(-v, kind="stable")[:10]
    res["top_windows"] = [{"y_px": int(ys[pos[i][0]]), "x_px": int(xs[pos[i][1]]), "logit": float(v[i])} for i in top]
    return (res, grid) if with_grid else res


def _f(x, fmt=".2f"):
    return "n/a" if x is None else format(x, fmt)


def text_summary(res):
    m, r, c = res["map"], res["rotated_90"], res["controls"]
    lines = [f"StrokeNet ({res['weights']}), {m['learned_n']} windows of 6.1 mm scored at stride {res['stride_px']} px "
             f"(0.048 mm), {m['learned_n_skipped']} skipped (under 99 % core papyrus)"]
    if not m["learned_n"]:
        lines.append(f"  no window has 99 % of its pixels above {USABLE_MIN} and {CORE_MM} mm inside the papyrus; "
                     "StrokeNet expects maps on the organisers' 0 to 255 scale")
    if m["learned_frac_above_val_blank_q99"] is not None:
        lines.append(f"  windows above the blank-papyrus threshold: {m['learned_frac_above_val_blank_q99']:.3f} as given, "
                     f"{r['learned_frac_above_val_blank_q99']:.3f} turned 90 degrees")
    lines.append(f"  mean logit {_f(m['learned_mean'])} (turned {_f(r['learned_mean'])}), "
                 f"top tenth {_f(m['learned_top10'])}")
    if c["windows"]:
        for name, label in (("rot90", "copies turned 90 degrees"),
                            ("iaaft", f"IAAFT copies ({c['iaaft']['iterations']} iterations)")):
            x = c[name]
            line = (f"  {c['windows']} random windows above their {label}: {x['frac_above_copy']:.2f} "
                    f"(mean logit drop {x['mean_logit_drop']:.2f})")
            refs = [f"{kind} {_f(v['frac_above_copy'])}" for kind, v in sorted(x.get("val_ref", {}).items())]
            lines.append(line + (f"; validation: {', '.join(refs)}" if refs else ""))
    lines.append(f"  {res['orientation_hint']}")
    lines.append(res["note"])
    return "\n".join(lines)
