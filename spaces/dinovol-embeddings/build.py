"""Build the dinovol Embeddings Space (https://huggingface.co/spaces/SharpMeow/dinovol-embeddings) into OUT.

It reads one z slice of the public bucket by URL, logged out, and writes the page's pictures and search data:

  assets/ct.webp         the CT slice (open data, level 1, shown at every 4th voxel)
  assets/tokens.webp     tokens_unit as color: the slice's three main directions as red, green and blue
  assets/dense.webp      the same for dense, every 4 voxels
  assets/search.i8       tokens_unit of every cell inside the scroll, cut to the slice's 32 main directions, unit
                         length, int8 (x 127); the page's click-to-search takes dot products of these
  assets/mask.u8         which cells are inside the scroll, one bit each, row major
  assets/rgb.webp        one layer (z 9,680) of the color volume (scripts in Scrolls-private made it), read back by URL
  index.html             this folder's index.html with the numbers below filled in

The pictures are model output of a public scan that is not prize-eligible (PHerc0841); they live only on the Space,
never in this repository (hard rule 6). Needs zarr 3, fsspec, aiohttp, numpy and pillow; about a minute and 1 GB
of downloads on a cloud container.

  python3 spaces/dinovol-embeddings/build.py OUT
"""
import argparse
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUCKET = ("https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/"
          "PHerc0841/20250821151531-dinovol_8um_ps192_102126.zarr")
RGB = ("https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/"
       "PHerc0841/20250821151531-dinovol_8um_ps192_102126-rgb.ome.zarr")
CT = ("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/"
      "PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr")
Z = 9600                              # scan voxels; token cell 1200, dense cell 2400
BOX = (1152, 6816, 2592, 6048)        # y0, y1, x0, x1 in scan voxels, every 8: the scroll at this z, with a margin
RGB_GB = "1.6 GB"                      # the color volume's size, from its upload receipt
K = 32                                # directions kept for search
QUERIES = 60                          # random cells for the search accuracy check


def main_directions(X, k, center=True):
    """The k main directions (principal components) of the rows of X, strongest first."""
    import numpy as np
    mu = X.mean(0) if center else np.zeros(X.shape[1], X.dtype)
    w, V = np.linalg.eigh(np.cov((X - mu)[::5].T))
    return mu, V[:, ::-1][:, :k]


def colors(q, s):
    """An RGB picture of int8 vectors q with scales s: the three main directions, 1st to 99th percentile."""
    import numpy as np
    m = s > 0
    X = q[m].astype(np.float32) * s[m, None].astype(np.float32)
    mu, V = main_directions(X, 3)
    P = (X - mu) @ V
    lo, hi = np.percentile(P, 1, axis=0), np.percentile(P, 99, axis=0)
    img = np.zeros(m.shape + (3,), np.uint8)
    img[m] = (np.clip((P - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
    return img


def build(out):
    import numpy as np
    import zarr
    from PIL import Image
    from zarr.storage import FsspecStore

    out = Path(out)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    zarr.config.set({"async.concurrency": 64})
    g = zarr.open_group(FsspecStore.from_url(BUCKET, read_only=True), mode="r", zarr_format=2)
    y0, y1, x0, x1 = BOX
    t = (Z // 8, slice(y0 // 8, y1 // 8), slice(x0 // 8, x1 // 8))
    d = (Z // 4, slice(y0 // 4, y1 // 4), slice(x0 // 4, x1 // 4))
    q, s = np.asarray(g["tokens_unit"][t]), np.asarray(g["tokens_unit_scale"][t])
    dq, ds = np.asarray(g["dense"][d]), np.asarray(g["dense_scale"][d])
    ct = np.asarray(zarr.open_group(CT, mode="r")["1"][Z // 2, y0 // 2:y1 // 2, x0 // 2:x1 // 2])
    h, w = ds.shape

    Image.fromarray(ct).resize((w, h), Image.LANCZOS).save(out / "assets" / "ct.webp", quality=88)
    Image.fromarray(colors(q, s)).save(out / "assets" / "tokens.webp", lossless=True)
    Image.fromarray(colors(dq, ds)).save(out / "assets" / "dense.webp", quality=90)

    m = s > 0
    X = q[m].astype(np.float32) * s[m, None].astype(np.float32)
    _, V = main_directions(X, K, center=False)
    P = X @ V
    P /= np.linalg.norm(P, axis=1, keepdims=True)
    Q = np.round(P * 127).astype(np.int8)
    (out / "assets" / "search.i8").write_bytes(Q.tobytes())
    (out / "assets" / "mask.u8").write_bytes(np.packbits(m.ravel()).tobytes())

    # How close is the page's 32-direction search to the full 480-number cosine? Random cells inside the scroll.
    qi = np.random.default_rng(1).choice(len(X), QUERIES, replace=False)
    full = X @ X[qi].T
    approx = Q.astype(np.float32) @ Q[qi].astype(np.float32).T
    r = [float(np.corrcoef(full[:, j], approx[:, j])[0, 1]) for j in range(QUERIES)]
    top = len(X) // 20
    ov = [len(set(np.argsort(-full[:, j])[:top]) & set(np.argsort(-approx[:, j])[:top])) / top
          for j in range(QUERIES)]
    data = {"z": Z, "box": BOX, "shape": list(m.shape), "k": K, "n": int(m.sum()), "queries": QUERIES,
            "r_median": round(float(np.median(r)), 3), "r_min": round(min(r), 3),
            "top5_median": round(float(np.median(ov)), 2), "top5_min": round(min(ov), 2),
            "bucket": BUCKET, "ct": CT, "rgb": RGB}
    rgb = zarr.open_array(FsspecStore.from_url(RGB + "/0", read_only=True), mode="r", zarr_format=2)
    layer = np.asarray(rgb[:, (Z + 80) // 8, y0 // 8:y1 // 8, x0 // 8:x1 // 8]).transpose(1, 2, 0)
    Image.fromarray(layer).save(out / "assets" / "rgb.webp", lossless=True)
    data["rgb_gb"] = RGB_GB
    page = (HERE / "index.html").read_text().replace("__DATA__", json.dumps(data)).replace("__RGBGB__", RGB_GB)
    (out / "index.html").write_text(page)
    for f in ("README.md", "NOTICE", "connect.json", "CONNECT.md"):
        shutil.copy(HERE / f, out / f)
    shutil.copy(HERE.parent.parent / "LICENSE", out / "LICENSE")
    return data


def main(argv=None):
    p = argparse.ArgumentParser(description="Build the dinovol Embeddings Space into a folder.")
    p.add_argument("out", help="folder to write the Space into (uploaded as is)")
    a = p.parse_args(argv)
    print(json.dumps(build(a.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
