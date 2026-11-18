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
- a scan model: anisotropic point spread, correlated noise, a phase-edge filter, rings, slow drift and
  supersampling for partial volume;
- OME-zarr output with levels 0 to L, written in parallel, chunk-aligned, a winding label volume beside it, and
  optional center and recto surfaces of the whole sheet as tifxyz.

Ink is off in this release. It is a simulator: a score on its volumes is model output on synthetic data and says
nothing about a real scroll. It is not yet calibrated against real CT (see "Realism: in progress" on the tool page).

  python -m kit.scrollsim2 make OUT [--preset smoke|pilot] [--set KEY=VALUE ...] [--workers N] [--block B]
                                     [--levels L] [--chunk C] [--surfaces] [--resume] [--max-blocks N]
  python -m kit.scrollsim2 estimate [--preset ...] [--set ...] [--workers N] [--block B] [--sample K]
  python -m kit.scrollsim2 pyramid OUT [--workers N]     rebuild CT levels 1 and up from level 0, then verify
  python -m kit.scrollsim2 verify OUT                    every CT chunk on disk, no '.partial' temp file
  python -m kit.scrollsim2 publish SRC DST [--levels L ...] [--no-labels]   plain copy of a local folder, then verify
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

VERSION = 1
ANG = 1024                 # samples of the unwrapped angle per turn
GZ = 8.0                   # z step of the geometry fields, voxels
GS = 8.0                   # along-sheet step of the coarse random fields, voxels
WG = 16.0                  # grid step of the displacement field, voxels
HALFMAX = 1.1774           # sqrt(2 ln 2): a Gaussian's half width at half maximum, in sigmas

# The sheet and scan model. Lengths in output voxels. The defaults give a plausible look at about 8 um per voxel;
# they are not a calibration.
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
}
DEFAULTS = dict(json.loads(json.dumps(BASE)), **EXTRA)
PRESETS = {
    # the unit-test scroll
    "smoke": {"shape": [64, 208, 208]},
    # one full cross-section at a short height: about 125 windings at the defaults (mean step about 10.4 voxels at
    # 45 percent contacts), crush axis along x so the box is about half as tall as wide
    "pilot": {"shape": [1024, 1728, 3264], "alpha": 0.0},
}
HASH_SALT = {"noise": 13}
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
    """All parameters: DEFAULTS, then the preset, then OVER."""
    p = json.loads(json.dumps(DEFAULTS))
    if preset:
        if preset not in PRESETS:
            raise SimError(f"unknown preset {preset}; known: {', '.join(PRESETS)}")
        p.update(json.loads(json.dumps(PRESETS[preset])))
    for k, v in (over or {}).items():
        if k not in DEFAULTS:
            raise SimError(f"unknown parameter {k}")
        p[k] = v
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

    def voxels(self, out):
        """As Roll.voxels_all_turns (density, label as turn index, its theta), then an all-false placeholder for
        3D ink truth (ink is off), and the distance to the nearest winding center (voxels, inf outside the roll)."""
        np = _np()
        p = self.p
        rolled = self.rolled(out)
        rho, phi, z, j = self.locate_turn(rolled)
        N = len(rho)
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
            dens += np.where(ok, amp * (recto + verso), 0)
            band = np.abs(d) <= half + HALFMAX * sig
            near = ok & band & (np.abs(d) < best)
            best = np.where(near, np.abs(d), best)
            lab = np.where(near, kk, lab)
            near_any = np.minimum(near_any, np.abs(d))
        theta = phi + 2 * math.pi * np.clip(lab, 0, self.max_k)
        return dens, lab, theta, np.zeros(N, bool), near_any

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
        return int(math.ceil(4 * (max(sz, sxy) + e + float(p["noise_corr"])))) + 2

    def _bias_field(self):
        """The slow brightness drift from the [seed, 11] stream, coarse grid."""
        np = _np()
        if getattr(self, "_bias", None) is None:
            Z, Y, X = self.Z, self.Y, self.X
            rng = np.random.default_rng([int(self.p["seed"]), 11])
            self._bias = _field(rng, (max(2, Z // 32), max(2, Y // 32), max(2, X // 32)), 1.0)
            rr = np.random.default_rng([int(self.p["seed"]), 12])
            self._rings = rr.standard_normal(int(math.hypot(X, Y) / 2) + 4)
        return self._bias

    def density_block(self, z0, z1, y0, y1, x0, x1):
        """Density, winding labels (id + 1, 0 none) and distance to the nearest winding on a box, no scan model."""
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
        offs = (np.arange(n) + 0.5) / n - 0.5
        for a in range(0, N, POINTS_PER_PASS):           # bounded memory: about 1 GB per pass at most
            c = cen[a:a + POINTS_PER_PASS]
            d0, lab, th, _, nr = self.voxels(c)
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
                            acc += self.voxels(c + np.array([ox, oy, oz]))[0]
                dens[a:a + len(c)] = acc / n ** 3
        return dens.reshape(shape), labels.reshape(shape), near.reshape(shape)

    def scan_block(self, z0, z1, y0, y1, x0, x1, air=None):
        """The CT (uint8) and labels of the box, rendered with a halo so no filter sees the block edge."""
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
        else:
            dens, labels, near = self.density_block(Z0, Z1, Y0, Y1, X0, X1)
        v = float(p["air"]) + (float(p["bright"]) - float(p["air"])) * np.clip(dens, 0, 1.6)
        sz = math.hypot(float(p["blur"]), float(p["psf_z"]))
        sxy = math.hypot(float(p["blur"]), float(p["psf_xy"]))
        if sz > 0 or sxy > 0:
            v = nd.gaussian_filter(v, (sz, sxy, sxy), mode="nearest")
        if float(p["edge"]) > 0:
            v = v + float(p["edge"]) * (v - nd.gaussian_filter(v, float(p["edge_sigma"]), mode="nearest"))
        b = self._bias_field()
        if float(p["bias"]) > 0:
            gz = (np.arange(Z0, Z1) + 0.5) / self.Z * b.shape[0] - 0.5
            gy = (np.arange(Y0, Y1) + 0.5) / self.Y * b.shape[1] - 0.5
            gx = (np.arange(X0, X1) + 0.5) / self.X * b.shape[2] - 0.5
            G = np.meshgrid(gz, gy, gx, indexing="ij")
            v = v * (1 + float(p["bias"]) * nd.map_coordinates(b, G, order=1, mode="nearest")).astype(np.float32)
        if float(p["rings"]) > 0:
            yy, xx = np.mgrid[Y0:Y1, X0:X1]
            r = np.clip(np.rint(np.hypot(yy - (self.Y - 1) / 2, xx - (self.X - 1) / 2)).astype(np.int64), 0,
                        len(self._rings) - 1)
            v = v + (self._rings[r] * float(p["rings"]))[None].astype(np.float32)
        if float(p["noise"]) > 0:
            w = hashed_normal(p["seed"], Z0, Z1, Y0, Y1, X0, X1)
            c = float(p["noise_corr"])
            if c > 0:
                w = nd.gaussian_filter(w, c, mode="nearest") / _smooth_noise_gain(max(c, 1e-6))
            v = v + float(p["noise"]) * w
        ct = np.clip(np.rint(v), 0, 255).astype(np.uint8)
        core = (slice(h, h + z1 - z0), slice(h, h + y1 - y0), slice(h, h + x1 - x0))
        return ct[core], labels[core], bool(air)


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
    ct, labels, air = _SC.scan_block(*b)
    g = zarr.open_group(str(out / "ct.zarr"), mode="r+")
    _write_checked(out / "ct.zarr" / "0", g["0"], b, ct)
    lg = zarr.open_group(str(out / "truth" / "labels.zarr"), mode="r+")
    _write_checked(out / "truth" / "labels.zarr" / "0", lg["0"], b, labels)
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
        datasets.append({"path": str(lev), "coordinateTransformations": [{"type": "scale", "scale": [2.0 ** lev] * 3}]})
    g.attrs["multiscales"] = [{"version": "0.4", "name": "scrollsim2", "axes": [
        {"name": n, "type": "space", "unit": "micrometer"} for n in "zyx"], "datasets": datasets}]
    lg = zarr.open_group(str(out / "truth" / "labels.zarr"), mode="w", zarr_format=2)
    lg.create_array("0", shape=shapes[0], chunks=tuple(min(chunk, s) for s in shapes[0]), dtype="uint16", fill_value=0)
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
    air = sum(1 for a, _ in res if a)
    busy = [s for a, s in res if not a]
    pressed = float((sc.press[ANG:sc.n_end] > 0.5).mean()) if sc.n_end > ANG else 0.0
    doc = {"tool": "kit.scrollsim2", "version": VERSION, "code_sha256": code_sha256(),
           "params": sc.p2, "preset": preset, "complete": complete,
           "turns": round(sc.theta_end / (2 * math.pi), 2), "alpha": sc.alpha, "sheet_length_vox": round(sc.s_end, 1),
           "pressed_share": round(pressed, 4), "r_outer_rolled": round(sc.r_outer, 1),
           "center_line": [[round(float(v), 3) for v in r] for r in sc.cl],
           "render": {"workers": int(workers), "block": int(block), "chunk": int(chunk), "levels": int(levels),
                      "blocks": len(blocks), "blocks_done": len(done), "blocks_this_run": len(res),
                      "air_blocks_this_run": air, "complete": complete, "stopped": stop,
                      "seconds_init": round(t_init, 1),
                      "seconds_level0": round(t_render, 1), "seconds_pyramid": round(t_down, 1),
                      "seconds_per_sheet_block_mean": round(sum(busy) / len(busy), 3) if busy else None,
                      "deadline": deadline, "spare_s": spare, "verified": check,
                      "seconds": round(time.time() - t0, 1), "peak_rss_mb": _peak_rss_mb()},
           "note": "Synthetic volume (scrollsim2). Model output scored here is about this simulator, never a real "
                   "scroll. Ink is off in this release."}
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
        else:
            a.add_argument("--sample", type=int, default=4)
        a.add_argument("--preset", choices=sorted(PRESETS))
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
    a = sub.add_parser("info")
    a.add_argument("sim")
    args = ap.parse_args(argv)
    try:
        if args.cmd in ("make", "estimate"):
            over = _parse_set(args.set)
            if args.seed is not None:
                over["seed"] = args.seed
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
