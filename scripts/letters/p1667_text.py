"""PHerc. 1667's published Greek text as a scoring reference for the letter reader.

The text is the column-by-column transcription in arXiv 2606.29085 ("Complete virtual unwrapping
and reading of a rolled Herculaneum papyrus", Methods, "Complete PHerc. 1667 transcription and
translation": columns 5 to 22; columns 1 to 4 are traces). The paper is not in this repository;
this script reads a local copy of its PDF (word boxes from pdftotext -bbox, so an under-dot stays
with its letter; see bbox_layout) and writes the reference outside Git.

Each papyrus line becomes a string over the reader's 24 capitals (lunate sigma) plus '?':
- a letter the editors print, dotted (uncertain) or not, is that letter: it is on the papyrus;
- a letter inside square brackets is a restoration of lost papyrus, and an under-dot with no
  letter is an illegible trace; both become '?' (one unknown letter each). An under-dot set right
  after a letter, or after punctuation or a bracket that follows a letter, belongs to that letter;
  only one set after a space is a trace (the PDF's text layer moves dots off their letters, so the
  text is rebuilt from word boxes, see bbox_layout);
- accents, breathings, punctuation, hyphens, braces and spaces are dropped (scriptio continua);
  a letter in braces (written but deleted by the editors) stays, since it is on the papyrus;
- anything in round brackets (Leiden: letters the scribe did not write) is dropped;
- a Latin "o" printed among Greek letters (one typo, col. 14 l. 3) is read as omicron;
- the English translation (right of the Greek) and the apparatus (below each column) are dropped;
- "ll. 1-2 traces" and the like stand for lines with nothing legible and are kept as empty lines,
  so line numbers stay right; every column's numbered lines (5, 10) are checked against the count.

  python scripts/letters/p1667_text.py PAPER.pdf OUT.json
"""
import html
import json
import re
import subprocess
import unicodedata
from pathlib import Path

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"
START = "Coll. 1-4 traces"
END = "Validation and papyrological review"
GAP = re.compile(r"\s{8,}")          # the translation sits at least 8 spaces right of the Greek
COL = re.compile(r"^\s*Col\. (\d+)")
NUMBERED = re.compile(r"^\s*(\d+)\s{3,}(\S.*)$")      # a text line with its line number
APPARATUS = re.compile(r"^\s{0,3}\d+\s(?=\S)")      # apparatus entries: a number, one space, text
TRACES = re.compile(r"^\s*(ll?)\. (\d+)(?:-(\d+))? (traces|tantum vestigia)")
PAGE_FURNITURE = re.compile(r"^\s*(\d+|Angelotti et al\.|Complete virtual unwrapping and reading of a rolled Herculaneum papyrus)\s*$")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
DOT = "̣"


def letter(ch):
    """Reader capital for a Greek base letter, or None."""
    if ch in "σςϲΣϹ":
        return "Ϲ"
    if ch in "oO":
        return "Ο"
    up = ch.upper()
    return up if up in ALPHABET else None


def normalize(text, starts=False):
    """Papyrus letters of one transcribed line: capitals, '?' for restored or illegible letters.

    With starts=True also returns a string of '1' and '0', one per letter: '1' where the edition
    prints a space (or the line begins) before that letter, so the words of the edition are known."""
    out, flags, depth, prev_base, space = [], [], 0, None, True
    if "]" in text and ("[" not in text or text.index("]") < text.index("[")):
        depth = 1                    # a line that opens inside a restoration carried from the line before
    text = re.sub(r"\([^()]*\)", "", text)
    for ch in unicodedata.normalize("NFD", text):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == DOT:
            if prev_base is None:    # an under-dot on no letter: an illegible trace
                out.append("?")
                flags.append("1" if space else "0")
                space = False
        elif unicodedata.combining(ch):
            continue
        else:
            b = letter(ch)
            if b is not None:
                out.append("?" if depth else b)
                flags.append("1" if space else "0")
                prev_base, space = b, False
                continue
            space = space or ch.isspace()
        if ch.isspace():
            prev_base = None         # punctuation and brackets set right after a letter keep its under-dot with it
    return ("".join(out), "".join(flags)) if starts else "".join(out)


def parse(layout_text):
    sec = layout_text[layout_text.index(START):layout_text.index(END)]
    cols, cur, in_app, problems = {}, None, False, []
    for raw in sec.split("\n")[1:]:
        m = COL.match(raw)
        if m:
            cur, in_app = int(m.group(1)), False
            cols[cur] = []
            continue
        if cur is None or in_app or not raw.strip() or PAGE_FURNITURE.match(raw):
            continue
        t = TRACES.match(raw)
        if t:
            a = int(t.group(2))
            b = int(t.group(3) or a)
            cols[cur] += [{"n": None, "text": "", "letters": "", "traces": True} for _ in range(a, b + 1)]
            continue
        if APPARATUS.match(raw) and not NUMBERED.match(raw) and cols[cur]:
            in_app = True
            continue
        nm = NUMBERED.match(raw)
        n = int(nm.group(1)) if nm else None
        rest = nm.group(2) if nm else raw
        left = next((g for g in GAP.split(rest.rstrip()) if g.strip()), "")
        if not (GREEK.search(left) or DOT in left):
            continue                 # translation continuation or a line with no Greek
        body = left.strip()
        letters, starts = normalize(body, starts=True)
        cols[cur].append({"n": n, "text": body.strip(), "letters": letters, "starts": starts})
    for c, lines in cols.items():
        stray = [i for i, L in enumerate(lines) if L["letters"] and set(L["letters"]) == {"?"}
                 and "[" not in L["text"] and "]" not in L["text"] and L["n"] is None]
        for i, L in enumerate(lines):
            if L["n"] is not None and L["n"] != i + 1:
                drop = [s for s in stray if s < i]
                if len(drop) == i + 1 - L["n"]:
                    for s in reversed(drop):
                        lines.pop(s)
                    problems.append(f"col {c}: dropped {len(drop)} stray dot-only line(s) to fit line {L['n']}")
                    break
        for i, L in enumerate(lines):
            if L["n"] is not None and L["n"] != i + 1:
                problems.append(f"col {c}: line numbered {L['n']} is line {i + 1}")
    return cols, problems


WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="[\d.]+">(.*?)</word>')
JOIN_PT = 1.2       # words closer than this (points) are one word
DOT_JOIN_PT = 2.0   # a word that starts with an under-dot this close joins the word before: the dot is under
                    # that word's last letter (measured: such gaps are -5.4 to 1.6 pt; a free trace sits
                    # at least 2.5 pt away, usually 5 pt, a full space)
TEXT_X_MAX = 280.0  # lines starting right of this are the translation column
SPACE_PT = 12.0     # up to this gap: one space; up to COLUMN_PT: four (line number to text)
COLUMN_PT = 40.0    # wider gaps (text to translation) become ten spaces, so GAP splits them
LINE_PT = 1.2       # words whose tops differ by less than this are on one printed line


def bbox_layout(pdf):
    """The PDF's text rebuilt from word boxes (pdftotext -bbox), one printed line per text line.

    pdftotext -layout puts a space between a letter and the under-dot set just after it whenever
    their boxes do not touch, and normalize() would then read the dot as an illegible trace. Here
    a word starting with an under-dot closer than DOT_JOIN_PT to the word before is joined to it
    without a space, so the dot stays with its letter; a free trace is set a full space away from
    the letter before it and stays free. Lines carry no indentation (the parse tells line numbers
    from apparatus entries by the gap after the number), and lines that start in the translation
    column are left out."""
    raw = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, encoding="utf-8", check=True).stdout
    out = []
    for page in raw.split("<page ")[1:]:
        words = sorted(((float(y), float(x0), float(x1), html.unescape(w)) for x0, y, x1, w in WORD.findall(page)))
        lines, cur = [], []
        for w in words:
            if cur and w[0] - cur[0][0] >= LINE_PT:
                lines.append(cur)
                cur = []
            cur.append(w)
        if cur:
            lines.append(cur)
        for ln in lines:
            ln.sort(key=lambda w: w[1])
            if ln[0][1] > TEXT_X_MAX:
                continue
            s, prev = "", None
            for _, x0, x1, w in ln:
                if prev is not None:
                    gap = x0 - prev
                    if gap < JOIN_PT or (w.startswith(DOT) and gap < DOT_JOIN_PT):
                        pass
                    else:
                        s += " " if gap <= SPACE_PT else "    " if gap <= COLUMN_PT else " " * 10
                s += w
                prev = x1 if prev is None else max(prev, x1)   # an under-dot's zero-width box sits inside its letter's
            out.append(s)
    return "\n".join(out)


def main(pdf, out):
    txt = bbox_layout(pdf)
    cols, problems = parse(txt)
    letters = sum(sum(c.isalpha() for c in L["letters"]) for v in cols.values() for L in v)
    unknown = sum(L["letters"].count("?") for v in cols.values() for L in v)
    res = {"source": "arXiv 2606.29085v1, Methods, Complete PHerc. 1667 transcription and translation",
           "rule": __doc__.split("\n\n")[1], "alphabet": ALPHABET,
           "columns": {str(c): [{"line": i + 1, "letters": L["letters"], "word_starts": L.get("starts", ""),
                                 "printed": L["text"]}
                                for i, L in enumerate(v)] for c, v in sorted(cols.items())},
           "visible_letters": letters, "unknown_letters": unknown, "problems": problems}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"{len(cols)} columns, {sum(len(v) for v in cols.values())} lines, {letters} visible letters, "
          f"{unknown} unknown; problems: {problems or 'none'}")


def parse_args(argv=None):
    """PAPER.pdf and OUT.json; anything else stops with the usage."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", help="a local copy of arXiv 2606.29085 (v1)")
    ap.add_argument("out", help="the reference JSON to write, such as work/p1667/text.json")
    return ap.parse_args(argv)


if __name__ == "__main__":
    a = parse_args()
    if getattr(a, "out", None):   # the folder first, so a long read never ends on a missing folder
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    main(a.pdf, a.out)
