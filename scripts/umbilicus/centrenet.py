"""A small heatmap CNN that places the winding centre (umbilicus) on a downsampled CT slice.

Trained on published hand-placed umbilici; every number it reports comes from scrolls it did not train on.
Input: three neighbouring level-3 slices (z - 64, z, z + 64 level-0 voxels), resampled into a square frame
around the scroll. Output: a heatmap at half resolution whose peak is the centre.
"""
import os, time
import numpy as np
import torch, torch.nn as nn, torch.nn.functional as F
import slices
from slices import smooth_z   # noqa: F401  (centrenet.smooth_z for callers; it lives in slices, which needs no torch)

def frame(npz, size, device=None):
    """Resample a scroll's slice stack into a size x size frame. Returns images (n, size, size) float16 and the frame."""
    d = np.load(npz); ct = d["ct"]; z = d["z_l0"]; f = 2 ** (int(d["level"]) if "level" in d.files else 3)
    nz = ct.max(0) > 0
    ys, xs = np.nonzero(nz); y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    side = float(max(y1 - y0, x1 - x0)) * 1.05; cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
    H, W = ct.shape[1:]
    th = torch.zeros(1, 2, 3)
    th[0, 0, 0] = side / W; th[0, 0, 2] = 2 * cx / W - 1
    th[0, 1, 1] = side / H; th[0, 1, 2] = 2 * cy / H - 1
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    grid = F.affine_grid(th, (1, 1, 2 * size, 2 * size), align_corners=False).to(device)
    imgs = []
    for b in range(0, len(ct), 32):   # area-like resampling: bilinear at 2x then 2x2 mean
        t = torch.from_numpy(ct[b:b + 32]).to(device).float()[:, None] / 255.0
        imgs.append(F.avg_pool2d(F.grid_sample(t, grid.expand(len(t), -1, -1, -1), align_corners=False), 2)[:, 0].half().cpu())
    fr = dict(oy=cy - side / 2, ox=cx - side / 2, px=side / size * f, um=float(d["um"]), vol=str(d["vol"]),
              size=size, z_l0=z, present=ct.reshape(len(ct), -1).max(1) > 0)
    return torch.cat(imgs).numpy(), fr

class Frame:
    """Coordinate maps between the net frame and level-0 voxels."""
    @staticmethod
    def net_to_l0(p, fr, level=3):
        f = 2 ** level
        # net pixel p's centre samples level-`level` coordinate o + (p + 0.5) * step - 0.5 (grid_sample, align_corners=False)
        step = fr["px"] / f
        return np.stack([(fr["oy"] + (p[:, 0] + 0.5) * step - 0.5) * f, (fr["ox"] + (p[:, 1] + 0.5) * step - 0.5) * f], 1)
    @staticmethod
    def l0_to_net(yx, fr, level=3):
        f = 2 ** level
        step = fr["px"] / f
        return np.stack([(yx[:, 0] / f - fr["oy"] + 0.5) / step - 0.5, (yx[:, 1] / f - fr["ox"] + 0.5) / step - 0.5], 1)

def truth_net(s, fr):
    """Published centre at every slice in net px (NaN outside the annotated z range)."""
    _, T = slices.truth(s); z = fr["z_l0"]
    ty, tx = np.interp(z, T[:, 0], T[:, 1]), np.interp(z, T[:, 0], T[:, 2])
    t = Frame.l0_to_net(np.stack([ty, tx], 1), fr).astype(np.float32)
    t[(z < T[0, 0]) | (z > T[-1, 0])] = np.nan
    return t

class Net(nn.Module):
    def __init__(s, c=16):
        super().__init__()
        def blk(a, b): return nn.Sequential(nn.Conv2d(a, b, 3, padding=1), nn.BatchNorm2d(b), nn.ReLU(inplace=True),
                                            nn.Conv2d(b, b, 3, padding=1), nn.BatchNorm2d(b), nn.ReLU(inplace=True))
        s.e1, s.e2, s.e3, s.e4, s.e5 = blk(3, c), blk(c, 2 * c), blk(2 * c, 4 * c), blk(4 * c, 8 * c), blk(8 * c, 8 * c)
        s.d4, s.d3, s.d2 = blk(16 * c, 4 * c), blk(8 * c, 2 * c), blk(4 * c, c)
        s.out = nn.Conv2d(c, 1, 1)
    def forward(s, x):
        x1 = s.e1(x); x2 = s.e2(F.max_pool2d(x1, 2)); x3 = s.e3(F.max_pool2d(x2, 2))
        x4 = s.e4(F.max_pool2d(x3, 2)); x5 = s.e5(F.max_pool2d(x4, 2))
        u = lambda a, b: torch.cat([F.interpolate(a, size=b.shape[-2:], mode="bilinear", align_corners=False), b], 1)
        y = s.d4(u(x5, x4)); y = s.d3(u(y, x3)); y = s.d2(u(y, x2))
        return s.out(y)[:, 0]          # half resolution

def stack3(imgs, idx):
    """(b, 3, S, S): slices i-1, i, i+1 (64 level-0 voxels apart), clamped at the ends."""
    n = len(imgs)
    return torch.stack([imgs[(idx - 1).clamp(0, n - 1)], imgs[idx], imgs[(idx + 1).clamp(0, n - 1)]], 1)

def augment(x, t, rng):
    """Random dihedral transform, shift and contrast per sample. x on any device, t (b, 2) numpy in net px.
    Random numbers and centre bookkeeping stay on the host, so the GPU never waits on them."""
    b, _, n, _ = x.shape
    out, tt = [], t.copy()
    for i in range(b):
        xi = x[i]; y, xx = tt[i]
        if rng.random() < 0.5:
            xi = xi.flip(-1); xx = n - 1 - xx
        for _ in range(int(rng.integers(4))):   # rot90 counter-clockwise: (y, x) -> (n - 1 - x, y)
            xi = torch.rot90(xi, 1, (-2, -1)); y, xx = n - 1 - xx, y
        dy, dx = (int(v) for v in rng.integers(-(n // 10), n // 10 + 1, 2))
        if not (0 <= y + dy < n and 0 <= xx + dx < n):   # torch.roll wraps: never push the centre off the frame
            dy = dx = 0
        out.append(torch.roll(xi, (dy, dx), (-2, -1))); tt[i] = (y + dy, xx + dx)
    g = torch.from_numpy(rng.uniform(0.8, 1.25, (b, 1, 1, 1)).astype(np.float32)).to(x.device)
    o = torch.from_numpy(rng.uniform(-0.1, 0.1, (b, 1, 1, 1)).astype(np.float32)).to(x.device)
    return torch.stack(out) * g + o, tt

def heat(t, m, sigma):
    yy = torch.arange(m, device=t.device).float()
    return torch.exp(-((yy[None, :, None] - t[:, 0, None, None]) ** 2 + (yy[None, None, :] - t[:, 1, None, None]) ** 2) / (2 * sigma ** 2))

def train(data, epochs, seed, width=16, batch=16, lr=2e-3, time_s=None, device="cpu", log=print):
    """data: {scroll: (imgs float16 numpy, published centres in net px from truth_net)}. Stops after `epochs` or
    `time_s` seconds."""
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    imgs = {s: torch.from_numpy(v[0]).to(device) for s, v in data.items()}
    items = [(s, i) for s, v in data.items() for i in range(len(v[1])) if np.isfinite(v[1][i, 0])]
    net = Net(width).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr, weight_decay=1e-4)
    steps = max(1, epochs * len(items) // batch)
    def lr_at(frac):
        """Warm up over the first 10 % of the run, then cosine down to 1 % of lr. The run's progress is the larger of
        steps done and time used, so a run stopped by the time cap still ends with a low learning rate."""
        frac = min(max(frac, 0.0), 1.0)
        if frac < 0.1:
            return lr * (0.04 + 0.96 * frac / 0.1)
        return lr * (0.01 + 0.99 * 0.5 * (1 + np.cos(np.pi * (frac - 0.1) / 0.9)))
    t0 = time.time(); st = 0; net.train(); stopped = "epochs"
    amp = device != "cpu"
    while st < steps:
        perm = rng.permutation(len(items)).tolist()
        for b in range(0, len(perm) - batch + 1, batch):
            sel = [items[j] for j in perm[b:b + batch]]
            x = torch.cat([stack3(imgs[s], torch.tensor([i], device=device)) for s, i in sel]).float()
            t = np.stack([data[s][1][i] for s, i in sel])
            x, t = augment(x, t, rng); t = torch.from_numpy(t).float().to(device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
                h = net(x)
            h = h.float(); g = heat(t / 2 - 0.25, h.shape[-1], 1.5)
            loss = F.binary_cross_entropy_with_logits(h, g, pos_weight=torch.tensor(50.0, device=device))
            frac = max(st / steps, (time.time() - t0) / time_s if time_s else 0.0)
            for gp in opt.param_groups:
                gp["lr"] = lr_at(frac)
            opt.zero_grad(set_to_none=True); loss.backward(); opt.step(); st += 1
            if st % 100 == 0:
                log(f"step {st}/{steps} loss {loss.item():.4f} {time.time() - t0:.0f}s")
            if st >= steps:
                break
            if time_s and time.time() - t0 > time_s:
                stopped = "time"; break
        if stopped == "time":
            break
    return net, dict(steps=st, planned_steps=steps, stopped=stopped, seconds=round(time.time() - t0, 1), items=len(items))

@torch.no_grad()
def predict(net, imgs, device="cpu"):
    """Centre per slice in net px, averaged over the 8 dihedral transforms; and peak height (0..1)."""
    x_all = torch.from_numpy(imgs).to(device)
    return predict_stacked(net, lambda idx: stack3(x_all, idx).float(), len(imgs), device)

@torch.no_grad()
def predict_stacked(net, get, n, device="cpu"):
    """predict() for inputs built by get(idx) -> (b, 3, S, S) float, idx a tensor of item numbers."""
    net.eval(); P, C = [], []
    amp = device != "cpu"
    for b in range(0, n, 32):
        idx = torch.arange(b, min(b + 32, n), device=device)
        x = get(idx); acc = 0
        for fl in (0, 1):
            for k in range(4):
                xx = x.flip(-1) if fl else x
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
                    h = net(torch.rot90(xx, k, (-2, -1))).float()
                h = torch.rot90(h, -k, (-2, -1))
                acc = acc + (h.flip(-1) if fl else h)
        p = torch.sigmoid(acc / 8).cpu()
        nb, m, _ = p.shape
        j = p.view(nb, -1).argmax(1); py, px = j // m, j % m
        for i in range(nb):
            y0, y1, x0, x1 = max(py[i] - 4, 0), min(py[i] + 5, m), max(px[i] - 4, 0), min(px[i] + 5, m)
            w = p[i, y0:y1, x0:x1]
            yy, xx = torch.meshgrid(torch.arange(y0, y1).float(), torch.arange(x0, x1).float(), indexing="ij")
            P.append([float((w * yy).sum() / w.sum() * 2 + 0.5), float((w * xx).sum() / w.sum() * 2 + 0.5)])
            C.append(float(p[i].max()))
    return np.array(P, np.float32), np.array(C, np.float32)
