"""Daily backup check of the live prize page against the dated prize snapshot. Read-only; standard library only.

  python3 -m kit.prizewatch [--url URL] [--snapshot FILE] [--state FILE] [--timeout S] [--today YYYY-MM-DD] [--json]

One GET of https://scrollprize.org/prizes. From the page text it takes the dollar amounts, the long dates ("June
25th, 2027") and the 14-digit volume ids, and compares them with the snapshot kit uses (kit/prizes.py SNAPSHOT):
every deadline, prize total, per-scroll amount and tier in the snapshot must appear on the page, every eligible
volume in the snapshot must appear on it, every volume id on the page must be in the snapshot, and no snapshot
deadline may have passed. With --state (the routine passes work/routines/prize-page.json, git-ignored) it also says
what appeared or disappeared on the page since the last run.

Exit 0 when the page and the snapshot agree and nothing changed; 3 when an agent should re-read the page, then add
a new dated snapshot in kit/data (docs/AI-AGENTS.md rule 4) and update any prize notes AGENTS.md names; 75 when the
page cannot be fetched (offline); 2 on an unreadable snapshot. The live page wins when they disagree. It posts and
submits nothing. The routine registry (docs/routines.json, kit/routines.py) runs it daily; the same file is in
Scrolls and Scrolls-private.
"""

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timezone
from pathlib import Path

from . import prizes

URL = "https://scrollprize.org/prizes"
EXIT_ATTENTION, EXIT_OFFLINE = 3, 75
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
DATE = re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
                  r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.? (\d{1,2})(?:st|nd|rd|th)?,? "
                  r"(20\d\d)\b")
AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?:\s?(million|M|k|K)\b)?")
VOLUME = re.compile(r"(?<!\d)(20\d{12})(?!\d)")
AMOUNT_FIELDS = ("total_usd", "per_scroll_usd", "monthly_best_usd")


def page_text(raw):
    """Visible text of an HTML page: scripts and styles dropped, tags removed, entities decoded, spaces folded."""
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw or "")
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text.replace("​", " ")).strip()


def _month(name):
    name = name.lower()
    return next(i for m, i in MONTHS.items() if m.startswith(name[:3]))


def facts(raw):
    """{"amounts": [USD ints], "dates": [ISO dates], "volumes": [14-digit ids]} named on the page."""
    text = page_text(raw)
    amounts = set()
    for whole, frac, unit in AMOUNT.findall(text):
        value = float(whole.replace(",", "") + ("." + frac if frac else ""))
        value *= {"million": 1e6, "M": 1e6, "k": 1e3, "K": 1e3}.get(unit, 1)
        amounts.add(int(round(value)))
    dates = set()
    for month, day, year in DATE.findall(text):
        try:
            dates.add(date(int(year), _month(month), int(day)).isoformat())
        except ValueError:
            pass
    return {"amounts": sorted(amounts), "dates": sorted(dates), "volumes": sorted(set(VOLUME.findall(raw or "")))}


def snapshot_expectations(snapshot):
    """What the snapshot says the page shows: [(prize id, kind, value)]."""
    out = []
    for p in snapshot["prizes"]:
        pid = p["id"]
        if p.get("deadline"):
            out.append((pid, "date", datetime.fromisoformat(p["deadline"]).date().isoformat()))
        for field in AMOUNT_FIELDS:
            if isinstance(p.get(field), (int, float)):
                out.append((pid, "amount", int(p[field])))
        tiers = p.get("tiers_usd") or {}
        for v in (tiers.values() if isinstance(tiers, dict) else []):
            out.append((pid, "amount", int(v)))
        for v in p.get("typical_tiers_usd") or []:
            out.append((pid, "amount", int(v)))
        for e in p.get("eligible") or []:
            if VOLUME.fullmatch(str(e.get("volume", ""))):
                out.append((pid, "volume", e["volume"]))
    return out


def compare(snapshot, seen, now):
    """Problems, in plain sentences, between the snapshot and the facts seen on the page (now: aware datetime)."""
    problems = []
    found = {"date": set(seen["dates"]), "amount": set(seen["amounts"]), "volume": set(seen["volumes"])}
    for pid, kind, value in snapshot_expectations(snapshot):
        if value not in found[kind]:
            shown = f"{value:,} USD" if kind == "amount" else value
            problems.append(f"{pid}: the snapshot's {kind} {shown} is not on the page")
    listed = {e.get("volume") for p in snapshot["prizes"] for e in p.get("eligible") or []}
    for v in sorted(found["volume"] - listed):
        problems.append(f"the page names volume {v}, which the snapshot does not list (newly eligible?)")
    for p in snapshot["prizes"]:
        if p.get("deadline") and datetime.fromisoformat(p["deadline"]) < now:
            problems.append(f"{p['id']}: the snapshot's deadline {prizes.deadline_date(p).isoformat()} has passed; "
                            "the page should name the next one")
    return problems


def changes(old, new):
    out = []
    for key in ("amounts", "dates", "volumes"):
        before, after = set(old.get(key, [])), set(new.get(key, []))
        if after - before:
            out.append(f"new on the page since the last check: {key} {', '.join(map(str, sorted(after - before)))}")
        if before - after:
            out.append(f"gone from the page since the last check: {key} {', '.join(map(str, sorted(before - after)))}")
    return out


def fetch(url=URL, timeout=20, opener=None):
    req = urllib.request.Request(url, headers={"User-Agent": "scrolls-kit-prizewatch"})
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def check(raw, snapshot, now=None, state_path=None):
    """(exit code, report dict). Updates the state file with what the page shows now."""
    now = now or datetime.now(timezone.utc)
    seen = facts(raw)
    problems = compare(snapshot, seen, now)
    changed = []
    if state_path:
        state_path = Path(state_path)
        try:
            old = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = None
        if isinstance(old, dict) and isinstance(old.get("facts"), dict):
            changed = changes(old["facts"], seen)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state_path.write_text(json.dumps({"checked": stamp, "facts": seen}, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(json.dumps(seen, sort_keys=True).encode()).hexdigest()[:16]
    report = {"snapshot_checked": snapshot.get("checked"), "page_facts_digest": digest, "problems": problems,
              "changes": changed, "amounts": len(seen["amounts"]), "dates": seen["dates"],
              "volumes": len(seen["volumes"])}
    return (EXIT_ATTENTION if problems or changed else 0), report


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.prizewatch", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=URL)
    p.add_argument("--snapshot", default=str(prizes.SNAPSHOT))
    p.add_argument("--state", help="JSON file that keeps what the page showed last time (for change reports)")
    p.add_argument("--timeout", type=float, default=20)
    p.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        snapshot = prizes.load(args.snapshot)
    except (OSError, ValueError) as exc:
        print(f"prizewatch: cannot read the snapshot {args.snapshot}: {exc}", file=sys.stderr)
        return 2
    try:
        raw = fetch(args.url, args.timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"prizewatch: offline, {args.url} could not be fetched: {exc}")
        return EXIT_OFFLINE
    now = (datetime.combine(date.fromisoformat(args.today), time(12), timezone.utc) if args.today
           else datetime.now(timezone.utc))
    code, report = check(raw, snapshot, now, args.state)
    if args.json:
        print(json.dumps(report, indent=2))
        return code
    print(f"prize page {args.url} against the snapshot of {report['snapshot_checked']}: {report['amounts']} amounts, "
          f"dates {', '.join(report['dates']) or 'none'}, {report['volumes']} volume ids")
    for line in report["problems"] + report["changes"]:
        print("  " + line)
    if code:
        print("Re-read the page; if it changed, add a new dated snapshot in kit/data (docs/AI-AGENTS.md rule 4) "
              "and update any prize notes the repository's AGENTS.md names. The live page wins.")
    else:
        print("  agrees with the snapshot" + (", unchanged since the last check" if args.state else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
