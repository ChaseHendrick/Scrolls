"""Draft SRS-2 pass rule for the Sim Realism Standard: a stratified permutation test over whole units.

Why. SRS-1's null calibration (docs/evidence/srs1-calibration-1126/) found that its fixed bar (the set's worst critic
AUC at most one real-against-real control draw plus 0.05) fails a perfect simulator 29 to 60 percent of the time,
because one control draw spreads with sd 0.10 at 6 groups. So SRS-1 can only rule a set out. SRS-2 replaces the bar
with a p-value whose false FAIL rate is set by its alpha, and keeps every SRS-1 critic, window and training setting
(kit.simscore). This module is a draft: it is not in force until its preregistered calibration
(docs/prereg/2026-11-26-srs2-null-calibration.md) and an independent review have passed.

The test, in order:
1. Units. A real unit is one reference slice not listed as trained on (the generator may have been fitted to the
   listed ones; they are never scored). The simulated tiles are cut, in file order, into sim units of about as many
   windows as the median real slice (no picking), so a sim unit is the same size as a real one. A slice's windows
   are correlated, so the unit, not the window, is what gets permuted.
2. Folds. Real units and sim units are dealt separately, in a seeded order, round robin to FOLDS folds, so each fold
   holds both kinds. Each critic (SRS-1's feat, cnn and cnn_half, SEEDS training seeds) scores fold k with a model
   trained, real against sim, on fold k + 1 (mod FOLDS) only: the "ring" design. A unit's score is the mean of its
   windows' scores, averaged over the training seeds (the fold deal is the same for every seed). The usual
   cross-fitting (train on every other fold) was tried first on development seeds and failed a perfect simulator
   0.06 to 0.10 of the time at alpha 0.05, because each pair of folds then enters two folds' tests; in the ring each
   pair enters one, and the same draws gave 0.03 to 0.07.
3. Statistic. Within each fold the units are ranked by score; S_c is the sum over folds of the real units' ranks for
   critic c, standardized to Z_c by its exact mean and variance under within-fold relabeling. T = max over critics
   of Z_c, so the whole family of critics is tested at once.
4. p-value. PERMS within-fold relabelings (seeded; the same draws for every critic, so the max is taken inside each
   draw): p = (1 + #{T_perm >= T}) / (1 + PERMS). Under exchangeable units (a perfect simulator) each fold's
   held-out scores do not depend on that fold's labels, so p is close to uniform; the three fold tests are not
   independent (fold k's labels train fold k - 1's model), so exactness is checked by the preregistered calibration,
   not assumed.
5. Gates, each able to fail (a failed gate makes the record VOID): the same pipeline must FAIL the set with Gaussian
   blur sigma PLANT_BLUR and with noise sd PLANT_NOISE added (p at most ALPHA), and must not FAIL the set against
   itself (half its sim units, seeded, as stand-in real units; p above SPLIT_MIN_P).
6. Status. FAIL when p <= ALPHA. PASS when p > ALPHA, the gates hold and the reference has at least ADMIT_GROUPS
   eligible slices (set by the calibration; None until then, when a would-be PASS is INCONCLUSIVE). SMOKE for runs
   below the sizes or steps.

A PASS means no SRS-2 critic separated the set's units from the reference's slices at ALPHA, on a reference where the
same judge caught a blurred and a noisy copy of the set: Model output, not proof that the set is real. Gray values
only; no labels are scored.

    python -m kit.simperm rule [--json]
    python -m kit.simperm score --reference REF.npz --sim SIM.npz --generator NAME --attempts N --out REC.json
    python -m kit.simperm check REC.json [--json]
    python -m kit.simperm calibrate --out CAL.json [--reps 200 --power-reps 100] [--workers 4]
"""
import argparse
import hashlib
import json
import os
import sys
import time

from kit import simscore as ss

STANDARD = "SRS-2-draft"
ALPHA = 0.05
PERMS = 9999
PERM_SEED = 20261127
FOLD_SEED = 0
SPLIT_SEED = 1
SPLIT_MIN_P = 0.01
PLANT_BLUR = 1.0
PLANT_NOISE = 0.08
DESIGN = "ring"
MIN_REAL_UNITS = 6
MIN_SIM_UNITS = 6
CRITICS = ss.CRITICS
FOLDS = ss.FOLDS
SEEDS = ss.SEEDS
STEPS = ss.STEPS
WIN = ss.WIN
MIN_COVER = ss.MIN_COVER
SETTINGS = {"alpha": ALPHA, "perms": PERMS, "perm_seed": PERM_SEED, "fold_seed": FOLD_SEED, "split_seed": SPLIT_SEED,
            "split_min_p": SPLIT_MIN_P, "plant_blur": PLANT_BLUR, "plant_noise": PLANT_NOISE,
            "min_real_units": MIN_REAL_UNITS, "min_sim_units": MIN_SIM_UNITS, "critics": list(CRITICS),
            "folds": FOLDS, "seeds": list(SEEDS), "steps": STEPS, "win": WIN, "min_cover": MIN_COVER, "design": DESIGN}

# Set by the preregistered calibration (docs/prereg/2026-11-26-srs2-null-calibration.md); None until it has run and
# passed review, so no SRS-2 draft record can PASS before then.
ADMIT_GROUPS = None


class PermError(ValueError):
    pass


def _np():
    import numpy as np
    return np


# ---------------------------------------------------------------- units and folds

def sim_units(window_tile, n_tiles, per_unit):
    """Unit id per tile: consecutive tiles in file order, a unit closed once it holds at least PER_UNIT windows;
    a last unit short of PER_UNIT is dropped (id -1). WINDOW_TILE: the tile index of every window."""
    np = _np()
    counts = np.bincount(np.asarray(window_tile), minlength=n_tiles)
    uid, cur, have = np.full(n_tiles, -1), 0, 0
    for t in range(n_tiles):
        uid[t] = cur
        have += int(counts[t])
        if have >= per_unit:
            cur, have = cur + 1, 0
    if have:
        uid[uid == cur] = -1
    return uid


def deal(real_ids, sim_ids, folds=FOLDS, seed=FOLD_SEED):
    """{unit: fold}, real and sim units dealt separately (seeded order, round robin), so every fold holds both."""
    np = _np()
    rng = np.random.default_rng(int(seed))
    out = {}
    for ids in (sorted(set(real_ids)), sorted(set(sim_ids))):
        if len(ids) < folds:
            raise PermError(f"{len(ids)} units cannot fill {folds} folds")
        for i, k in enumerate(rng.permutation(len(ids))):
            out[ids[k]] = i % folds
    return out


# ---------------------------------------------------------------- scores

def _train_score(critic, Xa, Xb, Xte, seed, steps, device):
    np = _np()
    from kit import simcritic as sc
    y = np.r_[np.ones(len(Xa)), np.zeros(len(Xb))]
    if critic == "feat":
        return np.asarray(sc._logistic(np.vstack([Xa, Xb]), y, Xte), np.float64)
    return np.asarray(sc._cnn(np.concatenate([Xa, Xb]), y, Xte, steps, seed, device), np.float64)


def train_folds(k, folds, design):
    """The folds whose units train the model that scores fold K: every other fold ("cross"), or only the next one
    ("ring": fold k + 1 mod FOLDS), so that no two folds' tests share a pair of training folds."""
    if design == "ring":
        return {(k + 1) % len(folds)} if len(folds) > 1 else set()
    if design in ("holdout", "half"):
        return set(folds) - {k} if k == folds[0] else None
    if design == "cross":
        return set(folds) - {k}
    raise PermError(f"unknown design {design!r}")


def unit_scores(A, uA, B, uB, critic, fold_of, seeds=SEEDS, steps=STEPS, device="cpu", design=None):
    """Cross-fitted unit scores. A (real, label 1) and B (sim, label 0) are window stacks, or feature rows for the
    feat critic; uA and uB the unit id of every row (unit ids must not overlap). Returns {unit: score}, each the mean
    over SEEDS of the mean held-out score of that unit's rows."""
    np = _np()
    uA, uB = np.asarray(uA), np.asarray(uB)
    fA = np.array([fold_of[u] for u in uA])
    fB = np.array([fold_of[u] for u in uB])
    design = DESIGN if design is None else design
    folds = sorted(set(fold_of.values()))
    acc = {}
    for k in folds:
        te = np.r_[np.flatnonzero(fA == k), len(uA) + np.flatnonzero(fB == k)]
        units = np.r_[uA, uB][te]
        X = np.concatenate([A, B])
        tr = train_folds(k, folds, design)
        if tr is None:
            continue
        tr = sorted(tr)
        ta, tb = np.isin(fA, tr), np.isin(fB, tr)
        for s in seeds:
            sc_ = _train_score(critic, A[ta], B[tb], X[te], int(s) * 101 + k, steps, device)
            for u in np.unique(units):
                acc.setdefault(int(u) if np.issubdtype(type(u), np.integer) else u, []).append(
                    float(sc_[units == u].mean()))
    return {u: float(np.mean(v)) for u, v in acc.items()}


def _within_ranks(x):
    np = _np()
    from scipy.stats import rankdata
    return rankdata(np.asarray(x, np.float64))


def permtest(scores, real_units, fold_of, perms=PERMS, seed=PERM_SEED):
    """Max-over-critics stratified permutation test. SCORES: {critic: {unit: score}}, REAL_UNITS the units labeled
    real. Returns {"z": {critic: Z}, "t": T, "p": p, "auc_unit": {critic: unit-level AUC}, "perms": PERMS}."""
    np = _np()
    critics = sorted(scores)
    real = set(real_units)
    units = sorted(fold_of, key=lambda u: (str(type(u)), u))
    folds = sorted(set(fold_of.values()))
    rng = np.random.default_rng(int(seed))
    mean = var = 0.0
    obs = {c: 0.0 for c in critics}
    null = {c: np.zeros(perms) for c in critics}
    for k in folds:
        us = [u for u in units if fold_of[u] == k]
        n, r = len(us), sum(u in real for u in us)
        if r == 0 or r == n:
            raise PermError(f"fold {k} holds only one kind of unit")
        mean += r * (n + 1) / 2
        var += r * (n - r) * (n + 1) / 12
        ranks = {c: _within_ranks([scores[c][u] for u in us]) for c in critics}
        lab = np.array([u in real for u in us])
        for c in critics:
            obs[c] += float(ranks[c][lab].sum())
        pick = np.argsort(rng.random((perms, n)), axis=1)[:, :r]
        for c in critics:
            null[c] += ranks[c][pick].sum(1)
    sd = var ** 0.5
    z = {c: (obs[c] - mean) / sd for c in critics}
    t = max(z.values())
    tn = np.max(np.stack([(null[c] - mean) / sd for c in critics]), axis=0)
    p = (1 + int((tn >= t - 1e-12).sum())) / (1 + perms)
    from kit import simcritic as sc
    auc = {}
    for c in critics:
        y = np.array([u in real for u in units])
        auc[c] = round(float(sc.auc([scores[c][u] for u in units], y)), 6)
    return {"z": {c: round(v, 6) for c, v in z.items()}, "t": round(t, 6), "p": round(p, 6), "auc_unit": auc,
            "perms": perms}


def test_units(data, real_units, sim_units_, fold_of, critics=CRITICS, seeds=SEEDS, steps=STEPS, device="cpu",
               perms=PERMS, perm_seed=PERM_SEED, progress=None):
    """Run each critic and the permutation test. DATA: {critic: (A, uA, B, uB)} (feature rows for feat, windows
    otherwise). Returns {"scores": {critic: {unit: score}}, **permtest}."""
    scores = {}
    for c in critics:
        if c not in data:
            continue
        A, uA, B, uB = data[c]
        scores[c] = unit_scores(A, uA, B, uB, c, fold_of, seeds, steps, device)
        if progress:
            progress(f"  critic {c} done")
    out = permtest(scores, real_units, fold_of, perms, perm_seed)
    out["scores"] = {c: {str(u): round(v, 9) for u, v in s.items()} for c, s in scores.items()}
    return out


# ---------------------------------------------------------------- status

def gates(planted):
    """{name: bool} from the planted tests' p-values: blur and noise must FAIL, the self split must not."""
    g = {}
    for k in ("blur", "noise"):
        p = (planted.get(k) or {}).get("p")
        g[f"planted_{k}"] = p is not None and p <= ALPHA
    p = (planted.get("split") or {}).get("p")
    g["self_split"] = p is not None and p > SPLIT_MIN_P
    return g


_DEFAULT = object()


def status(p, n_real_units, gate=None, admit=_DEFAULT, smoke=False):
    admit = ADMIT_GROUPS if admit is _DEFAULT else admit
    if smoke:
        return "SMOKE", "a smoke run (sizes or steps below SRS-2) is never a verdict"
    if gate is not None and not all(gate.values()):
        return "VOID", "gate failed: " + ", ".join(k for k, ok in gate.items() if not ok)
    if p is None:
        return "VOID", "no p-value"
    if p <= ALPHA:
        return "FAIL", f"p {p} <= alpha {ALPHA}: a critic separated the set's units from the reference's slices"
    if admit is not None and n_real_units >= admit:
        return "PASS", f"p {p} > alpha {ALPHA} on {n_real_units} eligible slices (admitted from {admit})"
    return "INCONCLUSIVE", (f"p {p} > alpha {ALPHA}, but a reference of {n_real_units} eligible slices is not "
                            f"admitted (admit_groups {admit})")


# ---------------------------------------------------------------- scoring a set

def scorer_digests():
    here = os.path.dirname(os.path.abspath(__file__))
    return {n: ss.file_sha256(os.path.join(here, n)) for n in ("simcritic.py", "simscore.py", "simperm.py")}


def _transform(W, kind, seed):
    np = _np()
    from scipy import ndimage as nd
    from kit import simcritic as sc
    if kind == "blur":
        return np.stack([sc.unit(nd.gaussian_filter(w, PLANT_BLUR)) for w in W]).astype(np.float32)
    rng = np.random.default_rng(int(seed))
    return np.stack([sc.unit(w + rng.normal(0, PLANT_NOISE, w.shape)) for w in W]).astype(np.float32)


def score(ref, tiles, generator, attempts, trained_on=(), device="cpu", steps=STEPS, smoke=False, perms=PERMS,
          critics=CRITICS, progress=print):
    """Score simulated TILES against REF (kit.simscore.load_reference layout) under the SRS-2 draft rule."""
    np = _np()
    from kit import simcritic as sc
    if steps != STEPS and not smoke:
        raise PermError(f"SRS-2 uses {STEPS} CNN steps; other values need smoke=True")
    if attempts is None or int(attempts) < 0:
        raise PermError("attempts must be the count of sets scored before this one (0 for the first)")
    names = list(ref["name"])
    unknown = sorted(set(trained_on) - set(names))
    if unknown:
        raise PermError(f"trained_on names {unknown} are not slices of the reference")
    keep = [i for i, n in enumerate(names) if n not in set(trained_on)]
    cover = ref.get("cover")
    cts = [ref["ct"][i] for i in keep]
    covs = [cover[i] for i in keep] if cover is not None else None
    R, gR = sc.grid_windows(cts, WIN, covs, MIN_COVER)
    RH, gRH = sc.half(cts, None, WIN, covs, MIN_COVER)
    S, tS = sc.grid_windows(tiles, WIN)
    SH, tSH = sc.half(tiles, None, WIN)
    per_unit = int(np.median(np.bincount(gR)))
    uid = sim_units(tS, len(tiles), per_unit)
    n_sim_units = int(uid.max() + 1) if (uid >= 0).any() else 0
    problems = []
    if len(keep) < MIN_REAL_UNITS:
        problems.append(f"{len(keep)} eligible slices; SRS-2 needs at least {MIN_REAL_UNITS}")
    if n_sim_units < max(MIN_SIM_UNITS, 2 * FOLDS):
        problems.append(f"{n_sim_units} sim units of {per_unit} windows; SRS-2 needs at least {MIN_SIM_UNITS}")
    if problems and not smoke:
        raise PermError("; ".join(problems))
    real_ids = [f"r{i}" for i in range(len(keep))]
    sim_ids = [f"s{k}" for k in range(n_sim_units)]
    fold_of = deal(real_ids, sim_ids, FOLDS, FOLD_SEED)
    uR = np.array([f"r{g}" for g in gR])
    uRH = np.array([f"r{g}" for g in gRH])
    sm, smh = uid[tS] >= 0, uid[tSH] >= 0
    S, uS = S[sm], np.array([f"s{uid[t]}" for t in tS[sm]])
    SH, uSH = SH[smh], np.array([f"s{uid[t]}" for t in tSH[smh]])
    t0 = time.time()

    def data_for(Sw, SHw):
        d = {}
        for c in critics:
            if c == "feat":
                d[c] = (np.stack([sc.features(w) for w in R]), uR, np.stack([sc.features(w) for w in Sw]), uS)
            elif c == "cnn":
                d[c] = (R, uR, Sw, uS)
            elif c == "cnn_half" and len(SHw):
                d[c] = (RH, uRH, SHw, uSH)
        return d

    rec = {"standard": STANDARD, "scorer": scorer_digests(), "settings": dict(SETTINGS, steps=steps, perms=perms),
           "smoke": bool(smoke), "size_problems": problems, "device": device,
           "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "reference": {"id": ref.get("id", "custom"), "slices": names, "eligible": [names[i] for i in keep],
                         "n_real_units": len(keep), "n_windows": int(len(R)), "digest": sc.digest(R),
                         "trained_on": list(trained_on)},
           "set": {"n_tiles": len(tiles), "windows_per_unit": per_unit, "n_sim_units": n_sim_units,
                   "n_windows": int(len(S)), "digest": sc.digest(S)},
           "generator": dict(generator or {}), "attempts": int(attempts),
           "fold_of": {u: int(k) for u, k in sorted(fold_of.items())}}
    progress(f"units: {len(keep)} real ({len(R)} windows), {n_sim_units} sim of {per_unit} windows")
    progress("set: reference slices against the sim units")
    rec["result"] = test_units(data_for(S, SH), real_ids, sim_ids, fold_of, critics, SEEDS, steps, device, perms,
                               PERM_SEED, progress)
    rec["planted"] = {}
    for kind in ("blur", "noise"):
        progress(f"planted: the set with {kind}")
        Sk = _transform(S, kind, 11)
        SHk = _transform(SH, kind, 13) if len(SH) else SH
        rec["planted"][kind] = {k: v for k, v in test_units(data_for(Sk, SHk), real_ids, sim_ids, fold_of, critics,
                                                            SEEDS, steps, device, perms, PERM_SEED).items()
                                if k != "scores"}
    progress("planted: the set against itself")
    rng = np.random.default_rng(SPLIT_SEED)
    half_ids = set(rng.permutation(sim_ids)[:len(sim_ids) // 2].tolist())
    ps = [u for u in sim_ids if u in half_ids]
    qs = [u for u in sim_ids if u not in half_ids]
    fold_s = deal(ps, qs, FOLDS, FOLD_SEED)
    dsplit = {}
    for c, (A, uA, B, uB) in data_for(S, SH).items():
        a, b = np.isin(uB, ps), np.isin(uB, qs)
        dsplit[c] = (B[a], uB[a], B[b], uB[b])
    rec["planted"]["split"] = {k: v for k, v in test_units(dsplit, ps, qs, fold_s, critics, SEEDS, steps, device,
                                                           perms, PERM_SEED).items() if k != "scores"}
    rec["gates"] = gates(rec["planted"])
    rec["status"], rec["reason"] = status(rec["result"]["p"], len(keep), rec["gates"], smoke=smoke)
    rec["calibration"] = {"admit_groups": ADMIT_GROUPS}
    rec["seconds"] = round(time.time() - t0, 1)
    rec["record_sha256"] = record_digest(rec)
    return rec


def record_digest(rec):
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def check(rec):
    """Problems with a record: [] when its p-value, gates and status recompute from its own stored unit scores."""
    p = []
    if rec.get("standard") != STANDARD:
        p.append(f"standard is {rec.get('standard')!r}, not {STANDARD}")
    if rec.get("record_sha256") != record_digest(rec):
        p.append("record_sha256 does not match the record")
    smoke = bool(rec.get("smoke"))
    s = rec.get("settings") or {}
    for k, v in SETTINGS.items():
        if k in ("steps", "perms") and smoke:
            continue
        if s.get(k) != v:
            p.append(f"setting {k} is {s.get(k)!r}, SRS-2 draft fixes {v!r}")
    res = rec.get("result") or {}
    fold_of = rec.get("fold_of") or {}
    scores = res.get("scores") or {}
    if not smoke and sorted(scores) != sorted(CRITICS):
        p.append(f"result ran critics {sorted(scores)}, SRS-2 runs {sorted(CRITICS)}")
    if scores and fold_of:
        real = [u for u in fold_of if u.startswith("r")]
        try:
            again = permtest(scores, real, fold_of, int(s.get("perms", PERMS)), PERM_SEED)
        except PermError as exc:
            p.append(f"permutation test does not recompute: {exc}")
        else:
            for k in ("t", "p"):
                if abs(again[k] - (res.get(k) if res.get(k) is not None else -9)) > 1e-6:
                    p.append(f"result {k} {res.get(k)} recomputes as {again[k]}")
    g = gates(rec.get("planted") or {})
    if g != rec.get("gates"):
        p.append(f"gates {rec.get('gates')} recompute as {g}")
    n = (rec.get("reference") or {}).get("n_real_units") or 0
    st, _ = status(res.get("p"), n, g, (rec.get("calibration") or {}).get("admit_groups"), smoke)
    if st != rec.get("status"):
        p.append(f"status {rec.get('status')} recomputes as {st}")
    return p


# ---------------------------------------------------------------- calibration (preregistered 26 Nov 2026)

CAL_POOL_SEED0 = 4621001   # unit u of the pool is hardcases.tiles(4, CAL_POOL_SEED0 + u, 256)
CAL_POOL = 400
CAL_ONESEED = 4622001      # the one-seed sim (SRS-1's kind of perfect simulator), report only
CAL_ONESEED_TILES = 480
CAL_TILES_PER_UNIT = 4
CAL_GROUPS = (6, 12, 24)
CAL_KS = ("G", 60)
CAL_SIGMAS = (0.5, 0.8)


def _pool_tiles(seed):
    from kit import hardcases
    return list(hardcases.tiles(CAL_TILES_PER_UNIT, seed, 256)["image"])


def _feat_rows(tiles, sigma):
    np = _np()
    from scipy import ndimage as nd
    from kit import simcritic as sc
    W, _ = sc.grid_windows([nd.gaussian_filter(np.asarray(t, np.float32), sigma) if sigma else t for t in tiles], WIN)
    return np.stack([sc.features(w) for w in W])


def _unit_feats(seed):
    tiles = _pool_tiles(seed)
    return {s: _feat_rows(tiles, s) for s in (None,) + CAL_SIGMAS}


def calibration_features(pool=CAL_POOL, workers=1, progress=print, seed0=CAL_POOL_SEED0, oneseed_seed=CAL_ONESEED):
    """Feature rows of every pool unit (unblurred and at each CAL_SIGMAS) and of the one-seed sim's units. SEED0 and
    ONESEED_SEED default to the preregistered seeds; development runs pass other ones."""
    np = _np()
    from kit import simcritic as sc
    seeds = [seed0 + u for u in range(pool)]
    t0 = time.time()
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(workers) as ex:
            units = list(ex.map(_unit_feats, seeds, chunksize=4))
    else:
        units = [_unit_feats(s) for s in seeds]
    progress(f"pool features: {pool} units in {time.time() - t0:.0f} s")
    from kit import hardcases
    one = list(hardcases.tiles(CAL_ONESEED_TILES, oneseed_seed, 256)["image"])
    W, tile = sc.grid_windows(one, WIN)
    F = np.stack([sc.features(w) for w in W])
    oneseed = [F[np.isin(tile, range(k, k + CAL_TILES_PER_UNIT))]
               for k in range(0, CAL_ONESEED_TILES, CAL_TILES_PER_UNIT)]
    progress(f"one-seed features in {time.time() - t0:.0f} s")
    return units, oneseed


def tested_folds(fold_of, design=None):
    """The part of FOLD_OF the test reads: every fold, or only the first one for the exact holdout designs."""
    design = DESIGN if design is None else design
    if design in ("holdout", "half"):
        first = min(fold_of.values())
        return {u: k for u, k in fold_of.items() if k == first}
    return fold_of


def _feat_test(real_rows, sim_rows, perms, perm_seed, fold_seed, design=None):
    """The SRS-2 test with the feat critic on lists of per-unit feature rows."""
    np = _np()
    rid = [f"r{i}" for i in range(len(real_rows))]
    sid = [f"s{i}" for i in range(len(sim_rows))]
    A = np.vstack(real_rows)
    uA = np.concatenate([np.full(len(x), f"r{i}") for i, x in enumerate(real_rows)])
    B = np.vstack(sim_rows)
    uB = np.concatenate([np.full(len(x), f"s{i}") for i, x in enumerate(sim_rows)])
    d = DESIGN if design is None else design
    fold_of = deal(rid, sid, 2 if d == "half" else FOLDS, fold_seed)
    scores = {"feat": unit_scores(A, uA, B, uB, "feat", fold_of, seeds=(0,), design=design)}
    return permtest(scores, rid, tested_folds(fold_of, design), perms, perm_seed)


def _srs1_rule(real_rows, sim_rows):
    """SRS-1's fixed bar on the same units (feat critic): control = half the real units against the other half."""
    np = _np()
    from kit import simcritic as sc
    G = len(real_rows)
    ga = np.concatenate([np.full(len(x), i) for i, x in enumerate(real_rows)])
    gb = np.concatenate([np.full(len(x), i) for i, x in enumerate(sim_rows)])
    A, B = np.vstack(real_rows), np.vstack(sim_rows)
    h = ga < G // 2
    dummy = lambda n: np.zeros((n, 1, 1))  # noqa: E731
    ctrl = np.mean([sc.critic_auc(dummy(h.sum()), ga[h], dummy((~h).sum()), ga[~h], "feat", FOLDS, s,
                                  feats=(A[h], A[~h]))["auc"] for s in SEEDS])
    st = np.mean([sc.critic_auc(dummy((~h).sum()), ga[~h], dummy(len(B)), gb, "feat", FOLDS, s,
                                feats=(A[~h], B))["auc"] for s in SEEDS])
    return ss.verdict(float(st), float(ctrl))["verdict"]


def calibrate(groups=CAL_GROUPS, ks=CAL_KS, reps=200, power_reps=100, perms=PERMS, pool=CAL_POOL, workers=1,
              progress=print, feats=None):
    """The null calibration of docs/prereg/2026-11-26-srs2-null-calibration.md (feat critic, synthetic units).
    Per G and K: the perfect simulator's FAIL rate (G + K distinct pool units, roles at random), SRS-1's bar on the
    same draws, the blurred simulators' FAIL rates (power), and the one-seed simulator's FAIL rate (report only)."""
    np = _np()
    t0 = time.time()
    units, oneseed = feats if feats is not None else calibration_features(pool, workers, progress)
    out = {"prereg": "docs/prereg/2026-11-26-srs2-null-calibration.md", "standard": STANDARD, "critic": "feat",
           "alpha": ALPHA, "perms": perms, "folds": FOLDS, "pool": pool, "pool_seeds": [CAL_POOL_SEED0,
           CAL_POOL_SEED0 + pool - 1], "oneseed_seed": CAL_ONESEED, "tiles_per_unit": CAL_TILES_PER_UNIT,
           "reps": reps, "power_reps": power_reps, "sigmas": list(CAL_SIGMAS), "by": {}}
    for G in groups:
        for kk in ks:
            K = G if kk == "G" else int(kk)
            rows = {"null": [], "srs1": [], "oneseed": [], **{f"blur{s}": [] for s in CAL_SIGMAS}}
            for r in range(reps):
                rng = np.random.default_rng([G, K, r, 1127])
                pick = rng.choice(pool, G + K, replace=False)
                real = [units[i][None] for i in pick[:G]]
                sim = [units[i][None] for i in pick[G:]]
                res = _feat_test(real, sim, perms, int(rng.integers(2 ** 31)), int(rng.integers(2 ** 31)))
                rows["null"].append(res["p"])
                rows["srs1"].append(_srs1_rule(real, sim))
                if r < power_reps:
                    for s in CAL_SIGMAS:
                        simb = [units[i][s] for i in pick[G:]]
                        rows[f"blur{s}"].append(_feat_test(real, simb, perms, int(rng.integers(2 ** 31)),
                                                           int(rng.integers(2 ** 31)))["p"])
                    one = [oneseed[i] for i in rng.choice(len(oneseed), K, replace=False)]
                    rows["oneseed"].append(_feat_test(real, one, perms, int(rng.integers(2 ** 31)),
                                                      int(rng.integers(2 ** 31)))["p"])
                if (r + 1) % 50 == 0:
                    progress(f"  G {G} K {K}: {r + 1} of {reps}, {time.time() - t0:.0f} s")
            p = np.array(rows["null"])
            res = {"G": G, "K": K, "false_fail": round(float((p <= ALPHA).mean()), 4),
                   "p_quartiles": [round(float(q), 4) for q in np.percentile(p, [25, 50, 75])],
                   "srs1_false_fail": round(float(np.mean([v == "FAIL" for v in rows["srs1"]])), 4),
                   "oneseed_fail": round(float((np.array(rows["oneseed"]) <= ALPHA).mean()), 4),
                   "power": {str(s): round(float((np.array(rows[f"blur{s}"]) <= ALPHA).mean()), 4)
                             for s in CAL_SIGMAS},
                   "p_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}
            out["by"][f"G{G}_K{K}"] = res
            progress(f"G {G} K {K}: false FAIL {res['false_fail']}, SRS-1 {res['srs1_false_fail']}, "
                     f"power {res['power']}, one-seed {res['oneseed_fail']}")
    out["metrics"] = summarize(out)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def summarize(cal):
    """The numbers the preregistered readout rule reads, from a calibration's per-cell results."""
    by = cal["by"]
    ff = [v["false_fail"] for v in by.values()]
    admit = []
    for G in sorted({v["G"] for v in by.values()}):
        cells = [v for v in by.values() if v["G"] == G]
        bal = [v for v in cells if v["K"] == G]
        if all(v["false_fail"] <= 0.08 for v in cells) and bal and bal[0]["power"].get("0.8", 0) >= 0.80:
            admit.append(G)
    g6 = [v for v in by.values() if v["G"] == min(v2["G"] for v2 in by.values())]
    g24 = [v for v in by.values() if v["G"] == max(v2["G"] for v2 in by.values()) and v["K"] == v["G"]]
    return {"false_fail_max": max(ff), "admit_groups": min(admit) if admit else None,
            "srs1_false_fail_g6_max": max(v["srs1_false_fail"] for v in g6),
            "blur08_power_gmax": g24[0]["power"].get("0.8") if g24 else None}


# ---------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.simperm", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rule", help="print the fixed settings")
    r.add_argument("--json", action="store_true")
    s = sub.add_parser("score", help="score a simulated set under the SRS-2 draft rule and write its record")
    s.add_argument("--reference", required=True, help="a reference npz (python -m kit.simscore reference R343.npz)")
    s.add_argument("--sim", required=True, help="npz of simulated tiles")
    s.add_argument("--key", default="image")
    s.add_argument("--n", type=int, default=ss.MIN_SIM_TILES, help="first N tiles (default SRS-1's 240)")
    s.add_argument("--generator", required=True)
    s.add_argument("--attempts", type=int, required=True)
    s.add_argument("--trained-on", nargs="*", default=[])
    s.add_argument("--device", default="cpu")
    s.add_argument("--smoke", action="store_true")
    s.add_argument("--steps", type=int, default=STEPS)
    s.add_argument("--perms", type=int, default=PERMS)
    s.add_argument("--out", required=True)
    c = sub.add_parser("check", help="recompute a record's p-value, gates and status; exit 1 on any problem")
    c.add_argument("record")
    c.add_argument("--json", action="store_true")
    k = sub.add_parser("calibrate", help="run the preregistered null calibration (feat critic, synthetic units)")
    k.add_argument("--out", required=True)
    k.add_argument("--reps", type=int, default=200)
    k.add_argument("--power-reps", type=int, default=100)
    k.add_argument("--perms", type=int, default=PERMS)
    k.add_argument("--pool", type=int, default=CAL_POOL)
    k.add_argument("--groups", type=int, nargs="*", default=list(CAL_GROUPS))
    k.add_argument("--workers", type=int, default=1)
    k.add_argument("--seed0", type=int, default=CAL_POOL_SEED0, help="first pool seed (development runs only)")
    k.add_argument("--oneseed-seed", type=int, default=CAL_ONESEED, help="one-seed sim seed (development only)")
    k.add_argument("--freeze", default=None, help="freeze id to write into the record (the frozen run only)")
    a = ap.parse_args(argv)
    if sys.stdout.isatty():
        try:
            from kit import termstyle
            termstyle.script()
        except Exception:
            pass
    if a.cmd == "rule":
        body = {"standard": STANDARD, "settings": SETTINGS, "admit_groups": ADMIT_GROUPS}
        print(json.dumps(body, indent=1, sort_keys=True) if a.json else
              "\n".join(f"{k}: {v}" for k, v in sorted(SETTINGS.items())))
        return 0
    if a.cmd == "score":
        ref = ss.load_reference(a.reference)
        tiles = ss.load_sim(a.sim, a.key, a.n)
        rec = score(ref, tiles, {"name": a.generator, "file": os.path.basename(a.sim), "key": a.key,
                                 "file_sha256": ss.file_sha256(a.sim)}, a.attempts, a.trained_on, a.device, a.steps,
                    a.smoke, a.perms)
        with open(a.out, "w") as f:
            json.dump(rec, f, indent=1, sort_keys=True)
        print(f"{STANDARD} {rec['status']}: p {rec['result']['p']}, T {rec['result']['t']}")
        print(rec["reason"])
        print(f"record {a.out}")
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
            print(f"{STANDARD} record {a.record}: {'OK' if not probs else 'PROBLEMS'} (status {rec.get('status')})")
            for x in probs:
                print(f"  {x}")
        return 1 if probs else 0
    if a.freeze and (a.seed0 != CAL_POOL_SEED0 or a.oneseed_seed != CAL_ONESEED):
        print("a frozen run uses the preregistered seeds", file=sys.stderr)
        return 2
    feats = calibration_features(a.pool, a.workers, seed0=a.seed0, oneseed_seed=a.oneseed_seed)
    res = calibrate(tuple(a.groups), reps=a.reps, power_reps=a.power_reps, perms=a.perms, pool=a.pool,
                    workers=a.workers, feats=feats)
    res["pool_seeds"] = [a.seed0, a.seed0 + a.pool - 1]
    res["oneseed_seed"] = a.oneseed_seed
    if a.freeze:
        res["freeze"] = a.freeze
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    print(json.dumps(res["metrics"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
