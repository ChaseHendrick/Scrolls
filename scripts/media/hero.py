#!/usr/bin/env python3
"""Make a release hero from a JSON recipe: a graded 1920 x 640 WebP, a 1200 x 630 social card and a sidecar JSON.

    python scripts/media/hero.py scripts/media/recipes/umbilicus.json --out-dir docs/assets/umbilicus
    python scripts/media/hero.py RECIPE.json --out-dir OUT --preview 0.25     # a quick small render, no card
    python scripts/media/hero.py RECIPE.json --check                           # validate the recipe only

The picture matches the repository's reference hero (docs/assets/README.md): 3:1, charcoal #171A1C, ivory #EEE7D9 and
copper #B77A54, ivory key light from the upper left, a copper rim, no text, WebP at quality 83, Lanczos-resized from a
render at twice the size. The card is the same picture cropped to 1200 x 630 with the title, a line of text and the
media label in Inter, for Hugging Face thumbnails and GitHub's social preview.

A recipe's "scene" is one of:
  {"kind": "procedural", "name": NAME, "params": {...}}   a scene from scenes.py (no scan pixels: a Concept
                                                          illustration, or a Synthetic demo for a screenshot scene)
  {"kind": "image", "path": PATH, "focus": [X, Y]}        an existing picture, cropped to 3:1 around focus (0 to 1)

Real data renders and model output are refused under any docs/assets/ folder (public Git holds no renders); make them
in Scrolls-private's docs/media/. Needs numpy and Pillow; the card needs the Inter font (or --font).
"""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import MediaError, check_meta, output_record, write_guard, write_sidecar  # noqa: E402

HERO_SIZE = (1920, 640)
CARD_SIZE = (1200, 630)
SUPERSAMPLE = 2
WEBP_QUALITY = 83
CARD_QUALITY = 88
HERO_MAX_BYTES = 300_000
FONT_DIRS = ("/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/inter", "/Library/Fonts",
             str(Path.home() / "Library/Fonts"), "/usr/share/fonts")
SCRIPTS = ("common.py", "hero.py", "scene.py", "scenes.py")
RECIPE_KEYS = {"name", "release_id", "label", "alt", "caption", "license", "scene", "grade", "card", "sources",
               "data", "seed"}


def load_recipe(path):
    recipe = json.loads(Path(path).read_text(encoding="utf-8"))
    unknown = set(recipe) - RECIPE_KEYS
    if unknown:
        raise MediaError(f"unknown recipe keys {sorted(unknown)}")
    for key in ("name", "scene"):
        if key not in recipe:
            raise MediaError(f"the recipe needs {key!r}")
    if not isinstance(recipe["name"], str) or not recipe["name"].replace("-", "").isalnum() \
            or recipe["name"] != recipe["name"].lower():
        raise MediaError("name is lowercase letters, digits and hyphens, such as umbilicus-hero")
    check_meta(recipe)
    scene = recipe["scene"]
    if not isinstance(scene, dict) or scene.get("kind") not in ("procedural", "image"):
        raise MediaError('scene.kind is "procedural" or "image"')
    if scene["kind"] == "procedural" and recipe["label"] not in ("Concept illustration", "Synthetic demo"):
        raise MediaError("a procedural scene is a Concept illustration or a Synthetic demo")
    return recipe


# ---------------------------------------------------------------------------------------------------------------------
# Grading


def grade(rgb_linear, g=None):
    """Tone map linear RGB and give it the reference look. Returns sRGB floats in [0, 1]."""
    import numpy as np

    from scene import COPPER, IVORY, CHARCOAL, EMBER, blur, smoothstep, to_srgb, wide_blur

    g = dict(g or {})
    exposure = g.get("exposure", 1.0)
    x = np.maximum(rgb_linear * exposure, 0)
    # ACES filmic fit (Narkowicz 2015).
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    x = np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0, 1)
    img = to_srgb(x)
    h, w = img.shape[:2]
    lum = img @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    # Split tone toward the palette: shadows to charcoal and ember, highlights to ivory.
    duo = g.get("duotone", 0.18)
    if duo:
        stops = np.array([0.0, 0.33, 0.70, 1.0], dtype=np.float32)
        cols = np.stack([CHARCOAL, EMBER, COPPER, IVORY]).astype(np.float32)
        ramp = np.stack([np.interp(lum, stops, cols[:, k]) for k in range(3)], axis=-1)
        img = img * (1 - duo) + ramp * duo
    # Ivory key light falloff from the upper left, darker toward the right.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xs, ys = xx / w, yy / h
    key = g.get("key", 0.10)
    if key:
        r = np.sqrt(((xs - 0.05) / 0.6) ** 2 + ((ys + 0.1) / 1.0) ** 2)
        img = img + key * np.exp(-r * r * 2.0)[..., None] * IVORY * (1 - img)
    rim = g.get("rim", 0.12)
    if rim:
        gy, gx = np.gradient(blur(lum, w / 1200))
        edges = np.clip(np.hypot(gx, gy) * w / 60, 0, 1)
        edges = wide_blur(edges, w / 700) * smoothstep(0.08, 0.5, lum)
        img = img + rim * edges[..., None] * COPPER
    fade = g.get("fade_right", 0.0)
    if fade:
        t = smoothstep(1 - fade, 1.0, xs)[..., None]
        img = img * (1 - t) + CHARCOAL * t
    vig = g.get("vignette", 0.35)
    if vig:
        r = np.sqrt(((xs - 0.45) / 0.75) ** 2 + ((ys - 0.45) / 0.85) ** 2)
        t = np.clip(r - 0.55, 0, 1)[..., None] * vig
        img = img * (1 - t) + CHARCOAL * t
    lift = g.get("black", 1.0)          # keep the darkest pixels at the charcoal of the page, not pure black
    if lift:
        img = np.maximum(img, CHARCOAL * 0.55 * lift + img * (1 - 0.55 * lift))
    return np.clip(img, 0, 1).astype(np.float32)


def add_grain(img_u8, amount, seed):
    import numpy as np

    if not amount:
        return img_u8
    rng = np.random.default_rng(seed + 1)
    noise = rng.normal(0, amount * 255, img_u8.shape[:2]).astype(np.float32)[..., None]
    return np.clip(img_u8.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def cover_crop(img, size, focus=(0.5, 0.5)):
    """Crop a PIL image to the aspect of size around focus, then resize with Lanczos."""
    from PIL import Image

    w, h = img.size
    tw, th = size
    if w / h > tw / th:
        cw, ch = round(h * tw / th), h
    else:
        cw, ch = w, round(w * th / tw)
    x0 = min(max(round(focus[0] * w - cw / 2), 0), w - cw)
    y0 = min(max(round(focus[1] * h - ch / 2), 0), h - ch)
    return img.crop((x0, y0, x0 + cw, y0 + ch)).resize(size, Image.LANCZOS)


# ---------------------------------------------------------------------------------------------------------------------
# The card


def find_font(name, override=None):
    if override:
        return override
    for d in FONT_DIRS:
        p = Path(d)
        if not p.is_dir():
            continue
        hits = sorted(p.rglob(name))
        if hits:
            return str(hits[0])
    return None


def wrap(draw, text, font, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def make_card(hero_full, recipe, font_override=None):
    """The 1200 x 630 social card: the hero, darkened behind the text, with the title, a line and the label."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from scene import CHARCOAL, COPPER, IVORY

    card = recipe.get("card") or {}
    focus = card.get("focus", [0.62, 0.5])
    img = cover_crop(hero_full, CARD_SIZE, focus)
    arr = np.asarray(img).astype(np.float32) / 255
    w, h = CARD_SIZE
    xs = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    shade = np.clip(1.35 - xs * 1.45, 0, 0.9) * np.clip(0.55 + ys * 0.7, 0, 1)
    arr = arr * (1 - shade) + CHARCOAL * shade
    img = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    semibold = find_font("Inter*SemiBold.otf", font_override) or find_font("Inter*.ttf", font_override)
    regular = find_font("Inter-Regular.otf", font_override) or semibold
    medium = find_font("Inter-Medium.otf", font_override) or regular
    if not semibold:
        raise MediaError("no Inter font found for the card; install Inter or give --font FILE")
    ivory = tuple(int(c * 255 + 0.5) for c in IVORY)
    copper = tuple(int(c * 255 + 0.5) for c in COPPER)
    soft = tuple(int(c * 255 * 0.78 + 0.5) for c in IVORY)
    x = 64
    kicker = card.get("kicker", "SCROLLS  |  RELEASED TOOL")
    draw.text((x, 70), kicker, font=ImageFont.truetype(medium, 22), fill=copper)
    title_font = ImageFont.truetype(semibold, card.get("title_size", 66))
    y = 118
    for line in wrap(draw, card.get("title", recipe["name"]), title_font, 640):
        draw.text((x, y), line, font=title_font, fill=ivory)
        y += int(title_font.size * 1.12)
    sub_font = ImageFont.truetype(regular, 28)
    y += 14
    for line in wrap(draw, card.get("subtitle", ""), sub_font, 560)[:4]:
        draw.text((x, y), line, font=sub_font, fill=soft)
        y += 40
    small = ImageFont.truetype(medium, 20)
    draw.text((x, h - 64), recipe["label"], font=small, fill=copper)
    url = card.get("url", "github.com/ChaseHendrick/Scrolls")
    draw.text((w - 64 - draw.textlength(url, font=small), h - 64), url, font=small, fill=soft)
    draw.line([(x, 104), (x + 46, 104)], fill=copper, width=3)
    return img


# ---------------------------------------------------------------------------------------------------------------------


def render_source(recipe, size, log):
    """The recipe's scene as a PIL image of `size`, graded (procedural) or cropped (image)."""
    import numpy as np
    from PIL import Image

    scene = recipe["scene"]
    if scene["kind"] == "image":
        src = Path(scene["path"])
        img = Image.open(src).convert("RGB")
        img = cover_crop(img, size, scene.get("focus", (0.5, 0.5)))
        if recipe.get("grade"):
            arr = np.asarray(img).astype(np.float32) / 255
            from scene import to_linear
            img = Image.fromarray((grade(to_linear(arr), dict(recipe["grade"], exposure=recipe["grade"].get(
                "exposure", 1.6))) * 255 + 0.5).astype(np.uint8))
        return img
    import scenes
    from scene import render

    t0 = time.time()
    built = scenes.build(scene["name"], scene.get("params", {}), size[0], size[1], seed=recipe.get("seed", 0))
    lin = render(built, seed=recipe.get("seed", 0), progress=log)
    log(f"rendered {size[0]} x {size[1]} in {time.time() - t0:.1f} s")
    srgb = grade(lin, recipe.get("grade"))
    return Image.fromarray((srgb * 255 + 0.5).astype(np.uint8))


def make(recipe_path, out_dir, preview=None, font=None, quiet=False):
    """Make the hero, card and sidecar of one recipe. Returns the sidecar record."""
    from PIL import Image

    recipe = load_recipe(recipe_path)
    out_dir = Path(out_dir)
    write_guard(recipe["label"], out_dir / f"{recipe['name']}.webp")
    out_dir.mkdir(parents=True, exist_ok=True)

    def log(msg):
        if not quiet:
            print(f"hero: {recipe['name']}: {msg}", file=sys.stderr)

    if preview:
        size = (int(HERO_SIZE[0] * preview) // 2 * 2, int(HERO_SIZE[1] * preview) // 2 * 2)
        img = render_source(recipe, (size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE), log).resize(size, Image.LANCZOS)
        path = out_dir / f"{recipe['name']}-preview.png"
        img.save(path)
        return {"preview": str(path), "width": size[0], "height": size[1]}
    big = (HERO_SIZE[0] * SUPERSAMPLE, HERO_SIZE[1] * SUPERSAMPLE)
    full = render_source(recipe, big, log)
    import numpy as np

    hero = full.resize(HERO_SIZE, Image.LANCZOS)
    grain = (recipe.get("grade") or {}).get("grain", 0.006)
    hero = Image.fromarray(add_grain(np.asarray(hero), grain, recipe.get("seed", 0)))
    hero_path = out_dir / f"{recipe['name']}.webp"
    quality = WEBP_QUALITY
    hero.save(hero_path, "WEBP", quality=quality, method=6)
    while hero_path.stat().st_size > HERO_MAX_BYTES and quality > 60:
        quality -= 5
        hero.save(hero_path, "WEBP", quality=quality, method=6)
        log(f"over {HERO_MAX_BYTES} bytes; saved again at quality {quality}")
    outputs = [output_record(hero_path, *HERO_SIZE, kind="hero", format="webp", quality=quality)]
    if recipe.get("card") is not None:
        card = make_card(full, recipe, font)
        card = Image.fromarray(add_grain(np.asarray(card), grain * 0.6, recipe.get("seed", 0) + 7))
        card_path = out_dir / f"{recipe['name'].removesuffix('-hero')}-card.jpg"
        card.save(card_path, "JPEG", quality=CARD_QUALITY, optimize=True, progressive=True)
        outputs.append(output_record(card_path, *CARD_SIZE, kind="social card", format="jpeg", quality=CARD_QUALITY))
    inputs = []
    if recipe["scene"]["kind"] == "image":
        inputs.append(output_record(recipe["scene"]["path"]) | {"file": str(recipe["scene"]["path"])})
    params = recipe["scene"].get("params") or {}
    for extra in list(params.get("inputs", [])) + [panel["image"] for panel in params.get("panels", [])]:
        inputs.append(output_record(extra) | {"file": str(extra)})
    meta = dict(recipe)
    sidecar = out_dir / f"{recipe['name']}.json"
    command = f"python scripts/media/hero.py {recipe_path} --out-dir {out_dir}"
    record = write_sidecar(sidecar, meta, outputs, command=command, scripts=SCRIPTS, inputs=inputs,
                           extra={"recipe": recipe})
    log(f"wrote {hero_path} ({outputs[0]['bytes']} bytes)" + (f" and {outputs[1]['file']}" if len(outputs) > 1 else ""))
    return record


def main(argv=None):
    p = argparse.ArgumentParser(prog="python scripts/media/hero.py", description=__doc__.split("\n")[0])
    p.add_argument("recipe", nargs="+", help="recipe JSON files (scripts/media/recipes/*.json)")
    p.add_argument("--out-dir", help="folder for the hero, card and sidecar (required unless --check)")
    p.add_argument("--preview", type=float, metavar="SCALE",
                   help="write only NAME-preview.png at SCALE times 1920 x 640, ungrained, with no card or sidecar")
    p.add_argument("--check", action="store_true", help="validate the recipes and exit; render nothing")
    p.add_argument("--font", help="a font file for the card instead of Inter")
    p.add_argument("--json", action="store_true", help="print the sidecar records as JSON on stdout")
    p.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
    args = p.parse_args(argv)
    try:
        if args.check:
            for path in args.recipe:
                load_recipe(path)
            print(json.dumps({"recipes": len(args.recipe), "ok": True}))
            return 0
        if not args.out_dir:
            p.error("--out-dir is required unless --check")
        records = [make(path, args.out_dir, args.preview, args.font, args.quiet) for path in args.recipe]
        if args.json:
            print(json.dumps(records, indent=2))
        return 0
    except (MediaError, OSError, ValueError, KeyError) as exc:
        print(f"hero: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
