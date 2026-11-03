# altrain: does fine-tuning on suggested tiles beat random tiles?

`python -m kit altrain` lays out a simulated labeling round on one segment with real ink labels (test blocks and a pool of tiles), picks tiles by a label suggester, uncertainty or chance, and judges the fine-tuned readers' test AUC with a paired bootstrap and fixed controls.

| Field | Value |
| --- | --- |
| Id | `altrain` |
| Status | Experimental |
| Kind | kit command,kit module |
| Area | Training |
| Run | `python -m kit altrain plan`, `python -m kit altrain readout` |
| Code | `kit/altrain.py` |
| Tests | `tests/test_altrain.py` |
| Needs | Python 3 (run here with 3.13), numpy. The fine-tunes themselves need a GPU worker of your own (torch, villa's `vesuvius` package and the released `scrollprize/ink_9um` checkpoints) that writes one `runs/ID.npz` per run |
| Runs on | `plan` and `readout`: any CPU, about 1 s for `plan` on a 1024 x 1536 mask and 17 s for `readout` of two synthetic segments with 2000 bootstrap draws (measured 2026-11-03, 4-core cloud container). The fine-tunes: one rtx-pro-6000 Hugging Face Job per segment (see Cost and time) |
| Network | None |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-11-03 |
| Checked | 2026-11-03 against commit `043bbbd` |

## What it does

The Vesuvius Challenge open problems list active learning: let a model point at the regions where a person's label would help most. Our `kit labelsuggest` picks such tiles, and its earlier tests showed that its picks hold more of a committee's mistakes than random tiles. A villa maintainer asked for more: a training run comparison, which shows that a model trained on the suggested tiles ends up better than one trained on random tiles.

`altrain` is the rule of that comparison. On one segment with real ink labels (an "oracle": the labels exist already, but an arm may only use those of the tiles it picked), a fixed layout splits the labeled area into test blocks, never trained on, and a pool of 64 px tiles kept one tile away from every test block. For each budget (5, 10 and 20 % of the pool) four arms pick k tiles: SUGGEST (the top tiles by labelsuggest's label-free ink-edge measure on the base readers' maps), UNCERTAIN (the top tiles by mean entropy of one reader's ink probability), RANDOM (five random sets) and SHUF (the SUGGEST scores shuffled across the pool, a control). The same base reader is fine-tuned on each arm's tiles (three seeds; RANDOM's five sets), and every fine-tuned reader maps the test blocks forward and with reversed depth.

`readout` turns the per-block score histograms into each arm's mean test AUC and a paired hierarchical bootstrap of the differences (test blocks resampled together for every arm, runs within each arm). A segment counts only when its controls hold; the verdict needs SUGGEST minus RANDOM's lower bound above 0 at two of three budgets on two counted segments.

A suggested tile is a place to label, never a reading; every map is a model's output. A PASS here says nothing about a person's labeling time: the labels were drawn already.

## When to use it

- To test whether a tile-picking rule helps a fine-tune more than random tiles on segments with real labels, with controls that can fail.
- To lay out a segment for such a test (`plan`) before any map or fine-tune exists.

Do not use it:

- To pick tiles for a person to label: use `kit labelsuggest map` and `export` ([labelsuggest](labelsuggest.md)).
- To score one reader against labels: use `kit auc` with the reverse-depth control ([auc](auc.md)).
- On a segment the base reader trained on: its labels are already in the network, so the arms cannot differ for a reason that matters.

## Quick start

Run from the repository root. The first block writes a 1024 x 1536 supervision mask and the records of two synthetic segments on which SUGGEST was planted better than the other arms; no network, no GPU.

```bash
export D=/tmp/altrain-demo
python3 - <<'EOF'
import json, os
from pathlib import Path
import numpy as np
from tests import test_altrain as T
d = Path(os.environ["D"]); d.mkdir(parents=True, exist_ok=True)
np.save(d / "sup.npy", np.ones((1024, 1536), bool))
for name, seed in (("a", 1), ("b", 2)):
    ids, f, r = T.synth_segment(T.Readout.SEPS, seed=seed)
    s = d / "results" / name; (s / "runs").mkdir(parents=True)
    (s / "plan.json").write_text(json.dumps({"segment": name, "runs": [{"id": i} for i in ids]}))
    (s / "base.json").write_text(json.dumps(T.BASE))
    for i in ids:
        np.savez(s / "runs" / f"{i}.npz", fwd=f[i], rev=r[i])
EOF
python3 -m kit altrain plan "$D/sup.npy"
python3 -m kit altrain readout "$D/results"

# Real use
python3 -m kit altrain plan SUP.npy --foot FOOT.npy --json
python3 -m kit altrain readout RESULTS --json
```

- `SUP.npy`, `FOOT.npy`: a segment's supervision mask and CT footprint on the map grid.
- `RESULTS`: one folder per segment holding the worker's plan.json, base.json and runs/*.npz.

On 2026-11-03 it printed:

```
156 pool tiles, 8 test blocks, budgets {'0.05': 8, '0.10': 16, '0.20': 31}
a: COUNTED
  budget 0.05: SUGGEST 0.8569 RANDOM 0.7621 diff +0.0948 (lower +0.0866)
  ...
verdict PASS: counted ['a', 'b'], passing ['a', 'b']
```

It worked when `readout` exits 0 and prints a verdict; on these planted records the verdict is PASS.

## Checks and controls

Each control makes its segment VOID (not counted) and each fails a synthetic segment in `tests/test_altrain.py`:

- **Reverse depth:** every arm's mean reverse-depth AUC at every budget at or below `REV_MAX` 0.55 (a planted reverse separation of 25 on the 0 to 255 scale, AUC about 0.72, voids the segment).
- **Shuffled suggestions equal RANDOM:** SHUF minus RANDOM averaged over budgets, its 99 % bootstrap interval must hold 0 (a SHUF arm planted better voids the segment).
- **Labels track the CT:** the base reader's test AUC with labels in place beats the map moved 32 px by at least 0.05.
- **Differential reverse depth (claim guard):** a budget counts only when SUGGEST minus RANDOM's forward lower bound is above 0 and the gain is larger forward than with reversed depth (lower bound of the difference above 0); a gain planted equally in both directions does not count.
- **Records:** a missing base record is INCOMPLETE, never counted; the readout wants exactly the expected segments and each plan's sha256 as its base record names it.
- **Size:** at least 100 pool tiles and 12 test blocks.
- **Layout:** `disjoint` is false when a pool tile touches a test block (a test moves one in), and the worker refuses such a layout.
- **The arms differ only by their picks:** equal arms give FAIL in tests, a planted better SUGGEST gives PASS.

**The fragment benchmark** (3 Nov 2026, preregistered and frozen before any fine-tune, each fragment read once; numbers in `docs/results.json`, `label_suggest_checks`): on Frag2, Frag3 and Frag4, ink_9um seed 42 fine-tuned on the edge measure's tiles did **not** beat random tiles at any budget (no lower bound above 0), and at 5 % it was below random on Frag3 and Frag4 (about -0.10 AUC). The readout is **VOID** by its rule: only Frag4 counted; Frag2 and Frag3 failed the displaced-label control, and Frag2's arms also crossed the 0.55 reverse-depth bar. One base reader, one short recipe, exposed fragment surfaces only.

Claim label: Model output for any map; Measurement for numbers from a run; that suggested tiles beat random ones in a fine-tune is not shown (the preregistered test was VOID and no budget favored SUGGEST).

## Commands and options

### `python -m kit altrain plan`

```
usage: python -m kit altrain plan [-h] [--foot FOOT] [--json] sup
```

| Option | Default | Meaning |
| --- | --- | --- |
| `sup` | required | supervision mask .npy (nonzero = labeled) |
| `--foot FOOT` | none | CT footprint mask .npy (default: the supervision mask) |
| `--json` | off | print the whole record as JSON |

### `python -m kit altrain readout`

```
usage: python -m kit altrain readout [-h] [--nboot NBOOT]
                                     [--segments SEGMENTS [SEGMENTS ...]]
                                     [--json]
                                     root
```

| Option | Default | Meaning |
| --- | --- | --- |
| `root` | required | a results folder: one subfolder per segment (plan.json, base.json, runs/*.npz) |
| `--nboot NBOOT` | `2000` | bootstrap draws (the preregistered readout uses the default) |
| `--segments SEGMENTS ...` | `frag2 frag3 frag4` | the segments the results folder must hold; a missing one makes the verdict INCOMPLETE, any other is refused |
| `--json` | off | print the whole record as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `ALError()` | exception |  | bad input; the message says why |
| `constants()` | dict | none | The rule's constants, as one dict (hashed into every record). |
| `constants_sha256()` | str | none | SHA-256 of `constants()` as sorted JSON |
| `layout(sup, foot=None)` | dict: shape, test_blocks, pool, test_mask | ALError | The fixed spatial layout of one segment from its supervision mask (and CT footprint). |
| `pool_mask(shape, tiles)` | bool array | none | True inside the given 64 px tiles |
| `disjoint(lay)` | bool | none | True when no pool tile pixel lies in, or within GUARD tiles of, a test block (a checkable invariant). |
| `edge_map(maps, valid, cut=CUT)` | float32 array (0 or 1) | none | kit labelsuggest's `edge` measure: 1 where the committee call (mean probability at or above cut) differs from a valid 4-neighbor |
| `entropy_map(p, eps=1e-06)` | float32 array | none | Binary entropy (nats) of an ink probability map. |
| `tile_means(arr, valid, tiles)` | float64 array | none | Mean of arr over each tile's valid pixels (0 for a tile with none). |
| `k_of(n_pool, frac)` | int | none | tiles revealed at a budget: round(frac x pool), at least 1 |
| `top_k(scores, k, rng)` | sorted list of int | none | Indices of the k highest scores, ties broken at random by rng (a fixed order would pick by position). |
| `selections(edge_scores, ent_scores, budgets=BUDGETS, seed=PICK_SEED)` | dict per budget | ALError | Per budget: SUGGEST and UNCERTAIN (one tile set each), RANDOM (RANDOM_DRAWS sets), SHUF (SHUF_DRAWS sets), as pool indices |
| `runs(sel)` | list of dict | none | Every fine-tune of a segment: dict(id, budget, arm, draw, seed, tiles) from selections(). |
| `to_u8(p)` | uint8 array | none | probabilities 0..1 to 0..255, rounded |
| `block_hists(prob_u8, ink, sup, blocks, side=BLOCK)` | int64 array (n_blocks, 2, 256) | none | per test block, the counts of background (0) and ink (1) supervised pixels per uint8 score |
| `auc_counts(c)` | float array | none | AUC from counts (..., 2, BINS): P(ink score > background score) + half the ties; nan without both classes. |
| `auc_direct(score, ink, mask)` | float | none | Rank AUC on the masked pixels (ties half): the reference auc_counts must equal on uint8 scores. |
| `boot_arm_means(hists, nboot=NBOOT, seed=BOOT_SEED)` | (dict of draws, dict of point estimates) | ALError | Paired hierarchical bootstrap: each draw resamples the test blocks (shared by every arm) and each arm's runs |
| `diff(boot, point, a, b, lower_q=LOWER_Q)` | dict: est, lower, upper | none | a minus b, point estimate and the bootstrap's 2.5th and 97.5th percentiles |
| `segment_readout(seg, fwd, rev, base=None, expected=None, nboot=NBOOT, seed=BOOT_SEED)` | dict | ALError | One segment: per budget the arm means and differences, the controls, whether it counts and passes |
| `verdict(segments)` | dict: verdict, counted, passing | none | PASS, FAIL, VOID or INCOMPLETE by the rule in How it works |
| `load_results(root)` | list of tuples | none | A results folder: one subfolder per segment with base.json, plan.json and runs/<id>.npz (fwd, rev). |
| `readout(root, nboot=NBOOT)` | dict | ALError | every segment's readout and the verdict, with `constants_sha256` |
| `cmd_plan(a)` | exit code | none | `kit altrain plan` |
| `cmd_readout(a)` | exit code | none | `kit altrain readout` |
| `build_parser(p)` | None | none | adds plan and readout to an argparse parser |
| `cmd_altrain(a)` | exit code | none | 0 done, 2 an error |
| `main(argv=None)` | exit code | none | `python -m kit.altrain` |

## Inputs

- `plan`: a supervision mask (.npy, 2D, nonzero = labeled) on the map grid, and optionally the CT footprint on the same grid.
- `readout`: a folder with one subfolder per segment: `plan.json` (`segment`, `runs[].id`), `base.json` (`n_pool`, `n_test_blocks`, `auc_inplace`, `auc_displaced`) and `runs/ID.npz` with arrays `fwd` and `rev`, each (test blocks, 2, 256) int64 counts of background and ink supervised pixels per uint8 score. Run ids read `bBUDGET-ARM-dDRAW-sSEED`, as `runs()` writes them.

## Outputs

`plan` prints the pool and test counts and k per budget (`--json`: also `test_pixels`, `disjoint`, `constants_sha256`). `readout` prints per segment its state and per budget SUGGEST, RANDOM and their difference with its lower bound, then the verdict; `--json` prints the whole record:

| Field | Type | Meaning |
| --- | --- | --- |
| `verdict` | str | PASS, FAIL, VOID or INCOMPLETE |
| `counted`, `passing` | list | segments whose controls held; those passing at two or more budgets |
| `segments[].budgets[B].auc`, `rev_auc` | object | each arm's mean test AUC forward and with reversed depth |
| `segments[].budgets[B].SUGGEST-RANDOM` | object | `est`, `lower`, `upper` (also UNCERTAIN-RANDOM, SUGGEST-UNCERTAIN, SHUF-RANDOM, SUGGEST-RANDOM_reverse) |
| `segments[].budgets[B].forward_minus_reverse_gain` | object | `est`, `lower`: the claim guard |
| `segments[].budgets[B].revealed_ink_px`, `revealed_ink_ratio_suggest_random` | object, float | each arm's mean revealed ink pixels; SUGGEST's over RANDOM's |
| `nboot_frozen`, `frozen_segment_set` | bool | whether this is the preregistered readout |
| `segments[].shuffle_control` | object | pooled SHUF minus RANDOM, its 99 % interval, `holds` |
| `segments[].void_why` | list | why a segment is VOID |
| `constants_sha256` | str | the rule's constants |

| Exit code | Meaning |
| --- | --- |
| `0` | printed (any verdict) |
| `2` | an input problem: the message on stderr says which |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `the supervision mask must be 2D` | the mask file holds a stack or a vector | pass the 2D mask on the map grid |
| `footprint ... and supervision ... differ` | the footprint and the supervision mask differ in shape | put both on the map grid |
| `edge and entropy scores differ in length` | the two score lists were computed on different pool lists | compute both from `layout()`'s pool |
| `arms were scored on different test blocks` | runs of one segment have histograms of different block counts | rerun the runs on the plan's test blocks |
| `kit altrain needs numpy` | numpy missing | install numpy |
| `: segment ... is not one of` | a results subfolder holds another segment (the smoke's Frag1, say) | keep only the test segments' folders, or pass `--segments` |
| `: a second folder for segment` | two folders hold one segment | keep one |
| `: plan.json differs from the plan base.json was made with` | plan.json changed after the base checks | fetch the records again; never edit them |
| a segment `INCOMPLETE` | runs listed in plan.json have no npz yet | finish them (the worker skips finished runs) before any readout counts |

## How it works

1. Layout (`layout`): 256 px blocks with (by + bx) mod 3 = 0 and at least 25 % supervised are test blocks; 64 px tiles with at least 50 % supervised and footprint, outside every pattern block and more than one tile from one, form the pool.
2. Picks (`selections`, seed `PICK_SEED` 20261104): SUGGEST, the top k pool tiles by mean `edge_map` of the base readers' probabilities (cut 0.5, labelsuggest's default); UNCERTAIN, the top k by mean `entropy_map` of one reader; RANDOM, five random sets; SHUF, the top k of three permutations of the SUGGEST scores. Ties are broken at random. k = round(budget x pool) for budgets 0.05, 0.10 and 0.20.
3. The worker fine-tunes the base reader on each run's revealed tiles (loss masked to them) and maps the test blocks forward and reversed; it stores per-block histograms of uint8 scores.
4. AUC from histograms (`auc_counts`): for each bin, ink counts times (background below plus half the background in the bin), over ink times background totals; equal to the rank AUC with ties counted half.
5. Bootstrap (`boot_arm_means`, 2000 draws, seed 20261103): block weights from resampling the test blocks, shared by every arm; within each arm its runs resampled; each draw's arm mean AUC. The lower bound is the 2.5th percentile of SUGGEST minus RANDOM.
6. Readout (`segment_readout`, `verdict`): the controls of Checks and controls; PASS with two counted segments each passing at two or more of three budgets.

## Cost and time

`plan` and `readout` are local and quick (Runs on). The fragment benchmark's fine-tunes ran on one RTX PRO 6000 GPU per fragment: a 300-step fine-tune of ink_9um (window 17 x 128 x 128, batch 8) took 17 s alone, and 42 runs in 3 lanes took 9 to 15 minutes per fragment (measured 2026-11-03).

## For agents

- **Command:** `python -m kit altrain plan SUP.npy --foot FOOT.npy --json`; after the worker's Jobs, `python -m kit altrain readout RESULTS --json`
- **Parse:** `plan`: `pool_tiles`, `test_blocks`, `disjoint`, `k`; `readout`: `verdict`, `counted`, `passing`, and per segment `budgets[B]["SUGGEST-RANDOM"]["lower"]` and `void_why`
- **Rerun:** safe: both only read and print
- **Success:** exit 0 and a verdict; PASS only with two counted segments
- **Not a pass:** a lower bound above 0 on a VOID segment; INCOMPLETE; any number from a segment the base reader trained on; a readout computed before every run of the plan exists
- **Go-ahead:** Nothing
- **Never:** call a suggested tile or a map a reading; tune the recipe or the picks on a test segment; read a readout before every run exists and then add runs

## Tests

`python3 -m unittest tests.test_altrain` (21 tests, about 2 minutes): the layout and its disjointness (and a moved tile failing it), the edge measure equal to `kit labelsuggest`'s, the picks' sizes, top-k and random ties, histogram AUC equal to the rank AUC, the bootstrap covering 0 for equal arms and not for a better one, PASS, FAIL, every VOID control (absolute and differential reverse depth, shuffled suggestions, displaced labels, size), INCOMPLETE without a run or a base record, and the file readout's segment-set and plan-hash refusals. Not covered: a GPU worker.

## History

- 2026-11-03: first public version, with the fragment benchmark (VOID; SUGGEST not shown to beat random); built on `043bbbd`.

## Related

- [labelsuggest](labelsuggest.md): the suggester whose edge measure SUGGEST uses.
- [auc](auc.md): scoring a single map with the reverse-depth control.
- `docs/results.json`, `label_suggest_checks`: the fragment benchmark's numbers.
- villa PR #2381 (https://github.com/ScrollPrize/villa/pull/2381): the maintainer's request for a training run comparison.
