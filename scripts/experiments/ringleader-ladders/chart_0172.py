"""Chart of the second passing frozen ladder test (PHerc0172 scan 20241024131838, z 9,680 to 9,904, read once 6 Nov
2026). Model output: on-winding E0 of villa's spiral fit with and without Ringleader's ladders, three seeds each,
against the organizers' hand-traced windings w052 to w095.

    python3 scripts/experiments/ringleader-ladders/chart_0172.py [--out docs/assets/ringleader]

Writes ladders-test-0172-light.png and ladders-test-0172-dark.png (scores only: no CT pixels, mesh or map). The numbers
are copied from the test's readout (its sha256 7f5e3d9f...); the colors and layout are chart.py's.
"""

import argparse
from pathlib import Path

E0 = {   # per seed 1, 2, 3
    "A": (0.0700, 0.0664, 0.0717),
    "E": (0.2675, 0.2674, 0.2702),
    "G": (0.2935, 0.2928, 0.2781),
    "Q": (0.0379, 0.0377, 0.0355),
}
RL = 0.497          # Ringleader v1 itself on the same pixels (the teacher; information)
DIST = (20, 60, 100, 140, 180, 220)       # bin centers, slices from the nearest evidence slice
BY_DIST = {          # mean over the three seeds
    "A": (0.0613, 0.0626, 0.0643, 0.0804, 0.0788, 0.0773),
    "E": (0.3116, 0.3062, 0.3005, 0.2232, 0.2121, 0.2067),
    "G": (0.3271, 0.3208, 0.3109, 0.2458, 0.2456, 0.2366),
    "Q": (0.0350, 0.0360, 0.0368, 0.0367, 0.0383, 0.0410),
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
    a1.set_title("Frozen test, read once: PHerc0172 z 9,680 to 9,904, 57 slices",
                 loc="left", fontsize=13.5, color=t["ink"], pad=12)
    for k in ("G", "E", "A", "Q"):
        a2.plot(DIST, BY_DIST[k], color=t["c"][k], lw=2, marker="o", ms=8, markeredgecolor=t["bg"],
                markeredgewidth=2, label=NAMES[k])
    a2.set_ylim(0, 0.6)
    a2.set_xlim(0, 240)
    a2.set_xlabel("slices from the nearest ladder slice (z 9,640 to 9,676)")
    a2.set_ylabel("on-winding E0, mean of 3 seeds")
    a2.set_title("By distance: largest near the ladder slices, still ahead at 200",
                 loc="left", fontsize=13.5, color=t["ink"], pad=12)
    lg = a2.legend(loc="upper right", frameon=False, fontsize=11)
    for txt in lg.get_texts():
        txt.set_color(t["ink2"])
    fig.text(0.01, 0.015, "Model output. villa spiral fit e2254ebe, 30,000 steps per fit; Ringleader v1 ladders on 10 "
             "slices below the scored band.\nScore: share of matched sheet pixels on the right winding, one free "
             "offset per slice. Pass rule: G minus A at least +0.10 pooled (got +0.219).", color=t["ink2"], fontsize=10.5)
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
        draw(theme, out / f"ladders-test-0172-{theme}.png")
        print(out / f"ladders-test-0172-{theme}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
