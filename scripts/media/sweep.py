#!/usr/bin/env python3
"""Frames of a synthetic scroll swept from cap to base, with its winding center marked: a Concept illustration.

    python scripts/media/sweep.py --out-dir FRAMES [--frames 72] [--width 960] [--height 540] [--seed 7]
    python scripts/media/encode.py FRAMES --fps 18 --gif docs/assets/umbilicus/umbilicus-center-sweep.gif ...

Left: the cross-section at the current height in the scanner's fixed frame (faint axes), one sheet wound as a spiral
drawn from formulas (scenes.scroll_section), with the winding center as a copper ring that drifts as the sweep goes
down. Right: the scroll's side view at the same scale, its outline rimmed in copper, with the center's track drawn
down to the current height. Nothing comes from a scan or a model: the center is the one the formulas put there, so the picture
shows what the umbilicus finder looks for, not a result of it. Needs numpy and Pillow.
"""

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def center_at(z):
    """The synthetic winding center (x, y) in units of the scroll radius at height z in [0, 1], in the scanner's fixed
    frame: it drifts as a real scroll's center does when the scroll leans and its ends are crushed."""
    return (0.16 * math.sin(2 * math.pi * 0.8 * z + 0.4) + 0.05 * math.sin(2 * math.pi * 2.3 * z),
            0.12 * math.cos(2 * math.pi * 0.6 * z) - 0.04 * math.sin(2 * math.pi * 1.7 * z + 1.0))


def radius_at(z):
    """The scroll's outer radius at height z: narrow at the two crushed ends, full in the middle."""
    return 0.25 + 0.72 * math.sin(math.pi * min(max(z, 0.0), 1.0)) ** 0.35


def frame(z, size, seed, history):
    import numpy as np
    from PIL import Image

    from scene import COPPER, EMBER, IVORY, SHADOW, blur, hex_rgb
    from scenes import scroll_section

    w, h = size
    ss = 2
    W, H = w * ss, h * ss
    img = np.ones((H, W, 3), np.float32) * SHADOW
    scale = 0.36                                   # scroll radius 1 is this fraction of the panel side
    side = H
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    x = (xx - side / 2) / (side * scale)
    y = (yy - side / 2) / (side * scale)
    cx, cy = center_at(z)
    r_out = radius_at(z)
    sheet, along, r, edge = scroll_section((x - cx).ravel(), (y - cy).ravel(), seed, turns=9.0, r_in=0.05,
                                           r_out=r_out * 0.92, thick=0.5, wobble=0.5, gaps=0.0, squash=0.86,
                                           rot=0.3 + 0.8 * z)
    sheet, r, edge = (a.reshape(x.shape) for a in (sheet, r, edge))
    inside = r < edge + 0.01
    tone = 0.78 + 0.22 * np.clip(1 - np.hypot(x + 0.6, y + 0.7) / 2.6, 0, 1)    # key light from the upper left
    sec = SHADOW * 0.8 * (1 - sheet[..., None]) + IVORY * (sheet * tone)[..., None] * 0.9
    img[:, :side] = np.where(inside[..., None], sec, SHADOW)
    # the scanner's fixed axes, so the center's drift reads against them
    for a in (np.abs(xx - side / 2) < 0.6 * ss, np.abs(yy - side / 2) < 0.6 * ss):
        img[:, :side][a] = img[:, :side][a] * 0.6 + hex_rgb("#4A3D33") * 0.4
    # the center: a copper ring with a soft glow, and its recent track
    px, py = side / 2 + cx * side * scale, side / 2 + cy * side * scale
    d = np.hypot(xx - px, yy - py)
    glow = np.exp(-(d / (side * 0.035)) ** 2) * 0.55
    ring = np.clip(1 - np.abs(d - side * 0.022) / (1.6 * ss), 0, 1)
    dot = np.clip(1 - (d - side * 0.006) / (1.2 * ss), 0, 1)
    trail = np.zeros_like(d)
    for k, (hx, hy) in enumerate(history[-30:]):
        q = np.hypot(xx - (side / 2 + hx * side * scale), yy - (side / 2 + hy * side * scale))
        trail = np.maximum(trail, np.clip(1 - (q - 1.5 * ss) / ss, 0, 1) * (k + 1) / 30 * 0.6)
    for amount in (glow, trail, ring, dot):
        img[:, :side] = img[:, :side] * (1 - amount[..., None]) + COPPER * amount[..., None]
    # right: the side view, at the same scale, with the center's track drawn down to this height
    x0 = side + int(W * 0.05)
    pw = W - x0 - int(W * 0.04)
    top, bot = int(H * 0.07), int(H * 0.93)
    mid = x0 + pw / 2
    half = side * scale                            # the same pixels per scroll radius as the cross-section
    body, rim = hex_rgb("#2C2521"), COPPER * 0.75
    for row in range(top, bot):
        zz = (row - top) / (bot - top)
        rr_ = radius_at(zz)
        a, b = int(mid - rr_ * half), int(mid + rr_ * half)
        img[row, a:b] = body * (0.9 + 0.2 * math.sin(math.pi * zz))
        img[row, max(a - ss, 0):a + ss] = rim
        img[row, b - ss:b + ss] = rim
        tx = mid + center_at(zz)[0] * half
        lo, hi = int(tx - 1.6 * ss), int(tx + 1.6 * ss) + 1
        img[row, lo:hi] = COPPER if zz <= z else img[row, lo:hi] * 0.5 + EMBER * 0.5
    cur = int(top + z * (bot - top))
    band = slice(max(cur - ss, 0), cur + ss)
    img[band, x0:x0 + pw] = img[band, x0:x0 + pw] * 0.3 + IVORY * 0.7
    bloom = blur(np.clip(img - 0.55, 0, 1), 6 * ss)
    img = np.clip(img + 0.5 * bloom, 0, 1)
    return Image.fromarray((img * 255 + 0.5).astype(np.uint8)).resize((w, h), Image.LANCZOS)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python scripts/media/sweep.py", description=__doc__.split("\n")[0])
    p.add_argument("--out-dir", required=True, help="folder for frame-NNNNN.png")
    p.add_argument("--frames", type=int, default=72, help="frames from cap to base (default 72)")
    p.add_argument("--width", type=int, default=960, help="frame width in pixels (default 960)")
    p.add_argument("--height", type=int, default=540, help="frame height in pixels (default 540)")
    p.add_argument("--seed", type=int, default=7, help="noise seed (default 7)")
    args = p.parse_args(argv)
    if args.frames < 2 or args.width < 64 or args.height < 64:
        p.error("need at least 2 frames of at least 64 x 64 pixels")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    history = []
    for i in range(args.frames):
        z = 0.02 + 0.96 * i / (args.frames - 1)
        history.append(center_at(z))
        frame(z, (args.width, args.height), args.seed, history).save(out / f"frame-{i:05d}.png")
    print(json.dumps({"frames": args.frames, "out_dir": str(out), "width": args.width, "height": args.height}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
