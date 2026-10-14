"""Paired bootstrap of two eval_p172.py results: is model B's character error on the PHerc. 172 drawings
really different from model A's?

Each half of the drawings holds only a few dozen matched lines, and letters within a line are not
independent, so the unit resampled is the reference line (segment, reference string), or with
--level segment the whole segment. A line one model failed to match counts for the other model only,
exactly as in eval_p172.py's cer_matched_lines. Prints the point difference B - A, a 95% interval and
the share of resamples in which B is worse. Both inputs are model output on public community
drawings; keep them in ignored work/ folders.

  python scripts/letters/compare_p172.py A.json B.json [--key ink_only|with_lm] [--level line|segment]

A reference line outside the reader's alphabet (a result edited by hand with a Latin look-alike or a
final sigma) stops the comparison with the alphabet printed.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.letterlines import check_references  # noqa: E402
from kit.letterread import edit_distance, utf8_console  # noqa: E402


def line_units(res, key="ink_only", segments=None):
    """{(segment, reference line): (edit errors, reference letters)} from an eval_p172 result."""
    out = {}
    for r in res["segments"]:
        if segments is not None and r["segment"] not in segments:
            continue
        for read, ref in r.get(key, {}).get("pairs", []):
            out[(r["segment"], ref)] = (edit_distance(read, ref), len(ref))
    return out


def check_result_references(res, key="ink_only", source="result"):
    """SystemExit when a reference line of an eval_p172 result holds a character outside the reader's alphabet.

    eval_p172.py writes references in the alphabet; a result edited or made by hand with a Latin look-alike
    or a final sigma would only ever count as errors, so it is refused with the alphabet printed."""
    refs = {f"{r['segment']} pair {i}": ref for r in res["segments"]
            for i, (_, ref) in enumerate(r.get(key, {}).get("pairs", []))}
    try:
        check_references(refs, wildcard=None, source=source)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


def paired_bootstrap(a, b, n=20000, seed=0, level="line"):
    keys = sorted(set(a) | set(b))
    if not keys:
        raise ValueError("no matched lines in either result")
    ea, la = (np.array([a.get(k, (0, 0))[i] for k in keys], float) for i in (0, 1))
    eb, lb = (np.array([b.get(k, (0, 0))[i] for k in keys], float) for i in (0, 1))
    rng = np.random.default_rng(seed)
    if level == "segment":
        segs = sorted({k[0] for k in keys})
        groups = [np.array([i for i, k in enumerate(keys) if k[0] == s]) for s in segs]
    diffs = []
    for _ in range(n):
        if level == "segment":
            idx = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        else:
            idx = rng.integers(0, len(keys), len(keys))
        if la[idx].sum() and lb[idx].sum():
            diffs.append(eb[idx].sum() / lb[idx].sum() - ea[idx].sum() / la[idx].sum())
    diffs = np.array(diffs)
    return {"cer_a": round(ea.sum() / la.sum(), 3), "cer_b": round(eb.sum() / lb.sum(), 3),
            "diff_b_minus_a": round(eb.sum() / lb.sum() - ea.sum() / la.sum(), 3),
            "ci95": [round(float(v), 3) for v in np.percentile(diffs, [2.5, 97.5])],
            "share_b_worse": round(float((diffs > 0).mean()), 3), "units": len(keys), "level": level,
            "resamples": int(len(diffs))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--key", default="ink_only", choices=["ink_only", "with_lm"])
    ap.add_argument("--level", default="line", choices=["line", "segment"])
    ap.add_argument("--n", type=int, default=20000)
    x = ap.parse_args(argv)
    ra, rb = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (x.a, x.b))
    for path, r in ((x.a, ra), (x.b, rb)):
        check_result_references(r, x.key, Path(path).name)
    segs = {r["segment"] for r in rb["segments"]}       # compare on the segments both results cover
    res = paired_bootstrap(line_units(ra, x.key, segs), line_units(rb, x.key), n=x.n, level=x.level)
    print(json.dumps(res))


if __name__ == "__main__":
    utf8_console()   # Greek prints in a pipe and on a Windows console
    main()
