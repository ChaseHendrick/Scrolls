"""Put Fiber Checker on Hugging Face as a free CPU Space, after its owner said yes.

  python3 tools/deploy.py OWNER/NAME [--private] [--yes]

Stages the Space's files in a temporary folder: the page (app.py, fibercat.py, README.md, requirements.txt, NOTICE,
LICENSE, connect.html, connect.json, CONNECT.md, onescroll.html, guide/index.html), the checker itself from
scripts/fibercheck/ (fibercheck.py, fcmodel.py), the free judge's weights (weights/fibercheck-local.pt, refused unless
its SHA-256 is the tested one) and every file in assets/: the game's pictures (game.npz, from tools/build_game.py) and
the welcome page's and guides' pictures (tools/build_media.py). Lists them with their SHA-256, asks y/N unless --yes,
then creates the Space if needed and uploads them in one commit. Needs huggingface_hub and a logged-in token with
write access.
"""
import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TOOL = HERE.parent.parent / "scripts" / "fibercheck"
PAGE = ["app.py", "fibercat.py", "README.md", "requirements.txt", "NOTICE", "LICENSE", "connect.html",
        "connect.json", "CONNECT.md", "onescroll.html", "guide/index.html"]
MAX_PICTURE = 4_000_000             # docs/media/README.md: every picture at most 4 MB
WEIGHTS_SHA256 = "e43c25b322816f9f821a154a472eb51e0af86baa194ca5d65094083e8c4b35d7"


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def stage(dst):
    dst.mkdir(parents=True)
    for f in PAGE:
        (dst / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / f, dst / f)
    for f in ("fibercheck.py", "fcmodel.py"):
        shutil.copy2(TOOL / f, dst / f)
    w = HERE / "weights" / "fibercheck-local.pt"
    if not w.is_file() or sha256(w) != WEIGHTS_SHA256:
        sys.exit(f"{w} is missing or not the tested weights (SHA-256 {WEIGHTS_SHA256[:16]}...)")
    (dst / "weights").mkdir()
    shutil.copy2(w, dst / "weights" / w.name)
    assets = sorted(f for f in (HERE / "assets").glob("*") if f.is_file()) if (HERE / "assets").is_dir() else []
    if not any(f.name == "game.npz" for f in assets):
        print("note: assets/game.npz is missing (tools/build_game.py); the game tab will say so")
    if not any(f.name == "hero.webp" for f in assets):
        print("note: the welcome page's pictures are missing (tools/build_media.py); it shows without them")
    for f in assets:
        if f.suffix in (".png", ".webp", ".gif", ".jpg") and f.stat().st_size > MAX_PICTURE:
            sys.exit(f"{f} is over 4 MB")
        (dst / "assets").mkdir(exist_ok=True)
        shutil.copy2(f, dst / "assets" / f.name)
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
                                 commit_message="Fiber Checker: page, checker, free judge weights and pictures")
        print(f"uploaded: {info}")
        print(f"https://huggingface.co/spaces/{a.space}")


if __name__ == "__main__":
    main()
