"""Card pictures for the Every field tab: each field's xy preview (cos | normals; preview_xy in fields.json, a
dataset's preview-xy.png or, for villa's fields in the open data, the picture make_previews.py wrote) as a small 2:1
WebP (fitted whole, on black) under assets/thumbs/SCROLL-VOLUME.webp. The guide falls back to the preview itself when
a thumb is missing. Like the rest of assets/, the thumbs live on the Space, not in git.

  python3 spaces/lasagna-fields/make_thumbs.py OUT_DIR [PREVIEWS_DIR]   (then upload OUT_DIR as assets/thumbs/)

PREVIEWS_DIR, make_previews.py's output, is read before the Space has the open-data previews.
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 720, 360


def trim(im):
    """The picture without its title bar and empty margins: the panels are pure black where the field is empty, the
    title bar and labels sit on a dark gray canvas around them, so keep the black panels' box, then the content in it."""
    import numpy as np
    a = np.asarray(im).astype(int)
    canvas = a[0, 0].copy()
    black = (a.max(axis=2) <= 3)
    ys, xs = np.nonzero(black)
    if len(ys) and (ys.max() - ys.min()) * (xs.max() - xs.min()) > 0.3 * a.shape[0] * a.shape[1]:
        a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    if canvas.max() > 3:                                 # the canvas strip between the panels turns black too
        a = a.copy()
        a[np.abs(a - canvas).max(axis=2) <= 4] = 0
    ys, xs = np.nonzero(a.max(axis=2) > 24)
    if len(ys):
        pad = 8
        a = a[max(0, ys.min() - pad):ys.max() + 1 + pad, max(0, xs.min() - pad):xs.max() + 1 + pad]
    from PIL import Image
    return Image.fromarray(a.astype("uint8"))


def main(argv=None):
    from PIL import Image
    args = argv or sys.argv[1:]
    out = Path(args[0])
    local = Path(args[1]) if len(args) > 1 else None
    out.mkdir(parents=True, exist_ok=True)
    doc = json.loads((HERE / "fields.json").read_text())
    for f in doc["fields"]:
        name = f"{f['scroll']}-{f['volume']}"
        url = f["preview_xy"]
        here = local / url.rsplit("/", 1)[1] if local else None
        raw = here.read_bytes() if here and here.is_file() else urllib.request.urlopen(url, timeout=120).read()
        im = trim(Image.open(io.BytesIO(raw)).convert("RGB"))
        r = min(W / im.width, H / im.height)              # contain, centered on black like the panels
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H))
        canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
        canvas.save(out / f"{name}.webp", "WEBP", quality=82, method=6)
        print(name, (out / f"{name}.webp").stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
