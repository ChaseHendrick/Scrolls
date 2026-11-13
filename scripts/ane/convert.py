"""Convert a traced ink model to a Core ML package for the Apple Neural Engine.

Usage:
  python convert.py TRACED.pt OUT.mlpackage SHAPE

TRACED.pt is a TorchScript trace (export_ckpt.py writes one). SHAPE is the input shape it was traced at,
comma-separated: B,1,D,P,P for a whole ink model, such as 16,1,17,128,128 for ink_9um at batch 16. All three
arguments are required; the shape is not read from the trace.

It writes OUT.mlpackage: a float16 ML program with one input named "x" of that fixed shape, compute units
CPU_AND_NE (the Neural Engine, with the CPU for what it cannot run), for macOS 15 or later. coreml_server.py runs
the package.

Needs coremltools and torch in the same Python (coremltools 9.0 with torch 2.7 on Python 3.12 is a pair that has
worked; coremltools 9.0 has no build for Python 3.14). float16 on the Neural Engine is not bit-equal to float32 on
a CPU or GPU, so compare a map from the package with one from the checkpoint before relying on it.
"""
import argparse, sys, warnings


def _shape(text):
    try:
        shape = tuple(int(v) for v in text.split(","))
    except ValueError:
        shape = ()
    if not shape or min(shape) < 1:
        raise argparse.ArgumentTypeError("SHAPE must be positive integers separated by commas, such as 16,1,17,128,128")
    return shape


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert a traced ink model to a Core ML package (float16, CPU_AND_NE)")
    ap.add_argument("traced", metavar="TRACED.pt", help="TorchScript trace, as export_ckpt.py writes it")
    ap.add_argument("out", metavar="OUT.mlpackage", help="the Core ML package to write")
    ap.add_argument("shape", metavar="SHAPE", type=_shape, help="input shape of the trace, such as 16,1,17,128,128")
    a = ap.parse_args(argv)
    try:
        import torch, coremltools as ct
    except ImportError as e:
        raise SystemExit("convert.py needs torch and coremltools in this Python (%s): %s" % (sys.executable, e))
    warnings.filterwarnings("ignore")
    tr = torch.jit.load(a.traced).eval(); shape = a.shape
    ml = ct.convert(tr, inputs=[ct.TensorType(name="x", shape=shape)], convert_to="mlprogram", compute_precision=ct.precision.FLOAT16,
                    compute_units=ct.ComputeUnit.CPU_AND_NE, minimum_deployment_target=ct.target.macOS15)
    ml.save(a.out); print("saved", a.out, shape)
    return 0


if __name__ == "__main__":
    sys.exit(main())
