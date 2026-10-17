"""The ink-reader leaderboard, docs/leaderboard.md, written from docs/results.json.

Every released ink reader scored on the held-out PHerc0841 segments (w00, ag896, ag405) and on PHerc0139 w045, with
its controls beside it: forward AUC, the reverse-depth control, the shuffled-depth control where one was run, whether
the reader's training data left that segment out, crop or whole map, source and date.

  python -m kit leaderboard render    rewrite docs/leaderboard.md from docs/results.json
  python -m kit leaderboard check     exit 1 when docs/leaderboard.md and docs/results.json disagree (a unit test runs this)

Rows come from results.json's "results" (measured in this repository) and "community" (reported by others) lists;
"finetune_checks", our own fine-tunes, are not released readers and stay out. Each row's held-out status comes from
"held_out_by_reader", one word per reader family and test group; a reader with no status there is an error, so a new
reader cannot reach the board without one. An ensemble ("A + B mean") takes the least held-out status of its parts.

Standard library only.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "docs" / "results.json"
BOARD = ROOT / "docs" / "leaderboard.md"

# Test group of each segment key in results.json.
GROUPS = {"0841-w00": "PHerc0841", "0841-ag896": "PHerc0841", "0841-ag405": "PHerc0841", "w045": "w045"}
SEGMENT_ORDER = ("0841-w00", "0841-ag896", "0841-ag405", "w045")
SEGMENT_TITLE = {"0841-w00": "PHerc0841 w00", "0841-ag896": "PHerc0841 auto-grown 896 (ag896)",
                 "0841-ag405": "PHerc0841 auto-grown 405 (ag405)", "w045": "PHerc0139 w045"}
# Reader family from the start of a reader name; longest first so "v8in-1447" is not read as "v8in".
FAMILIES = ("v8in-1447", "Reader v2", "ink_9um", "Hecate", "d9v2", "v8in")
STATUSES = ("held out", "possibly not held out", "not held out")  # best to worst
STATUS_CELL = {"held out": "held out", "possibly not held out": "**possibly NOT held out**",
               "not held out": "**NOT held out**"}
MIN_GAP = 0.10  # forward minus reverse below this is flagged, as in kit/gate.py
DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
LONG_DASHES = (chr(0x2014), chr(0x2013))

HEADER = """# Ink reader leaderboard

<!-- generated from docs/results.json by python -m kit leaderboard render; edit results.json, not this file -->

Every released ink reader on the labelled test segments, with its controls beside it. Model output, not readings.
Numbers come only from [`results.json`](results.json); this page is written from it, and
`python -m kit leaderboard check` (run by the tests) fails when the two disagree.

How to read it:

- **Forward**: pixel AUC of the map with the depth layers in their stored order, against the segment's 20260918 human
  labels inside its supervision mask (`kit auc`).
- **Reversed**: the same reader on the layers in reverse depth order, the control. It should sit near or below 0.5,
  and well below Forward. **Gap** is Forward minus Reversed; a gap under {min_gap:.2f} is marked "weak control"
  (the threshold `kit gate` uses).
- **Shuffled**: a map made with the depth layers shuffled, a second control, where one was run. One shuffle is one
  random draw, so it moves between runs.
- **Held out**: whether the reader's training data left this segment out, from `held_out_by_reader` in
  results.json (reasons and sources in its `held_out`). Rows marked **NOT held out** or **possibly NOT held out** are
  not a fair test of that reader.
- **Window**: `whole` is the whole segment; `crop` is the 640 px window where the labels mark the most ink, chosen
  with the labels, so crop scores (the reversed control's included) run higher than whole-map ones. `inner 64` leaves
  a 64 px edge out. Only rows with the same window, edge and render compare directly, so each table splits by window.
- Rows are sorted by Forward within a window. A higher Forward is not a ranking by itself: check the controls and the
  held-out column first. `kit gate` applies the Phase 0 rule to the crop rows.
"""


class BoardError(ValueError):
    pass


def family(reader):
    for name in FAMILIES:
        if reader.startswith(name):
            return name
    return None


def parts(reader):
    """Reader families in a reader name; an ensemble "A + B mean" has two."""
    names = [p.strip() for p in re.sub(r"\s+mean$", "", reader).split(" + ")] if " + " in reader else [reader]
    return [family(n) for n in names]


def status(reader, group, table):
    """Held-out status of a reader (or ensemble) on a test group; BoardError when any part has none."""
    found = []
    for fam in parts(reader):
        if fam is None:
            raise BoardError(f"reader {reader!r}: no known family; add it to kit/leaderboard.py FAMILIES")
        value = (table.get(group) or {}).get(fam)
        if value not in STATUSES:
            raise BoardError(f"reader {reader!r} on {group}: held_out_by_reader has no status for {fam!r} "
                             f"(one of {', '.join(STATUSES)})")
        found.append(value)
    return max(found, key=STATUSES.index)


def row_date(row):
    if row.get("date"):
        if not DATE.fullmatch(str(row["date"])):
            raise BoardError(f"date {row['date']!r} is not YYYY-MM-DD")
        return row["date"]
    m = DATE.search(str(row.get("source", "")))
    return m.group(1) if m else None


def _source(src):
    if src.startswith("https://"):
        short = re.sub(r"^https://(www\.)?", "", src)
        if len(short) > 60:
            short = short[:57] + "..."
        return f"[{short}]({src})"
    if src.startswith("docs/"):
        return f"[`{src[5:]}`]({src[5:]})"
    if re.match(r"(scripts|kit|tests)/", src):
        return f"[`{src}`](../{src})"
    return src


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def window(row):
    if row.get("window") == "whole":
        return "whole"
    return f"crop, inner {row.get('inner_px', 0)}"


def measured(data):
    """Rows measured in this repository on the board's segments, each with its status and date."""
    table = data.get("held_out_by_reader") or {}
    rows = []
    for r in data.get("results", []):
        seg = r.get("segment")
        if seg not in GROUPS or r.get("auc_as_stored") is None:
            continue
        date = row_date(r)
        if date is None:
            raise BoardError(f"{r['reader']} on {seg}: no date (add a \"date\" field or a dated source)")
        rows.append(dict(r, _status=status(r["reader"], GROUPS[seg], table), _date=date, _window=window(r)))
    return rows


def community(data):
    table = data.get("held_out_by_reader") or {}
    rows = []
    for r in data.get("community", []):
        test = r.get("test", "")
        group = "PHerc0841" if "PHerc0841" in test else "w045" if "w045" in test else None
        if group is None:
            continue
        rows.append(dict(r, _status=status(r["reader"], group, table), _date=row_date(r) or "not recorded"))
    return rows


def _gap(fwd, rev):
    if rev is None:
        return "", ""
    gap = fwd - rev
    return f"{gap:+.4f}", ("weak control" if gap < MIN_GAP else "")


def render(data):
    if "held_out_by_reader" not in data:
        raise BoardError("results.json has no held_out_by_reader")
    rows = measured(data)
    out = [HEADER.format(min_gap=MIN_GAP).rstrip("\n"), ""]
    out.append(f"Written from results.json of {data.get('updated', 'unknown date')}.")
    out.append("")
    out.append("## Measured in this repository")
    for seg in SEGMENT_ORDER:
        seg_rows = [r for r in rows if r["segment"] == seg]
        out += ["", f"### {SEGMENT_TITLE[seg]}", ""]
        info = data.get("segments", {}).get(seg, {})
        if info:
            out.append(f"Segment `{info.get('segment')}`, {info.get('voxel_um')} um surface volume, crop "
                       f"`{info.get('crop')}` (y0, y1, x0, x1).")
            out.append("")
        if not seg_rows:
            out.append("No row yet.")
            continue
        windows = sorted({r["_window"] for r in seg_rows}, key=lambda w: (w != "whole", w))
        for w in windows:
            out += [f"Window: {w}", "",
                    "| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |",
                    "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |"]
            these = sorted((r for r in seg_rows if r["_window"] == w),
                           key=lambda r: (-r["auc_as_stored"], r["reader"], r.get("device", "")))
            for r in these:
                gap, flag = _gap(r["auc_as_stored"], r.get("auc_reversed"))
                shuffled = r.get("auc_shuffled")
                out.append("| " + " | ".join(_cell(c) for c in (
                    r["reader"], STATUS_CELL[r["_status"]], f"{r['auc_as_stored']:.4f}",
                    "" if r.get("auc_reversed") is None else f"{r['auc_reversed']:.4f}",
                    gap + (f" ({flag})" if flag else ""),
                    "" if shuffled is None else f"{shuffled:.4f}",
                    r.get("map_from", ""), r.get("device", ""), _source(r.get("source", "")), r["_date"])) + " |")
            out.append("")
        if out[-1] == "":
            out.pop()
        seen = {f for r in seg_rows for f in parts(r["reader"])}
        missing = [f for f in FAMILIES if f in (data["held_out_by_reader"].get(GROUPS[seg]) or {}) and f not in seen]
        if missing:
            out += ["", "Not scored here yet: " + ", ".join(f"`{m}`" for m in missing) + "."]
    crows = community(data)
    out += ["", "## Reported by others (Community report)", "",
            "Each team's own crop, labels and settings, so these do not compare directly with the tables above or "
            "with each other.", "",
            "| Reader | Test | Held out | Forward | Reversed | Gap | Source | Date | Note |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |"]
    for r in sorted(crows, key=lambda r: (r["test"], -r["auc"], r["reader"])):
        gap, flag = _gap(r["auc"], r.get("auc_reversed"))
        out.append("| " + " | ".join(_cell(c) for c in (
            r["reader"], r["test"], STATUS_CELL[r["_status"]], f"{r['auc']:.4f}",
            "" if r.get("auc_reversed") is None else f"{r['auc_reversed']:.4f}",
            gap + (f" ({flag})" if flag else ""), _source(r.get("source", "")), r["_date"],
            r.get("note", ""))) + " |")
    text = "\n".join(out) + "\n"
    for dash in LONG_DASHES:
        if dash in text:
            raise BoardError("a long dash reached the leaderboard; fix the results.json text it came from")
    return text


def load(path=RESULTS):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check(results_path=RESULTS, board_path=BOARD):
    """Problems as strings; empty when the board is what results.json renders to."""
    try:
        want = render(load(results_path))
    except KeyError as exc:
        return [f"leaderboard: a row in {results_path} has no {exc} field"]
    except (OSError, ValueError) as exc:
        return [f"leaderboard: {exc}"]
    board = Path(board_path)
    if not board.is_file():
        return [f"leaderboard: no {board_path}; run python -m kit leaderboard render"]
    if board.read_text(encoding="utf-8") != want:
        return [f"leaderboard: {board_path} differs from what {results_path} renders to; "
                "run python -m kit leaderboard render (edit results.json, not the page)"]
    return []


def add_arguments(p):
    p.add_argument("--results", default=str(RESULTS), help="the scores (default docs/results.json)")
    p.add_argument("--out", default=str(BOARD), help="the page (default docs/leaderboard.md)")
    actions = p.add_subparsers(dest="action", required=True)
    actions.add_parser("render", help="rewrite the leaderboard page from results.json")
    actions.add_parser("check", help="exit 1 when the page and results.json disagree")


def run(args):
    if not Path(args.results).is_file():
        print(f"leaderboard: no {args.results}; it reads the repository's docs/results.json, so run it from a clone "
              "or give --results", file=sys.stderr)
        return 2
    if args.action == "check":
        problems = check(args.results, args.out)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    try:
        text = render(load(args.results))
        Path(args.out).write_text(text, encoding="utf-8")
    except KeyError as exc:
        print(f"leaderboard: a row in {args.results} has no {exc} field", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"leaderboard: {exc}", file=sys.stderr)
        return 2
    tables = text.count("\n| ---")
    print(json.dumps({"out": args.out, "rows": text.count("\n| ") - 2 * tables, "tables": tables}))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit leaderboard", description=__doc__.split("\n")[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
