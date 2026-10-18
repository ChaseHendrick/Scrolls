#!/usr/bin/env python3
"""Encode frames (or a video) into a web MP4 and a two-pass palette GIF, under size limits, with sidecar JSON.

    python scripts/media/encode.py FRAMES/ --mp4 OUT.mp4 --gif OUT.gif --meta META.json
    python scripts/media/encode.py capture.mkv --gif OUT.gif --gif-width 960 --gif-fps 12

FRAMES/ holds PNG frames named in order (capture_web.py writes frame-00000.png, frame-00001.png, ...). The MP4 is
H.264, yuv420p, CRF 20, preset slow, with the index at the front (+faststart) so it starts playing at once. The GIF is
made in two passes: ffmpeg's palettegen with stats_mode=diff, then paletteuse with sierra2_4a dithering and
rectangle diff mode, then gifsicle -O3 with --lossy. When a file is over its limit (GIF 4 MB, MP4 10 MB by default),
the GIF is made again narrower, slower and lossier, and the MP4 at a higher CRF, until it fits or the steps run out
(exit 3). META.json gives the media label, alt text, caption and license that the sidecars record (common.py).
Needs ffmpeg and gifsicle on PATH.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import MediaError, check_meta, output_record, write_guard, write_sidecar  # noqa: E402

GIF_MAX_MB = 4.0
MP4_MAX_MB = 10.0
SCRIPTS = ("common.py", "encode.py")


def tool(name):
    path = shutil.which(name)
    if not path:
        raise MediaError(f"{name} is not on PATH; install it (macOS: brew install {name})")
    return path


def frames_input(src, fps):
    """ffmpeg input arguments for a folder of PNG frames or a video file."""
    src = Path(src)
    if src.is_dir():
        frames = sorted(src.glob("*.png"))
        if not frames:
            raise MediaError(f"no PNG frames in {src}")
        m = re.fullmatch(r"(.*?)(\d+)\.png", frames[0].name)
        if not m:
            raise MediaError(f"frame names must end in a number, such as frame-00000.png, not {frames[0].name}")
        pattern = f"{m.group(1)}%0{len(m.group(2))}d.png"
        return ["-framerate", str(fps), "-start_number", str(int(m.group(2))), "-i", str(src / pattern)], len(frames)
    if src.is_file():
        return ["-i", str(src)], None
    raise MediaError(f"no such frames folder or video: {src}")


def probe(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                          "stream=width,height,nb_read_frames:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True)
    try:
        info = json.loads(out.stdout)
        st = info["streams"][0]
        return {"width": int(st["width"]), "height": int(st["height"]),
                "frames": int(st.get("nb_read_frames") or 0),
                "seconds": round(float(info.get("format", {}).get("duration") or 0), 2)}
    except (ValueError, KeyError, IndexError):
        return {}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise MediaError(f"{Path(cmd[0]).name} failed: {r.stderr.strip()[-400:]}")


def encode_mp4(src, out, fps, crf, max_mb, width=None, log=print):
    ffmpeg = tool("ffmpeg")
    inp, _ = frames_input(src, fps)
    scale = f"scale={width}:-2:flags=lanczos" if width else "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos"
    for c in (crf, crf + 3, crf + 6, crf + 9):
        run([ffmpeg, "-y", "-loglevel", "error", *inp, "-vf", f"{scale},format=yuv420p", "-c:v", "libx264",
             "-preset", "slow", "-crf", str(c), "-movflags", "+faststart", "-an", str(out)])
        size = Path(out).stat().st_size
        if size <= max_mb * 1e6:
            return {"crf": c}
        log(f"encode: {out} is {size / 1e6:.1f} MB at CRF {c}, over {max_mb} MB; trying CRF {c + 3}")
    raise MediaError(f"{out} stays over {max_mb} MB; shorten the clip or lower its size")


def encode_gif(src, out, fps, gif_fps, width, lossy, max_mb, log=print):
    ffmpeg, gifsicle = tool("ffmpeg"), tool("gifsicle")
    inp, _ = frames_input(src, fps)
    steps = [(width, gif_fps, lossy), (width, max(8, gif_fps - 3), lossy + 30), (int(width * 0.85), max(8, gif_fps - 3),
             lossy + 50), (int(width * 0.7), 8, lossy + 80)]
    with tempfile.TemporaryDirectory() as tmp:
        palette, raw = Path(tmp) / "palette.png", Path(tmp) / "raw.gif"
        for w, f, lz in steps:
            chain = f"fps={f},scale={w}:-1:flags=lanczos"
            run([ffmpeg, "-y", "-loglevel", "error", *inp, "-vf", f"{chain},palettegen=stats_mode=diff:max_colors=256",
                 str(palette)])
            run([ffmpeg, "-y", "-loglevel", "error", *inp, "-i", str(palette), "-lavfi",
                 f"{chain}[x];[x][1:v]paletteuse=dither=sierra2_4a:diff_mode=rectangle", str(raw)])
            run([gifsicle, "-O3", f"--lossy={lz}", "-o", str(out), str(raw)])
            size = Path(out).stat().st_size
            if size <= max_mb * 1e6:
                return {"width": w, "fps": f, "lossy": lz}
            log(f"encode: {out} is {size / 1e6:.1f} MB at {w} px, {f} fps, lossy {lz}; over {max_mb} MB, trying smaller")
    raise MediaError(f"{out} stays over {max_mb} MB after every step; shorten the clip")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python scripts/media/encode.py", description=__doc__.split("\n")[0])
    p.add_argument("src", help="a folder of numbered PNG frames, or a video file")
    p.add_argument("--mp4", help="write an H.264 MP4 here")
    p.add_argument("--gif", help="write a GIF here")
    p.add_argument("--meta", help="JSON with label, alt, caption, license (and optional sources, release_id); "
                                  "writes a sidecar NAME.json next to each output")
    p.add_argument("--fps", type=float, default=30.0, help="frame rate of the PNG frames (default 30)")
    p.add_argument("--crf", type=int, default=20, help="H.264 quality, lower is better (default 20)")
    p.add_argument("--mp4-width", type=int, help="scale the MP4 to this width (default: the frames' width)")
    p.add_argument("--gif-fps", type=int, default=12, help="GIF frame rate (default 12)")
    p.add_argument("--gif-width", type=int, default=960, help="GIF width in pixels (default 960)")
    p.add_argument("--lossy", type=int, default=40, help="gifsicle --lossy level (default 40)")
    p.add_argument("--max-gif-mb", type=float, default=GIF_MAX_MB, help="GIF size limit in MB (default 4)")
    p.add_argument("--max-mp4-mb", type=float, default=MP4_MAX_MB, help="MP4 size limit in MB (default 10)")
    p.add_argument("--json", action="store_true", help="print what was written as JSON")
    args = p.parse_args(argv)
    if not args.mp4 and not args.gif:
        p.error("give --mp4, --gif or both")
    log = lambda msg: print(msg, file=sys.stderr)  # noqa: E731
    try:
        meta = check_meta(json.loads(Path(args.meta).read_text(encoding="utf-8"))) if args.meta else None
        written = []
        for out, kind in ((args.mp4, "mp4"), (args.gif, "gif")):
            if not out:
                continue
            if meta:
                write_guard(meta["label"], out)
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            if kind == "mp4":
                settings = encode_mp4(args.src, out, args.fps, args.crf, args.max_mp4_mb, args.mp4_width, log)
            else:
                settings = encode_gif(args.src, out, args.fps, args.gif_fps, args.gif_width, args.lossy,
                                      args.max_gif_mb, log)
            info = probe(out)
            rec = output_record(out, info.get("width"), info.get("height"), kind=kind,
                                seconds=info.get("seconds"), frames=info.get("frames"), settings=settings)
            written.append((Path(out), rec))
            log(f"encode: wrote {out} ({rec['bytes']} bytes)")
        if meta:
            # one sidecar per name: OUT.mp4 and OUT.gif share OUT.json
            cmd = "python scripts/media/encode.py " + " ".join(sys.argv[1:] if argv is None else argv)
            for stem in dict.fromkeys(path.with_suffix(".json") for path, _ in written):
                write_sidecar(stem, meta, [r for path, r in written if path.with_suffix(".json") == stem],
                              command=cmd, scripts=SCRIPTS)
        written = [r for _, r in written]
        if args.json:
            print(json.dumps(written, indent=2))
        return 0
    except MediaError as exc:
        print(f"encode: {exc}", file=sys.stderr)
        return 3 if "stays over" in str(exc) else 2
    except (OSError, ValueError) as exc:
        print(f"encode: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
