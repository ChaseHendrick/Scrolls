"""Concept GIF (synthetic data only) of how ladders.py turns Ringleader's labels into villa relative windings.

    python3 scripts/experiments/ringleader-ladders/concept_gif.py [--out docs/assets/ringleader/ladders-concept.gif]

A drawn spiral, not scan data: five slow frames (sheets; Ringleader's winding labels with a few wrong pieces; the
pieces near a broken edge dropped; up to K points per sure piece; the points as one relative-winding collection).
"""

import argparse
import io
import math
from pathlib import Path

import numpy as np

BG, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#d9d8d3"
W1, W2 = "#2a78d6", "#eb6834"          # alternate windings
BAD = "#6250d6"
CAPTIONS = [
    "1. Sheets in one z-slice (drawn spiral, not scan data)",
    "2. Ringleader labels every piece with its winding; three pieces got a wrong label",
    "3. Pieces near a broken edge are dropped: only sure pieces stay",
    "4. Up to 8 points per sure piece, numbered by angle from the start ray",
    "5. One relative-winding collection per slice: villa's spiral fit learns the order",
]


def spiral(n_turns=7, per_turn=900, piece=150):
    P = 2.0 + (np.arange(n_turns * per_turn) + 0.5) / per_turn
    T = np.floor(P).astype(int)
    th = 2 * math.pi * (P - T)
    r = 0.9 * P
    pid = np.zeros(len(P), int)
    k, cnt, prev = 0, 0, T[0]
    for i in range(len(P)):
        if T[i] != prev or cnt == piece:
            k, cnt, prev = k + 1, 0, T[i]
        pid[i] = k
        cnt += 1
    return r * np.cos(th), r * np.sin(th), T, pid, th


def frame(i, x, y, T, pid, th, wrong, unsure):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 8.6), dpi=100)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.plot([0, 9.5], [0, 0], color=GRID, lw=1.5, ls=(0, (4, 4)))
    ax.text(9.6, 0.15, "start ray", color=INK2, fontsize=11)
    for q in np.unique(pid):
        m = pid == q
        if i == 0:
            c, lw, a = INK2, 2.5, 1.0
        else:
            bad = q in wrong
            drop = i >= 2 and (bad or q in unsure)
            c = BAD if bad else (W1 if T[m][0] % 2 else W2)
            lw, a = (2.5, 0.18) if drop else (3.5, 1.0)
            if i >= 3 and not drop:
                a = 0.35
        ax.plot(x[m], y[m], color=c, lw=lw, alpha=a, solid_capstyle="round")
        if i >= 3 and not (q in wrong or q in unsure):
            idx = np.flatnonzero(m)
            sel = idx[np.unique(np.rint(np.linspace(0, len(idx) - 1, min(8, len(idx)))).astype(int))]
            ax.scatter(x[sel], y[sel], s=40, color=W1 if T[m][0] % 2 else W2, edgecolor=BG, linewidth=1.2, zorder=3)
    if i >= 1:
        for t in np.unique(T):
            j = np.flatnonzero((T == t) & (np.abs(th - 0.35) < 0.01))
            if len(j):
                ax.text(x[j[0]], y[j[0]] + 0.25, f"{t - T.min()}", color=INK, fontsize=11, ha="center",
                        fontweight="bold")
    if i == 4:
        ax.text(0, -9.9, '{"wind_a": 0, 1, 2, ...   "winding_is_absolute": false}', color=INK, fontsize=12,
                ha="center", family="DejaVu Sans Mono")
    ax.set_xlim(-9.5, 10.8)
    ax.set_ylim(-10.4, 9.0)
    fig.text(0.04, 0.95, CAPTIONS[i], color=INK, fontsize=13.5)
    fig.text(0.04, 0.92, "Ringleader ladders for villa's spiral fit (concept, synthetic)", color=INK2, fontsize=11)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    from PIL import Image
    return Image.open(buf).convert("RGB")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/assets/ringleader/ladders-concept.gif")
    a = ap.parse_args(argv)
    x, y, T, pid, th = spiral()
    wrong = {int(pid[2000]), int(pid[3700]), int(pid[5100])}
    unsure = {q + d for q in wrong for d in (-1, 1)}
    frames = [frame(i, x, y, T, pid, th, wrong, unsure) for i in range(5)]
    pal = [f.quantize(colors=96, method=2) for f in frames]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=[2600, 3200, 3200, 3200, 4200], loop=0,
                optimize=True)
    frames[4].save(out.with_suffix(".png"))
    print(out, out.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
