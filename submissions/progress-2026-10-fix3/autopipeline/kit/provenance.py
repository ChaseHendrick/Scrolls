"""Provenance record for one run: who ran what, when, on which machine, from which inputs.

Writes a JSON record and a single SHA-256 digest of it. The digest can be published or
committed on its own as a timestamped commitment: it reveals nothing about the record, and
anyone later shown the record can recompute the digest and check it matches. The scripts
write one for every run, null or not, so publishing a digest never hints at a result.

Inputs (zarr stores, label stores, any directory) are fingerprinted by hashing every file
locally: a manifest of (relative path, size, SHA-256) and a digest over that manifest.
Standard library only.
"""

import getpass
import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

CHUNK = 1 << 20
SCHEMA = 1


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def fingerprint(path):
    """SHA-256 of a file, or of a directory's sorted (relative path, size, sha256) manifest."""
    path = Path(path)
    if path.is_file():
        return {"path": str(path), "kind": "file", "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    if not path.is_dir():
        raise FileNotFoundError(path)
    entries = []
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            full = Path(root) / name
            entries.append((full.relative_to(path).as_posix(), full.stat().st_size, sha256_file(full)))
    entries.sort()
    manifest = "\n".join(f"{rel}\t{size}\t{digest}" for rel, size, digest in entries)
    return {"path": str(path), "kind": "directory", "files": len(entries),
            "bytes": sum(size for _, size, _ in entries),
            "sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest()}


def _git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              check=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def code_state(repo):
    """Commit, branch, and whether tracked files differ from that commit."""
    commit = _git(repo, "rev-parse", "HEAD")
    if commit is None:
        return {"repo": str(repo), "commit": None}
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=no")
    return {"repo": str(repo), "commit": commit, "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            "uncommitted_changes": bool(dirty)}


def operator(repo):
    """Who ran it: git's user.name where the code lives, else the login name. No email."""
    return {"name": _git(repo, "config", "user.name") or getpass.getuser(), "login": getpass.getuser()}


def machine():
    info = {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "python": platform.python_version()}
    if platform.system() == "Darwin":
        try:
            info["chip"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                          text=True, timeout=10).stdout.strip()
            info["macos"] = platform.mac_ver()[0]
        except (OSError, subprocess.SubprocessError):
            pass
    return info


def canonical(record):
    """The bytes the digest covers: the record without its digest, keys sorted, no spaces."""
    body = {k: v for k, v in record.items() if k != "digest"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def build(name, repo, started=None, inputs=(), models=(), outputs=(), extra_code=(), note=None, notes=None):
    """Assemble a record. inputs, models and outputs are paths; extra_code are other git repos."""
    record = {
        "schema": SCHEMA,
        "run": name,
        "operator": operator(repo),
        "machine": machine(),
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code": [code_state(repo)] + [code_state(r) for r in extra_code],
        "models": [fingerprint(p) for p in models],
        "inputs": [fingerprint(p) for p in inputs],
        "outputs": [fingerprint(p) for p in outputs],
    }
    if note:
        record["note"] = note
    if notes:
        record["notes"] = notes
    record["digest"] = hashlib.sha256(canonical(record)).hexdigest()
    return record


def verify(record, recheck_files=False):
    """Problems with a record: a digest that does not match, and optionally files that changed."""
    problems = []
    if hashlib.sha256(canonical(record)).hexdigest() != record.get("digest"):
        problems.append("digest does not match the record")
    if recheck_files:
        for section in ("models", "inputs", "outputs"):
            for item in record.get(section, []):
                try:
                    now = fingerprint(item["path"])["sha256"]
                except FileNotFoundError:
                    problems.append(f"{section}: {item['path']} is missing")
                    continue
                if now != item["sha256"]:
                    problems.append(f"{section}: {item['path']} changed")
    return problems


def write(record, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
