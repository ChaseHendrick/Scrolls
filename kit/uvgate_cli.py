"""Sheet gate command: python -m kit uvgate PATH --source-area AREA.

Reads a JSON list of triangles, or CSV when the path ends with .csv,
and prints one verdict object. With --mesh the object also includes
the mesh gate, and pass requires that gate too.
Exit 0 when the verdict passes, 1 when it fails, and 2 on a bad file or gate error.
"""

import argparse
import json
import sys

from .meshgate import mesh_verdict
from .uvgate import UvGateError, load_uv_csv, sheet_verdict, uv_overlap_gate


def build_parser(parser=None):
    """Attach uvgate arguments to a parser. Creates one when none is given."""
    if parser is None:
        parser = argparse.ArgumentParser(prog="python -m kit uvgate")
    parser.add_argument(
        "path",
        metavar="PATH",
        help="JSON file: a list of triangles, each three [u, v] numbers. A .csv file uses header tri,u,v",
    )
    parser.add_argument(
        "--source-area",
        type=float,
        required=True,
        help="source area for the sheet verdict",
    )
    parser.add_argument(
        "--min-fraction",
        type=float,
        default=0.90,
        help="minimum coverage fraction (default 0.90)",
    )
    parser.add_argument(
        "--overlap-only",
        action="store_true",
        help="score uv_overlap_gate and ignore coverage",
    )
    parser.add_argument(
        "--mesh",
        action="store_true",
        help="also score mesh_verdict and require it to pass",
    )
    return parser


def cmd_uvgate(args):
    """Print one verdict JSON object and return the process status."""
    try:
        with open(args.path, encoding="utf-8") as handle:
            raw = handle.read()
        if str(args.path).lower().endswith(".csv"):
            triangles = load_uv_csv(raw)
        else:
            triangles = json.loads(raw)
        if args.overlap_only:
            verdict = uv_overlap_gate(triangles)
        else:
            verdict = sheet_verdict(
                triangles, args.source_area, min_fraction=args.min_fraction
            )
        if getattr(args, "mesh", False):
            mesh = mesh_verdict(triangles)
            verdict["mesh"] = mesh
            verdict["pass"] = verdict["pass"] and mesh["pass"]
    except (OSError, json.JSONDecodeError, UvGateError, TypeError, ValueError) as exc:
        print(f"uvgate: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(verdict))
    return 0 if verdict["pass"] else 1
