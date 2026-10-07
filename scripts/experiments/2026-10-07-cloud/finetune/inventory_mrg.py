"""Idea 2 data inventory: segments of non-target scrolls with a 1.129 um `mrg` ink map and a 9 um
surface volume in the public bucket. Lists object names and sizes only; downloads nothing else.

    python inventory_mrg.py OUT.json [--sizes]

Target scrolls (any scroll in kit/data/prizes-2026-10-06.json except PHerc1447, which left First
Letters on 24 Sep 2026) are skipped without being listed. --sizes also sums the bytes of each
matching 9 um surface-volume prefix (a recursive listing, slow).
"""
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
REPO = Path(__file__).resolve().parents[4]


def targets():
    data = json.loads((REPO / "kit/data/prizes-2026-10-06.json").read_text())
    found = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                if isinstance(v, str) and v.startswith("PHerc"):
                    found.add(v.split("/")[0])
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data["prizes"])
    found.discard("PHerc1447")
    return found


def listing(prefix, delimiter="/"):
    token, prefixes, keys = None, [], []
    while True:
        q = {"list-type": "2", "prefix": prefix}
        if delimiter:
            q["delimiter"] = delimiter
        if token:
            q["continuation-token"] = token
        with urllib.request.urlopen(BUCKET + "/?" + urllib.parse.urlencode(q), timeout=120) as r:
            root = ET.fromstring(r.read())
        prefixes += [e.findtext(NS + "Prefix") for e in root.iter(NS + "CommonPrefixes")]
        keys += [(e.findtext(NS + "Key"), int(e.findtext(NS + "Size"))) for e in root.iter(NS + "Contents")]
        if root.findtext(NS + "IsTruncated") != "true":
            return prefixes, keys
        token = root.findtext(NS + "NextContinuationToken")


def main():
    out, sizes = Path(sys.argv[1]), "--sizes" in sys.argv
    skip = targets()
    scrolls = [p.rstrip("/") for p in listing("")[0] if not p.startswith("_")]
    rows = []
    for scroll in scrolls:
        if scroll in skip or scroll == "PHerc0841":  # PHerc0841 is the test scroll
            continue
        segs = listing(f"{scroll}/segments/")[0]
        print(scroll, len(segs), "segments", flush=True)
        for seg in segs:
            parts = listing(seg)[0]
            if seg + "ink-detection/" not in parts:
                continue
            ink = listing(seg + "ink-detection/")[1]
            mrg = [(k, s) for k, s in ink if re.search(r"1\.129um.*mrg", k)]
            if not mrg:
                continue
            sv = listing(seg + "surface-volumes/")[0] if seg + "surface-volumes/" in parts else []
            sv9 = [p for p in sv if re.search(r"/9\.\d+um-[^/]*/$", p)]
            row = {"scroll": scroll, "segment": seg, "mrg": [{"key": k, "bytes": s} for k, s in mrg],
                   "surface_volumes": sv, "surface_9um": sv9,
                   "ink_labels": seg + "ink-labels/" in parts}
            if sizes:
                row["surface_9um_bytes"] = {p: sum(s for _, s in listing(p, None)[1]) for p in sv9}
            rows.append(row)
            print("  ", seg, "9um" if sv9 else "no-9um", flush=True)
    out.write_text(json.dumps({"skipped_targets": sorted(skip), "rows": rows}, indent=1) + "\n")


if __name__ == "__main__":
    main()
