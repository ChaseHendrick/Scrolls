"""SS2D, VMamba's four-direction 2D selective scan, in plain PyTorch so it runs on CPU, Apple MPS and CUDA.

Mamba's published kernels (mamba-ssm, VMamba's csms6s) need CUDA, so on the Mac no Mamba model ran at all. This
file is a from-scratch build of the method (VMamba, Liu et al., NeurIPS 2024, https://github.com/MzeroMiko/VMamba,
MIT; Mamba, Gu and Dao 2023), written for this repository:

  selective_scan(u, delta, A, B, C, D)   the S6 recurrence h_t = exp(delta_t A) h_{t-1} + delta_t B_t u_t,
                                         y_t = C_t . h_t + D u_t, computed in chunks of `chunk` steps: inside a
                                         chunk every pair (t, s) gets exp(S_t - S_s) from the cumulative sum S of
                                         delta A, which is never positive, so nothing overflows; the state is
                                         carried from chunk to chunk. Exact, not an approximation (the tests
                                         check it against the step-by-step loop)
  SS2D(dim)                              in-projection, depthwise 3x3 conv, the image scanned four ways (rows,
                                         columns, and both reversed), one selective scan over the four sequences,
                                         the four results folded back to the image and summed, gated, projected
  VSSBlock(dim)                          LayerNorm, SS2D, residual; LayerNorm, MLP, residual
  SS2DUNet(in_ch, out_ch, widths)        a 2D U-Net: convolutions at full resolution, a VSS block in every
                                         encoder and decoder stage below it, stride-2 convolutions down and
                                         transposed convolutions up, skip links

When mamba-ssm is installed and the tensors are on CUDA, `fast=True` hands the scan to its selective_scan_fn
kernel instead; the result is the same up to float rounding. Defaults follow VMamba's SS2D: d_state 16, expand 2,
dt_rank ceil(dim / 16), dt initialised log-uniform in [0.001, 0.1], A_log = log(1..d_state).

torch is the only dependency. Nothing here downloads anything.
"""

import math

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.checkpoint


def selective_scan_ref(u, delta, A, B, C, D=None, delta_bias=None, delta_softplus=True):
    """The step-by-step S6 loop, for tests only. Shapes as selective_scan."""
    (u, delta, A, B, C), rep = _prepare(u, delta, A, B, C, delta_bias, delta_softplus)
    B, C = B.repeat_interleave(rep, dim=1), C.repeat_interleave(rep, dim=1)
    bsz, d, L = u.shape
    h = u.new_zeros(bsz, d, A.shape[1])
    ys = []
    for t in range(L):
        h = torch.exp(delta[:, :, t, None] * A) * h + (delta[:, :, t] * u[:, :, t])[..., None] * B[:, :, :, t]
        ys.append((h * C[:, :, :, t]).sum(-1))
    y = torch.stack(ys, dim=-1)
    if D is not None:
        y = y + u * D[None, :, None]
    return y


def _prepare(u, delta, A, B, C, delta_bias, delta_softplus):
    """Common checks and float32 casts; returns the tensors and how many channels share each B, C group."""
    bsz, d, L = u.shape
    if delta.shape != u.shape:
        raise ValueError(f"delta shape {tuple(delta.shape)} must equal u shape {tuple(u.shape)}")
    if A.shape[0] != d:
        raise ValueError(f"A has {A.shape[0]} rows, u has {d} channels")
    if B.dim() != 4 or C.dim() != 4 or B.shape[-1] != L or C.shape[-1] != L:
        raise ValueError("B and C must be (batch, groups, d_state, L)")
    g = B.shape[1]
    if d % g:
        raise ValueError(f"{d} channels do not split into {g} groups")
    rep = d // g
    delta = delta.float()
    if delta_bias is not None:
        delta = delta + delta_bias[None, :, None].float()
    if delta_softplus:
        delta = F.softplus(delta)
    return (u.float(), delta, A.float(), B.float(), C.float()), rep


def _chunk(u, dl, A, B, C, h, rep=1):
    """One chunk of selective_scan: (y (b, d, T), last state (b, d, N)). B and C are (b, groups, N, T)."""
    T = u.shape[-1]
    if rep > 1:
        B = B.repeat_interleave(rep, dim=1)
        C = C.repeat_interleave(rep, dim=1)
    dA = dl[..., None] * A[None, :, None, :]                     # b d T N, <= 0 when A <= 0
    S = torch.cumsum(dA, dim=2)
    seg = S[:, :, :, None, :] - S[:, :, None, :, :]              # b d T(t) T(s) N: S_t - S_s
    causal = torch.ones(T, T, dtype=torch.bool, device=u.device).tril()
    seg = seg.masked_fill(~causal[None, None, :, :, None], float("-inf"))
    Bx = (dl * u)[..., None] * B.transpose(2, 3)                 # b d T N
    w = torch.exp(seg).permute(0, 1, 4, 2, 3)                    # b d N T T
    hs = torch.matmul(w, Bx.permute(0, 1, 3, 2)[..., None])[..., 0].permute(0, 1, 3, 2)
    hs = hs + torch.exp(S) * h[:, :, None, :]
    y = (hs * C.transpose(2, 3)).sum(-1)
    return y, hs[:, :, -1]


def selective_scan(u, delta, A, B, C, D=None, delta_bias=None, delta_softplus=True, chunk=16, fast=False):
    """S6 selective scan over L steps, exact, in chunks.

    u, delta: (batch, d, L). A: (d, N), normally negative. B, C: (batch, groups, N, L) with d divisible by
    groups. D: (d,) or None. delta_bias: (d,) or None. Returns y: (batch, d, L) as float32."""
    if fast and u.is_cuda:
        try:
            from mamba_ssm.ops.selective_scan_interface import selective_scan_fn
        except ImportError:
            selective_scan_fn = None
        if selective_scan_fn is not None:
            return selective_scan_fn(u.contiguous(), delta.contiguous(), A.contiguous(), B.contiguous(),
                                     C.contiguous(), D, None, delta_bias, delta_softplus).float()
    if chunk < 1:
        raise ValueError("chunk must be at least 1")
    (u, delta, A, B, C), rep = _prepare(u, delta, A, B, C, delta_bias, delta_softplus)
    bsz, d, L = u.shape
    N = A.shape[1]
    h = u.new_zeros(bsz, d, N)
    out = []
    grad = torch.is_grad_enabled() and any(t.requires_grad for t in (u, delta, A, B, C))
    for s0 in range(0, L, chunk):
        s1 = min(L, s0 + chunk)
        args = (u[:, :, s0:s1], delta[:, :, s0:s1], A, B[:, :, :, s0:s1], C[:, :, :, s0:s1], h, rep)
        if grad:   # keep only the chunk's inputs; the T x T weights are recomputed in the backward pass
            y, h = torch.utils.checkpoint.checkpoint(_chunk, *args, use_reentrant=False)
        else:
            y, h = _chunk(*args)
        out.append(y)
    y = torch.cat(out, dim=-1)
    if D is not None:
        y = y + u * D.float()[None, :, None]
    return y


class SS2D(nn.Module):
    """VMamba's SS2D on channels-last input (batch, H, W, dim) -> same shape."""

    def __init__(self, dim, d_state=16, expand=2, dt_rank=None, d_conv=3, dt_min=0.001, dt_max=0.1,
                 dt_init_floor=1e-4, chunk=16, fast=False):
        super().__init__()
        self.dim, self.d_state, self.chunk, self.fast = dim, d_state, chunk, fast
        self.d_inner = int(expand * dim)
        self.dt_rank = dt_rank or math.ceil(dim / 16)
        K, di, N, R = 4, self.d_inner, d_state, self.dt_rank
        self.in_proj = nn.Linear(dim, 2 * di, bias=False)
        self.conv2d = nn.Conv2d(di, di, d_conv, padding=d_conv // 2, groups=di, bias=True)
        self.x_proj_weight = nn.Parameter(torch.empty(K, R + 2 * N, di))
        nn.init.kaiming_uniform_(self.x_proj_weight, a=math.sqrt(5))
        std = R ** -0.5
        self.dt_projs_weight = nn.Parameter(torch.empty(K, di, R).uniform_(-std, std))
        dt = torch.exp(torch.rand(K, di) * (math.log(dt_max) - math.log(dt_min)) + math.log(dt_min))
        dt = dt.clamp(min=dt_init_floor)
        self.dt_projs_bias = nn.Parameter(dt + torch.log(-torch.expm1(-dt)))   # inverse softplus
        self.A_logs = nn.Parameter(torch.log(torch.arange(1, N + 1, dtype=torch.float32)).repeat(K * di, 1))
        self.Ds = nn.Parameter(torch.ones(K * di))
        self.out_norm = nn.LayerNorm(di)
        self.out_proj = nn.Linear(di, dim, bias=False)

    @staticmethod
    def scan_orders(x):
        """(b, c, H, W) -> (b, 4, c, H*W): row-major, column-major, and both reversed."""
        b, c, H, W = x.shape
        rows = x.reshape(b, c, H * W)
        cols = x.transpose(2, 3).reshape(b, c, H * W)
        xs = torch.stack([rows, cols], dim=1)
        return torch.cat([xs, xs.flip(-1)], dim=1)

    @staticmethod
    def merge_orders(ys, H, W):
        """Inverse of scan_orders, summed: (b, 4, c, H*W) -> (b, c, H*W) in row-major order."""
        b, _, c, L = ys.shape
        ys = ys[:, 0:2] + ys[:, 2:4].flip(-1)
        cols = ys[:, 1].reshape(b, c, W, H).transpose(2, 3).reshape(b, c, L)
        return ys[:, 0] + cols

    def forward(self, x):
        b, H, W, _ = x.shape
        xz = self.in_proj(x)
        x, z = xz.chunk(2, dim=-1)
        x = F.silu(self.conv2d(x.permute(0, 3, 1, 2).contiguous()))   # b di H W
        K, di, N, R = 4, self.d_inner, self.d_state, self.dt_rank
        L = H * W
        xs = self.scan_orders(x)                                        # b K di L
        x_dbl = torch.einsum("bkdl,kcd->bkcl", xs, self.x_proj_weight)
        dts, Bs, Cs = torch.split(x_dbl, [R, N, N], dim=2)
        dts = torch.einsum("bkrl,kdr->bkdl", dts, self.dt_projs_weight)
        y = selective_scan(xs.reshape(b, K * di, L), dts.reshape(b, K * di, L), -torch.exp(self.A_logs.float()),
                           Bs, Cs, self.Ds, self.dt_projs_bias.reshape(-1), True, chunk=self.chunk,
                           fast=self.fast)
        y = self.merge_orders(y.reshape(b, K, di, L), H, W)             # b di L
        y = y.transpose(1, 2).reshape(b, H, W, di).to(z.dtype)
        y = self.out_norm(y) * F.silu(z)
        return self.out_proj(y)


class VSSBlock(nn.Module):
    """Channels-first (b, c, H, W) block: x + SS2D(LN(x)), then x + MLP(LN(x))."""

    def __init__(self, dim, mlp_ratio=4.0, **ss2d):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.ss2d = SS2D(dim, **ss2d)
        self.norm2 = nn.LayerNorm(dim)
        hidden = int(dim * mlp_ratio)
        self.mlp = nn.Sequential(nn.Linear(dim, hidden), nn.GELU(), nn.Linear(hidden, dim))

    def forward(self, x):
        x = x.permute(0, 2, 3, 1)
        x = x + self.ss2d(self.norm1(x))
        x = x + self.mlp(self.norm2(x))
        return x.permute(0, 3, 1, 2)


def _conv(cin, cout):
    return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.InstanceNorm2d(cout, affine=True),
                         nn.LeakyReLU(0.01, inplace=True))


class SS2DUNet(nn.Module):
    """2D U-Net with a VSS block in every stage below full resolution. Input (b, in_ch, H, W) with H and W divisible by
    2 ** (len(widths) - 1); output (b, out_ch, H, W) logits."""

    def __init__(self, in_ch, out_ch, widths=(32, 64, 128, 256), blocks=1, d_state=16, chunk=16, fast=False):
        super().__init__()
        self.widths = tuple(widths)
        self.stem = _conv(in_ch, widths[0])
        self.enc = nn.ModuleList()
        self.down = nn.ModuleList()
        for i, w in enumerate(widths):
            if i == 0:   # full resolution: convolutions only, as VMamba scans after its patch embedding
                self.enc.append(_conv(w, w))
            else:
                self.enc.append(nn.Sequential(*[VSSBlock(w, d_state=d_state, chunk=chunk, fast=fast)
                                                for _ in range(blocks)]))
            if i + 1 < len(widths):
                self.down.append(nn.Sequential(nn.Conv2d(w, widths[i + 1], 2, stride=2), nn.GroupNorm(1, widths[i + 1])))
        self.up = nn.ModuleList()
        self.dec = nn.ModuleList()
        for i in range(len(widths) - 1, 0, -1):
            self.up.append(nn.ConvTranspose2d(widths[i], widths[i - 1], 2, stride=2))
            tail = _conv(widths[0], widths[0]) if i == 1 else \
                VSSBlock(widths[i - 1], d_state=d_state, chunk=chunk, fast=fast)
            self.dec.append(nn.Sequential(_conv(2 * widths[i - 1], widths[i - 1]), tail))
        self.head = nn.Conv2d(widths[0], out_ch, 1)

    def forward(self, x):
        f = 2 ** (len(self.widths) - 1)
        if x.shape[-1] % f or x.shape[-2] % f:
            raise ValueError(f"SS2DUNet needs H and W divisible by {f}, got {tuple(x.shape[-2:])}")
        x = self.stem(x)
        skips = []
        for i, stage in enumerate(self.enc):
            x = stage(x)
            if i < len(self.down):
                skips.append(x)
                x = self.down[i](x)
        for up, dec in zip(self.up, self.dec):
            x = up(x)
            x = dec(torch.cat([x, skips.pop()], dim=1))
        return self.head(x)
