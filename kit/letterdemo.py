"""An offline check that the letter reader works: synthetic Greek capitals, a noise image, and a pass rule.

  python -m kit letterdemo [--weights letters-v2-real] [--out DIR] [--json]
  scrolls-letterdemo ...                 (the same, from an installed package)

The demo draws four lines of Greek capitals, each line the 24 letters in an order fixed by a seed,
with the repository's own skeleton hand (the centreline strokes of scripts/letters/letterdata.py,
copied below and held equal to it by tests/test_letterdemo.py), in numpy only: no system font and
no Pillow. The strokes are blurred and set on a noisy ground, like a clean ink map. It also makes an
image of the same noise with no letters. It reads both with the released weights (downloaded once
and checked by SHA-256, or a file given with --weights) at the letter height it drew, with the
reader's usual nulls, and passes when:

- the text page's status is strong: more than three times the letters of every null, and at least
  ten letters (control_status);
- the page's character error is at most MAX_CER: the edit distance between every letter the reader
  decoded, line by line from the top, and the 96 letters drawn, over 96;
- the noise image's status is none or too_few: it keeps no more letters than its own nulls, or too
  few to judge.

It prints DEMO PASS or DEMO FAIL with the numbers and exits 0 on a pass, 1 on a fail and 2 when it
cannot run (no weights, no numpy). It needs numpy only; with Pillow and --out it also writes the
page and an overlay as PNG.

What a pass shows: the package, its weights and numpy read clean synthetic letters and keep their
controls. It does not show that the reader reads a scroll: the letters are drawn by the hand the
model trained on, with known truth. Every string the reader returns is model output, a letter
hypothesis, not a reading.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

from . import letterread as R

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"   # lunate sigma U+03F9, as the released weights
SEED = 20261014          # draws the letter order, the glyph variants and the text page's ground
NOISE_SEED = 20261015    # the noise image's ground
LETTER_PX = 32           # letter height drawn, in pixels; the reader is told this height
N_LINES = 4
PITCH = 2.0              # line spacing, letter heights
GAP = 0.3                # space between letters, letter heights
PEN = 0.14               # stroke width, letter heights
MAX_CER = 0.25
TEXT_PASS = ("strong",)
NOISE_PASS = ("none", "too_few")
RULE = (f"pass when the text page's status is strong (more than {R.STRONG_FACTOR} times the letters of every null, "
        f"at least {R.MIN_LETTERS} letters), its character error is at most {MAX_CER:g}, and the noise image's "
        "status is none or too_few")

# ------------------------------------------------------------------ the skeleton hand
# Copied from scripts/letters/letterdata.py (tests/test_letterdemo.py checks the two are equal).
# Centrelines in letter units: x right from the letter's left edge, y down, y = 0 top line,
# y = 1 base line. Each glyph: (advance width, [strokes]); a stroke is a list of points.


def _arc(cx, cy, rx, ry, a0, a1, n=24):
    t = np.radians(np.linspace(a0, a1, n))
    return [(cx + rx * math.cos(u), cy - ry * math.sin(u)) for u in t]


def _skeletons():
    S = {}
    S["Α"] = [(0.85, [[(0.0, 1.0), (0.42, 0.0), (0.85, 1.0)], [(0.18, 0.62), (0.68, 0.62)]]),
              (0.85, [[(0.05, 1.0), (0.45, 0.0), (0.85, 1.0)], _arc(0.36, 0.72, 0.2, 0.17, 20, 340)])]
    S["Β"] = [(0.62, [[(0.0, 0.0), (0.0, 1.0)], [(0.0, 0.0)] + _arc(0.22, 0.24, 0.32, 0.24, 90, -90) + [(0.0, 0.48)],
                     [(0.0, 0.48)] + _arc(0.25, 0.74, 0.36, 0.26, 90, -90) + [(0.0, 1.0)]])]
    S["Γ"] = [(0.62, [[(0.0, 1.0), (0.0, 0.0), (0.62, 0.0)]])]
    S["Δ"] = [(0.9, [[(0.0, 1.0), (0.45, 0.0), (0.9, 1.0), (0.0, 1.0)]])]
    S["Ε"] = [(0.7, [_arc(0.45, 0.5, 0.45, 0.5, 60, 300), [(0.02, 0.5), (0.5, 0.5)]]),
              (0.65, [[(0.62, 0.0), (0.0, 0.0), (0.0, 1.0), (0.65, 1.0)], [(0.0, 0.5), (0.5, 0.5)]])]
    S["Ζ"] = [(0.75, [[(0.03, 0.0), (0.72, 0.0), (0.03, 1.0), (0.75, 1.0)]])]
    S["Η"] = [(0.75, [[(0.0, 0.0), (0.0, 1.0)], [(0.75, 0.0), (0.75, 1.0)], [(0.0, 0.5), (0.75, 0.5)]])]
    S["Θ"] = [(0.85, [_arc(0.42, 0.5, 0.42, 0.5, 0, 360, 36), [(0.12, 0.5), (0.72, 0.5)]]),
              (0.85, [_arc(0.42, 0.5, 0.42, 0.5, 0, 360, 36), [(0.32, 0.5), (0.52, 0.5)]])]
    S["Ι"] = [(0.08, [[(0.04, 0.0), (0.04, 1.0)]])]
    S["Κ"] = [(0.72, [[(0.0, 0.0), (0.0, 1.0)], [(0.68, 0.0), (0.03, 0.56)], [(0.22, 0.42), (0.72, 1.0)]]),
              (0.72, [[(0.08, 0.0), (0.0, 0.5), (0.04, 1.0)], [(0.65, 0.02), (0.05, 0.55), (0.72, 1.0)]])]
    S["Λ"] = [(0.85, [[(0.0, 1.0), (0.42, 0.0), (0.85, 1.0)]])]
    S["Μ"] = [(1.0, [[(0.0, 1.0), (0.06, 0.0), (0.5, 0.75), (0.94, 0.0), (1.0, 1.0)]]),
              (1.05, [[(0.0, 1.0), (0.2, 0.0), (0.52, 0.85), (0.85, 0.0), (1.05, 1.0)]]),
              (0.95, [[(0.0, 1.0)] + _arc(0.25, 0.45, 0.24, 0.45, 180, 0, 12) + _arc(0.72, 0.45, 0.23, 0.45, 180, 0, 12)[1:] + [(0.95, 1.0)]])]
    S["Ν"] = [(0.75, [[(0.0, 1.0), (0.0, 0.0), (0.75, 1.0), (0.75, 0.0)]]),
              (0.75, [[(0.0, 1.0), (0.08, 0.0), (0.7, 1.0), (0.78, -0.05)]])]
    S["Ξ"] = [(0.72, [[(0.04, 0.0), (0.68, 0.0)], [(0.14, 0.5), (0.58, 0.5)], [(0.0, 1.0), (0.72, 1.0)]]),
              (0.72, [[(0.04, 0.0), (0.68, 0.0)], [(0.14, 0.5), (0.58, 0.5)], [(0.0, 1.0), (0.72, 1.0)], [(0.36, 0.38), (0.36, 0.62)]])]
    S["Ο"] = [(0.62, [_arc(0.31, 0.44, 0.31, 0.38, 0, 360, 32)]), (0.8, [_arc(0.4, 0.5, 0.4, 0.5, 0, 360, 32)])]
    S["Π"] = [(0.8, [[(0.0, 0.0), (0.0, 1.0)], [(-0.06, 0.0), (0.82, 0.0)], [(0.72, 0.0), (0.74, 0.9), (0.84, 1.0)]]),
              (0.8, [[(0.04, 0.0), (0.0, 1.0)], [(-0.06, 0.02), (0.8, 0.0)], [(0.7, 0.0), (0.72, 1.0)]])]
    S["Ρ"] = [(0.62, [[(0.0, 0.0), (0.0, 1.3)], [(0.0, 0.0)] + _arc(0.25, 0.26, 0.35, 0.26, 90, -90) + [(0.0, 0.52)]])]
    S["Ϲ"] = [(0.7, [_arc(0.45, 0.5, 0.45, 0.5, 55, 305)])]
    S["Τ"] = [(0.8, [[(0.0, 0.0), (0.8, 0.0)], [(0.4, 0.0), (0.4, 1.0)]]),
              (0.8, [[(0.0, 0.08), (0.1, 0.0), (0.8, 0.0)], [(0.4, 0.0), (0.4, 0.96), (0.5, 1.0)]])]
    S["Υ"] = [(0.8, [[(0.0, 0.0), (0.4, 0.5), (0.8, 0.0)], [(0.4, 0.5), (0.4, 1.0)]]),
              (0.8, [_arc(0.2, 0.0, 0.2, 0.5, 180, 270, 8) + _arc(0.6, 0.0, 0.2, 0.5, 270, 360, 8), [(0.4, 0.5), (0.4, 1.0)]])]
    S["Φ"] = [(0.95, [[(0.48, -0.28), (0.48, 1.28)], _arc(0.48, 0.48, 0.48, 0.32, 0, 360, 32)])]
    S["Χ"] = [(0.8, [[(0.0, 0.0), (0.8, 1.0)], [(0.8, 0.0), (0.0, 1.0)]])]
    S["Ψ"] = [(0.95, [[(0.48, -0.25), (0.48, 1.0)], _arc(0.48, 0.0, 0.46, 0.6, 180, 360, 16)])]
    S["Ω"] = [(1.0, [[(0.08, 0.15)] + _arc(0.27, 0.55, 0.22, 0.45, 160, 360, 10)[1:] + _arc(0.73, 0.55, 0.22, 0.45, 180, 380, 10)[1:]]),
              (0.9, [_arc(0.45, 0.45, 0.4, 0.45, -60, 240, 28), [(0.0, 1.0), (0.25, 1.0)], [(0.65, 1.0), (0.9, 1.0)]])]
    return S


SKELETONS = _skeletons()


# ------------------------------------------------------------------ drawing, numpy only

def _segments(text, h, rng, x0, top):
    """Stroke segments ((x, y), (x, y)) in page pixels of one line of text, its letters' left edges and its right end.

    Each letter takes a variant of its skeleton picked by rng; letters sit PEN + GAP letter heights apart."""
    segs, lefts, x = [], [], float(x0)
    for ch in text:
        variants = SKELETONS[ch]
        adv, strokes = variants[int(rng.integers(len(variants)))]
        dy = float(rng.normal(0.0, 0.02)) * h   # a little baseline wobble
        lefts.append(x)
        for st in strokes:
            pts = [(x + px * h, top + dy + py * h) for px, py in st]
            segs.extend(zip(pts[:-1], pts[1:]))
        x += (adv + PEN + GAP) * h
    return segs, lefts, x


def draw_segments(shape, segs, width):
    """Ink coverage (0 to 1) of round-pen strokes `width` px wide along the segments, anti-aliased by distance."""
    out = np.zeros(shape, np.float32)
    r = width / 2.0
    pad = r + 1.5
    for (ax, ay), (bx, by) in segs:
        y0, y1 = max(0, int(math.floor(min(ay, by) - pad))), min(shape[0], int(math.ceil(max(ay, by) + pad)) + 1)
        x0, x1 = max(0, int(math.floor(min(ax, bx) - pad))), min(shape[1], int(math.ceil(max(ax, bx) + pad)) + 1)
        if y0 >= y1 or x0 >= x1:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float64)
        vx, vy = bx - ax, by - ay
        n2 = vx * vx + vy * vy
        t = np.clip(((xx - ax) * vx + (yy - ay) * vy) / n2, 0.0, 1.0) if n2 > 0 else 0.0
        d = np.hypot(xx - (ax + t * vx), yy - (ay + t * vy))
        np.maximum(out[y0:y1, x0:x1], np.clip(r + 0.5 - d, 0.0, 1.0).astype(np.float32), out=out[y0:y1, x0:x1])
    return out


def blur(a, sigma):
    """Separable Gaussian blur with reflected edges (numpy only)."""
    if sigma <= 0.05:
        return a
    k = int(math.ceil(3 * sigma))
    w = np.exp(-0.5 * (np.arange(-k, k + 1) / sigma) ** 2)
    w /= w.sum()
    p = np.pad(a, ((k, k), (0, 0)), mode="reflect")
    a = sum(w[i] * p[i:i + a.shape[0]] for i in range(2 * k + 1))
    p = np.pad(a, ((0, 0), (k, k)), mode="reflect")
    return sum(w[i] * p[:, i:i + a.shape[1]] for i in range(2 * k + 1))


def ground(shape, h, rng):
    """A noisy ground like an ink map's background: smooth blotches, fibre streaks along the lines, and grain."""
    blotch = blur(rng.standard_normal(shape), 0.3 * h)
    blotch /= max(float(blotch.std()), 1e-9)
    streak = blur(blur(rng.standard_normal(shape), 0.04 * h).T, 0.6 * h).T
    streak /= max(float(streak.std()), 1e-9)
    grain = rng.standard_normal(shape)
    return (0.12 + 0.05 * blotch + 0.04 * streak + 0.05 * grain).astype(np.float32)


def page_lines(seed=SEED, n_lines=N_LINES):
    """The demo's text: n_lines lines, each the 24 capitals in an order drawn from the seed."""
    rng = np.random.default_rng(seed)
    return ["".join(ALPHABET[i] for i in rng.permutation(len(ALPHABET))) for _ in range(n_lines)]


def render_page(lines, h=LETTER_PX, seed=SEED):
    """(image, truth): the lines drawn h px tall with the skeleton hand, blurred, on a noisy ground (ink bright).

    The image is float32 in 0 to 1. truth holds per line its text, its centre row and each letter's left edge,
    all in page pixels. The same lines, h and seed give the same image."""
    rng = np.random.default_rng(seed + 1)
    drawn, x_end = [], 0.0
    for i, text in enumerate(lines):
        top = (1.2 + i * PITCH) * h
        segs, lefts, x = _segments(text, h, rng, 1.5 * h, top)
        drawn.append((text, top, segs, lefts))
        x_end = max(x_end, x)
    shape = (int(round((2.4 + (len(lines) - 1) * PITCH + 1.0) * h)), int(math.ceil(x_end + 1.2 * h)))
    ink = draw_segments(shape, [s for d in drawn for s in d[2]], PEN * h)
    ink = blur(ink, 0.05 * h)
    img = np.clip(ground(shape, h, rng) + 0.7 * ink, 0.0, 1.0).astype(np.float32)
    truth = [{"text": text, "y": round(top + 0.5 * h, 1), "x": [round(v, 1) for v in lefts]}
             for text, top, _, _ in drawn]
    return img, truth


def noise_page(shape, h=LETTER_PX, seed=NOISE_SEED):
    """An image of the text page's ground alone, with no letters: the demo's known-bad input."""
    return np.clip(ground(shape, h, np.random.default_rng(seed)), 0.0, 1.0).astype(np.float32)


# ------------------------------------------------------------------ the check

def decoded(res):
    """Every letter the reader decoded, any confidence, line by line in reading order (column, then row)."""
    lines = sorted(res["lines"], key=lambda ln: (ln["column"], ln["y"]))
    return ["".join(lt["glyph"] for lt in ln["letters"]) for ln in lines]


def character_error(res, truth):
    """Edit distance between the decoded letters, joined line by line, and the drawn letters, over the letters drawn."""
    want = "".join(t["text"] for t in truth)
    return R.edit_distance("".join(decoded(res)), want) / max(1, len(want))


def judge(text_res, noise_res, truth, max_cer=MAX_CER):
    """(passed, numbers) under RULE: the text page strong at a character error up to max_cer, the noise none or too_few."""
    cer = character_error(text_res, truth)
    tc, nc = text_res["control"], noise_res["control"]
    checks = {"text_status": tc["status"] in TEXT_PASS, "character_error": cer <= max_cer,
              "noise_status": nc["status"] in NOISE_PASS}
    numbers = {"text": {"status": tc["status"], "letters_kept": tc["letters_kept"],
                        "null_letters_kept": tc["null_letters_kept"], "ratio": tc["ratio"],
                        "character_error": round(cer, 4), "letters_drawn": sum(len(t["text"]) for t in truth),
                        "lines_found": len(text_res["lines"]), "lines_drawn": len(truth)},
               "noise": {"status": nc["status"], "letters_kept": nc["letters_kept"],
                         "null_letters_kept": nc["null_letters_kept"], "ratio": nc["ratio"]},
               "checks": checks, "max_cer": max_cer, "rule": RULE}
    return all(checks.values()), numbers


def run(weights="letters-v2-real", progress=None):
    """Draw the page and the noise image, read both with the weights and judge them: a JSON-able dict.

    weights: a released model name, a path or a LineNet (letterread.load_weights). The dict holds
    `passed`, `numbers` (judge()), `truth`, `decoded`, the two full results under `text_result` and
    `noise_result`, and the drawing's settings; the images are returned under `_images` (not JSON)."""
    say = progress or (lambda msg: None)
    net = R.load_weights(weights)
    lines = page_lines()
    img, truth = render_page(lines)
    noise = noise_page(img.shape)
    say(f"reading the text page ({img.shape[0]} x {img.shape[1]} px, letters {LETTER_PX} px tall)")
    text_res = R.read(img, net, letter_px=LETTER_PX, orientation=False)
    say("reading the noise image")
    noise_res = R.read(noise, net, letter_px=LETTER_PX, orientation=False)
    passed, numbers = judge(text_res, noise_res, truth)
    return {"note": R.NOTE, "demo": "kit.letterdemo", "passed": passed, "numbers": numbers,
            "drawing": {"seed": SEED, "noise_seed": NOISE_SEED, "letter_px": LETTER_PX, "lines": len(lines),
                        "pitch": PITCH, "gap": GAP, "pen": PEN, "shape": list(img.shape),
                        "hand": "skeleton (scripts/letters/letterdata.py), drawn in numpy"},
            "truth": truth, "decoded": decoded(text_res), "weights": R.weights_info(net),
            "text_result": text_res, "noise_result": noise_res, "_images": (img, noise)}


def report(out):
    """The demo's printed report: truth and decode line by line, both statuses, and DEMO PASS or DEMO FAIL."""
    n, w = out["numbers"], out["weights"]
    t, z = n["text"], n["noise"]
    rows = [f"Letter reader demo: {t['lines_drawn']} lines of Greek capitals drawn with the skeleton hand "
            f"(seed {out['drawing']['seed']}), letters {out['drawing']['letter_px']} px tall, and an image of noise",
            f"weights: {w['name'] or '(not a released model)'} ({w['file']}, sha256 {str(w['sha256'])[:12]})", ""]
    for i, truth in enumerate(out["truth"]):
        got = out["decoded"][i] if i < len(out["decoded"]) else ""
        rows += [f"  drawn   {truth['text']}", f"  decoded {got}"]
    for extra in out["decoded"][len(out["truth"]):]:
        rows.append(f"  decoded {extra}   (a line with no drawn line)")
    rows += ["",
             f"text page:   {t['status']} ({t['letters_kept']} letters kept; nulls "
             f"{', '.join(map(str, t['null_letters_kept']))}, ratio {t['ratio']:g}); character error "
             f"{t['character_error']:.3f} over {t['letters_drawn']} letters; {t['lines_found']} lines found of "
             f"{t['lines_drawn']}",
             f"noise image: {z['status']} ({z['letters_kept']} letters kept; nulls "
             f"{', '.join(map(str, z['null_letters_kept']))}, ratio {z['ratio']:g})",
             f"rule: {n['rule']}", ""]
    failed = [k for k, ok in n["checks"].items() if not ok]
    if out["passed"]:
        rows.append(f"DEMO PASS: the text page is {t['status']} at a character error of {t['character_error']:.3f}, "
                    f"and the noise image is {z['status']}.")
    else:
        rows.append(f"DEMO FAIL ({', '.join(failed)}): text page {t['status']}, character error "
                    f"{t['character_error']:.3f} (at most {n['max_cer']:g} passes); noise image {z['status']}.")
    rows.append(R.NOTE)
    return "\n".join(rows)


def save(out, folder):
    """Write demo.json and, with Pillow, demo-page.png and demo-overlay.png into folder; returns the files written."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    img, _ = out["_images"]
    data = {k: v for k, v in out.items() if k != "_images"}
    files = [folder / "demo.json"]
    files[0].write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    try:
        from PIL import Image
    except ImportError:
        return files
    Image.fromarray((np.clip(img, 0, 1) * 255).round().astype(np.uint8)).save(folder / "demo-page.png")
    R.overlay(img, out["text_result"], folder / "demo-overlay.png")
    return files + [folder / "demo-page.png", folder / "demo-overlay.png"]


def run_cli(args):
    """The command line (python -m kit letterdemo, scrolls-letterdemo) on parsed arguments: weights, out, json, quiet.

    Prints the report (or JSON with --json) and returns 0 on DEMO PASS, 1 on DEMO FAIL and 2 when the demo cannot
    run (DEMO ERROR on stderr: the weights cannot be found or downloaded, or --out is not a folder)."""
    R.utf8_console()
    say = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))
    try:
        if args.out and Path(args.out).exists() and not Path(args.out).is_dir():
            raise OSError(f"--out {args.out}: not a folder")
        out = run(args.weights, progress=say)
    except (ImportError, OSError, KeyError, ValueError) as exc:
        print(f"DEMO ERROR: {exc}", file=sys.stderr)
        return 2
    files, failed = [], None
    if args.out:
        try:
            files = save(out, args.out)
        except (ImportError, OSError, ValueError) as exc:
            failed = exc
    if args.json:
        print(json.dumps({k: out[k] for k in ("note", "passed", "numbers", "truth", "decoded", "weights", "drawing")},
                         ensure_ascii=False, indent=1))
    else:
        print(report(out))
    for f in files:
        say(f"wrote {f}")
    if failed is not None:
        print(f"DEMO ERROR: could not write into {args.out}: {failed}", file=sys.stderr)
        return 2
    return 0 if out["passed"] else 1
