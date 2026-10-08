"""Train the CTC line reader on synthetic bands; export numpy weights (.npz) for kit/letterread.py.

Usage:
  python scripts/letters/train_linenet.py DATA_DIR OUT_DIR --val VAL_DIR [--steps N] [--batch B]
      [--device cpu|cuda] [--amp] [--channels 32,64,96,128,192] [--dilations 1,2] [--workers 0] [--keep]

DATA_DIR and VAL_DIR hold shards from gen_dataset.py. Writes OUT_DIR/linenet.pt (torch state),
OUT_DIR/linenet.npz (BatchNorm folded, linenet-v1) and OUT_DIR/train.json (settings, losses and
validation numbers). --keep also saves the weights at every evaluation, so a checkpoint can be chosen
on real letters (eval_p172.py --split dev) rather than on synthetic validation. Weights stay out of git.
"""
import argparse
import glob
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_dataset import load_shard  # noqa: E402
import letterdata as L  # noqa: E402

ALPHABET = L.ALPHABET
BLANK = 0


def cbr(i, o, k=3, p=1):
    return [nn.Conv2d(i, o, k, padding=p, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True)]


class LineNet(nn.Module):
    """Band (1 x 36 x W) -> per-frame logits (25 x W/4). Fully convolutional, no recurrence.

    With the default dilations (1, 2) each output frame sees 58 px of the line at a letter height of 16 px,
    about three letters; dilations 1, 2, 4 widen that to 90 px, about five."""

    def __init__(self, n_classes=len(ALPHABET) + 1, c=(32, 64, 96, 128, 192), dilations=(1, 2)):
        super().__init__()
        c1, c2, c3, c4, c5 = c
        self.stem = nn.Sequential(*cbr(1, c1), nn.MaxPool2d(2),
                                  *cbr(c1, c2), nn.MaxPool2d(2),
                                  *cbr(c2, c3), *cbr(c3, c3), nn.MaxPool2d((2, 1)),
                                  *cbr(c3, c4))
        self.collapse = nn.Sequential(nn.Conv2d(c4, c5, (4, 1), bias=False), nn.BatchNorm2d(c5), nn.ReLU(inplace=True))
        self.dilations = tuple(dilations)
        self.ts = nn.ModuleList(nn.Sequential(nn.Conv1d(c5, c5, 3, padding=d, dilation=d, bias=False),
                                              nn.BatchNorm1d(c5), nn.ReLU(inplace=True)) for d in self.dilations)
        self.head = nn.Conv1d(c5, n_classes, 1)

    def forward(self, x):
        y = self.stem(x)
        y = self.collapse(y).squeeze(2)          # B x C x T
        for t in self.ts:
            y = y + t(y)
        return self.head(y)                     # B x K x T (logits)


def encode(text):
    return [ALPHABET.index(c) + 1 for c in text]


def greedy(logits_kt):
    best = logits_kt.argmax(0)
    out, prev = [], -1
    for b in best.tolist():
        if b != prev and b != BLANK:
            out.append(ALPHABET[b - 1])
        prev = b
    return "".join(out)


def edit(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class Data:
    """All lines of a shard folder in memory (uint8), batched by width so padding stays small."""

    def __init__(self, d, max_shards=None):
        files = sorted(glob.glob(str(Path(d) / "*.npz")))[:max_shards]
        self.imgs, self.texts = [], []
        for f in files:
            im, tx, _ = load_shard(f)
            self.imgs += im
            self.texts += tx
        self.widths = np.array([a.shape[1] for a in self.imgs])
        print(f"{d}: {len(self.imgs)} lines from {len(files)} shards", flush=True)

    def batch(self, idx, rng=None):
        imgs = [self.imgs[i].astype(np.float32) / 255.0 for i in idx]
        if rng is not None:  # cheap photometric augmentation
            out = []
            for a in imgs:
                g = rng.uniform(0.7, 1.4)
                a = np.clip(a, 0, 1) ** g
                a = a * rng.uniform(0.7, 1.0) + rng.uniform(0, 0.15)
                a = a + rng.normal(0, rng.uniform(0, 0.04), a.shape).astype(np.float32)
                out.append(np.clip(a, 0, 1))
            imgs = out
        W = max(a.shape[1] for a in imgs)
        W = int(math.ceil(W / 4) * 4)
        H = imgs[0].shape[0]
        x = np.zeros((len(imgs), 1, H, W), np.float32)
        for k, a in enumerate(imgs):
            x[k, 0, :, :a.shape[1]] = a
            x[k, 0, :, a.shape[1]:] = np.median(a)
        tl = [len(self.texts[i]) for i in idx]
        tg = sum((encode(self.texts[i]) for i in idx), [])
        il = [a.shape[1] // 4 for a in imgs]
        return torch.from_numpy(x), torch.tensor(tg, dtype=torch.long), torch.tensor(il), torch.tensor(tl)


class Batches(torch.utils.data.Dataset):
    """One item per width bucket, augmented with a generator seeded by (seed, epoch, bucket)."""

    def __init__(self, data, buckets, seed):
        self.data, self.buckets, self.seed, self.epoch = data, buckets, seed, 0

    def __len__(self):
        return len(self.buckets)

    def __getitem__(self, i):
        return self.data.batch(self.buckets[i], np.random.default_rng((self.seed, self.epoch, i)))


def evaluate(model, data, n=600, bs=64, device="cpu"):
    model.eval()
    errs = chars = 0
    blank_lines = blank_letters = 0
    with torch.no_grad():
        order = np.argsort(data.widths[:n])
        for s in range(0, min(n, len(order)), bs):
            idx = order[s:s + bs]
            x, _, il, _ = data.batch(idx)
            lg = model(x.to(device)).float().cpu()
            for k, i in enumerate(idx):
                got = greedy(lg[k, :, :int(il[k])])
                want = data.texts[i]
                if want:
                    errs += edit(got, want)
                    chars += len(want)
                else:
                    blank_lines += 1
                    blank_letters += len(got)
    model.train()
    return errs / max(1, chars), blank_letters / max(1, blank_lines)


def export_npz(model, path):
    """Fold BatchNorm into convolutions and save plain arrays for numpy inference."""
    model.eval()
    out, k = {}, 0

    def fold(conv, bn):
        w = conv.weight.detach().double()
        b = conv.bias.detach().double() if conv.bias is not None else torch.zeros(w.shape[0], dtype=torch.float64)
        s = bn.weight.detach().double() / torch.sqrt(bn.running_var.double() + bn.eps)
        w = w * s.view(-1, *([1] * (w.dim() - 1)))
        b = (b - bn.running_mean.double()) * s + bn.bias.detach().double()
        return w.float().numpy(), b.float().numpy()

    layers = []
    mods = list(model.stem)
    i = 0
    while i < len(mods):
        m = mods[i]
        if isinstance(m, nn.Conv2d):
            w, b = fold(m, mods[i + 1])
            out[f"w{k}"], out[f"b{k}"] = w, b
            layers.append({"op": "conv2d", "id": k, "pad": m.padding[0]})
            k += 1
            i += 3
        elif isinstance(m, nn.MaxPool2d):
            ks = m.kernel_size if isinstance(m.kernel_size, tuple) else (m.kernel_size, m.kernel_size)
            layers.append({"op": "maxpool", "k": list(ks)})
            i += 1
        else:
            i += 1
    w, b = fold(model.collapse[0], model.collapse[1])
    out[f"w{k}"], out[f"b{k}"] = w, b
    layers.append({"op": "collapse", "id": k})
    k += 1
    for t, dil in zip(model.ts, model.dilations):
        w, b = fold(t[0], t[1])
        out[f"w{k}"], out[f"b{k}"] = w, b
        layers.append({"op": "conv1d_res", "id": k, "dilation": dil})
        k += 1
    out[f"w{k}"] = model.head.weight.detach().float().numpy()
    out[f"b{k}"] = model.head.bias.detach().float().numpy()
    layers.append({"op": "head", "id": k})
    meta = {"alphabet": ALPHABET, "blank": BLANK, "letter_px": L.H_PX, "band": [L.BAND_TOP, L.BAND_BOT],
            "stride": 4, "layers": layers, "format": "linenet-v1"}
    np.savez(path, meta=np.array(json.dumps(meta, ensure_ascii=False)), **out)
    model.train()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--val")
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=48)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume")
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--amp", action="store_true", help="bfloat16 autocast on CUDA (CTC loss stays float32)")
    ap.add_argument("--channels", default="32,64,96,128,192")
    ap.add_argument("--dilations", default="1,2")
    ap.add_argument("--workers", type=int, default=0, help="DataLoader worker processes for batch assembly")
    ap.add_argument("--keep", action="store_true", help="also keep each evaluation's weights as OUT_DIR/ckpt/linenet-stepNNNNNN.npz")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tr = Data(a.data)
    va = Data(a.val) if a.val else None
    channels = tuple(int(v) for v in a.channels.split(","))
    dilations = tuple(int(v) for v in a.dilations.split(","))
    model = LineNet(c=channels, dilations=dilations)
    if a.resume:
        model.load_state_dict(torch.load(a.resume, map_location="cpu"))
    model.to(a.device)
    n_params = sum(p.numel() for p in model.parameters())
    print("params", n_params, flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.steps, pct_start=0.1)
    ctc = nn.CTCLoss(blank=BLANK, zero_infinity=True)
    order = np.argsort(tr.widths)
    buckets = [order[i:i + a.batch] for i in range(0, len(order), a.batch)]
    batches = Batches(tr, buckets, a.seed)
    amp = a.amp and a.device.startswith("cuda")
    t0 = time.time()
    hist, evals = [], []
    step = epoch = 0
    while step < a.steps:
        batches.epoch = epoch
        if a.workers:
            it = torch.utils.data.DataLoader(batches, batch_size=None, shuffle=True, num_workers=a.workers,
                                             generator=torch.Generator().manual_seed(a.seed + epoch))
        else:
            it = (batches[int(bi)] for bi in rng.permutation(len(buckets)))
        for x, tg, il, tl in it:
            if step >= a.steps:
                break
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
                lg = model(x.to(a.device, non_blocking=True))         # B K T
            lp = F.log_softmax(lg.float(), 1).permute(2, 0, 1)         # T B K
            loss = ctc(lp, tg, il, tl)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            sched.step()
            step += 1
            hist.append(loss.item())
            if step % 50 == 0:
                print(f"step {step} loss {np.mean(hist[-50:]):.3f} lr {sched.get_last_lr()[0]:.2e} {time.time() - t0:.0f}s", flush=True)
            if va is not None and (step % a.eval_every == 0 or step == a.steps):
                cer, fp = evaluate(model, va, device=a.device)
                evals.append({"step": step, "val_cer": round(cer, 4), "letters_per_blank_line": round(fp, 3)})
                print(f"EVAL step {step} val CER {cer:.3f} letters per blank line {fp:.2f}", flush=True)
                torch.save(model.state_dict(), out / "linenet.pt")
                export_npz(model.cpu(), out / "linenet.npz")
                if a.keep:
                    (out / "ckpt").mkdir(exist_ok=True)
                    export_npz(model, out / "ckpt" / f"linenet-step{step:06d}.npz")
                model.to(a.device)
        epoch += 1
    torch.save(model.state_dict(), out / "linenet.pt")
    export_npz(model.cpu(), out / "linenet.npz")
    info = {"steps": a.steps, "batch": a.batch, "lr": a.lr, "seed": a.seed, "channels": channels, "dilations": dilations,
            "params": n_params, "train_lines": len(tr.imgs), "val_lines": len(va.imgs) if va else 0,
            "device": a.device, "amp": amp, "seconds": round(time.time() - t0, 1),
            "loss_last_200": round(float(np.mean(hist[-200:])), 4) if hist else None, "evals": evals}
    (out / "train.json").write_text(json.dumps(info, indent=1) + "\n")
    print("done", time.time() - t0, flush=True)


if __name__ == "__main__":
    main()
