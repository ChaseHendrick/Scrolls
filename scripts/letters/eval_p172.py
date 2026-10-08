"""Real-letter check on PHerc. 172: read the hand-drawn ink labels and compare with the labeller's transcription.

Data: N.A. Bodill, Herculaneum-Scroll-Labels (https://github.com/Bodillium/Herculaneum-Scroll-Labels,
CC BY-NC-SA 4.0): binary ink-label PNGs for PHerc. 172 segments and "Preliminary Transcriptions of
P.Herc. 172" v0.1 (2024-12-07), whose author calls the readings speculative and not peer reviewed.
Nothing from that repository is copied here; pass a local clone.

What it measures: whether the reader names the letters a person drew, scored as character error
rate (edit distance over reference letters) on lines matched in order to the transcription
(letters the transcription marks unknown are skipped). It is not an ink-map test: the masks are
clean drawings of what the labeller read. A model trained on synthetic lines meets real
Herculaneum letterforms here for the first time, so this is a domain-transfer check.

Every string is model output. Keep --out files in ignored work/ folders.

Usage:
  git clone --depth 1 https://github.com/Bodillium/Herculaneum-Scroll-Labels work/bodillium
  python scripts/letters/eval_p172.py work/bodillium --weights work/letters/linenet.npz [--lm work/letters/greek5.npz]
Needs numpy, Pillow and pdftotext (poppler-utils).
"""
import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit import letterread as R  # noqa: E402

LETTERS = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"
LABEL_DIR = "P.Herc. 172 (Scroll 5) Ink Labels"
PDF_DIR = "Transcriptions & Readings"


def parse_transcription(text):
    """{segment id: [[line, ...] per column block]} with letters in capitals, lunate sigma, '?' for unknown."""
    segs = re.split(r"Segment (\d{14})", text)
    out = {}
    for i in range(1, len(segs), 2):
        cols = []
        for block in re.findall(r"---\n(.*?)\n\s*---", segs[i + 1], re.S):
            lines = []
            for ln in block.split("\n"):
                ln = re.sub(r"^\s*\d+\s+", "", ln)                        # line numbers
                d = unicodedata.normalize("NFD", ln)
                d = re.sub(r"(?<![^\s\[\]])̣", "?", d)               # a dot below with no letter: unknown letter
                d = "".join(c for c in d if not unicodedata.combining(c))
                d = d.upper().replace("Σ", "Ϲ").replace("C", "Ϲ").replace("ς", "Ϲ")
                lines.append("".join(c for c in d if c in LETTERS + "?"))
            cols.append(lines)
        out[segs[i]] = cols
    return out


def match_lines(read, ref):
    """Order-preserving pairing of read lines with reference lines, minimising total edit cost.

    Unpaired lines cost their length, so a stray read line or a missed reference line is charged."""
    n, m = len(read), len(ref)
    D = np.zeros((n + 1, m + 1))
    D[0, :] = np.cumsum([0] + [len(r) for r in ref])
    back = {}
    for i in range(1, n + 1):
        D[i, 0] = D[i - 1, 0] + len(read[i - 1])
        back[(i, 0)] = (i - 1, 0, None)
        for j in range(1, m + 1):
            opts = [(D[i - 1, j - 1] + R.edit_distance(read[i - 1], ref[j - 1]), (i - 1, j - 1, (i - 1, j - 1))),
                    (D[i - 1, j] + len(read[i - 1]), (i - 1, j, None)),
                    (D[i, j - 1] + len(ref[j - 1]), (i, j - 1, None))]
            D[i, j], back[(i, j)] = min(opts, key=lambda o: o[0])
    pairs, i, j = [], n, m
    while i > 0:
        if j == 0:
            i -= 1
            continue
        pi, pj, pr = back[(i, j)]
        if pr is not None:
            pairs.append(pr)
        i, j = pi, pj
    return pairs[::-1]


def load_mask(path, down):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    a = np.asarray(Image.open(path).convert("L")) > 127
    ys, xs = np.nonzero(a)
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    H, W = (a.shape[0] // down) * down, (a.shape[1] // down) * down
    return a[:H, :W].reshape(H // down, down, W // down, down).mean(axis=(1, 3))


def evaluate(repo, weights, lm=None, lm_weight=0.5, down=4, nulls=2):
    repo = Path(repo)
    pdf = sorted((repo / PDF_DIR).glob("*.pdf"))
    if not pdf:
        raise SystemExit(f"no transcription PDF under {repo / PDF_DIR}")
    text = subprocess.run(["pdftotext", "-layout", str(pdf[0]), "-"], capture_output=True, text=True, check=True).stdout
    gt = parse_transcription(text)
    net = R.LineNet(weights)
    tot = {"ink_only": [0, 0], "with_lm": [0, 0]}
    rows = []
    for sid, cols in gt.items():
        f = repo / LABEL_DIR / f"{sid}_inklabels.png"
        ref = [r for r in (ln.replace("?", "") for c in cols for ln in c) if r]
        if not f.exists() or not ref:
            continue
        res = R.analyze(load_mask(f, down), net, nulls=nulls, seed=0, lm=lm, lm_weight=lm_weight if lm else 0.0)
        row = {"segment": sid, "letter_px": res["letter_px"], "lines_read": len(res["lines"]), "ref_lines": len(ref),
               "control": res["control"]["verdict"], "kept": res["control"]["letters_kept"],
               "null_kept": res["control"]["null_letters_kept"]}
        decodes = {"ink_only": ["".join(l["glyph"] for l in L["letters"]) for L in res["lines"]]}
        if lm is not None:
            decodes["with_lm"] = [L["with_lm"] for L in res["lines"]]
        for name, read in decodes.items():
            pairs = match_lines(read, ref)
            err = sum(R.edit_distance(read[i], ref[j]) for i, j in pairs)
            nref = sum(len(ref[j]) for _, j in pairs)
            tot[name][0] += err
            tot[name][1] += nref
            row[name] = {"cer": round(err / max(1, nref), 3), "ref_letters": nref,
                         "pairs": [[read[i], ref[j]] for i, j in pairs]}
        rows.append(row)
    summary = {name: {"cer_matched_lines": round(e / n, 3), "ref_letters": n} for name, (e, n) in tot.items() if n}
    return {"note": R.NOTE, "data": "Bodillium/Herculaneum-Scroll-Labels, PHerc. 172 hand-drawn ink labels",
            "weights": str(weights), "down": down, "summary": summary, "segments": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="local clone of Bodillium/Herculaneum-Scroll-Labels")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--lm", help="letter language model .npz (python -m kit greeklm build)")
    ap.add_argument("--lm-weight", type=float, default=0.5)
    ap.add_argument("--down", type=int, default=4, help="downsample the label grid by this factor before reading (speed only)")
    ap.add_argument("--out", help="full result JSON (keep it in work/)")
    a = ap.parse_args()
    lm = None
    if a.lm:
        from kit import greeklm
        lm = greeklm.KNLetterLM.load(a.lm)
    res = evaluate(a.repo, a.weights, lm, a.lm_weight, a.down)
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for r in res["segments"]:
        print(f"{r['segment']}: CER {r['ink_only']['cer']} on {r['ink_only']['ref_letters']} letters"
              + (f", with LM {r['with_lm']['cer']}" if "with_lm" in r else "")
              + f"; control: {r['kept']} kept vs nulls {r['null_kept']}")
    print(json.dumps(res["summary"]))


if __name__ == "__main__":
    main()
