"""The procedural hero scenes, one per released tool, built for scene.render().

Every scene is generated from formulas and a seed: no scan, map, model output, lettering or ink. Each builder takes
(params, width, height, seed) and returns a scene.Scene. Recipes in scripts/media/recipes/ name a builder and may
override its params.

The compositions follow the reference hero (docs/assets/README.md): a low camera, one subject running on a
left-to-right diagonal through most of the frame height and cropped at the left edge, the ivory key light from the
upper left and a copper rim, no text. Scroll cross-sections are spirals with a start and an end (scroll_section), never
concentric rings.
"""

import math

import numpy as np

from scene import (L_CHARCOAL, L_COPPER, L_EMBER, L_IVORY, Camera, Scene, Surface, copper_metal, fbm, grid_lines,
                   normalize, papyrus, ragged, ridges, smoothstep, to_linear, tube, value_noise)

SCENES = {}


def scene(fn):
    SCENES[fn.__name__.removeprefix("build_")] = fn
    return fn


def build(name, params, width, height, seed=0):
    if name not in SCENES:
        raise ValueError(f"no scene {name!r}; scenes: {', '.join(sorted(SCENES))}")
    return SCENES[name](dict(params or {}), width, height, seed)


def catmull(points):
    """A smooth curve t in [0, 1] -> (n, 3) through the given points (Catmull-Rom, clamped ends)."""
    pts = np.asarray(points, dtype=np.float32)
    pts = np.concatenate([2 * pts[:1] - pts[1:2], pts, 2 * pts[-1:] - pts[-2:-1]])
    nseg = len(pts) - 3

    def curve(t):
        t = np.clip(np.asarray(t, dtype=np.float32), 0, 1) * nseg
        i = np.minimum(np.floor(t).astype(int), nseg - 1)
        f = (t - i)[:, None]
        p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        return 0.5 * ((2 * p1) + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f
                      + (-p0 + 3 * p1 - 3 * p2 + p3) * f * f * f)

    return curve


def frame_from(axis):
    a = normalize(np.asarray(axis, dtype=np.float32))
    e1 = normalize(np.cross(a, np.array([0, 1, 0], dtype=np.float32)))
    if np.linalg.norm(e1) < 1e-3:
        e1 = np.array([1, 0, 0], dtype=np.float32)
    e2 = normalize(np.cross(e1, a))
    return a, e1, e2


def ring_noise(th, r, freq, rfreq, seed, octaves=3):
    """Noise around a circle that has no seam where the angle wraps from pi to -pi."""
    return fbm(np.cos(th) * freq + r * rfreq, np.sin(th) * freq - r * rfreq * 0.7, octaves, seed)


def scroll_section(x, y, seed, turns=8.0, r_in=0.07, r_out=0.9, thick=0.42, wobble=0.45, gaps=0.22, squash=0.8,
                   rot=0.0):
    """A synthetic scroll cross-section at (x, y) in disc units around the winding center at the origin.

    One sheet wound as an Archimedean spiral from r_in to r_out, squashed to an ellipse and wobbling, with its inner
    start and outer end visible, uneven thickness and a few delaminated gaps. Returns (sheet in [0, 1], turns along
    the spiral at the nearest sheet, the squashed radius, outer edge radius at this angle)."""
    c, s = math.cos(rot), math.sin(rot)
    xr, yr = x * c + y * s, (-x * s + y * c) / squash
    r, th = np.hypot(xr, yr), np.arctan2(yr, xr)
    pitch = (r_out - r_in) / turns
    w = wobble * pitch * (ring_noise(th, r, 1.1, 1.6, seed) - 0.5) * 2
    w = w + 0.9 * pitch * (ring_noise(th, r, 0.45, 0.6, seed + 3, 2) - 0.5)
    phase = (r - r_in + w) / pitch - th / (2 * np.pi)         # an integer at the middle of a sheet
    m = np.floor(phase + 0.5)
    along = m + th / (2 * np.pi)                              # turns from the inner start
    f = 1 - np.abs(phase - m) * 2                             # 1 at the middle of a sheet, 0 halfway to the next
    t = thick * (0.65 + 0.7 * ring_noise(th, m * 0.37, 0.9, 1.0, seed + 5, 2))
    sheet = smoothstep(1 - t, 1 - t * 0.45, f)
    sheet = sheet * (along >= 0.0) * (along <= turns - 0.2)
    if gaps:
        split = ring_noise(th, m * 0.13, 0.8, 1.0, seed + 9, 2)
        sheet = sheet * (0.12 + 0.88 * smoothstep(gaps - 0.03, gaps + 0.03, split))
    edge = r_in + pitch * (turns - 0.2 + th / (2 * np.pi) + 0.5) - w
    return sheet.astype(np.float32), along.astype(np.float32), r.astype(np.float32), edge.astype(np.float32)


def sheet_albedo(sheet, along, r, th, seed, tone=1.0):
    """Albedo of a cut scroll: warm gray-brown sheets with fibers along the spiral and dark gaps between them."""
    fib = ridges(along * 3.0 + 0.1 * np.cos(th), th * 9.0 + r * 40, 2, seed + 17, 2.0)
    mott = fbm(np.cos(th) * 3 + r * 6, np.sin(th) * 3 - r * 4, 4, seed + 19)
    lite = (0.55 + 0.35 * fib + 0.25 * (mott - 0.5)) * tone
    col = to_linear(np.array([0.62, 0.55, 0.47], dtype=np.float32)) * 0.75
    gap = L_CHARCOAL * 0.12
    return gap[None, :] * (1 - sheet[:, None]) + col[None, :] * (lite * sheet)[:, None]


def oriented(center, yaw=0.0, pitch=0.0, scale=1.0, roll=0.0):
    """A function local (n, 3) -> world (n, 3): scale, roll about z, pitch about x, yaw about y, move to center."""
    c = np.asarray(center, dtype=np.float32)
    ya, pa, ra = math.radians(yaw), math.radians(pitch), math.radians(roll)
    ry = np.array([[math.cos(ya), 0, math.sin(ya)], [0, 1, 0], [-math.sin(ya), 0, math.cos(ya)]], dtype=np.float32)
    rx = np.array([[1, 0, 0], [0, math.cos(pa), -math.sin(pa)], [0, math.sin(pa), math.cos(pa)]], dtype=np.float32)
    rz = np.array([[math.cos(ra), -math.sin(ra), 0], [math.sin(ra), math.cos(ra), 0], [0, 0, 1]], dtype=np.float32)
    m = (ry @ rx @ rz) * scale

    def f(p):
        return p @ m.T + c

    return f


def segment(a, b):
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    return lambda t: a[None, :] + (b - a)[None, :] * np.asarray(t, dtype=np.float32)[:, None]


# ---------------------------------------------------------------------------------------------------------------------
# The umbilicus finder: cross-sections of one synthetic scroll with a copper thread through each winding center.


@scene
def build_umbilicus(p, W, H, seed):
    """Synthetic cross-sections of one scroll, cap to base, on a diagonal. Each disc's winding center sits off its
    middle, and the copper thread bends through those centers the way a predicted center line drifts."""
    n = p.get("discs", 6)
    R = p.get("radius", 1.0)
    start = np.array(p.get("start", [-2.9, 1.12, 1.4]), dtype=np.float32)
    end = np.array(p.get("end", [6.8, 1.12, -6.6]), dtype=np.float32)
    axis = normalize(end - start)
    _, e1, e2 = frame_from(axis)
    rng = np.random.default_rng(seed)
    centers, winding = [], []
    for k in range(n):
        t = k / (n - 1)
        c = start + (end - start) * t
        off = R * np.array([0.17 * math.sin(2.3 * t * math.pi + 0.5) + rng.normal(0, 0.015),
                            0.13 * math.cos(1.6 * t * math.pi + 0.2) + rng.normal(0, 0.015)], dtype=np.float32)
        centers.append(c)
        winding.append((off, c + off[0] * e1 + off[1] * e2))
    pts = np.array([w for _, w in winding])
    thread = catmull(np.concatenate([pts[:1] - (pts[1] - pts[0]) * 0.9, pts, pts[-1:] + (pts[-1] - pts[-2]) * 1.4]))
    surfaces = []
    for k in range(n):
        c = centers[k]
        off = winding[k][0]
        sd = seed + 31 * k
        rot = 0.7 * k + 0.4
        squash = 0.78 + 0.05 * (k % 3)
        turns = p.get("turns", 8.5)

        def local(u, v, off=off):
            th = v * 2 * np.pi
            r = u * R * 1.25
            return r * np.cos(th) - off[0] / R * R, r * np.sin(th) - off[1] / R * R, th, r

        def pos(u, v, c=c, off=off):
            x, y, _, _ = local(u, v)
            x, y = x + off[0], y + off[1]
            return c + x[:, None] * e1 + y[:, None] * e2

        def mat(u, v, P, N, sd=sd, rot=rot, squash=squash, turns=turns):
            x, y, _, _ = local(u, v)
            sheet, along, r, edge = scroll_section(x / R, y / R, sd, turns=turns, rot=rot, squash=squash, thick=0.5,
                                                   wobble=0.6)
            keep = r < edge + 0.02
            th = np.arctan2(y, x)
            alb = sheet_albedo(sheet, along, r, th, sd, tone=1.25)
            glow = smoothstep(0.075, 0.0, np.hypot(x, y) / R)
            emit = (L_COPPER * 2.2)[None, :] * glow[:, None]
            kk = len(u)
            return {"albedo": alb, "emit": emit, "keep": keep, "metal": np.zeros(kk, np.float32),
                    "shine": np.full(kk, 22.0, np.float32), "spec": 0.08 + 0.25 * sheet,
                    "rim": 0.6 + 0.6 * sheet}

        surfaces.append(Surface(pos, mat, tiles=(28, 72), density=0.75))

        def bpos(u, v, c=c, off=off):
            x, y, _, _ = local(u, v)
            return c + (x + off[0])[:, None] * e1 + (y + off[1])[:, None] * e2 + 0.035 * axis

        def bmat(u, v, P, N, sd=sd, rot=rot, squash=squash, turns=turns):
            x, y, _, _ = local(u, v)
            _, _, r, edge = scroll_section(x / R, y / R, sd, turns=turns, rot=rot, squash=squash, thick=0.5,
                                           wobble=0.6)
            kk = len(u)
            return {"albedo": np.broadcast_to(L_EMBER * 0.35, (kk, 3)), "keep": r < edge + 0.01,
                    "metal": np.zeros(kk, np.float32), "shine": np.full(kk, 12.0, np.float32),
                    "spec": np.full(kk, 0.1, np.float32), "rim": np.full(kk, 1.4, np.float32)}

        surfaces.append(Surface(bpos, bmat, tiles=(20, 48), density=0.9))
    surfaces.append(tube(thread, 0.017, copper_metal(glow=1.3), shadow=False))
    cam = Camera(p.get("eye", [-6.4, 1.55, 6.6]), p.get("target", [1.6, 0.95, -2.6]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(centers[1] - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -9), (9, 3, 4)), dof=p.get("dof", 0.08), bloom=0.4, fog=0.012,
                 spot=((-2.2, 1.0, 0.6), 6.5), key_power=p.get("key_power", 3.4))


# ---------------------------------------------------------------------------------------------------------------------
# A sheet that rolls up at one end: shared by Unroll, the reader and the workbench scenes.


def roll_profile(turns=4.5, r_in=0.18, r_out=0.62, run=6.0, wave=0.05, wobble=0.0, n=24000, seed=0):
    """The 2D cross-section of a rolled sheet that unrolls the way a rug does: the outer turn leaves the bottom of
    the roll and the sheet runs flat along +x under the light. Returns (s, xy, s_roll, s_flat): arc length samples,
    (n, 2) points, and where the roll ends (the same place the flat run starts); the roll rests on y = 0 at x = 0.
    wobble loosens the turns unevenly, so the end reads as a spiral of real sheets rather than rings."""
    cy = r_out + 0.006
    big = 2 * np.pi * turns
    th = np.linspace(0, big, n // 2)
    r = r_in + (r_out - r_in) * th / big
    if wobble:
        pitch = (r_out - r_in) / turns
        r = r + wobble * pitch * (np.sin(th * 0.5 + seed) * 0.6 + np.sin(th * 1.0 + 1.7 * seed) * 0.4) \
            * np.clip(th / (2 * np.pi), 0, 1) * np.clip((big - th) / np.pi, 0, 1)
    alpha = -np.pi / 2 - (big - th)                    # winds so that the outer end heads along +x at the bottom
    spiral = np.stack([r * np.cos(alpha), cy + r * np.sin(alpha) * 0.97], axis=1)
    spiral[:, 1] -= spiral[-1, 1] - 0.006
    xs = np.linspace(0.0, run, n // 2)[1:] + spiral[-1, 0]
    ys = 0.006 + wave * np.sin((xs - xs[0]) * 2.1) ** 2 * np.exp(-(xs - xs[0]) / (run * 0.6))
    flat = np.stack([xs, ys], axis=1)
    xy = np.concatenate([spiral, flat])
    seg = np.hypot(*np.diff(xy, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    s_end = float(s[len(spiral) - 1])
    return s.astype(np.float32), xy.astype(np.float32), s_end, s_end


def profile_sheet(s, xy, width, place, material, s_range=None, tiles=(160, 24), **kw):
    """A Surface following the profile (s, xy) across `width` along z, moved by place(p) -> p."""
    S = s[-1]
    lo, hi = s_range or (0.0, float(S))

    def pos(u, v):
        ss = lo + u * (hi - lo)
        x = np.interp(ss, s, xy[:, 0])
        y = np.interp(ss, s, xy[:, 1])
        z = (v - 0.5) * width
        return place(np.stack([x, y, z], axis=1).astype(np.float32))

    return Surface(pos, material, tiles=tiles, **kw)


def placer(rot_deg=0.0, offset=(0, 0, 0)):
    c, s_ = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    off = np.asarray(offset, dtype=np.float32)

    def place(p):
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        return np.stack([c * x + s_ * z, y, -s_ * x + c * z], axis=1) + off

    return place


def papyrus_material(S, width, seed, edge=0.02, char=0.2, tone=1.0, s_range=None, extra=None, bump=0.0009, scale=0.45):
    lo, hi = s_range or (0.0, S)

    def mat(u, v, P, N):
        ss = lo + u * (hi - lo)
        zz = v * width
        alb, height = papyrus(ss, zz, seed, scale=scale, tone=tone, char=char)
        keep = ragged(ss / S, v, amount=edge, seed=seed, freq=40.0)
        k = len(u)
        out = {"albedo": alb, "bump": height * bump, "keep": keep, "metal": np.zeros(k, np.float32),
               "shine": np.full(k, 14.0, np.float32), "spec": np.full(k, 0.14, np.float32),
               "rim": np.full(k, 1.1, np.float32)}
        if extra:
            out = extra(u, v, ss, zz, out)
        return out

    def bump_fn(u, v):
        return papyrus(lo + u * (hi - lo), v * width, seed, scale=scale, detail=False) * bump

    mat.bump_fn = bump_fn
    return mat


@scene
def build_unroll(p, W, H, seed):
    """A roll whose outer sheet unrolls flat along a diagonal, and over the flat run two layers peel up from it and
    float: a copper surface grid and a fine scatter of ivory points, as a viewer stacks its layers."""
    width = p.get("width", 2.4)
    s, xy, s_roll, s_flat = roll_profile(turns=p.get("turns", 9.0), r_in=0.14, r_out=0.74, run=p.get("run", 9.0),
                                         wobble=0.35, seed=seed)
    S = float(s[-1])
    place = placer(p.get("rot", -14.0), (-3.0, 0, 0.9))
    surfaces = [profile_sheet(s, xy, width, place, papyrus_material(S, width, seed, edge=0.008, char=0.4, tone=1.6),
                              tiles=(300, 28), bump_scale=1.0, density=0.7)]
    x0 = float(np.interp(s_flat, s, xy[:, 0])) + 1.3
    x1 = float(xy[-1, 0]) - 0.4
    tilt = math.radians(p.get("layer_tilt", 10.0))
    for li, (h, kind) in enumerate(((0.5, "grid"), (0.98, "points"))):
        def pos(u, v, h=h, li=li):
            x = x0 + 0.25 * li + u * (x1 - x0 - 0.25 * li)
            z = (v - 0.5) * width * 0.96
            lift = smoothstep(0.0, 0.22, u)                     # each layer peels up from the sheet at its left end
            y = 0.02 + (h - 0.02) * lift - z * math.tan(tilt) * lift + 0.05 * np.sin(u * 4.5 + li) * lift
            return place(np.stack([x, y, z], axis=1).astype(np.float32))

        if kind == "grid":
            def mat(u, v, P, N):
                lines = grid_lines(u * (x1 - x0), v * width, 1 / 0.2, 1 / 0.2, 0.035)
                fade = smoothstep(0.0, 0.12, u) * smoothstep(1.0, 0.82, u)
                keep = lines & (fbm(u * 9, v * 9, 2, seed + 3) < 0.35 + 0.65 * fade)
                k = len(u)
                return {"albedo": np.broadcast_to(L_COPPER * 1.1, (k, 3)), "keep": keep,
                        "metal": np.ones(k, np.float32), "shine": np.full(k, 50.0, np.float32),
                        "spec": np.full(k, 0.9, np.float32), "emit": (L_COPPER * 0.4)[None, :] * fade[:, None],
                        "rim": np.full(k, 1.5, np.float32)}
        else:
            def mat(u, v, P, N):
                field = fbm(u * 3.2, v * 2.4, 4, seed + 11)
                gu, gv = u * (x1 - x0) / 0.06, v * width / 0.06
                jit = value_noise(np.floor(gu), np.floor(gv), seed + 13)
                d = np.hypot((gu % 1.0) - 0.5 - 0.25 * (jit - 0.5), (gv % 1.0) - 0.5 + 0.25 * (jit - 0.5))
                fade = smoothstep(0.05, 0.3, u) * smoothstep(1.0, 0.7, u) * smoothstep(0.0, 0.15, v) \
                    * smoothstep(1.0, 0.85, v)
                size = (0.05 + 0.13 * smoothstep(0.4, 0.75, field)) * fade
                keep = d < size
                k = len(u)
                glow = (0.3 + 0.7 * smoothstep(0.4, 0.75, field)) * fade
                return {"albedo": np.broadcast_to(L_IVORY * 0.35, (k, 3)), "keep": keep,
                        "metal": np.zeros(k, np.float32), "shine": np.full(k, 20.0, np.float32),
                        "spec": np.full(k, 0.3, np.float32), "emit": (L_IVORY * 0.9)[None, :] * glow[:, None],
                        "rim": np.zeros(k, np.float32)}
        surfaces.append(Surface(pos, mat, tiles=(72, 24), density=0.6, cast=li == 0, shadow=False))
    cam = Camera(p.get("eye", [-2.6, 2.1, 7.6]), p.get("target", [1.7, 0.25, -0.4]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(np.array([-2.6, 0.7, 0.9]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -4), (7, 2, 4)), dof=p.get("dof", 0.08), bloom=0.4, fog=0.01,
                 spot=((-2.4, 1.0, 1.0), 6.0), key_power=p.get("key_power", 3.6),
                 key=tuple(p.get("key", (-0.36, 0.8, 0.7))))


# ---------------------------------------------------------------------------------------------------------------------
# Parts that several scenes share.


def palette_ramp(t):
    """Map t in [0, 1] through charcoal, ember, copper and ivory (linear RGB)."""
    stops = np.array([0.0, 0.35, 0.72, 1.0], dtype=np.float32)
    cols = np.stack([L_CHARCOAL * 0.6, L_EMBER, L_COPPER, L_IVORY])
    t = np.clip(t, 0, 1)
    return np.stack([np.interp(t, stops, cols[:, k]) for k in range(3)], axis=-1).astype(np.float32)


def cube_part(to_world, seed, size=1.0, detail=1.0, edge_glow=0.3, slices=("sheets", "embed", "speckle")):
    """A cube of edge 2 * size with three orthogonal slices through its center, each with a synthetic field (curved
    papyrus layers of a scroll, embedding-like patches and a sparse speckle), and copper edges."""
    out = []
    axes = [(0, 1, 2), (0, 2, 1), (2, 1, 0)]          # (in-plane a, in-plane b, normal)
    for kind, (ia, ib, inormal) in zip(slices, axes):
        def pos(u, v, ia=ia, ib=ib, inormal=inormal):
            loc = np.zeros((len(u), 3), dtype=np.float32)
            loc[:, ia] = (u * 2 - 1) * size
            loc[:, ib] = (v * 2 - 1) * size
            return to_world(loc)

        def mat(u, v, P, N, kind=kind):
            k = len(u)
            x, y = u * 2 - 1, v * 2 - 1
            if kind == "sheets":
                # part of a scroll's winding: curved layers around a center outside the cube
                cx, cy = -1.9, -1.4
                r = np.hypot(x - cx, (y - cy) * 1.15)
                th = np.arctan2(y - cy, x - cx)
                w = 0.05 * (fbm(np.cos(th) * 2 + r, np.sin(th) * 2, 3, seed) - 0.5)
                ph = (r + w) / 0.17
                f = 1 - np.abs((ph % 1.0) - 0.5) * 2
                sheet = smoothstep(0.5, 0.78, f) * (0.25 + 0.75 * smoothstep(0.25, 0.4, fbm(th * 6, ph * 0.3, 2,
                                                                                                 seed + 4)))
                fib = ridges(ph * 0.6, th * 30, 2, seed + 6, 2.0)
                col = to_linear(np.array([0.62, 0.55, 0.47], dtype=np.float32)) * 0.7
                alb = (L_CHARCOAL * 0.15)[None, :] + col[None, :] * (sheet * (0.6 + 0.4 * fib))[:, None]
                emit = (L_IVORY * 0.05)[None, :] * sheet[:, None]
            elif kind == "embed":
                t = fbm(x * 1.6 + 4, y * 1.6, 4, seed + 7)
                t = np.round(t * 7) / 7                                   # patches, like an embedding's colors
                alb = palette_ramp(0.15 + 1.0 * (t - 0.3) / 0.45) * 0.6
                emit = alb * 0.18
            else:
                base = fbm(x * 2, y * 2, 3, seed + 9)
                speck = value_noise(x * 60, y * 60, seed + 11) * smoothstep(0.5, 0.75, base)
                hot = smoothstep(0.55, 0.85, speck)
                alb = (L_CHARCOAL * 0.25)[None, :] + (L_COPPER * 0.5)[None, :] * hot[:, None]
                emit = (L_COPPER * 1.0)[None, :] * hot[:, None] ** 2
            return {"albedo": alb, "emit": emit, "metal": np.zeros(k, np.float32), "shine": np.full(k, 30.0, np.float32),
                    "spec": np.full(k, 0.25, np.float32), "rim": np.full(k, 0.6, np.float32)}

        out.append(Surface(pos, mat, tiles=(int(32 * detail) + 4, int(32 * detail) + 4), density=0.75))
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=np.float32) * size
    for i in range(8):
        for j in range(i + 1, 8):
            if np.sum(corners[i] != corners[j]) == 1:
                a, b = to_world(corners[i:i + 1])[0], to_world(corners[j:j + 1])[0]
                out.append(tube(segment(a, b), 0.009 * size + 0.003, copper_metal(glow=edge_glow), shadow=False))
    return out


@scene
def build_lens(p, W, H, seed):
    """A floating cube cut by three slices (curved papyrus layers, embedding-like patches and a sparse speckle) with a
    cloud of matched points along a curved sheet, and smaller cubes receding to the right."""
    surfaces = []
    center = p.get("center", [-0.9, 1.3, 0.6])
    main = oriented(center, yaw=p.get("yaw", 30), pitch=6, scale=1.0)
    surfaces += cube_part(main, seed, size=1.0, detail=1.6, edge_glow=0.25)

    def spos(u, v):
        x = (u * 2 - 1) * 0.92
        z = (v * 2 - 1) * 0.92
        y = 0.3 * np.sin(x * 1.8 + 0.4) * np.cos(z * 1.2) + 0.28
        return main(np.stack([x, y, z], axis=1).astype(np.float32))

    def smat(u, v, P, N):
        g = np.hypot((u * 46) % 1.0 - 0.5, (v * 46) % 1.0 - 0.5)
        sel = fbm(u * 4, v * 4, 3, seed + 21)
        keep = (g < 0.2) & (sel > 0.45)
        k = len(u)
        hot = smoothstep(0.45, 0.7, sel)
        return {"albedo": np.broadcast_to(L_IVORY * 0.5, (k, 3)), "keep": keep, "metal": np.zeros(k, np.float32),
                "shine": np.full(k, 30.0, np.float32), "spec": np.full(k, 0.2, np.float32),
                "emit": (L_IVORY * 1.3)[None, :] * hot[:, None] + (L_COPPER * 0.5)[None, :] * (1 - hot)[:, None],
                "rim": np.zeros(k, np.float32)}

    surfaces.append(Surface(spos, smat, tiles=(48, 48), density=0.6, shadow=False))
    for i, (cx, cz, s_) in enumerate(((2.0, -0.7, 0.6), (3.7, -1.9, 0.52), (5.3, -3.1, 0.46), (6.8, -4.3, 0.42),
                                      (8.2, -5.5, 0.38))):
        f = oriented([cx, 0.68 + s_ * 1.15, cz], yaw=22 + 15 * i, pitch=5, scale=1.0)
        surfaces += cube_part(f, seed + 50 * (i + 1), size=s_, detail=0.7, edge_glow=0.2)
    cam = Camera(p.get("eye", [-3.9, 2.2, 8.4]), p.get("target", [1.6, 0.95, -0.9]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(np.array(center) - cam.eye))
    return Scene(cam, surfaces, bounds=((-4, 0, -7), (9, 3, 3)), dof=p.get("dof", 0.1), bloom=0.4, fog=0.012,
                 spot=((-0.8, 1.4, 0.6), 6.5), key_power=p.get("key_power", 3.4))


# ---------------------------------------------------------------------------------------------------------------------
# The Scroll Text Reader: a sheet under a copper lens. No lettering, no ink, no boxes: a reading is never shown.


@scene
def build_reader(p, W, H, seed):
    """A papyrus sheet curling up at its left end, and a copper reading lens hovering over the flat part that shows
    the sheet's fibers magnified. Nothing is written on the sheet: no letters, no ink, no boxes."""
    width = p.get("width", 2.3)
    s, xy, s_roll, s_flat = roll_profile(turns=3.0, r_in=0.28, r_out=0.55, run=p.get("run", 8.5), wave=0.03,
                                         wobble=0.3, seed=seed)
    S = float(s[-1])
    place = placer(p.get("rot", -13.0), (-3.2, 0, 0.6))
    tone = 1.5
    surfaces = [profile_sheet(s, xy, width, place, papyrus_material(S, width, seed, edge=0.008, char=0.35, tone=tone),
                              tiles=(380, 36), bump_scale=1.0, density=0.65)]
    x_flat0 = float(np.interp(s_flat, s, xy[:, 0]))
    lc = np.array(p.get("lens_at", [x_flat0 + 2.1, 0.0]), dtype=np.float32)    # (x, z) on the sheet, local
    lr, lh = p.get("lens_radius", 0.62), p.get("lens_height", 0.42)
    lens_tilt = math.radians(p.get("lens_tilt", 18.0))
    mag = p.get("magnify", 2.2)

    def lens_point(rr, th, lift=0.0):
        x, z = lc[0] + rr * np.cos(th), lc[1] + rr * np.sin(th)
        y = lh + lift - (z - lc[1]) * math.tan(lens_tilt)
        return place(np.stack([x, y, z], axis=1).astype(np.float32))

    def gpos(u, v):
        return lens_point(u * lr, v * 2 * np.pi, 0.012 * (1 - u * u))

    def gmat(u, v, P, N):
        rr, th = u * lr, v * 2 * np.pi
        # the sheet point under the lens, magnified about the lens center
        xm, zm = lc[0] + rr * np.cos(th) / mag, lc[1] + rr * np.sin(th) / mag
        ss = s_flat + (xm - x_flat0)
        alb, _ = papyrus(ss, zm + width / 2, seed, scale=0.45, tone=tone * 0.9, char=0.1)
        edge = smoothstep(0.86, 1.0, u)
        k = len(u)
        return {"albedo": alb * (1 - edge[:, None]) * 0.35, "emit": alb * (1 - edge[:, None]) * 1.6,
                "metal": np.zeros(k, np.float32), "shine": np.full(k, 90.0, np.float32),
                "spec": np.full(k, 0.9, np.float32), "rim": np.full(k, 0.3, np.float32)}

    surfaces.append(Surface(gpos, gmat, tiles=(24, 64), density=0.6, cast=False, shadow=False))
    ring = lambda t: lens_point(np.full_like(np.asarray(t, dtype=np.float32), lr), np.asarray(t) * 2 * np.pi, 0.0)
    surfaces.append(tube(ring, 0.028, copper_metal(glow=0.5), n=(800, 24), shadow=False))
    h0 = lens_point(np.array([lr + 0.02], np.float32), np.array([0.35 * np.pi], np.float32))[0]
    h1 = lens_point(np.array([lr + 0.95], np.float32), np.array([0.35 * np.pi], np.float32), 0.25)[0]
    surfaces.append(tube(segment(h0, h1), 0.034, copper_metal(glow=0.25), shadow=False))
    cam = Camera(p.get("eye", [-2.4, 2.0, 6.4]), p.get("target", [1.2, 0.05, -0.5]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(lens_point(np.array([0.0], np.float32), np.array([0.0], np.float32))[0]
                                     - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -4), (7, 2, 4)), dof=p.get("dof", 0.08), bloom=0.35, fog=0.01,
                 spot=((-1.0, 0.5, 0.6), 5.5), key_power=p.get("key_power", 3.4))


# ---------------------------------------------------------------------------------------------------------------------
# Segment stack check: consecutive segments of one spiral, standing, with a missing sector and a touching pair.


@scene
def build_stackcheck(p, W, H, seed):
    """One scroll's winding as a standing spiral strip cut into consecutive segments around a copper center post,
    with faint rays from the center along the floor. One segment misses a sector (its torn edges glow ivory) and two
    neighboring windings touch (a copper glow where they meet)."""
    turns = p.get("turns", 5.6)
    r0, pitch = 0.32, p.get("pitch", 0.34)
    center = np.array(p.get("center", [0.0, 0.0, -0.4]), dtype=np.float32)
    hgt = p.get("height", 0.62)
    seg_turns = 0.92
    gap_seg, gap = 3, (math.radians(40), math.radians(115))
    touch_turn, touch_at = 4.15, math.radians(205)
    span = 2 * np.pi * turns

    def radius(T):
        th = T * 2 * np.pi
        r = r0 + pitch * T + 0.035 * np.sin(th * 2 + 0.7) + 0.03 * (fbm(np.cos(th) * 1.5 + T * 0.3, np.sin(th) * 1.5,
                                                                         2, seed) - 0.5)
        # the touching pair: the outer winding bows in to meet the one inside it
        d = np.angle(np.exp(1j * (th - touch_at)))
        near = np.exp(-((T - touch_turn) / 0.5) ** 2) * np.exp(-(d / 0.30) ** 2)
        return r - (pitch - 0.035) * near

    def pos(u, v):
        T = u * turns
        th = T * 2 * np.pi
        r = radius(T)
        return np.stack([center[0] + r * np.cos(th), v * hgt, center[2] + r * np.sin(th)], axis=1).astype(np.float32)

    def mat(u, v, P, N):
        T = u * turns
        th = T * 2 * np.pi
        k_seg = np.floor(T / seg_turns)
        local = T / seg_turns - k_seg
        alb, height = papyrus(T * 2 * np.pi * (r0 + pitch * T) * 0.5, v * hgt, seed + 3, tone=1.3)
        alb = alb * (1.0 + 0.18 * (k_seg % 2))[:, None]
        kk = len(u)
        keep = ragged(local, v, amount=0.006, seed=seed + 5, freq=26.0)
        ang = np.mod(th, 2 * np.pi)
        emit = np.zeros((kk, 3), np.float32)
        in_gap_seg = k_seg == gap_seg
        inside = in_gap_seg & (ang > gap[0]) & (ang < gap[1])
        keep = keep & ~inside
        near_gap = np.minimum(np.abs(ang - gap[0]), np.abs(ang - gap[1]))
        emit = emit + (L_IVORY * 2.6)[None, :] * (smoothstep(0.14, 0.0, near_gap) * in_gap_seg)[:, None]
        d = np.abs(np.angle(np.exp(1j * (th - touch_at))))
        touching = smoothstep(0.32, 0.0, d) * (np.abs(T - touch_turn + 0.5) < 0.9)
        emit = emit + (L_COPPER * 3.2)[None, :] * touching[:, None]
        return {"albedo": alb, "bump": height * 0.0009, "keep": keep, "metal": np.zeros(kk, np.float32),
                "shine": np.full(kk, 14.0, np.float32), "spec": np.full(kk, 0.14, np.float32), "emit": emit,
                "rim": np.full(kk, 1.1, np.float32)}

    surfaces = [Surface(pos, mat, u=(0.0, 1.0), tiles=(360, 10), density=0.7, bump_scale=1.0)]
    for i in range(16):
        a = math.radians(i * 22.5 + 7)
        d = np.array([math.cos(a), 0, math.sin(a)], dtype=np.float32)

        def rpos(u, v, d=d):
            r = 0.15 + u * 3.4
            side = np.array([-d[2], 0, d[0]], dtype=np.float32)
            return (center[None, :] + d[None, :] * r[:, None] + side[None, :] * ((v - 0.5) * 0.01)[:, None]
                    + np.array([0, 0.003, 0], np.float32)).astype(np.float32)

        def rmat(u, v, P, N):
            k = len(u)
            f = smoothstep(1.0, 0.1, u) * 0.6
            return {"albedo": np.broadcast_to(L_COPPER * 0.4, (k, 3)), "metal": np.ones(k, np.float32),
                    "shine": np.full(k, 40.0, np.float32), "spec": np.full(k, 0.5, np.float32),
                    "emit": (L_COPPER * 0.35)[None, :] * f[:, None], "rim": np.zeros(k, np.float32)}

        surfaces.append(Surface(rpos, rmat, tiles=(64, 1), density=0.7, cast=False))
    surfaces.append(tube(segment(center, center + np.array([0, 1.0, 0], np.float32)), 0.024, copper_metal(glow=1.1),
                         shadow=False, up=(1, 0, 0)))
    cam = Camera(p.get("eye", [-2.2, 4.6, 6.2]), p.get("target", [0.95, -0.15, -0.7]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(center + np.array([0, 0.3, 0]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-3, 0, -3), (3, 1.5, 3)), dof=p.get("dof", 0.08), bloom=0.45, fog=0.008,
                 spot=((-0.6, 0.8, -0.2), 5.0), key_power=p.get("key_power", 4.4))


# ---------------------------------------------------------------------------------------------------------------------
# Inkfilter: a fixed filter down through a surface volume's layers, its response map and the reversed control.


@scene
def build_inkfilter(p, W, H, seed):
    """A surface volume as a tall stack of thin papyrus layers with a copper sampling column down through
    them, and two upright panels of equal size beside it on the diagonal: the filter's response, and the same filter
    run with the layers in reverse order, plainly dimmer. Synthetic fields only: no ink, no letters."""
    surfaces = []
    nl = p.get("layers", 7)
    gap_h = p.get("layer_gap", 0.3)
    base = np.array(p.get("stack_at", [-2.3, 0.22, 0.5]), dtype=np.float32)
    w_, d_ = 2.0, 1.5
    stack = oriented(base, yaw=-20)
    for i in range(nl):
        h = i * gap_h

        def pos(u, v, h=h):
            return stack(np.stack([(u - 0.5) * w_, np.full_like(u, h), (v - 0.5) * d_], axis=1).astype(np.float32))

        def mat(u, v, P, N, i=i):
            alb, height = papyrus(u * w_ + i * 0.37, v * d_ + i * 0.11, seed + i, scale=0.6, tone=0.75, char=0.3)
            k = len(u)
            keep = ragged(u, v, amount=0.01, seed=seed + i, freq=30.0)
            return {"albedo": alb, "keep": keep, "metal": np.zeros(k, np.float32),
                    "shine": np.full(k, 14.0, np.float32), "spec": np.full(k, 0.12, np.float32),
                    "rim": np.full(k, 1.0, np.float32)}

        surfaces.append(Surface(pos, mat, tiles=(40, 30), density=0.5, cast=i == nl - 1))
    col = stack(np.array([[0.22, 0.0, 0.08]], np.float32))[0]
    top_y = (nl - 1) * gap_h + 0.55
    surfaces.append(tube(segment(col - np.array([0, 0.2, 0], np.float32), col + np.array([0, top_y, 0], np.float32)),
                         0.026, copper_metal(glow=1.4), shadow=False, up=(1, 0, 0)))
    for i in range(nl):
        c = col + np.array([0, i * gap_h + 0.01, 0], np.float32)

        def rpos(u, v, c=c):
            th = u * 2 * np.pi
            r = 0.07 + 0.06 * v
            return (c[None, :] + np.stack([r * np.cos(th), np.zeros_like(u), r * np.sin(th)], axis=1)).astype(np.float32)

        surfaces.append(Surface(rpos, copper_metal(glow=1.6), tiles=(24, 2), density=0.7, shadow=False, cast=False))

    def response(u, v, reverse):
        # the filter's response to the layers' fibers: banded along the strips, strongest in a broad region
        fib = ridges(u * 1.2, v * 26, 2, seed + 81, 2.0)
        strip = fbm(u * 0.8, v * 6, 2, seed + 85)
        region = smoothstep(0.38, 0.66, fbm(u * 2.0 + 1, v * 1.6, 3, seed + 77))
        t = 0.18 + 0.42 * fib * (0.4 + 0.6 * region) + 0.35 * region + 0.1 * strip
        if reverse:
            t = 0.10 + 0.25 * fbm(u * 6, v * 6, 3, seed + 5) * (0.6 + 0.4 * fib)
        return np.clip(t, 0, 1)

    pw, ph = 1.7, 1.25
    for j, (center, rev) in enumerate((([0.55, 1.05, -0.5], False), ([2.75, 1.05, -1.75], True))):
        panel = oriented(center, yaw=-28 + 4 * j, pitch=-6)

        def mpos(u, v, panel=panel):
            return panel(np.stack([(u - 0.5) * pw, (0.5 - v) * ph, np.zeros_like(u)], axis=1).astype(np.float32))

        def mmat(u, v, P, N, rev=rev):
            t = response(u, v, rev)
            colr = palette_ramp(0.05 + 0.95 * t)
            edge = np.minimum(np.minimum(u, 1 - u) * pw / ph, np.minimum(v, 1 - v))
            frame = smoothstep(0.016, 0.0, edge)
            gl = 0.32 if rev else 1.0
            k = len(u)
            return {"albedo": colr * 0.3 * (1 - frame[:, None]) + L_COPPER * frame[:, None],
                    "emit": colr * 1.6 * gl * (1 - frame[:, None]) + (L_COPPER * 0.8 * gl)[None, :] * frame[:, None],
                    "metal": frame, "shine": np.full(k, 30.0, np.float32), "spec": 0.15 + 0.6 * frame,
                    "rim": np.full(k, 0.8, np.float32)}

        surfaces.append(Surface(mpos, mmat, tiles=(48, 36), density=0.6))
    top = col + np.array([0, top_y, 0], np.float32)
    link = catmull([top, top + np.array([0.8, 0.12, -0.2], np.float32),
                    np.array([0.55 - 0.78, 1.05 + 0.62, -0.5 + 0.3], np.float32)])
    surfaces.append(tube(link, 0.009, copper_metal(glow=1.4), shadow=False))
    cam = Camera(p.get("eye", [-4.0, 3.0, 7.6]), p.get("target", [0.4, 0.95, -0.9]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(base + np.array([0, 1.0, 0]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -4), (5, 3, 3)), dof=p.get("dof", 0.08), bloom=0.4, fog=0.01,
                 spot=((-1.8, 1.0, 0.4), 5.5), key_power=p.get("key_power", 3.4))


# ---------------------------------------------------------------------------------------------------------------------
# The workbench: one still life on a tray.


@scene
def build_workbench(p, W, H, seed):
    """A still life on one dark tray, seen from a low three-quarter angle: a cube with glowing slices in front, a
    small papyrus roll unrolling behind it, and two cut cross-sections on a copper thread overlapping at the back."""
    surfaces = []
    # the tray: a thin slab with a copper lip
    tw, td, th_ = 6.4, 3.2, 0.06
    tray = oriented([0.2, 0.0, -0.4], yaw=-12)

    def tpos(u, v):
        return tray(np.stack([(u - 0.5) * tw, np.full_like(u, th_), (v - 0.5) * td], axis=1).astype(np.float32))

    def tmat(u, v, P, N):
        k = len(u)
        grain = fbm(u * 40, v * 3, 3, seed + 2)
        return {"albedo": L_EMBER[None, :] * (0.30 + 0.12 * grain)[:, None],
                "metal": np.zeros(k, np.float32), "shine": np.full(k, 30.0, np.float32),
                "spec": np.full(k, 0.25, np.float32), "rim": np.full(k, 0.6, np.float32)}

    surfaces.append(Surface(tpos, tmat, tiles=(48, 24), density=0.8))
    for (a, b) in (((-0.5, -0.5), (0.5, -0.5)), ((0.5, -0.5), (0.5, 0.5)), ((0.5, 0.5), (-0.5, 0.5)),
                   ((-0.5, 0.5), (-0.5, -0.5))):
        pa = tray(np.array([[a[0] * tw, th_, a[1] * td]], np.float32))[0]
        pb = tray(np.array([[b[0] * tw, th_, b[1] * td]], np.float32))[0]
        surfaces.append(tube(segment(pa, pb), 0.018, copper_metal(glow=0.15), shadow=False))
    # the roll, at the back left, unrolling to the right behind the cube
    width = 1.0
    s, xy, s_roll, s_flat = roll_profile(turns=6.0, r_in=0.09, r_out=0.36, run=3.0, wave=0.02, wobble=0.35,
                                         seed=seed)
    S = float(s[-1])
    place = placer(-12, (-2.4, th_, -1.0))
    surfaces.append(profile_sheet(s, xy, width, place, papyrus_material(S, width, seed, edge=0.01, tone=1.2),
                                  tiles=(220, 16), bump_scale=1.0))
    # the cube, in front
    surfaces += cube_part(oriented([-0.2, th_ + 0.62, 0.35], yaw=28, pitch=0), seed + 5, size=0.6, detail=1.2,
                          edge_glow=0.3)
    # two cross-sections on a thread, at the back right
    pts = np.array([[1.25, th_ + 0.62, -0.75], [2.15, th_ + 0.60, -1.25], [3.05, th_ + 0.58, -1.75]], np.float32)
    thread = catmull(np.concatenate([pts[:1] - (pts[1] - pts[0]) * 0.8, pts, pts[-1:] + (pts[2] - pts[1]) * 0.8]))
    a, e1, e2 = frame_from(pts[1] - pts[0])
    for k, c in enumerate(pts[:2]):
        R = 0.56

        def pos(u, v, c=c):
            th = v * 2 * np.pi
            return c + (u * R * 1.2)[:, None] * (np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2)

        def mat(u, v, P, N, k=k):
            th = v * 2 * np.pi
            x, y = u * 1.2 * np.cos(th), u * 1.2 * np.sin(th)
            sheet, along, r, edge = scroll_section(x, y, seed + k, turns=7.0, rot=0.6 * k)
            kk = len(u)
            glow = smoothstep(0.08, 0.0, np.hypot(x, y))
            return {"albedo": sheet_albedo(sheet, along, r, np.arctan2(y, x), seed + k, tone=1.2),
                    "emit": (L_COPPER * 2.0)[None, :] * glow[:, None], "keep": r < edge + 0.02,
                    "metal": np.zeros(kk, np.float32), "shine": np.full(kk, 22.0, np.float32),
                    "spec": 0.08 + 0.25 * sheet, "rim": 0.6 + 0.6 * sheet}

        surfaces.append(Surface(pos, mat, tiles=(20, 56), density=0.8))
    surfaces.append(tube(thread, 0.013, copper_metal(glow=1.2), shadow=False))
    cam = Camera(p.get("eye", [-3.4, 1.7, 6.6]), p.get("target", [0.4, 0.45, -0.7]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(np.array([-0.2, 0.68, 0.35]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-4, 0, -3), (4, 1.6, 2)), dof=p.get("dof", 0.08), bloom=0.4, fog=0.01,
                 spot=((-0.8, 0.8, 0.0), 5.0), key_power=p.get("key_power", 3.6))


# ---------------------------------------------------------------------------------------------------------------------
# Screenshots as floating panels (a Synthetic demo when they show only made-up data).


def sample(tex, u, v):
    h, w = tex.shape[:2]
    x = np.clip((u * (w - 1)).astype(np.int64), 0, w - 1)
    y = np.clip((v * (h - 1)).astype(np.int64), 0, h - 1)
    return tex[y, x]


def padded(img, pad):
    """The screenshot with a margin of its own background color (its corner pixel) on every side, so text that runs to
    the edge of the capture does not look cut off on the panel."""
    if not pad:
        return img
    bg = img[2, 2]
    out = np.empty((img.shape[0] + 2 * pad, img.shape[1] + 2 * pad, 3), dtype=img.dtype)
    out[:] = bg
    out[pad:pad + img.shape[0], pad:pad + img.shape[1]] = img
    return out


@scene
def build_panels(p, W, H, seed):
    """Screenshots of a tool as glowing panels floating at an angle over the floor (a Synthetic demo when the
    screenshots show only made-up data). params: {"panels": [{"image": PATH, "center": [x, y, z], "yaw": DEG,
    "pitch": DEG, "height": H, "crop": [x0, y0, x1, y1], "pad": PX, "glow": G}], "eye", "target", "fov"}."""
    from PIL import Image

    surfaces = []
    for i, spec in enumerate(p["panels"]):
        img = np.asarray(Image.open(spec["image"]).convert("RGB")).astype(np.float32) / 255
        crop = spec.get("crop")
        if crop:
            x0, y0, x1, y1 = crop
            img = img[y0:y1, x0:x1]
        img = padded(img, int(spec.get("pad", 0)))
        lin = to_linear(img)
        ih, iw = lin.shape[:2]
        hh = spec.get("height", 2.0)
        ww = hh * iw / ih
        f = oriented(spec["center"], yaw=spec.get("yaw", 0), pitch=spec.get("pitch", 0))
        bright = spec.get("glow", 0.9)

        def pos(u, v, ww=ww, hh=hh, f=f):
            loc = np.stack([(u - 0.5) * ww, (0.5 - v) * hh, np.zeros_like(u)], axis=1).astype(np.float32)
            return f(loc)

        def mat(u, v, P, N, lin=lin, bright=bright, ww=ww, hh=hh):
            col = sample(lin, u, v)
            k = len(u)
            r = 0.035 / min(ww, hh)
            edge = np.minimum(np.minimum(u, 1 - u) * ww / hh, np.minimum(v, 1 - v))
            frame = smoothstep(r * 0.5, 0.0, edge)
            return {"albedo": col * 0.25 * (1 - frame[:, None]) + (L_COPPER * frame[:, None]),
                    "emit": col * bright * (1 - frame[:, None]) + (L_COPPER * 0.6)[None, :] * frame[:, None],
                    "metal": frame, "shine": np.full(k, 60.0, np.float32), "spec": 0.35 + 0.5 * frame,
                    "rim": np.full(k, 1.2, np.float32)}

        surfaces.append(Surface(pos, mat, tiles=(64, 48), density=0.55))
    cam = Camera(p.get("eye", [-3.0, 2.4, 8.8]), p.get("target", [0.8, 1.0, -0.6]), p.get("fov", 20), W, H)
    if p.get("focus"):
        cam.focus = float(np.linalg.norm(np.asarray(p["focus"]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-6, 0, -5), (6, 3, 3)), dof=p.get("dof", 0.25), bloom=0.25, fog=0.01,
                 spot=tuple(p.get("spot", [[-1.0, 1.0, 0.5], 6.0])), key_power=2.2, cavity=0.0)


# ---------------------------------------------------------------------------------------------------------------------
# Headless VC3D for agents: a scan cube, and a traced surface leaving it as a copper mesh on a papyrus sheet.


@scene
def build_vc3dagent(p, W, H, seed):
    """A floating scan cube cut by slices of curved papyrus layers, and from inside it a sheet running out along the
    diagonal: papyrus underneath, a copper surface grid traced over it that fades toward the far end, and a row of
    small copper beads riding a thin line above it, as calls and results pass between an agent and the tools.
    Synthetic fields only: no scan, no ink, no letters."""
    surfaces = []
    center = p.get("center", [-1.7, 1.25, 0.7])
    main = oriented(center, yaw=p.get("yaw", 32), pitch=6, scale=1.0)
    surfaces += cube_part(main, seed, size=0.95, detail=1.4, edge_glow=0.3, slices=("sheets", "sheets", "speckle"))
    x0, x1, width = -0.4, p.get("run", 6.6), p.get("width", 1.6)
    tilt = math.radians(p.get("tilt", 8.0))
    place = placer(p.get("rot", -20.0), (center[0], 0.0, center[2]))

    def sheet_y(x, z, h=0.0):
        rise = 1.15 * np.exp(-((x - x0) / 2.2) ** 2)        # leaves the cube's middle, settles toward the floor
        return 0.08 + rise + 0.07 * np.sin(x * 1.3 + 0.6) + h - z * math.tan(tilt)

    def spos(u, v, h=0.0):
        x = x0 + u * (x1 - x0)
        z = (v - 0.5) * width
        return place(np.stack([x, sheet_y(x, z, h), z], axis=1).astype(np.float32))

    def pmat(u, v, P, N):
        alb, height = papyrus(u * (x1 - x0), v * width, seed, scale=0.45, tone=1.4, char=0.35)
        k = len(u)
        keep = ragged(u, v, amount=0.012, seed=seed + 2, freq=24.0)
        return {"albedo": alb, "keep": keep, "metal": np.zeros(k, np.float32), "shine": np.full(k, 14.0, np.float32),
                "spec": np.full(k, 0.12, np.float32), "rim": np.full(k, 1.0, np.float32)}

    surfaces.append(Surface(spos, pmat, tiles=(260, 30), density=0.7))

    def gmat(u, v, P, N):
        lines = grid_lines(u * (x1 - x0), v * width, 1 / 0.18, 1 / 0.18, 0.04)
        fade = smoothstep(1.0, 0.45, u) * smoothstep(0.0, 0.06, u)
        keep = lines & (fbm(u * 9, v * 9, 2, seed + 3) < 0.25 + 0.75 * fade)
        k = len(u)
        return {"albedo": np.broadcast_to(L_COPPER * 1.1, (k, 3)), "keep": keep, "metal": np.ones(k, np.float32),
                "shine": np.full(k, 50.0, np.float32), "spec": np.full(k, 0.9, np.float32),
                "emit": (L_COPPER * 0.9)[None, :] * fade[:, None], "rim": np.full(k, 1.5, np.float32)}

    surfaces.append(Surface(lambda u, v: spos(u, v, 0.012), gmat, tiles=(260, 30), density=0.6, cast=False,
                            shadow=False))
    lift = p.get("line_lift", 0.62)
    line = lambda t: spos(np.asarray(t, np.float32) * 0.92 + 0.05, np.full_like(np.asarray(t, np.float32), 0.5), lift)
    surfaces.append(tube(line, 0.008, copper_metal(glow=1.1), shadow=False))
    for i in range(p.get("beads", 7)):
        c = line(np.array([0.06 + i * 0.13], np.float32))[0]

        def bpos(u, v, c=c, r=0.05 + 0.012 * (i % 3)):
            th, ph = u * 2 * np.pi, v * np.pi
            return (c[None, :] + r * np.stack([np.sin(ph) * np.cos(th), np.cos(ph), np.sin(ph) * np.sin(th)],
                                              axis=1)).astype(np.float32)

        surfaces.append(Surface(bpos, copper_metal(glow=1.6 if i % 2 else 0.9), tiles=(18, 12), density=0.7,
                                shadow=False, cast=False))
    cam = Camera(p.get("eye", [-4.2, 2.3, 8.2]), p.get("target", [1.4, 0.8, -0.9]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(np.array(center) - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -6), (8, 3, 3)), dof=p.get("dof", 0.09), bloom=0.4, fog=0.012,
                 spot=((-1.2, 1.2, 0.6), 6.5), key_power=p.get("key_power", 3.4))
