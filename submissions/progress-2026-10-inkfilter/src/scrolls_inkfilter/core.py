"""Fixed image filters for a surface-volume window (Z,H,W).

The face-mix recipe combines front-to-back alpha compositing, a papyrus edge
step, and local texture. It assumes the high-z face is the ink side; always
inspect and score its reverse-depth control. Constants were selected on public
labels and frozen before the separate-window confirmation in evidence/README.md.
Only NumPy is required. An ink map is filter output, not a reading.
"""

_FACE_MIX = [
    {"kind": "composite", "face": "bot", "half": 20, "lo": 0.45, "hi": 0.60, "opacity": 1.0},
    {"kind": "step", "face": "bot", "depths": [2, 1, 0, -1]},
    {"kind": "texture", "face": "bot", "depths": [2], "window": 3},
]
RECIPES = {
    "face-mix": {"components": _FACE_MIX, "smooth": 48, "background": 192},
    # the same map smoothed less, for looking at strokes; not the scored recipe
    "face-mix-sharp": {"components": _FACE_MIX, "smooth": 8, "background": 192},
}
DEFAULT_RECIPE = "face-mix"
PRESMOOTH = (1.0, 1.5, 1.5)     # z, y, x voxels: the Gaussian before the threshold and the "bright" samples
TEXTURE_WINDOW = 5              # px: box side for the local mean and the local RMS of "texture"
KINDS = ("bright", "step", "texture", "composite")
COMPOSITE = {"half": 20, "lo": 0.45, "hi": 0.60, "opacity": 1.0, "cutoff": 1.0}   # VC3D alpha compositing defaults here
FACES = ("bot", "top")


class InkFilterError(ValueError):
    pass


def _np():
    try:
        import numpy as np
    except ImportError as exc:  # the core kit is standard library only
        raise InkFilterError("numpy is required for kit inkfilter") from exc
    return np


# ---------------------------------------------------------------- filters (numpy only)

def gaussian_kernel(sigma, truncate=4.0):
    """Normalized 1D Gaussian taps of radius int(truncate * sigma + 0.5), as scipy.ndimage builds them."""
    np = _np()
    r = int(truncate * float(sigma) + 0.5)
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (x / float(sigma)) ** 2)
    return (k / k.sum()).astype(np.float32)


def _correlate1d(a, taps, axis):
    np = _np()
    r = len(taps) // 2
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="symmetric")   # numpy mirrors again when the kernel is longer than the axis
    out = np.zeros(a.shape, np.float32)
    for i, w in enumerate(taps):
        sl = [slice(None)] * a.ndim
        sl[axis] = slice(i, i + a.shape[axis])
        out += np.float32(w) * p[tuple(sl)]
    return out


def gaussian(a, sigma):
    """Gaussian smoothing of a float32 copy of `a`; `sigma` is one number or one per axis (0 leaves an axis)."""
    np = _np()
    out = np.asarray(a, dtype=np.float32)
    sig = [sigma] * out.ndim if not isinstance(sigma, (tuple, list)) else list(sigma)
    if len(sig) != out.ndim:
        raise InkFilterError(f"sigma {sigma} does not fit an array of {out.ndim} dimensions")
    for ax, s in enumerate(sig):
        if s and s > 0:
            out = _correlate1d(out, gaussian_kernel(s), ax)
    return out


def box(img, size):
    """Mean over a size x size window (odd size), mirrored edges, by cumulative sums."""
    np = _np()
    if size < 1 or size % 2 == 0:
        raise InkFilterError("the box size must be a positive odd number")
    r = size // 2
    p = np.pad(np.asarray(img, dtype=np.float64), r, mode="symmetric")
    c = np.cumsum(np.cumsum(p, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = img.shape
    s = c[size:size + h, size:size + w] - c[:h, size:size + w] - c[size:size + h, :w] + c[:h, :w]
    return (s / (size * size)).astype(np.float32)


def texture(img, size=TEXTURE_WINDOW):
    """Local root-mean-square of the detail left after removing the local mean, both over size x size boxes."""
    np = _np()
    img = np.asarray(img, dtype=np.float32)
    return np.sqrt(np.maximum(box((img - box(img, size)) ** 2, size), 0)).astype(np.float32)


def otsu(values, bins=256):
    """Otsu's threshold of a 1D sample (bin centres of a `bins` histogram)."""
    np = _np()
    h, e = np.histogram(values, bins=bins)
    c = (e[:-1] + e[1:]) / 2
    w0 = np.cumsum(h)
    w1 = w0[-1] - w0
    m0 = np.cumsum(h * c) / np.maximum(w0, 1)
    m1 = (np.sum(h * c) - np.cumsum(h * c)) / np.maximum(w1, 1)
    return float(c[np.argmax(w0 * w1 * (m0 - m1) ** 2)])


def faces(g, thr, center=None):
    """(top, bot, has): per column, the first and last voxel of the papyrus run (g > thr) nearest the centre layer;
    `has` is False where the column has no papyrus at all."""
    np = _np()
    Z = g.shape[0]
    c = Z // 2 if center is None else int(center)
    P = g > thr
    idx = np.arange(Z, dtype=np.int16)[:, None, None]
    big = np.int16(10000)
    d = np.where(P, np.abs(idx - c), big)
    c0 = d.argmin(0).astype(np.int16)
    has = d.min(0) < big
    air = ~P
    top = np.where(air & (idx < c0[None]), idx, np.int16(-1)).max(0) + 1
    bot = np.where(air & (idx > c0[None]), idx, big).min(0) - 1
    bot = np.minimum(bot, Z - 1)
    return top.astype(np.int16), bot.astype(np.int16), has


def sample(v, face, depth):
    """v[face + depth] per column, clipped to the volume."""
    np = _np()
    z = np.clip(face.astype(np.int32) + int(depth), 0, v.shape[0] - 1)
    return np.take_along_axis(v, z[None], 0)[0]


def robust_z(m, mask=None):
    """(m - median) / (1.4826 * MAD), the statistics taken over `mask` (all pixels when None or empty)."""
    np = _np()
    m = np.asarray(m, dtype=np.float32)
    ref = m[mask] if mask is not None and mask.any() else m.ravel()
    med = float(np.median(ref))
    mad = float(np.median(np.abs(ref - med))) * 1.4826 + 1e-6
    return (m - med) / mad


# ---------------------------------------------------------------- recipes

def check_recipe(recipe):
    """Raise InkFilterError unless `recipe` is a usable recipe dict; return it."""
    if not isinstance(recipe, dict) or not recipe.get("components"):
        raise InkFilterError("a recipe is a dict with a non-empty 'components' list")
    for comp in recipe["components"]:
        if comp.get("kind") not in KINDS:
            raise InkFilterError(f"component kind must be one of {KINDS}: {comp}")
        if comp.get("face") not in FACES:
            raise InkFilterError(f"component face must be one of {FACES}: {comp}")
        if comp["kind"] == "composite":
            c = {**COMPOSITE, **comp}
            if not (int(c["half"]) >= 1 and 0 <= float(c["lo"]) < float(c["hi"]) and float(c["opacity"]) > 0):
                raise InkFilterError(f"composite needs half >= 1, 0 <= lo < hi and opacity > 0: {comp}")
        elif not comp.get("depths") or not all(isinstance(d, int) for d in comp["depths"]):
            raise InkFilterError(f"component depths must be a non-empty list of integers: {comp}")
        if comp.get("sign", 1) not in (1, -1):
            raise InkFilterError(f"component sign must be 1 or -1: {comp}")
    for key in ("smooth", "background"):
        if float(recipe.get(key, 0)) < 0:
            raise InkFilterError(f"{key} must be 0 or more")
    return recipe


def composite_alpha(stack, lo, hi, opacity=1.0, cutoff=1.0):
    """VC3D's front-to-back alpha compositing (villa `utils::composite_alpha`, commit b29f310) of a (L, H, W) stack,
    front layer first: each layer's value is normalized to (v - lo) / (hi - lo) and clipped at 1; a layer at or below
    lo adds nothing; its weight is (1 - alpha) * min(normalized * opacity, 1), alpha accumulates the weights, and a
    pixel stops once alpha reaches `cutoff`. Returns the accumulated weight times normalized value."""
    np = _np()
    alpha = np.zeros(stack.shape[1:], np.float32)
    acc = np.zeros(stack.shape[1:], np.float32)
    for layer in stack:
        n = (layer.astype(np.float32) - lo) / (hi - lo)
        live = (n > 0) & (alpha < cutoff)
        n = np.minimum(n, 1.0)
        w = np.where(live, (1.0 - alpha) * np.minimum(n * opacity, 1.0), 0.0).astype(np.float32)
        acc += w * np.where(live, n, 0)
        alpha += w
    return acc


def recipe_named(name):
    if name not in RECIPES:
        raise InkFilterError(f"unknown recipe {name!r}; known: {', '.join(sorted(RECIPES)) or 'none'}")
    return RECIPES[name]


def components(vol, recipe, reverse=False):
    """The recipe's component images of one (Z, H, W) window before normalization, and the rendered mask."""
    np = _np()
    check_recipe(recipe)
    v = np.asarray(vol)
    if v.ndim != 3 or v.shape[0] < 3:
        raise InkFilterError(f"a surface volume window is (Z, H, W) with Z >= 3, got {v.shape}")
    if reverse:
        v = v[::-1]
    rendered = v.max(0) > 0
    g = gaussian(v, PRESMOOTH)
    sub = g[:, ::4, ::4]
    sub = sub[sub > 0]
    if sub.size == 0:
        raise InkFilterError("the window is empty (no rendered voxels)")
    thr = otsu(sub)
    top, bot, has = faces(g, thr)
    face_of = {"bot": (bot, -1), "top": (top, 1)}      # "inside the papyrus" is lower z at bot, higher z at top
    out = []
    raw = None
    for comp in recipe["components"]:
        face, inward = face_of[comp["face"]]
        if comp["kind"] == "bright":
            img = np.mean([sample(g, face, inward * d) for d in comp["depths"]], 0)
        elif comp["kind"] == "step":
            img = np.max([sample(g, face, inward * d) - sample(g, face, inward * (d - 1)) for d in comp["depths"]], 0)
        elif comp["kind"] == "composite":
            c = {**COMPOSITE, **comp}
            mid, half = v.shape[0] // 2, int(c["half"])
            band = v[max(0, mid - half):mid + half + 1]
            if comp["face"] == "bot":                  # the bot (high z) face's side is the front
                band = band[::-1]
            full = {np.dtype("uint8"): 255.0, np.dtype("uint16"): 65535.0}.get(v.dtype, 1.0)
            img = composite_alpha(band, float(c["lo"]) * full, float(c["hi"]) * full, float(c["opacity"]),
                                  float(c["cutoff"]))
        else:
            if raw is None:
                raw = v.astype(np.float32) if v.dtype != np.float32 else v
            size = int(comp.get("window", TEXTURE_WINDOW))
            img = np.mean([texture(sample(raw, face, inward * d), size) for d in comp["depths"]], 0)
        out.append(img.astype(np.float32))
    return out, rendered & has, {"threshold": thr, "bot_median": float(np.median(bot[has])) if has.any() else None,
                                 "top_median": float(np.median(top[has])) if has.any() else None}


def ink_map(vol, recipe=None, reverse=False, info=None):
    """The ink map (H, W) float32 of one surface-volume window under `recipe` (a dict or a name in RECIPES)."""
    np = _np()
    recipe = recipe_named(recipe or DEFAULT_RECIPE) if not isinstance(recipe, dict) else recipe
    comps, mask, meta = components(vol, recipe, reverse)
    m = np.zeros(comps[0].shape, np.float32)
    for comp, img in zip(recipe["components"], comps):
        m += comp.get("sign", 1) * robust_z(img, mask)
    m /= len(comps)
    b, s = float(recipe.get("background", 0)), float(recipe.get("smooth", 0))
    if b > 0:
        m = m - gaussian(m, b)
    if s > 0:
        m = gaussian(m, s)
    if info is not None:
        info.update(meta)
        info["rendered_fraction"] = float(mask.mean())
    return m.astype(np.float32)


