"""Preview pictures for the villa fields in the open data, which ship none: a slice through the middle of the scroll
(xy) and one along it (xz), cos beside the normals as color, read over HTTPS from each field's run folder.

  python3 spaces/lasagna-fields/make_previews.py OUT_DIR

writes OUT_DIR/SCROLL-VOLUME-xy.webp and -xz.webp (at most 1,600 px) for every open-data row of fields.json; upload OUT_DIR as the Space's
assets/previews/ (pictures stay out of git). Needs numpy, pillow, zarr<3, fsspec and aiohttp. Model output: a
picture of villa's lasagna field, never a reading.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import zarr
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent


def normals_rgb(nx_u8, ny_u8, cos_u8):
    """Encoded normals (v * 127 + 128) as color: |x|, |y|, z to red, green, blue; black where cos holds no data
    (villa's open-data fields store 218 in both normals there, not their arrays' fill value)."""
    nx = (nx_u8.astype(np.float32) - 128.0) / 127.0
    ny = (ny_u8.astype(np.float32) - 128.0) / 127.0
    nz = np.sqrt(np.maximum(0.0, 1.0 - nx * nx - ny * ny))
    rgb = np.stack([np.abs(nx), np.abs(ny), nz], -1) * 255.0
    rgb[cos_u8 == 0] = 0
    return np.rint(rgb).clip(0, 255).astype(np.uint8)


def polish(cos, nrm, title, out, min_width=1000, max_width=1600, max_side=1600):
    """cos and normals side by side, cropped to the data, on a dark ground, with a title and a label over each."""
    occ = (cos > 0) | (nrm.max(-1) > 0)
    ys, xs = np.nonzero(occ)
    pad = max(4, int(0.02 * max(occ.shape)))
    y0, y1 = max(0, ys.min() - pad), min(occ.shape[0], ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(occ.shape[1], xs.max() + 1 + pad)
    panels = [Image.fromarray(np.ascontiguousarray(np.repeat(cos[y0:y1, x0:x1, None], 3, -1))),
              Image.fromarray(np.ascontiguousarray(nrm[y0:y1, x0:x1]))]
    gap, margin, head, lab = 24, 24, 56, 30
    pw = panels[0].width
    scale = min(max(1.0, min_width / (2 * pw + gap + 2 * margin)), max_width / (2 * pw + gap + 2 * margin))
    if scale != 1.0:
        size = (max(1, round(pw * scale)), max(1, round(panels[0].height * scale)))
        panels = [p.resize(size, Image.NEAREST if scale > 1 else Image.LANCZOS) for p in panels]
    pw, ph = panels[0].size
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    big = ImageFont.truetype(font, 22) if os.path.exists(font) else ImageFont.load_default()
    small = ImageFont.truetype(font, 16) if os.path.exists(font) else ImageFont.load_default()
    tw = ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(title, font=big)
    canvas = Image.new("RGB", (max(2 * pw + gap + 2 * margin, int(tw) + 1 + 2 * margin), head + lab + ph + margin),
                       (14, 17, 23))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 16), title, fill=(236, 238, 242), font=big)
    for i, (p, text, color) in enumerate(((panels[0], "cos (one band per papyrus layer)", (170, 200, 255)),
                                          (panels[1], "normals: red x, green y, blue z", (255, 190, 140)))):
        x = margin + i * (pw + gap)
        draw.text((x, head), text, fill=color, font=small)
        canvas.paste(p, (x, head + lab))
    if max(canvas.size) > max_side:                     # the media rule's 1920 px, with room
        canvas.thumbnail((max_side, max_side), Image.LANCZOS)
    canvas.save(out, quality=86, method=6)


def level_of(root, want=5):
    """The coarsest level up to want that the array has."""
    attrs = json.load(urllib.request.urlopen(root + "/.zattrs"))
    have = [int(d["path"]) for d in attrs["multiscales"][0]["datasets"]]
    return max(v for v in have if v <= want) if min(have) <= want else min(have)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [f for f in json.loads((HERE / "fields.json").read_text())["fields"] if f["source"] == "open-data"]
    for f in rows:
        m = json.load(urllib.request.urlopen(f["manifest"]))
        name = {k: m["groups"][k]["zarr"].split("/")[0] for k in ("cos", "nx", "ny")}
        lv = max(level_of(f"{f['stream']}/{name[k]}") for k in name)
        arr = {k: zarr.open(f"{f['stream']}/{name[k]}/{lv}", mode="r") for k in name}
        zc, yc = arr["cos"].shape[0] // 2, arr["cos"].shape[1] // 2
        views = {"xy": {k: np.asarray(a[zc]) for k, a in arr.items()},
                 "xz": {k: np.asarray(a[:, yc, :]) for k, a in arr.items()}}
        for view, v in views.items():
            title = f"{f['scroll']} {f['volume']}, villa predict3d, {'xy at mid z' if view == 'xy' else 'xz at mid y'}"
            polish(v["cos"], normals_rgb(v["nx"], v["ny"], v["cos"]), title, out / f"{f['scroll']}-{f['volume']}-{view}.webp")
        print(f"{f['scroll']} {f['volume']}: level {lv}, {arr['cos'].shape}", flush=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
