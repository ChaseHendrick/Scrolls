"""Pixel AUC of an ink map against a segment's published ink labels.

On a labelled segment no model was trained on (PHerc0139 w045 for ink_9um and v8in), this
is the generalization number: the chance that a labelled ink pixel scores above a
labelled non-ink pixel. Only pixels inside the supervision mask count, because the
labellers marked ink and non-ink there and nowhere else. Reference values (Community
reports, not checked here): `ink_9um` on PHerc0841 team surfaces, 0.74 to 0.81 (Bullo27);
on the PHerc0139 title, 0.81 to 0.95 depending on the checkpoint (Nieuwlaar).

The labels sit on the 2.4 um scan's grid. Its pyramid level 2 is the 9 um surface grid up
to a uniform scale (w045: 5,820 x 8,020 labels for 5,980 x 8,240 surface pixels), so labels
are mapped onto the map by nearest neighbour, and a scale that differs between the axes is
refused. A map that covers only a window of the surface gives that window with `crop` and
the full surface shape with `surface_shape`.

The reverse-direction map is the control: it reads the same CT, so it is shown the same
ink, but in the wrong depth order. A forward AUC well above the reverse AUC says the model
reads ink, not just brightness.

Pixels where the map is exactly 0 are left out by default: villa and v8in write 0 where
they made no prediction (outside the surface). The count is reported.
"""

from .layers import _zarr
from .verify import VerifyError, _numpy, load_map

DEFAULT_LEVEL = "2"
MAX_AXIS_MISMATCH = 0.005


def _load(path):
    np = _numpy()
    if str(path).endswith(".npy"):
        return np.load(path)
    return load_map(path)


def _levels(path, level):
    zarr = _zarr()
    node = zarr.open(str(path), mode="r")
    if not hasattr(node, "shape"):
        if level not in node:
            raise VerifyError(f"{path}: no level {level!r}; levels: {sorted(node.keys())}")
        node = node[level]
    return node


def _quantize(np, values):
    """Integer scores for exact histogram AUC: uint8 and uint16 as is, floats to 0..65535."""
    if values.dtype in (np.uint8, np.uint16):
        return values.astype(np.int64), 65536
    v = values.astype(np.float64)
    top = float(v.max()) if v.size else 1.0
    if top > 1.0:
        v = v / (255.0 if top <= 255 else 65535.0)
    return np.clip(np.round(v * 65535), 0, 65535).astype(np.int64), 65536


def auc_scores(ink_scores, background_scores):
    """Mann-Whitney AUC with ties counted half, from two integer score arrays."""
    np = _numpy()
    if len(ink_scores) == 0 or len(background_scores) == 0:
        return None
    a, n = _quantize(np, ink_scores)
    b, _ = _quantize(np, background_scores)
    ha = np.bincount(a, minlength=n).astype(np.float64)
    hb = np.bincount(b, minlength=n).astype(np.float64)
    below = np.concatenate(([0.0], np.cumsum(hb)[:-1]))  # background strictly below each score
    wins = float((ha * below).sum() + 0.5 * (ha * hb).sum())
    return wins / (float(ha.sum()) * float(hb.sum()))


def label_grid(labels_shape, surface_shape, crop, map_shape):
    """Row and column indices into the labels for every map pixel (nearest neighbour)."""
    np = _numpy()
    sy = labels_shape[0] / surface_shape[0]
    sx = labels_shape[1] / surface_shape[1]
    if abs(sy - sx) > MAX_AXIS_MISMATCH * max(sy, sx):
        raise VerifyError(f"labels {labels_shape} and surface {surface_shape} differ in scale between axes "
                          f"({sy:.4f} vs {sx:.4f}); they are not the same grid")
    y0, y1, x0, x1 = crop if crop is not None else (0, surface_shape[0], 0, surface_shape[1])
    if (y1 - y0, x1 - x0) != tuple(map_shape):
        raise VerifyError(f"map shape {tuple(map_shape)} does not match the window {y1 - y0} x {x1 - x0}")
    rows = np.minimum(((np.arange(y0, y1) + 0.5) * sy).astype(np.int64), labels_shape[0] - 1)
    cols = np.minimum(((np.arange(x0, x1) + 0.5) * sx).astype(np.int64), labels_shape[1] - 1)
    return rows, cols


def score_array(prediction, ink, mask, keep_zero=False):
    """AUC of a 2D map against same-shape boolean ink and mask arrays."""
    np = _numpy()
    use = mask & (np.ones_like(mask) if keep_zero else prediction != 0)
    result = {
        "auc": auc_scores(prediction[use & ink], prediction[use & ~ink]),
        "ink_px": int((use & ink).sum()),
        "background_px": int((use & ~ink).sum()),
        "unpredicted_px_in_mask": int((mask & (prediction == 0)).sum()),
    }
    if result["auc"] is not None:
        result["auc"] = round(result["auc"], 4)
    return result


def score_files(prediction, labels, mask, control=None, level=DEFAULT_LEVEL, crop=None,
                surface_shape=None, keep_zero=False):
    np = _numpy()
    pred = np.squeeze(_load(prediction))
    if pred.ndim != 2:
        raise VerifyError(f"{prediction}: expected a 2D map, got shape {pred.shape}")
    if surface_shape is None:
        if crop is not None:
            raise VerifyError("a cropped map needs the full surface shape (surface_shape)")
        surface_shape = pred.shape
    lab = _levels(labels, level)
    msk = _levels(mask, level)
    if lab.shape != msk.shape:
        raise VerifyError(f"labels {lab.shape} and mask {msk.shape} differ in shape at level {level}")
    rows, cols = label_grid(lab.shape, surface_shape, crop, pred.shape)
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    ink = np.asarray(lab[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    supervised = np.asarray(msk[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    result = {"forward": score_array(pred, ink, supervised, keep_zero),
              "files": {"prediction": str(prediction), "labels": str(labels), "mask": str(mask),
                        "control": None if control is None else str(control)},
              "level": level, "crop": crop}
    if control is not None:
        ctrl = np.squeeze(_load(control))
        if ctrl.shape != pred.shape:
            raise VerifyError(f"control shape {ctrl.shape} differs from the map's {pred.shape}")
        result["control"] = score_array(ctrl, ink, supervised, keep_zero)
    return result


def format_result(result):
    def line(label, r):
        if r["auc"] is None:
            return f"{label}: no AUC (ink {r['ink_px']} px, background {r['background_px']} px in the mask)"
        return (f"{label}: AUC {r['auc']:.4f} on {r['ink_px']} ink and {r['background_px']} background px"
                + (f" ({r['unpredicted_px_in_mask']} unpredicted px in the mask left out)" if r["unpredicted_px_in_mask"] else ""))

    rows = [line("map    ", result["forward"])]
    if "control" in result:
        rows.append(line("control", result["control"]))
        f, c = result["forward"]["auc"], result["control"]["auc"]
        if f is not None and c is not None:
            rows.append(f"map minus control: {f - c:+.4f} (near 0 means the model is not reading ink in this direction)")
    return "\n".join(rows)
