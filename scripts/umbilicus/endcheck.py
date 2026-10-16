"""End-point rule for umbilicus (scroll centre) lines: measure it on the published scrolls and apply it to files.

    python endcheck.py calibrate --cache DIR [--out calib.json] [--radius MM]
    python endcheck.py score RUN_DIR --cache DIR [--data NPZ_DIR] [--out score.json]
    python endcheck.py files SRC DST --cache DIR [--data NPZ_DIR]

calibrate  the rule at the published centres of the 13 published scrolls (held constant past their first and last
           control points): how often the support falls under the bar inside each annotated band, and how many points
           the rule drops at each end. Public data only. --radius tries another radius than the rule's.
score      the rule on a finished run's held-out predictions (refine_*.json of refine.py chain, or fold*.json of
           pipeline.py job): per held-out scroll, the error against the published centre over all scored slices
           (this must equal the run's result.json), over the slices pipeline.keep_band keeps, and over the slices
           the end-point rule keeps. One stage per folder: a folder with both kinds of record is refused.
files      apply the rule to umbilicus JSONs already written (SRC/*_umbilicus.json to DST).

Slices are the ones the pipeline reads (level-0 z = 32 + 64 k). With --data the pipeline's own slice files
(<scroll>.npz from `slices.py extract`) are used. Without it, the open-data bucket is read with HTTP range requests:
the whole level-5 plane of each slice (papyrus area for keep_band, a stand-in for the level-3 area the pipeline
uses) and a level-3 window around each centre (the rule itself), about 40 to 90 MB per scroll, cached in --cache.
A chunk the bucket does not hold reads as 0 (air), as in the slice files; missing_chunks counts those reads (one per
plane and chunk, from the cache too), or is null when a cache file made before the count was stored was used.
Cache files are named by scroll and by a hash of the scan's bucket path and hold that path, so two scans of one scroll
never share them; cache files made before 16 October 2026 (named by scroll only) are not read. A slice file given with
--data must hold the scan the run or umbilicus file names.
"""
import argparse, glob, hashlib, json, os, sys
import numpy as np
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline, slices

class Bucket:
    """One scroll's slices from the bucket: level-5 area per slice and level-3 windows around given centres.
    missing: chunk reads the bucket answered with NoSuchKey (read as 0), counted from the cache too; None once a
    cache file without a stored count was used."""
    def __init__(self, vol, cache, name):
        self.vol, self.cache, self.name = vol.rstrip("/"), cache, name
        self.tag = hashlib.sha256(self.vol.encode()).hexdigest()[:12]    # cache files are per scan, not per scroll
        os.makedirs(cache, exist_ok=True)
        self.um = float(self.vol.split("/")[-1].split("-")[1].replace("um", ""))
        self.L3 = slices.PlaneReader(self.vol, 3)
        self.missing = 0

    def _count(self, n):
        self.missing = None if self.missing is None or n is None else self.missing + int(n)

    @staticmethod
    def _stored(npz):
        return int(npz["missing"]) if "missing" in npz.files else None

    def _load(self, f):
        """A cache file of this scan, or None (absent, or written for another scan)."""
        if not os.path.exists(f):
            return None
        hit = np.load(f)
        if "vol" not in hit.files or str(hit["vol"]).rstrip("/") != self.vol:
            print(f"{f}: cache file of another scan, read again", file=sys.stderr)
            return None
        return hit

    def heights(self):
        Z0 = self.L3.shape[0] * 8
        z = np.arange(32, Z0, 64)
        return z[z // 8 < self.L3.shape[0]]

    def area(self, z):
        """Filled papyrus area of each slice from the level-5 plane (pipeline.papyrus_area's mask, 4x coarser)."""
        from scipy import ndimage as ndi
        f = os.path.join(self.cache, f"{self.name}_{self.tag}_l5.npz")
        hit = self._load(f)
        if hit is not None and np.array_equal(hit["z"], z):
            p5 = hit["p5"]; self._count(self._stored(hit))
        else:
            L5 = slices.PlaneReader(self.vol, 5)
            with ThreadPoolExecutor(8) as ex:
                p5 = np.stack(list(ex.map(lambda zz: L5.plane(int(zz) // 32, threads=9), z)))
            self._count(L5.missing)
            np.savez_compressed(f, z=z, p5=p5, missing=L5.missing, vol=self.vol)
        a = np.array([ndi.binary_fill_holes(ndi.gaussian_filter(im.astype(np.float32), 0.5) > 5).sum() for im in p5], float)
        return a, p5.reshape(len(p5), -1).max(1) > 0

    def windows(self, z, yx, use):
        """The rule's level-3 windows (pipeline.window_origins) on slices where use is True; zeros elsewhere."""
        org, h = pipeline.window_origins(yx, self.um, 3)
        ok = use & np.isfinite(yx).all(1)
        org[~ok] = 0
        key = hashlib.sha256(np.ascontiguousarray(np.c_[z, org, ok]).astype(np.int64).tobytes()).hexdigest()[:16]
        f = os.path.join(self.cache, f"{self.name}_{self.tag}_l3_{key}.npz")
        hit = self._load(f)
        if hit is not None:
            self._count(self._stored(hit))
            return hit["w"], org
        w = np.zeros((len(z), 2 * h, 2 * h), np.uint8); m0 = self.L3.missing
        def one(i):
            y0, x0 = org[i]
            return i, self.L3.plane(int(z[i]) // 8, y0, y0 + 2 * h, x0, x0 + 2 * h, threads=9)
        with ThreadPoolExecutor(8) as ex:
            for i, c in ex.map(one, np.nonzero(ok)[0]):
                w[i] = c
        n = self.L3.missing - m0; self._count(n)
        np.savez_compressed(f, w=w, missing=n, vol=self.vol)
        return w, org


def _rule_bucket(src, z, yx, present, keep):
    """pipeline.end_trimmed_keep on windows read from the bucket."""
    w, org = src.windows(z, yx, present)
    return pipeline.apply_end_rule(w, org, yx, z, src.um, keep, 3)


def _npz(data, s, vol):
    """data/<s>.npz, refused unless it holds the scan vol."""
    f = os.path.join(data, f"{s}.npz"); d = np.load(f)
    held = str(d["vol"]).rstrip("/") if "vol" in d.files else None
    if held != str(vol).rstrip("/"):
        raise SystemExit(f"{f} holds slices of {held}, not {vol}: use another --data folder")
    return d


def _rule_npz(d, yx, keep):
    return pipeline.end_trimmed_keep(d["ct"], yx, np.asarray(d["z_l0"]), float(d["um"]), keep,
                                     level=int(d["level"]) if "level" in d.files else 3)


def _ends(keep0, keep1, scored):
    """Points the rule drops at the low and high ends, and how many of them are scored."""
    gone = keep0 & ~keep1
    idx = np.nonzero(keep0)[0]
    if not len(idx):
        return dict(dropped_low=0, dropped_high=0, dropped_scored=0)
    mid = idx[len(idx) // 2]
    return dict(dropped_low=int(gone[:mid].sum()), dropped_high=int(gone[mid:].sum()), dropped_scored=int((gone & scored).sum()))


def calibrate(cache, out=None, radius_mm=None):
    """The rule at the published centres of the 13 published scrolls. radius_mm tries another radius than
    pipeline.END_RADIUS_MM (the rule's constant is restored afterwards)."""
    if radius_mm is not None:
        old = pipeline.END_RADIUS_MM; pipeline.END_RADIUS_MM = float(radius_mm)
        try:
            return calibrate(cache, out)
        finally:
            pipeline.END_RADIUS_MM = old
    res, pooled = dict(rule=_rule(), scrolls={}), []
    for s in slices.LABELLED:
        vol, T = slices.truth(s)
        src = Bucket(vol, cache, s)
        z = src.heights(); area, present = src.area(z)
        yx = np.stack([np.interp(z, T[:, 0], T[:, 1]), np.interp(z, T[:, 0], T[:, 2])], 1)
        scored = (z >= T[0, 0]) & (z <= T[-1, 0])
        L = T[-1, 0] - T[0, 0]
        interior = (z >= T[0, 0] + 0.1 * L) & (z <= T[-1, 0] - 0.1 * L)   # where a person placed a centre, away from the ends
        kb = pipeline.keep_band(area, z, src.um) & present
        k2, sup, thr = _rule_bucket(src, z, yx, present, kb)
        pooled.append(sup[interior])
        res["scrolls"][s] = dict(papyrus_level=thr, slices=len(z), scored=int(scored.sum()), keep_band=int(kb.sum()),
                                 keep_band_scored=int((kb & scored).sum()), end_rule=int(k2.sum()),
                                 end_rule_scored=int((k2 & scored).sum()), **_ends(kb, k2, scored),
                                 interior_below_bar=int((sup[interior] < pipeline.END_SUPPORT).sum()),
                                 interior=int(interior.sum()), missing_chunks=src.missing)
        print(s, json.dumps(res["scrolls"][s]), flush=True)
    allI = np.concatenate(pooled)
    res["interior_pooled"] = dict(n=int(len(allI)), below_bar=round(float((allI < pipeline.END_SUPPORT).mean()), 4),
                                  pct=dict(zip(["0.5", "1", "2", "5", "10"], np.percentile(allI, [0.5, 1, 2, 5, 10]).round(3).tolist())))
    if out:
        with open(out, "w") as fh:
            json.dump(res, fh, indent=1)
    return res


def _rule():
    return dict(radius_mm=pipeline.END_RADIUS_MM, min_support=pipeline.END_SUPPORT, run_mm=pipeline.END_RUN_MM, rays=pipeline.END_RAYS,
                cap_mm=pipeline.CAP_MM, area_frac=pipeline.AREA_FRAC)


def _stats(e):
    return pipeline._stats(np.asarray(e)) if len(e) else dict(n=0)


def score(run, cache, data=None, out=None):
    """Held-out error over all scored slices, over keep_band, and over keep_band plus the end-point rule."""
    files = sorted(glob.glob(os.path.join(run, "*.json")))
    recs, stages = [], set()
    for f in files:
        if os.path.basename(f)[:4] in ("refi", "fold"):
            with open(f) as fh:
                r = json.load(fh)
            if "preds" in r:          # job records only (refine.py cv's refine_cv.json is a summary)
                recs.append(r); stages.add(os.path.basename(f)[:4])
    if not recs:
        raise SystemExit(f"{run}: no refine_*.json or fold*.json")
    if len(stages) > 1:               # each stage is scored from its own records; mixing them gives a wrong number
        raise SystemExit(f"{run}: holds both first-stage (fold*.json) and zoom-stage (refine_*.json) records; "
                         "score one stage per folder")
    res = dict(rule=_rule(), run=os.path.basename(run.rstrip("/")), source="npz" if data else "bucket (level-5 area)", scrolls={})
    pool = {k: [] for k in ("all", "keep_band", "end_rule")}
    for s in slices.LABELLED:
        rs = [r for r in recs if r.get("test") and s in r["test"]]
        if not rs:
            continue
        p = rs[0]["preds"][s]; z = np.array(p["z"]); um = float(p["um"]); present = np.array(p["present"], bool)
        if "base_yx" in p:            # refine.chain_collect: the chained answer of the fold's refine model
            yx = slices.smooth_z(np.where(present[:, None], np.array(p["yx"], float), np.nan)); arm = "chained"
        else:                         # pipeline.collect: mean of the fold's first-stage seeds
            yx = slices.smooth_z(np.mean([np.array(r["preds"][s]["yx"], float) for r in rs], 0)); arm = "first stage"
        _, T = slices.truth(s)
        scored = (z >= T[0, 0]) & (z <= T[-1, 0])
        if data:
            d = _npz(data, s, p["vol"])
            kb = pipeline.keep_band(pipeline.papyrus_area(d["ct"]), z, um) & present
            k2, sup, thr = _rule_npz(d, yx, kb); miss = None      # slice files do not record absent chunks
        else:
            src = Bucket(p["vol"], cache, s)
            area, _ = src.area(z)
            kb = pipeline.keep_band(area, z, um) & present
            k2, sup, thr = _rule_bucket(src, z, yx, present, kb); miss = src.missing
        e = np.hypot(*(yx - np.stack([np.interp(z, T[:, 0], T[:, 1]), np.interp(z, T[:, 0], T[:, 2])], 1)).T) * um / 1000
        sel = dict(all=scored, keep_band=scored & kb, end_rule=scored & k2)
        res["scrolls"][s] = dict(arm=arm, papyrus_level=thr, missing_chunks=miss, **_ends(kb, k2, scored),
                                 **{k: _stats(e[v]) for k, v in sel.items()},
                                 dropped_scored_median_error_mm=round(float(np.median(e[scored & kb & ~k2])), 3) if (scored & kb & ~k2).any() else None)
        for k, v in sel.items():
            pool[k] += list(e[v])
        print(s, json.dumps(res["scrolls"][s]), flush=True)
    res["pooled"] = {k: _stats(v) for k, v in pool.items()}
    if out:
        with open(out, "w") as fh:
            json.dump(res, fh, indent=1)
    return res


def files(src_dir, dst, cache, data=None):
    """Apply the end-point rule to written umbilicus JSONs; points already dropped stay dropped."""
    os.makedirs(dst, exist_ok=True); out = {}
    for f in sorted(glob.glob(os.path.join(src_dir, "*_umbilicus.json"))):
        s = os.path.basename(f)[:-len("_umbilicus.json")]
        with open(f) as fh:
            j = json.load(fh)
        cp = sorted(j["control_points"], key=lambda q: q["z"])
        if not cp:
            continue
        z = np.array([q["z"] for q in cp], float); yx = np.array([[q["y"], q["x"]] for q in cp], float)
        um = float(j["metadata"]["voxelsize_um"])
        if data:
            d = _npz(data, s, j["metadata"]["source_volume"]); zz = np.asarray(d["z_l0"], float)
            idx = np.searchsorted(zz, z)
            if not (idx < len(zz)).all() or not np.array_equal(zz[np.minimum(idx, len(zz) - 1)], z):
                raise SystemExit(f"{s}: control point heights are not the slice file's heights")
            full = np.full((len(zz), 2), np.nan); full[idx] = yx
            k_all, _, thr = _rule_npz(d, full, np.isin(np.arange(len(zz)), idx))
            keep = k_all[idx]
        else:
            b = Bucket(j["metadata"]["source_volume"], cache, s)
            allp = np.ones(len(z), bool)
            keep, _, thr = _rule_bucket(b, z.astype(int), yx, allp, allp)
        j["control_points"] = [q for q, k in zip(cp, keep) if k]
        j["metadata"]["total_points"] = len(j["control_points"])
        j["metadata"]["end_trimmed"] = (f"end-point rule: dropped from each end until {pipeline.END_RUN_MM:g} mm of slices where at least "
                                        f"{pipeline.END_SUPPORT:g} of {pipeline.END_RAYS} rays from the centre meet papyrus within "
                                        f"{pipeline.END_RADIUS_MM:g} mm (scripts/umbilicus/endcheck.py)")
        with open(os.path.join(dst, os.path.basename(f)), "w") as fh:
            json.dump(j, fh, indent=1)
        out[s] = dict(points_in=len(cp), points_out=int(keep.sum()), papyrus_level=thr)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["calibrate", "score", "files"])
    ap.add_argument("args", nargs="*", help="score: RUN_DIR; files: SRC DST")
    ap.add_argument("--cache", default=os.path.join("work", "umbilicus", "endcheck-cache"))
    ap.add_argument("--data", help="the pipeline's slice files (<scroll>.npz) instead of bucket reads")
    ap.add_argument("--out", help="write the result JSON here")
    ap.add_argument("--radius", type=float, help="calibrate: try this radius in mm instead of the rule's")
    a = ap.parse_args()
    if a.cmd == "calibrate":
        r = calibrate(a.cache, a.out, a.radius)
        print(json.dumps(dict(interior_pooled=r["interior_pooled"], rule=r["rule"]), indent=1))
    elif a.cmd == "score":
        if len(a.args) != 1:
            raise SystemExit("score RUN_DIR")
        print(json.dumps(score(a.args[0], a.cache, a.data, a.out)["pooled"], indent=1))
    else:
        if len(a.args) != 2:
            raise SystemExit("files SRC DST")
        print(json.dumps(files(a.args[0], a.args[1], a.cache, a.data), indent=1))
