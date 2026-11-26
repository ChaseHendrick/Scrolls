"""Figures for the Segment Atlas dataset card: `assets/hero.png`, `assets/by_scroll.png` and `assets/quality.png`.

Drawn from the atlas rows and the Lens preview grids only (no CT, no model output). Every figure covers scrolls on no
prize list in kit's dated snapshot, the same scrolls that get Lens previews; scrolls on a prize list appear in the
tables only. Needs matplotlib (an ImportError tells kit.atlas.write to skip the figures).
"""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import atlas, tifxyz  # noqa: E402

BLUE, ORANGE, ROSE = "#3d6fd1", "#e08a3c", "#c2416b"
INK, MUTED, RULE = "#1d2330", "#5b6475", "#d9dde4"
PAPER = (0.93, 0.89, 0.82)
DPI = 150
FLAG_COLORS = ((1, ORANGE, "hole"), (2, BLUE, "fold"), (4, ROSE, "stretched"))


def _style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": RULE,
                         "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
                         "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white",
                         "axes.facecolor": "white", "savefig.facecolor": "white"})


def public(rows):
    """Rows of scrolls on no prize list: the only ones the figures draw."""
    return [r for r in rows if not r.get("prize_lists")]


def _rgb(hexcolor):
    return tuple(int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5))


def shade(xyz, flags):
    """An RGBA image of a Lens grid: paper tone lit by the surface normal, flags painted over, missing nodes clear."""
    np = tifxyz._np()
    h, w, _ = xyz.shape
    gy, gx = np.gradient(xyz, axis=(0, 1))
    n = np.cross(gx, gy)
    norm = np.linalg.norm(n, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        n = n / norm
    light = np.array([0.35, -0.45, 0.82])
    light = light / np.linalg.norm(light)
    lit = np.abs(np.nan_to_num((n * light).sum(-1), nan=0.0))
    lit = 0.45 + 0.55 * lit
    img = np.ones((h, w, 4))
    img[..., :3] = np.array(PAPER)[None, None, :] * lit[..., None]
    for bit, color, _ in FLAG_COLORS:
        m = (flags & bit) > 0
        img[m, :3] = 0.25 * img[m, :3] + 0.75 * np.array(_rgb(color))
    img[..., 3] = np.isfinite(xyz).all(-1)
    return img


def _tile_ok(r):
    """A mesh whose grid makes a readable tile: mostly filled and not a long strip."""
    h, w = r.get("grid_h") or 0, r.get("grid_w") or 0
    return h and w and 0.4 <= h / w <= 2.5 and (r.get("filled_share") or 0) >= 0.45


def pick_hero(rows, lens_dir, n=12):
    """Up to n top-level meshes with a preview, at most two per scroll, the largest of each segment first."""
    best = {}
    for r in public(rows):
        if r.get("kind") != "mesh" or not r.get("lens") or r.get("area_cm2") is None or r.get("error"):
            continue
        if not _tile_ok(r) or not (Path(lens_dir) / r["lens"]).is_file():
            continue
        key = (r["scroll"], r["segment"])
        if key not in best or r["area_cm2"] > best[key]["area_cm2"]:
            best[key] = r
    by_scroll = {}
    for r in sorted(best.values(), key=lambda r: -r["area_cm2"]):
        by_scroll.setdefault(r["scroll"], []).append(r)
    picked, rnd = [], 0
    while len(picked) < n and rnd < 2:
        for scroll in sorted(by_scroll, key=lambda s: -by_scroll[s][0]["area_cm2"]):
            if rnd < len(by_scroll[scroll]) and len(picked) < n:
                picked.append(by_scroll[scroll][rnd])
        rnd += 1
    return picked


def hero(rows, lens_dir, path, n=12):
    picked = pick_hero(rows, lens_dir, n)
    if not picked:
        return False
    cols = 4
    nrow = math.ceil(len(picked) / cols)
    fig, axes = plt.subplots(nrow, cols, figsize=(12, 2.9 * nrow + 0.9), dpi=DPI)
    axes = [axes] if nrow * cols == 1 else list(getattr(axes, "flat", axes))
    for ax in axes:
        ax.axis("off")
    for ax, r in zip(axes, picked):
        _, _, _, _, _, xyz, flags = atlas.read_lens((Path(lens_dir) / r["lens"]).read_bytes())
        img = shade(xyz, flags)
        if img.shape[0] > img.shape[1] * 1.15:      # landscape tiles read better
            img = tifxyz._np().rot90(img)
        ax.imshow(img, interpolation="bilinear")
        ax.set_title(f"{r['scroll']}  {r['segment'][:24]}\n{r['area_cm2']:,.1f} cm2 at {r['voxel_um']:g} um",
                     fontsize=8.5, color=INK, pad=4)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, c, _ in FLAG_COLORS]
    fig.legend(handles, [f"{name} nodes" for _, _, name in FLAG_COLORS], loc="lower center", ncol=3, frameon=False,
               fontsize=9)
    fig.suptitle("Vesuvius Segment Atlas: preview grids of public segments", fontsize=13, color=INK, y=0.995)
    fig.tight_layout(rect=(0, 0.035, 1, 0.965), h_pad=1.2, w_pad=0.8)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return True


def by_scroll(rows, segs, path):
    pub = {r["scroll"] for r in public(rows)}
    area, nseg, clean, meshes = {}, {}, {}, {}
    for g in segs:
        if g["scroll"] not in pub:
            continue
        nseg[g["scroll"]] = nseg.get(g["scroll"], 0) + 1
        area[g["scroll"]] = area.get(g["scroll"], 0.0) + (g.get("area_cm2") or 0.0)
    for r in public(rows):
        if r.get("kind") == "mesh" and r.get("grid_h") is not None and not r.get("error"):
            meshes[r["scroll"]] = meshes.get(r["scroll"], 0) + 1
            clean[r["scroll"]] = clean.get(r["scroll"], 0) + bool(r.get("clean"))
    order = sorted((s for s in nseg if area.get(s, 0) > 0), key=lambda s: area[s])
    if not order:
        return False
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 0.42 * len(order) + 1.6), dpi=DPI, sharey=True,
                                 gridspec_kw={"width_ratios": [1.6, 1]})
    y = range(len(order))
    a1.barh(y, [area[s] for s in order], color=BLUE, height=0.62)
    a1.set_xscale("log")
    a1.set_yticks(list(y), order)
    for i, s in enumerate(order):
        a1.text(area[s] * 1.08, i, f"{area[s]:,.0f} cm2, {nseg[s]} segment{'s' if nseg[s] != 1 else ''}", va="center", fontsize=8, color=MUTED)
    a1.set_xlim(right=max(area.values()) * 12)
    a1.set_xlabel("traced area, cm2 (log scale; each segment once)")
    a1.grid(axis="x", color=RULE, lw=0.6)
    share = [100 * clean.get(s, 0) / meshes[s] if meshes.get(s) else 0 for s in order]
    a2.barh(y, share, color=ORANGE, height=0.62)
    for i, (s, v) in enumerate(zip(order, share)):
        a2.text(v + 1.5, i, f"{clean.get(s, 0)} of {meshes.get(s, 0)}", va="center", fontsize=8, color=MUTED)
    a2.set_xlim(0, 115)
    a2.set_xlabel("top-level meshes with no holes, folds or stretched nodes, %")
    a2.grid(axis="x", color=RULE, lw=0.6)
    fig.suptitle("Traced area and clean meshes per scroll (scrolls on no prize list)", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return True


def quality(rows, path):
    np = tifxyz._np()
    top = [r for r in public(rows) if r.get("kind") == "mesh" and r.get("within_10pct") is not None
           and r.get("area_cm2")]
    scrolls = sorted({r["scroll"] for r in top}, key=lambda s: np.median(
        [r["within_10pct"] for r in top if r["scroll"] == s]))
    if not scrolls:
        return False
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 0.42 * len(scrolls) + 1.6), dpi=DPI, sharey=True)
    rng = np.random.default_rng(0)
    for i, s in enumerate(scrolls):
        v = np.array([100 * r["within_10pct"] for r in top if r["scroll"] == s])
        a1.scatter(v, i + rng.uniform(-0.22, 0.22, v.size), s=9, color=BLUE, alpha=0.45, lw=0)
        a1.plot([np.median(v)] * 2, [i - 0.32, i + 0.32], color=INK, lw=1.6)
    a1.set_yticks(range(len(scrolls)), scrolls)
    a1.set_xlabel("grid edges within 10 % of the promised step, % (one dot per mesh, bar at the median)")
    a1.grid(axis="x", color=RULE, lw=0.6)
    left = np.zeros(len(scrolls))
    for key, color, name in (("holes_mm2", ORANGE, "holes"), ("folds_mm2", BLUE, "folds"),
                             ("stretched_mm2", ROSE, "stretched")):
        share = []
        for s in scrolls:
            rs = [r for r in top if r["scroll"] == s]
            total = sum(r["area_cm2"] * 100 for r in rs)        # mm2
            share.append(100 * sum((r.get(key) or 0) for r in rs) / total if total else 0)
        a2.barh(range(len(scrolls)), share, left=left, color=color, height=0.62, label=name)
        left += np.array(share)
    a2.set_xlabel("flagged area over mesh area, % (sum over top-level meshes)")
    a2.legend(frameon=False, fontsize=8, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.06))
    a2.grid(axis="x", color=RULE, lw=0.6)
    fig.suptitle("Grid quality per scroll (scrolls on no prize list)", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return True


def write_all(out, rows, segs):
    """Draw every figure into OUT/assets/; return the names drawn (kit.atlas.card links those)."""
    _style()
    assets = Path(out) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    made = []
    if hero(rows, Path(out) / "lens", assets / "hero.png"):
        made.append("hero")
    if by_scroll(rows, segs, assets / "by_scroll.png"):
        made.append("by_scroll")
    if quality(rows, assets / "quality.png"):
        made.append("quality")
    return made
