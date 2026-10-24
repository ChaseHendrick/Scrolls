"""Coverage polish of a scroll's center line (umbilicus): move it, slice by slice, to the deepest point of the
scroll's traced sheet nearby (added 24 Oct 2026).

On each polished slice the line's point moves to the place of highest winding coverage within 8 mm of it
(kit/windcheck.py: how many wraps of the slice's traced sheet sweep a full turn round a point, highest inside the
innermost wrap), read on the scan's published level-0 normal grids (villa's vc_gen_normalgrids output, the files
villa's vc_gen_umbilicus reads). A coarse grid of 0.4 mm over the disc, then a fine grid of 0.05 mm within 0.5 mm of
the coarse best, the highest coverage kept; a slice whose grid holds fewer than 500 traced segments is skipped; the
polished points pass a robust outlier check along z (window 5) and become the new line. The numbers are rule
version 1, frozen for the test below on 22 Oct 2026 (rule sha256 71d431b3); tests/test_axispolish.py pins the frozen
code's outputs on synthetic slices.

Evidence (Model output, measured against villa's own predicted sheets): on ten fresh scans, the Center Finder's
lines polished so sat deeper in villa's traced sheet than villa's vc_gen_umbilicus at slices the polish never read,
pooled median +0.084 wraps (95% interval +0.028 to +0.169), deeper on 8 of 10 scans; unpolished they lost by -0.33
wraps (docs/evidence/2026-10-22-umbilicus-windpolish/). It is not a measurement of the true axis, and the polish of
any other line (villa's, a person's) is untested. Do not polish a person's line: it is their placement.

    python -m kit axispolish LINE.json --out POLISHED.json            # grids found on the open-data bucket
    python -m kit axispolish LINE.json --grids DIR_OR_URL --out POLISHED.json [--every 100] [--json]

numpy inside the functions (standard library at import); numba, when installed, computes the same sums compiled
(about 8 times faster; tests hold them equal to windcheck.coverage).
"""

import argparse
import json
import math
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import windcheck
from .vc3d_io import percentile

VERSION = 1
RULE = {"version": VERSION, "radius_mm": 8.0, "coarse_mm": 0.4, "fine_radius_mm": 0.5, "fine_mm": 0.05,
        "min_segments": 500, "window": 5}
# One polished slice every EVERY slices. The test polished slices 50 and 100 above and below each scored slice, so
# a line read between polished slices at most 100 apart stays inside what it measured.
EVERY = 100
LABEL = ("Model output: coverage polish of a center line on the scan's published normal grids (kit/axispolish.py, "
         "winding coverage of villa's predicted sheets), not a measurement of the true axis")
EVIDENCE = ("On ten fresh scans the Center Finder's lines, polished so, beat villa's vc_gen_umbilicus by winding "
            "coverage at slices the polish never read: +0.084 wraps, 8 of 10 scans, 95% interval +0.028 to +0.169 "
            "(docs/evidence/2026-10-22-umbilicus-windpolish/)")
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
GRID_MAGIC, GRID_VERSION = 0x56434753, 3
# sha256 of the frozen test's whole rule (these numbers plus the test's own settings), 22 Oct 2026
FROZEN_RULE_SHA256 = "71d431b3459f69c3989899a3f4d09647132714119ce6cb0537109ebb9d2fb5c8"


class PolishError(Exception):
    pass


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise PolishError("the coverage polish needs numpy: python -m pip install numpy") from exc
    return numpy


# ---------------------------------------------------------------- the normal grids

def read_grid(source):
    """A GridStore file (villa core/src/GridStore.cpp, format v3, big-endian) as (header, [polylines (N, 2) of
    (u, v)]); u, v are (x, y) for xy slices. An empty file is an empty slice."""
    np = _np()
    raw = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    if not raw:
        return None, []
    if len(raw) < 52:
        raise PolishError("grid file shorter than its header")
    magic, ver, bx, by, bw, bh, cell, nb, npaths, bio, po, jo, js = struct.unpack(">13I", raw[:52])
    if magic != GRID_MAGIC:
        raise PolishError(f"not a GridStore file (magic {magic:#x})")
    if ver > GRID_VERSION:
        raise PolishError(f"GridStore version {ver} is newer than {GRID_VERSION}")
    lines, cur = [], po
    while cur < jo:
        sx, sy, n = struct.unpack(">iiI", raw[cur:cur + 12])
        cur += 12
        off = np.frombuffer(raw[cur:cur + n], dtype=np.int8).reshape(-1, 2).astype(np.int64)
        cur += n
        start = np.array([[sx, sy]], dtype=np.int64)
        lines.append(np.vstack([start, np.cumsum(off, axis=0) + start]) if len(off) else start)
    meta = json.loads(raw[jo:jo + js]) if js else {}
    return {"version": ver, "bounds": [bx, by, bw, bh], "cell": cell, "buckets": nb, "paths": npaths,
            "meta": meta}, lines


def write_grid(path, lines, bounds, cell=64, meta=None):
    """Polylines as a GridStore v3 file laid out the way GridStore::save writes it (test inputs)."""
    np = _np()
    bx, by, bw, bh = (int(v) for v in bounds)
    gw, gh = -(-bw // cell), -(-bh // cell)
    grid = [[] for _ in range(gw * gh)]
    paths, offsets = b"", []
    for line in lines:
        p = np.asarray(line, dtype=np.int64).reshape(-1, 2)
        if len(p) < 2:
            continue
        d = np.diff(p, axis=0)
        if np.abs(d).max() > 127:
            raise PolishError("a polyline step does not fit in int8")
        offsets.append(len(paths))
        paths += struct.pack(">iiI", int(p[0, 0]), int(p[0, 1]), d.size) + d.astype(np.int8).tobytes()
        cells = {int((q[1] - by) // cell) * gw + int((q[0] - bx) // cell) for q in p
                 if 0 <= (q[0] - bx) // cell < gw and 0 <= (q[1] - by) // cell < gh}
        for c in sorted(cells):
            grid[c].append(len(offsets) - 1)
    idx, flat = [0], []
    for bucket in grid:
        flat += [offsets[h] for h in bucket]
        idx.append(len(flat))
    meta_b = json.dumps(meta or {}).encode()
    bio = 52
    po = bio + 4 * len(idx) + 4 * len(flat)
    jo = po + len(paths)
    head = struct.pack(">13I", GRID_MAGIC, GRID_VERSION, bx, by, bw, bh, cell, len(grid), len(offsets), bio, po, jo,
                       len(meta_b))
    body = struct.pack(f">{len(idx)}I", *idx) + struct.pack(f">{len(flat)}I", *flat) + paths + meta_b
    Path(path).write_bytes(head + body)


def _http(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "scrolls-kit axispolish"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def find_grids(scroll, volume, get=None):
    """The bucket URL of a scan's level-0 normal grids (SCROLL/representations/predictions/surfaces/
    VOLUMEID-...-L0-....normal-grids), or None when the bucket has none."""
    from . import find
    vid = str(volume)[:14]
    prefixes, _ = find.list_prefix(f"{scroll}/representations/predictions/surfaces/",
                                   *(() if get is None else (get,)))
    hits = sorted(p for p in prefixes if p.rsplit("/", 2)[-2].startswith(vid) and "-L0-" in p
                  and p.rstrip("/").endswith(".normal-grids"))
    return f"{BUCKET}/{hits[-1].rstrip('/')}" if hits else None


def grid_source(grids, cache=None, get=_http):
    """segs_at(z) over a normal-grid folder or URL holding xy/NNNNNN.grid: the slice's segments, or None when the
    slice has no grid or it cannot be read. A URL's files are kept under cache when one is given."""
    base = str(grids).rstrip("/")
    remote = "://" in base
    cache = Path(cache) if cache else None

    def segs_at(z):
        rel = f"xy/{int(z):06d}.grid"
        try:
            if not remote:
                f = Path(base) / rel
                if not f.is_file():
                    return None
                data = f.read_bytes()
            else:
                hit = cache / rel if cache else None
                if hit is not None and hit.is_file():
                    data = hit.read_bytes()
                else:
                    data = get(f"{base}/{rel}")
                    if hit is not None:
                        hit.parent.mkdir(parents=True, exist_ok=True)
                        hit.write_bytes(data)
            return windcheck.segments(read_grid(data)[1])
        except (OSError, urllib.error.URLError, PolishError, ValueError, struct.error):
            return None
    return segs_at


# ---------------------------------------------------------------- the line

def load_line(path):
    """(points [(z, y, x)] sorted by z, metadata dict) from a control_points JSON file."""
    try:
        raw = json.loads(Path(path).read_text())
        pts = sorted((float(p["z"]), float(p["y"]), float(p["x"])) for p in raw["control_points"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PolishError(f"{path}: not a center line in the published format (control_points of x, y, z): {exc}")
    if len(pts) < 2 or not all(math.isfinite(v) for p in pts for v in p):
        raise PolishError(f"{path}: a line needs at least 2 finite control points")
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return pts, meta


def centre_at(points, z):
    """(x, y) of the line at height z: linear between control points, constant past the ends."""
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


def _line_at(zs, vs, z):
    """Siegel's repeated-median line through (zs, vs), evaluated at z."""
    n = len(zs)
    slopes = []
    for i in range(n):
        s = sorted((vs[j] - vs[i]) / (zs[j] - zs[i]) for j in range(n) if j != i and zs[j] != zs[i])
        if s:
            slopes.append(s[len(s) // 2] if len(s) % 2 else 0.5 * (s[len(s) // 2 - 1] + s[len(s) // 2]))
    if not slopes:
        return sorted(vs)[n // 2]
    slopes.sort()
    k = len(slopes)
    slope = slopes[k // 2] if k % 2 else 0.5 * (slopes[k // 2 - 1] + slopes[k // 2])
    icpt = sorted(v - slope * zz for zz, v in zip(zs, vs))
    b = icpt[n // 2] if n % 2 else 0.5 * (icpt[n // 2 - 1] + icpt[n // 2])
    return b + slope * z


def robust_axis(points, window=5, floor=1.0):
    """Drop points far from their neighbors along z: each is compared with a repeated-median line through the
    `window` points nearest it in z (itself left out); a point farther than the median such distance plus 4 robust
    deviations (1.4826 x MAD, at least `floor` voxels) is dropped. Returns (kept, dropped), sorted by z."""
    pts = sorted((float(z), float(y), float(x)) for z, y, x in points)
    if len(pts) < 3:
        return pts, []
    k = max(2, min(int(window), len(pts) - 1))
    dist = []
    for i, (z, y, x) in enumerate(pts):
        near = sorted((j for j in range(len(pts)) if j != i), key=lambda j: (abs(pts[j][0] - z), j))[:k]
        zs = [pts[j][0] for j in near]
        dist.append(math.hypot(y - _line_at(zs, [pts[j][1] for j in near], z),
                               x - _line_at(zs, [pts[j][2] for j in near], z)))
    med = percentile(sorted(dist), 50)
    limit = med + 4 * max(percentile(sorted(abs(d - med) for d in dist), 50) * 1.4826, floor)
    kept = [p for p, d in zip(pts, dist) if d <= limit]
    dropped = [{"z": p[0], "y": p[1], "x": p[2], "distance": round(d, 2)} for p, d in zip(pts, dist) if d > limit]
    return kept, dropped


# ---------------------------------------------------------------- the polish

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


def polish_line(guess, heights, segs_at, voxel_um, rule=RULE, log=None):
    """guess: the line [(z, y, x)] sorted by z; heights: the slices to polish; segs_at(z) -> segments or None.
    Returns (polished line [(z, y, x)], or None when fewer than 2 points survive; per-slice records)."""
    per, recs = {}, []
    for z in heights:
        segs = segs_at(z)
        n = 0 if segs is None else len(segs[0])
        if n < rule["min_segments"]:
            recs.append({"z": z, "segments": n, "skipped": True})
            continue
        g = centre_at(guess, z)
        pt, top, gc = polish_point(segs, g, voxel_um, rule)
        per[z] = pt
        recs.append({"z": z, "segments": n, "guess": [round(g[0], 2), round(g[1], 2)],
                     "point": [round(pt[0], 2), round(pt[1], 2)], "coverage": round(top, 4),
                     "guess_coverage": round(gc, 4),
                     "moved_mm": round(math.hypot(pt[0] - g[0], pt[1] - g[1]) * voxel_um / 1000.0, 4)})
        if log:
            log(f"z {z}: moved {recs[-1]['moved_mm']:.2f} mm, +{top - gc:.3f} wraps")
    pts = [(float(z), p[1], p[0]) for z, p in sorted(per.items())]
    if len(pts) < 2:
        return None, recs
    kept, _ = robust_axis(pts, window=rule["window"])
    return (kept if len(kept) >= 2 else None), recs


def heights(guess, every, z_range=None):
    """The slices to polish: every `every`-th slice inside the guess's z span (and z_range [z0, z1] when given)."""
    z0, z1 = guess[0][0], guess[-1][0]
    if z_range:
        z0, z1 = max(z0, z_range[0]), min(z1, z_range[1])
    first = int(math.ceil(z0 / every) * every)
    return list(range(first, int(math.floor(z1)) + 1, every))


def polish_file(line, out, grids=None, scroll=None, every=EVERY, voxel_um=None, cache=None, segs_at=None, log=None):
    """Polish a center line file and write the result in the same format, with metadata.polish added. Returns a
    summary dict. grids: a normal-grid folder or URL; else found on the bucket from scroll and the line's volume."""
    guess, meta = load_line(line)
    vox = float(voxel_um or meta.get("voxelsize_um") or 0)
    if not vox > 0:
        raise PolishError("give --voxel-um: the line's metadata names no voxelsize_um")
    if every < 1:
        raise PolishError("--every is a whole number of slices, at least 1")
    if segs_at is None:
        if not grids:
            scroll = scroll or str(meta.get("source_volume", "")).split("/")[0] or None
            if not scroll or not meta.get("volume"):
                raise PolishError("give --grids, or --scroll with a line whose metadata names its volume")
            grids = find_grids(scroll, meta["volume"])
            if not grids:
                raise PolishError(f"the open-data bucket has no level-0 normal grids for {scroll} {meta['volume']}")
        segs_at = grid_source(grids, cache)
    z_range = meta.get("z_valid") if isinstance(meta.get("z_valid"), list) and len(meta["z_valid"]) == 2 else None
    hs = heights(guess, every, z_range)
    t0 = time.time()
    pts, recs = polish_line(guess, hs, segs_at, vox, log=log)
    if pts is None:
        raise PolishError(f"fewer than 2 of {len(hs)} slices could be polished (no grid, or under "
                          f"{RULE['min_segments']} traced segments)")
    done = [r for r in recs if not r.get("skipped")]
    moved = sorted(r["moved_mm"] for r in done)
    gain = sorted(r["coverage"] - r["guess_coverage"] for r in done)
    record = {"rule": RULE, "frozen_rule_sha256": FROZEN_RULE_SHA256, "every": every, "grids": str(grids) if grids else None,
              "guess": Path(line).name, "slices": len(recs), "polished": len(done), "kept": len(pts),
              "median_moved_mm": round(percentile(moved, 50), 3),
              "median_gain_wraps": round(percentile(gain, 50), 4), "label": LABEL, "evidence": EVIDENCE,
              "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    new_meta = {k: v for k, v in meta.items() if k not in ("total_points",)}
    new_meta.update({"total_points": len(pts), "polish": record})
    doc = {"control_points": [{"x": round(x, 2), "y": round(y, 2), "z": z} for z, y, x in pts], "metadata": new_meta}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(doc, indent=1) + "\n")
    return {"out": str(out), "points": len(pts), "seconds": round(time.time() - t0, 1),
            **{k: record[k] for k in ("slices", "polished", "median_moved_mm", "median_gain_wraps", "grids")},
            "per_slice": recs}


# ---------------------------------------------------------------- command line

def build_parser(p):
    p.add_argument("line", metavar="LINE.json", help="a center line in the published format (control_points, "
                   "metadata with voxelsize_um and volume), such as a Center Finder line from kit centerline get")
    p.add_argument("--out", required=True, help="the polished line, same format, metadata.polish added")
    p.add_argument("--grids", help="the scan's level-0 normal-grid folder or URL (holding xy/NNNNNN.grid); "
                   "default: found on the open-data bucket from the line's volume")
    p.add_argument("--scroll", help="the scroll, when the line's metadata has no source_volume (e.g. PHerc0175A)")
    p.add_argument("--every", type=int, default=EVERY, help=f"polish one slice every this many (default {EVERY})")
    p.add_argument("--voxel-um", type=float, help="voxel size, when the line's metadata names none")
    p.add_argument("--cache", help="keep downloaded grid files here")
    p.add_argument("--verbose", action="store_true", help="print each slice's move")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")
    return p


def cmd_axispolish(args):
    try:
        res = polish_file(args.line, args.out, grids=args.grids, scroll=args.scroll, every=args.every,
                          voxel_um=args.voxel_um, cache=args.cache,
                          log=(lambda m: print(m, file=sys.stderr)) if args.verbose else None)
    except PolishError as exc:
        print(f"axispolish: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({k: v for k, v in res.items() if k != "per_slice"}, indent=1))
    else:
        print(f"wrote {res['out']}: {res['points']} points from {res['polished']} of {res['slices']} slices")
        print(f"median move: {res['median_moved_mm']} mm")
        print(f"median coverage gain: {res['median_gain_wraps']} wraps")
        print(f"time: {res['seconds']} s")
        print(f"Model output, not the true axis: {EVIDENCE}")
    return 0


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit axispolish", description=__doc__.split("\n\n")[0]))
    return cmd_axispolish(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
