"""Reading photograph-like pages: ink polarity, a tilt of a few degrees and a quarter turn.

Pages come from letterdata.make_page(domain="photo"): dark ink on a light papyrus ground, the
opposite polarity of an ink map, stored as 8-bit grey and each turned a few degrees by a true
rotation (not the reader's shear). Each page is read at its true letter height with --polarity
bright (the default), dark and auto, and once more dark with the rows the deskew shears in filled
with 0, as every read did before read() filled them with the ground's grey for dark ink. Reported
per read: the status, letters kept against the nulls, the character error over all read letters on
lines matched in order to the true lines (eval_p172.match_lines, as in eval_pages.py), the deskew
angle against the true one, the polarity auto chose (by its quick read both ways) and whether the
read carried the polarity hint (a read in a given polarity whose controls do not pass checks the
other polarity). Each page is also turned a quarter turn counter-clockwise (its lines then run up
and down) and read with auto: the orientation reads should name rot90 as the best, and best_view
should be --rotate 90. The same page on a dark mount and on a white mount, each making up 60% of
the frame, compares auto's quick read with the grey-level guess (normalize(a, "auto")), which
judges from the median grey. Pages with no letters, photo-like (read with auto and with dark) and
ink-map-like (eval_pages.blank_page, read with auto and with bright), measure how much choosing
the polarity by letter counts raises the chance of a pass where there is no text.

Model output on synthetic images only; it says nothing about real photographs.

Usage: python scripts/letters/eval_photos.py --weights W [--pages 12] [--blanks 12] [--seed 31] [--nulls 4] [--out JSON]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import letterdata as L  # noqa: E402
from eval_p172 import match_lines  # noqa: E402
from eval_pages import blank_page  # noqa: E402
from kit import letterread as R  # noqa: E402

POLARITIES = ("bright", "dark", "auto")


def turn(img, deg):
    """img turned deg degrees counter-clockwise about its centre (bilinear), corners filled with the median grey."""
    from PIL import Image
    im = Image.fromarray(np.asarray(img, np.float32), mode="F")
    return np.asarray(im.rotate(deg, resample=Image.BILINEAR, expand=True, fillcolor=float(np.median(img))),
                      np.float32)


def eight_bit(img):
    """The grey levels of an 8-bit photograph: 0 to 255, whole numbers."""
    return np.round(np.clip(img, 0, 1) * 255).astype(np.float32)


def photo_page(rng, h, n_lines, tilt, blank=False):
    """(image, line texts): a synthetic photo page turned tilt degrees; with blank, the same ground and no ink."""
    if blank:
        hs = h * L.SS
        clean = np.zeros((int(2 * hs * (n_lines + 1)), int(16 * hs)), np.float32)
        img, lines = L.downsample(L.to_photo_domain(clean, hs, rng), L.SS).astype(np.float32), []
    else:
        img, lines, _, _ = L.make_page(rng, n_lines=n_lines, h=h, domain="photo", tilt_deg=0)
    return eight_bit(turn(img, tilt) if tilt else img), lines


def on_mount(img, frac=0.6, grey=20.0):
    """img in the middle of a dark mount that makes up about frac of the whole frame."""
    s = 1.0 / np.sqrt(1.0 - frac)
    H, W = int(round(img.shape[0] * s)), int(round(img.shape[1] * s))
    out = np.full((H, W), grey, np.float32)
    y0, x0 = (H - img.shape[0]) // 2, (W - img.shape[1]) // 2
    out[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
    return out


def cer(res, lines):
    """(edits, letters) over all read letters of the lines matched in order to the true lines."""
    read = ["".join(l["glyph"] for l in r["letters"]) for r in res["lines"]]
    pairs = match_lines(read, lines)
    return sum(R.edit_distance(read[a], lines[b]) for a, b in pairs), sum(len(lines[b]) for _, b in pairs)


def summary_row(res, lines, true_deskew):
    e, n = cer(res, lines)
    c = res["control"]
    out = {"status": c["status"], "kept": c["letters_kept"], "nulls": c["null_letters_kept"], "edits": e,
           "letters": n, "cer": round(e / max(1, n), 3), "deskew_deg": res["deskew_deg"],
           "deskew_error": round(abs(res["deskew_deg"] - true_deskew), 2), "used": res["polarity"]["used"],
           "hint": "hint" in res["polarity"]}
    if "trial" in res["polarity"]:
        t = res["polarity"]["trial"]
        out["trial"] = {p: [t[p]["letters_kept"], max(t[p]["null_letters_kept"])] for p in ("bright", "dark")}
    return out


def blank_reads(net, imgs, polarities, nulls, seed):
    """Status of each page with no letters read in each polarity, at 24 px with four nulls."""
    rows = []
    for i, img in enumerate(imgs):
        row = {}
        for pol in polarities:
            res = R.read(img, net, letter_px=24.0, polarity=pol, nulls=nulls, seed=seed + i, orientation=False)
            c = res["control"]
            row[pol] = {"kept": c["letters_kept"], "nulls": c["null_letters_kept"], "status": c["status"],
                        "used": res["polarity"]["used"]}
        rows.append(row)
        print(json.dumps(row), flush=True)
    return rows


def passes(rows, pol):
    """How many reads in this polarity passed (strong or weak)."""
    return sum(r[pol]["status"] in ("strong", "weak") for r in rows)


def evaluate(weights, pages=12, seed=31, nulls=4, blanks=12):
    net = R.load_weights(weights)   # a .npz file or a released model name
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(pages):
        h = float(rng.uniform(18, 30))
        tilt = float(rng.choice([-1, 1]) * rng.uniform(2, 5))
        img, lines = photo_page(rng, h, int(rng.integers(4, 8)), tilt)
        # a counter-clockwise turn by tilt lifts the right end of each line; the shear that levels it is -tilt
        row = {"page": i, "letter_px": round(h, 1), "tilt_deg": round(tilt, 2), "deskew_true": round(-tilt, 2),
               "lines_true": len(lines)}
        for pol in POLARITIES:
            res = R.read(img, net, letter_px=h, polarity=pol, nulls=nulls, seed=i, orientation=False)
            row[pol] = summary_row(res, lines, -tilt)
        res = R.read(img, net, letter_px=h, polarity="dark", nulls=nulls, seed=i, orientation=False, shear_fill=0.0)
        row["dark_fill0"] = summary_row(res, lines, -tilt)
        quarter = np.rot90(img, 1)          # lines run up and down
        res = R.read(quarter, net, letter_px=h, polarity="auto", nulls=nulls, seed=i)
        o = res["orientation"]
        row["quarter_turn"] = {"status": res["control"]["status"], "orientation": o["letters_kept"], "best": o["best"],
                               "best_view": o["best_view"]}
        for mount, grey in (("dark_mount", 20.0), ("white_mount", 250.0)):
            mounted = on_mount(img, grey=grey)
            t = R.polarity_trial(R.normalize(mounted, "bright"), net, "bright", letter_px=h, seed=i)
            row[mount] = {"grey_level_guess": R.normalize_info(mounted, "auto")[1]["used"], "auto": t["choice"],
                          "trial": {p: [t[p]["letters_kept"], max(t[p]["null_letters_kept"])] for p in ("bright", "dark")}}
        rows.append(row)
        print(json.dumps(row), flush=True)
    photo_blanks = [photo_page(rng, 24.0, 6, float(rng.uniform(-5, 5)), blank=True)[0] for _ in range(blanks)]
    blank_photo = blank_reads(net, photo_blanks, ("auto", "dark"), nulls, 100)
    map_blanks = [blank_page(rng, 24.0, "texture" if i % 2 == 0 else "clutter") for i in range(blanks)]
    blank_map = blank_reads(net, map_blanks, ("auto", "bright"), nulls, 200)
    summary = {}
    for pol in POLARITIES + ("dark_fill0",):
        st = [r[pol]["status"] for r in rows]
        edits, letters = sum(r[pol]["edits"] for r in rows), sum(r[pol]["letters"] for r in rows)
        summary[pol] = {"cer": round(edits / max(1, letters), 3), "letters": letters,
                        "status": {s: st.count(s) for s in R.STATUS_TEXT if st.count(s)},
                        "hints": sum(r[pol]["hint"] for r in rows),
                        "deskew_within_1_deg": f"{sum(r[pol]['deskew_error'] <= 1.0 for r in rows)} of {len(rows)}",
                        "deskew_at_limit": f"{sum(abs(r[pol]['deskew_deg']) >= R.DESKEW_DEG for r in rows)} of {len(rows)}"}
    n = len(rows)
    summary["auto_chose_dark"] = f"{sum(r['auto']['used'] == 'dark' for r in rows)} of {n}"
    summary["quarter_turn_best_rot90"] = f"{sum(r['quarter_turn']['best'] == 'rot90' for r in rows)} of {n}"
    for mount in ("dark_mount", "white_mount"):
        summary[mount] = {"auto_chose_dark": f"{sum(r[mount]['auto'] == 'dark' for r in rows)} of {n}",
                          "grey_level_guess_dark": f"{sum(r[mount]['grey_level_guess'] == 'dark' for r in rows)} of {n}"}

    def statuses(rs, pol):
        st = [r[pol]["status"] for r in rs]
        return {s: st.count(s) for s in R.STATUS_TEXT if st.count(s)}
    summary["blank_photo_pages"] = {"pages": len(blank_photo), "auto": statuses(blank_photo, "auto"),
                                    "dark": statuses(blank_photo, "dark"),
                                    "passed_auto": passes(blank_photo, "auto"), "passed_dark": passes(blank_photo, "dark")}
    summary["blank_map_pages"] = {"pages": len(blank_map), "auto": statuses(blank_map, "auto"),
                                  "bright": statuses(blank_map, "bright"),
                                  "passed_auto": passes(blank_map, "auto"), "passed_bright": passes(blank_map, "bright")}
    return {"note": R.NOTE + " Synthetic photograph-like pages only.", "weights": net.file,
            "weights_sha256": net.sha256, "seed": seed,
            "nulls": nulls, "summary": summary, "pages": rows, "blank_photo_pages": blank_photo,
            "blank_map_pages": blank_map}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--pages", type=int, default=12)
    ap.add_argument("--blanks", type=int, default=12, help="pages with no letters of each kind (default 12)")
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--nulls", type=int, default=4)
    ap.add_argument("--out")
    a = ap.parse_args()
    if getattr(a, "out", None):   # the folder first, so a long read never ends on a missing folder
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    res = evaluate(a.weights, a.pages, a.seed, a.nulls, a.blanks)
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res["summary"]))


if __name__ == "__main__":
    R.utf8_console()   # Greek prints in a pipe and on a Windows console
    main()
