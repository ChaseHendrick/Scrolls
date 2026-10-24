"""The still and GIF for the isometry block proposed for meta.json (villa issue #2279), made with kit tifxyz isometry.

  still   a public segment shaded by kit tifxyz preview, every node whose worst grid edge is off the promised step
          by more than 10 % marked by how far, the 1.5x flags ringed, beside a histogram of every edge over the step
          and the block kit tifxyz isometry computes for it
  gif     a made-up sheet (part of a cylinder, so its grid starts exactly isometric) whose nodes slide along the
          sheet in one patch, as a tracer's grid can: the surface keeps its shape while the edges stretch on one side
          of the patch and squash on the other, and the block's numbers follow frame by frame

The segment must be from a public scan that is not prize-eligible (the public media rule, docs/media/README.md);
write_guard() refuses anything else under docs/assets/. Each file gets a sidecar JSON. Needs numpy, tifffile,
matplotlib and Pillow.

  python scripts/media/isometry_media.py SEGMENT --scan PHerc0139 --segment w035 --out-dir docs/assets/tifxyz
"""

import argparse
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import common  # noqa: E402
from kit import tifxyz  # noqa: E402

SCRIPTS = ("common.py", "isometry_media.py")
BG, FG, DIM = "#0b1014", "#e1ebef", "#7a8f98"
# worst edge over the step at a node: within 10 % (no mark), 10 to 25 %, 25 % to 1.5x, beyond 1.5x (flagged)
BANDS = ((1.1, 1.25, "#e8c547", "10 to 25 % off"), (1.25, 1.5, "#f08a3c", "25 % to 1.5x off"),
         (1.5, float("inf"), "#ff4d5e", "over 1.5x off (stretched node)"))
BLOCK_KEYS = ("within_10pct", "within_25pct", "median_abs_log_ratio", "area_ratio", "angle_deg", "stretched_nodes",
              "l2_mean", "linf", "area_error")


def _style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG, "text.color": FG,
                         "axes.labelcolor": DIM, "axes.edgecolor": DIM, "xtick.color": DIM, "ytick.color": DIM,
                         "font.size": 12, "font.family": "DejaVu Sans"})
    return plt


def _off(ratio):
    """How far a ratio is from 1 in the symmetric sense: 1.3 and 1/1.3 are both 1.3 off."""
    np = tifxyz._np()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.exp(np.abs(np.log(ratio)))


def _block_text(r):
    lines = ['"isometry": {', f'  "version": {r["version"]},', f'  "step_vx": {json.dumps(r["step_vx"])},',
             f'  "edges": {r["edges"]},']
    for k in BLOCK_KEYS:
        lines.append(f'  "{k}": {json.dumps(r[k])},')
    lines[-1] = lines[-1].rstrip(",")
    return "\n".join(lines + ["}"])


def _png(fig):
    from PIL import Image
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def still(seg, scan, name):
    plt = _style()
    np = seg._np
    r = tifxyz.isometry(seg)
    off = _off(tifxyz.node_ratio(seg))
    ec, er = tifxyz._edges(seg)
    both = np.concatenate([ec[np.isfinite(ec)], er[np.isfinite(er)]])
    fig = plt.figure(figsize=(16, 9), dpi=100)
    fig.text(0.03, 0.945, f"How isometric is {scan} {name}'s grid? kit tifxyz isometry, the block proposed for "
             "meta.json", fontsize=19, color=FG)
    fig.text(0.03, 0.91, f"Promised step {r['step_vx'][0]:g} voxels (1 / scale). {r['edges']:,} grid edges. Mesh "
             f"geometry only, no CT, no ink. {common.DATA_CREDIT}.", fontsize=12, color=DIM)
    ax = fig.add_axes([0.02, 0.1, 0.47, 0.78])
    ax.imshow(tifxyz.shade(seg), interpolation="lanczos")
    ys, xs = np.nonzero(np.isfinite(off))
    for lo, hi, col, lab in BANDS:
        k = (off[ys, xs] >= lo) & (off[ys, xs] < hi)
        n = int(k.sum())
        ax.scatter(xs[k], ys[k], s=3 if lo < 1.5 else 10, c=col, linewidths=0, label=f"{lab}: {n:,} nodes")
    flag = (off >= 1.5)
    fy, fx = np.nonzero(flag)
    # ring each cluster of flagged nodes once
    done = np.zeros(len(fy), bool)
    for i in range(len(fy)):
        if done[i]:
            continue
        near = (np.abs(fy - fy[i]) < 30) & (np.abs(fx - fx[i]) < 30)
        done |= near
        ax.add_patch(plt.Circle((fx[near].mean(), fy[near].mean()), 28, fill=False, ec="#ff4d5e", lw=1.6))
    ax.set_axis_off()
    leg = ax.legend(loc="upper left", bbox_to_anchor=(0.0, -0.005), ncol=3, fontsize=10, frameon=True,
                    markerscale=3, columnspacing=1.0)
    leg.get_frame().set_facecolor(BG)
    leg.get_frame().set_edgecolor(DIM)
    h = fig.add_axes([0.56, 0.52, 0.41, 0.33])
    bins = np.exp(np.linspace(np.log(0.5), np.log(2.0), 161))
    h.hist(np.clip(both, 0.5, 2.0), bins=bins, color="#9fb8c2", log=True)
    h.set_xscale("log")
    ticks = [0.5, 1 / 1.5, 0.8, 1 / 1.1, 1.0, 1.1, 1.25, 1.5, 2.0]
    h.set_xticks(ticks)
    h.set_xticklabels(["0.5", "1/1.5", "0.8", "1/1.1", "1", "1.1", "1.25", "1.5", "2"])
    h.minorticks_off()
    h.axvspan(1 / 1.1, 1.1, color="#3a6f5a", alpha=0.35, lw=0)
    for x in (1 / 1.5, 1.5):
        h.axvline(x, color="#ff4d5e", lw=1.2, ls="--")
    h.set_xlabel("edge length over the promised step (log scale)\ngreen: within 10 %; red dashes: the 1.5x flags")
    h.set_ylabel("edges")
    for s in ("top", "right"):
        h.spines[s].set_visible(False)
    fig.text(0.56, 0.42, _block_text(r), family="DejaVu Sans Mono", fontsize=12.5, color=FG, va="top")
    fig.text(0.81, 0.42, "within_*: share of edges within\n10 % and 25 % of the step\n\narea_ratio: triangle area "
             "over\ncells x step x step\n\nangle_deg: p5, p50, p95\n\nl2_mean, linf, area_error:\nflatboi's stretch "
             "metrics,\nthe grid as the flattening\n(a perfect grid gives 1, 1, 0)", fontsize=10.5, color=DIM,
             va="top")
    img = _png(fig)
    plt.close(fig)
    return img, r


def sliding_sheet(amp, h=34, w=52, step=20.0, radius=1500.0):
    """A cylinder patch with an exactly isometric grid, whose nodes then slide along the sheet by amp grid steps at
    most, in a round patch: the surface keeps its shape and only its grid stretches and squashes."""
    np = tifxyz._np()
    r, c = np.mgrid[0:h, 0:w].astype(float)
    g = np.exp(-(((c - w * 0.5) / 5.0) ** 2 + ((r - h * 0.5) / 6.0) ** 2) / 2.0)
    s = (c + amp * g) * step                      # arc length along the curved direction
    xyz = np.stack([radius * np.sin(s / radius), r * step, radius * (1 - np.cos(s / radius))], -1)
    return tifxyz.Segment(xyz, np.ones((h, w), bool), {"scale": [1 / step, 1 / step]}, "sliding-sheet", None)


def _edge_color(off):
    for lo, hi, col, _ in BANDS[::-1]:
        if off >= lo:
            return col
    return "#9fb8c2"


def gif_frames(amps):
    plt = _style()
    from mpl_toolkits.mplot3d.art3d import Line3DCollection
    np = tifxyz._np()
    frames, reports = [], []
    for amp in amps:
        seg = sliding_sheet(amp)
        r = tifxyz.isometry(seg)
        reports.append(r)
        P = seg.xyz
        ec, er = tifxyz._edges(seg)
        segs, cols, widths = [], [], []
        for E, a, b in ((ec, P[:, :-1], P[:, 1:]), (er, P[:-1, :], P[1:, :])):
            o = _off(E)
            for i in np.ndindex(E.shape):
                segs.append((a[i], b[i]))
                cols.append(_edge_color(o[i]))
                widths.append(0.7 if o[i] < 1.1 else 1.6)
        fig = plt.figure(figsize=(9.6, 5.4), dpi=100)
        ax = fig.add_axes([-0.04, -0.1, 0.68, 1.0], projection="3d")
        ax.set_facecolor(BG)
        ax.add_collection3d(Line3DCollection(segs, colors=cols, linewidths=widths))
        lo, hi = P.reshape(-1, 3).min(0), P.reshape(-1, 3).max(0)
        ax.set_xlim(lo[0], hi[0])
        ax.set_ylim(lo[1], hi[1])
        ax.set_zlim(lo[2], lo[2] + (hi[0] - lo[0]) * 0.6)
        ax.set_box_aspect((hi[0] - lo[0], hi[1] - lo[1], (hi[0] - lo[0]) * 0.6))
        ax.view_init(elev=52, azim=-78)
        ax.set_axis_off()
        fig.text(0.03, 0.93, "Same sheet, its grid nodes sliding along it", fontsize=15, color=FG)
        fig.text(0.03, 0.885, f"slide up to {amp:.1f} grid steps; synthetic demo, no scan data", fontsize=10.5,
                 color=DIM)
        y = 0.80
        fig.text(0.64, y + 0.06, "kit tifxyz isometry", fontsize=13, color=FG)
        for k in ("within_10pct", "within_25pct", "median_abs_log_ratio", "stretched_nodes", "l2_mean", "linf",
                  "area_error", "area_ratio"):
            fig.text(0.64, y, k, family="DejaVu Sans Mono", fontsize=11.5, color=DIM)
            fig.text(0.97, y, f"{r[k]}", family="DejaVu Sans Mono", fontsize=11.5, color=FG, ha="right")
            y -= 0.062
        y -= 0.02
        for col, lab in (("#9fb8c2", "edge within 10 % of the step"),) + tuple((b[2], b[3]) for b in BANDS):
            fig.text(0.64, y, "■", color=col, fontsize=12)
            fig.text(0.67, y, lab.replace(" (stretched node)", ""), color=DIM, fontsize=10.5)
            y -= 0.05
        frames.append(_png(fig))
        plt.close(fig)
    return frames, reports


def main(argv=None):
    p = argparse.ArgumentParser(prog="python scripts/media/isometry_media.py", description=__doc__.split("\n\n")[0])
    p.add_argument("segment", help="tifxyz folder or bucket URL (kit tifxyz's argument)")
    p.add_argument("--scan", required=True, help="the scroll, for example PHerc0139")
    p.add_argument("--segment", dest="name", required=True, help="the segment, for example w035")
    p.add_argument("--cache", default=tifxyz.DEFAULT_CACHE)
    p.add_argument("--out-dir", required=True)
    a = p.parse_args(argv)
    np = tifxyz._np()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cmd = f"python scripts/media/isometry_media.py {a.segment} --scan {a.scan} --segment {a.name} --out-dir {a.out_dir}"

    seg = tifxyz.load(a.segment, a.cache)
    um = f"{seg.voxel_um:g} um" if seg.voxel_um else "unknown"
    data = {"scan": a.scan, "voxel_size": um, "labels": "none", "credit": common.DATA_CREDIT,
            "segment": a.name, "volume": seg.volume}
    path = out / "isometry-still.png"
    meta = {"label": "Real data render", "license": common.DATA_LICENSE, "data": data,
            "sources": [a.segment] if "://" in a.segment else [],
            "alt": f"{a.scan} segment {a.name} shaded gray, almost free of marks: a few yellow and orange dots where a "
                   "node's worst grid edge is 10 to 50 % off the promised step, and red rings around the small "
                   "clusters off by more than 1.5x; beside it a histogram of every edge's length over the step, "
                   "packed at 1, and the isometry block kit tifxyz isometry computes for the segment.",
            "caption": f"Real data render: kit tifxyz isometry on {a.scan} {a.name}, the isometry block proposed for "
                       f"meta.json. Mesh geometry only, no CT, no ink. {common.DATA_CREDIT}."}
    common.write_guard(meta["label"], path, meta)
    img, rep = still(seg, a.scan, a.name)
    img.save(path, optimize=True)
    common.size_guard(path, img.width)
    common.write_sidecar(path.with_suffix(".json"), meta,
                         [common.output_record(path, img.width, img.height, kind="still", format="png")],
                         command=cmd, scripts=SCRIPTS, extra={"isometry": rep})
    print(path)

    up = list(np.linspace(0.0, 4.0, 25))
    amps = [0.0] * 4 + up + [4.0] * 8 + up[::-1] + [0.0] * 4
    frames, reps = gif_frames(sorted(set(amps)))
    by_amp = dict(zip(sorted(set(amps)), frames))
    seq = [by_amp[x] for x in amps]
    gif = out / "isometry-demo.gif"
    gmeta = {"label": "Synthetic demo", "license": "Apache-2.0", "data": None, "sources": [],
             "alt": "A made-up curved sheet drawn as its grid, in gray. In one round patch the grid nodes slide along "
                    "the sheet and back: the sheet keeps its shape, but the edges on one side of the patch turn "
                    "yellow, orange and red as they stretch and on the other side as they squash, while the numbers "
                    "beside it (edges within 10 %, median log ratio, stretched nodes, flatboi's L2 and Linf) move "
                    "away from a perfect grid's and back.",
             "caption": "Synthetic demo: kit tifxyz isometry on a made-up sheet whose grid nodes slide along it, as a "
                        f"tracer's grid can. At the largest slide, {reps[-1]['within_10pct'] * 100:.1f} % of the edges "
                        f"stay within 10 % and {reps[-1]['stretched_nodes']} nodes are flagged; the surface itself "
                        "never changes. No scan data."}
    common.write_guard(gmeta["label"], gif, gmeta)
    pal = [f.quantize(colors=96, method=2, dither=0) for f in seq]
    durations = [90] * len(pal)
    for i in (0, len(up) + 3 + 4):  # rest a little longer at a perfect grid and at the largest slide
        durations[i] = 900
    pal[0].save(gif, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True, disposal=1)
    common.size_guard(gif, seq[0].width)
    common.write_sidecar(gif.with_suffix(".json"), gmeta,
                         [common.output_record(gif, seq[0].width, seq[0].height, kind="gif", format="gif",
                                               seconds=round(sum(durations) / 1000, 1))],
                         command=cmd, scripts=SCRIPTS)
    print(gif)
    return 0


if __name__ == "__main__":
    sys.exit(main())
