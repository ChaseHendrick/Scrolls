"""Direct 3D ink on a traced sheet (kit ink3d): a 3D ink model predicts ink in the scan's own voxels, and its volume
is read onto the sheet at every pixel of the 2.5D render's canvas, so a 3D map and a 2.5D map of one surface share
their pixels, their labels and their scorer. AutoPipeline's ink stage runs a model named here when a plan lists it in
ink.models (or backends.ink), beside or instead of a 2.5D reader; any other workflow calls run() the same way.

    python -m kit ink3d list [--json]                     every 3D model, its engine, status and what it needs
    python -m kit ink3d fetch NAME [--dest DIR]            download a model's pinned weights and register them
    python -m kit ink3d run NAME --mesh TIFXYZ --render ZARR --volume URL --voxel-um UM --out DIR
        [--pitch-um UM] [--device cpu|cuda|mps] [--json]  infer (or read a published volume), project, control
    python -m kit ink3d pitch --mesh TIFXYZ --volume URL --voxel-um UM [--json]   the sheet pitch from the CT alone
    python -m kit ink3d project MAP --mesh TIFXYZ --render ZARR --out OUT.tif [--map-factor F] [--shift-um UM]

How a map is made (Model output, never a reading):
  1. The sheet pitch, model-free: the scan's CT is sampled along the render normals at patches spread over the
     surface, the mean profile's nearest peak on each side of the sheet gives the pitch (or --pitch-um / a plan's
     ink.pitch_um names it). No peak on either side refuses the run: without a pitch there is no control.
  2. The engine writes a 3D prediction volume over every chunk the projections below read (engines: `command`, any
     program given the mesh, the volume, the chunk list and an output zarr; `villa-full3d`, villa's
     infer_full3d_tifxyz on a villa full_3d checkpoint; `gambiarra`, villa's paris4_3d_gambiarra
     inference of the team's 3D model; `published`, a prediction volume someone already made for this scan, read
     where it lies, nothing inferred). An optional `post` command runs on the volume after it (a CT gate).
  3. Each canvas pixel's render point and normal (kit labelxfer.sample_pixels, the points vc_render_tifxyz samples)
     read the volume, trilinear, at every map voxel step within plus or minus half_um of the sheet, and keep the
     largest: ink_f.tif. The control, ink_r.tif, is the same read with the sheet moved two pitches out and two
     pitches in, the larger of the two at each pixel, so it is never easier to beat than either. Reverse depth order
     means nothing for a 3D model, so the r map of a 3D model is this moved-sheet control and the record says so.
  4. Maps are uint16 TIFFs on the render canvas: 0 where the render has no pixel, else 1 + round(p * 65534).

Status: every 3D model is experimental until one beats the 2.5D default on a frozen held-out test; none has (see each
model's `why`). A model only runs when a plan or caller names it.

Standard library and numpy (tifffile for the maps); an engine's own needs (torch, villa) are its Python's, run as a
child process of KIT_INK_PYTHON (else this Python). Nothing here launches paid compute.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HALF_UM = 15.0           # read within this distance of the sheet on either side (3 level-1 voxels at 2.4 um)
SHIFT_PITCHES = 2        # the control: the sheet moved this many pitches out and in
PITCH_LO_UM, PITCH_HI_UM = 20.0, 400.0     # a pitch outside this is not a sheet pitch
PITCH_REACH_UM = 450.0   # how far the CT profile reaches either side of the sheet
PITCH_PATCHES = 9        # patches the profile is pooled from (a 3 x 3 spread over the canvas)
PITCH_PATCH_PX = 24      # each patch's side in canvas pixels
PITCH_LEVEL_UM = 10.0    # the profile reads the coarsest CT level with voxels no larger than this
TILE = 64                # canvas pixels per side of one projection read
ENGINES = ("command", "published", "villa-full3d", "gambiarra")
STATUSES = ("default", "validated", "experimental", "pending", "failed")
PLACEHOLDERS = ("{mesh}", "{volume}", "{output}", "{targets}", "{device}", "{level}", "{voxel_um}")

# The 3D ink models kit knows. Each names its engine, where its weights come from (pinned), the grid its output is on
# (map_factor: level-0 scan voxels per output voxel; out_level: the CT level the engine reads and writes), what it
# needs, its licence and its status with the evidence behind it. Our own models are added by kit/ink3d_ext_*.py
# (register), so a private model never ships in a public copy.
MODELS = {
    "team-3d-paris4": {
        "engine": "gambiarra", "origin": "team", "by": "the organisers' released 3D ink model (Paris 4 scribbles, "
        "dinovol teacher), run by villa's paris4_3d_gambiarra inference unchanged",
        "repo": "scrollprize/ink_paris4_3d_4.8um_gambiarra", "revision": "4c7119858d4390747e14ddfea6cedcebe65e0530",
        "files": ["model.safetensors"], "checkpoint": "model.safetensors",
        "sha256": {"model.safetensors": "a3986efb473364251af075bbcfa1a982a21a08106d7a5d48b9e954dfeca1a433"},
        "licence": "MIT (weights and villa's paris4_3d_gambiarra code)", "map_factor": 2, "value_range": [0, 255],
        "native_um": 2.4, "needs": ["torch", "villa", "env:KIT_GAMBIARRA"], "compute": "gpu",
        "status": "experimental",
        "why": "no passing held-out result against the 2.5D default yet; trained on 2.4 um Paris 4 scans only",
        "fetch_code": "villa branch ink-paris4-3d-gambiarra, commit c9ca2dc52a7a47ba0df2bfef377639e4b96f16a1: put "
                      "its vesuvius/src/vesuvius/ink_detection/paris4_3d_gambiarra folder's parent in KIT_GAMBIARRA"},
    "forrest-3d-9.6um": {
        "engine": "published", "origin": "community", "by": "Forrest's 9.6 um distillation of the 3D ink model, "
        "inferred over whole scans and published on dl.ash2txt.org (read where it lies, never copied)",
        "volumes": {}, "url_pattern": "https://dl.ash2txt.org/community-uploads/forrest/volcomp/{scroll}/"
                                      "representations/predictions/",
        "licence": "not stated: read at run time from its own host, never redistributed", "map_factor": None,
        "map_um": 9.6, "value_range": [0, 255], "needs": ["numpy"], "compute": "cpu", "status": "experimental",
        "why": "no held-out score yet; a scan is listed in `volumes` once its prediction is published and checked"},
}
EXTENSIONS = {}


class Ink3DError(Exception):
    pass


# ---------------------------------------------------------------- the registry

def register(name, spec):
    """Add a 3D model (an extension's own, or a caller's): spec as in MODELS. Refuses a malformed spec."""
    problems = check_spec(name, spec)
    if problems:
        raise Ink3DError(f"3D model {name}: " + "; ".join(problems))
    EXTENSIONS[name] = spec


def _load_extensions():
    import importlib
    import pkgutil
    pkg = Path(__file__).resolve().parent
    for m in pkgutil.iter_modules([str(pkg)]):
        if m.name.startswith("ink3d_ext_"):
            importlib.import_module(f"{__package__}.{m.name}").register(sys.modules[__name__])


_LOADED = []


def models(registered=None):
    """{name: spec} of every 3D model: kit's own, the extensions', and any model registered on this machine whose
    entry says "dims": "3d" (the models tool's models.json, given as `registered`)."""
    if not _LOADED:
        _LOADED.append(True)
        _load_extensions()
    out = {**MODELS, **EXTENSIONS}
    for name, e in (registered or {}).items():
        if isinstance(e, dict) and e.get("dims") == "3d":
            out[name] = {**out.get(name, {}), **e}
    return out


def is_3d(name, registered=None):
    return name in models(registered)


def check_spec(name, spec):
    p = []
    if not isinstance(spec, dict):
        return ["a spec is an object"]
    if spec.get("engine") not in ENGINES:
        p.append(f"engine is one of {', '.join(ENGINES)}")
    if spec.get("status", "experimental") not in STATUSES:
        p.append(f"status is one of {', '.join(STATUSES)}")
    if spec.get("engine") == "command":
        cmd = spec.get("command")
        if not (isinstance(cmd, list) and cmd and all(isinstance(w, str) for w in cmd)):
            p.append("a command engine needs command, an argument list")
        elif "{output}" not in " ".join(cmd):
            p.append("the command must name {output}, the zarr it writes")
    if spec.get("engine") in ("villa-full3d", "gambiarra") and not (spec.get("checkpoint") or spec.get("repo")):
        p.append("a learned engine needs checkpoint (a path) or repo, revision and files to fetch")
    if spec.get("map_factor") is not None and not (isinstance(spec["map_factor"], (int, float))
                                                    and spec["map_factor"] > 0):
        p.append("map_factor is level-0 voxels per output voxel, a positive number")
    vr = spec.get("value_range", [0, 255])
    if not (isinstance(vr, list) and len(vr) == 2 and vr[1] > vr[0]):
        p.append("value_range is [low, high] with high above low")
    if spec.get("post") is not None and not (isinstance(spec["post"], list) and spec["post"]
                                             and all(isinstance(w, str) for w in spec["post"])):
        p.append("post is an argument list")
    return p


def needs_status(spec, env=None):
    """{need: True/False} on this machine: env:NAME needs that variable; torch and villa are the ink Python's and are
    not imported here (they are reported as `ink python`, checked when the engine starts)."""
    env = os.environ if env is None else env
    out = {}
    for n in spec.get("needs") or []:
        if n.startswith("env:"):
            out[n] = bool(env.get(n[4:]))
        elif n == "numpy":
            try:
                import numpy  # noqa: F401
                out[n] = True
            except ImportError:
                out[n] = False
        else:
            out[n] = "ink python"
    if spec.get("engine") in ("villa-full3d", "gambiarra"):
        out["weights"] = bool(spec.get("checkpoint") and Path(spec["checkpoint"]).is_file())
    return out


def describe(name, registered=None):
    """{name, dims, engine, origin, by, licence, status, why, compute} of one 3D model, for records."""
    s = models(registered).get(name)
    if s is None:
        return None
    return {"name": name, "dims": "3d", **{k: s.get(k) for k in ("engine", "origin", "by", "licence", "status", "why",
                                                                    "compute")}}


# ---------------------------------------------------------------- reading the volume onto the sheet

def _np():
    try:
        import numpy as np
    except ImportError as exc:
        raise Ink3DError("kit ink3d needs numpy") from exc
    return np


def open_volume(location, voxel_um=None):
    from .vc3d_region import Volume
    return Volume(str(location), voxel_um=voxel_um)


def canvas(mesh, render=None):
    """The mesh as kit labelxfer reads it and its render canvas (H, W). With a render, its level-0 shape must be
    layers x that canvas, or nothing is projected (a map on another grid would sit on the wrong pixels)."""
    from . import labelxfer
    M = labelxfer.read_mesh(mesh)
    h, w = labelxfer.canvas_shape(M)
    if render is not None:
        shape = open_volume(render).shape(0)
        if len(shape) != 3 or list(shape[1:]) != [h, w]:
            raise Ink3DError(f"the render {render} is {shape}, not layers by the mesh's canvas {[h, w]}: the 3D map "
                             "would not sit on the render's pixels")
    return M, (h, w)


def tiles(shape, tile=TILE):
    h, w = shape
    for r0 in range(0, h, tile):
        for c0 in range(0, w, tile):
            yield r0, min(h, r0 + tile), c0, min(w, c0 + tile)


def points(M, r0, r1, c0, c1):
    from . import labelxfer
    np = _np()
    R = np.arange(r0, r1)[:, None]
    C = np.arange(c0, c1)[None, :]
    R, C = np.broadcast_arrays(R, C)
    return labelxfer.sample_pixels(M, R, C)


def _to_map(np, xyz, factor):
    """Level-0 (x, y, z) to an output grid `factor` level-0 voxels per voxel (pixel centres aligned)."""
    return (np.asarray(xyz, dtype=float) + 0.5) / factor - 0.5


def project(vol, M, shape, factor, half_vox, shift_vox=0.0, level=0, tile=TILE):
    """The volume read onto the sheet: float (H, W), NaN where the canvas has no rendered pixel; at each pixel the
    largest trilinear value within plus or minus half_vox output voxels of its render point along the normal, the
    point first moved shift_vox output voxels along the normal."""
    np = _np()
    out = np.full(shape, np.nan, dtype=np.float64)
    steps = np.arange(-int(half_vox), int(half_vox) + 1, dtype=float)
    for r0, r1, c0, c1 in tiles(shape, tile):
        pts, nrm, ok = points(M, r0, r1, c0, c1)
        if not ok.any():
            continue
        p, n = pts[ok], nrm[ok]
        best = np.full(len(p), -np.inf)
        for t in steps:
            q = _to_map(np, p + (shift_vox + t) * factor * n, factor)
            best = np.maximum(best, vol.sample(level, q))
        block = out[r0:r1, c0:c1]
        block[ok] = best
    return out


def profile(ct, M, shape, voxel_um, reach_um=PITCH_REACH_UM, patches=PITCH_PATCHES, side=PITCH_PATCH_PX):
    """The mean CT profile along the render normals at patches spread over the canvas: (ts in um, values). The CT
    level is the coarsest with voxels no larger than PITCH_LEVEL_UM, and the profile steps one of its voxels."""
    np = _np()
    level = ct.coarsest_within(PITCH_LEVEL_UM) if ct.voxel_um else 0
    lv_um = ct.level_um(level) or voxel_um
    factor = lv_um / voxel_um
    reach = max(2, int(math.ceil(reach_um / lv_um)))
    ts = np.arange(-reach, reach + 1, dtype=float)
    h, w = shape
    k = max(1, int(round(math.sqrt(patches))))
    centres = [(int((i + 0.5) * h / k), int((j + 0.5) * w / k)) for i in range(k) for j in range(k)]
    total, count = np.zeros(len(ts)), np.zeros(len(ts))
    for cy, cx in centres:
        r0, c0 = max(0, cy - side // 2), max(0, cx - side // 2)
        pts, nrm, ok = points(M, r0, min(h, r0 + side), c0, min(w, c0 + side))
        if ok.sum() < 4:
            continue
        p, n = pts[ok], nrm[ok]
        prof = np.array([vol_mean(ct, level, _to_map(np, p + t * factor * n, factor)) for t in ts])
        total = total + np.nan_to_num(prof, nan=0.0)
        count = count + np.isfinite(prof)
    if not np.any(count):
        raise Ink3DError("no patch of the surface has enough rendered pixels to read the CT profile")
    with np.errstate(invalid="ignore", divide="ignore"):
        return ts * lv_um, np.where(count > 0, total / np.maximum(count, 1), np.nan)


def vol_mean(vol, level, xyz):
    """The mean CT value at the points, NaN when any point lies outside the array (its fill is not the scan)."""
    np = _np()
    xyz = np.asarray(xyz, dtype=float)
    shape = vol.shape(level)[::-1]          # x, y, z
    if not len(xyz) or (xyz < 0).any() or (xyz > np.asarray(shape) - 1).any():
        return float("nan")
    return float(np.mean(vol.sample(level, xyz)))


PEAK_PROMINENCE = 0.05   # a peak rises this share of the profile's range above the lowest value between it and t = 0


def nearest_peaks(prof, ts_um, lo=PITCH_LO_UM, hi=PITCH_HI_UM):
    """The nearest strict local maximum of the profile on each side of the sheet within lo to hi um that rises above
    a trough between it and the sheet: (minus, plus), None where a side has none. NaN (outside the scan) is never a
    peak or a neighbour of one, and a plateau is not a peak."""
    np = _np()
    prof, ts = np.asarray(prof, float), np.asarray(ts_um, float)
    fin = prof[np.isfinite(prof)]
    span = float(fin.max() - fin.min()) if fin.size else 0.0
    zero = int(np.argmin(np.abs(ts)))
    out = []
    for sign in (-1, 1):
        best = None
        for i in range(1, len(prof) - 1):
            t = ts[i]
            if np.sign(t) != sign or not lo <= abs(t) <= hi or not np.isfinite(prof[i - 1:i + 2]).all():
                continue
            if not (prof[i] > prof[i - 1] and prof[i] > prof[i + 1]):
                continue
            between = prof[min(i, zero):max(i, zero) + 1]
            if span <= 0 or not np.isfinite(between).all() or prof[i] - between.min() < PEAK_PROMINENCE * span:
                continue
            if best is None or abs(t) < abs(best):
                best = float(t)
        out.append(best)
    return tuple(out)


def sheet_pitch(ct, M, shape, voxel_um):
    """{pitch_um, minus_um, plus_um, source}: the pitch from the CT profile, the mean of the two sides' nearest
    peaks, or the one side found. Raises when neither side has a peak."""
    ts, prof = profile(ct, M, shape, voxel_um)
    minus, plus = nearest_peaks(prof, ts)
    found = [abs(v) for v in (minus, plus) if v is not None]
    if not found:
        raise Ink3DError(f"the CT profile has no sheet peak within {PITCH_LO_UM} to {PITCH_HI_UM} um of the surface "
                         "on either side: give the pitch (--pitch-um, ink.pitch_um)")
    return {"pitch_um": round(sum(found) / len(found), 3), "minus_um": minus, "plus_um": plus,
            "source": "CT profile along the render normals (model-free)"}


def reach_chunks(M, shape, factor, half_vox, shifts_vox, chunks, grid_shape, tile=TILE):
    """The output chunks (z, y, x keys) the projections at every shift read, on a grid of `chunks` and
    `grid_shape` (output voxels): what an engine must infer."""
    np = _np()
    keys = set()
    ch = np.asarray(chunks, dtype=float)
    top = np.asarray(grid_shape) - 1
    for r0, r1, c0, c1 in tiles(shape, tile):
        pts, nrm, ok = points(M, r0, r1, c0, c1)
        if not ok.any():
            continue
        p, n = pts[ok], nrm[ok]
        for s in shifts_vox:
            for t in range(-int(half_vox) - 1, int(half_vox) + 2):    # every step: a segment can cut a chunk corner
                q = _to_map(np, p + (s + t) * factor * n, factor)[:, ::-1]          # z, y, x
                for corner in (np.floor(q), np.floor(q) + 1):
                    idx = (np.clip(corner, 0, top) // ch).astype(int)
                    keys.update(map(tuple, np.unique(idx, axis=0).tolist()))
    return sorted(keys)


def encode(np, p):
    """uint16: 0 where p is NaN (no rendered pixel), else 1 + round(clip(p, 0, 1) * 65534)."""
    u = np.zeros(p.shape, dtype=np.uint16)
    ok = np.isfinite(p)
    u[ok] = 1 + np.round(np.clip(p[ok], 0.0, 1.0) * 65534).astype(np.uint16)
    return u


def write_map(path, p):
    np = _np()
    try:
        import tifffile
    except ImportError as exc:
        raise Ink3DError("kit ink3d needs tifffile to write a map") from exc
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(str(path), encode(np, p))
    return str(path)


def scaled(np, m, value_range):
    lo, hi = value_range
    return (m - lo) / float(hi - lo)


# ---------------------------------------------------------------- engines

def ink_python(env=None):
    env = os.environ if env is None else env
    return env.get("KIT_INK_PYTHON") or sys.executable


def _fill(words, values):
    out = []
    for w in words:
        for k, v in values.items():
            w = w.replace("{" + k + "}", str(v))
        out.append(w)
    return out


def _run(cmd, log, env=None, cwd=None):
    with open(log, "a") as fh:
        fh.write(f"$ {' '.join(map(str, cmd))}\n")
        fh.flush()
        return subprocess.run([str(c) for c in cmd], stdout=fh, stderr=subprocess.STDOUT, env=env, cwd=cwd).returncode


def mesh_copy(mesh, volume, dest):
    """The tifxyz copied into dest with villa's volume_source.txt naming the scan, so villa's mesh reader finds the
    volume without anything written beside the original mesh."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(mesh, dest)
    (dest / "volume_source.txt").write_text(str(volume).rstrip("/") + "\n")
    return dest


def grid_for(spec, ct, voxel_um):
    """(map_factor, out_level, grid_shape, chunks) of the engine's output grid. The output is on CT level
    out_level = log2(map_factor) for the learned engines (they read and write that level's grid and chunks); a
    command engine's chunks default to 64."""
    np = _np()
    factor = spec.get("map_factor")
    if factor is None and spec.get("map_um"):
        factor = float(spec["map_um"]) / float(voxel_um)
    factor = float(factor or 1)
    level = int(round(math.log2(factor))) if factor >= 1 and abs(math.log2(factor) - round(math.log2(factor))) < 1e-6 \
        else None
    if level is not None and level < len(ct.levels):
        meta = ct.levels[level]["meta"]
        return factor, level, list(meta["shape"]), list(meta.get("inner") or meta["chunks"])
    shape0 = ct.shape(0)
    return factor, level, [int(np.ceil(s / factor)) for s in shape0], [int(spec.get("chunk", 64))] * 3


def infer(spec, name, mesh, volume, work, targets, device, voxel_um, level, log):
    """Run the engine; returns the location of the prediction volume (a zarr group or array)."""
    eng = spec["engine"]
    env = dict(os.environ)
    env.pop("KIT_ALLOW_MODAL", None)
    if eng == "published":
        src = (spec.get("volumes") or {}).get(str(volume)) or (spec.get("volumes") or {}).get(_scan_key(volume))
        if not src:
            raise Ink3DError(f"{name}: no published 3D prediction is listed for this scan ({volume}); listed: "
                             f"{', '.join(sorted(spec.get('volumes') or {})) or 'none yet'}")
        return src
    out = Path(work) / "pred.zarr"
    tfile = Path(work) / "targets.json"
    tfile.write_text(json.dumps(targets))
    if eng == "command":
        cmd = _fill(spec["command"], {"mesh": mesh, "volume": volume, "output": out, "targets": tfile,
                                      "device": device, "level": level if level is not None else 0,
                                      "voxel_um": voxel_um})
        rc = _run(cmd, log, env)
    elif eng == "villa-full3d":
        m = mesh_copy(mesh, volume, Path(work) / "mesh")
        rc = _run([ink_python(env), "-m", f"{__package__}.ink3d", "_villa", spec["checkpoint"], m, out,
                   "--targets", tfile, "--level", str(level), "--batch", str(spec.get("batch", 4)),
                   "--workers", str(spec.get("workers", 8))], log, env, cwd=str(Path(__file__).resolve().parents[1]))
    elif eng == "gambiarra":
        if not env.get("KIT_GAMBIARRA"):
            raise Ink3DError(f"{name}: KIT_GAMBIARRA must name the folder holding paris4_3d_gambiarra "
                             f"({spec.get('fetch_code', 'villa branch ink-paris4-3d-gambiarra')})")
        out = Path(work) / "pred-g"
        rc = _run([ink_python(env), "-m", f"{__package__}.ink3d", "_gambiarra", spec["checkpoint"], out,
                   str(volume).rstrip("/") + "/0/", "--targets", tfile, "--device", device], log, env,
                  cwd=str(Path(__file__).resolve().parents[1]))
        out = out / "code.zarr"
    else:
        raise Ink3DError(f"{name}: unknown engine {eng}")
    if rc != 0:
        raise Ink3DError(f"{name}: the {eng} engine exited {rc} (log {log})")
    if spec.get("post"):
        rc = _run(_fill(spec["post"], {"output": out, "volume": volume, "targets": tfile, "mesh": mesh,
                                       "device": device, "level": level if level is not None else 0,
                                       "voxel_um": voxel_um}), log, env)
        if rc != 0:
            raise Ink3DError(f"{name}: its post step exited {rc} (log {log})")
    return str(out)


def _scan_key(volume):
    return str(volume).rstrip("/").rsplit("/", 1)[-1]


class Decoded:
    """G's stored codes read as scores 0..255 (255 sigmoid((c - 127.5) / 10); code 0, no prediction, is 0): wraps a
    Volume so sample() returns scores."""

    def __init__(self, vol):
        self.vol, self.levels = vol, vol.levels

    def sample(self, level, xyz):
        np = _np()
        # decode each corner before blending, so a 0 code (no prediction) never blends as a low logit
        pts = np.asarray(xyz, dtype=float).reshape(-1, 3)
        zyx = pts[:, ::-1]
        lo = np.floor(zyx.min(axis=0)).astype(int) - 1
        hi = np.floor(zyx.max(axis=0)).astype(int) + 2
        c = np.asarray(self.vol.read(level, list(zip(lo, hi + 1))), np.float64)
        block = 255.0 / (1.0 + np.exp(-(c - 127.5) / 10.0))
        block[c == 0] = 0.0
        local = zyx - lo
        i0 = np.floor(local).astype(int)
        f = local - i0
        out = np.zeros(len(pts))
        import itertools
        for dz, dy, dx in itertools.product((0, 1), repeat=3):
            w = (f[:, 0] if dz else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dx else 1 - f[:, 2])
            out += w * block[np.clip(i0[:, 0] + dz, 0, block.shape[0] - 1), np.clip(i0[:, 1] + dy, 0,
                                                                                    block.shape[1] - 1),
                             np.clip(i0[:, 2] + dx, 0, block.shape[2] - 1)]
        return out


# ---------------------------------------------------------------- one run

def run(name, mesh, render, volume, voxel_um, out, device="cpu", pitch_um=None, registered=None, half_um=HALF_UM,
        log=None):
    """One 3D model on one surface: pitch, inference, projection and control. Writes OUT/ink_f.tif, OUT/ink_r.tif and
    OUT/ink.json, and returns the record (AutoPipeline's ink entry: exit, out, maps, comparison, warnings, device)."""
    np = _np()
    started = time.time()
    spec = models(registered).get(name)
    if spec is None:
        raise Ink3DError(f"no 3D model {name}; known: {', '.join(sorted(models(registered)))}")
    problems = check_spec(name, spec)
    if problems:
        raise Ink3DError(f"3D model {name}: " + "; ".join(problems))
    out = Path(out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    log = Path(log) if log else out / "ink3d.log"
    M, shape = canvas(mesh, render)
    ct = open_volume(volume, voxel_um)
    warnings = []
    if spec.get("native_um") and abs(float(voxel_um) / float(spec["native_um"]) - 1) > 0.15:
        warnings.append(f"{name} was trained on {spec['native_um']} um scans and this scan is {voxel_um} um")
    if pitch_um is None:
        pitch = sheet_pitch(ct, M, shape, voxel_um)
    else:
        pitch = {"pitch_um": float(pitch_um), "source": "given"}
    factor, level, grid_shape, chunks = grid_for(spec, ct, voxel_um)
    map_um = factor * float(voxel_um)
    half_vox = max(1, int(round(half_um / map_um)))
    shift = SHIFT_PITCHES * pitch["pitch_um"] / map_um
    shifts = (0.0, shift, -shift)
    targets = [] if spec["engine"] == "published" else [list(k) for k in reach_chunks(
        M, shape, factor, half_vox, shifts, chunks, grid_shape)]
    pred = infer(spec, name, mesh, volume, work, targets, device, voxel_um, level, log)
    vol = open_volume(pred)
    if spec["engine"] == "gambiarra":
        vol = Decoded(vol)
    lvl = 0
    maps = {}
    on = scaled(np, project(vol, M, shape, factor, half_vox, 0.0, lvl), spec.get("value_range", [0, 255]))
    moved = [scaled(np, project(vol, M, shape, factor, half_vox, s, lvl), spec.get("value_range", [0, 255]))
             for s in shifts[1:]]
    with np.errstate(invalid="ignore"):
        ctl = np.fmax(moved[0], moved[1])
    ctl[np.isnan(on)] = np.nan
    maps["f"] = {"path": write_map(out / "ink_f.tif", on)}
    maps["r"] = {"path": write_map(out / "ink_r.tif", ctl),
                 "control": f"moved-sheet: the larger of the sheet moved {SHIFT_PITCHES} pitches out and in"}
    for v, m in (("f", on), ("r", ctl)):
        fin = m[np.isfinite(m)]
        maps[v]["stats"] = {"pixels": int(fin.size), "mean": round(float(fin.mean()), 5) if fin.size else None,
                            "above_threshold": round(float((fin > 0.5).mean()), 6) if fin.size else None,
                            "threshold": 0.5}
    rec = {"exit": 0, "out": str(out), "dims": "3d", "model": describe(name, registered), "engine": spec["engine"],
           "mesh": str(mesh), "render": str(render) if render else None, "volume": str(volume),
           "voxel_um": float(voxel_um), "prediction": str(pred), "grid": {"map_factor": factor, "level": level,
                                                                          "map_um": round(map_um, 4)},
           "half_um": half_um, "half_voxels": half_vox, "pitch": pitch, "control_shift_um":
           round(SHIFT_PITCHES * pitch["pitch_um"], 3), "targets": len(targets), "maps": maps,
           "comparison": {"r": {"control": "moved-sheet",
                                "f_mean_minus_r_mean": round(float(np.nanmean(on) - np.nanmean(ctl)), 5)
                                if np.isfinite(on).any() else None}},
           "warnings": warnings, "device": device, "seconds": round(time.time() - started, 1),
           "variants": ["f", "r"],
           "note": "model output, not a reading; the r map of a 3D model is the moved-sheet control, not reverse "
                   "depth"}
    (out / "ink.json").write_text(json.dumps(rec, indent=1))
    return rec


# ---------------------------------------------------------------- engine entry points (run in the ink Python)

def _plan_points(np, targets, chunks):
    """Chunk centres as a one-row point grid, so villa's planner occupies exactly the target chunks."""
    k = np.asarray(sorted(map(tuple, targets)), np.float64)
    c = np.asarray(chunks, np.float64)
    centre = (k + 0.5) * c
    z, y, x = (centre[:, i][None, :].astype(np.float32) for i in range(3))
    return x, y, z, np.ones_like(x, bool)


def villa_main(argv):
    """villa's infer_full3d_tifxyz on exactly the target chunks (the plan's point reader patched, nothing else)."""
    p = argparse.ArgumentParser(prog="kit.ink3d _villa")
    p.add_argument("checkpoint")
    p.add_argument("mesh")
    p.add_argument("out")
    p.add_argument("--targets", required=True)
    p.add_argument("--level", type=int, default=1)
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--workers", type=int, default=8)
    a = p.parse_args(argv)
    import numpy as np
    import vesuvius.ink_detection.inference.infer_full3d_tifxyz as I
    src = I.read_volume_source(Path(a.mesh))
    vol = I._open_shared_volume(src, str(a.level), cache_dir=None, cache_max_gb=None)
    targets = json.loads(Path(a.targets).read_text())
    pts = _plan_points(np, targets, tuple(vol.chunks))
    I.read_tifxyz_points = lambda d, native_coordinate_scale=1.0: pts
    return I.main([str(a.mesh), str(a.checkpoint), str(a.out), "--resolution", str(a.level), "--write-region",
                   "occupied", "--chunk-halo", "0", "--num-workers", str(a.workers), "--batch-size", str(a.batch),
                   "--overwrite", "--no-compile"]) or 0


def gambiarra_main(argv):
    """villa's paris4_3d_gambiarra.infer_volume on exactly the target units (its unit list replaced by them)."""
    p = argparse.ArgumentParser(prog="kit.ink3d _gambiarra")
    p.add_argument("weights")
    p.add_argument("out")
    p.add_argument("ct0")
    p.add_argument("--targets", required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--unit", type=int, default=128)
    p.add_argument("--batch", type=int, default=16)
    a = p.parse_args(argv)
    import vesuvius.ink_detection as ID
    pkg = os.environ["KIT_GAMBIARRA"]
    if not (Path(pkg) / "paris4_3d_gambiarra" / "infer_volume.py").is_file():
        raise SystemExit(f"{pkg}: no paris4_3d_gambiarra package")
    ID.__path__.append(pkg)
    import vesuvius.ink_detection.paris4_3d_gambiarra.infer_volume as IV
    targets = [tuple(k) for k in json.loads(Path(a.targets).read_text())]
    IV.units_of = lambda shape, unit, box=None: list(targets)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    return IV.main(["--weights", a.weights, "--out", a.out, "--ct", a.ct0, "--unit", str(a.unit), "--chunk",
                    str(a.unit), "--batch", str(a.batch), "--presence", "probe"]) or 0


# ---------------------------------------------------------------- fetch and command line

def fetch(name, dest=None, home=None, log=print):
    """Download a model's pinned files (kit.vc3d_catalog's checked downloader) and register it in the models tool's
    models.json with dims 3d and its checkpoint path. Returns the receipt."""
    from . import vc3d_catalog
    spec = models().get(name)
    if spec is None or not spec.get("repo"):
        raise Ink3DError(f"{name}: not a 3D model with weights to fetch")
    home = Path(home or os.environ.get("KIT_VC3D_HOME") or Path.home() / ".vc3d")
    dest = Path(dest or home / "models" / name)
    receipt = vc3d_catalog.fetch_model(name, dest, log=log, spec={**spec, "engine": spec["engine"]})
    receipt["checkpoint"] = str(dest / spec["checkpoint"])
    reg = home / "models.json"
    try:
        current = json.loads(reg.read_text())
    except (OSError, json.JSONDecodeError):
        current = {}
    pin = next((f["sha256"] for f in receipt["files"] if f["path"] == spec["checkpoint"]), None)
    current[name] = {"dims": "3d", "engine": spec["engine"], "checkpoint": receipt["checkpoint"], "sha256": pin,
                     "notes": f"fetched by kit ink3d from {spec['repo']}@{spec['revision']}"}
    home.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps(current, indent=1))
    return receipt


def listing(registered=None, env=None):
    return {"models": {n: {**describe(n, registered), "needs": needs_status(s, env)}
                       for n, s in sorted(models(registered).items())},
            "rule": "every 3D model is experimental until one beats the 2.5D default on a frozen held-out test"}


def registered_models(home=None):
    home = Path(home or os.environ.get("KIT_VC3D_HOME") or Path.home() / ".vc3d")
    try:
        return json.loads((home / "models.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_villa"]:
        return villa_main(argv[1:])
    if argv[:1] == ["_gambiarra"]:
        return gambiarra_main(argv[1:])
    p = argparse.ArgumentParser(prog="python -m kit ink3d", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list", help="every 3D model with its engine, status and needs")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("fetch", help="download a model's pinned weights and register them")
    s.add_argument("name")
    s.add_argument("--dest")
    s = sub.add_parser("run", help="one 3D model on one surface: pitch, inference, projection, control")
    s.add_argument("name")
    s.add_argument("--mesh", required=True)
    s.add_argument("--render")
    s.add_argument("--volume", required=True)
    s.add_argument("--voxel-um", type=float, required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--pitch-um", type=float)
    s.add_argument("--device", default="cpu")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("pitch", help="the sheet pitch from the CT alone")
    s.add_argument("--mesh", required=True)
    s.add_argument("--volume", required=True)
    s.add_argument("--voxel-um", type=float, required=True)
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("project", help="a 3D prediction volume read onto a surface's render canvas")
    s.add_argument("map")
    s.add_argument("--mesh", required=True)
    s.add_argument("--render")
    s.add_argument("--out", required=True)
    s.add_argument("--map-factor", type=float, default=1.0)
    s.add_argument("--half-vox", type=int, default=3)
    s.add_argument("--shift-vox", type=float, default=0.0)
    s.add_argument("--max", type=float, default=255.0, help="the volume's value for probability 1")
    a = p.parse_args(argv)
    try:
        if a.cmd == "list":
            res = listing(registered_models())
            if a.json:
                print(json.dumps(res, indent=1))
            else:
                for n, m in res["models"].items():
                    print(f"{n}: {m['engine']}, {m['origin']}, {m['status']}; {m['licence']}")
                    print(f"  {m['why']}")
                print(res["rule"])
            return 0
        if a.cmd == "fetch":
            r = fetch(a.name, a.dest)
            print(f"{a.name}: {r['checkpoint']}")
            return 0
        if a.cmd == "pitch":
            M, shape = canvas(a.mesh)
            r = sheet_pitch(open_volume(a.volume, a.voxel_um), M, shape, a.voxel_um)
            print(json.dumps(r, indent=1) if a.json else f"sheet pitch {r['pitch_um']} um ({r['source']})")
            return 0
        if a.cmd == "project":
            np = _np()
            M, shape = canvas(a.mesh, a.render)
            m = project(open_volume(a.map), M, shape, a.map_factor, a.half_vox, a.shift_vox)
            write_map(a.out, scaled(np, m, [0, a.max]))
            print(a.out)
            return 0
        r = run(a.name, a.mesh, a.render, a.volume, a.voxel_um, a.out, a.device, a.pitch_um, registered_models())
        print(json.dumps(r, indent=1) if a.json else
              f"{a.name}: f {r['maps']['f']['path']}, control r {r['maps']['r']['path']} (pitch "
              f"{r['pitch']['pitch_um']} um; model output, not a reading)")
        return 0
    except Ink3DError as exc:
        print(f"kit ink3d: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
