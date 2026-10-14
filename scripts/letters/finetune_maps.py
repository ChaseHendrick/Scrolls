"""Fine-tune the letter reader on real ink-map lines whose text is published
(docs/letter-reader.md, Reproduce the benchmarks).

Training lines are the crops of p1667_align.py (each published line of a training column, cut from the map
along its fitted row at the reader's working scale), labelled with the published line.
A published '?' (a restored or illegible letter) is a wildcard that may be read as any letter or as nothing,
so the loss never asks the reader to invent a letter in a hole nor punishes it for seeing one there.
Every batch mixes map lines with synthetic and real-letterform lines from gen_dataset.py shards, so the
reader keeps what it knew. The schedule is fixed in advance and the last step is the model (no checkpoint is
chosen on held-out text).

Starts from any linenet-v1 .npz (BatchNorm already folded, so the network trains as plain convolutions), or
a released model's name such as letters-v2-real, and writes one (OUT_DIR/linenet.npz) with finetune.json, its
record: file names and SHA-256 of the start and the result, never a local folder.

  python scripts/letters/p1667_align.py crops ALIGN.json NPY_DIR --columns 9,10,12 --out LINES.npz
  python -m kit letterlines build RECORDS.json --split train --out LINES.npz      # your own lines instead
  python scripts/letters/finetune_maps.py train LINES.npz SHARDS_DIR --weights W --out OUT_DIR [--steps N]

Weights and map lines stay out of git (maps of a published scroll, but large and derived).
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p1667_align import load_lines  # noqa: E402
from kit import letterread as R  # noqa: E402
from kit.letterlines import check_references  # noqa: E402

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"
WILD = -1


# ------------------------------------------------------------------ the network, trainable from a folded .npz

def torch_net(weights):
    import torch
    import torch.nn as nn

    z = np.load(weights, allow_pickle=False)
    meta = json.loads(str(z["meta"]))

    class Folded(nn.Module):
        def __init__(self):
            super().__init__()
            self.meta = meta
            self.p = nn.ParameterDict({k: nn.Parameter(torch.from_numpy(z[k].astype(np.float32)))
                                       for k in z.files if k != "meta"})

        def forward(self, x):                  # B x 1 x H x W -> B x K x T
            F = torch.nn.functional
            for L in meta["layers"]:
                op, i = L["op"], L.get("id")
                if op == "conv2d":
                    x = F.relu(F.conv2d(x, self.p[f"w{i}"], self.p[f"b{i}"], padding=L["pad"]))
                elif op == "maxpool":
                    x = F.max_pool2d(x, tuple(L["k"]))
                elif op == "collapse":
                    x = F.relu(F.conv2d(x, self.p[f"w{i}"], self.p[f"b{i}"])).squeeze(2)
                elif op == "conv1d_res":
                    d = L["dilation"]
                    w = self.p[f"w{i}"]
                    x = x + F.relu(F.conv1d(x, w, self.p[f"b{i}"], padding=d * (w.shape[2] - 1) // 2, dilation=d))
                elif op == "head":
                    x = F.conv1d(x, self.p[f"w{i}"], self.p[f"b{i}"])
            return x

        def export(self, path):
            out = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in self.p.items()}
            np.savez(path, meta=np.array(json.dumps(meta, ensure_ascii=False)), **out)

    return Folded()


def pattern_dfa(target, K):
    """Deterministic automaton over the letters 1..K-1 for a target whose WILD entries each stand for one
    letter or none. State 0 is the start; delta[q][c] is the next state or -1; accept[q] says whether a
    letter string ending in q matches the whole target. Built by subset construction, so every letter
    string has one run, and a string that several readings of the wildcards produce is counted once."""
    n = len(target)

    def close(S):
        S, todo = set(S), list(S)
        while todo:
            i = todo.pop()
            if i < n and target[i] == WILD and i + 1 not in S:
                S.add(i + 1)
                todo.append(i + 1)
        return frozenset(S)

    order = [close({0})]
    index = {order[0]: 0}
    delta = []
    for S in order:                                   # grows while it is walked
        row = [-1] * K
        for c in range(1, K):
            nxt = close({i + 1 for i in S if i < n and target[i] in (c, WILD)})
            if nxt:
                if nxt not in index:
                    index[nxt] = len(order)
                    order.append(nxt)
                row[c] = index[nxt]
        delta.append(row)
    return delta, [n in S for S in order]


def wild_ctc(lp, targets, Ts):
    """Per-sample CTC negative log-likelihood, batched: lp (B x T x K log-probs), targets (lists of class ids,
    WILD for '?'), Ts (frames per sample).

    A '?' may be read as any one letter or as nothing. The likelihood is the total probability of every
    frame path whose collapsed letters (repeats merged, blanks dropped) match the target, each path once:
    the forward pass runs in log space over (automaton state, last frame's class), and the automaton
    (pattern_dfa) is deterministic. Without wildcards it equals the usual CTC loss."""
    import torch
    B, Tm, K = lp.shape
    dev, dt = lp.device, lp.dtype
    NEG = -1e30
    dfas = [pattern_dfa(tg, K) for tg in targets]
    Q = max(len(d) for d, _ in dfas)
    to = torch.full((B, Q, K), Q, dtype=torch.long)    # to[b, q, c]: the state letter c leads to; Q = none
    final = torch.full((B, Q), NEG, dtype=dt)          # 0 on accepting states
    for b, (delta, acc) in enumerate(dfas):
        for q, row in enumerate(delta):
            if acc[q]:
                final[b, q] = 0.0
            for c, r in enumerate(row):
                if r >= 0:
                    to[b, q, c] = r
    to, final = to.to(dev), final.to(dev)
    alpha = torch.full((B, Q, K), NEG, dtype=dt, device=dev)
    alpha[:, 0, 0] = 0.0                              # nothing read yet; as if the last frame were a blank
    neg = torch.full((B, Q, 1), NEG, dtype=dt, device=dev)
    Ts_t = torch.as_tensor(Ts, device=dev)
    for t in range(Tm):
        below = torch.cat([neg, torch.logcumsumexp(alpha, 2)[:, :, :-1]], 2)                 # last class < c
        above = torch.cat([torch.logcumsumexp(alpha.flip(2), 2).flip(2)[:, :, 1:], neg], 2)  # last class > c
        other = torch.logaddexp(below, above)
        # a new letter c: log-sum-exp of `other` over the states that c takes to the same state
        top = torch.full((B, Q + 1, K), NEG, dtype=dt, device=dev).scatter_reduce(
            1, to, other.detach(), reduce="amax", include_self=True)
        S = torch.zeros((B, Q + 1, K), dtype=dt, device=dev).scatter_add(1, to, (other - top.gather(1, to)).exp())
        fresh = torch.where(S > 0, S.clamp_min(0.5).log() + top, torch.full_like(S, NEG))[:, :Q]
        stay = torch.cat([torch.logsumexp(alpha, 2, keepdim=True), alpha[:, :, 1:]], 2)      # a blank, or c again
        new = torch.logaddexp(stay, fresh) + lp[:, t, None, :]
        alpha = torch.where((t < Ts_t)[:, None, None], new, alpha)
    return -torch.logsumexp(torch.logsumexp(alpha, 2) + final, 1)


def encode(text):
    return [WILD if ch == "?" else ALPHABET.index(ch) + 1 for ch in text]


def augment(a, rng, h=16):
    """Small vertical shift and scale, then contrast, gamma and noise."""
    H, W = a.shape
    s = rng.uniform(0.9, 1.1)
    dy = rng.uniform(-0.15, 0.15) * h
    ys = np.clip((np.arange(H) - H / 2 + dy) / s + H / 2, 0, H - 1)
    Wn = max(8, int(round(W * rng.uniform(0.92, 1.08))))
    xs = np.clip(np.arange(Wn) * W / Wn, 0, W - 1)
    y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
    y1, x1 = np.minimum(y0 + 1, H - 1), np.minimum(x0 + 1, W - 1)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    a = (a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx) * (1 - fy) + (a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx) * fy
    a = np.clip(a, 0, 1) ** rng.uniform(0.7, 1.4)
    a = a * rng.uniform(0.7, 1.1) + rng.uniform(0, 0.1)
    return np.clip(a + rng.normal(0, rng.uniform(0, 0.04), a.shape), 0, 1).astype(np.float32)


def train(lines_npz, shards, weights, out, steps=1500, batch=24, p_map=0.5, lr=3e-4, seed=0, threads=4, device="cpu"):
    mimgs, mtexts, _, lines_meta = load_lines(lines_npz)
    try:   # every text in the alphabet, '?' a wildcard: refused before torch loads or a folder is made
        check_references({f"line {i}": t for i, t in enumerate(mtexts)}, alphabet=ALPHABET,
                         source=Path(lines_npz).name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    import torch
    from gen_dataset import load_shard
    import glob
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    simgs, stexts = [], []
    for f in sorted(glob.glob(str(Path(shards) / "*.npz")))[:12]:
        im, tx, _ = load_shard(f)
        simgs += im
        stexts += tx
    if not simgs and round(batch * p_map) < batch:
        raise SystemExit(f"{shards}: no shard .npz files; make the synthetic lines with scripts/letters/gen_dataset.py")
    model = torch_net(weights).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.1)
    nm = int(round(batch * p_map))
    t0, hist = time.time(), []
    for step in range(1, steps + 1):
        items = [(augment(mimgs[i].astype(np.float32) / 255, rng), mtexts[i]) for i in rng.integers(0, len(mimgs), nm)]
        items += [(augment(simgs[i].astype(np.float32) / 255, rng), stexts[i])
                  for i in rng.integers(0, len(simgs), batch - nm)]
        W = int(math.ceil(max(a.shape[1] for a, _ in items) / 4) * 4)
        x = np.zeros((len(items), 1, items[0][0].shape[0], W), np.float32)
        for k, (a, _) in enumerate(items):
            x[k, 0, :, :a.shape[1]] = a
            x[k, 0, :, a.shape[1]:] = np.median(a)
        lg = model(torch.from_numpy(x).to(device))
        lp = torch.log_softmax(lg, 1).permute(0, 2, 1)                    # B T K
        nll = wild_ctc(lp, [encode(t) for _, t in items], [a.shape[1] // 4 for a, _ in items])
        loss = (nll / torch.tensor([max(1, len(t)) for _, t in items], device=nll.device)).mean()
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        opt.step()
        sched.step()
        hist.append(loss.item())
        if step % 25 == 0:
            print(f"step {step} loss {np.mean(hist[-25:]):.3f} {time.time() - t0:.0f}s", flush=True)
    model.export(out / "linenet.npz")
    # file names and SHA-256 only, so the record can be shared without a local folder
    info = {"device": device, "base": Path(weights).name, "base_sha256": R._sha256(weights),
            "lines": Path(lines_npz).name, "lines_meta": lines_meta, "map_lines": len(mimgs),
            "shards": Path(shards).name, "steps": steps, "batch": batch, "p_map": p_map, "lr": lr, "seed": seed,
            "seconds": round(time.time() - t0, 1), "loss_last_100": round(float(np.mean(hist[-100:])), 4),
            "model": "linenet.npz", "model_sha256": R._sha256(out / "linenet.npz"),
            "note": "A fine-tuned letter reader: a new model whose output is still a hypothesis for a person to check; "
                    "judge it on lines it did not train on (python -m kit letterlines score)."}
    (out / "finetune.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("done", info, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("lines")
    t.add_argument("shards")
    t.add_argument("--weights", required=True, help="the model to start from: a released name such as "
                                                    "letters-v2-real, or a linenet-v1 .npz")
    t.add_argument("--out", required=True)
    t.add_argument("--steps", type=int, default=1500)
    t.add_argument("--batch", type=int, default=24)
    t.add_argument("--p-map", type=float, default=0.5)
    t.add_argument("--lr", type=float, default=3e-4)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--threads", type=int, default=4)
    t.add_argument("--device", default="cpu")
    a = ap.parse_args()
    if a.cmd == "train":
        if a.steps < 20:
            ap.error("--steps: give at least 20 (the one-cycle schedule warms up over a tenth of them)")
        weights = R.resolve_weights(a.weights)      # a released name is downloaded once and SHA-256 checked
        train(a.lines, a.shards, weights, a.out, a.steps, a.batch, a.p_map, a.lr, a.seed, a.threads, a.device)


if __name__ == "__main__":
    main()
