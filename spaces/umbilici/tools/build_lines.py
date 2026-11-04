"""Build data/lines.json for the Space from the public center-lines dataset folder.

Usage: python3 tools/build_lines.py DATASET_DIR OUT.json [--no-ct]
DATASET_DIR is a copy of SharpMeow/vesuvius-center-lines (index.json plus lines/). Only the control points, the
public fields of index.json (with each Center Finder line's per-end CT end check, ct_ends, ct_untested_scan
as untested, and superseded_by, the newer version of a line), each file's frame
stamp (voxel size, volume name and grid) and its usable_ends are copied; the rest of each file's metadata is not. Scan shapes are read from the
Vesuvius Challenge open-data bucket.

Since 1.13.0 each line also gets "outside": how many control points at each end lie outside the scroll in the CT,
by the test in outside_ends() of the Center Finder's scripts/umbilicus/lineends.py (the one copy of the
test), read from level 5 of the scan's masked OME-Zarr in the same bucket (about 16 KB per range read). The page hides
those end runs by default. The test never changes a line's points, file or sha256. A line it cannot test gets
"outside": null and the reason in "outside_why"; --no-ct skips the test.
"""
import importlib.util
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
# The test lives in the Center Finder (scripts/umbilicus/lineends.py, whose trim command cuts the same end runs from a
# line file), so the page hides exactly what a trim would cut. It is loaded from its file, not through sys.path, so
# the Center Finder's other generic module names never shadow anything: tools/lineends.py beside this file when there
# is one (the Space ships a copy there), else the repository's.
def _load_lineends():
    name = "umbilicus_lineends"
    if name not in sys.modules:
        here = Path(__file__).resolve().parent
        path = here / "lineends.py"
        if not path.exists():
            path = here.parents[2] / "scripts" / "umbilicus" / "lineends.py"
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


_le = _load_lineends()
CORNER, END_SHARE, FAR_MM, LEVEL = _le.CORNER, _le.END_SHARE, _le.FAR_MM, _le.LEVEL
Slices, Volume, hull, hull_distance = _le.Slices, _le.Volume, _le.hull, _le.hull_distance
check_line, open_slices, outside_ends = _le.check_line, _le.open_slices, _le.outside_ends


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
            outside, why = check_line([tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)], scan)
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
