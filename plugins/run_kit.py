"""Run `python -m kit` from this checkout, for the VC3D plugin manifests in this folder.

    python3 plugins/run_kit.py strokenet MAP.png --pixel-mm 0.0024 --json

VC3D starts plugins with an argument list and no working directory of their own, so
`python3 -m kit` only works where the kit is installed. This launcher puts the checkout
that holds it first on sys.path and hands every argument to kit's own command line,
so a manifest works from a plain clone. It adds nothing else.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from kit.cli import main  # noqa: E402  (after the path is set)

if __name__ == "__main__":
    sys.exit(main())
