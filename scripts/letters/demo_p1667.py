"""Try the Greek letter reader on a public ink map in a few minutes on a laptop CPU.

Downloads the small JPEG (8 times downsampled, about 3.5 MB) of one PHerc. 1667 segment's 2.4 um
ink-detection map from the open-data bucket, averages it 2 by 2 to the reader's grid (about 38 um
per pixel, where PHerc. 1667's letters are about 86 pixels tall; this matches the full map cut by
16 to a correlation of 0.99998), reads it, and writes:

  OUT/<segment>.json         every line's letters, boxes and confidences, with the controls
  OUT/<segment>-overlay.png  the map with the letters drawn on it (needs Pillow)
  and a text summary on screen.

PHerc. 1667's Greek text is published (arXiv 2606.29085), so the letters can be checked against
the edition. Every string is model output, a hypothesis for a person to check, not a reading.

  python scripts/letters/demo_p1667.py [--segment w013] [--weights letters-v2-ccby] [--out DIR]
                                       [--crop Y0 Y1 X0 X1] [--letter-px 86|auto] [--lm LM.npz]

Needs numpy and Pillow. --weights takes a file or a released model name (kit/data/letter-weights.json),
resolved (downloaded once, SHA-256 checked) before the map. A map already in OUT is used as it is,
with no listing of the bucket; its bucket address is kept beside it in OUT/<segment>-ds8.json.
The result records file names and public addresses only, never a local folder.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit import letterread as R  # noqa: E402
from p1667_fetch import BUCKET, download, keys, segment_prefix  # noqa: E402

LETTER_PX = 86.0   # PHerc. 1667 letter height on the 38 um grid (median of the six labeled segments)


def small_map(seg, cache):
    """The segment's 8x downsampled 2.4 um map, averaged 2 by 2: (float32 array on the 38 um grid, its bucket URL).

    A JPEG already in the cache folder is used without listing the bucket (download() only writes
    complete files); its URL comes from the note written beside it, None when there is none."""
    from PIL import Image
    dest = Path(cache) / f"{seg}-ds8.jpg"
    note = dest.with_suffix(".json")
    if dest.exists() and dest.stat().st_size > 0:
        try:
            url = json.loads(note.read_text(encoding="utf-8")).get("url")
        except (OSError, ValueError, AttributeError):
            url = None
    else:
        pre = segment_prefix(seg, keys("PHerc1667/segments/", delimiter=True))
        jpg = [k for k in keys(pre + "ink-detection/downsampled/") if re.search(r"2\.399um.*stride128-ds8\.jpg$", k)]
        if len(jpg) != 1:
            raise SystemExit(f"{seg}: {len(jpg)} small 2.4 um maps in the bucket")
        download(jpg[0], dest)
        url = f"{BUCKET}/{jpg[0]}"
        note.write_text(json.dumps({"segment": seg, "url": url}) + "\n", encoding="utf-8")
    Image.MAX_IMAGE_PIXELS = None
    a = np.asarray(Image.open(dest).convert("L"), np.float32) / 255.0
    H, W = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
    return a[:H, :W].reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)), url


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--segment", default="w013", help="PHerc. 1667 segment id, w011 to w041 (default w013)")
    ap.add_argument("--weights", default=R.DEFAULT_WEIGHTS,
                    help="a released model name or a linenet-v1 .npz (default %(default)s)")
    ap.add_argument("--out", default="work/letters/demo")
    ap.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"), help="rows and columns on the 38 um grid")
    ap.add_argument("--letter-px", default=str(LETTER_PX), help="letter height in grid pixels, or auto to estimate it")
    ap.add_argument("--lm", help="letter language model .npz (python -m kit greeklm build), shown beside the ink-only read")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # the weights and the language model first: a failed download then costs no map download
    net = R.load_weights(a.weights)
    lm = None
    if a.lm:
        from kit import greeklm
        lm = greeklm.KNLetterLM.load(a.lm)
    img, url = small_map(a.segment, out)
    if a.crop:
        y0, y1, x0, x1 = a.crop
        img = img[y0:y1, x0:x1]
    res = R.read(img, net, letter_px=None if a.letter_px == "auto" else float(a.letter_px), lm=lm)
    res["source"] = {"file": f"{a.segment}-ds8.jpg", "map": url,
                     "grid": "8x downsampled JPEG averaged 2 by 2 (about 38 um per pixel)",
                     "crop": a.crop, "weights": net.file}
    # the files first, then the screen, so a console that fails on a letter never loses the read
    (out / f"{a.segment}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    try:
        R.overlay(img, res, out / f"{a.segment}-overlay.png")
    except ImportError:
        print("(no overlay: Pillow is missing)")
    print(R.text_summary(res))
    print(f"wrote {out / (a.segment + '.json')} and {out / (a.segment + '-overlay.png')}")


if __name__ == "__main__":
    R.utf8_console()   # Greek prints in a pipe and on a Windows console
    main()
