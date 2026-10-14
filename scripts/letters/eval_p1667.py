"""Fresh letter-recognition test: read the drawn letter groups of PHerc. 1667's official ink labels.

The groups come from p1667_groups.py (a fixed, model-free cut of the six labelled segments); the
reference letters come from three independent blind transcriptions of the group images, and only
groups on which all three agree exactly, with no unsure letter, are scored. No reader has seen
PHerc. 1667, and no checkpoint is chosen here: the four checkpoints were chosen earlier on the
PHerc. 172 dev half. The rule was fixed on 9 October 2026 before these reads (docs/logs/2026-10-14-letter-reader.md).

Each group is read from its crop with the line centre and the segment's letter height given
(lines=[centre], letter_px=h, one column), ink only and with the language model. Scored as
character error over reference letters, one unit per group, plus two controls: letters kept on
the reader's null images against the real crops, and the error against references permuted
across groups (the chance floor). Every string is model output on public drawings, not a reading.

With --source map the same windows are cut from the segments' 2.4 um ink-detection maps
(p1667_mapcrops.py) instead of the drawings. A map window also shows the unlabelled letters on
either side of a group, so every result also carries the free-ends error: the edit distance from
the reference to the best-matching run of letters in the read, so letters read before and after
the reference are not charged (errors_free_ends; compare --metric free_ends).

With --source map-wide the windows are made two letter heights taller above and below
(p1667_mapcrops.py --wide), so they hold the neighbouring lines, and the reader is given no line:
it finds the lines itself (lines=None). With --letter-px auto it is not given the letter height
either (scale search). A group is scored on the read line nearest its true centre if that line is
within HIT_TOL letter heights of it, and counts every reference letter as an error if no line is;
errors_free_ends_any is the lenient score, the best of all read lines.

With --source map-region the reader reads each segment's whole labelled map region once
(p1667_mapcrops.py --region: several columns of about ten lines), finding columns, lines and
letter positions itself (columns="auto", lines=None). A group is scored on the found line, in a
reader column overlapping the group, whose row at the group's centre (undoing that column's
deskew) is nearest the group's line, if within HIT_TOL letter heights; its read is the letters on
that line whose boxes centre inside the group's window span (the group's box widened by PAD_X
letter heights each side, as in the windows). Ink only: the language-model decode has no letter
positions, so it cannot be cut to a group.

  python scripts/letters/eval_p1667.py read GROUPS_DIR REFS.json --weights W [--lm LM] [--source label|map|map-wide|map-region] [--letter-px given|auto] --out OUT.json
  python scripts/letters/eval_p1667.py compare A.json B.json [--key ink_only|with_lm] [--level group|segment] [--metric plain|free_ends|free_ends_any]

--weights takes a linenet-v1 .npz or a released model name such as letters-v2-real; the result records it
as given, as on 9 October 2026. REFS.json is {"agreed": {group id: letters}}: Greek capitals in the
reader's alphabet, lunate sigma for every sigma, '?' for an unsure letter (its group is not scored); any
other character in a scored group stops the run with the alphabet printed. read prints which row of
docs/letter-reader.md's table "How well it reads" the settings reproduce, then the guide's measure first
(plain character error for the drawings, free ends for the maps), and the summary JSON as its last line.
The rows: --source label (row 1), map (row 2), map-wide (row 3; with --letter-px auto, row 3's second
value) and map-region --letter-px auto (row 4).
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit import letterread as R  # noqa: E402
from kit.letterlines import check_references  # noqa: E402

NULLS = 2
LM_WEIGHT = 0.5
HIT_TOL = 0.5     # map-wide: a read line within this many letter heights of the group's centre is its line


def references(path):
    """{group id: reference letters} for groups the three transcriptions agree on, with no '?'.

    Every text that is scored must be in the reader's alphabet: a Latin look-alike or a final sigma
    would only ever count as an error, so it stops the run with a message that names it and prints the
    alphabet (SystemExit). A group with a '?' (an unsure letter) is left out as before, unchecked."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    refs = {gid: t for gid, t in data["agreed"].items() if t and "?" not in t}
    try:
        check_references(refs, wildcard=None, source=f"{Path(path).name} (agreed)")
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    return refs


def free_ends_distance(read, ref):
    """Edit distance from ref to the closest substring of read (letters before and after it are free)."""
    prev = [0] * (len(read) + 1)
    for i in range(1, len(ref) + 1):
        cur = [i] + [0] * len(read)
        for j in range(1, len(read) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ref[i - 1] != read[j - 1]))
        prev = cur
    return min(prev)


def permuted(ids, seed=0):
    """A fixed derangement of the group ids (each reference moved to another group)."""
    rng = np.random.default_rng(seed)
    ids = list(ids)
    while True:
        p = list(rng.permutation(len(ids)))
        if all(p[i] != i for i in range(len(ids))):
            return {ids[i]: ids[p[i]] for i in range(len(ids))}


def read(groups_dir, refs_path, weights, lm=None, source="label", letter_px="given"):
    if source == "map-wide":
        return read_wide(groups_dir, refs_path, weights, lm, letter_px)
    if source == "map-region":
        return read_region(groups_dir, refs_path, weights, letter_px)
    groups_dir = Path(groups_dir)
    meta = {g["id"]: g for g in json.loads((groups_dir / "groups.json").read_text())["groups"]}
    refs = references(refs_path)
    net = R.load_weights(weights)   # a .npz path or a released model name; recorded as given
    rows, tot = [], {}
    for gid in sorted(refs):
        g, ref = meta[gid], refs[gid]
        c = np.load(groups_dir / ("npy" if source == "label" else "map-npy") / f"{gid}.npy")
        if not 0 <= g["centre_y"] < c.shape[0]:
            raise SystemExit(f"{gid}: line centre {g['centre_y']} is outside its crop ({c.shape[0]} rows)")
        res = R.analyze(c, net, letter_px=g["letter_h"], lines=[g["centre_y"]], columns="off", nulls=NULLS, seed=0,
                        lm=lm, lm_weight=LM_WEIGHT if lm else 0.0)
        decodes = {"ink_only": "".join("".join(l["glyph"] for l in L["letters"]) for L in res["lines"])}
        if lm is not None:
            decodes["with_lm"] = "".join(L["with_lm"] for L in res["lines"])
        row = {"segment": gid, "scroll_segment": g["segment"], "ref": ref, "kept": res["control"]["letters_kept"],
               "null_kept": res["control"]["null_letters_kept"]}
        for key, txt in decodes.items():
            e, fe = R.edit_distance(txt, ref), free_ends_distance(txt, ref)
            row[key] = {"read": txt, "errors": e, "errors_free_ends": fe, "pairs": [[txt, ref]]}
            t = tot.setdefault(key, [0, 0, 0])
            t[0] += e
            t[1] += len(ref)
            t[2] += fe
        rows.append(row)
    perm = permuted([r["segment"] for r in rows])
    by = {r["segment"]: r for r in rows}
    summary = {}
    for key, (e, n, fe) in tot.items():
        pe = sum(R.edit_distance(by[g][key]["read"], by[perm[g]]["ref"]) for g in by)
        pfe = sum(free_ends_distance(by[g][key]["read"], by[perm[g]]["ref"]) for g in by)
        pn = sum(len(by[perm[g]]["ref"]) for g in by)
        summary[key] = {"cer": round(e / n, 3), "errors": e, "ref_letters": n,
                        "cer_permuted_refs": round(pe / pn, 3), "cer_free_ends": round(fe / n, 3),
                        "errors_free_ends": fe, "cer_free_ends_permuted_refs": round(pfe / pn, 3)}
    summary["groups"] = len(rows)
    summary["letters_kept"] = sum(r["kept"] for r in rows)
    summary["null_letters_kept"] = [sum(r["null_kept"][i] for r in rows) for i in range(NULLS)]
    return {"note": R.NOTE, "data": "PHerc. 1667 official ink labels, six segments, groups from p1667_groups.py",
            "source": source, "weights": str(weights), "nulls": NULLS, "lm_weight": LM_WEIGHT if lm else None,
            "summary": summary, "segments": rows}


def read_wide(groups_dir, refs_path, weights, lm=None, letter_px="given"):
    """Read the tall map windows with no line given; score the found line nearest the group's centre."""
    groups_dir = Path(groups_dir)
    meta = {g["id"]: g for g in json.loads((groups_dir / "groups.json").read_text())["groups"]}
    where = json.loads((groups_dir / "map-wide.json").read_text())["groups"]
    refs = references(refs_path)
    net = R.load_weights(weights)   # a .npz path or a released model name; recorded as given
    rows, tot = [], {}
    for gid in sorted(refs):
        g, ref, cy = meta[gid], refs[gid], where[gid]["centre_y_in_window"]
        c = np.load(groups_dir / "map-wide-npy" / f"{gid}.npy")
        res = R.analyze(c, net, letter_px=g["letter_h"] if letter_px == "given" else None, lines=None,
                        columns="off", nulls=NULLS, seed=0, lm=lm, lm_weight=LM_WEIGHT if lm else 0.0)
        ys = [L["y"] for L in res["lines"]]
        near = min(range(len(ys)), key=lambda i: abs(ys[i] - cy)) if ys else None
        hit = near is not None and abs(ys[near] - cy) <= HIT_TOL * g["letter_h"]
        texts = {"ink_only": ["".join(l["glyph"] for l in L["letters"]) for L in res["lines"]]}
        if lm is not None:
            texts["with_lm"] = [L["with_lm"] for L in res["lines"]]
        row = {"segment": gid, "scroll_segment": g["segment"], "ref": ref, "kept": res["control"]["letters_kept"],
               "null_kept": res["control"]["null_letters_kept"], "centre_y": cy, "lines_y": ys,
               "line_hit": hit, "letter_px_used": res["letter_px"], "letter_h": g["letter_h"]}
        for key, lines in texts.items():
            txt = lines[near] if hit else ""
            e, fe = R.edit_distance(txt, ref), free_ends_distance(txt, ref)
            fa = min([free_ends_distance(s, ref) for s in lines] or [len(ref)])
            row[key] = {"read": txt, "lines": lines, "errors": e, "errors_free_ends": fe, "errors_free_ends_any": fa,
                        "pairs": [[txt, ref]]}
            t = tot.setdefault(key, [0, 0, 0, 0])
            t[0] += e
            t[1] += len(ref)
            t[2] += fe
            t[3] += fa
        rows.append(row)
    perm = permuted([r["segment"] for r in rows])
    by = {r["segment"]: r for r in rows}
    summary = {}
    for key, (e, n, fe, fa) in tot.items():
        pe = sum(R.edit_distance(by[g][key]["read"], by[perm[g]]["ref"]) for g in by)
        pfe = sum(free_ends_distance(by[g][key]["read"], by[perm[g]]["ref"]) for g in by)
        pfa = sum(min([free_ends_distance(s, by[perm[g]]["ref"]) for s in by[g][key]["lines"]]
                      or [len(by[perm[g]]["ref"])]) for g in by)
        pn = sum(len(by[perm[g]]["ref"]) for g in by)
        summary[key] = {"cer": round(e / n, 3), "errors": e, "ref_letters": n,
                        "cer_permuted_refs": round(pe / pn, 3), "cer_free_ends": round(fe / n, 3),
                        "errors_free_ends": fe, "cer_free_ends_permuted_refs": round(pfe / pn, 3),
                        "cer_free_ends_any": round(fa / n, 3), "errors_free_ends_any": fa,
                        "cer_free_ends_any_permuted_refs": round(pfa / pn, 3)}
    summary["groups"] = len(rows)
    summary["line_hits"] = sum(r["line_hit"] for r in rows)
    summary["lines_per_window"] = round(sum(len(r["lines_y"]) for r in rows) / max(1, len(rows)), 2)
    summary["letters_kept"] = sum(r["kept"] for r in rows)
    summary["null_letters_kept"] = [sum(r["null_kept"][i] for r in rows) for i in range(NULLS)]
    return {"note": R.NOTE, "data": "PHerc. 1667 2.4 um ink-detection maps, tall windows around the label groups",
            "source": "map-wide", "letter_px": letter_px, "hit_tol": HIT_TOL, "weights": str(weights),
            "nulls": NULLS, "lm_weight": LM_WEIGHT if lm else None, "summary": summary, "segments": rows}


def row_at(line, col, x):
    """Input row of a found line at input column x, undoing its column's deskew shear."""
    return line["y"] + (x - 0.5 * (col["x0"] + col["x1"])) * math.tan(math.radians(col["deskew_deg"]))


def group_read(res, cy, x0, x1, h):
    """(read on the group's line or None, reads of every candidate line) for a group at row cy, span x0..x1."""
    xc = 0.5 * (x0 + x1)
    cols = res["columns"]
    cand = [L for L in res["lines"] if cols[L["column"]]["x0"] < x1 and cols[L["column"]]["x1"] > x0]

    def cut(L):
        return "".join(l["glyph"] for l in L["letters"] if x0 <= 0.5 * (l["box"][2] + l["box"][3]) < x1)
    reads = [cut(L) for L in cand]
    if not cand:
        return None, reads, None
    i = min(range(len(cand)), key=lambda k: abs(row_at(cand[k], cols[cand[k]["column"]], xc) - cy))
    off = row_at(cand[i], cols[cand[i]["column"]], xc) - cy
    return (reads[i] if abs(off) <= HIT_TOL * h else None), reads, round(off, 1)


def read_region(groups_dir, refs_path, weights, letter_px="given"):
    """Read each segment's whole map region once; score every group on the letters found at its place."""
    from p1667_groups import PAD_X
    groups_dir = Path(groups_dir)
    meta = json.loads((groups_dir / "groups.json").read_text())
    pads = json.loads((groups_dir / "map-region.json").read_text())["segments"]
    refs = references(refs_path)
    net = R.load_weights(weights)   # a .npz path or a released model name; recorded as given
    seg_res, rows, segs = {}, [], {}
    for seg, st in meta["stats"].items():
        img = np.load(groups_dir / "map-region-npy" / f"{seg}.npy")
        res = R.analyze(img, net, letter_px=st["letter_h"] if letter_px == "given" else None, lines=None,
                        columns="auto", nulls=NULLS, seed=0)
        seg_res[seg] = res
        segs[seg] = {"letter_px_used": res["letter_px"], "columns": [[c["x0"], c["x1"]] for c in res["columns"]],
                     "lines": len(res["lines"]), "letters_kept": res["control"]["letters_kept"],
                     "null_letters_kept": res["control"]["null_letters_kept"]}
        print(seg, segs[seg]["columns"], segs[seg]["lines"], "lines", flush=True)
    tot = [0, 0, 0, 0]
    for g in sorted((g for g in meta["groups"] if g["id"] in refs), key=lambda g: g["id"]):
        ref, h, Rp = refs[g["id"]], g["letter_h"], pads[g["segment"]]["pad"]
        bx0, bx1 = g["box"][2], g["box"][3]
        txt, reads, off = group_read(seg_res[g["segment"]], g["centre_y_segment"] + Rp,
                                     bx0 - PAD_X * h + Rp, bx1 + PAD_X * h + Rp, h)
        hit = txt is not None
        txt = txt or ""
        e, fe = R.edit_distance(txt, ref), free_ends_distance(txt, ref)
        fa = min([free_ends_distance(s, ref) for s in reads] or [len(ref)])
        rows.append({"segment": g["id"], "scroll_segment": g["segment"], "ref": ref, "line_hit": hit, "row_offset": off,
                     "ink_only": {"read": txt, "lines": reads, "errors": e, "errors_free_ends": fe,
                                  "errors_free_ends_any": fa, "pairs": [[txt, ref]]}})
        for k, v in enumerate((e, len(ref), fe, fa)):
            tot[k] += v
    perm = permuted([r["segment"] for r in rows])
    by = {r["segment"]: r for r in rows}
    e, n, fe, fa = tot
    pr = {g: by[perm[g]]["ref"] for g in by}
    pe = sum(R.edit_distance(by[g]["ink_only"]["read"], pr[g]) for g in by)
    pfe = sum(free_ends_distance(by[g]["ink_only"]["read"], pr[g]) for g in by)
    pfa = sum(min([free_ends_distance(s, pr[g]) for s in by[g]["ink_only"]["lines"]] or [len(pr[g])]) for g in by)
    pn = sum(len(pr[g]) for g in by)
    summary = {"ink_only": {"cer": round(e / n, 3), "errors": e, "ref_letters": n, "cer_permuted_refs": round(pe / pn, 3),
                            "cer_free_ends": round(fe / n, 3), "errors_free_ends": fe,
                            "cer_free_ends_permuted_refs": round(pfe / pn, 3), "cer_free_ends_any": round(fa / n, 3),
                            "errors_free_ends_any": fa, "cer_free_ends_any_permuted_refs": round(pfa / pn, 3)},
               "groups": len(rows), "line_hits": sum(r["line_hit"] for r in rows),
               "lines_read": sum(s["lines"] for s in segs.values()),
               "letters_kept": sum(s["letters_kept"] for s in segs.values()),
               "null_letters_kept": [sum(s["null_letters_kept"][i] for s in segs.values()) for i in range(NULLS)]}
    return {"note": R.NOTE, "data": "PHerc. 1667 2.4 um ink-detection maps, whole labelled region of each segment",
            "source": "map-region", "letter_px": letter_px, "hit_tol": HIT_TOL, "weights": str(weights),
            "nulls": NULLS, "lm_weight": None, "summary": summary, "regions": segs, "segments": rows}


GUIDE_ROWS = {   # (source, --letter-px): the row of docs/letter-reader.md's table "How well it reads" it reproduces
    ("label", "given"): "row 1, PHerc. 1667 official ink labels (drawings), line given",
    ("map", "given"): "row 2, Same 87 groups read from the 2.4 um ink maps, line given",
    ("map-wide", "given"): "row 3, Maps, windows about three lines tall, reader finds the line",
    ("map-wide", "auto"): "row 3's second value, the same windows with nothing given",
    ("map-region", "auto"): "row 4, Maps, each segment's whole labelled region read once, nothing given",
    ("map-region", "given"): "no row of the table: the whole regions with the letter height given (in the log; "
                             "row 4 is --letter-px auto)",
}


def headline(res):
    """Lines printed before the summary JSON: the guide's measure first, then the other, and the controls.

    The guide quotes the plain character error for the drawings (--source label) and the free-ends error
    for the maps, whose windows also show unlabelled letters beside a group. Printing only; the summary
    and the --out file are unchanged."""
    src, summ = res["source"], res["summary"]
    row = GUIDE_ROWS.get((src, res.get("letter_px", "given")), "no row of the guide's table")
    out = [f"source {src}, letter height {res.get('letter_px', 'given')}: the guide's {row}"]
    for key in ("ink_only", "with_lm"):
        m = summ.get(key)
        if not m:
            continue
        plain = f"character error {m['cer']} ({m['errors']} edits over {m['ref_letters']} reference letters)"
        free = f"free-ends error {m['cer_free_ends']} ({m['errors_free_ends']} edits)"
        first, second = (plain, free) if src == "label" else (free, plain)
        out.append(f"{key}: {first}; {second}; against references permuted across groups "
                   f"{m['cer_permuted_refs']} plain, {m['cer_free_ends_permuted_refs']} free ends")
    hits = f", line found for {summ['line_hits']} of them" if "line_hits" in summ else ""
    out.append(f"{summ['groups']} groups{hits}; letters kept {summ['letters_kept']} against nulls "
               f"{summ['null_letters_kept']} (Model output, not a reading)")
    return out


def units(res, key, metric="plain"):
    field = {"plain": "errors", "free_ends": "errors_free_ends", "free_ends_any": "errors_free_ends_any"}[metric]
    return {(r["scroll_segment"], r["segment"]): (r[key][field], len(r["ref"])) for r in res["segments"] if key in r}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("groups_dir")
    r.add_argument("refs")
    r.add_argument("--weights", required=True)
    r.add_argument("--lm")
    r.add_argument("--source", default="label", choices=("label", "map", "map-wide", "map-region"))
    r.add_argument("--letter-px", default="given", choices=("given", "auto"))
    r.add_argument("--out")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--key", default="ink_only", choices=("ink_only", "with_lm"))
    c.add_argument("--level", default="group", choices=("group", "segment"))
    c.add_argument("--metric", default="plain", choices=("plain", "free_ends", "free_ends_any"))
    c.add_argument("--n", type=int, default=20000)
    a = ap.parse_args()
    if getattr(a, "out", None):   # the folder first, so a long read never ends on a missing folder
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == "read":
        lm = None
        if a.lm:
            from kit import greeklm
            lm = greeklm.KNLetterLM.load(a.lm)
        res = read(a.groups_dir, a.refs, a.weights, lm, a.source, a.letter_px)
        if a.out:
            Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("\n".join(headline(res)))
        print(json.dumps(res["summary"], ensure_ascii=False))   # last, so `| tail -1` still gives the JSON
    else:
        from compare_p172 import paired_bootstrap
        A, B = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (a.a, a.b))
        ua, ub = units(A, a.key, a.metric), units(B, a.key, a.metric)
        if set(ua) != set(ub):
            raise SystemExit("the two results score different groups")
        out = paired_bootstrap(ua, ub, n=a.n, level="line" if a.level == "group" else "segment")
        out["level"] = a.level
        print(json.dumps({"a": a.a, "b": a.b, "key": a.key, "metric": a.metric, **out}))


if __name__ == "__main__":
    R.utf8_console()   # Greek prints in a pipe and on a Windows console
    main()
