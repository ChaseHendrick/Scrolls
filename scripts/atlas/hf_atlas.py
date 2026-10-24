"""Build or refresh the public Segment Atlas dataset (SharpMeow/vesuvius-segment-atlas) on Hugging Face.

  job       what runs inside the Hugging Face Job: download the published atlas (its lens/ previews included),
            measure only new or changed meshes with `python -m kit atlas build --previous ... --lens`, and upload the
            folder back. Needs HF_TOKEN with write access to the dataset.
  run       start that Job once now, on cpu-upgrade (8 vCPU, 32 GB, 0.03 USD an hour on 23 Oct 2026), and print its id
  schedule  create (or replace) the daily scheduled Job
  status    the scheduled Job and the last runs

The Job clones this repository's public `main` (or --ref) and runs the kit from it, so a fix reaches the next daily
run once it is merged. Everything it reads is public open data; it writes only the public dataset.

  python scripts/atlas/hf_atlas.py run --ref main --timeout 3h
  python scripts/atlas/hf_atlas.py schedule --cron "17 6 * * *"
"""

import argparse
import json
import os
import shlex
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

DATASET = "SharpMeow/vesuvius-segment-atlas"
REPO = "https://github.com/ChaseHendrick/Scrolls"
IMAGE = "python:3.12"
FLAVOR = "cpu-upgrade"
CRON = "17 6 * * *"        # daily, 06:17 UTC
NAME = "segment-atlas"
PIP = "numpy tifffile imagecodecs scipy huggingface_hub"


def job(out="/tmp/atlas", workers=6, repo=DATASET):
    """Inside the Job: pull the published atlas, measure what changed, push the folder back."""
    from huggingface_hub import HfApi, snapshot_download
    from kit import atlas
    api = HfApi()
    api.create_repo(repo, repo_type="dataset", private=False, exist_ok=True)
    out = Path(out)
    try:
        snapshot_download(repo, repo_type="dataset", local_dir=out)
    except Exception as exc:  # a first build has nothing to download
        print(f"no published atlas yet ({type(exc).__name__}); building from scratch", flush=True)
    prev = out / "atlas.jsonl"
    t0 = time.time()
    summary = atlas.build(out, previous=prev if prev.is_file() else None, workers=workers, lens=True,
                          progress=lambda m: print(m, flush=True), workdir="/tmp")
    keep = {r["lens"] for r in atlas.read_atlas(out / "atlas.jsonl") if r.get("lens")}
    stale = [p for p in (out / "lens").glob("*.slg.gz") if p.name not in keep] if (out / "lens").is_dir() else []
    for p in stale:
        p.unlink()
    msg = (f"Refresh: {summary['meshes']} meshes of {summary['segments']} segments, {summary['errors']} not "
           f"measured (kit {summary['kit_commit']}, {round(time.time() - t0)} s)")
    api.upload_folder(folder_path=str(out), repo_id=repo, repo_type="dataset", commit_message=msg,
                      ignore_patterns=[".cache/**"], delete_patterns=["lens/*.slg.gz"])
    print(msg, flush=True)
    return 0


def command(ref, workers):
    return ["bash", "-c", " && ".join([
        f"pip install -q {PIP}",
        f"git clone -q --depth 1 -b {shlex.quote(ref)} {REPO} /w",
        "cd /w",
        f"python scripts/atlas/hf_atlas.py job --workers {int(workers)}"])]


def main(argv=None):
    if sys.stdout.isatty():              # the Scrolls look (AGENTS.md rule 17)
        from kit import termstyle
        termstyle.script()
    p = argparse.ArgumentParser(prog="python scripts/atlas/hf_atlas.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("job", help="run inside the Hugging Face Job")
    a.add_argument("--out", default="/tmp/atlas")
    a.add_argument("--workers", type=int, default=6)
    for name in ("run", "schedule"):
        a = sub.add_parser(name)
        a.add_argument("--ref", default="main", help="branch or tag of this repository the Job runs")
        a.add_argument("--workers", type=int, default=6)
        a.add_argument("--timeout", default="3h")
        a.add_argument("--flavor", default=FLAVOR)
        if name == "schedule":
            a.add_argument("--cron", default=CRON)
    sub.add_parser("status")
    args = p.parse_args(argv)
    if args.action == "job":
        return job(args.out, args.workers)
    from huggingface_hub import HfApi
    api = HfApi()
    token = os.environ.get("HF_TOKEN")
    secrets = {"HF_TOKEN": token} if token else None
    if args.action == "run":
        j = api.run_job(image=IMAGE, command=command(args.ref, args.workers), flavor=args.flavor,
                        timeout=args.timeout, secrets=secrets, labels={"tool": NAME})
        print(json.dumps({"job": j.id, "url": getattr(j, "url", None), "flavor": args.flavor, "ref": args.ref}))
        return 0
    if args.action == "schedule":
        for s in api.list_scheduled_jobs():
            if (getattr(s, "job_spec", None) and NAME in json.dumps(getattr(s.job_spec, "labels", {}) or {})):
                api.delete_scheduled_job(scheduled_job_id=s.id)
                print(f"replaced scheduled job {s.id}")
        s = api.create_scheduled_job(image=IMAGE, command=command(args.ref, args.workers), schedule=args.cron,
                                     concurrency=False, flavor=args.flavor, timeout=args.timeout, secrets=secrets,
                                     labels={"tool": NAME})
        print(json.dumps({"scheduled_job": s.id, "cron": args.cron, "ref": args.ref}))
        return 0
    for s in api.list_scheduled_jobs():
        print(s)
    for j in list(api.list_jobs())[:5]:
        print(j.id, getattr(j, "status", None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
