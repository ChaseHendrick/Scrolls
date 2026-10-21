"""Relative winding chains: reject a chain that contradicts itself.

A chain is a list of steps. Each step has point ids ``a`` and ``b`` and an
integer wrap count ``k`` from ``a`` to ``b`` (outward positive). Standard
library only. Not a UV orientation gate, a surface self-intersection test, or a reading.

  python -m kit windconsistency CHAINS.json

Checks relative constraints across all chains, including loops of three or more steps.
Prints JSON and exits 0 for a pass, 1 for inconsistent/invalid chains, or 2 for an unreadable file.
Named windconsistency to avoid a clash with the external joe-carr-data/windcheck tool.
"""

from __future__ import annotations

import json
import sys

RULE = (
    "pass only when every k is an integer, a repeated point has k 0, "
    "each ordered pair states one k, the reverse pair is -k, "
    "every closed path sums to zero across all chains, and at least one step is present"
)


def _integer(k):
    return isinstance(k, int) and not isinstance(k, bool)



def _inconsistent_components(stated):
    """Count components with no integer point potentials satisfying W(b) - W(a) = k.

    Called after the pair checks, so each pair has exactly one k. Assigning potentials
    along a spanning tree checks all cycles without enumerating them, in O(points + steps).
    Each disconnected component has its own arbitrary zero. No recursion or floating point.
    """
    adjacent = {}
    for (a, b), ks in stated.items():
        k = next(iter(ks))
        adjacent.setdefault(a, []).append((b, k))
        adjacent.setdefault(b, []).append((a, -k))
    winding = {}
    breaks = 0
    for start in adjacent:
        if start in winding:
            continue
        winding[start] = 0
        pending = [start]
        inconsistent = False
        while pending:
            a = pending.pop()
            for b, k in adjacent[a]:
                expected = winding[a] + k
                if b not in winding:
                    winding[b] = expected
                    pending.append(b)
                elif winding[b] != expected:
                    inconsistent = True
        breaks += int(inconsistent)
    return breaks


def wind_check(chains):
    """Return ``{"pass", "breaks", "rule"}`` for a list of winding chains.

    ``pass`` is True only when ``breaks == 0`` and there is at least one step.
    An empty chain is a break. No chains at all fails with ``breaks == 0``.
    When the local input/pair checks pass, each inconsistent connected component adds
    one break. Breaks are not a census of distinct cycles. Chain order is immaterial.
    """
    if not isinstance(chains, list):
        return {"pass": False, "breaks": 1, "rule": RULE}

    breaks = 0
    steps = 0
    stated = {}

    for chain in chains:
        if not isinstance(chain, list) or len(chain) == 0:
            breaks += 1
            continue
        bad_k = False
        repeated = False
        kept = []
        for step in chain:
            if not isinstance(step, dict):
                bad_k = True
                continue
            a = step.get("a")
            b = step.get("b")
            k = step.get("k")
            if not _integer(k) or not isinstance(a, str) or not isinstance(b, str):
                bad_k = True
                continue
            if a == b and k != 0:
                repeated = True
            kept.append((a, b, k))
        if bad_k:
            breaks += 1
        if repeated:
            breaks += 1
        for a, b, k in kept:
            steps += 1
            stated.setdefault((a, b), set()).add(k)

    for ks in stated.values():
        if len(ks) > 1:
            breaks += 1

    seen = set()
    for (a, b), ks in stated.items():
        if a == b or (b, a) not in stated:
            continue
        token = (a, b) if (a, b) < (b, a) else (b, a)
        if token in seen:
            continue
        seen.add(token)
        if ks != {-k for k in stated[(b, a)]}:
            breaks += 1

    if breaks == 0:
        breaks += _inconsistent_components(stated)
    return {"pass": breaks == 0 and steps > 0, "breaks": breaks, "rule": RULE}


def build_parser(parser):
    parser.add_argument("path", metavar="CHAINS.json", help="JSON list of winding chains; each step has a, b and k")
    return parser


def cmd_windconsistency(args):
    try:
        with open(args.path, encoding="utf-8") as handle:
            chains = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"windconsistency: {exc}", file=sys.stderr)
        return 2
    verdict = wind_check(chains)
    print(json.dumps(verdict))
    return 0 if verdict["pass"] else 1
