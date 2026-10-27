"""Put Ink Atlas on Hugging Face as a free CPU Space, after its owner said yes.

  python3 tools/deploy.py OWNER/NAME [--private] [--yes]

Stages the page's files in a temporary folder (app.py, atlasdata.py, README.md, requirements.txt, NOTICE, LICENSE,
connect.html, CONNECT.md, connect.json), lists them with their SHA-256, asks y/N unless --yes, then creates the Space
if needed and uploads them in one commit. The Space holds code only: the maps stay in the dataset
SharpMeow/first-letters-ink-atlas and are read at run time. Needs huggingface_hub and a token with write access.
"""
import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PAGE = ["app.py", "atlasdata.py", "README.md", "requirements.txt", "NOTICE", "LICENSE", "connect.html", "CONNECT.md",
        "connect.json"]


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def stage(dst):
    dst.mkdir(parents=True)
    for f in PAGE:
        if not (HERE / f).is_file():
            sys.exit(f"{f} is missing (connect.html and CONNECT.md: python -m kit spaceconnect render spaces/ink-atlas)")
        shutil.copy2(HERE / f, dst / f)
    return dst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("space", help="OWNER/NAME")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--yes", action="store_true", help="upload without asking (the owner already said yes)")
    a = ap.parse_args(argv)
    from huggingface_hub import HfApi
    api = HfApi()
    user = api.whoami()["name"]
    with tempfile.TemporaryDirectory(prefix="ink-atlas-") as tmp:
        st = stage(Path(tmp) / "space")
        print(f"Ink Atlas as {user}, to {a.space}:")
        for p in sorted(q for q in st.rglob("*") if q.is_file()):
            print(f"  {sha256(p)}  {p.stat().st_size:9d}  {p.relative_to(st).as_posix()}")
        if not a.yes and input("Upload? [y/N] ").strip().lower() != "y":
            sys.exit("nothing sent")
        api.create_repo(a.space, repo_type="space", space_sdk="gradio", private=a.private, exist_ok=True)
        info = api.upload_folder(repo_id=a.space, repo_type="space", folder_path=str(st),
                                 commit_message="Ink Atlas: page, API and MCP tools")
        print(f"uploaded: {info}")
        print(f"https://huggingface.co/spaces/{a.space}")


if __name__ == "__main__":
    main()
