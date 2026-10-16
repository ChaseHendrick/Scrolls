"""Compare two ink maps from the same input: a reference (e.g. CPU) and a candidate (e.g. MPS).

Acceptance follows the GENChase Apple GPU backend
(https://github.com/ChaseHendrick/GENChase/blob/main/apps/validate/APPLE-GPU.md):
agreement under a stated tolerance counts only if a deliberately wrong input, the
control, is caught by the same comparison. Without a control the verdict says so.

Default tolerance: villa PR #1865 reported CPU and MPS maps differing by at most 1 of
255 grey levels on 0.002% of pixels. The defaults (2 levels, at most 0.01% of pixels
beyond that) leave margin above that report without accepting a different map.

The maps are villa's uint8 TIFFs. Reading them needs numpy and tifffile (and
imagecodecs for LZW); villa's environment has all three.
"""

import math

DEFAULT_TOLERANCE = 2
DEFAULT_MAX_FRACTION = 1e-4
ROWS_PER_BLOCK = 1024

PASS = "pass"
PASS_UNCONTROLLED = "pass-uncontrolled"
FAIL = "fail"
CONTROL_NOT_CAUGHT = "control-not-caught"


# The extra that installs the map tools' dependencies (numpy, tifffile, imagecodecs, zarr, scipy; pyproject.toml).
MAPS_INSTALL = 'python -m pip install "scrolls-workbench[maps]"'

# The command running now, for install hints: (what the user typed, the kit command), such as
# ("python -m kit auc", "auc"). kit.cli sets it while a command runs; None when kit is used as a library.
RUNNING = None


class VerifyError(Exception):
    pass


def missing(module):
    """The VerifyError for a map tool that cannot import `module`: the command that needs it, the maps
    extra that installs it, and how to run the command inside villa's environment instead."""
    typed, name = RUNNING if RUNNING else (None, None)
    need = f"{module} is required for {typed}" if typed else f"{module} is required"
    note = " (its zarr needs Python 3.11 or newer)" if module == "zarr" else ""
    return VerifyError(f"{need}. Install the maps extra{note}: {MAPS_INSTALL}, or run inside villa's environment: "
                       f"uv run --project \"$VILLA/vesuvius\" --extra models python -m kit {name or 'COMMAND'} ...")


def _numpy():
    try:
        import numpy
    except ImportError as exc:
        raise missing("numpy") from exc
    return numpy


def load_map(path):
    np = _numpy()
    try:
        import tifffile
    except ImportError as exc:
        raise missing("tifffile") from exc
    try:
        array = tifffile.imread(str(path))
    except Exception as exc:  # tifffile raises several types, e.g. for LZW without imagecodecs
        raise VerifyError(f"cannot read {path}: {exc}") from exc
    array = np.squeeze(array)
    if array.ndim != 2:
        raise VerifyError(f"{path}: expected a 2D map, got shape {array.shape}")
    return array


def compare(reference, candidate, tolerance=DEFAULT_TOLERANCE):
    """Statistics of candidate minus reference, computed in row blocks to bound memory."""
    np = _numpy()
    if reference.shape != candidate.shape:
        return {"shape_match": False, "reference_shape": list(reference.shape),
                "candidate_shape": list(candidate.shape)}
    n = reference.size
    max_abs = 0.0
    sum_abs = 0.0
    over = 0
    sx = sy = sxx = syy = sxy = 0.0
    for start in range(0, reference.shape[0], ROWS_PER_BLOCK):
        a = reference[start:start + ROWS_PER_BLOCK].astype(np.float64)
        b = candidate[start:start + ROWS_PER_BLOCK].astype(np.float64)
        d = np.abs(b - a)
        # NaN or inf in one map and not the other is a disagreement: d is then NaN or inf, and
        # max() and "d > tolerance" would both pass a NaN by. Equal values (inf and inf) or NaN in
        # both maps at the same pixel agree.
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        bad = ~(d <= tolerance) & ~same
        d = np.where(same, 0.0, d)
        if bad.any() and not np.isfinite(d[bad]).all():
            max_abs = math.inf
        max_abs = max(max_abs, float(d.max()))
        sum_abs += float(d.sum())
        over += int(bad.sum())
        sx += float(a.sum())
        sy += float(b.sum())
        sxx += float((a * a).sum())
        syy += float((b * b).sum())
        sxy += float((a * b).sum())
    cov = sxy - sx * sy / n
    var_a = sxx - sx * sx / n
    var_b = syy - sy * sy / n
    pearson = cov / math.sqrt(var_a * var_b) if var_a > 0 and var_b > 0 else None
    return {
        "shape_match": True,
        "shape": list(reference.shape),
        "pixels": n,
        "tolerance": tolerance,
        "max_abs_diff": max_abs,
        "mean_abs_diff": sum_abs / n,
        "pixels_over_tolerance": over,
        "fraction_over_tolerance": over / n,
        "pearson": pearson,
    }


def agrees(stats, max_fraction=DEFAULT_MAX_FRACTION):
    return bool(stats.get("shape_match")) and stats["fraction_over_tolerance"] <= max_fraction


def verdict(candidate_agrees, control_agrees=None):
    if not candidate_agrees:
        return FAIL
    if control_agrees is None:
        return PASS_UNCONTROLLED
    if control_agrees:
        return CONTROL_NOT_CAUGHT
    return PASS


def verify_arrays(reference, candidate, control=None, tolerance=DEFAULT_TOLERANCE,
                  max_fraction=DEFAULT_MAX_FRACTION):
    np = _numpy()
    if reference.dtype.kind == "f" and reference.size and not np.isfinite(reference).any():
        # NaN at the same pixel counts as agreement, so an all-NaN candidate (both devices overflowing,
        # say) would agree with an all-NaN reference and any finite control would look caught
        raise VerifyError("the reference map has no finite values; a broken reference cannot show agreement")
    result = {"candidate": compare(reference, candidate, tolerance), "max_fraction": max_fraction}
    result["candidate_agrees"] = agrees(result["candidate"], max_fraction)
    control_agrees = None
    if control is not None:
        if control.shape != reference.shape:
            # A control of another shape would "disagree" by shape alone and turn any candidate
            # into a pass; it shows nothing about whether the comparison can fail.
            raise VerifyError(f"control shape {tuple(control.shape)} differs from the reference's "
                              f"{tuple(reference.shape)}; the control must be the same map made wrongly")
        result["control"] = compare(reference, control, tolerance)
        control_agrees = agrees(result["control"], max_fraction)
        result["control_agrees"] = control_agrees
    result["verdict"] = verdict(result["candidate_agrees"], control_agrees)
    return result


def verify_files(reference, candidate, control=None, tolerance=DEFAULT_TOLERANCE,
                 max_fraction=DEFAULT_MAX_FRACTION):
    result = verify_arrays(
        load_map(reference), load_map(candidate),
        None if control is None else load_map(control),
        tolerance, max_fraction,
    )
    result["files"] = {"reference": str(reference), "candidate": str(candidate),
                       "control": None if control is None else str(control)}
    return result


EXPLAIN = {
    PASS: "candidate agrees with the reference, and the control was caught",
    PASS_UNCONTROLLED: "candidate agrees, but no control was given, so this comparison was not shown able to fail",
    FAIL: "candidate does not agree with the reference",
    CONTROL_NOT_CAUGHT: "the control also agreed, so this comparison cannot tell maps apart; it proves nothing",
}


def format_result(result):
    def line(label, stats):
        if not stats.get("shape_match"):
            return f"{label}: shape mismatch {stats['reference_shape']} vs {stats['candidate_shape']}"
        pearson = "n/a" if stats["pearson"] is None else f"{stats['pearson']:.6f}"
        return (f"{label}: max |diff| {stats['max_abs_diff']:.0f}, mean {stats['mean_abs_diff']:.4f}, "
                f"{stats['fraction_over_tolerance']:.6%} of pixels over {stats['tolerance']}, pearson {pearson}")

    rows = [line("candidate", result["candidate"])]
    if "control" in result:
        rows.append(line("control  ", result["control"]))
    rows.append(f"verdict: {result['verdict']} ({EXPLAIN[result['verdict']]})")
    return "\n".join(rows)
