"""Build data/lines.json for the Space from the public center-lines dataset folder.

Usage: python3 tools/build_lines.py DATASET_DIR OUT.json
DATASET_DIR is a copy of SharpMeow/vesuvius-center-lines (index.json plus lines/). Only the control points, the
public fields of index.json (with each Center Finder line's per-end CT end check, ct_ends, ct_untested_scan
as untested, and superseded_by, the newer version of a line), each file's frame
stamp (voxel size, volume name and grid) and its usable_ends are copied; the rest of each file's metadata is not. Scan shapes are read from the
Vesuvius Challenge open-data bucket.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

S3 = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
SOURCES = {
    "bucket": {"label": "Vesuvius Challenge", "short": "VC"},
    "drobkov": {"label": "Alexey Drobkov", "short": "AD"},
    "tauil": {"label": "Abd Elilah (manual)", "short": "AE"},
    "dopico": {"label": "Iyan Dopico", "short": "ID"},
    "finder-polished": {"label": "Chase Hendrick's Center Finder, polished", "short": "CP"},
    "finder": {"label": "Chase Hendrick's Center Finder", "short": "CF"},
}

# The frame stamp VC3D reads from an umbilicus file's metadata (villa volume-cartographer/core/src/Umbilicus.cpp).
STAMP = ("voxelsize_um", "volume", "volume_width", "volume_height", "volume_slices")


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def main(src, out):
    src = Path(src)
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
            })
        lines.sort(key=lambda l: list(SOURCES).index(l["source"]))
        scrolls.append({
            "scroll": name, "scan": s["scan"], "volume": vol, "zarr": base, "voxel_um": um,
            "shape": zarr0["shape"], "levels": len(levels), "pyramid": pyramid,
            "first_letters": s["first_letters"], "grand_prize": s["grand_prize"], "lines": lines,
        })
        print(name, vol, zarr0["shape"], len(levels), [l["source"] for l in lines])
    Path(out).write_text(json.dumps({"made": ix["made"], "frame": ix["frame"], "sources": SOURCES,
                                     "scrolls": scrolls}, separators=(",", ":")))


if __name__ == "__main__":
    main(*sys.argv[1:])
