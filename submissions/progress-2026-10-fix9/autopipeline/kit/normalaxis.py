"""Scroll axis (umbilicus) from a scan's normal grids, with numpy alone: `python -m kit normalaxis`, the umbilicus
tool's method "normals" and AutoPipeline's umbilicus backend "normals".

Why it exists. AutoPipeline estimates the axis of a scan without a published one with villa's vc_gen_umbilicus
(kit/autopipe.py estimate_umbilicus), so every such run needs a villa build beside kit. villa documents what the
tool does: it scores each candidate point by how radially the slice's normals point away from it (villa
core/src/normalgridtools.cpp, align_and_extract_umbilicus, GPL-3.0). This module is our own implementation of
that idea, written from the description and from geometry, not from villa's code, so it runs anywhere kit runs:
no binary, no seed, the same answer every time, and a confidence for every slice that an agent can act on.

Per slice (the xy GridStore file of one z, as vc_gen_normalgrids writes it; kit.surfacepred.read_grid reads it):

  segments  every step of every polyline (a sheet's trace in the slice) gives a midpoint m, a unit tangent t and
            a length w. A sheet of a rolled scroll runs round the axis, so its normal line (through m, across t)
            passes near the axis: on an Archimedean spiral of pitch p, within p / (2 pi) of it. For a candidate
            center c, sin(theta) = t . (c - m) / |c - m| measures how far the normal at m points off c.
  vote      candidates on a GRID x GRID lattice over the slice's polylines, each scored by the length-weighted sum
            of max(0, 1 - (sin(theta) / TOL)^2) over segments at least R_MIN from it; the best cell is searched
            again on a finer lattice ZOOMS times. A vote, so a minority of segments that point elsewhere (a
            crushed region, a fragment, the case) cannot drag the answer the way a mean would.
  refine    iteratively reweighted least squares on sin(theta) with Tukey's biweight (c = TUKEY_C robust
            deviations): each round solves sum W t t^T c = sum W t t^T m with W = w * biweight / |c - m|^2,
            until the move is under 0.01 voxels.
  check     the median |sin(theta)| of all segments at least R_MIN from the answer (directions at random give
            about 0.7; a spiral of pitch p at radius r gives about p / (2 pi r)), the inlier share (length-weighted
            share of segments with nonzero biweight) and how well the tangents span the plane (the normal
            equations' condition). A slice with fewer than MIN_SEGMENTS segments, a median |sin(theta)| over
            MAX_MEDIAN_SIN, a refinement that does not converge in MAX_ITER rounds or a degenerate system gives no
            estimate, with the reason. On synthetic slices (selfcheck) a spiral squashed to 0.6 of its width in y
            gives 0.35 and is kept; squashed to 0.4 it gives 0.6 and is refused, as are spokes (0.95) and clutter
            alone (0.75).

Across slices the caller drops outliers with AutoPipeline's robust_axis, the same rule its vc_gen_umbilicus path
uses, so the two backends differ only in the per-slice estimate. Every number here is model output, not a
measurement: check a line on CT before relying on it. Standard library plus numpy.
"""

import json
import math
from pathlib import Path

VERSION = 1                 # bump when a rule below changes: a stored estimate names the version that made it
GRID = 33                   # vote lattice per side
ZOOMS = 3                   # finer lattices round the best cell
TOL = 0.15                  # |sin(theta)| at which a segment's vote falls to zero
R_MIN = 20.0                # voxels: segments nearer a candidate than this neither vote nor weigh
TUKEY_C = 4.685             # Tukey biweight constant, in robust deviations of sin(theta)
SCALE_FLOOR = 0.01          # least robust deviation of sin(theta)
MAX_ITER = 50
MOVE_TOL = 0.01             # voxels
MIN_SEGMENTS = 20
MAX_MEDIAN_SIN = 0.5         # normals typically more than 30 degrees off the answer: no estimate
MIN_STEP = 2.0              # voxels: shorter polyline steps carry too coarse a direction (integer coordinates)
MAX_COND = 1e6              # largest condition number of the 2 x 2 normal equations taken
RULE = {"version": VERSION, "grid": GRID, "zooms": ZOOMS, "tol": TOL, "r_min": R_MIN, "tukey_c": TUKEY_C,
        "scale_floor": SCALE_FLOOR, "max_iter": MAX_ITER, "move_tol": MOVE_TOL, "min_segments": MIN_SEGMENTS,
        "max_median_sin": MAX_MEDIAN_SIN, "min_step": MIN_STEP, "max_cond": MAX_COND}


class NormalAxisError(Exception):
    pass


def _np():
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - numpy is in every environment that computes
        raise NormalAxisError("the normals method needs numpy") from exc
    return numpy


def segments(lines, min_step=MIN_STEP):
    """Midpoints (N, 2), unit tangents (N, 2) and lengths (N,) of every polyline step at least min_step long.
    lines: polylines of (u, v) points, (x, y) on an xy slice."""
    np = _np()
    mids, tans, lens = [], [], []
    for line in lines:
        p = np.asarray(line, dtype=float).reshape(-1, 2)
        if len(p) < 2:
            continue
        d = np.diff(p, axis=0)
        n = np.hypot(d[:, 0], d[:, 1])
        ok = n >= min_step
        if not ok.any():
            continue
        mids.append((p[:-1][ok] + p[1:][ok]) / 2)
        tans.append(d[ok] / n[ok, None])
        lens.append(n[ok])
    if not mids:
        return np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0)
    return np.vstack(mids), np.vstack(tans), np.concatenate(lens)


def _sin(np, cand, m, t):
    """sin(theta) and distance |c - m| for candidates (K, 2) against segments (N, 2): arrays (K, N)."""
    dx = cand[:, None, 0] - m[None, :, 0]
    dy = cand[:, None, 1] - m[None, :, 1]
    r = np.hypot(dx, dy)
    s = (t[None, :, 0] * dx + t[None, :, 1] * dy) / np.maximum(r, 1e-9)
    return s, r


def vote(m, t, w, lo, hi, grid=GRID, tol=TOL, r_min=R_MIN, block=32):
    """The best candidate on a grid x grid lattice over [lo, hi] (each (x, y)) and its score, and the lattice step."""
    np = _np()
    xs = np.linspace(lo[0], hi[0], grid)
    ys = np.linspace(lo[1], hi[1], grid)
    cand = np.stack(np.meshgrid(xs, ys, indexing="xy"), -1).reshape(-1, 2)
    scores = np.empty(len(cand))
    for i in range(0, len(cand), block):
        s, r = _sin(np, cand[i:i + block], m, t)
        v = np.clip(1.0 - (s / tol) ** 2, 0.0, None) * (r >= r_min)
        scores[i:i + block] = v @ w
    k = int(np.argmax(scores))
    step = np.array([(hi[0] - lo[0]) / max(grid - 1, 1), (hi[1] - lo[1]) / max(grid - 1, 1)])
    return cand[k], float(scores[k]), step


def refine(m, t, w, start, r_min=R_MIN, c=TUKEY_C, max_iter=MAX_ITER, move_tol=MOVE_TOL):
    """IRLS on sin(theta) with Tukey's biweight from start. Returns (center, info)."""
    np = _np()
    p = np.asarray(start, dtype=float)
    info = {"iterations": 0, "converged": False}
    for it in range(1, max_iter + 1):
        s, r = _sin(np, p[None], m, t)
        s, r = s[0], r[0]
        far = r >= r_min
        if far.sum() < 3:
            raise NormalAxisError("too few segments away from the candidate")
        scale = max(1.4826 * float(np.median(np.abs(s[far]))), SCALE_FLOOR)
        u = s / (c * scale)
        bw = np.where((np.abs(u) < 1) & far, (1 - u ** 2) ** 2, 0.0)
        W = w * bw / np.maximum(r, r_min) ** 2
        txx, txy, tyy = (W * t[:, 0] ** 2).sum(), (W * t[:, 0] * t[:, 1]).sum(), (W * t[:, 1] ** 2).sum()
        A = np.array([[txx, txy], [txy, tyy]])
        tm = t[:, 0] * m[:, 0] + t[:, 1] * m[:, 1]
        b = np.array([(W * t[:, 0] * tm).sum(), (W * t[:, 1] * tm).sum()])
        ev = np.linalg.eigvalsh(A)
        cond = float(ev[-1] / ev[0]) if ev[0] > 0 else float("inf")
        if not math.isfinite(cond) or cond > MAX_COND:
            raise NormalAxisError(f"the tangents do not span the plane (condition {cond:.3g})")
        new = np.linalg.solve(A, b)
        move = float(np.hypot(*(new - p)))
        p = new
        info.update(iterations=it, condition=round(cond, 2), scale=round(scale, 5))
        if move < move_tol:
            info["converged"] = True
            break
    s, r = _sin(np, p[None], m, t)
    s, r = s[0], r[0]
    far = r >= r_min
    scale = max(1.4826 * float(np.median(np.abs(s[far]))), SCALE_FLOOR)
    inl = far & (np.abs(s) < c * scale)
    info["inlier_share"] = round(float(w[inl].sum() / w.sum()), 4) if w.sum() > 0 else 0.0
    info["median_abs_sin"] = round(float(np.median(np.abs(s[far]))), 5)
    return p, info


def estimate_slice(lines, bounds=None):
    """The axis point of one slice from its polylines: {"x", "y", "segments", "inlier_share", ...}, or
    {"x": None, "reason": ...} when the slice gives none. bounds: (x0, y0, x1, y1) to vote over (default the
    polylines' extent)."""
    np = _np()
    m, t, w = segments(lines)
    out = {"segments": int(len(w))}
    if len(w) < MIN_SEGMENTS:
        return {**out, "x": None, "y": None, "reason": f"{len(w)} segments, fewer than {MIN_SEGMENTS}"}
    if bounds is None:
        lo, hi = m.min(0), m.max(0)
    else:
        lo, hi = np.array(bounds[:2], float), np.array(bounds[2:], float)
    best, score, step = vote(m, t, w, lo, hi)
    for _ in range(ZOOMS):
        best, score, step = vote(m, t, w, best - 2 * step, best + 2 * step)
    try:
        p, info = refine(m, t, w, best)
    except NormalAxisError as exc:
        return {**out, "x": None, "y": None, "reason": str(exc)}
    out.update(info, vote_score_share=round(score / float(w.sum()), 4))
    if not info["converged"]:
        return {**out, "x": None, "y": None, "reason": f"the refinement did not settle in {MAX_ITER} rounds"}
    if info["median_abs_sin"] > MAX_MEDIAN_SIN:
        return {**out, "x": None, "y": None,
                "reason": f"median |sin(theta)| {info['median_abs_sin']} over {MAX_MEDIAN_SIN}: the normals do not "
                          "point at one center"}
    return {**out, "x": round(float(p[0]), 2), "y": round(float(p[1]), 2)}


def grid_file_estimate(path):
    """estimate_slice on one GridStore file (kit.surfacepred.read_grid)."""
    from . import surfacepred
    try:
        header, lines = surfacepred.read_grid(path)
    except surfacepred.SurfacePredError as exc:
        return {"x": None, "y": None, "segments": 0, "reason": str(exc)}
    if header is None:
        return {"x": None, "y": None, "segments": 0, "reason": "empty slice"}
    return estimate_slice(lines)


def estimate_axis(grids_dir, slices, workers=4, log=None):
    """Per-slice estimates for the xy grids of the given slices under grids_dir (xy/NNNNNN.grid). Returns
    (points [(z, y, x)], per_slice {z: record}); slices with no file or no estimate are in per_slice only."""
    import concurrent.futures
    grids_dir = Path(grids_dir)

    def one(z):
        f = grids_dir / "xy" / f"{int(z):06d}.grid"
        if not f.is_file():
            return z, {"x": None, "y": None, "segments": 0, "reason": "no grid file"}
        return z, grid_file_estimate(f)

    with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as pool:
        got = dict(pool.map(one, slices))
    pts = [(float(z), r["y"], r["x"]) for z, r in sorted(got.items()) if r.get("x") is not None]
    if log:
        log(f"normals: {len(pts)} of {len(got)} slices gave an estimate")
    return pts, {int(z): r for z, r in sorted(got.items())}


# ---------------------------------------------------------------- synthetic scrolls (tests and the self-check)

def spiral_lines(cx, cy, r0=150.0, r1=1500.0, pitch=30.0, step=20.0, squash=1.0, phase=0.0, gap_every=40,
                 noise=0.0, seed=0):
    """Polylines of an Archimedean spiral round (cx, cy), r = r0 + pitch * angle / (2 pi), sampled every `step`
    voxels of arc, broken every gap_every points, its y offsets multiplied by squash (a crushed scroll), with
    Gaussian noise (voxels) on each point, rounded to integers as GridStore keeps them."""
    np = _np()
    rng = np.random.default_rng(seed)
    pts, a = [], 0.0
    while True:
        r = r0 + pitch * a / (2 * math.pi)
        if r > r1:
            break
        pts.append((cx + r * math.cos(a + phase), cy + squash * r * math.sin(a + phase)))
        a += step / max(r, 1.0)
    p = np.asarray(pts) + (rng.normal(0, noise, (len(pts), 2)) if noise else 0)
    p = np.round(p).astype(np.int64)
    return [p[i:i + gap_every] for i in range(0, len(p), gap_every) if len(p[i:i + gap_every]) >= 2]


def clutter_lines(n, lo, hi, length=200.0, step=20.0, seed=0):
    """n straight polylines at random places and directions: segments whose normals point nowhere in particular."""
    np = _np()
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        a = rng.uniform(0, math.pi)
        c = rng.uniform(lo, hi, 2)
        k = max(2, int(length / step))
        s = (np.arange(k) - k / 2) * step
        out.append(np.round(c + np.stack([s * math.cos(a), s * math.sin(a)], 1)).astype(np.int64))
    return out


def selfcheck():
    """Planted checks that can fail, on synthetic slices with a known center: a spiral off the slice's center, a
    crushed one, one with clutter, and a control of spokes (normals pointing round the center, never at it) that
    must give no estimate. Returns {"passes": bool, "checks": [...]}"""
    checks = []

    def add(name, lines, want, tol):
        r = estimate_slice(lines)
        if want is None:
            ok = r["x"] is None
            err = None
        else:
            err = None if r["x"] is None else round(math.hypot(r["x"] - want[0], r["y"] - want[1]), 3)
            ok = err is not None and err <= tol
        checks.append({"name": name, "passes": bool(ok), "error_vox": err, "tolerance_vox": tol,
                       "median_abs_sin": r.get("median_abs_sin"), "reason": r.get("reason")})

    add("spiral off center", spiral_lines(1300.0, 900.0), (1300.0, 900.0), 2.0)
    add("crushed spiral (y x 0.6)", spiral_lines(800.0, 1000.0, squash=0.6), (800.0, 1000.0), 5.0)
    add("spiral with a third of its length in clutter", spiral_lines(1000.0, 1000.0, seed=1)
        + clutter_lines(600, -400.0, 2400.0, seed=2), (1000.0, 1000.0), 3.0)
    spokes = []
    for k in range(48):
        a = 2 * math.pi * k / 48
        spokes.append([(round(1000 + r * math.cos(a)), round(1000 + r * math.sin(a))) for r in range(100, 1500, 20)])
    add("control: spokes give no estimate", spokes, None, None)
    add("control: clutter alone gives no estimate", clutter_lines(200, 0.0, 2000.0, seed=5), None, None)
    return {"passes": all(c["passes"] for c in checks), "checks": checks, "rule": RULE}


# ---------------------------------------------------------------- command line

def build_parser(p):
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("slice", help="the axis point of one GridStore file (xy/NNNNNN.grid)")
    a.add_argument("grid")
    a = sub.add_parser("axis", help="per-slice estimates for xy grids in a folder, outliers dropped like "
                                    "AutoPipeline's (robust_axis); writes villa's control_points JSON")
    a.add_argument("grids", help="folder holding xy/NNNNNN.grid")
    a.add_argument("--slices", required=True, help="comma-separated slice numbers")
    a.add_argument("--out", help="umbilicus JSON to write")
    a.add_argument("--window", type=int, default=5)
    sub.add_parser("selfcheck", help="planted synthetic checks that can fail; exit 1 when any fails")


def cmd_normalaxis(args):
    if args.action == "selfcheck":
        res = selfcheck()
        print(json.dumps(res, indent=1))
        return 0 if res["passes"] else 1
    if args.action == "slice":
        print(json.dumps(grid_file_estimate(args.grid), indent=1))
        return 0
    from . import autopipe
    zs = [int(v) for v in args.slices.split(",") if v.strip()]
    pts, per = estimate_axis(args.grids, zs)
    kept, dropped = autopipe.robust_axis(pts, window=args.window) if pts else ([], [])
    res = {"slices": len(zs), "estimates": len(pts), "kept": len(kept), "dropped": dropped, "per_slice": per,
           "rule": RULE}
    if args.out and kept:
        Path(args.out).write_text(json.dumps(autopipe.umbilicus_json(kept, {"method": "kit normalaxis", **RULE}),
                                             indent=1))
        res["umbilicus"] = args.out
    print(json.dumps(res, indent=1))
    return 0 if len(kept) >= 2 else 1
