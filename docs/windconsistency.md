# Relative winding consistency

`python -m kit windconsistency CHAINS.json` checks integer relative winding constraints across all supplied
chains. It does not generate labels, modify a mesh, test self-intersections, or establish physical sheet identity.
Synthetic tests only.

Input is a JSON list of chains. Each chain is a list of steps with string point identifiers `a` and `b`, and
integer `k`, meaning winding(b) minus winding(a), outward positive. Booleans are not integer counts.

```json
[[{"a": "p0", "b": "p1", "k": 1},
  {"a": "p1", "b": "p2", "k": 2},
  {"a": "p2", "b": "p0", "k": -3}]]
```

This loop passes because its counts sum to zero. Changing the final count to -2 fails, although no ordered
pair repeats. Constraints may be spread across chains and listed in either direction or any order. Each
disconnected component has an independent winding origin. A spanning-tree potential check tests every
closed path in linear time without enumerating loops.

The JSON verdict contains `pass`, `breaks`, and `rule`. `breaks` counts local input/pair failures; when those
checks pass, each inconsistent connected component adds one break. It is not a count of all contradictory
cycles. Empty input fails with zero breaks. Exit status is 0 for a pass, 1 for inconsistent or invalid chains,
and 2 for an unreadable file or malformed JSON.

The tests include a regression for a three-step contradiction that a pair-only check misses. No real winding data
was assessed. Every option, output and failure is on the [tool page](tools/windconsistency.md).
