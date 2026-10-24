"""Put an ink map or a prediction on a named scale, or refuse it (numpy only).

Ink maps and surface predictions come stored three ways: uint8 on the organizers' 0 to 255 scale (villa flat
inference, the organizers' maps, our renderer), uint16 on 0 to 65535 (kit ensemble's .tif output, some bucket
volumes), and float, usually probabilities in 0 to 1 (Reader V3 and v8in .npy, sigmoid outputs) but sometimes
0 to 255 or logits. A fixed cut written for one of these (USABLE_MIN 3, `>= 128`, `> 0.5`) silently keeps
nothing or everything on another: public StrokeNet v1 scored no window on 0 to 1 maps that way (public Scrolls
PR #152; audit a note of the source repository).

Scales: "unit" (0 to 1), "u8" (0 to 255), "u16" (0 to 65535). With scale="auto" the scale is read from the
stored dtype, never guessed from the values alone: uint8 is u8, uint16 is u16, and a float map is unit only when
every finite value lies in 0 to 1 (an overshoot up to UNIT_SLACK, as after cubic resampling, is clipped). Any
other float map (0 to 255, 0 to 65535, logits) and any other dtype is refused under auto: the caller names its
scale. A named scale is checked against the values too, so a 0 to 1 map named u8 is refused rather than read as
nearly blank.

  scale_of(a, scale="auto", name="map")   the scale, or MapScaleError
  to_unit(a, scale="auto", name="map")    float32 in 0 to 1 (NaN kept), and the scale it came from
  to_u8(a, scale="auto", name="map")      uint8 on 0 to 255, round half up; NaN becomes 0
  require(a, scale, name="map")           None when a's values are on `scale`, else MapScaleError; for tools
                                          whose cuts are written on one scale (a `>= 128` on u8)
  same_scale(maps)                        the one scale every (name, array) pair is on, or MapScaleError; for
                                          tools that average, subtract or compare maps
"""

SCALES = ("auto", "unit", "u8", "u16")
TOP = {"unit": 1.0, "u8": 255.0, "u16": 65535.0}
UNIT_SLACK = 1e-3          # a float map up to 1.001 still reads as 0 to 1 (clipped); above it, name the scale
_DTYPE_SCALE = {"uint8": "u8", "uint16": "u16"}   # by kind and size, so a big-endian ">u2" TIFF counts too


class MapScaleError(ValueError):
    """A map whose scale cannot be read or does not match what was asked; the message says which and why."""


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise MapScaleError("numpy is required for kit.mapscale: python -m pip install numpy") from exc
    return numpy


def _range(np, a):
    """(lowest, highest) finite value, or (None, None) when there is none."""
    v = np.asarray(a)
    if v.size == 0:
        return None, None
    if v.dtype.kind == "f":   # fmin and fmax skip NaN without copying a whole-segment map
        lo, hi = float(np.fmin.reduce(v, axis=None)), float(np.fmax.reduce(v, axis=None))
        return (None, None) if lo != lo else (lo, hi)
    return float(v.min()), float(v.max())


def _describe(dtype, lo, hi):
    span = "no finite value" if lo is None else f"values {lo:.6g} to {hi:.6g}"
    return f"{dtype} with {span}"


def scale_of(a, scale="auto", name="map"):
    """The scale a's values are on: `scale` itself once checked, or under auto the scale its dtype names."""
    np = _np()
    if scale not in SCALES:
        raise MapScaleError(f"{name}: scale must be one of {', '.join(SCALES)}, not {scale!r}")
    a = np.asarray(a)
    kind = a.dtype.kind
    dt = {("u", 1): "uint8", ("u", 2): "uint16"}.get((kind, a.dtype.itemsize), str(a.dtype))
    if kind not in "uif" or a.dtype == bool:
        raise MapScaleError(f"{name}: {dt} is not a map dtype (uint8, uint16 or float)")
    if dt in _DTYPE_SCALE and scale in ("auto", _DTYPE_SCALE[dt]):
        return _DTYPE_SCALE[dt]       # every value of the dtype fits its scale: no pass over the data
    lo, hi = _range(np, a)
    if scale == "auto":
        if kind == "f" and (lo is None or (lo >= 0.0 and hi <= 1.0 + UNIT_SLACK)):
            return "unit"
        raise MapScaleError(f"{name}: {_describe(dt, lo, hi)} has no scale its dtype names; only uint8 (0 to 255), "
                            "uint16 (0 to 65535) and float maps within 0 to 1 are read without one, so give "
                            "its scale (unit, u8 or u16)")
    if dt in _DTYPE_SCALE and _DTYPE_SCALE[dt] != scale:
        raise MapScaleError(f"{name}: a {dt} map is on {_DTYPE_SCALE[dt]}, not {scale}")
    if lo is None:
        return scale
    top = TOP[scale]
    if lo < 0.0 or hi > top * (1.0 + UNIT_SLACK):
        raise MapScaleError(f"{name}: {_describe(dt, lo, hi)} does not fit {scale} (0 to {top:g})")
    if scale != "unit" and kind == "f" and 0.0 < hi <= 1.0 + UNIT_SLACK:
        raise MapScaleError(f"{name}: {_describe(dt, lo, hi)} looks like 0 to 1 probabilities, not {scale} "
                            f"(0 to {top:g}); a map that dim is blank on {scale}, so name it unit")
    return scale


def to_unit(a, scale="auto", name="map"):
    """(float32 map in 0 to 1, scale): divided by its scale's top and clipped; NaN stays NaN."""
    np = _np()
    a = np.asarray(a)
    s = scale_of(a, scale, name)
    out = a.astype(np.float32) / np.float32(TOP[s])
    np.clip(out, 0.0, 1.0, out=out)
    return out, s


def to_u8(a, scale="auto", name="map"):
    """(uint8 map on 0 to 255, scale): round half up; NaN becomes 0 (no data, as villa writes it)."""
    np = _np()
    a = np.asarray(a)
    if a.dtype == np.uint8 and scale in ("auto", "u8"):
        return a, "u8"
    u, s = to_unit(a, scale, name)
    u = np.nan_to_num(u, nan=0.0)
    return np.floor(u * np.float32(255.0) + np.float32(0.5)).astype(np.uint8), s


def require(a, scale, name="map"):
    """None when a's values are on `scale` (its dtype agrees, its range fits and it is not a 0 to 1 map named u8
    or u16); else MapScaleError naming what it is."""
    if scale == "auto":
        raise MapScaleError("require needs a named scale: unit, u8 or u16")
    scale_of(a, scale, name)


def same_scale(maps):
    """The scale every map is on under auto, for tools that combine maps: [(name, array), ...] -> scale."""
    seen = {}
    for name, a in maps:
        seen.setdefault(scale_of(a, "auto", name), []).append(name)
    if len(seen) > 1:
        parts = "; ".join(f"{s}: {', '.join(n)}" for s, n in sorted(seen.items()))
        raise MapScaleError(f"the maps are on different scales ({parts}); put them on one scale first (to_unit)")
    return next(iter(seen)) if seen else "auto"
