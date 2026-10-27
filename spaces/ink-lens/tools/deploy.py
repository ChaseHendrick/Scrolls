"""Put Ink Lens on Hugging Face as a ZeroGPU Space, from your own computer, after you say y.

  python3 tools/deploy.py files                       list the Space's files with their SHA-256 (no network)
  python3 tools/deploy.py stage DEST                  copy them into DEST, laid out as the Space runs them
  python3 tools/deploy.py OWNER/NAME [--private]      check, show, ask y/N, then upload

In order, stopping at the first failure:
  1. checks this computer is logged in to Hugging Face (`hf auth login`; it never logs in for you);
  2. stages the Space's files (SPACE_FILES and the kit modules) in a temporary folder and lists them with SHA-256;
  3. when the Space exists, says which files differ from the live ones;
  4. asks y/N. Anything but y stops here and nothing is sent;
  5. creates the Space if needed (Gradio, public unless --private), uploads the files, and asks for ZeroGPU hardware
     (zero-a10g) if the Space does not have it.

A new Space needs Chase's yes first (AGENTS.md rule 8). A free account may host two ZeroGPU Spaces; replacing an
existing Space's app (OWNER/NAME of that Space) uploads these files over it. Needs huggingface_hub.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPACE = HERE.parent
ROOT = SPACE.parents[1]
HARDWARE = "zero-a10g"
SPACE_FILES = ("README.md", "app.py", "engine.py", "gate.py", "inklens.py", "vc3dout.py", "volio.py", "bridge.py",
               "zoo.py", "runners.py", "compare.py", "samples.json", "requirements.txt", "LICENSE", "NOTICE",
               "connect.json", "connect.html", "CONNECT.md", "onescroll.html")
KIT_MODULES = ("__init__", "auc", "fetch", "layers", "s3retry", "verify")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def space_files(gallery=None):
    """{path in the Space: source file}. gallery (or INKLENS_GALLERY): the folder tools/gallery_job.py assemble wrote,
    published as the Space's gallery/ (maps are model output on public data; they never go into git)."""
    files = {n: SPACE / n for n in SPACE_FILES}
    files.update({f"kit/{m}.py": ROOT / "kit" / f"{m}.py" for m in KIT_MODULES})
    gallery = gallery or os.environ.get("INKLENS_GALLERY")
    if gallery:
        g = Path(gallery)
        if not (g / "index.json").is_file():
            raise SystemExit(f"{g} holds no gallery index.json")
        files.update({f"gallery/{p.relative_to(g).as_posix()}": p for p in sorted(g.rglob("*"))
                      if p.is_file() and p.suffix in (".json", ".png")})
    missing = [k for k, v in files.items() if not v.is_file()]
    if missing:
        raise SystemExit(f"missing Space files: {missing}")
    return files


def stage(dest):
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty")
    for target, src in sorted(space_files().items()):
        out = dest / target
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
    return dest


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["files"]:
        print(json.dumps([{"path": k, "sha256": sha256_file(v), "bytes": v.stat().st_size}
                          for k, v in sorted(space_files().items())], indent=1))
        return 0
    if argv[:1] == ["stage"] and len(argv) == 2:
        print(stage(argv[1]))
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("space", help="OWNER/NAME")
    ap.add_argument("--private", action="store_true")
    a = ap.parse_args(argv)
    if a.space.count("/") != 1:
        sys.exit("give the Space as OWNER/NAME")
    from huggingface_hub import HfApi
    from huggingface_hub.utils import RepositoryNotFoundError
    api = HfApi()
    try:
        user = api.whoami()["name"]
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"not logged in to Hugging Face ({type(exc).__name__}). Run: hf auth login")
    sys.path.insert(0, str(SPACE))
    import engine
    with tempfile.TemporaryDirectory(prefix="ink-lens-") as tmp:
        st = stage(Path(tmp) / "space")
        local = {p.relative_to(st).as_posix(): sha256_file(p) for p in sorted(st.rglob("*")) if p.is_file()}
        print(f"Ink Lens {engine.VERSION}, as {user}, to {a.space}:")
        for rel, sha in local.items():
            print(f"  {sha}  {rel}")
        try:
            info = api.space_info(a.space, files_metadata=True)
            exists = True
        except RepositoryNotFoundError:
            info, exists = None, False
        if exists:
            live = {s.rfilename: (s.lfs.sha256 if s.lfs else None) for s in info.siblings or []}
            changed = []
            for rel, sha in local.items():
                if rel not in live:
                    changed.append(f"new      {rel}")
                    continue
                got = live[rel]
                if got is None:
                    got = sha256_file(api.hf_hub_download(a.space, rel, repo_type="space"))
                if got != sha:
                    changed.append(f"changed  {rel}")
            extra = sorted(set(live) - set(local) - {".gitattributes"})
            print("Differences from the live Space:" if changed else "The live Space already has these files.")
            for line in changed:
                print("  " + line)
            if extra:
                print("Files on the live Space that Ink Lens does not have (left as they are; delete them on the Hub "
                      "if this replaces another app): " + ", ".join(extra))
        else:
            print(f"{a.space} does not exist yet; it will be created {'private' if a.private else 'public'}.")
        if input("Send these files? Type y to send: ").strip().lower() != "y":
            print("nothing sent")
            return 0
        if not exists:
            api.create_repo(a.space, repo_type="space", space_sdk="gradio", private=a.private,
                            space_hardware=HARDWARE)
        api.upload_folder(folder_path=str(st), repo_id=a.space, repo_type="space",
                          commit_message=f"Ink Lens {engine.VERSION}")
    rt = api.get_space_runtime(a.space)
    if (rt.requested_hardware or rt.hardware) != HARDWARE:
        print(f"asking for {HARDWARE} (was {rt.requested_hardware or rt.hardware})")
        api.request_space_hardware(a.space, HARDWARE)
    print(f"done: https://huggingface.co/spaces/{a.space}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
