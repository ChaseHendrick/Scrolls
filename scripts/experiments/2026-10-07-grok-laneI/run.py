"""Lane I: crop placement sensitivity, downsampled proxy, crop scan speed (rule: docs/prereg/2026-10-07-grok-laneI.md).

Usage: python run.py DATA_DIR OUT_JSON   (DATA_DIR holds 0841-w00_labels, 0841-w00_9um.zarr, inkdet/w00/*.tif)
"""
import os
import sys

if os.environ.get("SCROLLS_REPLAY_HISTORICAL_LANEI") != "1":
    raise SystemExit("Archival run only: R1/R2 used nonfinite bootstrap intervals. "
                     "New validated runs require corrected interval handling and input provenance. "
                     "For a deliberate unvalidated replay, set SCROLLS_REPLAY_HISTORICAL_LANEI=1.")
print("WARNING: historical unvalidated replay; do not report R1/R2 as validated evidence.",
      file=sys.stderr)
import glob, json, sys, time
import numpy as np, tifffile, zarr
from scipy.stats import rankdata, spearmanr
from kit.auc import label_grid, score_array, block_bootstrap
from kit.cropscan import scan

D, OUT = sys.argv[1], sys.argv[2]
WIN, STRIDE, INNER = 640, 320, 64
REPO = (2624, 3264, 2688, 3328)
T = {}
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
t0 = time.time()
import os
CACHE = os.environ.get("LANEI_CACHE")
if CACHE and os.path.exists(f"{CACHE}/maps.npz"):
    z = np.load(f"{CACHE}/maps.npz"); maps = {k: z[k] for k in z.files if k not in ("ink", "mask")}; ink, mask = z["ink"], z["mask"]
    S = ink.shape; lab = zarr.open(f"{D}/0841-w00_labels/inklabels.zarr", mode="r")["2"]; f = glob.glob(f"{D}/inkdet/w00/*.tif")[0]
else:
  lab = zarr.open(f"{D}/0841-w00_labels/inklabels.zarr", mode="r")["2"][:]
  sup = zarr.open(f"{D}/0841-w00_labels/supervision.zarr", mode="r")["2"][:]
  vol = zarr.open(f"{D}/0841-w00_9um.zarr/0", mode="r")
  S = vol.shape[1:]
  r, c = label_grid(lab.shape, S, None, S)
  ink = lab[np.ix_(r, c)] > 0; mask = sup[np.ix_(r, c)] > 0
  f = glob.glob(f"{D}/inkdet/w00/*.tif")[0]
  t = tifffile.imread(f)
  h, w = t.shape[0] // 4 * 4, t.shape[1] // 4 * 4
  team = t[:h, :w].reshape(h // 4, 4, w // 4, 4).mean((1, 3), dtype=np.float32)
  del t
  team = team[np.ix_(np.minimum(r, team.shape[0] - 1), np.minimum(c, team.shape[1] - 1))]
  v = vol[:]
  maps = {"TEAM": team / 255.0}
  for i, (a, b) in enumerate([(0, 7), (7, 14), (14, 21), (21, 28)]):
      maps[f"B{i+1}"] = v[a:b].mean(0, dtype=np.float32) / 255.0
  del v
  nz = maps["B1"] > 0
  def avg_rank(m):
      out = np.zeros(m.shape, np.float32); out[nz] = (rankdata(m[nz]) - 0.5) / nz.sum(); return out
  maps["BAVG"] = np.mean([avg_rank(maps[f"B{i}"]) for i in range(1, 5)], 0).astype(np.float32)
  for k in maps: maps[k] = np.clip(maps[k], 1e-6, 1).astype(np.float32) * (nz | (k == "TEAM"))
  if CACHE: os.makedirs(CACHE, exist_ok=True); np.savez(f"{CACHE}/maps.npz", ink=ink, mask=mask, **maps)
T["load_s"] = round(time.time() - t0, 1)
res = {"surface_shape": S, "labels_shape": lab.shape, "team_file": f.split("/")[-1], "timing": T}

log("T1")
# T1: scan vs loop
t0 = time.time(); scans = {k: scan(m, ink, mask, WIN, STRIDE, INNER) for k, m in maps.items()}; T["scan_all_readers_s"] = round(time.time() - t0, 2)
crops = [s["crop"] for s in scans["TEAM"]]
valid = [i for i, s in enumerate(scans["TEAM"]) if all(scans[k][i]["auc"] is not None for k in maps)]
def crop_auc(m, cr, im=ink, mk=mask, inner=INNER):
    y0, y1, x0, x1 = cr
    return score_array(m[y0:y1, x0:x1], im[y0:y1, x0:x1], mk[y0:y1, x0:x1], inner=inner)["auc"]
t0 = time.time(); loop = {k: [crop_auc(m, crops[i]) for i in valid] for k, m in maps.items()}; T["loop_all_readers_s"] = round(time.time() - t0, 2)
err = max(abs(loop[k][j] - scans[k][i]["auc"]) for k in maps for j, i in enumerate(valid))
res["T1"] = {"crops_total": len(crops), "crops_valid": len(valid), "max_abs_diff": err, "pass": err <= 1e-4,
             "speedup": round(T["loop_all_readers_s"] / T["scan_all_readers_s"], 1)}
A = {k: np.array(loop[k]) for k in maps}   # exact AUCs, used below

log("full region")
# full region and R3
res["full"] = {}
for k, m in maps.items():
    bb = block_bootstrap(m, ink, mask, seed=0)
    res["full"][k] = {"auc": score_array(m, ink, mask)["auc"], "ci95": bb["ci95"]}
res["R3"] = res["full"]["TEAM"]

log("bootstrap per crop")
# bootstrap per crop
t0 = time.time()
def sl(a, cr): y0, y1, x0, x1 = cr; return a[y0:y1, x0:x1]
CI = {k: [] for k in maps}
for i in valid:
    cr = crops[i]
    for k, m in maps.items():
        CI[k].append(block_bootstrap(sl(m, cr), sl(ink, cr), sl(mask, cr), inner=INNER, seed=0)["ci95"])
repo_ci = {}
for k, m in maps.items():
    repo_ci[k] = {"auc": crop_auc(m, REPO), **block_bootstrap(sl(m, REPO), sl(ink, REPO), sl(mask, REPO), inner=INNER, seed=0)}
R1 = {}
for k in maps:
    a = A[k]; lo, hi = repo_ci[k]["ci95"]
    cov_repo = float(((a >= lo) & (a <= hi)).mean())
    covs = [float(np.mean([(lo2 <= a[j] <= hi2) for j in range(len(a)) if j != n])) for n, (lo2, hi2) in enumerate(CI[k])]
    hw = [(h2 - l2) / 2 for l2, h2 in CI[k]]
    R1[k] = {"repo_crop": repo_ci[k], "repo_ci_coverage_of_crops": round(cov_repo, 3), "mean_coverage": round(float(np.mean(covs)), 3),
             "between_crop_sd": round(float(a.std(ddof=1)), 4), "median_boot_sd": round(float(np.median(hw) / 1.96), 4),
             "auc_min": float(a.min()), "auc_max": float(a.max()), "repo_percentile": round(float((a < repo_ci[k]["auc"]).mean()), 3)}
R1["problem_declared"] = R1["TEAM"]["mean_coverage"] < 0.8 or R1["BAVG"]["mean_coverage"] < 0.8
res["R1"] = R1

log("R2")
# R2
B = ["B1", "B2", "B3", "B4", "BAVG"]
pairs = [(B[i], B[j]) for i in range(5) for j in range(i + 1, 5)] + [("TEAM", "BAVG")]
R2 = {"pairs": {}}
tot_sig = tot_dis = 0
for p, q in pairs:
    fb = block_bootstrap(maps[p], ink, mask, seed=0, other=maps[q])["compare"]
    fsig = not (fb["ci95"][0] <= 0 <= fb["ci95"][1])
    sig = dis = 0
    for i in valid:
        cr = crops[i]
        cb = block_bootstrap(sl(maps[p], cr), sl(ink, cr), sl(mask, cr), inner=INNER, seed=0, other=sl(maps[q], cr))["compare"]
        if not (cb["ci95"][0] <= 0 <= cb["ci95"][1]):
            sig += 1; dis += int(np.sign(cb["difference"]) != np.sign(fb["difference"]))
    R2["pairs"][f"{p}-{q}"] = {"full_diff": fb["difference"], "full_ci95": fb["ci95"], "full_significant": fsig,
                               "crop_significant": sig, "crop_significant_disagree": dis}
    if fsig: tot_sig += sig; tot_dis += dis
R2["significant_crop_orderings"] = tot_sig; R2["disagree"] = tot_dis
R2["disagree_share"] = round(tot_dis / tot_sig, 3) if tot_sig else None
R2["problem_declared"] = bool(tot_sig and tot_dis / tot_sig >= 0.2)
fullbest = max(["B1", "B2", "B3", "B4"], key=lambda k: res["full"][k]["auc"])
best = [max(["B1", "B2", "B3", "B4"], key=lambda k: A[k][j]) for j in range(len(valid))]
R2["full_best_window"] = fullbest; R2["crop_best_window_counts"] = {k: best.count(k) for k in ["B1", "B2", "B3", "B4"]}
R2["share_crops_best_equals_full"] = round(best.count(fullbest) / len(best), 3)
R2["share_crops_BAVG_beats_all_windows"] = round(float(np.mean([A["BAVG"][j] > max(A[k][j] for k in B[:4]) for j in range(len(valid))])), 3)
res["R2"] = R2
T["bootstrap_s"] = round(time.time() - t0, 1)

log("P1")
# P1 proxy
def pool(a, s, kind):
    H, W = a.shape[0] // s * s, a.shape[1] // s * s
    x = a[:H, :W].reshape(H // s, s, W // s, s)
    return x.mean((1, 3)) if kind == "mean" else (x.all((1, 3)) if kind == "all" else x.mean((1, 3)) >= 0.5)
P1 = {}
for s in (2, 4):
    t0 = time.time()
    pi, pm = pool(ink, s, "half"), pool(mask, s, "all")
    pa = {}
    for k, m in maps.items():
        pm_k = pool(m, s, "mean").astype(np.float32)
        pa[k] = np.array([crop_auc(pm_k, [x // s for x in crops[i]], pi, pm, INNER // s) for i in valid], float)
    tp = time.time() - t0
    ok = True; rep = {}
    for k in maps:
        good = ~np.isnan(pa[k])
        rho = spearmanr(pa[k][good], A[k][good]).statistic; mae = float(np.nanmax(np.abs(pa[k] - A[k])))
        rep[k] = {"spearman": round(float(rho), 4), "max_abs_err": round(mae, 4)}
        ok &= rho >= 0.95 and mae <= 0.02
    agree = n = 0
    for p, q in pairs:
        for j in range(len(valid)):
            d = A[p][j] - A[q][j]
            if abs(d) >= 0.01:
                n += 1; agree += int(np.sign(d) == np.sign(pa[p][j] - pa[q][j]))
    rep["order_agreement"] = round(agree / n, 4) if n else None
    rep["pass"] = bool(ok and n and agree / n >= 0.95)
    rep["proxy_s"] = round(tp, 2)
    P1[f"x{s}"] = rep
res["P1"] = P1
res["T1"]["loop_full_res_s"] = T["loop_all_readers_s"]
res["per_crop"] = [{"crop": crops[i], **{k: float(A[k][j]) for k in maps}} for j, i in enumerate(valid)]
json.dump(res, open(OUT, "w"), indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
print(json.dumps({k: v for k, v in res.items() if k != "per_crop"}, indent=1, default=str))
