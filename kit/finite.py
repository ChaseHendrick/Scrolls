"""Finite-output guard: no speed, score or map counts when the output holds NaN or Inf, or fp16 would overflow.

A model that returns NaN still runs, so a benchmark will happily time it and a scorer will happily score it. A
common cause is a sum or mean taken in fp16, whose largest finite value is 65,504: the mean of one 128^3 tile of
values in [0, 1] (2,097,152 voxels) passes that limit, the sum becomes Inf and every output after it NaN. A timing
of a model that returns NaN is not a timing, and a score over NaN is not a score. This module makes the check one
line, for any array or saved map, and refuses before the number is written.

    from kit import finite
    finite.require(out, "normals")                          # raises NonFinite on NaN, Inf (or fp16 range with half=True)
    s, out = finite.timed(model, tile, name="model")        # seconds, output: refused when the output is not finite
    finite.sum_overflows(2_097_152, 1.0)                    # True: an fp16 sum of this many values in [0, 1] overflows

    python -m kit.finite check MAP.npy [MAP.tif ...] [--half] [--json]   # exit 0 finite, 1 not, 2 unreadable
    python -m kit.finite sum --count 2097152 --max 1.0 [--dtype float16] # exit 1 when the sum can overflow

Reads .npy and .npz with numpy, .tif/.tiff with tifffile and .zarr with zarr when they are installed; numpy is
needed for arrays. Read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

FP16_MAX = 65504.0
DTYPE_MAX = {"float16": FP16_MAX, "fp16": FP16_MAX, "half": FP16_MAX, "bfloat16": 3.3895e38,
             "float32": 3.4028e38, "fp32": 3.4028e38}
EXIT_OK, EXIT_FAIL, EXIT_INPUT = 0, 1, 2


class NonFinite(ValueError):
    """An output with NaN or Inf values (or past the fp16 range when half was asked): no number may be taken from
    it."""


def _np():
    import numpy as np   # noqa: PLC0415 (only the array helpers need it)
    return np


def stats(arr, half=False):
    """{"n", "nan", "inf", "finite_fraction", "min", "max", "absmax", "constant", "fp16_over", "ok"} for an array.
    ok is False when any value is NaN or Inf, or (half=True) when a finite value is past the fp16 range."""
    np = _np()
    a = np.asarray(arr)
    n = int(a.size)
    if n == 0:
        return {"n": 0, "nan": 0, "inf": 0, "finite_fraction": 0.0, "min": None, "max": None, "absmax": None,
                "constant": True, "fp16_over": 0, "ok": False, "why": "empty output"}
    if a.dtype.kind not in "biufc":
        raise TypeError(f"not a numeric array (dtype {a.dtype}): nothing to check")
    if a.dtype.kind in "biu":
        lo, hi = a.min(), a.max()
        return {"n": n, "nan": 0, "inf": 0, "finite_fraction": 1.0, "min": float(lo), "max": float(hi),
                "absmax": float(max(abs(float(lo)), abs(float(hi)))), "constant": bool(n > 1 and lo == hi),
                "fp16_over": 0, "ok": True, "why": ""}
    nan = int(np.isnan(a).sum())
    inf = int(np.isinf(a).sum())
    fin = a[np.isfinite(a)]
    lo = float(fin.min()) if fin.size else None
    hi = float(fin.max()) if fin.size else None
    absmax = None if lo is None else max(abs(lo), abs(hi))
    over = int((np.abs(fin.astype(np.float64)) > FP16_MAX).sum()) if half and fin.size else 0
    why = []
    if nan:
        why.append(f"{nan} NaN")
    if inf:
        why.append(f"{inf} Inf")
    if over:
        why.append(f"{over} values past the fp16 range ({FP16_MAX:g})")
    return {"n": n, "nan": nan, "inf": inf, "finite_fraction": (n - nan - inf) / n, "min": lo, "max": hi,
            "absmax": absmax, "constant": bool(fin.size > 1 and lo == hi), "fp16_over": over, "ok": not why,
            "why": ", ".join(why)}


def require(arr, name="output", half=False):
    """stats(arr) when the output is finite (and in fp16 range with half); else NonFinite naming what is wrong."""
    s = stats(arr, half)
    if not s["ok"]:
        raise NonFinite(f"{name}: {s['why']} of {s['n']} values: no speed, score or map may be taken from it")
    return s


def timed(fn, *args, name="output", half=False, repeat=1, clock=time.perf_counter, check=None, **kw):
    """(seconds per call, last output) for fn(*args, **kw) run `repeat` times; NonFinite when the last output (every
    numeric array in a tuple, list or dict it returns; strings and metadata are skipped) is not finite, so a bench
    never records a speed for NaN output. A function that writes in place passes check=lambda: BUFFER; a call with
    no numeric array to check is refused too, since its speed would be unchecked."""
    out, t0 = None, clock()
    for _ in range(max(1, int(repeat))):
        out = fn(*args, **kw)
    sec = (clock() - t0) / max(1, int(repeat))
    target = check() if check is not None else out
    seen = 0
    for i, part in enumerate(_parts(target)):
        arr = _numeric(_host(part))
        if arr is None:
            continue
        require(arr, f"{name}[{i}]" if i else name, half)
        seen += 1
    if not seen:
        raise NonFinite(f"{name}: the call returned no numeric array to check; pass check=lambda: BUFFER for a "
                        "function that writes in place")
    return sec, out


def _numeric(x):
    """x as a numeric numpy array, or None for None, strings, and other non-numeric values."""
    if x is None or isinstance(x, (str, bytes)):
        return None
    np = _np()
    try:
        a = np.asarray(x)
    except Exception:
        return None
    return a if a.dtype.kind in "biufc" and a.size else None


def _parts(out):
    if isinstance(out, dict):
        return list(out.values())
    if isinstance(out, (list, tuple)):
        return list(out)
    return [out]


def _host(x):
    """A numpy view of a torch tensor or anything array-like."""
    for attr in ("detach",):
        if hasattr(x, attr):
            x = x.detach()
    if hasattr(x, "cpu") and callable(x.cpu):
        x = x.cpu()
    if hasattr(x, "float") and callable(getattr(x, "float")) and hasattr(x, "numpy"):
        x = x.float()
    if hasattr(x, "numpy") and callable(x.numpy):
        x = x.numpy()
    return x


def sum_overflows(count, max_value, dtype="float16"):
    """True when a sum of `count` values of magnitude up to max_value can pass the largest finite value of dtype (an
    fp16 sum of 2,097,152 voxels in [0, 1] can reach 2.1 million, past 65,504): accumulate in fp32 on the host."""
    lim = DTYPE_MAX.get(str(dtype).lower())
    if lim is None:
        raise ValueError(f"dtype {dtype!r}: one of {', '.join(sorted(DTYPE_MAX))}")
    return float(count) * abs(float(max_value)) > lim


def load(path):
    """The array saved at path (.npy, .npz first array, .tif/.tiff, .zarr first array)."""
    p = Path(path)
    suf = p.suffix.lower()
    np = _np()
    if suf == ".npy":
        return np.load(p, mmap_mode="r")
    if suf == ".npz":
        with np.load(p) as z:
            return z[z.files[0]]
    if suf in (".tif", ".tiff"):
        import tifffile   # noqa: PLC0415
        return tifffile.imread(str(p))
    if suf == ".zarr" or p.is_dir():
        import zarr   # noqa: PLC0415
        z = zarr.open(str(p), mode="r")
        if hasattr(z, "shape"):
            return z[...]
        key = sorted(z.array_keys())[0]
        return z[key][...]
    raise ValueError(f"{p}: not .npy, .npz, .tif, .tiff or .zarr")


def add_arguments(p):
    a = p.add_subparsers(dest="action", required=True)
    c = a.add_parser("check", help="every file finite (exit 0), else 1; 2 when one cannot be read")
    c.add_argument("paths", nargs="+")
    c.add_argument("--half", action="store_true", help="also refuse finite values past the fp16 range")
    c.add_argument("--json", action="store_true")
    s = a.add_parser("sum", help="can an fp16 (or --dtype) sum of COUNT values up to MAX overflow? exit 1 when it can")
    s.add_argument("--count", type=float, required=True)
    s.add_argument("--max", type=float, required=True, dest="max_value")
    s.add_argument("--dtype", default="float16")
    s.add_argument("--json", action="store_true")


def run(args, say=print):
    if args.action == "sum":
        if args.dtype.lower() not in DTYPE_MAX:
            say(f"unknown --dtype {args.dtype!r}: one of {', '.join(sorted(DTYPE_MAX))}")
            return EXIT_INPUT
        over = sum_overflows(args.count, args.max_value, args.dtype)
        rec = {"count": args.count, "max": args.max_value, "dtype": args.dtype, "overflows": over,
               "largest": args.count * abs(args.max_value), "limit": DTYPE_MAX[args.dtype.lower()]}
        if args.json:
            say(json.dumps(rec))
        else:
            say(f"{'OVERFLOWS' if over else 'fits'}: a {args.dtype} sum of {args.count:g} values up to "
                f"{args.max_value:g} can reach {rec['largest']:g} (limit {rec['limit']:g})"
                + ("; accumulate in fp32 on the host" if over else ""))
        return EXIT_FAIL if over else EXIT_OK
    out, code = [], EXIT_OK
    for path in args.paths:
        try:
            s = stats(load(path), args.half)
        except Exception as e:   # unreadable is its own exit code, never a pass
            out.append({"path": path, "error": str(e)})
            code = max(code, EXIT_INPUT)
            continue
        s["path"] = path
        out.append(s)
        if not s["ok"]:
            code = max(code, EXIT_FAIL)
    if args.json:
        say(json.dumps(out, indent=1))
    else:
        for s in out:
            if "error" in s:
                say(f"UNREADABLE {s['path']}: {s['error']}")
            else:
                say(f"{'finite' if s['ok'] else 'NOT FINITE'} {s['path']}: n={s['n']} min={s['min']} max={s['max']}"
                    + (f" ({s['why']})" if s['why'] else "") + (" constant" if s["constant"] else ""))
    return code


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.finite", description=__doc__.splitlines()[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
