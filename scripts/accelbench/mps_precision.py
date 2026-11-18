"""Which precision is fastest on this GPU for 2D and 3D convolution networks: fp32, fp16 or bf16 autocast, for
inference and for a training step, with the CPU in fp32 beside them.

On an Apple M1 Pro, five timed steps of a 2D ink model benchmark were 1.23 times faster in fp16, and those of a 3D
model about 9 percent slower (16 Oct 2026), while kit.accel's --precision auto then picked fp16 on MPS for every
model. This script times longer runs of three synthetic networks so the default can follow a measurement.
The networks and inputs are random (no scroll data, no weights); a receipt is a timing record only.

  python3 scripts/accelbench/mps_precision.py OUT_DIR [--device auto] [--nets conv2d,conv3d,unet3d]
                                              [--precisions fp32,fp16,bf16] [--modes infer,train]
                                              [--repeats 20] [--cpu-repeats 5] [--no-cpu] [--overwrite]

Writes OUT_DIR/<net>-<mode>.json (kit.accelbench timing receipts, one arm per device and precision) and
OUT_DIR/summary.json, and prints one line per arm: median seconds per call, the speed against fp32 on the same
device, and for inference the largest difference from the fp32 output on that device. A precision the device
refuses is recorded as skipped, not as an error.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# name: (input shape without the batch, batch)
NETS = {
    "conv2d": ((16, 128, 128), 16),      # a 2D ink model's 16 depth slices as channels
    "conv3d": ((1, 16, 64, 64), 8),      # a 3D ink model's stack of a depth window
    "unet3d": ((1, 64, 64, 64), 2),      # a small nnU-Net-like 3D encoder and decoder
}


def build(name):
    import torch.nn as nn
    if name == "conv2d":
        layers, c = [], 16
        for out in (64, 64, 128, 128, 128, 64):
            layers += [nn.Conv2d(c, out, 3, padding=1), nn.BatchNorm2d(out), nn.ReLU(inplace=True)]
            c = out
        return nn.Sequential(*layers, nn.Conv2d(c, 1, 1))
    if name == "conv3d":
        layers, c = [], 1
        for out in (32, 32, 64, 64, 64, 32):
            layers += [nn.Conv3d(c, out, 3, padding=1), nn.BatchNorm3d(out), nn.ReLU(inplace=True)]
            c = out
        return nn.Sequential(*layers, nn.Conv3d(c, 1, 1))
    if name == "unet3d":
        def block(i, o):
            return nn.Sequential(nn.Conv3d(i, o, 3, padding=1), nn.InstanceNorm3d(o, affine=True),
                                 nn.LeakyReLU(0.01, inplace=True), nn.Conv3d(o, o, 3, padding=1),
                                 nn.InstanceNorm3d(o, affine=True), nn.LeakyReLU(0.01, inplace=True))

        class UNet(nn.Module):
            def __init__(self):
                super().__init__()
                self.e1, self.e2, self.e3 = block(1, 16), block(16, 32), block(32, 64)
                self.pool = nn.MaxPool3d(2)
                self.u2, self.d2 = nn.ConvTranspose3d(64, 32, 2, stride=2), block(64, 32)
                self.u1, self.d1 = nn.ConvTranspose3d(32, 16, 2, stride=2), block(32, 16)
                self.out = nn.Conv3d(16, 1, 1)

            def forward(self, x):
                import torch
                a = self.e1(x)
                b = self.e2(self.pool(a))
                c = self.e3(self.pool(b))
                b = self.d2(torch.cat([self.u2(c), b], 1))
                return self.out(self.d1(torch.cat([self.u1(b), a], 1)))
        return UNet()
    raise ValueError(f"unknown net {name!r}; use {', '.join(NETS)}")


def arm(name, mode, device, precision, seed=20261023):
    """(callable, setup, reference output or None) for one network, mode, device and precision."""
    import torch
    from kit import accel
    torch.manual_seed(seed)
    net = build(name).to(device)
    shape, batch = NETS[name]
    x = torch.randn(batch, *shape, generator=torch.Generator().manual_seed(seed + 1)).to(device)
    if mode == "infer":
        net.eval()

        def fn():
            with torch.inference_mode(), accel.autocast(device, precision):
                return net(x)
        return fn
    net.train()
    opt = torch.optim.SGD(net.parameters(), lr=1e-3)
    scaler = accel.grad_scaler(device, precision)

    def step():
        opt.zero_grad(set_to_none=True)
        with accel.autocast(device, precision):
            loss = net(x).float().pow(2).mean()
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
    return step


def max_diff(a, b):
    return float((a.float().cpu() - b.float().cpu()).abs().max())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("out_dir")
    p.add_argument("--device", default="auto", help="auto (CUDA, then MPS, then CPU), mps, cuda, cuda:N or cpu")
    p.add_argument("--nets", default=",".join(NETS))
    p.add_argument("--precisions", default="fp32,fp16,bf16")
    p.add_argument("--modes", default="infer,train")
    p.add_argument("--repeats", type=int, default=20)
    p.add_argument("--warmup", type=int, default=3)
    p.add_argument("--cpu-repeats", type=int, default=5, help="repeats of the CPU fp32 arm (it is slow; at least 5)")
    p.add_argument("--no-cpu", action="store_true", help="skip the CPU fp32 arm")
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args(argv)
    if sys.stdout.isatty():              # the Scrolls look (AGENTS.md rule 17)
        from kit import termstyle
        termstyle.script("mps_precision")
    import torch
    from kit import accel, accelbench
    device = accel.resolve_device(a.device)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = {"device": str(device), "torch": torch.__version__, "threads": torch.get_num_threads(),
               "nets": {k: {"input": list(v[0]), "batch": v[1]} for k, v in NETS.items()}, "rows": []}
    for name in a.nets.split(","):
        for mode in a.modes.split(","):
            timings, ref = {}, None
            arms = [(str(device), pr, False) for pr in a.precisions.split(",")]
            if not a.no_cpu and accel.device_type(device) != "cpu":
                arms.append(("cpu", "fp32", True))
            for dev, pr, slow in arms:
                label = f"{dev}-{pr}"
                try:
                    fn = arm(name, mode, dev, pr)
                    y = fn()
                    accel.synchronize(dev)
                except (RuntimeError, ValueError, TypeError) as e:
                    summary["rows"].append({"net": name, "mode": mode, "arm": label, "skipped": str(e)[:300]})
                    print(f"{name:7} {mode:5} {label:12} skipped: {str(e).splitlines()[0][:120]}")
                    continue
                t = accelbench.time_callable(fn, device=dev, warmup=1 if slow else a.warmup,
                                             repeats=a.cpu_repeats if slow else a.repeats)
                timings[label] = t
                row = {"net": name, "mode": mode, "arm": label, "median_s": t["median_s"], "min_s": t["min_s"],
                       "spread": t["spread"]}
                if mode == "infer" and dev == str(device):
                    if pr == "fp32":
                        ref = y
                    elif ref is not None:
                        row["max_diff_vs_fp32"] = max_diff(y, ref)
                base = next((r for r in summary["rows"] if r["net"] == name and r["mode"] == mode
                             and r["arm"] == f"{device}-fp32" and "median_s" in r), None)
                if base and label != base["arm"]:
                    row["x_vs_fp32"] = round(base["median_s"] / t["median_s"], 3)
                summary["rows"].append(row)
                extra = "".join(f"  {k} {row[k]:.4g}" for k in ("x_vs_fp32", "max_diff_vs_fp32") if k in row)
                print(f"{name:7} {mode:5} {label:12} {t['median_s']:.4f} s per call{extra}")
            if timings:
                rec = accelbench.timing_receipt(f"mps_precision {name} {mode}", timings, device=str(device),
                                                sizes={"input": list(NETS[name][0]), "batch": NETS[name][1]},
                                                source_files=("scripts/accelbench/mps_precision.py", "kit/accel.py"),
                                                root=ROOT)
                accelbench.write_receipt(rec, out / f"{name}-{mode}.json", overwrite=a.overwrite)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
