#!/usr/bin/env python3
"""Optional, local Harness2 workflow comparison on generated provenance fixtures. No models or scroll data.

demo runs Harness2's real recursion with a deterministic local proposer; compare evaluates
the exact supplied recipe. Both need a separate Harness2 checkout at the pinned commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys

PIN = "1cfe254e8d25b15f37048c3730134686abe60335"
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MAX_FILES = 6000
MAX_BYTES = 32 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
WALL_SECONDS = 300
LIMITS = {"wall_seconds": WALL_SECONDS, "files": MAX_FILES, "bytes": MAX_BYTES,
          "worker_seconds": 30, "worker_output_bytes": 16384,
          "executions": 48, "proposer_calls": 64}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_text(value):
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(text):
    def invalid(value):
        raise ValueError(f"non-finite JSON value: {value}")
    return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=invalid)


def recipe(text):
    """The strict candidate recipe: exactly schema 1 and a Boolean recheck_files."""
    if len(text.encode("utf-8")) > 1024:
        raise ValueError("recipe exceeds 1024 bytes")
    value = strict_json(text)
    if (not isinstance(value, dict) or set(value) != {"schema", "recheck_files"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or type(value["recheck_files"]) is not bool):
        raise ValueError("recipe must contain exactly schema: 1 and recheck_files: boolean")
    return value


def safe_path(value):
    """Refuse traversal and symlinks, including links in existing parents."""
    path = Path(value).expanduser()
    if ".." in path.parts:
        raise ValueError(f"parent traversal is not allowed: {path}")
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"symlink is not allowed: {part}")
    return path


def read_small(path, cap=MAX_FILE):
    path = safe_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
        raise ValueError(f"expected a regular file of at most {cap} bytes: {path}")
    return path.read_bytes()


def snapshot(root):
    """Bounded content inventory; also rejects special files and linked directories."""
    result = {}
    total = 0
    root = safe_path(root)
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            safe_path(Path(base) / name)
        for name in names:
            path = Path(base) / name
            raw = read_small(path)
            total += len(raw)
            result[path.relative_to(root).as_posix()] = digest(raw)
            if len(result) > MAX_FILES or total > MAX_BYTES:
                raise ValueError("run exceeds the file-count or total-output limit")
    return result


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, timeout=10).stdout


def upstream_identity(path):
    """Hashes of the pinned upstream package; refuses any other revision or local change."""
    path = safe_path(path)
    try:
        head = git(path, "rev-parse", "HEAD").decode().strip() if path.is_dir() else ""
    except (OSError, subprocess.SubprocessError):
        head = ""
    if head != PIN:
        raise ValueError(f"--upstream must be a checkout at {PIN}")
    if (path / ".env").exists() or (path / ".env").is_symlink():
        raise ValueError("upstream .env is not allowed (Harness2 imports it automatically)")
    listing = git(path, "ls-tree", "-r", "-z", PIN, "--", "harness2", "pyproject.toml")
    expected = {}
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        meta, name = entry.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("unsupported upstream file type")
        expected[name.decode()] = sha.decode()
    actual = snapshot(path / "harness2")
    if {f"harness2/{name}" for name in actual} != set(expected) - {"pyproject.toml"}:
        raise ValueError("upstream package has missing or extra files (including bytecode)")
    hashes = {}
    for name, sha in expected.items():
        raw = read_small(path / name)
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != sha:
            raise ValueError(f"upstream source differs from pin: {name}")
        hashes[name] = digest(raw)
    # engine.py never puts the checkout on sys.path; this keeps a stray root module out anyway.
    for child in path.iterdir():
        if child.name.endswith((".py", ".pyc", ".so", ".pyd")):
            raise ValueError(f"upstream root import shadow is not allowed: {child.name}")
    return {"commit": PIN, "files_sha256": hashes}


def source_identity():
    """The Scrolls code a run depends on: kit and this folder, by content, plus the commit."""
    paths = sorted((ROOT / "kit").rglob("*.py")) + sorted(HERE.glob("*.py"))
    try:
        commit = git(ROOT, "rev-parse", "HEAD").decode().strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {"commit": commit,
            "files_sha256": {p.relative_to(ROOT).as_posix(): digest(read_small(p))
                             for p in paths if "__pycache__" not in p.parts}}


def prepare_output(path, identity):
    """Create a run directory, or accept an existing one only if it is this run, finished and intact."""
    path = safe_path(path)
    if path == ROOT or path in ROOT.parents or path == HERE:
        raise ValueError("output cannot replace the repository or an ancestor")
    if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT / "work"):
        raise ValueError("outputs inside this repository must be under work/")
    if path.exists():
        if not path.is_dir():
            raise ValueError("output is not a directory")
        if any(path.iterdir()):
            if not (path / "manifest.json").is_file():
                raise ValueError("output directory is not empty and holds no run; use a fresh --out")
            manifest = strict_json(read_small(path / "manifest.json").decode())
            if manifest != identity:
                raise ValueError("existing output provenance is incompatible; use a fresh --out")
            if not (path / "receipt.json").is_file():
                raise ValueError("an earlier run in this output did not finish; use a fresh --out")
            receipt = strict_json(read_small(path / "receipt.json").decode())
            current = snapshot(path)
            current.pop("receipt.json", None)
            if current != receipt:
                raise ValueError("existing output artifacts changed or are incomplete; use a fresh --out")
            # An interrupted resume must not leave a receipt that still looks valid.
            (path / "receipt.json").unlink()
            return True
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json_text(identity), encoding="utf-8")
    return False


def parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action", required=True)
    for name, text in (("demo", "exercise Harness2's real recursion with deterministic local proposals"),
                       ("compare", "evaluate the exact supplied candidate recipe against the baseline")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--upstream", required=True, type=Path,
                         help=f"separate Harness2 checkout at {PIN[:12]}")
        cmd.add_argument("--out", required=True, type=Path, help="new or resumable run directory")
        cmd.add_argument("--k", type=int, choices=(1, 2), default=1, help="Harness2 recursion budget")
        if name == "compare":
            cmd.add_argument("--candidate", required=True, type=Path,
                             help="strict recipe JSON: {\"schema\": 1, \"recheck_files\": true}")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if os.name != "posix" or not (3, 12) <= sys.version_info[:2] < (3, 14):
            raise ValueError("this optional integration requires POSIX and Python >=3.12,<3.14")
        upstream = safe_path(args.upstream)
        out = safe_path(args.out)
        if out == upstream or out.is_relative_to(upstream) or upstream.is_relative_to(out):
            raise ValueError("output and upstream checkout must not overlap")
        candidate = (recipe(read_small(args.candidate, 1024).decode())
                     if args.action == "compare" else None)
        identity = {"schema": 1, "kind": "synthetic-provenance-workflow",
                    "action": args.action, "k": args.k, "candidate": candidate,
                    "output_root": str(out), "fixture_version": 1,
                    "python": list(sys.version_info[:2]),
                    "upstream": upstream_identity(upstream), "scrolls": source_identity(),
                    "limits": LIMITS}
        resumed = prepare_output(out, identity)
        # A separate isolated interpreter owns the optional imports, the fixed worker and the wall limit.
        env = {"PATH": os.defpath, "LANG": "C.UTF-8"}
        log = out / "engine.log"
        with log.open("wb") as stream:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-S", "-B", str(HERE / "engine.py"), str(upstream), str(out)],
                env=env, cwd=out, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=True)
            try:
                status = proc.wait(timeout=WALL_SECONDS)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise ValueError(f"local integration exceeded its {WALL_SECONDS} second wall limit") from None
        if status:
            raise ValueError(f"integration failed (exit {status}); see {log}")
        result = strict_json(read_small(out / "comparison.json").decode())
        current = snapshot(out)
        current.pop("receipt.json", None)
        (out / "receipt.json").write_text(json_text(current), encoding="utf-8")
        print(json_text({"out": str(out), "resumed": resumed, "status": result["status"],
                         "comparison": str(out / "comparison.json"),
                         "new_executions": result["new_executions"],
                         "new_proposer_calls": result["new_proposer_calls"]}), end="")
        return 0 if result["status"] == "ok" else 1
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"harness2: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
