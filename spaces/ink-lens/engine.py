"""Ink Lens engine: an openly licensed 9 um ink model on one region, three depth windows, both depth orders.

The model is built by villa's own flat ink inference (vesuvius.ink_detection.inference.infer.configure_model, at the
commit pinned in VILLA_COMMIT) from a checkpoint downloaded by URL and refused unless its SHA-256 matches. The patch
schedule (128 px patches, stride 64, the last flush with the end), the layer choice (center crop, reversed for the
control), villa's per-patch robust normalization and the Hann blend are villa's; two things differ from villa's
command line, both to fit one ZeroGPU call:

1. the robust normalization runs batched on the device (robust_torch), checked against villa's CPU function
   (robust_np is a line-for-line copy of villa's normalize_robust for a patch with no mask; tests/test_inklens.py
   compares them, and compares robust_np with villa's own function when villa is importable);
2. the maps stay float (0 to 1) instead of villa's uint8 encoding, so the control-set threshold is not quantized.

run_reference() is the same algorithm in numpy with any predict function: the tests run it with a stand-in model,
and the torch path is checked against it.

  python3 engine.py estimate 1024 1024 --windows 3      patches and the GPU seconds one call asks for
  python3 engine.py fetch d9v2                           download and check a checkpoint into the cache
"""

from __future__ import annotations

import hashlib
import math
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
VILLA_REPO = "https://github.com/ScrollPrize/villa.git"
VILLA_TARBALL = "https://codeload.github.com/ScrollPrize/villa/tar.gz/{commit}"
VILLA_COMMIT = "8aa507c1215f1fa8758f13d0538f7af9710e02d7"   # ScrollPrize/villa main, 18 Oct 2026
CACHE = Path(os.environ.get("INKLENS_CACHE") or Path(tempfile.gettempdir()) / "ink-lens")
USER_AGENT = f"ink-lens/{VERSION}"

# Openly licensed 9 um readers that drop into villa's flat inference. Public held-out scores (PHerc0841, crops with a
# 64 px inner edge, raw / reversed AUC) are in docs/results.json; d9v2 is the default.
READERS = {
    "d9v2": {
        "title": "d9v2 (TAUIL-Abd-Elilah, MIT)",
        "url": "https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search/releases/download/v1.0/"
               "d9v2_ft-012000.pth",
        "file": "d9v2_ft-012000.pth",
        "sha256": "50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966",
        "license": "MIT",
        "source": "https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search",
        "held_out": "PHerc0841 w00, ag896, ag405 (its reader/test.txt)",
    },
    "ink_9um": {
        "title": "ink_9um seed 42 step 75,000 (Vesuvius Challenge, MIT)",
        "url": "https://huggingface.co/scrollprize/ink_9um/resolve/main/hybrid_3d2d-seed42/step-075000.pth",
        "file": "ink_9um-seed42-step-075000.pth",
        "sha256": "e635558ae6a1a807a7e5ec1e83adfd45bc3c0ac53883ea43f1d4e085d62a9cab",
        "license": "MIT",
        "source": "https://huggingface.co/scrollprize/ink_9um",
        "held_out": "PHerc0841 (its label dataset has no PHerc0841 segment)",
    },
}
READER_CHOICES = ("d9v2", "ink_9um", "both")

PATCH, STRIDE, DEPTH = 128, 64, 17
STACK = 21                                   # layers kept around the middle: the three windows below fit in it
WINDOW_OFFSETS = {1: (2,), 3: (0, 2, 4)}     # window starts inside the 21-layer stack (2 is villa's own center)
BATCH = 64
MIN_SIDE, MAX_SIDE = PATCH, 2048
MIN_LAYERS, MAX_LAYERS = DEPTH, 65
# One call's duration: a fixed start plus a per-patch allowance, capped. The per-patch figure is an estimate (3 to
# 6 ms per patch with batched fp16 and normalization on the GPU) with a margin; every receipt records the measured
# seconds so the first calls calibrate it.
GPU_START_S, GPU_PER_PATCH_S, GPU_MAX_S = 4.0, 0.012, 40


class EngineError(ValueError):
    """A request the engine refuses; the message says why."""


# ---------------------------------------------------------------- sizing

def positions(length, patch=PATCH, stride=STRIDE):
    """Patch starts along one axis, the last flush with the end (villa's _sliding_positions_1d)."""
    if length <= patch:
        return [0]
    out = list(range(0, length - patch + 1, max(1, stride)))
    if out[-1] != length - patch:
        out.append(length - patch)
    return out


def readers_of(choice):
    if choice not in READER_CHOICES:
        raise EngineError(f"reader {choice!r}: choose one of {', '.join(READER_CHOICES)}")
    return ("d9v2", "ink_9um") if choice == "both" else (choice,)


def patches(height, width, windows=3, reader="d9v2"):
    """Patches one call runs: per pass the patch grid, times windows, times two depth orders, times readers."""
    if windows not in WINDOW_OFFSETS:
        raise EngineError(f"windows {windows}: use 1 or 3")
    return len(positions(height)) * len(positions(width)) * windows * 2 * len(readers_of(reader))


def gpu_seconds(n_patches):
    """The duration a call asks ZeroGPU for; refuses a call that would need more than GPU_MAX_S."""
    need = math.ceil(GPU_START_S + n_patches * GPU_PER_PATCH_S)
    if need > GPU_MAX_S:
        raise EngineError(f"{n_patches} patches need about {need} GPU seconds, more than the {GPU_MAX_S} s one call "
                          "may ask for; use a smaller region, one depth window, or local mode")
    return need


def estimate(height, width, windows=3, reader="d9v2"):
    check_side(height, width)
    n = patches(height, width, windows, reader)
    out = {"height": int(height), "width": int(width), "windows": int(windows), "reader": reader, "patches": n}
    try:
        out["gpu_seconds_requested"] = gpu_seconds(n)
    except EngineError as exc:
        out["gpu_seconds_requested"] = None
        out["refused"] = str(exc)
    return out


def check_side(height, width):
    for name, side in (("height", height), ("width", width)):
        if not MIN_SIDE <= int(side) <= MAX_SIDE:
            raise EngineError(f"{name} {side} px: a region is {MIN_SIDE} to {MAX_SIDE} px a side at 9.6 um")


def check_volume(volume, windows=3):
    """Refuse anything but a uint8 (layers, rows, columns) region of the right size and depth."""
    import numpy as np
    a = np.asarray(volume)
    if a.ndim != 3:
        raise EngineError(f"a surface volume has 3 axes (layers, rows, columns), this one has {a.ndim}")
    if a.dtype != np.uint8:
        raise EngineError(f"type {a.dtype}: the engine takes uint8 (volio.to_uint8 converts uint16)")
    L, H, W = a.shape
    need = STACK if windows == 3 else DEPTH
    if not need <= L <= MAX_LAYERS:
        raise EngineError(f"{L} layers: {windows} depth window{'s' if windows > 1 else ''} need{'' if windows > 1 else 's'} "
                          f"{need} to {MAX_LAYERS} layers, layers first")
    check_side(H, W)
    if not a.any():
        raise EngineError("the region is all zero (off the segment, or a hole in it)")
    return L, H, W


def stack(volume, windows=3):
    """The middle STACK layers (or all, if fewer), as villa's center crop chooses them (upper center when uneven)."""
    L = volume.shape[0]
    n = min(L, STACK)
    start = L // 2 - n // 2
    return volume[start:start + n]


def window_indices(n_layers, offset, direction):
    """Layer indices of one 17-layer window inside the stack; reversed for the control."""
    if n_layers < STACK:            # one window, centered (villa's own choice)
        start = n_layers // 2 - DEPTH // 2
    else:
        start = offset
    idx = list(range(start, start + DEPTH))
    return idx[::-1] if direction == "reverse" else idx


def passes(windows):
    """(offset, direction) for every pass of one reader: each window in both orders."""
    return [(o, d) for o in WINDOW_OFFSETS[windows] for d in ("forward", "reverse")]


# ---------------------------------------------------------------- villa's normalization, numpy and torch

def robust_np(patch):
    """villa's normalize_robust (vesuvius/image_proc/intensity/normalization.py at VILLA_COMMIT) with no mask:
    clip to the 1st and 99th percentiles, subtract the median, divide by 1.4826 x MAD, with villa's fallbacks."""
    import numpy as np
    arr = np.asarray(patch).astype(np.float32, copy=True)
    valid = arr.reshape(-1)
    if valid.size == 0:
        return arr
    std_preclip = float(np.std(valid))
    lower = float(np.percentile(valid, 1.0))
    upper = float(np.percentile(valid, 99.0))
    np.clip(arr, lower, upper, out=arr)
    valid = arr.reshape(-1)
    median = float(np.median(valid))
    mad = float(np.median(np.abs(valid - median)))
    scaled = 1.4826 * mad
    if not np.isfinite(scaled) or scaled < 1e-6:
        span = upper - lower
        cands = []
        if np.isfinite(std_preclip):
            cands.append(abs(std_preclip))
        if np.isfinite(span):
            cands.append(abs(span) / 2.0)
        scaled = next((c for c in cands if c >= 1e-6), None)
        if scaled is None or not np.isfinite(scaled):
            scaled = 1.0
    arr -= median
    arr /= scaled
    np.nan_to_num(arr, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return arr


def _lerp_sorted(torch, s, q):
    """numpy's linear percentile of each row of an already sorted (B, N) tensor."""
    n = s.shape[1]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return s[:, lo] + (s[:, hi] - s[:, lo]) * frac


def robust_torch(x):
    """robust_np on every row of a (B, N) float32 tensor at once, on its device."""
    import torch
    x = x.float()
    s, _ = torch.sort(x, dim=1)
    std_pre = x.std(dim=1, unbiased=False)
    lower, upper = _lerp_sorted(torch, s, 0.01), _lerp_sorted(torch, s, 0.99)
    x = torch.maximum(torch.minimum(x, upper[:, None]), lower[:, None])
    s = torch.maximum(torch.minimum(s, upper[:, None]), lower[:, None])
    median = _lerp_sorted(torch, s, 0.5)
    dev, _ = torch.sort((x - median[:, None]).abs(), dim=1)
    scaled = 1.4826 * _lerp_sorted(torch, dev, 0.5)
    half_span = (upper - lower).abs() / 2.0
    ok = torch.isfinite(scaled) & (scaled >= 1e-6)
    fb = torch.where(torch.isfinite(std_pre) & (std_pre.abs() >= 1e-6), std_pre.abs(),
                     torch.where(torch.isfinite(half_span) & (half_span >= 1e-6), half_span,
                                 torch.ones_like(half_span)))
    scaled = torch.where(ok, scaled, fb)
    out = (x - median[:, None]) / scaled[:, None]
    return torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def hann2d():
    """villa's floored Hann blend map (compute_importance_map_2d, mode hann), in numpy."""
    import numpy as np
    w1 = np.hanning(PATCH).astype(np.float32)          # numpy's hanning is the symmetric (periodic=False) window
    w = np.outer(w1, w1)
    w /= max(float(w.max()), float(np.finfo(np.float32).eps))
    return np.maximum(w, 0.001).astype(np.float32)


# ---------------------------------------------------------------- the numpy reference

def run_reference(volume, predict, windows=3):
    """The whole algorithm in numpy: predict(batch (B, 1, 17, 128, 128) float32) -> (B, 128, 128) probabilities.
    Returns {"forward": F, "reverse": R} (float32, 0 to 1), each the mean over the windows."""
    import numpy as np
    vol = stack(np.asarray(volume), windows)
    L, H, W = vol.shape
    ys, xs = positions(H), positions(W)
    wmap = hann2d()
    maps = {"forward": [], "reverse": []}
    for off, direction in passes(windows):
        idx = window_indices(L, off, direction)
        psum = np.zeros((H, W), np.float32)
        wsum = np.zeros((H, W), np.float32)
        for y0 in ys:
            for x0 in xs:
                raw = vol[idx, y0:y0 + PATCH, x0:x0 + PATCH]
                if not raw.any():
                    continue
                p = np.asarray(predict(robust_np(raw)[None, None]), np.float32)[0]
                psum[y0:y0 + PATCH, x0:x0 + PATCH] += p * wmap
                wsum[y0:y0 + PATCH, x0:x0 + PATCH] += wmap
        prob = np.divide(psum, wsum, out=np.zeros_like(psum), where=wsum > 1e-6)
        maps[direction].append(np.clip(prob, 0, 1))
    return {d: np.mean(m, axis=0).astype(np.float32) for d, m in maps.items()}


# ---------------------------------------------------------------- downloads

def sha256_file(path, block=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp, open(part, "wb") as out:
        shutil.copyfileobj(resp, out, 1 << 20)
    os.replace(part, dest)


def ensure_checkpoint(name, cache=CACHE):
    """A reader's checkpoint, downloaded once and refused unless its SHA-256 matches READERS. INKLENS_<NAME> (for
    example INKLENS_D9V2) may name a local copy; its SHA-256 is still checked."""
    spec = READERS[name]
    env = os.environ.get("INKLENS_" + name.upper())
    path = Path(env).expanduser() if env else Path(cache) / "checkpoints" / spec["file"]
    if not path.is_file():
        if env:
            raise EngineError(f"INKLENS_{name.upper()}={env} does not exist")
        _download(spec["url"], path)
    digest = sha256_file(path)
    if digest != spec["sha256"]:
        raise EngineError(f"{path} has SHA-256 {digest}, expected {spec['sha256']} for {name}; refusing it")
    return path


def _git_commit(path):
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _villa_tarball(tmp, commit):
    root = tmp.resolve()
    kept = 0
    req = urllib.request.Request(VILLA_TARBALL.format(commit=commit), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp, tarfile.open(fileobj=resp, mode="r|gz") as tf:
        for m in tf:
            _, _, rel = m.name.partition("/")
            if not rel.startswith("vesuvius/src/"):
                continue
            target = (root / rel).resolve()
            if root not in target.parents or m.issym() or m.islnk():
                continue
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                kept += 1
    if not kept:
        raise EngineError(f"the villa tarball for {commit} held no vesuvius/src files")


def ensure_villa(cache=CACHE):
    """villa's vesuvius package on sys.path: VILLA_SRC (a local vesuvius/src) when set, else the pinned commit,
    downloaded once (sparse git fetch, else GitHub's tarball)."""
    if os.environ.get("VILLA_SRC"):
        src = Path(os.environ["VILLA_SRC"]).expanduser().resolve()
        info = {"source": "VILLA_SRC", "commit": _git_commit(src)}
    else:
        dest = Path(cache) / f"villa-{VILLA_COMMIT[:12]}"
        if not (dest / "COMMIT").is_file():
            tmp = dest.with_name(dest.name + ".part")
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            try:
                git = ["git", "-C", str(tmp)]
                for cmd in (["init", "-q"], ["remote", "add", "origin", VILLA_REPO],
                            ["sparse-checkout", "set", "vesuvius/src"],
                            ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", VILLA_COMMIT],
                            ["checkout", "-q", "FETCH_HEAD"]):
                    subprocess.run(git + cmd, capture_output=True, text=True, check=True, timeout=600)
            except (OSError, subprocess.SubprocessError):
                shutil.rmtree(tmp, ignore_errors=True)
                tmp.mkdir(parents=True)
                _villa_tarball(tmp, VILLA_COMMIT)
            (tmp / "COMMIT").write_text(VILLA_COMMIT + "\n")
            shutil.rmtree(dest, ignore_errors=True)
            os.replace(tmp, dest)
        src = dest / "vesuvius" / "src"
        info = {"source": "pinned download", "commit": (dest / "COMMIT").read_text().strip()}
    if not (src / "vesuvius" / "ink_detection" / "inference" / "infer.py").is_file():
        raise EngineError(f"{src} holds no villa vesuvius package")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    info["pinned"] = VILLA_COMMIT
    return info


def load_villa_model(name, cache=CACHE):
    """(model, preprocessing, amp dtype, info) for one reader, built by villa's configure_model. The checkpoint is
    opened with torch.load(weights_only=True): villa's loader allows any pickle, so it is replaced for this call."""
    import argparse
    import torch
    villa = ensure_villa(cache)
    path = ensure_checkpoint(name, cache)
    from vesuvius.ink_detection.inference import infer
    original = infer.load_checkpoint
    infer.load_checkpoint = lambda p: torch.load(str(p), map_location="cpu", weights_only=True)
    try:
        cm = infer.configure_model(argparse.Namespace(checkpoint=path, amp_dtype="auto"))
    finally:
        infer.load_checkpoint = original
    got = (int(cm.patch_size), int(cm.input_depth))
    if got != (PATCH, DEPTH):
        raise EngineError(f"{name} has patch and depth {got}; Ink Lens is built for {(PATCH, DEPTH)}")
    if cm.preprocessing not in ("tifxyz_robust", "divide_255"):
        raise EngineError(f"{name} asks for preprocessing {cm.preprocessing!r}, which Ink Lens does not run")
    info = {"name": name, "sha256": READERS[name]["sha256"], "url": READERS[name]["url"],
            "license": READERS[name]["license"], "preprocessing": cm.preprocessing,
            "amp_on_cuda": str(cm.amp_dtype).replace("torch.", ""), "villa": villa, "loader": "weights_only=True"}
    return cm.model.eval(), cm.preprocessing, cm.amp_dtype, info


# ---------------------------------------------------------------- the torch engine

def pick_device(prefer=None):
    import torch
    if prefer:
        return torch.device(prefer)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class Engine:
    """Readers loaded once; run() does one region on one device.

    models: {name: (module, preprocessing, amp_dtype, info)} to use instead of downloading (the tests pass a
    stand-in); otherwise every name in `readers` is loaded through villa."""

    def __init__(self, readers=("d9v2",), cache=CACHE, models=None, place_on_cuda=True):
        t0 = time.time()
        import torch
        self.torch = torch
        self.models = dict(models) if models else {n: load_villa_model(n, cache) for n in readers}
        if place_on_cuda and torch.cuda.is_available():
            for m in self.models.values():
                m[0].to("cuda")
        self.startup_s = round(time.time() - t0, 1)

    def describe(self):
        return {"engine": f"ink-lens {VERSION}", "readers": {n: m[3] for n, m in self.models.items()},
                "patch": PATCH, "stride": STRIDE, "depth": DEPTH, "stack": STACK, "blend": "hann (villa, floored)",
                "batch": BATCH, "torch": self.torch.__version__}

    def run(self, volume, reader="d9v2", windows=3, device=None, batch=BATCH):
        """{"forward": F, "reverse": R, "per_reader": {...}, ...} for one uint8 region, float32 maps in 0 to 1."""
        import numpy as np
        torch = self.torch
        names = readers_of(reader)
        missing = [n for n in names if n not in self.models]
        if missing:
            raise EngineError(f"reader {', '.join(missing)} is not loaded here")
        check_volume(volume, windows)
        dev = pick_device(device)
        t0 = time.perf_counter()
        vol = stack(np.asarray(volume), windows)
        L, H, W = vol.shape
        stack_start = int(np.asarray(volume).shape[0] // 2 - L // 2)
        vt = torch.from_numpy(np.ascontiguousarray(vol)).to(dev)
        coords = [(y, x) for y in positions(H) for x in positions(W)]
        wmap = torch.from_numpy(hann2d()).to(dev)
        per_reader, n_patches = {}, 0
        for name in names:
            model, prep, amp, _ = self.models[name]
            model = model.to(dev)
            maps = {"forward": [], "reverse": []}
            for off, direction in passes(windows):
                idx = torch.tensor(window_indices(L, off, direction), device=dev)
                sub = vt.index_select(0, idx)
                psum = torch.zeros((H, W), dtype=torch.float32, device=dev)
                wsum = torch.zeros((H, W), dtype=torch.float32, device=dev)
                for b0 in range(0, len(coords), batch):
                    chunk = coords[b0:b0 + batch]
                    raw = torch.stack([sub[:, y:y + PATCH, x:x + PATCH] for y, x in chunk])   # (B, 17, 128, 128)
                    keep = raw.reshape(len(chunk), -1).any(dim=1)   # villa skips all-zero patches, before normalizing
                    if not bool(keep.any()):
                        continue
                    if not bool(keep.all()):
                        chunk = [c for c, k in zip(chunk, keep.tolist()) if k]
                        raw = raw[keep]
                    flat = raw.reshape(len(chunk), -1).float()
                    norm = robust_torch(flat) if prep == "tifxyz_robust" else flat / 255.0
                    images = norm.reshape(len(chunk), 1, DEPTH, PATCH, PATCH)
                    ctx = (torch.autocast("cuda", dtype=amp) if dev.type == "cuda" and amp is not None
                           else _null())
                    with torch.inference_mode(), ctx:
                        logits = model(images)
                    prob = logits.float().sigmoid()
                    if prob.shape[-2:] != (PATCH, PATCH):
                        prob = torch.nn.functional.interpolate(prob, size=(PATCH, PATCH), mode="bilinear",
                                                               align_corners=False)
                    prob = prob[:, 0]
                    for (y, x), p in zip(chunk, prob):
                        psum[y:y + PATCH, x:x + PATCH] += p * wmap
                        wsum[y:y + PATCH, x:x + PATCH] += wmap
                    n_patches += len(chunk)
                out = torch.where(wsum > 1e-6, psum / wsum.clamp_min(1e-6), torch.zeros_like(psum)).clamp(0, 1)
                maps[direction].append(out)
            per_reader[name] = {d: torch.stack(m).mean(0).cpu().numpy().astype(np.float32) for d, m in maps.items()}
        if dev.type == "cuda":
            torch.cuda.synchronize(dev)
        F = np.mean([per_reader[n]["forward"] for n in names], axis=0).astype(np.float32)
        R = np.mean([per_reader[n]["reverse"] for n in names], axis=0).astype(np.float32)
        name = torch.cuda.get_device_name(dev) if dev.type == "cuda" else (platform.processor() or platform.machine())
        return {"forward": F, "reverse": R, "per_reader": per_reader, "readers": list(names), "windows": windows,
                "window_layers": {f"{o}:{d}": window_indices(L, o, d) for o, d in passes(windows)},
                "stack_layers": int(L), "stack_start": stack_start, "patches": n_patches, "device": str(dev), "device_name": name,
                "seconds": round(time.perf_counter() - t0, 3)}


class _null:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Ink Lens engine helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("height", type=int)
    e.add_argument("width", type=int)
    e.add_argument("--windows", type=int, default=3, choices=(1, 3))
    e.add_argument("--reader", default="d9v2", choices=READER_CHOICES)
    f = sub.add_parser("fetch")
    f.add_argument("reader", choices=sorted(READERS))
    a = ap.parse_args(argv)
    try:
        if a.cmd == "estimate":
            print(json.dumps(estimate(a.height, a.width, a.windows, a.reader), indent=1))
        else:
            print(json.dumps({"reader": a.reader, "path": str(ensure_checkpoint(a.reader))}))
    except EngineError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
