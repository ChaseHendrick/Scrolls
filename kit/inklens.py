"""Ink Lens from kit: `python -m kit.inklens ARGS` runs spaces/ink-lens/inklens.py with ARGS.

The tool registry (kit/data/registry/ink-lens.json) starts Ink Lens this way, because a manifest runs kit or a
program on PATH, never a file path. The tool's page is docs/tools/ink-lens.md. Standard library only here; Ink Lens
itself needs numpy and tifffile, and torch in local mode.
"""

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "spaces" / "ink-lens" / "inklens.py"


def load():
    """Ink Lens's client module, from this checkout."""
    if not SCRIPT.is_file():
        raise FileNotFoundError(f"{SCRIPT} is missing: Ink Lens ships in public Scrolls under spaces/ink-lens/")
    here = str(SCRIPT.parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    spec = importlib.util.spec_from_file_location("inklens_client", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    try:
        mod = load()
    except FileNotFoundError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return mod.main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
