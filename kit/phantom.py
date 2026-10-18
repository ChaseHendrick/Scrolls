"""Synthetic carbon-ink-on-papyrus phantoms with known ground truth.

A phantom is a small surface volume (depth, height, width) that looks, to a detector, like a
flattened papyrus sheet: two fibre layers at right angles, a slowly varying brightness field,
CT-like noise, and carbon ink strokes laid in rows of letter-sized cells on the top surface.
Carbon ink is nearly invisible in density, so by default the ink adds a small density step and
a small thickness bump, well below the noise. The ink mask that made the strokes is the label,
so every pixel's truth is known, unlike on a real segment where labels are hand drawn.

Uses:
  * stress-test a detector: does it beat the depth-reversed control on a phantom it never saw?
  * calibrate AUC noise: draw many phantoms of one difficulty, score a simulated reader of one
    fixed quality on each, and compare the spread of AUC between phantoms with the block
    bootstrap interval that `kit auc --bootstrap` reports on one segment.

The strokes are random lines and arcs, not letters of any script. Nothing here is a reading,
and a detector's score on a phantom says nothing about any scroll. Numpy only.
"""

import math

from .verify import VerifyError, _numpy

VOXEL_UM = 9.366


def gaussian_blur(img, sigma):
    """Isotropic Gaussian blur over the last two axes, reflected edges (numpy FFT, no scipy)."""
    np = _numpy()
    out = np.asarray(img, dtype=np.float64)
    for axis in (out.ndim - 2, out.ndim - 1):
        out = _blur_axis(np, out, sigma, axis)
    return out


def _stroke_mask(np, rng, h, w, letter_px, width_px, row_gap, fill):
    """Rows of letter cells; each cell gets 2 to 4 random line or arc strokes."""
    yy, xx = np.mgrid[0:h, 0:w]
    mask = np.zeros((h, w), dtype=bool)
    pitch_y = int(letter_px * (1 + row_gap))
    pitch_x = int(letter_px * 0.9)
    margin = letter_px // 2
    cells = 0
    for y0 in range(margin, h - letter_px - margin + 1, pitch_y):
        for x0 in range(margin, w - letter_px - margin + 1, pitch_x):
            if rng.random() > fill:
                continue
            cells += 1
            for _ in range(rng.integers(2, 5)):
                sl = (slice(y0 - 2 * width_px, y0 + letter_px + 2 * width_px),
                      slice(x0 - 2 * width_px, x0 + letter_px + 2 * width_px))
                cy, cx = yy[sl], xx[sl]
                if rng.random() < 0.6:   # straight stroke
                    p = y0 + rng.random(2) * letter_px, x0 + rng.random(2) * letter_px
                    ay, ax = p[0][0], p[1][0]
                    dy, dx = p[0][1] - ay, p[1][1] - ax
                    t = np.clip(((cy - ay) * dy + (cx - ax) * dx) / max(dy * dy + dx * dx, 1e-9), 0, 1)
                    d = np.hypot(cy - ay - t * dy, cx - ax - t * dx)
                else:                    # arc
                    rad = letter_px * (0.25 + 0.25 * rng.random())
                    my, mx = y0 + letter_px / 2, x0 + letter_px / 2
                    a0 = rng.random() * 2 * math.pi
                    span = math.pi * (0.6 + rng.random())
                    ang = (np.arctan2(cy - my, cx - mx) - a0) % (2 * math.pi)
                    d = np.abs(np.hypot(cy - my, cx - mx) - rad)
                    d = np.where(ang <= span, d, np.inf)
                mask[sl] |= d <= width_px / 2
    return mask, cells


def make_phantom(shape=(512, 512), depth=26, seed=0, letter_px=96, stroke_px=None, fill=0.7,
                 ink_contrast=0.25, ink_bump=0.6, noise=1.0, drift=0.8, row_gap=0.5):
    """Return dict(volume float32 [depth,h,w], ink bool [h,w], mask bool [h,w], meta).

    Units of contrast and noise: one unit is the papyrus fibre texture's standard deviation.
    ink_contrast: density added under ink in the top two layers. ink_bump: fraction of a layer
    the sheet surface rises under ink (carbon ink's thickness). noise: per-voxel Gaussian noise.
    drift: amplitude of a smooth brightness field across the sheet (confounds brightness)."""
    np = _numpy()
    h, w = shape
    if depth < 8:
        raise VerifyError("a phantom needs at least 8 layers")
    if min(h, w) < 2 * letter_px:
        raise VerifyError("the phantom is too small for its letter size")
    stroke_px = stroke_px or max(2, letter_px // 8)
    rng = np.random.default_rng(seed)
    ink, cells = _stroke_mask(np, rng, h, w, letter_px, stroke_px, row_gap, fill)
    ink_soft = gaussian_blur(ink.astype(np.float64), stroke_px / 4)

    def fibres(sy, sx):
        f = _blur_axis(np, _blur_axis(np, rng.standard_normal((h, w)), sy, 0), sx, 1)
        return (f - f.mean()) / (f.std() + 1e-12)

    recto, verso = fibres(0.8, 12.0), fibres(12.0, 0.8)
    field = gaussian_blur(rng.standard_normal((h, w)), min(h, w) / 6)
    field = drift * (field - field.mean()) / (field.std() + 1e-12)

    z = np.arange(depth, dtype=np.float64)[:, None, None]
    top = depth * 0.35 - ink_bump * ink_soft[None]          # surface rises under ink
    mid = depth * 0.5
    bottom = depth * 0.65
    occupancy = 1 / (1 + np.exp(-(z - top) * 3)) * (1 / (1 + np.exp((z - bottom) * 3)))
    layer = np.where(z < mid, recto[None], verso[None])
    vol = occupancy * (2.0 + layer + field[None])
    ink_layers = np.exp(-0.5 * ((z - (top + 1.0)) / 1.0) ** 2)
    vol += ink_contrast * ink_soft[None] * ink_layers
    vol += noise * rng.standard_normal(vol.shape)
    mask = np.zeros((h, w), dtype=bool)
    e = letter_px // 4
    mask[e:h - e, e:w - e] = True
    meta = {"seed": seed, "shape": [depth, h, w], "letter_px": letter_px, "stroke_px": stroke_px,
            "letter_um": round(letter_px * VOXEL_UM, 1), "cells": cells, "fill": fill,
            "ink_contrast": ink_contrast, "ink_bump": ink_bump, "noise": noise, "drift": drift,
            "ink_fraction": round(float(ink[mask].mean()), 4), "ink_top_layer": round(depth * 0.35, 2)}
    return {"volume": vol.astype(np.float32), "ink": ink, "mask": mask, "meta": meta}


def _blur_axis(np, img, sigma, axis):
    img = np.asarray(img, dtype=np.float64)
    if sigma <= 0:
        return img.copy()
    n = img.shape[axis]
    r = min(max(1, int(math.ceil(3 * sigma))), n - 1)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    p = np.pad(img, [(r, r) if a == axis else (0, 0) for a in range(img.ndim)], mode="reflect")
    m = p.shape[axis]
    kk = np.zeros(m)
    kk[:2 * r + 1] = k
    shape = [1] * img.ndim
    shape[axis] = m // 2 + 1
    f = np.fft.irfft(np.fft.rfft(p, axis=axis) * np.fft.rfft(kk).reshape(shape), n=m, axis=axis)
    return np.take(f, np.arange(2 * r, 2 * r + n), axis=axis)


def surface_detector(volume, band=2):
    """A transparent baseline reader: density just above the sheet's top surface band minus the
    sheet interior, per pixel. It reads the depth order, so the reversed volume is its control."""
    np = _numpy()
    v = volume.astype(np.float64)
    prof = v.mean(axis=(1, 2))
    top = int(np.argmax(np.diff(prof)))  # steepest rise: entering the sheet
    ink = v[top:top + band + 1].mean(0)
    core = v[top + band + 2:top + band + 6].mean(0)
    s = gaussian_blur(ink - core, 2.0)
    return _unit(np, s)


def _unit(np, s):
    """Map to (0, 1], never exactly 0 (kit auc drops zeros as no-prediction)."""
    lo, hi = np.percentile(s, [0.5, 99.5])
    return (np.clip((s - lo) / max(hi - lo, 1e-12), 0, 1) * 0.998 + 0.001).astype(np.float32)


def simulated_reader(ink, quality=1.0, blur_px=4.0, noise_px=6.0, seed=0):
    """A stand-in reader of fixed quality: blurred truth plus spatially correlated noise.
    quality is the signal-to-noise ratio of the blurred truth against unit-variance noise."""
    np = _numpy()
    rng = np.random.default_rng(seed)
    sig = gaussian_blur(ink.astype(np.float64), blur_px)
    sig = (sig - sig.mean()) / (sig.std() + 1e-12)
    n = gaussian_blur(rng.standard_normal(ink.shape), noise_px)
    n = (n - n.mean()) / (n.std() + 1e-12)
    return _unit(np, quality * sig + n)


def calibrate(n=12, shape=(512, 512), letter_px=96, quality=1.0, draws=200, block_px=107, seed=0):
    """AUC spread between phantoms against the one-segment block bootstrap interval."""
    np = _numpy()
    from . import auc as kauc
    rows = []
    for i in range(n):
        ph_ink, _ = _stroke_mask(np, np.random.default_rng(seed * 1000 + i), shape[0], shape[1], letter_px,
                                 max(2, letter_px // 8), 0.5, 0.7)
        mask = np.zeros(shape, dtype=bool)
        e = letter_px // 4
        mask[e:-e, e:-e] = True
        pred = simulated_reader(ph_ink, quality=quality, seed=seed * 1000 + i + 500)
        a = kauc.score_array(pred, ph_ink, mask)["auc"]
        b = kauc.block_bootstrap(pred, ph_ink, mask, draws=draws, block_px=block_px, seed=i)
        rows.append({"phantom": i, "auc": a, "ci95": b["ci95"], "half_width": b["half_width"]})
    aucs = np.array([r["auc"] for r in rows])
    hw = np.array([r["half_width"] for r in rows])
    mean = float(aucs.mean())
    covered = sum(r["ci95"][0] <= mean <= r["ci95"][1] for r in rows)
    return {"n": n, "shape": list(shape), "letter_px": letter_px, "quality": quality, "block_px": block_px,
            "draws": draws, "auc_mean": round(mean, 4), "auc_sd_between": round(float(aucs.std(ddof=1)), 4),
            "empirical_half_width": round(float(1.96 * aucs.std(ddof=1)), 4),
            "bootstrap_half_width_mean": round(float(hw.mean()), 4),
            "ratio_bootstrap_to_empirical": round(float(hw.mean() / max(1.96 * aucs.std(ddof=1), 1e-12)), 3),
            "intervals_covering_mean": f"{covered}/{n}", "rows": rows}
