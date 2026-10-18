"""Null windows for StrokeNet: copies of a window with one kind of structure destroyed, and
seam-matched copies that keep it.

Each null keeps something of the window and destroys something else; a text detector that
scores real text above a null has used what the null destroys, or an artifact of the null.

  iaaft    IAAFT surrogate (Schreiber and Schmitz 1996, Phys. Rev. Lett. 77, 635), 200
           iterations: the same pixel values (identical histogram) and nearly the same amplitude
           spectrum, with the spatial arrangement scrambled. On these narrow-range uint8 windows
           the copies keep a small excess of high-frequency power (a log-spectrum logistic
           regression trained on text against 20-iteration copies separates validation text from
           200-iteration copies at AUC about 0.85), so a score that rejects them may use that
           residue; the `nullspec` baseline measures how far the residue alone goes.
  iaaft20  the same with 20 iterations (training negatives and the training monitor).
  phase    plain Fourier phase randomization, rounded to whole values: the same amplitude
           spectrum, but the histogram becomes nearly Gaussian, so a histogram alone can separate
           it (kept for comparison with the 7 October 2026 recipe).
  shuffle  4 x 4 tiles of 32 px (1.54 mm) permuted, each rotated by a random multiple of 90
           degrees and flipped at random: local texture kept, arrangement and line direction lost.
           Leaves seams on the 32 px lattice.
  rot90    the whole window rotated by 90 degrees: everything kept except orientation.
  strip    16 vertical strips of 8 px (0.38 mm) permuted: every row keeps its values, so the
           line pattern survives, while letter shapes are cut apart. Leaves seams on the 8 px
           lattice.

Seam-matched windows (jitter): the window rebuilt on the shuffle or strip lattice, every piece in
its own place and orientation but taken from the pooled map at an independent random offset of up
to 3 px in each direction. They carry seams on the same lattice as the nulls while keeping the
letters nearly intact, so text against its null can be compared with seams on both sides:

  tilejit  32 px tiles of the 4 x 4 lattice      stripjit  8 px wide full-height strips

The torch functions take a float tensor (B, 1, H, W) on any device. Random draws come from a numpy
Generator (permutations, rotations, offsets) or a CPU torch.Generator (noise, IAAFT start), so a
seed fixes the result. eval_sets() builds a split's fixed evaluation windows on the CPU; for a
fixed chunk size and library versions it gives the same arrays on any machine (FFT rounding can
differ between CPU types; the arrays' SHA-256 are recorded so a rebuild can be compared).
"""
import hashlib

import numpy as np
import torch

TILE = 32
STRIP = 8
IAAFT_ITERS = 200          # evaluation
TRAIN_IAAFT_ITERS = 20     # training negatives and the training monitor
JITTER = 3                 # px, seam-matched windows
# Every (kind, source) pair an evaluation build can make, in a fixed order: its index fixes the
# random streams, so a subset (the training monitor) gives the same arrays as the full build.
PAIRS = (("iaaft", "text"), ("iaaft20", "text"), ("phase", "text"), ("shuffle", "text"), ("rot90", "text"),
         ("strip", "text"), ("tilejit", "text"), ("stripjit", "text"), ("iaaft", "blank"), ("shuffle", "blank"),
         ("rot90", "blank"), ("strip", "blank"), ("tilejit", "blank"), ("stripjit", "blank"))
MONITOR_PAIRS = (("iaaft20", "text"), ("shuffle", "text"), ("tilejit", "text"), ("rot90", "text"), ("rot90", "blank"))


def _ranks(z):
    """Rank of every element along dim 1 (0 = smallest), ties broken by position."""
    idx = torch.argsort(z, dim=1, stable=True)
    r = torch.empty_like(idx)
    r.scatter_(1, idx, torch.arange(z.shape[1], device=z.device).expand_as(idx))
    return r


def iaaft(x, gen, iters=IAAFT_ITERS):
    B = x.shape[0]
    size = x.shape[-2:]
    flat = x.reshape(B, -1)
    vals = flat.sort(dim=1).values
    amp = torch.fft.rfft2(x).abs()
    start = torch.rand(flat.shape, generator=gen).to(x.device)
    y = flat.gather(1, torch.argsort(start, dim=1))
    for _ in range(iters):
        Y = torch.fft.rfft2(y.reshape_as(x))
        z = torch.fft.irfft2(torch.polar(amp, torch.angle(Y)), s=size).reshape(B, -1)
        y = vals.gather(1, _ranks(z))
    return y.reshape_as(x)


def phase(x, gen):
    m = x.mean(dim=(2, 3), keepdim=True)
    F = torch.fft.rfft2(x - m)
    noise = torch.randn(x.shape, generator=gen).to(x.device)
    ph = torch.angle(torch.fft.rfft2(noise))
    ph[..., 0, 0] = 0
    out = torch.fft.irfft2(torch.polar(F.abs(), ph), s=x.shape[-2:]) + m
    return out.round().clamp(0, 255)            # whole values in 0..255, like every other window


def shuffle(x, rng, tile=TILE):
    B, _, H, W = x.shape
    n = H // tile
    t = x.reshape(B, 1, n, tile, n, tile).permute(0, 2, 4, 1, 3, 5).reshape(B, n * n, 1, tile, tile)
    perm = torch.from_numpy(np.argsort(rng.random((B, n * n)), axis=1)).to(x.device)
    t = t[torch.arange(B, device=x.device)[:, None], perm]
    k = torch.from_numpy(rng.integers(4, size=(B, n * n))).to(x.device)
    fl = torch.from_numpy(rng.random((B, n * n)) < 0.5).to(x.device)
    out = t.clone()
    for kk in (1, 2, 3):
        m = k == kk
        if m.any():
            out[m] = torch.rot90(t[m], kk, dims=(2, 3))
    if fl.any():
        out[fl] = torch.flip(out[fl], dims=(3,))
    return out.reshape(B, n, n, 1, tile, tile).permute(0, 3, 1, 4, 2, 5).reshape(B, 1, H, W)


def rot90(x):
    return torch.rot90(x, 1, dims=(2, 3))


def strip(x, rng, width=STRIP):
    B, _, H, W = x.shape
    n = W // width
    t = x.reshape(B, H, n, width)
    perm = torch.from_numpy(np.argsort(rng.random((B, n)), axis=1)).to(x.device)
    idx = perm[:, None, :, None].expand(B, H, n, width)
    return t.gather(2, idx).reshape(B, 1, H, W)


def make(kind, x, rng, gen):
    if kind == "iaaft":
        return iaaft(x, gen, IAAFT_ITERS)
    if kind == "iaaft20":
        return iaaft(x, gen, TRAIN_IAAFT_ITERS)
    if kind == "phase":
        return phase(x, gen)
    if kind == "shuffle":
        return shuffle(x, rng)
    if kind == "rot90":
        return rot90(x)
    if kind == "strip":
        return strip(x, rng)
    raise ValueError(kind)


def pieces(lattice, size=128):
    """(y0, x0, h, w) of every piece of a lattice: 'tile' (4 x 4 tiles of 32 px) or 'strip'
    (16 full-height strips of 8 px)."""
    if lattice == "tile":
        return [(ty * TILE, tx * TILE, TILE, TILE) for ty in range(size // TILE) for tx in range(size // TILE)]
    if lattice == "strip":
        return [(0, sx * STRIP, size, STRIP) for sx in range(size // STRIP)]
    raise ValueError(lattice)


def jitter(maps, seg_idx, pos, lattice, rng, max_off=JITTER, size=128):
    """Seam-matched windows: each piece of the lattice taken from the pooled map at its own random
    offset (dy, dx) in -max_off..max_off, clipped so the piece stays inside the map. maps: list of
    2D uint8 arrays; seg_idx, pos: each window's map index and (y, x). Returns uint8 (N, size, size)."""
    pcs = pieces(lattice, size)
    n = len(pos)
    off = rng.integers(-max_off, max_off + 1, size=(n, len(pcs), 2))
    out = np.empty((n, size, size), np.uint8)
    for i in range(n):
        m = maps[int(seg_idx[i])]
        H, W = m.shape
        y, x = int(pos[i][0]), int(pos[i][1])
        for p, (y0, x0, h, w) in enumerate(pcs):
            sy = min(max(y + y0 + int(off[i, p, 0]), 0), H - h)
            sx = min(max(x + x0 + int(off[i, p, 1]), 0), W - w)
            out[i, y0:y0 + h, x0:x0 + w] = m[sy:sy + h, sx:sx + w]
    return out


def array_sha256(a):
    a = np.ascontiguousarray(a)
    h = hashlib.sha256(f"{a.dtype.str}{a.shape}".encode())
    h.update(a.tobytes())
    return h.hexdigest()


def eval_sets(d, seed, maps=None, chunk=512, pairs=PAIRS):
    """A split's fixed evaluation windows.

    d: load_split output with "text", "blank" (and "dense"), plus "<kind>_seg" and "<kind>_pos"
    when pairs include seam-matched kinds (seg indices into maps). Returns {name: uint8 array}:
    "text", "blank", "dense" and "<kind>_<source>" for every (kind, source) in pairs. Each pair has
    its own random streams, fixed by seed and the pair's index in PAIRS."""
    out = {"text": np.asarray(d["text"], np.uint8), "blank": np.asarray(d["blank"], np.uint8)}
    if "dense" in d:
        out["dense"] = np.asarray(d["dense"], np.uint8)
    for kind, src in pairs:
        pi = PAIRS.index((kind, src))
        rng = np.random.default_rng([seed, pi])
        gen = torch.Generator().manual_seed(int(seed) * 1000 + pi)
        w = out[src]
        if kind in ("tilejit", "stripjit"):
            arr = jitter(maps, d[src + "_seg"], d[src + "_pos"], kind[:-3], rng)
        else:
            parts = []
            for i in range(0, len(w), chunk):
                x = torch.from_numpy(w[i:i + chunk].astype(np.float32))[:, None]
                parts.append(make(kind, x, rng, gen)[:, 0].numpy())
            arr = np.concatenate(parts) if parts else np.zeros((0,) + w.shape[1:], np.float32)
            arr = np.clip(np.rint(arr), 0, 255).astype(np.uint8)
        out[f"{kind}_{src}"] = arr
    return out
