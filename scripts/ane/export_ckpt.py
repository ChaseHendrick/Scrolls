"""Trace a villa ink checkpoint to TorchScript at a fixed batch size, ready for Core ML or for direct use.

Usage:
  python export_ckpt.py CKPT OUT.pt BATCH [NORM]

CKPT is a flat ink checkpoint in villa's format, such as ink_9um's step-075000.pth or a fine-tune of it. OUT.pt is
the TorchScript trace to write, at input shape (BATCH, 1, depth, patch, patch) with depth and patch read from the
checkpoint's own config (17 and 128 for ink_9um). The trace outputs logits. inkpreview.py runs it as it is
(--backend torchscript --model OUT.pt --input-shape BATCH,1,depth,patch,patch) and convert.py turns it into a
Core ML package.

Needs, in the Python that runs it:
  torch
  villa's vesuvius package, importable (from a villa checkout: the vesuvius folder set up with its models extra,
  see villa's vesuvius/README.md). The model is built and loaded by villa's own
  vesuvius.ink_detection.inference.infer.configure_model, so the weights and the network are villa's.

What it changes in the network: every InstanceNorm3d (5D input) runs as the equivalent 4D instance norm, because
the Core ML conversion this was written for (coremltools 9.0) did not convert the 5D one. The script runs the model
on one random batch before and after the change and prints the largest difference as swap_maxdiff in a JSON line,
with ckpt, patch, depth, batch, norm, split and out_shape. Read that line: the input shape for convert.py and
inkpreview.py is (batch, 1, depth, patch, patch), and swap_maxdiff should be near 0.

NORM (optional):
  in4d  the default, described above.
  hier  every InstanceNorm, 2D ones too, computes its mean and centered variance in two levels: over blocks of at
        most HIER_BLOCK elements (environment variable, default 1024), then over the block means, so the float16
        sums on the Neural Engine stay short. A numeric variant to test, not the default.

Environment variables:
  HIER_BLOCK  block size for NORM hier (default 1024).
  SPLIT       1 traces only the 2D U-Net; its input is then the output of the network's 3D depth-fusion stem, which
              the caller runs elsewhere. inkpreview.py does not use split traces.

Cautions: villa loads a checkpoint with torch.load and pickle, which runs code from the file, so trace only
checkpoints you trust. villa loads weights without requiring every key to match; read its log lines about missing
or unexpected keys before using the trace.
"""
import argparse, json, os, sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trace a villa ink checkpoint to TorchScript at a fixed batch size")
    ap.add_argument("ckpt", metavar="CKPT", help="flat ink checkpoint in villa's format")
    ap.add_argument("out", metavar="OUT.pt", help="TorchScript file to write")
    ap.add_argument("batch", metavar="BATCH", type=int, help="batch size of the trace")
    ap.add_argument("norm", metavar="NORM", nargs="?", default="in4d", choices=("in4d", "hier"),
                    help="in4d (default) or hier, the two-level instance norm")
    a = ap.parse_args(argv)
    if a.batch < 1:
        ap.error("BATCH must be at least 1")
    ck, out, B, NORM = a.ckpt, a.out, a.batch, a.norm
    HB = int(os.environ.get("HIER_BLOCK", "1024")); SPLIT = os.environ.get("SPLIT", "0") == "1"
    try:
        import torch, torch.nn as nn, torch.nn.functional as F
        from vesuvius.ink_detection.inference.infer import configure_model
    except ImportError as e:
        raise SystemExit("export_ckpt.py needs torch and villa's vesuvius package in this Python (%s): %s"
                         % (sys.executable, e))
    cm = configure_model(argparse.Namespace(checkpoint=ck, amp_dtype="default"))
    m = cm.model.eval().float()

    class IN4D(nn.Module):
        def __init__(self, src): super().__init__(); self.src = src

        def forward(self, x):
            n, c = x.shape[:2]; sh = x.shape
            if NORM != "hier":
                y = F.instance_norm(x.reshape(n, c, -1, x.shape[-1]), weight=self.src.weight, bias=self.src.bias, use_input_stats=True, eps=self.src.eps)
                return y.reshape(sh)
            L = 1
            for v in sh[2:]: L *= int(v)
            b = HB
            while L % b: b //= 2
            xb = x.reshape(n, c, L // b, b)
            mu = xb.mean(dim=3, keepdim=True).mean(dim=2, keepdim=True)
            xc = xb - mu
            var = (xc * xc).mean(dim=3, keepdim=True).mean(dim=2, keepdim=True)
            y = xc * torch.rsqrt(var + self.src.eps) * self.src.weight.view(1, c, 1, 1) + self.src.bias.view(1, c, 1, 1)
            return y.reshape(sh)

    def swap(mod):
        for k, ch in mod.named_children():
            if type(ch).__name__ == "InstanceNorm3d" or (NORM == "hier" and type(ch).__name__ == "InstanceNorm2d"): setattr(mod, k, IN4D(ch))
            else: swap(ch)

    P, D = cm.patch_size, cm.input_depth
    P = P[0] if isinstance(P, (tuple, list)) else P
    x = torch.randn(B, 1, D, P, P)

    class Net2D(nn.Module):
        def __init__(self, net): super().__init__(); self.net = net

        def forward(self, f):
            o = self.net(f)["ink"]
            return o[0] if isinstance(o, (list, tuple)) else o

    with torch.no_grad():
        y0 = m(x); swap(m); y1 = m(x)
        print(json.dumps(dict(ckpt=ck, patch=P, depth=D, batch=B, norm=NORM, split=SPLIT, out_shape=list(y1.shape), swap_maxdiff=float((y1 - y0).abs().max()))))
        if SPLIT:
            f = m.model.depth_fusion(x); t = Net2D(m.model.network).eval(); torch.jit.trace(t, f, check_trace=False).save(out)
        else:
            torch.jit.trace(m, x, check_trace=False).save(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
