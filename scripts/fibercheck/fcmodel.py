"""A small local fiber judge: one fiber score per surface render, trained on Claude's answers to the frozen fiber pairs.

Pairs (on, other) of kinds C1 noise, C2 gap, C4 blur and R1 half offset are trained with binary cross-entropy of
sigmoid(score(on) - score(other)) against Claude's share of answers that preferred the on render; a phase-scrambled
copy of each on render (same power spectrum, strands destroyed, no seams) is a further negative with target 1. C3 tile
shuffle and C5 identical copies are never trained on. A pair is judged A or B by the larger score, SAME only on an exact tie.
Round 2 (the released weights) also trains on tile shuffles of 7, 21 and 28 pixels. Both rounds were
preregistered before any test image existed. cv and train need the training sets (fcdata.py), which are not
public; judging needs only the weights. Model output.

Usage:
  python3 scripts/fibercheck/fcmodel.py cv --sets work/fibercheck/sets          leave-one-scroll-out settings
  python3 scripts/fibercheck/fcmodel.py train --sets DIR --epochs N --lr LR --out W.pt
  python3 scripts/fibercheck/fcmodel.py judge --weights W.pt --set DIR --out replies.jsonl
"""
import argparse, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

TRAIN_KINDS = ("C1", "C2", "C4", "R1")
CROP = 112
SEED = 0


def load_png(path):
    """The PNG at about one pixel per voxel (the renders are drawn 3 pixels per voxel), z-scored."""
    from PIL import Image
    im = Image.open(path).convert("L")
    w, h = im.size
    im = im.resize((w // 3, h // 3), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)


PHASE = "phase:"


def phase_scramble(a, name):
    """Same amplitude spectrum, random phase (seeded by the file name): texture statistics kept, long strands gone."""
    import zlib
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    f = np.fft.fft2(a)
    ph = np.angle(np.fft.fft2(rng.standard_normal(a.shape)))
    b = np.real(np.fft.ifft2(np.abs(f) * np.exp(1j * ph))).astype(np.float32)
    return (b - b.mean()) / (b.std() + 1e-6)


def net():
    import torch.nn as nn

    def block(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(),
                             nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(), nn.MaxPool2d(2))
    return nn.Sequential(block(1, 8), block(8, 16), block(16, 32), block(32, 32),
                         nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(32, 1))


SHUF = "shuf"


def tile_shuffle(a, tile, name):
    """Turned and permuted tiles of side `tile` (seeded by the name): local texture kept, long strands cut."""
    import zlib
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    n = (min(a.shape) // tile) * tile
    b = a[:n, :n]
    tiles = [np.rot90(b[i:i + tile, j:j + tile], int(rng.integers(0, 4)))
             for i in range(0, n, tile) for j in range(0, n, tile)]
    order = rng.permutation(len(tiles))
    g = n // tile
    out = np.block([[tiles[order[i * g + j]] for j in range(g)] for i in range(g)]).astype(np.float32)
    return (out - out.mean()) / (out.std() + 1e-6)


class Pairs:
    """(on image, other image, target) for the trained kinds, images cached in memory. negatives: 'phase' and any
    'shufN' (tile shuffle with N-pixel tiles), each a synthetic negative with target 1."""

    def __init__(self, patches, negatives=("phase",)):
        self.cache, self.items = {}, []
        for p in patches:
            for k in TRAIN_KINDS:
                if k in p["claude"] and k in p["img"]:
                    self.items.append((p["img"]["on"], p["img"][k], p["claude"][k][0], k))
            for neg in negatives:
                pre = PHASE if neg == "phase" else f"{neg}:"
                self.items.append((p["img"]["on"], pre + p["img"]["on"], 1.0, neg))

    def img(self, path):
        if path not in self.cache:
            if path.startswith(PHASE):
                self.cache[path] = phase_scramble(load_png(path[len(PHASE):]), path)
            elif path.startswith(SHUF):
                head, src = path.split(":", 1)
                self.cache[path] = tile_shuffle(load_png(src), int(head[len(SHUF):]), path)
            else:
                self.cache[path] = load_png(path)
        return self.cache[path]


def _aug(a, b, rng):
    n = min(a.shape[0], b.shape[0])
    y, x = rng.integers(0, n - CROP + 1, size=2)
    a, b = a[y:y + CROP, x:x + CROP], b[y:y + CROP, x:x + CROP]
    r = int(rng.integers(0, 4))
    a, b = np.rot90(a, r), np.rot90(b, r)
    if rng.random() < 0.5:
        a, b = a[:, ::-1], b[:, ::-1]
    return np.ascontiguousarray(a), np.ascontiguousarray(b)


def train(patches, epochs, lr, batch=32, seed=SEED, say=print, negatives=("phase",)):
    import torch
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    ds = Pairs(patches, negatives)
    m = net()
    opt = torch.optim.AdamW(m.parameters(), lr=lr, weight_decay=1e-4)
    steps = epochs * max(1, len(ds.items) // batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, lr, total_steps=steps)
    m.train()
    for ep in range(epochs):
        order = rng.permutation(len(ds.items))
        tot = 0.0
        for s in range(0, len(order) - batch + 1, batch):
            A, B, T = [], [], []
            for i in order[s:s + batch]:
                on, ot, t, _ = ds.items[i]
                a, b = _aug(ds.img(on), ds.img(ot), rng)
                A.append(a), B.append(b), T.append(t)
            a = torch.from_numpy(np.stack(A))[:, None]
            b = torch.from_numpy(np.stack(B))[:, None]
            t = torch.tensor(T, dtype=torch.float32)
            s_ab = m(torch.cat([a, b])).squeeze(1)
            d = s_ab[:len(A)] - s_ab[len(A):]
            loss = torch.nn.functional.binary_cross_entropy_with_logits(d, t)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += float(loss.detach()) * len(A)
        say(f"epoch {ep + 1}/{epochs} loss {tot / max(1, len(order)):.4f}")
    m.eval()
    return m


def scores(m, paths):
    """Fiber score of each image: the mean over the centre crop and its four quarter turns."""
    import torch
    out = {}
    with torch.no_grad():
        for p in paths:
            a = load_png(p)
            n = min(a.shape)
            c0 = (a.shape[0] - n) // 2
            a = a[c0:c0 + n, c0:c0 + n]
            x = torch.from_numpy(np.stack([np.ascontiguousarray(np.rot90(a, r)) for r in range(4)]))[:, None]
            out[p] = float(m(x).mean())
    return out


def agreement(m, patches):
    """Per trained kind and C3: share of patches where the model prefers on, and its agreement with Claude's majority."""
    paths = sorted({f for p in patches for f in p["img"].values()})
    sc = scores(m, paths)
    res = {}
    for k in TRAIN_KINDS + ("C3",):
        on_pref, agree = [], []
        for p in patches:
            if k not in p["img"]:
                continue
            d = sc[p["img"]["on"]] - sc[p["img"][k]]
            on_pref.append(d > 0)
            if k in p["claude"] and p["claude"][k][0] != 0.5:
                agree.append((d > 0) == (p["claude"][k][0] > 0.5))
        res[k] = {"on_share": float(np.mean(on_pref)), "claude_agree": float(np.mean(agree)) if agree else None}
    return res


def cmd_cv(a):
    """Leave-one-scroll-out over the training scrolls for each (epochs, lr); C3 is not reported here (prereg)."""
    import fcdata as D          # training data lives only where the sets do; judging needs none of it
    ps = D.load(a.sets)
    scrolls = sorted({p["scroll"] for p in ps})
    grid = [(e, lr) for e in a.epochs for lr in a.lr]
    out = []
    for e, lr in grid:
        per = {}
        for s in scrolls:
            m = train([p for p in ps if p["scroll"] != s], e, lr, say=lambda *_: None, negatives=a.negatives.split(","))
            r = agreement(m, [p for p in ps if p["scroll"] == s])
            per[s] = {k: v for k, v in r.items() if k in TRAIN_KINDS}
        mean = float(np.mean([per[s][k]["claude_agree"] for s in scrolls for k in TRAIN_KINDS]))
        out.append({"epochs": e, "lr": lr, "mean_claude_agree": mean, "per_scroll": per})
        print(json.dumps(out[-1]), flush=True)
    best = max(out, key=lambda r: r["mean_claude_agree"])
    Path(a.out).write_text(json.dumps({"grid": out, "chosen": {"epochs": best["epochs"], "lr": best["lr"]}}, indent=1))
    print("chosen", best["epochs"], best["lr"])


def cmd_train(a):
    import torch
    import fcdata as D
    m = train(D.load(a.sets), a.epochs, a.lr, negatives=a.negatives.split(","))
    torch.save({"state": m.state_dict(), "epochs": a.epochs, "lr": a.lr, "seed": SEED, "negatives": a.negatives,
                "train_kinds": TRAIN_KINDS, "sets": list(D.SETS)}, a.out)
    print("saved", a.out)


def load_model(weights):
    import torch
    ck = torch.load(weights, map_location="cpu")
    m = net()
    m.load_state_dict(ck["state"])
    m.eval()
    return m


def cmd_judge(a):
    """Answer every pair of a frozen-format manifest (A, B or SAME) into a replies.jsonl the frozen scorer reads."""
    m = load_model(a.weights)
    man = json.load(open(Path(a.set) / "manifest.json"))
    paths = sorted({str(Path(a.set) / f) for r in man["requests"] for f in r["images"]})
    sc = scores(m, paths)
    with open(a.out, "w") as f:
        for r in man["requests"]:
            x, y = (sc[str(Path(a.set) / im)] for im in r["images"])
            ans = "SAME" if x == y else ("A" if x > y else "B")
            f.write(json.dumps({"id": r["id"], "reply": ans, "type": "succeeded"}) + "\n")
    print("wrote", a.out, len(man["requests"]), "answers")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cv")
    c.add_argument("--sets", required=True)
    c.add_argument("--epochs", type=int, nargs="+", default=[6, 12])
    c.add_argument("--lr", type=float, nargs="+", default=[2e-3])
    c.add_argument("--out", default="work/fibercheck/cv.json")
    c.add_argument("--negatives", default="phase", help="synthetic negatives: phase and shufN (round 2: phase,shuf7,shuf21,shuf28)")
    t = sub.add_parser("train")
    t.add_argument("--sets", required=True)
    t.add_argument("--epochs", type=int, required=True)
    t.add_argument("--lr", type=float, required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--negatives", default="phase")
    j = sub.add_parser("judge")
    j.add_argument("--weights", required=True)
    j.add_argument("--set", required=True)
    j.add_argument("--out", required=True)
    a = ap.parse_args()
    {"cv": cmd_cv, "train": cmd_train, "judge": cmd_judge}[a.cmd](a)


if __name__ == "__main__":
    main()
