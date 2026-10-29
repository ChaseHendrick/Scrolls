"""Multi-scale label snap: snap a label traced on a coarse scan onto the recto face seen in a finer, registered scan.

kit labelsnap snaps a label on the scan it was traced on. It abstains, or picks the wrong face, where two sheets look
about as near at 9 um. This module reads the finer, registered scan instead: it reads the finer scan through the
catalog matrix (coarse level-0 voxels to fine level-0 voxels), refits the matrix's error along the normal per vertex
or per tile (kit.snaptruth.register_shift on coarse against fine profiles), finds the recto face on the fine profiles
in coarse units, and maps the result back to the coarse frame. Vertices whose registration fails, or with no fine
face, fall back to the coarse snap.

The defaults are the setting tested on 60 fresh PHerc0139 sites against the recto face of an independent 1.129 um
scan (27 October 2026; a test fixed in writing before it ran): a registration per vertex from its 3 x 3 window and
the "bands" face finder (the recto face of the fine band nearest the label, kit.snaptruth's face definition). Build
the fine samplers with `sampler()`, which reads at voxel centers; a plain kit.snap.Sampler reads level L at
xyz / 2^L, about 0.26 coarse voxels off per axis at the 2.399 um levels 1 and 2. "finder": "labelsnap" with tile 4
is an earlier setting, kept as an option.

A snapped label is geometry, not a reading; nothing here is about ink.
"""

import math

from . import labelsnap as L
from . import snap as S

VERSION = 2
DEFAULTS = {
    "tile": 1,                # a registration every tile cells along each grid axis (1: per vertex)
    "reg_window": 3,          # each registration reads the profiles in this window of cells around its centre
    "min_lines": 6,           # profiles a registration needs
    "reg_t": 26.0,            # registration profiles span -reg_t..reg_t, coarse voxels (the tests' setting)
    "reg_step": 0.25,
    "reg_smax": 4.0,          # shift search range, coarse voxels
    "reg_min_peak": 0.8,      # a tile's registration counts when its mean NCC reaches this (the tests' floor)
    "smooth": 0.5,            # spread of the registrations over the grid, in tiles (normalized convolution sigma)
    "fallback": True,         # coarse snap where the fine snap has no answer
    "fine_extra": None,       # extra snap_face options for the fine snap (such as {"max_move": 8.0})
    "fine_resolve": None,     # kit.snapresolve mode for the fine snap's abstaining vertices (None: leave them)
    "resolve_opts": None,     # its options
    "finder": "bands",        # face finder on the fine profiles: "labelsnap" (kit labelsnap's) or "bands" (the band
                              # nearest the registered label and its recto face, kit.snaptruth.sheet_faces)
    "band_t": 16.0,           # "bands": the fine profile spans -band_t..band_t, coarse voxels
    "band_step": 0.25,
    "band_opts": {"sigma": 1.0},   # "bands": sheet_faces options (FACE_DEFAULTS otherwise)
}
FINDERS = ("labelsnap", "bands")


def _np():
    return S._numpy()


def sampler(vol, level):
    """A kit.snap.Sampler on the fine volume that reads voxel centres, (xyz + 0.5) / 2^level - 0.5, as the tests'
    truth and positive control do. Pass it (for the face) and one at a coarser level (for the registration) as
    snap_fine's fine samplers."""
    return S.Sampler(vol, level=level, centres=True)


def apply(M, p):
    np = _np()
    p = np.asarray(p, dtype=np.float64).reshape(-1, 3)
    return p @ np.asarray(M, dtype=np.float64)[:, :3].T + np.asarray(M, dtype=np.float64)[:, 3]


class MappedSampler:
    """A kit.snap sampler that reads a finer volume at coarse level-0 points: each point goes through M (3 x 4,
    coarse level-0 xyz to the fine volume's level-0 xyz) and then to `sampler` (a kit.snap.Sampler on the fine
    volume)."""

    def __init__(self, sampler, M):
        np = _np()
        self.sampler = sampler
        self.M = np.asarray(M, dtype=np.float64).reshape(3, 4)

    def trilinear(self, xyz):
        return self.sampler.trilinear(apply(self.M, xyz))


def tile_shifts(xs, ys, zs, n, ok, coarse, fine_reg, opts=None, batch=S.DEFAULT_BATCH):
    """The shift along the normal (coarse voxels) that best aligns the fine scan's profiles with the coarse scan's
    (fine read at t + shift), registered at the centre of every tile of the grid from the profiles in a window of
    reg_window cells around it (the scans' misregistration varies along the sheet, so the window is small), then
    spread over the grid by normalized convolution. Returns (shift grid of the mesh's shape, nan where no
    registration reaches; list of per-tile records)."""
    np = _np()
    from . import snaptruth as T
    o = dict(DEFAULTS)
    o.update(opts or {})
    H, W = xs.shape
    tl = int(o["tile"])
    h = int(o["reg_window"]) // 2
    step = float(o["reg_step"])
    t = np.arange(-o["reg_t"], o["reg_t"] + 0.5 * step, step)
    smax = float(o["reg_smax"])
    t_ext = np.arange(-o["reg_t"] - smax - 1, o["reg_t"] + smax + 1 + 0.5 * step, step / 2)
    vy, vx = np.nonzero(ok)
    idx = np.full((H, W), -1)
    idx[vy, vx] = np.arange(len(vy))
    P = np.stack([xs[vy, vx], ys[vy, vx], zs[vy, vx]], -1).astype(np.float64)
    N = n[vy, vx].astype(np.float64)
    ref = S._profile(coarse, P, N, t, batch) if len(vy) else np.zeros((0, len(t)))
    mov = S._profile(fine_reg, P, N, t_ext, batch) if len(vy) else np.zeros((0, len(t_ext)))
    grid = np.full((H, W), np.nan)
    recs = []
    for r in range(min(tl // 2, H - 1), H, tl):
        for c in range(min(tl // 2, W - 1), W, tl):
            win = idx[max(0, r - h):r + h + 1, max(0, c - h):c + h + 1].ravel()
            win = win[win >= 0]
            if len(win) < int(o["min_lines"]):
                continue
            g = T.register_shift(t, ref[win], t_ext, mov[win], np.ones(len(t), bool), s_max=smax)
            good = (math.isfinite(g["shift"]) and not g["edge"] and g["peak"] >= o["reg_min_peak"])
            recs.append({"at": [r, c], "shift": g["shift"], "peak": g["peak"], "edge": g["edge"],
                         "lines": g["lines"], "used": bool(good)})
            if good:
                grid[r, c] = g["shift"]
    if np.isfinite(grid).any():
        grid = S.normconv(grid, max(0.5, float(o["smooth"]) * tl))
        grid[~ok] = np.nan
    return grid, recs


def band_snap(xa, ya, za, n, ok, sampler, axis, recto_sign, o, batch=S.DEFAULT_BATCH):
    """The "bands" finder: at each vertex, the papyrus band of the fine profile nearest the (registered) label and
    that band's recto face (kit.snaptruth.sheet_faces, the face definition the 1.129 um tests score against). A
    vertex whose choice is ambiguous, or whose band runs off the profile, gets no face. Returns xs, ys, zs and
    detail.measured (offset along the normal, nan where none), the shape label_snap returns."""
    np = _np()
    from . import snaptruth as T
    from . import snapresolve
    measured = np.full(xa.shape, np.nan)
    xo, yo, zo = xa.copy(), ya.copy(), za.copy()
    ty, tx = np.nonzero(ok)
    if len(ty):
        base = np.stack([xa[ty, tx], ya[ty, tx], za[ty, tx]], -1).astype(np.float64)
        nvx = n[ty, tx].astype(np.float64)
        rs = snapresolve.recto_signs(base, nvx, axis, None if recto_sign is None
                                     else np.broadcast_to(np.asarray(recto_sign, dtype=np.float64), xa.shape)[ty, tx])
        t = np.arange(-o["band_t"], o["band_t"] + 0.5 * o["band_step"], o["band_step"])
        prof = S._profile(sampler, base, nvx, t, batch)
        for j in range(len(ty)):
            if rs[j] == 0 or not np.isfinite(prof[j]).all():
                continue
            row = T.sheet_faces(t, prof[j], rs[j], 0.0, o["band_opts"])
            if row["ok"] and np.isfinite(row["recto"]):
                measured[ty[j], tx[j]] = row["recto"]
        m = np.isfinite(measured)
        xo[m] += measured[m] * n[m][:, 0]
        yo[m] += measured[m] * n[m][:, 1]
        zo[m] += measured[m] * n[m][:, 2]
    return {"xs": xo, "ys": yo, "zs": zo, "detail": {"measured": measured}}


def snap_fine(xs, ys, zs, valid, coarse, fine, fine_reg, M, axis=None, recto_sign=None, target="recto",
              face_sigma=L.DEFAULTS["face_sigma"], opts=None, batch=S.DEFAULT_BATCH):
    """The multi-scale label snap of one mesh. coarse: a kit.snap.Sampler on the label's own scan (level 0 frame);
    fine, fine_reg: kit.snap.Samplers on the finer scan at the level the faces are found on and the level its
    registration reads (a level near the coarse voxel size); M: coarse level-0 xyz to fine level-0 xyz. Returns a
    dict: xs, ys, zs (snapped grids), valid, source (uint8 grid: 1 the fine snap, 2 the coarse snap, 0 not moved),
    abstain (uint8, 0 measured by either, 1 neither, 255 invalid), shift (registration grid), tiles (records),
    fine and coarse (the two label_snap results), report."""
    np = _np()
    o = dict(DEFAULTS)
    o.update(opts or {})
    if o["finder"] not in FINDERS:
        raise S.SnapError(f"finesnap finder must be one of {', '.join(FINDERS)}, not {o['finder']!r}")
    if o["finder"] == "bands" and o["fine_resolve"]:
        raise S.SnapError("finesnap fine_resolve works with the labelsnap finder only")
    n, ok = S.normals(xs, ys, zs, valid)
    shift, recs = tile_shifts(xs, ys, zs, n, ok, coarse, MappedSampler(fine_reg, M), o, batch)
    reg = ok & np.isfinite(shift)
    sh = np.where(reg, shift, 0.0)
    xa, ya, za = (xs + sh * n[..., 0], ys + sh * n[..., 1], zs + sh * n[..., 2])
    if o["finder"] == "bands":
        fres = band_snap(xa, ya, za, n, reg, MappedSampler(fine, M), axis, recto_sign, o, batch)
    else:
        fres = L.label_snap(xa, ya, za, valid, MappedSampler(fine, M), axis=axis, recto_sign=recto_sign,
                            target=target, merged=False, face_sigma=face_sigma, extra_opts=o["fine_extra"],
                            batch=batch)
    nres = 0
    if o["fine_resolve"]:
        from . import snapresolve
        ro = dict(o["resolve_opts"] or {}, mode=o["fine_resolve"])
        rr = snapresolve.resolve(xa, ya, za, valid, MappedSampler(fine, M), fres, axis=axis, recto_sign=recto_sign,
                                 face_opts={"sigma": float(face_sigma)}, opts=ro, batch=batch)
        res_v = rr["resolved"]
        fres = dict(fres)
        fres["detail"] = dict(fres["detail"], measured=rr["measured"])
        fres["xs"], fres["ys"], fres["zs"] = rr["xs"], rr["ys"], rr["zs"]
        nres = int(res_v.sum())
    cres = L.label_snap(xs, ys, zs, valid, coarse, axis=axis, recto_sign=recto_sign, target=target, merged=False,
                        face_sigma=face_sigma, batch=batch)
    f_meas = reg & np.isfinite(fres["detail"]["measured"])
    c_meas = ok & np.isfinite(cres["detail"]["measured"])
    xo, yo, zo = xs.copy(), ys.copy(), zs.copy()
    source = np.zeros(xs.shape, np.uint8)
    use_f = f_meas
    xo[use_f] = fres["xs"][use_f] - sh[use_f] * n[use_f][:, 0]
    yo[use_f] = fres["ys"][use_f] - sh[use_f] * n[use_f][:, 1]
    zo[use_f] = fres["zs"][use_f] - sh[use_f] * n[use_f][:, 2]
    source[use_f] = 1
    if o["fallback"]:
        use_c = ~use_f & np.asarray(cres["apply"], bool)
        xo[use_c], yo[use_c], zo[use_c] = cres["xs"][use_c], cres["ys"][use_c], cres["zs"][use_c]
        source[use_c] = 2
    abstain = np.full(xs.shape, L.ABSTAIN_INVALID, np.uint8)
    abstain[valid] = L.ABSTAIN_YES
    abstain[f_meas | (c_meas if o["fallback"] else False)] = L.ABSTAIN_OK
    nv = max(1, int(ok.sum()))
    report = {"tiles": len(recs), "tiles_registered": int(sum(r["used"] for r in recs)),
              "frac_registered": float(reg.sum() / nv), "frac_fine": float(use_f.sum() / nv),
              "frac_coarse_fallback": float((source == 2).sum() / nv),
              "frac_abstained": float((abstain == L.ABSTAIN_YES).sum() / max(1, int(valid.sum()))),
              "fine_resolved": nres, "median_shift": float(np.nanmedian(shift[reg])) if reg.any() else None, "opts": o}
    return {"xs": xo, "ys": yo, "zs": zo, "valid": valid, "source": source, "abstain": abstain, "shift": shift,
            "tiles": recs, "fine": fres, "coarse": cres, "report": report}


def read_matrix(path, inverse=False):
    """The 3 x 4 affine (x, y, z rows) from coarse level-0 xyz to fine level-0 xyz: a VC3D transform.json (its
    transformation_matrix), {"matrix": ...}, or a bare 3 x 4 or 4 x 4 list; inverse=True inverts it (for a transform
    published the other way, fine to coarse)."""
    import json
    from pathlib import Path
    from .vc3d_landmarks import LandmarkError, as_matrix, invert
    try:
        t = json.loads(Path(path).read_text())
        m = as_matrix(t.get("transformation_matrix") or t.get("matrix") if isinstance(t, dict) else t)
        if any(not math.isfinite(v) for r in m for v in r):
            raise LandmarkError("the matrix has a non-finite entry")
        return invert(m) if inverse else m
    except (OSError, ValueError, LandmarkError) as exc:
        raise S.SnapError(f"{path}: not a usable matrix ({exc})") from exc


def as_label_result(fr):
    """snap_fine's result in the shape kit labelsnap's writer takes: the snapped grids and abstain mask are finesnap's;
    reason is 0 exactly where a vertex was placed and the coarse snap's reason elsewhere; confidence is the coarse
    snap's where it measured, else 0 (source.tif says which snap placed each vertex)."""
    np = _np()
    c = fr["coarse"]
    ab = fr["abstain"]
    reason = np.where(ab == L.ABSTAIN_OK, 0, c["reason"]).astype(np.uint8)
    reason[(ab == L.ABSTAIN_YES) & (reason == 0)] = 5          # "ambiguous or off the profile"
    conf = np.where(ab == L.ABSTAIN_OK, c["confidence"], 0.0).astype(np.float32)
    out = dict(c)
    out.update({"xs": fr["xs"], "ys": fr["ys"], "zs": fr["zs"], "abstain": ab, "reason": reason, "confidence": conf,
                "apply": fr["source"] > 0, "opts": dict(c["opts"], finesnap=fr["report"]["opts"]),
                "report": dict(c["report"], finesnap={k: v for k, v in fr["report"].items() if k != "opts"})})
    return out


def run_snap(args):
    import json
    import time
    from pathlib import Path
    np = _np()
    t0 = time.time()
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise S.SnapError(f"{out} is not empty: write each run to a new folder")
    axis = L._axis_of(args)
    xs, ys, zs, valid = S.load_mesh(args.surface)
    vol = S.open_volume(args.volume)
    fvol = S.open_volume(args.fine)
    M = np.asarray(read_matrix(args.matrix, inverse=args.matrix_inverse), dtype=np.float64)
    opts = json.loads(args.opts) if args.opts else {}
    fr = snap_fine(xs, ys, zs, valid, S.Sampler(vol, level=args.level), sampler(fvol, args.fine_level),
                   sampler(fvol, args.reg_level), M, axis=axis, recto_sign=args.recto_sign, target=args.target,
                   face_sigma=args.face_sigma, opts=opts)
    res = as_label_result(fr)
    t_snap = time.time() - t0
    label_shape, scale = None, 1.0
    if not args.no_label:
        if not 0 <= args.label_level < len(vol.levels):
            raise S.SnapError(f"--label-level {args.label_level}: the volume has {len(vol.levels)} levels")
        label_shape = vol.shape(args.label_level)
        scale = L.level_scale(vol, args.label_level)
    desc = {"location": str(args.volume), "level": int(args.level), "shape_zyx": vol.shape(0),
            "axis": axis[0] if axis else None, "recto_sign": args.recto_sign,
            "fine": {"location": str(args.fine), "level": int(args.fine_level), "reg_level": int(args.reg_level),
                     "matrix": M.tolist(), "matrix_file": str(args.matrix), "inverted": bool(args.matrix_inverse)}}
    extra = {"seconds": {"snap": round(t_snap, 2)}, "finesnap": {"version": VERSION, "report": res["report"]["finesnap"]}}
    rec = L.write_outputs(out, args.surface, res, desc, label_shape, scale, args.label_level, args.ignore_halo,
                          args.label_step, args.review_min, args.review_max, extra, xs, ys, zs)
    L._write_grid_tif(out / "source.tif", fr["source"])
    rec["seconds"]["total"] = round(time.time() - t0, 2)
    (out / "labelsnap.json").write_text(json.dumps(rec, indent=1, default=float))
    return rec


def build_parser(p):
    sub = p.add_subparsers(dest="finesnap_cmd", required=True)
    s = sub.add_parser("snap", help="snap one tifxyz surface label onto the recto face seen in a finer registered scan")
    s.add_argument("surface", help="tifxyz folder in the coarse volume's level-0 voxels")
    s.add_argument("--volume", required=True, help="the CT the label lives in (coarse): OME-Zarr folder or URL")
    s.add_argument("--fine", required=True, help="a finer scan of the same scroll: OME-Zarr folder or URL")
    s.add_argument("--matrix", required=True, help="coarse level-0 xyz to fine level-0 xyz: a VC3D transform.json, "
                   "{\"matrix\": ...} or a 3 x 4 list")
    s.add_argument("--matrix-inverse", action="store_true", help="the file maps fine to coarse: invert it")
    s.add_argument("--fine-level", type=int, default=1,
                   help="fine level the faces are read at, near half the coarse voxel (1 for 2.399 um under 9.362)")
    s.add_argument("--reg-level", type=int, default=2,
                   help="fine level the registration reads, near the coarse voxel (2 for 2.399 um under 9.362)")
    s.add_argument("--opts", help="snap_fine options as JSON (default: the tested setting, finesnap.DEFAULTS)")
    s.add_argument("--level", type=int, default=0, help="coarse pyramid level the coarse snap reads")
    s.add_argument("--out", required=True, help="output folder (created; existing products are refused)")
    s.add_argument("--umbilicus", help="umbilicus JSON naming the scroll axis (kit snap's format)")
    s.add_argument("--umbilicus-scale", type=float, default=1.0)
    s.add_argument("--axis-point", nargs=3, type=float, metavar=("X", "Y", "Z"))
    s.add_argument("--axis-dir", nargs=3, type=float, metavar=("X", "Y", "Z"))
    s.add_argument("--recto-sign", type=float, choices=(1.0, -1.0))
    s.add_argument("--target", choices=("recto",), default="recto", help="the recto face (the only target tested)")
    s.add_argument("--face-sigma", type=float, default=L.DEFAULTS["face_sigma"])
    s.add_argument("--no-label", action="store_true", help="skip the OME-Zarr surface label")
    s.add_argument("--label-level", type=int, default=0)
    s.add_argument("--ignore-halo", type=float)
    s.add_argument("--label-step", type=float, default=L.DEFAULTS["label_step"])
    s.add_argument("--review-min", type=int, default=L.DEFAULTS["review_min"])
    s.add_argument("--review-max", type=int, default=L.DEFAULTS["review_max"])
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("check", help="check one output folder (kit labelsnap check, plus source.tif)")
    c.add_argument("out")
    c.add_argument("--json", action="store_true")


def check_outputs(out):
    from pathlib import Path
    probs = L.check_outputs(out)
    p = Path(out) / "source.tif"
    if not p.is_file():
        return probs + ["missing: source.tif"]
    src = L._read_grid_tif(p)
    ab = L._read_grid_tif(Path(out) / "abstain.tif") if (Path(out) / "abstain.tif").is_file() else None
    if ab is not None and src.shape != ab.shape:
        probs.append(f"source.tif is {src.shape}, the mesh grid is {ab.shape}")
    elif not set(_np().unique(src).tolist()) <= {0, 1, 2}:
        probs.append("source.tif holds values other than 0, 1 and 2")
    return probs


def cmd_finesnap(args):
    import json
    import sys
    try:
        if args.finesnap_cmd == "snap":
            rec = run_snap(args)
            probs = check_outputs(args.out)
            if args.json:
                print(json.dumps(rec, indent=1, default=float))
            else:
                v, f = rec["vertices"], rec["finesnap"]["report"]
                print(f"finesnap: {f['frac_registered']:.3f} of vertices registered to the fine scan; "
                      f"{f['frac_fine']:.3f} placed by the fine snap, {f['frac_coarse_fallback']:.3f} by the coarse "
                      f"snap; {v['abstained']} of {v['valid']} abstained; wrote {args.out}")
            if probs:
                print("kit finesnap: the outputs fail their own check:\n  " + "\n  ".join(probs), file=sys.stderr)
                return 1
            return 0
        probs = check_outputs(args.out)
        if args.json:
            print(json.dumps({"out": args.out, "ok": not probs, "problems": probs}, indent=1))
        else:
            print("finesnap check: " + ("ok" if not probs else "FAILED\n  " + "\n  ".join(probs)))
        return 0 if not probs else 1
    except (S.SnapError, L.LabelSnapError) as exc:
        print(f"kit finesnap: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="python -m kit finesnap", description=__doc__.split("\n")[0])
    build_parser(p)
    return cmd_finesnap(p.parse_args(argv))
