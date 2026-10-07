"""Checkpoint soup: the uniform weight average of several checkpoints of ONE training run.

After Nieuwlaar's make_soup.py (https://github.com/Nieuwlaar/ink9um-dense-native), whose
soup42_last4 (the last four released ink_9um seed-42 checkpoints, steps 40k to 75k)
gained 0.03 to 0.06 AUC on PHerc0139. His other finding is the reason for the guard
below: averaging the weights of different seeds gave AUC 0.49, a broken model. Different
runs sit in different basins; average their maps (`python -m kit ensemble`), not their weights.

    python scripts/soup.py out.pth step-040000.pth step-050000.pth step-060000.pth step-075000.pth

Keeps the first input's non-tensor payload (config, step), adds a "soup" entry with the
inputs' SHA-256, and refuses checkpoints whose config seeds differ unless --allow-cross-seed.
"""

import argparse
import hashlib
import sys

import torch

STATE_KEYS = ("model", "ema_model", "model_state_dict", "state_dict", "network_weights")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def state_key(payload):
    if not isinstance(payload, dict):
        return None
    return next((k for k in STATE_KEYS if k in payload and isinstance(payload[k], dict)), None)


def seed(payload):
    cfg = payload.get("config") if isinstance(payload, dict) else None
    return cfg.get("seed") if isinstance(cfg, dict) else None


def soup(paths, allow_cross_seed=False):
    first = torch.load(paths[0], map_location="cpu", weights_only=False)
    key = state_key(first)
    sd = first[key] if key else first
    acc = {k: v.double().clone() if torch.is_tensor(v) and v.is_floating_point() else v for k, v in sd.items()}
    seeds = {seed(first)}
    for p in paths[1:]:
        other = torch.load(p, map_location="cpu", weights_only=False)
        if state_key(other) != key:
            raise ValueError(f"{p}: state key {state_key(other)!r}, expected {key!r}")
        osd = other[key] if key else other
        if osd.keys() != sd.keys():
            raise ValueError(f"{p}: different tensor names from {paths[0]}")
        seeds.add(seed(other))
        for k, v in osd.items():
            if torch.is_tensor(v) and v.is_floating_point():
                if v.shape != sd[k].shape:
                    raise ValueError(f"{p}: {k} has shape {tuple(v.shape)}, expected {tuple(sd[k].shape)}")
                acc[k] += v.double()
    if len(seeds) > 1 and not allow_cross_seed:
        raise ValueError(f"checkpoints come from seeds {sorted(seeds, key=str)}: a cross-run weight soup "
                         "breaks the model (Nieuwlaar: AUC 0.49). Average the maps instead, or pass --allow-cross-seed.")
    n = len(paths)
    for k, v in acc.items():
        if torch.is_tensor(v) and v.is_floating_point():
            acc[k] = (v / n).to(sd[k].dtype)
    meta = {"inputs": [{"path": str(p), "sha256": sha256(p)} for p in paths], "n": n, "method": "uniform weight mean"}
    if key:
        first[key] = acc
        first["soup"] = meta
        return first, meta
    return acc, meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--allow-cross-seed", action="store_true")
    args = ap.parse_args(argv)
    if len(args.inputs) < 2:
        ap.error("need at least two checkpoints")
    payload, meta = soup(args.inputs, args.allow_cross_seed)
    torch.save(payload, args.out)
    print(f"soup of {meta['n']} -> {args.out} sha256 {sha256(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
