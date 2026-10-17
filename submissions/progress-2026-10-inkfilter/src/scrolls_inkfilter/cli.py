"""Local-file interface; no network clients or repository-specific helpers."""

import argparse
import json
from pathlib import Path

import numpy as np

from . import __version__
from .core import DEFAULT_RECIPE, RECIPES, InkFilterError, ink_map


def read_window(path, level=0, crop=None):
    """Read a local (Z,H,W) .npy, TIFF stack, or Zarr array/group window."""
    if "://" in str(path):
        raise InkFilterError("input must be a local file or Zarr directory")
    path = Path(path)
    if level < 0:
        raise InkFilterError("level must be nonnegative")
    if path.suffix.lower() == ".npy":
        if level != 0:
            raise InkFilterError(".npy and TIFF inputs have only level 0")
        a = np.load(path, mmap_mode="r", allow_pickle=False)
    elif path.suffix.lower() in (".tif", ".tiff"):
        if level != 0:
            raise InkFilterError(".npy and TIFF inputs have only level 0")
        import tifffile
        a = tifffile.imread(path)
    elif path.is_dir():
        import zarr
        a = zarr.open(str(path), mode="r")
        if isinstance(a, zarr.Group):
            a = a[str(level)]
            if not isinstance(a, zarr.Array):
                raise InkFilterError("the selected Zarr level must be an array, not a group")
        elif level != 0:
            raise InkFilterError("a bare Zarr array has only level 0")
    else:
        raise InkFilterError("input must be .npy, .tif, .tiff, or a local Zarr directory")
    if len(a.shape) != 3 or not 3 <= a.shape[0] <= 4096 or min(a.shape[1:]) < 1:
        raise InkFilterError(f"input must be (Z,H,W), 3 <= Z <= 4096, H,W >= 1; got {a.shape}")
    shape = tuple(int(v) for v in a.shape)
    y0, y1, x0, x1 = crop if crop is not None else (0, shape[1], 0, shape[2])
    if not (0 <= y0 < y1 <= shape[1] and 0 <= x0 < x1 <= shape[2]):
        raise InkFilterError("crop must be nonempty and inside the selected array")
    v = np.asarray(a[:, y0:y1, x0:x1])
    if v.dtype not in (np.dtype("uint8"), np.dtype("uint16")) and v.dtype.kind != "f":
        raise InkFilterError("input must be uint8, uint16, or floating point in [0,1]")
    if not np.isfinite(v).all() or (v.dtype.kind == "f" and (v.min() < 0 or v.max() > 1)):
        raise InkFilterError("floating-point input must be finite and in [0,1]")
    return v, shape, [y0, y1, x0, x1]


def write_map(path, data):
    """Write a float32 .npy or TIFF map."""
    if path.suffix.lower() == ".npy":
        with path.open("wb") as stream:
            np.save(stream, data.astype(np.float32), allow_pickle=False)
    else:
        import tifffile
        tifffile.imwrite(path, data.astype(np.float32))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed ink filter with a reverse-depth control. Output is not a reading.")
    parser.add_argument("volume", help="local .npy, TIFF stack, or Zarr directory, shape (Z,H,W)")
    parser.add_argument("--output", required=True, help="map .npy, .tif, or .tiff; also writes _reverse and .json")
    parser.add_argument("--level", type=int, default=0, help="numeric Zarr group level (default: 0)")
    parser.add_argument("--crop", nargs=4, type=int, metavar=("Y0", "Y1", "X0", "X1"), help="crop on the selected array grid")
    parser.add_argument("--recipe", choices=sorted(RECIPES), default=DEFAULT_RECIPE)
    parser.add_argument("--overwrite", action="store_true", help="replace existing output files")
    args = parser.parse_args(argv)
    try:
        output = Path(args.output)
        if output.suffix.lower() not in (".npy", ".tif", ".tiff"):
            raise InkFilterError("output must end in .npy, .tif, or .tiff")
        control = output.with_name(output.stem + "_reverse" + output.suffix)
        record = output.with_suffix(".json")
        paths = (output, control, record)
        source = Path(args.volume).resolve()
        resolved_outputs = [p.resolve() for p in paths]
        if any(p == source for p in resolved_outputs):
            raise InkFilterError("output must not replace the input")
        if source.is_dir() and any(p.is_relative_to(source) for p in resolved_outputs):
            raise InkFilterError("output files must not be inside the input directory")
        if source.exists() and any(p.exists() and p.samefile(source) for p in paths):
            raise InkFilterError("output must not replace the input")
        if len(set(resolved_outputs)) != len(paths):
            raise InkFilterError("output paths must resolve to different files")
        if any(p.is_symlink() or (p.exists() and p.stat().st_nlink > 1) for p in paths):
            raise InkFilterError("output files must not be symbolic links or multiply linked files")
        if not args.overwrite and any(p.exists() for p in paths):
            raise InkFilterError("an output already exists; choose another name or pass --overwrite")
        if output.suffix.lower() != ".npy":
            import tifffile  # fail before processing when the optional writer is missing
        v, shape, crop = read_window(args.volume, args.level, args.crop)
        info = {}
        forward = ink_map(v, args.recipe, info=info)
        reverse = ink_map(v, args.recipe, reverse=True)
        result = {"schema_version": 1, "version": __version__, "input": str(args.volume),
                  "level": args.level, "crop": crop, "surface_shape": shape,
                  "recipe_name": args.recipe, "recipe": RECIPES[args.recipe], "window": info,
                  "output": str(output), "control": str(control), "record": str(record),
                  "note": "filter output, not a reading"}
        output.parent.mkdir(parents=True, exist_ok=True)
        write_map(output, forward)
        write_map(control, reverse)
        record.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (InkFilterError, OSError, ValueError, KeyError, ImportError) as exc:
        parser.exit(2, f"scrolls-inkfilter: {exc}\n")
    print(json.dumps(result, allow_nan=False))
    return 0
