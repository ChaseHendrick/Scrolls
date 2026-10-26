"""Put Fiber Checker on Hugging Face as a free CPU Space, after its owner said yes.

  python3 tools/deploy.py OWNER/NAME [--private] [--yes]

Stages the Space's files in a temporary folder: the page (app.py, fibercat.py, README.md, requirements.txt, NOTICE,
LICENSE, connect.html), the checker itself from scripts/fibercheck/ (fibercheck.py, fcmodel.py), the free judge's
weights (weights/fibercheck-local.pt, refused unless its SHA-256 is the tested one) and the game's pictures
(assets/game.npz, from tools/build_game.py). Lists them with their SHA-256, asks y/N unless --yes, then creates the
Space if needed and uploads them in one commit. Needs huggingface_hub and a logged-in token with write access.
"""
import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TOOL = HERE.parent.parent / "scripts" / "fibercheck"
PAGE = ["app.py", "fibercat.py", "README.md", "requirements.txt", "NOTICE", "LICENSE", "connect.html"]
WEIGHTS_SHA256 = "e43c25b322816f9f821a154a472eb51e0af86baa194ca5d65094083e8c4b35d7"


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def stage(dst):
    dst.mkdir(parents=True)
    for f in PAGE:
        shutil.copy2(HERE / f, dst / f)
    for f in ("fibercheck.py", "fcmodel.py"):
        shutil.copy2(TOOL / f, dst / f)
    w = HERE / "weights" / "fibercheck-local.pt"
    if not w.is_file() or sha256(w) != WEIGHTS_SHA256:
        sys.exit(f"{w} is missing or not the tested weights (SHA-256 {WEIGHTS_SHA256[:16]}...)")
    (dst / "weights").mkdir()
    shutil.copy2(w, dst / "weights" / w.name)
    g = HERE / "assets" / "game.npz"
    if g.is_file():
        (dst / "assets").mkdir()
        shutil.copy2(g, dst / "assets" / g.name)
    else:
        print("note: assets/game.npz is missing (tools/build_game.py); the game tab will say so")
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
    with tempfile.TemporaryDirectory(prefix="fiber-checker-") as tmp:
        st = stage(Path(tmp) / "space")
        print(f"Fiber Checker as {user}, to {a.space}:")
        for p in sorted(q for q in st.rglob("*") if q.is_file()):
            print(f"  {sha256(p)}  {p.stat().st_size:9d}  {p.relative_to(st).as_posix()}")
        if not a.yes and input("Upload? [y/N] ").strip().lower() != "y":
            sys.exit("nothing sent")
        api.create_repo(a.space, repo_type="space", space_sdk="gradio", private=a.private, exist_ok=True)
        info = api.upload_folder(repo_id=a.space, repo_type="space", folder_path=str(st),
                                 commit_message="Fiber Checker: page, checker, free judge weights and game pictures")
        print(f"uploaded: {info}")
        print(f"https://huggingface.co/spaces/{a.space}")


if __name__ == "__main__":
    main()
