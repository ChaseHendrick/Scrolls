"""Small, independently testable data guards for the unrun lane H job."""
import math
import numpy as np

VILLA_REVISION = 'e0bbb8b40a2db58b1d71864f286eb85717e59e64'
CHECKPOINT_REVISION = '7109667e2607db1b90c37c8b09cb876ea7fe7bb1'
CHECKPOINT_SHA256 = 'e635558ae6a1a807a7e5ec1e83adfd45bc3c0ac53883ea43f1d4e085d62a9cab'


def validate_boxes(shape, boxes, gap, patch):
    if len(shape) != 2 or min(shape) < 1 or patch < 1 or patch > min(shape) or gap < 0:
        raise ValueError('require positive canvas/patch sizes and a nonnegative gap')
    if not boxes:
        raise ValueError('at least one excluded evaluation box is required')
    for box in boxes:
        if len(box) != 4 or not all(isinstance(x, (int, np.integer)) for x in box):
            raise ValueError('excluded boxes must contain four integer coordinates')
        y0, y1, x0, x1 = box
        if not (0 <= y0 < y1 <= shape[0] and 0 <= x0 < x1 <= shape[1]):
            raise ValueError('excluded box must lie inside the full canvas')


def allowed_mask(shape, boxes, gap, patch):
    """Allowed top-left coordinates; whole patches avoid every half-open box plus gap."""
    validate_boxes(shape, boxes, gap, patch)
    ok = np.ones(shape, bool)
    ok[shape[0] - patch + 1:, :] = False
    ok[:, shape[1] - patch + 1:] = False
    for y0, y1, x0, x1 in boxes:
        ok[max(0, y0 - gap - patch + 1):min(shape[0], y1 + gap),
           max(0, x0 - gap - patch + 1):min(shape[1], x1 + gap)] = False
    return ok


def exclude_targets(weight, boxes, gap, patch):
    validate_boxes(weight.shape, boxes, gap, patch)
    out = weight.copy()
    for y0, y1, x0, x1 in boxes:
        out[max(0, y0 - gap):min(out.shape[0], y1 + gap),
            max(0, x0 - gap):min(out.shape[1], x1 + gap)] = 0
    return out


def pseudo_targets(prediction, ink_thr, bg_thr):
    if not (math.isfinite(ink_thr) and math.isfinite(bg_thr) and 0 <= bg_thr < ink_thr <= 1):
        raise ValueError('require 0 <= bg threshold < ink threshold <= 1')
    raw = np.asarray(prediction)
    if raw.ndim != 2 or raw.dtype != np.uint8 and raw.dtype.kind != 'f':
        raise ValueError('pseudo map must be a 2D uint8 map or floating probabilities')
    values = raw.astype(np.float32)
    if raw.dtype == np.uint8:
        values /= 255.0  # Quantization is a dtype contract, not a guess from the maximum.
    if not np.isfinite(values).all() or values.min() < 0 or values.max() > 1:
        raise ValueError('pseudo probabilities must be finite and inside [0,1]')
    ink = values >= ink_thr
    # Stored zero can mean uncovered inference; conservatively leave it unknown.
    weight = (values > 0) & (ink | (values <= bg_thr))
    return ink.astype(np.float32), weight.astype(np.float32)


def pooled_targets(functional, target, weight, output_shape):
    """Pool only known labels; unknown values cannot become background evidence."""
    known = target.where(weight > 0, target.new_zeros(()))
    fraction = functional.adaptive_avg_pool2d(weight, output_shape)
    numerator = functional.adaptive_avg_pool2d(known * weight, output_shape)
    labels = numerator / fraction.clamp_min(1e-12)
    return (labels > .5).float(), (fraction > .5).float()
