"""Dated snapshot of the open Vesuvius Challenge prizes.

The snapshot is a copy of https://scrollprize.org/prizes and villa's
``prizeEligibility.json`` on the date in its ``checked`` field. The live page wins
when they disagree.

Eligible lists stay exactly as villa publishes them. An eligible entry may carry an
``award`` (date, title, source, label, checked) when the organisers have announced a prize
for that scroll before villa's list changes; ``format_table`` prints it.
"""

import json
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOT = DATA_DIR / "prizes-2026-10-09.json"
DATA_BROWSER = "https://scrollprize.org/data_browser/"


def load(path=SNAPSHOT):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def deadline_date(prize):
    return datetime.fromisoformat(prize["deadline"]).date()


def days_left(prize, today=None):
    today = today or date.today()
    return (deadline_date(prize) - today).days


def find(snapshot, prize_id):
    for prize in snapshot["prizes"]:
        if prize["id"] == prize_id:
            return prize
    raise KeyError(prize_id)


def eligible_entry(snapshot, scroll, prize_id="first-letters-2027"):
    """Return the eligibility entry for ``scroll`` under ``prize_id``, or None."""
    wanted = normalize_scroll(scroll)
    for entry in find(snapshot, prize_id)["eligible"]:
        if normalize_scroll(entry["scroll"]) == wanted:
            return entry
    return None


def eligible_volume(snapshot, scroll, prize_id="first-letters-2027"):
    """Return the eligible volume id for ``scroll`` under ``prize_id``, or None."""
    entry = eligible_entry(snapshot, scroll, prize_id)
    return entry["volume"] if entry else None


def award(snapshot, scroll, prize_id="first-letters-2027"):
    """Return the recorded award for ``scroll`` under ``prize_id`` (date, title, source, label, checked), or None."""
    entry = eligible_entry(snapshot, scroll, prize_id)
    return entry.get("award") if entry else None


def normalize_scroll(name):
    """Map 'PHerc. 826', 'pherc0826' and 'PHerc0826' to 'PHERC0826'."""
    text = name.upper().replace(" ", "").replace(".", "")
    if not text.startswith("PHERC"):
        return text
    rest = text[len("PHERC"):]
    digits = ""
    while rest and rest[0].isdigit():
        digits, rest = digits + rest[0], rest[1:]
    if digits:
        return "PHERC" + digits.zfill(4) + rest
    return "PHERC" + rest


def amount(prize):
    for key in ("total_usd", "total_usd_per_year"):
        if key in prize:
            suffix = "/yr" if key.endswith("per_year") else ""
            return f"${prize[key]:,}{suffix}"
    return "?"


def format_table(snapshot, today=None):
    rows = [f"Open prizes, snapshot checked {snapshot['checked']} ({snapshot['source']})", ""]
    for prize in snapshot["prizes"]:
        left = days_left(prize, today)
        when = f"{left} days left" if left >= 0 else f"deadline passed {-left} days ago; re-check"
        rows.append(f"{prize['title']:<24} {amount(prize):>14}  {prize['deadline'][:10]}  {when}")
        rows.append(f"    {prize['goal']}")
        if prize["eligible"] and prize["eligible"][0]["volume"] != "any":
            names = ", ".join(e["scroll"] + (" (awarded)" if "award" in e else "") for e in prize["eligible"])
            rows.append(f"    Eligible ({len(prize['eligible'])}): {names}")
        for e in prize["eligible"]:
            if "award" in e:
                rows.append(f"    {e['scroll']}: {prize['title']} awarded {e['award']['date']}, "
                            f"still on villa's eligible list ({e['award']['source']})")
        rows.append("")
    rows.append(snapshot["note"])
    return "\n".join(rows)
