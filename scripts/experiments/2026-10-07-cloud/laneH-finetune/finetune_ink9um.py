"""Low-LR fine-tune of an ink_9um checkpoint (lane H, 2026-10-07).

Targets are either human labels (arm S, supervised) or confident pseudo-labels
from a base ink_9um map (arm P, self-training). Training windows are drawn only
where the whole patch lies at least --gap px outside every --exclude box
(test crops). Training inputs exclude those pixels; the arm P teacher still
processes the whole same-segment canvas and is not an independent-scroll audit.

Writes a checkpoint {"config", "state_dict"} that villa's flat inference loads
unchanged, plus a JSON training log. Weights stay outside git.
"""
from __future__ import annotations

import argparse, hashlib, json, math, subprocess, sys, time
from pathlib import Path

import numpy as np
from training_guard import (allowed_mask, exclude_targets, pooled_targets, pseudo_targets,
                            VILLA_REVISION, CHECKPOINT_SHA256)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True, type=Path)
    p.add_argument("--volume", required=True, help="full-surface 9 um zarr (group with level 0)")
    p.add_argument("--labels", help="inklabels.zarr (arm S)")
    p.add_argument("--mask", help="supervision.zarr (arm S)")
    p.add_argument("--level", default="2")
    p.add_argument("--pseudo-map", help="base model forward map .tif on the full surface (arm P)")
    p.add_argument("--ink-thr", type=float, default=0.90, help="arm P: map >= this is ink")
    p.add_argument("--bg-thr", type=float, default=0.10, help="arm P: map <= this is not ink")
    p.add_argument("--exclude", type=int, nargs=4, action="append", default=[], metavar=("Y0", "Y1", "X0", "X1"))
    p.add_argument("--gap", type=int, default=64)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--steps-per-epoch", type=int, default=400)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--min-supervised", type=float, default=0.10)
    p.add_argument("--seed", type=int, default=20261007)
    p.add_argument("--out", required=True, type=Path, help="output directory (outside git)")
    p.add_argument("--device", default="cpu")
    p.add_argument("--execute", action="store_true", help="explicitly run authorized training; default refuses execution")
    p.add_argument("--allow-gpu", action="store_true", help="explicitly opt in to already authorized CUDA compute")
    p.add_argument("--villa-root", required=True, type=Path)
    p.add_argument("--smoke", type=int, default=0, help="run only N steps (pipeline test, not a result)")
    a = p.parse_args(argv)
    if not a.execute:
        p.error("not run: --execute is required for authorized training")
    if a.device != "cpu" and not a.allow_gpu:
        p.error("GPU training requires explicit --allow-gpu and prior budget authorization")
    if not a.exclude or min(a.epochs, a.steps_per_epoch, a.batch_size) < 1 or a.smoke < 0:
        p.error("require exclusions, positive training counts and nonnegative smoke steps")
    if not math.isfinite(a.lr) or a.lr <= 0 or not math.isfinite(a.min_supervised) or not 0 < a.min_supervised <= 1:
        p.error("require finite positive learning rate and 0 < min-supervised <= 1")
    if a.out.exists() and any(a.out.iterdir()):
        p.error("output directory must be empty; do not reuse a historical checkpoint")
    if a.labels is not None and a.mask is None:
        p.error("supervised training requires both --labels and --mask")
    if (a.pseudo_map is None) == (a.labels is None):
        p.error("give exactly one of --labels/--mask (arm S) or --pseudo-map (arm P)")
    import torch
    import torch.nn.functional as F
    import zarr
    from vesuvius.ink_detection.config import InkConfig
    from vesuvius.ink_detection.inference.infer import (flat_preprocessing_from_config, normalize_flat_patch, select_layer_indices)
    from vesuvius.ink_detection.inference.inference_runtime import TargetModel
    from vesuvius.ink_detection.models.checkpoint import load_checkpoint, select_inference_weights, load_model_state
    from vesuvius.ink_detection.models.model import make_model
    revision = subprocess.check_output(["git", "-C", str(a.villa_root), "rev-parse", "HEAD"], text=True).strip()
    if revision != VILLA_REVISION:
        p.error("villa checkout differs from the pinned compatible revision")
    digest = hashlib.sha256()
    with a.checkpoint.open("rb") as checkpoint_file:
        for block in iter(lambda: checkpoint_file.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != CHECKPOINT_SHA256:
        p.error("base checkpoint SHA256 differs from the pinned published seed42 artifact")
    rng = np.random.default_rng(a.seed); torch.manual_seed(a.seed)
    dev = torch.device(a.device)

    payload = load_checkpoint(a.checkpoint)
    cfg = InkConfig.from_mapping(payload["config"])
    _, state = select_inference_weights(payload, source=a.checkpoint)
    if cfg.data.mode != "flat" or cfg.model.crop_size[1] != cfg.model.crop_size[2]:
        p.error("require a flat checkpoint with square spatial patches")
    base = make_model(cfg)
    load_model_state(base, state)  # Official strict loading, including DDP key handling.
    model = TargetModel(base, input_pad_depth_to=cfg.model.input_pad_depth_to).to(dev).train()
    depth, patch, _ = cfg.model.crop_size
    prep = flat_preprocessing_from_config(cfg.data.normalization)

    root = zarr.open(a.volume, mode="r"); vol = root["0"] if not hasattr(root, "shape") else root
    if len(vol.shape) != 3:
        p.error("volume must have shape depth,height,width")
    D, H, W = vol.shape
    layers = select_layer_indices(D, layer_start=None, layer_end=None, output_depth=depth, direction="forward")

    if len(layers) != depth:
        p.error("volume has fewer layers than the checkpoint input depth")
    if a.labels:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from kit.auc import labels_on_map
        ink, sup = labels_on_map(a.labels, a.mask, a.level, (H, W), None, (H, W))
        target = ink.astype(np.float32); weight = sup.astype(np.float32)
        source = "labels"
    else:
        import tifffile
        m = np.asarray(tifffile.imread(a.pseudo_map))
        if m.shape != (H, W):
            p.error("pseudo map and full-volume canvas shapes differ")
        target, weight = pseudo_targets(m, a.ink_thr, a.bg_thr)
        source = f"pseudo ink>={a.ink_thr} bg<={a.bg_thr}"
    weight = exclude_targets(weight, a.exclude, a.gap, patch)
    ok = allowed_mask((H, W), a.exclude, a.gap, patch)
    # candidate corners on a coarse grid with enough supervised pixels
    step = max(1, patch // 4)
    cands = [(y, x) for y in range(0, H - patch + 1, step) for x in range(0, W - patch + 1, step)
             if ok[y, x] and weight[y:y + patch, x:x + patch].mean() >= a.min_supervised]
    if not cands:
        sys.exit("no admissible training windows")
    ink_frac = float((target * weight).sum() / max(weight.sum(), 1))
    print(f"{len(cands)} windows, patch {patch}, depth {depth}, layers {layers.tolist()}, "
          f"target {source}, supervised ink fraction {ink_frac:.3f}, strict checkpoint load", flush=True)

    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    total = a.smoke or a.epochs * a.steps_per_epoch
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 0.5 * (1 + math.cos(math.pi * min(s, total) / total)))
    pos_w = torch.tensor((1 - ink_frac) / max(ink_frac, 1e-3), device=dev).clamp(max=10)
    log, t0, a.out = [], time.time(), a.out; a.out.mkdir(parents=True, exist_ok=True)

    def batch():
        xs, ys, ws = [], [], []
        for i in rng.integers(0, len(cands), a.batch_size):
            y, x = cands[i]
            v = np.asarray(vol[:, y:y + patch, x:x + patch])[layers]
            if rng.random() < 0.5: v = v[:, :, ::-1]; flip = 1
            else: flip = 0
            xs.append(normalize_flat_patch(np.ascontiguousarray(v), prep).astype(np.float32))
            t, w = target[y:y + patch, x:x + patch], weight[y:y + patch, x:x + patch]
            if flip: t, w = t[:, ::-1], w[:, ::-1]
            ys.append(t.copy()); ws.append(w.copy())
        return (torch.from_numpy(np.stack(xs))[:, None].to(dev), torch.from_numpy(np.stack(ys))[:, None].to(dev),
                torch.from_numpy(np.stack(ws))[:, None].to(dev))

    for step_i in range(total):
        x, y, w = batch()
        with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
            logits = model(x)
        logits = logits.float()
        if logits.ndim == 5: logits = logits.mean(2)
        if logits.ndim == 3: logits = logits[:, None]
        yd, wd = pooled_targets(F, y, w, logits.shape[-2:])
        loss = (F.binary_cross_entropy_with_logits(logits, yd, pos_weight=pos_w, reduction="none") * wd).sum() / wd.sum().clamp(min=1)
        opt.zero_grad(set_to_none=True); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); sched.step()
        if step_i % 20 == 0 or step_i == total - 1:
            log.append({"step": step_i, "loss": float(loss), "lr": sched.get_last_lr()[0], "s": round(time.time() - t0, 1)})
            print(json.dumps(log[-1]), flush=True)
        if not a.smoke and (step_i + 1) % a.steps_per_epoch == 0:
            ep = (step_i + 1) // a.steps_per_epoch
            torch.save({"config": payload["config"], "state_dict": model.model.state_dict()}, a.out / f"epoch{ep}.pth")
    torch.save({"config": payload["config"], "state_dict": model.model.state_dict()}, a.out / "last.pth")
    json.dump({"args": {k: str(v) for k, v in vars(a).items()}, "windows": len(cands), "ink_fraction": ink_frac,
               "seconds": round(time.time() - t0, 1), "log": log, "smoke": bool(a.smoke),
               "villa_revision": revision, "base_checkpoint_sha256": digest.hexdigest()}, open(a.out / "train_log.json", "w"), indent=1)


if __name__ == "__main__":
    main()
