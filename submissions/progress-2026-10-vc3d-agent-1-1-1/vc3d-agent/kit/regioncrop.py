"""Region crop: keep the clean parts of a traced surface instead of accepting or rejecting it whole.

  kit meshqa crop SURFACE OUT      cut three kinds of evidence out of a tifxyz grid and write every connected piece
                                   left above a minimum area as its own tifxyz folder in VC3D's layout.
  AutoPipeline qa.crop             the same cut on a trace qa rejects (a module of AutoPipeline, Run.crop_one); each piece
                                   is checked again by the same qa rule and joins the run as its own surface.

AutoPipeline's qa (a module of AutoPipeline, Run.qa_one) accepts or rejects a trace whole: one transverse self-crossing, or
one seating window that is not seated, and the whole trace is gone, however much of it is clean. Here the
evidence is cut out locally and the rest is kept:

  - transverse self-crossings: both quads of every contact villa's vc_tifxyz_selfcross reports under either
    triangulation, grown by `dilate` cells in the 8-neighbourhood (every vertex of the trace is a candidate for
    the cut);
  - seating: the grid footprint of every seating window whose verdict is in `seating.fail`. Windows come from
    AutoPipeline's check_surface (their window_xywh converted to grid rows and columns by footprint), from a JSON
    list of {"rows", "cols", "verdict"}, or are measured here on a tiling of the grid (seating_grid: kit vc3d_seat's
    score on a stack sampled from the CT along the normals, so no VC3D build is needed);
  - off-sheet growth: 4-connected blobs of at least `off_sheet.min_cells` vertices that kit switchfix's prediction
    profile puts on no sheet (class off_sheet; isolated misses of the prediction are not cut). The same detector's
    jump edges (a normal offset over 7 voxels, or a change of the sheet under the vertices) separate pieces when
    `regions.use_jumps` is on.

Every 4-connected piece of the vertices left (across no cut edge) whose area is at least `regions.min_area_cm2` is
kept. Areas are VC3D's (switchfix.surface_area_vx2) in coordinate units squared, turned into cm2 with the size of
one coordinate unit (coordinate_unit_um): the voxel size given, times villa's original_volume_downscale when the
surface's meta.json says its coordinates are in a downscaled frame (villa #2112's key, read as VC3D's
OpenDataSegmentCache does), or meta.json's top-level voxel_size_um (the current voxel size villa #2175 writes).
Without either, cm2 is refused rather than guessed (an area quoted in the wrong unit was villa #2072's lesson).

Each kept piece is written as <OUT>/<name>-rNN[.tifxyz]: x.tif, y.tif, z.tif as float32 cropped to the piece's
bounding box with (-1, -1, -1) elsewhere (VC3D's invalid sentinel), generations.tif cropped when the source has one,
and meta.json with format, type, scale (unchanged: a crop never resamples), a recomputed bbox, area_vx2 and
area_cm2, voxel_size_um at the top level, a new uuid and name = the folder name (villa #2178: a derived surface keeps
coordinate provenance but not catalog identity, so vc_open_data_representation is dropped and no
catalog-origin.json is copied), and a "kit_regioncrop" record of where it came from. Every other meta key is kept.
VC3D and villa's patch tools (vc_grow_seg_from_segments, vc_tifxyz_selfcross, vc_render_tifxyz) read the folders
as they read any tifxyz. Folders are staged beside OUT and renamed into place.

Two more outputs hand the pieces to the community's tools (21 Oct 2026):

  --spiral-patches DIR   each kept piece as a patch folder villa's spiral fitting loads from a dataset's
                         verified_patches directory (fit_session.py FitInputSpec "verified_patches", conventional
                         folder verified_patches): DIR/<uuid>/ with x.tif, y.tif, z.tif and meta.json (scale and uuid
                         are what spiral-fitting/tifxyz.py load_tifxyz reads). Named by uuid, as villa's patch
                         entries are (Config.patch_uuid_filter_regex matches those names). Nothing else is written
                         into DIR, because villa tries to load every entry there. A piece villa would drop (no valid
                         quad after its erosion, spiral_helpers.erode_patch_valid_region: Config.patch_erode_patches,
                         1 cell, unless meta.json's spiral_patch_erode_cells overrides it, which the source's meta
                         carries into every patch and the check uses too) is not written and is listed in the
                         record. Each uuid is uuid5 of the source (its uuid, else its real path), the piece's index
                         and params_digest, so a rerun names the same pieces the same way. Because villa loads every
                         entry, a rerun into a DIR that already holds patches cut from the same source is refused;
                         with --overwrite those entries are all replaced (stale ones removed), so no piece is ever
                         loaded twice. Entries not written by this tool are never touched. Pass
                         <dataset>/verified_patches.
  --vc3d-points FILE     a VC3D point collection file (version 1, PointCollections.cpp; kit/villafmt.py reads it
                         back): one collection per kept piece, its interior anchor vertex first and then up to
                         --max-points of its outline, and one collection "<name>-cuts" at the crossings and jump
                         edges that separate the pieces. Points are the surface's own (x, y, z) volume coordinates.

Both formats follow the villa source at ChaseHendrick/villa 4eecd08f (spiral-fitting/tifxyz.py, spiral_helpers.py,
fit_session.py, config.py; read 21 Oct 2026); villa's loader itself needs torch, which a test of AutoPipeline
runs only when VILLA_SPIRAL_FITTING names a spiral-fitting tree that imports.

The whole-trace arms are kept beside it: `selfcross.per_cm2` is a tolerance on transverse crossings per cm2 of the
whole trace, calibrated on published meshes (a note of the source repository) instead of qa's 0.

A kept piece is a place where these checks found nothing, not a verified sheet and never a reading. No tracer is
changed here: this module reads a finished tifxyz and writes new ones beside it.
"""

import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import uuid as _uuid
from pathlib import Path

PARAMS = {
    "version": 1,
    # Frozen 21 Oct 2026 from development data only (a note of the source repository; Model output):
    # per_cm2 is the largest crossing rate of the 11 development references rounded up to a multiple of 5 (w032,
    # 63.5 per cm2). Of 60 settings swept offline, the one the rule fixed before the sweep picked cuts crossings
    # (dilated 2 cells) and rejects a piece more than 0.30 off the sheet; seating tiles (fail []) and off-sheet
    # blob cuts (min_cells null) are measured on request but cut nothing, because on published windings they
    # cut clean surface (seating tiles on w031 and w032, m7 blobs on w027, w031, w032 and PHerc0841 w00).
    "selfcross": {"dilate": 2, "per_cm2": 65.0},
    "seating": {"fail": [], "window_cells": 10, "step_vox": 2.0, "min_quads": 0.25},
    "off_sheet": {"min_cells": None},
    # max_off_share: a piece whose share of off-sheet vertices is over this is rejected whole (null: no test)
    "regions": {"connectivity": 4, "min_area_cm2": 0.05, "use_jumps": True, "max_off_share": 0.30},
}
OPEN_DATA_DOWNSCALE_KEYS = ("vc_open_data_original_volume_downscale", "original_volume_downscale",
                            "originalVolumeDownscale", "volume_downscale", "volumeDownscale")
DROP_META = ("uuid", "name", "bbox", "area_vx2", "area_cm2", "vc_open_data_representation", "kit_regioncrop")


class CropError(ValueError):
    """A problem the caller can fix: an unreadable surface, a missing measurement, an unknown voxel size."""


def _np():
    try:
        import numpy as np
    except ImportError as exc:      # pragma: no cover - numpy is a stated dependency of the map tools
        raise CropError("kit meshqa crop needs numpy") from exc
    return np


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def params_digest(params=None):
    return hashlib.sha256(canonical(params or PARAMS).encode()).hexdigest()


def merged(params=None, **over):
    """PARAMS with `params` (a nested dict of the same shape) merged over it, then the keyword overrides given as
    section__key=value (None leaves a value as it is)."""
    out = json.loads(json.dumps(PARAMS))
    for sec, vals in (params or {}).items():
        if isinstance(vals, dict) and isinstance(out.get(sec), dict):
            out[sec].update(vals)
        else:
            out[sec] = vals
    for k, v in over.items():
        if v is None:
            continue
        sec, key = k.split("__", 1)
        out[sec][key] = v
    check_params(out)
    return out


def check_params(p):
    sc, st, off, rg = p["selfcross"], p["seating"], p["off_sheet"], p["regions"]
    if not (isinstance(sc["dilate"], int) and not isinstance(sc["dilate"], bool) and sc["dilate"] >= 0):
        raise CropError("selfcross.dilate is a whole number of cells, 0 or more")
    if sc["per_cm2"] is not None and not (isinstance(sc["per_cm2"], (int, float)) and sc["per_cm2"] >= 0):
        raise CropError("selfcross.per_cm2 is a rate, 0 or more, or null")
    if off["min_cells"] is not None and not (isinstance(off["min_cells"], int) and off["min_cells"] >= 1):
        raise CropError("off_sheet.min_cells is a whole number of vertices, 1 or more, or null (no blob cut)")
    mo = rg.get("max_off_share")
    if mo is not None and not (isinstance(mo, (int, float)) and 0 <= mo <= 1):
        raise CropError("regions.max_off_share is a share from 0 to 1, or null")
    if not (isinstance(rg["min_area_cm2"], (int, float)) and rg["min_area_cm2"] >= 0):
        raise CropError("regions.min_area_cm2 is an area in cm2, 0 or more")
    if rg["connectivity"] != 4:
        raise CropError("regions.connectivity: only 4 (the grid's edges) is supported")
    if not (isinstance(st["window_cells"], int) and st["window_cells"] >= 2):
        raise CropError("seating.window_cells is a whole number of cells, 2 or more")
    if not set(st["fail"]) <= {"not seated", "unclear"}:
        raise CropError("seating.fail lists verdicts from 'not seated' and 'unclear'")


# ---------------------------------------------------------------- reading

def read(path):
    """(xyz (H, W, 3) float64, valid (H, W) as VC3D's loader keeps it, meta, generations or None) of a tifxyz."""
    from . import meshqa
    np = _np()
    p = Path(path)
    if not meshqa.is_tifxyz_dir(p):
        raise CropError(f"{p}: not a tifxyz folder (x.tif, y.tif, z.tif)")
    try:
        patch = meshqa.load_patch(p)
    except meshqa.MeshQAError as exc:
        raise CropError(str(exc)) from exc
    if patch.read_errors or not patch.shapes_agree:
        raise CropError(f"{p}: unreadable or mismatched grids: {patch.read_errors or 'x, y, z shapes differ'}")
    xyz = np.stack([np.asarray(patch.x, np.float64), np.asarray(patch.y, np.float64),
                    np.asarray(patch.z, np.float64)], axis=-1)
    valid = np.asarray(patch.valid, bool) & np.isfinite(xyz).all(-1)
    gens = None
    gp = p / "generations.tif"
    if gp.is_file():
        try:
            g = np.asarray(meshqa.read_tiff_page(gp), dtype=np.float64)
            if g.ndim == 3:
                g = g[0]
            if g.shape == valid.shape:
                gens = np.rint(g).astype(np.int64)
        except Exception:  # noqa: BLE001 - generations are optional provenance; an unreadable file is left out
            gens = None
    return xyz, valid, dict(patch.meta or {}), gens


def coordinate_unit_um(meta, voxel_um=None):
    """(micrometres per coordinate unit, how) for a surface: the voxel size given (that of the volume the
    coordinates refer to before any downscale), times villa's original_volume_downscale when meta.json says the
    coordinates sit in a downscaled frame and VC3D has not scaled them back
    (vc_open_data_coordinates_scaled_to_original_volume); else meta.json's top-level voxel_size_um (villa #2175:
    the current voxel size, already in the coordinates' frame) or fit_config.voxel_size_um. (None, why) when none."""
    meta = meta or {}
    down = 1.0
    for k in OPEN_DATA_DOWNSCALE_KEYS:
        v = meta.get(k)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and v > 0:
            down = v
            break
    scaled = meta.get("vc_open_data_coordinates_scaled_to_original_volume")
    try:
        scaled = float(scaled) if scaled is not None else None
    except (TypeError, ValueError):
        scaled = None
    factor = 1.0 if (down == 1.0 or (scaled is not None and abs(scaled - down) < 1e-9)) else down
    if voxel_um is not None:
        v = float(voxel_um)
        if not (math.isfinite(v) and v > 0):
            raise CropError("the voxel size is a positive number of micrometres")
        how = f"voxel size {v:g} um given" + (f", times original_volume_downscale {factor:g}" if factor != 1 else "")
        return v * factor, how
    for src, val in (("meta.json voxel_size_um", meta.get("voxel_size_um")),
                     ("meta.json fit_config.voxel_size_um", (meta.get("fit_config") or {}).get("voxel_size_um"))):
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if math.isfinite(val) and val > 0:
            return val, src
    return None, "no voxel size: pass --voxel-um (meta.json has no voxel_size_um)"


def area_vx2(xyz, mask):
    from . import switchfix
    np = _np()
    return switchfix.surface_area_vx2(np.where(mask[..., None], xyz, -1.0))


# ---------------------------------------------------------------- evidence

def _count(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CropError(f"self-crossing report: the {field} must be a nonnegative integer")
    return int(value)


def parse_selfcross(sc, shape=None):
    """{"transverse", "contacts"} of a vc_tifxyz_selfcross report (villa's JSON: census rows for diagonals 0 and 1,
    each with transverse and, when located, transverse_contacts [{quad1: [row, col], quad2: [row, col]}]); contacts
    is None for a report that gives counts only. An absent or inconsistent census never means zero crossings."""
    census = sc.get("census") if isinstance(sc, dict) else None
    if not isinstance(census, list) or not census:
        raise CropError("self-crossing report: no nonempty census")
    diagonals = [row.get("diagonal") if isinstance(row, dict) else None for row in census]
    if len(diagonals) != 2 or any(type(d) is not int for d in diagonals) or set(diagonals) != {0, 1}:
        raise CropError("self-crossing report: the census must measure diagonal 0 and diagonal 1 exactly once")
    total, contacts, located = 0, [], True
    for row in census:
        n = _count(row.get("transverse"), "transverse count")
        total += n
        if "transverse_contacts" not in row:
            located = False
            continue
        entries = row["transverse_contacts"]
        if not isinstance(entries, list) or len(entries) != n:
            raise CropError("self-crossing report: the contact list does not match its transverse count")
        for e in entries:
            quads = [e.get(k) if isinstance(e, dict) else None for k in ("quad1", "quad2")]
            if any(not isinstance(q, (list, tuple)) or len(q) != 2 for q in quads):
                raise CropError("self-crossing report: each contact needs two quads of a row and a column")
            contacts.append([_count(v, "quad coordinate") for q in quads for v in q])
    if shape is not None:
        for r1, c1, r2, c2 in contacts:
            if max(r1, r2) >= shape[0] - 1 or max(c1, c2) >= shape[1] - 1:
                raise CropError("self-crossing report: a contact lies outside the surface's quad grid")
    return {"transverse": total, "contacts": contacts if located else None}


def selfcross_report(surface, tools, threads=2, timeout=3600):
    """Run villa's vc_tifxyz_selfcross on a tifxyz (kit.vc3d tools: VC_BIN or PATH) and parse its report."""
    import subprocess
    if tools is None or not tools.has("vc_tifxyz_selfcross"):
        raise CropError("vc_tifxyz_selfcross not found (set VC_BIN to a villa build's bin): crossings cannot be "
                        "measured")
    with tempfile.TemporaryDirectory() as tmp:
        rep = Path(tmp) / "selfcross.json"
        try:
            subprocess.run([str(a) for a in tools.argv("vc_tifxyz_selfcross", "--surface", surface, "-o", rep,
                                                        "--threads", threads)],
                           capture_output=True, text=True, timeout=timeout, check=False)
            sc = json.loads(rep.read_text())
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise CropError(f"vc_tifxyz_selfcross failed on {surface}: {exc}") from exc
    return parse_selfcross(sc)


def load_selfcross(report, shape=None):
    """parse_selfcross of a vc_tifxyz_selfcross report (a path or the parsed JSON); the contacts must be located
    (villa's report lists transverse_contacts), or nothing can be cut."""
    sc = json.loads(Path(report).read_text()) if isinstance(report, (str, os.PathLike)) else report
    rep = parse_selfcross(sc, shape)
    if rep["contacts"] is None:
        raise CropError("the self-crossing report gives counts only (no transverse_contacts): nothing can be cut "
                        "locally; rerun villa's vc_tifxyz_selfcross, which lists them")
    return rep


def selfcross_mask(contacts, valid, dilate):
    """The vertices to cut for crossings: the corners of both quads of every contact, grown by `dilate` cells in
    the 8-neighbourhood, within `valid`."""
    np = _np()
    from scipy import ndimage
    mark = np.zeros(valid.shape, bool)
    H, W = valid.shape
    for r1, c1, r2, c2 in contacts or []:
        for r, c in ((r1, c1), (r2, c2)):
            mark[max(0, r):min(H, r + 2), max(0, c):min(W, c + 2)] = True
    mark &= valid
    if dilate > 0 and mark.any():
        mark = ndimage.binary_dilation(mark, structure=np.ones((3, 3), bool), iterations=int(dilate))
    return mark & valid


def footprint(window_xywh, scale, level=0, scale_segmentation=1.0):
    """The grid rows and columns, [r0, r1) and [c0, c1), a check_surface seating window covers: its crop is in output
    pixels, a grid vertex (row, col) sitting at pixel (col / sx, row / sy) x scale_segmentation / 2^level."""
    x0, y0, w, h = (float(v) for v in window_xywh)
    sx, sy = (float(v) for v in (scale or [1.0, 1.0])[:2])
    f = float(scale_segmentation) / (2 ** int(level))
    return ([int(math.floor(y0 * sy / f)), int(math.ceil((y0 + h) * sy / f)) + 1],
            [int(math.floor(x0 * sx / f)), int(math.ceil((x0 + w) * sx / f)) + 1])


def windows_from_check(seating, meta):
    """check_surface's seating record (its windows, or failing that its central candidate) as grid windows
    {"rows", "cols", "verdict", ...} through footprint."""
    from . import vc3d_seat
    out = []
    wins = seating.get("windows") or (seating.get("candidates") or [])[:1]
    for w in wins:
        if not w.get("window_xywh"):
            continue
        rows, cols = footprint(w["window_xywh"], (meta or {}).get("scale"), seating.get("level", 0),
                                       w.get("scale_segmentation", seating.get("scale_segmentation", 1.0)))
        out.append({"rows": rows, "cols": cols, "verdict": w.get("verdict") or vc3d_seat.verdict(w),
                    **{k: w.get(k) for k in ("contrast", "coverage", "score", "exit") if k in w}})
    return out


def load_windows(path_or_list, meta=None):
    """Seating windows from a JSON file or list: grid windows ({"rows", "cols", "verdict"}) as they are, or a
    check_surface seating record ({"windows": [{"window_xywh", ...}]}) converted."""
    w = json.loads(Path(path_or_list).read_text()) if isinstance(path_or_list, (str, os.PathLike)) else path_or_list
    if isinstance(w, dict) and ("windows" in w or "candidates" in w):
        if all("rows" in x for x in w.get("windows") or [{}]):
            w = w.get("windows")
        else:
            return windows_from_check(w, meta)
    if not isinstance(w, list):
        raise CropError("seating windows: a list of {rows, cols, verdict} or a check_surface seating record")
    for x in w:
        if not (isinstance(x, dict) and len(x.get("rows") or []) == 2 and len(x.get("cols") or []) == 2
                and x.get("verdict") in ("seated", "not seated", "unclear", "unmeasured")):
            raise CropError("each seating window needs rows [r0, r1), cols [c0, c1) and a verdict")
    return w


def seating_mask(windows, valid, fail):
    """The vertices inside the grid footprint (rows [r0, r1), cols [c0, c1)) of every window whose verdict is in
    `fail`, within `valid`."""
    np = _np()
    mark = np.zeros(valid.shape, bool)
    for w in windows or []:
        if w.get("verdict") in set(fail) and w.get("rows") and w.get("cols"):
            r0, r1 = (max(0, int(v)) for v in w["rows"])
            c0, c1 = (max(0, int(v)) for v in w["cols"])
            mark[r0:r1, c0:c1] = True
    return mark & valid


def seating_grid(xyz, valid, sampler, voxel_um=None, window_cells=10, step_vox=2.0, half_layers=None,
                 min_quads=0.25, material=None):
    """Seating windows on a tiling of the grid in blocks of window_cells quads. Each block is sampled on a regular
    grid of about step_vox voxels along the surface (bilinear in the quad), at integer offsets -half..half along the
    bilinear unit normal, nearest voxel of `sampler` (a switchfix.ChunkSampler over the CT), and scored by kit
    vc3d_seat.seating and .verdict, the score AutoPipeline's check_surface gives a VC3D render. half defaults to
    check_surface's choice, ceil(280 um / voxel), from 3 to 200 layers. A block with under min_quads of its quads
    valid is "unmeasured" and never cut. Deviation from check_surface: nearest-voxel samples of the level-0 volume,
    not VC3D's trilinear render, and windows on a tiling instead of 1 to 9 window centres."""
    from . import surfbench, vc3d_seat
    np = _np()
    material = vc3d_seat.MATERIAL if material is None else material
    normals, _, ok, step = surfbench.grid_geometry(xyz, valid)
    half = int(half_layers or (min(200, max(3, math.ceil(280.0 / voxel_um))) if voxel_um else 30))
    sub = max(1, int(round((step if math.isfinite(step) else 20.0) / float(step_vox))))
    H, W = valid.shape
    offs = np.arange(-half, half + 1, dtype=np.float64)
    nrm = np.where(ok[..., None], normals, 0.0)
    t = (np.arange(sub) + 0.5) / sub
    out = []
    for r0 in range(0, H - 1, window_cells):
        for c0 in range(0, W - 1, window_cells):
            r1, c1 = min(r0 + window_cells, H - 1), min(c0 + window_cells, W - 1)
            q = ok[r0:r1, c0:c1] & ok[r0 + 1:r1 + 1, c0:c1] & ok[r0:r1, c0 + 1:c1 + 1] & ok[r0 + 1:r1 + 1, c0 + 1:c1 + 1]
            win = {"rows": [r0, r1 + 1], "cols": [c0, c1 + 1], "quads_valid": round(float(q.mean()), 4)}
            if q.mean() < min_quads:
                out.append({**win, "verdict": "unmeasured", "why": f"under {min_quads} of the quads valid"})
                continue

            def bil(a):
                a00, a01 = a[r0:r1, c0:c1], a[r0:r1, c0 + 1:c1 + 1]
                a10, a11 = a[r0 + 1:r1 + 1, c0:c1], a[r0 + 1:r1 + 1, c0 + 1:c1 + 1]
                v, u = t[:, None, None, None, None], t[None, :, None, None, None]
                # (sub_v, sub_u, rows, cols, 3) -> (rows * sub_v, cols * sub_u, 3)
                b = (a00 * (1 - v) * (1 - u) + a01 * (1 - v) * u + a10 * v * (1 - u) + a11 * v * u)
                return b.transpose(2, 0, 3, 1, 4).reshape((r1 - r0) * sub, (c1 - c0) * sub, 3)

            P, N = bil(np.where(valid[..., None], xyz, 0.0)), bil(nrm)
            Nn = np.linalg.norm(N, axis=-1)
            pix = np.repeat(np.repeat(q, sub, axis=0), sub, axis=1) & (Nn > 1e-6)
            N = N / np.where(Nn > 1e-6, Nn, 1.0)[..., None]
            pts, dirs = P[pix], N[pix]
            samp = pts[None, :, :] + offs[:, None, None] * dirs[None, :, :]
            vals = sampler.values(np.rint(samp[..., ::-1]).reshape(-1, 3)).reshape(len(offs), -1)
            stack = np.zeros((len(offs),) + pix.shape, np.uint8)
            stack[:, pix] = np.clip(vals, 0, 255).astype(np.uint8)
            res = vc3d_seat.seating(stack.shape, stack, material=material)
            out.append({**win, "verdict": vc3d_seat.verdict(res),
                        **{k: res.get(k) for k in ("contrast", "coverage", "score", "gap", "valid_pixels")}})
    return out


def offsheet(xyz, valid, sampler, min_cells):
    """(off-sheet blobs of at least min_cells vertices (none when min_cells is None), horizontal and vertical jump
    edges, detector summary, every off-sheet vertex) from kit switchfix's detector on the prediction `sampler`
    (None: no prediction read, nothing cut, jumps only)."""
    from . import switchfix
    np = _np()
    summary, arr = switchfix.detect(xyz, valid, sampler)
    cls = arr["cls"]
    mark = np.zeros_like(valid)
    blobs = []
    off_all = (cls == switchfix.OFF) if sampler is not None else None
    if sampler is not None and min_cells is not None:
        lab, n = switchfix._components(cls == switchfix.OFF)
        if n:
            sizes = np.bincount(lab[lab >= 0], minlength=n)
            big = sizes >= int(min_cells)
            mark = (lab >= 0) & big[np.maximum(lab, 0)]
            blobs = sorted((int(s) for s in sizes[big]), reverse=True)
    keep = ("vertices", "classes", "class_shares", "median_thickness_vox", "median_neighbour_step_vox",
            "jump_edges", "sheet_jump_edges", "params_digest")
    return mark, arr["cut_h"], arr["cut_v"], {**{k: summary.get(k) for k in keep}, "cut_blobs": len(blobs),
                                              "cut_blob_vertices": int(mark.sum())}, off_all


# ---------------------------------------------------------------- the cut

def cut_regions(xyz, valid, *, contacts=None, windows=None, offsheet_mask=None, cut_h=None, cut_v=None,
                unit_um=None, params=None, extra_mask=None, off_vertices=None):
    """The region crop on arrays. contacts: located transverse contacts [[r1, c1, r2, c2], ...] (None: crossings
    not measured, nothing cut for them); windows: grid seating windows (None: not measured); offsheet_mask and the
    jump edges from offsheet(); extra_mask: any other vertices to cut (another tool's flags, such as TIFXYZ
    Doctor's cells, so that its cut is kept by the same piece rule); off_vertices: every off-sheet vertex, for
    regions.max_off_share (a piece mostly off the sheet is rejected whole). Returns (record, arrays): arrays holds cut
    (H, W), labels (H, W; -1 outside every kept piece) and the masks by reason."""
    from . import switchfix
    np = _np()
    P = params or PARAMS
    if unit_um is None and P["regions"]["min_area_cm2"] > 0:
        raise CropError("regions.min_area_cm2 needs the size of a coordinate unit (the voxel size)")
    zeros = np.zeros_like(valid)
    sc = selfcross_mask(contacts, valid, P["selfcross"]["dilate"]) if contacts else zeros.copy()
    st = seating_mask(windows, valid, P["seating"]["fail"]) if windows else zeros.copy()
    of = (offsheet_mask & valid) if offsheet_mask is not None else zeros.copy()
    ex = (extra_mask & valid) if extra_mask is not None else zeros.copy()
    cut = sc | st | of | ex
    good = valid & ~cut
    if P["regions"]["use_jumps"] and cut_h is not None:
        lab, n = switchfix._components(good, cut_h, cut_v)
    else:
        lab, n = switchfix._components(good)
    total = area_vx2(xyz, valid)
    k2cm = (unit_um * 1e-4) ** 2 if unit_um else None
    least_vx2 = P["regions"]["min_area_cm2"] / k2cm if k2cm else 0.0
    labels = np.full(valid.shape, -1, np.int32)
    kept, dropped = [], {"pieces": 0, "vertices": 0, "area_vx2": 0.0}
    off_dropped = {"pieces": 0, "vertices": 0, "area_vx2": 0.0}
    max_off = P["regions"].get("max_off_share")
    order = []
    for k in range(n):
        mk = lab == k
        a = area_vx2(xyz, mk)
        order.append((a, k, mk))
    order.sort(key=lambda x: (-x[0], x[1]))
    for a, k, mk in order:
        if a <= 0 or a < least_vx2:
            dropped["pieces"] += 1
            dropped["vertices"] += int(mk.sum())
            dropped["area_vx2"] += a
            continue
        if max_off is not None and off_vertices is not None and (off_vertices & mk).sum() > max_off * mk.sum():
            off_dropped["pieces"] += 1
            off_dropped["vertices"] += int(mk.sum())
            off_dropped["area_vx2"] += a
            continue
        idx = len(kept)
        labels[mk] = idx
        rr, cc = np.nonzero(mk)
        kept.append({"index": idx, "vertices": int(mk.sum()), "area_vx2": round(a, 2),
                     "area_cm2": round(a * k2cm, 5) if k2cm else None,
                     "rows": [int(rr.min()), int(rr.max()) + 1], "cols": [int(cc.min()), int(cc.max()) + 1]})
    kept_vx2 = sum(r["area_vx2"] for r in kept)
    rec = {
        "params_digest": params_digest(P),
        "grid": list(valid.shape), "vertices": int(valid.sum()),
        "area_vx2": round(total, 2), "area_cm2": round(total * k2cm, 5) if k2cm else None,
        "cut_vertices": {"selfcross": int(sc.sum()), "seating": int(st.sum()), "off_sheet": int(of.sum()),
                         **({"extra": int(ex.sum())} if extra_mask is not None else {}), "any": int(cut.sum())},
        "measured": {"selfcross": contacts is not None, "seating": windows is not None,
                     "off_sheet": offsheet_mask is not None},
        "regions": kept, "kept_area_vx2": round(kept_vx2, 2),
        "kept_area_cm2": round(kept_vx2 * k2cm, 5) if k2cm else None,
        "kept_share": round(kept_vx2 / total, 4) if total > 0 else 0.0,
        "dropped_small": {**dropped, "area_vx2": round(dropped["area_vx2"], 2)},
        "dropped_off_sheet": {**off_dropped, "area_vx2": round(off_dropped["area_vx2"], 2)},
    }
    return rec, {"cut": cut, "labels": labels, "selfcross": sc, "seating": st, "off_sheet": of, "extra": ex}


def whole_trace(transverse, area_cm2, per_cm2):
    """The whole-trace arms: qa's zero tolerance, and the calibrated rate per cm2 (None: not set)."""
    rate = (transverse / area_cm2) if (transverse is not None and area_cm2) else None
    return {"transverse": transverse, "per_cm2": round(rate, 3) if rate is not None else None,
            "zero_tolerance": None if transverse is None else transverse == 0,
            "calibrated": None if (rate is None or per_cm2 is None) else rate <= per_cm2,
            "tolerance_per_cm2": per_cm2}


# ---------------------------------------------------------------- writing

def _write_grid(path, arr, kind):
    """A float32 (kind f32) or uint16 (u16) single-page TIFF: tifffile when present, else kit/vc3d_io's writer."""
    np = _np()
    a = np.ascontiguousarray(arr, dtype=np.float32 if kind == "f32" else np.uint16)
    try:
        import tifffile
        tifffile.imwrite(str(path), a)
        return
    except ImportError:
        pass
    import array
    from . import vc3d_io
    vc3d_io.write_tiff(path, vc3d_io.Raster(a.shape[0], a.shape[1], kind,
                                            array.array("f" if kind == "f32" else "H", a.tobytes())))


def region_meta(meta, out_name, xyz, mask, unit_um, unit_how, provenance, new_uuid=None):
    np = _np()
    new = {k: v for k, v in (meta or {}).items() if k not in DROP_META}
    a = area_vx2(xyz, mask)
    new.update({"format": new.get("format", "tifxyz"), "type": new.get("type", "seg"),
                "scale": new.get("scale", [0.05, 0.05]), "uuid": new_uuid or str(_uuid.uuid4()), "name": out_name,
                "bbox": [[float(v) for v in xyz[mask].min(axis=0)], [float(v) for v in xyz[mask].max(axis=0)]],
                "area_vx2": a})
    if unit_um:
        new["area_cm2"] = a * (unit_um * 1e-4) ** 2
        if "voxel_size_um" not in new or unit_how.startswith("voxel size"):
            new["voxel_size_um"] = unit_um
    new["kit_regioncrop"] = provenance
    return new


def write_regions(src, out, xyz, labels, rec, meta, gens=None, unit_um=None, unit_how="", overwrite=False,
                  uuids=None, names=None, regions=None, tag="path"):
    """Write each kept piece of `labels` as its own tifxyz folder under `out` (see the module docstring); every
    folder is staged under out and renamed into place. names: folder names in region order (default
    <stem>-rNN[.tifxyz]); regions: the subset of rec["regions"] to write (default all); tag: the key under which each
    region's folder is recorded. Returns the folder paths in region order."""
    np = _np()
    src = Path(src)
    out = Path(os.path.abspath(out))
    stem = src.name[:-len(".tifxyz")] if src.name.endswith(".tifxyz") else src.name
    suffix = ".tifxyz" if src.name.endswith(".tifxyz") else ""
    regions = rec["regions"] if regions is None else regions
    if names is None:
        names = [f"{stem}-r{r['index']:02d}{suffix}" for r in regions]
    targets = [out / n for n in names]
    if out.exists() and not out.is_dir():
        raise CropError(f"{out}: exists and is not a folder")
    if out.resolve() == src.resolve() or src.resolve() in out.resolve().parents:
        raise CropError("the output folder may not be the source or inside it")
    for t in targets:
        if t.exists() and not overwrite:
            raise CropError(f"{t}: exists (pass --overwrite to replace it)")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".regioncrop.", suffix=".partial", dir=out))
    written = []
    try:
        for r, name, target in zip(regions, names, targets):
            r0, r1 = r["rows"]
            c0, c1 = r["cols"]
            mk = labels[r0:r1, c0:c1] == r["index"]
            sub = np.where(mk[..., None], xyz[r0:r1, c0:c1], -1.0)
            stage = work / name
            stage.mkdir()
            for i, ax in enumerate("xyz"):
                _write_grid(stage / f"{ax}.tif", sub[..., i], "f32")
            if gens is not None:
                _write_grid(stage / "generations.tif", np.where(mk, np.clip(gens[r0:r1, c0:c1], 0, 65535), 0), "u16")
            prov = {"source": str(src), "source_realpath": os.path.realpath(src),
                    "source_uuid": (meta or {}).get("uuid"), "region": r["index"],
                    "source_rows": r["rows"], "source_cols": r["cols"], "params_digest": rec["params_digest"],
                    "unit": unit_how, "tool": "kit meshqa crop"}
            m = region_meta(meta, name, xyz[r0:r1, c0:c1], mk, unit_um, unit_how, prov,
                            new_uuid=(uuids[r["index"]] if uuids else None))
            (stage / "meta.json").write_text(json.dumps(m, indent=4) + "\n", encoding="utf-8")
            r[tag], r[f"{tag}_uuid" if tag != "path" else "uuid"] = str(target), m["uuid"]
        for name, target in zip(names, targets):
            if target.exists():
                shutil.rmtree(target)
            os.replace(work / name, target)
            written.append(target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return written


# ---------------------------------------------------------------- community outputs

SPIRAL_ERODE_CELLS = 1          # villa spiral-fitting Config.patch_erode_patches (config.py, read 21 Oct 2026)
SPIRAL_ERODE_META = "spiral_patch_erode_cells"   # tifxyz.py load_tifxyz: a patch's own override of that default
SPIRAL_UUID_NS = _uuid.UUID("6b1e9c52-2a57-5f0e-9d43-6e2f0c1a7b30")     # kit meshqa crop's spiral patch names
TOOL = "kit meshqa crop"


def spiral_erode_cells(meta, default=SPIRAL_ERODE_CELLS):
    """The erosion villa applies to a patch carrying this meta.json (tifxyz.py Patch.erosion_cells: the meta's
    spiral_patch_erode_cells when present, else the config default) and where it came from."""
    v = (meta or {}).get(SPIRAL_ERODE_META)
    if v is None:
        return int(default), "villa default (Config.patch_erode_patches)"
    try:
        return int(v), f"meta.json {SPIRAL_ERODE_META}"
    except (TypeError, ValueError):
        raise CropError(f"meta.json {SPIRAL_ERODE_META} = {v!r} is not a whole number (villa's loader would fail)")


def _source_key(src, meta):
    """What identifies the surface a piece was cut from: its meta.json uuid, else its real path."""
    u = (meta or {}).get("uuid")
    return f"uuid:{u}" if u else f"path:{os.path.realpath(src)}"


def spiral_patch_uuid(src, meta, region, digest):
    """The deterministic name of a piece's spiral patch: uuid5 over the source, the region index and the params."""
    return str(_uuid.uuid5(SPIRAL_UUID_NS, f"{TOOL}|{_source_key(src, meta)}|r{int(region)}|{digest}"))


def spiral_entries_from(out, src, meta):
    """The entries of a verified_patches folder that this tool cut from the same source (any region, any params),
    by their meta.json kit_regioncrop record. Entries written by anything else are ignored."""
    out = Path(out)
    if not out.is_dir():
        return []
    key, found = _source_key(src, meta), []
    for e in sorted(out.iterdir()):
        mf = e / "meta.json"
        if e.name.startswith(".") or not e.is_dir() or not mf.is_file():
            continue
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        kr = m.get("kit_regioncrop") if isinstance(m, dict) else None
        if not isinstance(kr, dict) or kr.get("tool") != TOOL:
            continue
        if kr.get("source_uuid"):
            k = f"uuid:{kr['source_uuid']}"
        else:
            sp = kr.get("source_realpath") or (os.path.realpath(kr["source"]) if kr.get("source") else None)
            k = f"path:{sp}" if sp else None
        if k == key:
            found.append(e)
    return found


def spiral_patch_check(valid, erode_cells=SPIRAL_ERODE_CELLS):
    """What villa's spiral fitting would keep of a piece (spiral-fitting/tifxyz.py Patch, spiral_helpers.py
    erode_patch_valid_region, fit_spiral.py _prepare_patch_sampling_cache): a valid quad has four valid corners, the
    valid region is eroded by erode_cells (scipy binary_erosion, border 0), a patch with no valid quad left is dropped,
    and the fit samples only the largest 8-connected component of the quads. Returns a record; "loads" is False when
    villa would drop the piece."""
    np = _np()
    from scipy import ndimage
    v = np.asarray(valid, bool)

    def quads(m):
        return m[:-1, :-1] & m[1:, :-1] & m[:-1, 1:] & m[1:, 1:]

    q0 = quads(v)
    ev = ndimage.binary_erosion(v, iterations=int(erode_cells), border_value=0) if erode_cells > 0 else v
    q1 = quads(ev)
    largest = 0
    if q1.any():
        lab, n = ndimage.label(q1, structure=np.ones((3, 3), bool))
        largest = int(np.bincount(lab.ravel())[1:].max()) if n else 0
    return {"quads": int(q0.sum()), "quads_after_erosion": int(q1.sum()), "erode_cells": int(erode_cells),
            "largest_quad_component": largest,
            "largest_share": round(largest / int(q1.sum()), 4) if q1.any() else 0.0,
            "loads": bool(q0.any()) and bool(q1.any())}


def write_spiral_patches(src, out, xyz, labels, rec, meta, gens=None, unit_um=None, unit_how="", erode_cells=None,
                         overwrite=False):
    """The kept pieces as patch folders of villa's spiral fitting, out/<uuid>/ (see the module docstring). A piece
    villa would drop after its erosion is not written. erode_cells is villa's config default; the source meta's
    spiral_patch_erode_cells, copied into every patch, overrides it as villa's loader does. Patches this tool cut
    from the same source before are refused, or all replaced under overwrite. Returns the record {"dir", "written",
    "dropped", "replaced", "removed", "erode_cells", ...}."""
    erode, erode_from = spiral_erode_cells(meta, SPIRAL_ERODE_CELLS if erode_cells is None else int(erode_cells))
    out = Path(os.path.abspath(out))
    if out.exists() and not out.is_dir():
        raise CropError(f"{out}: exists and is not a folder")
    before = spiral_entries_from(out, src, meta)
    if before and not overwrite:
        raise CropError(f"{out}: already holds {len(before)} spiral patch(es) cut from this surface "
                        f"({', '.join(e.name for e in before[:3])}{', ...' if len(before) > 3 else ''}); villa "
                        f"loads every entry, so pass --overwrite to replace them")
    keep, dropped, checks = [], [], {}
    for r in rec["regions"]:
        r0, r1 = r["rows"]
        c0, c1 = r["cols"]
        chk = spiral_patch_check(labels[r0:r1, c0:c1] == r["index"], erode)
        checks[r["index"]] = chk
        (keep if chk["loads"] else dropped).append(r)
    uuids = {r["index"]: spiral_patch_uuid(src, meta, r["index"], rec["params_digest"]) for r in keep}
    if keep:
        write_regions(src, out, xyz, labels, rec, meta, gens, unit_um, unit_how, overwrite=overwrite,
                      uuids=uuids, names=[uuids[r["index"]] for r in keep], regions=keep, tag="spiral_patch")
    new = set(uuids.values())
    removed = []
    for e in before:                    # under overwrite: an earlier run's piece this run did not write again
        if e.name not in new:
            shutil.rmtree(e)
            removed.append(e.name)
    for r in rec["regions"]:
        r["spiral_check"] = checks[r["index"]]
    return {"dir": str(out), "written": [r["index"] for r in keep], "dropped": [r["index"] for r in dropped],
            "replaced": sorted(e.name for e in before if e.name in new), "removed": removed,
            "erode_cells": erode, "erode_from": erode_from,
            "format": "villa spiral-fitting verified_patches entry (uuid-named tifxyz folder)"}


def _even(idx, n):
    """At most n items of idx, spread evenly (all of them when there are no more than n)."""
    if n is None or len(idx) <= n:
        return list(idx)
    step = len(idx) / float(n)
    return [idx[int(i * step)] for i in range(n)]


def vc3d_point_doc(xyz, labels, rec, name, cut_h=None, cut_v=None, contacts=None, max_points=200, valid=None):
    """A VC3D point collection document (version 1) with one collection per kept piece (its interior anchor, the
    vertex farthest from the piece's edge, then up to max_points outline vertices) and one "<name>-cuts" collection
    (the quad centres of crossing contacts and the midpoints of jump edges between valid vertices, up to max_points).
    Collection ids are 1, 2, ... in that order; point ids count from 1 within each collection."""
    np = _np()
    from scipy import ndimage
    from .villafmt import VC3D_POINTS_VERSION
    cols = {}

    def coll(cname, pts, color):
        cid = str(len(cols) + 1)
        cols[cid] = {"name": cname, "metadata": {"winding_is_absolute": False}, "color": list(color),
                     "points": {str(i + 1): {"p": [round(float(c), 3) for c in p], "creation_time": 0,
                                             "wind_a": None} for i, p in enumerate(pts)}}

    for r in rec["regions"]:
        mk = labels == r["index"]
        if not mk.any():
            continue
        dist = ndimage.distance_transform_cdt(np.pad(mk, 1), metric="taxicab")[1:-1, 1:-1]
        anchor = np.unravel_index(int(np.argmax(np.where(mk, dist, -1))), mk.shape)
        edge = mk & ~ndimage.binary_erosion(mk, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool),
                                            border_value=0)
        rr, cc = np.nonzero(edge)
        ang = np.arctan2(rr - anchor[0], cc - anchor[1])
        order = [i for i in np.argsort(ang, kind="stable") if (rr[i], cc[i]) != anchor]
        pts = [xyz[anchor]] + [xyz[rr[i], cc[i]] for i in _even(order, max_points)]
        coll(f"{name}-r{r['index']:02d}", pts, (0.2, 0.8, 0.3))
    cut_pts = []
    for r1, c1, r2, c2 in contacts or []:
        for r_, c_ in ((r1, c1), (r2, c2)):
            q = xyz[r_:r_ + 2, c_:c_ + 2].reshape(-1, 3)
            cut_pts.append(q.mean(axis=0))
    valid = np.ones(labels.shape, bool) if valid is None else np.asarray(valid, bool)
    for cut, (dr, dc) in ((cut_h, (0, 1)), (cut_v, (1, 0))):
        if cut is None:
            continue
        rr, cc = np.nonzero(cut)
        for a, b in zip(rr, cc):
            if valid[a, b] and valid[a + dr, b + dc]:
                cut_pts.append((xyz[a, b] + xyz[a + dr, b + dc]) / 2.0)
    if cut_pts:
        coll(f"{name}-cuts", _even(cut_pts, max_points), (0.9, 0.2, 0.2))
    return {"vc_pointcollections_json_version": VC3D_POINTS_VERSION, "collections": cols}


def write_vc3d_points(path, doc):
    """Write a point collection document atomically and read it back with kit/villafmt.py's parser (the rules of
    VC3D's PointCollections.cpp); a document that does not read back is refused."""
    from . import villafmt
    path = Path(path)
    text = json.dumps(doc, indent=1) + "\n"
    if doc["collections"]:
        try:
            villafmt.parse_seeds(text, str(path))
        except villafmt.FormatError as exc:
            raise CropError(f"the point collection does not read back: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return {"path": str(path), "collections": len(doc["collections"]),
            "points": sum(len(c["points"]) for c in doc["collections"].values())}


# ---------------------------------------------------------------- one call

def crop(surface, out=None, *, selfcross=None, windows=None, ct=None, prediction=None, voxel_um=None,
         params=None, overwrite=False, workers=4, cache_dir=None, write=True, spiral_patches=None, vc3d_points=None,
         max_points=200):
    """The region crop of one tifxyz. selfcross: a vc_tifxyz_selfcross report (path or dict), "auto" (run villa's
    tool from VC_BIN or PATH) or None (not measured); windows: grid seating windows or a check_surface seating
    record (path or object); ct: a CT zarr (bucket prefix, URL or folder) to measure seating on a tiling here when
    no windows are given; prediction: a surface prediction for the off-sheet cut and jump edges (None: jumps from
    the geometry only, nothing cut as off-sheet). Writes the pieces to `out` when write, and when given (and write)
    to spiral_patches (villa's verified_patches folder) and vc3d_points (a VC3D point collection file). Returns the
    record."""
    from . import switchfix
    P = params or PARAMS
    check_params(P)
    xyz, valid, meta, gens = read(surface)
    if not valid.any():
        raise CropError(f"{surface}: no valid vertex")
    unit_um, unit_how = coordinate_unit_um(meta, voxel_um)
    contacts, sc_info = None, {"measured": False}
    if selfcross == "auto":
        from . import vc3d
        rep = selfcross_report(surface, vc3d.find_tools(), threads=workers)
        if rep["contacts"] is None:
            raise CropError("vc_tifxyz_selfcross listed no contact positions: nothing can be cut locally")
        contacts, sc_info = rep["contacts"], {"measured": True, "transverse": rep["transverse"], "source": "auto"}
    elif selfcross is not None:
        rep = load_selfcross(selfcross, valid.shape)
        contacts, sc_info = rep["contacts"], {"measured": True, "transverse": rep["transverse"],
                                              "source": str(selfcross) if not isinstance(selfcross, dict) else "dict"}
    win, st_info = None, {"measured": False}
    if windows is not None:
        win = load_windows(windows, meta)
        st_info = {"measured": True, "source": "given", "windows": len(win)}
        if not win:     # a one-window check_surface record keeps no window position: nothing to cut by
            win, st_info = None, {"measured": False, "why": "the seating record has no located window"}
    elif ct is not None:
        sampler = switchfix.open_prediction(ct, cache_dir, workers=workers)
        win = seating_grid(xyz, valid, sampler, unit_um, P["seating"]["window_cells"], P["seating"]["step_vox"],
                           min_quads=P["seating"]["min_quads"])
        st_info = {"measured": True, "source": f"seating_grid on {ct}", "windows": len(win)}
    if win is not None:
        st_info["verdicts"] = {v: sum(1 for w in win if w.get("verdict") == v)
                               for v in ("seated", "unclear", "not seated", "unmeasured")}
    pred = switchfix.open_prediction(prediction, cache_dir, workers=workers) if prediction else None
    of, cut_h, cut_v, of_info, off_all = offsheet(xyz, valid, pred, P["off_sheet"]["min_cells"])
    rec, arrays = cut_regions(xyz, valid, contacts=contacts, windows=win,
                              offsheet_mask=of if pred is not None else None, cut_h=cut_h, cut_v=cut_v,
                              unit_um=unit_um, params=P, off_vertices=off_all)
    rec.update({"surface": str(surface), "unit_um": unit_um, "unit": unit_how, "params": P,
                "selfcross": sc_info, "seating": st_info,
                "off_sheet": {**of_info, "measured": pred is not None, "prediction": str(prediction) if prediction
                              else None},
                "whole_trace": whole_trace(sc_info.get("transverse"), rec["area_cm2"], P["selfcross"]["per_cm2"])})
    if win is not None:
        rec["seating"]["windows_list"] = win
    if write and spiral_patches is not None:       # refuse before anything is written
        if Path(spiral_patches).exists() and not Path(spiral_patches).is_dir():
            raise CropError(f"{spiral_patches}: exists and is not a folder")
        spiral_erode_cells(meta)
        if not overwrite and spiral_entries_from(spiral_patches, surface, meta):
            raise CropError(f"{spiral_patches}: already holds spiral patches cut from this surface; villa loads every "
                            f"entry, so pass --overwrite to replace them")
    if write and out is not None and rec["regions"]:
        write_regions(surface, out, xyz, arrays["labels"], rec, meta, gens, unit_um, unit_how, overwrite)
        rec["out"] = str(out)
    if write and spiral_patches is not None:
        rec["spiral_patches"] = write_spiral_patches(surface, spiral_patches, xyz, arrays["labels"], rec, meta, gens,
                                                     unit_um, unit_how, overwrite=overwrite)
    if write and vc3d_points is not None:
        name = Path(surface).name
        name = name[:-len(".tifxyz")] if name.endswith(".tifxyz") else name
        doc = vc3d_point_doc(xyz, arrays["labels"], rec, name,
                             cut_h if P["regions"]["use_jumps"] else None,
                             cut_v if P["regions"]["use_jumps"] else None, contacts, max_points, valid)
        rec["vc3d_points"] = write_vc3d_points(vc3d_points, doc)
    return rec


# ---------------------------------------------------------------- command line (kit meshqa crop)

def add_parser(act):
    c = act.add_parser("crop", help="keep the clean parts of a trace: cut self-crossings, unseated windows and "
                                    "off-sheet blobs, write each piece above a minimum area as a VC3D tifxyz")
    c.add_argument("surface", help="tifxyz folder")
    c.add_argument("out", nargs="?", help="folder for the kept pieces (<name>-rNN); omit with --dry-run")
    c.add_argument("--selfcross", metavar="REPORT",
                   help="villa vc_tifxyz_selfcross report (JSON with transverse_contacts), or auto to run the tool "
                        "(VC_BIN or PATH); without it crossings are not measured and nothing is cut for them")
    c.add_argument("--seating", metavar="FILE", help="seating windows: a JSON list of {rows, cols, verdict}, or "
                                                     "AutoPipeline check_surface's seating record")
    c.add_argument("--ct", metavar="ZARR", help="measure seating here on a tiling of the grid from this CT zarr "
                                                 "(open-data bucket prefix, URL or folder; level 0)")
    c.add_argument("--prediction", metavar="ZARR", help="surface prediction of the same scan for the off-sheet cut "
                                                         "and the sheet-jump edges (level 0)")
    c.add_argument("--voxel-um", type=float, help="voxel size of the volume the coordinates refer to (default: "
                                                  "meta.json voxel_size_um)")
    c.add_argument("--min-area-cm2", type=float, help=f"keep pieces of at least this area "
                                                      f"(default {PARAMS['regions']['min_area_cm2']})")
    c.add_argument("--dilate", type=int, help=f"cells grown around each crossing (default "
                                              f"{PARAMS['selfcross']['dilate']})")
    c.add_argument("--off-min-cells", type=int, help=f"smallest off-sheet blob cut, in vertices; 0 cuts no blob "
                                                     f"(default {PARAMS['off_sheet']['min_cells']})")
    c.add_argument("--max-off-share", type=float, help=f"reject a piece whole when more than this share of its "
                                                       f"vertices is off the sheet; negative turns the test off "
                                                       f"(default {PARAMS['regions']['max_off_share']})")
    c.add_argument("--seat-fail", choices=("none", "not-seated", "not-seated-or-unclear"),
                   help="seating windows to cut: none (the frozen default: seating is reported, nothing is cut), "
                        "not seated, or not seated and unclear")
    c.add_argument("--window-cells", type=int, help=f"seating tile edge in quads with --ct (default "
                                                    f"{PARAMS['seating']['window_cells']})")
    c.add_argument("--per-cm2", type=float, help=f"whole-trace crossing tolerance per cm2 reported beside "
                                                 f"(default {PARAMS['selfcross']['per_cm2']})")
    c.add_argument("--no-jumps", action="store_true", help="do not separate pieces at jump edges")
    c.add_argument("--spiral-patches", metavar="DIR", help="also write each kept piece as a patch villa's spiral "
                                                            "fitting loads: DIR/<uuid>/ (pass <dataset>/"
                                                            "verified_patches)")
    c.add_argument("--vc3d-points", metavar="FILE", help="also write a VC3D point collection file: one collection "
                                                          "per kept piece (anchor and outline) and one of the cuts")
    c.add_argument("--max-points", type=int, default=200, help="outline or cut points per collection in "
                                                                "--vc3d-points (default 200)")
    c.add_argument("--cache", metavar="DIR", help="chunk cache for --ct and --prediction")
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--dry-run", action="store_true", help="measure and print; write nothing")
    c.add_argument("--overwrite", action="store_true", help="replace existing piece folders, and with "
                                                             "--spiral-patches every patch an earlier run cut from "
                                                             "this surface")
    c.add_argument("--record", metavar="FILE", help="write the JSON record here too")
    c.add_argument("--json", action="store_true", help="print the JSON record")
    return c


def run_crop(args):
    if not args.dry_run and not (args.out or args.spiral_patches or args.vc3d_points):
        raise CropError("give an output folder (or --spiral-patches or --vc3d-points), or --dry-run")
    if args.max_points < 1:
        raise CropError("--max-points is 1 or more")
    P = merged(None, selfcross__dilate=args.dilate, selfcross__per_cm2=args.per_cm2,
               regions__min_area_cm2=args.min_area_cm2,
               seating__window_cells=args.window_cells, regions__use_jumps=False if args.no_jumps else None)
    if args.seat_fail is not None:
        P["seating"]["fail"] = {"none": [], "not-seated": ["not seated"],
                                "not-seated-or-unclear": ["not seated", "unclear"]}[args.seat_fail]
    if args.off_min_cells is not None:
        P["off_sheet"]["min_cells"] = args.off_min_cells or None
    if args.max_off_share is not None:
        P["regions"]["max_off_share"] = args.max_off_share if args.max_off_share >= 0 else None
    check_params(P)
    rec = crop(args.surface, args.out, selfcross=args.selfcross, windows=args.seating, ct=args.ct,
               prediction=args.prediction, voxel_um=args.voxel_um, params=P, overwrite=args.overwrite,
               workers=args.workers, cache_dir=args.cache, write=not args.dry_run,
               spiral_patches=args.spiral_patches, vc3d_points=args.vc3d_points, max_points=args.max_points)
    if args.record:
        Path(args.record).parent.mkdir(parents=True, exist_ok=True)
        Path(args.record).write_text(json.dumps(rec, indent=1) + "\n")
    if args.json:
        print(json.dumps({k: v for k, v in rec.items() if k != "params"}, indent=1))
    else:
        cm = rec["kept_area_cm2"]
        print(f"{rec['surface']}: kept {len(rec['regions'])} pieces, "
              + (f"{cm:.4f} of {rec['area_cm2']:.4f} cm2" if cm is not None else f"{rec['kept_area_vx2']:.0f} vx2")
              + f" ({rec['kept_share']:.3f}); cut {rec['cut_vertices']}")
        wt = rec["whole_trace"]
        if wt["transverse"] is not None:
            print(f"  whole trace: {wt['transverse']} crossings ({wt['per_cm2']} per cm2); zero tolerance "
                  f"{'passes' if wt['zero_tolerance'] else 'rejects'}, calibrated {wt['tolerance_per_cm2']} per cm2 "
                  f"{'passes' if wt['calibrated'] else 'rejects'}")
        for r in rec["regions"]:
            print(f"  r{r['index']:02d} rows {r['rows']} cols {r['cols']} {r['vertices']} vertices "
                  + (f"{r['area_cm2']:.4f} cm2" if r["area_cm2"] is not None else f"{r['area_vx2']:.0f} vx2")
                  + (f" -> {r['path']}" if r.get("path") else "")
                  + (f"; spiral patch {r['spiral_patch']}" if r.get("spiral_patch") else ""))
        sp = rec.get("spiral_patches")
        if sp:
            print(f"  spiral patches: {len(sp['written'])} written to {sp['dir']}"
                  + (f", {len(sp['dropped'])} too thin for villa's {sp['erode_cells']}-cell erosion (not written)"
                     if sp["dropped"] else "")
                  + (f", {len(sp['removed'])} earlier patches from this surface removed" if sp["removed"] else ""))
        if rec.get("vc3d_points"):
            vp = rec["vc3d_points"]
            print(f"  VC3D points: {vp['collections']} collections, {vp['points']} points -> {vp['path']}")
    return 0 if rec["regions"] else 3
