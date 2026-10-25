"""The still for docs/tools/crowdmerge.md: one planted crowd on PHerc0139 and what kit crowdmerge makes of it.

A cross-section along one row of one 8 mm window of a hand-traced winding (A), in the bench's frame: across,
millimeters along the row; up, each surface's offset from A along A's normal, in voxels. The touching winding (B) is
drawn from its own published mesh. The top panel shows the bench's crowd (7 copies of A, 3 of which slide onto B);
the bottom one the consensus beside the crowd's largest trace and the naive mean. PHerc0139 is public and on no
prize list; the picture is mesh geometry only (published hand traces and planted copies of them), no CT and no ink.
Writes a sidecar JSON. Needs numpy, scipy, tifffile and Pillow, and `python -m kit hopbench refs` first.

  python scripts/media/crowdmerge_still.py --site w023 w024 25 0 --seed 2 --row-frac 0.7 --out-dir docs/assets/crowdmerge
"""

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import common  # noqa: E402
from kit import crowdmerge as cm  # noqa: E402
from kit import sheetrefs as sr  # noqa: E402

SCRIPTS = ("common.py", "crowdmerge_still.py")
BG, FG, DIM, GRID = (8, 12, 16), (225, 235, 239), (122, 143, 152), (34, 44, 52)
A_COL, B_COL = (225, 235, 239), (110, 120, 128)
GOOD, SLIP = (86, 156, 214), (230, 140, 60)
CONS, LARGE, MEAN = (80, 200, 120), (220, 80, 80), (170, 120, 220)


def section(points, A, row, c0, half=0.6):
    """(mm along the row, offset from A in voxels): per native column of A, the median offset of the points whose
    nearest A vertex lies on that native row and column."""
    np = sr._np()
    if not len(points):
        return np.zeros((0, 2))
    s, ins, src, _ = sr.match(points, A)
    W = A.valid.shape[1]
    r, c = np.divmod(src, W)
    keep = ins & np.isfinite(s) & (np.abs(r - row) <= half)
    cols, sv = c[keep], s[keep]
    out = [((col - c0) * A.step * sr.VOXEL_UM / 1000.0, float(np.median(sv[cols == col]))) for col in np.unique(cols)]
    return np.array(out).reshape(-1, 2)


def panel(d, box, curves, ylim, xlim, title, font, small):
    x0, y0, x1, y1 = box
    d.rectangle(box, outline=GRID)
    for v in range(int(math.ceil(ylim[0] / 5)) * 5, int(ylim[1]) + 1, 5):
        y = y1 - (v - ylim[0]) / (ylim[1] - ylim[0]) * (y1 - y0)
        d.line([(x0, y), (x1, y)], fill=GRID)
        d.text((x0 - 40, y - 7), f"{v:+d}", fill=DIM, font=small)
    for mm in range(0, int(xlim[1]) + 1):
        x = x0 + (mm - xlim[0]) / (xlim[1] - xlim[0]) * (x1 - x0)
        d.text((x - 4, y1 + 6), f"{mm}", fill=DIM, font=small)
    d.text((x0, y0 - 26), title, fill=FG, font=font)
    for pts, col, width in curves:
        if not len(pts):
            continue
        pts = [(px, py) for px, py in pts if xlim[0] <= px <= xlim[1]]
        xy = [(x0 + (px - xlim[0]) / (xlim[1] - xlim[0]) * (x1 - x0),
               y1 - (min(max(py, ylim[0]), ylim[1]) - ylim[0]) / (ylim[1] - ylim[0]) * (y1 - y0)) for px, py in pts]
        for (ax, ay), (bx, by) in zip(xy, xy[1:]):
            if abs(bx - ax) < 30:
                d.line([(ax, ay), (bx, by)], fill=col, width=width)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--site", nargs=4, required=True, metavar=("A", "B", "ROW0", "COL0"),
                   help="windings and the window's top-left native cell, as a bench row's A, B and at")
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--row-frac", type=float, default=0.5, help="which row of the window, 0 (top) to 1 (bottom)")
    p.add_argument("--refs", default=str(sr.DEFAULT_REFS))
    p.add_argument("--out-dir", required=True)
    p.add_argument("--name", default="crowdmerge-pherc0139")
    a = p.parse_args(argv)
    np = sr._np()
    from PIL import Image, ImageDraw, ImageFont
    out = Path(a.out_dir) / f"{a.name}.png"
    meta = {"label": "Real data render", "license": "CC BY-NC 4.0",
            "alt": "Two stacked line charts. Top: a white line at zero offset (winding A), a gray line about 10 to 15 "
                   "voxels away that meets it at one place (winding B), four blue traces along the white line and "
                   "three orange traces that leave it for the gray one at different places. Bottom: a green "
                   "consensus line that stays on the white line, a red line (the largest single trace) that leaves "
                   "it, and a purple naive mean that sits between the two windings.",
            "caption": f"Real data render: kit crowdmerge on one planted crowd of PHerc0139 winding {a.site[0]} next "
                       f"to {a.site[1]} (published hand traces, scan 20250728140407), cross-section along one row of an "
                       "8 mm window. Mesh geometry only, no CT, no ink. Vesuvius Challenge open data, "
                       "CC BY-NC 4.0.",
            "data": {"scan": "PHerc0139", "voxel_size": f"{sr.VOXEL_UM} um", "labels": "none",
                     "credit": "Vesuvius Challenge open data, CC BY-NC 4.0",
                     "segment": f"{a.site[0]}, {a.site[1]} (hand-traced windings)", "volume": sr.VOLUME},
            "sources": [f"{sr.BUCKET}/{sr.SAMPLE}/segments/"]}
    common.write_guard(meta["label"], out, meta)
    man, refs = sr.load_refs(a.refs)
    R = {r.name: r for r in refs}
    A, B = R[a.site[0]], R[a.site[1]]
    r0, c0 = int(a.site[2]), int(a.site[3])
    side = int(math.ceil(cm.WINDOW_MM * 1000.0 / sr.VOXEL_UM / A.step))
    win = (slice(r0, r0 + side), slice(c0, c0 + side))
    xyz, valid = A.xyz[win], A.valid[win] & (A.label[win] == A.gid)
    up, uv, nA, ok, step, _ = cm._densify(xyz, valid, 2.0)
    s = np.full(ok.shape, np.nan)
    ins = np.zeros(ok.shape, bool)
    nB = np.zeros(ok.shape + (3,))
    ss, ii, _, nn = sr.match(up[ok], B)
    s[ok], ins[ok], nB[ok] = ss, ii & np.isfinite(ss), nn
    crowd = cm.crowd(up, ok, nA, s, ins, nB, step, np.random.default_rng(a.seed))
    traces = [(n, P, v) for n, P, v, _ in crowd]
    vote = cm.merge(traces)
    mean = cm.merge(traces, method="mean")
    row = r0 + int(round(a.row_frac * (side - 1)))
    lo, hi = up[ok].min(0) - 40, up[ok].max(0) + 40
    bp = B.scoring()[0]
    bp = bp[((bp >= lo) & (bp <= hi)).all(1)]
    sec = lambda P: section(P, A, row, c0)  # noqa: E731
    big = max(crowd, key=lambda c: int(c[2].sum()))
    curves_top = [(sec(bp), B_COL, 3), (sec(up[ok]), A_COL, 3)]
    for i, (n, P, v, _) in enumerate(crowd):
        curves_top.append((sec(P[v]), SLIP if i < cm.SLIPPING else GOOD, 2))
    curves_bot = [(sec(bp), B_COL, 3), (sec(up[ok]), A_COL, 3), (sec(mean["xyz"][mean["valid"]]), MEAN, 2),
                  (sec(big[1][big[2]]), LARGE, 2), (sec(vote["xyz"][vote["valid"]]), CONS, 4)]
    allx = np.concatenate([c[0][:, 0] for c in curves_top if len(c[0])])
    bsec = curves_top[0][0]
    xlim = (0.0, cm.WINDOW_MM)
    m = (float(np.abs(bsec[:, 1]).max()) if len(bsec) else 20.0) + 4
    ylim = (-m, m)
    Wd, Ht = 1200, 860
    img = Image.new("RGB", (Wd, Ht), BG)
    d = ImageDraw.Draw(img)
    big_f, small = ImageFont.load_default(size=22), ImageFont.load_default(size=14)
    d.text((70, 16), f"kit crowdmerge: 7 traces of PHerc0139 {A.name}, 3 of which slide onto {B.name} where they touch",
           fill=FG, font=big_f)
    d.text((70, 46), "Cross-section along one row of an 8 mm window: across, mm along the row; up, offset "
           f"from {A.name} along its normal, voxels ({sr.VOXEL_UM} um)", fill=DIM, font=small)
    panel(d, (70, 110, Wd - 30, 420), curves_top, ylim, xlim, "The crowd", big_f, small)
    panel(d, (70, 490, Wd - 30, 760), curves_bot, ylim, xlim, "What each method makes of it", big_f, small)
    key = [(A_COL, f"{A.name} (hand trace)"), (B_COL, f"{B.name} (hand trace)"), (GOOD, "traces on the sheet"),
           (SLIP, "traces that slide"), (CONS, "crowdmerge consensus"), (LARGE, "largest single trace"),
           (MEAN, "naive mean")]
    x = 70
    for col, label in key:
        d.line([(x, 800), (x + 24, 800)], fill=col, width=4)
        d.text((x + 30, 792), label, fill=DIM, font=small)
        x += 40 + int(d.textlength(label, font=small))
    d.text((70, 826), "Mesh geometry only (published hand traces and planted copies of them), no CT, no ink. "
           "Vesuvius Challenge open data, CC BY-NC 4.0.", fill=DIM, font=small)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    common.size_guard(out, img.size[0])
    rec = common.output_record(out, img.size[0], img.size[1], kind="still", format="png")
    command = (f"python scripts/media/crowdmerge_still.py --site {' '.join(a.site)} --seed {a.seed} "
               f"--row-frac {a.row_frac} --out-dir {a.out_dir}")
    common.write_sidecar(out.with_suffix(".json"), meta, [rec], command=command, scripts=SCRIPTS,
                         inputs=[f"{sr.SAMPLE}/{A.name}", f"{sr.SAMPLE}/{B.name}"],
                         extra={"summary": {k: vote["summary"][k] for k in ("traces", "vertices", "grown_vertices")}})
    print(json.dumps({"png": str(out), "bytes": rec["bytes"], "size": list(img.size)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
