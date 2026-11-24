#!/usr/bin/env python3
"""Synthetic demo pictures of ScrollSim v2 (`kit.scrollsim2`): every pixel comes from a synthetic scroll this script
renders itself. No scan data, no labels from any real scroll, no model output.

It makes two scrolls with kit.scrollsim2 (the smoke preset, and a 96 x 640 x 640 one of about 21 windings), plus an
inked 128 x 512 x 512 scroll and its noink twin for the ink pictures, then draws:

  scrollsim2-slice.png     one axial slice of the CT beside the same slice with its exact winding labels over it
  scrollsim2-stages.png    one slice of the same seed three ways: a round roll, contact zones added, then crushed
                           and bent (the defaults)
  scrollsim2-surface.png   the whole sheet's center surface (tifxyz) in 3D, colored by winding number
  scrollsim2-zscroll.gif   a slow pass through z, CT beside labels
  scrollsim2-scan.png      one crop of the medium scroll under three scan models (none, --scan synchrotron,
                           --scan lab) and each one's noise power spectrum
  scrollsim2-orbit.gif     the center surface swung from side to side
  scrollsim2-pressed.png   the box with the most pressed sheet on one slice: CT, labels and contact truth
  scrollsim2-pressed-z.gif a pass through z of that box
  scrollsim2-truth.png     the --truth contact,uvw layers on a crop of one slice
  scrollsim2-physics.png   one crop with each sheet-physics effect alone and all together (exaggerated demo settings)
  scrollsim2-physics-steps.gif  the same crop as the effects are switched on one at a time
  scrollsim2-ink.png       a third scroll with the ink writer on, and its noink twin: a flattened stretch of the recto
                           face as ink truth, CT with ink, CT without, and their difference
  scrollsim2-ink-layers.gif  layers through the sheet at the inked face, CT with ink above the difference

Each with a sidecar JSON (scripts/media/common.py). Needs numpy, scipy, zarr, tifffile, matplotlib and Pillow.

  python scripts/media/scrollsim2_demo.py --work WORK --out-dir docs/assets/scrollsim2 [--only NAME ...]
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


SCAN_CROP = (40, 56, 128, 512, 128, 512)       # z, y, x of the medium scroll: the middle third of the roll


def fig_scan(plt, np, out):
    """The same crop rendered with no scan model, --scan synchrotron and --scan lab (scan_block, so only the crop
    is rendered), and the noise power spectrum of each, measured by kit.scrollsim2.measure_nps on an air box."""
    from kit import scrollsim2 as s2
    z0, z1, y0, y1, x0, x1 = SCAN_CROP
    zc = (z1 - z0) // 2
    rows = [("No scan model (release 1)", ""), ("--scan synchrotron", "synchrotron"), ("--scan lab", "lab")]
    cols = ["#3B6FB6", "#E08A2E", "#8A55B0"]
    fig, axs = plt.subplots(1, 4, figsize=(19.2, 5.4), gridspec_kw={"width_ratios": [1, 1, 1, 1.15]})
    info = {"crop_zyx": list(SCAN_CROP), "slice_z": z0 + zc, "nps": {}}
    for ax, (title, scan), col in zip(axs[:3], rows, cols):
        sc = s2.Scroll2(dict(MEDIUM, scan=scan))
        sc.prepare()
        ct = sc.scan_block(z0, z1, y0, y1, x0, x1)[0]
        ax.imshow(ct[zc], cmap="gray", vmin=0, vmax=255, interpolation="nearest",
                  extent=(x0 - 0.5, x1 - 0.5, y1 - 0.5, y0 - 0.5))
        ax.set_title(title)
        ax.set_xlabel("x (voxels)")
        ax.set_ylabel("y (voxels)")
        air = sc.scan_block(0, 64, -700, -636, -700, -636)[0].astype(float)
        m = s2.measure_nps(air, tile=32, share=1.0)
        fr, ps = np.array(m["freq"]), np.array(m["psd"])
        keep = (fr > 0) & (fr <= 0.5)
        axs[3].plot(fr[keep], ps[keep], color=col, lw=2.4, label=f"{title.split(' (')[0]}, sd {m['variance'] ** 0.5:.1f}")
        info["nps"][scan or "none"] = {"variance": round(m["variance"], 3)}
    a = axs[3]
    a.set_title("Noise power spectrum in air")
    a.set_xlabel("frequency (cycles per voxel)")
    a.set_ylabel("power (gray levels squared)")
    a.set_yscale("log")
    a.grid(True, color="#E4DFD6", lw=0.8)
    a.legend(frameon=False, fontsize=11, loc="upper right")
    for sp in ("top", "right"):
        a.spines[sp].set_visible(False)
    fig.suptitle(f"ScrollSim v2 scan models on one synthetic crop, slice z = {z0 + zc}; presets are a starting "
                 "point, not a calibration", fontsize=13, color=MUTED, y=0.03)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    size = save(fig, out, 100)
    plt.close(fig)
    return size, info


# ---------------------------------------------------------------- pictures added 2026-11-18: physics, truth, ink, orbit
# Sheet physics settings for the pictures: exaggerated so each effect shows at this zoom. They are demo values, not
# measurements of real papyrus.
PHYS = [("Plain sheet (defaults)", {}),
        ("Waviness", {"wave_amp": 1.2, "wave_len": 64.0}),
        ("Glued joins (kolleseis)", {"kolle_every": 900.0, "kolle_len": 300.0}),
        ("Gap debris, strands, dust", {"debris": 0.4, "debris_r": 1.3, "strands": 0.3, "dust": 0.25}),
        ("Cracks", {"cracks": 30.0, "crack_len": 8.0, "crack_w": 1.0}),
        ("Carbonization bubbles", {"bubbles": 0.6, "bubble_r": 1.6}),
        ("Ply density variation", {"ply_var": 0.5, "ply_var_len": 60.0})]
PHYS_CROP = (48, 400, 200, 96)           # z, y0, x0, edge of the medium scroll, low on the left of the roll


def _phys_all():
    allp = {}
    for _, o in PHYS[1:]:
        allp.update(o)
    return allp


def _phys_crop(over):
    from kit import scrollsim2 as s2
    z, y0, x0, n = PHYS_CROP
    sc = s2.Scroll2(dict(MEDIUM, **over))
    sc.prepare()
    return sc.scan_block(z, z + 1, y0, y0 + n, x0, x0 + n)[0][0]


def fig_physics(plt, np, out):
    """One crop of the medium scroll with each sheet-physics effect alone, and all of them together."""
    cases = PHYS + [("All of them together", _phys_all())]
    fig, axs = plt.subplots(2, 4, figsize=(19.2, 10.9))
    for ax, (title, over) in zip(axs.ravel(), cases):
        ax.imshow(_phys_crop(over), cmap="gray", vmin=0, vmax=255, interpolation="nearest")
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
    z, y0, x0, n = PHYS_CROP
    fig.suptitle(f"ScrollSim v2 sheet physics, one {n} x {n} voxel crop at z = {z}; demo settings exaggerated to show "
                 "each effect, not measured on real papyrus", fontsize=14, color=MUTED, y=0.025)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.955, bottom=0.06, wspace=0.04, hspace=0.1)
    size = save(fig, out, 100)
    plt.close(fig)
    return size, {"crop_z_y0_x0_edge": list(PHYS_CROP), "cases": [{"title": t, "set": o} for t, o in cases]}


def _font(size):
    from PIL import ImageFont
    import matplotlib
    return ImageFont.truetype(str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"), size)


def _gray_panel(np, a, scale):
    from PIL import Image
    im = Image.fromarray(np.ascontiguousarray(a)).convert("RGB")
    return im.resize((a.shape[1] * scale, a.shape[0] * scale), Image.NEAREST)


def _gif_save(frames, out, ms, colors=64):
    from PIL import Image
    q = [f.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    q[0].save(out, save_all=True, append_images=q[1:], duration=ms, loop=0, optimize=True)
    return q[0].size


def gif_physics(np, out, scale=3):
    """The same crop as physics effects are switched on one at a time, then the plain sheet again."""
    from PIL import Image, ImageDraw
    font = _font(17)
    over, frames, steps = {}, [], []
    n = PHYS_CROP[3]
    plain = None
    for i, (title, o) in enumerate(PHYS):
        over = dict(over, **o)
        ct = _phys_crop(over)
        if plain is None:
            plain = ct
        label = title if i == 0 else f"+ {title.lower()}"
        steps.append(label)
        f = Image.new("RGB", (n * scale + 20, n * scale + 44), BG)
        f.paste(_gray_panel(np, ct, scale), (10, 34))
        ImageDraw.Draw(f).text((12, 8), f"{i + 1}/{len(PHYS)}  {label}", font=font, fill=FG)
        frames.append(f)
    size = _gif_save(frames, out, 1100)
    return size, {"frames": len(frames), "frame_ms": 1100, "steps": steps, "crop_z_y0_x0_edge": list(PHYS_CROP)}


def _slice_truth(d, z):
    from kit import scrollsim2 as s2
    doc = json.loads((d / "truth.json").read_text())
    sc = s2.Scroll2(doc["params"] if "params" in doc else dict(MEDIUM))
    return sc, sc.truth_block(z, z + 1, 0, sc.Y, 0, sc.X, kinds=("contact", "uvw"))


def _contact_rgb(np, ct, contact, alpha=0.7):
    from matplotlib.colors import to_rgb
    g = (ct.astype(np.float32) / 255.0)[..., None].repeat(3, -1)
    apart, pressed = np.array(to_rgb(WIND[0]), np.float32), np.array(to_rgb(WIND[1]), np.float32)
    col = np.where((contact == 2)[..., None], pressed, apart)
    return np.where((contact > 0)[..., None], (1 - alpha) * g + alpha * col, g)


TRUTH_CROP = (240, 200, 176)             # y0, x0, edge of the medium scroll's middle slice: inner windings


def fig_truth(plt, np, d, out):
    """The optional truth layers on a crop of one slice: contact (apart or pressed), u (arc length along the sheet)
    and w (offset across the sheet, recto side positive)."""
    from mpl_toolkits.axes_grid1 import make_axes_locatable
    ct, _, doc = load(d)
    z = ct.shape[0] // 2
    y0, x0, n = TRUTH_CROP
    win = (slice(y0, y0 + n), slice(x0, x0 + n))
    _, tr = _slice_truth(d, z)
    contact, u, w = tr["contact"][0][win], tr["u"][0][win], tr["w"][0][win]
    g = ct[z][win]
    fig, axs = plt.subplots(1, 4, figsize=(19.2, 5.6))
    bg = np.full(g.shape + (3,), 0.16, np.float32)
    lim = float(np.nanmax(np.abs(w)))
    panels = [("Synthetic CT", lambda ax: ax.imshow(g, cmap="gray", vmin=0, vmax=255, interpolation="nearest"), None),
              ("contact: apart (blue), pressed (orange)",
               lambda ax: ax.imshow(_contact_rgb(np, g, contact), interpolation="nearest"), None),
              ("u: arc length along the sheet",
               lambda ax: ax.imshow(np.ma.masked_invalid(u), cmap="cividis", interpolation="nearest"), "voxels"),
              ("w: offset across the sheet",
               lambda ax: ax.imshow(np.ma.masked_invalid(w), cmap="PuOr", vmin=-lim, vmax=lim,
                                    interpolation="nearest"), "voxels, recto side positive")]
    for ax, (title, draw, unit) in zip(axs, panels):
        if unit:
            ax.imshow(bg, interpolation="nearest")
        im = draw(ax)
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
        cax = make_axes_locatable(ax).append_axes("right", size="5%", pad=0.08)
        if unit:
            fig.colorbar(im, cax=cax, label=unit)
        else:
            cax.axis("off")
    fig.suptitle(f"ScrollSim v2 truth layers (make --truth contact,uvw), a {n} x {n} voxel crop of slice z = {z}; "
                 "v is the rolled height", fontsize=14, color=MUTED, y=0.04)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    size = save(fig, out, 100)
    plt.close(fig)
    pressed = float((tr["contact"][0] == 2).sum()) / max(1, int((tr["contact"][0] > 0).sum()))
    return size, {"z": z, "crop_y0_x0_edge": list(TRUTH_CROP), "pressed_share_of_sheet_on_slice": round(pressed, 3)}


PRESS_EDGE = 112


def _pressed_window(np, contact, n=PRESS_EDGE):
    """(y0, x0) of the n x n window with the most pressed sheet voxels."""
    from scipy import ndimage
    m = ndimage.uniform_filter((contact == 2).astype(np.float32), n, mode="constant")
    h = n // 2
    m[:h], m[-h:], m[:, :h], m[:, -h:] = 0, 0, 0, 0
    y, x = np.unravel_index(int(np.argmax(m)), m.shape)
    return int(y - h), int(x - h)


def fig_pressed(plt, np, d, out):
    """Where windings press together: the CT gap closes, while the exact labels still tell the windings apart."""
    from matplotlib.patches import Rectangle
    ct, lab, _ = load(d)
    z = ct.shape[0] // 2
    _, tr = _slice_truth(d, z)
    contact = tr["contact"][0]
    y0, x0 = _pressed_window(np, contact)
    n = PRESS_EDGE
    win = (slice(y0, y0 + n), slice(x0, x0 + n))
    fig, axs = plt.subplots(1, 4, figsize=(19.2, 5.5))
    axs[0].imshow(ct[z], cmap="gray", vmin=0, vmax=255, interpolation="nearest")
    axs[0].add_patch(Rectangle((x0 - 0.5, y0 - 0.5), n, n, fill=False, ec=WIND[1], lw=2.5))
    axs[0].set_title(f"Slice z = {z}, the box zoomed")
    axs[1].imshow(ct[z][win], cmap="gray", vmin=0, vmax=255, interpolation="nearest")
    axs[1].set_title("CT: gaps close where windings press")
    axs[2].imshow(overlay(np, ct[z][win], lab[z][win], alpha=0.7), interpolation="nearest")
    axs[2].set_title("Exact winding labels")
    axs[3].imshow(_contact_rgb(np, ct[z][win], contact[win]), interpolation="nearest")
    axs[3].set_title("contact: apart (blue), pressed (orange)")
    for ax in axs:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(f"ScrollSim v2 contact zones: the {n} x {n} voxel box with the most pressed sheet on this slice "
                 "(contact_share 0.45, the default)", fontsize=14, color=MUTED, y=0.04)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    size = save(fig, out, 100)
    plt.close(fig)
    return size, {"z": z, "box_y0_x0_edge": [y0, x0, n]}


def gif_pressed(np, d, out, scale=2):
    """A pass through z of the pressed box: CT, labels and contact side by side."""
    from PIL import Image, ImageDraw
    ct, lab, _ = load(d)
    z = ct.shape[0] // 2
    sc, tr = _slice_truth(d, z)
    y0, x0 = _pressed_window(np, tr["contact"][0])
    n = PRESS_EDGE
    con = sc.truth_block(0, ct.shape[0], y0, y0 + n, x0, x0 + n, kinds=("contact",))["contact"]
    font = _font(16)
    p = n * scale
    frames = []
    for k in range(0, ct.shape[0], 4):
        a = ct[k, y0:y0 + n, x0:x0 + n]
        panels = [_gray_panel(np, a, scale),
                  Image.fromarray((overlay(np, a, lab[k, y0:y0 + n, x0:x0 + n], 0.7) * 255).astype(np.uint8)),
                  Image.fromarray((_contact_rgb(np, a, con[k]) * 255).astype(np.uint8))]
        f = Image.new("RGB", (3 * p + 40, p + 44), BG)
        dr = ImageDraw.Draw(f)
        for i, (im, t) in enumerate(zip(panels, (f"CT, z = {k}", "Winding labels", "Pressed (orange)"))):
            f.paste(im.resize((p, p), Image.NEAREST), (10 + i * (p + 10), 34))
            dr.text((12 + i * (p + 10), 8), t, font=font, fill=FG)
        frames.append(f)
    size = _gif_save(frames, out, 200, colors=64)
    return size, {"frames": len(frames), "z_step": 4, "frame_ms": 200, "box_y0_x0_edge": [y0, x0, n]}


# The ink scroll: Parker et al. 2019 sizes at 8 um voxels (a 5 um deposit, 8 um absorbed), small letters so a short
# box holds three lines. Demo values, not a calibration.
INK_SCROLL = {"shape": [128, 512, 512], "seed": 5, "ink_um": 5.0, "ink_depth_um": 8.0, "ink_rho": 0.3,
              "ink_tex": 0.5, "ink_letter": 26.0, "ink_line": 38.0, "ink_margin": 8.0, "ink_col": 420.0,
              "ink_gap": 60.0}
INK_S = (0.42, 1100)                     # start of the shown stretch as a share of the sheet length, and its length


def make_ink_runs(work):
    from kit import scrollsim2 as s2
    out = {}
    for name, over in (("ink", INK_SCROLL), ("noink", s2.noink(INK_SCROLL))):
        d = Path(work) / name
        if not (d / "truth.json").is_file():
            s2.make(d, over, None, workers=s2.default_workers(), block=128, chunk=64, levels=1, progress=None)
        out[name] = d
    return out


def _ct(np, d):
    import zarr
    return np.asarray(zarr.open_group(str(d / "ct.zarr"), mode="r")["0"][:])


def _layer(np, sc, vols, s, d):
    """Each volume in VOLS sampled on the sheet's recto face moved by D voxels along the rolled radius (negative into
    the gap on the recto side, positive into the sheet), on the grid z x S. Also the vertex mask."""
    from scipy import ndimage
    zs = np.arange(0.0, sc.Z, 1.0)
    th = sc.theta_of_s(s)
    TH, ZZ = np.meshgrid(th, zs)
    r = sc.R_at(TH, ZZ) + sc.face_offset(TH, ZZ) + d
    rolled = np.stack([sc.center[0] + r * np.cos(TH), sc.center[1] + r * np.sin(TH), ZZ], -1).reshape(-1, 3)
    o, _ = sc.forward(rolled)
    coords = np.stack([o[:, 2], o[:, 1], o[:, 0]])
    lim = np.array([sc.Z - 1, sc.Y - 1, sc.X - 1], np.float64)[:, None]
    ok = (np.isfinite(coords).all(0) & (coords >= 0).all(0) & (coords <= lim).all(0)).reshape(TH.shape)
    c = np.where(np.isfinite(coords), coords, 0)
    return [ndimage.map_coordinates(v.astype(np.float32), c, order=1, mode="nearest").reshape(TH.shape)
            for v in vols], ok


def _ink_setup(np, work):
    from kit import scrollsim2 as s2
    runs = make_ink_runs(work)
    sc = s2.Scroll2(INK_SCROLL)
    sc.prepare()
    s0 = float(sc.s[0]) + INK_S[0] * (float(sc.s_end) - float(sc.s[0]))
    s = np.arange(s0, s0 + INK_S[1], 1.0)
    return sc, _ct(np, runs["ink"]), _ct(np, runs["noink"]), s


def fig_ink(plt, np, work, out):
    """The ink writer on a stretch of the recto face: the page truth, the CT there with ink and in the noink twin,
    and their difference."""
    from mpl_toolkits.axes_grid1 import make_axes_locatable
    sc, a, b, s = _ink_setup(np, work)
    TH, ZZ = np.meshgrid(sc.theta_of_s(s), np.arange(0.0, sc.Z, 1.0))
    page = sc.ink_cover(s[None, :].repeat(len(ZZ), 0).ravel(), ZZ.ravel()).reshape(ZZ.shape)
    best, layers = None, {}
    for dd in (-1.0, -0.5, 0.0, 0.5, 1.0, 1.5):
        (la, lb), ok = _layer(np, sc, (a, b), s, dd)
        layers[dd] = (la, lb, ok)
        e = float(np.abs(la - lb)[ok].mean())
        if best is None or e > best[1]:
            best = (dd, e)
    la, lb, ok = layers[best[0]]
    rows = ok.mean(1) > 0.9                     # drop the slices at the box edge where the face leaves the volume
    page, la, lb, ok = page[rows], la[rows], lb[rows], ok[rows]
    diff = np.where(ok, la - lb, np.nan)
    fig, axs = plt.subplots(4, 1, figsize=(19.2, 10.6))
    axs[0].imshow(page, cmap="Greys", vmin=0, vmax=1, interpolation="nearest", aspect="equal")
    axs[0].set_title("Ink truth on the page (sheet coordinates): random Greek capitals, not text")
    axs[1].imshow(np.where(ok, la, 0), cmap="gray", vmin=0, vmax=255, interpolation="nearest")
    moved = f", moved {best[0]:+g} voxels" if best[0] else ""
    axs[1].set_title(f"CT sampled on the recto face{moved}, with ink")
    axs[2].imshow(np.where(ok, lb, 0), cmap="gray", vmin=0, vmax=255, interpolation="nearest")
    axs[2].set_title("The same place in the noink twin (make --noink)")
    lim = float(np.nanpercentile(np.abs(diff), 99.5)) or 1.0
    im = axs[3].imshow(np.ma.masked_invalid(diff), cmap="PuOr_r", vmin=-lim, vmax=lim, interpolation="nearest")
    axs[3].set_title("With ink minus noink: the paired ink effect in gray levels (faint letters where the page is blank are "
                     "the next winding in, a few voxels away)")
    for i, ax in enumerate(axs):
        ax.set_xticks([])
        ax.set_yticks([])
        cax = make_axes_locatable(ax).append_axes("right", size="1%", pad=0.08)
        if i == 3:
            fig.colorbar(im, cax=cax)
        else:
            cax.axis("off")
    fig.suptitle(f"ScrollSim v2 ink writer: {INK_S[1]} voxels along the sheet x {int(rows.sum())} slices; "
                 f"{INK_SCROLL['ink_um']:g} um deposit, {INK_SCROLL['ink_depth_um']:g} um absorbed, 8 um voxels. "
                 "Synthetic truth, not a reading", fontsize=14, color=MUTED, y=0.02)
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    size = save(fig, out, 100)
    plt.close(fig)
    return size, {"ink_scroll": INK_SCROLL, "s_range": [float(s[0]), float(s[-1])], "face_shift": best[0],
                  "mean_abs_diff": round(best[1], 3), "diff_lim": round(lim, 2)}


def gif_ink_layers(np, work, out, scale=2):
    """Layers through the sheet at the recto face: the CT with ink above its difference from the noink twin. The
    effect lives within a voxel or two of the face."""
    from PIL import Image, ImageDraw
    from matplotlib import colormaps
    sc, a, b, s = _ink_setup(np, work)
    s = s[740:1040]                             # a dense stretch of the shown page
    font = _font(16)
    cmap = colormaps["PuOr_r"]
    shifts = [round(x, 2) for x in np.arange(-3.0, 4.01, 1.0)]
    stack = [_layer(np, sc, (a, b), s, dd) for dd in shifts]
    lim = max(float(np.nanpercentile(np.abs((la - lb)[ok]), 99.5)) for (la, lb), ok in stack) or 1.0
    rows = stack[0][1].mean(1) > 0.9
    stack = [((la[rows], lb[rows]), ok[rows]) for (la, lb), ok in stack]
    W, H = len(s) * scale, int(rows.sum()) * scale
    frames = []
    for dd, ((la, lb), ok) in zip(shifts + shifts[-2:0:-1], stack + stack[-2:0:-1]):
        f = Image.new("RGB", (W + 20, 2 * (H + 30) + 36), BG)
        dr = ImageDraw.Draw(f)
        dr.text((12, 8), f"Layer {dd:+.1f} voxels from the recto face (negative: gap side)", font=font, fill=FG)
        c = np.clip((la - lb) / lim * 0.5 + 0.5, 0, 1)
        rgb = (cmap(np.where(ok, c, 0.5))[..., :3] * 255).astype(np.uint8)
        ims = [_gray_panel(np, np.clip(np.where(ok, la, 0), 0, 255).astype(np.uint8), scale),
               Image.fromarray(rgb).resize((W, H), Image.NEAREST)]
        for i, (im, t) in enumerate(zip(ims, ("CT with ink", "With ink minus the noink twin"))):
            y = 36 + i * (H + 30)
            dr.text((12, y), t, font=font, fill=MUTED)
            f.paste(im, (10, y + 22))
        frames.append(f)
    size = _gif_save(frames, out, 450, colors=96)
    return size, {"frames": len(frames), "frame_ms": 450, "shifts": shifts, "s_range": [float(s[0]), float(s[-1])],
                  "diff_lim": round(lim, 2)}


def gif_orbit(plt, np, d, out, n=28, swing=50.0):
    """The center surface with one quarter cut away, swung SWING degrees each way about the view of the still."""
    import tifffile
    from PIL import Image
    from matplotlib.colors import to_rgb
    s = d / "truth" / "surfaces" / "spiral-center"
    P = np.stack([tifffile.imread(s / f"{c}.tif") for c in "xyz"], -1)
    w = np.load(s / "winding.npy")
    k = 4
    P, w = P[::k, ::k], w[::k, ::k]
    ok = (P >= 0).all(-1) & np.isfinite(w)
    cx, cy = np.median(P[ok][:, 0]), np.median(P[ok][:, 1])
    ok &= ~((P[..., 0] > cx) & (P[..., 1] < cy))
    pal = np.array([to_rgb(c) for c in WIND])
    col = pal[(np.where(ok, w, 1).astype(np.int64) - 1) % len(WIND)]
    col = np.concatenate([col, np.where(ok, 1.0, 0.0)[..., None]], -1)
    X, Y, Z = (np.where(ok, P[..., i], np.nan) for i in range(3))
    frames = []
    tmp = Path(str(out) + ".frame.png")
    for i in range(n):
        fig = plt.figure(figsize=(6.4, 4.6))
        ax = fig.add_subplot(projection="3d")
        ax.set_facecolor(BG)
        ax.plot_surface(X, Y, Z, facecolors=col, rstride=1, cstride=1, linewidth=0, antialiased=False, shade=True)
        ax.set_box_aspect((1, 1, 0.42), zoom=1.45)
        ax.view_init(elev=30, azim=-58 + swing * np.sin(2 * np.pi * i / n))
        ax.set_axis_off()
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        fig.savefig(tmp, dpi=100)
        plt.close(fig)
        with Image.open(tmp) as im:
            frames.append(im.convert("RGB").copy())
    tmp.unlink()
    size = _gif_save(frames, out, 110, colors=64)
    return size, {"frames": n, "frame_ms": 110, "vertex_stride": k, "swing_deg": swing}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True, help="scratch folder for the two synthetic scrolls (reused if present)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="+", help="draw only these files (names as listed above)")
    a = ap.parse_args(argv)
    import numpy as np
    plt = _style()
    standalone = {"scrollsim2-scan.png", "scrollsim2-physics.png", "scrollsim2-physics-steps.gif", "scrollsim2-ink.png",
                  "scrollsim2-ink-layers.gif"}
    runs = make_runs(a.work) if not a.only or set(a.only) - standalone else {}
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
        ("scrollsim2-scan.png", lambda p: fig_scan(plt, np, p),
         "Four panels: the same synthetic crop of papyrus windings three times, first plain, then with synchrotron "
         "settings (sharper sheet edges with a bright rim, fine grainy noise and faint rings), then with lab settings "
         "(softer, blotchier noise, stronger rings and slightly darker sheets toward the middle of the roll); the "
         "fourth panel is a line chart of each version's noise power against frequency on a log scale.",
         "Synthetic demo: one ScrollSim v2 crop under no scan model, --scan synchrotron and --scan lab, with each "
         "noise power spectrum. No scan data."),
        ("scrollsim2-physics.png", lambda p: fig_physics(plt, np, p),
         "Eight gray synthetic CT crops of the same papyrus windings in a two by four grid: the plain sheet, then with "
         "waviness, glued joins where the sheet doubles in thickness, bright debris and strands in the gaps, short "
         "cracks, small dark bubbles inside the sheet, uneven ply density, and all of them together.",
         "Synthetic demo: ScrollSim v2 sheet physics, each effect alone and all together, on one crop. Demo settings, "
         "not measurements. No scan data."),
        ("scrollsim2-physics-steps.gif", lambda p: gif_physics(np, p),
         "Animation of one gray synthetic CT crop as sheet physics effects are switched on one at a time: waviness, "
         "glued joins, gap debris, cracks, bubbles and ply density variation.",
         "Synthetic demo: ScrollSim v2 sheet physics switched on one at a time on one crop. No scan data."),
        ("scrollsim2-truth.png", lambda p: fig_truth(plt, np, runs["medium"], p),
         "Four panels of one synthetic slice: gray CT; the sheet tinted blue where windings lie apart and orange "
         "where they press together; the sheet colored by arc length from the inner end, dark at the center and "
         "yellow outside; and the sheet colored by signed offset across its thickness, purple on one face and "
         "orange on the other.",
         "Synthetic demo: ScrollSim v2 truth layers contact, u and w on one slice. No scan data."),
        ("scrollsim2-pressed.png", lambda p: fig_pressed(plt, np, runs["medium"], p),
         "Four panels: a synthetic slice with a box drawn on it, then that box zoomed three ways: gray CT where "
         "neighboring windings touch with no visible gap, the same box tinted by exact winding number, and tinted "
         "orange where windings press together and blue where they lie apart.",
         "Synthetic demo: a ScrollSim v2 contact zone, CT beside exact labels and contact truth. No scan data."),
        ("scrollsim2-pressed-z.gif", lambda p: gif_pressed(np, runs["medium"], p),
         "Animation through z of a zoomed synthetic box where windings press together: gray CT, the same box tinted "
         "by winding number, and tinted by contact, side by side; pressed zones open and close as the slices pass.",
         "Synthetic demo: a pass through z of a ScrollSim v2 contact zone, CT beside labels and contact truth. "
         "No scan data."),
        ("scrollsim2-ink.png", lambda p: fig_ink(plt, np, Path(a.work), p),
         "Four long strips of the same stretch of a synthetic sheet, flattened: black random Greek capitals on white "
         "as the ink truth; gray CT on the sheet's face with ink, where the letters are faint; the same place in "
         "the twin rendered without ink; and the difference of the two, where the letters stand out in orange.",
         "Synthetic demo: the ScrollSim v2 ink writer on a flattened stretch of the recto face, with its noink twin "
         "and their difference. Random letters, not text; not a reading. No scan data."),
        ("scrollsim2-ink-layers.gif", lambda p: gif_ink_layers(np, Path(a.work), p),
         "Animation of three stacked strips of a flattened synthetic sheet, stepping through layers from the gap "
         "beside the inked face into the sheet: CT with ink, the noink twin, and their difference, where random "
         "letters appear only in the layers nearest the face.",
         "Synthetic demo: layers through a ScrollSim v2 sheet at its inked face, ink beside the noink twin and their "
         "difference. Random letters, not text; not a reading. No scan data."),
        ("scrollsim2-orbit.gif", lambda p: gif_orbit(plt, np, runs["medium"], p),
         "Animation of a synthetic sheet's center surface turning once: a crushed spiral wall about 21 windings "
         "deep with one quarter cut away, each winding in one of six repeating colors.",
         "Synthetic demo: the ScrollSim v2 center surface turning once, colored by winding number. No scan data."),
    ]
    if a.only:
        unknown = set(a.only) - {j[0] for j in jobs}
        if unknown:
            ap.error(f"unknown --only name(s): {', '.join(sorted(unknown))}")
        jobs = [j for j in jobs if j[0] in a.only]
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
