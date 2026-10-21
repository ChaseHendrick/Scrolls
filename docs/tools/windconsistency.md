# windconsistency: check that relative winding counts can all hold at once

`python -m kit windconsistency` reads a JSON list of relative winding steps (point a to point b is k windings outward) and passes only when every count is an integer and all of them, across every chain and every closed path, can hold at the same time.

| Field | Value |
| --- | --- |
| Id | `windconsistency` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit windconsistency`, `from kit.windconsistency import wind_check` |
| Code | `kit/windconsistency.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_windconsistency.py` |
| Needs | Python 3.10 or newer, standard library only |
| Runs on | Any CPU. 100,000 steps take about 1.6 s inside Python and about 5 to 6.5 s for the whole command (measured 2026-10-16, 4-core Xeon cloud container under heavy shared load, synthetic chains) |
| Network | None |
| Writes | Nothing (prints one JSON line) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-21; a line of the Scrolls kit entry in the README's "Released tools", id `windconsistency` |
| Guide | [windconsistency.md](../windconsistency.md) |
| Checked | 2026-10-21 against commit `4e2e71e` |

## What it does

A relative winding constraint says how many turns of papyrus (windings) lie between two points: point b is k windings outward of point a, with k negative when b is inward. People click such constraints along lines from the core in villa's spiral-fitting tools (relative-winding annotations), and generators can make them automatically. If the counts disagree with each other, a spiral fit fed with them cannot satisfy them all, and at least one of them is wrong.

`kit windconsistency` checks exactly that, and nothing else. It reads chains of steps `{"a", "b", "k"}` and fails when a count is not an integer, when a point is said to be a nonzero number of windings from itself, when one ordered pair is given two different counts, when a pair and its reverse do not cancel (a to b is k but b to a is not -k), or when any closed path of steps, within one chain or spread over several, does not sum to zero. The last test is what a pair-only check misses: it would pass the loop p0 to p1 to p2 to p0 with every k equal to 1.

It does not say whether the counts are right. A set of counts that is consistent but wrong everywhere (every k doubled, say) passes. It does not generate labels, does not look at a mesh, a prediction or the CT, does not test a surface for self-intersection, and does not establish which physical sheet a point is on. Its verdict is a property of the numbers it is given; it is never a reading and says nothing about ink.

## When to use it

- Before feeding hand-made or generated relative windings to a spiral fit: a failure means the set contradicts itself somewhere.
- After merging constraints from several sources (several annotators, several runs of a generator): contradictions often only appear across sources, around loops.
- As a cheap gate in a pipeline step that writes relative windings, since it is standard library only and linear in the input size.

Do not use it:

- To judge whether counts are correct against published windings: it checks only that they agree with each other.
- To check a UV map or a triangle mesh for overlaps: use [uvgate](uvgate.md).
- On villa's `relative_windings.json` directly: that format holds points with winding values, not `{"a", "b", "k"}` steps, so convert it first (no converter is in the repository).

## Quick start

```bash
cat > LOOP.json <<'EOF'
[[{"a": "p0", "b": "p1", "k": 1},
  {"a": "p1", "b": "p2", "k": 2},
  {"a": "p2", "b": "p0", "k": -3}]]
EOF
python -m kit windconsistency LOOP.json
echo "exit $?"
```

- `LOOP.json`: any file path; the example is the guide's three-step loop, whose counts sum to zero.

It printed (synthetic input, 2026-10-16):

```
{"pass": true, "breaks": 0, "rule": "pass only when every k is an integer, a repeated point has k 0, each ordered pair states one k, the reverse pair is -k, every closed path sums to zero across all chains, and at least one step is present"}
exit 0
```

With the last count changed to `-2` (no ordered pair repeats, but the loop sums to 1) it printed `{"pass": false, "breaks": 1, ...}` and exit 1. It worked when the exit code is 0 and `pass` is `true`.

## Checks and controls

- **The check can fail on a planted contradiction.** Change any one `k` on a closed loop and the verdict must turn to `"pass": false` with exit 1; the Quick start's `-3` to `-2` is that control. `tests/test_windconsistency.py` plants contradictions of every kind: a three-step loop of 1, 1, 1 (the regression the pair-only checker missed), a contradiction spread over three single-step chains in all six orders, a five-step loop off by one, one bad edge among several consistent cycles, a 2,001-step loop off by one, a reverse pair that does not cancel, two counts for one pair, a nonzero self-step, a non-integer count, a boolean count and malformed steps.
- **The consistent cases pass.** The same tests check that a consistent triangle passes in every order and direction, both as one chain and as three, and that disconnected groups of points each get their own origin (a chain with k = 10^30 next to a consistent triangle passes).
- **What a pass does not show.** A pass is necessary for correct counts, not sufficient. It was run on synthetic data only; no real winding data has been checked with it ([guide](../windconsistency.md)).

Claim label: None. The verdict is a property of the supplied numbers (whether they can all hold), not a claim about any scroll; a pass does not make the counts Model output that is right.

## Commands and options

### `python -m kit windconsistency`

```
usage: python -m kit windconsistency [-h] CHAINS.json
```

| Option | Default | Meaning |
| --- | --- | --- |
| `CHAINS.json` | required | Path of a UTF-8 JSON file holding a list of chains; each chain is a list of steps, each step an object with string point ids `a` and `b` and an integer count `k` (see Inputs) |

## Python API

```python
from kit.windconsistency import wind_check
verdict = wind_check([[{"a": "p0", "b": "p1", "k": 1}, {"a": "p1", "b": "p0", "k": -1}]])
print(verdict["pass"], verdict["breaks"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `wind_check(chains)` | `{"pass": bool, "breaks": int, "rule": str}` (see Outputs) | Nothing for any JSON-like input; malformed input is a break, not an exception | Pure function, standard library only, chain order immaterial. `chains` that is not a list gives `{"pass": False, "breaks": 1}` |
| `build_parser(parser)` | The same `argparse` parser, with the `CHAINS.json` positional added | Nothing | Called by `kit/cli.py` to build the `windconsistency` subcommand |
| `cmd_windconsistency(args)` | Exit code: `0` pass, `1` not a pass, `2` unreadable file or invalid JSON | Nothing; read errors are caught and printed | What the command runs. Reads `args.path`, prints the verdict as one JSON line |

The module constant `RULE` is the rule text printed in every verdict.

## Inputs

One JSON file, read as UTF-8:

```json
[[{"a": "p0", "b": "p1", "k": 1},
  {"a": "p1", "b": "p2", "k": 2}],
 [{"a": "p2", "b": "p0", "k": -3}]]
```

| Item | Format | Rule |
| --- | --- | --- |
| Top level | JSON list of chains | Anything else (an object, a number, `null`) is one break and fails |
| Chain | JSON list of steps | An empty list, or anything that is not a list, is one break |
| Step | JSON object with keys `a`, `b`, `k`; other keys are ignored | A step that is not an object, or whose `a` or `b` is not a string, or whose `k` is not an integer, is invalid: the chain gets one break however many invalid steps it has, and its valid steps are still checked |
| `a`, `b` | Strings, point identifiers | Any string; the same string is the same point in every chain. Numbers are not accepted as ids |
| `k` | JSON integer, any size (Python integers are exact) | winding(b) minus winding(a), outward positive. `1.0`, `1.5`, `"1"`, `true` and `false` are not integers. `a` equal to `b` needs `k` 0 |

Chains are only a way to group steps: constraints are pooled over all chains, so a loop may be spread over several chains, and steps may be listed in any order or direction. There is no size limit in the code; memory grows with the number of distinct points and pairs (about 140 MB peak for 100,000 steps on 100,000 points, measured 2026-10-16).

## Outputs

One JSON line on stdout, for every readable file:

| Field | Type | Meaning |
| --- | --- | --- |
| `pass` | bool | True only when `breaks` is 0 and at least one valid step was given |
| `breaks` | int | Number of failures found (see How it works): local input and pair failures; only when there are none, one per connected group of points whose counts contradict each other. It is not a count of contradictory cycles. 0 with `pass` false means no valid step at all (an empty list) |
| `rule` | str | The rule text (`RULE`), the same in every verdict |

Nothing is written to disk. Read errors go to stderr as `windconsistency: MESSAGE`.

| Exit code | Meaning |
| --- | --- |
| `0` | `pass` is true: every count is an integer and all of them can hold at once |
| `1` | The file was read and parsed and `pass` is false: invalid or contradictory steps, or no step at all |
| `2` | The file could not be opened or decoded, or is not valid JSON (message on stderr), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: the following arguments are required: CHAINS.json` on stderr, exit code 2 | No file given | Pass the JSON file path |
| `windconsistency: [Errno 2] No such file or directory: 'PATH'`, exit code 2 | The path does not exist (any `OSError`, such as a directory or no permission, prints the same way) | Fix the path |
| `windconsistency: Expecting value: line 1 column 1 (char 0)`, exit code 2 | The file is not JSON (any `ValueError` from the JSON parser or the UTF-8 decoder prints its own message after `windconsistency:`) | Write the file as UTF-8 JSON |
| `{"pass": false, "breaks": 0, ...}`, exit code 1 | The list holds no valid step (for example `[]`) | Give at least one step |
| `{"pass": false, "breaks": N, ...}` with N at least 1, exit code 1 | An invalid step, a nonzero self-step, two counts for one pair, a reverse pair that does not cancel, or a loop that does not close | Find the bad steps with `wind_check` on subsets, or fix the generator; the verdict does not say which step is wrong |

## How it works

1. Read the file and parse it as JSON (`cmd_windconsistency`); a read or parse error prints a message and returns 2.
2. For each chain: a chain that is not a non-empty list adds one break. Each step must be an object with string `a`, string `b` and integer `k` (`_integer` accepts `int` but not `bool`); any invalid step adds one break for the chain. A step with `a` equal to `b` and `k` not 0 adds one break for the chain. Valid steps are counted and recorded as `stated[(a, b)]`, the set of counts given for that ordered pair.
3. Each ordered pair with more than one distinct count adds one break.
4. Each pair stated in both directions whose counts are not exact negatives of each other adds one break (once per unordered pair).
5. Only when steps 2 to 4 found nothing: build an undirected graph with an edge a to b of weight k and b to a of weight -k, and walk each connected group of points from an arbitrary start with winding 0, assigning winding(b) = winding(a) + k along a spanning tree (`_inconsistent_components`). An edge whose ends already have windings that differ from its k means some closed path through it does not sum to zero; each group with such an edge adds one break. This tests every closed path without listing them, in time linear in points plus steps, with exact integers and no recursion (a 2,001-step loop is in the tests).
6. `pass` is `breaks == 0` and at least one valid step.

No published method is followed; assigning integer potentials along a spanning tree is the standard test that a set of difference constraints on a graph is consistent.

## Cost and time

Measured 2026-10-16 on a 4-core Xeon cloud container (lscpu reports 2.80 GHz), with the load average about 20 from other sessions, so the times are upper bounds. On a synthetic consistent set of 10,000 chains of 10 random steps among 100,000 points (4.1 MB of JSON): `wind_check` alone 1.6 s; with one count planted wrong 2.6 s (the walk runs then); the whole command 4.9 to 6.5 s including Python start-up and the JSON parse, about 140 MB peak memory. The Quick start's three-step file took about 2.1 s, nearly all of it start-up. It runs anywhere; nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit windconsistency CHAINS.json`; the output is always one JSON line on stdout.
- **Parse:** `pass` (bool) is the verdict; `breaks` (int) is how many failures were found, not which steps; `rule` is fixed text.
- **Rerun:** Safe and idempotent; it only reads the file.
- **Success:** Exit code 0 and `"pass": true`.
- **Not a pass:** Exit 1 with `"breaks": 0` (no valid step at all). And a pass is not evidence that the counts are right: a consistently wrong set passes.
- **Go-ahead:** Nothing.
- **Never:** Call a pass a verified winding labeling, a reading, or evidence of sheet identity; pass it numbers as strings or floats (`"1"`, `1.0` fail).

## Tests

```bash
python -m unittest tests.test_windconsistency -v
```

20 tests, all synthetic, about 1.5 s: single steps, agreeing and disagreeing repeats, reverse pairs, non-integer and boolean counts, self-steps, empty input, the three-step loop regression, consistent triangles in every order and direction, contradictions across chains, long loops, disconnected groups, malformed input, and the command line's exit codes 0, 1 and 2 with JSON output and the `windconsistency:` error prefix. They do not run on real winding data.

## History

- 2026-10-21: first public release, from public `main` at `4e2e71e`, with `python -m kit windconsistency` in `kit/cli.py`; first written 13 October 2026 from a pair-only checker, under a new name so it does not clash with the external windcheck tool, adding the closed-path check across all chains.

## Related

- [windconsistency guide](../windconsistency.md): the input format and the verdict.
- [uvgate](uvgate.md): the separate check that triangles do not overlap in UV, released with this tool.
