"""Compare two ink maps from the same input: a reference (e.g. CPU) and a candidate (e.g. MPS).

Acceptance follows the GENChase Apple GPU backend
(https://github.com/ChaseHendrick/GENChase/blob/main/apps/validate/APPLE-GPU.md):
agreement under a stated tolerance counts only if a deliberately wrong input, the
control, is caught by the same comparison. Without a control the verdict says so.

Default tolerance: villa PR #1865 reported CPU and MPS maps differing by at most 1 of
255 gray levels on 0.002% of pixels. The defaults (2 levels, at most 0.01% of pixels
beyond that) leave margin above that report without accepting a different map.

The maps are villa's uint8 TIFFs. Reading them needs numpy and tifffile (and
imagecodecs for LZW); villa's environment has all three. `load_map` also reads 8-bit and
16-bit gray PNG (Hecate writes its maps as PNG, round(255 p)) with zlib and numpy alone:
a color PNG is accepted only when its color channels agree (the first is kept, alpha is
ignored); palette, sub-byte and interlaced PNG are refused. Maps keep their own grid; a
map on another grid is refused by the comparison, never resized here.
"""

import math
import struct
import zlib
from pathlib import Path

DEFAULT_TOLERANCE = 2
UNIT_SLACK = 1e-3   # kit.mapscale.UNIT_SLACK: a float map up to 1.001 still counts as 0 to 1
DEFAULT_MAX_FRACTION = 1e-4
ROWS_PER_BLOCK = 1024

PASS = "pass"
PASS_UNCONTROLLED = "pass-uncontrolled"
FAIL = "fail"
CONTROL_NOT_CAUGHT = "control-not-caught"


class VerifyError(Exception):
    pass


def _numpy():
    try:
        import numpy
    except ImportError as exc:
        raise VerifyError(
            "numpy is required. Run inside villa's environment: "
            "uv run --project \"$VILLA/vesuvius\" --extra models python -m kit verify ..."
        ) from exc
    return numpy


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}   # color type: samples per pixel (3, palette, is refused)


# ---------------------------------------------------------------- sealed files
# A preregistration can seal published files (labels, or maps made with them) until its one-time opening, so that no
# choice made before the opening can use them. A registry, a JSON file under a folder of the source repository, lists each sealed file
# by sha256 with its group (the unit that opens together) and whether it may be decoded after the opening at all, and
# names the marker file, relative to the source folder, whose "openings" list records the opened groups:
#   {"marker": "docs/.../openings.json",
#    "files": {"<sha256>": {"file": "<name>", "group": "<group>", "after_opening": true}}}
# read_png here and kit.vc3d_io.read_png_gray call sealed_refuse before decoding, so every kit command that reads a
# PNG through them (kit auc, the agent tools) refuses a sealed file. Readers outside
# kit (PIL, tifffile, cv2 in a script) are not covered. With no registry nothing is hashed.
SOURCE = Path(__file__).resolve().parents[1]
SEALED_DIR = SOURCE / "kit" / "data" / "sealed"


class SealedError(VerifyError):
    """A sealed file would be decoded before its opening is recorded, or at all when it never opens."""


def sealed_registries():
    """Every registry under SEALED_DIR, as dicts; an unreadable registry is an error, not a free pass."""
    if not SEALED_DIR.is_dir():
        return []
    import json
    out = []
    for path in sorted(SEALED_DIR.glob("*.json")):
        try:
            reg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SealedError(f"cannot read the sealed-file registry {path}: {exc}") from None
        reg.setdefault("source", str(path))
        out.append(reg)
    return out


def opened_groups(marker, source=None):
    """Groups that the marker file (relative to the source folder) records as opened; none when it is absent."""
    if not marker:
        return set()
    path = Path(source or SOURCE) / marker
    if not path.is_file():
        return set()
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SealedError(f"cannot read the opening marker {path}: {exc}") from None
    return {str(g) for entry in data.get("openings", []) for g in entry.get("windings", entry.get("groups", []))}


def sealed_check(blob, what="file", registries=None):
    """None when the bytes may be decoded now, else why not."""
    regs = sealed_registries() if registries is None else registries
    if not regs:
        return None
    import hashlib
    digest = hashlib.sha256(bytes(blob)).hexdigest()
    for reg in regs:
        entry = (reg.get("files") or {}).get(digest)
        if entry is None:
            continue
        name = entry.get("file", digest[:12])
        if not entry.get("after_opening", False):
            return f"{what} is {name}, sealed by {reg['source']}: it is never decoded, before or after the opening"
        if str(entry.get("group")) not in opened_groups(reg.get("marker")):
            return (f"{what} is {name}, sealed by {reg['source']} until the opening of {entry.get('group')} is "
                    f"recorded in {reg.get('marker')}")
    return None


def sealed_refuse(blob, what="file", allow=False):
    """SealedError when `blob` is a sealed file that may not be decoded now; allow=True is for the one tool that
    performs the opening, which records it first."""
    if allow:
        return
    why = sealed_check(blob, what)
    if why:
        raise SealedError(why)


def _png_unfilter(np, rows, filters, bpp):
    """Undo PNG's per-row filters. rows: (h, stride) uint8 as stored, filters: (h,) filter types.

    Rows filtered with None, Sub or Up are undone one row at a time. Average and Paeth depend on
    the reconstructed left neighbor, so when any row uses them the whole image is undone along
    anti-diagonals: every pixel of one diagonal depends only on the two diagonals before it."""
    h, stride = rows.shape
    if filters.size and int(filters.max()) > 4:
        raise VerifyError(f"PNG row filter {int(filters.max())} is not defined")
    if not (filters >= 3).any():
        out = np.empty_like(rows)
        prev = np.zeros(stride, np.uint8)
        for r in range(h):
            x, f = rows[r], int(filters[r])
            if f == 1:
                x = np.cumsum(x.reshape(-1, bpp), axis=0, dtype=np.uint8).reshape(-1)
            elif f == 2:
                x = x + prev
            out[r] = x
            prev = out[r]
        return out
    w = stride // bpp
    w1 = w + 1
    pad = np.zeros(((h + 1) * w1, bpp), np.int16)   # one row and one column of zeros before the image
    x_all = rows.reshape(h * w, bpp).astype(np.int16)
    f_all = filters.astype(np.int16)
    for d in range(h + w - 1):
        r = np.arange(max(0, d - w + 1), min(h - 1, d) + 1)
        j = d - r
        idx = (r + 1) * w1 + j + 1
        a, b, c = pad[idx - 1], pad[idx - w1], pad[idx - w1 - 1]
        f = f_all[r][:, None]
        pa, pb, pc = np.abs(b - c), np.abs(a - c), np.abs(a + b - 2 * c)
        paeth = np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c))
        pred = np.select([f == 1, f == 2, f == 3, f == 4], [a, b, (a + b) >> 1, paeth], 0)
        pad[idx] = (x_all[r * w + j] + pred) & 255
    return pad.reshape(h + 1, w1, bpp)[1:, 1:].reshape(h, stride).astype(np.uint8)


def read_png(path, allow_sealed=False):
    """A gray PNG (8 or 16 bit) as a 2D uint8 or uint16 array, decoded with zlib and numpy. A sealed file (above)
    is refused unless allow_sealed."""
    np = _numpy()
    blob = Path(path).read_bytes()
    if blob[:8] != PNG_SIGNATURE:
        raise VerifyError(f"{path}: not a PNG")
    sealed_refuse(blob, str(path), allow_sealed)
    pos, idat, header = 8, [], None
    while pos + 8 <= len(blob):
        n = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag, payload = blob[pos + 4:pos + 8], blob[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            if len(payload) != 13:
                raise VerifyError(f"{path}: corrupt PNG header")
            header = struct.unpack(">IIBBBBB", payload)
        elif tag == b"IDAT":
            idat.append(payload)
        elif tag == b"IEND":
            break
        pos += 12 + n
    if header is None or not idat:
        raise VerifyError(f"{path}: PNG without IHDR or IDAT")
    w, h, depth, color, _, _, interlace = header
    if not (w and h):
        raise VerifyError(f"{path}: empty PNG ({w} x {h})")
    if color not in PNG_CHANNELS or depth not in (8, 16) or interlace:
        raise VerifyError(f"{path}: only 8 or 16-bit gray (or gray-valued color), non-interlaced PNG is read "
                          f"(bit depth {depth}, color type {color}, interlace {interlace})")
    channels = PNG_CHANNELS[color]
    bpp = channels * depth // 8
    stride = w * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise VerifyError(f"{path}: corrupt PNG data: {exc}") from exc
    if len(raw) < h * (stride + 1):
        raise VerifyError(f"{path}: PNG data holds {len(raw)} bytes, {h * (stride + 1)} expected")
    rows = np.frombuffer(raw, np.uint8, h * (stride + 1)).reshape(h, stride + 1)
    data = _png_unfilter(np, np.ascontiguousarray(rows[:, 1:]), rows[:, 0], bpp)
    if depth == 16:
        data = data.view(">u2").astype(np.uint16)
    data = data.reshape(h, w, channels)
    colours = data[..., :3] if channels >= 3 else data[..., :1]
    if colours.shape[-1] > 1 and not (colours == colours[..., :1]).all():
        raise VerifyError(f"{path}: a color PNG whose channels differ is not an ink map")
    return np.ascontiguousarray(data[..., 0])


def load_map(path):
    np = _numpy()
    try:
        with open(path, "rb") as fh:
            is_png = fh.read(8) == PNG_SIGNATURE
    except OSError as exc:
        raise VerifyError(f"cannot read {path}: {exc}") from exc
    if is_png:
        return read_png(path)
    try:
        import tifffile
    except ImportError as exc:
        raise VerifyError("tifffile is required (it is in villa's environment)") from exc
    try:
        array = tifffile.imread(str(path))
    except Exception as exc:  # tifffile raises several types, e.g. for LZW without imagecodecs
        raise VerifyError(f"cannot read {path}: {exc}") from exc
    array = np.squeeze(array)
    if array.ndim != 2:
        raise VerifyError(f"{path}: expected a 2D map, got shape {array.shape}")
    return array


def compare(reference, candidate, tolerance=DEFAULT_TOLERANCE, factor=1.0):
    """Statistics of candidate minus reference, computed in row blocks to bound memory; both are multiplied by
    factor first (255 puts two 0 to 1 maps on the gray levels the tolerance counts)."""
    np = _numpy()
    if reference.shape != candidate.shape:
        return {"shape_match": False, "reference_shape": list(reference.shape),
                "candidate_shape": list(candidate.shape)}
    n = reference.size
    max_abs = 0.0
    sum_abs = 0.0
    over = 0
    sx = sy = sxx = syy = sxy = 0.0
    for start in range(0, reference.shape[0], ROWS_PER_BLOCK):
        a = reference[start:start + ROWS_PER_BLOCK].astype(np.float64) * factor
        b = candidate[start:start + ROWS_PER_BLOCK].astype(np.float64) * factor
        d = np.abs(b - a)
        # NaN or inf in one map and not the other is a disagreement: d is then NaN or inf, and
        # max() and "d > tolerance" would both pass a NaN by. Equal values (inf and inf) or NaN in
        # both maps at the same pixel agree.
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        bad = ~(d <= tolerance) & ~same
        d = np.where(same, 0.0, d)
        if bad.any() and not np.isfinite(d[bad]).all():
            max_abs = math.inf
        max_abs = max(max_abs, float(d.max()))
        sum_abs += float(d.sum())
        over += int(bad.sum())
        sx += float(a.sum())
        sy += float(b.sum())
        sxx += float((a * a).sum())
        syy += float((b * b).sum())
        sxy += float((a * b).sum())
    cov = sxy - sx * sy / n
    var_a = sxx - sx * sx / n
    var_b = syy - sy * sy / n
    pearson = cov / math.sqrt(var_a * var_b) if var_a > 0 and var_b > 0 else None
    return {
        "shape_match": True,
        "shape": list(reference.shape),
        "pixels": n,
        "tolerance": tolerance,
        "max_abs_diff": max_abs,
        "mean_abs_diff": sum_abs / n,
        "pixels_over_tolerance": over,
        "fraction_over_tolerance": over / n,
        "pearson": pearson,
    }


def agrees(stats, max_fraction=DEFAULT_MAX_FRACTION):
    return bool(stats.get("shape_match")) and stats["fraction_over_tolerance"] <= max_fraction


def verdict(candidate_agrees, control_agrees=None):
    if not candidate_agrees:
        return FAIL
    if control_agrees is None:
        return PASS_UNCONTROLLED
    if control_agrees:
        return CONTROL_NOT_CAUGHT
    return PASS


def _gray_factor(np, reference, candidate, control=None):
    """255 when the maps are float maps in 0 to 1, so the tolerance counts gray levels as it does on villa's uint8
    maps (on 0 to 1 a tolerance of 2 let any candidate agree; audit, 22 Oct 2026); else 1. A 0 to 1 map beside a
    uint8 or uint16 map, or a uint8 beside a uint16 map, is refused: they differ by up to 255 everywhere. A float
    map holding gray levels (0 to 255) may still be compared with a uint8 one, and a blank map with any."""
    # kit.mapscale's rule, inlined: the AutoPipeline Space stages verify.py without mapscale.py
    maps = [reference, candidate] + ([control] if control is not None else [])

    def scale(m):
        d = np.asarray(m).dtype
        if d.kind == "u" and d.itemsize in (1, 2):
            return "u8" if d.itemsize == 1 else "u16"
        if d.kind != "f":
            return None
        v = np.asarray(m)
        lo, hi = (float(np.fmin.reduce(v, axis=None)), float(np.fmax.reduce(v, axis=None))) if v.size else (0.0, 0.0)
        if lo != lo or hi == 0:
            return None                      # all NaN or all zero: fits any scale
        return "unit" if lo >= 0 and hi <= 1 + UNIT_SLACK else "float"
    found = {scale(m) for m in maps} - {None}
    if ("unit" in found and found & {"u8", "u16"}) or {"u8", "u16"} <= found:
        raise VerifyError(f"the maps are on different scales ({', '.join(sorted(found))}); compare maps of one scale "
                          "(kit.mapscale.to_u8 puts a 0 to 1 map on villa's uint8 grid)")
    floats = all(np.asarray(m).dtype.kind == "f" for m in maps)
    return 255.0 if floats and found == {"unit"} else 1.0


def verify_arrays(reference, candidate, control=None, tolerance=DEFAULT_TOLERANCE,
                  max_fraction=DEFAULT_MAX_FRACTION):
    np = _numpy()
    if reference.dtype.kind == "f" and reference.size and not np.isfinite(reference).any():
        # NaN at the same pixel counts as agreement, so an all-NaN candidate (both devices overflowing,
        # say) would agree with an all-NaN reference and any finite control would look caught
        raise VerifyError("the reference map has no finite values; a broken reference cannot show agreement")
    factor = _gray_factor(np, reference, candidate, control)
    result = {"candidate": compare(reference, candidate, tolerance, factor), "max_fraction": max_fraction}
    if factor != 1.0:
        result["scaled_from_0_1"] = True
    result["candidate_agrees"] = agrees(result["candidate"], max_fraction)
    control_agrees = None
    if control is not None:
        if control.shape != reference.shape:
            # A control of another shape would "disagree" by shape alone and turn any candidate
            # into a pass; it shows nothing about whether the comparison can fail.
            raise VerifyError(f"control shape {tuple(control.shape)} differs from the reference's "
                              f"{tuple(reference.shape)}; the control must be the same map made wrongly")
        result["control"] = compare(reference, control, tolerance, factor)
        control_agrees = agrees(result["control"], max_fraction)
        result["control_agrees"] = control_agrees
    result["verdict"] = verdict(result["candidate_agrees"], control_agrees)
    return result


def verify_files(reference, candidate, control=None, tolerance=DEFAULT_TOLERANCE,
                 max_fraction=DEFAULT_MAX_FRACTION):
    result = verify_arrays(
        load_map(reference), load_map(candidate),
        None if control is None else load_map(control),
        tolerance, max_fraction,
    )
    result["files"] = {"reference": str(reference), "candidate": str(candidate),
                       "control": None if control is None else str(control)}
    return result


EXPLAIN = {
    PASS: "candidate agrees with the reference, and the control was caught",
    PASS_UNCONTROLLED: "candidate agrees, but no control was given, so this comparison was not shown able to fail",
    FAIL: "candidate does not agree with the reference",
    CONTROL_NOT_CAUGHT: "the control also agreed, so this comparison cannot tell maps apart; it proves nothing",
}


def format_result(result):
    def line(label, stats):
        if not stats.get("shape_match"):
            return f"{label}: shape mismatch {stats['reference_shape']} vs {stats['candidate_shape']}"
        pearson = "n/a" if stats["pearson"] is None else f"{stats['pearson']:.6f}"
        return (f"{label}: max |diff| {stats['max_abs_diff']:.0f}, mean {stats['mean_abs_diff']:.4f}, "
                f"{stats['fraction_over_tolerance']:.6%} of pixels over {stats['tolerance']}, pearson {pearson}")

    rows = [line("candidate", result["candidate"])]
    if "control" in result:
        rows.append(line("control  ", result["control"]))
    rows.append(f"verdict: {result['verdict']} ({EXPLAIN[result['verdict']]})")
    return "\n".join(rows)
