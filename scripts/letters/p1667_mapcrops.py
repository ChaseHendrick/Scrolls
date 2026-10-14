"""Cut PHerc. 1667's 2.4 um ink-detection maps at the letter groups of p1667_groups.py.

Each labelled segment's ink map (`ink-detection/PHerc1667-<id>-2.399um-...-volume-20251217075048-
...-new_canon_autoresearch_recipe-tile256-stride128.tif` in the open-data bucket) has exactly the
shape of its ink label's level 0, so the two share a grid. For every group this cuts the map over
the same padded box as the label crop (level 0, block-averaged by 16 to the groups' 38 um grid,
scaled to 0..1), so a reader sees the same window with the map in place of the drawing. Also
reports the alignment check: mean map value under labelled ink against the rest of the crops,
and the same for the label shifted by up to 3 grid pixels (the unshifted label should score best).

  python scripts/letters/p1667_mapcrops.py GROUPS_DIR MAPS_DIR
  python scripts/letters/p1667_mapcrops.py GROUPS_DIR MAPS_DIR --wide
MAPS_DIR holds <wNNN>.tif. Writes GROUPS_DIR/map-npy/<id>.npy and GROUPS_DIR/map-check.json.
With --wide it instead writes GROUPS_DIR/map-wide-npy/<id>.npy: the same window made WIDE_PAD_Y
letter heights taller above and below, so it holds the neighbouring lines and the reader has to
find the group's line itself (map-wide.json keeps where the group's line is, for checking only).
With --region it writes GROUPS_DIR/map-region-npy/<segment>.npy instead: the segment's whole
labelled frame (the box around all its labelled ink, several columns of about ten lines) padded
by REGION_PAD letter heights, read in bands to keep memory low; map-region.json keeps the padding.
"""
import json
import sys
from pathlib import Path

import numpy as np

from p1667_groups import D, PAD_X, PAD_Y

F = 2 * D      # level 0 pixels per grid pixel (labels were cut from level 1, block 8)
WIDE_PAD_Y = 2.0
REGION_PAD = 1.0
BAND = 16      # grid rows per band when cutting a whole region


def cut(z, r0, c0, ny, nx):
    """Map rows r0.. and columns c0.. (level 0) over ny x nx grid pixels, block-averaged, 0..1; zero off the map."""
    H0, W0 = z.shape
    out = np.zeros((ny * F, nx * F), np.float32)
    rr0, cc0 = max(0, r0), max(0, c0)
    rr1, cc1 = min(H0, r0 + ny * F), min(W0, c0 + nx * F)
    if rr1 > rr0 and cc1 > cc0:
        out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = np.asarray(z[rr0:rr1, cc0:cc1], np.float32) / 255.0
    return out.reshape(ny, F, nx, F).mean(axis=(1, 3))


def wide(groups_dir, maps_dir):
    import tifffile
    import zarr
    groups_dir, maps_dir = Path(groups_dir), Path(maps_dir)
    meta = json.loads((groups_dir / "groups.json").read_text())
    (groups_dir / "map-wide-npy").mkdir(exist_ok=True)
    where = {}
    for seg, st in meta["stats"].items():
        z = zarr.open(tifffile.imread(maps_dir / f"{seg}.tif", aszarr=True), mode="r")
        oy, ox = st["origin_level1"]
        h = st["letter_h"]
        for g in (g for g in meta["groups"] if g["segment"] == seg):
            y0, y1, x0, x1 = g["box"]
            py, px = int(round((PAD_Y + WIDE_PAD_Y) * h)), int(round(PAD_X * h))
            Y0, X0 = y0 - py, x0 - px
            ny, nx = (y1 - y0) + 2 * py, g["crop_shape"][1]
            m = cut(z, (oy + Y0 * D) * 2, (ox + X0 * D) * 2, ny, nx)
            np.save(groups_dir / "map-wide-npy" / f"{g['id']}.npy", m)
            where[g["id"]] = {"centre_y_in_window": g["centre_y"] + int(round(WIDE_PAD_Y * h)), "shape": list(m.shape)}
        print(seg, "done", flush=True)
    (groups_dir / "map-wide.json").write_text(json.dumps({"WIDE_PAD_Y": WIDE_PAD_Y, "groups": where}, indent=1) + "\n")


def main(groups_dir, maps_dir):
    import tifffile
    import zarr
    groups_dir, maps_dir = Path(groups_dir), Path(maps_dir)
    meta = json.loads((groups_dir / "groups.json").read_text())
    (groups_dir / "map-npy").mkdir(exist_ok=True)
    check = {}
    for seg, st in meta["stats"].items():
        z = zarr.open(tifffile.imread(maps_dir / f"{seg}.tif", aszarr=True), mode="r")
        H0, W0 = z.shape
        oy, ox = st["origin_level1"]
        h = st["letter_h"]
        inside, outside, shifted = [], [], {}
        for g in (g for g in meta["groups"] if g["segment"] == seg):
            y0, y1, x0, x1 = g["box"]
            py, px = int(round(PAD_Y * h)), int(round(PAD_X * h))
            Y0, X0 = y0 - py, x0 - px
            ny, nx = g["crop_shape"]
            r0, c0 = (oy + Y0 * D) * 2, (ox + X0 * D) * 2
            out = np.zeros((ny * F, nx * F), np.float32)
            rr0, cc0 = max(0, r0), max(0, c0)
            rr1, cc1 = min(H0, r0 + ny * F), min(W0, c0 + nx * F)
            if rr1 > rr0 and cc1 > cc0:
                out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = np.asarray(z[rr0:rr1, cc0:cc1], np.float32) / 255.0
            m = out.reshape(ny, F, nx, F).mean(axis=(1, 3))
            np.save(groups_dir / "map-npy" / f"{g['id']}.npy", m)
            lab = np.load(groups_dir / "npy" / f"{g['id']}.npy") > 0.5
            inside.append(m[lab]); outside.append(m[~lab])
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    s = np.roll(np.roll(lab, dy, axis=0), dx, axis=1)
                    shifted.setdefault((dy, dx), []).append(m[s])
        best = max(shifted, key=lambda k: float(np.concatenate(shifted[k]).mean()))
        check[seg] = {"map_under_labels": round(float(np.concatenate(inside).mean()), 3),
                      "map_elsewhere_in_crops": round(float(np.concatenate(outside).mean()), 3),
                      "best_shift_dy_dx": list(best),
                      "map_under_labels_best_shift": round(float(np.concatenate(shifted[best]).mean()), 3)}
        print(seg, check[seg], flush=True)
    (groups_dir / "map-check.json").write_text(json.dumps(check, indent=1) + "\n")


def region(groups_dir, maps_dir):
    import tifffile
    import zarr
    groups_dir, maps_dir = Path(groups_dir), Path(maps_dir)
    meta = json.loads((groups_dir / "groups.json").read_text())
    (groups_dir / "map-region-npy").mkdir(exist_ok=True)
    pads = {}
    for seg, st in meta["stats"].items():
        z = zarr.open(tifffile.imread(maps_dir / f"{seg}.tif", aszarr=True), mode="r")
        oy, ox = st["origin_level1"]
        R = int(round(REGION_PAD * st["letter_h"]))
        H, W = st["shape"][0] + 2 * R, st["shape"][1] + 2 * R
        m = np.concatenate([cut(z, (oy + (y - R) * D) * 2, (ox - R * D) * 2, min(BAND, H - y), W)
                            for y in range(0, H, BAND)])
        np.save(groups_dir / "map-region-npy" / f"{seg}.npy", m)
        pads[seg] = {"pad": R, "shape": list(m.shape)}
        print(seg, m.shape, flush=True)
    (groups_dir / "map-region.json").write_text(json.dumps({"REGION_PAD": REGION_PAD, "segments": pads}, indent=1) + "\n")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    mode = region if "--region" in sys.argv[3:] else wide if "--wide" in sys.argv[3:] else main
    mode(*sys.argv[1:3])
