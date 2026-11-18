"""Device and precision choice for the torch scripts: CUDA, then Apple MPS, then CPU.

torch is imported inside the functions, so `import kit.accel` works without it and kit stays
standard library at import time.

Devices: ``auto`` picks CUDA when torch sees a CUDA card, else MPS when torch sees Apple's GPU,
else the CPU. An explicit ``cuda``, ``cuda:N``, ``mps`` or ``cpu`` is checked and refused when
this torch cannot use it, so a typo or a missing GPU never falls back to the CPU in silence.

Precisions:

- ``auto``: bf16 autocast on a CUDA card that does bf16 natively (Ampere or newer), fp16 autocast
  with a GradScaler on an older card, and plain fp32 on MPS and the CPU. On an Apple M1 Pro (23 Oct
  2026, scripts/accelbench/mps_precision.py, two runs) fp16 and bf16 autocast ran inference at 0.82
  to 1.04 times the speed of fp32 and training at 0.84 to 1.31 times, faster only for the plain 3D
  conv training step; CPU autocast is slow without bf16 hardware, and an M1 has none. Pass
  ``fp16`` or ``bf16`` to choose autocast on MPS.
- ``bf16`` or ``fp16``: that autocast dtype on the chosen device; torch raises where it cannot.
- ``fp32``: no autocast. This is the code path every script ran before mixed precision came in,
  so an ``--fp32`` run reproduces earlier fp32 numbers. It does not touch TF32: on CUDA, torch's
  default lets cuDNN convolutions use TF32 (``torch.backends.cudnn.allow_tf32`` is True) and
  keeps matmuls in full fp32, exactly as in those runs. Scripts that turned TF32 off before still
  do so themselves; ``disable_tf32`` is here for them.

  python -m kit.accel [--device D] [--precision P]           # what auto picks on this machine, as JSON
  python -m kit.accel --check [--device D] [--precision P]   # forward check against CPU fp32, with a control

``--check`` runs a small seeded 3D-to-2D network (a toy, not an ink model) on the chosen device and precision and
on the CPU in fp32, and compares the output logits, as the largest difference over the reference's standard
deviation. Its control is the CPU fp32 output for the same input with the depth order reversed, which must differ
by at least ten times the tolerance; otherwise the check could not fail and counts as failed. Exit status 0 means
both held. It shows the device and autocast work on this machine; it says nothing about a given model's maps.
"""
import argparse
import contextlib
import json
import warnings

PRECISIONS = ('auto', 'bf16', 'fp16', 'fp32')
ALIASES = {'bfloat16': 'bf16', 'float16': 'fp16', 'half': 'fp16', 'float32': 'fp32', 'none': 'fp32',
           'off': 'fp32', 'full': 'fp32'}
DEVICE_HELP = 'auto (CUDA, then MPS, then CPU; the default), cuda, cuda:N, mps or cpu'
PRECISION_HELP = ('auto (bf16 on CUDA, fp16 if the card has no bf16, fp32 on MPS and CPU), bf16, fp16 '
                  'or fp32 (no autocast: the code path of runs before mixed precision)')


def _torch():
    import torch
    return torch


def device_type(device):
    """'cuda:1' -> 'cuda'. torch.autocast and GradScaler want the bare type."""
    kind = getattr(device, 'type', None)
    return kind if isinstance(kind, str) else str(device).split(':', 1)[0].strip().lower()


def mps_available(torch=None):
    torch = torch or _torch()
    mps = getattr(torch.backends, 'mps', None)
    return bool(mps is not None and mps.is_available())


def resolve_device(name='auto'):
    """Return the device string to hand to torch: auto picks CUDA, then MPS, then CPU."""
    torch = _torch()
    name = str(name if name is not None else 'auto').strip().lower()
    if name == 'auto':
        if torch.cuda.is_available():
            return 'cuda'
        if mps_available(torch):
            return 'mps'
        return 'cpu'
    try:
        dev = torch.device(name)
    except (RuntimeError, ValueError) as error:
        raise ValueError(f'unknown device {name!r}; use {DEVICE_HELP}') from error
    if dev.type == 'cuda':
        if not torch.cuda.is_available():
            raise ValueError(f'{name} requested but this torch sees no CUDA device')
        if dev.index is not None and dev.index >= torch.cuda.device_count():
            raise ValueError(f'{name} requested but this machine has {torch.cuda.device_count()} CUDA device(s)')
    elif dev.type == 'mps':
        if not mps_available(torch):
            raise ValueError(f'{name} requested but torch.backends.mps.is_available() is False')
    elif dev.type != 'cpu':
        raise ValueError(f'unsupported device {name!r}; use {DEVICE_HELP}')
    return name


def cuda_bf16_native(device='cuda', torch=None):
    """True on cards that compute bf16 natively (compute capability 8.0 or newer)."""
    torch = torch or _torch()
    if not torch.cuda.is_available():
        return False
    try:
        major, _ = torch.cuda.get_device_capability(torch.device(device))
    except (AssertionError, RuntimeError, ValueError):
        return False
    return major >= 8


def mps_autocast_available(torch=None):
    torch = torch or _torch()
    check = getattr(getattr(torch, 'amp', None), 'is_autocast_available', None)
    try:
        return bool(check and check('mps'))
    except (RuntimeError, ValueError):
        return False


def normalize_precision(precision):
    p = str(precision if precision is not None else 'auto').strip().lower()
    p = ALIASES.get(p, p)
    if p not in PRECISIONS:
        raise ValueError(f'unknown precision {precision!r}; use {", ".join(PRECISIONS)}')
    return p


def resolve_precision(device, precision='auto'):
    """Return 'bf16', 'fp16' or 'fp32' for this device (see the module docstring)."""
    p = normalize_precision(precision)
    if p == 'fp32':
        return 'fp32'
    kind = device_type(device)
    torch = _torch()
    if kind == 'cuda':
        native = cuda_bf16_native(device, torch)
        if p == 'auto':
            return 'bf16' if native else 'fp16'
        if p == 'bf16' and not native:
            raise ValueError('this CUDA card has no native bf16; use --precision fp16 or fp32')
        return p
    if kind == 'mps':
        if not mps_autocast_available(torch):
            if p == 'auto':
                return 'fp32'
            raise ValueError(f'torch {torch.__version__} has no MPS autocast; use --precision fp32')
        return 'fp32' if p == 'auto' else p
    if kind == 'cpu':
        if p in ('bf16', 'fp16'):
            # bf16 autocast on a Hugging Face cpu-upgrade machine ran about 40x slower than the same work on one L4 (23 Oct 2026)
            warnings.warn(f'{p} autocast on the CPU is usually much slower than fp32 (about 40x on Hugging Face '
                          'cpu-upgrade, 23 Oct 2026); prefer a GPU or --precision fp32', stacklevel=2)
        return 'fp32' if p == 'auto' else p
    raise ValueError(f'unsupported device {device!r}')


def dtype(precision):
    """The torch dtype autocast uses for a resolved precision, or None for fp32."""
    torch = _torch()
    return {'bf16': torch.bfloat16, 'fp16': torch.float16, 'fp32': None}[normalize_precision(precision)]


def _resolved(device, precision):
    p = normalize_precision(precision)
    return resolve_precision(device, p) if p == 'auto' else p


def autocast(device, precision):
    """Context manager for the forward pass: autocast in bf16 or fp16, or nothing for fp32.

    Pass a precision from resolve_precision or from_args; 'auto' is resolved here."""
    p = _resolved(device, precision)
    if p == 'fp32':
        return contextlib.nullcontext()
    return _torch().autocast(device_type=device_type(device), dtype=dtype(p))


def grad_scaler(device, precision):
    """A GradScaler that is on only for fp16 on CUDA or MPS (bf16 and fp32 need none)."""
    torch = _torch()
    kind = device_type(device)
    on = _resolved(device, precision) == 'fp16' and kind in ('cuda', 'mps')
    return torch.amp.GradScaler(kind if on else 'cpu', enabled=on)


def synchronize(device):
    """Wait for queued GPU work (for timings); a no-op on the CPU."""
    torch = _torch()
    kind = device_type(device)
    if kind == 'cuda':
        torch.cuda.synchronize(torch.device(device))
    elif kind == 'mps':
        torch.mps.synchronize()


def disable_tf32():
    """Keep CUDA matmuls and cuDNN convolutions in full fp32 (both TF32 switches off)."""
    torch = _torch()
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False


def add_arguments(parser, device='auto', precision='auto', fp32_flag=True):
    """Add --device, --precision and (unless fp32_flag is False) --fp32 to an argparse parser."""
    parser.add_argument('--device', default=device, help=DEVICE_HELP)
    parser.add_argument('--precision', default=precision, type=normalize_precision, help=PRECISION_HELP)
    if fp32_flag:
        parser.add_argument('--fp32', action='store_true',
                            help='full fp32, no autocast: reproduces runs from before mixed precision '
                                 '(same as --precision fp32)')
    return parser


def from_args(args):
    """(device, precision) from parsed add_arguments flags, both resolved and checked."""
    device = resolve_device(args.device)
    precision = normalize_precision(args.precision)
    if getattr(args, 'fp32', False):
        if precision not in ('auto', 'fp32'):
            raise ValueError(f'--fp32 contradicts --precision {precision}')
        precision = 'fp32'
    return device, resolve_precision(device, precision)


def describe(device, precision):
    """A small JSON-ready record of what ran, for logs and receipts."""
    torch = _torch()
    p = resolve_precision(device, precision)
    record = {'device': str(device), 'device_type': device_type(device), 'precision': p,
              'autocast_dtype': None if p == 'fp32' else str(dtype(p)).replace('torch.', ''),
              'torch': str(torch.__version__)}
    if device_type(device) == 'cuda' and torch.cuda.is_available():
        record['gpu'] = torch.cuda.get_device_name(torch.device(device))
    return record


# Largest logit difference against CPU fp32, over the reference's standard deviation. On a CPU (torch 2.14.1) the
# check measured 0 for fp32, 0.006 for fp16 and 0.05 for bf16, and 6.6 for the control. fp32 on CUDA with TF32
# allowed (torch's default for cuDNN convolutions) gets its own bound: TF32 emulated on the CPU, by rounding the
# convolutions' inputs and weights to 10 mantissa bits, gave 0.0065.
TOLERANCE = {'fp32': 1e-3, 'tf32': 0.03, 'bf16': 0.15, 'fp16': 0.03}
CONTROL_FACTOR = 10                                        # the control must differ by at least 10 times that


def check(device, precision, seed=20261015, depth=16, size=64, batch=2):
    """The forward check of ``--check``: a record with the differences, the tolerance and ``ok``."""
    torch = _torch()
    p = resolve_precision(device, precision)
    g = torch.Generator().manual_seed(seed)
    x = (torch.rand(batch, 1, depth, size, size, generator=g) - 0.5) / 0.29     # about zero mean, unit variance
    net = torch.nn.Sequential(torch.nn.Conv3d(1, 4, 3, padding=1), torch.nn.GELU(), torch.nn.Flatten(1, 2),
                              torch.nn.Conv2d(4 * depth, 8, 3, padding=1), torch.nn.GELU(),
                              torch.nn.Conv2d(8, 1, 1))
    with torch.no_grad():
        for w in net.parameters():
            w.copy_(torch.randn(w.shape, generator=g) * (2.0 / max(1, w[0].numel())) ** 0.5)
    net.eval()

    def logits(model, inp, dev, prec):
        with torch.inference_mode(), autocast(dev, prec):
            return model(inp.to(dev)).float().cpu()
    ref = logits(net, x, 'cpu', 'fp32')
    control = logits(net, x.flip(2), 'cpu', 'fp32')
    test = logits(net.to(device), x, device, p)
    synchronize(device)
    scale = float(ref.std())
    diff = float((test - ref).abs().max()) / scale
    control_diff = float((control - ref).abs().max()) / scale
    tf32 = (p == 'fp32' and device_type(device) == 'cuda'
            and bool(torch.backends.cudnn.allow_tf32 or torch.backends.cuda.matmul.allow_tf32))
    tol = TOLERANCE['tf32' if tf32 else p]
    record = describe(device, p)
    record['tf32_allowed'] = tf32
    record.update({'check': 'toy forward against CPU fp32: max logit difference over the reference std',
                   'max_diff': round(diff, 6), 'tolerance': tol, 'control': 'depth order reversed, CPU fp32',
                   'control_max_diff': round(control_diff, 6),
                   'control_caught': control_diff > CONTROL_FACTOR * tol, 'agrees': diff <= tol})
    record['ok'] = record['agrees'] and record['control_caught']
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m kit.accel', description=__doc__.split('\n\n')[0])
    add_arguments(ap)
    ap.add_argument('--check', action='store_true', help='run the forward check against CPU fp32, with its control')
    a = ap.parse_args(argv)
    try:
        device, precision = from_args(a)
    except ValueError as e:
        ap.error(str(e))
    if a.check:
        record = check(device, precision)
        print(json.dumps(record, indent=2))
        return 0 if record['ok'] else 1
    print(json.dumps(describe(device, precision), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
