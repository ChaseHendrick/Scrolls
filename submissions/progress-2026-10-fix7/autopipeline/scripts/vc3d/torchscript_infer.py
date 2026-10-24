"""Headless flat ink inference on a pooled surface-volume zarr box, with a TorchScript ink model.

Self-contained (numpy, torch, zarr); no villa import, so it can be copied with a TorchScript
model (a TorchScript export of an ink checkpoint) to a machine outside any repository. It reproduces villa's
flat inference contract for ink_9um (`vesuvius.ink_detection.inference.infer`): per-patch
robust normalization (clip to the 1st and 99th percentiles, subtract the median, divide by
1.4826 MAD), center crop of the selected slice window to the model depth, optional depth
reversal, sigmoid, floored Hann blending of 128 px patches, all-zero patches skipped.

Variants: f = forward, r = depth reversed (center-cropped slices flipped), s = depth shuffled
(the window slices permuted by numpy default_rng(seed).permutation(n) before the center crop).

Output: uint8 .npy (rint(255 * blended probability)), shape of the box, 0 where no patch.
A JSON sidecar records settings, patch count, wall time and the device.

  python torchscript_infer.py ZARR MODEL.pt OUT.npy --box r0,r1,c0,c1 --slices 1,22 --variant f
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

PATCH = 128


def normalize_robust(patch: np.ndarray) -> np.ndarray:
    """villa normalize_robust(patch) with default arguments (whole patch, clip 1..99 %).

    Non-negative integer patches up to 16 bits take the histogram route, which gives the same
    float32 result to the bit; anything else takes the direct route."""
    p = np.asarray(patch)
    if p.size and p.dtype.kind in "ui" and int(p.min()) >= 0 and int(p.max()) <= 65535:
        return _normalize_robust_hist(p)
    return _normalize_robust_direct(p)


def _normalize_robust_hist(p: np.ndarray) -> np.ndarray:
    """normalize_robust from the value histogram. np.percentile and np.median depend only on the
    multiset of values, so each runs on a sorted array with the same multiset, and the float32
    steps run once per distinct value, then map back through a lookup table."""
    cnt = np.bincount(p.ravel())
    present = np.flatnonzero(cnt)
    k = cnt[present]
    vals = present.astype(np.float32)
    lo, hi = np.percentile(np.repeat(vals, k), [1.0, 99.0], overwrite_input=True)
    c = vals.copy()
    np.clip(c, lo, hi, out=c)                       # monotone, so c stays sorted
    med = float(np.median(np.repeat(c, k), overwrite_input=True))
    dev = np.abs(c - med)
    o = np.argsort(dev, kind="stable")
    smad = 1.4826 * float(np.median(np.repeat(dev[o], k[o]), overwrite_input=True))
    if not np.isfinite(smad) or smad < 1e-6:
        std_pre = float(np.asarray(p, dtype=np.float32).std())
        cands = [x for x in (abs(std_pre), abs(hi - lo) / 2.0) if np.isfinite(x) and x >= 1e-6]
        smad = cands[0] if cands else 1.0
    c -= med
    c /= smad
    np.nan_to_num(c, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    lut = np.zeros(cnt.size, np.float32)
    lut[present] = c
    return lut[p]


def _normalize_robust_direct(patch: np.ndarray) -> np.ndarray:
    arr = np.asarray(patch, dtype=np.float32).copy()
    if arr.size == 0:
        return arr
    std_pre = float(arr.std())
    mn, mx = float(arr.min()), float(arr.max())
    lo, hi = np.percentile(arr, [1.0, 99.0])
    np.clip(arr, lo, hi, out=arr)
    med = float(np.median(arr))
    smad = 1.4826 * float(np.median(np.abs(arr - med)))
    if not np.isfinite(smad) or smad < 1e-6:
        cands = [c for c in (abs(std_pre), abs(hi - lo) / 2.0) if np.isfinite(c) and c >= 1e-6]
        smad = cands[0] if cands else 1.0
    arr -= med
    arr /= smad
    np.nan_to_num(arr, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return arr


def slice_order(window: tuple[int, int], depth: int, variant: str, seed: int = 20261007) -> np.ndarray:
    """Indices into the pooled stack fed to the model, in order."""
    idx = np.arange(window[0], window[1])
    if variant == "s":
        idx = idx[np.random.default_rng(seed).permutation(idx.size)]
    if idx.size > depth:
        start = idx.size // 2 - depth // 2
        idx = idx[start:start + depth]
    elif idx.size < depth:
        raise ValueError(f"window has {idx.size} slices, model needs {depth}")
    if variant == "r":
        idx = idx[::-1]
    elif variant not in ("f", "s"):
        raise ValueError(f"variant must be f, r or s, got {variant!r}")
    return idx


def hann2d(n: int = PATCH) -> np.ndarray:
    w = np.hanning(n).astype(np.float32)  # symmetric, same as torch.hann_window(periodic=False)
    m = np.outer(w, w)
    m /= max(float(m.max()), 1e-12)
    return np.maximum(m, 0.001).astype(np.float32)


def positions(lo: int, hi: int, stride: int, patch: int = PATCH) -> list[int]:
    """Top-left positions covering [lo, hi) with the last patch flush to hi (villa style)."""
    n = hi - lo
    if n <= patch:
        return [lo]
    out = list(range(lo, hi - patch + 1, stride))
    if out[-1] != hi - patch:
        out.append(hi - patch)
    return out


def load_model(model_path):
    """(model in eval mode on the CPU, its meta.json or {}), from one load of the TorchScript file."""
    import torch
    extra = {"meta.json": ""}
    model = torch.jit.load(model_path, map_location="cpu", _extra_files=extra).eval()
    return model, json.loads(extra["meta.json"] or "{}")


def run(zarr_path, model_path, out_path, box, window, variant, stride=96, batch=16, device="cpu",
        dtype="fp32", threads=3, seed=20261007, battery_guard=False, log_every=200, loaded=None):
    """loaded: load_model(model_path)'s result, so callers running several variants load once."""
    import torch
    import zarr
    if device == "cpu":
        torch.set_num_threads(int(threads))
    arr = zarr.open_group(zarr_path, mode="r")["0"]
    model, meta = loaded if loaded is not None else load_model(model_path)
    depth = int(meta.get("input_depth", 17))
    model = model.to(device)
    order = slice_order(window, depth, variant, seed)
    r0, r1, c0, c1 = box
    H, W = r1 - r0, c1 - c0
    tmp = out_path + ".acc"
    acc = np.lib.format.open_memmap(tmp + ".sum.npy", mode="w+", dtype=np.float32, shape=(H, W))
    wsum = np.lib.format.open_memmap(tmp + ".w.npy", mode="w+", dtype=np.float32, shape=(H, W))
    wmap = hann2d()
    ys, xs = positions(r0, r1, stride), positions(c0, c1, stride)
    amp = None
    kind = torch.device(device).type          # the bare type autocast documents; cuda:1 would skip its CUDA check
    if dtype == "bf16":
        amp = torch.autocast(device_type=kind, dtype=torch.bfloat16)
    elif dtype == "fp16":
        amp = torch.autocast(device_type=kind, dtype=torch.float16)
    t0 = time.time()
    n_run = n_skip = 0
    pend_x, pend_pos = [], []

    def flush():
        nonlocal n_run
        if not pend_x:
            return
        x = torch.from_numpy(np.stack(pend_x)[:, None]).to(device)
        with torch.inference_mode():
            if amp is not None:
                with amp:
                    lg = model(x)
            else:
                lg = model(x)
            pr = lg.float().sigmoid()
            if pr.shape[-2:] != (PATCH, PATCH):
                pr = torch.nn.functional.interpolate(pr, size=(PATCH, PATCH), mode="bilinear",
                                                     align_corners=False)
            pr = pr.cpu().numpy()[:, 0]
        for p, (y, xx) in zip(pr, pend_pos):
            acc[y - r0:y - r0 + PATCH, xx - c0:xx - c0 + PATCH] += p * wmap
            wsum[y - r0:y - r0 + PATCH, xx - c0:xx - c0 + PATCH] += wmap
        n_run += len(pend_x)
        pend_x.clear()
        pend_pos.clear()

    total = len(ys) * len(xs)
    k = 0
    for y in ys:
        strip = np.asarray(arr[:, y:y + PATCH, c0:c1])[order]  # (depth, 128, W)
        for xx in xs:
            k += 1
            p = strip[:, :, xx - c0:xx - c0 + PATCH]
            if p.shape[1:] != (PATCH, PATCH):
                q = np.zeros((p.shape[0], PATCH, PATCH), p.dtype)
                q[:, :p.shape[1], :p.shape[2]] = p
                p = q
            if not p.any():
                n_skip += 1
                continue
            pend_x.append(normalize_robust(p))
            pend_pos.append((y, xx))
            if len(pend_x) >= batch:
                flush()
            if log_every and k % log_every == 0:
                el = time.time() - t0
                print(f"{k}/{total} run={n_run} skip={n_skip} {el:.0f}s "
                      f"{el / max(n_run, 1):.3f}s/patch", flush=True)
                if battery_guard:
                    _battery_wait()
    flush()
    out = np.zeros((H, W), np.uint8)
    nz = wsum[:] > 0
    out[nz] = np.rint(255.0 * np.clip(acc[nz] / wsum[nz], 0, 1)).astype(np.uint8)
    np.save(out_path, out)
    del acc, wsum
    for s in (".sum.npy", ".w.npy"):
        os.remove(tmp + s)
    info = {"zarr": zarr_path, "model": os.path.basename(model_path), "model_meta": meta, "box": list(box),
            "window": list(window), "variant": variant, "slice_order": order.tolist(), "stride": stride,
            "batch": batch, "device": device, "dtype": dtype, "threads": threads, "patches_run": n_run,
            "patches_skipped_empty": n_skip, "wall_s": round(time.time() - t0, 1)}
    with open(out_path + ".json", "w") as fh:
        json.dump(info, fh, indent=1)
    print(json.dumps(info), flush=True)
    return info


def _battery_wait(min_pct=25, poll_s=120):
    """On a Mac on battery below min_pct, pause until it is charging or above the limit."""
    import subprocess
    while True:
        try:
            s = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
        except OSError:
            return
        if "Battery Power" not in s:
            return
        try:
            pct = int(s.split("%")[0].split()[-1])
        except (ValueError, IndexError):
            return
        if pct >= min_pct:
            return
        print(f"battery {pct}% on battery power: pausing", flush=True)
        time.sleep(poll_s)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("zarr")
    p.add_argument("model")
    p.add_argument("out")
    p.add_argument("--box", required=True, help="canvas r0,r1,c0,c1 (level-2 px)")
    p.add_argument("--slices", default="1,22", help="pooled slice window start,end")
    p.add_argument("--variant", default="f", choices=("f", "r", "s"))
    p.add_argument("--stride", type=int, default=96)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--device", default="cpu")
    p.add_argument("--dtype", default="fp32", choices=("fp32", "bf16", "fp16"))
    p.add_argument("--threads", type=int, default=3)
    p.add_argument("--seed", type=int, default=20261007)
    p.add_argument("--battery-guard", action="store_true")
    a = p.parse_args(argv)
    box = tuple(int(v) for v in a.box.split(","))
    win = tuple(int(v) for v in a.slices.split(","))
    run(a.zarr, a.model, a.out, box, win, a.variant, a.stride, a.batch, a.device, a.dtype, a.threads,
        a.seed, a.battery_guard)
    return 0


if __name__ == "__main__":
    sys.exit(main())
