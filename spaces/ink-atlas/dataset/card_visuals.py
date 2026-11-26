"""Two pictures for the dataset card of SharpMeow/first-letters-ink-atlas, drawn from the dataset's own public files.

  python3 spaces/ink-atlas/dataset/card_visuals.py DATASET_DIR --out DIR [--surface ID] [--order forward]

  hero.jpg     one PHerc0343 reference surface, one box: the CT layer, all seven models and the ensemble, each with
               its own 1st to 99.5th percentile stretch inside the box (the maps' own values are in the PNGs)
  anatomy.png  what one surface holds: the 65-layer canvas, the three depth windows, the two depth orders, the files

Needs numpy, Pillow and matplotlib. Reads only the named reference surface and atlas.json.
"""
import argparse
import json
from pathlib import Path

INK, MUTED, GRID, BLUE, ORANGE, BG = "#1d2330", "#5b6475", "#e3e6ec", "#3d6fd1", "#e08a3c", "#ffffff"
LAYERS = [("ct", "CT, middle layer", "public scan, level 0"),
          ("ink_9um-s42", "ink_9um seed 42", "Vesuvius Challenge"),
          ("ink_9um-s43", "ink_9um seed 43", "Vesuvius Challenge"),
          ("reader-v2", "Reader v2", "Domenico Russo"),
          ("reader-v3", "Reader V3", "Domenico Russo"),
          ("dense-native", "dense_native", "Erwin Nieuwlaar"),
          ("d9v2", "d9v2", "TAUIL-Abd-Elilah"),
          ("hecate-9.6", "Hecate 9.6 µm", "Vesuvius Challenge"),
          ("ensemble", "Ensemble", "mean of z-scores")]


def _stretch(a, mask):
    import numpy as np
    v = a[mask]
    lo, hi = np.percentile(v, [1, 99.5]) if v.size else (0, 1)
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)


def hero(root, sid, order, out, box):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image
    atlas = json.loads((root / "atlas.json").read_text())
    s = next(x for x in atlas["surfaces"] if x["id"] == sid)
    d = root / s["path"]
    y0, y1, x0, x1 = box
    ct = np.asarray(Image.open(d / "ct_mid.png").convert("L"), np.float32)[y0:y1, x0:x1]
    mask = ct > 0
    fig, axes = plt.subplots(3, 3, figsize=(12, 13.2), dpi=150, facecolor=BG)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.865, bottom=0.05, wspace=0.04, hspace=0.12)
    for ax, (key, title, by) in zip(axes.flat, LAYERS):
        if key == "ct":
            img, cmap = _stretch(ct, mask), "gray"
        else:
            rel = f"ensemble/{order}.png" if key == "ensemble" else f"maps/{key}/c+0_s1_{order}.png"
            a = np.asarray(Image.open(d / rel).convert("L"), np.float32)[y0:y1, x0:x1]
            img, cmap = _stretch(a, mask), "magma"
        ax.imshow(img, cmap=cmap, vmin=0, vmax=1, interpolation="lanczos")
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color(ORANGE if key == "ensemble" else GRID)
            sp.set_linewidth(2.2 if key == "ensemble" else 1)
        ax.set_title(title, fontsize=13, color=INK, fontweight="bold", loc="left", pad=16)
        ax.text(0, 1.012, by, transform=ax.transAxes, fontsize=9.5, color=MUTED, va="bottom")
    fig.text(0.02, 0.968, "First Letters ink atlas", fontsize=24, fontweight="bold", color=INK)
    fig.text(0.02, 0.942, "Seven public ink models on one shared 9.6 µm canvas, so every map lines up pixel for pixel",
             fontsize=13, color=MUTED)
    side = (x1 - x0) * 9.6 / 1000
    fig.text(0.02, 0.92, f"PHerc0343 reference surface {sid.replace('kbh-', '')}, the same {side:.1f} mm box in "
             f"every panel, {order} depth order, center window", fontsize=11, color=MUTED)
    fig.text(0.02, 0.02, "Model output, not a reading. Each panel is stretched on its own; the PNGs keep each "
             "model's values. Data: Vesuvius Challenge open data (CC BY-NC 4.0); mesh by ketchupbyheinz.",
             fontsize=9.5, color=MUTED)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".png")
    fig.savefig(tmp, facecolor=BG)
    plt.close(fig)
    im = Image.open(tmp).convert("RGB")
    im.thumbnail((1800, 1800), Image.LANCZOS)
    im.save(out, quality=88, optimize=True, progressive=True)
    tmp.unlink()


def anatomy(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, Rectangle
    fig = plt.figure(figsize=(13.5, 6.0), dpi=150, facecolor=BG)
    ax = fig.add_axes([0.03, 0.12, 0.47, 0.74])
    ax.set_xlim(0, 10)
    ax.set_ylim(-36, 36)
    ax.axis("off")
    # the 65 layers of the canvas, center layer 0, 9.6 um apart, the traced surface at 0
    for k in range(-32, 33):
        ax.plot([1.2, 8.8], [k, k], color=GRID if k else INK, linewidth=0.6 if k else 2.2, zorder=1)
    for c, name in ((-4, "c-4"), (0, "c+0"), (4, "c+4")):
        ax.plot([1.2, 8.8], [c, c], color=BLUE, linewidth=2.4 if c == 0 else 1.6, zorder=2,
                linestyle="-" if c == 0 else (0, (4, 2)))
        ax.text(9.0, c * 1.9, name, color=BLUE, fontsize=11, fontweight="bold", va="center")
    ax.text(1.1, 0, "traced\nsurface", color=INK, fontsize=10, ha="right", va="center")
    ax.text(1.1, 31, "layer +32", color=MUTED, fontsize=9, ha="right", va="center")
    ax.text(1.1, -31, "layer -32", color=MUTED, fontsize=9, ha="right", va="center")
    ax.add_patch(FancyArrowPatch((5, -35), (5, -24), arrowstyle="-|>", mutation_scale=16, color=ORANGE, lw=2))
    ax.text(5.25, -31, "forward: the depth order as stored", color=ORANGE, fontsize=10, va="center")
    ax.add_patch(FancyArrowPatch((5, 35), (5, 24), arrowstyle="-|>", mutation_scale=16, color=ORANGE, lw=2))
    ax.text(5.25, 31, "reverse: the same layers flipped,\nthe other face read as the writing side", color=ORANGE, fontsize=10, va="center")
    fig.text(0.03, 0.92, "One surface: a 65-layer canvas, three depth windows, two depth orders", fontsize=15,
             fontweight="bold", color=INK)
    fig.text(0.03, 0.025, "Layers are 9.6 µm apart along each pixel's mesh normal; the middle layer is on the mesh.\nA depth "
             "window is where a model's 3D input is centered: 4 layers to one side, on the mesh, or 4 to the other.", fontsize=9.5, color=MUTED)
    tree = ("surfaces/SCROLL/SURFACE_ID/\n"
            "  meta.json\n"
            "  ct_mid.png\n"
            "  preview.jpg\n"
            "  maps/MODEL/\n"
            "    c-4_s1_forward.png\n"
            "    c-4_s1_reverse.png\n"
            "    c+0_s1_forward.png\n"
            "    c+0_s1_reverse.png\n"
            "    c+4_s1_forward.png\n"
            "    c+4_s1_reverse.png\n"
            "  ensemble/forward.png\n"
            "  ensemble/reverse.png\n"
            "  ensemble-rev/forward.png\n"
            "  ensemble-rev/reverse.png")
    fig.text(0.545, 0.83, tree, family="DejaVu Sans Mono", fontsize=10.5, color=INK, va="top", linespacing=1.45)
    notes = ("7 models; Hecate 9.6 has c+0 only\n\n"
             "maps: 0 to 255 is 0 to 1\n"
             "ensemble: 0 to 255 is z -2 to 4\n\n"
             "ensemble/: z-scores with the\nforward maps' statistics\n"
             "ensemble-rev/: with the\nreverse maps' statistics")
    fig.text(0.79, 0.83, notes, fontsize=10, color=MUTED, va="top", linespacing=1.45)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BG)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", help="local copy of the dataset (atlas.json and the reference surface's files)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--surface", default="kbh-PHerc0343_4937_3336_11593")
    ap.add_argument("--order", default="forward", choices=("forward", "reverse"))
    ap.add_argument("--box", default="120,1144,260,1284", help="y0,y1,x0,x1 in canvas pixels")
    a = ap.parse_args(argv)
    root, out = Path(a.root), Path(a.out)
    hero(root, a.surface, a.order, out / "hero.jpg", [int(v) for v in a.box.split(",")])
    anatomy(out / "anatomy.png")


if __name__ == "__main__":
    main()
