"""Lane F E2 (two-reader disagreement filter), E3 (depth-profile shape transfer w045 -> w00),
E4 (self-training on w00 pseudo-labels), plus E1 scoring. Rules: docs/logs/2026-10-07-grok-laneF.md.

Usage: python e234.py REPO_ROOT WORK_DIR OUT_JSON
"""
import json, sys
import numpy as np
from scipy import ndimage as ndi
from scipy.stats import rankdata
from sklearn.linear_model import LogisticRegression
from sklearn.cluster import KMeans
sys.path.insert(0, sys.argv[1])
from kit.layers import open_volume, depth_permutation
from kit.auc import labels_on_map, score_array, block_bootstrap, _load

W, OUT = sys.argv[2], sys.argv[3]
SEED, INNER, PAD = 20261007, 64, 8
SEG = {"w045": dict(zarr="w045_9um.zarr", lab="w045_labels", crop=(3840, 4480, 2560, 3200)),
       "w00": dict(zarr="0841-w00_9um.zarr", lab="0841-w00_labels", crop=(2624, 3264, 2688, 3328))}


def norm(m):
    m = m.astype(np.float64); lo, hi = np.percentile(m, [0.5, 99.5])
    return np.clip((m - lo) / (hi - lo + 1e-12), 1e-6, 1.0)


def rank(a):
    """Preserve equal predictions; pixel order must not break score ties."""
    return (rankdata(a, method="average") / a.size).reshape(a.shape)


def auc(m, ink, sup):
    return score_array(norm(m), ink, sup, inner=INNER)["auc"]


def compare(m, base, ink, sup):
    b = block_bootstrap(norm(m), ink, sup, draws=300, seed=0, other=norm(base), inner=INNER)
    c = b["compare"]
    return {"auc": c["auc_map"], "auc_base": c["auc_other"], "gain": c["difference"], "gain_ci95": c["ci95"],
            "auc_ci95": b["ci95"], "passes": bool(c["difference"] >= 0.01 and c["ci95"][0] > 0)}


D = {}
for n, s in SEG.items():
    vol = open_volume(f"{W}/data/{s['zarr']}"); surf = vol.shape[1:]; y0, y1, x0, x1 = s["crop"]
    v = np.asarray(vol[:, y0 - PAD:y1 + PAD, x0 - PAD:x1 + PAD]).astype(np.float32)
    ink, sup = labels_on_map(f"{W}/data/{s['lab']}/inklabels.zarr", f"{W}/data/{s['lab']}/supervision.zarr",
                             "2", surf, s["crop"], (y1 - y0, x1 - x0))
    D[n] = dict(v=v, ink=ink, sup=sup)
D["w00"]["s42"] = _load(f"{W}/0841-w00/maps/ink9um_s42.tif")[2624:3264, 2688:3328].astype(np.float64)
D["w00"]["v8in"] = np.load(f"{W}/0841-w00/maps/crop_gpu.npy").astype(np.float64)
D["w045"]["s42"] = _load(f"{W}/w045/maps/ink9um_s42.tif")[3840:4480, 2560:3200].astype(np.float64)
D["w045"]["v8in"] = np.load(f"{W}/w045/maps/v8in.npy").astype(np.float64)
res = {"seed": SEED, "inner": INNER, "rank_method": "average_ties_v2",
       "E3_control_method": "fixed_real_classifier_permuted_test_depth_v2"}

# ---- E1 scoring
e1 = {}
for s in (42, 43):
    base = _load(f"{W}/0841-w00/maps/ink9um_quick_s{s}.tif").astype(np.float64)
    e1[f"s{s}_baseline_auc"] = auc(base, D["w00"]["ink"], D["w00"]["sup"])
    for z in ("w00_matched_self", "w00_matched_w045", "w00_matched_perlayer"):
        m = _load(f"{W}/laneF/maps/{z}_s{s}.tif").astype(np.float64)
        e1[f"s{s}_{z}"] = compare(m, base, D["w00"]["ink"], D["w00"]["sup"])
        e1[f"s{s}_{z}"]["max_abs_diff_vs_baseline"] = float(np.abs(m - base).max())
e1["self_control_ok"] = all(abs(e1[f"s{s}_w00_matched_self"]["gain"]) <= 0.003 for s in (42, 43))
e1["positive"] = e1["self_control_ok"] and all(e1[f"s{s}_w00_matched_w045"]["passes"] for s in (42, 43))
res["E1"] = e1; print("E1", json.dumps(e1), flush=True)

# ---- E2
e2 = {}
for n in ("w00", "w045"):
    d = D[n]; ra, rb = rank(d["s42"]), rank(d["v8in"])
    rbr = rank(np.roll(d["v8in"], (211, 307), (0, 1)))
    e2[n] = {"pearson_s42_v8in": float(np.corrcoef(d["s42"].ravel(), d["v8in"].ravel())[0, 1]),
             "v8in_auc": auc(d["v8in"], d["ink"], d["sup"]),
             "filter": compare(ra - 0.5 * np.abs(ra - rb), ra, d["ink"], d["sup"]),
             "mean_ensemble": compare((ra + rb) / 2, ra, d["ink"], d["sup"]),
             "filter_vs_mean": compare(ra - 0.5 * np.abs(ra - rb), (ra + rb) / 2, d["ink"], d["sup"]),
             "control_rolled_v8in": compare(ra - 0.5 * np.abs(ra - rbr), ra, d["ink"], d["sup"])}
w = e2["w00"]
e2["positive"] = w["filter"]["passes"] and not w["control_rolled_v8in"]["passes"]
e2["filter_specific"] = e2["positive"] and w["filter_vs_mean"]["gain"] >= 0.005
res["E2"] = e2; print("E2", json.dumps(e2), flush=True)


# ---- E3
def profiles(v, shape_only=True, sizes=(5,)):
    feats = []
    for k in sizes:
        p = ndi.uniform_filter(v, (1, k, k))[:, PAD:-PAD, PAD:-PAD]      # (L, H, W)
        p = p.reshape(p.shape[0], -1).T                                   # (H*W, L)
        if shape_only:
            p = (p - p.mean(1, keepdims=True)) / (p.std(1, keepdims=True) + 1e-6)
        feats.append(p)
    return np.concatenate(feats, 1)


def fit_apply(train_v, test_v, d_train, shape_only=True, sizes=(5,), labels=None, mask=None, seed=SEED):
    Xtr, Xte = profiles(train_v, shape_only, sizes), profiles(test_v, shape_only, sizes)
    if not shape_only:
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6; Xtr, Xte = (Xtr - mu) / sd, (Xte - mu) / sd
    y = (d_train["ink"] if labels is None else labels).ravel()
    m = (d_train["sup"] if mask is None else mask).ravel()
    idx = np.flatnonzero(m); rng = np.random.default_rng(seed)
    idx = rng.choice(idx, min(50000, idx.size), replace=False)
    clf = LogisticRegression(max_iter=2000, C=1.0).fit(Xtr[idx], y[idx])
    return clf.decision_function(Xte).reshape(640, 640), clf


def shuffled_test_score(clf, test_v, permutation):
    """Disrupt test depth order while keeping the real-trained reader fixed.

    Refitting with the same permutation of train and test merely renames
    logistic-regression features and cannot be a wrong-depth control.
    """
    shape = (test_v.shape[1] - 2 * PAD, test_v.shape[2] - 2 * PAD)
    return clf.decision_function(profiles(test_v[permutation])).reshape(shape)


a, b = D["w045"], D["w00"]
perm = depth_permutation(a["v"].shape[0], SEED)
m_real, clf = fit_apply(a["v"], b["v"], a)
m_shuf = shuffled_test_score(clf, b["v"], perm)
m_rev = shuffled_test_score(clf, b["v"], np.arange(b["v"].shape[0] - 1, -1, -1))
rng = np.random.default_rng(SEED)
nulls = [auc(np.roll(m_real, (int(p), int(q)), (0, 1)), b["ink"], b["sup"]) for p, q in rng.integers(120, 520, (8, 2))]
self_w045 = auc(fit_apply(a["v"], a["v"], a)[0], a["ink"], a["sup"])
e3 = {"w00_auc": auc(m_real, b["ink"], b["sup"]), "w00_auc_depth_shuffled": auc(m_shuf, b["ink"], b["sup"]),
      "w00_auc_reversed_input": auc(m_rev, b["ink"], b["sup"]), "rolled_null_min": min(nulls),
      "rolled_null_max": max(nulls), "w045_train_auc": self_w045, "coef": [round(float(c), 3) for c in clf.coef_[0]],
      "bootstrap": block_bootstrap(norm(m_real), b["ink"], b["sup"], draws=300, seed=0, inner=INNER)}
e3["positive"] = bool(e3["w00_auc"] >= 0.55 and e3["w00_auc"] > max(nulls)
                      and e3["w00_auc"] - e3["w00_auc_depth_shuffled"] >= 0.02)
# descriptive: unsupervised k-means of w00 profile shapes
P = profiles(b["v"]); km = KMeans(6, n_init=4, random_state=0).fit(P[::7])
lab = km.predict(P).reshape(640, 640); inner = np.zeros_like(b["sup"]); inner[INNER:-INNER, INNER:-INNER] = True
use = b["sup"] & inner
e3["kmeans_w00"] = [{"cluster": c, "share": round(float((lab[use] == c).mean()), 4),
                     "ink_rate": round(float(b["ink"][use][lab[use] == c].mean()), 4)} for c in range(6)]
e3["kmeans_w00_base_ink_rate"] = round(float(b["ink"][use].mean()), 4)
res["E3"] = e3; print("E3", json.dumps({k: v for k, v in e3.items() if k != "coef"}), flush=True)

# ---- E4
t = b["s42"]; left = np.zeros((640, 640), bool); left[:, :320] = True
q90, q40 = np.quantile(t[left], [0.9, 0.4])
pl = (t >= q90); pm = left & ((t >= q90) | (t <= q40))
right_sup = b["sup"].copy(); right_sup[:, :320] = False
stud, _ = fit_apply(b["v"], b["v"], b, shape_only=False, sizes=(5, 15), labels=pl, mask=pm)
pl_r = np.roll(pl, (0, 160), (0, 1)); pm_r = left & np.roll((t >= q90) | (t <= q40), (0, 160), (0, 1))
stud_c, _ = fit_apply(b["v"], b["v"], b, shape_only=False, sizes=(5, 15), labels=pl_r, mask=pm_r)
rt = rank(t)
e4 = {"pseudo_ink_px": int((pl & pm).sum()), "pseudo_bg_px": int((pm & ~pl).sum()),
      "teacher_right_auc": auc(t, b["ink"], right_sup), "student_right_auc": auc(stud, b["ink"], right_sup),
      "fusion": compare(0.5 * rank(stud) + 0.5 * rt, rt, b["ink"], right_sup),
      "control_rolled_pseudo": compare(0.5 * rank(stud_c) + 0.5 * rt, rt, b["ink"], right_sup),
      "control_student_right_auc": auc(stud_c, b["ink"], right_sup)}
e4["positive"] = e4["fusion"]["passes"] and not e4["control_rolled_pseudo"]["passes"]
e4["inconclusive"] = e4["fusion"]["passes"] and e4["control_rolled_pseudo"]["passes"]
res["E4"] = e4; print("E4", json.dumps(e4), flush=True)
json.dump(res, open(OUT, "w"), indent=1)
