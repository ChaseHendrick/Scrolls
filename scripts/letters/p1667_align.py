"""Place PHerc. 1667's published lines on its ink maps with no person: the step that turns the published
text into real ink-map lines for training and testing the letter reader
(docs/letter-reader.md, Reproduce the benchmarks).

1. read: each segment's 2.4 um map (on the 38 um grid of eval_p1667_text.py cut) is split into text columns
   at gutters (split_columns: a dip in the papyrus-normalised column profile, at least GUTTER_DEPTH below
   the peaks on both sides within GUTTER_REACH letter heights; image only), and each column is read by a
   reader (kit.letterread.analyze, columns off, lines found from the image), keeping every letter's box.
2. align: every found line is scored against every published line by local alignment (match +1,
   mismatch -1, gap -1, '?' 0; eval_p1667_text.local_scores). For each reader column the best order-keeping
   match of found lines to the lines of each published column (gain = score above FLOOR) picks its column;
   its p value is the share of SHIFTED decoy texts (the visible letters in reading order moved round, so
   every word survives and only where the lines fall changes) whose best column sum is at least as high,
   and a column is accepted at p <= P_ACCEPT. Matched lines scoring at least ANCHOR are anchors: their
   letter-to-letter alignment gives points (x, y) on the map for (published line k, letter j).
3. Geometry, per segment and published column, from all its anchor points: rows y = a + b k + s x (outliers
   beyond ANCHOR_TOL line pitches dropped) and the left margin x = x0 + w j (common letter pitch w, one
   intercept per line, x0 their median: ancient columns are left-justified). Every published line k of the
   column then has a crop: centred on its fitted row, from x0 - MARGIN w to x0 + (longest line + MARGIN) w.
   Nothing in a crop depends on that line's own letters beyond its line number.
4. crops: cut those bands at the reader's working scale, for training or testing.

The alignment depends only on the images, the reading model used here and the published text; it is
frozen (its digest recorded) before any model it is used to test reads a crop.

  python scripts/letters/p1667_align.py read NPY_DIR --weights W --out READ.json
  python scripts/letters/p1667_align.py align READ.json TEXT.json --out ALIGN.json
  python scripts/letters/p1667_align.py crops ALIGN.json NPY_DIR --columns 9,10 [--best] --out LINES.npz
  python scripts/letters/p1667_align.py show ALIGN.json

Model output on public maps of a published scroll; not a reading.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_p1667_text import local_scores  # noqa: E402
from kit import letterread as R  # noqa: E402

LETTER_PX = 86.0     # letter height on the 38 um grid (median of the labelled segments)
NET_PX = 16          # the reader's working letter height
BAND = (1.1, 1.15)   # band rows above and below the line centre, in letter heights (letterdata.BAND_*)
GUTTER_DEPTH = 0.15  # a gutter's profile is at least this far below the lower of its two neighbouring peaks
GUTTER_REACH = 12.0  # letter heights either side to find those peaks
GUTTER_MIN_W = 10.0  # columns at least this many letter heights wide
FLOOR = 3            # local score Greek-like noise reaches on a published line
ANCHOR = 5           # a matched line this good gives anchor points
ANCHOR_TOL = 0.3     # anchor row residual allowed, in line pitches
MARGIN = 0.6         # crop margin, in letter pitches
N_SHIFTED = 99
P_ACCEPT = 0.01
NULLS = 2
SEED = 0


# ------------------------------------------------------------------ columns and reading

def split_columns(a, h=LETTER_PX):
    """Spans (x0, x1) of text columns of a normalised map with letters h px tall: cut at gutters."""
    pap = a > 0.02
    den = pap.sum(axis=0)
    ok = den > 0.2 * a.shape[0]
    if not ok.any():
        return [(0, a.shape[1])]
    prof = np.where(ok, a.sum(axis=0) / np.maximum(den, 1), 0.0)
    prof = np.where(ok, prof, prof[ok].min())
    p = R._smooth1d(prof.astype(np.float64), 1.0 * h)
    W, r, reach = len(p), int(6 * h), int(GUTTER_REACH * h)
    cuts = []
    for x in np.argsort(p):
        if not ok[x] or p[x] > p[max(0, x - r):x + r + 1].min():
            continue
        if p[x] > (1 - GUTTER_DEPTH) * min(p[max(0, x - reach):x + 1].max(), p[x:x + reach + 1].max()):
            continue
        if x < 0.5 * GUTTER_MIN_W * h or W - x < 0.5 * GUTTER_MIN_W * h:
            continue
        if all(abs(x - c) >= GUTTER_MIN_W * h for c in cuts):
            cuts.append(int(x))
    edges = [0] + sorted(cuts) + [W]
    return list(zip(edges[:-1], edges[1:]))


def read_maps(npy_dir, weights):
    net = R.LineNet(weights)
    segs = {}
    for f in sorted(Path(npy_dir).glob("*.npy")):
        img = np.load(f)
        a = R.normalize(img, "bright")
        cols = []
        for x0, x1 in split_columns(a):
            res = R.analyze(img[:, x0:x1], net, letter_px=LETTER_PX, lines=None, columns="off", nulls=NULLS, seed=SEED)
            lines = [{"y": L["y"], "read": "".join(l["glyph"] for l in L["letters"]),
                      "kept": "".join("1" if l["kept"] else "0" for l in L["letters"]),
                      "x": [round(x0 + 0.5 * (l["box"][2] + l["box"][3]), 1) for l in L["letters"]],
                      "ly": [round(0.5 * (l["box"][0] + l["box"][1]), 1) for l in L["letters"]]} for L in res["lines"]]
            cols.append({"span": [x0, x1], "deskew_deg": res["deskew_deg"], "letters_kept": res["control"]["letters_kept"],
                         "null_letters_kept": res["control"]["null_letters_kept"], "lines": lines})
        segs[f.stem] = {"shape": list(img.shape), "columns": cols}
        print(f.stem, len(cols), "columns", [len(c["lines"]) for c in cols], "lines", flush=True)
    return {"note": R.NOTE, "weights": str(weights), "letter_px": LETTER_PX, "segments": segs}


# ------------------------------------------------------------------ alignment

def text_lines(text):
    """[(column, line, letters)] in reading order, empty lines kept (they hold a place)."""
    return [(int(c), L["line"], L["letters"]) for c, v in sorted(text["columns"].items(), key=lambda kv: int(kv[0]))
            for L in v]


def shifted_texts(lines, n=N_SHIFTED):
    """n decoys: the visible letters in reading order moved round by k places, poured back into the same shape."""
    vis = [ch for _, _, s in lines for ch in s if ch != "?"]
    V = len(vis)
    out = []
    for k in range(1, n + 1):
        s = int(round(k * V / (n + 1)))
        it = iter(vis[s:] + vis[:s])
        out.append(["".join(ch if ch == "?" else next(it) for ch in t) for _, _, t in lines])
    return out


def order_match(G):
    """Best order-keeping match on gain matrix G (found lines x published lines): (sum, [(i, j)])."""
    n, m = G.shape
    D = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = max(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1] + G[i - 1, j - 1])
    pairs, i, j = [], n, m
    while i > 0 and j > 0:
        if G[i - 1, j - 1] > 0 and D[i, j] == D[i - 1, j - 1] + G[i - 1, j - 1]:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif D[i, j] == D[i - 1, j]:
            i -= 1
        else:
            j -= 1
    return float(D[n, m]), pairs[::-1]


def column_sums(S, col_of):
    G = np.maximum(0, S.astype(np.float64) - FLOOR)
    return {c: order_match(G[:, idx]) for c, idx in col_of.items()}


def local_pairs(a, b):
    """Letter pairs (i in a, j in b) matched by the best local alignment (same scores as local_scores)."""
    n, m = len(a), len(b)
    H = np.zeros((n + 1, m + 1), int)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = 0 if b[j - 1] == "?" else (1 if a[i - 1] == b[j - 1] else -1)
            H[i, j] = max(0, H[i - 1, j - 1] + s, H[i - 1, j] - 1, H[i, j - 1] - 1)
    i, j = (int(v) for v in np.unravel_index(int(H.argmax()), H.shape))
    out = []
    while i > 0 and j > 0 and H[i, j] > 0:
        s = 0 if b[j - 1] == "?" else (1 if a[i - 1] == b[j - 1] else -1)
        if H[i, j] == H[i - 1, j - 1] + s:
            if s == 1:
                out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif H[i, j] == H[i - 1, j] - 1:
            i -= 1
        else:
            j -= 1
    return out[::-1]


def fit_rows(pts, pitch_guess):
    """y = a + b k + s x from points [(x, y, k)], dropping the worst while its residual exceeds ANCHOR_TOL pitches."""
    pts = list(pts)
    while True:
        P = np.array(pts, float)
        ks = set(P[:, 2])
        if len(ks) >= 2:
            A = np.c_[np.ones(len(P)), P[:, 2], P[:, 0]]
            (a, b, s), *_ = np.linalg.lstsq(A, P[:, 1], rcond=None)
            if not 0.5 * pitch_guess < b < 1.6 * pitch_guess:
                b = pitch_guess
                A2 = np.c_[np.ones(len(P)), P[:, 0]]
                (a, s), *_ = np.linalg.lstsq(A2, P[:, 1] - b * P[:, 2], rcond=None)
        else:
            b = pitch_guess
            A2 = np.c_[np.ones(len(P)), P[:, 0]]
            (a, s), *_ = np.linalg.lstsq(A2, P[:, 1] - b * P[:, 2], rcond=None) if len(P) > 1 else ((P[0, 1] - b * P[0, 2], 0.0),)
        res = np.abs(P[:, 1] - (a + b * P[:, 2] + s * P[:, 0])) / b
        w = int(res.argmax())
        if res[w] <= ANCHOR_TOL or len(pts) <= 3:
            return float(a), float(b), float(s), len(pts)
        pts.pop(w)


def fit_margin(pts):
    """Common letter pitch w and left margin x0 from points [(x, k, j)]: x = c_k + w j, x0 = median c_k."""
    by = {}
    for x, k, j in pts:
        by.setdefault(k, []).append((x, j))
    num = den = 0.0
    for v in by.values():
        if len(v) >= 2:
            X = np.array(v, float)
            xm, jm = X[:, 0].mean(), X[:, 1].mean()
            num += ((X[:, 0] - xm) * (X[:, 1] - jm)).sum()
            den += ((X[:, 1] - jm) ** 2).sum()
    w = num / den if den > 0 else 0.0
    if not 0.5 * LETTER_PX < w < 1.6 * LETTER_PX:
        w = 0.95 * LETTER_PX
    c = [np.median([x - w * j for x, j in v]) for v in by.values()]
    return float(np.median(c)), float(w), len(by)


def align(read, text):
    lines = text_lines(text)
    refs = [s for _, _, s in lines]
    col_of = {}
    for j, (c, _, _) in enumerate(lines):
        col_of.setdefault(c, []).append(j)
    longest = {c: max(len(lines[j][2]) for j in idx) for c, idx in col_of.items()}
    decoys = shifted_texts(lines)
    units = [(seg, ci) for seg, st in sorted(read["segments"].items()) for ci, col in enumerate(st["columns"]) if col["lines"]]
    reads = [L["read"] for seg, ci in units for L in read["segments"][seg]["columns"][ci]["lines"]]
    S_real = local_scores(reads, refs)
    S_dec = [local_scores(reads, d) for d in decoys]
    out_units, groups, r0 = [], {}, 0
    for seg, ci in units:
        col = read["segments"][seg]["columns"][ci]
        n = len(col["lines"])
        S = S_real[r0:r0 + n]
        sums = column_sums(S, col_of)
        best_c = max(sums, key=lambda c: sums[c][0])
        best = sums[best_c][0]
        dec_best = [max(v[0] for v in column_sums(Sd[r0:r0 + n], col_of).values()) for Sd in S_dec]
        r0 += n
        p = (1 + sum(d >= best for d in dec_best)) / (1 + len(dec_best))
        ys = [L["y"] for L in col["lines"]]
        u = {"segment": seg, "column": ci, "span": col["span"], "found_lines": n, "published_column": best_c,
             "sum": round(best, 1), "decoy_max": round(max(dec_best), 1), "p": round(p, 4),
             "accepted": bool(best > 0 and p <= P_ACCEPT),
             "second": sorted(((round(v[0], 1), c) for c, v in sums.items() if c != best_c), reverse=True)[:2],
             "pitch": round(float(np.median(np.diff(ys))), 1) if n > 1 else None, "anchors": []}
        if u["accepted"]:
            cidx = col_of[best_c]
            for i, jj in sums[best_c][1]:
                j = cidx[jj]
                if S[i, j] < ANCHOR:
                    continue
                L = col["lines"][i]
                pts = [(L["x"][a], L["ly"][a], b) for a, b in local_pairs(L["read"], refs[j])]
                u["anchors"].append({"found": i, "line": lines[j][1], "score": int(S[i, j]), "text": refs[j],
                                     "read": L["read"], "points": pts})
                groups.setdefault((seg, best_c), []).append((u, lines[j][1], pts))
        out_units.append(u)
    geoms = []
    for (seg, c), items in sorted(groups.items()):
        rows = [(x, y, k) for _, k, pts in items for x, y, _ in pts]
        marg = [(x, k, j) for _, k, pts in items for x, _, j in pts]
        pitches = [u["pitch"] for u, _, _ in items if u["pitch"]]
        if len(rows) < 6:
            continue
        a, b, s, used = fit_rows(rows, float(np.median(pitches)) if pitches else 2.0 * LETTER_PX)
        x0, w, nk = fit_margin(marg)
        H, W = read["segments"][seg]["shape"]
        crops = []
        for j in col_of[c]:
            k = lines[j][1]
            cx0, cx1 = x0 - MARGIN * w, x0 + (longest[c] + MARGIN) * w
            cy = a + b * k + s * 0.5 * (cx0 + cx1)
            inside = 0 <= cy < H and cx1 > 0 and cx0 < W
            crops.append({"line": k, "text": refs[j], "y_mid": round(cy, 1), "x0": round(cx0, 1), "x1": round(cx1, 1),
                          "on_map": bool(inside)})
        geoms.append({"segment": seg, "published_column": c, "a": round(a, 2), "b": round(b, 2), "s": round(s, 5),
                      "x0": round(x0, 1), "w": round(w, 2), "anchor_lines": len({k for _, k, _ in items}),
                      "anchor_points": len(rows), "points_used": used, "crops": crops})
    body = {"note": "Model output on public maps of a published scroll; not a reading.",
            "read_weights": read.get("weights"), "letter_px": read.get("letter_px"),
            "rule": {"floor": FLOOR, "anchor": ANCHOR, "anchor_tol": ANCHOR_TOL, "margin": MARGIN,
                     "gutter_depth": GUTTER_DEPTH, "gutter_reach": GUTTER_REACH, "gutter_min_w": GUTTER_MIN_W,
                     "shifted_decoys": N_SHIFTED, "p_accept": P_ACCEPT},
            "units": out_units, "geometry": geoms}
    body["digest"] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return body


# ------------------------------------------------------------------ crops

def cut_crop(a, g, cr, f, net_px=NET_PX):
    """Band of one published line at the reader's scale: rows follow the fitted line, slope s included."""
    W = max(8, int(round((cr["x1"] - cr["x0"]) * f)))
    rows = int(round((BAND[0] + BAND[1]) * net_px))
    xs = cr["x0"] + (np.arange(W) + 0.5) / f
    yc = g["a"] + g["b"] * cr["line"] + g["s"] * xs
    vs = (np.arange(rows) + 0.5 - BAND[0] * net_px) / f
    Y = (yc[None, :] + vs[:, None]) * f - 0.5
    X = np.broadcast_to(xs[None, :] * f - 0.5, Y.shape)
    H, Wa = a.shape
    ok = (Y >= 0) & (Y <= H - 1) & (X >= 0) & (X <= Wa - 1)
    y0 = np.clip(np.floor(Y).astype(int), 0, H - 1)
    x0 = np.clip(np.floor(X).astype(int), 0, Wa - 1)
    y1, x1 = np.minimum(y0 + 1, H - 1), np.minimum(x0 + 1, Wa - 1)
    fy, fx = np.clip(Y - y0, 0, 1), np.clip(X - x0, 0, 1)
    v = (a[y0, x0] * (1 - fx) + a[y0, x1] * fx) * (1 - fy) + (a[y1, x0] * (1 - fx) + a[y1, x1] * fx) * fy
    return np.where(ok, v, 0.0).astype(np.float32), float(ok.mean())


def crops(align_, npy_dir, columns, best=False, min_on=0.6):
    """Bands, texts and places of every crop of the given published columns (best: one segment per column,
    the one with the most anchor lines, then points)."""
    f = NET_PX / float(align_["letter_px"])
    geoms = [g for g in align_["geometry"] if g["published_column"] in columns]
    if best:
        pick = {}
        for g in geoms:
            c = g["published_column"]
            if c not in pick or (g["anchor_lines"], g["anchor_points"]) > (pick[c]["anchor_lines"], pick[c]["anchor_points"]):
                pick[c] = g
        geoms = list(pick.values())
    imgs, texts, where = [], [], []
    for seg in sorted({g["segment"] for g in geoms}):
        a0 = R.normalize(np.load(Path(npy_dir) / f"{seg}.npy"), "bright")
        a = R.resize(a0, (max(8, int(round(a0.shape[0] * f))), max(8, int(round(a0.shape[1] * f)))))
        for g in (g for g in geoms if g["segment"] == seg):
            for cr in g["crops"]:
                if not cr["on_map"]:
                    continue
                band, on = cut_crop(a, g, cr, f)
                if on < min_on:
                    continue
                imgs.append(band)
                texts.append(cr["text"])
                where.append([seg, g["published_column"], cr["line"]])
    return imgs, texts, where


def save_lines(path, imgs, texts, where, meta):
    H = imgs[0].shape[0]
    flat = np.concatenate([(np.clip(a, 0, 1) * 255).round().astype(np.uint8).T.reshape(-1) for a in imgs])
    np.savez(path, flat=flat, widths=np.array([a.shape[1] for a in imgs], np.int32), height=H,
             texts=np.array(json.dumps(texts, ensure_ascii=False)), where=np.array(json.dumps(where)),
             meta=np.array(json.dumps(meta)))


def load_lines(path):
    z = np.load(path)
    H, flat, o, imgs = int(z["height"]), z["flat"], 0, []
    for w in z["widths"]:
        imgs.append(flat[o:o + H * w].reshape(w, H).T)
        o += H * w
    return imgs, json.loads(str(z["texts"])), json.loads(str(z["where"])), json.loads(str(z["meta"]))


def show(al):
    for u in al["units"]:
        print(f"{u['segment']} col {u['column']} span {u['span']} lines {u['found_lines']} -> published "
              f"{u['published_column']} sum {u['sum']} (decoys max {u['decoy_max']}, p {u['p']}) "
              f"{'ACCEPT' if u['accepted'] else 'reject'} second {u['second']}; anchors {len(u['anchors'])}")
        for A in u["anchors"]:
            print(f"    l{A['line']:>2} s{A['score']:>2} {A['text']:<22} | {A['read']}")
    for g in al["geometry"]:
        on = sum(c["on_map"] for c in g["crops"])
        print(f"GEOM {g['segment']} col {g['published_column']}: pitch {g['b']} slope {g['s']} x0 {g['x0']} w {g['w']} "
              f"anchor lines {g['anchor_lines']} points {g['anchor_points']} ({g['points_used']} used); crops on map {on}/{len(g['crops'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r_ = sub.add_parser("read")
    r_.add_argument("npy_dir")
    r_.add_argument("--weights", required=True)
    r_.add_argument("--out", required=True)
    a_ = sub.add_parser("align")
    a_.add_argument("read")
    a_.add_argument("text")
    a_.add_argument("--out", required=True)
    c_ = sub.add_parser("crops")
    c_.add_argument("align")
    c_.add_argument("npy_dir")
    c_.add_argument("--columns", required=True)
    c_.add_argument("--best", action="store_true")
    c_.add_argument("--out", required=True)
    s_ = sub.add_parser("show")
    s_.add_argument("align")
    a = ap.parse_args()
    if a.cmd == "read":
        res = read_maps(a.npy_dir, a.weights)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False) + "\n", encoding="utf-8")
    elif a.cmd == "align":
        rd = json.loads(Path(a.read).read_text(encoding="utf-8"))
        tx = json.loads(Path(a.text).read_text(encoding="utf-8"))
        res = align(rd, tx)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        show(res)
        print("digest", res["digest"])
    elif a.cmd == "crops":
        al = json.loads(Path(a.align).read_text(encoding="utf-8"))
        cols = {int(c) for c in a.columns.split(",")}
        imgs, texts, where = crops(al, a.npy_dir, cols, a.best)
        save_lines(a.out, imgs, texts, where, {"align_digest": al["digest"], "columns": sorted(cols), "best": a.best})
        print(len(imgs), "crops,", sum(len(t.replace("?", "")) for t in texts), "visible letters, columns",
              sorted({w[1] for w in where}), "segments", sorted({w[0] for w in where}))
    else:
        show(json.loads(Path(a.align).read_text(encoding="utf-8")))


if __name__ == "__main__":
    R.utf8_console()   # Greek prints in a pipe and on a Windows console
    main()
