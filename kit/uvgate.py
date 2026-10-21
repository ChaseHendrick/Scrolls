"""Parameter-domain sheet gate with an optional NumPy spatial index. Not a reading.

uv_overlap_gate fails on any positive-area interior intersection of two
triangles in the parameter domain and fails when nothing was measured.
coverage_verdict fails when the sum of triangle areas is under a stated
fraction of the source area. Overlaps are not subtracted from that sum.

Community tool gap, checked 2026-10-21 against Hob3rMallow/scrollfiesta_public
at bce8a65: its ribbon_verdict counts lattice cells covered twice by vertex
position but does not measure triangle interior overlap area, and the sheet
stage of sheet_assemble returns 0 even when ribbon_verdict's gates fail.
"""

from __future__ import annotations

import csv
from fractions import Fraction
from io import StringIO
from numbers import Integral


class UvGateError(ValueError):
    pass


def uv_overlap_gate(triangles, abs_eps=1e-12, *, method="auto", collect_pairs=False):
    """Pass when some triangle has area and no pair overlaps above abs_eps.

    ``auto`` uses a NumPy spatial grid when available. ``reference`` retains
    the original exact all-pairs implementation for comparison. ``grid``
    requires NumPy, but falls back to the reference for unusual numeric types
    or ranges that cannot be safely indexed. Exact clipping decides all hits.
    ``collect_pairs`` additionally returns every hit as sorted index pairs.

    Typical similarly sized triangles have bounded grid occupancy, giving
    near-linear candidate work. Dense overlaps or very unequal sizes can still
    require quadratic work: the number of overlapping pairs can itself be
    quadratic. Shared edges/vertices have zero interior intersection area.
    """
    if method not in {"auto", "grid", "reference"}:
        raise ValueError("method must be auto, grid, or reference")
    if method == "reference":
        return _reference_gate(triangles, abs_eps, collect_pairs)
    try:
        import numpy as np
    except ImportError:
        if method == "grid":
            raise
        return _reference_gate(triangles, abs_eps, collect_pairs)
    # Keep original values for the exact fallback. Do not coerce Fractions,
    # Decimals, numeric strings or large integers through a lossy float cast.
    if not isinstance(triangles, (list, tuple, np.ndarray)):
        triangles = list(triangles)
    try:
        values = np.asarray(triangles)
    except (ValueError, TypeError):
        return _reference_gate(triangles, abs_eps, collect_pairs)
    if (values.ndim != 3 or values.shape[1:] != (3, 2)
            or values.dtype.kind not in "fiu"
            or (values.dtype.kind == "f" and values.dtype.itemsize != 8)
            or (values.dtype.kind in "iu" and values.size
                and (np.any(values > 2**53) or np.any(values < -(2**53))))):
        return _reference_gate(triangles, abs_eps, collect_pairs)
    if (not isinstance(triangles, np.ndarray) and values.dtype.kind == "f"
            and np.any(np.abs(values) >= 2**53)):
        return _reference_gate(triangles, abs_eps, collect_pairs)
    if not np.isfinite(values).all():
        return _reference_gate(triangles, abs_eps, collect_pairs)
    # A negative tolerance makes even zero-area intersections hits in the
    # original implementation, so disjoint pairs must not be culled.
    try:
        negative_limit = Fraction(abs_eps) < 0
    except (TypeError, ValueError, OverflowError):
        return _reference_gate(triangles, abs_eps, collect_pairs)
    if negative_limit:
        return _reference_gate(triangles, abs_eps, collect_pairs)
    return _grid_gate(values.astype(np.float64, copy=False), abs_eps, collect_pairs)


def _result(positive, degenerate, hits, witness, pairs):
    result = {
        "pass": bool(positive and hits == 0),
        "pairs": hits,
        "degenerate": degenerate,
        "witness": witness,
        "rule": ("fail when any pair has interior intersection area above abs_eps"
                 if positive else "fail when no triangle has positive area"),
    }
    if pairs is not None:
        result["overlapping_pairs"] = sorted(pairs)
    return result


def _reference_gate(triangles, abs_eps, collect_pairs):
    """Original Fraction preparation and all-pairs clipping oracle."""
    tris = [_prepare(tri) for tri in triangles]
    degenerate = sum(1 for area, _ in tris if area == 0)
    positive = [(i, poly) for i, (area, poly) in enumerate(tris) if area > 0]
    hits, witness = 0, None
    pairs = [] if collect_pairs else None
    if positive:
        limit = Fraction(abs_eps)
        for a in range(len(positive)):
            i, poly_i = positive[a]
            for b in range(a + 1, len(positive)):
                j, poly_j = positive[b]
                area = _poly_area(_clip(poly_i, poly_j))
                if area > limit:
                    hits += 1
                    if witness is None:
                        witness = (i, j, float(area))
                    if pairs is not None:
                        pairs.append((i, j))
    return _result(len(positive), degenerate, hits, witness, pairs)


def _orientation(a, b, c, integer_exact=False):
    """Return determinant and a conservative mask of reliable floating signs.

    The orient2d first-stage error bound is (3 + 16u)u times the sum
    of absolute products, u=2**-53. Uncertain signs are never used to cull.
    The absolute floor also makes subnormal product rounding inconclusive.
    Small integral coordinates have exact differences/products/determinants.
    """
    import numpy as np
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        left = (a[..., 0] - c[..., 0]) * (b[..., 1] - c[..., 1])
        right = (a[..., 1] - c[..., 1]) * (b[..., 0] - c[..., 0])
        det = left - right
        if integer_exact:
            return det, np.ones(det.shape, dtype=bool)
        bound = (np.abs(left) + np.abs(right)) * 3.3306690738754716e-16 + 1e-300
        reliable = np.isfinite(det) & (np.abs(det) > bound)
    # These equalities prove exact collinearity, without relying on a rounded
    # zero determinant. They include the shared vertices of adjacent faces.
    zero = (((a == c).all(axis=-1)) | ((b == c).all(axis=-1))
            | ((a == b).all(axis=-1))
            | ((a[..., 0] == b[..., 0]) & (b[..., 0] == c[..., 0]))
            | ((a[..., 1] == b[..., 1]) & (b[..., 1] == c[..., 1])))
    return np.where(zero, 0.0, det), reliable | zero


def _interior_candidates(a, b, integer_exact):
    """Conservatively discard pairs separated by an edge of either triangle."""
    import numpy as np
    keep = np.ones(len(a), dtype=bool)
    for subject, other in ((a, b), (b, a)):
        for edge in range(3):
            det, reliable = _orientation(subject[:, edge, None, :],
                                          subject[:, (edge + 1) % 3, None, :],
                                          other, integer_exact)
            keep &= ~np.all(reliable & (det <= 0), axis=1)
    return keep


def _grid_gate(values, abs_eps, collect_pairs):
    import math
    import numpy as np

    # Exact arithmetic for lattice coordinates up to this bound: differences
    # <=2**26, products <=2**52, determinant <=2**53, all representable.
    integer_exact = bool(np.all(np.abs(values) <= 2**25)
                         and np.all(values == np.floor(values)))
    det, reliable = _orientation(values[:, 0], values[:, 1], values[:, 2], integer_exact)
    sign = np.sign(det)
    exact = {}
    for i in np.flatnonzero(~reliable):
        area, poly = _prepare(values[i])
        exact[int(i)] = poly
        exact_det = _cross(*tuple(_point(p) for p in values[i]))
        sign[i] = (exact_det > 0) - (exact_det < 0)
    valid = np.flatnonzero(sign != 0)
    degenerate = len(values) - len(valid)
    pairs = [] if collect_pairs else None
    if not len(valid):
        return _result(0, degenerate, 0, None, pairs)
    limit = Fraction(abs_eps)
    # Own this compact, CCW copy. Do not mutate caller arrays.
    tris = values[valid].copy()
    reverse = sign[valid] < 0
    tris[reverse] = tris[reverse][:, [0, 2, 1], :]
    low, high = tris.min(axis=1), tris.max(axis=1)
    with np.errstate(over="ignore", invalid="ignore"):
        width = (high - low).max(axis=1)
    typical = float(np.median(width))
    if not math.isfinite(typical) or typical <= 0:
        return _reference_gate(values, abs_eps, collect_pairs)
    exponent = math.ceil(math.log2(typical))
    # Keep cell indices exactly representable and away from int64 overflow.
    largest = float(np.max(np.abs(tris)))
    if largest:
        exponent = max(exponent, math.ceil(math.log2(largest)) - 48)
    if not -400 <= exponent <= 400:
        return _reference_gate(values, abs_eps, collect_pairs)
    while True:
        scaled_low = np.ldexp(low, -exponent)
        scaled_high = np.ldexp(high, -exponent)
        # Power-of-two scaling is exact in the normal range. Check round trips
        # before using half-open cells, including for subnormal coordinates.
        if (not np.array_equal(np.ldexp(scaled_low, exponent), low)
                or not np.array_equal(np.ldexp(scaled_high, exponent), high)):
            return _reference_gate(values, abs_eps, collect_pairs)
        cell_low = np.floor(scaled_low).astype(np.int64)
        cell_high = np.ceil(scaled_high).astype(np.int64) - 1
        span = cell_high - cell_low + 1
        counts_float = span[:, 0].astype(float) * span[:, 1]
        if counts_float.max() <= 4096 and counts_float.sum() <= 8 * len(tris):
            break
        exponent += 1
    counts = span[:, 0] * span[:, 1]
    total = int(counts.sum())
    ids = np.repeat(np.arange(len(tris)), counts)
    offset = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
    cell_x = cell_low[ids, 0] + offset // span[ids, 1]
    cell_y = cell_low[ids, 1] + offset % span[ids, 1]
    order = np.lexsort((cell_y, cell_x))
    ids, cell_x, cell_y = ids[order], cell_x[order], cell_y[order]
    starts = np.r_[0, np.flatnonzero((cell_x[1:] != cell_x[:-1])
                                    | (cell_y[1:] != cell_y[:-1])) + 1]
    sizes = np.diff(np.r_[starts, total])
    active = np.flatnonzero(sizes > 1)
    # Release construction arrays before candidate batches increase the peak.
    del offset, order, scaled_low, scaled_high, cell_high, span, counts_float, counts
    hits, witness = 0, None
    distance = 1
    while len(active):
        lengths = sizes[active] - distance
        batch_starts = starts[active]
        positions = (np.repeat(batch_starts, lengths) + np.arange(int(lengths.sum()))
                     - np.repeat(np.cumsum(lengths) - lengths, lengths))
        for start in range(0, len(positions), 65536):
            pos = positions[start:start + 65536]
            first, second = ids[pos], ids[pos + distance]
            # Each pair belongs only to its lexicographically first shared
            # cell. This removes duplicates without an unbounded pair set.
            own = ((cell_x[pos] == np.maximum(cell_low[first, 0], cell_low[second, 0]))
                   & (cell_y[pos] == np.maximum(cell_low[first, 1], cell_low[second, 1])))
            first, second = first[own], second[own]
            bbox = np.all(np.minimum(high[first], high[second])
                          > np.maximum(low[first], low[second]), axis=1)
            first, second = first[bbox], second[bbox]
            candidate = _interior_candidates(tris[first], tris[second], integer_exact)
            for a, b in zip(first[candidate], second[candidate]):
                i, j = sorted((int(valid[a]), int(valid[b])))
                if i not in exact:
                    exact[i] = _prepare(values[i])[1]
                if j not in exact:
                    exact[j] = _prepare(values[j])[1]
                area = _poly_area(_clip(exact[i], exact[j]))
                if area > limit:
                    hits += 1
                    if witness is None or (i, j) < witness[:2]:
                        witness = (i, j, float(area))
                    if pairs is not None:
                        pairs.append((i, j))
        distance += 1
        active = active[sizes[active] > distance]
    return _result(len(valid), degenerate, hits, witness, pairs)


def triangle_area(tri):
    """Absolute area of a triangle given as three (x, y) points."""
    (x1, y1), (x2, y2), (x3, y3) = tri
    return abs(x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)) / 2.0


def coverage_fraction(triangles, source_area):
    """Sum of triangle areas divided by source_area. Raises if source_area is not positive."""
    if source_area <= 0:
        raise UvGateError("source_area must be positive")
    return sum(triangle_area(tri) for tri in triangles) / source_area


def coverage_verdict(triangles, source_area, min_fraction=0.90):
    """Pass only when coverage_fraction is at least min_fraction."""
    fraction = coverage_fraction(triangles, source_area)
    return {
        "pass": fraction >= min_fraction,
        "fraction": fraction,
        "min_fraction": min_fraction,
        "rule": "pass only if summed triangle area over source_area is at least min_fraction",
    }


def sheet_verdict(triangles, source_area, min_fraction=0.90, abs_eps=1e-12):
    """Pass only when both the overlap gate and the coverage gate pass."""
    overlap = uv_overlap_gate(triangles, abs_eps=abs_eps)
    coverage = coverage_verdict(triangles, source_area, min_fraction=min_fraction)
    return {
        "pass": overlap["pass"] and coverage["pass"],
        "overlap": overlap,
        "coverage": coverage,
    }


def load_uv_csv(text: str):
    """Load triangles from CSV text with header tri,u,v.

    Rows that share a tri id form one triangle. Ids stay in first-seen order.
    Each id must have exactly three rows. Empty text or a header-only file
    returns an empty list.
    """
    if text.strip() == "":
        return []
    rows = list(csv.reader(StringIO(text)))
    if not rows:
        return []
    header = [cell.strip() for cell in rows[0]]
    if header != ["tri", "u", "v"]:
        raise UvGateError("bad header")
    groups = {}
    order = []
    for row in rows[1:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) < 3:
            raise UvGateError("row must have tri, u, and v")
        tri_id = row[0].strip()
        try:
            u = float(row[1].strip())
            v = float(row[2].strip())
        except ValueError:
            raise UvGateError("non-numeric coordinate")
        if tri_id not in groups:
            order.append(tri_id)
            groups[tri_id] = []
        groups[tri_id].append((u, v))
    triangles = []
    for tri_id in order:
        points = groups[tri_id]
        if len(points) != 3:
            raise UvGateError("triangle must have 3 points")
        triangles.append(tuple(points))
    return triangles


def _prepare(triangle):
    if len(triangle) != 3:
        raise UvGateError("triangle must have 3 points")
    points = tuple(_point(p) for p in triangle)
    area2 = _cross(points[0], points[1], points[2])
    if area2 < 0:
        points = (points[0], points[2], points[1])
        area2 = -area2
    return area2 / 2, points


def _point(p):
    if len(p) != 2:
        raise UvGateError("point must be (x, y)")
    # NumPy integers must not remain fixed-width Fraction numerators.
    return tuple(Fraction(int(v) if isinstance(v, Integral) else v) for v in p)


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _clip(subject, clip):
    output = list(subject)
    for i in range(3):
        if not output:
            return []
        edge_a = clip[i]
        edge_b = clip[(i + 1) % 3]
        incoming = output
        output = []
        previous = incoming[-1]
        for current in incoming:
            current_in = _cross(edge_a, edge_b, current) >= 0
            previous_in = _cross(edge_a, edge_b, previous) >= 0
            if current_in:
                if not previous_in:
                    output.append(_line_hit(previous, current, edge_a, edge_b))
                output.append(current)
            elif previous_in:
                output.append(_line_hit(previous, current, edge_a, edge_b))
            previous = current
    return output


def _line_hit(p, q, a, b):
    rx, ry = q[0] - p[0], q[1] - p[1]
    sx, sy = b[0] - a[0], b[1] - a[1]
    denom = rx * sy - ry * sx
    if denom == 0:
        if _cross(a, b, p) == 0:
            return p
        return q
    t = ((a[0] - p[0]) * sy - (a[1] - p[1]) * sx) / denom
    return (p[0] + t * rx, p[1] + t * ry)


def _poly_area(poly):
    if len(poly) < 3:
        return Fraction(0)
    acc = Fraction(0)
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        acc += x1 * y2 - x2 * y1
    return abs(acc) / 2
