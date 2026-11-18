#!/usr/bin/env python3
"""scrollsim2: a synthetic Herculaneum-style scroll at full scale, rendered block by block, with exact truth.

ScrollSim v2 rolls one papyrus sheet into a spiral around the z axis, presses neighboring windings together in
smooth contact zones, crushes the roll and bends it with a smooth displacement field, and renders a CT-like volume
(two fiber plies per winding, holes, delamination, blur, a slow brightness drift, optional rings, noise, 8 bits).
Every voxel's winding and every surface point's position are known exactly, so a tracer's winding numbers and
surfaces can be scored end to end against ground truth.

What it adds for a whole scroll:

- a winding lookup by binary search over turns, so a voxel costs about log2(turns) lookups instead of one per turn;
- fiber textures from small periodic tiles instead of whole-sheet images (a 125-winding sheet is over a million
  voxels long);
- a crush axis that may be fixed (alpha 0 puts the major axis along x), so the box can be narrow in y;
- a block renderer whose every voxel is independent of the block size: noise comes from a hash of the voxel's
  position, and each block is rendered with a halo wide enough for every filter;
- a CT scan model: supersampling for partial volume, anisotropic point spread, propagation phase contrast with
  Paganin retrieval, noise with a set or measured power spectrum, beam-hardening cupping, rings about the rotation
  axis, acquisition slabs with gain steps, slow drift, and scan presets (`--scan synchrotron|lab`), all off by
  default; and a physical voxel size in the OME-Zarr metadata;
- OME-zarr output with levels 0 to L, written in parallel, chunk-aligned, a winding label volume beside it, and
  optional center and recto surfaces of the whole sheet as tifxyz.

An ink writer (off by default; the ink_* parameters) puts text-like Greek capitals on the recto face as a thin
deposit with a weak density and texture change, and writes exact 3D and per-surface ink truth; `--noink` makes the
twin without the ink. It is a simulator: a score on its volumes is model output on synthetic data and says nothing
about a real scroll. It is not yet calibrated against real CT or real ink (see "Realism: in progress" on the tool
page).

  python -m kit.scrollsim2 make OUT [--preset smoke|pilot] [--scan synchrotron|lab] [--set KEY=VALUE ...]
                                     [--workers N] [--block B]
                                     [--levels L] [--chunk C] [--surfaces] [--resume] [--max-blocks N] [--noink]
  python -m kit.scrollsim2 estimate [--preset ...] [--set ...] [--workers N] [--block B] [--sample K]
  python -m kit.scrollsim2 pyramid OUT [--workers N]     rebuild CT levels 1 and up from level 0, then verify
  python -m kit.scrollsim2 verify OUT                    every CT chunk on disk, no '.partial' temp file
  python -m kit.scrollsim2 publish SRC DST [--levels L ...] [--no-labels]   plain copy of a local folder, then verify
  python -m kit.scrollsim2 vc3d SIM OUT [--voxel-um V] [--copy]   a folder VC3D opens: volumes, surfaces, project
  python -m kit.scrollsim2 nps CT.npy [--mask M.npy] [--tile 32] [--share 0.25] [--out F]   a crop's noise spectrum,
                                     fitted as the `nps` bands (prints the --set value)
  python -m kit.scrollsim2 info OUT

numpy and scipy (the map tools' optional dependencies); zarr for make.
"""

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

VERSION = 2                # 2: the CT scan model (phase, noise spectrum, cupping, slabs) and physical voxel size
ANG = 1024                 # samples of the unwrapped angle per turn
GZ = 8.0                   # z step of the geometry fields, voxels
GS = 8.0                   # along-sheet step of the coarse random fields, voxels
WG = 16.0                  # grid step of the displacement field, voxels
HALFMAX = 1.1774           # sqrt(2 ln 2): a Gaussian's half width at half maximum, in sigmas

# The sheet and scan model. Lengths in output voxels. The defaults are set for about 8 um per voxel; they are
# not a calibration.
BASE = {
    "shape": [256, 512, 512],  # z, y, x of the output volume
    "pitch": 14.0,             # winding center spacing where windings lie apart
    "pitch_sd": 0.12,          # relative smooth variation of that spacing
    "r0": 24.0,                # radius of the sheet's inner end
    "thick": 7.0,              # winding thickness, two plies, voxels
    "thick_sd": 0.15,
    "ply_sigma": 0.8,          # each ply's Gaussian sigma, as a share of a quarter of the thickness
    "fiber": 0.25,             # fiber texture amplitude in each ply
    "contact_share": 0.45,     # share of every interface pressed together
    "zone": 150.0,             # correlation length of the contact field, voxels
    "touch": 0.85,             # center spacing at full contact, as a share of the local thickness
    "delam": 1.5,              # largest ply separation where a winding has split, voxels
    "holes": 0.02,             # share of the sheet missing
    "squash": 0.5,             # minor over major axis of the global crush (1: round)
    "warp": 5.0,               # rms of the smooth displacement, voxels
    "warp_corr": 96.0,         # its correlation length, voxels
    "margin": 10.0,            # air kept between the roll and the box edge (rolled frame), voxels
    "air": 60.0, "bright": 150.0, "noise": 3.0, "blur": 0.9, "bias": 0.08, "rings": 0.0,
    "seed": 0,
}
# Full-scale and scan-model keys. Lengths in output voxels.
EXTRA = {
    "alpha": -1.0,         # crush major axis angle, radians; below 0 draws it at random from the seed
    "tex_z": 1024,         # fiber tile height (periodic), voxels
    "tex_s": 16384,        # fiber tile length along the sheet (periodic), voxels
    "supersample": 1,      # sub-samples per axis averaged into each voxel (partial volume); 1 is the center only
    "psf_z": 0.0,          # extra point spread along z (sigma), combined with blur in quadrature
    "psf_xy": 0.0,         # extra point spread in-plane (sigma)
    "noise_corr": 0.0,     # sigma of the noise correlation, voxels; 0 is white
    "edge": 0.0,           # phase-edge gain: v + edge * (v - G(v, edge_sigma)); 0 off
    "edge_sigma": 1.5,
    # CT scan model (scan model version 2, "How it works" on the tool page). All off at the defaults, so the CT of
    # release 1 is unchanged. The geometry lengths above stay in voxels whatever voxel_um says.
    "scan": "",            # a scan preset (SCANS), applied after --preset and before --set
    "voxel_um": 8.0,       # physical voxel size, um: the OME-Zarr scale and the phase model
    "phase_mm": 0.0,       # propagation distance, mm; 0 is no phase contrast
    "energy_kev": 78.0,    # mean photon energy, keV
    "db_object": 1000.0,   # delta over beta of the sheet against air
    "db_recon": 1000.0,    # delta over beta the Paganin retrieval assumed; 0 is no retrieval (raw phase contrast)
    "phase_halo": 24,      # widest phase-filter kernel radius, voxels; the filter is fitted within it
    "nps": [],             # noise sd per band of NPS_SIGMAS, gray levels, added to `noise`; [] off
    "cupping": 0.0,        # beam hardening: share of sheet contrast lost where the mean path through the roll peaks
    "axis_yx": [],         # rotation axis (y, x), voxels, the center of the rings; [] is the box center
    "slab_z": 0,           # height of the scan's acquisition slabs, voxels; 0 is one slab
    "slab_gain": 0.0,      # sd of each slab's gain step
    # Ink writer ("Ink writer" on the tool page). Off at the defaults (ink_um and ink_depth_um 0), so the CT and
    # labels are unchanged. Thicknesses are in micrometers (converted with voxel_um, in the rolled frame like the sheet); the
    # page layout is in voxels along the sheet (arc length s) and z, like the other geometry lengths.
    "ink_um": 0.0,         # ink deposit on the recto face, um; Parker et al. 2019 measured 3 to 5 um
    "ink_depth_um": 0.0,   # depth inside the recto face the ink reaches, um; Parker et al. 2019: 4 to 12 um more
    "ink_rho": 0.0,        # ink density relative to the papyrus (deposit: 1 + ink_rho of a ply's peak; inside the
                           # face the papyrus density times 1 + ink_rho); above -1
    "ink_tex": 0.0,        # share of the recto fiber texture replaced by a fine isotropic grain within ink_depth_um
    "ink_off": 0,          # 1: the noink twin (ink truth written, nothing painted into the CT)
    "ink_letter": 40.0,    # letter height, voxels (an assumption, set so a test box holds whole letters)
    "ink_advance": 0.8,    # letter advance along the sheet, as a share of the letter height
    "ink_line": 64.0,      # line pitch in z, voxels
    "ink_col": 1024.0,     # column width along the sheet, voxels
    "ink_gap": 192.0,      # gap between columns (and before the first), voxels
    "ink_margin": 48.0,    # top and bottom margin in z, voxels
    "ink_space": 0.18,     # share of letter places left blank (word spaces)
    "ink_stroke": 0.12,    # stroke width of the procedural glyphs, share of the letter height
    "ink_glyphs": "auto",  # auto (DejaVu Sans Greek capitals via Pillow when found, else strokes), font or strokes
}
DEFAULTS = dict(json.loads(json.dumps(BASE)), **EXTRA)
PRESETS = {
    # the unit-test scroll
    "smoke": {"shape": [64, 208, 208]},
    # one full cross-section at a short height: about 125 windings at the defaults (mean step about 10.4 voxels at
    # 45 percent contacts), crush axis along x so the box is about half as tall as wide
    "pilot": {"shape": [1024, 1728, 3264], "alpha": 0.0},
}
HASH_SALT = {"noise": 13, "nps": 200}
NPS_SIGMAS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0)   # noise bands: G(s_j) - G(s_j+1) of white noise; the last is G(4)
CUP_XY, CUP_Z, CUP_ANGLES = 8, 64, 24              # the cupping field's grid (voxels) and its projection angles
# Scan presets: a starting point for each kind of scan, chosen by eye and from published setups. They are not a
# calibration: measurements on real CT (`python -m kit.scrollsim2 nps` for the noise) replace these numbers. Their
# noise is filtered back-projection's ramp: ramp_nps(3.5, 0.5) for the synchrotron, ramp_nps(3.0, 0.3) for the lab.
SCANS = {
    # a synchrotron scan with propagation phase contrast and Paganin retrieval (ESRF BM18-like: 78 keV mean,
    # 22 cm propagation, delta over beta 1000 assumed in the retrieval); the sheet's own delta over beta is set
    # higher, so the retrieval under-corrects and a bright edge stays, as residual fringes do in real scans
    "synchrotron": {"supersample": 2, "phase_mm": 220.0, "energy_kev": 78.0, "db_recon": 1000.0,
                    "db_object": 1500.0, "psf_z": 0.6, "psf_xy": 0.6, "noise": 0.0,
                    "nps": [0.0, 0.5739, 3.4395, 0.0, 0.0, 0.3012, 0.0118], "rings": 0.6, "slab_z": 512, "slab_gain": 0.02},
    # a lab micro-CT scan: no phase contrast, beam hardening, stronger rings, smoother noise
    "lab": {"supersample": 2, "psf_z": 0.9, "psf_xy": 0.9, "noise": 0.0, "nps": [0.0, 0.0, 0.0, 2.4549, 1.7244, 0.0, 0.0049],
            "cupping": 0.15, "rings": 1.2},
}
POINTS_PER_PASS = 1 << 18      # voxels evaluated at once by density_block
INCOMPLETE = 75                # make's exit code when it stopped early (deadline or --max-blocks): resume it


class SimError(ValueError):
    pass


def _np():
    import numpy as np
    return np


def _ndi():
    from scipy import ndimage
    return ndimage


def _field(rng, shape, sigma):
    """Smooth zero-mean, unit-sd random field; sigma in grid cells (one per axis or one for all)."""
    f = _ndi().gaussian_filter(rng.standard_normal(shape), sigma, mode="reflect")
    return (f - f.mean()) / (f.std() + 1e-9)


def _bilerp(np, grid, fi, fj):
    """Bilinear lookup of grid at fractional (fi, fj), clamped to the grid."""
    n0, n1 = grid.shape
    fi = np.clip(fi, 0, n0 - 1.000001)
    fj = np.clip(fj, 0, n1 - 1.000001)
    i0 = fi.astype(np.int64)
    j0 = fj.astype(np.int64)
    a, b = fi - i0, fj - j0
    g = grid.ravel()
    k = i0 * n1 + j0
    return ((1 - a) * ((1 - b) * g[k] + b * g[k + 1]) + a * ((1 - b) * g[k + n1] + b * g[k + n1 + 1]))


def params(over=None, preset=None):
    """All parameters: DEFAULTS, then the preset, then the scan preset (`scan`, from OVER or the preset), then OVER."""
    p = json.loads(json.dumps(DEFAULTS))
    if preset:
        if preset not in PRESETS:
            raise SimError(f"unknown preset {preset}; known: {', '.join(PRESETS)}")
        p.update(json.loads(json.dumps(PRESETS[preset])))
    scan = (over or {}).get("scan", p["scan"]) or ""
    if scan:
        if scan not in SCANS:
            raise SimError(f"unknown scan preset {scan}; known: {', '.join(SCANS)}")
        p.update(json.loads(json.dumps(SCANS[scan])))
    p["scan"] = scan
    for k, v in (over or {}).items():
        if k not in DEFAULTS:
            raise SimError(f"unknown parameter {k}")
        p[k] = v
    _check_scan(p)
    _check_ink(p)
    if int(p["supersample"]) < 1:
        raise SimError("supersample is 1 or more")
    for k in ("psf_z", "psf_xy", "noise_corr", "edge"):
        if float(p[k]) < 0:
            raise SimError(f"{k} is 0 or more")
    if int(p["tex_z"]) < 16 or int(p["tex_s"]) < 16:
        raise SimError("tex_z and tex_s are 16 or more")
    p["shape"] = [int(x) for x in p["shape"]]
    if len(p["shape"]) != 3 or min(p["shape"]) < 16:
        raise SimError("shape is three sizes of 16 voxels or more")
    if not 0.2 <= float(p["squash"]) <= 1.0:
        raise SimError("squash lies in 0.2 to 1")
    if not 0.0 <= float(p["contact_share"]) < 1.0:
        raise SimError("contact_share lies in 0 to 1")
    if float(p["pitch"]) <= float(p["thick"]):
        raise SimError("pitch must exceed thick")
    return p


def _check_scan(p):
    """Refuse scan-model values out of range (in place: lists become lists of floats)."""
    for k in ("voxel_um", "energy_kev", "db_object"):
        if not float(p[k]) > 0:
            raise SimError(f"{k} is above 0")
    for k in ("phase_mm", "db_recon", "cupping", "slab_gain"):
        if float(p[k]) < 0:
            raise SimError(f"{k} is 0 or more")
    if float(p["cupping"]) >= 1:
        raise SimError("cupping lies in 0 to below 1")
    if int(p["phase_halo"]) < 2:
        raise SimError("phase_halo is 2 or more")
    if int(p["slab_z"]) < 0:
        raise SimError("slab_z is 0 or more")
    nps = p["nps"]
    if not isinstance(nps, (list, tuple)) or (len(nps) and len(nps) != len(NPS_SIGMAS)):
        raise SimError(f"nps is [] or {len(NPS_SIGMAS)} band sds, one per band of {list(NPS_SIGMAS)}")
    p["nps"] = [float(v) for v in nps]
    if any(v < 0 for v in p["nps"]):
        raise SimError("every nps band sd is 0 or more")
    ax = p["axis_yx"]
    if not isinstance(ax, (list, tuple)) or len(ax) not in (0, 2):
        raise SimError("axis_yx is [] or [y, x]")
    p["axis_yx"] = [float(v) for v in ax]


def _check_ink(p):
    """Refuse ink-writer values out of range."""
    for k in ("ink_um", "ink_depth_um", "ink_tex", "ink_gap", "ink_margin", "ink_stroke"):
        if float(p[k]) < 0:
            raise SimError(f"{k} is 0 or more")
    if float(p["ink_tex"]) > 1:
        raise SimError("ink_tex lies in 0 to 1")
    if float(p["ink_rho"]) <= -1:
        raise SimError("ink_rho is above -1")
    if int(p["ink_off"]) not in (0, 1):
        raise SimError("ink_off is 0 or 1")
    if float(p["ink_letter"]) < 4 or float(p["ink_advance"]) <= 0:
        raise SimError("ink_letter is 4 voxels or more and ink_advance above 0")
    if float(p["ink_line"]) < float(p["ink_letter"]):
        raise SimError("ink_line is ink_letter or more")
    if float(p["ink_col"]) < float(p["ink_letter"]) * float(p["ink_advance"]):
        raise SimError("ink_col holds at least one letter")
    if not 0 <= float(p["ink_space"]) < 1:
        raise SimError("ink_space lies in 0 to below 1")
    if p["ink_glyphs"] not in ("auto", "font", "strokes"):
        raise SimError("ink_glyphs is auto, font or strokes")


def noink(over=None):
    """The noink twin of OVER: the same parameters with the ink left out of the CT (its truth is still written)."""
    return dict(over or {}, ink_off=1)


def _base_params(p):
    """The sheet-model keys of P, checked."""
    p = {k: p.get(k, v) for k, v in json.loads(json.dumps(BASE)).items()}
    p["shape"] = [int(x) for x in p["shape"]]
    return p


def _mix64(np, x):
    """splitmix64 finalizer on uint64 arrays."""
    x = (x + np.uint64(0x9E3779B97F4A7C15)) & np.uint64(0xFFFFFFFFFFFFFFFF)
    x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return x ^ (x >> np.uint64(31))


def _hash3(np, seed, salt, z, y, x):
    """A uint64 hash of integer grid positions (broadcast arrays), the seed and a salt."""
    with np.errstate(over="ignore"):
        h = _mix64(np, np.uint64(int(seed) & 0xFFFFFFFF) * np.uint64(1000003) + np.uint64(salt))
        for a in (z, y, x):
            h = _mix64(np, h ^ (np.asarray(a).astype(np.int64).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)))
    return h


def hashed_normal(seed, z0, z1, y0, y1, x0, x1, salt=HASH_SALT["noise"]):
    """Standard normal noise on the box [z0, z1) x [y0, y1) x [x0, x1), a function of each voxel's position only."""
    np = _np()
    z = np.arange(z0, z1)[:, None, None]
    y = np.arange(y0, y1)[None, :, None]
    x = np.arange(x0, x1)[None, None, :]
    with np.errstate(over="ignore"):
        h = _hash3(np, seed, salt, z, y, x)
        h2 = _mix64(np, h)
    u1 = ((h >> np.uint64(11)).astype(np.float64) + 0.5) / 9007199254740992.0
    u2 = (h2 >> np.uint64(11)).astype(np.float64) / 9007199254740992.0
    return (np.sqrt(-2.0 * np.log(u1)) * np.cos(2 * math.pi * u2)).astype(np.float32)


def _smooth_noise_gain(sigma):
    """sd of 3D white unit noise after a Gaussian of sigma voxels (continuous approximation, exact for sigma >= 1)."""
    return 1.0 / math.sqrt((2.0 * math.sqrt(math.pi) * sigma) ** 3)


# ---------------------------------------------------------------------------------------------------- scan model
def _taps(sigma):
    """The 1D kernel scipy's gaussian_filter applies for SIGMA (truncate 4); [1] for 0."""
    np = _np()
    if sigma <= 0:
        return np.ones(1)
    r = int(4.0 * sigma + 0.5)
    d = np.zeros(2 * r + 1)
    d[r] = 1.0
    return _ndi().gaussian_filter1d(d, sigma, mode="constant")


def _transfer1(sigma, f):
    """The real transfer of _taps(SIGMA) at frequencies F, cycles per voxel (its DTFT, exact)."""
    np = _np()
    t = _taps(sigma)
    r = (len(t) - 1) // 2
    j = np.arange(-r, r + 1)
    return np.cos(2 * math.pi * np.asarray(f, np.float64)[..., None] * j) @ t


def _band_transfer(j, fz, fy, fx):
    """Transfer of noise band J on broadcast frequency grids: G(s_j) - G(s_j+1), the last band G(s_last)."""
    s = NPS_SIGMAS
    g = _transfer1(s[j], fz) * _transfer1(s[j], fy) * _transfer1(s[j], fx)
    if j + 1 < len(s):
        g = g - _transfer1(s[j + 1], fz) * _transfer1(s[j + 1], fy) * _transfer1(s[j + 1], fx)
    return g


_NPS_GAIN = {}


def nps_band_gain(j):
    """sd of band J's output for unit white noise (exact for scipy's kernels: Parseval on a 72-point grid, longer
    than any kernel)."""
    if j not in _NPS_GAIN:
        np = _np()
        f = np.fft.fftfreq(72)
        t = _band_transfer(j, f[:, None, None], f[None, :, None], f[None, None, :])
        _NPS_GAIN[j] = float(math.sqrt(float((t * t).mean())))
    return _NPS_GAIN[j]


def nps_band_psd(j, fz, fy, fx):
    """Band J's noise power spectrum at unit variance (mean 1 over the frequency cube)."""
    return (_band_transfer(j, fz, fy, fx) / nps_band_gain(j)) ** 2


def _radial(np, vals, rad, nbins, n):
    """Mean of VALS in shells of |f| one grid step (1/N) wide: centers, means, counts (empty shells dropped)."""
    k = np.minimum(np.rint(rad * n).astype(np.int64), nbins - 1).ravel()
    cnt = np.bincount(k, minlength=nbins)
    tot = np.bincount(k, weights=vals.ravel(), minlength=nbins)
    keep = cnt > 0
    return (np.arange(nbins) / n)[keep], tot[keep] / cnt[keep], cnt[keep]


def measure_nps(vol, tile=32, share=0.25, mask=None):
    """The noise power spectrum of a CT crop, label-free: split VOL (z, y, x) into TILE^3 tiles, keep those inside
    MASK (all of the tile) or every tile, take the SHARE with the least structure (variance after a Gaussian of 2
    voxels; gaps and air), and average their Hann-windowed periodograms, mean removed. The PSD's mean over the
    frequency cube is the noise variance. Returns freq (cycles per voxel, shell centers), psd, count per shell,
    variance, tiles used."""
    np = _np()
    nd = _ndi()
    v = np.asarray(vol, np.float64)
    if v.ndim != 3 or min(v.shape) < tile:
        raise SimError(f"the crop is {list(v.shape)}; nps needs a 3D crop of at least {tile} voxels per axis")
    if mask is not None and np.asarray(mask).shape != v.shape:
        raise SimError("the mask's shape differs from the crop's")
    cand = []
    for z in range(0, v.shape[0] - tile + 1, tile):
        for y in range(0, v.shape[1] - tile + 1, tile):
            for x in range(0, v.shape[2] - tile + 1, tile):
                box = (slice(z, z + tile), slice(y, y + tile), slice(x, x + tile))
                if mask is not None and not np.asarray(mask)[box].all():
                    continue
                cand.append((float(nd.gaussian_filter(v[box], 2.0).var()), box))
    if not cand:
        raise SimError("no tile lies wholly inside the mask")
    cand.sort(key=lambda c: c[0])
    use = cand[:max(1, int(round(share * len(cand))))]
    w1 = _hann(tile)
    w = w1[:, None, None] * w1[None, :, None] * w1[None, None, :]
    acc = np.zeros((tile,) * 3)
    for _, box in use:
        t = v[box] - v[box].mean()
        acc += np.abs(np.fft.fftn(t * w)) ** 2 / (w * w).sum()
    acc /= len(use)
    f = np.fft.fftfreq(tile)
    rad = np.sqrt(f[:, None, None] ** 2 + f[None, :, None] ** 2 + f[None, None, :] ** 2)
    nb = int(math.ceil(math.sqrt(3) / 2 * tile)) + 1
    fr, ps, cnt = _radial(np, acc, rad, nb, tile)
    return {"freq": [round(float(x), 6) for x in fr], "psd": [float(x) for x in ps], "count": [int(c) for c in cnt],
            "variance": float(acc.mean()), "tile": int(tile), "tiles": len(use), "tiles_seen": len(cand)}


def _hann(tile):
    return _np().hanning(int(tile) + 2)[1:-1]


def _windowed_band(j, tile):
    """The expected Hann-windowed periodogram of unit-variance band J on a TILE^3 grid, as measure_nps takes it:
    the band's autocovariance times the window's autocorrelation, transformed (exact; every term is separable)."""
    np = _np()
    n = int(tile)
    w = _hann(n)
    ww = np.correlate(w, w, "full")                       # lags -(n-1) .. n-1
    lag = np.arange(-(n - 1), n)
    f = np.fft.fftfreq(n)
    cosm = np.cos(2 * math.pi * f[:, None] * lag[None, :])

    def c1(x, y):
        """sum over lags of (x corr y)(lag) ww(lag) cos(2 pi f lag), for centered symmetric taps X and Y."""
        full = np.correlate(y, x, "full")                 # lags -(len(x)-1) .. len(y)-1 about the centers
        rx, ry = (len(x) - 1) // 2, (len(y) - 1) // 2
        lags = np.arange(-(len(x) - 1), len(y)) - (ry - rx)
        keep = np.abs(lags) <= n - 1
        acc = np.zeros(2 * n - 1)
        acc[lags[keep] + n - 1] = full[keep]
        return cosm @ (acc * ww)
    a = _taps(NPS_SIGMAS[j])
    terms = [(1.0, c1(a, a))]
    if j + 1 < len(NPS_SIGMAS):
        b = _taps(NPS_SIGMAS[j + 1])
        terms += [(-2.0, c1(a, b)), (1.0, c1(b, b))]
    out = np.zeros((n, n, n))
    for sgn, c in terms:
        out += sgn * c[:, None, None] * c[None, :, None] * c[None, None, :]
    return out / float((w * w).sum()) ** 3 / nps_band_gain(j) ** 2


def fit_nps(freq, psd, count=None, tile=32):
    """Band sds (one per NPS_SIGMAS band) whose summed spectrum fits a radial PSD (measure_nps's freq, psd and
    count, at the same TILE), by non-negative least squares on shells weighted by their size. Each band enters as
    its expected windowed periodogram, so the window's smoothing does not bias the fit. Returns nps (the sds), the
    fitted variance and the weighted relative error of the fit."""
    np = _np()
    from scipy.optimize import nnls
    fr = np.asarray(freq, np.float64)
    ps = np.asarray(psd, np.float64)
    cnt = np.ones_like(fr) if count is None else np.asarray(count, np.float64)
    # each band's radial spectrum on the same tile grid and shells as measure_nps
    f = np.fft.fftfreq(int(tile))
    fz, fy, fx = f[:, None, None], f[None, :, None], f[None, None, :]
    rad = np.sqrt(fz ** 2 + fy ** 2 + fx ** 2)
    nb = int(math.ceil(math.sqrt(3) / 2 * tile)) + 1
    cols = []
    for j in range(len(NPS_SIGMAS)):
        c, m, _ = _radial(np, _windowed_band(j, tile), rad, nb, int(tile))
        cols.append(np.interp(fr, c, m))
    A = np.stack(cols, 1)
    wt = np.sqrt(cnt) * (fr > 0)                          # the zero shell is mostly the removed mean: left out
    c, _ = nnls(A * wt[:, None], ps * wt)
    fit = A @ c
    err = float(np.sqrt(((fit - ps) ** 2 * cnt).sum() / max((ps ** 2 * cnt).sum(), 1e-30)))
    return {"nps": [round(float(math.sqrt(max(x, 0.0))), 4) for x in c], "variance_fit": float(c.sum()),
            "relative_error": round(err, 4)}


def ramp_nps(total_sd, cutoff=0.5, n=32):
    """Band sds for the noise of filtered back-projection: a ramp |f| times a Hann window that reaches 0 at CUTOFF
    (cycles per voxel), scaled to TOTAL_SD gray levels, fitted to the NPS_SIGMAS bands by non-negative least
    squares in relative terms on an N^3 frequency grid, then scaled to the total. The coarse band ladder gives the
    ramp's shape, low at low frequency and peaked toward the cutoff, not its exact curve. Returns the `nps` list."""
    np = _np()
    from scipy.optimize import nnls
    f = np.fft.fftfreq(int(n))
    fz, fy, fx = f[:, None, None], f[None, :, None], f[None, None, :]
    rad = np.sqrt(fz ** 2 + fy ** 2 + fx ** 2)
    tgt = np.where(rad < cutoff, rad * np.cos(math.pi * rad / (2 * cutoff)) ** 2, 0.0)
    tgt *= float(total_sd) ** 2 / tgt.mean()
    A = np.stack([nps_band_psd(j, fz, fy, fx).ravel() for j in range(len(NPS_SIGMAS))], 1)
    w = 1.0 / np.maximum(tgt.ravel(), 0.1 * tgt.mean())   # relative errors, so the few low-frequency bins count
    c, _ = nnls(A * w[:, None], tgt.ravel() * w)
    c *= float(total_sd) ** 2 / max(float(c.sum()), 1e-30)   # each band has unit variance: keep the total
    return [round(float(math.sqrt(max(x, 0.0))), 4) for x in c]


WAVE_UM_KEV = 1.239842e-3      # photon wavelength in um times its energy in keV
PHASE_TOL = 0.01               # the phase filter's largest transfer error, when phase_halo allows it


def phase_model(p):
    """The image-domain phase model for parameters P, or None when phase_mm is 0.

    Propagation over phase_mm turns the sheet's density into (1 + a_o k^2) times it in frequency (the
    transport-of-intensity form Paganin's method inverts), with a = distance x delta/beta x wavelength / (4 pi), in
    voxels squared; Paganin retrieval with db_recon divides by (1 + a_r k^2). Linear in the weak-absorption limit,
    and isotropic in 3D for a parallel beam about the z axis. With db_recon 0 the raw phase contrast is
    v - a_o * laplacian(v). Otherwise the result is (a_o/a_r) v + (1 - a_o/a_r) Y(v), where Y = 1/(1 + a_r k^2)
    is fitted as the fewest Gaussians (up to 11) within PHASE_TOL whose kernels fit inside phase_halo; max_error is
    the fit's largest transfer error up to the axis Nyquist frequency."""
    if float(p["phase_mm"]) <= 0:
        return None
    np = _np()
    from scipy.optimize import nnls
    lam = WAVE_UM_KEV / float(p["energy_kev"])
    vox = float(p["voxel_um"])
    a_of = lambda db: float(p["phase_mm"]) * 1000.0 * float(db) * lam / (4 * math.pi) / vox ** 2   # noqa: E731
    a_o = a_of(p["db_object"])
    out = {"a_object_vox2": a_o, "length_object_um": math.sqrt(a_o) * vox}
    if float(p["db_recon"]) <= 0:
        out.update(raw=True, halo=1, max_error=0.0)
        return out
    a_r = a_of(p["db_recon"])
    smax = min(int(p["phase_halo"]) / 4.0, 2.5 * math.sqrt(a_r) + 0.5)
    k = np.linspace(0, math.pi * math.sqrt(3), 600)
    target = 1.0 / (1.0 + a_r * k * k)

    def fit(sig):
        A = np.stack([np.exp(-0.5 * s * s * k * k) for s in sig], 1)
        A = np.vstack([A, 1e3 * np.ones((1, len(sig)))])  # the k = 0 row, heavily weighted: the gain at DC is 1
        w, _ = nnls(A, np.append(target, 1e3))
        return w / w.sum()
    kk = k[k <= math.pi]
    best = None
    for n in range(1, 11):                                # the fewest kernels within PHASE_TOL (each costs a filter)
        sig = [0.0] + [float(s) for s in np.geomspace(0.35, max(smax, 0.36), n)]
        wts = fit(sig)
        sig = [s for s, w in zip(sig, wts) if w >= 2e-3]
        wts = fit(sig)
        err = float(np.abs(np.stack([np.exp(-0.5 * s * s * kk * kk) for s in sig], 1) @ wts
                           - 1.0 / (1.0 + a_r * kk * kk)).max())
        if best is None or err < best[0] - 1e-6:
            best = (err, sig, wts)
        if err <= PHASE_TOL:
            break
    err, sig, wts = best
    used = [(s, float(w)) for s, w in zip(sig, wts) if w > 0]
    out.update(raw=False, a_recon_vox2=a_r, length_recon_um=math.sqrt(a_r) * vox, ratio=a_o / a_r,
               gaussians=[[round(s, 4), round(w, 6)] for s, w in used],
               max_error=round(err, 4),
               halo=int(math.ceil(4 * max(s for s, _ in used))) + 1)
    return out


def apply_phase(v, ph):
    """PHASE_MODEL's filter PH applied to a gray volume V (float32 out). Kernels reach ph["halo"] voxels; values
    nearer the edge of V are approximate (scan_block renders a halo for that)."""
    np = _np()
    nd = _ndi()
    v = np.asarray(v, np.float32)
    if ph["raw"]:
        return v - np.float32(ph["a_object_vox2"]) * nd.laplace(v, mode="nearest")
    y = np.zeros_like(v)
    for s, w in ph["gaussians"]:
        y += np.float32(w) * (nd.gaussian_filter(v, s, mode="nearest") if s > 0 else v)
    r = ph["ratio"]
    return np.float32(r) * v + np.float32(1 - r) * y


def scan_report(p):
    """The derived scan model for parameters P, as truth.json records it."""
    ph = phase_model(p)
    nps = [float(v) for v in p["nps"]]
    return {"version": 2, "scan": p["scan"] or None, "voxel_um": float(p["voxel_um"]),
            "phase": ph, "nps_total_sd": round(math.sqrt(sum(v * v for v in nps)), 4) if nps else 0.0,
            "cupping": float(p["cupping"]), "slab_z": int(p["slab_z"]), "slab_gain": float(p["slab_gain"]),
            "axis_yx": p["axis_yx"] or None}


# ------------------------------------------------------------------ ink writer (off by default)
# Carbon ink on the recto face: a thin deposit outside the face, a zone just inside it with a density change and a
# grain texture, and an exact truth of both. The physics follows Parker et al., "From invisibility to readability:
# Recovering the ink of Herculaneum", PLoS ONE 14(5): e0215775 (2019),
# https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0215775 (read 2026-11-18): the ink layer is 3 to
# 5 um thick, absorption adds 4 to 12 um of depth, and x-rays pass through the carbon ink and carbonized papyrus in
# almost exactly the same way. The layout numbers (letter size, lines, columns) are assumptions, not measurements.
INK_GREEK = "".join(chr(c) for c in range(0x391, 0x3AA) if c != 0x3A2)   # the 24 Greek capitals
INK_PX = 48                    # glyph atlas cell height, pixels
INK_SALT = 300                 # hash salt of the page layout (300 the letter, 301 the line length)
INK_FONTS = ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
             "/Library/Fonts/DejaVuSans.ttf", "/opt/homebrew/share/fonts/DejaVuSans.ttf")
INK_SHARE_SAMPLES = 1 << 20    # random sheet points behind the recorded pattern share


def _font_glyphs(np, H, W):
    """Greek capitals in DejaVu Sans, rendered by Pillow at 4x and box-filtered to coverage; None when unavailable."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    font = None
    for path in INK_FONTS:
        try:
            font = ImageFont.truetype(path, 100)
            break
        except OSError:
            continue
    if font is None:
        return None
    S = 4 * H
    b = font.getbbox("Η")                     # the cap height of Eta sets the size: caps fill 70 percent
    size = max(4, int(round(100 * 0.7 * S / max(1, b[3] - b[1]))))
    font = ImageFont.truetype(font.path, size)
    base = int(round(0.85 * S))
    out = np.zeros((len(INK_GREEK), H, W), np.float32)
    for g, ch in enumerate(INK_GREEK):
        im = Image.new("L", (S, S), 0)
        d = ImageDraw.Draw(im)
        x0, _, x1, _ = d.textbbox((0, base), ch, font=font, anchor="ls")
        d.text(((S - (x1 - x0)) / 2 - x0, base), ch, font=font, fill=255, anchor="ls")
        out[g] = np.asarray(im.resize((W, H), Image.BOX), np.float32) / 255.0
    return out


def _stroke_glyphs(np, H, W, stroke):
    """Procedural letter-like glyphs: two to four straight strokes between points of a 3 x 3 grid, a fixed alphabet."""
    k = 4
    yy, xx = np.mgrid[0:H * k, 0:W * k]
    py = (yy + 0.5) / (H * k)
    px = (xx + 0.5) / (W * k)
    anchors = [(y, x) for y in (0.15, 0.5, 0.85) for x in (0.15, 0.5, 0.85)]
    out = np.zeros((len(INK_GREEK), H, W), np.float32)
    for g in range(len(INK_GREEK)):
        rng = np.random.default_rng([INK_SALT, g])
        dist = np.full(py.shape, np.inf)
        for _ in range(2 + g % 3):
            i, j = rng.choice(len(anchors), 2, replace=False)
            (ay, ax), (by, bx) = anchors[i], anchors[j]
            ay, by = ay * H, by * H                    # in letter-height units (pixels of H)
            ax, bx = ax * W, bx * W
            qy, qx = py * H, px * W
            vy, vx = by - ay, bx - ax
            t = np.clip(((qy - ay) * vy + (qx - ax) * vx) / (vy * vy + vx * vx), 0, 1)
            dist = np.minimum(dist, np.hypot(qy - ay - t * vy, qx - ax - t * vx))
        hit = (dist <= 0.5 * float(stroke) * H).astype(np.float32)
        out[g] = hit.reshape(H, k, W, k).mean((1, 3))
    return out


def ink_glyphs(mode="auto", advance=0.8, stroke=0.12):
    """The glyph atlas, float32 (24, INK_PX, W) coverage in 0 to 1 with W = advance * INK_PX, and its source:
    'font:DejaVuSans' or 'strokes'. MODE auto takes the font when Pillow finds it; font refuses without it."""
    np = _np()
    H = INK_PX
    W = max(4, int(round(float(advance) * H)))
    if mode in ("auto", "font"):
        a = _font_glyphs(np, H, W)
        if a is not None:
            return a, "font:DejaVuSans"
        if mode == "font":
            raise SimError("ink_glyphs font needs Pillow and the DejaVu Sans font")
    return _stroke_glyphs(np, H, W, stroke), "strokes"


def _box2_cdf(np, x, a, b):
    """CDF at X of the sum of two centered uniform variables of widths A and B: a voxel's extent along a direction
    that is the sum of two of its edges' projections."""
    a, b = np.maximum(a, b), np.maximum(np.minimum(a, b), 1e-9)
    t = x + 0.5 * (a + b)
    return np.where(t <= 0, 0.0, np.where(t <= b, t * t / (2 * a * b), np.where(
        t <= a, (t - 0.5 * b) / a, np.where(t < a + b, 1 - (a + b - t) ** 2 / (2 * a * b), 1.0))))


def ink_share(np, d, lo, hi, a, b):
    """Share of a voxel centered at normal coordinate D whose extent along the normal is a box of width A plus one of
    width B, that lies in the slab [LO, HI]: the exact partial volume of a flat layer across a parallelepiped."""
    return _box2_cdf(np, hi - d, a, b) - _box2_cdf(np, lo - d, a, b)


class Roll:
    """The geometry and the truth of one rolled, pressed and crushed sheet, rebuilt exactly from its parameters.
    Every random field comes from the seed in a fixed order, so the same parameters give the same scroll."""

    def __init__(self, p):
        np = _np()
        self.p = p = _base_params(p)
        self.Z, self.Y, self.X = Z, Y, X = p["shape"]
        rng = np.random.default_rng(int(p["seed"]))
        self.center = np.array([(X - 1) / 2.0, (Y - 1) / 2.0])
        self.alpha = float(rng.uniform(0, math.pi))            # direction of the crush's major axis
        pitch, r0 = float(p["pitch"]), float(p["r0"])
        rmax = 0.5 * min(X, Y) - float(p["margin"]) - 2.5 * float(p["warp"])
        if rmax < r0 + 2 * pitch:
            raise SimError("the box holds less than two windings; raise shape or lower pitch")
        turns = int(math.ceil((rmax - r0) / (pitch * (1 - p["contact_share"]) * (1 - p["pitch_sd"]))))
        turns = max(turns, 3) + 4
        n = turns * ANG
        self.dth = 2 * math.pi / ANG
        th = np.arange(n) * self.dth
        self.nz = int(math.ceil(Z / GZ)) + 3                    # z grid from -GZ to beyond Z
        zc = (np.arange(self.nz) - 1) * GZ
        snom = r0 * th + pitch * th ** 2 / (4 * math.pi)
        ns = int(snom[-1] / GS) + 3

        def along(sig_vox, sig_z=None):
            f = _field(rng, (ns, self.nz), (sig_vox / GS, (sig_z or sig_vox) / GZ))
            return _bilerp(np, f, np.repeat(snom[:, None] / GS, self.nz, 1), np.repeat(np.arange(self.nz)[None], n, 0))

        thick = float(p["thick"]) * np.clip(1 + float(p["thick_sd"]) * along(40.0), 0.5, None)
        apart = pitch * (1 + float(p["pitch_sd"]) * along(120.0))
        c = along(float(p["zone"]))
        cs = float(p["contact_share"])
        touch = float(p["touch"]) * thick
        zin = (zc >= -GZ / 2) & (zc <= Z - 1 + GZ / 2)
        used = n
        for _ in range(4):                                      # the contact quantile over the sheet that is used
            if cs > 0:                                          # ramp: the top third of each zone fully pressed
                lo, hi = np.quantile(c[ANG:max(used, ANG + 1)], [1 - cs, 1 - cs / 3])
                press = np.clip((c - lo) / max(hi - lo, 1e-6), 0, 1)
            else:
                press = np.zeros_like(c)
            press[:ANG] = 0                                     # the first turn has no winding inside it
            gap = np.maximum((1 - press) * apart + press * touch, 0.75 * touch)
            R = np.empty((n, self.nz))
            R[:ANG] = r0 + pitch * th[:ANG, None] / (2 * math.pi)
            for t in range(1, turns):
                R[t * ANG:(t + 1) * ANG] = R[(t - 1) * ANG:t * ANG] + gap[t * ANG:(t + 1) * ANG]
            over = np.flatnonzero(R[:, zin].max(1) > rmax)
            end = min(int(over[0]) if len(over) else n, n - ANG)    # one turn of headroom for lookups
            if end == used:
                break
            used = end
        self.n_end = end
        self.theta_end = (end - 1) * self.dth
        self.R, self.thick, self.press = R, thick, press
        dl = np.clip(along(30.0) - 1.0, 0, None)
        self.delam = float(p["delam"]) * dl / (dl.max() + 1e-9) * (1 - press)
        holef = along(16.0)
        self.hole = holef < (np.quantile(holef, float(p["holes"])) if float(p["holes"]) > 0 else -np.inf)
        rbar = R[:, zin].mean(1)
        self.s = np.concatenate([[0.0], np.cumsum(0.5 * (rbar[1:] + rbar[:-1]) * self.dth)])
        self.s_end = float(self.s[end - 1])
        self.th = th
        # the displacement field (output frame, backward: rolled point = unsquash(out + D(out)))
        wshape = (int(Z / WG) + 3, int(Y / WG) + 3, int(X / WG) + 3)
        sig = float(p["warp_corr"]) / WG
        self.D = np.stack([_field(rng, wshape, sig) for _ in range(3)], 0) * (float(p["warp"]) / math.sqrt(3))
        self.D[2] *= 0.5                                        # less bending along the axis
        self._rng_state = rng.bit_generator.state
        self._tex = None
        self.max_k = int(math.ceil(self.theta_end / (2 * math.pi))) + 1

    # ------------------------------------------------------------------ frames
    def _disp(self, xyz):
        """D at output points xyz (N, 3) as x, y, z."""
        np = _np()
        nd = _ndi()
        co = np.stack([xyz[:, 2] / WG + 1, xyz[:, 1] / WG + 1, xyz[:, 0] / WG + 1])
        return np.stack([nd.map_coordinates(self.D[i], co, order=1, mode="nearest") for i in range(3)], 1)

    def _squash(self, xy, inverse=False):
        np = _np()
        s = float(self.p["squash"])
        ca, sa = math.cos(self.alpha), math.sin(self.alpha)
        d = xy - self.center
        u = d[:, 0] * ca + d[:, 1] * sa
        v = -d[:, 0] * sa + d[:, 1] * ca
        v = v / s if inverse else v * s
        return np.stack([self.center[0] + u * ca - v * sa, self.center[1] + u * sa + v * ca], 1)

    def rolled(self, out):
        """Rolled-frame points (x, y, z) of output points (N, 3)."""
        np = _np()
        q = out + self._disp(out)
        return np.concatenate([self._squash(q[:, :2], inverse=True), q[:, 2:3]], 1)

    def forward(self, rolled, iters=12):
        """Output points of rolled-frame points (fixed point of out = squash(rolled) - D(out)) and the residual."""
        np = _np()
        q = np.concatenate([self._squash(rolled[:, :2]), rolled[:, 2:3]], 1)
        out = q.copy()
        for _ in range(iters):
            out = q - self._disp(out)
        res = np.abs(out + self._disp(out) - q).max(1) if len(out) else np.zeros(0)
        return out, res

    def center_line(self, step=8.0):
        """The output-frame center line: (x, y, z) points of the rolled axis."""
        np = _np()
        z = np.arange(-GZ, self.Z + GZ, step)
        pts = np.stack([np.full_like(z, self.center[0]), np.full_like(z, self.center[1]), z], 1)
        return self.forward(pts)[0]

    def _center_at(self, cl, z):
        np = _np()
        return np.interp(z, cl[:, 2], cl[:, 0]), np.interp(z, cl[:, 2], cl[:, 1])

    # ------------------------------------------------------------------ sheet lookups
    def _fi(self, theta):
        return theta / self.dth

    def _fz(self, z):
        return z / GZ + 1

    def R_at(self, theta, z):
        np = _np()
        r = _bilerp(np, self.R, self._fi(theta), self._fz(z))
        return np.where((theta >= 0) & (theta <= self.theta_end), r, np.inf)

    def at(self, grid, theta, z):
        return _bilerp(_np(), grid.astype(_np().float64), self._fi(theta), self._fz(z))

    def s_at(self, theta):
        np = _np()
        return np.interp(theta, self.th[:self.n_end], self.s[:self.n_end])

    def theta_of_s(self, s):
        np = _np()
        return np.interp(s, self.s[:self.n_end], self.th[:self.n_end])

    def face_offset(self, theta, z):
        """Recto (inner) face, as an offset from the winding center (negative), voxels."""
        t = self.at(self.thick, theta, z)
        d = self.at(self.delam, theta, z)
        sig = float(self.p["ply_sigma"]) * t / 4
        return -(t / 4 + d / 2 + HALFMAX * sig)

    def hole_at(self, theta, z):
        np = _np()
        i = np.clip(np.rint(self._fi(theta)).astype(np.int64), 0, self.hole.shape[0] - 1)
        j = np.clip(np.rint(self._fz(z)).astype(np.int64), 0, self.hole.shape[1] - 1)
        return self.hole[i, j]

    # ------------------------------------------------------------------ voxels
    def voxels_all_turns(self, out):
        """The reference lookup: density, turn index (-1 none) and its theta at output points (N, 3), from the
        radius of every turn at each point's angle. Slow at full scale (one lookup per turn); Scroll2.voxels finds
        the same turn by binary search, and the tests hold the two equal."""
        np = _np()
        p = self.p
        rolled = self.rolled(out)
        d = rolled[:, :2] - self.center
        rho = np.hypot(d[:, 0], d[:, 1])
        phi = np.mod(np.arctan2(d[:, 1], d[:, 0]), 2 * math.pi)
        z = rolled[:, 2]
        th = phi[None] + 2 * math.pi * np.arange(self.max_k + 1)[:, None]
        Rk = self.R_at(th, np.broadcast_to(z, th.shape))
        N = len(rho)
        j = (Rk <= rho[None]).sum(0) - 1
        dens = np.zeros(N, np.float64)
        best = np.full(N, np.inf)
        lab = np.full(N, -1, np.int64)
        idx = np.arange(N)
        for dk in (-1, 0, 1, 2):
            k = j + dk
            ok = (k >= 0) & (k <= self.max_k)
            kk = np.clip(k, 0, self.max_k)
            rk = Rk[kk, idx]
            ok &= np.isfinite(rk)
            if not ok.any():
                continue
            thk = th[kk, idx]
            d = np.where(ok, rho - rk, np.inf)
            t = self.at(self.thick, np.where(ok, thk, 0), z)
            dl = self.at(self.delam, np.where(ok, thk, 0), z)
            half = t / 4 + dl / 2
            sig = float(p["ply_sigma"]) * t / 4
            s = self.s_at(np.where(ok, thk, 0))
            tr = self._tex_at("recto", z, s)
            tv = self._tex_at("verso", z, s)
            hole = self.hole_at(np.where(ok, thk, 0), z)
            amp = np.where(hole, 0.2, 1.0)
            fib = float(p["fiber"])
            recto = np.exp(-0.5 * ((d + half) / sig) ** 2) * (1 + fib * tr)
            verso = np.exp(-0.5 * ((d - half) / sig) ** 2) * (1 + fib * tv)
            dens += np.where(ok, amp * (recto + verso), 0)
            band = np.abs(d) <= half + HALFMAX * sig
            near = ok & band & (np.abs(d) < best)
            best = np.where(near, np.abs(d), best)
            lab = np.where(near, kk, lab)
        return dens, lab, th[np.clip(lab, 0, self.max_k), idx]

    def winding_id(self, theta, out_xy, cl, z_out):
        """Winding numbers in the output frame: one step across the +x half-plane from the center line."""
        np = _np()
        cx, cy = self._center_at(cl, z_out)
        phi = np.mod(np.arctan2(out_xy[:, 1] - cy, out_xy[:, 0] - cx), 2 * math.pi)
        return np.rint((theta - phi) / (2 * math.pi)).astype(np.int64) + 1    # the inner partial turn is 0 or 1

    def surface(self, step=4.0, which="center"):
        """The whole sheet as one grid on (z, s): output points (H, W, 3) as x, y, z, the validity mask, the
        winding id per vertex, theta, and the press value (0 apart, 1 fully pressed). which: center or recto."""
        np = _np()
        zs = np.arange(0.0, self.Z - 1 + 1e-9, step)
        s0 = float(self.s[0])
        ss = np.arange(s0, self.s_end, step)
        th = self.theta_of_s(ss)
        TH, ZZ = np.meshgrid(th, zs)
        r = self.R_at(TH, ZZ)
        if which == "recto":
            r = r + self.face_offset(TH, ZZ)
        elif which != "center":
            raise SimError("which is center or recto")
        rolled = np.stack([self.center[0] + r * np.cos(TH), self.center[1] + r * np.sin(TH), ZZ], -1).reshape(-1, 3)
        out, res = self.forward(rolled)
        out = out.reshape(TH.shape + (3,))
        lim = np.array([self.X - 1, self.Y - 1, self.Z - 1], np.float64)
        valid = np.isfinite(out).all(-1) & (out >= 0).all(-1) & (out <= lim).all(-1) & np.isfinite(r)
        cl = self.center_line()
        wid = self.winding_id(TH.ravel(), out.reshape(-1, 3)[:, :2], cl, out.reshape(-1, 3)[:, 2]).reshape(TH.shape)
        press = self.at(self.press, TH.ravel(), ZZ.ravel()).reshape(TH.shape)
        return {"P": out, "valid": valid, "winding": wid, "theta": TH, "z_rolled": ZZ, "press": press,
                "s": ss, "z": zs, "step": float(step), "residual": float(res.max()) if len(res) else 0.0}


class Scroll2(Roll):
    """The rolled sheet at full scale. Roll builds every random field from the seed in a fixed order; this class
    changes only lookups, textures, the crush axis and the box height."""

    def __init__(self, p):
        np = _np()
        self.p2 = p = params(p)
        Z, Y, X = p["shape"]
        base = {k: p[k] for k in BASE}
        fixed = float(p["alpha"]) >= 0
        if fixed:
            base["shape"] = [Z, X, X]               # the roll's size is set by the box width; y is cut below
        super().__init__(base)
        if fixed:
            self.alpha = float(p["alpha"])
            self.Y = Y
            self.center = np.array([(X - 1) / 2.0, (Y - 1) / 2.0])
            rmax = 0.5 * X - float(p["margin"]) - 2.5 * float(p["warp"])
            ca, sa = abs(math.cos(self.alpha)), abs(math.sin(self.alpha))
            s = float(p["squash"])
            need = 2 * (rmax * math.hypot(s * ca, sa) + float(p["margin"]) + 2.5 * float(p["warp"]))
            if Y + 1e-9 < need:
                raise SimError(f"the box is {Y} voxels in y; this crush needs {math.ceil(need)}")
        self.p = dict(self.p, shape=[Z, Y, X])
        self._tile = None
        self.cl = self.center_line()
        self.r_outer = float(np.nanmax(np.where(np.isfinite(self.R[:self.n_end]), self.R[:self.n_end], np.nan)))
        self.r_inner = float(np.nanmin(self.R[:self.n_end]))
        self._inkc = None
        self.ink_on = float(p["ink_um"]) > 0 or float(p["ink_depth_um"]) > 0     # the ink writer (off by default)

    def at(self, grid, theta, z):
        """Roll's lookup without its per-call float64 copy of the whole grid (about 40 million values per
        field at full scale: 62 percent of a block's time, and memory bandwidth for every worker)."""
        np = _np()
        g = grid if grid.dtype == np.float64 else self._f64(grid)
        return _bilerp(np, g, self._fi(theta), self._fz(z))

    def _lookup3(self, theta, z):
        """R, thick and delam at the same (theta, z), sharing one set of bilinear weights (_bilerp's
        clamping and arithmetic, so the values are the same)."""
        np = _np()
        fi, fj = self._fi(theta), self._fz(z)
        n0, n1 = self.R.shape
        fi = np.clip(fi, 0, n0 - 1.000001)
        fj = np.clip(fj, 0, n1 - 1.000001)
        i0 = fi.astype(np.int64)
        j0 = fj.astype(np.int64)
        a, b = fi - i0, fj - j0
        k = i0 * n1 + j0
        out = []
        for grid in (self.R, self.thick, self.delam):
            g = (grid if grid.dtype == np.float64 else self._f64(grid)).ravel()
            out.append((1 - a) * ((1 - b) * g[k] + b * g[k + 1]) + a * ((1 - b) * g[k + n1] + b * g[k + n1 + 1]))
        return out

    def _f64(self, grid):
        np = _np()
        cache = self.__dict__.setdefault("_f64_cache", {})
        key = id(grid)
        if key not in cache:
            cache[key] = (grid, np.ascontiguousarray(grid, np.float64))
        return cache[key][1]

    # ------------------------------------------------------------------ textures
    def textures(self):
        """Periodic fiber tiles (recto along the sheet, verso along z), from the seed's texture stream."""
        if self._tile is not None:
            return self._tile
        np = _np()
        nd = _ndi()
        rng = np.random.default_rng([int(self.p["seed"]), 7])
        H, W = int(self.p2["tex_z"]), int(self.p2["tex_s"])
        tr = nd.gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), (0.8, 12.0), mode="wrap")
        tv = nd.gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), (12.0, 0.8), mode="wrap")
        tr /= tr.std() + 1e-9
        tv /= tv.std() + 1e-9
        self._tile = {"zpad": 0, "recto": tr, "verso": tv}
        return self._tile

    def _tex_at(self, name, z, s):
        np = _np()
        a = self.textures()[name]
        i = np.mod(np.rint(z).astype(np.int64), a.shape[0])
        j = np.mod(np.rint(s).astype(np.int64), a.shape[1])
        return a[i, j]

    # ------------------------------------------------------------------ voxels
    def locate_turn(self, rolled):
        """rho, phi, z and the turn j just inside each rolled point (largest k with R_k <= rho, -1 for none)."""
        np = _np()
        d = rolled[:, :2] - self.center
        rho = np.hypot(d[:, 0], d[:, 1])
        phi = np.mod(np.arctan2(d[:, 1], d[:, 0]), 2 * math.pi)
        z = rolled[:, 2]
        N = len(rho)
        lo = np.full(N, -1, np.int64)
        hi = np.full(N, self.max_k + 1, np.int64)
        act = hi - lo > 1
        while act.any():
            mid = (lo + hi) // 2
            r = self.R_at(phi + 2 * math.pi * mid, z)
            le = r <= rho
            lo = np.where(act & le, mid, lo)
            hi = np.where(act & ~le, mid, hi)
            act = hi - lo > 1
        return rho, phi, z, lo

    def voxels(self, out, width=1.0, ink=True):
        """As Roll.voxels_all_turns (density, label as turn index, its theta), then the 3D ink truth (all false when
        ink is off), and the distance to the nearest winding center (voxels, inf outside the roll). WIDTH is the edge
        of the cube each point stands for (output voxels), for the ink's partial volume; INK false leaves ink out."""
        np = _np()
        p = self.p
        rolled = self.rolled(out)
        rho, phi, z, j = self.locate_turn(rolled)
        N = len(rho)
        inked = np.zeros(N, bool)
        ik = self._ink_ctx(phi, width) if (ink and self.ink_on) else None
        dens = np.zeros(N, np.float64)
        best = np.full(N, np.inf)
        near_any = np.full(N, np.inf)
        lab = np.full(N, -1, np.int64)
        for dk in (-1, 0, 1, 2):
            k = j + dk
            ok = (k >= 0) & (k <= self.max_k)
            kk = np.clip(k, 0, self.max_k)
            thk = phi + 2 * math.pi * kk
            inr = (thk >= 0) & (thk <= self.theta_end)
            ok &= inr
            if not ok.any():
                continue
            thz = np.where(ok, thk, 0)
            rk, t, dl = self._lookup3(thz, z)
            d = np.where(ok, rho - rk, np.inf)
            half = t / 4 + dl / 2
            sig = float(p["ply_sigma"]) * t / 4
            s = self.s_at(thz)
            tr = self._tex_at("recto", z, s)
            tv = self._tex_at("verso", z, s)
            hole = self.hole_at(thz, z)
            amp = np.where(hole, 0.2, 1.0)
            fib = float(p["fiber"])
            recto = np.exp(-0.5 * ((d + half) / sig) ** 2) * (1 + fib * tr)
            verso = np.exp(-0.5 * ((d - half) / sig) ** 2) * (1 + fib * tv)
            if ik is not None:                                  # the ink writer
                recto, hit = self._ink_apply(ik, ok, d, half, sig, s, z, hole, tr, recto, dens)
                inked |= hit
            dens += np.where(ok, amp * (recto + verso), 0)
            band = np.abs(d) <= half + HALFMAX * sig
            near = ok & band & (np.abs(d) < best)
            best = np.where(near, np.abs(d), best)
            lab = np.where(near, kk, lab)
            near_any = np.minimum(near_any, np.abs(d))
        theta = phi + 2 * math.pi * np.clip(lab, 0, self.max_k)
        return dens, lab, theta, inked, near_any

    def block_is_air(self, z0, z1, y0, y1, x0, x1, step=8):
        """True when no sheet can reach the box: every sampled rolled radius lies beyond the outermost winding (or
        inside the innermost) by more than the sampling step can hide."""
        np = _np()
        zs = np.unique(np.clip(np.r_[np.arange(z0, z1, step), z1 - 1], z0, z1 - 1))
        ys = np.unique(np.clip(np.r_[np.arange(y0, y1, step), y1 - 1], y0, y1 - 1))
        xs = np.unique(np.clip(np.r_[np.arange(x0, x1, step), x1 - 1], x0, x1 - 1))
        Zg, Yg, Xg = np.meshgrid(zs, ys, xs, indexing="ij")
        out = np.stack([Xg.ravel(), Yg.ravel(), Zg.ravel()], 1).astype(np.float64)
        rho = np.hypot(*(self.rolled(out)[:, :2] - self.center).T)
        slack = step * math.sqrt(3) / float(self.p["squash"]) + 2.5 * float(self.p["warp"]) + 2 * float(self.p["thick"]) + 4
        return bool((rho.min() > self.r_outer + slack) or (rho.max() < self.r_inner - slack))

    # ------------------------------------------------------------------ rendering
    def halo(self):
        p = self.p2
        sz = math.hypot(float(p["blur"]), float(p["psf_z"]))
        sxy = math.hypot(float(p["blur"]), float(p["psf_xy"]))
        e = float(p["edge_sigma"]) if float(p["edge"]) > 0 else 0.0
        h = int(math.ceil(4 * (max(sz, sxy) + e + float(p["noise_corr"])))) + 2
        ph = self.phase()
        if ph is not None:
            h += ph["halo"]
        if any(float(v) > 0 for v in p["nps"]):
            h = max(h, int(4 * NPS_SIGMAS[-1] + 0.5) + 2)
        return h

    def phase(self):
        if not hasattr(self, "_phase"):
            self._phase = phase_model(self.p2)
        return self._phase

    def prepare(self):
        """Build the fields every block reads (bias, rings, slabs, cupping) once, before workers fork."""
        self._bias_field()
        self.phase()
        if float(self.p2["cupping"]) > 0:
            self._cup_field()

    def _cup_field(self):
        """Beam hardening's cupping, on a coarse grid (CUP_Z x CUP_XY x CUP_XY voxels): for each grid point the
        mean, over CUP_ANGLES projection angles in the slice, of the sheet's line integral along the ray through it,
        divided by the largest such value in the volume (0 to 1). Longer paths through the roll lose more contrast."""
        np = _np()
        nd = _ndi()
        if getattr(self, "_cup", None) is not None:
            return self._cup
        Z, Y, X = self.Z, self.Y, self.X
        nz, ny, nx = max(2, -(-Z // CUP_Z)), max(2, -(-Y // CUP_XY)), max(2, -(-X // CUP_XY))
        zc = (np.arange(nz) + 0.5) * Z / nz - 0.5
        yc = (np.arange(ny) + 0.5) * Y / ny - 0.5
        xc = (np.arange(nx) + 0.5) * X / nx - 0.5
        occ = np.zeros((nz, ny, nx))
        q = CUP_XY / 4.0
        for oy in (-q, q):
            for ox in (-q, q):
                Zg, Yg, Xg = np.meshgrid(zc, yc + oy, xc + ox, indexing="ij")
                pts = np.stack([Xg.ravel(), Yg.ravel(), Zg.ravel()], 1)
                d = np.zeros(len(pts))
                for a in range(0, len(pts), POINTS_PER_PASS):
                    d[a:a + POINTS_PER_PASS] = self.voxels(pts[a:a + POINTS_PER_PASS], ink=False)[0]
                occ += np.clip(d, 0, 1.6).reshape(occ.shape) / 4.0
        D = int(math.ceil(math.hypot(ny, nx))) + 2
        py, px = (D - ny) // 2, (D - nx) // 2
        path = np.zeros_like(occ)
        for i in range(nz):
            sq = np.zeros((D, D))
            sq[py:py + ny, px:px + nx] = occ[i]
            acc = np.zeros((D, D))
            for a in np.arange(CUP_ANGLES) * 180.0 / CUP_ANGLES:
                r = nd.rotate(sq, a, reshape=False, order=1)
                back = np.broadcast_to(r.sum(0, keepdims=True), r.shape)
                acc += nd.rotate(back, -a, reshape=False, order=1)
            path[i] = acc[py:py + ny, px:px + nx] / CUP_ANGLES
        top = float(path.max())
        self._cup = (path / top) if top > 0 else path
        return self._cup

    def _coarse_at(self, field, Z0, Z1, Y0, Y1, X0, X1):
        """FIELD (a coarse grid over the whole box, cell centers) interpolated to the voxels of a block."""
        np = _np()
        gz = (np.arange(Z0, Z1) + 0.5) / self.Z * field.shape[0] - 0.5
        gy = (np.arange(Y0, Y1) + 0.5) / self.Y * field.shape[1] - 0.5
        gx = (np.arange(X0, X1) + 0.5) / self.X * field.shape[2] - 0.5
        G = np.meshgrid(gz, gy, gx, indexing="ij")
        return _ndi().map_coordinates(field, G, order=1, mode="nearest")

    def _slabs(self):
        """Per-slab gains and ring profiles: slab k holds z in [k slab_z, (k + 1) slab_z)."""
        np = _np()
        if getattr(self, "_slab", None) is None:
            p = self.p2
            sz = int(p["slab_z"])
            n = max(1, -(-self.Z // sz)) if sz > 0 else 1
            gain = np.ones(n)
            if float(p["slab_gain"]) > 0:
                gain = 1 + float(p["slab_gain"]) * np.random.default_rng([int(p["seed"]), 15]).standard_normal(n)
            self._bias_field()
            ay, ax = self._axis()
            nr = len(self._rings0)
            far = int(max(math.hypot(ay - y, ax - x) for y in (0, self.Y - 1) for x in (0, self.X - 1))) + 4
            nr = max(nr, far)
            rings = np.random.default_rng([int(self.p["seed"]), 12]).standard_normal(nr * n).reshape(n, nr)
            self._slab = (sz, gain.astype(np.float32), rings)
        return self._slab

    def _axis(self):
        ax = self.p2["axis_yx"]
        return (float(ax[0]), float(ax[1])) if ax else ((self.Y - 1) / 2, (self.X - 1) / 2)

    def _bias_field(self):
        """The slow brightness drift from the [seed, 11] stream, coarse grid."""
        np = _np()
        if getattr(self, "_bias", None) is None:
            Z, Y, X = self.Z, self.Y, self.X
            rng = np.random.default_rng([int(self.p["seed"]), 11])
            self._bias = _field(rng, (max(2, Z // 32), max(2, Y // 32), max(2, X // 32)), 1.0)
            rr = np.random.default_rng([int(self.p["seed"]), 12])
            self._rings = self._rings0 = rr.standard_normal(int(math.hypot(X, Y) / 2) + 4)
        return self._bias

    def density_block(self, z0, z1, y0, y1, x0, x1):
        """Density, winding labels (id + 1, 0 none), distance to the nearest winding and the 3D ink truth (bool) on a
        box, no scan model."""
        np = _np()
        shape = (z1 - z0, y1 - y0, x1 - x0)
        n = int(self.p2["supersample"])
        zz, yy, xx = np.meshgrid(np.arange(z0, z1, dtype=np.float64), np.arange(y0, y1, dtype=np.float64),
                                 np.arange(x0, x1, dtype=np.float64), indexing="ij")
        cen = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], 1)
        del zz, yy, xx
        N = len(cen)
        dens = np.zeros(N, np.float32)
        labels = np.zeros(N, np.uint16)
        near = np.zeros(N, np.float32)
        inkv = np.zeros(N, bool)
        offs = (np.arange(n) + 0.5) / n - 0.5
        for a in range(0, N, POINTS_PER_PASS):           # bounded memory: about 1 GB per pass at most
            c = cen[a:a + POINTS_PER_PASS]
            d0, lab, th, ik, nr = self.voxels(c)
            inkv[a:a + len(c)] = ik
            wid = self.winding_id(th, c[:, :2], self.cl, c[:, 2])
            labels[a:a + len(c)] = np.where(lab >= 0, wid + 1, 0)
            near[a:a + len(c)] = nr
            if n == 1:
                dens[a:a + len(c)] = d0
            else:
                acc = np.zeros(len(c))
                for oz in offs:
                    for oy in offs:
                        for ox in offs:
                            acc += self.voxels(c + np.array([ox, oy, oz]), width=1.0 / n)[0]
                dens[a:a + len(c)] = acc / n ** 3
        return dens.reshape(shape), labels.reshape(shape), near.reshape(shape), inkv.reshape(shape)

    def scan_block(self, z0, z1, y0, y1, x0, x1, air=None, with_ink=False):
        """The CT (uint8) and labels of the box, rendered with a halo so no filter sees the block edge. WITH_INK adds
        a fourth value, the 3D ink truth of the box (uint8, 1 inside the ink)."""
        np = _np()
        nd = _ndi()
        p = self.p2
        h = self.halo()
        Z0, Z1, Y0, Y1, X0, X1 = z0 - h, z1 + h, y0 - h, y1 + h, x0 - h, x1 + h
        if air is None:
            air = self.block_is_air(Z0, Z1, Y0, Y1, X0, X1)
        shape = (Z1 - Z0, Y1 - Y0, X1 - X0)
        if air:
            dens = np.zeros(shape, np.float32)
            labels = np.zeros(shape, np.uint16)
            near = np.full(shape, np.inf, np.float32)
            inkv = np.zeros(shape, bool)
        else:
            dens, labels, near, inkv = self.density_block(Z0, Z1, Y0, Y1, X0, X1)
        v = float(p["air"]) + (float(p["bright"]) - float(p["air"])) * np.clip(dens, 0, 1.6)
        if float(p["cupping"]) > 0 and not air:
            c = self._coarse_at(self._cup_field(), Z0, Z1, Y0, Y1, X0, X1)
            v = float(p["air"]) + (v - float(p["air"])) * (1 - float(p["cupping"]) * c).astype(np.float32)
        ph = self.phase()
        if ph is not None and not air:                  # an air block is constant, which the phase model keeps
            v = apply_phase(v, ph)
        sz = math.hypot(float(p["blur"]), float(p["psf_z"]))
        sxy = math.hypot(float(p["blur"]), float(p["psf_xy"]))
        if sz > 0 or sxy > 0:
            v = nd.gaussian_filter(v, (sz, sxy, sxy), mode="nearest")
        if float(p["edge"]) > 0:
            v = v + float(p["edge"]) * (v - nd.gaussian_filter(v, float(p["edge_sigma"]), mode="nearest"))
        b = self._bias_field()
        if float(p["bias"]) > 0:
            v = v * (1 + float(p["bias"]) * self._coarse_at(b, Z0, Z1, Y0, Y1, X0, X1)).astype(np.float32)
        slab_z, gain, rings = self._slabs()
        sidx = np.clip(np.arange(Z0, Z1) // slab_z, 0, len(gain) - 1) if slab_z > 0 else np.zeros(Z1 - Z0, np.int64)
        if float(p["slab_gain"]) > 0:
            v = v * gain[sidx][:, None, None]
        if float(p["rings"]) > 0:
            ay, ax = self._axis()
            yy, xx = np.mgrid[Y0:Y1, X0:X1]
            r = np.clip(np.rint(np.hypot(yy - ay, xx - ax)).astype(np.int64), 0, rings.shape[1] - 1)
            for k in np.unique(sidx):
                m = sidx == k
                v[m] = v[m] + (rings[k][r] * float(p["rings"]))[None].astype(np.float32)
        if float(p["noise"]) > 0:
            w = hashed_normal(p["seed"], Z0, Z1, Y0, Y1, X0, X1)
            c = float(p["noise_corr"])
            if c > 0:
                w = nd.gaussian_filter(w, c, mode="nearest") / _smooth_noise_gain(max(c, 1e-6))
            v = v + float(p["noise"]) * w
        for j, sd in enumerate(p["nps"]):
            if sd <= 0:
                continue
            w = hashed_normal(p["seed"], Z0, Z1, Y0, Y1, X0, X1, salt=HASH_SALT["nps"] + j)
            s0, s1 = NPS_SIGMAS[j], (NPS_SIGMAS[j + 1] if j + 1 < len(NPS_SIGMAS) else None)
            band = nd.gaussian_filter(w, s0, mode="nearest") if s0 > 0 else w
            if s1 is not None:
                band = band - nd.gaussian_filter(w, s1, mode="nearest")
            v = v + np.float32(sd / nps_band_gain(j)) * band
        ct = np.clip(np.rint(v), 0, 255).astype(np.uint8)
        core = (slice(h, h + z1 - z0), slice(h, h + y1 - y0), slice(h, h + x1 - x0))
        if with_ink:
            return ct[core], labels[core], bool(air), inkv[core].astype(np.uint8)
        return ct[core], labels[core], bool(air)

    # ------------------------------------------------------------------ ink writer (off by default)
    def _ink(self):
        """The ink model, built once per scroll from the parameters and the seed: the glyph atlas (padded by one
        zero pixel), the layout numbers, the grain tile, and the thicknesses in voxels."""
        if self._inkc is not None:
            return self._inkc
        np = _np()
        p = self.p2
        atlas, src = ink_glyphs(p["ink_glyphs"], p["ink_advance"], p["ink_stroke"])
        um = float(p["voxel_um"])
        L = float(p["ink_letter"])
        cw = L * float(p["ink_advance"])
        room = self.Z - 2 * float(p["ink_margin"])
        c = {"atlas": np.pad(atlas, ((0, 0), (1, 1), (1, 1))), "source": src,
             "atlas_sha256": hashlib.sha256(atlas.tobytes()).hexdigest(),
             "th": float(p["ink_um"]) / um, "dep": float(p["ink_depth_um"]) / um,
             "rho": float(p["ink_rho"]), "tex": float(p["ink_tex"]), "paint": int(p["ink_off"]) == 0,
             "L": L, "cw": cw, "nslot": int(float(p["ink_col"]) // cw),
             "nlines": int((room - L) // float(p["ink_line"])) + 1 if room >= L else 0, "grain": None}
        if c["tex"] > 0:
            rng = np.random.default_rng([int(p["seed"]), 17])
            g = _ndi().gaussian_filter(rng.standard_normal((256, 256)).astype(np.float32), 0.8, mode="wrap")
            c["grain"] = g / (g.std() + 1e-9)
        self._inkc = c
        return c

    def ink_cover(self, s, z):
        """Ink coverage, 0 to 1, of the page at sheet coordinates S (arc length, voxels) and rolled Z: columns of
        lines of letters, each letter a glyph chosen by a hash of the seed, column, line and place (block independent,
        no stored page), sampled bilinearly from the anti-aliased atlas."""
        np = _np()
        p = self.p2
        c = self._ink()
        A = c["atlas"]
        s = np.asarray(s, np.float64)
        z = np.asarray(z, np.float64)
        L, cw = c["L"], c["cw"]
        gap, period = float(p["ink_gap"]), float(p["ink_col"]) + float(p["ink_gap"])
        u0 = s - gap
        col = np.floor(u0 / period)
        u = u0 - col * period
        zz = z - float(p["ink_margin"])
        line = np.floor(zz / float(p["ink_line"]))
        v = zz - line * float(p["ink_line"])
        place = np.floor(u / cw)
        x = u - place * cw
        ok = ((u0 >= 0) & (u < float(p["ink_col"])) & (place < c["nslot"]) & (line >= 0) & (line < c["nlines"])
              & (v < L) & (s >= 0) & (s <= self.s_end))
        ci = np.where(ok, col, 0).astype(np.int64)
        li = np.where(ok, line, 0).astype(np.int64)
        pi = np.where(ok, place, 0).astype(np.int64)
        h = _hash3(np, p["seed"], INK_SALT, ci, li, pi)
        hl = _hash3(np, p["seed"], INK_SALT + 1, ci, li, np.zeros_like(pi))
        cut = (hl % np.uint64(c["nslot"] // 3 + 1)).astype(np.int64)            # a ragged right edge
        blank = (h >> np.uint64(11)).astype(np.float64) / 9007199254740992.0 < float(p["ink_space"])
        ok &= (pi < c["nslot"] - cut) & ~blank
        g = (h % np.uint64(len(INK_GREEK))).astype(np.int64)
        H, W = A.shape[1] - 2, A.shape[2] - 2
        fy = np.clip(np.where(ok, v, 0) / L * H + 0.5, 0, H + 1 - 1e-6)
        fx = np.clip(np.where(ok, x, 0) / cw * W + 0.5, 0, W + 1 - 1e-6)
        i0, j0 = fy.astype(np.int64), fx.astype(np.int64)
        a, b = fy - i0, fx - j0
        n1 = A.shape[2]
        k = (g * A.shape[1] + i0) * n1 + j0
        f = A.ravel()
        val = (1 - a) * ((1 - b) * f[k] + b * f[k + 1]) + a * ((1 - b) * f[k + n1] + b * f[k + n1 + 1])
        return np.where(ok, val, 0.0)

    def _ink_ctx(self, phi, width):
        """Per point: the widths of the voxel's extent along the sheet normal (rolled frame), from the crush's
        stretch of the output voxel's x and y edges; the smooth bend's small gradient is left out."""
        np = _np()
        s = float(self.p["squash"])
        ca, sa = math.cos(self.alpha), math.sin(self.alpha)
        cp, sp = np.cos(phi), np.sin(phi)
        u = cp * ca + sp * sa
        v = (-cp * sa + sp * ca) / s
        return {"a": np.abs(u * ca - v * sa) * float(width), "b": np.abs(u * sa + v * ca) * float(width)}

    def _ink_apply(self, ik, ok, d, half, sig, s, z, hole, tr, recto, dens):
        """Paint one winding's ink into RECTO (returned) and DENS (in place), and return its truth. The recto face is
        at d = -(half + HALFMAX sig), the ply's half maximum on its inner side; the deposit fills [face - th, face]
        with density 1 + rho, and within [face, face + dep] the ply's density is scaled by 1 + rho and its fiber
        texture is blended toward the grain by tex. Each share is the voxel's exact partial volume of the slab."""
        np = _np()
        c = self._ink()
        face = -(half + HALFMAX * sig)
        dd = np.where(ok, d, 1e9)
        lo, hi = face - c["th"], face + c["dep"]
        ext = 0.5 * (ik["a"] + ik["b"])
        touch = np.flatnonzero(ok & ~hole & (dd - ext < hi) & (dd + ext > lo))     # voxels the slab reaches
        cov = np.zeros(len(dd))
        if len(touch):
            cov[touch] = self.ink_cover(np.broadcast_to(s, dd.shape)[touch], np.broadcast_to(z, dd.shape)[touch])
        hit = cov >= 0.5
        if not c["paint"] or not len(touch):
            return recto, hit
        t = touch
        a, b, dt, cv = ik["a"][t], ik["b"][t], dd[t], cov[t]
        if c["th"] > 0:
            dens[t] += cv * (1 + c["rho"]) * ink_share(np, dt, lo[t], face[t], a, b)
        if c["dep"] > 0 and (c["rho"] != 0 or c["tex"] > 0):
            f = cv * ink_share(np, dt, face[t], hi[t], a, b)
            rt = recto[t]
            if c["tex"] > 0:
                gt = c["grain"]
                zt, st = np.broadcast_to(z, dd.shape)[t], np.broadcast_to(s, dd.shape)[t]
                gr = gt[np.mod(np.rint(zt).astype(np.int64), gt.shape[0]),
                        np.mod(np.rint(st).astype(np.int64), gt.shape[1])]
                m = c["tex"] * f
                tx = (1 - m) * tr[t] + m * gr
                rt = np.exp(-0.5 * ((d[t] + half[t]) / sig[t]) ** 2) * (1 + float(self.p["fiber"]) * tx)
            recto = recto.copy()
            recto[t] = rt * (1 + c["rho"] * f)
        return recto, hit

    def ink_surface(self, surf):
        """Ink truth on a surface grid (as surface() returns it): uint8, 1 where the vertex is valid, not in a hole
        and the page there is inked (coverage 0.5 or more)."""
        np = _np()
        TH, ZZ = surf["theta"], surf["z_rolled"]
        cov = self.ink_cover(self.s_at(TH.ravel()), ZZ.ravel()).reshape(TH.shape)
        hole = self.hole_at(TH.ravel(), ZZ.ravel()).reshape(TH.shape)
        return (surf["valid"] & ~hole & (cov >= 0.5)).astype(np.uint8)

    def ink_report(self):
        """The ink record for truth.json: on or off, the twin flag, thicknesses in voxels, the layout, the glyph
        source and its atlas hash, and the pattern share (share of the sheet's area inked, from random points)."""
        if not self.ink_on:
            return {"on": False}
        np = _np()
        p = self.p2
        c = self._ink()
        rng = np.random.default_rng([int(p["seed"]), 16])
        s = rng.uniform(0, self.s_end, INK_SHARE_SAMPLES)
        z = rng.uniform(0, self.Z - 1, INK_SHARE_SAMPLES)
        cov = self.ink_cover(s, z)
        return {"on": True, "painted": c["paint"], "twin": None if c["paint"] else "noink",
                "params": {k: p[k] for k in p if k.startswith("ink_")},
                "thickness_vox": round(c["th"], 4), "depth_vox": round(c["dep"], 4),
                "glyphs": c["source"], "atlas_sha256": c["atlas_sha256"],
                "lines_per_column": c["nlines"], "places_per_line": c["nslot"],
                "pattern_share": round(float((cov >= 0.5).mean()), 5),
                "pattern_cover_mean": round(float(cov.mean()), 5),
                "source": "Parker et al., PLoS ONE 14(5): e0215775 (2019), "
                          "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0215775: ink 3 to 5 um "
                          "thick, absorbed 4 to 12 um deeper, x-ray attenuation almost that of carbonized papyrus",
                "note": "Model output on synthetic data: a simple layer model, not calibrated against real ink, and "
                        "no real ink reader has been shown to see it."}


# ---------------------------------------------------------------------------------------------------- make
_SC = None          # the scroll a forked worker renders (copy on write)


def _blocks(shape, block):
    Z, Y, X = shape
    return [(z, min(z + block, Z), y, min(y + block, Y), x, min(x + block, X))
            for z in range(0, Z, block) for y in range(0, Y, block) for x in range(0, X, block)]


WRITE_TRIES = 3     # writes of one block's chunks before make gives up on it


def _chunk_keys(b, chunks):
    """The zarr format 2 chunk keys ('z.y.x') a box covers; CHUNKS per axis."""
    r = [range(b[2 * a] // chunks[a], (b[2 * a + 1] - 1) // chunks[a] + 1) for a in range(3)]
    return [f"{i}.{j}.{k}" for i in r[0] for j in r[1] for k in r[2]]


def _landed(arr_dir, keys):
    """The keys whose chunk file is not on disk under ARR_DIR (a write through a bucket mount can leave only a
    '.partial' temp file, which zarr then reads as fill value)."""
    return [k for k in keys if not (Path(arr_dir) / k).is_file()]


def _write_checked(arr_dir, arr, box, data):
    """Write DATA into ARR at the chunk-aligned BOX and check that the file of every chunk holding a value other than
    the fill value landed (zarr 3 does not write an all-fill chunk); retry up to WRITE_TRIES times."""
    c = arr.chunks
    fill = arr.fill_value if arr.fill_value is not None else 0
    keys = []
    for k in _chunk_keys(box, c):
        i = [int(x) for x in k.split(".")]
        sl = tuple(slice(i[a] * c[a] - box[2 * a], (i[a] + 1) * c[a] - box[2 * a]) for a in range(3))
        if (data[sl] != fill).any():
            keys.append(k)
    for _ in range(WRITE_TRIES):
        arr[box[0]:box[1], box[2]:box[3], box[4]:box[5]] = data
        missing = _landed(arr_dir, keys)
        if not missing:
            return
    raise SimError(f"{arr_dir}: chunk(s) {', '.join(missing[:4])} did not land after {WRITE_TRIES} writes")


def _work_level0(args):
    out, b = args
    import zarr
    t = time.time()
    if _SC.ink_on:
        ct, labels, air, ink = _SC.scan_block(*b, with_ink=True)
    else:
        ct, labels, air = _SC.scan_block(*b)
    g = zarr.open_group(str(out / "ct.zarr"), mode="r+")
    _write_checked(out / "ct.zarr" / "0", g["0"], b, ct)
    lg = zarr.open_group(str(out / "truth" / "labels.zarr"), mode="r+")
    _write_checked(out / "truth" / "labels.zarr" / "0", lg["0"], b, labels)
    if _SC.ink_on:                                       # the ink writer's 3D truth
        ig = zarr.open_group(str(out / "truth" / "ink.zarr"), mode="r+")
        _write_checked(out / "truth" / "ink.zarr" / "0", ig["0"], b, ink)
    return air, time.time() - t


def _work_down(args):
    out, lev, b = args
    import zarr
    np = _np()
    g = zarr.open_group(str(out / "ct.zarr"), mode="r+")
    src = g[str(lev - 1)]
    z0, z1, y0, y1, x0, x1 = b
    a = src[2 * z0:min(2 * z1, src.shape[0]), 2 * y0:min(2 * y1, src.shape[1]), 2 * x0:min(2 * x1, src.shape[2])]
    a = a.astype(np.float32)
    pad = [(0, 2 * (e - s) - n) for (s, e), n in zip(((z0, z1), (y0, y1), (x0, x1)), a.shape)]
    if any(p[1] for p in pad):
        a = np.pad(a, pad, mode="edge")
    d = a.reshape(z1 - z0, 2, y1 - y0, 2, x1 - x0, 2).mean((1, 3, 5))
    _write_checked(out / "ct.zarr" / str(lev), g[str(lev)], b, np.clip(np.rint(d), 0, 255).astype(np.uint8))
    return 0


def verify(out):
    """Every CT chunk of every level on disk (the CT is never all fill: air renders gray and noisy), and no '.partial'
    temp file anywhere. Returns a dict; 'ok' false names what is missing."""
    out = Path(out)
    import zarr
    g = zarr.open_group(str(out / "ct.zarr"), mode="r")
    report = {"levels": {}, "partial": [], "ok": True}
    for name in sorted(g.array_keys(), key=int):
        a = g[name]
        b = (0, a.shape[0], 0, a.shape[1], 0, a.shape[2])
        miss = _landed(out / "ct.zarr" / name, _chunk_keys(b, a.chunks))
        report["levels"][name] = {"chunks": len(_chunk_keys(b, a.chunks)), "missing": len(miss),
                                  "first_missing": miss[:4]}
        report["ok"] &= not miss
    report["partial"] = sorted(str(p.relative_to(out)) for p in out.rglob("*.partial"))[:20]
    report["ok"] &= not report["partial"]
    return report


def publish(src, dst, levels=None, labels=True):
    """Copy a finished local scrollsim2 folder SRC to DST (for example a bucket mount) with plain file writes, never
    zarr's write-then-rename, remove any '.partial' file left under the copied arrays in DST, then verify DST.
    LEVELS limits the CT levels copied (for a pyramid repair: 1 to 5); LABELS false skips the label volume."""
    import shutil
    src, dst = Path(src), Path(dst)
    if not (src / "ct.zarr").is_dir():
        raise SimError(f"{src} is not a scrollsim2 folder (no ct.zarr)")
    names = sorted((p.name for p in (src / "ct.zarr").iterdir() if p.is_dir()), key=int)
    if levels is not None:
        names = [n for n in names if int(n) in set(int(x) for x in levels)]
    dirs = [Path("ct.zarr") / n for n in names] + ([Path("truth") / "labels.zarr" / "0"] if labels else [])
    files = [Path("ct.zarr") / ".zgroup", Path("ct.zarr") / ".zattrs", Path("truth.json")]
    if labels:
        files += [Path("truth") / "labels.zarr" / ".zgroup", Path("truth") / "labels.zarr" / ".zattrs"]
    if labels and (src / "truth" / "ink.zarr" / "0").is_dir():      # the ink writer's truth
        dirs.append(Path("truth") / "ink.zarr" / "0")
        files += [Path("truth") / "ink.zarr" / ".zgroup", Path("truth") / "ink.zarr" / ".zattrs"]
    copied = 0
    for d in dirs:
        (dst / d).mkdir(parents=True, exist_ok=True)
        for f in (src / d).iterdir():
            if f.is_file() and not f.name.endswith(".partial"):
                shutil.copyfile(f, dst / d / f.name)
                copied += 1
        for f in (dst / d).glob("*.partial"):
            f.unlink()
    for f in files:
        if (src / f).is_file():
            (dst / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / f, dst / f)
            copied += 1
    rep = verify(dst)
    rep["copied_files"] = copied
    return rep


def pyramid(out, workers=1):
    """Rebuild CT levels 1 and up from level 0 of a complete make (truth.json complete), then verify."""
    out = Path(out)
    doc = json.loads((out / "truth.json").read_text())
    if not doc.get("complete", True):
        raise SimError(f"{out}: level 0 is not complete; resume make first")
    import zarr
    g = zarr.open_group(str(out / "ct.zarr"), mode="r")
    levels = sorted(int(k) for k in g.array_keys())
    chunk = g["0"].chunks[0]
    shapes = {lev: g[str(lev)].shape for lev in levels}
    pool = _pool(int(workers))
    try:
        t = time.time()
        for lev in levels[1:]:
            _map(pool, _work_down, [(out, lev, b) for b in _blocks(shapes[lev], chunk)])
    finally:
        if pool:
            pool.close()
            pool.join()
    rep = verify(out)
    rep["seconds"] = round(time.time() - t, 1)
    return rep


def _pool(workers):
    import multiprocessing as mp
    return mp.get_context("fork").Pool(workers) if workers > 1 else None


def _map(pool, fn, items):
    return pool.map(fn, items, chunksize=1) if pool else [fn(i) for i in items]


def write_surface(folder, surf, name):
    """One tifxyz surface (x.tif, y.tif, z.tif float32 with -1 at holes, meta.json) and winding.npy, the winding
    number of every vertex (NaN at holes)."""
    np = _np()
    from . import vc3d_io
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    valid = surf["valid"]
    for i, c in enumerate("xyz"):
        a = np.where(valid, surf["P"][..., i], -1.0).astype(np.float32)
        vc3d_io.write_tiff(folder / f"{c}.tif", vc3d_io.raster_from_numpy(a))
    meta = {"format": "tifxyz", "type": "seg", "uuid": name, "scale": [1.0 / surf["step"], 1.0 / surf["step"]],
            "source": "kit.scrollsim2"}
    if valid.any():
        q = surf["P"][valid]
        meta["bbox"] = [q.min(0).tolist(), q.max(0).tolist()]
    (folder / "meta.json").write_text(json.dumps(meta, indent=2))
    np.save(folder / "winding.npy", np.where(valid, surf["winding"], np.nan).astype(np.float64))
    return folder


VC3D_PROJECT = "scrollsim2.volpkg.json"
VC3D_UUID_NS = "6d1f0c62-3b0e-5a8e-9a3e-5c7f2b1d9e41"     # uuid5 namespace for this tool's surface ids


def _vc3d_volume(src, dst, uid, name, voxel_um, copy):
    """One VC3D volume folder: SRC's level arrays (linked, or copied with COPY), an OME-Zarr 0.4 multiscales group
    and the meta.json VC3D's Volume reads (type vol, uuid, width, height, slices; voxelsize)."""
    import shutil
    import zarr
    g = zarr.open_group(str(src), mode="r")
    levels = sorted(g.array_keys(), key=int)
    z, y, x = g[levels[0]].shape
    dst.mkdir(parents=True)
    for lev in levels:
        if copy:
            shutil.copytree(src / lev, dst / lev)
        else:
            os.symlink(os.path.relpath((src / lev).resolve(), dst.resolve()), dst / lev, target_is_directory=True)
    (dst / ".zgroup").write_text(json.dumps({"zarr_format": 2}) + "\n")
    ds = [{"path": lev, "coordinateTransformations": [{"type": "scale", "scale": [2.0 ** int(lev)] * 3}]}
          for lev in levels]
    # no unit on the axes: a micrometer unit with scale 1 would declare 1 um voxels, and VC3D lets a size from the
    # store's metadata override meta.json's voxelsize
    (dst / ".zattrs").write_text(json.dumps({"multiscales": [{"version": "0.4", "name": name, "axes": [
        {"name": n, "type": "space"} for n in "zyx"], "datasets": ds}]}, indent=1) + "\n")
    meta = {"uuid": uid, "name": name, "type": "vol", "format": "zarr", "width": int(x), "height": int(y),
            "slices": int(z), "voxelsize": float(voxel_um), "min": 0.0,
            "max": 255.0 if g[levels[0]].dtype.itemsize == 1 else 65535.0}
    (dst / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    return {"location": str(dst), "uuid": uid, "levels": len(levels), "shape": [int(z), int(y), int(x)]}


def export_vc3d(sim, out, voxel_um=None, copy=False):
    """A folder VC3D opens for a finished make SIM: volumes/<id>-ct and volumes/<id>-labels (the CT and the winding
    labels as two zarr volumes with meta.json), paths/spiral-center and paths/spiral-recto (the truth surfaces as
    tifxyz, meta.json uuid a canonical uuid5) when SIM was made with --surfaces, and scrollsim2.volpkg.json, the
    project file VC3D builds of late October 2026 open, checked by kit.villafmt before it is written. Level arrays
    are linked, or copied with COPY. VOXEL_UM (default: the make's voxel_um) is the voxel size VC3D shows in
    physical units; the volume is synthetic and has no measured size of its own."""
    import shutil
    import uuid
    from . import villafmt
    sim, out = Path(sim), Path(out)
    doc = json.loads((sim / "truth.json").read_text())
    if not doc.get("complete"):
        raise SimError(f"{sim}: the make is not complete; resume it first")
    if out.exists() and any(out.iterdir()):
        raise SimError(f"{out} exists and is not empty")
    if voxel_um is None:
        voxel_um = float(doc["params"].get("voxel_um", 8.0))
    if not float(voxel_um) > 0:
        raise SimError("--voxel-um is above 0")
    short = doc["code_sha256"][:8] + "-" + hashlib.sha256(json.dumps(doc["params"], sort_keys=True).encode()
                                                          ).hexdigest()[:8]
    out.mkdir(parents=True, exist_ok=True)
    vols = [_vc3d_volume(sim / "ct.zarr", out / "volumes" / f"scrollsim2-{short}-ct", f"scrollsim2-{short}-ct",
                         "scrollsim2 CT (synthetic)", voxel_um, copy),
            _vc3d_volume(sim / "truth" / "labels.zarr", out / "volumes" / f"scrollsim2-{short}-labels",
                         f"scrollsim2-{short}-labels", "scrollsim2 winding labels (id + 1)", voxel_um, copy)]
    segs = []
    for name in ("spiral-center", "spiral-recto"):
        src = sim / "truth" / "surfaces" / name
        if not src.is_dir():
            continue
        dst = out / "paths" / name
        shutil.copytree(src, dst)
        meta = json.loads((dst / "meta.json").read_text())
        meta["uuid"] = str(uuid.uuid5(uuid.UUID(VC3D_UUID_NS), f"{short}:{name}"))
        meta["name"] = name
        (dst / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        segs.append({"location": str(dst), "uuid": meta["uuid"]})
    proj = out / VC3D_PROJECT
    pdoc = villafmt.build_project(proj, [v["location"] for v in vols], [out / "paths"] if segs else [],
                                  name=f"scrollsim2-{short}")
    rep = villafmt.write_project(proj, pdoc)
    if not rep["ok"]:
        raise SimError(f"{proj}: the project check failed: {json.dumps(rep['errors'])[:400]}")
    return {"tool": "kit.scrollsim2 vc3d", "project": str(proj), "volumes": vols, "surfaces": segs,
            "voxel_um": float(voxel_um), "linked": not copy, "project_check": {"ok": rep["ok"],
            "warnings": [w["message"] for w in rep["warnings"]]}}


def code_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


DEADLINE_ENV = "KIT_JOB_DEADLINE"
SPARE_ENV = "KIT_JOB_SPARE_S"
SPARE_S = 180.0


def _float(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _deadline(environ=None):
    """The job's deadline and the spare kept for the last writes: DEADLINE_ENV is the epoch second the job's
    timeout ends (set it in a batch job), SPARE_ENV the seconds kept for the last writes (default SPARE_S)."""
    env = os.environ if environ is None else environ
    d = _float(env.get(DEADLINE_ENV))
    r = _float(env.get(SPARE_ENV))
    return d, (SPARE_S if r is None else r)


def make(out, over=None, preset=None, workers=1, block=128, levels=5, chunk=128, surfaces=False, progress=print,
         resume=False, max_blocks=None, environ=None, order="zyx"):
    """Render one scroll into OUT: ct.zarr (OME-zarr, levels 0 to LEVELS), truth/labels.zarr, truth.json, and with
    SURFACES the center and recto tifxyz of the whole sheet.

    Saves as it goes: each finished block is on disk before its index is added to truth/done.txt. RESUME reuses an
    OUT made with the same parameters and renders only the blocks not in done.txt. A job deadline (KIT_JOB_DEADLINE)
    stops new blocks once less than the spare is left; MAX_BLOCKS stops after that many new blocks (a timing
    probe). Either stop writes truth.json with "complete": false and skips the pyramid and surfaces. ORDER zyx renders
    blocks in index order; middle renders those nearest the volume's center first (sheet blocks, for a probe)."""
    global _SC
    import zarr  # noqa: F401  (fail before any work when zarr is missing)
    progress = progress or (lambda m: None)
    out = Path(out)
    fresh = not (out.exists() and any(out.iterdir()))
    if not fresh and not resume:
        raise SimError(f"{out} exists and is not empty")
    if block % chunk or block <= 0:
        raise SimError("--block must be a positive multiple of --chunk, so parallel writes never share a chunk")
    if not 0 <= int(levels) <= 8:
        raise SimError("--levels lies in 0 to 8")
    if order not in ("zyx", "middle"):
        raise SimError("--order is zyx or middle")
    deadline, spare = _deadline(environ)
    t0 = time.time()
    p = params(over, preset)
    key = {"params": p, "block": int(block), "chunk": int(chunk), "levels": int(levels), "code_sha256": code_sha256()}
    if not fresh:
        try:
            old = json.loads((out / "truth" / "make-key.json").read_text())
        except (OSError, ValueError):
            raise SimError(f"{out} is not a scrollsim2 folder to resume (no truth/make-key.json)")
        if old != json.loads(json.dumps(key, sort_keys=True)):
            raise SimError(f"{out} was made with other parameters, block, chunk, levels or code; resume needs the same")
    sc = Scroll2(dict(p))
    sc.prepare()
    t_init = time.time() - t0
    _SC = sc
    pool = _pool(int(workers))        # fork before any zarr call starts its I/O thread in this process
    try:
        return _make_with(pool, sc, out, fresh, p, key, block, chunk, levels, workers, deadline, spare,
                          max_blocks, progress, t0, t_init, preset, surfaces, order)
    finally:
        if pool:
            pool.close()
            pool.join()
        _SC = None


def _make_with(pool, sc, out, fresh, p, key, block, chunk, levels, workers, deadline, spare, max_blocks, progress,
               t0, t_init, preset, surfaces, order):
    import zarr
    Z, Y, X = sc.Z, sc.Y, sc.X
    shapes = [(Z, Y, X)]
    for _ in range(int(levels)):
        shapes.append(tuple((s + 1) // 2 for s in shapes[-1]))
    blocks = _blocks(shapes[0], block)
    donef = out / "truth" / "done.txt"
    done = set()
    if not fresh:
        done = {int(x) for x in donef.read_text().split()} if donef.exists() else set()
        return _map_resume(pool, sc, out, shapes, blocks, done, workers, deadline, spare, max_blocks, progress,
                           t0, t_init, key, preset, surfaces, order)
    (out / "truth").mkdir(parents=True, exist_ok=True)
    (out / "truth" / "make-key.json").write_text(json.dumps(key, sort_keys=True) + "\n")
    g = zarr.open_group(str(out / "ct.zarr"), mode="w", zarr_format=2)
    datasets = []
    for lev, shp in enumerate(shapes):
        g.create_array(str(lev), shape=shp, chunks=tuple(min(chunk, s) for s in shp), dtype="uint8", fill_value=0)
        datasets.append({"path": str(lev), "coordinateTransformations": [
            {"type": "scale", "scale": [float(p["voxel_um"]) * 2.0 ** lev] * 3}]})
    g.attrs["multiscales"] = [{"version": "0.4", "name": "scrollsim2", "axes": [
        {"name": n, "type": "space", "unit": "micrometer"} for n in "zyx"], "datasets": datasets}]
    lg = zarr.open_group(str(out / "truth" / "labels.zarr"), mode="w", zarr_format=2)
    lg.create_array("0", shape=shapes[0], chunks=tuple(min(chunk, s) for s in shapes[0]), dtype="uint16", fill_value=0)
    if sc.ink_on:                                        # the ink writer's 3D truth: 1 inside the ink
        ig = zarr.open_group(str(out / "truth" / "ink.zarr"), mode="w", zarr_format=2)
        ig.create_array("0", shape=shapes[0], chunks=tuple(min(chunk, s) for s in shapes[0]), dtype="uint8",
                        fill_value=0)
    return _map_resume(pool, sc, out, shapes, blocks, done, workers, deadline, spare, max_blocks, progress, t0,
                       t_init, key, preset, surfaces, order)


def _map_resume(pool, sc, out, shapes, blocks, done, workers, deadline, spare, max_blocks, progress, t0, t_init,
                key, preset, surfaces, order="zyx"):
    block, chunk, levels = key["block"], key["chunk"], key["levels"]
    donef = out / "truth" / "done.txt"
    todo = [i for i in range(len(blocks)) if i not in done]
    if order == "middle":
        mid = [s / 2 for s in shapes[0]]
        todo.sort(key=lambda i: sum(((blocks[i][2 * a] + blocks[i][2 * a + 1]) / 2 - mid[a]) ** 2 for a in range(3)))
    stop = None
    res = []
    t_down = 0.0
    complete = False
    t1 = time.time()
    step = max(1, 2 * int(workers))
    report = max(1, len(blocks) // 50)
    last = -report
    new = 0
    for i in range(0, len(todo), step):
        if deadline is not None and deadline - time.time() < spare:
            stop = "deadline"
            break
        if max_blocks is not None and new >= int(max_blocks):
            stop = "max_blocks"
            break
        part = todo[i:i + step]
        if max_blocks is not None:
            part = part[:int(max_blocks) - new]
        res += _map(pool, _work_level0, [(out, blocks[j]) for j in part])
        new += len(part)
        with open(donef, "a") as f:                  # after the blocks are written: done.txt never runs ahead
            f.write("".join(f"{j}\n" for j in part))
        done.update(part)
        if len(done) - last >= report or len(done) == len(blocks):
            last = len(done)
            progress(f"PROGRESS {len(done)}/{len(blocks)} blocks {time.time() - t1:.0f}s")
    t_render = time.time() - t1
    complete = len(done) == len(blocks)
    check = None
    if complete:
        t2 = time.time()
        for lev in range(1, len(shapes)):
            _map(pool, _work_down, [(out, lev, b) for b in _blocks(shapes[lev], chunk)])
        t_down = time.time() - t2
        check = verify(out)
        if not check["ok"]:
            raise SimError(f"{out}: chunks missing after the pyramid: {json.dumps(check)[:400]}")
    workers = int(workers)
    doc_s = {}
    if surfaces and complete:
        t3 = time.time()
        sd = out / "truth" / "surfaces"
        sd.mkdir(parents=True, exist_ok=True)
        cen = sc.surface(4.0, "center")
        rec = sc.surface(4.0, "recto")
        write_surface(sd / "spiral-center", cen, "spiral-center")
        write_surface(sd / "spiral-recto", rec, "spiral-recto")
        doc_s = {"surface_residual_vox": max(cen["residual"], rec["residual"]),
                 "seconds_surfaces": round(time.time() - t3, 1)}
        if sc.ink_on:                                    # ink.tif: which recto surface points are inked
            from . import vc3d_io
            im = sc.ink_surface(rec)
            for name in ("spiral-center", "spiral-recto"):
                vc3d_io.write_tiff(sd / name / "ink.tif", vc3d_io.Raster(im.shape[0], im.shape[1], "u8",
                                                                         im.tobytes()))
            doc_s["ink_surface_share"] = round(float(im[rec["valid"]].mean()), 5) if rec["valid"].any() else None
    air = sum(1 for a, _ in res if a)
    busy = [s for a, s in res if not a]
    pressed = float((sc.press[ANG:sc.n_end] > 0.5).mean()) if sc.n_end > ANG else 0.0
    doc = {"tool": "kit.scrollsim2", "version": VERSION, "code_sha256": code_sha256(),
           "params": sc.p2, "preset": preset, "complete": complete,
           "turns": round(sc.theta_end / (2 * math.pi), 2), "alpha": sc.alpha, "sheet_length_vox": round(sc.s_end, 1),
           "pressed_share": round(pressed, 4), "r_outer_rolled": round(sc.r_outer, 1),
           "scan_model": scan_report(sc.p2),
           "center_line": [[round(float(v), 3) for v in r] for r in sc.cl],
           "render": {"workers": int(workers), "block": int(block), "chunk": int(chunk), "levels": int(levels),
                      "blocks": len(blocks), "blocks_done": len(done), "blocks_this_run": len(res),
                      "air_blocks_this_run": air, "complete": complete, "stopped": stop,
                      "seconds_init": round(t_init, 1),
                      "seconds_level0": round(t_render, 1), "seconds_pyramid": round(t_down, 1),
                      "seconds_per_sheet_block_mean": round(sum(busy) / len(busy), 3) if busy else None,
                      "deadline": deadline, "spare_s": spare, "verified": check,
                      "seconds": round(time.time() - t0, 1), "peak_rss_mb": _peak_rss_mb()},
           "ink": sc.ink_report(),
           "note": "Synthetic volume (scrollsim2). Model output scored here is about this simulator, never a real "
                   "scroll. " + ("Ink is off (the ink_* parameters turn it on)." if not sc.ink_on else
                                 "Its ink is a simple layer model, not calibrated against real ink." if not
                                 int(sc.p2["ink_off"]) else "This is the noink twin: ink truth, no ink in the CT.")}
    doc.update(doc_s)
    (out / "truth.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


def _peak_rss_mb():
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    except Exception:                                   # noqa: BLE001 - the figure is informational
        return None


def estimate(over=None, preset=None, workers=1, block=128, sample=4, seed=0, progress=print):
    """Time a few sheet blocks and extrapolate a full make: classify every block as air or sheet (cheap), render
    SAMPLE random sheet blocks on one core, and scale by the sheet block count over WORKERS. Rendering only; the
    pyramid adds a few percent. The estimate is a probe for the run's cap, not a measurement of the run."""
    np = _np()
    progress = progress or (lambda m: None)
    t0 = time.time()
    sc = Scroll2(dict(params(over, preset)))
    sc.prepare()
    t_init = time.time() - t0
    blocks = _blocks((sc.Z, sc.Y, sc.X), block)
    h = sc.halo()
    t1 = time.time()
    sheet = [b for b in blocks if not sc.block_is_air(b[0] - h, b[1] + h, b[2] - h, b[3] + h, b[4] - h, b[5] + h)]
    t_cls = time.time() - t1
    rng = np.random.default_rng(seed)
    pick = [sheet[i] for i in rng.choice(len(sheet), size=min(sample, len(sheet)), replace=False)] if sheet else []
    times = []
    for b in pick:
        t = time.time()
        sc.scan_block(*b, air=False)
        times.append(time.time() - t)
        progress(f"PROGRESS {len(times)}/{len(pick)} sample blocks {sum(times):.0f}s")
    per = float(np.mean(times)) if times else 0.0
    air_cost = 0.02 * per
    total_core = per * len(sheet) + air_cost * (len(blocks) - len(sheet))
    return {"tool": "kit.scrollsim2 estimate", "shape": [sc.Z, sc.Y, sc.X], "turns": round(sc.theta_end / (2 * math.pi), 2),
            "block": block, "blocks": len(blocks), "sheet_blocks": len(sheet), "sampled": len(pick),
            "seconds_per_sheet_block": round(per, 2), "seconds_init": round(t_init, 1),
            "seconds_classify": round(t_cls, 1), "core_seconds": round(total_core, 0),
            "wall_seconds_at_workers": round(t_init + total_core / max(1, int(workers)), 0), "workers": int(workers),
            "voxels": sc.Z * sc.Y * sc.X, "peak_rss_mb": _peak_rss_mb(),
            "note": "Interpretation: per-block time on this machine times the sheet block count, over the workers; "
                    "air blocks counted at 2 percent of a sheet block"}


def _parse_set(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SimError("--set is KEY=VALUE")
        k, v = it.split("=", 1)
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


MAX_WORKERS = 16     # rendering is bound by memory bandwidth: on a 16-core, 32-thread cloud CPU it saturates from
                     # about 8 processes, and 32 workers ran slower than 16
BLAS_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def default_workers():
    """The CPU count, at most MAX_WORKERS."""
    return max(1, min(os.cpu_count() or 1, MAX_WORKERS))


def single_thread_blas(environ=None):
    """Set each BLAS thread variable to 1 where unset, so a forked worker never runs a BLAS pool as wide as the host
    (an inherited 32-thread OpenMP pool made rendering many times slower). Effective only before numpy is first imported."""
    env = os.environ if environ is None else environ
    for v in BLAS_VARS:
        env.setdefault(v, "1")


def main(argv=None):
    single_thread_blas()
    ap = argparse.ArgumentParser(prog="python -m kit.scrollsim2", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("make", "estimate"):
        a = sub.add_parser(name)
        if name == "make":
            a.add_argument("out")
            a.add_argument("--levels", type=int, default=5)
            a.add_argument("--chunk", type=int, default=128)
            a.add_argument("--surfaces", action="store_true")
            a.add_argument("--resume", action="store_true")
            a.add_argument("--max-blocks", type=int)
            a.add_argument("--order", choices=["zyx", "middle"], default="zyx")
            a.add_argument("--noink", action="store_true", help="the noink twin: ink truth only, no ink in the CT")
        else:
            a.add_argument("--sample", type=int, default=4)
        a.add_argument("--preset", choices=sorted(PRESETS))
        a.add_argument("--scan", choices=sorted(SCANS))
        a.add_argument("--set", action="append", default=[])
        a.add_argument("--seed", type=int)
        a.add_argument("--workers", type=int, default=default_workers())
        a.add_argument("--block", type=int, default=128)
    a = sub.add_parser("pyramid")
    a.add_argument("sim")
    a.add_argument("--workers", type=int, default=default_workers())
    a = sub.add_parser("verify")
    a.add_argument("sim")
    a = sub.add_parser("publish")
    a.add_argument("src")
    a.add_argument("dst")
    a.add_argument("--levels", type=int, nargs="+")
    a.add_argument("--no-labels", action="store_true")
    a = sub.add_parser("vc3d")
    a.add_argument("sim")
    a.add_argument("out")
    a.add_argument("--voxel-um", type=float)
    a.add_argument("--copy", action="store_true")
    a = sub.add_parser("nps")
    a.add_argument("ct")
    a.add_argument("--mask")
    a.add_argument("--tile", type=int, default=32)
    a.add_argument("--share", type=float, default=0.25)
    a.add_argument("--out")
    a = sub.add_parser("info")
    a.add_argument("sim")
    args = ap.parse_args(argv)
    try:
        if args.cmd in ("make", "estimate"):
            over = _parse_set(args.set)
            if args.seed is not None:
                over["seed"] = args.seed
            if args.scan:
                over["scan"] = args.scan
            if args.cmd == "make" and args.noink:
                over = noink(over)
            if args.cmd == "make":
                doc = make(args.out, over, args.preset, args.workers, args.block, args.levels, args.chunk,
                           args.surfaces, progress=lambda m: print(m, file=sys.stderr, flush=True),
                           resume=args.resume, max_blocks=args.max_blocks, order=args.order)
                doc = {k: v for k, v in doc.items() if k != "center_line"}
                if not doc["complete"]:
                    print(json.dumps(doc))
                    return INCOMPLETE
            else:
                doc = estimate(over, args.preset, args.workers, args.block, args.sample,
                               progress=lambda m: print(m, file=sys.stderr, flush=True))
            print(json.dumps(doc))
        elif args.cmd == "vc3d":
            print(json.dumps(export_vc3d(args.sim, args.out, args.voxel_um, args.copy)))
        elif args.cmd == "nps":
            np = _np()
            vol = np.load(args.ct, mmap_mode="r")
            mask = np.load(args.mask).astype(bool) if args.mask else None
            m = measure_nps(vol, args.tile, args.share, mask)
            m["fit"] = fit_nps(m["freq"], m["psd"], m["count"], args.tile)
            m["set"] = "nps=" + json.dumps(m["fit"]["nps"], separators=(",", ":"))
            if args.out:
                Path(args.out).write_text(json.dumps(m, indent=1) + "\n")
            print(json.dumps({k: m[k] for k in ("variance", "tiles", "tiles_seen", "fit", "set")}))
        elif args.cmd in ("pyramid", "verify", "publish"):
            if args.cmd == "publish":
                rep = publish(args.src, args.dst, args.levels, not args.no_labels)
            else:
                rep = pyramid(args.sim, args.workers) if args.cmd == "pyramid" else verify(args.sim)
            print(json.dumps(rep))
            return 0 if rep["ok"] else 1
        else:
            doc = json.loads((Path(args.sim) / "truth.json").read_text())
            doc.pop("center_line", None)
            print(json.dumps(doc, indent=1))
    except SimError as e:
        raise SystemExit(f"scrollsim2: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
