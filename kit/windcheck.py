"""Winding coverage: how deep a point on a CT slice sits in the scroll's rolled sheet, read from the slice's traced
papyrus sheets alone, with no person's center line. kit/axispolish.py moves a center line by it.

Seen from a point, every wrap of the sheet that encloses the point sweeps a full turn, 2 pi, whatever its shape or
distance; a wrap the point lies outside sweeps less (a circle of radius rho seen from distance r > rho sweeps
4 asin(rho / r) when its arcs are summed without sign). So the summed absolute angle that all traced sheet segments
subtend at the point, divided by 2 pi, counts the wraps around it: it is highest inside the innermost wrap and falls by
about 0.64 for every wrap of pitch the point moves out (for concentric circles the deficit is (2/pi)(r/b) for a point
at distance r from the center of circles of pitch b). `coverage` returns that count in wraps (one per wrap when each
wrap is traced once).

The traces are a slice's polylines from a normal grid (villa's vc_gen_normalgrids output, read by
kit.axispolish.read_grid: level-0 x and y), so a coverage is a Measurement against a model's sheet predictions, never
against the true axis. A missing trace far from two nearby points lowers both their coverages by almost the same
amount, so the difference between two points on one slice is what the check reads; inside a hollow core, where no
trace passes, coverage is nearly flat and the check cannot rank two points there. numpy inside the functions;
standard library at import.
"""

import math

NEAR_VOXELS = 0.5   # a segment that passes this close to the point is left out: its sweep is undefined


def _np():
    import numpy
    return numpy


def segments(lines):
    """(P, Q): the consecutive point pairs of every polyline, as float arrays (n, 2) of x, y."""
    np = _np()
    ps, qs = [], []
    for ln in lines:
        a = np.asarray(ln, dtype=float).reshape(-1, 2)
        if len(a) >= 2:
            ps.append(a[:-1])
            qs.append(a[1:])
    if not ps:
        return np.zeros((0, 2)), np.zeros((0, 2))
    return np.vstack(ps), np.vstack(qs)


def coverage(segs, point):
    """Summed absolute angle the segments subtend at point (x, y), in turns (wraps around the point)."""
    np = _np()
    p, q = segs
    if len(p) == 0:
        return 0.0
    c = np.array([float(point[0]), float(point[1])])
    a = np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])
    b = np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0])
    d = np.abs((b - a + math.pi) % (2 * math.pi) - math.pi)
    v = q - p
    t = np.clip(((c - p) * v).sum(1) / np.maximum((v * v).sum(1), 1e-12), 0.0, 1.0)
    near = np.hypot(*(p + t[:, None] * v - c).T) < NEAR_VOXELS
    return float(d[~near].sum() / (2 * math.pi))


def ring(segs, point, radius, n=8):
    """Coverages at n points on a circle of radius (voxels) about point, starting on +x: the sensitivity control."""
    return [coverage(segs, (point[0] + radius * math.cos(2 * math.pi * k / n),
                            point[1] + radius * math.sin(2 * math.pi * k / n))) for k in range(n)]


def best_near(segs, points, radius, step):
    """The highest coverage on a square grid of spacing step within radius (voxels) of any of points: (coverage,
    (x, y)). Reported beside the arms, never in a verdict."""
    best = None
    n = int(radius // step)
    for px, py in points:
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                if i * i + j * j > n * n:
                    continue
                q = (px + i * step, py + j * step)
                v = coverage(segs, q)
                if best is None or v > best[0]:
                    best = (v, q)
    return best


def spiral(centre, pitch, turns, step=2.0, start=0.0):
    """A synthetic Archimedean spiral polyline about center, r = start + pitch * theta / (2 pi), points about step
    apart (tests and the self-check)."""
    np = _np()
    pts, th = [], 0.0
    stop = 2 * math.pi * turns
    while th <= stop:
        r = start + pitch * th / (2 * math.pi)
        pts.append((centre[0] + r * math.cos(th), centre[1] + r * math.sin(th)))
        th += step / max(r, step)
    return np.array(pts)


def selfcheck():
    """On a synthetic spiral of 20 wraps, pitch 40 voxels: coverage falls strictly from the center to 2, 5 and 10
    wraps out; the same holds for a spiral squashed to half height (a flattened scroll); and with 40% of the
    segments dropped at random the center still reads above a point 3 wraps out."""
    np = _np()
    sp = spiral((1000.0, 1000.0), 40.0, 20)
    segs = segments([sp])
    at = [coverage(segs, (1000.0 + 40.0 * k, 1000.0)) for k in (0, 2, 5, 10)]
    sq = sp.copy()
    sq[:, 1] = 1000.0 + (sq[:, 1] - 1000.0) * 0.5
    sqs = segments([sq])
    flat = [coverage(sqs, (1000.0 + 40.0 * k, 1000.0)) for k in (0, 2, 5)]
    rng = np.random.default_rng(20261016)
    p, q = segs
    keep = rng.random(len(p)) > 0.4
    thin = (p[keep], q[keep])
    t0, t3 = coverage(thin, (1000.0, 1000.0)), coverage(thin, (1120.0, 1000.0))
    falls = all(x > y for x, y in zip(at, at[1:])) and all(x > y for x, y in zip(flat, flat[1:]))
    return {"passes": bool(falls and t0 > t3), "coverage": [round(v, 3) for v in at],
            "flattened": [round(v, 3) for v in flat], "thinned": {"centre": round(t0, 3), "three_wraps": round(t3, 3)}}
