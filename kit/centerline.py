"""Get a scroll's center line (umbilicus) into your VC3D project or spiral-fitting folder in one command.

Sources, both public: the center lines dataset SharpMeow/vesuvius-center-lines on Hugging Face (every public line
for the prize-eligible scans and, since v2.3, 11 other public scans, each with its sha256 in index.json) and the
open-data bucket's SCROLL/representations/umbilicus/ files. `list` shows every line kit can find; `get` downloads one, checks its
sha256 when the index gives one, and writes it as FOLDER/umbilicus.json, the name VC3D searches for and
spiral-fitting reads (villa main 8aa507c12: volume-cartographer/core/src/ScrollUmbilicus.cpp, spiral-fitting/
fit_session.py; see docs/tools/umbilicus.md). When the file lacks volume_width, volume_height and volume_slices and
the line's volume is known, they are stamped from metadata.json's shape, so VC3D can place the points at any
pyramid level. It replaces an umbilicus.json already in FOLDER only with --force, and never writes beside an
estimated_umbilicus.json (VC3D refuses a folder with both). The line's points are in level-0 voxels of the volume
it names.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from . import find as _find
from .verify import VerifyError

KIND_ORDER = {"person": 0, "bucket": 1, "model": 2}
# Within a kind, a line the dataset marks superseded_by a newer version comes after the lines that are not (since
# v2.5: each original finder line, superseded by its coverage polish, which sat deeper in villa's traced sheet on all
# ten scans of its frozen test, docs/evidence/2026-10-22-umbilicus-windpolish); then a source here comes first, for
# copies of the dataset older than v2.5
SOURCE_ORDER = {"finder-polished": 0}
_VOL_PREFIX = re.compile(r"^(\d{14})-umbilicus")


def lines(scroll, get=_find.http_get):
    """Every line kit can find for a scroll: [{"source", "kind", "volume", "url", "sha256", "credit", "licence"}]."""
    _find.check_id(scroll)
    out = []
    for f in _find.centerlines(scroll, get):
        out.append({"source": f.get("source"), "kind": f.get("kind") or "unknown",
                    "volume": str(f.get("volume") or f.get("scan") or "")[:14] or None, "points": f.get("points"),
                    "url": f"{_find.HUB}/datasets/{_find.CENTERLINES}/resolve/main/{f['file']}",
                    "sha256": f.get("sha256"), "credit": f.get("credit"), "licence": f.get("licence"),
                    "usable_ends": None, "superseded_by": f.get("superseded_by"), "from": _find.CENTERLINES})
    try:
        _, keys = _find.list_prefix(f"{scroll}/representations/umbilicus/", get)
    except OSError:
        keys = []
    for key, _ in keys:
        if not key.endswith(".json"):
            continue
        m = _VOL_PREFIX.match(key.rsplit("/", 1)[-1])
        url = f"{_find.BUCKET}/{key}"
        if any(l["url"] == url for l in out):
            continue
        out.append({"source": "bucket-file", "kind": "bucket", "volume": m.group(1) if m else None, "points": None,
                    "url": url, "sha256": None, "credit": f"{_find.DATA_CREDIT} (representations/umbilicus)",
                    "licence": "CC BY-NC 4.0 (Vesuvius Challenge open data terms)", "from": "open-data bucket"})
    return order(out)


def order(found):
    """Best first: person-made, then bucket, then model lines; within a kind, the newest version of a line (no
    superseded_by) first, then SOURCE_ORDER, then by source name."""
    return sorted(found, key=lambda l: (KIND_ORDER.get(l["kind"], 3), bool(l.get("superseded_by")),
                                        SOURCE_ORDER.get(l["source"], 1),
                                        str(l["source"])))


def pick(found, source=None):
    if not found:
        raise VerifyError("no center line found in the center lines dataset or the bucket")
    if source:
        hit = [l for l in found if l["source"] == source]
        if not hit:
            raise VerifyError(f"no line from source {source!r}; there are: {', '.join(str(l['source']) for l in found)}")
        return hit[0]
    return found[0]


def stamp(data, scroll, volume, get=_find.http_get):
    """Add volume_width, volume_height and volume_slices (from metadata.json) to a line without them."""
    meta = data.setdefault("metadata", {}) if isinstance(data, dict) else None
    if meta is None or not volume or all(k in meta for k in ("volume_width", "volume_height", "volume_slices")):
        return False
    if any(k in meta for k in ("volume_width", "volume_height", "volume_slices")):
        return False  # a partial set is the author's; VC3D refuses it, and we do not guess the rest
    try:
        md = _find.get_json(_find.METADATA, get)
        _, s = _find.sample(md, scroll)
    except (OSError, ValueError, VerifyError):
        return False
    v = (s.get("volumes") or {}).get(volume)
    shape = ((v or {}).get("properties") or {}).get("shape")
    if not (isinstance(shape, list) and len(shape) == 3 and all(isinstance(n, int) and n > 0 for n in shape)):
        return False
    meta["volume_slices"], meta["volume_height"], meta["volume_width"] = shape
    meta.setdefault("volume", v.get("long_id"))
    return True


def get_line(scroll, folder=None, out=None, source=None, force=False, get=_find.http_get, do_stamp=True):
    """Download one line, check it, write it; the report dict."""
    found = lines(scroll, get)
    line = pick(found, source)
    raw = get(line["url"])
    if line["sha256"] and hashlib.sha256(raw).hexdigest() != line["sha256"]:
        raise VerifyError(f"{line['url']}: sha256 differs from the dataset's index.json; not written")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise VerifyError(f"{line['url']} is not JSON: {exc}") from exc
    pts = data.get("control_points") if isinstance(data, dict) else None
    if not isinstance(pts, list) or not pts:
        raise VerifyError(f"{line['url']} has no control_points; VC3D refuses such a file")
    stamped = stamp(data, scroll, line["volume"], get) if do_stamp else False
    if folder:
        folder = Path(folder)
        if not folder.is_dir():
            raise VerifyError(f"no folder {folder}: give the folder that holds your *.volpkg.json, or a spiral fit dataset")
        if (folder / "estimated_umbilicus.json").exists():
            raise VerifyError(f"{folder} has estimated_umbilicus.json; move it away first (VC3D refuses a folder "
                              "with both it and umbilicus.json)")
        if (folder / "umbilicus.json").exists() and not force:
            raise VerifyError(f"{folder} already has umbilicus.json; use --force to replace it")
        dest = folder / "umbilicus.json"
    else:
        dest = Path(out or f"{scroll}_umbilicus.json")
        if dest.exists() and not force:
            raise VerifyError(f"{dest} exists; use --force to replace it")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_text(json.dumps(data, indent=1) if stamped else raw.decode("utf-8"))
    tmp.replace(dest)
    zs = [p.get("z") for p in pts if isinstance(p, dict)]
    meta = data.get("metadata") or {}
    return {"scroll": scroll, "written": str(dest), "source": line["source"], "kind": line["kind"],
            "volume": line["volume"], "points": len(pts), "z": [min(zs), max(zs)] if zs else None,
            "sha256_checked": bool(line["sha256"]), "stamped_grid": stamped, "credit": line["credit"],
            "licence": line["licence"], "usable_ends": meta.get("usable_ends"), "url": line["url"],
            "others": [l["source"] for l in found if l is not line]}


def format_list(scroll, found):
    if not found:
        return f"{scroll}: no center line in {_find.CENTERLINES} or the bucket"
    rows = [f"{scroll}: {len(found)} center line(s), best first"]
    for l in found:
        pts = f"{l['points']} points, " if l["points"] else ""
        rows.append(f"  {str(l['source']):<12} {l['kind']:<7} volume {l['volume'] or '?'}  {pts}{l['licence']}")
        rows.append(f"    {l['url']}")
    return "\n".join(rows)


def format_get(r):
    rows = [f"wrote {r['written']}: {r['source']} line ({r['kind']}), {r['points']} points, z {r['z'][0]:g} to "
            f"{r['z'][1]:g}, level-0 voxels of volume {r['volume'] or '(not stated)'}",
            f"  sha256 {'checked against the index' if r['sha256_checked'] else 'not published for this file'}"
            + ("; grid size stamped from metadata.json" if r["stamped_grid"] else "")]
    if r["usable_ends"] is not None:
        rows.append(f"  usable ends: {r['usable_ends']}")
    if r["kind"] == "model":
        rows.append("  model output: check it on CT slices before relying on it")
    rows.append(f"  credit: {r['credit']}, {r['licence']}")
    if r["others"]:
        rows.append(f"  other sources: {', '.join(str(o) for o in r['others'])} (--source NAME)")
    return "\n".join(rows)


def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("list", help="every center line kit can find for a scroll")
    a.add_argument("scroll")
    a.add_argument("--json", action="store_true")
    a = actions.add_parser("get", help="download one, check it, write it as FOLDER/umbilicus.json")
    a.add_argument("scroll")
    a.add_argument("--into", metavar="FOLDER", help="write FOLDER/umbilicus.json (your VC3D project or fit dataset)")
    a.add_argument("--out", help="write here instead (default: SCROLL_umbilicus.json)")
    a.add_argument("--source", help="pick a source by name (see list); default: person-made, then bucket, then model")
    a.add_argument("--no-stamp", action="store_true", help="leave the file exactly as published")
    a.add_argument("--force", action="store_true", help="replace an existing umbilicus.json")
    a.add_argument("--json", action="store_true")
    return p


def cmd_centerline(args):
    """python -m kit centerline list|get SCROLL: exit 0 when done, 2 on a refusal or a failed download."""
    try:
        if args.action == "list":
            found = lines(args.scroll)
            print(json.dumps(found, indent=1) if args.json else format_list(args.scroll, found))
            return 0
        if args.into and args.out:
            raise VerifyError("give --into or --out, not both")
        r = get_line(args.scroll, args.into, args.out, args.source, args.force, do_stamp=not args.no_stamp)
    except VerifyError as exc:
        print(f"kit centerline: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"kit centerline could not download or write: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1) if args.json else format_get(r))
    return 0


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit.centerline", description=__doc__.split("\n\n")[0]))
    return cmd_centerline(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
