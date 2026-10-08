"""Text-row periodicity score for an ink map: a triage aid, not a verdict.

Port of Bullo27's `analysis/rowscore.py` (https://github.com/Bullo27/first-letters-survey,
MIT, commit a5f9c51, read 2026-10-07). Greek text sits in rows a few millimetres apart, so
an ink map that shows text carries a spectral peak at a 2.5 to 8 mm period in one
direction. The score is the peak power in that band over the band's median power,
computed on the largest connected piece of the mapped surface.

Reference values reported there (Community report, not checked here): PHerc0139 w045 and
w033 score 73 to 148; 65 automatic patches on eligible scrolls score 2.5 to 33.5;
and 6 cm2 tiles of the controls score 6.8 to 77.4, which overlaps the negatives. So a low
score on a small patch proves little, and a high score is a place to look, not ink. The
verdict stays visual.

Differences from the original: numpy reimplements OpenCV's area and nearest resizes, a box-sum
erosion replaces cv2.erode, and scipy.ndimage (in villa's environment) finds the largest
piece; without scipy that step is skipped and the result says so. Several maps (e.g. two
checkpoints) are averaged before scoring, as Bullo27 found averaging raises the score on
real text (w045: 84 and 111 alone, 125 averaged).
"""

from .verify import VerifyError, _numpy, load_map

DOWNSAMPLE = 4
ERODE_PX = 31
MIN_VALID_PX = 5000
MIN_BAND_BINS = 20
PERIOD_MM = (2.5, 8.0)


def _normalize(np, array):
    a = array.astype(np.float32)
    top = float(a.max()) if a.size else 0.0
    if top > 1.5:
        a = a / (255.0 if top <= 255 else 65535.0)
    return a


def _area_weights(np, n_in, n_out):
    """(n_out, n_in) matrix averaging each output cell's span of inputs, with fractional
    edge weights: OpenCV's INTER_AREA when shrinking."""
    scale = n_in / n_out
    starts = np.arange(n_out) * scale
    edges = np.arange(n_in + 1, dtype=np.float64)
    lo = np.maximum(edges[None, :-1], starts[:, None])
    hi = np.minimum(edges[None, 1:], starts[:, None] + scale)
    return (np.clip(hi - lo, 0, None) / scale).astype(np.float32)


def _area_resize(np, a, k):
    h, w = a.shape[0] // k, a.shape[1] // k
    return _area_weights(np, a.shape[0], h) @ a @ _area_weights(np, a.shape[1], w).T


def _sparse_area_weights(np, n_in, n_out):
    """The same float32 cell overlaps as _area_weights, stored without zero entries."""
    try:
        from scipy.sparse import csr_matrix
    except ImportError as exc:
        raise VerifyError("--fast-resize requires scipy; omit it for the original dense resize") from exc
    scale = n_in / n_out
    starts = np.arange(n_out) * scale
    rows, cols = [], []
    for row, start in enumerate(starts):
        indices = range(max(0, int(np.floor(start))), min(n_in, int(np.ceil(start + scale))))
        cols.extend(indices)
        rows.extend([row] * len(indices))
    rows = np.asarray(rows, dtype=np.int64)
    cols = np.asarray(cols, dtype=np.int64)
    lo = np.maximum(cols, starts[rows])
    hi = np.minimum(cols + 1, starts[rows] + scale)
    weights = (np.clip(hi - lo, 0, None) / scale).astype(np.float32)
    result = csr_matrix((weights, (rows, cols)), shape=(n_out, n_in))
    result.eliminate_zeros()
    return result


def _sparse_area_resize(np, a, k):
    """Resize finite clipped row-score values; summation order can differ from dense BLAS."""
    h, w = a.shape[0] // k, a.shape[1] // k
    rows = _sparse_area_weights(np, a.shape[0], h)
    cols = _sparse_area_weights(np, a.shape[1], w)
    return cols.dot(rows.dot(a).T).T


def _nearest_resize(np, mask, shape):
    rows = np.floor(np.arange(shape[0]) * (mask.shape[0] / shape[0])).astype(int)
    cols = np.floor(np.arange(shape[1]) * (mask.shape[1] / shape[1])).astype(int)
    return mask[np.ix_(rows, cols)]


def _erode(np, mask, size):
    """Binary erosion with a size x size square, via a summed-area table.

    Outside the image counts as set, as in cv2.erode's default border, so the image edge
    itself does not erode."""
    r = size // 2
    padded = np.pad(mask.astype(np.int32), r, constant_values=1)
    s = np.pad(padded.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    h, w = mask.shape
    box = s[size:size + h, size:size + w] - s[:h, size:size + w] - s[size:size + h, :w] + s[:h, :w]
    return box == size * size


def _largest_piece(np, mask):
    try:
        from scipy import ndimage
    except ImportError:
        return mask, None, False
    labels, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return mask, None, True
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    piece = labels == int(np.argmax(sizes))
    rows, cols = np.nonzero(piece)
    box = (rows.min(), rows.max() + 1, cols.min(), cols.max() + 1)
    return piece, box, True


def score_array(array, voxel_um, valid=None, *, fast_resize=False):
    """Row score of one 2D ink map; optional sparse resize can change float32 rounding."""
    np = _numpy()
    a = _normalize(np, np.asarray(array))
    if a.ndim != 2:
        raise VerifyError(f"expected a 2D map, got shape {a.shape}")
    v = np.clip((a - 0.25) / 0.5, 0, 1)
    if valid is None:
        valid = a > 0.01
    k = DOWNSAMPLE
    resize_mode = "dense"
    if fast_resize and np.isfinite(v).all():
        ds = _sparse_area_resize(np, v, k)
        resize_mode = "sparse_area_float32"
    else:
        ds = _area_resize(np, v, k)
        if fast_resize:
            resize_mode = "dense_nonfinite_fallback"
    vm = _nearest_resize(np, valid, ds.shape)
    vm = _erode(np, vm, ERODE_PX)
    vm, box, components = _largest_piece(np, vm)
    if box is not None:
        y0, y1, x0, x1 = box
        ds, vm = ds[y0:y1, x0:x1], vm[y0:y1, x0:x1]
    result = {"valid_px": int(valid.sum()), "largest_piece": components}
    if fast_resize:
        result.update(resize_mode=resize_mode,
                      resize_note="Sparse cell overlaps match dense weights, but float32 accumulation and near-tied FFT peaks can differ.")
    if vm.sum() < MIN_VALID_PX:
        result.update(score=None, reason="too small: the surface needs to be over about 1 cm across")
        return result
    x = ds.copy()
    x[~vm] = ds[vm].mean()
    x = x - x.mean()
    h, w = x.shape
    window = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    power = np.abs(np.fft.fftshift(np.fft.fft2(x * window))) ** 2
    fy = np.fft.fftshift(np.fft.fftfreq(h))
    fx = np.fft.fftshift(np.fft.fftfreq(w))
    FY, FX = np.meshgrid(fy, fx, indexing="ij")
    radius = np.hypot(FY, FX)
    px_mm = k * voxel_um * 1e-3
    band = (radius > px_mm / PERIOD_MM[1]) & (radius < px_mm / PERIOD_MM[0])
    if band.sum() < MIN_BAND_BINS:
        result.update(score=None, reason="band empty: the map is too small for a 2.5 to 8 mm period")
        return result
    in_band = power[band]
    iy, ix = np.unravel_index(int(np.argmax(np.where(band, power, 0))), power.shape)
    vv = v[valid]
    result.update(
        score=round(float(in_band.max() / np.median(in_band)), 1),
        period_mm=round(float(px_mm / radius[iy, ix]), 2),
        angle_deg=round(float(np.degrees(np.arctan2(FY[iy, ix], FX[iy, ix]))), 1),
        mean_ink=round(float(vv.mean()), 4),
        p99=round(float(np.percentile(vv, 99)), 3),
        frac_gt_half=round(float((vv > 0.5).mean()), 4),
    )
    return result


def mean_map(arrays):
    np = _numpy()
    shapes = {tuple(a.shape) for a in arrays}
    if len(shapes) != 1:
        raise VerifyError(f"maps to average differ in shape: {sorted(shapes)}")
    total = np.zeros(arrays[0].shape, dtype=np.float32)
    for a in arrays:
        total += _normalize(np, a)
    return total / len(arrays)


def score_files(forward, voxel_um, reverse=(), *, fast_resize=False):
    """Score the mean of the forward maps and, if given, the mean of the reverse maps."""
    result = {"voxel_um": voxel_um, "forward": score_array(mean_map([load_map(p) for p in forward]), voxel_um, fast_resize=fast_resize),
              "files": {"forward": [str(p) for p in forward], "reverse": [str(p) for p in reverse]}}
    if reverse:
        result["reverse"] = score_array(mean_map([load_map(p) for p in reverse]), voxel_um, fast_resize=fast_resize)
    if fast_resize:
        result["fast_resize"] = True
    return result


def format_result(result):
    def line(label, r):
        if r.get("score") is None:
            return f"{label}: no score ({r['reason']})"
        return (f"{label}: row score {r['score']}, period {r['period_mm']} mm at {r['angle_deg']} deg, "
                f"p99 {r['p99']}, {r['frac_gt_half']:.2%} over 0.5")

    rows = [line("forward", result["forward"])]
    if "reverse" in result:
        rows.append(line("reverse", result["reverse"]))
    if not result["forward"].get("largest_piece"):
        rows.append("note: scipy not found, so the largest-piece step was skipped; thin strips can fake a period")
    if result.get("fast_resize"):
        rows.append("note: --fast-resize changes float32 accumulation; near-tied FFT peaks can differ (see JSON resize_mode)")
    rows.append("triage only: Bullo27 reports held-out controls at 73-148 and 6 cm2 control tiles as low as 6.8. Look at the map.")
    return "\n".join(rows)
