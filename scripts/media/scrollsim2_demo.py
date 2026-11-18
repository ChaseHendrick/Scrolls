#!/usr/bin/env python3
"""Synthetic demo pictures of ScrollSim v2 (`kit.scrollsim2`): every pixel comes from a synthetic scroll this script
renders itself. No scan data, no labels from any real scroll, no model output.

It makes two scrolls with kit.scrollsim2 (the smoke preset, and a 96 x 640 x 640 one of about 21 windings), then draws:

  scrollsim2-slice.png     one axial slice of the CT beside the same slice with its exact winding labels over it
  scrollsim2-stages.png    one slice of the same seed three ways: a round roll, contact zones added, then crushed
                           and bent (the defaults)
  scrollsim2-surface.png   the whole sheet's center surface (tifxyz) in 3D, colored by winding number
  scrollsim2-zscroll.gif   a slow pass through z, CT beside labels

Each with a sidecar JSON (scripts/media/common.py). Needs numpy, scipy, zarr, tifffile, matplotlib and Pillow.

  python scripts/media/scrollsim2_demo.py --work WORK --out-dir docs/assets/scrollsim2
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import common  # noqa: E402

SCRIPTS = ("common.py", "scrollsim2_demo.py")
MEDIUM = {"shape": [96, 640, 640]}
BG = "#FAF8F4"                      # warm off-white: reads on light and dark pages
FG = "#24282B"
MUTED = "#6B6F73"
# Winding colors, cycled: adjacent windings always differ, and no hue family dominates.
WIND = ["#3B6FB6", "#E08A2E", "#8A55B0", "#C8453C", "#2E9C9A", "#C9A227"]
COMMAND = "python scripts/media/scrollsim2_demo.py --work WORK --out-dir docs/assets/scrollsim2"


def _style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
                         "text.color": FG, "axes.labelcolor": FG, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.edgecolor": "#C9C4BA", "font.size": 12, "axes.titlesize": 14,
                         "axes.titleweight": "bold", "font.family": "DejaVu Sans"})
    return plt


def make_runs(work):
    from kit import scrollsim2 as s2
    work = Path(work)
    out = {}
    for name, over, preset in (("smoke", {}, "smoke"), ("medium", dict(MEDIUM), None)):
        d = work / name
        if not (d / "truth.json").is_file():
            s2.make(d, over, preset, workers=s2.default_workers(), block=64 if name == "smoke" else 128, chunk=64,
                    levels=2, surfaces=True, progress=None)
        out[name] = d
    return out


def load(d):
    import zarr
    import numpy as np
    ct = np.asarray(zarr.open_group(str(d / "ct.zarr"), mode="r")["0"][:])
    lab = np.asarray(zarr.open_group(str(d / "truth" / "labels.zarr"), mode="r")["0"][:])
    return ct, lab, json.loads((d / "truth.json").read_text())


def overlay(np, ct, lab, alpha=0.62):
    """RGB float image: gray CT, sheet voxels tinted by winding number (cycled palette)."""
    from matplotlib.colors import to_rgb
    g = (ct.astype(np.float32) / 255.0)[..., None].repeat(3, -1)
    pal = np.array([to_rgb(c) for c in WIND], np.float32)
    col = pal[(np.maximum(lab.astype(np.int64), 1) - 1) % len(WIND)]
    m = (lab > 0)[..., None]
    return np.where(m, (1 - alpha) * g + alpha * col, g)


def ray_numbers(np, lab, cy, cx, angle, every=5):
    """(y, x, winding) where the ray from (cy, cx) at ANGLE (radians, the crush's long axis) first meets each winding
    that is a multiple of EVERY."""
    seen, out = set(), []
    for t in np.arange(0, max(lab.shape), 0.5):
        y, x = cy + t * np.sin(angle), cx + t * np.cos(angle)
        if not (0 <= y < lab.shape[0] - 0.5 and 0 <= x < lab.shape[1] - 0.5):
            break
        w = int(lab[int(round(y)), int(round(x))]) - 1
        if w > 0 and w % every == 0 and w not in seen:
            seen.add(w)
            out.append((y, x, w))
    return out


def save(fig, path, dpi):
    fig.savefig(path, dpi=dpi)
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def fig_slice(plt, np, d, out):
    ct, lab, doc = load(d)
    z = ct.shape[0] // 2
    cl = np.asarray(doc["center_line"])
    cx = float(np.interp(z, cl[:, 2], cl[:, 0]))
    cy = float(np.interp(z, cl[:, 2], cl[:, 1]))
    fig, axs = plt.subplots(1, 2, figsize=(12.8, 6.9))
    axs[0].imshow(ct[z], cmap="gray", vmin=0, vmax=255, interpolation="nearest")
    axs[0].set_title(f"Synthetic CT, slice z = {z}")
    axs[1].imshow(overlay(np, ct[z], lab[z]), interpolation="nearest")
    axs[1].set_title("Exact winding labels over it")
    for y, x, w in ray_numbers(np, lab[z], cy, cx, float(doc["alpha"]) + np.pi):
        axs[1].text(x, y, str(w), ha="center", va="center", fontsize=11, fontweight="bold", color=FG,
                    bbox=dict(boxstyle="round,pad=0.22", fc=BG, ec="#C9C4BA", lw=0.6, alpha=0.92))
    for ax in axs:
        ax.set_xlabel("x (voxels)")
        ax.set_ylabel("y (voxels)")
    fig.suptitle(f"ScrollSim v2: about {doc['turns']:.0f} windings in {ct.shape[2]} x {ct.shape[1]} voxels; "
                 "colors repeat every 6 windings, numbers mark every 5th", fontsize=13, color=MUTED, y=0.03)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    size = save(fig, out, 150)
    plt.close(fig)
    return size, {"z": z, "turns": doc["turns"], "shape": ct.shape[::-1][:2]}


def fig_stages(plt, np, out):
    from kit import scrollsim2 as s2
    base = {"shape": [16, 512, 512], "seed": 3}
    cases = [("Round roll, no contacts", dict(base, squash=1.0, contact_share=0.0, warp=0.0)),
             ("Contact zones added", dict(base, squash=1.0, warp=0.0)),
             ("Crushed and bent (defaults)", dict(base))]
    fig, axs = plt.subplots(1, 3, figsize=(15.6, 5.9))
    for ax, (title, p) in zip(axs, cases):
        sc = s2.Scroll2(p)
        ct, lab, _ = sc.scan_block(8, 9, 0, 512, 0, 512)
        ax.imshow(overlay(np, ct[0], lab[0], alpha=0.5), interpolation="nearest")
        ax.set_title(title)
        ax.set_xlabel("x (voxels)")
        ax.set_ylabel("y (voxels)")
    fig.suptitle("One seed, three settings: contact_share 0 then 0.45; squash 1 then 0.5 with warp 5 voxels",
                 fontsize=13, color=MUTED, y=0.04)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    size = save(fig, out, 120)
    plt.close(fig)
    keys = ("shape", "seed", "contact_share", "squash", "warp", "alpha")
    return size, {"cases": [{"title": t, **{k: s2.params(p)[k] for k in keys}} for t, p in cases]}


def fig_surface(plt, np, d, out):
    import tifffile
    from matplotlib.colors import to_rgb
    s = d / "truth" / "surfaces" / "spiral-center"
    P = np.stack([tifffile.imread(s / f"{c}.tif") for c in "xyz"], -1)
    w = np.load(s / "winding.npy")
    k = 3                                                       # every 3rd vertex in each direction
    P, w = P[::k, ::k], w[::k, ::k]
    ok = (P >= 0).all(-1) & np.isfinite(w)
    cx, cy = np.median(P[ok][:, 0]), np.median(P[ok][:, 1])
    ok &= ~((P[..., 0] > cx) & (P[..., 1] < cy))                # cut away the quarter facing the camera
    pal = np.array([to_rgb(c) for c in WIND])
    col = pal[(np.where(ok, w, 1).astype(np.int64) - 1) % len(WIND)]
    col = np.concatenate([col, np.where(ok, 1.0, 0.0)[..., None]], -1)
    X, Y, Z = (np.where(ok, P[..., i], np.nan) for i in range(3))
    fig = plt.figure(figsize=(12.8, 7.6))
    ax = fig.add_subplot(projection="3d")
    ax.set_facecolor(BG)
    ax.plot_surface(X, Y, Z, facecolors=col, rstride=1, cstride=1, linewidth=0, antialiased=False, shade=True)
    ax.set_box_aspect((1, 1, 0.42))
    ax.view_init(elev=28, azim=-58)
    ax.set_xlabel("x (voxels)", labelpad=8)
    ax.set_ylabel("y (voxels)", labelpad=8)
    ax.set_zlabel("z", labelpad=2)
    for a in (ax.xaxis, ax.yaxis, ax.zaxis):
        a.set_pane_color((0.96, 0.95, 0.93, 1.0))
    ax.set_title("The whole sheet's center surface (tifxyz), colored by its exact winding number", pad=4)
    fig.text(0.5, 0.04, "One quarter cut away to show the windings inside; colors repeat every 6. "
             "Every 3rd vertex drawn.",
             ha="center", color=MUTED, fontsize=12)
    fig.subplots_adjust(left=0.0, right=1.0, top=0.95, bottom=0.06)
    size = save(fig, out, 150)
    plt.close(fig)
    return size, {"vertex_stride": k, "windings": int(np.nanmax(w))}


def gif_z(np, d, out, scale=0.5):
    from PIL import Image, ImageDraw, ImageFont
    import matplotlib
    ct, lab, _ = load(d)
    font = ImageFont.truetype(str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"), 18)
    H, W = ct.shape[1], ct.shape[2]
    w2, h2 = int(W * scale), int(H * scale)
    frames = []
    for z in range(0, ct.shape[0], 4):
        a = Image.fromarray(ct[z]).convert("RGB").resize((w2, h2), Image.BILINEAR)
        b = Image.fromarray((overlay(np, ct[z], lab[z]) * 255).astype(np.uint8)).resize((w2, h2), Image.NEAREST)
        f = Image.new("RGB", (2 * w2 + 30, h2 + 44), BG)
        f.paste(a, (10, 34))
        f.paste(b, (w2 + 20, 34))
        dr = ImageDraw.Draw(f)
        dr.text((12, 7), f"Synthetic CT, z = {z}", font=font, fill=FG)
        dr.text((w2 + 22, 7), "Exact winding labels", font=font, fill=FG)
        frames.append(f.quantize(colors=48, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=200, loop=0, optimize=True)
    return frames[0].size, {"frames": len(frames), "z_step": 4, "frame_ms": 200}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True, help="scratch folder for the two synthetic scrolls (reused if present)")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    import numpy as np
    plt = _style()
    runs = make_runs(a.work)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("scrollsim2-slice.png", lambda p: fig_slice(plt, np, runs["medium"], p),
         "Two panels of one synthetic slice, 640 by 640 voxels: on the left gray CT of a crushed spiral of papyrus "
         "windings with noise, on the right the same slice with every sheet voxel tinted by its exact winding number "
         "in six repeating colors, and every fifth winding numbered along a line from the center.",
         "Synthetic demo: ScrollSim v2 slice and its exact winding labels. No scan data."),
        ("scrollsim2-stages.png", lambda p: fig_stages(plt, np, p),
         "Three synthetic slices of one seed, tinted by winding: a round evenly spaced spiral, the same spiral with "
         "windings pressed together in places, and the same roll crushed to an oval and gently bent.",
         "Synthetic demo: one ScrollSim v2 seed without contacts, with contact zones, and crushed and bent. "
         "No scan data."),
        ("scrollsim2-surface.png", lambda p: fig_surface(plt, np, runs["medium"], p),
         "A 3D view of a synthetic sheet's center surface, a crushed spiral wall about 21 windings deep with one "
         "quarter cut away, each winding drawn in one of six repeating colors.",
         "Synthetic demo: the whole sheet's center surface from ScrollSim v2, colored by winding number. "
         "No scan data."),
        ("scrollsim2-zscroll.gif", lambda p: gif_z(np, runs["medium"], p),
         "Animation through z of a synthetic scroll: gray CT on the left and the same slice tinted by winding "
         "number on the right; the spiral shifts slowly as the slices pass.",
         "Synthetic demo: a pass through z of a ScrollSim v2 scroll, CT beside its winding labels. No scan data."),
    ]
    for name, draw, alt, caption in jobs:
        path = out_dir / name
        meta = common.check_meta({"label": "Synthetic demo", "alt": alt, "caption": caption, "license": "Apache-2.0"})
        common.write_guard(meta["label"], path, meta)
        (w, h), info = draw(path)
        common.size_guard(path, w)
        rec = common.output_record(path, w, h, kind="clip" if name.endswith(".gif") else "still",
                                   format=name.rsplit(".", 1)[1])
        common.write_sidecar(path.with_suffix(".json"), meta, [rec], command=COMMAND, scripts=SCRIPTS,
                             extra={"scrollsim2": json.loads(json.dumps(info, default=list))})
        print(f"{name}: {w} x {h}, {path.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
