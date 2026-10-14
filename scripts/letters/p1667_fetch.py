"""Fetch the public PHerc. 1667 data the letter benchmarks read, from the open-data bucket (anonymous HTTPS).

Writes OUT/maps/<wNNN>.tif (the 19 segments' 2.4 um ink-detection maps, about 1.9 GB in all) and
OUT/labels/<wNNN>/z/1/ (level 1 of the six labelled segments' official inklabels.zarr, under 1 MB).
Resumable: files already there are kept. Standard library only.

  python scripts/letters/p1667_fetch.py OUT [--labels-only]

Then: p1667_groups.py OUT/labels GROUPS, p1667_mapcrops.py GROUPS OUT/maps [--wide|--region], and
eval_p1667_text.py cut OUT/maps NPY for whole maps on the 38 um grid (see docs/letter-reader.md).
"""
import re
import sys
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


def keys(prefix, delimiter=False):
    """Every key (or with delimiter, every sub-prefix) under prefix."""
    out, token = [], None
    while True:
        url = f"{BUCKET}/?list-type=2&prefix={prefix}" + ("&delimiter=/" if delimiter else "")
        if token:
            url += "&continuation-token=" + urllib.request.quote(token)
        x = _get(url)
        out += re.findall(r"<Prefix>([^<]*)</Prefix>" if delimiter else r"<Key>([^<]*)</Key>", x)
        m = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", x)
        if not m:
            return [k for k in out if k != prefix]
        token = m.group(1)


def segment_prefix(seg, prefixes):
    """The one flattened segment folder of a segment id (merged or straightened variants are left out)."""
    p = [q for q in prefixes if f"-{seg}_" in q and q.endswith("flatboi/")]
    if len(p) != 1:
        raise SystemExit(f"{seg}: {len(p)} segment folders in the bucket")
    return p[0]


def download(key, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(f"{BUCKET}/{key}", timeout=600) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
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
            tif = [k for k in keys(pre + "ink-detection/") if re.search(r"2\.399um.*stride128\.tif$", k)]
            if len(tif) != 1:
                raise SystemExit(f"{seg}: {len(tif)} 2.4 um maps")
            jobs.append((tif[0], out / "maps" / f"{seg}.tif"))
            print(seg, tif[0], flush=True)
        if seg in LABELLED:
            base = pre + LABELS
            jobs += [(k, out / "labels" / seg / "z" / "1" / k[len(base) + 2:]) for k in keys(base + "1/")]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda j: download(*j), jobs))
    print("done:", len(jobs), "files in", out, flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        raise SystemExit(__doc__)
    main(sys.argv[1], "--labels-only" in sys.argv[2:])
