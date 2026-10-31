"""Ink offset diagnostic: how much an ink model's AUC changes when a segment's surface moves along its normal.

    python3 scripts/offsetdiag/offsetdiag.py fetch KEY --work WORK
    python3 scripts/offsetdiag/offsetdiag.py validate KEY ROW COL --work WORK
    python3 scripts/offsetdiag/offsetdiag.py render KEY --work WORK
    python3 scripts/offsetdiag/offsetdiag.py measure KEY --work WORK
    python3 scripts/offsetdiag/offsetdiag.py arms KEY --work WORK
    bash scripts/offsetdiag/infer.sh CHECKPOINT WORK MODEL          # on a CUDA machine with villa installed
    python3 scripts/offsetdiag/offsetdiag.py score --work WORK --model MODEL

fetch downloads the segment's published mesh, ink labels and the published surface volume's box (arm P0). render
samples the scan along the mesh normal at 44 whole-voxel offsets; measure finds, on an 8 px grid, the offset of villa's
lasagna cos maximum nearest the mesh (the sheet center); arms cuts 28-layer stacks from the render: constant shifts,
SNAP to the sheet center, and its same-size controls ANTI and RAND. villa's ink inference maps every arm in both depth
directions, and score gives each arm's AUC with the reverse-depth control and its difference to R0. Every map is
model output, not a reading.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import oddata as D  # noqa: E402
import odarms  # noqa: E402
import odgeom as G  # noqa: E402

VERSION = "1.0.0"
VALIDATE_OFFSETS = np.arange(-18, 18.01, 0.5)
COS_OFFSETS = np.arange(-12, 12.01, 0.25)


def _style():
    if sys.stdout.isatty():                  # the Scrolls look (AGENTS.md, terminal look rule)
        try:
            from kit import termstyle
            termstyle.script()
        except ImportError:
            pass


def say(*a):
    print(*a, flush=True)


def _seg(a):
    return D.segment(a.key, a.segments)


def _scan(seg, work):
    return D.Zarr2(seg["scan"], cache=Path(work) / "cache")


def _mesh(work, key):
    d = Path(work) / "mesh" / key
    if not (d / "x.tif").exists():
        raise D.DataError(f"no mesh in {d}; run fetch {key} first")
    return G.load_mesh(d)


def _p0(work, key):
    p = Path(work) / "arms" / key / "P0.zarr"
    if not p.exists():
        raise D.DataError(f"no published box at {p}; run fetch {key} first")
    return odarms.read_zarr(p)


def cmd_fetch(a):
    from kit import fetch
    seg = _seg(a)
    work = Path(a.work)
    base = D.OPEN_DATA
    root = seg["segment"].rstrip("/")
    n, got, size = fetch.fetch_prefix(f"{root}/{seg['mesh']}", work / "mesh" / a.key, base=base)
    say(f"mesh: {n} files, {got} bytes fetched")
    for name in ("inklabels.zarr", "supervision.zarr"):
        dest = work / "labels" / a.key / name
        fetch.fetch_prefix(f"{root}/{seg['labels']}/{name}/2", dest / "2", base=base)
        meta = D.http_get(f"{base}/{root}/{seg['labels']}/{name}/zarr.json")
        if meta is None:
            meta = D.http_get(f"{base}/{root}/{seg['labels']}/{name}/.zgroup")
            if meta is None:
                raise D.DataError(f"no zarr metadata for {root}/{seg['labels']}/{name}")
            (dest / ".zgroup").write_bytes(meta)
        else:
            (dest / "zarr.json").write_bytes(meta)
    say(f"labels: level 2 of inklabels.zarr and supervision.zarr in {work / 'labels' / a.key}")
    y0, y1, x0, x1 = seg["box"]
    sv = D.Zarr2(f"{base}/{root}/{seg['surface_volume']}")
    if tuple(sv.shape[1:]) != tuple(seg["shape"]):
        raise D.DataError(f"surface volume shape {sv.shape} does not match the segment's {seg['shape']}")
    box = sv.read_box((0, y0, x0), (sv.shape[0], y1, x1))
    odarms.write_zarr(work / "arms" / a.key / "P0.zarr", box)
    say(f"P0: published surface volume box {list(box.shape)} in {work / 'arms' / a.key / 'P0.zarr'}")
    return 0


def cmd_validate(a):
    seg = _seg(a)
    y0, y1, x0, x1 = seg["box"]
    n = a.size
    pub = _p0(a.work, a.key)[:, a.row:a.row + n, a.col:a.col + n].astype(np.float32)
    if pub.shape[1:] != (n, n):
        raise D.DataError(f"tile {a.row}, {a.col} of size {n} leaves the {y1 - y0} x {x1 - x0} box")
    t = time.time()
    img = G.render(_mesh(a.work, a.key), _scan(seg, a.work), VALIDATE_OFFSETS, (y0 + a.row, y0 + a.row + n),
                   (x0 + a.col, x0 + a.col + n), seg["normal_sign"])
    mid = int(np.argmin(np.abs(VALIDATE_OFFSETS)))
    mask = (img[mid] > 0) & (pub[pub.shape[0] // 2] > 0)
    if mask.sum() < 100:
        raise D.DataError(f"only {int(mask.sum())} valid pixels in the tile; pick a tile on the labeled surface")
    best = G.match_layers(pub, img, VALIDATE_OFFSETS, mask)
    ok = G.check_layers(best, pub.shape[0])
    rec = {"key": a.key, "row": a.row, "col": a.col, "size": n, "valid_px": int(mask.sum()),
           "layers": [{"layer": j, "best_offset": o, "r": r} for j, o, r in best], "pass": ok,
           "seconds": round(time.time() - t, 1)}
    out = Path(a.work) / "render" / f"{a.key}_validate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    for j, o, r in best:
        if j % 3 == 0 or j in (13, 14):
            say(f"layer {j:2d}: best offset {o:+5.1f} (expected {j - (pub.shape[0] - 1) / 2:+5.1f}), r {r:.3f}")
    say(("PASS" if ok else "FAIL") + f": {out}")
    return 0 if ok else 1


def cmd_render(a):
    seg = _seg(a)
    y0, y1, x0, x1 = seg["box"]
    offs = G.stack_offsets(seg["layers"], odarms.MAX_SHIFT)
    t = time.time()
    img = G.render(_mesh(a.work, a.key), _scan(seg, a.work), offs, (y0, y1), (x0, x1), seg["normal_sign"],
                   log=lambda s: say(f"{a.key} {s} ({time.time() - t:.0f} s)"))
    out = Path(a.work) / "render" / f"{a.key}.npy"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.save(out, np.clip(np.rint(img), 0, 255).astype(np.uint8))
    say(f"DONE {out} {list(img.shape)} offsets {offs[0]} to {offs[-1]}")
    return 0


def cmd_measure(a):
    seg = _seg(a)
    y0, y1, x0, x1 = seg["box"]
    t = time.time()
    cos = D.Zarr2(seg["cos"], cache=Path(a.work) / "cache")
    prof, ok = G.cos_profiles(_mesh(a.work, a.key), cos, (y0, y1), (x0, x1), COS_OFFSETS, seg["normal_sign"],
                              seg["cos_scale"], odarms.STRIDE)
    d = G.nearest_peak(prof, COS_OFFSETS)
    out = Path(a.work) / "render" / f"{a.key}_cos.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, cos=prof.astype(np.uint8), ok=ok, ts=COS_OFFSETS, d=d)
    v = d[ok]
    found = float(np.isfinite(v).mean()) if v.size else 0.0
    pct = np.nanpercentile(v, [5, 25, 50, 75, 95]).round(2).tolist() if np.isfinite(v).any() else None
    say(f"{a.key}: {int(ok.sum())} points, peak found at {found:.3f}, offset percentiles 5 25 50 75 95: {pct} "
        f"({time.time() - t:.0f} s) -> {out}")
    return 0


def cmd_arms(a):
    seg = _seg(a)
    work = Path(a.work)
    src = work / "render" / f"{a.key}.npy"
    cosf = work / "render" / f"{a.key}_cos.npz"
    for p, step in ((src, "render"), (cosf, "measure")):
        if not p.exists():
            raise D.DataError(f"no {p}; run {step} {a.key} first")
    big = np.load(src)
    H, W = big.shape[1:]
    valid = big[big.shape[0] // 2 - 1] > 0        # offset -0.5, the layer next to the surface
    c = np.load(cosf)
    field, stats = odarms.shift_field(c["d"], c["ok"], (H, W))
    shifts = odarms.arm_shifts(field, valid)
    pub = _p0(a.work, a.key)
    rec = {"key": a.key, "shape": [H, W], "lasagna": stats, "arms": {}}
    for name, r in shifts.items():
        arr = odarms.take(big, r, seg["layers"])
        odarms.write_zarr(work / "arms" / a.key / f"{name}.zarr", arr)
        rec["arms"][name] = odarms.shift_summary(r, valid)
        if name == "R0" and pub.shape == arr.shape:
            m = valid & (pub[pub.shape[0] // 2] > 0)
            rec["r0_vs_published_corr"] = odarms.layer_corr(arr, pub, m)
        say(a.key, name, json.dumps(rec["arms"][name]))
    out = work / "arms" / a.key / "arms.json"
    out.write_text(json.dumps(rec, indent=1))
    say(json.dumps({k: v for k, v in rec.items() if k != "arms"}))
    return 0


def cmd_score(a):
    import odscore
    table = D.segments(a.segments)
    keys = a.keys or list(D.SEGMENTS)
    work = Path(a.work)
    out = {}
    for model in a.model:
        for key in keys:
            if key not in table:
                raise D.DataError(f"unknown segment {key!r}")
            seg = table[key]
            rows = odscore.score_segment(work / "maps", model, key, work / "labels" / key, seg["shape"], seg["box"],
                                         ("P0",) + odarms.ARMS, a.draws, a.seed,
                                         log=lambda *r: say(r[0], r[1], r[2], json.dumps(r[3])))
            for arm, row in rows.items():
                out[f"{model} {key} {arm}"] = row
    if not out:
        raise D.DataError(f"no maps named MODEL_KEY_ARM.tif in {work / 'maps'}")
    dest = Path(a.out) if a.out else work / "scores.json"
    dest.write_text(json.dumps(out, indent=1))
    say(f"{len(out)} maps scored -> {dest}")
    return 0


def parser():
    p = argparse.ArgumentParser(prog="offsetdiag.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(s, key=True):
        if key:
            s.add_argument("key", help="segment key: 0841-w00, 0841-ag896, or one from --segments")
        s.add_argument("--work", default=os.environ.get("OFFDIAG_WORK", "."),
                       help="work folder for caches, meshes, labels, renders, arms and maps (default $OFFDIAG_WORK "
                            "or the current folder)")
        s.add_argument("--segments", help="JSON file of extra segments (see the tool page)")
        return s

    common(sub.add_parser("fetch", help="download the mesh, labels and published box (P0)"))
    s = common(sub.add_parser("validate", help="check the normal and layer convention on one tile against P0"))
    s.add_argument("row", type=int, help="tile row inside the box")
    s.add_argument("col", type=int, help="tile column inside the box")
    s.add_argument("--size", type=int, default=128, help="tile size in px (default 128)")
    common(sub.add_parser("render", help="render the box at 44 whole-voxel offsets along the normal"))
    common(sub.add_parser("measure", help="offset of villa's lasagna cos maximum nearest the mesh, 8 px grid"))
    common(sub.add_parser("arms", help="write the 28-layer arms as zarr groups"))
    s = common(sub.add_parser("score", help="score every arm's map with its reverse-depth control"), key=False)
    s.add_argument("--model", action="append", required=True,
                   help="model name used in the map file names MODEL_KEY_ARM.tif (repeatable)")
    s.add_argument("--keys", nargs="+", help="segment keys (default 0841-w00 0841-ag896)")
    s.add_argument("--draws", type=int, default=1000, help="bootstrap draws for arm minus R0 (default 1000)")
    s.add_argument("--seed", type=int, default=20261030, help="bootstrap seed (default 20261030)")
    s.add_argument("--out", help="scores file (default WORK/scores.json)")
    return p


COMMANDS = {"fetch": cmd_fetch, "validate": cmd_validate, "render": cmd_render, "measure": cmd_measure,
            "arms": cmd_arms, "score": cmd_score}


def main(argv=None):
    _style()
    a = parser().parse_args(argv)
    from kit.verify import VerifyError
    try:
        return COMMANDS[a.cmd](a)
    except (D.DataError, VerifyError, ValueError) as e:
        print(f"offsetdiag.py: error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
