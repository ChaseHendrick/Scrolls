"""Every volume of the Vesuvius Challenge open-data bucket, as one catalog: past, present and new.

Sources, all public, read over anonymous HTTPS, nothing posted:

  metadata.json   https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json (samples, scans, volumes,
                  segments, predictions, licenses)
  the listing     S3 ListObjectsV2 of the bucket: each sample's `SAMPLE/volumes/` folder, which also finds a volume
                  that is in the bucket but not (or no longer, or not yet) in metadata.json
  prizes          https://scrollprize.org/prizes (live page; a volume id named there is eligible) and the dated
                  snapshot kit/data/prizes-*.json (which prize names it)

The bucket is the only data source. A volume whose catalog entry points elsewhere (the 2023 scans served from another
host) is kept in the catalog as "outside-bucket" unless the listing finds it in the bucket, and is never fetched from
the other host. dl.ash2txt.org is never used (refused in code; a test checks it).

The bucket keeps no object versions (ListObjectVersions shows VersionId null for metadata.json, checked 16 Oct 2026), so
the past is what the bucket still holds: superseded volumes (superseded_by set), volumes of earlier scan versions,
scans that have a catalog record but no volume, and listing-only volumes. Each row's "era" says which.

Each row (one per volume): sample, volume id, long id, voxel_um, energy_keV, shape_zyx, size_gb (uint8 level 0),
zarr URL, in_bucket, access, era, surface predictions, normal grids, umbilicus, published segments (count) and ink
(segment ink maps, ink labels, 3D ink predictions), license, prize eligibility. Standard library only.
"""

import gzip
import hashlib
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BUCKET = "vesuvius-challenge-open-data"
BUCKET_URL = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
METADATA_URL = BUCKET_URL + "/metadata.json"
PRIZES_URL = "https://scrollprize.org/prizes"
LICENSE = "CC BY-NC 4.0"
FORBIDDEN_HOSTS = ("dl.ash2txt.org",)
INK_SEGMENT_TYPES = ("ink-detection", "ink-detection-downsampled", "ink-labels", "3d-ink-prediction")
SCHEMA = 1
# Sample, volume and zarr folder names become folder names in the batch state and words in a shell command, so a row
# whose id is anything else (a "..", a "/", a space, a quote) is left out of the catalog and listed under "rejected".
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ScanCatalogError(Exception):
    pass


def safe_id(value):
    """True for a name that is safe as one path component and one shell word (never "." or "..")."""
    return isinstance(value, str) and bool(SAFE_ID.match(value)) and value not in (".", "..")


def valid_shape(shape):
    """True for a level-0 shape of three positive integers."""
    return (isinstance(shape, (list, tuple)) and len(shape) == 3
            and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in shape))


def check_url(url):
    host = urllib.parse.urlparse(url).hostname or ""
    if any(host == h or host.endswith("." + h) for h in FORBIDDEN_HOSTS):
        raise ScanCatalogError(f"refused: {host} is never used; the open-data bucket is the only source")
    return url


def http_get(url, opener=None, timeout=120):
    from urllib.request import Request, urlopen  # here, not at the top: `python -m kit` imports this module
    check_url(url)
    req = Request(url, headers={"User-Agent": "kit-scancatalog", "Accept-Encoding": "identity"})
    with (opener or urlopen)(req, timeout=timeout) as resp:
        data = resp.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def list_prefixes(prefix, get=http_get):
    """Common prefixes (folders) under `prefix` in the bucket, following continuation tokens."""
    out, token = [], None
    while True:
        q = {"list-type": "2", "delimiter": "/", "prefix": prefix}
        if token:
            q["continuation-token"] = token
        root = ET.fromstring(get(BUCKET_URL + "/?" + urllib.parse.urlencode(q)))
        ns = {"s": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
        tag = (lambda t: "s:" + t) if ns else (lambda t: t)
        out += [e.text for e in root.findall(f"{tag('CommonPrefixes')}/{tag('Prefix')}", ns) if e.text]
        if (root.findtext(tag("IsTruncated"), "false", ns) or "false").lower() != "true":
            return out
        token = root.findtext(tag("NextContinuationToken"), None, ns)


def listing(get=http_get):
    """{sample: [zarr folder names under SAMPLE/volumes/]} from the bucket listing."""
    out = {}
    for p in list_prefixes("", get):
        sample = p.rstrip("/")
        if not sample or sample.startswith("_"):
            continue
        out[sample] = sorted(q[len(p) + len("volumes/"):].rstrip("/")
                             for q in list_prefixes(p + "volumes/", get) if q != p + "volumes/")
    return out


def live_prize_ids(html):
    """Volume ids (14 digits) the live prizes page names."""
    return sorted(set(re.findall(r"(?<!\d)(20\d{12})(?!\d)", html or "")))


def snapshot_prizes(snapshot):
    """{volume id: [prize ids]} from a dated prizes snapshot."""
    out = {}
    for prize in (snapshot or {}).get("prizes", []):
        for e in prize.get("eligible", []) or []:
            if e.get("volume"):
                out.setdefault(str(e["volume"]), []).append(prize["id"])
    return out


def parse_long_id(name):
    """Volume id, voxel and energy from a zarr folder name such as 20250821110041-0.500um-masked.zarr."""
    name = name or ""
    out = {}
    m = re.match(r"^(\d{14})", name)
    if m:
        out["volume"] = m[1]
    um = re.search(r"-([\d.]+)um", name)
    kev = re.search(r"-([\d.]+)keV", name)
    if um:
        out["voxel_um"] = float(um[1])
    if kev:
        out["energy_keV"] = float(kev[1])
    return out


def _ink_counts(segments, volume_id):
    n = {"segments": 0, "segment_ink_maps": 0, "ink_labels": 0, "ink_3d": 0}
    for g in segments.values():
        if g.get("original_volume_id") != volume_id:
            continue
        n["segments"] += 1
        types = {d.get("type") for d in g.get("data", [])}
        n["segment_ink_maps"] += bool(types & {"ink-detection", "ink-detection-downsampled"})
        n["ink_labels"] += "ink-labels" in types
        n["ink_3d"] += "3d-ink-prediction" in types
    return n


def _zarr_entry(v):
    for d in v.get("data", []):
        if d.get("type") == "ome-zarr":
            o = (d.get("origins") or [{}])[0]
            roots = [r.get("url", "") for r in o.get("access_roots") or []]
            return o.get("path", ""), roots
    return "", []


def build(cat, bucket_listing, snapshot=None, live_html=None, checked=None):
    """The catalog document: {"schema", "checked", "sources", "volumes": [...], "scans_without_volume": [...],
    "rejected": [rows left out because an id is not a safe name or repeats a key]}."""
    live = set(live_prize_ids(live_html)) if live_html is not None else None
    snap = snapshot_prizes(snapshot)
    rows, seen, rejected = [], set(), []

    def reject(sid, vid, name, reason):
        rejected.append({"sample": str(sid)[:200], "volume": str(vid)[:200], "name": str(name)[:200],
                         "reason": reason})

    samples = cat.get("samples", {})
    for sid in sorted(set(samples) | set(bucket_listing)):
        if not safe_id(sid):
            reject(sid, "", "", "sample id is not a safe name")
            continue
        s = samples.get(sid, {})
        listed = set(bucket_listing.get(sid, []))
        vols = s.get("volumes", {})
        keys = set()
        for vid in sorted(vols):
            v = vols[vid]
            p = v.get("properties", {}) or {}
            path, roots = _zarr_entry(v)
            name = path.rstrip("/").split("/")[-1] if path else (v.get("long_id") or "")
            if not safe_id(vid) or (name and not safe_id(name)):
                reject(sid, vid, name, "volume id or zarr folder name is not a safe name")
                continue
            in_bucket = name in listed or any(r == f"s3://{BUCKET}" for r in roots)
            types = {}
            for d in v.get("data", []):
                types.setdefault(d.get("type"), []).append(d)
            shape = p.get("shape")
            preds = [{"model": (d.get("parameters") or {}).get("model_id"),
                      "level": (d.get("parameters") or {}).get("level")} for d in types.get("surface-prediction-zarr", [])]
            row = {"sample": sid, "volume": vid, "long_id": v.get("long_id") or name,
                   "scan_id": v.get("scan_id"), "voxel_um": p.get("pixel_size_um"),
                   "energy_keV": p.get("energy_keV"), "shape_zyx": shape,
                   "size_gb": round(shape[0] * shape[1] * shape[2] / 1e9, 1) if valid_shape(shape) else None,
                   "zarr_url": f"{BUCKET_URL}/{sid}/volumes/{name}/" if in_bucket else None,
                   "in_bucket": in_bucket, "access": "bucket" if in_bucket else "outside-bucket",
                   "in_metadata": True, "superseded_by": p.get("superseded_by"),
                   "surface_predictions": preds, "normal_grids": len(types.get("normal-grids", [])),
                   "umbilicus": bool(types.get("umbilicus")), "lasagna": len(types.get("lasagna", [])),
                   "volume_ink_3d": len(types.get("ink-detection-3d-zarr", [])),
                   **_ink_counts(s.get("segments", {}), vid),
                   "license": (p.get("license") or {}).get("name"),
                   "prizes_snapshot": sorted(snap.get(vid, [])),
                   "prize_live": (vid in live) if live is not None else None}
            row["era"] = "superseded" if row["superseded_by"] else "current"
            rows.append(row)
            keys.add(vid)
            seen.add((sid, name))
        for name in sorted(listed):
            if (sid, name) in seen:
                continue
            if not safe_id(name):
                reject(sid, "", name, "zarr folder name in the listing is not a safe name")
                continue
            meta = parse_long_id(name)
            # The volume id, else (a second zarr of a known volume id) the folder name without .zarr, else the whole
            # folder name: the first that no earlier row of this sample uses, so every key is unique.
            vid = next((c for c in (meta.get("volume", name), name[:-5] if name.endswith(".zarr") else name, name)
                        if safe_id(c) and c not in keys), None)
            if vid is None:
                reject(sid, meta.get("volume", ""), name, "duplicate volume id")
                continue
            keys.add(vid)
            rows.append({"sample": sid, "volume": vid, "long_id": name, "scan_id": None,
                         "voxel_um": meta.get("voxel_um"), "energy_keV": meta.get("energy_keV"), "shape_zyx": None,
                         "size_gb": None, "zarr_url": f"{BUCKET_URL}/{sid}/volumes/{name}/", "in_bucket": True,
                         "access": "bucket", "in_metadata": False, "superseded_by": None, "surface_predictions": [],
                         "normal_grids": 0, "umbilicus": False, "lasagna": 0, "volume_ink_3d": 0, "segments": 0,
                         "segment_ink_maps": 0, "ink_labels": 0, "ink_3d": 0, "license": None,
                         "prizes_snapshot": sorted(snap.get(vid, [])),
                         "prize_live": (vid in live) if live is not None else None, "era": "listing-only"})
    for r in rows:
        r["prize_eligible"] = bool(r["prize_live"]) if r["prize_live"] is not None else bool(r["prizes_snapshot"])
    have = {r.get("scan_id") for r in rows}
    orphans = []
    for sid, s in sorted(samples.items()):
        for scid, sc in sorted((s.get("scans") or {}).items()):
            if scid in have:
                continue
            p = sc.get("properties", {}) or {}
            orphans.append({"sample": sid, "scan_id": scid, "long_id": sc.get("long_id"),
                            "voxel_um": p.get("pixel_size_um"), "energy_keV": p.get("energy_keV"),
                            "date": (sc.get("creation") or {}).get("date")})
    return {"schema": SCHEMA, "checked": checked or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": {"metadata": METADATA_URL, "listing": BUCKET_URL + "/?list-type=2", "prizes": PRIZES_URL},
            "license_expected": LICENSE, "volumes": rows, "scans_without_volume": orphans, "rejected": rejected}


def key(row):
    return f"{row['sample']}/{row['volume']}"


def fingerprint(row):
    """What a change to a volume's catalog row is measured by (new predictions, grids, segments, supersession)."""
    keep = {k: row.get(k) for k in ("long_id", "voxel_um", "shape_zyx", "in_bucket", "superseded_by",
                                     "surface_predictions", "normal_grids", "umbilicus", "segments", "license")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:16]


def diff(old, new):
    """{"new": [rows], "changed": [rows], "gone": [keys]} between two catalog documents."""
    o = {key(r): r for r in (old or {}).get("volumes", [])}
    n = {key(r): r for r in new.get("volumes", [])}
    return {"new": [n[k] for k in sorted(n) if k not in o],
            "changed": [n[k] for k in sorted(n) if k in o and fingerprint(o[k]) != fingerprint(n[k])],
            "gone": sorted(k for k in o if k not in n)}


def fetch(snapshot=None, get=http_get, live=True):
    """Build the catalog from the network (metadata.json, the listing, the live prizes page)."""
    cat = json.loads(get(METADATA_URL))
    html = None
    if live:
        try:
            html = get(PRIZES_URL).decode("utf-8", "replace")
        except OSError:
            html = None
    return build(cat, listing(get), snapshot, html)


def summary(doc):
    rows = doc["volumes"]
    return {"volumes": len(rows), "samples": len({r["sample"] for r in rows}),
            "era": {e: sum(r["era"] == e for r in rows) for e in ("current", "superseded", "listing-only")},
            "access": {a: sum(r["access"] == a for r in rows) for a in ("bucket", "outside-bucket")},
            "prize_eligible": sum(r["prize_eligible"] for r in rows),
            "license": {str(l): sum(r["license"] == l for r in rows) for l in {r["license"] for r in rows}},
            "scans_without_volume": len(doc["scans_without_volume"]), "rejected": len(doc.get("rejected", []))}


def write(doc, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return path
