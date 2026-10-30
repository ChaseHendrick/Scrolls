"""AFV V2 fiber probabilities over one box of an open-data scan, for whole-scroll AFV fiber volumes.

  python3 afv_tile.py infer --ct URL --core Z0 Z1 Y0 Y1 X0 X1 --weights DIR --out DIR [--norm window|tile]
        [--step 64] [--batch 4] [--max-windows N] [--channels-last] [--compile] [--budget-s S]
  python3 afv_tile.py bench --weights DIR [--batch 4] [--n 64]          (model throughput on random input)

The model is Qual's AFV fiber model V2 (https://huggingface.co/Qualzz20/afv_fiber_9um_v2, Apache-2.0), loaded with
its own model.py. Inference follows the recipe on the V1 model card: 128^3 windows, a 64-voxel stride, Gaussian
blending, bf16, no mirroring. Windows sit on one lattice fixed to the whole volume (multiples of the stride), and a box
reads the windows that touch its core, so a cropped run gives the same values as an uncropped one whenever the
normalization does not depend on the crop. `--norm window` normalizes each window by its own mean and standard
deviation (model.py's default call, crop independent); `--norm tile` uses one mean and deviation over the nonzero
voxels the box reads (closer to the trainer's 640^3 region statistics, but it depends on the box).

Outputs, under --out: v.npy and h.npy (uint8, probability x 255, the core box), and result.json (timings, windows,
throughput). Channel order of the model: background, vertical, horizontal, intersection; v and h are the softmax
probabilities of channels 1 and 2. Model output about texture, not a reading.
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

WIN = 128


def zarray(url):
    with urllib.request.urlopen(url.rstrip("/") + "/.zarray", timeout=60) as r:
        meta = json.load(r)
    assert meta["dtype"] in ("|u1", "<u1") and meta["compressor"] is None and meta["order"] == "C", meta
    assert meta.get("dimension_separator", ".") == "/", meta
    return meta


def fetch_box(url, meta, lo, hi, workers=32):
    """uint8 array of the volume over [lo, hi) (zyx), zero outside the volume and in chunks not stored."""
    lo, hi = np.asarray(lo), np.asarray(hi)
    shape, ch = np.asarray(meta["shape"]), np.asarray(meta["chunks"])
    out = np.zeros(tuple(hi - lo), np.uint8)
    c0 = np.maximum(lo, 0) // ch
    c1 = (np.minimum(hi, shape) + ch - 1) // ch
    keys = [(a, b, c) for a in range(c0[0], c1[0]) for b in range(c0[1], c1[1]) for c in range(c0[2], c1[2])]
    stats = {"chunks": len(keys), "stored": 0, "bytes": 0}

    def get(k):
        for attempt in range(6):
            try:
                with urllib.request.urlopen(f"{url.rstrip('/')}/{k[0]}/{k[1]}/{k[2]}", timeout=120) as r:
                    return k, r.read()
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    return k, None
                time.sleep(2 ** attempt)
            except Exception:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"chunk {k} failed")

    with ThreadPoolExecutor(workers) as pool:
        for k, data in pool.map(get, keys):
            if data is None:
                continue
            k = np.asarray(k)
            full = np.minimum(ch, shape - k * ch)          # edge chunks are stored full size in zarr v2
            arr = np.frombuffer(data, np.uint8)
            arr = arr.reshape(tuple(ch)) if arr.size == ch.prod() else arr.reshape(tuple(full))
            arr = arr[:full[0], :full[1], :full[2]]
            g0 = k * ch
            s0 = np.maximum(g0, lo)
            s1 = np.minimum(g0 + full, hi)
            if (s1 <= s0).any():
                continue
            out[tuple(slice(a - b, c - b) for a, b, c in zip(s0, lo, s1))] = \
                arr[tuple(slice(a - b, c - b) for a, b, c in zip(s0, g0, s1))]
            stats["stored"] += 1
            stats["bytes"] += len(data)
    return out, stats


def gaussian(win=None, sigma_scale=1 / 8):
    """nnU-Net's Gaussian importance map: sigma = win / 8, scaled to max 1, zeros raised to the smallest nonzero."""
    win = win or WIN
    c = (np.arange(win) - (win - 1) / 2) / (win * sigma_scale)
    g1 = np.exp(-0.5 * c ** 2)
    g = g1[:, None, None] * g1[None, :, None] * g1[None, None, :]
    g = g / g.max()
    g[g == 0] = g[g > 0].min()
    return g.astype(np.float32)


def lattice(core_lo, core_hi, step, shape):
    """Window origins on the global lattice (multiples of step, clamped so a window never starts past shape - WIN)
    whose window touches the core."""
    axes = []
    for a in range(3):
        last = max(0, shape[a] - WIN)
        starts = set()
        p = max(0, ((core_lo[a] - WIN + 1) // step) * step)
        while p < core_hi[a]:
            q = min(p, last)
            if q + WIN > core_lo[a]:
                starts.add(q)
            p += step
        if last < core_hi[a] and last + WIN > core_lo[a]:
            starts.add(last)
        axes.append(sorted(starts))
    return axes


def load(weights, device, channels_last, compile_, mode=None):
    import torch
    sys.path.insert(0, str(weights))
    from model import load_model
    m = load_model(weights, device=device)
    if channels_last:
        m = m.to(memory_format=torch.channels_last_3d)
    if compile_:
        m = torch.compile(m, mode=mode) if mode else torch.compile(m)
    return m


def predict_box(ctg_box, rlo, rhi, clo, chi, model, step, norm, batch, channels_last, dev, g, say=print):
    """Probabilities over [clo, chi) from CT already on the device over [rlo, rhi): (v, h) uint8 and the 2x average
    pooled (v, h) uint8 (pooled before quantization, as the spline generator prefers), plus the windows run."""
    import torch
    shape_r = tuple(int(v) for v in (rhi - rlo))
    axes = []
    for j in range(3):
        starts = list(range(int(rlo[j]), int(rhi[j]) - WIN + 1, step))
        axes.append(starts)
    origins = [(z, y, x) for z in axes[0] for y in axes[1] for x in axes[2]]
    keep = []
    for o in origins:
        sl = tuple(slice(o[i] - rlo[i], o[i] - rlo[i] + WIN) for i in range(3))
        if bool(ctg_box[sl].any()):
            keep.append(o)
    acc = torch.zeros((2,) + shape_r, dtype=torch.float32, device=dev)
    wsum = torch.zeros(shape_r, dtype=torch.float32, device=dev)
    with torch.inference_mode(), torch.autocast(dev, dtype=torch.bfloat16, enabled=(dev == "cuda")):
        for i in range(0, len(keep), batch):
            group = keep[i:i + batch]
            sls = [tuple(slice(int(o[j] - rlo[j]), int(o[j] - rlo[j] + WIN)) for j in range(3)) for o in group]
            x = torch.stack([ctg_box[s] for s in sls])[:, None].float()
            if len(group) < batch:      # a full batch every call, so a compiled model never recompiles
                x = torch.cat([x, x[:1].expand(batch - len(group), -1, -1, -1, -1)])
            if norm == "window":
                mean = x.mean(dim=(2, 3, 4), keepdim=True)
                std = x.std(dim=(2, 3, 4), keepdim=True)
                x = (x - mean) / std.clamp_min(10.0)
            else:
                raise ValueError("tiles use per-window normalization only (crop independent)")
            if channels_last:
                x = x.contiguous(memory_format=torch.channels_last_3d)
            p = torch.softmax(model(x)["seg"].float(), 1)[:, 1:3]
            for k, s_ in enumerate(sls):
                acc[(slice(None),) + s_] += p[k] * g
                wsum[s_] += g
    cs = tuple(slice(int(clo[j] - rlo[j]), int(chi[j] - rlo[j])) for j in range(3))
    # Normalize, quantize and pool in z slabs of SLAB planes (even, so the 2x pooling never straddles two slabs):
    # the same elementwise arithmetic as on the whole core at once, so the bytes are identical, without a second
    # full-size float copy on the GPU (a dense 1,024^3 core next to a compiled model's CUDA graph pools ran out of
    # memory on an RTX PRO 6000, 28 Oct).
    SLAB = 128
    nz = int(chi[0] - clo[0])
    ez = [int(chi[j] - clo[j]) // 2 * 2 for j in range(3)]
    q = np.zeros((2,) + tuple(int(chi[j] - clo[j]) for j in range(3)), np.uint8)
    pq = np.zeros((2, ez[0] // 2, ez[1] // 2, ez[2] // 2), np.uint8)
    for z0 in range(0, nz, SLAB):
        z1 = min(z0 + SLAB, nz)
        zs = slice(cs[0].start + z0, cs[0].start + z1)
        w = wsum[zs, cs[1], cs[2]]
        prob = acc[:, zs, cs[1], cs[2]] / w.clamp_min(1e-6)
        prob[:, w == 0] = 0
        q[:, z0:z1] = (prob * 255).round().clamp(0, 255).to(torch.uint8).cpu().numpy()
        pz1 = min(z1, ez[0])
        if pz1 > z0:
            pp = prob[:, :pz1 - z0, :ez[1], :ez[2]]
            pooled = torch.nn.functional.avg_pool3d(pp[None], 2)[0]
            pq[:, z0 // 2:pz1 // 2] = (pooled * 255).round().clamp(0, 255).to(torch.uint8).cpu().numpy()
        del w, prob
    del acc, wsum
    return q, pq, len(keep), len(origins)


def tiles(a):
    """Many 1,024^3 tiles of one scan in one Job, CT prefetched one tile ahead, each tile's 512^3 blocks (native) and
    256^3 pooled blocks written blosc-zstd compressed and uploaded to the bucket by a background thread."""
    import queue
    import threading
    import numcodecs
    import torch
    t0 = time.time()
    torch.backends.cudnn.benchmark = True
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    plan = json.loads(Path(a.plan).read_text())
    ct = plan["ct"]
    meta = zarray(ct)
    shape = np.array(meta["shape"])
    model = load(Path(a.weights), dev, False, a.compile, a.compile_mode)
    g = torch.from_numpy(gaussian()).to(dev)
    codec = numcodecs.Blosc(cname="zstd", clevel=3, shuffle=numcodecs.Blosc.BITSHUFFLE)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ids = set(a.ids or [])
    if a.job is not None:
        ids |= set(plan["jobs"][a.job])
    todo = [t for t in plan["tiles"] if t["id"] in ids] if ids else plan["tiles"]
    up_q = queue.Queue()
    errors = []

    def uploader():
        api = None
        if a.bucket:
            from huggingface_hub import HfApi
            api = HfApi()
        while True:
            item = up_q.get()
            if item is None:
                return
            files, done_mark = item
            for attempt in range(6):
                try:
                    if api is not None:
                        api.batch_bucket_files(a.bucket, add=[(str(f), f"{a.prefix}/{f.relative_to(out)}")
                                                              for f in files + [done_mark]])
                        for f in files:
                            f.unlink()
                    break
                except Exception as e:  # noqa: BLE001 (retry any upload error, then record it)
                    if attempt == 5:
                        errors.append(f"{done_mark.name}: {e}")
                    time.sleep(2 ** attempt)

    up = threading.Thread(target=uploader, daemon=True)
    up.start()

    def reads(t):
        clo = np.array(t["core"][0::2])
        chi = np.minimum(np.array(t["core"][1::2]), shape)
        # every window on the global lattice (origins at multiples of the step) that touches the core; windows past
        # the volume's edge read zeros, the same in every tile, so tiles stay crop independent
        rlo = ((clo - WIN) // a.step + 1) * a.step
        rhi = ((chi - 1) // a.step) * a.step + WIN
        return clo, chi, rlo, rhi

    pre_q = queue.Queue(maxsize=1)

    def prefetch():
        for t in todo:
            clo, chi, rlo, rhi = reads(t)
            box, st = fetch_box(ct, meta, rlo, rhi, workers=48)
            pre_q.put((t, box, st))
        pre_q.put(None)

    threading.Thread(target=prefetch, daemon=True).start()
    rows = []
    n = 0
    while True:
        item = pre_q.get()
        if item is None:
            break
        t, box, st = item
        ts = time.time()
        clo, chi, rlo, rhi = reads(t)
        ctg = torch.from_numpy(box).to(dev)
        q, pq, nrun, nlat = predict_box(ctg, rlo, rhi, clo, chi, model, a.step, "window", a.batch, False, dev, g)
        del ctg
        files = []
        B = 512
        for bz in range(0, q.shape[1], B):
            for by in range(0, q.shape[2], B):
                for bx in range(0, q.shape[3], B):
                    blk = q[:, bz:bz + B, by:by + B, bx:bx + B]
                    if not blk.any():
                        continue
                    z, y, x = (int(clo[0]) + bz, int(clo[1]) + by, int(clo[2]) + bx)
                    f = out / "native" / f"{z}_{y}_{x}.blosc"
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(codec.encode(np.ascontiguousarray(blk)))
                    files.append(f)
                    pb = pq[:, bz // 2:(bz + B) // 2, by // 2:(by + B) // 2, bx // 2:(bx + B) // 2]
                    f2 = out / "pooled" / f"{z}_{y}_{x}.blosc"
                    f2.parent.mkdir(parents=True, exist_ok=True)
                    f2.write_bytes(codec.encode(np.ascontiguousarray(pb)))
                    files.append(f2)
        row = {"id": t["id"], "core": t["core"], "windows_run": nrun, "windows_lattice": nlat, "blocks": len(files) // 2,
               "fetch": st, "infer_s": round(time.time() - ts, 2),
               "block_shapes": "native (2, <=512, <=512, <=512) uint8 VH; pooled (2, <=256, <=256, <=256)"}
        mark = out / "tiles" / f"{t['id']}.json"
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(json.dumps(row))
        up_q.put((files, mark))
        rows.append(row)
        n += 1
        print(f"PROGRESS {n}/{len(todo)} tile {t['id']} windows {nrun} in {row['infer_s']} s", flush=True)
        if a.budget_s and time.time() - t0 > a.budget_s:
            print(f"budget reached after {n} of {len(todo)} tiles", flush=True)
            break
    up_q.put(None)
    up.join()
    summary = {"tiles_done": n, "tiles_planned": len(todo), "errors": errors, "total_s": round(time.time() - t0, 1),
               "windows": sum(r["windows_run"] for r in rows),
               "gpu": torch.cuda.get_device_name(0) if dev == "cuda" else None}
    print(json.dumps(summary), flush=True)
    return 1 if errors else 0


def infer(a):
    import torch
    t0 = time.time()
    torch.backends.cudnn.benchmark = True
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    meta = zarray(a.ct)
    shape = meta["shape"]
    clo, chi = np.array(a.core[0::2]), np.array(a.core[1::2])
    chi = np.minimum(chi, shape)
    axes = lattice(clo, chi, a.step, shape)
    rlo = np.array([ax[0] for ax in axes])
    rhi = np.array([ax[-1] + WIN for ax in axes])
    ct, fstats = fetch_box(a.ct, meta, rlo, rhi)
    t_fetch = time.time() - t0
    origins = [(z, y, x) for z in axes[0] for y in axes[1] for x in axes[2]]
    # windows with no CT at all write nothing and cost nothing (masked volumes are zero outside the scroll)
    keep = []
    for o in origins:
        sl = tuple(slice(o[i] - rlo[i], o[i] - rlo[i] + WIN) for i in range(3))
        if ct[sl].any():
            keep.append(o)
    if a.max_windows:
        keep = keep[:a.max_windows]
    nz = ct[ct > 0]
    tile_mean = float(nz.mean()) if nz.size else 0.0
    tile_std = float(nz.std()) if nz.size else 10.0
    model = load(Path(a.weights), dev, a.channels_last, a.compile, a.compile_mode)
    g = torch.from_numpy(gaussian()).to(dev)
    acc = torch.zeros((2,) + tuple(int(v) for v in (rhi - rlo)), dtype=torch.float32, device=dev)
    wsum = torch.zeros(tuple(int(v) for v in (rhi - rlo)), dtype=torch.float32, device=dev)
    ctg = torch.from_numpy(ct).to(dev)
    t1 = time.time()
    done = 0
    budget_end = t0 + a.budget_s if a.budget_s else None
    with torch.inference_mode(), torch.autocast(dev, dtype=torch.bfloat16, enabled=(dev == "cuda")):
        for i in range(0, len(keep), a.batch):
            group = keep[i:i + a.batch]
            sls = [tuple(slice(int(o[j] - rlo[j]), int(o[j] - rlo[j] + WIN)) for j in range(3)) for o in group]
            x = torch.stack([ctg[s] for s in sls])[:, None].float()
            if a.norm == "window":
                mean = x.mean(dim=(2, 3, 4), keepdim=True)
                std = x.std(dim=(2, 3, 4), keepdim=True)
            else:
                mean = torch.full((len(group), 1, 1, 1, 1), tile_mean, device=dev)
                std = torch.full((len(group), 1, 1, 1, 1), tile_std, device=dev)
            x = (x - mean) / std.clamp_min(10.0)
            if a.channels_last:
                x = x.contiguous(memory_format=torch.channels_last_3d)
            p = torch.softmax(model(x)["seg"].float(), 1)[:, 1:3]
            for k, s in enumerate(sls):
                acc[(slice(None),) + s] += p[k] * g
                wsum[s] += g
            done += len(group)
            if done % (a.batch * 64) == 0:
                print(f"PROGRESS {done}/{len(keep)}", flush=True)
            if budget_end and time.time() > budget_end:
                raise SystemExit(f"budget reached after {done} of {len(keep)} windows")
    if dev == "cuda":
        torch.cuda.synchronize()
    t_inf = time.time() - t1
    cs = tuple(slice(int(clo[j] - rlo[j]), int(chi[j] - rlo[j])) for j in range(3))
    prob = acc[(slice(None),) + cs] / wsum[cs].clamp_min(1e-6)
    prob[:, wsum[cs] == 0] = 0
    q = (prob * 255).round().clamp(0, 255).to(torch.uint8).cpu().numpy()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "v.npy", q[0])
    np.save(out / "h.npy", q[1])
    res = {"ct": a.ct, "core_zyx": [[int(clo[i]), int(chi[i])] for i in range(3)],
           "read_zyx": [[int(rlo[i]), int(rhi[i])] for i in range(3)], "step": a.step, "norm": a.norm,
           "tile_mean": tile_mean, "tile_std": tile_std, "windows_lattice": len(origins), "windows_run": len(keep),
           "batch": a.batch, "channels_last": a.channels_last, "compile": a.compile, "compile_mode": a.compile_mode,
           "device": dev,
           "gpu": torch.cuda.get_device_name(0) if dev == "cuda" else None, "fetch": fstats,
           "fetch_s": round(t_fetch, 2), "infer_s": round(t_inf, 2),
           "windows_per_s": round(len(keep) / t_inf, 3) if t_inf > 0 else None,
           "total_s": round(time.time() - t0, 2), "torch": torch.__version__}
    (out / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res), flush=True)
    return 0


def bench(a):
    import torch
    torch.backends.cudnn.benchmark = True
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    rows = []
    for cl in ([False, True] if dev == "cuda" and a.channels_last_too else [False]):
        for batch in a.batches:
            model = load(Path(a.weights), dev, cl, a.compile, a.compile_mode)
            x = torch.randint(0, 255, (batch, 1, WIN, WIN, WIN), device=dev).float()
            x = (x - x.mean()) / x.std()
            if cl:
                x = x.contiguous(memory_format=torch.channels_last_3d)
            dt_ = {"bf16": torch.bfloat16, "fp16": torch.float16}[a.dtype]
            with torch.inference_mode(), torch.autocast(dev, dtype=dt_, enabled=(dev == "cuda")):
                for _ in range(3):
                    model(x)
                if dev == "cuda":
                    torch.cuda.synchronize()
                t = time.time()
                for _ in range(a.n):
                    model(x)
                if dev == "cuda":
                    torch.cuda.synchronize()
                dt = time.time() - t
            rows.append({"win": WIN, "compile": a.compile, "mode": a.compile_mode, "dtype": a.dtype,
                         "gpu": torch.cuda.get_device_name(0) if dev == "cuda" else None,
                         "channels_last": cl, "batch": batch,
                         "windows_per_s": round(a.n * batch / dt, 3),
                         "voxels_per_s": round(a.n * batch * WIN ** 3 / dt),
                         "max_mem_gb": round(torch.cuda.max_memory_allocated() / 2 ** 30, 2) if dev == "cuda" else None})
            print(json.dumps(rows[-1]), flush=True)
            del model
            if dev == "cuda":
                torch.cuda.empty_cache()
    res = {"gpu": torch.cuda.get_device_name(0) if dev == "cuda" else None, "torch": torch.__version__, "rows": rows}
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "bench.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res), flush=True)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("infer")
    i.add_argument("--ct", required=True, help="URL of one zarr v2 level array (uint8, uncompressed, '/' separator)")
    i.add_argument("--core", type=int, nargs=6, required=True, metavar=("Z0", "Z1", "Y0", "Y1", "X0", "X1"))
    i.add_argument("--weights", required=True)
    i.add_argument("--out", required=True)
    i.add_argument("--norm", choices=("window", "tile"), default="window")
    i.add_argument("--step", type=int, default=64)
    i.add_argument("--batch", type=int, default=4)
    i.add_argument("--max-windows", type=int, default=0)
    i.add_argument("--channels-last", action="store_true")
    i.add_argument("--compile", action="store_true")
    i.add_argument("--budget-s", type=float, default=0)
    t = sub.add_parser("tiles")
    t.add_argument("--plan", required=True, help="the scan's plan JSON (afv_plan.py)")
    t.add_argument("--ids", nargs="*", help="tile ids to run (default every tile of the plan)")
    t.add_argument("--job", type=int, help="run the plan's jobs[JOB] tile list")
    t.add_argument("--weights", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--bucket", help="owner/name to upload into (needs HF_TOKEN); none keeps the files local")
    t.add_argument("--prefix", default="afv/run")
    t.add_argument("--step", type=int, default=64)
    t.add_argument("--batch", type=int, default=8)
    t.add_argument("--budget-s", type=float, default=0)
    t.add_argument("--compile", action="store_true", help="torch.compile the model (about 1.3x on an RTX PRO 6000)")
    for s_ in (i, t):
        s_.add_argument("--compile-mode", help="torch.compile mode; max-autotune measured 1.47x eager on an RTX PRO 6000")
    b = sub.add_parser("bench")
    b.add_argument("--weights", required=True)
    b.add_argument("--batches", type=int, nargs="+", default=[2, 4, 8])
    b.add_argument("--n", type=int, default=20)
    b.add_argument("--out")
    b.add_argument("--compile", action="store_true")
    b.add_argument("--channels-last-too", action="store_true")
    b.add_argument("--compile-mode", help="torch.compile mode, e.g. max-autotune or reduce-overhead")
    b.add_argument("--dtype", choices=("bf16", "fp16"), default="bf16")
    for s_ in (i, t, b):
        s_.add_argument("--win", type=int, default=128, help="window edge (the model was trained on 128; it is fully "
                        "convolutional, so larger windows are an inference option to validate against 128)")
    a = p.parse_args(argv)
    global WIN
    WIN = a.win
    return {"infer": infer, "bench": bench, "tiles": tiles}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
