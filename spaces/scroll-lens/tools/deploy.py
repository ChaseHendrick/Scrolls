"""Put Scroll Lens on Hugging Face as a ZeroGPU Space, from your own computer, after you say y.

  python3 tools/deploy.py OWNER/NAME [--private]

In order, stopping at the first failure:
  1. checks this computer is logged in to Hugging Face (`hf auth login`; it never logs in for you);
  2. stages the Space's files (lens.SPACE_FILES) in a temporary folder and lists them with their SHA-256;
  3. when the Space exists, says which files differ from the live ones;
  4. asks y/N. Anything but y stops here and nothing is sent;
  5. creates the Space if needed (Gradio, public unless --private), uploads the files, and asks for ZeroGPU
     hardware (zero-a10g) if the Space does not have it. The gallery/ folder on the Space is left alone:
     tools/build_gallery.py builds and uploads it.

Safe to run twice: with nothing changed it uploads nothing and only checks the hardware. A public Space shows its
owner's name, and each commit shows its uploader's. Needs huggingface_hub (python3 -m pip install huggingface_hub).
To delete the Space: its Settings page, "Delete this Space".
"""

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import lens  # noqa: E402

HARDWARE = "zero-a10g"


def main(argv=None):
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
    with tempfile.TemporaryDirectory(prefix="scroll-lens-") as tmp:
        stage = lens.stage(Path(tmp) / "space")
        files = sorted(p for p in stage.rglob("*") if p.is_file())
        print(f"Scroll Lens {lens.VERSION}, as {user}, to {a.space}:")
        local = {}
        for p in files:
            rel = p.relative_to(stage).as_posix()
            local[rel] = lens.sha256_file(p)
            print(f"  {local[rel]}  {p.stat().st_size:9d}  {rel}")
        exists = True
        try:
            info = api.space_info(a.space, files_metadata=True)
        except RepositoryNotFoundError:
            exists, info = False, None
        if exists:
            live = {}
            for s in info.siblings or []:
                if s.rfilename in local:
                    live[s.rfilename] = s.lfs.sha256 if s.lfs else None
            changed = []
            for rel in local:
                if rel not in live:
                    changed.append(f"new      {rel}")
                    continue
                sha = live[rel]
                if sha is None:          # small files are stored in git: compare their bytes
                    data = Path(api.hf_hub_download(a.space, rel, repo_type="space")).read_bytes()
                    sha = hashlib.sha256(data).hexdigest()
                if sha != local[rel]:
                    changed.append(f"changed  {rel}")
            print("Differences from the live Space:" if changed else "The live Space already has these files.")
            for line in changed:
                print("  " + line)
        else:
            print(f"{a.space} does not exist yet; it will be created {'private' if a.private else 'public'}.")
        if input("Send these files? Type y to send: ").strip().lower() != "y":
            print("nothing sent")
            return 0
        if not exists:
            api.create_repo(a.space, repo_type="space", space_sdk="gradio", private=a.private,
                            space_hardware=HARDWARE)
        api.upload_folder(folder_path=str(stage), repo_id=a.space, repo_type="space",
                          commit_message=f"Scroll Lens {lens.VERSION}")
    rt = api.get_space_runtime(a.space)
    if (rt.requested_hardware or rt.hardware) != HARDWARE:
        print(f"asking for {HARDWARE} (was {rt.requested_hardware or rt.hardware})")
        api.request_space_hardware(a.space, HARDWARE)
    print(f"done: https://huggingface.co/spaces/{a.space}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
