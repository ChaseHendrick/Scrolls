"""Headless ink detection on one surface volume: the forward map and its controls, for any engine.

The agent tools (kit/vc3d_agent.py, `ink`) run this in the Python that has the model's stack
(KIT_INK_PYTHON); it also runs by hand:

    python scripts/vc3d/ink.py --input RENDER --out DIR --engine villa --checkpoint CKPT.pth
    python scripts/vc3d/ink.py --input RENDER --out DIR --engine torchscript --checkpoint MODEL.pt
    python scripts/vc3d/ink.py --input RENDER --out DIR --engine v8in --model-dir SNAPSHOT
    python scripts/vc3d/ink.py --input RENDER --out DIR --engine command \\
        --command-json '["my-ink", "{input}", "{output}", "--reverse={reverse}"]'

RENDER is a surface volume: a zarr from `vc_render_tifxyz --zarr-output` (an OME-Zarr group whose
level "0" is (layers, height, width)) or a bare zarr array, or a folder of numbered layer TIFFs.
Each engine gets the layout it reads; copies go under DIR/work and are removed at the end.

Engines
  villa        villa's flat inference, `python -m vesuvius.ink_detection.inference.infer`, on a .pth
               checkpoint: ink_9um and its drop-in fine-tunes (Reader v2, d9v2). Forward and reverse
               come from one run (--direction both). CUDA when available, else CPU; villa's flat
               inference has no MPS path, so on a Mac use the torchscript engine.
  torchscript  a TorchScript export of an ink checkpoint, run here by
               scripts/vc3d/torchscript_infer.py: villa's robust normalisation, centre crop of the
               layers to the model depth, Hann blending of 128 px patches. CPU, CUDA or MPS.
  v8in         a snapshot of Youssef Nader's v8in through scripts/v8in_run.py (reads a layer folder;
               uses the central 24 layers).
  command      any program, as an argv list with placeholders {input} (a zarr group, or a layer
               folder when the list contains {layers}), {output} (write a probability map there,
               TIFF or .npy), {reverse} ("1" to read the layers reversed, else "0") and {device}.

Variants (--variants)
  f  forward: the layer order as rendered (the team's order when kit rendered it)
  r  depth reversed: the control a reader of real ink must lose (AGENTS.md rule 4)
  s  depth shuffled: a fixed permutation (kit.layers.depth_permutation, --seed) that is neither the
     stored nor the reversed order; the cleaner null

Writes DIR/ink_<variant>.tif or .npy and DIR/ink.json: each map's statistics as a probability,
inside the rendered surface (where the input's middle layer is nonzero), and the forward map
compared with each control. These are model outputs, not readings: a forward map that keeps its
blobs under reversal or shuffling is responding to something other than ink in depth order.
A run whose maps cannot be read fails (status "failed" in ink.json, its reasons under "failures",
exit 3): a map with one value in every finite pixel (all zero included) or no finite value, a map
with a non-finite pixel on the surface (anywhere when no surface mask has its shape), a map with
one value on the surface, or a forward map identical to a control. A broken GPU run can write
all-zero or NaN maps and exit 0, and such a map would read as "no ink"; a faint map that varies
on the surface, with every surface pixel finite, passes. The log's advice follows the reason: a constant or non-finite map is rerun on
another device or precision; a forward map identical to a control means the engine did not read
the control's input.
Needs numpy; zarr for zarr inputs and conversions; tifffile when installed (else kit.vc3d_io's
standard-library TIFF code); the engine's own stack (torch) to run a model.
"""
from __future__ import annotations

import argparse
import array
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from kit import vc3d_io  # noqa: E402

SEED = 20261007
MAX_STATS = 4_000_000  # pixels sampled for statistics


def log(message):
    print(f"[ink {time.strftime('%H:%M:%S')}] {message}", flush=True)


class InkError(Exception):
    pass


# ---------------------------------------------------------------- volumes

def _zarr():
    try:
        import zarr
    except ImportError as exc:
        raise InkError("zarr is needed to read or write surface volumes in this Python") from exc
    return zarr


def is_layer_dir(path):
    p = Path(path)
    return p.is_dir() and not vc3d_io.is_zarr(p) and bool(vc3d_io.layer_files(p))


def open_stack(path):
    """(layers, height, width) array-like of a zarr (group level "0" or bare array) or a layer folder."""
    p = Path(path)
    if vc3d_io.is_zarr(p):
        node = _zarr().open(str(p), mode="r")
        return node if hasattr(node, "shape") else node["0"]
    files = vc3d_io.layer_files(p)
    if not files:
        raise InkError(f"{p} is neither a zarr nor a folder of numbered layer TIFFs")
    return LayerStack(files)


class LayerStack:
    """A folder of layer TIFFs indexed like a (layers, height, width) array; reads only what it needs."""

    def __init__(self, files):
        self.files = list(files)
        first = read_image(self.files[0])
        self.shape = (len(self.files), *first.shape)
        self.dtype = first.dtype

    def __getitem__(self, key):
        key = key if isinstance(key, tuple) else (key,)
        layers = range(len(self.files))[key[0]]
        rest = key[1:]
        if isinstance(layers, int):
            return read_image(self.files[layers])[rest]
        return np.stack([read_image(self.files[k])[rest] for k in layers])


def read_image(path):
    """A 2-D map or layer as numpy: TIFF (tifffile when installed, else kit.vc3d_io), .npy or PNG."""
    p = Path(path)
    if p.suffix.lower() == ".npy":
        return np.load(p)
    if p.suffix.lower() == ".png":
        from PIL import Image
        return np.asarray(Image.open(p))
    try:
        import tifffile
        return np.squeeze(tifffile.imread(str(p)))
    except ImportError:
        r = vc3d_io.read_tiff(p)
        dtype = {"u8": np.uint8, "i8": np.int8, "u16": np.uint16, "i16": np.int16, "u32": np.uint32,
                 "i32": np.int32, "f32": np.float32, "f64": np.float64}[r.kind]
        return np.frombuffer(bytes(r.data) if r.kind == "u8" else r.data.tobytes(), dtype=dtype).reshape(r.h, r.w)


def write_zarr(dest, data, attrs=None):
    """An OME-Zarr group with level "0" = data (zarr format 2, which every reader here takes)."""
    zarr = _zarr()
    try:
        group = zarr.open_group(str(dest), mode="w", zarr_format=2)
    except TypeError:  # zarr 2
        group = zarr.open_group(str(dest), mode="w")
    chunks = (data.shape[0], min(128, data.shape[1]), min(128, data.shape[2]))
    if hasattr(group, "create_array"):
        try:
            group.create_array("0", data=data, chunks=chunks)
        except TypeError:
            group.create_array("0", shape=data.shape, dtype=data.dtype, chunks=chunks)[...] = data
    else:
        group.create_dataset("0", data=data, chunks=chunks)
    group.attrs["multiscales"] = [{"version": "0.4", "name": "kit-ink",
                                   "axes": [{"name": a, "type": "space"} for a in "zyx"],
                                   "datasets": [{"path": "0"}]}]
    for k, v in (attrs or {}).items():
        group.attrs[k] = v
    return Path(dest)


def write_layers(dest, data):
    """00.tif, 01.tif, ... as kit/layers.py writes them (v8in's input); without tifffile, uncompressed
    through kit.vc3d_io (u8 and u16 as they are, anything else as float32)."""
    try:
        import tifffile
    except ImportError:
        tifffile = None
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(len(data) - 1)))
    for k, layer in enumerate(data):
        path = dest / f"{k:0{width}d}.tif"
        if tifffile is not None:
            tifffile.imwrite(str(path), np.ascontiguousarray(layer))
        else:
            vc3d_io.write_tiff(path, raster(layer))
    return dest


def raster(arr):
    """A 2-D array as a kit.vc3d_io Raster."""
    a = np.asarray(arr)
    if a.dtype == np.uint8:
        return vc3d_io.Raster(a.shape[0], a.shape[1], "u8", np.ascontiguousarray(a).tobytes())
    kind, code, dtype = ("u16", "H", np.uint16) if a.dtype == np.uint16 else ("f32", "f", np.float32)
    data = array.array(code)
    data.frombytes(np.ascontiguousarray(a, dtype=dtype).tobytes())
    return vc3d_io.Raster(a.shape[0], a.shape[1], kind, data)


def window(shape, layer_start=None, layer_end=None, box=None):
    n, h, w = shape
    a = 0 if layer_start is None else int(layer_start)
    b = n if layer_end is None else int(layer_end)
    if not 0 <= a < b <= n:
        raise InkError(f"layer window [{a}, {b}) is outside the {n} layers")
    r0, r1, c0, c1 = box if box else (0, h, 0, w)
    if not (0 <= r0 < r1 <= h and 0 <= c0 < c1 <= w):
        raise InkError(f"box {list(box)} is outside the {h} x {w} surface")
    return a, b, (r0, r1, c0, c1)


def read_window(stack, a, b, box):
    r0, r1, c0, c1 = box
    return np.asarray(stack[a:b, r0:r1, c0:c1])


def depth_permutation(n, seed):
    from kit.layers import depth_permutation as perm
    return perm(n, seed)


# ---------------------------------------------------------------- engines

def probability(arr):
    """A map as float32 probability: uint8 / 255, uint16 / 65535, floats as they are."""
    a = np.asarray(arr)
    if a.ndim == 3:
        a = a[0] if a.shape[0] == 1 else a.squeeze()
    if a.dtype == np.uint8:
        return a.astype(np.float32) / 255.0
    if a.dtype == np.uint16:
        return a.astype(np.float32) / 65535.0
    return a.astype(np.float32)


class Engine:
    """One model. run(path, variants, out) writes ink_<v> maps for variants in f, r, read from `path`,
    which is in the engine's layout ("zarr" or "layers")."""

    layout = "zarr"

    def __init__(self, args):
        self.args = args
        self.device = args.device

    def env(self):
        env = dict(os.environ)
        n = str(self.args.threads)
        env.update(OMP_NUM_THREADS=n, MKL_NUM_THREADS=n, OPENBLAS_NUM_THREADS="1")
        if self.device == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = ""
        return env

    def call(self, argv):
        argv = [str(a) for a in argv]
        log("$ " + " ".join(argv))
        sys.stdout.flush()
        rc = subprocess.run(argv, env=self.env(), stderr=subprocess.STDOUT).returncode  # output joins ours
        if rc != 0:
            raise InkError(f"the {self.name} engine exited {rc}: {' '.join(argv[:4])} ...")

    def describe(self):
        return {"engine": self.name, "device": self.device}

    def predict(self, stack, variant="f"):
        """Probability map of an in-memory (layers, height, width) stack."""
        with tempfile.TemporaryDirectory(prefix="kit-ink-") as tmp:
            tmp = Path(tmp)
            src = write_zarr(tmp / "in.zarr", stack) if self.layout == "zarr" else write_layers(tmp / "in", stack)
            maps = self.run(src, [variant], tmp / "out")
            return probability(read_image(maps[variant]))


class Villa(Engine):
    name = "villa"

    def __init__(self, args):
        super().__init__(args)
        if self.device.startswith("mps"):
            raise InkError("villa's flat inference has no MPS path; use the torchscript engine on a Mac "
                           "(a TorchScript export of the checkpoint)")
        if importlib.util.find_spec("vesuvius") is None:
            raise InkError(f"the vesuvius package (villa) is not importable in {sys.executable}; install villa's "
                           "vesuvius or point KIT_INK_PYTHON at its environment")
        self.checkpoint = Path(args.checkpoint)

    def run(self, path, variants, out):
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        want = set(variants)
        direction = "both" if want == {"f", "r"} else "forward" if want == {"f"} else "reverse"
        target = out / "ink_f.tif" if "f" in want else out / "ink_r.tif"
        argv = [sys.executable, "-m", "vesuvius.ink_detection.inference.infer", path, self.checkpoint, target,
                "--direction", direction, "--batch-size", self.args.batch or 4, "--no-compile",
                "--num-workers", min(4, self.args.threads)]
        if self.args.stride:
            argv += ["--stride", self.args.stride]
        if self.device.startswith("cuda:"):
            argv += ["--gpus", self.device.split(":", 1)[1]]
        self.call(argv)
        maps = {}
        if direction == "both":
            (out / "ink_f_reverse.tif").replace(out / "ink_r.tif")
            maps = {"f": out / "ink_f.tif", "r": out / "ink_r.tif"}
        else:
            maps[variants[0]] = target
        return maps


class TorchScript(Engine):
    name = "torchscript"

    def __init__(self, args):
        super().__init__(args)
        spec = importlib.util.spec_from_file_location("torchscript_infer", ROOT / "scripts" / "vc3d" / "torchscript_infer.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.checkpoint = Path(args.checkpoint)

    def run(self, path, variants, out):
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        arr = open_stack(path)
        n, h, w = arr.shape
        maps = {}
        for v in variants:
            dest = out / f"ink_{v}.npy"
            self.mod.run(str(path), str(self.checkpoint), str(dest), (0, h, 0, w), (0, n), v,
                         stride=self.args.stride or 96, batch=self.args.batch or 16, device=self.device,
                         threads=self.args.threads, seed=self.args.seed, log_every=0)
            maps[v] = dest
        return maps


class V8in(Engine):
    name = "v8in"
    layout = "layers"

    def __init__(self, args):
        super().__init__(args)
        self.model_dir = Path(args.model_dir)

    def run(self, path, variants, out):
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        maps = {}
        for v in variants:
            dest = out / f"ink_{v}.npy"
            argv = [sys.executable, ROOT / "scripts" / "v8in_run.py", "--model-dir", self.model_dir, "--layers", path,
                    "--output", dest, "--device", self.device, "--batch-size", self.args.batch or 16,
                    "--workers", min(4, self.args.threads)]
            if self.args.stride:
                argv += ["--stride", self.args.stride]
            if v == "r":
                argv += ["--reverse"]
            self.call(argv)
            maps[v] = dest
        return maps


class Command(Engine):
    name = "command"

    def __init__(self, args):
        super().__init__(args)
        self.template = json.loads(args.command_json)
        if not isinstance(self.template, list) or not self.template:
            raise InkError("--command-json must be a JSON list of arguments")
        self.layout = "layers" if any("{layers}" in str(t) for t in self.template) else "zarr"

    def run(self, path, variants, out):
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        maps = {}
        for v in variants:
            dest = out / f"ink_{v}.tif"
            values = {"input": str(path), "layers": str(path), "output": str(dest), "reverse": "1" if v == "r" else "0",
                      "device": self.device}
            argv = [str(t).format(**values) for t in self.template]
            self.call(argv)
            if not dest.is_file():
                npy = dest.with_suffix(".npy")
                if npy.is_file():
                    dest = npy
                else:
                    raise InkError(f"{argv[0]} wrote nothing at {dest}")
            maps[v] = dest
        return maps


ENGINES = {"villa": Villa, "torchscript": TorchScript, "v8in": V8in, "command": Command}


def make_engine(args):
    if args.engine in ("villa", "torchscript") and not args.checkpoint:
        raise InkError(f"engine {args.engine} needs --checkpoint")
    if args.engine == "v8in" and not args.model_dir:
        raise InkError("engine v8in needs --model-dir")
    if args.engine == "command" and not args.command_json:
        raise InkError("engine command needs --command-json")
    return ENGINES[args.engine](args)


# ---------------------------------------------------------------- inputs in each engine's layout

def prepare(engine, src, a, b, box, work, shuffle_seed=None):
    """The input in the engine's layout, windowed and boxed (and depth-shuffled when asked).
    Returns (path, info). The original is used as it is when nothing has to change."""
    stack = open_stack(src)
    n, h, w = stack.shape
    whole = (a, b) == (0, n) and box == (0, h, 0, w)
    layout_ok = (engine.layout == "layers" and is_layer_dir(src)) or (
        engine.layout == "zarr" and vc3d_io.is_zarr(src) and (engine.name != "torchscript" or _is_group(src)))
    info = {"layers": [a, b], "box": list(box)}
    if whole and layout_ok and shuffle_seed is None:
        return Path(src), info
    order = depth_permutation(b - a, shuffle_seed) if shuffle_seed is not None else None
    if order is not None:
        info.update(shuffle_seed=shuffle_seed, order=[int(i) + a for i in order])
    name = "shuffled" if order is not None else "input"
    if engine.layout == "layers" and not is_layer_dir(src):
        from kit.layers import export_layers  # zarr to layer TIFFs in row bands, as kit layers does
        dest = Path(work) / name
        export_layers(stack, dest, start=a, count=b - a, crop=box, order=order)
        return dest, info
    data = read_window(stack, a, b, box)
    if order is not None:
        data = data[order]
    if engine.layout == "layers":
        return write_layers(Path(work) / name, data), info
    return write_zarr(Path(work) / f"{name}.zarr", data, {"kit_ink_window": info}), info


def _is_group(path):
    p = Path(path)
    return (p / ".zgroup").is_file() or ((p / "zarr.json").is_file() and
                                         json.loads((p / "zarr.json").read_text()).get("node_type") == "group")


# ---------------------------------------------------------------- statistics

def surface_mask(src, a, b, box):
    stack = open_stack(src)
    r0, r1, c0, c1 = box
    return np.asarray(stack[(a + b) // 2, r0:r1, c0:c1]) > 0


def _sample(values):
    step = max(1, values.size // MAX_STATS)
    return values[::step]


def map_stats(prob, mask, threshold=0.5):
    inside = prob[mask] if mask is not None and mask.shape == prob.shape else prob.ravel()
    v = _sample(inside.astype(np.float32))
    if v.size == 0:
        return {"pixels": 0}
    return {"shape": list(prob.shape), "pixels": int(inside.size), "masked": mask is not None and mask.shape == prob.shape,
            "mean": round(float(v.mean()), 5), "p50": round(float(np.percentile(v, 50)), 5),
            "p99": round(float(np.percentile(v, 99)), 5), "above_threshold": round(float((v > threshold).mean()), 6),
            "threshold": threshold}


def compare(fwd, ctl, mask, threshold=0.5):
    """Forward against one control: how much ink each reports, and whether they report the same pixels."""
    if fwd.shape != ctl.shape:
        return {"error": f"shapes differ {list(fwd.shape)} vs {list(ctl.shape)}"}
    sel = mask if mask is not None and mask.shape == fwd.shape else np.ones(fwd.shape, bool)
    f, c = _sample(fwd[sel]), _sample(ctl[sel])
    fa, ca = f > threshold, c > threshold
    union = int((fa | ca).sum())
    r = None
    if f.std() > 1e-6 and c.std() > 1e-6:
        r = round(float(np.corrcoef(f, c)[0, 1]), 4)
    return {"above_threshold": {"forward": round(float(fa.mean()), 6), "control": round(float(ca.mean()), 6)},
            "forward_minus_control": round(float(fa.mean() - ca.mean()), 6),
            "overlap_iou": round(float((fa & ca).sum()) / union, 4) if union else None,
            "pearson_r": r, "mean": {"forward": round(float(f.mean()), 5), "control": round(float(c.mean()), 5)}}


# ---------------------------------------------------------------- unreadable maps

NAMES = {"f": "forward map", "r": "reversed control", "s": "shuffled control"}


class UnreadableMaps(InkError):
    """The engine wrote maps that cannot be read (ink.json has status "failed"); main exits 3."""

    def __init__(self, message, summary):
        super().__init__(message)
        self.summary = summary


def constant(prob, where=""):
    """Why a map holds nothing to read, or None: no finite value, or one value in every finite pixel (all zero
    included). where names the part checked (" on the surface"). A genuinely faint map still varies, however little,
    and passes."""
    a = np.asarray(prob)
    finite = np.isfinite(a)
    if not finite.any():
        return f"holds no finite value{where}"
    v = a if finite.all() else a[finite]
    lo, hi = float(v.min()), float(v.max())
    if lo != hi:
        return None
    return f"is constant{where}: every {'pixel' if v is a else 'finite pixel'} is {lo:g}"


IDENTICAL = "forward map is identical to the "


def unreadable(probs, mask=None):
    """Reasons a run's maps cannot be read: a map that is constant, a map with a non-finite pixel on the surface (where
    mask is True; anywhere when mask is None or of another shape), a map with one value on the surface (a mask of at
    least 2 pixels), or a forward map identical to a control. A broken GPU run can write all-zero or NaN maps and exit
    0, and such a map would read as "no ink"; a dead network can write one value on the surface and 0 off it, where
    tiled inference skips the empty patches."""
    reasons, fwd = [], probs.get("f")
    for v in (v for v in "frs" if v in probs):
        prob, name = probs[v], NAMES[v]
        on = mask is not None and mask.shape == prob.shape
        why = constant(prob)
        if why:
            reasons.append(f"{name} {why}")
        else:
            inside = prob[mask] if on else np.asarray(prob).ravel()
            bad = int(inside.size - np.count_nonzero(np.isfinite(inside)))
            if bad:
                reasons.append(f"{name} has {bad} non-finite pixel{'s' if bad != 1 else ''} "
                               f"{'on the surface' if on else 'in the map'}")
            elif on and inside.size >= 2:
                why = constant(inside, " on the surface")
                if why:
                    reasons.append(f"{name} {why}")
        if v != "f" and fwd is not None and prob.shape == fwd.shape and np.array_equal(prob, fwd, equal_nan=True):
            reasons.append(IDENTICAL + name)
    return reasons


def advice(failures):
    """What to do about a failed run, by reason. A constant or non-finite map is what a broken device or precision
    writes; a forward map identical to a control means the control's input never reached the engine, and another
    device will not change that."""
    tips = []
    if any(not r.startswith(IDENTICAL) for r in failures):
        tips.append("A broken GPU run can write such maps and exit 0; this is not a null result, so rerun on another "
                    "device or precision before reading anything.")
    if any(r.startswith(IDENTICAL) for r in failures):
        tips.append("A forward map identical to a control means the engine did not read the control's input (check "
                    "{reverse}, the layer window and the shuffled copy); this is not a null result, so fix that "
                    "before reading anything.")
    return " ".join(tips)


# ---------------------------------------------------------------- main

def run(args):
    started = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    variants = [v for v in args.variants.split(",") if v]
    bad = sorted(set(variants) - {"f", "r", "s"})
    if bad:
        raise InkError(f"unknown variants {bad}; use f, r, s")
    engine = make_engine(args)
    stack = open_stack(args.input)
    box = tuple(int(v) for v in args.box.split(",")) if args.box else None
    a, b, box = window(stack.shape, args.layer_start, args.layer_end, box)
    log(f"input {args.input}: {list(stack.shape)} layers x rows x cols; window layers [{a}, {b}), box {list(box)}; "
        f"engine {engine.name} on {engine.device}")
    maps, notes = {}, {}
    try:
        direct = [v for v in variants if v in ("f", "r")]
        if direct:
            path, info = prepare(engine, args.input, a, b, box, work)
            notes["input"] = {"path": str(path), **info}
            maps.update(engine.run(path, direct, out))
        if "s" in variants:
            path, info = prepare(engine, args.input, a, b, box, work, shuffle_seed=args.seed)
            notes["shuffled"] = {"path": str(path), **info}
            got = engine.run(path, ["f"], work / "shuffled-out")
            dest = out / f"ink_s{Path(got['f']).suffix}"
            Path(got["f"]).replace(dest)
            maps["s"] = dest
    finally:
        if not args.keep_work and work.exists():
            shutil.rmtree(work, ignore_errors=True)
    mask = surface_mask(args.input, a, b, box)
    probs = {v: probability(read_image(p)) for v, p in maps.items()}
    failures = unreadable(probs, mask)
    summary = {"engine": engine.describe(), "input": str(args.input), "window": {"layers": [a, b], "box": list(box)},
               "variants": variants, "seed": args.seed, "prepared": notes,
               "status": "failed" if failures else "ok", "failures": failures,
               "maps": {v: {"path": str(maps[v]), "stats": map_stats(probs[v], mask)} for v in maps},
               "comparison": {v: compare(probs["f"], probs[v], mask) for v in probs if v != "f" and "f" in probs},
               "seconds": round(time.time() - started, 1),
               "note": "model output, not a reading; a forward map that keeps its blobs under the controls is "
                       "not responding to ink in depth order"}
    (out / "ink.json").write_text(json.dumps(summary, indent=1))
    log(f"done in {summary['seconds']} s: " + ", ".join(
        f"{v} above 0.5: {summary['maps'][v]['stats'].get('above_threshold')}" for v in maps))
    if failures:
        raise UnreadableMaps("the maps cannot be read (status failed in ink.json): " + "; ".join(failures) + ". " +
                             advice(failures), summary)
    return summary


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="surface volume: zarr or layer folder")
    p.add_argument("--out", required=True, help="output folder")
    p.add_argument("--variants", default="f,r", help="comma list of f, r, s (default f,r)")
    p.add_argument("--engine", required=True, choices=sorted(ENGINES))
    p.add_argument("--checkpoint", help="villa .pth or TorchScript .pt")
    p.add_argument("--model-dir", help="v8in snapshot")
    p.add_argument("--command-json", help="command engine: JSON argv with {input} or {layers}, {output}, "
                   "{reverse} and {device}")
    p.add_argument("--device", default="cpu", help="cpu, cuda, cuda:N or mps")
    p.add_argument("--batch", type=int)
    p.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    p.add_argument("--layer-start", type=int)
    p.add_argument("--layer-end", type=int)
    p.add_argument("--box", help="r0,r1,c0,c1 in pixels")
    p.add_argument("--stride", type=int)
    p.add_argument("--seed", type=int, default=SEED, help="depth-shuffle seed")
    p.add_argument("--keep-work", action="store_true", help="keep the converted inputs under OUT/work")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        run(args)
    except UnreadableMaps as exc:
        log(f"error: {exc}")
        return 3
    except InkError as exc:
        log(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
