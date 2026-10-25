"""Provenance record for one run: who ran what, when, on which machine, from which inputs.

Writes a JSON record and a single SHA-256 digest of it. The digest can be published or
committed on its own as a timestamped commitment: it reveals nothing about the record, and
anyone later shown the record can recompute the digest and check it matches. The scripts
write one for every run, null or not, so publishing a digest never hints at a result.

Inputs (zarr stores, label stores, any directory) are fingerprinted by hashing every file
locally: a manifest of (relative path, size, SHA-256) and a digest over that manifest.
Symbolic links are followed, directories included, with a guard against links back to a
directory being walked; each link and its target are listed next to the digest. A directory
with no symlinked subdirectory (and nothing unreadable in it) hashes exactly as it did before
links were followed, so older records still recheck.

Each code entry names the commit, whether tracked files differ from it (`uncommitted_changes`,
unchanged in meaning) and, since 16 October 2026, how many untracked files git does not ignore
(`untracked_files`); both are None when `git status` cannot be read.
Only regular files are hashed; a device, FIFO or socket is refused, so a link to /dev/zero
cannot hang a run. The digest is computed from the record itself: a match shows the record is
unchanged since its digest was made, not who made it. Standard library only.
"""

import errno
import getpass
import hashlib
import json
import os
import platform
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

CHUNK = 1 << 20
SCHEMA = 1


def _open_regular(path):
    """Open a regular file for reading (following symlinks); refuse a device, FIFO or socket without blocking."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise ValueError(f"{path}: not a regular file (device, FIFO or socket); refused")
    return os.fdopen(fd, "rb"), st.st_size


def sha256_file(path):
    return _hash_regular(path)[1]


def _hash_regular(path):
    """(size, sha256) of a regular file."""
    h = hashlib.sha256()
    f, size = _open_regular(path)
    with f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return size, h.hexdigest()


def _walk(directory, rel, ancestors, entries, links):
    """Add every file under `directory` to entries as (relative path, size, sha256), following links.

    `ancestors` holds (device, inode) of the directories on the path being walked, so a link back to one
    of them is listed as a cycle and not entered. A broken link raises FileNotFoundError; anything that
    is not a regular file or a directory (a FIFO, a socket, a device) raises ValueError.
    """
    st = os.stat(directory)
    here = (st.st_dev, st.st_ino)
    if here in ancestors:
        raise ValueError(f"{directory}: directory loop")
    ancestors = ancestors | {here}
    with os.scandir(directory) as it:
        items = sorted(it, key=lambda e: e.name)
    for item in items:
        name = f"{rel}/{item.name}" if rel else item.name
        full = Path(item.path)
        if item.is_symlink():
            target = os.readlink(item.path)
            try:
                st = os.stat(item.path)
            except FileNotFoundError:
                raise FileNotFoundError(errno.ENOENT, f"broken symbolic link to {target!r}", str(full)) from None
            if stat.S_ISDIR(st.st_mode):
                cycle = (st.st_dev, st.st_ino) in ancestors
                entry = {"path": name, "target": target, "kind": "directory"}
                if cycle:
                    entry["cycle"] = True
                links.append(entry)
                if not cycle:
                    _walk(full, name, ancestors, entries, links)
            elif stat.S_ISREG(st.st_mode):
                links.append({"path": name, "target": target, "kind": "file"})
                entries.append((name, st.st_size, sha256_file(full)))
            else:
                raise ValueError(f"{full}: link to something that is not a regular file or directory")
        elif item.is_dir(follow_symlinks=False):
            _walk(full, name, ancestors, entries, links)
        elif item.is_file(follow_symlinks=False):
            entries.append((name, item.stat(follow_symlinks=False).st_size, sha256_file(full)))
        else:
            raise ValueError(f"{full}: not a regular file or directory")


def fingerprint(path):
    """SHA-256 of a file, or of a directory's sorted (relative path, size, sha256) manifest.

    Symbolic links inside a directory are followed (files and directories alike) and listed under "links"
    with their targets; a link back to a directory already being walked is listed with "cycle" and not
    entered. When `path` itself is a link, its target is kept as "link". The sha256 covers file names,
    sizes and contents, not link targets, so it names the data, wherever the links point.
    """
    path = Path(path)
    link = os.readlink(path) if path.is_symlink() else None
    if path.is_file():
        size, digest = _hash_regular(path)
        out = {"path": str(path), "kind": "file", "bytes": size, "sha256": digest}
    elif path.is_dir():
        entries, links = [], []
        _walk(path, "", frozenset(), entries, links)
        entries.sort()
        manifest = "\n".join(f"{rel}\t{size}\t{digest}" for rel, size, digest in entries)
        out = {"path": str(path), "kind": "directory", "files": len(entries),
               "bytes": sum(size for _, size, _ in entries),
               "sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest()}
        if links:
            out["links"] = sorted(links, key=lambda item: item["path"])
    elif path.exists():
        raise ValueError(f"{path}: not a regular file or directory (device, FIFO or socket); refused")
    else:
        raise FileNotFoundError(path)
    if link is not None:
        out["link"] = link
    return out


def _git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              check=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def code_state(repo):
    """Commit, branch, whether tracked files differ from that commit, and how many untracked files there are.

    `uncommitted_changes` keeps its old meaning (tracked files only); `untracked_files` counts files git does
    not track and does not ignore. Both are None when `git status` fails, since the state is then unknown.
    A repo with no readable commit gives only {"repo", "commit": None}.
    """
    commit = _git(repo, "rev-parse", "HEAD")
    if commit is None:
        return {"repo": str(repo), "commit": None}
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if status is None:
        uncommitted = untracked = None
    else:
        lines = [line for line in status.splitlines() if line]
        untracked = sum(1 for line in lines if line.startswith("??"))
        uncommitted = len(lines) > untracked
    return {"repo": str(repo), "commit": commit, "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            "uncommitted_changes": uncommitted, "untracked_files": untracked}


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


def files_listed(record):
    """How many models, inputs and outputs the record lists."""
    return sum(len(record.get(section) or []) for section in ("models", "inputs", "outputs"))


def _check_shape(record):
    """ValueError when the record is not a provenance record's shape (verify would otherwise crash on it)."""
    if not isinstance(record, dict):
        raise ValueError("malformed record: not a JSON object")
    if not isinstance(record.get("digest"), str):
        raise ValueError("malformed record: no digest")
    for section in ("models", "inputs", "outputs"):
        items = record.get(section, [])
        if not isinstance(items, list):
            raise ValueError(f"malformed record: {section} is not a list")
        for item in items:
            if not (isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("sha256"), str)):
                raise ValueError(f"malformed record: an entry in {section} without a path and sha256")


def verify(record, recheck_files=False):
    """Problems with a record: a digest that does not match, and optionally files that changed.
    ValueError for a record of the wrong shape."""
    _check_shape(record)
    problems = []
    if hashlib.sha256(canonical(record)).hexdigest() != record.get("digest"):
        problems.append("digest does not match the record")
    if recheck_files:
        for section in ("models", "inputs", "outputs"):
            for item in record.get(section, []):
                try:
                    now = fingerprint(item["path"])["sha256"]
                except (OSError, ValueError) as exc:
                    if os.path.lexists(item["path"]):
                        problems.append(f"{section}: {item['path']} cannot be fingerprinted ({exc})")
                    else:
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
