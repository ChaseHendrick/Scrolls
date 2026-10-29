#!/usr/bin/env python3
"""Download villa's current Linux VC3D AppImage and check its sha256.

  python3 scripts/get_vc3d.py                      the AppImage in villa's `latest` release, into this folder
  python3 scripts/get_vc3d.py stable               the one in villa's `stable` release instead
  python3 scripts/get_vc3d.py URL --sha256 HEX     one pinned file

villa rebuilds its `latest` release from main on every build and deletes the one before, so a file name taken
from it stops downloading within days. This asks GitHub's API which AppImage the release holds now, downloads it,
checks it against the sha256 GitHub publishes for the asset, and makes it executable. A file already there with
the right sha256 is kept. While villa is uploading a new `latest` the release is missing for a few minutes, so a
missing release, a server error or a broken download is tried again a few times over about three minutes.
stdout gets the file's path and nothing else, so `APPIMAGE="$(python3 scripts/get_vc3d.py)"` works; the name,
source and sha256 go to stderr, and to a JSON file with --record. Set GITHUB_TOKEN if GitHub's API limit for
anonymous requests (60 an hour) gets in the way. Standard library only, Python 3.8 or newer.
"""

import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com/repos/ScrollPrize/villa/releases/tags/{tag}"
APPIMAGE = re.compile(r"VC3D-[\w.-]+-linux-x86_64\.AppImage")
RETRY_DELAYS = (15, 45, 120)   # seconds before each new try after a passing failure; tests set it to zeros


class FetchError(Exception):
    pass


class Passing(FetchError):
    """A failure worth another try: the release is being replaced, a server error, a broken connection."""


def release_asset(release):
    """(name, url, sha256 or None) of the one Linux x86_64 AppImage in a GitHub release's JSON."""
    assets = release.get("assets") or []
    found = [a for a in assets if APPIMAGE.fullmatch(a.get("name") or "")]
    if len(found) != 1:
        names = ", ".join(a.get("name") or "?" for a in assets) or "none"
        raise FetchError(f"expected one *-linux-x86_64.AppImage in the release, found {len(found)} (assets: {names})")
    digest = found[0].get("digest") or ""
    sha = digest[7:].lower() if digest.lower().startswith("sha256:") else None
    return found[0]["name"], found[0]["browser_download_url"], sha


def _token():
    return os.environ.get("GITHUB_TOKEN") or None


def _open(url, accept=None, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "get_vc3d", **({"Accept": accept} if accept else {})})
    if _token() and urllib.parse.urlsplit(url).hostname == "api.github.com":
        # unredirected: a redirect to another host must not carry the token
        req.add_unredirected_header("Authorization", "Bearer " + _token())
    return urllib.request.urlopen(req, timeout=timeout)


def find(tag, api=API):
    """The AppImage that villa's release `tag` holds now, as release_asset gives it."""
    url = api.format(tag=urllib.parse.quote(tag))
    try:
        with _open(url, accept="application/vnd.github+json") as r:
            release = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404 and tag == "latest":
            raise Passing(f"villa has no `latest` release right now ({url} answered 404); villa deletes it and "
                          f"uploads a new one on every build, which takes a few minutes") from None
        if e.code == 404:
            raise FetchError(f"villa has no `{tag}` release ({url} answered 404); its releases are latest and "
                             f"stable") from None
        if e.code == 401 and _token():
            raise FetchError(f"GitHub refused the GITHUB_TOKEN that is set ({url} answered 401): replace it or "
                             f"unset it") from None
        if e.code in (401, 403, 429):
            raise FetchError(f"GitHub's API refused {url} ({e.code}), most likely its limit of 60 anonymous "
                             f"requests an hour. Set GITHUB_TOKEN (for `docker build`, pass it with --secret "
                             f"id=github_token,env=GITHUB_TOKEN), or pin one AppImage URL and its sha256") from None
        if e.code >= 500:
            raise Passing(f"{url} answered {e.code}") from None
        raise FetchError(f"{url} answered {e.code}") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise Passing(f"could not reach {url}: {getattr(e, 'reason', e)}") from None
    except ValueError:
        raise Passing(f"{url} did not answer with a release's JSON") from None
    return release_asset(release)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url, path, expected=None):
    """Download url to path through path + '.part', checking the sha256 when expected is given; returns it.
    The .part file goes away on any failure, Ctrl-C included."""
    part = path + ".part"
    h, n = hashlib.sha256(), 0
    try:
        try:
            with _open(url, timeout=120) as r, open(part, "wb") as f:
                for block in iter(lambda: r.read(1 << 20), b""):
                    h.update(block)
                    f.write(block)
                    n += len(block)
                size = r.headers.get("Content-Length")
        except urllib.error.HTTPError as e:
            # 404: the release was replaced between the lookup and the download
            raise (Passing if e.code == 404 or e.code >= 500 else FetchError)(
                f"could not download {url}: it answered {e.code}") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise Passing(f"could not download {url}: {getattr(e, 'reason', e)}") from None
        if size and size.isdigit() and n != int(size):
            raise Passing(f"the download of {url} stopped after {n} of {size} bytes")
        got = h.hexdigest()
        if expected and got != expected:
            raise FetchError(f"{url} has sha256 {got}, not the expected {expected}; nothing was kept")
        os.chmod(part, 0o755)
        os.replace(part, path)
        return got
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise


def get(source="latest", out=".", sha256=None, api=API, require_sha256=False, say=None):
    """Fetch the AppImage named by source (a villa release tag, or an https URL) into out; returns a record.
    require_sha256: refuse to download a file with no sha256 to check it against."""
    sha256 = (sha256 or "").strip().lower() or None
    if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise FetchError(f"--sha256 {sha256} is not 64 hex digits")
    say = say or (lambda msg: print(f"get_vc3d: {msg}", file=sys.stderr))
    for attempt, delay in enumerate((*RETRY_DELAYS, None)):
        try:
            return _get_once(source, out, sha256, api, require_sha256)
        except Passing as e:
            if delay is None:
                raise FetchError(f"{e} (gave up after {attempt + 1} tries)") from None
            say(f"{e}; trying again in {delay} s")
            time.sleep(delay)


def _get_once(source, out, sha256, api, require_sha256):
    if "://" in source:
        url, tag = source, None
        name = os.path.basename(urllib.parse.unquote(urllib.parse.urlsplit(url).path))
        if name in ("", ".", ".."):
            raise FetchError(f"{url} names no file")
        published = None
    else:
        tag = source
        name, url, published = find(tag, api)
        if sha256 and published and sha256 != published:
            raise FetchError(f"--sha256 {sha256} is not the sha256 GitHub publishes for {name} ({published})")
    expected = sha256 or published
    if require_sha256 and not expected:
        raise FetchError(f"no sha256 to check {name} against: " + (
            "pass the URL's sha256 too" if tag is None else "GitHub publishes none for it; pin its URL and sha256"))
    os.makedirs(out, exist_ok=True)
    path = os.path.abspath(os.path.join(out, name))
    if expected and os.path.isfile(path) and sha256_of(path) == expected:
        os.chmod(path, 0o755)
        got, kept = expected, True
    else:
        got, kept = download(url, path, expected), False
    return {"path": path, "name": name, "url": url, "release": tag, "sha256": got,
            "checked_against": "--sha256" if sha256 else ("GitHub" if published else None), "kept_existing": kept}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="get_vc3d.py", description=__doc__.split("\n")[0])
    ap.add_argument("source", nargs="?", default="latest",
                    help="a villa release tag (latest, the default; stable) or an AppImage URL")
    ap.add_argument("--sha256", default="", help="the file's expected sha256 (needed to check a URL)")
    ap.add_argument("--require-sha256", action="store_true",
                    help="refuse a file with no sha256 to check it against (the Dockerfile sets this)")
    ap.add_argument("--out", default=".", help="folder to put the AppImage in (default: this one)")
    ap.add_argument("--record", help="also write the name, URL and sha256 of what was fetched to this JSON file")
    ap.add_argument("--api", default=API, help=argparse.SUPPRESS)   # tests point this at a local server
    a = ap.parse_args(argv)
    try:
        rec = get(a.source, a.out, a.sha256, a.api, a.require_sha256)
    except FetchError as e:
        print(f"get_vc3d: {e}", file=sys.stderr)
        return 1
    check = {"GitHub": "matches the sha256 GitHub publishes", "--sha256": "matches --sha256"}.get(
        rec["checked_against"], "NOT checked: no sha256 was given or published")
    print(f"get_vc3d: {rec['name']} from {rec['url']}\nget_vc3d: sha256 {rec['sha256']} ({check})"
          + ("; already there, kept" if rec["kept_existing"] else ""), file=sys.stderr)
    if a.record:
        with open(a.record, "w") as f:
            json.dump(rec, f, indent=2)
            f.write("\n")
    print(rec["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
