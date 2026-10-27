"""Compare ink models side by side on one region: the same pixels, the same labels, each model's own control.

The fair canvas. Every model of a comparison reads the same segment of the same scan, at its own scale, and every map
lands on one 9.6 um grid where the labels are scored:

  scan "2.4"     the segment's finer scan (about 2.4 um, 109 layers). 9 um models and Hecate 9.6 read it pooled 4x
                 (villa's own recipe for its 9 um training inputs, and ink-sdk's scale rule); Hecate 2.4 and canonical
                 2 um read it as it is, and their maps are mean-pooled 4x onto the 9.6 um grid. The labels' level 2
                 is that grid exactly. Scan-space 3D models (gambiarra, DINO-guided) read the scan around the mesh as a
                 Hugging Face Job and land on the same grid through project3d.py (tools/gallery_job.py).
  scan "native"  the segment's 9.4 um scan (28 layers), as Ink Lens reads it: 9 um models only.

Each model runs on depth windows (runners.window: its own depth, centered `center` layers from the middle in 9.6 um
layers, `step` layers apart), in both depth orders where it reads depth order. Nothing picks a best cell: the
headline row of a model is its center window (c+0, step 1) as stored, against its own control, the same window
reversed. A model that reads only forward (canonical 2 um) gets its control from Ink Lens reversing the input
layers. Every map passes ink-sdk's liveness gate before it is scored; a DEGENERATE map is shown, flagged, and never
ranked.

Scores (kit/auc.py): pixel AUC inside the supervision mask with a 64 px edge left out, the control's AUC, their gap,
and a 95 % block-bootstrap interval (1 mm blocks). Each row carries the model's training exposure on the shown scroll
(zoo.exposure): a score on a scroll a model trained on is a pipeline check, not a test.

Also: the z-score ensemble of the chosen models (ink-sdk's recipe after Erwin Nieuwlaar's, reading side as stored),
scored like a model with the ensemble of the controls as its control; a stability map (the share of all cells above
a threshold); mosaics (rows = models, columns = depth windows); depth profiles from Hecate's 3D volume; and a JSON run
record of everything (pins, windows, timings, liveness, scores, exposure).

Model output, not a reading.
"""

from __future__ import annotations

import json
import math
import platform
import time
from pathlib import Path

import runners
import zoo

GRID_UM = 9.6
INNER = 64
BOOT_DRAWS = 200
CENTERS = (0,)
STEPS = (1,)
THRESHOLDS = (0.5, 0.7)
BLOCK_PX = 104          # 1 mm on the 9.6 um grid
MIN_BLOCKS = 9          # fewer 1 mm blocks than this give no interval (a 640 px crop has about 36)
VERSION = "0.2.0"
SCANS = {"2.4": 2.403, "native": 9.366}


class CompareError(ValueError):
    """A comparison Ink Lens refuses; the message says why."""


# ---------------------------------------------------------------- inputs

def plan(name, scan):
    """How a model reads a scan: {"pool": k, "map_pool": m, "depth_factor": f, "source_um": u} or a CompareError.
    k pools the volume before the model (zoo.scale_plan, ink-sdk's rule), m pools its map onto the 9.6 um grid, f
    converts 9.6 um layers of a window center into the model's own layers."""
    spec = zoo.get(name)
    if spec["family"] == "ct3d":
        raise CompareError(f"{name} reads the scan itself; its maps come from the precomputed gallery")
    source = SCANS.get(scan)
    if source is None:
        raise CompareError(f"scan {scan!r}: use 2.4 or native")
    try:
        how, k = zoo.scale_plan(source, name)
    except zoo.ZooError as exc:
        raise CompareError(str(exc)) from None
    out_um = source * k
    m = int(round(GRID_UM / out_um)) if scan == "2.4" else 1
    return {"pool": k, "map_pool": max(1, m), "depth_factor": max(1, m), "source_um": source}


def control_note(name):
    c = zoo.control_of(name)
    if c == "none":
        return "reverse-depth (the input layers reversed by Ink Lens; the model's profile runs forward only)"
    return {"reverse-depth": "reverse-depth (the same layers, reversed)",
            "moved-sheet": "moved sheet (the surface moved two sheet pitches out and in, the larger of the two)"}[c]


def sample_inputs(s, scan="2.4", box=None, size=None, with_labels=True):
    """The volume and labels of a sample region. box: (y0, y1, x0, x1) on the 9.6 um grid ("2.4") or on the native
    9.4 um grid ("native"); default: the sample's 640 px crop, or `size` px around its center. Returns
    (volume uint8, (ink, supervision) or None, info)."""
    import inklens
    import volio
    if scan == "native":
        b = inklens.sample_box(s, size=size) if box is None else tuple(int(v) for v in box)
        vol, info = inklens.read_sample(s, b)
        lab = inklens.labels_for(s, b, (b[1] - b[0], b[3] - b[2])) if with_labels else None
        return vol, lab, dict(info, box=list(b), grid="native", um_per_px=s["um_per_px"])
    sc = s.get("scan24")
    if not sc:
        raise CompareError(f"sample {s['id']} has no 2.4 um scan")
    if box is None:
        y0, y1, x0, x1 = sc["crop"]
        if size:
            cy, cx, h = (y0 + y1) // 2, (x0 + x1) // 2, int(size) // 2
            y0, y1, x0, x1 = cy - h, cy - h + int(size), cx - h, cx - h + int(size)
        box = (y0, y1, x0, x1)
    y0, y1, x0, x1 = (int(v) for v in box)
    gy, gx = sc["grid_shape"]
    if not (0 <= y0 < y1 <= gy and 0 <= x0 < x1 <= gx):
        raise CompareError(f"box {[y0, y1, x0, x1]} is outside the {gy} x {gx} grid")
    url = f"{volio.BUCKET}/{s['scroll']}/segments/{s['segment']}/{sc['surface_volume']}"
    data, info = volio.read_region(url, (4 * y0, 4 * x0, 4 * (y1 - y0), 4 * (x1 - x0)))
    vol = volio.to_uint8(data)
    lab = None
    if with_labels:
        kit = inklens.find_kit()
        if kit is None:
            raise CompareError("label scoring needs this repository's kit/ (and zarr)")
        import tempfile
        from kit import auc, fetch
        with tempfile.TemporaryDirectory(prefix="inklens-labels-") as tmp:
            fetch.fetch_prefix(f"{s['scroll']}/segments/{s['segment']}/{s['labels']}", tmp)
            lab = auc.labels_on_map(Path(tmp) / "inklabels.zarr", Path(tmp) / "supervision.zarr", "2",
                                    (gy, gx), (y0, y1, x0, x1), (y1 - y0, x1 - x0))
    return vol, lab, dict(info, box=[y0, y1, x0, x1], grid="9.6 um", um_per_px=sc["um_per_px"])


# ---------------------------------------------------------------- liveness (ink-sdk's gate)

# ink-sdk's thresholds (ink_sdk/liveness.py), used as they are when ink-sdk is not installed
MIN_SPREAD, MIN_STD, MAX_NEAR_HALF, NEAR_HALF = 0.05, 0.02, 0.90, 0.05


def _assess_local(m, valid):
    import numpy as np
    v = np.asarray(m, np.float64)[valid].ravel()
    if v.size == 0:
        return {"verdict": "EMPTY", "reason": "no valid pixels", "metrics": {}}
    p50, p99 = (float(x) for x in np.percentile(v, [50, 99]))
    std, near = float(v.std()), float((np.abs(v - 0.5) <= NEAR_HALF).mean())
    fail = [t for t, bad in ((f"p99-p50 {p99 - p50:.4f} < {MIN_SPREAD}", p99 - p50 < MIN_SPREAD),
                             (f"std {std:.4f} < {MIN_STD}", std < MIN_STD),
                             (f"{near:.1%} of pixels within {NEAR_HALF} of 0.5", near > MAX_NEAR_HALF)) if bad]
    return {"verdict": "DEGENERATE" if fail else "ALIVE", "reason": "; ".join(fail),
            "metrics": {"p50": p50, "p99": p99, "spread_p99_p50": p99 - p50, "std": std, "fraction_near_half": near,
                        "valid_pixels": int(v.size)}}


def liveness(m, valid=None):
    """ink-sdk's liveness gate: EMPTY, DEGENERATE (no decision in the map) or ALIVE."""
    import numpy as np
    m = np.asarray(m, np.float32)
    ok = np.isfinite(m) if valid is None else (np.asarray(valid, bool) & np.isfinite(m))
    try:
        from ink_sdk.liveness import assess_liveness
        rep = assess_liveness(np.nan_to_num(m), valid=ok)
    except ImportError:
        rep = _assess_local(m, ok)
    return {"verdict": rep["verdict"], "reason": rep.get("reason", ""),
            "metrics": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rep.get("metrics", {}).items()}}


def asymmetry(f, r):
    """ink-sdk's forward/reverse asymmetry (pixels over thresholds in each order), or None without ink-sdk."""
    import numpy as np
    try:
        from ink_sdk.liveness import forward_reverse_asymmetry
    except ImportError:
        return None
    return forward_reverse_asymmetry(np.nan_to_num(f), np.nan_to_num(r))


def map_values(p, family):
    """ink-sdk's ensemble input: a 9 um model's map as clip((255 p - 64) / 128, 0, 1), others as they are."""
    import numpy as np
    p = np.asarray(p, np.float32)
    return np.clip((p * 255.0 - 64.0) / 128.0, 0.0, 1.0) if family == "villa9" else p


# ---------------------------------------------------------------- scoring

def score(m, ink, sup, control=None, inner=INNER, draws=BOOT_DRAWS, block_px=BLOCK_PX, valid=None):
    """AUC, control AUC, gap and a block-bootstrap interval of the AUC and of the gap (same draws). Pixels count when
    supervised and valid (scan data under them, and a finite value in the map and its control); a map's exact zeros
    count like any other value, since some models (Hecate) put exact zeros on clear background."""
    import numpy as np
    from kit import auc
    m = np.asarray(m, np.float32)
    use = np.asarray(sup, bool) & np.isfinite(m)
    if valid is not None:
        use &= np.asarray(valid, bool)
    c = None
    if control is not None:
        c = np.asarray(control, np.float32)
        use &= np.isfinite(c)
        c = np.nan_to_num(c)
    m = np.nan_to_num(m)
    if min(m.shape) < 4 * inner:          # a small live region keeps an edge in proportion, not 64 px
        inner = min(m.shape) // 8
    out = {"auc": auc.score_array(m, ink, use, keep_zero=True, inner=inner)}
    if c is not None:
        out["control"] = auc.score_array(c, ink, use, keep_zero=True, inner=inner)
        a, b = out["auc"]["auc"], out["control"]["auc"]
        out["gap"] = None if a is None or b is None else round(a - b, 4)
    if draws:
        try:
            out["bootstrap"] = auc.block_bootstrap(m, ink, use, draws=draws, inner=inner, block_px=block_px,
                                                   other=c, keep_zero=True)
        except Exception as exc:  # noqa: BLE001  (an interval is a bonus)
            out["bootstrap"] = {"error": str(exc)[:200]}
        else:
            ci = out["bootstrap"].get("ci95") or []
            if out["bootstrap"].get("blocks", 0) < MIN_BLOCKS or any(not math.isfinite(v) for v in ci):
                # too few 1 mm blocks to resample: no honest interval
                out["bootstrap"] = {"error": f"too few 1 mm blocks for an interval ({out['bootstrap'].get('blocks')})"}
    return out


# ---------------------------------------------------------------- ensemble (ink-sdk's recipe)

def ensemble(maps, valid, side_maps=None, families=None):
    """Mean of per-model z-scores. maps: {model: reading-side map}; side_maps: {model: blind-side map} scored with
    the reading side's statistics, never its own. villa9 maps are first mapped to clip((255 p - 64) / 128, 0, 1)
    (ink_sdk.ensemble.map_values). Returns (ensemble, blind ensemble or None, stats)."""
    import numpy as np
    stats, acc, accb = {}, None, None
    for name, m in maps.items():
        adapter = (families or {}).get(name)
        v = map_values(np.nan_to_num(m), adapter)
        pix = v[valid].astype(np.float64)
        mu, sd = float(pix.mean()), float(pix.std()) + 1e-6
        stats[name] = {"mean": round(mu, 6), "sd": round(sd, 6)}
        z = (v - mu) / sd
        acc = z if acc is None else acc + z
        if side_maps is not None:
            zb = (map_values(np.nan_to_num(side_maps[name]), adapter) - mu) / sd
            accb = zb if accb is None else accb + zb
    n = len(maps)
    return acc / n, (None if accb is None else accb / n), stats


def stability(cells, valid, threshold):
    """Share of cells where the map is at least `threshold` (what survives the choice of settings)."""
    import numpy as np
    if not cells:
        return None
    acc = np.zeros(valid.shape, np.float32)
    for m in cells:
        acc += (np.nan_to_num(m) >= threshold)
    out = acc / len(cells)
    out[~valid] = 0
    return out


# ---------------------------------------------------------------- the run

def _ct_valid(volume, pool_k):
    """Valid 9.6 um pixels: CT > 0 in every layer of the region (ink-sdk's ensemble rule), pooled to the grid."""
    import numpy as np
    v = (np.asarray(volume) > 0).all(axis=0)
    if pool_k > 1:
        H, W = v.shape[0] // pool_k * pool_k, v.shape[1] // pool_k * pool_k
        v = v[:H, :W].reshape(H // pool_k, pool_k, W // pool_k, pool_k).all(axis=(1, 3))
    return v


def run(volume, scan, models, labels=None, centers=CENTERS, steps=STEPS, loaded=None, device=None,
        ensemble_models=None, output_3d=False, draws=BOOT_DRAWS, say=print, sample=None, **renamed):
    """Compare `models` on one region. volume: uint8 (layers, rows, columns) of `scan` ("2.4": the finer scan at
    level 0; "native": the 9.4 um scan); labels: (ink, supervision) boolean arrays on the 9.6 um grid of the region,
    or None. loaded: {name: runner} already loaded (the Space keeps them); others are loaded here. centers was
    spelled the British way before 27 Oct 2026; scripts written then still pass it under that name (`renamed`).
    Returns (result dict, maps dict {(model, window, order): 9.6 um map}, volumes {(model, window): 3D})."""
    centers = renamed.pop("centres", centers)
    if renamed:
        raise TypeError(f"run() got unexpected keyword arguments {sorted(renamed)}")
    import numpy as np
    t0 = time.perf_counter()
    vol = np.asarray(volume)
    if vol.dtype != np.uint8 or vol.ndim != 3:
        raise CompareError("a surface volume is uint8 (layers, rows, columns)")
    if not models:
        raise CompareError("choose at least one model")
    grid_pool = 4 if scan == "2.4" else 1
    block_px = BLOCK_PX if scan == "2.4" else 107     # 1 mm on the grid
    grid_shape = (vol.shape[1] // grid_pool, vol.shape[2] // grid_pool)
    valid = _ct_valid(vol, grid_pool)
    loaded = {} if loaded is None else loaded
    pooled = {}
    maps, vols, rows = {}, {}, {}
    for name in models:
        spec = zoo.get(name)
        row = {"model": name, "title": spec["title"], "by": spec["by"], "family": spec["family"],
               "license": spec["license"], "control": control_note(name)}
        rows[name] = row
        try:
            p = plan(name, scan)
        except CompareError as exc:
            row["skipped"] = str(exc)
            continue
        row["scale"] = {"source_um": p["source_um"], "model_um": spec["scale_um"], "pool": p["pool"],
                        "map_pool": p["map_pool"]}
        v = pooled.get(p["pool"])
        if v is None:
            v = pooled[p["pool"]] = runners.pool(vol, p["pool"])
        depth = spec["depth"]
        wins = runners.windows_for(v.shape[0], depth, [int(c) * p["depth_factor"] for c in centers],
                                   [int(s) for s in steps])
        # keys in 9.6 um layer units, whatever the model's own layers
        wins = {f"c{int(round(int(k.split('_')[0][1:]) / p['depth_factor'])):+d}_{k.split('_')[1]}": idx
                for k, idx in wins.items()}
        if not wins:
            row["skipped"] = (f"{depth} layers centered at {list(centers)} do not fit the region's {v.shape[0]} "
                              "layers at this scale")
            continue
        row["windows"] = {k: [int(i) for i in idx] for k, idx in wins.items()}
        try:
            r = loaded.get(name)
            if r is None:
                say(f"loading {name}")
                r = loaded[name] = runners.load(name, device=device)
            t1 = time.perf_counter()
            orders = tuple(spec["orders"])
            if spec["family"] == "villa9":
                got = r.run(v, wins, orders=orders, device=device)
                row["patches"] = getattr(r, "last_patches", None)
            elif spec["family"] == "hecate":
                got = r.run(v, wins, orders=orders, pixel_um=p["source_um"] * p["pool"], output_3d=output_3d,
                            device=device)
                if output_3d:
                    got, v3 = got
                    for (k, _), arr in v3.items():
                        if k == "c+0_s1":       # the center window's volume only (a 2.4 um one is 420 MB)
                            vols[(name, k)] = arr
            else:     # canonical: forward only; the control is the same layers reversed by Ink Lens
                got = r.run(v, wins, orders=("forward",), pixel_um=p["source_um"] * p["pool"], device=device)
                rev = r.run(v, {k: idx[::-1] for k, idx in wins.items()}, orders=("forward",),
                            pixel_um=p["source_um"] * p["pool"], device=device)
                got.update({(k, "reverse"): m for (k, _), m in rev.items()})
            row["seconds"] = round(time.perf_counter() - t1, 3)
            row["runner"] = getattr(r, "info", {})
        except Exception as exc:  # noqa: BLE001  (one model failing never hides the others)
            row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            continue
        for (k, order), m in got.items():
            g = runners.pool_map(m, p["map_pool"])[:grid_shape[0], :grid_shape[1]]
            maps[(name, k, order)] = g
        row["cells"] = {}
        for k in wins:
            f, rv = maps.get((name, k, "forward")), maps.get((name, k, "reverse"))
            cell = {"liveness": {o: liveness(m, valid) for o, m in (("forward", f), ("reverse", rv)) if m is not None}}
            if f is not None and rv is not None:
                cell["asymmetry"] = asymmetry(f, rv)
            if labels is not None and f is not None:
                cell["score"] = score(f, labels[0], labels[1], control=rv, draws=draws if k == "c+0_s1" else 0,
                                      block_px=block_px, valid=valid)
            row["cells"][k] = cell
        head = row["cells"].get("c+0_s1") or next(iter(row["cells"].values()))
        row["alive"] = head["liveness"].get("forward", {}).get("verdict") == "ALIVE"
    result = {"tool": f"Ink Lens compare {VERSION}", "scan": scan, "grid_um": GRID_UM, "grid_shape": list(grid_shape),
              "centers": [int(c) for c in centers], "steps": [int(s) for s in steps], "models": rows,
              "valid_px": int(valid.sum()), "inner": INNER, "bootstrap_draws": draws, "block_px": block_px,
              "ink_sdk": f"{zoo.INK_SDK_REPO} @ {zoo.INK_SDK_COMMIT}", "note": NOTE}
    if sample is not None:
        result["sample"] = sample
        scroll = sample.get("scroll")
        for name, row in rows.items():
            st, why, src = zoo.exposure(name, scroll)
            row["exposure"] = {"scroll": scroll, "status": st, "why": why, "source": src}
    # ensemble of the alive models' center windows, as stored; its control is the ensemble of their controls
    members = [n for n in (ensemble_models or [n for n in models if rows[n].get("alive")])
               if (n, "c+0_s1", "forward") in maps and rows[n].get("alive")]
    if len(members) >= 2:
        fam = {n: zoo.get(n)["family"] for n in members}
        e, eb, st = ensemble({n: maps[(n, "c+0_s1", "forward")] for n in members}, valid,
                             {n: maps.get((n, "c+0_s1", "reverse"), maps[(n, "c+0_s1", "forward")]) for n in members},
                             fam)
        maps[("ensemble", "c+0_s1", "forward")] = e
        maps[("ensemble", "c+0_s1", "reverse")] = eb
        ens = {"members": members, "stats": st, "recipe": "ink-sdk ensemble (Erwin Nieuwlaar's PHerc0343 recipe): "
               "mean of per-model z-scores, reading side as stored, blind side with the reading side's statistics"}
        if labels is not None:
            ens["score"] = score(e, labels[0], labels[1], control=eb, draws=draws, block_px=block_px, valid=valid)
        result["ensemble"] = ens
    cells = [m for (n, k, o), m in maps.items() if o == "forward" and n != "ensemble" and rows.get(n, {}).get("alive")]
    result["stability"] = {f"{t:g}": None for t in THRESHOLDS}
    for t in THRESHOLDS:
        s = stability(cells, valid, t)
        if s is not None:
            maps[("stability", f"t{t:g}", "forward")] = s
            result["stability"][f"{t:g}"] = {"cells": len(cells), "mean_share": round(float(s[valid].mean()), 4)}
    for (name, k), arr in vols.items():
        prof = depth_profile(arr, labels, grid_pool if scan == "2.4" and zoo.get(name)["scale_um"] < 5 else 1)
        if prof:
            rows[name].setdefault("depth_profile", {})[k] = prof
    result["seconds"] = round(time.perf_counter() - t0, 3)
    result["environment"] = environment()
    return result, maps, vols


def depth_profile(vol3d, labels, pool_k):
    """Mean 3D ink probability per layer over labeled ink and labeled background pixels (where a 3D model puts
    ink in depth)."""
    import numpy as np
    if labels is None:
        return None
    ink, sup = labels
    v = np.asarray(vol3d, np.float32) / 255.0
    if pool_k > 1:
        L, H, W = v.shape[0], v.shape[1] // pool_k * pool_k, v.shape[2] // pool_k * pool_k
        v = v[:, :H, :W].reshape(L, H // pool_k, pool_k, W // pool_k, pool_k).mean(axis=(2, 4))
    h, w = min(v.shape[1], ink.shape[0]), min(v.shape[2], ink.shape[1])
    v, ink, sup = v[:, :h, :w], ink[:h, :w], sup[:h, :w]
    a, b = sup & ink, sup & ~ink
    if not a.any() or not b.any():
        return None
    return {"ink": [round(float(x), 4) for x in v[:, a].mean(axis=1)],
            "background": [round(float(x), 4) for x in v[:, b].mean(axis=1)]}


def environment():
    out = {"python": platform.python_version(), "machine": platform.machine()}
    try:
        import torch
        out["torch"] = torch.__version__
        out["cuda"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        out["torch"] = None
    try:
        import engine
        out["villa"] = engine.VILLA_COMMIT
    except ImportError:
        pass
    out["ink_sdk"] = zoo.INK_SDK_COMMIT
    return out


NOTE = ("Model output, not a reading. AUC is the chance a labeled ink pixel scores above a labeled background "
        "pixel inside the supervision mask; a score on a scroll the model trained on shows the pipeline runs, not "
        "that it generalizes.")


# ---------------------------------------------------------------- cost

# Rough GPU seconds per million 9.6 um grid pixels for one window in one depth order (an A100-class GPU; ZeroGPU's
# H200 slices are faster), and seconds to load a model once. Used only to ask ZeroGPU for a duration.
SECONDS_PER_MPX = {"villa9": 6.0, "hecate-9.6": 8.0, "hecate-2.4": 60.0, "canonical-2um": 45.0}
LOAD_S = 8.0


def estimate(models, height, width, n_windows=1):
    """GPU seconds one comparison asks for: models on a height x width region of the 9.6 um grid."""
    mpx = height * width / 1e6
    total = 0.0
    for name in models:
        spec = zoo.get(name)
        if spec["family"] == "ct3d":
            continue
        rate = SECONDS_PER_MPX.get(name, SECONDS_PER_MPX.get(spec["family"], 30.0))
        total += LOAD_S + rate * mpx * n_windows * 2
    return int(min(600, max(30, 1.5 * total + 10)))


# ---------------------------------------------------------------- pictures

def stretch(m, valid=None, lo_q=1.0, hi_q=99.5):
    import numpy as np
    m = np.nan_to_num(np.asarray(m, np.float32))
    pix = m[valid] if valid is not None and valid.any() else m.ravel()
    lo, hi = (float(x) for x in np.percentile(pix, [lo_q, hi_q])) if pix.size else (0.0, 1.0)
    return np.clip((m - lo) / max(hi - lo, 1e-9), 0, 1)


def to_rgb(m, mode="absolute", valid=None):
    """A map as an RGB uint8 image: absolute 0..1 probability, or stretched p1..p99.5 (ink-sdk's display)."""
    import numpy as np
    g = stretch(m, valid) if mode == "stretched" else np.clip(np.nan_to_num(np.asarray(m, np.float32)), 0, 1)
    g8 = (g * 255).astype(np.uint8)
    return np.repeat(g8[..., None], 3, axis=-1)


def label_outline(rgb, ink, sup, color=(255, 170, 40)):
    """Draw the labeled ink's outline (inside the supervision mask) on an image of the same grid."""
    import numpy as np
    a = np.asarray(ink, bool) & np.asarray(sup, bool)
    edge = a & ~(np.roll(a, 1, 0) & np.roll(a, -1, 0) & np.roll(a, 1, 1) & np.roll(a, -1, 1))
    out = rgb.copy()
    out[edge] = color
    return out


def mosaic(maps, rows, cols, mode="absolute", valid=None, labels=None, thumb=200, gap=4):
    """rows: [model], cols: [(window, order)]; an RGB grid with a dark gap, empty where a cell is missing."""
    import numpy as np
    tiles = []
    for r in rows:
        line = []
        for k, o in cols:
            m = maps.get((r, k, o))
            if m is None:
                line.append(None)
                continue
            img = to_rgb(m, "stretched" if r == "ensemble" else mode, valid)    # z-scores have no 0..1 scale
            if labels is not None:
                img = label_outline(img, *labels)
            line.append(_thumb(img, thumb))
        tiles.append(line)
    th = max((t.shape[0] for line in tiles for t in line if t is not None), default=thumb)
    tw = max((t.shape[1] for line in tiles for t in line if t is not None), default=thumb)
    H = len(rows) * th + (len(rows) + 1) * gap
    W = len(cols) * tw + (len(cols) + 1) * gap
    out = np.full((H, W, 3), 24, np.uint8)
    for i, line in enumerate(tiles):
        for j, t in enumerate(line):
            if t is None:
                continue
            y, x = gap + i * (th + gap), gap + j * (tw + gap)
            out[y:y + t.shape[0], x:x + t.shape[1]] = t
    return out


def _thumb(img, width):
    import numpy as np
    h = max(1, int(round(img.shape[0] * width / img.shape[1])))
    ys = (np.arange(h) * img.shape[0] / h).astype(int)
    xs = (np.arange(width) * img.shape[1] / width).astype(int)
    return img[np.ix_(ys, xs)]


def table(result):
    """Markdown rows: model, exposure, liveness, AUC [95 %], control, gap, seconds."""
    lines = ["| Model | Trained on this scroll? | Map | AUC (95 % interval) | Control | Gap | Seconds |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    marks = {"trained": "yes", "likely": "likely", "selected": "no (recipe chosen on it)", "held_out": "no",
             "unknown": "not stated"}
    for name, row in result["models"].items():
        exp = marks.get(row.get("exposure", {}).get("status"), "")
        if row.get("skipped") or row.get("error"):
            lines.append(f"| {row['title']} | {exp} | {'skipped' if row.get('skipped') else 'error'}: "
                         f"{(row.get('skipped') or row.get('error'))[:90]} | | | | |")
            continue
        head = row["cells"].get("c+0_s1") or next(iter(row["cells"].values()))
        live = head["liveness"].get("forward", {}).get("verdict", "")
        sc = head.get("score", {})
        a = (sc.get("auc") or {}).get("auc")
        ci = (sc.get("bootstrap") or {}).get("ci95")
        c = (sc.get("control") or {}).get("auc")
        g = sc.get("gap")
        auc_txt = ("no labeled ink here" if sc and a is None else "" if a is None
                   else f"{a:.3f}" + (f" ({ci[0]:.3f} to {ci[1]:.3f})" if ci else ""))
        lines.append(f"| {row['title']} | {exp} | {live} | {auc_txt} | {'' if c is None else f'{c:.3f}'} | "
                     f"{'' if g is None else f'{g:+.3f}'} | {row.get('seconds', '')} |")
    e = result.get("ensemble")
    if e and e.get("score"):
        sc = e["score"]
        a, c, g = sc["auc"]["auc"], (sc.get("control") or {}).get("auc"), sc.get("gap")
        ci = (sc.get("bootstrap") or {}).get("ci95")
        auc_txt = "no labeled ink here" if a is None else f"{a:.3f}" + (f" ({ci[0]:.3f} to {ci[1]:.3f})" if ci else "")
        lines.append(f"| Ensemble of {len(e['members'])} (z-score) | | | {auc_txt}"
                     f" | {'' if c is None else f'{c:.3f}'} | {'' if g is None else f'{g:+.3f}'} | |")
    return "\n".join(lines)


def record(result, path):
    """Write the JSON run record."""
    Path(path).write_text(json.dumps(result, indent=1, default=_jsonable))
    return path


def _jsonable(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    if isinstance(o, (set, tuple)):
        return list(o)
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return str(o)
