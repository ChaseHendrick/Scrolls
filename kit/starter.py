"""Scrolls Starter: a local introduction, setup snapshot and reader command builder.

Standard library only. The generated page is self-contained and opens from a file URL;
it never starts a server, executes browser commands, downloads weights or runs inference.
"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, reader_backends

DATA = Path(__file__).parent / "data"
PACKAGES = {"numpy": "numpy", "Pillow": "PIL", "tifffile": "tifffile", "imagecodecs": "imagecodecs"}
START_HERE = "https://github.com/ChaseHendrick/Scrolls/blob/main/docs/start-here.md"


def _packages():
    # Import, rather than just find_spec: a present package can have a broken native library.
    program = """import importlib, json
result = []
for name, module in json.loads(__import__('sys').argv[1]).items():
    try:
        loaded = importlib.import_module(module)
        result.append(dict(name=name, available=True, version=str(getattr(loaded, '__version__', 'unknown'))))
    except Exception as exc:
        result.append(dict(name=name, available=False, detail=f'{type(exc).__name__}: {exc}'[:400]))
print(json.dumps(result))
"""
    try:
        probe = subprocess.run([sys.executable, "-I", "-c", program, json.dumps(PACKAGES)],
                               capture_output=True, text=True, timeout=15, check=True)
        return json.loads(probe.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return [{"name": name, "available": False, "detail": f"Import check incomplete: {type(exc).__name__}"}
                for name in PACKAGES]


def _weights():
    models = json.loads((DATA / "letter-weights.json").read_text(encoding="utf-8"))["models"]
    override = os.environ.get("KIT_LETTER_WEIGHTS")
    path = Path(override).expanduser() if override else Path.home() / ".cache" / "scrolls-kit" / "letters"
    single = path.is_file() or path.suffix.lower() == ".npz"
    results = []
    for name, model in models.items():
        candidate = path if single else path / model["file"]
        state = "missing"
        try:
            if candidate.is_file():
                if candidate.stat().st_size > 64 * 1024 * 1024:
                    state = "not checked (over 64 MiB)"
                else:
                    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                    state = "verified" if digest == model["sha256"] else "hash mismatch"
        except OSError:
            state = "unreadable"
        results.append({"name": name, "state": state, "license": model["license_id"]})
    return results


def check_setup():
    """Return a real local setup snapshot; no image reads, downloads or inference."""
    capabilities = reader_backends.capabilities()
    return {"schema": 1, "checked_at": datetime.now(timezone.utc).isoformat(), "version": __version__,
            "python": sys.version.split()[0], "executable": sys.executable, "system": platform.system(),
            "virtual_environment": sys.prefix != sys.base_prefix,
            "packages": _packages(), "weights": _weights(), "tesseract": capabilities["tesseract"],
            "tools": {name: bool(shutil.which(name)) for name in ("git", "jupyter", "docker")},
            "start_here": START_HERE}


def portable_report():
    """Return a generic report for a shareable page, with no machine probes or paths."""
    return {"schema": 1, "portable": True, "version": __version__, "python": None, "executable": "python",
            "system": None, "checked_at": None, "virtual_environment": None, "packages": [], "weights": [],
            "tools": {}, "tesseract": {"available": False, "reason": "not checked", "languages": []},
            "start_here": START_HERE}


def write_app(out=None, report=None):
    """Write a new self-contained HTML file and return its absolute path; never overwrite."""
    report = check_setup() if report is None else report
    template = (DATA / "starter.html").read_text(encoding="utf-8")
    script = (DATA / "starter.js").read_text(encoding="utf-8")
    encoded = json.dumps(report, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = template.replace("__SCRIPT__", script).replace("__REPORT__", encoded)
    destination = Path(out).expanduser().absolute() if out else Path(tempfile.mkdtemp(prefix="scrolls-starter-")) / "index.html"
    # Exclusive open also refuses a symlink, including a dangling one. Parents are not made implicitly.
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(page)
    return destination


def add_arguments(parser):
    """Add the start command's arguments to an argparse parser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--out", metavar="HTML", help="write a new HTML file here; never overwrite (default: temporary folder)")
    group.add_argument("--check", action="store_true", help="print the local setup snapshot as JSON; do not write or open a page")
    parser.add_argument("--portable", action="store_true", help="make a shareable page without inspecting this machine; setup is not checked")
    parser.add_argument("--no-open", action="store_true", help="write the page and print its path without opening a browser")


def run(args):
    """Handle start: print a check or generate and optionally open the local page."""
    try:
        if args.portable and args.check:
            raise ValueError("choose --portable or --check, not both")
        report = portable_report() if args.portable else check_setup()
        if args.check:
            print(json.dumps(report, indent=2))
            return 0
        path = write_app(args.out, report)
        print(f"Scrolls Starter: {path}")
        print("Open this file in a browser. It works offline; no server or account is needed.")
        if not args.no_open:
            try:
                opened = webbrowser.open(path.as_uri())
            except (webbrowser.Error, OSError):
                opened = False
            if not opened:
                print("No browser opened. Open the printed HTML file yourself, or copy it to your own computer.")
        return 0
    except FileExistsError:
        print("error: output already exists; choose a new --out path", file=sys.stderr)
    except (OSError, ValueError) as exc:
        print(f"error: could not prepare Scrolls Starter: {exc}", file=sys.stderr)
    return 2
