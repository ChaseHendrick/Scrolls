"""Record docs/assets/quickstart-terminal.gif: real commands from docs/QUICKSTART.md and their real text output.

Runs each command below in a scratch folder, captures what it prints, and draws it as terminal frames with Pillow.
The GIF shows text only, never scan imagery (public repository rule). Needs Pillow and the quick start's installs.

  python scripts/quickstart/terminal_gif.py [--out docs/assets/quickstart-terminal.gif] [--work work/quickstart-gif]
"""

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
COLS, ROWS, SIZE = 92, 20, 13
FG, BG, PROMPT = (220, 220, 210), (24, 26, 30), (120, 200, 140)


def commands(work):
    py = shlex.quote(sys.executable)
    s = "https://huggingface.co/spaces/SharpMeow/unroll/resolve/main"
    return [
        ("python scripts/quickstart/first_look.py all",
         f"{py} {ROOT}/scripts/quickstart/first_look.py all --out {work}"),
        ("python inkbench.py compare w046_gpu.png --segment w046 --model ink_9um -o ink9um.json",
         f"cd {work} && curl -fsSLO {s}/tools/inkbench.py && curl -fsSLO {s}/data/bench/w046_gpu.png && "
         f"{py} inkbench.py compare w046_gpu.png --segment w046 --model ink_9um -o ink9um.json"),
        ("python inkbench.py compare w046_ct.png --segment w046 --model x-ray-floor -o floor.json",
         f"cd {work} && curl -fsSLO {s}/data/bench/w046_ct.png && "
         f"{py} inkbench.py compare w046_ct.png --segment w046 --model x-ray-floor -o floor.json"),
        ("python inkbench.py rank ink9um.json floor.json --metric ap",
         f"cd {work} && {py} inkbench.py rank ink9um.json floor.json --metric ap"),
    ]


def wrap(line):
    return [line[i:i + COLS] for i in range(0, max(len(line), 1), COLS)]


def frame(lines, font, cw, ch):
    img = Image.new("P", (COLS * cw + 24, ROWS * ch + 20))
    img.putpalette(list(BG) + list(FG) + list(PROMPT) + [0, 0, 0] * 253)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines[-ROWS:]):
        if line.startswith("$ "):
            d.text((12, 10 + i * ch), "$", font=font, fill=2)
            d.text((12 + 2 * cw, 10 + i * ch), line[2:], font=font, fill=1)
        else:
            d.text((12, 10 + i * ch), line, font=font, fill=1)
    return img


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=ROOT / "docs/assets/quickstart-terminal.gif")
    p.add_argument("--work", type=Path, default=ROOT / "work/quickstart-gif")
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(FONT, SIZE)
    cw = round(font.getlength("M"))
    ch = SIZE + 5
    screen, frames, times = [], [], []
    for shown, real in commands(a.work.resolve()):
        out = subprocess.run(real, shell=True, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True).stdout
        out = out.replace(str(a.work.resolve()), "work/quickstart")
        typed = "$ "
        for k in range(0, len(shown), 6):
            typed = "$ " + shown[:k + 6]
            frames.append(frame(screen + wrap(typed), font, cw, ch))
            times.append(40)
        screen += wrap(typed)
        frames[-1] = frame(screen, font, cw, ch)
        times[-1] = 500
        for line in out.rstrip("\n").splitlines():
            screen += wrap(line)
        frames.append(frame(screen, font, cw, ch))
        times.append(2600)
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=times, loop=0, optimize=True)
    print(f"wrote {a.out}: {len(frames)} frames, {a.out.stat().st_size // 1000} kB")


if __name__ == "__main__":
    main()
