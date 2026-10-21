#!/usr/bin/env python3
"""Render a scripted terminal session, title cards, a concept diagram and side-by-side panels into PNG frames.

    python scripts/media/termcast.py CAST.json --out-dir FRAMES [--fps 12] [--size 1280x720] [--srt OUT.srt]
    python scripts/media/termcast.py CAST.json --still OUT.png --at SECONDS --meta META.json

CAST.json lists scenes, each with "seconds", a media "label" shown in the corner, an optional burned-in "caption" (at
most 2 lines of 42 characters, the Netflix timed-text limits) and a "type": terminal (commands typed at a steady speed,
then their real output), card (a kicker, a title and lines), image (a picture from docs/assets/ or docs/images/ with a
slow zoom), diagram (the AutoPipeline and VC3D loop, drawn) or split (two panels, the right one revealed at
"reveal_at" seconds). Terminal text is pasted from real runs; this script draws it, it never runs a command. Frames
go to encode.py for the GIF and MP4 (pass this command with --made-with so the sidecar records it); --still writes one
PNG with its own sidecar. Needs Pillow and the DejaVu Sans Mono and Inter fonts.
"""

import argparse
import json
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import ROOT, MediaError, check_meta, input_guard, output_record, size_guard, write_guard, write_sidecar  # noqa: E402

CHARCOAL, PANEL, IVORY, DIM, COPPER, GREEN = "#171A1C", "#202427", "#EEE7D9", "#9A958C", "#B77A54", "#6FBF8E"
MONO = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/Library/Fonts/DejaVuSansMono.ttf"]
SANS = ["/usr/share/fonts/opentype/inter/Inter-Regular.otf", "/Library/Fonts/Inter-Regular.otf"]
SANS_BOLD = ["/usr/share/fonts/opentype/inter/Inter-Bold.otf", "/Library/Fonts/Inter-Bold.otf"]
TYPE_CPS = 30.0          # characters typed per second
LINES_PS = 40.0          # output lines shown per second
CAPTION_CHARS, CAPTION_LINES = 42, 2
SCRIPTS = ("common.py", "termcast.py")


def font(paths, size):
    for p in paths:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    raise MediaError(f"none of these fonts is installed: {', '.join(paths)}")


class Canvas:
    def __init__(self, w, h):
        self.w, self.h, self.s = w, h, h / 720.0
        self.mono = font(MONO, round(19 * self.s))
        self.sans = font(SANS, round(26 * self.s))
        self.small = font(SANS, round(18 * self.s))
        self.bold = font(SANS_BOLD, round(46 * self.s))
        self.mid = font(SANS_BOLD, round(28 * self.s))

    def px(self, v):
        return round(v * self.s)


def caption_lines(text):
    lines = textwrap.wrap(text, CAPTION_CHARS) if text else []
    if len(lines) > CAPTION_LINES:
        raise MediaError(f"caption over {CAPTION_LINES} lines of {CAPTION_CHARS} characters: {text!r}")
    return lines


def chrome(c, img, scene):
    d = ImageDraw.Draw(img)
    label = scene.get("label")
    if label:
        tw = d.textlength(label, font=c.small)
        x0, y0 = c.w - tw - c.px(40), c.px(18)
        d.rounded_rectangle([x0 - c.px(12), y0 - c.px(6), x0 + tw + c.px(12), y0 + c.px(28)], radius=c.px(8),
                            fill=PANEL, outline=COPPER, width=max(1, c.px(1.5)))
        d.text((x0, y0), label, fill=IVORY, font=c.small)
    lines = caption_lines(scene.get("caption"))
    if lines:
        lh = c.px(34)
        top = c.h - c.px(24) - lh * len(lines) - c.px(16)
        d.rectangle([0, top, c.w, c.h], fill="#0E1011")
        for i, line in enumerate(lines):
            tw = d.textlength(line, font=c.sans)
            d.text(((c.w - tw) / 2, top + c.px(12) + i * lh), line, fill=IVORY, font=c.sans)


def draw_terminal(c, img, scene, t):
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = c.px(40), c.px(60), c.w - c.px(40), c.h - c.px(130)
    d.rounded_rectangle([x0, y0, x1, y1], radius=c.px(14), fill="#0F1214", outline="#33383C", width=c.px(2))
    for i, col in enumerate(("#E0675B", "#E5B454", "#6FBF8E")):
        d.ellipse([x0 + c.px(18 + 22 * i), y0 + c.px(14), x0 + c.px(32 + 22 * i), y0 + c.px(28)], fill=col)
    d.text((x0 + c.px(100), y0 + c.px(10)), scene.get("title", "Terminal"), fill=DIM, font=c.small)
    shown, clock = [], 0.0
    for step in scene["steps"]:
        cmd = step.get("cmd")
        if cmd is not None:
            dur = len(cmd) / TYPE_CPS
            if t < clock:
                break
            n = len(cmd) if t >= clock + dur else int((t - clock) * TYPE_CPS)
            shown.append(("cmd", cmd[:n] + ("_" if n < len(cmd) else "")))
            clock += dur + 0.25
        if t < clock:
            break
        out = step.get("out", [])
        n = min(len(out), int((t - clock) * LINES_PS) + 1) if t >= clock else 0
        shown += [("out", line) for line in out[:n]]
        clock += len(out) / LINES_PS + float(step.get("pause", 0.8))
    lh = c.px(25)
    rows = int((y1 - y0 - c.px(60)) / lh)
    cols = int((x1 - x0 - c.px(40)) / d.textlength("M", font=c.mono))
    wrapped = []
    for kind, text in shown:
        prefix = "$ " if kind == "cmd" else ""
        pieces = textwrap.wrap(prefix + text, cols, drop_whitespace=False, replace_whitespace=False) or [prefix]
        wrapped += [(kind, p, i == 0) for i, p in enumerate(pieces)]
    for i, (kind, text, first) in enumerate(wrapped[-rows:]):
        y = y0 + c.px(46) + i * lh
        x = x0 + c.px(20)
        if kind == "cmd" and first:
            d.text((x, y), "$", fill=COPPER, font=c.mono)
            d.text((x + d.textlength("$ ", font=c.mono), y), text[2:], fill=IVORY, font=c.mono)
        else:
            color = GREEN if text.strip() in ("DEMO PASS",) or text.strip().endswith(" done") else (
                IVORY if kind == "cmd" else "#C9C3B8")
            d.text((x, y), text, fill=color, font=c.mono)


def draw_card(c, img, scene, t):
    d = ImageDraw.Draw(img)
    y = c.px(150)
    if scene.get("kicker"):
        d.text((c.px(90), y), scene["kicker"], fill=COPPER, font=c.mid)
        y += c.px(56)
    for line in textwrap.wrap(scene.get("title", ""), 38):
        d.text((c.px(90), y), line, fill=IVORY, font=c.bold)
        y += c.px(62)
    y += c.px(18)
    for i, line in enumerate(scene.get("lines", [])):
        if t >= i * float(scene.get("stagger", 0.0)):
            f = c.mono if line.startswith("$ ") else c.sans
            d.text((c.px(90), y), line, fill=IVORY if line.startswith("$ ") else "#D6D0C5", font=f)
        y += c.px(40)


def draw_image(c, img, scene, t):
    src = ROOT / scene["src"]
    pic = Image.open(src).convert("RGB")
    z0, z1 = scene.get("zoom", [1.0, 1.08])
    z = z0 + (z1 - z0) * min(1.0, t / max(0.1, float(scene["seconds"])))
    box_w, box_h = c.w - c.px(80), c.h - c.px(170)
    scale = min(box_w / pic.width, box_h / pic.height) * z
    pic = pic.resize((max(1, round(pic.width * scale)), max(1, round(pic.height * scale))), Image.LANCZOS)
    cx, cy = c.w // 2, c.px(60) + box_h // 2
    left, top = cx - pic.width // 2, cy - pic.height // 2
    crop = pic.crop((max(0, -left), max(0, -top), max(0, -left) + min(pic.width, box_w + c.px(80)),
                     max(0, -top) + min(pic.height, box_h)))
    img.paste(crop, (max(0, left), max(c.px(60), top)))


def arrow(d, a, b, c, color):
    d.line([a, b], fill=color, width=c.px(4))
    import math
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (-1, 1):
        d.line([b, (b[0] - c.px(18) * math.cos(ang + s * 0.45), b[1] - c.px(18) * math.sin(ang + s * 0.45))],
               fill=color, width=c.px(4))


def draw_diagram(c, img, scene, t):
    d = ImageDraw.Draw(img)
    boxes = {"VC3D": (c.px(110), c.px(190)), "AutoPipeline": (c.w - c.px(470), c.px(190))}
    bw, bh = c.px(360), c.px(150)
    subs = {"VC3D": "villa's viewer and editor", "AutoPipeline": "plans, runs and checks"}
    for name, (x, y) in boxes.items():
        d.rounded_rectangle([x, y, x + bw, y + bh], radius=c.px(18), fill=PANEL, outline=COPPER, width=c.px(3))
        tw = d.textlength(name, font=c.mid)
        d.text((x + (bw - tw) / 2, y + c.px(38)), name, fill=IVORY, font=c.mid)
        sw = d.textlength(subs[name], font=c.small)
        d.text((x + (bw - sw) / 2, y + c.px(88)), subs[name], fill=DIM, font=c.small)
    (vx, vy), (ax, ay) = boxes["VC3D"], boxes["AutoPipeline"]
    top_y, bot_y = vy + c.px(45), vy + bh - c.px(45)
    steps = scene.get("steps") or ["focus point and scan", "accepted surfaces and seed points"]
    if t >= 0.3:
        arrow(d, (vx + bw + c.px(10), top_y), (ax - c.px(10), top_y), c, COPPER)
        tw = d.textlength(steps[0], font=c.small)
        d.text(((vx + bw + ax - tw) / 2, top_y - c.px(34)), steps[0], fill=IVORY, font=c.small)
    if t >= 1.2:
        arrow(d, (ax - c.px(10), bot_y), (vx + bw + c.px(10), bot_y), c, GREEN)
        tw = d.textlength(steps[1], font=c.small)
        d.text(((vx + bw + ax - tw) / 2, bot_y + c.px(10)), steps[1], fill=IVORY, font=c.small)
    y = vy + bh + c.px(50)
    for i, line in enumerate(scene.get("lines", [])):
        if t >= 1.8 + 0.4 * i:
            d.text((c.px(110), y), line, fill="#D6D0C5", font=c.mono if line.startswith("$ ") else c.sans)
        y += c.px(38)


def draw_split(c, img, scene, t):
    d = ImageDraw.Draw(img)
    gap, top, bottom = c.px(30), c.px(70), c.h - c.px(140)
    half = (c.w - c.px(80) - gap) // 2
    for side, x in (("left", c.px(40)), ("right", c.px(40) + half + gap)):
        panel = scene[side]
        if side == "right" and t < float(scene.get("reveal_at", 0)):
            continue
        d.rounded_rectangle([x, top, x + half, bottom], radius=c.px(14), fill=PANEL,
                            outline=COPPER if side == "right" else "#3A3F43", width=c.px(2))
        d.text((x + c.px(24), top + c.px(20)), panel["title"], fill=IVORY, font=c.mid)
        if panel.get("subtitle"):
            d.text((x + c.px(24), top + c.px(60)), panel["subtitle"], fill=DIM, font=c.small)
        y = top + c.px(104)
        for line in panel.get("lines", []):
            for piece in textwrap.wrap(line, int((half - c.px(48)) / d.textlength("M", font=c.mono))) or [""]:
                d.text((x + c.px(24), y), piece, fill="#D6D0C5", font=c.mono)
                y += c.px(25)


DRAW = {"terminal": draw_terminal, "card": draw_card, "image": draw_image, "diagram": draw_diagram,
        "split": draw_split}


def load_cast(path):
    cast = json.loads(Path(path).read_text(encoding="utf-8"))
    scenes = cast.get("scenes") or []
    if not scenes:
        raise MediaError(f"{path} has no scenes")
    for i, s in enumerate(scenes):
        if s.get("type") not in DRAW:
            raise MediaError(f"scene {i}: type must be one of {', '.join(DRAW)}")
        if float(s.get("seconds", 0)) <= 0:
            raise MediaError(f"scene {i}: seconds must be above 0")
        caption_lines(s.get("caption"))
    return cast


def frame(c, scene, t):
    img = Image.new("RGB", (c.w, c.h), CHARCOAL)
    DRAW[scene["type"]](c, img, scene, t)
    chrome(c, img, scene)
    return img


def timeline(cast):
    t, out = 0.0, []
    for s in cast["scenes"]:
        out.append((t, t + float(s["seconds"]), s))
        t += float(s["seconds"])
    return out


def srt_time(sec):
    ms = round(sec * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(cast, path):
    rows, n = [], 0
    for start, end, s in timeline(cast):
        lines = caption_lines(s.get("caption"))
        if lines:
            n += 1
            rows.append(f"{n}\n{srt_time(start)} --> {srt_time(end)}\n" + "\n".join(lines) + "\n")
    Path(path).write_text("\n".join(rows), encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("cast", help="the cast JSON")
    p.add_argument("--out-dir", help="write frame-00000.png, frame-00001.png, ... here")
    p.add_argument("--fps", type=float, default=12.0, help="frames per second (default 12)")
    p.add_argument("--size", default="1280x720", help="WIDTHxHEIGHT (default 1280x720)")
    p.add_argument("--srt", help="also write the captions as an .srt file")
    p.add_argument("--still", help="write one PNG instead of frames")
    p.add_argument("--at", type=float, default=0.0, help="with --still: the time in seconds (default 0)")
    p.add_argument("--meta", help="with --still: label, alt, caption and license for its sidecar")
    args = p.parse_args(argv)
    try:
        w, h = (int(v) for v in args.size.lower().split("x"))
        cast = load_cast(args.cast)
        c = Canvas(w, h)
        inputs = [s["src"] for s in cast["scenes"] if s["type"] == "image"]
        if args.srt:
            write_srt(cast, args.srt)
        if args.still:
            meta = json.loads(Path(args.meta).read_text()) if args.meta else None
            if meta:
                check_meta(meta)
            write_guard(meta["label"] if meta else None, args.still, meta)
            input_guard([ROOT / i for i in inputs], args.still, label=meta["label"] if meta else None)
            for start, end, s in timeline(cast):
                if start <= args.at < end:
                    frame(c, s, args.at - start).save(args.still, optimize=True)
                    break
            else:
                raise MediaError(f"--at {args.at} is past the cast's end")
            size_guard(args.still, w)
            if meta:
                write_sidecar(Path(args.still).with_suffix(".json"), meta, [output_record(args.still, w, h, kind="png")],
                              command=f"python scripts/media/termcast.py {Path(args.cast).resolve().relative_to(ROOT).as_posix()}"
                                      f" --still {Path(args.still).name} --at {args.at:g} --size {args.size}"
                                      f" --meta {Path(args.meta).resolve().relative_to(ROOT).as_posix()}",
                              scripts=SCRIPTS, inputs=inputs)
            print(f"wrote {args.still}")
            return 0
        if not args.out_dir:
            raise MediaError("give --out-dir for frames or --still for one picture")
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for start, end, s in timeline(cast):
            k = 0
            while start + k / args.fps < end - 1e-9:
                frame(c, s, k / args.fps).save(out / f"frame-{n:05d}.png", compress_level=1)
                k, n = k + 1, n + 1
        print(f"wrote {n} frames ({n / args.fps:.1f} s at {args.fps:g} fps) to {out}")
        return 0
    except (MediaError, OSError, ValueError, KeyError) as exc:
        print(f"termcast: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
