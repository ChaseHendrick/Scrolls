"""Export a rendered surface volume (zarr) to numbered layer TIFFs: 00.tif, 01.tif, ...

villa's `vc_render_tifxyz --zarr-output` and the team's published surface volumes are
zarr stores of shape (layers, height, width), uint8, either a bare array or an OME-Zarr
group whose full-resolution level is "0". v8in (YoussefMoNader/ink-8um-v8in) reads a
directory of numbered layer images instead, and uses the central 24 when there are more.

Chunks of these stores usually hold every layer (w045: 28 x 128 x 128), so reading one
layer decompresses the whole volume. The export therefore reads all requested layers in
row bands into memory when they fit under max_bytes (w045: 1.4 GB, about 14 times faster
than layer by layer), and falls back to one layer at a time otherwise. Depth order is kept as
stored; reverse it at inference time (v8in `--reverse`), not here, so one export serves both
directions. Needs numpy, tifffile and zarr (all in villa's environment).

The depth-shuffle control (after aviad12g's vesuvius-depth-order-control) is the exception:
`shuffle` writes the layers in a fixed random order, never the stored or the reversed one. A
model that reads ink loses it there; on PHerc0841 every released reader we tried fell to
about 0.5 AUC on shuffled layers, a cleaner null than the reversed volume, which keeps a
depth structure. `kit shuffle` writes a zarr (villa's input); `kit layers --shuffle` writes
v8in's layer folder in the same order.
"""

from pathlib import Path

from .verify import VerifyError, _numpy


def _zarr():
    try:
        import zarr
    except ImportError as exc:
        raise VerifyError("zarr is required (it is in villa's environment)") from exc
    return zarr


def open_volume(path, level="0"):
    """Return the (layers, height, width) array of a surface-volume zarr."""
    zarr = _zarr()
    try:
        node = zarr.open(str(path), mode="r")
    except Exception as exc:  # zarr raises several types for a missing or malformed store
        raise VerifyError(f"cannot open {path} as zarr: {exc}") from exc
    if not hasattr(node, "shape"):
        if level not in node:
            raise VerifyError(f"{path}: zarr group has no level {level!r}; levels: {sorted(node.keys())}")
        node = node[level]
    if len(node.shape) != 3:
        raise VerifyError(f"{path}: expected (layers, height, width), got shape {node.shape}")
    return node


def depth_permutation(n, seed):
    """A fixed random order of n layers that is neither the stored nor the reversed order."""
    np = _numpy()
    if n < 3:
        raise VerifyError(f"a depth shuffle needs at least 3 layers, got {n}")
    rng = np.random.default_rng(seed)
    ident = list(range(n))
    while True:
        perm = [int(i) for i in rng.permutation(n)]
        if perm != ident and perm != ident[::-1]:
            return perm


DEFAULT_MAX_BYTES = 4 * 1024 ** 3
BAND_ROWS = 1024


def export_layers(volume, out_dir, start=0, count=None, compression="zlib", crop=None,
                  max_bytes=DEFAULT_MAX_BYTES, order=None):
    """Write layers start .. start+count-1 of volume as 00.tif, 01.tif, ... in out_dir.

    crop is (y0, y1, x0, x1) in full-resolution pixels, or None for the whole layer. order, a
    permutation of range(count), writes layer start+order[i] as file i (the shuffle control)."""
    np = _numpy()
    import tifffile

    total = volume.shape[0]
    if count is None:
        count = total - start
    if start < 0 or count < 1 or start + count > total:
        raise VerifyError(f"layers {start}..{start + count - 1} are outside the volume's {total} layers")
    h, w = volume.shape[1:]
    y0, y1, x0, x1 = 0, h, 0, w
    if crop is not None:
        y0, y1, x0, x1 = crop
        if not (0 <= y0 < y1 <= h and 0 <= x0 < x1 <= w):
            raise VerifyError(f"crop {list(crop)} is outside the {h} x {w} layer")
    region = (slice(y0, y1), slice(x0, x1))
    if volume.dtype != np.uint8:
        raise VerifyError(f"the volume is {volume.dtype}; v8in expects uint8 layers")
    stack = None
    if count * (y1 - y0) * (x1 - x0) <= max_bytes:
        stack = np.empty((count, y1 - y0, x1 - x0), dtype=np.uint8)
        for band in range(y0, y1, BAND_ROWS):
            end = min(band + BAND_ROWS, y1)
            stack[:, band - y0:end - y0] = volume[start:start + count, band:end, x0:x1]
    if order is None:
        order = list(range(count))
    elif sorted(order) != list(range(count)):
        raise VerifyError(f"order must be a permutation of 0..{count - 1}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(count - 1)))
    written = []
    for i, src in enumerate(order):
        layer = stack[src] if stack is not None else np.asarray(volume[(start + src, *region)])
        path = out / f"{i:0{width}d}.tif"
        tifffile.imwrite(path, layer, compression=compression)
        written.append(path)
    return written


def export_file(src, out_dir, start=0, count=None, level="0", crop=None, max_bytes=DEFAULT_MAX_BYTES,
                shuffle_seed=None):
    volume = open_volume(src, level)
    n = (volume.shape[0] - start) if count is None else count
    order = None if shuffle_seed is None else depth_permutation(n, shuffle_seed)
    written = export_layers(volume, out_dir, start, count, crop=crop, max_bytes=max_bytes, order=order)
    return {"source": str(src), "shape": list(volume.shape), "start": start, "crop": crop,
            "layers": len(written), "out_dir": str(out_dir), "order": order}


def shuffle_file(src, dst, seed, level="0", crop=None):
    """Write src's layers in a fixed random order to a new zarr (array "0"), for villa's reader."""
    np = _numpy()
    zarr = _zarr()
    volume = open_volume(src, level)
    n, h, w = volume.shape
    y0, y1, x0, x1 = crop if crop is not None else (0, h, 0, w)
    if not (0 <= y0 < y1 <= h and 0 <= x0 < x1 <= w):
        raise VerifyError(f"crop {list(crop)} is outside the {h} x {w} layer")
    order = depth_permutation(n, seed)
    data = np.empty((n, y1 - y0, x1 - x0), dtype=volume.dtype)
    for band in range(y0, y1, BAND_ROWS):
        end = min(band + BAND_ROWS, y1)
        data[:, band - y0:end - y0] = volume[:, band:end, x0:x1][order]
    group = zarr.open_group(str(dst), mode="w")
    group.create_array("0", data=data, chunks=(n, min(128, y1 - y0), min(128, x1 - x0)))
    group.attrs["depth_shuffle"] = {"source": str(src), "seed": seed, "order": order, "crop": crop}
    return {"source": str(src), "out": str(dst), "shape": list(data.shape), "seed": seed, "order": order}
