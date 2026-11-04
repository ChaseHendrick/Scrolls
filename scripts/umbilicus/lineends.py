"""Center line ends against the scroll's outline in the masked CT: find the end runs that leave the papyrus and trim them.

    python scripts/umbilicus/lineends.py check FILE [FILE ...] [--volume SCROLL/volumes/VOL] [--report R.json] [--json]
    python scripts/umbilicus/lineends.py trim FILE [FILE ...] --out DIR [--volume SCROLL/volumes/VOL] [--report R.json]

FILE is an umbilicus file in the published format (control_points x, y, z in level-0 voxels of its scan). Its scan
is metadata.source_volume ("SCROLL/volumes/VOL.zarr", as the Center Finder writes it) unless --volume names it. The
scan must be a masked OME-Zarr in the Vesuvius Challenge open-data bucket: voxels outside the scroll are zero.

The test (outside_ends) reads level 5 of the scan (32 times down) by HTTP range requests. A control point lies
outside the scroll when, in its own axial slice, no nonzero voxel lies within FAR_MM (4 mm) of it and it sits more
than FAR_MM outside the convex hull of the slice's nonzero voxels, or the slice has no nonzero voxel at all. Only the
outer END_SHARE (a quarter) of a line's points at each end can be cut: at each end the cut reaches from the end to
the innermost outside point in that zone, so an excursion that comes back inside is cut with it, and the middle half
of a line is never cut. Two checks make the test able to fail; a line that fails either is left whole and reported
untested: its middle point must be inside (else the frame or the mask is wrong) and the slice corner farthest from
it must be outside (else the scan's air is not zero).

check   prints, per file, the points and the height each end would lose; writes nothing but the --report JSON.
trim    also writes DIR/<file name> for every file: the same JSON with the cut end points removed and
        metadata.papyrus_trim saying what was cut and by which rule. A file with nothing to cut, or untested, is
        written unchanged except for that block. Points keep their order and every key they had.

The same test hides the end runs in the Umbilici Space (spaces/umbilici/tools/build_lines.py imports it from here),
so a trimmed line shows whole there. It measures the line against the published mask, not where the center is: a
trimmed line is still model output. Standard library only (numcodecs to read a scan stored with compressed chunks).
"""
import argparse
import json
import math
import re
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

S3 = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
VERSION = "1.0.0"

# A control point lies outside the scroll when, in its own axial slice of the scan's masked CT (voxels outside the
# scroll are zero), it sits more than FAR_MM outside the convex hull of the nonzero voxels, or the slice has no
# nonzero voxel at all. The hull, not the nearest voxel, is the bar because a scroll's ends taper and break into
# fragments: a point between two fragments is near no voxel but still inside the scroll's outline (a survey of all 57
# shown lines on 4 Nov 2026 found such gaps of up to 10.9 mm on people's lines, all inside the hull).
# Only the outer END_SHARE of a line's points at each end can be hidden: at each end the hidden run reaches from the
# end to the innermost outside point in that zone, so an excursion a few points in from an end that comes back inside
# is hidden with it. The middle half of a line is never hidden. Two built-in checks make the test able to fail, and
# a line whose checks fail is drawn whole and marked untested: the line's middle point must be inside (else the frame
# or the mask is wrong), and the slice corner farthest from it must be outside (else the scan's air is not zero).
LEVEL = 5          # 32 times down: 0.28 to 0.30 mm voxels on the 1.2 m scans, 77 um on the 2.4 um scans
FAR_MM = 4.0
END_SHARE = 0.25
CORNER = 0.02      # the corner control sits this share of the width in from each edge
RULE = ("end points cut where they leave the scroll in the masked CT (level 5): no nonzero voxel within 4 mm in "
        "the point's slice and more than 4 mm outside the convex hull of the slice's nonzero voxels, or a slice "
        "with no scroll; only the outer quarter of points at each end can be cut, from the end to the innermost "
        "outside point; the middle point must be inside and the slice corner farthest from it outside, else nothing "
        "is cut")


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


class Volume:
    """One pyramid level of a uint8 OME-Zarr: shape (z, y, x), read one axial plane of a chunk at a time.

    tile(zi, cy, cx) returns that plane of chunk (zi // cz, cy, cx) as bytes (cy_size * cx_size), or None for a
    missing chunk, which reads as zeros (the masked scans' fill value)."""

    def __init__(self, shape, chunks, tile, threads=1):
        self.shape, self.chunks, self._tile, self.threads = list(shape), list(chunks), tile, threads
        self.cache, self.lock = {}, threading.Lock()

    def tiles(self, zi, y0, y1, x0, x1):
        _, ch_y, ch_x = self.chunks
        if not 0 <= zi < self.shape[0]:
            return []
        y0, y1 = max(0, y0), min(self.shape[1], y1)
        x0, x1 = max(0, x0), min(self.shape[2], x1)
        if y0 >= y1 or x0 >= x1:
            return []
        return [(zi, a, b) for a in range(y0 // ch_y, (y1 - 1) // ch_y + 1) for b in range(x0 // ch_x, (x1 - 1) // ch_x + 1)]

    def prefetch(self, keys):
        todo = sorted(set(keys) - set(self.cache))
        if not todo:
            return
        def one(k):
            v = self._tile(*k)
            with self.lock:
                self.cache[k] = v
        if self.threads > 1 and len(todo) > 1:
            with ThreadPoolExecutor(self.threads) as ex:
                list(ex.map(one, todo))
        else:
            for k in todo:
                one(k)

    def rows(self, zi, y0, y1, x0, x1):
        """Rows y0..y1-1 of slice zi between x0 and x1, as bytes, zero outside the volume."""
        _, ch_y, ch_x = self.chunks
        self.prefetch(self.tiles(zi, y0, y1, x0, x1))
        out = []
        for y in range(y0, y1):
            if not (0 <= zi < self.shape[0] and 0 <= y < self.shape[1]):
                out.append(bytes(x1 - x0))
                continue
            row = bytearray(x1 - x0)
            xa, xb = max(0, x0), min(self.shape[2], x1)
            for b in (range(xa // ch_x, (xb - 1) // ch_x + 1) if xa < xb else ()):
                t = self.cache.get((zi, y // ch_y, b))
                if t is None:
                    continue
                tx0 = b * ch_x
                a0, a1 = max(x0, tx0), min(x1, tx0 + ch_x, self.shape[2])
                r = (y % ch_y) * ch_x
                row[a0 - x0:a1 - x0] = t[r + a0 - tx0:r + a1 - tx0]
            out.append(bytes(row))
        return out


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def hull(pts):
    """Convex hull, counterclockwise, of (x, y) points (Andrew's monotone chain)."""
    pts = sorted(set(pts))
    if len(pts) <= 2:
        return pts
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and _cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and _cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def hull_distance(h, p):
    """Distance from p to the convex polygon h (0 inside or on it)."""
    if len(h) >= 3 and all(_cross(h[i], h[(i + 1) % len(h)], p) >= 0 for i in range(len(h))):
        return 0.0
    if len(h) == 1:
        return math.hypot(p[0] - h[0][0], p[1] - h[0][1])
    return min(_seg_dist(p, h[i], h[(i + 1) % len(h)]) for i in range(len(h)))


class Slices:
    """The CT test on one scan level: vol (a Volume), f (level-0 voxels per voxel there), vox_mm (its voxel size)."""

    def __init__(self, vol, f, vox_mm):
        self.vol, self.f, self.vox_mm, self.hulls = vol, f, vox_mm, {}

    def _window(self, x, y, z, r):
        zi, yc, xc = int(z) // self.f, y / self.f, x / self.f
        return zi, yc, xc, (int(math.floor(yc - r)) - 1, int(math.ceil(yc + r)) + 1, int(math.floor(xc - r)) - 1, int(math.ceil(xc + r)) + 1)

    def near_tiles(self, x, y, z):
        zi, _, _, (y0, y1, x0, x1) = self._window(x, y, z, FAR_MM / self.vox_mm)
        return self.vol.tiles(zi, y0, y1, x0, x1)

    def slice_tiles(self, z):
        return self.vol.tiles(int(z) // self.f, 0, self.vol.shape[1], 0, self.vol.shape[2])

    def material_near(self, x, y, z):
        """True when a nonzero voxel center lies within FAR_MM of the point in its slice."""
        r = FAR_MM / self.vox_mm
        zi, yc, xc, (y0, y1, x0, x1) = self._window(x, y, z, r)
        for j, row in zip(range(y0, y1), self.vol.rows(zi, y0, y1, x0, x1)):
            dy = j + 0.5 - yc
            if abs(dy) > r:
                continue
            half = math.sqrt(r * r - dy * dy)
            a, b = math.ceil(xc - half - 0.5), math.floor(xc + half - 0.5)
            seg = row[max(0, a - x0):max(0, b - x0 + 1)]
            if seg.count(0) < len(seg):
                return True
        return False

    def hull_of(self, zi):
        """Convex hull of slice zi's nonzero voxel centers, in voxels of this level (None for an empty slice)."""
        if zi not in self.hulls:
            pts = []
            Y, X = self.vol.shape[1], self.vol.shape[2]
            for y, row in enumerate(self.vol.rows(zi, 0, Y, 0, X)):
                s = row.lstrip(b"\0")
                if s:
                    pts += [(X - len(s) + 0.5, y + 0.5), (len(row.rstrip(b"\0")) - 0.5, y + 0.5)]
            self.hulls[zi] = hull(pts) if pts else None
        return self.hulls[zi]

    def outside(self, x, y, z):
        """None when the point is inside the scroll; else the distance past the slice's hull, mm, or 'empty'."""
        if self.material_near(x, y, z):
            return None
        h = self.hull_of(int(z) // self.f)
        if h is None:
            return "empty"
        d = hull_distance(h, (x / self.f, y / self.f)) * self.vox_mm
        return d if d > FAR_MM else None


def outside_ends(points, sl):
    """The CT test on one line: points as (x, y, z) level-0 voxels sorted by z, sl a Slices.

    Returns (result, None) or (None, why). result holds, per end, the hidden run's length (hidden), how many of its
    points lie outside (far), how many of those are in a slice with no scroll at all (empty) and the largest distance
    past the hull of the others (max_mm)."""
    n = len(points)
    if n < 3:
        return None, "the line has fewer than three points"
    zone = max(1, int(n * END_SHARE))
    idx = sorted(set(range(zone)) | set(range(n - zone, n)) | {n // 2})
    vol = sl.vol
    vol.prefetch([k for i in idx for k in sl.near_tiles(*points[i])])
    mid = points[n // 2]
    if sl.outside(*mid) is not None:
        return None, "its middle point lies outside the scroll in the CT, so the frame or the mask is in doubt"
    X, Y = vol.shape[2] * sl.f, vol.shape[1] * sl.f
    cx = [CORNER * X, (1 - CORNER) * X]
    cy = [CORNER * Y, (1 - CORNER) * Y]
    corner = max(((a, b) for a in cx for b in cy), key=lambda c: math.hypot(c[0] - mid[0], c[1] - mid[1]))
    vol.prefetch(sl.slice_tiles(mid[2]))
    if sl.outside(corner[0], corner[1], mid[2]) is None:
        return None, "a corner of the scan's slice reads as inside the scroll, so the scan's air is not zero"
    far = {}
    for i in idx:
        if i == n // 2:
            continue
        if not sl.material_near(*points[i]):
            vol.prefetch(sl.slice_tiles(points[i][2]))
        far[i] = sl.outside(*points[i])
    res = {}
    for end, order in (("low", range(zone)), ("high", range(n - 1, n - 1 - zone, -1))):
        hit = [k for k, i in enumerate(order) if far[i] is not None]
        hidden = hit[-1] + 1 if hit else 0
        vals = [far[i] for k, i in enumerate(order) if k < hidden and far[i] is not None]
        mms = [v for v in vals if v != "empty"]
        res[end] = {"hidden": hidden, "far": len(vals), "empty": sum(1 for v in vals if v == "empty"),
                    "max_mm": round(max(mms), 1) if mms else None}
    return dict(res, level=None, far_mm=FAR_MM, end_share=END_SHARE), None


def _range_tile(url, chunks, compressor):
    """tile() for a level in the bucket: one range read per plane of an uncompressed chunk; a compressed chunk is read
    whole once and decoded with numcodecs."""
    ch_z, ch_y, ch_x = chunks
    whole, lock = {}, threading.Lock()
    codec = None
    if compressor:
        import numcodecs  # ImportError: the caller marks the line untested
        codec = numcodecs.get_codec(compressor)

    def get(u, rng=None):
        req = urllib.request.Request(u, headers={"Range": "bytes=%d-%d" % rng} if rng else {})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    return None
                err = e
            except OSError as e:
                err = e
        raise err

    def tile(zi, cy, cx):
        key = f"{url}/{zi // ch_z}/{cy}/{cx}"
        plane = ch_y * ch_x
        if codec is None:
            off = (zi % ch_z) * plane
            return get(key, (off, off + plane - 1))
        with lock:
            have = key in whole
        if not have:
            raw = get(key)
            data = bytes(codec.decode(raw)) if raw is not None else None
            with lock:
                whole[key] = data
        data = whole[key]
        return None if data is None else data[(zi % ch_z) * plane:(zi % ch_z + 1) * plane]
    return tile


def open_slices(base, pyramid, um):
    """The CT test's view of one scan: the Slices for level LEVEL (or the coarsest level there is) of its zarr."""
    k = min(LEVEL, len(pyramid) - 1)
    p = pyramid[k]
    comp = None
    if p["compressor"]:
        comp = get_json(f"{base}/{p['path']}/.zarray")["compressor"]
    tile = _range_tile(f"{base}/{p['path']}", p["chunks"], comp)
    f = 2 ** k
    return Slices(Volume(p["shape"], p["chunks"], tile, threads=32), f, um * f / 1000), k


def read_pyramid(base):
    """Every level of the OME-Zarr at base: path, shape, chunks, dtype and compressor id."""
    attrs = get_json(f"{base}/.zattrs")
    out = []
    for lv in [d["path"] for d in attrs["multiscales"][0]["datasets"]]:
        za = get_json(f"{base}/{lv}/.zarray")
        comp = za.get("compressor")
        out.append({"path": lv, "shape": za["shape"], "chunks": za["chunks"], "dtype": za["dtype"],
                    "compressor": comp.get("id") if comp else None})
    return out


def open_scan(source_volume):
    """(Slices, level) for a bucket scan named "SCROLL/volumes/VOL.zarr", or (None, why) when it cannot be read."""
    m = re.search(r"-([0-9.]+)um-", source_volume or "")
    if not m:
        return None, f"no voxel size in the volume name {source_volume!r}"
    base = f"{S3}/{source_volume.strip('/')}"
    try:
        return open_slices(base, read_pyramid(base), float(m.group(1)))
    except ImportError:
        return None, "this scan's chunks are compressed and numcodecs is not installed to read them"
    except Exception as e:  # a scan that cannot be opened: its lines are left whole and say so
        return None, f"the scan's CT could not be opened ({type(e).__name__})"


def check_line(points, scan):
    """(result, why) for one line; scan is (Slices, level) or (None, why). result["level"] is the level read."""
    sl, lev = scan
    if sl is None:
        return None, lev
    try:
        res, why = outside_ends(points, sl)
    except Exception as e:  # a read that failed: the line is left whole and says so
        return None, f"the CT could not be read ({type(e).__name__})"
    if res:
        res["level"] = lev
    return res, why


# ---------- trimming a file ----------

def _path_mm(pts, um):
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) * um / 1000


def cut_of(n, res):
    """The kept slice [a, b) of a line of n points sorted by z, from a result of outside_ends (None keeps all)."""
    if not res:
        return 0, n
    return res["low"]["hidden"], n - res["high"]["hidden"]


def trim_doc(doc, res, why, um=None):
    """A copy of an umbilicus document with the end runs res cuts removed and metadata.papyrus_trim recording it.

    Points keep their file order and keys; the cut is made on their order by z (the order outside_ends tested).
    res None (untested) cuts nothing and records why. um, the voxel size in micrometers, gives the cut in mm."""
    cps = doc["control_points"]
    order = sorted(range(len(cps)), key=lambda i: cps[i]["z"])
    a, b = cut_of(len(cps), res)
    keep = set(order[a:b])
    pts = [(cps[i]["x"], cps[i]["y"], cps[i]["z"]) for i in order]
    out = dict(doc)
    out["control_points"] = [p for i, p in enumerate(cps) if i in keep]
    md = dict(doc.get("metadata") or {})
    um = um if um is not None else md.get("voxelsize_um")
    rec = {"version": VERSION, "rule": RULE, "points_before": len(cps), "points_after": len(keep)}
    if res is None:
        rec.update({"tested": False, "why": why})
    else:
        rec.update({"tested": True, "level": res.get("level"), "far_mm": res["far_mm"], "end_share": res["end_share"]})
        for end, run, edge in (("low", pts[:a + 1] if a else [], a), ("high", pts[b - 1:] if b < len(pts) else [], b - 1)):
            e = res[end]
            rec[end] = {"points": e["hidden"], "outside": e["far"], "empty_slices": e["empty"],
                        "max_mm_past_outline": e["max_mm"]}
            if e["hidden"] and edge >= 0 and edge < len(pts):
                dz = abs(pts[edge][2] - (pts[0][2] if end == "low" else pts[-1][2]))
                rec[end]["z_voxels"] = round(dz, 2)
                if um:
                    rec[end]["z_mm"] = round(dz * um / 1000, 2)
                    rec[end]["path_mm"] = round(_path_mm(run, um), 2)
    md["papyrus_trim"] = rec
    out["metadata"] = md
    return out


def _points(doc):
    return [(p["x"], p["y"], p["z"]) for p in sorted(doc["control_points"], key=lambda p: p["z"])]


def run(files, volume=None, out=None, scans=None, opener=None):
    """check (out None) or trim (out a folder) each file; returns one report row per file.

    scans caches (Slices, level) per volume across calls; opener(source_volume) opens one (open_scan by default)."""
    scans = {} if scans is None else scans
    opener = opener or open_scan
    rows = []
    for f in files:
        f = Path(f)
        doc = json.loads(f.read_text())
        md = doc.get("metadata") or {}
        vol = volume or md.get("source_volume")
        if not vol:
            res, why = None, "the file names no scan (metadata.source_volume); give --volume"
        else:
            if vol not in scans:
                scans[vol] = opener(vol)
            res, why = check_line(_points(doc), scans[vol])
        m = re.search(r"-([0-9.]+)um-", vol or "")
        um = md.get("voxelsize_um") or (float(m.group(1)) if m else None)
        new = trim_doc(doc, res, why, um)
        rec = new["metadata"]["papyrus_trim"]
        rows.append(dict({"file": str(f), "volume": vol}, **rec))
        if out is not None:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / f.name).write_text(json.dumps(new, indent=1) + "\n")
    return rows


def _say(r):
    if not r["tested"]:
        return f"{Path(r['file']).name}: untested, {r['why']}; left whole"
    parts = []
    for end in ("low", "high"):
        e = r[end]
        if e["points"]:
            parts.append(f"{end} {e['points']} points" + (f", {e['z_mm']} mm of height" if "z_mm" in e else "")
                         + (f", up to {e['max_mm_past_outline']} mm past the outline" if e["max_mm_past_outline"] else "")
                         + (f", {e['empty_slices']} in slices with no scroll" if e["empty_slices"] else ""))
    return f"{Path(r['file']).name}: {r['points_before']} to {r['points_after']} points" + (": " + "; ".join(parts) if parts else ", nothing outside")


def main(argv=None):
    if sys.stdout.isatty():                  # the Scrolls look (AGENTS.md, terminal look rule)
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from kit import termstyle
            termstyle.script()
        except ImportError:
            pass
    ap = argparse.ArgumentParser(prog="lineends.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["check", "trim"])
    ap.add_argument("files", nargs="+", help="umbilicus files in the published format")
    ap.add_argument("--out", help="trim: the folder for the trimmed copies")
    ap.add_argument("--volume", help="the scan, SCROLL/volumes/VOL.zarr in the open-data bucket, for every file "
                                     "(default: each file's metadata.source_volume)")
    ap.add_argument("--report", help="write the per-file report here as JSON")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    a = ap.parse_args(argv)
    if a.cmd == "trim" and not a.out:
        ap.error("trim needs --out DIR")
    out = Path(a.out) if a.cmd == "trim" else None
    if out is not None and any(Path(f).resolve().parent == out.resolve() for f in a.files):
        ap.error("--out is the folder of an input file; write the trimmed copies elsewhere")
    rows = run(a.files, a.volume, out)
    if a.report:
        Path(a.report).write_text(json.dumps(rows, indent=1) + "\n")
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            print(_say(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
