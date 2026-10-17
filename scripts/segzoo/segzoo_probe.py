"""Frozen-feature probe: DINOv2 or DINOv3 features of 2D images, a logistic head trained on one set, scored once on
another, with bootstrap intervals and a paired comparison against another method's per-item hits.

This is the cheapest way to ask whether a big pretrained image model helps a small 2D task here (single
letters, triage windows, ink at a face) before paying for any fine-tune: the backbone stays frozen, so the only
thing learned is a linear head, and it runs on a CPU.

  features  IMAGES.npz -> FEATURES.npz. IMAGES.npz holds `images` (n, H, W) or (n, 3, H, W), uint8 or float in
            [0, 1]; `labels` (n,) and `groups` (n,) are copied through when present. --model is a Hugging Face
            id: facebook/dinov2-small (Apache-2.0, open) or facebook/dinov3-vits16-pretrain-lvd1689m (DINOv3
            License, gated: needs an approved, logged-in account)
  fit       TRAIN.npz TEST.npz -> RESULT.json: a multinomial logistic head on standardised training features
            (L2 penalty chosen by grouped cross-validation on the training set only), then one pass over the
            test set: accuracy with a 95% bootstrap interval, per-class accuracy, a label-permutation control,
            and with --against HITS.json the paired difference against another method's per-item hits

Every prediction is model output. The test set is read once, after the head is fixed.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

L2_GRID = (1e-4, 1e-3, 1e-2, 1e-1, 1.0)


def as_float_images(images):
    x = np.asarray(images)
    if x.dtype == np.uint8:
        return x.astype(np.float32) / 255.0
    x = x.astype(np.float32)
    if x.size and (x.min() < -1e-6 or x.max() > 1 + 1e-6):
        raise ValueError("float images must lie in [0, 1]")
    return x


def standardise(train, *others):
    mu, sd = train.mean(0), train.std(0) + 1e-6
    return [(train - mu) / sd] + [(o - mu) / sd for o in others]


def fit_softmax(X, y, n_classes, l2=1e-2, iters=200):
    """Multinomial logistic regression by L-BFGS in torch (float64). Returns (W (d, k), b (k,))."""
    import torch
    Xt = torch.as_tensor(X, dtype=torch.float64)
    yt = torch.as_tensor(y, dtype=torch.long)
    W = torch.zeros(X.shape[1], n_classes, dtype=torch.float64, requires_grad=True)
    b = torch.zeros(n_classes, dtype=torch.float64, requires_grad=True)
    opt = torch.optim.LBFGS([W, b], lr=1.0, max_iter=iters, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.cross_entropy(Xt @ W + b, yt) + l2 * (W * W).sum()
        loss.backward()
        return loss

    opt.step(closure)
    return W.detach().numpy(), b.detach().numpy()


def predict(X, W, b):
    z = X @ W + b
    z = z - z.max(1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(1, keepdims=True)


def choose_l2(X, y, groups, n_classes, grid=L2_GRID, folds=5):
    """The grid value with the best mean accuracy over group folds of the training set (groups never split)."""
    ug = sorted(set(groups))
    if len(ug) < 2:
        return grid[len(grid) // 2], {}
    k = min(folds, len(ug))
    fold_of = {g: i % k for i, g in enumerate(ug)}
    f = np.array([fold_of[g] for g in groups])
    scores = {}
    for l2 in grid:
        acc = []
        for i in range(k):
            tr, va = f != i, f == i
            if not va.any() or not tr.any():
                continue
            Xs, Vs = standardise(X[tr], X[va])
            W, b = fit_softmax(Xs, y[tr], n_classes, l2=l2)
            acc.append(float((predict(Vs, W, b).argmax(1) == y[va]).mean()))
        scores[l2] = float(np.mean(acc)) if acc else 0.0
    best = max(grid, key=lambda v: (scores.get(v, 0.0), -v))
    return best, scores


def bootstrap(hits, reps=10000, seed=0):
    hits = np.asarray(hits, dtype=np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, hits.size, size=(reps, hits.size))
    m = hits[idx].mean(1)
    return float(hits.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def paired(a, b, reps=10000, seed=0):
    """Mean of a - b over items with a 95% bootstrap interval; verdict better / worse / no clear difference."""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    if a.shape != b.shape:
        raise ValueError("paired hits must cover the same items")
    d, lo, hi = bootstrap(a - b, reps, seed)
    verdict = "better" if lo > 0 else "worse" if hi < 0 else "no clear difference"
    return {"difference": round(d, 4), "low": round(lo, 4), "high": round(hi, 4), "verdict": verdict}


def permutation_control(Xtr, ytr, Xte, yte, n_classes, l2, reps=20, seed=0):
    """Accuracy of heads trained on shuffled training labels: what the pipeline reaches with no signal."""
    rng = np.random.default_rng(seed)
    accs = []
    for _ in range(reps):
        W, b = fit_softmax(Xtr, rng.permutation(ytr), n_classes, l2=l2)
        accs.append(float((predict(Xte, W, b).argmax(1) == yte).mean()))
    return {"mean": round(float(np.mean(accs)), 4), "max": round(float(np.max(accs)), 4), "reps": reps}


def run_fit(train, test, against=None, seed=0):
    """train / test: dicts with features (n, d), labels (n,), groups (n,), optional ids (n,). Returns the result."""
    classes = sorted(set(map(str, train["labels"])))
    index = {c: i for i, c in enumerate(classes)}
    unknown = sorted(set(map(str, test["labels"])) - set(classes))
    if unknown:
        raise ValueError(f"test labels never seen in training: {unknown}")
    ytr = np.array([index[str(v)] for v in train["labels"]])
    yte = np.array([index[str(v)] for v in test["labels"]])
    l2, cv = choose_l2(train["features"], ytr, [str(g) for g in train["groups"]], len(classes))
    Xtr, Xte = standardise(train["features"], test["features"])
    W, b = fit_softmax(Xtr, ytr, len(classes), l2=l2)
    pred = predict(Xte, W, b).argmax(1)
    hits = (pred == yte).astype(int)
    acc, lo, hi = bootstrap(hits, seed=seed)
    per_class = {c: round(float(hits[yte == i].mean()), 4) for i, c in enumerate(classes) if (yte == i).any()}
    ids = [str(v) for v in test.get("ids", range(len(yte)))]
    out = {"n_train": int(len(ytr)), "n_test": int(len(yte)), "classes": classes, "l2": l2,
           "cv_accuracy": {str(k): round(v, 4) for k, v in cv.items()},
           "accuracy": round(acc, 4), "low": round(lo, 4), "high": round(hi, 4), "per_class": per_class,
           "control_shuffled_labels": permutation_control(Xtr, ytr, Xte, yte, len(classes), l2, seed=seed),
           "predictions": {i: classes[p] for i, p in zip(ids, pred)}, "hits": {i: int(h) for i, h in zip(ids, hits)}}
    if against:
        other = against["hits"]
        missing = [i for i in ids if i not in other]
        if missing:
            raise ValueError(f"--against lacks {len(missing)} test items, such as {missing[:3]}")
        out["paired_against"] = dict(paired(hits, [other[i] for i in ids], seed=seed), name=against.get("name"))
    return out


def _load(path):
    z = np.load(path, allow_pickle=False)
    return {k: z[k] for k in z.files}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    f = sub.add_parser("features", help="frozen backbone features for every image")
    f.add_argument("images", help=".npz with images (and labels, groups, ids when present)")
    f.add_argument("--model", default="facebook/dinov2-small", help="Hugging Face id of a DINOv2 or DINOv3 model")
    f.add_argument("--revision", default=None, help="model revision (commit) to pin")
    f.add_argument("--size", type=int, default=224, help="input side in pixels (default 224)")
    f.add_argument("--device", default="cpu")
    f.add_argument("--out", required=True)
    g = sub.add_parser("fit", help="train the head on TRAIN, score once on TEST")
    g.add_argument("train")
    g.add_argument("test")
    g.add_argument("--against", default=None,
                   help="JSON {\"name\": ..., \"hits\": {id: 0 or 1}} of another method on the same test items")
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        if a.action == "features":
            from segzoo_nets import FrozenFeatures
            d = _load(a.images)
            fx = FrozenFeatures(a.model, device=a.device, size=a.size, revision=a.revision)
            feats = fx.features(as_float_images(d["images"]))
            extra = {k: d[k] for k in ("labels", "groups", "ids") if k in d}
            np.savez_compressed(a.out, features=feats, model=a.model, **extra)
            print(f"wrote {a.out}: {feats.shape[0]} images x {feats.shape[1]} features from {a.model}")
            return 0
        against = json.loads(Path(a.against).read_text()) if a.against else None
        res = run_fit(_load(a.train), _load(a.test), against=against, seed=a.seed)
        Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
        line = f"accuracy {res['accuracy']} [{res['low']}, {res['high']}] on {res['n_test']}; " \
               f"shuffled-label control {res['control_shuffled_labels']['mean']}"
        if "paired_against" in res:
            pa = res["paired_against"]
            line += f"; against {pa['name']}: {pa['difference']} [{pa['low']}, {pa['high']}] {pa['verdict']}"
        print(line)
        return 0
    except (ValueError, OSError, KeyError) as e:
        print(f"segzoo_probe {a.action}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
