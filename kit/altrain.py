"""Active-learning training-run comparison: does fine-tuning on the tiles a label suggester picks beat random tiles?

A simulated labeling round with oracle labels. On one segment with real ink labels, a fixed spatial layout splits the
labeled area into test blocks (never trained on) and a pool of tiles. Each arm reveals the oracle labels of k pool
tiles only, chosen by its rule, and the same base reader is fine-tuned on them; every fine-tuned reader then maps the
test blocks forward and with reversed depth. The arms:

  SUGGEST    the top k pool tiles by kit labelsuggest's label-free ink-edge measure on the base readers' maps
  UNCERTAIN  the top k pool tiles by mean binary entropy of one reader's ink probability (uncertainty sampling)
  RANDOM     k pool tiles at random (several draws)
  SHUF       the top k of the SUGGEST tile scores shuffled across the pool (a control: it must equal RANDOM)

This module is the label-free layout and selection, the scoring from per-block score histograms, the paired
hierarchical bootstrap and the readout rule. It reads no CT and trains nothing: a GPU worker fine-tunes the base
reader per run and hands over each run's per-block histograms (runs/<id>.npz with arrays fwd and rev). numpy only.

    python -m kit altrain plan SUP.npy [--foot FOOT.npy] [--json]          the layout's counts (label-free)
    python -m kit altrain readout RESULTS_DIR [--json]                      per segment and budget, then the verdict

A suggested tile is a place to label, never a reading; every map is a model's output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

TILE = 64                      # pool tile side, map pixels
BLOCK = 256                    # test block side (a multiple of TILE)
PERIOD = 3                     # block (by, bx) is a test block when (by + bx) % PERIOD == 0
MIN_VALID = 0.5                # least supervised (and footprint) share of a pool tile
MIN_TEST_SUP = 0.25            # least supervised share of a test block
GUARD = 1                      # pool tiles within GUARD tiles (Chebyshev) of any pattern block are left out
BUDGETS = (0.05, 0.10, 0.20)   # share of the pool revealed
SEEDS = (0, 1, 2)              # training seeds of SUGGEST, UNCERTAIN and SHUF
RANDOM_DRAWS = 5               # RANDOM tile sets; draw d trains with seed SEEDS[d % 3]
SHUF_DRAWS = 3                 # SHUF permutations; draw d trains with seed SEEDS[d]
ARMS = ("SUGGEST", "UNCERTAIN", "RANDOM", "SHUF")
CUT = 0.5                      # kit labelsuggest's default ink probability cut for the edge measure
NBOOT = 2000
BOOT_SEED = 20261103
PICK_SEED = 20261104
LOWER_Q = 0.025                # the lower bound: 2.5th percentile (one-sided 97.5 %)
SHUF_ALPHA = 0.01              # SHUF minus RANDOM, pooled over budgets: its 99 % interval must hold 0
REV_MAX = 0.55                 # every arm's mean reverse-depth AUC at every budget at or below this
DISPLACE_PX = 32               # usable: the base reader's AUC with labels in place beats labels moved 32 px ...
DISPLACE_MIN = 0.05            # ... by at least this
MIN_POOL_TILES = 100
MIN_TEST_BLOCKS = 12
PASS_SEGMENTS = 2              # PASS: at least two counted segments ...
PASS_BUDGETS = 2               # ... each with SUGGEST minus RANDOM's lower bound above 0 at two or more budgets
BINS = 256                     # maps are scored as uint8 (0..255) probabilities
TEST_SEGMENTS = ("frag2", "frag3", "frag4")   # the fragment benchmark's segments; readout wants exactly these
BASE_KEYS = ("n_pool", "n_test_blocks", "auc_inplace", "auc_displaced", "plan_sha256")


class ALError(Exception):
    pass


def _np():
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover
        raise ALError("kit altrain needs numpy") from e
    return np


def constants():
    """The rule's constants, as one dict (hashed into every record)."""
    names = ("TILE", "BLOCK", "PERIOD", "MIN_VALID", "MIN_TEST_SUP", "GUARD", "BUDGETS", "SEEDS", "RANDOM_DRAWS",
             "SHUF_DRAWS", "ARMS", "CUT", "NBOOT", "BOOT_SEED", "PICK_SEED", "LOWER_Q", "SHUF_ALPHA", "REV_MAX",
             "DISPLACE_PX", "DISPLACE_MIN", "MIN_POOL_TILES", "MIN_TEST_BLOCKS", "PASS_SEGMENTS", "PASS_BUDGETS",
             "BINS", "TEST_SEGMENTS", "BASE_KEYS")
    g = globals()
    return {n: list(g[n]) if isinstance(g[n], tuple) else g[n] for n in names}


def constants_sha256():
    return hashlib.sha256(json.dumps(constants(), sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------- layout (label-free: the supervision mask only)

def _share(mask, side):
    """Share of True per side x side cell (partial last row and column dropped): (rows, cols) float array."""
    np = _np()
    H, W = mask.shape
    r, c = H // side, W // side
    m = mask[:r * side, :c * side].reshape(r, side, c, side)
    return m.mean(axis=(1, 3)) if r and c else np.zeros((r, c))


def layout(sup, foot=None):
    """The fixed spatial layout of one segment from its supervision mask (and CT footprint).

    Test blocks: BLOCK px blocks with (by + bx) % PERIOD == 0 and at least MIN_TEST_SUP supervised. Pool: TILE px
    tiles with at least MIN_VALID supervised and footprint, outside every pattern block and more than GUARD tiles
    from one (pattern blocks count whether or not they are test blocks, so no pool label touches a test block).
    Returns dict(shape, test_blocks [(y, x)], pool [(y, x)] in pixels, test_mask)."""
    np = _np()
    sup = np.asarray(sup).astype(bool)
    if sup.ndim != 2:
        raise ALError("the supervision mask must be 2D")
    foot = sup if foot is None else np.asarray(foot).astype(bool)
    if foot.shape != sup.shape:
        raise ALError(f"footprint {foot.shape} and supervision {sup.shape} differ")
    H, W = sup.shape
    k = BLOCK // TILE
    bshare = _share(sup, BLOCK)
    br, bc = bshare.shape
    by, bx = np.mgrid[0:br, 0:bc]
    pattern = (by + bx) % PERIOD == 0
    test = pattern & (bshare >= MIN_TEST_SUP)
    tr, tc = H // TILE, W // TILE
    patt_t = np.zeros((tr, tc), bool)
    patt_t[:br * k, :bc * k] = np.repeat(np.repeat(pattern, k, 0), k, 1)
    near = patt_t.copy()
    for dy in range(-GUARD, GUARD + 1):
        for dx in range(-GUARD, GUARD + 1):
            sh = np.zeros_like(patt_t)
            ys = slice(max(dy, 0), tr + min(dy, 0)); yd = slice(max(-dy, 0), tr + min(-dy, 0))
            xs = slice(max(dx, 0), tc + min(dx, 0)); xd = slice(max(-dx, 0), tc + min(-dx, 0))
            sh[yd, xd] = patt_t[ys, xs]
            near |= sh
    ok = (_share(sup, TILE) >= MIN_VALID) & (_share(foot, TILE) >= MIN_VALID) & ~near
    pool = [(int(y) * TILE, int(x) * TILE) for y, x in zip(*np.nonzero(ok))]
    blocks = [(int(y) * BLOCK, int(x) * BLOCK) for y, x in zip(*np.nonzero(test))]
    tmask = np.zeros((H, W), bool)
    for y, x in blocks:
        tmask[y:y + BLOCK, x:x + BLOCK] = True
    return {"shape": [H, W], "test_blocks": blocks, "pool": pool, "test_mask": tmask & sup}


def pool_mask(shape, tiles):
    np = _np()
    m = np.zeros(tuple(shape), bool)
    for y, x in tiles:
        m[y:y + TILE, x:x + TILE] = True
    return m


def disjoint(lay):
    """True when no pool tile pixel lies in, or within GUARD tiles of, a test block (a checkable invariant)."""
    g = GUARD * TILE
    for ty, tx in lay["pool"]:
        for by, bx in lay["test_blocks"]:
            if ty < by + BLOCK + g and ty + TILE > by - g and tx < bx + BLOCK + g and tx + TILE > bx - g:
                return False
    return True


# ---------------------------------------------------------------- selection measures (label-free)

def edge_map(maps, valid, cut=CUT):
    """kit labelsuggest's `edge` measure: 1 where the committee call (mean probability at or above cut) differs
    from a valid 4-neighbor, else 0. maps: probabilities 0..1 on one grid."""
    np = _np()
    valid = np.asarray(valid).astype(bool)
    call = np.mean(np.stack([np.asarray(m, np.float32) for m in maps]), axis=0) >= float(cut)
    e = np.zeros(call.shape, bool)
    d = (call[:-1, :] != call[1:, :]) & valid[:-1, :] & valid[1:, :]
    e[:-1, :] |= d
    e[1:, :] |= d
    d = (call[:, :-1] != call[:, 1:]) & valid[:, :-1] & valid[:, 1:]
    e[:, :-1] |= d
    e[:, 1:] |= d
    e &= valid
    return e.astype(np.float32)


def entropy_map(p, eps=1e-6):
    """Binary entropy (nats) of an ink probability map."""
    np = _np()
    q = np.clip(np.asarray(p, np.float64), eps, 1 - eps)
    return (-(q * np.log(q) + (1 - q) * np.log(1 - q))).astype(np.float32)


def tile_means(arr, valid, tiles):
    """Mean of arr over each tile's valid pixels (0 for a tile with none)."""
    np = _np()
    out = np.zeros(len(tiles), np.float64)
    for i, (y, x) in enumerate(tiles):
        v = valid[y:y + TILE, x:x + TILE]
        if v.any():
            out[i] = float(arr[y:y + TILE, x:x + TILE][v].mean())
    return out


def k_of(n_pool, frac):
    return max(1, int(round(frac * n_pool)))


def top_k(scores, k, rng):
    """Indices of the k highest scores, ties broken at random by rng (a fixed order would pick by position)."""
    np = _np()
    scores = np.asarray(scores, np.float64)
    order = np.lexsort((rng.random(len(scores)), -scores))
    return sorted(int(i) for i in order[:k])


def selections(edge_scores, ent_scores, budgets=BUDGETS, seed=PICK_SEED):
    """Per budget: SUGGEST and UNCERTAIN (one tile set each), RANDOM (RANDOM_DRAWS sets), SHUF (SHUF_DRAWS sets),
    as lists of pool indices. Fixed by seed; reads no label."""
    np = _np()
    edge_scores, ent_scores = np.asarray(edge_scores), np.asarray(ent_scores)
    n = len(edge_scores)
    if len(ent_scores) != n:
        raise ALError("edge and entropy scores differ in length")
    out = {}
    for bi, frac in enumerate(budgets):
        k = k_of(n, frac)
        base = seed + 1000 * bi
        rec = {"frac": frac, "k": k,
               "SUGGEST": [top_k(edge_scores, k, np.random.default_rng(base + 1))],
               "UNCERTAIN": [top_k(ent_scores, k, np.random.default_rng(base + 2))],
               "RANDOM": [sorted(int(i) for i in np.random.default_rng(base + 100 + d).choice(n, k, replace=False))
                          for d in range(RANDOM_DRAWS)],
               "SHUF": []}
        for d in range(SHUF_DRAWS):
            r = np.random.default_rng(base + 200 + d)
            rec["SHUF"].append(top_k(r.permutation(edge_scores), k, r))
        out[f"{frac:.2f}"] = rec
    return out


def runs(sel):
    """Every fine-tune of a segment: dict(id, budget, arm, draw, seed, tiles) from selections()."""
    out = []
    for b, rec in sel.items():
        for arm in ARMS:
            sets = rec[arm]
            if arm in ("SUGGEST", "UNCERTAIN"):
                pairs = [(0, s) for s in SEEDS]
            elif arm == "RANDOM":
                pairs = [(d, SEEDS[d % len(SEEDS)]) for d in range(RANDOM_DRAWS)]
            else:
                pairs = [(d, SEEDS[d]) for d in range(SHUF_DRAWS)]
            for d, s in pairs:
                out.append({"id": f"b{b}-{arm}-d{d}-s{s}", "budget": b, "arm": arm, "draw": d, "seed": s,
                            "tiles": sets[d]})
    return out


# ---------------------------------------------------------------- scoring

def to_u8(p):
    np = _np()
    return np.clip(np.rint(np.asarray(p, np.float64) * 255.0), 0, 255).astype(np.uint8)


def block_hists(prob_u8, ink, sup, blocks, side=BLOCK):
    """(n_blocks, 2, BINS) int64: per test block, the counts of background (0) and ink (1) supervised pixels per
    uint8 score."""
    np = _np()
    out = np.zeros((len(blocks), 2, BINS), np.int64)
    for i, (y, x) in enumerate(blocks):
        s = sup[y:y + side, x:x + side].astype(bool)
        v = prob_u8[y:y + side, x:x + side][s].astype(np.int64)
        k = ink[y:y + side, x:x + side][s].astype(bool)
        out[i, 0] = np.bincount(v[~k], minlength=BINS)
        out[i, 1] = np.bincount(v[k], minlength=BINS)
    return out


def auc_counts(c):
    """AUC from counts (..., 2, BINS): P(ink score > background score) + half the ties; nan without both classes."""
    np = _np()
    c = np.asarray(c, np.float64)
    neg, pos = c[..., 0, :], c[..., 1, :]
    below = np.cumsum(neg, axis=-1) - neg
    num = (pos * (below + 0.5 * neg)).sum(axis=-1)
    den = pos.sum(axis=-1) * neg.sum(axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def auc_direct(score, ink, mask):
    """Rank AUC on the masked pixels (ties half): the reference auc_counts must equal on uint8 scores."""
    np = _np()
    s = np.asarray(score)[mask].astype(np.float64)
    k = np.asarray(ink)[mask].astype(bool)
    npos, nneg = int(k.sum()), int((~k).sum())
    if not npos or not nneg:
        return float("nan")
    _, inv, cnt = np.unique(s, return_inverse=True, return_counts=True)
    before = np.cumsum(cnt) - cnt
    ranks = before[inv] + (cnt[inv] + 1) / 2.0
    return float((ranks[k].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))


def _weights(n_blocks, nboot, rng):
    np = _np()
    idx = rng.integers(0, n_blocks, size=(nboot, n_blocks))
    w = np.zeros((nboot, n_blocks), np.float64)
    np.add.at(w, (np.repeat(np.arange(nboot), n_blocks), idx.ravel()), 1.0)
    return w


def boot_arm_means(hists, nboot=NBOOT, seed=BOOT_SEED):
    """Paired hierarchical bootstrap. hists: {arm: (n_runs, n_blocks, 2, BINS)} on the same test blocks. Each draw
    resamples the test blocks (shared by every arm) and, within each arm, its runs; returns {arm: (nboot,) mean
    AUC} and the point estimates {arm: mean over runs of each run's AUC on all blocks}."""
    np = _np()
    rng = np.random.default_rng(seed)
    nb = {h.shape[1] for h in hists.values()}
    if len(nb) != 1:
        raise ALError("arms were scored on different test blocks")
    n_blocks = nb.pop()
    w = _weights(n_blocks, nboot, rng)
    boot, point = {}, {}
    for arm in sorted(hists):
        h = np.asarray(hists[arm], np.float64)
        n = h.shape[0]
        flat = h.reshape(n, n_blocks, 2 * BINS)
        per = np.stack([auc_counts((w @ flat[r]).reshape(nboot, 2, BINS)) for r in range(n)], axis=1)
        pick = rng.integers(0, n, size=(nboot, n))
        boot[arm] = np.take_along_axis(per, pick, axis=1).mean(axis=1)
        point[arm] = float(np.mean(auc_counts(h.sum(axis=1))))
    return boot, point


def diff(boot, point, a, b, lower_q=LOWER_Q):
    np = _np()
    d = boot[a] - boot[b]
    return {"est": round(point[a] - point[b], 6), "lower": round(float(np.quantile(d, lower_q)), 6),
            "upper": round(float(np.quantile(d, 1 - lower_q)), 6)}


def segment_readout(seg, fwd, rev, base=None, expected=None, nboot=NBOOT, seed=BOOT_SEED, extra=None):
    """One segment. fwd, rev: {run_id: (n_blocks, 2, BINS)} forward and reverse-depth histograms; base: the worker's
    base record (BASE_KEYS); expected: the run ids the plan made; extra: {run_id: {revealed_px, revealed_ink_px}}
    (reported only). Returns per budget the arm means and differences, the controls and whether the segment counts.
    A missing run or a missing base record makes the segment INCOMPLETE (technical), never COUNTED."""
    np = _np()
    why = []
    expected = sorted(expected) if expected is not None else sorted(fwd)
    missing = [r for r in expected if r not in fwd or r not in rev]
    base = base or {}
    nobase = [k for k in BASE_KEYS if base.get(k) is None]
    if missing or nobase:
        return {"segment": seg, "state": "INCOMPLETE", "missing": missing, "missing_base": nobase, "counted": False}
    if base["n_pool"] < MIN_POOL_TILES:
        why.append(f"pool {base['n_pool']} tiles < {MIN_POOL_TILES}")
    if base["n_test_blocks"] < MIN_TEST_BLOCKS:
        why.append(f"{base['n_test_blocks']} test blocks < {MIN_TEST_BLOCKS}")
    if not base["auc_inplace"] - base["auc_displaced"] >= DISPLACE_MIN:
        why.append(f"labels do not track the CT: base AUC {base['auc_inplace']:.4f} in place against "
                   f"{base['auc_displaced']:.4f} moved {DISPLACE_PX} px")
    budgets = sorted({r.split("-")[0][1:] for r in expected})
    out = {"segment": seg, "budgets": {}}
    shuf_boot, shuf_point = [], []
    for b in budgets:
        ids = {arm: sorted(r for r in expected if r.startswith(f"b{b}-{arm}-")) for arm in ARMS}
        hf = {arm: np.stack([fwd[r] for r in ids[arm]]) for arm in ARMS}
        hr = {arm: np.stack([rev[r] for r in ids[arm]]) for arm in ARMS}
        boot, point = boot_arm_means(hf, nboot, seed)
        rboot, rpoint = boot_arm_means(hr, nboot, seed)      # same seed: the same block and run draws (paired)
        dd = (boot["SUGGEST"] - boot["RANDOM"]) - (rboot["SUGGEST"] - rboot["RANDOM"])
        rec = {"auc": {a: round(point[a], 6) for a in ARMS}, "rev_auc": {a: round(rpoint[a], 6) for a in ARMS},
               "runs": {a: len(ids[a]) for a in ARMS},
               "SUGGEST-RANDOM": diff(boot, point, "SUGGEST", "RANDOM"),
               "SUGGEST-RANDOM_reverse": diff(rboot, rpoint, "SUGGEST", "RANDOM"),
               "forward_minus_reverse_gain": {
                   "est": round((point["SUGGEST"] - point["RANDOM"]) - (rpoint["SUGGEST"] - rpoint["RANDOM"]), 6),
                   "lower": round(float(np.quantile(dd, LOWER_Q)), 6)},
               "UNCERTAIN-RANDOM": diff(boot, point, "UNCERTAIN", "RANDOM"),
               "SUGGEST-UNCERTAIN": diff(boot, point, "SUGGEST", "UNCERTAIN"),
               "SHUF-RANDOM": diff(boot, point, "SHUF", "RANDOM")}
        # a budget counts only when the gain is above 0 and larger forward than with reversed depth (review fix 5)
        rec["suggest_beats_random"] = (rec["SUGGEST-RANDOM"]["lower"] > 0
                                       and rec["forward_minus_reverse_gain"]["lower"] > 0)
        if extra:
            ink = {a: float(np.mean([extra[r]["revealed_ink_px"] for r in ids[a]])) for a in ARMS
                   if all(r in extra for r in ids[a])}
            rec["revealed_ink_px"] = {a: round(v, 1) for a, v in ink.items()}
            if ink.get("RANDOM"):
                rec["revealed_ink_ratio_suggest_random"] = round(ink.get("SUGGEST", 0) / ink["RANDOM"], 4)
        for a in ARMS:
            if not rpoint[a] <= REV_MAX:
                why.append(f"budget {b}: {a} mean reverse-depth AUC {rpoint[a]:.4f} > {REV_MAX}")
        shuf_boot.append(boot["SHUF"] - boot["RANDOM"])
        shuf_point.append(point["SHUF"] - point["RANDOM"])
        out["budgets"][b] = rec
    pooled = np.mean(np.stack(shuf_boot), axis=0)
    lo, hi = (float(np.quantile(pooled, q)) for q in (SHUF_ALPHA / 2, 1 - SHUF_ALPHA / 2))
    out["shuffle_control"] = {"est": round(float(np.mean(shuf_point)), 6), "lo": round(lo, 6), "hi": round(hi, 6),
                              "holds": lo <= 0 <= hi}
    if not out["shuffle_control"]["holds"]:
        why.append(f"shuffled suggestions differ from RANDOM (pooled {SHUF_ALPHA:.0%} interval {lo:.4f} to {hi:.4f})")
    out["n_budgets_beating"] = sum(r["suggest_beats_random"] for r in out["budgets"].values())
    out["void_why"] = why
    out["counted"] = not why
    out["state"] = "COUNTED" if not why else "VOID"
    out["passes"] = out["counted"] and out["n_budgets_beating"] >= PASS_BUDGETS
    return out


def verdict(segments):
    """PASS: at least PASS_SEGMENTS counted segments (any of the test segments) each with SUGGEST minus RANDOM's
    lower bound above 0, and its forward gain larger than its reverse-depth gain (lower bound above 0), at
    PASS_BUDGETS or more budgets. FAIL: at least PASS_SEGMENTS counted, fewer pass. VOID:
    fewer than PASS_SEGMENTS counted. INCOMPLETE while any segment has missing runs (a technical state)."""
    if any(s.get("state") == "INCOMPLETE" for s in segments):
        return {"verdict": "INCOMPLETE", "counted": [], "passing": []}
    counted = [s["segment"] for s in segments if s.get("counted")]
    passing = [s["segment"] for s in segments if s.get("passes")]
    if len(counted) < PASS_SEGMENTS:
        v = "VOID"
    elif len(passing) >= PASS_SEGMENTS:
        v = "PASS"
    else:
        v = "FAIL"
    return {"verdict": v, "counted": counted, "passing": passing}


# ---------------------------------------------------------------- files

def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_results(root, segments=TEST_SEGMENTS):
    """A results folder: one subfolder per segment with plan.json, base.json and runs/<id>.npz (fwd, rev, and
    optionally revealed_px, revealed_ink_px). Exactly `segments`: a missing one is returned with no plan (the readout
    makes it INCOMPLETE); a folder of another segment, a duplicate, or a plan whose sha256 differs from base.json's
    plan_sha256 is refused."""
    np = _np()
    root = Path(root)
    found = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "plan.json").is_file()):
        plan = json.loads((d / "plan.json").read_text())
        name = plan.get("segment", d.name)
        if name not in segments:
            raise ALError(f"{d}: segment {name!r} is not one of {list(segments)}")
        if name in found:
            raise ALError(f"{d}: a second folder for segment {name!r}")
        base = json.loads((d / "base.json").read_text()) if (d / "base.json").is_file() else {}
        if base.get("plan_sha256") and base["plan_sha256"] != _sha256(d / "plan.json"):
            raise ALError(f"{d}: plan.json differs from the plan base.json was made with")
        fwd, rev, extra = {}, {}, {}
        for f in sorted((d / "runs").glob("*.npz")) if (d / "runs").is_dir() else []:
            if f.name.endswith(".part.npz"):
                continue
            z = np.load(f)
            fwd[f.stem], rev[f.stem] = z["fwd"], z["rev"]
            if "revealed_ink_px" in z.files:
                extra[f.stem] = {"revealed_px": int(z["revealed_px"]), "revealed_ink_px": int(z["revealed_ink_px"])}
        found[name] = (name, fwd, rev, base, [r["id"] for r in plan["runs"]], extra)
    return [found.get(s, (s, None, None, None, None, None)) for s in segments]


def readout(root, nboot=NBOOT, segments=TEST_SEGMENTS):
    segs = []
    for s, f, r, b, e, x in load_results(root, segments):
        if f is None:
            segs.append({"segment": s, "state": "INCOMPLETE", "missing": ["(no records folder)"], "counted": False})
        else:
            segs.append(segment_readout(s, f, r, b, e, nboot, extra=x))
    return {"kind": "kit-altrain-readout", "constants_sha256": constants_sha256(), "segments": segs,
            "segments_expected": list(segments), "nboot": nboot, "nboot_frozen": nboot == NBOOT,
            "frozen_segment_set": tuple(segments) == TEST_SEGMENTS, **verdict(segs)}


def cmd_plan(a):
    np = _np()
    sup = np.load(a.sup)
    foot = np.load(a.foot) if a.foot else None
    lay = layout(sup, foot)
    rec = {"shape": lay["shape"], "pool_tiles": len(lay["pool"]), "test_blocks": len(lay["test_blocks"]),
           "test_pixels": int(lay["test_mask"].sum()), "disjoint": disjoint(lay),
           "k": {f"{f:.2f}": k_of(len(lay["pool"]), f) for f in BUDGETS}, "constants_sha256": constants_sha256()}
    print(json.dumps(rec, indent=1) if a.json else
          f"{rec['pool_tiles']} pool tiles, {rec['test_blocks']} test blocks, budgets {rec['k']}")
    return 0


def cmd_readout(a):
    rec = readout(a.root, a.nboot, tuple(a.segments))
    if a.json:
        print(json.dumps(rec, indent=1))
    else:
        for s in rec["segments"]:
            if s["state"] == "INCOMPLETE":
                print(f"{s['segment']}: INCOMPLETE ({len(s['missing'])} runs missing; base keys missing: "
                      f"{s.get('missing_base') or 'none'})")
                continue
            print(f"{s['segment']}: {s['state']}" + (f" ({'; '.join(s['void_why'])})" if s["void_why"] else ""))
            for b, r in s["budgets"].items():
                d = r["SUGGEST-RANDOM"]
                print(f"  budget {b}: SUGGEST {r['auc']['SUGGEST']:.4f} RANDOM {r['auc']['RANDOM']:.4f} "
                      f"diff {d['est']:+.4f} (lower {d['lower']:+.4f})")
        print(f"verdict {rec['verdict']}: counted {rec['counted']}, passing {rec['passing']}")
        if not (rec["nboot_frozen"] and rec["frozen_segment_set"]):
            print("note: not the preregistered readout (non-default --nboot or --segments)")
    return 0


def build_parser(p):
    sub = p.add_subparsers(dest="altrain_cmd", required=True)
    q = sub.add_parser("plan", help="the layout's counts from a supervision mask (label-free)")
    q.add_argument("sup", help="supervision mask .npy (nonzero = labeled)")
    q.add_argument("--foot", help="CT footprint mask .npy (default: the supervision mask)")
    q.add_argument("--json", action="store_true")
    q = sub.add_parser("readout", help="per segment and budget, the controls and the verdict")
    q.add_argument("root", help="a results folder: one subfolder per segment (plan.json, base.json, runs/*.npz)")
    q.add_argument("--nboot", type=int, default=NBOOT, help="bootstrap draws (the preregistered readout uses the default)")
    q.add_argument("--segments", nargs="+", default=list(TEST_SEGMENTS),
                   help="the segments the results folder must hold (default: the fragment benchmark's three)")
    q.add_argument("--json", action="store_true")


def cmd_altrain(a):
    try:
        return {"plan": cmd_plan, "readout": cmd_readout}[a.altrain_cmd](a)
    except ALError as e:
        print(f"altrain: {e}", file=sys.stderr)
        return 2


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit altrain", description=__doc__.split("\n\n")[0])
    build_parser(p)
    return cmd_altrain(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
