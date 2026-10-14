"""Checks of the letter reader's control status (kit/letterread.py control_status) on public and synthetic data.

windows: cut a map into windows, read each as stored and on tile-shuffled copies of the whole map
(letter-sized tiles scrambled, so lines and letters are broken, as in the tile-shuffle null), and
count each status and the old verdict() wording. On shuffled windows any pass is a false one; this
is how the floor of 10 letters (MIN_LETTERS) was checked on PHerc. 1667 w013's 38 um map.

blanks: read eval_pages.py's synthetic pages with no letters (papyrus-like texture and clutter),
each with the letter size searched and with the true size given, and count each status.

Model output only: letter hypotheses, never a reading. Do not run it on a prize-eligible scroll's
maps in public (prize disclosure terms).

Usage:
  python scripts/letters/eval_controls.py windows MAP --weights W [--letter-px 86] [--window 520 1000] [--copies 3]
  python scripts/letters/eval_controls.py blanks --weights W [--pages 12] [--seeds 21 22]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
from kit import letterread as R  # noqa: E402

OLD = {"confident letters well above every null": "well above",
       "more confident letters than every null, but within a factor of three": "above",
       "confident letters NOT above the nulls: treat every letter here as noise": "NOT above"}


def windows(path, weights, letter_px=86.0, size=(520, 1000), copies=3, nulls=4):
    img = R.normalize(R.load_image(path))
    net = R.load_weights(weights)   # a .npz file or a released model name
    H, W = img.shape
    wh, ww = size
    maps = [("as_stored", img)] + [(f"shuffled{s}", R.null_images(img, letter_px, n=1, seed=100 + s)[0][1])
                                   for s in range(copies)]
    rows = []
    for name, a in maps:
        for y0 in range(0, H - wh + 1, wh):
            for x0 in range(0, W - ww + 1, ww):
                res = R.analyze(a[y0:y0 + wh, x0:x0 + ww], net, letter_px=letter_px, nulls=nulls, seed=len(rows))
                c = res["control"]
                rows.append({"map": name, "y0": y0, "x0": x0, "lines": len(res["lines"]), "kept": c["letters_kept"],
                             "nulls": c["null_letters_kept"], "old": OLD[c["verdict"]], "status": c["status"]})
                print(json.dumps(rows[-1]), flush=True)
    summary = {}
    for kind in ("as_stored", "shuffled"):
        rs = [r for r in rows if r["map"].startswith(kind)]
        summary[kind] = {"windows": len(rs), "old": dict(Counter(r["old"] for r in rs)),
                         "status": dict(Counter(r["status"] for r in rs)),
                         "kept_where_old_passed_under_floor": sorted(r["kept"] for r in rs
                                                                     if r["old"] != "NOT above" and r["kept"] < R.MIN_LETTERS),
                         "max_kept": max((r["kept"] for r in rs), default=None)}
    return {"note": R.NOTE, "map": Path(path).name, "weights": net.file, "weights_sha256": net.sha256,
            "letter_px": letter_px, "window": list(size), "nulls": nulls, "summary": summary, "windows": rows}


def blanks(weights, pages=12, seeds=(21, 22), nulls=4, h=24.0):
    from eval_pages import blank_page
    net = R.load_weights(weights)   # a .npz file or a released model name
    rows = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        for i in range(pages):
            kind = ("texture", "clutter")[i % 2]
            img = blank_page(rng, h, kind)
            for given in (None, h):
                c = R.analyze(img, net, letter_px=given, nulls=nulls, seed=i)["control"]
                rows.append({"seed": seed, "page": i, "kind": kind, "letter_px": "given" if given else "searched",
                             "kept": c["letters_kept"], "nulls": c["null_letters_kept"], "old": OLD[c["verdict"]],
                             "status": c["status"]})
                print(json.dumps(rows[-1]), flush=True)
    return {"note": R.NOTE + " Synthetic pages with no letters.", "weights": net.file, "weights_sha256": net.sha256,
            "summary": {
        "reads": len(rows), "status": dict(Counter(r["status"] for r in rows)),
        "old": dict(Counter(r["old"] for r in rows))}, "reads": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("windows", help="windows of a map, as stored and tile-shuffled")
    a.add_argument("map")
    a.add_argument("--weights", required=True, help="linenet-v1 .npz file, or a released model name such as letters-v2-real")
    a.add_argument("--letter-px", type=float, default=86.0)
    a.add_argument("--window", type=int, nargs=2, default=(520, 1000), metavar=("H", "W"))
    a.add_argument("--copies", type=int, default=3)
    a.add_argument("--out")
    b = sub.add_parser("blanks", help="synthetic pages with no letters")
    b.add_argument("--weights", required=True, help="linenet-v1 .npz file, or a released model name such as letters-v2-real")
    b.add_argument("--pages", type=int, default=12)
    b.add_argument("--seeds", type=int, nargs="+", default=[21, 22])
    b.add_argument("--out")
    args = ap.parse_args(argv)
    if args.cmd == "windows":
        res = windows(args.map, args.weights, args.letter_px, tuple(args.window), args.copies)
    else:
        res = blanks(args.weights, args.pages, tuple(args.seeds))
    print(json.dumps(res["summary"], ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    R.utf8_console()   # Greek prints in a pipe and on a Windows console
    main()
