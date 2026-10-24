"""Run villa lasagna's fit.py on a CPU or MPS device without editing villa (kit lasagna fit uses it off CUDA).

fit.py always loads its volume through fit_data.load_3d_streaming, whose sparse caches create torch.cuda.Stream and
compile CUDA kernels, so every fit that reads a volume fails off CUDA ("torch.cuda.Stream requires CUDA support").
This shim swaps in villa's dense loader fit_data.load_3d (cuda_gridsample=False, so FitData3D samples with torch's
F.grid_sample) when the device is not CUDA, then runs fit.main with the same arguments. On CUDA it changes nothing.

The dense loader reads the whole box into memory: KIT_LASAGNA_CROP="x0,y0,z0,w,h,d" (lasagna base voxels) limits
it to a box, which load_3d records as the data's origin, so fit coordinates stay in the base frame. fit.py asks for
the data again at every stage and every so many steps (_ensure_data finds no streaming caches on dense data), so
the last load is kept and handed back for the same arguments: one copy in memory, read once. fit.py's
corr-point-roi stage calls fit_data.load_3d itself, with no crop, off CUDA; the shim gives that call the same box.
It reads local zarr only (a manifest with a lasagna-remote.json marker streams, which needs CUDA): mirror a crop
first with kit lasagna manifest. The 'data' (cos) loss term uses a CUDA kernel either way.

Usage, from villa's lasagna folder with it on PYTHONPATH: python fit_cpu_shim.py CONFIG.json [...] [fit.py flags]
"""
import os
import sys

import torch

import fit
import fit_data

_orig_streaming = fit_data.load_3d_streaming
_orig_load_3d = fit_data.load_3d
_last = {}


def crop_from_env(text=None):
    """(x0, y0, z0, w, h, d) from KIT_LASAGNA_CROP, or None."""
    text = os.environ.get("KIT_LASAGNA_CROP", "") if text is None else text
    if not text.strip():
        return None
    vals = [int(round(float(v))) for v in text.replace(" ", "").split(",")]
    if len(vals) != 6 or min(vals[3:]) <= 0 or min(vals[:3]) < 0:
        raise SystemExit(f"KIT_LASAGNA_CROP must be x0,y0,z0,w,h,d with x0, y0, z0 at least 0 (villa's load_3d "
                         f"shifts every channel for a negative start) and positive w, h, d; got {text!r}")
    return tuple(vals)


def _dense_off_cuda(*, path, device, skip_channels=None, sparse_prefetch_backend="tensorstore",
                    require_umbilicus=False):
    dev = torch.device(device)
    if dev.type == "cuda":
        return _orig_streaming(path=path, device=device, skip_channels=skip_channels,
                               sparse_prefetch_backend=sparse_prefetch_backend,
                               require_umbilicus=require_umbilicus)
    crop = crop_from_env()
    key = (str(path), str(dev), crop, tuple(sorted(skip_channels or ())), bool(require_umbilicus))
    if key in _last:
        return _last[key]
    _last.clear()                       # drop the previous load before reading another
    print(f"[kit-shim] dense load_3d instead of load_3d_streaming on {dev}, crop={crop}", flush=True)
    data = _orig_load_3d(path=path, device=dev, crop=crop, cuda_gridsample=False,
                         skip_channels=skip_channels, require_umbilicus=require_umbilicus)
    _last[key] = data
    return data


def _load_3d_in_box(**kwargs):
    """fit_data.load_3d (keyword-only), with KIT_LASAGNA_CROP as its crop off CUDA when the caller gives none."""
    if kwargs.get("crop") is None and torch.device(kwargs.get("device", "cpu")).type != "cuda":
        crop = crop_from_env()
        if crop is not None:
            kwargs["crop"] = crop
            print(f"[kit-shim] load_3d without a crop on {kwargs.get('device')}: crop={crop}", flush=True)
    return _orig_load_3d(**kwargs)


fit_data.load_3d_streaming = _dense_off_cuda
fit_data.load_3d = _load_3d_in_box

if __name__ == "__main__":
    raise SystemExit(fit.main(sys.argv[1:]))
