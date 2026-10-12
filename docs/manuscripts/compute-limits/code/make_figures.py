"""Draw the three figures of the paper from the files in data/.

Usage, from the folder above code/:  python3 code/make_figures.py
Writes paper/figures/*.pdf. Needs matplotlib (code/requirements.txt).
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "paper" / "figures"
BLUE, ORANGE, GREY, INK = "#2a78d6", "#eb6834", "#8a8984", "#0b0b0b"

plt.rcParams.update({
    "font.family": "serif", "font.size": 9, "axes.edgecolor": GREY,
    "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False,
    "pdf.fonttype": 42, "svg.hashsalt": "compute-limits",
})


def load(name):
    return json.loads((DATA / name).read_text())


def mean(row):
    return (row["0841-w00"] + row["0841-ag896"]) / 2


def leads():
    rounds = load("selftrain_rounds.json")["rounds"]
    ea = load("error_analysis.json")
    base = mean(rounds["round1"]["rows"]["readerv2"]["texture"])
    bars = []
    for tag, arms in (("round1", ("S0", "S1", "S2")), ("round2", ("V1", "V2", "V3"))):
        for arm in arms:
            bars.append((f"{arm} (round {tag[-1]})", mean(rounds[tag]["rows"][arm + "-ens"]["texture"]) - base, BLUE))
    m = ea["models_texture"]
    bars.append(("Reader v2 + d9v2, rank mean", m["rv2+d9v2 rank mean (ranks over all box px)"]["lead_vs_readerv2"], ORANGE))
    bars.append(("Reader ensemble, 3 windows", m["rv2+d9x3 teacher (diag.json)"]["lead_vs_readerv2"], ORANGE))
    return bars


def fig_leads():
    bars = leads()
    fig, ax = plt.subplots(figsize=(5.6, 2.9))
    y = list(range(len(bars)))[::-1]
    ax.barh(y, [b[1] for b in bars], color=[b[2] for b in bars], height=0.62, edgecolor="white", linewidth=1)
    ax.set_yticks(y, [b[0] for b in bars])
    ax.axvline(0, color=GREY, lw=0.8)
    for x, lab in ((0.015, "development gate +0.015"), (0.02, "final bar +0.02")):
        ax.axvline(x, color=INK, lw=0.8, ls=(0, (3, 3)))
        ax.text(x - 0.0003, len(bars) - 0.45, lab, rotation=90, va="top", ha="right", fontsize=7.5)
    ax.set_xlabel("AUC lead over Reader v2, development mean")
    ax.set_xlim(-0.008, 0.022)
    ax.grid(axis="x", color="#e6e5e0", lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "leads.pdf", bbox_inches="tight")


def fig_probe():
    p = load("b300_probe.json")
    fig, (a, b) = plt.subplots(1, 2, figsize=(5.6, 2.3))
    runs = p["gpu"]["runs"]
    a.plot([r["batch"] for r in runs], [r["patches_per_s"] for r in runs], color=BLUE, lw=2, marker="o", ms=4, label="GPU step alone")
    real = p["real"]
    a.plot([r["batch"] for r in real], [r["batch"] / r["s_per_step"] for r in real], ls="none", marker="s", ms=5, color=ORANGE, label="real training step")
    a.set_xscale("log", base=2)
    a.set_xticks([16, 32, 64, 128, 256], ["16", "32", "64", "128", "256"])
    a.set_xlabel("batch size")
    a.set_ylabel("patches per second")
    a.set_ylim(0, 900)
    a.legend(frameon=False, fontsize=7.5, loc="lower right")
    packs = p["pack"]["runs"]
    b.bar([str(r["copies"]) for r in packs], [r["patches_per_s"] for r in packs], color=BLUE, width=0.6, edgecolor="white")
    b.set_xlabel("trainings on one B300 (batch 16)")
    b.set_ylabel("total patches per second")
    b.set_ylim(0, 900)
    for ax in (a, b):
        ax.grid(axis="y", color="#e6e5e0", lw=0.6)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "probe.pdf", bbox_inches="tight")


def fig_tracer():
    t = load("tracer_cores.json")
    s = load("seed_anchor.json")
    runs = [r for r in t["runs"] if r["finished"]]
    fig, ax = plt.subplots(figsize=(5.6, 2.1))
    labels = [f"{r['cores']} cores" for r in runs]
    vals = [r["trace_s"] for r in runs]
    anch = [g for g in s["generations_60_threads_2"] if g["run"] == "anchored"][0]
    labels.append("seed held, 2 threads")
    vals.append(anch["trace_s"])
    colors = [BLUE] * len(runs) + [ORANGE]
    y = list(range(len(vals)))[::-1]
    ax.barh(y, vals, color=colors, height=0.6, edgecolor="white")
    ax.set_yticks(y, labels)
    shares = [f"{r['dominant']} {r['dominant_share']:.2f}" for r in runs] + [f"{anch['dominant']} {anch['dominant_share']:.2f}"]
    for yy, v, sh in zip(y, vals, shares):
        ax.text(v + 30, yy, f"{v:.0f} s; on {sh}", va="center", fontsize=7.5)
    ax.set_xlabel("seconds for one 60-generation trace")
    ax.set_xlim(0, 2900)
    ax.grid(axis="x", color="#e6e5e0", lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "tracer.pdf", bbox_inches="tight")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_leads()
    fig_probe()
    fig_tracer()
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.pdf"))))
