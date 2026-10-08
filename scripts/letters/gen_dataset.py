"""Write synthetic line bands to sharded .npz files (uint8 images, texts, letter boxes)."""
import argparse
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import letterdata as L  # noqa: E402


def shard(args):
    out, seed, n, domain = args
    rng = np.random.default_rng(seed)
    imgs, texts, boxes, widths = [], [], [], []
    for _ in range(n):
        img, text, bx = L.make_sample(rng, domain=domain)
        imgs.append((img * 255).round().astype(np.uint8))
        texts.append(text)
        boxes.append(bx)
        widths.append(img.shape[1])
    H = imgs[0].shape[0]
    flat = np.concatenate([a.T.reshape(-1) for a in imgs])     # column-major per image
    np.savez(out, flat=flat, widths=np.array(widths, np.int32), height=H,
             texts=np.array(json.dumps(texts, ensure_ascii=False)),
             boxes=np.array(json.dumps(boxes)))
    return out


def load_shard(path):
    z = np.load(path)
    H = int(z["height"])
    widths = z["widths"]
    flat = z["flat"]
    texts = json.loads(str(z["texts"]))
    imgs, o = [], 0
    for w in widths:
        imgs.append(flat[o:o + H * w].reshape(w, H).T)
        o += H * w
    return imgs, texts, json.loads(str(z["boxes"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--shard", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--domain", default=None, choices=[None, "map", "mask"])
    ap.add_argument("--procs", type=int, default=os.cpu_count())
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    jobs = [(str(Path(a.out) / f"shard-{a.seed:04d}-{i:04d}.npz"), a.seed * 100003 + i, a.shard, a.domain)
            for i in range(a.n // a.shard)]
    t = time.time()
    with Pool(a.procs) as p:
        for k, o in enumerate(p.imap_unordered(shard, jobs), 1):
            print(f"{k}/{len(jobs)} {o} {time.time() - t:.0f}s", flush=True)
