"""Recompute the published aggregates from saved scalar window scores.

This does not download data, produce maps, or rerun the pixel AUC calculation.
"""
import json
from collections import defaultdict
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent


def summarize(draws=2000, seed=0):
    rows = json.loads((HERE / "window-scores.json").read_text())
    t = defaultdict(lambda: defaultdict(list))
    for r in rows:
        sample, seg = r["window"].split("__")[:2]
        for k, a in r["auc"].items():
            t[sample][seg].append((k, a))
    methods = sorted({k for r in rows for k in r["auc"]})
    per = {s: {m: float(np.mean([np.mean([a for k, a in v if k == m]) for v in segs.values()])) for m in methods}
           for s, segs in t.items()}
    rng = np.random.default_rng(seed)
    out = {"windows": len(rows), "per_scroll": per, "mean": {m: float(np.mean([per[s][m] for s in per])) for m in methods},
           "paired": {}}
    for m in methods:
        if m == "filter":
            continue
        diffs = []
        for _ in range(draws):
            vals = []
            for s, segs in t.items():
                keys = list(segs)
                pick = rng.choice(len(keys), len(keys))
                vals.append(np.mean([np.mean([a for k, a in segs[keys[i]] if k == "filter"]) -
                                     np.mean([a for k, a in segs[keys[i]] if k == m]) for i in pick]))
            diffs.append(np.mean(vals))
        out["paired"][m] = {"mean_diff": float(out["mean"]["filter"] - out["mean"][m]),
                            "ci95": [float(x) for x in np.percentile(diffs, [2.5, 97.5])],
                            "scrolls_won": int(sum(per[s]["filter"] > per[s][m] for s in per))}
    return out


if __name__ == "__main__":
    result = summarize()
    expected = json.loads((HERE / "confirmation-summary.json").read_text())
    def check(a, b):
        if isinstance(a, dict):
            assert a.keys() == b.keys()
            for k in a:
                check(a[k], b[k])
        elif isinstance(a, list):
            assert len(a) == len(b)
            for x, y in zip(a, b):
                check(x, y)
        else:
            assert abs(a - b) < 1e-12, (a, b)
    check(result, expected)
    print(json.dumps(result, indent=2))
    print("AGGREGATE CHECK PASS: 56 saved window scores; no map rerun")
