"""Synthetic inputs for `kit lasagna selftest` (run in the lasagna Python: numpy, zarr and tifffile).

    python selftest_data.py OUT [--size N] [--slope S]

Writes into OUT:
  vol.lasagna.json        manifest version 2, base_shape_zyx, one uint8 level array per channel at scaledown 0
  cos.zarr, grad_mag.zarr, nx.zarr, ny.zarr
                          papyrus sheets as planes of constant y every PERIOD voxels: normal +y everywhere
                          (nx encodes 0 as 128, ny encodes 1 as 255), cos peaks on the sheets, grad_mag 100
  init_tilted.tifxyz      a plane through the middle of the box, tilted in x by SLOPE (y = c + S (x - xc)), on a
                          4-voxel grid: the fit's normal term should turn it toward the sheets' orientation
  stages.json             one short mesh stage with the normal, step and smooth terms
  stages_control.json     the same stage with the normal term off: the tilt must then stay (the check's control)
"""
import argparse
import json
from pathlib import Path

import numpy as np
import tifffile
import zarr

PERIOD = 8.0
STEP = 4.0


def stage_cfg(normal):
    return {
        "base": {"normal": float(normal), "step": 1.0, "smooth": 1.0},
        "stages": [{"name": "selftest", "steps": 40, "lr": 0.1, "params": ["mesh_ms"], "min_scaledown": 0}],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--slope", type=float, default=0.3)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n = a.size
    yy = np.arange(n, dtype=np.float32)[None, :, None]
    chans = {
        "cos": np.broadcast_to((0.5 + 0.5 * np.cos(2 * np.pi * yy / PERIOD)) * 255.0, (n, n, n)),
        "grad_mag": np.full((n, n, n), 100.0),
        "nx": np.full((n, n, n), 128.0),
        "ny": np.full((n, n, n), 255.0),
    }
    groups = {}
    for name, arr in chans.items():
        z = zarr.open(str(out / f"{name}.zarr"), mode="w", shape=(n, n, n), chunks=(32, 32, 32), dtype="uint8")
        z[:] = np.asarray(arr).astype(np.uint8)
        groups[name] = {"zarr": f"{name}.zarr", "scaledown": 0, "channels": [name]}
    manifest = {"version": 2, "source_to_base": 1.0, "base_shape_zyx": [n, n, n], "grad_mag_encode_scale": 1000.0,
                "grad_mag_factor": 1.0, "groups": groups}
    (out / "vol.lasagna.json").write_text(json.dumps(manifest, indent=1) + "\n")

    lo, hi = 12.0, n - 12.0
    cols = np.arange(lo, hi + 0.1, STEP, dtype=np.float32)
    rows = np.arange(lo, hi + 0.1, STEP, dtype=np.float32)
    xg = np.broadcast_to(cols[None, :], (len(rows), len(cols))).astype(np.float32)
    zg = np.broadcast_to(rows[:, None], (len(rows), len(cols))).astype(np.float32)
    yg = (n / 2.0 + a.slope * (xg - n / 2.0)).astype(np.float32)
    td = out / "init_tilted.tifxyz"
    td.mkdir(exist_ok=True)
    for axis, g in (("x", xg), ("y", yg), ("z", zg)):
        tifffile.imwrite(str(td / f"{axis}.tif"), g)
    (td / "meta.json").write_text(json.dumps({
        "format": "tifxyz", "type": "seg", "uuid": "kit-lasagna-selftest", "scale": [1.0 / STEP, 1.0 / STEP],
        "bbox": [[float(xg.min()), float(yg.min()), float(zg.min())], [float(xg.max()), float(yg.max()), float(zg.max())]],
    }) + "\n")
    (out / "stages.json").write_text(json.dumps(stage_cfg(1.0), indent=1) + "\n")
    (out / "stages_control.json").write_text(json.dumps(stage_cfg(0.0), indent=1) + "\n")
    print(json.dumps({"out": str(out), "size": n, "slope": a.slope, "grid": [len(rows), len(cols)]}))


if __name__ == "__main__":
    main()
