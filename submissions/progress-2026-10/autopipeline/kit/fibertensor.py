"""Fiber-orientation-aware ink features and a tiny learned reader (lane D, 2026-10-07).

Untested idea, made testable: papyrus fibres run in two near-perpendicular directions, and a
pen stroke laid over them crosses fibres at other angles and fills the gaps between them. So
the in-plane texture of inked papyrus should be less coherent, and oriented more often off
the two fibre axes, than bare papyrus. Raw brightness at any one depth separates ink from
background at most 0.58 AUC on PHerc0841 (docs/logs/2026-10-07-overlap-and-baseline.md);
this module asks how much a 2D structure tensor, read per depth band and referred to the
segment's own dominant fibre axis, adds on top of brightness, with a model small enough to
train on a CPU in seconds.

Features per pixel (all from the surface volume alone, no labels):

* brightness: z-scored mean of each depth band, smoothed at 1 and 4 px;
* structure tensor of each band at integration scales `RHO` (px): log energy, coherence
  (l1 - l2) / (l1 + l2), and the "off-fibre" angle, the distance of the local orientation
  to the nearer of the two fibre axes (0 on a fibre, 1 at 45 degrees). The fibre axis is
  the energy-weighted mean of the doubled orientation angle over the whole input, found
  once per segment, so the feature is rotation-invariant across segments;
* depth contrast: band to band differences of the means (ink sits at one depth).

`raw` features (brightness only) are the ablation the method must beat.

Model: logistic regression or a 1 hidden-layer MLP in numpy, trained on a balanced pixel
sample with standardised features. The map is the predicted probability, shifted into
(0.001, 1] so `kit auc` never drops a pixel as "no prediction".

    python -m kit fibertensor train  VOLUME.zarr LABEL_DIR --crop Y0 Y1 X0 X1 --surface-shape H W -o model.npz
    python -m kit fibertensor predict model.npz VOLUME.zarr --crop Y0 Y1 X0 X1 -o map.tif [--reverse]

An ink map is model output, not a reading.
"""

import json

from .verify import VerifyError, _numpy

BANDS = 5
RHO = (2.0, 4.0, 8.0)
GRAD_SIGMA = 1.0
EPS = 1e-6


def _scipy_ndimage():
    try:
        from scipy import ndimage
    except ImportError as exc:  # pragma: no cover
        raise VerifyError("kit fibertensor needs scipy") from exc
    return ndimage


def load_volume(path, crop=None, reverse=False, margin=0):
    """(layers, H, W) float32 window of a surface volume zarr (group with level "0", or array)."""
    np = _numpy()
    from .layers import _zarr
    node = _zarr().open(str(path), mode="r")
    if not hasattr(node, "shape"):
        node = node["0"]
    if crop is None:
        a = np.asarray(node[:])
    else:
        y0, y1, x0, x1 = crop
        a = np.asarray(node[:, max(0, y0 - margin):y1 + margin, max(0, x0 - margin):x1 + margin])
    a = a.astype(np.float32)
    return a[::-1].copy() if reverse else a


def fibre_axis(np, ndi, img):
    """Dominant in-plane orientation (radians) of a 2D image: energy-weighted doubled-angle mean."""
    gy = ndi.gaussian_filter(img, GRAD_SIGMA, order=(1, 0))
    gx = ndi.gaussian_filter(img, GRAD_SIGMA, order=(0, 1))
    jxx, jyy, jxy = (gx * gx).sum(), (gy * gy).sum(), (gx * gy).sum()
    return 0.5 * float(np.arctan2(2 * jxy, jxx - jyy))


def tensor_features(np, ndi, img, axis, rhos=RHO):
    """Per-pixel log energy, coherence and off-fibre angle at each integration scale."""
    gy = ndi.gaussian_filter(img, GRAD_SIGMA, order=(1, 0))
    gx = ndi.gaussian_filter(img, GRAD_SIGMA, order=(0, 1))
    out = []
    for rho in rhos:
        jxx = ndi.gaussian_filter(gx * gx, rho)
        jyy = ndi.gaussian_filter(gy * gy, rho)
        jxy = ndi.gaussian_filter(gx * gy, rho)
        tr = jxx + jyy
        d = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2)
        coh = d / (tr + EPS)
        theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy) - axis
        # two fibre axes 90 degrees apart: distance to the nearer one, scaled to 0..1
        off = np.abs(np.sin(2 * theta))
        out += [np.log(tr + EPS), coh, off]
    return out


def features(volume, kind="fibre", bands=BANDS, axis=None):
    """Feature stack (F, H, W) and the fibre axes used (one per band).

    kind "raw": band brightness only (the baseline); "fibre": brightness, structure tensor
    and depth contrast. Pass `axis` (from training) to reuse fixed axes; by default each
    segment's own axes are measured, which needs no labels."""
    np = _numpy()
    ndi = _scipy_ndimage()
    if volume.ndim != 3 or volume.shape[0] < bands:
        raise VerifyError(f"need a (layers, H, W) volume with at least {bands} layers, got {volume.shape}")
    edges = np.linspace(0, volume.shape[0], bands + 1).round().astype(int)
    means = []
    for b in range(bands):
        m = volume[edges[b]:edges[b + 1]].mean(0)
        sd = float(m.std()) or 1.0
        means.append((m - float(m.mean())) / sd)
    feats = []
    for m in means:
        feats += [ndi.gaussian_filter(m, 1.0), ndi.gaussian_filter(m, 4.0)]
    axes = []
    if kind == "fibre":
        for b, m in enumerate(means):
            ax = fibre_axis(np, ndi, m) if axis is None else float(axis[b])
            axes.append(ax)
            feats += tensor_features(np, ndi, m, ax)
        for b in range(bands - 1):
            feats.append(ndi.gaussian_filter(means[b + 1] - means[b], 2.0))
    elif kind != "raw":
        raise VerifyError(f"unknown feature kind {kind!r}")
    return np.stack(feats).astype(np.float32), axes


def _sample(np, ink, sup, n, rng):
    pos = np.flatnonzero((ink & sup).ravel())
    neg = np.flatnonzero((~ink & sup).ravel())
    if len(pos) == 0 or len(neg) == 0:
        raise VerifyError("training labels hold only one class inside the mask")
    k = min(n // 2, len(pos), len(neg))
    return np.concatenate([rng.choice(pos, k, replace=False), rng.choice(neg, k, replace=False)]), k


def fit(feats, ink, sup, model="mlp", hidden=16, samples=60000, epochs=200, lr=0.01, l2=1e-4, seed=0):
    """Train on a balanced sample of supervised pixels. Returns a dict of numpy arrays."""
    np = _numpy()
    rng = np.random.default_rng(seed)
    F = feats.shape[0]
    X = feats.reshape(F, -1).T
    idx, k = _sample(np, ink, sup, samples, rng)
    x = X[idx].astype(np.float64)
    y = np.concatenate([np.ones(k), np.zeros(k)])
    mu, sd = x.mean(0), x.std(0) + EPS
    x = (x - mu) / sd
    if model == "logreg":
        params = {"W1": np.zeros((F, 1)), "b1": np.zeros(1)}
    elif model == "mlp":
        params = {"W1": rng.normal(0, 1 / np.sqrt(F), (F, hidden)), "b1": np.zeros(hidden),
                  "W2": rng.normal(0, 1 / np.sqrt(hidden), (hidden, 1)), "b2": np.zeros(1)}
    else:
        raise VerifyError(f"unknown model {model!r}")
    m = {k_: np.zeros_like(v) for k_, v in params.items()}
    v2 = {k_: np.zeros_like(v) for k_, v in params.items()}
    for t in range(1, epochs + 1):       # full-batch Adam
        p, cache = _forward(np, params, x)
        g = (p - y)[:, None] / len(y)
        grads = _backward(np, params, cache, x, g)
        for k_ in params:
            grads[k_] = grads[k_] + l2 * params[k_]
            m[k_] = 0.9 * m[k_] + 0.1 * grads[k_]
            v2[k_] = 0.999 * v2[k_] + 0.001 * grads[k_] ** 2
            params[k_] -= lr * (m[k_] / (1 - 0.9 ** t)) / (np.sqrt(v2[k_] / (1 - 0.999 ** t)) + 1e-8)
    p, _ = _forward(np, params, x)
    loss = float(-(y * np.log(p + EPS) + (1 - y) * np.log(1 - p + EPS)).mean())
    out = dict(params)
    out.update({"mu": mu, "sd": sd, "train_loss": np.array(loss), "train_pixels": np.array(2 * k)})
    return out


def _forward(np, params, x):
    if "W2" in params:
        h = np.maximum(0, x @ params["W1"] + params["b1"])
        z = (h @ params["W2"] + params["b2"])[:, 0]
        return 1 / (1 + np.exp(-z)), h
    z = (x @ params["W1"] + params["b1"])[:, 0]
    return 1 / (1 + np.exp(-z)), None


def _backward(np, params, h, x, g):
    if "W2" in params:
        gW2 = h.T @ g
        gh = (g @ params["W2"].T) * (h > 0)
        return {"W1": x.T @ gh, "b1": gh.sum(0), "W2": gW2, "b2": g.sum(0)}
    return {"W1": x.T @ g, "b1": g.sum(0)}


def predict(params, feats, chunk=1 << 18):
    """Probability map (H, W) in (0.001, 1]."""
    np = _numpy()
    F, H, W = feats.shape
    X = feats.reshape(F, -1).T
    out = np.empty(X.shape[0], np.float32)
    p = {k: params[k] for k in ("W1", "b1", "W2", "b2") if k in params}
    for s in range(0, X.shape[0], chunk):
        x = (X[s:s + chunk].astype(np.float64) - params["mu"]) / params["sd"]
        out[s:s + chunk] = _forward(np, p, x)[0]
    return (out.reshape(H, W) * 0.999 + 0.001).astype(np.float32)


def save_model(path, params, meta):
    np = _numpy()
    np.savez(path, meta=np.array(json.dumps(meta)), **params)


def load_model(path):
    np = _numpy()
    z = np.load(path, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    return {k: z[k] for k in z.files if k != "meta"}, meta


def _crop_inner(np, arr, crop, margin, full_shape):
    """Cut the margin back off a window read with `margin` extra pixels."""
    if crop is None or margin == 0:
        return arr
    y0, y1, x0, x1 = crop
    oy, ox = y0 - max(0, y0 - margin), x0 - max(0, x0 - margin)
    return arr[..., oy:oy + (y1 - y0), ox:ox + (x1 - x0)]


MARGIN = 32   # extra context read around a crop so filters see no artificial edge


def train_files(volume, label_dir, crop, surface_shape, out, kind="fibre", model="mlp", seed=0,
                samples=60000, epochs=200, reverse=False):
    from . import auc
    np = _numpy()
    vol = load_volume(volume, crop, reverse, MARGIN)
    feats, axes = features(vol, kind)
    feats = _crop_inner(np, feats, crop, MARGIN, surface_shape)
    ink, sup = auc.labels_on_map(f"{label_dir}/inklabels.zarr", f"{label_dir}/supervision.zarr", "2",
                                 tuple(surface_shape), crop, feats.shape[1:])
    params = fit(feats, ink, sup, model=model, seed=seed, samples=samples, epochs=epochs)
    meta = {"kind": kind, "model": model, "seed": seed, "train_volume": str(volume), "crop": crop,
            "train_axes": axes, "bands": BANDS, "rho": list(RHO), "features": int(feats.shape[0]),
            "train_loss": float(params["train_loss"]), "train_pixels": int(params["train_pixels"])}
    save_model(out, params, meta)
    return meta


def predict_files(model_path, volume, crop, out, reverse=False):
    import tifffile
    np = _numpy()
    params, meta = load_model(model_path)
    vol = load_volume(volume, crop, reverse, MARGIN)
    feats, axes = features(vol, meta["kind"])
    feats = _crop_inner(np, feats, crop, MARGIN, None)
    if feats.shape[0] != meta["features"]:
        raise VerifyError(f"model expects {meta['features']} features, got {feats.shape[0]}")
    m = predict(params, feats)
    tifffile.imwrite(out, m)
    return {"map": str(out), "shape": list(m.shape), "axes": axes, "kind": meta["kind"], "reverse": reverse}
