"""Which way does a surface's normal point, toward the scroll's centre or away, and does one sign hold for the
whole patch?

VC3D renders layer k at (k - (n - 1) / 2) * step along the grid normal N = dP/dcol x dP/drow, or along -N with
--flip-normals. villa's comment on that flag (apps/src/vc_render_tifxyz.cpp at e0bbb8b) says that for a segment
in the standard orientation (rows down along +z, columns winding from the outside in) N points out of the
scroll, while layer numbers should grow toward the centre, so --flip-normals is "usually what we want".
Usually is the gap this module closes: a surface written with its rows or columns the other way round (another
tool, a transposed or mirrored grid) has N pointing in, and the same flag then stacks its layers away from
the centre.

The sign is decided once per patch, by a vote of its vertices weighted by area and by how squarely each
normal faces the axis, as the community notes advise: choosing the sign per vertex flipped the depth order on
10 to 50 percent of the vertices in their patches, because crumpled papyrus tilts and folds locally
(https://github.com/alexxxmur/vesuvius-pherc0846a-2p4um, read 7 Oct 2026). The grid normal follows the sheet through a fold,
so one sign per patch keeps the recto on the same side of the stack; the vertices that vote the other way are
reported as tiles, to show where the sheet tilts or folds.

The centre is the umbilicus, read in villa's formats (text lines "z, y, x"; JSON [[z, y, x], ...],
[{"x", "y", "z"}, ...] or {"points" | "control_points": [...]}), linear in z and held constant past its ends as
villa's Umbilicus does; or a fixed axis; or, failing both, a circle fitted to the surface itself, which is an
estimate and is labelled so. Standard library.
"""

import json
import math
from pathlib import Path

from . import vc3d_io

CLEAR, WEAK = 0.8, 0.65   # vote shares (by weight) for a clear or weak majority; an interpretation, not a measured bar
MIN_RADIUS = 20.0         # voxels: nearer the axis than this the radial direction says little
MIN_HORIZONTAL = 0.2      # |N_xy| / |N| below this the normal runs along the axis and does not vote
ALONG_Z = 0.7             # |row direction . z| above this counts as rows running along z


class OrientError(ValueError):
    pass


# ---------------------------------------------------------------- umbilicus

def parse_umbilicus(data):
    """Control points [(z, y, x)] sorted by z, from parsed JSON or from the text of a villa umbilicus file."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        text = data.strip()
        if text[:1] in ("[", "{"):
            data = json.loads(text)
        else:
            pts = []
            for n, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                vals = [v.strip() for v in line.split(",") if v.strip()]
                if len(vals) != 3:
                    raise OrientError(f"umbilicus line {n}: expected z, y, x")
                pts.append(tuple(float(v) for v in vals))
            data = pts
    if isinstance(data, dict):
        for key in ("points", "control_points"):
            if key in data:
                data = data[key]
                break
        else:
            raise OrientError("umbilicus JSON needs an array, or a 'points' or 'control_points' array")
    pts = []
    for i, e in enumerate(data or []):
        if isinstance(e, dict):
            if not all(k in e for k in "xyz"):
                raise OrientError(f"umbilicus entry {i} lacks x, y or z")
            pts.append((float(e["z"]), float(e["y"]), float(e["x"])))
        elif isinstance(e, (list, tuple)) and len(e) >= 3:
            pts.append((float(e[0]), float(e[1]), float(e[2])))
        else:
            raise OrientError(f"umbilicus entry {i} is neither [z, y, x] nor an object with x, y, z")
    if not pts:
        raise OrientError("umbilicus has no points")
    return sorted(pts)


def load_umbilicus(source, scale=1.0):
    """Control points from a file (JSON by extension or content, else villa's text) or parsed data, with every
    coordinate multiplied by scale (for an umbilicus annotated in another binning)."""
    if isinstance(source, (str, Path)) and Path(source).is_file():
        source = Path(source).read_text()
    pts = parse_umbilicus(source)
    return [(z * scale, y * scale, x * scale) for z, y, x in pts] if scale != 1 else pts


def centre_at(points, z):
    """(x, y) of the umbilicus at height z: linear between control points, constant past the ends."""
    if z <= points[0][0]:
        return points[0][2], points[0][1]
    if z >= points[-1][0]:
        return points[-1][2], points[-1][1]
    lo, hi = 0, len(points) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if points[mid][0] <= z:
            lo = mid
        else:
            hi = mid
    (z0, y0, x0), (z1, y1, x1) = points[lo], points[hi]
    t = (z - z0) / (z1 - z0) if z1 != z0 else 0.0
    return x0 + t * (x1 - x0), y0 + t * (y1 - y0)


def fit_circle(xs, ys):
    """Kasa least-squares circle through points: (cx, cy, radius, rms residual, angular span in degrees)."""
    n = len(xs)
    if n < 3:
        raise OrientError("a circle needs at least 3 points")
    mx, my = sum(xs) / n, sum(ys) / n
    u = [x - mx for x in xs]
    v = [y - my for y in ys]
    suu = sum(a * a for a in u)
    svv = sum(b * b for b in v)
    suv = sum(a * b for a, b in zip(u, v))
    suuu = sum(a ** 3 for a in u)
    svvv = sum(b ** 3 for b in v)
    suvv = sum(a * b * b for a, b in zip(u, v))
    svuu = sum(b * a * a for a, b in zip(u, v))
    det = suu * svv - suv * suv
    if abs(det) < 1e-9 * max(1.0, suu * svv):
        raise OrientError("the surface is flat in x and y: no circle to fit")
    uc = (0.5 * (suuu + suvv) * svv - 0.5 * (svvv + svuu) * suv) / det
    vc = (0.5 * (svvv + svuu) * suu - 0.5 * (suuu + suvv) * suv) / det
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    cx, cy = uc + mx, vc + my
    rms = math.sqrt(sum((math.hypot(x - cx, y - cy) - r) ** 2 for x, y in zip(xs, ys)) / n)
    angles = sorted(math.atan2(y - cy, x - cx) for x, y in zip(xs, ys))
    gaps = [b - a for a, b in zip(angles, angles[1:])] + [angles[0] + 2 * math.pi - angles[-1]]
    span = math.degrees(2 * math.pi - max(gaps))
    return cx, cy, r, rms, span


# ---------------------------------------------------------------- the vote

def _transform(affine):
    if not affine:
        return None
    rows = [list(map(float, r)) for r in affine[:3]]
    if len(rows) != 3 or any(len(r) != 4 for r in rows):
        raise OrientError("affine must be 3 rows of 4 numbers (x, y, z rows)")
    return rows


def _apply(m, p, translate=True):
    if m is None:
        return p
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + (m[i][3] if translate else 0.0) for i in range(3))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _share(pos, neg):
    total = pos + neg
    return pos / total if total else None


def confidence(share):
    """'clear', 'weak' or 'ambiguous' for the larger side of a vote."""
    if share is None:
        return "ambiguous"
    m = max(share, 1 - share)
    return "clear" if m >= CLEAR else "weak" if m >= WEAK else "ambiguous"


def orientation(surface, umbilicus=None, centre_xy=None, scale_segmentation=1.0, affine=None,
                max_vertices=200_000, tiles=6, grid_box=None):
    """Vote on the sign of the grid normal against the scroll's centre, and describe the grid's layout.

    umbilicus: control points from load_umbilicus, in the volume's level-0 voxels; centre_xy: a fixed axis
    (x, y) instead; neither: a circle fitted to the surface. The surface's coordinates are multiplied by
    scale_segmentation and then taken through affine (3 x 4, rows of x, y, z), as vc_render_tifxyz does.
    grid_box [row0, row1, col0, col1) limits the vote to that part of the grid: one patch of a larger trace, or
    the part a cropped render covers."""
    p = Path(surface)
    gx, gy, gz = (vc3d_io.read_tiff(p / f"{a}.tif") for a in "xyz")
    if not (gx.h == gy.h == gz.h and gx.w == gy.w == gz.w):
        raise OrientError(f"{p}: x, y and z grids differ in size")
    rows, cols = gx.h, gx.w
    r0, r1, c0, c1 = grid_box or (0, rows, 0, cols)
    r0, r1, c0, c1 = max(0, r0), min(rows, r1), max(0, c0), min(cols, c1)
    if r0 >= r1 or c0 >= c1:
        raise OrientError(f"grid_box {list(grid_box or [])} holds no vertex of the {rows} x {cols} grid")
    bh, bw = r1 - r0, c1 - c0
    X, Y, Z = gx.data, gy.data, gz.data
    m = _transform(affine)
    s = float(scale_segmentation)

    def point(r, c):
        i = r * cols + c
        a, b, d = X[i], Y[i], Z[i]
        if (a == -1 and b == -1 and d == -1) or a != a or b != b or d != d or not (a or b or d):
            return None
        return _apply(m, (a * s, b * s, d * s))

    stride = max(1, math.ceil(math.sqrt(bh * bw / max(1, max_vertices))))
    verts = []   # (r, c, position, N, U, V)
    for r in range(r0, r1, stride):
        for c in range(c0, c1, stride):
            p0 = point(r, c)
            if p0 is None:
                continue
            nb = {}
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                rr, cc = r + dr, c + dc
                nb[(dr, dc)] = point(rr, cc) if 0 <= rr < rows and 0 <= cc < cols else None
            U = _diff(p0, nb[(0, 1)], nb[(0, -1)])
            V = _diff(p0, nb[(1, 0)], nb[(-1, 0)])
            if U is None or V is None:
                continue
            N = _cross(U, V)
            if not any(N):
                continue
            verts.append((r, c, p0, N, U, V))
    if not verts:
        raise OrientError(f"{p}: no vertex with valid neighbours to take a normal from")
    out = {"surface": str(p), "grid_rows_cols": [rows, cols], "sampled_every": stride, "vertices": len(verts)}
    if grid_box:
        out["grid_box"] = [r0, r1, c0, c1]

    fit = None
    if umbilicus:
        out["centre"] = "umbilicus"
        centre = lambda z: centre_at(umbilicus, z)  # noqa: E731
    elif centre_xy:
        out["centre"] = "axis"
        cx0, cy0 = float(centre_xy[0]), float(centre_xy[1])
        centre = lambda z: (cx0, cy0)  # noqa: E731
    else:
        step = max(1, len(verts) // 20000)
        try:
            cx0, cy0, rad, rms, span = fit_circle([v[2][0] for v in verts[::step]], [v[2][1] for v in verts[::step]])
        except OrientError as exc:
            raise OrientError(f"no umbilicus or centre_xy given, and no centre to estimate from the surface: {exc}") \
                from exc
        reliable = span >= 30 and rms <= 0.15 * rad
        fit = {"centre_xy": [round(cx0, 1), round(cy0, 1)], "radius": round(rad, 1), "rms": round(rms, 2),
               "arc_degrees": round(span, 1), "reliable": reliable}
        out["centre"] = "fitted circle (an estimate" + ("" if reliable else ", and an unreliable one") + ")"
        out["fit"] = fit
        centre = lambda z: (cx0, cy0)  # noqa: E731

    nout = nin = 0.0
    near = along = 0
    zpos = zneg = 0.0
    rows_along_z = 0
    upos = uneg = 0.0
    grid = {}
    by_rc = {}
    for r, c, (px, py, pz), N, U, V in verts:
        area = math.sqrt(N[0] ** 2 + N[1] ** 2 + N[2] ** 2)
        by_rc[(r, c)] = (N[0] / area, N[1] / area, N[2] / area)
        cx, cy = centre(pz)
        rx, ry = px - cx, py - cy
        rho = math.hypot(rx, ry)
        if rho < MIN_RADIUS:
            near += 1
            continue
        horiz = math.hypot(N[0], N[1]) / area
        vl = math.sqrt(V[0] ** 2 + V[1] ** 2 + V[2] ** 2) or 1.0
        vz = V[2] / vl
        if abs(vz) >= ALONG_Z:
            rows_along_z += 1
        if vz > 0:
            zpos += area * vz
        else:
            zneg -= area * vz
        ul = math.sqrt(U[0] ** 2 + U[1] ** 2 + U[2] ** 2) or 1.0
        turn = (U[1] * rx - U[0] * ry) / (ul * rho)   # U . (z x r_hat): + turns from +x toward +y about +z
        if turn > 0:
            upos += area * turn
        else:
            uneg -= area * turn
        if horiz < MIN_HORIZONTAL:
            along += 1
            continue
        cos = (N[0] * rx + N[1] * ry) / (area * rho)
        w = area * abs(cos)
        key = (min(tiles - 1, (r - r0) * tiles // bh), min(tiles - 1, (c - c0) * tiles // bw))
        t = grid.setdefault(key, [0.0, 0.0])
        if cos > 0:
            nout += w
            t[0] += w
        else:
            nin += w
            t[1] += w
    share = _share(nout, nin)
    conf = confidence(share)
    vote = None if share is None else "outward" if share >= 0.5 else "inward"
    out["normal"] = {"outward_share": None if share is None else round(share, 4), "vote": vote, "confidence": conf,
                     "near_axis": near, "along_axis": along,
                     "thresholds": {"clear": CLEAR, "weak": WEAK, "note": "an interpretation"}}
    if conf == "ambiguous" or vote is None:
        out["team_order"] = None
        out["advice"] = ("no clear sign: the surface folds over itself, wraps through the centre, or the centre is "
                         "wrong; split it into patches (or check the umbilicus) before rendering in team order")
    else:
        out["team_order"] = "--flip-normals" if vote == "outward" else "no flag (+N already points to the centre)"
        minority = 1 - max(share, 1 - share)
        out["advice"] = (f"+N points {vote} on {max(share, 1 - share):.0%} of the voting area, so layers grow toward "
                         f"the centre with {out['team_order']}")
        if minority > 0.05:
            out["advice"] += (f"; {minority:.0%} faces the other way (local tilts or folds): one sign for the patch "
                              "keeps the recto on one side of the stack, as the community notes advise")
    zs = _share(zpos, zneg)
    out["rows"] = {"along_z_share": round(rows_along_z / max(1, len(verts) - near), 4),
                   "plus_z_share": None if zs is None else round(zs, 4)}
    out["rows"]["run"] = ("across z" if out["rows"]["along_z_share"] < 0.5 else "+z" if (zs or 0) >= 0.5 else "-z")
    us = _share(upos, uneg)
    out["columns"] = {"turn_share": None if us is None else round(us, 4),
                      "turn": None if us is None else "positive" if us >= 0.5 else "negative",
                      "note": "positive: +column turns from +x toward +y about +z"}
    out["layout"] = layout(vote, out["rows"]["run"])
    pairs = flips = 0
    for (r, c), n0 in by_rc.items():
        for key in ((r, c + stride), (r + stride, c)):
            n1 = by_rc.get(key)
            if n1 is not None:
                pairs += 1
                if n0[0] * n1[0] + n0[1] * n1[1] + n0[2] * n1[2] < 0:
                    flips += 1
    out["folds"] = {"neighbour_pairs": pairs, "flipped_pairs": flips,
                    "share": round(flips / pairs, 4) if pairs else None,
                    "note": "neighbouring sampled normals more than 90 degrees apart: sharp folds or grid creases"}
    if vote is not None:
        total = nout + nin
        odd = []
        for (tr, tc), (o, i) in sorted(grid.items()):
            tshare = _share(o, i)
            if tshare is None or (o + i) < 0.01 * total:
                continue
            if (tshare >= 0.5) != (vote == "outward"):
                odd.append({"rows": [r0 + tr * bh // tiles, r0 + (tr + 1) * bh // tiles - 1],
                            "cols": [c0 + tc * bw // tiles, c0 + (tc + 1) * bw // tiles - 1],
                            "outward_share": round(tshare, 3), "area_share": round((o + i) / total, 3)})
        out["disagreeing_tiles"] = odd
    return out


def _diff(p0, ahead, behind):
    if ahead is not None and behind is not None:
        return tuple((a - b) / 2 for a, b in zip(ahead, behind))
    if ahead is not None:
        return tuple(a - b for a, b in zip(ahead, p0))
    if behind is not None:
        return tuple(a - b for a, b in zip(p0, behind))
    return None


def layout(vote, rows_run):
    """The grid's layout against villa's standard segment orientation (rows along +z, +N outward)."""
    if vote is None:
        return "unknown (no clear normal sign)"
    if rows_run == "across z":
        return "rows do not run along z (a transposed or rotated grid, or a sheet lying across the axis)"
    return {("outward", "+z"): "villa's standard orientation (rows along +z, +N outward)",
            ("outward", "-z"): "standard turned 180 degrees (rows along -z, +N outward)",
            ("inward", "+z"): "standard mirrored left to right (rows along +z, +N inward)",
            ("inward", "-z"): "standard mirrored top to bottom (rows along -z, +N inward)"}[(vote, rows_run)]
