#!/usr/bin/env python3
"""Benchmark the UV gate on the texture coordinates of a triangular OBJ.

--obj-uv reads each triangular face's texture indices, preserving per-corner UV,
face order and original units. Materials and texture images are never opened.
It does not assess 3D self-intersection, ink or reading.

Each invocation launches one fresh worker. Gate timing excludes OBJ loading,
UV extraction and hashing. Whole-process wall time includes worker startup and
all preparation. Peak RSS is the worker's whole-process high-water mark, not a
baseline-subtracted gate allocation. Repeat the command for independent runs.

Example (large runs use the spatial method, never the quadratic reference):
  python scripts/bench_uvgate.py --obj-uv WORK/w039_flattened.obj \
      --triangles all --method grid --collect-pairs --output WORK/w039-full.json
"""
from __future__ import annotations

import argparse
from array import array
import math
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REFERENCE_LIMIT = 2000


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_obj_uv(path, triangles=None, selection="prefix", seed=0):
    """Load triangular OBJ face-corner vt coordinates without opening assets.

    Positive indices resolve against final counts; negative indices resolve at
    the face line. Keep every face, including degenerate ones. Refuse missing UV
    and nontriangular faces rather than silently changing the tested geometry.
    Random subsets are sorted by original face index for stable pair witnesses.
    """
    import numpy as np

    if triangles is not None and (isinstance(triangles, bool) or
                                  not isinstance(triangles, int) or triangles <= 0):
        raise ValueError("triangles must be a positive integer, or all")
    if selection not in ("prefix", "random"):
        raise ValueError("selection must be prefix or random")
    path = Path(path).resolve()
    digest = file_sha256(path)
    size = path.stat().st_size
    coords, corners = array("d"), array("q")
    vertices = max_vertex = 0

    def index(token, count):
        value = int(token)
        if not value:
            raise ValueError("OBJ indices cannot be zero")
        resolved = value - 1 if value > 0 else count + value
        if resolved < 0:
            raise ValueError("relative index is out of range")
        return resolved

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.partition("#")[0].split()
            if not fields:
                continue
            kind, values = fields[0], fields[1:]
            try:
                if kind == "v":
                    if len(values) < 3 or not all(math.isfinite(float(v)) for v in values[:3]):
                        raise ValueError("vertex needs three finite coordinates")
                    vertices += 1
                elif kind == "vt":
                    if len(values) not in (2, 3):
                        raise ValueError("texture coordinate needs two values (optional third zero)")
                    uv = [float(v) for v in values]
                    if not all(math.isfinite(v) for v in uv) or (len(uv) == 3 and uv[2] != 0):
                        raise ValueError("texture coordinates must be finite and two-dimensional")
                    coords.extend(uv[:2])
                elif kind == "f":
                    if len(values) != 3:
                        raise ValueError("only triangular OBJ faces are supported")
                    for token in values:
                        parts = token.split("/")
                        if len(parts) not in (2, 3) or not parts[0] or not parts[1]:
                            raise ValueError("each face corner needs vertex/texture indices")
                        max_vertex = max(max_vertex, index(parts[0], vertices) + 1)
                        corners.append(index(parts[1], len(coords) // 2))
                # Material, normal, group and object records are not UV inputs.
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"{path.name}:{line_number}: {exc}") from exc
    uv = np.frombuffer(coords, dtype=np.float64).reshape(-1, 2)
    faces = np.frombuffer(corners, dtype=np.int64).reshape(-1, 3)
    if not len(uv) or not len(faces):
        raise ValueError("OBJ needs texture coordinates and triangular faces")
    if max_vertex > vertices or np.max(faces) >= len(uv):
        raise ValueError("OBJ face index is out of range")
    full_triangles = len(faces)
    count = full_triangles if triangles is None else triangles
    if count > full_triangles:
        raise ValueError(f"requested {count} triangles, but OBJ has {full_triangles}")
    if selection == "random" and count < full_triangles:
        indices = np.sort(np.random.default_rng(seed).choice(full_triangles, count, replace=False))
    else:
        indices = np.arange(count, dtype=np.int64)
    result = np.asarray(uv[faces[indices]], dtype="<f8")
    if path.stat().st_size != size or file_sha256(path) != digest:
        raise RuntimeError("OBJ changed while loading")
    return result, {
        "obj": str(path), "domain": "OBJ per-corner vt coordinates in original units",
        "limitation": "Released flattening geometry only; no texture, ink, 3D overlap or reading assessment.",
        "selection": selection, "seed": seed,
        "vertices": vertices, "uv_vertices": len(uv),
        "full_triangles": full_triangles, "triangles": len(result),
        "uv_bounds": [uv.min(axis=0).tolist(), uv.max(axis=0).tolist()],
        "face_order": "original OBJ order, including degenerate faces; texture seams preserved",
        "units": "original vt values, no normalization or rescaling; abs_eps is in squared UV units",
        "array_dtype": result.dtype.str, "array_bytes": result.nbytes,
        "triangles_sha256": hashlib.sha256(memoryview(result).cast("B")).hexdigest(),
        "face_indices_sha256": hashlib.sha256(indices.astype("<i8").tobytes()).hexdigest(),
        "files": {"obj": {"bytes": size, "sha256": digest}},
    }


def peak_rss_bytes():
    # Darwin reports bytes; Linux reports KiB. Restrict this conversion to those
    # documented platform conventions rather than silently guessing elsewhere.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(value)
    if sys.platform.startswith("linux"):
        return int(value * 1024)
    return None


def benchmark(args):
    import numpy as np
    try:
        import tifffile
    except ImportError:  # optional; recorded only so receipts name the environment
        tifffile = None
    from kit.uvgate import uv_overlap_gate

    if args.method == "reference" and (args.triangles is None or args.triangles > REFERENCE_LIMIT):
        raise ValueError(f"quadratic reference is limited to {REFERENCE_LIMIT} triangles")
    started = time.perf_counter()
    triangles, source = load_obj_uv(args.obj_uv, args.triangles, args.selection, args.seed)
    preparation = time.perf_counter() - started
    source_files = ("kit/uvgate.py", "scripts/bench_uvgate.py")
    hashes = {name: file_sha256(ROOT / name) for name in source_files}
    gate_wall_start = time.perf_counter()
    gate_cpu_start = time.process_time()
    verdict = uv_overlap_gate(triangles, abs_eps=args.abs_eps, method=args.method, collect_pairs=args.collect_pairs)
    gate_cpu = time.process_time() - gate_cpu_start
    gate_wall = time.perf_counter() - gate_wall_start
    for name, digest in hashes.items():
        if file_sha256(ROOT / name) != digest:
            raise RuntimeError(f"source changed during benchmark: {name}")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report = {
        "schema": 1, "source": source, "method": args.method, "abs_eps": args.abs_eps,
        "collect_pairs": args.collect_pairs, "verdict": verdict,
        "preparation_wall_seconds": preparation, "gate_wall_seconds": gate_wall,
        "gate_cpu_seconds": gate_cpu, "worker_cpu_seconds_to_receipt": usage.ru_utime + usage.ru_stime,
        "worker_peak_rss_bytes": peak_rss_bytes(),
        "memory_scope": "fresh worker whole-process high-water RSS, including imports and preparation",
        "implementation_sha256": hashes,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                    "tifffile": tifffile.__version__ if tifffile else None, "platform": platform.platform(),
                    "machine": platform.machine(), "logical_cpu_count": os.cpu_count()},
    }
    return report


def triangle_count(value):
    if value == "all":
        return None
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer or all") from exc
    if count <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer or all")
    return count


def main(argv=None):
    args_in = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--obj-uv", type=Path, required=True, help="local triangular OBJ with face texture indices")
    parser.add_argument("--triangles", type=triangle_count, default=1000000, help="positive count, or all")
    parser.add_argument("--selection", choices=("prefix", "random"), default="prefix")
    parser.add_argument("--seed", type=int, default=0, help="seed for random face selection")
    parser.add_argument("--abs-eps", type=float, default=1e-12, help="overlap area threshold in squared UV units")
    parser.add_argument("--timeout-seconds", type=float, default=300, help="whole worker timeout")
    parser.add_argument("--method", choices=("auto", "grid", "reference"), default="grid")
    parser.add_argument("--collect-pairs", action="store_true", help="ask gate for all overlap pair diagnostics")
    parser.add_argument("--output", type=Path, help="JSON result path; stdout is always JSON")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(args_in)
    if not math.isfinite(args.abs_eps) or args.abs_eps < 0:
        parser.error("--abs-eps must be finite and nonnegative")
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be finite and positive")
    if args.worker:
        try:
            report = benchmark(args)
        except (ValueError, RuntimeError) as exc:
            parser.error(str(exc))
    else:
        started = time.perf_counter()
        try:
            child = subprocess.run([sys.executable, str(Path(__file__).resolve()), *args_in, "--worker"],
                                   capture_output=True, text=True, timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            parser.error(f"worker exceeded {args.timeout_seconds:g} seconds; no result written")
        whole_wall = time.perf_counter() - started
        if child.returncode:
            sys.stderr.write(child.stderr)
            return child.returncode
        report = json.loads(child.stdout)
        report["whole_process_wall_seconds"] = whole_wall
        report["whole_process_wall_scope"] = "fresh worker startup through exit, including preparation and JSON serialization"
    payload = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output and not args.worker:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + f".{os.getpid()}.tmp")
        temporary.write_text(payload)
        temporary.replace(args.output)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
