"""Fit the radar's learned relevance head (head.json) from blind ratings of collected items.

Input: a JSON list of items as the radar stores them (GET /api/items or the store file) and a ratings file mapping each
item id to one or more raters' {"value": 0..100}. The target is the mean rating. Two ridge heads are fitted: "full"
(bge-small embedding of the item text plus metadata) and "meta" (metadata only, for items with no embedding). Each head
is calibrated to 0..100 by isotonic regression on out-of-fold predictions, so the mapping is monotone and the bands
mean what the ratings mean. Nested cross-validation reports what to expect on new items. Training needs scikit-learn
and scipy; the Space itself only needs numpy to apply the head.

  python train_head.py --items items.json --ratings ratings.json --out head.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json

import numpy as np

import scanner


def mean_rating(r) -> float:
    vals = [v["value"] for v in (r.values() if isinstance(r, dict) and "value" not in r else [r])]
    return float(np.mean(vals))


def fit(X, y, alphas):
    from sklearn.linear_model import RidgeCV
    return RidgeCV(alphas=alphas).fit(X, y)


def oof(X, y, alphas, seed, folds=5):
    from sklearn.model_selection import KFold
    pred = np.zeros(len(y))
    for tr, te in KFold(folds, shuffle=True, random_state=seed).split(X):
        pred[te] = fit(X[tr], y[tr], alphas).predict(X[te])
    return pred


def calibrator(pred, y, how="quantile"):
    """Map raw predictions to 0..100. "quantile" (default) gives the k-th percentile prediction the k-th percentile
    rating, so each band holds about as many items as the ratings put there; "isotonic" maps to the expected rating,
    which keeps fewer, surer items in the high band."""
    if how == "isotonic":
        from sklearn.isotonic import IsotonicRegression
        iso = IsotonicRegression(y_min=0, y_max=100, out_of_bounds="clip").fit(pred, y)
        return iso.X_thresholds_, iso.y_thresholds_
    q = np.linspace(0, 1, 41)
    cx, cy = np.quantile(pred, q), np.quantile(y, q)
    keep = np.r_[True, np.diff(cx) > 1e-9]  # np.interp needs increasing x
    return cx[keep], cy[keep]


def band(v, cfg):
    return "high" if v >= cfg["bands"]["high"] else "medium" if v >= cfg["bands"]["medium"] else "low"


def nested(X, y, alphas, cfg, reps=5, how="quantile"):
    """Outer 5-fold: fit ridge and its calibration on the training part only, score the held-out part."""
    from scipy.stats import spearmanr
    from sklearn.model_selection import KFold
    rho, prec, rec, n_hi = [], [], [], []
    for seed in range(reps):
        out = np.zeros(len(y))
        for tr, te in KFold(5, shuffle=True, random_state=100 + seed).split(X):
            cx, cy = calibrator(oof(X[tr], y[tr], alphas, seed), y[tr], how)
            out[te] = np.interp(fit(X[tr], y[tr], alphas).predict(X[te]), cx, cy)
        rho.append(spearmanr(out, y)[0])
        hp = np.array([band(v, cfg) == "high" for v in out])
        ht = np.array([band(v, cfg) == "high" for v in y])
        prec.append((hp & ht).sum() / max(1, hp.sum()))
        rec.append((hp & ht).sum() / max(1, ht.sum()))
        n_hi.append(int(hp.sum()))
    return {"spearman": round(float(np.mean(rho)), 3), "spearman_sd": round(float(np.std(rho)), 3),
            "high_precision": round(float(np.mean(prec)), 2), "high_recall": round(float(np.mean(rec)), 2),
            "high_items": round(float(np.mean(n_hi)), 1)}


def main(argv=None) -> int:
    from scipy.stats import spearmanr
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", required=True)
    ap.add_argument("--ratings", required=True)
    ap.add_argument("--out", default=str(scanner.HERE / "head.json"))
    ap.add_argument("--models", default=None, help="fastembed cache directory")
    ap.add_argument("--calibration", choices=("quantile", "isotonic"), default="quantile")
    a = ap.parse_args(argv)
    cfg = scanner.load_config()
    items = {i["id"]: i for i in json.load(open(a.items))}
    ratings = json.load(open(a.ratings))
    ids = sorted(k for k in ratings if k in items)
    y = np.array([mean_rating(ratings[k]) for k in ids])
    sources = sorted({items[k]["source"] for k in ids})
    kinds = sorted({items[k]["kind"] for k in ids})
    M = np.array([scanner.Head.features(items[k], sources, kinds) for k in ids], "float32")

    from fastembed import TextEmbedding
    model = TextEmbedding(cfg["semantic"]["model"], cache_dir=a.models)
    texts = [scanner.embed_text(cfg, items[k]["title"], items[k].get("summary") or "") for k in ids]
    E = np.array(list(model.embed(texts, batch_size=64)), "float32")
    E /= np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)

    alphas = np.logspace(-2, 3, 20)
    rule = np.array([items[k]["score"] for k in ids])
    report = {"rule_score": round(float(spearmanr(rule, y)[0]), 3),
              "keyword": round(float(spearmanr([items[k]["keyword"] for k in ids], y)[0]), 3)}
    out = {"version": 1, "trained": dt.date.today().isoformat(), "items": len(ids), "target": "mean blind rating 0..100",
           "embedding": cfg["semantic"]["model"], "meta_features": scanner.META_FEATURES, "sources": sources,
           "kinds": kinds, "calibration": a.calibration}
    for name, X in (("full", np.hstack([E, M])), ("meta", M)):
        report[name] = nested(X, y, alphas, cfg, how=a.calibration)
        r = fit(X, y, alphas)
        cx, cy = calibrator(oof(X, y, alphas, 0), y, a.calibration)
        coef = r.coef_.astype(float)
        h = {"alpha": float(r.alpha_), "intercept": round(float(r.intercept_), 6),
             "coef_meta": [round(c, 6) for c in coef[-M.shape[1]:]],
             "cal_x": [round(float(v), 4) for v in cx], "cal_y": [round(float(v), 2) for v in cy]}
        if name == "full":
            h["coef_emb"] = [round(c, 6) for c in coef[:E.shape[1]]]
        out[name] = h
    rule_hi = np.array([band(v, cfg) == "high" for v in rule])
    true_hi = np.array([band(v, cfg) == "high" for v in y])
    report["rule_high_precision"] = round(float((rule_hi & true_hi).sum() / max(1, rule_hi.sum())), 2)
    report["rule_high_recall"] = round(float((rule_hi & true_hi).sum() / max(1, true_hi.sum())), 2)
    report["rule_high_items"] = int(rule_hi.sum())
    report["rated_high_items"] = int(true_hi.sum())
    out["evaluation"] = report
    with open(a.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
        f.write("\n")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
