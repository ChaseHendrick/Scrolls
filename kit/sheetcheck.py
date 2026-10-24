"""Label-free self-check of an ink map: does its ink sit on the traced sheet, or does it smear across sheets, follow
the mask edge, or light up empty space?

An ink map is read from one traced sheet (a mesh). If the same model, read one sheet pitch away along the mesh
normals, gives nearly the same map, the map is not about this sheet: neighboring wraps carry different text, so
ink read on the sheet and ink read one sheet away should share little. The check needs no labels, so it can be run
on any scroll, before any test, by anyone with the map and the CT.

  maps    2D maps of one window read at several normal shifts k (in sheet pitches): --map 0=on.tif --map 1=out.tif
          --map -1=in.tif [--map 2=... --map -2=...]. Any model: a 3D model's prediction projected at each shift,
          or a 2.5D model run on surface volumes rendered at each shift. Optional --mask (valid pixels) and --ct
          (the CT on the traced sheet, same grid) add the mask-edge and empty-space checks.
  volume  a 3D prediction volume (zarr or a TIFF stack, z y x) and a tifxyz mesh: the map is projected here at
          each shift (trilinear, maximum over +-HALF voxels along the normal), then checked as `maps` does.
  demo    synthetic sheets with known ink: a sharp map passes, a map smeared across sheets, one with a shared
          artifact, one following the mask edge and one lit in empty space each fail. Shows the check can fail.
  summary several window results (--json output of maps or volume) into one verdict per model: at least 6
          windows, their mean r1 under the bar, and at most a fifth of them FAIL.

Per window, after subtracting a Gaussian blur of --sigma map pixels (slow shading that every sheet shares):
  r(k)    Pearson correlation of the map at shift k with the map at k = 0, on pixels valid in both. The larger of
          k = -1 and +1 must stay under --bar (0.5: the map one sheet away explains under a quarter of the variance
          of the map on the sheet), and so must the larger of k = -2 and +2 when given. Maps that stay alike at two
          pitches as at one are labeled "shared": shading, mesh or CT texture common to every sheet; maps that fall
          off with distance are labeled "smeared along the normal".
  edge    with --mask (or NaN in the maps): the share of the top 10 % of map pixels within --edge-px of an invalid
          pixel, over the share of all valid pixels there. At --enrich (3.0) or more, ink follows the mask edge.
  void    with --ct: the same enrichment for pixels darker than half the window's median CT value (empty space or
          a crack under the mesh). At --enrich or more, ink lights up where there is no papyrus.

A PASS is a necessary condition, not proof: a map can be sheet-specific and still carry no ink signal. It does not
replace a labeled score with its control (kit auc --control). Model output stays model output, never a reading.
Numpy and tifffile; zarr for zarr volumes.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

from .verify import VerifyError, _numpy, load_map

SIGMA = 32.0        # map pixels: the high-pass that removes shading shared by every sheet
BAR = 0.5           # largest correlation allowed between the map on the sheet and one or two pitches away
SHARED = 0.8        # r(2) at least this share of r(1): the likeness does not fall with distance
TOP = 0.10          # share of map pixels counted as the map's ink
EDGE_PX = 16        # map pixels from an invalid pixel that count as the mask edge
ENRICH = 3.0        # top-pixel enrichment that flags the edge or empty space
MIN_SHARE = 0.01    # an edge or void zone under this share of valid pixels is too small to judge
VOID_FRACTION = 0.5  # CT below this fraction of the window's median counts as empty space
HALF = 3            # volume: voxels either side of the shifted sheet whose maximum is the map
MIN_WINDOWS = 6     # summary: windows a model verdict needs
MAX_FAILED = 0.2    # summary: largest share of windows that may FAIL


class SheetCheckError(VerifyError):
    """Raised for unusable maps, masks, volumes or meshes."""


# ---------------------------------------------------------------- statistics

def _blur(np, img, sigma):
    from .phantom import gaussian_blur
    return gaussian_blur(img, sigma)


def highpass(m, valid, sigma=SIGMA):
    """The map minus its NaN-aware Gaussian blur; invalid pixels become 0. sigma 0 or None: unchanged."""
    np = _numpy()
    f = np.where(valid, np.asarray(m, dtype=np.float64), 0.0)
    if not sigma:
        return f
    w = _blur(np, valid.astype(np.float64), sigma)
    b = _blur(np, f, sigma) / np.maximum(w, 1e-6)
    return np.where(valid, f - b, 0.0)


def _corr(np, a, b):
    a, b = a - a.mean(), b - b.mean()
    d = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum()) / d if d > 0 else None


def parse_k(text):
    """A shift in sheet pitches from text, as a finite float."""
    try:
        k = float(text)
    except ValueError as exc:
        raise SheetCheckError(f"shift {text!r} is not a number of sheet pitches") from exc
    if not math.isfinite(k):
        raise SheetCheckError(f"shift {text!r} is not finite")
    return k


def profile(maps, valid=None, sigma=SIGMA):
    """{k: r} for every k != 0 in maps ({k: 2D array}, k = 0 required), on pixels valid in every map."""
    np = _numpy()
    if 0.0 not in maps:
        raise SheetCheckError("the map at k = 0 (on the traced sheet) is required")
    shapes = {np.shape(m) for m in maps.values()}
    if len(shapes) != 1:
        raise SheetCheckError(f"maps of different shapes: {sorted(shapes)}")
    ok = np.all([np.isfinite(m) for m in maps.values()], axis=0)
    if valid is not None:
        ok &= np.asarray(valid, dtype=bool)
    if ok.sum() < 100:
        raise SheetCheckError(f"only {int(ok.sum())} pixels are valid in every map")
    hp = {k: highpass(m, ok, sigma)[ok] for k, m in maps.items()}
    return {k: _corr(np, hp[0.0], v) for k, v in sorted(hp.items()) if k != 0.0}, ok


def _side(r, K):
    vals = [r[k] for k in (-float(K), float(K)) if r.get(k) is not None]
    return max(vals) if vals else None


def _edge_zone(np, valid, px):
    """Valid pixels within px of an invalid one (the image border is not an edge: windows are crops)."""
    bad = ~valid
    if not bad.any():
        return np.zeros_like(valid)
    near = _blur(np, bad.astype(np.float64), px / 2.0) > 0.02
    return near & valid


def enrichment(m, valid, zone, top=TOP):
    """(share of the top pixels in zone) / (share of valid pixels in zone), and the zone's share; None if empty."""
    np = _numpy()
    v = np.asarray(m, dtype=np.float64)[valid]
    z = zone[valid]
    share = float(z.mean()) if z.size else 0.0
    if share == 0 or v.size == 0:
        return None, share
    cut = np.quantile(v, 1 - top)
    hi = v >= cut
    return float(z[hi].mean()) / share, share


def check(maps, mask=None, ct=None, sigma=SIGMA, bar=BAR, top=TOP, edge_px=EDGE_PX, enrich=ENRICH,
          void_fraction=VOID_FRACTION, min_share=MIN_SHARE):
    """One window's verdict: PASS, FAIL, or NO-SHIFTS (only the map on the sheet: edge and void checks only)."""
    np = _numpy()
    maps = {float(k): np.asarray(v, dtype=np.float64) for k, v in maps.items()}
    m0 = maps.get(0.0)
    if m0 is None:
        raise SheetCheckError("the map at k = 0 (on the traced sheet) is required")
    valid = np.isfinite(m0)
    if mask is not None:
        mask = np.asarray(mask)
        if mask.shape != m0.shape:
            raise SheetCheckError(f"mask shape {mask.shape} is not the map's {m0.shape}")
        valid &= mask > 0
    why, notes = [], []
    out = {"pixels": int(valid.sum()), "sigma": sigma, "bar": bar, "r": {}, "r1": None, "r2": None,
           "kind": None}
    if len(maps) > 1:
        r, _ = profile(maps, valid, sigma)
        out["r"] = {f"{k:+g}": None if v is None else round(v, 4) for k, v in r.items()}
        r1, r2 = _side(r, 1), _side(r, 2)
        out["r1"], out["r2"] = r1, r2
        if r1 is None and r2 is None:
            why.append("no map at k = -1, +1, -2 or +2")
        for K, rk in ((1, r1), (2, r2)):
            if rk is not None and rk >= bar:
                why.append(f"the map {K} pitch{'es' if K > 1 else ''} away correlates {rk:.3f} with the map on the "
                           f"sheet (bar {bar})")
        if r1 is not None and r2 is not None and r1 >= bar:
            out["kind"] = "shared" if r2 >= SHARED * r1 else "smeared"
            notes.append("alike at two pitches as at one: shading, mesh or CT texture shared by every sheet"
                         if out["kind"] == "shared" else "falls off with distance: smeared along the normal")
    edge, eshare = enrichment(m0, valid, _edge_zone(np, valid, edge_px), top)
    out["edge"] = {"enrichment": edge, "zone_share": round(eshare, 4)}
    if edge is not None and eshare >= min_share and edge >= enrich:
        why.append(f"ink follows the mask edge ({edge:.2f}x as many top pixels within {edge_px} px of it)")
    out["void"] = None
    if ct is not None:
        ct = np.asarray(ct, dtype=np.float64)
        if ct.shape != m0.shape:
            raise SheetCheckError(f"CT shape {ct.shape} is not the map's {m0.shape}")
        cv = valid & np.isfinite(ct)
        med = float(np.median(ct[cv])) if cv.any() else 0.0
        zone = cv & (ct < void_fraction * med)
        v, vshare = enrichment(m0, cv, zone, top)
        out["void"] = {"enrichment": v, "zone_share": round(vshare, 4), "threshold": void_fraction * med,
                       "r_ct": _corr(np, highpass(m0, cv, sigma)[cv], highpass(ct, cv, sigma)[cv])}
        if v is not None and vshare >= min_share and v >= enrich:
            why.append(f"ink lights up empty space ({v:.2f}x as many top pixels where the CT is under "
                       f"{void_fraction:g} of its median)")
    if len(maps) == 1:
        out["verdict"] = "FAIL" if why else "NO-SHIFTS"
        notes.append("no shifted maps: the neighbor-sheet test did not run")
    else:
        out["verdict"] = "FAIL" if why else "PASS"
    out["why"], out["notes"] = why, notes
    return out


def summary(results, min_windows=MIN_WINDOWS, bar=BAR, max_failed=MAX_FAILED):
    """One verdict for a model from {name: window result}: windows, mean r1 under bar, few enough FAILs.

    PASS needs at least min_windows windows that ran the neighbor-sheet test, their mean r1 under bar, and at most
    max_failed of all windows FAIL."""
    ran = {n: r for n, r in results.items() if r.get("verdict") in ("PASS", "FAIL") and r.get("r1") is not None}
    failed = sorted(n for n, r in results.items() if r.get("verdict") == "FAIL")
    r1 = [r["r1"] for r in ran.values()]
    mean_r1 = sum(r1) / len(r1) if r1 else None
    why = []
    if len(ran) < min_windows:
        why.append(f"{len(ran)} windows ran the neighbor-sheet test, under {min_windows}")
    if mean_r1 is not None and mean_r1 >= bar:
        why.append(f"mean r1 {mean_r1:.3f} at or above {bar}")
    if results and len(failed) > max_failed * len(results):
        why.append(f"{len(failed)} of {len(results)} windows FAIL, over {max_failed:.0%}")
    return {"windows": len(results), "ran": len(ran), "failed": failed, "mean_r1": mean_r1,
            "verdict": "FAIL" if why else "PASS", "why": why}


# ---------------------------------------------------------------- 3D projection

def mesh_normals(xyz, valid):
    """Unit normals (H, W, 3) of a tifxyz grid: column step cross row step, central differences."""
    np = _numpy()
    p = np.where(valid[..., None], xyz, np.nan)
    gr, gc = np.gradient(p, axis=0), np.gradient(p, axis=1)
    n = np.cross(gc, gr)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return n / ln


def trilinear(vol, pts, origin):
    """Sample vol (a numpy block whose index 0 is origin, z y x) at pts (N, 3) x y z; NaN outside the block."""
    np = _numpy()
    q = pts[:, ::-1] - np.asarray(origin, dtype=np.float64)       # z y x in block coordinates
    out = np.full(len(q), np.nan)
    ok = np.isfinite(q).all(1) & (q >= 0).all(1) & (q <= np.asarray(vol.shape) - 1).all(1)
    if not ok.any():
        return out
    q = q[ok]
    i0 = np.minimum(np.floor(q).astype(np.int64), np.asarray(vol.shape) - 2).clip(0)
    f = q - i0
    acc = np.zeros(len(q))
    for dz in (0, 1):
        for dy in (0, 1):
            for dx in (0, 1):
                w = ((f[:, 0] if dz else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1])
                     * (f[:, 2] if dx else 1 - f[:, 2]))
                acc += w * vol[i0[:, 0] + dz, i0[:, 1] + dy, i0[:, 2] + dx]
    out[ok] = acc
    return out


def project(volume, xyz, normals, shift=0.0, half=HALF, rows=64):
    """A 2D map (H, W) projected from a 3D volume on a mesh moved shift voxels along its normals.

    For each vertex, the maximum of the volume sampled at vertex + (shift + t) * normal, t from -half to +half in
    steps of 1, in the volume's voxel grid (xyz x y z). Reads one bounding block per strip of rows."""
    np = _numpy()
    H, W = xyz.shape[:2]
    out = np.full((H, W), np.nan, dtype=np.float32)
    ts = np.arange(-half, half + 1, dtype=np.float64) + float(shift)
    shape = np.asarray(volume.shape[-3:])
    for r0 in range(0, H, rows):
        p = xyz[r0:r0 + rows].reshape(-1, 3)
        n = normals[r0:r0 + rows].reshape(-1, 3)
        pts = p[None] + ts[:, None, None] * n[None]                    # (T, N, 3) x y z
        fin = pts[np.isfinite(pts).all(-1)]
        if not len(fin):
            continue
        lo = np.clip(np.floor(fin.min(0))[::-1].astype(int) - 1, 0, shape - 1)
        hi = np.clip(np.ceil(fin.max(0))[::-1].astype(int) + 2, 1, shape)
        block = np.asarray(volume[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]], dtype=np.float64)
        if min(block.shape) < 2:
            continue
        s = trilinear(block, pts.reshape(-1, 3), lo).reshape(len(ts), -1)
        with np.errstate(all="ignore"):
            m = np.where(np.isnan(s).all(0), np.nan, np.nanmax(np.where(np.isnan(s), -np.inf, s), 0))
        out[r0:r0 + rows] = m.reshape(-1, W)
    return out


def open_volume(path, level=0):
    """A z y x array from a local zarr (array, or group with arrays named by level) or a TIFF stack."""
    np = _numpy()
    path = str(path)
    if path.lower().endswith((".tif", ".tiff")):
        import tifffile
        v = tifffile.imread(path)
        if v.ndim != 3:
            raise SheetCheckError(f"{path}: a TIFF volume needs 3 axes, got {v.ndim}")
        return v
    try:
        import zarr
    except ImportError as exc:
        raise SheetCheckError("reading a zarr volume needs zarr: pip install zarr") from exc
    z = zarr.open(path, mode="r")
    if hasattr(z, "shape"):
        arr = z
    else:
        key = str(level)
        if key not in z:
            raise SheetCheckError(f"{path}: no array {key!r} (use --level)")
        arr = z[key]
    if len(arr.shape) != 3:
        raise SheetCheckError(f"{path}: expected 3 axes (z y x), got {arr.shape}")
    del np
    return arr


def volume_maps(volume, mesh, pitch, ks=(-2.0, -1.0, 0.0, 1.0, 2.0), scale=1.0, half=HALF, flip=False,
                rows=None, cols=None):
    """{k: map} projected from a prediction volume on a tifxyz mesh at each shift k (in pitches).

    pitch is in the volume's voxels; scale maps mesh coordinates to the volume grid (0.5 for a level-1 volume and a
    level-0 mesh)."""
    from . import tifxyz
    np = _numpy()
    seg = tifxyz.load(mesh)
    xyz, valid = seg.xyz, seg.valid
    if rows:
        xyz, valid = xyz[rows[0]:rows[1]], valid[rows[0]:rows[1]]
    if cols:
        xyz, valid = xyz[:, cols[0]:cols[1]], valid[:, cols[0]:cols[1]]
    if not valid.any():
        raise SheetCheckError(f"{mesh}: no valid vertices in the chosen rows and columns")
    xyz = np.where(valid[..., None], xyz * float(scale), np.nan)
    n = mesh_normals(xyz, valid) * (-1.0 if flip else 1.0)
    ks = sorted(set(float(k) for k in ks) | {0.0})
    return {k: project(volume, xyz, n, k * float(pitch), half) for k in ks}


# ---------------------------------------------------------------- synthetic demo

def demo_maps(kind, shape=(256, 256), seed=0, sheets=5):
    """Synthetic maps at k = -2..2 for one kind: sharp, smeared, shared, edge or void. Returns (maps, mask, ct)."""
    from .phantom import _stroke_mask, gaussian_blur
    np = _numpy()
    rng = np.random.default_rng(seed)
    h, w = shape
    ink = [gaussian_blur(_stroke_mask(np, rng, h, w, 64, 8, 0.5, 0.7)[0].astype(np.float64), 1.5)
           for _ in range(sheets)]
    c = sheets // 2
    noise = lambda: 0.5 * rng.standard_normal(shape)   # noqa: E731
    mask = np.ones(shape, dtype=bool)
    mask[:, : w // 8] = False                            # an unlabeled strip: the mask edge
    yy, xx = np.mgrid[0:h, 0:w]
    ct = 1.0 + 0.1 * rng.standard_normal(shape)
    crack = np.abs(yy - 0.55 * xx - h * 0.3) < 6         # a dark crack under the mesh
    ct[crack] = 0.2
    art = gaussian_blur(rng.standard_normal(shape), 6)
    art *= 0.4 / art.std()                               # a pattern every sheet shares (CT texture, mesh)
    maps = {}
    for k in range(-2, 3):
        i = c + k
        if kind == "smeared":                            # each map averages neighboring sheets
            wts = np.exp(-0.5 * ((np.arange(sheets) - i) / 1.0) ** 2)
            m = sum(wt * a for wt, a in zip(wts, ink)) / wts.sum()
        elif kind == "shared":
            m = 0.4 * ink[i] + art
        else:
            m = ink[i].copy()
        maps[float(k)] = (m - m.mean()) / m.std() + noise()
    if kind == "edge":
        d = np.clip(xx - w // 8, 0, None)
        maps[0.0] = maps[0.0] + 4.0 * np.exp(-d / 8.0)
    if kind == "void":
        maps[0.0] = maps[0.0] + 3.0 * crack
    for k in maps:
        maps[k] = np.where(mask, maps[k], np.nan)
    return maps, mask, ct


DEMO_KINDS = ("sharp", "smeared", "shared", "edge", "void")


def demo(seed=0, shape=(256, 256)):
    """{kind: window result} for the five synthetic kinds; only "sharp" should PASS."""
    out = {}
    for kind in DEMO_KINDS:
        maps, mask, ct = demo_maps(kind, shape, seed)
        out[kind] = check(maps, mask, ct)
    return out


def demo_png(path, seed=0, shape=(256, 256)):
    """A picture of the demo: one row per kind, the map at k = -1, 0, +1, and the verdict as a colored bar."""
    from .tifxyz import write_png
    np = _numpy()
    rows = []
    res = demo(seed, shape)
    for kind in DEMO_KINDS:
        maps, mask, _ = demo_maps(kind, shape, seed)
        tiles = []
        for k in (-1.0, 0.0, 1.0):
            m = maps[k]
            v = m[np.isfinite(m)]
            lo, hi = np.quantile(v, [0.01, 0.99])
            t = np.clip((np.nan_to_num(m, nan=lo) - lo) / (hi - lo + 1e-9), 0, 1)
            t = np.where(np.isfinite(m), t, 0.15)
            tiles.append(np.repeat((t * 255).astype(np.uint8)[..., None], 3, -1))
            tiles.append(np.full((m.shape[0], 8, 3), 255, np.uint8))
        bar = np.zeros((m.shape[0], 24, 3), np.uint8)
        bar[:] = (46, 160, 67) if res[kind]["verdict"] == "PASS" else (207, 34, 46)
        rows.append(np.concatenate(tiles + [bar], 1))
        rows.append(np.full((8, rows[-1].shape[1], 3), 255, np.uint8))
    write_png(str(path), np.concatenate(rows[:-1], 0))
    return res


# ---------------------------------------------------------------- command line

_MAP = re.compile(r"^\s*([+-]?[0-9.]+)\s*=(.+)$")


def _parse_map(spec):
    m = _MAP.match(spec)
    if not m:
        raise SheetCheckError(f"--map {spec!r}: expected K=PATH, such as 0=on.tif or -1=in.tif")
    return parse_k(m.group(1)), m.group(2)


def _read2d(path):
    np = _numpy()
    path = str(path)
    if path.endswith(".npy"):
        a = np.squeeze(np.load(path))
        if a.ndim != 2:
            raise SheetCheckError(f"{path}: expected a 2D map, got shape {a.shape}")
        return a
    return load_map(path)


def format_result(name, r):
    """Plain lines for one window result: the correlations, the edge and void enrichments, notes and verdict."""
    lines = []
    rs = "  ".join(f"r({k}) {'n/a' if v is None else f'{v:+.3f}'}" for k, v in r["r"].items())
    if rs:
        lines.append(f"{name}  {rs}")
    e = r.get("edge") or {}
    if e.get("enrichment") is not None:
        lines.append(f"{name}  mask edge: {e['enrichment']:.2f}x top pixels ({e['zone_share']:.1%} of the window)")
    v = r.get("void")
    if v and v.get("enrichment") is not None:
        lines.append(f"{name}  empty space: {v['enrichment']:.2f}x top pixels ({v['zone_share']:.1%} of the window)")
    for n in r.get("notes", []):
        lines.append(f"{name}  note: {n}")
    lines.append(f"{name}  {r['verdict']}" + (f" ({'; '.join(r['why'])})" if r["why"] else ""))
    return "\n".join(lines)


def build_parser(p):
    """Adds maps, volume, demo and summary to an argparse parser."""
    s = p.add_subparsers(dest="action", required=True)

    def common(c):
        c.add_argument("--name", default="window", help="window name in the output (default: window)")
        c.add_argument("--sigma", type=float, default=SIGMA, help=f"high-pass blur in map pixels (default {SIGMA:g})")
        c.add_argument("--bar", type=float, default=BAR, help=f"largest r at one or two pitches (default {BAR})")
        c.add_argument("--top", type=float, default=TOP, help=f"share of pixels counted as ink (default {TOP})")
        c.add_argument("--edge-px", type=float, default=EDGE_PX, help=f"mask edge width (default {EDGE_PX})")
        c.add_argument("--enrich", type=float, default=ENRICH, help=f"enrichment that flags (default {ENRICH})")
        c.add_argument("--json", action="store_true", help="print the result as JSON")

    m = s.add_parser("maps", help="check 2D maps read at several normal shifts")
    m.add_argument("--map", action="append", required=True, metavar="K=PATH",
                   help="map read k sheet pitches along the normal (TIFF or .npy); k = 0 is required")
    m.add_argument("--mask", help="valid pixels (nonzero), same grid")
    m.add_argument("--ct", help="CT on the traced sheet, same grid: adds the empty-space check")
    common(m)

    v = s.add_parser("volume", help="project a 3D prediction on a tifxyz mesh at several shifts, then check")
    v.add_argument("volume", help="prediction volume: local zarr (z y x) or TIFF stack")
    v.add_argument("mesh", help="tifxyz folder (local or open-data URL)")
    v.add_argument("--pitch", type=float, required=True, help="sheet pitch in the volume's voxels")
    v.add_argument("--k", type=float, action="append", help="shifts in pitches (default -2 -1 0 1 2)")
    v.add_argument("--scale", type=float, default=1.0, help="mesh coordinates to volume grid (0.5: level 1)")
    v.add_argument("--level", type=int, default=0, help="zarr group level (default 0)")
    v.add_argument("--half", type=int, default=HALF, help=f"voxels either side of the sheet (default {HALF})")
    v.add_argument("--flip", action="store_true", help="reverse the mesh normals")
    v.add_argument("--rows", type=int, nargs=2, metavar=("R0", "R1"), help="mesh rows to use")
    v.add_argument("--cols", type=int, nargs=2, metavar=("C0", "C1"), help="mesh columns to use")
    v.add_argument("--ct", help="CT volume (zarr or TIFF stack, same grid as the prediction) for the void check")
    v.add_argument("--save-maps", help="folder to write the projected maps (k+0.tif and so on)")
    common(v)

    d = s.add_parser("demo", help="synthetic sheets: one sharp map passes, four kinds of false ink fail")
    d.add_argument("--seed", type=int, default=0, help="random seed of the synthetic sheets (default 0)")
    d.add_argument("--png", help="write a picture of the demo")
    d.add_argument("--json", action="store_true", help="print the results as JSON")

    u = s.add_parser("summary", help="window results (--json of maps or volume) into one verdict")
    u.add_argument("results", nargs="+", help="JSON files, each one window result or {name: result}")
    u.add_argument("--min-windows", type=int, default=MIN_WINDOWS, help=f"windows needed (default {MIN_WINDOWS})")
    u.add_argument("--bar", type=float, default=BAR, help=f"mean r1 must stay under this (default {BAR})")
    u.add_argument("--max-failed", type=float, default=MAX_FAILED,
                   help=f"largest share of windows that may FAIL (default {MAX_FAILED})")
    u.add_argument("--json", action="store_true", help="print the summary and every window as JSON")


def _opts(a):
    return dict(sigma=a.sigma, bar=a.bar, top=a.top, edge_px=a.edge_px, enrich=a.enrich)


def run(a):
    """The result for parsed arguments: {name: window result}, or {"summary", "windows"} for summary."""
    if a.action == "maps":
        maps = {}
        for spec in a.map:
            k, path = _parse_map(spec)
            if k in maps:
                raise SheetCheckError(f"two maps for k = {k:g}")
            maps[k] = _read2d(path)
        mask = _read2d(a.mask) if a.mask else None
        ct = _read2d(a.ct) if a.ct else None
        return {a.name: check(maps, mask, ct, **_opts(a))}
    if a.action == "volume":
        vol = open_volume(a.volume, a.level)
        ks = a.k or (-2.0, -1.0, 0.0, 1.0, 2.0)
        maps = volume_maps(vol, a.mesh, a.pitch, ks, a.scale, a.half, a.flip, a.rows, a.cols)
        ct = None
        if a.ct:
            ct = volume_maps(open_volume(a.ct, a.level), a.mesh, a.pitch, (0.0,), a.scale, 0, a.flip,
                             a.rows, a.cols)[0.0]
        if a.save_maps:
            import tifffile
            out = Path(a.save_maps)
            out.mkdir(parents=True, exist_ok=True)
            for k, m in maps.items():
                tifffile.imwrite(str(out / f"k{k:+g}.tif"), m)
        return {a.name: check(maps, None, ct, **_opts(a))}
    if a.action == "demo":
        return demo_png(a.png, a.seed) if a.png else demo(a.seed)
    res = {}
    for f in a.results:
        d = json.loads(Path(f).read_text())
        items = {Path(f).stem: d} if "verdict" in d else d
        for n, r in items.items():
            if n in res:
                raise SheetCheckError(f"window {n} appears twice")
            res[n] = r
    return {"summary": summary(res, a.min_windows, a.bar, a.max_failed), "windows": res}


def cmd_sheetcheck(a):
    """Runs and prints; exit 0 on PASS (or NO-SHIFTS, or a demo that behaved), 1 on FAIL, 2 on unusable input."""
    try:
        res = run(a)
    except (VerifyError, OSError, ValueError) as exc:
        print(f"kit sheetcheck: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=1, sort_keys=True, default=float))
    elif a.action == "summary":
        s = res["summary"]
        r1 = "n/a" if s["mean_r1"] is None else f"{s['mean_r1']:.3f}"
        for n, r in sorted(res["windows"].items()):
            print(f"{n}  r1 {'n/a' if r.get('r1') is None else format(r['r1'], '.3f')}  {r['verdict']}")
        print(f"{s['windows']} windows, {s['ran']} with the neighbor-sheet test, mean r1 {r1}: {s['verdict']}"
              + (f" ({'; '.join(s['why'])})" if s["why"] else ""))
    else:
        for n, r in res.items():
            print(format_result(n, r))
        if a.action == "demo" and getattr(a, "png", None):
            print(f"picture: {a.png}")
    if a.action == "summary":
        return 0 if res["summary"]["verdict"] == "PASS" else 1
    if a.action == "demo":
        return 0 if all(r["verdict"] == ("PASS" if k == "sharp" else "FAIL") for k, r in res.items()) else 1
    return 0 if all(r["verdict"] in ("PASS", "NO-SHIFTS") for r in res.values()) else 1


def main(argv=None):
    """Command line entry: python -m kit sheetcheck."""
    p = argparse.ArgumentParser(prog="python -m kit sheetcheck", description=__doc__.split("\n")[0])
    build_parser(p)
    return cmd_sheetcheck(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
