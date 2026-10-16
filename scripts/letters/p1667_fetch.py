"""Fetch the public PHerc. 1667 data the letter benchmarks read, from the open-data bucket (anonymous HTTPS).

Writes OUT/maps/<wNNN>.tif (the 19 segments' 2.4 um ink-detection maps, about 1.9 GB in all) and
OUT/labels/<wNNN>/z/1/ (level 1 of the six labelled segments' official inklabels.zarr, under 1 MB).
Resumable: files already there at their listed size are kept; a cut-off download is refused.
Standard library only.

  python scripts/letters/p1667_fetch.py OUT [--labels-only]

--labels-only fetches the six label sets alone (under 1 MB, no maps): enough for p1667_groups.py and
eval_p1667.py --source label, the drawings row of docs/letter-reader.md's table "How well it reads".

Then: p1667_groups.py OUT/labels GROUPS, p1667_mapcrops.py GROUPS OUT/maps [--wide|--region], and
eval_p1667_text.py cut OUT/maps NPY for whole maps on the 38 um grid (see docs/letter-reader.md).
"""
import argparse
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
LABELLED = ("w013", "w018", "w023", "w028", "w029", "w031")
SEGMENTS = ("w011", "w012", "w013", "w018", "w023", "w028", "w029", "w030", "w031", "w032", "w033", "w034",
            "w035", "w036", "w037", "w038", "w039", "w040", "w041")
LABELS = "ink-labels/2.399um-volume-20251217075048/20260918/inklabels.zarr/"


def _get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read().decode()


def keys(prefix, delimiter=False, sizes=False):
    """Every key (or with delimiter, every sub-prefix) under prefix; with sizes, {key: size in bytes}."""
    out, size, token = [], {}, None
    while True:
        url = f"{BUCKET}/?list-type=2&prefix={prefix}" + ("&delimiter=/" if delimiter else "")
        if token:
            url += "&continuation-token=" + urllib.request.quote(token)
        x = _get(url)
        if delimiter:
            out += re.findall(r"<Prefix>([^<]*)</Prefix>", x)
        else:
            for block in x.split("<Contents>")[1:]:
                k, n = re.search(r"<Key>([^<]*)</Key>", block), re.search(r"<Size>(\d+)</Size>", block)
                out.append(k.group(1))
                size[k.group(1)] = int(n.group(1)) if n else None
        m = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", x)
        if not m:
            out = [k for k in out if k != prefix]
            return {k: size[k] for k in out} if sizes else out
        token = m.group(1)


def segment_prefix(seg, prefixes):
    """The one flattened segment folder of a segment id (merged or straightened variants are left out)."""
    p = [q for q in prefixes if f"-{seg}_" in q and q.endswith("flatboi/")]
    if len(p) != 1:
        raise SystemExit(f"{seg}: {len(p)} segment folders in the bucket")
    return p[0]


def label_path(root, base, key):
    """Where a listed label key goes under root: refused unless it is a plain relative path below base (the listing
    comes from the network, and a key such as BASE/../../x would otherwise write outside OUT)."""
    tail = key[len(base):] if key.startswith(base) else ""
    parts = tail.split("/")
    if not tail or tail.startswith("/") or "\\" in tail or any(p in ("", ".", "..") for p in parts):
        raise SystemExit(f"refusing unsafe key {key!r}")
    dest = Path(root) / tail
    if not dest.resolve().is_relative_to(Path(root).resolve()):
        raise SystemExit(f"refusing key {key!r}: it leaves {root}")
    return dest


def download(key, dest, size=None):
    """Fetch one key unless dest is already complete: its size, when the listing gave one, else not empty.
    A body shorter than its Content-Length (or than size) is refused, so a cut-off file is never kept."""
    if dest.exists() and dest.stat().st_size > 0 and size in (None, dest.stat().st_size):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    n = 0
    with urllib.request.urlopen(f"{BUCKET}/{key}", timeout=600) as r, open(tmp, "wb") as f:
        want = r.headers.get("Content-Length")
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            n += len(b)
    for expected in (want, size):
        if expected is not None and n != int(expected):
            tmp.unlink(missing_ok=True)
            raise OSError(f"{key}: {n} bytes received, {expected} expected; nothing kept")
    tmp.replace(dest)


def main(out, labels_only=False):
    out = Path(out)
    prefixes = keys("PHerc1667/segments/", delimiter=True)
    jobs = []
    for seg in SEGMENTS:
        if labels_only and seg not in LABELLED:
            continue
        pre = segment_prefix(seg, prefixes)
        if not labels_only:
            listed = keys(pre + "ink-detection/", sizes=True)
            tif = [k for k in listed if re.search(r"2\.399um.*stride128\.tif$", k)]
            if len(tif) != 1:
                raise SystemExit(f"{seg}: {len(tif)} 2.4 um maps")
            jobs.append((tif[0], out / "maps" / f"{seg}.tif", listed[tif[0]]))
            print(seg, tif[0], flush=True)
        if seg in LABELLED:
            base = pre + LABELS
            jobs += [(k, label_path(out / "labels" / seg / "z" / "1", base + "1/", k), n)
                     for k, n in keys(base + "1/", sizes=True).items()]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda j: download(*j), jobs))
    print("done:", len(jobs), "files in", out, flush=True)


def parse_args(argv=None):
    """OUT and --labels-only; an unknown option or a missing OUT stops with the usage (so a mistyped
    --labels-only never starts the 1.9 GB download of every map)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="folder to write maps/ and labels/ into, such as work/p1667")
    ap.add_argument("--labels-only", action="store_true",
                    help="only the six label sets, under 1 MB (enough for the drawings row of the guide)")
    return ap.parse_args(argv)


if __name__ == "__main__":
    a = parse_args()
    main(a.out, a.labels_only)
