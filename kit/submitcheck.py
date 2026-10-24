"""A preflight for a folder you plan to submit for a Vesuvius Challenge milestone prize.

It checks only what the prize page states about the files, and quotes the line each check comes from
(https://scrollprize.org/prizes, read 24 Oct 2026; the quotes are in RULES). It never says a submission will pass:
legibility, false-positive mitigation, the methodology and held-out validation are judged by the organizers' review
teams, and are listed as things for you to check.

  problem  a stated file rule the folder breaks (exit 1): no tifxyz mesh, a mesh missing x.tif, y.tif, z.tif or
           meta.json, a grid that does not load, no image, an image named after no mesh, and for the Grand Prize a
           mesh not named column_NN.tifxyz or a gap or repeat in the column numbers
  note     a stated rule the folder may break but a script cannot decide: more than one image where the page asks
           for a single one, no banner image for the Grand Prize, a mesh with no image named after it
  info     numbers to show the reviewers, with no limit stated on the page: each mesh's area and how isometric
           its grid is (kit tifxyz), since the page asks for "a low-distortion isometric 2D parametrization" but
           states no threshold
  you check  every other stated requirement (scale bar, letter sizes, no manual annotation, scroll named,
           methodology, false-positive mitigation, held-out validation, no training overlap)

Grid numbers need numpy and tifffile; without them the file checks still run.
"""

import json
import re
import sys
from pathlib import Path

from .verify import VerifyError

PAGE = "https://scrollprize.org/prizes"
READ = "2026-10-24"
PRIZES = ("first-letters", "grand", "title")
IMAGE_EXT = (".png", ".tif", ".tiff", ".jpg", ".jpeg", ".webp")
TIFXYZ_FILES = ("x.tif", "y.tif", "z.tif", "meta.json")
COLUMN = re.compile(r"^column_(\d+)\.tifxyz$")

# Quoted from PAGE on READ. Each check below names the rule it applies.
RULES = {
    "mesh": {"grand": "The submission must contain a set of meshes in tifxyz format whose union corresponds to the "
                      "totality of the scroll surface to be virtually unwrapped.",
             "first-letters": "The submission must contain the mesh(es), in tifxyz format, of the surface region "
                              "containing the letters",
             "title": "The submission must contain the mesh, in tifxyz format, of the surface region containing the "
                      "title"},
    "flat": {"grand": "Each tifxyz must already include a low-distortion isometric 2D parametrization (flattening).",
             "first-letters": "already including a low-distortion isometric 2D parametrization (flattening)",
             "title": "already including a low-distortion isometric 2D parametrization (flattening)"},
    "names": {"grand": "Name each mesh with a sequential column number (e.g. column_01.tifxyz, column_02.tifxyz, ...) "
                       "following the order of the windings, so every mesh is identifiable by its column."},
    "image": {"grand": "Submissions must include images of the virtually unwrapped papyrus, showing visible and "
                       "legible text.",
              "first-letters": "Submissions must be an image of the virtually unwrapped segment, showing at least 10 "
                               "visible and legible letters within a single 4 cm² area.",
              "title": "Submissions must be an image of the virtually unwrapped region, showing the title visibly "
                       "and legibly."},
    "single": {"grand": "Submit a single static image for each column or sequence of consecutive wraps.",
               "first-letters": "Submit a single static image showing the text region."},
    "image_name": {"grand": "Name each image after the tifxyz mesh (from the same package) used to generate it",
                   "first-letters": "Name each image after the tifxyz mesh (from the same package) used to generate "
                                    "it, so it is traceable to the exact surface it was rendered from.",
                   "title": "Name the image after the tifxyz mesh (from the same package) used to generate it, so it "
                            "is traceable to the exact surface it was rendered from."},
    "banner": {"grand": "Also include a single banner image spanning the full unrolled scroll, showing ink detection "
                        "results across all columns, with each column's number overlaid on it"},
}

MANUAL = {
    "grand": [
        "Include scale bars showing the size of 1cm on each submission image.",
        "Images must be generated programmatically from the reconstructed CT scan volume and the corresponding mesh "
        "submitted in the same package, and should not contain manual annotations of characters or text.",
        "Specify which scroll each image came from.",
        "Verify that at least 70% of each counted column's preserved characters are legible.",
        "No overlap between training and prediction regions.",
        "Please create a Docker image that we can easily run to reproduce your work, and please include system "
        "requirements.",
        "The unrolling pipeline should be fully automated; up to 8 documented hours of human annotation / input are "
        "tolerated.",
        "Any dataset created or used to train ML models must be published publicly, under a CC-BY-NC 4.0 license.",
        "Held-out validation. Run your method on the public input renders/volumes with known ground truth",
        "To qualify, you must have registered on the Vesuvius Challenge Discord at the time of the submission.",
    ],
    "first-letters": [
        "Include a scale bar showing the size of 1 cm on the submission image, and the pixel and millimeter "
        "dimensions of a few representative letters.",
        "Images must be generated programmatically from the reconstructed CT scan volume and the mesh(es) submitted "
        "in the same package, and should not contain manual annotations of characters or text.",
        "Specify which scroll the image comes from. For multiple scrolls, please make multiple submissions.",
        "Annotate the rows of text.",
        "Do not include overlap between training and prediction regions",
        "False-positive mitigation.",
        "Held-out validation. Run your method on the public input renders/volumes with known ground truth",
    ],
    "title": [
        "Include a scale bar showing the size of 1 cm on the submission image, and the pixel and millimeter "
        "dimensions of a few representative letters.",
        "Images must be generated programmatically from the reconstructed CT scan volume and the mesh submitted in "
        "the same package, and should not contain manual annotations of characters or text.",
        "Specify which scan the image comes from",
        "Illustrate the ink predictions in the spatial context of the title search",
        "Do not include overlap between training and prediction regions",
        "False-positive mitigation.",
        "Held-out validation. Run your method on the public input renders/volumes with known ground truth",
    ],
}


def _flag(out, level, rule, text, prize):
    q = RULES.get(rule, {}).get(prize) if rule else None
    out.append({"level": level, "rule": rule, "text": text, "quote": q})


def _stem(path):
    name = path.name
    for ext in IMAGE_EXT:
        if name.lower().endswith(ext):
            return name[:-len(ext)]
    return name


def _named_after(stem, mesh_stems):
    """The mesh an image is named after: its name is the mesh's, or starts with it followed by a separator."""
    for m in sorted(mesh_stems, key=len, reverse=True):
        if stem == m or (stem.startswith(m) and not stem[len(m)].isalnum()):
            return m
    return None


def _grid(folder, voxel_um):
    """kit tifxyz numbers for one mesh, or (None, reason) when they cannot be had."""
    from . import tifxyz
    try:
        seg = tifxyz.load(str(folder), voxel_um=voxel_um)
    except VerifyError as exc:
        return None, str(exc)
    if not seg.valid.any():
        return None, "the grid has no valid nodes"
    inf, st = tifxyz.info(seg), tifxyz.stretch(seg)
    rep, _ = tifxyz.check(seg)
    return {"grid": inf["grid"], "area_cm2": inf["area_cm2"], "area_vox2": inf["area_vox2"],
            "edge_median": [(st["edge_columns"] or {}).get("p50"), (st["edge_rows"] or {}).get("p50")],
            "within_10pct": st["within_10pct"], "holes": rep["holes"]["nodes"], "folds": rep["folds"]["nodes"],
            "stretched": rep["stretched"]["nodes"]}, None


def submitcheck(folder, prize="first-letters", voxel_um=None, grids=True):
    """A JSON-ready report on one folder: {"prize", "folder", "meshes", "images", "flags", "manual", "ok"}."""
    if prize not in PRIZES:
        raise VerifyError(f"unknown prize {prize!r}; choose one of {', '.join(PRIZES)}")
    root = Path(folder)
    if not root.is_dir():
        raise VerifyError(f"no folder at {folder}")
    flags = []
    meshes = sorted(p for p in root.rglob("*") if p.is_dir() and p.name.endswith(".tifxyz"))
    images = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT
                    and not any(q.name.endswith(".tifxyz") for q in p.parents))
    rep = {"prize": prize, "folder": str(root), "page": PAGE, "read": READ, "meshes": [], "images": []}
    if not meshes:
        _flag(flags, "problem", "mesh", "no tifxyz mesh (a folder whose name ends in .tifxyz)", prize)
    numpy_ok = grids
    if grids:
        try:
            import numpy  # noqa: F401
            import tifffile  # noqa: F401
        except ImportError:
            numpy_ok = False
            _flag(flags, "info", None, "grid numbers skipped: pip install numpy tifffile to get them", prize)
    for m in meshes:
        row = {"mesh": str(m.relative_to(root))}
        missing = [f for f in TIFXYZ_FILES if not (m / f).is_file()]
        if missing:
            _flag(flags, "problem", "mesh", f"{row['mesh']}: missing {', '.join(missing)}", prize)
        elif numpy_ok:
            nums, why = _grid(m, voxel_um)
            if nums is None:
                _flag(flags, "problem", "mesh", f"{row['mesh']}: {why}", prize)
            else:
                row.update(nums)
                area = (f"{nums['area_cm2']:.2f} cm2" if nums["area_cm2"] is not None
                        else f"{nums['area_vox2']:.0f} vox2 (give --voxel-um for cm2)")
                _flag(flags, "info", "flat", f"{row['mesh']}: {area}, {nums['holes']} hole, {nums['folds']} fold and "
                      f"{nums['stretched']} stretched nodes (kit tifxyz check); median edge length "
                      f"{nums['edge_median'][0]} and "
                      f"{nums['edge_median'][1]} of the step meta.json promises, {nums['within_10pct']:.1%} of edges "
                      f"within 10 %; the page states no numeric limit", prize)
        rep["meshes"].append(row)
    if prize == "grand" and meshes:
        nums = []
        for m in meshes:
            k = COLUMN.match(m.name)
            if not k:
                _flag(flags, "problem", "names", f"{m.name}: not named column_NN.tifxyz", prize)
            else:
                nums.append(int(k.group(1)))
        if nums:
            seen = sorted(nums)
            dup = sorted({n for n in seen if seen.count(n) > 1})
            gaps = sorted(set(range(seen[0], seen[-1] + 1)) - set(seen))
            if dup:
                _flag(flags, "problem", "names", f"column numbers used twice: {dup}", prize)
            if gaps:
                _flag(flags, "problem", "names", f"column numbers missing between {seen[0]} and {seen[-1]}: {gaps}",
                      prize)
    mesh_stems = {m.name[:-len(".tifxyz")] for m in meshes}
    named, other = {}, []
    for im in images:
        after = _named_after(_stem(im), mesh_stems)
        rep["images"].append({"image": str(im.relative_to(root)), "mesh": after})
        if after:
            named.setdefault(after, []).append(im)
        else:
            other.append(im)
    if not images:
        _flag(flags, "problem", "image", "no image (png, tif, jpg or webp)", prize)
    if prize == "grand":
        if not other and images:
            _flag(flags, "note", "banner", "no image other than the per-mesh ones, so no banner image; the page sets "
                  "no name for it", prize)
        elif len(other) > 1:
            _flag(flags, "problem", "image_name", "images named after no mesh: " +
                  ", ".join(str(p.relative_to(root)) for p in other[:-1]) + f" (one, {other[-1].name}, is taken as "
                  "the banner)", prize)
        for m in sorted(mesh_stems - set(named)):
            _flag(flags, "note", "single", f"{m}.tifxyz has no image named after it (fine only if it is part of a "
                  "sequence of consecutive wraps shown in another image)", prize)
    else:
        for im in other:
            _flag(flags, "problem", "image_name", f"{im.relative_to(root)} is named after no mesh in the folder",
                  prize)
        if prize == "first-letters" and len(images) > 1:
            _flag(flags, "note", "single", f"{len(images)} images; the page asks for a single static image", prize)
    rep["flags"] = flags
    rep["manual"] = MANUAL[prize]
    rep["problems"] = sum(1 for f in flags if f["level"] == "problem")
    rep["ok"] = rep["problems"] == 0
    return rep


def format_report(r):
    lines = [f"{r['folder']}: {len(r['meshes'])} mesh(es), {len(r['images'])} image(s), checked for the "
             f"{r['prize']} prize against {r['page']} (read {r['read']})", ""]
    for f in r["flags"]:
        lines.append(f"  {f['level']:<8}{f['text']}")
        if f["quote"]:
            lines.append(f"          rule: \"{f['quote']}\"")
    if not r["flags"]:
        lines.append("  nothing flagged")
    lines += ["", "You check (stated on the page; no script can):"] + [f"  - \"{q}\"" for q in r["manual"]]
    lines += ["", f"{r['problems']} problem(s). This checks file rules only; the review teams judge the rest."
              if r["problems"] else "No file problems found. This checks file rules only; the review teams judge "
              "the rest."]
    return "\n".join(lines)


def build_parser(p):
    p.add_argument("folder", help="the folder you plan to submit")
    p.add_argument("--prize", choices=PRIZES, default="first-letters", help="which prize's rules to apply")
    p.add_argument("--voxel-um", type=float, help="voxel size of the meshes' volume in um, for areas in cm2")
    p.add_argument("--no-grids", action="store_true", help="file checks only; skip loading the grids")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    return p


def cmd_submitcheck(args):
    """python -m kit submitcheck FOLDER: exit 0 with no problem, 1 with one or more, 2 on a bad folder."""
    try:
        r = submitcheck(args.folder, args.prize, args.voxel_um, grids=not args.no_grids)
    except VerifyError as exc:
        print(f"kit submitcheck: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1, ensure_ascii=False) if args.json else format_report(r))
    return 0 if r["ok"] else 1
