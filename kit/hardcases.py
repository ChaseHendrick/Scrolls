#!/usr/bin/env python3
"""ScrollSim Hard Cases (kit hardcases): exact 3D sheet layouts for the hard cases of papyrus CT.

Each layout is a function of continuous position (z, y, x): a sheet coordinate f, sheets centred on fixed levels of
f, and masks for air, crack openings and delamination gaps. Any block, any slice direction and any grid gives the
same sheets, so a 2D training tile and a 3D volume of one layout agree voxel for voxel, and every sheet keeps its
exact id. The kinds follow the hard-case layouts of Synthetic-Slices v0.2 (vincentl065, MIT licence,
https://github.com/vincentl065/Synthetic-Slices, read 24 Nov 2026), rebuilt here as 3D fields rather than copied:

- plain: a gently bent stack with undulations and pitch changes;
- spiral: a flattened spiral with its centre (umbilicus) in or near the box, which Synthetic-Slices lacks;
- hairpin, tight_u, tight_bend: offsets of a folded centre line (arc plus tangent arms), so the folded sheet keeps
  one id round the fold;
- accordion: a stack zig-zagging with rounded tips, optionally compact;
- mush: crushed sheets with short, weak, patchy waviness, painted crushed by the renderer;
- delamination: one sheet's two plies part over a lens, both keeping the sheet's id;
- crack: a jagged fault through the stack, sheets cut and offset, the opening painted as air;
- edge: the scroll's outer edge, the last sheets ending raggedly, air beyond.

Extras on top of a kind: contact (two neighbours pressed together over a patch, their lines at least 3 px apart)
and a crushed patch. A physics renderer (two plies per sheet, fibre texture, gap debris, inclusions, point spread,
a phase-contrast rim, white, ramp and correlated noise, slow gain) turns a layout into CT.

    python -m kit hardcases tiles OUT.npz --n 2000 --seed 1 [--size 256] [--side 0.3] [--kinds plain,spiral,...]
    python -m kit hardcases volume OUT.npz --kind hairpin --seed 3 [--shape 64,256,256]
    python -m kit hardcases info

Shards follow Synthetic-Slices' format (image, lines, sheet_id, dist, kind, crack, crushed) plus air. The grid is
9.362 um per voxel by default, Synthetic-Slices' scale. numpy and scipy only.

It is a simulator: a score on its tiles is model output on synthetic data and says nothing about a real scroll.
"""

import argparse
import json
import math
import sys
import time

VOXEL_UM = 9.362
KINDS = ("plain", "spiral", "hairpin", "tight_u", "tight_bend", "accordion", "mush", "delamination", "crack", "edge")
# Shares of the default recipe: Synthetic-Slices' S5 recipe gives 50 % plain, 25 % folds and 25 % hard cases; here
# spirals take part of the plain share, and the edge is a kind of its own.
RECIPE = {"plain": 0.25, "spiral": 0.15, "hairpin": 0.08, "tight_u": 0.07, "tight_bend": 0.06, "accordion": 0.07,
          "mush": 0.08, "delamination": 0.08, "crack": 0.08, "edge": 0.08}
EXTRAS = {"contact": 0.25, "crushed_patch": 0.15, "inclusions": 0.25, "debris": 0.25}
# Sheet pitch at 9.362 um: Synthetic-Slices calibrated 5th, 50th and 95th percentiles of 4.75, 7.75 and 16 px at
# 18.7 um on real m7 slices; doubled here.
PITCH_P50 = 15.5
PITCH_SIGMA = 0.37
PITCH_MIN = 9.0
THICK_MIN = 3.0
LINE_SEP_MIN = 3.0
# Hard-case zone bits of raster()["zone"], so a detector or tracer can be scored per hard case.
ZONES = {"fold": 1, "contact": 2, "delamination": 4, "crack": 8, "crushed": 16, "edge": 32, "centre": 64}
DIST_CLIP = 255


class SimError(ValueError):
    pass


def _np():
    import numpy
    return numpy


def _ndi():
    from scipy import ndimage
    return ndimage


class Wave:
    """A smooth random field of unit variance: a sum of N cosines with random wave vectors of length about
    2 pi / scale (per axis scale (z, y, x)), so it can be evaluated at any position, in any block."""

    def __init__(self, rng, scale, n=8, zscale=None):
        np = _np()
        sz = float(zscale if zscale is not None else scale)
        d = rng.normal(size=(n, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        mag = 2 * math.pi * rng.uniform(0.6, 1.4, n)
        self.k = d * mag[:, None] / np.array([sz, float(scale), float(scale)])
        self.ph = rng.uniform(0, 2 * math.pi, n)
        a = rng.normal(size=n)
        self.a = a / math.sqrt(float((a ** 2).sum()) / 2)

    def __call__(self, z, y, x):
        np = _np()
        out = 0.0
        for j in range(len(self.a)):
            out = out + self.a[j] * np.cos(self.k[j, 0] * z + self.k[j, 1] * y + self.k[j, 2] * x + self.ph[j])
        return out


def pitch_draw(rng, n, compact=False):
    """N gaps between sheet centres, in voxels: lognormal about PITCH_P50, or near the minimum when COMPACT."""
    np = _np()
    if compact:
        return np.clip(rng.uniform(PITCH_MIN, PITCH_MIN + 4, n), PITCH_MIN, None)
    return np.clip(PITCH_P50 * np.exp(rng.normal(0, PITCH_SIGMA, n)), PITCH_MIN, 48.0)


def _levels(rng, lo, hi, compact=False, scale=1.0, start=None):
    """Sheet centre levels covering [lo, hi] and their thicknesses, so neighbouring sheets keep a gap of at least
    1.5 voxels and every sheet is at least THICK_MIN thick. SCALE is the largest |grad f| the levels must allow for
    (gaps in f are SCALE times the drawn gaps)."""
    np = _np()
    span = hi - lo
    n = int(span / (PITCH_MIN * scale)) + 8
    g = pitch_draw(rng, n, compact) * scale
    s0 = lo - float(g[0]) * rng.uniform(0.2, 1.0) if start is None else float(start)
    lv = s0 + np.concatenate([[0.0], np.cumsum(g)])
    lv = lv[lv <= hi + 2 * float(g.max())]
    gaps = np.diff(lv) / scale
    left = np.concatenate([[gaps[0]], gaps])
    right = np.concatenate([gaps, [gaps[-1]]])
    near = np.minimum(left, right)
    t = rng.uniform(0.38, 0.66, len(lv)) * near
    t = np.clip(t, THICK_MIN, 16.0)
    # keep a gap of at least 1.5 voxels between neighbours
    for i in range(len(lv) - 1):
        over = (t[i] + t[i + 1]) / 2 + 1.5 - gaps[i]
        if over > 0:
            t[i] = max(THICK_MIN, t[i] - over)
            t[i + 1] = max(THICK_MIN, t[i + 1] - over)
    return lv.astype(float), t.astype(float)


def _squeeze(np, f, a, g0, s):
    """Monotone level map that narrows the level span [a, a + g0] by s (0 <= s < g0): levels below a stay, levels
    above a + g0 move down by s. Returns the new f as a function of position."""
    s = np.clip(s, 0, 0.95 * g0)
    lo = f < a
    mid = (f >= a) & (f < a + g0 - s)
    out = np.where(lo, f, f + s)
    return np.where(mid, a + (f - a) * g0 / np.maximum(g0 - s, 1e-6), out)


def _open(np, f, a, h):
    """Monotone level map that opens a gap of h voxels at level a: positions with f in [a, a + h) map to a (the
    opening, returned as a mask), positions above to f - h."""
    h = np.maximum(h, 0)
    gap = (f >= a) & (f < a + h) & (h > 0)
    out = np.where(f < a, f, np.where(f < a + h, a, f - h))
    return out, gap


class Layout:
    """One random layout of KIND, a function of position. field(z, y, x) gives (f, masks); levels and thick hold
    the sheet centres and thicknesses in f. The box is SIZE (z, y, x) voxels; positions outside it are valid too."""

    def __init__(self, kind, seed, size=(1, 256, 256), extras=None):
        np = _np()
        if kind not in KINDS:
            raise SimError(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
        self.kind = kind
        self.seed = int(seed)
        self.size = tuple(int(v) for v in size)
        rng = np.random.default_rng([self.seed, KINDS.index(kind), 7919])
        self.rng_seed = int(rng.integers(1 << 62))
        Z, H, W = self.size
        self.c = np.array([Z / 2, H / 2, W / 2], float)
        self.theta = rng.uniform(0, 2 * math.pi)
        self.tilt = rng.normal(0, 0.003)
        self.compact = bool(kind in ("mush",) or (kind in ("hairpin", "tight_u", "tight_bend", "accordion")
                                                  and rng.random() < 0.3))
        diag = math.hypot(H, W) + Z
        self.reach = diag
        self.p = {}
        ex = dict(EXTRAS if extras is None else extras)
        hard = kind in ("mush", "delamination", "crack")
        self.contact = (not hard) and rng.random() < ex.get("contact", 0)
        self.crushed = 1 if kind == "mush" else (2 if (kind != "edge" and rng.random() < ex.get("crushed_patch", 0))
                                                 else 0)
        self.inclusions = bool(rng.random() < ex.get("inclusions", 0))
        self.debris = bool(rng.random() < ex.get("debris", 0))
        self.w_und = Wave(rng, rng.uniform(150, 400), zscale=rng.uniform(300, 900))
        self.w_pitch = Wave(rng, rng.uniform(200, 500), zscale=rng.uniform(400, 1200))
        self.a_und = rng.uniform(2, 14)
        self.a_pitch = rng.uniform(0.0, 0.12)
        self.kappa = rng.normal(0, 1 / 900)
        getattr(self, "_init_" + kind)(rng)
        if self.contact:
            self._init_contact(rng)
        if self.crushed == 2:
            self.patch = (self.c + rng.uniform(-0.3, 0.3, 3) * np.array([Z, H, W]), rng.uniform(30, 90, 3))
        self.check = self._self_check()

    # frame -----------------------------------------------------------------------------------------------------
    def frame(self, z, y, x):
        """(u, v): along and across the stack in the slice plane, the across axis turning slowly with z."""
        np = _np()
        th = self.theta + self.tilt * (z - self.c[0])
        dy, dx = y - self.c[1], x - self.c[2]
        u = dx * np.cos(th) + dy * np.sin(th)
        v = -dx * np.sin(th) + dy * np.cos(th)
        return u, v

    def _stack(self, z, y, x):
        np = _np()
        u, v = self.frame(z, y, x)
        und = self.a_und * self.w_und(z, y, x) + 0.5 * self.kappa * u ** 2
        f = (v + und) * (1 + self.a_pitch * self.w_pitch(z, y, x))
        return f, u, v

    # kinds -------------------------------------------------------------------------------------------------------
    def _plain_levels(self, rng, compact=False):
        r = self.reach * (1 + self.a_pitch) + 3 * self.a_und + 40
        self.levels, self.thick = _levels(rng, -r, r, compact, scale=1 + self.a_pitch)

    def _init_plain(self, rng):
        self._plain_levels(rng)

    def _f_plain(self, z, y, x):
        f, u, v = self._stack(z, y, x)
        return f, {"u": u}

    def _init_spiral(self, rng):
        Z, H, W = self.size
        np = _np()
        inside = rng.random() < 0.6
        off = rng.uniform(0.15, 0.85, 2) if inside else rng.uniform(-0.6, 1.6, 2)
        self.sc = np.array([off[0] * H, off[1] * W])
        self.sdrift = rng.normal(0, 0.05, 2)
        self.ecc = rng.uniform(0.55, 1.0)
        self.sp = float(pitch_draw(rng, 1)[0])
        self.hole = rng.uniform(1.5, 5.0) * self.sp
        self.warp_a = rng.uniform(0, 0.6) * self.sp
        self.warp_l = rng.uniform(2.5, 6.0) * self.sp
        rmax = math.hypot(H, W) * 2.5 + 2 * self.sp
        k0 = int(math.ceil(self.hole / self.sp))
        self.levels = np.arange(k0, int(rmax / self.sp) + 2, dtype=float) * self.sp
        t = rng.uniform(0.38, 0.62) * self.sp * np.ones(len(self.levels))
        t *= np.exp(rng.normal(0, 0.12, len(t)))
        self.thick = np.clip(t, THICK_MIN, self.sp - 1.5)

    def _f_spiral(self, z, y, x):
        np = _np()
        cz = z - self.c[0]
        cy = self.sc[0] + self.sdrift[0] * cz
        cx = self.sc[1] + self.sdrift[1] * cz
        th0 = self.theta + self.tilt * cz
        dy, dx = y - cy, x - cx
        a = dx * np.cos(th0) + dy * np.sin(th0)
        b = (-dx * np.sin(th0) + dy * np.cos(th0)) / self.ecc
        r = np.hypot(a, b)
        th = np.arctan2(b, a)
        r = r + self.warp_a * np.sin(r / self.warp_l)
        f = r - self.sp * (th + math.pi) / (2 * math.pi)
        return f, {"u": th * np.maximum(r, 1), "zone_centre": r < self.hole + 3 * self.sp}

    def _init_fold(self, rng, span, rlo, rhi):
        np = _np()
        Z, H, W = self.size
        self.fold_span = span
        self.p0 = float(pitch_draw(rng, 1)[0])
        self.R0 = float(rng.uniform(rlo, rhi))
        self.apex = np.array([rng.uniform(0.2, 0.8) * H, rng.uniform(0.2, 0.8) * W])
        self.fold_w = Wave(rng, rng.uniform(200, 500), zscale=rng.uniform(200, 600))
        self.fold_drift = rng.normal(0, 0.08, 2)
        r = self.reach + 40
        lv_out, t_out = _levels(rng, 0, r, self.compact, start=0.0)
        inner = []
        if self.kind != "hairpin":
            g = pitch_draw(rng, 40, self.compact)
            acc = 0.0
            for gi in g:
                acc += gi
                if acc > 0.8 * (self.R0 * 0.85) - THICK_MIN:
                    break
                inner.append(-acc)
        lv = np.concatenate([np.array(sorted(inner)), lv_out])
        self.levels = lv
        gaps = np.diff(lv)
        left = np.concatenate([[gaps[0]], gaps])
        right = np.concatenate([gaps, [gaps[-1]]])
        near = np.minimum(left, right)
        t = np.clip(rng.uniform(0.4, 0.62, len(lv)) * near, THICK_MIN, 14.0)
        if self.kind == "hairpin":
            i0 = int(np.argmin(np.abs(lv)))
            t[i0] = min(t[i0], 2 * self.R0 - 1.0)
        for i in range(len(lv) - 1):
            over = (t[i] + t[i + 1]) / 2 + 1.5 - gaps[i]
            if over > 0:
                t[i] = max(THICK_MIN, t[i] - over)
                t[i + 1] = max(THICK_MIN, t[i + 1] - over)
        self.thick = t
        # inner sheets may not reach the centre of the arc: the smallest inner level stays above -R
        keep = self.levels > -(0.85 * self.R0 - self.thick / 2 - 1.0)
        self.levels, self.thick = self.levels[keep], self.thick[keep]

    def _f_fold(self, z, y, x):
        """Signed distance to a centre line made of an arc of radius R spanning fold_span radians and two tangent
        rays, outside positive. Offsets of it are the sheets."""
        np = _np()
        cz = z - self.c[0]
        R = self.R0 * (1 + 0.08 * self.fold_w(z, 0 * y, 0 * x))
        ay = self.apex[0] + self.fold_drift[0] * cz
        ax = self.apex[1] + self.fold_drift[1] * cz
        th = self.theta + self.tilt * cz
        dy, dx = y - ay, x - ax
        a = dx * np.cos(th) + dy * np.sin(th)
        b = -dx * np.sin(th) + dy * np.cos(th)
        # arc centred at the origin, symmetric about +a, from -span/2 to +span/2
        h = self.fold_span / 2
        rho = np.hypot(a, b)
        ang = np.arctan2(b, a)
        on_arc = np.abs(ang) <= h
        d_arc = np.where(on_arc, np.abs(rho - R), np.inf)
        s_arc = np.sign(rho - R)
        best = d_arc
        sign = s_arc
        for sgn in (-1.0, 1.0):
            ea = R * math.cos(h)
            eb = sgn * R * math.sin(h)
            # tangent pointing away from the arc
            ta, tb = -math.sin(h), sgn * math.cos(h)
            pa, pb = a - ea, b - eb
            t = pa * ta + pb * tb
            # outward normal (away from the arc's centre)
            na, nb = math.cos(h), sgn * math.sin(h)
            perp = pa * na + pb * nb
            d_ray = np.where(t >= 0, np.abs(perp), np.hypot(pa, pb))
            s_ray = np.where(t >= 0, np.sign(perp), np.sign(rho - R))
            better = d_ray < best
            best = np.where(better, d_ray, best)
            sign = np.where(better, s_ray, sign)
        f = sign * best
        # the fold zone: the arc and two pitches beyond its ends
        return f, {"u": a, "zone_fold": (np.abs(ang) <= h + 0.35) & (rho < R + 6 * self.p0)}

    def _init_hairpin(self, rng):
        self._init_fold(rng, math.pi, THICK_MIN / 2 + 0.6, THICK_MIN / 2 + 2.5)
        self.R0 = max(self.R0, self.thick[int(_np().argmin(_np().abs(self.levels)))] / 2 + 0.6)

    def _init_tight_u(self, rng):
        self._init_fold(rng, math.pi, 1.2 * PITCH_P50, 3.5 * PITCH_P50)

    def _init_tight_bend(self, rng):
        self._init_fold(rng, math.radians(rng.uniform(60, 130)), 0.8 * PITCH_P50, 4.0 * PITCH_P50)

    _f_hairpin = _f_fold
    _f_tight_u = _f_fold
    _f_tight_bend = _f_fold

    def _init_accordion(self, rng):
        self.acc_P = rng.uniform(40, 120)
        self.acc_alpha = math.radians(rng.uniform(30, 65))
        self.acc_A = math.tan(self.acc_alpha) * self.acc_P / 4
        self.acc_round = rng.uniform(0.85, 0.97)
        self.acc_w = Wave(rng, rng.uniform(150, 400), zscale=rng.uniform(150, 500))
        scale = 1 / math.cos(self.acc_alpha)
        r = self.reach + self.acc_A + 40
        self.levels, self.thick = _levels(rng, -r * scale, r * scale, self.compact, scale=scale)

    def _f_accordion(self, z, y, x):
        np = _np()
        u, v = self.frame(z, y, x)
        t = u / self.acc_P + 0.15 * self.acc_w(z, y, x)
        zig = (2 / math.pi) * np.arcsin(self.acc_round * np.sin(2 * math.pi * t)) / ((2 / math.pi) * math.asin(self.acc_round))
        f = v - self.acc_A * zig
        return f, {"u": u}

    def _init_mush(self, rng):
        self.m_P = rng.uniform(30, 70)
        self.m_A = rng.uniform(1.5, 3.5)
        self.m_w1 = Wave(rng, rng.uniform(80, 160), zscale=rng.uniform(80, 200))
        self.m_w2 = Wave(rng, rng.uniform(150, 250), zscale=rng.uniform(150, 300))
        self.m_w3 = Wave(rng, rng.uniform(40, 80), zscale=rng.uniform(40, 120))
        self.m_k = rng.uniform(0.15, 0.35)
        grad = 1 + 2 * math.pi * self.m_A * 1.6 / self.m_P
        self.a_und = min(self.a_und, 6.0)
        r = self.reach + 40
        self.levels, self.thick = _levels(rng, -r * grad, r * grad, True, scale=grad)

    def _f_mush(self, z, y, x):
        np = _np()
        u, v = self.frame(z, y, x)
        am = self.m_A * np.clip(0.6 + 0.6 * self.m_w1(z, y, x), 0, 1.6)
        t = u / self.m_P + 0.3 * self.m_w2(z, y, x) + self.m_k * self.m_w3(z, y, x)
        return v + am * np.sin(2 * math.pi * t), {"u": u}

    def _init_delamination(self, rng):
        np = _np()
        self._plain_levels(rng)
        mid = int(np.argmin(np.abs(self.levels)))
        i = int(np.clip(mid + rng.integers(-2, 3), 1, len(self.levels) - 2))
        self.d_i = i
        gap = float(self.levels[i + 1] - self.levels[i])
        self.d_sl = rng.uniform(40, 90)
        self.d_sz = rng.uniform(30, 90)
        self.d_h = rng.uniform(0.72, 0.85) * rng.uniform(0.6, 0.9) * gap
        self.d_u0 = rng.uniform(-0.25, 0.25) * min(self.size[1:])
        self.d_z0 = rng.uniform(-0.3, 0.3) * max(self.size[0], 1)

    def _f_delamination(self, z, y, x):
        np = _np()
        f, u, v = self._stack(z, y, x)
        g = np.exp(-0.5 * (((u - self.d_u0) / self.d_sl) ** 2 + ((z - self.c[0] - self.d_z0) / self.d_sz) ** 2))
        h = self.d_h * g
        f2, gap = _open(np, f, self.levels[self.d_i], h)
        Li = self.levels[self.d_i]
        near = np.abs(f - Li) < 2 * float(self.levels[self.d_i + 1] - Li) + h
        return f2, {"u": u, "opening": gap, "delam_h": h, "zone_delam": (g > 0.1) & near}

    def _init_crack(self, rng):
        np = _np()
        Z, H, W = self.size
        self._plain_levels(rng)
        gap = float(np.median(np.diff(self.levels)))
        self.k_c = np.array([rng.uniform(0.2, 0.8) * H, rng.uniform(0.2, 0.8) * W])
        self.k_psi = math.radians(rng.uniform(4, 22)) * rng.choice([-1, 1])
        self.k_jag = Wave(rng, rng.uniform(30, 80), n=10, zscale=rng.uniform(60, 200))
        self.k_jag_a = rng.uniform(2, 10)
        self.k_wnoise = Wave(rng, 25, n=10, zscale=60)
        self.k_D0 = rng.choice([-1, 1]) * rng.uniform(0.3, 2.2) * gap
        self.k_Lt = max(40.0, 2.5 * abs(self.k_D0))
        self.k_a0, self.k_a1 = -rng.uniform(80, 600), rng.uniform(80, 600)
        self.k_w0 = rng.uniform(3, 16)
        self.k_recede = rng.uniform(0, 7, (len(self.levels), 2))

    def _f_crack(self, z, y, x):
        np = _np()
        f, u, v = self._stack(z, y, x)
        cz = z - self.c[0]
        th = self.theta + self.tilt * cz + math.pi / 2 + self.k_psi
        dy, dx = y - self.k_c[0], x - self.k_c[1]
        a = dx * np.cos(th) + dy * np.sin(th)
        b = -dx * np.sin(th) + dy * np.cos(th)
        bb = b - self.k_jag_a * self.k_jag(z, a, 0 * a)
        t = np.clip(np.minimum(a - self.k_a0, self.k_a1 - a) / self.k_Lt, 0, 1)
        w = self.k_w0 * t ** 0.6 * np.clip(1 + 0.35 * self.k_wnoise(z, a, 0 * a), 0.4, 1.6)
        half = np.where(t > 0, np.maximum(w / 2, 1.5), 0.0)
        f = f + self.k_D0 * t * (bb > 0)
        opening = (t > 0) & (np.abs(bb) <= half)
        return f, {"u": u, "opening_air": opening, "crack": opening, "crack_b": bb, "crack_half": half,
                   "zone_crack": (t > 0) & (np.abs(bb) <= half + 12)}

    def _init_edge(self, rng):
        np = _np()
        self._plain_levels(rng)
        mid = int(np.argmin(np.abs(self.levels)))
        self.e_last = int(np.clip(mid + rng.integers(-3, 4), 2, len(self.levels) - 3))
        nfray = int(rng.integers(1, 4))
        self.e_ends = {}
        span = max(self.size[1:])
        for j in range(nfray):
            k = self.e_last - j
            self.e_ends[k] = (rng.uniform(-0.45, 0.45) * span, Wave(rng, rng.uniform(40, 120), zscale=80),
                              rng.uniform(5, 30), rng.choice([-1, 1]))

    def _f_edge(self, z, y, x):
        f, u, v = self._stack(z, y, x)
        L = self.levels[self.e_last] + self.thick[self.e_last] / 2 + 2.0
        return f, {"u": u, "air": f > L, "zone_edge": (f > self.levels[max(0, self.e_last - 3)]) & (f <= L + 8)}

    def _init_contact(self, rng):
        np = _np()
        Z, H, W = self.size
        n = len(self.levels)
        mid = int(np.argmin(np.abs(self.levels)))
        picks = []
        for _ in range(int(rng.integers(1, 3))):
            i = int(np.clip(mid + rng.integers(-4, 4), 0, n - 2))
            if i in picks or (i + 1) in picks or (i - 1) in picks:
                continue
            picks.append(i)
        self.c_pairs = []
        for i in picks:
            g0 = float(self.levels[i + 1] - self.levels[i] - (self.thick[i] + self.thick[i + 1]) / 2)
            if g0 <= 0.5:
                continue
            L = rng.uniform(30, 300)
            u0 = rng.uniform(-0.3, 0.3) * min(H, W)
            self.c_pairs.append((i, float(self.levels[i] + self.thick[i] / 2), g0, L, u0, rng.uniform(0.7, 0.97)))

    # field and checks --------------------------------------------------------------------------------------------
    def field(self, z, y, x):
        """(f, masks) at positions z, y, x (broadcastable arrays)."""
        np = _np()
        z, y, x = np.broadcast_arrays(np.asarray(z, float), np.asarray(y, float), np.asarray(x, float))
        f, m = getattr(self, "_f_" + self.kind)(z, y, x)
        if self.contact and self.c_pairs:
            u = m["u"]
            zc = np.zeros(f.shape, bool)
            for i, a, g0, L, u0, depth in self.c_pairs:
                bump = np.exp(-0.5 * ((u - u0) / L) ** 2) * np.exp(-0.5 * ((z - self.c[0]) / (2 * L)) ** 2)
                zc |= (bump > 0.3) & (f > a - 2 * g0 - 10) & (f < a + 2 * g0 + 10)
                f = _squeeze(np, f, a, g0, depth * g0 * bump)
            m["zone_contact"] = zc
        return f, m

    def _self_check(self):
        np = _np()
        lv = self.levels
        if len(lv) < 2:
            raise SimError("layout has fewer than two sheets")
        if not np.all(np.diff(lv) > 0):
            raise SimError("sheet levels are not increasing")
        sep = np.diff(lv) - (self.thick[:-1] + self.thick[1:]) / 2
        return {"sheets": int(len(lv)), "min_gap_f": float(sep.min()), "min_thick": float(self.thick.min())}

    def describe(self):
        d = {"kind": self.kind, "seed": self.seed, "size": list(self.size), "compact": self.compact,
             "contact": bool(self.contact and getattr(self, "c_pairs", [])), "crushed": int(self.crushed),
             "inclusions": self.inclusions, "debris": self.debris}
        d.update(self.check)
        return d


def kind_name(lay):
    """Synthetic-Slices style kind label: base kind, _compact, +contact, +crushed."""
    s = lay.kind + ("_compact" if lay.compact and lay.kind != "mush" else "")
    if lay.contact and getattr(lay, "c_pairs", []):
        s += "+contact"
    if lay.crushed == 2:
        s += "+crushed"
    return s


def _grid(np, plane, origin, shape):
    """Positions of a grid: PLANE 'z' gives an axial slice (y, x) at origin z, 'y' a side slice (z, x); 'vol' a
    (z, y, x) block. ORIGIN is the first voxel (z, y, x); SHAPE the grid shape (2 or 3 values)."""
    z0, y0, x0 = (float(v) for v in origin)
    if plane == "vol":
        Z, H, W = shape
        return (z0 + np.arange(Z)[:, None, None], y0 + np.arange(H)[None, :, None], x0 + np.arange(W)[None, None, :])
    A, B = shape
    if plane == "z":
        return (np.full((1, 1), z0), y0 + np.arange(A)[:, None], x0 + np.arange(B)[None, :])
    if plane == "y":
        return (z0 + np.arange(A)[:, None], np.full((1, 1), y0), x0 + np.arange(B)[None, :])
    raise SimError(f"unknown plane {plane!r}")


def raster(lay, plane="z", origin=(0, 0, 0), shape=(256, 256), eps=0.25):
    """Rasterize LAY on a grid. Returns a dict of arrays of SHAPE: sheet (uint16, sheet id plus 1 in every sheet
    voxel, 0 in gaps and air), lines (uint16, id plus 1 on each sheet's median line in the grid's plane, or its
    median surface for a 'vol' grid), q (float32, position across the sheet, -1 to 1, nan outside sheets), air,
    crack, opening (bool), crushed (uint8 0/1 mask of the crushed look), and gpar (float32, |grad f| along the
    grid's in-plane axes), plus levels and thick."""
    np = _np()
    z, y, x = _grid(np, plane, origin, shape)
    z, y, x = np.broadcast_arrays(z, y, x)
    f, m = lay.field(z, y, x)
    # gradient by central differences on the continuous field
    g2 = []
    gs = []
    for ax in range(3):
        dz, dy, dx = [(eps if ax == j else 0.0) for j in range(3)]
        fp, _ = lay.field(z + dz, y + dy, x + dx)
        fm, _ = lay.field(z - dz, y - dy, x - dx)
        gs.append((fp - fm) / (2 * eps))
    in_plane = {"z": (1, 2), "y": (0, 2), "vol": (0, 1, 2)}[plane]
    gmag = np.sqrt(sum(g ** 2 for g in gs))
    gmax_plane = np.max(np.stack([np.abs(gs[a]) for a in in_plane]), axis=0)
    gmag = np.maximum(gmag, 1e-3)
    lv, th = lay.levels, lay.thick
    k = np.clip(np.searchsorted(lv, f), 1, len(lv) - 1)
    k = np.where(np.abs(f - lv[k - 1]) <= np.abs(f - lv[k]), k - 1, k)
    df = f - lv[k]
    d = df / gmag
    t = th[k]
    air = np.zeros(f.shape, bool)
    opening = np.zeros(f.shape, bool)
    crack = np.zeros(f.shape, bool)
    gone = np.zeros(f.shape, bool)
    if "air" in m:
        air |= m["air"]
    if "opening_air" in m:
        air |= m["opening_air"]
        crack |= m["crack"]
        # sheets recede from the crack edge by a few voxels each
        rec = lay.k_recede[k, (m["crack_b"] > 0).astype(int)]
        gone |= (m["crack_half"] > 0) & (np.abs(m["crack_b"]) <= m["crack_half"] + rec)
    if "opening" in m:
        opening |= m["opening"]
    if lay.kind == "edge":
        u = m["u"]
        for kk, (e0, w, wa, sgn) in lay.e_ends.items():
            end = e0 + wa * w(z, y, x)
            gone |= (k == kk) & (sgn * (u - end) > 0)
        gone |= k > lay.e_last
    inside = (np.abs(d) < t / 2) & ~air & ~opening & ~gone
    sheet = np.where(inside, k + 1, 0).astype(np.uint16)
    q = np.where(inside, 2 * d / t, np.nan).astype(np.float32)
    # median line: the level crossing, about one voxel wide in the grid's plane
    target = np.zeros(f.shape)
    if lay.kind == "delamination":
        h = m["delam_h"]
        sep = (k == lay.d_i) & (h >= 2.0)
        target = np.where(sep, np.sign(df) * th[lay.d_i] / 4, 0.0)
    near = np.abs(df - target) <= 0.5 * np.maximum(gmax_plane, 1e-3)
    if lay.kind == "delamination":
        # inside the opening f is flat at the level: no line there
        near &= ~opening
    lines = np.where(near & ~air & ~gone & (np.abs(d) < t / 2 + 1), k + 1, 0).astype(np.uint16)
    crushed = np.zeros(f.shape, np.uint8)
    if lay.crushed == 1:
        crushed[...] = 1
    elif lay.crushed == 2:
        (pz, py, px), (rz, ry, rx) = lay.patch
        r2 = ((z - pz) / max(rz, 1)) ** 2 + ((y - py) / ry) ** 2 + ((x - px) / rx) ** 2
        crushed = (r2 < 1).astype(np.uint8)
    zone = np.zeros(f.shape, np.uint8)
    for key, bit in (("zone_fold", "fold"), ("zone_contact", "contact"), ("zone_delam", "delamination"),
                     ("zone_crack", "crack"), ("zone_edge", "edge"), ("zone_centre", "centre")):
        if key in m:
            zone |= (np.broadcast_to(m[key], f.shape).astype(np.uint8) * ZONES[bit])
    zone |= crushed.astype(np.uint8) * ZONES["crushed"]
    out = {"sheet": sheet, "lines": lines, "q": q, "air": air, "crack": crack, "opening": opening,
           "crushed": crushed, "zone": zone, "levels": lv, "thick": th}
    if plane != "vol":
        out = {kk: (vv.reshape(shape) if hasattr(vv, "shape") and vv.ndim and vv.size == shape[0] * shape[1]
                    else vv) for kk, vv in out.items()}
    return out


def line_separation(lines):
    """Smallest distance (voxels) from a line pixel to a line pixel of another sheet, for a 2D line image (ids)."""
    np = _np()
    nd = _ndi()
    ids = [int(v) for v in np.unique(lines) if v]
    if len(ids) < 2:
        return float("inf")
    best = float("inf")
    for i in ids:
        others = (lines > 0) & (lines != i)
        if not others.any():
            continue
        dt = nd.distance_transform_edt(~others)
        best = min(best, float(dt[lines == i].min()))
    return best


# physics render -------------------------------------------------------------------------------------------------

def render(r, seed, crushed=0, inclusions=False, debris=False):
    """CT (uint8) of a rasterized layout R (2D or 3D), with randomized papyrus, scan and noise settings drawn from
    SEED. Two plies per sheet, a fibre texture, gap debris, the crushed look where R['crushed'] is set, the crack and
    the air beyond an edge kept dark, inclusions and debris, then point spread, phase rim, noise and gain."""
    np = _np()
    nd = _ndi()
    rng = np.random.default_rng([int(seed), 104729])
    q = r["q"]
    shape = q.shape
    inside = np.isfinite(q)
    qq = np.where(inside, q, 0.0)
    ply_off = rng.uniform(0.35, 0.6)
    ply_w = rng.uniform(0.22, 0.42)
    gain_a = rng.uniform(0.75, 1.1)
    gain_b = rng.uniform(0.75, 1.1)
    prof = gain_a * np.exp(-((qq + ply_off) / ply_w) ** 2) + gain_b * np.exp(-((qq - ply_off) / ply_w) ** 2)
    prof = prof + rng.uniform(0.15, 0.55)              # the core between plies
    prof = prof / prof.max() if prof.max() > 0 else prof
    edge = np.clip((1 - np.abs(qq)) / rng.uniform(0.15, 0.35), 0, 1)
    dens = np.where(inside, prof * edge, 0.0)
    w = rng.normal(size=shape)
    fib = nd.gaussian_filter(w, rng.uniform(0.8, 1.6))
    fib /= fib.std() + 1e-9
    big = nd.gaussian_filter(rng.normal(size=shape), rng.uniform(6, 20))
    big /= big.std() + 1e-9
    dens = dens * np.clip(1 + rng.uniform(0.1, 0.35) * fib + rng.uniform(0.05, 0.2) * big, 0.2, 2.0)
    # gap debris and fill
    fill = rng.uniform(0.0, 0.18)
    blobs = nd.gaussian_filter(rng.normal(size=shape), rng.uniform(1.5, 4.0))
    blobs = np.clip(blobs / (blobs.std() + 1e-9) - rng.uniform(0.8, 2.0), 0, None)
    gapv = fill * np.clip(0.6 + 0.4 * big, 0, 2) + rng.uniform(0.0, 0.25) * blobs
    air = r["air"] | r["crack"]
    dens = np.where(inside, dens, np.where(air, 0.0, gapv))
    # crushed look: blur across sheets, lower local contrast, grain
    cr = r["crushed"].astype(bool) if crushed else np.zeros(shape, bool)
    if cr.any():
        sig = rng.uniform(1.2, 2.6)
        bl = nd.gaussian_filter(dens, sig)
        c = rng.uniform(0.55, 0.8)
        bl = bl.mean() + c * (bl - bl.mean()) + 0.08 * nd.gaussian_filter(rng.normal(size=shape), 0.7)
        soft = nd.gaussian_filter(cr.astype(float), 6) if cr.ndim else cr
        dens = dens * (1 - soft) + bl * soft
    if inclusions:
        n = int(rng.integers(1, 6))
        pts = (rng.random((n, len(shape))) * np.array(shape)).astype(int)
        spot = np.zeros(shape)
        spot[tuple(pts.T)] = rng.uniform(2, 5, n)
        dens = dens + nd.gaussian_filter(spot, rng.uniform(0.8, 2.0)) * 12
    if debris:
        spot = (rng.random(shape) < 0.0015) & air
        dens = dens + nd.gaussian_filter(spot.astype(float), 1.0) * rng.uniform(1, 4)
    v = dens
    psf = rng.uniform(0.5, 1.4)
    v = nd.gaussian_filter(v, psf)
    rim = rng.uniform(0.0, 1.2)
    if rim > 0:
        v = v + rim * (v - nd.gaussian_filter(v, rng.uniform(1.0, 3.0)))
    sd = rng.uniform(0.04, 0.16)
    w = rng.normal(size=shape)
    mixw = rng.dirichlet([1.0, 1.0, 1.0])
    ramp = w - nd.gaussian_filter(w, 1.0)
    corr = nd.gaussian_filter(w, 1.5)
    noise = mixw[0] * w + mixw[1] * ramp / (ramp.std() + 1e-9) + mixw[2] * corr / (corr.std() + 1e-9)
    v = v + sd * noise
    v = v * (1 + rng.uniform(0, 0.15) * big)
    lo_air = rng.uniform(20, 70)
    hi_sheet = rng.uniform(150, 230)
    out = lo_air + (hi_sheet - lo_air) * v
    if rng.random() < 0.3:
        g = rng.uniform(0.7, 1.4)
        out = 255 * (np.clip(out, 0, 255) / 255) ** g
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


# tiles ----------------------------------------------------------------------------------------------------------

def _pick_kind(rng, recipe):
    np = _np()
    names = [k for k in KINDS if recipe.get(k, 0) > 0]
    p = np.array([recipe[k] for k in names], float)
    return names[int(rng.choice(len(names), p=p / p.sum()))]


def tile(seed, k, size=256, recipe=None, side=0.3, extras=None):
    """Tile K of a run with SEED: its layout raster, physics CT and the Synthetic-Slices record fields."""
    np = _np()
    nd = _ndi()
    recipe = dict(RECIPE if recipe is None else recipe)
    for attempt in range(20):
        rng = np.random.default_rng([int(seed), int(k), attempt, 31337])
        kind = _pick_kind(rng, recipe)
        try:
            Z = max(size, 64)
            lay = Layout(kind, int(rng.integers(1 << 31)), size=(Z, size, size), extras=extras)
        except SimError:
            continue
        plane = "y" if rng.random() < side else "z"
        if plane == "z":
            origin = (rng.uniform(0, Z), 0, 0)
        else:
            origin = (0, rng.uniform(0.2, 0.8) * size, 0)
        r = raster(lay, plane, origin, (size, size))
        if (r["lines"] > 0).sum() < 0.004 * size * size:
            continue
        if kind != "spiral" and line_separation(r["lines"]) < LINE_SEP_MIN - 1e-6:
            continue
        img = render(r, int(rng.integers(1 << 31)), crushed=lay.crushed, inclusions=lay.inclusions,
                     debris=lay.debris)
        ln = r["lines"] > 0
        if kind == "spiral":
            # one sheet rolled: winding ids jump at the branch cut, so give each connected line piece its own id
            lab, _ = nd.label(ln, np.ones((3, 3)))
            r["lines"] = lab.astype(np.uint16)
        d = nd.distance_transform_edt(~ln)
        return {"image": img, "lines": ln.astype(np.uint8), "sheet_id": r["lines"],
                "dist": np.clip(np.round(d), 0, DIST_CLIP).astype(np.uint8),
                "dist_cond": (np.clip(np.round(d * 4), 0, 255) / 4).astype(np.float32),
                "crack": r["crack"].astype(np.uint8), "air": r["air"], "crushed": int(lay.crushed),
                "crushed_mask": r["crushed"], "zone": r["zone"], "kind": kind_name(lay), "plane": plane,
                "guidance": 1.0 if kind in ("plain", "spiral") else 1.6, "layout": lay.describe()}
    raise SimError(f"tile {k}: no valid layout after 20 tries")


def tiles(n, seed, size=256, recipe=None, side=0.3, k0=0, progress=None):
    """N tiles as one shard dict of stacked arrays (Synthetic-Slices keys plus air, plane and layout JSON)."""
    np = _np()
    recs = []
    t0 = time.time()
    for k in range(k0, k0 + n):
        recs.append(tile(seed, k, size, recipe, side))
        if progress and (k - k0 + 1) % 50 == 0:
            progress(f"PROGRESS {k - k0 + 1}/{n} tiles, {time.time() - t0:.0f} s")
    out = {key: np.stack([r[key] for r in recs]) for key in ("image", "lines", "sheet_id", "dist", "crack", "air",
                                                             "crushed_mask", "zone")}
    out["crushed"] = np.array([r["crushed"] for r in recs], np.uint8)
    out["kind"] = np.array([r["kind"] for r in recs])
    out["plane"] = np.array([r["plane"] for r in recs])
    out["guidance"] = np.array([r["guidance"] for r in recs], np.float32)
    out["layout"] = np.array([json.dumps(r["layout"]) for r in recs])
    return out


def volume(kind, seed, shape=(64, 256, 256), extras=None):
    """A 3D block of one layout: raster plus physics CT."""
    lay = Layout(kind, seed, size=shape, extras=extras)
    r = raster(lay, "vol", (0, 0, 0), shape)
    ct = render(r, seed, crushed=lay.crushed, inclusions=lay.inclusions, debris=lay.debris)
    return lay, r, ct


def build_parser(ap):
    """The arguments of `python -m kit hardcases` on AP (kit.cli defers here)."""
    sub = ap.add_subparsers(dest="hardcases_cmd", required=True)
    t = sub.add_parser("tiles", help="training tiles with exact lines, Synthetic-Slices shard format")
    t.add_argument("out")
    t.add_argument("--n", type=int, default=100)
    t.add_argument("--seed", type=int, default=1)
    t.add_argument("--size", type=int, default=256)
    t.add_argument("--side", type=float, default=0.3, help="share of side (z, x) slices")
    t.add_argument("--kinds", default="", help="comma list: use these kinds with equal shares")
    t.add_argument("--k0", type=int, default=0)
    v = sub.add_parser("volume", help="one 3D block of a layout with its CT")
    v.add_argument("out")
    v.add_argument("--kind", default="hairpin", choices=KINDS)
    v.add_argument("--seed", type=int, default=1)
    v.add_argument("--shape", default="64,256,256")
    sub.add_parser("info", help="kinds, recipe and scale")
    return ap


def cmd_hardcases(a):
    """Run one parsed `kit hardcases` command; exit code 0 written, 2 refused."""
    np = _np()
    try:
        if a.hardcases_cmd == "info":
            print(json.dumps({"kinds": KINDS, "recipe": RECIPE, "extras": EXTRAS, "voxel_um": VOXEL_UM,
                              "pitch_p50": PITCH_P50}, indent=1))
            return 0
        if a.hardcases_cmd == "tiles":
            rec = None
            if a.kinds:
                ks = [s.strip() for s in a.kinds.split(",") if s.strip()]
                bad = [s for s in ks if s not in KINDS]
                if bad:
                    raise SimError(f"unknown kinds {bad}")
                rec = {s: 1.0 for s in ks}
            sh = tiles(a.n, a.seed, a.size, rec, a.side, a.k0, progress=print)
            np.savez_compressed(a.out, **sh)
            print(json.dumps({"out": a.out, "n": a.n, "kinds": {k: int((sh["kind"] == k).sum())
                                                                 for k in sorted(set(sh["kind"].tolist()))}}))
            return 0
        if a.hardcases_cmd == "volume":
            shape = tuple(int(s) for s in a.shape.split(","))
            lay, r, ct = volume(a.kind, a.seed, shape)
            np.savez_compressed(a.out, ct=ct, sheet=r["sheet"], lines=r["lines"], air=r["air"], crack=r["crack"],
                                zone=r["zone"])
            print(json.dumps(lay.describe()))
            return 0
    except SimError as e:
        print(f"kit hardcases: {e}", file=sys.stderr)
        return 2
    return 0




def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit hardcases", description=__doc__.split("\n")[0])
    return cmd_hardcases(build_parser(ap).parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
