"""What exists for one scroll, and how to credit it: one command instead of browsing the bucket, the data browser
and the Hub by hand.

  find   the scroll's volumes (voxel size, shape, licence, prize eligibility from kit's dated snapshot), how many
         segments it has on which volume, every prediction and representation folder in the open-data bucket
         (surfaces, lasagna, fibers, ink, umbilicus files), center lines in SharpMeow/vesuvius-center-lines, and
         Hugging Face datasets, models and Spaces whose names or cards match the scroll's id
  cite   the credit and licence lines for a scroll's volumes (and, with --centerline, for its center lines), ready
         to paste under a figure or into a README

Sources, all public and read over anonymous HTTPS: the bucket's metadata.json and its listing, the Hugging Face Hub
API search, and the center lines dataset's index.json. Nothing is downloaded beyond those listings, and nothing is
posted. A Hub match is a name match, not a check that the data is right; open its card before using it.
"""

import argparse
import gzip
import json
import re
import sys
import urllib.parse
import urllib.request

from .verify import VerifyError

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
METADATA = BUCKET + "/metadata.json"
HUB = "https://huggingface.co"
CENTERLINES = "SharpMeow/vesuvius-center-lines"
CENTERLINES_INDEX = f"{HUB}/datasets/{CENTERLINES}/resolve/main/index.json"
DATA_CREDIT = "Vesuvius Challenge open data"
SCROLL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,40}$")


def http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "scrolls-kit find", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def get_json(url, get=http_get):
    return json.loads(get(url).decode("utf-8"))


def check_id(scroll):
    if not SCROLL_ID.match(scroll or ""):
        raise VerifyError(f"not a scroll id: {scroll!r} (for example PHerc0139)")
    return scroll


def sample(meta, scroll):
    """The metadata.json sample for a scroll id, matched without regard to case."""
    samples = meta.get("samples") or {}
    for k, v in samples.items():
        if k.lower() == scroll.lower():
            return k, v
    near = sorted(k for k in samples if scroll.lower().rstrip("ab") in k.lower())
    hint = f"; close: {', '.join(near[:6])}" if near else ""
    raise VerifyError(f"{scroll} is not in the open-data metadata.json{hint}")


def list_prefix(prefix, get=http_get):
    """(sub-folders, [(key, size)]) directly under a bucket prefix."""
    out_p, out_k, token = [], [], None
    while True:
        q = {"list-type": "2", "delimiter": "/", "prefix": prefix}
        if token:
            q["continuation-token"] = token
        x = get(f"{BUCKET}/?{urllib.parse.urlencode(q)}").decode("utf-8")
        out_p += [p for p in re.findall(r"<Prefix>(.*?)</Prefix>", x) if p != prefix]
        out_k += [(k, int(s)) for k, s in re.findall(r"<Key>(.*?)</Key>.*?<Size>(\d+)</Size>", x, re.S)]
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", x)
        if not m:
            return out_p, out_k
        token = m.group(1)


def representations(scroll, get=http_get):
    """{kind: [names]} of the bucket's SCROLL/representations: umbilicus files and each predictions/KIND/ folder."""
    out = {}
    base = f"{scroll}/representations/"
    kinds, files = list_prefix(base, get)
    for k in kinds:
        name = k[len(base):].strip("/")
        sub, keys = list_prefix(k, get)
        if name == "predictions":
            for kind in sub:
                runs, rk = list_prefix(kind, get)
                out[f"predictions/{kind[len(k):].strip('/')}"] = [r[len(kind):].strip("/") for r in runs] + \
                    [key[len(kind):] for key, _ in rk]
        else:
            out[name] = [s[len(k):].strip("/") for s in sub] + [key[len(k):] for key, _ in keys]
    for key, _ in files:
        out.setdefault("files", []).append(key[len(base):])
    return out


def hub_search(scroll, get=http_get):
    """Hub repos whose id or card matches the scroll id: [{"type", "id", "url"}]."""
    found = []
    for kind, path in (("dataset", "datasets"), ("model", "models"), ("space", "spaces")):
        try:
            rows = get_json(f"{HUB}/api/{path}?search={urllib.parse.quote(scroll)}&limit=50", get)
        except (OSError, ValueError):
            continue
        for r in rows:
            rid = r.get("id")
            if rid and not r.get("private"):
                prefix = "" if kind == "model" else f"{path}/"
                found.append({"type": kind, "id": rid, "url": f"{HUB}/{prefix}{rid}"})
    return found


def centerlines(scroll, get=http_get):
    """Rows of the center lines dataset's index.json for this scroll ([] when it has none or the Hub is down)."""
    try:
        idx = get_json(CENTERLINES_INDEX, get)
    except (OSError, ValueError):
        return []
    return [f for f in idx.get("files", []) if str(f.get("scroll", "")).lower() == scroll.lower()]


def eligible_volumes():
    """{volume id: [prize names]} from kit's dated prize snapshot."""
    from . import prizes
    try:
        snap = prizes.load()
    except (OSError, ValueError):
        return {}
    out = {}
    for p in snap.get("prizes", []):
        for v in re.findall(r"\b\d{14}\b", json.dumps(p)):
            out.setdefault(v, [])
            name = p.get("title") or p.get("id")
            if name and name not in out[v]:
                out[v].append(name)
    return out


def find(scroll, get=http_get, hub=True):
    """Everything kit can see for one scroll, as a dict."""
    check_id(scroll)
    meta = get_json(METADATA, get)
    sid, s = sample(meta, scroll)
    elig = eligible_volumes()
    vols = []
    for vid, v in sorted((s.get("volumes") or {}).items()):
        pr = v.get("properties") or {}
        lic = pr.get("license") or {}
        vols.append({"id": vid, "long_id": v.get("long_id"), "voxel_um": pr.get("pixel_size_um"),
                     "shape_zyx": pr.get("shape"), "licence": lic.get("name"), "superseded_by": pr.get("superseded_by"),
                     "prizes": elig.get(vid, []), "url": f"{BUCKET}/{sid}/volumes/{v.get('long_id')}/"})
    segs = s.get("segments") or {}
    by_vol = {}
    for g in segs.values():
        by_vol[g.get("original_volume_id") or "unknown"] = by_vol.get(g.get("original_volume_id") or "unknown", 0) + 1
    out = {"scroll": sid, "volumes": vols, "segments": {"count": len(segs), "by_volume": by_vol,
                                                       "url": f"{BUCKET}/{sid}/segments/"},
           "representations": representations(sid, get), "centerlines": centerlines(sid, get),
           "hub": hub_search(sid, get) if hub else None,
           "browse": f"https://scrollprize.org/data_browser/"}
    return out


def cite(scroll, get=http_get, with_centerlines=False, volume=None):
    """Credit lines: one per volume (or the one --volume names), and per center line with --centerline."""
    check_id(scroll)
    meta = get_json(METADATA, get)
    sid, s = sample(meta, scroll)
    lines = []
    for vid, v in sorted((s.get("volumes") or {}).items()):
        if volume and volume not in (vid, v.get("long_id")):
            continue
        lic = (v.get("properties") or {}).get("license") or {}
        name, url = lic.get("name") or "licence not stated in metadata.json", lic.get("url") or ""
        lines.append({"what": f"{sid} volume {v.get('long_id')}", "credit": f"{DATA_CREDIT}, {name}",
                      "licence_url": url, "source": f"{BUCKET}/{sid}/volumes/{v.get('long_id')}/"})
    if volume and not lines:
        raise VerifyError(f"{sid} has no volume {volume}")
    if with_centerlines:
        for f in centerlines(sid, get):
            lines.append({"what": f"{sid} center line ({f.get('source')})", "credit": f.get("credit"),
                          "licence_url": f.get("licence"), "source": f"{HUB}/datasets/{CENTERLINES}/blob/main/{f.get('file')}"})
    return {"scroll": sid, "lines": lines}


def format_find(r):
    lines = [f"{r['scroll']}"]
    lines.append(f"  volumes ({len(r['volumes'])})")
    for v in r["volumes"]:
        shp = "x".join(str(n) for n in (v["shape_zyx"] or [])) or "?"
        pz = f"  prize: {', '.join(v['prizes'])}" if v["prizes"] else ""
        s = v["superseded_by"]
        sup = f"  superseded by {s.get('volume_id', s) if isinstance(s, dict) else s}" if s else ""
        lines.append(f"    {v['long_id']}  {v['voxel_um']} um  {shp} (z y x)  {v['licence']}{pz}{sup}")
    sg = r["segments"]
    per = ", ".join(f"{n} on {k}" for k, n in sorted(sg["by_volume"].items())) or "none"
    lines.append(f"  segments: {sg['count']} ({per})")
    rep = r["representations"]
    if rep:
        lines.append("  bucket representations")
        for k, names in sorted(rep.items()):
            lines.append(f"    {k}: {len(names)}")
            lines += [f"      {n}" for n in names[:12]]
            if len(names) > 12:
                lines.append(f"      ... and {len(names) - 12} more")
    else:
        lines.append("  bucket representations: none")
    if r["centerlines"]:
        lines.append(f"  center lines in {CENTERLINES}")
        lines += [f"    {f['source']} ({f.get('kind', '')}, {f.get('points')} points)  {f['file']}" for f in r["centerlines"]]
    if r["hub"] is not None:
        lines.append(f"  Hugging Face matches ({len(r['hub'])}; a name match, read each card first)")
        lines += [f"    {h['type']:<7} {h['url']}" for h in r["hub"]]
    lines.append(f"  bucket: {BUCKET}/{r['scroll']}/   browser: {r['browse']}")
    return "\n".join(lines)


def format_cite(r):
    out = []
    for l in r["lines"]:
        lic = l["licence_url"] or ""
        tail = f" ({lic})" if lic.startswith("http") else f", {lic}" if lic and lic not in str(l["credit"]) else ""
        out.append(f"{l['what']}: {l['credit']}{tail}")
        out.append(f"  source: {l['source']}")
    return "\n".join(out)


def build_parser(p, action):
    p.add_argument("scroll", help="scroll id as in the bucket, for example PHerc0139 or PHerc0175A")
    if action == "find":
        p.add_argument("--no-hub", action="store_true", help="skip the Hugging Face search")
    else:
        p.add_argument("--volume", help="only this volume (short or long id)")
        p.add_argument("--centerline", action="store_true", help="also credit the scroll's center lines")
    p.add_argument("--json", action="store_true")
    return p


def cmd_find(args):
    """python -m kit find SCROLL: exit 0 when listed, 2 when the scroll is unknown or the bucket cannot be read."""
    try:
        r = find(args.scroll, hub=not args.no_hub)
    except VerifyError as exc:
        print(f"kit find: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"kit find could not read the bucket's metadata or listing: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1) if args.json else format_find(r))
    return 0


def cmd_cite(args):
    """python -m kit cite SCROLL: exit 0 with the lines, 2 when the scroll or volume is unknown."""
    try:
        r = cite(args.scroll, with_centerlines=args.centerline, volume=args.volume)
    except VerifyError as exc:
        print(f"kit cite: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"kit cite could not read the bucket's metadata: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1) if args.json else format_cite(r))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.find", description=__doc__.split("\n\n")[0])
    build_parser(p, "find")
    return cmd_find(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
