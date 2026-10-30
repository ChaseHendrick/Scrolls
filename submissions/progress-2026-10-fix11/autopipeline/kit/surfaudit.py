"""One surface audit with swappable checks: `python -m kit.surfaudit`.

Five checks of traced tifxyz surfaces, ours and the community's, behind one interface. Each looks at the segments
it is given and returns, per segment, a boolean mask of the vertices it flags on that segment's own grid; the audit
writes every mask as a VC3D vertex mask:

  switchfix      kit switchfix (version 1) per segment: the vertices the seed's winding cannot reach (off the
                 predicted sheet, in a contact zone, or across a jump). Without --prediction only the jump test
                 runs (recorded as jump_test_only).
  switchfix2     kit switchfix2 per segment: the vertices it would move back onto the seed's predicted sheet or
                 remove. Needs --prediction.
  stackcheck     public Scrolls' segment stack check (kit stackcheck) on the segments as one stack, inner to outer,
                 with --umbilicus: its per-segment union mask "NAME/any" (order, missing sector, skipped winding,
                 turn overlap, coincident, stack end) for the checks its own thresholds flagged. Run in the public
                 checkout (--public-root, else SCROLLS_PUBLIC_ROOT, else ../Scrolls beside this repository), or read
                 from the --flags .npz a run of it already wrote (--stackcheck-flags, with --stackcheck-report to
                 apply its thresholds; without the report every vertex it marked counts).
  sheetchain     vesuvius-sheet-chain's dupcheck.py (Jashanjot Singh Gill and Nhat Nam Tran, MIT,
                 github.com/Jashann/vesuvius-sheet-chain), which needs two renders: for each --pair it runs dupcheck
                 unchanged (through a script of the source repository, which also records where each tile sits)
                 and flags the vertices under each duplicated tile, on both segments of the pair.
  spiralfiteval  jo-tud's spiralfiteval H5 (MIT, github.com/jo-tud/spiralfiteval), called through its own Fit: per
                 vertex, the normal gap to the nearest other segment of the stack; under --dup-vox (its default 2
                 voxels) is a duplicated winding. The segments are its windings, in the order given.

A check that cannot run here (a missing input, tool or checkout) is "not_run" with the reason, and the audit is
then not reported clean. Nothing is downloaded and nothing is installed: the community tools are called where they
already are (--sheetchain DIR or SHEETCHAIN_DIR; --spiralfiteval SRC or SPIRALFITEVAL_SRC, the folder holding the
spiralfiteval package, or an installed spiralfiteval).

Outputs, under --out: report.json, and one folder per segment holding <check>.tif per check that ran (uint8, 255
flagged, 0 not), flags_any.tif (their union) and mask.tif in VC3D's mask convention (255 where the vertex is valid
and no check flagged it, 0 elsewhere; VC3D's loader keeps a vertex only where channel 0 is at least 255, as
kit meshqa models). With --vc3d-copy the folder also gets the segment's x.tif, y.tif, z.tif and meta.json, so it
opens in VC3D as a tifxyz with the flagged vertices masked out. Exit status: 0 every requested check ran and none
flagged, 1 a check flagged something or did not run, 2 the audit could not be made.

Usage:

    python -m kit.surfaudit checks [--json]
    python -m kit.surfaudit run SEG [SEG ...] --out DIR [--checks switchfix,stackcheck,...] [--prediction LOC]
        [--seed NAME X Y Z] [--umbilicus U.json] [--stackcheck-flags F.npz [--stackcheck-report R.json]]
        [--public-root DIR]
        [--stackcheck-arg ARG] [--pair SEG_A RENDER_A SEG_B RENDER_B] [--pairs PAIRS.json] [--sheetchain DIR]
        [--spiralfiteval SRC] [--dup-vox 2] [--max-gap-vox 60] [--vc3d-copy] [--json]

numpy (and scipy for the switchfix checks and spiralfiteval) are needed; the rest is the standard library.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TILES_SCRIPT = ROOT / "scripts" / "surfaudit" / "dupcheck_tiles.py"
CHECK_NAMES = ("switchfix", "switchfix2", "stackcheck", "sheetchain", "spiralfiteval")
DEFAULTS = {"dup_vox": 2.0, "max_gap_vox": 60.0, "max_step_vox": 5.0}
VC3D_KEEP = 255          # QuadSurface's mask rule: channel 0 >= 255 keeps the vertex (kit/meshqa.py mask_pass)


class AuditError(ValueError):
    pass


def _np():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise AuditError("kit surfaudit needs numpy") from exc
    return np


# ---------------------------------------------------------------- segments

class Segment:
    """One tifxyz folder: name (the folder's name, or NAME=PATH), path, xyz (H, W, 3) float64, valid (H, W), meta."""

    def __init__(self, name, path, xyz, valid, meta):
        self.name, self.path, self.xyz, self.valid, self.meta = name, Path(path), xyz, valid, meta or {}

    @property
    def shape(self):
        return tuple(self.valid.shape)


def load_segments(specs):
    from . import surfbench
    segs, seen = [], set()
    for spec in specs:
        name, _, path = spec.partition("=") if "=" in spec and not Path(spec).exists() else ("", "", spec)
        path = Path(path)
        name = name or (path.name[:-len(".tifxyz")] if path.name.endswith(".tifxyz") else path.name)
        if name in seen:
            raise AuditError(f"two segments named {name}: name them with NAME=PATH")
        seen.add(name)
        try:
            xyz, valid, meta = surfbench.read_tifxyz(path)
        except surfbench.BenchError as exc:
            raise AuditError(f"{path}: {exc}") from exc
        segs.append(Segment(name, path, xyz, valid, meta))
    if not segs:
        raise AuditError("no segments")
    return segs


# ---------------------------------------------------------------- the interface

class Result:
    """What one check returns: status "ran", "not_run" (why) or "failed" (why); per segment a mask and a summary."""

    def __init__(self, status, why=None, masks=None, summary=None, detail=None):
        self.status, self.why = status, why
        self.masks = masks or {}
        self.summary = summary or {}
        self.detail = detail or {}


class Check:
    """A check: name, origin (ours or community, and whose), by, licence, inputs, and run(segs, ctx) -> Result.
    available(ctx) says what it is missing on this machine, or None."""

    def __init__(self, name, origin, by, licence, inputs, run, available):
        self.name, self.origin, self.by, self.licence, self.inputs = name, origin, by, licence, inputs
        self._run, self._available = run, available

    def available(self, ctx):
        return self._available(ctx)

    def run(self, segs, ctx):
        missing = self.available(ctx)
        if missing:
            return Result("not_run", missing)
        try:
            return self._run(segs, ctx)
        except AuditError as exc:
            return Result("failed", str(exc))
        except (ValueError, OSError) as exc:     # the checked tool's own refusal (SwitchFixError and the like)
            return Result("failed", f"{type(exc).__name__}: {exc}")

    def describe(self, ctx=None):
        return {"name": self.name, "origin": self.origin, "by": self.by, "licence": self.licence,
                "inputs": self.inputs, "missing": self.available(ctx or {})}


def _seed(seg, ctx):
    from . import switchfix
    return switchfix.seed_of(seg.meta, (ctx.get("seeds") or {}).get(seg.name))


def _sampler(ctx):
    s = ctx.get("sampler")
    if s is None and ctx.get("prediction"):
        from . import switchfix
        s = switchfix.open_prediction(ctx["prediction"], ctx.get("cache"))
        ctx["sampler"] = s
    return s


def _has(module):
    try:
        __import__(module)
        return True
    except ImportError:
        return False


# -- switchfix, version 1 and 2 (ours)

def _avail_switchfix(ctx):
    return None if _has("scipy") else "needs scipy"


def _run_switchfix(segs, ctx):
    from . import switchfix
    sampler = _sampler(ctx)
    masks, summ = {}, {}
    for s in segs:
        sm, arr = switchfix.detect(s.xyz, s.valid, sampler, seed=_seed(s, ctx))
        masks[s.name] = arr["flagged"] & s.valid
        summ[s.name] = {k: sm.get(k) for k in ("flagged", "flagged_share", "jump_edges", "sheet_jump_edges",
                                               "params_digest")}
        summ[s.name]["jump_test_only"] = sampler is None
    return Result("ran", masks=masks, summary=summ)


def _avail_switchfix2(ctx):
    if not _has("scipy"):
        return "needs scipy"
    if ctx.get("sampler") is None and not ctx.get("prediction"):
        return "needs --prediction (switchfix2 follows the seed's predicted sheet)"
    return None


def _run_switchfix2(segs, ctx):
    from . import switchfix2
    sampler = _sampler(ctx)
    masks, summ = {}, {}
    for s in segs:
        sm, arr = switchfix2.detect(s.xyz, s.valid, sampler, seed=_seed(s, ctx))
        a = arr["action"]
        masks[s.name] = ((a == switchfix2.MOVE) | (a == switchfix2.REMOVE)) & s.valid
        summ[s.name] = {k: sm.get(k) for k in ("kept", "moved", "removed", "params_digest")}
    return Result("ran", masks=masks, summary=summ)


# -- stackcheck (ours, public Scrolls)

def public_root(ctx):
    for c in (ctx.get("public_root"), os.environ.get("SCROLLS_PUBLIC_ROOT"), ROOT.parent / "Scrolls"):
        if c and (Path(c) / "kit" / "stackcheck.py").is_file():
            return Path(c)
    return None


def _avail_stackcheck(ctx):
    if ctx.get("stackcheck_flags"):
        return None if Path(ctx["stackcheck_flags"]).is_file() else f"no file {ctx['stackcheck_flags']}"
    if not ctx.get("umbilicus"):
        return "needs --umbilicus (or --stackcheck-flags from a run of it)"
    if public_root(ctx) is None:
        return "needs public Scrolls' kit/stackcheck.py (--public-root, SCROLLS_PUBLIC_ROOT or ../Scrolls)"
    return None


# stackcheck's report (summary.flagged) -> the per-vertex masks of that check in its --flags file
STACK_MASKS = {"order": "order", "order_vertices": "order", "coincident_pairs": "coincident",
               "missing_sectors": "missing_sector", "missing_runs": "missing_sector",
               "skipped_windings": "skipped_winding", "turn_overlaps": "turn_overlap", "stack_ends": "stack_end"}


def read_stack_flags(path, segs, report=None):
    """Per-segment masks from a stackcheck --flags .npz, matched by name (else by position when the names differ but
    the counts agree), each checked against the segment's grid. With stackcheck's report, only the masks of the
    checks it flagged (its --min-count and --min-share decide, as in its own verdict); without one, every vertex it
    marked (NAME/any), including marks under its thresholds."""
    np = _np()
    z = np.load(path, allow_pickle=False)
    names = [str(n) for n in z["names"]]
    if len(names) != len(segs):
        raise AuditError(f"{path} holds {len(names)} segments, the audit has {len(segs)}")
    byname = {s.name for s in segs} == set(names)
    keys = None
    if report is not None:
        flagged = (report.get("summary") or {}).get("flagged") or {}
        keys = sorted({STACK_MASKS[k] for k, v in flagged.items() if v and k in STACK_MASKS})
    masks, summ = {}, {}
    for i, s in enumerate(segs):
        n = s.name if byname else names[i]
        got = {k: np.asarray(z[f"{n}/{k}"], bool) for k in (keys if keys is not None else ["any"])}
        for k, m in got.items():
            if m.shape != s.shape:
                raise AuditError(f"{path}: {n}/{k} is {m.shape}, segment {s.name} is {s.shape}")
        m = np.zeros(s.shape, bool)
        for v in got.values():
            m |= v
        masks[s.name] = m & s.valid
        summ[s.name] = {"marked": {k.split("/", 1)[1]: int(np.asarray(z[k]).sum()) for k in z.files
                                   if k.startswith(n + "/")}, "masks_used": keys if keys is not None else ["any"]}
    return masks, summ


def _run_stackcheck(segs, ctx):
    detail, rep = {}, None
    if ctx.get("stackcheck_flags"):
        path = Path(ctx["stackcheck_flags"])
        detail["flags_file"] = str(path)
        if ctx.get("stackcheck_report"):
            rep = json.loads(Path(ctx["stackcheck_report"]).read_text())
            detail["report_file"] = str(ctx["stackcheck_report"])
    else:
        if len(segs) < 2:
            raise AuditError("stackcheck needs a stack: two or more consecutive windings")
        root = public_root(ctx)
        tmp = Path(tempfile.mkdtemp(prefix="surfaudit-stack-", dir=ctx.get("tmp")))
        path = tmp / "flags.npz"
        cmd = [ctx.get("python") or sys.executable, "-m", "kit", "stackcheck",
               *[f"{s.name}={s.path.resolve()}" for s in segs], "--umbilicus", str(Path(ctx["umbilicus"]).resolve()),
               "--flags", str(path), "--out", str(tmp / "report.json"), "--json", *(ctx.get("stackcheck_args") or [])]
        env = {**os.environ, "PYTHONPATH": str(root)}
        p = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=ctx.get("timeout", 3600))
        if p.returncode not in (0, 1) or not path.is_file():
            raise AuditError(f"stackcheck exited {p.returncode}: {(p.stderr or p.stdout)[-600:]}")
        rep = json.loads((tmp / "report.json").read_text())
        detail.update(public_root=str(root), exit=p.returncode, clean=rep["summary"].get("clean"),
                      not_checked=rep["summary"].get("not_checked"), flagged=rep["summary"].get("flagged"))
    masks, summ = read_stack_flags(path, segs, rep)
    return Result("ran", masks=masks, summary=summ, detail=detail)


# -- sheet-chain's dupcheck (community)

def _sheetchain_script(ctx):
    d = ctx.get("sheetchain") or os.environ.get("SHEETCHAIN_DIR")
    if not d:
        return None
    p = Path(d) / "sheetchain" / "dupcheck.py"
    return p if p.is_file() else None


def _avail_sheetchain(ctx):
    if not ctx.get("pairs"):
        return "needs two renders: --pair SEG_A RENDER_A SEG_B RENDER_B (or --pairs)"
    if not TILES_SCRIPT.is_file():
        return "needs the tile wrapper script of the source repository, which this release does not ship"
    if _sheetchain_script(ctx) is None:
        return "needs a vesuvius-sheet-chain checkout (--sheetchain DIR or SHEETCHAIN_DIR) with sheetchain/dupcheck.py"
    if not (_has("PIL") and _has("scipy")):
        return "dupcheck.py needs pillow and scipy"
    return None


def _cells(seg, offset, y0, x0, size):
    """The grid rows and columns under render pixels [y0, y0 + size) x [x0, x0 + size) of a render of seg on its own
    grid (render pixel p is grid position p * scale, meta.json scale [x, y]), offset the crop's top left pixel."""
    sc = seg.meta.get("scale") or [1.0, 1.0]
    sx, sy = float(sc[0]), float(sc[1])
    r0, c0 = (offset[0] + y0) * sy, (offset[1] + x0) * sx
    r1, c1 = (offset[0] + y0 + size) * sy, (offset[1] + x0 + size) * sx
    H, W = seg.shape
    lo_r, hi_r = max(0, int(r0)), min(H, int(-(-r1 // 1)))
    lo_c, hi_c = max(0, int(c0)), min(W, int(-(-c1 // 1)))
    return slice(lo_r, max(lo_r, hi_r)), slice(lo_c, max(lo_c, hi_c))


def tiles_to_masks(tiles, seg_a, seg_b, offset_a=(0, 0), offset_b=(0, 0)):
    """Masks of the vertices under dupcheck's duplicated tiles: tiles is dupcheck_tiles.py's JSON ({"T", "tiles":
    [[y, x, ncc, dx, dy, dup], ...]}); render B's tile sits at (y + dy, x + dx)."""
    np = _np()
    T = int(tiles["T"])
    ma = np.zeros(seg_a.shape, bool)
    mb = np.zeros(seg_b.shape, bool) if seg_b is not None else None
    for y, x, _, dx, dy, dup in tiles["tiles"]:
        if not dup:
            continue
        ma[_cells(seg_a, offset_a, int(y), int(x), T)] = True
        if mb is not None:
            mb[_cells(seg_b, offset_b, int(y + dy), int(x + dx), T)] = True
    return ma & seg_a.valid, (mb & seg_b.valid) if mb is not None else None


def run_dupcheck(script, render_a, render_b, ctx):
    p = subprocess.run([ctx.get("python") or sys.executable, "-I", str(TILES_SCRIPT), str(script), str(render_a),
                        str(render_b)], capture_output=True, text=True, timeout=ctx.get("timeout", 3600))
    if p.returncode != 0:
        raise AuditError(f"dupcheck exited {p.returncode}: {(p.stderr or p.stdout)[-600:]}")
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise AuditError(f"dupcheck_tiles.py printed no JSON: {p.stdout[-300:]}") from exc


def _run_sheetchain(segs, ctx):
    np = _np()
    script = _sheetchain_script(ctx)
    by = {s.name: s for s in segs}
    masks = {s.name: np.zeros(s.shape, bool) for s in segs}
    pairs = []
    for pr in ctx["pairs"]:
        a, b = by.get(pr["a"]), by.get(pr.get("b")) if pr.get("b") else None
        if a is None or (pr.get("b") and b is None):
            raise AuditError(f"--pair names a segment not in the audit: {pr['a']} {pr.get('b')}")
        t = run_dupcheck(script, pr["render_a"], pr["render_b"], ctx)
        rec = {k: pr.get(k) for k in ("a", "b", "render_a", "render_b")}
        if t.get("no_overlap"):
            pairs.append({**rec, "no_overlap": True})
            continue
        ma, mb = tiles_to_masks(t, a, b, pr.get("offset_a") or (0, 0), pr.get("offset_b") or (0, 0))
        masks[a.name] |= ma
        if b is not None:
            masks[b.name] |= mb
        dup = [x for x in t["tiles"] if x[5]]
        pairs.append({**rec, "tiles": len(t["tiles"]), "duplicated": len(dup),
                      "duplicated_share": round(len(dup) / len(t["tiles"]), 4) if t["tiles"] else None,
                      "global_shift": [t.get("gdx"), t.get("gdy")]})
    summ = {n: {"flagged": int(m.sum())} for n, m in masks.items()}
    return Result("ran", masks=masks, summary=summ, detail={"pairs": pairs, "script": str(script)})


# -- spiralfiteval H5 (community)

def _spiralfiteval(ctx):
    src = ctx.get("spiralfiteval") or os.environ.get("SPIRALFITEVAL_SRC")
    if src and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from spiralfiteval import fit as sfe_fit
    except ImportError:
        return None
    return sfe_fit


def _avail_spiralfiteval(ctx):
    if _spiralfiteval(ctx) is None:
        return "needs spiralfiteval (--spiralfiteval SRC, SPIRALFITEVAL_SRC, or installed)"
    return None


def _run_spiralfiteval(segs, ctx):
    np = _np()
    if len(segs) < 2:
        raise AuditError("spiralfiteval's duplicate check needs two or more windings")
    F = _spiralfiteval(ctx)
    dup = float(ctx.get("dup_vox", DEFAULTS["dup_vox"]))
    max_gap = float(ctx.get("max_gap_vox", DEFAULTS["max_gap_vox"]))
    grids = {i: (s.xyz.astype(np.float32), s.valid.copy()) for i, s in enumerate(segs)}
    fit = F.build_fit(grids, name="surfaudit", column_sense=1, max_step=float(ctx.get("max_step_vox",
                                                                                      DEFAULTS["max_step_vox"])))
    masks, summ = {}, {}
    for i, s in enumerate(segs):
        m = np.zeros(s.shape, bool)
        rr, cc = np.nonzero(s.valid)
        if len(rr):
            f = i + cc / float(s.shape[1])          # build_fit's spiral time of an original vertex (column_sense 1)
            _, gap = fit.project(s.xyz[rr, cc].astype(np.float64), max_gap, exclude_f=f)
            hit = np.isfinite(gap) & (gap < dup)
            m[rr[hit], cc[hit]] = True
            has = np.isfinite(gap)
            summ[s.name] = {"flagged": int(hit.sum()), "duplicate_share": round(float(hit.mean()), 4),
                            "no_neighbour_share": round(float(1 - has.mean()), 4),
                            "median_gap_vox": round(float(np.median(gap[has])), 3) if has.any() else None}
        masks[s.name] = m
    return Result("ran", masks=masks, summary=summ, detail={"dup_vox": dup, "max_gap_vox": max_gap,
                                                             "module": getattr(F, "__file__", None)})


CHECKS = {
    "switchfix": Check("switchfix", "ours", "kit switchfix (version 1): vertices the seed's winding cannot reach",
                       "this repository", "one surface; --prediction optional (else the jump test only)",
                       _run_switchfix, _avail_switchfix),
    "switchfix2": Check("switchfix2", "ours", "kit switchfix2: vertices it would move back onto the seed's sheet or "
                        "remove", "this repository", "one surface and --prediction", _run_switchfix2,
                        _avail_switchfix2),
    "stackcheck": Check("stackcheck", "ours (public Scrolls)", "public Scrolls' segment stack check, union mask per "
                        "segment", "public Scrolls", "a stack inner to outer and --umbilicus, or --stackcheck-flags",
                        _run_stackcheck, _avail_stackcheck),
    "sheetchain": Check("sheetchain", "community (Jashanjot Singh Gill and Nhat Nam Tran)", "vesuvius-sheet-chain's "
                        "dupcheck.py on two renders, called unchanged", "MIT (called, not copied)",
                        "two renders per pair (ct/d+00.jpg on each segment's own grid)", _run_sheetchain,
                        _avail_sheetchain),
    "spiralfiteval": Check("spiralfiteval", "community (Johannes Pfeffer, jo-tud)", "spiralfiteval's H5 duplicated "
                           "winding test through its own Fit", "MIT (called, not copied)",
                           "two or more windings in stack order", _run_spiralfiteval, _avail_spiralfiteval),
}


# ---------------------------------------------------------------- the audit

def audit(segs, checks, ctx=None):
    """Run the named checks; returns (report, {segment: {check: mask}})."""
    np = _np()
    ctx = dict(ctx or {})
    bad = [c for c in checks if c not in CHECKS]
    if bad or not checks:
        raise AuditError(f"no check {', '.join(bad) or '(none named)'}; checks: {', '.join(CHECK_NAMES)}")
    out = {s.name: {} for s in segs}
    rep = {"kind": "kit-surfaudit", "version": 1, "segments": [{"name": s.name, "path": str(s.path),
                                                               "grid": list(s.shape), "valid": int(s.valid.sum())}
                                                              for s in segs], "checks": {}}
    for name in checks:
        c = CHECKS[name]
        res = c.run(segs, ctx)
        entry = {"status": res.status, **({"why": res.why} if res.why else {}), "origin": c.origin, "by": c.by,
                 "licence": c.licence}
        if res.status == "ran":
            per = {}
            for s in segs:
                m = res.masks.get(s.name)
                if m is None:
                    continue
                m = np.asarray(m, bool)
                if m.shape != s.shape:
                    raise AuditError(f"check {name} returned a {m.shape} mask for {s.name} ({s.shape})")
                out[s.name][name] = m & s.valid
                n = int(out[s.name][name].sum())
                per[s.name] = {**res.summary.get(s.name, {}), "flagged": n,
                               "flagged_share": round(n / max(int(s.valid.sum()), 1), 4)}
            entry["segments"] = per
            entry["flagged"] = sum(p["flagged"] for p in per.values())
            if res.detail:
                entry["detail"] = res.detail
        rep["checks"][name] = entry
    union = {}
    for s in segs:
        any_ = np.zeros(s.shape, bool)
        for m in out[s.name].values():
            any_ |= m
        union[s.name] = {"flagged": int(any_.sum()), "flagged_share": round(int(any_.sum()) / max(int(s.valid.sum()),
                                                                                                    1), 4)}
    ran = [n for n, e in rep["checks"].items() if e["status"] == "ran"]
    rep["summary"] = {"ran": ran, "not_run": {n: e.get("why") for n, e in rep["checks"].items() if n not in ran},
                      "flagged": {n: e["flagged"] for n, e in rep["checks"].items() if e.get("flagged")},
                      "union": union}
    rep["summary"]["clean"] = len(ran) == len(checks) and not rep["summary"]["flagged"]
    return rep, out


def _u8(path, arr):
    from . import vc3d_io
    np = _np()
    a = np.ascontiguousarray(arr, dtype=np.uint8)
    vc3d_io.write_tiff(path, vc3d_io.Raster(a.shape[0], a.shape[1], "u8", a.tobytes()))


def write_masks(out, segs, masks, vc3d_copy=False):
    """Per segment: <check>.tif, flags_any.tif and mask.tif (VC3D keep mask); with vc3d_copy the tifxyz files too."""
    np = _np()
    out = Path(out)
    written = {}
    for s in segs:
        d = out / s.name
        d.mkdir(parents=True, exist_ok=True)
        any_ = np.zeros(s.shape, bool)
        files = []
        for name, m in masks[s.name].items():
            _u8(d / f"{name}.tif", np.where(m, 255, 0))
            files.append(f"{name}.tif")
            any_ |= m
        _u8(d / "flags_any.tif", np.where(any_, 255, 0))
        _u8(d / "mask.tif", np.where(s.valid & ~any_, VC3D_KEEP, 0))
        files += ["flags_any.tif", "mask.tif"]
        if vc3d_copy:
            for f in ("x.tif", "y.tif", "z.tif", "meta.json"):
                shutil.copyfile(s.path / f, d / f)
            files += ["x.tif", "y.tif", "z.tif", "meta.json"]
        written[s.name] = {"dir": str(d), "files": files}
    return written


def parse_pairs(pair_args, pairs_file):
    pairs = []
    for a, ra, b, rb in pair_args or []:
        pairs.append({"a": a, "render_a": ra, "b": None if b in ("-", "") else b, "render_b": rb})
    if pairs_file:
        data = json.loads(Path(pairs_file).read_text())
        if not isinstance(data, list):
            raise AuditError(f"{pairs_file}: a list of pairs")
        for p in data:
            if not isinstance(p, dict) or not {"a", "render_a", "render_b"} <= set(p):
                raise AuditError(f"{pairs_file}: each pair has a, render_a, render_b (b, offset_a, offset_b optional)")
            pairs.append(p)
    return pairs


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------- command line

def build_parser(p):
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("checks", help="the checks, where each comes from and what this machine lacks for it")
    a.add_argument("--json", action="store_true")
    a = act.add_parser("run", help="run checks on tifxyz segments and write VC3D vertex masks")
    a.add_argument("segments", nargs="+", help="tifxyz folders (NAME=PATH names one); a stack goes inner to outer")
    a.add_argument("--out", required=True, help="output folder: report.json and one mask folder per segment")
    a.add_argument("--checks", default="switchfix", help=f"comma list from {','.join(CHECK_NAMES)} (default switchfix)")
    a.add_argument("--prediction", help="surface prediction (local zarr, bucket prefix or URL) for switchfix and "
                                        "switchfix2")
    a.add_argument("--cache", default=None, help="chunk cache for a remote prediction")
    a.add_argument("--seed", nargs=4, action="append", metavar=("NAME", "X", "Y", "Z"),
                   help="a segment's seed (else its meta.json seed, else its nearest vertex to the grid's middle)")
    a.add_argument("--umbilicus", help="umbilicus JSON for stackcheck")
    a.add_argument("--stackcheck-flags", help="a stackcheck --flags .npz to read instead of running it")
    a.add_argument("--stackcheck-report", help="that run's --out report.json: keep only the checks it flagged")
    a.add_argument("--public-root", help="public Scrolls checkout for stackcheck (default SCROLLS_PUBLIC_ROOT or "
                                         "../Scrolls)")
    a.add_argument("--stackcheck-arg", action="append", default=[], help="one more argument for stackcheck "
                                                                         "(repeat; e.g. --stackcheck-arg=--stride=2)")
    a.add_argument("--pair", nargs=4, action="append", metavar=("SEG_A", "RENDER_A", "SEG_B", "RENDER_B"),
                   help="two renders for sheetchain, each a folder with ct/d+00.jpg on its segment's own grid; "
                        "SEG_B '-' flags only SEG_A")
    a.add_argument("--pairs", help="JSON list of pairs {a, render_a, b, render_b, offset_a, offset_b} for crops")
    a.add_argument("--sheetchain", help="vesuvius-sheet-chain checkout (default SHEETCHAIN_DIR)")
    a.add_argument("--spiralfiteval", help="folder holding the spiralfiteval package (default SPIRALFITEVAL_SRC)")
    a.add_argument("--dup-vox", type=float, default=DEFAULTS["dup_vox"], help="spiralfiteval duplicate gap (default 2)")
    a.add_argument("--max-gap-vox", type=float, default=DEFAULTS["max_gap_vox"],
                   help="spiralfiteval farthest normal search (default 60)")
    a.add_argument("--vc3d-copy", action="store_true", help="copy each segment's tifxyz files beside its mask.tif")
    a.add_argument("--json", action="store_true")
    return p


def cmd_surfaudit(args):
    ctx = {"public_root": getattr(args, "public_root", None), "sheetchain": getattr(args, "sheetchain", None),
           "spiralfiteval": getattr(args, "spiralfiteval", None)}
    if args.action == "checks":
        rows = [CHECKS[n].describe(ctx) for n in CHECK_NAMES]
        if args.json:
            print(json.dumps(rows, indent=1))
        else:
            for r in rows:
                print(f"{r['name']:<14} {r['origin']}; {r['by']}. Needs {r['inputs']}."
                      + (f" Missing here: {r['missing']}" if r["missing"] else " Available"))
        return 0
    try:
        segs = load_segments(args.segments)
        names = {s.name for s in segs}
        seeds = {}
        for n, *xyz in args.seed or []:
            if n not in names:
                raise AuditError(f"--seed names {n}, not a segment of the audit")
            seeds[n] = [float(v) for v in xyz]
        ctx.update(prediction=args.prediction, cache=args.cache, seeds=seeds, umbilicus=args.umbilicus,
                   stackcheck_flags=args.stackcheck_flags,
                   stackcheck_report=args.stackcheck_report, stackcheck_args=args.stackcheck_arg,
                   pairs=parse_pairs(args.pair, args.pairs), dup_vox=args.dup_vox, max_gap_vox=args.max_gap_vox)
        checks = [c.strip() for c in args.checks.split(",") if c.strip()]
        rep, masks = audit(segs, checks, ctx)
        rep["written"] = write_masks(args.out, segs, masks, args.vc3d_copy)
        rep["settings"] = {"checks": checks, "dup_vox": args.dup_vox, "max_gap_vox": args.max_gap_vox,
                           "prediction": args.prediction, "seeds": seeds, "vc3d_copy": args.vc3d_copy}
        Path(args.out, "report.json").write_text(json.dumps(rep, indent=1, default=str))
    except (AuditError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"kit surfaudit: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rep, indent=1, default=str))
    else:
        for n, e in rep["checks"].items():
            print(f"{n:<14} {e['status']:<8} " + (f"flagged {e.get('flagged', 0)}" if e["status"] == "ran"
                                                  else e.get("why", "")))
        print(f"clean: {rep['summary']['clean']}; masks in {args.out}")
    return 0 if rep["summary"]["clean"] else 1


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit.surfaudit", description=__doc__.split("\n")[0]))
    return cmd_surfaudit(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
