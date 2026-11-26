"""Draw figure.svg (and optionally a PNG) for the finite-window axis note from the closed forms.

  python docs/manuscripts/finite-window-axis/figure.py [--png OUT.png]

Needs numpy and matplotlib. Pure mathematics: no data.
"""
import argparse
import math
import os
import sys

import numpy as np


def delta(b, R):
    return np.arctan2(np.sqrt(R) * np.sin(b / 2), 1 + np.sqrt(R) * np.cos(b / 2))


def b_max(R):
    return math.pi / 2 + math.acos(1 - 1 / R) if R > 1 else math.pi


def main(argv=None):
    if sys.stdout.isatty():  # the Scrolls look (AGENTS.md rule 17), when run inside a checkout
        try:
            from kit import termstyle
            termstyle.script()
        except ImportError:
            pass
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--png", help="also write a PNG here (1920 px wide)")
    a = p.parse_args(argv)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 11, "font.family": "DejaVu Sans", "axes.spines.top": False,
                         "axes.spines.right": False, "svg.hashsalt": "finite-window-axis"})
    colors = {1: "#3b6fb6", 2: "#7a5cc4", 4: "#c2477f", 10: "#e07b39", 100: "#b59a1f"}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.8, 5.0))

    for R, c in colors.items():
        bm = b_max(R)
        b = np.linspace(0, bm - 1e-9, 600)
        ax1.plot(np.degrees(b), np.degrees(delta(b, R)), color=c, lw=2.2, label=f"R = {R}")
        if R > 1:
            ax1.plot([math.degrees(bm)], [45], "o", color=c, ms=6)
    ax1.axhline(45, color="#888888", lw=0.8, ls=":")
    ax1.text(4, 46.5, "domain edge: error jumps to 90 deg beyond the dot", color="#555555", fontsize=9)
    ax1.set_xlabel("total turn across the window, b = Omega L (deg)")
    ax1.set_ylabel("exact worst-case axis error (deg)")
    ax1.set_title("Worst-case error of the half-argument estimate", fontsize=12)
    ax1.set_xlim(0, 180)
    ax1.set_ylim(0, 50)
    ax1.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, 0.93))

    D = np.radians(np.linspace(0.5, 44.5, 400))
    for R, c in colors.items():
        bmax = 2 * D + 2 * np.arcsin(np.sin(D) / np.sqrt(R))
        ok = bmax < b_max(R)
        ax2.plot(np.degrees(D[ok]), np.degrees(bmax[ok]), color=c, lw=2.2, label=f"R = {R}")
    ax2.set_xlabel("allowed axis error D (deg)")
    ax2.set_ylabel("largest allowed turn across the window (deg)")
    ax2.set_title("Window-length rule: b = 2D + 2 arcsin(sin D / sqrt R)", fontsize=12)
    ax2.set_xlim(0, 45)
    ax2.set_ylim(0, 180)
    ax2.legend(frameon=False, loc="upper left")
    fig.text(0.5, 0.005, "delta(b, R) = arg(1 + sqrt(R) exp(i b / 2)); weights vary by at most a factor R inside the window. "
             "Mathematics only, no data.", ha="center", fontsize=9, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    here = os.path.dirname(os.path.abspath(__file__))
    fig.savefig(os.path.join(here, "figure.svg"), metadata={"Date": None})
    if a.png:
        fig.savefig(a.png, dpi=150)
    print("wrote figure.svg" + (f" and {a.png}" if a.png else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
