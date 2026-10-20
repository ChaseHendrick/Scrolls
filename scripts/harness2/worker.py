"""Fixed CLI worker; it accepts only a generated record and a boolean recipe."""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def forbid_external(event, args):
    if event.startswith("socket.") or event in ("subprocess.Popen", "os.system", "os.posix_spawn"):
        raise RuntimeError("the synthetic provenance worker cannot use network or launch processes")


sys.addaudithook(forbid_external)

from kit.cli import main

if len(sys.argv) != 3 or sys.argv[2] not in ("true", "false"):
    raise SystemExit("fixed worker requires RECORD and true|false")
arguments = ["provenance", "check", sys.argv[1]]
if sys.argv[2] == "true":
    arguments.append("--files")
raise SystemExit(main(arguments))
