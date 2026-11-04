"""Exposure Atlas: how much of each labeled evaluation segment a released ink model's training segments already cover.

A score on a labeled segment tests an ink model only where the model never trained on that papyrus. Training lists
name segments, and names miss the same sheet traced twice, re-rendered at another resolution, or filed under another
id. This module checks it on the meshes: in one scroll frame (the evaluation segment's own scan), for every vertex
of the evaluation mesh, how far along the normal the nearest training surface lies, counting only training surfaces
whose own footprint covers that spot. It reads tifxyz meshes and the open-data catalog, never labels or CT.

    python -m kit expatlas models [--json]                       every model and how its list was resolved
    python -m kit expatlas segments [--catalog C] [--json]        the labeled evaluation segments in the catalog
    python -m kit expatlas pair EVAL TRAIN [--frame VOL] [--json] one evaluation mesh against one training mesh
    python -m kit expatlas matrix --out DIR [--skip FILE] [--scroll S ...] [--model M ...] [--json]
    python -m kit expatlas plant --prereg FILE --out DIR [--json]  the preregistered instrument checks
    python -m kit expatlas show MATRIX.json [--json]               print a matrix written earlier

The geometry follows dlescanogithub's proposal in ScrollPrize/villa issue 2346 (28 Oct 2026): map both surfaces to
level-0 voxels of one volume, count the share of points within a few voxels of the other surface (KD-tree nearest
neighbour), and look at the z ranges and the render band along the normal. Here the distance is the offset along
the training surface's normal at its nearest vertices, kept only where the tangential distance is inside that
surface's grid footprint, so an edge or a hole is not counted as cover.

Calls per evaluation segment and model (Model output of this geometry; the training lists are Sourced fact or
Community report as each model's entry says):
  trained    its own or inherited training list names the segment
  exposed    at least EXPOSED_FRAC of the evaluation vertices lie within D_SAME_UM of a training surface
  trace      at least TRACE_FRAC but under EXPOSED_FRAC
  selected   the checkpoint was chosen on it (by name), or a validation segment covers it
  clear      no training segment on that scroll, or the geometry finds less than TRACE_FRAC
  unknown    no published list, or names on that scroll that match no catalog segment, and nothing above
  not-run    outside the run's scope (a --scroll filter or a --skip pattern)
Cross-scan pairs depend on the catalog's affine transforms (questioned in villa issues 1835 and 2312). Each such
cell carries the transform's landmark leave-one-out error from kit meshaudit; above TRANSFORM_FLAG_UM it is flagged
"winding uncertain", and above TRANSFORM_LIMIT_UM (half a nominal 140 um winding) a geometric call reads unknown.

Needs numpy, scipy (cKDTree) and tifffile. Network: plain HTTPS to the public open-data bucket.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

from . import meshaudit

SCHEMA = "expatlas/1"
DATA = Path(__file__).resolve().parent / "data"
REGISTRY = DATA / "expatlas-models.json"
BUCKET = meshaudit.BUCKET

D_SAME_UM = 60.0           # same sheet: offset along the normal at most this
BAND_UM = 100.0            # render band: a training input window of about +-100 um would hold this papyrus's CT
REACH_UM = 300.0           # offsets past this are not looked for
EXPOSED_FRAC = 0.05
TRACE_FRAC = 0.005
TRANSFORM_FLAG_UM = 30.0   # half of D_SAME_UM
TRANSFORM_LIMIT_UM = 70.0  # half a nominal winding of 140 um
MAX_EVAL_POINTS = 150_000
FOOTPRINT = 0.8            # tangential reach, as a share of the training grid's step
K_NEAREST = 8
TRAIN_ROLES = ("train", "train_split")
STATUSES = ("trained", "exposed", "trace", "selected", "clear", "unknown", "not-run")
CODES = {"trained": "T", "exposed": "E", "trace": "t", "selected": "S", "clear": ".", "unknown": "?", "not-run": "-"}


class AtlasError(ValueError):
    pass


def _np():
    try:
        import numpy as np
    except ImportError as exc:
        raise AtlasError("numpy is required for kit expatlas") from exc
    return np


def _kdtree():
    try:
        from scipy.spatial import cKDTree
    except ImportError as exc:
        raise AtlasError("scipy is required for kit expatlas (cKDTree)") from exc
    return cKDTree


# ---------------------------------------------------------------- registry and catalog

def load_registry(path=REGISTRY):
    d = json.loads(Path(path).read_text())
    if d.get("schema") != "expatlas-models/1":
        raise AtlasError(f"{path}: schema is not expatlas-models/1")
    ids = [m["id"] for m in d["models"]]
    if len(set(ids)) != len(ids):
        raise AtlasError(f"{path}: model ids repeat")
    for m in d["models"]:
        for p in m.get("inherits", []):
            if p not in ids:
                raise AtlasError(f"{path}: {m['id']} inherits unknown model {p}")
        for e in m["entries"]:
            if e["source"] not in d["sources"]:
                raise AtlasError(f"{path}: {m['id']} cites unknown source {e['source']}")
    return d


def chain(registry, model_id, _seen=None):
    """[(model id, via)] for a model and everything it inherits; via is the path, such as 'd9v2 < ink_9um'."""
    by = {m["id"]: m for m in registry["models"]}
    _seen = _seen or ()
    if model_id in _seen:
        raise AtlasError(f"inheritance loop at {model_id}")
    out = [(model_id, model_id)]
    for p in by[model_id].get("inherits", []):
        out += [(mid, f"{model_id} < {via}") for mid, via in chain(registry, p, _seen + (model_id,))]
    return out


_ON = re.compile(r"(\d{14})-on-(\d{14})-([\d.]+)um\.tifxyz/?$")


def catalog_index(cat):
    """{segment id: {scroll, suffix, volume, meshes {volume: path}, native, labeled}} and {scroll: {volume: um}}."""
    index, px = {}, {}
    for sid, s in cat["samples"].items():
        px[sid] = {v: (x.get("properties") or {}).get("pixel_size_um") for v, x in (s.get("volumes") or {}).items()}
        for gid, g in (s.get("segments") or {}).items():
            rec = {"scroll": sid, "suffix": g.get("suffix") or "", "volume": g.get("original_volume_id"),
                   "meshes": {}, "native": None, "labeled": False}
            for d in g.get("data") or []:
                paths = [o.get("path", "") for o in d.get("origins") or []]
                if d["type"] == "ink-labels":
                    rec["labeled"] = True
                elif d["type"] == "tifxyz-transformed":
                    for p in paths:
                        m = _ON.search(p)
                        if m:
                            rec["meshes"][m.group(2)] = p.rstrip("/")
                elif d["type"] == "tifxyz" and paths:
                    rec["native"] = paths[0].rstrip("/")
            index[gid] = rec
    return index, px


def evaluation_segments(index, scrolls=None):
    return sorted(g for g, r in index.items() if r["labeled"] and (not scrolls or r["scroll"] in scrolls))


def names_of(gid, rec):
    return {gid, rec["suffix"], f"{gid}-{rec['suffix']}"} - {""}


def read_skip(path):
    """Patterns, one per line, SCROLL/GLOB matched against a segment's id, suffix and id-suffix; # starts a comment."""
    pats = []
    if path:
        for line in Path(path).read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                if "/" not in line:
                    raise AtlasError(f"skip pattern {line!r} is not SCROLL/GLOB")
                pats.append(line)
    return pats


def skipped(gid, rec, pats):
    import fnmatch
    for p in pats:
        sc, glob = p.split("/", 1)
        if fnmatch.fnmatchcase(rec["scroll"], sc) and any(fnmatch.fnmatch(n.lower(), glob.lower())
                                                           for n in names_of(gid, rec)):
            return True
    return False


def transform_errors(cat):
    """{(scroll, from volume, to volume): landmark error in um}, leave-one-out RMS where it can be computed, else
    the fit RMS; both directions get the same number."""
    out = {}
    for r in meshaudit.transforms_audit(cat):
        err = r.get("loo_rms_um")
        if err is None:
            err = r.get("fit_rms_um")
        for key in ((r["sample"], r["from_volume"], r["to_volume"]), (r["sample"], r["to_volume"], r["from_volume"])):
            if err is not None and (key not in out or err > out[key]):
                out[key] = err
    return out


def path_error(cat, errors, scroll, a, b):
    """Landmark error of the catalog route from volume a to b: the root sum of squares over its steps, or None."""
    if a == b:
        return 0.0
    _, how = meshaudit.sample_matrix(cat, scroll, a, b)
    if not how:
        return errors.get((scroll, a, b))
    total = 0.0
    for step in how.split("."):
        m = re.match(r"(\d{14})-(\d{14})", step)
        if not m:
            return None
        e = errors.get((scroll, m.group(1), m.group(2)))
        if e is None:
            return None
        total += e * e
    return math.sqrt(total)


# ---------------------------------------------------------------- meshes

class Fetcher:
    """Reads tifxyz folders from the bucket (or a local folder) into a cache folder, once."""

    def __init__(self, cache, base=BUCKET, get=None):
        self.cache = Path(cache)
        self.base = base
        self.get = get or meshaudit._get

    def read(self, path):
        np = _np()
        import io
        if os.path.isdir(path):
            return meshaudit.read_tifxyz(path, fetch=lambda p: Path(p).read_bytes())
        key = hashlib.sha256(path.encode()).hexdigest()[:20]
        folder = self.cache / key
        arrs = []
        for a in "xyz":
            f = folder / f"{a}.tif"
            if not f.is_file():
                folder.mkdir(parents=True, exist_ok=True)
                tmp = f.with_suffix(".part")
                tmp.write_bytes(self.get(f"{self.base}/{path}/{a}.tif"))
                tmp.replace(f)
            arrs.append(meshaudit.imread_capped(io.BytesIO(f.read_bytes())).astype(np.float64))
        xyz = np.stack(arrs, -1)
        bad = (xyz == -1).any(-1) | ~np.isfinite(xyz).all(-1) | (xyz <= 0).all(-1)
        xyz[bad] = np.nan
        return xyz


def mesh_in_frame(cat, index, gid, frame, fetch):
    """(H, W, 3) vertices of segment gid in voxels of volume `frame`, and how they got there; (None, why) if no
    route exists. The catalog's own copy on that volume is used first; otherwise the native mesh through the
    catalog's sample-level matrix."""
    rec = index[gid]
    if frame in rec["meshes"]:
        # the catalog made this copy from the segment's own volume, so its route's transform error applies
        return fetch.read(rec["meshes"][frame]), {"route": "catalog copy", "from": rec["volume"] or frame}
    src = rec["volume"]
    native = rec["native"] or rec["meshes"].get(src)
    if native is None:
        return None, "no tifxyz mesh in the catalog"
    xyz = fetch.read(native)
    if src == frame:
        return xyz, {"route": "native", "from": src}
    m, how = meshaudit.sample_matrix(cat, rec["scroll"], src, frame)
    if m is None:
        return None, f"no catalog transform from {src} to {frame}"
    np = _np()
    flat = xyz.reshape(-1, 3)
    ok = np.isfinite(flat).all(1)
    out = np.full_like(flat, np.nan)
    out[ok] = meshaudit.apply_affine(m, flat[ok])
    return out.reshape(xyz.shape), {"route": "matrix", "from": src, "derivation": how}


def grid_step(xyz):
    """Median edge length of the grid, in its own units (the larger of the row and column medians)."""
    np = _np()
    steps = []
    for ax in (0, 1):
        d = np.linalg.norm(np.diff(xyz, axis=ax), axis=-1)
        d = d[np.isfinite(d)]
        if d.size:
            steps.append(float(np.median(d)))
    if not steps:
        raise AtlasError("mesh has no finite edges")
    return max(steps)


def decimate(xyz, max_points):
    """Every k-th row and column so at most max_points valid vertices remain."""
    np = _np()
    n = int(np.isfinite(xyz).all(-1).sum())
    k = max(1, int(math.ceil(math.sqrt(n / max_points)))) if n > max_points else 1
    return xyz[::k, ::k], k


class Surface:
    """A training mesh ready for offset queries: vertices, unit normals, grid step and a KD-tree."""

    def __init__(self, xyz, name=""):
        np = _np()
        self.name = name
        self.step = grid_step(xyz)
        nrm = meshaudit.grid_normals(xyz)
        ok = np.isfinite(xyz).all(-1) & np.isfinite(nrm).all(-1)
        if ok.sum() < 4:
            raise AtlasError(f"{name}: fewer than 4 vertices with a normal")
        self.points = xyz[ok]
        self.normals = nrm[ok]
        z = self.points[:, 2]
        self.zrange = (float(z.min()), float(z.max()))
        self.tree = _kdtree()(self.points)


def eval_points(xyz, max_points=MAX_EVAL_POINTS):
    np = _np()
    sub, k = decimate(xyz, max_points)
    ok = np.isfinite(sub).all(-1)
    return sub[ok], k


def offsets(points, surf, px_um, reach_um=REACH_UM, k=K_NEAREST):
    """|offset| in um along the training surface's normal for each point, inf where the surface does not cover it
    (no vertex within reach whose tangential distance is inside FOOTPRINT grid steps)."""
    np = _np()
    tau = FOOTPRINT * surf.step
    r = math.hypot(reach_um / px_um, 1.5 * surf.step)
    k = min(k, len(surf.points))
    _, idx = surf.tree.query(points, k=k, distance_upper_bound=r)
    if idx.ndim == 1:
        idx = idx[:, None]
    out = np.full(len(points), np.inf)
    n = len(surf.points)
    for j in range(idx.shape[1]):
        ok = idx[:, j] < n
        if not ok.any():
            continue
        q = surf.points[idx[ok, j]]
        nn = surf.normals[idx[ok, j]]
        v = points[ok] - q
        h = np.einsum("ij,ij->i", v, nn)
        t = np.linalg.norm(v - h[:, None] * nn, axis=1)
        hh = np.where(t <= tau, np.abs(h) * px_um, np.inf)
        out[ok] = np.minimum(out[ok], hh)
    out[out > reach_um] = np.inf
    return out


def summarize(h):
    """Shares of evaluation vertices by offset to the nearest covering training surface."""
    np = _np()
    n = int(h.size)
    if n == 0:
        return {"points": 0}
    same = h <= D_SAME_UM
    return {"points": n, "f_same": round(float(same.mean()), 5), "f_band": round(float((h <= BAND_UM).mean()), 5),
            "f_reach": round(float(np.isfinite(h).mean()), 5),
            "median_offset_um": round(float(np.median(h[same])), 2) if same.any() else None}


def call(f_same):
    if f_same is None:
        return "unknown"
    if f_same >= EXPOSED_FRAC:
        return "exposed"
    if f_same >= TRACE_FRAC:
        return "trace"
    return "clear"


def zoverlap(points, zrange):
    """Share of the evaluation mesh's z range that the training mesh's z range also spans (villa 2346's z check)."""
    lo, hi = float(points[:, 2].min()), float(points[:, 2].max())
    if hi <= lo:
        return 0.0
    return round(max(0.0, min(hi, zrange[1]) - max(lo, zrange[0])) / (hi - lo), 4)


def pair(eval_xyz, train_xyz, px_um, name=""):
    """One evaluation mesh against one training mesh, both in voxels of one volume of px_um."""
    pts, k = eval_points(eval_xyz)
    surf = Surface(train_xyz, name)
    h = offsets(pts, surf, px_um)
    out = summarize(h)
    out.update(call=call(out.get("f_same")), z_overlap=zoverlap(pts, surf.zrange), eval_stride=k,
               train_step_um=round(surf.step * px_um, 2))
    return out


# ---------------------------------------------------------------- the matrix

def _entries_for(registry, model_id):
    by = {m["id"]: m for m in registry["models"]}
    out = []
    for mid, via in chain(registry, model_id):
        for e in by[mid]["entries"]:
            out.append({**e, "model": mid, "via": via})
    return out


def _unpublished(registry, model_id):
    by = {m["id"]: m for m in registry["models"]}
    return [mid for mid, _ in chain(registry, model_id) if by[mid].get("list") == "not published"]


def build_matrix(cat, registry, fetch, models=None, scrolls=None, skip=(), log=None):
    """Every (model, evaluation segment) cell, the evaluation segments' overlaps with each other, and the settings."""
    np = _np()
    log = log or (lambda s: None)
    index, px = catalog_index(cat)
    errors = transform_errors(cat)
    model_ids = models or [m["id"] for m in registry["models"]]
    evals = evaluation_segments(index, scrolls)
    rows, cells, dups = [], [], []
    cache = {}
    for e in evals:
        rec = index[e]
        row = {"segment": e, "scroll": rec["scroll"], "suffix": rec["suffix"], "frame": rec["volume"]}
        rows.append(row)
        if skipped(e, rec, skip):
            row["status"] = "not-run"
            for mid in model_ids:
                cells.append({"model": mid, "segment": e, "status": "not-run", "why": "outside this run's scope"})
            continue
        frame = rec["volume"]
        pxu = px[rec["scroll"]].get(frame)
        xyz, how = mesh_in_frame(cat, index, e, frame, fetch)
        if xyz is None:
            row["status"] = f"no mesh: {how}"
            for mid in model_ids:
                cells.append({"model": mid, "segment": e, "status": "unknown", "why": f"evaluation mesh: {how}"})
            continue
        pts, k = eval_points(xyz)
        row.update(px_um=pxu, points=int(len(pts)), stride=k, status="run")
        log(f"{rec['scroll']} {e} {rec['suffix']}: {len(pts)} points at stride {k}")

        def offsets_to(t):
            if (e, t) in cache:
                return cache[(e, t)]
            trec = index[t]
            if skipped(t, trec, skip):
                res = (None, "outside this run's scope", None)
            else:
                txyz, thow = mesh_in_frame(cat, index, t, frame, fetch)
                if txyz is None:
                    res = (None, thow, None)
                else:
                    err = path_error(cat, errors, rec["scroll"], thow["from"], frame)
                    try:
                        surf = Surface(txyz, t)
                        res = (offsets(pts, surf, pxu), {**thow, "transform_error_um": err,
                                                         "z_overlap": zoverlap(pts, surf.zrange)}, err)
                    except AtlasError as exc:
                        res = (None, str(exc), None)
            cache[(e, t)] = res
            return res

        # the evaluation segments' overlaps with each other (one sheet scored twice)
        for o in evals:
            if o != e and index[o]["scroll"] == rec["scroll"]:
                h, info, err = offsets_to(o)
                if h is not None:
                    s = summarize(h)
                    dups.append({"segment": e, "other": o, **s, "call": call(s["f_same"]),
                                 "transform_error_um": err})
        for mid in model_ids:
            cells.append(_cell(registry, mid, e, rec, offsets_to, index))
    return {"schema": SCHEMA, "settings": settings(), "segments": rows, "cells": cells, "duplicates": dups,
            "models": [{k: m.get(k) for k in ("id", "title", "by", "weights", "label", "list", "inherits", "note")}
                       for m in registry["models"] if m["id"] in model_ids]}


def settings():
    return {"d_same_um": D_SAME_UM, "band_um": BAND_UM, "reach_um": REACH_UM, "exposed_frac": EXPOSED_FRAC,
            "trace_frac": TRACE_FRAC, "transform_flag_um": TRANSFORM_FLAG_UM,
            "transform_limit_um": TRANSFORM_LIMIT_UM, "max_eval_points": MAX_EVAL_POINTS,
            "footprint_steps": FOOTPRINT, "k_nearest": K_NEAREST}


def _cell(registry, mid, e, rec, offsets_to, index):
    np = _np()
    scroll = rec["scroll"]
    ents = _entries_for(registry, mid)
    named = [x for x in ents if x["segment"] == e]
    cell = {"model": mid, "segment": e, "flags": []}
    trained = [x for x in named if x["role"] in TRAIN_ROLES]
    if trained:
        x = trained[0]
        cell.update(status="trained", why=f"named in {x['via']}'s list as {x['name']} ({x['role']})",
                    names=[{"name": y["name"], "via": y["via"], "role": y["role"]} for y in trained])
        return cell
    sel = [x for x in named if x["role"] in ("validation",)] + \
          [x for x in ents if x["role"] == "selected" and x["scroll"] == scroll and x["segment"] == "*"]
    notes = [f"{x['via']}: {x['role']} ({x['name']})" for x in named if x["role"] in ("validation_only", "test")]
    if notes:
        cell["flags"] += notes
    # geometry over the training (and validation) segments on this scroll
    best, union, uerr = [], None, []
    for role_set, tag in ((TRAIN_ROLES, "train"), (("validation",), "validation")):
        for x in ents:
            if x["role"] not in role_set or x["scroll"] != scroll or not x["segment"] or x["segment"] == "*":
                continue
            if x["segment"] == e or x["segment"] not in index:
                continue
            h, info, err = offsets_to(x["segment"])
            if h is None:
                cell["flags"].append(f"{x['via']}: {x['name']}: {info}")
                continue
            s = summarize(h)
            best.append({"segment": x["segment"], "name": x["name"], "via": x["via"], "as": tag,
                         "f_same": s["f_same"], "f_band": s["f_band"], "transform_error_um": err,
                         "z_overlap": info.get("z_overlap") if isinstance(info, dict) else None})
            if tag == "train":
                union = h if union is None else np.minimum(union, h)
                uerr.append(err)
    best.sort(key=lambda b: -b["f_same"])
    cell["covering"] = [b for b in best if b["f_band"] > 0][:5]
    unresolved = [x for x in ents if x["role"] in TRAIN_ROLES and x["scroll"] == scroll and not x["segment"]]
    noscroll = [x for x in ents if x["role"] in TRAIN_ROLES and x["scroll"] is None and not x["segment"]]
    if unresolved:
        cell["flags"].append(f"{len(unresolved)} name(s) on {scroll} match no catalog segment: "
                             + ", ".join(sorted({x['name'] for x in unresolved})))
    if noscroll:
        cell["flags"].append(f"{len(noscroll)} name(s) with no scroll: " + ", ".join(sorted({x['name'] for x in noscroll})))
    geo = None
    if union is not None:
        geo = summarize(union)
        cell.update({k: geo[k] for k in ("f_same", "f_band", "median_offset_um")})
        errs = [x for x in uerr if x]
        worst = max(errs) if errs else 0.0
        if any(x is None for x in uerr):
            cell["flags"].append("a training mesh came through a transform with no landmark error")
        cell["transform_error_um"] = round(worst, 2)
        if worst > TRANSFORM_FLAG_UM:
            cell["flags"].append(f"winding uncertain: transform landmark error {worst:.1f} um")
    gcall = call(geo["f_same"]) if geo else None
    if geo and cell.get("transform_error_um", 0) > TRANSFORM_LIMIT_UM and gcall in ("exposed", "trace", "clear"):
        cell["flags"].append(f"geometric call {gcall} not trusted: transform error over {TRANSFORM_LIMIT_UM:g} um")
        gcall = None
    vcover = [b for b in best if b["as"] == "validation" and call(b["f_same"]) == "exposed"]
    if gcall == "exposed":
        b = next(b for b in best if b["as"] == "train")
        cell.update(status="exposed", why=f"training surfaces cover {geo['f_same']:.1%} of it within {D_SAME_UM:g} um "
                                          f"(largest: {b['name']} via {b['via']}, {b['f_same']:.1%})")
    elif sel or vcover:
        why = sel[0] if sel else None
        cell.update(status="selected", why=(f"{why['via']}: checkpoint chosen on {why['name']}" if why else
                                            f"validation segment {vcover[0]['name']} covers {vcover[0]['f_same']:.1%}"))
    elif gcall == "trace":
        cell.update(status="trace", why=f"training surfaces cover {geo['f_same']:.1%} within {D_SAME_UM:g} um")
    elif _unpublished(registry, mid):
        cell.update(status="unknown", why="training list not published: " + ", ".join(_unpublished(registry, mid)))
    elif unresolved:
        cell.update(status="unknown", why="names on this scroll that match no catalog segment")
    elif union is None and any(x["role"] in TRAIN_ROLES and x["scroll"] == scroll for x in ents):
        cell.update(status="unknown", why="its training meshes on this scroll could not be read")
    elif union is None and geo is None and cell["flags"] and any("not trusted" in f for f in cell["flags"]):
        cell.update(status="unknown", why="transform error too large to call")
    elif geo is not None and gcall is None:
        cell.update(status="unknown", why="transform error too large to call")
    elif geo is not None:
        cell.update(status="clear", why=f"training surfaces cover {geo['f_same']:.2%} within {D_SAME_UM:g} um")
    else:
        cell.update(status="clear", why=f"no training segment on {scroll} in its list")
    return cell


# ---------------------------------------------------------------- the instrument checks (planted duplicates)

def write_tifxyz(folder, xyz, extra=None):
    import tifffile
    np = _np()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    arr = np.where(np.isfinite(xyz), xyz, -1.0).astype(np.float32)
    for i, a in enumerate("xyz"):
        tifffile.imwrite(str(folder / f"{a}.tif"), arr[..., i])
    meta = {"format": "tifxyz", "type": "seg", "scale": [0.05, 0.05], **(extra or {})}
    (folder / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")


def displaced(xyz, delta_vox):
    """The mesh moved along its own unit normals by delta_vox (voxels); holes stay holes."""
    np = _np()
    n = meshaudit.grid_normals(xyz)
    return xyz + n * delta_vox


def plant_check(cat, prereg, fetch, out, log=None):
    """Run the preregistered planted-duplicate checks: (a) recall, (b) adjacent-winding control, (c) cross-scroll
    negative and (d) the real positive pair. Returns the record; nothing here reads labels."""
    np = _np()
    log = log or (lambda s: None)
    out = Path(out)
    index, px = catalog_index(cat)
    errors = transform_errors(cat)
    rng = np.random.default_rng(int(prereg["seed"]))
    exclude = set(prereg.get("exclude_segments", []))
    cands = []
    for gid, rec in sorted(index.items()):
        if rec["scroll"] in prereg["scrolls"] and not rec["labeled"] and gid not in exclude \
                and (rec["native"] or rec["meshes"].get(rec["volume"])):
            cands.append(gid)
    pick = sorted(rng.choice(len(cands), size=int(prereg["n"]), replace=False).tolist())
    chosen = [cands[i] for i in pick]
    planted = []
    used_ids = set(index)
    for i, gid in enumerate(chosen):
        rec = index[gid]
        f1 = rec["volume"]
        f2 = _second_volume(cat, rec["scroll"], f1, px)
        m12, _ = meshaudit.sample_matrix(cat, rec["scroll"], f1, f2)
        xyz1, _ = mesh_in_frame(cat, index, gid, f1, fetch)
        xyz1, _ = decimate(xyz1, prereg.get("max_mesh_points", 400_000))
        flat = xyz1.reshape(-1, 3)
        ok = np.isfinite(flat).all(1)
        c = np.full_like(flat, np.nan)
        c[ok] = meshaudit.apply_affine(m12, flat[ok])
        c = c.reshape(xyz1.shape)
        delta = float(prereg["deltas_vox"][i % len(prereg["deltas_vox"])])
        err = path_error(cat, errors, rec["scroll"], f1, f2) or 0.0
        fit = _fit_rms(cat, rec["scroll"], f1, f2)
        direction = rng.normal(size=3)
        direction /= np.linalg.norm(direction)
        jitter = direction * (fit / px[rec["scroll"]][f2])
        copy_a = displaced(c, delta) + jitter
        copy_b = displaced(c, delta + float(prereg["shift_um"]) / px[rec["scroll"]][f2]) + jitter
        while True:
            new = "".join(str(d) for d in rng.integers(0, 10, size=14))
            if new not in used_ids:
                used_ids.add(new)
                break
        for tag, arr in (("a", copy_a), ("b", copy_b)):
            write_tifxyz(out / "planted" / f"{new}-{tag}", arr, {"uuid": f"planted-{new}-{tag}", "volume": f2})
        planted.append({"source": gid, "scroll": rec["scroll"], "frame": f1, "copy_frame": f2, "id": new,
                        "delta_vox": delta, "jitter_um": round(fit, 2), "transform_error_um": round(err, 2),
                        "xyz1": xyz1})
        log(f"planted {gid} -> {new} ({rec['scroll']} {f1} -> {f2}, delta {delta} vox, jitter {fit:.1f} um)")
    res = {"schema": SCHEMA + "/plant", "prereg": prereg.get("file"), "settings": settings(), "candidates": len(cands),
           "a": [], "b": [], "c": [], "d": []}
    for p in planted:
        pxu = px[p["scroll"]][p["frame"]]
        pts, _ = eval_points(p["xyz1"])
        for tag in ("a", "b"):
            idx = {**index, p["id"]: {"scroll": p["scroll"], "suffix": "", "volume": p["copy_frame"], "meshes": {},
                                      "native": str(out / "planted" / f"{p['id']}-{tag}"), "labeled": False}}
            back, how = mesh_in_frame(cat, idx, p["id"], p["frame"], fetch)
            h = offsets(pts, Surface(back, p["id"]), pxu)
            s = summarize(h)
            res[tag].append({"source": p["source"], "copy": p["id"], "scroll": p["scroll"], "delta_vox": p["delta_vox"],
                             "jitter_um": p["jitter_um"], "transform_error_um": p["transform_error_um"], **s,
                             "call": call(s["f_same"])})
    # (c) cross-scroll: each original against a planted copy from the other scroll, read as if in this frame
    others = {}
    for p in planted:
        others.setdefault(p["scroll"], []).append(p)
    for i, p in enumerate(planted):
        pool = [q for s, qs in sorted(others.items()) if s != p["scroll"] for q in qs]
        if not pool:
            continue
        q = pool[i % len(pool)]
        raw = fetch.read(str(out / "planted" / f"{q['id']}-a"))
        pts, _ = eval_points(p["xyz1"])
        h = offsets(pts, Surface(raw, q["id"]), px[p["scroll"]][p["frame"]])
        s = summarize(h)
        res["c"].append({"source": p["source"], "scroll": p["scroll"], "other": q["source"],
                         "other_scroll": q["scroll"], **s, "call": call(s["f_same"])})
    # (d) the real positive pair, both directions
    for a, b in prereg["positive_pairs"]:
        for x, y in ((a, b), (b, a)):
            frame = index[x]["volume"]
            ex, _ = mesh_in_frame(cat, index, x, frame, fetch)
            ty, how = mesh_in_frame(cat, index, y, frame, fetch)
            err = path_error(cat, errors, index[x]["scroll"], how["from"], frame)
            r = pair(ex, ty, px[index[x]["scroll"]][frame], y)
            res["d"].append({"eval": x, "train": y, "route": how["route"], "transform_error_um": err, **r})
    res["verdict"] = verdict(res, prereg)
    return res


def _second_volume(cat, scroll, f1, px):
    """The other volume of the scroll with a sample-level matrix from f1 whose voxel size is nearest f1's."""
    opts = []
    for v, um in sorted(px[scroll].items()):
        if v != f1 and um and meshaudit.sample_matrix(cat, scroll, f1, v)[0] is not None:
            opts.append((abs(math.log(um / px[scroll][f1])), v))
    if not opts:
        raise AtlasError(f"{scroll}: no second volume with a catalog transform from {f1}")
    return min(opts)[1]


def _fit_rms(cat, scroll, a, b):
    for r in meshaudit.transforms_audit({"samples": {scroll: cat["samples"][scroll]}}):
        if {r["from_volume"], r["to_volume"]} == {a, b} and r.get("fit_rms_um") is not None:
            return float(r["fit_rms_um"])
    return 0.0


def verdict(res, prereg):
    bars = prereg["bars"]
    a_hit = sum(r["call"] == "exposed" for r in res["a"])
    b_ok = sum(r["call"] != "exposed" for r in res["b"])
    c_ok = sum(r["call"] != "exposed" for r in res["c"])
    d_ok = sum(r["call"] == "exposed" for r in res["d"])
    checks = {
        "a_recall": {"value": a_hit, "of": len(res["a"]), "bar": bars["a_min"], "pass": a_hit >= bars["a_min"]},
        "b_adjacent_clear": {"value": b_ok, "of": len(res["b"]), "bar": bars["b_min"], "pass": b_ok >= bars["b_min"]},
        "c_cross_scroll": {"value": c_ok, "of": len(res["c"]), "bar": bars["c_min"], "pass": c_ok >= bars["c_min"]},
        "d_real_positive": {"value": d_ok, "of": len(res["d"]), "bar": len(res["d"]),
                            "pass": d_ok == len(res["d"]) and len(res["d"]) > 0},
    }
    return {"checks": checks, "pass": all(c["pass"] for c in checks.values())}


# ---------------------------------------------------------------- text

def format_matrix(m):
    ids = [x["id"] for x in m["models"]]
    by = {(c["model"], c["segment"]): c for c in m["cells"]}
    lines = ["Exposure Atlas (Model output of mesh geometry; training lists as each model's source says)",
             f"same sheet: within {m['settings']['d_same_um']:g} um along the normal; exposed at "
             f"{m['settings']['exposed_frac']:.0%} of the evaluation vertices or more",
             "codes: T trained (named)  E exposed  t trace  S selected  . clear  ? unknown  - not run", ""]
    w = max(len(i) for i in ids)
    lines.append("segment".ljust(42) + " ".join(i[:w].rjust(w) for i in ids))
    for r in m["segments"]:
        name = f"{r['scroll']} {r['suffix'] or r['segment']}"[:41].ljust(42)
        cells = []
        for i in ids:
            c = by.get((i, r["segment"]), {})
            code = CODES.get(c.get("status"), " ")
            if c.get("status") in ("exposed", "trace") and c.get("f_same") is not None:
                code = f"{code}{round(100 * c['f_same'])}"
            cells.append(code.rjust(w))
        lines.append(name + " ".join(cells))
    flagged = [c for c in m["cells"] if c.get("flags") and c["status"] != "not-run"]
    if flagged:
        lines += ["", "Flags:"]
        for c in flagged:
            lines.append(f"  {c['model']} on {c['segment']}: " + "; ".join(c["flags"]))
    if m.get("duplicates"):
        hits = [d for d in m["duplicates"] if d["call"] in ("exposed", "trace")]
        lines += ["", f"Evaluation segments on one sheet (of {len(m['duplicates'])} same-scroll pairs, "
                      f"{len(hits)} at trace or more):"]
        for d in hits:
            lines.append(f"  {d['segment']} on {d['other']}: {d['call']} {d['f_same']:.1%}")
    return "\n".join(lines)


def format_plant(res):
    lines = ["Exposure Atlas instrument checks (planted duplicates)"]
    for k, c in res["verdict"]["checks"].items():
        lines.append(f"  {k}: {c['value']} of {c['of']} (bar {c['bar']}) {'PASS' if c['pass'] else 'FAIL'}")
    fa = sorted(r["f_same"] for r in res["a"])
    fb = sorted(r["f_same"] for r in res["b"])
    fc = sorted(r["f_same"] for r in res["c"])
    if fa:
        lines.append(f"  (a) f_same min {fa[0]:.3f} median {fa[len(fa) // 2]:.3f}")
    if fb:
        lines.append(f"  (b) f_same max {fb[-1]:.3f}")
    if fc:
        lines.append(f"  (c) f_same max {fc[-1]:.3f}")
    for r in res["d"]:
        lines.append(f"  (d) {r['eval']} on {r['train']}: {r['call']} f_same {r['f_same']:.3f} ({r['route']})")
    lines.append("Instrument: " + ("PASS" if res["verdict"]["pass"] else "FAIL"))
    return "\n".join(lines)


def format_models(reg):
    lines = []
    for m in reg["models"]:
        n = len(m["entries"])
        res = sum(1 for e in m["entries"] if e["segment"])
        inh = f", inherits {', '.join(m['inherits'])}" if m.get("inherits") else ""
        lines.append(f"{m['id']}: {m['title']} by {m['by']}; list {m['list']}; {n} entries, {res} resolved to "
                     f"catalog segments{inh} ({m['label']})")
    return "\n".join(lines)


# ---------------------------------------------------------------- command line

def build_parser(p):
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("models", help="every model and how its training list was resolved")
    s.add_argument("--registry", default=str(REGISTRY))
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("segments", help="the labeled evaluation segments in the catalog")
    s.add_argument("--catalog", help="metadata.json path or URL (default: the bucket's)")
    s.add_argument("--scroll", action="append")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("pair", help="one evaluation mesh against one training mesh (catalog ids or tifxyz folders)")
    s.add_argument("eval")
    s.add_argument("train")
    s.add_argument("--frame", help="volume id of the frame (default: the evaluation segment's own volume)")
    s.add_argument("--px-um", type=float, help="voxel size of the frame, for two local folders")
    s.add_argument("--catalog")
    s.add_argument("--cache", default="work/expatlas/cache")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("matrix", help="every model against every labeled evaluation segment")
    s.add_argument("--out", required=True, help="folder for matrix.json and matrix.txt")
    s.add_argument("--catalog")
    s.add_argument("--registry", default=str(REGISTRY))
    s.add_argument("--scroll", action="append", help="only this scroll's evaluation segments (repeatable)")
    s.add_argument("--model", action="append", help="only this model (repeatable)")
    s.add_argument("--skip", help="file of SCROLL/GLOB patterns: segments never read, their cells not-run")
    s.add_argument("--cache", default="work/expatlas/cache")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("plant", help="the preregistered instrument checks on planted duplicates")
    s.add_argument("--prereg", required=True, help="JSON block of the preregistration (see the tool page)")
    s.add_argument("--out", required=True)
    s.add_argument("--catalog")
    s.add_argument("--cache", default="work/expatlas/cache")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("show", help="print a matrix.json written earlier")
    s.add_argument("matrix")
    s.add_argument("--json", action="store_true")


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def cmd_expatlas(args):
    try:
        return _run(args)
    except (AtlasError, KeyError, ValueError) as exc:
        print(f"kit expatlas: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"kit expatlas could not read or write: {exc}", file=sys.stderr)
        return 2


def _catalog(args):
    return meshaudit.load_catalogue(getattr(args, "catalog", None))


def _run(args):
    if args.action == "models":
        reg = load_registry(args.registry)
        print(json.dumps(reg, indent=1) if args.json else format_models(reg))
        return 0
    if args.action == "show":
        m = json.loads(Path(args.matrix).read_text())
        print(json.dumps(m, indent=1) if args.json else format_matrix(m))
        return 0
    cat = _catalog(args)
    if args.action == "segments":
        index, px = catalog_index(cat)
        rows = [{"segment": g, "scroll": index[g]["scroll"], "suffix": index[g]["suffix"],
                 "volume": index[g]["volume"], "frames": sorted(index[g]["meshes"])}
                for g in evaluation_segments(index, args.scroll)]
        print(json.dumps(rows, indent=1) if args.json else
              "\n".join(f"{r['scroll']} {r['segment']} {r['suffix']} (traced on {r['volume']}; "
                        f"{len(r['frames'])} frames)" for r in rows))
        return 0
    fetch = Fetcher(args.cache)
    if args.action == "pair":
        index, px = catalog_index(cat)
        if os.path.isdir(args.eval) and os.path.isdir(args.train):
            if not args.px_um:
                raise AtlasError("two local folders need --px-um")
            r = pair(fetch.read(args.eval), fetch.read(args.train), args.px_um, args.train)
        else:
            frame = args.frame or index[args.eval]["volume"]
            ex, _ = mesh_in_frame(cat, index, args.eval, frame, fetch)
            tx, how = mesh_in_frame(cat, index, args.train, frame, fetch)
            if ex is None or tx is None:
                raise AtlasError(f"no mesh in frame {frame}: {_ if ex is None else how}")
            r = pair(ex, tx, px[index[args.eval]["scroll"]][frame], args.train)
            r["route"] = how
            r["transform_error_um"] = path_error(cat, transform_errors(cat), index[args.eval]["scroll"],
                                                 how["from"], frame)
        print(json.dumps(r, indent=1) if args.json else
              f"{args.eval} on {args.train}: {r['call']}, {r['f_same']:.1%} within {D_SAME_UM:g} um, "
              f"{r['f_band']:.1%} within {BAND_UM:g} um, z overlap {r['z_overlap']:.0%}")
        return 0
    if args.action == "matrix":
        reg = load_registry(args.registry)
        m = build_matrix(cat, reg, fetch, models=args.model, scrolls=args.scroll, skip=read_skip(args.skip),
                         log=_log)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "matrix.json").write_text(json.dumps(m, indent=1) + "\n")
        (out / "matrix.txt").write_text(format_matrix(m) + "\n")
        print(json.dumps(m, indent=1) if args.json else format_matrix(m))
        return 0
    if args.action == "plant":
        text = Path(args.prereg).read_text()
        block = re.search(r"```json\n(.*?)\n```", text, re.S)
        prereg = json.loads(block.group(1) if block else text)
        prereg["file"] = args.prereg
        res = plant_check(cat, prereg, fetch, args.out, log=_log)
        Path(args.out, "plant.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps(res, indent=1) if args.json else format_plant(res))
        return 0 if res["verdict"]["pass"] else 3
    raise AtlasError(f"unknown action {args.action}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit expatlas", description=__doc__.split("\n\n")[0])
    build_parser(p)
    args = p.parse_args(argv)
    return cmd_expatlas(args)


if __name__ == "__main__":
    sys.exit(main())
