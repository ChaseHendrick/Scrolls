#!/usr/bin/env python3
"""Synthetic demo stills, a slow GIF and a short MP4 of the contact barrier (`kit switchfix barrier`, AutoPipeline's
qa.repair since 0.1.9) cutting a trace that hopped onto a touching sheet, and leaving alone a trace that did not.

Made-up data only: two sheets in a small volume, the same cases tests/test_switchfix_barrier.py of the AutoPipeline
package uses (no scan, no model output). The barrier itself is the released code, imported from the AutoPipeline
package folder given with --package (branch submission/progress-2026-10-fix9, folder
submissions/progress-2026-10-fix9/autopipeline/), so the picture shows what that code keeps and cuts.

  hop      sheet B (the neighbor) comes down onto sheet A (the trace's own), the two touch, then part again with A
           bending away: a trace that keeps straight leaves the contact on B. That is a sheet switch.
  stay     the same contact, but afterwards B moves back up and A stays: the trace is still on its own sheet.

Outputs (OUT_DIR): barrier-hop-still.png, barrier-control.png, barrier-topview.png, barrier-hop.gif, barrier-hop.mp4, each
with a sidecar JSON (scripts/media/common.py). Needs numpy, scipy, Pillow, ffmpeg and gifsicle.

  python scripts/media/barrier_demo.py --package PKG --out-dir docs/assets/contact-barrier
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402

SCRIPTS = ("common.py", "barrier_demo.py")
SHAPE = (112, 320, 400)       # z, y, x, as the package's barrier tests
ZA = 49.5                     # the trace's own sheet (A) and the trace's height
SEED = (12.0, 24.0, ZA)       # x, y, z
YCUT = 160                    # the cross-section's y
Z0, Z1 = 22, 84               # the z rows drawn
SCALE = 4                     # screen pixels per voxel, the same in x and z
FPS = 8

BG = (23, 26, 28)             # charcoal
INK = (238, 231, 217)         # ivory text
MUTED = (165, 160, 150)
AMBER = (242, 177, 52)        # the trace as grown
TEAL = (43, 179, 160)         # kept by the barrier
CORAL = (228, 87, 46)         # cut off by the barrier
MAGENTA = (222, 92, 222)      # barrier points


def font(size, bold=False):
    from PIL import ImageFont
    import matplotlib
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name), size)


def sheets(a_of_x, b_of_x):
    import numpy as np
    v = np.zeros(SHAPE, np.uint8)
    for f in (a_of_x, b_of_x):
        for x in range(SHAPE[2]):
            c = float(f(x))
            v[int(round(c - 1.5)):int(round(c + 1.5)) + 1, :, x] = 1
    return v


# The two cases of the package's tests (tests/test_switchfix_barrier.py, hop_volume and stay_volume), unchanged:
# sheet B, 14 voxels above A, comes to 6 voxels above it from x 200, the prediction draws the two as one thin run from
# x 236 to 264, then they part again. Hop: A drops 6 voxels below the trace (14 from x 300), so the straight trace
# left the contact on B. Stay: B goes back up and A stays, so the trace is still on A. (Smooth bends instead of these
# steps were tried on 28 Oct 2026 and the rule then saw no contact on both sides, so the steps are kept: the picture
# shows exactly the case the tests check.) main() checks that the barrier keeps and cuts as those tests require.
def a_hop(x):
    return ZA if x < 264 else (ZA - 6 if x < 300 else ZA - 14)


def b_hop(x):
    return ZA + 14 if x < 200 else (ZA + 6 if x < 236 else ZA)


def a_stay(x):
    return ZA


def b_stay(x):
    return ZA if 236 <= x < 264 else (ZA + 6 if 200 <= x < 300 else ZA + 14)


CASES = {"hop": (a_hop, b_hop), "stay": (a_stay, b_stay)}


class ArrayReader:
    def __init__(self, vol, chunk=32):
        self.vol, self.chunks = vol, (chunk,) * 3
        self.meta = {"shape": list(vol.shape)}

    def read(self, key):
        import numpy as np
        c = self.chunks[0]
        z, y, x = (int(k) * c for k in key)
        out = np.zeros(self.chunks, np.uint8)
        part = self.vol[z:z + c, y:y + c, x:x + c]
        out[:part.shape[0], :part.shape[1], :part.shape[2]] = part
        return out


def mesh(step=4):
    import numpy as np
    xs = np.arange(8, 393, step, dtype=float)
    ys = np.arange(8, 313, step, dtype=float)
    X, Y = np.meshgrid(xs, ys)
    Z = np.full(X.shape, ZA)
    return np.stack([X, Y, Z], -1), np.ones(X.shape, bool)


def run_barrier(sf, sheetgap, vol):
    """The released barrier on a synthetic case: keep (H, W) and info from sf.barrier_keep, the same without the
    contact barrier (as the tests' joined control), and the dense barrier points' x and y, recomputed with the
    function's own steps for the overlay."""
    import numpy as np
    xyz, valid = mesh()
    field = sheetgap.Field(ArrayReader(vol), 1)
    keep, info = sf.barrier_keep(xyz, valid, field, seed=SEED)
    saved = sf.BARRIER["sheetgap"].pop("contact_barrier")
    try:
        joined, _ = sf.barrier_keep(xyz, valid, sheetgap.Field(ArrayReader(vol), 1), seed=SEED)
    finally:
        sf.BARRIER["sheetgap"]["contact_barrier"] = saved
    rule = sf.barrier_rule()
    up, _, nrm, ok, ustep = sheetgap.densify(xyz, valid, rule["step_vox"])
    cert = sheetgap.check_dense(up, nrm, ok, ustep, sheetgap.Field(ArrayReader(vol), 1), rule)
    bar = getattr(cert, "barrier", None)
    pts = up[bar] if bar is not None and bar.any() else np.zeros((0, 3))
    return xyz, valid, keep, joined, info, pts


def ct_slice(vol, seed=7):
    """The cross-section at y YCUT as a CT-like gray picture: blurred sheets, grain and a faint background."""
    import numpy as np
    from scipy import ndimage
    rng = np.random.default_rng(seed)
    sl = vol[:, YCUT, :].astype(np.float32)
    sl = ndimage.gaussian_filter(sl, 1.1)
    sl = sl / max(float(sl.max()), 1e-6)
    grain = ndimage.gaussian_filter(rng.normal(0, 1, sl.shape).astype(np.float32), 0.8)
    img = 0.10 + 0.78 * sl + 0.045 * grain
    img = np.clip(img[Z0:Z1][::-1], 0, 1)                       # z up
    g = (40 + 190 * img).astype(np.uint8)
    rgb = np.stack([g * 1.0, g * 0.96, g * 0.90], -1).astype(np.uint8)    # a warm gray
    return np.kron(rgb, np.ones((SCALE, SCALE, 1), np.uint8))


def to_screen(x, z):
    return (x * SCALE, (Z1 - 1 - z) * SCALE + SCALE / 2)


def row_at(xyz):
    import numpy as np
    return int(np.argmin(np.abs(xyz[:, 0, 1] - YCUT)))


def draw_trace(d, xyz, colors, upto=None, width=7):
    r = row_at(xyz)
    xs = xyz[r, :, 0]
    zs = xyz[r, :, 2]
    n = len(xs) if upto is None else upto
    for i in range(max(0, n - 1)):
        p0, p1 = to_screen(xs[i], zs[i]), to_screen(xs[i + 1], zs[i + 1])
        d.line([p0, p1], fill=colors[i], width=width)
    return [to_screen(xs[i], zs[i]) for i in range(n)]


def panel(vol, xyz, colors, title, sub, case, upto=None, barrier_pts=None, head=False, bar_alpha=1.0,
          labels=True):
    """One cross-section panel with a title band: CT-like slice, sheet labels, the trace and barrier points."""
    from PIL import Image, ImageDraw
    import numpy as np
    sl = ct_slice(vol)
    h, w = sl.shape[:2]
    band = 86
    img = Image.new("RGB", (w, h + band), BG)
    img.paste(Image.fromarray(sl), (0, band))
    d = ImageDraw.Draw(img, "RGBA")
    d.text((18, 12), title, font=font(26, True), fill=INK)
    d.text((18, 50), sub, font=font(19), fill=MUTED)

    def shifted(p):
        return (p[0], p[1] + band)

    if labels:
        a_of_x, b_of_x = CASES[case]
        fa, fb = font(17, True), font(17, True)
        xa, xb = 30, 30
        pa = shifted(to_screen(xa, a_of_x(xa) - 4.5))
        pb = shifted(to_screen(xb, b_of_x(xb) + 7.5))
        d.text(pa, "sheet A (the trace's own)", font=fa, fill=(205, 230, 225))
        d.text(pb, "sheet B (the neighbor)", font=fb, fill=(235, 215, 190))
        if case == "hop":
            xr = 335
            d.text(shifted(to_screen(xr, a_of_x(xr) - 3.0)), "A bends away", font=font(16), fill=(205, 230, 225))
            d.text(shifted(to_screen(xr - 10, b_of_x(xr) + 7.0)), "B continues here", font=font(16),
                   fill=(235, 215, 190))
        else:
            xr = 335
            d.text(shifted(to_screen(xr - 20, b_of_x(xr) + 7.5)), "B moves back up", font=font(16),
                   fill=(235, 215, 190))
        cx = 250
        d.text(shifted(to_screen(cx - 22, ZA + 12.5)), "contact", font=font(17, True), fill=INK)
        d.line([shifted(to_screen(cx, ZA + 8.0)), shifted(to_screen(cx, ZA + 3.5))], fill=INK, width=2)
    # the trace, drawn on the panel's own coordinates
    r = row_at(xyz)
    xs, zs = xyz[r, :, 0], xyz[r, :, 2]
    n = len(xs) if upto is None else upto
    for i in range(max(0, n - 1)):
        d.line([shifted(to_screen(xs[i], zs[i])), shifted(to_screen(xs[i + 1], zs[i + 1]))], fill=colors[i], width=7)
    if n >= 1 and head:
        hx, hy = shifted(to_screen(xs[n - 1], zs[n - 1]))
        d.ellipse([hx - 8, hy - 8, hx + 8, hy + 8], fill=AMBER + (255,), outline=INK, width=2)
    sx, sy = shifted(to_screen(SEED[0], SEED[2]))
    d.ellipse([sx - 10, sy - 10, sx + 10, sy + 10], outline=INK, width=3)
    d.text((sx + 14, sy + 10), "seed", font=font(16, True), fill=INK)
    if barrier_pts is not None and len(barrier_pts) and bar_alpha > 0:
        near = barrier_pts[np.abs(barrier_pts[:, 1] - YCUT) <= 6]
        if len(near):
            a = int(110 * bar_alpha)
            x0, y0 = shifted(to_screen(float(near[:, 0].min()), ZA + 4))
            x1, y1 = shifted(to_screen(float(near[:, 0].max()), ZA - 4))
            d.rectangle([x0, y0, x1, y1], fill=MAGENTA + (a,), outline=MAGENTA + (int(255 * bar_alpha),), width=2)
            d.text((x0 + 6, y1 + 6), "barrier", font=font(17, True), fill=MAGENTA + (int(255 * bar_alpha),))
    return img


def colors_for(xyz, keep_row, mode, cut_alpha=1.0):
    n = xyz.shape[1]
    if mode == "grown":
        return [AMBER + (255,)] * n
    out = []
    for i in range(n):
        if keep_row[i]:
            out.append(TEAL + (255,))
        else:
            out.append(CORAL + (int(255 * cut_alpha),))
    return out


def stack(*imgs, gap=10, foot=None):
    from PIL import Image, ImageDraw
    w = max(i.size[0] for i in imgs)
    h = sum(i.size[1] for i in imgs) + gap * (len(imgs) - 1) + (84 if foot else 0)
    out = Image.new("RGB", (w, h), BG)
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.size[1] + gap
    if foot:
        ImageDraw.Draw(out).text((18, y + 6), foot, font=font(16), fill=MUTED)
    return out


def legend(d, x, y, items):
    for color, text in items:
        d.line([(x, y + 11), (x + 34, y + 11)], fill=color, width=7)
        d.text((x + 44, y), text, font=font(17), fill=INK)
        x += 60 + int(font(17).getlength(text))


FOOT = ("Synthetic demo: made-up sheets in a 112 x 320 x 400 voxel volume; the cut is computed by the released "
        "kit switchfix barrier (AutoPipeline 0.1.9). No scan data.")


def still_hop(R):
    from PIL import ImageDraw
    vol, (xyz, valid, keep, joined, info, pts) = R["hop"]
    r = row_at(xyz)
    top = panel(vol, xyz, colors_for(xyz, joined[r], "grown"), "Trace as grown",
                "It runs straight through the contact. Past it, its own sheet bends away: it is now on the neighbor.",
                "hop")
    bot = panel(vol, xyz, colors_for(xyz, keep[r], "barrier"), "After the contact barrier",
                "Where the neighbor shows on both sides of the trace, a barrier is drawn. Only the seed's side is kept.",
                "hop", barrier_pts=pts)
    img = stack(top, bot, foot=FOOT)
    d = ImageDraw.Draw(img)
    legend(d, 18, img.size[1] - 34, [(AMBER, "as grown"), (TEAL, "kept"), (CORAL, "cut"), (MAGENTA, "barrier")])
    return img


def still_control(R):
    from PIL import ImageDraw
    vol, (xyz, valid, keep, joined, info, pts) = R["stay"]
    r = row_at(xyz)
    top = panel(vol, xyz, colors_for(xyz, joined[r], "grown"), "Control: a trace that stays on its sheet",
                "The same contact, but afterwards the neighbor moves back up. The trace never left sheet A.",
                "stay")
    bot = panel(vol, xyz, colors_for(xyz, keep[r], "barrier"), "After the contact barrier: nothing cut",
                "The neighbor touched from one side only, so no barrier is drawn and every vertex is kept.",
                "stay", barrier_pts=pts)
    img = stack(top, bot, foot=FOOT)
    legend(ImageDraw.Draw(img), 18, img.size[1] - 34, [(AMBER, "as grown"), (TEAL, "kept"), (CORAL, "cut")])
    return img


def keep_map(keep, valid, title, sub, w=760):
    """The whole trace seen from above (x across, y down): kept and cut vertices."""
    from PIL import Image, ImageDraw
    import numpy as np
    H, W = keep.shape
    rgb = np.zeros((H, W, 3), np.uint8)
    rgb[:] = BG
    rgb[valid & keep] = TEAL
    rgb[valid & ~keep] = CORAL
    k = max(1, w // W)
    tile = Image.fromarray(np.kron(rgb, np.ones((k, k, 1), np.uint8)))
    band = 86
    img = Image.new("RGB", (tile.size[0] + 36, tile.size[1] + band + 40), BG)
    img.paste(tile, (18, band))
    d = ImageDraw.Draw(img)
    d.text((18, 12), title, font=font(24, True), fill=INK)
    d.text((18, 48), sub, font=font(17), fill=MUTED)
    sx = 18 + int((SEED[0] - 8) / 4) * k
    sy = band + int((SEED[1] - 8) / 4) * k
    d.ellipse([sx - 9, sy - 9, sx + 9, sy + 9], outline=INK, width=3)
    for xv, lab in ((200, "x 200"), (264, "x 264")):
        px = 18 + int((xv - 8) / 4) * k
        d.line([(px, band + tile.size[1] + 4), (px, band + tile.size[1] + 14)], fill=MUTED, width=2)
        d.text((px - 22, band + tile.size[1] + 16), lab, font=font(14), fill=MUTED)
    return img


def still_top(R):
    from PIL import Image, ImageDraw
    vol, (xyz, valid, keep, joined, info, pts) = R["hop"]
    a = keep_map(keep, valid, "Hop: seed's side kept",
                 f"{int(keep.sum())} of {int(valid.sum())} vertices kept; the cut runs along the contact")
    vol2, (xyz2, valid2, keep2, joined2, info2, pts2) = R["stay"]
    b = keep_map(keep2, valid2, "Control: kept whole",
                 f"{int(keep2.sum())} of {int(valid2.sum())} vertices kept; no barrier drawn")
    w = a.size[0] + b.size[0] + 20
    out = Image.new("RGB", (w, max(a.size[1], b.size[1]) + 70), BG)
    out.paste(a, (0, 0))
    out.paste(b, (a.size[0] + 20, 0))
    d = ImageDraw.Draw(out)
    d.text((18, out.size[1] - 56), "The traced surface from above (x across, y down), seed ringed. "
           "Synthetic demo, released kit switchfix barrier.", font=font(16), fill=MUTED)
    legend(d, 18, out.size[1] - 30, [(TEAL, "kept"), (CORAL, "cut")])
    return out


def frames(R, out_dir):
    """The GIF's frames: the trace grows through the contact onto the neighbor; the barrier is drawn and the far part
    cut; then the control grows through the same kind of contact and is kept whole. About 8 frames a second."""
    from PIL import ImageDraw
    seq = []
    vol, (xyz, valid, keep, joined, info, pts) = R["hop"]
    r = row_at(xyz)
    n = xyz.shape[1]
    grown = colors_for(xyz, joined[r], "grown")
    xs = xyz[r, :, 0]
    for k in range(2, n + 1, 2):
        sub = ("The trace grows from its seed along sheet A." if xs[k - 1] < 236 else
               "At the contact the two sheets look like one." if xs[k - 1] < 264 else
               "Past the contact, sheet A bends away: the trace is now on sheet B.")
        seq.append(panel(vol, xyz, grown, "1. A trace grows through a contact", sub, "hop", upto=k, head=True))
    seq += [seq[-1]] * 16
    for t in range(1, 9):
        seq.append(panel(vol, xyz, grown, "2. The contact barrier looks at the contact",
                         "The neighbor shows on both sides of the trace there: a barrier is drawn.", "hop",
                         barrier_pts=pts, bar_alpha=t / 8))
    seq += [seq[-1]] * 8
    for t in range(1, 11):
        cols = colors_for(xyz, keep[r], "barrier", cut_alpha=max(0.25, 1 - t / 10))
        seq.append(panel(vol, xyz, cols, "3. Only the seed's side is kept",
                         "The part past the barrier is cut off. The trace ends on its own sheet.", "hop",
                         barrier_pts=pts))
    seq += [seq[-1]] * 20
    vol2, (xyz2, valid2, keep2, joined2, info2, pts2) = R["stay"]
    grown2 = colors_for(xyz2, joined2[r], "grown")
    for k in range(4, n + 1, 4):
        seq.append(panel(vol2, xyz2, grown2, "4. Control: the same contact, no switch",
                         "Afterwards the neighbor moves back up; the trace never left sheet A.", "stay", upto=k,
                         head=True))
    seq += [seq[-1]] * 8
    kept2 = colors_for(xyz2, keep2[r], "barrier")
    seq += [panel(vol2, xyz2, kept2, "5. The barrier keeps all of it",
                  "Touched from one side only: no barrier, nothing cut.", "stay")] * 24
    out = []
    for i, im in enumerate(seq):
        d = ImageDraw.Draw(im)
        d.text((im.size[0] - 380, 14), "Synthetic demo, no scan data", font=font(16), fill=MUTED)
        p = out_dir / f"frame-{i:05d}.png"
        im.save(p)
        out.append(p)
    return out


def meta_for(name, alt, caption):
    return {"label": "Synthetic demo", "alt": alt, "caption": caption, "license": "Apache-2.0", "release_id": None,
            "data": None, "sources": []}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--package", required=True, help="the AutoPipeline package folder (holds kit/switchfix.py)")
    ap.add_argument("--out-dir", required=True, help="where the stills, GIF, MP4 and sidecars go")
    ap.add_argument("--package-commit", default="", help="the commit the package folder was taken from")
    a = ap.parse_args(argv)
    pkg = Path(a.package).resolve()
    if not (pkg / "kit" / "switchfix.py").exists():
        sys.exit(f"{pkg}: no kit/switchfix.py; give the AutoPipeline package folder")
    sys.path.insert(0, str(pkg))
    from kit import sheetgap, switchfix as sf
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    R = {}
    for case, (fa, fb) in CASES.items():
        vol = sheets(fa, fb)
        R[case] = (vol, run_barrier(sf, sheetgap, vol))
    hop_keep, stay_keep = R["hop"][1][2], R["stay"][1][2]
    hop_join = R["hop"][1][3]
    X = R["hop"][1][0][..., 0]
    checks = {"hop_seed_side_kept": bool(hop_keep[X <= 150].all()), "hop_far_side_cut": bool(not hop_keep[X >= 330].any()),
              "hop_joined_without_barrier": bool(hop_join[X >= 330].all()),
              "stay_kept_whole": bool(stay_keep[R["stay"][1][1]].all()),
              "hop_barrier_points": int(R["hop"][1][4]["barrier_points"]),
              "stay_barrier_points": int(R["stay"][1][4]["barrier_points"]),
              "barrier_digest": sf.barrier_digest(), "sheetgap_rule_digest": sheetgap.rule_digest(sf.barrier_rule())}
    print(json.dumps(checks, indent=1))
    if not (checks["hop_seed_side_kept"] and checks["hop_far_side_cut"] and checks["hop_joined_without_barrier"]
            and checks["stay_kept_whole"]):
        sys.exit("the barrier did not behave as the package's tests say; no media written")
    cmd = "python scripts/media/barrier_demo.py --package PKG --out-dir " + str(a.out_dir)
    extra = {"barrier": {"package_commit": a.package_commit, **checks}}
    stills = {
        "barrier-hop-still": (still_hop(R),
                        "Two cross-sections of a made-up pair of sheets. Top: a trace in amber runs straight from "
                        "its seed through a place where the two sheets touch and ends on the neighboring sheet. "
                        "Bottom: the same trace after the contact barrier, the seed's side in teal, the part past the "
                        "contact in coral, and magenta marks where the barrier was drawn.",
                        "Synthetic demo: the contact barrier (kit switchfix barrier, AutoPipeline 0.1.9) on made-up "
                        "sheets. A trace that ran through a contact onto the neighboring sheet is cut back to its "
                        "seed's side. No scan data."),
        "barrier-control": (still_control(R),
                            "Two cross-sections of a made-up pair of sheets where the trace passes a contact but "
                            "stays on its own sheet. The contact barrier draws no barrier and keeps the whole trace "
                            "in teal.",
                            "Synthetic demo, the control: the same kind of contact with no sheet switch. The contact "
                            "barrier keeps every vertex. No scan data."),
        "barrier-topview": (still_top(R),
                            "Two maps of a traced surface seen from above. Left: the hop case, teal on the seed's side "
                            "and coral past a straight cut along the contact. Right: the control, all teal.",
                            "Synthetic demo: what the contact barrier keeps (teal) and cuts (coral) over the whole "
                            "made-up trace, for the hop and for the control. No scan data."),
    }
    for name, (img, alt, caption) in stills.items():
        p = out / f"{name}.png"
        meta = meta_for(name, alt, caption)
        common.write_guard(meta["label"], p, meta)
        img.save(p, optimize=True)
        common.size_guard(p, img.size[0])
        common.write_sidecar(out / f"{name}.json", meta, [common.output_record(p, *img.size, kind="still",
                                                                                format="png")],
                             command=cmd, scripts=SCRIPTS, extra=extra)
        print(p, img.size, p.stat().st_size)
    tmp = Path(tempfile.mkdtemp(prefix="barrier-frames-"))
    try:
        fr = frames(R, tmp)
        w, h = __import__("PIL.Image", fromlist=["Image"]).open(fr[0]).size
        gif, mp4 = out / "barrier-hop.gif", out / "barrier-hop.mp4"
        meta = meta_for("barrier-hop", "An animation on made-up sheets: a trace grows from its seed through a "
                        "contact and ends on the neighboring sheet; the contact barrier is drawn at the contact and "
                        "the part past it fades out; then a control trace passes the same kind of contact without "
                        "switching and is kept whole.",
                        "Synthetic demo: the contact barrier (kit switchfix barrier, AutoPipeline 0.1.9) cutting a "
                        "sheet switch and keeping a control trace whole, on made-up sheets. No scan data.")
        common.write_guard(meta["label"], gif, meta)
        pattern = str(tmp / "frame-%05d.png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", pattern, "-vf",
                        "fps=%d,scale=%d:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];"
                        "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" % (FPS, min(w, 1280)),
                        "-loop", "0", str(gif)], check=True)
        subprocess.run(["gifsicle", "-O3", "--lossy=40", "-b", str(gif)], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", pattern, "-vf",
                        "scale=%d:-2:flags=lanczos,format=yuv420p" % min(w, 1280), "-c:v", "libx264", "-crf", "22",
                        "-preset", "slow", "-movflags", "+faststart", "-r", str(FPS), str(mp4)], check=True)
        from PIL import Image
        outs = []
        for p, kind in ((gif, "gif"), (mp4, "video")):
            common.size_guard(p, min(w, 1280))
            if not p.exists():
                sys.exit(f"{p} was over the public size limit and was removed")
            if kind == "gif":
                gw, gh = Image.open(p).size
            else:
                gw, gh = min(w, 1280), None
                probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                        "stream=width,height", "-of", "csv=p=0", str(p)], capture_output=True,
                                       text=True, check=True).stdout.strip().split(",")
                gw, gh = int(probe[0]), int(probe[1])
            outs.append(common.output_record(p, gw, gh, kind=kind, format=p.suffix[1:], fps=FPS,
                                             frames=len(fr), seconds=round(len(fr) / FPS, 1)))
            print(p, gw, gh, p.stat().st_size)
        common.write_sidecar(out / "barrier-hop.json", meta, outs, command=cmd, scripts=SCRIPTS, extra=extra)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
