"""Is a surface seated on a papyrus sheet, and in which frame? Scores from a stack VC3D rendered along it.

A mesh traced in one scan or binning and rendered against another is not seated: its render cuts
across the windings and looks plausible until someone inspects it. The test asks whether the sheet
runs along the surface: on a seated surface the center layer sits in papyrus and the layers about a
gap away on both sides fall between windings, so the center is brighter than both.

Ported from axiosdevs/herculaneum-scroll-tools, `ink/seat_mesh.py` (`sheet_contrast`, `probe_gap`,
`seating_score`) at commit 63a09d4, under the MIT License reproduced below. The original samples the
volume at mesh points through its own chunked reader; here `vc_render_tifxyz --num-slices 2N+1`
renders the stack, so the sampling is VC3D's own (trilinear, remote volumes, any compressor), and
`--scale-segmentation` plays the role of the original's scale search. Pure standard library.

    MIT License

    Copyright (c) 2026

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""

import random
import statistics
from itertools import compress

MATERIAL = 40          # center intensity (uint8) above which a pixel counts as inside material
MIN_COVERAGE = 0.25    # below this the surface is mostly in air and gets the floor score -1
MIN_PIXELS = 1000      # sheet_contrast needs this many pixels valid in every layer
SPAN = 25              # sheet_contrast: layers either side of the middle
# Interpretation thresholds, not from the original: its seated surfaces scored a sheet contrast of
# +30 to +39 and a cut across the windings about 0 (seat_mesh.sheet_contrast docstring).
SEATED_CONTRAST, UNSEATED_CONTRAST = 10.0, 3.0


# S_local as alexxxmur's repository defines it (https://github.com/alexxxmur/vesuvius-pherc0846a-2p4um, read 7 Oct 2026)
S_LOCAL_COLUMNS, S_LOCAL_COLUMN_UM, S_LOCAL_HALF_UM, S_LOCAL_SMOOTH_UM = 40, 300.0, 131.0, 10.0
S_LOCAL_REFERENCE = ("Community report (alexxxmur, https://github.com/alexxxmur/vesuvius-pherc0846a-2p4um): "
                     "ink-labelled team surfaces median 0.40 (min 0.19), auto-grown team surfaces 0.22 (min 0.12), "
                     "PHercParis4 surfaces 0.24 to 0.38, at a resolution the notes do not give. Scan contrast and "
                     "voxel size move it (w035 gave 0.37 at 9.362 um and 1.25 at 2.399 um), so compare surfaces of one "
                     "scan only. Exploratory, not a pass mark.")
_NONZERO = bytes([0] + [1] * 255)


def _plain(data):
    """Samples the sums here can take: a numpy array becomes bytes (8-bit unsigned) or a list of Python numbers,
    since a sum of numpy uint8 or uint16 values keeps that type and wraps past its largest value."""
    if hasattr(data, "dtype") and hasattr(data, "ravel"):
        return data.tobytes() if data.dtype.kind == "u" and data.dtype.itemsize == 1 else data.ravel().tolist()
    return data


def _planes(shape, data):
    n, h, w = shape
    plane = h * w
    return [data[k * plane:(k + 1) * plane] for k in range(n)]


def valid_mask(shape, data):
    """0/1 bytes, one per pixel: 1 where the pixel is nonzero in every layer (VC3D leaves off-surface pixels 0).
    8-bit stacks are masked a layer at a time with bytes.translate and big-integer ANDs, at C speed."""
    n, h, w = shape
    plane = h * w
    if isinstance(data, (bytes, bytearray)):
        acc = (1 << (8 * plane)) - 1 if plane else 0
        for layer in _planes(shape, data):
            acc &= int.from_bytes(bytes(layer).translate(_NONZERO), "big")
        return acc.to_bytes(plane, "big") if n else bytes([1]) * plane
    keep = bytearray([1]) * plane
    for layer in _planes(shape, data):
        for i, v in enumerate(layer):
            if not v:
                keep[i] = 0
    return bytes(keep)


def valid_pixels(shape, data):
    """Indices of pixels that are nonzero in every layer (VC3D leaves off-surface pixels 0)."""
    return [i for i, v in enumerate(valid_mask(shape, data)) if v]


def profile(shape, data, pixels):
    """Mean of each layer over the given pixels: a list of indices, or a 0/1 mask as from valid_mask."""
    n, h, w = shape
    data = _plain(data)
    if isinstance(pixels, (bytes, bytearray)):
        count = pixels.count(1)
        return [sum(compress(layer, pixels)) / count for layer in _planes(shape, data)] if count else [None] * n
    plane = h * w
    if not pixels:
        return [None] * n
    return [sum(data[k * plane + i] for i in pixels) / len(pixels) for k in range(n)]


def _above(layer, mask, material):
    """0/1 mask of the pixels in `mask` whose value in `layer` is above `material`."""
    if isinstance(layer, (bytes, bytearray)):
        table = bytes(1 if v > material else 0 for v in range(256))
        n = len(layer)
        return (int.from_bytes(bytes(layer).translate(table), "big") & int.from_bytes(mask, "big")).to_bytes(n, "big")
    return bytes(1 if m and v > material else 0 for v, m in zip(layer, mask))


def sheet_contrast(prof, span=SPAN, pixels=None):
    """The middle layer's mean minus the mean of the layers `span` out (seat_mesh.sheet_contrast)."""
    if pixels is not None and pixels < MIN_PIXELS:
        return None
    mid = len(prof) // 2
    lo, hi = max(0, mid - span), min(len(prof) - 1, mid + span)
    return prof[mid] - 0.5 * (prof[lo] + prof[hi])


def probe_gap(prof, step_layers=2, fallback=25):
    """Half the distance to the neighboring winding, in layers: the first minimum of the two-sided
    mean profile walking out from the middle (seat_mesh.probe_gap, there in steps of 2 voxels)."""
    mid = len(prof) // 2
    steps = list(range(step_layers, mid, step_layers))
    means = [0.5 * (prof[mid + t] + prof[mid - t]) for t in steps]
    if len(means) < 3:
        return min(fallback, mid)
    # np.convolve(means, ones(3)/3, mode="same"): zero padded at both ends, as in the original
    padded = [0.0] + means + [0.0]
    smooth = [(padded[i] + padded[i + 1] + padded[i + 2]) / 3 for i in range(len(means))]
    for i in range(1, len(smooth) - 1):
        if smooth[i] <= smooth[i - 1] and smooth[i] <= smooth[i + 1]:
            return steps[i]
    return steps[min(range(len(smooth)), key=smooth.__getitem__)]


def seating(shape, data, gap=None, material=MATERIAL):
    """Score one rendered stack (layers centered on the surface). Higher is better seated.

    Returns gap (layers), coverage (fraction of valid pixels whose center is material), contrast (center
    minus the mean of +-gap, over those pixels), score (contrast x coverage, or -1 below the coverage
    floor), the per-layer profile and seat_mesh's sheet_contrast."""
    n, h, w = shape
    data = _plain(data)
    plane = h * w
    mask = valid_mask(shape, data)
    count = mask.count(1)
    prof = profile(shape, data, mask)
    out = {"layers": n, "valid_pixels": count, "profile": [round(p, 2) for p in prof] if count else []}
    if not count:
        out.update(score=-1.0, coverage=0.0, contrast=None, gap=None, sheet_contrast=None)
        return out
    mid = n // 2
    gap = probe_gap(prof) if gap is None else min(int(gap), mid)
    centre = data[mid * plane:(mid + 1) * plane]
    on = _above(centre, mask, material)
    n_on = on.count(1)
    coverage = n_on / count
    out.update(gap=gap, coverage=round(coverage, 4), sheet_contrast=sheet_contrast(prof, pixels=count))
    if out["sheet_contrast"] is not None:
        out["sheet_contrast"] = round(out["sheet_contrast"], 2)
    if coverage < MIN_COVERAGE or not n_on:
        out.update(score=-1.0, contrast=None, surface_mean=round(sum(compress(centre, mask)) / count, 2))
        return out
    c = sum(compress(centre, on)) / n_on
    before = sum(compress(data[(mid - gap) * plane:(mid - gap + 1) * plane], on)) / n_on
    after = sum(compress(data[(mid + gap) * plane:(mid + gap + 1) * plane], on)) / n_on
    contrast = c - 0.5 * (before + after)
    out.update(contrast=round(contrast, 2), score=round(contrast * coverage, 2), surface_mean=round(c, 2))
    return out


def verdict(result):
    """'seated', 'not seated' or 'unclear' from one seating result (thresholds are an interpretation)."""
    contrast = result.get("contrast")
    if result.get("score", -1) < 0 or contrast is None:
        return "not seated"
    if contrast >= SEATED_CONTRAST:
        return "seated"
    if contrast <= UNSEATED_CONTRAST:
        return "not seated"
    return "unclear"


def best_frame(rows):
    """Rank frame candidates [{'scale_segmentation': s, 'score': ...}] best first, with the margin
    over the runner-up (a clear winner is what makes the frame search a check that can fail)."""
    ranked = sorted(rows, key=lambda r: -r["score"])
    margin = ranked[0]["score"] - ranked[1]["score"] if len(ranked) > 1 else None
    return ranked, margin


def _smooth(values, width):
    """Centered moving average over `width` (odd) values, over what exists at the ends."""
    if width <= 1:
        return list(values)
    r = width // 2
    out = []
    for i in range(len(values)):
        part = values[max(0, i - r):i + r + 1]
        out.append(sum(part) / len(part))
    return out


def s_local_params(voxel_um):
    """Column side, half window and smoothing in layers (1 voxel apart) for a voxel size in um."""
    if not voxel_um or voxel_um <= 0:
        raise ValueError("S_local needs the voxel size in um")
    smooth = max(1, round(S_LOCAL_SMOOTH_UM / voxel_um))
    return {"column_px": max(1, round(S_LOCAL_COLUMN_UM / voxel_um)), "half_layers": max(1, round(S_LOCAL_HALF_UM / voxel_um)),
            "smooth_layers": smooth + (smooth % 2 == 0)}


def s_local_columns(shape, data, voxel_um, count, rng, min_valid=0.5, mask=None):
    """(max - median) / median of the depth profile of `count` random columns of one rendered stack (layers
    1 voxel apart, centered on the surface): the profile is the column's mean per layer, smoothed over about
    10 um, within the central +-131 um. A column is a square about 0.3 mm on a side, kept when at least
    min_valid of it is on the surface; its mean comes from a regular subsample of at most 32 x 32 pixels."""
    n, h, w = shape
    data = _plain(data)
    par = s_local_params(voxel_um)
    cpx, half, sm = par["column_px"], par["half_layers"], par["smooth_layers"]
    mask = valid_mask(shape, data) if mask is None else mask
    if not mask.count(1):
        return []
    mid = n // 2
    lo, hi = max(0, mid - half), min(n - 1, mid + half)
    ext_lo, ext_hi = max(0, lo - sm // 2), min(n - 1, hi + sm // 2)
    ch, cw = min(cpx, h), min(cpx, w)
    stride = max(1, -(-max(ch, cw) // 32))
    planes = _planes(shape, data)
    out, tries = [], 0
    while len(out) < count and tries < 50 * count:
        tries += 1
        r0, c0 = rng.randrange(h - ch + 1), rng.randrange(w - cw + 1)
        pix = [r * w + c for r in range(r0, r0 + ch, stride) for c in range(c0, c0 + cw, stride)]
        good = [i for i in pix if mask[i]]
        if len(good) < min_valid * len(pix):
            continue
        prof = [sum(planes[k][i] for i in good) / len(good) for k in range(ext_lo, ext_hi + 1)]
        prof = _smooth(prof, sm)[lo - ext_lo:hi - ext_lo + 1]
        med = statistics.median(prof)
        if med > 0:
            out.append((max(prof) - med) / med)
    return out


def s_local_summary(values, voxel_um, layers=None, seed=None):
    """S_local (the median over columns) with its settings and the community's reference values."""
    par = s_local_params(voxel_um)
    out = {"s_local": round(statistics.median(values), 4) if values else None, "columns": len(values),
           "column_um": S_LOCAL_COLUMN_UM, "half_um": S_LOCAL_HALF_UM, "smooth_um": S_LOCAL_SMOOTH_UM,
           "voxel_um": voxel_um, **par, "seed": seed, "reference": S_LOCAL_REFERENCE}
    if values:
        q = sorted(values)
        out["quartiles"] = [round(q[len(q) // 4], 4), round(q[(3 * len(q)) // 4], 4)]
    if layers is not None and layers // 2 < par["half_layers"]:
        out["note"] = (f"the stack reaches {layers // 2} layers either side, short of +-{S_LOCAL_HALF_UM} um "
                       f"({par['half_layers']} layers): the score used what there was")
    return out


def s_local(stacks, voxel_um, seed=0, columns=S_LOCAL_COLUMNS):
    """S_local over several stacks of one surface: the columns are shared out evenly between the stacks, and
    each stack draws its own from a generator seeded by the seed and its place in the list."""
    values = []
    n = max(1, len(stacks))
    for k, (shape, data) in enumerate(stacks):
        quota = columns // n + (1 if k < columns % n else 0)
        values += s_local_columns(shape, data, voxel_um, quota, random.Random(f"{seed}:{k}"))
    layers = min((shape[0] for shape, _ in stacks), default=None)
    return s_local_summary(values, voxel_um, layers, seed)
