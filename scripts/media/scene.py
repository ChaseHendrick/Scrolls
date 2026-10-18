"""Procedural 3D scenes for release heroes, drawn by a small NumPy renderer.

Nothing here reads a scan, a map or a model: every surface, texture and light is made from formulas and a seed, so a
picture made from these scenes is a Concept illustration (docs/assets/README.md). The look follows the repository's
reference hero: a charcoal field, an ivory key light from the upper left, a copper rim light, no text.

How it draws: each surface is a function of (u, v). The renderer samples it densely enough that neighboring samples
land less than a pixel apart on screen (per tile of the (u, v) square), keeps the nearest sample per pixel (a point
splat z-buffer), and then shades every pixel once: wrapped diffuse and specular light from the key, a Fresnel copper
rim, an ambient term, soft shadows from a shadow map with percentage-closer filtering, a contact shadow on the floor,
depth-based cavity darkening, fog, depth of field and bloom. Output is linear RGB; hero.py tone maps and grades it.

Only numpy (and Pillow, for the letters and screenshots some scenes draw onto their surfaces).
"""

import math

import numpy as np

# ---------------------------------------------------------------------------------------------------------------------
# Color


def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


def to_linear(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float32), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055).astype(np.float32)


CHARCOAL = hex_rgb("#171A1C")
IVORY = hex_rgb("#EEE7D9")
COPPER = hex_rgb("#B77A54")
EMBER = hex_rgb("#3A2A22")
# The reference heroes' field reads warm, (19, 18, 16) to (24, 22, 20), not the cool page charcoal: the darkest
# pixels lift to SHADOW, and the floor under the key light is a warm sweep that falls to charcoal at the edges.
SHADOW = hex_rgb("#161412")
FLOOR_WARM = hex_rgb("#1E1A17")
L_CHARCOAL, L_IVORY, L_COPPER, L_EMBER = (to_linear(c) for c in (CHARCOAL, IVORY, COPPER, EMBER))
L_SHADOW, L_FLOOR_WARM = to_linear(SHADOW), to_linear(FLOOR_WARM)

# ---------------------------------------------------------------------------------------------------------------------
# Noise


def _hash(ix, iy, seed):
    h = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263 + (seed * 2654435761 % 4294967296)) \
        & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (((h ^ (h >> 16)) & 0xFFFF) / 65535.0).astype(np.float32)


def value_noise(x, y, seed=0):
    """Smooth value noise in [0, 1] at points (x, y)."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    ix, iy = np.floor(x), np.floor(y)
    fx, fy = (x - ix).astype(np.float32), (y - iy).astype(np.float32)
    ux, uy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(ix, iy, seed), _hash(ix + 1, iy, seed)
    c, d = _hash(ix, iy + 1, seed), _hash(ix + 1, iy + 1, seed)
    return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy


def fbm(x, y, octaves=4, seed=0, lacunarity=2.0, gain=0.5):
    """Fractal sum of value noise, normalized to about [0, 1]."""
    total, amp, norm = 0.0, 1.0, 0.0
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    for o in range(octaves):
        total = total + amp * value_noise(x, y, seed + 101 * o)
        norm += amp
        amp *= gain
        x, y = x * lacunarity + 17.13, y * lacunarity + 5.71
    return (total / norm).astype(np.float32)


def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, dtype=np.float32) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------------------------------------------------------------
# Blur (separable box blurs; three passes approximate a Gaussian)


def _box1d(a, r, axis):
    if r < 1:
        return a
    a = np.swapaxes(a, 0, axis)
    pad = np.concatenate([np.repeat(a[:1], r + 1, axis=0), a, np.repeat(a[-1:], r, axis=0)], axis=0)
    c = np.cumsum(pad, axis=0, dtype=np.float64)
    out = ((c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)).astype(np.float32)
    return np.swapaxes(out, 0, axis)


def blur(a, sigma):
    """Approximate Gaussian blur of a 2D or 3D (H, W, C) array over its first two axes."""
    if sigma <= 0.3:
        return a.astype(np.float32, copy=False)
    r = max(1, int(round(math.sqrt(12 * sigma * sigma / 3 + 1) / 2)))
    out = a.astype(np.float32, copy=False)
    for _ in range(3):
        out = _box1d(_box1d(out, r, 0), r, 1)
    return out


def downsample2(a):
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    a = a[:h, :w]
    return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])


def upsample_to(a, shape):
    ys = (np.arange(shape[0]) + 0.5) * a.shape[0] / shape[0] - 0.5
    xs = (np.arange(shape[1]) + 0.5) * a.shape[1] / shape[1] - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, a.shape[0] - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, a.shape[1] - 1)
    y1, x1 = np.minimum(y0 + 1, a.shape[0] - 1), np.minimum(x0 + 1, a.shape[1] - 1)
    fy = np.clip(ys - y0, 0, 1).astype(np.float32)[:, None]
    fx = np.clip(xs - x0, 0, 1).astype(np.float32)[None, :]
    if a.ndim == 3:
        fy, fx = fy[..., None], fx[..., None]
    top = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx
    bot = a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    return (top * (1 - fy) + bot * fy).astype(np.float32)


def wide_blur(a, sigma):
    """Blur with a large sigma by blurring a half-size copy (or smaller) and scaling it back up."""
    level, small = 0, a.astype(np.float32, copy=False)
    while sigma / (2 ** level) > 8 and min(small.shape[:2]) > 32:
        small = downsample2(small)
        level += 1
    small = blur(small, sigma / (2 ** level))
    return small if level == 0 else upsample_to(small, a.shape[:2])


# ---------------------------------------------------------------------------------------------------------------------
# Geometry helpers


def normalize(v, axis=-1):
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.maximum(n, 1e-12)


def rot_y(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]], dtype=np.float32)


def rot_x(deg):
    a = math.radians(deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]], dtype=np.float32)


def rot_z(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]], dtype=np.float32)


class Camera:
    """A pinhole camera looking from eye at target, y up; fov is the vertical field of view in degrees."""

    def __init__(self, eye, target, fov, width, height, up=(0, 1, 0), focus=None, aperture=0.0):
        self.eye = np.asarray(eye, dtype=np.float32)
        f = normalize(np.asarray(target, dtype=np.float32) - self.eye)
        r = normalize(np.cross(f, np.asarray(up, dtype=np.float32)))
        self.f, self.r, self.u = f, r, np.cross(r, f).astype(np.float32)
        self.width, self.height = width, height
        self.focal = (height / 2) / math.tan(math.radians(fov) / 2)
        self.cx, self.cy = width / 2, height / 2
        self.focus = float(focus) if focus else float(np.linalg.norm(np.asarray(target) - self.eye))
        self.aperture = aperture

    def to_camera(self, p):
        d = p - self.eye
        return d @ self.r, d @ self.u, d @ self.f

    def project(self, p):
        x, y, z = self.to_camera(p)
        zs = np.maximum(z, 1e-6)
        return self.cx + self.focal * x / zs, self.cy - self.focal * y / zs, z

    def rays(self):
        """Per-pixel view directions, scaled so that the camera-space depth along each ray equals the distance t."""
        xs = (np.arange(self.width, dtype=np.float32) + 0.5 - self.cx) / self.focal
        ys = -(np.arange(self.height, dtype=np.float32) + 0.5 - self.cy) / self.focal
        d = (self.f[None, None, :] + xs[None, :, None] * self.r[None, None, :]
             + ys[:, None, None] * self.u[None, None, :])
        return d.astype(np.float32)


# ---------------------------------------------------------------------------------------------------------------------
# Surfaces and materials


class Surface:
    """A parametric surface: position(u, v) -> (n, 3) and material(u, v, p, n) -> dict of per-sample arrays.

    The material returns "albedo" (n, 3, linear RGB) and optionally "metal" (0 to 1), "shine" (specular exponent),
    "spec" (specular strength), "emit" (n, 3, linear radiance), "keep" (bool mask: drop samples, for holes and ragged
    edges), "bump" (a height field used to tilt normals) and "rim" (scale of the copper rim light). A material may
    carry a bump_fn(u, v) attribute that returns a height field alone; the renderer then takes the normal's finite
    differences from it (all three samples) instead of evaluating the whole material twice more.
    """

    def __init__(self, position, material, u=(0.0, 1.0), v=(0.0, 1.0), tiles=(48, 48), density=0.7,
                 shadow=True, max_per_tile=800, bump_scale=0.0, normal=None, cast=True):
        self.position, self.material = position, material
        self.u, self.v, self.tiles, self.density = u, v, tiles, density
        self.shadow, self.cast, self.max_per_tile = shadow, cast, max_per_tile
        self.bump_scale, self.normal = bump_scale, normal

    def normals(self, uu, vv, p, eps=1e-4):
        if self.normal is not None:
            return normalize(self.normal(uu, vv, p))
        du = (self.u[1] - self.u[0]) * eps
        dv = (self.v[1] - self.v[0]) * eps
        pu = self.position(uu + du, vv) - self.position(uu - du, vv)
        pv = self.position(uu, vv + dv) - self.position(uu, vv - dv)
        n = np.cross(pu, pv)
        return normalize(n), normalize(pu), normalize(pv)

    def plan(self, cam):
        """Per tile of the (u, v) square, how many samples along u and v keep neighbors under `density` pixels."""
        tu, tv = self.tiles
        us = np.linspace(self.u[0], self.u[1], tu + 1, dtype=np.float32)
        vs = np.linspace(self.v[0], self.v[1], tv + 1, dtype=np.float32)
        gu, gv = np.meshgrid(us, vs, indexing="ij")
        p = self.position(gu.ravel(), gv.ravel())
        sx, sy, z = cam.project(p)
        sx, sy, z = (a.reshape(tu + 1, tv + 1) for a in (sx, sy, z))
        front = z > 0.05
        du = np.hypot(np.diff(sx, axis=0), np.diff(sy, axis=0))          # (tu, tv+1)
        dv = np.hypot(np.diff(sx, axis=1), np.diff(sy, axis=1))          # (tu+1, tv)
        lu = np.maximum(du[:, :-1], du[:, 1:])
        lv = np.maximum(dv[:-1, :], dv[1:, :])
        ok = front[:-1, :-1] & front[1:, :-1] & front[:-1, 1:] & front[1:, 1:]
        inside = ((sx > -cam.width * 0.2) & (sx < cam.width * 1.2) & (sy > -cam.height * 0.3)
                  & (sy < cam.height * 1.3))
        vis = inside[:-1, :-1] | inside[1:, :-1] | inside[:-1, 1:] | inside[1:, 1:]
        # Curved tiles bend between corners: oversample a little more than the corner spacing says.
        nu = np.clip(np.ceil(lu * 1.15 / self.density), 1, self.max_per_tile).astype(np.int64)
        nv = np.clip(np.ceil(lv * 1.15 / self.density), 1, self.max_per_tile).astype(np.int64)
        nu[~(ok & vis)] = 0
        nv[~(ok & vis)] = 0
        return us, vs, nu, nv

    def samples(self, us, vs, nu, nv, rng, budget=2_500_000):
        """Yield (u, v) arrays of jittered samples, at most about `budget` per batch."""
        tu, tv = nu.shape
        counts = (nu * nv).ravel()
        order = np.nonzero(counts)[0]
        start = 0
        while start < len(order):
            cum = np.cumsum(counts[order[start:]])
            stop = start + max(1, int(np.searchsorted(cum, budget)))
            cells = order[start:stop]
            start = stop
            c = counts[cells]
            cell = np.repeat(cells, c)
            first = np.repeat(np.cumsum(c) - c, c)
            k = np.arange(cell.size, dtype=np.int64) - first
            iu, iv = cell // tv, cell % tv
            nuc, nvc = nu.ravel()[cell], nv.ravel()[cell]
            ku, kv = k % nuc, k // nuc
            ju = rng.random(cell.size, dtype=np.float32)
            jv = rng.random(cell.size, dtype=np.float32)
            u = us[iu] + (us[iu + 1] - us[iu]) * ((ku + ju) / nuc)
            v = vs[iv] + (vs[iv + 1] - vs[iv]) * ((kv + jv) / nvc)
            yield u.astype(np.float32), v.astype(np.float32)


def ridges(x, y, octaves, seed, sharp):
    """Thin bright lines where fractal noise crosses its middle: fibers, when y is stretched against x."""
    n = fbm(x, y, octaves, seed)
    return (1 - np.clip(np.abs(2 * n - 1) * 1.6, 0, 1)) ** sharp


def papyrus(u, v, seed=0, scale=1.0, tone=1.0, char=0.0, detail=True):
    """Albedo and bump height of a procedural carbonized papyrus sheet at (u, v) in sheet units.

    Long fibers along u in strips of uneven tone (papyrus is pith strips laid side by side) with narrow gaps between
    strips, a fainter layer across them, char mottling and pitting. Nothing in it is a dark stroke: no mark here may
    look like ink. char (0 to 1) darkens it toward
    black-brown. detail=False returns only the height, for bump mapping."""
    x, y = u * scale, v * scale
    strands = ridges(x * 0.3, y * 48, 2, seed, 2.5)                     # fibers along u
    fine = ridges(x * 0.6 + 3.1, y * 130, 1, seed + 7, 2.0)
    strip = fbm(x * 0.25, y * 7.0, 2, seed + 11)                        # the pith strips, each its own tone
    across = ridges(x * 38, y * 0.5, 2, seed + 13, 6.0)                 # the lower layer, faint
    split = smoothstep(0.80, 0.95, ridges(x * 0.12, y * 16, 1, seed + 41, 1.0))   # gaps between strips, along u
    height = 0.6 * strands + 0.25 * fine + 0.35 * strip + 0.08 * across - 0.6 * split
    if not detail:
        return height.astype(np.float32)
    mott = fbm(x * 1.2, y * 4.0, 3, seed + 29)                          # char mottling, stretched along the fibers
    pits = smoothstep(0.74, 0.86, fbm(x * 9, y * 40, 2, seed + 31)) * smoothstep(0.5, 0.7, mott)
    t = (0.40 + 0.26 * strands + 0.10 * fine + 0.22 * (strip - 0.5) + 0.04 * across
         - 0.12 * smoothstep(0.5, 0.85, mott) - 0.10 * pits - 0.18 * split)
    t = np.clip(t, 0, 1)[:, None]
    dark = np.array([0.036, 0.030, 0.025], dtype=np.float32)
    mid = np.array([0.095, 0.080, 0.066], dtype=np.float32)
    light = np.array([0.27, 0.236, 0.195], dtype=np.float32)
    alb = np.where(t < 0.42, dark + (mid - dark) * (t / 0.42), mid + (light - mid) * ((t - 0.42) / 0.58))
    alb = alb * (1 - 0.65 * char) * tone
    height = height - 0.4 * pits + 0.2 * mott
    return alb.astype(np.float32), height.astype(np.float32)


def ragged(u, v, edge_u=(0.0, 1.0), edge_v=(0.0, 1.0), amount=0.012, seed=0, freq=60.0):
    """Keep mask with frayed edges: samples near the (u, v) borders are dropped where noise says so, with a few
    fiber tufts that reach further in, so an edge reads as torn papyrus rather than a saw blade."""
    def depth(a, b, sd):
        tear = fbm(a * freq, b * 3, 3, sd) * amount * 2
        tufts = smoothstep(0.72, 0.95, value_noise(a * freq * 5, b * 2, sd + 1)) * amount * 2.5
        return tear + tufts

    return ((v - edge_v[0]) > depth(u, v, seed)) & ((edge_v[1] - v) > depth(u + 9.3, v, seed + 9)) & \
           ((u - edge_u[0]) > depth(v, u, seed + 5)) & ((edge_u[1] - u) > depth(v + 4.1, u, seed + 11))


def grid_lines(a, b, na, nb, width):
    """Mask of grid lines, na lines along a and nb along b, each `width` of a cell wide."""
    fa = np.abs((a * na) % 1.0 - 0.5)
    fb = np.abs((b * nb) % 1.0 - 0.5)
    return (fa > 0.5 - width) | (fb > 0.5 - width)


def tube(curve, radius, material, n=(400, 24), t=(0.0, 1.0), up=(0, 1, 0), **kw):
    """A tube of the given radius around curve(t) -> (n, 3)."""
    up = np.asarray(up, dtype=np.float32)

    def frame(tt):
        e = 1e-3
        tan = normalize(curve(tt + e) - curve(tt - e))
        a = np.cross(tan, up)
        bad = np.linalg.norm(a, axis=1) < 1e-3
        a[bad] = np.cross(tan[bad], np.array([1, 0, 0], dtype=np.float32))
        a = normalize(a)
        b = normalize(np.cross(tan, a))
        return a, b

    def pos(tt, vv):
        a, b = frame(tt)
        ang = (vv * 2 * np.pi)[:, None]
        r = radius(tt)[:, None] if callable(radius) else radius
        return curve(tt) + r * (np.cos(ang) * a + np.sin(ang) * b)

    def nrm(tt, vv, p):
        a, b = frame(tt)
        ang = (vv * 2 * np.pi)[:, None]
        return np.cos(ang) * a + np.sin(ang) * b

    return Surface(pos, material, u=t, v=(0.0, 1.0), tiles=(max(8, n[0] // 8), 4), normal=nrm, **kw)


def sphere(center, radius, material, **kw):
    c = np.asarray(center, dtype=np.float32)

    def pos(uu, vv):
        th, ph = uu * 2 * np.pi, vv * np.pi
        return c + radius * np.stack([np.sin(ph) * np.cos(th), np.cos(ph), np.sin(ph) * np.sin(th)], axis=1)

    def nrm(uu, vv, p):
        return p - c

    return Surface(pos, material, tiles=(16, 8), normal=nrm, **kw)


def plain(albedo, metal=0.0, shine=24.0, spec=0.25, emit=None, rim=1.0):
    """A material of one color."""
    albedo = np.asarray(albedo, dtype=np.float32)

    def mat(u, v, p, n):
        k = len(u)
        out = {"albedo": np.broadcast_to(albedo, (k, 3)), "metal": np.full(k, metal, np.float32),
               "shine": np.full(k, shine, np.float32), "spec": np.full(k, spec, np.float32),
               "rim": np.full(k, rim, np.float32)}
        if emit is not None:
            out["emit"] = np.broadcast_to(np.asarray(emit, dtype=np.float32), (k, 3))
        return out

    return mat


def copper_metal(glow=0.0):
    return plain(L_COPPER * 1.1, metal=1.0, shine=60.0, spec=1.0, emit=L_COPPER * glow if glow else None, rim=1.4)


# ---------------------------------------------------------------------------------------------------------------------
# The renderer


class Scene:
    def __init__(self, camera, surfaces, key=(-0.42, 0.78, 0.62), rim=(0.75, 0.35, -0.6), key_power=3.2,
                 rim_power=1.6, ambient=0.06, floor=True, floor_y=0.0, fog=0.02, bounds=None, shadow_soft=2.5,
                 contact=0.55, cavity=0.6, bloom=0.35, dof=1.0, background=None, floor_tone=1.0, exposure=1.0,
                 spot=None, backdrop=0.85):
        self.camera, self.surfaces = camera, surfaces
        self.key, self.rim = normalize(np.asarray(key, dtype=np.float32)), normalize(np.asarray(rim, dtype=np.float32))
        self.key_power, self.rim_power, self.ambient = key_power, rim_power, ambient
        self.floor, self.floor_y, self.fog, self.bounds = floor, floor_y, fog, bounds
        self.shadow_soft, self.contact, self.cavity, self.bloom, self.dof = shadow_soft, contact, cavity, bloom, dof
        self.background, self.floor_tone, self.exposure = background, floor_tone, exposure
        self.backdrop = backdrop          # strength of the warm glow on the backdrop at the upper left
        # spot: (center xyz, radius): the key light pools around center and falls to 30 % far from it.
        self.spot = spot


def spot_falloff(scene, p):
    if scene.spot is None:
        return np.ones(len(p), dtype=np.float32)
    c, r = np.asarray(scene.spot[0], dtype=np.float32), float(scene.spot[1])
    d2 = np.sum((p - c[None, :]) ** 2, axis=1) / (r * r)
    return (0.3 + 0.7 * np.exp(-d2)).astype(np.float32)


class _LightMap:
    """An orthographic depth map seen from the key light, for shadows."""

    def __init__(self, direction, bounds, res):
        w = direction
        a = normalize(np.cross(np.array([0, 1, 0], dtype=np.float32), w))
        if np.linalg.norm(a) < 1e-3:
            a = np.array([1, 0, 0], dtype=np.float32)
        b = normalize(np.cross(w, a))
        self.a, self.b, self.w = a, b, w
        lo, hi = np.asarray(bounds[0], dtype=np.float32), np.asarray(bounds[1], dtype=np.float32)
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])],
                           dtype=np.float32)
        s, t = corners @ a, corners @ b
        self.s0, self.s1, self.t0, self.t1 = s.min(), s.max(), t.min(), t.max()
        span = max(self.s1 - self.s0, self.t1 - self.t0)
        self.res = res
        self.scale = (res - 1) / span
        self.depth = np.full((res, res), -np.inf, dtype=np.float32)

    def coords(self, p):
        return (p @ self.a - self.s0) * self.scale, (p @ self.b - self.t0) * self.scale, p @ self.w

    def splat(self, p):
        x, y, d = self.coords(p)
        ix, iy = np.round(x).astype(np.int64), np.round(y).astype(np.int64)
        ok = (ix >= 0) & (iy >= 0) & (ix < self.res) & (iy < self.res)
        np.maximum.at(self.depth.ravel(), iy[ok] * self.res + ix[ok], d[ok])

    def finish(self):
        # Fill pinholes between samples: a 3 x 3 maximum.
        d = self.depth
        pad = np.pad(d, 1, mode="edge")
        m = d.copy()
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                m = np.maximum(m, pad[dy:dy + d.shape[0], dx:dx + d.shape[1]])
        self.depth = m

    def visibility(self, p, soft, bias):
        x, y, d = self.coords(p)
        vis = np.zeros(len(p), dtype=np.float32)
        offs = [(0, 0)] + [(math.cos(a) * r, math.sin(a) * r) for r in (0.5, 1.0) for a in
                           np.linspace(0, 2 * np.pi, 8, endpoint=False) + r]
        for ox, oy in offs:
            ix = np.clip(np.round(x + ox * soft).astype(np.int64), 0, self.res - 1)
            iy = np.clip(np.round(y + oy * soft).astype(np.int64), 0, self.res - 1)
            vis += (d >= self.depth[iy, ix] - bias).astype(np.float32)
        return vis / len(offs)


class _Coverage:
    """A top-down map of how much geometry hangs low over the floor, for contact shadows."""

    def __init__(self, bounds, res=1024, floor_y=0.0, reach=0.6):
        lo, hi = bounds
        self.x0, self.z0 = lo[0], lo[2]
        span = max(hi[0] - lo[0], hi[2] - lo[2])
        self.scale = (res - 1) / span
        self.res, self.floor_y, self.reach = res, floor_y, reach
        self.map = np.zeros((res, res), dtype=np.float32)

    def splat(self, p):
        h = p[:, 1] - self.floor_y
        w = np.exp(-np.maximum(h, 0) / self.reach).astype(np.float32)
        ix = np.round((p[:, 0] - self.x0) * self.scale).astype(np.int64)
        iz = np.round((p[:, 2] - self.z0) * self.scale).astype(np.int64)
        ok = (ix >= 0) & (iz >= 0) & (ix < self.res) & (iz < self.res) & (w > 0.02)
        np.maximum.at(self.map.ravel(), iz[ok] * self.res + ix[ok], w[ok])

    def finish(self, sigma_world=0.18):
        self.map = blur(self.map, sigma_world * self.scale)

    def lookup(self, p):
        ix = np.clip(np.round((p[:, 0] - self.x0) * self.scale).astype(np.int64), 0, self.res - 1)
        iz = np.clip(np.round((p[:, 2] - self.z0) * self.scale).astype(np.int64), 0, self.res - 1)
        inside = ((p[:, 0] - self.x0) * self.scale >= 0) & ((p[:, 0] - self.x0) * self.scale < self.res) & \
                 ((p[:, 2] - self.z0) * self.scale >= 0) & ((p[:, 2] - self.z0) * self.scale < self.res)
        return np.where(inside, self.map[iz, ix], 0.0)


def background(scene, w, h):
    """The seamless charcoal backdrop with a warm ivory glow at the upper left (linear RGB)."""
    if scene.background is not None:
        return scene.background(w, h)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x, y = xx / w, yy / h
    d = np.sqrt(((x - 0.0) / 0.5) ** 2 + ((y + 0.12) / 0.85) ** 2)
    glow = np.exp(-d * d * 1.5)[..., None]
    base = L_SHADOW * (0.8 + 0.3 * (1 - x))[..., None]
    return (base + glow * (to_linear(np.array([0.40, 0.345, 0.285])) * scene.backdrop)).astype(np.float32)


def render(scene, seed=0, progress=None):
    """Render a Scene to a linear RGB float array of the camera's size."""
    cam = scene.camera
    W, H = cam.width, cam.height
    rng = np.random.default_rng(seed)
    depth = np.full(H * W, np.inf, dtype=np.float32)
    normal = np.zeros((H * W, 3), dtype=np.float32)
    albedo = np.zeros((H * W, 3), dtype=np.float32)
    emit = np.zeros((H * W, 3), dtype=np.float32)
    mat = np.zeros((H * W, 4), dtype=np.float32)        # metal, shine, spec, rim
    receives = np.ones(H * W, dtype=bool)
    bounds = scene.bounds or ((-6, 0, -6), (6, 4, 6))
    light = _LightMap(scene.key, bounds, 2048)
    cover = _Coverage(bounds, floor_y=scene.floor_y)
    for si, surf in enumerate(scene.surfaces):
        us, vs, nu, nv = surf.plan(cam)
        for u, v in surf.samples(us, vs, nu, nv, rng):
            p = surf.position(u, v).astype(np.float32)
            got = surf.normals(u, v, p)
            if isinstance(got, tuple):
                n, tu, tv = got
            else:
                n, tu, tv = got, None, None
            m = surf.material(u, v, p, n)
            keep = m.get("keep")
            if keep is not None:
                keep = np.asarray(keep, dtype=bool)
                u, v, p, n = u[keep], v[keep], p[keep], n[keep]
                if tu is not None:
                    tu, tv = tu[keep], tv[keep]
                m = {k: (np.asarray(val)[keep] if k != "keep" else None) for k, val in m.items()}
            if len(p) == 0:
                continue
            if surf.bump_scale and m.get("bump") is not None and tu is not None:
                # Tilt the normal along the height field's gradient (finite differences in u and v).
                e = 2e-4
                hb = np.asarray(m["bump"], dtype=np.float32)
                fast = getattr(surf.material, "bump_fn", None)     # height only, cheaper than the whole material
                if fast is not None:
                    h0 = fast(u, v)
                    gu = (fast(u + e, v) - h0) / e
                    gv = (fast(u, v + e) - h0) / e
                else:
                    gu = (np.asarray(surf.material(u + e, v, p, n)["bump"], dtype=np.float32) - hb) / e
                    gv = (np.asarray(surf.material(u, v + e, p, n)["bump"], dtype=np.float32) - hb) / e
                n = normalize(n - surf.bump_scale * (gu[:, None] * tu + gv[:, None] * tv))
            if surf.cast:
                light.splat(p)
                cover.splat(p)
            sx, sy, z = cam.project(p)
            ix, iy = np.floor(sx).astype(np.int64), np.floor(sy).astype(np.int64)
            ok = (ix >= 0) & (iy >= 0) & (ix < W) & (iy < H) & (z > 0.05)
            pix = (iy * W + ix)[ok]
            zz = z[ok]
            idx = np.nonzero(ok)[0]
            order = np.lexsort((zz, pix))
            pix_s = pix[order]
            first = np.ones(len(pix_s), dtype=bool)
            first[1:] = pix_s[1:] != pix_s[:-1]
            sel = order[first]
            pp, zsel = pix[sel], zz[sel]
            closer = zsel < depth[pp]
            sel, pp, zsel = sel[closer], pp[closer], zsel[closer]
            src = idx[sel]
            depth[pp] = zsel
            normal[pp] = n[src]
            albedo[pp] = np.asarray(m["albedo"], dtype=np.float32)[src]
            k = len(p)
            mat[pp, 0] = np.asarray(m.get("metal", np.zeros(k)), dtype=np.float32)[src]
            mat[pp, 1] = np.asarray(m.get("shine", np.full(k, 24.0)), dtype=np.float32)[src]
            mat[pp, 2] = np.asarray(m.get("spec", np.full(k, 0.25)), dtype=np.float32)[src]
            mat[pp, 3] = np.asarray(m.get("rim", np.ones(k)), dtype=np.float32)[src]
            e_ = m.get("emit")
            emit[pp] = 0.0 if e_ is None else np.asarray(e_, dtype=np.float32)[src]
            receives[pp] = surf.shadow
        if progress:
            progress(f"surface {si + 1}/{len(scene.surfaces)}")
    light.finish()
    cover.finish()

    rays = cam.rays().reshape(-1, 3)
    hit = np.isfinite(depth)
    # The floor: where a ray meets y = floor_y in front of any surface.
    img = np.zeros((H * W, 3), dtype=np.float32)
    bg = background(scene, W, H).reshape(-1, 3)
    floor_hit = np.zeros(H * W, dtype=bool)
    if scene.floor:
        dy = rays[:, 1]
        t = np.where(dy < -1e-6, (scene.floor_y - cam.eye[1]) / np.where(dy < -1e-6, dy, -1), np.inf)
        floor_hit = np.isfinite(t) & (t < depth)
        depth = np.where(floor_hit, t, depth).astype(np.float32)
    pos = cam.eye[None, :] + rays * np.where(np.isfinite(depth), depth, 0)[:, None]
    view = normalize(cam.eye[None, :] - pos)

    # Surfaces.
    s = hit & ~floor_hit
    if s.any():
        n = normal[s]
        v = view[s]
        flip = np.sum(n * v, axis=1) < 0
        n[flip] *= -1
        p = pos[s]
        vis = light.visibility(p + n * 0.004, scene.shadow_soft, bias=0.01)
        vis = np.where(receives[s], vis, 1.0) * spot_falloff(scene, p)
        ndl = np.sum(n * scene.key, axis=1)
        wrap = np.clip((ndl + 0.25) / 1.25, 0, 1)
        h = normalize(scene.key[None, :] + v)
        ndh = np.clip(np.sum(n * h, axis=1), 0, 1)
        ndv = np.clip(np.sum(n * v, axis=1), 0, 1)
        metal, shine, spec, rimk = mat[s, 0], mat[s, 1], mat[s, 2], mat[s, 3]
        alb = albedo[s]
        key_col = L_IVORY * scene.key_power
        diffuse = alb * (1 - 0.85 * metal)[:, None] * (wrap * vis)[:, None] * key_col
        f0 = (0.04 * (1 - metal))[:, None] + alb * metal[:, None]
        fres = f0 + (1 - f0) * ((1 - ndv) ** 5)[:, None] * 0.6
        specular = fres * (spec * (ndh ** shine) * (shine + 2) / 8 * np.clip(ndl, 0, 1) * vis)[:, None] * key_col
        rim_l = np.clip(np.sum(n * scene.rim, axis=1) + 0.1, 0, 1)
        rim = (L_COPPER * scene.rim_power) * (rimk * ((1 - ndv) ** 4) * rim_l)[:, None]
        rim = rim * (0.35 + 0.65 * alb.mean(axis=1, keepdims=True) / 0.3).clip(0.3, 1.6)
        sky = 0.5 + 0.5 * n[:, 1]
        amb = alb * (scene.ambient * (0.6 * sky + 0.4))[:, None] * (L_IVORY * 0.7 + L_COPPER * 0.3)
        img[s] = diffuse + specular + rim + amb + emit[s]

    # The floor.
    if floor_hit.any():
        p = pos[floor_hit]
        vis = light.visibility(p + np.array([0, 0.004, 0], dtype=np.float32), scene.shadow_soft * 1.6, bias=0.01)
        vis = vis * spot_falloff(scene, p)
        occl = np.clip(1 - scene.contact * cover.lookup(p), 0.15, 1)
        ndl = max(scene.key[1], 0.0)
        # Light pools near the subject and falls off away from it.
        lo, hi = np.asarray(bounds[0]), np.asarray(bounds[1])
        cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
        fall = np.exp(-(((p[:, 0] - cx) / (hi[0] - lo[0] + 1e-6)) ** 2 * 2.2
                        + ((p[:, 2] - cz) / (hi[2] - lo[2] + 1e-6)) ** 2 * 2.2))
        # A warm sweep under the light that cools to charcoal away from it.
        warm = (0.25 + 0.75 * fall)[:, None]
        alb = (L_FLOOR_WARM * 1.45 * warm + L_CHARCOAL * (1 - warm)) * scene.floor_tone
        col = alb * (ndl * scene.key_power * vis * (0.35 + 0.65 * fall))[:, None] * L_IVORY / 0.9
        col = col * occl[:, None] + alb * scene.ambient * occl[:, None]
        # A soft glossy sheen of the key light on the floor.
        v = view[floor_hit]
        refl = v * np.array([-1, 1, -1], dtype=np.float32)
        sheen = np.clip(np.sum(refl * scene.key, axis=1), 0, 1) ** 20 * 0.08 * vis
        img[floor_hit] = col + (sheen * occl)[:, None] * L_IVORY
    # The backdrop: where nothing was hit, and as fog with distance.
    img[~np.isfinite(depth)] = bg[~np.isfinite(depth)]
    dist = np.where(np.isfinite(depth), depth, 1e6)
    fogk = (1 - np.exp(-scene.fog * np.maximum(dist - cam.focus * 0.6, 0)))[:, None]
    img = img * (1 - fogk) + bg * fogk

    img = img.reshape(H, W, 3)
    depth2 = np.where(np.isfinite(depth), depth, cam.focus * 50).reshape(H, W).astype(np.float32)
    # Cavities: pixels farther than their neighborhood sit in a crease and get less ambient and key light.
    if scene.cavity:
        near = wide_blur(depth2, W / 300)
        crease = np.clip((depth2 - near) / (0.02 * cam.focus), 0, 1)
        surf_mask = (hit & ~floor_hit).reshape(H, W)
        img = img * (1 - scene.cavity * 0.6 * (crease * surf_mask))[..., None]
    if scene.dof:
        coc = np.abs(1 / depth2 - 1 / cam.focus) * cam.focus      # 0 at the focus distance
        coc = np.clip(coc * scene.dof * 2.2, 0, 1)
        b1 = wide_blur(img, W / 900)
        b2 = wide_blur(img, W / 320)
        t1 = np.clip(coc * 2, 0, 1)[..., None]
        t2 = np.clip(coc * 2 - 1, 0, 1)[..., None]
        img = img * (1 - t1) + b1 * t1
        img = img * (1 - t2) + b2 * t2
    if scene.bloom:
        lum = img.mean(axis=2, keepdims=True)
        bright = np.clip(img * (lum > 0.6) * 1.0, 0, 8) * np.clip((lum - 0.6) / 0.6, 0, 1)
        glow = 0.6 * wide_blur(bright, W / 400) + 0.4 * wide_blur(bright, W / 90)
        img = img + scene.bloom * glow
    return (img * scene.exposure).astype(np.float32)
