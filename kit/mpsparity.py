"""CPU-versus-MPS (or CUDA) check that a small training run gives the same result on two devices.

A torch training script that gains a ``--device`` flag can run on Apple's GPU, but MPS kernels are not the CPU's
kernels: an operator can be missing, slower to converge or plainly different. This module checks, before a GPU
run is trusted, that a network trains the same on DEV as on REF (default mps against cpu). It uses seeded
synthetic inputs: a check of the device, not of a model's quality. Built-in networks (``conv3d``, ``conv2d``,
``unet3d``) cover the common layers; ``--script PATH --build NAME --shape B,C,D,H,W`` checks your own network.

Per network, three checks, each with a control that must be able to fail (AGENTS hard rule 4):

- ``forward``: eval-mode output on DEV against REF, as the largest difference over the reference output's
  standard deviation. Control: REF's output for the input with its depth order reversed must differ by at
  least ten times the tolerance; otherwise the check is VOID.
- ``grad``: one train-mode backward pass (dropout off, so both devices draw nothing at random), as the norm of
  the gradient difference over the reference gradient's norm. Control: the gradient for the reversed input.
- ``train``: STEPS AdamW steps on identical CPU-drawn batches, as the distance between the two final weight
  sets over the distance the reference moved from the start. Control: the reference trained on another batch
  order must sit at least ten times the tolerance away.

``--bench N`` times N training steps at the network's real batch and shape on DEV (seconds a step, and on MPS
the driver memory), for a time estimate. ``ops`` probes operators that 3D data paths use (3D grid_sample,
generators on the device and the like) on DEV against the CPU.

  python -m kit.mpsparity run [--models conv3d,conv2d,unet3d] [--device mps] [--ref cpu] [--steps 10]
                              [--bench 0] [--bar fixed|bf16] [--out FILE] [--json]
  python -m kit.mpsparity run --script PATH --build NAME --shape B,C,D,H,W [--real-shape B,C,D,H,W] ...
  python -m kit.mpsparity ops [--device mps] [--json]
  python -m kit.mpsparity list

Exit 0 when every check passed, 1 when one failed or was VOID, 2 on a usage error. A PASS says the device
trains this network like the reference on synthetic inputs; it does not move a number measured on one device
to another without its own check.
"""
import argparse
import copy
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

FWD_TOL, GRAD_TOL, TRAIN_TOL = 1e-3, 1e-3, 0.02
CONTROL_FACTOR = 10.0

def _conv3d():
    nn = _torch().nn
    return nn.Sequential(nn.Conv3d(1, 16, 3, padding=1), nn.GroupNorm(4, 16), nn.ReLU(),
                         nn.Conv3d(16, 16, 3, padding=1), nn.GroupNorm(4, 16), nn.ReLU(),
                         nn.Dropout3d(0.1), nn.Conv3d(16, 1, 1))


def _conv2d():
    torch = _torch()
    nn = torch.nn

    class DepthAsChannels(nn.Module):
        """A 2D network that reads a (B, 1, D, H, W) stack with its D slices as channels."""
        def __init__(self, depth=16):
            super().__init__()
            layers, c = [], depth
            for out in (32, 32, 16):
                layers += [nn.Conv2d(c, out, 3, padding=1), nn.BatchNorm2d(out), nn.ReLU()]
                c = out
            self.body = nn.Sequential(*layers, nn.Conv2d(c, 1, 1))

        def forward(self, x):
            return self.body(x.flatten(1, 2))
    return DepthAsChannels()


def _unet3d():
    torch = _torch()
    nn = torch.nn

    def block(i, o):
        return nn.Sequential(nn.Conv3d(i, o, 3, padding=1), nn.InstanceNorm3d(o, affine=True), nn.LeakyReLU(0.01))

    class UNet3D(nn.Module):
        """Two levels: conv blocks, a strided down step, ConvTranspose3d up and a skip join."""
        def __init__(self, c=8):
            super().__init__()
            self.e1, self.down, self.e2 = block(1, c), nn.Conv3d(c, 2 * c, 2, stride=2), block(2 * c, 2 * c)
            self.up, self.d1, self.head = nn.ConvTranspose3d(2 * c, c, 2, stride=2), block(2 * c, c), nn.Conv3d(c, 1, 1)

        def forward(self, x):
            a = self.e1(x)
            b = self.e2(self.down(a))
            return self.head(self.d1(torch.cat([self.up(b), a], 1)))
    return UNet3D()


# name: what builds the network, the small parity shape (batch, channels, D, H, W) and a real batch and shape
# (for --bench). Synthetic networks only; --script adds your own as "custom".
MODELS = {
    "conv3d": {"script": None, "build": lambda m: _conv3d(), "small": (2, 1, 16, 16, 16), "real": (8, 1, 64, 64, 64),
               "note": "plain 3D conv stack with GroupNorm and Dropout3d, 16 channels"},
    "conv2d": {"script": None, "build": lambda m: _conv2d(), "small": (4, 1, 16, 32, 32), "real": (16, 1, 16, 128, 128),
               "note": "2D conv stack with BatchNorm2d that reads 16 depth slices as channels"},
    "unet3d": {"script": None, "build": lambda m: _unet3d(), "small": (1, 1, 16, 16, 16), "real": (2, 1, 64, 64, 64),
               "note": "two-level 3D U-Net with InstanceNorm3d, a strided conv down and ConvTranspose3d up"},
}


def _torch():
    import torch
    return torch


def load_script(name, models=None):
    """Import a network's script as a module, with its folder on sys.path for its own imports; None for a built-in."""
    spec_ = (models or MODELS)[name]
    if not spec_.get("script"):
        return None
    path = Path(spec_["script"])
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        raise ValueError(f"no script at {path}")
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(f"mpsparity_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    return mod


def check_device(name):
    torch = _torch()
    if name == "mps":
        mps = getattr(torch.backends, "mps", None)
        if not (mps is not None and mps.is_available()):
            raise ValueError("mps requested but torch.backends.mps.is_available() is False")
    elif name.startswith("cuda"):
        if not torch.cuda.is_available():
            raise ValueError(f"{name} requested but this torch sees no CUDA device")
    elif name != "cpu":
        raise ValueError(f"unknown device {name!r}: use mps, cuda, cuda:N or cpu")
    return name


def sync(device):
    torch = _torch()
    if device == "mps":
        torch.mps.synchronize()
    elif device.startswith("cuda"):
        torch.cuda.synchronize()


def make_input(shape, seed, mask_channel=None):
    torch = _torch()
    g = torch.Generator().manual_seed(seed)
    x = torch.randn(shape, generator=g)
    if mask_channel is not None:
        x[:, mask_channel] = (torch.rand(x[:, mask_channel].shape, generator=g) > 0.2).float()
    return x


def flat_out(out):
    torch = _torch()
    if isinstance(out, (tuple, list)):
        return torch.cat([o.reshape(-1).float() for o in out])
    return out.reshape(-1).float()


def no_dropout(net):
    torch = _torch()
    for m in net.modules():
        if isinstance(m, (torch.nn.Dropout, torch.nn.Dropout2d, torch.nn.Dropout3d)):
            m.p = 0.0
    return net


def pair(build, ref, dev, seed, mutate_dev=None):
    """Two copies of one seeded network: on REF and on DEV. mutate_dev changes the DEV copy (tests only)."""
    torch = _torch()
    torch.manual_seed(seed)
    base = build()
    a = copy.deepcopy(base).to(ref)
    b = copy.deepcopy(base).to(dev)
    if mutate_dev:
        mutate_dev(b)
    return base, a, b


def outcome(value, tol, control):
    if control < CONTROL_FACTOR * tol:
        return "VOID"
    return "PASS" if value <= tol else "FAIL"


def _amp(device, on):
    """bf16 autocast on DEVICE when on (the precision many CUDA training runs use), else a no-op."""
    torch = _torch()
    return torch.autocast(device_type(device), dtype=torch.bfloat16, enabled=bool(on))


def device_type(device):
    return str(device).split(":", 1)[0]


def forward_check(build, small, ref, dev, seed=0, mask_channel=None, mutate_dev=None, tol=FWD_TOL, dev_amp=False):
    torch = _torch()
    _, a, b = pair(build, ref, dev, seed, mutate_dev)
    a.eval(); b.eval()
    x = make_input(small, seed + 1, mask_channel)
    with torch.no_grad():
        oa = flat_out(a(x.to(ref))).cpu().double()
        with _amp(dev, dev_amp):
            ob = flat_out(b(x.to(dev))).cpu().double()
        oc = flat_out(a(x.flip(2).to(ref))).cpu().double()
    sd = float(oa.std()) or 1e-12
    value = float((ob - oa).abs().max()) / sd
    control = float((oc - oa).abs().max()) / sd
    return {"check": "forward", "value": value, "tol": tol, "control": control, "outcome": outcome(value, tol, control)}


def _grad(net, x, t, device, amp=False):
    net.zero_grad(set_to_none=True)
    with _amp(device, amp):
        out = flat_out(net(x.to(device)))
    loss = ((out - t.to(device)) ** 2).mean()
    loss.backward()
    torch = _torch()
    return torch.cat([p.grad.reshape(-1).cpu().double() for p in net.parameters() if p.grad is not None])


def grad_check(build, small, ref, dev, seed=0, mask_channel=None, mutate_dev=None, tol=GRAD_TOL, dev_amp=False):
    torch = _torch()
    _, a, b = pair(build, ref, dev, seed, mutate_dev)
    no_dropout(a).train(); no_dropout(b).train()
    x = make_input(small, seed + 1, mask_channel)
    with torch.no_grad():
        n = flat_out(copy.deepcopy(a).eval()(x.to(ref))).numel()
    t = torch.randn(n, generator=torch.Generator().manual_seed(seed + 2))
    ga, gb = _grad(a, x, t, ref), _grad(b, x, t, dev, dev_amp)
    gc = _grad(a, x.flip(2), t, ref)
    norm = float(ga.norm()) or 1e-12
    value = float((gb - ga).norm()) / norm
    control = float((gc - ga).norm()) / norm
    return {"check": "grad", "value": value, "tol": tol, "control": control, "outcome": outcome(value, tol, control)}


def _train(net, device, batches, targets, lr=1e-3, amp=False):
    torch = _torch()
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    losses = []
    for x, t in zip(batches, targets):
        opt.zero_grad(set_to_none=True)
        with _amp(device, amp):
            out = flat_out(net(x.to(device)))
        loss = ((out.float() - t.to(device)) ** 2).mean()
        loss.backward()
        opt.step()
        losses.append(loss.item())
    return torch.cat([p.detach().reshape(-1).cpu().double() for p in net.parameters()]), losses


def train_check(build, small, ref, dev, seed=0, steps=10, mask_channel=None, mutate_dev=None, tol=TRAIN_TOL,
                dev_amp=False):
    torch = _torch()
    base, a, b = pair(build, ref, dev, seed, mutate_dev)
    c = copy.deepcopy(base).to(ref)
    for net in (a, b, c):
        no_dropout(net).train()
    with torch.no_grad():
        n = flat_out(copy.deepcopy(base).eval()(make_input(small, seed, mask_channel))).numel()
    xs = [make_input(small, seed + 10 + i, mask_channel) for i in range(steps)]
    ts = [torch.randn(n, generator=torch.Generator().manual_seed(seed + 1000 + i)) for i in range(steps)]
    w0 = torch.cat([p.detach().reshape(-1).double() for p in base.parameters()])
    wa, la = _train(a, ref, xs, ts)
    wb, lb = _train(b, dev, xs, ts, amp=dev_amp)
    wc, _ = _train(c, ref, xs[::-1], ts[::-1])          # control: same batches, another order
    moved = float((wa - w0).norm()) or 1e-12
    value = float((wb - wa).norm()) / moved
    control = float((wc - wa).norm()) / moved
    loss_rel = max(abs(p - q) / max(abs(p), 1e-12) for p, q in zip(la, lb))
    return {"check": "train", "steps": steps, "value": value, "tol": tol, "control": control,
            "loss_max_rel_diff": loss_rel, "loss_ref": [round(v, 6) for v in la],
            "loss_dev": [round(v, 6) for v in lb], "outcome": outcome(value, tol, control)}


MAX_GB = 12.0       # keeps a 16 GB Mac out of swap; an uncapped first bench of a 3D U-Net reached 28 GB


def cap_memory(dev, max_gb=MAX_GB):
    """On MPS, make torch refuse allocations past MAX_GB (an out-of-memory error, recorded, instead of swapping)."""
    torch = _torch()
    if dev != "mps":
        return None
    total = torch.mps.recommended_max_memory()
    frac = min(1.0, max_gb * 1e9 / total)
    torch.mps.set_per_process_memory_fraction(frac)
    return round(frac, 3)


def bench(build, real, dev, steps, mask_channel=None, seed=0, batch=None):
    """Seconds a training step at the network's real shape on DEV (first step left out as warm-up). batch replaces
    the real batch (s_per_sample lets a smaller batch estimate the real one)."""
    torch = _torch()
    if batch:
        real = (min(batch, real[0]),) + tuple(real[1:])
    torch.manual_seed(seed)
    net = build().to(dev).train()
    opt = torch.optim.AdamW(net.parameters(), lr=1e-4)
    x = make_input(real, seed, mask_channel).to(dev)
    times = []
    for i in range(steps + 1):
        t0 = time.time()
        opt.zero_grad(set_to_none=True)
        out = flat_out(net(x))
        loss = (out ** 2).mean()
        loss.backward()
        opt.step()
        sync(dev)
        if i:
            times.append(time.time() - t0)
    med = sorted(times)[len(times) // 2]
    rec = {"batch_shape": list(real), "steps": steps, "s_per_step": round(med, 4), "s_per_sample": round(med / real[0], 5)}
    if dev == "mps":
        rec["mps_driver_gb"] = round(torch.mps.driver_allocated_memory() / 1e9, 2)
    return rec


def bar_outcome(value, bar, control):
    """The bf16 bar: DEV in fp32 must sit nearer the REF fp32 result than bf16 autocast does on REF, the precision
    many CUDA training runs already use. A bar for networks whose fixed tolerances are stricter than the noise of
    a precision people already accept. VOID when the control (reversed input or batch order) is not past the bar."""
    if control <= bar:
        return "VOID"
    return "PASS" if value < bar else "FAIL"


def run_model(name, ref="cpu", dev="mps", steps=10, bench_steps=0, seed=0, bench_batch=None, bar="fixed",
              models=None):
    spec_ = (models or MODELS)[name]
    mod = load_script(name, models)
    build = lambda: spec_["build"](mod)                  # noqa: E731
    mc = spec_.get("mask_channel")
    rec = {"model": name, "script": spec_["script"], "note": spec_["note"],
           "small_shape": list(spec_["small"]), "checks": []}
    for fn, kw in ((forward_check, {}), (grad_check, {}), (train_check, {"steps": steps})):
        try:
            c = fn(build, spec_["small"], ref, dev, seed=seed, mask_channel=mc, **kw)
            if bar == "bf16":                            # the bar: bf16 autocast against fp32 on REF, same seed
                amp = fn(build, spec_["small"], ref, ref, seed=seed, mask_channel=mc, dev_amp=True, **kw)
                c["fixed_tol_outcome"] = c["outcome"]
                c["bar"], c["tol"] = "bf16", amp["value"]
                c["outcome"] = bar_outcome(c["value"], amp["value"], c["control"])
            rec["checks"].append(c)
        except Exception as e:                           # an operator MPS lacks, say: a failure, with its text
            rec["checks"].append({"check": fn.__name__.replace("_check", ""), "outcome": "FAIL",
                                  "error": f"{type(e).__name__}: {e}"[:500]})
    if bench_steps:
        try:
            rec["bench"] = bench(build, spec_["real"], dev, bench_steps, mc, seed, bench_batch)
        except Exception as e:
            rec["bench"] = {"error": f"{type(e).__name__}: {e}"[:500]}
        finally:
            if dev == "mps":
                _torch().mps.empty_cache()
    v = {c["check"]: c["outcome"] for c in rec["checks"]}
    if bar == "bf16":   # a forward VOID is allowed (an untrained output can barely depend on its input), not a FAIL
        rec["outcome"] = ("FAIL" if "FAIL" in v.values() else
                          "PASS" if v.get("grad") == "PASS" and v.get("train") == "PASS" else "VOID")
        return rec
    rec["outcome"] = "PASS" if all(c["outcome"] == "PASS" for c in rec["checks"]) else (
        "VOID" if any(c["outcome"] == "VOID" for c in rec["checks"]) and
        not any(c["outcome"] == "FAIL" for c in rec["checks"]) else "FAIL")
    return rec


def custom_model(script, build, shape, real=None):
    """A MODELS-style entry for a network in your own script: build is the name of a callable there that takes no
    arguments and returns the torch module; shape and real are (batch, channels, D, H, W)."""
    if not script or not build or not shape:
        raise ValueError("--script, --build and --shape go together")
    if not Path(script).is_file():
        raise ValueError(f"no script at {script}")
    return {"script": script, "build": lambda m: getattr(m, build)(), "small": tuple(shape),
            "real": tuple(real or shape), "note": f"{build}() from {script}"}


def parse_shape(text):
    try:
        shape = tuple(int(v) for v in str(text).split(","))
    except ValueError:
        shape = ()
    if len(shape) < 3 or min(shape) < 1:
        raise ValueError(f"bad shape {text!r}: use B,C,D,H,W (at least batch, channels and depth; all positive)")
    return shape


def _op_cases():
    torch = _torch()
    import torch.nn.functional as F

    def grid3d(d):
        g = torch.Generator().manual_seed(0)
        x = torch.randn(1, 1, 16, 16, 16, generator=g).to(d)
        grid = (torch.rand(1, 8, 8, 8, 3, generator=g) * 2 - 1).to(d)
        return F.grid_sample(x, grid, mode="bilinear", padding_mode="border", align_corners=True)

    def grid3d_nearest(d):
        g = torch.Generator().manual_seed(0)
        x = torch.randn(1, 1, 16, 16, 16, generator=g).to(d)
        grid = (torch.rand(1, 8, 8, 8, 3, generator=g) * 2 - 1).to(d)
        return F.grid_sample(x, grid, mode="nearest", padding_mode="border", align_corners=True)

    def gen_randint(d):
        g = torch.Generator(device=d).manual_seed(5)
        return torch.randint(0, 100, (64,), generator=g, device=d).float() * 0   # runs; values are device RNG

    def trilinear(d):
        x = torch.randn(1, 1, 8, 8, 8, generator=torch.Generator().manual_seed(0)).to(d)
        return F.interpolate(x, scale_factor=4, mode="trilinear", align_corners=False)

    def convt3d(d):
        torch.manual_seed(0)
        m = torch.nn.ConvTranspose3d(4, 2, 2, stride=2)
        x = torch.randn(1, 4, 6, 6, 6, generator=torch.Generator().manual_seed(1))
        return m.to(d)(x.to(d))

    def instnorm3d(d):
        torch.manual_seed(0)
        m = torch.nn.InstanceNorm3d(4, affine=True)
        x = torch.randn(2, 4, 6, 6, 6, generator=torch.Generator().manual_seed(1))
        return m.to(d)(x.to(d))

    def topk(d):
        x = torch.randn(1000, generator=torch.Generator().manual_seed(0)).to(d)
        return torch.topk(x, 37).values

    def uint8_lut(d):
        lut = torch.linspace(-2, 2, 256).to(d)
        v = torch.randint(0, 256, (4, 8, 8, 8), generator=torch.Generator().manual_seed(0), dtype=torch.uint8).to(d)
        return lut[v.long()]

    return {"grid_sample_3d_bilinear": grid3d, "grid_sample_3d_nearest": grid3d_nearest,
            "generator_randint_on_device": gen_randint, "interpolate_trilinear": trilinear,
            "conv_transpose3d": convt3d, "instance_norm3d": instnorm3d, "topk": topk, "uint8_table_lookup": uint8_lut}


def ops(dev="mps", tol=1e-4):
    """Each operator on DEV against the CPU: supported and close, or the error torch gave."""
    torch = _torch()
    out = {"fallback_env": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"), "ops": {}}
    for name, fn in _op_cases().items():
        try:
            with torch.no_grad():
                a = fn("cpu").double()
                b = fn(dev).cpu().double()
            sd = float(a.std()) or 1.0
            rel = float((b - a).abs().max()) / sd
            out["ops"][name] = {"ok": rel <= tol, "rel": rel}
        except Exception as e:
            out["ops"][name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    out["ok"] = all(v["ok"] for v in out["ops"].values())
    return out


def environment(dev):
    torch = _torch()
    import platform
    return {"torch": torch.__version__, "python": platform.python_version(), "machine": platform.machine(),
            "system": platform.system(), "device": dev,
            "fallback_env": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"), "threads": torch.get_num_threads()}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.mpsparity", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="forward, gradient and short-training checks, DEV against REF")
    r.add_argument("--models", help="comma list of " + ", ".join(MODELS) + " (default: all, or none with --script)")
    r.add_argument("--script", help="a Python file that defines your network")
    r.add_argument("--build", help="the callable in --script that takes no arguments and returns the network")
    r.add_argument("--shape", help="--script: the small check shape B,C,D,H,W (the depth axis, index 2, is reversed "
                                   "for the control)")
    r.add_argument("--real-shape", help="--script: the batch and shape --bench times (default --shape)")
    r.add_argument("--device", default="mps")
    r.add_argument("--ref", default="cpu")
    r.add_argument("--steps", type=int, default=10)
    r.add_argument("--bench", type=int, default=0, help="also time N training steps at the real shape on DEV")
    r.add_argument("--bench-batch", type=int, help="--bench: this batch instead of the real one (s_per_sample scales it)")
    r.add_argument("--max-gb", type=float, default=MAX_GB, help="MPS: refuse allocations past this many GB (default 12)")
    r.add_argument("--bar", choices=("fixed", "bf16"), default="fixed",
                   help="fixed: the tolerances 1e-3, 1e-3, 0.02; bf16: DEV must beat bf16 autocast on REF")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--out", help="write the record here as JSON")
    r.add_argument("--json", action="store_true")
    o = sub.add_parser("ops", help="probe the data-path operators on DEV against the CPU")
    o.add_argument("--device", default="mps")
    o.add_argument("--json", action="store_true")
    sub.add_parser("list", help="the built-in networks")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for k, v in MODELS.items():
            print(f"{k}: small {','.join(map(str, v['small']))}, real {','.join(map(str, v['real']))}; {v['note']}")
        return 0
    models = dict(MODELS)
    try:
        check_device(a.device)
        if a.cmd == "run":
            check_device(a.ref)
            names = [n.strip() for n in (a.models or ("" if a.script else ",".join(MODELS))).split(",") if n.strip()]
            bad = [n for n in names if n not in MODELS]
            if bad:
                raise ValueError(f"unknown model(s) {', '.join(bad)}: use {', '.join(MODELS)}")
            if a.script or a.build or a.shape or a.real_shape:
                models["custom"] = custom_model(a.script, a.build, a.shape and parse_shape(a.shape),
                                                a.real_shape and parse_shape(a.real_shape))
                names.append("custom")
            if not names:
                raise ValueError("no network to check: name --models or give --script, --build and --shape")
    except ValueError as e:
        ap.error(str(e))
    if a.cmd == "ops":
        rec = {"environment": environment(a.device), **ops(a.device)}
        if a.json:
            print(json.dumps(rec, indent=1))
        else:
            for k, v in rec["ops"].items():
                print(f"{k}: {'ok' if v['ok'] else 'NOT OK'} {v.get('rel', v.get('error'))}")
        return 0 if rec["ok"] else 1
    t0 = time.time()
    frac = cap_memory(a.device, a.max_gb)
    rec = {"tool": "kit.mpsparity", "environment": environment(a.device), "ref": a.ref, "mps_memory_fraction": frac,
           "bar": a.bar, "seed": a.seed,
           "tolerances": {"forward": FWD_TOL, "grad": GRAD_TOL, "train": TRAIN_TOL, "control_factor": CONTROL_FACTOR},
           "models": [], "ops": ops(a.device) if a.device != "cpu" else None}
    for n in names:
        m = run_model(n, a.ref, a.device, a.steps, a.bench, a.seed, a.bench_batch, a.bar, models)
        rec["models"].append(m)
        if not a.json:
            parts = ", ".join(f"{c['check']} {c['outcome']}" + (f" {c['value']:.2e} (control {c['control']:.2e})"
                              if "value" in c else f" {c.get('error', '')}") for c in m["checks"])
            print(f"{n}: {m['outcome']}: {parts}" + (f"; bench {m['bench']}" if "bench" in m else ""), flush=True)
    rec["seconds"] = round(time.time() - t0, 1)
    rec["ok"] = all(m["outcome"] == "PASS" for m in rec["models"])
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rec, indent=1) + "\n")
    if a.json:
        print(json.dumps(rec, indent=1))
    else:
        print("ALL PASS" if rec["ok"] else "NOT ALL PASS", flush=True)
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
