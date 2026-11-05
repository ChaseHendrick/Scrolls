# fiber-stop-score: end a beam fiber trace before it slides onto the next fiber, with the sheet-plane penalty it was tested with

Two opt-in settings for villa's beam fiber tracer, proposed in villa PRs #2377 (`stop_score_weights`, `stop_score_bias`) and #2265 (`sheet_plane_weight`): fewer traces that leave the annotated fiber, for about the same traced length.

| Field | Value |
| --- | --- |
| Id | `fiber-stop-score` |
| Status | Experimental |
| Kind | patch |
| Area | Surfaces and tracing |
| Run | villa's own entry points, built from the two PR branches: the reference evaluation `python3 -m vc.fiber_evaluation CONFIG.json RESULT.json` with the keys below in its `trace` block, or `vc.fiber_trace.TraceConfig` from Python. `vc.fiber_trace.stop_score_features` gives the stop score's three inputs along any polyline |
| Code | Not in this repository: villa draft PR [#2377](https://github.com/ScrollPrize/villa/pull/2377) (branch `fiber-stop-score` of ChaseHendrick/villa, head `4a07823150851a8dfd158203d19ce42e051940bc`, two commits on villa `main` `08e06a804`) and draft PR [#2265](https://github.com/ScrollPrize/villa/pull/2265) (branch `fiber-sheet-plane`, head `009a404dbf33aec556fe7bfc7853173326f9ba75`, villa `main` `f7756c758` merged in). Files touched: villa's fiber tracer core source and header, the chunk tracer, reference replay, and the `vc.fiber_trace` Python bindings |
| Tests | None in this repository. In villa: 3 C++ cases in `test_fiber_trace3d` and 1 in `test_fiber_reference_replay_core` plus 2 Python tests for the stop score (#2377); 5 C++ cases and 2 Python tests for the sheet-plane weight (#2265). See Tests |
| Needs | A villa build with its Python package (`vc.fiber_trace`, `vc.fiber_evaluation`) from both PR branches merged; the public fiber prediction and lasagna normals of the scroll (open data); for a test, annotated fibers in villa's fiber JSON |
| Runs on | Wherever villa's beam fiber tracer runs (CPU). The stop score adds three presence look-ups per committed step; the extra time was not measured separately |
| Network | villa's tracer reads the fiber prediction and lasagna normals from the open-data bucket `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`, as stock villa does; these settings add no host |
| Writes | Nothing of its own: villa's evaluation writes RESULT.json and its cache under the config's `remote_cache_root`, as without these settings |
| Go-ahead | Not needed to build or run. Changing the villa PRs' text or posting on them needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Proposed upstream as villa draft PRs #2265 (2026-10-23) and #2377 (2026-10-30); not merged in villa. This page: public `main` since 2026-11-05 |
| License | The code is in villa PRs under villa's license (MIT); this page Apache 2.0 ([LICENSE](../../LICENSE)); fiber predictions, normals and annotations are Vesuvius Challenge open data (CC BY-NC 4.0) |
| Checked | 2026-11-05 against commit `cc5f793` |

## What it does

villa's beam fiber tracer follows a papyrus fiber through the organizers' fiber prediction. Its common failure is not stopping too early but going on too long: the trace slides onto a neighboring fiber and keeps going. The organizers' [2026 open problems](https://scrollprize.org/2026_open_problems) put the trade plainly: "a tracer that confidently follows fewer fibers correctly is more useful than one that follows more fibers with a higher error rate." A stop is cheap to fix (reseed); a wrong stretch has to be found and deleted. Until these PRs the only early stop was `replay_presence_cutoff`, which stops where fiber presence is low, and presence often stays high where the trace has already left its fiber.

The **stop score** (villa #2377) ends a beam trace before a committed step when `bias + weights . [presence, axis agreement, lateral rival] > 0`. All three inputs are things the tracer already samples at the current point: the presence of the strongest valid direction, how well that direction agrees with the step, and how much stronger a fiber is 8, 16 or 24 base voxels to the side. It reads only the current point, so it never looks ahead. The trace ends with reason `stop_score`; reference replay treats that like a presence-cutoff stop (`stop_score_filtered`) and reseeds further along the reference.

The **sheet-plane penalty** (villa #2265, `sheet_plane_weight`) charges each candidate step `weight * asin(|n . d|)^2`, the squared angle between the step `d` and the local lasagna sheet plane (normal `n`), so a slow drift out of the sheet costs something. The stop score was tuned and tested on top of it at weight 0.75, so the two are used together.

Both settings are off by default (all weights 0), and off they leave the tracer exactly as stock villa. The chunk tracer (CPU and GPU) refuses a config with either one on. Status is Experimental: neither PR is merged in villa, and the sheet-plane penalty's own gain resolved on one of three public test sets (see Checks and controls). Traces are model output scored against human fiber annotations; nothing here reads text.

## When to use it

- Tracing fibers with villa's beam tracer where a wrong stretch costs more than a stop, for example when traces feed a fiber-guided mesh and every wrong fiber has to be found by hand.
- Fitting stop weights for a scroll that looks different from PHerc0139: `vc.fiber_trace.stop_score_features` returns the three inputs along any polyline, so a logistic fit on development fibers gives new weights.

Do not use it:

- When reach matters more than precision: the stop score reaches fewer annotated control points than the stock beam tracer from the same seeds (about 9 % fewer in the PR's test). Use the stock settings.
- With the chunk tracer: both settings are beam-only and refused there. Use the beam backend (`backend: beam`).
- As a replacement for villa's learned `fiber_tracer_large` where its precision is what you need: `fiber_tracer_large` is more precise per traced voxel in every test here, and stops much sooner.
- Without lasagna normals: `sheet_plane_weight` needs them.

## Quick start

Fetch both PR branches into a villa clone, merge them, and build villa's Python package as villa's own build instructions describe:

```bash
git clone https://github.com/ScrollPrize/villa.git && cd villa
git fetch origin pull/2265/head:fiber-sheet-plane pull/2377/head:fiber-stop-score
git checkout -b fiber-tracer-tested fiber-sheet-plane
git merge fiber-stop-score
```

The merge stops on one conflict in `volume-cartographer/core/src/fiber_tracer/FiberChunkTrace.cpp`, where each branch adds its own chunk-tracer refusal on the same line: keep both `throw` lines, then `git add` that file and `git commit`. Checked with `git merge-tree` on the heads named in Code (5 Nov 2026); the merged tree was not built for this page.

Then put the tested settings in the `trace` block of a `vc.fiber_evaluation` config (the format of villa's `docs/fiber_evaluation.md`):

```json
"trace": {
  "replay_presence_cutoff": 0.1,
  "sheet_plane_weight": 0.75,
  "stop_score_weights": [-3.337961978038475, -38.37888728031481, 3.2607291950806836],
  "stop_score_bias": 35.39635373347652
}
```

and run `python3 -m vc.fiber_evaluation CONFIG.json RESULT.json`. CONFIG.json is a villa evaluation config with the fiber list and prediction manifest; RESULT.json is where villa writes the replay result. It worked when segments in RESULT.json end with termination reason `stop_score_filtered` as well as villa's usual reasons. Recorded on the #2377 branch build (30 Oct 2026, Ubuntu 24.04, 4 cores, Release, `VC_TESTING=ON`, Python 3.13): `test_fiber_trace3d` 54 cases pass, `test_fiber_reference_replay_core` 8 pass, Python `test_fiber_trace.py` and `test_fiber_evaluation.py` 22 pass.

## Checks and controls

Every setting was fixed on PHerc0139 development fibers before any test, each test's rules were written down before it ran, and each was run once. Fibers are the annotators' public fibers, all drawn after the organizers' fiber model (run `20260915212757`) was trained; the tracer followed that model's public prediction. A failure is the trace going more than 20 base voxels off the annotated fiber (villa's `vc.fiber_evaluation`, `error_threshold_base` 20).

**Stop score against a presence cutoff that stops about as often.** The control that can fail: `replay_presence_cutoff` 0.26, chosen on the development fibers to add about as many stops as the stop score. A stop score that only stopped more would do no better than it.

| Test (public annotator fibers) | Fibers | Failures per voxel, stop score over cutoff 0.26 (95 % interval) | Traced length kept | Stops |
| --- | ---: | ---: | ---: | ---: |
| PHerc1451, files from `dl.ash2txt.org/other/annotators/1451_fibers/` (28 Oct 2026) | 193 | 0.73 (0.66 to 0.79) | 1.00 | 0.90 |
| PHerc1451, new fibers drawn in VC3D's shared fiber store `dl.ash2txt.org/other/annotators/fibers_db/` from 1 to 3 Nov 2026 (3 Nov 2026) | 84 | 0.73 (0.64 to 0.86) | 1.00 | 0.80 |

Pass needed the ratio's one-sided 95 % upper bound below 1, at least 95 % of the cutoff's kept length and at most 125 % of its stops; both passed. On the 84 new fibers, against the same tracer with no stop at all, the ratio was 0.69 (0.60 to 0.79), at the same kept length: 92.3 failures per million voxels kept without a stop, 86.8 with the cutoff, 63.6 with the stop score.

**From fixed seeds, scored at the annotators' control points** (a trace that runs onto a neighboring fiber stops counting; length precision is on-fiber length over traced length):

| | PHerc1451, 760 seeds on 190 fibers | PHerc1451 new fibers, 332 seeds on 83 fibers |
| --- | ---: | ---: |
| Length precision, stop score over stock beam settings | 1.13 (1.09 to 1.18) | 0.914 against 0.839 |
| Control points reached, stop score over stock | 0.91 (0.87 to 0.95) | 713 against 912 |
| `fiber_tracer_large` at confidence 0.7: length precision | 0.99 | 0.978 |
| Stop score's precision as a share of `fiber_tracer_large`'s | 0.91 | 0.93 (0.89 to 0.97) |
| Control points reached, stop score over `fiber_tracer_large` | 3.07 (2.75 to 3.46) | 4.1 (713 against 175) |

The bar set beforehand against the community tracer, at least 0.90 of [`fiber_tracer_large`](https://huggingface.co/scrollprize/fiber_tracer_large)'s length precision, was met on both PHerc1451 sets.

**Two controls that can fail, on the new fibers.** Both cut the same traces made without the stop score to no more than the stop score's kept length: one with the stop scores shuffled along each trace, one with stops at random points. If the gain came only from stopping more, they would match the stop score. They did not: length precision 0.865 (shuffled) and 0.824 (random) against 0.914; the stop score's off-fiber share was 0.64 of the shuffled control's (one-sided upper bound 0.80) and 0.49 of the random control's (upper bound 0.67), so both controls failed as the rules required. These controls cut finished traces; they were not run inside the tracer.

**Sheet-plane penalty (weight 0.75) against stock (weight 0).**

| Test | Score | Result |
| --- | --- | --- |
| 192 PHerc0139 fibers (`0139_fibers/`, 23 Oct 2026) | Failures per voxel on villa's replay | 0.94 (0.90 to 0.97): 1,233 against 1,322 failures, 99.7 % of stock's length, 100.8 % of its stops. Pass |
| 116 PHerc0332 fibers (`0332_fibers/`, 23 Oct 2026) | Annotators' control points reached from 464 fixed starts | 1.025 (98.33 % interval 0.973 to 1.081): no difference resolved |
| 193 PHerc1451 fibers (28 Oct 2026) | Failures per voxel on villa's replay | 0.95 (0.89 to 1.01): not resolved; control points reached 1.01 times stock |

So the penalty keeps traces closer to the reference line on PHerc0139, where that line was mostly drawn by the beam tracer itself (villa issue [#2264](https://github.com/ScrollPrize/villa/issues/2264)), and did not resolve a gain elsewhere. On the 84 new PHerc1451 fibers its reading was void: one of ten parts of the stock arm failed on a download error and the rules allowed no rerun.

Limits, stated as found:

- New fibers on a scroll the method has already seen. Both stop score tests used PHerc1451, and the public fiber prediction the tracer follows was trained on other PHerc1451 fibers. The stronger test, a scroll unseen by both the stop score's settings and `fiber_tracer_large`, has not been run.
- villa #2377 also reports a second test scroll, whose fibers `fiber_tracer_large` lists in its training data. There the stop score again cut failures against the matched cutoff, but `fiber_tracer_large` kept clearly more of its traced length on the fiber, below the 0.90 bar.
- One development scroll (PHerc0139) set every weight. The stop score's weights are a class-weighted logistic fit of "a failure follows within 150 base voxels" on 30 development fibers; on 297 development fibers it had 14.9 % fewer failures per voxel than weight 0.75 alone, at 99.7 % of its length.
- The reference lines between annotated control points are mostly beam-drawn, which favors the beam tracer on replay; the control-point tables guard against that.

Claim label: Model output (villa's tracers over the public fiber prediction), scored against human fiber annotations under rules fixed before each run; the readings in the tables are Measurements of those outputs. Sources: villa PRs #2377 and #2265 for the earlier tests; the 84-fiber test is new on this page.

## Commands and options

### villa `TraceConfig` keys added by the two PRs

Set in a `vc.fiber_evaluation` config's `trace` block, in a fiber tracer JSON config, or as `vc.fiber_trace.TraceConfig(...)` keyword arguments and attributes.

| Option | Default | Meaning |
| --- | --- | --- |
| `stop_score_weights` | `[0.0, 0.0, 0.0]` | Weights of [presence, axis agreement, lateral rival]. All zero turns the stop score off. Each must be finite. Tested: `[-3.338, -38.379, 3.261]` |
| `stop_score_bias` | `0.0` | Added to the weighted sum; the trace ends before a step whose total is above 0. Must be finite. Tested: `35.396`, which gave about 160 extra stops per million voxels on the development fibers |
| `sheet_plane_weight` | `0.0` | Weight of the squared out-of-sheet angle in each candidate step's loss. 0 disables it; negative or non-finite values are rejected. Needs lasagna normals. Tested: `0.75` |

The settings were tested with villa's `replay_presence_cutoff` 0.1, `error_threshold_base` 20 and `backend` `beam`, other values at villa's defaults.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `vc.fiber_trace.stop_score_features(field, points_base_xyz)` | An N x 3 array: presence, axis agreement, lateral rival at each point | `ValueError` with fewer than two points | The same features the beam tracer computes for `stop_score_weights`; use it to fit your own weights on development fibers. villa #2377 |
| `vc.fiber_trace.TraceConfig` | The trace config | `ValueError` on an invalid value | Gains the `stop_score_weights`, `stop_score_bias` and `sheet_plane_weight` attributes; `to_dict` and `from_dict` round-trip them |

## Inputs

- The scroll's public fiber prediction (villa's lasagna manifest of `presence` and the axis channels) and its lasagna normals, as villa's tracer reads them. The tests used run `20260915212757` (`...-fibers-20260915212757-L1`) and normals `...-lasagna-20260419180421-L2` of each scroll.
- For an evaluation: annotated fibers in villa's fiber JSON, with at least two control points each, coordinates in base (level 0) voxels. villa's `load_fibers` refuses a file whose non-final control point lacks `segment_to_next`.

## Outputs

villa's own outputs, unchanged in form. A trace the stop score ends has termination reason `stop_score`; in reference replay its segment reads `stop_score_filtered` and the replay reseeds further along the reference. `filtered_stops` in the replay result counts these stops with the presence-cutoff stops. With all weights zero every output is the stock tracer's.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `stop score is supported by the beam backend only` | The stop score is on in a chunk tracer config | Use `backend: beam`, or set the weights to 0 |
| `sheet_plane_weight is currently supported by direct CPU tracing only` | `sheet_plane_weight` above 0 in a chunk tracer config | Use the beam backend, or set the weight to 0 |
| `stop score weight must be finite`, `stop score bias must be finite` | A NaN or infinite value | Give finite numbers |
| `sheet plane weight must be finite`, `smoothness weights must be non-negative` | A NaN, infinite or negative `sheet_plane_weight` | Give 0 or a positive number |
| `stop score features need at least two points` | `stop_score_features` got a single point | Pass a polyline of two or more points |
| `stop score needs finite points, a nonzero step and a positive scale` | A non-finite point, a zero-length step or a bad scale reached the feature code | Check the polyline and `trace_to_base_scale` |
| Git reports a conflict in `FiberChunkTrace.cpp` when merging the two branches | Both branches add a chunk-tracer refusal on the same line | Keep both lines |

## How it works

1. Before each committed beam step, at the current point with the step as the tangent, the tracer takes the strongest valid direction option: its presence is feature 1, and abs(cos) between its direction and the step is feature 2.
2. Feature 3 samples the strongest valid presence at 8, 16 and 24 base voxels to the side, in four directions perpendicular to the step, and subtracts feature 1: a positive value means a stronger fiber lies just beside the trace.
3. If `stop_score_bias + stop_score_weights . features > 0`, the trace ends there with reason `stop_score`. Main villa's later width checks run after it; the stop reason wins.
4. With `sheet_plane_weight` above 0, each candidate direction's loss gains `weight * asin(|n . d|)^2` from the lasagna normal at that point. Turning on only this weight switches the tracer to normal-aware smoothness; villa's defaults already use it, so default use is unchanged.

The tested weights come from a class-weighted logistic regression of "a failure follows within 150 base voxels" on 87,959 trace points of 30 PHerc0139 development fibers (1,583 positives); the bias was then set to add about 160 stops per million voxels there.

## Cost and time

Not measured separately: the stop score adds a few presence look-ups per step to a tracer that already samples presence many times per step. The tests ran villa's tracer as CPU jobs on Hugging Face (fiber tracing) and one GPU job set for `fiber_tracer_large`; their wall times are per test, not per trace, and are not quoted here.

## For agents

- **Command:** `python3 -m vc.fiber_evaluation CONFIG.json RESULT.json` on a villa build of both PR branches, with `sheet_plane_weight` 0.75, `stop_score_weights` [-3.337961978038475, -38.37888728031481, 3.2607291950806836] and `stop_score_bias` 35.39635373347652 in the config's `trace` block and `backend` `beam`.
- **Parse:** RESULT.json's segments and failures; count segments with termination reason `stop_score_filtered`, and failures per retained voxel against a stock run on the same fibers.
- **Rerun:** Safe; villa overwrites RESULT.json and reuses its cache.
- **Success:** villa exits 0 and RESULT.json has segments; the stop score is active when some segments end `stop_score_filtered`.
- **Not a pass:** fewer failures with no matched control (a presence cutoff that stops as often, or the same traces cut at random points); a gain on fibers the weights were fit on; a gain on a scroll whose fibers trained the prediction, reported as if the scroll were new; a sheet-plane gain on beam-drawn reference lines alone.
- **Go-ahead:** Nothing to run it. Posting on the villa PRs needs Chase's yes.
- **Never:** call a fiber trace a reading of text; enable either setting in the chunk tracer; quote the PHerc0139 numbers as held out, since every weight was fit there.

## Tests

In villa, after building with `VC_TESTING=ON`: `test_fiber_trace3d` (stop score off by default and validated, the three features, a stop before a step whose score is positive; sheet-plane weight off by default, a synthetic drift case where stock drifts 11.8 voxels off the sheet over 64 and weight 8 drifts 1.4, explicit 0 identical to defaults, an in-sheet turn unchanged at weight 100, invalid weights rejected), `test_fiber_reference_replay_core` (a stop score stop is a filtered stop), and Python `test_fiber_trace.py` and `test_fiber_evaluation.py` (config round trips, features, replay filtering, chunk refusal). Not covered: the merged tree of both branches, which was not built for this page; held-out accuracy, which only the tests in Checks and controls measure.

## History

- 2026-11-05: page written for the public record of the two villa PRs and the 84-fiber PHerc1451 test of 3 Nov 2026, the update to [villa #2377](https://github.com/ScrollPrize/villa/pull/2377).
- 2026-11-04: [villa #2265](https://github.com/ScrollPrize/villa/pull/2265) merged villa `main` `f7756c758`; chunk tracing now refuses `sheet_plane_weight`.
- 2026-10-30: [villa #2377](https://github.com/ScrollPrize/villa/pull/2377) opened as a draft (stop score).
- 2026-10-23: [villa #2265](https://github.com/ScrollPrize/villa/pull/2265) opened as a draft (sheet-plane weight), with issue [#2264](https://github.com/ScrollPrize/villa/issues/2264) on beam-drawn reference lines.

## Related

- [afv-fibers](afv-fibers.md): fiber curves for six scans and a catalog of every public fiber set, including the annotators' fibers these tests used.
- [fibercheck](fibercheck.md): checks whether fibers show on a traced surface; a different question from where a fiber trace should stop.
- [fibers](fibers.md): streams the AFV fibers of one box of a scan.
- villa's `volume-cartographer/docs/fiber_evaluation.md`: the evaluation config and scoring these numbers use.
