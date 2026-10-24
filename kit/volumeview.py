"""Local Neuroglancer links for explicitly described public OME-Zarr grids.

Only checks the supplied metadata; never opens sources or verifies remote registration.
Source-grid scales must be dimensionless ones, as in the official Vesuvius atlas.
Coordinate-state convention: villa 1db9cd9, scrollprize.org/src/components/atlas/dataAccess.js
(MIT, Vesuvius Challenge; attribution and license in NOTICE). Independently implemented.
"""

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

VIEWER = "https://neuroglancer-demo.appspot.com/#!"
MAX_MANIFEST_BYTES = 1048576
_AXES = ["z", "y", "x"]
_OUTPUT = {a: [1e-6, "m"] for a in ("x", "y", "z")}
_GRAY = "#uicontrol invlerp normalized\nvoid main() { emitGrayscale(normalized()); }"
_OVERLAY = ('#uicontrol vec3 color color(default="#ff7a1a")\n'
            '#uicontrol invlerp normalized\nvoid main() { emitRGBA(vec4(color, normalized())); }')


class VolumeViewError(ValueError):
    """The local manifest cannot safely describe a supported viewer state."""


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise VolumeViewError(f"{label}: expected exactly {', '.join(sorted(expected))}")


def _text(value, label):
    if (not isinstance(value, str) or not 1 <= len(value) <= 120
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise VolumeViewError(f"{label}: expected nonempty text of at most 120 characters without controls")
    return value


def _vector(value, label, *, shape=False):
    if not isinstance(value, list) or len(value) != 3:
        raise VolumeViewError(f"{label}: expected three positive finite numbers in ZYX order")
    for n in value:
        if (isinstance(n, bool) or not isinstance(n, (int, float))
                or (shape and not isinstance(n, int)) or not 0 < n <= 1e12):
            raise VolumeViewError(f"{label}: expected positive {'integers' if shape else 'numbers'} at most 1e12")
    return value


def _source(url):
    if (not isinstance(url, str) or len(url) > 4096
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
        raise VolumeViewError("source: expected a public Vesuvius OME-Zarr root URL")
    try:
        p = urlsplit(url)
    except ValueError as exc:
        raise VolumeViewError("source: invalid URL") from exc
    hosts = {"vesuvius-challenge-open-data.s3.amazonaws.com",
             "vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"}
    if p.query or p.fragment or p.username or p.password or p.netloc != p.hostname:
        raise VolumeViewError("source: credentials, ports, queries and fragments are not supported")
    if p.scheme == "s3" and p.netloc == "vesuvius-challenge-open-data":
        host = "vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
    elif p.scheme == "https" and p.netloc in hosts:
        host = p.netloc
    else:
        raise VolumeViewError("source: only the public vesuvius-challenge-open-data bucket is supported")
    path = p.path.rstrip("/")
    if (not re.fullmatch(r"/[A-Za-z0-9._/-]+\.zarr", path)
            or any(part in ("", ".", "..") for part in path[1:].split("/"))):
        raise VolumeViewError("source: expected a .zarr root path without escapes or traversal")
    return "zarr2://https://" + host + path


def build_state(manifest):
    """Validate a declared grid manifest and return a Neuroglancer state, without I/O."""
    _keys(manifest, ("schema", "layers"), "manifest")
    if type(manifest["schema"]) is not int or manifest["schema"] != 1:
        raise VolumeViewError("schema: expected 1")
    layers = manifest["layers"]
    if not isinstance(layers, list) or not 1 <= len(layers) <= 2:
        raise VolumeViewError("layers: expected CT alone or CT followed by one prediction")
    result, names, reference = [], set(), None
    for index, layer in enumerate(layers):
        _keys(layer, ("name", "role", "source", "frame", "shape_zyx", "voxel_size_um_zyx",
                      "origin_um_zyx", "source_grid"), "layer")
        name = _text(layer["name"], "name")
        frame = _text(layer["frame"], "frame")
        if name in names:
            raise VolumeViewError("name: layers must have distinct names")
        names.add(name)
        if layer["role"] != ("ct" if index == 0 else "prediction"):
            raise VolumeViewError("role: expected CT first, then prediction")
        grid = layer["source_grid"]
        _keys(grid, ("axes", "scale", "units", "origin"), "source_grid")
        if grid["axes"] != _AXES:
            raise VolumeViewError("source_grid.axes: only exactly [z, y, x] is supported")
        # Do not double-apply an OME source's existing physical scale or transform.
        # Numeric equality alone would accept bools; disallow those explicitly.
        for key, expected in (("scale", [1, 1, 1]), ("origin", [0, 0, 0])):
            val = grid[key]
            if (not isinstance(val, list) or val != expected
                    or any(type(n) not in (int, float) for n in val)):
                raise VolumeViewError("source_grid: only dimensionless unit scale and zero origin are supported")
        if grid["units"] != ["", "", ""]:
            raise VolumeViewError("source_grid: physical source units are not supported; do not apply spacing twice")
        origin = layer["origin_um_zyx"]
        if (not isinstance(origin, list) or origin != [0, 0, 0]
                or any(type(n) not in (int, float) for n in origin)):
            raise VolumeViewError("origin_um_zyx: only an explicit zero origin is supported")
        shape = _vector(layer["shape_zyx"], "shape_zyx", shape=True)
        spacing = _vector(layer["voxel_size_um_zyx"], "voxel_size_um_zyx")
        scales = [n * 1e-6 for n in spacing]
        extent = [n * v for n, v in zip(shape, spacing)]
        if not all(math.isfinite(v) and v > 0 for v in scales + extent):
            raise VolumeViewError("grid: spacing or physical extent cannot be represented finitely")
        if reference is None:
            reference = (frame, extent)
        elif (frame != reference[0]
              or any(not math.isclose(a, b, rel_tol=1e-10, abs_tol=0) for a, b in zip(extent, reference[1]))):
            raise VolumeViewError("overlay: frame and physical extents must match the CT exactly")
        state_layer = {
            "type": "image", "name": name,
            "source": {"url": _source(layer["source"]), "transform": {
                # Neuroglancer pairs these dimension objects by position. Keep
                # both XYZ, converting the manifest's ZYX values explicitly.
                "inputDimensions": {a: [scale, "m"] for a, scale in zip(reversed(_AXES), reversed(scales))},
                "outputDimensions": {a: list(v) for a, v in _OUTPUT.items()}}},
            "shader": _GRAY if index == 0 else _OVERLAY,
        }
        if index:
            state_layer["blend"] = "additive"
        result.append(state_layer)
    return {"dimensions": {a: list(v) for a, v in _OUTPUT.items()}, "layers": result, "layout": "4panel"}


def viewer_link(manifest):
    """Validate the manifest and encode its state under the fixed HTTPS viewer host."""
    return VIEWER + quote(json.dumps(build_state(manifest), separators=(",", ":"), allow_nan=False), safe="")


def add_arguments(parser):
    """Add the common standalone and workbench command arguments."""
    parser.add_argument("manifest", help="local JSON with explicitly declared grid metadata")
    parser.add_argument("--format", choices=("url", "state", "receipt"), default="url",
                        help="URL, Neuroglancer state, or state plus input digest (default: url)")
    parser.add_argument("--out", help="write a new local file instead of stdout; never overwrites")


def _reject_constant(value):
    raise VolumeViewError(f"JSON: non-finite number {value} is not supported")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VolumeViewError(f"JSON: duplicate key {key} is not supported")
        result[key] = value
    return result


def run(args):
    """Read one bounded local manifest and write validated output; return 0 or 2."""
    try:
        src = Path(args.manifest)
        if args.out and Path(args.out).resolve() == src.resolve():
            raise VolumeViewError("output: must not replace the input manifest")
        with src.open("rb") as f:
            raw = f.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise VolumeViewError("manifest: exceeds the 1 MiB limit")
        manifest = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        state = build_state(manifest)
        link = viewer_link(manifest)
        if args.format == "url":
            content = link
        elif args.format == "state":
            content = json.dumps(state, indent=2, allow_nan=False)
        else:
            content = json.dumps({"schema": 1, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                                  "validation": "supplied metadata only; remote sources not verified",
                                  "state": state, "url": link}, indent=2, allow_nan=False)
        if args.out:
            # Exclusive creation also protects existing hardlinks and symlinks.
            with Path(args.out).open("x", encoding="utf-8") as f:
                f.write(content + "\n")
        else:
            print(content)
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        print(f"volumeview: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    """Standalone entry point, equivalent to the workbench command."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
