"""Chart of the frozen ladder test (PHerc0139 z 1,960 to 2,300, read once 4 Nov 2026). Model output: on-winding E0 of
villa's spiral fit with and without Ringleader's ladders, three seeds each, against published hand windings.

    python3 scripts/experiments/ringleader-ladders/chart.py [--out docs/assets/ringleader]

Writes ladders-test-light.png and ladders-test-dark.png (scores only: no CT pixels, mesh or map). The numbers are
copied from the test's readout (its sha256 26c59694...); the colors passed the dataviz palette check in both modes.
"""

import argparse
from pathlib import Path

E0 = {   # per seed 1, 2, 3
    "A": (0.2186, 0.2304, 0.2325),
    "E": (0.3595, 0.3803, 0.3803),
    "G": (0.4150, 0.4142, 0.3974),
    "Q": (0.1027, 0.1046, 0.1123),
}
RL = 0.790          # Ringleader v1 itself on the same pixels (the teacher; information)
DIST = (20, 60, 100, 140, 180, 220, 260, 300, 340)       # bin centers, slices from the nearest evidence slice
BY_DIST = {          # mean over the three seeds
    "A": (0.2857, 0.2632, 0.2423, 0.2230, 0.2259, 0.2224, 0.2083, 0.1998, 0.1893),
    "E": (0.6739, 0.5544, 0.4431, 0.3569, 0.3107, 0.2813, 0.2799, 0.2805, 0.2866),
    "G": (0.7379, 0.6245, 0.4871, 0.3847, 0.3396, 0.3325, 0.3149, 0.2886, 0.2796),
    "Q": (0.0972, 0.0956, 0.1026, 0.1049, 0.1081, 0.1132, 0.1136, 0.1114, 0.1071),
}
NAMES = {"A": "villa spiral fit alone", "E": "+ Ringleader ladders (round 1)", "G": "+ grown ladders (round 2)",
         "Q": "+ plus-one control", "RL": "Ringleader v1 itself"}
THEMES = {
    "light": dict(bg="#fcfcfb", ink="#0b0b0b", ink2="#52514e", grid="#e4e3df",
                  c={"A": "#2a78d6", "E": "#eb6834", "G": "#1baf7a", "Q": "#6250d6", "RL": "#e87ba4"}),
    "dark": dict(bg="#1a1a19", ink="#f0efec", ink2="#c3c2b7", grid="#34332f",
                 c={"A": "#3987e5", "E": "#d95926", "G": "#199e70", "Q": "#9085e9", "RL": "#d55181"}),
}


def draw(theme, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = THEMES[theme]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "text.color": t["ink"],
                         "axes.labelcolor": t["ink2"], "xtick.color": t["ink2"], "ytick.color": t["ink2"]})
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 6.6), dpi=100, gridspec_kw={"width_ratios": [1.05, 1]})
    fig.patch.set_facecolor(t["bg"])
    for ax in (a1, a2):
        ax.set_facecolor(t["bg"])
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(t["grid"])
        ax.grid(True, axis="x" if ax is a1 else "y", color=t["grid"], lw=0.8)
        ax.set_axisbelow(True)
    rows = ["A", "E", "G", "Q", "RL"]
    for y, k in enumerate(rows):
        vals = (RL,) if k == "RL" else E0[k]
        m = sum(vals) / len(vals)
        a1.plot([0, m], [y, y], color=t["c"][k], lw=2, solid_capstyle="round", alpha=0.55)
        a1.scatter(vals, [y] * len(vals), s=90, color=t["c"][k], edgecolor=t["bg"], linewidth=2, zorder=3)
        a1.text(m + 0.025, y, f"{m:.3f}" + ("" if k == "RL" else "  (3 seeds)"), va="center", color=t["ink"],
                fontsize=12)
    a1.set_yticks(range(len(rows)), [NAMES[k] for k in rows], fontsize=12.5)
    a1.tick_params(axis="y", length=0)
    a1.set_xlim(0, 1)
    a1.set_ylim(len(rows) - 0.4, -0.6)
    a1.set_xlabel("on-winding E0 against published hand windings (higher is better)")
    a1.set_title("Frozen test, read once: PHerc0139 z 1,960 to 2,300, 86 slices",
                 loc="left", fontsize=13.5, color=t["ink"], pad=12)
    for k in ("G", "E", "A", "Q"):
        a2.plot(DIST, BY_DIST[k], color=t["c"][k], lw=2, marker="o", ms=8, markeredgecolor=t["bg"],
                markeredgewidth=2, label=NAMES[k])
    a2.set_ylim(0, 0.85)
    a2.set_xlim(0, 360)
    a2.set_xlabel("slices from the nearest ladder slice (z 1,920 to 1,956)")
    a2.set_ylabel("on-winding E0, mean of 3 seeds")
    a2.set_title("By distance: largest near the ladder slices, still ahead past 300",
                 loc="left", fontsize=13.5, color=t["ink"], pad=12)
    lg = a2.legend(loc="upper right", frameon=False, fontsize=11)
    for txt in lg.get_texts():
        txt.set_color(t["ink2"])
    fig.text(0.01, 0.015, "Model output. villa spiral fit e2254ebe, 30,000 steps per fit; Ringleader v1 ladders on 10 "
             "slices below the scored band.\nScore: share of matched sheet pixels on the right winding, one free "
             "offset per slice. Pass rule: G minus A at least +0.10 pooled (got +0.182).", color=t["ink2"], fontsize=10.5)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(out, facecolor=t["bg"])
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/assets/ringleader")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        draw(theme, out / f"ladders-test-{theme}.png")
        print(out / f"ladders-test-{theme}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
