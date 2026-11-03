"""Chart of the preregistered real drift test of 3 November 2026: kit labelsnap (labeled
snap_labels in the chart) against A.Q. Snyder's scroll-label-snap (https://github.com/aqsnyder/scroll-label-snap,
MIT, pinned at 347ea5b4f3f7e346197034b7df599a4709aa0bbe) on public PHerc0139, plus a self-consistency panel from the
earlier planted-shift development sites. Numbers are copied from the scored runs; Model output, geometry only.

python scripts/experiments/lsnap-realdrift/chart.py [OUT_DIR]   (default: the current folder)
Writes labelsnap-realdrift-dark.png and labelsnap-realdrift-light.png.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

# Real drift test, preregistered and scored once, HF Job 6aea627fc78863f9c6320c59,
# score.json sha256 9b31743c...f9f5c0. 43 sites drawn; 173 of 387 vertices covered (28 sites,
# 22 cells); 95% cell-cluster bootstrap intervals.
LS = "scroll-label-snap"
W1 = [  # name, value, lo, hi, group
    ("published labels", 0.173, 0.105, 0.257, "base"),
    (f"{LS}, defaults", 0.179, 0.093, 0.257, "aqs"),
    ("m7 snap", 0.214, 0.132, 0.317, "base"),
    (f"{LS}, --target-offset 0", 0.353, 0.252, 0.463, "aqs"),
    (f"{LS}, author's settings", 0.393, 0.268, 0.518, "aqs"),
    (f"{LS}, --target-offset 0, template_weight 0", 0.434, 0.310, 0.560, "aqs"),
    ("snap_labels (mine)", 0.798, 0.732, 0.859, "mine"),
]
SIGNED = [  # median signed distance, voxels, + = inside the sheet
    ("published labels", 3.21, 2.05, 4.78, "base"),
    (f"{LS}, defaults", 2.69, 2.16, 3.16, "aqs"),
    ("m7 snap", 1.89, 0.88, 3.19, "base"),
    (f"{LS}, --target-offset 0", 1.34, 1.01, 2.59, "aqs"),
    (f"{LS}, author's settings", 1.19, 0.93, 2.21, "aqs"),
    (f"{LS}, --target-offset 0, template_weight 0", 0.91, 0.35, 2.32, "aqs"),
    ("snap_labels (mine)", 0.02, -0.12, 0.08, "mine"),
]
# Planted +/-3 voxel shift on the earlier 108 development sites (972 vertices), from
# the earlier planted-shift development test (scored once): share returned within 1 voxel of the tool's own
# unshifted placement (self-consistency). Author's settings were not run there.
PLANT = [
    (f"{LS}, defaults", 0.079, 0.061, "aqs"),
    (f"{LS}, --target-offset 0", 0.202, 0.303, "aqs"),
    (f"{LS}, --target-offset 0, template_weight 0", 0.493, 0.717, "aqs"),
    ("snap_labels (mine)", 0.694, 0.563, "mine"),
    ("m7 snap (snaps to a fixed prediction)", 0.872, 0.867, "base"),
]


def make(mode, out):
    if mode == "dark":
        S, T1, T2, GRID = "#1a1a19", "#f0efec", "#d4d3ca", "#3a3a37"
        COL = {"mine": "#3987e5", "aqs": "#d95926", "base": "#7a7975"}
    else:
        S, T1, T2, GRID = "#fcfcfb", "#0b0b0b", "#3f3e3b", "#e4e3df"
        COL = {"mine": "#2a78d6", "aqs": "#eb6834", "base": "#a3a29d"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, axes = plt.subplots(3, 1, figsize=(12.5, 16.5), dpi=150,
                             gridspec_kw={"height_ratios": [7, 7, 5], "hspace": 0.62})
    fig.patch.set_facecolor(S)

    def style(ax, title, sub, xlim, ticks, labels):
        ax.set_facecolor(S)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_xlim(*xlim)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, color=T2)
        ax.tick_params(axis="x", length=0, colors=T2)
        ax.tick_params(axis="y", length=0, colors=T1)
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_title(title, loc="left", color=T1, fontsize=13, fontweight="bold", pad=44)
        ax.text(0, 1.02, sub, transform=ax.transAxes, color=T2, fontsize=10, va="bottom")

    def bar(ax, y, x0, v, c, h, aspect):
        left, width = (x0, v - x0) if v >= x0 else (v, x0 - v)
        ax.add_patch(FancyBboxPatch((left, y - h / 2), width, h,
                                    boxstyle="round,pad=0,rounding_size=0.01",
                                    linewidth=0, facecolor=c, mutation_aspect=aspect))

    def whisker(ax, y, lo, hi):
        ax.plot([lo, hi], [y, y], color=T1, linewidth=1.4, solid_capstyle="butt")
        for x in (lo, hi):
            ax.plot([x, x], [y - 0.13, y + 0.13], color=T1, linewidth=1.4)

    def ylabels(ax, rows, key):
        ax.set_ylim(-0.6, len(rows) - 0.4)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows])
        for lbl, r in zip(ax.get_yticklabels(), rows):
            if r[key] == "mine":
                lbl.set_fontweight("bold")

    ax = axes[0]
    style(ax, "Real drift test: label within 1 voxel of the two-scan recto face",
          "43 fresh PHerc0139 sites drawn; scored on the 173 of 387 vertices (28 sites) where both reference\n"
          "scans find the face. Preregistered, scored once. Whiskers: 95% intervals.  Higher is better →",
          (0, 1), [0, 0.25, 0.5, 0.75, 1.0], ["0", "0.25", "0.5", "0.75", "1"])
    for i, (n, v, lo, hi, g) in enumerate(W1):
        bar(ax, i, 0, v, COL[g], 0.62, 1 / 60)
        whisker(ax, i, lo, hi)
        ax.text(hi + 0.015, i, f"{v:.3f}", va="center", color=T1, fontsize=10.5)
    ylabels(ax, W1, 4)

    ax = axes[1]
    style(ax, "How far inside the sheet the label sits",
          "Median signed distance from the two-scan face in voxels (+ = inside the papyrus), same 173\n"
          "vertices. Whiskers: 95% intervals.  Closer to 0 is better",
          (-0.6, 5.3), [0, 1, 2, 3, 4, 5], ["0", "1", "2", "3", "4", "5"])
    ax.axvline(0, color=T2, linewidth=1.2)
    for i, (n, v, lo, hi, g) in enumerate(SIGNED):
        bar(ax, i, 0, v, COL[g], 0.62, 1 / 12)
        whisker(ax, i, lo, hi)
        ax.text(hi + 0.08, i, f"{v:+.2f}", va="center", color=T1, fontsize=10.5)
    ax.text(-0.08, len(SIGNED) - 0.5, "two-scan face", color=T2, fontsize=9, ha="right", va="center")
    ylabels(ax, SIGNED, 4)

    ax = axes[2]
    style(ax, "Self-consistency under a planted shift (earlier sites)",
          "108 spent development sites (972 vertices): each label shifted 3 voxels in (+3) or out (-3); share\n"
          "the tool puts back within 1 voxel of its own unshifted result. Not accuracy. Author's settings not\n"
          "run here.  Higher is better →",
          (0, 1), [0, 0.25, 0.5, 0.75, 1.0], ["0", "0.25", "0.5", "0.75", "1"])
    h = 0.32
    for i, (n, a, b, g) in enumerate(PLANT):
        bar(ax, i + h / 2 + 0.02, 0, a, COL[g], h, 1 / 60)
        bar(ax, i - h / 2 - 0.02, 0, b, COL[g], h, 1 / 60)
        ax.text(a + 0.015, i + h / 2 + 0.02, f"+3 vx  {a:.2f}", va="center", color=T1, fontsize=9.5)
        ax.text(b + 0.015, i - h / 2 - 0.02, f"-3 vx  {b:.2f}", va="center", color=T1, fontsize=9.5)
    ylabels(ax, PLANT, 3)

    fig.text(0.02, 0.008,
             "Preregistered call: snap_labels ahead of all four scroll-label-snap settings (Bonferroni intervals). Controls passed:\n"
             "the 9.4 um label scan's own face hits 0.95, and moving the reference 1.5 voxels drops that to 0.07 and 0.10.\n"
             "Reference face: where ROI2 (2.403 um) and the 2.399 um scan both find the recto face within 1 voxel of each other.\n"
             "Both are about 2.4 um at a similar energy, so they may share a face bias. Both tools read only the 9.4 um label scan.\n"
             "Model output, one scroll (PHerc0139), one band (z 6194 to 7890); 128 of the 173 scored vertices are on winding w038.\n"
             "scroll-label-snap is built for whole segments; here it ran on 13 x 13 vertex crops, which gives its offset estimate\n"
             "and template fewer samples, and its default keeps the mesh's own offset by design. Pinned at 347ea5b4, not tuned here.\n"
             "snap_labels defaults were set on other PHerc0139 sites; it abstains on 19% of scored vertices, scored where its grid puts them.",
             color=T2, fontsize=10)
    fig.legend(handles=[Patch(color=COL["mine"], label="snap_labels (mine)"),
                        Patch(color=COL["aqs"], label="scroll-label-snap (A.Q. Snyder)"),
                        Patch(color=COL["base"], label="baselines")],
               loc="upper left", bbox_to_anchor=(0.40, 0.995), ncol=3, frameon=False,
               labelcolor=T1, fontsize=10, handlelength=1.2)
    fig.subplots_adjust(left=0.40, right=0.95, top=0.91, bottom=0.14)
    fig.savefig(out, facecolor=S)


if __name__ == "__main__":
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    make("dark", out_dir / "labelsnap-realdrift-dark.png")
    make("light", out_dir / "labelsnap-realdrift-light.png")
