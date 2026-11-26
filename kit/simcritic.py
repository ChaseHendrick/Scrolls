"""ScrollSim realism critic: a held-apart judge of how real simulated CT windows look, and what gives them away.

The judge is kept apart from any generator that is tuned toward real CT (render presets from kit.simreal, a learned
texture, layout fits): a generator owns its own tests, and this module owns the judge.

What it measures. Two sets of 2D windows, REAL (grey values of real CT) and SIM (simulated tiles, raw or realised).
A fresh critic is fitted on some groups and scores held-out groups (grouped folds: a real slice or a sim tile never
sits on both sides of a split, so overlapping windows cannot leak). The score is the ROC AUC of "real" on the
held-out windows: 0.5 means the critic cannot tell the sets apart, 1.0 means it always can. Several critics
(a feature logistic, a CNN at full resolution, a CNN at half resolution for context) each give an AUC; the judge's
verdict uses the WORST case (the highest AUC), so a set passes only when no critic separates it.

Why a separate judge. A critic used to train or tune the generator is optimised against, so its AUC falls by
construction (Goodhart). The judge here is refitted from scratch on every call, never saved, and `judge` refuses real
windows from any group listed in `trained_on` (the slices the generator's discriminator saw).

Controls (rule 4): `control` runs the same critics on two real sets (for example even against odd slices). Its AUC
is the floor a perfect simulator would reach on that scroll; `verdict` compares against it. `planted` builds known
cases (identical sets, a set with added noise, a blurred set) so the critics are shown to fail and to pass.

Attribution. `VIEWS` transform both sets the same way before the CNN critic: `marginal` ranks every window to a
uniform grey histogram (removes the histogram); `whiten` also sets every window's Fourier amplitude to the pooled
mean (removes the power spectrum, keeps phase: edges and geometry); `phaserand` keeps each window's amplitude and
draws a random phase (keeps only histogram-free spectrum); `low` and `high` keep only coarse or fine scales; `ridge`
keeps only a label-free bright-ridge map (sheet geometry). If the AUC stays high under a view, that view's content
still gives sim away; if it falls to the control, the removed content was the giveaway.

Grey values only: no labels are read. Use it on public scans you may use for development; it has not been run on
prize-eligible scrolls.
"""
import hashlib
import json

CRITICS = ("feat", "cnn", "cnn_half")
VIEWS = ("full", "marginal", "whiten", "phaserand", "low", "high", "ridge")
WIN = 128


class CriticError(ValueError):
    pass


def _np():
    import numpy as np
    return np


# ---------------------------------------------------------------- windows

def unit(w):
    """A window scaled to its own 1st..99th percentiles (float32), the same scaling a generator's training uses."""
    np = _np()
    w = np.asarray(w, np.float32)
    lo, hi = np.percentile(w, [1, 99])
    return (w - lo) / max(float(hi - lo), 1e-6)


def grid_windows(images, win=WIN, masks=None, min_cover=0.98, groups=None):
    """Non-overlapping WIN windows on a grid over each image in IMAGES (2D arrays of any size), with the group id of
    each (GROUPS[i], default i). Windows whose MASKS cover is under MIN_COVER are dropped. Returns (windows, groups)."""
    np = _np()
    out, gid = [], []
    for i, im in enumerate(images):
        im = np.asarray(im)
        H, W = im.shape
        g = i if groups is None else groups[i]
        for y in range(0, H - win + 1, win):
            for x in range(0, W - win + 1, win):
                if masks is not None and masks[i][y:y + win, x:x + win].mean() < min_cover:
                    continue
                out.append(unit(im[y:y + win, x:x + win]))
                gid.append(g)
    if not out:
        raise CriticError("no window fits")
    return np.stack(out).astype(np.float32), np.asarray(gid)


def half(images, groups=None, win=WIN, masks=None, min_cover=0.98):
    """Context-scale windows: 2*WIN windows on a grid, each 2x2 mean-pooled to WIN (the cnn_half critic's input)."""
    np = _np()
    big, gid = grid_windows(images, 2 * win, masks, min_cover, groups)
    small = big.reshape(len(big), win, 2, win, 2).mean((2, 4))
    return np.stack([unit(w) for w in small]).astype(np.float32), gid


def digest(windows):
    """SHA-256 of a window stack (recorded with every judgement, so a later run can prove which windows it saw)."""
    np = _np()
    return hashlib.sha256(np.ascontiguousarray(windows, np.float32).tobytes()).hexdigest()


# ---------------------------------------------------------------- views

def _rank_uniform(w):
    np = _np()
    r = np.argsort(np.argsort(w.ravel(), kind="stable"), kind="stable").astype(np.float32)
    return (r / max(r.size - 1, 1)).reshape(w.shape)


def view(windows, name, ref_amp=None, seed=0):
    """Both sets go through the same VIEW before a critic. REF_AMP (the pooled mean Fourier amplitude, from
    `pooled_amplitude`) is needed by `whiten`."""
    np = _np()
    from scipy import ndimage as nd
    X = np.asarray(windows, np.float32)
    if name == "full":
        return X
    if name == "marginal":
        return np.stack([_rank_uniform(w) for w in X])
    if name == "whiten":
        if ref_amp is None:
            raise CriticError("whiten needs ref_amp")
        out = []
        for w in X:
            F = np.fft.fft2(_rank_uniform(w) - 0.5)
            out.append(_rank_uniform(np.real(np.fft.ifft2(ref_amp * np.exp(1j * np.angle(F))))))
        return np.stack(out).astype(np.float32)
    if name == "phaserand":
        rng = np.random.default_rng(int(seed))
        out = []
        for w in X:
            F = np.fft.fft2(_rank_uniform(w) - 0.5)
            ph = np.angle(np.fft.fft2(rng.standard_normal(w.shape)))
            out.append(_rank_uniform(np.real(np.fft.ifft2(np.abs(F) * np.exp(1j * ph)))))
        return np.stack(out).astype(np.float32)
    if name == "low":
        return np.stack([unit(nd.gaussian_filter(w, 3.0)) for w in X])
    if name == "high":
        return np.stack([unit(w - nd.gaussian_filter(w, 1.5)) for w in X])
    if name == "ridge":
        return np.stack([ridge_map(w) for w in X])
    raise CriticError(f"unknown view {name}")


def pooled_amplitude(*sets):
    """Mean Fourier amplitude of rank-uniform windows over every set given (used by the whiten view)."""
    np = _np()
    acc, n = None, 0
    for X in sets:
        for w in X:
            a = np.abs(np.fft.fft2(_rank_uniform(w) - 0.5))
            acc = a if acc is None else acc + a
            n += 1
    return acc / max(n, 1)


def ridge_map(w):
    """Label-free bright-ridge map of a unit window: the negative smaller Hessian eigenvalue at sigma 1.5, kept where
    it is a local maximum across either axis and above its own 80th percentile (0 or 1, float32)."""
    np = _np()
    from scipy import ndimage as nd
    s = np.asarray(w, np.float64)
    hxx = nd.gaussian_filter(s, 1.5, order=(0, 2))
    hyy = nd.gaussian_filter(s, 1.5, order=(2, 0))
    hxy = nd.gaussian_filter(s, 1.5, order=(1, 1))
    r = -((hxx + hyy) / 2 - np.sqrt(((hxx - hyy) / 2) ** 2 + hxy ** 2))
    a = (r >= np.roll(r, 1, 0)) & (r >= np.roll(r, -1, 0))
    b = (r >= np.roll(r, 1, 1)) & (r >= np.roll(r, -1, 1))
    return ((a | b) & (r > np.percentile(r, 80))).astype(np.float32)


# ---------------------------------------------------------------- critics

def auc(score, y):
    """ROC AUC of SCORE for Y == 1 (ties averaged)."""
    np = _np()
    from scipy.stats import rankdata
    score, y = np.asarray(score, np.float64), np.asarray(y).astype(bool)
    r = rankdata(score)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        raise CriticError("auc needs both classes")
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n0 * n1))


def features(w):
    """Hand-made features of one unit window: 17 grey quantiles, 12 bands of the radial log power spectrum (mean
    removed), 9 quantiles of the gradient magnitude, structure-tensor coherence quantiles at 2 scales, and
    the ridge map's density and mean run length."""
    np = _np()
    from scipy import ndimage as nd
    s = np.asarray(w, np.float64)
    q = np.quantile(s, np.linspace(0.02, 0.98, 17))
    H, W = s.shape
    f = np.abs(np.fft.fftshift(np.fft.fft2(s - s.mean()))) ** 2
    yy, xx = np.indices((H, W))
    k = np.rint(np.hypot(yy - H // 2, xx - W // 2)).astype(int)
    kmax = min(H, W) // 2
    prof = np.bincount(k.ravel(), f.ravel(), kmax + 1)[1:kmax] / np.maximum(np.bincount(k.ravel(), None, kmax + 1)[1:kmax], 1)
    at = np.geomspace(1, kmax - 1, 12)
    ps = np.interp(np.log(at), np.log(np.arange(1, kmax)), np.log(prof + 1e-12))
    ps = ps - ps.mean()
    gy, gx = nd.sobel(s, 0), nd.sobel(s, 1)
    gm = np.quantile(np.hypot(gx, gy), np.linspace(0.1, 0.9, 9))
    coh = []
    for sg in (2.0, 5.0):
        jxx, jyy, jxy = (nd.gaussian_filter(a, sg) for a in (gx * gx, gy * gy, gx * gy))
        c = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-9)
        coh.extend(np.quantile(c, [0.25, 0.5, 0.75]))
    rm = ridge_map(s)
    runs = nd.label(rm)[1]
    return np.concatenate([q, ps, gm, coh, [rm.mean(), rm.sum() / max(runs, 1)]])


def _logistic(A, y, B, l2=1.0, iters=500):
    np = _np()
    mu, sd = A.mean(0), A.std(0) + 1e-9
    A, B = (A - mu) / sd, (B - mu) / sd
    w, b = np.zeros(A.shape[1]), 0.0
    wt = np.where(y == 1, 0.5 / max(y.sum(), 1), 0.5 / max((1 - y).sum(), 1))
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(A @ w + b, -30, 30)))
        g = A.T @ ((p - y) * wt) + l2 * w / len(A)
        w -= 1.0 * g
        b -= 1.0 * float(((p - y) * wt).sum())
    return B @ w + b


def _net(torch, nn, width=24):
    def blk(a, b, s):
        return [nn.Conv2d(a, b, 3, s, 1), nn.LeakyReLU(0.2)]
    layers = blk(1, width, 1) + blk(width, width, 2) + blk(width, 2 * width, 1) + blk(2 * width, 2 * width, 2) \
        + blk(2 * width, 4 * width, 1) + blk(4 * width, 4 * width, 2) + blk(4 * width, 4 * width, 2)
    return nn.Sequential(*layers, nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.3), nn.Linear(4 * width, 1))


def _cnn(Xtr, ytr, Xte, steps, seed, device="cpu", batch=32, lr=1e-3):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    np = _np()
    torch.manual_seed(int(seed))
    gen = torch.Generator().manual_seed(int(seed))
    net = _net(torch, nn).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr, weight_decay=1e-3)
    Xtr, Xte = np.asarray(Xtr, np.float32), np.asarray(Xte, np.float32)
    X1 = torch.from_numpy(np.ascontiguousarray(Xtr[ytr == 1]))
    X0 = torch.from_numpy(np.ascontiguousarray(Xtr[ytr == 0]))
    for _ in range(int(steps)):
        a = X1[torch.randint(0, len(X1), (batch // 2,), generator=gen)]
        b = X0[torch.randint(0, len(X0), (batch // 2,), generator=gen)]
        x = torch.cat([a, b])[:, None]
        k = int(torch.randint(0, 4, (1,), generator=gen))
        x = torch.rot90(x, k, (2, 3))
        if int(torch.randint(0, 2, (1,), generator=gen)):
            x = x.flip(3)
        y = torch.cat([torch.ones(len(a)), torch.zeros(len(b))])
        loss = F.binary_cross_entropy_with_logits(net(x.to(device))[:, 0], y.to(device))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    net.eval()
    te = torch.from_numpy(np.ascontiguousarray(Xte))[:, None]
    out = []
    with torch.no_grad():
        for i in range(0, len(te), 64):
            xb = te[i:i + 64].to(device)
            # test-time average over the 8 symmetries, so orientation alone cannot carry the score
            s = sum(net(torch.rot90(xb, k, (2, 3)) if f == 0 else torch.rot90(xb, k, (2, 3)).flip(3))[:, 0]
                    for k in range(4) for f in range(2)) / 8
            out.append(s.cpu())
    return torch.cat(out).numpy()


def folds_of(groups, k, seed):
    """Fold index per window: whole groups are dealt to K folds in a seeded random order."""
    np = _np()
    u = np.unique(groups)
    if len(u) < k:
        raise CriticError(f"{len(u)} groups cannot fill {k} folds")
    rng = np.random.default_rng(int(seed))
    order = rng.permutation(len(u))
    lut = {g: int(i % k) for i, g in zip(range(len(u)), u[order])}
    return np.array([lut[g] for g in groups])


def critic_auc(A, gA, B, gB, critic="cnn", folds=3, seed=0, steps=800, device="cpu", feats=None):
    """Mean held-out AUC over grouped FOLDS of CRITIC telling A (label 1) from B (label 0). FEATS: precomputed
    feature rows (fa, fb) for the feat critic. Returns {"auc": mean, "per_fold": [...]}."""
    np = _np()
    fa, fb = folds_of(gA, folds, seed), folds_of(gB, folds, seed + 7919)
    res = []
    for k in range(folds):
        if critic == "feat":
            Fa, Fb = feats if feats is not None else (np.stack([features(w) for w in A]),
                                                       np.stack([features(w) for w in B]))
            Xtr = np.vstack([Fa[fa != k], Fb[fb != k]])
            ytr = np.r_[np.ones((fa != k).sum()), np.zeros((fb != k).sum())]
            Xte = np.vstack([Fa[fa == k], Fb[fb == k]])
            s = _logistic(Xtr, ytr, Xte)
        else:
            Xtr = np.concatenate([A[fa != k], B[fb != k]])
            ytr = np.r_[np.ones((fa != k).sum()), np.zeros((fb != k).sum())]
            Xte = np.concatenate([A[fa == k], B[fb == k]])
            s = _cnn(Xtr, ytr, Xte, steps, seed * 101 + k, device)
        yte = np.r_[np.ones((fa == k).sum()), np.zeros((fb == k).sum())]
        res.append(auc(s, yte))
    return {"auc": float(np.mean(res)), "per_fold": [float(r) for r in res]}


# ---------------------------------------------------------------- judge

def judge(real, real_groups, sim, sim_groups, real_half=None, sim_half=None, critics=CRITICS, views=("full",),
          folds=3, seeds=(0, 1), steps=800, device="cpu", trained_on=(), progress=print, sink=None):
    """Judge SIM against REAL (unit windows and their group ids; *_half: the context-scale pair from `half`, needed
    for cnn_half). Each critic is run on each seed; per view the score is the mean over seeds, and `worst` is the
    highest of them. Refuses real groups listed in TRAINED_ON. Views other than full use the cnn critic only. SINK,
    when given, is called with the partial result after every critic and view, so a run stopped at its cap keeps
    what finished."""
    np = _np()
    bad = sorted(set(np.unique(real_groups).tolist()) & set(trained_on))
    if bad:
        raise CriticError(f"real groups {bad} trained the generator; the judge must not score on them")
    out = {"n_real": int(len(real)), "n_sim": int(len(sim)), "real_groups": sorted(set(np.unique(real_groups).tolist())),
           "digest_real": digest(real), "digest_sim": digest(sim), "folds": folds, "seeds": list(seeds),
           "steps": steps, "critics": {}, "views": {}}
    feats = None
    for c in critics:
        if c == "cnn_half":
            if real_half is None or sim_half is None:
                continue
            A, gA, B, gB = real_half[0], real_half[1], sim_half[0], sim_half[1]
        else:
            A, gA, B, gB = real, real_groups, sim, sim_groups
        if c == "feat" and feats is None:
            feats = (np.stack([features(w) for w in real]), np.stack([features(w) for w in sim]))
        runs = [critic_auc(A, gA, B, gB, c, folds, s, steps, device, feats if c == "feat" else None) for s in seeds]
        out["critics"][c] = {"auc": float(np.mean([r["auc"] for r in runs])), "runs": runs}
        progress(f"  critic {c}: AUC {out['critics'][c]['auc']:.3f}")
        if sink is not None:
            sink(out)
    ref = pooled_amplitude(real, sim) if "whiten" in views else None
    for v in views:
        if v == "full":
            continue
        A, B = view(real, v, ref, seed=11), view(sim, v, ref, seed=13)
        runs = [critic_auc(A, real_groups, B, sim_groups, "cnn", folds, s, steps, device) for s in seeds]
        out["views"][v] = {"auc": float(np.mean([r["auc"] for r in runs])), "runs": runs}
        progress(f"  view {v}: AUC {out['views'][v]['auc']:.3f}")
        if sink is not None:
            sink(out)
    out["worst"] = max(r["auc"] for r in out["critics"].values()) if out["critics"] else None
    out["worst_critic"] = max(out["critics"], key=lambda c: out["critics"][c]["auc"]) if out["critics"] else None
    return out


def merge(parts):
    """One judge result from PARTS, each a `judge` result on the same windows with its own seeds (for running seeds
    in parallel): runs are concatenated and every AUC is the mean over all runs, as one `judge` call would give."""
    np = _np()
    if not parts:
        raise CriticError("nothing to merge")
    keys = ("n_real", "n_sim", "real_groups", "digest_real", "digest_sim", "folds", "steps")
    for p in parts[1:]:
        if any(p[k] != parts[0][k] for k in keys):
            raise CriticError("parts were judged on different windows or settings")
    out = {k: parts[0][k] for k in keys}
    out["seeds"] = [s for p in parts for s in p["seeds"]]
    for sec in ("critics", "views"):
        out[sec] = {}
        for name in parts[0][sec]:
            runs = [r for p in parts for r in p[sec][name]["runs"]]
            out[sec][name] = {"auc": float(np.mean([r["auc"] for r in runs])), "runs": runs}
    out["worst"] = max(r["auc"] for r in out["critics"].values()) if out["critics"] else None
    out["worst_critic"] = max(out["critics"], key=lambda c: out["critics"][c]["auc"]) if out["critics"] else None
    return out


def verdict(result, control, margin=0.05, ceiling=0.60):
    """PASS when the worst critic's AUC is at most the control's worst AUC plus MARGIN and at most CEILING; else
    FAIL. The rule is fixed here so a preregistration can cite it."""
    w, c = result["worst"], control["worst"]
    ok = w is not None and c is not None and w <= c + margin and w <= ceiling
    return {"verdict": "PASS" if ok else "FAIL", "worst": w, "control_worst": c, "margin": margin, "ceiling": ceiling,
            "gap_to_bar": None if w is None else round(w - min(c + margin, ceiling), 4)}


def planted(real, real_groups, critics=("feat", "cnn"), steps=600, device="cpu", seed=0, progress=print):
    """Known cases built from REAL alone, each a check that can fail: a real set split in two at random groups
    (expect near 0.5), the same set with Gaussian noise sd 0.08 added to one half (expect high), and with one half
    blurred at sigma 1.0 (expect high)."""
    np = _np()
    from scipy import ndimage as nd
    u = np.unique(real_groups)
    rng = np.random.default_rng(int(seed))
    pick = set(rng.permutation(u)[:len(u) // 2].tolist())
    a = np.array([g in pick for g in real_groups])
    A, gA, B, gB = real[a], real_groups[a], real[~a], real_groups[~a]
    nrng = np.random.default_rng(int(seed) + 1)
    cases = {"same": B, "noise": np.stack([unit(w + nrng.normal(0, 0.08, w.shape)) for w in B]),
             "blur": np.stack([unit(nd.gaussian_filter(w, 1.0)) for w in B])}
    cases = {k: v.astype(np.float32) for k, v in cases.items()}
    out = {}
    for name, BB in cases.items():
        out[name] = {c: critic_auc(A, gA, BB, gB, c, 2, seed, steps, device)["auc"] for c in critics}
        progress(f"  planted {name}: {out[name]}")
    return out


def dumps(obj):
    return json.dumps(obj, indent=1, sort_keys=True)
