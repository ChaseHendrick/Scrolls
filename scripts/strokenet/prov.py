"""Provenance of StrokeNet's preregistered run: the files it runs and their SHA-256 at a commit.

Standard library only, so the cloud runner's launcher (scripts/strokenet/modal_strokenet.py) can
check the checkout before anything is uploaded, without numpy or torch on the launching computer.
"""
import hashlib
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PREREG = "docs/prereg/2026-10-14-strokenet.md"
CODE_FILES = tuple(f"scripts/strokenet/{n}.py" for n in ("data", "nulls", "train", "metrics", "baselines", "pipeline",
                                                          "evaluate", "prov", "modal_strokenet")) + (
    "kit/strokenet.py", PREREG, "docs/strokenet-data-manifest.json")


def sha256_bytes(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def code_provenance(root=REPO):
    """Git commit, whether any file of CODE_FILES differs from it, and each file's SHA-256."""
    out = {"files": {f: sha256_bytes(Path(root) / f) for f in CODE_FILES if (Path(root) / f).exists()}}
    try:
        out["commit"] = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                                       text=True, check=True).stdout.strip()
        st = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", *CODE_FILES], capture_output=True,
                            text=True, check=True).stdout.strip()
        out["dirty"] = bool(st)
    except (OSError, subprocess.CalledProcessError):
        out["commit"], out["dirty"] = None, None
    out["missing"] = [f for f in CODE_FILES if f not in out["files"]]
    return out
