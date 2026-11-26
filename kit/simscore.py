"""Reference scorer of the Sim Realism Standard, version 1 (SRS-1): one fixed way to rate any simulated scroll CT.

The standard is written in docs/standards/sim-realism.md. This module is its reference implementation: it fixes every
setting of kit.simcritic (window, critics, folds, seeds, steps, the pass rule), runs the gates in order and writes one
JSON record that anyone can check without rerunning the critics.

Order of a scoring (each step can fail, and a failed gate makes the record VOID, never PASS):
1. Sizes: at least MIN_GROUPS real slices and MIN_SIM_TILES simulated tiles (the first ones, in the order given).
2. Planted checks on the real windows alone: two random halves (must stay under PLANTED_SAME_MAX), one half with
   noise and one half blurred (each must reach PLANTED_SHIFT_MIN). A judge that cannot fail or pass known cases says
   nothing about a simulator.
3. Control: the same critics on even against odd real slices. Its worst AUC must stay under CONTROL_MAX.
4. Set: the odd real slices against the simulated windows. A generator may have been fitted to the even slices
   (the "fit half"), never to the odd ones; the scorer refuses odd groups listed as trained on.
5. Verdict: kit.simcritic.verdict (PASS when the worst critic's AUC is at most the control's worst plus 0.05 and at
   most 0.60), then the sample-size rule of the 26 Nov 2026 null calibration (ADMIT_GROUPS, D99): on a reference with
   fewer groups than ADMIT_GROUPS a FAIL counts only beyond D99 and a PASS is INCONCLUSIVE.

The record names the standard, the scorer's file digests, the settings, the reference and the set (window digests),
the generator and how many sets its authors scored before this one (`attempts`, count every attempt). `check`
recomputes the gates, the verdict and the status from the numbers in a record and fails on any mismatch.

A PASS means no SRS-1 critic separated the set from that reference: Model output, not proof that the set is real.
Gray values only; no labels are scored. The R343 reference reads public PHerc0343P CT and uses the organizers'
public surface labels only to set the gray-value normalization.
"""
import argparse
import hashlib
import json
import os
import sys
import time

STANDARD = "SRS-1"
WIN = 128
MIN_COVER = 0.98
CRITICS = ("feat", "cnn", "cnn_half")
FOLDS = 3
SEEDS = (0, 1)
STEPS = 800
MARGIN = 0.05
CEILING = 0.60
PLANTED_SAME_MAX = 0.65
PLANTED_SHIFT_MIN = 0.90
CONTROL_MAX = 0.65
MIN_GROUPS = 6
MIN_SIM_TILES = 240
MIN_TILE = 256
SETTINGS = {"win": WIN, "min_cover": MIN_COVER, "critics": list(CRITICS), "folds": FOLDS, "seeds": list(SEEDS),
            "steps": STEPS, "margin": MARGIN, "ceiling": CEILING, "planted_same_max": PLANTED_SAME_MAX,
            "planted_shift_min": PLANTED_SHIFT_MIN, "control_max": CONTROL_MAX, "min_groups": MIN_GROUPS,
            "min_sim_tiles": MIN_SIM_TILES, "min_tile": MIN_TILE}

# Sample-size rule, from the null calibration preregistered in docs/prereg/2026-11-26-srs1-null-calibration.md
# (evidence docs/evidence/srs1-calibration-1126/). ADMIT_GROUPS: the smallest admitted reference size (None: none
# admitted). D99: the 99th percentile of gap_to_bar for a perfect simulator, by reference group count.
# Result (26 Nov 2026): no size admitted (false FAIL 0.595, 0.485 and 0.285 at 6, 12 and 24 groups), so under SRS-1
# a PASS is never a verdict and a FAIL counts only beyond D99.
ADMIT_GROUPS = None
D99 = {6: 0.2454, 12: 0.2045, 24: 0.0788}

# R343-v1: six axial slices of PHerc0343P (a public fragment scan on no prize list), level 2 of the 2.215 um scan
# (8.86 um), resampled to 9.362 um, as judged on 25 Nov 2026.
R343 = {
    "id": "R343-v1",
    "ct": "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343P/volumes/"
          "20260304131111-2.215um-0.4m-111keV-masked.zarr/2",
    "labels": "https://huggingface.co/buckets/scrollprize/datasets/resolve/surfaces/2um_032726/"
              "2.215um_0.4m_111keV_PHerc0343P_surface.zarr/2",
    "zs": (1460, 1500, 1540, 1580, 1620, 1660),
    "box": (1006, 1663, 1148, 2605),  # y0, y1, x0, x1 in level-2 voxels
    "src_um": 8.86,
    "target_um": 9.362,
    "floor": -0.43,  # cover: resampled CT above this (the masked volume's zeros map to about -0.44)
}


class ScoreError(ValueError):
    pass


def _np():
    import numpy as np
    return np


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def scorer_digests():
    """SHA-256 of the scorer's own files, so a record says exactly which code made it."""
    here = os.path.dirname(os.path.abspath(__file__))
    return {name: file_sha256(os.path.join(here, name)) for name in ("simcritic.py", "simscore.py")}


# ---------------------------------------------------------------- inputs

def reference_r343(progress=print):
    """The R343-v1 reference: {"ct": [2D float32], "cover": [2D bool], "name": [...], "id"}. Reads public CT and
    labels over HTTP with kit.sentinel's zarr reader (14 s in a 4-core cloud container, 26 Nov 2026)."""
    np = _np()
    from scipy import ndimage as nd
    from kit import sentinel
    y0, y1, x0, x1 = R343["box"]
    zc = sentinel.Store(R343["ct"]).level(0)
    zl = sentinel.Store(R343["labels"]).level(0)
    if zc.shape != zl.shape:
        raise ScoreError(f"CT {zc.shape} and labels {zl.shape} differ")
    raw = []
    for z in R343["zs"]:
        ct = zc.read(z, z + 1, y0, y1, x0, x1)[0].astype(np.float32)
        lab = zl.read(z, z + 1, y0, y1, x0, x1)[0]
        raw.append((z, ct, lab))
        progress(f"  read z {z}")
    allv = np.concatenate([ct[lab != 2][::3] for _, ct, lab in raw])
    lo, hi = np.percentile(allv, [0.5, 99.5])
    s = R343["src_um"] / R343["target_um"]
    out = {"id": R343["id"], "ct": [], "cover": [], "name": [], "lo_hi": [float(lo), float(hi)]}
    for z, ct, _ in raw:
        r = np.clip(nd.zoom((ct - lo) / (hi - lo), s, order=1), -0.5, 1.5).astype(np.float32)
        out["ct"].append(r)
        out["cover"].append(r > R343["floor"])
        out["name"].append(f"z{z}")
    return out


def save_reference(ref, path):
    np = _np()
    np.savez_compressed(path, ct=np.stack(ref["ct"]), cover=np.stack(ref["cover"]), name=np.array(ref["name"]),
                        id=np.array(ref.get("id", "custom")))


def load_reference(path):
    """A reference npz: `ct` (N, H, W) or an object array of 2D slices, optional `cover` (same shapes, bool),
    optional `name` and `id`. Slices are kept in file order; even and odd mean their index in that order."""
    np = _np()
    t = np.load(path, allow_pickle=True)
    ct = [np.asarray(c, np.float32) for c in t["ct"]]
    cover = [np.asarray(c, bool) for c in t["cover"]] if "cover" in t.files else None
    name = [str(n) for n in t["name"]] if "name" in t.files else [f"s{i}" for i in range(len(ct))]
    rid = str(t["id"]) if "id" in t.files else "custom"
    return {"id": rid, "ct": ct, "cover": cover, "name": name}


def load_sim(path, key="image", n=MIN_SIM_TILES):
    """The first N tiles under KEY of a simulated set's npz, in file order (no picking)."""
    np = _np()
    t = np.load(path, allow_pickle=True)
    if key not in t.files:
        raise ScoreError(f"{path}: no key {key!r} (keys {t.files})")
    tiles = [np.asarray(x, np.float32) for x in t[key][:n]]
    return tiles


# ---------------------------------------------------------------- scoring

def _sizes(ref, tiles, smoke):
    problems = []
    if len(ref["ct"]) < MIN_GROUPS:
        problems.append(f"reference has {len(ref['ct'])} slices; SRS-1 needs at least {MIN_GROUPS}")
    if len(tiles) < MIN_SIM_TILES:
        problems.append(f"set has {len(tiles)} tiles; SRS-1 needs at least {MIN_SIM_TILES}")
    small = [i for i, t in enumerate(tiles) if min(t.shape) < MIN_TILE]
    if small:
        problems.append(f"{len(small)} tiles are under {MIN_TILE} px (first: index {small[0]})")
    if problems and not smoke:
        raise ScoreError("; ".join(problems))
    return problems


def gates(planted, control):
    """The gate results computed from the planted AUCs and the control's worst AUC: {name: bool}."""
    g = {}
    same = [v for v in (planted.get("same") or {}).values()]
    g["planted_same"] = bool(same) and all(v is not None and v < PLANTED_SAME_MAX for v in same)
    for k in ("noise", "blur"):
        vals = [v for v in (planted.get(k) or {}).values()]
        g[f"planted_{k}"] = bool(vals) and all(v is not None and v >= PLANTED_SHIFT_MIN for v in vals)
    cw = (control or {}).get("worst")
    g["control"] = cw is not None and cw < CONTROL_MAX
    return g


def verdict(worst, control_worst):
    """kit.simcritic.verdict's rule (inclusive bars), safe when either worst is None (then FAIL, gap None)."""
    ok = worst is not None and control_worst is not None and worst <= control_worst + MARGIN and worst <= CEILING
    gap = None if worst is None or control_worst is None else round(worst - min(control_worst + MARGIN, CEILING), 4)
    return {"verdict": "PASS" if ok else "FAIL", "worst": worst, "control_worst": control_worst, "margin": MARGIN,
            "ceiling": CEILING, "gap_to_bar": gap}


def d99_for(n_groups, table=None):
    """D99 of the nearest calibrated group count at or above N_GROUPS (None when none is calibrated)."""
    table = D99 if table is None else table
    ks = sorted(int(k) for k in table if int(k) >= n_groups)
    return table[ks[0]] if ks else None


_DEFAULT = object()


def status(v, n_groups, admit=_DEFAULT, table=None, gate=None, smoke=False):
    """PASS, FAIL, INCONCLUSIVE, VOID (a gate failed) or SMOKE, with the reason. ADMIT and TABLE default to this
    module's calibration; `check` passes the ones stored in the record."""
    admit = ADMIT_GROUPS if admit is _DEFAULT else admit
    if smoke:
        return "SMOKE", "a smoke run (sizes or steps below SRS-1) is never a verdict"
    if gate is not None and not all(gate.values()):
        return "VOID", "gate failed: " + ", ".join(k for k, ok in gate.items() if not ok)
    if v["gap_to_bar"] is None:
        return "VOID", "no worst AUC"
    if admit is not None and n_groups >= admit:
        return v["verdict"], f"reference of {n_groups} groups is admitted (at least {admit})"
    d = d99_for(n_groups, table)
    if v["verdict"] == "FAIL" and d is not None and v["gap_to_bar"] > d:
        return "FAIL", f"reference of {n_groups} groups is not admitted; gap {v['gap_to_bar']} exceeds D99 {d}"
    return "INCONCLUSIVE", (f"reference of {n_groups} groups is not admitted; a PASS, or a FAIL within D99 "
                            f"({d}), is not a verdict")


def score(ref, tiles, generator, attempts, trained_on=(), device="cpu", steps=STEPS, smoke=False, progress=print):
    """Score simulated TILES against reference REF under SRS-1. GENERATOR: a dict naming the simulator (name,
    version, seeds, URL). ATTEMPTS: how many sets its authors scored under SRS-1 before this one. TRAINED_ON: slice
    names of REF the generator was fitted to; only even slices may be listed. SMOKE allows small sizes and STEPS for a
    pipeline check and marks the record SMOKE."""
    np = _np()
    from kit import simcritic as sc
    if steps != STEPS and not smoke:
        raise ScoreError(f"SRS-1 uses {STEPS} CNN steps; other values need smoke=True")
    if attempts is None or int(attempts) < 0:
        raise ScoreError("attempts must be the count of sets scored before this one (0 for the first)")
    size_problems = _sizes(ref, tiles, smoke)
    names = list(ref["name"])
    odd_trained = [n for i, n in enumerate(names) if i % 2 == 1 and n in set(trained_on)]
    if odd_trained:
        raise ScoreError(f"odd slices {odd_trained} trained the generator; SRS-1 scores sets on the odd slices")
    unknown = sorted(set(trained_on) - set(names))
    if unknown:
        raise ScoreError(f"trained_on names {unknown} are not slices of the reference")
    t0 = time.time()
    R, gR = sc.grid_windows(ref["ct"], WIN, ref.get("cover"), MIN_COVER)
    RH, gRH = sc.half(ref["ct"], None, WIN, ref.get("cover"), MIN_COVER)
    S, gS = sc.grid_windows(tiles, WIN)
    SH, gSH = sc.half(tiles, None, WIN)
    ev, od, evh, odh = gR % 2 == 0, gR % 2 == 1, gRH % 2 == 0, gRH % 2 == 1
    rec = {"standard": STANDARD, "scorer": scorer_digests(), "settings": dict(SETTINGS, steps=steps),
           "smoke": bool(smoke), "size_problems": size_problems, "device": device,
           "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "reference": {"id": ref.get("id", "custom"), "slices": names, "n_groups": len(names),
                         "n_windows": int(len(R)), "n_even": int(ev.sum()), "n_odd": int(od.sum()),
                         "digest": sc.digest(R), "trained_on": list(trained_on)},
           "set": {"n_tiles": len(tiles), "n_windows": int(len(S)), "digest": sc.digest(S)},
           "generator": dict(generator or {}), "attempts": int(attempts)}
    progress(f"windows: reference {len(R)} ({int(ev.sum())} even, {int(od.sum())} odd), set {len(S)}")
    progress("planted checks")
    rec["planted"] = sc.planted(R, gR, critics=("feat", "cnn"), steps=steps, device=device, progress=progress)
    progress("control: even against odd slices")
    rec["control"] = sc.judge(R[ev], gR[ev], R[od], gR[od], (RH[evh], gRH[evh]), (RH[odh], gRH[odh]),
                              critics=CRITICS, folds=FOLDS, seeds=SEEDS, steps=steps, device=device,
                              progress=progress)
    progress("set: odd slices against the simulated tiles")
    rec["result"] = sc.judge(R[od], gR[od], S, gS, (RH[odh], gRH[odh]), (SH, gSH), critics=CRITICS, folds=FOLDS,
                             seeds=SEEDS, steps=steps, device=device, progress=progress)
    rec["gates"] = gates(rec["planted"], rec["control"])
    rec["verdict"] = verdict(rec["result"].get("worst"), rec["control"].get("worst"))
    rec["status"], rec["reason"] = status(rec["verdict"], len(names), gate=rec["gates"], smoke=smoke)
    rec["calibration"] = {"admit_groups": ADMIT_GROUPS, "d99": {str(k): v for k, v in D99.items()}}
    rec["seconds"] = round(time.time() - t0, 1)
    rec["record_sha256"] = record_digest(rec)
    return rec


def record_digest(rec):
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def check(rec):
    """Problems with a record, recomputed from its own numbers: [] when it is consistent with SRS-1."""
    p = []
    if rec.get("standard") != STANDARD:
        p.append(f"standard is {rec.get('standard')!r}, not {STANDARD}")
    if rec.get("record_sha256") != record_digest(rec):
        p.append("record_sha256 does not match the record")
    smoke = bool(rec.get("smoke"))
    s = rec.get("settings") or {}
    for k, v in SETTINGS.items():
        if k == "steps" and smoke:
            continue
        if s.get(k) != v:
            p.append(f"setting {k} is {s.get(k)!r}, SRS-1 fixes {v!r}")
    ref, st = rec.get("reference") or {}, rec.get("set") or {}
    if not smoke:
        if (ref.get("n_groups") or 0) < MIN_GROUPS:
            p.append(f"reference has {ref.get('n_groups')} groups, under {MIN_GROUPS}")
        if (st.get("n_tiles") or 0) < MIN_SIM_TILES:
            p.append(f"set has {st.get('n_tiles')} tiles, under {MIN_SIM_TILES}")
    names = ref.get("slices") or []
    odd = [n for i, n in enumerate(names) if i % 2 == 1 and n in set(ref.get("trained_on") or [])]
    if odd:
        p.append(f"odd slices {odd} are listed as trained on")
    for part in ("control", "result"):
        crit = (rec.get(part) or {}).get("critics") or {}
        if not smoke and sorted(crit) != sorted(CRITICS):
            p.append(f"{part} ran critics {sorted(crit)}, SRS-1 runs {sorted(CRITICS)}")
        for c, r in crit.items():
            runs = [x.get("auc") for x in r.get("runs") or []]
            if not smoke and len(runs) != len(SEEDS):
                p.append(f"{part} {c} has {len(runs)} seed runs, SRS-1 runs {len(SEEDS)}")
            if runs and abs(sum(runs) / len(runs) - r.get("auc", -1)) > 1e-9:
                p.append(f"{part} {c} AUC is not the mean of its runs")
        if crit:
            worst = max(r["auc"] for r in crit.values())
            if abs(worst - ((rec.get(part) or {}).get("worst") or -1)) > 1e-9:
                p.append(f"{part} worst is not the highest critic AUC")
    g = gates(rec.get("planted") or {}, rec.get("control") or {})
    if g != rec.get("gates"):
        p.append(f"gates {rec.get('gates')} recompute as {g}")
    v = verdict((rec.get("result") or {}).get("worst"), (rec.get("control") or {}).get("worst"))
    if v != rec.get("verdict"):
        p.append(f"verdict {rec.get('verdict')} recomputes as {v}")
    cal = rec.get("calibration") or {}
    table = {int(k): x for k, x in (cal.get("d99") or {}).items()}
    stt, _ = status(v, ref.get("n_groups") or 0, admit=cal.get("admit_groups"), table=table, gate=g, smoke=smoke)
    if cal.get("admit_groups") is None and stt in ("PASS",):
        p.append("PASS with no admitted reference size")
    if stt != rec.get("status"):
        p.append(f"status {rec.get('status')} recomputes as {stt}")
    return p


# ---------------------------------------------------------------- calibration (preregistered 26 Nov 2026)

CAL_REAL_SEED0 = 4611101
CAL_SIM_SEED = 4612001


def calibrate(groups=(6, 12, 24), reps=200, power_reps=100, sigmas=(0.5, 0.8), pool=480, n_sim=MIN_SIM_TILES,
              tiles_per_group=4, progress=print):
    """The null calibration of docs/prereg/2026-11-26-srs1-null-calibration.md, feat critic only. Returns per G the
    null replicates (control, set, gap), f(G), D99(G), the power arms' PASS rates and the admission decision."""
    np = _np()
    from scipy import ndimage as nd
    from kit import hardcases, simcritic as sc
    gmax = max(groups)
    t0 = time.time()
    real_tiles = [list(hardcases.tiles(tiles_per_group, CAL_REAL_SEED0 + g, 256)["image"]) for g in range(gmax)]
    sim_tiles = list(hardcases.tiles(pool, CAL_SIM_SEED, 256)["image"])
    progress(f"tiles made in {time.time() - t0:.0f} s")

    def feats_of(tiles, sigma=None):
        W, gid = sc.grid_windows([nd.gaussian_filter(np.asarray(t, np.float32), sigma) if sigma else t
                                  for t in tiles], WIN)
        return np.stack([sc.features(w) for w in W]), gid

    RF = []
    for g, ts in enumerate(real_tiles):
        F, _ = feats_of(ts)
        RF.append(F)
    SF = {None: feats_of(sim_tiles)}
    for s in sigmas:
        SF[s] = feats_of(sim_tiles, s)
    progress(f"features in {time.time() - t0:.0f} s")

    def auc_feat(Fa, ga, Fb, gb):
        runs = []
        for seed in SEEDS:
            dummy_a, dummy_b = np.zeros((len(Fa), 1, 1)), np.zeros((len(Fb), 1, 1))
            runs.append(sc.critic_auc(dummy_a, ga, dummy_b, gb, "feat", FOLDS, seed, feats=(Fa, Fb))["auc"])
        return float(np.mean(runs))

    out = {"prereg": "docs/prereg/2026-11-26-srs1-null-calibration.md", "critic": "feat", "folds": FOLDS,
           "seeds": list(SEEDS), "real_seeds": [CAL_REAL_SEED0, CAL_REAL_SEED0 + gmax - 1], "sim_seed": CAL_SIM_SEED,
           "pool": pool, "n_sim": n_sim, "tiles_per_group": tiles_per_group, "reps": reps,
           "power_reps": power_reps, "sigmas": list(sigmas), "by_groups": {}}
    for G in groups:
        rows = {None: [], **{s: [] for s in sigmas}}
        for r in range(reps):
            rng = np.random.default_rng([G, r, 1126])
            perm = rng.permutation(G)
            A, B = perm[:G // 2], perm[G // 2:]
            Fa = np.vstack([RF[i] for i in A])
            ga = np.concatenate([np.full(len(RF[i]), i) for i in A])
            Fb = np.vstack([RF[i] for i in B])
            gb = np.concatenate([np.full(len(RF[i]), i) for i in B])
            ctrl = auc_feat(Fa, ga, Fb, gb)
            pick = np.sort(rng.choice(pool, n_sim, replace=False))
            for s in rows:
                if s is not None and r >= power_reps:
                    continue
                F, gid = SF[s]
                m = np.isin(gid, pick)
                st = auc_feat(Fb, gb, F[m], gid[m])
                v = verdict(st, ctrl)
                rows[s].append({"control": round(ctrl, 4), "set": round(st, 4), "gap": v["gap_to_bar"],
                                "verdict": v["verdict"]})
            if (r + 1) % 25 == 0:
                progress(f"  G {G}: {r + 1} of {reps} replicates, {time.time() - t0:.0f} s")
        null = rows[None]
        gaps = np.array([x["gap"] for x in null])
        res = {"null": null, "false_fail": float(np.mean([x["verdict"] == "FAIL" for x in null])),
               "d99": round(float(np.percentile(gaps, 99)), 4),
               "control_sd": round(float(np.std([x["control"] for x in null])), 4),
               "set_sd": round(float(np.std([x["set"] for x in null])), 4),
               "power": {str(s): {"pass_rate": float(np.mean([x["verdict"] == "PASS" for x in rows[s]])),
                                  "set_mean": round(float(np.mean([x["set"] for x in rows[s]])), 4),
                                  "rows": rows[s]} for s in sigmas}}
        res["admitted"] = res["false_fail"] <= 0.10
        out["by_groups"][str(G)] = res
        progress(f"G {G}: false FAIL {res['false_fail']:.3f}, D99 {res['d99']}, admitted {res['admitted']}")
    adm = [G for G in groups if out["by_groups"][str(G)]["admitted"]]
    out["admit_groups"] = min(adm) if adm else None
    out["d99"] = {str(G): out["by_groups"][str(G)]["d99"] for G in groups}
    out["seconds"] = round(time.time() - t0, 1)
    return out


# ---------------------------------------------------------------- command line

def _print(lines):
    for ln in lines:
        print(ln)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.simscore", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reference", help="fetch the R343-v1 reference slices to an npz")
    r.add_argument("out")
    s = sub.add_parser("score", help="score a simulated set under SRS-1 and write its record")
    s.add_argument("--reference", required=True, help="a reference npz (python -m kit.simscore reference R343.npz)")
    s.add_argument("--sim", required=True, help="npz of simulated tiles")
    s.add_argument("--key", default="image", help="the npz key of the tiles (default image)")
    s.add_argument("--generator", required=True, help="the simulator's name and version, for the record")
    s.add_argument("--attempts", type=int, required=True, help="sets your team scored under SRS-1 before this one")
    s.add_argument("--trained-on", nargs="*", default=[], help="even reference slice names the generator was fitted to")
    s.add_argument("--device", default="cpu")
    s.add_argument("--smoke", action="store_true", help="small sizes and --steps for a pipeline check; never a verdict")
    s.add_argument("--steps", type=int, default=STEPS)
    s.add_argument("--out", required=True)
    c = sub.add_parser("check", help="recompute a record's gates, verdict and status; exit 1 on any problem")
    c.add_argument("record")
    c.add_argument("--json", action="store_true")
    k = sub.add_parser("calibrate", help="rerun the preregistered null calibration (feat critic, synthetic tiles)")
    k.add_argument("--out", required=True)
    k.add_argument("--reps", type=int, default=200)
    k.add_argument("--power-reps", type=int, default=100)
    a = ap.parse_args(argv)
    if sys.stdout.isatty():
        try:
            from kit import termstyle
            termstyle.script()
        except Exception:
            pass
    if a.cmd == "reference":
        ref = reference_r343()
        save_reference(ref, a.out)
        from kit import simcritic as sc
        R, _ = sc.grid_windows(ref["ct"], WIN, ref["cover"], MIN_COVER)
        _print([f"wrote {a.out}: {len(ref['ct'])} slices, {len(R)} windows, digest {sc.digest(R)}"])
        return 0
    if a.cmd == "score":
        ref = load_reference(a.reference)
        tiles = load_sim(a.sim, a.key)
        rec = score(ref, tiles, {"name": a.generator, "file": os.path.basename(a.sim), "key": a.key,
                                 "file_sha256": file_sha256(a.sim)}, a.attempts, a.trained_on, a.device, a.steps,
                    a.smoke)
        with open(a.out, "w") as f:
            json.dump(rec, f, indent=1, sort_keys=True)
        v = rec["verdict"]
        _print([f"{STANDARD} {rec['status']}: worst {v['worst']}, control {v['control_worst']}, "
                f"gap to bar {v['gap_to_bar']}", rec["reason"], f"record {a.out}"])
        return 0
    if a.cmd == "check":
        try:
            with open(a.record) as f:
                rec = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"cannot read record {a.record}: {exc}", file=sys.stderr)
            return 2
        probs = check(rec)
        if a.json:
            print(json.dumps({"ok": not probs, "problems": probs, "status": rec.get("status")}))
        else:
            _print([f"{STANDARD} record {a.record}: {'OK' if not probs else 'PROBLEMS'} (status {rec.get('status')})"]
                   + [f"  {x}" for x in probs])
        return 1 if probs else 0
    res = calibrate(reps=a.reps, power_reps=a.power_reps)
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    _print([f"admit_groups {res['admit_groups']}, d99 {res['d99']}"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
