#!/usr/bin/env python3
"""simgan: a learned sim-to-real texture for ScrollSim tiles, trained on real CT gray values only.

kit.hardcases renders sheets with hand-made physics; kit.simreal and kit.simcritic show that classifiers still tell
those tiles from real CT windows, whatever the render knobs. simgan learns the rest: a small U-Net G maps a physics
tile (plus a noise channel) to a residual added to it, trained against a patch discriminator D on unlabelled real
windows (least-squares GAN), with a structure loss that keeps the sheet-scale image (Gaussian blur, SIGMA px) of G's
output equal to the input's, so sheets stay where the layout put them and the exact labels still hold. Optional
terms: the log radial spectrum and grain statistics of the real windows (spec_w, grain_w, hi_w), and steering of
G's residual along the local sheet direction (oriented: full, band:S, mix:A). Real windows are normalized per window
to their 1st..99th percentiles, the same per-window view line detectors take.

Checks (each can fail): `cnn_auc`, a fresh small CNN trained to tell real from realized windows, scored on held-out
halves; `line_keep`, a ridge filter's F1 at 2 px of the realized tile against the layout's own lines, beside the
same for the physics tile (G must not move or erase sheets). For a realism verdict use kit.simscore (SRS-1), which
refits its critics on every call and refuses real slices the generator trained on.

The real side holds gray values only, never labels. Never train G on CT a test will score on: those windows would
then be part of the generator. The command line trains on the even slices of an SRS-1 reference (R343-v1, public
PHerc0343P CT) so the odd slices stay free for kit.simscore.

    G = simgan.train(sim_uint8, real_unit, steps=6000, device="cuda", oriented="band:4")
    out = simgan.realize(G, sim_uint8, device="cuda")       # uint8, same shape, lines unchanged

    python -m kit.simgan real R343.npz REAL.npz              even-slice training windows from a reference npz
    python -m kit.simgan tiles TILES.npz [--n 4000]          Hard Cases physics tiles under the R4 preset
    python -m kit.simgan train TILES.npz REAL.npz G.safetensors [--steer band:4] [--steps 6000] [--device cuda]
    python -m kit.simgan realize G.safetensors TILES.npz OUT.npz [--n 2000]
    python -m kit.simgan linekeep OUT.npz [--n 64]
"""
import argparse
import json
import math
import os
import sys
import time

SIGMA = 2.0
LAM = 10.0
LO, HI = -0.25, 1.25         # unit range kept when writing uint8


class GanError(ValueError):
    pass


def _torch():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    return torch, nn, F


def unit(w):
    """A 2D window scaled to its own 1st..99th percentiles (numpy float32)."""
    import numpy as np
    w = np.asarray(w, np.float32)
    lo, hi = np.percentile(w, [1, 99])
    return (w - lo) / max(float(hi - lo), 1e-6)


def unit_t(x):
    """Torch (B, 1, H, W): each sample scaled to its own 1st..99th percentiles."""
    torch, _, _ = _torch()
    q = torch.quantile(x.flatten(1)[:, ::5].float(), torch.tensor([0.01, 0.99], device=x.device), dim=1)
    return (x - q[0][:, None, None, None]) / (q[1] - q[0] + 1e-6)[:, None, None, None]


def build(width=32, d_width=64, oriented=False):
    torch, nn, F = _torch()

    def block(a, b):
        return nn.Sequential(nn.Conv2d(a, b, 3, padding=1), nn.GroupNorm(8, b), nn.SiLU(),
                             nn.Conv2d(b, b, 3, padding=1), nn.GroupNorm(8, b), nn.SiLU())

    class Gen(nn.Module):
        def __init__(s, c=width):
            super().__init__()
            s.e1, s.e2, s.e3 = block(2, c), block(c, 2 * c), block(2 * c, 4 * c)
            s.u2, s.d2 = nn.ConvTranspose2d(4 * c, 2 * c, 2, 2), block(4 * c, 2 * c)
            s.u1, s.d1 = nn.ConvTranspose2d(2 * c, c, 2, 2), block(2 * c, c)
            s.o = nn.Conv2d(c, 1, 1)
            nn.init.zeros_(s.o.weight)
            nn.init.zeros_(s.o.bias)
            s.oriented = steer_mode(oriented)

        def forward(s, x, z):
            a = s.e1(torch.cat([x, z], 1))
            b = s.e2(F.avg_pool2d(a, 2))
            c = s.e3(F.avg_pool2d(b, 2))
            b = s.d2(torch.cat([s.u2(c), b], 1))
            a = s.d1(torch.cat([s.u1(b), a], 1))
            r = s.o(a)
            return x + steer_residual(r, x, s.oriented)

    sn = nn.utils.spectral_norm

    class Disc(nn.Module):
        def __init__(s, c=64):
            super().__init__()
            s.net = nn.Sequential(sn(nn.Conv2d(1, c, 4, 2, 1)), nn.LeakyReLU(0.2),
                                  sn(nn.Conv2d(c, 2 * c, 4, 2, 1)), nn.LeakyReLU(0.2),
                                  sn(nn.Conv2d(2 * c, 4 * c, 4, 2, 1)), nn.LeakyReLU(0.2),
                                  sn(nn.Conv2d(4 * c, 4 * c, 3, 1, 1)), nn.LeakyReLU(0.2),
                                  sn(nn.Conv2d(4 * c, 1, 3, 1, 1)))

        def forward(s, x):
            return s.net(x)

    return Gen(), Disc(d_width)


def blur_t(x, sigma=SIGMA):
    torch, _, F = _torch()
    r = int(math.ceil(3 * sigma))
    t = torch.arange(-r, r + 1, dtype=x.dtype, device=x.device)
    g = torch.exp(-t * t / (2 * sigma * sigma))
    g = (g / g.sum())
    x = F.conv2d(F.pad(x, (0, 0, r, r), mode="reflect"), g.view(1, 1, -1, 1))
    return F.conv2d(F.pad(x, (r, r, 0, 0), mode="reflect"), g.view(1, 1, 1, -1))


def radial_profile_t(x, bins=32):
    """Log mean Fourier amplitude of X (B, 1, H, W) in BINS radial bands up to Nyquist, averaged over the batch."""
    torch, _, _ = _torch()
    h, w = x.shape[-2:]
    fy = torch.fft.fftfreq(h, device=x.device)[:, None]
    fx = torch.fft.fftfreq(w, device=x.device)[None, :]
    idx = torch.clamp((torch.sqrt(fx * fx + fy * fy) / 0.5 * bins).long(), max=bins - 1).flatten()
    a = torch.fft.fft2(x - x.mean((2, 3), keepdim=True)).abs().mean((0, 1)).flatten()
    s = torch.zeros(bins, device=x.device, dtype=a.dtype).index_add_(0, idx, a)
    n = torch.zeros(bins, device=x.device, dtype=a.dtype).index_add_(0, idx, torch.ones_like(a))
    return torch.log(s / n.clamp(min=1) + 1e-6)


def grain_stats_t(x, sigma=2.0, qs=(0.25, 0.5, 0.75, 0.9)):
    """Quantiles over the batch of structure-tensor coherence (smoothed by SIGMA px) and of gradient strength of
    X (B, 1, H, W): how strongly grain runs along one direction, and how sharp edges are."""
    torch, _, F = _torch()
    k = torch.tensor([[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]], device=x.device, dtype=x.dtype) / 8
    xp = F.pad(x, (1, 1, 1, 1), mode="reflect")
    gx = F.conv2d(xp, k.view(1, 1, 3, 3))
    gy = F.conv2d(xp, k.t().contiguous().view(1, 1, 3, 3))
    jxx, jxy, jyy = blur_t(gx * gx, sigma), blur_t(gx * gy, sigma), blur_t(gy * gy, sigma)
    coh = torch.sqrt((jxx - jyy) ** 2 + 4 * jxy * jxy + 1e-12) / (jxx + jyy + 1e-6)
    g = torch.sqrt(gx * gx + gy * gy + 1e-12)
    q = torch.tensor(qs, device=x.device, dtype=x.dtype)
    return torch.cat([torch.quantile(coh.flatten()[::7], q), torch.quantile(g.flatten()[::7], q)])


def orientation_t(x, sigma=2.0):
    """Local sheet direction of X (B, 1, H, W), in radians: the structure tensor's gradient direction (smoothed by
    SIGMA px) turned by 90 degrees. No gradient flows through it."""
    torch, _, F = _torch()
    with torch.no_grad():
        k = torch.tensor([[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]], device=x.device, dtype=x.dtype) / 8
        xp = F.pad(x, (1, 1, 1, 1), mode="reflect")
        gx = F.conv2d(xp, k.view(1, 1, 3, 3))
        gy = F.conv2d(xp, k.t().contiguous().view(1, 1, 3, 3))
        jxx, jxy, jyy = blur_t(gx * gx, sigma), blur_t(gx * gy, sigma), blur_t(gy * gy, sigma)
        return 0.5 * torch.atan2(2 * jxy, jxx - jyy) + math.pi / 2


def steer_t(r, x, nb=8, along=2.0, across=0.6, kappa=4.0, size=9):
    """R (B, 1, H, W) smoothed along the local sheet direction of X: a bank of NB anisotropic Gaussians (ALONG and
    ACROSS px) blended per pixel by a von Mises weight (KAPPA) on the angle to orientation_t(X). The result cannot be
    isotropic texture: grain runs with the sheets."""
    torch, _, F = _torch()
    th = orientation_t(x)
    h = size // 2
    t = torch.arange(-h, h + 1, dtype=r.dtype, device=r.device)
    yy, xx = torch.meshgrid(t, t, indexing="ij")
    ks, ws = [], []
    for b in range(nb):
        a = math.pi * b / nb
        u = xx * math.cos(a) + yy * math.sin(a)
        v = -xx * math.sin(a) + yy * math.cos(a)
        g = torch.exp(-u * u / (2 * along * along) - v * v / (2 * across * across))
        ks.append(g / g.sum())
        ws.append(kappa * torch.cos(2 * (th - a)))
    rb = F.conv2d(F.pad(r, (h, h, h, h), mode="reflect"), torch.stack(ks)[:, None])
    w = torch.softmax(torch.cat(ws, 1), 1)
    return (rb * w).sum(1, keepdim=True)


def steer_mode(oriented):
    """The residual steering mode as a string: "" (none), "full" (all of the residual steered along the sheets),
    "band:S" (only the residual's low band, a Gaussian blur at S px, steered; the finer texture stays free) or
    "mix:A" (A of the residual steered, 1 - A free). True means "full", False ""."""
    if oriented is True:
        return "full"
    if not oriented:
        return ""
    m = str(oriented)
    if m == "full":
        return m
    kind, _, val = m.partition(":")
    try:
        v = float(val)
    except ValueError:
        raise GanError(f"steer mode {m!r}: use full, band:SIGMA or mix:ALPHA")
    if kind == "band" and v > 0:
        return f"band:{v:g}"
    if kind == "mix" and 0 < v <= 1:
        return f"mix:{v:g}"
    raise GanError(f"steer mode {m!r}: band needs SIGMA > 0, mix needs 0 < ALPHA <= 1")


def steer_residual(r, x, mode):
    """G's residual R after the steering MODE (steer_mode) along the sheets of the physics tile X."""
    if not mode:
        return r
    if mode == "full":
        return steer_t(r, x)
    kind, _, val = mode.partition(":")
    v = float(val)
    if kind == "band":
        lo = blur_t(r, v)
        return (r - lo) + steer_t(lo, x)
    return (1 - v) * r + v * steer_t(r, x)


def hi_band_t(prof, start=0.4):
    """The bins of a radial profile (radial_profile_t) from START of Nyquist up (the band hi_w weighs)."""
    return prof[int(math.floor(start * len(prof))):]


def straight_through(x, edited):
    """EDITED (no gradient) in the forward pass, X's gradient in the backward pass: the discriminator judges the
    edited image while G learns as if the edit were the identity (an edit inside the training loop)."""
    return x + (edited - x).detach()


def _gnorm(torch, loss, x):
    g, = torch.autograd.grad(loss, x, retain_graph=True)
    return float(g.norm())


def _aug(torch, x, gen):
    k = int(torch.randint(0, 4, (1,), generator=gen))
    x = torch.rot90(x, k, (2, 3))
    if int(torch.randint(0, 2, (1,), generator=gen)):
        x = x.flip(3)
    return x


def train(sim, real, steps=8000, device="cpu", seed=1, batch=16, lam=LAM, lr=2e-4, progress=print, width=32,
          sigma=SIGMA, d_width=64, spec_w=0.0, grain_w=0.0,
          oriented=False, hi_w=0.0, edit=None, score=None, score_ratio=0.0, init=None):
    """G and D trained on SIM (N, H, W) physics tiles (any numeric type) against REAL (M, H, W) real windows already
    scaled by unit(). LAM weighs the structure loss, the L1 between G's output and its input both blurred by SIGMA px:
    a larger SIGMA or a smaller LAM lets G change more of the sheets' own profile (width, contrast) while their
    positions stay. D_WIDTH sets the discriminator's channels (64; 128 in the measured settings). SPEC_W weighs an L1 between the batch's log radial
    amplitude profiles of G's output and of the real windows; GRAIN_W one between their coherence and gradient-strength
    quantiles (from a realism judge's attribution: too much power near Nyquist, grain not along the sheets).
    ORIENTED steers G's residual along the sheets (steer_t): True or "full" all of it, "band:S" only its low band
    below S px, "mix:A" a share A (steer_mode).
    HI_W weighs an extra L1 on the spectrum's band above 0.4 Nyquist (hi_band_t). EDIT, a callable from
    unit-view tiles (B, 1, H, W) to edited unit-view tiles with no gradient (a diffusion partial-noise edit), puts
    the edit in the loop: D judges unit_t(EDIT(G's output)) and G learns through it straight (straight_through).
    SCORE, a callable from unit-view tiles to a surrogate loss whose gradient is a prior's score (score distillation
    with a diffusion model), adds that loss to G's, weighted each step so its gradient norm on G's output is
    SCORE_RATIO times the adversarial one's. INIT, a saved G (save()) or its state dict, starts G from those weights
    (a fine-tune; D starts fresh). Returns G (eval mode) with its loss history in G.kit_log."""
    torch, _, F = _torch()
    import numpy as np
    torch.manual_seed(int(seed))
    gen = torch.Generator().manual_seed(int(seed))
    G, D = build(width, d_width, oriented)
    if init is not None:
        if isinstance(init, str):
            from safetensors.torch import load_file
            init = load_file(init)
        G.load_state_dict(init)
    G, D = G.to(device), D.to(device)
    oG = torch.optim.Adam(G.parameters(), lr, betas=(0.5, 0.999))
    oD = torch.optim.Adam(D.parameters(), lr, betas=(0.5, 0.999))
    S = torch.from_numpy(np.asarray(sim))
    R = torch.from_numpy(np.asarray(real, np.float32))
    log = []
    t0 = time.time()
    for p in range(steps):
        xs = S[torch.randint(0, len(S), (batch,), generator=gen)].float().to(device)[:, None]
        xs = _aug(torch, unit_t(xs), gen)
        xr = _aug(torch, R[torch.randint(0, len(R), (batch,), generator=gen)].to(device)[:, None], gen)
        z = torch.randn(xs.shape, generator=gen).to(device)
        fake = G(xs, z)
        fake_n = unit_t(fake)            # judged in the detectors' per-window view
        if edit is not None:
            fake_n = straight_through(fake_n, unit_t(edit(fake_n.detach())))
        dl = ((D(xr) - 1) ** 2).mean() + (D(fake_n.detach()) ** 2).mean()
        oD.zero_grad(set_to_none=True)
        dl.backward()
        oD.step()
        adv = ((D(fake_n) - 1) ** 2).mean()
        st = (blur_t(fake, sigma) - blur_t(xs, sigma)).abs().mean()
        gl = adv + lam * st
        if spec_w:
            gl = gl + spec_w * (radial_profile_t(fake_n) - radial_profile_t(xr)).abs().mean()
        if grain_w:
            gl = gl + grain_w * (grain_stats_t(fake_n) - grain_stats_t(xr)).abs().mean()
        if hi_w:
            gl = gl + hi_w * (hi_band_t(radial_profile_t(fake_n)) - hi_band_t(radial_profile_t(xr))).abs().mean()
        sw = sv = 0.0
        if score is not None and score_ratio:
            sl = score(fake_n)
            sw = score_ratio * _gnorm(torch, adv, fake_n) / max(_gnorm(torch, sl, fake_n), 1e-12)
            sv = float(sl)
            gl = gl + sw * sl
        if not (torch.isfinite(gl) and torch.isfinite(dl)):
            raise GanError(f"non-finite loss at step {p + 1}")
        oG.zero_grad(set_to_none=True)
        gl.backward()
        oG.step()
        if p % 250 == 0 or p == steps - 1:
            log.append({"step": p + 1, "d": float(dl), "adv": float(adv), "struct": float(st)})
            if score is not None:
                log[-1].update(score=sv, score_w=sw)
            if progress:
                progress(f"PROGRESS gan step {p + 1}/{steps} d {float(dl):.3f} adv {float(adv):.3f} "
                         f"struct {float(st):.4f} {time.time() - t0:.0f} s")
    G.eval()
    G.kit_log = log
    return G


def realize(G, images, device="cpu", batch=32, seed=0, edit=None):
    """Realized uint8 tiles from physics IMAGES (N, H, W): G's output in the per-window unit view, written as
    uint8 over LO..HI. EDIT: the same callable train() put in the loop, applied to G's output first."""
    torch, _, _ = _torch()
    import numpy as np
    gen = torch.Generator().manual_seed(int(seed))
    out = []
    with torch.no_grad():
        for i in range(0, len(images), batch):
            x = unit_t(torch.from_numpy(np.asarray(images[i:i + batch])).float().to(device)[:, None])
            z = torch.randn(x.shape, generator=gen).to(device)
            y = unit_t(G(x, z))
            if edit is not None:
                y = unit_t(edit(y))
            y = y[:, 0].float().cpu().numpy()
            if not np.isfinite(y).all():
                raise GanError("non-finite realized tile")
            out.append(np.clip(np.rint((np.clip(y, LO, HI) - LO) / (HI - LO) * 255), 0, 255).astype(np.uint8))
    return np.concatenate(out)


def save(G, path):
    from safetensors.torch import save_file
    save_file({k: v.detach().cpu().contiguous() for k, v in G.state_dict().items()}, path,
              metadata={"kind": "simgan-G", "width": "32", "oriented": "1" if getattr(G, "oriented", "") else "0",
                       "steer": getattr(G, "oriented", "") or ""})


def load(path, device="cpu"):
    from safetensors import safe_open
    from safetensors.torch import load_file
    with safe_open(path, "pt") as f:
        meta = f.metadata() or {}
    G, _ = build(32, oriented=meta.get("steer") or meta.get("oriented") == "1")
    G.load_state_dict(load_file(path))
    return G.to(device).eval()


def cnn_auc(real, fake, device="cpu", steps=600, seed=0, batch=32):
    """A fresh small CNN taught to tell REAL from FAKE windows (both (N, H, W), unit-scaled), trained on half of
    each and scored by ROC AUC on the other half. 0.5: it cannot tell them apart."""
    torch, nn, F = _torch()
    import numpy as np
    from kit import simreal
    torch.manual_seed(int(seed))
    gen = torch.Generator().manual_seed(int(seed))
    rr, ff = np.asarray(real, np.float32), np.asarray(fake, np.float32)
    nr, nf = len(rr) // 2, len(ff) // 2
    net = nn.Sequential(nn.Conv2d(1, 16, 5, 2, 2), nn.LeakyReLU(0.2), nn.Conv2d(16, 32, 5, 2, 2), nn.LeakyReLU(0.2),
                        nn.Conv2d(32, 64, 5, 2, 2), nn.LeakyReLU(0.2), nn.Conv2d(64, 64, 3, 2, 1), nn.LeakyReLU(0.2),
                        nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(64, 1)).to(device)
    opt = torch.optim.Adam(net.parameters(), 1e-3)
    Rt, Ft = torch.from_numpy(rr[:nr]), torch.from_numpy(ff[:nf])
    for _ in range(steps):
        a = Rt[torch.randint(0, nr, (batch // 2,), generator=gen)]
        b = Ft[torch.randint(0, nf, (batch // 2,), generator=gen)]
        x = _aug(torch, torch.cat([a, b])[:, None].to(device), gen)
        y = torch.cat([torch.ones(len(a)), torch.zeros(len(b))]).to(device)
        loss = F.binary_cross_entropy_with_logits(net(x)[:, 0], y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    with torch.no_grad():
        te = torch.from_numpy(np.concatenate([rr[nr:], ff[nf:]]))[:, None]
        s = torch.cat([net(te[i:i + 64].to(device))[:, 0].cpu() for i in range(0, len(te), 64)]).numpy()
    y = np.r_[np.ones(len(rr) - nr), np.zeros(len(ff) - nf)]
    return simreal._auc(s, y)


TOL = 2     # px, the line F1 tolerance (Synthetic-Slices' juges.f1)

# R4: Hard Cases render bounds (kit.hardcases.tiles dense_look), fitted on CPU with kit.simreal.distance to median
# window statistics (width and pitch weighted most) of the R343-v1 slices (public PHerc0343P CT, gray values only),
# 25 Nov 2026. The fit record does not say the odd slices were left out, so treat these 8 bounds as having seen
# them. Every simgan setting in docs/tools/simgan.md#results starts from tiles rendered under them.
PRESETS = {
    "r4": {"sd": (0.1056, 0.1077), "psf": (0.9306, 1.1038), "ply_w": (0.2159, 0.2297), "rim": (0.8886, 0.9105),
           "gap": (0.3648, 0.4266), "pitch": (0.7734, 0.7942), "fill": (0.8711, 0.9567), "core": (0.7323, 0.854)},
}
# The measured settings (docs/tools/simgan.md#results): structure loss 10 at sigma 1.5 px, spectrum 1, grain 5,
# discriminator 128 channels, 6,000 steps. "band:4" steering gave the lowest CNN critic AUC.
DEFAULTS = {"lam": 10.0, "sigma": 1.5, "spec_w": 1.0, "grain_w": 5.0, "d_width": 128, "steps": 6000}


def ridge(img, sigmas=(1.0, 1.5, 2.0, 2.5, 3.0)):
    """Bright-ridge response of a 2D image: scikit-image's Sato filter, max over SIGMAS."""
    import numpy as np
    from skimage.filters import sato
    return sato(np.asarray(img, np.float64), sigmas=sigmas, black_ridges=False).astype(np.float32)


def extract(prob, mask):
    """Synthetic-Slices' NMS 2 line extraction of PROB inside MASK. A map with NaN or Inf is refused."""
    import numpy as np
    if not np.isfinite(np.asarray(prob, np.float64)).all():
        raise GanError("non-finite ridge map: NaN or Inf, refused before scoring")
    try:
        from synthetic_slices.extract import extract_lines
    except ImportError as exc:
        raise GanError("line_keep needs Synthetic-Slices and OpenCV: pip install opencv-python-headless && pip "
                       "install --no-deps git+https://github.com/vincentl065/Synthetic-Slices@"
                       "bf8d26f502ed38c188c409d7f3011a7a11c4cf89") from exc
    return extract_lines(prob, mask) > 0


def f1(pred, ref, mask=None, tol=TOL):
    """F1 between line maps PRED and REF inside MASK with a TOL px tolerance (Synthetic-Slices' juges.f1): precision
    pixels are predicted pixels within TOL of a true line, recall pixels true pixels within TOL of a prediction."""
    import numpy as np
    from scipy import ndimage as nd
    p, r = np.asarray(pred) > 0, np.asarray(ref) > 0
    if mask is not None:
        m = np.asarray(mask, bool)
        p, r = p & m, r & m
    if not p.any() and not r.any():
        return 1.0
    rd = nd.binary_dilation(r, iterations=tol) if r.any() else r
    pd = nd.binary_dilation(p, iterations=tol) if p.any() else p
    prec = int((p & rd).sum()) / max(1, int(p.sum()))
    rec = int((r & pd).sum()) / max(1, int(r.sum()))
    return float(2 * prec * rec / max(1e-9, prec + rec))


def line_keep(images, lines, n=64):
    """Mean F1 at 2 px of ridge (Sato) lines after Synthetic-Slices' NMS on IMAGES against the layouts' LINES, over
    the first N. Run it on the physics tiles and on the realized ones: G must not lower it."""
    import numpy as np
    f = []
    for im, ln in zip(images[:n], lines[:n]):
        m = np.ones(np.shape(ln), bool)
        f.append(f1(extract(ridge(np.asarray(im, np.float32) / 255.0), m), np.asarray(ln) > 0, m))
    return float(np.mean(f))


# ---------------------------------------------------------------- command line

def real_windows(slices, n=3000, seed=1, win=256):
    """N unit-scaled real windows (N, WIN, WIN) drawn from 2D SLICES with kit.simreal.windows (no cover mask)."""
    import numpy as np
    from kit import simreal
    ws = simreal.windows([np.asarray(c, np.float64) for c in slices], None, n, seed, win=win, min_cover=0.0)
    return np.stack([unit(w) for w in ws])


def physics_tiles(n=4000, seed=41, preset="r4", max_air=0.05):
    """N Hard Cases tiles (256 px) under PRESET's render bounds; tiles with more than MAX_AIR air are left out.
    Returns the kept tiles' image, lines and sheet_id arrays."""
    import numpy as np
    from kit import hardcases
    sh = hardcases.tiles(n, seed, 256, None, 0.3, 0, dense_look=PRESETS[preset] if preset else None)
    keep = np.array([float(np.mean(m)) <= max_air for m in sh["air"]])
    return {"image": sh["image"][keep], "lines": sh["lines"][keep], "sheet_id": sh["sheet_id"][keep]}


def _savez(path, **arrays):
    import numpy as np
    with open(path + ".part", "wb") as fh:
        np.savez_compressed(fh, **arrays)
    os.replace(path + ".part", path)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.simgan", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("real", help="unit-scaled training windows from the even slices of a reference npz")
    r.add_argument("reference", help="npz with ct (python -m kit.simscore reference R343.npz)")
    r.add_argument("out")
    r.add_argument("--n", type=int, default=3000)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--win", type=int, default=256)
    t = sub.add_parser("tiles", help="Hard Cases physics tiles under a render preset, with lines and sheet ids")
    t.add_argument("out")
    t.add_argument("--n", type=int, default=4000)
    t.add_argument("--seed", type=int, default=41)
    t.add_argument("--preset", default="r4", choices=sorted(PRESETS) + ["none"])
    g = sub.add_parser("train", help="train G on physics tiles against real windows; writes G as safetensors")
    g.add_argument("tiles")
    g.add_argument("real")
    g.add_argument("out")
    g.add_argument("--steer", default="", help="residual steering: none, full, band:S or mix:A (default none)")
    g.add_argument("--steps", type=int, default=DEFAULTS["steps"])
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--lam", type=float, default=DEFAULTS["lam"])
    g.add_argument("--sigma", type=float, default=DEFAULTS["sigma"])
    g.add_argument("--spec", type=float, default=DEFAULTS["spec_w"])
    g.add_argument("--grain", type=float, default=DEFAULTS["grain_w"])
    g.add_argument("--hi", type=float, default=0.0, help="weight of the high-band spectrum term (0: off)")
    g.add_argument("--d-width", type=int, default=DEFAULTS["d_width"])
    g.add_argument("--hold", type=int, default=240, help="last tiles kept out of training (default 240)")
    g.add_argument("--device", default="cpu")
    z = sub.add_parser("realize", help="realize physics tiles with a trained G; writes image, phys, lines, sheet_id")
    z.add_argument("g")
    z.add_argument("tiles")
    z.add_argument("out")
    z.add_argument("--n", type=int, default=2000)
    z.add_argument("--seed", type=int, default=0)
    z.add_argument("--device", default="cpu")
    k = sub.add_parser("linekeep", help="line F1 of realized (image) and physics (phys) tiles against their lines")
    k.add_argument("npz")
    k.add_argument("--n", type=int, default=64)
    k.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if sys.stdout.isatty() and not getattr(a, "json", False):
        try:
            from kit import termstyle
            termstyle.script()
        except Exception:
            pass
    import numpy as np
    if a.cmd == "real":
        ct = list(np.load(a.reference, allow_pickle=True)["ct"])
        even = ct[0::2]
        w = real_windows(even, a.n, a.seed, a.win)
        _savez(a.out, real=w.astype(np.float32), slices=np.arange(0, len(ct), 2))
        print(f"wrote {a.out}: {len(w)} windows of {a.win} px from slices {list(range(0, len(ct), 2))} of {len(ct)}")
        return 0
    if a.cmd == "tiles":
        sh = physics_tiles(a.n, a.seed, None if a.preset == "none" else a.preset)
        _savez(a.out, **sh)
        print(f"wrote {a.out}: {len(sh['image'])} of {a.n} tiles kept (air at most 5 %)")
        return 0
    if a.cmd == "train":
        img = np.load(a.tiles)["image"]
        real = np.load(a.real)["real"]
        if a.hold >= len(img):
            raise SystemExit(f"--hold {a.hold} leaves no training tiles of {len(img)}")
        steer = steer_mode("" if a.steer in ("", "none") else a.steer)
        t0 = time.time()
        G = train(img[:len(img) - a.hold] if a.hold else img, real, a.steps, a.device, seed=a.seed, lam=a.lam,
                  sigma=a.sigma, spec_w=a.spec, grain_w=a.grain, hi_w=a.hi, d_width=a.d_width, oriented=steer)
        save(G, a.out + ".part")
        os.replace(a.out + ".part", a.out)
        meta = {"tiles": os.path.basename(a.tiles), "real": os.path.basename(a.real), "steer": steer or "none",
                "steps": a.steps, "seed": a.seed, "lam": a.lam, "sigma": a.sigma, "spec": a.spec, "grain": a.grain,
                "hi": a.hi, "d_width": a.d_width, "hold": a.hold, "seconds": round(time.time() - t0),
                "loss_last": G.kit_log[-1]}
        with open(a.out + ".json", "w") as f:
            json.dump(meta, f, indent=1)
        print(f"wrote {a.out} and {a.out}.json")
        return 0
    if a.cmd == "realize":
        t = np.load(a.tiles)
        n = min(a.n, len(t["image"]))
        G = load(a.g, a.device)
        out = realize(G, t["image"][:n], a.device, seed=a.seed)
        _savez(a.out, image=out, phys=t["image"][:n], lines=t["lines"][:n], sheet_id=t["sheet_id"][:n])
        print(f"wrote {a.out}: {n} realized tiles")
        return 0
    t = np.load(a.npz)
    res = {"realized": line_keep(t["image"], t["lines"], a.n)}
    if "phys" in t.files:
        res["physics"] = line_keep(t["phys"], t["lines"], a.n)
    print(json.dumps(res) if a.json else "line keep " + ", ".join(f"{k} {v:.3f}" for k, v in res.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
