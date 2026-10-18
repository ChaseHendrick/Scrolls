"""Cut PHerc. 1667's official ink labels into letter groups, for a letter-recognition test of the reader.

The official labels on the six labeled PHerc. 1667 segments (w013, w018, w023, w028, w029, w031;
open-data bucket, PHerc1667/segments/<segment>/ink-labels/2.399um-volume-20251217075048/20260918/
inklabels.zarr) are drawings of single letters and short runs of letters scattered over the
columns, not whole lines. This script turns each label into groups by a fixed rule that looks at
the drawing only, never at a reader's output:

1. Level 1 of the label (4.8 um per pixel), cropped to its ink, block-averaged by 8 (38 um per
   pixel); ink is the mean above 0.5.
2. Connected ink pieces of at least MIN_AREA pixels (letters are 1,300 px or more here; smaller
   pieces are stray marks).
3. h, the segment's letter height, is the median height of its pieces.
4. Pieces join one group when their vertical centers differ by less than 0.5 h and the horizontal
   gap between them is under 0.6 h (union over all pairs), so a group is one run of letters on
   one line.
5. Each group is read from a crop padded by PAD_X h left and right and PAD_Y h above and below,
   with the line center at the median of its pieces' vertical centers.

Outputs groups.json (segment, group id, box, center, h) and one PNG per group for the blind
transcription (black letters on white, 96 px per letter height). Model-free: run it before any
reader touches the data.

  python scripts/letters/p1667_groups.py LABELS_DIR OUT_DIR
LABELS_DIR holds <wNNN>/z/1 (a local copy of level 1 of each inklabels.zarr). Needs numpy, scipy, zarr
and Pillow.
"""
import json
from pathlib import Path

import numpy as np

D = 8
MIN_AREA = 500
V_JOIN, H_JOIN = 0.5, 0.6
PAD_X, PAD_Y = 1.0, 0.75
SEGMENTS = ("w013", "w018", "w023", "w028", "w029", "w031")


def downsample(path):
    try:
        import zarr
    except ImportError as exc:
        raise SystemExit(f"p1667_groups.py reads the ink labels with zarr ({exc}): python -m pip install -e \".[all]\" "
                         "(Python 3.11 or newer), or python -m pip install zarr") from None
    x = zarr.open_array(str(path), mode="r")
    full = np.asarray(x[:]) > 0
    rows, cols = np.nonzero(full.any(axis=1))[0], np.nonzero(full.any(axis=0))[0]
    y0, x0 = int(rows[0]), int(cols[0])
    H, W = ((rows[-1] + 1 - y0) // D) * D, ((cols[-1] + 1 - x0) // D) * D
    a = full[y0:y0 + H, x0:x0 + W].reshape(H // D, D, W // D, D).mean(axis=(1, 3)).astype(np.float32)
    return a, (y0, x0)


def groups_of(a):
    from scipy import ndimage as ndi
    m = a > 0.5
    lab, n = ndi.label(m)
    sl = ndi.find_objects(lab)
    area = ndi.sum(m, lab, range(1, n + 1))
    keep = [i for i in range(n) if area[i] >= MIN_AREA]
    box = {i: (sl[i][0].start, sl[i][0].stop, sl[i][1].start, sl[i][1].stop) for i in keep}
    h = float(np.median([b[1] - b[0] for b in box.values()]))
    parent = {i: i for i in keep}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for p in keep:
        for q in keep:
            if p < q:
                (a0, a1, b0, b1), (c0, c1, d0, d1) = box[p], box[q]
                gap = max(d0 - b1, b0 - d1, 0)
                if abs((a0 + a1) / 2 - (c0 + c1) / 2) < V_JOIN * h and gap < H_JOIN * h:
                    parent[find(p)] = find(q)
    out = {}
    for i in keep:
        out.setdefault(find(i), []).append(i)
    groups = []
    for members in out.values():
        y0 = min(box[i][0] for i in members); y1 = max(box[i][1] for i in members)
        x0 = min(box[i][2] for i in members); x1 = max(box[i][3] for i in members)
        cy = float(np.median([(box[i][0] + box[i][1]) / 2 for i in members]))
        groups.append({"box": [int(y0), int(y1), int(x0), int(x1)], "centre_y": cy, "pieces": len(members)})
    groups.sort(key=lambda g: (g["box"][0] // max(1, int(h)), g["box"][2]))   # rows of about one letter, then left to right
    return groups, h, len(keep), n - len(keep)


def crop(a, g, h):
    y0, y1, x0, x1 = g["box"]
    py, px = int(round(PAD_Y * h)), int(round(PAD_X * h))
    Y0, X0 = max(0, y0 - py), max(0, x0 - px)
    Y1, X1 = min(a.shape[0], y1 + py), min(a.shape[1], x1 + px)
    c = np.zeros((y1 - y0 + 2 * py, x1 - x0 + 2 * px), np.float32)
    c[Y0 - (y0 - py):Y0 - (y0 - py) + (Y1 - Y0), X0 - (x0 - px):X0 - (x0 - px) + (X1 - X0)] = a[Y0:Y1, X0:X1]
    return c, g["centre_y"] - (y0 - py)


def main(labels_dir, out_dir):
    from PIL import Image
    labels_dir, out_dir = Path(labels_dir), Path(out_dir)
    (out_dir / "png").mkdir(parents=True, exist_ok=True)
    (out_dir / "npy").mkdir(parents=True, exist_ok=True)
    rows, stats = [], {}
    for seg in SEGMENTS:
        a, origin = downsample(labels_dir / seg / "z" / "1")
        groups, h, kept, dropped = groups_of(a)
        stats[seg] = {"shape": list(a.shape), "origin_level1": list(origin), "letter_h": h, "pieces": kept,
                      "pieces_dropped_small": dropped, "groups": len(groups)}
        for k, g in enumerate(groups):
            gid = f"{seg}-g{k:03d}"
            c, cy = crop(a, g, h)
            np.save(out_dir / "npy" / f"{gid}.npy", c)
            f = 96.0 / h
            im = Image.fromarray(((1 - np.clip(c, 0, 1)) * 255).astype(np.uint8))
            im = im.resize((max(1, int(c.shape[1] * f)), max(1, int(c.shape[0] * f))), Image.LANCZOS)
            im.save(out_dir / "png" / f"{gid}.png")
            # centre_y is the line center in the crop's own rows (what the reader is given); the
            # segment's row stays as centre_y_segment. (Before 9 October's fix, **g overwrote it.)
            rows.append({"id": gid, "segment": seg, "letter_h": h, **g, "centre_y_segment": g["centre_y"],
                         "centre_y": cy, "crop_shape": list(c.shape)})
    (out_dir / "groups.json").write_text(json.dumps({"rule": {"D": D, "MIN_AREA": MIN_AREA, "V_JOIN": V_JOIN,
                                                               "H_JOIN": H_JOIN, "PAD_X": PAD_X, "PAD_Y": PAD_Y},
                                                      "stats": stats, "groups": rows}, indent=1) + "\n")
    print(json.dumps(stats, indent=1))
    print("groups", len(rows))


def parse_args(argv=None):
    """LABELS_DIR and OUT_DIR; anything else stops with the usage."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labels_dir", help="p1667_fetch.py's OUT/labels: <wNNN>/z/1 of each inklabels.zarr")
    ap.add_argument("out_dir", help="where groups.json, png/ and npy/ go, such as work/p1667/groups")
    return ap.parse_args(argv)


if __name__ == "__main__":
    a = parse_args()
    main(a.labels_dir, a.out_dir)
