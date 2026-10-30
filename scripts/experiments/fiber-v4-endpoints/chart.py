"""Before/after chart for the villa PR that makes load_fibers read kollesis_termination
end tags from version 4 fiber files. Counts come from count.py on the public PHerc0139
annotator fibers (https://dl.ash2txt.org/other/annotators/0139_fibers/, 620 files) with
villa main 8f5f0d7 and with the one-line fix.

    python chart.py OUT_DIR
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# known ends returned by load_fibers, by file version: (version 3, version 4)
BEFORE = (4, 0)
AFTER = (4, 74)
TAGGED = 78  # kollesis_termination tags on end control points in the files

INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
V3, V4 = "#eb6834", "#2a78d6"


def main(out_dir):
    fig, ax = plt.subplots(figsize=(12, 4.6), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    rows = [("With this PR", AFTER), ("villa main today", BEFORE)]
    for y, (name, (v3, v4)) in enumerate(rows):
        ax.barh(y, v3, height=0.5, color=V3, edgecolor=SURFACE, linewidth=2)
        if v4:
            ax.barh(y, v4, left=v3, height=0.5, color=V4, edgecolor=SURFACE, linewidth=2)
        ax.text(v3 + v4 + 1.2, y, f"{v3 + v4} of {TAGGED}", va="center", fontsize=15, color=INK,
                fontweight="bold")
    ax.axvline(TAGGED, color=MUTED, linestyle=(0, (4, 3)), linewidth=1.5)
    ax.text(TAGGED, 1.42, f"{TAGGED} end tags in the files", ha="right", va="bottom", fontsize=12,
            color=MUTED)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=14, color=INK)
    ax.set_xlim(0, 92)
    ax.set_ylim(-0.6, 1.9)
    ax.set_xlabel("kollesis_termination ends that load_fibers returns as known ends", fontsize=12,
                  color=MUTED)
    ax.tick_params(axis="x", colors=MUTED, labelsize=11)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    handles = [plt.Rectangle((0, 0), 1, 1, color=V3), plt.Rectangle((0, 0), 1, 1, color=V4)]
    ax.legend(handles, ["version 3 files (165)", "version 4 files (455)"], loc="upper left",
              bbox_to_anchor=(0.0, 1.02), ncol=2,
              frameon=False, fontsize=12, labelcolor=INK)
    fig.suptitle("PHerc0139 annotator fibers: tagged fiber ends that reach training and scoring",
                 x=0.02, ha="left", fontsize=16, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(f"{out_dir}/fiber-v4-endpoints.png", facecolor=SURFACE)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
