"""Coverage polish of an estimated scroll axis: AutoPipeline's umbilicus.polish (added 22 Oct 2026).

On each polished slice the axis point moves to the deepest place within 8 mm of the estimate, deepest by winding
coverage (kit/windcheck.py: how many wraps of the slice's traced sheet sweep a full turn round a point) on the
scan's published normal grids. A coarse grid of 0.4 mm over the disc, then a fine grid of 0.05 mm within 0.5 mm of
the coarse best, the highest coverage kept; a slice whose grid holds fewer than 500 traced segments is skipped; the
polished points go through AutoPipeline's robust_axis (window 5). It is the polish of
a script of the source repository (frozen rule version 1, digest 71d431b3), with the same numbers; tests hold the two
equal on synthetic slices.

Evidence: a frozen test of the source repository compared the scroll centre finder's line, polished so, with
villa's vc_gen_umbilicus by winding coverage at slices the polish never read. Model output, measured on villa's own
predicted sheets: not a claim about the true axis. The polish of any other estimator's axis (villa, normals) is untested.

numpy inside the functions (standard library at import); numba, when installed, computes the same sums compiled
(about 8 times faster; tests hold them equal to windcheck.coverage).
"""

import math
from pathlib import Path

from . import windcheck

VERSION = 1
# The polish of a script of the source repository RULE (frozen 22 Oct 2026); a test of the source repository holds them equal
RULE = {"version": VERSION, "radius_mm": 8.0, "coarse_mm": 0.4, "fine_radius_mm": 0.5, "fine_mm": 0.05,
        "min_segments": 500, "window": 5}
# The plan setting (OPTIONAL["umbilicus.polish"] in kit/autopipe.py): the rule version and one polished slice every
# `every` slices. The test polished slices 50 and 100 above and below each scored slice, so its line was read between
# polished slices at most 100 apart: 100 keeps AutoPipeline's line inside that
DEFAULTS = {"version": VERSION, "every": 100}
LABEL = ("Model output: coverage polish of the estimated axis on the scan's published normal grids (kit/axispolish.py, "
         "winding coverage of villa's predicted sheets), not a measurement of the true axis")


class PolishError(Exception):
    pass


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise PolishError("the coverage polish needs numpy in kit's Python") from exc
    return numpy


_NB = []


def _kernel():
    """The compiled coverage sum, or None without numba (compiled once per process)."""
    if not _NB:
        try:
            import numba
        except ImportError:
            _NB.append(None)
            return None
        np = _np()

        @numba.njit(parallel=True)
        def cov(px, py, qx, qy, cx, cy, near):
            n, m = cx.shape[0], px.shape[0]
            out = np.zeros(n)
            for k in numba.prange(n):
                s, x0, y0 = 0.0, cx[k], cy[k]
                for i in range(m):
                    vx, vy = qx[i] - px[i], qy[i] - py[i]
                    vv = max(vx * vx + vy * vy, 1e-12)
                    t = min(1.0, max(0.0, ((x0 - px[i]) * vx + (y0 - py[i]) * vy) / vv))
                    fx, fy = px[i] + t * vx - x0, py[i] + t * vy - y0
                    if math.sqrt(fx * fx + fy * fy) < near:
                        continue
                    d = (math.atan2(qy[i] - y0, qx[i] - x0) - math.atan2(py[i] - y0, px[i] - x0) + math.pi) \
                        % (2 * math.pi)
                    s += abs(d - math.pi)
                out[k] = s / (2 * math.pi)
            return out
        _NB.append(cov)
    return _NB[0]


def coverage_many(segs, pts, use_numba=True):
    """windcheck.coverage at every point of pts (n, 2) of x, y, in wraps."""
    np = _np()
    p, q = segs
    pts = np.asarray(pts, float).reshape(-1, 2)
    if len(p) == 0:
        return np.zeros(len(pts))
    kern = _kernel() if use_numba else None
    if kern is not None:
        c = np.ascontiguousarray
        return kern(c(p[:, 0]), c(p[:, 1]), c(q[:, 0]), c(q[:, 1]), c(pts[:, 0]), c(pts[:, 1]),
                    windcheck.NEAR_VOXELS)
    out = np.zeros(len(pts))
    v = q - p
    vv = np.maximum((v * v).sum(1), 1e-12)
    for i in range(0, len(pts), 32):
        c = pts[i:i + 32][:, None, :]
        a = np.arctan2(p[None, :, 1] - c[..., 1], p[None, :, 0] - c[..., 0])
        b = np.arctan2(q[None, :, 1] - c[..., 1], q[None, :, 0] - c[..., 0])
        d = np.abs((b - a + math.pi) % (2 * math.pi) - math.pi)
        t = np.clip(((c - p[None]) * v[None]).sum(2) / vv[None], 0, 1)
        foot = p[None] + t[..., None] * v[None]
        d[np.hypot(foot[..., 0] - c[..., 0], foot[..., 1] - c[..., 1]) < windcheck.NEAR_VOXELS] = 0
        out[i:i + 32] = d.sum(1) / (2 * math.pi)
    return out


def disc(centre, radius, step):
    """Points of a square grid of spacing step inside a disc, the centre included."""
    np = _np()
    n = int(radius // step)
    ij = [(i, j) for i in range(-n, n + 1) for j in range(-n, n + 1) if i * i + j * j <= n * n]
    return np.array([(centre[0] + i * step, centre[1] + j * step) for i, j in ij])


def polish_point(segs, guess, voxel_um, rule=RULE):
    """The polished point of one slice: ((x, y), its coverage, the guess's coverage)."""
    mm = 1000.0 / voxel_um
    pts = disc(guess, rule["radius_mm"] * mm, rule["coarse_mm"] * mm)
    cov = coverage_many(segs, pts)
    best = pts[int(cov.argmax())]
    pts = disc(best, rule["fine_radius_mm"] * mm, rule["fine_mm"] * mm)
    cov = coverage_many(segs, pts)
    k = int(cov.argmax())
    g = float(coverage_many(segs, [guess])[0])
    return (float(pts[k][0]), float(pts[k][1])), float(cov[k]), g


def polish_line(guess, heights, segs_at, voxel_um, rule=RULE):
    """guess: the estimated axis [(z, y, x)]; heights: the slices to polish; segs_at(z) -> segments or None.
    Returns (line [(z, y, x)] through robust_axis, or None when fewer than 2 points survive; per-slice records)."""
    from . import autopipe, vc3d_orient
    per, recs = {}, []
    for z in heights:
        segs = segs_at(z)
        n = 0 if segs is None else len(segs[0])
        if n < rule["min_segments"]:
            recs.append({"z": z, "segments": n, "skipped": True})
            continue
        g = vc3d_orient.centre_at(guess, z)
        pt, top, gc = polish_point(segs, g, voxel_um, rule)
        per[z] = pt
        recs.append({"z": z, "segments": n, "guess": [round(g[0], 2), round(g[1], 2)],
                     "point": [round(pt[0], 2), round(pt[1], 2)], "coverage": round(top, 4),
                     "guess_coverage": round(gc, 4),
                     "moved_mm": round(math.hypot(pt[0] - g[0], pt[1] - g[1]) * voxel_um / 1000.0, 4)})
    pts = [(float(z), p[1], p[0]) for z, p in sorted(per.items())]
    if len(pts) < 2:
        return None, recs
    kept, _ = autopipe.robust_axis(pts, window=rule["window"])
    return (kept if len(kept) >= 2 else None), recs


def grid_segments(folder):
    """segs_at(z) over a folder holding xy/NNNNNN.grid (autopipe.fetch_grids): None for a missing or unreadable
    grid."""
    from . import surfacepred
    folder = Path(folder)

    def segs_at(z):
        f = folder / "xy" / f"{int(z):06d}.grid"
        if not f.is_file():
            return None
        try:
            return windcheck.segments(surfacepred.read_grid(f)[1])
        except (OSError, surfacepred.SurfacePredError):
            return None
    return segs_at


def heights(guess, every, z_range=None):
    """The slices to polish: every `every`-th slice inside the guess's z span (and z_range [z0, z1) when given)."""
    z0, z1 = guess[0][0], guess[-1][0]
    if z_range:
        z0, z1 = max(z0, z_range[0]), min(z1, z_range[1] - 1)
    first = int(math.ceil(z0 / every) * every)
    return list(range(first, int(math.floor(z1)) + 1, every))


def check(setting):
    """make_plan's refusals for umbilicus.polish."""
    if not isinstance(setting, dict):
        raise PolishError("umbilicus.polish is an object (or true for its defaults)")
    if setting.get("version") != VERSION:
        raise PolishError(f"umbilicus.polish version {setting.get('version')!r}: this kit polishes by rule "
                          f"version {VERSION}")
    ev = setting.get("every")
    if isinstance(ev, bool) or not isinstance(ev, int) or ev < 1:
        raise PolishError("umbilicus.polish every is a whole number of slices, at least 1")
