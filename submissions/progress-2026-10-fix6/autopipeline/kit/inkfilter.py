"""Ink filters: hand-designed ink maps from a surface volume, with no trained model and no learned weights.

A surface volume is the stack of layers rendered along a segment's mesh (z = depth along the surface normal, y and
x = the flattened surface). This module turns one window of it into a 2D map, higher where ink is more likely,
using only fixed operations: smoothing, a threshold between air and papyrus, sampling at a depth measured from the
papyrus face, a local texture measure and a robust per-window normalization. Nothing is fitted to labels. The
recipe's few constants (which face, which depths, the texture window, the smoothing) were chosen on published ink
labels leave-one-scroll-out (a note of the source repository); a recipe is a plain dict, so a person can read and
change every step.

Steps of `ink_map(vol)`:

  1. g = vol smoothed by a Gaussian of (1, 1.5, 1.5) voxels (z, y, x).
  2. thr = Otsu's threshold of g over the rendered voxels (one number per window): papyrus above, air below.
  3. For each column (y, x), the papyrus run nearest the centre layer (where the mesh sits) gives two faces: `top`
     (its first papyrus voxel going up in z) and `bot` (its last). In the team's surface volumes the ink side is
     `bot`, the high-z face (measured on 7 scrolls, see the log); `reverse=True` flips the depth order first, which
     is the reverse-depth control the AUC rule asks for.
  4. Each component samples the raw or smoothed volume at fixed depths from the ink face (positive = inside the
     papyrus, 0 = the face voxel, negative = outside) and reduces them to a 2D image: "bright" is the mean of g at
     those depths; "step" is the steepest fall of g from one depth to the next one further out (how sharp the
     papyrus-to-air edge is); "texture" is the local root-mean-square of the raw layer's fine detail (the cracked
     ink texture the community calls crackle), averaged over the depths. "composite" is VC3D's alpha compositing
     of the raw layers within `half` of the centre layer, front to back from the named face's side, with its
     window `lo` to `hi` given as fractions of the data type's full scale (255 for uint8).
  5. Each component image is put on one scale with a robust z-score (median and MAD over the rendered pixels),
     given its sign, and the components are averaged with equal weights.
  6. A broad Gaussian background of `background` pixels is subtracted when it is not 0, and the result is
     smoothed by a 2D Gaussian of `smooth` pixels (about the width of a pen stroke).

Only numpy is needed (no scipy): Gaussians are separable convolutions with mirrored edges (scipy's "reflect"),
box filters are cumulative sums. Reading a remote window uses kit.vc3d_region.Volume; writing a TIFF uses tifffile.

villa's prediction files (`run(..., villa_names=SEGDIR)`, `kit inkfilter --villa-names SEGDIR`). The float32 map is
always written as before. With villa_names, the map and its reverse-depth control are also written as the files
villa's ink inference writes (villa main 8aa507c12): uint8 0 to 255, tiled, LZW, Big TIFF, named
SEGDIR/preds/<seg>_<model>_forward_<ddmmyy>.tif and ..._reverse_... (vesuvius/src/vesuvius/ink_detection/inference/
infer.py:791-834, 1211-1213, 1223-1247), so villa's merge_predictions takes each by its direction
(preprocessing/merge_predictions.py:112-136). The map is put on 0 to 1 by `--scale`: "minmax" (the rendered pixels'
minimum and maximum) or "pLO-pHI" (their LO-th and HI-th percentiles); both limits come from the forward map, and
the control uses the same limits, so the two files share one scale as villa's probabilities do. Then villa's own
encoding applies (clipped to 0 to 1, times 255, truncated), and pixels where the window has no rendered voxel are 0,
as villa leaves pixels it did not predict. The scaling is a display scale, not a probability, and is recorded in the
JSON record and in the overlay record. villa predicts at level 0 (infer.py:967-968, --resolution default "0" at
1308), so a map read at level L is copied onto level 0's grid by repeating each pixel (nearest neighbor); the whole
surface is needed, not a crop, since villa's files and VC3D's overlay are one image per segment. The files are
written by kit.villafmt's `preds export`, which reads each back before it takes villa's name, and the forward file is
registered in SEGDIR/ink-detections.json for VC3D's Ink Detection overlay (apps/VC3D/OpenDataSegmentCache.cpp:651-694)
when SEGDIR is a tifxyz segment. VC3D shows an 8-bit map as stored but stretches any other depth from its own minimum
to its maximum (apps/VC3D/overlays/InkDetectionOverlayController.cpp:106-137, 518), which is why a float32 map lost
its scale there.

An ink map from this module is a filter output, not a reading: it never shows that letters were found.
"""

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

# Frozen 17 Oct 2026 by a note of the source repository: the pick of the leave-one-scroll-out study on 56 windows
# of 7 scrolls (a note of the source repository). Smoothing and background are in pixels of the level read: level 1
# of a 2.4 um scan is 4.8 um per pixel, so 48 px is about 0.23 mm (a pen stroke) and 192 px about 0.9 mm.
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


# ---------------------------------------------------------------- files

def read_window(location, level, box, voxel_um=None, workers=8):
    """A (Z, H, W) window [[z0, z1], [y0, y1], [x0, x1]] of a local or remote surface volume (zarr or OME-Zarr)."""
    from . import vc3d_region
    vol = vc3d_region.Volume(location, voxel_um=voxel_um, workers=workers)
    shape = vol.shape(level)
    box = [[0, shape[0]] if b is None else list(b) for b in box]
    return vol.read(level, box), shape


def write_map(path, m):
    """Save a map as float32 TIFF (.tif/.tiff) or .npy."""
    np = _np()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".tif", ".tiff"):
        try:
            import tifffile
        except ImportError as exc:
            raise InkFilterError("writing a TIFF needs tifffile; use a .npy output instead") from exc
        tifffile.imwrite(str(path), m.astype(np.float32))
    elif path.suffix.lower() == ".npy":
        np.save(str(path), m.astype(np.float32))
    else:
        raise InkFilterError(f"{path}: write a .tif, .tiff or .npy file")
    return str(path)


# ---------------------------------------------------------------- villa's prediction files (--villa-names)

DEFAULT_VILLA_SCALE = "minmax"
VILLA_DIRECTIONS = ("forward", "reverse")      # the map, then its reverse-depth control (villa's two layer orders)
VILLA_ENCODING = ("(value - lo) / (hi - lo), clipped to 0 to 1, times 255 and truncated to uint8, villa's encoding of "
                  "a probability (vesuvius/src/vesuvius/ink_detection/inference/infer.py:791-812 at villa main "
                  "8aa507c12); 0 where the window has no rendered voxel, as villa leaves pixels it did not predict; "
                  "a display scale, not a probability")


def _villafmt():
    from . import villafmt
    return villafmt


def parse_scale(text):
    """{"name", "kind", "percentiles"} for --scale: "minmax" (the rendered pixels' minimum and maximum) or "pLO-pHI"
    (their LO-th and HI-th percentiles, 0 <= LO < HI <= 100, such as p1-p99)."""
    t = str(text if text is not None else DEFAULT_VILLA_SCALE).strip().lower()
    if t == "minmax":
        return {"name": "minmax", "kind": "minmax", "percentiles": None}
    m = re.fullmatch(r"p(\d+(?:\.\d+)?)-p(\d+(?:\.\d+)?)", t)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if 0 <= lo < hi <= 100:
            return {"name": t, "kind": "percentile", "percentiles": [lo, hi]}
    raise InkFilterError(f"--scale {text!r}: use minmax, or pLO-pHI with 0 <= LO < HI <= 100 (such as p1-p99)")


def scale_limits(m, mask, scale):
    """(lo, hi): the values that become 0 and 255, from m's pixels where mask is True (all pixels when mask is None
    or empty) under a parse_scale dict. InkFilterError when there is no range to stretch."""
    np = _np()
    m = np.asarray(m, dtype=np.float32)
    ref = m[mask] if mask is not None and mask.any() else m.ravel()
    ref = ref[np.isfinite(ref)]
    if ref.size == 0:
        raise InkFilterError("the map has no finite value to scale")
    if scale["kind"] == "minmax":
        lo, hi = float(ref.min()), float(ref.max())
    else:
        lo, hi = (float(v) for v in np.percentile(ref, scale["percentiles"]))
    if not hi > lo:
        raise InkFilterError(f"the map has no range to stretch under --scale {scale['name']} (from {lo:g} to {hi:g})")
    return lo, hi


def to_unit(m, lo, hi, mask=None):
    """float32 (m - lo) / (hi - lo) clipped to 0 to 1, and 0 where mask is False (pixels with no rendered voxel)."""
    np = _np()
    p = ((np.asarray(m, dtype=np.float64) - lo) / (hi - lo)).astype(np.float32)
    p = np.nan_to_num(p, nan=0.0, posinf=1.0, neginf=0.0)
    np.clip(p, 0, 1, out=p)
    if mask is not None:
        p[~mask] = 0
    return p


def level0_block(size, size0):
    """(by, bx): level-0 pixels per pixel of a level of (h, w) pixels whose level 0 is (H0, W0) pixels. OME-Zarr
    levels divide the grid by a whole factor, rounding up or down; InkFilterError for any other pair of sizes."""
    out = []
    for n, n0, axis in zip(size, size0, ("rows", "columns")):
        b = max(1, int(round(n0 / max(1, n))))
        if n not in (n0 // b, -(-n0 // b)):
            raise InkFilterError(f"the level's {n} {axis} are not level 0's {n0} divided by a whole factor, so the map "
                                 "cannot be put on villa's level-0 grid; read the volume at --level 0")
        out.append(b)
    return tuple(out)


def to_level0(a, size0, block):
    """The level-0 copy of a level-L map, by repeating each pixel (nearest neighbor): level-0 pixel (y, x) takes
    pixel (y // by, x // bx), clipped to the last row and column."""
    np = _np()
    by, bx = block
    iy = np.minimum(np.arange(int(size0[0])) // by, a.shape[0] - 1)
    ix = np.minimum(np.arange(int(size0[1])) // bx, a.shape[1] - 1)
    return a[np.ix_(iy, ix)]


def villa_plan(segdir, model, size0, date=None, overwrite=False, control=True):
    """Everything --villa-names will write, checked before the map is made (InkFilterError on a refusal): SEGDIR, the
    model name, the date, each file's name and the direction villa's merge reads from it, the level-0 size against a
    surface zarr in SEGDIR (what villa would predict there), against the segment's tifxyz canvas (what VC3D stretches
    the map over) and against the predictions of the same direction already in SEGDIR/preds/."""
    vf = _villafmt()
    segdir = Path(segdir)
    if not segdir.is_dir():
        raise InkFilterError(f"--villa-names {segdir}: not a folder (the segment folder that gets preds/ and "
                             "ink-detections.json)")
    try:
        model = vf.model_stem(model)
    except vf.FormatError as exc:
        raise InkFilterError(f"--model: {exc}") from None
    date = date or datetime.now().strftime(vf.PRED_DATE)
    try:
        ok_date = len(date) == 6 and date.isdigit() and bool(datetime.strptime(date, vf.PRED_DATE))
    except ValueError:
        ok_date = False
    if not ok_date:
        raise InkFilterError(f"--villa-date {date!r} is not DDMMYY, the date villa's folder inference writes "
                             "(infer.py:1212)")
    seg = Path(os.path.abspath(segdir)).name
    h0, w0 = (int(v) for v in size0)
    paths = {}
    for direction in (VILLA_DIRECTIONS if control else VILLA_DIRECTIONS[:1]):
        name = vf.pred_name(seg, model, direction, date)
        parsed = vf.pred_direction(name)
        if parsed != direction:
            raise InkFilterError(f"villa's merge_predictions would read {name} as {parsed!r}, not {direction!r} "
                                 "(merge_predictions.py:112-118: _forward_ anywhere in the name counts first); the "
                                 "segment folder or the model name holds _forward_ or _reverse_, so pass another --model")
        if name.lower().startswith(vf.PRED_MERGED):
            raise InkFilterError(f"{name} starts with {vf.PRED_MERGED}, which villa's merge_predictions takes for its "
                                 "own output and never merges (merge_predictions.py:27, 125-126)")
        dest = segdir / "preds" / name
        if dest.exists() and not overwrite:
            raise InkFilterError(f"{dest} exists; pass --villa-overwrite to replace it")
        paths[direction] = dest
    plan = {"segment": str(segdir), "segment_name": seg, "model": model, "date": date, "size": [w0, h0],
            "paths": {d: str(p) for d, p in paths.items()}, "overwrite": bool(overwrite), "villa": vf.VILLA_PIN,
            "register": False, "tifxyz": None, "warnings": []}
    stale = segdir / "preds" / vf.pred_name(seg, model, "reverse", date)
    if not control and stale.exists():
        plan["warnings"].append(f"preds/ holds {stale.name} from an earlier run, and --no-control writes no new "
                                "control, so that file is not this map's control")
    surf = vf.villa_surface(segdir)
    if surf["height"] is not None and (surf["height"], surf["width"]) != (h0, w0):
        raise InkFilterError(f"the map is {w0} x {h0} on level 0 but villa would predict {surf['width']} x "
                             f"{surf['height']} from {surf['path']} (infer.py:940-952, 1165-1189): this volume is not "
                             "that segment's surface volume")
    plan["surface_zarr"] = surf["path"]
    seg_check = vf.check_tifxyz(segdir, pixels=False) if (segdir / "meta.json").is_file() else None
    if seg_check is not None and seg_check["ok"]:
        meta, rows, cols, expected = vf.canvas_aspect(segdir)
        if abs((w0 / h0) / expected - 1) > vf.ASPECT_TOL:
            raise InkFilterError(f"the map is {w0} x {h0} (aspect {w0 / h0:.4f}) but {seg}'s {cols} x {rows} grid "
                                 f"needs aspect {expected:.4f}: VC3D stretches an ink map over the whole grid "
                                 "(InkDetectionOverlayController.cpp:399-437), so this map is not of this segment")
        plan.update(register=True, tifxyz={"grid": [rows, cols], "key": vf.segment_key(segdir, meta)})
    else:
        why = "no meta.json" if seg_check is None else "; ".join(e["message"] for e in seg_check["errors"])
        plan["no_record"] = (f"{segdir} is not a loadable tifxyz segment ({why}), so no ink-detections.json record "
                             "is written: VC3D's overlay lists the records of the segment it shows")
        plan["warnings"].append(plan["no_record"])
    preds = segdir / "preds"
    others = {}
    for p in (sorted(preds.iterdir()) if preds.is_dir() else []):
        if not p.is_file() or p.suffix.lower() not in vf.PRED_SUFFIXES or p.stem.lower().startswith(vf.PRED_MERGED):
            continue
        d = vf.pred_direction(p.name)
        if d not in paths or p == paths[d]:
            continue
        try:
            pw, ph, _ = vf.image_size(p)
        except vf.FormatError:
            plan["warnings"].append(f"cannot read the size of {p.name} in preds/")
            continue
        if (pw, ph) != (w0, h0):
            raise InkFilterError(f"preds/ already holds {p.name}, a {d} prediction of {pw} x {ph}, and this map is "
                                 f"{w0} x {h0}: villa's merge_predictions stops on a shape mismatch "
                                 "(merge_predictions.py:330-340)")
        others.setdefault(d, []).append(p.name)
    for d, names in sorted(others.items()):
        plan["warnings"].append(
            f"preds/ already holds {len(names)} other {d} prediction(s) ({', '.join(names[:3])}): villa's "
            "merge_predictions merges every file of a direction (merge_predictions.py:129-136, 237-291), and this "
            "filter's 0 to 255 is a display scale, not a probability, so a merge would mix it with the models' "
            "probabilities; keep the filter's files out of that preds/ before merging")
    return plan


def write_villa(plan, maps, mask, scale, block, extra=None, tmp_dir=None):
    """Write maps ({"forward": map, "reverse": control}, level-L float arrays of one shape) as villa's predictions
    under plan, through kit.villafmt's preds export, and register the forward file in SEGDIR/ink-detections.json when
    SEGDIR is a tifxyz segment. Both maps are scaled by the forward map's limits over mask (the rendered pixels), then
    copied onto level 0 by block. The control goes first, so a stop between the two never leaves a forward file
    without its control. Returns the record (its "errors" empty on success)."""
    np = _np()
    vf = _villafmt()
    lo, hi = scale_limits(maps["forward"], mask, scale)
    w0, h0 = plan["size"]
    rec = {"segment": plan["segment"], "segment_name": plan["segment_name"], "model": plan["model"],
           "date": plan["date"], "villa": plan["villa"], "surface_zarr": plan.get("surface_zarr"),
           "tifxyz": plan["tifxyz"],
           "scale": {"name": scale["name"], "kind": scale["kind"], "percentiles": scale["percentiles"], "lo": lo,
                     "hi": hi, "limits_from": "the forward map's rendered pixels; the control uses the same limits",
                     "rule": VILLA_ENCODING},
           "level0": {"size": [w0, h0], "block": list(block),
                      "how": "level 0 is villa's grid; each pixel of the level read is repeated block times "
                             "(nearest neighbor)" if tuple(block) != (1, 1) else "read at level 0, villa's grid"},
           "files": {}, "registered": None, "warnings": list(plan["warnings"]), "errors": [], "published": False}
    segdir = Path(plan["segment"])
    tmp = Path(tempfile.mkdtemp(prefix=".kit-inkfilter-villa-", dir=str(tmp_dir) if tmp_dir else None))
    try:
        for direction in (d for d in ("reverse", "forward") if d in maps and d in plan["paths"]):
            m = np.asarray(maps[direction], dtype=np.float32)
            on = m[mask] if mask is not None and mask.any() else m.ravel()
            p = to_level0(to_unit(m, lo, hi, mask), (h0, w0), block)
            src = tmp / f"{direction}.npy"
            np.save(src, p)
            register = direction == "forward" and plan["register"]
            meta = {"producer": "kit inkfilter --villa-names", "scale": rec["scale"], "level0": rec["level0"],
                    **(extra or {})}
            if register and "reverse" in rec["files"]:
                meta["reverse_control"] = rec["files"]["reverse"]["name"]
            try:
                rep = vf.export_pred(src, segdir, plan["model"], direction, scale="prob", date=plan["date"],
                                     overwrite=plan["overwrite"], register=register,
                                     label=f"{plan['segment_name']} - {plan['model']} ({scale['name']})"
                                     if register else None, extra=meta if register else None)
            except vf.FormatError as exc:
                rec["errors"].append(f"villafmt preds export refused the {direction} file: {exc}")
                break
            if not rep["ok"] or not rep["written"] or Path(rep["file"]) != Path(plan["paths"][direction]):
                why = "; ".join(e["message"] for e in rep["errors"]) or f"it wrote {rep['file']}"
                rec["errors"].append(f"villafmt preds export refused the {direction} file: {why}")
                if rep.get("written"):
                    rec["files"][direction] = {"path": rep["file"], "name": rep["name"], "direction": direction}
                break
            rec["files"][direction] = {
                "path": rep["file"], "name": rep["name"], "direction": direction,
                "clipped_low": float(np.mean(on < lo)), "clipped_high": float(np.mean(on > hi)),
                "encoding": rep["encoding"], "villafmt_scale": rep["scale"],
                "warnings": [e["message"] for e in rep["warnings"]]}
            if register:
                rec["registered"] = rep["registered"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if "forward" in rec["files"] and not plan["register"]:
        rec["registered"] = {"skipped": plan.get("no_record")}
    rec["published"] = not rec["errors"]
    return rec


def run(location, output, level=1, crop=None, recipe=None, control=True, voxel_um=None, workers=8,
        villa_names=None, model=None, scale=None, villa_date=None, villa_overwrite=False):
    """Read a window, write its ink map and (by default) the reverse-depth control next to it, and return a summary.
    `crop` is (y0, y1, x0, x1) on the level's grid; None means the whole surface (only sensible for small ones).
    `recipe` is a name in RECIPES, a recipe dict, or None for DEFAULT_RECIPE.
    `villa_names` (a segment folder) also writes the map and the control as villa's uint8 predictions in
    SEGDIR/preds/ and registers the map for VC3D's overlay (see the module docstring); `model` names the map in villa's
    file names (default inkfilter-<recipe name>), `scale` is "minmax" (default) or "pLO-pHI", `villa_date` the
    DDMMYY in the names (default today) and `villa_overwrite` replaces files already at those names."""
    if villa_names is None and (model is not None or scale is not None or villa_date or villa_overwrite):
        raise InkFilterError("--model, --scale, --villa-date and --villa-overwrite go with --villa-names SEGDIR")
    if crop is not None and (crop[1] <= crop[0] or crop[3] <= crop[2]):
        raise InkFilterError(f"empty crop {list(crop)}")
    if isinstance(recipe, dict):
        name, rec = "custom", check_recipe(recipe)
    else:
        name = recipe or DEFAULT_RECIPE
        rec = recipe_named(name)
    sc = parse_scale(scale) if villa_names is not None else None
    np = _np()
    shape0 = None
    if crop is None or villa_names is not None:
        from . import vc3d_region
        V = vc3d_region.Volume(location, voxel_um=voxel_um)
        shape, shape0 = V.shape(level), V.shape(0)
        if crop is None:
            crop = (0, shape[1], 0, shape[2])
    y0, y1, x0, x1 = (int(c) for c in crop)
    if y1 <= y0 or x1 <= x0:
        raise InkFilterError(f"empty crop {crop}")
    plan = block = None
    if villa_names is not None:
        if (y0, y1, x0, x1) != (0, shape[1], 0, shape[2]):
            raise InkFilterError(f"--villa-names needs the whole {shape[1]} x {shape[2]} surface at level {level}, not "
                                 f"the crop {[y0, y1, x0, x1]}: villa's predictions and VC3D's overlay are one image "
                                 "per segment, and a crop would be stretched over all of it")
        block = level0_block(shape[1:], shape0[1:])
        plan = villa_plan(villa_names, model or f"inkfilter-{name}", shape0[1:], villa_date, villa_overwrite,
                          control)
    vol, shape = read_window(location, level, [None, [y0, y1], [x0, x1]], voxel_um, workers)
    info = {}
    m = ink_map(vol, rec, info=info)
    out = {"location": str(location), "level": level, "crop": [y0, y1, x0, x1], "surface_shape": shape,
           "recipe_name": name, "recipe": rec, "output": write_map(output, m), "window": info,
           "note": "filter output, not a reading"}
    c = None
    if control:
        p = Path(output)
        ctrl = p.with_name(p.stem + "_reverse" + p.suffix)
        c = ink_map(vol, rec, reverse=True)
        out["control"] = write_map(ctrl, c)
    out["map_stats"] = {"min": float(np.min(m)), "max": float(np.max(m)), "mean": float(np.mean(m))}
    if plan is not None:
        maps = {"forward": m, **({"reverse": c} if c is not None else {})}
        out["villa"] = write_villa(plan, maps, np.asarray(vol).max(0) > 0, sc, block,
                                   extra={"recipe": name, "level_read": level, "float_map": out["output"]},
                                   tmp_dir=Path(output).resolve().parent)
    side = Path(output).with_suffix(".json")
    side.write_text(json.dumps(out, indent=2) + "\n")
    out["record"] = str(side)
    if plan is not None and out["villa"]["errors"]:
        raise InkFilterError("--villa-names: " + "; ".join(out["villa"]["errors"]) + f" (record: {side})")
    return out


def pool_yx(vol, n):
    """Mean over n x n pixel blocks of a (Z, H, W) stack, the last blocks partial, in the stack's dtype (rounded for
    an integer dtype, so the composite's limits stay fractions of the dtype's full scale)."""
    np = _np()
    v = np.asarray(vol)
    if n == 1:
        return v
    Z, H, W = v.shape
    h, w = -(-H // n), -(-W // n)
    acc = np.zeros((Z, h, w), np.float64)
    cnt = np.zeros((1, h, w), np.float64)
    for dy in range(n):
        for dx in range(n):
            part = v[:, dy::n, dx::n].astype(np.float64)
            acc[:, :part.shape[1], :part.shape[2]] += part
            cnt[:, :part.shape[1], :part.shape[2]] += 1
    m = acc / cnt
    return np.rint(m).astype(v.dtype) if np.issubdtype(v.dtype, np.integer) else m.astype(v.dtype)


def engine_map(location, output, reverse=False, pool=2, recipe=None, workers=8):
    """One map as AutoPipeline's ink tool asks a command engine for it (vc3d_catalog.BUILTIN_MODELS["inkfilter"]):
    level 0 of the render read whole, averaged over pool x pool pixels (pool 2 on a 2.4 um render is the 4.8 um grid
    the recipe was chosen on, level 1 of the team's surface volumes, which keep every layer), the forward map or with
    `reverse` the reverse-depth control, repeated back onto level 0's grid (nearest neighbor) and written to `output`
    with a JSON record next to it."""
    np = _np()
    if int(pool) < 1:
        raise InkFilterError("pool is a whole number of pixels, 1 or more")
    pool = int(pool)
    name = recipe or DEFAULT_RECIPE
    rec = recipe_named(name) if not isinstance(recipe, dict) else check_recipe(recipe)
    from . import vc3d_region
    shape = vc3d_region.Volume(location, workers=workers).shape(0)
    vol, shape = read_window(location, 0, [[0, shape[0]], [0, shape[1]], [0, shape[2]]], workers=workers)
    info = {}
    m = ink_map(pool_yx(vol, pool), rec, reverse=bool(reverse), info=info)
    full = np.repeat(np.repeat(m, pool, 0), pool, 1)[:shape[1], :shape[2]]
    out = {"location": str(location), "level": 0, "pool": pool, "surface_shape": shape, "reverse": bool(reverse),
           "recipe_name": name if not isinstance(recipe, dict) else "custom", "recipe": rec,
           "output": write_map(output, full), "window": info, "note": "filter output, not a reading"}
    side = Path(output).with_suffix(".json")
    side.write_text(json.dumps(out, indent=2) + "\n")
    out["record"] = str(side)
    return out


def format_result(r):
    lines = [f"ink map ({r['recipe_name']}): {r['output']}"]
    if r.get("control"):
        lines.append(f"reverse-depth control: {r['control']}")
    w = r["window"]
    lines.append(f"window y {r['crop'][0]}:{r['crop'][1]} x {r['crop'][2]}:{r['crop'][3]} at level {r['level']}, "
                 f"papyrus threshold {w['threshold']:.1f}, rendered {100 * w['rendered_fraction']:.0f} %")
    v = r.get("villa")
    if v:
        s = v["scale"]
        for d, f in v["files"].items():
            lines.append(f"villa {d} prediction: {f['path']} (uint8, scale {s['name']}: {s['lo']:.4g} to {s['hi']:.4g} "
                         f"as 0 to 255)")
        reg = v.get("registered") or {}
        lines.append(f"VC3D overlay record: {reg['file']}" if reg.get("file") else
                     f"no VC3D overlay record: {reg.get('skipped')}")
        for wmsg in v.get("warnings", []):
            lines.append(f"warning: {wmsg}")
    lines.append(f"record: {r['record']}")
    lines.append("A filter output, not a reading. Score it with: python -m kit auc MAP --control CONTROL ...")
    return "\n".join(lines)


__all__ = ["RECIPES", "DEFAULT_RECIPE", "InkFilterError", "gaussian", "box", "texture", "otsu", "faces", "sample",
           "robust_z", "check_recipe", "components", "ink_map", "read_window", "write_map", "run", "format_result",
           "pool_yx", "engine_map",
           "DEFAULT_VILLA_SCALE", "parse_scale", "scale_limits", "to_unit", "level0_block", "to_level0", "villa_plan",
           "write_villa"]
