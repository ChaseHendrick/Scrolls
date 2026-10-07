"""Experimental, label-free surface consistency checks on existing villa ink maps.

This does no rendering or inference. Accepted patches are geometry suggestions, not
evidence of ink. The merged mesh must be rerendered and checked again.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import shutil

from .hpscore import HIGH_PASS_UM, high_pass, _r
from .verify import VerifyError, _numpy, load_map

KINDS = ("forward", "reverse", "shuffle")
NOTICE = ("Experimental consistency-approved geometry only. The final merged surface "
          "must be rerendered and rechecked before claiming improvement: patch context changes.")


def _positive(value, name, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise VerifyError(f"{name} must be finite")
    if value < 0 or (not allow_zero and value == 0):
        raise VerifyError(f"{name} must be {'nonnegative' if allow_zero else 'positive'}")
    return value


def _hashes(path):
    path = Path(path)
    files = sorted(path.rglob("*")) if path.is_dir() else [path]
    result = {}
    for file in files:
        if file.is_symlink():
            raise VerifyError(f"symlink inputs are not supported: {file}")
        if file.is_file():
            digest = hashlib.sha256()
            with file.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            result[str(file.relative_to(path)) if path.is_dir() else file.name] = digest.hexdigest()
    return result


def _overlap(out, inputs):
    out = Path(out).resolve()
    if out.exists():
        raise VerifyError(f"output already exists: {out}")
    for source in inputs:
        source = Path(source).resolve()
        if out == source or out in source.parents or (source.is_dir() and source in out.parents):
            raise VerifyError(f"input-output overlap: {source} and {out}")
    return out


def _mesh(path):
    np = _numpy()
    import tifffile
    path = Path(path).resolve()
    if not path.is_dir():
        raise VerifyError(f"missing native tifxyz directory: {path}")
    try:
        arrays = [tifffile.imread(path / f"{c}.tif") for c in "xyz"]
        xyz = np.stack(arrays, axis=-1).astype(float)
        meta = json.loads((path / "meta.json").read_text())
        scale = np.asarray(meta["scale"], dtype=float)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VerifyError(f"invalid tifxyz mesh or required meta.json scale in {path}: {exc}") from exc
    if (xyz.ndim != 3 or min(xyz.shape[:2]) < 2 or not np.isfinite(xyz).all() or
            any(not np.issubdtype(a.dtype, np.floating) for a in arrays)):
        raise VerifyError(f"{path}: finite x/y/z 2D grids, at least 2 x 2, are required")
    if scale.shape != (2,) or not np.isfinite(scale).all() or (scale <= 0).any():
        raise VerifyError(f"{path}: meta.json scale must have two positive finite values")
    valid = (xyz >= 0).all(-1) & (xyz.sum(-1) > 0)
    # Native holes use (-1, -1, -1) or the zero triplet. Mixed negatives are malformed.
    holes = (xyz == -1).all(-1) | (xyz == 0).all(-1)
    if not (valid | holes).all() or valid.sum() < 4:
        raise VerifyError(f"{path}: malformed holes or fewer than four valid points")
    # Native meta.json scale is [x, y], while array shapes are [row, col].
    shape = tuple(int(round(n / s)) for n, s in zip(xyz.shape[:2], scale[::-1]))
    return {"path": path, "xyz": xyz, "valid": valid, "scale": scale, "map_shape": shape,
            "dtypes": [a.dtype for a in arrays]}


def _roundoff(mesh):
    np = _numpy()
    ulp = max(float(np.spacing(np.asarray(np.max(np.abs(mesh["xyz"][..., i])), dtype=dtype)))
              for i, dtype in enumerate(mesh["dtypes"]))
    tolerance = max(.001, 2 * math.sqrt(3) * ulp)
    if tolerance > .1:
        raise VerifyError("coordinate precision is inadequate for subvoxel normal-offset checks")
    return tolerance


def _normals(mesh):
    """Native local tangents, with one-sided differences beside holes and edges."""
    np = _numpy()
    xyz, valid = mesh["xyz"], mesh["valid"]
    tangents, supported = [], valid.copy()
    for axis in (0, 1):
        before, after = np.roll(xyz, 1, axis), np.roll(xyz, -1, axis)
        vb, va = np.roll(valid, 1, axis), np.roll(valid, -1, axis)
        edge0 = [slice(None)] * 2
        edge1 = edge0.copy()
        edge0[axis], edge1[axis] = 0, -1
        vb[tuple(edge0)], va[tuple(edge1)] = False, False
        delta = np.where((va & vb)[..., None], after - before,
                         np.where(va[..., None], after - xyz, xyz - before))
        tangents.append(delta)
        supported &= va | vb
    cross = np.cross(tangents[0], tangents[1])
    norm = np.linalg.norm(cross, axis=-1)
    supported &= norm > 1e-8
    normals = np.zeros_like(cross)
    normals[supported] = cross[supported] / norm[supported, None]
    return normals, supported


def _faces(mesh):
    """Oriented native-grid triangle Jacobians, excluding triangles across holes."""
    np = _numpy()
    xyz, valid = mesh["xyz"], mesh["valid"]
    a, b, c, d = xyz[:-1, :-1], xyz[1:, :-1], xyz[:-1, 1:], xyz[1:, 1:]
    cross = np.stack([np.cross(b - a, c - a), np.cross(c - d, b - d)], -2)
    ok = np.stack([valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:],
                   valid[1:, 1:] & valid[:-1, 1:] & valid[1:, :-1]], -1)
    return cross, ok


def _unfolded(base, candidate):
    np = _numpy()
    a, valid = _faces(base)
    b, _ = _faces(candidate)
    return not ((a * b).sum(-1)[valid] <= 1e-12).any()


def _write_mesh(source, destination, xyz):
    import tifffile
    shutil.copytree(source, destination)
    for axis, c in enumerate("xyz"):
        dtype = tifffile.imread(Path(source) / f"{c}.tif").dtype
        # Preserve native coordinate precision and sidecar metadata.
        tifffile.imwrite(destination / f"{c}.tif", xyz[..., axis].astype(dtype))


def _blank_maps():
    return {kind: {"path": None, "model": None, "stride": None} for kind in KINDS}


def _sample_native(array, covered, mesh):
    """Bilinear samples at native vertices on an unrotated villa render canvas.

    vc_render_tifxyz centers the pixel canvas at -(size-1)/2 and QuadSurface
    centers its grid at count/(2*scale). Native vertex coordinates therefore
    map to row/scale_y-.5, col/scale_x-.5 for scale=1, group=0 renders.
    Border vertices outside the pixel canvas have no coverage.
    """
    np = _numpy()
    from scipy.ndimage import map_coordinates
    rows, cols = np.indices(mesh["valid"].shape, dtype=float)
    positions = np.stack([rows / mesh["scale"][1] - .5, cols / mesh["scale"][0] - .5])
    values = map_coordinates(array, positions, order=1, mode="constant", cval=0, prefilter=False)
    weights = map_coordinates(covered.astype(float), positions, order=1, mode="constant", cval=0, prefilter=False)
    return values, weights >= 1 - 1e-6


def prepare(mesh, out_dir, voxel_um, offsets, max_shift_um=50):
    """Write bounded native normal-offset candidates and an unfilled map manifest.

    Offsets are signed volume voxels. Use villa to render and infer the three maps
    for every mesh, including a separate reference trace, then fill the manifest.
    """
    np = _numpy()
    _positive(voxel_um, "voxel_um")
    _positive(max_shift_um, "max_shift_um")
    offsets = list(offsets)
    if not offsets:
        raise VerifyError("at least one nonzero candidate offset is required")
    for offset in offsets:
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
            raise VerifyError("offsets must be finite numbers")
        if offset == 0 or abs(offset) * voxel_um > max_shift_um:
            raise VerifyError("candidate offsets must be nonzero and within max_shift_um")
    if len(set(offsets)) != len(offsets):
        raise VerifyError("duplicate candidate offsets")
    source = _mesh(mesh)
    hashes = _hashes(source["path"])
    out = _overlap(out_dir, [source["path"]])
    normals, supported = _normals(source)
    if supported.sum() < 4:
        raise VerifyError("mesh has too few points with usable local normals")
    _roundoff(source)
    if not _unfolded(source, source):
        raise VerifyError("source mesh has degenerate native-grid triangles")
    prepared = []
    for offset in offsets:
        xyz = source["xyz"].copy()
        xyz[supported] += offset * normals[supported]
        if (xyz[source["valid"]] < 0).any() or (xyz[source["valid"]].sum(-1) <= 0).any():
            raise VerifyError("offset would create negative coordinates or a hole")
        # Check the coordinates as they will actually be stored before writing.
        with np.errstate(over="ignore", invalid="ignore"):
            xyz = np.stack([xyz[..., i].astype(dtype).astype(float)
                            for i, dtype in enumerate(source["dtypes"])], -1)
        if not np.isfinite(xyz).all():
            raise VerifyError("offset exceeds native coordinate precision")
        _geometry(source, dict(source, xyz=xyz), offset, voxel_um, max_shift_um, normals, supported)
        prepared.append(xyz)
    out.mkdir(parents=True)
    baseline = {"mesh": os.path.relpath(source["path"], out), "hashes": hashes, "maps": _blank_maps()}
    manifest = {"schema": 1, "voxel_um": voxel_um, "max_shift_um": max_shift_um,
                "model": None, "stride": None, "baseline": baseline, "reference": None,
                "candidates": [], "notice": NOTICE}
    for i, (offset, xyz) in enumerate(zip(offsets, prepared)):
        dst = out / f"offset-{i:03d}.tifxyz"
        _write_mesh(source["path"], dst, xyz)
        manifest["candidates"].append({"offset_vox": offset, "mesh": dst.name,
                                       "hashes": _hashes(dst), "maps": _blank_maps()})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return manifest


def _path(root, value):
    if not isinstance(value, str) or not value:
        raise VerifyError("manifest needs filled mesh and map paths")
    return (root / value).resolve()


def _record(record, root, model, stride, voxel_um, require_hashes=True):
    np = _numpy()
    from scipy.ndimage import gaussian_filter
    if not isinstance(record, dict):
        raise VerifyError("baseline, separate reference and candidates must be mesh records")
    mesh = _mesh(_path(root, record.get("mesh")))
    hashes = _hashes(mesh["path"])
    expected = record.get("hashes")
    if (require_hashes and not expected) or (expected is not None and expected != hashes):
        raise VerifyError(f"missing or changed mesh file hashes: {mesh['path']}")
    maps, map_hashes, paths, coverage = {}, {}, [], {}
    for kind in KINDS:
        spec = record.get("maps", {}).get(kind)
        if (not isinstance(spec, dict) or spec.get("model") != model or
                type(spec.get("stride")) is not int or spec.get("stride") != stride):
            raise VerifyError(f"{kind}: maps must share the manifest model and stride")
        path = _path(root, spec.get("path"))
        if not path.is_file():
            raise VerifyError(f"missing {kind} map: {path}")
        try:
            array = np.load(path, allow_pickle=False) if path.suffix == ".npy" else load_map(path)
        except (OSError, ValueError) as exc:
            raise VerifyError(f"cannot load {kind} map: {exc}") from exc
        array = np.asarray(array, dtype=float)
        if array.shape != mesh["map_shape"] or not np.isfinite(array).all() or (array < 0).any():
            raise VerifyError(f"{kind}: expected finite nonnegative full-surface map {mesh['map_shape']}")
        covered = array > 0
        hp = high_pass(np, gaussian_filter, array, covered, HIGH_PASS_UM / voxel_um)
        maps[kind], coverage[kind] = _sample_native(hp, covered, mesh)
        paths.append(path)
        map_hashes[kind] = {"path": str(path), "sha256": _hashes(path)[path.name]}
    mesh.update(maps=maps, coverage=coverage, hashes=hashes, map_hashes=map_hashes, inputs=paths)
    return mesh


def _geometry(base, candidate, offset, voxel_um, max_shift_um, normals, supported):
    np = _numpy()
    if (candidate["xyz"].shape != base["xyz"].shape or
            not np.array_equal(candidate["valid"], base["valid"]) or
            not np.array_equal(candidate["scale"], base["scale"])):
        raise VerifyError("candidate must preserve native topology, holes and scale")
    delta = candidate["xyz"] - base["xyz"]
    along = (delta * normals).sum(-1)
    tangent = np.linalg.norm(delta - along[..., None] * normals, axis=-1)
    tolerance = max(_roundoff(base), _roundoff(candidate))
    if (not np.array_equal(candidate["xyz"][~base["valid"]], base["xyz"][~base["valid"]]) or
            (np.linalg.norm(delta[base["valid"]], axis=-1) * voxel_um > max_shift_um + tolerance * voxel_um).any() or
            (tangent[supported] > tolerance).any() or
            (np.abs(along[supported] - offset) > tolerance).any() or
            (np.linalg.norm(delta[base["valid"] & ~supported], axis=-1) > tolerance).any()):
        raise VerifyError("candidate is not the declared bounded normal offset, or changes holes")
    cn, cs = _normals(candidate)
    if (not cs[supported].all() or ((cn * normals).sum(-1)[supported] <= 0).any() or
            not _unfolded(base, candidate)):
        raise VerifyError("candidate folds or degenerates the native grid")


def _correlation(np, a, b, mask, min_points):
    if int(mask.sum()) < min_points:
        return None
    return _r(np, a[mask], b[mask])


def _scores(np, source, reference, ref_index, mask, min_points, displaced):
    """All controls use fixed correspondences and the same subset as the forward map."""
    flat = lambda array: array.ravel()
    sf, rf = source["maps"]["forward"], flat(reference["maps"]["forward"])[ref_index]
    score = _correlation(np, sf, rf, mask, min_points)
    controls = []
    for kind in ("reverse", "shuffle"):
        sc = source["maps"][kind]
        rc = flat(reference["maps"][kind])[ref_index]
        for a, b in ((sc, rc), (sc, rf), (sf, rc)):
            r = _correlation(np, a, b, mask, min_points)
            if r is None:
                return {"r": score, "control_max_abs": None, "reason": "inadequate control points or variation"}
            controls.append(abs(r))
    spatial = []
    for index, valid in displaced:
        ok = mask & valid
        r = _correlation(np, sf, flat(reference["maps"]["forward"])[index], ok, min_points)
        if r is not None:
            spatial.append(abs(r))
    if len(spatial) < 2:
        return {"r": score, "control_max_abs": None, "reason": "inadequate spatially displaced controls"}
    return {"r": score, "control_max_abs": max(controls + spatial),
            "spatial_controls": len(spatial), "reason": None}


def _displacements(np, reference, ref_index, voxel_um):
    """Fixed 1 to 3 mm native-grid displacements without periodic wrapping."""
    xyz, valid = reference["xyz"], reference["valid"]
    rows, cols = np.unravel_index(ref_index, valid.shape)
    result = []
    for axis in (0, 1):
        d = np.linalg.norm(np.diff(xyz, axis=axis), axis=-1)
        pairs = np.take(valid, range(valid.shape[axis] - 1), axis=axis) & np.take(valid, range(1, valid.shape[axis]), axis=axis)
        spacing = float(np.median(d[pairs])) * voxel_um if pairs.any() else 0
        if spacing <= 0:
            continue
        for mm in (1, 2, 3):
            step = max(1, int(round(mm * 1000 / spacing)))
            for sign in (-1, 1):
                rr, cc = rows.copy(), cols.copy()
                if axis == 0:
                    rr += sign * step
                else:
                    cc += sign * step
                inside = (rr >= 0) & (rr < valid.shape[0]) & (cc >= 0) & (cc < valid.shape[1])
                rr, cc = np.clip(rr, 0, valid.shape[0] - 1), np.clip(cc, 0, valid.shape[1] - 1)
                idx = np.ravel_multi_index((rr, cc), valid.shape)
                distance = np.linalg.norm(xyz.reshape(-1, 3)[idx] - xyz.reshape(-1, 3)[ref_index], axis=-1) * voxel_um
                inside &= valid[rr, cc] & reference["coverage"]["forward"][rr, cc]
                inside &= (distance >= 1000 - 1e-6) & (distance <= 3000 + 1e-6)
                result.append((idx, inside))
    return result


def correct(manifest_path, out_dir, region_points=8, min_points=24, min_corr=.5,
            min_gain=.1, control_margin=.1, max_step_vox=1):
    """Select on alternating rows; validate that winner once on held-back rows.

    Weak or uncovered regions are flagged. Only winners passing both subsets and
    every control can modify the new copy. No runner-up is tried after rejection.
    """
    np = _numpy()
    from scipy.spatial import cKDTree
    for name, value in (("region_points", region_points), ("min_points", min_points)):
        if isinstance(value, bool) or not isinstance(value, int) or value < (2 if name == "region_points" else 3):
            raise VerifyError(f"{name} must be an integer of at least {2 if name == 'region_points' else 3}")
    for name, value in (("min_corr", min_corr), ("min_gain", min_gain), ("control_margin", control_margin),
                        ("max_step_vox", max_step_vox)):
        _positive(value, name, allow_zero=name != "max_step_vox")
    if min_corr > 1 or min_gain > 2 or control_margin > 2:
        raise VerifyError("correlation thresholds are outside their possible range")
    manifest_path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise VerifyError(f"cannot read manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise VerifyError("surfacefix manifest schema must be 1")
    voxel_um = _positive(manifest.get("voxel_um"), "voxel_um")
    bound = _positive(manifest.get("max_shift_um"), "max_shift_um")
    model, stride = manifest.get("model"), manifest.get("stride")
    if not isinstance(model, str) or not model.strip() or isinstance(stride, bool) or not isinstance(stride, int) or stride <= 0:
        raise VerifyError("manifest needs a model identifier and positive integer inference stride")
    root = manifest_path.parent
    base = _record(manifest.get("baseline"), root, model, stride, voxel_um)
    reference = _record(manifest.get("reference"), root, model, stride, voxel_um, require_hashes=False)
    if base["path"] == reference["path"] or base["hashes"] == reference["hashes"] or (
            base["xyz"].shape == reference["xyz"].shape and np.array_equal(base["xyz"], reference["xyz"])):
        raise VerifyError("reference must be a separate trace, not a copy of the baseline mesh")
    normals, supported = _normals(base)
    records = manifest.get("candidates")
    if not isinstance(records, list) or not records:
        raise VerifyError("manifest needs bounded offset candidates")
    candidates, offsets = [], []
    for record in records:
        offset = record.get("offset_vox") if isinstance(record, dict) else None
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
            raise VerifyError("candidate offset_vox must be finite")
        if offset == 0 or abs(offset) * voxel_um > bound or offset in offsets:
            raise VerifyError("candidate offsets must be unique, nonzero and within max_shift_um")
        candidate = _record(record, root, model, stride, voxel_um)
        _geometry(base, candidate, offset, voxel_um, bound, normals, supported)
        candidates.append(candidate)
        offsets.append(offset)
    all_meshes = [base, reference] + candidates
    inputs = [manifest_path] + [p for mesh in all_meshes for p in [mesh["path"]] + mesh["inputs"]]
    out = _overlap(out_dir, inputs)
    # Freeze baseline-to-reference matches before inspecting any candidate's map.
    ref_flat = np.flatnonzero(reference["valid"])
    distance, nearest = cKDTree(reference["xyz"].reshape(-1, 3)[ref_flat]).query(base["xyz"].reshape(-1, 3))
    ref_index = ref_flat[nearest].reshape(base["valid"].shape)
    gap_ok = distance.reshape(base["valid"].shape) * voxel_um <= bound
    coverage = base["valid"] & supported & gap_ok
    for mesh in [base] + candidates:
        for kind in KINDS:
            coverage &= mesh["coverage"][kind]
    for kind in KINDS:
        coverage &= reference["coverage"][kind].ravel()[ref_index]
    displaced = _displacements(np, reference, ref_index, voxel_um)
    rows, cols = np.indices(base["valid"].shape)
    region_ids = (rows // region_points) * math.ceil(base["valid"].shape[1] / region_points) + cols // region_points
    choices = np.zeros_like(base["valid"], dtype=float)
    report = {"schema": 1, "experimental": True, "notice": NOTICE, "model": model, "stride": stride,
              "voxel_um": voxel_um, "thresholds": {"region_points": region_points, "min_points": min_points,
              "min_corr": min_corr, "min_gain": min_gain, "control_margin": control_margin,
              "max_step_vox": max_step_vox, "max_shift_um": bound, "high_pass_um": HIGH_PASS_UM,
              "spatial_displacement_um": [1000, 3000],
              "map_sampling": "bilinear at native row/scale_y-.5, col/scale_x-.5",
              "normal_tolerance_vox": max(_roundoff(mesh) for mesh in [base] + candidates)},
              "input_hashes": {str(mesh["path"]): {"mesh": mesh["hashes"], "maps": mesh["map_hashes"]}
                               for mesh in all_meshes}, "manifest_sha256": _hashes(manifest_path)[manifest_path.name],
              "regions": []}
    for region_id in np.unique(region_ids[base["valid"]]):
        area = (region_ids == region_id) & base["valid"]
        rr, cc = np.nonzero(area)
        selection = area & coverage & (rows % 2 == 0)
        held_back = area & coverage & (rows % 2 == 1)
        region = {"id": int(region_id), "box": [int(rr.min()), int(rr.max() + 1), int(cc.min()), int(cc.max() + 1)],
                  "points": int(area.sum()), "selection_points": int(selection.sum()),
                  "held_back_points": int(held_back.sum()), "accepted": False, "offset_vox": 0,
                  "flagged": False, "reasons": []}
        report["regions"].append(region)
        if min(int(selection.sum()), int(held_back.sum())) < min_points:
            region.update(flagged=True, reasons=["inadequate points or map/reference coverage"])
            continue
        baseline_selection = _scores(np, base, reference, ref_index, selection, min_points, displaced)
        baseline_held = _scores(np, base, reference, ref_index, held_back, min_points, displaced)
        region["baseline"] = {"selection": baseline_selection, "held_back": baseline_held}
        if baseline_selection["control_max_abs"] is None or baseline_held["control_max_abs"] is None:
            region.update(flagged=True, reasons=["inadequate baseline negative controls"])
            continue
        if all(score["r"] is not None and score["r"] >= min_corr and
               score["r"] - score["control_max_abs"] >= control_margin
               for score in (baseline_selection, baseline_held)):
            region["reasons"].append("baseline passes both subsets and controls; no correction needed")
            continue
        baseline_r = [baseline_selection["r"], baseline_held["r"]]
        region["flagged"] = True
        if any(r is None or r < min_corr for r in baseline_r):
            region["reasons"].append("weak baseline agreement")
        else:
            region["reasons"].append("baseline fails negative-control margin")
        scored = [_scores(np, candidate, reference, ref_index, selection, min_points, displaced)
                  for candidate in candidates]
        eligible = [i for i, score in enumerate(scored) if score["r"] is not None]
        if not eligible:
            region["reasons"].append("no candidate with usable selection variation")
            continue
        winner = max(eligible, key=lambda i: scored[i]["r"])
        selected = scored[winner]
        # The held-back subset is used only for the already-selected winner.
        validated = _scores(np, candidates[winner], reference, ref_index, held_back, min_points, displaced)
        region["winner"] = {"offset_vox": offsets[winner], "selection": selected, "held_back": validated}
        for label, score, baseline in (("selection", selected, baseline_selection), ("held_back", validated, baseline_held)):
            r, br = score["r"], baseline["r"]
            if r is None or br is None or r < min_corr or r - br < min_gain:
                region["reasons"].append(f"{label}: insufficient correlation or gain")
            control = score["control_max_abs"]
            if control is None or r is None or r - control < control_margin:
                region["reasons"].append(f"{label}: controls agree or are inadequate")
        if any(reason.startswith(("selection:", "held_back:")) for reason in region["reasons"]):
            region["flagged"] = True
            continue
        region.update(accepted=True, flagged=True, offset_vox=offsets[winner])
        choices[area & supported & coverage] = offsets[winner]
    # Reject both sides of excessive neighboring jumps, including unchanged neighbors.
    # Rejection can create new jumps, so conservatively reject to a fixed point.
    while True:
        bad = set()
        for axis in (0, 1):
            a = [slice(None)] * 2
            b = a.copy()
            a[axis], b[axis] = slice(None, -1), slice(1, None)
            a, b = tuple(a), tuple(b)
            jump = (np.abs(choices[a] - choices[b]) > max_step_vox + 1e-8) & base["valid"][a] & base["valid"][b]
            bad.update(int(i) for i in region_ids[a][jump])
            bad.update(int(i) for i in region_ids[b][jump])
        newly = [r for r in report["regions"] if r["accepted"] and r["id"] in bad]
        if not newly:
            break
        for region in newly:
            region.update(accepted=False, offset_vox=0)
            region["reasons"].append("neighboring offset discontinuity exceeds max_step_vox")
            choices[region_ids == region["id"]] = 0
    xyz = base["xyz"].copy()
    for offset, candidate in zip(offsets, candidates):
        take = choices == offset
        xyz[take] = candidate["xyz"][take]
    merged = dict(base, xyz=xyz)
    merged_normals, merged_supported = _normals(merged)
    if (not merged_supported[supported].all() or ((merged_normals * normals).sum(-1)[supported] <= 0).any() or
            not _unfolded(base, merged)):
        # Fail closed: mixed-patch geometry is never accepted on a folded grid.
        xyz = base["xyz"].copy()
        for region in report["regions"]:
            if region["accepted"]:
                region.update(accepted=False, offset_vox=0)
                region["reasons"].append("merged geometry folds or degenerates the native grid")
    report["accepted_regions"] = sum(r["accepted"] for r in report["regions"])
    report["flagged_regions"] = sum(r["flagged"] for r in report["regions"])
    report["status"] = ("corrections_require_rerender" if report["accepted_regions"] else
                        "no_corrections" if report["flagged_regions"] else "unchanged")
    out.mkdir(parents=True)
    _write_mesh(base["path"], out / "corrected.tifxyz", xyz)
    report["output_mesh"] = "corrected.tifxyz"
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report
