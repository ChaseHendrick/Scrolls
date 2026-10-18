"""Simple scores to compare StrokeNet against. numpy only, except the randcnn baseline, which
needs torch and train.py (imported when it is fitted or scored).

Seven single numbers with no fitting; evaluate.py sets each one's direction per measure on
validation:

  density    window mean. The text and blank labels come partly from ink density, so this shows
             how much of the text-against-blank test the labeling rule alone explains.
  skew       skewness of the window's values. It does not depend on pixel order, bit for bit:
             windows of whole numbers 0..255 (uint8, or floats holding such values) use moments
             of their 256-value histogram, other float windows exactly rounded sums (math.fsum).
             So any permutation of a window scores exactly the same, and the value-keeping nulls
             (iaaft, shuffle, rot90, strip) tie with their source windows (AUC exactly 0.5).
  lines      (v_rows - v_cols) / (v_rows + v_cols + 1e-9) of the normalized window's row-mean and
             column-mean variances: high for horizontal bands such as text lines.
  roughness  log of the mean squared 5-point Laplacian of the normalized window over interior
             pixels: high-frequency energy. IAAFT copies carry excess high-frequency power, so
             this score separates text from its IAAFT copies well away from 0.5; it measures the
             IAAFT residue that T2 must be read against.
  seam8      log(mean |z[:, c+1] - z[:, c]| over the strip seams c = 7, 15, ..., 119 + 1e-6)
             - log(the same over every other c in 0..126 + 1e-6), z the normalized window: a
             detector of the strip null's 8 px seams.
  seam32     the same for the tile seams c = 31, 63, 95, along both axes, the two summed: a
             detector of the tile shuffle's 32 px seams.
  grid       the seam32 construction on the 6.4 px grid of the organizers' prediction tiles
             (overlapping 256 px tiles at stride 128 px on the 2.4 um grid), columns and rows
             round(6.4 k) - 1, both axes summed. The pooled maps carry that grid as lines of
             smaller steps (15 to 25 % smaller than elsewhere, in every segment); windows cut on
             a 32 px stride (5 grid periods) all carry it at one phase, and the tile seams 31,
             63, 95 lie on grid lines, so seam32 is negative on unaltered windows. IAAFT copies,
             strip copies and the jitter windows lose or move the grid, so this one number
             separates windows from those copies with no text signal at all: it is the
             preregistered measure of how much of a null test the grid alone explains.
             (grid_step is the same function under its earlier name.)

Four fitted on training windows only, by L2 logistic regression; they always read
"higher = text":

  spectrum   on spectrum_features: 84 log mean powers of the normalized window minus its mean,
             in 12 radial bands with edges np.geomspace(1, 91, 13) (cycles per window, full
             fft2, so every frequency up to the corner r = 90.5 is in a band) by 8 angular bins
             over [0, pi). 12 of the 96 bins hold no frequency of a 128 x 128 window and are
             dropped by a fixed index list. Fitted on the StrokeNet training mixture. It is not
             blind to IAAFT copies: their excess high-frequency power is visible to it.
  nullspec   on spectrum_features, fitted on training text windows (positives) against their own
             IAAFT-20 copies (negatives). It sees only the power spectrum, so what separates the
             two for it is the IAAFT residue, not letter shapes.
  texture    on spectrum_features + hand_features (84 + 21 = 105 features), fitted on the
             training mixture. hand_features: the seven single numbers above, an
             8-bin gradient-orientation histogram (energy weighted, normalized to sum 1,
             log(h + 1e-6)) and the 0.05, 0.25, 0.5, 0.75, 0.95, 0.99 quantiles of the
             normalized values.
  randcnn    train.Net(width, depth) with frozen random weights (torch.manual_seed(seed)), batch
             norm statistics set by no-gradient passes over the training mixture, and a logistic
             head on the global mean and max of its last feature map.

The caller builds the training windows (uint8 pos and neg arrays, text and its IAAFT copies);
fit_* return dicts of numpy arrays and numbers, save_models and load_models keep them in one npz,
and score_all scores windows with every baseline whose model is given.
"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

NAMES = ("density", "skew", "lines", "roughness", "seam8", "seam32", "grid", "spectrum", "nullspec",
         "texture", "randcnn")
SINGLE = NAMES[:7]
FITTED = NAMES[7:]
N_RAD, N_ANG = 12, 8
R_EDGES = np.geomspace(1.0, 91.0, N_RAD + 1)         # cycles per window
N_ORI = 8
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
STRIP, TILE = 8, 32                                    # seam lattices of the strip and tile nulls
GRID_PX = 6.4          # the organizers' prediction stride, 128 px at 2.4 um, in 48 um pixels
HAND_NAMES = (SINGLE + tuple(f"orient{i}" for i in range(N_ORI))
              + tuple(f"q{q:g}" for q in QUANTILES))


def _lower_median(f):
    """Per-row median taking the lower middle value for an even count, as torch.median does."""
    k = (f.shape[1] - 1) // 2
    return np.partition(f, k, axis=1)[:, k:k + 1]


def normalise(windows):
    """Per window (x - median) / (1.4826 MAD), clipped to -3..20, divided by 5 (as StrokeNet)."""
    x = np.asarray(windows, np.float32)
    f = x.reshape(len(x), -1)
    med = _lower_median(f)
    mad = _lower_median(np.abs(f - med)) * 1.4826
    sd = f.std(axis=1, ddof=1, keepdims=True)          # unbiased, as torch.std
    mad = np.where(mad < 1e-3, sd + 1e-3, mad)
    return (np.clip((f - med) / mad, -3, 20) / 5.0).reshape(x.shape)


def _chunks(n, chunk):
    return [slice(i, min(i + chunk, n)) for i in range(0, n, chunk)]


def _flat(windows):
    """(N, pixels) view of an array of windows (also for N = 0)."""
    w = np.asarray(windows)
    return w.reshape(len(w), int(np.prod(w.shape[1:], dtype=np.int64)))


# ------------------------------------------------------------------ single numbers
def density(windows):
    """Window mean (sum / count in float64: exact and order-free for whole-number windows)."""
    f = _flat(windows)
    return f.astype(np.float64).sum(axis=1) / max(f.shape[1], 1)


def _byte_valued(f):
    if f.dtype == np.uint8:
        return True
    if np.issubdtype(f.dtype, np.integer):
        return f.size == 0 or (f.min() >= 0 and f.max() <= 255)
    return bool(np.all(np.isfinite(f)) and np.all((f >= 0) & (f <= 255)) and np.all(f == np.rint(f)))


def _skew_hist(f):
    """Skewness of rows of whole numbers 0..255 from their histograms. The moments are summed
    over the 256 values in a fixed order, so the result depends only on the histogram."""
    N, n = f.shape
    h = np.bincount((np.arange(N, dtype=np.int64)[:, None] * 256 + f.astype(np.int64)).ravel(),
                    minlength=N * 256).reshape(N, 256)
    mean = (h @ np.arange(256, dtype=np.int64)) / n    # exact integer sums
    m2, m3 = np.zeros(N), np.zeros(N)
    for v in range(256):
        c = h[:, v].astype(np.float64)
        d = v - mean
        m2 += c * d * d
        m3 += c * d * d * d
    m2, m3 = m2 / n, m3 / n
    return np.where(m2 > 1e-12, m3 / np.maximum(m2, 1e-12) ** 1.5, 0.0)


def _skew_fsum(row):
    """Skewness of one row of floats from exactly rounded sums (math.fsum), so order-free."""
    n = row.size
    d = row - math.fsum(row) / n
    m2 = math.fsum(d * d) / n
    m3 = math.fsum(d * d * d) / n
    return m3 / m2 ** 1.5 if m2 > 1e-12 else 0.0


def skew(windows, chunk=1024):
    """Skewness of each window's values, bit for bit independent of pixel order."""
    f = _flat(windows)
    if _byte_valued(f):
        out = [_skew_hist(f[s]) for s in _chunks(len(f), chunk)]
        return np.concatenate(out) if out else np.zeros(0)
    return np.array([_skew_fsum(r) for r in f.astype(np.float64)], np.float64).reshape(len(f))


def _lines_z(z):
    vr = z.mean(axis=2).var(axis=1)          # variance of the row means (down the window)
    vc = z.mean(axis=1).var(axis=1)          # variance of the column means (across)
    return (vr - vc) / (vr + vc + 1e-9)


def _roughness_z(z):
    lap = z[:, :-2, 1:-1] + z[:, 2:, 1:-1]
    lap += z[:, 1:-1, :-2]
    lap += z[:, 1:-1, 2:]
    lap -= 4 * z[:, 1:-1, 1:-1]
    ms = np.einsum("nij,nij->n", lap, lap) / (lap.shape[1] * lap.shape[2])
    # the floor only guards a perfectly flat window (log 0); real windows sit far above it
    return np.log(np.maximum(ms, 1e-30))


def _seam_cols(width, period):
    """Columns c whose step to c + 1 crosses a seam of a period px lattice (c = period - 1, ...)."""
    return np.arange(period - 1, width - 1, period)


def _grid_cols(width, period=GRID_PX):
    """Columns c just before each line of a period px grid (c = round(period k) - 1)."""
    c = np.round(np.arange(1, int(width / period) + 2) * period).astype(np.int64) - 1
    return c[c < width - 1]


def _seam_ratio(d, cols):
    """d: (N, H, W - 1) absolute steps between neighboring columns. log(mean over the columns
    cols + 1e-6) - log(mean over every other column + 1e-6)."""
    m = np.zeros(d.shape[2], bool)
    m[cols] = True
    return np.log(d[:, :, m].mean(axis=(1, 2)) + 1e-6) - np.log(d[:, :, ~m].mean(axis=(1, 2)) + 1e-6)


def _both_axes(z, cols_fn):
    dx = np.abs(np.diff(z, axis=2))
    dy = np.abs(np.diff(z, axis=1)).transpose(0, 2, 1)
    return _seam_ratio(dx, cols_fn(z.shape[2])) + _seam_ratio(dy, cols_fn(z.shape[1]))


def _seam8_z(z):
    return _seam_ratio(np.abs(np.diff(z, axis=2)), _seam_cols(z.shape[2], STRIP))


def _seam32_z(z):
    return _both_axes(z, lambda n: _seam_cols(n, TILE))


def _grid_z(z):
    return _both_axes(z, _grid_cols)


def _orient_z(z):
    """8-bin histogram of gradient orientation over [0, pi) (central differences on interior
    pixels), weighted by squared gradient magnitude, normalized to sum 1, as log(h + 1e-6)."""
    N = len(z)
    gy = (z[:, 2:, 1:-1] - z[:, :-2, 1:-1]) / 2
    gx = (z[:, 1:-1, 2:] - z[:, 1:-1, :-2]) / 2
    e = (gx * gx + gy * gy).reshape(N, -1)
    th = np.arctan2(gy, gx).reshape(N, -1)
    th[th < 0] += np.pi                      # direction to orientation; exactly pi wraps to bin 0
    b = (th * (N_ORI / np.pi)).astype(np.int64) % N_ORI
    h = np.bincount((np.arange(N, dtype=np.int64)[:, None] * N_ORI + b).ravel(), weights=e.ravel(),
                    minlength=N * N_ORI).reshape(N, N_ORI)
    s = h.sum(axis=1, keepdims=True)
    h = np.where(s > 0, h / np.maximum(s, 1e-300), 0.0)
    return np.log(h + 1e-6)


def _per_chunk(windows, fn, chunk=256):
    windows = np.asarray(windows)
    out = [fn(normalise(windows[s]).astype(np.float64)) for s in _chunks(len(windows), chunk)]
    return np.concatenate(out) if out else np.zeros(0)


def lines(windows, chunk=1024):
    return _per_chunk(windows, _lines_z, chunk)


def roughness(windows, chunk=256):
    return _per_chunk(windows, _roughness_z, chunk)


def seam8(windows, chunk=256):
    return _per_chunk(windows, _seam8_z, chunk)


def seam32(windows, chunk=256):
    return _per_chunk(windows, _seam32_z, chunk)


def grid(windows, chunk=256):
    """The seam32 construction on the 6.4 px grid of the organizers' prediction tiles (columns
    and rows round(6.4 k) - 1), both axes summed."""
    return _per_chunk(windows, _grid_z, chunk)


grid_step = grid                        # its name in the development checks


def _hand_parts(windows, chunk=256):
    """The seven single numbers, the orientation histogram and the quantiles, normalizing once."""
    windows = np.asarray(windows)
    parts = {k: [] for k in SINGLE + ("orient", "quant")}
    for s in _chunks(len(windows), chunk):
        z = normalise(windows[s]).astype(np.float64)
        parts["lines"].append(_lines_z(z))
        parts["roughness"].append(_roughness_z(z))
        parts["seam8"].append(_seam8_z(z))
        parts["seam32"].append(_seam32_z(z))
        parts["grid"].append(_grid_z(z))
        parts["orient"].append(_orient_z(z))
        parts["quant"].append(np.quantile(z.reshape(len(z), -1), QUANTILES, axis=1).T)
    out = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in parts.items()}
    if not len(windows):
        out["orient"], out["quant"] = np.zeros((0, N_ORI)), np.zeros((0, len(QUANTILES)))
    out["density"] = density(windows)
    out["skew"] = skew(windows)
    return out


def _hand_matrix(parts):
    return np.column_stack([parts[k] for k in SINGLE] + [parts["orient"], parts["quant"]])


def hand_features(windows, chunk=256):
    """(N, 21) features in the order of HAND_NAMES."""
    return _hand_matrix(_hand_parts(windows, chunk))


# ------------------------------------------------------------------ spectrum
_SPEC = {}


def _spectrum_bins(H, W):
    """Fixed bin layout for H x W windows: (frequency indices in a band, averaging matrix, kept
    bin numbers ri * N_ANG + ai). Computed once per shape."""
    if (H, W) not in _SPEC:
        fy = (np.fft.fftfreq(H) * H)[:, None] + np.zeros((1, W))     # whole numbers
        fx = (np.fft.fftfreq(W) * W)[None, :] + np.zeros((H, 1))
        r = np.sqrt(fy * fy + fx * fx)
        ri = np.digitize(r, R_EDGES) - 1                               # r < 1 (DC) gives -1
        ang = np.mod(np.arctan2(fy, fx), np.pi)
        # the small offset puts frequencies on a bin edge (45 and 135 degrees) in the upper bin
        ai = np.floor(ang * (N_ANG / np.pi) + 1e-9).astype(np.int64) % N_ANG
        full = np.where((ri >= 0) & (ri < N_RAD), ri * N_ANG + ai, -1).ravel()
        sel = np.nonzero(full >= 0)[0]
        cnt = np.bincount(full[sel], minlength=N_RAD * N_ANG)
        keep = np.nonzero(cnt > 0)[0]
        col = np.full(N_RAD * N_ANG, -1)
        col[keep] = np.arange(len(keep))
        A = np.zeros((len(sel), len(keep)))
        A[np.arange(len(sel)), col[full[sel]]] = 1.0 / cnt[full[sel]]
        _SPEC[(H, W)] = (sel, A, keep)
    return _SPEC[(H, W)]


def spectrum_bins(H=128, W=128):
    """Bin numbers ri * 8 + ai kept as features (84 of 96 for a 128 x 128 window)."""
    return _spectrum_bins(H, W)[2].copy()


def spectrum_features(windows, chunk=256):
    """(N, 84) for 128 x 128 windows: log(mean power + 1e-6) per nonempty radial and angular
    bin of the full 2D power spectrum of the normalized window minus its mean."""
    windows = np.asarray(windows)
    sel, A, keep = _spectrum_bins(*windows.shape[1:])
    out = []
    for s in _chunks(len(windows), chunk):
        z = normalise(windows[s]).astype(np.float64)
        z = z - z.mean(axis=(1, 2), keepdims=True)
        F = np.fft.fft2(z, axes=(1, 2)).reshape(len(z), -1)[:, sel]
        out.append(np.log((F.real ** 2 + F.imag ** 2) @ A + 1e-6))
    return np.concatenate(out) if out else np.zeros((0, len(keep)))


# ------------------------------------------------------------------ logistic regression
def fit_logistic(X, y, l2=1e-3, sample_weight=None, iters=100, tol=1e-8):
    """L2-regularized logistic regression on standardized features (weighted mean and standard
    deviation; a constant feature keeps sd 1 and gets coefficient 0), by damped Newton steps
    with a backtracking line search. Minimizes sum_i w_i logloss_i + l2 / 2 |beta|^2 with the
    weights summing to 1 and the intercept not penalized. Raises RuntimeError if the largest
    gradient component does not fall below tol within iters steps, or if a line search finds no
    decrease while it is above 1e-6. Returns {"mu", "sd", "w" (coefficients, intercept last),
    "l2", "iters"}."""
    X = np.asarray(X, np.float64)
    y = np.asarray(y, np.float64).ravel()
    n, d = X.shape
    if len(y) != n or n == 0:
        raise ValueError("X and y must be non-empty with one label per row")
    if sample_weight is None:
        sw = np.full(n, 1.0 / n)
    else:
        sw = np.asarray(sample_weight, np.float64).ravel()
        if len(sw) != n or (sw < 0).any() or not np.all(np.isfinite(sw)) or sw.sum() <= 0:
            raise ValueError("sample weights must be finite, non-negative and not all zero")
        sw = sw / sw.sum()
    mu = sw @ X
    sd = np.sqrt(sw @ (X - mu) ** 2)
    sd = np.where(sd > 1e-12 * (1 + np.abs(mu)), sd, 1.0)
    Z = np.hstack([(X - mu) / sd, np.ones((n, 1))])
    R = l2 * np.eye(d + 1)
    R[-1, -1] = 0.0

    def obj(b):
        u = Z @ b
        return float(sw @ (np.logaddexp(0, u) - y * u) + 0.5 * b @ R @ b)

    beta = np.zeros(d + 1)
    f = obj(beta)
    for it in range(iters + 1):
        p = 1 / (1 + np.exp(-np.clip(Z @ beta, -500, 500)))
        g = Z.T @ (sw * (p - y)) + R @ beta
        if np.abs(g).max() <= tol:
            break
        if it == iters:
            raise RuntimeError(f"fit_logistic did not converge in {iters} steps (gradient {np.abs(g).max():.3g})")
        Hm = (Z * (sw * p * (1 - p))[:, None]).T @ Z + R + 1e-12 * np.eye(d + 1)
        step = np.linalg.solve(Hm, g)
        lam = 1.0
        while lam >= 1e-10:
            new = beta - lam * step
            f_new = obj(new)
            if f_new <= f - 1e-4 * lam * float(g @ step):
                break
            lam /= 2
        else:
            if np.abs(g).max() <= 1e-6:          # no decrease left at rounding level: converged
                break
            raise RuntimeError(f"fit_logistic: line search failed (gradient {np.abs(g).max():.3g})")
        beta, f = new, f_new
    return {"mu": mu, "sd": sd, "w": beta, "l2": float(l2), "iters": int(it)}


def logistic_score(model, X):
    """Logit of the fitted model for features X (float64)."""
    X = np.asarray(X, np.float64)
    w = np.asarray(model["w"], np.float64)
    return ((X - model["mu"]) / model["sd"]) @ w[:-1] + w[-1]


def _fit_features(Xp, Xn, kind, l2):
    X = np.concatenate([Xp, Xn])
    y = np.concatenate([np.ones(len(Xp)), np.zeros(len(Xn))])
    m = fit_logistic(X, y, l2=l2)
    m.update(kind=kind, n_pos=int(len(Xp)), n_neg=int(len(Xn)), n_features=int(X.shape[1]))
    return m


def fit_spectrum(pos, neg, l2=1e-3):
    """Spectrum baseline: positives against negatives of the StrokeNet training mixture."""
    return _fit_features(spectrum_features(pos), spectrum_features(neg), "spectrum", l2)


def fit_nullspec(text, copies, l2=1e-3):
    """Null-spectrum baseline: training text windows against their own IAAFT-20 copies."""
    return _fit_features(spectrum_features(text), spectrum_features(copies), "nullspec", l2)


def _texture_features(windows, parts=None, spec=None):
    parts = _hand_parts(windows) if parts is None else parts
    spec = spectrum_features(windows) if spec is None else spec
    return np.hstack([spec, _hand_matrix(parts)])


def fit_texture(pos, neg, l2=1e-3):
    """Texture baseline: spectrum_features + hand_features on the training mixture."""
    return _fit_features(_texture_features(pos), _texture_features(neg), "texture", l2)


# ------------------------------------------------------------------ random CNN
def _torch_modules():
    import torch
    import train as T
    return torch, T


def _cnn_features(net, windows, device, batch):
    """Global mean and max of net.features over each normalized window, float64 (N, 2 C)."""
    torch, T = _torch_modules()
    out = []
    with torch.no_grad():
        for s in _chunks(len(windows), batch):
            x = torch.from_numpy(np.asarray(windows[s], np.float32))[:, None].to(device)
            f = net.features(T.robust_norm_t(x))
            out.append(torch.cat([f.mean(dim=(2, 3)), f.amax(dim=(2, 3))], dim=1).double().cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, net.head.in_features))


def _randcnn_net(model, device="cpu"):
    """Rebuild the frozen random network of a randcnn model (eval mode)."""
    torch, T = _torch_modules()
    net = T.Net(int(model["width"]), int(model["depth"]))
    net.load_state_dict({k: torch.as_tensor(np.asarray(v)) for k, v in model["state"].items()})
    return net.to(device).eval()


def fit_randcnn(pos, neg, width, depth, seed=0, batch=256, device="cpu", l2=1e-3):
    """Random-CNN baseline: train.Net(width, depth) with the random weights of
    torch.manual_seed(seed) (drawn in a forked RNG, so the caller's RNG is untouched). Batch norm
    running statistics are reset and set by no-gradient forward passes in train mode (momentum
    None, so a cumulative average) over the training mixture in nearly equal, seeded random
    batches; then eval mode. Features: the global mean and max of the last feature map; an L2
    logistic head is fitted on them. The returned dict holds the network's state dict as numpy
    arrays ("state") next to the logistic model, so save_models can keep it in an npz.
    TF32 and other device settings are the caller's."""
    torch, T = _torch_modules()
    x_all = np.concatenate([np.asarray(pos), np.asarray(neg)])
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        net = T.Net(width, depth)
    for m in net.modules():
        if isinstance(m, torch.nn.modules.batchnorm._BatchNorm):
            m.momentum = None
            m.reset_running_stats()
    net.to(device).train()
    order = np.random.default_rng(seed).permutation(len(x_all))
    with torch.no_grad():
        for idx in np.array_split(order, max(1, math.ceil(len(order) / batch))):
            x = torch.from_numpy(x_all[np.sort(idx)].astype(np.float32))[:, None].to(device)
            net.features(T.robust_norm_t(x))
    net.eval()
    Fp = _cnn_features(net, np.asarray(pos), device, batch)
    Fn = _cnn_features(net, np.asarray(neg), device, batch)
    m = _fit_features(Fp, Fn, "randcnn", l2)
    m.update(width=int(width), depth=int(depth), seed=int(seed),
             state={k: v.detach().cpu().numpy() for k, v in net.state_dict().items()})
    return m


# ------------------------------------------------------------------ scoring and storage
def score_all(windows, models=None, device="cpu"):
    """{name: float64 scores} for one array of windows: the seven single numbers always, and each
    fitted baseline (spectrum, nullspec, texture, randcnn) whose model is in models."""
    models = models or {}
    unknown = set(models) - set(FITTED)
    if unknown:
        raise ValueError(f"unknown baseline models: {sorted(unknown)}")
    windows = np.asarray(windows)
    parts = _hand_parts(windows)
    out = {k: np.asarray(parts[k], np.float64) for k in SINGLE}
    spec = None
    if any(k in models for k in ("spectrum", "nullspec", "texture")):
        spec = spectrum_features(windows)
    for k in ("spectrum", "nullspec"):
        if k in models:
            out[k] = logistic_score(models[k], spec)
    if "texture" in models:
        out["texture"] = logistic_score(models["texture"], _texture_features(windows, parts, spec))
    if "randcnn" in models:
        m = models["randcnn"]
        out["randcnn"] = logistic_score(m, _cnn_features(_randcnn_net(m, device), windows, device, 256))
    return out


def _flatten(d, prefix, out):
    for k, v in d.items():
        k = str(k)
        if "/" in k:
            raise ValueError(f"key {k!r} holds '/'")
        key = f"{prefix}/{k}" if prefix else k
        if isinstance(v, dict):
            _flatten(v, key, out)
        else:
            a = np.asarray(v)
            if a.dtype == object:
                raise TypeError(f"{key}: cannot store {type(v).__name__} without pickle")
            out[key] = a


def save_models(path, models):
    """Save {name: model dict} in one npz, nested keys joined by '/' (for example 'texture/w',
    'randcnn/state/features.0.weight'). Values must be numbers, strings or numpy arrays."""
    flat = {}
    _flatten(models, "", flat)
    with open(path, "wb") as f:
        np.savez(f, **flat)


def load_models(path):
    """Inverse of save_models: nested dicts, 0-d arrays turned back into Python numbers or strings."""
    out = {}
    with np.load(path, allow_pickle=False) as z:
        for key in z.files:
            parts = key.split("/")
            d = out
            for p in parts[:-1]:
                d = d.setdefault(p, {})
            a = z[key]
            d[parts[-1]] = a.item() if a.ndim == 0 else a
    return out
