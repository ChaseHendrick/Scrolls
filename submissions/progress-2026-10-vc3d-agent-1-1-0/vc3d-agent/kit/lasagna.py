"""Headless lasagna for agents: villa's lasagna surface fitter with no VC3D, JSON in and JSON out.

villa's lasagna (ScrollPrize/villa, lasagna/) fits multi-winding meshes to its predicted normals, grad_mag and cos
volumes. VC3D drives it through an HTTP fit service; its own `fit.py` runs from a shell but gives an agent no result
it can read, needs a local manifest, and every volume mode needs CUDA. These tools are that missing layer, on top of
villa's own code (nothing here reimplements the fit):

  lasagna_status    where villa's lasagna and its Python are, what that Python has (torch, CUDA, MPS)
  lasagna_configs   villa's shipped stage configs: mode, stages, steps, loss terms; one config in full
  lasagna_manifest  a local .lasagna.json for fit.py from a published lasagna run (streamed: CUDA), or a mirror of a
                    crop of it (any device), or a check of a local manifest
  lasagna_fit       one fit.py run from a config plus overrides: progress, checkpoints, tifxyz with their stats
  lasagna_export    fit2tifxyz on a checkpoint (one segment, name, voxel size for the area)
  lasagna_selftest  a tiny synthetic fit on CPU whose check can fail, with a control
  lasagna_service   a client for villa's fit service (the HTTP API VC3D speaks), local or on a GPU machine

They register on kit/vc3d_agent.py (through kit/vc3d_ext_lasagna.py), so `python -m kit vc3d mcp` serves them over
MCP and `python -m kit vc3d call lasagna_fit '{...}'` runs one; `python -m kit lasagna fit ...` is the same with
flags. Results are JSON on stdout, progress on stderr; exit 0 when the tool succeeded, 1 when it ran and failed,
2 when it could not run (bad arguments, villa not set up, a service it cannot reach, a failed download), as
`kit vc3d call` does. Guide: docs/lasagna-agents.md.

Where villa is: LASAGNA_DIR (villa's lasagna folder), else VILLA_DIR/lasagna, else ~/villa/lasagna (VC3D's own
search). Its Python: LASAGNA_PYTHON, else LASAGNA_DIR/.venv/bin/python (villa's bootstrap), else this Python.
Off CUDA, fit.py runs through scripts/lasagna/fit_cpu_shim.py, which loads a box densely instead of streaming.
Standard library only; torch and the rest live in the lasagna Python.
"""

import argparse
import base64
import concurrent.futures
import copy
import http.client
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import kithome, s3retry, vc3d_audit

MODES = ("seed", "ext", "model", "flatten", "atlas")
DEVICES = ("cuda", "cpu", "mps")
REQUIRED_CHANNELS = ("grad_mag", "nx", "ny")
SERVICE_API = "2"                        # villa fit_service.py: X-Fit-Service-API-Version
MARKER = "lasagna-remote.json"           # VC3D's sidecar: groups resolve against artifact_url and stream
TERMINAL = ("finished", "error", "cancelled")
MAX_CHUNKS = 20000                       # a manifest mirror refuses more chunks than this unless told otherwise
DENSE_GIB = 6.0                          # a dense (off-CUDA) load refuses a box larger than this, uint8 voxels
MAX_LEVEL = 32                           # the deepest OME-Zarr level (scaledown) a manifest may name
PROGRESS_RE = re.compile(r"^PROGRESS (\d+) (\d+) (\S+)\s*$")
GUIDE = "docs/lasagna-agents.md"


class LasagnaError(Exception):
    pass


# ---------------------------------------------------------------- where villa is

def find_lasagna(env):
    """(lasagna folder, python, villa root or None, how found). Raises LasagnaError when none holds fit.py."""
    tried = []
    for how, value in (("LASAGNA_DIR", env.get("LASAGNA_DIR")),
                       ("VILLA_DIR", env.get("VILLA_DIR") and str(Path(env["VILLA_DIR"]) / "lasagna")),
                       ("~/villa/lasagna", str(Path(env.get("HOME") or Path.home()) / "villa" / "lasagna"))):
        if not value:
            continue
        p = Path(value).expanduser()
        tried.append(f"{how}={p}")
        if (p / "fit.py").is_file():
            py = env.get("LASAGNA_PYTHON")
            if not py:
                venv = p / ".venv" / "bin" / "python"
                py = str(venv) if venv.exists() else sys.executable
            villa = p.parent if (p.parent / "vesuvius").is_dir() or (p.parent / ".git").exists() else None
            return p, py, villa, how
    raise LasagnaError("villa's lasagna not found (" + ("; ".join(tried) or "nothing set") + "): set LASAGNA_DIR to "
                       "villa's lasagna folder (or VILLA_DIR to a villa checkout) and LASAGNA_PYTHON to a Python with "
                       f"torch, numpy, zarr and tifffile ({GUIDE}, 'Setting up')")


def lasagna_env(env, lasagna, villa):
    """The environment fit.py runs in: villa's lasagna folder on PYTHONPATH, and vesuvius/src (fit imports
    vc3d_fiber_format from it) when the checkout has it."""
    paths = [str(lasagna)]
    if villa is not None and (villa / "vesuvius" / "src").is_dir():
        paths.append(str(villa / "vesuvius" / "src"))
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    return dict(env, PYTHONPATH=os.pathsep.join(paths), PYTHONUNBUFFERED="1", WANDB_MODE="disabled")


def shim_path():
    try:
        return kithome.source_file("scripts/lasagna/fit_cpu_shim.py", "fits off CUDA")
    except kithome.MissingSource as exc:
        raise LasagnaError(str(exc)) from exc


def selftest_script():
    try:
        return kithome.source_file("scripts/lasagna/selftest_data.py", "the lasagna self-test")
    except kithome.MissingSource as exc:
        raise LasagnaError(str(exc)) from exc


PROBE = r"""
import importlib, json, sys
out = {"python": sys.version.split()[0], "executable": sys.executable, "packages": {}}
for name in ("torch", "numpy", "zarr", "tifffile", "tensorstore"):
    try:
        m = importlib.import_module(name)
        out["packages"][name] = getattr(m, "__version__", "present")
    except Exception as exc:
        out["packages"][name] = None
        out.setdefault("missing", {})[name] = f"{type(exc).__name__}: {exc}"[:300]
try:
    import torch
    out["cuda"] = bool(torch.cuda.is_available())
    out["cuda_devices"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())] if out["cuda"] else []
    out["mps"] = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
except Exception:
    out["cuda"] = out["mps"] = False
if "--fit" in sys.argv:
    try:
        import fit, fit2tifxyz  # noqa: F401
        out["fit_import"] = "ok"
    except Exception as exc:
        out["fit_import"] = f"{type(exc).__name__}: {exc}"[:500]
print("KIT_PROBE " + json.dumps(out))
"""


def probe(env, py, lasagna, villa, fit=False, timeout=300):
    """What the lasagna Python has: packages, CUDA, MPS, and (fit=True) whether `import fit` works."""
    try:
        r = subprocess.run([py, "-c", PROBE] + (["--fit"] if fit else []), capture_output=True, text=True,
                           timeout=timeout, cwd=str(lasagna), env=lasagna_env(env, lasagna, villa))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"could not run {py}: {exc}"}
    for line in r.stdout.splitlines():
        if line.startswith("KIT_PROBE "):
            return json.loads(line[len("KIT_PROBE "):])
    return {"error": f"{py} exited {r.returncode}: {(r.stderr or r.stdout)[-800:]}"}


def git_head(folder):
    try:
        r = subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


# ---------------------------------------------------------------- configs

def load_json(path, what="JSON"):
    try:
        return json.loads(Path(path).read_text())
    except OSError as exc:
        raise LasagnaError(f"cannot read {what} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LasagnaError(f"{what} {path} is not valid JSON: {exc}") from exc


def stage_list(cfg):
    """[(name, steps)] of a config's optimizer stages: the `stages` list (steps on the stage or in its opt; an
    int or "auto"), or older top-level stage objects."""
    out = []
    if isinstance(cfg.get("stages"), list):
        for i, s in enumerate(cfg["stages"]):
            if isinstance(s, dict):
                opt = s.get("opt") if isinstance(s.get("opt"), dict) else {}
                out.append((str(s.get("name", f"stage_{i}")), s.get("steps", opt.get("steps"))))
    for k, v in cfg.items():
        if k not in ("args", "base", "stages") and isinstance(v, dict) and "steps" in v:
            out.append((k, v.get("steps")))
    return out


def arg_key(key):
    """A fit.py argument as villa's cli_json finds it: leading dashes dropped, '-' and '_' the same option."""
    return str(key).lstrip("-").replace("_", "-")


def norm_args(args):
    """args as fit.py applies them, keyed by arg_key: cli_json walks the merged args in order, so of two
    spellings of one option (model-init, model_init) the later one wins."""
    out = {}
    for k, v in (args or {}).items():
        out[arg_key(k)] = v
    return out


def truthy(value):
    """villa's _truthy_config_bool."""
    if isinstance(value, (bool, int, float)):
        return bool(value)
    return isinstance(value, str) and value.strip().lower() in ("1", "true", "yes", "on")


SEED_NEEDS = {"seed": ("seed", "seed [x, y, z] in base voxels"),
              "model_h": ("model-h", "model_h, the surface's height in base voxels (fit.py: 'model-init=seed requires "
                                     "--model-h')"),
              "approval-inpaint-tifxyz": ("approval-inpaint-tifxyz", "args approval-inpaint-tifxyz, the tifxyz "
                                                                     "approval-inpaint fills")}


def seed_needs(args):
    """What model-init seed needs from the caller, as fit.py checks it: approval-inpaint first (it needs the seed
    and its tifxyz, and works out model-h), then corr-point-roi (it works out the seed and model-h from the
    correction points), then 'model-init=seed requires --seed, --model-h'. args are keyed by arg_key."""
    corr, appr = truthy(args.get("corr-point-roi")), truthy(args.get("approval-inpaint"))
    needs = ["seed"] if appr or not corr else []
    if not corr and not appr:
        needs.append("model_h")
    if appr:
        needs.append("approval-inpaint-tifxyz")
    return needs


def config_needs(cfg):
    """(model-init, init mode, what a run of this config still needs from the caller) as fit.py checks them."""
    args = norm_args(cfg.get("args") if isinstance(cfg.get("args"), dict) else {})
    mode = str(args.get("model-init", "seed"))
    init_mode = args.get("init-mode")
    needs = {"ext": ["tifxyz_init"], "model": ["model_input"], "flatten": ["external_surfaces"],
             "atlas": ["atlas"]}.get(mode, [])
    if mode == "seed":
        needs = seed_needs(args)
        if (init_mode or "cylinder_seed") == "cylinder_seed":
            needs.append("umbilicus (the manifest's umbilicus_json)")
    if init_mode == "shell-dir-crop" or truthy(args.get("corr-point-roi")):
        needs.append("init_shell_dir")
    if truthy(args.get("corr-point-roi")):
        needs.append("corr_points")
    have = {"tifxyz_init": "tifxyz-init", "model_input": "model-input", "init_shell_dir": "init-shell-dir",
            **{k: v[0] for k, v in SEED_NEEDS.items()}}
    needs = [n for n in needs if not (n in have and args.get(have[n])) and n not in cfg]
    return mode, (init_mode if init_mode or mode != "seed" else "cylinder_seed (villa's default)"), needs


def describe_config(path):
    cfg = load_json(path, "config")
    if not isinstance(cfg, dict):
        raise LasagnaError(f"config {path} is not a JSON object")
    stages = stage_list(cfg)
    steps = [s for _, s in stages if isinstance(s, (int, float))]
    mode, init_mode, needs = config_needs(cfg)
    return {"name": Path(path).name, "path": str(path), "model_init": mode, "init_mode": init_mode,
            "stages": [{"name": n, "steps": s} for n, s in stages],
            "total_steps": int(sum(steps)) if steps and len(steps) == len(stages) else None,
            "loss_terms": sorted(k for k, v in (cfg.get("base") or {}).items() if v) if isinstance(cfg.get("base"), dict)
            else [],
            "needs": needs}


def resolve_config(lasagna, name, base=None):
    """A config path, absolute: as given (relative to base) when it exists, else villa's
    lasagna/configs/<name>(.json). fit.py runs in villa's lasagna folder, so a relative path would not reach it."""
    p = Path(str(name)).expanduser()
    if not p.is_absolute() and base is not None:
        p = Path(base) / p
    if p.is_file():
        return p.resolve()
    p = Path(str(name)).expanduser()
    for cand in (lasagna / "configs" / p.name, lasagna / "configs" / f"{p.name}.json", lasagna / p):
        if cand.is_file():
            return cand
    known = sorted(q.name for q in (lasagna / "configs").glob("*.json")) if (lasagna / "configs").is_dir() else []
    raise LasagnaError(f"no config {name!r} (not a file, not in {lasagna / 'configs'}); villa ships: "
                       + ", ".join(known))


def deep_merge(a, b):
    """fit.py's merge (cli_json.merge_cfgs): objects merge key by key, anything else (lists too) is replaced."""
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else copy.deepcopy(v)
    return out


# ---------------------------------------------------------------- manifests and data

def ceil_half(n, times):
    for _ in range(times):
        n = (n + 1) // 2
    return n


def https(url):
    url = str(url)
    return vc3d_audit.s3_https(url) if url.lower().startswith("s3://") else url


def http_get(url, timeout=60, opener=None):
    """GET with S3's false 404s retried; a server on this machine is reached without the proxy."""
    url = https(url)
    req = urllib.request.Request(url, headers={"User-Agent": "kit-lasagna"})
    try:
        with s3retry.open_url(req, opener or service_opener(url).open, timeout=timeout) as resp:
            return resp.read()
    except http.client.HTTPException as exc:   # a transfer cut off part way (IncompleteRead) is a failed download
        raise OSError(f"{type(exc).__name__}: {exc}") from exc


def fetch(url, what, opener=None):
    """http_get with every failure as a LasagnaError naming what was fetched."""
    try:
        return http_get(url, opener=opener)
    except urllib.error.HTTPError as exc:
        raise LasagnaError(f"{what} {https(url)}: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LasagnaError(f"{what} {https(url)}: {getattr(exc, 'reason', exc)}") from exc


def fetch_json(url, what, opener=None):
    try:
        return json.loads(fetch(url, what, opener))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LasagnaError(f"{what} {https(url)} is not JSON: {exc}") from exc


def list_prefix(url, opener=None):
    """Keys under an S3 prefix (anonymous ListObjectsV2, one level, with continuation)."""
    endpoint, prefix = vc3d_audit.s3_listing(https(url).rstrip("/") + "/")
    if endpoint is None:
        raise LasagnaError(f"{url} is not an S3 URL; give the .lasagna.json URL itself")
    keys, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "delimiter": "/"}
        if token:
            q["continuation-token"] = token
        body = fetch(f"{endpoint}/?{urllib.parse.urlencode(q)}", "listing", opener).decode("utf-8", "replace")
        keys += re.findall(r"<Key>([^<]+)</Key>", body)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", body)
        if not m:
            return endpoint, prefix, keys
        token = m.group(1)


def remote_manifest(source, opener=None):
    """(run folder URL ending in /, manifest file name, manifest dict) for a published run folder or manifest URL."""
    src = https(source)
    if src.endswith(".lasagna.json"):
        base, name = src.rsplit("/", 1)
        return base + "/", name, fetch_json(src, "manifest", opener)
    endpoint, prefix, keys = list_prefix(src, opener)
    names = [k[len(prefix):] for k in keys if k.endswith(".lasagna.json") and "/" not in k[len(prefix):]]
    if len(names) != 1:
        raise LasagnaError(f"{source}: expected one .lasagna.json in the folder, found {names or 'none'}")
    base = f"{endpoint}/{prefix}"
    return base, names[0], fetch_json(base + names[0], "manifest", opener)


def check_manifest_doc(doc):
    """Problems villa's LasagnaVolume.load / fit_data would raise on, without reading any zarr."""
    if not isinstance(doc, dict):
        return ["the manifest is not a JSON object"]
    probs = []
    groups = doc.get("groups")
    if not isinstance(groups, dict) or not groups:
        return ["no groups"]
    chans = {}
    for g, spec in groups.items():
        if not isinstance(spec, dict) or not {"zarr", "scaledown", "channels"} <= set(spec):
            probs.append(f"group {g}: needs zarr, scaledown and channels")
            continue
        rel = str(spec["zarr"])
        if rel.startswith("/") or ".." in Path(rel).parts or re.match(r"^[a-z]+://", rel, re.I):
            probs.append(f"group {g}: zarr {rel!r} must be a relative path inside the manifest's folder")
        if (isinstance(spec["scaledown"], bool) or not isinstance(spec["scaledown"], int)
                or not 0 <= spec["scaledown"] <= MAX_LEVEL):
            probs.append(f"group {g}: scaledown {spec['scaledown']!r} is not an OME-Zarr level (0 to {MAX_LEVEL})")
        if not isinstance(spec["channels"], list):
            probs.append(f"group {g}: channels is not a list")
            continue
        for c in spec["channels"]:
            chans.setdefault(c, g)
    miss = [c for c in REQUIRED_CHANNELS if c not in chans]
    if miss:
        probs.append(f"channels {miss} missing (fit.py needs grad_mag, nx and ny; cos for the data terms)")
    shape = doc.get("base_shape_zyx")
    if shape is not None and not (isinstance(shape, list) and len(shape) == 3
                                  and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in shape)):
        probs.append(f"base_shape_zyx {shape!r} is not three positive integers")
    s2b = doc.get("source_to_base", 1.0)
    if isinstance(s2b, bool) or not isinstance(s2b, (int, float)) or not (math.isfinite(s2b) and s2b > 0):
        probs.append(f"source_to_base {s2b!r} is not a positive number")
    elif not probs:
        for g, spec in groups.items():
            if level_spacing(doc, spec) < 1:
                probs.append(f"group {g}: level {spec['scaledown']} with source_to_base {s2b} is under one base "
                             "voxel per voxel")
    return probs


def spatial(shape):
    """Z, Y, X of a level array: a 3D array, or villa's older flat (C, Z, Y, X) group."""
    return list(shape[-3:])


def check_zarray(za):
    """A problem with a level array's metadata that kit relies on (shape, chunks, separator), or None. villa reads
    3D arrays and older 4D (C, Z, Y, X) groups."""
    if not isinstance(za, dict):
        return "level metadata is not a JSON object"
    shape, chunks = za.get("shape"), za.get("chunks")
    ints = lambda v, low: (isinstance(v, list) and len(v) in (3, 4)  # noqa: E731
                           and all(isinstance(x, int) and not isinstance(x, bool) and x >= low for x in v))
    if not ints(shape, 0):
        return f"shape {shape!r} is not three integers (Z, Y, X) or four (C, Z, Y, X)"
    if not ints(chunks, 1) or len(chunks) != len(shape):
        return f"chunks {chunks!r} is not {len(shape)} positive integers"
    if za.get("dimension_separator", ".") not in (".", "/"):
        return f"dimension_separator {za.get('dimension_separator')!r} is not '.' or '/'"
    return None


def level_spacing(doc, spec):
    """Base voxels per voxel of a group's level array: 2**scaledown x source_to_base, as villa rounds it."""
    return int(round(2 ** int(spec["scaledown"]) * float(doc.get("source_to_base", 1.0))))


def base_frame(doc, zarrays):
    """The manifest's base frame (Z, Y, X) as fit.py takes it: base_shape_zyx, or for an older manifest without
    one villa's fallback (fit_data.get_preprocessed_params): the first readable level array, finest group first,
    its spatial shape times 2**scaledown. None when neither is known."""
    if doc.get("base_shape_zyx") is not None:
        return [int(v) for v in doc["base_shape_zyx"]]
    for g, spec in sorted((doc.get("groups") or {}).items(), key=lambda kv: int(kv[1]["scaledown"])):
        za = zarrays.get(g)
        if isinstance(za, dict) and not za.get("error") and not check_zarray(za):
            return [int(v) * 2 ** int(spec["scaledown"]) for v in spatial(za["shape"])]
    return None


def snap_crop(crop, doc):
    """A crop (x0, y0, z0, w, h, d) as villa's load_3d needs it: the start clipped at 0 and every edge on whole
    voxels of the coarsest group. load_3d reads each group from max(0, start // its spacing) but sets the data's
    origin from the start as given (on the finest group's grid), so a negative start, or one off the coarsest grid,
    samples channels up to |start| or spacing - 1 voxels off, with no error."""
    step = max([level_spacing(doc, spec) for spec in (doc.get("groups") or {}).values()] or [1])
    x0, y0, z0, w, h, d = (int(v) for v in crop)
    lo = [max(0, v) // step * step for v in (x0, y0, z0)]
    hi = [-(-(v + n) // step) * step for v, n in ((x0, w), (y0, h), (z0, d))]
    if any(b <= a for a, b in zip(lo, hi)):
        raise LasagnaError(f"crop {list(crop)} ends at or before voxel 0 on some axis: it holds no data")
    return [lo[0], lo[1], lo[2], hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]]


def group_rows(doc, zarrays):
    """Per group: channels, level, zarr, spacing in base voxels, shape, chunks; checked against base_shape_zyx."""
    rows, probs = [], []
    if check_manifest_doc(doc):
        return rows, probs              # check_manifest_doc names the problems; nothing here can be trusted
    s2b = float(doc.get("source_to_base", 1.0))
    base = doc.get("base_shape_zyx")
    for g, spec in doc["groups"].items():
        za = zarrays.get(g)
        if za is None:
            za = {}
        elif not isinstance(za, dict):
            za = {"error": f"level metadata is not a JSON object ({type(za).__name__})"}
        row = {"group": g, "channels": spec.get("channels"), "level": spec.get("scaledown"), "zarr": spec.get("zarr"),
               "spacing_base_voxels": (2 ** int(spec["scaledown"])) * s2b,
               "shape_zyx": za.get("shape"), "chunks": za.get("chunks"), "dtype": za.get("dtype")}
        bad = None if (not za or za.get("error")) else check_zarray(za)
        if za.get("error") or bad:
            row["error"] = za.get("error") or bad
            probs.append(f"group {g}: {row['error']}")
        elif za:
            if len(za["shape"]) == 4:
                row["shape_zyx"] = spatial(za["shape"])
                row["layout"] = "flat (C, Z, Y, X)"
            if za.get("dtype") != "|u1":
                probs.append(f"group {g}: dtype {za.get('dtype')} (lasagna reads uint8)")
            if base:
                want = [ceil_half(v, int(spec["scaledown"])) for v in base]
                if spatial(za["shape"]) != want:
                    probs.append(f"group {g}: shape {za['shape']} is not base_shape_zyx {base} halved "
                                 f"{spec['scaledown']} times ({want}); villa refuses it")
        rows.append(row)
    return rows, probs


def chunk_keys(zarray, box_zyx):
    """Chunk keys of a v2 level array that a box [(z0, z1), (y0, y1), (x0, x1)] of its voxels touches (every
    channel of a flat (C, Z, Y, X) group)."""
    bad = check_zarray(zarray)
    if bad:
        raise LasagnaError(f"level array: {bad}")
    sep = zarray.get("dimension_separator", ".")
    box = list(box_zyx)
    if len(zarray["shape"]) == 4:
        box = [(0, zarray["shape"][0])] + box
    ranges = []
    for (lo, hi), n, c in zip(box, zarray["shape"], zarray["chunks"]):
        lo, hi = max(0, lo), min(n, hi)
        if hi <= lo:
            return []
        ranges.append(range(lo // c, (hi - 1) // c + 1))
    keys = [()]
    for r in ranges:
        keys = [k + (i,) for k in keys for i in r]
    return [sep.join(map(str, k)) for k in keys]


def level_box(crop, spacing):
    """crop (x0, y0, z0, w, h, d) in base voxels -> [(z0, z1), (y0, y1), (x0, x1)] of a level's voxels, as
    villa's load_3d reads it (floor of the start, ceiling of the end)."""
    x0, y0, z0, w, h, d = (int(v) for v in crop)
    ds = int(round(spacing))
    return [(z0 // ds, -(-(z0 + d) // ds)), (y0 // ds, -(-(y0 + h) // ds)), (x0 // ds, -(-(x0 + w) // ds))]


def dense_gib(doc, zarrays, crop=None, skip=()):
    """GiB of uint8 voxels a dense load of every group reads (a crop box, or whole levels), leaving out the
    channels in skip. A group it cannot size raises: the guard fails closed."""
    total = 0
    for g, spec in (doc.get("groups") or {}).items():
        chans = [c for c in (spec.get("channels") or []) if c not in skip]
        if not chans:
            continue
        za = zarrays.get(g)
        if isinstance(za, dict):
            bad = za.get("error") or check_zarray(za)
        else:
            bad = "no level metadata" if za is None else "level metadata is not a JSON object"
        if bad:
            raise LasagnaError(f"cannot size group {g} for a dense load: {bad}")
        shape = spatial(za["shape"])
        if crop is not None:
            box = level_box(crop, level_spacing(doc, spec))
            n = 1
            for (lo, hi), m in zip(box, shape):
                n *= max(0, min(m, hi) - max(0, lo))
        else:
            n = shape[0] * shape[1] * shape[2]
        total += n * len(chans)
    return total / 2 ** 30


def local_zarrays(manifest, doc):
    out = {}
    if check_manifest_doc(doc):
        return out
    for g, spec in doc["groups"].items():
        p = manifest.parent / str(spec.get("zarr"))
        if (p / ".zarray").is_file():
            try:
                out[g] = json.loads((p / ".zarray").read_text())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                out[g] = {"error": f"{p / '.zarray'} is not JSON: {exc}"}
        elif (p / "zarr.json").is_file():
            try:
                meta = json.loads((p / "zarr.json").read_text())
                out[g] = {"shape": meta.get("shape"), "chunks": (meta.get("chunk_grid") or {}).get("configuration", {})
                          .get("chunk_shape"),
                          "dtype": "|u1" if meta.get("data_type") == "uint8" else meta.get("data_type")}
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
                out[g] = {"error": f"{p / 'zarr.json'} is not zarr v3 array metadata: {exc}"}
        else:
            out[g] = {"error": f"no zarr level array at {p} (.zarray or zarr.json)"}
        if not isinstance(out[g], dict):
            out[g] = {"error": f"{p} level metadata is not a JSON object"}
    return out


def mirror_chunks(base_url, rel, zarray, keys, dest, workers=16, opener=None, sleep=time.sleep):
    """Copy the listed chunk files of one level array; a NoSuchKey chunk is absent (zarr reads it as fill 0, which
    lasagna reads as no data), any other failure raises. Returns (copied, absent, bytes)."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    for key in keys:
        if root not in (root / key).resolve().parents:
            raise LasagnaError(f"chunk key {key!r} would write outside {dest}")

    def one(key):
        target = dest / key
        if target.is_file():
            return "kept", target.stat().st_size
        url = f"{base_url}{rel}/{key}"
        try:
            data = http_get(url, opener=opener)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and not s3retry.false_404(404, exc.read() or b""):
                return "absent", 0
            raise LasagnaError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise LasagnaError(f"{url}: {getattr(exc, 'reason', exc)}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return "copied", len(data)

    copied = absent = nbytes = 0
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        for state, n in ex.map(one, keys):
            copied += state in ("copied", "kept")
            absent += state == "absent"
            nbytes += n
    return copied, absent, nbytes


# ---------------------------------------------------------------- fit runs

def parse_progress(log_text):
    """Steps and losses from fit.py's `PROGRESS step total loss` lines."""
    rows = []
    for line in log_text.splitlines():
        m = PROGRESS_RE.match(line.strip())
        if m:
            try:
                rows.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
            except ValueError:
                continue
    if not rows:
        return {"lines": 0}
    losses = [r[2] for r in rows]
    finite = [v for v in losses if math.isfinite(v)]
    return {"lines": len(rows), "last_step": rows[-1][0], "total_steps": rows[-1][1], "first_loss": losses[0],
            "last_loss": losses[-1], "min_loss": min(finite) if finite else None,
            "non_finite": len(losses) - len(finite)}


HINTS = (
    ("torch.cuda.Stream requires CUDA", "fit.py streams volumes through CUDA caches: use device cpu or mps (kit runs "
                                        "the dense shim) with a local manifest, or run on a CUDA machine"),
    ("expected one argument", "a path ending in .json after a flag is read as a config file; kit passes paths in the "
                              "config's args, so this came from extra argv"),
    ("expected .lasagna.json", "input must be a local file named *.lasagna.json (lasagna_manifest writes one)"),
    ("No module named 'vc3d_fiber_format'", "fit.py imports vesuvius/src/vc3d_fiber_format: use villa's full "
                                            "checkout (VILLA_DIR) or install lasagna from it"),
    ("No module named", "the lasagna Python lacks a package: run lasagna_status, then villa's "
                        "scripts/bootstrap_venv.py or point LASAGNA_PYTHON at its venv"),
    ("CUDA out of memory", "the fit did not fit in GPU memory: a smaller model (model_h, model_w, depth) or a larger GPU"),
    ("missing required channels", "the manifest lacks a channel fit.py needs (grad_mag, nx, ny; cos for data terms)"),
    ("lasagna-remote.json", "a remote manifest streams over CUDA only; mirror a crop with lasagna_manifest for CPU"),
    ("cylinder_seed missing required stage role", "mode seed defaults to init-mode cylinder_seed, which needs a "
                                                  "cylinder config (init_cyl.json) and the manifest's umbilicus; or "
                                                  "start from a tifxyz with mode ext"),
    ("umbilicus", "this init mode needs the manifest's umbilicus_json: lasagna_manifest with a published (URL) "
                  "source and umbilicus writes one; for a local manifest, put the umbilicus JSON beside it and set "
                  "umbilicus_json to its file name"),
    ("requires exactly one external_surfaces entry", "the fit service takes mode ext's start surface (and flatten's "
                                                     "surface) as overrides.external_surfaces: [{path, offset: 0}]"),
)


def weight(cfg, term):
    """A loss term's weight in a config's base (0 when absent or not a number)."""
    base = cfg.get("base") if isinstance(cfg.get("base"), dict) else {}
    try:
        return float(base.get(term) or 0)
    except (TypeError, ValueError):
        return 0.0


def hints_for(text):
    return [h for key, h in HINTS if key in text]


def tifxyz_dirs(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and (p / "x.tif").is_file())


def surface_tilt(path, axis_from=0, axis_to=1):
    """Least-squares slope of coordinate `axis_to` against `axis_from` over a tifxyz's valid vertices (selftest)."""
    from . import vc3d_io
    grids = [vc3d_io.read_tiff(Path(path) / f"{a}.tif").data for a in "xyz"]
    pts = [p for p in zip(*grids) if not (p[0] == -1 and p[1] == -1 and p[2] == -1)]
    if len(pts) < 3:
        return None
    mf = sum(p[axis_from] for p in pts) / len(pts)
    mt = sum(p[axis_to] for p in pts) / len(pts)
    sff = sum((p[axis_from] - mf) ** 2 for p in pts)
    return sum((p[axis_from] - mf) * (p[axis_to] - mt) for p in pts) / sff if sff else None


def tifxyz_meta(path):
    """A tifxyz's meta.json as villa's volume_scale.read_tifxyz_meta reads it ({} when absent or unreadable)."""
    try:
        meta = json.loads((Path(path) / "meta.json").read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return meta if isinstance(meta, dict) else {}


def shape3(value, name):
    """villa's volume_scale.parse_shape_zyx: None, or three positive integers."""
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise LasagnaError(f"{name} must be a ZYX list of three positive integers")
    try:
        out = [int(v) for v in value]
    except (TypeError, ValueError):
        raise LasagnaError(f"{name} must contain positive integers") from None
    if min(out) <= 0:
        raise LasagnaError(f"{name} must contain positive integers")
    return out


def surface_scale(meta, base_shape_zyx, request_shape_zyx=None, label="tifxyz"):
    """The factor fit.py multiplies a tifxyz's coordinates by before fitting (villa's _tifxyz_scale_to_base and
    volume_scale.coordinate_scale_to_base): from the surface's frame (meta.base_shape_zyx, else the config's
    vc3d_volume_shape_zyx) to the manifest's base_shape_zyx, a power of two; 1 when either frame is unknown."""
    base = shape3(base_shape_zyx, "base_shape_zyx")
    src = shape3(meta.get("base_shape_zyx"), f"{label}.base_shape_zyx") if isinstance(meta, dict) else None
    src = src or shape3(request_shape_zyx, "vc3d_volume_shape_zyx")
    if base is None or src is None:
        return 1.0
    ratios = [b / s for b, s in zip(base, src)]
    if any(abs(r - ratios[0]) / max(abs(ratios[0]), 1e-12) > 0.01 for r in ratios):
        raise LasagnaError(f"{label}.base_shape_zyx {src} is anisotropic relative to base_shape_zyx {base}")
    pow2 = 2.0 ** int(round(math.log2(sum(ratios) / 3.0)))
    if any(abs(r - pow2) / pow2 > 0.01 for r in ratios):
        raise LasagnaError(f"{label}.base_shape_zyx {src} is not a power-of-two ratio to base_shape_zyx {base}")
    return pow2


def box_overlap(bbox, crop):
    """Fraction of a bbox [[x0, y0, z0], [x1, y1, z1]]'s extent on each axis that lies inside a crop, the least."""
    (x0, y0, z0), (x1, y1, z1) = bbox
    cx, cy, cz, w, h, d = crop
    fr = []
    for lo, hi, c0, n in ((x0, x1, cx, w), (y0, y1, cy, h), (z0, z1, cz, d)):
        if hi > lo:
            fr.append(max(0.0, min(hi, c0 + n) - max(lo, c0)) / (hi - lo))
        else:                           # flat on this axis (a plane): inside or not
            fr.append(1.0 if c0 <= lo < c0 + n else 0.0)
    return min(fr)


def tifxyz_bbox(path):
    """[[x0, y0, z0], [x1, y1, z1]] of a tifxyz's valid vertices, from meta.json's bbox or the grids."""
    p = Path(path)
    meta = tifxyz_meta(p)
    bb = meta.get("bbox")
    if isinstance(bb, list) and len(bb) == 2 and all(isinstance(v, list) and len(v) == 3 for v in bb):
        return bb
    from . import vc3d_io
    grids = [vc3d_io.read_tiff(p / f"{a}.tif").data for a in "xyz"]
    pts = [q for q in zip(*grids) if not (q[0] == -1 and q[1] == -1 and q[2] == -1)]
    if not pts:
        return None
    return [[min(q[k] for q in pts) for k in range(3)], [max(q[k] for q in pts) for k in range(3)]]


def crop_around(bbox, margin, base_shape_zyx=None, source_to_base=1.0):
    """(x0, y0, z0, w, h, d) of a bbox grown by margin voxels, clipped to the volume when its shape is known.
    base_shape_zyx is in source voxels (villa's manifest), so the volume is base_shape_zyx x source_to_base base
    voxels."""
    (x0, y0, z0), (x1, y1, z1) = bbox
    lo = [int(math.floor(v - margin)) for v in (x0, y0, z0)]
    hi = [int(math.ceil(v + margin)) + 1 for v in (x1, y1, z1)]
    if base_shape_zyx:
        lim = [int(base_shape_zyx[k] * float(source_to_base)) for k in (2, 1, 0)]
        lo = [max(0, v) for v in lo]
        hi = [min(m, v) for v, m in zip(hi, lim)]
    else:
        lo = [max(0, v) for v in lo]
    if any(h <= l for l, h in zip(lo, hi)):
        raise LasagnaError(f"the box around {bbox} (margin {margin}) lies outside the volume")
    return [lo[0], lo[1], lo[2], hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]]


def plain_name(value, what, out):
    """A folder name fit2tifxyz joins onto its output folder (out_base / name): one plain name, so nothing lands
    outside out (AGENTS.md rule 6 is checked on out only)."""
    name = str(value)
    if (not name or name in (".", "..") or "/" in name or "\\" in name or Path(name).is_absolute()
            or Path(out).resolve() not in (Path(out) / name).resolve().parents):
        raise LasagnaError(f"{what} {value!r} must be one plain folder name (no '/', '\\\\', '.' or '..')")
    return name


# ---------------------------------------------------------------- fit service client

def service_opener(url):
    """No proxy for a service on this machine (the cloud's egress proxy cannot reach it)."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1") or host.startswith("127."):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def service_call(url, method, path, body=None, timeout=60, raw=False):
    """One request to villa's fit service with its API header. JSON reply, or bytes with raw. Errors raise
    LasagnaError with the service's own message."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url.rstrip("/") + path, data=data, method=method,
                                 headers={"X-Fit-Service-API-Version": SERVICE_API, "Content-Type": "application/json",
                                          "X-VC3D-Source": "kit-lasagna"})
    try:
        with service_opener(url).open(req, timeout=timeout) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as exc:
        text = (exc.read() or b"").decode("utf-8", "replace")
        try:
            msg = json.loads(text).get("error", text)
        except (json.JSONDecodeError, AttributeError):
            msg = text
        raise LasagnaError(f"{method} {path}: HTTP {exc.code}: {str(msg)[:500]}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LasagnaError(f"{method} {url}{path}: {getattr(exc, 'reason', exc)} (is the fit service running? "
                           "villa: lasagna-fit-service --port N --data-dir DIR)") from exc
    except http.client.HTTPException as exc:     # a reply cut off part way
        raise LasagnaError(f"{method} {url}{path}: {type(exc).__name__}: {exc}") from exc
    if raw:
        return blob
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        raise LasagnaError(f"{method} {path}: reply is not JSON: {blob[:200]!r}") from exc


def discover_services(home=None):
    """Live fit services from ~/.fit_services/<pid>.json (written by villa's service at start)."""
    folder = Path(home or Path.home()) / ".fit_services"
    out = []
    files = sorted(folder.glob("*.json"), key=lambda f: (f.stat().st_mtime, f.name)) if folder.is_dir() else []
    for f in files:                      # oldest first, so the last live one is the newest
        try:
            info = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pid = info.get("pid")
        alive = False
        if isinstance(pid, int):
            try:
                os.kill(pid, 0)
                alive = True
            except PermissionError:
                alive = True
            except OSError:
                alive = False
        host = str(info.get("host") or "127.0.0.1")
        host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host     # bound to every address: reach it here
        host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        out.append({"url": f"http://{host}:{info.get('port')}", "pid": pid, "alive": alive,
                    "data_dir": info.get("data_dir"), "datasets": info.get("datasets"), "file": str(f)})
    return out


def safe_extract(blob, dest):
    """Unpack a results tar.gz into dest: regular files and folders only, nothing outside dest."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    names = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tar:
        for m in tar.getmembers():
            target = (root / m.name).resolve()
            if not (m.isfile() or m.isdir()) or (target != root and root not in target.parents):
                raise LasagnaError(f"results archive member {m.name!r} is not a plain file inside the folder")
        for m in tar.getmembers():
            target = (root / m.name).resolve()
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as src, open(target, "wb") as fh:
                shutil.copyfileobj(src, fh)
            names.append(m.name)
    return names


# ---------------------------------------------------------------- the tools

def register(agent):
    """Add the lasagna_* tools to kit/vc3d_agent.py (called through kit/vc3d_ext_lasagna.py)."""
    tool, STR, INT, NUM, BOOL, ARR, OBJ = (agent.tool, agent.STR, agent.INT, agent.NUM, agent.BOOL, agent.ARR,
                                           agent.OBJ)
    ToolError = agent.ToolError

    def where(ctx):
        try:
            return find_lasagna(ctx.env)
        except LasagnaError as exc:
            raise ToolError(str(exc)) from exc

    def check_started(rc, argv):
        """run_logged's 'could not start: ...' is a setup problem (exit 2), not a run that failed."""
        if str(rc).startswith("could not start"):
            raise ToolError(f"{argv[0]} {rc}: set LASAGNA_PYTHON to a Python with torch, numpy, zarr and tifffile "
                            f"({GUIDE}, 'Setting up')")

    def guarded(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except LasagnaError as exc:
            raise ToolError(str(exc)) from exc

    def local_input(ctx, path, what):
        p = agent.resolve(ctx, path)
        if not p.exists():
            raise ToolError(f"{what} not found: {p}")
        return p.resolve()

    # ------------------------------------------------------------ status

    @tool("lasagna_status", "Lasagna: where and what",
          "Where villa's lasagna is (LASAGNA_DIR, VILLA_DIR or ~/villa/lasagna) and its commit, the Python that runs "
          "it (LASAGNA_PYTHON) and what it has: torch, numpy, zarr, tifffile, tensorstore, CUDA, MPS, and with "
          "check_import whether `import fit` works. Call it first; lasagna_fit picks its default device from it.",
          {"check_import": BOOL("also import fit.py and fit2tifxyz.py in that Python (slower; catches a missing "
                                "vesuvius/src)")},
          readonly=True)
    def h_status(ctx, a):
        try:
            lasagna, py, villa, how = find_lasagna(ctx.env)
        except LasagnaError as exc:
            return {"found": False, "problem": str(exc), "guide": GUIDE}
        info = probe(ctx.env, py, lasagna, villa, fit=bool(a.get("check_import")))
        configs = sorted(p.name for p in (lasagna / "configs").glob("*.json")) if (lasagna / "configs").is_dir() else []
        out = {"found": True, "lasagna_dir": str(lasagna), "found_by": how, "villa": str(villa) if villa else None,
               "villa_commit": git_head(lasagna), "python": py, "probe": info, "configs": len(configs),
               "shim": str(shim_path()) if (Path(kithome.SOURCE) / "scripts/lasagna/fit_cpu_shim.py").is_file()
               else None}
        if info.get("error"):
            out["problem"] = info["error"]
        elif info.get("missing"):
            out["problem"] = "the lasagna Python lacks " + ", ".join(sorted(info["missing"]))
        if info.get("cuda"):
            out["default_device"] = "cuda"
        else:
            out["default_device"] = "mps" if info.get("mps") else "cpu"
            out["note"] = ("no CUDA: volume fits run through the dense shim on a box (a local or mirrored manifest, "
                           "lasagna_manifest with crop), and the cos 'data' loss term needs CUDA. Real-size GPU fits "
                           "need a CUDA machine: lasagna_fit with dry_run gives the exact command")
        if villa is None or not (villa / "vesuvius" / "src").is_dir():
            out["warning"] = ("no villa/vesuvius/src beside lasagna: fit.py imports vc3d_fiber_format from it unless "
                              "lasagna was installed from a full villa checkout")
        return out

    # ------------------------------------------------------------ configs

    @tool("lasagna_configs", "Lasagna stage configs",
          "villa's shipped fit configs (lasagna/configs/*.json): each one's mode (model-init), init mode, stages and "
          "steps, loss terms, and what it needs (external_surfaces, corr_points, atlas). With name, that config in "
          "full. VC3D picks: New Model init*.json (seed), Re-optimize corr*.json (model), Offset offset.json (model "
          "with external_surfaces), flatten*.json (flatten).",
          {"name": STR("one config's file name (e.g. init_cyl.json) or path: return it in full")},
          readonly=True)
    def h_configs(ctx, a):
        lasagna, _, _, _ = where(ctx)
        if a.get("name"):
            path = guarded(resolve_config, lasagna, a["name"], ctx.root)
            return {"config": guarded(describe_config, path), "json": guarded(load_json, path, "config")}
        rows, bad = [], []
        for p in sorted((lasagna / "configs").glob("*.json")):
            try:
                rows.append(describe_config(p))
            except LasagnaError as exc:
                bad.append({"name": p.name, "problem": str(exc)})
        return {"folder": str(lasagna / "configs"), "configs": rows, "invalid": bad,
                "next": "lasagna_configs name=... for one in full; lasagna_fit config=... to run one"}

    # ------------------------------------------------------------ manifest

    @tool("lasagna_manifest", "Lasagna input manifest",
          "The local .lasagna.json fit.py needs as input. source: a published lasagna run folder or its "
          ".lasagna.json URL (s3:// or https; 22 scrolls have one, under <scroll>/representations/predictions/"
          "lasagna/), or a local .lasagna.json to check. For a URL without crop it writes the manifest plus "
          "VC3D's lasagna-remote.json marker, so fit.py streams the published stores (CUDA only). With crop it "
          "copies just the chunks under that box into a local mirror, which any device can fit (pass the same crop "
          "to lasagna_fit, or let it read kit_crop from the manifest). Returns channels, levels, shapes, spacing "
          "in base voxels and any problem villa would refuse.",
          {"source": STR("published run folder or .lasagna.json URL, or a local .lasagna.json"),
           "crop": ARR("x0, y0, z0, w, h, d in base (level 0) voxels: mirror only this box", {"type": "integer"},
                       minItems=6, maxItems=6),
           "umbilicus": STR("an umbilicus JSON (path or URL, control_points in base voxels) to put beside the "
                            "manifest as umbilicus_json (needed for init-mode cylinder_seed)"),
           "out": STR("folder for the manifest (default under work/vc3d/lasagna/inputs)"),
           "max_chunks": INT(f"refuse a mirror of more chunks than this (default {MAX_CHUNKS})", minimum=1)},
          required=["source"], background=True, openworld=True)
    def h_manifest(ctx, a):
        src = str(a["source"])
        if not agent.is_url(src):
            given = [k for k in ("crop", "umbilicus", "out", "max_chunks") if a.get(k) is not None]
            if given:
                raise ToolError(f"{', '.join(given)} apply to a published (URL) source; a local manifest is only "
                                "checked. Give lasagna_fit its crop; for cylinder_seed put the umbilicus JSON beside "
                                "the manifest and set umbilicus_json to its file name")
            p = local_input(ctx, src, "manifest")
            doc = guarded(load_json, p, "manifest")
            probs = check_manifest_doc(doc)
            remote = (p.parent / MARKER).is_file()
            rows, more = group_rows(doc, {} if remote else local_zarrays(p, doc))
            get = doc.get if isinstance(doc, dict) else (lambda k, d=None: d)
            out = {"manifest": str(p), "mode": "remote" if remote else "local", "groups": rows,
                   "base_shape_zyx": get("base_shape_zyx"), "source_to_base": get("source_to_base", 1.0),
                   "kit_crop": get("kit_crop"), "problems": probs + more, "ok": not (probs or more)}
            if not p.name.endswith(".lasagna.json"):
                out["problems"].append("the file name must end in .lasagna.json (villa refuses others)")
                out["ok"] = False
            if not remote and isinstance(doc, dict) and doc.get("base_shape_zyx") is None:
                out["note"] = "no base_shape_zyx: fit.py takes the extent from the zarr levels"
            umb = get("umbilicus_json")
            out["umbilicus_json"] = umb
            if umb and not remote and not (p.parent / str(umb)).is_file():
                out["problems"].append(f"umbilicus_json {umb!r} is not a file beside the manifest")
                out["ok"] = False
            if not out["ok"]:
                out["exit"] = 1
            return out
        base, name, doc = guarded(remote_manifest, src)
        probs = check_manifest_doc(doc)
        if probs:
            raise ToolError(f"{base}{name}: " + "; ".join(probs))
        stem = name[: -len(".lasagna.json")]
        out_folder = agent.out_dir(ctx, a.get("out"), "lasagna", "inputs",
                                   agent.slug(stem + ("-crop" if a.get("crop") else "-remote")))
        zarrays = {}
        for g, spec in doc["groups"].items():
            try:
                zarrays[g] = fetch_json(f"{base}{spec['zarr']}/.zarray", "level metadata")
            except LasagnaError as exc:
                zarrays[g] = {"error": str(exc)}
            if not isinstance(zarrays[g], dict):
                zarrays[g] = {"error": f"{base}{spec['zarr']}/.zarray is not a JSON object"}
        rows, more = group_rows(doc, zarrays)
        if any(r.get("error") for r in rows):
            raise ToolError("cannot read the level arrays: " + "; ".join(more))
        local = dict(doc)
        steps = []
        if a.get("umbilicus"):
            u = str(a["umbilicus"])
            blob = guarded(fetch, u, "umbilicus") if agent.is_url(u) else local_input(ctx, u, "umbilicus").read_bytes()
            try:
                umb = json.loads(blob)
            except json.JSONDecodeError as exc:
                raise ToolError(f"umbilicus {u} is not JSON: {exc}") from exc
            if not (isinstance(umb, dict) and umb.get("control_points")):
                raise ToolError(f"umbilicus {u} has no control_points (lasagna's format: "
                                "{control_points: [{x, y, z}]} in base voxels)")
            (out_folder / "umbilicus.json").write_text(json.dumps(umb, indent=1) + "\n")
            local["umbilicus_json"] = "umbilicus.json"
        elif doc.get("umbilicus_json"):
            rel = str(doc["umbilicus_json"])
            if rel.startswith("/") or ".." in Path(rel).parts or re.match(r"^[a-z]+://", rel, re.I):
                raise ToolError(f"{base}{name}: umbilicus_json {rel!r} is not a relative path inside the run folder")
            (out_folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (out_folder / rel).write_bytes(guarded(fetch, base + rel, "umbilicus"))
        if a.get("crop"):
            asked = [int(v) for v in a["crop"]]
            if min(asked[3:]) <= 0:
                raise ToolError("crop needs positive w, h and d")
            crop = guarded(snap_crop, asked, doc)
            if crop != asked:
                steps.append({"crop_asked": asked, "crop": crop, "why": "start clipped at 0 and edges on whole voxels "
                              "of the coarsest group, so every channel's crop starts on the same grid in villa's "
                              "load_3d"})
            plan = {}
            for g, spec in doc["groups"].items():
                plan[g] = guarded(chunk_keys, zarrays[g], level_box(crop, level_spacing(doc, spec)))
            n = sum(len(v) for v in plan.values())
            cap = int(a.get("max_chunks") or MAX_CHUNKS)
            if n > cap:
                raise ToolError(f"the crop touches {n} chunks over {len(plan)} groups, over max_chunks {cap}; "
                                "a smaller crop, or raise max_chunks")
            for g, spec in doc["groups"].items():
                rel = str(spec["zarr"])
                level = out_folder / rel
                level.mkdir(parents=True, exist_ok=True)
                (level / ".zarray").write_text(json.dumps(zarrays[g], indent=1) + "\n")
                parent = rel.rsplit("/", 1)[0] if "/" in rel else None
                if parent:
                    for meta in (".zattrs", ".zgroup"):
                        try:
                            (out_folder / parent / meta).write_bytes(fetch(f"{base}{parent}/{meta}", meta))
                        except LasagnaError:
                            pass                     # optional: villa reads the level array itself
                ctx.say(f"lasagna_manifest: {g}: {len(plan[g])} chunks of {rel}")
                try:
                    copied, absent, nbytes = mirror_chunks(base, rel, zarrays[g], plan[g], level)
                except LasagnaError as exc:
                    raise ToolError(f"{exc}; the partial mirror is in {out_folder}: run again with out={out_folder} "
                                    "to resume (copied chunks are kept)") from exc
                steps.append({"group": g, "chunks": len(plan[g]), "copied": copied, "absent_no_data": absent,
                              "bytes": nbytes})
            local["kit_crop"] = crop
            local["kit_mirror_of"] = base + name
            mode = "mirror"
        else:
            (out_folder / MARKER).write_text(json.dumps({"artifact_url": base, "manifest_file": name}, indent=1) + "\n")
            mode = "remote"
        manifest = out_folder / name
        manifest.write_text(json.dumps(local, indent=1) + "\n")
        out = {"manifest": str(manifest), "mode": mode, "source": base + name, "groups": rows,
               "base_shape_zyx": doc.get("base_shape_zyx"), "source_to_base": doc.get("source_to_base", 1.0),
               "kit_crop": local.get("kit_crop"), "umbilicus_json": local.get("umbilicus_json") or None,
               "problems": more, "ok": not more}
        if steps:
            out["mirror"] = [st for st in steps if "group" in st]
            snapped = [st for st in steps if "crop_asked" in st]
            if snapped:
                out["crop_snapped"] = snapped[0]
        if more:
            out["exit"] = 1
        if mode == "remote":
            out["note"] = ("streams the published stores: fit.py needs CUDA for this (lasagna_fit device cuda). For "
                           "CPU or MPS, run again with crop")
        agent.write_receipt(ctx, out_folder, "lasagna_manifest", a, steps, [str(manifest)], agent.now(), mode=mode)
        return out

    # ------------------------------------------------------------ fit

    fit_props = {
        "config": ARR("villa configs to merge, left to right (names in lasagna/configs, e.g. init_cyl.json, or "
                      "paths); kit's own overrides go last", {"type": "string"}, minItems=1),
        "input": STR("the local .lasagna.json (lasagna_manifest writes one); not for mode flatten"),
        "mode": STR("model-init: seed (new model), ext (from tifxyz_init), model (re-optimize model_input), flatten "
                    "(one external surface, no input), atlas; default the config's", enum=list(MODES)),
        "seed": ARR("seed point x, y, z in base voxels (seed mode)", {"type": "number"}, minItems=3, maxItems=3),
        "model_h": NUM("model height in base voxels: seed mode needs it unless corr-point-roi or approval-inpaint "
                       "works it out", minimum=1),
        "model_w": NUM("model width (seed mode), in model_w_unit", minimum=0),
        "model_w_unit": STR("voxels or wraps", enum=["voxels", "wraps"]),
        "depth": INT("windings (model depth)", minimum=1),
        "tifxyz_init": STR("tifxyz to start from (mode ext)"),
        "model_input": STR("checkpoint .pt to start from (mode model)"),
        "external_surfaces": ARR("[{path, offset}] tifxyz references (offset mode: offset +-1 is the next winding; "
                                 "flatten: exactly one)", {"type": "object"}),
        "corr_points": STR("correction points JSON file in VC3D's format ({collections: {...}})"),
        "init_shell_dir": STR("shells for init-mode shell-dir-crop"),
        "voxel_um": NUM("voxel size in um, for areas in the exported tifxyz", minimum=0),
        "args": OBJ("more fit.py arguments, keys as in a config's args (e.g. {\"mesh-step\": 50}); they override the "
                    "configs, and the named arguments here override them"),
        "overrides": OBJ("top-level config keys merged last (e.g. {\"stages\": [...], \"base\": {...}}); lists replace"),
        "device": STR("cuda, cpu or mps (default: cuda when the lasagna Python has it, else mps, else cpu)",
                      enum=list(DEVICES)),
        "crop": ARR("off CUDA: x0, y0, z0, w, h, d in base voxels to load (default: the manifest's kit_crop, else "
                    "the start surface's box plus margin, else the whole volume if small enough)",
                    {"type": "integer"}, minItems=6, maxItems=6),
        "margin": INT("voxels around the start surface for the default crop (default 128)", minimum=0),
        "export": OBJ("also export with fit2tifxyz as VC3D does: {single_segment, output_name, prefix, "
                      "target_volume_shape_zyx, omit_model, out, timeout} as lasagna_export takes them (checked "
                      "before the fit runs); writes out/export"),
        "out": STR("output folder (default under work/vc3d/lasagna/fits)"),
        "timeout": INT("seconds before the fit is stopped (default 3600)", minimum=1),
        "dry_run": BOOL("write the merged config and the command, run nothing (for a GPU machine: with no "
                        "device the command is for CUDA)"),
    }

    def default_device(ctx, lasagna, py, villa):
        info = probe(ctx.env, py, lasagna, villa)
        if info.get("error"):
            raise ToolError(f"cannot ask the lasagna Python which device it has: {info['error']}")
        return "cuda" if info.get("cuda") else ("mps" if info.get("mps") else "cpu")

    PATH_ARGS = (("input", "input"), ("tifxyz_init", "tifxyz-init"), ("model_input", "model-input"),
                 ("init_shell_dir", "init-shell-dir"))

    def manifest_info(path):
        doc = guarded(load_json, path, "manifest")
        remote = (Path(path).parent / MARKER).is_file()
        return doc, remote, ({} if remote else local_zarrays(Path(path), doc))

    EXPORT_KEYS = ("single_segment", "output_name", "prefix", "target_volume_shape_zyx", "omit_model", "out",
                   "timeout")

    def check_export(ctx, exp):
        """lasagna_fit's export, checked before fit.py runs: a bad value must not cost a finished fit its result."""
        if not exp:
            return None
        bad = sorted(set(exp) - set(EXPORT_KEYS))
        if bad:
            raise ToolError(f"export takes {', '.join(EXPORT_KEYS)}, not {', '.join(bad)} (it exports the fit's own "
                            "model_final.pt, with the fit's voxel_um)")
        try:
            agent.validate(agent.TOOLS["lasagna_export"], dict(exp, model="model_final.pt"))
        except ToolError as exc:
            raise ToolError(f"export: {exc}") from exc
        for key, name in (("output_name", exp.get("output_name")),
                          ("prefix", None if exp.get("prefix") is None else f"{exp['prefix']}0000.tifxyz")):
            if name is not None:
                guarded(plain_name, name, f"export.{key}", ctx.home)
        if exp.get("out"):
            agent.writable(ctx, exp["out"])
        return dict(exp)

    def h_fit_impl(ctx, a, name="lasagna_fit"):
        if "args" in (a.get("overrides") or {}):
            raise ToolError("put fit.py arguments in args, not overrides.args")
        exp = check_export(ctx, a.get("export"))
        lasagna, py, villa, _ = where(ctx)
        started = agent.now()
        configs = [guarded(resolve_config, lasagna, c, ctx.root) for c in a.get("config") or []]
        merged = {}
        for c in configs:
            cfg = guarded(load_json, c, "config")
            if not isinstance(cfg, dict):
                raise ToolError(f"config {c} is not a JSON object")
            merged = deep_merge(merged, cfg)
        cargs = merged.get("args") if isinstance(merged.get("args"), dict) else {}
        args = dict(a.get("args") or {})     # kit's overrides args: the caller's, as given, then kit's own fields
        notes = []

        def put(flag, value):
            """Set a fit.py argument so it wins in fit.py's merge: under flag and under every other spelling of it
            in the configs and args (cli_json applies the later of model-init and model_init)."""
            for k in list(cargs) + list(args):
                if arg_key(k) == flag:
                    args[k] = value
            args[flag] = value

        for key, flag in PATH_ARGS:     # paths given here resolve like every kit path (relative to the kit home)
            if a.get(key):
                put(flag, str(local_input(ctx, a[key], key)))
            else:
                for k in list(args):
                    if arg_key(k) == flag and args[k]:
                        args[k] = str(local_input(ctx, args[k], f"args.{k}"))
        if a.get("mode"):
            put("model-init", a["mode"])
        for key, flag in (("seed", "seed"), ("model_h", "model-h"), ("model_w", "model-w"),
                          ("model_w_unit", "model-w-unit"), ("depth", "depth")):
            if a.get(key) is not None:
                put(flag, a[key])
        eff = norm_args(deep_merge(cargs, args))     # the arguments as fit.py will apply them

        mode = str(eff.get("model-init", "seed"))
        if mode not in MODES:
            raise ToolError(f"mode {mode!r} is not one of {', '.join(MODES)}")

        def eff_path(flag):
            """A path argument as fit.py will see it: a config's relative path is relative to villa's lasagna
            folder, where fit.py runs."""
            v = eff.get(flag)
            if not v:
                return None
            q = Path(str(v)).expanduser()
            return q if q.is_absolute() else lasagna / q

        inp = None
        if mode != "flatten":
            inp = eff_path("input")
            if inp is None:
                raise ToolError("input: the local .lasagna.json (lasagna_manifest makes one from a published run)")
            if not inp.name.endswith(".lasagna.json"):
                raise ToolError(f"input {inp} must be named *.lasagna.json (villa refuses others)")
            if not inp.is_file():
                raise ToolError(f"input not found: {inp}")
        need = {"ext": ("tifxyz-init", "tifxyz_init"), "model": ("model-input", "model_input")}.get(mode)
        if need and not eff_path(need[0]):
            raise ToolError(f"mode {mode} needs {need[1]}")
        if mode == "seed":
            missing = [SEED_NEEDS[n][1] for n in seed_needs(eff) if eff.get(SEED_NEEDS[n][0]) in (None, "", [])]
            if missing:
                raise ToolError("mode seed needs " + "; and ".join(missing))

        top = {}
        if a.get("external_surfaces"):
            surfaces = []
            for s in a["external_surfaces"]:
                if not isinstance(s, dict) or not s.get("path"):
                    raise ToolError("external_surfaces items are {path, offset}")
                surfaces.append(dict(s, path=str(local_input(ctx, s["path"], "external surface"))))
            top["external_surfaces"] = surfaces
        if a.get("corr_points"):
            top["corr_points"] = guarded(load_json, local_input(ctx, a["corr_points"], "corr_points"), "corr_points")
        if a.get("voxel_um"):
            top["voxel_size_um"] = float(a["voxel_um"])
        over = deep_merge(dict(a.get("overrides") or {}), top)
        final_top = deep_merge(merged, over)          # top-level keys as fit.py will see them
        surfaces = final_top.get("external_surfaces")
        if mode == "flatten" and not (isinstance(surfaces, list) and len(surfaces) == 1):
            raise ToolError("mode flatten needs exactly one external_surfaces entry (the tifxyz to flatten)")

        device = a.get("device") or str(eff.get("device") or "") or None
        if device is None and a.get("dry_run"):
            device = "cuda"
            notes.append("dry_run with no device: the command is for a CUDA machine; give device "
                         "cpu or mps for a command that runs here")
        elif device is None:
            device = default_device(ctx, lasagna, py, villa)
        if device not in DEVICES:
            raise ToolError(f"device {device!r} is not one of {', '.join(DEVICES)}")
        put("device", device)
        if device != "cuda" and not any(arg_key(k) == "cuda-gridsample" for k in (a.get("args") or {})):
            put("cuda-gridsample", 0)

        env = lasagna_env(ctx.env, lasagna, villa)
        crop = None
        script = lasagna / "fit.py"
        doc = remote = zarrays = None
        gpu_spec = "device cuda with dry_run gives the command for a GPU run spec"
        if inp is not None:
            doc, remote, zarrays = manifest_info(inp)
            probs = check_manifest_doc(doc)
            if probs:
                raise ToolError(f"{inp}: " + "; ".join(probs))
        if device != "cuda":
            script = guarded(shim_path)
            if inp is not None:
                if remote:
                    raise ToolError(f"{inp} streams remote stores ({MARKER}), which needs CUDA: mirror a crop with "
                                    f"lasagna_manifest source=... crop=[...] for device {device}, or {gpu_spec}")
                crop = a.get("crop") or doc.get("kit_crop")
                if crop is not None and not (isinstance(crop, list) and len(crop) == 6
                                             and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                     and math.isfinite(v) for v in crop) and min(crop[3:]) > 0):
                    raise ToolError(f"crop {crop!r} is not x0, y0, z0, w, h, d with positive w, h and d")
                if crop is not None and not a.get("crop"):
                    notes.append(f"crop {crop}: the mirrored box (the manifest's kit_crop)")
                first = surfaces[0] if isinstance(surfaces, list) and surfaces else {}
                start = eff_path("tifxyz-init") if mode == "ext" else (
                    first.get("path") if isinstance(first, dict) and first.get("path") else None)
                if start is not None and not Path(start).is_absolute():
                    start = lasagna / start
                bb = None
                frame = base_frame(doc, zarrays)
                if frame is None:
                    raise ToolError(f"{inp} has no base_shape_zyx and no readable level array, so its frame (and "
                                    "the size of a dense load) is unknown: lasagna_manifest path=... names the problem")
                if doc.get("base_shape_zyx") is None:
                    notes.append(f"the manifest has no base_shape_zyx: its frame is {frame}, the finest level array "
                                 "times 2**scaledown, as fit.py works it out")
                if start is not None and Path(start).is_dir():
                    raw = tifxyz_bbox(start)
                    if raw:
                        f = guarded(surface_scale, tifxyz_meta(start), frame,
                                    final_top.get("vc3d_volume_shape_zyx"), "start surface")
                        bb = [[float(v) * f for v in raw[0]], [float(v) * f for v in raw[1]]]
                        if f != 1.0:
                            notes.append(f"the start surface's coordinates scale by {f:g} into the manifest's frame "
                                         f"(fit.py scales them the same way): its box there is {bb}")
                if crop is None and bb:
                    margin = int(a.get("margin", 128))
                    crop = guarded(crop_around, bb, margin, frame, doc.get("source_to_base", 1.0))
                    notes.append(f"crop {crop}: the start surface's box plus {margin} voxels")
                if crop is not None:
                    snapped = guarded(snap_crop, crop, doc)
                    if snapped != [int(v) for v in crop]:
                        how = "its start clipped at 0 and " if min(crop[:3]) < 0 else ""
                        notes.append(f"crop {snapped}: {list(crop)} with {how}its edges on whole voxels of the "
                                     "coarsest group, so villa's load_3d reads every channel on the same grid")
                    crop = snapped
                    if bb is not None:
                        inside = box_overlap(bb, crop)
                        if inside <= 0:
                            raise ToolError(f"the start surface (box {bb} in the manifest's frame) lies outside "
                                            f"crop {crop}, where fit.py reads no data: give a crop around it")
                        if inside < 1:
                            notes.append(f"part of the start surface lies outside crop {crop} (at least "
                                         f"{inside:.0%} inside on each axis); outside it fit.py reads no data")
                gib = guarded(dense_gib, doc, zarrays, crop)
                if truthy(eff.get("corr-point-roi")):
                    gib += guarded(dense_gib, doc, zarrays, crop, ("cos", "pred_dt"))
                    notes.append("corr-point-roi loads grad_mag, nx and ny a second time (the shim gives that load "
                                 "the same crop); its correction points must lie inside the crop")
                if gib > DENSE_GIB:
                    raise ToolError(f"a dense load of {'the crop' if crop else 'the whole volume'} reads about "
                                    f"{gib:.1f} GiB, over {DENSE_GIB} GiB: give a smaller crop (base voxels), or "
                                    f"{gpu_spec}")
                if crop is not None:
                    env["KIT_LASAGNA_CROP"] = ",".join(str(int(v)) for v in crop)
        out = agent.out_dir(ctx, a.get("out"), "lasagna", "fits", f"{agent.stamp()}-{mode}")
        put("out-dir", str(out))
        put("progress", True)
        overrides = deep_merge(dict(a.get("overrides") or {}), {"args": args, **top})
        cfg_path = out / "kit_overrides.json"
        cfg_path.write_text(json.dumps(overrides, indent=1) + "\n")
        final = deep_merge(merged, overrides)
        (out / "fit_config_merged.json").write_text(json.dumps(final, indent=1) + "\n")

        if device != "cuda" and any(weight(final, t) for t in ("data", "data_plain")):
            notes.append("the config weights the cos 'data' terms, whose kernel is CUDA only: expect a failure "
                         "off CUDA (zero them in overrides.base)")
        argv = [py, str(script), *map(str, configs), str(cfg_path)]
        (out / "command.json").write_text(json.dumps({"argv": argv, "cwd": str(lasagna),
                                                      "env": {k: env[k] for k in ("PYTHONPATH", "KIT_LASAGNA_CROP")
                                                              if k in env}}, indent=1) + "\n")
        res = {"out": str(out), "mode": mode, "device": device, "configs": [str(c) for c in configs],
               "config_merged": str(out / "fit_config_merged.json"), "command": str(out / "command.json"),
               "crop": crop, "villa_commit": git_head(lasagna)}
        if notes:
            res["notes"] = notes
        if a.get("dry_run"):
            res.update(exit=0, dry_run=True, argv=argv,
                       next="run argv from cwd lasagna_dir with that PYTHONPATH (on a CUDA machine for real-size "
                            "fits)")
            return res
        log = out / "fit.log"
        rc, secs = agent.run_logged(ctx, argv, log, env=env, timeout=int(a.get("timeout", 3600)), cwd=str(lasagna))
        check_started(rc, argv)
        text = log.read_text(errors="replace") if log.is_file() else ""
        res.update(exit=rc, seconds=secs, log=str(log), progress=parse_progress(text))
        snaps = (sorted((out / "model_snapshots").glob("*.pt"), key=lambda f: (f.stat().st_mtime_ns, f.name))
                 if (out / "model_snapshots").is_dir() else [])      # by time: stage names do not sort in run order
        res["checkpoints"] = {"count": len(snaps), "last": str(snaps[-1]) if snaps else None,
                              "final": str(out / "model_final.pt") if (out / "model_final.pt").is_file() else None}
        res["tifxyz"] = [agent.tifxyz_stats(p, a.get("voxel_um")) for p in tifxyz_dirs(out / "tifxyz")]
        steps = [{"argv": argv, "exit": rc, "seconds": secs}]
        outputs = [str(p) for p in tifxyz_dirs(out / "tifxyz")] + ([res["checkpoints"]["final"]]
                                                                  if res["checkpoints"]["final"] else [])
        if rc == 0 and exp:
            if not res["checkpoints"]["final"]:
                res["export"] = {"exit": 1, "error": "fit.py wrote no model_final.pt to export"}
            else:
                eout = agent.resolve(ctx, exp["out"]) if exp.get("out") else out / "export"
                inside = Path(out).resolve() in Path(eout).resolve().parents
                try:                    # a failed export keeps the fit's own result and receipt
                    res["export"] = h_export_impl(ctx, {**exp, "model": res["checkpoints"]["final"],
                                                        "out": str(eout), "voxel_um": a.get("voxel_um")},
                                                  receipt=not inside)   # an export folder of its own gets one too
                except (ToolError, LasagnaError) as exc:
                    res["export"] = {"exit": 1, "error": str(exc)}
                except Exception as exc:  # noqa: BLE001 (a bug in the export must not lose a finished fit)
                    res["export"] = {"exit": 1, "error": f"export crashed: {type(exc).__name__}: {exc}"}
            e = res["export"]
            steps.append({"export": e.get("command"), "exit": e.get("exit"), "seconds": e.get("seconds"),
                          **({"error": e["error"]} if e.get("error") else {})})
            outputs += [t["path"] for t in e.get("tifxyz") or [] if isinstance(t, dict) and t.get("path")]
            if e.get("exit") != 0:
                res["exit"] = 1
                res["error"] = "the fit ran, but its export failed: " + str(e.get("error"))
        if rc != 0:
            res["error"] = f"fit.py exited {rc}"
            res["log_tail"] = agent.tail(log, 30)
            hints = hints_for(text)
            if hints:
                res["hints"] = hints
        elif not res["tifxyz"]:
            res["warning"] = "fit.py finished but wrote no tifxyz"
        agent.write_receipt(ctx, out, name, a, steps, outputs, started, villa_commit=res["villa_commit"],
                            device=device, crop=crop)
        return res

    @tool("lasagna_fit", "Lasagna fit",
          "Run villa's fit.py once, headless: villa configs merged left to right, then kit's overrides (input, mode, "
          "seed, model size, start surface or checkpoint, external surfaces, correction points, device, out-dir). "
          "Returns the PROGRESS readout (steps, first, last and lowest loss), checkpoints, and each exported "
          "tifxyz with its stats (grid, valid fraction, bbox, area); on failure the log tail and hints. Off CUDA it "
          "runs through kit's dense shim on a box (crop). dry_run writes the merged config and command only. "
          "Real-size fits need a CUDA machine: dry_run with no device (or device cuda) gives the exact command to "
          "run there.",
          fit_props, background=True)
    def h_fit(ctx, a):
        return h_fit_impl(ctx, a)

    # ------------------------------------------------------------ export

    def h_export_impl(ctx, a, receipt=True):
        lasagna, py, villa, _ = where(ctx)
        started = agent.now()
        model = local_input(ctx, a["model"], "model")
        if a.get("output_name"):
            guarded(plain_name, a["output_name"], "output_name", ctx.home)
        if a.get("prefix"):
            guarded(plain_name, f"{a['prefix']}0000.tifxyz", "prefix", ctx.home)
        out = agent.out_dir(ctx, a.get("out"), "lasagna", "exports", f"{agent.stamp()}-{agent.slug(model.stem)}")
        argv = [py, str(lasagna / "fit2tifxyz.py"), f"--input={model}", f"--output={out}"]
        if a.get("single_segment"):
            argv.append("--single-segment")
        if a.get("output_name"):
            argv.append(f"--output-name={a['output_name']}")
        if a.get("prefix"):
            argv.append(f"--prefix={a['prefix']}")
        if a.get("voxel_um"):
            argv.append(f"--voxel-size-um={float(a['voxel_um'])}")
        if a.get("target_volume_shape_zyx"):
            argv += ["--target-volume-shape-zyx", *map(str, a["target_volume_shape_zyx"])]
        if a.get("omit_model"):
            argv.append("--omit-model")
        log = out / "export.log"
        rc, secs = agent.run_logged(ctx, argv, log, env=lasagna_env(ctx.env, lasagna, villa),
                                    timeout=int(a.get("timeout", 1800)), cwd=str(lasagna))
        check_started(rc, argv)
        res = {"out": str(out), "exit": rc, "seconds": secs, "log": str(log), "command": argv,
               "tifxyz": [agent.tifxyz_stats(p, a.get("voxel_um")) for p in tifxyz_dirs(out)]}
        if rc != 0:
            res["error"] = f"fit2tifxyz.py exited {rc}"
            res["log_tail"] = agent.tail(log, 30)
            hints = hints_for(log.read_text(errors="replace") if log.is_file() else "")
            if hints:
                res["hints"] = hints
        if receipt:
            agent.write_receipt(ctx, out, "lasagna_export", a, [{"argv": argv, "exit": rc, "seconds": secs}],
                                [str(p) for p in tifxyz_dirs(out)], started)
        return res

    @tool("lasagna_export", "Lasagna export to tifxyz",
          "villa's fit2tifxyz.py on a lasagna checkpoint (model_final.pt or a snapshot): one tifxyz per winding, or "
          "one segment with single_segment (what VC3D asks for), named output_name, with area from voxel_um, "
          "rescaled to another pyramid frame with target_volume_shape_zyx. Returns each tifxyz's stats.",
          {"model": STR("lasagna checkpoint .pt"),
           "single_segment": BOOL("one tifxyz for the whole model, as VC3D exports it"),
           "output_name": STR("tifxyz folder name (with single_segment)"),
           "prefix": STR("folder prefix per winding (default winding_)"),
           "voxel_um": NUM("voxel size in um, for the area in meta.json", minimum=0),
           "target_volume_shape_zyx": ARR("Z, Y, X of the volume frame to write coordinates in (a power-of-two "
                                          "level of the lasagna base)", {"type": "integer"}, minItems=3, maxItems=3),
           "omit_model": BOOL("do not copy model.pt into the tifxyz"),
           "out": STR("output folder (default under work/vc3d/lasagna/exports)"),
           "timeout": INT("seconds (default 1800)", minimum=1)},
          required=["model"], background=True)
    def h_export(ctx, a):
        return h_export_impl(ctx, a)

    # ------------------------------------------------------------ selftest

    @tool("lasagna_selftest", "Lasagna self-test",
          "A tiny synthetic fit on CPU through kit's shim, end to end (about a minute): sheets of constant y, a "
          "start plane tilted 0.3 in x. With the normal term the fit must turn the plane to under a quarter of its "
          "tilt; the control (normal term off) must keep over 60 % of it, so the check can fail. Proves the lasagna "
          "Python, villa's fit, the shim, the PROGRESS readout and the tifxyz export work here.",
          {"out": STR("output folder (default under work/vc3d/lasagna/selftest)")},
          background=True)
    def h_selftest(ctx, a):
        lasagna, py, villa, _ = where(ctx)
        out = agent.out_dir(ctx, a.get("out"), "lasagna", "selftest", agent.stamp())
        log = out / "data.log"
        argv = [py, str(guarded(selftest_script)), str(out / "data")]
        rc, _ = agent.run_logged(ctx, argv, log, timeout=600)
        check_started(rc, argv)
        if rc != 0:
            return {"exit": 1, "passed": False, "error": "could not write the synthetic inputs (the lasagna Python "
                                                         "needs numpy, zarr and tifffile)", "log_tail": agent.tail(log, 20)}
        data = out / "data"
        runs = {}
        for arm, cfg in (("fit", "stages.json"), ("control", "stages_control.json")):
            runs[arm] = h_fit_impl(ctx, {"config": [str(data / cfg)], "input": str(data / "vol.lasagna.json"),
                                         "mode": "ext", "tifxyz_init": str(data / "init_tilted.tifxyz"),
                                         "device": "cpu", "out": str(out / arm), "timeout": 900},
                                   name="lasagna_selftest")
        tilt0 = surface_tilt(data / "init_tilted.tifxyz")
        tilts = {}
        for arm, r in runs.items():
            dirs = tifxyz_dirs(Path(r["out"]) / "tifxyz")
            tilts[arm] = surface_tilt(dirs[0]) if r.get("exit") == 0 and dirs else None
        checks = {
            "fits_ran": all(r.get("exit") == 0 for r in runs.values()),
            "progress_complete": all(r.get("progress", {}).get("last_step") == r.get("progress", {}).get("total_steps")
                                     and r.get("progress", {}).get("lines", 0) > 0 for r in runs.values()),
            "fit_turned_plane": tilts.get("fit") is not None and abs(tilts["fit"]) < 0.25 * abs(tilt0),
            "control_kept_tilt": tilts.get("control") is not None and abs(tilts["control"]) > 0.6 * abs(tilt0),
        }
        passed = all(checks.values())
        res = {"exit": 0 if passed else 1, "passed": passed, "checks": checks,
               "tilt": {"start": tilt0, "fit": tilts.get("fit"), "control": tilts.get("control")},
               "runs": {arm: {k: r.get(k) for k in ("exit", "seconds", "progress", "out", "error", "log_tail",
                                                   "hints") if r.get(k) is not None} for arm, r in runs.items()},
               "out": str(out), "villa_commit": git_head(lasagna)}
        (out / "selftest.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
        return res

    # ------------------------------------------------------------ service

    @tool("lasagna_service", "Lasagna fit service client",
          "Talk to villa's lasagna fit service (lasagna-fit-service, the HTTP API VC3D uses), here or on a GPU "
          "machine. actions: discover (services listed in ~/.fit_services), health, datasets, jobs, job (state, "
          "step, loss; wait seconds for it to end), submit (POST /jobs with data_input from datasets, a config, "
          "output_name; returns job_id), cancel, results (download the tar of a finished job and unpack it, with "
          "tifxyz stats). The service runs one job at a time; a temporary result can be downloaded only once.",
          {"action": STR("discover, health, datasets, jobs, job, submit, cancel or results",
                         enum=["discover", "health", "datasets", "jobs", "job", "submit", "cancel", "results"]),
           "url": STR("the service, http://HOST:PORT (default: the newest live one in ~/.fit_services)"),
           "id": STR("job id (job, cancel, results)"),
           "wait": NUM("job: seconds to wait for the job to end (default 0, at most 3600)", minimum=0, maximum=3600),
           "data_input": STR("submit: the dataset path as the service host sees it (from datasets)"),
           "config": STR("submit: a villa config name or path, read here and sent whole"),
           "args": OBJ("submit: fit.py arguments merged into the config's args (seed, model-h, depth, ...)"),
           "overrides": OBJ("submit: top-level config keys merged last (external_surfaces paths are the host's)"),
           "model_input": STR("submit, mode model: the checkpoint .pt as a path on the service's host"),
           "model_file": STR("submit, mode model: a checkpoint .pt here, sent in the request (model_data)"),
           "output_name": STR("submit: result name (default agent.tifxyz)"),
           "single_segment": BOOL("submit: one tifxyz, as VC3D asks (default true)"),
           "body": OBJ("submit: a whole request body instead (data_input, config, job_spec, ...), sent as is"),
           "out": STR("results: folder to unpack into (default under work/vc3d/lasagna/service)")},
          required=["action"], openworld=True)
    def h_service(ctx, a):
        act = a["action"]
        if act == "discover":
            found = discover_services(ctx.env.get("HOME"))
            return {"services": found, "live": [s["url"] for s in found if s["alive"]]}
        url = a.get("url")
        if not url:
            live = [s for s in discover_services(ctx.env.get("HOME")) if s["alive"]]
            if not live:
                raise ToolError("no url and no live service in ~/.fit_services: start villa's lasagna-fit-service "
                                "(--port N --data-dir DIR) and give its url")
            url = live[-1]["url"]
        if act == "health":
            return dict(guarded(service_call, url, "GET", "/health"), url=url)
        if act == "datasets":
            return dict(guarded(service_call, url, "GET", "/datasets"), url=url)
        if act == "jobs":
            return dict(guarded(service_call, url, "GET", "/jobs"), url=url)
        if act in ("job", "cancel", "results") and not a.get("id"):
            raise ToolError(f"{act} needs id")
        if act == "job":
            deadline = time.time() + float(a.get("wait") or 0)
            while True:
                snap = guarded(service_call, url, "GET", f"/jobs/{urllib.parse.quote(a['id'])}")
                if snap.get("state") in TERMINAL or time.time() >= deadline or ctx.cancelled():
                    break
                ctx.say(f"lasagna_service: job {a['id']} {snap.get('state')} {snap.get('stage')} "
                        f"step {snap.get('step')}/{snap.get('total_steps')} loss {snap.get('loss')}")
                time.sleep(min(2.0, max(0.1, deadline - time.time())))
            res = dict(snap, url=url)
            if snap.get("state") in ("error", "cancelled"):
                res["exit"] = 1
                res["hints"] = hints_for(str(snap.get("error") or "")) or None
            return res
        if act == "cancel":
            return dict(guarded(service_call, url, "POST", f"/jobs/{urllib.parse.quote(a['id'])}/cancel", {}),
                        url=url)
        if act == "results":
            blob = guarded(service_call, url, "GET", f"/jobs/{urllib.parse.quote(a['id'])}/results", raw=True,
                           timeout=600)
            out = agent.out_dir(ctx, a.get("out"), "lasagna", "service", f"{agent.stamp()}-{agent.slug(a['id'])}")
            names = guarded(safe_extract, blob, out)
            return {"url": url, "out": str(out), "files": len(names), "bytes": len(blob),
                    "tifxyz": [agent.tifxyz_stats(p) for p in tifxyz_dirs(out)]}
        # submit
        if a.get("body"):
            body = dict(a["body"])
        else:
            if not a.get("config"):
                raise ToolError("submit needs config (or a whole body)")
            lasagna = None
            try:
                lasagna = find_lasagna(ctx.env)[0]
            except LasagnaError:
                pass
            path = agent.resolve(ctx, a["config"])
            if not path.is_file():
                if lasagna is None:
                    raise ToolError(f"config {a['config']} is not a file and villa's configs are not here")
                path = guarded(resolve_config, lasagna, a["config"], ctx.root)
            cfg = guarded(load_json, path, "config")
            if a.get("args"):
                cfg = deep_merge(cfg, {"args": dict(a["args"])})
            if a.get("overrides"):
                cfg = deep_merge(cfg, dict(a["overrides"]))
            cargs = cfg.get("args") if isinstance(cfg.get("args"), dict) else {}
            mode = str(cargs.get("model-init", cargs.get("model_init", "seed")))
            body = {"config": cfg, "config_name": path.name, "output_name": a.get("output_name") or "agent.tifxyz",
                    "single_segment": a.get("single_segment", True)}
            if a.get("data_input"):
                body["data_input"] = a["data_input"]
            elif mode != "flatten":
                raise ToolError("submit needs data_input (a dataset path from action datasets)")
            if a.get("model_file"):
                pt = local_input(ctx, a["model_file"], "model_file")
                body["model_data"] = base64.b64encode(pt.read_bytes()).decode("ascii")
            elif a.get("model_input"):
                body["model_input"] = a["model_input"]
            elif mode == "model":
                raise ToolError("mode model needs the checkpoint: model_file (a .pt here, sent with the request) or "
                                "model_input (a path on the service's host); the service ignores args.model-input")
        reply = guarded(service_call, url, "POST", "/jobs", body)
        return dict(reply, url=url, next=f"lasagna_service action=job id={reply.get('job_id')} wait=600")


# ---------------------------------------------------------------- command line

COMMANDS = ("status", "configs", "manifest", "fit", "export", "selftest", "service")


def _coerce(text, spec):
    """A flag's text as the schema's type: JSON when it parses, comma lists for arrays, true/false for booleans."""
    kind = spec.get("type")
    if kind == "string":
        return text
    if kind == "boolean":
        if text.lower() in ("1", "true", "yes", "on"):
            return True
        if text.lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"not a boolean: {text!r}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if kind == "array":
            items = [t for t in text.split(",") if t != ""]
            item = (spec.get("items") or {}).get("type")
            if item in ("integer", "number"):
                return [int(t) if item == "integer" else float(t) for t in items]
            return items
        raise ValueError(f"not JSON: {text!r}")


def build_parser(p):
    p.add_argument("command", choices=COMMANDS + ("tools",), help="the lasagna_* tool to run, or tools to list them")
    p.add_argument("arguments", nargs="?", default="",
                   help="the tool's arguments as a JSON object, or @file.json (flags below add to it)")
    p.add_argument("--background", action="store_true", help="run as a background job (read it with "
                                                             "python -m kit vc3d call jobs)")
    p.add_argument("--json", action="store_true", help="tools: print each tool's argument schema")
    p.add_argument("rest", nargs=argparse.REMAINDER,
                   help="--key value flags, one per argument (dashes or underscores; arrays as JSON or a,b,c)")
    return p


BOOL_WORDS = ("1", "true", "yes", "on", "0", "false", "no", "off")


def parse_flags(tokens, schema):
    """({key: value}, loose) from ['--key', 'value', '--flag', ...] against a tool's schema. A boolean stands alone
    unless a true/false word follows it. An array flag may repeat (--config a.json --config b.json); each value is a
    JSON list, a JSON item or a comma list. loose holds the tokens found where a flag belonged (the JSON or @file
    arguments, when they come after a flag)."""
    props = schema["properties"]
    out, loose, i = {}, [], 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("--"):
            loose.append(tok)
            i += 1
            continue
        key, eq, inline = tok[2:].partition("=")
        key = key.replace("-", "_")
        if key not in props:
            raise ValueError(f"no argument {key!r}; this tool takes {', '.join(sorted(props))}")
        spec = props[key]
        if eq:
            text = inline
        elif spec.get("type") == "boolean" and (i + 1 >= len(tokens) or tokens[i + 1].lower() not in BOOL_WORDS):
            text = "true"
        else:
            if i + 1 >= len(tokens):
                raise ValueError(f"--{key} needs a value")
            i += 1
            text = tokens[i]
        value = _coerce(text, spec)
        if spec.get("type") == "array":
            value = value if isinstance(value, list) else [value]
            out[key] = out.get(key, []) + value
        elif key in out:
            raise ValueError(f"--{key.replace('_', '-')} given twice")
        else:
            out[key] = value
        i += 1
    return out, loose


def cmd_lasagna(args):
    from . import vc3d_agent
    if args.command == "tools":
        tools = [t for t in vc3d_agent.TOOLS.values() if t.name.startswith("lasagna_")]
        if args.json or "--json" in (args.rest or []) or args.arguments == "--json":
            print(json.dumps([{"name": t.name, "description": t.description, "inputSchema": t.schema()}
                              for t in tools], indent=1))
        else:
            for t in tools:
                print(f"{t.name[len('lasagna_'):]:9s} {t.title}")
            print("\npython -m kit lasagna COMMAND '{...}' or --key value; --json lists the arguments")
        return 0
    name = f"lasagna_{args.command}"
    t = vc3d_agent.TOOLS[name]
    text = args.arguments
    rest = list(args.rest or [])
    if text.startswith("-"):           # no JSON given: the first token is already a flag
        rest, text = [text] + rest, ""
    if "-h" in rest or "--help" in rest:
        print(json.dumps({"name": name, "title": t.title, "description": t.description,
                          "arguments": t.schema()}, indent=1))
        return 0
    try:
        flags, loose = parse_flags(rest, t.schema())
        if loose and not text and len(loose) == 1 and loose[0].lstrip()[:1] in ("{", "@"):
            text = loose.pop()          # the JSON or @file came after a flag
        if loose:
            raise ValueError(f"unexpected {loose[0]!r}: flags are --key value, and the JSON arguments come once")
        if text.startswith("@"):
            text = Path(text[1:]).read_text()
        params = json.loads(text) if text.strip() else {}
        if not isinstance(params, dict):
            raise ValueError("arguments must be a JSON object")
        params.update(flags)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(json.dumps({"error": f"bad arguments: {exc}"}, indent=1))
        return 2
    if args.background:
        params["background"] = True
    ctx = vc3d_agent.Context(progress=lambda m: print(m, file=sys.stderr, flush=True))
    try:
        result = vc3d_agent.call(name, params, ctx)
    except (vc3d_agent.ToolError, LasagnaError) as exc:
        print(json.dumps({"error": str(exc)}, indent=1))
        return 2
    except Exception as exc:  # a bug, not the caller's arguments: still JSON on stdout, the traceback on stderr
        import traceback
        traceback.print_exc()
        print(json.dumps({"error": f"{name} crashed: {type(exc).__name__}: {exc}"}, indent=1))
        return 1
    finally:
        ctx.close()
    result.pop("_images", None)
    print(json.dumps(result, indent=1, default=str))
    return 0 if result.get("exit") in (None, 0) else 1


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="kit lasagna", description=__doc__.split("\n\n")[0]))
    return cmd_lasagna(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
