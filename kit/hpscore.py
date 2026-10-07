"""Letter-scale score: correlation of an ink map with the labels after a 48 um high-pass.

Ported from Chris Scheirer's `hp_score.py` and `score_crop.py` (ShribyrLabs/vesuvius-reports,
report 02, MIT). His point: pixel AUC and plain correlation cannot tell letters from ink
blobs, because a blob over a line of text scores well on both, and blurring a map raises
them. Removing a 48 um Gaussian blur from map and key first, then correlating what is left
(edges and strokes at letter scale), separates them: on his scale noise reads 0.01, blobs
0.04, a read where a person made out four letters 0.076, the best 9 um reads 0.11 to 0.14.
Run-to-run noise for one recipe was 0.005.

His key is the team's 2.4 um prediction; here it is the segment's human labels (ink 1,
non-ink 0) inside the supervision mask, so our numbers are on a different scale from his
and compare only with each other, on the same pixels. The null is his: the key rolled by
150, 300 and -300 px (at 9.362 um) along the rows; the largest |r| among them says how much
a misaligned key still scores. A blur raises this score too (his 2026-09-25 caveat), so
compare maps at the same blur.

Needs numpy and scipy.
"""

from .auc import _load, labels_on_map, DEFAULT_LEVEL
from .verify import VerifyError, _numpy

HIGH_PASS_UM = 48.0
NULL_SHIFTS_PX_AT_9362 = (150, 300, -300)


def _gaussian():
    try:
        from scipy.ndimage import gaussian_filter
    except ImportError as exc:
        raise VerifyError("scipy is required for kit hpscore") from exc
    return gaussian_filter


def high_pass(np, gf, img, m, sigma):
    """img minus its Gaussian mean over the pixels in m (normalised convolution)."""
    w = gf(m.astype(np.float64), sigma)
    return img - gf(img * m, sigma) / np.maximum(w, 1e-3)


def _r(np, a, b):
    if a.size < 3 or float(a.std()) == 0.0 or float(b.std()) == 0.0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def score_array(prediction, ink, supervised, voxel_um, inner=0):
    np = _numpy()
    gf = _gaussian()
    sigma = HIGH_PASS_UM / voxel_um
    pred = prediction.astype(np.float64)
    valid = supervised.astype(bool)
    key = np.where(valid, ink.astype(np.float64), 0.0)
    kh = high_pass(np, gf, key, valid, sigma)
    core = valid & (gf(valid.astype(np.float64), 2 * sigma) > 0.999)
    covered = pred > 0
    m = core & covered
    if inner:
        if 2 * inner >= min(pred.shape):
            raise VerifyError(f"inner {inner} leaves nothing of a {pred.shape} map")
        edge = np.zeros_like(m)
        edge[inner:-inner, inner:-inner] = True
        m &= edge
    ph = high_pass(np, gf, pred, covered, sigma)
    r = _r(np, ph[m], kh[m])
    nulls = []
    for s in NULL_SHIFTS_PX_AT_9362:
        s = int(round(s * 9.362 / voxel_um))
        both = m & np.roll(m, s, 0)
        v = _r(np, ph[both], np.roll(kh, s, 0)[both])
        if v is not None:
            nulls.append(abs(v))
    rnd = lambda v: None if v is None else round(v, 4)
    return {"hp_r": rnd(r), "raw_r": rnd(_r(np, pred[m], key[m])), "null_max_abs": rnd(max(nulls) if nulls else None),
            "px": int(m.sum()), "sigma_px": round(sigma, 3), "inner": inner}


def score_files(prediction, labels, mask, voxel_um, control=None, level=DEFAULT_LEVEL, crop=None,
                surface_shape=None, inner=0):
    np = _numpy()
    pred = np.squeeze(_load(prediction))
    if pred.ndim != 2:
        raise VerifyError(f"{prediction}: expected a 2D map, got shape {pred.shape}")
    if surface_shape is None:
        if crop is not None:
            raise VerifyError("a cropped map needs the full surface shape (surface_shape)")
        surface_shape = pred.shape
    ink, supervised = labels_on_map(labels, mask, level, surface_shape, crop, pred.shape)
    result = {"forward": score_array(pred, ink, supervised, voxel_um, inner), "voxel_um": voxel_um, "crop": crop}
    if control is not None:
        ctrl = np.squeeze(_load(control))
        if ctrl.shape != pred.shape:
            raise VerifyError(f"control shape {ctrl.shape} differs from the map's {pred.shape}")
        result["control"] = score_array(ctrl, ink, supervised, voxel_um, inner)
    return result


def format_result(result):
    def line(label, r):
        if r["hp_r"] is None:
            return f"{label}: no score ({r['px']} px with a full {2 * r['sigma_px']:.0f} px labelled neighbourhood)"
        return (f"{label}: letter-scale r {r['hp_r']:+.4f} (raw r {r['raw_r']:+.4f}, rolled-key null |r| <= "
                f"{r['null_max_abs']:.4f}) on {r['px']} px")

    rows = [line("map    ", result["forward"])]
    if "control" in result:
        rows.append(line("control", result["control"]))
    return "\n".join(rows)
