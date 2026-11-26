#!/usr/bin/env python3
"""ctmatch: match the contrast and noise of synthetic training tiles to a real CT, from the real CT's own grey values.

A sheet-line detector trained on simulated tiles sees real CT through its input statistics: the shape of the grey-value
histogram (air, papyrus, bright inclusions), the noise level and the noise grain. Synthetic tiles get these wrong in
ways a per-window linear normalisation cannot undo. ctmatch takes a REFERENCE from real CT slices (grey values only,
never labels): for many 256 px windows, the window's 257 quantiles after its own 1st to 99th percentile scaling, its
bright fraction (share of pixels above its Otsu threshold), its noise level (standard
deviation of the residual after a Gaussian blur of sigma 1.5, over the window's 1 to 99 range) and its noise grain
(lag-1 correlation of that residual). During training each synthetic tile, with probability P, gets

1. a light blur that brings the tile's own grain to the reference window's grain, then extra noise, white noise
   blurred to that grain, so its residual level reaches the reference's;
2. a quantile map onto the reference window's histogram (rank-preserving, so every line stays where it was).

The reference window is drawn among the K windows whose bright fraction is nearest the tile's own; when even that
window's bright fraction is more than TOL away, the tile keeps its own histogram (blur and noise only), so a tile with
little papyrus is never forced into a crowded window's histogram. The lines are never moved, only grey values change.

    ref = ctmatch.reference(slices, masks)            # numpy, from real CT slices (floats, any scale)
    x = ctmatch.apply(x, ref, gen)                     # torch (B, H, W) grey values, any scale; returns 0..255

It is a training augmentation, not a reading: the reference holds grey-value statistics only.
"""

import math

NQ = 257
WIN = 256
SIG_RES = 1.5


def _np():
    import numpy as np
    return np


def _residual_stats(np, nd, w):
    """Noise level and grain of a 2D window W already scaled to its own 1..99 percentile range."""
    r = w - nd.gaussian_filter(w, SIG_RES)
    sd = float(r.std())
    a, b = r[:, :-1].ravel(), r[:, 1:].ravel()
    c = float(np.corrcoef(a, b)[0, 1]) if sd > 0 else 0.0
    return sd, c


def otsu(v, bins=64):
    """Otsu's threshold of the values V (numpy), on a BINS histogram between the 1st and 99th percentiles."""
    np = _np()
    v = np.asarray(v, np.float64).ravel()
    lo, hi = np.percentile(v, [1, 99])
    if hi <= lo:
        return float(lo)
    h, e = np.histogram(np.clip(v, lo, hi), bins, (lo, hi))
    c = (e[:-1] + e[1:]) / 2
    w0 = np.cumsum(h)
    w1 = w0[-1] - w0
    m0 = np.cumsum(h * c) / np.maximum(w0, 1)
    m1 = (np.sum(h * c) - np.cumsum(h * c)) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(c[int(np.argmax(between[:-1]))])


def _otsu_t(torch, s, bins=64):
    """Otsu's threshold per sample of S (B, N) torch, on BINS bins between each sample's 1st and 99th percentiles."""
    B = s.shape[0]
    q = torch.quantile(s[:, ::7], torch.tensor([0.01, 0.99], device=s.device), dim=1)
    lo, hi = q[0], torch.maximum(q[1], q[0] + 1e-6)
    idx = ((s.clamp(lo[:, None], hi[:, None]) - lo[:, None]) / (hi - lo)[:, None] * (bins - 1e-3)).long()
    h = torch.zeros(B, bins, device=s.device).scatter_add_(1, idx, torch.ones_like(s))
    c = lo[:, None] + (torch.arange(bins, device=s.device)[None] + 0.5) / bins * (hi - lo)[:, None]
    w0 = h.cumsum(1)
    w1 = w0[:, -1:] - w0
    hc = (h * c).cumsum(1)
    m0 = hc / w0.clamp(min=1)
    m1 = (hc[:, -1:] - hc) / w1.clamp(min=1)
    between = (w0 * w1 * (m0 - m1) ** 2)[:, :-1]
    return c.gather(1, between.argmax(1, keepdim=True))[:, 0]


def window_stats(w):
    """Statistics of one 2D window (any scale): dict with q (257 quantiles of the window scaled to its 1..99
    percentiles), bright, noise, grain."""
    np = _np()
    from scipy import ndimage as nd
    w = np.asarray(w, np.float64)
    lo, hi = np.percentile(w, [1, 99])
    s = (w - lo) / max(hi - lo, 1e-6)
    q = np.quantile(s, np.linspace(0, 1, NQ))
    bright = float((s > otsu(s)).mean())
    sd, c = _residual_stats(np, nd, s)
    return {"q": q.astype(np.float32), "bright": bright, "noise": sd, "grain": c}


def reference(slices, masks=None, n=512, seed=0, win=WIN, min_cover=0.98):
    """A reference from real CT SLICES (list of 2D arrays). MASKS (optional, same shapes) mark usable pixels; a
    window is kept when at least MIN_COVER of it is inside. N windows drawn at random (seed SEED). Returns a dict of
    numpy arrays: q (n, 257), bright (n,), noise (n,), grain (n,)."""
    np = _np()
    rng = np.random.default_rng(int(seed))
    cand = []
    for i, s in enumerate(slices):
        H, W = s.shape
        if H < win or W < win:
            continue
        cand.append(i)
    if not cand:
        raise ValueError("ctmatch: no slice holds a full window")
    out = {"q": [], "bright": [], "noise": [], "grain": []}
    tries = 0
    while len(out["q"]) < n and tries < 50 * n:
        tries += 1
        i = cand[int(rng.integers(len(cand)))]
        s = slices[i]
        H, W = s.shape
        y, x = int(rng.integers(0, H - win + 1)), int(rng.integers(0, W - win + 1))
        if masks is not None and masks[i][y:y + win, x:x + win].mean() < min_cover:
            continue
        w = np.asarray(s[y:y + win, x:x + win], np.float64)
        if not np.isfinite(w).all() or np.percentile(w, 99) - np.percentile(w, 1) <= 0:
            continue
        st = window_stats(w)
        for k in out:
            out[k].append(st[k])
    if len(out["q"]) < max(8, n // 4):
        raise ValueError(f"ctmatch: only {len(out['q'])} usable windows")
    return {k: np.asarray(v, np.float32) for k, v in out.items()}


def save(ref, path):
    np = _np()
    np.savez_compressed(path, **ref)


def load(path):
    np = _np()
    z = np.load(path)
    return {k: z[k] for k in z.files}


def summary(ref):
    """Median statistics of a reference (or of tiles measured the same way), for a report."""
    np = _np()
    return {"windows": int(len(ref["q"])), "bright": float(np.median(ref["bright"])),
            "noise": float(np.median(ref["noise"])), "grain": float(np.median(ref["grain"])),
            "q_median": [float(v) for v in np.median(ref["q"], 0)[::32]]}


def tile_stats(tiles, n=None):
    """window_stats over the first N tiles (N, H, W): the same measures as a reference, for comparing simulated
    tiles with real CT."""
    np = _np()
    out = {"q": [], "bright": [], "noise": [], "grain": []}
    for t in tiles[: n or len(tiles)]:
        st = window_stats(t)
        for k in out:
            out[k].append(st[k])
    return {k: np.asarray(v, np.float32) for k, v in out.items()}


def distance(a, b):
    """How far statistics A are from B (dicts from reference or tile_stats): mean absolute difference of the
    median quantile curves (in units of the 1..99 range), and the medians' noise and grain differences."""
    np = _np()
    qa, qb = np.median(a["q"], 0), np.median(b["q"], 0)
    return {"hist": float(np.abs(qa - qb).mean()),
            "noise": float(np.median(a["noise"]) - np.median(b["noise"])),
            "grain": float(np.median(a["grain"]) - np.median(b["grain"])),
            "bright": float(np.median(a["bright"]) - np.median(b["bright"]))}


# torch side ------------------------------------------------------------------------------------------------------

def _blur_kernel(torch, sigma, device):
    r = max(1, int(math.ceil(3 * sigma)))
    t = torch.arange(-r, r + 1, device=device, dtype=torch.float32)
    k = torch.exp(-t * t / (2 * sigma * sigma))
    return k / k.sum(), r


def _blur(torch, F, x, sigma):
    """Separable Gaussian blur of (B, H, W) by a per-call scalar sigma."""
    if sigma <= 0.05:
        return x
    k, r = _blur_kernel(torch, sigma, x.device)
    y = F.conv2d(F.pad(x[:, None], (r, r, 0, 0), mode="reflect"), k.view(1, 1, 1, -1))
    y = F.conv2d(F.pad(y, (0, 0, r, r), mode="reflect"), k.view(1, 1, -1, 1))
    return y[:, 0]


# lag-1 correlation of the residual (minus a sigma 1.5 blur) of white noise blurred by sigma s, measured on 256 px
# fields (seed 0, 25 Nov 2026); grain_sigma interpolates the inverse
GRAIN_TABLE = ((0.0, -0.25), (0.3, -0.093), (0.5, 0.112), (0.7, 0.402), (0.9, 0.561), (1.1, 0.656), (1.4, 0.752),
               (1.8, 0.831))


# grain of kit.hardcases physics tiles after a Gaussian blur of sigma b (30 tiles, seed 3, 25 Nov 2026): the blur
# that brings a tile's own grain to a reference window's grain, before any noise is added
SIM_BLUR_TABLE = ((0.0, 0.452), (0.5, 0.575), (0.7, 0.725), (0.9, 0.77), (1.1, 0.801))


def _interp_inverse(t, c):
    c = float(c)
    if c <= t[0][1]:
        return t[0][0]
    for (s0, c0), (s1, c1) in zip(t, t[1:]):
        if c <= c1:
            return s0 + (s1 - s0) * (c - c0) / (c1 - c0)
    return t[-1][0]


def blur_sigma(c):
    """The blur that brings a simulated tile's grain to C (clamped to SIM_BLUR_TABLE)."""
    return _interp_inverse(SIM_BLUR_TABLE, c)


def grain_sigma(c):
    """The blur sigma whose noise residual has lag-1 correlation C (clamped to the table)."""
    return _interp_inverse(GRAIN_TABLE, c)


def apply(x, ref, gen=None, p=0.8, k=16, noise=True, tol=0.15):
    """Match a batch X (B, H, W) torch float grey values (any scale) to random reference windows; returns grey values
    0..255 (float). GEN: a torch.Generator (CPU) for reproducible draws. P: share of samples matched (the rest are
    only rescaled to 0..255 by their 1..99 percentiles). K: candidates by nearest bright fraction. TOL: the quantile
    map is skipped (blur and noise only) when the chosen window's bright fraction differs from the tile's by more,
    so a tile of mostly air is never painted with a crowded window's grey values."""
    import torch
    import torch.nn.functional as F
    B, H, W = x.shape
    dev = x.device
    x = x.float()
    flat = x.reshape(B, -1)
    sub = flat[:, ::7]
    q = torch.quantile(sub, torch.tensor([0.01, 0.99], device=dev), dim=1)
    s = (x - q[0][:, None, None]) / (q[1] - q[0] + 1e-6)[:, None, None]
    sf = s.reshape(B, -1)
    bright = (sf > _otsu_t(torch, sf)[:, None]).float().mean(1)
    rq = torch.as_tensor(ref["q"], device=dev)
    rb = torch.as_tensor(ref["bright"], device=dev)
    rn = torch.as_tensor(ref["noise"], dtype=torch.float32)
    rg = torch.as_tensor(ref["grain"], dtype=torch.float32)
    out = s.clone()
    pick = torch.rand(B, generator=gen) < p
    kk = min(int(k), len(rb))
    for i in range(B):
        if not bool(pick[i]):
            continue
        near = torch.topk(-(rb - bright[i]).abs(), kk).indices
        j = int(near[int(torch.randint(kk, (1,), generator=gen))])
        xi = s[i:i + 1]
        if noise:
            xi = _blur(torch, F, xi, blur_sigma(float(rg[j])))
            r = xi - _blur(torch, F, xi, SIG_RES)
            have = float(r.std())
            want = float(rn[j])
            if want > have:
                sig = grain_sigma(float(rg[j]))
                z = torch.randn((1, H, W), generator=gen).to(dev)
                z = _blur(torch, F, z, sig)
                zr = z - _blur(torch, F, z, SIG_RES)
                z = z * (math.sqrt(want * want - have * have) / (float(zr.std()) + 1e-8))
                xi = xi + z
        if abs(float(rb[j]) - float(bright[i])) > tol:
            out[i] = xi[0]
            continue
        # rank-preserving quantile map onto the reference window's histogram
        v = xi.reshape(-1)
        order = torch.argsort(v)
        ranks = torch.empty_like(order)
        ranks[order] = torch.arange(v.numel(), device=dev)
        u = ranks.float() / max(1, v.numel() - 1) * (rq.shape[1] - 1)
        lo = u.floor().long().clamp(0, rq.shape[1] - 1)
        hi = (lo + 1).clamp(max=rq.shape[1] - 1)
        f = u - lo.float()
        m = rq[j][lo] * (1 - f) + rq[j][hi] * f
        out[i] = m.reshape(H, W)
    return (out.clamp(-0.25, 1.25) * 204 + 25.5).clamp(0, 255)
