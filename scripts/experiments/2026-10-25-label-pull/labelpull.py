"""Time one public label pull from scrollprize/datasets both ways: every file through download_bucket_files
(before) against kit.hfpull, which downloads each distinct file once and copies the rest (after), then check the two
folders are identical. Public data, no token needed.

  python scripts/experiments/2026-10-25-label-pull/labelpull.py PREFIX OUT
"""
import argparse
import filecmp
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from kit import hfpull  # noqa: E402

BUCKET = "scrollprize/datasets"


def before(api, prefix, out):
    """Every file of the store in one download_bucket_files call: the plain way, with no deduplication."""
    todo = hfpull.plan_api(api, BUCKET, prefix, out)
    for _, q in todo:
        q.parent.mkdir(parents=True, exist_ok=True)
    api.download_bucket_files(BUCKET, [(f, str(q)) for f, q in todo], raise_on_missing_files=True)
    return len(todo)


def same(a, b):
    d = filecmp.dircmp(a, b)
    return not (d.left_only or d.right_only or d.diff_files or d.funny_files) and all(
        same(Path(a) / s, Path(b) / s) for s in d.common_dirs)


def main():
    if sys.stdout.isatty():              # the Scrolls look (AGENTS.md rule 17)
        from kit import termstyle
        termstyle.script()
    from huggingface_hub import HfApi
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("out")
    a = ap.parse_args()
    api, out = HfApi(token=False), Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    t = time.monotonic()
    n = before(api, a.prefix, out / "before")
    tb = time.monotonic() - t
    got = hfpull.pull(a.prefix, out / "after", bucket=BUCKET, mount=None, api=api, say=lambda m: None)
    print(json.dumps({"store": a.prefix, "files": n, "before_s": round(tb, 1), "after_s": got["seconds"],
                      "downloaded": got["downloaded"], "identical": same(out / "before", out / "after")}))


if __name__ == "__main__":
    main()
