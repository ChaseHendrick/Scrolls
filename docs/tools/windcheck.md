# windcheck: measure winding coverage around a candidate axis point

Measure how much a slice's predicted sheet traces wrap around a point, with displacement and synthetic controls.

| Field | Value |
| --- | --- |
| Id | `windcheck` |
| Status | Current |
| Kind | kit module |
| Area | Surfaces and tracing |
| Run | `from kit import windcheck` |
| Code | `kit/windcheck.py` |
| Tests | `tests/test_axispolish.py`, `tests/test_windcheck.py` |
| Needs | Python 3.10 or newer, numpy and level-0 `(x, y)` polylines |
| Runs on | CPU; through [axispolish](axispolish.md) about 0.75 s per slice with numba and about 6 s with numpy alone on 4 cloud cores (22 Oct 2026, the frozen test's development runs) |
| Network | None |
| Writes | Nothing; returns arrays and dictionaries |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-24, with [axispolish](axispolish.md); a line of the Scrolls kit entry in the README's "Released tools" |
| Checked | 2026-10-24 against commit `81e5ead` |

## What it does

`windcheck` sums the absolute angle that a slice's sheet segments subtend around a candidate point, then divides by one full turn. The result is winding coverage in wraps. A completely traced closed loop around the point contributes one wrap. [axispolish](axispolish.md) uses it to move a center line to the deepest point of the traced sheet.

Coverage measures geometry in model-predicted traces. Missing traces lower it, duplicate traces increase it, and a hollow core can have nearly flat coverage. It is not true-axis distance or a reading of ink. Ring offsets measure sensitivity; the local grid search is descriptive and never decides a scientific verdict.

## When to use it

Use it to compare candidate center points on the same slice traces and check sensitivity to displacement. Use [axispolish](axispolish.md) to polish a whole center line, and [centerline](centerline.md) to get one. Do not compare raw coverage across different trace sets as though only axis quality changed.

## Quick start

Run planted spirals from the repository root:

```bash
python - <<'PY'
import json
from kit import windcheck
result = windcheck.selfcheck()
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if result['passes'] else 1)
PY
```

Observed on 17 October 2026:

```json
{"coverage": [19.841, 18.375, 16.408, 13.197], "flattened": [19.895, 18.195, 15.812], "passes": true, "thinned": {"centre": 11.925, "three_wraps": 10.614}}
```

These are synthetic values. `passes` means the prescribed displacements reduced coverage.

## Checks and controls

`selfcheck` generates a 20-turn spiral with pitch 40 voxels. Coverage must decrease from the center to points 2, 5 and 10 pitches away. Compressing the spiral to half height must preserve the decrease at 0, 2 and 5 pitches. After seeded removal of 40% of segments, the center must still exceed a point 3 pitches away. The self-check can return false.

`ring` defaults to eight offsets at the caller's radius. A flat response shows that this trace set cannot distinguish the candidates at that displacement. The polish test of 22 October 2026 used a 3 mm ring round villa's point as its sensitivity control (pooled -2.40 wraps, so the check sees 3 mm).

Claim label: Model output, geometry measured against predicted traces; the example is synthetic.

## Commands and options

Not applicable: the module has no CLI. Use its Python API or `python -m kit axispolish`.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `segments(lines)` | `(P, Q)` float arrays | Numpy import/shape errors | Consecutive endpoints, each `(M, 2)`; empty input gives empty arrays |
| `coverage(segs, point)` | Float wraps | Numeric/input errors | Empty segments return `0.0`; excludes segments within 0.5 voxels of the point |
| `ring(segs, point, radius, n=8)` | Float list | Numeric/input errors | Radius in voxels; equally spaced offsets starting at positive x |
| `best_near(segs, points, radius, step)` | `(coverage, (x, y))` or `None` | Numeric/input errors | Highest sampled value within the search circles; empty centers give `None` |
| `spiral(centre, pitch, turns, step=2.0, start=0.0)` | Float `(N, 2)` array | Numeric/input errors | Synthetic Archimedean spiral; positive pitch and step |
| `selfcheck()` | Dictionary | Numpy import/numerical errors | Seeded displacement controls |

## Inputs

`lines` is an iterable of numeric polylines of shape `(N, 2)`, in `(x, y)` order and level-0 voxels. Segment pairs have equal shape `(M, 2)`. Points use the same coordinates. Radius, search step, spiral pitch and start radius are in voxels. Use finite coordinates and positive finite steps; these low-level functions do not comprehensively validate inputs. No hard size limit is imposed.

## Outputs

The library prints and writes nothing. Function returns are listed in Python API.

| Field | Type | Meaning |
| --- | --- | --- |
| `passes` | Boolean | All self-check displacement inequalities hold |
| `coverage` | Float list | Synthetic coverage at 0, 2, 5 and 10 pitches from center |
| `flattened` | Float list | Coverage at 0, 2 and 5 pitches on the compressed spiral |
| `thinned` | Object | `centre` and `three_wraps` after random segment removal |

All coverage values are wraps. The Quick start wrapper exits 0 on pass and 1 on failure; the library has no exit status.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'numpy'` | Missing numerical dependency | Install the project's numpy dependency in the active interpreter |
| `ValueError` while reshaping | Malformed points | Supply numeric `(N, 2)` coordinates |
| Non-finite coverage | Non-finite input coordinates | Validate inputs; do not interpret NaNs |
| `ZeroDivisionError` in local search | Zero step | Use a positive finite step |
| `passes: false` | A planted check failed | Diagnose numerical or implementation changes before interpreting comparisons |
| High or flat coverage at implausible points | Missing or duplicated traces, or a hollow core | Inspect provenance and ring sensitivity; avoid an unsupported ranking |

## How it works

The function wraps each segment's angular difference into the shortest signed interval, takes its absolute value, sums, then divides by `2*pi`. Segment direction does not matter. A segment passing within `NEAR_VOXELS = 0.5` voxels of the candidate is omitted because its sweep is undefined there.

`best_near` samples a square lattice clipped to circles with integer radius `int(radius // step)`. It does not optimize a continuous curve. `spiral` uses roughly `step` arc spacing. The thinning control uses numpy seed `20261016`.

## Cost and time

Production timing and memory are not measured. Array space grows with segment count; ring and search time multiply by the number of candidate points. The synthetic example ran on a cloud CPU on 17 October 2026. No jobs or paid compute are launched.

## For agents

- **Command:** Run the Python self-check above; use identical segment arrays for every compared candidate.
- **Parse:** Require `passes: true`. Coverage and gains are wraps; coordinates and radii are voxels.
- **Rerun:** Pure arithmetic, no files; synthetic defaults are deterministic.
- **Success:** Passing controls establish synthetic behavior, not the true axis of a scroll.
- **Not a pass:** Flat ring response, duplicated traces, different trace sets or choosing a local optimum after inspecting the arms.
- **Go-ahead:** Nothing.
- **Never:** Call coverage true-axis distance, use descriptive local search as a verdict, or call model output a reading.

## Tests

```bash
python -m unittest tests.test_windcheck -q
```

Tests cover loops, off-center candidates, spiral displacement, segments crossing the point, ring sampling, local search and the self-check. They do not establish trace completeness or accuracy on real scans.

## History

- 2026-10-24: ported to public Scrolls with [axispolish](axispolish.md) on top of `81e5ead`; the code is the private module of 16 October 2026, unchanged except its docstring.

## Related

- [axispolish](axispolish.md): polishes a center line by this coverage.
- [centerline](centerline.md): gets a scroll's published center line.
- [Polish test evidence](../evidence/2026-10-22-umbilicus-windpolish/README.md): the 22 October 2026 result.
