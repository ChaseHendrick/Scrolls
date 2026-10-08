"""End-to-end check on synthetic pages: letter size, deskew, line finding and reading together.

Pages come from letterdata.make_page (seeded, never seen in training: the generator draws new
styles and texts), in the ink-map and drawn-label looks. The reader gets no letter size and no
line positions. Reports character error rate on lines matched in order to the true lines, and
letters kept on two kinds of blank page (papyrus-like texture and clutter with no letters), which
should be near zero. Model output on synthetic images only.

With --text, line texts are slices of a real Greek text instead of random letters, which is the
fair test of a language model (use a text that is not in the model's corpus).

Usage: python scripts/letters/eval_pages.py --weights W [--pages 24] [--seed 11] [--lm LM --text TEI] [--out JSON]
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
from kit import letterread as R  # noqa: E402


class TextSource:
    """Line texts as consecutive slices of a real Greek text (keep it out of the language model's corpus)."""

    def __init__(self, path):
        from kit import greeklm
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
        self.text = greeklm.clean_text(greeklm.tei_text(raw) if path.endswith(".xml") else raw)
        if len(self.text) < 1000:
            raise SystemExit(f"{path}: too little Greek text")

    def sample(self, rng, n):
        i = int(rng.integers(0, len(self.text) - n))
        return self.text[i:i + n]


def blank_page(rng, h, kind):
    """A page with no letters: ink-map texture only, or texture plus strokes and blobs that are not letters."""
    hs = h * L.SS
    shape = (int(hs * 10), int(hs * 16))
    clean = np.zeros(shape, np.float32)
    if kind == "clutter":
        clean = L._clutter(shape, hs, rng)
    return L.downsample(L.to_map_domain(clean, hs, rng), L.SS).astype(np.float32)


def evaluate(weights, pages=24, seed=11, lm=None, lm_weight=0.5, nulls=2, text=None):
    net = R.LineNet(weights)
    rng = np.random.default_rng(seed)
    tot = {"map": [0, 0], "mask": [0, 0]}
    tot_lm = {"map": [0, 0], "mask": [0, 0]}
    rows = []
    for i in range(pages):
        dom = "mask" if i % 3 == 2 else "map"
        h = float(rng.uniform(18, 40))
        img, lines, _, _ = L.make_page(rng, n_lines=int(rng.integers(3, 7)), h=h, domain=dom, lm=text)
        res = R.analyze(img, net, nulls=nulls, seed=i, lm=lm, lm_weight=lm_weight if lm else 0.0)
        read = ["".join(l["glyph"] for l in r["letters"]) for r in res["lines"]]
        pairs = match_lines(read, lines)
        err = sum(R.edit_distance(read[a], lines[b]) for a, b in pairs)
        n = sum(len(lines[b]) for _, b in pairs)
        missed = sum(len(t) for j, t in enumerate(lines) if j not in {b for _, b in pairs})
        tot[dom][0] += err
        tot[dom][1] += n
        row = {"page": i, "domain": dom, "letter_px_true": round(h, 1), "letter_px_used": res["letter_px"],
               "lines_true": len(lines), "lines_read": len(read), "lines_matched": len(pairs),
               "letters_in_unmatched_lines": missed, "cer": round(err / max(1, n), 3),
               "kept": res["control"]["letters_kept"], "null_kept": res["control"]["null_letters_kept"]}
        if lm is not None:
            read_lm = [r["with_lm"] for r in res["lines"]]
            e2 = sum(R.edit_distance(read_lm[a], lines[b]) for a, b in pairs)
            tot_lm[dom][0] += e2
            tot_lm[dom][1] += n
            row["cer_with_lm"] = round(e2 / max(1, n), 3)
        rows.append(row)
        print(json.dumps(row), flush=True)
    blanks = []
    for i, kind in enumerate(["texture", "clutter"] * 3):
        res = R.analyze(blank_page(rng, 24.0, kind), net, nulls=nulls, seed=100 + i)
        blanks.append({"kind": kind, "lines_read": len(res["lines"]), "letters_kept": res["control"]["letters_kept"],
                       "null_kept": res["control"]["null_letters_kept"], "verdict": res["control"]["verdict"]})
        print(json.dumps(blanks[-1]), flush=True)
    summary = {d: {"cer_matched_lines": round(e / n, 3), "letters": n} for d, (e, n) in tot.items() if n}
    if lm is not None:
        summary["with_lm"] = {d: round(e / n, 3) for d, (e, n) in tot_lm.items() if n}
    summary["blank_pages_letters_kept"] = [b["letters_kept"] for b in blanks]
    summary["letter_px_ratio_median"] = round(float(np.median([r["letter_px_used"] / r["letter_px_true"] for r in rows])), 3)
    summary["lines_found"] = f"{sum(r['lines_matched'] for r in rows)} of {sum(r['lines_true'] for r in rows)}"
    return {"note": R.NOTE + " Synthetic pages only.", "weights": str(weights), "seed": seed,
            "text": "real Greek" if text is not None else "uniform random letters", "summary": summary,
            "pages": rows, "blank_pages": blanks}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--pages", type=int, default=24)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--lm")
    ap.add_argument("--lm-weight", type=float, default=0.5)
    ap.add_argument("--text", help="Greek TEI .xml or plain text for the line texts (default: random letters)")
    ap.add_argument("--out")
    a = ap.parse_args()
    lm = None
    if a.lm:
        from kit import greeklm
        lm = greeklm.KNLetterLM.load(a.lm)
    res = evaluate(a.weights, a.pages, a.seed, lm, a.lm_weight, text=TextSource(a.text) if a.text else None)
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res["summary"]))


if __name__ == "__main__":
    main()
