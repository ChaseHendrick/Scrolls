"""Ink Lens's precomputed comparison: every model of zoo.py on every sample's whole 640 px crop, as Hugging Face Jobs.

The Space compares models live on what fits a ZeroGPU call; the gallery holds what does not: full crops for every
model, depth sweeps, Hecate's 3D volumes, and the two scan-space 3D models (gambiarra, DINO-guided), which read the
scan itself and cannot run inside a Space call. Three steps, each its own command:

  python tools/gallery_job.py flat --out DIR [--samples ID ...] [--models NAME ...] [--centres -4 0 4] [--steps 1 2]
      every 2.5D, Hecate and canonical model on each sample's 2.4 um crop (and the 9 um models also on the 9.4 um
      scan), in a GPU Job with torch and ink-sdk: maps, run record, Hecate depth profiles
  python tools/gallery_job.py ct3d --out DIR --ap ROOT [--samples ID ...] [--models NAME ...] [--device cuda]
      the scan-space 3D models in a Job with villa's ink code installed: AutoPipeline's public kit ink3d (ROOT is
      AutoPipeline's folder in a public Scrolls checkout) infers each model's volume over the CT the sample's crop
      reads, reads it onto the 2.4 um mesh within 15 um of the sheet, and builds the moved-sheet control
  python tools/gallery_job.py assemble --flat DIR --ct3d DIR --out GALLERY
      scores the 3D maps with the same scorer, writes the Space's gallery folder: scores.json, one PNG per map
      (centre window), mosaics of each sweep, stability maps, depth profiles

Maps are on the 9.6 um grid of the labels' level 2. Model output, not a reading; a score on a scroll a model trained
on shows the pipeline runs, nothing more (zoo.exposure says which).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPACE = HERE.parent
sys.path.insert(0, str(SPACE))

GRID_POOL = 4            # 2.4 um mesh pixels per 9.6 um grid pixel
CENTRES = (-4, 0, 4)     # 9.6 um layers from the middle of the 2.4 um scan's 27 pooled layers
STEPS = (1, 2)


def progress(i, n, what):
    print(f"PROGRESS {i}/{n} {what}", flush=True)


def _samples(ids):
    import inklens
    data = inklens.load_samples()
    out = [s for s in data["samples"] if s.get("scan24") and (not ids or s["id"] in ids)]
    if ids and len(out) != len(ids):
        raise SystemExit(f"unknown or 2.4-less samples among {ids}")
    return out


def _save_maps(path, maps):
    import numpy as np
    np.savez_compressed(path, **{"|".join(k): np.asarray(v, np.float16) for k, v in maps.items()})


def _load_maps(path):
    import numpy as np
    with np.load(path) as z:
        return {tuple(k.split("|")): z[k].astype(np.float32) for k in z.files}


# ---------------------------------------------------------------- flat: 2.5D, Hecate, canonical

def _smoke(a, models, size):
    """--smoke: one sample, a small square, one window, no interval, so a CPU run checks the whole path."""
    if a.smoke:
        a.size, a.samples = a.size or size, a.samples or ["0841-w00"]
        a.models = a.models or models
        if hasattr(a, "centres"):
            a.centres, a.steps, a.draws = [0], [1], 0


def cmd_flat(a):
    import compare
    import inklens
    import zoo
    _smoke(a, None, 128)
    if inklens.find_kit() is None:      # labels and the mesh come through this repository's kit/
        raise SystemExit("run from a Scrolls checkout: label scoring needs its kit/")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    names = a.models or [n for n in zoo.models() if zoo.get(n)["family"] != "ct3d"]
    samples = _samples(a.samples)
    loaded, n, i = {}, len(samples) * 2, 0
    for s in samples:
        info = {"id": s["id"], "scroll": s["scroll"], "segment": s["segment"]}
        if not a.no_orient:
            rep = orientation(s, out / "mesh" / s["id"])
            (out / f"{s['id']}_orient.json").write_text(json.dumps(rep, indent=1, default=str))
            print(f"  {s['id']} orientation: layer 0 on the {rep.get('layer0_face')} face, 9 um models' map that "
                  f"sees ink: {rep.get('recommended_primary') or rep.get('error') or rep.get('why')}", flush=True)
        for scan in ("2.4", "native"):
            i += 1
            these = names if scan == "2.4" else [m for m in names if zoo.get(m)["family"] == "villa9"]
            if not these:
                continue
            t0 = time.time()
            try:
                vol, lab, vinfo = compare.sample_inputs(s, scan, size=a.size)
            except Exception as exc:  # noqa: BLE001  (one sample failing never stops the others)
                print(f"  {s['id']} {scan}: {type(exc).__name__}: {exc}", flush=True)
                progress(i, n, f"{s['id']} {scan} failed")
                continue
            res, maps, vols = compare.run(vol, scan, these, labels=lab, centres=a.centres, steps=a.steps,
                                          loaded=loaded, device=a.device, output_3d=(scan == "2.4"),
                                          draws=a.draws, sample=dict(info, box=vinfo["box"], grid=vinfo["grid"]))
            stem = out / f"{s['id']}_{scan}"
            compare.record(res, f"{stem}.json")
            _save_maps(f"{stem}_maps.npz", maps)
            if lab is not None:
                import numpy as np
                np.savez_compressed(f"{stem}_labels.npz", ink=lab[0], sup=lab[1])
            for row in res["models"].values():
                print(f"  {s['id']} {scan} {row['model']}: {row.get('error') or row.get('skipped') or 'ok'}",
                      flush=True)
            progress(i, n, f"{s['id']} {scan} in {time.time() - t0:.0f} s")
    return 0


def orientation(s, mesh_dest):
    """ink-sdk's label-free depth-orientation check of the sample's 2.4 um scan (mesh + CT): which face of the sheet
    layer 0 is on, and which map its 9 um rule says sees ink. Reads the scan's layers lazily over HTTP."""
    try:
        import zarr
        from ink_sdk import orient as O
        from kit import fetch
        sc = s["scan24"]
        fetch.fetch_prefix(f"{s['scroll']}/segments/{s['segment']}/{sc['tifxyz']}", mesh_dest)
        mesh = next(Path(mesh_dest).rglob("x.tif")).parent
        base = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
        surf = f"{base}/{s['scroll']}/segments/{s['segment']}/{sc['surface_volume']}"
        O._open_layers = lambda v: zarr.open_group(str(v), mode="r")["0"]
        # T: CT voxels each side of the sheet; a 2.4 um render spans about 54, ink-sdk's default 16 suits 9 um
        return O.orient(mesh, surf, f"{base}/{sc['ct']}", adapter="ink9um", ct_level="0", T=64)
    except Exception as exc:  # noqa: BLE001  (the check fails closed)
        return {"layer0_face": "undetermined", "recommended_primary": None, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------- ct3d: scan-space 3D models through AP's kit ink3d

def _ct3d_spec(name, path):
    """kit ink3d's spec of a zoo ct3d model, its weights at `path` (already sha-checked by runners.fetch)."""
    import zoo
    z = zoo.get(name)
    if z["engine"] == "gambiarra":
        return {"engine": "gambiarra", "checkpoint": str(path), "map_factor": 2, "value_range": [0, 255],
                "native_um": 2.4, "licence": z["license"], "status": "experimental", "by": z["by"]}
    return {"engine": "villa-full3d", "checkpoint": str(path), "map_factor": 1, "value_range": [0, 255],
            "native_um": 2.4, "licence": z["license"], "status": "experimental", "by": z["by"], "batch": 2,
            "workers": 8}


def _fetch_mesh(s, dest):
    """The sample's 2.4 um tifxyz mesh (x, y, z TIFFs and meta.json) from the open-data bucket."""
    from kit import fetch
    sc = s["scan24"]
    fetch.fetch_prefix(f"{s['scroll']}/segments/{s['segment']}/{sc['tifxyz']}", dest)
    found = [p.parent for p in Path(dest).rglob("x.tif")]
    if len(found) != 1:
        raise SystemExit(f"{s['id']}: expected one tifxyz under {dest}, found {found}")
    return found[0]


def crop_canvas(ink3d, box, full_shape):
    """Make kit ink3d read only the crop: its canvas becomes the crop's 2.4 um pixels (box on the 9.6 um grid, times
    4), every point lookup offset by the crop's corner. Returns the crop's (H, W)."""
    y0, y1, x0, x1 = (GRID_POOL * int(v) for v in box)
    shape = (y1 - y0, x1 - x0)
    orig_canvas, orig_points = ink3d.canvas, ink3d.points

    def canvas(mesh, render=None):
        M, full = orig_canvas(mesh, render)
        if tuple(full) != tuple(full_shape):
            raise SystemExit(f"the mesh canvas {full} is not the 2.4 um scan's {full_shape}")
        return M, shape

    def points(M, r0, r1, c0, c1):
        return orig_points(M, r0 + y0, r1 + y0, c0 + x0, c1 + x0)

    ink3d.canvas, ink3d.points = canvas, points
    return shape


def cmd_ct3d(a):
    import numpy as np
    import tifffile
    import runners
    import zoo
    ap = Path(a.ap).resolve()
    sys.path.insert(0, str(ap))
    os.environ.setdefault("KIT_INK_PYTHON", sys.executable)
    from kit import ink3d
    _smoke(a, ["gambiarra-3d"], 32)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    names = a.models or [n for n in zoo.models() if zoo.get(n)["family"] == "ct3d"]
    samples = _samples(a.samples)
    weights = {n: runners.fetch(n) for n in names}
    n, i = len(samples) * len(names), 0
    for s in samples:
        sc = s["scan24"]
        mesh = _fetch_mesh(s, out / "mesh" / s["id"])
        ct = f"https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/{sc['ct']}"
        render = f"https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/{s['scroll']}/segments/" \
                 f"{s['segment']}/{sc['surface_volume']}"
        box = sc["crop"]
        if a.size:      # a smaller square around the crop's centre (smoke runs)
            cy, cx, h = (box[0] + box[1]) // 2, (box[2] + box[3]) // 2, a.size // 2
            box = [cy - h, cy - h + a.size, cx - h, cx - h + a.size]
        for name in names:
            i += 1
            t0 = time.time()
            dest = out / s["id"] / name
            rec = {"model": name, "sample": s["id"], "box": box}
            saved = (ink3d.canvas, ink3d.points)
            try:
                crop_canvas(ink3d, box, sc["level0_shape"])
                ink3d.register(name, _ct3d_spec(name, weights[name]))
                r = ink3d.run(name, str(mesh), render, ct, float(sc["um_per_px"]), dest, device=a.device)
                f = tifffile.imread(dest / "ink_f.tif")
                c = tifffile.imread(dest / "ink_r.tif")
                dec = [np.where(m == 0, np.nan, (m.astype(np.float32) - 1) / 65534.0) for m in (f, c)]
                grid = [runners.pool_map(m, GRID_POOL) for m in dec]
                np.savez_compressed(out / f"{s['id']}_{name}.npz", forward=grid[0].astype(np.float16),
                                    control=grid[1].astype(np.float16))
                rec.update(record=r, seconds=round(time.time() - t0, 1))
            except Exception as exc:  # noqa: BLE001  (one model failing never hides the others)
                rec["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            finally:
                ink3d.canvas, ink3d.points = saved
            (out / f"{s['id']}_{name}.json").write_text(json.dumps(rec, indent=1, default=str))
            progress(i, n, f"{s['id']} {name}: {rec.get('error', 'ok')} in {time.time() - t0:.0f} s")
    return 0


# ---------------------------------------------------------------- assemble: the Space's gallery folder

def _png(path, rgb):
    from PIL import Image
    Image.fromarray(rgb).save(path, optimize=True)


def cmd_assemble(a):
    import numpy as np
    import compare
    import inklens
    import zoo
    inklens.find_kit()
    flat, ct3d, out = Path(a.flat), Path(a.ct3d) if a.ct3d else None, Path(a.out)
    (out / "maps").mkdir(parents=True, exist_ok=True)
    index = {"tool": f"Ink Lens gallery {compare.VERSION}", "grid_um": compare.GRID_UM, "samples": {},
             "note": compare.NOTE, "made": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    for rec_path in sorted(flat.glob("*_2.4.json")):
        sid = rec_path.name[:-len("_2.4.json")]
        res = json.loads(rec_path.read_text())
        maps = _load_maps(flat / f"{sid}_2.4_maps.npz")
        lab = np.load(flat / f"{sid}_2.4_labels.npz")
        labels = (lab["ink"], lab["sup"])
        valid = np.ones(labels[0].shape, bool)
        scroll = res["sample"]["scroll"]
        # the scan-space 3D models, scored by the same scorer against their moved-sheet control
        for f in sorted(ct3d.glob(f"{sid}_*.json")) if ct3d else []:
            name = f.stem[len(sid) + 1:]
            rec = json.loads(f.read_text())
            spec = zoo.get(name)
            row = {"model": name, "title": spec["title"], "by": spec["by"], "family": "ct3d",
                   "license": spec["license"], "control": compare.control_note(name)}
            st, why, src = zoo.exposure(name, scroll)
            row["exposure"] = {"scroll": scroll, "status": st, "why": why, "source": src}
            if rec.get("error"):
                row["error"] = rec["error"]
            else:
                z = np.load(ct3d / f"{sid}_{name}.npz")
                fm, cm = (z[k].astype(np.float32) for k in ("forward", "control"))
                h, w = labels[0].shape
                fm, cm = fm[:h, :w], cm[:h, :w]
                maps[(name, "c+0_s1", "forward")], maps[(name, "c+0_s1", "reverse")] = fm, cm
                cell = {"liveness": {"forward": compare.liveness(fm, np.isfinite(fm)),
                                     "reverse": compare.liveness(cm, np.isfinite(cm))},
                        "score": compare.score(fm, labels[0], labels[1], control=cm, draws=a.draws)}
                row.update(cells={"c+0_s1": cell}, seconds=rec.get("seconds"),
                           alive=cell["liveness"]["forward"]["verdict"] == "ALIVE",
                           ink3d={k: rec["record"].get(k) for k in ("pitch", "grid", "half_um", "control_shift_um",
                                                                    "targets", "warnings")})
            res["models"][name] = row
        o = flat / f"{sid}_orient.json"
        if o.is_file():
            res["orientation"] = json.loads(o.read_text())
        native = flat / f"{sid}_native.json"
        if native.is_file():
            res["native_scan"] = {n: r.get("cells", {}).get("c+0_s1", {}).get("score")
                                  for n, r in json.loads(native.read_text())["models"].items()}
        order = [n for n in res["models"] if (n, "c+0_s1", "forward") in maps]
        for (n, k, o), m in maps.items():
            if k == "c+0_s1" or n == "stability":
                img = compare.to_rgb(m, "stretched" if n == "ensemble" else "absolute")
                _png(out / "maps" / f"{sid}__{n}__{k}__{o}.png", img)
        cols = sorted({(k, o) for (n, k, o) in maps if n in res["models"] and k.startswith("c")},
                      key=lambda t: (t[1] != "forward", int(t[0].split("_s")[1]), int(t[0][1:].split("_")[0])))
        _png(out / f"{sid}__mosaic.png", compare.mosaic(maps, order, cols, labels=labels))
        res["mosaic"] = {"rows": order, "columns": [f"{k} {o}" for k, o in cols]}
        res["table"] = compare.table(res)
        index["samples"][sid] = {"scroll": scroll, "record": f"{sid}.json", "mosaic": f"{sid}__mosaic.png",
                                 "models": order}
        compare.record(res, out / f"{sid}.json")
        print(res["table"], flush=True)
    (out / "index.json").write_text(json.dumps(index, indent=1))
    return 0


def parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("flat")
    f.add_argument("--out", required=True)
    f.add_argument("--samples", nargs="*")
    f.add_argument("--models", nargs="*")
    f.add_argument("--centres", nargs="*", type=int, default=list(CENTRES))
    f.add_argument("--steps", nargs="*", type=int, default=list(STEPS))
    f.add_argument("--device", default=None)
    f.add_argument("--draws", type=int, default=300)
    f.add_argument("--no-orient", action="store_true", help="skip ink-sdk's depth-orientation check")
    f.add_argument("--size", type=int, help="a square this many 9.6 um px around the crop's centre (smoke runs)")
    f.add_argument("--smoke", action="store_true", help="one sample, 128 px, one window: a CPU check of the path")
    c = sub.add_parser("ct3d")
    c.add_argument("--out", required=True)
    c.add_argument("--ap", required=True, help="AutoPipeline's folder (holding kit/ink3d.py) in a public checkout")
    c.add_argument("--samples", nargs="*")
    c.add_argument("--models", nargs="*")
    c.add_argument("--device", default="cuda")
    c.add_argument("--size", type=int, help="a square this many 9.6 um px around the crop's centre (smoke runs)")
    c.add_argument("--smoke", action="store_true", help="one sample, 32 px, the gambiarra model: a CPU check")
    s = sub.add_parser("assemble")
    s.add_argument("--flat", required=True)
    s.add_argument("--ct3d")
    s.add_argument("--out", required=True)
    s.add_argument("--draws", type=int, default=300)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    return {"flat": cmd_flat, "ct3d": cmd_ct3d, "assemble": cmd_assemble}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
