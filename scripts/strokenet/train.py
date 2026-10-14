"""Train StrokeNet (a small CNN, PyTorch) on text and blank windows of the training segments.

Positives: text windows, half of them as they are and half rebuilt as seam-matched windows on the
shuffle or strip lattice (nulls.jitter), so lattice seams carry no label. Negatives: blank papyrus
windows (half of them rotated by 90 degrees, so fibre direction alone cannot look like text, and
jittered in the same shares as the positives) and nulls of text windows made on the fly
(scripts/strokenet/nulls.py: IAAFT surrogates with 20 iterations, tile shuffle, rot90). The final
checkpoint (cosine schedule to zero) is exported for numpy inference (kit/strokenet.py); a fixed
validation monitor set is scored every 500 steps for the record. The test segments are never read
here.

  python scripts/strokenet/train.py --work WORK --out RUN [--width 16] [--depth 4] [--lr 2e-3]
         [--steps 6000] [--seed 0] [--neg-mix blank=0.4,iaaft=0.2,shuffle=0.2,rot90=0.2]
         [--jitter 0.25,0.25] [--permute-labels] [--positives text|blank] [--monitor SETS.npz]
         [--resume] [--device cuda|mps|cpu]

--positives blank is the artifact control: blank windows are the positives and IAAFT, shuffle and
strip copies of blank the negatives (for example --neg-mix iaaft=1,shuffle=1,strip=1), so it never
sees text and can learn only what the nulls themselves leave behind.

Seeds fix every random draw; runs on CUDA, MPS or CPU (bit-identical reruns are expected on the
CPU; on a GPU, deterministic algorithms are requested but cuFFT and cuDNN may still differ in the
last bits). Checkpoint and resume (--resume).
"""
import argparse
import json
import math
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")      # deterministic cuBLAS, set before CUDA starts

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data as D  # noqa: E402
import metrics as M  # noqa: E402
import nulls as NL  # noqa: E402

VAL_SEED = 12345
DEFAULT_MIX = "blank=0.4,iaaft=0.2,shuffle=0.2,rot90=0.2"
NEG_KINDS = ("blank", "iaaft", "shuffle", "rot90", "strip")
NULL_KIND = {"iaaft": "iaaft20", "shuffle": "shuffle", "rot90": "rot90", "strip": "strip"}
DEFAULT_JITTER = "0.25,0.25"      # shares of tile- and strip-jittered positives and blank negatives


# ------------------------------------------------------------------ model
class Net(nn.Module):
    """Pairs of 3 x 3 convolutions with batch norm and ReLU, max pooling after each pair, then
    global mean and max pooling and one linear unit (the logit)."""

    def __init__(self, width=16, depth=4, cap=8):
        super().__init__()
        layers, cin = [], 1
        self.chans = [int(width * min(2 ** i, cap)) for i in range(depth)]
        for c in self.chans:
            layers += [nn.Conv2d(cin, c, 3, padding=1, bias=False), nn.BatchNorm2d(c), nn.ReLU(inplace=True),
                       nn.Conv2d(c, c, 3, padding=1, bias=False), nn.BatchNorm2d(c), nn.ReLU(inplace=True),
                       nn.MaxPool2d(2)]
            cin = c
        self.features = nn.Sequential(*layers)
        self.head = nn.Linear(2 * cin, 1)

    def forward(self, x):
        f = self.features(x)
        g = torch.cat([f.mean(dim=(2, 3)), f.amax(dim=(2, 3))], dim=1)
        return self.head(g).squeeze(1)


def robust_norm_t(x):
    """Per window (x - median) / (1.4826 MAD), clipped to -3..20, divided by 5 (as kit.strokenet)."""
    B = x.shape[0]
    f = x.reshape(B, -1)
    med = f.median(dim=1, keepdim=True).values
    mad = (f - med).abs().median(dim=1, keepdim=True).values * 1.4826
    sd = f.std(dim=1, keepdim=True)
    mad = torch.where(mad < 1e-3, sd + 1e-3, mad)
    return (((f - med) / mad).clamp(-3, 20) / 5.0).reshape_as(x)


def export_numpy(model, path, meta):
    """Fold batch norm into the convolutions and save an npz for kit.strokenet (numpy inference)."""
    model = model.cpu().eval()
    arrs, mods = {}, list(model.features)
    k = i = 0
    while i < len(mods):
        m = mods[i]
        if isinstance(m, nn.Conv2d):
            bn = mods[i + 1]
            inv = 1.0 / torch.sqrt(bn.running_var + bn.eps)
            s = (bn.weight * inv).detach().double().numpy()
            b = (bn.bias - bn.running_mean * bn.weight * inv).detach().double().numpy()
            arrs[f"conv{k}_w"] = (m.weight.detach().double().numpy() * s[:, None, None, None]).astype(np.float32)
            arrs[f"conv{k}_b"] = b.astype(np.float32)
            k += 1
            i += 3
            continue
        if isinstance(m, nn.MaxPool2d):
            arrs[f"pool_after_{k - 1}"] = np.array(1)
        i += 1
    arrs["head_w"] = model.head.weight.detach().numpy().astype(np.float32)
    arrs["head_b"] = model.head.bias.detach().numpy().astype(np.float32)
    arrs["n_conv"] = np.array(k)
    arrs["meta"] = np.array(json.dumps(meta))
    np.savez(path, **arrs)


def load_model(run_dir, device="cpu", ckpt="final.pt"):
    cfg = json.loads((Path(run_dir) / "config.json").read_text())
    model = Net(cfg["width"], cfg["depth"]).to(device)
    model.load_state_dict(torch.load(Path(run_dir) / ckpt, map_location=device, weights_only=True))
    return model.eval(), cfg


# ------------------------------------------------------------------ scoring
@contextmanager
def fp32():
    """Full fp32 convolutions and matrix products on CUDA (no TF32), restored afterwards."""
    old = (torch.backends.cudnn.allow_tf32, torch.backends.cuda.matmul.allow_tf32)
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.matmul.allow_tf32 = False
    try:
        yield
    finally:
        torch.backends.cudnn.allow_tf32, torch.backends.cuda.matmul.allow_tf32 = old


@torch.no_grad()
def score(model, arr, device, bs=512):
    """Logits for windows (N, H, W), uint8 or float, in fp32 (TF32 off)."""
    model.eval()
    out = []
    with fp32():
        for i in range(0, len(arr), bs):
            x = torch.from_numpy(np.asarray(arr[i:i + bs], np.float32))[:, None].to(device)
            out.append(model(robust_norm_t(x)).float().cpu().numpy())
    return np.concatenate(out) if out else np.zeros(0, np.float32)


MONITOR_KEYS = ("text", "blank", "dense", "iaaft20_text", "shuffle_text", "tilejit_text", "rot90_text", "rot90_blank")


def val_metrics(s):
    """Monitor summary from logits of the monitor arrays. select is the sweep's choice rule."""
    r = {"T1_auc": M.auc(s["text"], s["blank"]), "T2_20_auc": M.auc(s["text"], s["iaaft20_text"]),
         "T3_auc": M.auc(s["tilejit_text"], s["shuffle_text"]), "T4_auc": M.auc(s["text"], s["rot90_text"]),
         "T4_paired_frac": M.paired_frac(s["text"], s["rot90_text"]), "T6_auc": M.auc(s["blank"], s["rot90_blank"]),
         "T8_auc": M.auc(s["text"], s["dense"])}
    r["mean_T1_T4"] = float(np.mean([r["T1_auc"], r["T2_20_auc"], r["T3_auc"], r["T4_auc"]]))
    r["select"] = float(np.mean([r["T1_auc"], r["T2_20_auc"], r["T3_auc"], r["T4_auc"], r["T8_auc"]]))
    return r


def monitor_sets(work, segs, limit=0):
    """The fixed monitor windows of the validation segments (seed VAL_SEED, 20-iteration IAAFT)."""
    d = D.load_split(work, segs, kinds=("text", "blank", "dense"), with_segments=True, with_positions=True)
    if limit:                                         # smoke tests only
        d = {k: v[:limit] for k, v in d.items()}
    sets = NL.eval_sets(d, VAL_SEED, D.load_maps(work, segs), pairs=NL.MONITOR_PAIRS)
    return {k: sets[k] for k in MONITOR_KEYS}


def parse_mix(s, allowed=NEG_KINDS):
    d = {}
    for part in s.split(","):
        k, v = part.split("=")
        if k not in allowed:
            raise ValueError(f"unknown negative kind {k}")
        d[k] = float(v)
    w = np.array([d.get(k, 0.0) for k in NEG_KINDS])
    if w.sum() <= 0:
        raise ValueError("negative mix sums to zero")
    return w / w.sum()


def parse_jitter(s):
    t, st = (float(v) for v in s.split(","))
    if t < 0 or st < 0 or t + st > 1:
        raise ValueError("jitter shares must be non-negative and sum to at most 1")
    return np.array([1.0 - t - st, t, st])


def windows(src, idx, maps, shares, rng):
    """Windows src["w"][idx] as float32 (n, 1, 128, 128): plain, tile-jittered or strip-jittered in
    the given shares (nulls.jitter, from the pooled maps)."""
    n = len(idx)
    out = src["w"][idx].copy()
    kind = rng.choice(3, size=n, p=shares)
    for k, lattice in ((1, "tile"), (2, "strip")):
        m = np.nonzero(kind == k)[0]
        if len(m):
            out[m] = NL.jitter(maps, src["seg"][idx[m]], src["pos"][idx[m]], lattice, rng)
    return torch.from_numpy(out.astype(np.float32))[:, None]


# ------------------------------------------------------------------ training
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True, help="data.py work folder (crops/, pooled/)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=16)
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--neg-mix", default=DEFAULT_MIX, help="shares of blank, iaaft (20 iterations), shuffle, rot90, strip negatives")
    ap.add_argument("--blank-rot", type=float, default=0.5, help="share of blank negatives rotated by 90 degrees")
    ap.add_argument("--jitter", default=DEFAULT_JITTER, help="shares of tile- and strip-jittered positives and blank negatives")
    ap.add_argument("--positives", choices=["text", "blank"], default="text",
                    help="blank: the artifact control (blank positives, nulls of blank as negatives; never sees text)")
    ap.add_argument("--no-flip", action="store_true")
    ap.add_argument("--permute-labels", action="store_true",
                    help="control: labels permuted at random within every batch (should learn nothing)")
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--max-minutes", type=float, default=0, help="stop (and export) after this wall time; 0 = no cap")
    ap.add_argument("--monitor", default=None, help="npz of the monitor windows (pipeline prep); built here when absent")
    ap.add_argument("--train-segments", default=None, help="override (smoke tests only)")
    ap.add_argument("--val-segments", default=None, help="override (smoke tests only)")
    ap.add_argument("--val-limit", type=int, default=0, help="use only the first N monitor windows of each kind (smoke tests only)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--device", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dev = a.device or ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
    if dev == "cuda":
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.manual_seed(a.seed)
    np.random.seed(a.seed)
    rng = np.random.default_rng(a.seed)
    gen = torch.Generator().manual_seed(a.seed)
    sp = D.splits()
    train_segs = a.train_segments.split(",") if a.train_segments else sp["train"]
    val_segs = a.val_segments.split(",") if a.val_segments else sp["validation"]
    if set(train_segs + val_segs) & set(sp["test"]):
        raise SystemExit("a test segment was named for training or validation")
    mix = parse_mix(a.neg_mix)
    shares = parse_jitter(a.jitter)
    if a.positives == "blank" and mix[0] > 0:
        raise SystemExit("the artifact control has no blank negatives (its positives are blank)")
    tr = D.load_split(a.work, train_segs, with_segments=True, with_positions=True)
    maps = D.load_maps(a.work, train_segs)
    pos_src = {"w": tr[a.positives], "seg": tr[a.positives + "_seg"], "pos": tr[a.positives + "_pos"]}
    blank_src = {"w": tr["blank"], "seg": tr["blank_seg"], "pos": tr["blank_pos"]}
    t_start = time.time()
    if a.monitor and not (a.val_segments or a.val_limit):
        with np.load(a.monitor) as z:              # closed: an open file on the cloud volume blocks its commits
            vsets = {k: z[k] for k in MONITOR_KEYS}
    else:
        vsets = monitor_sets(a.work, val_segs, a.val_limit)
    t_vsets = time.time() - t_start
    model = Net(a.width, a.depth).to(dev)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=a.wd)
    sched = lambda s: a.lr * (0.5 * (1 + math.cos(math.pi * min(1.0, s / a.steps)))) * min(1.0, (s + 1) / 200)
    step, best, best_step, hist = 0, -1.0, -1, []
    ck = out / "checkpoint.pt"
    resumed_from = 0
    if a.resume and ck.exists():
        st = torch.load(ck, map_location="cpu", weights_only=False)
        model.load_state_dict(st["model"])
        opt.load_state_dict(st["opt"])
        step, best, best_step, hist = st["step"], st["best"], st["best_step"], st["hist"]
        rng.bit_generator.state = st["rng"]
        gen.set_state(st["gen"])
        torch.set_rng_state(st["torch_rng"])
        resumed_from = step
        print(f"resumed at step {step}", flush=True)
    cfg = {k: v for k, v in vars(a).items() if k not in ("work", "out", "resume", "monitor")}
    cfg.update({"device": dev, "torch": torch.__version__, "numpy": np.__version__, "n_params": n_params,
                "neg_shares": dict(zip(NEG_KINDS, [float(v) for v in mix])),
                "jitter_shares": dict(zip(("plain", "tile", "strip"), [float(v) for v in shares])),
                "train_iaaft_iters": NL.TRAIN_IAAFT_ITERS, "train_segments": train_segs, "val_segments": val_segs,
                "n_train_pos": int(len(pos_src["w"])), "n_train_blank": int(len(blank_src["w"])),
                "n_monitor": {k: int(len(v)) for k, v in vsets.items()}, "val_seed": VAL_SEED,
                "monitor_sha256": {k: NL.array_sha256(v) for k, v in vsets.items()}, "monitor_build_s": round(t_vsets, 1),
                "tf32_training": bool(torch.backends.cudnn.allow_tf32) if dev == "cuda" else False,
                "resumed_from_step": resumed_from})
    (out / "config.json").write_text(json.dumps(cfg, indent=1) + "\n")
    B = a.batch
    nP, nN = B // 2, B - B // 2
    t0, seen = time.time(), 0
    while step < a.steps:
        model.train()
        pos = windows(pos_src, rng.integers(len(pos_src["w"]), size=nP), maps, shares, rng).to(dev)
        counts = rng.multinomial(nN, mix)
        negs = []
        if counts[0]:
            xb = windows(blank_src, rng.integers(len(blank_src["w"]), size=counts[0]), maps, shares, rng).to(dev)
            rb = torch.from_numpy(rng.uniform(size=counts[0]) < a.blank_rot).to(dev)
            negs.append(torch.where(rb[:, None, None, None], torch.rot90(xb, 1, dims=(2, 3)), xb))
        for kind, c in zip(NEG_KINDS[1:], counts[1:]):
            if c:
                src = pos_src["w"][rng.integers(len(pos_src["w"]), size=c)]
                x = torch.from_numpy(src.astype(np.float32))[:, None].to(dev)
                negs.append(NL.make(NULL_KIND[kind], x, rng, gen))
        x = torch.cat([pos] + negs)
        y = torch.cat([torch.ones(nP), torch.zeros(nN)])
        if a.permute_labels:
            y = y[torch.from_numpy(rng.permutation(B))]
        y = y.to(dev)
        if not a.no_flip:      # flips keep line and stroke orientation statistics (never rot90)
            fh = torch.from_numpy(rng.uniform(size=B) < 0.5).to(dev)
            fv = torch.from_numpy(rng.uniform(size=B) < 0.5).to(dev)
            x = torch.where(fh[:, None, None, None], torch.flip(x, dims=(3,)), x)
            x = torch.where(fv[:, None, None, None], torch.flip(x, dims=(2,)), x)
        # intensity augmentation the normalisation does not cancel: gamma per window, then noise
        # with its own level per window (a gain or an offset would be removed by the normalisation)
        g = torch.from_numpy(rng.uniform(0.8, 1.25, size=(B, 1, 1, 1)).astype(np.float32)).to(dev)
        x = 255.0 * (x.clamp(0, 255) / 255.0) ** g
        sig = torch.from_numpy(rng.uniform(0, 3, size=(B, 1, 1, 1)).astype(np.float32)).to(dev)
        x = x + torch.randn(x.shape, generator=gen).to(dev) * sig
        for pg in opt.param_groups:
            pg["lr"] = sched(step)
        logit = model(robust_norm_t(x))
        loss = Fn.binary_cross_entropy_with_logits(logit, y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        step += 1
        seen += B
        over = a.max_minutes > 0 and (time.time() - t_start) > 60 * a.max_minutes
        if step % a.eval_every == 0 or step == a.steps or over:
            s = {k: score(model, v, dev) for k, v in vsets.items()}
            r = val_metrics(s)
            r.update({"step": step, "loss": float(loss.item()), "samples_per_s": seen / (time.time() - t0)})
            hist.append(r)
            print(json.dumps(r), flush=True)
            if r["select"] > best:
                best, best_step = r["select"], step
            torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "step": step, "best": best,
                        "best_step": best_step, "hist": hist, "rng": rng.bit_generator.state, "gen": gen.get_state(),
                        "torch_rng": torch.get_rng_state()}, ck.with_suffix(".part"))
            ck.with_suffix(".part").replace(ck)       # whole: a copy taken at any moment can be resumed
            t0, seen = time.time(), 0
            if over:
                print(f"wall-time cap reached at step {step}", flush=True)
                break
    torch.save(model.state_dict(), out / "final.pt")
    final = hist[-1]
    meta = {"name": out.name, "width": a.width, "depth": a.depth, "crop_px": 128, "pixel_mm": D.PX,
            "norm": "per window (x - median) / (1.4826 MAD), clip -3..20, / 5", "checkpoint": "final",
            "step": final["step"], "monitor": {k: v for k, v in final.items() if k.endswith(("auc", "frac")) or k in ("mean_T1_T4", "select")},
            "seed": a.seed, "neg_shares": cfg["neg_shares"], "jitter_shares": cfg["jitter_shares"],
            "positives": a.positives, "permute_labels": a.permute_labels}
    export_numpy(model, out / "strokenet.npz", meta)
    (out / "history.json").write_text(json.dumps({"config": cfg, "history": hist, "final": final,
                                                  "final_select": final["select"], "best_select": best,
                                                  "best_step": best_step, "best_final_gap": best - final["select"],
                                                  "train_wall_s": time.time() - t_start}, indent=1) + "\n")
    print("done final select", final["select"], "best", best, "at step", best_step, flush=True)
    return final["select"]


if __name__ == "__main__":
    main()
