"""Concept GIF (synthetic data only) of why ladders.py 1.2.0 writes one connected component per slice.

    python3 scripts/experiments/ringleader-ladders/components_gif.py [--out docs/assets/ringleader/ladders-components.gif]

A drawn spiral of seven windings, not scan data, in the style of concept_gif.py beside it. The slice's sure pieces fall
into three connected components with no traced sheet between them. Ringleader solves each component with its own free
offset, so labels compare only inside one component. Six slow frames: the components; their labels on three offsets;
1.1.0 writing every component into one collection; a pair across components whose written winding difference is
wrong; 1.2.0 keeping only the component with the most sure pieces; and a 1.1.0 versus 1.2.0 summary, which is also
written as the PNG. With --sidecar (the default) it writes NAME.json beside the GIF in the scrolls-media/1 schema.
"""

import argparse
import hashlib
import io
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]

BG, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#d9d8d3"
UNTRACED = "#b4b2ab"
HILITE = "#fff1bf"
# Component colors, the concept GIF's blue, orange and violet: blue for the large component.
COMP = {1: "#2a78d6", 2: "#eb6834", 3: "#6250d6"}
TRUE_TO_LABEL = {1: 0, 2: -5, 3: -1}   # each component's free offset: label = true winding + offset
DOTS = 4                                # dots per sure piece in the drawing (ladders.py uses up to 8)
DURATIONS = [3000, 3000, 3000, 3000, 3000, 4500]
STEPS = [
    "1. One slice: its sure pieces fall into three connected components",
    "2. Ringleader solves each component with its own free offset",
    "3. Version 1.1.0 wrote every component into one collection",
    "4. So winding differences across components were arbitrary",
    "5. Version 1.2.0 keeps one component per slice",
    "Summary: 1.1.0 versus 1.2.0",
]
SUB = "Ringleader ladders for villa's spiral fit (concept, synthetic: a drawn spiral, not scan data)"


def spiral(n_turns=7, per_turn=900, piece=150):
    """Samples of a drawn spiral: x, y, true winding T, piece number within its turn, angle."""
    P = 2.0 + (np.arange(n_turns * per_turn) + 0.5) / per_turn
    T = np.floor(P).astype(int) - 2
    th = 2 * math.pi * (P - np.floor(P))
    r = 0.9 * P
    k = ((P - np.floor(P)) * per_turn // piece).astype(int)
    return r * np.cos(th), r * np.sin(th), T, k, th


def component_of(t, k):
    """Component of piece k of turn t, 0 where no sheet is traced."""
    if t <= 3:
        return 1
    if t in (5, 6) and k in (0, 1):
        return 2
    if t in (5, 6) and k in (3, 4):
        return 3
    return 0


def pieces(x, y, T, K, th):
    """One record per piece: its turn, piece number, component, label, sample indices and dot indices."""
    out = []
    for t in np.unique(T):
        for k in np.unique(K[T == t]):
            idx = np.flatnonzero((T == t) & (K == k))
            c = component_of(int(t), int(k))
            trim = idx[int(len(idx) * 0.04): len(idx) - int(len(idx) * 0.04)]
            dots = trim[np.rint(np.linspace(0, len(trim) - 1, DOTS)).astype(int)]
            out.append({"t": int(t), "k": int(k), "c": c, "idx": idx, "trim": trim, "dots": dots,
                        "label": int(t) + TRUE_TO_LABEL[c] if c else None})
    return out


def at(x, y, th, T, t, angle):
    j = np.flatnonzero(T == t)
    j = j[np.argmin(np.abs(th[j] - angle))]
    return x[j], y[j]


def draw_slice(ax, x, y, T, th, P, mode, small=False):
    """mode: 'pieces', 'labels', 'all' (1.1.0 dots), 'pair' (1.1.0 dots and the wrong pair), 'main' (1.2.0)."""
    ax.set_facecolor(BG)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.plot([0, 8.9], [0, 0], color=GRID, lw=1.5, ls=(0, (4, 4)), zorder=0)
    ax.text(8.95, 0.2, "start\nray", color=INK2, fontsize=10 if small else 11, va="bottom")
    faded = mode == "main"
    for p in P:
        if not p["c"]:
            ax.plot(x[p["idx"]], y[p["idx"]], color=UNTRACED, lw=1.4, ls=(0, (2, 3)), alpha=0.9, zorder=1)
            continue
        dim = faded and p["c"] != 1
        a = 0.16 if dim else (0.45 if mode in ("all", "pair", "main") else 1.0)
        ax.plot(x[p["trim"]], y[p["trim"]], color=COMP[p["c"]], lw=4 if not small else 3.2, alpha=a,
                solid_capstyle="round", zorder=2)
        if mode in ("all", "pair", "main") and not dim:
            ax.scatter(x[p["dots"]], y[p["dots"]], s=46 if not small else 30, color=COMP[p["c"]], edgecolor=BG,
                       linewidth=1.2, zorder=3)
    # true windings along a ray where only component 1 is traced
    ray = 2.62
    for t in range(7):
        px, py = at(x, y, th, T, t, ray)
        ax.text(px, py, str(t), color=INK2, fontsize=9.5 if small else 11, ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.12", fc=BG, ec="none"), zorder=4)
    tx, ty = at(x, y, th, T, 6, ray)
    ax.text(tx - 0.3, ty + 0.75, "true winding", color=INK2, fontsize=9.5 if small else 11, ha="center",
            style="italic")
    if mode != "pieces":
        spots = [(1, t, 0.33) for t in range(4)] + [(2, t, 0.33) for t in (5, 6)] + [(3, t, 4.2) for t in (5, 6)]
        for c, t, angle in spots:
            if faded and c != 1:
                continue
            px, py = at(x, y, th, T, t, angle)
            ax.text(px, py, str(t + TRUE_TO_LABEL[c]), color="white", fontsize=10 if small else 12,
                    fontweight="bold", ha="center", va="center", zorder=5,
                    bbox=dict(boxstyle="round,pad=0.22", fc=COMP[c], ec=BG, lw=1.2))
    if faded:
        for (t, angle) in ((6, 1.0), (6, 4.0)):
            px, py = at(x, y, th, T, t, angle)
            ax.text(px * 1.12, py * 1.12, "left out", color=INK2, fontsize=10 if small else 12, ha="center",
                    va="center", style="italic", zorder=5)
    if mode == "pair":
        da, db = [next(p["dots"][2] for p in P if p["t"] == t and p["k"] == 1) for t in (3, 5)]
        pa, pb = (x[da], y[da]), (x[db], y[db])
        for q in (pa, pb):
            ax.scatter([q[0]], [q[1]], s=260 if not small else 170, facecolor="none", edgecolor=INK, linewidth=2.4,
                       zorder=6)
        ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color=INK, lw=2.4, ls=(0, (3, 2)), zorder=6)
        ax.annotate("written -3, true +2", xy=(pb[0] + 0.25, pb[1] + 0.35), xytext=(3.4, 8.3),
                    fontsize=11 if small else 13, color=INK, fontweight="bold", ha="center", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.35", fc=HILITE, ec=INK, lw=1.4),
                    arrowprops=dict(arrowstyle="-", color=INK, lw=1.6))
    ax.set_xlim(-8.6, 9.9)
    ax.set_ylim(-8.6, 9.2)


def swatch(fig, x, y, color, text, dashed=False, size=14.5):
    import matplotlib.lines as mlines
    line = mlines.Line2D([x, x + 0.03], [y + 0.008, y + 0.008], transform=fig.transFigure, color=color,
                         lw=1.6 if dashed else 5, ls=(0, (2, 3)) if dashed else "-", solid_capstyle="round")
    fig.add_artist(line)
    fig.text(x + 0.042, y, text, color=INK, fontsize=size, va="baseline")


def panel_text(fig, i):
    """The right-hand panel of frames 1 to 5."""
    x0 = 0.585
    lines = {
        0: [("swatch", 1, "Component 1: 24 sure pieces"), ("swatch", 2, "Component 2: 4 sure pieces"),
            ("swatch", 3, "Component 3: 4 sure pieces"), ("dashed", 0, "sheet not traced: no edge joins them"),
            ("gap",), ("text", "A component is a set of pieces joined by"), ("text", "continuity and radial edges.")],
        1: [("swatch", 1, "Component 1: true 0 to 3, labels 0 to 3"),
            ("swatch", 2, "Component 2: true 5 to 6, labels 0 to 1"),
            ("swatch", 3, "Component 3: true 5 to 6, labels 4 to 5"), ("gap",),
            ("text", "Each component's labels are right inside it,"),
            ("text", "on an offset of its own. Labels compare"), ("text", "only inside one component.")],
        2: [("text", "One collection, one offset:"), ("gap",),
            ("swatch", 1, "wind_a 0 to 3 from component 1"), ("swatch", 2, "wind_a 0 to 1 from component 2"),
            ("swatch", 3, "wind_a 4 to 5 from component 3"), ("gap",),
            ("text", "32 sure pieces written, three offsets mixed.")],
        3: [("text", "The ringed pair, two sheets apart:"), ("gap",),
            ("text", "written: 0 minus 3 = -3 windings"), ("text", "true: +2 windings"), ("gap",),
            ("text", "Every difference written between two"),
            ("text", "components is arbitrary: villa's spiral fit"), ("text", "is taught a wrong order there.")],
        4: [("box", "kept: component with the most sure pieces"), ("gap",),
            ("swatch", 1, "Component 1: 24 sure pieces, wind_a 0 to 3"),
            ("text", "Components 2 and 3: 8 sure pieces left out"), ("text", "and counted in the record."), ("gap",),
            ("text", "A tie goes to the smallest component number."),
            ("text", "grow adds pieces of that component only.")],
    }[i]
    y = 0.70
    for item in lines:
        kind = item[0]
        if kind == "gap":
            y -= 0.035
            continue
        if kind == "swatch":
            swatch(fig, x0, y, COMP[item[1]], item[2])
        elif kind == "dashed":
            swatch(fig, x0, y, UNTRACED, item[2], dashed=True)
        elif kind == "box":
            fig.text(x0, y, item[1], color=INK, fontsize=15, fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.4", fc=HILITE, ec=INK, lw=1.3))
        else:
            fig.text(x0, y, item[1], color=INK, fontsize=14.5)
        y -= 0.046 if kind == "text" else 0.062


def frame(i, x, y, T, th, P):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(14, 8), dpi=100)
    fig.patch.set_facecolor(BG)
    fig.text(0.03, 0.935, STEPS[i], color=INK, fontsize=21)
    fig.text(0.03, 0.895, SUB, color=INK2, fontsize=12.5)
    if i < 5:
        ax = fig.add_axes([0.02, 0.02, 0.53, 0.85])
        draw_slice(ax, x, y, T, th, P, ["pieces", "labels", "all", "pair", "main"][i])
        panel_text(fig, i)
    else:
        for n, (left, mode, title, notes) in enumerate([
                (0.02, "pair", "1.1.0: every component, one offset",
                 ["32 sure pieces written", "differences across components wrong"]),
                (0.51, "main", "1.2.0: one component per slice",
                 ["24 sure pieces written (component 1)", "every difference inside one component"])]):
            ax = fig.add_axes([left, 0.13, 0.47, 0.68])
            draw_slice(ax, x, y, T, th, P, mode, small=True)
            cx = left + 0.235
            fig.text(cx, 0.82, title, color=INK, fontsize=17, fontweight="bold", ha="center")
            fig.text(cx, 0.095, notes[0], color=INK, fontsize=14, ha="center")
            fig.text(cx, 0.06, notes[1], color=COMP[2] if n == 0 else COMP[1], fontsize=14, ha="center",
                     fontweight="bold")
        fig.add_artist(plt.Line2D([0.5, 0.5], [0.06, 0.84], transform=fig.transFigure, color=GRID, lw=1.5))
        fig.text(0.5, 0.015, "--all-components rebuilds the 1.1.0 files, only to reproduce past tests",
                 color=INK2, fontsize=12.5, ha="center")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    from PIL import Image
    return Image.open(buf).convert("RGB")


META = {
    "label": "Synthetic demo",
    "alt": ("Six slow frames on a drawn spiral of seven windings: the sure pieces of one slice in three connected "
            "components (blue, 24 pieces; orange and violet, 4 each) with an untraced sheet between them; each "
            "component's Ringleader labels on its own offset; version 1.1.0 writing all of them into one "
            "relative-winding collection; a ringed pair across components written -3 windings apart where the true "
            "difference is +2; version 1.2.0 keeping only the blue component, the one with the most sure pieces; "
            "and a 1.1.0 versus 1.2.0 summary."),
    "caption": ("Synthetic demo of why scripts/ringleader/ladders.py 1.2.0 writes one connected component per slice. "
                "No scan data; geometry, not a reading."),
    "license": "Apache-2.0",
    "release_id": None,
    "data": None,
    "sources": [],
}


def write_sidecar(gif, png, command):
    sys.path.insert(0, str(ROOT / "scripts" / "media"))
    import common as media
    media.check_meta(META)
    from PIL import Image
    outputs = []
    for p in (gif, png):
        with Image.open(p) as im:
            outputs.append(media.output_record(p, *im.size))
    rec = {"schema": media.SCHEMA, "name": gif.stem, **{k: META[k] for k in ("label", "alt", "caption", "license",
                                                                             "release_id", "data", "sources")},
           "outputs": outputs, "inputs": [], "made": __import__("datetime").date.today().isoformat(),
           "tool": {"scripts": [HERE.relative_to(ROOT).as_posix()],
                    "scripts_sha256": hashlib.sha256(HERE.read_bytes()).hexdigest(),
                    "base_commit": media.git_commit()},
           "command": command}
    problems = media.public_problems(rec)
    if problems:
        raise SystemExit("sidecar: " + "; ".join(problems))
    side = gif.with_suffix(".json")
    side.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return side


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/assets/ringleader/ladders-components.gif")
    ap.add_argument("--no-sidecar", action="store_true", help="skip NAME.json beside the GIF")
    a = ap.parse_args(argv)
    x, y, T, K, th = spiral()
    P = pieces(x, y, T, K, th)
    counts = {c: sum(1 for p in P if p["c"] == c) for c in COMP}
    assert counts == {1: 24, 2: 4, 3: 4}, counts
    frames = [frame(i, x, y, T, th, P) for i in range(len(STEPS))]
    pal = [f.quantize(colors=128, method=2) for f in frames]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=DURATIONS, loop=0, optimize=True)
    png = out.with_suffix(".png")
    frames[-1].save(png, optimize=True)
    print(out, out.stat().st_size)
    print(png, png.stat().st_size)
    if not a.no_sidecar:
        cmd = f"python3 {HERE.relative_to(ROOT).as_posix()} --out {a.out}"
        print(write_sidecar(out, png, cmd))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
