"""kit.sheethug: sheet-hugging surfaces through pressed and touching sheets, trained on synthetic fused contacts.

Tracers merge neighbouring windings where two sheets are pressed together. Earlier simulated contacts (four
simulators, October 2026) taught local nets a cue real scans lack: the merged
band's extra width or a dark line between the sheets. Real pressed bands are about as wide as one sheet (median 7.75
voxels at 9.362 um, IQR 5 to 14.6, against 6.25 apart), with a shallow dip, and 90 to 93 percent of contact area
keeps a free face: the evidence of which sheet is which lies outside the contact.

This module makes 3D blocks of sheet stacks whose contacts are fused islands with those properties (zero gap, both
sheets thinned, band width drawn so it does not mark a contact, no forced dark line), trains a small two-scale 3D
net (a 64^3 local crop plus a 256^3 context box at a quarter of the resolution) to predict papyrus, each sheet's
centre surface and the interface between touching sheets, and scores centre surfaces inside fused zones, so a model
that uses context can be told apart from the same model without it.

    python -m kit.sheethug block OUT.npz --seed S [--shape 192,192,192]
    python -m kit.sheethug bank DIR --n N --seed S [--workers W]
    python -m kit.sheethug train DIR OUT.pt --arm wide|local --seed S [--steps N] [--device cpu|cuda|mps]
    python -m kit.sheethug gate DIR --weights W.pt [W.pt ...] [--out F.json]
    python -m kit.sheethug info

Everything it makes is synthetic; a score on its blocks says nothing about a real scroll (Model output, synthetic
data). Real-data tests go through a frozen preregistration.
"""

import argparse
import json
import math
import os
import sys
import time

VOXEL_UM = 9.362
SHAPE = (192, 192, 192)
LOCAL = 64
CONTEXT = 256
CTX_DS = 4
# Lone sheets: real half-max width 6.25 voxels at 9.362 um where windings are apart (our measurement on
# PHerc0139 public open data, 2.4 um scan in 9.362 um voxels, October 2026); drawn lognormal about THICK_P50.
THICK_P50 = 6.5
THICK_SIGMA = 0.25
THICK_RANGE = (3.5, 12.0)
# Gaps between apart sheets: pitch about 15.5 voxels (hardcases' calibration), so a gap median near 8.5.
GAP_P50 = 8.5
GAP_SIGMA = 0.5
GAP_MIN = 1.5
COMPACT_SHARE = 0.3
COMPACT_GAP = (1.5, 4.0)
# Fused islands: radius in the sheet plane, lognormal median 60 voxels (a contact point sits a median 120 voxels
# from where its windings part, p90 384); thinning KAPPA and overlap C at full fusion (spacing of the two centres =
# C times their mean thickness), drawn so the fused band (about (1 + C) times the thinned thickness) spans the real
# 5 to 14.6 voxel IQR.
ISLAND_P50 = 60.0
ISLAND_RANGE = (20.0, 200.0)
KAPPA = (0.15, 0.5)
OVERLAP = (0.55, 1.0)
NO_ISLAND_SHARE = 0.15
RUN_P = {1: 0.6, 2: 0.25, 3: 0.15}
OUTS = ("papyrus", "centre", "interface")
TOL = 2


class HugError(ValueError):
    pass


def _np():
    import numpy
    return numpy


def _ndi():
    from scipy import ndimage
    return ndimage


# geometry ---------------------------------------------------------------------------------------------------------

def _smooth(rng, shape, sigma):
    np = _np()
    nd = _ndi()
    a = nd.gaussian_filter(rng.normal(size=shape), sigma, mode="wrap")
    return a / (a.std() + 1e-9)


def _rotation(rng, tilt=0.45):
    """Rows: the stack axis u (sheet normal), then v and w. As in a scroll, the normal lies near the axial (y, x)
    plane: its tilt out of that plane is uniform within TILT radians, so axial slices cut sheets across, not along."""
    np = _np()
    t = rng.uniform(-tilt, tilt)
    phi = rng.uniform(0, 2 * math.pi)
    u = np.array([math.sin(t), math.cos(t) * math.cos(phi), math.cos(t) * math.sin(phi)])
    a = np.array([1.0, 0.0, 0.0])
    v = a - u * (a @ u)
    v /= np.linalg.norm(v)
    w = np.cross(u, v)
    ang = rng.uniform(0, 2 * math.pi)
    v, w = math.cos(ang) * v + math.sin(ang) * w, -math.sin(ang) * v + math.cos(ang) * w
    return np.stack([u, v, w])


class Stack:
    """One random sheet stack with fused islands, a function of position. Sheets are offset height fields
    H_k(v, w) along a stack axis u, in a frame that is rotated and smoothly bent; T_k(v, w) is each sheet's local
    thickness and F_k(v, w) its fusion (0 apart, 1 fully fused). Maps are sampled every MAP_STEP voxels."""

    MAP_STEP = 2.0

    def __init__(self, seed, shape=SHAPE):
        np = _np()
        rng = np.random.default_rng([int(seed), 7717])
        self.seed = int(seed)
        self.shape = tuple(int(s) for s in shape)
        self.R = _rotation(rng)
        # bends: a few long sinusoidal displacements (strain kept under about 0.35)
        L = float(max(self.shape))
        self.warp = []
        for _ in range(int(rng.integers(0, 4))):
            lam = rng.uniform(1.5, 4.0) * L
            kdir = rng.normal(size=3)
            kdir /= np.linalg.norm(kdir)
            ddir = rng.normal(size=3)
            ddir /= np.linalg.norm(ddir)
            amp = rng.uniform(0.0, 0.055) * lam
            self.warp.append((2 * math.pi / lam * kdir, ddir, amp, rng.uniform(0, 2 * math.pi)))
        r = 0.5 * math.sqrt(sum(s * s for s in self.shape)) + sum(w[2] for w in self.warp) + 8
        self.r = r
        n = int(math.ceil(2 * r / self.MAP_STEP)) + 3
        self.n = n
        self.compact = rng.random() < COMPACT_SHARE
        wav = _smooth(rng, (n, n), rng.uniform(5, 20)) * rng.uniform(0, 4.0)
        H, T, F = [], [], []
        # sheet thicknesses and gaps
        u = -r - 20.0
        k = 0
        t_prev = None
        gaps, thick = [], []
        while u < r + 20 and k < 200:
            t = float(np.clip(THICK_P50 * math.exp(rng.normal(0, THICK_SIGMA)), *THICK_RANGE))
            thick.append(t)
            if self.compact:
                g = float(rng.uniform(*COMPACT_GAP))
            else:
                g = float(max(GAP_MIN, GAP_P50 * math.exp(rng.normal(0, GAP_SIGMA))))
            gaps.append(g)
            u += t + g
            k += 1
        K = len(thick)
        self.K = K
        Tm = np.stack([t * np.exp(0.12 * _smooth(rng, (n, n), rng.uniform(4, 12))) for t in thick])
        Gm = np.stack([np.maximum(GAP_MIN, g * np.exp(0.3 * _smooth(rng, (n, n), rng.uniform(6, 20))))
                       for g in gaps])
        if self.compact:
            Gm = np.clip(Gm, COMPACT_GAP[0], None)
        # fused islands
        Fm = np.zeros((K, n, n))
        Pm = np.zeros((max(K - 1, 1), n, n))
        self.islands = []
        c = (np.arange(n) - (n - 1) / 2) * self.MAP_STEP
        vv, ww = np.meshgrid(c, c, indexing="ij")
        n_isl = 0 if rng.random() < NO_ISLAND_SHARE else int(rng.integers(1, 4))
        # the sheet nearest u = 0 at the map centre, to put islands inside the block
        cum = -r - 20.0 + np.concatenate([[0.0], np.cumsum(np.array(thick) + np.array(gaps))])
        mid = int(np.argmin(np.abs(cum)))
        kappa_c = np.zeros((K, n, n))
        pairs = []
        for _ in range(n_isl):
            m = int(rng.choice(list(RUN_P), p=list(RUN_P.values())))
            k0 = int(np.clip(mid + rng.integers(-int(0.25 * r / 14), int(0.25 * r / 14) + 1), 0, K - m - 1))
            v0, w0 = rng.uniform(-0.35, 0.35, 2) * min(self.shape)
            Lv = float(np.clip(ISLAND_P50 * math.exp(rng.normal(0, 0.6)), *ISLAND_RANGE))
            Lw = float(np.clip(Lv * math.exp(rng.normal(0, 0.4)), *ISLAND_RANGE))
            th = rng.uniform(0, math.pi)
            a = ((vv - v0) * math.cos(th) + (ww - w0) * math.sin(th)) / Lv
            b = (-(vv - v0) * math.sin(th) + (ww - w0) * math.cos(th)) / Lw
            q2 = a * a + b * b
            # plateau with soft edges, roughened so the island outline is not an ellipse
            rough = 0.25 * _smooth(rng, (n, n), 6)
            B = np.clip(1.6 * np.exp(-0.5 * q2 * (1 + rough)) - 0.3, 0, 1)
            kap = rng.uniform(*KAPPA)
            cc = rng.uniform(*OVERLAP)
            for j in range(k0, k0 + m):
                Fm[j] = np.maximum(Fm[j], B)
                Fm[j + 1] = np.maximum(Fm[j + 1], B)
                kappa_c[j] = np.maximum(kappa_c[j], kap * B)
                kappa_c[j + 1] = np.maximum(kappa_c[j + 1], kap * B)
            self.islands.append({"k0": k0, "run": m, "v0": float(v0), "w0": float(w0), "Lv": Lv, "Lw": Lw,
                                 "kappa": float(kap), "c": float(cc)})
            # pairs of this island: gap goes to the overlap -(1 - c) * mean thickness at full fusion
            for j in range(k0, k0 + m):
                pairs.append((j, B, cc))
                Pm[j] = np.maximum(Pm[j], B)
        Tm = Tm * (1 - kappa_c)
        for j, B, cc in pairs:
            target = -(1 - cc) * (Tm[j] + Tm[j + 1]) / 2
            Gm[j] = np.minimum(Gm[j], (1 - B) * Gm[j] + B * target)
        Hm = np.zeros((K, n, n))
        Hm[0] = -r - 20.0 + wav + Tm[0] / 2
        for j in range(1, K):
            Hm[j] = Hm[j - 1] + (Tm[j - 1] + Tm[j]) / 2 + Gm[j - 1]
        self.H, self.T, self.F = Hm.astype(np.float32), Tm.astype(np.float32), Fm.astype(np.float32)
        self.P = Pm.astype(np.float32)  # fusion of each neighbouring pair (j, j + 1)
        self.wav_amp = float(np.abs(wav).max())

    def frame(self, z, y, x):
        """(u, v, w) of positions z, y, x (block voxel coordinates)."""
        np = _np()
        p = np.stack([np.asarray(z, float), np.asarray(y, float), np.asarray(x, float)], axis=-1)
        p = p - (np.array(self.shape, float) - 1) / 2
        for kv, dv, amp, ph in self.warp:
            p = p + amp * np.sin(p @ kv + ph)[..., None] * dv
        q = p @ self.R.T
        return q[..., 0], q[..., 1], q[..., 2]

    def _map(self, M, v, w):
        nd = _ndi()
        np = _np()
        iv = v / self.MAP_STEP + (self.n - 1) / 2
        iw = w / self.MAP_STEP + (self.n - 1) / 2
        return nd.map_coordinates(M, [iv.ravel(), iw.ravel()], order=1, mode="nearest").reshape(np.shape(v))

    def raster(self, origin=(0, 0, 0), shape=None):
        """Labels and per-voxel fields on the block grid (or a sub-box): owner (uint8, sheet id plus 1, 0 off
        papyrus), e1 (signed position across the owner, -1 to 1 at its faces), e2 (the same for the next nearest
        sheet), centre (bool, the owner's centre surface, about one voxel thick), fusion (float32, the owner's
        fusion 0 to 1)."""
        np = _np()
        shape = tuple(shape or self.shape)
        g = np.meshgrid(*[np.arange(o, o + s, dtype=np.float32) for o, s in zip(origin, shape)], indexing="ij")
        u, v, w = self.frame(*g)
        u, v, w = u.ravel().astype(np.float32), v.ravel().astype(np.float32), w.ravel().astype(np.float32)
        N = u.size
        best = np.full(N, np.inf, np.float32)
        second = np.full(N, np.inf, np.float32)
        e1 = np.zeros(N, np.float32)
        e2 = np.zeros(N, np.float32)
        own = np.zeros(N, np.int32)
        dist = np.zeros(N, np.float32)
        fus = np.zeros(N, np.float32)
        for k in range(self.K):
            reach = float(self.T[k].max()) / 2 * 1.6 + 2
            lo, hi = float(self.H[k].min()) - reach, float(self.H[k].max()) + reach
            sel = np.flatnonzero((u >= lo) & (u <= hi))
            if sel.size == 0:
                continue
            vs, ws = v[sel], w[sel]
            h = self._map(self.H[k], vs, ws)
            t = self._map(self.T[k], vs, ws)
            d = u[sel] - h
            e = d / (t / 2)
            a = np.abs(e)
            b0, s0, e10 = best[sel], second[sel], e1[sel]
            better = a < b0
            sec = (~better) & (a < s0)
            second[sel] = np.where(better, b0, np.where(sec, a, s0))
            e2[sel] = np.where(better, e10, np.where(sec, e, e2[sel]))
            best[sel] = np.where(better, a, b0)
            e1[sel] = np.where(better, e, e10)
            bi = sel[better]
            own[bi] = k + 1
            dist[bi] = d[better]
            if bi.size:
                fus[bi] = self._map(self.F[k], vs[better], ws[better])
        e2 = np.where(np.isfinite(second), e2, 9.0).astype(np.float32)
        best, e1, e2, own, dist, fus = (x.reshape(shape) for x in (best, e1, e2, own, dist, fus))
        inside = best < 1.0
        owner = np.where(inside, own, 0)
        if owner.max() > 255:
            raise HugError("more than 255 sheets in one block")
        centre = inside & (np.abs(dist) <= 0.5)
        return {"owner": owner.astype(np.uint8), "e1": e1, "e2": e2, "centre": centre,
                "fusion": np.where(inside, fus, 0).astype(np.float32)}

    def describe(self):
        return {"seed": self.seed, "shape": list(self.shape), "sheets": self.K, "compact": bool(self.compact),
                "islands": self.islands, "bends": len(self.warp)}


# render -----------------------------------------------------------------------------------------------------------

def render(r, seed):
    """CT (uint8) of a raster R. Each voxel takes the brighter of its two nearest sheets' profiles (two plies, a
    core between them, a soft edge at the faces), so a fused contact shows a dip only as deep as the drawn edge and
    overlap leave, and a lone sheet can show a ply dip of its own. Then gap fill and debris, fibre texture, point
    spread, phase rim, noise and gain, randomized from SEED (as in kit.hardcases.render)."""
    np = _np()
    nd = _ndi()
    rng = np.random.default_rng([int(seed), 104723])
    shape = r["e1"].shape
    po = rng.uniform(0.3, 0.6)
    pw = rng.uniform(0.22, 0.45)
    ga, gb = rng.uniform(0.75, 1.1, 2)
    core = rng.uniform(0.15, 0.7)
    soft = rng.uniform(0.06, 0.25)
    edge0 = rng.uniform(0.95, 1.1)

    def prof(e):
        base = core + ga * np.exp(-((e + po) / pw) ** 2) + gb * np.exp(-((e - po) / pw) ** 2)
        return base / (core + max(ga, gb)) / (1 + np.exp(np.clip(-(edge0 - np.abs(e)) / soft, -60, 60)))

    dens = np.maximum(prof(r["e1"]), prof(r["e2"]))
    big = _smooth(rng, shape, rng.uniform(6, 20))
    fib = nd.gaussian_filter(rng.normal(size=shape), rng.uniform(0.8, 1.6))
    fib /= fib.std() + 1e-9
    dens = dens * np.clip(1 + rng.uniform(0.1, 0.35) * fib + rng.uniform(0.05, 0.2) * big, 0.2, 2.0)
    fill = rng.uniform(0.0, 0.18)
    blobs = nd.gaussian_filter(rng.normal(size=shape), rng.uniform(1.5, 4.0))
    blobs = np.clip(blobs / (blobs.std() + 1e-9) - rng.uniform(0.8, 2.0), 0, None)
    gapv = fill * np.clip(0.6 + 0.4 * big, 0, 2) + rng.uniform(0.0, 0.25) * blobs
    dens = np.maximum(dens, gapv)
    v = nd.gaussian_filter(dens, rng.uniform(0.5, 1.4))
    rim = rng.uniform(0.0, 1.0)
    if rim > 0:
        v = v + rim * (v - nd.gaussian_filter(v, rng.uniform(1.0, 3.0)))
    w = rng.normal(size=shape)
    mixw = rng.dirichlet([1.0, 1.0, 1.0])
    ramp = w - nd.gaussian_filter(w, 1.0)
    corr = nd.gaussian_filter(w, 1.5)
    noise = mixw[0] * w + mixw[1] * ramp / (ramp.std() + 1e-9) + mixw[2] * corr / (corr.std() + 1e-9)
    v = v + rng.uniform(0.04, 0.16) * noise
    v = v * (1 + rng.uniform(0, 0.15) * big)
    lo_air, hi_sheet = rng.uniform(20, 70), rng.uniform(150, 230)
    out = lo_air + (hi_sheet - lo_air) * v
    if rng.random() < 0.3:
        out = 255 * (np.clip(out, 0, 255) / 255) ** rng.uniform(0.7, 1.4)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def interface(owner):
    """Papyrus voxels with a 6-neighbour of another sheet (the face where two sheets touch)."""
    np = _np()
    o = np.asarray(owner)
    out = np.zeros(o.shape, bool)
    for ax in range(o.ndim):
        a = np.swapaxes(o, 0, ax)
        m = np.swapaxes(out, 0, ax)
        diff = (a[1:] != a[:-1]) & (a[1:] > 0) & (a[:-1] > 0)
        m[1:] |= diff
        m[:-1] |= diff
    return out


def block(seed, shape=SHAPE):
    """One synthetic block: dict of ct (uint8), owner (uint8), centre (bool), fusion (float16), interface (bool),
    and its description."""
    np = _np()
    st = Stack(seed, shape)
    r = st.raster()
    ct = render(r, seed)
    return {"ct": ct, "owner": r["owner"], "centre": r["centre"], "fusion": r["fusion"].astype(np.float16),
            "interface": interface(r["owner"]), "info": st.describe()}


def band_widths(b, step=4):
    """Half-max widths are hard to read from labels; this reports each block's labelled band thickness along the
    stack axis instead: run lengths of papyrus along z, split into fused (fusion > 0.5) and apart runs."""
    np = _np()
    o = b["owner"] > 0
    fz = b["fusion"].astype(np.float32) > 0.5
    out = {"apart": [], "fused": []}
    Z = o.shape[0]
    for y in range(0, o.shape[1], step):
        for x in range(0, o.shape[2], step):
            col = o[:, y, x]
            z = 0
            while z < Z:
                if col[z]:
                    z0 = z
                    while z < Z and col[z]:
                        z += 1
                    if z0 > 0 and z < Z:
                        out["fused" if fz[z0:z, y, x].any() else "apart"].append(z - z0)
                else:
                    z += 1
    return {k: (float(np.median(v)) if v else None, len(v)) for k, v in out.items()}


# bank -------------------------------------------------------------------------------------------------------------

def save_block(b, path):
    np = _np()
    tmp = path + ".partial.npz"
    np.savez_compressed(tmp, ct=b["ct"], owner=b["owner"], centre=b["centre"], fusion=b["fusion"],
                        interface=b["interface"], info=np.array(json.dumps(b["info"])))
    os.replace(tmp, path)


def load_block(path):
    np = _np()
    with np.load(path) as z:
        b = {k: z[k] for k in ("ct", "owner", "centre", "fusion", "interface")}
        b["info"] = json.loads(str(z["info"]))
    return b


def _bank_one(args):
    seed, path, shape = args
    if not os.path.exists(path):
        save_block(block(seed, shape), path)
    return path


def bank(dest, n, seed, shape=SHAPE, workers=1, progress=print):
    """N blocks with seeds SEED*100000 + i into DEST/block-SEED-i.npz (skips blocks already written)."""
    os.makedirs(dest, exist_ok=True)
    jobs = [(int(seed) * 100000 + i, os.path.join(dest, f"block-{int(seed)}-{i:04d}.npz"), tuple(shape))
            for i in range(int(n))]
    if workers > 1:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(workers) as pool:
            for i, p in enumerate(pool.imap_unordered(_bank_one, jobs)):
                if progress:
                    progress(f"PROGRESS {i + 1}/{len(jobs)} {os.path.basename(p)}")
    else:
        for i, j in enumerate(jobs):
            _bank_one(j)
            if progress:
                progress(f"PROGRESS {i + 1}/{len(jobs)} {os.path.basename(j[1])}")
    return [j[1] for j in jobs]


# inputs -----------------------------------------------------------------------------------------------------------

def pooled(ct, ds=CTX_DS):
    """CT (uint8 0 to 255, or float 0 to 1) mean pooled by DS after padding each axis to a multiple of DS, and the
    share of real (unpadded) voxels in each cell: (2, Z/DS, Y/DS, X/DS) float32."""
    np = _np()
    v = ct.astype(np.float32) / 255.0 if ct.dtype == np.uint8 else ct.astype(np.float32)
    pad = [(0, (-s) % ds) for s in v.shape]
    val = np.pad(np.ones(v.shape, np.float32), pad)
    v = np.pad(v, pad) * val
    n = [s // ds for s in v.shape]
    pool = lambda x: x.reshape(n[0], ds, n[1], ds, n[2], ds).mean((1, 3, 5))
    pv, pm = pool(v), pool(val)
    return np.stack([np.where(pm > 0, pv / np.maximum(pm, 1e-6), 0.0), pm]).astype(np.float32)


def context_box(pool_, centre, size=CONTEXT, ds=CTX_DS):
    """The SIZE^3 context box centred on CENTRE (z, y, x; each a multiple of DS) cut from POOL_ (the output of
    pooled()), zero outside the volume: (2, SIZE/DS, ...) float32 (pooled CT, share of real voxels)."""
    np = _np()
    n = size // ds
    out = np.zeros((2, n, n, n), np.float32)
    src, dst = [], []
    for c, S in zip(centre, pool_.shape[1:]):
        if int(c) % ds:
            raise HugError(f"context centre {centre} is not on the {ds}-voxel grid")
        a = int(c) // ds - n // 2
        lo, hi = max(0, a), min(S, a + n)
        if hi <= lo:
            return out
        src.append(slice(lo, hi))
        dst.append(slice(lo - a, hi - a))
    out[(slice(None),) + tuple(dst)] = pool_[(slice(None),) + tuple(src)]
    return out


def targets(b, sl):
    np = _np()
    nd = _ndi()
    o = b["owner"][sl]
    cen = nd.binary_dilation(b["centre"][sl], iterations=1) & (o > 0)
    return np.stack([o > 0, cen, b["interface"][sl]]).astype(np.float32)


class Sampler:
    """Random training samples from a bank: a LOCAL^3 crop (half of them centred on a fused voxel when the block
    has one), its context box, and targets. ARM 'local' zeroes the context input."""

    def __init__(self, paths, arm, seed, fused_share=0.5):
        np = _np()
        if arm not in ("wide", "local"):
            raise HugError(f"unknown arm {arm!r}")
        self.blocks = [load_block(p) for p in paths]
        self.arm = arm
        self.rng = np.random.default_rng([int(seed), 99])
        self.fused_share = fused_share
        self.fused_idx = []
        self.pools = [pooled(b["ct"]) for b in self.blocks]
        for b in self.blocks:
            f = b["fusion"].astype(np.float32) > 0.5
            self.fused_idx.append(np.argwhere(f[::2, ::2, ::2]) * 2 if f.any() else None)

    def one(self):
        np = _np()
        r = self.rng
        i = int(r.integers(len(self.blocks)))
        b = self.blocks[i]
        S = np.array(b["ct"].shape)
        h = LOCAL // 2
        fi = self.fused_idx[i]
        if fi is not None and len(fi) and r.random() < self.fused_share:
            c = fi[int(r.integers(len(fi)))] + r.integers(-8, 9, 3)
        else:
            c = r.integers(h, S - h + 1)
        c = np.clip(c, h, S - h)
        c = (c // CTX_DS) * CTX_DS
        c = np.clip(c, h, S - h)
        sl = tuple(slice(int(a) - h, int(a) + h) for a in c)
        x = b["ct"][sl][None].astype(np.float32) / 255.0
        y = targets(b, sl)
        if self.arm == "wide":
            cx = context_box(self.pools[i], c)
        else:
            n = CONTEXT // CTX_DS
            cx = np.zeros((2, n, n, n), np.float32)
        # flips and axis swaps of y and x (z stays the scroll axis), the same for all inputs
        k = int(r.integers(4))
        for ax in (1, 2, 3):
            if r.random() < 0.5:
                x, y, cx = (np.flip(a, ax) for a in (x, y, cx))
        if k % 2:
            x, y, cx = (np.swapaxes(a, 2, 3) for a in (x, y, cx))
        # intensity: gain, offset, gamma
        g = r.uniform(0.8, 1.25)
        o = r.uniform(-0.1, 0.1)
        gam = r.uniform(0.8, 1.25)
        x = np.clip(np.clip(x, 0, 1) ** gam * g + o, -0.5, 1.5)
        cx = cx.copy()
        cx[0] = np.clip(np.clip(cx[0], 0, 1) ** gam * g + o, -0.5, 1.5) * (cx[1] > 0)
        return np.ascontiguousarray(x), np.ascontiguousarray(cx), np.ascontiguousarray(y)

    def batch(self, n):
        np = _np()
        xs, cs, ys = zip(*(self.one() for _ in range(n)))
        return np.stack(xs), np.stack(cs), np.stack(ys)


# model ------------------------------------------------------------------------------------------------------------

def make_net(width=16):
    """Two-scale 3D U-Net. Local path: LOCAL^3 crop, levels at strides 1, 2, 4, 8. Context path: the context box at
    stride CTX_DS (64^3), encoded to stride 32 and decoded to stride 8; its centre (the local crop's footprint) is
    upsampled to the local path's stride-4 level and concatenated there. Outputs 3 logits (OUTS) at full
    resolution."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    def blk(i, o):
        return nn.Sequential(nn.Conv3d(i, o, 3, padding=1), nn.GroupNorm(4, o), nn.GELU(),
                             nn.Conv3d(o, o, 3, padding=1), nn.GroupNorm(4, o), nn.GELU())

    w = width

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.e1, self.e2, self.e3, self.e4 = blk(1, w), blk(w, 2 * w), blk(2 * w + 2 * w, 4 * w), blk(4 * w, 4 * w)
            self.d3, self.d2, self.d1 = blk(8 * w, 4 * w), blk(6 * w, 2 * w), blk(3 * w, w)
            self.head = nn.Conv3d(w, len(OUTS), 1)
            self.c1, self.c2, self.c3, self.c4 = blk(2, w), blk(w, 2 * w), blk(2 * w, 2 * w), blk(2 * w, 2 * w)
            self.cd = blk(4 * w, 2 * w)

        def forward(self, x, cx):
            # context: 64^3 at stride 4 -> 32 (s8) -> 16 (s16) -> 8 (s32), back up to s8
            c1 = self.c1(cx)
            c2 = self.c2(F.max_pool3d(c1, 2))
            c3 = self.c3(F.max_pool3d(c2, 2))
            c4 = self.c4(F.max_pool3d(c3, 2))
            u = F.interpolate(c4, scale_factor=4, mode="trilinear", align_corners=False)
            c2 = self.cd(torch.cat([c2, u], 1))
            n = c2.shape[-1]
            m = LOCAL // (2 * CTX_DS)  # the local crop's footprint at stride 8
            a = (n - m) // 2
            cc = c2[..., a:a + m, a:a + m, a:a + m]
            cc = F.interpolate(cc, scale_factor=2, mode="trilinear", align_corners=False)
            e1 = self.e1(x)
            e2 = self.e2(F.max_pool3d(e1, 2))
            e3 = self.e3(torch.cat([F.max_pool3d(e2, 2), cc], 1))
            e4 = self.e4(F.max_pool3d(e3, 2))
            d3 = self.d3(torch.cat([F.interpolate(e4, scale_factor=2, mode="trilinear", align_corners=False), e3], 1))
            d2 = self.d2(torch.cat([F.interpolate(d3, scale_factor=2, mode="trilinear", align_corners=False), e2], 1))
            d1 = self.d1(torch.cat([F.interpolate(d2, scale_factor=2, mode="trilinear", align_corners=False), e1], 1))
            return self.head(d1)

    return Net()


def pick_device(device="auto"):
    import torch
    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def train(paths, arm, seed=1, steps=3000, batch=4, lr=2e-3, device="auto", width=16, progress=print, log_every=50):
    """Train one arm on bank PATHS; the last step is kept (nothing selects on held-out blocks). Loss: BCE on the
    three outputs, centre and interface with positive weight 3, plus a soft Dice on centre."""
    import torch
    import torch.nn.functional as F
    np = _np()
    torch.manual_seed(int(seed))
    dev = pick_device(device)
    net = make_net(width).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=int(steps),
                                                pct_start=max(0.05, 3.0 / max(1, int(steps))))
    smp = Sampler(paths, arm, seed)
    pw = torch.tensor([1.0, 3.0, 3.0], device=dev).view(1, 3, 1, 1, 1)
    t0 = time.time()
    hist = []
    for step in range(int(steps)):
        x, cx, y = (torch.from_numpy(a).to(dev) for a in smp.batch(batch))
        logit = net(x, cx)
        bce = F.binary_cross_entropy_with_logits(logit, y, pos_weight=pw)
        p = torch.sigmoid(logit[:, 1])
        t = y[:, 1]
        dice = 1 - (2 * (p * t).sum() + 1) / (p.sum() + t.sum() + 1)
        loss = bce + 0.5 * dice
        if not torch.isfinite(loss):
            raise HugError(f"non-finite loss at step {step}")
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        sched.step()
        hist.append(float(loss))
        if progress and (step + 1) % log_every == 0:
            progress(f"PROGRESS {step + 1}/{steps} loss {np.mean(hist[-log_every:]):.4f} "
                     f"{(time.time() - t0) / (step + 1):.2f} s/step")
    net.eval()
    return net.cpu(), {"arm": arm, "seed": int(seed), "steps": int(steps), "batch": int(batch), "lr": lr,
                       "width": int(width), "device": dev, "seconds": round(time.time() - t0, 1),
                       "final_loss": float(np.mean(hist[-50:]))}


def save_net(net, meta, path):
    import torch
    tmp = path + ".partial"
    torch.save({"state": net.state_dict(), "meta": meta}, tmp)
    os.replace(tmp, path)


def load_net(path, device="cpu"):
    import torch
    d = torch.load(path, map_location=device, weights_only=False)
    net = make_net(d["meta"].get("width", 16))
    net.load_state_dict(d["state"])
    net.eval()
    return net.to(device), d["meta"]


def predict(net, ct, arm, device="cpu", stride=48, batch=4):
    """Probabilities (3, Z, Y, X) float32 over a whole volume CT (uint8 or float 0 to 1), by LOCAL^3 tiles at
    STRIDE with a cosine-squared blend; ARM 'local' feeds zero context. Volumes smaller than LOCAL are padded."""
    import torch
    np = _np()
    v = ct.astype(np.float32) / 255.0 if ct.dtype == np.uint8 else ct.astype(np.float32)
    pad = [(0, max(LOCAL, s + (-s) % CTX_DS) - s) for s in v.shape]
    v = np.pad(v, pad, mode="reflect") if any(p[1] for p in pad) else v
    pv = pooled(v)
    if any(p[1] for p in pad):
        # cells made only of reflected padding count as outside the volume
        real = np.zeros(v.shape, np.float32)
        real[:ct.shape[0], :ct.shape[1], :ct.shape[2]] = 1
        pv[1] = pooled(real)[0]
        pv[0] = np.where(pv[1] > 0, pv[0], 0)
    Z, Y, X = v.shape
    out = np.zeros((len(OUTS), Z, Y, X), np.float32)
    wsum = np.zeros((Z, Y, X), np.float32)
    w1 = np.sin(np.linspace(0, math.pi, LOCAL + 2)[1:-1]) ** 2
    wt = (w1[:, None, None] * w1[None, :, None] * w1[None, None, :]).astype(np.float32)
    if stride % CTX_DS:
        raise HugError(f"stride {stride} is not a multiple of {CTX_DS}")
    starts = [sorted(set(list(range(0, S - LOCAL + 1, stride)) + [S - LOCAL])) for S in (Z, Y, X)]
    coords = [(a, b, c) for a in starts[0] for b in starts[1] for c in starts[2]]
    n = CONTEXT // CTX_DS
    with torch.no_grad():
        for i in range(0, len(coords), batch):
            grp = coords[i:i + batch]
            xs = np.stack([v[a:a + LOCAL, b:b + LOCAL, c:c + LOCAL][None] for a, b, c in grp])
            if arm == "wide":
                cs = np.stack([context_box(pv, (a + LOCAL // 2, b + LOCAL // 2, c + LOCAL // 2)) for a, b, c in grp])
            else:
                cs = np.zeros((len(grp), 2, n, n, n), np.float32)
            p = torch.sigmoid(net(torch.from_numpy(xs).to(device), torch.from_numpy(cs).to(device))).cpu().numpy()
            for (a, b, c), pp in zip(grp, p):
                out[:, a:a + LOCAL, b:b + LOCAL, c:c + LOCAL] += pp * wt
                wsum[a:a + LOCAL, b:b + LOCAL, c:c + LOCAL] += wt
    out /= np.maximum(wsum, 1e-6)
    return out[:, :ct.shape[0], :ct.shape[1], :ct.shape[2]]


# scoring ----------------------------------------------------------------------------------------------------------
# Scoring is in 2D axial slices, the same way for synthetic blocks and real labelled cubes: truth lines are the
# skeleton of the labelled papyrus with the boundaries between different sheets removed (truth_lines below,
# Synthetic-Slices' benchmark rule), predicted lines are Synthetic-Slices' NMS 2 of a centre probability, and the
# contact zone is labelled papyrus within CONTACT_R pixels of a pixel of another sheet. Plain F1 at 2 px cannot see a
# merge when two touching sheets' lines sit 3 to 4 px apart (one line between them lies within 2 px of both), so the
# primary score assigns every predicted pixel to the sheet of its nearest truth line, and a truth pixel counts as
# recalled only if a predicted pixel assigned to its own sheet lies within the tolerance (split recall).

CONTACT_R = 3
SLICE_STEP = 16
SLICE_MARGIN = 8


def contact_zone(owner, r=CONTACT_R):
    """Labelled papyrus pixels within R pixels (8-connected steps) of a pixel of another sheet, in a 2D slice."""
    np = _np()
    nd = _ndi()
    o = np.asarray(owner)
    face = interface(o)
    if not face.any():
        return np.zeros(o.shape, bool)
    return nd.binary_dilation(face, structure=np.ones((3, 3), bool), iterations=r) & (o > 0)


def truth_lines(owner):
    """True centre lines of a labelled slice: skeleton of the papyrus with the boundaries between different sheets
    removed, so touching sheets give separate lines (the rule of Synthetic-Slices' benchmark truth)."""
    np = _np()
    from skimage.morphology import skeletonize
    lab = np.asarray(owner)
    P = np.pad(lab, 1, mode="edge")
    bord = np.zeros(lab.shape, bool)
    H, W = lab.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                nb = P[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
                bord |= (nb != lab) & (nb > 0) & (lab > 0)
    return skeletonize((lab > 0) & ~bord)


def ridge_map(img, sigmas=(1.0, 1.5, 2.0, 2.5, 3.0)):
    """Bright-ridge response of a 2D image (skimage's Sato filter, max over SIGMAS): the no-learning baseline."""
    np = _np()
    from skimage.filters import sato
    return sato(np.asarray(img, np.float64), sigmas=sigmas, black_ridges=False).astype(np.float32)


def nms_lines(prob, mask):
    """Synthetic-Slices' NMS 2 lines of PROB inside MASK (bool); a non-finite map raises HugError."""
    np = _np()
    if not np.isfinite(np.asarray(prob, np.float64)).all():
        raise HugError("non-finite map refused before scoring")
    try:
        from synthetic_slices.extract import extract_lines
    except ImportError as e:
        raise HugError("needs the synthetic_slices package (pip install --no-deps "
                       "git+https://github.com/vincentl065/Synthetic-Slices@bf8d26f502ed38c188c409d7f3011a7a11c4cf89)") from e
    return extract_lines(np.asarray(prob, np.float32), mask) > 0


def split_counts(pred, ref_lines, owner, mask, tol=2):
    """Counts inside MASK: tp_p and n_p (predicted pixels within TOL of any truth line), n_r (truth line pixels),
    tp_r (truth pixels within TOL of any predicted pixel) and tp_s (truth pixels within TOL of a predicted pixel
    assigned to the same sheet, each predicted pixel taking the sheet of its nearest truth line pixel). Distances are
    TOL steps of the 4-connected dilation (Synthetic-Slices' F1 tolerance)."""
    np = _np()
    nd = _ndi()
    p = np.asarray(pred, bool) & mask
    r = np.asarray(ref_lines, bool) & mask
    out = {"tp_p": 0, "n_p": int(p.sum()), "tp_r": 0, "n_r": int(r.sum()), "tp_s": 0}
    if not r.any() or not p.any():
        return out
    rall = np.asarray(ref_lines, bool)
    rd = nd.binary_dilation(rall, iterations=tol)
    pd = nd.binary_dilation(p, iterations=tol)
    out["tp_p"] = int((p & rd).sum())
    out["tp_r"] = int((r & pd).sum())
    _, idx = nd.distance_transform_edt(~rall, return_indices=True)
    sheet_of = np.asarray(owner)[idx[0], idx[1]]
    lab = np.where(rall, np.asarray(owner), 0)
    for k in np.unique(lab[r]):
        pk = p & (sheet_of == k)
        if pk.any():
            out["tp_s"] += int((r & (lab == k) & nd.binary_dilation(pk, iterations=tol)).sum())
    return out


def scores_of(c):
    """Precision, recall, split recall, F1 and split F1 from pooled counts."""
    prec = c["tp_p"] / max(1, c["n_p"])
    rec = c["tp_r"] / max(1, c["n_r"])
    srec = c["tp_s"] / max(1, c["n_r"])
    f = lambda a, b: float(2 * a * b / max(1e-9, a + b))
    return {"precision": prec, "recall": rec, "split_recall": srec, "f1": f(prec, rec), "split_f1": f(prec, srec)}


def slice_eval(prob2d, owner2d, foot2d, tol=2):
    """One axial slice: counts in the contact zone ('contact') and the whole footprint ('all')."""
    np = _np()
    lines = truth_lines(owner2d) & foot2d
    pred = nms_lines(prob2d, foot2d)
    cz = contact_zone(owner2d) & foot2d
    return {"contact": split_counts(pred, lines, owner2d, cz, tol),
            "all": split_counts(pred, lines, owner2d, foot2d, tol)}


def control_probs(owner2d):
    """Control maps of a slice: 'oracle' (truth lines), 'merged' (skeleton of the papyrus with sheet ids dropped:
    a perfect papyrus segmenter that never splits touching sheets)."""
    np = _np()
    from skimage.morphology import skeletonize
    return {"oracle": truth_lines(owner2d).astype(np.float32),
            "merged": skeletonize(np.asarray(owner2d) > 0).astype(np.float32)}


def axial_slices(Z, step=SLICE_STEP, margin=SLICE_MARGIN):
    return list(range(margin, Z - margin, step))


def pool(counts):
    tot = {}
    for c in counts:
        for z, d in c.items():
            t = tot.setdefault(z, {k: 0 for k in d})
            for k in d:
                t[k] += d[k]
    return {z: dict(d, **scores_of(d)) for z, d in tot.items()}


def gate(paths, weights, device="cpu", progress=print, ridge=True):
    """Score each weights file, the ridge filter and the controls on held-out blocks PATHS, in axial slices every
    SLICE_STEP voxels. Returns {name: {arm, seed, zones}} with pooled counts and scores for zones 'contact' and
    'all'. Controls: 'control-oracle' (truth lines), 'control-merged' (papyrus skeleton without sheet ids) and
    'control-flip' (the first weights file's map mirrored left to right, so its lines fall on truth only by
    chance). A non-finite map raises HugError."""
    np = _np()
    nets = [(os.path.basename(w),) + load_net(w, device) for w in weights]
    names = [n for n, _, _ in nets] + (["ridge-sato"] if ridge else []) + \
        ["control-oracle", "control-merged", "control-flip"]
    counts = {n: [] for n in names}
    for i, p in enumerate(paths):
        b = load_block(p)
        Z, Y, X = b["ct"].shape
        foot = np.zeros((Y, X), bool)
        foot[SLICE_MARGIN:-SLICE_MARGIN, SLICE_MARGIN:-SLICE_MARGIN] = True
        zs = axial_slices(Z)
        probs = {}
        for j, (name, net, meta) in enumerate(nets):
            pr = predict(net, b["ct"], meta["arm"], device)[1]
            if not np.isfinite(pr).all():
                raise HugError(f"{name}: non-finite probabilities on {p}")
            probs[name] = pr
        for z in zs:
            o = b["owner"][z]
            maps = {n: probs[n][z] for n, _, _ in nets}
            if ridge:
                maps["ridge-sato"] = ridge_map(b["ct"][z].astype(np.float32) / 255.0)
            cp = control_probs(o)
            maps["control-oracle"] = cp["oracle"]
            maps["control-merged"] = cp["merged"]
            if nets:
                m0 = maps[nets[0][0]]
                maps["control-flip"] = np.ascontiguousarray(m0[:, ::-1])
            for n, m in maps.items():
                counts[n].append(slice_eval(m, o, foot))
        if progress:
            progress(f"PROGRESS {i + 1}/{len(paths)} {os.path.basename(p)}")
    meta_of = {n: m for n, _, m in nets}
    return {n: {"arm": meta_of.get(n, {}).get("arm", n), "seed": meta_of.get(n, {}).get("seed"),
                "zones": pool(c)} for n, c in counts.items() if c}


# command line -----------------------------------------------------------------------------------------------------

def build_parser(ap=None):
    ap = ap or argparse.ArgumentParser(prog="python -m kit.sheethug", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("block", help="one synthetic block to an .npz")
    p.add_argument("out")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--shape", default=",".join(map(str, SHAPE)))
    p = sub.add_parser("bank", help="N blocks into a folder")
    p.add_argument("dest")
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--shape", default=",".join(map(str, SHAPE)))
    p.add_argument("--workers", type=int, default=1)
    p = sub.add_parser("train", help="train one arm on a bank folder")
    p.add_argument("bank")
    p.add_argument("out")
    p.add_argument("--arm", choices=("wide", "local"), required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--steps", type=int, default=3000)
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--width", type=int, default=16)
    p.add_argument("--device", default="auto")
    p = sub.add_parser("gate", help="score weights on a bank folder of held-out blocks")
    p.add_argument("bank")
    p.add_argument("--weights", nargs="+", required=True)
    p.add_argument("--device", default="auto")
    p.add_argument("--out")
    sub.add_parser("info", help="constants as JSON")
    return ap


def _blocks_in(d):
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.startswith("block-") and f.endswith(".npz"))


def main(argv=None):
    a = build_parser().parse_args(argv)
    shape = tuple(int(s) for s in a.shape.split(",")) if hasattr(a, "shape") else None
    if a.cmd == "block":
        b = block(a.seed, shape)
        save_block(b, a.out)
        print(json.dumps(b["info"]))
    elif a.cmd == "bank":
        bank(a.dest, a.n, a.seed, shape, a.workers)
    elif a.cmd == "train":
        net, meta = train(_blocks_in(a.bank), a.arm, a.seed, a.steps, a.batch, device=a.device, width=a.width)
        meta["bank"] = os.path.abspath(a.bank)
        save_net(net, meta, a.out)
        print(json.dumps(meta))
    elif a.cmd == "gate":
        res = gate(_blocks_in(a.bank), a.weights, pick_device(a.device))
        print(json.dumps({k: {z: [round(d["f1"], 4), round(d["split_f1"], 4)] for z, d in v["zones"].items()}
                          for k, v in res.items()}))
        if a.out:
            tmp = a.out + ".partial"
            with open(tmp, "w") as f:
                json.dump(res, f, indent=1)
            os.replace(tmp, a.out)
    elif a.cmd == "info":
        print(json.dumps({"voxel_um": VOXEL_UM, "shape": SHAPE, "local": LOCAL, "context": CONTEXT,
                          "ctx_ds": CTX_DS, "outs": OUTS, "tol": TOL, "contact_r": CONTACT_R, "slice_step": SLICE_STEP, "thick_p50": THICK_P50,
                          "island_p50": ISLAND_P50, "kappa": KAPPA, "overlap": OVERLAP}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
