"""Before/after chart for the villa PR that keeps a fresh vc_grow_seg_from_seed trace with
x/y/z limits growing (villa #2104). Reads counts.jsonl from count.py: three runs per build of
seed 3770 3698 4608 on the public PHerc0139 surface prediction, inside the box from #2104,
200-generation budget, villa main 8f5f0d7 with and without the fix.

    python chart.py COUNTS.jsonl OUT_DIR
"""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BEFORE, AFTER = "#eb6834", "#2a78d6"


def main(counts_path, out_dir):
    runs = [json.loads(line) for line in open(counts_path) if line.strip()]
    fig, ax = plt.subplots(figsize=(12, 5.2), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for run in runs:
        color = AFTER if "patched" in run["run"] and "unpatched" not in run["run"] else BEFORE
        # generations.tif numbers placed vertices from 1; max_gen is the generation that
        # found nothing more to place, so the line runs flat to it.
        ys = run["cumulative"] + [run["cumulative"][-1]] * (run["max_gen"] - len(run["cumulative"]) + 1)
        z = 3 if color == BEFORE else 2
        ax.plot(range(len(ys)), ys, color=color, linewidth=2.5, zorder=z)
        ax.plot(len(ys) - 1, ys[-1], "o", color=color, markersize=8, zorder=z)
    ax.text(15, 120, "villa main today: stops at generation 12 or 13 (max_gen)\n(481 to 573 vertices, 0.15 to 0.19 cm²)",
            fontsize=13, color=BEFORE, va="bottom", fontweight="bold")
    ax.text(60, 2180, "with this PR: grows until its fringe is empty\nat generation 58 (2,611 to 2,612 vertices, 0.86 cm²)",
            fontsize=13, color=AFTER, ha="right", va="top", fontweight="bold")
    ax.set_xlim(0, 62)
    ax.set_ylim(0, 2900)
    ax.set_xlabel("generation (200-generation budget)", fontsize=12, color=MUTED)
    ax.set_ylabel("valid vertices placed so far", fontsize=12, color=MUTED)
    ax.tick_params(colors=MUTED, labelsize=11)
    ax.grid(color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    fig.suptitle("PHerc0139, seed 3770 3698 4608, inside the x/y/z limits from #2104: three runs per build",
                 x=0.02, ha="left", fontsize=16, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(f"{out_dir}/bound-stall-growth.png", facecolor=SURFACE)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ".")
