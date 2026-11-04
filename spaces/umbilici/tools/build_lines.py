"""Build data/lines.json for the Space from the public center-lines dataset folder.

Usage: python3 tools/build_lines.py DATASET_DIR OUT.json [--no-ct]
DATASET_DIR is a copy of SharpMeow/vesuvius-center-lines (index.json plus lines/). Only the control points, the
public fields of index.json (with each Center Finder line's per-end CT end check, ct_ends, ct_untested_scan
as untested, and superseded_by, the newer version of a line), each file's frame
stamp (voxel size, volume name and grid) and its usable_ends are copied; the rest of each file's metadata is not. Scan shapes are read from the
Vesuvius Challenge open-data bucket.

Since 1.13.0 each line also gets "outside": how many control points at each end lie outside the scroll in the CT,
by the test in outside_ends() below, read from level 5 of the scan's masked OME-Zarr in the same bucket (about
16 KB per range read). The page hides those end runs by default. The test never changes a line's points, file or
sha256. A line it cannot test gets "outside": null and the reason in "outside_why"; --no-ct skips the test.
"""
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
SOURCES = {
    "bucket": {"label": "Vesuvius Challenge", "short": "VC"},
    "drobkov": {"label": "Alexey Drobkov", "short": "AD"},
    "tauil": {"label": "Abd Elilah (manual)", "short": "AE"},
    "dopico": {"label": "Iyan Dopico", "short": "ID"},
    "finder-v2": {"label": "Chase Hendrick's Center Finder v2", "short": "C2"},
    "finder-polished": {"label": "Chase Hendrick's Center Finder, polished", "short": "CP"},
    "finder": {"label": "Chase Hendrick's Center Finder", "short": "CF"},
}

# The frame stamp VC3D reads from an umbilicus file's metadata (villa volume-cartographer/core/src/Umbilicus.cpp).
STAMP = ("voxelsize_um", "volume", "volume_width", "volume_height", "volume_slices")


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


# ---------- the CT test for line ends ----------
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
    zi = int(mid[2]) // sl.f
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


def test_line(points, scan):
    """outside and outside_why for one line; scan is (Slices, level) or (None, why)."""
    sl, lev = scan
    if sl is None:
        return None, lev
    try:
        res, why = outside_ends(points, sl)
    except Exception as e:  # a read that failed: the line is drawn whole and says so
        return None, f"the CT could not be read ({type(e).__name__})"
    if res:
        res["level"] = lev
    return res, why


def main(src, out, *flags):
    src = Path(src)
    ct = "--no-ct" not in flags
    ix = json.loads((src / "index.json").read_text())
    vol_of = {}
    for f in ix["files"]:
        if f.get("volume"):
            vol_of[f["scan"]] = f["volume"]
    scrolls = []
    # the prize page's scans first, then the other public scans (v2.3 and later), each group by name
    for name, s in sorted(ix["scrolls"].items(), key=lambda kv: (not (kv[1]["first_letters"] or kv[1]["grand_prize"]), kv[0])):
        vol = vol_of[s["scan"]]
        base = f"{S3}/{name}/volumes/{vol}"
        attrs = get_json(f"{base}/.zattrs")
        levels = [d["path"] for d in attrs["multiscales"][0]["datasets"]]
        pyramid = []
        for lv in levels:
            za = get_json(f"{base}/{lv}/.zarray")
            comp = za.get("compressor")
            pyramid.append({"path": lv, "shape": za["shape"], "chunks": za["chunks"], "dtype": za["dtype"],
                            "compressor": comp.get("id") if comp else None})
        zarr0 = pyramid[0]
        um = float(re.search(r"-([0-9.]+)um-", vol).group(1))
        if not ct:
            scan = (None, "the page was built without the CT test (--no-ct)")
        else:
            try:
                scan = open_slices(base, pyramid, um)
            except ImportError:
                scan = (None, "this scan's chunks are compressed and the build had no numcodecs to read them")
            except Exception as e:
                scan = (None, f"the scan's CT could not be opened ({type(e).__name__})")
        lines = []
        for f in ix["files"]:
            if f["scroll"] != name:
                continue
            doc = json.loads((src / f["file"]).read_text())
            pts = doc["control_points"]
            md = doc.get("metadata") or {}
            stamp = {k: md[k] for k in STAMP if k in md}
            flat = []
            for p in sorted(pts, key=lambda p: p["z"]):
                flat += [round(p["x"]), round(p["y"]), round(p["z"])]
            outside, why = test_line([tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)], scan)
            # v2.2 and later grade each end on CT (index ct_ends); a line is FLAG if either end is. Older releases
            # carried one grade in the note.
            ends = {k: {q: e[q] for q in ("grade", "recapped", "D_mm") if q in e} for k, e in (f.get("ct_ends") or {}).items()}
            grade = None
            if ends:
                grade = "FLAG" if any(e.get("grade") != "PASS" for e in ends.values()) else "PASS"
            else:
                m = re.search(r"end check (PASS|FLAG|VOID)", f.get("note", ""))
                if m:
                    grade = m.group(1)
            use = md.get("usable_ends")
            # the license key keeps the dataset index's own published spelling, so data/lines.json reads like
            # index.json and its readers keep working (the page's tables and labels say license; app.js lic())
            lines.append({
                "source": f["source"], "kind": f["kind"], "credit": f["credit"], "licence": f["licence"],
                "upstream": f["upstream"], "file": f["file"], "sha256": f["sha256"], "z": f["z"],
                "note": f.get("note", ""), "grade": grade, "ends": ends, "untested": bool(f.get("ct_untested_scan")),
                "usable": [k for k in ("low", "high") if use.get(k)] if isinstance(use, dict) else None,
                "stamp": stamp, "points": flat,
                # v2.5 and later: the file of the newer version of this line, if there is one (the page fades it)
                "superseded_by": f.get("superseded_by"),
                # 1.13.0: the end runs that lie outside the scroll in the CT (outside_ends); null with the reason
                # when the line could not be tested
                "outside": outside, "outside_why": why,
            })
        lines.sort(key=lambda l: list(SOURCES).index(l["source"]))
        scrolls.append({
            "scroll": name, "scan": s["scan"], "volume": vol, "zarr": base, "voxel_um": um,
            "shape": zarr0["shape"], "levels": len(levels), "pyramid": pyramid,
            "first_letters": s["first_letters"], "grand_prize": s["grand_prize"], "lines": lines,
        })
        if scan[0] is not None:
            scan[0].vol.cache.clear()
        print(name, vol, zarr0["shape"], len(levels), [(l["source"], l["outside"] and (l["outside"]["low"]["hidden"], l["outside"]["high"]["hidden"])) for l in lines], flush=True)
    Path(out).write_text(json.dumps({"made": ix["made"], "frame": ix["frame"], "sources": SOURCES,
                                     "scrolls": scrolls}, separators=(",", ":")))


if __name__ == "__main__":
    main(*sys.argv[1:])
