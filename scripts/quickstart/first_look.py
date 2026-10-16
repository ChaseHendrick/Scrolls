"""First look at the open data: one CT slice, one segment, one ink layer, in a few MB.

Used by docs/QUICKSTART.md. Reads only the public bucket vesuvius-challenge-open-data over anonymous HTTPS.
Needs numpy, Pillow and tifffile (pip install ".[reader]" from the repository root installs all three).

  python scripts/quickstart/first_look.py slice   [--z 170] [--out work/quickstart]
  python scripts/quickstart/first_look.py segment [--out work/quickstart]
  python scripts/quickstart/first_look.py ink     [--out work/quickstart]
  python scripts/quickstart/first_look.py all     [--out work/quickstart]

slice    one z slice of PHerc. 0139's 9.362 um scan at level 5 (32 times coarser, 207 x 207 px), about 8 MB
segment  the 9.362 um tifxyz mesh of segment w035 (under 1 MB); prints its grid and bounding box and, with the
         slice, writes slice-with-w035.png marking where w035 crosses that slice
ink      the published ink detection preview of w035 (a 0.5 MB JPEG, 8 times downsampled)

Everything lands in work/ (git-ignored). The data are CC BY-NC 4.0: images of scan data stay on your machine and
never go into a public repository. An ink layer shows where a model detects ink; it is not a reading.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BUCKET = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
VOLUME = "PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr"
SEGMENT = "PHerc0139/segments/20260317000000-w035_2026031718"
MESH = SEGMENT + "/mesh/20260317000000-on-20250728140407-9.362um.tifxyz"
LEVEL = 5


def get(key):
    url = BUCKET + "/" + key
    if not url.startswith(BUCKET + "/"):
        raise SystemExit("refusing a URL outside the open-data bucket")
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def deps():
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        import tifffile  # noqa: F401
    except ImportError as e:
        raise SystemExit(f"missing {e.name}: run python -m pip install numpy pillow tifffile")


def slice_plane(z):
    import numpy as np
    meta = json.loads(get(f"{VOLUME}/{LEVEL}/.zarray"))
    if meta.get("compressor") is not None or meta["dtype"] != "|u1":
        raise SystemExit("unexpected level layout: " + json.dumps(meta))
    nz, ny, nx = meta["shape"]
    cz, cy, cx = meta["chunks"]
    if not 0 <= z < nz:
        raise SystemExit(f"--z must be 0 to {nz - 1} at level {LEVEL}")
    plane = np.zeros((ny, nx), np.uint8)
    for iy in range(-(-ny // cy)):
        for ix in range(-(-nx // cx)):
            try:
                raw = get(f"{VOLUME}/{LEVEL}/{z // cz}/{iy}/{ix}")
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    continue  # a chunk that was never written holds the fill value, 0
                raise
            chunk = np.frombuffer(raw, np.uint8).reshape(cz, cy, cx)
            y0, x0 = iy * cy, ix * cx
            h, w = min(cy, ny - y0), min(cx, nx - x0)
            plane[y0:y0 + h, x0:x0 + w] = chunk[z % cz, :h, :w]
    return plane


def cmd_slice(args):
    from PIL import Image
    plane = slice_plane(args.z)
    out = args.out / f"slice-z{args.z}.png"
    Image.fromarray(plane).save(out)
    print(f"wrote {out}: level {LEVEL} slice {args.z} (full-resolution z about {args.z * 2 ** LEVEL}), "
          f"{plane.shape[1]} x {plane.shape[0]} px, values {plane.min()} to {plane.max()}")
    return plane


def cmd_segment(args, plane=None):
    import numpy as np
    import tifffile
    folder = args.out / "w035.tifxyz"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("meta.json", "x.tif", "y.tif", "z.tif"):
        (folder / name).write_bytes(get(f"{MESH}/{name}"))
    meta = json.loads((folder / "meta.json").read_text())
    x, y, z = (tifffile.imread(folder / f"{a}.tif") for a in "xyz")
    valid = (x != -1) & np.isfinite(x)
    print(f"wrote {folder}: grid {x.shape[1]} x {x.shape[0]} points, {valid.mean():.0%} valid, "
          f"grid step {1 / meta['scale'][0]:.0f} voxels")
    lo, hi = meta["bbox"]
    print(f"bounding box in level-0 voxels (x, y, z): {[round(v) for v in lo]} to {[round(v) for v in hi]}")
    if plane is not None:
        from PIL import Image
        f = 2 ** LEVEL
        near = valid & (np.abs(z / f - args.z) < 0.5)
        rgb = np.stack([plane] * 3, -1)
        ys = np.clip((y[near] / f).astype(int), 0, plane.shape[0] - 1)
        xs = np.clip((x[near] / f).astype(int), 0, plane.shape[1] - 1)
        rgb[ys, xs] = (255, 64, 64)
        out = args.out / "slice-with-w035.png"
        Image.fromarray(rgb).resize((plane.shape[1] * 3, plane.shape[0] * 3), Image.NEAREST).save(out)
        print(f"wrote {out}: {int(near.sum())} mesh points of w035 near slice {args.z}, in red")


def cmd_ink(args):
    listing = get(f"?list-type=2&prefix={urllib.parse.quote(SEGMENT + '/ink-detection/downsampled/')}").decode()
    keys = [k for k in re.findall(r"<Key>([^<]+)</Key>", listing) if k.endswith(".jpg")]
    if not keys:
        raise SystemExit("no ink preview found for w035")
    key = next((k for k in keys if "2.399um" in k), keys[0])
    out = args.out / "w035-ink-preview.jpg"
    out.write_bytes(get(key))
    print(f"wrote {out} ({out.stat().st_size // 1000} kB) from {key}")
    print("Model output: bright areas are where an ink model detects ink. w035 is in the released models' "
          "training labels, so this is a check that the data and tools work, not a new result.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("what", choices=("slice", "segment", "ink", "all"))
    p.add_argument("--z", type=int, default=170, help="level-5 slice index; 170 crosses segment w035")
    p.add_argument("--out", type=Path, default=Path("work/quickstart"))
    args = p.parse_args(argv)
    deps()
    args.out.mkdir(parents=True, exist_ok=True)
    plane = None
    if args.what in ("slice", "all"):
        plane = cmd_slice(args)
    if args.what in ("segment", "all"):
        if plane is None and args.what == "segment":
            plane = slice_plane(args.z)
        cmd_segment(args, plane)
    if args.what in ("ink", "all"):
        cmd_ink(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
