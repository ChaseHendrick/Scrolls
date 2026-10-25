"""Lasagnetta, a student of villa's lasagna net: a small 3D U-Net that reads the teacher's CT and writes the teacher's
stored products at their own scaledowns, cos at 1/2 and grad_mag plus the normal at 1/4, so it never decodes back to
full resolution (the teacher's costliest stage). Plain torch; BatchNorm so a tile's output does not depend on the
tile's contents elsewhere, as InstanceNorm's does.

Outputs (logits for cos and gm, a free 3-vector for the normal, sign-free):
  cos    (B, 1, D/2, H/2, W/2)
  gm     (B, 1, D/4, H/4, W/4)    stored grad_mag / 255
  normal (B, 3, D/4, H/4, W/4)
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

CONFIGS = {
    # name: widths at 1, 1/2, 1/4, 1/8, 1/16 (and 1/32 when six are given), convs per stage (one number, or one per
    # stage below the stem); norm_input: each tile scaled to zero mean and unit spread over its non-zero CT voxels
    "s16": {"widths": (8, 16, 32, 64, 128), "depth": 1},
    "m24": {"widths": (12, 24, 48, 96, 160), "depth": 2},
    "l32": {"widths": (16, 32, 64, 128, 192, 256), "depth": 2},
    # dev round 2: per-tile input normalization, and more depth where the grid is coarse
    "l32n": {"widths": (16, 32, 64, 128, 192, 256), "depth": 2, "norm_input": True},
    "xl": {"widths": (16, 32, 64, 128, 256, 320), "depth": (2, 2, 3, 4, 4), "norm_input": True},
    # dev round 3: the full-resolution stem features, folded 2x2x2 into channels, feed the cos
    # head at 1/2 (round 2's nets never read them past the first strided stage); f2 adds a second stem convolution
    "l32nf": {"widths": (16, 32, 64, 128, 192, 256), "depth": 2, "norm_input": True, "full_skip": True},
    "l32nf2": {"widths": (16, 32, 64, 128, 192, 256), "depth": 2, "norm_input": True, "full_skip": True,
               "stem_depth": 2},
    # later round: the student underfits again (training crops score as dev), and the cos head at 1/2 is
    # where sheet peaks are placed, so w24 widens the fine stages (1, 1/2, 1/4) by half as well as the coarse ones
    "w24": {"widths": (24, 48, 96, 160, 256, 320), "depth": (2, 2, 3, 3, 3), "norm_input": True},
    # w24 beat xl at every step (dev peak F1 0.822 against 0.805), so w32 widens the fine stages again
    "w32": {"widths": (32, 64, 128, 192, 256, 320), "depth": (2, 2, 3, 3, 3), "norm_input": True},
}


def conv(cin, cout, stride=1):
    return nn.Sequential(nn.Conv3d(cin, cout, 3, stride, 1, bias=False), nn.BatchNorm3d(cout),
                         nn.LeakyReLU(0.01, inplace=True))


class Stage(nn.Sequential):
    def __init__(self, cin, cout, depth, stride):
        super().__init__(conv(cin, cout, stride), *[conv(cout, cout) for _ in range(depth - 1)])


class Up(nn.Module):
    def __init__(self, cin, cskip, cout, depth):
        super().__init__()
        self.up = nn.ConvTranspose3d(cin, cin // 2, 2, 2)
        self.fuse = Stage(cin // 2 + cskip, cout, depth, 1)

    def forward(self, x, skip):
        return self.fuse(torch.cat([self.up(x), skip], 1))


def fold2(x):
    """(B, C, D, H, W) to (B, 8C, D/2, H/2, W/2): each 2x2x2 block's values as channels, nothing lost."""
    b, c, d, h, w = x.shape
    x = x.reshape(b, c, d // 2, 2, h // 2, 2, w // 2, 2).permute(0, 1, 3, 5, 7, 2, 4, 6)
    return x.reshape(b, c * 8, d // 2, h // 2, w // 2)


class LasStudent(nn.Module):
    def __init__(self, widths=(12, 24, 48, 96, 160), depth=2, norm_input=False, full_skip=False, stem_depth=1):
        super().__init__()
        w = list(widths)
        dep = [depth] * (len(w) - 1) if isinstance(depth, int) else list(depth)
        self.norm_input = norm_input
        self.stem = Stage(1, w[0], stem_depth, 1) if stem_depth > 1 else conv(1, w[0])
        self.full = Stage(w[1] + 8 * w[0], w[1], 2, 1) if full_skip else None
        self.down = nn.ModuleList(Stage(w[i], w[i + 1], dep[i], 2) for i in range(len(w) - 1))
        # decoder from the deepest stage back to 1/2 (index 1); 1/4 is index 2
        self.up = nn.ModuleList(Up(w[i + 1], w[i], w[i], min(2, dep[i - 1])) for i in range(len(w) - 2, 0, -1))
        self.head_other = nn.Conv3d(w[2], 4, 1)
        self.head_cos = nn.Conv3d(w[1], 1, 1)

    def forward(self, x):
        if self.norm_input:
            m = (x > 0).float()
            n = m.sum(dim=(1, 2, 3, 4), keepdim=True).clamp_min(1.0)
            mean = (x * m).sum(dim=(1, 2, 3, 4), keepdim=True) / n
            var = (((x - mean) * m) ** 2).sum(dim=(1, 2, 3, 4), keepdim=True) / n
            x = (x - mean) / (var.sqrt() + 1e-3) * m
        feats = [self.stem(x)]
        for d in self.down:
            feats.append(d(feats[-1]))
        y = feats[-1]
        level = len(feats) - 1
        other = None
        for u in self.up:
            level -= 1
            y = u(y, feats[level])
            if level == 2:
                other = self.head_other(y)
        if self.full is not None:
            y = self.full(torch.cat([y, fold2(feats[0])], 1))
        return {"cos": self.head_cos(y), "gm": other[:, :1], "normal": other[:, 1:]}


def build(name):
    return LasStudent(**CONFIGS[name])


def cos_slope_loss(cos_logit, tgt_cos, mask):
    """Relative squared error of cos's differences along y and along x (amendment 6): extra wiggles between the
    teacher's sheets, the spurious peaks the sheet-peak F1 counts, show up as wrong slopes. Pairs inside the mask."""
    c = torch.sigmoid(cos_logit.float())
    num = den = c.new_zeros(())
    for ax in (3, 4):                                             # (B, 1, z, y, x): y and x
        n = c.shape[ax] - 1
        ds, dt = c.narrow(ax, 1, n) - c.narrow(ax, 0, n), tgt_cos.narrow(ax, 1, n) - tgt_cos.narrow(ax, 0, n)
        m = mask.narrow(ax, 1, n) * mask.narrow(ax, 0, n)
        num = num + ((ds - dt) ** 2 * m).sum()
        den = den + (dt ** 2 * m).sum()
    return num / den.clamp_min(1e-6)


def losses(out, tgt, slope_w=0.0):
    """BCE on cos and gm (soft targets, papyrus mask), 1 - (n.t)^2 on the normal (sign-free); with slope_w > 0 also
    slope_w times cos_slope_loss."""
    mc, mo = tgt["mask_cos"].float(), tgt["mask_other"].float()
    nc, no = mc.sum().clamp_min(1.0), mo.sum().clamp_min(1.0)
    l_cos = (F.binary_cross_entropy_with_logits(out["cos"].float(), tgt["cos"], reduction="none") * mc).sum() / nc
    l_gm = (F.binary_cross_entropy_with_logits(out["gm"].float(), tgt["gm"], reduction="none") * mo).sum() / no
    n = F.normalize(out["normal"].float(), dim=1, eps=1e-6)
    l_n = ((1.0 - (n * tgt["normal"]).sum(1, keepdim=True) ** 2) * mo).sum() / no
    res = {"cos": l_cos, "gm": l_gm, "normal": l_n, "total": l_cos + l_gm + l_n}
    if slope_w > 0:
        res["slope"] = cos_slope_loss(out["cos"], tgt["cos"], mc)
        res["total"] = res["total"] + slope_w * res["slope"]
    return res


def to_maps(out):
    """Network output to the metric's maps: cos and gm on 0..1, the normal as a unit vector."""
    return {"cos": torch.sigmoid(out["cos"].float()), "gm": torch.sigmoid(out["gm"].float()),
            "normal": F.normalize(out["normal"].float(), dim=1, eps=1e-6)}


# inference recipes: flips of the input's spatial axes (0 z, 1 y, 2 x), averaged
FLIP_SETS = {"none": [()], "yx4": [(), (1,), (2,), (1, 2)],
             "x8": [(), (0,), (1,), (2,), (0, 1), (0, 2), (1, 2), (0, 1, 2)]}


def blur(v, sigmas):
    """Separable Gaussian blur of (N, 1, z, y, x) with one sigma per spatial axis (edges replicated; 0 skips)."""
    for ax, sigma in enumerate(sigmas):
        if sigma <= 0:
            continue
        r = max(1, int(math.ceil(3 * sigma)))
        k = torch.exp(-(torch.arange(-r, r + 1, dtype=torch.float32, device=v.device) ** 2) / (2 * sigma * sigma))
        shape = [1, 1, 1, 1, 1]
        shape[2 + ax] = 2 * r + 1
        pad = [0, 0, 0, 0, 0, 0]
        pad[2 * (2 - ax)] = pad[2 * (2 - ax) + 1] = r
        v = F.conv3d(F.pad(v, pad, mode="replicate"), (k / k.sum()).reshape(shape))
    return v


class Ensemble(nn.Module):
    """Several students read as one: predict_maps averages every member over every flip. forward runs each member
    and returns the last one's output (for timing only)."""

    def __init__(self, members):
        super().__init__()
        self.members = nn.ModuleList(members)

    def forward(self, x):
        out = None
        for m in self.members:
            out = m(x)
        return out


@torch.no_grad()
def predict_maps(net, x, flips=((),), cos_blur=(0, 0, 0), cos_offset=0.0):
    """to_maps of net on x (N, 1, z, y, x), averaged over flips of x (each output flipped back and the normal's
    components on flipped axes negated) and, for an Ensemble, over its members: cos and gm as means, the normal as a
    sign-aligned mean (aligned to the first output) normalized; then cos blurred with sigmas (z, y, x) in cos voxels
    and lowered by cos_offset, clipped to 0..1 (the same as a higher peak threshold; fitted on training crops).
    One net, one flip, no blur: to_maps(net(x))."""
    acc = ref = None
    runs = [(m, f) for m in (net.members if isinstance(net, Ensemble) else [net]) for f in flips]
    for member, f in runs:
        dims = tuple(2 + a for a in f)
        m = to_maps(member(x.flip(dims) if f else x))
        if f:
            m = {k: v.flip(dims) for k, v in m.items()}
            sign = torch.ones(3, device=x.device)
            for a in f:              # channel order x, y, z: spatial axis 0 (z) is channel 2, axis 2 (x) is channel 0
                sign[2 - a] = -1.0
            m["normal"] = m["normal"] * sign.view(1, 3, 1, 1, 1)
        if acc is None:
            acc, ref = {k: v.clone() for k, v in m.items()}, m["normal"]
            continue
        acc["cos"] += m["cos"]
        acc["gm"] += m["gm"]
        acc["normal"] += m["normal"] * torch.where((m["normal"] * ref).sum(1, keepdim=True) < 0, -1.0, 1.0)
    acc["cos"] /= len(runs)
    acc["gm"] /= len(runs)
    acc["normal"] = F.normalize(acc["normal"], dim=1, eps=1e-6)
    if any(cos_blur):
        with torch.autocast(device_type=x.device.type, enabled=False):      # in float32, not autocast's bf16
            acc["cos"] = blur(acc["cos"].float(), cos_blur)
    if cos_offset:
        acc["cos"] = (acc["cos"] - cos_offset).clamp(0.0, 1.0)
    return acc
