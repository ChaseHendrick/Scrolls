"""Readers that run through the team's koine_machines inference (villa branch merge-ink-pipelines), such as Reader V3.

Ink Lens's engine (engine.py, a copied file this folder never edits) runs 128 px villa-flat readers. Koine readers use
larger patches (Reader V3: 17 x 384 x 384), so they get this small engine with the same contract: run(volume) returns
{"forward", "reverse", ...} float32 maps in 0 to 1, the reverse map from the same layers in reversed depth order. It
follows koine's own inference (koine_machines/inference/infer.py at the pinned commit): the center 17 layers, robust
or /255 preprocessing per patch, sigmoid of the model's logits, patches at 50 % overlap blended with koine's floored
Hann map, all-zero patches skipped. The checkpoint is SHA-256 pinned and loaded with torch.load(weights_only=True).

To add a reader, add an entry to KOINE_READERS (a fixed URL, its SHA-256 and license); app.py lists it.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import engine

KOINE_REPO = engine.VILLA_REPO
KOINE_COMMIT = "3ea17f54a9b3d5fd1aaf73e1d2c8386dbaa9f30e"     # villa merge-ink-pipelines, as the Transfer Matrix ran it
OVERLAP = 0.5

KOINE_READERS = {
    "readerv3": {
        "title": "Reader V3 (Domenico Russo, MIT)",
        "url": "https://huggingface.co/domenicor046/reader-v3/resolve/main/reader-v3.pth",
        "file": "reader-v3.pth",
        "sha256": "ea405417450abd8ace1b8ff79ebce3adb646c5e48ab95da46844d77efe984d8a",
        "license": "MIT",
        "source": "https://huggingface.co/domenicor046/reader-v3",
        "held_out": "author-reported: every published result on data it never trained on, PHerc0841 w00 among them",
    },
}


def ensure_checkpoint(name, cache=engine.CACHE):
    spec = KOINE_READERS[name]
    path = Path(cache) / "checkpoints" / spec["file"]
    if not path.is_file():
        engine._download(spec["url"], path)
    digest = engine.sha256_file(path)
    if digest != spec["sha256"]:
        raise engine.EngineError(f"{path} has SHA-256 {digest}, expected {spec['sha256']} for {name}; refusing it")
    return path


def _tarball(tmp):
    root = tmp.resolve()
    kept = 0
    url = engine.VILLA_TARBALL.format(commit=KOINE_COMMIT)
    req = urllib.request.Request(url, headers={"User-Agent": engine.USER_AGENT})
    with urllib.request.urlopen(req, timeout=900) as resp, tarfile.open(fileobj=resp, mode="r|gz") as tf:
        for m in tf:
            _, _, rel = m.name.partition("/")
            if not rel.startswith("ink-detection/koine_machines/"):
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
        raise engine.EngineError(f"the villa tarball for {KOINE_COMMIT} held no koine_machines files")


def ensure_koine(cache=engine.CACHE):
    """koine_machines on sys.path (KOINE_SRC, a local ink-detection folder, when set), plus villa's vesuvius package
    from engine.ensure_villa for the robust normalization koine imports."""
    engine.ensure_villa(cache)
    if os.environ.get("KOINE_SRC"):
        src = Path(os.environ["KOINE_SRC"]).expanduser().resolve()
    else:
        dest = Path(cache) / f"koine-{KOINE_COMMIT[:12]}"
        if not (dest / "COMMIT").is_file():
            tmp = dest.with_name(dest.name + ".part")
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            try:
                git = ["git", "-C", str(tmp)]
                for cmd in (["init", "-q"], ["remote", "add", "origin", KOINE_REPO],
                            ["sparse-checkout", "set", "ink-detection/koine_machines"],
                            ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", KOINE_COMMIT],
                            ["checkout", "-q", "FETCH_HEAD"]):
                    subprocess.run(git + cmd, capture_output=True, text=True, check=True, timeout=900)
            except (OSError, subprocess.SubprocessError):
                shutil.rmtree(tmp, ignore_errors=True)
                tmp.mkdir(parents=True)
                _tarball(tmp)
            (tmp / "COMMIT").write_text(KOINE_COMMIT + "\n")
            shutil.rmtree(dest, ignore_errors=True)
            os.replace(tmp, dest)
        src = dest / "ink-detection"
    if not (src / "koine_machines" / "inference" / "infer.py").is_file():
        raise engine.EngineError(f"{src} holds no koine_machines package")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return {"koine": KOINE_COMMIT, "villa": engine.VILLA_COMMIT}


def load(name, cache=engine.CACHE):
    """(model, info) for one koine reader, built by koine's own builder from the checkpoint's config."""
    import torch
    versions = ensure_koine(cache)
    path = ensure_checkpoint(name, cache)
    from koine_machines.inference import infer
    payload = torch.load(str(path), map_location="cpu", weights_only=True)
    cm = infer.build_repo_training_model_bundle(payload, path)
    amp = infer.resolve_amp_dtype(amp_dtype_arg="auto", checkpoint_payload=payload, checkpoint_path=path)
    del payload
    info = {"name": name, "engine": "koine", "patch": int(cm.roi_size), "depth": int(cm.in_chans),
            "preprocessing": cm.preprocessing, "amp_on_cuda": str(amp).replace("torch.", ""),
            "sha256": KOINE_READERS[name]["sha256"], "url": KOINE_READERS[name]["url"],
            "license": KOINE_READERS[name]["license"], "loader": "weights_only=True", **versions}
    return cm.model.eval(), info, amp


def positions(length, patch, stride):
    """Patch starts covering 0..length, the last flush with the end (one start when the region is smaller)."""
    if length <= patch:
        return [0]
    n = math.ceil((length - patch) / stride) + 1
    starts = [i * stride for i in range(n - 1)] + [length - patch]
    return sorted(set(starts))


def hann(patch):
    import torch
    w = torch.outer(torch.hann_window(patch, periodic=False), torch.hann_window(patch, periodic=False))
    return torch.clamp(w / w.max(), min=1e-3)


def patches(height, width, patch=384):
    stride = max(1, round(patch * (1 - OVERLAP)))
    return len(positions(height, patch, stride)) * len(positions(width, patch, stride)) * 2


class KoineReader:
    """One koine reader, loaded once (on the CPU; run() moves it to the call's device)."""

    def __init__(self, name, cache=engine.CACHE, model=None, info=None):
        if model is None:
            model, info, self.amp = load(name, cache)
        else:
            self.amp = None
        self.name, self.model, self.info = name, model, info

    def run(self, volume, device="cpu", batch=4):
        import numpy as np
        import torch
        t0 = time.perf_counter()
        dev = torch.device(device)
        vol = np.asarray(volume)
        L, H, W = vol.shape
        depth, patch = self.info["depth"], self.info["patch"]
        if L < depth:
            raise engine.EngineError(f"{L} layers: {self.name} reads {depth}")
        start = L // 2 - depth // 2               # koine's center crop (upper center when uneven)
        sub = vol[start:start + depth]
        ph, pw = max(H, patch), max(W, patch)     # a region smaller than one patch is padded with zeros
        padded = np.zeros((depth, ph, pw), np.uint8)
        padded[:, :H, :W] = sub
        stride = max(1, round(patch * (1 - OVERLAP)))
        coords = [(y, x) for y in positions(ph, patch, stride) for x in positions(pw, patch, stride)]
        wmap = hann(patch).to(dev)
        model = self.model.to(dev)
        robust = self.info["preprocessing"] == "tifxyz_robust"
        if robust:
            from vesuvius.image_proc.intensity.normalization import normalize_robust
        maps, n = {}, 0
        for direction in ("forward", "reverse"):
            stack = padded if direction == "forward" else padded[::-1]
            psum = torch.zeros((ph, pw), dtype=torch.float32, device=dev)
            wsum = torch.zeros((ph, pw), dtype=torch.float32, device=dev)
            for b0 in range(0, len(coords), batch):
                chunk = [(y, x) for y, x in coords[b0:b0 + batch] if stack[:, y:y + patch, x:x + patch].any()]
                if not chunk:
                    continue
                arrs = []
                for y, x in chunk:
                    p = np.ascontiguousarray(stack[:, y:y + patch, x:x + patch])
                    arrs.append(normalize_robust(p) if robust else p.astype(np.float32) / 255.0)
                images = torch.from_numpy(np.stack(arrs).astype(np.float32))[:, None].to(dev)
                ctx = (torch.autocast("cuda", dtype=self.amp) if dev.type == "cuda" and self.amp is not None
                       else engine._null())
                with torch.inference_mode(), ctx:
                    logits = model(images)
                prob = logits.float().sigmoid()
                if prob.shape[-2:] != (patch, patch):
                    prob = torch.nn.functional.interpolate(prob, size=(patch, patch), mode="bilinear",
                                                           align_corners=False)
                for (y, x), pr in zip(chunk, prob[:, 0]):
                    psum[y:y + patch, x:x + patch] += pr * wmap
                    wsum[y:y + patch, x:x + patch] += wmap
                n += len(chunk)
            out = torch.where(wsum > 1e-6, psum / wsum.clamp_min(1e-6), torch.zeros_like(psum)).clamp(0, 1)
            maps[direction] = out[:H, :W].cpu().numpy().astype(np.float32)
        return {"forward": maps["forward"], "reverse": maps["reverse"], "patches": n,
                "layers": [start, start + depth], "seconds": round(time.perf_counter() - t0, 3)}
