#!/usr/bin/env python3
"""Our single-letter classifier for papyrus photographs (candidate O5 of the ICDAR head-to-head).

Trained on Hell-Char only (github.com/ipavlopoulos/diachronic-greek-letterforms at aeef8466, CC BY 4.0; all 144
papyri, the 32 "Unknown" crops left out), from ImageNet weights of timm's ConvNeXt (v1, Apache-2.0 in timm).
No ICDAR image and no Herculaneum data are used to train it. The recipe differs from the released Hell-Char
ConvNeXt-V2 (R1) in: a larger input (96 px, aspect kept on the crop's own papyrus tone), per-crop contrast
standardization, heavy photometric and geometric augmentation that imitates other collections' photographs (blur,
resolution loss, noise, stroke width, loose and tight boxes), label smoothing, an EMA of the weights, and all of
Hell-Char rather than an 80% split.

  python scripts/letters/icdar_train.py train --hellchar HC/data/hellchar --out DIR [--seed 0] [--epochs 40]
  python scripts/letters/icdar_train.py smoke --out DIR          # 2 tiny steps on random crops, CPU

Each run folder holds model.pt (EMA state dict), config.json and train.json (losses, timings, sha256).
`predict_folder(DIR, greys)` returns log-probabilities over the 24 capitals in ALPHABET order; with several
run folders joined by commas it averages their log-probabilities (an ensemble of our own runs only).
"""
import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
NAMES = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu",
         "nu", "xi", "omicron", "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega"]
DEFAULTS = {"arch": "convnext_tiny.fb_in22k_ft_in1k", "size": 96, "epochs": 40, "batch": 128, "lr": 5e-4,
            "wd": 0.05, "smooth": 0.1, "ema": 0.999, "warmup": 1, "tta": 0}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ data

def hellchar_items(root):
    """[(gray uint8 crop, class index, papyrus TM)] for every Hell-Char crop of a known letter."""
    from PIL import Image
    root = Path(root)
    out = []
    with open(root / "hellchar.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            n = r["letter"].strip().lower()
            if n not in NAMES:
                continue
            p = root / "cliplets" / r["filename"]
            if not p.exists():
                continue
            out.append((np.asarray(Image.open(p).convert("L")), NAMES.index(n), r["TM"].strip()))
    return out


def standardize(a):
    """Gray crop to float32 with its papyrus (80th percentile) at 1 and its ink core (2nd percentile) at 0."""
    a = np.asarray(a, np.float32)
    bg, lo = np.percentile(a, [80, 2])
    return np.clip((a - lo) / max(bg - lo, 8.0), -0.5, 1.5)


def to_square(a, size, fill=1.0):
    """Aspect-kept resize of a standardized crop onto a size x size canvas of papyrus tone."""
    import cv2
    h, w = a.shape
    s = size / max(h, w)
    nh, nw = max(1, int(round(h * s))), max(1, int(round(w * s)))
    r = cv2.resize(a, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    c = np.full((size, size), fill, np.float32)
    y, x = (size - nh) // 2, (size - nw) // 2
    c[y:y + nh, x:x + nw] = r
    return c


def augment(a, rng):
    """A raw gray crop (uint8) to a perturbed raw gray crop: box jitter, affine, stroke width, blur, resolution,
    noise, contrast and gamma. Every step is a random photograph-to-photograph difference; none adds ink."""
    import cv2
    a = np.asarray(a, np.float32)
    h, w = a.shape
    bg = float(np.percentile(a, 80))
    # box jitter: each side moves in by up to 6% or out by up to 15% of the letter's size (padded with papyrus)
    m = [int(round(rng.uniform(-0.06, 0.15) * s)) for s in (h, h, w, w)]
    pad = max(0, *m)
    if pad:
        a = cv2.copyMakeBorder(a, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    t, b, l, r = (pad - m[0], pad + h + m[1], pad - m[2], pad + w + m[3])
    a = a[max(0, t):max(t + 2, b), max(0, l):max(l + 2, r)]
    h, w = a.shape
    # affine: rotation 8 degrees, shear 0.15, anisotropic scale 0.85 to 1.15
    ang = math.radians(rng.uniform(-8, 8))
    sh = rng.uniform(-0.15, 0.15)
    sx, sy = rng.uniform(0.85, 1.15), rng.uniform(0.85, 1.15)
    M = np.array([[math.cos(ang) * sx, -math.sin(ang) + sh, 0], [math.sin(ang), math.cos(ang) * sy, 0]], np.float32)
    c = np.array([w / 2, h / 2], np.float32)
    M[:, 2] = c - M[:, :2] @ c
    a = cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # stroke width: ink is dark, so a min filter thickens it and a max filter thins it
    if rng.random() < 0.35:
        k = np.ones((2, 2), np.uint8) if min(h, w) < 60 else np.ones((3, 3), np.uint8)
        a = cv2.erode(a, k) if rng.random() < 0.5 else cv2.dilate(a, k)
    # resolution loss and blur
    if rng.random() < 0.4:
        f = rng.uniform(0.25, 0.8)
        small = cv2.resize(a, (max(4, int(w * f)), max(4, int(h * f))), interpolation=cv2.INTER_AREA)
        a = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    if rng.random() < 0.3:
        a = cv2.GaussianBlur(a, (0, 0), rng.uniform(0.3, 1.5))
    # contrast, brightness, gamma and noise
    lo, hi = float(np.percentile(a, 2)), bg
    g = (a - lo) / max(hi - lo, 1.0)
    g = np.clip(g, 0, 1.5) ** rng.uniform(0.6, 1.6)
    g = g * rng.uniform(0.5, 1.2) + rng.uniform(-0.1, 0.1)
    if rng.random() < 0.4:
        g = g + rng.normal(0, rng.uniform(0.02, 0.12), g.shape)
    return np.clip(g * 255.0, 0, 255).astype(np.uint8)


def batch_tensor(crops, size):
    import torch
    x = np.stack([to_square(standardize(c), size) for c in crops])[:, None]
    x = (x - 0.5) / 0.5
    return torch.from_numpy(np.repeat(x, 3, axis=1).astype(np.float32))


# ------------------------------------------------------------------ model

def make_model(arch, pretrained):
    import timm
    return timm.create_model(arch, pretrained=pretrained, num_classes=24)


class _Aug:
    """torch Dataset of augmented, standardized, squared crops (workers draw their own random streams)."""

    def __init__(self, items, size, seed):
        self.items, self.size, self.seed = items, size, seed

    def __len__(self):
        return len(self.items)

    def __getitem__(self, k):
        import torch
        info = torch.utils.data.get_worker_info()
        rng = np.random.default_rng([self.seed, k, int(torch.randint(0, 2 ** 31, (1,)))])
        a = to_square(standardize(augment(self.items[k][0], rng)), self.size)
        x = np.repeat(((a - 0.5) / 0.5)[None], 3, axis=0).astype(np.float32)
        return torch.from_numpy(x), int(self.items[k][1])


def train(items, out, cfg, seed, device, log_every=50, max_steps=None, workers=None):
    import torch
    import torch.nn.functional as F
    torch.manual_seed(seed)
    model = make_model(cfg["arch"], pretrained=not cfg.get("no_pretrained")).to(device)
    ema = make_model(cfg["arch"], pretrained=False).to(device)
    ema.load_state_dict(model.state_dict())
    for p in ema.parameters():
        p.requires_grad_(False)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=cfg["wd"])
    n = len(items)
    steps_per_epoch = max(1, n // cfg["batch"])
    total = steps_per_epoch * cfg["epochs"] if max_steps is None else max_steps
    warm = steps_per_epoch * cfg["warmup"] if max_steps is None else 1
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warm if s < warm else 0.5 * (1 + math.cos(math.pi * (s - warm) / max(1, total - warm))))
    labels = np.array([c for _, c, _ in items])
    workers = min(8, max(0, (os.cpu_count() or 2) - 1)) if workers is None else workers   # more hit the Job's process limit
    dl = torch.utils.data.DataLoader(_Aug(items, cfg["size"], seed), batch_size=cfg["batch"], shuffle=True,
                                     drop_last=True, num_workers=workers, persistent_workers=workers > 0,
                                     generator=torch.Generator().manual_seed(seed))
    log, t0, step = [], time.time(), 0
    amp = device.startswith("cuda")
    pairs = list(zip(ema.state_dict().values(), model.state_dict().values()))
    while step < total:
        for x, y in dl:
            if step >= total:
                break
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
                loss = F.cross_entropy(model(x), y, label_smoothing=cfg["smooth"])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            with torch.no_grad():
                d = min(cfg["ema"], (1 + step) / (10 + step))
                for pe, pm in pairs:
                    if pe.dtype.is_floating_point:
                        pe.mul_(d).add_(pm.detach(), alpha=1 - d)
                    else:
                        pe.copy_(pm)
            if step % log_every == 0:
                log.append({"step": step, "loss": round(float(loss), 4), "s": round(time.time() - t0, 1)})
                print(f"PROGRESS {step}/{total} loss {float(loss):.4f} {time.time() - t0:.0f}s", flush=True)
            step += 1
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(ema.state_dict(), out / "model.pt")
    conf = dict(cfg, seed=seed, train_items=n, classes=list(ALPHABET),
                train_counts=np.bincount(labels, minlength=24).tolist())
    (out / "config.json").write_text(json.dumps(conf, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "train.json").write_text(json.dumps({"log": log, "seconds": round(time.time() - t0, 1),
                                                "model_sha256": sha256_file(out / "model.pt")}, indent=1) + "\n")
    return out


# ------------------------------------------------------------------ prediction

def pack_crops(work_part, out):
    """One npz of a built part's letter crops in letters.json order: ids, shapes and one flat uint8 buffer."""
    from PIL import Image
    work_part = Path(work_part)
    letters = json.loads((work_part / "letters.json").read_text())
    arrs = [np.asarray(Image.open(work_part / "crops" / f"{L['id']}.png").convert("L")) for L in letters]
    np.savez_compressed(out, ids=np.array([L["id"] for L in letters]), shapes=np.array([a.shape for a in arrs]),
                        buf=np.concatenate([a.ravel() for a in arrs]))


def unpack_crops(path):
    z = np.load(path)
    buf, shapes, ids = z["buf"], z["shapes"], z["ids"]      # each z[...] access decompresses again: read once
    out, o = [], 0
    for h, w in shapes:
        out.append(buf[o:o + h * w].reshape(h, w))
        o += h * w
    return list(ids), out


def _scales(tta):
    return [1.0] if not tta else [1.0, 0.9, 1.1]


def predict_one(folder, greys, batch=256, device="cpu", tta=None):
    import torch
    folder = Path(folder)
    cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    m = make_model(cfg["arch"], pretrained=False)
    m.load_state_dict(torch.load(folder / "model.pt", map_location="cpu", weights_only=True))
    m.eval().to(device)
    outs = []
    for s in _scales(cfg.get("tta", 0) if tta is None else tta):
        res = []
        size = cfg["size"]
        with torch.inference_mode():
            for i in range(0, len(greys), batch):
                xs = []
                for g in greys[i:i + batch]:
                    a = to_square(standardize(g), size)
                    if s != 1.0:
                        import cv2
                        k = max(8, int(round(size * s)))
                        r = cv2.resize(a, (k, k), interpolation=cv2.INTER_LINEAR)
                        c = np.ones((size, size), np.float32)
                        if k >= size:
                            o = (k - size) // 2
                            c = r[o:o + size, o:o + size]
                        else:
                            o = (size - k) // 2
                            c[o:o + k, o:o + k] = r
                        a = c
                    xs.append(a)
                x = (np.stack(xs)[:, None] - 0.5) / 0.5
                x = torch.from_numpy(np.repeat(x, 3, axis=1).astype(np.float32)).to(device)
                res.append(torch.log_softmax(m(x).float(), 1).cpu().numpy())
        outs.append(np.concatenate(res))
    lp = np.mean(outs, axis=0)
    return lp - np.logaddexp.reduce(lp, axis=1, keepdims=True), cfg


def predict_folder(folders, greys, batch=256, device="cpu"):
    parts = [predict_one(f, greys, batch, device)[0] for f in str(folders).split(",")]
    lp = np.mean(parts, axis=0)
    return lp - np.logaddexp.reduce(lp, axis=1, keepdims=True)


def train_logprior(folder):
    """log of the training class shares of a run (or the mean over an ensemble's runs)."""
    shares = []
    for f in str(folder).split(","):
        c = np.array(json.loads((Path(f) / "config.json").read_text())["train_counts"], float)
        shares.append(np.log(c / c.sum()))
    return np.mean(shares, axis=0)


# ------------------------------------------------------------------ commands

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--hellchar", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--seed", type=int, default=0)
    for k, v in DEFAULTS.items():
        t.add_argument("--" + k, type=type(v), default=v)
    t.add_argument("--max-steps", type=int)
    d = sub.add_parser("devpost", help="posteriors of run folders on a packed crop file (dev only)")
    d.add_argument("--crops", required=True)
    d.add_argument("--runs", nargs="+", required=True)
    d.add_argument("--out", required=True)
    s = sub.add_parser("smoke")
    s.add_argument("--out", required=True)
    a = p.parse_args(argv)
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if a.cmd == "smoke":
        rng = np.random.default_rng(0)
        items = [((rng.random((50 + i % 20, 40 + i % 15)) * 255).astype(np.uint8), i % 24, "x") for i in range(64)]
        cfg = dict(DEFAULTS, batch=8, epochs=1, no_pretrained=True, arch="convnext_atto")
        out = train(items, a.out, cfg, 0, device, log_every=1, max_steps=2, workers=0)
        lp = predict_folder(out, [items[0][0], items[1][0]])
        assert lp.shape == (2, 24) and np.allclose(np.exp(lp).sum(1), 1, atol=1e-4)
        print("smoke ok", out)
        return
    if a.cmd == "devpost":
        ids, greys = unpack_crops(a.crops)
        Path(a.out).mkdir(parents=True, exist_ok=True)
        for r in a.runs:
            for tta in (0, 1):
                lp, _ = predict_one(r, greys, batch=512, device=device, tta=tta)
                np.savez_compressed(Path(a.out) / f"post-{Path(r).name}-tta{tta}.npz", ids=np.array(ids),
                                    logp=lp.astype(np.float32))
                print("PROGRESS devpost", r, tta, flush=True)
        return
    items = hellchar_items(a.hellchar)
    cfg = {k: getattr(a, k) for k in DEFAULTS}
    print(f"{len(items)} Hell-Char crops, device {device}, cfg {cfg}", flush=True)
    train(items, a.out, cfg, a.seed, device, max_steps=a.max_steps)


if __name__ == "__main__":
    main()
