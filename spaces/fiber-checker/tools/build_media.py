"""Build the pictures of Fiber Checker's welcome page from the game's renders (public scrolls on no prize list).

  python3 tools/build_media.py [--run RUN_DIR] [--shot SCREENSHOT.png] [--frames FRAMES_DIR]

Writes into assets/ (on the Space only, never in git, docs/media/README.md):
  hero.webp           a mosaic of the clearest renders, for the page's hero
  pair-N-{on,scramble,shuffle,off}.webp   three patches with the controls the judge must beat
  map.png, tile-N.webp                    a fiber map and its clearest patches, from a fibercheck score folder (--run)
  ui.webp             a screenshot of the Check tab with a result (--shot), at most 1600 px wide
  howto-FLOW.gif, howto-*.webp            the How-to guides' GIFs and stills, from tools/record_howto.js (--frames)
  media.json          where every picture came from
Every picture is at most 1920 px and well under 4 MB.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent.parent
for p in (HERE, HERE.parent.parent / "scripts" / "fibercheck"):
    sys.path.insert(0, str(p))
import fibercheck as FC  # noqa: E402
from fcmodel import tile_shuffle  # noqa: E402

ASSETS = HERE / "assets"
# chosen by eye from a contact sheet of game.npz (build_game.py's order): clear crossing strands, no bright
# inclusions or empty gaps, every scroll shown; the judge's own scores follow each picture in media.json
HERO = [6, 97, 30, 61, 101, 0, 42, 87, 9, 113, 24, 64, 8, 102, 45, 83, 13, 100, 27, 56, 2, 116, 34, 94]
PAIRS = [6, 45, 61]


def grey(a, size=None):
    lo, hi = np.percentile(a, [1, 99])
    im = Image.fromarray((np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype(np.uint8))
    return im.resize((size, size), Image.BICUBIC) if size else im


def gif(frames, out, width=1100, limit=3.9e6):
    """One GIF from [(png, ms), ...] at `width` px, made narrower until it is under `limit` bytes."""
    while True:
        ims = []
        for f, _ in frames:
            im = Image.open(f).convert("RGB")
            ims.append(im.resize((width, round(im.height * width / im.width)), Image.LANCZOS))
        # one shared palette keeps the interface's colors steady from frame to frame
        pal = ims[-1].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        q = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in ims]
        q[0].save(out, save_all=True, append_images=q[1:], duration=[ms for _, ms in frames], loop=0,
                  optimize=True, disposal=1)
        if out.stat().st_size < limit or width <= 640:
            return width
        width -= 120


def frames_media(src, meta):
    """GIFs and stills of the How-to guides from record_howto.js's frames.json and shots."""
    flows = json.loads((src / "frames.json").read_text())
    for flow, frames in flows.items():
        w = gif([(src / f, ms) for f, ms in frames], ASSETS / f"howto-{flow}.gif")
        meta["pictures"][f"howto-{flow}.gif"] = f"interface recording of the {flow} guide at {w} px (public scrolls on no prize list)"
    for shot in ("result", "upload"):
        f = src / f"shot-{shot}.png"
        if f.is_file():
            im = Image.open(f).convert("RGB")
            if im.width > 1100:
                im = im.resize((1100, round(im.height * 1100 / im.width)), Image.LANCZOS)
            im.save(ASSETS / f"howto-{shot}.webp", quality=86)
            meta["pictures"][f"howto-{shot}.webp"] = f"interface screenshot ({shot}, PHerc0139 w030)"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", type=Path, help="a fibercheck score folder for the example map")
    ap.add_argument("--shot", type=Path, help="a screenshot of the Check tab with a result")
    ap.add_argument("--frames", type=Path, help="record_howto.js's output folder (frames.json and shots)")
    a = ap.parse_args()
    z = np.load(ASSETS / "game.npz")
    on, off, src = z["on"].astype(np.float64), z["off"].astype(np.float64), list(z["src"])
    judge = FC.LocalJudge(str(HERE / "weights" / "fibercheck-local.pt"))
    scr = [FC.phase_scramble(x, 7) for x in on]
    p, _ = judge.prefer([FC.to_input(x, x) for x in on], [FC.to_input(s, x) for s, x in zip(scr, on)])
    meta = {"note": "Renders of the Vesuvius Challenge open data (CC BY-NC 4.0) along open-data meshes of public "
                    "scrolls on no prize list, made by fibercheck's renderer. Not model output except map.png.",
            "pictures": {}}
    # hero: 8 x 3 tiles of 200 px = 1600 x 600
    cols, rows, t = 8, 3, 200
    hero = Image.new("L", (cols * t, rows * t))
    for k, i in enumerate(HERO[:cols * rows]):
        hero.paste(grey(on[i], t), ((k % cols) * t, (k // cols) * t))
    hero.save(ASSETS / "hero.webp", quality=82)
    meta["pictures"]["hero.webp"] = [f"{src[i]} (judge {p[i]:.2f})" for i in HERO[:cols * rows]]
    for n, i in enumerate(PAIRS):
        x = on[i]
        sh = tile_shuffle(x, 14, f"page:{i}") * x.std() + x.mean()
        for name, img in (("on", x), ("scramble", FC.phase_scramble(x, 7)), ("shuffle", sh), ("off", off[i])):
            grey(img, 320).save(ASSETS / f"pair-{n}-{name}.webp", quality=88)
        meta["pictures"][f"pair-{n}-*.webp"] = src[i]
    if a.run:
        shutil.copy2(a.run / "fiber_map.png", ASSETS / "map.png")
        rec = json.loads((a.run / "fiber.json").read_text())
        meta["pictures"]["map.png"] = {"model_output": True, "segment": rec.get("segment"), "ct": rec.get("ct"),
                                       "summary": rec["summary"]}
        for n, f in enumerate(sorted((a.run / "tiles").glob("*clearest*.png"))[:6]):
            Image.open(f).convert("L").save(ASSETS / f"tile-{n}.webp", quality=88)
        (ASSETS / "map-summary.json").write_text(json.dumps(rec["summary"]))
    if a.shot:
        im = Image.open(a.shot).convert("RGB")
        if im.width > 1600:
            im = im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS)
        im.save(ASSETS / "ui.webp", quality=85)
        meta["pictures"]["ui.webp"] = "interface screenshot of the Check tab with a finished check (PHerc0139 w030)"
    if a.frames:
        frames_media(a.frames, meta)
    (ASSETS / "media.json").write_text(json.dumps(meta, indent=1))
    for f in sorted(ASSETS.glob("*")):
        if f.suffix in (".webp", ".png", ".gif"):
            w, h = Image.open(f).size
            assert max(w, h) <= 1920 and f.stat().st_size < 4e6, f
            print(f"{f.name}: {w} x {h}, {f.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
