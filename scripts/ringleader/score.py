"""Score Ringleader labels against published hand-traced windings, seam-free (wtruth). Model output.

    python3 -m kit hopbench refs                      # once: PHerc0139 windings w023 to w040 and their manifest
    python3 scripts/ringleader/score.py work/ringleader/run1 [--every 3] [--windings w023,w024,...]

Reads RUN/zNNNNN.npz (from run_slices.py, slab3d.py or fitlabel.py), caches the truth per slice and reference set
under --truth, and writes RUN/score.json. Metrics:
  on_winding  E0: the share of matched sheet pixels whose label minus true turn equals the slice's most common
              offset (pooled over slices, weighted by matched labeled pixels)
  pair        share of random pairs of matched pixels (different turns) whose label difference is right
  step        radial samples with both ends matched: label difference equals turn difference
  switches    along each reference winding ordered by angle, changes of label minus turn
Arms: global, naive (if saved), and three controls that must score badly: planted (+1 on the sector holding
25 % of scored pixels; must drop E0 by at least 0.8 x that share), shift (+1 outside the median radius in a
90 degree sector; must drop by 0.8 x its share) and jitter (a random -1, 0 or +1 per piece; at most 0.4).
Truth turns use the references' own hand (wtruth.Truth.hand); labels made with the other hand are converted and
then score as badly as they are. Strata (contact within 8 voxels of another winding, and free) are scored at the
slice's global offset.
"""

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent))
import rlcommon  # noqa: E402
import wtruth  # noqa: E402

WORK = Path("work") / "ringleader"
_TRUTH = None


def load_references(refs_dir, windings=None):
    """(manifest, [Ref]) from a kit.sheetrefs reference folder (python -m kit hopbench refs), optionally only the
    named windings."""
    from kit import sheetrefs as sr
    man, refs = sr.load_refs(refs_dir)
    if windings:
        want = set(windings)
        missing = want - {r.name for r in refs}
        if missing:
            raise SystemExit(f"windings not in {refs_dir}: {sorted(missing)}")
        refs = [r for r in refs if r.name in want]
    if not refs:
        raise SystemExit(f"no references in {refs_dir}")
    return man, refs


def truth_dir(a):
    """The truth cache folder for this reference set and axis: --truth / a short digest of both."""
    man, refs = load_references(a.refs, a.windings)
    key = json.dumps({"manifest": man.get("digest"), "windings": sorted(r.name for r in refs),
                      "umbilicus": a.umbilicus, "v": 1}, sort_keys=True)
    return Path(a.truth) / hashlib.sha256(key.encode()).hexdigest()[:12]


def truth_obj(a):
    global _TRUTH
    if _TRUTH is None:
        _, refs = load_references(a.refs, a.windings)
        _TRUTH = wtruth.Truth(refs, rlcommon.load_axis(a.cache, a.umbilicus))
    return _TRUTH


def truth_hand(tdir, a):
    """The references' own hand (wtruth.Truth.hand), cached in tdir/hand.json."""
    f = Path(tdir) / "hand.json"
    if f.is_file():
        return int(json.loads(f.read_text())["hand"])
    T = truth_obj(a)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"hand": T.hand, "outer_votes": T.hand_votes}))
    return int(T.hand)


def cached_truth(z, ys, xs, tdir, a):
    """rank, alpha, ambiguous (two windings within 4 voxels) and contact (two within 8) for pixels (ys, xs) of
    slice z, computed once per pixel."""
    f = Path(tdir) / f"z{z:05d}-v4.npz"
    key = ys.astype(np.int64) * 10000 + xs
    names = ("rank", "alpha", "amb", "contact")
    have = {"key": np.zeros(0, np.int64), "rank": np.zeros(0, np.int64), "alpha": np.zeros(0),
            "amb": np.zeros(0, bool), "contact": np.zeros(0, bool)}
    if f.is_file():
        d = np.load(f)
        have = {k: d[k] for k in have}
    hk = have["key"]
    pos = np.clip(np.searchsorted(hk, key), 0, max(len(hk) - 1, 0))
    found = (hk[pos] == key) if len(hk) else np.zeros(len(key), bool)
    miss = np.flatnonzero(~found)
    if len(miss):
        T = truth_obj(a)
        mk = np.unique(key[miss])
        P = np.stack([mk % 10000, mk // 10000, np.full(len(mk), z)], 1).astype(float)
        t0 = time.time()
        new = dict(zip(names, T.label(P, amb=True)))
        print(f"z{z}: truth for {len(P)} new pixels in {time.time() - t0:.0f} s", flush=True)
        allk = np.concatenate([hk, mk])
        o = np.argsort(allk)
        have = {"key": allk[o], **{k: np.concatenate([have[k], new[k]])[o] for k in names}}
        f.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(f, **have)
        pos = np.searchsorted(have["key"], key)
    return tuple(have[k][pos] for k in names)


def offset_share(e):
    e = e[np.isfinite(e)]
    if not len(e):
        return None, None
    v, c = np.unique(e, return_counts=True)
    return float(c.max() / len(e)), int(v[c.argmax()])


def score_labels(L, turn, th, rows_a, rows_b, rng, n_pairs=200000):
    m = np.isfinite(L) & np.isfinite(turn)
    e = (L - turn)[m]
    on, off = offset_share(e)
    res = {"matched": int(np.isfinite(turn).sum()), "labelled_matched": int(m.sum()), "on_winding": on,
           "offset": off}
    if on is not None:
        res["off_by"] = {str(int(k)): int(v) for k, v in zip(*np.unique(e - off, return_counts=True)) if k != 0}
    idx = np.flatnonzero(m)
    if len(idx) > 1:
        i, j = rng.choice(idx, n_pairs), rng.choice(idx, n_pairs)
        k = turn[i] != turn[j]
        res["pair"] = float(((L[i] - L[j]) == (turn[i] - turn[j]))[k].mean())
    ok = np.isfinite(L[rows_a]) & np.isfinite(L[rows_b]) & np.isfinite(turn[rows_a]) & np.isfinite(turn[rows_b])
    dl = (L[rows_b] - L[rows_a])[ok]
    dt = (turn[rows_b] - turn[rows_a])[ok]
    res["steps"] = int(ok.sum())
    if ok.sum():
        res["step_acc"] = float((dl == dt).mean())
        res["step_err"] = {str(int(k)): int(v) for k, v in zip(*np.unique(dt - dl, return_counts=True)) if k != 0}
        res["step_true_diff"] = {str(int(k)): int(v) for k, v in zip(*np.unique(dt, return_counts=True))}
    # switches along each reference turn (by angle)
    sw = 0
    for t in np.unique(turn[m]):
        s = np.flatnonzero(m & (turn == t))
        if len(s) < 2:
            continue
        o = s[np.argsort(th[s])]
        sw += int((np.diff(L[o]) != 0).sum())
    res["switches"] = sw
    return res


def main(argv=None):
    from kit import sheetrefs as sr
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="a folder of zNNNNN.npz label files, or a folder of such folders")
    ap.add_argument("--every", type=int, default=3, help="score every Nth skeleton pixel (default 3)")
    ap.add_argument("--refs", default=str(sr.DEFAULT_REFS), help="reference folder (default %(default)s)")
    ap.add_argument("--windings", default=None, help="comma-separated winding names to use (default: all)")
    ap.add_argument("--cache", default=str(WORK / "cache"), help="umbilicus download cache (default %(default)s)")
    ap.add_argument("--umbilicus", default=None, help="umbilicus JSON in the slices' frame (default PHerc0139's)")
    ap.add_argument("--truth", default=str(WORK / "truth"), help="truth cache root (default %(default)s)")
    ap.add_argument("--exclude-z", default=None, help="z ranges never to score, lo:hi,lo:hi or a file of them")
    ap.add_argument("--clear", action="store_true", help="leave out pixels where two windings lie within the "
                    "matching distance (pressed closer than the truth can tell apart)")
    a = ap.parse_args(argv)
    a.windings = [w.strip() for w in a.windings.split(",") if w.strip()] if a.windings else None
    a.exclude = rlcommon.parse_ranges(a.exclude_z)
    a.tdir = truth_dir(a)
    run = Path(a.run)
    if not list(run.glob("z*.npz")):
        for sub in sorted(x for x in run.iterdir() if x.is_dir() and list(x.glob("z*.npz"))):
            print(f"== {sub.name}", flush=True)
            score_run(sub, a)
        return
    score_run(run, a)


PX_MM = 0.009362          # PHerc0139 frame 20250728140407 voxel size, for switches per mm


def planted(L, th, turn_s, share=0.25):
    """+1 on the sector theta' < phi holding `share` of the scored, labeled, matched pixels (calibrated control:
    it must lower on_winding by at least 0.8 x share x the arm's on_winding)."""
    m = np.isfinite(L) & np.isfinite(turn_s)
    phi = float(np.quantile(th[m], share)) if m.any() else 0.0
    out = L.copy()
    out[th < phi] += 1
    return out, phi


def score_run(run, a):
    T_names = sorted(r.name for r in load_references(a.refs, a.windings)[1])
    out = {"truth": "seam-free turns (wtruth), windings ranked by number; offsets over 2 voxels toward a winding "
                    "number not loaded are unknown", "windings": T_names, "slices": {}}
    for f in sorted(run.glob("z*.npz")):
        z = int(f.stem[1:])
        rlcommon.check_z([z], a.exclude)
        d = np.load(f)
        ys, xs, L, th, hand = d["ys"], d["xs"], d["label"], d["theta_p"], int(d["hand"])
        rows = d["rows"]
        n = len(ys)
        ra = rows[:, 0].astype(int) if len(rows) else np.zeros(0, int)
        rb = rows[:, 1].astype(int) if len(rows) else np.zeros(0, int)
        samp = np.arange(0, n, a.every)
        need = np.unique(np.concatenate([samp, ra, rb]))
        rk, al, am, ct = cached_truth(z, ys[need], xs[need], a.tdir, a)
        th_hand = truth_hand(a.tdir, a)
        th_t = th if hand == th_hand else np.where(th > 0, 2 * math.pi - th, 0.0)    # theta' in the truth's hand
        turn = np.full(n, np.nan)
        tt, resid = wtruth.turns(rk, al, th_t[need], th_hand)
        turn[need] = tt
        ambig = np.zeros(n, bool)
        ambig[need] = am
        contact = np.zeros(n, bool)
        contact[need] = ct
        if a.clear:
            turn[ambig] = np.nan
        scored = np.zeros(n, bool)
        scored[samp] = True
        turn_s = np.where(scored, turn, np.nan)
        rng = np.random.default_rng(z)
        mt = rk >= 0
        rec = {"z": z, "hand": hand, "truth_hand": th_hand, "ambiguous_share": float(am[mt].mean()) if mt.any() else None,
               "contact_share": float(ct[mt].mean()) if mt.any() else None,
               "turn_resid_p99": float(np.nanpercentile(resid, 99)) if np.isfinite(resid).any() else None,
               "arms": {}, "strata": {}}

        def arm(Lx):
            r = score_labels(Lx, turn_s, th, ra, rb, rng)
            g = score_labels(Lx, turn, th, ra, rb, rng, n_pairs=2)     # radial steps use all matched row ends
            for k in ("steps", "step_acc", "step_err", "step_true_diff"):
                if k in g:
                    r[k] = g[k]
            nm = int((np.isfinite(Lx) & np.isfinite(turn_s)).sum())
            r["switches_per_mm"] = r["switches"] / (a.every * nm * PX_MM) if nm else None
            return r
        rec["arms"]["global"] = arm(L)
        if "naive" in d.files:
            rec["arms"]["naive"] = arm(d["naive"])
        ident = arm(turn.copy())             # the truth against itself: a sanity check that cannot fail, not a control
        rec["sanity_truth_is_1"] = ident["on_winding"] == 1.0 and ident["switches"] == 0
        pl, phi = planted(L, th, turn_s)
        rec["arms"]["planted_control"] = arm(pl) | {"phi_deg": round(math.degrees(phi), 1), "share": 0.25}
        r_ = d["r"]
        rmed = float(np.nanmedian(r_[np.isfinite(turn_s)]))
        sh = L.copy()
        shm = (th < math.pi / 2) & (r_ > rmed)
        sh[shm] += 1
        ms = np.isfinite(L) & np.isfinite(turn_s)
        shift_share = float(shm[ms].mean()) if ms.any() else 0.0
        rec["arms"]["shift_control"] = arm(sh) | {"share": round(shift_share, 4)}
        pid = d["pid"]
        # one random -1, 0 or +1 per piece (per chain of pieces left too few independent draws: noise, 15 Oct)
        jit = L + np.where(pid >= 0, rng.integers(-1, 2, pid.max() + 1)[np.maximum(pid, 0)], 0)
        rec["arms"]["jitter_control"] = arm(jit)
        # strata of the global arm: pixels with another winding within 8 voxels, and the rest
        goff = rec["arms"]["global"].get("offset")
        for name, msk in (("contact", contact), ("free", ~contact)):
            Ls = np.where(msk, L, np.nan)
            rs = score_labels(Ls, np.where(msk, turn_s, np.nan), th, ra, rb, rng, n_pairs=50000)
            okr = msk[ra] if len(ra) else np.zeros(0, bool)
            g = score_labels(L, np.where(msk, turn, np.nan), th, ra[okr], rb[okr], rng, n_pairs=2)
            mm = np.isfinite(Ls) & np.isfinite(turn_s)
            on_g = float(((Ls - turn_s)[mm] == goff).mean()) if mm.any() and goff is not None else None
            # on_winding at the slice's global offset; the stratum's own modal offset only as extra information
            rec["strata"][name] = {"on_winding": on_g, "own_offset": rs.get("offset"),
                                   "own_offset_on_winding": rs.get("on_winding"),
                                   "labelled_matched": rs["labelled_matched"], "step_acc": g.get("step_acc"),
                                   "steps": g.get("steps")}
        e0 = rec["arms"]["global"]["on_winding"] or 0.0
        chk = {"planted_drops": (e0 - (rec["arms"]["planted_control"]["on_winding"] or 0)) >= 0.8 * 0.25 * e0,
               "shift_drops": (e0 - (rec["arms"]["shift_control"]["on_winding"] or 0)) >= 0.8 * shift_share * e0,
               "jitter_low": (rec["arms"]["jitter_control"]["on_winding"] or 0) <= 0.4}
        rec["controls_pass"] = chk
        out["slices"][str(z)] = rec
        if hand != th_hand:
            print(f"z{z}: labels use hand {hand}, the references {th_hand}: scored in the references' hand")
        nn = lambda v: float("nan") if v is None else v  # noqa: E731  (an empty slice must not stop the stack)
        print(f"z{z}: turn residual p99 {rec['turn_resid_p99']}, ambiguous share {nn(rec['ambiguous_share']):.3f}, "
              f"contact share {nn(rec.get('contact_share')):.3f}, controls {chk}")
        for k, v in rec["arms"].items():
            print(f"  {k:17s} on {v.get('on_winding')!s:.6} pair {v.get('pair')!s:.6} step {v.get('step_acc')!s:.6} "
                  f"({v.get('steps')}) switches {v.get('switches')} ({v.get('switches_per_mm') or 0:.3f}/mm) "
                  f"off_by {v.get('off_by')}", flush=True)
        for k, v in rec["strata"].items():
            print(f"  stratum {k:9s} on {v['on_winding']!s:.6} (n {v['labelled_matched']}) step {v['step_acc']!s:.6} "
                  f"({v['steps']})")
    tot = {}
    for arm_ in ("global", "naive"):
        vals = [s_["arms"][arm_] for s_ in out["slices"].values() if arm_ in s_["arms"]]
        if vals:
            w = np.array([v["labelled_matched"] for v in vals], float)
            tot[arm_] = {k: float(np.average([v[k] for v in vals], weights=w)) for k in ("on_winding", "pair")
                         if all(v.get(k) is not None for v in vals)}
            ws = np.array([v.get("steps", 0) for v in vals], float)
            if ws.sum():
                tot[arm_]["step_acc"] = float(np.average([v.get("step_acc", 0) for v in vals], weights=ws))
    out["pooled"] = tot
    print("pooled", json.dumps(tot))
    (run / ("score-clear.json" if a.clear else "score.json")).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
