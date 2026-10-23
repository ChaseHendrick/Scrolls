"""Build data/lines.json for the Space from the public center-lines dataset folder.

Usage: python3 tools/build_lines.py DATASET_DIR OUT.json
DATASET_DIR is a copy of SharpMeow/vesuvius-center-lines (index.json plus lines/). Only the control points, the
public fields of index.json and each file's frame stamp (voxel size, volume name and grid) are copied; the rest
of each file's metadata is not. Scan shapes are read from the
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
    for name, s in sorted(ix["scrolls"].items()):
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
            grade = None
            m = re.search(r"end check (PASS|FLAG|VOID)", f.get("note", ""))
            if m:
                grade = m.group(1)
            lines.append({
                "source": f["source"], "kind": f["kind"], "credit": f["credit"], "licence": f["licence"],
                "upstream": f["upstream"], "file": f["file"], "sha256": f["sha256"], "z": f["z"],
                "note": f.get("note", ""), "grade": grade, "stamp": stamp, "points": flat,
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
