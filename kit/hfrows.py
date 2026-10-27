"""Add Hugging Face Jobs to a cost ledger from Hugging Face's own bill, one row per Job, never twice.

`python -m kit run hf-rows` is the Hugging Face counterpart of `kit run modal-row`. Modal leaves the numbers to the
caller; Hugging Face publishes them, so this reads them itself: the billing endpoint
/api/settings/billing/usage/jobs gives every Job of the current billing period with its flavor, billed minutes and
cost in micro USD, and /api/jobs/NAMESPACE lists Jobs by label. Each chosen Job becomes one row, written through
kit.modalledger.append under the key "hfjob:JOB_ID", so a rerun, or a Job already in the ledger, writes nothing.

The rows take the ledger's columns from its header, as modal-row does. The public ledger
(docs/compute/hf-jobs-costs.csv) takes a row only behind --public-generic and a generic purpose (modalledger's
public gate); the purpose is the caller's text, never a Job's own labels or command. A Job still running is left
out with a note, since its bill is not final; run the command again once it ends.

Needs a Hugging Face token with billing read access ("Billing: read billing usage" on a fine-grained token) in
HF_TOKEN (or --token-env NAME). Standard library only.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import modalledger

API = "https://huggingface.co"
USAGE = "/api/settings/billing/usage/jobs"
KEY_PREFIX = "hfjob:"
NOT_FINISHED = "1970-01-01"          # the bill's completedAt for a Job still running
JOB_ID = re.compile(r"^[0-9a-f]{12,40}$")
LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class HFRowsError(Exception):
    pass


def http_get(url, token, timeout=60):
    """(parsed JSON, next page URL or None) for an authenticated GET."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "scrolls-kit"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            nxt = LINK_NEXT.search(resp.headers.get("Link") or "")
            return json.load(resp), (nxt.group(1) if nxt else None)
    except urllib.error.HTTPError as exc:
        hint = " (the token needs billing read access)" if exc.code in (401, 403) else ""
        raise HFRowsError(f"GET {url.split('?')[0]}: HTTP {exc.code}{hint}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HFRowsError(f"GET {url.split('?')[0]}: {exc}") from exc


def billed_jobs(token, get=None):
    """{job id: bill entry} for the current billing period, from /api/settings/billing/usage/jobs."""
    data, _ = (get or http_get)(API + USAGE, token)
    details = ((data or {}).get("usage") or {}).get("jobDetails")
    if not isinstance(details, list):
        raise HFRowsError(f"{USAGE} returned no usage.jobDetails list")
    return {d["jobId"]: d for d in details if isinstance(d, dict) and d.get("jobId")}


def namespace(token, get=None):
    data, _ = (get or http_get)(API + "/api/whoami-v2", token)
    name = (data or {}).get("name")
    if not name:
        raise HFRowsError("whoami-v2 returned no name")
    return name


def labelled_ids(label, token, ns=None, get=None):
    """Ids of the Jobs in a namespace that carry the label KEY=VALUE (the Jobs API filters on the server)."""
    if "=" not in label:
        raise HFRowsError(f"--label takes KEY=VALUE, not {label!r}")
    get = get or http_get
    ns = ns or namespace(token, get)
    url = f"{API}/api/jobs/{urllib.parse.quote(ns)}?" + urllib.parse.urlencode({"label": label})
    ids = []
    while url:
        page, url = get(url, token)
        ids += [j["id"] for j in page or [] if isinstance(j, dict) and j.get("id")]
    return ids


def row_for(entry, purpose):
    """One ledger row (column: value) for a bill entry."""
    started = str(entry.get("startedAt") or "")
    return {"date_time_utc": started[:16].replace("T", " ") + " UTC" if started else "",
            "purpose": purpose, "flavor": entry.get("hardwareFlavor") or "",
            "minutes": int(entry.get("totalMinutes") or 0),
            "billed_usd": round(int(entry.get("totalCostMicroUsd") or 0) / 1e6, 6),
            "notes": f"HF Job {entry['jobId']}, billed by Hugging Face"}


def finished(entry):
    return not str(entry.get("completedAt") or NOT_FINISHED).startswith(NOT_FINISHED)


def plan(bill, ids):
    """(entries to write, ids still running, ids not in this period's bill), in the order given, ids deduplicated."""
    todo, running, missing = [], [], []
    for i in dict.fromkeys(ids):
        e = bill.get(i)
        if e is None:
            missing.append(i)
        elif not finished(e):
            running.append(i)
        else:
            todo.append(e)
    return todo, running, missing


def add(ledger, ids, purpose, token, public=False, dry_run=False, get=None):
    """Write one row per finished Job in ids; returns a report dict: added, already, running, missing, usd."""
    get = get or http_get
    bad = [i for i in ids if not JOB_ID.match(i)]
    if bad:
        raise HFRowsError(f"not a Job id: {', '.join(bad)}")
    if not purpose or not purpose.strip():
        raise HFRowsError("--purpose is required: what the Jobs were for, in words fit for the ledger")
    todo, running, missing = plan(billed_jobs(token, get), ids)
    report = {"added": [], "already": [], "running": running, "missing": missing, "usd": 0.0}
    for e in todo:
        row = row_for(e, purpose.strip())
        if dry_run:
            header, rows = modalledger.read(ledger)
            done = modalledger.holds(rows, KEY_PREFIX + e["jobId"])
            if not done and modalledger.is_public(header):
                why = public_refusal_or_flag(row, public)
                if why:
                    raise modalledger.LedgerRowError(f"{ledger}: {why}")
        else:
            done = not modalledger.append(ledger, row, KEY_PREFIX + e["jobId"], public=public, generic=public)
        report["already" if done else "added"].append(e["jobId"])
        if not done:
            report["usd"] += row["billed_usd"]
    report["usd"] = round(report["usd"], 6)
    return report


def public_refusal_or_flag(row, public):
    if not public:
        return "this is the public ledger: pass --public-generic for generic Jobs, or write the private ledger"
    return modalledger.public_refusal(row, True)


def token_from(env_name="HF_TOKEN"):
    tok = os.environ.get(env_name, "").strip()
    if not tok:
        raise HFRowsError(f"set {env_name} to a Hugging Face token with billing read access")
    return tok
