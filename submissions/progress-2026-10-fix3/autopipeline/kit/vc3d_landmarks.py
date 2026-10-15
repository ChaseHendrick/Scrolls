"""Do the open-data catalog's cross-scan transforms agree with their own landmarks?

The catalog (kit/vc3d_catalog.py) gives, per volume, affine transforms to other scans of the same sample: a
3 x 4 matrix taking voxel (x, y, z) of the source volume to voxel (x, y, z) of the target, with the landmark
pairs behind it (`from_landmarks`, `to_landmarks`, in the same voxels). Per sample it also lists a matrix for
every ordered pair of volumes with the path it was derived by (a stored transform, its inverse, a chain).
VC3D shows segments in another scan's frame with that table, and kit's `render` takes such a matrix as
`affine`. A wrong matrix puts a surface beside its sheet in the other scan, and nothing reports it.

Per transform, in micrometres of the target scan:

- how far the stored matrix misses its own landmarks, and whether it is their least-squares affine fit (a
  refit that fits far better means the matrix was not made from these landmarks);
- leave-one-out errors: each landmark predicted by a fit to the others. A fit always matches the points it
  was made from (four points fit an affine exactly), so this is the honest error between landmarks;
- the same for a similarity (rotation, one scale, translation; mirrored when the matrix is), which has 7
  parameters instead of 12 and holds up better on few or flat landmark sets;
- the landmark set's spread along its principal axes: an affine fitted to nearly flat landmarks is free to
  tilt across the thin direction;
- the matrix's scales against the ratio of the voxel sizes, its anisotropy and its handedness. A negative
  determinant means the two frames are mirror images: a surface's normal flips between them, so its layer
  order has to be decided in the frame it is rendered in;
- at given points (a segment's place), the jackknife spread of the mapped position: how firmly the landmarks
  pin the transform down there, chained across the hops of a derived pair;
- per sample, whether every derived matrix equals the composition of the stored ones its path names.

Verdicts follow fixed rules with a tolerance (default 75 um, half the about 0.15 mm thickness of a
carbonized sheet; docs/papyrus/README.md). They are checks that can fail, not judgements of any scan.
Standard library.
"""

import hashlib
import json
import math

TOLERANCE_UM = 75.0
FLAT = 0.1            # smallest over largest principal spread of the landmarks below this: nearly flat
SCALE_NOTE = 0.01     # the matrix's scale off the voxel-size ratio, or its axes off each other, by over 1 %
DERIVED_UM = 1.0      # a derived matrix this far from its path's composition anywhere in the volume: a defect
INVERSE = "⁻¹"
VERDICTS = ("inconsistent", "weak", "consistent", "unchecked")


class LandmarkError(ValueError):
    pass


# ---------------------------------------------------------------- 3 x 4 affines (rows x, y, z)

def as_matrix(m):
    rows = [[float(v) for v in r] for r in (m or [])[:3]]
    if len(rows) != 3 or any(len(r) != 4 for r in rows):
        raise LandmarkError("a transform is 3 rows of 4 numbers (x, y, z rows)")
    return rows


def apply(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))


def det3(a):
    return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))


def inv3(a):
    d = det3(a)
    if d == 0 or not math.isfinite(d):
        return None
    return [[(a[(j + 1) % 3][(i + 1) % 3] * a[(j + 2) % 3][(i + 2) % 3]
              - a[(j + 1) % 3][(i + 2) % 3] * a[(j + 2) % 3][(i + 1) % 3]) / d for j in range(3)] for i in range(3)]


def invert(m):
    inv = inv3([r[:3] for r in m])
    if inv is None:
        raise LandmarkError("the matrix is singular")
    return [inv[i] + [-sum(inv[i][k] * m[k][3] for k in range(3))] for i in range(3)]


def compose(second, first):
    """The affine that applies `first`, then `second`."""
    return [[sum(second[i][k] * first[k][j] for k in range(3)) for j in range(3)]
            + [sum(second[i][k] * first[k][3] for k in range(3)) + second[i][3]] for i in range(3)]


def eig_sym(s, sweeps=60):
    """(eigenvalues, eigenvectors as columns) of a small symmetric matrix by Jacobi rotations, largest first."""
    n = len(s)
    a = [[float(v) for v in r] for r in s]
    v = [[float(i == j) for j in range(n)] for i in range(n)]
    for _ in range(sweeps):
        off = sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        if off <= 1e-30 * max(sum(a[i][i] ** 2 for i in range(n)), 1e-300):
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if a[p][q] == 0.0:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                sn = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - sn * akq, sn * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - sn * aqk, sn * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - sn * vkq, sn * vkp + c * vkq
    order = sorted(range(n), key=lambda i: -a[i][i])
    return [a[i][i] for i in order], [[v[k][i] for i in order] for k in range(n)]


def _mean(points):
    n = len(points)
    return [sum(p[i] for p in points) / n for i in range(3)]


def _cross_cov(src, dst, cs, cd):
    """S[a][b] = sum over points of (src_a - cs_a) * (dst_b - cd_b)."""
    return [[sum((s[a] - cs[a]) * (d[b] - cd[b]) for s, d in zip(src, dst)) for b in range(3)] for a in range(3)]


def fit_affine(src, dst):
    """Least-squares affine taking src to dst ([(x, y, z)] each), or None when the points do not fix one
    (fewer than four, or all in one plane)."""
    if len(src) < 4 or len(src) != len(dst):
        return None
    cs, cd = _mean(src), _mean(dst)
    sxx = _cross_cov(src, src, cs, cs)
    vals, _ = eig_sym(sxx)
    if vals[-1] <= 1e-12 * max(vals[0], 1e-300):
        return None
    inv = inv3(sxx)
    if inv is None:
        return None
    sxd = _cross_cov(src, dst, cs, cd)
    a = [[sum(sxd[k][i] * inv[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return [a[i] + [cd[i] - sum(a[i][k] * cs[k] for k in range(3))] for i in range(3)]


def _quat_rotation(w, x, y, z):
    return [[w * w + x * x - y * y - z * z, 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (y * x + w * z), w * w - x * x + y * y - z * z, 2 * (y * z - w * x)],
            [2 * (z * x - w * y), 2 * (z * y + w * x), w * w - x * x - y * y + z * z]]


def fit_similarity(src, dst, mirror=False):
    """Least-squares rotation, one scale and translation taking src to dst (Horn's unit quaternions, with the
    scale fitted to dst); with mirror, after flipping x of src, so the result has a negative determinant.
    None when the points do not fix one (fewer than three, or all at one place)."""
    if len(src) < 3 or len(src) != len(dst):
        return None
    flip = -1.0 if mirror else 1.0
    s2 = [(flip * p[0], p[1], p[2]) for p in src]
    cs, cd = _mean(s2), _mean(dst)
    ss = sum((p[i] - cs[i]) ** 2 for p in s2 for i in range(3))
    if ss <= 0:
        return None
    S = _cross_cov(s2, dst, cs, cd)
    (sxx, sxy, sxz), (syx, syy, syz), (szx, szy, szz) = S
    N = [[sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
         [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
         [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
         [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz]]
    _, vecs = eig_sym(N)
    q = [vecs[k][0] for k in range(4)]
    norm = math.sqrt(sum(v * v for v in q)) or 1.0
    r = _quat_rotation(*(v / norm for v in q))
    scale = sum(sum((d[i] - cd[i]) * sum(r[i][k] * (s[k] - cs[k]) for k in range(3)) for i in range(3))
                for s, d in zip(s2, dst)) / ss
    a = [[scale * r[i][0] * flip, scale * r[i][1], scale * r[i][2]] for i in range(3)]
    c0 = _mean(src)
    return [a[i] + [cd[i] - sum(a[i][k] * c0[k] for k in range(3))] for i in range(3)]


def decompose(m):
    """Scales (singular values, largest first), determinant, mean scale, anisotropy and the rotation angle of the
    matrix's linear part (after undoing a mirror in x, when it has one)."""
    a = [r[:3] for r in m]
    ata = [[sum(a[k][i] * a[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    vals, vecs = eig_sym(ata)
    sv = [math.sqrt(max(v, 0.0)) for v in vals]
    d = det3(a)
    out = {"scales": sv, "det": d, "mirror": d < 0, "mean_scale": abs(d) ** (1 / 3),
           "anisotropy": (sv[0] / sv[-1] - 1) if sv[-1] > 0 else None, "rotation_deg": None}
    if sv[-1] > 0:
        isq = [[sum(vecs[i][k] * vecs[j][k] / sv[k] for k in range(3)) for j in range(3)] for i in range(3)]
        rot = [[sum(a[i][k] * isq[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        if d < 0:
            rot = [[-row[0], row[1], row[2]] for row in rot]
        cos = max(-1.0, min(1.0, (rot[0][0] + rot[1][1] + rot[2][2] - 1) / 2))
        out["rotation_deg"] = math.degrees(math.acos(cos))
    return out


# ---------------------------------------------------------------- landmark statistics

def residuals(m, src, dst):
    """Distance from each mapped landmark to its partner, in target voxels."""
    return [math.dist(apply(m, s), d) for s, d in zip(src, dst)]


def leave_one_out(fit, src, dst):
    """Each landmark's distance from where a fit to the others puts it, in target voxels (None where the others
    cannot fix a fit)."""
    out = []
    for i in range(len(src)):
        m = fit(src[:i] + src[i + 1:], dst[:i] + dst[i + 1:])
        out.append(math.dist(apply(m, src[i]), dst[i]) if m is not None else None)
    return out


def jackknife(fit, src, dst, points):
    """Jackknife standard error of the mapped position of each point, in target voxels: how much the mapping
    there moves when one landmark is left out. None when a fit without one landmark is not possible."""
    n = len(src)
    fits = [fit(src[:i] + src[i + 1:], dst[:i] + dst[i + 1:]) for i in range(n)]
    if n < 2 or any(f is None for f in fits):
        return [None for _ in points]
    out = []
    for p in points:
        maps = [apply(f, p) for f in fits]
        c = _mean(maps)
        out.append(math.sqrt((n - 1) / n * sum(math.dist(q, c) ** 2 for q in maps)))
    return out


def spread(points):
    """Standard deviations of the points along their principal axes, largest first."""
    c = _mean(points)
    cov = [[sum((p[i] - c[i]) * (p[j] - c[j]) for p in points) / len(points) for j in range(3)] for i in range(3)]
    vals, _ = eig_sym(cov)
    return [math.sqrt(max(v, 0.0)) for v in vals]


def _stats(values, unit):
    vals = [v * unit for v in values if v is not None]
    if not vals:
        return None
    vals.sort()
    mid = len(vals) // 2
    median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return {"median_um": round(median, 2), "max_um": round(vals[-1], 2),
            "rms_um": round(math.sqrt(sum(v * v for v in vals) / len(vals)), 2)}


def _box(points):
    return [[min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]]


def _corners(box):
    (x0, y0, z0), (x1, y1, z1) = box
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def max_difference(m1, m2, box):
    """Largest distance between where two affines put the corners of a box (so anywhere inside it)."""
    return max(math.dist(apply(m1, p), apply(m2, p)) for p in _corners(box))


def _r(v, nd=2):
    return None if v is None else round(v, nd)


def _pts(raw, what):
    try:
        pts = [tuple(float(v) for v in p) for p in (raw or [])]
    except (TypeError, ValueError) as exc:
        raise LandmarkError(f"{what}: not a list of [x, y, z] points") from exc
    if any(len(p) != 3 for p in pts):
        raise LandmarkError(f"{what}: every point is [x, y, z]")
    return pts


# ---------------------------------------------------------------- one transform

def check_transform(t, from_um=None, to_um=None, tolerance_um=TOLERANCE_UM, at=None, max_listed=50):
    """Report on one stored transform: {"transformation_matrix", "from_landmarks", "to_landmarks",
    "to_volume_id"} as the catalog has it. Distances are in micrometres of the target scan when to_um is
    known, otherwise in its voxels (and the report says so)."""
    m = as_matrix(t.get("transformation_matrix") or t.get("matrix"))
    src, dst = _pts(t.get("from_landmarks"), "from_landmarks"), _pts(t.get("to_landmarks"), "to_landmarks")
    if len(src) != len(dst):
        raise LandmarkError(f"{len(src)} from_landmarks but {len(dst)} to_landmarks")
    unit = float(to_um) if to_um else 1.0
    tol = float(tolerance_um)
    n = len(src)
    dec = decompose(m)
    rep = {"landmarks": n, "from_um": from_um, "to_um": to_um, "units": "um" if to_um else "target voxels"}
    mat = {"scales": [round(v, 5) for v in dec["scales"]], "mirror": dec["mirror"],
           "anisotropy_pct": _r(dec["anisotropy"] * 100 if dec["anisotropy"] is not None else None),
           "rotation_deg": _r(dec["rotation_deg"])}
    ratio = from_um / to_um if from_um and to_um else None
    if ratio:
        mat["voxel_ratio"] = round(ratio, 5)
        mat["scale_vs_voxel_ratio_pct"] = round((dec["mean_scale"] / ratio - 1) * 100, 2)
    rep["matrix"] = mat
    flags = {}
    if dec["mirror"]:
        flags["mirror"] = ("the matrix's determinant is negative, so the two frames are mirror images; a surface's "
                           "normal flips between them, so decide its layer order in the frame it is rendered in "
                           "(render's orientation check does, with an umbilicus in that frame)")
    if ratio and abs(dec["mean_scale"] / ratio - 1) > SCALE_NOTE:
        flags["scale"] = (f"the matrix scales by {dec['mean_scale']:.5g}, {mat['scale_vs_voxel_ratio_pct']:+.2f}% "
                          f"off the voxel-size ratio {ratio:.5g} (a nominal voxel size may be off, or the fit)")
    if dec["anisotropy"] is not None and dec["anisotropy"] > SCALE_NOTE:
        flags["anisotropy"] = (f"the matrix stretches one direction {mat['anisotropy_pct']}% more than another; two "
                               "scans of one rigid object differ by a rotation and one scale")
    if n == 0:
        rep.update(verdict="unchecked", reason="no landmarks: nothing to check the matrix against here", flags=flags)
        return rep
    stored = residuals(m, src, dst)
    rep["stored"] = {**_stats(stored, unit), "per_landmark": [round(v * unit, 2) for v in stored[:max_listed]]}
    aff = fit_affine(src, dst)
    box = _box(src)
    if aff is not None:
        fit_res = residuals(aff, src, dst)
        rep["affine_refit"] = {**_stats(fit_res, unit), "differs_from_stored_um": round(
            max_difference(aff, m, box) * unit, 2), "matrix": [[round(v, 9) for v in r] for r in aff]}
    sim = fit_similarity(src, dst, mirror=dec["mirror"])
    if sim is not None:
        rep["similarity_refit"] = {**_stats(residuals(sim, src, dst), unit),
                                   "scale": round(decompose(sim)["mean_scale"], 6),
                                   "matrix": [[round(v, 9) for v in r] for r in sim]}
    loo_aff = leave_one_out(fit_affine, src, dst) if n >= 5 else None
    if loo_aff and any(v is not None for v in loo_aff):
        rep["leave_one_out_affine"] = {**_stats(loo_aff, unit),
                                       "per_landmark": [_r(v * unit if v is not None else None)
                                                        for v in loo_aff[:max_listed]]}
    sim_fit = (lambda s, d: fit_similarity(s, d, mirror=dec["mirror"]))
    loo_sim = leave_one_out(sim_fit, src, dst) if n >= 4 else None
    if loo_sim and any(v is not None for v in loo_sim):
        rep["leave_one_out_similarity"] = {**_stats(loo_sim, unit),
                                           "per_landmark": [_r(v * unit if v is not None else None)
                                                            for v in loo_sim[:max_listed]]}
    sd = spread(src)
    fu = float(from_um) if from_um else 1.0
    rep["geometry"] = {"spread_um" if from_um else "spread_voxels": [round(v * fu, 1) for v in sd],
                       "flatness": round(sd[-1] / sd[0], 4) if sd[0] > 0 else None,
                       "box_from_voxels": [[round(v, 1) for v in c] for c in box]}
    if sd[0] > 0 and sd[-1] / sd[0] < FLAT:
        flags["flat"] = (f"the landmarks spread {sd[-1] * fu:.0f} along their thinnest direction against "
                         f"{sd[0] * fu:.0f} along their widest ({'um' if from_um else 'voxels'}), so an affine is "
                         "free to tilt across that direction; check the error where you need it (at)")

    stored_max = max(stored) * unit
    verdict, why = "consistent", None
    if n < 4:
        verdict, why = "unchecked", f"{n} landmarks cannot fix an affine (it takes 4 not in one plane)"
    elif aff is None:
        verdict, why = "unchecked", "the landmarks lie in one plane, so they do not fix an affine"
    elif stored_max > tol:
        refit_max = max(fit_res) * unit
        if refit_max <= tol:
            verdict, why = "inconsistent", (
                f"the matrix misses its own landmarks by up to {stored_max:.1f} um while an affine refit fits them "
                f"within {refit_max:.1f} um: it was not made from these landmarks (or they changed); "
                "affine_refit.matrix is the fit")
        else:
            verdict, why = "inconsistent", (
                f"no affine fits these landmarks within {tol:g} um (the refit misses one by {refit_max:.1f} um): "
                "a landmark may be misplaced (see the leave-one-out errors), or the scans differ by more than an "
                "affine")
    elif n == 4:
        verdict, why = "weak", "4 landmarks fit any affine exactly, so their residual is no evidence"
        if rep.get("leave_one_out_similarity"):
            why += (f"; held out from a similarity fit they miss by up to "
                    f"{rep['leave_one_out_similarity']['max_um']} um")
    elif rep.get("leave_one_out_affine") and rep["leave_one_out_affine"]["max_um"] > tol:
        lo = rep["leave_one_out_affine"]
        verdict, why = "weak", (f"a landmark left out is predicted up to {lo['max_um']} um off (median "
                                f"{lo['median_um']}): between landmarks the matrix may be that far out")
    la, ls = rep.get("leave_one_out_affine"), rep.get("leave_one_out_similarity")
    if la and ls and ls["max_um"] <= tol < la["max_um"]:
        flags["similarity"] = (f"a similarity fit predicts left-out landmarks within {ls['max_um']} um (the affine: "
                               f"{la['max_um']} um); the affine's extra freedom fits noise here. "
                               "similarity_refit.matrix can be given to render as affine")
    if aff is not None and verdict != "inconsistent" and rep["affine_refit"]["differs_from_stored_um"] > max(unit, 1.0):
        flags["not_lsq"] = (f"the matrix and an affine refit of its landmarks differ by up to "
                            f"{rep['affine_refit']['differs_from_stored_um']} um across the landmarks' box")
    rep["verdict"] = verdict
    rep["reason"] = why
    rep["flags"] = flags
    if at:
        rep["at"] = error_at(m, src, dst, at, from_um, to_um, mirror=dec["mirror"])
    return rep


def error_at(m, src, dst, points, from_um=None, to_um=None, mirror=False, max_listed=50):
    """How firmly the landmarks pin the transform down at given points of the source frame: per point the mapped
    position, the jackknife spread of an affine and of a similarity fit (target um), the distance to the
    nearest landmark (source um) and whether it lies inside the landmarks' box; with a summary."""
    pts = _pts(points, "at")
    tu, fu = float(to_um or 1.0), float(from_um or 1.0)
    ja = jackknife(fit_affine, src, dst, pts) if len(src) >= 5 else [None] * len(pts)
    js = jackknife(lambda s, d: fit_similarity(s, d, mirror=mirror), src, dst, pts) if len(src) >= 4 \
        else [None] * len(pts)
    box = _box(src) if src else None
    rows = []
    for p, a, s in zip(pts, ja, js):
        rows.append({"point": [round(v, 2) for v in p], "mapped": [round(v, 2) for v in apply(m, p)],
                     "jackknife_affine_um": _r(a * tu if a is not None else None),
                     "jackknife_similarity_um": _r(s * tu if s is not None else None),
                     "nearest_landmark_um": _r(min(math.dist(p, q) for q in src) * fu) if src else None,
                     "inside_landmark_box": bool(box) and all(box[0][i] <= p[i] <= box[1][i] for i in range(3))})
    out = {"points": len(rows), "rows": rows[:max_listed]}
    for key in ("jackknife_affine_um", "jackknife_similarity_um", "nearest_landmark_um"):
        vals = sorted(r[key] for r in rows if r[key] is not None)
        if vals:
            out[key.replace("_um", "_max_um")] = vals[-1]
            out[key.replace("_um", "_median_um")] = vals[len(vals) // 2]
    out["inside_landmark_box_share"] = round(sum(r["inside_landmark_box"] for r in rows) / len(rows), 3) \
        if rows else None
    return out


# ---------------------------------------------------------------- the catalog

def _sample_entry(cat, sample):
    samples = cat.get("samples", {})
    if sample in samples:
        return sample, samples[sample]
    lower = {k.lower(): k for k in samples}
    if sample.lower() in lower:
        return lower[sample.lower()], samples[lower[sample.lower()]]
    raise LandmarkError(f"no sample {sample!r} in the catalog")


def volume_info(sample_entry, vid):
    props = ((sample_entry.get("volumes") or {}).get(vid) or {}).get("properties") or {}
    return props.get("pixel_size_um"), props.get("shape")


def stored_transforms(cat, sample=None):
    """[(sample, from volume, transform)] for every transform stored on a volume of the catalog."""
    names = [sample] if sample else sorted(cat.get("samples", {}))
    out = []
    for name in names:
        sid, s = _sample_entry(cat, name)
        for vid, vol in sorted((s.get("volumes") or {}).items()):
            for t in ((vol.get("properties") or {}).get("transforms") or []):
                out.append((sid, vid, t))
    return out


def parse_path(path):
    """[(from, to, inverted)] for a derivation path such as 'A-B' or 'A-B⁻¹.B-C⁻¹'. Each hop
    goes from one volume to the next; an inverted hop uses the inverse of the transform stored the other way."""
    hops = []
    for hop in str(path or "").split("."):
        inverted = hop.endswith(INVERSE)
        a, sep, b = (hop[:-len(INVERSE)] if inverted else hop).partition("-")
        if not sep or not a or not b:
            raise LandmarkError(f"derivation path {path!r}: hop {hop!r} is not FROM-TO")
        hops.append((a, b, inverted))
    return hops


def _stored_map(cat, sid):
    return {(vid, t.get("to_volume_id")): t for s2, vid, t in stored_transforms(cat, sid)}


def derived_table(cat, sample):
    """Every matrix in the sample's volume_transforms table against the composition of the stored transforms
    its derivation path names. Returns [{from, to, path, max_difference_um, ok, problem?}]."""
    sid, s = _sample_entry(cat, sample)
    stored = _stored_map(cat, sid)
    rows = []
    for group in (((s.get("sample") or {}).get("properties") or {}).get("volume_transforms") or []):
        a = group.get("from_volume_id")
        for t in group.get("transforms") or []:
            b, path = t.get("to_volume_id"), t.get("derivation_path")
            row = {"from": a, "to": b, "path": path}
            try:
                given = as_matrix(t.get("matrix") or t.get("transformation_matrix"))
                hops = parse_path(path)
                if hops[0][0] != a or hops[-1][1] != b or any(h[1] != k[0] for h, k in zip(hops, hops[1:])):
                    raise LandmarkError(f"path {path!r} does not lead from {a} to {b}")
                comp = None
                for x, y, inverted in hops:
                    key = (y, x) if inverted else (x, y)
                    if key not in stored:
                        raise LandmarkError(f"path {path!r} names {key[0]} to {key[1]}, which no volume stores")
                    hm = as_matrix(stored[key].get("transformation_matrix"))
                    hm = invert(hm) if inverted else hm
                    comp = hm if comp is None else compose(hm, comp)
            except LandmarkError as exc:
                rows.append({**row, "ok": False, "problem": str(exc)})
                continue
            shape = volume_info(s, a)[1]
            to_um = volume_info(s, b)[0] or 1.0
            far = [float(shape[2]), float(shape[1]), float(shape[0])] if shape and len(shape) == 3 else [1.0e4] * 3
            box = [[0.0, 0.0, 0.0], far]
            diff = max_difference(given, comp, box) * to_um
            row.update(max_difference_um=round(diff, 4), ok=diff <= DERIVED_UM)
            if not row["ok"]:
                row["problem"] = (f"differs from the composition of its path by up to {diff:.3g} um inside the "
                                  f"source volume")
            rows.append(row)
    return rows


def path_between(cat, sample, from_volume, to_volume):
    """The derivation path the sample's table gives for from_volume to to_volume, or None."""
    sid, s = _sample_entry(cat, sample)
    for group in (((s.get("sample") or {}).get("properties") or {}).get("volume_transforms") or []):
        if group.get("from_volume_id") != from_volume:
            continue
        for t in group.get("transforms") or []:
            if t.get("to_volume_id") == to_volume:
                return t.get("derivation_path")
    return None


def error_along(cat, sample, from_volume, to_volume, points):
    """error_at for a pair of volumes the table connects, hop by hop: each point is carried through the path,
    each hop's jackknife spread is taken where the point is on that hop (inverted hops fit the landmarks the
    other way), and the spreads add in quadrature (they are in micrometres, which the hops preserve)."""
    sid, s = _sample_entry(cat, sample)
    path = path_between(cat, sid, from_volume, to_volume)
    if path is None:
        stored = _stored_map(cat, sid)
        if (from_volume, to_volume) not in stored:
            raise LandmarkError(f"{sid} has no transform from {from_volume} to {to_volume}")
        path = f"{from_volume}-{to_volume}"
    stored = _stored_map(cat, sid)
    pts = _pts(points, "at")
    cur = list(pts)
    hops_out, total_a, total_s = [], [0.0] * len(pts), [0.0] * len(pts)
    known_a, known_s = [True] * len(pts), [True] * len(pts)
    for x, y, inverted in parse_path(path):
        key = (y, x) if inverted else (x, y)
        if key not in stored:
            raise LandmarkError(f"path {path!r} names {key[0]} to {key[1]}, which no volume stores")
        t = stored[key]
        m = as_matrix(t.get("transformation_matrix"))
        src, dst = _pts(t.get("from_landmarks"), "from_landmarks"), _pts(t.get("to_landmarks"), "to_landmarks")
        if inverted:
            m, src, dst = invert(m), dst, src
        fu, tu = volume_info(s, x)[0], volume_info(s, y)[0]
        if src:
            rep = error_at(m, src, dst, cur, fu, tu, mirror=det3([r[:3] for r in m]) < 0, max_listed=len(cur))
        else:
            rep = {"points": len(cur), "rows": [{"jackknife_affine_um": None, "jackknife_similarity_um": None}
                                                for _ in cur], "note": "no landmarks on this hop"}
        for i, r in enumerate(rep["rows"]):
            for key2, total, known in (("jackknife_affine_um", total_a, known_a),
                                       ("jackknife_similarity_um", total_s, known_s)):
                if r.get(key2) is None:
                    known[i] = False
                else:
                    total[i] += r[key2] ** 2
        hops_out.append({"from": x, "to": y, "inverted": inverted, "landmarks": len(src),
                         **{k: v for k, v in rep.items() if k != "rows"}})
        cur = [apply(m, p) for p in cur]
    shape = volume_info(s, to_volume)[1]
    inside = (lambda q: all(0 <= q[i] < shape[2 - i] for i in range(3))) if shape and len(shape) == 3 else \
        (lambda q: None)
    rows = [{"point": [round(v, 2) for v in p], "mapped": [round(v, 2) for v in q],
             "jackknife_affine_um": round(math.sqrt(a), 2) if ka else None,
             "jackknife_similarity_um": round(math.sqrt(b), 2) if kb else None, "inside_target_volume": inside(q)}
            for p, q, a, b, ka, kb in zip(pts, cur, total_a, total_s, known_a, known_s)]
    outside = sum(r["inside_target_volume"] is False for r in rows)
    return {"path": path, "hops": hops_out, "points": len(rows), "rows": rows[:50],
            **({"outside_target_volume": outside} if outside else {}),
            "jackknife_affine_max_um": max((r["jackknife_affine_um"] for r in rows
                                            if r["jackknife_affine_um"] is not None), default=None),
            "jackknife_similarity_max_um": max((r["jackknife_similarity_um"] for r in rows
                                                if r["jackknife_similarity_um"] is not None), default=None)}


def _landmark_key(t):
    blob = json.dumps([t.get("from_landmarks"), t.get("to_landmarks")], sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def check_catalog(cat, sample=None, from_volume=None, to_volume=None, tolerance_um=TOLERANCE_UM):
    """check_transform for every stored transform (of one sample, from or to one volume), with each sample's
    derived table checked and a summary."""
    picked = [(sid, vid, t) for sid, vid, t in stored_transforms(cat, sample)
              if (not from_volume or vid == from_volume) and (not to_volume or t.get("to_volume_id") == to_volume)]
    if not picked:
        raise LandmarkError("no stored transform matches" + (f" in {sample}" if sample else "") +
                            (f" from {from_volume}" if from_volume else "") + (f" to {to_volume}" if to_volume else ""))
    shared = {}
    for sid, vid, t in picked:
        if t.get("from_landmarks"):
            shared.setdefault(_landmark_key(t), []).append(f"{sid} {vid} to {t.get('to_volume_id')}")
    rows = []
    for sid, vid, t in picked:
        _, s = _sample_entry(cat, sid)
        to = t.get("to_volume_id")
        rep = {"sample": sid, "from": vid, "to": to, **check_transform(t, volume_info(s, vid)[0],
                                                                        volume_info(s, to)[0], tolerance_um)}
        twins = [x for x in shared.get(_landmark_key(t), []) if x != f"{sid} {vid} to {to}"] \
            if t.get("from_landmarks") else []
        if twins:
            rep["same_landmarks_as"] = twins
        rows.append(rep)
    derived = {}
    for sid in sorted({r["sample"] for r in rows}):
        table = derived_table(cat, sid)
        derived[sid] = {"entries": len(table), "problems": [r for r in table if not r["ok"]],
                        "max_difference_um": max((r.get("max_difference_um", 0.0) for r in table), default=None)}
    counts = {v: sum(r["verdict"] == v for r in rows) for v in VERDICTS}
    return {"tolerance_um": tolerance_um, "transforms": rows, "counts": counts,
            "mirrored": [f"{r['sample']} {r['from']} to {r['to']}" for r in rows if r["matrix"]["mirror"]],
            "derived": derived}


def summary_row(rep):
    """One line's worth of a transform report, for listings."""
    def get(*keys):
        cur = rep
        for k in keys:
            cur = cur.get(k) if isinstance(cur, dict) else None
        return cur
    return {"sample": rep.get("sample"), "from": rep.get("from"), "to": rep.get("to"),
            "landmarks": rep["landmarks"], "verdict": rep["verdict"],
            "stored_max_um": get("stored", "max_um"), "refit_max_um": get("affine_refit", "max_um"),
            "loo_affine_max_um": get("leave_one_out_affine", "max_um"),
            "loo_similarity_max_um": get("leave_one_out_similarity", "max_um"),
            "flatness": get("geometry", "flatness"), "mirror": rep["matrix"]["mirror"],
            "scale_vs_voxel_ratio_pct": rep["matrix"].get("scale_vs_voxel_ratio_pct"),
            "reason": rep.get("reason"), "flags": sorted(rep.get("flags", {}))}


# ---------------------------------------------------------------- the image check

IMAGE_DEFAULTS = {"work_um": 4.0, "patch": 64, "search": 32, "margin": 0.1, "exclude": 6.0, "min_filled": 0.5}


def image_check(matrix, from_vol, to_vol, points, from_um, to_um, to_points=None, tolerance_um=TOLERANCE_UM,
                work_um=None, patch=None, search=None, margin=None, exclude=None, control=True, progress=None):
    """Does the CT around each point match the CT where the matrix puts it?

    `from_vol` and `to_vol` are kit.vc3d_region.Volume objects; points are level-0 voxels (x, y, z) of the source
    scan. The work happens on the coarser scan's grid at about `work_um` (default 4 um, or its own voxel when
    coarser): a cube of `patch` voxels of the finer scan is resampled through the matrix (trilinear, from the
    pyramid level nearest the work grid) and correlated (NCC) with the coarser scan at every shift up to `search`
    voxels. The peak gives where the CT says the point's content lies, relative to where the matrix puts it
    (`offset_um`, in the target frame). The best correlation farther than `exclude` voxels from the peak is the
    control: a peak less than `margin` above it is ambiguous (layered papyrus looks alike nearby), so no claim is
    made. With `control`, each template is also matched against another point's neighbourhood (pairs swapped):
    those must not match, or the check failed its control. With to_points (the target landmarks), each
    landmark's own error is how far it lies from where the CT puts its partner."""
    import numpy as np
    from . import vc3d_region

    opt = dict(IMAGE_DEFAULTS)
    opt.update({k: v for k, v in {"work_um": work_um, "patch": patch, "search": search, "margin": margin,
                                  "exclude": exclude}.items() if v is not None})
    m = as_matrix(matrix)
    pts = _pts(points, "points")
    tps = _pts(to_points, "to_points") if to_points else None
    coarse_is_to = float(to_um) >= float(from_um)
    C, F = (to_vol, from_vol) if coarse_is_to else (from_vol, to_vol)
    C.voxel_um = C.voxel_um or float(to_um if coarse_is_to else from_um)
    F.voxel_um = F.voxel_um or float(from_um if coarse_is_to else to_um)
    g = np.array(invert(m) if coarse_is_to else m)
    lin = np.array([r[:3] for r in m])
    lc = C.finest_reaching(max(float(opt["work_um"]), C.voxel_um))
    w_um = C.level_um(lc)
    lf = F.coarsest_within(w_um * 1.25)
    P, S = int(opt["patch"]), int(opt["search"])
    half = P // 2
    fac_c = np.array(C.factors[lc][::-1], dtype=float)
    idx = np.indices((P, P, P)).reshape(3, -1).T          # (z, y, x) offsets inside the template
    setup = {"coarse": "to" if coarse_is_to else "from", "work_um": round(w_um, 4), "coarse_level": lc,
             "fine_level": lf, "fine_level_um": round(F.level_um(lf), 4), "patch": P, "search": S,
             "patch_um": round(P * w_um, 1), "search_um": round(S * w_um, 1), "margin": opt["margin"],
             "exclude_voxels": opt["exclude"], "tolerance_um": tolerance_um}

    def template_image(p):
        c0 = apply(m, p) if coarse_is_to else tuple(p)
        ci = np.rint(C.to_level(lc, [c0])[0]).astype(int)                     # x, y, z on the work grid
        box = [[ci[2] - half - S, ci[2] - half + P + S], [ci[1] - half - S, ci[1] - half + P + S],
               [ci[0] - half - S, ci[0] - half + P + S]]
        image = C.read(lc, box)
        cl = ci[None, :] + (idx[:, ::-1] - half)                              # x, y, z of each template voxel
        f0 = C.from_level(lc, cl) @ g[:, :3].T + g[:, 3]                      # in the finer scan, level 0
        tmpl = F.sample(lf, F.to_level(lf, f0)).reshape(P, P, P)
        return tmpl, image

    def judge(tmpl, image):
        filled = min(float((tmpl != 0).mean()), float((image != 0).mean()))
        if filled < opt["min_filled"]:
            return {"verdict": "no_structure", "filled": round(filled, 3)}
        ncc = vc3d_region.ncc_map(tmpl, image.astype(np.float64))
        if ncc is None:
            return {"verdict": "no_structure", "filled": round(filled, 3)}
        best, k, side = vc3d_region.peak(ncc, opt["exclude"])
        d = np.array(k[::-1], dtype=float) - S                                # x, y, z shift on the work grid
        d0 = d / fac_c                                                        # in the coarse scan's level 0
        off_vox = d0 if coarse_is_to else -(lin @ d0)                          # in the target scan's level 0
        off_um = off_vox * float(to_um)
        out = {"ncc_peak": round(best, 4), "ncc_at_matrix": round(float(ncc[S, S, S]), 4),
               "ncc_elsewhere": round(side, 4), "distinct": round(best - side, 4),
               "offset_um": [round(float(v), 1) for v in off_um],
               "offset_norm_um": round(float(np.linalg.norm(off_um)), 1),
               "at_search_edge": bool(np.any(np.abs(d) >= S - 0.5)), "filled": round(filled, 3),
               "_off_vox": off_vox}
        if best - side < opt["margin"]:
            out["verdict"] = "ambiguous"
        elif out["at_search_edge"]:
            out["verdict"] = "beyond_search"
        else:
            out["verdict"] = "matches" if out["offset_norm_um"] <= tolerance_um else "offset"
        return out

    rows, first_t, prev_i, swaps = [], None, None, []
    for k, p in enumerate(pts):
        if progress:
            progress(f"image check {k + 1} of {len(pts)}")
        try:
            tmpl, image = template_image(p)
        except vc3d_region.RegionError as exc:
            rows.append({"point": list(p), "verdict": "unread", "error": str(exc)})
            prev_i = None
            continue
        res = judge(tmpl, image)
        row = {"point": [round(v, 2) for v in p], "mapped": [round(v, 2) for v in apply(m, p)], **res}
        if tps is not None and "_off_vox" in res:
            r = np.array(tps[k]) - np.array(apply(m, p))
            row["landmark_residual_um"] = round(float(np.linalg.norm(r)) * float(to_um), 1)
            row["landmark_error_um"] = round(float(np.linalg.norm(r - res["_off_vox"])) * float(to_um), 1)
        row.pop("_off_vox", None)
        rows.append(row)
        if control:
            if prev_i is not None:
                swaps.append(judge(tmpl, prev_i)["verdict"])
            elif first_t is None:
                first_t = tmpl
            prev_i = image
    if control and first_t is not None and prev_i is not None and len(rows) > 2:
        swaps.append(judge(first_t, prev_i)["verdict"])
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    offs = sorted(r["offset_norm_um"] for r in rows if r["verdict"] == "matches")
    report = {"setup": setup, "points": len(rows), "counts": counts, "rows": rows,
              "median_offset_um_of_matches": offs[len(offs) // 2] if offs else None,
              "chunks_read": {"coarse": C.chunks_read, "fine": F.chunks_read},
              "missing_chunks": {"coarse": C.missing, "fine": F.missing}}
    if control:
        judged = [v for v in swaps if v not in ("no_structure", "unread")]
        bad = sum(v in ("matches", "offset", "beyond_search") for v in judged)
        report["control"] = {"swapped_pairs": len(swaps), "judged": len(judged), "matched": bad,
                             "passed": (bad <= len(judged) // 10) if judged else None}
        if report["control"]["passed"] is False:
            report["warning"] = (f"{bad} of {len(judged)} swapped pairs matched, so a match here does not show "
                                 "that the scans agree")
        elif report["control"]["passed"] is None and any(r["verdict"] == "matches" for r in rows):
            report["warning"] = "no swapped pair could be judged, so the matches have no control"
    if tps is not None:
        errs = sorted(r["landmark_error_um"] for r in rows if r.get("verdict") == "matches"
                      and r.get("landmark_error_um") is not None)
        report["landmark_error_um"] = {"median": errs[len(errs) // 2], "max": errs[-1]} if errs else None
    return report
