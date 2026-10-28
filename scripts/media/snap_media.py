#!/usr/bin/env python3
"""Stills and slow GIFs of a snap for the Snapped Labels Space: the published label moving onto the papyrus face.

  concept   a synthetic cross section (no scan, no model output): two wraps of papyrus, a published label beside the
            first, the snap along the normals onto the recto face, then the truth face (dashed) with its band of one
            voxel on each side. Media label Concept illustration, so it may go under docs/assets/.
  real      a segment of the public dataset on its own CT, read live from the open data: the published line moving
            onto the snapped line and back, slowly. The lines are geometry from a band finder, so the media label is
            Model output: write_guard() refuses it under docs/assets/, and it goes on the Hugging Face dataset (next to
            snapped-0139.gif) only after Chase's yes. It refuses a prize-eligible scroll and held-out labels anywhere.

The motion matches the Space's "Animate snap" button: hold 1.2 s on the published line, 2.4 s to the snapped one, hold
1.6 s, 2.4 s back. Every output gets a sidecar JSON (common.write_sidecar) with its label, caption, license and, for
real data, the scan, voxel size, labels drawn and the credit "Vesuvius Challenge open data, CC BY-NC 4.0".

  python scripts/media/snap_media.py concept --out-dir docs/assets/snapped-labels
  python scripts/media/snap_media.py real --segment PHerc0139/20260206000002-w054_2026020617 --z 8048 --out-dir OUT

Needs numpy and Pillow; real also needs the network (huggingface.co and the open-data bucket).
"""

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402

SCRIPTS = ("common.py", "snap_media.py")
DATA = "https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels/resolve/main"
PUB, SNAP, BAND, INK = (240, 138, 36), (47, 123, 246), (217, 198, 163), (27, 29, 41)
FPS = 15
HOLD0, MOVE, HOLD1 = 1.2, 2.4, 1.6


def timeline(back=True):
    """(t, seconds) frames of one loop: t is 0 on the published line and 1 on the snapped one. Holds are one frame
    each with a long duration, so the GIF stays small."""
    frames = [(0.0, HOLD0)]
    n = int(round(MOVE * FPS))
    frames += [((i + 1) / n, 1 / FPS) for i in range(n - 1)]
    frames.append((1.0, HOLD1))
    if back:
        frames += [(1 - (i + 1) / n, 1 / FPS) for i in range(n - 1)]
    return frames


def _font(size):
    from PIL import ImageFont
    for name in ("Inter-Regular.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def save_gif(frames, durations, path):
    """Frames (RGB PIL images) into a looping GIF. One shared palette from a few frames plus a swatch of every color
    the moving line takes (orange to blue), so the line keeps its color through the tween."""
    from PIL import Image, ImageDraw
    w, h = frames[0].size
    k = min(len(frames), 6)
    picks = [frames[int(i * (len(frames) - 1) / max(1, k - 1))] for i in range(k)]
    sheet = Image.new("RGB", (w, h * k + 64))
    for i, f in enumerate(picks):
        sheet.paste(f, (0, h * i))
    sw = ImageDraw.Draw(sheet)
    for i in range(32):   # the line's colors, large enough that the palette keeps them
        sw.rectangle((i * w // 32, h * k, (i + 1) * w // 32, h * k + 63), fill=mix(PUB, SNAP, i / 31))
    pal = sheet.quantize(colors=200, method=Image.Quantize.MEDIANCUT)
    out = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    out[0].save(path, save_all=True, append_images=out[1:], duration=[int(round(1000 * d)) for d in durations],
                loop=0, optimize=True, disposal=1)


def finish(paths, meta, out_dir, command, data_meta=None):
    """Size checks and one sidecar for every output."""
    outs = []
    for p in paths:
        common.size_guard(p)
        dims = common.media_size(p)
        outs.append(common.output_record(p, *dims) if dims else common.output_record(p))
    side = Path(out_dir) / (Path(paths[0]).stem + ".json")
    common.write_sidecar(side, meta, outs, command=command, scripts=SCRIPTS)
    return side


# ---------------------------------------------------------------- concept

_BASE = {}


def _concept_base(size, seed):
    """The made-up papyrus and grain behind every concept frame, at twice the size (built once)."""
    import numpy as np
    key = (size, seed)
    if key in _BASE:
        return _BASE[key]
    W, H = size
    S = 2
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H * S, 0:W * S].astype(np.float32) / S
    img = 26 + 10 * rng.standard_normal((H * S, W * S)).astype(np.float32)
    for x0, thick in ((0.0, 70.0), (300.0, 62.0)):
        d = xx - (_face(yy, H) + x0)
        inside = (d >= 0) & (d <= thick)
        fib = 0.5 + 0.5 * np.sin(yy / 3.1 + 0.8 * np.sin(xx / 11.0))
        img = np.where(inside, 150 + 55 * fib + 14 * rng.standard_normal(img.shape), img)
        edge = np.exp(-np.minimum(np.abs(d), np.abs(d - thick)) ** 2 / 18.0)
        img = img + 40 * edge * inside
    img = np.clip(img, 0, 255).astype(np.uint8)
    rgb = np.stack([img * 0.92, img * 0.86, img * 0.74], -1).clip(0, 255).astype(np.uint8)   # warm, like papyrus
    _BASE[key] = rgb
    return rgb


def _face(y, H):
    """The recto face of the first made-up wrap: x as a function of y."""
    import numpy as np
    return 300 + 26 * np.sin(y / 120.0) + 0.0004 * (y - H / 2) ** 2


def concept_scene(t, truth_alpha, size=(960, 540), seed=7):
    """One frame of the synthetic cross section. t: 0 published, 1 snapped. truth_alpha: how much of the truth face
    and its band shows (0 to 1)."""
    import numpy as np
    from PIL import Image, ImageDraw
    W, H = size
    S = 2   # draw at twice the size, then downsample, for smooth lines
    face = lambda y: _face(y, H)   # noqa: E731
    rgb = _concept_base(size, seed)
    im = Image.fromarray(rgb, "RGB")
    dr = ImageDraw.Draw(im, "RGBA")
    ys = np.linspace(20, H - 20, 220)
    recto = [(float(face(y)) * S, float(y) * S) for y in ys]
    # published: beside the face, toward the center (left), wandering 2 to 9 voxels off
    off = 14 + 9 * np.sin(ys / 47.0) + 5 * np.cos(ys / 23.0)
    pub = [(float(face(y) - o) * S, float(y) * S) for y, o in zip(ys, off)]
    truth = [(float(face(y) + 1.5) * S, float(y) * S) for y in ys]
    if truth_alpha > 0:
        a = int(70 * truth_alpha)
        band = [(x - 6 * S, y) for x, y in truth] + [(x + 6 * S, y) for x, y in truth[::-1]]
        dr.polygon(band, fill=(110, 160, 255, a))
    cur = [(px + (rx - px) * t, py) for (px, py), (rx, _) in zip(pub, recto)]
    if t > 0:
        for (px, py), (cx, cy) in list(zip(pub, cur))[::9]:
            dr.line([(px, py), (cx, cy)], fill=(230, 232, 240, 150), width=S)
    dr.line(pub, fill=PUB + (110 if t > 0 else 255,), width=4 * S, joint="curve")
    dr.line(cur, fill=mix(PUB, SNAP, t) + (255,), width=4 * S, joint="curve")
    if truth_alpha > 0:
        a = int(255 * truth_alpha)
        for i in range(0, len(truth) - 1, 2):
            dr.line([truth[i], truth[i + 1]], fill=(255, 255, 255, a), width=2 * S)
    im = im.resize((W, H), Image.LANCZOS)
    dr = ImageDraw.Draw(im, "RGBA")
    f, fb = _font(17), _font(19)
    word = "Published label" if t == 0 else "Snapped onto the recto face" if t >= 1 else "Moving along the normals"
    dr.rounded_rectangle((14, 14, 28 + dr.textlength(word, font=fb), 46), 6, fill=(0, 0, 0, 150))
    dr.text((24, 18), word, font=fb, fill=(255, 255, 255))
    if truth_alpha > 0:
        lx, ly, txt = int(face(H * 0.72)) + 84, int(H * 0.72) - 12, "truth face (dashed), shaded ±1 voxel"
        dr.rounded_rectangle((lx - 8, ly - 4, lx + 8 + dr.textlength(txt, font=f), ly + 24), 6,
                             fill=(0, 0, 0, int(150 * truth_alpha)))
        dr.line([(lx - 8, ly + 10), (int(face(H * 0.72)) + 4, ly + 10)], fill=(255, 255, 255, int(200 * truth_alpha)), width=1)
        dr.text((lx, ly), txt, font=f, fill=(255, 255, 255, int(255 * truth_alpha)))
    dr.text((24, H - 60), "toward the center line", font=f, fill=(235, 235, 240))
    dr.line([(24, H - 30), (210, H - 30)], fill=(235, 235, 240), width=2)
    dr.polygon([(16, H - 30), (30, H - 37), (30, H - 23)], fill=(235, 235, 240))
    dr.text((W - 14, H - 14), "Concept illustration: made-up data, not a scan", font=_font(14),
            fill=(235, 235, 240), anchor="rd")
    return im


def concept(out_dir, name="snap-concept"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"label": "Concept illustration", "license": "Apache-2.0",
            "alt": "A made-up cross section of two papyrus wraps: an orange published label beside the first wrap moves "
                   "along its normals onto the wrap's recto face and turns blue; then a dashed truth face and its "
                   "one-voxel band appear.",
            "caption": "Concept illustration: a published label (orange) snapped along its normals onto the recto face "
                       "(blue), then a truth face (dashed) with its band of one voxel on each side. Made-up data, no "
                       "scan and no model output."}
    gif, still = out_dir / f"{name}.gif", out_dir / f"{name}.png"
    for p in (gif, still):
        common.write_guard(meta["label"], p, meta)
    frames, durs = [], []
    for t, d in timeline(back=False):
        frames.append(concept_scene(t, 0.0))
        durs.append(d)
    for i in range(8):
        frames.append(concept_scene(1.0, (i + 1) / 8))
        durs.append(1 / FPS)
    durs[-1] = 2.4
    for i in range(int(MOVE * FPS) - 1):   # back to the start, truth face fading out
        t = 1 - (i + 1) / (MOVE * FPS)
        frames.append(concept_scene(t, max(0.0, t)))
        durs.append(1 / FPS)
    save_gif(frames, durs, gif)
    concept_scene(1.0, 1.0).save(still, optimize=True)
    cmd = "python scripts/media/snap_media.py concept --out-dir OUT_DIR"
    return finish([gif, still], meta, out_dir, cmd)


# ---------------------------------------------------------------- real

def _get(url, rng=None):
    req = urllib.request.Request(url, headers={"User-Agent": "scrolls-snap-media"})
    if rng:
        req.add_header("Range", f"bytes={rng[0]}-{rng[0] + rng[1] - 1}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return None
        raise


def ct_window(vol, z, y0, x0, n):
    """A level-0 n x n window of plane z from an uncompressed OME-Zarr v2 volume, as uint8 (0 outside the scan); the
    same reads as the Space's viewer."""
    import numpy as np
    m = json.loads(_get(f"{vol}/0/.zarray"))
    if m.get("compressor"):
        raise common.MediaError("compressed scan: this script reads uncompressed chunks only")
    Z, Y, X = m["shape"]
    cz, cy, cx = m["chunks"]
    out = np.zeros((n, n), np.uint8)
    if not 0 <= z < Z:
        return out
    for by in range(max(0, y0) // cy, (min(Y, y0 + n) - 1) // cy + 1):
        for bx in range(max(0, x0) // cx, (min(X, x0 + n) - 1) // cx + 1):
            b = _get(f"{vol}/0/{z // cz}/{by}/{bx}", ((z % cz) * cy * cx, cy * cx))
            if not b:
                continue
            tile = np.frombuffer(b, np.uint8).reshape(cy, cx)
            ys, xs = by * cy - y0, bx * cx - x0
            sy, sx = slice(max(0, -ys), min(cy, n - ys)), slice(max(0, -xs), min(cx, n - xs))
            out[max(0, ys):max(0, ys) + (sy.stop - sy.start), max(0, xs):max(0, xs) + (sx.stop - sx.start)] = tile[sy, sx]
    return out


def real_meta(view, segment, z):
    short = segment.split("/")[-1].split("-", 1)[-1].split("_")[0]
    return {"label": "Model output", "license": common.DATA_LICENSE,
            "alt": f"{view['scroll']} segment {short} on CT at z {z}: the published label (orange) moving along its "
                   "normals onto the snapped label (blue) and back, slowly.",
            "caption": f"Model output on {view['scroll']} {short}, z {z}: published label (orange) snapped onto the "
                       f"papyrus face (blue). {common.DATA_CREDIT}.",
            "data": {"scan": view["scroll"], "voxel_size": f"{view.get('voxel_um')} um",
                     "labels": f"published and snapped labels of {short}", "segment": short,
                     "volume": view.get("frame") or "", "credit": common.DATA_CREDIT}}


def real(segment, z, out_dir, data=DATA, win=192, size=720, center=None, name=None):
    scroll, seg = segment.split("/", 1)
    view = json.loads(_get(f"{data}/viewer/{scroll}/{seg}.json"))
    meta = real_meta(view, segment, z)
    problems = common.real_data_problems(meta)
    if problems:
        raise common.MediaError("refused under the public media rule: " + "; ".join(problems))
    out_dir = Path(out_dir)
    name = name or f"snap-{scroll.lower()}-{meta['data']['segment']}-z{z}"
    gif, s_pub, s_snap = (out_dir / f"{name}.gif", out_dir / f"{name}-published.png", out_dir / f"{name}-snapped.png")
    for p in (gif, s_pub, s_snap):
        common.write_guard(meta["label"], p, meta)   # Model output: refused under docs/assets/
    import numpy as np   # after the refusals, so they hold without numpy and Pillow
    from PIL import Image, ImageDraw
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = np.frombuffer(_get(f"{data}/viewer/{scroll}/{seg}.bin"), np.float32).reshape(-1, 8)
    plane = min(view["planes"], key=lambda p: abs(p["z"] - z))
    r = rows[plane["first"]:plane["first"] + plane["count"]]
    if not len(r):
        raise common.MediaError(f"no label pieces on the plane nearest z {z}")
    if center:
        cx, cy = center
    else:   # the piece nearest the plane's centroid, as the viewer starts
        mx, my = r[:, 0].mean(), r[:, 1].mean()
        i = int(np.argmin((r[:, 0] - mx) ** 2 + (r[:, 1] - my) ** 2))
        cx, cy = float(r[i, 0]), float(r[i, 1])
    x0, y0 = int(round(cx - win / 2)), int(round(cy - win / 2))
    ct = ct_window(view["volume"], plane["z"], y0, x0, win)
    nz = ct[ct > 0]
    lo, hi = (np.percentile(nz, 1), np.percentile(nz, 99.5)) if nz.size else (0, 255)
    g = np.clip((ct.astype(np.float32) - lo) * 255 / max(1, hi - lo), 0, 255).astype(np.uint8)
    S = 2
    base = Image.fromarray(g, "L").resize((size * S, size * S), Image.NEAREST).convert("RGB")
    k = size * S / win
    P = lambda x, y: ((x - x0 + 0.5) * k, (y - y0 + 0.5) * k)   # noqa: E731
    um = view.get("voxel_um")

    def frame(t):
        im = base.copy()
        dr = ImageDraw.Draw(im, "RGBA")
        for a in r:
            dr.line([P(a[0], a[1]), P(a[2], a[3])], fill=PUB + (90 if t > 0 else 255,), width=3 * S)
        col = mix(PUB, SNAP, t) + (255,)
        for a in r:
            ax, ay = a[0] + (a[4] - a[0]) * t, a[1] + (a[5] - a[1]) * t
            bx, by = a[2] + (a[6] - a[2]) * t, a[3] + (a[7] - a[3]) * t
            dr.line([P(ax, ay), P(bx, by)], fill=col, width=3 * S)
        im = im.resize((size, size), Image.LANCZOS)
        dr = ImageDraw.Draw(im, "RGBA")
        word = "Published label" if t == 0 else "Snapped label" if t >= 1 else "Snapping along the normals"
        fb, f = _font(19), _font(14)
        dr.rounded_rectangle((12, 12, 26 + dr.textlength(word, font=fb), 44), 6, fill=(0, 0, 0, 150))
        dr.text((22, 16), word, font=fb, fill=(255, 255, 255))
        sb = 10 * size / win
        dr.rectangle((16, size - 24, 16 + sb, size - 20), fill=(255, 255, 255))
        dr.text((16, size - 46), f"10 voxels ({round(10 * um)} µm)" if um else "10 voxels", font=f, fill=(255, 255, 255))
        line2 = f"Model output · {view['scroll']} {meta['data']['segment']}, z {plane['z']} · {common.DATA_CREDIT}"
        dr.rounded_rectangle((size - 20 - dr.textlength(line2, font=f), size - 30, size - 8, size - 8), 5,
                             fill=(0, 0, 0, 150))
        dr.text((size - 14, size - 12), line2, font=f, fill=(235, 235, 240), anchor="rd")
        return im

    tl = timeline(back=True)
    save_gif([frame(t) for t, _ in tl], [d for _, d in tl], gif)
    frame(0.0).save(s_pub, optimize=True)
    frame(1.0).save(s_snap, optimize=True)
    cmd = (f"python scripts/media/snap_media.py real --segment {segment} --z {z} --window {win} --size {size} "
           "--out-dir OUT_DIR")
    return finish([gif, s_pub, s_snap], meta, out_dir, cmd)


def main(argv=None):
    p = argparse.ArgumentParser(prog="snap_media.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("concept", help="the synthetic cross section: a still and a slow GIF (Concept illustration)")
    c.add_argument("--out-dir", required=True, help="where the files and their sidecar go")
    c.add_argument("--name", default="snap-concept", help="file name stem")
    r = sub.add_parser("real", help="a dataset segment on its live CT: two stills and a slow GIF (Model output)")
    r.add_argument("--segment", required=True, help="SCROLL/SEGMENT, a path from the dataset's index.json")
    r.add_argument("--z", type=int, required=True, help="the z plane; the nearest plane in the viewer data is used")
    r.add_argument("--out-dir", required=True, help="where the files and their sidecar go (never docs/assets/)")
    r.add_argument("--window", type=int, default=192, help="CT window, in voxels")
    r.add_argument("--size", type=int, default=720, help="output width and height, in pixels")
    r.add_argument("--center", type=float, nargs=2, metavar=("X", "Y"), help="window center in voxels")
    r.add_argument("--data", default=DATA, help="another copy of the dataset")
    a = p.parse_args(argv)
    try:
        if a.mode == "concept":
            side = concept(a.out_dir, a.name)
        else:
            side = real(a.segment, a.z, a.out_dir, a.data, a.window, a.size, a.center)
    except common.MediaError as exc:
        print(f"snap_media.py: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {side}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
