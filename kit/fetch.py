"""Mirror one prefix of the public Vesuvius Challenge bucket over anonymous HTTPS.

The same files ``aws s3 sync --no-sign-request`` would fetch, without the AWS CLI.
Existing files of the right size are skipped, so an interrupted fetch resumes.
"""

import concurrent.futures
import os
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from . import s3retry

BUCKET_URL = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
W035_9UM = ("PHerc0139/segments/20260317000000-w035_2026031718/surface-volumes/"
            "9.362um-1.2m-113keV-volume-20250728140407.zarr")
# Unseen by v8in (its patch pack lists w033, w035, w041, w044 for PHerc0139). Not held out
# from ink_9um: its 2.4 um render is ink_9um training segment pherc0139-w029, so for ink_9um
# and its fine-tunes this native 9.362 um render is a cross-scan check on a training surface
# (docs/logs/2026-10-08-w045-not-held-out.md).
W045_9UM = ("PHerc0139/segments/20260126000000-w045_2026012619/surface-volumes/"
            "9.362um-1.2m-113keV-volume-20250728140407.zarr")
ALIASES = {"w035": W035_9UM, "w045": W045_9UM}


class FetchError(Exception):
    pass


def parse_listing(xml):
    """Return ([(key, size)], next_token or None) from one ListObjectsV2 page."""
    entries = [
        (key, int(size))
        for key, size in re.findall(r"<Contents>.*?<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>.*?</Contents>", xml, re.S)
    ]
    token = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
    return entries, token.group(1) if token else None


def list_prefix(prefix, opener=urllib.request.urlopen, base=BUCKET_URL):
    prefix = prefix.strip("/") + "/"
    entries, token, seen = [], None, set()
    while True:
        url = f"{base}/?list-type=2&max-keys=1000&prefix={urllib.parse.quote(prefix)}"
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token, safe="")
        page, token = parse_listing(s3retry.open_url(url, opener, 60).read().decode())
        entries += page
        if not token:
            return prefix, entries
        if token in seen:
            raise FetchError("bucket listing repeated a continuation token")
        seen.add(token)


def local_path(dest, prefix, key):
    relative = key[len(prefix):]
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise FetchError(f"refusing unsafe key {key!r}")
    return Path(dest) / relative


MARGIN_BYTES = 1 << 30   # leave at least 1 GiB free after a fetch


def plan(prefix, dest, opener=urllib.request.urlopen, base=BUCKET_URL):
    """What a fetch would do, before it starts: objects, total bytes, bytes still missing at dest, free bytes there."""
    prefix, entries = list_prefix(prefix, opener, base)
    if not entries:
        raise FetchError(f"nothing under s3://vesuvius-challenge-open-data/{prefix}")
    missing = 0
    for key, size in entries:
        out = local_path(dest, prefix, key)
        if not (out.exists() and out.stat().st_size == size):
            missing += size
    probe = Path(dest)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    return {"prefix": prefix, "objects": len(entries), "total_bytes": sum(s for _, s in entries),
            "missing_bytes": missing, "free_bytes": free, "fits": missing + MARGIN_BYTES <= free,
            "entries": entries}


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000


def fetch_prefix(prefix, dest, workers=16, opener=urllib.request.urlopen, base=BUCKET_URL, entries=None):
    if entries is None:
        prefix, entries = list_prefix(prefix, opener, base)
    else:
        prefix = prefix.strip("/") + "/"
    if not entries:
        raise FetchError(f"nothing under s3://vesuvius-challenge-open-data/{prefix}")

    def get(entry):
        key, size = entry
        out = local_path(dest, prefix, key)
        if out.exists() and out.stat().st_size == size:
            return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        last = None
        for _ in range(4):
            try:
                # a false 404 (S3's NoSuchBucket for a key it just listed) is asked again on a new connection
                data = s3retry.open_url(f"{base}/{urllib.parse.quote(key)}", opener, 120).read()
                if len(data) != size:
                    raise FetchError(f"{key}: got {len(data)} bytes, expected {size}")
                tmp = out.with_name(out.name + ".part")
                tmp.write_bytes(data)
                os.replace(tmp, out)
                return size
            except Exception as exc:  # retried: truncated reads happen (villa issue #1666)
                last = exc
        raise FetchError(f"{key}: {last}")

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        fetched = sum(pool.map(get, entries))
    return len(entries), fetched, sum(size for _, size in entries)
