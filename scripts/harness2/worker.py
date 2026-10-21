"""Fixed CLI worker; it accepts only a generated record and a boolean recipe.

engine.py starts it as `python -I -S -B worker.py RECORD true|false`. It runs the real
`python -m kit provenance check` (with `--files` for true) in this process, with an audit
hook that refuses network use, process launches and file writes. The hook guards this
worker's own code path; it is not a security sandbox.
"""

import sys

sys.dont_write_bytecode = True

import importlib.util  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LAUNCH = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
          "os.forkpty", "pty.spawn")
CHANGES = ("os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.truncate", "os.symlink", "os.link",
           "os.chmod", "os.utime", "shutil.rmtree", "shutil.copyfile", "shutil.move")
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def forbid_external(event, args):
    if event.startswith("socket.") or event in LAUNCH:
        raise RuntimeError("the synthetic provenance worker cannot use network or launch processes")
    writing = event in CHANGES
    if event == "open":
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
            (isinstance(flags, int) and bool(flags & WRITE_FLAGS))
    if writing:
        raise RuntimeError("the synthetic provenance worker cannot write files")


def load_kit():
    """Import this checkout's kit package by file location, without changing sys.path."""
    spec = importlib.util.spec_from_file_location(
        "kit", ROOT / "kit" / "__init__.py", submodule_search_locations=[str(ROOT / "kit")])
    module = importlib.util.module_from_spec(spec)
    sys.modules["kit"] = module
    spec.loader.exec_module(module)
    from kit.cli import main as kit_main
    return kit_main


def main(argv):
    if len(argv) != 3 or argv[2] not in ("true", "false"):
        raise SystemExit("fixed worker requires RECORD and true|false")
    sys.addaudithook(forbid_external)
    kit_main = load_kit()
    arguments = ["provenance", "check", argv[1]]
    if argv[2] == "true":
        arguments.append("--files")
    return kit_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
