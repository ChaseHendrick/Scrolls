"""Forward against depth-reversed ink maps: the area ratio at rising thresholds, and its trend.

  python -m kit dirtrend FORWARD REVERSE [--surface SURFACE.zarr] [--region MASK] [--crop Y0 Y1 X0 X1]
                         [--thresholds 0.5 0.6 0.7 0.8 0.9] [--decode none|ls] [--min-pixels 50]
                         [--min-gain 0.05] [--min-coverage 0.9] [--json]

Why (Community report, freek_cool, Discord #ink-detection, 2026-08-31, thread "A read-out rule for
--direction both", code https://github.com/FreekCool/vesuvius-ink-harness): running a model on the
depth-reversed surface volume is villa's own control, but nothing said what to conclude when both
directions look alike. On PHerc. 1447 one checkpoint put 3.6 to 5.2 % of the surface above p = 0.5,
and the reversed run did the same in unrelated places, forward/reversed area ratio 0.45 to 1.09. On
labelled in-domain PHerc0172 crops the ratio was 1.08 to 35. A bare "ratio above 1" did not separate
the two, because the in-domain minimum sat below the 1447 maximum. The trend did: in-domain the
asymmetry strengthened with the threshold in 6 of 6 series, and on 1447 it weakened in 6 of 6. The
pixels a model is surest of are, on real ink, the most dependent on depth order. His proposed rule:
report the forward/reversed ratio, not just the forward map. One volume, one checkpoint; descriptive.

What this computes, per threshold t: the share of counted pixels at or above t in each map, the ratio
(forward + 1) / (reverse + 1) of those counts (identical maps give exactly 1), and the overlap of the
two pixel sets (Jaccard, and the share of forward pixels also above t in reverse); once per pair, the
Pearson correlation of the two maps. Each row is paired (both maps have at least min_pixels above t),
reverse-empty (only the forward map does), forward-empty or both-empty. The trend is the least-squares
slope of log ratio against t over the paired rows, and the gain is the last paired ratio over the first.

Verdicts (Interpretation of his rule; descriptive, never a reading):
  strengthening  basis trend: slope > 0, gain above 1 + min_gain, last paired ratio above 1, and log gain
                 at least 3 times its counting noise (the four counts as Poisson counts; ours, and a floor,
                 since pixels in blobs are not independent; on 1,000 pairs of independent noise maps of
                 one distribution it called nothing but flat). Basis
                 reverse-empties: the forward map's top row with min_pixels is reverse-empty, its ratio
                 bound is at least 2 (ours), and the paired rows below do not weaken; the reverse map ran
                 out first, the limit of strengthening, where a ratio can only be bounded. Either way the
                 map depends on depth order the way labelled ink did. Necessary, not sufficient: it is
                 not evidence of letters.
  flat           paired rows with no trend either way, or a rising trend contradicted by a forward-empty
                 row (the reversed map holds the surest pixels): the asymmetry does not grow with the threshold.
                 By this rule, do not treat the forward map as ink evidence. A steady large ratio is
                 outside what the rule was built on; the ratios are printed.
  weakening      slope < 0, gain below 1 / (1 + min_gain), log gain at most -3 times its counting noise:
                 the surest pixels are the least dependent on
                 depth order, as on 1447. Do not treat the forward map as ink evidence.
  blank          the forward map has fewer than min_pixels above the lowest threshold and the counted
                 pixels have CT under them (coverage at least min_coverage). A blank map is not "no
                 ink"; it says only that this model put nothing above t where there was scan to read.
  blank-unchecked  the same, but coverage is unknown (no --surface) or below min_coverage. After inkdx
                 (Community report, anshu231 and Abd Elilah, Discord #ink-detection, 2026-07-30 to
                 2026-08-05, https://github.com/ash9241/inkdx commit 4977ff4): a no-ink call needs CT
                 coverage of at least 0.9, because 30 of 36 published surface predictions put more than
                 10 % of their sheet on CT that is identically zero, and a region picked by prediction
                 alone gave a confident "no ink" off 0 % CT. Suspect calls (flat, weakening) stay valid
                 at partial coverage; the coverage is printed beside every call.
  too-few-pixels fewer than two paired rows and no reverse-empty top row.
  void           the built-in A/A check failed: the forward map read against itself must come out flat
                 with every ratio exactly 1. If it does not, the code is broken, not the map.

Counted pixels: inside --crop and --region (pixels > 0) when given; finite in both maps; and, with
--surface (the rendered surface volume, zarr), only where the volume is above 0 in every layer. CT
coverage is the share of the region (or of the whole crop when no region is given) that has CT in every
layer; with the whole grid as denominator, mesh-free corners count against coverage, which is the safe
side for a blank call. Give --region (the mesh's valid pixels or a supervision mask) to measure a
segment fairly.

Calibrate before trusting it: run it on a labelled public segment (PHerc0841 w00 or ag896 forward and
reverse maps) with the same model. If that does not read strengthening, the rule says nothing about that
model. Needs numpy (and tifffile or PNG maps; zarr for --surface).
"""

import json
import math
import sys

from .verify import VerifyError, _numpy

THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)
MIN_PIXELS = 50
MIN_GAIN = 0.05
MIN_Z = 3.0                  # ours: log gain over its Poisson counting noise, for a trend call
MIN_COVERAGE = 0.9           # inkdx's NO_INK_EVIDENCE floor (commit 4977ff4)
REVERSE_EMPTY_RATIO = 2.0    # ours: the bound (forward + 1) / (reverse + 1) a reverse-empty top row needs
ROWS = 512                   # rows per block, so a whole-segment map stays within memory
EXIT = {"strengthening": 0, "flat": 0, "weakening": 0, "blank": 0, "blank-unchecked": 3, "too-few-pixels": 3,
        "no-pixels": 3, "void": 1}


def unit(np, a, decode="none"):
    """A map as float32 probabilities: uint8 / 255, uint16 / 65535, floats as they are (a float map above 1 is
    divided by 255 or 65535, as kit ensemble does); decode ls undoes villa's label smoothing."""
    from .ensemble import decode_values
    a = np.asarray(a)
    if decode == "ls" or a.dtype in (np.uint8, np.uint16):
        return decode_values(a, decode)
    v = a.astype(np.float32)
    finite = v[np.isfinite(v)]
    top = float(finite.max()) if finite.size else 1.0
    return v / (255.0 if top <= 255 else 65535.0) if top > 1.0 else v


def _counts(np, fwd, rev, keep, thresholds, rows=ROWS):
    """Per threshold: forward count, reverse count, both; and the sums for one Pearson r. Row blocks."""
    k = len(thresholds)
    f_n, r_n, both = [0] * k, [0] * k, [0] * k
    n = 0
    sf = sr = sff = srr = sfr = 0.0
    for r0 in range(0, fwd.shape[0], rows):
        sel = keep[r0:r0 + rows]
        f = fwd[r0:r0 + rows][sel].astype(np.float64)
        r = rev[r0:r0 + rows][sel].astype(np.float64)
        if not f.size:
            continue
        n += f.size
        sf, sr = sf + f.sum(), sr + r.sum()
        sff, srr, sfr = sff + (f * f).sum(), srr + (r * r).sum(), sfr + (f * r).sum()
        for i, t in enumerate(thresholds):
            fa, ra = f >= t, r >= t
            f_n[i] += int(fa.sum())
            r_n[i] += int(ra.sum())
            both[i] += int((fa & ra).sum())
    corr = None
    if n > 1:
        vf, vr = sff - sf * sf / n, srr - sr * sr / n
        if vf > 1e-12 * n and vr > 1e-12 * n:
            corr = (sfr - sf * sr / n) / math.sqrt(vf * vr)
    return n, f_n, r_n, both, corr


def _trend(rows, min_gain, min_z=None):
    """(slope of log ratio against threshold, gain, call, basis) over the rows where both maps have min_pixels."""
    min_z = MIN_Z if min_z is None else min_z
    paired = [r for r in rows if r["kind"] == "paired"]
    slope = gain = None
    call = "too-few-pixels"
    if len(paired) >= 2:
        ts = [r["threshold"] for r in paired]
        ls = [math.log(r["ratio"]) for r in paired]
        mt, ml = sum(ts) / len(ts), sum(ls) / len(ls)
        den = sum((t - mt) ** 2 for t in ts)
        slope = sum((t - mt) * (v - ml) for t, v in zip(ts, ls)) / den if den else 0.0
        gain = paired[-1]["ratio"] / paired[0]["ratio"]
        # counting noise of log(gain), the four counts taken as independent Poisson counts (pixels in blobs are
        # not independent, so this is a floor on the noise, not its size)
        first, last = paired[0], paired[-1]
        se = math.sqrt(sum(1.0 / (first[k] + 1) + 1.0 / (last[k] + 1) for k in ("forward_px", "reverse_px")))
        z = math.log(gain) / se
        if slope > 0 and gain > 1 + min_gain and last["ratio"] > 1 and z >= min_z:
            call = "strengthening"
        elif slope < 0 and gain < 1 / (1 + min_gain) and z <= -min_z:
            call = "weakening"
        else:
            call = "flat"
    # A forward map that runs out while the reversed one still holds pixels contradicts a rising trend: the surest
    # pixels are then the reversed map's
    if call == "strengthening" and any(r["kind"] == "forward-empty" for r in rows):
        call = "flat"
    # The reverse map running out while the forward map still holds pixels is the limit of strengthening: the
    # ratio there cannot be measured, only bounded. It counts when it is the forward map's top used threshold, the
    # bound is at least REVERSE_EMPTY_RATIO, and the paired rows below it do not weaken.
    top = [r for r in rows if r["forward_px"] >= r["min_px"]]
    if top and top[-1]["kind"] == "reverse-empty" and top[-1]["ratio"] >= REVERSE_EMPTY_RATIO and \
            call != "weakening":
        return slope, gain, "strengthening", "reverse-empties"
    return slope, gain, call, "trend" if paired else None


def _table(np, fwd, rev, keep, thresholds, min_pixels, min_gain):
    n, f_n, r_n, both, corr = _counts(np, fwd, rev, keep, thresholds)
    rows = []
    for t, a, b, c in zip(thresholds, f_n, r_n, both):
        union = a + b - c
        kind = ("paired" if min(a, b) >= min_pixels else "reverse-empty" if a >= min_pixels else
                "forward-empty" if b >= min_pixels else "both-empty")
        rows.append({"threshold": t, "forward_px": a, "reverse_px": b,
                     "forward_area": round(a / n, 6) if n else None, "reverse_area": round(b / n, 6) if n else None,
                     "ratio": (a + 1) / (b + 1), "jaccard": round(c / union, 4) if union else None,
                     "forward_shared": round(c / a, 4) if a else None, "kind": kind, "min_px": min_pixels})
    slope, gain, call, basis = _trend(rows, min_gain)
    if n and f_n[0] < min_pixels:
        call, basis = "blank", None
    if not n:
        call, basis = "no-pixels", None
    for r in rows:
        r["ratio"] = round(r["ratio"], 4)
        del r["min_px"]
    return {"pixels": n, "rows": rows, "pearson_r": None if corr is None else round(corr, 4),
            "slope": None if slope is None else round(slope, 4), "gain": None if gain is None else round(gain, 4),
            "call": call, "basis": basis}


def ct_columns(np, volume, rows=ROWS, box=None, layers=None):
    """Pixels where a surface volume (z, y, x array-like) is above 0 in every layer of [a, b) (default all), inside
    box (y0, y1, x0, x1), read in row blocks."""
    z, h, w = (int(s) for s in volume.shape)
    y0, y1, x0, x1 = box or (0, h, 0, w)
    a, b = layers or (0, z)
    ok = np.zeros((y1 - y0, x1 - x0), bool)
    for r0 in range(y0, y1, rows):
        blk = np.asarray(volume[a:b, r0:min(r0 + rows, y1), x0:x1])
        ok[r0 - y0:r0 - y0 + blk.shape[1]] = (blk > 0).all(0)
    return ok


def readout(fwd, rev, ct=None, region=None, thresholds=THRESHOLDS, min_pixels=MIN_PIXELS, min_gain=MIN_GAIN,
            min_coverage=MIN_COVERAGE, decode="none"):
    """The readout of two maps on one grid (arrays). ct: pixels with CT under them, or None (unknown); region:
    pixels that belong to the surface being judged, or None (the whole grid)."""
    np = _numpy()
    fwd, rev = np.squeeze(np.asarray(fwd)), np.squeeze(np.asarray(rev))
    if fwd.ndim != 2 or fwd.shape != rev.shape:
        raise VerifyError(f"the maps must be 2D and of one shape, got {fwd.shape} and {rev.shape}")
    thresholds = sorted(float(t) for t in thresholds)
    if not thresholds or any(not 0.0 < t < 1.0 for t in thresholds) or len(set(thresholds)) != len(thresholds):
        raise VerifyError("thresholds are distinct probabilities strictly between 0 and 1")
    if min_pixels < 1 or min_gain < 0 or not 0.0 < min_coverage <= 1.0:
        raise VerifyError("min_pixels is at least 1, min_gain at least 0, min_coverage in (0, 1]")
    f, r = unit(np, fwd, decode), unit(np, rev, decode)
    keep = np.isfinite(f) & np.isfinite(r)
    area = np.ones(f.shape, bool)
    for name, m in (("region", region), ("ct", ct)):
        if m is not None and np.asarray(m).shape != f.shape:
            raise VerifyError(f"{name} mask {np.asarray(m).shape} differs from the maps' {f.shape}")
    if region is not None:
        area = np.asarray(region, bool)
        keep &= area
    coverage = None
    if ct is not None:
        ct = np.asarray(ct, bool)
        denom = int(area.sum())
        coverage = round(int((ct & area).sum()) / denom, 4) if denom else 0.0
        keep &= ct
    res = _table(np, f, r, keep, thresholds, min_pixels, min_gain)
    # A/A: the forward map against itself must read flat, every ratio exactly 1 (or blank / no pixels when the
    # forward map is). A rule that cannot call identical maps flat cannot be trusted on different ones.
    aa = _table(np, f, f, keep, thresholds, min_pixels, min_gain)
    aa_ok = all(row["ratio"] == 1.0 for row in aa["rows"]) and aa["call"] in ("flat", "blank", "no-pixels",
                                                                              "too-few-pixels")
    call = res["call"]
    if not aa_ok:
        call = "void"
    elif call == "blank" and (coverage is None or coverage < min_coverage):
        call = "blank-unchecked"
    res.update(call=call, aa_check="pass" if aa_ok else "fail", ct_coverage=coverage, min_coverage=min_coverage,
               coverage_of="region" if region is not None else "grid", thresholds=thresholds, min_pixels=min_pixels,
               min_gain=min_gain, decode=decode, meaning=MEANING[call],
               note="model output, not a reading; strengthening is necessary for ink evidence, not sufficient")
    if coverage is not None and coverage < min_coverage and call not in ("blank-unchecked", "void"):
        res["warning"] = (f"CT under {coverage:.1%} of the {res['coverage_of']}: counts cover the scanned part only; "
                          "no blank or no-ink call is possible here")
    return res


MEANING = {
    "strengthening": "the forward map's surest pixels outnumber the reversed map's more as the threshold rises; on "
                     "labelled PHerc0841 crops (12 Oct 2026) this held even where the reversed map scored the higher "
                     "AUC, so it is a record, not ink evidence, and never a reading",
    "flat": "the asymmetry does not grow with the threshold: by this rule, do not treat the forward map as ink "
            "evidence",
    "weakening": "the surest pixels are the least dependent on depth order: do not treat the forward map as ink "
                 "evidence",
    "blank": "nothing above the lowest threshold where there was CT to read; not evidence that there is no ink",
    "blank-unchecked": "nothing above the lowest threshold, but CT coverage is unknown or below the floor: no call",
    "too-few-pixels": "fewer than two thresholds with enough pixels in both maps: no call",
    "no-pixels": "no pixel to count (region, CT and finite values leave none): no call",
    "void": "the A/A check failed (a map against itself did not read flat): the readout is broken, no call",
}


def _crop(a, crop):
    if crop is None:
        return a
    y0, y1, x0, x1 = crop
    return a[y0:y1, x0:x1]


def readout_files(forward, reverse, surface=None, region=None, crop=None, level="0", **kw):
    np = _numpy()
    from .ensemble import _read
    fwd, rev = np.squeeze(_read(forward)), np.squeeze(_read(reverse))
    if fwd.shape != rev.shape:
        raise VerifyError(f"{forward} {fwd.shape} and {reverse} {rev.shape} differ in shape")
    if crop is not None:
        y0, y1, x0, x1 = crop
        if not (0 <= y0 < y1 <= fwd.shape[0] and 0 <= x0 < x1 <= fwd.shape[1]):
            raise VerifyError(f"crop {list(crop)} is not inside the maps' {fwd.shape}")
    reg = None
    if region is not None:
        reg = np.squeeze(_read(region)) > 0
        if reg.shape != fwd.shape:
            raise VerifyError(f"region {region} {reg.shape} differs from the maps' {fwd.shape}")
        reg = _crop(reg, crop)
    ct = None
    if surface is not None:
        from . import s3retry
        try:
            s3retry.refuse_remote(surface, "kit dirtrend --surface")
        except ValueError as exc:
            raise VerifyError(str(exc)) from None
        from .layers import open_volume
        vol = open_volume(surface, level)
        if tuple(int(s) for s in vol.shape[1:]) != fwd.shape:
            raise VerifyError(f"surface volume {surface} rows x cols {tuple(vol.shape[1:])} differ from the maps' "
                              f"{fwd.shape}")
        ct = ct_columns(np, vol, box=crop)
    res = readout(_crop(fwd, crop), _crop(rev, crop), ct=ct, region=reg, **kw)
    res["inputs"] = {"forward": str(forward), "reverse": str(reverse),
                     "surface": None if surface is None else str(surface),
                     "region": None if region is None else str(region), "crop": None if crop is None else list(crop)}
    return res


def format_result(res):
    lines = [f"direction readout: {res['call']} ({res['meaning']})",
             f"pixels counted {res['pixels']}, Pearson r {res['pearson_r']}, slope of log ratio {res['slope']}, "
             f"gain {res['gain']}, A/A {res['aa_check']}",
             "CT coverage: " + ("unknown (no --surface)" if res["ct_coverage"] is None else
                                f"{res['ct_coverage']:.1%} of the {res['coverage_of']} "
                                f"(floor {res['min_coverage']:.0%})"),
             "  t      forward     reverse     ratio   jaccard  rows"]
    for r in res["rows"]:
        lines.append(f"  {r['threshold']:<5}  {r['forward_px']:>10}  {r['reverse_px']:>10}  {r['ratio']:>8}  "
                     f"{'-' if r['jaccard'] is None else r['jaccard']:>7}  {r['kind']}")
    if res.get("warning"):
        lines.append("warning: " + res["warning"])
    lines.append(res["note"])
    return "\n".join(lines)


def build_parser(p):
    p.add_argument("forward", help="forward ink map (.tif, .png or .npy)")
    p.add_argument("reverse", help="the same model on the depth-reversed surface volume, same grid")
    p.add_argument("--surface", metavar="SURFACE.zarr",
                   help="the rendered surface volume: count only pixels with CT in every layer, and measure coverage")
    p.add_argument("--level", default="0", help="OME-Zarr level of --surface when it is a group")
    p.add_argument("--region", metavar="MASK", help="pixels > 0 belong to the surface judged (mesh valid area or a "
                                                    "supervision mask); the coverage denominator")
    p.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"), help="read only this window")
    p.add_argument("--thresholds", type=float, nargs="+", default=list(THRESHOLDS))
    p.add_argument("--decode", choices=("none", "ls"), default="none",
                   help="ls: villa label-smoothed maps (uint8 v -> clip((v-64)/128, 0, 1))")
    p.add_argument("--min-pixels", type=int, default=MIN_PIXELS,
                   help="pixels above t a map needs for its count to be used")
    p.add_argument("--min-gain", type=float, default=MIN_GAIN, help="last ratio over first must pass 1 + this")
    p.add_argument("--min-coverage", type=float, default=MIN_COVERAGE, help="CT coverage a blank call needs")
    p.add_argument("--json", action="store_true")


def cmd_dirtrend(args):
    try:
        res = readout_files(args.forward, args.reverse, args.surface, args.region,
                            tuple(args.crop) if args.crop else None, args.level, thresholds=args.thresholds,
                            min_pixels=args.min_pixels, min_gain=args.min_gain, min_coverage=args.min_coverage,
                            decode=args.decode)
    except (VerifyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2) if args.json else format_result(res))
    return EXIT[res["call"]]


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="kit dirtrend", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    build_parser(p)
    return cmd_dirtrend(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
