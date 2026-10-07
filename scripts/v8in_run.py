"""Run v8in (YoussefMoNader/ink-8um-v8in) on a layer folder, optionally in fp16 on the Mac GPU.

Same as the model's own predict.py (it calls the same predict_surface), plus `--fp16`: an
outer torch.autocast for MPS. The release enables fp16 autocast only on CUDA, so on a Mac
it runs fp32. fp16 can change the map, so scripts/mac-w045.sh accepts it only after the
CPU-vs-MPS crop check passes with it on.

    python scripts/v8in_run.py --model-dir CKPT_DIR --layers LAYERS --output map.npy \
        --device mps [--fp16] [--reverse] [--stride 21] [--batch-size 16]
"""

import argparse
import contextlib
import sys
import time
from pathlib import Path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-dir", type=Path, required=True, help="local snapshot of the v8in repository")
    p.add_argument("--layers", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True, help=".npy (float32), .tif (16-bit) or .png")
    p.add_argument("--device", default="cpu")
    p.add_argument("--fp16", action="store_true", help="fp16 autocast on MPS (CUDA already uses it)")
    p.add_argument("--reverse", action="store_true", help="reverse the depth order of the layers")
    p.add_argument("--stride", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args(argv)

    sys.path.insert(0, str(args.model_dir))
    import torch
    from ink8um import InkDetector, predict_surface, save_prediction

    if args.fp16 and not args.device.startswith("mps"):
        p.error("--fp16 is for MPS; CUDA already runs fp16 and the CPU stays fp32")
    model = InkDetector.from_pretrained(str(args.model_dir))
    started = time.time()
    last = [0.0]

    def progress(done, total):
        if time.time() - last[0] > 30 or done == total:
            last[0] = time.time()
            print(f"  {done}/{total} tiles ({time.time() - started:.0f}s)", flush=True)

    autocast = (torch.autocast(device_type="mps", dtype=torch.float16) if args.fp16
                else contextlib.nullcontext())
    with autocast:
        prediction = predict_surface(model, args.layers, reverse=args.reverse, stride=args.stride,
                                     batch_size=args.batch_size, num_workers=args.workers,
                                     device=args.device, progress=progress)
    save_prediction(prediction, args.output)
    print(f"device={args.device} fp16={args.fp16} reverse={args.reverse} stride={args.stride or model.stride} "
          f"done in {time.time() - started:.0f}s; shape={prediction.shape} mean={prediction.mean():.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
