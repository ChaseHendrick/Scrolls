"""Upload the index tables, card and card pictures to SharpMeow/first-letters-ink-atlas, after its owner said yes.

  python3 spaces/ink-atlas/dataset/publish.py STAGE [--repo OWNER/NAME] [--yes]

STAGE holds the files to add, laid out as in the dataset: README.md (this folder's card), provenance.json (this
folder's), metadata.jsonl, surfaces/metadata.jsonl, index/*.csv and assets/*.{jpg,png} (from build_index.py and
card_visuals.py), and SHA256SUMS, written last over the dataset as it will be with
`python -m kit.datacard sums SharpMeow/first-letters-ink-atlas --overlay STAGE --write` and checked with
`python -m kit.datacard check ... --overlay STAGE` (the scroll dataset card standard, docs/standards/dataset-card.md). The script
lists them with their SHA-256 and size, refuses any path that would replace an existing file other than README.md,
asks y/N unless --yes, and uploads them in one commit. It never deletes or moves a file. Needs huggingface_hub and a
token with write access.
"""
import argparse
import hashlib
import sys
from pathlib import Path

REPO = "SharpMeow/first-letters-ink-atlas"
ALLOWED = ("README.md", "provenance.json", "SHA256SUMS", "metadata.jsonl", "surfaces/metadata.jsonl", "index/",
           "assets/")
REPLACEABLE = {"README.md", "provenance.json", "SHA256SUMS", "metadata.jsonl", "surfaces/metadata.jsonl",
               "index/surfaces.csv", "index/maps.csv", "assets/hero.jpg", "assets/anatomy.png"}


def plan(stage, existing):
    """The upload list: (path, sha256, bytes). Exits on a path outside ALLOWED or one that would overwrite a
    published map, record or picture."""
    out = []
    for p in sorted(Path(stage).rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(stage).as_posix()
        if not rel.startswith(ALLOWED) or (rel.startswith("surfaces/") and rel != "surfaces/metadata.jsonl"):
            sys.exit(f"refused: {rel} is outside the index, card and card pictures")
        if rel in existing and rel not in REPLACEABLE:
            sys.exit(f"refused: {rel} already exists in the dataset and is not one of the files this script owns")
        out.append((rel, hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stage")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--yes", action="store_true", help="upload without asking (the owner already said yes)")
    ap.add_argument("--message", default="Add Dataset Viewer index tables and a new card")
    a = ap.parse_args(argv)
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi()
    existing = set(api.list_repo_files(a.repo, repo_type="dataset"))
    files = plan(a.stage, existing)
    for rel, sha, n in files:
        print(f"{'replace' if rel in existing else 'add':8} {rel}  {n:>10,} B  {sha[:16]}")
    if not a.yes and input(f"Upload {len(files)} files to {a.repo}? [y/N] ").strip().lower() != "y":
        sys.exit("not uploaded")
    ops = [CommitOperationAdd(path_in_repo=rel, path_or_fileobj=str(Path(a.stage) / rel)) for rel, _, _ in files]
    info = api.create_commit(a.repo, ops, commit_message=a.message, repo_type="dataset")
    print(info.commit_url)


if __name__ == "__main__":
    main()
