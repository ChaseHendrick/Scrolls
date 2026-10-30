"""AutoPipeline's coupled steps labels, fibers and joins, each a swappable stage that reads the step before it.

labels is Snapped Labels' placement, fibers is Weft and joins is the kollesis finder, so one run goes from a traced
surface to a surface label on the papyrus face, the papyrus fibers on it and the glued sheet joins along it.

    python -m kit apcouple init RUN --surface S [--surface S2 ...] --volume URL --voxel-um UM [--umbilicus U]
                                [--sample PHerc0814]          a run folder from any tifxyz surface (couple.json)
    python -m kit apcouple labels|fibers|joins RUN [--use NAME] [--set KEY=VALUE ...]   one step on a run folder
    python -m kit apcouple chain RUN [--use STAGE=NAME ...]   labels, fibers, joins in order
    python -m kit apcouple swap RUN STAGE A B                 two backends of one stage and the steps after it,
                                                              side by side, with swap-STAGE-A-B.json (the diff)
    python -m kit apcouple check RUN [--json]                 the run folder against the steps' contracts
    python -m kit apcouple from-run APRUN [--out RUN]         a run folder from a finished AutoPipeline run
    python -m kit apcouple backends [--json]                  the three stages' backends

After an AutoPipeline run, `from-run APRUN` makes the run folder from the run's accepted traces, its scan and its
center line, so the steps follow the run headless. They are also AutoPipeline backend stages (kit/apbackends.py:
`kit stages list`, `kit autopipeline backends` and `preflight` list and check them, and apbackends.translate turns
{"labels": "snapped", "fibers": "weft", "joins": "kfh1"} into their settings). As plan settings that Run.report
runs after the stack check they come in a later version, and a plan that names them is refused until then. in_autopipe() and
check_plan() are what that wiring will call.

The steps (CONTRACTS says what each reads and writes):

  labels   snapped: kit labelsnap on each surface: the recto-face snap, the abstain mask, the OME-Zarr surface label
           (1 surface, 2 ignore) and the VC3D review queue, the same function `kit labelsnap snap` runs (Snapped
           Labels' placement code). mesh: the surface as given, written as the same surface label with no snap and
           no abstain (the baseline a voxel-exact test compares against). off: nothing; later steps read the surface
  fibers   weft: scripts/afvfibers/weft_trace.py crop on the public AFV V2 fiber probabilities
           (SharpMeow/afv-fiber-probabilities, Qual's AFV V2 model) in a box around each surface (the snapped one
           when labels made one), then the share of fiber points near the surface. The maps must be of the run's own
           scan (frame check). off: nothing
  joins    kfh1: the kollesis finder's score (scripts/kollesis/fullheight.py and
           fh_scores.py) at each end of each horizontal fiber that ends on the surface, the patch followed along
           the surface behind the end; beside it the same score at a point moved back along the surface by the
           shift of 3 cm, the control. Geometry is set in 2.399 um
           voxels, scaled to the scan's voxel size (recorded). off: nothing

Maturity (kit/stagereg.py's scale): every backend here is experimental: no preregistered test has scored these
steps' output on a new trace yet. Every surface, label, fiber and score is Model output, not a reading.

Standard library at import; numpy (and the steps' own tools) when a step runs. Nothing here launches a paid job.
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

VERSION = 1
ROOT = Path(__file__).resolve().parent.parent
WEFT_DIR = ROOT / "scripts" / "afvfibers"
KOLL_DIR = ROOT / "scripts" / "kollesis"
ORDER = ("labels", "fibers", "joins")
AFV_BUCKET = "SharpMeow/afv-fiber-probabilities"
AFV_SCANS = ("PHerc0009B", "PHerc0139", "PHerc0332", "PHerc0814", "PHerc0841", "PHerc1667")
KOLL_UM = 2.399             # the voxel size the kollesis geometry was set in
KOLL_SHIFT = 12500.0        # the shifted control, 3 cm at 2.399 um
FAR_NEED = 6000.0           # kfh1 compares 0 to 600 behind with 4000 to 8000 behind, valid on at least half
                            # the far window (fh_scores.MIN_VALID): a body shorter than this cannot be scored
NOTE = "Every surface, label, fiber and score here is Model output, not a reading."

# Plan settings (kit.autopipe OPTIONAL): absent unless a plan names them, so older plans keep their digest
DEFAULTS = {
    "labels": {"method": "snapped", "level": 0, "label_level": 0, "max_move": None},
    "fibers": {"method": "weft", "bucket": AFV_BUCKET, "scan": None, "box_l0": 1024, "pad_l0": 64, "halo": 64,
               "near_l0": 8.0, "keep_blocks": False},
    "joins": {"method": "kfh1", "family": "H", "near_l0": 8.0, "max_ends": 200, "threads": 12},
}
METHODS = {"labels": ("snapped", "mesh"), "fibers": ("weft",), "joins": ("kfh1",)}

_WHY = {
    "labels": "Snapped Labels' placement code; no preregistered test has scored this step's output on a new trace",
    "fibers": "Weft, our fiber tracer; no preregistered held-out test has scored it against AFV V2 yet",
    "joins": "the kollesis finder's score; untested on Weft fiber ends, along a traced surface and at other voxel "
             "sizes",
}
# The three stages' lines in the stage registry (kit.stagereg.STAGES). They are added here, at import, and not in
# kit/stagereg.py, so that those two files stay as
# they were in 0.1.9; kit/apbackends.py imports this module, and the registry loads apbackends through its extension
STAGE_LINES = {
    "labels": "a surface label on the papyrus face made from a surface (Snapped Labels' placement), the label source",
    "fibers": "papyrus fibers traced on or near a surface",
    "joins": "glued sheet joins (kollesis) scored along a surface at fiber ends",
}


def register_stages():
    """Add the three stages to kit.stagereg.STAGES (once; a stage it already has keeps its line)."""
    from . import stagereg
    for st, line in STAGE_LINES.items():
        stagereg.STAGES.setdefault(st, line)


# Backend tables in kit/apbackends.py's form (kit.apbackends.STAGES takes them in; the stage registry lists them)
STAGES = {
    "labels": {
        "default": "off",
        "choices": {
            "snapped": {"origin": "ours", "by": "Snapped Labels' placement: kit labelsnap moves each surface onto "
                        "the recto face of its CT sheet, with an abstain mask, an OME-Zarr surface label (1 surface, "
                        "2 ignore) and a VC3D review queue (kit/labelsnap.py)", "kind": "classical",
                        "licence": "this repository", "needs": ["numpy"], "compute": "cpu",
                        "maturity": "experimental", "why": _WHY["labels"],
                        "settings": {"labels": {"method": "snapped"}}},
            "mesh": {"origin": "ours", "by": "the surface as given, written as the same OME-Zarr surface label with no "
                     "snap and no abstain: the baseline a voxel-exact test compares against", "kind": "classical",
                     "licence": "this repository", "needs": ["numpy"], "compute": "cpu", "maturity": "experimental",
                     "why": "a baseline, not a claim: voxelizing a mesh is what the community does today",
                     "settings": {"labels": {"method": "mesh"}}},
            "off": {"origin": None, "by": "no surface label: later steps read the surface as traced", "kind": "off",
                    "needs": [], "compute": None, "maturity": "default", "settings": {"labels": None}},
        },
    },
    "fibers": {
        "default": "off",
        "choices": {
            "weft": {"origin": "ours", "by": "Weft (scripts/afvfibers/weft_trace.py crop) on the public AFV V2 fiber "
                     "probabilities of Qual's model (SharpMeow/afv-fiber-probabilities, Qualzz20/afv_fiber_9um_v2, "
                     "Apache-2.0) in a box around each surface", "kind": "classical",
                     "licence": "this repository; the probabilities are CC BY-NC 4.0 like the scans (Qual's model: Apache-2.0)",
                     "needs": ["numpy", "scipy", "numcodecs", "huggingface_hub",
                               "source:scripts/afvfibers/weft_trace.py"],
                     "compute": "cpu", "maturity": "experimental", "why": _WHY["fibers"],
                     "settings": {"fibers": {"method": "weft"}}},
            "off": {"origin": None, "by": "no fibers", "kind": "off", "needs": [], "compute": None,
                    "maturity": "default", "settings": {"fibers": None}},
        },
    },
    "joins": {
        "default": "off",
        "choices": {
            "kfh1": {"origin": "ours", "by": "the kollesis finder's frozen score kfh1 (scripts/kollesis/fullheight.py, "
                     "fh_scores.py) at each horizontal fiber end on the surface, with the shifted-point control",
                     "kind": "classical", "licence": "this repository", "needs": ["numpy", "scipy",
                     "source:scripts/kollesis/fullheight.py"], "compute": "cpu", "maturity": "experimental",
                     "why": _WHY["joins"], "settings": {"joins": {"method": "kfh1"}}},
            "off": {"origin": None, "by": "no joins", "kind": "off", "needs": [], "compute": None,
                    "maturity": "default", "settings": {"joins": None}},
        },
    },
}

# What each step reads and writes in a run folder; check() holds a folder to it
CONTRACTS = {
    "labels": {"reads": ["couple.json: surfaces.<sid>.surface (tifxyz folder), volume_url, umbilicus"],
               "writes": ["labels.json: surfaces.<sid>.{method, surface, label, record}",
                          "labels/<sid>/ (snapped: kit labelsnap's products; mesh: surface_label.zarr, mesh.json)"]},
    "fibers": {"reads": ["couple.json", "labels.json (optional): surfaces.<sid>.surface, else couple.json's"],
               "writes": ["fibers.json: surfaces.<sid>.{afv, box_l0, fibers, near_share}", "fibers/<sid>.afv"]},
    "joins": {"reads": ["couple.json", "labels.json (optional)", "fibers.json: surfaces.<sid>.afv"],
              "writes": ["joins.json: surfaces.<sid>.{file, ends, scored, median}", "joins/<sid>.json"]},
}


class CoupleError(ValueError):
    pass


def _np():
    import numpy
    return numpy


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise CoupleError(f"{path}: {exc}") from None


def _write(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=float))
    tmp.replace(path)


def _top(run):
    """The outermost run folder holding RUN (a swap arm lives inside its parent run): RUN itself, or the highest
    parent with a couple.json."""
    top = Path(run).resolve()
    for q in top.parents:
        if (q / "couple.json").is_file():
            top = q
    return top


def _rel(run, p):
    """A path as a record stores it: relative to the run folder when inside the outermost run folder that holds it
    (so a run folder, swap arms included, can be moved or copied whole), else absolute."""
    if p is None:
        return None
    p, r = Path(p).resolve(), Path(run).resolve()
    try:
        p.relative_to(_top(r))
    except ValueError:
        return str(p)
    return os.path.relpath(p, r)


def _at(run, p):
    """A path a record stores, as a path to open: relative ones are inside the run folder."""
    if p is None:
        return None
    p = Path(p)
    return p if p.is_absolute() else Path(run) / p


PATH_KEYS = {"couple": ("surface",), "labels": ("surface", "label"), "fibers": ("surface", "afv"),
             "joins": ("file",)}


def _rebase(rec, kind, old, new):
    """A record copied from run folder OLD into NEW, its relative paths rewritten to point where they did."""
    rec = json.loads(json.dumps(rec))
    fix = (lambda v: os.path.relpath(Path(old).resolve() / v, Path(new).resolve())
           if v and not Path(v).is_absolute() else v)
    for v in (rec.get("surfaces") or {}).values():
        for k in PATH_KEYS[kind]:
            if k in v:
                v[k] = fix(v[k])
    if kind == "couple" and rec.get("umbilicus"):
        rec["umbilicus"] = fix(rec["umbilicus"])
    return rec


def _token():
    """A record's id: a later step stores the id of the record it read, so check finds stale records."""
    return hashlib.sha256(f"{time.time_ns()}-{os.getpid()}-{os.urandom(8).hex()}".encode()).hexdigest()[:16]


def _token_of(run, stage):
    p = Path(run) / f"{stage}.json"
    return _load(p).get("token") if p.is_file() else None


def sha256_tree(path):
    """sha256 over a file, or over a folder's files (relative names and bytes, sorted)."""
    p = Path(path)
    h = hashlib.sha256()
    if p.is_file():
        h.update(p.read_bytes())
        return h.hexdigest()
    for f in sorted(x for x in p.rglob("*") if x.is_file()):
        h.update(str(f.relative_to(p)).encode() + b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()


def settings_for(stage, given=None):
    """A step's settings: DEFAULTS merged with what is given (None or True for the defaults). Refuses unknown keys
    and methods."""
    s = dict(DEFAULTS[stage])
    if given not in (None, True):
        if not isinstance(given, dict):
            raise CoupleError(f"{stage} is an object (or true for its defaults)")
        bad = [k for k in given if k not in s]
        if bad:
            raise CoupleError(f"{stage}: unknown setting {', '.join(bad)}; settings: {', '.join(s)}")
        s.update(given)
    check(stage, s)
    return s


def check(stage, s):
    """make_plan's refusals for one step's settings."""
    if s.get("method") not in METHODS[stage]:
        raise CoupleError(f"{stage}.method is one of {', '.join(METHODS[stage])}")
    pos = {"labels": (), "fibers": ("box_l0", "near_l0"), "joins": ("near_l0", "max_ends", "threads")}[stage]
    for k in pos:
        v = s.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
            raise CoupleError(f"{stage}.{k} is a number above 0")
    for k in ("level", "label_level", "halo", "pad_l0"):
        if k in s and (isinstance(s[k], bool) or not isinstance(s[k], int) or s[k] < 0):
            raise CoupleError(f"{stage}.{k} is a whole number from 0")
    if stage == "labels" and s.get("max_move") is not None and not (isinstance(s["max_move"], (int, float))
                                                                    and s["max_move"] > 0):
        raise CoupleError("labels.max_move is a number of voxels above 0, or null for kit labelsnap's 4")
    if stage == "joins" and s.get("family") not in ("H", "V", "both"):
        raise CoupleError("joins.family is H, V or both")
    if stage == "fibers" and s.get("scan") is not None and s["scan"] not in AFV_SCANS:
        raise CoupleError(f"fibers.scan is one of the scans with published AFV V2 maps: {', '.join(AFV_SCANS)}")


def check_plan(s):
    """kit.autopipe make_plan's refusals for the three optional settings of a plan's settings s."""
    for stage in ORDER:
        if s.get(stage) is not None:
            check(stage, s[stage])
    if s.get("joins") is not None and s.get("fibers") is None:
        raise CoupleError("joins scores fiber ends: it needs fibers")


# ---------------------------------------------------------------- the run folder

def init(run, surfaces, volume_url, voxel_um, umbilicus=None, sample=None, origin="given"):
    """Write RUN/couple.json: the surfaces the steps read and the scan they live in."""
    run = Path(run)
    run.mkdir(parents=True, exist_ok=True)
    surf = {}
    for i, s in enumerate(surfaces):
        sid, path = (s if isinstance(s, (list, tuple)) else (f"s{i:02d}", s))
        p = Path(path)
        if not all((p / f).is_file() for f in ("x.tif", "y.tif", "z.tif")):
            raise CoupleError(f"{p}: not a tifxyz folder (x.tif, y.tif, z.tif)")
        surf[sid] = {"surface": _rel(run, p), "sha256": sha256_tree(p)}
    if not surf:
        raise CoupleError("init needs at least one surface")
    rec = {"version": VERSION, "origin": origin, "sample": sample, "volume_url": str(volume_url).rstrip("/"),
           "voxel_um": float(voxel_um), "umbilicus": _rel(run, umbilicus) if umbilicus else None,
           "surfaces": surf, "note": NOTE}
    _write(run / "couple.json", rec)
    return rec


def _couple(run):
    p = Path(run) / "couple.json"
    if not p.is_file():
        raise CoupleError(f"{run}: no couple.json (python -m kit apcouple init, or an AutoPipeline run with labels, "
                          "fibers or joins)")
    return _load(p)


def surface_of(run, sid):
    """The surface later steps read: the one labels wrote (snapped), else the run's own."""
    lab = Path(run) / "labels.json"
    if lab.is_file():
        s = (_load(lab).get("surfaces") or {}).get(sid) or {}
        if s.get("surface"):
            return str(_at(run, s["surface"]))
    return str(_at(run, _couple(run)["surfaces"][sid]["surface"]))


# ---------------------------------------------------------------- labels

def labels_args(surface, volume, out, s, umbilicus):
    """The `kit labelsnap snap` argument list this step runs (the parity test runs the same list by hand)."""
    a = [str(surface), "--volume", str(volume), "--out", str(out), "--level", str(s["level"]),
         "--label-level", str(s["label_level"])]
    if umbilicus:
        a += ["--umbilicus", str(umbilicus)]
    if s.get("max_move") is not None:
        a += ["--max-move", str(s["max_move"])]
    return a


def _labelsnap_namespace(argv):
    from . import labelsnap
    p = argparse.ArgumentParser(prog="kit labelsnap")
    labelsnap.build_parser(p)
    try:
        return p.parse_args(["snap"] + list(argv))
    except SystemExit as exc:
        raise CoupleError(f"labels: kit labelsnap refused its arguments {list(argv)}") from exc


def run_labels(run, s=None):
    from . import labelsnap
    s = settings_for("labels", s)
    run = Path(run)
    c = _couple(run)
    if s["method"] == "snapped" and not c.get("umbilicus"):         # refused before anything is deleted
        raise CoupleError("labels snapped names the recto face by the scroll axis: couple.json needs "
                          "umbilicus (init --umbilicus, or the run's umbilicus.json)")
    out = {}
    for sid, sv in sorted(c["surfaces"].items()):
        dest = run / "labels" / sid
        if dest.exists():
            shutil.rmtree(dest)
        t0 = time.time()
        src = _at(run, sv["surface"])
        if s["method"] == "snapped":
            ns = _labelsnap_namespace(labels_args(src, c["volume_url"], dest, s, _at(run, c["umbilicus"])))
            rec = labelsnap.run_snap(ns)
            probs = labelsnap.check_outputs(dest)
            if probs:
                raise CoupleError(f"labels {sid}: kit labelsnap's own check failed: {'; '.join(probs)}")
            surf = dest / "snapped.tifxyz"
            summ = {"vertices": rec["vertices"], "label": rec.get("label"), "review": rec["review"]}
        else:
            summ = mesh_label(src, c["volume_url"], dest, s)
            surf = src
        out[sid] = {"method": s["method"], "surface": _rel(run, surf), "label": _rel(run, dest / "surface_label.zarr"),
                    "record": summ, "seconds": round(time.time() - t0, 2)}
    rec = {"version": VERSION, "stage": "labels", "token": _token(), "settings": s, "surfaces": out,
           "digests": {sid: sha256_tree(_at(run, o["label"])) for sid, o in out.items()}, "note": NOTE}
    _write(run / "labels.json", rec)
    return rec


def mesh_label(surface, volume, dest, s):
    """The mesh baseline: the surface's own vertices voxelized as kit labelsnap's surface label, every vertex
    measured (no abstain, no ignore band)."""
    from . import labelsnap
    from . import snap as S
    np = _np()
    xs, ys, zs, valid = S.load_mesh(surface)
    vol = S.open_volume(volume)
    if not 0 <= s["label_level"] < len(vol.levels):
        raise CoupleError(f"labels.label_level {s['label_level']}: the volume has {len(vol.levels)} levels")
    n, ok = S.normals(xs, ys, zs, valid)
    ab = np.full(xs.shape, labelsnap.ABSTAIN_INVALID, np.uint8)
    ab[valid] = labelsnap.ABSTAIN_OK
    dest.mkdir(parents=True, exist_ok=True)
    lab = labelsnap.write_surface_label(Path(dest) / "surface_label.zarr", xs, ys, zs, valid, ab, n,
                                        vol.shape(s["label_level"]), labelsnap.level_scale(vol, s["label_level"]),
                                        0.0, labelsnap.DEFAULTS["label_step"], source=str(volume),
                                        level=s["label_level"])
    rec = {"tool": "kit apcouple labels mesh", "surface": str(surface), "valid": int(valid.sum()), "label": lab}
    (Path(dest) / "mesh.json").write_text(json.dumps(rec, indent=1, default=float))
    return rec


# ---------------------------------------------------------------- fibers

def _weft():
    if str(WEFT_DIR) not in sys.path:
        sys.path.insert(0, str(WEFT_DIR))
    import weft_trace
    return weft_trace


def _norm_url(u):
    u = str(u or "").rstrip("/")
    tail = u.rsplit("/", 1)[-1]
    return u.rsplit("/", 1)[0] if tail.isdigit() else u


def surface_points(surface):
    """(N, 3) xyz level-0 points of a tifxyz surface's valid vertices."""
    from . import snap as S
    np = _np()
    xs, ys, zs, valid = S.load_mesh(surface)
    return np.stack([xs[valid], ys[valid], zs[valid]], 1).astype(np.float64)


def surface_box(P, box_l0, pad=0):
    """[x0, x1, y0, y1, z0, z1] (L0, whole voxels, from 0): the surface's bounding box grown by pad when it fits
    box_l0 on every axis, else a box_l0 cube centered on the vertex nearest the surface's median point (the box stays
    on the surface)."""
    np = _np()
    lo, hi = np.maximum(np.floor(P.min(0)) - pad, 0), np.ceil(P.max(0)) + 1 + pad
    if ((hi - lo) <= box_l0).all():
        c0, c1 = lo, hi
    else:
        med = np.median(P, 0)
        ctr = P[np.argmin(((P - med) ** 2).sum(1))]
        half = np.minimum((hi - lo) / 2, box_l0 / 2)
        c0 = np.maximum(np.floor(ctr - half), 0)
        c1 = c0 + np.ceil(2 * half)
    return [int(v) for v in (c0[0], c1[0], c0[1], c1[1], c0[2], c1[2])]


def needed_blocks(vol, box, halo):
    """The pooled block names (Z_Y_X, level coordinates) weft_trace.run_crop reads for an L0 box."""
    np = _np()
    f = 2 ** int(vol["level"])
    shape2 = np.array(vol["shape_zyx"])
    lo2 = (np.array(box[0::2][::-1], float) / f).astype(int)
    hi2 = (np.array(box[1::2][::-1], float) / f).astype(int)
    rlo = np.maximum(lo2 - halo, 0) // 2 * 2
    rhi = np.minimum(hi2 + halo, shape2)
    b = int(vol.get("block", 512))
    return [f"{z}_{y}_{x}" for z in range((int(rlo[0]) // b) * b, int(rhi[0]), b)
            for y in range((int(rlo[1]) // b) * b, int(rhi[1]), b)
            for x in range((int(rlo[2]) // b) * b, int(rhi[2]), b)]


def fetch_blocks(bucket, scan, names, dest, held=None):
    """Download SCAN/volume.json and the pooled blocks named into dest (pooled/NAME.blosc), skipping files there.
    A block the bucket does not hold is all zero (no CT there), as weft_trace reads it, and is listed as absent."""
    from huggingface_hub import HfApi
    dest = Path(dest)
    (dest / "pooled").mkdir(parents=True, exist_ok=True)
    api = HfApi()
    want = [] if (dest / "volume.json").is_file() else [(f"{scan}/volume.json", str(dest / "volume.json"))]
    if names and held is None:
        held = held_blocks(bucket, scan, api)
    absent = []
    for n in names:
        if (dest / "pooled" / f"{n}.blosc").is_file():
            continue
        if held is not None and f"{n}.blosc" not in held:
            absent.append(n)
            continue
        want.append((f"{scan}/pooled/{n}.blosc", str(dest / "pooled" / f"{n}.blosc")))
    if want:
        api.download_bucket_files(bucket, want)
    return {"downloaded": len(want), "absent": sorted(absent)}


def held_blocks(bucket, scan, api=None):
    """The pooled block file names the bucket holds for a scan (one listing, reused for every surface of a run)."""
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi()
    return {Path(str(getattr(f, "path", f))).name for f in api.list_bucket_tree(bucket, prefix=f"{scan}/pooled")}


def near_share(F, P, near):
    """Share of the fiber points F (xyz) within `near` voxels of the surface points P, or None without scipy."""
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return None
    if not len(F) or not len(P):
        return None
    d, _ = cKDTree(P).query(F, k=1)
    return float((d <= near).mean())


def run_fibers(run, s=None, blocks=None):
    """Weft in each surface's box. `blocks`: a local folder with volume.json and pooled/ (tests, or a mirror); by
    default the blocks come from the bucket into RUN/fibers/blocks, removed after unless keep_blocks."""
    s = settings_for("fibers", s)
    np = _np()
    w = _weft()
    run = Path(run)
    c = _couple(run)
    scan = s["scan"] or c.get("sample")
    out = {}
    held = None                                # the bucket's block listing, read once per run
    for sid in sorted(c["surfaces"]):
        surf = surface_of(run, sid)
        P = surface_points(surf)
        box = surface_box(P, s["box_l0"], s["pad_l0"])
        bdir = Path(blocks) if blocks else run / "fibers" / "blocks"
        fetched = None
        if not blocks:
            if scan not in AFV_SCANS:
                out[sid] = {"status": "not run", "why": f"no published AFV V2 maps for {scan}; scans with maps: "
                                                        f"{', '.join(AFV_SCANS)}"}
                continue
            if not (bdir / "volume.json").is_file():
                fetch_blocks(s["bucket"], scan, [], bdir)
        vol = _load(bdir / "volume.json")
        if _norm_url(vol.get("ct")) != _norm_url(c["volume_url"]):
            raise CoupleError(f"fibers: the AFV maps are of {vol.get('ct')}, the run's scan is {c['volume_url']}: "
                              "a different frame")
        if not blocks:
            want = needed_blocks(vol, box, s["halo"])
            if held is None and want:
                held = held_blocks(s["bucket"], scan)
            fetched = fetch_blocks(s["bucket"], scan, want, bdir, held)
        afv = run / "fibers" / f"{sid}.afv"
        t0 = time.time()
        rc = w.run_crop(argparse.Namespace(volume=str(bdir / "volume.json"), blocks=str(bdir),
                                           crop_l0=[str(v) for v in box], out=str(afv), halo=s["halo"],
                                           exterior=None, frame_from=None, params=None))
        if rc:
            raise CoupleError(f"fibers {sid}: weft_trace crop exited {rc}")
        fib = w.read_afv(afv)
        side = Path(str(afv) + ".json")
        made = _load(side).get("fibers") if side.is_file() else None
        if made is not None and made != len(fib):
            raise CoupleError(f"fibers {sid}: weft_trace wrote {made} fibers but {afv} reads back {len(fib)}: the "
                              "file did not land whole (a network or bucket mount? run in a local folder)")
        F = np.concatenate([q for _, _, q, _ in fib]) if fib else np.zeros((0, 3))
        fam = {k: sum(1 for _, f, _, _ in fib if f == k) for k in ("V", "H")}
        out[sid] = {"status": "done", "surface": _rel(run, surf), "afv": _rel(run, afv), "box_l0": box,
                    "fibers": len(fib),
                    "families": fam, "points": int(len(F)), "near_l0": s["near_l0"],
                    "near_share": near_share(F, P, s["near_l0"]), "seconds": round(time.time() - t0, 1),
                    **({"blocks": fetched} if fetched else {})}
    if not blocks and not s["keep_blocks"]:                 # once, after every surface: neighbors share blocks
        shutil.rmtree(run / "fibers" / "blocks" / "pooled", ignore_errors=True)
    rec = {"version": VERSION, "stage": "fibers", "token": _token(), "reads": {"labels": _token_of(run, "labels")},
           "settings": s, "scan": scan, "surfaces": out,
           "note": "Weft fibers on AFV V2 probabilities. " + NOTE}
    _write(run / "fibers.json", rec)
    return rec


# ---------------------------------------------------------------- joins

def _koll():
    if str(KOLL_DIR) not in sys.path:
        sys.path.insert(0, str(KOLL_DIR))
    import fh_scores
    import fullheight
    return fullheight, fh_scores


class ScaledReader:
    """The kollesis finder's reader in its frozen frame (2.399 um voxels) over a scan of another voxel size: a point
    of that frame at kollesis level L is read at the scan's level `level`, nearest voxel. Identity for a 2.399 um
    scan read at level 1, the frozen setup."""

    def __init__(self, reader, factor, level):
        self.reader, self.factor, self.level = reader, float(factor), int(level)

    @property
    def requests(self):
        return getattr(self.reader, "requests", 0)

    def __call__(self, level, zyx):
        np = _np()
        q = np.asarray(zyx, float) * (2 ** int(level)) * self.factor / (2 ** self.level)
        return self.reader(self.level, q)


def read_level(voxel_um, frozen_level=1):
    """The scan level nearest the frozen read (level 1 of a 2.399 um scan, 4.8 um voxels); 0 for coarser scans."""
    return max(0, int(round(math.log2(KOLL_UM * 2 ** frozen_level / float(voxel_um)))))


def check_zarr(volume_url, level):
    """The kollesis reader reads uncompressed uint8 zarr v2 arrays with 128^3 chunks; refuse others."""
    import urllib.request
    try:
        z = json.loads(urllib.request.urlopen(f"{_norm_url(volume_url)}/{level}/.zarray", timeout=60).read())
    except Exception as exc:  # noqa: BLE001
        raise CoupleError(f"joins: cannot read {volume_url} level {level} header: {exc}") from None
    if z.get("compressor") is not None or z.get("dtype") not in ("|u1", "uint8") or z.get("chunks") != [128] * 3:
        raise CoupleError(f"joins: the kollesis reader takes uncompressed uint8 128^3 chunks; {volume_url} level "
                          f"{level} is {z.get('dtype')} {z.get('chunks')} {z.get('compressor')}")
    return z


def _grid(surface):
    from . import snap as S
    np = _np()
    xs, ys, zs, valid = S.load_mesh(surface)
    return np.stack([xs, ys, zs], -1).astype(np.float64), valid


def surface_body(G, valid, p, t, length, tree=None):
    """A body for the kollesis frame behind the fiber end p (xyz) with outward tangent t: the surface grid line
    through the vertex nearest p that runs closest to t in the horizontal plane, walked away from t (behind the end)
    for `length` voxels, then p. Returns (body (N, 3) ending at p, walked length, distance from p to the surface)."""
    np = _np()
    if tree is None:
        from scipy.spatial import cKDTree
        idx = np.argwhere(valid)
        tree = (cKDTree(G[valid]), idx)
    kd, idx = tree
    d, k = kd.query(p)
    r, c = (int(v) for v in idx[k])
    th = np.array([t[0], t[1], 0.0])
    th = th / (np.linalg.norm(th) + 1e-12)
    best = None
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        r1, c1 = r + dr, c + dc
        if 0 <= r1 < G.shape[0] and 0 <= c1 < G.shape[1] and valid[r1, c1]:
            v = G[r1, c1] - G[r, c]
            v = np.array([v[0], v[1], 0.0])
            cos = float(np.dot(v, -th) / (np.linalg.norm(v) + 1e-12))     # behind: against the outward tangent
            if best is None or cos > best[0]:
                best = (cos, dr, dc)
    if best is None or best[0] < 0.5:
        return None, 0.0, float(d)
    _, dr, dc = best
    pts, walked, rr, cc = [G[r, c]], 0.0, r, c
    while walked < length:
        r1, c1 = rr + dr, cc + dc
        if not (0 <= r1 < G.shape[0] and 0 <= c1 < G.shape[1]) or not valid[r1, c1]:
            break
        walked += float(np.linalg.norm(G[r1, c1] - G[rr, cc]))
        pts.append(G[r1, c1])
        rr, cc = r1, c1
    body = np.array(pts[::-1])
    tt = np.asarray(t, float)
    p = np.asarray(p, float)
    while len(body) > 1 and float(np.dot(body[-1] - p, tt)) > 0:   # a vertex beyond the end: the body would double back
        body = body[:-1]
    body = np.concatenate([body, p[None]], 0)
    return body, walked, float(d)


def cut_back(body, dist):
    """The body with its last `dist` voxels of arc removed (a point moved back along it), or None if too short."""
    np = _np()
    seg = np.linalg.norm(np.diff(body, axis=0), axis=1)
    s = np.r_[0, np.cumsum(seg)]
    total = s[-1]
    if total <= dist:
        return None
    at = total - dist
    j = int(np.searchsorted(s, at, side="right"))
    a = (at - s[j - 1]) / max(seg[j - 1], 1e-12)
    end = body[j - 1] + a * (body[j] - body[j - 1])
    return np.concatenate([body[:j], end[None]], 0)


def score_body(body_frozen, reader):
    """kfh1 for one body in the frozen frame (the kollesis finder's frame, extract, features and kfh1 unchanged)."""
    fh, fs = _koll()
    np = _np()
    fr = fh.frame(body_frozen)
    raw, cen, rows = fh.extract(fr, reader)
    f = fh.features(raw, cen)
    v = fs.kfh1({**f, "s": fr["s"].astype(np.float32)})
    return None if not np.isfinite(v) else float(v)


def fiber_ends(fibers, family):
    """[(fiber id, which end 0 or 1, end point xyz, outward unit tangent)] of fibers of the family."""
    np = _np()
    out = []
    for fid, fam, q, _ in fibers:
        if family != "both" and fam != family or len(q) < 3:
            continue
        for which, (p, prev) in enumerate(((q[0], q[min(5, len(q) - 1)]), (q[-1], q[max(-6, -len(q))]))):
            t = np.asarray(p, float) - np.asarray(prev, float)
            n = np.linalg.norm(t)
            if n > 0:
                out.append((int(fid), which, np.asarray(p, float), t / n))
    return out


def need_url(volume_url):
    """joins reads the scan with the kollesis finder's HTTPS reader: refuse a local folder before any step runs."""
    if not str(volume_url).startswith(("http://", "https://")):
        raise CoupleError(f"joins reads the scan over HTTPS (the kollesis finder's reader); {volume_url} is not a URL: "
                          "give init the scan's zarr URL, or turn joins off")


def run_joins(run, s=None, reader=None):
    """kfh1 at each fiber end on the surface, with the shifted control. `reader`: a (level, zyx) -> values function
    in the scan's own voxels (tests); by default the kollesis finder's public-zarr reader."""
    s = settings_for("joins", s)
    np = _np()
    fh, _ = _koll()
    w = _weft()
    run = Path(run)
    c = _couple(run)
    fib = _load(run / "fibers.json") if (run / "fibers.json").is_file() else None
    if fib is None:
        raise CoupleError("joins reads fibers.json: run the fibers step first")
    um = float(c["voxel_um"])
    factor = KOLL_UM / um                      # frozen-frame voxels -> scan voxels
    level = read_level(um)
    if reader is None:
        need_url(c["volume_url"])
        check_zarr(c["volume_url"], level)
        reader = fh.Zarr(_norm_url(c["volume_url"]), workers=int(s["threads"]))
    rd = ScaledReader(reader, factor, level)
    behind = fh.BEHIND * factor                # walked length behind the end, scan voxels
    shift = KOLL_SHIFT * factor
    need = FAR_NEED * factor                   # kfh1's far window needs the patch this far behind the end
    out = {}
    from scipy.spatial import cKDTree
    for sid in sorted(c["surfaces"]):
        fs_ = (fib.get("surfaces") or {}).get(sid) or {}
        if fs_.get("status") != "done":
            out[sid] = {"status": "not run", "why": "no fibers for this surface"}
            continue
        surf = surface_of(run, sid)
        G, valid = _grid(surf)
        tree = (cKDTree(G[valid]), np.argwhere(valid))
        ends = fiber_ends(w.read_afv(str(_at(run, fs_["afv"]))), s["family"])
        rows, t0 = [], time.time()
        tried = 0
        for fid, which, p, t in ends:
            body, walked, dist = surface_body(G, valid, p, t, behind + shift, tree)
            row = {"fiber": fid, "end": which, "point": [round(float(v), 2) for v in p],
                   "surface_distance": round(dist, 2)}
            if dist > s["near_l0"]:
                rows.append({**row, "status": "off surface"})
                continue
            if body is None:
                rows.append({**row, "status": "no surface line behind the end"})
                continue
            if walked < need:
                rows.append({**row, "status": "surface too short behind the end", "walked": round(walked, 1)})
                continue
            if tried >= s["max_ends"]:
                rows.append({**row, "status": "over max_ends"})
                continue
            tried += 1
            k = score_body(body / factor, rd)
            back = cut_back(body, shift) if k is not None and walked >= need + shift else None
            kc = score_body(back / factor, rd) if back is not None else None
            rows.append({**row, "status": "scored" if k is not None else "unscorable", "walked": round(walked, 1),
                         "kfh1": k, "kfh1_shifted": kc})
        sc = [r["kfh1"] for r in rows if r.get("kfh1") is not None]
        ct = [r["kfh1_shifted"] for r in rows if r.get("kfh1_shifted") is not None]
        rec = {"surface": _rel(run, surf), "afv": fs_["afv"], "rows": rows}
        _write(run / "joins" / f"{sid}.json", rec)
        out[sid] = {"status": "done", "file": _rel(run, run / "joins" / f"{sid}.json"), "ends": len(ends),
                    "scored": len(sc), "median": float(np.median(sc)) if sc else None,
                    "shifted_scored": len(ct), "shifted_median": float(np.median(ct)) if ct else None,
                    "statuses": {k: sum(r["status"] == k for r in rows) for k in sorted({r["status"] for r in rows})},
                    "seconds": round(time.time() - t0, 1)}
    rec = {"version": VERSION, "stage": "joins", "token": _token(), "reads": {"fibers": _token_of(run, "fibers")},
           "settings": s, "voxel_um": um, "frozen_um": KOLL_UM,
           "scale": factor, "read_level": level, "behind_l0": behind, "shift_l0": shift, "need_l0": need,
           "surfaces": out,
           "deviation": None if abs(um - KOLL_UM) < 1e-3 else
           f"geometry frozen in {KOLL_UM} um voxels, scaled by {factor:.4f} to this {um} um scan and read at level "
           f"{level} (nearest voxel): untested at this voxel size",
           "note": "kfh1 sorts candidate joins for a person to look at; it is not a detector. " + NOTE}
    _write(run / "joins.json", rec)
    return rec


# ---------------------------------------------------------------- chain, swap, check

RUNNERS = {"labels": run_labels, "fibers": run_fibers, "joins": run_joins}


def chain(run, settings=None, start="labels", **kw):
    """The steps from `start` on, each with its settings (None: off; True or a dict: on). Returns {stage: record}."""
    settings = settings or {}
    j = settings.get("joins")
    if j not in (None, False) and "reader" not in kw and ORDER.index(start) <= ORDER.index("joins"):
        need_url(_couple(run)["volume_url"])            # before labels and fibers spend their compute
    done = {}
    for st in ORDER[ORDER.index(start):]:
        v = settings.get(st)
        if v is None or v is False:
            for f in (f"{st}.json",):
                if (Path(run) / f).exists():
                    (Path(run) / f).unlink()
            done[st] = {"status": "off"}
            continue
        extra = {k: kw[k] for k in (("blocks",) if st == "fibers" else ("reader",) if st == "joins" else ())
                 if k in kw}
        done[st] = RUNNERS[st](run, v, **extra)
    return done


def summary(rec):
    """The few numbers a swap diff compares, per surface, from one step's record."""
    if not rec or rec.get("status") == "off":
        return {"status": "off"}
    keys = {"labels": ("method", "surface"), "fibers": ("fibers", "families", "near_share", "box_l0"),
            "joins": ("ends", "scored", "median", "shifted_median")}[rec["stage"]]
    out = {}
    for sid, v in (rec.get("surfaces") or {}).items():
        out[sid] = {k: v.get(k) for k in keys}
        if rec["stage"] == "labels":
            out[sid]["label_sha256"] = (rec.get("digests") or {}).get(sid)
            vv = (v.get("record") or {}).get("vertices") or {}
            out[sid].update({k: vv.get(k) for k in ("measured", "abstained", "moved")})
    return out


def swap(run, stage, a, b, settings=None, **kw):
    """Run backend a and backend b of one stage, and every step after it, each in its own copy of the run folder
    (RUN/swap-STAGE-A-B/A and .../B, with the steps before `stage` copied as they are), and write
    RUN/swap-STAGE-A-B.json: each arm's per-surface summary of every step it ran and the digest of each record."""
    if stage not in ORDER:
        raise CoupleError(f"swap: stage is one of {', '.join(ORDER)}")
    for n in (a, b):
        if n not in STAGES[stage]["choices"]:
            raise CoupleError(f"swap: {stage} has no backend {n}; backends: {', '.join(STAGES[stage]['choices'])}")
    run = Path(run)
    base = dict(settings or {})
    for st in ORDER:                                   # hold every stage's settings, the swapped one's too
        if base.get(st) is None and (run / f"{st}.json").is_file():
            base[st] = _load(run / f"{st}.json")["settings"]
    if isinstance(base.get(stage), dict):              # the swapped stage keeps its settings, less the backend
        base[stage] = {k: v for k, v in base[stage].items() if k != "method"}
    top = run / f"swap-{stage}-{a}-{b}"
    arms = {}
    for n in (a, b):
        d = top / n
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        _write(d / "couple.json", _rebase(_couple(run), "couple", run, d))
        for st in ORDER[:ORDER.index(stage)]:
            if (run / f"{st}.json").is_file():
                _write(d / f"{st}.json", _rebase(_load(run / f"{st}.json"), st, run, d))
        st_set = dict(base)
        st_set[stage] = (STAGES[stage]["choices"][n].get("settings") or {}).get(stage)
        if st_set[stage] is not None:
            keep = base[stage] if isinstance(base.get(stage), dict) else {}
            mine = DEFAULTS[stage]                     # settings this backend's method takes (all share one table)
            st_set[stage] = {**{k: v for k, v in keep.items() if k in mine}, **st_set[stage]}
        recs = chain(d, st_set, start=stage, **kw)
        arms[n] = {"folder": _rel(run, d), "steps": {st: summary(r) for st, r in recs.items()},
                   "records": {st: sha256_tree(d / f"{st}.json") for st in recs if (d / f"{st}.json").is_file()}}
    changed = sorted(st for st in ORDER[ORDER.index(stage):]
                     if arms[a]["steps"].get(st) != arms[b]["steps"].get(st))
    rec = {"version": VERSION, "stage": stage, "a": a, "b": b, "arms": arms, "changed": changed,
           "note": "Swap one stage, hold the rest: what that stage changes downstream. " + NOTE}
    _write(run / f"swap-{stage}-{a}-{b}.json", rec)
    return rec


def check_run(run):
    """Problems with a run folder against CONTRACTS (empty when fine)."""
    run = Path(run)
    probs = []
    try:
        c = _couple(run)
    except CoupleError as exc:
        return [str(exc)]
    for sid, sv in (c.get("surfaces") or {}).items():
        if not sv.get("surface") or not _at(run, sv["surface"]).is_dir():
            probs.append(f"couple.json: surface {sid} missing at {sv.get('surface')}")
    if not c.get("volume_url"):
        probs.append("couple.json: no volume_url")
    for st in ORDER:
        p = run / f"{st}.json"
        if not p.is_file():
            continue
        r = _load(p)
        if r.get("stage") != st:
            probs.append(f"{st}.json: stage is {r.get('stage')}")
        for sid, v in (r.get("surfaces") or {}).items():
            if sid not in c["surfaces"]:
                probs.append(f"{st}.json: surface {sid} is not in couple.json")
            if v.get("status") == "not run":
                continue
            for k in {"labels": ("surface", "label"), "fibers": ("afv",), "joins": ("file",)}[st]:
                if v.get(k) and not _at(run, v[k]).exists():
                    probs.append(f"{st}.json: {sid}.{k} missing at {v[k]}")
        if st == "joins" and not (run / "fibers.json").is_file():
            probs.append("joins.json without fibers.json: joins reads fibers")
        prev = ORDER[ORDER.index(st) - 1] if st != "labels" else None
        if prev and "reads" in r and (r["reads"] or {}).get(prev) != _token_of(run, prev):
            probs.append(f"{st}.json was made from another {prev}.json than the one here: rerun {st} (or chain from "
                         f"{prev})")
    return probs


# ---------------------------------------------------------------- AutoPipeline

def install(stages, pipeline_stage):
    """Add the three stages to AutoPipeline's backend tables (kit/apbackends.py calls this at load)."""
    for st, table in STAGES.items():
        stages.setdefault(st, table)
        pipeline_stage.setdefault(st, "report")


def from_run(aprun, out=None):
    """A coupled run folder (couple.json) from a finished AutoPipeline run folder: its accepted traced surfaces, its
    scan and its center line (umbilicus.json), read from plan.json and state.json. OUT defaults to APRUN/coupled.
    This is how the steps follow an AutoPipeline run today; inside a plan they come in a later version."""
    aprun = Path(aprun)
    plan, state = aprun / "plan.json", aprun / "state.json"
    if not plan.is_file() or not state.is_file():
        raise CoupleError(f"{aprun}: not an AutoPipeline run folder (plan.json and state.json)")
    plan, state = _load(plan), _load(state)
    r = plan.get("resolved") or {}
    if not r.get("volume_url") or not r.get("voxel_um"):
        raise CoupleError(f"{aprun}: plan.json names no resolved volume_url and voxel_um")
    surfaces = []
    for sid, sv in sorted((state.get("surfaces") or {}).items()):
        if not sv.get("accepted") or not sv.get("surface"):
            continue
        p = Path(sv["surface"])
        surfaces.append((sid, p if p.is_absolute() else aprun / p))
    if not surfaces:
        raise CoupleError(f"{aprun}: no accepted surfaces in state.json")
    um = aprun / "umbilicus.json"
    out = Path(out) if out else aprun / "coupled"
    return init(out, surfaces, r["volume_url"], r["voxel_um"], str(um) if um.is_file() else None, r.get("sample"),
                origin=f"autopipeline run {aprun} (plan {str(plan.get('digest', ''))[:12]})")


def in_autopipe(run):
    """Run.report's call: couple.json from the run's accepted surfaces, then the plan's steps in order. Returns
    report.json's record of them (files and counts)."""
    s = run.s
    out = Path(run.out) / "coupled"                    # its own folder: AutoPipeline's labels/ holds ink labels
    if not any(sv.get("surface") for _, sv in run.surfaces(accepted=True)):
        return {"status": "not run", "why": "no accepted surfaces"}
    from_run(run.out, out)
    recs = chain(out, {st: s.get(st) for st in ORDER})
    return {"status": "done", "steps": {st: summary(r) for st, r in recs.items()},
            "files": [str(out / f"{st}.json") for st in ORDER if (out / f"{st}.json").is_file()], "note": NOTE}


# ---------------------------------------------------------------- command line

def _sets(pairs):
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def _tool_errors():
    """The refusals of the tools the steps call (kit labelsnap, kit snap), reported like apcouple's own."""
    out = []
    for mod, name in (("labelsnap", "LabelSnapError"), ("snap", "SnapError")):
        try:
            out.append(getattr(__import__(f"kit.{mod}", fromlist=["x"]), name))
        except (ImportError, AttributeError):
            pass
    return tuple(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit apcouple", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="a run folder (couple.json) from tifxyz surfaces")
    i.add_argument("run")
    i.add_argument("--surface", action="append", required=True, help="tifxyz folder; SID=PATH names it")
    i.add_argument("--volume", required=True, help="the scan's zarr URL or folder (level-0 coordinates)")
    i.add_argument("--voxel-um", type=float, required=True)
    i.add_argument("--umbilicus", help="the scroll axis (kit snap's umbilicus format); labels snapped needs it")
    i.add_argument("--sample", help="the scan's scroll id, such as PHerc0814 (fibers finds its AFV maps by it)")
    f = sub.add_parser("from-run", help="a run folder from a finished AutoPipeline run's accepted surfaces")
    f.add_argument("aprun")
    f.add_argument("--out", help="the coupled run folder (default APRUN/coupled)")
    for st in ORDER:
        q = sub.add_parser(st, help=f"the {st} step on a run folder")
        q.add_argument("run")
        names = ", ".join(n for n in STAGES[st]["choices"] if n != "off")
        q.add_argument("--use", default=None, help=f"backend: {names}")
        q.add_argument("--set", action="append", metavar="KEY=VALUE", help="a setting (JSON value)")
        if st == "fibers":
            q.add_argument("--blocks", help="local folder with volume.json and pooled/ instead of the bucket")
        q.add_argument("--json", action="store_true")
    c = sub.add_parser("chain", help="labels, fibers and joins in order")
    c.add_argument("run")
    c.add_argument("--use", action="append", metavar="STAGE=NAME", help="backend per stage (default: every step on, "
                   "snapped, weft, kfh1; off turns one off)")
    c.add_argument("--blocks")
    c.add_argument("--json", action="store_true")
    w = sub.add_parser("swap", help="two backends of one stage and the steps after it, with the diff")
    w.add_argument("run")
    w.add_argument("stage", choices=ORDER)
    w.add_argument("a")
    w.add_argument("b")
    w.add_argument("--blocks")
    w.add_argument("--json", action="store_true")
    k = sub.add_parser("check", help="the run folder against the steps' contracts")
    k.add_argument("run")
    k.add_argument("--json", action="store_true")
    b = sub.add_parser("backends", help="the three stages' backends and contracts")
    b.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.cmd == "init":
            surfs = [tuple(x.split("=", 1)) if "=" in x and not Path(x).exists() else x for x in a.surface]
            res = init(a.run, surfs, a.volume, a.voxel_um, a.umbilicus, a.sample)
        elif a.cmd == "from-run":
            res = from_run(a.aprun, a.out)
        elif a.cmd in ORDER:
            given = _sets(a.set)
            if a.use:
                given["method"] = a.use
            kw = {"blocks": a.blocks} if a.cmd == "fibers" and a.blocks else {}
            res = RUNNERS[a.cmd](a.run, given or None, **kw)
        elif a.cmd == "chain":
            sets = {st: True for st in ORDER}
            for u in a.use or []:
                st, _, n = u.partition("=")
                if st not in ORDER:
                    raise CoupleError(f"--use {u}: stage is one of {', '.join(ORDER)}")
                sets[st] = None if n == "off" else {"method": n}
            res = chain(a.run, sets, **({"blocks": a.blocks} if a.blocks else {}))
        elif a.cmd == "swap":
            res = swap(a.run, a.stage, a.a, a.b, **({"blocks": a.blocks} if a.blocks else {}))
        elif a.cmd == "check":
            probs = check_run(a.run)
            res = {"run": a.run, "ok": not probs, "problems": probs}
            print(json.dumps(res, indent=1) if a.json else
                  "apcouple check: " + ("ok" if not probs else "FAILED\n  " + "\n  ".join(probs)))
            return 0 if not probs else 1
        else:
            res = {"stages": STAGES, "contracts": CONTRACTS, "defaults": DEFAULTS}
            if not a.json:
                for st in ORDER:
                    print(f"{st} (default off; acts at report, after the stack check)")
                    for n, v in STAGES[st]["choices"].items():
                        print(f"  {n}: {v.get('maturity')}; {v['by']}")
                return 0
    except (CoupleError, *_tool_errors()) as exc:
        print(f"kit apcouple: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1, default=float))
    return 0


register_stages()

if __name__ == "__main__":
    sys.exit(main())
