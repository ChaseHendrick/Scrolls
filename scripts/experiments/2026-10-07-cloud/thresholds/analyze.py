"""thresholds job: lead (c) of scripts/experiments/2026-10-07-cloud/README.md, on whole-segment ink_9um seed 42
maps (forward and reverse) of PHerc0841 w00, ag896, ag405 and PHerc0139 w045.

  python analyze.py part1|part2|part3|all [--work DIR] [--out results_partN.json]

part1: leave-one-sheet-out threshold calibrated on PHerc0841. w00 and ag896 are two traces of one sheet;
       both calibrate on ag405. ag405 calibrates on the fixed primary trace w00, never pooled with ag896.
       Apply millerandmuller's candidate rule at that threshold and at 0.7843.
part2: the automatic readout rules of three community repositories, reimplemented from the files and commits
       cited in notes.md, applied to every whole-segment map, forward and reverse.
part3: kit rowscore and kit auc on random square windows of 0.25 to 4 cm2, forward and reverse.

Maps, volumes and labels are read from $WORK (never from git). Output is small JSON only. Model output, not a
reading.
"""
import argparse, json, math, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "../../../.."))
sys.path.insert(0, REPO)

import numpy as np
import tifffile
import zarr
from scipy import ndimage

from kit.auc import labels_on_map, score_array as auc_score
from kit.rowscore import score_array as row_score

SEGMENTS = {  # surface shape (H, W) and voxel size (um), from scripts/mac-w045.sh and the cloud README
    "0841-w00": ((4220, 4760), 9.366),
    "0841-ag896": ((4640, 4720), 9.366),
    "0841-ag405": ((3760, 4900), 9.366),
    "w045": ((5980, 8240), 9.362),
}
P0841 = ["0841-w00", "0841-ag896", "0841-ag405"]
ACTIVE = list(P0841)  # --segments narrows parts 2 and 3 (part 1 always needs all three); w045 dropped for budget
# Fixed before part 1 runs. The second trace is a sensitivity check, not another independent sheet.
SHEET_BY_SEGMENT = {"0841-w00": "w00-ag896", "0841-ag896": "w00-ag896", "0841-ag405": "ag405"}
PRIMARY_TRACE = "0841-w00"
CALIBRATION_TRACES = {"0841-w00": ("0841-ag405",), "0841-ag896": ("0841-ag405",),
                      "0841-ag405": (PRIMARY_TRACE,)}


def load(work, seg):
    m = os.path.join(work, "thresholds", "maps", f"{seg}_ink9um_s42")
    F = tifffile.imread(m + ".tif")
    R = tifffile.imread(m + "_reverse.tif")
    assert F.dtype == np.uint8 and R.dtype == np.uint8, (F.dtype, R.dtype)
    shape, vox = SEGMENTS[seg]
    assert F.shape == R.shape == shape, (seg, F.shape, R.shape, shape)
    lab = os.path.join(work, "data", f"{seg}_labels")
    ink, sup = labels_on_map(os.path.join(lab, "inklabels.zarr"), os.path.join(lab, "supervision.zarr"), "2",
                             shape, None, shape)
    valid = (F > 0) | (R > 0)  # villa writes 0 where it made no prediction (outside the surface)
    return dict(seg=seg, F=F, R=R, ink=ink, sup=sup, valid=valid, vox=vox,
                cm2_per_px=(vox * 1e-4) ** 2, area_cm2=float(valid.sum()) * (vox * 1e-4) ** 2)


def mid_slice(work, seg):
    a = zarr.open(os.path.join(work, "data", f"{seg}_9um.zarr"), mode="r")
    a = a["0"] if hasattr(a, "keys") else a
    return np.asarray(a[a.shape[0] // 2])


# ---------------------------------------------------------------- millerandmuller (first-light-pherc0826)
# analysis/target-PHerc0826-window1-full-w010-065/analyze_target.py at ee8eef11e57ce7b5bc84ae3cdf5692ca234fac7c:
# map / 255 >= THRESHOLD; 8-connected components; bounding-box long side >= 0.5 mm / 9.362 um (53.41 px);
# forward, reverse, and the "full mechanical pass" on pixels at or above in BOTH directions.
MM_FLOOR_PX = 0.5 * 1000 / 9.362


def component_label_evidence(area, on_ink, in_supervision):
    """Keep historical ink_frac; precision uses only pixels with known labels.

    Pixels outside supervision are unknown, even when inklabels is zero there.
    known_label_precision is undefined for an entirely unlabelled component.
    """
    area, on_ink, in_supervision = int(area), int(on_ink), int(in_supervision)
    if not 0 <= on_ink <= in_supervision <= area or area <= 0:
        raise ValueError("component label counts must satisfy 0 <= ink <= supervision <= area, area > 0")
    return {"area_px": area, "ink_frac": on_ink / area, "sup_frac": in_supervision / area,
            "supervised_ink_px": on_ink, "supervised_background_px": in_supervision - on_ink,
            "unknown_px": area - in_supervision,
            "known_label_precision": on_ink / in_supervision if in_supervision else None}


def label_summary(components):
    """Add label coverage without treating unknown pixels as false positives."""
    known = [c["known_label_precision"] for c in components if c["known_label_precision"] is not None]
    return {"label_evidence": components,
            "candidates_without_supervision": sum(c["sup_frac"] == 0 for c in components),
            "candidates_with_partial_supervision": sum(0 < c["sup_frac"] < 1 for c in components),
            "median_supervision_fraction": float(np.median([c["sup_frac"] for c in components])) if components else None,
            "median_known_label_precision": float(np.median(known)) if known else None}


def mm_components(mask, ink=None, sup=None):
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    out = []
    if n == 0:
        return out
    objs = ndimage.find_objects(lab)
    if ink is not None:
        idx = np.arange(1, n + 1)
        area = ndimage.sum(np.ones_like(mask, np.float32), lab, idx)
        on_ink = ndimage.sum((ink & sup).astype(np.float32), lab, idx)
        in_sup = ndimage.sum(sup.astype(np.float32), lab, idx)
    for i, sl in enumerate(objs, start=1):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if max(h, w) < MM_FLOOR_PX:
            continue
        c = {"long_px": int(max(h, w)), "bbox": [int(sl[0].start), int(sl[0].stop), int(sl[1].start), int(sl[1].stop)]}
        if ink is not None:
            c.update(component_label_evidence(area[i - 1], on_ink[i - 1], in_sup[i - 1]))
        out.append(c)
    return out


def mm_rule(d, T):
    """Counts under millerandmuller's rule at threshold T (probability). 'mostly on labelled ink': more than half
    of the component's pixels are labelled ink (labels at level 2, inside the supervision mask).
    This historical count is not precision: unlabelled pixels remain unknown."""
    f = d["F"].astype(np.float32) / 255 >= T
    r = d["R"].astype(np.float32) / 255 >= T
    res = {}
    for name, m in (("forward", f), ("reverse", r), ("both", f & r)):
        cs = mm_components(m, d["ink"], d["sup"])
        res[name] = {"candidates": len(cs), "per_cm2": round(len(cs) / d["area_cm2"], 3),
                     "mostly_on_ink": sum(c["ink_frac"] > 0.5 for c in cs),
                     "mostly_in_supervision": sum(c["sup_frac"] > 0.5 for c in cs),
                     "px_at_or_above": int(m.sum()), **label_summary(cs)}
    sup = d["sup"] & d["valid"]
    res["ink_share_at_or_above"] = round(float(f[sup & d["ink"]].mean()), 4)
    res["background_share_at_or_above"] = round(float(f[sup & ~d["ink"]].mean()), 5)
    res["reverse_ink_share_at_or_above"] = round(float(r[sup & d["ink"]].mean()), 4)
    return res


def ink_values(d):
    return d["F"][d["sup"] & d["ink"] & d["valid"]].astype(np.float32) / 255


def calibration_traces(held_out):
    traces = CALIBRATION_TRACES[held_out]
    if any(SHEET_BY_SEGMENT[s] == SHEET_BY_SEGMENT[held_out] for s in traces):
        raise ValueError("calibration cannot use another trace of the held-out sheet")
    if len({SHEET_BY_SEGMENT[s] for s in traces}) != len(traces):
        raise ValueError("calibration cannot pool duplicate traces of one sheet")
    return traces


def threshold_uint8(T):
    """First uint8 bin accepted by the actual float32 map/255 comparison."""
    if not np.isfinite(T) or not 0 <= T <= 1:
        raise ValueError("threshold must be finite and between zero and one")
    return int(np.searchsorted(np.arange(256, dtype=np.float32) / 255, T, side="left"))


def part1(work):
    data = {s: load(work, s) for s in P0841}
    rows, med = [], {}
    for s, d in data.items():
        v = ink_values(d)
        if not v.size:
            raise ValueError(f"no supervised ink pixels in {s}")
        med[s] = float(np.median(v))
        rows.append({"segment": s, "area_cm2": round(d["area_cm2"], 2), "ink_px": int(v.size),
                     "background_px": int((d["sup"] & ~d["ink"] & d["valid"]).sum()),
                     "median_forward_on_ink": round(med[s], 4),
                     "median_reverse_on_ink": round(float(np.median(d["R"][d["sup"] & d["ink"] & d["valid"]]) / 255), 4)})
    out = {"segments": rows, "loo": [], "training_threshold_0.7843": {},
           "calibration_unit": "independent sheet", "primary_trace": PRIMARY_TRACE,
           "sheet_by_segment": dict(SHEET_BY_SEGMENT)}
    for held in P0841:
        others = calibration_traces(held)
        values = np.concatenate([ink_values(data[s]) for s in others])
        if not values.size:
            raise ValueError(f"no supervised ink pixels for calibrating {held}")
        T = float(np.median(values))
        r = {"held_out": held, "held_out_sheet": SHEET_BY_SEGMENT[held],
             "calibrated_on": list(others), "threshold": round(T, 4),
             "threshold_uint8": threshold_uint8(T), **mm_rule(data[held], T)}
        out["loo"].append(r)
    for s, d in data.items():
        out["training_threshold_0.7843"][s] = mm_rule(d, 0.7843)
    return out


# ---------------------------------------------------------------- bnleft (first-light-pherc0211)
# modal_app.py READOUT_SCRIPT at 728a27234f50d239c6c83934dad6952b48b94b76 (prereg/readout.md, T = 199):
# uint8 map >= T; 4-connected; drop bbox long side < round(0.5 mm / 9.362 um) = 53 px; drop components touching
# the map frame; drop bands (long >= 5 x short); drop components whose bbox centre lies where the surface volume's
# middle slice is > 50 % zero over a 129 px box. Every remaining component is a candidate, per direction.
def bnleft_rule(d, mid, T=199):
    zero_frac = ndimage.uniform_filter((mid == 0).astype(np.float32), size=129, mode="nearest")
    low_cov = zero_frac > 0.5
    res = {"T_uint8": T, "frac_low_coverage": round(float(low_cov.mean()), 4)}
    for name, P in (("forward", d["F"]), ("reverse", d["R"])):
        lab, n = ndimage.label(P >= T, structure=[[0, 1, 0], [1, 1, 1], [0, 1, 0]])
        ex = {"small": 0, "boundary": 0, "band": 0, "low_coverage": 0}
        cands = []
        for i, sl in enumerate(ndimage.find_objects(lab), start=1):
            h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if max(h, w) < 53:
                ex["small"] += 1; continue
            if sl[0].start == 0 or sl[1].start == 0 or sl[0].stop == P.shape[0] or sl[1].stop == P.shape[1]:
                ex["boundary"] += 1; continue
            if max(h, w) >= 5 * min(h, w):
                ex["band"] += 1; continue
            cy, cx = (sl[0].start + sl[0].stop) // 2, (sl[1].start + sl[1].stop) // 2
            if low_cov[cy, cx]:
                ex["low_coverage"] += 1; continue
            comp = lab[sl] == i
            cands.append(component_label_evidence(comp.sum(), (d["ink"][sl] & d["sup"][sl] & comp).sum(),
                                                  (d["sup"][sl] & comp).sum()))
        res[name] = {"components": int(n), "excluded": ex, "candidates": len(cands),
                     "per_cm2": round(len(cands) / d["area_cm2"], 3),
                     "mostly_on_ink": int(sum(c["ink_frac"] > 0.5 for c in cands)),
                     "frac_ge_T": round(float((P[d["valid"]] >= T).mean()), 5), **label_summary(cands)}
    return res


# ---------------------------------------------------------------- nerln (vesuvius-first-letters-pherc0800)
# reproduce.py at 174542319b383e84a8b1dbe2092f46850592f99a, rule as finalised in G0.md (22 Sep 18:48 and 19:07):
# forward uint8 >= 128; reverse thresholded at the value that lights the same fraction of valid pixels
# (valid = forward > 0 or reverse > 0); scipy default 4-connected components; area >= 12,000 px; the component
# must lie entirely inside a 64 px border band. Reported: counts at each step, both directions, the reverse also at
# the absolute 128, and the 50 % overlap check (a diagnostic, not a filter, since 19:07). Their part 2 of the 18:48
# rule: a segment is null unless forward candidates outnumber reverse ones.
NERLN_T, NERLN_AREA, NERLN_BORDER = 128, 12000, 64


def nerln_candidates(m, thr):
    lab, k = ndimage.label(m >= thr)
    H, W = m.shape
    area = np.bincount(lab.ravel())[1:] if k else np.array([], int)
    keep = []
    n_area = 0
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if area[i - 1] < NERLN_AREA:
            continue
        n_area += 1
        if sl[0].start >= NERLN_BORDER and sl[1].start >= NERLN_BORDER and sl[0].stop <= H - NERLN_BORDER \
                and sl[1].stop <= W - NERLN_BORDER:
            keep.append(i)
    return lab, keep, {"components_above": int(k), "after_area": n_area, "after_border": len(keep)}


def nerln_rule(d):
    F, R, valid = d["F"], d["R"], d["valid"]
    fa = float((F[valid] >= NERLN_T).mean())
    thr_m = float(np.percentile(R[valid], 100 * (1 - fa)))
    labF, cF, sF = nerln_candidates(F, NERLN_T)
    labR, cR, sR = nerln_candidates(R, thr_m)
    _, cRa, sRa = nerln_candidates(R, NERLN_T)
    rev_mask = np.isin(labR, cR)
    overl, label_evidence = [], []
    for i in cF:
        b = labF == i
        overl.append(float(rev_mask[b].mean()))
        label_evidence.append(component_label_evidence(b.sum(), (d["ink"] & d["sup"])[b].sum(), d["sup"][b].sum()))
    occ_mpx = valid.sum() / 1e6
    return {"forward_lit_fraction": round(fa, 5), "reverse_matched_threshold_uint8": round(thr_m, 1),
            "forward": {**sF, "candidates": len(cF), "per_cm2": round(len(cF) / d["area_cm2"], 3),
                        "per_valid_mpx": round(len(cF) / occ_mpx, 2),
                        "mostly_on_ink": int(sum(c["ink_frac"] > 0.5 for c in label_evidence)),
                        "overlap_ge_50pct_with_reverse": int(sum(x >= 0.5 for x in overl)),
                        **label_summary(label_evidence)},
            "reverse_matched": {**sR, "candidates": len(cR), "per_cm2": round(len(cR) / d["area_cm2"], 3)},
            "reverse_absolute_128": {**sRa, "candidates": len(cRa)},
            "verdict_forward_exceeds_reverse": len(cF) > len(cR),
            "mean_uint8": {"forward": round(float(F[valid].mean()), 1), "reverse": round(float(R[valid].mean()), 1)}}


# ---------------------------------------------------------------- TAUIL-Abd-Elilah (pherc0826-first-letters-search)
# search/read_sheets.py (best2mm, map rescale), search/band_score.py, search/dense_review.py (slab_fraction,
# elongation, one-sidedness, rank_score) at 7a6b453c9f4355b97575ee6367db4a51fea9c44c; README "strong sites (>= 0.5)".
# Their sites are 12 x 15 mm sheets; here each whole-segment map is tiled into 12 x 15 mm sites (z along rows).
def tauil_rescale(q):
    q = q.astype(np.float32) / 255
    return np.clip((q - 0.25) / 0.5, 0, 1)   # read_sheets.villa(): what they score and save


def best2mm(prob, valid, px_mm):
    v = ndimage.binary_erosion(valid, iterations=48)
    b = ((prob > 0.5) & v).astype(np.float32)
    w = int(round(2.0 / px_mm))
    loc = ndimage.uniform_filter(b, w) if min(b.shape) > w else b
    return {"frac": float(b[v].mean()) if v.any() else 0.0, "best_2mm": float(loc.max())}


def band_score(prob, valid, thr=0.5, band_mm=2.0, gap_mm=3.0, px_mm=8.64e-3):
    # band_score.py hard-codes PX_MM = 1 / 8.64e-3 (v8-in's grid); kept as published
    v = ndimage.binary_erosion(valid, iterations=48)
    cols = v.any(0)
    if cols.sum() < 100:
        return 0.0
    ink = (prob > thr) & v
    per_row = ink[:, cols].sum(1) / np.maximum(v[:, cols].sum(1), 1)
    bw = int(band_mm / px_mm)
    band = ndimage.uniform_filter1d(per_row.astype(np.float64), bw, mode="nearest")
    g = int(gap_mm / px_mm)
    Z = len(band)
    best = -1.0
    for z in range(bw // 2, Z - bw // 2):
        nb = [band[k] for k in (z - g, z + g) if bw // 2 <= k < Z - bw // 2]
        if nb:
            best = max(best, band[z] - float(np.mean(nb)))
    return best


def slab_fraction(m, v):
    b = (m > 0.5) & v
    if b.sum() < 100:
        return 0.0
    lab, n = ndimage.label(b)
    return float(np.bincount(lab.ravel())[1:].max() / b.sum())


def site_slices(shape, site_shape):
    """Nonoverlapping real footprints, including both remainder strips."""
    H, W = shape
    sh, sw = site_shape
    if H <= 0 or W <= 0 or sh <= 0 or sw <= 0:
        raise ValueError("canvas and site dimensions must be positive")
    for y0 in range(0, H, sh):
        for x0 in range(0, W, sw):
            yield slice(y0, min(y0 + sh, H)), slice(x0, min(x0 + sw, W))


def tauil_sites(d, mid):
    px_mm = d["vox"] * 1e-3
    sh, sw = int(round(12 / px_mm)), int(round(15 / px_mm))   # 12 mm along z (rows), 15 mm laterally
    H, W = d["F"].shape
    valid_all = mid > 0                                        # read_sheets: valid = middle layer > 0
    mf, mr = tauil_rescale(d["F"]), tauil_rescale(d["R"])
    sites = []
    covered_canvas_px = covered_valid_px = skipped_canvas_px = skipped_valid_px = 0
    tiled_sites = skipped_sites = 0
    for sl in site_slices((H, W), (sh, sw)):
        tiled_sites += 1
        height, width = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        pad = ((0, sh - height), (0, sw - width))
        # Outside-canvas samples are zero and invalid; they cannot add evidence.
        v = np.pad(valid_all[sl], pad, constant_values=False)
        if v.mean() < 0.05:                                    # fraction of the nominal-size site
            skipped_sites += 1
            skipped_canvas_px += height * width
            skipped_valid_px += int(v.sum())
            continue
        covered_canvas_px += height * width
        covered_valid_px += int(v.sum())
        s = {"y0": sl[0].start, "y1": sl[0].stop, "x0": sl[1].start, "x1": sl[1].stop,
             "shape_px": [height, width], "padded_px": sh * sw - height * width,
             "valid_frac": round(float(v.mean()), 3),
             "labelled_ink_px": int((d["ink"][sl] & d["sup"][sl]).sum())}
        for face, M in (("fwd", mf), ("rev", mr)):
            m = np.pad(M[sl], pad, constant_values=0)
            b = best2mm(m, v, px_mm)
            s[face] = {"best_2mm": round(b["best_2mm"], 3), "band": round(band_score(m, v), 3),
                       "slab": round(slab_fraction(m, v), 3)}
        for face, other in (("fwd", "rev"), ("rev", "fwd")):
            a, o = s[face], s[other]
            a["one_sided"] = round(a["best_2mm"] - o["best_2mm"], 3)
            a["rank_score"] = round((a["best_2mm"] + 2 * a["band"] + max(0.0, a["one_sided"])) * (1 - 0.7 * a["slab"]), 3)
        sites.append(s)
    valid_px = int(valid_all.sum())
    out = {"site_px": [sh, sw], "sites": len(sites), "boundary_policy": "zero-pad to nominal site; padding invalid",
           "coverage": {"tiled_sites": tiled_sites, "skipped_sites_below_5pct_valid": skipped_sites,
                        "canvas_px": H * W, "valid_surface_px": valid_px,
                        "covered_canvas_px": covered_canvas_px, "covered_valid_px": covered_valid_px,
                        "skipped_canvas_px": skipped_canvas_px, "skipped_valid_px": skipped_valid_px,
                        "canvas_fraction": covered_canvas_px / (H * W),
                        "valid_fraction": covered_valid_px / valid_px if valid_px else None}}
    for face in ("fwd", "rev"):
        st = [s for s in sites if s[face]["best_2mm"] >= 0.5]
        out[face] = {"strong": len(st),
                     "strong_one_sided": sum(s[face]["one_sided"] > 0 for s in st),
                     "strong_one_sided_slab_lt_0.5": sum(s[face]["one_sided"] > 0 and s[face]["slab"] < 0.5 for s in st),
                     "strong_on_labelled_ink_sites": sum(s["labelled_ink_px"] > 0 for s in st),
                     "median_best_2mm": round(float(np.median([s[face]["best_2mm"] for s in sites])), 3) if sites else None,
                     "median_rank_score": round(float(np.median([s[face]["rank_score"] for s in sites])), 3) if sites else None}
    out["sites_with_labelled_ink"] = sum(s["labelled_ink_px"] > 0 for s in sites)
    out["site_rows"] = sites
    return out


def line_frac(m, valid, px_mm, axis_rows=True, p_lo=3.5, p_hi=8.0, win_mm=10.0):
    """search/row_period.py profiles() + spectrum_score(): z-profile periodicity, z along rows (axis_rows) or
    along columns (the map transposed)."""
    if not axis_rows:
        m, valid = m.T, valid.T
    w = max(8, int(round(win_mm / px_mm)))
    num = den = 0.0
    for c0 in range(0, m.shape[1] - w + 1, w):
        mm, vv = m[:, c0:c0 + w], valid[:, c0:c0 + w]
        frac = vv.mean(1)
        if (frac > 0.3).mean() < 0.6:
            continue
        p = np.where(frac > 0.3, (mm * vv).sum(1) / np.maximum(vv.sum(1), 1), np.nan)
        rows = np.flatnonzero(np.isfinite(p))
        r0, r1 = rows.min(), rows.max() + 1
        p = p[r0:r1]
        if (r1 - r0) * px_mm < 10:
            continue
        good = np.isfinite(p)
        p = np.interp(np.arange(p.size), np.flatnonzero(good), p[good])
        p = p - ndimage.gaussian_filter1d(p, 6.0 / px_mm)
        p = p * np.hanning(p.size)
        f = np.fft.rfftfreq(p.size, d=px_mm)
        P = np.abs(np.fft.rfft(p)) ** 2
        per = np.where(f > 0, 1 / np.maximum(f, 1e-9), np.inf)
        band = (per >= 1.2) & (per <= 15)
        line = (per >= p_lo) & (per <= p_hi)
        if P[band].sum() <= 0:
            continue
        num += P[line].sum(); den += P[band].sum()
    return round(num / den, 3) if den else None


def part2(work):
    out = {}
    for s in ACTIVE:
        t0 = time.time()
        d = load(work, s)
        mid = mid_slice(work, s)
        assert mid.shape == d["F"].shape, (mid.shape, d["F"].shape)
        r = {"area_cm2": round(d["area_cm2"], 2)}
        r["millerandmuller_0.7843"] = mm_rule(d, 0.7843)
        r["bnleft_T199"] = bnleft_rule(d, mid)
        r["nerln"] = nerln_rule(d)
        r["tauil_sites"] = tauil_sites(d, mid)
        # row_period on the whole segment, both axes; the human labels pick the axis text lines stack along
        valid = ndimage.binary_erosion(mid > 0, iterations=8)
        human = (d["ink"] & d["sup"]).astype(np.float32)
        lf = {}
        for ax in (True, False):
            k = "z_along_rows" if ax else "z_along_columns"
            lf[k] = {"labels": line_frac(human, valid, d["vox"] * 1e-3, ax),
                     "forward": line_frac(tauil_rescale(d["F"]), valid, d["vox"] * 1e-3, ax),
                     "reverse": line_frac(tauil_rescale(d["R"]), valid, d["vox"] * 1e-3, ax)}
        r["tauil_row_period_line_frac"] = lf
        r["seconds"] = round(time.time() - t0)
        out[s] = r
        print(s, "part2 done", r["seconds"], "s", flush=True)
    return out


# ---------------------------------------------------------------- part 3: how much surface a null needs
SIZES_CM2 = (0.25, 0.5, 1.0, 2.0, 4.0)


def part3(work, n_windows=200, seed=20261007, min_valid=0.8, max_tries=200000):
    rng = np.random.default_rng(seed)
    out = {}
    for s in ACTIVE:
        d = load(work, s)
        valid = d["valid"]
        ii = valid.astype(np.int64).cumsum(0).cumsum(1)
        ii = np.pad(ii, ((1, 0), (1, 0)))
        H, W = valid.shape
        res = {}
        for a in SIZES_CM2:
            side = int(round(math.sqrt(a) / (d["vox"] * 1e-4)))
            wins, tries = [], 0
            if side < min(H, W):
                while len(wins) < n_windows and tries < max_tries:
                    tries += 1
                    y, x = int(rng.integers(0, H - side + 1)), int(rng.integers(0, W - side + 1))
                    v = ii[y + side, x + side] - ii[y, x + side] - ii[y + side, x] + ii[y, x]
                    if v >= min_valid * side * side:
                        wins.append((y, x))
            rows = []
            for y, x in wins:
                sl = (slice(y, y + side), slice(x, x + side))
                vv = valid[sl]
                row = {"y": y, "x": x}
                for name, M in (("fwd", d["F"]), ("rev", d["R"])):
                    rs = row_score(M[sl], d["vox"], valid=vv)
                    row[f"row_{name}"] = rs.get("score")
                    sup = d["sup"][sl] & vv
                    ink = d["ink"][sl]
                    if (sup & ink).sum() >= 100 and (sup & ~ink).sum() >= 100:
                        row[f"auc_{name}"] = auc_score(M[sl], ink, sup)["auc"]
                rows.append(row)
            f = np.array([r["row_fwd"] for r in rows if r["row_fwd"] is not None and r["row_rev"] is not None])
            rv = np.array([r["row_rev"] for r in rows if r["row_fwd"] is not None and r["row_rev"] is not None])
            entry = {"side_px": side, "windows": len(rows), "tries": tries, "scored": int(f.size)}
            if f.size >= 20:
                p95 = float(np.percentile(rv, 95))
                entry.update(rev_p95=round(p95, 1), share_fwd_above_rev_p95=round(float((f > p95).mean()), 3),
                             median_row_fwd=round(float(np.median(f)), 1), median_row_rev=round(float(np.median(rv)), 1),
                             share_fwd_gt_rev_same_window=round(float((f > rv).mean()), 3))
            au = [(r["auc_fwd"], r["auc_rev"]) for r in rows if "auc_fwd" in r and "auc_rev" in r]
            if au:
                au = np.array(au, dtype=float)
                entry.update(auc_windows=len(au), median_auc_fwd=round(float(np.median(au[:, 0])), 4),
                             median_auc_rev=round(float(np.median(au[:, 1])), 4),
                             share_auc_fwd_gt_rev=round(float((au[:, 0] > au[:, 1]).mean()), 3))
            entry["rows"] = rows
            res[str(a)] = entry
            print(s, a, {k: v for k, v in entry.items() if k != "rows"}, flush=True)
        out[s] = res
    # pooled over the three PHerc0841 segments
    pooled = {}
    for a in SIZES_CM2:
        f, rv = [], []
        for s in [x for x in P0841 if x in out]:
            for r in out[s][str(a)]["rows"]:
                if r["row_fwd"] is not None and r["row_rev"] is not None:
                    f.append(r["row_fwd"]); rv.append(r["row_rev"])
        if len(f) >= 20:
            p95 = float(np.percentile(rv, 95))
            pooled[str(a)] = {"scored": len(f), "rev_p95": round(p95, 1),
                              "share_fwd_above_rev_p95": round(float((np.array(f) > p95).mean()), 3)}
    out["pooled_0841"] = pooled
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=["part1", "part2", "part3", "all"])
    ap.add_argument("--work", default=os.environ.get("WORK", os.path.expanduser("~/scrolls-work")))
    ap.add_argument("--out-dir", default=os.path.join(os.path.expanduser("~/scrolls-work"), "thresholds", "results"))
    ap.add_argument("--segments", nargs="+", choices=list(SEGMENTS))
    ap.add_argument("--tag", default="", help="suffix for the output file name")
    a = ap.parse_args()
    if a.segments:
        ACTIVE[:] = a.segments
    os.makedirs(a.out_dir, exist_ok=True)
    for p in (["part1", "part2", "part3"] if a.part == "all" else [a.part]):
        t0 = time.time()
        r = globals()[p](a.work)
        r["_seconds"] = round(time.time() - t0)
        with open(os.path.join(a.out_dir, f"{p}{a.tag}.json"), "w") as fh:
            json.dump(r, fh, indent=1)
        print(p, "written", r["_seconds"], "s", flush=True)


if __name__ == "__main__":
    main()
