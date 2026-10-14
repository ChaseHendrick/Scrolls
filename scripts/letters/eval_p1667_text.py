"""Read PHerc. 1667 segments that have no ink labels and score the reads against the published text.

The earlier PHerc. 1667 tests scored the reader on letters drawn in the official ink labels, on
segments whose maps came from a model trained on those labels. This test uses the segments with no
labels: each segment's 2.4 um ink-detection map is cut whole to the 38 um grid of the earlier tests
(`cut`, block 16) and read once, the reader finding the columns, lines and letters itself
(columns="auto", lines=None), ink only. The reference is the published transcription of columns 5 to
22 (arXiv 2606.29085, Methods; `p1667_text.py` turns it into one string per papyrus line, '?' for a
restored or illegible letter). Nobody says which segment holds which column, so every read line is
aligned against every reference line.

Score of a read line against a reference line: local alignment (Smith-Waterman), match +1, mismatch
-1, gap -1, a reference '?' against any read letter 0. A read line's score is its best over the
reference lines; a text's total T is the sum over all read lines. The same reads are scored against
three sets of N_DECOYS decoy texts with exactly the reference's shape (line lengths, '?' places, empty
lines), poured into the reference's visible places in reading order:
- `words`: the reference's own words (runs of visible letters between the edition's spaces, '?' and
  line ends) in a random order, so the decoy has the same vocabulary and letters but other lines;
- `corpus`: consecutive letters of other Greek prose (Perseus editions of Diogenes Laertius,
  Xenophon and Plato, none of them Philodemus);
- `shuffled`: the reference's own visible letters permuted across their places.
- `shifted`: the reference's own visible letters in reading order, moved round by k places
  (k = 1/100 to 99/100 of the visible letters), so every word and every junction of words is kept
  and only where the lines and lacunae cut the text changes.
Reads that carry the published text should score higher on it than on every decoy; reads that only
carry Greek letter statistics or the reader's letter habits should not. Greek-like strings with no
link to the text (samples of the letter language model) beat the shuffled decoys every time and
often the word and corpus decoys, and the shifted ones only rarely (the dry run of 9 October 2026,
summarized in docs/logs/2026-10-14-letter-reader.md), so `shifted` is the decisive set and a line's
excess is measured against it. p = (1 + decoys with T at least the real T) / (1 + N_DECOYS).

The sums above reward any Greek-like read a little more on the real text than on any decoy built
from it or from other Greek (the dry run), so the decision rests on order instead. A pair is two
consecutive found lines of one reader column whose best lines (each unique and scoring at least
PAIR_MIN) are lines of one published column, in order, 1 to PAIR_STEP apart: reads that carry the
text land on the text line after line, while Greek-like noise almost never does. Pairs are counted
for the real text and every decoy; U1 passes (pairs_pass) when the real text has at least
PAIR_FLOOR pairs and more than every decoy of the PAIR_SETS.

  python scripts/letters/eval_p1667_text.py cut MAPS_DIR OUT_DIR [SEGMENT ...]
  python scripts/letters/eval_p1667_text.py read NPY_DIR --weights W --letter-px 86|auto|GROUPS.json --out READ.json
  python scripts/letters/eval_p1667_text.py decoys REFERENCE.json CORPUS.xml [CORPUS.xml ...] --out DECOYS.json
  python scripts/letters/eval_p1667_text.py score READ.json DECOYS.json --out SCORE.json
  python scripts/letters/eval_p1667_text.py compare A_SCORE.json B_SCORE.json

--weights takes a linenet-v1 .npz or a released model name such as letters-v2-real (recorded as given).
`decoys` refuses a reference line holding a character outside the reader's alphabet ('?' aside).

Every string read is model output on a public ink map, not a reading.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit import letterread as R  # noqa: E402
from kit.letterlines import check_references  # noqa: E402

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"
MATCH, MISMATCH, GAP, WILD = 1, -1, -1, 0
BLOCK = -100                 # score against padding: no alignment uses it
N_DECOYS = 99
SETS = ("shifted", "words", "corpus", "shuffled")
EXCESS_SET = "shifted"       # a line's excess: its real score minus its mean over these decoys
PAIR_MIN = 5                 # a read line counts in a pair only with a unique best line scoring at least this
PAIR_STEP = 2                # the second line's best line is 1 or 2 lines below the first's (the line finder can skip one)
PAIR_FLOOR = 3               # U1 needs at least this many pairs
PAIR_SETS = ("words", "corpus", "shuffled")   # the shifted decoys contain the real lines, cut elsewhere, so they
                                             # make pairs where the cuts fall close to the real ones; not used here
SEED = 0
NULLS = 2
BATCH = 16                   # read lines aligned at once
WILD_CODE, PAD_CODE = len(ALPHABET), len(ALPHABET) + 1
_IDX = {c: i for i, c in enumerate(ALPHABET)}


# ------------------------------------------------------------------ maps

def cut_whole(tif, out):
    """A whole 2.4 um map on the 38 um grid (block 16, 0..1), cut in bands to keep memory low."""
    import tifffile
    import zarr
    from p1667_mapcrops import BAND, F, cut
    z = zarr.open(tifffile.imread(tif, aszarr=True), mode="r")
    ny, nx = z.shape[0] // F, z.shape[1] // F
    m = np.concatenate([cut(z, y * F, 0, min(BAND, ny - y), nx) for y in range(0, ny, BAND)])
    np.save(out, m)
    return m.shape


# ------------------------------------------------------------------ reading

def read_maps(npy_dir, weights, letter_px):
    """Read every <segment>.npy whole; keep each found line's letters (all of them, as in the region test)."""
    npy_dir = Path(npy_dir)
    heights = None
    if letter_px not in ("auto",) and not str(letter_px).replace(".", "", 1).isdigit():
        heights = {s: st["letter_h"] for s, st in json.loads(Path(letter_px).read_text())["stats"].items()}
    net = R.load_weights(weights)   # a .npz path or a released model name; recorded as given
    segs = {}
    for f in sorted(npy_dir.glob("*.npy")):
        seg = f.stem
        h = None if letter_px == "auto" else heights[seg] if heights else float(letter_px)
        res = R.analyze(np.load(f), net, letter_px=h, lines=None, columns="auto", nulls=NULLS, seed=SEED)
        lines = [{"column": L["column"], "y": L["y"], "read": "".join(l["glyph"] for l in L["letters"]),
                  "kept": "".join("1" if l["kept"] else "0" for l in L["letters"]),
                  "x": [round(0.5 * (l["box"][2] + l["box"][3]), 1) for l in L["letters"]]} for L in res["lines"]]
        segs[seg] = {"shape": list(np.load(f, mmap_mode="r").shape), "letter_px_used": res["letter_px"],
                     "columns": [[c["x0"], c["x1"], c["deskew_deg"]] for c in res["columns"]],
                     "letters_kept": res["control"]["letters_kept"],
                     "null_letters_kept": res["control"]["null_letters_kept"], "lines": lines}
        print(seg, len(res["columns"]), "columns", len(lines), "lines", res["control"]["letters_kept"], "kept",
              res["control"]["null_letters_kept"], "null", flush=True)
    kept = sum(s["letters_kept"] for s in segs.values())
    null = [sum(s["null_letters_kept"][k] for s in segs.values()) for k in range(NULLS)]
    return {"note": R.NOTE, "weights": str(weights), "letter_px": letter_px, "nulls": NULLS, "seed": SEED,
            "control": {"letters_kept": kept, "null_letters_kept": null, "passes": kept > 3 * max(1, max(null))},
            "segments": segs}


# ------------------------------------------------------------------ decoys

def check_reference(reference, source="the reference"):
    """SystemExit, naming each line and character and printing the alphabet, when a line of a p1667_text.py
    reference ({"columns": {column: [{"line", "letters"}, ...]}}) holds a character the reader does not write.

    The alignment scores such a character as padding (BLOCK), which no alignment uses, so a Latin
    look-alike or a final sigma would silently cost the real text its matches; '?' is the wildcard."""
    lines = {f"column {c} line {L.get('line')}": L["letters"] for c, v in reference["columns"].items()
             for L in v if L.get("letters")}
    try:
        check_references(lines, alphabet=ALPHABET, source=source)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    return reference


def corpus_letters(xml_files):
    from kit import greeklm
    return "".join(greeklm.clean_text(greeklm.tei_text(Path(p).read_text(encoding="utf-8"))) for p in sorted(xml_files))


def word_chunks(lines):
    """Runs of visible letters in reading order, cut at the edition's word starts, at '?' and at line ends."""
    chunks, cur = [], ""
    for s, w in lines:
        w = w or "1" * len(s)
        for ch, f in zip(s, w):
            if (ch == "?" or f == "1") and cur:
                chunks.append(cur)
                cur = ""
            if ch != "?":
                cur += ch
        if cur:
            chunks.append(cur)
            cur = ""
    return chunks


def make_decoys(reference, corpus, n=N_DECOYS, seed=SEED):
    """Real text plus n decoys in each set of SETS, all with the reference's exact shape."""
    lines = [(c, L["line"], L["letters"], L.get("word_starts", "")) for c, v in
             sorted(reference["columns"].items(), key=lambda kv: int(kv[0])) for L in v if L["letters"]]
    visible = [ch for _, _, s, _ in lines for ch in s if ch != "?"]
    V = len(visible)
    block = len(corpus) // n
    if block < V:
        raise ValueError(f"corpus too short: {len(corpus)} letters for {n} decoys of {V}")
    rng = np.random.default_rng(seed)

    def fill(letters):
        it, out = iter(letters), []
        for _, _, s, _ in lines:
            out.append("".join(ch if ch == "?" else next(it) for ch in s))
        return out
    starts = [int(k * block + rng.integers(0, block - V + 1)) for k in range(n)]
    corpus_d = [fill(corpus[s:s + V]) for s in starts]
    shuffled_d = [fill([visible[i] for i in rng.permutation(V)]) for _ in range(n)]
    chunks = word_chunks([(s, w) for _, _, s, w in lines])
    words_d = [fill("".join(chunks[i] for i in rng.permutation(len(chunks)))) for _ in range(n)]
    shifts = [int(round(k * V / (n + 1))) for k in range(1, n + 1)]
    shifted_d = [fill(visible[s:] + visible[:s]) for s in shifts]
    return {"lines": [[c, l] for c, l, _, _ in lines], "real": [s for _, _, s, _ in lines], "corpus": corpus_d,
            "shuffled": shuffled_d, "words": words_d, "shifted": shifted_d, "corpus_starts": starts,
            "shifts": shifts, "visible_letters": V, "word_chunks": len(chunks), "seed": seed}


# ------------------------------------------------------------------ alignment

def _encode(strings, width, wild=True):
    a = np.full((len(strings), width), PAD_CODE, np.int8)
    for i, s in enumerate(strings):
        for j, ch in enumerate(s[:width]):
            a[i, j] = WILD_CODE if (wild and ch == "?") else _IDX.get(ch, PAD_CODE)
    return a


def _table():
    t = np.full((PAD_CODE + 1, PAD_CODE + 1), MISMATCH, np.int8)
    np.fill_diagonal(t, MATCH)
    t[:, WILD_CODE] = WILD
    t[PAD_CODE, :] = BLOCK
    t[:, PAD_CODE] = BLOCK
    return t


def local_scores(reads, refs):
    """Best local alignment score of every read string against every reference string: (len(reads), len(refs))."""
    out = np.zeros((len(reads), len(refs)), np.int16)
    if not reads or not refs:
        return out
    tab = _table()
    W = max(1, max(len(s) for s in refs))
    if W > 60:
        raise ValueError("reference lines longer than 60 letters would overflow the int8 scores")
    Rc = _encode(refs, W)
    k = np.arange(1, W + 1, dtype=np.int8)
    order = sorted(range(len(reads)), key=lambda i: len(reads[i]))
    for b0 in range(0, len(order), BATCH):
        idx = order[b0:b0 + BATCH]
        m = max(len(reads[i]) for i in idx)
        if m == 0:
            continue
        Q = _encode([reads[i] for i in idx], m, wild=False)
        H = np.zeros((len(idx), len(refs), W + 1), np.int8)
        best = np.zeros((len(idx), len(refs)), np.int8)
        for i in range(m):
            sub = tab[Q[:, i]][:, Rc]                       # (batch, refs, W)
            hp = np.maximum(H[:, :, :-1] + sub, H[:, :, 1:] + GAP)
            np.maximum(hp, 0, out=hp)
            # gaps along the reference: H[j] = max over k <= j of hp[k] - (j - k)
            hn = np.maximum.accumulate(hp + k, axis=2) - k
            H[:, :, 1:] = hn
            np.maximum(best, hn.max(axis=2), out=best)
        out[idx] = best
    return out


def naive_local(a, b):
    """Plain dynamic-programming version of one alignment, for tests."""
    def s(x, y):
        if y == "?":
            return WILD
        return MATCH if x == y else MISMATCH
    H = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    best = 0
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            H[i][j] = max(0, H[i - 1][j - 1] + s(a[i - 1], b[j - 1]), H[i - 1][j] + GAP, H[i][j - 1] + GAP)
            best = max(best, H[i][j])
    return best


# ------------------------------------------------------------------ scoring

def score(read, decoys):
    """Per read line: best score against the real text and each decoy text; totals, p values and excess."""
    reads, where = [], []
    for seg, st in sorted(read["segments"].items()):
        for i, L in enumerate(st["lines"]):
            reads.append(L["read"])
            where.append((seg, i))
    sets = [k for k in SETS if k in decoys]
    texts = [decoys["real"]] + [t for k in sets for t in decoys[k]]
    nl, n = len(decoys["real"]), len(decoys[sets[0]])
    flat = [s for t in texts for s in t]
    S = local_scores(reads, flat).reshape(len(reads), len(texts), nl).astype(np.int32)
    best = S.max(axis=2)                                   # (reads, texts)
    args = S.argmax(axis=2)
    unique = (S == best[:, :, None]).sum(axis=2) == 1
    del S
    arg = args[:, 0]
    real = best[:, 0]
    # pairs: consecutive found lines of one reader column whose best lines are, in order, lines of one
    # published column 1 to PAIR_STEP apart
    col = np.array([int(c) for c, _ in decoys["lines"]])
    num = np.array([int(l) for _, l in decoys["lines"]])
    pairs = np.zeros(len(texts), np.int64)
    seg_pairs = {}
    for r in range(len(reads) - 1):
        (s0, i0), (s1, i1) = where[r], where[r + 1]
        if s0 != s1 or read["segments"][s0]["lines"][i0].get("column") != read["segments"][s1]["lines"][i1].get("column"):
            continue
        a0, a1 = args[r], args[r + 1]
        step = num[a1] - num[a0]
        ok = ((best[r] >= PAIR_MIN) & (best[r + 1] >= PAIR_MIN) & unique[r] & unique[r + 1] & (col[a1] == col[a0])
              & (step >= 1) & (step <= PAIR_STEP))
        pairs += ok
        seg_pairs[s0] = seg_pairs.get(s0, 0) + int(ok[0])
    dec = {k: best[:, 1 + i * n:1 + (i + 1) * n] for i, k in enumerate(sets)}
    T = best.sum(axis=0)
    Td = {k: T[1 + i * n:1 + (i + 1) * n] for i, k in enumerate(sets)}
    ex_key = EXCESS_SET if EXCESS_SET in dec else sets[0]
    rows, per_seg = [], {}
    for r, (seg, i) in enumerate(where):
        row = {"segment": seg, "line": i, "read": reads[r], "real": int(real[r]),
               "best_ref": decoys["lines"][int(arg[r])] if real[r] > 0 else None}
        for k in sets:
            row[k + "_mean"], row[k + "_max"] = round(float(dec[k][r].mean()), 3), int(dec[k][r].max())
        row["excess"] = round(float(real[r] - dec[ex_key][r].mean()), 3)
        rows.append(row)
        d = per_seg.setdefault(seg, {"lines": 0, "real": 0, "pairs": seg_pairs.get(seg, 0),
                                     **{"excess_" + k: 0.0 for k in sets}})
        d["lines"] += 1
        d["real"] += int(real[r])
        for k in sets:
            d["excess_" + k] += float(real[r] - dec[k][r].mean())
    for d in per_seg.values():
        for k in sets:
            d["excess_" + k] = round(d["excess_" + k], 3)
        d["excess"] = d["excess_" + ex_key]
    summary = {"read_lines": len(reads), "letters_read": int(sum(len(s) for s in reads)), "T_real": int(T[0]),
               "pairs_real": int(pairs[0])}
    pd_sets = {k: pairs[1 + i * n:1 + (i + 1) * n] for i, k in enumerate(sets)}
    for k in sets:
        summary.update({f"pairs_{k}_max": int(pd_sets[k].max()),
                        f"p_pairs_{k}": round((1 + int((pd_sets[k] >= pairs[0]).sum())) / (1 + n), 4)})
    pooled = np.concatenate([pd_sets[k] for k in PAIR_SETS if k in pd_sets] or [np.zeros(0, np.int64)])
    summary.update({"pairs_decoys_max": int(pooled.max()) if len(pooled) else 0,
                    "p_pairs_pooled": round((1 + int((pooled >= pairs[0]).sum())) / (1 + len(pooled)), 4),
                    "pairs_pass": bool(pairs[0] >= PAIR_FLOOR and (not len(pooled) or pairs[0] > pooled.max()))})
    for k in sets:
        summary.update({f"T_{k}_mean": round(float(Td[k].mean()), 1), f"T_{k}_max": int(Td[k].max()),
                        f"p_{k}": round((1 + int((Td[k] >= T[0]).sum())) / (1 + n), 4),
                        f"excess_{k}": round(float((real - dec[k].mean(axis=1)).sum()), 1),
                        f"lines_beating_all_{k}": int(((real[:, None] > dec[k]).all(axis=1) & (real > 0)).sum())})
    summary.update({"excess_against": ex_key, "expected_lines_by_chance": round(len(reads) / (1 + n), 1),
                    "reader_control_passes": read["control"]["passes"]})
    return {"note": R.NOTE, "weights": read["weights"], "letter_px": read["letter_px"],
            "scoring": {"match": MATCH, "mismatch": MISMATCH, "gap": GAP, "wildcard": WILD, "decoys_per_set": n,
                        "sets": sets, "pair_min": PAIR_MIN, "pair_step": PAIR_STEP, "pair_floor": PAIR_FLOOR,
                        "pair_sets": [k for k in PAIR_SETS if k in sets]},
            "summary": summary, "segments": per_seg, "T_decoys": {k: [int(v) for v in Td[k]] for k in sets},
            "lines": rows}


def compare(A, B, n=20000, seed=SEED):
    """Paired bootstrap over segments of B minus A: pairs (decisive) and excess (reported); positive favours B."""
    segs = sorted(set(A["segments"]) & set(B["segments"]))
    rng = np.random.default_rng(seed)
    idx = [rng.integers(0, len(segs), len(segs)) for _ in range(n)]
    out = {"segments": len(segs), "resamples": n}
    for key in ("pairs", "excess"):
        a = np.array([A["segments"][s][key] for s in segs], float)
        b = np.array([B["segments"][s][key] for s in segs], float)
        diffs = np.array([(b[i] - a[i]).sum() for i in idx])
        out[key] = {"a": round(float(a.sum()), 1), "b": round(float(b.sum()), 1),
                    "diff_b_minus_a": round(float((b - a).sum()), 1),
                    "ci95": [round(float(v), 1) for v in np.percentile(diffs, [2.5, 97.5])]}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut")
    c.add_argument("maps_dir")
    c.add_argument("out_dir")
    c.add_argument("segments", nargs="*")
    r = sub.add_parser("read")
    r.add_argument("npy_dir")
    r.add_argument("--weights", required=True)
    r.add_argument("--letter-px", required=True)
    r.add_argument("--out", required=True)
    d = sub.add_parser("decoys")
    d.add_argument("reference")
    d.add_argument("corpus", nargs="+")
    d.add_argument("--out", required=True)
    s = sub.add_parser("score")
    s.add_argument("read")
    s.add_argument("decoys")
    s.add_argument("--out", required=True)
    m = sub.add_parser("compare")
    m.add_argument("a")
    m.add_argument("b")
    a = ap.parse_args()
    if getattr(a, "out", None):   # the folder first, so a long read never ends on a missing folder
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == "cut":
        out = Path(a.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        tifs = sorted(Path(a.maps_dir).glob("*.tif"))
        for t in tifs:
            if not a.segments or t.stem in a.segments:
                print(t.stem, cut_whole(t, out / f"{t.stem}.npy"), flush=True)
    elif a.cmd == "read":
        res = read_maps(a.npy_dir, a.weights, a.letter_px)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(res["control"]))
    elif a.cmd == "decoys":
        ref = check_reference(json.loads(Path(a.reference).read_text(encoding="utf-8")), Path(a.reference).name)
        res = make_decoys(ref, corpus_letters(a.corpus))
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False) + "\n", encoding="utf-8")
        print(len(res["real"]), "lines,", res["visible_letters"], "visible letters,", res["word_chunks"],
              "word chunks,", " + ".join(f"{len(res[k])} {k}" for k in SETS), "decoys")
    elif a.cmd == "score":
        rd = json.loads(Path(a.read).read_text(encoding="utf-8"))
        dc = json.loads(Path(a.decoys).read_text(encoding="utf-8"))
        res = score(rd, dc)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(res["summary"], ensure_ascii=False))
    else:
        A, B = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (a.a, a.b))
        print(json.dumps(compare(A, B)))


if __name__ == "__main__":
    R.utf8_console()   # Greek prints in a pipe and on a Windows console
    main()
