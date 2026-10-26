"""The open data's traced segments, for Fiber Checker: which scrolls have segments, on which scans, and where.

Everything comes from the Vesuvius Challenge open data's metadata.json: each segment's tifxyz meshes transformed onto
each scan ("tifxyz-transformed", one per target volume) and each scan's voxel size. Nothing is copied or rehosted;
the Space reads x.tif, y.tif, z.tif and the CT chunks it needs straight from the bucket.
"""
import gzip
import json
import math
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
METADATA = BUCKET + "/metadata.json"
USER_AGENT = "fiber-checker-space (huggingface.co/spaces/SharpMeow/fiber-checker)"
# Scans this Space never reads: PHercParis4 is kept out of every public tool of ours (Chase's rule).
REFUSED_SAMPLES = {"phercparis4"}
# Scrolls on a prize list (scrollprize.org/prizes, snapshot of 11 Oct 2026, kit/data/prizes-2026-10-11.json in
# ChaseHendrick/Scrolls). They can be checked like any other scroll; the examples and guide pictures never use them.
PRIZE_SAMPLES = {"PHerc0125", "PHerc0175A", "PHerc0175B", "PHerc0191", "PHerc0211", "PHerc0257", "PHerc0268",
                 "PHerc0306B", "PHerc0343", "PHerc0358", "PHerc0483A", "PHerc0483B", "PHerc0490A", "PHerc0490B",
                 "PHerc0800", "PHerc0813", "PHerc0826", "PHerc0846A", "PHerc0846B", "PHerc1203", "PHerc1218",
                 "PHerc1447", "PHerc1545", "PHercParis4"}
TARGET_UM = 9.0              # the free judge was trained and tested on renders of about 9 um voxels
TESTED_UM = (2.1, 2.5)       # level 2 of the 2.2 to 2.4 um scans: the setting both held-out tests used
CACHE = Path(os.environ.get("FIBERCHECK_CACHE") or Path(tempfile.gettempdir()) / "fiber-checker")


class CatalogError(Exception):
    """A refusal or failure shown to the visitor as is."""


def http_get(url, timeout=60, tries=4):
    """Bytes at `url`, or None for a missing object."""
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None
            err = exc
        except (urllib.error.URLError, OSError) as exc:
            err = exc
        time.sleep(1.5 * (i + 1))
    raise CatalogError(f"could not read {url}: {err}")


def level_for(um):
    """The CT level whose voxels are nearest 9 um (2 for 2.2 to 2.4 um scans, 0 for 7.9 to 9.4 um)."""
    return max(0, int(round(math.log2(TARGET_UM / float(um))))) if um else 0


_CAT = {"at": 0.0, "rows": None}
_LOCK = threading.Lock()


def catalog(refresh_s=6 * 3600):
    """{sample: [segment row, ...]}: one row per segment and scan it was transformed onto."""
    with _LOCK:
        if _CAT["rows"] is not None and time.time() - _CAT["at"] < refresh_s:
            return _CAT["rows"]
        raw = http_get(METADATA)
        if raw is None:
            raise CatalogError("the open data's metadata.json is missing")
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        meta = json.loads(raw)
        rows, scans = {}, {}
        for sid, s in sorted((meta.get("samples") or {}).items()):
            if sid.lower() in REFUSED_SAMPLES:
                continue
            vols = s.get("volumes") or {}
            for vid, v in vols.items():
                um = (v.get("properties") or {}).get("pixel_size_um")
                if um and v.get("long_id"):
                    scans[vid] = {"sample": sid, "volume": vid, "voxel_um": float(um), "level": level_for(um),
                                  "tested": TESTED_UM[0] <= float(um) <= TESTED_UM[1], "prize": sid in PRIZE_SAMPLES,
                                  "ct": f"{BUCKET}/{sid}/volumes/{v['long_id'].rstrip('/')}/"}
            for gid, g in sorted((s.get("segments") or {}).items()):
                for d in g.get("data") or []:
                    if d.get("type") != "tifxyz-transformed":
                        continue
                    vid = (d.get("parameters") or {}).get("target_volume")
                    v = vols.get(vid) or {}
                    um = (v.get("properties") or {}).get("pixel_size_um")
                    path = ((d.get("origins") or [{}])[0]).get("path")
                    if not (vid and um and path and v.get("long_id")):
                        continue
                    rows.setdefault(sid, []).append({
                        "sample": sid, "segment": gid, "name": g.get("long_id") or gid, "volume": vid,
                        "voxel_um": float(um), "level": level_for(um),
                        "tested": TESTED_UM[0] <= float(um) <= TESTED_UM[1],
                        "mesh": f"{BUCKET}/{path.rstrip('/')}/",
                        "ct": f"{BUCKET}/{sid}/volumes/{v['long_id'].rstrip('/')}/",
                        "prize": sid in PRIZE_SAMPLES})
        _CAT.update(at=time.time(), rows=rows, scans=scans)
        return rows


def scan(vid):
    """One CT volume of the open data by its 14-digit id (for a visitor's own mesh)."""
    vid = str(vid or "").strip().rstrip("/").split("/")[-1][:14]
    catalog()
    if vid in _CAT["scans"]:
        return _CAT["scans"][vid]
    raise CatalogError(f"{vid!r} is not a scan this Space reads; give the 14-digit volume id from the open data, "
                       "such as 20250526151718 (PHercParis4 is never read)")


def samples():
    return sorted(catalog())


def segments(sample):
    rows = catalog().get(sample)
    if not rows:
        raise CatalogError(f"{sample!r} has no traced segments in the open data")
    return rows


def find(sample, segment, volume=None):
    """The row for one segment on one scan: the scan given, or the tested setting's scan, or the first."""
    rows = [r for r in segments(sample) if segment in (r["segment"], r["name"])]
    if not rows:
        raise CatalogError(f"{segment!r} is not a traced segment of {sample}")
    if volume:
        rows_v = [r for r in rows if r["volume"] == str(volume)]
        if not rows_v:
            raise CatalogError(f"{segment} has no mesh on scan {volume}; it has {', '.join(r['volume'] for r in rows)}")
        return rows_v[0]
    return sorted(rows, key=lambda r: (not r["tested"], abs(r["voxel_um"] * 2 ** r["level"] - TARGET_UM)))[0]


def fetch_mesh(row):
    """x.tif, y.tif, z.tif (and meta.json) of a segment's mesh, cached by its bucket path."""
    folder = CACHE / "meshes" / row["mesh"].split("://")[-1].strip("/").replace("/", "_")
    if all((folder / f).is_file() for f in ("x.tif", "y.tif", "z.tif")):
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    for f in ("x.tif", "y.tif", "z.tif", "meta.json"):
        data = http_get(row["mesh"] + f, timeout=120)
        if data is None:
            if f == "meta.json":
                continue
            raise CatalogError(f"{row['mesh']}{f} is missing in the open data")
        tmp = folder / (f + ".part")
        tmp.write_bytes(data)
        tmp.replace(folder / f)
    return folder


def prune(folder, keep_bytes):
    """Delete the oldest files under `folder` until it holds at most `keep_bytes` (the CT chunk cache)."""
    files = [p for p in Path(folder).rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    if total <= keep_bytes:
        return 0
    freed = 0
    for p in sorted(files, key=lambda q: q.stat().st_atime):
        size = p.stat().st_size
        p.unlink(missing_ok=True)
        freed += size
        if total - freed <= keep_bytes:
            break
    return freed
