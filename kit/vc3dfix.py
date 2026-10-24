"""Two commands that keep S3's false 404s out of VC3D (villa's Volume Cartographer 3D).

  s3relay   runs a local relay (kit/s3relay.py) between VC3D and a remote zarr: alone, in the foreground, printing
            the URL to give VC3D; or around one command (`-- vc_render_tifxyz ...`), with the volume's URL in that
            command's arguments swapped for the relay's, VC3D's empty-chunk markers checked before and after the
            run (kit/vc3d_cache.py), and the chunks the run may have read as zeros listed.
  vc3dcache checks the empty-chunk markers VC3D's persistent cache holds for a remote volume, under the URL VC3D
            was given directly or through a relay, and deletes the false ones (chunks the bucket holds), so the next
            read fetches them. --all lists every volume folder in the cache with its marker count.

Why (kit/s3retry.py): S3 sometimes answers 404 with the error code NoSuchBucket for keys it holds, and VC3D takes any
404 for a missing chunk, caches it as empty for good and reads it as zeros with no error. Standard library.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from . import s3relay, vc3d_cache

DEFAULT_LEDGER = "work/vc3d-empty"
OPEN_DATA = "vesuvius-challenge-open-data"
OPEN_DATA_REGION = "us-east-1"
AFFECTED_EXIT = 4


def forms(url):
    """The spellings of one bucket URL that VC3D may have been given: as given, and for an S3 bucket its s3://,
    global https and (for the open-data bucket) us-east-1 https forms. Trailing slashes are dropped."""
    url = str(url).rstrip("/")
    m = re.match(r"^s3://([^/]+)/(.*)$", url) or \
        re.match(r"^https?://([a-z0-9.-]+)\.s3(?:[.-]([a-z0-9-]+))?\.amazonaws\.com/(.*)$", url)
    if not m:
        return [url]
    bucket, key = m.group(1), m.group(m.lastindex)
    out = [url, f"s3://{bucket}/{key}", f"https://{bucket}.s3.amazonaws.com/{key}"]
    if bucket == OPEN_DATA:
        out.append(f"https://{bucket}.s3.{OPEN_DATA_REGION}.amazonaws.com/{key}")
    return list(dict.fromkeys(out))


def swap(args, url, given):
    """args with every spelling of url (forms()) replaced by the relay's URL `given`; also the count replaced."""
    pats = sorted(forms(url), key=len, reverse=True)
    rx = re.compile("|".join(re.escape(p) for p in pats))
    out, n = [], 0
    for a in args:
        new, k = rx.subn(given, a)
        out.append(new)
        n += k
    return out, n


def serve(url, port=None, seconds=None, opener=None, say=print):
    """Run a relay for url's origin until Ctrl-C (or for `seconds`); returns {"url", "relay_url", "stats"}."""
    relay = s3relay.Relay(url, port=port, opener=opener).start()
    given = relay.url_for(url)
    say(f"relay for {relay.origin} on {relay.base}")
    say(f"give VC3D this URL: {given}")
    say("stop with Ctrl-C" if seconds is None else f"stops after {seconds:g} s")
    try:
        if seconds is None:
            while True:
                time.sleep(3600)
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    finally:
        relay.stop()
    return {"url": url, "relay_url": given, "stats": dict(relay.stats)}


def run_through(url, command, port=None, ledger=DEFAULT_LEDGER, env=None, root=None, opener=None, say=print):
    """Run one command with url swapped for a relay's, the cache checked around it. Returns a report with
    "returncode" (the command's) and "affected" (markers deleted since the run started: chunks it may have read as
    zeros). CacheError, before anything runs, for a cache.json VC3D would refuse."""
    root = root or vc3d_cache.cache_root(env)
    relay = s3relay.Relay(url, port=port, opener=opener).start()
    given = relay.url_for(url)
    store = None
    if opener is not None:
        from . import vc3d_audit
        store = lambda: vc3d_audit.HttpStore(str(url), opener=opener, rate=0)  # noqa: E731
    guard = vc3d_cache.Guard(url, env=env, ledger_dir=ledger, store_factory=store, root=root, cache_url=given)
    cmd, swapped = swap(command, url, given)
    report = {"url": url, "relay_url": given, "command": cmd, "swapped": swapped}
    try:
        before = guard.before()
        if before.get("deleted"):
            say(f"before the run: deleted {before['deleted']} false empty-chunk markers left by earlier runs")
        if not swapped:
            say(f"note: the command does not contain {url}; it runs unchanged")
        say(f"running: {' '.join(cmd)}")
        try:
            rc = subprocess.run(cmd, env=env).returncode
        except OSError as exc:
            say(f"kit s3relay: cannot run {cmd[0]}: {exc}")
            rc = 127
        after = guard.after()
    finally:
        relay.stop()
    report.update(returncode=rc, stats=dict(relay.stats), affected=after.get("affected", []),
                  cache=guard.summary())
    return report


def format_run(r):
    s = r["stats"]
    lines = [f"relay: {s['requests']} requests, {s['false_404']} false 404s asked again, {s['missing']} missing keys "
             f"passed on, {s['gave_up']} given up (sent as 503), {s['network_errors']} network errors",
             f"cache: {r['cache']['checked']} markers checked, {r['cache']['false_deleted']} false ones deleted "
             f"({r['cache']['cache']})"]
    if r["cache"].get("error"):
        lines.append(f"cache check failed: {r['cache']['error']}")
    if r["affected"]:
        lines.append(f"{len(r['affected'])} chunks the run may have read as zeros (their false markers are deleted "
                     "now): run it again")
        lines += [f"  {m}" for m in r["affected"][:20]]
    lines.append(f"command exit code {r['returncode']}")
    return "\n".join(lines)


def check_cache(url, delete=True, recheck=False, relay=True, root=None, ledger=DEFAULT_LEDGER, env=None,
                opener=None, progress=None):
    """{"cache_root", "volumes": [check reports], totals}: the folder for each spelling VC3D may have been given
    (forms(), and through a relay on any of its preferred ports when relay is true) that exists, the direct one
    always."""
    root = Path(root) if root else vc3d_cache.cache_root(env)
    given = forms(url)
    if relay:
        given += [r for g in given for r in s3relay.candidate_urls(g)]
    seen, out = set(), {"cache_root": str(root), "volumes": []}
    for i, g in enumerate(dict.fromkeys(given)):
        folder = vc3d_cache.volume_dir(g, root=root)
        if folder.name in seen or (i and not folder.is_dir()):
            continue
        seen.add(folder.name)
        store = None
        if opener is not None:
            from . import vc3d_audit
            store = vc3d_audit.HttpStore(str(url), opener=opener, rate=0)
        rep = vc3d_cache.check(url, env, ledger, store=store, delete=delete, recheck=recheck, progress=progress,
                               root=root, cache_url=g)
        out["volumes"].append({"folder": folder.name, "given": g, **rep})
    out["false_found"] = sum(len(v.get("false", [])) for v in out["volumes"])
    out["false_deleted"] = sum(v.get("deleted", 0) for v in out["volumes"])
    out["unknown"] = sum(len(v.get("unknown", [])) for v in out["volumes"])
    return out


def list_cache(root=None, ledger=DEFAULT_LEDGER, env=None):
    """Every volume folder under the cache root with its marker count and, when a ledger names it, its URL."""
    root = Path(root) if root else vc3d_cache.cache_root(env)
    known = {}
    for led in sorted(Path(ledger).glob("*.json")) if ledger else []:
        data = vc3d_cache.Ledger(led).read()
        if data.get("url"):
            known[led.stem] = data["url"]
    folders = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    return {"cache_root": str(root),
            "volumes": [{"folder": f.name, "markers": len(vc3d_cache.markers(f)), "url": known.get(f.name)}
                        for f in folders]}


def format_check(r):
    lines = [f"VC3D remote cache: {r['cache_root']}"]
    for v in r["volumes"]:
        if v.get("markers") == 0 and not Path(r["cache_root"], v["folder"]).is_dir():
            lines.append(f"  {v['folder']}: no cache folder (VC3D has not read {v['given']})")
            continue
        lines.append(f"  {v['folder']}: {v['markers']} empty-chunk markers, {v['known_true']} known true, "
                     f"{v['checked']} checked: {len(v['false'])} false ({v['deleted']} deleted), {v['true']} true, "
                     f"{len(v['unknown'])} unknown")
        if v.get("error"):
            lines.append(f"    check failed: {v['error']}")
    lines.append(f"{r['false_found']} false markers found, {r['false_deleted']} deleted, {r['unknown']} unknown")
    return "\n".join(lines)


def format_list(r):
    lines = [f"VC3D remote cache: {r['cache_root']}"]
    if not r["volumes"]:
        lines.append("  no volume folders")
    for v in r["volumes"]:
        lines.append(f"  {v['folder']}: {v['markers']} empty-chunk markers" + (f", {v['url']}" if v["url"] else ""))
    lines.append("check one with: python -m kit vc3dcache URL (the URL VC3D was given)")
    return "\n".join(lines)


def _url_ok(url):
    try:
        s3relay.origin_of(url)
    except s3relay.RelayError as exc:
        return str(exc)
    return None


def build_parser(p, action):
    if action == "s3relay":
        p.add_argument("url", help="the remote zarr VC3D should read, s3:// or https://")
        p.add_argument("--port", type=int, help="listen on this port (default: one chosen from the URL's host, so "
                                                "repeated runs reuse one VC3D cache folder)")
        p.add_argument("--for", dest="seconds", type=float, help="without a command: stop after this many seconds")
        p.add_argument("--ledger", default=DEFAULT_LEDGER, help="with a command: folder of the cache check's records")
        p.add_argument("cmd", nargs="*", metavar="COMMAND",
                       help="a command to run through the relay, after --; the URL in it is swapped for the relay's")
    else:
        p.add_argument("url", nargs="?", help="the remote volume's URL as VC3D was given it (not the relay's)")
        p.add_argument("--all", action="store_true", help="list every volume folder in the cache instead")
        p.add_argument("--no-delete", action="store_true", help="report false markers without deleting them")
        p.add_argument("--recheck", action="store_true", help="ask again about markers already found true")
        p.add_argument("--no-relay", action="store_true", help="skip the folders of relay URLs")
        p.add_argument("--root", help="VC3D's remote cache folder (default: found the way VC3D finds it)")
        p.add_argument("--ledger", default=DEFAULT_LEDGER, help="folder of the check's records")
    p.add_argument("--json", action="store_true")
    return p


def cmd_s3relay(args):
    """python -m kit s3relay URL [-- COMMAND]: 0 (or the command's exit code), 4 when the command succeeded but
    may have read zeros, 2 on a bad URL, no free port or a cache.json VC3D would refuse."""
    bad = _url_ok(args.url)
    if bad:
        print(f"kit s3relay: {bad}", file=sys.stderr)
        return 2
    say = (lambda s: print(s, file=sys.stderr)) if args.json else print
    try:
        if args.cmd:
            r = run_through(args.url, args.cmd, args.port, args.ledger, say=say)
        else:
            r = serve(args.url, args.port, args.seconds, say=say)
    except (s3relay.RelayError, vc3d_cache.CacheError) as exc:
        print(f"kit s3relay: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r, indent=1))
    elif args.cmd:
        print(format_run(r))
    else:
        s = r["stats"]
        print(f"relay stopped: {s['requests']} requests, {s['false_404']} false 404s asked again, {s['gave_up']} "
              "given up")
    if not args.cmd:
        return 0
    if r["returncode"] == 0 and r["affected"]:
        return AFFECTED_EXIT
    return r["returncode"]


def cmd_vc3dcache(args):
    """python -m kit vc3dcache URL: 0 when no false marker is left, 1 when --no-delete found some, 3 when some stay
    unknown, 2 on a usage error or a cache.json VC3D would refuse."""
    if args.all:
        try:
            r = list_cache(args.root, args.ledger)
        except vc3d_cache.CacheError as exc:
            print(f"kit vc3dcache: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(r, indent=1) if args.json else format_list(r))
        return 0
    if not args.url:
        print("kit vc3dcache: give the volume's URL, or --all", file=sys.stderr)
        return 2
    bad = _url_ok(args.url)
    if bad:
        print(f"kit vc3dcache: {bad}", file=sys.stderr)
        return 2
    say = (lambda s: print(s, file=sys.stderr)) if args.json else print
    try:
        r = check_cache(args.url, not args.no_delete, args.recheck, not args.no_relay, args.root, args.ledger,
                        progress=say)
    except vc3d_cache.CacheError as exc:
        print(f"kit vc3dcache: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1) if args.json else format_check(r))
    if r["false_found"] > r["false_deleted"]:
        return 1
    return 3 if r["unknown"] else 0
