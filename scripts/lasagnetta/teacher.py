"""villa's lasagna net in process on one 256^3 crop, for Lasagnetta's self-check (selfcheck.py).

It reproduces predict3d's tiles for the crop: villa's global tile lattice (tile 192, stride 128 in coordinates padded
by the 16 voxel border, so tile k reads CT [128k - 16, 128k + 176)), the same input scaling (uint8 / 255), bf16
autocast, sigmoid, villa's blend ramp over each tile's core and villa's own finalize (cos * 255, grad_mag * 1000,
encode_normal_nxny_u8). For a crop on the 128 grid two tiles per axis cover it; predict3d also blends in the tile
below, whose core reaches 32 voxels into the crop, so the outer 32 voxels on the low side of each axis can differ
slightly (scoring leaves out 32 voxels on every side). Needs a villa checkout's `lasagna/` folder (LASAGNETTA_VILLA,
default /opt/villa/lasagna) and its Python dependencies.
"""
import os
import sys
from pathlib import Path

import numpy as np
import torch

VILLA_LAS = Path(os.environ.get("LASAGNETTA_VILLA", "/opt/villa/lasagna"))
TILE, STRIDE, BORDER, OVERLAP = 192, 128, 16, 64
CROP = 256
LO, HI = BORDER, TILE - BORDER     # a tile's core inside it: [16, 176)


def villa():
    if str(VILLA_LAS) not in sys.path:
        sys.path.insert(0, str(VILLA_LAS))
    from normal_encoding import encode_normal_nxny_u8
    from train_unet_3d import build_model
    return build_model, encode_normal_nxny_u8


def ramp():
    """villa tiled_predict3d.blend_ramp(192, 16, 64): zero on the hard border, linear over 32 voxels of overlap."""
    r = np.zeros(TILE, np.float32)
    core = np.ones(HI - LO, np.float32)
    ov = min(max(0, OVERLAP - 2 * BORDER), (HI - LO) // 2)
    edges = np.linspace(0.0, 1.0, ov + 1, dtype=np.float32)[1:]
    core[:ov], core[-ov:] = edges, edges[::-1]
    r[LO:HI] = core
    return r


def tiles_for(origin):
    """Tile starts (in CT coordinates) per axis whose cores cover [o, o + 256) for o on the 128 grid, without the
    tile below (see the module note)."""
    for o in origin:
        if o % STRIDE:
            raise ValueError(f"crop origin {origin} is not on the {STRIDE} grid")
    return [[o - BORDER, o + STRIDE - BORDER] for o in origin]


def context_box(origin):
    """The CT box the tiles read: [o - 16, o + 304) per axis."""
    return tuple((o - BORDER, o + STRIDE - BORDER + TILE) for o in origin)


class Teacher:
    def __init__(self, checkpoint, device, batch=4):
        build_model, self.encode = villa()
        model, self.norm_type, _, sig = build_model(TILE, str(device), weights=str(checkpoint), strict=True)
        self.model, self.sigmoid, self.device, self.batch = model.eval(), bool(sig), device, batch
        r = torch.from_numpy(ramp()).to(device)
        self.w = r[:, None, None] * r[None, :, None] * r[None, None, :]

    @torch.no_grad()
    def raw(self, ct_ctx, origin):
        """The blended raw 8 channels (float32, (8, 256, 256, 256) on the device) of the crop at origin, from the CT of
        context_box(origin) (uint8, 320^3)."""
        box = context_box(origin)
        starts = tiles_for(origin)
        acc = torch.zeros((8, CROP, CROP, CROP), device=self.device)
        wsum = torch.zeros((CROP, CROP, CROP), device=self.device)
        x = torch.from_numpy(np.ascontiguousarray(ct_ctx)).to(self.device)
        jobs = [(z, y, xx) for z in starts[0] for y in starts[1] for xx in starts[2]]
        for i in range(0, len(jobs), self.batch):
            part = jobs[i:i + self.batch]
            t = torch.stack([x[z - box[0][0]:z - box[0][0] + TILE, y - box[1][0]:y - box[1][0] + TILE,
                               xx - box[2][0]:xx - box[2][0] + TILE] for z, y, xx in part])[:, None].float() / 255.0
            with torch.autocast(device_type=self.device.type, dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
                o = self.model(t)
            o = (o["output"] if isinstance(o, dict) else o).float()
            o = torch.sigmoid(o) if self.sigmoid else o.clamp(0.0, 1.0)
            for j, (z, y, xx) in enumerate(part):
                sl, dl = [], []
                for s, org in zip((z, y, xx), origin):
                    a, b = max(s, org), min(s + TILE, org + CROP)
                    sl.append(slice(a - s, b - s))
                    dl.append(slice(a - org, b - org))
                w = self.w[tuple(sl)]
                acc[(slice(None), *dl)] += o[j, :8][(slice(None), *sl)] * w
                wsum[tuple(dl)] += w
        return acc / wsum.clamp_min(1e-6)

    def products(self, ct_ctx, origin):
        """villa's stored uint8 products at full resolution: cos, grad_mag, nx, ny, each (256, 256, 256)."""
        slab = self.raw(ct_ctx, origin).cpu().numpy()
        cos = np.clip(slab[0] * 255.0, 0.0, 255.0).astype(np.uint8)
        gm = np.clip(slab[1] * 1000.0, 0.0, 255.0).astype(np.uint8)
        nx, ny = self.encode(slab[2], slab[3], slab[4], slab[5], slab[6], slab[7])
        return {"cos": cos, "grad_mag": gm, "nx": nx, "ny": ny}


class StubTeacher(Teacher):
    """For CPU smoke runs only: random raw channels through the same blending and finalize."""

    def __init__(self, device, batch=4):
        try:
            _, self.encode = villa()
        except ImportError:
            self.encode = lambda *ch: (np.full(ch[0].shape, 128, np.uint8), np.full(ch[0].shape, 128, np.uint8))
        self.sigmoid, self.device, self.batch = True, device, batch
        gen = torch.Generator().manual_seed(0)
        self.model = lambda t: torch.randn((t.shape[0], 8) + tuple(t.shape[2:]), generator=gen).to(t.device)
        r = torch.from_numpy(ramp()).to(device)
        self.w = r[:, None, None] * r[None, :, None] * r[None, None, :]
