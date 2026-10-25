"""Pull a folder of a Hugging Face bucket to local disk fast: each distinct file once, through the Hub API.

The organizers' public bucket scrollprize/datasets holds the ink label stores that ink models train on
(ink_9um/labels/, ink/). They are zarr v2 folders of tiny chunk files, mostly copies of one empty chunk, and the
Hub serves bucket files at about 40 to 60 a second whatever their size, so the request count is the cost. This
module lists the folder once and downloads each distinct (Xet hash, size) once in one `download_bucket_files`
call, then copies it on disk to the other paths (25 Oct 2026: the PHerc0139 w035 ink_9um label store,
see docs/tools/hfpull.md). Public buckets (PUBLIC) need no token; a private one needs HF_TOKEN in the
environment. Without huggingface_hub or a token, it copies from a mounted copy of the bucket (a bucket volume in an
HF Job) with threads instead. `python -m kit.hfpull PREFIX DEST` runs one pull under a
Python that has huggingface_hub.

    from kit import hfpull
    stats = hfpull.pull("ink_9um/labels/aligned-scrollprizeorg-21slices/pherc0139-w035", "labels/w035")

Standard library at import time; huggingface_hub is imported only for the API route.
"""
import fnmatch
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PUBLIC = ("scrollprize/datasets",)     # buckets anyone may read: the API route runs without a token
BUCKET = PUBLIC[0]
MOUNT_WORKERS = 32


class HfPullError(RuntimeError):
    pass


def excluded(rel, patterns):
    """True when a pattern matches the path under the pulled folder or the file's own name."""
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(Path(rel).name, p) for p in patterns or ())


def has_token(env=None):
    env = os.environ if env is None else env
    return bool(env.get("HF_TOKEN") or env.get("HUGGING_FACE_HUB_TOKEN"))


def _api(anonymous=False):
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return None
    api = HfApi(token=False) if anonymous else HfApi()
    return api if hasattr(api, "download_bucket_files") and hasattr(api, "list_bucket_tree") else None


def plan_api(api, bucket, prefix, dest, exclude=()):
    """[(bucket file, local path), ...] for every file under prefix that no pattern excludes; a prefix that names
    one file gives [(that file, dest)]."""
    prefix = prefix.strip("/")
    out = []
    for it in api.list_bucket_tree(bucket, prefix=prefix, recursive=True):
        if getattr(it, "type", "file") != "file":
            continue
        if it.path == prefix:                   # prefix names one file: dest is that file's path, as in plan_mount
            out.append((it, Path(dest)))
            continue
        if prefix and not it.path.startswith(prefix + "/"):
            continue                            # the listing matches by string prefix: skip sibling folders
        rel = it.path[len(prefix) + 1:] if prefix else it.path
        if not rel or rel.endswith(".part") or excluded(rel, exclude):
            continue
        out.append((it, Path(dest) / rel))
    return out


def unique(todo):
    """(first, copies): the planned downloads with one file per content hash, and (downloaded path, local path) for
    every other file with the same content, to copy on disk afterwards. A file without a content hash is its own
    group. The Hub fetches a bucket file by its Xet hash at about 60 files a second whatever their size, and label
    zarrs are mostly one empty chunk repeated (docs/tools/hfpull.md)."""
    first, copies, seen = [], [], {}
    for f, q in todo:
        h = getattr(f, "xet_hash", None)
        key = (h, int(getattr(f, "size", 0) or 0)) if h else ("path", id(f))
        if key in seen:
            copies.append((seen[key], q))
        else:
            seen[key] = q
            first.append((f, q))
    return first, copies


def plan_mount(src, dest, exclude=()):
    """[(mounted file, local path), ...] for the same rule, read from the mount."""
    src, out = Path(src), []
    if src.is_file():
        return [(src, Path(dest))]
    for dp, dirs, names in os.walk(src):
        dirs.sort()
        for n in sorted(names):
            p = Path(dp) / n
            rel = p.relative_to(src).as_posix()
            if n.endswith(".part") or p.is_symlink() or excluded(rel, exclude):
                continue
            out.append((p, Path(dest) / rel))
    return out


def _copy(pq):
    p, q = pq
    q.parent.mkdir(parents=True, exist_ok=True)
    part = q.with_name(q.name + ".part")
    shutil.copyfile(p, part)
    os.replace(part, q)


def pull(prefix, dest, *, exclude=(), bucket=BUCKET, mount=None, api=None, env=None, workers=MOUNT_WORKERS,
         say=print, clock=time.monotonic):
    """Copy bucket folder `prefix` to `dest`. Returns {"route", "files", "bytes", "seconds"}.

    route "api" when huggingface_hub with bucket downloads is there and either a token is or the bucket is public
    (PUBLIC), or `api` is given; else "mount", reading `mount`/`prefix`. The API route downloads each distinct file
    once (unique) and copies the rest on disk. Raises HfPullError when neither route can run."""
    t0 = clock()
    dest = Path(dest)
    if api is None and has_token(env):
        api = _api()
    elif api is None and bucket in PUBLIC:
        api = _api(anonymous=True)
    if api is not None:
        todo = plan_api(api, bucket, prefix, dest, exclude)
        first, copies = unique(todo)
        for _, q in todo:
            q.parent.mkdir(parents=True, exist_ok=True)
        if first:
            api.download_bucket_files(bucket, [(f, str(q)) for f, q in first], raise_on_missing_files=True)
        for src, q in copies:
            _copy((src, q))
        size = sum(int(getattr(f, "size", 0) or 0) for f, _ in todo)
        route = "api"
    else:
        if not mount or not (Path(mount) / prefix).exists():
            raise HfPullError(f"no token for the API route and {Path(mount or '.') / prefix} is not mounted")
        todo = plan_mount(Path(mount) / prefix, dest, exclude)
        with ThreadPoolExecutor(max(1, int(workers))) as ex:
            list(ex.map(_copy, todo))
        size = sum(q.stat().st_size for _, q in todo)
        route = "mount"
    out = {"route": route, "files": len(todo), "bytes": size, "seconds": round(clock() - t0, 1)}
    if route == "api":
        out["downloaded"] = len(first)
    say(f"hfpull {prefix}: {out['files']} files, {out['bytes'] / 1e9:.2f} GB in {out['seconds']} s via {route}"
        + (f" ({len(first)} downloaded, the rest copies of identical files)" if route == "api" and copies else ""))
    return out


def main(argv=None):
    """python -m kit.hfpull PREFIX DEST [--bucket B] [--mount M] [--exclude PAT ...]: one pull, its record as JSON
    on the last line. For Jobs whose own Python lacks huggingface_hub: run this under one that has it."""
    import argparse
    import json
    import sys
    if sys.stdout.isatty():              # the Scrolls look (AGENTS.md rule 17)
        from kit import termstyle
        termstyle.script()
    ap = argparse.ArgumentParser(prog="python -m kit.hfpull", description=main.__doc__.split(":")[0])
    ap.add_argument("prefix")
    ap.add_argument("dest")
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--mount", default=None, help="the mounted bucket root, for the fallback route")
    ap.add_argument("--exclude", action="append", default=[])
    a = ap.parse_args(argv)
    try:
        out = pull(a.prefix, a.dest, exclude=a.exclude, bucket=a.bucket, mount=a.mount,
                   say=lambda m: print(m, file=sys.stderr))
    except HfPullError as exc:
        print(f"hfpull: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
