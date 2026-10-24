import json, sys
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
d = {k: v[:-1] for k, v in json.load(open('trace.json')).items()}  # drop the exit sample
SURF, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
COL = {'current': '#eb6834', 'patched': '#2a78d6'}
LAB = {'current': 'current render_ink.py', 'patched': 'with the patch'}
out = sys.argv[1]
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 12, 'text.color': INK,
                     'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2})
T = max(v[-1][0] for v in d.values())
def frame(ax, upto):
    ax.clear(); ax.set_facecolor(SURF)
    ax.set_xlim(0, T * 1.02); ax.set_ylim(0, 1.75)
    ax.grid(axis='y', color=GRID, lw=0.8); ax.set_axisbelow(True)
    for s in ('top', 'right', 'left'): ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color(INK2)
    ax.tick_params(length=0)
    ax.set_xlabel('seconds'); ax.set_ylabel('process memory (GB)')
    for k, pts in d.items():
        xs = [p[0] for p in pts if p[0] <= upto]; ys = [p[1] for p in pts if p[0] <= upto]
        if not xs: continue
        ax.plot(xs, ys, color=COL[k], lw=2, solid_capstyle='round', label=LAB[k])
        peak = max(ys); tp = xs[ys.index(peak)]
        if upto >= pts[-1][0]:
            right = k == 'current'
            ax.annotate(f'peak {peak:.2f} GB', (tp, peak), xytext=(-10 if right else 8, 6),
                        textcoords='offset points', color=INK, fontsize=11,
                        ha='right' if right else 'left')
    if ax.lines: ax.legend(loc='upper left', frameon=False, labelcolor=INK)
    ax.set_title('Composite + 8-bit scaling of one 120 Mpx strip (5 uint8 slices)',
                 loc='left', color=INK, fontsize=13, pad=12)
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=120); fig.patch.set_facecolor(SURF)
frame(ax, T + 1); fig.tight_layout(); fig.savefig(f'{out}/render-ink-memory.png', facecolor=SURF)
n = 60
steps = [T * i / (n - 1) for i in range(n)] + [T + 1] * 15
fig2, ax2 = plt.subplots(figsize=(8, 4.2), dpi=90); fig2.patch.set_facecolor(SURF)
def upd(i): frame(ax2, steps[i]); fig2.tight_layout()
FuncAnimation(fig2, upd, frames=len(steps)).save(f'{out}/render-ink-memory.gif', writer=PillowWriter(fps=12))
