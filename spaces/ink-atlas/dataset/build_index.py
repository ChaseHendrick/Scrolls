"""Index tables for the public dataset SharpMeow/first-letters-ink-atlas, built from its own published files only.

  python3 spaces/ink-atlas/dataset/build_index.py DATASET_DIR [--out DIR]

DATASET_DIR is a local copy of the dataset (at least atlas.json, every surfaces/*/*/meta.json and preview.jpg). The
script reads nothing else and writes three things next to the existing files, moving or renaming none of them:

  metadata.jsonl           one row per picture under surfaces/ (every map, ensemble, CT layer and preview), keyed by
                           file_name; the Hub's image loader joins it to the pictures, so the Dataset Viewer and
                           load_dataset() show each picture with its surface, model, window, order and liveness
  surfaces/metadata.jsonl  one row per surface (provenance, canvas, coverage, alive models), joined to its
                           preview.jpg: the dataset's "surfaces" config
  index/surfaces.csv       the surface rows as a spreadsheet
  index/maps.csv           the picture rows as a spreadsheet

Values are copied from the published meta.json files; no map is opened or recomputed. The face check stays in each
meta.json and is not summarized here.
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

REPO = "SharpMeow/first-letters-ink-atlas"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/main/"
PX_CM2 = (9.6e-4) ** 2            # one 9.6 um canvas pixel, in cm2
METRICS = ("p50", "p99", "spread_p99_p50", "std", "fraction_near_half")
MAP_RANGE = (0.0, 1.0)            # 8-bit model maps: 0 to 255 stands for 0 to 1


def url(rel):
    return BASE + quote(rel)


def picture_rows(surface, meta):
    """One row per picture of one surface, in the dataset's own file order."""
    path, sid = surface["path"], surface["id"]
    zlo, zhi = meta.get("ensemble_png_z_range", [-2.0, 4.0])
    common = {"surface_id": sid, "scroll": surface["scroll"], "role": surface["role"]}
    files = list(meta["files"])
    for extra in ("ct_mid.png", "preview.jpg"):
        if extra not in files:
            files.append(extra)
    rows = []
    for rel in files:
        if not rel.endswith((".png", ".jpg")):
            continue
        row = dict(common, file_name=f"{path}/{rel}", kind=None, model=None, window=None,
                   window_offset_layers=None, order=None, stats_from=None, value_min=None, value_max=None,
                   alive=None, **{m: None for m in METRICS}, url=url(f"{path}/{rel}"))
        parts = rel.split("/")
        if parts[0] == "maps":
            model, stem = parts[1], parts[2][:-4]
            window, _, order = stem.rpartition("_")          # "c+0_s1", "forward"
            live = meta["models"][model]["liveness"].get(window, {}).get(order, {})
            row.update(kind="map", model=model, window=window.split("_")[0],
                       window_offset_layers=int(window.split("_")[0][1:]), order=order, value_min=MAP_RANGE[0], value_max=MAP_RANGE[1],
                       alive=live.get("verdict") == "ALIVE" if live else None,
                       **{m: live.get("metrics", {}).get(m) for m in METRICS})
        elif parts[0] in ("ensemble", "ensemble-rev"):
            order = parts[1][:-4]
            row.update(kind=parts[0], model="ensemble", order=order,
                       stats_from="forward" if parts[0] == "ensemble" else "reverse",
                       value_min=float(zlo), value_max=float(zhi))
        elif rel == "ct_mid.png":
            row.update(kind="ct")
        elif rel == "preview.jpg":
            row.update(kind="preview")
        else:
            continue
        rows.append(row)
    return rows


def surface_row(surface, meta):
    r = meta["render"]
    alive = [m for m, v in meta["models"].items() if v.get("alive")]
    return {
        "surface_id": surface["id"], "scroll": surface["scroll"], "role": surface["role"],
        "source": meta.get("source"), "scan": meta.get("scan"), "voxel_um": meta.get("voxel_um"),
        "canvas_um": meta.get("canvas_um"), "height_px": r["canvas_hw"][0], "width_px": r["canvas_hw"][1],
        "layers": r.get("layers"), "rendered_px": r.get("rendered_px"),
        "area_cm2": round(r["rendered_px"] * PX_CM2, 2) if r.get("rendered_px") else None,
        "models_alive": len(alive), "alive_models": ",".join(alive),
        "path": surface["path"], "meta_url": url(f"{surface['path']}/meta.json"),
        "preview_url": url(f"{surface['path']}/preview.jpg"),
        "mesh_url": meta.get("mesh", {}).get("base"), "ct_url": meta.get("ct"),
        "render_sha256": r.get("sha256"),
    }


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def _csv(path, rows):
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def build(root, out):
    root, out = Path(root), Path(out)
    atlas = json.loads((root / "atlas.json").read_text())
    pics, surfs = [], []
    for s in atlas["surfaces"]:
        meta = json.loads((root / s["path"] / "meta.json").read_text())
        if meta["id"] != s["id"] or meta["scroll"] != s["scroll"]:
            sys.exit(f"{s['path']}: meta.json says {meta['scroll']}/{meta['id']}, atlas.json {s['scroll']}/{s['id']}")
        pics += picture_rows(s, meta)
        surfs.append(surface_row(s, meta))
    _jsonl(out / "metadata.jsonl", pics)
    # the surfaces config: the image loader takes the preview pictures under surfaces/ with this file beside them
    _jsonl(out / "surfaces/metadata.jsonl",
           [dict(file_name=r["path"].split("/", 1)[1] + "/preview.jpg", **r) for r in surfs])
    _csv(out / "index/surfaces.csv", surfs)
    _csv(out / "index/maps.csv", pics)
    return {"pictures": len(pics), "surfaces": len(surfs), "maps": sum(r["kind"] == "map" for r in pics),
            "scrolls": len({r["scroll"] for r in surfs})}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", help="local copy of the dataset")
    ap.add_argument("--out", help="where to write (default: the copy itself)")
    a = ap.parse_args(argv)
    print(json.dumps(build(a.root, a.out or a.root)))


if __name__ == "__main__":
    main()
