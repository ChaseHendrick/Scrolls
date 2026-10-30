"""AutoPipeline's stack check: public Scrolls' `kit stackcheck` over a run's accepted traces at report.

stackcheck checks a stack of consecutive windings, given inner to outer, against the scroll's umbilicus, from
vertex positions alone (public Scrolls kit/stackcheck.py). An AutoPipeline run's traces start from seeds and are not
known to be one per winding, so this step orders them by their median distance from the run's umbilicus
(umbilicus.json, the axis the run used) and hands that order to stackcheck, reusing kit surfaudit's loaders.
Two of its checks read the same whatever the windings are: order (one trace lying outside the next one out on a ray
from the umbilicus, so they cross) and coincident pairs (two traces within --coincide-um of each other, one sheet
traced twice). The others (pair spacing, missing sectors and runs, skipped windings, turn overlaps, stack ends)
assume that the traces are consecutive windings, so on traces from seeds they report how the traces sit, not that
something is wrong; the record keeps them apart (SURFACE_CHECKS against STACK_CHECKS). A geometry check that can
fail, not a reading.

Settings (AutoPipeline's optional `stackcheck` setting): stride and upsample (stackcheck's --stride and --upsample;
2 and 1, the settings its page gives for full 2.4 um traces), planes (its --planes, 50) and timeout_s (3600)."""
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULTS = {"stride": 2, "upsample": 1, "planes": 50, "timeout_s": 3600}
VERSION = 1
# stackcheck's flagged checks (its report's summary.flagged keys) that mean the same on any traces, and those that
# assume consecutive windings
SURFACE_CHECKS = ("order", "order_vertices", "coincident_pairs")
STACK_CHECKS = ("pair_spacing", "missing_sectors", "missing_runs", "skipped_windings", "turn_overlaps", "stack_ends")
SURFACE_MASKS = ("order", "coincident")       # their per-vertex masks in stackcheck's --flags file
NOTE = ("Geometry checks of the run's traces by public Scrolls' kit stackcheck, ordered by median distance from the "
        "run's umbilicus. order and coincident_pairs mean the same on any traces; the stack checks assume consecutive "
        "windings, which traces from seeds are not known to be. A check that can fail, not a reading.")


class StackError(ValueError):
    pass


def check(c):
    """The `stackcheck` setting's values: whole numbers in range."""
    for key, lo, hi in (("stride", 1, 64), ("upsample", 1, 8), ("planes", 2, 2000), ("timeout_s", 60, 86400)):
        v = c.get(key)
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise StackError(f"stackcheck.{key} is a whole number from {lo} to {hi}")


def radial_order(segs, points):
    """[(name, median radius in voxels)] inner to outer: each segment's valid vertices' distance from the umbilicus
    at their own height (linear between control points, constant past the ends, as stackcheck interpolates)."""
    import numpy as np
    zs = np.array([p[0] for p in points], float)
    ys = np.array([p[1] for p in points], float)
    xs = np.array([p[2] for p in points], float)
    out = []
    for s in segs:
        v = s.xyz[s.valid]
        if not len(v):
            raise StackError(f"{s.name} has no valid vertex")
        cx, cy = np.interp(v[:, 2], zs, xs), np.interp(v[:, 2], zs, ys)
        out.append((s.name, float(np.median(np.hypot(v[:, 0] - cx, v[:, 1] - cy)))))
    return sorted(out, key=lambda t: (t[1], t[0]))


def run(paths, umbilicus, voxel_um, folder, settings=None, public_root=None, python=None):
    """The record of one stack check: paths {surface id: tifxyz folder}, umbilicus the run's umbilicus.json, folder
    where stackcheck's report.json and flags.npz go. status ran, not_run (why) or failed (why); on ran, the order,
    the checks flagged (surface checks apart from stack checks), and each surface's share of vertices marked by
    the surface checks (order, coincident) and by any check."""
    from . import surfaudit, vc3d_orient
    c = {**DEFAULTS, **(settings or {})}
    check(c)
    base = {"version": VERSION, "settings": c, "note": NOTE}
    paths = {k: v for k, v in paths.items() if v and Path(v).is_dir()}
    if len(paths) < 2:
        return {**base, "status": "not_run", "why": f"needs two or more accepted traces on disk, has {len(paths)}"}
    if not Path(umbilicus).is_file():
        return {**base, "status": "not_run", "why": f"no umbilicus at {umbilicus}"}
    why = surfaudit._avail_stackcheck({"umbilicus": str(umbilicus), "public_root": public_root})
    if why:
        return {**base, "status": "not_run", "why": why}
    root = surfaudit.public_root({"public_root": public_root})
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        segs = surfaudit.load_segments([f"{k}={v}" for k, v in sorted(paths.items())])
        order = radial_order(segs, vc3d_orient.load_umbilicus(umbilicus))
    except (surfaudit.AuditError, vc3d_orient.OrientError, StackError, OSError, ValueError) as exc:
        return {**base, "status": "failed", "why": str(exc)[-600:]}
    byname = {s.name: s for s in segs}
    flags, report = folder / "flags.npz", folder / "report.json"
    cmd = [python or sys.executable, "-m", "kit", "stackcheck",
           *[f"{n}={byname[n].path.resolve()}" for n, _ in order], "--umbilicus", str(Path(umbilicus).resolve()),
           "--voxel-um", repr(float(voxel_um)), "--stride", str(c["stride"]), "--upsample", str(c["upsample"]),
           "--planes", str(c["planes"]), "--flags", str(flags), "--out", str(report), "--json"]
    try:
        p = subprocess.run(cmd, cwd=root, env={**os.environ, "PYTHONPATH": str(root)},
                           capture_output=True, text=True, timeout=c["timeout_s"])
    except subprocess.TimeoutExpired:
        return {**base, "status": "failed", "why": f"stackcheck ran past timeout_s {c['timeout_s']}"}
    if p.returncode not in (0, 1) or not flags.is_file() or not report.is_file():
        return {**base, "status": "failed", "why": f"stackcheck exited {p.returncode}: {(p.stderr or p.stdout)[-600:]}"}
    import numpy as np
    rep = json.loads(report.read_text())
    summ = rep.get("summary") or {}
    flagged = {k: v for k, v in (summ.get("flagged") or {}).items() if v}
    z = np.load(flags, allow_pickle=False)
    surfaces = {}
    for n, _ in order:
        s = byname[n]
        def share(keys):
            m = np.zeros(s.shape, bool)
            for k in keys:
                if f"{n}/{k}" in z.files:
                    m |= np.asarray(z[f"{n}/{k}"], bool)
            return round(int((m & s.valid).sum()) / max(int(s.valid.sum()), 1), 4)
        surfaces[n] = {"surface_check_share": share(SURFACE_MASKS), "any_check_share": share(["any"])}
    return {**base, "status": "ran", "exit": p.returncode, "public_root": str(root), "report": str(report),
            "flags": str(flags), "order": [{"surface": n, "median_radius_vox": round(r, 1)} for n, r in order],
            "surface_checks_flagged": {k: v for k, v in flagged.items() if k in SURFACE_CHECKS},
            "stack_checks_flagged": {k: v for k, v in flagged.items() if k not in SURFACE_CHECKS},
            "not_checked": summ.get("not_checked"), "surfaces": surfaces}


def write(path, rec):
    """rec to path as JSON, atomically."""
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1))
    tmp.replace(path)
    return path
