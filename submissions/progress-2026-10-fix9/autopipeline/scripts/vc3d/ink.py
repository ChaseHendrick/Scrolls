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
               checkpoint: ink_9um and its drop-in fine-tunes (Reader v2, d9v2), run through
               scripts/vc3d/villa_infer.py, which loads the checkpoint weights-only (villa's own loader
               would run any pickle code in it) and, with --checkpoint-sha256, checks the bytes it loads
               against that hash. Forward and reverse come from one run (--direction both). CUDA when
               available, else CPU; villa's flat inference has no MPS path, so on a Mac use the
               torchscript engine.
  torchscript  a TorchScript export of an ink checkpoint (load only exports from a source you trust:
               TorchScript is code; --checkpoint-sha256 is checked before the load), run here by
               scripts/vc3d/torchscript_infer.py: villa's robust normalization, center crop of the
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
     stored nor the reversed order; often, not always, a cleaner null than r (report the seed; docs/tricks.md)

Villa's names (--villa-names SEGDIR)
  The forward map and the reversed control go into SEGDIR/preds/ under the names villa's folder inference gives its
  own predictions, <seg>_<model>_forward_<ddmmyy>.tif and <seg>_<model>_reverse_<ddmmyy>.tif, as uint8 0 to 255,
  tiled, LZW, Big TIFF (villa main 8aa507c12, vesuvius/src/vesuvius/ink_detection/inference/infer.py:791-834 and
  1211-1213, 1223-1247), so villa's merge_predictions takes each by its direction and villa's folder inference counts
  the segment as done for that model. <model> is the checkpoint's stem, as villa names it (--villa-model to choose
  another; required for the command engine). The villa engine's own file is moved in byte for byte; a map in any other
  form (v8in's float32 .npy, TorchScript's .npy, a command's TIFF) goes through kit.villafmt's `preds export`, which
  encodes it as villa's inference does (clipped to 0 to 1, times 255, truncated). The forward map is then registered
  in SEGDIR/ink-detections.json, the record VC3D's Ink Detection overlay lists (apps/VC3D/OpenDataSegmentCache.cpp:
  651-694, 2022-2063), when SEGDIR is a tifxyz segment. That overlay opens a map with cv::imread, which cannot read a
  .npy, and shows a uint8 map as stored but stretches any other depth from its own minimum to maximum
  (overlays/InkDetectionOverlayController.cpp:106-137, 518). The controls are never registered, and the shuffled map
  stays in DIR: villa has no name for it. ink.json keeps every variant under its key (f, r, s) with the path of the
  file written, so a reader of ink.json["maps"] finds villa's files. Statistics and the unreadable-map test then read
  the uint8 maps, and a map that holds nothing once encoded is refused like any unreadable map. Refused before the
  model runs: a --box crop (villa and VC3D take one image per segment), a render whose size does not fit SEGDIR (the
  tifxyz canvas's aspect within 2 percent, the exact size of a surface zarr there, and the size of the predictions of
  the same direction already in preds/, since villa's merge stops on a shape mismatch), a name villa's merge would
  read as the other direction, and a prediction already at the name (--villa-overwrite replaces it). Unreadable maps
  are never written to preds/.

Writes DIR/ink_<variant>.tif or .npy and DIR/ink.json: each map's statistics as a probability,
inside the rendered surface (where the input's middle layer is nonzero), the forward map
compared with each control, and, with f and r, kit dirtrend's direction readout (the forward over
reversed area ratio at rising thresholds and its trend, counted where the input has CT in every
layer of the window; Community report, freek_cool, 2026-08-31). These are model outputs, not readings: a forward map that keeps its
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
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
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


def check_checkpoint(path, want):
    """Refuse a checkpoint whose sha256 is not want (when want is given)."""
    if not want:
        return
    got = _sha256(path)
    if got != want.strip().lower():
        raise InkError(f"{path}: sha256 {got}, expected {want}; refusing to load it")


def _sha256(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


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
    """A 2-D map or layer as numpy: TIFF (tifffile when installed, else kit.vc3d_io; an LZW TIFF such as villa's
    predictions through kit.villafmt's decoder when tifffile has no imagecodecs), .npy or PNG."""
    p = Path(path)
    if p.suffix.lower() == ".npy":
        return np.load(p)
    if p.suffix.lower() == ".png":
        from PIL import Image
        return np.asarray(Image.open(p))
    try:
        import tifffile
    except ImportError:
        tifffile = None
    if tifffile is not None:
        try:
            return np.squeeze(tifffile.imread(str(p)))
        except ValueError:      # an LZW TIFF, villa's prediction encoding, when tifffile has no imagecodecs
            vf = _villafmt()
            info = vf.tiff_info(p)
            if info["compression"] != 5:
                raise
            return vf.read_lzw_pixels(p, info)
    else:
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


# The device line an engine prints ("Using MPS device", villa's inference), or "Using device: cuda"
DEVICE_LINE = re.compile(rb"\bUsing (?:device:? *([A-Za-z]+(?::\d+)?)\b|([A-Za-z]+(?::\d+)?) device\b)")


def reported_device(text):
    """The last device an engine's output says it used, lower case, or None."""
    found = None
    for m in DEVICE_LINE.finditer(text):
        found = (m.group(1) or m.group(2)).decode().lower()
    return found


class Engine:
    """One model. run(path, variants, out) writes ink_<v> maps for variants in f, r, read from `path`,
    which is in the engine's layout ("zarr" or "layers")."""

    layout = "zarr"

    def __init__(self, args):
        self.args = args
        self.device = args.device
        self.device_reported = None     # what the engine says it used: villa can take MPS on a Mac when asked cpu

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
        # the output joins ours as it comes (progress bars included), and its device line is kept
        echo = getattr(sys.stdout, "buffer", None)
        seen = b""
        with subprocess.Popen(argv, env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
            for chunk in iter(lambda: proc.stdout.read1(65536), b""):
                if echo is not None:
                    echo.write(chunk)
                    echo.flush()
                else:
                    sys.stdout.write(chunk.decode(errors="replace"))
                seen = (seen + chunk)[-4096:]
                self.device_reported = reported_device(seen) or self.device_reported
            rc = proc.wait()
        if rc != 0:
            raise InkError(f"the {self.name} engine exited {rc}: {' '.join(argv[:4])} ...")

    def describe(self):
        """The device asked for and the one the engine's output named (None when it named none)."""
        return {"engine": self.name, "device": self.device, "device_reported": self.device_reported}

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
        safe = [ROOT / "scripts" / "vc3d" / "villa_infer.py"]   # villa's infer, with a weights-only load
        pin = getattr(self.args, "checkpoint_sha256", None)
        if pin:
            safe += ["--sha256", pin]
        argv = [sys.executable, *safe, path, self.checkpoint, target,
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
        self.loaded = None              # the model is loaded once, then kept for every variant and stack

    def run(self, path, variants, out):
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        arr = open_stack(path)
        n, h, w = arr.shape
        if self.loaded is None:
            check_checkpoint(self.checkpoint, getattr(self.args, "checkpoint_sha256", None))
            self.loaded = self.mod.load_model(str(self.checkpoint))
        maps = {}
        for v in variants:
            dest = out / f"ink_{v}.npy"
            self.mod.run(str(path), str(self.checkpoint), str(dest), (0, h, 0, w), (0, n), v,
                         stride=self.args.stride or 96, batch=self.args.batch or 16, device=self.device,
                         threads=self.args.threads, seed=self.args.seed, log_every=0, loaded=self.loaded)
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
        shutil.rmtree(dest, ignore_errors=True)  # this run's own copy from an earlier --keep-work run; kit layers
        export_layers(stack, dest, start=a, count=b - a, crop=box, order=order)  # refuses to write over one
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


def direction(probs, src, a, b, box):
    """kit dirtrend's readout of the forward map against the reversed control, or None without both. Counted where
    the input has CT in every layer of [a, b); coverage is over the whole box, so mesh-free corners count against
    it (the safe side for a blank call). It never fails a run whose maps are readable."""
    if "f" not in probs or "r" not in probs or probs["f"].shape != probs["r"].shape:
        return None
    import kit.dirtrend as dirtrend   # this spelling lets the release cut find the module
    from kit.verify import VerifyError
    try:
        ct = dirtrend.ct_columns(np, open_stack(src), box=box, layers=(a, b))
        res = dirtrend.readout(probs["f"], probs["r"], ct=ct if ct.shape == probs["f"].shape else None)
    except (VerifyError, ValueError, OSError) as exc:
        return {"error": str(exc)}
    keys = ("call", "basis", "meaning", "ct_coverage", "coverage_of", "pixels", "pearson_r", "slope", "gain",
            "aa_check", "rows", "thresholds", "min_pixels", "min_gain", "warning")
    return {k: res[k] for k in keys if k in res}


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
ENCODED = " once encoded as villa's uint8 prediction"     # --villa-names: a map that holds nothing in 0 to 255


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
    rest = [r for r in failures if not r.endswith(ENCODED)]
    if any(not r.startswith(IDENTICAL) for r in rest):
        tips.append("A broken GPU run can write such maps and exit 0; this is not a null result, so rerun on another "
                    "device or precision before reading anything.")
    if any(r.startswith(IDENTICAL) for r in rest):
        tips.append("A forward map identical to a control means the engine did not read the control's input (check "
                    "{reverse}, the layer window and the shuffled copy); this is not a null result, so fix that "
                    "before reading anything.")
    if len(rest) < len(failures):
        tips.append("villa's uint8 encoding (clipped to 0 to 1, times 255, truncated) leaves the map with nothing to "
                    "read, so nothing was written to preds/; the engine's own map is still in the output folder. "
                    "Check the model's output scale before reading anything.")
    return " ".join(tips)


# ---------------------------------------------------------------- villa's names (--villa-names SEGDIR)

VILLA_DIRECTIONS = {"f": "forward", "r": "reverse"}   # the variants villa has a name for; s stays in OUT


def _villafmt():
    from kit import villafmt   # this spelling lets the release cut find the module
    return villafmt


def villa_model(args):
    """The model name in villa's file names: --villa-model, else the checkpoint's stem as villa's folder inference
    takes it (infer.py:1211), else the v8in snapshot folder's name."""
    if args.villa_model:
        return args.villa_model
    if args.engine in ("villa", "torchscript"):
        return Path(args.checkpoint).stem          # villa: Path(checkpoint).stem, any suffix
    if args.engine == "v8in":
        return Path(os.path.abspath(args.model_dir)).name
    raise InkError("--villa-names with the command engine needs --villa-model NAME: the model's name in villa's "
                   "prediction file names")


def villa_plan(args, shape, variants, box):
    """Everything --villa-names will write, checked before the model runs (InkError on a refusal): the folder, the
    names and their directions, a crop, the render's size against SEGDIR's tifxyz canvas, its surface zarr and the
    predictions already in preds/."""
    vf = _villafmt()
    segdir = Path(args.villa_names)
    if not segdir.is_dir():
        raise InkError(f"--villa-names {segdir}: not a folder (the segment folder that gets preds/ and "
                       "ink-detections.json)")
    if "f" not in variants:
        raise InkError("--villa-names writes the forward map under villa's name and registers it for VC3D; include f "
                       "in --variants")
    n, h, w = shape
    if tuple(box) != (0, h, 0, w):
        raise InkError(f"--villa-names needs the whole {h} x {w} surface, not the box {list(box)}: villa's predictions "
                       "and VC3D's overlay are one image per segment, and a crop would be stretched over all of it")
    try:
        model = vf.model_stem(villa_model(args))
    except vf.FormatError as exc:
        raise InkError(f"--villa-model: {exc}") from None
    date = args.villa_date or datetime.now().strftime(vf.PRED_DATE)
    try:
        ok_date = len(date) == 6 and date.isdigit() and bool(datetime.strptime(date, vf.PRED_DATE))
    except ValueError:
        ok_date = False
    if not ok_date:
        raise InkError(f"--villa-date {date!r} is not DDMMYY, the date villa's folder inference writes (infer.py:1212)")
    seg = Path(os.path.abspath(segdir)).name
    paths = {}
    for v in (v for v in ("f", "r") if v in variants):
        direction = VILLA_DIRECTIONS[v]
        name = vf.pred_name(seg, model, direction, date)
        parsed = vf.pred_direction(name)
        if parsed != direction:
            raise InkError(f"villa's merge_predictions would read {name} as {parsed!r}, not {direction!r} "
                           "(merge_predictions.py:112-118: _forward_ anywhere in the name counts first); the segment "
                           "folder or the model name holds _forward_ or _reverse_, so pass another --villa-model")
        if name.lower().startswith(vf.PRED_MERGED):
            raise InkError(f"{name} starts with {vf.PRED_MERGED}, which villa's merge_predictions takes for its own "
                           "output and never merges")
        dest = segdir / "preds" / name
        if dest.exists() and not args.villa_overwrite:
            raise InkError(f"{dest} exists; pass --villa-overwrite to replace it")
        paths[v] = dest
    plan = {"segment": str(segdir), "segment_name": seg, "model": model, "date": date, "size": [w, h],
            "paths": {v: str(p) for v, p in paths.items()}, "overwrite": bool(args.villa_overwrite),
            "villa": vf.VILLA_PIN, "warnings": []}
    surf = vf.villa_surface(segdir)
    if surf["height"] is not None and (surf["height"], surf["width"]) != (h, w):
        raise InkError(f"the render is {w} x {h} but villa would predict {surf['width']} x {surf['height']} from "
                       f"{surf['path']} (infer.py:940-952); villa's merge expects one size per segment")
    plan["surface_zarr"] = surf["path"]
    seg_check = vf.check_tifxyz(segdir, pixels=False) if (segdir / "meta.json").is_file() else None
    if seg_check is not None and seg_check["ok"]:
        meta, rows, cols, expected = vf.canvas_aspect(segdir)
        got = w / h
        if abs(got / expected - 1) > vf.ASPECT_TOL:
            raise InkError(f"the render is {w} x {h} (aspect {got:.4f}) but {seg}'s {cols} x {rows} grid needs aspect "
                           f"{expected:.4f}: VC3D stretches an ink map over the whole grid "
                           "(InkDetectionOverlayController.cpp:399-437), so this render is not of this segment")
        plan["tifxyz"] = {"grid": [rows, cols], "key": vf.segment_key(segdir, meta)}
    else:
        why = ("no meta.json" if seg_check is None else
               "; ".join(e["message"] for e in seg_check["errors"]))
        plan["tifxyz"] = None
        plan["no_record"] = (f"{segdir} is not a loadable tifxyz segment ({why}), so no ink-detections.json record "
                             "is written: VC3D's overlay lists the records of the segment it shows")
        plan["warnings"].append(plan["no_record"])
    preds = segdir / "preds"
    for p in (sorted(preds.iterdir()) if preds.is_dir() else []):
        if not p.is_file() or p.suffix.lower() not in vf.PRED_SUFFIXES or p.stem.lower().startswith(vf.PRED_MERGED):
            continue
        d = vf.pred_direction(p.name)
        mine = [v for v, q in paths.items() if VILLA_DIRECTIONS[v] == d]
        if not mine or p == paths[mine[0]]:
            continue
        try:
            pw, ph, _ = vf.image_size(p)
        except vf.FormatError:
            plan["warnings"].append(f"cannot read the size of {p.name} in preds/")
            continue
        if (pw, ph) != (w, h):
            raise InkError(f"preds/ already holds {p.name}, a {d} prediction of {pw} x {ph}, and this map is {w} x {h}: "
                           "villa's merge_predictions stops on a shape mismatch (merge_predictions.py:330-340)")
        if fnmatch.fnmatchcase(p.name, f"{seg}_{model}_{d}_*.tif"):     # villa's skip test (infer.py:1224-1236)
            plan["warnings"].append(f"preds/ already holds {p.name} for this model and direction: villa's folder "
                                    "inference skips on either file, and merge_predictions averages all of them")
    return plan


def villa_encode(raw, shape):
    """(uint8 map as villa's inference encodes it, None) or (None, why it cannot be). uint8 stays as it is; a float
    map must hold probabilities (0 to 1, as villafmt's prob scale takes them) and is clipped, times 255, truncated
    (infer.py:791-812); NaN and infinite values (off the surface: on it the run has failed already) become 0."""
    vf = _villafmt()
    a = np.asarray(raw)
    if a.ndim == 3 and a.shape[0] == 1:
        a = a[0]
    if a.shape != tuple(shape):
        return None, f"the map has shape {list(a.shape)} but the input surface is {list(shape)} (rows, columns)"
    if a.dtype == np.uint8:
        return a, None
    if a.dtype.kind == "f":
        finite = a[np.isfinite(a)]
        if finite.size and (float(finite.min()) < -vf.PROB_TOL or float(finite.max()) > 1 + vf.PROB_TOL):
            return None, (f"its values run from {float(finite.min()):g} to {float(finite.max()):g}, outside 0 to 1, so "
                          "they are not probabilities villa's encoding can keep")
    p = probability(a)
    p = np.nan_to_num(p.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    np.clip(p, 0, 1, out=p)
    p *= 255
    return p.astype(np.uint8), None


def is_villa_tiff(path):
    """True for a uint8 single-sample tiled LZW Big TIFF, the file villa's inference writes (infer.py:815-834)."""
    vf = _villafmt()
    try:
        info = vf.tiff_info(path)
    except vf.FormatError:
        return False
    return (info["dtype"] == "uint8" and info["samples"] == 1 and info["compression"] == 5 and info["tiled"]
            and info["bigtiff"])


def _move_into(src, dest):
    """Move src to dest whole: through a hidden .part name no villa tool picks up (merge_predictions.py:30 takes .png,
    .tif and .tiff), then one rename, so a stopped run leaves no half file under villa's name."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(f".{dest.name}.part")
    try:
        os.replace(src, part)
    except OSError:                 # another file system
        shutil.copyfile(src, part)
        os.unlink(src)
    os.replace(part, dest)


def publish_villa(plan, maps, raws, enc, tmp, engine_name, files):
    """Write the encoded maps under villa's names (the reversed control first, so a stop between the two never leaves
    a forward map without its control) and register the forward map in SEGDIR/ink-detections.json. Each file written
    goes into files (the caller's dict, so a later refusal still shows what was written). Returns the registration;
    InkError when villafmt refuses a file."""
    vf = _villafmt()
    segdir = Path(plan["segment"])
    for v in (v for v in ("r", "f") if v in enc):
        dest = Path(plan["paths"][v])
        src = Path(maps[v])
        rec = {"path": str(dest), "name": dest.name, "direction": VILLA_DIRECTIONS[v]}
        if is_villa_tiff(src):
            _move_into(src, dest)
            rec["how"] = "villa's own file, moved in byte for byte"
        else:
            # villafmt reads the map as ink.py read it (a .npy as it is, anything else saved here as a .npy first)
            raw = np.squeeze(np.asarray(raws[v]))
            as_is = raw.dtype == np.uint8 or (raw.dtype.kind == "f" and bool(np.isfinite(raw).all()))
            scale = "u8" if raw.dtype == np.uint8 or not as_is else "prob"
            if as_is and src.suffix.lower() == ".npy":
                source = src
            else:
                tmp.mkdir(parents=True, exist_ok=True)
                source = tmp / f"ink_{v}.npy"
                np.save(source, raw if as_is else enc[v])
            if not as_is:
                rec["encoded_here"] = ("the map was encoded here first (NaN or infinite values off the surface set to "
                                       f"0, or a {raw.dtype} map taken as a probability)")
            try:
                rep = vf.export_pred(source, segdir, plan["model"], VILLA_DIRECTIONS[v], scale=scale, date=plan["date"],
                                     overwrite=plan["overwrite"])
            except vf.FormatError as exc:
                raise InkError(f"villafmt preds export refused the {NAMES[v]}: {exc}") from None
            if not rep["ok"] or Path(rep["file"]) != dest:
                why = "; ".join(e["message"] for e in rep["errors"]) or f"it wrote {rep['file']}, not {dest}"
                raise InkError(f"villafmt preds export refused the {NAMES[v]}: {why}")
            rec.update(how=f"villafmt preds export, scale {scale}", engine_file=str(src),
                       encoding=rep["encoding"], scale=rep["scale"],
                       warnings=[e["message"] for e in rep["warnings"]])
        files[v] = rec
    registered = None
    if "f" in files and plan["tifxyz"] is not None:
        try:
            rep = vf.add_inkmap(segdir, files["f"]["path"], extra={
                "producer": "scripts/vc3d/ink.py --villa-names", "engine": engine_name, "variant": "f",
                "reverse_control": files.get("r", {}).get("name")})
        except vf.FormatError as exc:
            raise InkError(f"registering the forward map in ink-detections.json: {exc}") from None
        if not rep["ok"]:
            raise InkError("registering the forward map in ink-detections.json: " +
                           "; ".join(e["message"] for e in rep["errors"]))
        registered = {"file": rep["file"], "records": rep["records"], "record": rep["record"]}
    elif "f" in files:
        registered = {"skipped": plan["no_record"]}
    return registered


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
    plan = villa_plan(args, stack.shape, variants, box) if args.villa_names else None   # refusals before the model
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
    raws = {v: read_image(p) for v, p in maps.items()}
    probs = {v: probability(r) for v, r in raws.items()}
    failures = unreadable(probs, mask)
    villa = None
    if plan is not None:
        villa, failures = villa_step(plan, maps, raws, probs, mask, failures, out, engine.name)
    summary = {"engine": engine.describe(), "input": str(args.input), "window": {"layers": [a, b], "box": list(box)},
               "variants": variants, "seed": args.seed, "prepared": notes,
               "status": "failed" if failures else "ok", "failures": failures,
               "maps": {v: {"path": str(maps[v]), "stats": map_stats(probs[v], mask)} for v in maps},
               "comparison": {v: compare(probs["f"], probs[v], mask) for v in probs if v != "f" and "f" in probs},
               "direction": direction(probs, args.input, a, b, box),
               "seconds": round(time.time() - started, 1),
               "note": "model output, not a reading; a forward map that keeps its blobs under the controls is "
                       "not responding to ink in depth order"}
    if villa is not None:
        summary["villa_names"] = villa
        for v, rec in (villa.get("files") or {}).items():
            summary["maps"][v].update(villa_name=rec["name"], engine_file=rec.get("engine_file"))
    (out / "ink.json").write_text(json.dumps(summary, indent=1))
    log(f"done in {summary['seconds']} s: " + ", ".join(
        f"{v} above 0.5: {summary['maps'][v]['stats'].get('above_threshold')}" for v in maps))
    if failures:
        raise UnreadableMaps("the maps cannot be read (status failed in ink.json): " + "; ".join(failures) + ". " +
                             advice(failures), summary)
    if villa is not None and villa["errors"]:
        raise InkError("--villa-names: " + "; ".join(villa["errors"]) + f" ({villa.get('why_not', '')})")
    if villa is not None:
        reg = villa["registered"] or {}
        log(f"villa's names: {', '.join(rec['name'] for rec in villa['files'].values())} in {plan['segment']}/preds; "
            + (f"forward map registered in {reg['file']}" if reg.get("file") else f"not registered: {reg.get('skipped')}"))
    return summary


def villa_step(plan, maps, raws, probs, mask, failures, out, engine_name):
    """--villa-names once the maps are made: encode the forward map and the reversed control as villa's uint8, test
    the encoded maps as any map is tested, then publish and register them. Updates maps and probs to the files
    written. Returns (the record for ink.json, the run's failures). Nothing reaches preds/ from a run whose maps
    cannot be read, before or after the encoding."""
    villa = {k: plan[k] for k in ("segment", "segment_name", "model", "date", "paths", "surface_zarr", "tifxyz",
                                  "warnings", "villa")}
    villa.update(published=False, errors=[], files={}, registered=None)
    if failures:
        villa["why_not"] = "the maps cannot be read (status failed); nothing was written to preds/"
        return villa, failures
    w, h = plan["size"]
    enc = {}
    for v in (v for v in VILLA_DIRECTIONS if v in raws):
        e, why = villa_encode(raws[v], (h, w))
        if why:
            villa["errors"].append(f"the {NAMES[v]}: {why}")
        else:
            enc[v] = e
    if villa["errors"]:
        villa["why_not"] = "a map cannot be written as villa's prediction; nothing was written to preds/"
        return villa, failures
    encoded = {v: e.astype(np.float32) / 255.0 for v, e in enc.items()}
    lost = unreadable({**probs, **encoded}, mask)
    if lost:
        villa["why_not"] = "a map holds nothing once encoded as villa's uint8; nothing was written to preds/"
        return villa, [r + ENCODED for r in lost]
    tmp = Path(tempfile.mkdtemp(prefix=".kit-ink-villa-", dir=out))
    try:
        villa["registered"] = publish_villa(plan, maps, raws, enc, tmp, engine_name, villa["files"])
    except InkError as exc:
        villa["errors"].append(str(exc))
        villa["why_not"] = ("villa's names were not all written: files lists those that were" if villa["files"] else
                            "nothing was written to preds/")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        maps.update({v: Path(rec["path"]) for v, rec in villa["files"].items()})   # where each map now is
    if not villa["errors"]:
        villa["published"] = True
        probs.update(encoded)
    return villa, failures


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="surface volume: zarr or layer folder")
    p.add_argument("--out", required=True, help="output folder")
    p.add_argument("--variants", default="f,r", help="comma list of f, r, s (default f,r)")
    p.add_argument("--engine", required=True, choices=sorted(ENGINES))
    p.add_argument("--checkpoint", help="villa .pth or TorchScript .pt")
    p.add_argument("--checkpoint-sha256", help="refuse a checkpoint whose sha256 is not this (checked right before "
                   "the load, on the bytes loaded for villa)")
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
    p.add_argument("--villa-names", metavar="SEGDIR", help="write the forward map and the reversed control into "
                   "SEGDIR/preds/ under villa's prediction names as uint8 0 to 255, and register the forward map in "
                   "SEGDIR/ink-detections.json for VC3D's Ink Detection overlay")
    p.add_argument("--villa-model", metavar="NAME", help="the model name in villa's file names (default: the "
                   "checkpoint's stem, or the v8in snapshot folder's name; required for the command engine)")
    p.add_argument("--villa-date", metavar="DDMMYY", help="the date in villa's file names (default: today, as villa "
                   "writes it)")
    p.add_argument("--villa-overwrite", action="store_true", help="replace a prediction already at villa's name")
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
