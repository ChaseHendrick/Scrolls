"""Cross-validated training of the center network and the umbilicus files it writes.

    python pipeline.py job JOB --data DIR --out DIR [--size 256 --width 32 --epochs 40 --time-s 900 --device cuda]
    python pipeline.py collect --data DIR --out DIR [--vc3d-name]
    python pipeline.py trim SRC --data DIR --out DST [--vc3d-name]   # drop end points from umbilicus JSONs already written

JOB is fold<k>s<seed> (k = 0..3) or alls<seed>. A fold job trains on the labeled scrolls outside
that fold and predicts the fold's scrolls (scored, never seen in training) and any scrolls in slices.UNLABELLED.
collect averages the seeds per fold for the held-out score. For each scroll in slices.UNLABELLED, if any,
it takes the median of every model and writes an umbilicus JSON in the format of the published ones (control points
in level-0 voxels) to OUT/umbilicus/.

Umbilicus files (umbilicus_json, write_umbilicus) are named <scroll>_umbilicus.json, or with --vc3d-name
<scroll>/umbilicus.json, the name VC3D searches for first and spiral-fitting reads. Their metadata carries the scan's
level-0 width, height and slice count (all three or none), which VC3D uses to place the points on the volume it has
open. Both follow villa main 8aa507c12: volume-cartographer/core/src/ScrollUmbilicus.cpp:74-75 (file names) and
317-341 (rescale by the stamped grid), core/src/Umbilicus.cpp:272-426 (what VC3D accepts), apps/src/vc_gen_umbilicus.cpp:
224-226 and 510-520 (villa's own writer of the triplet), spiral-fitting/fit_session.py:362-365 (umbilicus.json).
"""
import argparse, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slices

# Folds by scroll, fixed on 13 Oct 2026 before the two training runs. Each mixes 8.64 and 9.362 um scans and both annotators.
FOLDS = [["PHerc0125", "PHerc0268", "PHerc1203"],
         ["PHerc0211", "PHerc0800", "PHerc0191", "PHerc1545"],
         ["PHerc0826", "PHerc1218", "PHerc0257"],
         ["PHerc1447", "PHerc0358", "PHerc0813"]]
assert sorted(sum(FOLDS, [])) == sorted(slices.LABELLED)

JOBS = [f"fold{k}s{s}" for k in range(len(FOLDS)) for s in (0, 1)] + ["alls0"]   # what a full run writes

def read_json(path):
    with open(path) as fh:
        return json.load(fh)

def write_json(obj, path, **kw):
    with open(path, "w") as fh:
        json.dump(obj, fh, **kw)

# The file name VC3D looks for first in each folder it searches (then estimated_umbilicus.json), and the one
# spiral-fitting's dataset folder must hold: villa main 8aa507c12, volume-cartographer/core/src/ScrollUmbilicus.cpp:74-75
# and spiral-fitting/fit_session.py:362-365.
VC3D_NAME = "umbilicus.json"
SUFFIX = "_umbilicus.json"            # this finder's default name, <scroll>_umbilicus.json, as the published files
DIMS = ("volume_width", "volume_height", "volume_slices")    # Umbilicus.cpp:385-387; x, y and z of the grid

def umbilicus_path(out, s, vc3d=False):
    """OUT/<s>_umbilicus.json (the default), or with vc3d OUT/<s>/umbilicus.json: one folder per scroll holding the
    name VC3D and spiral-fitting look for."""
    return os.path.join(out, s, VC3D_NAME) if vc3d else os.path.join(out, s + SUFFIX)

def write_umbilicus(j, out, s, vc3d=False):
    """Write an umbilicus file where umbilicus_path says and return its path. Strict JSON (no NaN), which VC3D's
    parser needs. Under the VC3D name a line with no points is not written, since VC3D refuses such a file
    (Umbilicus.cpp:327-329) and would stop at it: a file there from an earlier run is removed, and None is returned."""
    p = umbilicus_path(out, s, vc3d)
    if vc3d and not j["control_points"]:
        if os.path.exists(p):
            os.remove(p)
        print(f"{s}: no control points kept, so no {p} written (VC3D refuses an umbilicus file without points)",
              file=sys.stderr)
        return None
    text = json.dumps(j, indent=1, allow_nan=False)      # before any file is touched, so a refusal leaves none
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as fh:
        fh.write(text)
    os.replace(p + ".tmp", p)
    return p

def umbilicus_files(src):
    """[(scroll, path, vc3d)] for the umbilicus files in folder src, in both layouts: SRC/<s>_umbilicus.json and
    SRC/<s>/umbilicus.json. A scroll in both layouts is refused, since either could be meant."""
    found = {}
    for f in sorted(os.listdir(src)):
        p = os.path.join(src, f)
        if f.endswith(SUFFIX) and os.path.isfile(p):
            s, vc3d = f[:-len(SUFFIX)], False
        elif os.path.isfile(os.path.join(p, VC3D_NAME)):
            s, vc3d, p = f, True, os.path.join(p, VC3D_NAME)
        else:
            continue
        if s in found:
            raise SystemExit(f"{src}: {s} has both {s}{SUFFIX} and {s}/{VC3D_NAME}; keep one")
        found[s] = (s, p, vc3d)
    return [found[s] for s in sorted(found)]

def _rescales(fine, coarse, level):
    """True when each coarse count is floor or ceil of the fine count over 2**level: the only counts an integer
    downsampling gives, the test VC3D's uniformRescaleFactor applies (ScrollUmbilicus.cpp:273-291)."""
    f = 2 ** int(level)
    return len(fine) == len(coarse) and all(int(c) in (int(a) // f, -(-int(a) // f)) for a, c in zip(fine, coarse))

def slice_volume(data, expected, name):
    """Refuse a missing or different cache source before using its slices or dimensions for a line."""
    held = str(data["vol"]).rstrip("/") if "vol" in data.files else ""
    if not held:
        raise SystemExit(f"{name}: slice file has no source volume; rebuild it with slices.py extract")
    if expected and held != str(expected).rstrip("/"):
        raise SystemExit(f"{name}: slice file holds {held}, not {expected}: use another --data folder")
    return held

def volume_dims(vol, held=None, planes=None, level=3):
    """{volume_width, volume_height, volume_slices} of a scan's level-0 grid, for an umbilicus file's metadata, or {}.

    The grid is `held` (a slice file's shape_l0, [z, y, x]) when given, else the scan's level-0 .zarray in the bucket.
    `planes` (the (H, W) of a slice file's level-`level` planes) must be that grid downsampled 2**level times, or the
    shape belongs to another scan and nothing is stamped. {} (with the reason on stderr) when the grid cannot be read:
    the file then carries no triplet, never part of one (Umbilicus.cpp:389-421 refuses a partial triplet), and VC3D
    falls back to the voxel size (ScrollUmbilicus.cpp:348-358)."""
    why = None
    if held is not None:
        shape = [int(v) for v in np.asarray(held).ravel()]
    else:
        try:
            shape = slices.level0_shape(vol)
        except (RuntimeError, ValueError, OSError) as e:
            shape, why = None, f"its level-0 .zarray could not be read ({e})"
        if shape is None and why is None:
            why = "the bucket has no level-0 .zarray at that path"
    if shape is not None and not (len(shape) == 3 and all(v > 0 for v in shape)):
        shape, why = None, f"level-0 shape {shape} is not three positive integers"
    if shape is not None and planes is not None and not _rescales(shape[1:], list(planes), level):
        shape, why = None, (f"level-0 shape {shape} does not downsample to the slice file's level-{level} planes "
                            f"{list(planes)}")
    if shape is None:
        print(f"{vol}: no volume_width, volume_height or volume_slices stamped: {why}", file=sys.stderr)
        return {}
    z, y, x = shape
    return dict(volume_width=x, volume_height=y, volume_slices=z)

def stamp_dims(meta, dims, name):
    """Put dims (volume_dims's answer) into an umbilicus file's metadata in place. An existing complete triplet must
    equal dims; with dims empty it is kept. A partial triplet, which VC3D refuses, is replaced by dims or refused."""
    have = [k for k in DIMS if k in meta]
    if have and len(have) == 3 and dims and any(meta[k] != dims[k] for k in DIMS):
        raise SystemExit(f"{name}: its volume dimensions {[meta[k] for k in DIMS]} are not the scan's "
                         f"{[dims[k] for k in DIMS]}; the file is in another frame")
    if have and len(have) < 3 and not dims:
        raise SystemExit(f"{name}: metadata has {', '.join(have)} without the rest of volume_width, volume_height, "
                         "volume_slices, which VC3D refuses, and the scan's level-0 shape could not be read")
    meta.update(dims)
    return meta

def parse_job(job):
    """fold2s1 -> (2, 1); alls0 -> (None, 0)."""
    import re
    m = re.fullmatch(r"(fold(\d)|all)s(\d+)", job)
    if not m:
        raise SystemExit(f"bad job {job!r}: use fold<k>s<seed> or alls<seed>")
    return (int(m.group(2)) if m.group(2) else None), int(m.group(3))

def load_all(data, size, scrolls):
    import centrenet
    out = {}
    for s in scrolls:
        imgs, fr = centrenet.frame(os.path.join(data, f"{s}.npz"), size)
        t = centrenet.truth_net(s, fr) if s in slices.LABELLED else None
        out[s] = (imgs, t, fr)
    return out

def run_job(job, data, out, size=256, width=32, epochs=40, time_s=900, device="cpu", batch=32):
    import torch, centrenet
    k, seed = parse_job(job)
    test = FOLDS[k] if k is not None else []
    train = [s for s in slices.LABELLED if s not in test]
    D = load_all(data, size, slices.LABELLED + slices.UNLABELLED)
    log = lambda m: print(f"[{job}] {m}", flush=True)
    net, info = centrenet.train({s: (D[s][0], D[s][1]) for s in train}, epochs, seed, width=width, batch=batch,
                                time_s=time_s, device=device, log=log)
    os.makedirs(out, exist_ok=True)
    torch.save(net.state_dict(), os.path.join(out, f"{job}.pt"))
    preds = {}
    for s in test + slices.UNLABELLED + ([] if test else slices.LABELLED):
        P, C = centrenet.predict(net, D[s][0], device=device)
        L0 = centrenet.Frame.net_to_l0(P.astype(float), D[s][2])
        preds[s] = dict(z=D[s][2]["z_l0"].tolist(), yx=L0.round(2).tolist(), peak=C.round(4).tolist(),
                        present=D[s][2]["present"].tolist(), held_out=s in test, um=D[s][2]["um"], vol=D[s][2]["vol"])
    rec = dict(job=job, fold=k, seed=seed, train=train, test=test, size=size, width=width, epochs=epochs,
               batch=batch, time_s=time_s, device=device, train_info=info, preds=preds)
    if str(device).startswith("cuda"):     # mps or cpu: no CUDA name to record
        rec["gpu"] = torch.cuda.get_device_name(torch.device(device))
    write_json(rec, os.path.join(out, f"{job}.json"))
    log(f"done {info}")
    return rec

def _err_mm(yx, z, s, um):
    _, T = slices.truth(s)
    ok = (np.asarray(z) >= T[0, 0]) & (np.asarray(z) <= T[-1, 0])
    ty, tx = np.interp(z, T[:, 0], T[:, 1]), np.interp(z, T[:, 0], T[:, 2])
    e = np.hypot(yx[:, 0] - ty, yx[:, 1] - tx) * um / 1000
    return e[ok]

def _stats(e):
    return dict(n=int(len(e)), median_mm=round(float(np.median(e)), 3), p90_mm=round(float(np.percentile(e, 90)), 3),
                within_1mm=round(float((e <= 1).mean()), 3), within_2mm=round(float((e <= 2).mean()), 3))

def centroid_baseline(data, s):
    """Control: center of the papyrus area in each slice, the obvious automatic answer."""
    from scipy import ndimage as ndi
    d = np.load(os.path.join(data, f"{s}.npz")); ct = d["ct"]; f = 2 ** (int(d["level"]) if "level" in d.files else 3)
    P = []
    for im in ct:
        m = ndi.binary_fill_holes(ndi.gaussian_filter(im.astype(np.float32), 2) > 5)
        ys, xs = np.nonzero(m); P.append([ys.mean() * f, xs.mean() * f] if len(ys) else [np.nan, np.nan])
    return np.array(P), d["z_l0"]

# Which slices get a center in a written file. Both ends of every scan hold the mount (a thin strip) and caps, and
# the hand-placed lines skip them, so the network is never trained or scored there. Rule (13 Oct 2026, from the 13
# published scrolls only): drop 3 mm at each end of the slices with any papyrus, drop slices whose filled papyrus area
# is under 30 % of the scroll's median, and keep the longest unbroken run. On the published scrolls it keeps 96 to
# 100 % of each annotated band and a few slices beside it (51 on PHerc0268, whose line starts 41 mm into the body).
CAP_MM, AREA_FRAC = 3.0, 0.3

def papyrus_area(ct):
    """Filled papyrus area per slice (pixels at half the slice resolution), the centroid baseline's mask."""
    from scipy import ndimage as ndi
    return np.array([ndi.binary_fill_holes(ndi.gaussian_filter(im[::2, ::2].astype(np.float32), 1) > 5).sum()
                     for im in ct], float)

def keep_band(area, z, um, cap_mm=None, frac=None):
    """True on the longest unbroken run of slices that have at least frac of the median papyrus area and lie at least
    cap_mm inside the first and last slices with papyrus. Defaults: CAP_MM and AREA_FRAC, read when called."""
    cap_mm = CAP_MM if cap_mm is None else cap_mm; frac = AREA_FRAC if frac is None else frac
    area = np.asarray(area, float); z = np.asarray(z, float); pres = area > 0
    out = np.zeros(len(area), bool)
    if not pres.any():
        return out
    zp = z[pres]; c = cap_mm * 1000 / um
    k = pres & (area >= frac * np.median(area[pres])) & (z >= zp[0] + c) & (z <= zp[-1] - c)
    best, st = (0, 0, 0), None
    for i, v in enumerate(list(k) + [False]):
        if v and st is None:
            st = i
        elif not v and st is not None:
            best = max(best, (i - st, st, i)); st = None
    out[best[1]:best[2]] = True
    return out

# End-point rule (14 Oct 2026): keep_band can still keep heights near either end where the center sits in air, beside
# a broken end or inside a hollow one, because it looks at the papyrus area of the whole slice, not at the center.
# This rule looks at the center: cast END_RAYS rays from it in the level-3 slice and count the share that meet papyrus
# (CT at or above Otsu's air/papyrus level) within END_RADIUS_MM. Points are dropped from each end of the kept band
# inward until END_RUN_MM of consecutive slices reach END_SUPPORT; nothing between the first and last such run is
# ever dropped, so the rule cannot punch holes in the middle of a line. END_SUPPORT (three quarters of directions) and
# END_RUN_MM were set by meaning; END_RADIUS_MM is the smallest of 2, 3, 4, 5 mm at which, on the 13 published
# scrolls, at most 0.5 % of published centers in the middle 80 % of each annotated band fall under the bar (0.18 %
# at 4 mm, 1.2 % at 3 mm). Fixed on the 13 published scrolls only (endcheck.py calibrate).
END_RADIUS_MM, END_SUPPORT, END_RUN_MM, END_RAYS = 4.0, 0.75, 2.0, 32

def papyrus_level(ct):
    """Air/papyrus intensity level of a uint8 slice stack: Otsu's threshold over its nonzero voxels (zero is the
    volume mask). Returns an int; a voxel counts as papyrus at or above it."""
    h = np.bincount(np.asarray(ct, np.uint8).ravel(), minlength=256)[:256].astype(float)
    h[0] = 0
    if h.sum() == 0:
        return 256
    v = np.arange(256, dtype=float); w = np.cumsum(h); m = np.cumsum(h * v); tot_w, tot_m = w[-1], m[-1]
    w0, w1 = w[:-1], tot_w - w[:-1]
    ok = (w0 > 0) & (w1 > 0)
    between = np.zeros(255)
    between[ok] = (tot_m * w0[ok] / tot_w - m[:-1][ok]) ** 2 / (w0[ok] * w1[ok])   # Otsu's between-class variance
    return int(np.argmax(between)) + 1          # classes 0..t-1 and t..255

def end_support(ct, yx, um, level_thr, level=3, origin=None, radius_mm=None, rays=None):
    """Share of `rays` directions from each slice's center that meet papyrus within radius_mm.

    ct: (n, H, W) uint8 slices at pyramid level `level` (whole slices, or crops whose top-left corner in level
    pixels is origin[i]); yx: (n, 2) centers in level-0 voxels (a NaN center gives 0); level_thr from papyrus_level.
    The slice is smoothed with a 3x3 mean first, so a single bright voxel in air does not count as papyrus; samples
    off the slice count as air. Defaults: END_RADIUS_MM and END_RAYS, read when called."""
    radius_mm = END_RADIUS_MM if radius_mm is None else radius_mm; rays = END_RAYS if rays is None else rays
    ct = np.asarray(ct); yx = np.asarray(yx, float); n, H, W = ct.shape
    f = 2 ** level; rmax = radius_mm * 1000 / (um * f)
    r = np.arange(0.0, rmax + 1e-9, 0.5); a = 2 * np.pi * np.arange(rays) / rays
    dy, dx = np.sin(a)[:, None] * r[None], np.cos(a)[:, None] * r[None]
    org = np.zeros((n, 2)) if origin is None else np.asarray(origin, float)
    out = np.zeros(n)
    for i in range(n):
        if not np.isfinite(yx[i]).all():
            continue
        im = ct[i].astype(np.float32); p = np.pad(im, 1, mode="edge")
        sm = sum(p[1 + u:1 + u + H, 1 + v:1 + v + W] for u in (-1, 0, 1) for v in (-1, 0, 1)) / 9
        cy, cx = yx[i] / f - org[i]
        yi, xi = np.rint(cy + dy).astype(int), np.rint(cx + dx).astype(int)
        inside = (yi >= 0) & (yi < H) & (xi >= 0) & (xi < W)
        val = np.zeros(yi.shape, np.float32)
        val[inside] = sm[yi[inside], xi[inside]]
        out[i] = float((val >= level_thr).any(1).mean())
    return out

def trim_ends(keep, support, z, um, min_support=None, run_mm=None):
    """Drop kept slices at either end until run_mm of consecutive kept slices all have support >= min_support.
    Slices between the first and the last such run stay as they were. All False if no run qualifies.
    Defaults: END_SUPPORT and END_RUN_MM, read when called."""
    min_support = END_SUPPORT if min_support is None else min_support; run_mm = END_RUN_MM if run_mm is None else run_mm
    keep = np.asarray(keep, bool).copy(); support = np.asarray(support, float); z = np.asarray(z, float)
    idx = np.nonzero(keep)[0]
    if not len(idx):
        return keep
    dz = float(np.median(np.diff(z))) if len(z) > 1 else 64.0
    m = max(1, int(np.ceil(run_mm * 1000 / um / dz - 1e-9)))
    ok = support[idx] >= min_support
    runs = [p for p in range(len(idx) - m + 1) if ok[p:p + m].all()]
    if not runs:
        keep[:] = False
        return keep
    keep[:idx[runs[0]]] = False; keep[idx[runs[-1] + m - 1] + 1:] = False
    return keep

def window_origins(yx, um, level=3, half_mm=None):
    """Top-left corners (level pixels) and half side h of the windows the rule reads: 2h x 2h around each center.
    Rows whose center is NaN get (0, 0). Default half_mm: END_RADIUS_MM + 0.5, read when called."""
    half_mm = END_RADIUS_MM + 0.5 if half_mm is None else half_mm
    yx = np.asarray(yx, float); f = 2 ** level
    h = int(np.ceil(half_mm * 1000 / (um * f)))
    org = np.zeros((len(yx), 2), int); ok = np.isfinite(yx).all(1)
    org[ok] = np.rint(yx[ok] / f).astype(int) - h
    return org, h

def centre_windows(ct, yx, um, level=3):
    """The rule's windows cut from whole slices (zeros off the slice), with their origins."""
    ct = np.asarray(ct); n, H, W = ct.shape
    org, h = window_origins(yx, um, level)
    out = np.zeros((n, 2 * h, 2 * h), ct.dtype)
    for i, (y0, x0) in enumerate(org):
        if not np.isfinite(yx[i]).all():
            continue
        ys, xs, ye, xe = max(y0, 0), max(x0, 0), min(y0 + 2 * h, H), min(x0 + 2 * h, W)
        if ye > ys and xe > xs:
            out[i, ys - y0:ye - y0, xs - x0:xe - x0] = ct[i, ys:ye, xs:xe]
    return out, org

def end_trimmed_keep(ct, yx, z, um, keep, level=3):
    """keep after the end-point rule, with the per-slice support and the papyrus level used. The level is Otsu's
    over the windows of the kept slices, so whole slices and windows read straight from the bucket
    (endcheck.py) give the same answer."""
    w, org = centre_windows(ct, yx, um, level)
    return apply_end_rule(w, org, yx, z, um, keep, level)

def apply_end_rule(windows, origin, yx, z, um, keep, level=3):
    keep = np.asarray(keep, bool)
    thr = papyrus_level(windows[keep]) if keep.any() else 256
    sup = end_support(windows, yx, um, thr, level=level, origin=origin)
    return trim_ends(keep, sup, z, um), sup, thr

def _trim_note(end_rule=True):
    t = (f"mount and cap slices dropped: kept the longest run with at least {AREA_FRAC:g} of the median papyrus area, "
         f"at least {CAP_MM:g} mm inside the first and last slices with papyrus")
    if end_rule:
        t += (f"; end-point rule: dropped from each end until {END_RUN_MM:g} mm of slices where at least {END_SUPPORT:g} of "
              f"{END_RAYS} rays from the center meet papyrus within {END_RADIUS_MM:g} mm")
    return t

def trim(src, data, dst, end_rule=True, vc3d_name=False):
    """Drop the end-band points from umbilicus JSONs already written (umbilicus_files(src) -> dst, each under its own
    layout's name, or under SCROLL/umbilicus.json with vc3d_name): keep_band, then (end_rule) the end-point rule at the
    file's own centers, which must sit at the slice file's heights (a file written by this pipeline; for others use
    endcheck.py files without --data). The scan's level-0 width, height and slice count are stamped (stamp_dims)."""
    os.makedirs(dst, exist_ok=True); out = {}
    for s, f, vc3d in umbilicus_files(src):
        with open(f) as fh:
            j = json.load(fh)
        d = np.load(os.path.join(data, f"{s}.npz")); um = float(d["um"]); z = np.asarray(d["z_l0"]); ct = d["ct"]
        level = int(d["level"]) if "level" in d.files else 3
        vol = slice_volume(d, j.get("metadata", {}).get("source_volume"), f)
        j.setdefault("metadata", {})
        stamp_dims(j["metadata"], volume_dims(vol, d["shape_l0"] if "shape_l0" in d.files else None, ct.shape[1:], level), f)
        keep = keep_band(papyrus_area(ct), z, um)
        if end_rule:          # the file's own centers, at the slice heights they were written for
            P = sorted(j["control_points"], key=lambda p: p["z"]); yx = np.full((len(z), 2), np.nan)
            at = {int(v): i for i, v in enumerate(z)}
            off = [p["z"] for p in P if int(p["z"]) not in at]
            if off:
                raise SystemExit(f"{s}: {len(off)} control points are not at the slice file's heights (first z {off[0]}); "
                                 "use endcheck.py files without --data, or trim --no-end-rule")
            for p in P:
                yx[at[int(p["z"])]] = (p["y"], p["x"])
            keep = keep & np.isfinite(yx[:, 0])
            keep, _, _ = end_trimmed_keep(ct, yx, z, um, keep, level=level)
        zk = z[keep]
        cp = [p for p in j["control_points"] if len(zk) and zk[0] <= p["z"] <= zk[-1]]
        j["control_points"] = cp; j["metadata"]["total_points"] = len(cp)
        j["metadata"]["trimmed"] = _trim_note(end_rule)
        p = write_umbilicus(j, dst, s, vc3d or vc3d_name)
        out[s] = dict(points=len(cp), z=[int(zk[0]), int(zk[-1])] if len(zk) else None, file=p)
    return out

def umbilicus_json(s, z, yx, keep, um, vol, spread, note, dims=None):
    """The published umbilicus format: control points x, y, z in level-0 voxels, and metadata. dims: volume_dims's
    {volume_width, volume_height, volume_slices} of the scan's level-0 grid, stamped as VC3D reads them."""
    vol = str(vol).rstrip("/")         # metadata.volume must not be empty (Umbilicus.cpp:360-366)
    pts = [dict(x=int(round(x)), y=int(round(y)), z=int(zz), score=100) for zz, (y, x), k in zip(z, yx, keep) if k]
    med = float(np.nanmedian(spread[keep])) if keep.any() and spread is not None and np.isfinite(spread[keep]).any() else None
    if dims and (set(dims) != set(DIMS) or not all(int(v) > 0 for v in dims.values())):
        raise ValueError(f"dims must hold all of {DIMS} as positive integers, got {dims}")   # all three or none
    meta = dict(source_volume=vol, volume=vol.split("/")[-1], voxelsize_um=float(um))
    meta.update({k: int(dims[k]) for k in DIMS} if dims else {})
    meta.update(total_points=len(pts), created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), method=note,
                spread_mm_median=None if med is None else round(med, 3))
    return dict(control_points=pts, metadata=meta)

def collect(data, out, vc3d_name=False):
    import centrenet
    recs = [read_json(os.path.join(out, f)) for f in sorted(os.listdir(out)) if f.endswith(".json") and f[:3] in ("fol", "all")]
    res = dict(held_out={}, centroid={}, jobs=[{k: r[k] for k in ("job", "train_info", "size", "width", "epochs", "test")} | {"gpu": r.get("gpu")} for r in recs])
    allE, allB, allEs = [], [], []
    for s in slices.LABELLED:
        rs = [r for r in recs if r["test"] and s in r["test"]]
        if not rs: continue
        z = np.array(rs[0]["preds"][s]["z"]); um = rs[0]["preds"][s]["um"]
        yx = np.mean([np.array(r["preds"][s]["yx"]) for r in rs], 0)
        e = _err_mm(yx, z, s, um); es = _err_mm(centrenet.smooth_z(yx), z, s, um)
        P, zb = centroid_baseline(data, s); b = _err_mm(centrenet.smooth_z(P), zb, s, um)
        _, T = slices.truth(s); kb = keep_band(papyrus_area(np.load(os.path.join(data, f"{s}.npz"))["ct"]), z, um)
        res["held_out"][s] = dict(raw=_stats(e), smoothed=_stats(es), models=len(rs), kept=int(kb.sum()),
                                  kept_unscored=int((kb & ((z < T[0, 0]) | (z > T[-1, 0]))).sum()))
        res["centroid"][s] = _stats(b)
        allE += list(e); allEs += list(es); allB += list(b)
    if allE:
        res["held_out_all"] = dict(raw=_stats(np.array(allE)), smoothed=_stats(np.array(allEs)), centroid=_stats(np.array(allB)))
    # a partial run must not read as a full 13-scroll score
    found = {r["job"] for r in recs}
    missing_scrolls = [s for s in slices.LABELLED if s not in res["held_out"]]
    res.setdefault("held_out_all", {})
    res["held_out_all"].update(
        scrolls=len(res["held_out"]), missing_scrolls=missing_scrolls, missing_jobs=sorted(set(JOBS) - found),
        centroid_beaten=sum(res["held_out"][s]["smoothed"]["median_mm"] < res["centroid"][s]["median_mm"] for s in res["held_out"]),
        complete=not missing_scrolls and not (set(JOBS) - found) and all(v["models"] == 2 for v in res["held_out"].values()))
    if slices.UNLABELLED:
        res["unlabelled"] = {}
        os.makedirs(os.path.join(out, "umbilicus"), exist_ok=True)
    for s in slices.UNLABELLED:
        rs = [r for r in recs if s in r["preds"]]
        if not rs: continue
        p0 = rs[0]["preds"][s]; z = np.array(p0["z"]); um = p0["um"]; present = np.array(p0["present"])
        Y = np.array([r["preds"][s]["yx"] for r in rs])            # models x slices x 2
        yx = np.median(Y, 0)
        spread = np.median(np.hypot(*(Y - yx[None]).transpose(2, 0, 1)), 0) * um / 1000 if len(rs) > 1 else None
        sm = centrenet.smooth_z(np.where(present[:, None], yx, np.nan))
        d = np.load(os.path.join(data, f"{s}.npz")); ct = d["ct"]; level = int(d["level"]) if "level" in d.files else 3
        slice_volume(d, p0["vol"], s)
        keep = present & keep_band(papyrus_area(ct), z, um)   # no mount or caps
        keep, _, _ = end_trimmed_keep(ct, sm, z, um, keep, level=level)
        dims = volume_dims(p0["vol"], d["shape_l0"] if "shape_l0" in d.files else None, ct.shape[1:], level)
        j = umbilicus_json(s, z, sm, keep, um, p0["vol"], spread,
                           f"automatic: median of {len(rs)} center-network models, smoothed along z (scripts/umbilicus); {_trim_note()}",
                           dims)
        f = write_umbilicus(j, os.path.join(out, "umbilicus"), s, vc3d_name)
        res["unlabelled"][s] = dict(points=j["metadata"]["total_points"], models=len(rs), spread_mm_median=j["metadata"]["spread_mm_median"],
                                 file=f,
                                 spread_mm_p90=round(float(np.percentile(spread[keep], 90)), 3) if keep.any() and spread is not None else None,
                                 peak_median=round(float(np.median(np.mean([r["preds"][s]["peak"] for r in rs], 0)[keep])), 3))
    write_json(res, os.path.join(out, "result.json"), indent=1)
    return res

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["job", "collect", "trim"]); ap.add_argument("job", nargs="?")
    ap.add_argument("--data", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=256); ap.add_argument("--width", type=int, default=32)
    ap.add_argument("--epochs", type=int, default=40); ap.add_argument("--time-s", type=float, default=900)
    ap.add_argument("--batch", type=int, default=32); ap.add_argument("--device", default="cpu")
    ap.add_argument("--no-end-rule", action="store_true", help="trim: mount and caps only, without the end-point rule")
    ap.add_argument("--vc3d-name", action="store_true",
                    help="collect, trim: write SCROLL/umbilicus.json, the name VC3D and spiral-fitting look for, "
                         "instead of SCROLL_umbilicus.json")
    a = ap.parse_args()
    if a.cmd == "job":
        run_job(a.job, a.data, a.out, a.size, a.width, a.epochs, a.time_s, a.device, a.batch)
    elif a.cmd == "collect":
        print(json.dumps(collect(a.data, a.out, vc3d_name=a.vc3d_name), indent=1))
    elif a.cmd == "trim":                  # pipeline.py trim SRC_DIR --data NPZ_DIR --out DST_DIR [--no-end-rule] [--vc3d-name]
        print(json.dumps(trim(a.job, a.data, a.out, end_rule=not a.no_end_rule, vc3d_name=a.vc3d_name), indent=1))
