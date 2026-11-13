"""Core ML model server over a pipe: float32 batches in on stdin, the model's float32 output out on stdout.

Usage:
  python coreml_server.py PACKAGE.mlpackage [UNITS]

PACKAGE is a Core ML package with one input named "x" of a fixed shape (convert.py makes one). UNITS is a Core ML
compute unit name: CPU_AND_NE (the default: the Neural Engine, with the CPU for what it cannot run), ALL,
CPU_AND_GPU or CPU_ONLY.

It is a process of its own because coremltools often needs another Python than the caller's (coremltools 9.0 has no
build for Python 3.14, for one). inkpreview.py starts it with the Python that the environment variable COREML_PY
names. Prediction needs macOS; the script needs coremltools and numpy.

Protocol, on stdin and stdout:
  1. The server writes one text line, READY <input shape> <output shape>, shapes comma-separated as the package
     fixes them.
  2. For each batch the caller writes an 8-byte little-endian byte count, then a float32 array of the input shape in
     C order.
  3. The server answers with an 8-byte little-endian byte count and the model's first output as float32.
The server ends when stdin closes. Nothing but the protocol goes to stdout.
"""
import argparse, struct, sys

UNITS = ("CPU_AND_NE", "ALL", "CPU_AND_GPU", "CPU_ONLY")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Core ML model server over a pipe (float32 batches in, output out)")
    ap.add_argument("package", metavar="PACKAGE.mlpackage", help="Core ML package with one fixed-shape input named x")
    ap.add_argument("units", nargs="?", default="CPU_AND_NE", choices=UNITS, metavar="UNITS",
                    help="Core ML compute units: %s (default CPU_AND_NE)" % ", ".join(UNITS))
    a = ap.parse_args(argv)
    try:
        import numpy as np, coremltools as ct
    except ImportError as e:
        raise SystemExit("coreml_server.py needs numpy and coremltools in this Python (%s): %s" % (sys.executable, e))
    ml = ct.models.MLModel(a.package, compute_units=getattr(ct.ComputeUnit, a.units))
    spec = ml.get_spec().description
    ishape = tuple(int(v) for v in spec.input[0].type.multiArrayType.shape)
    oshape = tuple(int(v) for v in spec.output[0].type.multiArrayType.shape) or None
    if not oshape:  # ML programs may leave the output shape open: run once on zeros
        oshape = np.asarray(list(ml.predict({"x": np.zeros(ishape, np.float32)}).values())[0]).shape
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    out.write(("READY %s %s\n" % (",".join(map(str, ishape)), ",".join(map(str, oshape)))).encode()); out.flush()
    while True:
        h = inp.read(8)
        if len(h) < 8:
            break
        n = struct.unpack("<Q", h)[0]
        x = np.frombuffer(inp.read(n), dtype=np.float32).reshape(ishape).copy()
        y = np.ascontiguousarray(list(ml.predict({"x": x}).values())[0], dtype=np.float32)
        out.write(struct.pack("<Q", y.nbytes)); out.write(y.tobytes()); out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
