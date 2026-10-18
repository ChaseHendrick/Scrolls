#!/usr/bin/env python3
"""Frames of a synthetic scroll swept from cap to base, with its winding center marked: a Concept illustration.

    python scripts/media/sweep.py --out-dir FRAMES [--frames 72] [--width 960] [--height 540] [--seed 7]
    python scripts/media/encode.py FRAMES --fps 18 --gif docs/assets/umbilicus/umbilicus-center-sweep.gif ...

Left: the cross-section at the current height, a spiral of sheets drawn from formulas (scenes.spiral_section), with
the winding center as a copper ring. Right: the scroll's side profile with the center's track drawn down to the
current height. Nothing comes from a scan or a model: the center is the one the formulas put there, so the picture
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
    """The synthetic winding center (x, y) in units of the scroll radius at height z in [0, 1]."""
    return (0.10 * math.sin(2 * math.pi * 0.8 * z + 0.4) + 0.04 * math.sin(2 * math.pi * 2.3 * z),
            0.08 * math.cos(2 * math.pi * 0.6 * z) - 0.03 * math.sin(2 * math.pi * 1.7 * z + 1.0))


def radius_at(z):
    """The scroll's outer radius at height z: narrow at the two crushed ends, full in the middle."""
    return 0.25 + 0.72 * math.sin(math.pi * min(max(z, 0.0), 1.0)) ** 0.35


def frame(z, size, seed, history):
    import numpy as np
    from PIL import Image

    from scene import CHARCOAL, COPPER, EMBER, IVORY, blur
    from scenes import ring_noise, spiral_section

    w, h = size
    ss = 2
    W, H = w * ss, h * ss
    img = np.ones((H, W, 3), np.float32) * CHARCOAL
    # left: the cross-section
    side = H
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    x = (xx - side / 2) / (side * 0.42)
    y = (yy - side / 2) / (side * 0.42)
    cx, cy = center_at(z)
    r_out = radius_at(z)
    rr, th = np.hypot(x - cx, y - cy), np.arctan2(y - cy, x - cx)
    edge = r_out * (0.94 + 0.06 * (ring_noise(np.arctan2(y, x), 0.0, 1.4, 0.0, seed + int(z * 7)) - 0.5) * 2)
    inside = np.hypot(x, y) < edge
    sheet = spiral_section(rr.ravel(), th.ravel(), 1 / 15, seed, gaps=0.3, wobble=0.7, thick=0.26).reshape(rr.shape)
    sheet = sheet * inside * (1 - np.clip((0.07 - rr) / 0.05, 0, 1))
    tone = 0.55 + 0.45 * np.clip(1 - np.hypot(x + 0.4, y + 0.5) / 2.2, 0, 1)        # key light from the upper left
    sec = CHARCOAL * (1 - sheet[..., None]) + IVORY * (sheet * tone)[..., None] * 0.92
    sec = np.where(inside[..., None], sec * 0.96 + EMBER * 0.04, CHARCOAL)
    img[:, :side] = sec
    # the center: a copper ring with a soft glow, and the recent track
    px, py = side / 2 + cx * side * 0.42, side / 2 + cy * side * 0.42
    d = np.hypot(xx - px, yy - py)
    glow = np.exp(-(d / (side * 0.035)) ** 2) * 0.55
    ring = np.clip(1 - np.abs(d - side * 0.022) / (1.6 * ss), 0, 1)
    dot = np.clip(1 - (d - side * 0.006) / (1.2 * ss), 0, 1)
    trail = np.zeros_like(d)
    for k, (hx, hy) in enumerate(history[-24:]):
        q = np.hypot(xx - (side / 2 + hx * side * 0.42), yy - (side / 2 + hy * side * 0.42))
        trail = np.maximum(trail, np.clip(1 - (q - 1.5 * ss) / ss, 0, 1) * (k + 1) / 24 * 0.5)
    for amount in (glow, trail, ring, dot):
        img[:, :side] = img[:, :side] * (1 - amount[..., None]) + COPPER * amount[..., None]
    # right: the side profile and the center's track
    x0 = side + int(W * 0.06)
    pw = W - x0 - int(W * 0.05)
    zs = np.linspace(0, 1, H, dtype=np.float32)
    top, bot = int(H * 0.08), int(H * 0.92)
    for row in range(top, bot):
        zz = (row - top) / (bot - top)
        r = radius_at(zz)
        mid = x0 + pw / 2
        a, b = int(mid - r * pw * 0.42), int(mid + r * pw * 0.42)
        shade = 0.55 + 0.25 * math.sin(math.pi * zz)
        img[row, a:b] = CHARCOAL * (1 - shade * 0.35) + EMBER * shade * 0.35
        if zz <= z:
            tx = mid + center_at(zz)[0] * pw * 0.42 * 2.2
            lo, hi = int(tx - 1.6 * ss), int(tx + 1.6 * ss) + 1
            img[row, lo:hi] = COPPER
    cur = int(top + z * (bot - top))
    img[max(cur - ss, 0):cur + ss, x0:x0 + pw] = img[max(cur - ss, 0):cur + ss, x0:x0 + pw] * 0.3 + IVORY * 0.7
    bloom = blur(np.clip(img - 0.55, 0, 1), 6 * ss)
    img = np.clip(img + 0.5 * bloom, 0, 1)
    out = Image.fromarray((img * 255 + 0.5).astype(np.uint8)).resize((w, h), Image.LANCZOS)
    del zs
    return out


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
