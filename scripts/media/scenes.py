"""The procedural hero scenes, one per released tool, built for scene.render().

Every scene is generated from formulas and a seed: no scan, map, model output or recovered text. Each builder takes
(params, width, height, seed) and returns a scene.Scene. Recipes in scripts/media/recipes/ name a builder and may
override its params.
"""

import math

import numpy as np

from scene import (L_CHARCOAL, L_COPPER, L_EMBER, L_IVORY, Camera, Scene, Surface, copper_metal, fbm, grid_lines,
                   normalize, papyrus, plain, ragged, smoothstep, sphere, to_linear, tube, value_noise)

SCENES = {}


def scene(fn):
    SCENES[fn.__name__.removeprefix("build_")] = fn
    return fn


def build(name, params, width, height, seed=0):
    if name not in SCENES:
        raise ValueError(f"no scene {name!r}; scenes: {', '.join(sorted(SCENES))}")
    return SCENES[name](dict(params or {}), width, height, seed)


def catmull(points):
    """A smooth curve t in [0, 1] -> (n, 3) through the given points (centripetal Catmull-Rom, clamped ends)."""
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


def spiral_section(r, th, pitch, seed, gaps=0.0, wobble=0.25, thick=0.34):
    """Synthetic scroll cross-section: an Archimedean spiral of sheets in polar coordinates. Returns sheet in [0, 1]."""
    w = wobble * pitch * (ring_noise(th, r, 1.0, 0.8, seed) - 0.5) * 2
    w = w + 0.35 * pitch * (ring_noise(th, r, 0.4, 2.5, seed + 3, 2) - 0.5)
    phase = (r + w) / pitch - th / (2 * np.pi)
    f = np.abs((phase % 1.0) - 0.5) * 2                     # 1 at the middle of a sheet
    t = thick * (0.75 + 0.5 * ring_noise(th, r, 0.9, 4, seed + 5, 2))
    sheet = smoothstep(1 - t, 1 - t * 0.35, f)
    if gaps:
        sheet = sheet * smoothstep(gaps - 0.02, gaps + 0.02, ring_noise(th, np.floor(phase) * 0.11, 0.7, 1.0, seed + 9, 2))
    return sheet


# ---------------------------------------------------------------------------------------------------------------------


@scene
def build_umbilicus(p, W, H, seed):
    """Seven synthetic cross-sections of a scroll, cap to base, with a copper thread through each winding center."""
    n = p.get("discs", 7)
    R = p.get("radius", 0.95)
    start = np.array(p.get("start", [-3.4, 1.2, 1.8]), dtype=np.float32)
    end = np.array(p.get("end", [9.5, 1.05, -6.0]), dtype=np.float32)
    rng = np.random.default_rng(seed)
    axis_pts, centers, offsets = [], [], []
    for k in range(n):
        t = k / (n - 1)
        base = start + (end - start) * t
        drift = np.array([0.0, 0.10 * math.sin(2.1 * t * math.pi + 0.4), 0.12 * math.cos(1.7 * t * math.pi)],
                         dtype=np.float32)
        centers.append(base)
        axis_pts.append(base + drift)
        offsets.append(rng.normal(0, 0.05, 2))
    axis_pts = np.array(axis_pts)
    thread_pts = np.concatenate([axis_pts[:1] - (axis_pts[1] - axis_pts[0]) * 0.9, axis_pts,
                                 axis_pts[-1:] + (axis_pts[-1] - axis_pts[-2]) * 0.9])
    thread = catmull(thread_pts)
    surfaces = []
    pitch = R / p.get("windings", 17)
    for k in range(n):
        c = centers[k]
        tk = (k + 1) / (len(thread_pts) - 1)
        tan = normalize(thread(np.array([tk + 0.01]))[0] - thread(np.array([tk - 0.01]))[0])
        a, e1, e2 = frame_from(tan)
        um = axis_pts[k]
        # where the winding center sits on this disc, in disc coordinates
        oc = np.array([np.dot(um - c, e1), np.dot(um - c, e2)], dtype=np.float32)
        sd = seed + 31 * k
        bound = 0.06

        def pos(u, v, c=c, e1=e1, e2=e2):
            th = v * 2 * np.pi
            r = u * R
            return c + r[:, None] * (np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2)

        def mat(u, v, P, N, c=c, e1=e1, e2=e2, oc=oc, sd=sd, k=k):
            th = v * 2 * np.pi
            x, y = u * R * np.cos(th) - oc[0], u * R * np.sin(th) - oc[1]
            cr, sr = math.cos(0.9 * k + 0.3), math.sin(0.9 * k + 0.3)
            x, y = (x * cr + y * sr) / 1.0, (-x * sr + y * cr) / (0.80 + 0.04 * (k % 3))   # squashed, as scrolls are
            rr, tt = np.hypot(x, y), np.arctan2(y, x)
            edge = R * (0.90 + bound * (fbm(np.cos(th) * 1.7 + k, np.sin(th) * 1.7, 3, sd) - 0.5) * 2)
            keep = (u * R) < edge
            sheet = spiral_section(rr, tt, pitch, sd, gaps=0.3, wobble=0.7, thick=0.22)
            core = smoothstep(pitch * 1.4, pitch * 0.4, rr)          # the hollow at the winding center
            sheet = sheet * (1 - core)
            tex = (0.7 + 0.3 * ring_noise(tt, rr, 1.2, 30, sd + 1, 2))[:, None]
            alb = (L_CHARCOAL * 0.22)[None, :] * (1 - sheet[:, None]) + (L_IVORY * 0.42)[None, :] * tex * sheet[:, None]
            glow = smoothstep(pitch * 1.3, pitch * 0.3, rr)
            emit = (L_COPPER * 0.9)[None, :] * (glow * 0.9)[:, None] + (L_IVORY * 0.07)[None, :] * (tex * sheet[:, None])
            kk = len(u)
            return {"albedo": alb, "emit": emit, "keep": keep, "metal": np.zeros(kk, np.float32),
                    "shine": np.full(kk, 30.0, np.float32), "spec": 0.15 + 0.25 * sheet,
                    "rim": np.full(kk, 0.5, np.float32)}

        surfaces.append(Surface(pos, mat, tiles=(24, 64), density=0.8))
        # the disc's rim: a short band so each slice has thickness
        thick = 0.025

        def rpos(u, v, c=c, e1=e1, e2=e2, a=a, sd=sd, k=k):
            th = u * 2 * np.pi
            edge = R * (0.90 + bound * (fbm(np.cos(th) * 1.7 + k, np.sin(th) * 1.7, 3, sd) - 0.5) * 2)
            return c + edge[:, None] * (np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2) + \
                ((v - 0.5) * thick)[:, None] * a

        surfaces.append(Surface(rpos, plain(L_CHARCOAL * 0.6, shine=20, spec=0.2, rim=1.2), tiles=(96, 2), density=0.8))
    surfaces.append(tube(thread, 0.016, copper_metal(glow=1.2), shadow=False))
    cam = Camera(p.get("eye", [-4.2, 2.9, 9.8]), p.get("target", [2.4, 0.95, -1.4]), p.get("fov", 20), W, H)
    cam.focus = float(np.linalg.norm(centers[2] - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -8), (11, 3, 4)), dof=p.get("dof", 0.3), bloom=0.45, fog=0.015)


# ---------------------------------------------------------------------------------------------------------------------
# A sheet that rolls up at one end: shared by Unroll, the reader and the workbench scenes.


def roll_profile(turns=4.5, r_in=0.18, r_out=0.62, lift=0.0, run=6.0, drop=1.6, wave=0.05, n=24000):
    """The 2D cross-section of a rolled sheet whose outer end leaves the top of the roll, drops to the floor and runs
    flat along +x. Returns (s, xy): arc length samples and (n, 2) points; the roll rests on y = 0 at x = 0."""
    cy = r_out + 0.01 + lift
    big = 2 * np.pi * turns
    th = np.linspace(0, big, n // 2)
    r = r_in + (r_out - r_in) * th / big
    alpha = np.pi / 2 + (big - th)
    spiral = np.stack([r * np.cos(alpha), cy + r * np.sin(alpha)], axis=1)
    p0 = spiral[-1]
    x3 = p0[0] + drop
    p3 = np.array([x3, 0.006])
    tt = np.linspace(0, 1, n // 6)[1:, None]
    c1, c2 = p0 + np.array([drop * 0.45, 0.0]), p3 - np.array([drop * 0.5, 0.0])
    bez = (1 - tt) ** 3 * p0 + 3 * (1 - tt) ** 2 * tt * c1 + 3 * (1 - tt) * tt ** 2 * c2 + tt ** 3 * p3
    xs = np.linspace(x3, x3 + run, n // 3)[1:]
    ys = 0.006 + wave * np.sin((xs - x3) * 2.1) ** 2 * np.exp(-(xs - x3) / (run * 0.6))
    flat = np.stack([xs, ys], axis=1)
    xy = np.concatenate([spiral, bez, flat])
    seg = np.hypot(*np.diff(xy, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    return s.astype(np.float32), xy.astype(np.float32), float(s[len(spiral) - 1]), float(s[len(spiral) + len(bez) - 1])


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


def papyrus_material(S, width, seed, edge=0.02, char=0.2, tone=1.0, s_range=None, extra=None):
    lo, hi = s_range or (0.0, S)

    def mat(u, v, P, N):
        ss = lo + u * (hi - lo)
        zz = v * width
        alb, height = papyrus(ss, zz, seed, scale=1.0, tone=tone, char=char)
        keep = ragged(ss / S, v, amount=edge, seed=seed, freq=40.0)
        k = len(u)
        out = {"albedo": alb, "bump": height * 0.002, "keep": keep, "metal": np.zeros(k, np.float32),
               "shine": np.full(k, 14.0, np.float32), "spec": np.full(k, 0.12, np.float32),
               "rim": np.full(k, 1.0, np.float32)}
        if extra:
            out = extra(u, v, ss, zz, out)
        return out

    return mat


@scene
def build_unroll(p, W, H, seed):
    """A roll whose outer sheet unrolls flat and then lifts into floating layers: the papyrus, a copper surface grid
    and a scatter of ivory light, like a viewer's stacked layers."""
    width = p.get("width", 2.3)
    s, xy, s_roll, s_flat = roll_profile(turns=p.get("turns", 5.0), r_out=0.66, run=p.get("run", 6.5), drop=1.5)
    S = float(s[-1])
    place = placer(p.get("rot", -18.0), (-3.3, 0, 0.6))
    surfaces = [profile_sheet(s, xy, width, place, papyrus_material(S, width, seed, edge=0.012, char=0.15),
                              tiles=(260, 24), bump_scale=1.0)]
    # The floating layers over the flat run, exploded upward.
    x0, x1 = float(np.interp(s_flat, s, xy[:, 0])) + 0.25, float(xy[-1, 0]) - 0.15
    for li, (h, kind) in enumerate(((0.55, "grid"), (1.05, "ink"))):
        def pos(u, v, h=h, li=li):
            x = x0 + 0.08 * li + u * (x1 - x0)
            y = np.full_like(u, h) + 0.04 * np.sin(u * 5 + li)
            z = (v - 0.5) * width * 0.98
            return place(np.stack([x, y, z], axis=1).astype(np.float32))

        if kind == "grid":
            def mat(u, v, P, N):
                lines = grid_lines(u * (x1 - x0), v * width, 1 / 0.16, 1 / 0.16, 0.07)
                fade = smoothstep(0.0, 0.25, u) * smoothstep(1.0, 0.8, u)
                keep = lines & (fbm(u * 9, v * 9, 2, seed + 3) < 0.25 + 0.75 * fade)
                k = len(u)
                return {"albedo": np.broadcast_to(L_COPPER * 1.1, (k, 3)), "keep": keep,
                        "metal": np.ones(k, np.float32), "shine": np.full(k, 50.0, np.float32),
                        "spec": np.full(k, 0.9, np.float32), "emit": (L_COPPER * 0.35)[None, :] * fade[:, None],
                        "rim": np.full(k, 1.5, np.float32)}
        else:
            def mat(u, v, P, N):
                field = fbm(u * 3.2, v * 2.4, 4, seed + 11)
                gu, gv = u * (x1 - x0) / 0.08, v * width / 0.08            # a regular lattice of points
                d = np.hypot((gu % 1.0) - 0.5, (gv % 1.0) - 0.5)
                fade = smoothstep(0.0, 0.3, u) * smoothstep(1.0, 0.75, u)
                size = 0.12 + 0.22 * smoothstep(0.35, 0.75, field)
                keep = (d < size) & (fade > 0.05)
                k = len(u)
                glow = (0.2 + 0.8 * smoothstep(0.4, 0.75, field)) * fade
                return {"albedo": np.broadcast_to(L_IVORY * 0.35, (k, 3)), "keep": keep,
                        "metal": np.zeros(k, np.float32), "shine": np.full(k, 20.0, np.float32),
                        "spec": np.full(k, 0.3, np.float32), "emit": (L_IVORY * 0.55)[None, :] * glow[:, None],
                        "rim": np.zeros(k, np.float32)}
        surfaces.append(Surface(pos, mat, tiles=(64, 24), density=0.6, cast=li == 0, shadow=False))
    # Thin copper posts at the layer corners tie the stack together.
    for (cu, cv) in ((0, 0), (0, 1), (1, 0), (1, 1)):
        xa = x0 + cu * (x1 - x0)
        za = (cv - 0.5) * width * 0.98
        a = place(np.array([[xa, 0.01, za]], dtype=np.float32))[0]
        b = place(np.array([[xa + 0.08, 1.05, za]], dtype=np.float32))[0]
        surfaces.append(tube(lambda t, a=a, b=b: a[None, :] + (b - a)[None, :] * t[:, None], 0.006,
                             copper_metal(glow=0.4), shadow=False))
    cam = Camera(p.get("eye", [-3.8, 4.0, 9.8]), p.get("target", [1.1, -0.15, -0.7]), p.get("fov", 21), W, H)
    return Scene(cam, surfaces, bounds=((-5, 0, -4), (6, 2, 4)), dof=p.get("dof", 0.35), bloom=0.4, fog=0.012,
                 spot=((-2.6, 1.0, 1.0), 5.5), key_power=p.get("key_power", 2.4))


# ---------------------------------------------------------------------------------------------------------------------
# Parts that several scenes share.


def oriented(center, yaw=0.0, pitch=0.0, scale=1.0):
    """A function local (n, 3) -> world (n, 3): scale, then pitch about x, then yaw about y, then move to center."""
    c = np.asarray(center, dtype=np.float32)
    ya, pa = math.radians(yaw), math.radians(pitch)
    ry = np.array([[math.cos(ya), 0, math.sin(ya)], [0, 1, 0], [-math.sin(ya), 0, math.cos(ya)]], dtype=np.float32)
    rx = np.array([[1, 0, 0], [0, math.cos(pa), -math.sin(pa)], [0, math.sin(pa), math.cos(pa)]], dtype=np.float32)
    m = (ry @ rx) * scale

    def f(p):
        return p @ m.T + c

    return f


def palette_ramp(t):
    """Map t in [0, 1] through charcoal, ember, copper and ivory (linear RGB)."""
    stops = np.array([0.0, 0.35, 0.72, 1.0], dtype=np.float32)
    cols = np.stack([L_CHARCOAL * 0.6, L_EMBER, L_COPPER, L_IVORY])
    t = np.clip(t, 0, 1)
    return np.stack([np.interp(t, stops, cols[:, k]) for k in range(3)], axis=-1).astype(np.float32)


def cube_part(to_world, seed, size=1.0, detail=1.0, edge_glow=0.5, slices=("bands", "embed", "speckle")):
    """A cube of edge 2 * size with three orthogonal slices through its center, each with a synthetic field, and
    copper edges."""
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
            if kind == "bands":
                w = 0.25 * np.sin(x * 2.4 + 0.6) + 0.18 * (fbm(x * 1.5, y * 1.5, 3, seed) - 0.5)
                f = np.abs(((y + w) / 0.13) % 1.0 - 0.5) * 2
                sheet = smoothstep(0.62, 0.9, f) * (fbm(x * 3, y * 0.7, 2, seed + 4) > 0.33)
                alb = (L_CHARCOAL * 0.3)[None, :] + (L_IVORY * 0.45 - L_CHARCOAL * 0.3)[None, :] * sheet[:, None]
                emit = (L_IVORY * 0.10)[None, :] * sheet[:, None]
            elif kind == "embed":
                t = fbm(x * 1.6 + 4, y * 1.6, 4, seed + 7)
                t = np.round(t * 7) / 7                                   # patches, like an embedding's colors
                alb = palette_ramp(0.15 + 1.0 * (t - 0.3) / 0.45) * 0.6
                emit = alb * 0.22
            else:
                base = fbm(x * 2, y * 2, 3, seed + 9)
                speck = value_noise(x * 60, y * 60, seed + 11) * smoothstep(0.5, 0.75, base)
                hot = smoothstep(0.55, 0.85, speck)
                alb = (L_CHARCOAL * 0.25)[None, :] + (L_COPPER * 0.5)[None, :] * hot[:, None]
                emit = (L_COPPER * 1.2)[None, :] * hot[:, None] ** 2
            return {"albedo": alb, "emit": emit, "metal": np.zeros(k, np.float32), "shine": np.full(k, 30.0, np.float32),
                    "spec": np.full(k, 0.25, np.float32), "rim": np.full(k, 0.6, np.float32)}

        out.append(Surface(pos, mat, tiles=(int(32 * detail) + 4, int(32 * detail) + 4), density=0.75))
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=np.float32) * size
    for i in range(8):
        for j in range(i + 1, 8):
            if np.sum(corners[i] != corners[j]) == 1:
                a, b = to_world(corners[i:i + 1])[0], to_world(corners[j:j + 1])[0]
                out.append(tube(lambda t, a=a, b=b: a[None, :] + (b - a)[None, :] * t[:, None],
                                0.012 * size + 0.004, copper_metal(glow=edge_glow), shadow=False))
    return out


@scene
def build_lens(p, W, H, seed):
    """A floating cube cut by three slices (a synthetic sheet field, embedding-like patches and an ink-like speckle)
    with a cloud of matched points along a curved sheet, and smaller cubes receding to the right."""
    surfaces = []
    main = oriented(p.get("center", [-1.3, 1.25, 0.4]), yaw=p.get("yaw", 32), pitch=8, scale=1.0)
    surfaces += cube_part(main, seed, size=0.9, detail=1.5)

    def spos(u, v):
        x = (u * 2 - 1) * 0.82
        z = (v * 2 - 1) * 0.82
        y = 0.3 * np.sin(x * 1.8 + 0.4) * np.cos(z * 1.2) + 0.25
        return main(np.stack([x, y, z], axis=1).astype(np.float32))

    def smat(u, v, P, N):
        g = np.hypot((u * 46) % 1.0 - 0.5, (v * 46) % 1.0 - 0.5)
        sel = fbm(u * 4, v * 4, 3, seed + 21)
        keep = (g < 0.2) & (sel > 0.45)
        k = len(u)
        hot = smoothstep(0.45, 0.7, sel)
        return {"albedo": np.broadcast_to(L_IVORY * 0.5, (k, 3)), "keep": keep, "metal": np.zeros(k, np.float32),
                "shine": np.full(k, 30.0, np.float32), "spec": np.full(k, 0.2, np.float32),
                "emit": (L_IVORY * 1.4)[None, :] * hot[:, None] + (L_COPPER * 0.6)[None, :] * (1 - hot)[:, None],
                "rim": np.zeros(k, np.float32)}

    surfaces.append(Surface(spos, smat, tiles=(48, 48), density=0.6, shadow=False))
    for i, (cx, cz, s_) in enumerate(((1.9, -1.2, 0.5), (3.6, -2.6, 0.42), (5.2, -4.0, 0.36), (6.7, -5.5, 0.32))):
        f = oriented([cx, 0.62 + s_ * 1.2, cz], yaw=20 + 17 * i, pitch=6, scale=1.0)
        surfaces += cube_part(f, seed + 50 * (i + 1), size=s_, detail=0.6, edge_glow=0.3)
    cam = Camera(p.get("eye", [-5.0, 3.6, 10.2]), p.get("target", [0.9, 0.75, -0.9]), p.get("fov", 20), W, H)
    cam.focus = float(np.linalg.norm(np.array([-1.3, 1.25, 0.4]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-4, 0, -7), (8, 3, 3)), dof=p.get("dof", 0.3), bloom=0.45, fog=0.015,
                 spot=((-1.2, 1.4, 0.6), 6.0), key_power=2.6)


def letters_texture(seed, size=(4096, 1536), rows=6, cols=26, font=None):
    """A synthetic sheet of random Greek capitals (no words) as an ink mask, plus copper proposal boxes around some
    letters with a confidence bar under each. Returns (ink, boxes) float arrays in [0, 1] of shape (H, W)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    rng = np.random.default_rng(seed)
    alphabet = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
    w, h = size
    ink = Image.new("L", size, 0)
    box = Image.new("L", size, 0)
    di, db = ImageDraw.Draw(ink), ImageDraw.Draw(box)
    fpath = font
    if fpath is None:
        from hero import find_font
        fpath = find_font("Inter-Light.otf") or find_font("Inter-Regular.otf")
    line_h = h / (rows + 1.2)
    fsize = int(line_h * 0.62)
    fnt = ImageFont.truetype(fpath, fsize)
    boxed_row = rows // 2
    for r in range(rows):
        y = line_h * (0.7 + r) + rng.normal(0, 3)
        x = w * 0.04
        for c in range(cols):
            ch = alphabet[rng.integers(len(alphabet))]
            if rng.random() < 0.05:
                x += fsize * 0.5
                continue
            g = Image.new("L", (fsize * 2, fsize * 2), 0)
            ImageDraw.Draw(g).text((fsize * 0.4, fsize * 0.3), ch, font=fnt, fill=255)
            g = g.rotate(rng.normal(0, 3), resample=Image.BICUBIC)
            fade = int(150 + 105 * rng.random())
            ink.paste(Image.new("L", g.size, fade), (int(x - fsize * 0.4), int(y - fsize * 0.3)), g)
            adv = di.textlength(ch, font=fnt) * (1.05 + 0.15 * rng.random())
            if r == boxed_row and 6 <= c <= 13:
                top = y + fsize * 0.08
                db.rectangle([x - 6, top - 6, x + adv - 4, top + fsize * 0.86], outline=255, width=7)
                conf = 0.35 + 0.6 * rng.random()
                db.rectangle([x - 6, top + fsize * 0.98, x - 6 + (adv - 2) * conf, top + fsize * 1.05], fill=255)
            x += adv
            if x > w * 0.96:
                break
    ink = ink.filter(ImageFilter.GaussianBlur(2.2))
    a = np.asarray(ink).astype(np.float32) / 255
    rough = value_noise(*np.meshgrid(np.arange(w) / 9.0, np.arange(h) / 9.0), seed=seed + 3)
    a = np.clip(a * (0.65 + 0.6 * rough), 0, 1)
    return a, np.asarray(box.filter(ImageFilter.GaussianBlur(1.0))).astype(np.float32) / 255


def sample(tex, u, v):
    h, w = tex.shape[:2]
    x = np.clip((u * (w - 1)).astype(np.int64), 0, w - 1)
    y = np.clip((v * (h - 1)).astype(np.int64), 0, h - 1)
    return tex[y, x]


@scene
def build_reader(p, W, H, seed):
    """A papyrus sheet that curls up at its left end, with synthetic random Greek capitals in ink and copper proposal
    boxes with confidence bars around some of them. No scroll data, no words."""
    width = p.get("width", 2.2)
    s, xy, s_roll, s_flat = roll_profile(turns=1.6, r_in=0.32, r_out=0.48, run=p.get("run", 6.8), drop=0.9, wave=0.03)
    S = float(s[-1])
    ink, boxes = letters_texture(seed, font=p.get("font"))
    t0, t1 = s_flat / S + 0.01, 0.985          # where the letters sit along the sheet

    def extra(u, v, ss, zz, out):
        inside = (u > t0) & (u < t1)
        tu = np.clip((u - t0) / (t1 - t0), 0, 1)
        tv = np.clip(v, 0, 1)                      # v = 0 is the far edge, the top of the letters
        a = np.where(inside, sample(ink, tu, tv), 0.0)
        b = np.where(inside, sample(boxes, tu, tv), 0.0)
        alb = out["albedo"] * (1 - 0.88 * a[:, None])
        alb = alb * (1 - b[:, None]) + (L_COPPER * 1.05)[None, :] * b[:, None]
        out.update(albedo=alb, metal=np.maximum(out["metal"], b), shine=out["shine"] + 40 * b,
                   spec=out["spec"] + 0.8 * b, emit=(L_COPPER * 0.55)[None, :] * b[:, None])
        return out

    place = placer(p.get("rot", -16.0), (-3.4, 0, 0.5))
    mat = papyrus_material(S, width, seed, edge=0.010, char=0.0, tone=1.7, extra=extra)
    surfaces = [profile_sheet(s, xy, width, place, mat, tiles=(420, 40), bump_scale=1.0, density=0.6)]
    cam = Camera(p.get("eye", [-3.3, 3.2, 6.7]), p.get("target", [0.7, -0.45, -0.5]), p.get("fov", 22), W, H)
    cam.focus = float(np.linalg.norm(np.array([-0.4, 0.0, 0.0]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -4), (6, 2, 4)), dof=p.get("dof", 0.4), bloom=0.3, fog=0.012,
                 spot=((-1.2, 0.5, 0.6), 4.5), key_power=2.8)


@scene
def build_strokenet(p, W, H, seed):
    """A sheet cut into scoring windows: windows with rows of abstract strokes lift and glow by a synthetic score, and
    one lifted window's 90 degree turn hovers beside it as the control. No letters, no scroll data."""
    nx, nz = p.get("cols", 9), p.get("rows", 4)
    cell, gap = 0.7, 0.05
    rng = np.random.default_rng(seed)
    origin = np.array([-3.6, 0.0, -0.4], dtype=np.float32)
    yaw = math.radians(p.get("yaw", -14))
    rot = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]], np.float32)
    text_like = rng.random((nx, nz)) < 0.55
    score = np.where(text_like, 0.55 + 0.45 * rng.random((nx, nz)), 0.1 * rng.random((nx, nz)))
    lift = {(2, 1): 0.9, (4, 2): 0.55, (6, 1): 0.75}
    for c in lift:
        text_like[c] = True
        score[c] = 0.8 + 0.2 * rng.random()
    surfaces = []

    def strokes(a, b, sd, turned=False):
        if turned:
            a, b = b, a
        row = np.floor(b * 5)
        fb = (b * 5) % 1.0
        line = smoothstep(0.26, 0.36, fb) * smoothstep(0.74, 0.64, fb)
        seg = value_noise(a * 22 + row * 7.3, row * 3.1, sd)
        dash = smoothstep(0.42, 0.5, seg)
        return line * dash

    def window(ix, iz, h, turned=False, dx=0.0, glow_scale=1.0):
        x0 = ix * (cell + gap)
        z0 = iz * (cell + gap)
        sd = seed + 100 * ix + 7 * iz

        def pos(u, v):
            loc = np.stack([x0 + dx + u * cell, np.full_like(u, h + 0.004), z0 + v * cell], axis=1)
            return loc.astype(np.float32) @ rot.T + origin

        def mat(u, v, P, N):
            alb, height = papyrus(x0 + u * cell, z0 + v * cell, seed, tone=1.5)
            ink = strokes(u, v, sd, turned) if text_like[ix, iz] else np.zeros_like(u)
            alb = alb * (1 - 0.95 * ink[:, None])
            sc = score[ix, iz] * glow_scale
            edge = np.minimum(np.minimum(u, 1 - u), np.minimum(v, 1 - v))
            frame = smoothstep(0.035, 0.0, edge) * (h > 0.01)
            k = len(u)
            emit = (L_COPPER * (1.6 * sc))[None, :] * frame[:, None] + (L_COPPER * 0.05 * sc)[None, :]
            return {"albedo": alb * (1 - frame[:, None]) + (L_COPPER * frame[:, None]), "bump": height * 0.002,
                    "metal": frame, "shine": np.full(k, 16.0, np.float32) + 30 * frame,
                    "spec": 0.12 + 0.8 * frame, "emit": emit, "rim": np.full(k, 1.0, np.float32)}

        return Surface(pos, mat, tiles=(16, 16), density=0.7, bump_scale=1.0)

    for ix in range(nx):
        for iz in range(nz):
            surfaces.append(window(ix, iz, lift.get((ix, iz), 0.0)))
    # the control: the most lifted window, turned 90 degrees, hovering beside it with a weak glow
    surfaces.append(window(2, 1, 0.9, turned=True, dx=cell + 0.35, glow_scale=0.25))
    cam = Camera(p.get("eye", [-3.0, 3.9, 7.0]), p.get("target", [0.5, -0.5, 0.4]), p.get("fov", 21), W, H)
    return Scene(cam, surfaces, bounds=((-5, 0, -3), (6, 2, 4)), dof=p.get("dof", 0.35), bloom=0.4, fog=0.012,
                 spot=((-1.6, 0.6, 0.8), 5.0), key_power=2.6)


@scene
def build_stackcheck(p, W, H, seed):
    """Consecutive segments as standing sheets around a scroll's center thread, with rays from the center along the
    floor: one segment misses a sector (its edges glow) and two neighbors touch (an ivory glow)."""
    n = p.get("segments", 8)
    pitch = 0.24
    center = np.array(p.get("center", [-1.4, 0.0, -0.6]), dtype=np.float32)
    hgt = p.get("height", 0.5)
    surfaces = []
    gap_k, gap = 4, (math.radians(50), math.radians(122))
    touch_k, touch_at = 6, math.radians(200)
    for k in range(n):
        th0 = math.radians(120 + 31 * k)
        span = 2 * np.pi * 0.9

        def radius(th, k=k, th0=th0):
            r = 0.45 + pitch * k + pitch * (th - th0) / (2 * np.pi)
            r = r + 0.03 * np.sin(th * 3 + k) + 0.02 * (fbm(np.cos(th) * 2 + k, np.sin(th) * 2, 2, seed + k) - 0.5)
            if k == touch_k + 1:
                d = np.angle(np.exp(1j * (th - touch_at)))
                r = r - (pitch - 0.02) * np.exp(-(d / 0.18) ** 2)
            return r

        def pos(u, v, k=k, th0=th0, radius=radius):
            th = th0 + u * span
            r = radius(th)
            y = v * hgt
            return np.stack([center[0] + r * np.cos(th), y, center[2] + r * np.sin(th)], axis=1).astype(np.float32)

        def mat(u, v, P, N, k=k, th0=th0):
            th = th0 + u * span
            alb, height = papyrus(u * span * (0.55 + pitch * k), v * hgt, seed + k, tone=0.95 + 0.25 * (k % 2))
            kk = len(u)
            keep = ragged(u, v, amount=0.01, seed=seed + k, freq=30.0)
            emit = np.zeros((kk, 3), np.float32)
            if k == gap_k:
                ang = np.mod(th, 2 * np.pi)
                inside = (ang > gap[0]) & (ang < gap[1])
                keep = keep & ~inside
                near = np.minimum(np.abs(ang - gap[0]), np.abs(ang - gap[1]))
                emit = emit + (L_COPPER * 3.0)[None, :] * smoothstep(0.10, 0.0, near)[:, None]
            if k in (touch_k, touch_k + 1):
                d = np.abs(np.angle(np.exp(1j * (th - touch_at))))
                emit = emit + (L_IVORY * 1.3)[None, :] * smoothstep(0.16, 0.0, d)[:, None]
            return {"albedo": alb, "bump": height * 0.002, "keep": keep, "metal": np.zeros(kk, np.float32),
                    "shine": np.full(kk, 14.0, np.float32), "spec": np.full(kk, 0.12, np.float32), "emit": emit,
                    "rim": np.full(kk, 1.0, np.float32)}

        surfaces.append(Surface(pos, mat, tiles=(120, 12), density=0.75, bump_scale=1.0))
    # rays along the floor
    for i in range(24):
        a = math.radians(i * 15)
        d = np.array([math.cos(a), 0, math.sin(a)], dtype=np.float32)

        def rpos(u, v, d=d):
            r = 0.3 + u * 3.6
            side = np.array([-d[2], 0, d[0]], dtype=np.float32)
            return (center[None, :] + d[None, :] * r[:, None] + side[None, :] * ((v - 0.5) * 0.012)[:, None]
                    + np.array([0, 0.003, 0], np.float32)).astype(np.float32)

        def rmat(u, v, P, N):
            k = len(u)
            f = smoothstep(1.0, 0.2, u)
            return {"albedo": np.broadcast_to(L_COPPER * 0.6, (k, 3)), "metal": np.ones(k, np.float32),
                    "shine": np.full(k, 40.0, np.float32), "spec": np.full(k, 0.6, np.float32),
                    "emit": (L_COPPER * 0.5)[None, :] * f[:, None], "rim": np.zeros(k, np.float32)}

        surfaces.append(Surface(rpos, rmat, tiles=(64, 1), density=0.7, cast=False))
    surfaces.append(tube(lambda t: center[None, :] + np.array([0, 1, 0], np.float32)[None, :] * (t * 1.1)[:, None],
                         0.02, copper_metal(glow=1.0), shadow=False, up=(1, 0, 0)))
    cam = Camera(p.get("eye", [-2.6, 8.4, 8.6]), p.get("target", [0.5, -0.75, -1.0]), p.get("fov", 21), W, H)
    cam.focus = float(np.linalg.norm(center + np.array([0, 0.3, 0]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -5), (3, 2.2, 3)), dof=p.get("dof", 0.3), bloom=0.45, fog=0.012,
                 spot=((-1.4, 0.8, -0.4), 4.5), key_power=2.6)


@scene
def build_inkfilter(p, W, H, seed):
    """A surface volume as a stack of thin layers, a copper filter passing down through them, the map it makes and the
    reversed-depth control beside it. Synthetic fields only."""
    surfaces = []
    nl = p.get("layers", 7)
    base = np.array([-3.0, 0.25, -0.1], dtype=np.float32)
    w_, d_ = 2.0, 1.4
    yaw = math.radians(-22)
    rot = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]], np.float32)
    field = lambda u, v: fbm(u * 3.4 + 1, v * 2.9, 4, seed + 77)           # the hidden "ink" both maps show
    for i in range(nl):
        h = i * 0.22

        def pos(u, v, h=h):
            loc = np.stack([(u - 0.5) * w_, np.full_like(u, h), (v - 0.5) * d_], axis=1).astype(np.float32)
            return loc @ rot.T + base

        def mat(u, v, P, N, i=i):
            alb, height = papyrus(u * w_ + i * 0.37, v * d_ + i * 0.11, seed + i, tone=0.8 + 0.06 * (i % 3))
            depth_w = math.exp(-((i - nl * 0.45) / 1.6) ** 2)
            ink = smoothstep(0.55, 0.72, field(u, v)) * depth_w
            alb = alb * (1 - 0.5 * ink[:, None])
            k = len(u)
            keep = ragged(u, v, amount=0.008, seed=seed + i, freq=35.0)
            return {"albedo": alb, "bump": height * 0.002, "keep": keep, "metal": np.zeros(k, np.float32),
                    "shine": np.full(k, 14.0, np.float32), "spec": np.full(k, 0.1, np.float32),
                    "rim": np.full(k, 1.0, np.float32)}

        surfaces.append(Surface(pos, mat, tiles=(32, 24), density=0.75, bump_scale=1.0))
    probe = (np.array([0.18, 0, 0.05], np.float32) @ rot.T) + base
    surfaces.append(tube(lambda t: probe[None, :] + np.array([0, 1, 0], np.float32)[None, :] * (-0.25 + t * 2.15)[:, None],
                         0.022, copper_metal(glow=1.2), shadow=False, up=(1, 0, 0)))
    for i in range(nl):
        c = probe + np.array([0, i * 0.22 + 0.012, 0], np.float32)

        def rpos(u, v, c=c):
            th = u * 2 * np.pi
            r = 0.06 + 0.035 * v
            return (c[None, :] + np.stack([r * np.cos(th), np.zeros_like(u), r * np.sin(th)], axis=1)).astype(np.float32)

        surfaces.append(Surface(rpos, copper_metal(glow=0.8), tiles=(24, 2), density=0.7, shadow=False))
    top = probe + np.array([0, 1.9, 0], np.float32)
    link = catmull([top, top + np.array([1.2, 0.35, -0.4], np.float32), np.array([-0.55, 1.2, -0.75], np.float32)])
    surfaces.append(tube(link, 0.008, copper_metal(glow=1.6), shadow=False))
    for j, (cx, gl, rev) in enumerate(((0.4, 1.0, False), (3.1, 0.35, True))):
        cpos = np.array([cx, 0.9 + 0.1 * j, -0.7 - 1.3 * j], np.float32)
        yawj = math.radians(-30 + 6 * j)
        rj = np.array([[math.cos(yawj), 0, math.sin(yawj)], [0, 1, 0], [-math.sin(yawj), 0, math.cos(yawj)]], np.float32)
        tilt = np.array([[1, 0, 0], [0, math.cos(0.75), -math.sin(0.75)], [0, math.sin(0.75), math.cos(0.75)]], np.float32)

        def mpos(u, v, cpos=cpos, rj=rj):
            loc = np.stack([(u - 0.5) * w_, np.zeros_like(u), (v - 0.5) * d_], axis=1).astype(np.float32)
            return loc @ (rj @ tilt).T + cpos

        def mmat(u, v, P, N, gl=gl, rev=rev):
            f = field(u, v)
            t = smoothstep(0.32, 0.70, f)
            if rev:
                t = 0.35 * t + 0.3 * fbm(u * 9, v * 9, 3, seed + 5)
            col = palette_ramp(0.1 + 0.9 * t) if not rev else (L_IVORY * 0.25)[None, :] * (0.3 + t[:, None])
            edge = np.minimum(np.minimum(u, 1 - u), np.minimum(v, 1 - v))
            frame = smoothstep(0.012, 0.0, edge)
            k = len(u)
            return {"albedo": col * 0.55 * (1 - frame[:, None]) + L_COPPER * frame[:, None],
                    "emit": col * 0.55 * gl + (L_COPPER * 0.8 * gl)[None, :] * frame[:, None],
                    "metal": frame, "shine": np.full(k, 30.0, np.float32), "spec": 0.2 + 0.6 * frame,
                    "rim": np.full(k, 0.8, np.float32)}

        surfaces.append(Surface(mpos, mmat, tiles=(40, 30), density=0.7))
    cam = Camera(p.get("eye", [-4.2, 4.0, 9.6]), p.get("target", [0.3, 0.55, -0.9]), p.get("fov", 20), W, H)
    cam.focus = float(np.linalg.norm(base + np.array([0, 0.6, 0]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-5, 0, -4), (6, 2, 3)), dof=p.get("dof", 0.3), bloom=0.4, fog=0.012,
                 spot=((-2.6, 0.8, 0.4), 5.0), key_power=2.6)


@scene
def build_workbench(p, W, H, seed):
    """A still life of the tools' motifs on one bench: a small roll, a sheet with a copper surface grid, a cube with
    slices and a pair of cross-sections on a thread."""
    surfaces = []
    width = 1.2
    s, xy, s_roll, s_flat = roll_profile(turns=4.0, r_in=0.1, r_out=0.36, run=2.2, drop=0.8, wave=0.02)
    S = float(s[-1])

    def extra(u, v, ss, zz, out):
        lines = grid_lines(ss, zz, 1 / 0.12, 1 / 0.12, 0.08) & (u > s_flat / S)
        b = lines.astype(np.float32) * smoothstep(s_flat / S, s_flat / S + 0.15, u)
        out.update(albedo=out["albedo"] * (1 - b[:, None]) + (L_COPPER * 1.05)[None, :] * b[:, None],
                   metal=np.maximum(out["metal"], b), spec=out["spec"] + 0.8 * b, shine=out["shine"] + 40 * b,
                   emit=(L_COPPER * 0.35)[None, :] * b[:, None])
        return out

    place = placer(-20, (-4.1, 0, -0.1))
    surfaces.append(profile_sheet(s, xy, width, place, papyrus_material(S, width, seed, edge=0.012, extra=extra),
                                  tiles=(200, 16), bump_scale=1.0))
    surfaces += cube_part(oriented([0.2, 0.72, -0.9], yaw=30, pitch=6), seed + 5, size=0.6, detail=1.0)
    # two cross-sections on a thread
    pts = np.array([[2.5, 0.72, -0.9], [3.6, 0.70, -1.5], [4.7, 0.68, -2.1]], np.float32)
    thread = catmull(np.concatenate([pts[:1] - (pts[1] - pts[0]) * 0.8, pts, pts[-1:] + (pts[2] - pts[1]) * 0.8]))
    for k, c in enumerate(pts[:2]):
        a, e1, e2 = frame_from(pts[1] - pts[0])
        R = 0.58

        def pos(u, v, c=c, e1=e1, e2=e2):
            th = v * 2 * np.pi
            return c + (u * R)[:, None] * (np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2)

        def mat(u, v, P, N, k=k):
            th = v * 2 * np.pi
            sheet = spiral_section(u * R, th, R / 11, seed + k, gaps=0.3, wobble=0.6, thick=0.24)
            core = smoothstep(0.05, 0.015, u * R)
            kk = len(u)
            return {"albedo": (L_CHARCOAL * 0.22)[None, :] + (L_IVORY * 0.4)[None, :] * sheet[:, None],
                    "emit": (L_IVORY * 0.06)[None, :] * sheet[:, None] + (L_COPPER * 0.9)[None, :] * core[:, None],
                    "keep": u < 0.93 + 0.05 * (ring_noise(th, 0, 1.5, 0, seed + k) - 0.5),
                    "metal": np.zeros(kk, np.float32), "shine": np.full(kk, 30.0, np.float32),
                    "spec": np.full(kk, 0.2, np.float32), "rim": np.full(kk, 0.6, np.float32)}

        surfaces.append(Surface(pos, mat, tiles=(16, 48), density=0.8))
    surfaces.append(tube(thread, 0.012, copper_metal(glow=1.2), shadow=False))
    cam = Camera(p.get("eye", [-4.0, 3.5, 8.8]), p.get("target", [0.3, 0.4, -1.0]), p.get("fov", 18.5), W, H)
    cam.focus = float(np.linalg.norm(np.array([0.2, 0.72, -0.9]) - cam.eye))
    return Scene(cam, surfaces, bounds=((-6, 0, -5), (6, 2, 3)), dof=p.get("dof", 0.3), bloom=0.4, fog=0.012,
                 spot=((-2.0, 0.8, 0.2), 5.5), key_power=2.6)


@scene
def build_panels(p, W, H, seed):
    """Screenshots of a tool as glowing panels floating at an angle over the floor (a Synthetic demo when the
    screenshots show only made-up data). params: {"panels": [{"image": PATH, "center": [x, y, z], "yaw": DEG,
    "pitch": DEG, "height": H}], "eye", "target", "fov"}."""
    from PIL import Image

    surfaces = []
    for i, spec in enumerate(p["panels"]):
        img = np.asarray(Image.open(spec["image"]).convert("RGB")).astype(np.float32) / 255
        crop = spec.get("crop")
        if crop:
            x0, y0, x1, y1 = crop
            img = img[y0:y1, x0:x1]
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
