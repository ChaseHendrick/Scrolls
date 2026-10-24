"""What published ink labels exist for a scroll, and which public ink models saw them in training.

The open-data bucket keeps human ink labels beside each labeled segment, as
SCROLL/segments/SEGMENT/ink-labels/<voxel size>um-volume-<VOLUME>/<date>/<name>.zarr: inklabels (the ink), supervision
(where the labels may be trusted) and, for some, validation (the part set aside for validation). For one scroll, or
every scroll, this lists each labeled segment's label sets with their volume, voxel size, date, array shape and
stored size, read from the bucket.

Beside each it prints what this repository's public records say about training exposure: docs/results.json
`held_out` (the cited reasons) and `held_out_by_reader` (one word per model family), and the PHerc0139 w035 row of
docs/STANDARDS.md section 5. A segment with no record is "unknown", never assumed held out. The records cover the
released readers named there (ink_9um, v8in, v8in-1447, d9v2, Reader v2, Hecate); check a checkpoint's own
training list before calling any segment held out for it.

Published labels only: this reads the bucket and the repository's own files, and judges nothing. Standard library.
"""

import argparse
import concurrent.futures
import json
import re
import sys
import urllib.parse
from pathlib import Path

from . import find
from .verify import VerifyError

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "docs" / "results.json"
STANDARDS = ROOT / "docs" / "STANDARDS.md"
EXPOSURE_LOG = "docs/logs/2026-10-16-reader-exposure.md"
WORKERS = 16
MAX_PAGES = 20             # 20,000 keys per label array before its size is reported as a lower bound
_SET = re.compile(r"^(?P<um>\d+(?:\.\d+)?)um-volume-(?P<volume>\d{14})$")
_SHORT = re.compile(r"-(w\d+)(?:_|$)")

# Which segments each record in docs/results.json `held_out` speaks for (scroll, short segment id, or None for every
# segment of the scroll). The names come from the records' own text; a key missing here is listed as unmatched.
SCOPES = {"w045": ("PHerc0139", "w045"), "w043": ("PHerc0139", "w043"), "PHerc0841": ("PHerc0841", None),
          "PHerc1447": ("PHerc1447", None)}
# Rows of docs/STANDARDS.md section 5 ("Data splits and held-out sets") used the same way.
STANDARDS_ROWS = {"PHerc0139 w035": ("PHerc0139", "w035")}


def http_get(url, tries=5, sleep=None):
    """find.http_get, asked again on 429, 5xx or a dropped connection (the bucket's proxy path drops some)."""
    import time
    import urllib.error
    sleep = sleep or time.sleep
    for attempt in range(tries):
        try:
            return find.http_get(url)
        except urllib.error.HTTPError as exc:
            if not (exc.code == 429 or exc.code >= 500) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
        sleep(min(8.0, 0.5 * 2 ** attempt))


def list_all(prefix, get=http_get, max_pages=MAX_PAGES):
    """([(key, size)] under a bucket prefix at any depth, True when the listing stopped at max_pages)."""
    out, token = [], None
    for _ in range(max_pages):
        q = {"list-type": "2", "prefix": prefix}
        if token:
            q["continuation-token"] = token
        x = get(f"{find.BUCKET}/?{urllib.parse.urlencode(q)}").decode("utf-8")
        out += [(k, int(s)) for k, s in re.findall(r"<Key>(.*?)</Key>.*?<Size>(\d+)</Size>", x, re.S)]
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", x)
        if not m:
            return out, False
        token = m.group(1)
    return out, True


def _json(keys, prefix, name, get):
    key = prefix + name
    if key not in keys:
        return None
    try:
        return json.loads(get(f"{find.BUCKET}/{urllib.parse.quote(key)}"))
    except (OSError, ValueError):
        return None


def array_info(prefix, get=http_get, sizes=True):
    """{"shape", "dtype", "format", "levels", "bytes", "files", "bytes_at_least"} of one label zarr on the bucket."""
    keys, cut = list_all(prefix, get) if sizes else ([], False)
    names = {k for k, _ in keys}
    if not sizes:
        names = {prefix + n for n in ("zarr.json", ".zattrs", ".zarray", "0/zarr.json", "0/.zarray")}
    out = {"shape": None, "dtype": None, "format": None, "levels": None}
    root = _json(names, prefix, "zarr.json", get)
    level0 = ""
    ms = None
    if root is not None:
        out["format"] = 3
        if root.get("node_type") == "array":
            meta = root
        else:
            ms = ((root.get("attributes") or {}).get("ome") or {}).get("multiscales") or \
                (root.get("attributes") or {}).get("multiscales")
            level0 = (ms[0]["datasets"][0]["path"] + "/") if ms else "0/"
            meta = _json(names, prefix, level0 + "zarr.json", get)
        if meta:
            out.update(shape=meta.get("shape"), dtype=meta.get("data_type"))
    else:
        attrs = _json(names, prefix, ".zattrs", get)
        meta = _json(names, prefix, ".zarray", get)
        if meta is None:
            ms = (attrs or {}).get("multiscales")
            level0 = (ms[0]["datasets"][0]["path"] + "/") if ms else "0/"
            meta = _json(names, prefix, level0 + ".zarray", get)
        if meta:
            out.update(format=2, shape=meta.get("shape"), dtype=meta.get("dtype"))
    if ms:
        out["levels"] = len(ms[0].get("datasets") or [])
    if sizes:
        out.update(bytes=sum(s for _, s in keys), files=len(keys), bytes_at_least=cut)
    return out


def segment_labels(prefix, get=http_get, sizes=True):
    """The label sets under one segment folder (its bucket prefix ending in /): a list of dicts, oldest first."""
    sets = []
    for res in find.list_prefix(prefix + "ink-labels/", get)[0]:
        name = res[len(prefix + "ink-labels/"):].strip("/")
        m = _SET.match(name)
        for dated in find.list_prefix(res, get)[0]:
            sub, files = find.list_prefix(dated, get)
            entry = {"folder": name, "volume": m.group("volume") if m else None,
                     "voxel_um": float(m.group("um")) if m else None, "date": dated[len(res):].strip("/"),
                     "url": f"s3://vesuvius-challenge-open-data/{dated}", "arrays": {}}
            for arr in sub:
                aname = arr[len(dated):].strip("/")
                entry["arrays"][aname[:-5] if aname.endswith(".zarr") else aname] = array_info(arr, get, sizes)
            for key, size in files:
                entry["arrays"][key[len(dated):]] = {"bytes": size, "files": 1}
            sets.append(entry)
    return sorted(sets, key=lambda e: (e["date"], e["folder"]))


def short_id(segment):
    """The w-number of a segment folder name (20260317000000-w035_2026031718 -> w035), or None."""
    m = _SHORT.search(segment)
    return m.group(1) if m else None


def standards_rows(path=STANDARDS):
    """{row label: text} of the table in docs/STANDARDS.md section 5, or {} when the file is not there."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    sec = text.split("## 5. Data splits and held-out sets", 1)
    if len(sec) < 2:
        return {}
    rows = {}
    for line in sec[1].split("\n## ", 1)[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] not in ("Data", "---"):
            rows[cells[0]] = cells[1]
    return rows


def records(results=RESULTS, standards=STANDARDS):
    """[{"key", "scroll", "segment", "text", "by_reader", "source"}] from the public records, and the held_out keys
    that SCOPES does not place (so a new record is never dropped without notice)."""
    try:
        data = json.loads(Path(results).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    held, by = data.get("held_out") or {}, data.get("held_out_by_reader") or {}
    out, unmatched = [], []
    for key, text in held.items():
        if key not in SCOPES:
            unmatched.append(key)
            continue
        scroll, seg = SCOPES[key]
        out.append({"key": key, "scroll": scroll, "segment": seg, "text": text, "by_reader": by.get(key) or {},
                    "source": f"docs/results.json held_out.{key}" + (f" and held_out_by_reader.{key}" if key in by
                                                                       else "")})
    rows = standards_rows(standards)
    for label, (scroll, seg) in STANDARDS_ROWS.items():
        if label in rows:
            out.append({"key": label, "scroll": scroll, "segment": seg, "text": rows[label], "by_reader": {},
                        "source": "docs/STANDARDS.md section 5"})
    return out, unmatched


def exposure(scroll, segment, recs):
    """The records that speak for one segment of a scroll (segment-level first)."""
    sid = short_id(segment)
    mine = [r for r in recs if r["scroll"].lower() == scroll.lower() and (r["segment"] is None or r["segment"] == sid)]
    return sorted(mine, key=lambda r: r["segment"] is None)


def _first_sentence(text, limit=240):
    s = re.split(r"(?<=[a-z0-9)])\. ", text, maxsplit=1)[0].rstrip(".")
    return s if len(s) <= limit else s[:limit - 3].rstrip() + "..."


def inventory(scroll, get=http_get, sizes=True, recs=None, meta=None):
    """Every labeled segment of one scroll, with its label sets and exposure records: a JSON-ready dict."""
    meta = meta or find.get_json(find.METADATA, get)
    name, _ = find.sample(meta, scroll)
    segs = find.list_prefix(f"{name}/segments/", get)[0]
    recs, unmatched = records() if recs is None else (recs, [])

    def one(prefix):
        names = find.list_prefix(prefix, get)[0]
        if prefix + "ink-labels/" not in names:
            return None
        seg = prefix[len(f"{name}/segments/"):].strip("/")
        found = exposure(name, seg, recs)
        return {"segment": seg, "short_id": short_id(seg), "label_sets": segment_labels(prefix, get, sizes),
                "exposure": [{k: r[k] for k in ("key", "by_reader", "source")} | {"summary": _first_sentence(r["text"])}
                             for r in found] or "unknown: no public record in docs/results.json or docs/STANDARDS.md"}

    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        rows = [r for r in ex.map(one, segs) if r]
    return {"scroll": name, "segments": len(segs), "labeled": len(rows), "rows": rows,
            "records_unmatched": unmatched, "exposure_log": EXPOSURE_LOG}


def every_scroll(get=http_get, sizes=False):
    """inventory() for every scroll in metadata.json that has labeled segments."""
    meta = find.get_json(find.METADATA, get)
    recs, unmatched = records()
    out = []
    for name in sorted(meta.get("samples") or {}):
        inv = inventory(name, get, sizes, recs, meta)
        if inv["labeled"]:
            out.append(inv)
    return {"scrolls": out, "records_unmatched": unmatched, "exposure_log": EXPOSURE_LOG}


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000.0


def format_inventory(r):
    lines = [f"{r['scroll']}: {r['labeled']} of {r['segments']} segments carry published ink labels"]
    for row in r["rows"]:
        lines.append(f"  {row['segment']}")
        for s in row["label_sets"]:
            where = f"{s['voxel_um']:g} um volume {s['volume']}" if s["volume"] else s["folder"]
            parts = []
            for a, info in s["arrays"].items():
                shp = "x".join(str(v) for v in info["shape"]) if info.get("shape") else None
                size = (("at least " if info.get("bytes_at_least") else "") + _human(info["bytes"])) \
                    if info.get("bytes") is not None else None
                parts.append(a + (f" {shp}" if shp else "") + (f" {size}" if size else ""))
            lines.append(f"    {s['date']}  {where}: {', '.join(parts)}")
        if isinstance(row["exposure"], str):
            lines.append(f"    exposure  {row['exposure']}")
        for e in row["exposure"] if isinstance(row["exposure"], list) else []:
            if e["by_reader"]:
                lines.append(f"    exposure  " + ", ".join(f"{k} {v}" for k, v in e["by_reader"].items()))
            lines.append(f"    record    {e['summary']} ({e['source']})")
    if r.get("records_unmatched"):
        lines.append(f"  note: records not placed on a segment: {', '.join(r['records_unmatched'])}")
    lines.append(f"Exposure from this repository's public records; sources and reasons: {r['exposure_log']}. "
                 "No record means unknown, not held out.")
    return "\n".join(lines)


def format_every(r):
    lines = [f"{len(r['scrolls'])} scrolls with published ink labels"]
    for inv in r["scrolls"]:
        sets = sum(len(row["label_sets"]) for row in inv["rows"])
        known = sum(1 for row in inv["rows"] if isinstance(row["exposure"], list))
        n = inv["labeled"]
        lines.append(f"  {inv['scroll']:<14} {n:>3} labeled segment{'' if n == 1 else 's'}, {sets} label "
                     f"set{'' if sets == 1 else 's'}, {known} with an exposure record")
    lines.append(f"python -m kit labels SCROLL for one scroll's sets and records ({r['exposure_log']}).")
    return "\n".join(lines)


def build_parser(p):
    p.add_argument("scroll", nargs="?", help="scroll id, for example PHerc0841 (leave out for every scroll)")
    p.add_argument("--no-sizes", action="store_true", help="skip the stored sizes (one listing per label array)")
    p.add_argument("--json", action="store_true")
    return p


def cmd_labels(args):
    """python -m kit labels [SCROLL]: exit 0 when listed, 2 on an unknown scroll or no network."""
    try:
        if args.scroll:
            find.check_id(args.scroll)
            r = inventory(args.scroll, sizes=not args.no_sizes)
            text = format_inventory(r)
        else:
            r = every_scroll(sizes=False)
            text = format_every(r)
    except VerifyError as exc:
        print(f"kit labels: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"kit labels could not read the open-data bucket: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1) if args.json else text)
    return 0


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit.labels", description=__doc__.split("\n\n")[0]))
    return cmd_labels(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
