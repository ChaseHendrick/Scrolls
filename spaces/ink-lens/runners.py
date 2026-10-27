"""Run any zoo model on a surface volume: weights fetched and checked, then the model's own inference code.

  villa9     villa's flat ink inference model (configure_model at engine.VILLA_COMMIT), run here batched on the device
             with villa's per-patch normalisation (engine.robust_torch) and its floored Hann blend, at the patch size
             the checkpoint's own config names (Reader V3: 384 px; the others: 128 px), overlap 0.5.
  hecate     ink-sdk's Hecate adapter (LimeGS/ink-sdk at zoo.INK_SDK_COMMIT), in this process: the released
             hecate.py architecture, both depth orders, and its 3D volume in the render's layers.
  canonical  ink-sdk's canonical 2 um adapter, in this process, forward only.
  ct3d       not here: a scan-space 3D model needs the scan around the mesh and runs as a Hugging Face Job
             (tools/gallery_job.py); project3d.py reads its volume onto the surface.

Every run takes explicit depth windows. A window is a list of layer indices into the volume, in the order the model
reads them; its reverse-depth control is the same layers reversed (the same CT, the wrong order). window() builds
ink-sdk's battery windows: the model's depth, centred `centre` layers from the middle, `step` layers apart.

Weights are downloaded once into CACHE/models, at ink-sdk's own layout for its eight profiles (so `ink-sdk doctor`
reads the same files), and refused unless their size and SHA-256 match the zoo's pins. Checkpoints are opened with
torch.load(weights_only=True).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
import urllib.request
from pathlib import Path

import engine
import zoo

CACHE = engine.CACHE
USER_AGENT = engine.USER_AGENT
VILLA_BATCH = 64


class RunError(ValueError):
    """A run Ink Lens refuses; the message says why."""


# ---------------------------------------------------------------- depth windows (ink-sdk's battery rule)

def window(n_layers, depth, centre=0, step=1):
    """Layer indices of one window: `depth` layers, centred `centre` from the middle, `step` apart; None when it
    does not fit (ink_sdk.battery.window)."""
    mid = n_layers // 2
    idx = [mid + centre + step * (k - depth // 2) for k in range(depth)]
    return idx if min(idx) >= 0 and max(idx) < n_layers else None


def windows_for(n_layers, depth, centres=(0,), steps=(1,)):
    """{"c+0_s1": [...], ...} for every centre and step that fits; a window that does not fit is left out."""
    out = {}
    for s in steps:
        for c in centres:
            idx = window(n_layers, depth, int(c), int(s))
            if idx is not None:
                out[f"c{int(c):+d}_s{int(s)}"] = idx
    return out


# ---------------------------------------------------------------- weights

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
    with urllib.request.urlopen(req, timeout=900) as resp, open(part, "wb") as out:
        shutil.copyfileobj(resp, out, 1 << 20)
    os.replace(part, dest)


def _checked(path, sha, size, what):
    if size is not None and path.stat().st_size != size:
        raise RunError(f"{what}: {path} is {path.stat().st_size} bytes, the pin is {size}; refusing it")
    got = sha256_file(path)
    if got != sha:
        raise RunError(f"{what}: {path} has SHA-256 {got}, the pin is {sha}; refusing it")
    return path


def local_path(name, cache=CACHE):
    """Where a model's checkpoint lives: ink-sdk's checkpoint.path for its profiles, else models/NAME/FILE."""
    spec = zoo.get(name)
    w = spec["weights"]
    root = Path(cache) / "models"
    sdk_paths = {"ink_9um-s42": "ink_9um/hybrid_3d2d-seed42/step-075000.pth",
                 "ink_9um-s43": "ink_9um/hybrid_3d2d-seed43/step-075000.pth",
                 "reader-v2": "reader-v2/reader-v2-step040000.pth", "reader-v3": "reader-v3/reader-v3.pth",
                 "hecate-2.4": "hecate/hecate_2.4um.pth", "hecate-9.6": "hecate/hecate_9.6um.pth",
                 "canonical-2um": "canonical/r152_3ddec_v2_l5_epoch13.ckpt"}
    if name in sdk_paths:
        return root / sdk_paths[name]
    if w["kind"] == "hf-rebuild":
        return root / name
    return root / name / Path(w["path"]).name


def fetch(name, cache=CACHE, env=None):
    """The checked local checkpoint of a model (a folder of checked files for an hf-rebuild model). INKLENS_<NAME>
    (NAME upper-cased, - and . as _) may name a local copy; it is checked like a download."""
    env = os.environ if env is None else env
    spec = zoo.get(name)
    w = spec["weights"]
    key = "INKLENS_" + name.upper().replace("-", "_").replace(".", "_")
    if w["kind"] == "hf-rebuild":
        folder = Path(env.get(key) or local_path(name, cache))
        for role, (path, sha, size) in w["files"].items():
            p = folder / Path(path).name
            if not p.is_file():
                if env.get(key):
                    raise RunError(f"{key}={folder} has no {Path(path).name}")
                _download(f"https://huggingface.co/{w['repo']}/resolve/{w['revision']}/{path}", p)
            _checked(p, sha, size, f"{name} {role}")
        return folder
    path = Path(env[key]).expanduser() if env.get(key) else local_path(name, cache)
    if not path.is_file():
        if env.get(key):
            raise RunError(f"{key}={path} does not exist")
        _download(w["url"], path)
    return _checked(path, w["sha256"], w.get("bytes"), name)


# ---------------------------------------------------------------- villa 9 um

def load_checkpoint(name, path):
    """The checkpoint dict villa's configure_model reads, with no pickle beyond tensors and plain types."""
    import torch
    spec = zoo.get(name)
    if spec["weights"]["kind"] == "hf-rebuild":
        from safetensors.torch import load_file
        files = {role: Path(path) / Path(p).name for role, (p, _, _) in spec["weights"]["files"].items()}
        return {"model": load_file(str(files["weights"])), "config": json.loads(files["config"].read_text()),
                "step": int(spec["weights"]["step"])}
    return torch.load(str(path), map_location="cpu", weights_only=True)


def load_villa9(name, cache=CACHE):
    """(model, info) for one villa9 model, built by villa's own configure_model."""
    import argparse
    spec = zoo.get(name)
    if spec["family"] != "villa9":
        raise RunError(f"{name} is a {spec['family']} model, not villa9")
    villa = engine.ensure_villa(cache)
    path = fetch(name, cache)
    from vesuvius.ink_detection.inference import infer
    original = infer.load_checkpoint
    infer.load_checkpoint = lambda p: load_checkpoint(name, p)
    try:
        cm = infer.configure_model(argparse.Namespace(checkpoint=Path(path), amp_dtype="auto"))
    finally:
        infer.load_checkpoint = original
    depth = int(cm.input_depth)
    if depth != spec["depth"]:
        raise RunError(f"{name} reads {depth} layers; the zoo says {spec['depth']}")
    if cm.preprocessing not in ("tifxyz_robust", "divide_255"):
        raise RunError(f"{name} asks for preprocessing {cm.preprocessing!r}, which Ink Lens does not run")
    info = {"name": name, "family": "villa9", "patch": int(cm.patch_size), "depth": depth,
            "preprocessing": cm.preprocessing, "amp_on_cuda": str(cm.amp_dtype).replace("torch.", ""),
            "villa": villa, "loader": "weights_only=True" if spec["weights"]["kind"] != "hf-rebuild"
            else "safetensors + config json"}
    return Villa9(cm.model.eval(), cm.preprocessing, cm.amp_dtype, int(cm.patch_size), depth, info)


def hann(n):
    """villa's floored Hann blend for an n x n patch (engine.hann2d at any size)."""
    import numpy as np
    w1 = np.hanning(n).astype(np.float32)
    w = np.outer(w1, w1)
    w /= max(float(w.max()), float(np.finfo(np.float32).eps))
    return np.maximum(w, 0.001).astype(np.float32)


class Villa9:
    """One loaded villa9 model. run() gives a map per (window, order)."""

    def __init__(self, model, preprocessing, amp, patch, depth, info):
        self.model, self.prep, self.amp, self.patch, self.depth, self.info = model, preprocessing, amp, patch, depth, info

    def patches(self, height, width, n_windows, n_orders=2):
        stride = max(1, self.patch // 2)
        return (len(engine.positions(height, self.patch, stride)) * len(engine.positions(width, self.patch, stride))
                * n_windows * n_orders)

    def run(self, volume, windows, orders=("forward", "reverse"), device=None, batch=VILLA_BATCH):
        """{(window key, order): float32 map in 0..1}. volume: uint8 (layers, rows, columns) at the model's scale;
        windows: {key: [layer indices]} of exactly `depth` layers each."""
        import numpy as np
        import torch
        vol = np.asarray(volume)
        if vol.dtype != np.uint8 or vol.ndim != 3:
            raise RunError("a surface volume is uint8 (layers, rows, columns)")
        L, H, W = vol.shape
        P = self.patch
        if min(H, W) < P:
            raise RunError(f"{self.info['name']} reads {P} px patches; the region is {H} x {W}")
        for k, idx in windows.items():
            if len(idx) != self.depth or min(idx) < 0 or max(idx) >= L:
                raise RunError(f"window {k}: {self.depth} layers inside 0..{L - 1} needed, got {idx}")
        dev = engine.pick_device(device)
        model = self.model.to(dev)
        vt = torch.from_numpy(np.ascontiguousarray(vol)).to(dev)
        stride = max(1, P // 2)
        coords = [(y, x) for y in engine.positions(H, P, stride) for x in engine.positions(W, P, stride)]
        wmap = torch.from_numpy(hann(P)).to(dev)
        out, n = {}, 0
        for key, idx in windows.items():
            for order in orders:
                ids = idx if order == "forward" else idx[::-1]
                sub = vt.index_select(0, torch.tensor(ids, device=dev))
                psum = torch.zeros((H, W), dtype=torch.float32, device=dev)
                wsum = torch.zeros((H, W), dtype=torch.float32, device=dev)
                for b0 in range(0, len(coords), batch):
                    chunk = coords[b0:b0 + batch]
                    raw = torch.stack([sub[:, y:y + P, x:x + P] for y, x in chunk])
                    keep = raw.reshape(len(chunk), -1).any(dim=1)
                    if not bool(keep.any()):
                        continue
                    if not bool(keep.all()):
                        chunk = [c for c, k in zip(chunk, keep.tolist()) if k]
                        raw = raw[keep]
                    flat = raw.reshape(len(chunk), -1).float()
                    norm = engine.robust_torch(flat) if self.prep == "tifxyz_robust" else flat / 255.0
                    images = norm.reshape(len(chunk), 1, self.depth, P, P)
                    ctx = (torch.autocast("cuda", dtype=self.amp) if dev.type == "cuda" and self.amp is not None
                           else engine._null())
                    with torch.inference_mode(), ctx:
                        logits = model(images)
                    prob = logits.float().sigmoid()
                    if prob.shape[-2:] != (P, P):
                        prob = torch.nn.functional.interpolate(prob, size=(P, P), mode="bilinear", align_corners=False)
                    prob = prob[:, 0]
                    for (y, x), p in zip(chunk, prob):
                        psum[y:y + P, x:x + P] += p * wmap
                        wsum[y:y + P, x:x + P] += wmap
                    n += len(chunk)
                m = torch.where(wsum > 1e-6, psum / wsum.clamp_min(1e-6), torch.zeros_like(psum)).clamp(0, 1)
                out[(key, order)] = m.cpu().numpy().astype(np.float32)
        self.last_patches = n
        return out


# ---------------------------------------------------------------- ink-sdk: Hecate and canonical

def sdk_profile(name, direction=None):
    """The ink-sdk profile of a zoo model (its pins checked against the zoo), with another direction if asked."""
    from ink_sdk.registry import get_profile
    spec = zoo.get(name)
    if not spec.get("sdk_profile"):
        raise RunError(f"{name} has no ink-sdk profile")
    p = get_profile(spec["sdk_profile"])
    w = spec["weights"]
    if w["kind"] != "hf-rebuild" and (p.checkpoint.sha256 != w["sha256"] or p.source.revision != w["revision"]):
        raise RunError(f"{name}: ink-sdk's profile pins {p.checkpoint.sha256[:12]} at {p.source.revision[:12]}, the "
                       f"zoo pins {w['sha256'][:12]} at {w['revision'][:12]}")
    if direction and direction != p.execution.direction:
        p = p.model_copy(update={"execution": p.execution.model_copy(update={"direction": direction})})
    return p


def _prepared(volume, pixel_um, profile):
    import numpy as np
    from ink_sdk.contracts import PreparedInput, ScalePlan
    um = float(pixel_um)
    return PreparedInput(path=Path("in-memory"), array=np.ascontiguousarray(volume), pixel_um=(um, um, um),
                         source=Path("in-memory"), scale_plan=ScalePlan(um, float(profile.input.scale_um), "native"))


class SDKModel:
    """A Hecate or canonical model run through ink-sdk's own adapter, in this process."""

    def __init__(self, name, cache=CACHE, device=None, amp=None):
        spec = zoo.get(name)
        if spec["family"] not in ("hecate", "canonical"):
            raise RunError(f"{name} is not run through ink-sdk here")
        self.name, self.spec, self.cache = name, spec, Path(cache)
        fetch(name, cache)
        self.device = str(device) if device else "auto"
        self.amp = amp
        if spec["family"] == "hecate":
            from ink_sdk.adapters.hecate import HecateAdapter
            self.adapter = HecateAdapter(model_factory=self._cached(spec["family"]))
        else:
            from ink_sdk.adapters.canonical2um import Canonical2umAdapter
            self.adapter = Canonical2umAdapter(model_factory=self._cached(spec["family"]))
        self._model = None
        self.info = {"name": name, "family": spec["family"], "backend": f"ink-sdk {zoo.INK_SDK_COMMIT[:12]}",
                     "depth": spec["depth"]}

    def _cached(self, family):
        """The adapter's model factory, loading once (the adapters load per run)."""
        def factory(checkpoint, device, *rest):
            if self._model is None:
                if family == "hecate":
                    from ink_sdk._vendor import hecate
                    self._model = hecate.load_model(str(checkpoint), device)
                else:
                    from ink_sdk._vendor.canonical.model_resnet3d_3d_decoder import load_model
                    self._model = load_model(str(checkpoint), device, num_frames=rest[0])
            elif hasattr(self._model, "to"):
                self._model.to(device)
            return self._model
        return factory

    def run(self, volume, windows, orders=("forward", "reverse"), pixel_um=None, output_3d=False, workdir=None,
            device=None):
        """{(window key, order): map} and, with output_3d, {(window key, order): uint8 volume} for Hecate. device
        overrides the one given at load (a Space loads on the CPU, then runs inside its GPU call)."""
        import numpy as np
        from ink_sdk.contracts import RunContext
        allowed = tuple(o for o in orders if o in self.spec["orders"])
        if not allowed:
            raise RunError(f"{self.name} runs only {self.spec['orders']}")
        um = float(pixel_um or self.spec["scale_um"])
        maps, vols = {}, {}
        for key, idx in windows.items():
            sub = np.asarray(volume)[idx]
            if len(idx) != self.spec["depth"]:
                raise RunError(f"window {key}: {self.name} reads {self.spec['depth']} layers, got {len(idx)}")
            direction = "both" if len(allowed) == 2 else allowed[0]
            profile = sdk_profile(self.name, direction)
            ctx = RunContext(device=str(device) if device else self.device, models_dir=self.cache / "models", output_3d=bool(output_3d),
                             workdir=Path(workdir) if workdir else None, amp=self.amp)
            raw = self.adapter.run(_prepared(sub, um, profile), profile, ctx)
            for order in allowed:
                maps[(key, order)] = np.asarray(raw.maps[order], np.float32)
            if output_3d and raw.volume is not None:
                vols[(key, direction)] = np.asarray(raw.volume)
        return (maps, vols) if output_3d else maps


# ---------------------------------------------------------------- one entry point

def load(name, cache=CACHE, device=None, amp=None):
    family = zoo.get(name)["family"]
    if family == "villa9":
        return load_villa9(name, cache)
    if family in ("hecate", "canonical"):
        return SDKModel(name, cache, device=device, amp=amp)
    raise RunError(f"{name} reads the scan itself (ct3d): it runs as a Hugging Face Job, see tools/gallery_job.py")


def pool(volume, k):
    """A k x k x k mean pool of a uint8 volume (villa's prepare_9um_isotropic_input pools 2.4 um renders 4x),
    rounded back to uint8; edges that do not fill a block are cut."""
    import numpy as np
    v = np.asarray(volume)
    if k == 1:
        return v
    L, H, W = (s // k * k for s in v.shape)
    v = v[:L, :H, :W].reshape(L // k, k, H // k, k, W // k, k).astype(np.float32).mean(axis=(1, 3, 5))
    return np.rint(v).astype(np.uint8)


def pool_map(m, k):
    """A k x k mean pool of a 2D map, NaN-aware."""
    import numpy as np
    a = np.asarray(m, np.float32)
    if k == 1:
        return a
    H, W = a.shape[0] // k * k, a.shape[1] // k * k
    with np.errstate(invalid="ignore"):
        return np.nanmean(a[:H, :W].reshape(H // k, k, W // k, k), axis=(1, 3)).astype(np.float32)


def timed(fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    return out, round(time.perf_counter() - t0, 3)
