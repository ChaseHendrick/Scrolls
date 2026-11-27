"""Community surface tables for the Segment Atlas: ATLAS-15k's recto surface patches, measured like published meshes.

  python -m kit atlascomm build OUT [--measure SCROLL ...] [--limit N] [--shards I ...] [--revision REV]

ATLAS-15k (Qual, 27 Nov 2026, https://huggingface.co/datasets/Qualzz20/ATLAS-15k, CC BY-NC 4.0) holds 14,678 recto
surface patches on 28 open-data scrolls: per patch an id, the scan, voxel size, bounding box, area, and x, y, z node
grids 2 voxels apart (-1 where empty). `build` reads its parquet shards one at a time and writes OUT/atlas-15k.csv
and OUT/atlas-15k.jsonl, one row per patch: the dataset's own metadata for every patch and, for the scrolls named by
--measure, the Segment Atlas numbers of kit.atlas.measure (area, isometry, holes, folds, stretched nodes, extents) on
the patch grid. Rows of other scrolls carry the metadata only, with `measured` false. Each shard is deleted once
read, so the disk holds one shard (about 480 MB) at a time.

It needs pyarrow and huggingface_hub (imported only by `build`). The table links the dataset and the public scans;
it copies no node grid.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

DATASET = "Qualzz20/ATLAS-15k"
REVISION = "ac4b982a1dc105a861e090ecb60cbff4578b5187"   # the revision read on 27 Nov 2026
SHARDS = 18
STEP_VX = 2.0                                          # the card: neighbouring nodes are 2 voxels apart
META = ("id", "scroll", "scan", "voxel_um", "size_vx", "centre_xyz", "box_min_xyz", "box_max_xyz", "area_cm2")
MEASURED = ("grid_h", "grid_w", "nodes_filled", "filled_share", "area_cm2_measured", "edge_p5", "edge_p50",
            "edge_p95", "within_10pct", "within_25pct", "median_abs_log", "angle_p5", "angle_p50", "angle_p95",
            "holes_nodes", "holes_mm2", "folds_nodes", "folds_mm2", "stretched_nodes", "stretched_mm2", "clean",
            "extent_x_mm", "extent_y_mm", "extent_z_mm")
COLUMNS = ("id", "scroll", "volume", "scan", "voxel_um", "size_x", "size_y", "centre_x", "centre_y", "centre_z",
           "box_min_x", "box_min_y", "box_min_z", "box_max_x", "box_max_y", "box_max_z", "area_cm2", "measured") \
    + MEASURED + ("error",)


class AtlasCommError(Exception):
    pass


def volume_of(scan):
    """The volume name in a scan URL (.../volumes/NAME.zarr/0), or the URL when it has none."""
    if "/volumes/" in scan:
        return scan.split("/volumes/")[1].split(".zarr")[0]
    return scan


def segment(x, y, z, voxel_um, source=""):
    """A kit.tifxyz Segment from one patch's x, y, z grids (rows of lists, -1 where no node)."""
    import numpy as np
    from . import tifxyz
    xyz = np.stack([np.asarray(x, np.float32), np.asarray(y, np.float32), np.asarray(z, np.float32)], -1)
    if xyz.ndim != 3:
        raise AtlasCommError(f"{source}: x, y and z must be 2D grids of one shape")
    valid = np.isfinite(xyz).all(-1) & (xyz > -0.5).all(-1)
    return tifxyz.Segment(xyz, valid, {"scale": [1 / STEP_VX, 1 / STEP_VX]}, source, voxel_um)


def row_of(rec, measure=False):
    """One table row from one dataset record: its metadata, and the atlas numbers when measure is true."""
    out = {k: None for k in COLUMNS}
    out.update(id=rec["id"], scroll=rec["scroll"], scan=rec["scan"], volume=volume_of(rec["scan"]),
               voxel_um=round(float(rec["voxel_um"]), 4), area_cm2=round(float(rec["area_cm2"]), 4), measured=False)
    out["size_x"], out["size_y"] = rec["size_vx"]
    for k, v in (("centre", rec["centre_xyz"]), ("box_min", rec["box_min_xyz"]), ("box_max", rec["box_max_xyz"])):
        out[f"{k}_x"], out[f"{k}_y"], out[f"{k}_z"] = v
    if measure:
        from . import atlas
        try:
            nums, _ = atlas.measure(segment(rec["x"], rec["y"], rec["z"], float(rec["voxel_um"]), rec["id"]))
            nums["area_cm2_measured"] = nums.pop("area_cm2")
            out.update({k: nums.get(k) for k in MEASURED})
            out["measured"] = True
        except Exception as exc:   # one bad patch must not stop the table
            out["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return out


def write(out_dir, rows):
    import csv
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "atlas-15k.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(out / "atlas-15k.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in COLUMNS})


def summary(rows):
    by = {}
    for r in rows:
        s = by.setdefault(r["scroll"], {"scroll": r["scroll"], "patches": 0, "area_cm2": 0.0, "measured": 0,
                                        "clean": 0})
        s["patches"] += 1
        s["area_cm2"] = round(s["area_cm2"] + (r["area_cm2"] or 0), 2)
        s["measured"] += bool(r["measured"])
        s["clean"] += bool(r.get("clean"))
    return [by[k] for k in sorted(by)]


def build(out_dir, measure=(), limit=None, shards=None, revision=REVISION, workdir=None):
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download
    measure = set(measure)
    rows, t0 = [], time.time()
    for i in (shards if shards is not None else range(SHARDS)):
        tmp = tempfile.mkdtemp(prefix="atlas-15k-", dir=workdir)
        try:
            path = hf_hub_download(DATASET, f"data/train-{i:05d}-of-{SHARDS:05d}.parquet", repo_type="dataset",
                                   revision=revision, cache_dir=tmp)
            pf = pq.ParquetFile(path)
            for batch in pf.iter_batches(batch_size=64):
                for rec in batch.to_pylist():
                    rows.append(row_of(rec, rec["scroll"] in measure))
                    if limit and len(rows) >= limit:
                        break
                if limit and len(rows) >= limit:
                    break
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"PROGRESS shard {i + 1}/{SHARDS}: {len(rows)} rows, {time.time() - t0:.0f} s", flush=True)
        if limit and len(rows) >= limit:
            break
    write(out_dir, rows)
    s = summary(rows)
    Path(out_dir, "atlas-15k-scrolls.json").write_text(json.dumps({"dataset": DATASET, "revision": revision,
                                                                   "license": "CC BY-NC 4.0", "scrolls": s},
                                                                  indent=1) + "\n")
    return rows


def build_parser(p):
    sub = p.add_subparsers(dest="atlascomm_cmd", required=True)
    b = sub.add_parser("build", help="read ATLAS-15k shard by shard and write the patch table")
    b.add_argument("out", help="output folder")
    b.add_argument("--measure", action="append", default=[], metavar="SCROLL",
                   help="measure the patch grids of this scroll (repeatable); others get metadata only")
    b.add_argument("--limit", type=int, help="stop after N rows (a test)")
    b.add_argument("--shards", type=int, nargs="+", help="only these shard numbers (0 to 17)")
    b.add_argument("--revision", default=REVISION, help="dataset revision (default: the one read on 27 Nov 2026)")
    b.add_argument("--workdir", help="where each shard is downloaded while it is read")
    return p


def cmd_atlascomm(args):
    try:
        rows = build(args.out, args.measure, args.limit, args.shards, args.revision, args.workdir)
    except (AtlasCommError, OSError) as exc:
        print(f"atlascomm: {exc}", file=sys.stderr)
        return 2
    m = sum(r["measured"] for r in rows)
    print(f"{len(rows)} rows ({m} measured) -> {args.out}")
    return 0


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit atlascomm", description=__doc__.splitlines()[0]))
    return cmd_atlascomm(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
