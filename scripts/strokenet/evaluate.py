"""Turn StrokeNet's reads into the preregistered results (docs/prereg/2026-10-14-strokenet.md).

  python scripts/strokenet/evaluate.py calibrate --runs RUNS
  python scripts/strokenet/evaluate.py results --runs RUNS --out results.json [--manifest M.json]
  python scripts/strokenet/evaluate.py release --runs RUNS --out strokenet-paris4-v1.npz

calibrate (run by pipeline.validate, before any test window is scored): from the validation read
only, every model's Platt scaling and blank threshold, every single-number baseline's direction
per measure, the reference baseline per measure, the checks that can void a measure, and the
gate. Written once to calibration.json; results never refits anything.
results: every measure for every reported model and baseline on the test split, with block
bootstrap intervals and per-segment values for the released model, the pass bar for every model
and baseline, the comparisons with the reference baselines, the ablation and seed readings, and
the verdict.
release: the released model's numpy weights with its Platt parameters, blank threshold and
validation reference values written into the metadata (what kit/strokenet.py reads).
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics as M  # noqa: E402

# AUC measures: (positive array, negative array). Arrays made from text windows share the text
# windows' segments and positions, those made from blank windows the blank ones, dense its own.
AUC = {
    "T1": ("text", "blank"), "T2": ("text", "iaaft_text"), "T2_20": ("text", "iaaft20_text"),
    "T2_plain": ("text", "phase_text"), "T3": ("tilejit_text", "shuffle_text"), "T3_raw": ("text", "shuffle_text"),
    "T4": ("text", "rot90_text"), "T6": ("blank", "rot90_blank"), "T7": ("stripjit_text", "strip_text"),
    "T7_raw": ("text", "strip_text"), "T8": ("text", "dense"), "C_iaaft": ("blank", "iaaft_blank"),
    "C_shuffle": ("tilejit_blank", "shuffle_blank"), "C_strip": ("stripjit_blank", "strip_blank"),
}
PAIRED = {"T2_paired": ("text", "iaaft_text"), "T3_paired": ("tilejit_text", "shuffle_text"),
          "T4_paired": ("text", "rot90_text"), "T7_paired": ("stripjit_text", "strip_text")}
PAIRED_OF = {"T2_paired": "T2", "T3_paired": "T3", "T4_paired": "T4", "T7_paired": "T7"}
# The fixed evaluation mixture for Platt scaling, ECE and Brier: total weight of each component.
MIXTURE = {"text": 0.5, "blank": 0.1, "dense": 0.1, "iaaft_text": 0.1, "shuffle_text": 0.1, "rot90_text": 0.1}
BAR = {"T1": (">=", 0.95), "T1_AP": (">=", 0.80), "T2": (">=", 0.90), "T3": (">=", 0.80), "T4": (">=", 0.80),
       "T4_paired": (">=", 0.80), "T6_dev": ("<=", 0.10), "ECE": ("<=", 0.05), "FPR_blank": ("<=", 0.02)}
CONTROL_VOIDS = ("T1", "T1_AP", "T2", "T3", "T4", "T4_paired")     # void if control_permuted reaches the bar
ARTIFACT_MEASURES = ("T2", "T2_20", "T3", "T3_raw", "T4", "T7", "T7_raw", "T8")   # every null measure and every primary one
ARTIFACT_LIMIT = 0.75
COMPARE = ("T1", "T2", "T2_20", "T3", "T3_raw", "T4", "T7", "T7_raw", "T8")
PRIMARY = ("T2", "T4", "T8")
ALPHA = 0.05 / len(PRIMARY)
FLOOR = 0.01
MIN_PER_SEGMENT = 10
GATE = {"T1": 0.90, "mean_T1_T4": 0.85}
CONTROL_T1_GATE = 0.95
NUMPY_TOL = 1e-3
BAND_PX = 512
BOOT_N = 2000
FITTED = ("spectrum", "nullspec", "texture", "randcnn")
SEED_RUNS = ("released", "seed1", "seed2")
ABLATIONS = ("abl_no_nulls", "abl_no_iaaft", "abl_no_shuffle", "abl_no_rot90")


# ------------------------------------------------------------------ reading the reads
def source(key):
    """Which windows an evaluation array was made from: text, blank or dense."""
    if key == "dense":
        return "dense"
    if key == "blank" or key.endswith("_blank"):
        return "blank"
    return "text"


def load_read(runs, split):
    z = np.load(Path(runs) / f"read_{split}.npz")
    meta = json.loads((Path(runs) / f"read_{split}.json").read_text())
    return {k: z[k] for k in z.files}, meta


def scores(arr, kind, name):
    """{eval key: scores} of one model ('cnn') or baseline ('base')."""
    pre = f"{kind}/{name}/"
    return {k[len(pre):]: np.asarray(v, np.float64) for k, v in arr.items() if k.startswith(pre)}


def names(arr, kind):
    return sorted({k.split("/")[1] for k in arr if k.startswith(kind + "/")})


def groups(arr):
    """Per source: segment index and block id (segment x 512 px column band) of every window."""
    out = {}
    for src in ("text", "blank", "dense"):
        if src + "_seg" in arr:
            seg = np.asarray(arr[src + "_seg"])
            out[src] = {"seg": seg, "block": M.blocks(seg, np.asarray(arr[src + "_pos"]), BAND_PX)}
    return out


def mixture(s):
    """Scores, labels and weights of the fixed mixture."""
    comps = [k for k in MIXTURE if k in s and len(s[k])]
    w = M.mixture_weights({k: len(s[k]) for k in comps}, {k: MIXTURE[k] for k in comps})
    x = np.concatenate([s[k] for k in comps])
    y = np.concatenate([np.full(len(s[k]), 1.0 if k == "text" else 0.0) for k in comps])
    wt = np.concatenate([np.full(len(s[k]), w[k]) for k in comps])
    return x, y, wt


def point_measures(s, sign=None):
    """Point estimates of every AUC and paired measure (sign: optional {measure: +1 or -1})."""
    sg = lambda m: (sign or {}).get(m, 1.0)
    out = {m: M.auc(sg(m) * s[p], sg(m) * s[n]) for m, (p, n) in AUC.items() if p in s and n in s}
    out.update({m: M.paired_frac(sg(m) * s[p], sg(m) * s[n]) for m, (p, n) in PAIRED.items() if p in s and n in s})
    out["T1_AP"] = M.ap_at(sg("T1") * s["text"], sg("T1") * s["blank"], 0.10, 20)
    if all(k in out for k in ("T1", "T2", "T3", "T4")):
        out["mean_T1_T4"] = float(np.mean([out["T1"], out["T2"], out["T3"], out["T4"]]))
    return out


# ------------------------------------------------------------------ calibration (validation only)
def calib(s):
    """Platt (a, b) on the fixed validation mixture, and the blank logit threshold."""
    x, y, w = mixture(s)
    a, b = M.platt_fit(x, y, w)
    return {"platt": [float(a), float(b)], "q99": float(np.quantile(s["blank"], 0.99, method="higher"))}


def directions(raw, fitted):
    """+1 or -1 per measure: fitted baselines always read higher = text; a single-number baseline
    takes the direction its validation AUC points to (artifact checks and T6 stay +1)."""
    d = {}
    for m in AUC:
        if m in raw:
            d[m] = 1.0 if (fitted or m.startswith("C_") or m == "T6" or raw[m] >= 0.5) else -1.0
    for m, base in PAIRED_OF.items():
        d[m] = d.get(base, 1.0)
    d["T1_AP"] = d.get("T1", 1.0)
    return d


def calibrate(runs):
    """calibration.json from the validation read: nothing here sees a test window."""
    runs = Path(runs)
    p = runs / "calibration.json"
    if p.exists():
        raise SystemExit("calibration.json exists: it is written once")
    val, vmeta = load_read(runs, "validation")
    out = {"mixture": MIXTURE, "models": {}, "baselines": {}, "reference": {}, "validity": {}}
    for lab in names(val, "cnn"):
        s = scores(val, "cnn", lab)
        out["models"][lab] = {**calib(s), "val": point_measures(s)}
    for b in names(val, "base"):
        s = scores(val, "base", b)
        direc = directions(point_measures(s), b in FITTED)
        cd = direc.get("T1", 1.0)                           # calibration items use the text-vs-blank direction
        out["baselines"][b] = {"directions": direc, "calibration_direction": cd,
                               **calib({k: cd * v for k, v in s.items()}), "val": point_measures(s, direc)}
    for m in COMPARE:
        cands = [(out["baselines"][b]["val"].get(m, float("nan")), b) for b in out["baselines"]]
        cands = [c for c in cands if c[0] == c[0]]
        if cands:
            v, b = max(cands)
            out["reference"][m] = {"baseline": b, "val": v}
    ctrl = out["models"].get("control_permuted", {}).get("val", {})
    out["validity"]["control_permuted"] = {m: {"value": ctrl.get(m), "bar": BAR[m][1],
                                               "void": bool(ctrl.get(m) is not None and ctrl[m] >= BAR[m][1])}
                                           for m in CONTROL_VOIDS}
    art = out["models"].get("control_artifact", {}).get("val", {})
    out["validity"]["control_artifact"] = {m: {"value": art.get(m), "limit": ARTIFACT_LIMIT,
                                               "not_interpretable": bool(art.get(m) is not None and art[m] >= ARTIFACT_LIMIT)}
                                           for m in ARTIFACT_MEASURES}
    nc = vmeta.get("numpy_check", {})
    out["validity"]["numpy_check"] = {**nc, "tolerance": NUMPY_TOL,
                                      "ok": bool(nc.get("max_abs_logit_diff", float("inf")) <= NUMPY_TOL)}
    rel = out["models"]["released"]["val"]
    checks = {"released_T1": {"value": rel["T1"], "min": GATE["T1"], "ok": bool(rel["T1"] >= GATE["T1"])},
              "released_mean_T1_T4": {"value": rel["mean_T1_T4"], "min": GATE["mean_T1_T4"],
                                      "ok": bool(rel["mean_T1_T4"] >= GATE["mean_T1_T4"])},
              "control_permuted_T1": {"value": ctrl.get("T1"), "below": CONTROL_T1_GATE,
                                      "ok": bool(ctrl.get("T1") is not None and ctrl["T1"] < CONTROL_T1_GATE)},
              "numpy_check": {"value": nc.get("max_abs_logit_diff"), "max": NUMPY_TOL,
                              "ok": out["validity"]["numpy_check"]["ok"]}}
    out["gate"] = {"ok": all(c["ok"] for c in checks.values()), "checks": checks}
    sv = scores(val, "cnn", "released")
    ref = lambda a, b: {"above": M.paired_frac(sv[a], sv[b]), "mean_drop": float(np.mean(sv[a] - sv[b]))}
    out["val_ref"] = {src: {"above_rot90": ref(src, f"rot90_{src}")["above"],
                            "above_iaaft": ref(src, f"iaaft_{src}")["above"],
                            "mean_drop_rot90": ref(src, f"rot90_{src}")["mean_drop"],
                            "mean_drop_iaaft": ref(src, f"iaaft_{src}")["mean_drop"]} for src in ("text", "blank")}
    out["validation_read_sha256"] = hashlib.sha256((runs / "read_validation.npz").read_bytes()).hexdigest()
    p.write_text(json.dumps(out, indent=1, default=float) + "\n")
    return out


# ------------------------------------------------------------------ test measures
def per_segment(fn, gp, gn, n_seg, min_n=MIN_PER_SEGMENT):
    """fn(pos index, neg index) per segment with at least min_n windows on each side, else None."""
    out = []
    for i in range(n_seg):
        ip, ineg = np.nonzero(gp == i)[0], np.nonzero(gn == i)[0]
        out.append(fn(ip, ineg) if len(ip) >= min_n and len(ineg) >= min_n else None)
    return out


def full_measures(s, G, n_seg, cal, sign=None, boot=True):
    """Every measure on one split: point, block-bootstrap interval (boot) and per-segment values."""
    sg = lambda m: (sign or {}).get(m, 1.0)
    out = {}
    for table, fn in ((AUC, M.auc), (PAIRED, M.paired_frac)):
        for m, (p, n) in table.items():
            if p not in s or n not in s:
                continue
            a, b = sg(m) * s[p], sg(m) * s[n]
            gp, gn = G[source(p)], G[source(n)]
            r = {"value": fn(a, b),
                 "per_segment": per_segment(lambda ip, ineg: fn(a[ip], b[ineg]), gp["seg"], gn["seg"], n_seg)}
            if boot:
                lo, hi, used = M.block_bootstrap(lambda t: fn(a[t["p"]], b[t["n"]]),
                                                 {"p": gp["block"], "n": gn["block"]}, n=BOOT_N, seed=0)
                r.update({"ci95": [lo, hi], "boot_used": used})
            out[m] = r
    st, sb = sg("T1") * s["text"], sg("T1") * s["blank"]
    out["T1_AP"] = {"value": M.ap_at(st, sb, 0.10, 20)}
    out["T6_dev"] = {"value": abs(out["T6"]["value"] - 0.5)}
    d = cal.get("calibration_direction", 1.0)
    a_, b_ = cal["platt"]
    sc = {k: d * v for k, v in s.items()}
    x, y, w = mixture(sc)
    pr = M.sigmoid(a_ * x + b_)
    out["ECE"] = {"value": M.ece(pr, y, w)}
    out["Brier"] = {"value": M.brier(pr, y, w)}
    out["reliability"] = M.reliability(pr, y, w)
    out["mixture_components"] = {k: {"n": int(len(sc[k])), "mean_p": float(np.mean(M.sigmoid(a_ * sc[k] + b_))),
                                     "label": 1.0 if k == "text" else 0.0} for k in MIXTURE if k in sc and len(sc[k])}
    t = cal["q99"]
    out["FPR_blank"] = {"value": float(np.mean(sc["blank"] > t)),
                        "per_segment": per_segment(lambda ip, ineg: float(np.mean(sc["blank"][ineg] > t)),
                                                   G["blank"]["seg"], G["blank"]["seg"], n_seg)}
    out["FPR_dense"] = {"value": float(np.mean(sc["dense"] > t)) if len(sc["dense"]) else None}
    out["TPR_text"] = {"value": float(np.mean(sc["text"] > t))}
    out["above_threshold"] = {k: float(np.mean(sc[k] > t)) for k in sc if len(sc[k])}
    if boot:                     # the same block bootstrap for every other measure of the released model
        srcs = [k for k in ("text", "blank", "dense") if k in G]
        blk = {k: G[k]["block"] for k in srcs}

        def sub(t, arrs):
            return {k: v[t[source(k)]] for k, v in arrs.items() if source(k) in t}

        def mix(t, fn):
            xx, yy, ww = mixture(sub(t, sc))
            return fn(M.sigmoid(a_ * xx + b_), yy, ww)

        items = {"T1_AP": lambda t: M.ap_at(st[t["text"]], sb[t["blank"]], 0.10, 20),
                 "T6_dev": lambda t: abs(M.auc(sg("T6") * s["blank"][t["blank"]], sg("T6") * s["rot90_blank"][t["blank"]]) - 0.5),
                 "ECE": lambda t: mix(t, M.ece), "Brier": lambda t: mix(t, M.brier),
                 "FPR_blank": lambda t: float(np.mean(sc["blank"][t["blank"]] > t_)),
                 "TPR_text": lambda t: float(np.mean(sc["text"][t["text"]] > t_))}
        if len(sc["dense"]):
            items["FPR_dense"] = lambda t: float(np.mean(sc["dense"][t["dense"]] > t_))
        t_ = t
        for i, (k, fn) in enumerate(items.items()):
            lo, hi, used = M.block_bootstrap(fn, blk, n=BOOT_N, seed=10 + i)
            out[k].update({"ci95": [lo, hi], "boot_used": used})
    return out


def bar(m):
    res = {}
    for k, (op, thr) in BAR.items():
        v = m[k]["value"]
        ok = v >= thr if op == ">=" else v <= thr
        res[k] = {"value": v, "bar": f"{op} {thr}", "pass": bool(ok)}
        if "ci95" in m[k]:
            res[k]["ci95"] = m[k]["ci95"]
    return res


def compare(cnn, base, G, n_seg, measure, sign):
    """StrokeNet minus the reference baseline on one AUC measure: pooled difference with its block
    bootstrap interval, per-segment differences, their mean, the exact sign-flip p and t interval."""
    p, n = AUC[measure]
    cp, cn, bp, bn = cnn[p], cnn[n], sign * base[p], sign * base[n]
    gp, gn = G[source(p)], G[source(n)]
    f = lambda ip, ineg: M.auc(cp[ip], cn[ineg]) - M.auc(bp[ip], bn[ineg])
    diff = M.auc(cp, cn) - M.auc(bp, bn)
    lo, hi, used = M.block_bootstrap(lambda t: f(t["p"], t["n"]), {"p": gp["block"], "n": gn["block"]}, n=BOOT_N, seed=1)
    per = per_segment(f, gp["seg"], gn["seg"], n_seg)
    d = np.array([v for v in per if v is not None])
    mean = float(d.mean()) if len(d) else float("nan")
    pval = float(M.sign_flip(d)) if len(d) else float("nan")
    adds = bool(len(d) and mean >= FLOOR and pval <= ALPHA)
    return {"difference": diff, "ci95": [lo, hi], "boot_used": used, "per_segment": per, "segments_used": int(len(d)),
            "mean_per_segment": mean, "k_positive": int((d > 0).sum()), "sign_flip_p": pval,
            "t_interval": [float(v) for v in M.t_interval(d)] if len(d) > 1 else None,
            "adds_over_simple_scores": adds, "role": "primary" if measure in PRIMARY else "descriptive"}


def results(runs, manifest=None, test_split="test"):
    runs = Path(runs)
    cal = json.loads((runs / "calibration.json").read_text())
    gate = json.loads((runs / "gate.json").read_text())
    cal_sha = hashlib.sha256((runs / "calibration.json").read_bytes()).hexdigest()
    if gate.get("calibration_sha256") != cal_sha:
        raise SystemExit("calibration.json differs from the one the gate recorded")
    test, tmeta = load_read(runs, test_split)
    ev = json.loads((runs / f"evalsets_{test_split}.json").read_text())
    n_seg = len(ev["segments"])
    G = groups(test)
    res = {"prereg": "docs/prereg/2026-10-14-strokenet.md", "test_segments": ev["segments"], "split": test_split,
           "n_test": ev["n"], "evalsets_sha256": ev["sha256"], "provenance": tmeta.get("provenance"),
           "calibration_sha256": cal_sha, "gate": gate, "choice": json.loads((runs / "choice.json").read_text()),
           "validity": cal["validity"], "reference": cal["reference"], "models": {}, "baselines": {}}
    for lab in names(test, "cnn"):
        res["models"][lab] = full_measures(scores(test, "cnn", lab), G, n_seg, cal["models"][lab], boot=lab == "released")
        res["models"][lab]["bar"] = bar(res["models"][lab])
        h = runs / tmeta["models"][lab]["run"] / "history.json"
        if h.exists():
            hj = json.loads(h.read_text())
            res["models"][lab]["training"] = {"run": tmeta["models"][lab]["run"], "best_final_gap": hj.get("best_final_gap"),
                                              "final_select": hj.get("final_select")}
    for b in names(test, "base"):
        cb = cal["baselines"][b]
        res["baselines"][b] = full_measures(scores(test, "base", b), G, n_seg, cb, sign=cb["directions"], boot=False)
        res["baselines"][b]["bar"] = bar(res["baselines"][b])
    rel = res["models"]["released"]
    cnn = scores(test, "cnn", "released")
    res["comparisons"] = {}
    for m in COMPARE:
        if m in cal["reference"]:
            b = cal["reference"][m]["baseline"]
            sgn = cal["baselines"][b]["directions"].get(m, 1.0)
            res["comparisons"][m] = {"reference": b, **compare(cnn, scores(test, "base", b), G, n_seg, m, sgn)}
    void = [m for m, r in cal["validity"]["control_permuted"].items() if r["void"]]
    uninterp = [m for m, r in cal["validity"]["control_artifact"].items() if r["not_interpretable"]]
    for m in uninterp:
        if m in res["comparisons"]:
            res["comparisons"][m]["adds_over_simple_scores"] = False
            res["comparisons"][m]["withheld"] = "the artifact control reached its limit on validation"
    for m in void:                       # reported, but not counted in the verdict
        if m in res["comparisons"]:
            res["comparisons"][m]["adds_over_simple_scores"] = False
            res["comparisons"][m]["void"] = "the permuted-label control reached the bar on validation"
    counted = [k for k in BAR if k not in void]
    art = res["models"].get("control_artifact", {})
    res["artifact_control_test"] = {m: art.get(m, {}).get("value") for m in ARTIFACT_MEASURES}
    failed = [k for k in counted if not rel["bar"][k]["pass"]]
    best_simple = {k: any(res["baselines"][b]["bar"][k]["pass"] for b in res["baselines"]) for k in counted}
    seeds_met = sum(all(res["models"][s]["bar"][k]["pass"] for k in counted) for s in SEED_RUNS if s in res["models"])
    adds = [m for m in PRIMARY if res["comparisons"].get(m, {}).get("adds_over_simple_scores")]
    adds_desc = [m for m in COMPARE if m not in PRIMARY and res["comparisons"].get(m, {}).get("adds_over_simple_scores")]
    head = "meets its preregistered bar" if not failed else "misses its bar on " + ", ".join(failed)
    n_simple = sum(best_simple.values())
    res["verdict"] = {
        "bar": head, "failed_items": failed, "void_measures": void, "not_interpretable_as_text_structure": uninterp,
        "simple_scores_meet": f"{n_simple} of {len(counted)} counted bar items (any baseline per item)",
        "counted_items": counted,
        "simple_scores_meet_items": [k for k, v in best_simple.items() if v],
        "seeds": f"bar met by {seeds_met} of {len(SEED_RUNS)} seeds",
        "adds_over_simple_scores_primary": adds, "adds_over_simple_scores_descriptive": adds_desc,
        "line": (f"StrokeNet {head}; simple scores meet {n_simple} of {len(counted)} counted bar items; "
                 f"bar met by {seeds_met} of {len(SEED_RUNS)} seeds; adds over simple scores on "
                 + (", ".join(adds) if adds else "none")
                 + " of the primary measures (" + ", ".join(PRIMARY) + ")"
                 + (f"; void: {', '.join(void)}" if void else "")
                 + (f"; not interpretable as text structure: {', '.join(uninterp)}" if uninterp else "")),
    }
    res["ablations"] = ablations(res)
    import prov as PV
    ap_ = PV.code_provenance()
    read_files = (res["provenance"] or {}).get("files", {})
    res["analysis_provenance"] = {**ap_, "matches_test_read": {f: ap_["files"].get(f) == read_files.get(f)
                                                               for f in ("scripts/strokenet/evaluate.py",
                                                                         "scripts/strokenet/metrics.py")}}
    if manifest:
        res["data_reproducibility"] = compare_manifest(runs, manifest)
    return res


def ablations(res):
    """Ablation readings: an effect is claimed only when the ablation's mean over seeds 0 to 2 lies
    outside the released configuration's seed range and the per-segment difference of seed means
    has the sign of that shift in at least 5 of the 6 test segments."""
    out = {}
    base = [res["models"][s] for s in SEED_RUNS if s in res["models"]]
    for ab in ABLATIONS:
        runs = [res["models"][f"{ab}_s{k}"] for k in (0, 1, 2) if f"{ab}_s{k}" in res["models"]]
        if not runs or not base:
            continue
        out[ab] = {}
        for m in ("T1", "T2", "T3", "T4", "T7", "T8"):
            bv = [r[m]["value"] for r in base]
            av = [r[m]["value"] for r in runs]
            diffs = []
            for i in range(len(base[0][m]["per_segment"])):
                a = [r[m]["per_segment"][i] for r in runs if r[m]["per_segment"][i] is not None]
                b = [r[m]["per_segment"][i] for r in base if r[m]["per_segment"][i] is not None]
                if a and b:
                    diffs.append(float(np.mean(a) - np.mean(b)))
            mean = float(np.mean(av))
            up, down = mean > max(bv), mean < min(bv)
            same = sum(d > 0 for d in diffs) if up else sum(d < 0 for d in diffs) if down else 0
            out[ab][m] = {"ablation_mean": mean, "ablation_seeds": av, "released_range": [min(bv), max(bv)],
                          "direction": "up" if up else "down" if down else None,
                          "segments_same_sign": same, "segments": len(diffs), "effect": bool((up or down) and same >= 5)}
    return out


def compare_manifest(runs, manifest):
    """Window-file SHA-256 of the run's own build (RUNS/data-manifest.json) against the committed one."""
    mine = Path(runs) / "data-manifest.json"
    if not mine.exists():
        return {"checked": False, "why": "no data-manifest.json from the run"}
    a = json.loads(Path(manifest).read_text())["segments"]
    b = json.loads(mine.read_text())["segments"]
    diff = sorted(s for s in a if a[s].get("crops_sha256") != b.get(s, {}).get("crops_sha256"))
    return {"checked": True, "segments": len(a), "differ": diff, "ok": not diff}


def release(runs, out, name="strokenet-paris4-v1"):
    runs = Path(runs)
    cal = json.loads((runs / "calibration.json").read_text())
    choice = json.loads((runs / "choice.json").read_text())
    z = np.load(runs / choice["chosen"] / "strokenet.npz")
    arrs = {k: z[k] for k in z.files}
    meta = json.loads(str(arrs["meta"]))
    rel = cal["models"]["released"]
    meta.update({"name": name, "platt": rel["platt"], "val_blank_logit_q99": rel["q99"], "val_ref": cal["val_ref"],
                 "platt_mixture": MIXTURE, "run": choice["chosen"], "prereg": "docs/prereg/2026-10-14-strokenet.md",
                 "trained_on": "organiser 2.4 um ink predictions of PHerc. Paris 4, July 2026 tracings, training split",
                 "note": "Model output: a text-likeness score for 6.1 mm windows of a 48 um ink map, not a reading."})
    arrs["meta"] = np.array(json.dumps(meta))
    np.savez(out, **arrs)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=["calibrate", "results", "release"])
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--test-split", default="test", help="smoke runs only: smoke_test")
    a = ap.parse_args(argv)
    if a.action == "calibrate":
        print(json.dumps(calibrate(a.runs)["gate"], indent=1, default=float))
    elif a.action == "results":
        r = results(a.runs, a.manifest, a.test_split)
        Path(a.out).write_text(json.dumps(r, indent=1, default=float) + "\n")
        print(r["verdict"]["line"])
    else:
        print(json.dumps(release(a.runs, a.out), indent=1))


if __name__ == "__main__":
    main()
