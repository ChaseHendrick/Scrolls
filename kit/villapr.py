"""Two helpers for anyone with pull requests or issues on ScrollPrize/villa.

  prclock  days left before villa's "PR time limits" workflow closes each of a person's open PRs. The rule, from
           villa's .github/workflows/pr-time-limits.yml (main 6f2024569, read 23 Oct 2026): every day at 00:00
           America/Los_Angeles it closes an open PR with no activity for 14 days (GitHub's updatedAt), or open for
           28 days without a merge (createdAt), unless it carries the label keep-open. Any activity (a comment, a
           push, a review, a label) restarts the 14-day clock; nothing restarts the 28-day one.
  prtext   checks a PR or issue body against villa's templates (.github/pull_request_template.md and
           .github/ISSUE_TEMPLATE/issue.md) and CONTRIBUTING.md before you post: every template field filled, no
           template comments left, the verification box ticked, a picture or video for the proof, a motivation, no
           synthetic or toy example, and no long dashes (U+2014, U+2013), which read as machine-written.

prclock reads the public GitHub search API (60 requests an hour without a token; set GITHUB_TOKEN for more). It
never comments, bumps or relabels anything. prtext reads a local file only. Neither is a villa tool, and passing
prtext does not mean a maintainer will merge: the rules ask for real scroll data and human-written commentary,
which no script can judge.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .verify import VerifyError

REPO = "ScrollPrize/villa"
IDLE_DAYS, AGE_DAYS = 14, 28
EXEMPT_LABEL = "keep-open"
RUN_TZ = "America/Los_Angeles"
WORKFLOW = "https://github.com/ScrollPrize/villa/blob/main/.github/workflows/pr-time-limits.yml"
API = "https://api.github.com"
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(RUN_TZ)
    except Exception:  # no tz database (some Windows Pythons): Pacific daylight time, close enough for a day count
        return timezone(timedelta(hours=-7))


def _parse(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def next_run(at, tz=None):
    """The first daily run (00:00 in villa's time zone) at or after `at`."""
    tz = tz or _tz()
    local = at.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if midnight < local:
        midnight = (midnight + timedelta(days=1)).replace(hour=0)
    return midnight.astimezone(timezone.utc)


def clock(pr, now=None, tz=None):
    """When the time-limit workflow would close one PR (a GitHub search item), and why."""
    now = now or datetime.now(timezone.utc)
    labels = [l.get("name") for l in pr.get("labels") or []]
    created, updated = _parse(pr["created_at"]), _parse(pr["updated_at"])
    row = {"number": pr.get("number"), "title": pr.get("title"), "url": pr.get("html_url"),
           "draft": bool(pr.get("draft")), "created_at": pr["created_at"], "updated_at": pr["updated_at"],
           "keep_open": EXEMPT_LABEL in labels}
    if row["keep_open"]:
        row.update(closes_at=None, reason=f"label {EXEMPT_LABEL}", days_left=None)
        return row
    idle = next_run(updated + timedelta(days=IDLE_DAYS), tz)
    age = next_run(created + timedelta(days=AGE_DAYS), tz)
    when, why = (idle, "14 days without activity") if idle <= age else (age, "28 days open")
    row.update(closes_at=when.isoformat().replace("+00:00", "Z"), reason=why,
               days_left=round((when - now).total_seconds() / 86400, 1),
               age_limit_at=age.isoformat().replace("+00:00", "Z"))
    return row


def search(user, repo=REPO, token=None, opener=urllib.request.urlopen):
    """Open PRs by user in repo, from the GitHub search API (all pages)."""
    if not LOGIN.match(user or ""):
        raise VerifyError(f"not a GitHub login: {user!r}")
    items, page = [], 1
    while True:
        q = urllib.parse.quote(f"repo:{repo} is:pr is:open author:{user}")
        req = urllib.request.Request(f"{API}/search/issues?q={q}&per_page=100&page={page}",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "scrolls-kit"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with opener(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        got = data.get("items") or []
        for it in got:
            it.setdefault("draft", it.get("draft", False))
        items += got
        if len(got) < 100 or len(items) >= data.get("total_count", 0):
            return items
        page += 1


def prclock(user, repo=REPO, now=None, token=None, opener=urllib.request.urlopen):
    rows = [clock(pr, now) for pr in search(user, repo, token, opener)]
    rows.sort(key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 0))
    return {"user": user, "repo": repo, "rule": WORKFLOW, "prs": rows}


def format_clock(r, soon=3):
    if not r["prs"]:
        return f"{r['user']} has no open PRs on {r['repo']}"
    out = [f"{r['user']}: {len(r['prs'])} open PRs on {r['repo']}, soonest close first (rule: {WORKFLOW})"]
    for p in r["prs"]:
        if p["keep_open"]:
            out.append(f"  #{p['number']:<6} kept open (label {EXEMPT_LABEL})  {p['title']}")
            continue
        d = p["days_left"]
        mark = "!!" if d is not None and d <= soon else "  "
        kind = "draft" if p["draft"] else "ready"
        out.append(f"{mark}#{p['number']:<6} {d:>5.1f} days ({p['reason']}, {p['closes_at'][:10]})  {kind}  {p['title']}")
    out.append("Activity restarts the 14-day clock (a real update, not an empty bump); the 28-day limit does not move.")
    return "\n".join(out)


# ---------------------------------------------------------------- prtext

PR_FIELDS = ("In one sentence", "One real example", "Before", "After this PR", "Proof", "Why / where this is useful")
ISSUE_FIELDS = ("In one sentence", "I was trying to", "Using", "What happened", "What I expected or needed",
                "Evidence / reproduction")
PR_BOX = "I personally verified"
ISSUE_BOX = "I personally encountered or reproduced"
MEDIA = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\s|<video\s|github\.com/user-attachments/|\.(?:png|jpe?g|gif|webp|mp4|mov)\b", re.I)
GENERIC_TITLES = re.compile(r"^(?:fix(?:es|ed)?|update[sd]?|improve(?:ments?)?|changes?|misc|wip|patch|bug ?fix)\b\W*$", re.I)


def _field(body, name):
    """Text after **NAME:** up to the next bold field or heading, or None when the field is missing."""
    m = re.search(r"\*\*" + re.escape(name) + r":\*\*(.*?)(?=\n\s*\*\*[^*\n]+:\*\*|\n#|\n- \[|\Z)", body, re.S)
    if not m:
        return None
    return re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip()


def prtext(body, kind="pr", title=None):
    """Problems and reminders for a villa PR or issue body: {"problems": [...], "reminders": [...], "ok": bool}."""
    problems, reminders = [], []
    fields = PR_FIELDS if kind == "pr" else ISSUE_FIELDS
    for f in fields:
        v = _field(body, f)
        if v is None:
            problems.append(f"missing the template field **{f}:**")
        elif not v or v in ("[real data/input]",) or "[real data/input]" in v or "[action]" in v or "[result]" in v:
            problems.append(f"**{f}:** is empty or still has the template's placeholder")
    if re.search(r"<!--", body):
        problems.append("template comments (<!-- ... -->) are still in the text; delete them once each field is filled")
    box = PR_BOX if kind == "pr" else ISSUE_BOX
    if re.search(r"- \[ \]\s*" + re.escape(box), body):
        problems.append(f"the box \"{box} ...\" is not ticked; tick it only if it is true")
    elif not re.search(r"- \[[xX]\]\s*" + re.escape(box), body):
        problems.append(f"the checkbox \"{box} ...\" from the template is missing")
    media = len(MEDIA.findall(body))
    if kind == "pr" and media == 0:
        problems.append("no image or video: villa asks for before/after pictures or a video on real scroll data")
    is_fix = bool(re.search(r"\b(?:fix|bug|crash|error|exception)\w*", (title or "") + " " + body[:600], re.I))
    if kind == "pr" and is_fix and media < 2:
        reminders.append("a bugfix needs a screenshot of the error and one of the tool running without it (CONTRIBUTING)")
    if kind == "pr" and not re.search(r"\b(?:motivation|i was (?:trying|attempting|working)|while (?:using|running|tracing|working))\b", body, re.I):
        problems.append("no motivation: say what you were doing on scroll data when this came up (CONTRIBUTING)")
    if re.search(r"\b(?:synthetic|toy) (?:data|example|volume|input|test)", body, re.I):
        reminders.append("villa does not accept synthetic or toy examples as the proof; show real scroll data")
    dashes = len(re.findall("[\u2014\u2013]", body + (title or "")))
    if dashes:
        problems.append(f"{dashes} long dash(es) (U+2014 or U+2013): use commas, colons or full stops")
    if title is not None:
        words = len(title.split())
        if words < 4 or GENERIC_TITLES.match(title.strip()):
            problems.append(f"the title \"{title}\" is too vague: say what is wrong or what changes, in the tool's own terms")
        if len(title) > 90:
            reminders.append(f"the title is {len(title)} characters; under about 90 reads better in the list")
    reminders.append("villa needs human-written commentary on why the change is useful; write that part yourself")
    return {"kind": kind, "problems": problems, "reminders": reminders, "ok": not problems}


def format_text(r, path):
    head = "ready to post" if r["ok"] else f"{len(r['problems'])} to fix"
    out = [f"{path}: {head} (villa {r['kind']} template)"]
    out += [f"  fix   {p}" for p in r["problems"]]
    out += [f"  note  {p}" for p in r["reminders"]]
    return "\n".join(out)


def build_parser(p, action):
    if action == "prclock":
        p.add_argument("user", help="GitHub login, for example ChaseHendrick")
        p.add_argument("--repo", default=REPO, help="owner/name (the rule is villa's; other repos differ)")
        p.add_argument("--soon", type=float, default=3, help="mark PRs closing within this many days")
    else:
        p.add_argument("file", help="the PR or issue body, as Markdown (- reads standard input)")
        p.add_argument("--issue", action="store_true", help="check against the issue template instead")
        p.add_argument("--title", help="the title you plan to use")
    p.add_argument("--json", action="store_true")
    return p


def cmd_prclock(args):
    """python -m kit prclock USER: exit 0 when listed, 3 when a PR closes within --soon days, 2 when GitHub fails."""
    try:
        r = prclock(args.user, args.repo, token=os.environ.get("GITHUB_TOKEN"))
    except VerifyError as exc:
        print(f"kit prclock: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"kit prclock could not read the GitHub search API: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1) if args.json else format_clock(r, args.soon))
    return 3 if any(p["days_left"] is not None and p["days_left"] <= args.soon for p in r["prs"]) else 0


def cmd_prtext(args):
    """python -m kit prtext FILE: exit 0 when nothing to fix, 1 when something is, 2 when the file cannot be read."""
    try:
        body = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    except OSError as exc:
        print(f"kit prtext could not read the file: {exc}", file=sys.stderr)
        return 2
    r = prtext(body, "issue" if args.issue else "pr", args.title)
    print(json.dumps(r, indent=1) if args.json else format_text(r, args.file))
    return 0 if r["ok"] else 1
