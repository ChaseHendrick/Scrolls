"""Card pictures for the Every field tab: each public SharpMeow dataset's preview-xy.png (cos | normals, made with the
field) as a small 2:1 WebP (fitted whole, on black) under assets/thumbs/DATASET.webp. The guide falls back to the dataset's own PNG when a thumb
is missing. Like the rest of assets/, the thumbs live on the Space, not in git.

  python3 spaces/lasagna-fields/make_thumbs.py OUT_DIR      (then upload OUT_DIR as the Space's assets/thumbs/)
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
    out = Path((argv or sys.argv[1:])[0])
    out.mkdir(parents=True, exist_ok=True)
    doc = json.loads((HERE / "fields.json").read_text())
    for f in doc["fields"]:
        if not f.get("dataset"):
            continue
        name = f["dataset"].split("/")[1]
        url = f"https://huggingface.co/datasets/{f['dataset']}/resolve/main/preview-xy.png"
        im = trim(Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=120).read())).convert("RGB"))
        r = min(W / im.width, H / im.height)              # contain, centered on black like the panels
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H))
        canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
        canvas.save(out / f"{name}.webp", "WEBP", quality=82, method=6)
        print(name, (out / f"{name}.webp").stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
