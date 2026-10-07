"""Mesh and cross-scan render audit (protocol: docs/plans/2026-10-07-mesh-hypothesis.md).

Three checks on published data, all derived numbers only:

* ``transforms``: refit each catalogue affine from its stored landmarks; fit residual,
  leave-one-out error, inverse consistency and scale, in micrometres.
* ``canvas``: does a published mesh variant reproduce each surface volume's canvas size?
* ``depth``: where does the papyrus band sit along the normal in a segment's native render
  versus its cross-scan renders? Brightness peaks, never ink.

Network access is plain HTTPS to the public bucket (no AWS tools). Surface-volume chunks are
read directly when uncompressed (the published layout); compressed arrays need ``zarr``.
"""

import gzip
import json
import math
import re
import struct
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
SEED = 20261007
TIERS_UM = (25.0, 75.0)
CANVAS_RATIOS = (1.0, 0.5, 2.0, 4.0, 0.25)


# ---------------------------------------------------------------- HTTP and catalogue

def _get(url, byte_range=None, timeout=60):
    headers = {"Accept-Encoding": "identity"}
    if byte_range:
        headers["Range"] = "bytes=%d-%d" % byte_range
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def get_json(url):
    if "://" not in url:
        with open(url, "rb") as f:
            data = f.read()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return json.loads(data)
    return json.loads(_get(url))


def load_catalogue(path_or_url=None):
    return get_json(path_or_url or BUCKET + "/metadata.json")


def tif_dims(url):
    """Width and height of a classic TIFF or BigTIFF from its first IFD, via two range requests."""
    head = _get(url, (0, 15))
    bo = "<" if head[:2] == b"II" else ">"
    version = struct.unpack(bo + "H", head[2:4])[0]
    if version == 42:
        off = struct.unpack(bo + "I", head[4:8])[0]
        return parse_ifd_dims(_get(url, (off, off + 2 + 12 * 64)), bo)
    if version == 43:
        off = struct.unpack(bo + "Q", head[8:16])[0]
        return parse_ifd_dims(_get(url, (off, off + 8 + 20 * 64)), bo, big=True)
    raise ValueError("not a TIFF (version %d): %s" % (version, url))


def parse_ifd_dims(ifd, bo="<", big=False):
    if big:
        n, head, size, cnt_fmt = struct.unpack(bo + "Q", ifd[:8])[0], 8, 20, "Q"
    else:
        n, head, size, cnt_fmt = struct.unpack(bo + "H", ifd[:2])[0], 2, 12, "I"
    w = h = None
    for i in range(n):
        e = ifd[head + size * i:head + size * (i + 1)]
        if len(e) < size:
            break
        tag, typ = struct.unpack(bo + "HH", e[:4])
        v = e[4 + struct.calcsize(cnt_fmt):]
        if typ == 3:
            val = struct.unpack(bo + "H", v[:2])[0]
        elif typ == 16:
            val = struct.unpack(bo + "Q", v[:8])[0]
        else:
            val = struct.unpack(bo + "I", v[:4])[0]
        if tag == 256:
            w = val
        elif tag == 257:
            h = val
    if w is None or h is None:
        raise ValueError("TIFF IFD lacks width or height")
    return w, h


# ---------------------------------------------------------------- H2: transforms

def fit_affine(src, dst):
    """Least-squares 3x4 affine M with dst ~= M[:, :3] @ src + M[:, 3]."""
    import numpy as np
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    a = np.c_[src, np.ones(len(src))]
    x, *_ = np.linalg.lstsq(a, dst, rcond=None)
    return x.T


def apply_affine(m, pts):
    import numpy as np
    m = np.asarray(m, float)
    return np.asarray(pts, float) @ m[:, :3].T + m[:, 3]


def loo_errors(src, dst):
    """Leave-one-out residual norms (target units); None when fewer than 5 landmarks."""
    import numpy as np
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    n = len(src)
    if n < 5:
        return None
    out = []
    for i in range(n):
        keep = np.arange(n) != i
        m = fit_affine(src[keep], dst[keep])
        out.append(float(np.linalg.norm(apply_affine(m, src[i:i + 1])[0] - dst[i])))
    return out


def tier(loo_rms_um):
    if loo_rms_um is None:
        return "untestable"
    if loo_rms_um < TIERS_UM[0]:
        return "tight"
    if loo_rms_um <= TIERS_UM[1]:
        return "loose"
    return "coarse"


def audit_transform(matrix, src, dst, px_from_um, px_to_um, reverse=None):
    """Numbers for one stored transform. Units: micrometres unless named otherwise."""
    import numpy as np
    m = np.asarray(matrix, float)
    rec = {"n_landmarks": len(src) if src else 0, "px_from_um": px_from_um, "px_to_um": px_to_um}
    det = float(np.linalg.det(m[:, :3]))
    iso = abs(det) ** (1.0 / 3.0)
    expect = px_from_um / px_to_um if px_from_um and px_to_um else None
    rec["iso_scale"] = iso
    rec["expected_scale"] = expect
    rec["scale_dev_pct"] = 100.0 * (iso / expect - 1.0) if expect else None
    sv = np.linalg.svd(m[:, :3], compute_uv=False)
    rec["anisotropy_pct"] = 100.0 * float(sv.max() / sv.min() - 1.0)
    rec["handedness_flip"] = det < 0
    if not src or len(src) < 4:
        rec.update(refit_max_diff=None, fit_rms_um=None, loo_rms_um=None, loo_max_um=None, tier="untestable")
        return rec
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    spread = np.linalg.svd(src - src.mean(axis=0), compute_uv=False)
    # 0 for coplanar landmarks: the affine is then undetermined across that plane
    rec["landmark_flatness"] = float(spread[-1] / spread[0]) if spread[0] > 0 else 0.0
    refit = fit_affine(src, dst)
    rec["refit_max_diff"] = float(np.abs(refit - m).max())
    res = np.linalg.norm(apply_affine(m, src) - dst, axis=1)
    rec["fit_rms_um"] = float(np.sqrt((res ** 2).mean()) * px_to_um)
    rec["fit_max_um"] = float(res.max() * px_to_um)
    rres = np.linalg.norm(apply_affine(refit, src) - dst, axis=1)
    rec["refit_rms_um"] = float(np.sqrt((rres ** 2).mean()) * px_to_um)
    # the stored matrix should be (close to) the least-squares fit of its own landmarks
    rec["matrix_matches_landmarks"] = bool(rec["fit_rms_um"] <= rec["refit_rms_um"] + 1.0)
    loo = loo_errors(src, dst)
    if loo is None:
        rec["loo_rms_um"] = rec["loo_max_um"] = None
    else:
        loo = np.asarray(loo) * px_to_um
        rec["loo_rms_um"] = float(np.sqrt((loo ** 2).mean()))
        rec["loo_max_um"] = float(loo.max())
    rec["tier"] = tier(rec["loo_rms_um"])
    if reverse is not None:
        back = apply_affine(reverse, apply_affine(m, src))
        rec["roundtrip_max_um"] = float(np.linalg.norm(back - src, axis=1).max() * px_from_um)
    return rec


def transforms_audit(cat):
    """One record per stored transform with its volumes' voxel sizes."""
    rows = []
    for sid, s in sorted(cat["samples"].items()):
        vols = s.get("volumes") or {}
        px = {vid: (v.get("properties") or {}).get("pixel_size_um") for vid, v in vols.items()}
        stored = {}
        for vid, v in vols.items():
            for t in (v.get("properties") or {}).get("transforms") or []:
                stored[(vid, t["to_volume_id"])] = t
        for (a, b), t in sorted(stored.items()):
            rev = stored.get((b, a))
            rec = audit_transform(t["transformation_matrix"], t.get("from_landmarks"), t.get("to_landmarks"),
                                  px.get(a), px.get(b),
                                  reverse=rev["transformation_matrix"] if rev else None)
            rec.update(sample=sid, from_volume=a, to_volume=b, has_reverse=rev is not None)
            rows.append(rec)
    return rows


# ---------------------------------------------------------------- H1: canvas

def canvas_match(canvas, tif_wh, scale, ratios=CANVAS_RATIOS, tol=1.0):
    """Ratio r in `ratios` with |canvas - (dim / scale) * r| <= tol on both axes, else None."""
    gw, gh = tif_wh[0] / scale[0], tif_wh[1] / scale[1]
    for r in ratios:
        if abs(canvas[0] - gw * r) <= tol and abs(canvas[1] - gh * r) <= tol:
            return r
    return None


def _volume_id_in(name):
    m = re.search(r"volume-(\d{14})", name)
    return m.group(1) if m else None


def segment_entries(seg):
    """Surface-volume and mesh paths from a catalogue segment record."""
    sv, meshes = [], []
    for x in seg.get("data", []):
        for o in x.get("origins", []):
            p = o.get("path", "")
            if x["type"] == "layers-zarr":
                sv.append(p.rstrip("/"))
            elif x["type"].startswith("tifxyz"):
                meshes.append((x["type"], p.rstrip("/")))
    return sv, meshes


def canvas_audit(cat, samples=None, workers=16, base=BUCKET):
    jobs = []
    for sid, s in sorted(cat["samples"].items()):
        if samples and sid not in samples:
            continue
        for gid, g in sorted((s.get("segments") or {}).items()):
            sv, meshes = segment_entries(g)
            if sv:
                jobs.append((sid, gid, g, sv, meshes))

    def mesh_info(path):
        try:
            meta = get_json("%s/%s/meta.json" % (base, path))
            return {"path": path, "scale": meta.get("scale"), "wh": tif_dims("%s/%s/x.tif" % (base, path))}
        except Exception as e:  # noqa: BLE001 (record and continue)
            return {"path": path, "error": str(e)[:200]}

    def zattrs(path):
        try:
            return get_json("%s/%s/.zattrs" % (base, path))
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}

    paths_m = sorted({p for j in jobs for _, p in j[4]})
    paths_v = sorted({p for j in jobs for p in j[3]})
    with ThreadPoolExecutor(workers) as ex:
        minfo = dict(zip(paths_m, ex.map(mesh_info, paths_m)))
        vinfo = dict(zip(paths_v, ex.map(zattrs, paths_v)))
    rows = []
    for sid, gid, g, sv, meshes in jobs:
        cov = ((g.get("properties") or {}).get("volume_coverage")) or {}
        for p in sv:
            za = vinfo[p]
            vid = _volume_id_in(p.split("/")[-1])
            rec = {"sample": sid, "segment": gid, "surface_volume": p.split("/")[-1], "volume": vid,
                   "native_volume": g.get("original_volume_id"), "canvas": za.get("canvas_size"),
                   "overlap_ratio": (cov.get(vid) or {}).get("overlap_ratio"), "matches": []}
            if "error" in za or not za.get("canvas_size"):
                rec["error"] = za.get("error", "no canvas_size")
            else:
                for typ, mp in meshes:
                    mi = minfo[mp]
                    if "error" in mi or not mi.get("scale"):
                        continue
                    r = canvas_match(za["canvas_size"], mi["wh"], mi["scale"])
                    if r is not None:
                        rec["matches"].append({"mesh": mp.split("/")[-1], "type": typ, "ratio": r,
                                               "names_volume": vid is not None and vid in mp})
            rec["reproducible"] = bool(rec["matches"])
            rec["reproducible_by_named_variant"] = any(m["names_volume"] for m in rec["matches"])
            rows.append(rec)
    mesh_errors = [m for m in minfo.values() if "error" in m]
    return rows, mesh_errors


# ---------------------------------------------------------------- H3: depth profiles

def gaussian_smooth(y, sigma):
    import numpy as np
    y = np.asarray(y, float)
    if sigma <= 0:
        return y.copy()
    r = max(1, int(math.ceil(3 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(y, r, mode="reflect") if len(y) > r else np.pad(y, r, mode="edge")
    return np.convolve(pad, k, mode="valid")


def layer_positions_um(n_layers, dz_um):
    import numpy as np
    return (np.arange(n_layers) - (n_layers - 1) / 2.0) * dz_um


def sheet_peak_um(profile, dz_um, sigma_um=8.0, window_um=60.0):
    """Highest local maximum of the smoothed profile within +-window_um of the centre layer,
    refined with a parabola. Returns micrometres from the centre layer, or None."""
    import numpy as np
    p = np.asarray(profile, float)
    if p.size < 3 or not np.isfinite(p).all():
        return None
    s = gaussian_smooth(p, sigma_um / dz_um)
    z = layer_positions_um(p.size, dz_um)
    best = None
    for i in range(1, p.size - 1):
        if s[i] >= s[i - 1] and s[i] > s[i + 1] and abs(z[i]) <= window_um:
            if best is None or s[i] > s[best]:
                best = i
    if best is None:
        return None
    a, b, c = s[best - 1], s[best], s[best + 1]
    den = a - 2 * b + c
    frac = 0.5 * (a - c) / den if den != 0 else 0.0
    return float(z[best] + max(-0.5, min(0.5, frac)) * dz_um)


def shape_corr(p_native, dz_native, p_cross, dz_cross, flip=False, half_um=60.0, step_um=1.0):
    """Pearson correlation of two profiles on a common micrometre grid within +-half_um."""
    import numpy as np
    zn = layer_positions_um(len(p_native), dz_native)
    zc = layer_positions_um(len(p_cross), dz_cross)
    pc = np.asarray(p_cross, float)
    if flip:
        pc = pc[::-1]
    lo = max(zn[0], zc[0], -half_um)
    hi = min(zn[-1], zc[-1], half_um)
    if hi - lo < 4 * step_um:
        return float("nan")
    g = np.arange(lo, hi + step_um / 2, step_um)
    a = np.interp(g, zn, np.asarray(p_native, float))
    b = np.interp(g, zc, pc)
    a = a - a.mean()
    b = b - b.mean()
    d = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else float("nan")


def compare_profiles(native, cross, dz_native, dz_cross):
    """Per-tile offsets and the location control for one segment pair.

    native, cross: lists of profiles (or None) for the same tile centres."""
    import numpy as np
    pairs = [(a, b) for a, b in zip(native, cross) if a is not None and b is not None]
    out = {"tiles_with_profiles": len(pairs)}
    if len(pairs) < 4:
        out["evaluable"] = False
        out["reason"] = "fewer than 4 tiles with both profiles"
        return out
    fwd = [shape_corr(a, dz_native, b, dz_cross) for a, b in pairs]
    rev = [shape_corr(a, dz_native, b, dz_cross, flip=True) for a, b in pairs]
    flip = int(np.sum(np.nan_to_num(rev, nan=-2) > np.nan_to_num(fwd, nan=-2))) > len(pairs) / 2
    out["layer_order_opposite"] = bool(flip)
    matched = np.array(rev if flip else fwd, float)
    disp = []
    n = len(pairs)
    for i in range(n):
        for j in range(n):
            if i != j:
                disp.append(shape_corr(pairs[i][0], dz_native, pairs[j][1], dz_cross, flip=flip))
    disp = np.array(disp, float)
    out["matched_corr_median"] = float(np.nanmedian(matched))
    out["displaced_corr_p95"] = float(np.nanpercentile(disp, 95))
    out["location_control_pass"] = bool(out["matched_corr_median"] > out["displaced_corr_p95"])
    deltas = []
    for a, b in pairs:
        pa = sheet_peak_um(a, dz_native)
        pb = sheet_peak_um(b[::-1] if flip else b, dz_cross)
        if pa is not None and pb is not None:
            deltas.append(pb - pa)
    d = np.array(deltas, float)
    out["tiles_with_peaks"] = int(d.size)
    if d.size:
        med = float(np.median(d))
        out.update(delta_median_um=med, delta_mad_um=float(np.median(np.abs(d - med))),
                   frac_abs_over_25um=float(np.mean(np.abs(d) > TIERS_UM[0])),
                   frac_abs_over_75um=float(np.mean(np.abs(d) > TIERS_UM[1])),
                   deltas_um=[round(float(x), 2) for x in d])
    out["evaluable"] = bool(out["location_control_pass"] and d.size >= 4)
    return out


class SurfaceVolume:
    """Read windows of a published surface-volume zarr (v2, ZYX, chunks spanning all layers)."""

    def __init__(self, base_url, fetch=None, fetch_range=None):
        self.base = base_url.rstrip("/")
        self.fetch = fetch or (lambda u: _get(u))
        if fetch_range is None:
            fetch_range = (lambda u, a, b: self.fetch(u)[a:b + 1]) if fetch else (lambda u, a, b: _get(u, (a, b)))
        self.fetch_range = fetch_range
        self.attrs = json.loads(self.fetch(self.base + "/.zattrs"))
        self.levels = []
        for ds in self.attrs["multiscales"][0]["datasets"]:
            sc = [t for t in ds["coordinateTransformations"] if t["type"] == "scale"][0]["scale"]
            za = json.loads(self.fetch("%s/%s/.zarray" % (self.base, ds["path"])))
            self.levels.append({"path": ds["path"], "scale_um": sc, "zarray": za})
        self.dz_um = self.levels[0]["scale_um"][0]
        self.n_layers = self.levels[0]["zarray"]["shape"][0]

    def level_near(self, target_um):
        return min(range(len(self.levels)), key=lambda k: abs(self.levels[k]["scale_um"][1] - target_um))

    def read(self, level, r0, r1, c0, c1):
        import numpy as np
        lv = self.levels[level]
        za = lv["zarray"]
        if za.get("compressor") is not None or za.get("filters"):
            import zarr  # optional path
            return np.asarray(zarr.open_array(self.base + "/" + lv["path"], mode="r")[:, r0:r1, c0:c1])
        L, H, W = za["shape"]
        cz, cy, cx = za["chunks"]
        r0, r1, c0, c1 = max(r0, 0), min(r1, H), max(c0, 0), min(c1, W)
        out = np.full((L, max(r1 - r0, 0), max(c1 - c0, 0)), za.get("fill_value") or 0, dtype=np.dtype(za["dtype"]))
        sep = za.get("dimension_separator", ".")
        for zi in range(0, (L + cz - 1) // cz):
            for yi in range(r0 // cy, (r1 - 1) // cy + 1 if r1 > r0 else 0):
                for xi in range(c0 // cx, (c1 - 1) // cx + 1 if c1 > c0 else 0):
                    key = sep.join(str(k) for k in (zi, yi, xi))
                    try:
                        raw = self.fetch("%s/%s/%s" % (self.base, lv["path"], key))
                    except Exception:  # noqa: BLE001 (absent chunk = fill value)
                        continue
                    blk = np.frombuffer(raw, dtype=np.dtype(za["dtype"])).reshape(cz, cy, cx)
                    ys, xs = yi * cy, xi * cx
                    a0, a1 = max(r0, ys), min(r1, ys + cy)
                    b0, b1 = max(c0, xs), min(c1, xs + cx)
                    z1 = min(L, (zi + 1) * cz)
                    out[zi * cz:z1, a0 - r0:a1 - r0, b0 - c0:b1 - c0] = blk[:z1 - zi * cz, a0 - ys:a1 - ys, b0 - xs:b1 - xs]
        return out

    def read_layer(self, level, layer, r0, r1, c0, c1):
        """One layer of a window, fetching only that layer's bytes from each uncompressed chunk."""
        import numpy as np
        lv = self.levels[level]
        za = lv["zarray"]
        if za.get("compressor") is not None or za.get("filters"):
            return self.read(level, r0, r1, c0, c1)[layer]
        L, H, W = za["shape"]
        cz, cy, cx = za["chunks"]
        dt = np.dtype(za["dtype"])
        r0, r1, c0, c1 = max(r0, 0), min(r1, H), max(c0, 0), min(c1, W)
        out = np.full((max(r1 - r0, 0), max(c1 - c0, 0)), za.get("fill_value") or 0, dtype=dt)
        sep = za.get("dimension_separator", ".")
        zi, zl = divmod(layer, cz)
        n = cy * cx * dt.itemsize
        for yi in range(r0 // cy, (r1 - 1) // cy + 1 if r1 > r0 else 0):
            for xi in range(c0 // cx, (c1 - 1) // cx + 1 if c1 > c0 else 0):
                key = sep.join(str(k) for k in (zi, yi, xi))
                try:
                    raw = self.fetch_range("%s/%s/%s" % (self.base, lv["path"], key), zl * n, zl * n + n - 1)
                except Exception:  # noqa: BLE001 (absent chunk = fill value)
                    continue
                blk = np.frombuffer(raw, dtype=dt).reshape(cy, cx)
                ys, xs = yi * cy, xi * cx
                a0, a1 = max(r0, ys), min(r1, ys + cy)
                b0, b1 = max(c0, xs), min(c1, xs + cx)
                out[a0 - r0:a1 - r0, b0 - c0:b1 - c0] = blk[a0 - ys:a1 - ys, b0 - xs:b1 - xs]
        return out

    def profile(self, u, v, target_um=20.0, window_mm=1.5):
        """Mean intensity per layer over nonzero pixels of a square window centred at
        normalized canvas coordinates (u along columns, v along rows). None if invalid."""
        import numpy as np
        k = self.level_near(target_um)
        lv = self.levels[k]
        _, H, W = lv["zarray"]["shape"]
        px = lv["scale_um"][1]
        half = max(2, int(round(window_mm * 1000.0 / px / 2)))
        _, H0, W0 = self.levels[0]["zarray"]["shape"]
        f = self.levels[0]["scale_um"][1] / px  # full-resolution canvas to this level
        r, c = int(v * H0 * f), int(u * W0 * f)
        blk = self.read(k, r - half, r + half, c - half, c + half).astype(np.float64)
        if blk.size == 0:
            return None
        valid = blk[blk.shape[0] // 2] > 0
        if valid.mean() < 0.5:
            return None
        return [float(blk[i][valid].mean()) for i in range(blk.shape[0])]


def tile_centres(n, seed=SEED):
    import numpy as np
    rng = np.random.default_rng(seed)
    return [(float(a), float(b)) for a, b in rng.random((n, 2))]


def depth_segment(base, sample_id, seg, cross_ids=None, n_tiles=32, seed=SEED, workers=8, reference=None):
    """Compare the native render (or `reference` volume's render) with each other render of one
    catalogue segment."""
    sv, _ = segment_entries(seg)
    by_vol = {}
    for p in sv:  # first surface volume per volume id
        by_vol.setdefault(_volume_id_in(p.split("/")[-1]), p)
    native = reference or seg.get("original_volume_id")
    out = {"sample": sample_id, "segment": seg.get("long_id") or seg.get("id"), "native_volume": native,
           "reference_is_native": reference is None or reference == seg.get("original_volume_id"), "pairs": []}
    if native not in by_vol:
        out["error"] = "no surface volume on the native volume"
        return out
    nsv = SurfaceVolume("%s/%s" % (base, by_vol[native]))
    centres = tile_centres(n_tiles, seed)
    with ThreadPoolExecutor(workers) as ex:
        nprof = list(ex.map(lambda uv: _safe(nsv.profile, *uv), centres))
    out["native_dz_um"] = nsv.dz_um
    out["native_tiles_valid"] = sum(p is not None for p in nprof)
    for vid, p in sorted(by_vol.items()):
        if vid == native or (cross_ids and vid not in cross_ids):
            continue
        rec = {"cross_volume": vid, "surface_volume": p.split("/")[-1]}
        try:
            csv = SurfaceVolume("%s/%s" % (base, p))
            with ThreadPoolExecutor(workers) as ex:
                cprof = list(ex.map(lambda uv: _safe(csv.profile, *uv) if nprof[centres.index(uv)] is not None else None,
                                    centres))
            rec["cross_dz_um"] = csv.dz_um
            rec.update(compare_profiles(nprof, cprof, nsv.dz_um, csv.dz_um))
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        out["pairs"].append(rec)
    return out


def _safe(f, *a):
    try:
        return f(*a)
    except Exception:  # noqa: BLE001
        return None


def plan_depth(cat, per_combo=5, seed=SEED):
    """Up to `per_combo` segments per (sample, native volume, cross volume), seeded choice."""
    import numpy as np
    rng = np.random.default_rng(seed)
    combos = {}
    for sid, s in sorted(cat["samples"].items()):
        for gid, g in sorted((s.get("segments") or {}).items()):
            sv, _ = segment_entries(g)
            vols = {_volume_id_in(p.split("/")[-1]) for p in sv}
            nat = g.get("original_volume_id")
            if nat not in vols:
                continue
            for v in sorted(vols - {nat, None}):
                combos.setdefault((sid, nat, v), []).append(gid)
    plan = []
    for key in sorted(combos):
        gids = combos[key]
        pick = sorted(rng.choice(gids, size=min(per_combo, len(gids)), replace=False).tolist())
        plan.append({"sample": key[0], "native_volume": key[1], "cross_volume": key[2],
                     "segments_available": len(gids), "segments": pick})
    return plan


# ---------------------------------------------------------------- H4: how were cross meshes made?

def grid_normals(xyz):
    """Unit normals of a (H, W, 3) vertex grid (NaN where undefined)."""
    import numpy as np
    du = np.gradient(xyz, axis=1)
    dv = np.gradient(xyz, axis=0)
    n = np.cross(du, dv)
    with np.errstate(invalid="ignore", divide="ignore"):
        return n / np.linalg.norm(n, axis=-1, keepdims=True)


def affine_residuals(ref_xyz, cross_xyz, matrix, px_cross_um, search=4, max_points=20000, seed=SEED):
    """Send reference-mesh vertices through `matrix` and measure, against the nearest published
    cross-mesh vertex near the proportionally scaled grid position, the normal and tangential
    distances in micrometres of the cross volume."""
    import numpy as np
    H, W, _ = ref_xyz.shape
    Hc, Wc, _ = cross_xyz.shape
    ky = (Hc - 1) / max(H - 1, 1)
    kx = (Wc - 1) / max(W - 1, 1)
    ok = np.isfinite(ref_xyz).all(axis=-1)
    rr, cc = np.nonzero(ok)
    if rr.size == 0:
        return {"points": 0}
    if rr.size > max_points:
        pick = np.random.default_rng(seed).choice(rr.size, max_points, replace=False)
        rr, cc = rr[pick], cc[pick]
    p = apply_affine(matrix, ref_xyz[rr, cc])
    nc = grid_normals(cross_xyz)
    best_d = np.full(rr.size, np.inf)
    best_q = np.full((rr.size, 3), np.nan)
    best_n = np.full((rr.size, 3), np.nan)
    r0 = np.rint(rr * ky).astype(int)
    c0 = np.rint(cc * kx).astype(int)
    for dr in range(-search, search + 1):
        for dc in range(-search, search + 1):
            r = np.clip(r0 + dr, 0, Hc - 1)
            c = np.clip(c0 + dc, 0, Wc - 1)
            q = cross_xyz[r, c]
            d = np.linalg.norm(p - q, axis=1)
            d = np.where(np.isfinite(d), d, np.inf)
            better = d < best_d
            best_d[better] = d[better]
            best_q[better] = q[better]
            best_n[better] = nc[r, c][better]
    found = np.isfinite(best_d) & np.isfinite(best_n).all(axis=1)
    out = {"points": int(rr.size), "matched": int(found.sum())}
    if not found.any():
        return out
    v = p[found] - best_q[found]
    normal = np.abs((v * best_n[found]).sum(axis=1)) * px_cross_um
    total = np.linalg.norm(v, axis=1) * px_cross_um
    tang = np.sqrt(np.maximum(total ** 2 - normal ** 2, 0))
    for name, a in (("normal", normal), ("tangential", tang)):
        out[name + "_median_um"] = float(np.median(a))
        out[name + "_p90_um"] = float(np.percentile(a, 90))
        out[name + "_max_um"] = float(a.max())
    out["frac_normal_over_25um"] = float(np.mean(normal > TIERS_UM[0]))
    out["frac_normal_over_75um"] = float(np.mean(normal > TIERS_UM[1]))
    return out


def read_tifxyz(base_path, fetch=None):
    """(H, W, 3) float64 vertices in x, y, z order, NaN for holes (-1 or non-finite)."""
    import io
    import numpy as np
    import tifffile
    fetch = fetch or _get
    arrs = []
    for a in ("x", "y", "z"):
        arrs.append(tifffile.imread(io.BytesIO(fetch("%s/%s.tif" % (base_path, a)))).astype(np.float64))
    xyz = np.stack(arrs, axis=-1)
    bad = (xyz == -1).any(axis=-1) | ~np.isfinite(xyz).all(axis=-1)
    xyz[bad] = np.nan
    return xyz


def sample_matrix(cat, sample_id, a, b):
    """The catalogue's sample-level matrix from volume a to volume b, or None."""
    props = (cat["samples"][sample_id].get("sample") or {}).get("properties") or {}
    for e in props.get("volume_transforms") or []:
        if e.get("from_volume_id") == a:
            for t in e.get("transforms", []):
                if t.get("to_volume_id") == b:
                    return t["matrix"], t.get("derivation_path")
    return None, None


# ---------------------------------------------------------------- H5: in-plane shift between renders

def area_resample_1d(a, in_px, out_px, n_out, start_um, axis):
    """Average `a` along `axis` over output bins of out_px um starting at start_um (input pixel
    i covers [i*in_px, (i+1)*in_px) um)."""
    import numpy as np
    a = np.moveaxis(np.asarray(a, float), axis, 0)
    cs = np.concatenate([np.zeros((1,) + a.shape[1:]), np.cumsum(a, axis=0)], axis=0)
    edges_in = np.arange(cs.shape[0]) * in_px
    edges = start_um + np.arange(n_out + 1) * out_px
    flat = cs.reshape(cs.shape[0], -1)
    vals = np.stack([np.interp(edges, edges_in, flat[:, k]) for k in range(flat.shape[1])], axis=1)
    out = (vals[1:] - vals[:-1]) / (out_px / in_px)
    return np.moveaxis(out.reshape((n_out,) + a.shape[1:]), 0, axis)


def phase_shift(a, b, exclude=5):
    """Translation s (rows, cols) in pixels with b(x) ~= a(x - s), and the peak-to-sidelobe ratio."""
    import numpy as np
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa = np.fft.fft2((a - a.mean()) * win)
    fb = np.fft.fft2((b - b.mean()) * win)
    r = fb * np.conj(fa)
    r /= np.maximum(np.abs(r), 1e-12)
    c = np.real(np.fft.ifft2(r))
    i, j = np.unravel_index(int(np.argmax(c)), c.shape)
    h, w = c.shape

    def sub(m1, m0, p1):
        den = m1 - 2 * m0 + p1
        return 0.5 * (m1 - p1) / den if den != 0 else 0.0

    di = sub(c[(i - 1) % h, j], c[i, j], c[(i + 1) % h, j])
    dj = sub(c[i, (j - 1) % w], c[i, j], c[i, (j + 1) % w])
    si = i + di if i <= h // 2 else i + di - h
    sj = j + dj if j <= w // 2 else j + dj - w
    mask = np.ones_like(c, bool)
    for y in range(i - exclude, i + exclude + 1):
        for x in range(j - exclude, j + exclude + 1):
            mask[y % h, x % w] = False
    side = c[mask]
    psr = float((c[i, j] - side.mean()) / (side.std() + 1e-12))
    return (float(si), float(sj)), psr


def centre_patch(sv, u, v, size_mm=3.0, out_um=10.0):
    """Centre layer of a surface volume over a size_mm square at normalized (u, v), area-averaged
    to out_um pixels. None where under half the window is valid."""
    import numpy as np
    k = min((i for i in range(len(sv.levels)) if sv.levels[i]["scale_um"][1] <= out_um),
            key=lambda i: out_um - sv.levels[i]["scale_um"][1], default=0)
    lv = sv.levels[k]
    _, H, W = lv["zarray"]["shape"]
    px = lv["scale_um"][1]
    n = int(round(size_mm * 1000.0 / out_um))
    half_um = n * out_um / 2.0
    # centre from the full-resolution canvas: coarser levels round their sizes up
    _, H0, W0 = sv.levels[0]["zarray"]["shape"]
    px0 = sv.levels[0]["scale_um"][1]
    rc, cc = v * H0 * px0, u * W0 * px0
    r0 = int(np.floor((rc - half_um) / px)) - 1
    c0 = int(np.floor((cc - half_um) / px)) - 1
    r1 = int(np.ceil((rc + half_um) / px)) + 1
    c1 = int(np.ceil((cc + half_um) / px)) + 1
    if r0 < 0 or c0 < 0 or r1 > H or c1 > W:
        return None
    L = lv["zarray"]["shape"][0]
    blk = sv.read_layer(k, L // 2, r0, r1, c0, c1).astype(float)
    if (blk > 0).mean() < 0.5:
        return None
    out = area_resample_1d(blk, px, out_um, n, rc - half_um - r0 * px, 0)
    out = area_resample_1d(out, px, out_um, n, cc - half_um - c0 * px, 1)
    return out


def predicted_shift_um(ref_xyz, u, v, stored_ref_to_cross, true_cross_to_ref, px_ref_um):
    """Tangential (rows, cols) shift in um of the content a cross render shows at canvas (u, v),
    if the cross mesh was made with `stored_ref_to_cross` but `true_cross_to_ref` is correct."""
    import numpy as np
    H, W, _ = ref_xyz.shape
    r, c = int(round(v * (H - 1))), int(round(u * (W - 1)))
    p = ref_xyz[r, c]
    if not np.isfinite(p).all():
        return None
    d = apply_affine(true_cross_to_ref, apply_affine(stored_ref_to_cross, p[None]))[0] - p
    tv = ref_xyz[min(r + 1, H - 1), c] - ref_xyz[max(r - 1, 0), c]
    tu = ref_xyz[r, min(c + 1, W - 1)] - ref_xyz[r, max(c - 1, 0)]
    if not (np.isfinite(tv).all() and np.isfinite(tu).all()):
        return None
    tv /= np.linalg.norm(tv)
    tu /= np.linalg.norm(tu)
    return float(d @ tv * px_ref_um), float(d @ tu * px_ref_um), float(np.linalg.norm(d) * px_ref_um)
